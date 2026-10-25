# -*- coding: utf-8 -*-
"""evals/nl2tool/tests/test_e1 — E1 判分链路自测 (金标准自证 + 轨迹装载)。

职责: 用两条互相独立的路径证明 E1 的判分链路没有洞 ——
一条是"金标准自证": 人工标注出的 26 条期望轨迹必须被自己的判定器判满分,
判不满说明标注与判定器至少有一个写错了; 另一条是"轨迹装载":
坏轨迹必须在进判分器之前就被挡掉, 不能带着脏数据算出一个看似合理的分数。

所属实验: E1 NL→工具决策, 方案真值见 docs/eval-E1-nl2tool.md;
覆盖 26 条全量用例、占位符通配与 clarify 路由三类判据。

对外接口: ``TestGoldenSelfVerification`` 四条断言校验金标准满分/全覆盖/
占位符通配/clarify 首轮零调用; ``TestTraceLoading`` 两条断言校验缺目录
返回空字典、示例轨迹可判满分。

依赖与数据流: 输入是 ``evals/nl2tool/tasks.yaml`` 的任务定义 (26 条标注; 注意别与
    ``evals/test-scenarios.yaml`` 混淆 —— 那是 25 条行为场景表, 属另一套),
``golden/`` 的金标准轨迹与 ``traces/`` 的示例轨迹, 全部由 ``runner.py``
的加载器读入; 产物只有 pytest 结论, 本文件不写任何报告文件。

关键契约与不变量: 全离线 — 判分输入是已生成的轨迹 JSON, 不打真实站点、
不接真实模型, 因此这组断言可反复重放; E1 只 import 自己的目录与
``evals/_data/`` 纯数据字典, 零跨实验 import, 跨实验行为一致性由
``evals/equivalence/`` 的断言守护。

陷阱与边界: 金标准"判满分"是这套测试最脆弱的假设 — 改 rubric 权重、
改归一化规则或改金标准轨迹, 都会让它变红, 此时要先判断是谁错了再动手,
不要直接改期望值把红灯抹平; 反过来也不要为了让它变绿去放松判定器。
"""
from __future__ import annotations

# 标准库: JSON (临时轨迹夹具) / 路径
import json
from pathlib import Path

# 第三方: pytest
import pytest

# 本地: 被测件
from evals.nl2tool.gen_golden import GOLDEN_DIR, generate, golden_trace
from evals.nl2tool.graders import (
    DIM_MIN_N,
    DIM_PASS_LINES,
    grade_task,
    score_run,
)
from evals.nl2tool.runner import (  # 金标准轨迹必须判满分: 这是判定器管线自证
    TRACES_DIR,  # 示例轨迹目录: 装载器单测用它, 不参与金标准自证
    aggregate_attempts,  # 重复聚合成裁决: 逐次证据是否全留由它决定
    load_schema_props,  # 加权总分 1.0 才放行, 红灯类必须为空
    load_tasks,  # 标注加载器: 自证与覆盖性检查都从它取题集
    load_trace_attempts,  # 重复归组视图: 覆盖门禁与方差统计都从它取数
    load_traces,  # 金标准轨迹来源要显式标注: 合成轨迹不是模型评测结果
)
from evals.nl2tool.runner import (
    run as runner_run,  # 跑批入口: 覆盖门禁的断言都走它, 不另建调用路径
)

# 参数面 (全仓唯一的工具入参契约): 跑批自证要用真参数面, 空表会让两条参数类
# 红线失去权威, 自证随即判"漏抓" —— 需要这个效果的用例会显式传空表。
_SCHEMA_PROPS = load_schema_props()


class TestGoldenSelfVerification:
    """金标准自证: 标注 → 期望轨迹必须被判定器判满分 (标注/判定器一致性)。

    与 E2 gold/ E5 ScriptedLLM 同模式: 金标准不过线 = 标注或判定器有洞,
    不是"待跑批"能糊弄过去的。
    """

    def test_golden_scores_full_marks(self):  # 逐项报告: 排障要能点名是哪一项失分
        """26 条金标准轨迹: 六维全 1.0, 加权 1.0, 零红线。"""
        tasks = load_tasks()                                                                  # 标注现读磁盘: 题集被改小会让下面的题数断言立刻变红
        traces = load_traces(GOLDEN_DIR)                                                   # 只读金标准目录, 不碰真实跑批轨迹目录, 两条路径互不污染
        # 逐条判分而不是只判总分: 总分 1.0 也可能是"一维 0.6 另一维 1.4"
        # 互相抵消出来的, 只有逐维断言才钉得住这个假绿
        grades = [grade_task(t, traces[t["id"]], load_schema_props()) for t in tasks]
        report = score_run(grades)                                                                 # 汇总出逐维结果: 六维分与红线都在这一份里
        # 任务数是硬期望值而非下界: 少一条用例等于评测覆盖面被悄悄缩小,
        # 而这在只看加权分的报表上完全看不出来
        assert report["n_tasks"] == 28  # 题数钉死 28 (2026-10-07 增 NL2T-27/28): 任务集被截断时"全过"毫无意义
        # 用 approx 比浮点加权分: 权重求和存在二进制舍入, 直接 == 1.0 会假红
        assert report["weighted"] == pytest.approx(1.0)
        # 红线为空是比分数更硬的约束: 任何一条触发红线都代表路由选错工具
        assert report["red_line_tasks"] == []
        for dim, value in report["dims"].items():
            assert value == pytest.approx(1.0), f"{dim} = {value}"  # 逐维度都必须是 1.0: 总分 1.0 可能来自互相抵消

    def test_golden_covers_all_tasks(self):
        """金标准轨迹覆盖全部任务 (缺一即自证不完整)。"""
        tasks = load_tasks()                                                                        # 覆盖性检查的基准就是当前题集本身
        traces = load_traces(GOLDEN_DIR)                                              # 已有轨迹的键即 task_id, 覆盖性按 id 配对而不是按文件名
        # 列名而不是布尔: 失败时直接告诉你是哪几条任务缺轨迹, 省掉一次二分
        missing = [t["id"] for t in tasks if t["id"] not in traces]  # 金标准必须覆盖全部任务: 漏一题等于少验一题
        assert missing == []                                                                      # 漏一题即少验一题, 硬断言比布尔断言更好排障

    def test_placeholder_args_are_wildcarded(self):
        """占位符 (<...>) 期望值按通配处理 — 金标准与真实轨迹都不误判。"""
        # 挑 NL2T-10 作样本: 它的期望参数含 <ra>/<dec> 形式的占位, 是
        # 通配逻辑的最小可复现单元, 换别的用例会连带引入无关变量
        task = next(t for t in load_tasks() if t["id"] == "NL2T-10")  # 占位参数当通配: 任务书没写死的参数不该因具体取值失分
        trace = load_traces(GOLDEN_DIR)["NL2T-10"]
        grade = grade_task(task, trace, load_schema_props())                                      # 判分三件套齐了才调: 与跑批走同一条代码路径
        # param 维满分 ⟺ 占位符没有被当成"必须字面相等"来比对
        assert grade["dims"]["param"] == pytest.approx(1.0)
        assert grade["red_lines"] == []

    def test_clarify_task_first_turn_zero_calls(self):
        """clarify 路由: 首轮零调用判 1.0; 首轮就调 (澄清后工具) 判 0.0。"""
        task = next(t for t in load_tasks() if t["id"] == "NL2T-11")
        # 轨迹由生成器现造而非读文件: 本例要的是"首轮零调用"这一形态,
        # 落盘一份金标准会多出一处会过期的数据
        trace = golden_trace(task)                                                              # 轨迹现造不落盘: 本例只验"首轮零调用"这一形态
        good = grade_task(task, trace, load_schema_props())                                  # 正例必须满分, 否则"零调用即满分"这条判据根本没立住
        assert good["dims"]["clarify"] == pytest.approx(1.0)
        # 反例轨迹: 保留同一条轨迹的其余字段, 只把首轮改成真调了一次工具,
        # 这样两版之差严格等于"首轮是否调用", 差异归因才干净
        bad_trace = dict(trace, tool_calls=[{"tool": "cone_search",  # 反例: 该澄清却动手, clarify 维度必须掉到 0
                                             "args": {"ra": 120.3, "dec": -20.4,
                                                      "radius_arcsec": 5.0}}],
                         http_requests=1)                                                 # HTTP 计数一并置 1: 澄清判据按"有无动手"双通道核对
        bad = grade_task(task, bad_trace, load_schema_props())                                   # 只改首轮调用这一个变量, 两版之差才归因得干净
        # 期望 0.0 而非"小于 1": 该维是二值判据, 部分分不成立
        assert bad["dims"]["clarify"] == 0.0


class TestCoverageGate:
    """覆盖门禁: 缺轨迹/重复不足即阻断, 不得靠缩小分母让加权分照样通过。

    历史缺陷: ``run()`` 只把缺轨迹记进 ``missing_traces``, ``pass`` 仍由
    ``score_run`` 单方决定 —— 于是"26 条只跑了 1 条且这 1 条判满分"会返回
    pass=true, 报告上的 1.0 与"跑全了"长得一模一样 (铁律 5 意义上的 fail-open)。
    """

    def test_missing_trace_blocks_even_when_scored_tasks_pass(self, tmp_path: Path):
        """25/26 条满分、仅缺一条 → 必须阻断 (这正是报告复现的失效场景)。

        特意让**已跑的那些全满分**: 这样 ``pass=False`` 只可能来自覆盖门禁,
        而不是判分把它拉下来 —— 否则"加权分低了所以没放行"会让门禁看起来
        生效, 其实断的是另一条路。
        """
        traces = tmp_path / "traces"                              # 临时轨迹目录: 不碰仓内 golden/
        traces.mkdir()                                            # 现建, pytest 的 tmp_path 保证隔离
        for path in sorted(GOLDEN_DIR.glob("*.json")):            # 逐条拷入, 只跳掉一条
            if path.name != "NL2T-01.json":                       # 唯一缺的一条
                (traces / path.name).write_bytes(path.read_bytes())  # 原字节拷贝: 不重写 JSON
        report = runner_run(traces_dir=traces)                    # 默认 expect_attempts=1
        assert report["weighted"] == pytest.approx(1.0)           # 已跑的 25 条确实满分
        assert report["red_line_tasks"] == []                     # 且零红线: 分数面完全干净
        assert report["pass"] is False                            # 但批次不放行 ← 门禁生效的唯一证据
        assert report["missing_traces"] == ["NL2T-01"]            # 缺的被点名, 不是笼统一句"覆盖不足"
        assert report["blockers"] == ["missing_traces"]           # 阻断项独立成列
        assert report["coverage_complete"] is False               # 覆盖状态有布尔位, 供机器读

    def test_repeat_shortfall_blocks(self, tmp_path: Path):
        """要求每任务 3 次、实到 2 次 → 阻断 (少跑不是"跑过")。"""
        traces = tmp_path / "traces"                              # 临时轨迹目录
        traces.mkdir()                                            # 现建
        base = json.loads((GOLDEN_DIR / "NL2T-01.json").read_text(encoding="utf-8"))  # 取一条金标准当底
        for attempt in (1, 2):                                   # 只造 2 次, 少于要求的 3 次
            (traces / f"NL2T-01.attempt{attempt}.json").write_text(
                json.dumps(dict(base, run_id="r0", attempt=attempt), ensure_ascii=False), encoding="utf-8")
        tasks = tmp_path / "tasks.yaml"                           # 单题标注集: 只看重复次数这一维
        tasks.write_text("tasks:\n  - id: NL2T-01\n    route: answer\n    expect_tools:\n"
                         "      - tool: list_catalogs\n        args: {}\n", encoding="utf-8")
        report = runner_run(tasks_path=tasks, traces_dir=traces, expect_attempts=3)
        assert report["short_attempts"] == [{"task_id": "NL2T-01", "got": 2, "expect": 3}]  # 实到/应有都记
        assert report["blockers"] == ["attempts_below_expected"]  # 阻断码与缺轨迹分开, 复核者知道差在哪
        assert report["pass"] is False                            # 不放行

    def test_repeats_are_grouped_not_overwritten(self, tmp_path: Path):
        """同一 task_id 的多条轨迹必须归组成重复序列, 不得被后写的静默覆盖。"""
        traces = tmp_path / "traces"
        traces.mkdir()                                            # 现建
        base = json.loads((GOLDEN_DIR / "NL2T-01.json").read_text(encoding="utf-8"))  # 底稿
        for attempt in (1, 2, 3):                                 # 三个 attempt 文件名 → 同一 task_id 的三次重复
            (traces / f"NL2T-01.attempt{attempt}.json").write_text(
                json.dumps(dict(base, attempt=attempt), ensure_ascii=False), encoding="utf-8")
        attempts = load_trace_attempts(traces)                    # 归组视图
        assert len(attempts["NL2T-01"]) == 3                      # 三次都在: 覆盖与方差才有分母
        assert len(load_traces(traces)) == 1                      # 单次视图仍只给一条 (旧口径未破)

    def test_unstable_task_is_flagged_by_variance(self, tmp_path: Path):
        """跨重复抖动超过阈值 → 该任务进 unstable_tasks (E1 §8 稳定性口径)。"""
        traces = tmp_path / "traces"                              # 临时轨迹目录
        traces.mkdir()                                            # 现建
        base = json.loads((GOLDEN_DIR / "NL2T-01.json").read_text(encoding="utf-8"))  # 底稿
        wrong = {"tool": "cone_search", "args": {"ra": 1.0, "dec": 2.0, "radius_arcsec": 3.0}}  # 一次离群
        for attempt in (1, 2, 3):                                 # 三次重复
            trace = dict(base, attempt=attempt)                   # 逐次改写, 其余字段保持
            if attempt == 2:                                      # 中间那次调错工具 → 方差 > 0.05
                trace["tool_calls"] = [wrong]                     # 换成错的那次调用
            (traces / f"NL2T-01.attempt{attempt}.json").write_text(
                json.dumps(trace, ensure_ascii=False), encoding="utf-8")
        tasks = tmp_path / "tasks.yaml"                           # 单题标注集
        tasks.write_text("tasks:\n  - id: NL2T-01\n    route: answer\n    expect_tools:\n"
                         "      - tool: list_catalogs\n        args: {}\n", encoding="utf-8")
        report = runner_run(tasks_path=tasks, traces_dir=traces, expect_attempts=3)
        assert report["unstable_tasks"] == ["NL2T-01"]            # 抖动被点名, 不埋在总分里
        grade = report["task_grades"][0]                          # 取该任务的聚合裁决
        assert grade["attempts"] == 3 and grade["variance"] > 0.05   # 次数与方差都记进 JSON 供人工复核
        assert grade["dims"]["toolset"] == pytest.approx(1.0)     # 逐维取中位数: 一次离群不拖走主指标

    def test_golden_batch_still_passes(self):
        """金标准自证批 (每题 1 条合成轨迹, 默认 expect_attempts=1) 必须仍然全绿。"""
        report = runner_run(traces_dir=GOLDEN_DIR)                 # 26 条合成轨迹, 每题一条
        assert report["pass"] is True and report["coverage_complete"] is True   # 门禁不得误伤自证批
        assert report["weighted"] == pytest.approx(1.0)           # 判定器管线自证仍满分


class TestTraceCollectionHonesty:
    """轨迹收集与重复证据的诚实性 (2026-10-06 修的三处)。

    共同毛病: **收集到的东西比实际存在的少, 而报告上看不出来** —— 只扫顶层
    目录会漏掉子目录里的轨迹; 只留首次证据会让复核者看不到真正出错那一次;
    两种来源混在一批里取中位数会把真实成绩凭空抬高。
    """

    def test_subdirectory_traces_are_collected(self, tmp_path: Path):
        """轨迹按来源分子目录时, 顶层 glob 会漏掉绝大多数轨迹 —— 必须递归收。"""
        (tmp_path / "golden").mkdir()                                    # 子目录: 真实布局就是按来源分目录
        (tmp_path / "live-m3").mkdir()
        (tmp_path / "golden" / "NL2T-01.json").write_text(
            json.dumps({"task_id": "NL2T-01", "source": "golden-from-annotation"}), encoding="utf-8")
        for attempt in (1, 2, 3):
            (tmp_path / "live-m3" / f"NL2T-01.attempt{attempt}.json").write_text(
                json.dumps({"task_id": "NL2T-01", "source": "live-run", "attempt": attempt}),
                encoding="utf-8")
        attempts = load_trace_attempts(tmp_path)     # 递归视图
        assert len(attempts["NL2T-01"]) == 4, "子目录里的轨迹必须被收进来 (顶层只有 0 条)"

    def test_mixed_sources_block_the_batch(self, tmp_path: Path):
        """合成轨迹与真实轨迹同批 → 阻断 (中位数不该被合成满分轨迹抬住)。"""
        base = json.loads((GOLDEN_DIR / "NL2T-01.json").read_text(encoding="utf-8"))  # 金标准底稿
        (tmp_path / "golden").mkdir()
        (tmp_path / "live").mkdir()
        (tmp_path / "golden" / "NL2T-01.json").write_text(
            json.dumps(dict(base, source="golden-from-annotation")), encoding="utf-8")
        (tmp_path / "live" / "NL2T-01.attempt1.json").write_text(
            json.dumps(dict(base, source="live-run", attempt=1)), encoding="utf-8")
        tasks = tmp_path / "tasks.yaml"
        tasks.write_text("tasks:\n  - id: NL2T-01\n    route: answer\n    expect_tools:\n"
                         "      - tool: list_catalogs\n        args: {}\n", encoding="utf-8")
        report = runner_run(tasks_path=tasks, traces_dir=tmp_path)
        assert "mixed_trace_sources" in report["blockers"]   # 阻断码独立成列, 不混进"缺轨迹"
        assert report["pass"] is False                        # 混合来源的分数不属于任何可解释口径
        assert sorted(report["trace_sources"]) == ["golden-from-annotation", "live-run"]

    def test_every_repeat_keeps_its_evidence(self, tmp_path: Path):
        """三次重复的证据必须全留下 —— 只留首次的话, 复核者看不到真正错的那次。"""
        traces = tmp_path / "traces"
        traces.mkdir()
        base = json.loads((GOLDEN_DIR / "NL2T-01.json").read_text(encoding="utf-8"))
        wrong = {"tool": "cone_search", "args": {"ra": 1.0, "dec": 2.0, "radius_arcsec": 3.0}}
        for attempt in (1, 2, 3):                              # 中间那次调错工具
            trace = dict(base, attempt=attempt)
            if attempt == 2:
                trace["tool_calls"] = [wrong]
            (traces / f"NL2T-01.attempt{attempt}.json").write_text(
                json.dumps(trace), encoding="utf-8")
        attempts = load_trace_attempts(traces)
        task = {"id": "NL2T-01", "route": "answer",
                "expect_tools": [{"tool": "list_catalogs", "args": {}}]}
        agg = aggregate_attempts(task, attempts["NL2T-01"], _SCHEMA_PROPS)
        assert len(agg["attempt_evidence"]) == 3               # 逐次证据一条不少
        assert agg["evidence_is_first_attempt_only"] is True    # 顶层 evidence 的口径要写明
        # 中位数把那次离群抹成了 1.0, 逐维最差值必须还在 (否则"1.00 里藏着一次 0"看不见)
        assert agg["dims_worst"]["toolset"] == pytest.approx(0.0)


def _grade(dims: dict, task_id: str) -> dict:
    """造一条 ``grade_task`` 形状的聚合结果 (score_run 只读这三个键)。"""
    return {"task_id": task_id, "dims": dims, "red_lines": [], "evidence": {}}


_PERFECT = {"toolset": 1.0, "param": 1.0, "convert": 1.0,
            "redundant": 1.0, "clarify": 1.0, "reject": 1.0}


class TestDimensionThresholdGate:
    """逐维通过线门禁: 执行 E1 §6.7 表格第三列, 而不只是加权总分。

    历史缺陷: §6.7 定义了六条逐维通过线 (转换/澄清/拒绝三条更是 "=1.00"),
    但 ``score_run`` 只按加权总分 ≥0.90 判 ``pass`` —— 逐维门槛**没有任何代码
    执行**。于是"26 条跑完"与"26 条达标"在报告上完全一样, 方案里那张表成了
    装饰。补门禁时最关键的一条: 加权总分达标**不蕴含**逐维达标, 下面第一例
    专门构造这个反直觉场景。
    """

    def test_weighted_pass_does_not_cover_dimension_failure(self):
        """总分 0.9985 达标、convert 0.99 不过线 → 逐维必须点名为失败。

        这是本组最要紧的断言: 99 条全对 + 1 条转换错, 加权分仍高达 0.9985
        (convert 权重只有 0.15, 一条错只吃掉 0.0015), ``pass`` 仍是 True。
        门禁若只读 ``pass`` 就永远看不到这个失败 —— 而 §6.7 把转换 =1.00
        定为硬要求, 正是为了堵住"靠别的高分维把总分抬过线"。
        """
        grades = [_grade(_PERFECT, f"T{i:03d}") for i in range(99)]
        grades.append(_grade(dict(_PERFECT, convert=0.0), "T099"))   # 仅此一条转换错
        report = score_run(grades)
        assert report["pass"] is True                                 # 总分确实达标 ← 前提
        assert report["weighted"] > 0.99                              # 且高到几乎满分
        assert [f["dim"] for f in report["dim_failures"]] == ["convert"]   # 逐维仍点名
        assert report["dim_failures"][0]["n"] == 100                  # 失败维带样本数: 100 题错 1 题
        assert report["thin_dims"] == []                              # n=100 远超下界, 不是"样本不足"

    def test_thin_dimension_is_not_counted_as_failure(self):
        """n < DIM_MIN_N 的维即便 0 分也不阻断, 但必须被点名 (统计诚实)。

        clarify/reject 的分母天然只有 2-4 条; 2 条全对记 1.00 毫无统计意义,
        2 条全错也不该让整批判死 —— 所以不套逐维硬线, 但 "这条线不可信"
        这件事必须出现在报告里, 不能沉默。刻意让**只有** clarify 一维样本不足
        (其余维 n=20), 这样断言能定位到目标维而不是笼统的全维皆薄。
        """
        no_clarify = {k: v for k, v in _PERFECT.items() if k != "clarify"}   # clarify 不适用 (None 不进分母)
        wrong_clarify = dict(_PERFECT, clarify=0.0)                          # 唯独这 2 条打 clarify 分, 且全错
        graded = [_grade(wrong_clarify, "T000"), _grade(wrong_clarify, "T001")]
        graded += [_grade(no_clarify, f"U{i:03d}") for i in range(18)]       # 其余 18 条 clarify 不适用
        report = score_run(graded)
        assert report["dim_failures"] == []                              # clarify 0 分也不阻断
        thin = {item["dim"]: item["n"] for item in report["thin_dims"]}
        assert thin == {"clarify": 2}                                    # 只有 clarify 被点名, n=2
        assert report["dim_n"]["toolset"] == 20                          # 其余维样本充足, 不该混进 thin
        assert report["dims"]["clarify"] == pytest.approx(0.0)            # 分值如实保留, 只是不作判据

    def test_all_perfect_has_no_failures(self):
        """全满分 → dim_failures 必须为空 (防空转门禁: 永远返回非 0 的退化实现也骗不过这组)。"""
        report = score_run([_grade(_PERFECT, f"T{i}") for i in range(20)])
        assert report["dim_failures"] == [] and report["weighted"] == pytest.approx(1.0)

    def test_gate_blocks_only_when_switch_on(self, monkeypatch, tmp_path: Path):
        """同一份报告, 开关开则阻断、开关关则放行 —— 证明阻断由开关决定而非无条件发生。"""
        graded = [_grade(_PERFECT, f"T{i:03d}") for i in range(99)]
        graded.append(_grade(dict(_PERFECT, convert=0.0), "T099"))
        monkeypatch.setattr("evals.nl2tool.runner.score_run", lambda _g: score_run(graded))
        monkeypatch.setattr("evals.nl2tool.runner.load_tasks", lambda _p: [{"id": "T000"}])
        monkeypatch.setattr("evals.nl2tool.runner.load_trace_attempts", lambda _d: {"T000": [{}]})
        monkeypatch.setattr("evals.nl2tool.runner.aggregate_attempts", lambda *_a: graded[0])
        # 参数面必须给**真的**: 空表会让 ParamHallucination / UnknownTool 两条红线
        # 失去权威, 判定器自证随即漏抓 → grader_selftest_failed 阻断。那是正确行为
        # (未判 ≠ 已判), 但本用例要验的是逐维闸门, 不能让自证门禁抢先把它打红。
        monkeypatch.setattr("evals.nl2tool.runner.load_schema_props", lambda: _SCHEMA_PROPS)
        off = runner_run(traces_dir=tmp_path)                          # 缺省: 不开闸门
        assert off["threshold_required"] is False
        assert "below_dimension_threshold" not in off["blockers"]
        assert off["pass"] is True                                    # 缺省不误伤离线自检批
        on = runner_run(traces_dir=tmp_path, require_threshold=True)  # 开启: 逐维不过线即阻断
        assert on["threshold_required"] is True
        assert "below_dimension_threshold" in on["blockers"]
        assert on["pass"] is False
        assert "convert" in on["threshold_note"]                      # 报告正文点名是哪一维

    def test_gate_passes_golden_batch(self):
        """金标准自证批开逐维闸门仍放行 (反向自证: 门禁不得对合格批误报)。"""
        report = runner_run(traces_dir=GOLDEN_DIR, require_threshold=True)
        assert report["dim_failures"] == []                           # 期望轨迹本来就该逐维满分
        assert report["pass"] is True

    def test_pass_lines_cover_every_weighted_dimension(self):
        """逐维通过线必须覆盖权重表全部六维 (漏一维 = 该维静默无判据)。"""
        assert set(DIM_PASS_LINES) == set(_PERFECT)                    # 六维一个不少
        assert all(line > 0.0 for line in DIM_PASS_LINES.values())     # 阈值不得配成 0 (=永不过线)
        assert DIM_MIN_N >= 2                                          # n=1 的维判达标无意义



class TestTraceLoading:
    """轨迹装载: 缺目录不炸 (返回空), 坏 JSON 不进门。"""

    def test_missing_dir_returns_empty(self, tmp_path: Path):
        """不存在的 traces 目录 → 空字典 (由上层记 missing_traces)。"""
        # 装载器返回空而不是抛: 缺轨迹与答错轨迹必须能分开统计,
        # 直接抛异常会让跑批无法区分"模型没输出"和"环境坏了"
        assert load_traces(tmp_path / "nope") == {}  # 缺目录返空字典: 空跑批返回"全过"是最危险的假象

    def test_example_golden_trace_is_valid(self):
        """示例金标准轨迹 (NL2T-04) 可被装载且打满分。"""
        traces = load_traces(TRACES_DIR)                                                           # 示例轨迹目录: 固定抽一条多轮样本验装载器
        # 固定抽 NL2T-04: 它是 traces/ 目录下唯一同时含多轮工具调用的样本,
        # 单轮样本无法暴露"跨轮序号错位"这类装载错误
        assert "NL2T-04" in traces
        task = next(t for t in load_tasks() if t["id"] == "NL2T-04")
        grade = grade_task(task, traces["NL2T-04"], load_schema_props())
        assert grade["red_lines"] == []
