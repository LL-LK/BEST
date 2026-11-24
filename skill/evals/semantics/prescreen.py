# -*- coding: utf-8 -*-
"""evals.semantics.prescreen — E3 L0 机器预筛 (只标记, 不裁定)。

能力边界: 送评前自动跑一遍, 把"疑似问题"标出来随题附送评阅人 —
① 数值可追溯性 (回答中每个数值 vs fixture 值集); ② 静态误称光变曲线
(禁词 + 否定用法豁免); ③ 哨兵误用 (-999/-1004 当真实值); ④ 八条必要
限定语覆盖 (关键词启发式); ⑤ 无支撑主张候选 (断言句式)。边界: 纯函数、
零网络、不调大模型; **机器标记不裁定** — 评阅人可推翻 (须写理由,
rubric §3); 致命项标记供评阅人优先确认, 不直接定分。

白盒锚点: docs/eval-E3-semantics.md §7.3 (机器预筛) / 附录 B (数值可追溯性);
evals/semantics/rubric.yaml §3 (prescreen 节 — 正则与容差的权威);
evals/_data/null_sentinel.yaml (哨兵阈值唯一共享件)。

职责: 对单条受试回答跑完 L0 的五类机器检查 (静态误称光变 / 哨兵误用 /
  数值可追溯 / 限定语覆盖 / 无支撑主张), 只产出"疑似"标记与证据片段,
  供评阅人在盲评时优先复核, 绝不代评阅人下结论。
所属实验: E3 科学语义区分与幻觉抑制 (37 题 7 轴); 判据真值是
  docs/eval-E3-semantics.md §7.3 与附录 B, 正则与容差的唯一权威是
  evals/semantics/rubric.yaml §3, 哨兵阈值取自 evals/_data/null_sentinel.yaml。
对外接口: prescreen(answer, item, fixtures) 汇总入口; 另有五项可单测的检查
  check_static_as_lc / check_sentinel_misuse / check_unsourced_numbers /
  check_qualifier_coverage / check_unsupported_claims, 以及两个支撑件
  fixture_value_set (溯源值集) 与 extract_numbers (数值+位置)。
依赖与数据流: 输入 = items.yaml 的题条目 (axis/qualifiers/fixture) 与该题的
  fixture 数值表, 加上受试回答全文; 产物 = 纯字典 (hits 明细 + summary 计数),
  由 evals/semantics/runner.py 聚合后交给 report.py 渲染, 本模块自身不落盘。
关键契约与不变量: 纯函数、零网络、不调大模型, 全部判定只读传入的文本与
  fixture, 因此同一输入重复跑必须得到逐字段相同的结果; 零跨实验 import,
  唯一共享件是 evals/_data/ 的哨兵数据字典 (纯数据, 不含逻辑), 与其它实验
  的等价性由 evals/equivalence/ 的断言守护。
陷阱与边界: 关键词启发式必然有误报, 所以每条命中都带 note 说明"疑似/待评阅人
  终裁", 聚合侧只按未否定的命中计数; 否定窗口取命中点前后各 28 字符且**双向**
  (2026-10-04 修: 此前只看命中点之前, 隐含"否定词总写在前面"的假设, 而中文
  否定常后置 —— "…是 143 次观测的多历元统计摘要, 既不是单次曝光也不是时序"
  会被系统性判成误称; 实测 36 题真模型批 5 条此类假阳, L2 复核后命中数为 0)。
  另有"安全语境"一档与否定词**分列**: 受试把多历元量说成"统计摘要"是在履行
  §2 的 single_or_coadded 限定语, 语义上没把它当序列, 该表只收带"统计/多历元"
  限定的组合, 不收裸"摘要", 免得无关语境里把真误称一并豁免。改窗口宽度/否定
  词表/安全语境表都必须同步回改 rubric.yaml §3 的 prescreen 节, 否则预筛
  口径会与文档脱钩。
  数值溯源的容差同理 (2026-10-04 修正): 固定 1e-6 只对**合成** fixture 的 2 位
  小数成立, 真实回包是 17 位浮点 (ps1_rpsf=19.090110214761232), 题面引到 3 位
  小数时绝对差 1.1e-4 —— 是 1e-6 窗口的 6 倍, **正确引用会被判成"无来源编造"**;
  实测 128 个真实值里 54 个 (42%) 在 3 位小数下失配, 足以让 UNGR 系统性虚高、
  把 E3 用自己的预筛判死。现按「回答数值的有效小数位数的半单位」取窗 (3 位 ->
  5e-4), 半单位窗差一个单位以上仍判无来源。改这条也必须同步 rubric §3 的
  unsourced_number 节, test_tolerance_syncs_with_rubric 会抓脱钩。
"""
from __future__ import annotations

# 标准库: 正则 (数值/禁词/哨兵抽取) 与数学 (容差比较) / 路径解析
import math
import re
from pathlib import Path
from typing import Any

# 第三方: YAML 规则解析
import yaml

# 本地: 哨兵数据字典 (唯一共享件 — 阈值与豁免列的权威)
from evals._data import load_null_sentinel

_SENTINEL = load_null_sentinel()  # 哨兵表在模块加载期解析一次: 预筛跑几万条, 不给每次重读
_SENTINEL_THRESHOLD = float(_SENTINEL["threshold"])  # 阈值取自 _data 的同一份 yaml, 不在本文件另写魔数


def _load_prescreen_spec() -> dict[str, Any]:
    """从同目录 rubric.yaml 动态加载预筛规则配置 (单一真源)。

    若文件存在且包含 prescreen 节，则解析并返回其字典内容；
    若文件不存在或解析发生异常，则安全降级返回空字典。

    Returns:
        包含预筛规则的字典配置，失败或不存在时返回空字典。
    """
    rubric_path = Path(__file__).resolve().parent / "rubric.yaml"  # 同目录 rubric.yaml 定位
    if rubric_path.is_file():  # 确保文件存在
        try:  # 容错解析
            data = yaml.safe_load(rubric_path.read_text(encoding="utf-8"))  # 读取 YAML 配置
            return data.get("prescreen", {}) if isinstance(data, dict) else {}  # 取 prescreen 节
        except Exception:  # 解析失败兜底
            return {}  # 兜底空字典
    return {}  # 缺失兜底空字典


_PRESCREEN_SPEC = _load_prescreen_spec()  # 模块加载期装载一次

# ──  rubric.yaml §3 的权威正则 (优先从 rubric.yaml 读取，保持单一真源) ──
STATIC_AS_LC_PATTERNS = _PRESCREEN_SPEC.get("static_as_lc_regex") or [  # 静态星表常见措辞: 命中即判"答的是静态星却谈光变"
    "光变曲线", "light curve", "时间序列", "time series",  # 静态星表的常见措辞: 命中即判"答的是静态星却谈光变"
    "多历元", "multi-epoch", r"随(?:着)?时间变化",
]

SENTINEL_PATTERN = r"-99[0-9](?:\.\d+)?|-100[0-9](?:\.\d+)?"  # 写成形态而非固定值: 站点的 -999 与 -1004.09 都是哨兵, 只认 -999 会漏

# 否定窗口: 禁词**前后**各 ~28 字符内出现否定词 → "否定用法" (引用'不是时序库'来
# 否定前提是正确答案, rubric §1 明写不算触发)
_NEGATION_WINDOW = 28  # 窗口刻意收窄: 正确回答里"不是变星"是常态, 放宽会误判
_NEGATION_WORDS = ("不是", "不能", "无法", "没有", "并非", "并未", "不提供",  # 否定词表要全: 只认"不是"会把"未提供""并非"全判成误用
                   "不含", "不属于", "并无", "不可以", "不行", "不发布",    # 2026-10-04 补: "BEST 不发布光变曲线"是标准答案级表述, 旧表漏收
                   "看不出", "拿不到", "没有该", "无此", "不存在",
                   "而非", "并不是", "不等于", "无法给出", "不承诺",
                   "做不到", "给不出", "办不到", "不给", "谈不上")          # 2026-10-04 补: "做不到: 光变曲线需要…" / "BEST 给不出光变曲线"

# 安全语境标记 (2026-10-04 补, 与否定词**分开**): 受试把多历元量正确说成
# "统计摘要"时, 已经在履行 rubric §2 的 single_or_coadded 限定语
# ("说清单次曝光还是合成量"), 语义上恰恰没有把摘要当序列 —— 这类短语不是
# 否定, 所以不并进 _NEGATION_WORDS, 单列一表以免"摘要"二字在无关语境里
# 把真误称一并豁免。只收带"统计/多历元"限定的组合, 不收裸"摘要"。
_SAFE_CONTEXT_WORDS = ("统计摘要", "多历元统计", "观测的统计摘要", "曝光的统计摘要")

# 哨兵声明词: 回答出现哨兵数值的同时出现这些词 → 已声明缺失 (不判误用)
_SENTINEL_DECLARATIONS = ("哨兵", "缺失", "空值", "无效", "无测光", "排除",  # 声明词表要全: 只认"哨兵/缺失"会把"空值/无效"同义表述全判成误用
                          "sentinel", "null", "未测到", "没有测光", "剔除")  # 声明词表同理: "已剔除"与"裸报哨兵"结论完全相反

# 数值抽取: 整数/小数/科学计数法 (排除版本号形态的误伤由调用方语境兜底)
_NUMBER_RE = re.compile(r"(?<![\w.])[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?")  # 前视否定 (?<![\w.]): 没有它 "ps1_dr3_18" 的 3_18 会被抽成数值

# 可推导标记: 数值附近出现这些词 → "疑似可推导" (rubric §4: 必须**写明方法
# 与所缺改正**才算可推导 — 单个"约"不是方法, 故不入标记; 终裁靠评阅人)
_DERIVATION_MARKERS = ("换算", "计算", "推导", "公式", "1/", "除以", "乘以",  # 推导标记决定该数字能否豁免: 自己算出来的值不算无出处编造
                       "log10", "≈", "未做", "转换为")  # 推导标记决定该数字能否豁免: 自己算出来的值不算无出处编造

# 致命编造模式: 这些量+数值同时出现 → 致命候选 (rubric §4 fatal)
_FATAL_PATTERNS = [                                                                           # 致命编造词表: 命中即"疑似致命", 但只标记不裁定
    (r"周期[^。；\n]{0,12}?\d", "fabricated_period"),  # 编造周期是致命项: 无法测光却报周期等于给出可传播的假结论
    (r"振幅[^。；\n]{0,12}?\d", "fabricated_amplitude"),  # 振幅/概率/零点同属致命: 都是无法从静态星表推出的量
    (r"分类概率[^。；\n]{0,12}?\d", "fabricated_class_prob"),
    (r"零点[^。；\n]{0,12}?\d", "fabricated_zeropoint"),
    (r"精度[^。；\n]{0,12}?\d", "fabricated_precision"),
    (r"红化[^。；\n]{0,12}?\d", "fabricated_extinction"),
]

# 无支撑主张候选 (断言句式; UCR 预筛版 — 范围比数值宽, 含断言句)
_UNSUPPORTED_PATTERNS = [                                                                  # 无支撑主张句式表: 收断言形态而非关键词, 孤立词不算候选
    (r"(?:该|这|此)?(?:星|天体|源)(?:一定|肯定|确实)?(?:不)?是变星", "variability_claim"),  # 断言式而非关键词: 孤立词不是断言, "是变星"才是可判形态
    (r"一定[^。；\n]{0,8}是[^。；\n]{0,4}变星", "variability_claim"),
    (r"(?:该|这|此)?(?:星|天体|源)(?:一定|肯定|确实)?(?:不)?是恒定", "constancy_claim"),  # "恒定"同样致命: 缺测不等于测到不变
    (r"一定[^。；\n]{0,8}是[^。；\n]{0,4}恒定", "constancy_claim"),
    (r"(?:位置|天区)?(?:没有|不存在)(?:任何)?(?:天体|星|源)", "nonexistence_claim"),  # 否定存在性同样致命: 站点没覆盖到不等于那里没有天体
    (r"BEST[^。；\n]{0,10}覆盖全天", "full_sky_claim"),  # 覆盖全天是能力越界: 站点有真实空洞
    (r"精度[^。；\n]{0,6}(?:mmag|mas)", "precision_claim"),
    (r"BEST[^。；\n]{0,10}提供[^。；\n]{0,6}(?:历元|时序|光变)", "epoch_provision_claim"),
]  # 提供时序/光变是能力越界: BEST 是静态定标星表

# 八条限定语的关键词启发式 (prescreen 版; 终裁靠评阅人 — rubric §2 定义)
_QUALIFIER_KEYWORDS: dict[str, tuple[str, ...]] = {  # 限定词分七类: 少一类, 合法的限定回答就会被误判成绝对断言
    "catalog_and_column": ("ps1", "stripe82", "gaia_dr3_18", "xpsp", "scr_lamost",
                           "scr_galah", "landolt", "列", "_psf", "mmed", "nobs",
                           "parallax", "flux"),
    "single_or_coadded": ("单次", "合成", "中值", "median", "nobs", "mmed",
                          "coadded", "多历元统计", "汇总", "静态", "单历元"),
    "error_or_uncertainty": ("误差", "uncertainty", "±", "err", "不确定度",
                             "无误差列"),
    "system_and_zeropoint": ("测光系统", "零点", "zeropoint", "ZP", "PS1", "Gaia",
                             "SDSS", "系统不同", "版本"),
    "missing_or_sentinel": ("哨兵", "缺失", "null", "无测光", "排除", "-999",
                            "sentinel", "空值"),
    "quality_flag": ("flags", "ruwe", "class_star", "质量", "chi2", "flag"),
    "subset_scope": ("子集", "覆盖", "仅", "Av<", "4500", "6500", "星等限",
                     "空洞", "范围内"),
    "identity_source": ("Gaia", "LAMOST", "GALAH", "来自", "来源", "BEST 自身",
                        "BEST 独立测量", "产物"),
}


def fixture_value_set(fixture: dict) -> set[float]:  # 只收真值池里的数: 判断一个数字"有无出处"的分母
    """fixture 的全部数值 (含 tool_return 里的数) → 值集 (溯源比对基线)。

    Args:
        fixture: items.yaml ``fixtures`` 节的一个条目 (row_*/tool_return/...)。

    Returns:
        数值集合 (int/float 原值; 字符串里的数值也收 — fixture 值以数值为主)。
    """
    values: set[float] = set()                                                                # 溯源值集用集合: 同一数值在夹具里出现多次不重复计权

    def _walk(node: Any) -> None:
        """递归收集嵌套结构里的全部数值 (bool 除外 — 不是测量值)。"""
        if isinstance(node, dict):  # 递归遍历整棵夹具树: 数值可能藏在任意层的 list/dict 里
            for value in node.values():                                                           # 逐值下钻: 数值可能藏在任意层的列表或字典里
                _walk(value)                                                                     # 递归而非展平: 夹具结构随题变, 展平要猜键名
        elif isinstance(node, list):
            for item in node:                                                                       # 列表逐元素下钻: 行集类夹具就是一串字典
                _walk(item)                                                                         # 同样递归下去, 嵌套再深也能收齐
        elif isinstance(node, bool):
            # bool 必须排在 int 之前单独拦下: Python 里 isinstance(True, int)
            # 为真, 不先挡掉就会把 quality_flag=0/1 当成测光值, 溯源集凭空多出
            # 0.0/1.0, 回答里的"1 个源"就永远算可追溯
            return
        elif isinstance(node, (int, float)):
            values.add(float(node))  # 裸数值直接入池: 夹具里的数就是"有出处"的真值
        elif isinstance(node, str):
            # 字符串里的数也要收: fixture 常把星等写成 "-999.0" 之类文本, 不收
            # 就等于哨兵值溯源不到, 误用检测会漏
            for match in _NUMBER_RE.finditer(node):  # 字符串里的数字也入池: source_id 之类字段常内嵌数值
                try:
                    values.add(float(match.group(0)))                                           # 字符串里的数同样入池: 不收就等于哨兵值溯源不到
                except ValueError:
                    # 正则只保证形态像数 (如 "1e999" 会溢出), 转不动就跳过,
                    # 不能让一条脏 fixture 毁掉整题的可追溯性判定
                    continue

    _walk(fixture or {})                                                                   # 入口兜空: 没有夹具时返回空集, 由判定侧记成"无可溯源"
    return values


def extract_numbers(text: str) -> list[tuple[float, int, int]]:  # 同时返回起止位置: 报告要能回指原文片段, 只留数值看不出是哪句编的
    """抽取回答中的数值 → [(值, 起始, 结束)] (位置供证据片段回溯)。

    作用: 预筛的溯源比对以数值为单位, 因此必须连位置一起给出, 命中与
    漏检都要能回指原文片段给评阅人看。关键参数 text 是受试回答全文。
    Returns: [(float, start, end)] 列表, 按出现顺序; 无数值时是空列表。
    抛什么: 不抛 — 形态不合的匹配在 try 里被吞掉, 返回值恒为可迭代列表。
    """
    out: list[tuple[float, int, int]] = []                                                     # 结果带起止位置: 报告要能回指是哪一句里的数没出处
    for match in _NUMBER_RE.finditer(text or ""):
        try:
            out.append((float(match.group(0)), match.start(), match.end()))  # 解析不了就跳过该处: 一条畸形数字不该挂掉整条预筛
        except ValueError:
            # 同 fixture 那条: 单个数解析失败不该中断整题的数值审计
            continue
    return out


def _close_to_any(value: float, pool: set[float], tol: float = 1e-6) -> bool:  # 容差取 1e-6 为基线 + 按位数自适应放宽, 见 _significant_digits 的口径块
    """数值是否命中值集 (**按位数自适应**容差; 大数值用相对, 小数值用绝对)。

    作用: 判定一个回答数值能否溯源回 fixture。关键参数 pool 是溯源值集,
    tol 是双端容差基准。Returns: 命中任一候选即 True。抛什么: 不抛。

    **为什么不能只用固定 tol** (2026-10-04 真实数据逼出来的缺陷): 合成 fixture
    是 2 位小数 (16.812), 固定 1e-6 恰好够用; 但真实回包是 17 位浮点
    (ps1_rpsf = 19.090110214761232), 题面引到 3 位小数 (19.090) 时绝对差是
    **1.1e-4**, 比 1e-6 窗口大 6 倍 —— 正确的引用会被判成"无来源编造"。
    实测 128 个真实值里有 **54 个**在 3 位小数下失配 (42%), 足以让 UNGR 系统性
    虚高, 把 E3 用自己的预筛判死。

    **判据改成「按回答里的位数取半单位窗」**: 人引用一个数时不会写出 17 位小数,
    必然按某个精度舍入过, 所以「回答的数 == fixture 值按该精度的舍入结果」才是
    可溯源的真正含义。窗口 = 该位数的半个单位, 天然覆盖 19.0901102…→19.090,
    且**不会放宽到把真正编造的数放进来** (差一个单位以上的仍判无来源)。
    """
    # 半单位窗: 3 位小数 -> 5e-4, 2 位 -> 5e-3, 整数 -> 0.5
    digits = _significant_digits(value)
    half_ulp = 0.5 * (10.0 ** -digits) if digits else 0.5
    # 与原双端容差取并集: 保留"微小抖动算同一数"的原意, 再叠加位数窗
    base = tol + tol * abs(value)
    window = max(base, half_ulp)
    return any(abs(value - candidate) <= window
               for candidate in pool)                                                      # 命中任一候选即算可追溯: 值集是并集语义, 不要求一一对应


def _significant_digits(value: float, max_digits: int = 6) -> int:
    """从浮点的**字面文本**取有效小数位数 (回答里的数是解析出来的, 有原文本)。

    作用: 给 ``_close_to_any`` 的位数自适应窗口提供位数。关键参数 value 是
    待判数值, max_digits 是上限。Returns: 小数位数 (整数返回 0, 上限 max_digits)。
    抛什么: 不抛; 非有限值按 0 档处理 (它们本就该判缺测, 不参与溯源)。
    """
    if not math.isfinite(value):   # NaN/Inf 不该被当可溯源的真值 (与 E2 的非有限值纪律同源)
        return 0
    text = repr(abs(value))                      # repr 给最短往返表示, 不含科学计数法尾数噪音
    if "e" in text or "E" in text:                # 科学计数法: 按指数折算小数位, 超出上限即截
        mantissa, _, exponent = text.partition("e")
        frac = len(mantissa.partition(".")[2])
        return max(0, min(max_digits, frac - int(exponent)))
    frac = len(text.partition(".")[2])            # 定点表示: 小数位数即位数
    return min(frac, max_digits)


def _has_derivation_marker(text: str, start: int, end: int, window: int = 30) -> bool:
    """数值前后窗口内是否有"可推导"标记 (方法写出的疑似信号)。

    作用: 把"写了方法的新数"从"裸编的数"里分出来。关键参数 start/end 是
    该数值的字符区间, window 是左右各看多少字符。Returns: 命中任一标记
    即 True。抛什么: 不抛; 窗口越界靠 max/min 夹回文本范围。
    """
    # 窗口取 30 字符 ≈ 一句中文的长度: 太短会漏掉"距离 = 1/视差 换算"这种
    # 方法写在紧邻位置的正确推导, 判成无来源会误伤好回答
    left = max(0, start - window)                                                                   # 左窗口夹紧: 命中句首时不能越界取片
    right = min(len(text), end + window)                                                       # 右窗口同样夹紧: 两端对称才不偏袒句中与句尾的写法
    context = text[left:right]                                                                      # 窗口文本一次取出, 下面逐个标记判存在
    return any(marker in context for marker in _DERIVATION_MARKERS)


def check_static_as_lc(answer: str) -> list[dict]:
    """静态误称光变曲线候选 (否定用法豁免 — 引用"不是时序库"不算触发)。

    否定窗口取命中点**前后两侧** (2026-10-04 修)。此前只看命中点之前的窗口,
    隐含假设"否定词总写在前面" —— 该假设在中文里不成立: "…是 phot_g_n_obs=143
    次观测的**多历元**统计摘要, 既不是单次曝光也不是时序"把否定写在命中**之后**,
    于是正确的否定式回答被判成"疑似把静态数据称为时序"。实测 36 题真模型批里
    5 条属此类假阳 (L2 逐条复核后 static_as_lc 命中数为 0)。

    否定窗口内出现否定词的命中**保留在返回里但标 ``negated: True``**
    (docs/eval-E3-semantics.md §6 M4: 受试引用"BEST 不是时序库"来否定
    问题前提——那正是正确答案)。豁免由聚合侧完成: summary 的
    ``static_as_lc_triggered`` 只数非否定命中 (prescreen 汇总处的
    ``triggered_static`` 过滤), 评阅人仍能在 hits 里看到"这里提到了
    光变曲线但是否定用法"的完整证据。
    """
    hits: list[dict] = []                                                                        # 命中清单: 空即没有疑似, 非空即待评阅人确认
    for pattern in STATIC_AS_LC_PATTERNS:                                                     # 逐个静态措辞扫: 命中只是起点, 还要看是否否定用法
        for match in re.finditer(pattern, answer, re.IGNORECASE):                                   # 忽略大小写: 英文术语大小写混用很常见
            # 前后都取窗口: 中文否定既可能前置 ("做不到: 光变曲线需要…") 也可能
            # 后置 ("…是 X 的多历元统计摘要, 既不是…"), 只看一侧会系统性漏判
            before = answer[max(0, match.start() - _NEGATION_WINDOW):match.start()]
            after = answer[match.end():match.end() + _NEGATION_WINDOW]
            negated = any(w in before for w in _NEGATION_WORDS) or \
                any(w in after for w in _NEGATION_WORDS)   # 任一侧命中否定词即算否定用法
            # 安全语境是独立一档: 受试把多历元量正确描述成"统计摘要"时, 语义上
            # 没有把它当序列, 属 rubric §2 要求的 single_or_coadded 限定语
            safe_context = any(w in before + after for w in _SAFE_CONTEXT_WORDS)
            hits.append({"term": match.group(0), "pos": match.start(),
                         "negated": negated or safe_context,
                         "note": ("否定用法 (引用'不是时序库'否定前提) — 不算触发"
                                  if negated else
                                  ("安全语境 (已说明是统计摘要, 履行 single_or_coadded 限定) — 不算触发"
                                   if safe_context else "疑似把静态数据称为时序/光变"))})
    return hits


def check_sentinel_misuse(answer: str) -> list[dict]:
    """哨兵误用候选: 出现哨兵数值且未声明缺失 (同句窗口内无声明词)。

    作用: 抓"把 -999 当真实星等"这类硬错误。关键参数 answer 是回答全文。
    Returns: 命中列表, 每条带 value/pos/note; 声明过缺失则返回空列表。
    抛什么: 不抛, 纯正则扫描。
    """
    hits: list[dict] = []                                                                           # 哨兵命中清单: 声明过缺失的不会进这里
    for match in re.finditer(SENTINEL_PATTERN, answer):                                          # 按形态扫而不是按固定值: 站点的哨兵有多个变体
        # 40 字符窗口覆盖一个从句: 声明常写成"…是空测光哨兵值, 表示缺失"
        # 这样跨了标点, 窗口太小会把正确声明判成误用
        start = max(0, match.start() - 40)                                                 # 左窗口 40 字符: 够容纳"是空测光哨兵值"这类前置说明
        end = min(len(answer), match.end() + 40)                                                 # 右窗口同样 40 字符: 声明也常写在数值之后
        context = answer[start:end]                                                                 # 窗口文本一次取出, 下面判是否已声明缺失
        if not any(word in context for word in _SENTINEL_DECLARATIONS):                    # 窗口内无任何声明词才判疑似: 报哨兵不等于误用, 裸报才是
            hits.append({"value": match.group(0), "pos": match.start(),
                         "note": "哨兵数值出现但未声明缺失 — 疑似当真实值使用"})
    return hits


def check_unsourced_numbers(answer: str, fixture: dict) -> dict:
    """数值可追溯性: 可追溯 (命中 fixture 值集) / 疑似可推导 / 无来源 / 致命候选。

    作用: 算 UNGR 的预筛版。关键参数 answer 是回答全文, fixture 是该题数值表。
    Returns: 字典含 total_numbers / traceable / derivable / unsourced /
    fatal_candidates 五个分项与已算好的 ungr。抛什么: 不抛。
    """
    pool = fixture_value_set(fixture)                                                               # 先算溯源值集: 后面三类分桶都拿它当基准
    # 三类互斥且优先级固定: 可追溯 > 可推导 > 无来源。顺序反了会把好回答的
    # 正确换算算成无来源, UNGR 虚高, E3 就被自己的预筛判死
    traceable, derivable, unsourced, fatal = [], [], [], []                           # 四个桶一次起: 优先级固定的互斥分桶, 顺序反了会把好回答判成无来源
    for value, start, end in extract_numbers(answer):                                        # 逐个数值走一遍分桶: UNGR 的分子分母都由这里累出
        if _close_to_any(value, pool):                                                          # 命中值集即算可追溯, 优先级最高, 后两类不再判
            traceable.append({"value": value, "pos": start})
            continue
        if _has_derivation_marker(answer, start, end):                                       # 附近写了方法才算可推导: 自己算出来的值不算无出处编造
            derivable.append({"value": value, "pos": start,
                              "note": "附近有方法标记 — 疑似可推导 (评阅人终裁)"})
            continue
        # 无来源必须带原文片段: 评阅人要靠片段才能判断是"真编造"还是
        # "正则没覆盖到的表达", 空证据的标记没有复核价值
        unsourced.append({"value": value, "pos": start,
                          "fragment": answer[max(0, start - 20):end + 20]})
    # 致命候选独立于溯源分桶: 它按"量+值"共现匹配, 与数值溯源是两条正交判据,
    # 放在循环外是刻意的 — 编周期这种错即使值来自 fixture 也仍是致命编造
    for pattern, label in _FATAL_PATTERNS:                                                 # 致命候选独立一趟: 它按"量加值"共现判, 与数值溯源正交
        for match in re.finditer(pattern, answer):                                              # 逐模式扫致命形态, 命中片段截断保存供评阅人核对
            fatal.append({"kind": label, "fragment": match.group(0)[:60]})
    # UNGR 的分母刻意排除致命项: 致命编造由 fatal_candidate_count 单列上报,
    # 混进分母会让 UNGR 与"致命项"这一硬红线重复计权
    total = len(traceable) + len(derivable) + len(unsourced)                              # 分母刻意不含致命项: 致命由单列计数上报, 混进来会重复计权
    return {
        "total_numbers": total,
        "traceable": traceable,
        "derivable": derivable,
        "unsourced": unsourced,
        "fatal_candidates": fatal,
        # 分母为 0 时给 0.0 而不是抛错: 无回答是 L0 阶段的常态, 一报错
        # runner 就跑不下去; 0.0 在此处的语义是"本回答无数值可审", 无偏袒
        "ungr": (len(unsourced) / total) if total else 0.0,
    }


def check_qualifier_coverage(answer: str, required: list[str]) -> dict:
    """八条限定语的关键词覆盖 (每题 qualifiers 子集; 缺 = 疑似缺失)。

    作用: 算 RQC 的预筛版。关键参数 required 是该题声明必须写出的限定语名
    子集 (rubric §2 定义全集, 每题只声明其中几条)。Returns: 字典含
    required / covered / missing 与已算好的 rqc。抛什么: 不抛。
    """
    covered, missing = [], []                                                                   # 覆盖与缺失两栏分开攒: 报告要能分别看达标与缺口
    for qualifier in required or ():                                                   # 只查本题声明的限定语: 全集是 rubric 定义, 不是每题义务
        keywords = _QUALIFIER_KEYWORDS.get(qualifier)                                      # 取该限定语的关键词表: 查表而非内联判断, 改词表不动逻辑
        if keywords is None:                                                               # 未登记的限定语名要显式记账: 跳过等于让改名悄悄逃逸出统计
            # 未登记的限定语名按"缺失"记账而不是跳过: 跳过等于让改名悄悄
            # 逃逸出覆盖率统计, RQC 会虚高 (铁律 5 禁 fail-open 的同源要求)
            missing.append({"qualifier": qualifier, "note": "rubric 未登记该限定语"})
            continue
        # 任一关键词命中即算覆盖: 回答写法千变万化, 要求逐字命中会把
        # 正确但换了措辞的答案全判成缺失
        if any(word in answer for word in keywords):                                    # 任一关键词命中即算覆盖: 逐字要求会把换了措辞的正确答案全判缺失
            covered.append(qualifier)                                                            # 记限定语名而不是关键词: 报告按限定语逐条对账
        else:
            missing.append({"qualifier": qualifier,
                            "note": "关键词未命中 — 疑似缺失 (评阅人终裁)"})
    return {
        "required": list(required or ()),
        "covered": covered,
        "missing": missing,
        # 本题不要求任何限定语时给满分 1.0 而不是 0.0: 分母为空算"无义务",
        # 算成 0 会把与限定语无关的题一律拖成缺失
        "rqc": (len(covered) / len(required)) if required else 1.0,
    }


def check_unsupported_claims(answer: str) -> list[dict]:
    """无支撑主张候选 (断言句式; UCR 预筛版 — 不只数值)。

    作用: 抓"未标记变星 ⇒ 恒定"这类无支撑断言。关键参数 answer 是回答全文。
    Returns: 命中列表, 每条带 kind 与原文片段; 谨慎表述返回空列表。
    抛什么: 不抛, 纯正则扫描。
    """
    hits: list[dict] = []                                                                           # 断言候选清单: 空即没有越界主张
    for pattern, label in _UNSUPPORTED_PATTERNS:                                                # 逐句式扫: 同一句可能命中多条, 全部保留供复核
        for match in re.finditer(pattern, answer):                                           # 命中片段截断保存: 评阅人要看原文才知道是不是合理表述
            hits.append({"kind": label, "fragment": match.group(0)[:60]})
    return hits


def prescreen(answer: str, item: dict, fixtures: dict) -> dict:
    """对一条回答跑全部 L0 检查 → 命中清单 + 预筛摘要 (不裁定)。

    Args:
        answer: 受试回答全文 (Tier F 为对 fixture 的科学问题回答)。
        item: items.yaml 的一条 (qualifiers/axis/id)。
        fixtures: items.yaml 的 ``fixtures`` 全表 (按 item.fixture 取)。

    Returns:
        ``{"item_id", "axis", "hits": {检查: 命中}, "summary": {...}}``;
        summary 含 fatal_candidates 计数 (供评阅人优先确认)。
    """
    # fixture 取不到时传空字典而不是 None: 下游 fixture_value_set 会把 None
    # 当空表处理, 全部数值落进无来源 — 那是"没给数据"而非"数据说没有",
    # 但对预筛而言结论一致, 交给评阅人复核更省事
    fixture = (fixtures or {}).get(item.get("fixture")) if item.get("fixture") else None
    # 五项检查彼此独立, 顺序不影响任何分桶 — 刻意平铺, 便于逐项加断言
    numbers = check_unsourced_numbers(answer, fixture or {})                          # 数值可追溯: 夹具取不到时传空表, 由判定侧记成"无可溯源"而不是崩
    qualifiers = check_qualifier_coverage(answer, item.get("qualifiers"))
    static_lc = check_static_as_lc(answer)                                                # 静态误称光变: 否定用法照样进 hits, 过滤留给汇总处做
    sentinel = check_sentinel_misuse(answer)                                                        # 哨兵误用: 声明过缺失的自然不进清单
    claims = check_unsupported_claims(answer)                                                      # 无支撑主张: 与数值判据正交, 单独一趟扫
    # 否定用法在 hits 里保留证据、在 summary 里不计数: 评阅人需要看到
    # "提到光变曲线但是否定用法"这条, 而 static_as_lc_triggered 必须是
    # 纯违规题数, 混进豁免项会让 SFA 的分母失真
    triggered_static = [h for h in static_lc if not h.get("negated")]
    return {
        "item_id": item.get("id"),
        "axis": item.get("axis"),
        "hits": {
            "static_as_lc": static_lc,
            "sentinel_misuse": sentinel,
            "unsourced_numbers": numbers,
            "qualifier_coverage": qualifiers,
            "unsupported_claims": claims,
        },
        "summary": {
            "static_as_lc_triggered": bool(triggered_static),
            "sentinel_misuse_count": len(sentinel),
            "unsourced_number_count": len(numbers["unsourced"]),
            "fatal_candidate_count": len(numbers["fatal_candidates"]),
            "qualifier_missing": [m["qualifier"] for m in qualifiers["missing"]],
            "unsupported_claim_count": len(claims),
        },
    }
