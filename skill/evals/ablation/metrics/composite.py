# -*- coding: utf-8 -*-
"""evals.ablation.metrics.composite — E5 三门合成 + ESR + 幻觉三通道 + 拒绝/澄清 + 成本。

能力边界 (docs/eval-E5-baseline-ablation.md §6): E5 **只编排、不重写判定器** —
本模块把三个门的零件合成端到端成功率, 并按分域分母统计 (N/A 不进分母):

  - **D 决策门** (E1 口径): ``ToolSetF1 == 1.0`` ∧ ``ParamHallucination == 0``
    ∧ 路由正确 ∧ 无 S1 静默错值;
  - **F 取数门** (E2 口径): 行集 ``precision == recall == 1.0`` ∧ 字段一致率
    ``1.0`` ∧ ``(truncated, total_count, returned)`` 三元组一致 ∧ 四态不错判;
  - **E 表述门** (E3 **机器可判子集**): 关键断言全中 ∧ 无禁答项 ∧ 无致命无来源
    数值 ∧ 无哨兵误用 (E5 把"必要限定语齐"写进 critical 断言短语承载)。

**零跨实验 import 纪律**: 不 import evals/ 下任何其它实验的代码。
  - E3 的机器预筛 (evals/semantics/prescreen.py) 在此**抄同语义精简版**并注明
    出处 — 跨实验 import 本仓不允许; 两份实现的等价性**无断言覆盖**;
  - E1 的 ParamHallucination 依据 **references/tools.schema.json** (工具参数面
    的权威) 现算, 不 import evals/nl2tool/graders.py;
  - E2 的金标准按**路径读 JSON** (evals/groundtruth/gold/*.json), 引用其
    case_id 与关键字段值, 不另造金标准。

**诚实声明 (必须写进论文方法节)**: E5 的 HR_num/HR_claim 走机器预筛
(数值可追溯性比对 + 禁词表 + 哨兵扫描), 比 E3 的双专家盲评**弱**; 因此 E5 的
语义类指标是**代理指标 (proxy)** — 用于跨系统横向比较 (同一把尺子量九次),
**不用于**给"Skill 语义质量"下绝对结论 (绝对结论以 E3 为准)。

所属实验: E5 基线与消融 (30 任务 × 10 系统 + sham 共 11 装配, ScriptedLLM 离线跑;
成功率 = ScriptedLLM 跑通率而非模型能力), 方案真值 docs/eval-E5-baseline-ablation.md
§6 (指标体系) / §6.5 (N/A 口径) / §7 (判定分层)。本模块是 E5 的**判定层**:
harness 产出一条 run, 这里给出这条 run 的三门结论与一个系统的成绩单。

对外接口: gate_D / gate_F / gate_E (三门判定, 各自返回 blockers 明细);
score_run (单条 run 的三门汇总); aggregate + _card (按系统聚合成成绩单);
tool_set_f1 / param_hallucination (E1 口径零件); table_prefixes (星表前缀单点);
tool_params / fixtures (数据装载); _rate / _mean / _median
(三种统计口径的分母规则)。

依赖与数据流: 输入 = items.yaml 单条任务 + run 记录 (harness 产出的轨迹) +
references/tools.schema.json + E3 fixtures;
产物 = 判定 dict 与成绩单 dict, 由 evals/ablation/runner.py 汇入报告 JSON。

关键契约与不变量: 离线回放 —— 判定只吃 run 记录, 不接真实模型、不打真实站点,
rate_limit 归零; 零跨实验 import —— 唯一共享件是 evals/_data/ 纯数据字典;
**无断言覆盖** (与 E3 预筛、与 E2 oracle 的互为对账目前靠人工维护, 见
equivalence/import_isolation.py:15);
**分母不变式** —— 无意义指标一律 None (N/A), 绝不用 0 顶替 (§6.5; 记 0 是
§11 阻断项 3, 会把"不可用"伪装成"很差"并压低跨系统比较); 判定纯函数 ——
同一 (item, run) 必得同一结论, 无随机无时间, 轨迹指纹才可能逐字节一致。

陷阱与边界: gate_D 的 fail-closed 豁免最容易写错 —— 信封已回 E_INVALID_INPUT
说明工具边界把非法参**显式拦下**了, 此时不记 ParamHallucination (系统没有
"静默使用"它), 这正是 B3 与 A1 在边界题 E5-D08 (半径 0) 上的唯一分界, 豁免写
宽了 A1 就再也测不出滑坡; F 门在大结果集上只有抽样主键, 精度退化为"抽样是否
全中"而不是真正的 P/R, 记 1.0 是口径妥协不是宽松判; _median 取中位数而非均值,
是因为 repeat 的目的正是看稳定性 (均值会被单次异常拉走); ratio 类指标一律
分母空返 None 而不是 0。

白盒锚点: docs/eval-E5-baseline-ablation.md §6 (指标体系) / §6.5 (N/A 口径) /
§7 (判定分层); evals/_data/null_sentinel.yaml (哨兵阈值唯一共享件);
references/tools.schema.json (7 工具参数面)。
"""
from __future__ import annotations

# 标准库: JSON (schema 读取) / 路径 / 类型标注
import json  # 工具参数面 schema 的唯一读入口; 哨兵与夹具走 yaml
from pathlib import Path  # 四个路径锚点在模块级算一次, 判定里不重复读盘
from typing import Any, Optional  # 类型词表只用于标注, 运行期无依赖

from evals.ablation.metrics.assertions import match_critical  # critical 断言的表示归一 (2026-10-10)
from evals.ablation.metrics.facts import facts_pass  # 事实层: 从观测现导事实 (2026-10-10)
from evals.ablation.metrics.prescreen import (
    check_sentinel_misuse,  # 哨兵误用检查: 表述门的一路判据, E5 私有同语义副本
    check_unsourced_numbers,  # 数值可追溯检查: UNGR 的分子与分母都由它出
    check_unsupported_claims,  # 无支撑主张检查: 断言句式那一路判据
    value_pool,  # 溯源基线池: 判"有无出处"的分母就是它
)

# 本地: 生产星表注册簿的表单表名与可查星表 id (前缀集合的唯一出处, 见
# table_prefixes 的 docstring —— 不可在本实验另抄一份, 副本会与线上表名脱节)
from src.protocol import CATALOG_FORM_TABLES, CATALOG_PATHS

# 四个路径都在模块级算一次: 判定里反复读盘没有意义, 且路径要能跨机复跑
ABLATION_DIR = Path(__file__).resolve().parents[1]  # ablation 包根: items/systems/runs 都从它派生
EVALS_DIR = Path(__file__).resolve().parents[2]     # eval 包根: _data 与 semantics 只按路径读, 不 import
SKILL_DIR = Path(__file__).resolve().parents[3]     # skill 根: references/tools.schema.json 在其下两级
# 工具参数面的权威: ParamHallucination 现算它, 不 import E1 的判定器
SCHEMA_PATH = SKILL_DIR / "references" / "tools.schema.json"  # 参数面权威: 现算它, 不 import E1 的判定器
# E3 的夹具表按路径读 (S 类任务的数值溯源基线); 跨实验只许读文件不许 import
SEMANTICS_ITEMS = EVALS_DIR / "semantics" / "items.yaml"  # E3 夹具表按路径读: 跨实验只许读文件不许 import

def table_prefixes() -> tuple[str, ...]:
    """列名前缀集合 = 各可查星表的**表单表名** + "_" (长前缀优先)。

    权威来源是生产注册簿 :data:`src.protocol.CATALOG_FORM_TABLES` 与
    :data:`src.protocol.CATALOG_PATHS` (线上真实表名), 不在本实验另抄一份
    硬编码表 —— 硬编码副本的粒度必然与线上注册簿脱节: 同一列
    ``gaia_dr3_18_rpsf`` 剥出 ``rpsf`` 还是 ``dr3_18_rpsf`` 只取决于调用了哪份
    副本, E5 报告的列标签就随调用点而异, 同一列在两张表里对不上号。

    表名解析必须镜像协议层 ``catalog_tables()`` 的回退: ``CATALOG_FORM_TABLES``
    仅收录**多表**星表 (dr3xpcorr/gaia_dr3_18/xpsp), 单表星表不在表里, 协议层
    回退成"星表 id 自身即表名"。只遍历 FORM_TABLES 会漏掉 ps1_/uss_dr1_/
    splus_dr4_ 等全部单表前缀。

    长前缀优先是必需的: ``gaia_`` 与 ``gaia_dr3_18_`` 都是真前缀, 短的不先
    命中就会把规范列名剥残。

    Returns:
        按长度降序排列的前缀元组 (可直接顺序匹配)。
    """
    tables: set[str] = set()                                                                   # 表前缀集合现算: 只此一处产出, 渲染层不另持一份
    for catalog in CATALOG_PATHS:                                                                # 逐个目录路径剥前缀: 路径形态比裸名覆盖得更全
        tables.update(CATALOG_FORM_TABLES.get(catalog) or (catalog,))  # or (catalog,) 镜像协议层回退: 单表星表不在 FORM_TABLES 里
    return tuple(sorted((f"{t}_" for t in tables), key=len, reverse=True))  # 按长度降序: 短前缀会先吃掉 gaia_dr3_18_


# 已知星表前缀 (剥前缀取裸列名; 与 src.protocol 的星表名同源)
_TABLE_PREFIXES = table_prefixes()  # 前缀表现算: 改线上注册簿即改全部调用点, 硬编码副本会与真实表名脱节

# 参数值域 (E1 §6.2 / tools.schema.json 的 constraints 段)
# 每项是 (区间形态, 下界, 上界); 四种形态对应四种边界语义, 混用就会把
# 开闭区间判反 (ra 360.0 合法而 radius 0.0 不合法)
VALUE_RULES: dict[str, tuple[str, float, float]] = {  # 四种区间形态各判各的: 混用会把开闭边界判反
    "ra": ("range", 0.0, 360.0),             # [0, 360)
    "dec": ("range", -90.0, 90.0),           # [-90, 90]
    "radius_arcsec": ("open", 0.0, 18000.0),  # (0, 18000]
    "page": ("min", 1.0, 0.0),               # >= 1
    "page_size": ("closed", 1.0, 10000.0),   # [1, 10000]
}
# 排序方向的枚举: 不在 VALUE_RULES 里 (它是枚举不是区间), 单独判 bad_enum
ORDER_ENUM = ("asc", "desc")  # order 是枚举不是区间, 故不进 VALUE_RULES, 单独判 bad_enum


# ── 数据读取 (只读数据文件, 零跨实验 import) ────────────────────────────────

def tool_params() -> dict[str, set[str]]:
    """读 references/tools.schema.json → {工具: 合法参数名集合} (缺失即抛)。"""
    if not SCHEMA_PATH.is_file():  # fail-closed: 参数面缺失时"任何参数都合法"会让 ParamHallucination 恒 0, 红线静默失效
        raise FileNotFoundError(f"工具参数面缺失: {SCHEMA_PATH}")
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))  # 现读现算: schema 改了不必改代码
    # 收成集合: 判定里是成员测试, 列表会退化成 O(n) 扫描
    # 收成 set: 判定里是成员测试, 列表会退化成 O(n) 扫描
    return {tool["name"]: set((tool.get("inputSchema") or {}).get("properties") or {})
            for tool in schema.get("tools") or []}


def fixtures() -> dict[str, dict]:
    """读 E3 的 fixtures 表 (S 类任务的数值溯源基线; 路径装载, 零 import)。"""
    # 第三方: 系统装配表装载 (组件开关的判定输入)
    import yaml

    if not SEMANTICS_ITEMS.is_file():  # 缺表返空: 只让溯源池变小 (判据偏严), 不该让整批判定崩掉
        return {}
    data = yaml.safe_load(SEMANTICS_ITEMS.read_text(encoding="utf-8")) or {}
    return data.get("fixtures") or {}  # 只取 fixtures 段: items 段是题面, 不是溯源池


# ── E1 口径: 工具集与参数正确率 ─────────────────────────────────────────────

def tool_set_f1(expected: list[str], actual: list[str]) -> float:
    """工具名集合的 F1 (重复调用按集合去重; 双方皆空记 1.0)。"""
    exp, act = set(expected), set(actual)  # 转集合: 重复调用按去重计, 语义正是"调了哪些工具"
    if not exp and not act:                                                                         # 两侧都没有即满分: 双方都空不算少返
        return 1.0  # 双空记 1.0 而非 0.0: 拒绝题的正确形态就是零调用, 记 0 会把"守规矩"判成错
    if not exp or not act:                                                                         # 只有一侧空即判错: 这正是少返与多返的形态
        return 0.0  # 单边空记 0.0: 漏调与乱调两种都该判错, 不因一侧为空而放行
    overlap = len(exp & act)  # 交集计数: F1 的 P 与 R 都从这一个数推出
    if overlap == 0:                                                                                # 交集为空单独记: 少返与多返要能分开归因
        return 0.0  # 无交集提前退: (P+R) 分母会趋零, 直接给 0 更稳也更好读
    precision, recall = overlap / len(act), overlap / len(exp)  # 先实后期: 分子同是 overlap, 只分母不同
    return 2 * precision * recall / (precision + recall)


def param_hallucination(calls: list[dict]) -> list[dict]:
    """参数幻觉 (E1 红线): schema 外参数名 / 值越界 (半径 ≤0 或 >18000 等)。

    Returns:
        命中清单 ``[{"tool", "param", "kind", "value"}]``; 空清单 = 0 (达标)。
    """
    params = tool_params()  # 参数面现取一次: 逐次调会重复读盘
    hits: list[dict] = []   # 命中清单而非计数: 报告要逐条展示幻觉长什么样
    for call in calls or []:                                                                  # 逐调用核参数幻觉: 一次调用不短路, 命中的全部记下
        tool = str(call.get("tool") or "")
        # 未知工具整条记一条: 工具名都不对, 再逐参数判是白费
        if tool not in params:                                                                   # 工具不在参数面里不判幻觉: 未知工具归另一维管
            hits.append({"tool": tool, "param": None, "kind": "unknown_tool",
                         "value": tool})
            continue
        for name, value in (call.get("args") or {}).items():
            # schema 外参数名: E1 红线之一, 也是 A1 拆掉校验后最常出现的形态
            if name not in params[tool]:                                                       # 参数名不在 schema 外即幻觉: 出现就是红线
                hits.append({"tool": tool, "param": name, "kind": "unknown_param",
                             "value": value})
                continue
            rule = VALUE_RULES.get(name)                                                            # 取值域规则查表: 改阈值不动判定逻辑
            number = _as_float(value)                                                               # 先转数值: 转不动本身就是一种幻觉
            # 无区间规则的参数: 只可能是 order 这类枚举, 单独判 bad_enum
            if rule is None:                                                                   # 无规则的参数跳过值域判: 只判有明确合法域的那几个
                if name == "order" and str(value) not in ORDER_ENUM:
                    hits.append({"tool": tool, "param": name, "kind": "bad_enum",
                                 "value": value})
                continue
            kind, low, high = rule                                                                  # 规则拆成三段: 开闭区间与枚举各判各的
            # 转不出数值就跳过: 区间判据对非数值没有意义, 硬转会得到假越界
            if number is None:                                                                 # 转不动就记形态错: 不跳过量域判, 免得脏值蒙过去
                continue
            # 四种区间形态各判各的: 开/闭/半开/下界混写会把边界值判反
            bad = ((kind == "open" and not low < number <= high)
                   or (kind == "closed" and not low <= number <= high)
                   or (kind == "range" and not low <= number < high)
                   or (kind == "min" and number < low))
            if bad:                                                                                 # 越界即红线: 不按"接近"降级放过
                hits.append({"tool": tool, "param": name, "kind": "out_of_range",
                             "value": value})
    return hits


def _as_float(value: Any) -> Optional[float]:
    """安全转 float (不可解析/布尔 → None — 交由调用方按非数值分支处理)。"""
    # bool 先拦: Python 里 True 就是 1, 不拦会让 flag 型参数被拿去判值域
    if isinstance(value, bool):                                                            # 布尔先于数值判: 它是整数的子类, 不先挡会把标志位当星等
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# ── 三门判定 ────────────────────────────────────────────────────────────────

def gate_D(item: dict, run: dict) -> dict:
    """决策门 (E1 口径): ToolSetF1==1 ∧ ParamHallucination==0 ∧ 路由正确 ∧ 无 S1。

    **fail-closed 豁免 (重要口径)**: 若某次调用的信封已返回
    ``E_INVALID_INPUT``, 说明工具边界把非法参数**显式拦下**了 — 此时该参数
    不计入 ParamHallucination (系统没有"静默使用"它)。这正是 B3 与 A1 在
    边界题 (如 E5-D08 半径 0) 上的分界: B3 拦下 → 不记幻觉; A1 放行 → 记。
    """
    calls = run.get("tool_calls") or []
    envelopes = run.get("envelopes") or []
    # 拒绝路由题的期望工具集 = 空 (拒绝即零请求; expect_tools 里列的调用是
    # "天真系统会发出的陷阱调用" — 文档 §5.2 口径, 不是期望行为)
    if str(item.get("route")) == "reject":
        expected: list[str] = []                                                                 # 期望主键先备好: 没有 gold 时它保持为空
    else:
        expected = [str(s.get("tool")) for s in item.get("expect_tools") or []]
    actual = [str(c.get("tool")) for c in calls]  # 实得按调用序取不去重: 去重发生在 F1 里
    f1 = tool_set_f1(expected, actual)            # 集合 F1: 重复调用不罚, 漏调与乱调同罚
    hallucinations: list[dict] = []                                                              # 幻觉清单单列: 它是红线, 不与维度分混在一起
    # 逐条按信封豁免: 整批调用一次算会把"被拦下的"和"真幻觉"混在一起,
    # B3 与 A1 就再也分不开
    for index, call in enumerate(calls):                                                        # 调用与信封按下标配对: 两者顺序必须一致才能对账
        # 信封可能比调用少 (链路中断), 越界取空 dict 而不是 IndexError
        envelope = envelopes[index] if index < len(envelopes) else {}                           # 缺信封兜空字典: 少一条不该让整条 run 崩掉
        if (envelope.get("status") or {}).get("error_code") == "E_INVALID_INPUT":
            continue
        hallucinations.extend(param_hallucination([call]))                                      # 逐调用判完并入总清单: 报告要能按调用定位到参数
    route_ok = str(run.get("route")) == str(item.get("route"))
    assertions = item.get("assertions") or {}
    answer = str(run.get("answer_text") or "")
    # 禁答短语子串命中即算: 表述门只管"有没有说错的话", 不做语义裁决
    # 子串命中即算: 表述门只管"有没有说错的话", 不做语义裁决
    forbidden_hits = [str(f) for f in assertions.get("forbidden") or [] if str(f) in answer]
    # 致命数值来自 item+run 的可核值池, 不是全库
    fatal = check_unsourced_numbers(answer, value_pool(item, run))["fatal"]
    # S1 = 静默错值: 既说了禁答的话, 又编了致命数值, 任一成立即红线
    s1 = bool(forbidden_hits) or bool(fatal)  # S1 = 静默错值: 既说禁答又编致命值, 任一成立即红线
    blockers = []                             # 清单而非布尔: 报告要逐条显示挂在哪个判据上
    # blockers 是清单不是布尔: 报告要逐条显示"挂在哪个判据上", 合成一句会丢信息
    if f1 < 1.0:                                                                                    # 工具集不满分即记阻断: 决策门的第一条
        blockers.append(f"ToolSetF1={f1:.2f}")
    if hallucinations:                                                                            # 参数幻觉记阻断: 出现即红线, 不按占比折算
        blockers.append(f"ParamHallucination={len(hallucinations)}")
    if not route_ok:                                                                            # 路由错记阻断: 该拒的照做与该答的拒答都算这一类
        blockers.append(f"route={run.get('route')}!={item.get('route')}")
    if s1:                                                                                      # 静默错值记阻断: 它由引擎侧记账, 判定层只搬运
        blockers.append("S1_silent_wrong_value")
    return {"pass": not blockers, "blockers": blockers, "tool_set_f1": round(f1, 4),
            "param_hallucination": len(hallucinations),
            "param_hallucination_hits": hallucinations, "route_ok": route_ok,
            "s1": s1, "forbidden_hits": forbidden_hits}


def _derive_gold_fields(gold: dict) -> dict:
    """把 F 门要用的期望字段从 **E2 金标准文件** 现取, 不吃 items.yaml 里的手工副本。

    为什么必须有这一步 (2026-10-04): items.yaml 的 ``gold_result`` 按设计只是
    "登记 ref + 关键字段值", 权威在 ``evals/groundtruth/gold/<case_id>.json``。但
    E2 改指真实快照后, 那份手工副本 (``BEST_SIM_0001`` / ``first_ps1_rpsf: 18.2``
    / ``row_count: 2``) 就与权威**矛盾**了 —— 而 ``gate_F`` 读的正是副本, 于是
    取数门会拿"旧合成数据的期望"去判被测系统。抄一份就会漂, 所以改为现取:
    E2 换素材, E5 的期望自动跟着走。

    读不到 ref 文件时**退回副本并在返回值里留痕** (``derived_from`` 为 False),
    不静默用陈旧数据: 调用方能看出这次判分的期望来自哪里。
    """
    ref = gold.get("ref")
    if not ref:
        return {**gold, "derived_from": None}
    path = SKILL_DIR / str(ref)          # items.yaml 的 ref 是相对 skill 根写的 (如
    if not path.is_file():               # evals/groundtruth/gold/<case>.json), 复用已有锚点不新增
        return {**gold, "derived_from": None}
    try:
        real = json.loads(path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError):
        return {**gold, "derived_from": None}

    keys = [str(k) for k in (real.get("row_keys") or ())]
    trunc = real.get("truncation") or {}
    # 大结果集 (huge_*) 的金标准只给样本, 全量主键不可得 —— 与 items.yaml 原本
    # 用 row_keys_sample 的口径一致, 故按阈值分流, 不把 4000 个主键塞进期望集。
    sampled = len(keys) > 200
    field_values = real.get("field_values") or {}
    first_key = keys[0] if keys else None
    cells = field_values.get(first_key) or {} if first_key else {}
    key_values = {f"first_{col}": (spec.get("v") if isinstance(spec, dict) else spec)
                  for col, spec in cells.items()}
    derived = dict(gold)
    derived["row_keys"] = [] if sampled else keys
    derived["row_keys_sample"] = keys[:4] if sampled else []
    derived["row_count"] = int(real.get("row_count") or 0)
    derived["key_values"] = key_values
    derived["truncation"] = {
        "truncated": bool(trunc.get("expected_truncated")),
        "total_count": trunc.get("expected_total"),
        "returned_count": trunc.get("expected_returned"),
    }
    derived["derived_from"] = str(ref)
    return derived


def gate_F(item: dict, run: dict) -> Optional[dict]:
    """取数门 (E2 口径); 非 D 类 / 无金标准 / 无取数尝试 → None (N/A, 不进分母)。

    **"什么都没取到"仍记 N/A, 但不再是静默的** (D5, 2026-10-07):
    盲点是真的 —— 一条"该取没取"的 run 整条从分母消失, 成绩单上它既不拉低成功率
    也不留痕迹, 读者看到的却是"取数门满分"。

    但**不能**直接把它改成判红: §6.5 的 N/A 口径是刻意设计的, 因为 B0/B1 **按装配
    就没有数据库通路** (docs/eval-E5-baseline-ablation.md §3.2), 它们交白卷是结构性
    不可完成, 记 0 会把"这套装配里压根没有这个零件"说成"这个零件坏了"。
    真正的问题是 gate_F **分不清**这两种白卷 —— 而判据层拿不到"这套装配有没有数据
    通路"这个事实 (它在 systems/ 装配表里, 按零跨实验 import 纪律本层不该去 import)。

    所以这一轮的修法是**让排除可审计**而不是改判据: :func:`aggregate` 另计
    ``gate_F_na_runs``, 让"有多少条 run 因为交白卷而退出分母"在成绩单上看得见。
    想真正判红需要先给 run 记录补一个能力位, 那是一次 harness 侧改动, 见
    ``gate_F_na_runs`` 的注释。
    """
    gold = _derive_gold_fields(item.get("gold_result") or {})
    # 无 case_id 即没有可比金标准: 判了也只能凭空造基准, 不如显式 N/A
    if not gold.get("case_id"):
        return None
    if not (run.get("tool_calls") or []) and not (run.get("row_keys") or []):
        # 无任何取数尝试: 取数门 N/A (E5 §6.5)。是否"该取没取"由
        # gate_F_na_runs 单独记账, 不在这里改判 —— 见本函数 docstring 的取舍说明。
        return None
    reported = run.get("reported") or {}  # 报告态取自 run: 三元组与四态都拿被测系统的自述
    first_row = run.get("first_row") or {}
    observed = [str(k) for k in run.get("row_keys") or []]  # 实得主键: 位置不敏感, 已由 row_key 归一到 E2 口径
    gold_keys = [str(k) for k in gold.get("row_keys") or []]
    # 抽样主键: 大结果集的金标准只给样本, 全量主键不可得
    sample = [str(k) for k in gold.get("row_keys_sample") or []]
    expected_count = int(gold.get("row_count") or 0)  # 期望行数独立于主键集: 少取一页只有这条抓得到
    # 全量主键 → P/R 都算; 抽样主键 (大结果集) → 只算召回, 精度退化为"抽样是否全中"
    sampled = bool(sample) and not gold_keys                                                    # 只在有抽样而无全量主键时降级: 两种情况口径不同
    # 抽样时以样本为期望集: 没样本又没全量的题不该被算成"一条都没取到"
    exp = set(gold_keys) if gold_keys else set(sample)  # 抽样时以样本为期望集, 不让"没样本又没全量"的题算成零命中
    act = set(observed)                                 # 实得去重: 同一行出现在多页只算一条
    overlap = len(exp & act)                                                                        # 交集大小: 少返与多返都由它推
    # 期望为空但实得非空 → 0.0: 多取也是错, 不能因为没有分母就放行
    recall = (overlap / len(exp)) if exp else (1.0 if not act else 0.0)                           # 召回按期望集算; 期望为空时再看实际是否也空
    # 抽样主键只验召回; 精度退化为"抽样是否全中" (大结果集的全量主键不可得)
    precision = ((1.0 if recall >= 1.0 else 0.0) if sampled                                     # 抽样口径下精确率退化为二值: 只有全召回才算干净
                 else ((overlap / len(act)) if act else (1.0 if not exp else 0.0)))               # 非抽样口径按实际集算: 期望空且实际空记满分
    # 行数也要对: 主键集合对但少取一页的情况, 靠这条才抓得到
    count_ok = len(observed) == expected_count                                                   # 行数一致单独记: 少返与多返在这一项上直接可比
    hits, total = 0, 0  # 字段级命中/总数: 分子分母同口径才算得出比例
    for name, expected in (gold.get("key_values") or {}).items():
        # 只核 first_ 前缀的键: 它们描述"首行长什么样", 才是行级对账的基准
        if not name.startswith("first_"):
            continue
        total += 1                                                                            # 每进一个可比字段就扩大分母: 字段一致率因此是可加的
        actual = _cell(first_row, name[len("first_"):])
        if expected is None:                                                             # gold 期望缺失: 实测也缺才算对, 填 0 或填哨兵都判错
            # gold 期望缺失: 实测也必须是 None, 填 0 或填哨兵都算不一致
            hits += 1 if actual is None else 0                                                     # 双缺才计命中: 期望缺失却报出数值同样判错
        elif actual is not None and _close(actual, expected):
            hits += 1                                                                           # 双有且在容差内计命中: 这一项是字段一致的主路径
    # 无 first_ 键时记 1.0 而不是 0.0: 没有基准就没有不一致可言, 记 0 会凭空
    # 制造一条字段不一致的 blocker
    field_rate = (hits / total) if total else 1.0                                                 # 无可比字段记满分: 分子分母都空时不该判失败
    trunc = gold.get("truncation") or {}  # 截断三元组: truncated+total+returned 缺一即错判
    # 三元组必须三项齐: 少 truncated 就没有"截断了却不承认"这一类错判
    triple = {"truncated": bool(reported.get("truncated")),
              "total_count": reported.get("total_count"),
              "returned_count": reported.get("returned_count")}
    # 三项逐个比而不是整体比: 报单条错项才能在报告里看出是截断标记还是计数错
    triple_ok = (triple["truncated"] == bool(trunc.get("truncated"))
                 and _eq(triple["total_count"], trunc.get("total_count"))
                 and _eq(triple["returned_count"], trunc.get("returned_count")))
    state_ok = _state_ok(gold, reported)  # M5 四态: ERROR/EMPTY/ROWS 不得互相冒充
    blockers = []                                                                               # 阻断清单: 空即取数门全过, 非空即具体哪项破了
    if precision < 1.0 or recall < 1.0:                                                            # 行集不满分即记阻断: 少返与多返都算这一项
        blockers.append(f"rowset P={precision:.2f}/R={recall:.2f}")
    if not count_ok:                                                                            # 行数不一致记阻断: 它是最容易掩盖的一类取数缺陷
        blockers.append(f"row_count {len(observed)}!={expected_count}")
    if field_rate < 1.0:                                                                         # 字段一致率不满分记阻断: 报出的值与真值对不上
        blockers.append(f"field_consistency={field_rate:.2f}")
    if not triple_ok:                                                                        # 截断三元组不自洽记阻断: 这是"把截断说成全量"的现场
        blockers.append(f"trunc_triple={triple}")
    if not state_ok:  # M5 四态: ERROR/EMPTY/ROWS 不得互相冒充
        blockers.append(f"state={reported.get('state')}!={gold.get('result_state')}")
    return {"pass": not blockers, "blockers": blockers,
            "row_precision": round(precision, 4), "row_recall": round(recall, 4),
            # F1 也要防除零: 精度与召回同时为 0 时 (一条没对上一条也没多) 给 0.0
            "row_f1": round(2 * precision * recall / (precision + recall), 4)
            if (precision + recall) else 0.0,
            "field_consistency": round(field_rate, 4), "trunc_triple": triple,
            "trunc_triple_ok": triple_ok, "state_ok": state_ok,
            "state": reported.get("state")}


def _state_ok(gold: dict, reported: dict) -> bool:
    """M5 四态判定: gold.result_state 与观测态必须一致 (ERROR↔EMPTY 零容忍)。"""
    # 缺省都是 rows: 老题面没写 result_state 时按有行结果判
    expected = str(gold.get("result_state") or "rows")  # 缺省 rows: 老题面没写 result_state 时按有行结果判
    observed = str(reported.get("state") or "rows")
    if expected == "error":
        # 错误态还要对错误码: 显式失败可以换个理由, 但不能悄悄改成空结果
        code = gold.get("error_code")
        return observed == "error" and (code in (None, "")
                                        or reported.get("error_code") == code)
    return observed == expected


def _cell(row: dict, column: str) -> Any:
    """行内取列 (全限定名 / 裸名 / proximity 回连列 / 波段字典 依次尝试)。

    候选键按序: 原名 → ``inputobjs_`` 回连形 → 点号限定形的裸名 → 剥掉**已知
    星表前缀**后的裸名 (``ps1_rpsf`` → ``rpsf``)。刻意不用"第一个下划线段"
    当前缀剥 — ``dist_arcsec`` 会被误剥成 ``arcsec`` 而取不到值 (踩过)。
    """
    name = str(column)                                                                            # 列名先归一成字符串: 参数面里可能是别的类型
    candidates = [name, f"inputobjs_{name}", name.split(".")[-1]]  # 候选键四种形态: 原名 / 回连形 / 点号裸名 / 剥已知前缀
    # 只剥**已知**前缀: 遇到第一个命中就 break, 否则长前缀可能被短前缀抢走
    for prefix in _TABLE_PREFIXES:                                                               # 逐前缀试: 前缀集已按长度降序, 长前缀先命中
        if name.startswith(prefix):                                                                 # 命中即剥: 剥完得到裸列名
            bare = name[len(prefix):]                                                          # 按前缀长度切片: 不用替换, 免得剥掉列内同名片段
            candidates += [bare, f"inputobjs_{bare}"]
            break
    for key in candidates:                                                                        # 候选列名依次试: 全限定与裸形两种形态都要认
        if key in row and row[key] not in (None, ""):
            return row[key]
    # 波段字典是嵌套形态: 平铺取列会全落空, 测光类结果必须翻这两层
    for bucket in ("magnitudes", "magnitude_errors"):
        values = row.get(bucket) or {}                                                              # 翻嵌套字典: 光变类结果把测光塞在桶里
        for key in candidates:                                                                      # 桶内同样两种形态都试
            if key in values:                                                                       # 命中即取: 平铺取列会在这类结果上全落空
                return values[key]
    return None


def _close(actual: Any, expected: Any) -> bool:
    """数值比对 (|a-b| ≤ atol + rtol·|b|; atol=1e-6 与 evals/_data 容差表同档)。"""
    left, right = _as_float(actual), _as_float(expected)  # 两边同口径转 float: 星等列有文本形态, 强转会误判
    # 一侧不是数值就退成字符串比对: 星等列有时是文本形态, 强转会误判不一致
    if left is None or right is None:                                                               # 任一侧取不到即不可比: 不拿 0 顶替
        return str(actual).strip() == str(expected).strip()
    # 相对容差挂在 expected 上: gold 是真值, 观测侧的表示误差不该算成不一致
    return abs(left - right) <= 1e-6 + 1e-6 * abs(right)


def _eq(actual: Any, expected: Any) -> bool:
    """计数比对 (容差 1e-9; 与 evals/_data 的 count 档一致)。"""
    left, right = _as_float(actual), _as_float(expected)                                            # 两侧统一转数值再比: 文本形态也要能机比
    # 计数比字段一致度更严: 1e-9 足以吸收整数转浮点的尾数, 又不会放过真差异
    if left is None or right is None:                                                               # 转不动即不可比: 记失败而不是当作相等
        return actual == expected
    return abs(left - right) <= 1e-9


def gate_E(item: dict, run: dict) -> dict:
    """表述门 (E3 机器可判子集): 断言全中 ∧ 无禁答 ∧ 无致命无来源数值 ∧ 无哨兵误用。"""
    answer = str(run.get("answer_text") or "")
    assertions = item.get("assertions") or {}
    critical = list(assertions.get("critical") or [])   # 不强转 str: 允许 {any_of: [...]} 形态 (语义近义须显式声明)
    forbidden = [str(f) for f in assertions.get("forbidden") or []]  # 禁答短语同理: 命中即算"说错了话"
    # 关键断言走**表示归一** (metrics/assertions.py, 2026-10-10): 裸子串命中只在"答案是渲染层
    # 按模板产出的原文"时成立 —— 那对 ScriptedLLM 替身臂成立, 对 live 臂的自由行文不成立。
    # 实测同一批采集表里 「共 3 个源」被判缺 "3 行"、「未截断」被判缺 "truncated=false",
    # 使 E 门通过率在三次重复间变成 0.433/0.100/0.067 (决策逐字相同, 只有措辞不同),
    # 正是 add-back 极差 0.367 的成因。归一**只动表示, 不补事实**: 没说的事实照样判缺。
    matched = match_critical(answer, critical)
    missing = matched["missing"]                                    # 驱动判定: 归一后仍缺才算缺
    missing_strict = matched["missing_strict"]                      # 披露面: 裸子串口径, 与旧实现逐字可比
    # 禁答**保持裸子串**: 它测的是"说了不该说的话", 给近义开口子等于让话术逃逸
    # (test_gate_e_forbidden_hit 钉住这条口径, 不许被归一化顺手放宽)。
    hits = [f for f in forbidden if f in answer]
    numbers = check_unsourced_numbers(answer, value_pool(item, run))  # 无来源数值: 分母是 value_pool(item, run), 不是全库
    sentinel = check_sentinel_misuse(answer)                          # 哨兵误用与 E3 同源判据, 跨实验等价性无断言覆盖(靠人工同步)
    claims = check_unsupported_claims(answer)                                                       # 无支撑主张单独一趟: 它与短语判据正交
    blockers = []  # 门条件清单: 报告逐条展示, 合成一句会丢可归因性
    if missing:                                                                                   # 关键断言缺失记阻断: 该说的没说比说错更要紧
        blockers.append(f"missing_critical={missing}")
    if hits:                                                                                        # 命中禁答短语记阻断: 说错比不说更严重
        blockers.append(f"forbidden_hit={hits}")
    if numbers["fatal"]:
        # 只报 kind 不报全部明细: 致命编造必判, 明细留给 ungr 与报告表去展开
        blockers.append(f"fatal_number={[f['kind'] for f in numbers['fatal']]}")
    if sentinel:                                                                                    # 哨兵候选记阻断: 当成真实值用属于硬错误
        blockers.append("sentinel_misuse")
    # 无支撑主张 (HR_claim) 不进 blockers: 它是代理指标, 机器预筛比盲评弱,
    # 拿它当门条件会把 E5 的通过率绑死在一个近似量上
    return {"pass": not blockers, "blockers": blockers,
            "critical_missing": missing, "critical_missing_strict": missing_strict,
            "critical_entries": matched["entries"],
            # 事实层 (2026-10-10): 从**本次观测**现导事实, 再查答案是否如实陈述。
            # 与 critical 并列而不取代它 —— 两套读数各自披露, 读者能看出差在哪。
            # 存在的理由: critical 里写死的数值已与冻结数据脱钩 (D02/D03 断言 "2 行"
            # 而观测 174 行), 使任何诚实作答者都不可能通过; 事实层跟着观测走, 不会过期。
            "facts": facts_pass(answer, run),
            "forbidden_hits": hits,
            "fatal_numbers": numbers["fatal"], "sentinel_misuse": sentinel,
            "unsupported_claims": claims, "unsourced_numbers": numbers["unsourced"],
            "ungr": round(numbers["ungr"], 4)}


# ── 合成指标 ────────────────────────────────────────────────────────────────

def score_run(item: dict, run: dict) -> dict:
    """一条 run 的三门判定 (F 门对非 D 类返 None = N/A)。"""
    # 三个门平铺返回: 调用方按名字取, 不引入额外的嵌套层
    return {"item": item.get("id"), "system": run.get("system"),  # 三门平铺返回: 调用方按名字取, 不引入额外嵌套层
            "D": gate_D(item, run), "F": gate_F(item, run), "E": gate_E(item, run)}


def aggregate(runs: list[dict], items: list[dict]) -> dict[str, dict]:
    """按系统聚合成绩单 (比例型指标取三次重复的多数, 同时报极差)。"""
    # 任务表按 id 建索引: runs 里只存 item id, 不存整条任务
    by_item = {str(i.get("id")): i for i in items}  # 任务表按 id 建索引: runs 只存 item id, 不存整条任务
    grouped: dict[str, list[tuple[dict, dict]]] = {}                                                # 按系统与任务分组: 多次重复要能互相对账
    for run in runs:                                                                          # 逐 run 归组: 确定性自证与逐项对账都用这份分组
        item = by_item.get(str(run.get("item")))
        # 找不到任务就跳过这条 run: 它没有可比基准, 计入分母只会污染成绩单
        if item is not None:                                                             # 缺任务详情的 run 不进分组: 报告里点不出是哪题就没法复核
            grouped.setdefault(str(run.get("system")), []).append((item, run))
    return {system_id: _card(system_id, pairs)
            for system_id, pairs in sorted(grouped.items())}                                        # 组内按系统名排序: 报告列序要稳定可比


def _card(system_id: str, pairs: list[tuple[dict, dict]]) -> dict:
    """一个系统的成绩单: 三门通过率 + ESR 三件套 + 幻觉三通道 + 拒绝/澄清 + 代价。"""
    scored = [(item, run, score_run(item, run)) for item, run in pairs]  # 三门一次算完: _card 反复取用, 重算会把耗时放大 N 倍
    # 分域靠 id 前缀: D 类 (E5-Dnn) 查数据, C/R/S 类查知识与口径 —— 两套分母
    d_items = [t for t in scored if str(t[0].get("id")).startswith("E5-D")]  # 分域靠 id 前缀: D 类查数据, C/R/S 查知识与口径 —— 两套分母
    know_items = [t for t in scored if not str(t[0].get("id")).startswith("E5-D")]
    # D 类要三门齐过才算成: 决策对了但取数错, 对用户仍然是失败
    d_pass = [t for t in d_items if t[2]["D"]["pass"] and t[2]["F"] and t[2]["F"]["pass"]
              and t[2]["E"]["pass"]]
    # 知识类没有取数门 (F 为 None), 只看决策与表述
    know_pass = [t for t in know_items if t[2]["D"]["pass"] and t[2]["E"]["pass"]]
    rejects = [t for t in scored if str(t[0].get("id")).startswith("E5-R")]    # R 类"该拒"单独成类算 RejectAcc
    clarifies = [t for t in scored if str(t[0].get("id")).startswith("E5-C")]  # C 类"需澄清"单独成类算 MissedClarify
    # 过度拒绝只在 D/C 上看: R 类"该拒"与 D/C"不该拒"方向相反, 混在一起会互相抵消
    d_and_c = [t for t in scored if str(t[0].get("id")).startswith(("E5-D", "E5-C"))]
    # with_f 是 F 门的真实分母: 只有 F 非 None 的题才进, 这就是 N/A 不进分母的落点
    with_f = [t for t in scored if t[2]["F"]]  # F 门真实分母: 只有 F 非 None 的题才进, N/A 不进分母的落点
    # D5 (2026-10-07): N/A 的**条数**单独记账。分母少了几条是合法的 (§6.5), 但
    # "少了几条"本身以前看不出来 —— 读者只看到 gate_F 的比率, 无从知道有多少条 run
    # 因为交白卷而整条退出分母。把分母显式印出来, "满分"才不再掩盖"没考"。
    # 注意: 它**不参与**任何判定, 只是可审计性 —— 判红还是 N/A 是 harness 侧能力位的事。
    d_na = len([t for t in d_items if not t[2]["F"]])
    return {
        "system": system_id, "n_tasks": len(scored),
        "ESR_data": _rate(d_pass, d_items),             # D 类分域 ESR: 只用 D 题的分母
        "ESR_know": _rate(know_pass, know_items),       # 知识类分域 ESR: 只用非 D 题的分母
        "ESR_full": _rate(d_pass + know_pass, scored),  # 全集 ESR: D 域与知识域合并成一条的总体成功率
        "gate_D": _rate([t for t in scored if t[2]["D"]["pass"]], scored),
        "gate_F": _rate([t for t in with_f if t[2]["F"]["pass"]], with_f),
        # F 门的分母与退出分母的条数 (D5): 两者一起看才完整 —— 只有比率没有分母时,
        # "1.00" 既可能是"90 条全过"也可能是"0 条参与"
        "gate_F_n": len(with_f),
        "gate_F_na_runs": d_na,
        "gate_E": _rate([t for t in scored if t[2]["E"]["pass"]], scored),
        # ToolSetF1/RowF1/FieldConsistency 走中位数: repeat 的目的是看稳定性,
        # 均值会被单次异常拉走, 中位数给出"典型一次"的结果
        "ToolSetF1": _median([t[2]["D"]["tool_set_f1"] for t in scored]),
        # 反向计: 无幻觉的题占比才是 ParamF1, 幻觉条数另记一行
        "ParamF1": _rate([t for t in scored if t[2]["D"]["param_hallucination"] == 0], scored),
        "ParamHallucination": sum(t[2]["D"]["param_hallucination"] for t in scored),
        "RowF1": _median([t[2]["F"]["row_f1"] for t in with_f]),
        "FieldConsistency": _median([t[2]["F"]["field_consistency"] for t in with_f]),
        "TruncTriple": _rate([t for t in with_f if t[2]["F"]["trunc_triple_ok"]], with_f),
        # 幻觉三通道: 各自独立记比例, HR_any 是三者的复合 (见 _any_hallucination)
        "HR_param": _rate([t for t in scored if t[2]["D"]["param_hallucination"] > 0], scored),
        "HR_num": _rate([t for t in scored if t[2]["E"]["unsourced_numbers"]], scored),
        "HR_claim": _rate([t for t in scored if t[2]["E"]["unsupported_claims"]], scored),
        "HR_any": _rate([t for t in scored if _any_hallucination(t[2])], scored),
        "HR_fatal": _rate([t for t in scored if t[2]["E"]["fatal_numbers"]], scored),
        # 拒绝与澄清: RejectAcc 是分级均值 (1.0/0.5/0.25/0.0), 不用比例
        "RejectAcc": _mean([_reject_score(i, r, s) for i, r, s in rejects]),
        "OverRejectRate": _rate(_over_rejects(d_and_c), d_and_c),
        "MissedClarify": _rate([t for t in clarifies if not t[2]["D"]["route_ok"]], clarifies),
        # AvgCalls / AvgTurns 是成本面: 取均值, 因为要看的是"典型一题花多少"
        "AvgCalls": _mean([float(len(t[1].get("tool_calls") or [])) for t in scored]),
        "AvgTurns": _mean([float(t[1].get("turns") or 1) for t in scored]),
        # http_requests 是实测求和, 不是比例: 成本总量而非成本比率
        "http_requests": sum(int((t[1].get("cost") or {}).get("http_requests") or 0)  # 实测求和而非比例: 这是成本总量, 不是成本比率
                             for t in scored),
        # token 两列恒 None: API 不返 usage, 估算填数会污染成本结论 (§6.7)
        "tokens_in": None, "tokens_out": None,  # 两列恒 None: API 不返 usage, 估算填数会污染成本结论 (§6.7)
    }


def _any_hallucination(scored: dict) -> bool:
    """三通道任一命中即 HR_any (E5 §6.4 复合主指标)。"""
    # 或关系而不是计数: 只要有一条通道命中就是"出现了幻觉", 逐条加权的口径
    # 会被两个空通道稀释, 掩盖住那条真幻觉
    return bool(scored["D"]["param_hallucination"] or scored["E"]["unsourced_numbers"]
                or scored["E"]["unsupported_claims"])


def _reject_score(item: dict, run: dict, scored: dict) -> float:
    """单条 R 任务的拒绝得分 (E1 §6.6 口径, 分级而非二值)。

    1.0 = 路由 reject ∧ 未调被禁工具 ∧ 关键断言全中 (理由码 + 替代路径齐全);
    0.5 = 路由对 ∧ 未调被禁工具 ∧ 断言部分命中 (缺替代路径);
    0.25 = 路由对 ∧ 未调被禁工具但几乎没给出依据 (仅声明不支持);
    0.0 = 路由错 (该拒没拒) 或仍调了被禁工具。
    """
    # 路由错直接 0.0: 该拒没拒是硬错, 说得再清楚也救不回来
    if not scored["D"]["route_ok"]:
        return 0.0
    banned = {str(b) for b in (item.get("reject") or {}).get("must_not_call") or []}  # 被禁工具集取自题面: 判据必须与题面同源, 不由本层猜
    called = {str(c.get("tool")) for c in run.get("tool_calls") or []}
    # 调了被禁工具同样 0.0: 拒了却照查, 代价是真发出去了请求
    if banned and (banned & called):                                                         # 调了明令禁止的工具即判失败: 拒绝失效是最严重的路由错
        return 0.0
    critical = [str(c) for c in (item.get("assertions") or {}).get("critical") or []]
    answer = str(run.get("answer_text") or "")
    hit = sum(1 for c in critical if c in answer)  # 断言命中数: 后面按 1.0/0.5/0.25 三档映射
    # 断言命中数 → 得分 (E1 §6.6: 全中 1.0 / 部分 0.5 / 仅声明 0.25)
    return 1.0 if (critical and hit == len(critical)) else (0.5 if hit else 0.25)


def _over_rejects(d_and_c: list[tuple[dict, dict, dict]]) -> list:
    """过度拒绝 (反向指标): D/C 类上错误宣称"不支持" (E5 §6.5)。"""
    out = []                                                                                  # 可比对的样本逐条攒: 只有 D/C 两类题进这个口径
    for item, run, scored in d_and_c:                                                             # 逐条过一遍: 拒绝正确率只在这两类题上有意义
        answer = str(run.get("answer_text") or "")
        # 两个条件缺一不可: 光说"不支持"不一定是过度拒绝 (澄清轮本来就该问),
        # 必须同时路由判错才说明"该做没做还嘴硬"
        if "不支持" in answer and not scored["D"]["route_ok"]:
            out.append((item, run, scored))                                                        # 命中即入列: 报告要能点名是哪几题拒绝对了
    return out


def _median(values: list[float]) -> Optional[float]:
    """中位数 (空集 → None; 三次重复取中位数, E5 §8 稳定性口径)。"""
    # 空集返 None 而不是 0.0: 没有可比的题就没有中位数, 记 0 是 §11 阻断项 3
    if not values:                                                                            # 空样本直接返回: 中位数无从定义, 不返回 0 冒充
        return None
    ordered = sorted(values)                                                                     # 排序后取中位: 不排序的话偶数样本会取错那一半
    middle = len(ordered) // 2                                                                      # 中位下标: 奇数与偶数两种取法在这里分叉
    # 奇数个取正中那个
    if len(ordered) % 2:                                                                            # 奇数取正中一个, 偶数取中间两个的平均
        return round(float(ordered[middle]), 4)
    # 偶数个取中间两数的均值: repeat=2 时也走这一支
    return round((ordered[middle - 1] + ordered[middle]) / 2.0, 4)


def _mean(values: list) -> Optional[float]:
    """均值 (空集 → None; AvgCalls/AvgTurns/RejectAcc 的口径, E5 §6.6)。"""
    # 同样空集返 None: 与 _median 保持同一条分母不变式, 报告里 N/A 才一致
    if not values:                                                                                  # 空样本同样直接返回: 均值也无从定义
        return None
    return round(sum(float(v) for v in values) / len(values), 4)  # 同样空集返 None: 与 _median 同一条分母不变式


def _rate(numerator: list, denominator: list) -> Optional[float]:
    """比例 (分母空 → None = N/A, **不许记 0** — E5 §11 阻断项 3)。"""
    # 分母为空就是"该指标对此系统无意义", 例如 B0/B1 没有工具面; 记 0 会被读成
    # "这个系统什么都做不对", 跨系统比较的分母就被污染了
    if not denominator:                                                                    # 分母为零时不返回 0: 那会把"无法计算"读成"结果为零"
        return None
    return round(len(numerator) / len(denominator), 4)  # 分母空即 N/A, 记 0 会被读成"什么都做不对"
