# -*- coding: utf-8 -*-
"""evals.ablation.metrics.facts — 表述门的**事实层**: 从观测现导事实, 不再在 YAML 里写死。

**为什么需要它 (2026-10-10, 实证)**: `items.yaml` 的 `critical` 断言里写死了具体数值,
而这些数值**已与冻结数据脱钩**。普查 (`temp/e5_assertion_fact_audit.py` + `temp/e5_expect_vs_actual.py`):

| 题 | 应然查询 (items.yaml 声明) | 冻结快照观测 | critical 声称 |
|----|--------------------------|-------------|--------------|
| D02 | 60″ cone, sort ps1_rpsf | **174 行** | "2 行" |
| D03 | 300″ cone | **174 行** | "2 行" |
| D04 | 60″ cone + describe_catalog | **5 行** | "2 行" |
| D06 | 18000″ cone, max_rows 3000 | **0 行, truncated=False** | "3700"/"3000"/"truncated=true" |
| D07 | 60″ cone @dec=0 + fetch_page p2 | **0 行** | "2 行"/"17.55" |
| D09 | proximity batch | **3 行** | "1 个输入无匹配"/"4 行" |

且这 6 题的**实然查询与应然声明逐字相同** —— 所以不是探针选错, 是**断言写错了**。
后果: 表述通道要求作答者陈述**与数据矛盾**的数值, 于是任何诚实的作答者都不可能通过 ——
实测独立重采 90 个会话后该通道塌缩到 3.4% (`docs/e5-expression-channel-rebuild-verdict.md`)。

**修法**: 事实不再写死在 YAML, 而是**在判定时从该 run 的真实观测现导**:
行数 / 服务端总数 / 截断位 / 稳定引用 / content_trust。这样断言**不可能再过期** ——
素材换一代, 事实跟着观测走。

**边界 (不越权)**: 本层只查"观测里**有**的事实有没有被如实陈述"; 它**不**判
"该不该调这个工具"(那是 D 门)、也**不**放松禁答与无来源数值的检查 (仍在 gate_E 里)。
"""
from __future__ import annotations

# 标准库: 正则 (取稳定引用的路径段)
import re

# 本地: 概念抽取 (计数/截断的表示归一) —— 与 critical 断言同一套口径, 不另造第二套
from evals.ablation.metrics.assertions import canonicalize, concepts

# 稳定引用的可核对片段: 只比 "scheme://catalog/path" 这一段, 后面的查询串允许写法差异
_URI_RE = re.compile(r"(best://[a-z0-9_]+/[a-z_]+)", re.IGNORECASE)


def expected_facts(run: dict) -> list[dict]:
    """从一次 run 的**真实观测**导出应被陈述的事实清单。

    Args:
        run: 逐 run 轨迹 (须含 ``reported`` 信封面)。

    Returns:
        事实清单; 每项 ``{"kind", "value", "label"}``。``kind`` 决定比对方式:
        ``count`` / ``flag`` 走概念比对 (允许 "3 个源" 顶 "3 行"), ``text`` 走字面比对。
    """
    reported = run.get("reported") or {}
    facts: list[dict] = []
    for key, label in (("returned_count", "实返行数"), ("total_count", "服务端总数")):
        value = reported.get(key)
        if isinstance(value, (int, float)):                       # 计数缺失 (N/A) 不导出: 不许凭空要求
            facts.append({"kind": "count", "value": int(value), "label": label})
    truncated = reported.get("truncated")
    if isinstance(truncated, bool):                               # 截断位是布尔: 观测有才要求陈述
        facts.append({"kind": "flag", "value": truncated, "label": "截断位"})
    provenance = reported.get("provenance") or {}
    uri = str(provenance.get("stable_uri") or "")
    match = _URI_RE.search(uri)
    if match:                                                     # 只在观测**确有**稳定引用时才要求
        facts.append({"kind": "text", "value": match.group(1), "label": "稳定引用"})
    trust = str(provenance.get("content_trust") or "")
    if trust:                                                     # content_trust 同理
        facts.append({"kind": "text", "value": trust, "label": "内容可信标注"})
    return facts


def check_facts(answer: str, run: dict) -> dict:
    """判"观测里有的事实, 答案陈述了没有"。

    Args:
        answer: 答案正文。
        run: 逐 run 轨迹 (事实从这里现导)。

    Returns:
        ``{"expected", "stated", "missing"}``; ``missing`` 为未被陈述的事实标签清单。
    """
    canon = canonicalize(answer)                                  # 归一一次: 循环里反复算没意义
    have = concepts(answer)                                       # 答案的概念集 (计数/截断)
    expected = expected_facts(run)
    stated: list[str] = []
    missing: list[str] = []
    for fact in expected:
        kind, value = fact["kind"], fact["value"]
        if kind == "count":
            # 计数走**概念级**: "3 个源" 顶 "3 行"。
            # **为什么不用"数字本身出现"这条更松的判据 (2026-10-10 实测否决)**:
            # 试过补一条独立数值 token 的判据, 结果通过率从 0.241 飙到 **0.966**,
            # 直接顶到天花板 -> 分辨力丧失 -> 该通道又变成不可用 (橡皮图章)。
            # 实测两版对照: 概念级 pooled=0.241 p=0.718 **可用**; 数值 token 版
            # pooled=0.966 **退化**。故保留概念级: 它要求"带量纲地把计数说清楚",
            # 这既是真实的报告质量, 也是这个指标唯一有分辨力的形态。
            hit = f"count:rows={value}" in have
        elif kind == "flag":
            hit = f"flag:truncated={str(value).lower()}" in have  # 截断走概念: "未截断" 顶 "truncated=false"
        else:
            hit = canonicalize(str(value)) in canon               # 文本走归一后的字面
        (stated if hit else missing).append(fact["label"])
    return {"expected": expected, "stated": stated, "missing": missing}


def facts_pass(answer: str, run: dict) -> dict:
    """事实层的通过判定 (供 gate_E 作为**附加读数**挂上, 不单独决定放行)。"""
    result = check_facts(answer, run)
    return {"pass": not result["missing"], "missing": result["missing"],
            "n_expected": len(result["expected"]), "n_stated": len(result["stated"])}
