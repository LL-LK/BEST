# -*- coding: utf-8 -*-
"""evals.ablation.report — E5 报告渲染 (docs/eval-E5-baseline-ablation.md §12 五张表)。

职责: 把 runner 的成绩单渲染成 Markdown 人工复核面 — 五张主表:
  ① 主表 (T1: 11 装配 = 10 系统 + sham, × T1_COLUMNS 11 个物理列; N/A 显式标注)
  ② 消融效应表 (T2 贡献分解: Δ1/Δ2/Δ3 与 A1–A5 的 ΔESR + 预登记逐条核对)
  ③ sham + add-back 可靠性表 (掉分可归因、可恢复)
  ④ 幻觉三通道表 (HR_param / HR_num / HR_claim + HR_any + HR_fatal)
  ⑤ 成本-边际表 (http_requests / token / 边际成本 Δcost/ΔESR)

另附 §12 的 T4 统计表 (McNemar/Holm/bootstrap/效力) 与 T5 错误谱系归因 —
二者需真实模型跑批与 L2 抽样, 未跑时**显式标"待跑"而不是填空数** (空数是失真)。

所属实验: E5 基线与消融 (30 任务 × 10 系统 + sham 共 11 装配, ScriptedLLM 离线跑;
成功率 = ScriptedLLM 跑通率而非模型能力), 方案真值 docs/eval-E5-baseline-ablation.md
§12 (报告必须披露的 5 张表) / §6.4 (诚实声明) / §8 (统计与效力)。本文件是 E5 的
**呈现层**, 不参与任何判定 —— 数字全部来自 metrics/composite.aggregate 的成绩单。

对外接口: render_report(cards, hypotheses, broken, meta) -> Markdown 文本;
_fmt / _delta (格式化原语, N/A 与缺值的统一出口); _esr / _esr_data / _esr_know /
_avg (成绩单取值小工具, 缺系统一律返 None 而非 KeyError)。

依赖与数据流: 输入 = aggregate() 的 {系统 id: 成绩单} + hypotheses.yaml 全文 +
run_broken_selftest() 的返回 + 跑批元信息 dict; 产物 = Markdown 字符串, 由
evals/ablation/runner.py 落盘到 --md 指定路径 (JSON 那份才是数据权威)。

关键契约与不变量: 离线回放 —— 全部数字来自 ScriptedLLM 回放, rate_limit 归零,
不接真实模型、不打真实站点; 零跨实验 import —— 唯一共享件是 evals/_data/ 纯数据
字典, 本文件不 import 它, 也不 import 其它实验的代码; N/A 一律显式标注, **绝不
记 0** (分母口径见 §6.5, 记 0 是 §11 阻断项 3); 预登记假设跑后只核对不改写
(HARKing 是 §11 阻断项 6)。

陷阱与边界: 语义类指标 (表述门 / HR_num / HR_claim) 走机器预筛, 比 E3 的双专家
盲评弱, 报告头必须挂诚实声明 —— 否则读者会把它当绝对结论; Δ1 (B0→B1) 在 scripted
模式下**结构性不可分辨** (答案只由四个组件开关驱动, B1 的公共文档知识未建模),
报告必须显式披露这一点而不是让 Δ1=0 看起来像"文档知识没用"; sham 与 A2 在
scripted 下同样不可区分 (换入的等长无关文本不改变断言覆盖), 这是模式边界不是
消融结论, 所以写进"待跑项"表而不是写进结论表。

白盒锚点: docs/eval-E5-baseline-ablation.md §12 (报告必须披露的 5 张表) /
§6.4 (诚实声明: 语义指标是代理指标) / §8 (统计与效力)。
"""
from __future__ import annotations

# 标准库: 类型标注
from typing import Any, Optional  # 本层唯一 import: 零跨实验依赖, 共享件只按路径读不 import

# 键名必须与成绩单逐字对齐: 写错一个键 _fmt 会安静地渲染成 N/A, 表里看不出错在哪
T1_COLUMNS: tuple[tuple[str, str], ...] = (  # 主表指标列: 顺序即论文主表列序, 键与 _card 一一对应
    ("ESR_full", "ESR_full"), ("ESR_data", "ESR_data"), ("ESR_know", "ESR_know"),  # 三段 ESR: 掉分里有多少来自取数、多少来自知识
    ("ToolSetF1", "ToolSetF1"), ("ParamF1", "ParamF1"),  # 工具/参数用 F1 而非准确率: 漏选与错选同罚
    ("RowF1", "结果一致率(行集F1)"), ("FieldConsistency", "字段一致率"),  # 行集 F1 + 字段一致: 多列漏列同罚, 不靠堆行抬分
    ("HR_any", "HR_any"), ("RejectAcc", "RejectAcc"),  # 幻觉与拒答: 门禁侧的两个反向指标
    ("AvgCalls", "AvgCalls"), ("AvgTurns", "AvgTurns"),  # 成本侧: 多花几轮换回多少分
)

HR_COLUMNS: tuple[str, ...] = ("HR_param", "HR_num", "HR_claim", "HR_any", "HR_fatal")  # 三通道 + 复合 + 致命; 顺序即表 4 列序


def _fmt(value: Any, digits: int = 3) -> str:
    """指标值格式化 (None → 显式 ``N/A``; 绝不把 N/A 记成 0)。

    Args:
        value: 成绩单里的原始值; None 表示该指标对此系统无意义 (N/A)。
        digits: 浮点保留位数 (默认 3; 计数类传 0 走整数形态)。

    Returns:
        渲染好的字符串; None 一律变成 "N/A" 而不是 "0.000"。
    """
    if value is None:  # N/A 与 0 语义相反: 记 0 会把"不可用"伪装成"很差" (§11 阻断项 3)
        return "N/A"
    if isinstance(value, float):  # 非 float 走 str(): 计数类指标补成 3.000 会读成精度承诺
        return f"{value:.{digits}f}"
    return str(value)


def _delta(current: Any, base: Any) -> str:
    """相对基准的差 (任一为 N/A → ``—``; 不虚构差值)。

    Args:
        current: 被比系统的指标值。
        base: 基准 (B3) 的同一指标值。

    Returns:
        带符号的三位小数差值字符串; 任一侧缺失返回 "—" (长破折号, 与数字区分)。
    """
    if current is None or base is None:  # 缺一侧就不给差: 拿 0 参与减法会造出"基线满分所以 Δ 最大"的假象
        return "—"
    return f"{float(current) - float(base):+.3f}"  # 强制 float: int 减 float 会把 1.0 显示成 "1"


def render_report(cards: dict[str, dict], hypotheses: Optional[dict] = None,
                  broken: Optional[dict] = None, meta: Optional[dict] = None,
                  mode: str = "scripted", t4_text: str = "",
                  addback_rows: Optional[list[str]] = None,
                  t5_available: bool = False,
                  runs: Optional[list] = None, items: Optional[list] = None) -> str:
    """渲染 E5 报告 (Markdown; 五张主表 + 统计/错误谱系的待跑声明)。

    Args:
        cards: ``aggregate()`` 的 {系统 id: 成绩单}。
        hypotheses: hypotheses.yaml 全文 (消融效应表的预登记核对用)。
        broken: ``run_broken_selftest()`` 的返回 (metascore)。
        meta: 跑批元信息 (n_items/n_systems/repeat/determinism/生成时间)。

    Returns:
        Markdown 文本 (由 runner 落盘; 数据权威是并排的 JSON 那份)。
    """
    meta = meta or {}              # 三个可选块都兜底: 渲染是最后一步, 少传一块不该让跑批抛异常
    broken = broken or {}          # 缺块不抛: 报告是最后一步, 不该因少传统计块而让跑批失败
    hypotheses = hypotheses or {}  # 预登记表缺失则消融段整段为空, 属可见缺跑而非默认补零
    systems = [s for s in ("B0", "B1", "B2a", "B2b", "B3", "A1", "A2", "A3", "A4", "A5", "A6")  # 未登记的系统排到后面, 让"多跑了一个"看得见
               if s in cards] + [s for s in sorted(cards) if s not in                         # 未登记的装配排到表尾, 顺序稳定又不丢新跑出来的系统
                                 ("B0", "B1", "B2a", "B2b", "B3", "A1", "A2", "A3", "A4", "A5", "A6")]
    base = cards.get("B3") or {}  # 基准恒为 B3 (完整系统): 所有 Δ 都是"相对完整系统"的差, 换基准等于换问题
    lines = [                                                                                    # 表头段: 规模与确定性先于结论, 成绩数字后置
        "# E5 基线与消融实验 — 跑批报告",
        "",
        f"- 生成时间: {meta.get('generated_at', 'N/A')}",  # 元信息缺失渲染成 N/A, 报告不预设自己知道跑了多大
        f"- 规模: {meta.get('n_items', 'N/A')} 任务 × {meta.get('n_systems', 'N/A')} 系统 "
        f"× {meta.get('repeat', 'N/A')} 次重复",
        f"- 确定性 (同 items+系统重复跑指纹一致): "  # 确定性先于结论: 指纹不一致的跑批, 下面所有 Δ 都不能当结论读
        f"{'一致' if meta.get('deterministic') else '不一致 — 见 runs'}",
        f"- 反证夹具 metascore: {broken.get('metascore', 0.0):.2f} "  # < 1.00 时后面每张表都要打问号: 判定器漏抓 = 分数不可信
        f"({broken.get('n_caught', 0)}/{broken.get('n_fixtures', 0)}; "
        "< 1.00 → 判定器失效, E5 FAIL)",
        "",
        "> **诚实声明**: 表述门与 HR_num/HR_claim 走**机器预筛** (数值可追溯性 + "  # 诚实声明前置: 读者须先看到语义指标只是代理, 再看数字
        "禁词表 + 哨兵扫描), 比 E3 的双专家盲评**弱** — 语义类指标是**代理指标**, "
        "只用于跨系统横向比较, 绝对结论以 E3 为准 (§6.4)。",
        "",
        f"## 表 1 · 主表 (T1: {len(systems)} 装配 × 11 列)",
        "",
        "| 系统 | " + " | ".join(label for _, label in T1_COLUMNS) + " | http_requests |",  # 标签取自第二元素, 与数据列同源不会错位
        "|---|" + "---|" * (len(T1_COLUMNS) + 1),
    ]
    for system_id in systems:  # 主表行: 指标列顺序由 T1_COLUMNS 决定, 不按字母序重排
        card = cards[system_id]                                                         # systems 已按存在性过滤, 这里取卡不会 KeyError
        row = [system_id]                                                             # 系统 id 占首列, 后续列一律按 T1_COLUMNS 的列序追加
        row += [_fmt(card.get(key)) for key, _ in T1_COLUMNS]  # 按列序取键, 缺键统一走 N/A 出口而不是 KeyError
        row.append(_fmt(card.get("http_requests"), 0))     # 成本列走整数形态: 请求数是小计数, 三位小数没有信息量
        lines.append("| " + " | ".join(row) + " |")        # 两端竖线包住整行, 中间各列用 " | " 连
    lines += [                                                                                 # N/A 口径紧跟主表: 读表的人当场知道分母怎么算
        "",
        "N/A = 该指标对此系统无意义 (无工具面即无工具/参数/取数类指标), "
        "**不进分母** (§6.5; 误记为 0 是 §11 阻断项 3)。",
        "",
        "## 表 2 · 消融效应表 (T2 贡献分解 + 预登记核对)",
        "",
        "### 2.1 四级基线增量 (Δ)",
        "",
        "| 对照 | 含义 | ΔESR_full | ΔESR_data | ΔESR_know | ΔAvgCalls |",  # 表 2.1 只放基线链四段增量, 单组件消融行留给 2.2
        "|------|------|-----------|-----------|-----------|------------|",
    ]
    for label, left, right, meaning in (  # 四段增量: 每段只加一个零件, Δ 之和才是这条链的贡献
            ("Δ1", "B0", "B1", "文档上下文的贡献"),
            ("Δ2", "B1", "B2a", "数据库接入 (裸协议) 的贡献"),
            ("Δ2b", "B2a", "B2b", "原子工具抽象的贡献"),
            ("Δ3", "B2b", "B3", "Skill 约束与领域知识的贡献")):
        lines.append(f"| {label} | {meaning} | {_delta(_esr(cards, right), _esr(cards, left))} "  # 一律"右减左": 增量读作"赚了多少"
                     f"| {_delta(_esr_data(cards, right), _esr_data(cards, left))} "
                     f"| {_delta(_esr_know(cards, right), _esr_know(cards, left))} "
                     f"| {_delta(_avg(cards, right, 'AvgCalls'), _avg(cards, left, 'AvgCalls'))} |")
    lines += [                                                                                 # 单组件段与基线链段分开, 免得把绝对差与相对差混读
        "",
        "### 2.2 单组件消融 (one-at-a-time, 相对 B3)",
        "",
        "| 消融 | 拆掉的零件 | ΔESR_full | ΔESR_data | ΔESR_know | ΔRowF1 "
        "| ΔFieldConsistency | ΔRejectAcc | ΔHR_any | 预登记核对 |",
        "|------|-----------|-----------|-----------|-----------|--------|"
        "------------------|------------|---------|------------|",
    ]
    # 预登记核对: 机器对账 (2026-10-10) —— 原先此栏恒为"待核对 (跑后只核对不改写)",
    # 等于把**核对**本身留给人, 而没有人执行时这一栏永远是"待核对", 读者会误以为假设没验。
    # 本层只读 hypotheses.yaml, 一个字节都不改写 (不改写是防 HARKing 的铁律)。
    from evals.ablation.metrics.composite import score_run  # 配对证据要逐 run 打分
    from evals.ablation.metrics.prereg import render_prereg, verdicts  # 就地导入: 只有出报告才需要
    # runs/items 给了才做**逐题配对**, 标签才能带"显著/不可辨"; 不给则如实标 ·未配对。
    prereg = verdicts(cards, hypotheses, runs=runs, items=items, scorer=score_run)  # 逐条核对结论
    for entry in (hypotheses.get("ablations") or []):  # 行由 hypotheses.yaml 驱动: 少跑一个消融就少一行, 不会被默认值补上
        aid = str(entry.get("id"))  # 统一转字符串: YAML 里 id 可能是数字而 cards 的键是字符串
        card = cards.get(aid) or {}  # 取不到成绩单就当空卡: 缺跑渲染成 N/A/"—" 的可看见空缺
        lines.append(                                                                          # 消融行逐条拼: 预登记列由机器核对填, 假设本身不改写
            f"| {aid} | {str(entry.get('removed_component'))[:28]}… "
            f"| {_delta(card.get('ESR_full'), base.get('ESR_full'))} "
            f"| {_delta(card.get('ESR_data'), base.get('ESR_data'))} "
            f"| {_delta(card.get('ESR_know'), base.get('ESR_know'))} "
            f"| {_delta(card.get('RowF1'), base.get('RowF1'))} "
            f"| {_delta(card.get('FieldConsistency'), base.get('FieldConsistency'))} "
            f"| {_delta(card.get('RejectAcc'), base.get('RejectAcc'))} "
            f"| {_delta(card.get('HR_any'), base.get('HR_any'))} "
            f"| {render_prereg(prereg, [aid])} |")
    lines += [                                                                               # HARKing 红线写进报告正文, 不只留在代码注释里
        "",
        "> 预登记栏在**跑批前**冻结于 ``hypotheses.yaml`` (含 expect_worst / "
        "expect_stable / falsified_if); 本栏由 ``metrics/prereg.py`` **机器核对**填出 "
        "(命中 / 未命中 / 反向 / 不可机析), 核对**只读**该文件、逐字不改写 "
        "(HARKing 是 §11 阻断项 6)。",
        f"> 四级基线核对: {render_prereg(prereg, ['DELTA1', 'DELTA2', 'DELTA2b', 'DELTA3'])}"
        f" (逐指标观测 Δ 与冻结区间的对照由 ``metrics/prereg.py`` 现场算出)。",
        "> **通道可用性 (2026-10-10)**: 本表各列的重复统计前提**因门而异**, 且**逐批不同** ——"
        "**以本表下方那行「⤷ 逐通道标定 (可交换零假设)」的现场结果为准**, 本段不写死数值"
        "(写死会在换一批采集后变成假陈述: 曾把旧批的 `E 不可归因` 印在新批 `E 可用` 的报告里)。"
        "落列为: `ΔRejectAcc` 属决策门, `ΔRowF1`/`ΔFieldConsistency` 属取数门; "
        "而 `ΔESR_*` 是 D∧F∧E 合成口径 —— **若该批 composite 判为退化或不可归因, "
        "`ΔESR_*` 只可作参考, 不得单独引为结论**。",
        "",
        "## 表 3 · sham + add-back 可靠性表",
        "",
        "| 检验 | 系统 | ΔESR_full vs B3 | 判定 |",  # 判据列是文字结论, 数字列仍由 B3 基准算出
        "|------|------|-----------------|------|",
    ]
    sham = cards.get("sham_placeholder") or {}  # 判据是掉分幅度: 与真消融相当说明掉分来自文本长度而非信息量
    lines.append(f"| sham 安慰剂 (等长无关文字) | sham_placeholder "  # 掉分 < 真消融一半才算"掉分来自信息", 否则该消融降级为待复核
                 f"| {_delta(sham.get('ESR_full'), base.get('ESR_full'))} "
                 f"| {'掉分 < A2 真消融的 50% → 掉分来自信息' if sham else '待跑'} |")
    if addback_rows:   # 实测结果优先: 由 stats.addback_check 现算 (真模型批/有 runs 时)
        lines.extend(addback_rows)
    else:
        lines.append("| add-back 恢复检验 (只装回该零件) | (逐消融各一组) "  # 无 runs 时如实标"待跑", 不留空数
                     "| 目标: |B3 - add_back| ≤ 0.05 | 待跑 (P5) |")
    lines += [                                                                         # sham/add-back 结论未稳前不进主表, 只在可靠性表露头
        "",
        "> sham 与 add-back 的预登记预期同样冻结在 ``hypotheses.yaml#reliability``; "
        "sham 与真消融掉分相当 → 该消融结论降级为「待复核」, **不进主表**。",
        "",
    ]
    if t4_text:   # T4 统计表插在表 3 与表 5 之间: 报告表编号连续 (1/2/3/4/5/6)
        lines += [t4_text, ""]
    lines += [
        "## 表 5 · 幻觉三通道表 (机器预筛代理指标)",
        "",
        "| 系统 | " + " | ".join(HR_COLUMNS) + " |",  # 表 4 复用同一 systems 序, 读者不必在两张表间来回找行
        "|---|" + "---|" * len(HR_COLUMNS),
    ]
    for system_id in systems:  # 三通道表与主表同序同集: 读者不必来回找行
        card = cards[system_id]                                                                    # 三通道与主表同集同序, 缺系统也不会半途崩
        lines.append(f"| {system_id} | "  # 三通道 + HR_any + HR_fatal, 取值全部走 _fmt 的 N/A 出口
                     + " | ".join(_fmt(card.get(key)) for key in HR_COLUMNS) + " |")
    lines += [                                                                                     # 通道定义随表给出: 代理指标的口径必须自带
        "",
        "> 通道定义 (§6.4): HR_param = schema 外参数名或值越界; HR_num = 回答中数值 "
        "在给定数据/回包找不到出处且未写明算法; HR_claim = 无支撑的科学主张。"
        "HR_fatal = 致命编造数值 (周期/振幅/变星分类/零点/精度承诺/凭空红化)。",
        "",
        "## 表 6 · 成本-边际表",
        "",
        "| 系统 | http_requests | tokens_in | tokens_out | Δcost vs 上一级 "
        "| 边际成本 Δcost/ΔESR_full |",
        "|------|---------------|-----------|------------|---------------------"
        "-----------------------|",
    ]
    previous = None  # 成本表的 Δ 是"相对 systems 列表里的上一行", 故按列表序而非排序序遍历
    for system_id in systems:                                                                # 按列表序而非排序序遍历: 成本增量才有相对上一级的分母
        card = cards[system_id]                                                                   # 沿用主表同一张成绩单, 呈现层不重算任何指标
        cost = float(card.get("http_requests") or 0)  # 回放无网络等待, 成本口径只数请求条数而非墙钟时间
        delta_cost = "—" if previous is None else f"{cost - previous:+.0f}"  # 首行无上一级, 只能是破折号: 0 会被读成"零成本"
        delta_esr = _delta(card.get("ESR_full"), cards.get(  # 分母用相邻两级的 ΔESR_full; 为 0 时不给无穷大, 记破折号
            systems[systems.index(system_id) - 1] if systems.index(system_id) else {},  # 首行无上一级, 用空卡逼出 None, 免得索引 -1 串到末行
            {}).get("ESR_full")) if systems.index(system_id) else "—"
        marginal = "—"
        if previous is not None and delta_esr not in ("—",) and float(delta_esr) != 0:  # 三条件缺一不可: 首行/无基线/零增益都会让边际成本失去意义
            marginal = f"{(cost - previous) / float(delta_esr):+.1f}"
        lines.append(f"| {system_id} | {_fmt(card.get('http_requests'), 0)} | null | null "  # token 写死 null
                     f"| {delta_cost} | {marginal} |")
        previous = cost  # 逐行推进基准: 下一行的 Δcost 就是本行减本行
    lines += [                                                                              # token 禁用估算的说明紧跟成本表, 防止读者自行折算
        "",
        "> token 字段 API 未返回 usage → 一律记 ``null``, **禁止估算填数** (§6.7);"
        " 单价与计价日期写进报告头后才能折算 元。回放延迟不含网络等待, "
        "live 抽样另附一组作参照 (§6.7)。",
        "",
        f"## 待跑项与覆盖边界 (显式披露, 不冒充 100%; 本批 mode={mode})",
        "",
        "| 项 | 状态 | 缺什么 / 为什么 |",  # 待跑表与主表并列, 防止读者把未跑项读成 100% 覆盖
        "|----|------|--------|",
        ("| T4 统计表 | **已出** | 见文末 T4 (McNemar / Wilson CI / Holm / bootstrap / 效力) |"
         if mode == "live" else
         "| T4 统计表 (McNemar / Wilson CI / Holm / bootstrap / 效力) | 待跑 "
         "| 真实模型跑批 ≥3 次重复 |"),
        ("| T5 错误谱系与归因 | **已出** | 见文末 T5 (脱标识盲评, 20% 分层抽样); "
         "`review_mode: llm-only`, 代理指标 |"
         if t5_available else
         "| T5 错误谱系与归因 | 待跑 | L2 20% 抽样 (脱标识盲评); 未跑时不填空数 |"),
        "| drop-two 交互检验 | 未检验 | P5 可选项, 预算不足则明确写「未检验交互」 |",
        ("| Δ1 (B0→B1) 的文档知识贡献 | 真模型批下**已量出** "
         "| 见 T2.1; scripted 批不可分辨 (B1 的公共文档知识未建模, B0≡B1) |"
         if mode == "live" else
         "| Δ1 (B0→B1) 的文档知识贡献 | **scripted 模式不可分辨** "
         "| 答案渲染只由 4 个组件开关驱动 (data/field_semantics/provenance/post_verify), "
         "B1 的公共文档知识未建模 → B0 与 B1 的 C/R/S 答案相同; 需真模型跑批才能量出 |"),
        ("| sham 与 A2 的区分度 | 真模型批下**已可分辨** "
         "| 见 T1: sham 与 A2 的 ΔESR_full 是否接近, 据此判断掉分来自信息还是长度 |"
         if mode == "live" else
         "| sham 与 A2 的区分度 | **scripted 模式受限** "
         "| sham 换入的等长无关文本不改变断言覆盖 → sham ≡ A2; "
         "sham 的鉴别力 (掉分来自信息还是长度) 需真模型跑批 |"),
        ("| A1/A5 的效应扩散 | 真模型批下**可观测** "
         "| 见 T2.2 的 Δ 与 T5 归因; 不得据 scripted 批断言「仅此一题受影响」 |"
         if mode == "live" else
         "| A1/A5 的效应扩散 | 集中在边界题 "
         "| scripted 下 A1 只在 E5-D08 (半径 0)、A5 只在 D06/D11 可观测; "
         "真模型跑批可能扩散到其它题, 不得据此断言「仅此一题受影响」 |"),
        "",
    ]
    return "\n".join(lines)


def _esr(cards: dict[str, dict], system_id: str) -> Any:
    """取系统的 ESR_full (缺系统 → None; 交给 _delta 渲染成破折号)。"""
    return (cards.get(system_id) or {}).get("ESR_full")  # 缺系统返 None 而非 KeyError, 让 _delta 统一渲染成破折号


def _esr_data(cards: dict[str, dict], system_id: str) -> Any:
    """取系统的 ESR_data (缺系统 → None; 与 ESR_full 同一分域口径)。"""
    return (cards.get(system_id) or {}).get("ESR_data")


def _esr_know(cards: dict[str, dict], system_id: str) -> Any:
    """取系统的 ESR_know (缺系统 → None; 非 D 类题的分域成功率)。"""
    return (cards.get(system_id) or {}).get("ESR_know")


def _avg(cards: dict[str, dict], system_id: str, key: str) -> Any:
    """取系统的平均类指标 (缺系统 → None; key 形如 AvgCalls/AvgTurns)。"""
    return (cards.get(system_id) or {}).get(key)
