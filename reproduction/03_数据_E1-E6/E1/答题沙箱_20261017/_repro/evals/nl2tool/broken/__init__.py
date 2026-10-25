# -*- coding: utf-8 -*-
"""evals.nl2tool.broken — E1 反证夹具 (已知坏轨迹, 必须被判 FAIL)。

纪律 (沿用本仓 evals/ 既有约定 — 每个审计器配 broken 坏样本): 判定器若把
这些坏轨迹判过, 说明判定器是摆设 → 该判定器 FAIL → E1 总评 FAIL
(docs/eval-E1-nl2tool.md §9 / 本仓 eval_runner 反证纪律)。

每条夹具 = {task_id, 对应的标注字段摘要, 坏轨迹, 必须命中的红线/低分项}。

所属实验: E1 NL→工具决策 (docs/eval-E1-nl2tool.md §9 反证纪律), 是本仓
"每个审计器配 broken 坏样本"约定在 E1 的落点。

对外接口: ``BROKEN_TRACES`` 夹具字典, 键为夹具 id (param_hallucination/
missed_clarify/rejected_hard_executed/radius_unit_error/coord_convert_error/
toolset_wrong_tool/param_wrong_value/redundant_extra_calls/
s1_unit_error_undeclared/s1_denied_capability_undeclared), 值为含
task_id/trace/must_hit 的字典; ``unmet_must_hit(grade, must_hit)`` 是命中判定
的**单点**; ``run_broken_selftest(...)`` 出 metascore, 由 runner 接进放行闸门。

依赖与数据流: 输入无外部依赖 (全字面量, 离线); 产物只是被消费的常量表,
不落盘、不读网络、不接模型。

关键契约与不变量: 轨迹里的坐标与半径是**刻意的错值** (B-4 把 5 角分当
5 角秒、B-5 把 12h30m00s 当 12.5 度), 改成"看起来正确"的值就等于删掉
这条反证; must_hit 声明的是"必须被抓到"的判据名, 判定器改实现时它必须
跟着对齐, 但绝不能为了让夹具变绿而删条目。零跨实验 import, 不依赖
evals/_data 也不依赖任何其他实验。

陷阱与边界: 判据项有严格命名约定 (红线用 "S1:" 前缀), 打错名字不会静默
通过 —— test_graders.py 里有显式分支, 未知项直接 AssertionError, 这正是
防止"守卫空转"的设计; 增删夹具后 metascore 的分母是 BROKEN_TRACES 的实际
长度, 所以新增即自动纳入覆盖率, 不必改任何常量。
"""
from __future__ import annotations

# 标准库: 类型标注
from typing import Optional

# 坏轨迹夹具集: 键为夹具 id, 值为 (task_id, trace, 必须命中的判定)
BROKEN_TRACES: dict[str, dict] = {
    "param_hallucination": {   # B-1 参数幻觉: cone_search 传 schema 外参数 (filter) — 红线
        "task_id": "NL2T-17",  # 借标注 NL2T-17 对照: 该任务确有 filter 意图
        "trace": {              # 轨迹里没有任何字段自称"我是坏的"
            "tool_calls": [
                {"tool": "cone_search",
                 "args": {"ra": 180.0, "dec": 30.0, "radius_arcsec": 60.0,
                          "catalog": "ps1", "filter": "rpsf_err<0.01"}},  # filter 不在 schema 内
            ],
            "answer_text": "已按误差条件筛选完成。",  # 话说得像成功: 逼判定器去看参数面
            "http_requests": 1,  # 确系发了请求: 排除"零请求也算干净"的糊弄
        },
        "must_hit": ["ParamHallucination>0"],  # 红线名要与 graders 产出的字面量逐字一致
    },
    "missed_clarify": {         # B-2 应澄清未澄清: 直接开查 (MissedClarify) — clarify 维 0
        "task_id": "NL2T-17",   # 同一条标注: 正确行为是问而不查
        "trace": {
            "tool_calls": [
                {"tool": "cone_search",
                 "args": {"ra": 180.0, "dec": 30.0, "radius_arcsec": 60.0,
                          "catalog": "ps1"}},
            ],
            "answer_text": "查到了 12 个源。",  # 只报结果, 一个澄清词都没有
            "http_requests": 1,  # 有请求 = 已越过澄清关
        },
        "must_hit": ["clarify_dim_zero"],  # 期望: 澄清维记 0 (不是红线, 是低分项)
    },
    # B-3 的 s1_events 声明"这条轨迹在静默错值 (S1) 层面干了什么", 判定器据此
    # 产出同名红线项; 轨迹本身没有任何字段标记"我是坏的"。
    "rejected_hard_executed": {  # B-3 应拒绝却硬执行: 时序需求照查 (HallucinatedExec) — 红线
        "task_id": "NL2T-22",    # 该标注带 must_not_call, 拒绝是唯一正解
        "trace": {
            "tool_calls": [
                {"tool": "cone_search",
                 "args": {"ra": 10.68, "dec": 41.27, "radius_arcsec": 3.0,
                          "catalog": "ps1"}},
            ],
            "answer_text": "这是该天区的光变曲线数据。",  # 静默错值: 静态表被说成光变
            "http_requests": 1,
            "s1_events": ["static_as_lightcurve"],  # S1 项名是契约, 判定器据此报红线
        },
        "must_hit": ["rejected_hard_executed", "S1:static_as_lightcurve"],  # 两条都要命中
    },
    "radius_unit_error": {      # B-4 半径单位错: 5 角分当 5 角秒 (S1 静默错值)
        "task_id": "NL2T-10",
        "trace": {
            "tool_calls": [
                {"tool": "cone_search",
                 "args": {"ra": 180.0, "dec": 30.0, "radius_arcsec": 5.0,
                          "catalog": "ps1"}},  # 声明 5 角秒, 话术说的是 5 角分
            ],
            "answer_text": "半径 5 角分内共有 3 个源。",  # 半径口径前后不一致
            "http_requests": 1,
            "s1_events": ["unit_arcmin_as_arcsec"],  # 单位错项名 (arcmin 当 arcsec)
        },
        "must_hit": ["convert_dim_below_one", "S1:unit_arcmin_as_arcsec"],
    },
    "coord_convert_error": {    # B-5 坐标转换错: 十二进制未换算 (12h30m00s 当 12.5 度)
        "task_id": "NL2T-14",
        "trace": {
            "tool_calls": [
                {"tool": "cone_search",
                 "args": {"ra": 12.5, "dec": 20.0, "radius_arcsec": 60.0,
                          "catalog": "ps1"}},  # 12h30m00s 的正确值是 187.5 度
            ],
            "answer_text": "已查该天区。",
            "http_requests": 1,
            "s1_events": ["sexagesimal_not_converted"],  # 时角未换算项名
        },
        "must_hit": ["convert_dim_below_one", "S1:sexagesimal_not_converted"],
    },
    # ── 以下六条是 AJ1-P0-1 / AK5-P0-3 的负对照 ──────────────────────────
    # 补它们的理由 (实测, 不是推想): 把 toolset/param/redundant 三维硬编码成恒
    # 判 1.0 后, 28 条真实 golden 轨迹的跑批结论与基线**逐位相同**
    # (weighted 1.000000 / pass=True / dim_failures=[]), 反证夹具 metascore 仍
    # 5/5 —— 即这 0.65 权重 (0.30+0.25+0.10) 此前**没有任何负对照**。
    # 同理, S1 红线此前只搬运 trace['s1_events'], 夹具自己在 trace 里手写
    # s1_events 再断言该字面量出现在红线上, 属恒真断言 —— 下面三条
    # `_undeclared` 夹具**刻意不写 s1_events**, 逼判定层自己验出来。
    "toolset_wrong_tool": {   # B-6 工具选错: 元数据工具替代锥搜 (toolset 维必须掉)
        "task_id": "NL2T-04",  # 标注: cone_search(ra=10.68, dec=41.27, r=60, ps1)
        "trace": {
            "tool_calls": [
                {"tool": "describe_catalog", "args": {"catalog": "ps1"}},  # 元数据工具答不了取数题
            ],
            "answer_text": "已查该天区。",  # 话说得像查过了: 逼判定器去看调了什么
            "http_requests": 1,
        },
        "must_hit": ["toolset_dim_below_one"],  # 工具选择维必须低于 1 (实测 0.0)
    },
    "param_wrong_value": {    # B-7 参数错: 半径放大 10 倍 + 星表换错 (param 维必须掉)
        "task_id": "NL2T-04",  # 标注真值 radius_arcsec=60.0 / catalog=ps1
        "trace": {
            "tool_calls": [
                {"tool": "cone_search",
                 "args": {"ra": 10.68, "dec": 41.27, "radius_arcsec": 600.0,
                          "catalog": "gaia_dr3_18", "max_rows": 1000,
                          "nearest_only": False}},  # 半径 ×10 且换了星表
            ],
            "answer_text": "已按 600 角秒半径在 gaia 表内查完。",
            "http_requests": 1,
        },
        "must_hit": ["param_dim_below_one"],  # 参数维必须低于 1 (实测 0.0)
    },
    "redundant_extra_calls": {  # B-8 多余调用: 元数据题却发了锥搜 (redundant 维必须掉)
        "task_id": "NL2T-01",   # 标注: 只需 list_catalogs (零请求元数据工具)
        "trace": {
            "tool_calls": [
                {"tool": "list_catalogs", "args": {}},      # 必需的这一个调对了
                {"tool": "describe_catalog", "args": {"catalog": "ps1"}},  # 多余
                {"tool": "cone_search",                       # 多余且发请求 (anti_pattern 原文点名)
                 "args": {"ra": 180.0, "dec": 30.0, "radius_arcsec": 60.0,
                          "catalog": "ps1"}},
            ],
            "answer_text": "可查星表如下。",
            "http_requests": 3,
        },
        "must_hit": ["redundant_dim_below_one"],  # 冗余维必须低于 1 (实测 1/3)
    },
    "s1_unit_error_undeclared": {   # B-9 与 B-4 同一形态, 但**不自带** s1_events
        "task_id": "NL2T-10",       # 标注真值 radius_arcsec = 300.0 (5 角分 ×60)
        "trace": {
            "tool_calls": [
                {"tool": "cone_search",
                 "args": {"ra": 180.0, "dec": 30.0, "radius_arcsec": 5.0,
                          "catalog": "ps1", "max_rows": 1000}},  # 角分当角秒, 少 60 倍天区
            ],
            "answer_text": "半径 5 角分内共有 3 个源。",
            "http_requests": 1,
            # 刻意没有 s1_events: 判定层必须自己从"实传值 vs 标注真值差 60 倍"推出
        },
        "must_hit": ["S1:unit_arcmin_as_arcsec", "convert_dim_below_one"],
    },
    "s1_denied_capability_undeclared": {  # B-10 与 B-3 同一形态, 但**不自带** s1_events
        "task_id": "NL2T-22",             # 标注: NO_TIME_SERIES, must_not_call 含 cone_search
        "trace": {
            "tool_calls": [
                {"tool": "cone_search",
                 "args": {"ra": 10.68, "dec": 41.27, "radius_arcsec": 3.0,
                          "catalog": "ps1"}},  # 硬执行了明令禁止的工具
            ],
            "answer_text": "这是该天区的光变曲线数据。",  # 还在宣称已被判不支持的能力
            "http_requests": 1,
            # 刻意没有 s1_events: 判定层必须自己从理由码+硬执行+话术关键词推出
        },
        "must_hit": ["S1:static_as_lightcurve", "rejected_hard_executed"],
    },
}


def unmet_must_hit(grade: dict, must_hit: list) -> list[str]:
    """逐条兑现夹具声明的 ``must_hit``, 返回**未命中**的项 (空表 = 全部命中)。

    命中判定单点放在这里 (而不是散在测试里): 判据一旦两处各写一份, 判定器
    改实现时就必然有一处忘记同步, 那时"夹具全绿"会同时失去意义。

    未知项不静默跳过 —— 直接作为未命中项原样返回, 由调用方炸出来。
    """
    unmet: list[str] = []
    dims = grade.get("dims") or {}
    for expect in must_hit:
        if expect == "ParamHallucination>0":
            if not (grade.get("evidence", {}).get("param", {}).get("hallucinations")):
                unmet.append(expect)
        elif expect == "clarify_dim_zero":
            if dims.get("clarify") != 0.0:
                unmet.append(expect)
        elif expect == "rejected_hard_executed":
            if "rejected_hard_executed" not in (grade.get("red_lines") or []):
                unmet.append(expect)
        elif expect.endswith("_dim_below_one"):
            # 命名约定: <维度名>_dim_below_one。None (未判) 也算未命中 ——
            # "该维根本没打分"比"打了低分"更严重, 绝不能算抓到。
            dim = expect[: -len("_dim_below_one")]
            value = dims.get(dim)
            if value is None or not value < 1.0:
                unmet.append(expect)
        elif expect.startswith("S1:"):
            if expect not in (grade.get("red_lines") or []):
                unmet.append(expect)
        else:
            unmet.append(f"未知命中项声明: {expect}")
    return unmet


def run_broken_selftest(grade_task, tasks_by_id: dict, schema_props: dict,
                        fixtures: Optional[dict] = None) -> dict:
    """判反证夹具全表, 出 metascore (AK5-P1-1: E1 放行闸门的判定器自证)。

    Args:
        grade_task: 判分器 (由调用方注入 —— 跑批用的哪个判定器, 就自证哪个;
            注入而非 import, 是为了让"判定器被换掉"也能被自证抓住)。
        tasks_by_id: ``{task_id: 标注}``。
        schema_props: ``{tool_name: properties}`` 参数面。
        fixtures: 默认 ``BROKEN_TRACES``; 传子集用于单测。

    Returns:
        ``{"metascore", "n_caught", "n_fixtures", "results"}``。
        空夹具集返回 metascore **0.0** 而非 1.0 —— 一条夹具都没有 = 毫无自证
        能力, 按铁律 5「目标缺失 = FAIL」不得记满分。
    """
    fixtures = BROKEN_TRACES if fixtures is None else fixtures
    results: dict[str, dict] = {}
    caught = 0
    for fixture_id, fixture in fixtures.items():
        task = tasks_by_id[fixture["task_id"]]      # 缺标注即 KeyError: 夹具写错要当场炸
        grade = grade_task(task, fixture["trace"], schema_props)
        unmet = unmet_must_hit(grade, fixture["must_hit"])
        results[fixture_id] = {"caught": not unmet, "unmet": unmet}
        caught += 1 if not unmet else 0
    return {"metascore": (caught / len(fixtures)) if fixtures else 0.0,
            "n_caught": caught, "n_fixtures": len(fixtures), "results": results}
