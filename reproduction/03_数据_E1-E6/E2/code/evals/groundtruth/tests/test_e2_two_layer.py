# -*- coding: utf-8 -*-
"""E2 口径契约的**承重测试** (原「双层接线」件的收口版, 2026-10-07)。

本文件原守两条契约, 回放臂删除后只剩一条:

- ~~**离线安全**: 库函数裸调不得触网~~ —— **已随回放臂作废**。那条规则的全部
  理由是「单测不该挂在网络上」, 而它的实现手段是「库函数缺省 mode=replay」。回放
  删除后库里没有任何 offline 分支, 契约本身失去被测对象。
  它的**意图仍然成立** (单测不该依赖站点今天心情), 换了实现方式: 打桩的会话
  (``live_policy.CountingSession``) 让单测零外网依赖, 而不是切到另一条臂。
- **BC-05 诚实性**: ``declared``/``observed`` 两侧必须来自**不同观测面**。同源时
  差值恒 0, M7 恒真, 一条恒真的判据比没有判据更坏。**这条仍然活着**, 且因为
  跑批只剩实跑一条臂而更关键 —— 若把 declared 直接抄 observed, 实跑下 M7 会恒真。

其余各组 (M1 口径分派 / M6 可对账性 / blockers 承重 / 报告口径披露) 都随口径
调整而保留。逐条判据的承接映射见 ``docs/REPLAY-RETIREMENT-CRITERIA.md``。

**为什么单独立一个文件**: 这些都是**跨模块契约** (run_e2 的口径方向、
live_policy 的轨迹分类、m1/m4/m6/m7 四处的一致性), 而 ``test_e2.py`` 装的是
E2 的功能用例。把契约断言混进功能用例的后果是: 改功能时会顺手改掉契约断言,
而那正是本仓反复吃过的亏 (零覆盖比覆盖不足更难发现, 因为没人会去想
「这条分支有没有夹具」)。

所属实验: E2 金标准一致性 (实跑口径见 docs/eval-E2-groundtruth.md 与
``run_e2`` 模块 docstring)。
"""
from __future__ import annotations

# 标准库: 签名自省 / 路径拼接 / 源码缩进还原 / AST 结构判据
import ast
import inspect
import pathlib
import textwrap

import pytest  # 参数化与.raises

from evals.groundtruth import run_e2  # 被测编排件 (口径方向与轨迹分类都要看它)
from evals.groundtruth.live_policy import accounted_calls  # 轨迹分类: BC-05 声明侧的唯一实现
from evals.groundtruth.metrics import compare_case  # 七指标对账入口 (blockers 承重那条要用)

GT_DIR = pathlib.Path(__file__).resolve().parents[1]  # 本实验根 (场景目录的父)

class TestBC05CountHonesty:
    """M7 的两侧必须来自不同观测面 (BC-05)。"""

    def test_contract_shaped_calls_are_all_accounted(self):
        """BEST 两阶段的合法请求全部有据可依 → 差值 0。"""
        calls = [
            ("POST", "https://nadc.china-vo.org/data/best/ps1/q"),                      # 阶段一: 表单提交换 sqlid
            ("GET", "https://nadc.china-vo.org/data/best/sqlid/abc123/getcount"),        # 阶段二: 总数计数
            ("GET", "https://nadc.china-vo.org/data/best/sqlid/abc123?rows=100&page=1"),  # 阶段二: 翻页取数
            ("GET", "https://nadc.china-vo.org/data/best/sqlid/abc123?rows=100&page=2"),  # 阶段二: 翻页取数
        ]
        declared, unaccounted = accounted_calls(calls)
        assert declared == len(calls), f"合法请求被误判成隐藏请求: {unaccounted}"
        assert not unaccounted  # 两阶段的每一步都该认得出来

    def test_off_contract_call_is_unaccounted(self):
        """契约里没有的一发必须被抓出来 —— 这正是 M7 现在有的检验力。"""
        calls = [
            ("POST", "https://nadc.china-vo.org/data/best/ps1/q"),
            ("GET", "https://telemetry.example.invalid/collect"),  # 契约外: 遥测上报
        ]
        declared, unaccounted = accounted_calls(calls)
        assert declared == 1  # 只有 phase-1 那一发有据可依
        assert len(unaccounted) == 1 and "telemetry" in unaccounted[0]  # 且要点名是哪一次

    def test_hidden_request_makes_m7_fail(self):
        """两侧不等 → M7 转红 (旧实现同源时这条恒绿, 是 BC-05 的实证)。"""
        from evals.groundtruth.metrics.m7_determinism import score_m7  # 行内导入: 只为这条断言服务, 不进模块级导入

        honest = score_m7({}, {"data_hashes": ["a", "a"],           # 两次跑批同指纹: 确定性这分项先过
                               "declared_http_requests": 3, "observed_http_requests": 3})  # 两侧相等即诚实
        assert honest["pass"] and honest["http_requests_honest"] is True

        sneaky = score_m7({}, {"data_hashes": ["a", "a"],                                  # 确定性这分项同上
                               "declared_http_requests": 1, "observed_http_requests": 3,   # 少报两发
                               "unaccounted_calls": ["GET https://x.invalid/y"]})
        assert sneaky["http_requests_honest"] is False, "多发两发却仍判诚实 = BC-05 未修好"
        assert not sneaky["pass"] and sneaky["blockers"]  # 且必须真阻断, 不只是分数低

    def test_transport_error_repeat_makes_determinism_na(self):
        """传输层瞬断轮 → 确定性记 N/A 并点名轮次, 不记到被测代码账上 (2026-10-10)。"""
        from evals.groundtruth.metrics.m7_determinism import score_m7  # 行内导入: 只为这几条断言服务

        # 三轮里第 2 轮被传输层打断: 该轮落到空行集, 指纹必然与其余两轮不同
        degraded = score_m7({}, {                                       # 构造被瞬断的那一批
            "data_hashes": ["a", "empty", "a"],                         # 中间那条 = 空行集指纹
            "declared_http_requests": 3, "observed_http_requests": 3,   # 计数侧两侧相等: 诚实项应判过
            "repeat_states": [{"success": True, "transport_error": False},    # 第 1 轮正常
                              {"success": False, "transport_error": True},    # 第 2 轮被传输层打断
                              {"success": True, "transport_error": False}]})   # 第 3 轮正常
        assert degraded["deterministic"] is None, "传输层瞬断轮不该判确定性"       # 域闸: 记 N/A 而非 False
        assert degraded["transport_error_repeats"] == [2], "必须点名是哪一轮, 否则无从复核"   # 披露面
        assert "n/a" in degraded["determinism_domain"]   # 披露面要写明"这一项为何没判"
        assert degraded["pass"] and not degraded["blockers"]   # 计数诚实侧仍判, 且判过

        # 负对照 (防"永远绿"作弊): 同样三轮指纹不一致, 但无任何一轮属传输层失败 → 仍须判红
        clean = score_m7({}, {                                          # 干净的一批: 没有瞬断
            "data_hashes": ["a", "b", "a"],                             # 指纹真的漂了
            "declared_http_requests": 3, "observed_http_requests": 3,   # 计数侧仍然诚实
            "repeat_states": [{"success": True, "transport_error": False}] * 3})   # 三轮都正常
        assert clean["deterministic"] is False, "无瞬断时的指纹漂移必须照旧判红"   # 负对照的核心
        assert not clean["pass"] and clean["blockers"]                  # 且必须真阻断

    def test_no_measurable_m7_components_is_not_a_pass(self):
        """所有 M7 子项均缺证据时返回 N/A，不再把空分母算成满分。"""
        from evals.groundtruth.metrics.m7_determinism import score_m7

        result = score_m7({}, {
            "envelope": {"success": False, "error_code": "E_TRANSPORT"},
            "data_hashes": ["empty", "empty"],
            "repeat_states": [{"success": False, "transport_error": True}] * 2,
        })
        assert result["score"] is None
        assert result["pass"] is None
        assert result["evidence_status"] == "n/a_no_measurable_components"

    def test_any_transport_repeat_makes_batch_inconclusive(self, tmp_path, monkeypatch):
        """传输异常逐轮披露；该批不能汇总成 PASS，也不伪装成 SUT FAIL。"""
        scenario_file = tmp_path / "one.yaml"
        scenario_file.write_text("placeholder", encoding="utf-8")
        monkeypatch.setattr(run_e2, "load_scenario", lambda _path: {"case_id": "C1"})
        monkeypatch.setattr(run_e2, "load_gold", lambda _case_id: {})
        monkeypatch.setattr(run_e2, "detect_provenance_drift", lambda *_args: [])
        monkeypatch.setattr(run_e2, "pace", lambda _case_id: None)
        monkeypatch.setattr(run_e2, "run_scenario", lambda *_args, **_kwargs: {
            "repeat_states": [{"success": True, "transport_error": False},
                              {"success": False, "transport_error": True},
                              {"success": True, "transport_error": False}],
        })
        monkeypatch.setattr(run_e2, "compare_case", lambda *_args: {
            "metrics": {"m7_determinism": {"repeat_count": 3, "effective_repeats": 2,
                                           "transport_error_repeats": [2]}},
            "blockers": [], "weighted": 1.0, "pass": True,
        })
        monkeypatch.setattr(run_e2, "metascore", lambda _broken: 1.0)
        monkeypatch.setattr(run_e2, "load_broken_results", lambda: [])

        result = run_e2.run(tmp_path, repeat=3, mode=run_e2.MODE_LIVE)
        assert result["status"] == "inconclusive" and not result["pass"]
        assert result["repeat_coverage"] == {
            "planned_repeats": 3, "effective_repeats": 2,
            "transport_error_repeats": 1,
            "transport_error_cases": [{"case_id": "C1", "repeats": [2],
                                        "effective_repeats": 2, "planned_repeats": 3}],
            "complete": False,
        }
    def test_transport_classifier_keeps_contract_errors_out(self):
        """域闸只认传输层异常: 站点契约错误不得被它洗成"网络天气" (2026-10-10)。"""
        # 第三方: 传输层异常真身 (与 run_e2 的 name-based 判据对账)
        import requests  # 行内导入: 只在断言里用, 不进模块级依赖

        # 本地: 被测分类器
        from evals.groundtruth.run_e2 import _is_transport_error  # 行内导入: 同上

        assert _is_transport_error(requests.exceptions.ConnectionError("Connection aborted."))   # 连接中断
        assert _is_transport_error(requests.exceptions.ReadTimeout("timed out"))                 # 读超时
        # 负对照: 站点给了 HTTP 响应再报的错, 属被测行为, 不许被这道闸洗掉
        assert not _is_transport_error(requests.exceptions.HTTPError("500 Server Error"))        # 有响应
        assert not _is_transport_error(ValueError("E_INVALID_INPUT: 半径必须为正"))               # 契约错误

    def test_counts_are_not_the_same_object(self):
        """编排层不得把同一个计数器同时塞进两侧 (结构层面的承重断言)。"""
        actual = run_e2.run_scenario_once(
            run_e2.load_scenario(GT_DIR / "scenarios" / "cone_60as.yaml"),  # 黄金场景: 两阶段都跑得到
            mode=run_e2.MODE_LIVE)
        assert actual["observed_http_requests"] > 0  # 确实发过请求, 否则这条断言是空的
        assert "declared_http_requests" in actual and "unaccounted_calls" in actual  # 三个字段都要在
        # 回放两阶段查询里不该有解释不了的请求; 有则说明分类器漏了协议形态
        assert not actual["unaccounted_calls"], (
            f"回放层出现无法解释的请求: {actual['unaccounted_calls']}")




class TestM1DualDispatch:
    """M1 两套实现各走各的判据, 互不顶替。"""

    def test_replay_reports_precision_recall(self):
        """回放口径: 报 P/R 三元组, 少一行即判红。"""
        from evals.groundtruth.metrics.m1_rows import (
            score_m1,  # 行内导入: 与上一条同模块, 但刻意不提到顶层 (隔离到用例)
        )

        gold = {"row_keys": ["A", "B"]}          # 金标准两行
        out = score_m1(gold, {"mode": "replay", "rows": [{"source_id": "A"}]})  # 实测只回一行
        assert out["mode"] == "replay" and "recall" in out and "violations" not in out  # 字段形态即口径自报
        assert not out["pass"], "少一行还判过 = 行集口径没生效"

    def test_live_reports_invariants(self):
        """实跑口径: 报 violations 名单, 重复行即判红。"""
        from evals.groundtruth.metrics.m1_rows import score_m1  # 行内导入: 判定器按 mode 分派, 放在用例里才看得出调用点

        gold = {"max_rows": 2}                   # 预算两行
        rows = [{"source_id": "A"}, {"source_id": "A"}, {"source_id": "B"}]  # 三行且前两行同键
        out = score_m1(gold, {"mode": "live", "rows": rows})
        assert out["mode"] == "live" and "violations" in out and "recall" not in out  # 字段形态即口径自报
        assert not out["pass"], "重复行在 live 层必须判红"

    def test_missing_mode_falls_back_to_strict(self):
        """mode 漏传 → 走 replay (严的那套), 不静默降级成弱判据。"""
        from evals.groundtruth.metrics.m1_rows import score_m1  # 行内导入: 同上口径, 这里只验 live 分支的落点

        out = score_m1({"row_keys": ["A"]}, {"rows": []})  # 实测零行 vs 金标准一行
        assert out["mode"] == "replay"  # 缺省取严的那套
        assert not out["pass"]  # 且真的判红, 不是靠缺省走过场




class TestM6LiveReconcilability:
    """live 层"不可对账"要显式标记, 不许装作已验证。"""

    def test_snapshot_key_dropped_from_declared(self):
        """live 下版本身份移出分母, 但剩下两项仍要对得上。"""
        from evals.groundtruth.metrics.m6_version import (
            score_m6,  # 行内导入: M6 的可对账性只在此处断言, 故不进模块级导入
        )

        gold = {"snapshot_id": "sha256:old", "data_version": "ps1@old",   # 金标准带版本身份
                "catalog": "ps1", "endpoint": "/data/best/ps1/q"}
        actual = {"mode": "live",
                  "provenance": {"snapshot_id": None, "data_version": None,   # 真站点无版本标识面
                                 "catalog": "ps1", "endpoint": "/data/best/ps1/q"}}
        out = score_m6(gold, actual)
        assert out["reconcilable"] is False  # 显式标记: 不是"已验证"
        assert "snapshot_id" in out["not_reconcilable"]  # 且点名哪一项没验
        # 身份键移出分母: 剩下两项对得上, 才是"可对账的部分全过"
        assert out["declared"] == 2, f"身份键仍在分母里, live 层会恒红: {out}"
        assert out["pass"] and not out["cross_version_pollution"]  # 跨版本污染在 live 下无从指控

    def test_replay_still_reconciles_snapshot(self):
        """回放层仍要真判跨版本污染 —— 不许为了 live 把这道闸整个拆掉。"""
        from evals.groundtruth.metrics.m6_version import score_m6  # 行内导入: 与上条同源, 拆开是为了两条断言各自可读

        gold = {"snapshot_id": "sha256:old", "catalog": "ps1", "endpoint": "/data/best/ps1/q"}
        actual = {"mode": "replay",
                  "provenance": {"snapshot_id": "sha256:new", "catalog": "ps1",   # 拿 A 的答案报 B 的出处
                                 "endpoint": "/data/best/ps1/q"}}
        out = score_m6(gold, actual)
        assert out["reconcilable"] is True and not out["not_reconcilable"]  # 回放层这道闸仍在
        assert out["cross_version_pollution"] and not out["pass"]  # 且真判红




class TestCompareCaseBlockersAreLoadBearing:
    """B4 承重断言: ``compare_case`` 的 ``and not blockers`` 不可删。

    **这条为什么必须单独立**: J1 实测把 ``and not blockers`` 整条删掉, 1720 条
    测试**零条**变红 —— 也就是说这一段判据在测试面上完全没有承重。删掉它之后,
    "某个指标报了阻断项但加权分仍然很高" 的 case 会照放行, 而门禁显示通过。
    下面两条用例就是那道缺失的承重面: 构造**加权分接近满分但带阻断项**的输入,
    断言整批判红。

    构造方式选的是"把某指标的 ``blockers`` 塞满、``score`` 仍给 1.0" —— 这正是
    真实失效的样子 (自证性判据偶尔多报一条阻断), 也正是纯看均分会放过去的样子。
    """

    def test_blockers_override_perfect_weighted_score(self):
        """加权分过线 + 有阻断项 ⇒ 判红 (均分救不回来)。"""
        from evals.groundtruth.metrics import (  # 行内导入: 阈值与对账入口配对取, 缺一断言就没法判
            PASS_SCORE,
        )

        gold = {"snapshot_id": "syn_boundary", "catalog": "ps1",
                "endpoint": "/data/best/ps1/q", "row_keys": ["A"], "result_state": "rows"}
        actual = {"rows": [{"source_id": "A"}],
                  "envelope": {"total_count": 1, "returned_count": 1,
                               "truncated": False, "success": True},
                  # 唯一的差异: 报了个对不上的快照身份 → M6 判跨版本污染 (阻断级)
                  "provenance": {"snapshot_id": "sha256:other", "catalog": "ps1",
                                 "endpoint": "/data/best/ps1/q"},
                  # mode 必须钉 live: 回放臂已于 2026-10-07 整链删除, 传 replay 会让
                  # M4 抛 NotImplementedError 而不是走完七指标 —— 这条要断的是
                  # 「blockers 能否压过均分」, 不是「回放臂还在不在」。
                  # live 下 M6 仍会判跨版本污染: 身份键虽移出声明集, 但两侧非空且
                  # 完全不交时 cross_version 照样成立 (见 m6_version 的口径注释)。
                  "mode": "live"}
        compared = compare_case(gold, actual)
        # 前置条件: 加权分**过得了**旧的纯均分阈值 —— 否则"被均分救回来"无从谈起,
        # 本条断言会退化成"本来就红", 删掉 and not blockers 也不会暴露问题
        assert compared["weighted"] >= PASS_SCORE, (
            f"对照前提不成立: 加权分只有 {compared['weighted']:.4f} < {PASS_SCORE}, "
            "即使删掉 and not blockers 也未必放行")
        assert compared["blockers"], "前置条件: 该 case 必须真的带阻断项"
        assert not compared["pass"], (
            "加权分过线且有阻断项却判过 = and not blockers 失效: "
            "证伪级问题被均分洗掉了 (铁律 5 禁的那类)")

    def test_pass_clause_still_consults_blockers(self):
        """结构层负对照: ``pass`` 判据里必须仍有一个引用 ``blockers`` 的合取项。

        这条不看运行时表现, 只看**判据的结构**: 有人把 ``and not blockers`` 删掉,
        本条立刻红。上一条钉的是行为 (删了之后整批判红), 本条钉的是成因 (那句话
        还在不在) —— 两条一起, 才不会出现"行为测试因为别的巧合仍然绿"。
        """
        from evals.groundtruth import metrics as agg  # 行内导入: AST 要读的是 compare_case 自身的源码, 不能经门面转发

        src = textwrap.dedent(inspect.getsource(agg.compare_case))
        tree = ast.parse(src)
        pass_exprs = [v for node in ast.walk(tree)
                      if isinstance(node, ast.Return) and isinstance(node.value, ast.Dict)
                      for k, v in zip(node.value.keys, node.value.values)
                      if isinstance(k, ast.Constant) and k.value == "pass"]
        assert len(pass_exprs) == 1, "compare_case 的返回字典里应有且只有一个 pass 位"
        expr = pass_exprs[0]
        assert isinstance(expr, ast.BoolOp) and len(expr.values) == 2, (
            "pass 判据必须仍是两个合取项 (指标全过 / 零阻断); "
            "少一个就是有人删掉了 and not blockers")
        assert any(isinstance(v, ast.UnaryOp) and isinstance(v.op, ast.Not)
                   and isinstance(v.operand, ast.Name) and v.operand.id == "blockers"
                   for v in expr.values), (
            "两个合取项里必须有一项是 `not blockers` —— 阻断项任一命中即判红, "
            "加权分不得覆盖")




class TestLiveRunReportDisclosure:
    """live 批次的报告必须自报接线, 且不可对账项要点名。"""

    def test_report_carries_mode(self):
        """报告抬头必须写明这批是哪一层 —— 读者不能靠猜。

        2026-10-07 起库里只剩 live 一条臂 (回放层与 transport 已删, 见
        ``docs/REPLAY-RETIREMENT-CRITERIA.md``), 所以本条钉的是 ``live``:
        抬头必须自报 live + 点明行集类判据走不变量, 而不是宣称自己是回放基线。
        """
        one = GT_DIR / "scenarios" / "single_exact.yaml"  # 只跑单场景, 别把整批拉上网络
        report = run_e2.run(one, repeat=1, mode=run_e2.MODE_LIVE)
        assert report["mode"] == run_e2.MODE_LIVE  # JSON 侧自报
        md = run_e2.render_markdown(report)  # Markdown 侧也要说
        assert "live" in md and "不变量" in md  # 且要说清是哪一层、判据是什么
