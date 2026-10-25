# -*- coding: utf-8 -*-
"""evals.nl2tool.graders — E1 评分器 (三类 grader + 六维指标 + 红线)。

能力边界: 把一条任务的实际轨迹 (trace) 与专家标注 (task) 逐维比对打分 —
工具选择/参数/转换/冗余/澄清/拒绝六维, 加权汇总出 E1 独立实验分。
边界: **不调大模型判分** (决策评测必须可复现可复核, E1 §7); 判定全部经
exact/normalized/python 三类 grader 完成; 每条判定保留原文证据。

白盒锚点: docs/eval-E1-nl2tool.md §6 (指标体系) / §7 (grader 实现约定);
references/tools.schema.json (参数面的唯一权威 — ParamHallucination 判定)。
"""
from __future__ import annotations

# 标准库: 数据类型标注 / 正则 (拒绝声明的结构化识别与别名归一化)
import re
from typing import Any, Optional

# 本地: 七族归一化器 (normalized 档 grader 的比对前站)
from evals.nl2tool.normalizers import (
    norm_band,  # 波段归一: 必须连 system 一起比, 同名异系统不算对
    norm_catalog,  # 星表名归一: 只吃掉大小写与空白差异, 不做别名映射
    norm_column,  # 列名归一: 去首尾空白即可, 别名映射不在这一层做
    norm_coord,  # 坐标归一: 分量缺失时给 None, 由比对层判失败
    norm_number,  # 数值比较的统一入口: 绝对与相对容差都在这里定, 不各写一套
    norm_radius,  # 半径归一与坐标同源, 差别只在容差口径
    norm_set,  # 集合归一: 通用 set 档按全等比
    norm_set_covers,  # 列投影集合: 标注列必须齐全, 多投影不判错
    norm_sort,  # 排序列归一: schema 声明 ps1.rpsf 与裸名 rpsf 同义, 分隔符不参与比对
)

# ── 权重与红线 (E1 §6.7; 启动即校验和 = 1.00, 与 scoring-rubric 同款硬约束) ──

GRADER_WEIGHTS: dict[str, float] = {                                                      # 六维权重表: 和必须为 1.00, 启动即校验, 漂了当场炸
    "toolset": 0.30,    # ToolSetF1
    "param": 0.25,      # ParamF1
    "convert": 0.15,    # Coord/Unit/Band 三项均值
    "redundant": 0.10,  # 1 - RedundantCallRate
    "clarify": 0.10,    # 1 - MissedClarifyRate (含质量折半)
    "reject": 0.10,     # RejectAcc
}

PASS_SCORE = 0.90    # 放行线: 加权分达标 **且** 红线任务清单为空
WARN_SCORE = 0.85    # 观察线: 落在 [0.85,0.90) 仍放行, 但报告须标出

# 逐维通过线 (E1 §6.7 表格第三列, 与上面两条总分线**并列**的第二道判据)。
# 加权总分达标**不代表**逐维达标: 权重最高的 toolset(0.30)+param(0.25) 拿满分
# 就贡献 0.55, 剩下 0.45 权重的 convert/redundant/clarify/reject 全塌成 0,
# 加权分仍有 0.55 —— 连 WARN 线都到不了, 但 convert=0 意味着坐标/单位/波段转换
# 全错, 那是 §6.7 列为红线的性质。这道线此前只写在文档里、**没有任何代码执行它**,
# 于是"28 条跑完"与"28 条达标"在报告上长得一模一样。
DIM_PASS_LINES: dict[str, float] = {
    "toolset": 0.90, "param": 0.85, "convert": 1.00,
    "redundant": 0.90, "clarify": 1.00, "reject": 1.00,
}
DIM_WARN_LINES: dict[str, float] = {   # 警戒线只进报告不阻断: 低于它要标出, 但 §6.7 未把它定义为阻断项
    "toolset": 0.85, "param": 0.80, "convert": 0.95,
    "redundant": 0.85, "clarify": 0.90, "reject": 0.90,
}
DIM_MIN_N = 5   # 逐维样本数下界: 低于它的维度不参与阻断 (clarify/reject 分母天然只有 2-3 条,
                 # 2 条全对记 1.00 毫无统计意义 —— 同 E6 §5.5 统计诚实口径, 宁可标"样本不足"也不冒充达标)

# 参数面合法域 (ParamHallucination 判定; 权威出处 references/tools.schema.json)
_RADIUS_MAX_ARCSEC = 18000.0   # 18000 角秒 = 5°; 再大已非一次锥检索的合理域
_PAGE_SIZE_MAX = 10000         # 单页上限: 超限属幻觉, 不按"上游会截断"宽容

# 参数键 → 归一化器名 (G2 的缺省值比对要走与显式传值**同一把尺**, 否则同一个
# 参数"填 300"判对而"缺省得 300"判错, 那就自相矛盾了)。未登记的键按 number
# 档比 —— 现有标注里进 gold_args 的非枚举键都是数值 (max_rows/limit 类)。
_NORMALIZER_BY_KEY: dict[str, str] = {
    "ra": "coord", "dec": "coord",                                     # 坐标走球面归一: 六十进制与十进制度同值
    "radius_arcsec": "radius",                                         # 半径带单位: 缺省值可能是角秒也可能是度
    "catalog": "catalog",                                              # 星表名走别名归一: 别名与真表名同值
}


def weighted_score(dims: dict[str, Optional[float]]) -> float:
    """按权重表把逐维分折成加权总分 (不适用维不计入, 权重和仍为 1.00)。

    单一口径: ``score_run`` 的汇总分与 E1 跨重复的稳定性方差都调它 ——
    两处各折一次就会冒出两个"加权分", 报告里的总分与方差对不上。
    """
    return sum(weight * dims[dim] for dim, weight in GRADER_WEIGHTS.items()   # 只遍历权重表: dims 里的杂键不参与折算
               if dims.get(dim) is not None)      # None = 该维不适用, 既不贡献分子也不占分母


def check_weight_sum() -> None:
    """权重和必须恰为 1.00 (启动即校验; 和不符 = 配置损坏, 直接抛)。

    Raises:
        ValueError: 权重和偏离 1.00 (容差 1e-9)。
    """
    total = sum(GRADER_WEIGHTS.values())                                                # 先求和再比: 权重表是人工维护的, 漂了要当场抛而不是静默算错分
    if abs(total - 1.0) > 1e-9:                                                            # 1e-9 容差吸收二进制浮点误差, 不放宽成"差不多就行"
        raise ValueError(f"GRADER_WEIGHTS 和 {total} != 1.00 — 权重配置损坏")


# ── 三类 grader (E1 §7) ───────────────────────────────────────────────────

def grade_exact(actual: Any, expected: Any) -> bool:
    """exact grader: 字符串/布尔/枚举严格相等 (工具名/理由码/路由)。"""
    return actual == expected


def grade_normalized(actual: Any, expected: Any, normalizer: str) -> bool:
    """normalized grader: 先过归一化器再比 (坐标/半径/星表/列/波段/数/集合)。

    Args:
        normalizer: 归一化器名 (catalog/column/coord/radius/band/number/set;
            band 需 expected 为二元组)。

    Raises:
        ValueError: 未知归一化器名 (fail-closed, 不静默放过)。
    """
    if normalizer == "catalog":                  # 星表名: 大小写/空白差异不算错
        return grade_exact(norm_catalog(actual), norm_catalog(expected))
    if normalizer == "column":                   # 列名只去首尾空白, 不做别名映射
        return grade_exact(norm_column(actual), norm_column(expected))
    if normalizer == "coord":                    # 球面坐标: 任一分量为 None 即判失败
        a, b = norm_coord(actual), norm_coord(expected)                                           # 两边都归一再比: 字符串形态的坐标也要能机比
        return a is not None and b is not None and norm_number(a, b, 1e-6, 0.0)
    if normalizer == "radius":                   # 半径: 绝对容差 1e-6 角秒, 相对容差 0
        a, b = norm_radius(actual), norm_radius(expected)                                         # 半径同样先归一: 单位没写错时不该被判成幻觉
        return a is not None and b is not None and norm_number(a, b, 1e-6, 0.0)
    if normalizer == "band":                     # 波段须连 system 一起比, 同名异系统不算对
        system, band = expected                                                           # 波段期望是二元组: system 与 band 拆开分别归一
        return grade_exact(norm_band(system, actual), norm_band(system, band))
    if normalizer == "number":                   # 其余数值: 容差 1e-9, 覆盖单位换算的浮点噪声
        return norm_number(actual, expected, 1e-9, 0.0)
    if normalizer == "set":                      # 集合按无序比, 元素内部仍走各自归一化
        return norm_set(actual, expected)
    raise ValueError(f"未知归一化器: {normalizer!r}")


def grade_python(predicate: Any, *args: Any) -> bool:
    """python grader: 自定义断言 (如"should_call_best=false 不得出现真实请求")。"""
    return bool(predicate(*args))


# ── 参数幻觉与值域 (E1 §6.2: 出现即红线) ──────────────────────────────────

def param_hallucinations(call: dict, schema_props: dict) -> list[str]:
    """列出一次调用中的参数幻觉: schema 外参数名 / 值越界。

    Args:
        call: ``{"tool": ..., "args": {...}}`` 实际调用。
        schema_props: 该工具 inputSchema.properties (权威来自
            references/tools.schema.json; 由调用方注入, 本文件不读盘)。

    Returns:
        幻觉清单 (空列表 = 干净)。半径 ≤0 或 >18000、page_size >10000、
        坐标越界 (ra∉[0,360) / dec∉[-90,90]) 均计值越界。
    """
    bad: list[str] = []                                                                      # 幻觉清单: 空即干净, 非空即红线, 两种状态一眼可分
    # 逐参数核对 schema: 幻觉是红线, 一次调用不短路, 命中的全部返回
    for key, value in (call.get("args") or {}).items():
        if key not in schema_props:     # schema 外参数名 = 幻觉 (E1 §6.2 红线)
            bad.append(f"unknown_param:{key}")
            continue
        # 占位符形态的值跳过值域判定 (2026-10-07): ``<上一步返回的 ra>`` 这类值
        # 表达的是"运行时依赖", 与标注侧 ``_is_placeholder`` 同一个口径 —— 标注
        # 那一侧对占位符是按通配处理的 (不参与比对), 这里却按非数值记一条
        # ParamHallucination 红线, 于是"老老实实写明值来自上一步"被判成幻觉,
        # 而随手填个 0.0 反而干净。红线判的是**编造参数**, 不是"未具化的引用"。
        if _is_placeholder(value):
            continue
        if key == "radius_arcsec":     # 半径: 能转 float 才谈值域
            try:
                r = float(value)                                                                    # 先强转再判值域: 转不了本身就是一种幻觉
            except (TypeError, ValueError):
                bad.append(f"radius_not_numeric:{value!r}")
                continue
            if not (0.0 < r <= _RADIUS_MAX_ARCSEC):   # 下界开: 0 半径取不到任何目标
                bad.append(f"radius_out_of_range:{r}")
        elif key == "page_size":       # 单页条数: 上游只收整数
            try:
                p = int(value)                                                               # 页长只收整数: 字符串形态先转, 转不了即记非整数幻觉
            except (TypeError, ValueError):
                bad.append(f"page_size_not_int:{value!r}")
                continue
            if not (1 <= p <= _PAGE_SIZE_MAX):         # 下界 1: 0 页会被读成"无数据"
                bad.append(f"page_size_out_of_range:{p}")
        elif key in ("ra", "dec"):     # 球面坐标: ra 半开 / dec 闭
            try:
                v = float(value)                                                               # 坐标同样先强转, 转不了记形态错而不是跳过量域判定
            except (TypeError, ValueError):
                bad.append(f"{key}_not_numeric:{value!r}")
                continue
            # ra 半开 [0,360): 360° 与 0° 指向同一点, 出现即判越界以便定位错源;
            # dec 闭 [-90,90]: 两个天极本身合法, 口径与 ra 不同不可共用判据
            in_range = (0.0 <= v < 360.0) if key == "ra" else (-90.0 <= v <= 90.0)
            if not in_range:           # 越界即幻觉, 不按"接近"降级放过
                bad.append(f"{key}_out_of_range:{v}")
    return bad


# ── 单任务评分 (E1 §6 六维) ───────────────────────────────────────────────

# 澄清/拒绝判定的关键词表 (E1 §7 双通道的关键词通道)
_CLARIFY_WORDS = ("需要", "请提供", "请指明", "缺少", "澄清", "哪个")                                       # 澄清关键词表: 命中即认为确实在问, 而不是自己瞎猜
_REJECT_WORDS = ("不支持", "无法", "没有", "不能")                                                           # 拒绝词表: 命中即认为明确推开了责任 (保留供外部引用与回归对照, 判定已改走下面的结构识别)

# ── 拒绝声明 = "否定 + 能力动词"的结构, 而不是一张动词表 ────────────────────
# 2026-10-06 修正 (起因: 桌面跑批 NL2T-22 / NL2T-24 被判 0 分)。
# 原判定是 ``any(w in answer for w in _REJECT_WORDS)`` —— 四词表。模型写
# "不提供时序" / "工具面不接收上传文件" 这两种**更常见**的说法都不在词表里,
# 于是 declared=False, 而阶梯的第一档就是 declared —— 后面的理由码、替代路径
# 取证再齐全也全部作废, 教科书级拒绝被判 0.00。这是纯措辞差异造成的误判。
#
# 改成**结构识别**: 否定词后紧跟一个能力动词才算"声明了不支持"。两个收益 ——
#   1. 招回: 不提供 / 不接收 / 不接受 / 不暴露 / 不开放 / 不具备 ... 全部进网;
#   2. 抗噪: "没有任何问题" 这种句子里的 "没有" 后面不是能力动词, 不再误判成拒绝
#      (四词表时代它是 100% 误判的 —— 近恒真的判据与漏判的判据是同一种病)。
#
# 但**禁止性情态词必须单独放行**, 不能要求它后面接能力动词: NL2T-26 的答案是
# "不能把 API token 拼进查询参数里" —— "不能" 后面跟的是任意动词词组, 不在能力
# 动词表里, 只走结构匹配会把它判成"没声明"(实测该题从 1.00 掉到 0.00)。这类词
# 语义上已经锁死了"不许做", 不像 "没有 / 无法" 那样能接无辜宾语 ("没有任何问题"),
# 所以它们**单独出现即算声明**, 其余弱否定词才走结构匹配。
_REJECT_DECL_MODALS = ("不能", "不得", "禁止", "不允许", "不可", "不应", "不应该", "未能", "没法")
_REJECT_DECL_RE = re.compile(
    r"(?:不|无|没有|非|无法|未能|不能|不可|不得|禁止|未)"
    r"(?:会|能|可以|得|被|够|再|直接)?"
    r"(?:支持|提供|接收|接受|受理|允许|暴露|开放|具备|导出|上传|处理|覆盖|响应|生效|接受)"
)
# 反向结构: 能力名词被否定 ("没有这个能力" / "无此入口" / "缺乏相应通道")
_REJECT_DECL_NOUN_RE = re.compile(
    r"(?:无|没有|缺乏|缺少)(?:此|这个|该项|相应|对应)?(?:能力|入口|通道|接口|办法|权限|计划)"
)
# 无歧义的成句否认: 不带能力动词也明确表达了"做不到"
_REJECT_DECL_PHRASES = (
    "做不到", "办不到", "不可行", "行不通", "不具备", "未开放", "超出能力范围",
    "超出工具能力", "不在能力范围内", "工具面没有", "工具面不支持", "无此能力",
)
# 2026-10-07 补第四条通道: 上面三条都要求"否定 + 能力动词/能力名词", 但有**一类
# 拒绝根本不谈能力**, 它谈的是"数据该往哪去" —— 凭据/敏感值不得落进某个位置:
# "凭据不进查询参数" / "不写进 URL" / "不出现在结果体" / "不拼进请求串"。
# NL2T-26 的答案正是这个形态, 三条通道全部判 False → declared=False → 阶梯首档
# 缺席, 后面理由码取证再齐全也被清零 (实测 0.00)。这类句子的动词是
# 进/入/写/拼/带/放/落到, 宾语是 参数/URL/结果/响应/日志, 结构固定, 普通叙述里
# 不会出现 ("不进参数"不是一句能独立成立的话), 误判风险与能力动词通道同量级。
_REJECT_DECL_PLACEMENT_RE = re.compile(
    r"(?:不|不得|禁止|不能|不可|不会|勿)"
    r"(?:会|能|可以|得|被|再|直接|该|应)?"
    r"(?:进入|出现在|写入|放进|落进|进|入|写|拼|带|放|落)"
    r"(?:查询|请求|表单|结果|响应|输出|返回)?"
    r"(?:参数|URL|url|地址|链接|串|结果体|响应体|正文|日志|请求头|头)"
)

# ── 理由码别名的三档比对 (文件下方 _match_reason_alias 处有分档说明) ────────
# 别名($reason_aliases)是标注给出的"该理由码的中文表面说法"。原判定只有
# ``alias in answer`` 一条逐字通道 —— 模型写 "不支持 output.fmt=fits" 而别名是
# "不支持 fits" 时, 中间插了个变量名就判不中 (NL2T-23 实测 0.25)。见下方函数。
_ALIAS_TOKEN_RE = re.compile(r"[一-鿿]+|[A-Za-z0-9]+")   # 别名切成"中文串 / 英文数字串"两种词元
_ALIAS_TOKEN_WINDOW = 16      # 词元相邻容差: 允许插入 16 个字符 (承载 output.fmt= 这类变量名)
_ALIAS_TOKEN_MIN_LEN = 2      # 少于 2 字符的词元不单独取证 (单字是噪声, 不是证据)
_ALIAS_STRIP_RE = re.compile(r"[\s　，。、；：？！（）()【】\[\]「」『』“”\"'·—\-_/\\]+")  # 去标点去空白去分隔符
# 替代路径的**兜底**通道 (G3): 标注的 reject.suggest 是一整句中文建议, 要求逐字
# 命中才记 has_alt, 实际模型几乎不可能复述同一句话 —— 实测 12 次里有 11 次给了
# 实质替代路径却全被判 0.5。逐字命中保留为强证据, 命中不了再退到这张词表。
# 词表与 evals/robustness/graders.py 的 _ALT_WORDS 同源 (同一仓内的既有口径),
# 但**按铁律 6 零跨实验 import** 的约定在此独立复刻一份, 两处要同步改。
# 2026-10-06 瘦身: 去掉 "如" 与 "用 "。前者是中文高频单字, 只要回答里出现
# "如下"/"例如"/"如果" 就被判"给了替代路径" —— 近恒真的判据等于没有判据
# (实测 12 次里 11 次靠它蒙到分); 后者带尾空格, 正常中文里几乎不出现, 是
# 一条死条目。留下的是"给出路"的实义动词。
_ALT_WORDS = ("可以", "建议", "改用", "替代", "或者", "走")


def declared_rejection(answer: str) -> bool:
    """答案是否**明确声明了不支持**(§6.6 四要素之一)。

    走"否定 + 能力动词"的结构识别而非关键词表 —— 见 ``_REJECT_DECL_RE`` 上方的
    修正说明。关键词表漏判与误判同源: 它既抓不住 "不提供", 又被 "没有任何问题"
    这类普通句子白拿。结构识别两端一起收紧。

    Args:
        answer: 模型回答原文。

    Returns:
        True = 明确推开了责任; False = 没声明, 或只是在吐槽/描述。
    """
    if not answer:                                      # 空答案不可能有声明: 直接 False, 别让正则跑空
        return False
    if any(w in answer for w in _REJECT_DECL_MODALS):   # 禁止性情态词: 语义自足, 单独出现即算声明
        return True
    if _REJECT_DECL_RE.search(answer):                  # 主结构: 不/无/没有/非 + 能力动词
        return True
    if _REJECT_DECL_NOUN_RE.search(answer):             # 反向结构: 能力名词被否定
        return True
    if _REJECT_DECL_PLACEMENT_RE.search(answer):        # 落点结构: 凭据/敏感值不得进某个位置 (NL2T-26 形态)
        return True
    return any(p in answer for p in _REJECT_DECL_PHRASES)   # 无歧义成句: "做不到" 之类


def match_reason_alias(answer: str, alias: str) -> Optional[str]:
    """别名是否命中, 返回**最强档位**; 未命中返回 None。

    三档由强到弱 ( reviewer 要能分辨"说了同一句话"与"说了同一件事"):
      ``"exact"``      别名原文逐字出现在答案里 —— 最强, 与修复前口径一致;
      ``"normalized"`` 两侧去掉标点/空白/分隔符后再比 —— 吃掉全角半角与空格差异;
      ``"windowed"``   切成词元后要求**全部出现且相邻**(容差 ``_ALIAS_TOKEN_WINDOW``
                       个字符) —— 承载模型插入变量名的形态, 如答案写
                       "不支持 output.fmt=fits" 而别名是 "不支持 fits"。
    第三档是本次修的目标形态, 也是唯一有漏判风险的形态, 故要求
    **全部词元都在**且**在窗口内按序相邻**——只允许中间插东西, 不允许各处散落。
    "不支持" 出现在段首、"fits" 出现在段尾, 不算命中。
    """
    if not alias:                                                       # 空别名无从取证: 不参与三档比对
        return None
    if alias in answer:                                                 # 逐字: 最强证据, 短路返回
        return "exact"
    answer_norm = _ALIAS_STRIP_RE.sub("", answer).lower()               # 答案去噪: 标点与空白都不参与比对
    alias_norm = _ALIAS_STRIP_RE.sub("", alias).lower()
    if not alias_norm:
        return None
    if alias_norm in answer_norm:                                       # 去噪后仍是连续串: 同一句话
        return "normalized"
    tokens = [t for t in _ALIAS_TOKEN_RE.findall(alias_norm) if len(t) >= _ALIAS_TOKEN_MIN_LEN]
    if not tokens:                                                      # 全是由单字构成的别名: 走不了词元通道
        return None
    cursor: Optional[int] = None                                        # 游标为 None = 还没命中任何词元, 此时只看能不能找到, 不看距离
    for token in tokens:
        pos = answer_norm.find(token, cursor if cursor is not None else 0)   # 从上一词元之后找, 保证顺序
        if pos < 0:                                                     # 这个词元根本没出现 → 别名不成立
            return None
        if cursor is not None and pos - cursor > _ALIAS_TOKEN_WINDOW:   # 与上一词元隔太远 = 各处散落, 不是同一句话
            return None
        cursor = pos + len(token)
    return "windowed"


def _tool_names(calls: list) -> list[str]:
    """取轨迹中的工具名序列 (保序, 供 ToolSetF1/ToolSeqExact 消费)。"""
    return [str(c.get("tool", "")) for c in calls or ()]


def _is_placeholder(value: Any) -> bool:
    """标注里的运行时依赖占位符 (``<...>`` 形态)。

    值来自上一步返回或用户补充 (如 ``<resolved_ra>`` / ``<上一步的 sqlid>``),
    机比时按通配处理 — 否则金标准轨迹与真实轨迹都会因"对不上占位符"被误判。
    """
    return isinstance(value, str) and value.startswith("<") and value.endswith(">")


# 通配哨兵: 期望值无法具化时用它显式表达"这一项不比对", 而不是拿 None 兼任
# (None 本身也可能是合法期望值, 混用会把"不判"与"判为空"搅在一起)。
_WILDCARD = object()


def _resolved_gold(gold_value: Any, key: str, bindings: Optional[dict]) -> Any:
    """期望值的最终比对值: 占位符优先按 primer 具化, 具化不了才退回通配。

    为什么不能直接通配了事 (2026-10-06 修正): 标注里的 ``<上下文天区的 ra>``
    在**单轮盲测**下没有任何东西能约束它 —— 模型杜撰一个坐标去查, 占位符照样
    通配, 于是"编造上下文"不但不扣分, 还能凭换算做对拿到 convert 满分
    (实测 NL2T-09/10/12 杜撰作答 0.800 且零红线)。跑了 primer 之后上文里
    声明了天区, 占位符就有了确定值, 这里把它替换进去, 杜撰立刻现形。

    未配 binding 的题退回 ``_WILDCARD`` (不比对): 没有上文可依时这是唯一诚实的
    处置, 报告应把这类题点名为"未具化", 而不是默认它通过了。
    """
    if not _is_placeholder(gold_value):
        return gold_value
    if bindings and key in bindings:
        return bindings[key]
    return _WILDCARD


def _expected_tool_names(task: dict) -> tuple[set, set]:
    """标注期望轨迹的 (必需工具集, 白名单可选工具集)。

    ``optional: true`` 的期望项不计缺失也不计多余 (E1 §3 expect_tools 语义)。
    clarify 路由: ``expect_tools`` 是**澄清后** (第二轮) 的调用标注 — 第一轮
    的正确行为是零调用 (问而不查), 故第一轮判定的 required 为空, 澄清后的
    调用全进白名单 (第一轮就调 → toolset precision 0 照罚)。
    """
    required, optional = set(), set()                                                        # 两集合分开记: 可选项不因缺失扣分, 也不因出现算多余
    for item in task.get("expect_tools") or ():
        name = str(item.get("tool", ""))
        (optional if item.get("optional") else required).add(name)
    route = str(task.get("route", "answer"))
    if route == "clarify":
        return set(), required | optional
    # 拒绝路由同样可以有"澄清/拿到信息之后才发生"的合法轨迹 (2026-10-07):
    # NL2T-24 的标注一边在 reject.suggest 里推荐 crossmatch_batch 作为替代路径,
    # 一边把它写进 must_not_call, 于是"照建议做"被判成硬执行红线。真正要禁的是
    # "声称上传建 job", 不是这个工具本身。after_clarify 里的工具按 clarify 同
    # 口径处理: 不计缺失也不计多余, 由 must_not_call 单独管硬执行。
    if route == "reject" and task.get("expect_tools_after_clarify"):
        after = {str(i.get("tool", "")) for i in task["expect_tools_after_clarify"]}
        return set(), required | optional | after
    return required, optional
    return required, optional


def grade_task(task: dict, trace: dict, schema_props: Optional[dict] = None,
               context_bindings: Optional[dict] = None) -> dict:
    """对一条任务按六维打分, 返回维度分 + 红线标记 + 判定证据。

    Args:
        task: tasks.yaml 的一条标注 (含 expect_tools/clarify/reject/anti_patterns)。
        trace: 采集到的实际轨迹 ``{"tool_calls": [...], "answer_text": str,
            "http_requests": int, "model_id": str, ...}``。
        schema_props: ``{tool_name: properties_dict}`` 参数面 (ParamHallucination
            判定用; 缺省跳过值域判定 — 调用方应注入 references/tools.schema.json)。
        context_bindings: 占位符具化表 ``{"ra": 10.68, "dec": 41.27, ...}``, 由
            ``context_primers.yaml`` 的 ``bindings`` 段供给。缺省 None = 该批没有
            上文可依, 占位符维持通配 (杜撰坐标仍不扣分, 报告应点名"未具化")。
            **模型评测批必须注入**, 否则 NL2T-09/10/12 这类续接题的分数含水分。

    Returns:
        ``{"task_id", "dims": {六维分}, "red_lines": [红线命中], "evidence": {...}}``。
        dims 各维 0.0~1.0; 该任务不适用的维度记 None (不进分母)。
    """
    calls = trace.get("tool_calls") or []     # 回放轨迹: 由 golden 快照供给, 不现调工具
    predicted = _tool_names(calls)            # 保序: ToolSeqExact 还要看调用顺序
    required, optional = _expected_tool_names(task)                                         # 期望集由标注决定: 澄清路由下必需集为空, 全部落白名单
    pred_set = set(predicted)                 # 集合视图供 F1/冗余, 顺序信息留在 predicted
    route = task.get("route", "answer")       # 缺省 answer: 老标注无 route 键时不算 reject
    answer = str(trace.get("answer_text") or "")

    dims: dict[str, Optional[float]] = {}                                                  # 逐维结果容器: 不适用的维记 None, 与得零分严格区分
    evidence: dict[str, Any] = {"predicted_tools": predicted}

    # ── 工具选择 (ToolSetF1; optional 两边都不计) ──
    # 2026-10-07 修正: 原实现 ``precision = tp / len(pred_set)`` 把**白名单内的调用
    # 也算进了假阳性** —— 而本函数自己的 docstring 写着"optional:true 的期望项
    # 不计缺失也不计多余"。于是标注推荐的工具 (NL2T-11 的 describe_catalog 探查、
    # NL2T-24 suggest 里的 crossmatch_batch) 一旦真被调了, precision 立刻塌成 0,
    # 注释承诺的"不计多余"根本没兑现。现在按标准 tp/fp/fn 三相算: 假阳性只认
    # "既非必需也不在白名单"的调用。
    tp = len(pred_set & required)                                                              # 真阳性: 命中必需工具
    fp = len(pred_set - required - optional)                                                   # 假阳性: 白名单外的多余调用
    fn = len(required - pred_set)                                                              # 假阴性: 该调没调的必需工具
    precision = tp / (tp + fp) if (tp + fp) else (1.0 if not required else 0.0)            # 无多余调用时按标注是否点过必需项定分, 不让空轨迹白拿满分
    recall = tp / (tp + fn) if (tp + fn) else 1.0                                               # 无必需项即满分: 这类题本来就不考工具选择
    dims["toolset"] = (
        2 * precision * recall / (precision + recall)                                 # 取 F1 而非两项平均: 漏调与乱调同罚, 才压得住"多调几个蒙对"
        if (precision + recall) > 0 else 0.0                                                    # 两项皆零才兜 0: 除零会把红绿判断变成异常中断
    )
    evidence["toolset"] = {"tp": tp, "fp": fp, "fn": fn, "pred": sorted(pred_set),
                           "gold": sorted(required), "whitelist": sorted(optional)}

    # ── 参数 (只对工具名判对的调用逐个比; ParamF1 简化为逐调用通过率) ──
    # 参数幻觉对**所有** schema 内工具的调用生效 (不只期望轨迹内的) —
    # E1 §6.2: 出现 schema 外参数名/值越界的调用占比必须为 0 (红线)。
    param_hits, param_total, hallucinations = 0, 0, []                                            # 三个计数一次起: 命中数、比较基数、幻觉清单
    unknown_tools: list[str] = []                                                                   # 伪造工具名单列: 与参数幻觉不同源, 报告要能一眼分辨是"造工具"还是"造参数"
    defaulted: list[str] = []                                                                       # 走 schema 默认值而过的键 (G2): 报告要能区分"填对了"与"没填但默认值对"
    schema_props = schema_props or {}                                                       # 缺参数面即空表: 幻觉维退化为"未判", 不等于"干净"
    for call in calls:                                                            # 逐调用核幻觉: 参数红线对所有 schema 内工具生效, 不只期望轨迹内的
        name = call.get("tool", "")
        tool_props = schema_props.get(name, {}) if schema_props else {}          # 该工具的参数面: 缺省空表, 下面取默认值时一并兜空
        # 伪造工具名 (2026-10-06 修正): 原实现写成"工具名在 schema 里才判幻觉",
        # 于是模型凭空造一个 ``ztf_search`` 这类名字时, 既不计 ParamHallucination,
        # 也不进任何红线 —— 而 E1 §1 把"伪造工具名"明确列为**最严重**一档。
        # 现在工具名不在参数面里即记 unknown_tool, 由它单独带出一条红线。
        # 参数面未注入时 (空表) 保持"未判": 缺权威不等于干净, 但也不可凭空造红线,
        # 该情形交给调用方 (runner) 的覆盖门禁收口, 不在本函数里冒充已判。
        if schema_props and name not in schema_props:                                       # 有参数面却查不到该工具 = 工具名不存在
            unknown_tools.append(name)
        elif name in schema_props:                                                        # 工具名成立才谈参数幻觉: 否则比出来的全是 unknown_param 噪音
            hallucinations.extend(param_hallucinations(call, schema_props[name]))      # 一次调用可命中多条, 全部返回不短路: 报告要能看清错在哪几个参数
        if name not in required:                                                             # 参数逐项比只对工具名判对的调用做, 否则比了也没有意义
            continue
        expected_item = next(                                                                # 按工具名回标注取期望参数: 同名多次调用共用同一份期望
            (i for i in (task.get("expect_tools") or ()) if i.get("tool") == name), None
        )
        if not expected_item:                                                                  # 标注缺这一项就不计分母: 不拿无期望的参数凑通过率
            continue
        param_total += 1                                                                     # 进分母的只有"可比"的调用: 通过率的分母因此才有意义
        gold_args = expected_item.get("args") or {}
        actual_args = call.get("args") or {}
        ok = True                                                                                # 逐键与, 不短路: 一个参数错就算这次调用没过
        for key, gold_value in gold_args.items():                                                # 只比标注点名的参数: 标注没写的参数不据以判错
            gold_value = _resolved_gold(gold_value, key, context_bindings)                      # 占位符先按 primer 具化: 有上文可依就不再通配
            if gold_value is _WILDCARD:                                                         # 具化不了才按通配处理, 不参与机比
                continue  # 运行时依赖值: 通配, 不参与机比
            # 缺省参数按 schema 声明的 default 生效后再比 (G2): 调用方没写这个键时
            # 上游真的会取默认值, 所以"没写"既不等于"没给对"也不等于"错" —— 要
            # 拿默认值当实测量比一次。schema 没声明 default 的键保持缺省即失败,
            # 那才是真的漏传。
            if key not in actual_args or actual_args.get(key) is None:
                schema_default = (tool_props.get(key) or {}).get("default")
                if schema_default is None:                                                    # 无默认声明: 漏传就是漏传
                    ok = False                                                                # 不给"缺省即通过"的兜底, 那会放走漏参数
                    continue
                if grade_normalized(schema_default, gold_value, _NORMALIZER_BY_KEY.get(key, "number")):
                    defaulted.append(key)                                                      # 默认值恰好等于标注期望 → 这次调用过关
                    continue
                ok = False                                                                      # 默认值与标注期望不符 → 实测量确实错
                continue
            actual_value = actual_args.get(key)
            if key in ("ra", "dec"):
                ok = ok and grade_normalized(actual_value, gold_value, "coord")
            elif key == "radius_arcsec":
                ok = ok and grade_normalized(actual_value, gold_value, "radius")
            elif key == "catalog":
                ok = ok and grade_normalized(actual_value, gold_value, "catalog")
            elif key == "columns":
                ok = ok and norm_set_covers(actual_value, gold_value)                        # 列投影按包含判: 多投影不罚, 少投影才错
            elif key == "sort":
                # 排序列走列名归一而非 exact (2026-10-07): schema 的 sort 参数
                # description 明写"如 ps1.rpsf 或裸名 rpsf", 标注却写 ps1_rpsf ——
                # 按 exact 比, 照 schema 作答的那一份被判错、照标注写的那份通过,
                # 判分器与自己的权威声明打架。归一后三种写法收敛到同一个裸列名。
                ok = ok and grade_exact(norm_sort(actual_value), norm_sort(gold_value))
            elif isinstance(gold_value, (bool, str)):
                ok = ok and grade_exact(str(actual_value), str(gold_value))            # 布尔与字符串统一转字符串再比: 免得 True 与文本形态差异误判
            else:
                ok = ok and norm_number(actual_value, gold_value, 1e-9, 0.0)                     # 其余数值走统一容差入口, 不在这里另设一套阈值
        param_hits += 1 if ok else 0                                                    # 全对才计命中: 参数维判的是"整次调用对不对", 不是逐参数平均
    dims["param"] = (param_hits / param_total) if param_total else None
    evidence["param"] = {"hits": param_hits, "total": param_total,
                         "hallucinations": hallucinations, "defaulted_keys": defaulted,
                         "unknown_tools": unknown_tools}

    # ── 转换 (类别 convert/multi 且标注含坐标/半径/波段参数的任务) ──
    # clarify 路由的 expect_tools 是澄清后 (第二轮) 标注 — 第一轮零调用,
    # 转换项在首轮判定里记 N/A (与 toolset 维同口径)。
    convert_items = [                                                                      # 转换项只认带坐标/半径/波段的调用: 其余任务本就不考换算
        i for i in (task.get("expect_tools") or ())
        if any(k in (i.get("args") or {}) for k in ("ra", "dec", "radius_arcsec", "band"))
    ] if route != "clarify" else []
    if convert_items:                                                                               # 有可判的转换项才算这一维, 否则记不适用
        hits = 0                                                                                   # 转换命中数: 逐个期望调用记一次全对或不对
        judged = 0                                                                                 # 实际判过的项数 (分母): 没调的项不进分母, 见下
        for item in convert_items:                                                                  # 逐个期望调用判: 换算错一个就够拉低整维
            name = item.get("tool", "")
            call = next((c for c in calls if c.get("tool") == name), None)
            if not call:                                                                 # 期望调用的工具压根没被调: 不计分也不计过, 交给工具选择维扣
                # 2026-10-06 修正: 上一行注释原本是**假的** —— hits 不加分, 分母却
                # 仍是全部 convert_items, 于是"没调"被算成"换算 0 分", 并进一步触发
                # S1 红线 (见文末红线段)。实测证明这会让"规规矩矩问一句'哪片天区'"
                # 被记成"静默错值"红线级失败, 比杜撰坐标作答 (0.800 零红线) 还惨。
                # 现在没调的项既不进分子也不进分母, 兑现注释的承诺。
                continue
            judged += 1
            args = call.get("args") or {}
            gold = item.get("args") or {}
            item_ok = True                                                                   # 逐项与: 坐标、半径、波段三者任一错即这次换算不算成功
            for key in ("ra", "dec"):
                if key in gold:
                    gv = _resolved_gold(gold[key], key, context_bindings)                    # 占位符先按 primer 具化: 有上文可依就不再通配
                    if gv is not _WILDCARD:                                                  # 标注给了且能具化才判: 缺项与通配都不该在这里扣分
                        item_ok = item_ok and grade_normalized(args.get(key), gv, "coord")
            if "radius_arcsec" in gold:
                gv = _resolved_gold(gold["radius_arcsec"], "radius_arcsec", context_bindings)
                if gv is not _WILDCARD:
                    item_ok = item_ok and grade_normalized(                                   # 半径换算走半径归一: 单位口径与参数维保持一致
                        args.get("radius_arcsec"), gv, "radius")
            if "band" in gold:
                gv = _resolved_gold(gold["band"], "band", context_bindings)
                if gv is not _WILDCARD:
                    item_ok = item_ok and grade_normalized(                                   # 波段换算连 system 一起比, 同名异系统要能判出来
                        args.get("band"), gv, "band")
            hits += 1 if item_ok else 0                                                     # 三项全过才计一次命中: 换算维按调用计数, 不按字段计数
        # 一项都没判 (期望的换算调用一个都没发生) → 该维**不适用**, 不是 0 分。
        # 零调用时没有任何"值"可言, 谈不上 §3 定义的"静默错值"; 判 0 分会让
        # 合法澄清被当成科学性错误, 还顺带触发 S1 红线 (见文末)。
        dims["convert"] = (hits / judged) if judged else None
    else:
        dims["convert"] = None

    # ── 冗余 (必要集外的调用; optional 白名单不计) ──
    necessary = required | optional                                                                 # 必要集含可选项: 白名单内的调用不算冗余
    redundant = [t for t in predicted if t not in necessary]                                      # 保序列出多余工具: 报告要能看出乱调了哪几个
    duplicates = len(predicted) - len(pred_set)                                                # 重复调用单独计: 同一工具调三次与调一次是两种冗余
    dims["redundant"] = (
        1.0 - (len(redundant) + duplicates) / len(predicted)                               # 冗余与重复一起扣: 分子是多出来的调用数, 分母是总调用数
        if predicted else 1.0                                                             # 零调用不罚冗余: 该问不问问的是澄清维, 这里扣就是重复扣分
    )
    evidence["redundant"] = {"extra": redundant, "duplicates": duplicates}

    # ── 澄清 (三通道: 禁调工具 + 关键词 + 中文探针; 任一"在问"证据即算问了) ──
    clarify = task.get("clarify") or {}
    if route == "clarify" and clarify.get("required"):
        # 第一轮就发了"澄清后才会发"的调用 = 该问不问 (MissedClarify)
        expected_after = {str(i.get("tool", ""))
                          for i in (task.get("expect_tools") or ())}
        # 「该问不问」的判据 = 首轮发了澄清后才会发的调用, **或** 轨迹里记着任何
        # http_requests。后者是回放信封的离线计数 (rate_limit 归零的通道), 本函数
        # 绝不发真实请求, 判定因此完全离线、可逐字节复现。
        data_called = bool(pred_set & expected_after) or trace.get("http_requests", 0) > 0
        keyword_hit = any(w in answer for w in _CLARIFY_WORDS)                                  # 关键词通道独立于调用: 说在问与真在问是两条判据
        # 中文探针通道 (A1, 2026-10-04): 六词表漏判严重 —— 实测 21 次澄清尝试里
        # 17 次正确地停了手、也点明了缺什么, 却因措辞不在这六词内判 0.5。所以给
        # 标注补 clarify.probes (逐题挑"真在问才会出现"的中文短语), 命中任一即
        # 算在问。探针与关键词是**并联**的两条正面证据, 不互相替代。
        probe_hit = any(p in answer for p in (clarify.get("probes") or ()))
        # 2026-10-06 修正 (原实现 here: ``asking = keyword_hit or probe_hit``,
        # 命中任一通用澄清词 ("需要"/"请提供"/"缺少"...) 即记 1.0): §6.5 的
        # ClarifyQuality 白纸黑字写着"只说『请补充信息』记 0.5" —— 而"请提供坐标"
        # 这种句子必然命中通用词, 于是**泛泛一问与点明缺失维度同分**, 这一维形同
        # 没有质量判据。现在把两条通道分开: 满分必须点明缺的是哪个维度 (探针通道),
        # 只命中通用词落到 0.5, 两条通道在 evidence 里分列以便复核。
        named_dimension = probe_hit                                                      # 点明缺失维度 = §6.5 的满分条件
        named_satisfiable = bool(clarify.get("probes"))                                   # 标注没给探针则该条件不可满足, 要在证据里说清
        asking = keyword_hit or probe_hit
        # 2026-10-07 接线 ``clarify.partial_credit``: 标注白纸黑字写着"若未澄清但
        # 显式声明口径并给出结果, 判 0.5 (Assumption-Declared)", 而判分器此前
        # **没有任何一行读这个键** —— NL2T-11 那条半分根本不存在, 声明了假设的
        # 答案与闷头瞎查的答案同记 0.0。这两者不是一回事: 写明"我按 ps1 定标测光
        # 理解"之后, 读者能从答案里看出假设是什么, 静默错值的入口因此堵住一半。
        # 锚点由标注给 (``clarify.assumption_aliases``), 判分器不猜措辞 —— 与探针
        # 通道同一个纪律: 判据必须是标注声明过的字符串, 不能由判分器自己发挥。
        assumption_hit = any(a in answer for a in (clarify.get("assumption_aliases") or ()))
        assumption_satisfiable = bool(clarify.get("assumption_aliases"))
        # 判序说明: "声明了假设"要先于"说在问却真在查"判 —— 后者罚的是**虚伪**
        # (嘴上问、手上已经干了, 且读者看不出它按哪个口径干的); 摊开假设的答案
        # 同样没停下来问, 但歧义被显式记账了, 与闷头瞎查不是一个性质。
        if data_called and clarify.get("partial_credit") and assumption_hit:
            dims["clarify"] = 0.5  # 声明了口径才动手: 假设可审计, 但仍是"该问没问"
        elif data_called and asking:                                                     # 说在问却真在查是最坏形态: 单独一档, 便于报告点名
            dims["clarify"] = 0.0  # 说在问, 实际在查 — 仲裁 FAIL
        elif data_called:
            dims["clarify"] = 0.0  # MissedClarify
        elif named_dimension:
            dims["clarify"] = 1.0  # 点明了缺哪个维度且没硬执行: §6.5 满分
        elif asking:
            dims["clarify"] = 0.5  # 只泛泛请补充信息, 没点明缺什么 (§6.5 折半)
        else:
            dims["clarify"] = 0.5  # 停了但没说缺什么 (ClarifyQuality 折半)
        evidence["clarify"] = {"keyword_hit": keyword_hit, "probe_hit": probe_hit,
                               "data_called": data_called,
                               "named_dimension": named_dimension,
                               "named_satisfiable": named_satisfiable,
                               "assumption_hit": assumption_hit,
                               "assumption_satisfiable": assumption_satisfiable}
    else:
        dims["clarify"] = None

    # ── 拒绝 (四要素: 未调被禁工具 + 声明 + 理由码 + 替代路径) ──
    reject = task.get("reject") or {}
    if route == "reject" and reject:
        banned = set(reject.get("must_not_call") or ())
        violated = pred_set & banned                                                        # 被禁工具的交集: 非空即硬执行, 后面所有加分都不再考虑
        # 2026-10-06 二修: 原先这里写 ``any(w in answer for w in _REJECT_WORDS)``,
        # 四词表。模型写 "BEST 不提供过去五年的光变曲线" (NL2T-22) 或 "工具面不接收
        # 上传文件" (NL2T-24) 时都不在词表里 → declared=False → 阶梯首档缺席,
        # 后面的理由码与替代路径取证再齐全也被清零 (实测两条教科书级拒绝判 0.00)。
        # 改成结构识别 (见 ``declared_rejection``): 招回漏判的同时, "没有任何问题"
        # 这类普通句子不再被误判成拒绝 —— 漏判与误判本就是同一种病。
        declared = declared_rejection(answer)                                              # 拒绝声明: 声明是四要素里的第一项
        # 2026-10-06 修正: 原实现写成 ``reason_code in answer or declared`` —— 后半段
        # 让"给出理由码"这一要素**恒等于"声明不支持"**: 只要说了"不支持", 理由码
        # 就算给了。于是 §6.6 的四要素实际只有三条在起作用, 而 §7 明写理由码走
        # exact 通道。现在理由码独立取证: 逐字命中码本身, 或命中标注给的中文别名
        # (``reject.reason_aliases``)。标注两者都没给时该要素无从取证 (记 False,
        # 该题封顶 0.5) —— 宁可封顶也不退回"声明即理由"的老口径。
        code = str(reject.get("reason_code") or "")
        code_verbatim = bool(code) and code in answer                                     # 逐字命中码本身: §7 的 exact 通道
        # 别名三档 (2026-10-06 三修): 原判定只有 ``alias in answer`` 一条逐字通道,
        # 答案里插个变量名就断了 —— NL2T-23 模型写 "站点也不支持 output.fmt=fits",
        # 别名是 "不支持 fits", 中间多了 "output.fmt=" 五个字符, 逐字比落空,
        # 理由码要素因此缺失 (实测 0.25)。现在三档: 逐字 > 去标点去空白 > 词元窗口。
        # 取**最强**的一档进证据 —— 复核者要能看出这是"复述了同一句话"还是
        # "说了同一件事", 两者的可信度不是一个量级。
        alias_modes = [m for m in (match_reason_alias(answer, a)
                                   for a in (reject.get("reason_aliases") or ())) if m]
        code_alias = bool(alias_modes)
        code_alias_mode = (                                                                # 档位排序: exact 最强, windowed 最弱
            "exact" if "exact" in alias_modes
            else "normalized" if "normalized" in alias_modes
            else "windowed" if alias_modes else None
        )
        has_code = code_verbatim or code_alias
        # 替代路径双通道 (G3): 逐字命中 suggest 是强证据, 命中不了再退到兜底词表。
        # 两个通道的结果都进 evidence —— 只有 bool 的话, 复核者分不清"命中了标注
        # 原句"与"只命中了兜底词", 而这两者的可信度不是一个量级。
        alt_verbatim = bool(reject.get("suggest")) and any(
            s in answer for s in reject.get("suggest") or ()
        )
        alt_fallback = any(w in answer for w in _ALT_WORDS)
        has_alt = bool(reject.get("suggest")) and (alt_verbatim or alt_fallback)
        if violated:                                                                           # 调了禁工具直接零分: 声明得再漂亮也改变不了硬执行
            dims["reject"] = 0.0   # HallucinatedExec: 调了明令禁止的工具
        elif declared and has_code and has_alt:
            dims["reject"] = 1.0   # 四要素齐: 声明 + 理由码 + 替代路径, 且未硬执行
        elif declared and has_code:
            dims["reject"] = 0.5   # 缺替代路径: 说清了不做什么, 没说什么可做
        elif declared:
            dims["reject"] = 0.25  # 只声明不执行: 夹在"会答"与"会拒"之间
        else:
            dims["reject"] = 0.0   # 连拒绝声明都没有, 已被当正常答案计分
        evidence["reject"] = {"declared": declared, "has_code": has_code,
                              "code_verbatim": code_verbatim, "code_alias": code_alias,
                              "code_alias_mode": code_alias_mode,   # None/ exact / normalized / windowed: 这一要素靠什么取证
                              "code_expected": bool(code) or bool(reject.get("reason_aliases")),
                              "alt_verbatim": alt_verbatim, "alt_fallback": alt_fallback}
    else:
        dims["reject"] = None

    # ── 红线 (任一命中即该任务 FAIL, 不看加权) ──
    red_lines: list[str] = []                                                                 # 红线清单独立于六维分: 命中任一即整条任务 FAIL
    if hallucinations:                                                                             # 参数幻觉是红线: 出现即记, 不按占比折算
        red_lines.append("ParamHallucination>0")
    if unknown_tools:                                                                              # 伪造工具名 (E1 §1 最严重一档): 单独一条红线, 便于报告点名具体名字
        red_lines.append("UnknownTool>0")
    # 转换错 = S1 静默错值 (§1 第 4 条 / §6.3)。此前它**只**拉低 convert 维的分,
    # 不进红线 —— 而 convert 维跨重复取中位数 (§8), 三次里错一次会被中位数抹成
    # 1.0, 于是"静默错值"在报告上彻底消失 (红线只认外部注入的 s1_events, 判定器
    # 自己从不产出 S1)。单位/波段换算是用户看不出来的错, §6.7 给它的通过线是
    # 1.00, 必须按红线处置。
    # 2026-10-06: 这里的语义原本是"换算维没满分 = 出了静默错值", 但 convert 维
    # 把"期望的调用压根没发生"也算成 0 分 (见上文 convert 段的修正), 于是**合法
    # 的澄清提问**会被记成 S1 静默错值 —— 而 S1 的定义 (§3) 是"拿到了看起来正常
    # 的错误结果", 零调用连结果都没有。现在 convert 在未判时记 None, None 不进
    # 本行判定, "没做"与"做错"就此分开: 触发红线的只剩确实调用过且换算错的情形。
    if dims.get("convert") is not None and dims["convert"] < 1.0:
        red_lines.append("S1:convert_mismatch")
    if route == "reject" and (pred_set & set((task.get("reject") or {}).get("must_not_call") or ())):
        red_lines.append("rejected_hard_executed")
    for s1 in trace.get("s1_events") or ():   # S1 静默错值由引擎侧记账, 判定层只搬运不重算
        red_lines.append(f"S1:{s1}")

    return {"task_id": task.get("id"), "dims": dims,
            "red_lines": red_lines, "evidence": evidence}


def score_run(task_grades: list) -> dict:
    """汇总一次跑批: 六维均值 (None 不进分母) + 加权总分 + 红线清单。

    Args:
        task_grades: ``grade_task`` 的返回值列表。

    Returns:
        ``{"dims", "dim_n", "weighted", "pass", "warn", "red_line_tasks", "n_tasks",
        "dim_failures", "thin_dims"}``; 加权分不得覆盖红线 — 任一任务红线条目非空即
        ``pass=False``。``dim_failures`` 是逐维通过线的落点 (E1 §6.7 第三列), 与
        ``pass`` 互不覆盖: 总分过线而逐维不过线是**真实存在**的情形, 由
        ``--require-threshold`` 决定是否阻断, 不在 score_run 里偷改 pass。
    """
    check_weight_sum()                                                                      # 汇总前再校验一次: 配置损坏要当场炸, 而不是等到出报告
    dim_totals: dict[str, list[float]] = {k: [] for k in GRADER_WEIGHTS}                            # 六个桶先建空: 缺维与零分靠"桶空"区分
    red_tasks: list[str] = []                                                                 # 红线任务 id 单列: 报告要能直接点名哪几条不合格
    for grade in task_grades:                                                                 # 逐任务累加: 任何一条红线的权重都不许被其余任务稀释
        if grade["red_lines"]:
            red_tasks.append(grade["task_id"])
        for dim, value in grade["dims"].items():
            if value is not None:                                                             # 只有打了分的维进桶: 不适用维混进分母会凭空拉低均分
                dim_totals[dim].append(value)                                             # 收集而不即时求均值: 报告还要看单条, 提前平均就把证据丢了
    dims = {                                                                               # 逐维均值: 桶空则不适用, 与"得了零分"在报告里必须能分
        dim: (sum(values) / len(values) if values else None)                                       # 桶空即记不适用: 不该被记成零分去拉低总分
        for dim, values in dim_totals.items()                                                    # 均值按权重表顺序算: 报告里的列序因此稳定可比
    }
    weighted = weighted_score(dims)                                                              # 折算口径唯一出口: 稳定性方差用的是同一把尺
    dim_n = {dim: len(values) for dim, values in dim_totals.items()}                             # 逐维样本数: "1.00" 必须与"打了几分题"一起读, 否则两题全对会冒充满分
    # 逐维门槛判定: 低于 §6.7 通过线的维逐条点名, 样本不足的维标出来但**不阻断**
    dim_failures = [
        {"dim": dim, "value": round(value, 4), "line": DIM_PASS_LINES[dim], "n": dim_n[dim]}
        for dim, value in dims.items()
        if value is not None and dim_n[dim] >= DIM_MIN_N and value < DIM_PASS_LINES[dim]
    ]
    thin_dims = [                                                                    # 样本不足的维: 不阻断, 但报告必须点名 —— 免得读者把 2 题全对读成"转换全对"
        {"dim": dim, "n": dim_n[dim], "value": round(dims[dim], 4)}
        for dim in GRADER_WEIGHTS
        if dims.get(dim) is not None and dim_n[dim] < DIM_MIN_N
    ]
    return {
        "dims": dims,
        "dim_n": dim_n,
        "weighted": weighted,
        "pass": (weighted >= PASS_SCORE) and not red_tasks,
        "warn": weighted >= WARN_SCORE,
        "red_line_tasks": red_tasks,
        "n_tasks": len(task_grades),
        "dim_failures": dim_failures,
        "thin_dims": thin_dims,
    }
