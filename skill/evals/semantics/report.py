# -*- coding: utf-8 -*-
"""evals.semantics.report — E3 报告渲染 (Tier F 评分 + 一致性 + 预筛命中)。

能力边界: 把 runner 产出的 JSON 汇总渲染成 Markdown 人工复核面 (九个数
+ 错误谱系表占位 + 逐轴分层)。边界: 只渲染不改数据; L2 盲评未跑时,
相关栏目显式标"待 L2 判定" (不填空数 — 空数是失真)。

白盒锚点: docs/eval-E3-semantics.md §14 (报告必须披露的 9 个数);
evals/semantics/rubric.yaml §8 (report_required_numbers)。

职责: 把 E3 的 runner 汇总字典原样渲染成给人看的复核报告, 承担"披露九个数"
  这一硬要求, 并在 L2 判定缺位时显式留白而不是编数。
所属实验: E3 科学语义区分与幻觉抑制 (37 题 7 轴); 方案真值
  docs/eval-E3-semantics.md §14, 栏目清单以 evals/semantics/rubric.yaml §8
  (report_required_numbers) 为准, 本文件只负责排版不负责定义指标。
对外接口: render_report(summary) -> str, 把 runner 汇总渲染为 Markdown 文本;
  无其他导出, 纯函数、不读盘不写盘。
依赖与数据流: 输入 = evals/semantics/runner.py 的 run() 汇总字典 (题数、
  分系统预筛聚合、可选的一致性块); 产物 = Markdown 字符串, 由 runner 的
  --md 分支打印到 stdout, 不落盘、不被其他模块 import。
关键契约与不变量: 只渲染不改数据, 因此同一份 summary 渲染多少次都必须逐字
  相同 (报告是评审留痕, 不可复现的排版等于没留痕); 零跨实验 import — 本文件
  不 import evals/ 下任何其他实验, 也不 import src/; E3 与其它实验的等价性
  由 evals/equivalence/ 的断言守护。离线纪律同样适用: 报告里出现的每个数都
  来自回放, 不打真实站点。表头固定顺序, 两轮报告要能直接 diff。
陷阱与边界: 九个数里 SFA 有 S-A / S-B 两行而其余七行各一行 — 这是 §14 的
  原文口径, 不是笔误; 少渲染一行就会被判为"未披露必备数"。L2 判定未跑时
  写 0.00 等于伪造结果 (铁律 5 禁 fail-open 的同源要求), 所以只能标"待 L2 判定"。
"""
from __future__ import annotations

# 标准库: 类型标注 (本文件无运行时依赖, 刻意不 import 任何评测件 — 保持纯渲染)


def _broken_count(summary: dict) -> str:
    """反证夹具条数 → 报告第三节的括号文字。

    为什么现取而不写死: 夹具数会随题集增补 (2026-10-05 补 B-4 后由 3 条变 4 条),
    写死的 "3 份" 会让报告与实际夹具数脱节 —— 那正是 ``test_report_claims``
    守的"报告声称 vs 题集实数"那一族缺陷, 自己犯一遍最没说服力。
    缺 selftest 块时写 ``N/A`` 而不是猜一个数: 报告宁可缺数也不编数 (铁律 5)。
    """
    results = ((summary.get("selftest") or {}).get("results") or {})
    return str(len(results)) if results else "N/A"


def _coverage_line(summary: dict) -> str:
    """报告抬头的覆盖度行: 声明"实际预筛了几条回答", 与题集规模区分开。

    为什么单独一行: 题数 (n_items) 是**题集规模**, 不是**评测覆盖面**。
    两者在缺 --answers 时同看很容易误读成"全部题都评测过了", 而实际
    n_answered=0 —— 离线纪律 (铁律 7) 下 E3 尚未采集任何模型回答。
    这行是 E3 最重要的诚实信号, 不得折叠进题数那一行。
    """
    n_items = summary.get("n_items", 0)
    n_answered = summary.get("n_answered", 0)
    gate = "覆盖度闸门: 已开启 (--require-coverage)" if summary.get("coverage_required") \
        else "覆盖度闸门: 未开启 (离线自检模式)"
    if n_answered and n_answered >= n_items:
        return f"- 实际预筛覆盖: {n_answered}/{n_items} 条回答 · {gate}"
    return (f"- 实际预筛覆盖: **{n_answered}/{n_items}** 条回答"
            f" · {gate} —— **尚未采集任何模型回答**; 本报告只证明题集与 L0 预筛器就位, "
            "不含任何关于被测系统能力的结论")


def render_report(summary: dict) -> str:  # 渲染唯一入口: 判定在 runner/prescreen, 这里只排版不改结论
    """渲染 E3 报告 (Markdown)。

    NA 与 0 严格区分: 该指标不适用 ≠ 得了零分。

    Args:
        summary: runner 汇总 ``{"n_items", "n_fixture", "n_live",
            "prescreen": {系统: 聚合}, "agreement": {...} | None,
            "metascore": float, "generated_at": str}``。

    Returns:
        Markdown 文本 (结论页九个数; 缺数据显式标注, 不编)。
    """
    # 先铺表头骨架: 九个数的表头与九个数共用同一段说明文字, 后面有系统数据时
    # 整段会被下面那个分支整体替换, 这样"有/无系统"两条路径的抬头永不漂移
    lines = [  # 小数位固定: 跑批之间逐行比数字才有效
        "# E3 科学语义区分与幻觉抑制 — 预筛报告 (L0)",
        "",
        f"- 生成时间: {summary.get('generated_at', 'N/A')}",
        f"- 题数: {summary.get('n_items', 0)} "
        f"(fixture {summary.get('n_fixture', 0)} / live {summary.get('n_live', 0)}; "
        "live 不计入主指标)",
        f"- 反证夹具 metascore: {summary.get('metascore', 0.0):.2f} "
        "(< 1.00 → 预筛规则失效, E3 FAIL)",
        _coverage_line(summary),
        "",
        "## 1. 披露数 (结论页必备; L2 判定未跑项显式标注)",
        "",
        "| # | 数 | 值 |",   # 占位表头: 无受试系统时也不留空表 (空表会被读成"跑了但都是零")
        "|---|-----|-----|",
    ]
    # L0 阶段常常一个受试系统都没有 (L2 判定前只有反证夹具), 此时表格退化为一行
    # 占位, 比渲染一张全空表更诚实 — 空表会被读成"跑了但都是零"
    prescreen = summary.get("prescreen") or {}  # 预筛块可能整块缺失(只到 L0 预筛), 兜空字典让遍历不必判空
    # 按系统名排序而非按插入序: 报告是跨次对照物, 列序必须稳定可比
    systems = sorted(prescreen)  # 按系统名排序: 报告是跨次对照物, 列序必须稳定可比
    if systems:  # 有系统才铺九个数表: 列数随系统数变, 空表会被读成"跑了但都是零"
        header = "| # | 指标 | " + " | ".join(systems) + " |"
        # 有系统时重建整段抬头: 列数随系统数变, 靠不了上面那份三列骨架拼出来
        lines = [  # 有数据时整段替换抬头: 骨架那份是三列, 拼不出多列表
            "# E3 科学语义区分与幻觉抑制 — 预筛报告 (L0)",   # 有系统时重复抬头, 便于两段各自独立引用
            "",   # 空行分隔抬头与抬头下的口径说明
            f"- 生成时间: {summary.get('generated_at', 'N/A')}",
            f"- 题数: {summary.get('n_items', 0)} "
            f"(fixture {summary.get('n_fixture', 0)} / live {summary.get('n_live', 0)}; "
            "live 不计入主指标)",
            f"- 反证夹具 metascore: {summary.get('metascore', 0.0):.2f} "
            "(< 1.00 → 预筛规则失效, E3 FAIL)",
            _coverage_line(summary),
            "",
            "## 1. 披露数 (结论页必备; L2 判定未跑项显式标注)",
            "",
            header,
            "|---|-----|" + "---|" * len(systems),  # 错误谱系留空待 L2 判定: 自动判定不能替它定稿
        ]
        # 行的顺序就是 §14 的披露顺序, 不可重排: 评审按行号对着方案逐条核
        rows = [  # 九个数固定行序: 少一行就能被读成"这项没跑"
            ("1", "SFA (S-A)", "sfa"),
            ("2", "SFA (S-B)", "sfa"),
            ("3", "McNemar p / 差值 CI", "mcnemar"),  # McNemar 带 CI: 只给 p 值看不出差异有多大
            ("4", "UNGR (**L0 预筛版 = 上界**, 含致命项)", "ungr"),
            ("5", "UCR", "ucr"),
            ("6", "SLR", "slr"),
            ("7", "RQC", "rqc"),
        ]
        for number, label, key in rows:  # 按方案固定行序遍历: 评审按行号逐条对着方案核
            cells = []  # 逐系统攒一行的单元格, 最后一次性拼成 Markdown 行
            for system in systems:  # 列序与表头共用同一个系统列表, 靠它保证不错位
                # 缺键即"待 L2 判定"而不是 0: 键不存在代表这条数还没算 (L2 未跑),
                # 渲染成 0.00 会把"没测"谎报成"测了是零"
                value = prescreen[system].get(key, "待 L2 判定")  # 缺项显式写占位: 留空会被读成跑了但得零分
                cells.append(str(value))  # 统一转字符串: 数值与占位串要能拼进同一列
            lines.append(f"| {number} | {label} | " + " | ".join(cells) + " |")  # 行号 + 指标名 + 各系统值, 拼成九个数中的一行
    else:
        lines.append("| — | (无受试系统数据; runner 只到 L0 预筛) | — |")  # 无系统也留一行说明: 空表会被读成"跑了但都是零"
    lines += [  # 第二节抬头固定: 后面逐系统铺开六项命中计数
        "",
        "## 2. 预筛命中汇总 (每系统)",
        "",
        "> **L0 预筛只标记、不裁定** (rubric §3): 上列「疑似」计数是**上界**, 不是结论。",
        "> 它靠正则抽数分不出「可推导」与「编造」—— 写了公式的派生量照样被计入分子。",
        "> 实测 36 题真模型批: L0 判 248 个无来源数值 / 5 个致命编造 / 6 个静态误称,",
        "> 经 rubric 逐条复核后认定 4 / 0 / 0 (UNGR 0.4313 → 0.0070, 差 62 倍)。",
        "> **引用 UNGR / 致命项 / 静态误称必须说明是哪一层给的**, 直接引 L0 会高估两个数量级。",
        "",
    ]
    # 逐系统铺开六项命中计数: 这六项是"为什么这个数是这个数"的证据链,
    # 只给最终分不给分项的评审无法复核
    for system in systems:  # 有系统才逐个铺开; 无系统时这一节只剩抬头
        agg = prescreen[system]  # 聚合计数字典原样取用, 报告层不做二次聚合或换算
        lines += [
            f"### {system}",
            "",
            f"- 触发 static_as_lc 的题数: {agg.get('static_as_lc_triggered', 0)}",
            f"- 哨兵误用命中总数: {agg.get('sentinel_misuse_count', 0)}",
            f"- 疑似无来源数值总数: {agg.get('unsourced_number_count', 0)}",
            f"- 致命编造候选总数: {agg.get('fatal_candidate_count', 0)}",
            f"- 疑似无支撑主张总数: {agg.get('unsupported_claim_count', 0)}",
            f"- 限定语缺失总数: {agg.get('qualifier_missing_count', 0)}",
            "",
        ]
    lines += [  # 第三节与错误谱系表同样固定抬头, 两段一起收尾
        "## 3. 判定器自证 (metascore)",
        "",
        # 2026-10-03 全面去人工化: 本节原为「一致性 (双评后由 agreement.py 计算)」,
        # 渲染 κ / α / AC1 / ICC。但 E3 已改 LLM-only —— 没有人类评阅就没有"两人是否
        # 一致"这回事, 报这些数是伪造证据 (docs/eval-E3-semantics.md §10 / §12 阻断项 10)。
        # 判定器可信与否改由反证夹具 metascore 独自承担: 它不依赖评阅人是谁。
        f"- metascore: {summary.get('metascore', 'N/A')}  "
        # 夹具条数从 summary 现取而不写死: 写死过一次 (3 条), 加夹具 B-4 后报告仍写
        # "3 份" —— 报告与事实脱节, 而这正是 test_report_claims 那道门禁要挡的形态
        f"({_broken_count(summary)} 份反证夹具, 必须 = 1.00)",
        f"- 评阅模式: {summary.get('review_mode', 'llm-only (no human reviewer, no kappa)')}",
        "",
        "## 4. 错误谱系表 (L2 判定后补; 每条 = 脱敏原文 + 判定理由)",
        "",
        "- (待 L2 判定)",
        "",
    ]
    return "\n".join(lines)
