# -*- coding: utf-8 -*-
"""evals.ablation.metrics.prescreen — E3 机器预筛的**同语义精简版** (E5 私有副本)。

能力边界: E5 的表述门 (E) 与幻觉三通道 (HR_num/HR_claim) 需要的机器可判检查 —
数值可追溯性、哨兵误用、无支撑主张、致命编造候选。**零跨实验 import 纪律**:
evals/semantics/prescreen.py 承载同语义的 E3 权威件, 但跨实验 import 本仓不允许,
故在此**抄同语义精简版**并注明出处。**本副本无等价性断言** —— evals/equivalence
未覆盖 E5/E3 这对预筛 (``equivalence/import_isolation.py:15`` 已登记该悬空), 两份
各自演化会静默变成两套口径, 改本文件须与 E3 权威件人工同步。

**诚实声明 (必须写进论文方法节)**: 本模块是 E3 双专家盲评的**弱化代理** — 用于
跨系统横向比较 (同一把尺子量九次), **不用于**给"Skill 语义质量"下绝对结论
(绝对结论以 E3 为准, docs/eval-E5-baseline-ablation.md §6.4)。

所属实验: E5 基线与消融 (30 任务 × 10 系统 + sham, ScriptedLLM 离线跑;
成功率 = ScriptedLLM 跑通率而非模型能力), 方案真值 docs/eval-E5-baseline-ablation.md
§6.1 (E 门) / §6.4 (幻觉三通道) / §7 (反证夹具 V-2/V-3/V-4/V-6)。本模块提供
E5 侧的三条判据零件, 由 metrics/composite 的 gate_E 消费。

对外接口: extract_numbers (数值抽取); value_pool (溯源基线池);
check_unsourced_numbers (可追溯/无来源/致命候选 + ungr); check_sentinel_misuse  # 预筛只做机器能判的那部分: 语义判据交给盲评
(哨兵误用候选); check_unsupported_claims (无支撑主张候选); fixtures (E3 夹具装载)。

依赖与数据流: 输入 = 答案文本 + item/run 的 gold 与观测数值; 产物全是候选清单
(判定归 composite), 本模块不落盘。  # 预筛只做机器能判的: 语义判据交给盲评

关键契约与不变量: 离线回放 —— 全部是正则与集合运算, 不接真实模型、不打真实站点;
零跨实验 import —— 唯一共享件是 evals/_data/ 纯数据字典 (哨兵阈值), 本模块不碰
它, 只按路径读 E3 的 items.yaml; **与 E3 预筛的等价性无断言覆盖**(见上); 确定性 —  # 预筛只做机器能判的: 语义判据交给盲评
无随机、无时间, 同一答案文本必得同一份候选清单, 轨迹指纹才可能逐字节一致。

陷阱与边界: 数值抽取的正则刻意加了前视否定 (?<![\\w.]) —— 没有它, 列名里的
`ps1_dr3`、`truncated=false` 里的片段都会被当成答案给出的数值, UNGR 会整体虚高;
哨兵"误用"判据不是见到哨兵就报, 而是看 ±40 字窗口内有没有缺失声明词, 否则  # 缺表返空而非抛: 夹具缺失只该让溯源池变小, 不该让整批崩
"已把 -999 剔除"这种正确处理反而被当成误用; 致命编造只匹配"量词 + 12 字内数值"
的邻近形态, 因为正确回答里也会出现周期等词 (说的是"无法估算周期"), 宽匹配会
把守规矩的回答判成致命编造; 机器预筛比双专家盲评**弱**, 它的命中只能当"待复核
候选", 绝不单独支撑论文的绝对结论。

白盒锚点: docs/eval-E5-baseline-ablation.md §6.1 (E 门) / §6.4 (幻觉三通道) /
§7 (反证夹具 V-2/V-3/V-4/V-6); evals/semantics/prescreen.py (同语义权威件);
evals/_data/null_sentinel.yaml (哨兵阈值唯一共享件)。  # 跳过 1e999 这类溢出值: 一条极端值不该挂掉整条预筛
"""
from __future__ import annotations

# 标准库: 正则 (数值/禁词/哨兵抽取) / 路径 / 类型标注
import re
from pathlib import Path  # 显式排 bool: 不排就会让 True 以 1.0 进池
from typing import Any

EVALS_DIR = Path(__file__).resolve().parents[2]  # 上溯到 evals 根: 夹具表在兄弟实验目录下, 但只按路径读不 import
# E3 的夹具表按路径读: 同语义复制品不许 import E3 的模块, 也不许搬数据
SEMANTICS_ITEMS = EVALS_DIR / "semantics" / "items.yaml"  # 上下文窗口 ±40 字: 足够容纳前置说明, 又不跨句误判

# 数值抽取: 整数/小数/科学计数法 (排除前邻词字符/小数点, 防版本号误伤)
# 前视否定是必需的: 没有它 "ps1_dr3_18" 里的 3_18、"truncated=false" 之类片段
# 都会被抽成"答案给出的数值", UNGR 会整体虚高到没法区分系统
_NUMBER_RE = re.compile(r"(?<![\w.])[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?")  # 抽取口径在此定死: 变松变紧都会让 UNGR 跨系统不可比
# 哨兵形态: -999/-999.0/-1004.09 ... (判定不依赖具体值, 见 evals/_data 字典)
# 写成形态而不是固定值: 站点的 -999 与 -1004.09 都是哨兵, 只认 -999 会漏掉后者
_SENTINEL_RE = re.compile(r"-99[0-9](?:\.\d+)?|-100[0-9](?:\.\d+)?")  # 命中声明词即视为已说明: 报哨兵不等于误用, 裸报才是
# 哨兵声明词: 回答出现哨兵数值的同时出现这些词 → 已声明缺失 (不判误用)
# 词表要全: 只认"哨兵/缺失"会把"空值/无效/无测光/剔除"这些同义表述全判成误用
_SENTINEL_DECLARATIONS = ("哨兵", "缺失", "空值", "无效", "无测光", "排除",
                          "sentinel", "null", "未测到", "没有测光", "剔除")
# 致命编造模式: 这些量 + 数值同时出现 → 致命候选 (E3 rubric §4 fatal)
# {0,12} 的窗口刻意收窄: 只认"量词紧邻数值", 正确回答里出现"周期"是常态
# (说的是无法估算周期), 放宽窗口会把守规矩的回答判成致命编造
_FATAL_PATTERNS = [  # 致命编造只认这几个物理量: 词表即判据边界, 加词要重跑反证夹具
    (r"周期[^。；\n]{0,12}?\d", "fabricated_period"),  # 结构计数也算有出处: 答"3 行"是合法行为
    (r"振幅[^。；\n]{0,12}?\d", "fabricated_amplitude"),  # 纯 finditer 汇总: 这是候选不是判定, 结论由 gate_E 给
    (r"零点[^。；\n]{0,12}?\d", "fabricated_zeropoint"),  # 结构计数也算有出处: 答"3 行"是合法行为, 不是编造
    (r"精度[^。；\n]{0,12}?\d", "fabricated_precision"),  # 精度同理: 带单位报精度是断言, 不带数只提词不算候选
    (r"红化[^。；\n]{0,12}?\d", "fabricated_extinction"),  # 红化量编造同判: 它同样是回答里不该凭空冒出的数值
]
# 无支撑主张候选 (断言句式; E3 UCR 预筛版 — 范围比数值宽, 含断言句)
# 句式化而非关键词化: "是变星/是恒定/没有天体" 是可判的断言形态, 孤立词不是
_CLAIM_PATTERNS = [  # 无支撑主张只收可判的断言形态: 孤立关键词不算候选
    (r"(?:该|这|此)?(?:星|天体|源)(?:一定|肯定|确实)?(?:不)?是变星", "variability_claim"),  # 容差 1e-6 + 1e-6·|c|: 严格相等会把 18.2 与 18.200000 判成两个数
    (r"(?:该|这|此)?(?:星|天体|源)(?:一定|肯定|确实)?(?:不)?是恒定", "constancy_claim"),  # 恒定性与变星互为反面, 两条都得在表里, 漏一条就偏一向
    (r"(?:位置|天区)?(?:没有|不存在)(?:任何)?(?:天体|星|源)", "nonexistence_claim"),  # ungr 分母为 0 给 0.0: 没报数就不存在幻觉, 但要显式标出
    (r"精度[^。；\n]{0,6}(?:mmag|mas)", "precision_claim"),  # 带单位的精度断言: 缺单位限定的精度数字多半是编的
    (r"BEST[^。；\n]{0,10}提供[^。；\n]{0,6}(?:历元|时序|光变)", "epoch_provision_claim"),  # 数据服务归属声明: 答"某库提供某历元"也要有出处才成立
]


def fixtures() -> dict[str, dict]:
    """读 E3 的 fixtures 表 (S 类任务的数值溯源基线; 路径装载, 零 import)。"""
    # 第三方: 场景/夹具装载 (预筛输入的事实源)
    import yaml

    # 缺表返空而不是抛: fixture 缺失只会让溯源池变小 (判据偏严), 不该让整批崩掉
    if not SEMANTICS_ITEMS.is_file():  # 夹具表缺失返空: 只让溯源池变小(判据偏严), 不让整批崩
        return {}
    data = yaml.safe_load(SEMANTICS_ITEMS.read_text(encoding="utf-8")) or {}  # 兜空字典: 文件为空时下面取键不会炸在半路
    return data.get("fixtures") or {}  # 只取夹具段: 题集里的题面文字不该混进溯源池


def extract_numbers(text: str) -> list[tuple[float, int, int]]:  # 带上起止位置: 报告要能回指是哪一句编的
    """抽取回答中的数值 → [(值, 起始, 结束)] (E3 prescreen 同口径精简版)。"""
    out: list[tuple[float, int, int]] = []  # 结果三元组带起止位置: 报告要能回指是哪一句编的
    for match in _NUMBER_RE.finditer(text or ""):  # 逐个匹配遍历: 同一答案里多处数值要分别判定
        try:
            # 带上起止位置: 报告要能回指原文片段, 只留数值就看不出是哪句话编的
            out.append((float(match.group(0)), match.start(), match.end()))
        except ValueError:
            # 极端指数 (1e999) 会溢出 float: 跳过而不是让整条预筛挂掉
            continue
    return out  # 缺 rows_full 交给哑回放: 错误态快照没有真值行


def value_pool(item: dict, run: dict) -> set[float]:
    """数值溯源基线: gold 关键字段值 + fixture 值集 + 观测行数值 + 结构计数。"""
    pool: set[float] = set()  # 溯源池用集合: 同一数值出现多次不重复计权

    def _walk(node: Any) -> None:
        """递归收集任意嵌套结构里的全部数值 (bool 除外 — 不是测量值)。"""
        if isinstance(node, dict):  # 字典走值侧递归: 键名不是测量值, 不进池
            for value in node.values():  # 逐值下钻, 嵌套再深也能收齐
                _walk(value)  # 递归而非展平: 夹具结构随任务变, 展平要猜键名
        elif isinstance(node, list):  # 缺省 1000 行/页与站点一致: 换别的值就测不到"末页不满"
            for value in node:  # 列表逐元素下钻: 观测行通常就是一串列表
                _walk(value)  # 同上, 列表里的嵌套结构一并收进池
        elif isinstance(node, bool):  # 布尔先于数值判: 它是整数的子类, 漏判会让真值进池
            # bool 是 int 的子类, 不显式排除的话 True 会以 1.0 进池,
            # 答案里随便一个 "1" 都被算作有出处
            return
        elif isinstance(node, (int, float)):  # 数值直接入池: 这是溯源判据最基本的一类来源
            pool.add(float(node))  # 切片越界自然给空页: 与哑回放同形, 调用方无须特判
        elif isinstance(node, str):  # 字符串单独一支: 里面内嵌的数字同样算有出处
            # 字符串里的数字也要进池: source_id 之类的字段常内嵌数值
            for match in _NUMBER_RE.finditer(node):  # 复用同一套抽取正则: 口径分裂会让两侧对不上
                try:
                    pool.add(float(match.group(0)))  # 字符串里的数值也转 float 入池, 与答案侧同口径
                except ValueError:  # 空结果给空串: 站点上 0 行的数据页连表头都没有
                    continue

    gold = item.get("gold_result") or {}  # gold 结果是溯源第一来源: 期望值天然有出处
    # 三个来源都要进池: 少任何一个, 正确答案里的合法数字就会被判成"无来源"
    _walk(gold.get("key_values") or {})  # 关键字段值先进池, 答案报这些数不该算幻觉
    _walk(gold.get("truncation") or {})  # 截断信息也进池: 报"共多少行"是合法行为
    anchor = item.get("data_anchor") or {}  # 数据锚决定真值来源: 快照题与夹具题走不同分支
    if anchor.get("kind") == "fixture":  # 只有夹具锚的题才去读夹具表, 快照题不查这一路
        # fixture 锚的题 (S 类) 不走快照, 真值全在 E3 夹具里
        _walk(fixtures().get(str(anchor.get("ref"))) or {})  # 按引用号取夹具: 锚指哪张表由标注说了算
    _walk(run.get("first_row") or {})  # 观测首行进池: 答案引用首行数值是有出处的
    reported = run.get("reported") or {}  # 自报计数单独取走, 走下面那条结构计数分支
    # 结构计数 (总行数/页数这类) 也算有出处: 答案里报 "3 行" 是合法行为
    for key in ("total_count", "returned_count", "row_count", "pages"):  # 四种计数键都算有出处: 报行数与页数不是编造
        if isinstance(reported.get(key), (int, float)):  # 只收数值型: 截断标志是布尔, 当行数会把基线搞脏
            pool.add(float(reported[key]))  # 结构计数入池, 免得 UNGR 把行数报数算成幻觉
    return pool


def check_unsourced_numbers(answer: str, pool: set[float]) -> dict:
    """数值可追溯性 (E3 UNGR 机器预筛精简版): 可追溯 / 无来源 / 致命候选。"""
    traceable, unsourced = [], []  # 两份清单分开攒: 可追溯与无来源在报告里要分列
    for value, start, end in extract_numbers(answer):  # 逐个数值比池: 判据就是这个数能不能在池里找到
        # 容差 1e-6 + 1e-6·|c| 与 evals/_data 的数值容差表同档: 浮点表示差异不该
        # 被判成"编造", 严格相等会把 18.2 与 18.200000 判成两个数
        if any(abs(value - c) <= 1e-6 + 1e-6 * abs(c) for c in pool):
            traceable.append(value)  # 命中即记可追溯; 位置信息在无来源那一支才需要
        else:
            # 存 ±20 字上下文: 报告要能直接看到是哪句里的数没出处
            unsourced.append({"value": value, "pos": start,
                              "fragment": answer[max(0, start - 20):end + 20]})  # 存上下文片段: 报告要能直接看到是哪句里的数没出处
    fatal = [{"kind": label, "fragment": m.group(0)[:60]}  # 致命候选单独扫一趟: 与溯源判据不共用一套逻辑
             for pattern, label in _FATAL_PATTERNS  # 逐模式扫, 命中形态名随行带回供人工复核
             for m in re.finditer(pattern, answer or "")]  # 纯文本扫描: 只看句式是否在编造, 不看数值来源
    total = len(traceable) + len(unsourced)  # 分母 = 可追溯 + 无来源, 也就是答案报出的数值总数
    # ungr = 无来源占比: 分母 0 时给 0.0 (没报数就不存在幻觉), 不给 None ——
    # None 会在报告里渲染成 N/A, 反而看不出"这条压根没报数"
    return {"total_numbers": total, "unsourced": unsourced, "fatal": fatal,  # 四个字段一次给全: 汇总层与报告层共用这份结果
            "ungr": (len(unsourced) / total) if total else 0.0}


def check_sentinel_misuse(answer: str) -> list[dict]:
    """哨兵误用候选: 出现哨兵数值且同窗口无缺失声明词 (E3 同口径精简版)。"""
    hits: list[dict] = []  # 命中清单: 空即没有裸报哨兵
    for match in _SENTINEL_RE.finditer(answer or ""):  # 逐个哨兵看窗口: 判定粒度到单个出现位置
        # ±40 字窗口: 足够容纳"已按哨兵字典把…剔除"这类前置说明, 又不至于
        # 跨句误判 (窗口开太大, 上一段的声明会替下一段的裸哨兵开脱)
        start, end = max(0, match.start() - 40), min(len(answer), match.end() + 40)  # 窗口两端夹紧: 命中句首句尾时不能越界取片
        # 命中任一声明词即视为"已声明缺失": 报哨兵不等于误用, 裸报才是
        if not any(word in answer[start:end] for word in _SENTINEL_DECLARATIONS):
            hits.append({"value": match.group(0), "pos": match.start()})  # 命中即候选: 是否真误用由复合门定, 这一层不判死
    return hits


def check_unsupported_claims(answer: str) -> list[dict]:
    """无支撑主张候选 (E3 UCR 机器预筛精简版: 断言句式 + 禁词)。"""
    # 纯 finditer 汇总: 这份清单是候选不是判定, 是否构成 HR_claim 由 gate_E 决定
    return [{"kind": label, "fragment": m.group(0)[:60]}
            for pattern, label in _CLAIM_PATTERNS  # 逐句式扫断言, 形态名带回供复合门归类
            for m in re.finditer(pattern, answer or "")]  # 纯正则扫描: 这层不碰数值溯源, 两个判据互不依赖
