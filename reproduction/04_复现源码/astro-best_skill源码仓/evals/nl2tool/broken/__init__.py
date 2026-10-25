# -*- coding: utf-8 -*-
"""evals.nl2tool.broken — E1 反证夹具 (已知坏轨迹, 必须被判 FAIL)。

纪律 (沿用本仓 evals/ 既有约定 — 每个审计器配 broken 坏样本): 判定器若把
这些坏轨迹判过, 说明判定器是摆设 → 该判定器 FAIL → E1 总评 FAIL
(docs/eval-E1-nl2tool.md §9 / 本仓 eval_runner 反证纪律)。

每条夹具 = 自带的最小标注 + 坏轨迹 + 必须命中的判据。

所属实验: E1 NL→工具决策 (docs/eval-E1-nl2tool.md §9 反证纪律), 是本仓
"每个审计器配 broken 坏样本"约定在 E1 的落点。

对外接口: ``BROKEN_TRACES`` 夹具字典 (键为夹具 id, 值为含 task_id/task/
trace/must_hit 的字典); ``run_broken_selftest(schema_props)`` 逐条判分,
``metascore(schema_props)`` 给元分 (必须 1.00)。

> **2026-10-06 接线修正 (一)**: ``run_broken_selftest`` / ``metascore`` 此前
> **只存在于 test_graders.py 里** (那份实现把命中判据内联在测试函数中),
> runner 从不调用, 于是「metascore < 1.0 → E1 FAIL」这条自证门禁在跑批路径
> 上**没有任何代码执行** —— 判定器失效只会让单测变红, 跑批照样 exit 0。
> 现在把判据抽到本模块成为单一实现, test 与 runner 消费同一份。
>
> **2026-10-06 接线修正 (二): 夹具改为自包含。** 上一版让夹具按 ``task_id``
> 去**跑批时装载的 tasks.yaml** 里借标注, 有两个后果: (a) 标注集被裁剪时
> (单测里只造一两条 task 是常态) ``task_lookup`` 抛 KeyError, 整轮 ``run()``
> 直接崩, 而不是给出"未判"; (b) 把"判定器失效"与"这次的标注集里没这条题"
> 两种完全不同的故障混成一个 KeyError。反证夹具验的是**判定器**, 不是某一次
> 跑批的标注集, 因此每条夹具自带最小标注 (``task`` 字段), 与 E2/E4/E5/E6
> 的自包含口径对齐。``task_id`` 保留作溯源用 (说明这条坏形态对应哪条真实题),
> 不再参与判分。

依赖与数据流: 输入无外部依赖 (全字面量, 离线); 产物只是被消费的常量表,
不落盘、不读网络、不接模型。

关键契约与不变量: 轨迹里的坐标与半径是**刻意的错值** (B-4 把 5 角分当
5 角秒、B-5 把 12h30m00s 当 12.5 度), 改成"看起来正确"的值就等于删掉
这条反证; must_hit 声明的是"必须被抓到"的判据名, 判定器改实现时它必须
跟着对齐, 但绝不能为了让夹具变绿而删条目。零跨实验 import, 不依赖
evals/_data 也不依赖任何其他实验。

陷阱与边界: 判据项有严格命名约定 (红线用 "S1:" 前缀), 打错名字不会静默
通过 —— ``_check_must_hit`` 遇到未知项直接 ValueError, 这正是防止"守卫
空转"的设计; 增删夹具后 metascore 的分母是 BROKEN_TRACES 的实际长度,
所以新增即自动纳入覆盖率, 不必改任何常量。
"""
from __future__ import annotations

# 标准库: 脚本直跑时挂 skill 根 (供 evals.* 命名空间包导入)
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))  # 脚本直跑时挂 skill 根: 让 evals.* 命名空间包能被解析

# 本地: 判定入口 (坏轨迹必须经**被测判定器本身**判分 — 自证不能用第二套实现)
from evals.nl2tool.graders import grade_task  # noqa: E402

# 坏轨迹夹具集: 键为夹具 id; 值为 {task_id, task, trace, must_hit}。
# task 是**自带的最小标注** (只含触发该坏形态所必需的字段), 不读 tasks.yaml。
BROKEN_TRACES: dict[str, dict] = {
    "param_hallucination": {   # B-1 参数幻觉: cone_search 传 schema 外参数 (filter) — 红线
        "task_id": "NL2T-17",  # 溯源: 该真实任务确有 filter 意图
        "task": {"id": "NL2T-17", "route": "answer",   # 最小标注: 一次合法 cone_search
                 "expect_tools": [{"tool": "cone_search", "args": {
                     "ra": 180.0, "dec": 30.0, "radius_arcsec": 60.0, "catalog": "ps1"}}]},
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
        "task_id": "NL2T-17",   # 溯源: 该真实任务的正确行为是问而不查
        "task": {"id": "NL2T-17", "route": "clarify",   # 最小标注: 路由澄清且必须澄清
                 "clarify": {"required": True},
                 "expect_tools": [{"tool": "cone_search", "args": {
                     "ra": 180.0, "dec": 30.0, "radius_arcsec": 60.0, "catalog": "ps1"}}]},
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
        "task_id": "NL2T-22",    # 溯源: 该真实任务带 must_not_call, 拒绝是唯一正解
        "task": {"id": "NL2T-22", "route": "reject",   # 最小标注: 拒绝路由 + 禁调清单
                 "reject": {"must_not_call": ["cone_search"],
                            "reason_code": "unsupported_time_series"},
                 "expect_tools": []},
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
        "task_id": "NL2T-10",   # 溯源: 该真实任务考半径换算
        "task": {"id": "NL2T-10", "route": "answer",   # 最小标注: 期望 300 角秒 (即 5 角分)
                 "expect_tools": [{"tool": "cone_search", "args": {
                     "ra": 180.0, "dec": 30.0, "radius_arcsec": 300.0, "catalog": "ps1"}}]},
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
        "task_id": "NL2T-14",   # 溯源: 该真实任务考时角换算
        "task": {"id": "NL2T-14", "route": "answer",   # 最小标注: 12h30m00s 的正确值是 187.5 度
                 "expect_tools": [{"tool": "cone_search", "args": {
                     "ra": 187.5, "dec": 20.0, "radius_arcsec": 60.0, "catalog": "ps1"}}]},
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
    # B-6 (2026-10-06 新增): 凭空造工具名。E1 §1 把"伪造工具名"列在最严重一档,
    # 但原判定器只在"工具名存在于 schema"时才比参数, 造出来的名字既不记幻觉也不
    # 进红线 —— 这条夹具就是为了让该漏洞**不可能悄悄回来**: 判定器若再次放行,
    # metascore 立刻掉到 5/6, 跑批阻断。工具名与参数都挑得像模像样 (ztf_search 是
    # 真实巡天名), 逼判定器去查参数面而不是看"名字顺不顺眼"。
    "fabricated_tool": {
        "task_id": "NL2T-01",   # 溯源: 一条 answer 路由的普通查询, 正解只用 schema 内工具
        "task": {"id": "NL2T-01", "route": "answer",   # 最小标注: 期望 list_catalogs
                 "expect_tools": [{"tool": "list_catalogs", "args": {}}]},
        "trace": {
            "tool_calls": [
                {"tool": "ztf_search",  # schema 里没有这个工具
                 "args": {"ra": 180.0, "dec": 30.0, "radius_arcsec": 60.0}},
            ],
            "answer_text": "已在 ZTF 中检索到 8 个源。",  # 话说得像成功: 不靠话术识破
            "http_requests": 1,
        },
        "must_hit": ["UnknownTool>0"],
    },
}


def _check_must_hit(expect: str, grade: dict) -> bool:
    """兑现夹具声明的一条 must_hit (判据的**唯一**实现, test 与 runner 共用)。

    未知命中项抛 ValueError 而不是返回 False: 静默跳过会让夹具退化成空断言,
    守卫随之空转 —— 那正是"夹具越加越多、被抓住的一条没变"的成因。
    """
    if expect == "ParamHallucination>0":
        return bool(grade["evidence"]["param"]["hallucinations"])
    if expect == "UnknownTool>0":
        # 伪造工具名: 看未知工具名单而非只看红线字符串 —— 名单是证据, 红线是结论,
        # 只比对结论会在"红线名改了但判据没接"时漏判
        return bool(grade["evidence"]["param"].get("unknown_tools"))
    if expect == "clarify_dim_zero":
        return grade["dims"]["clarify"] == 0.0
    if expect == "rejected_hard_executed":
        return "rejected_hard_executed" in grade["red_lines"]
    if expect == "convert_dim_below_one":
        # 先断非 None 再比大小: 该维缺判时 None < 1.0 会抛 TypeError,
        # 报错信息会指向"类型不对"而不是"判定器漏判", 误导排查方向
        return grade["dims"]["convert"] is not None and grade["dims"]["convert"] < 1.0
    if expect.startswith("S1:"):
        return expect in grade["red_lines"]
    raise ValueError(f"未知命中项声明: {expect}")  # 未知项必须炸: 不炸等于夹具变空断言


def run_broken_selftest(schema_props: dict) -> list[dict]:
    """逐夹具对账: 坏轨迹必须被判定器抓住; 返回逐条结果 (漏抓可点名)。

    Args:
        schema_props: ``{工具名: 入参属性}`` 参数面 (ParamHallucination 与
            UnknownTool 的权威, 由调用方注入; 空表 = 这两条红线判不了, 夹具
            随之漏抓 → metascore 掉 → 阻断, 不会静默变绿)。

    Returns:
        ``[{fixture_id, task_id, caught, missed_must_hit, red_lines, dims}]``。
    """
    results: list[dict] = []   # 逐夹具一条: 漏抓时要能点名是哪一条, 不能只给一个总分
    for fixture_id in sorted(BROKEN_TRACES):   # 排序遍历: 结果顺序稳定, 报告可逐条对账
        fixture = BROKEN_TRACES[fixture_id]
        # 用夹具自带的标注而非外部标注集: 自证验的是判定器, 不该随某次跑批的
        # tasks.yaml 变化而变化, 也不该因标注集被裁剪而把整轮跑批带崩
        grade = grade_task(fixture["task"], fixture["trace"], schema_props or {})
        missed = [e for e in fixture["must_hit"] if not _check_must_hit(e, grade)]
        results.append({
            "fixture_id": fixture_id,
            "task_id": fixture["task_id"],
            "caught": not missed,          # 抓住 = 声明的命中项全部兑现
            "missed_must_hit": missed,     # 漏抓项原样列出: 报告要能看出漏了哪一条判据
            "red_lines": grade["red_lines"],
            "dims": grade["dims"],
        })
    return results


def metascore(schema_props: dict) -> float:
    """反证夹具元分 = 被抓住的夹具数 / 全部夹具数 (必须 1.00, 否则判定器失效)。

    空夹具表给 0.0 而不是 1.0: 没验过不等于验过了 (铁律 5 禁 fail-open)。
    """
    results = run_broken_selftest(schema_props)   # 另跑一遍而非复用缓存: 缓存会掩盖判定器失效
    if not results:
        return 0.0
    return sum(1 for r in results if r["caught"]) / len(results)
