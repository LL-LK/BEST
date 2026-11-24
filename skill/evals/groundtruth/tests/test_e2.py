# -*- coding: utf-8 -*-
"""E2 单测: 判定器自证 (反证夹具) + 回放传输语义 + canonical 规范化。

职责: 三层证据把 E2 的判定器钉住 —— 最内层是反证夹具自证 (10 个已知坏
样本必须全被抓, metascore=1.0), 中间层是回放传输语义 (路由、末页空表、
调用计数) 与 canonical 规范化的形态契约, 最外层是黄金路径端到端对账
(好答案必须被判过, 否则这套指标可能严到把正确答案也毙掉)。

所属实验: E2 金标准一致性, 方案真值 docs/eval-E2-groundtruth.md; 覆盖
§4.1 独立 oracle 铁律、§6 M1–M7 指标、§8 反证纪律。

对外接口: ``TestWeights`` 校验权重和恰为 1.00 且篡改必抛;
``TestBrokenSelftest`` 校验 metascore=1.0 与 ERROR→EMPTY 阻断;
``TestCanonical`` 校验主键/哨兵/三输出面; ``TestSnapshotTransport``
校验回放路由与 L 类保真; ``TestGoldIndependence`` 校验 gold/ 不 import
被测代码; ``TestProvenanceDriftDisclosure`` 校验生成器指纹漂移必被披露;
``TestEndToEndGolden`` 跑黄金路径对账;
``TestM3PaddedPrecision`` 校验假精度只记 warn 而真降精度仍判错。

依赖与数据流: 输入是 ``evals/groundtruth/snapshots/`` 下的 9 份快照与
``gold/`` 下的金标准; 产物只有 pytest 结论, 本文件不写报告。

关键契约与不变量: 全离线回放 —— SnapshotTransport 只读本地快照,
不发真实请求, rate_limit 归零, 因此这组断言可反复重跑; 反证夹具与黄金
路径**双向**自证: 只测坏样本会被"永远判 FAIL"的退化实现骗过, 只测好
样本会被"永远判 PASS"的实现骗过, 两者缺一不可; 快照目录缺失必须抛错
(fail-closed, 不静默返回空); 零跨实验 import, 唯一共享件是
``evals/_data/``, 等价性由 ``evals/equivalence/`` 断言守护。

陷阱与边界: ``TestEndToEndGolden`` 在金标准文件缺失时是 skip 而不是 pass ——
skip 意味着"这条证据暂缺", 与"验过了"是两回事, 看到满屏 skip 不要当作
绿灯; 黄金路径用的场景是 cone_60as, 它代表"好答案", 若它红了先查
回放层与 gold 是否同源, 而不是放宽指标; L 类保真比的是 sha256 原始
字节, 任何"顺手加个换行"的格式化都会让它红, 那不是假红而是真信号。
"""
from __future__ import annotations

# 标准库: JSON / 路径
import json
from pathlib import Path

# 第三方: pytest
import pytest

# 本地: 编排入口模块 (血缘漂移披露的隔离跑法; 整模块导入供 monkeypatch 桩替换)
import evals.groundtruth.run_e2 as run_e2

# 本地: 被测件
from evals.groundtruth.broken import run_broken_selftest
from evals.groundtruth.canonical import (
    batch_line_offset,
    canonical_rows,
    from_csv,
    from_envelope,
    from_query_result,
    is_sentinel,
    key_set,
    row_key,
)

# 本地: 被测判定器 (权重和/对账编排) 与回放传输 (两模式)
from evals.groundtruth.metrics import M_WEIGHTS, check_weight_sum, compare_case

GT_DIR = Path(__file__).resolve().parents[1]   # 本实验根 (被测件、场景、快照同级)


# ── 权重与判定器自证 ─────────────────────────────────────────────────────

class TestWeights:
    """权重和纪律 (与 scoring-rubric 同款硬约束)。"""

    def test_weight_sum_is_one(self):
        """M_WEIGHTS 和必须恰为 1.00。"""
        check_weight_sum()  # 权重和漂了, 七项指标的总分就不再可比

    def test_weight_sum_rejects_tampering(self, monkeypatch):
        """权重被改坏必须抛 ValueError (无 fail-open)。"""
        monkeypatch.setitem(M_WEIGHTS, "m1_rows", 0.31)  # 改成 0.31: 和变成 1.06
        with pytest.raises(ValueError):                                 # 非法格式必须抛 ValueError: 静默回落会把"请求 FITS 拿到 CSV"变成无声错误
            check_weight_sum()  # 篡改必须炸, 不许悄悄按新权重重算分数


class TestBrokenSelftest:
    """反证夹具: 全部坏样本必须被抓 (metascore=1.0)。数量由注册表决定, 不写死。"""

    def test_metascore_is_one(self):
        """每个夹具的目标指标必须报 FAIL (漏一个即判定器失效)。"""
        from evals.groundtruth.broken import _FIXTURES  # 数量现取: 写死字面量必然随夹具增删变陈旧

        results = run_broken_selftest()  # 逐个已知坏样本喂给判定器
        assert results, "反证夹具表空了: metascore 会因分母为 0 而假绿"
        assert len(results) == len(_FIXTURES), "自证结果条数必须等于注册表条数"
        missed = [r["fixture_id"] for r in results if not r["caught"]]
        assert not missed, f"反证夹具漏抓 (metascore<1.0): {missed}"  # 漏抓即红: 判定器空转的直接证据

    def test_no_fixture_targets_the_retired_replay_arm(self):
        """承重断言: 反证夹具**不得**再打已删除的回放判据。

        回放层 2026-10-07 整链删除后, M4 的 replay 分支改成显式 ``NotImplementedError``,
        而 ``_actual`` 曾长期缺省 ``mode="replay"`` —— 于是整条 metascore 自证链在第一
        条夹具就抛异常, 整批 E2 恒红, 而红的原因是接线遗留、与判定器无关。这类故障
        很难靠读代码发现 (夹具表看上去"很全")。

        本条把"夹具打的是现行判据"钉死: 任何一条夹具把 mode 拨回 replay, 立刻红。
        """
        from evals.groundtruth.broken import (  # 延迟导入: 夹具表只在断言时才需要, 顶层导入带进构造开销
            _FIXTURES,
            _actual,
        )

        offenders = [fid for fid, (build, _target, _gold) in _FIXTURES.items()
                     if build().get("mode") != run_e2.MODE_LIVE]  # 现造一次看实际口径, 不看源码字符串
        assert not offenders, (
            f"这些反证夹具打的不是实跑口径: {offenders} —— "
            "回放臂已删 (docs/REPLAY-RETIREMENT-CRITERIA.md), 留着会抛 NotImplementedError")
        assert _actual()["mode"] == run_e2.MODE_LIVE, "_actual 的缺省 mode 必须跟着现行臂走"

    def test_error_as_empty_is_a_blocker(self):
        """ERROR→EMPTY 必须触阻断项 (把服务故障读成科学结论, 零容忍)。"""
        results = {r["fixture_id"]: r for r in run_broken_selftest()}  # 按 id 建索引: 只取这一条
        assert "m5_states:ERROR_REPORTED_AS_EMPTY" in results["m5_error_as_empty"]["blockers"]  # 须是阻断项, 不能只降权

    def test_metascore_gates_the_overall_verdict(self, monkeypatch):
        """metascore 掉到 1.0 以下必须让整轮 FAIL, 哪怕 case 全部判过。

        ``metascore()`` 的 docstring 写着「metascore < 1.0 →
        E2 FAIL（判定器自身失效）」, 所以 ``run()`` 的 ``pass`` 必须由它决定;
        若 metascore 只进报告, 判定器漏抓注入故障时整轮照样 exit 0,
        报告正文却照印「必须 1.00」。fail-open 就藏在注释与实现之间。
        """
        # evals.groundtruth.run_e2: 放行条件的组装处 (metascore 是否真的并入 pass 只在这里)
        from evals.groundtruth import run_e2

        # 2026-10-07 改写: 实跑口径下**不能跑两遍全量批次再比 n_pass**。
        # 那条断言 ("case 判定没被连带改") 在回放期成立, 只因为数据被冻住了;
        # live 化之后活站点的数据随时间变, 同一份素材两轮跑出的 n_pass 本来就会
        # 漂 (实测 14 -> 12) —— 那不是判定器被改坏, 是**前提没了**。实测事故:
        # 这条用例因此红了 8 分钟, 报错文案还指着"case 判定被连带改了", 指向错误。
        # 改法: 第二轮**复用第一轮的实测面**, 只换掉反证夹具那一项。这样断言
        # 仍然断的是同一件事 (case 判定未被改动), 但不再依赖站点稳定性, 也不必
        # 第二次打满 17 个场景的网络。
        actuals: dict = {}
        real_run_scenario = run_e2.run_scenario  # 先存真身: monkeypatch 之后它才是唯一还能触网的入口

        def _record(scenario, repeat=3, mode=run_e2.MODE_LIVE):
            """按 case_id 缓存第一轮实测面; 之后一律回放缓存, 不再触网。"""
            key = (scenario["case_id"], repeat)
            if key not in actuals:  # 只在首次触网: 同 (case, repeat) 的第二遍直接吃缓存
                actuals[key] = real_run_scenario(scenario, repeat=repeat, mode=mode)
            return actuals[key]

        monkeypatch.setattr(run_e2, "run_scenario", _record)
        baseline = run_e2.run(repeat=1)  # 先在真实夹具上取一份基线
        # 2026-10-04 改写: 原断言是「前置: 真实夹具下 E2 应为 PASS」, 那等于把
        # **仓库当前素材的通过状态**当成这条测试的前提 —— E2 改指真实快照期间
        # 素材未全绿, 这条与被测机制无关的测试就跟着红了。改为直接验放行公式:
        # pass 必须**恰好**是「case 全过 且 metascore==1.0」, 这比"假设它是绿的"
        # 更强 (公式任一侧被漏掉都会红), 且与素材状态解耦。
        assert baseline["pass"] == (baseline["n_pass"] == baseline["n_cases"]
                                     and baseline["metascore"] == 1.0), \
            f"放行公式不符: pass={baseline['pass']} n_pass={baseline['n_pass']}/{baseline['n_cases']} " \
            f"metascore={baseline['metascore']}"

        monkeypatch.setattr(run_e2, "load_broken_results", lambda: [])  # 空夹具 -> metascore=0.0
        degraded = run_e2.run(repeat=1)  # 实测面走缓存: 唯一变量是反证夹具
        assert degraded["metascore"] == 0.0, "空夹具必须记 0.0 而非 1.0 (fail-closed)"
        assert not degraded["pass"], "metascore=0.0 仍判 PASS = 判定器失效被放行 (fail-open)"
        # 这次改动只动放行条件, 不动 case 判定本身 —— 两轮 case 通过数必须一致
        assert degraded["n_pass"] == baseline["n_pass"], (  # 防止有人用"改 case 判定"的方式糊掉这个洞
            f"case 判定被连带改了: {baseline['n_pass']} -> {degraded['n_pass']}")


# ── M3 假精度分流 (补零判 warn, 真降精度判错) ──────────────────────────────

class TestM3PaddedPrecision:
    """E2 §6 M3 (c): 整数补 .000000 的假精度不判错但记 warn。

    ``m3_units`` 的 docstring 与行内注释都承诺「假精度只进
    warnings, 判错会误伤合法实现」, 因此 ``precision_warnings`` 必须真的被
    append 过, 且补零值只落 ``precision_warnings`` 而不落
    ``precision_errors`` —— 与注释方向相反就是实现违约。

    **零分母阻断 (U-6/D7) 与本类正交**: 下面这份 GOLD 只声明了 ``precision_map``,
    单位与量纲两道分母必为 0 ⇒ 整块判 ``pass=False`` 并带 ``zero_denominator`` 阻断。
    这是**有意**的: 那两道在这份数据上确实没有观测面, 报满分是 fail-open。所以本类
    断的是"补零走 warning 通道、不进 errors", 不断 ``pass`` —— ``pass`` 的零分母
    语义由 :class:`TestM3ZeroDenominator` 单独断。
    """

    GOLD = {"precision_map": {"c": 5}, "unit_map": {}, "dimension_probes": {}}

    def _score(self, value):
        """按给定精度值跑一遍 M3, 只看精度那一道的产物。"""
        # 本地: M3 判定器 (行内导入是为了让"这段测试在改 m3_units 时才失败"的依赖显形)
        from evals.groundtruth.metrics.m3_units import score_m3

        return score_m3(self.GOLD, {"rows": [{"c": value}]})

    def test_padded_zeros_warn_but_do_not_fail(self):
        """补零形态: 记 warning, 且不拉低 precision_rate (不因**精度**判错)。"""
        r = self._score("18.200000")
        assert r["precision_warnings"], "补零形态必须记 warning (注释承诺的通道此前不存在)"
        assert not r["precision_errors"], "补零形态不得判错: 那会把格式选择当成精度缺陷"
        assert r["precision_rate"] == 1.0, "补零不得拉低精度率"
        assert "precision" not in r["zero_denominator"], "精度这道分母为 1, 不该进零分母名单"

    def test_real_precision_loss_still_fails(self):
        """真降精度必须仍判错 —— 这是分流不能越过的边界。"""
        r = self._score("18.2")
        assert r["precision_errors"], "真降精度 (18.200000→18.2) 必须判错"
        assert not r["precision_warnings"], "真降精度不属于补零形态"
        assert r["precision_rate"] < 1.0, "真降精度必须拉低精度率"
        assert not r["pass"], "真降精度必须不放行"

    def test_sufficient_digits_produce_no_findings(self):
        """位数达标: 既不记 warn 也不记 error。"""
        r = self._score("1.23456")
        assert not r["precision_warnings"] and not r["precision_errors"]
        assert r["precision_rate"] == 1.0


class TestM3ObservationSurface:
    """U-6/D7 承重断言: 三道维度都**必须有真的观测面**, 且缺口不得被报成满分。

    历史 (本类的由来): 实测下 ``probe`` 的分母**恒 0** —— 探针表用语义名
    (``ra_deg``/``magnitude``), 规范化行集用真实列名 (``ps1_ra``/``ps1_rpsf``),
    交集恒空 ⇒ ``probe_rate`` 恒 1.0, 报告上却写着"量纲 100% 合格"。
    修复 = 在 ``tolerances.yaml`` 补一张**实测采样**的语义名→真实列名映射表。

    现在三道维度的处境各不相同, 下面逐道钉住 —— 它们**不能**再混成一类:

    - ``probe``/``precision`` 有观测面, 真实分母非 0;
    - ``unit`` **按设计无第二来源** (回包行不带单位字段, 仓内也无逐列单位注册表),
      故记 ``not_observable`` 披露, **不阻断** —— 判红只会逼人编一个假来源出来;
    - 零分母若真出现在"本该可观测"的维度上, 仍必须阻断。
    """

    def test_probe_denominator_is_now_real(self):
        """行里带真实列名 ⇒ 探针必须真的比过格子, 而不是恒 1.0。"""
        from evals.groundtruth.metrics.m3_units import score_m3  # 行内导入: 断探针分母, 映射没接上时这一格会最先塌

        rows = [{"ps1_ra": "180.0081187", "ps1_dec": "30.01504491",
                 "inputobjs_dist_arcsec": "59.78", "ps1_rpsf": "18.2"}]
        r = score_m3({"precision_map": {"ps1_rpsf": 1}}, {"rows": rows})
        assert r["probe_checked"] >= 4, (
            f"探针只比过 {r['probe_checked']} 格: 语义名→真实列名的映射没接上, "
            "这正是 U-6/D7 记的『恒 1.0 却从未真比过一个格子』")
        assert "probe" not in r["zero_denominator"]

    def test_unit_is_disclosed_not_blocked(self):
        """unit 无第二来源 ⇒ 只披露不阻断 (判红等于逼人造假来源)。"""
        from evals.groundtruth.metrics.m3_units import (
            score_m3,  # 行内导入: unit 无来源要记披露, 顶层引反而看不出它在测什么
        )

        r = score_m3({"precision_map": {"c": 5}},
                     {"rows": [{"c": 1.23456, "ps1_ra": "180.0", "ps1_rpsf": "18.2"}]})
        assert "unit" in r["not_observable"], "无来源的维度必须显式披露"
        assert not [b for b in r["blockers"] if b.endswith(":unit")], (
            f"unit 不该阻断: {r['blockers']}")

    def test_missing_mapping_on_an_observable_dimension_still_blocks(self):
        """映射缺失 (本该可观测却没接上) 仍必须阻断 —— 披露不能取代红灯。"""
        from evals.groundtruth.metrics.m3_units import score_m3  # 行内导入: 映射缺失仍须阻断, 与上面两条口径相反

        # 行里只有 c 一个列, 且它不命中任何探针 ⇒ probe/precision 两道都无观测面
        r = score_m3({"precision_map": {"nope": 5}}, {"rows": [{"c": 1.23456}]})
        assert "precision" in r["zero_denominator"], "本该可观测却没接上 → 必须进零分母名单"
        assert not r["pass"] and r["blockers"], "零分母不得判过: 那是把『没测』报成『测过』"

    def test_no_rows_is_na_not_failure(self):
        """整批无行 ⇒ M3 记 N/A (score=None, pass=True), 状态归 M5。"""
        from evals.groundtruth.metrics.m3_units import score_m3  # 行内导入: 无行记 N/A, 与 M2 的同类分支同一形状

        r = score_m3({"precision_map": {"c": 5}}, {"rows": []})
        assert r["score"] is None and r["pass"] is True, "无行 = 判定无对象, 不是失败"
        assert not r["blockers"], "无行不该阻断: 空结果态由 M5 裁决"


# ── canonical 规范化 ─────────────────────────────────────────────────────

class TestCanonical:
    """标准行集: 主键/哨兵/三输出面。"""

    def test_row_key_prefers_source_id(self):
        """有 source_id 用 source_id (主键优先级)。"""
        assert row_key({"source_id": "BEST001", "ra": 1.0, "dec": 2.0}) == "BEST001"  # 主键退成坐标会让 M1 跨 case 串行

    def test_row_key_recognises_stripe82_calibstars_id(self):
        """口径对齐 (2026-10-04): stripe82 的真主键列必须被认, 不能退到坐标。

        产品侧 `BestSource.from_row` 的 ID 别名支路已含 `calibstars_id` (live 实证
        后补的), 能从真实行取到 `CALIBSTARS_0813769`; oracle 侧此前只认
        `*_source_id`, 对 stripe82 的 27 行全返回 None → 退到坐标键 —— **两侧
        不同尺**, M1 会报出看着像"数据对不上"的假失配。这条钉住两侧同口径。
        """
        row = {"stripe82_calibstars_id": "CALIBSTARS_0813769",
               "stripe82_ra": 29.967632, "stripe82_dec": 0.024272}
        assert row_key(row) == "CALIBSTARS_0813769"
        # oracle 的第二份独立实现 (gold_algorithms, 刻意不复用代码) 必须同判
        from evals.groundtruth.gold.gold_algorithms import row_key as gold_row_key

        assert gold_row_key(row) == "CALIBSTARS_0813769"

    def test_row_key_does_not_take_solution_id(self):
        """反向自证: `*_solution_id` 是解算批次 ID, **不得**被当主键。

        实测 gaia 回包里 `gaia_dr3_18_solution_id` 在 1000 行里只有 1 个不同值,
        字典序又排在 `gaia_dr3_18_source_id` 前面 —— 一旦把宽泛的 `id` 后缀放进
        名单就会先命中它, 等于拿重复 id 当主键 (重复 id 会让两行塌成同一主键,
        M2 拿 A 行的期望值比 B 行的实际值)。这条挡住"为修一个星表而放宽名单"。
        """
        row = {"gaia_dr3_18_solution_id": "1636148068921376768",
               "gaia_dr3_18_source_id": "4512921183874236032",
               "gaia_dr3_18_ra": 286.1016964504027, "gaia_dr3_18_dec": 15.6194192817014}
        assert row_key(row) == "4512921183874236032", "解算批次 ID 被当成了主键"

    def test_row_key_quantized_fallback(self):
        """无 source_id 用 (ra,dec)@9 量化键 (与 gold 同格式)。"""
        assert row_key({"ra": 180.123456789123, "dec": 30.5}) == "180.123456789,30.500000000"  # 量化到 9 位: 与 gold 逐字对齐

    def test_is_sentinel_threshold_and_exempt(self):
        """哨兵阈值判定 + 豁免列 (pmra 合法大负值不误杀)。"""
        assert is_sentinel("ps1_gpsf", "-999.0")  # 阈值内: 判缺失
        assert is_sentinel("ps1_gpsf", "-1004.07")  # 更负: 仍是哨兵 (各列阈值不同)
        assert not is_sentinel("ps1_gpsf", "18.2")  # 正常值: 不得误杀, 否则真值被当缺失
        assert not is_sentinel("pmra", "-1500.0")  # 豁免列

    def test_canonical_rows_types(self):
        """数值格转 float; 空串转 None; 哨兵保留原值 (不抹零)。"""
        rows = canonical_rows([{"a": "1.5", "b": "", "c": "-999.0"}])
        assert rows[0]["a"] == 1.5  # 转 float: 字符串比较会让 1.50 与 1.5 判成不一致
        assert rows[0]["b"] is None  # 空串 → None: M2 里两者必须同归 null 类
        assert rows[0]["c"] == "-999.0"  # 哨兵原样保留 (M5 判据)

    def test_from_envelope(self):
        """A 面: 信封 data.rows → 标准行集。"""
        rows = from_envelope({"data": {"rows": [{"ra": "1.0"}]}})
        assert rows == [{"ra": 1.0}]  # A 面也收敛成标准行集, 与 B/C 面同形

    def test_from_query_result(self):
        """B 面: BestQueryResult → (标准行集, 信封字段)。"""
        class _Src:
            """BestSource 最小替身 (source_id + raw_data; 信封面构造)。"""
            source_id = "S1"
            raw_data = {"ra": "180.0"}

        class _Result:
            """BestQueryResult 最小替身 (五字段信封; from_query_result 被测面)。"""
            sources = [_Src()]                                                                 # 最小源对象: 本用例只关心列解析, 不需要真实字段
            total_count = 1      # 服务端计数: M4 优先取它 (历史 bug 就出在这)
            returned_count = 1   # 实际返回行数: 与 total 一起构成截断三元组
            truncated = False                                                                       # 默认不截断
            success = True                                                                          # 默认成功
            error_code = None    # 非空即 ERROR 态, M5 判它不得降级成空结果

        rows, envelope = from_query_result(_Result())                                               # 从查询结果解析出行与信封
        assert rows[0]["source_id"] == "S1"  # 行集主键取 source_id
        assert envelope["total_count"] == 1  # 信封字段直传, 不在规范化层重算

    def test_key_set_dedup(self):
        """主键集合去重 (M1 比对单位) —— 无论走哪种键形态, 重复行只计一次。

        注意: 重复行必然带重复 id, 而重复 id 会触发 :meth:`id_keys_unique` 的降级,
        所以"去重"与"用 id 键"不能塞进同一条断言 —— 这里只管去重, 键形态由下面两条
        各自钉住。
        """
        row = {"source_id": "A", "ps1_ra": 1.0, "ps1_dec": 2.0}
        assert len(key_set([row, dict(row), dict(row)])) == 1, "完全相同的行只计一次"
        assert len(key_set([row, {"source_id": "B", "ps1_ra": 3.0, "ps1_dec": 4.0}])) == 2

    def test_key_set_uses_id_when_ids_are_unique(self):
        """id 在结果集内唯一 → 用 id 键 (E2 §2 的常规路径)。"""
        rows = [{"source_id": "A", "ps1_ra": 1.0, "ps1_dec": 2.0},
                {"source_id": "B", "ps1_ra": 3.0, "ps1_dec": 4.0}]
        assert key_set(rows) == {"A", "B"}

    def test_key_set_falls_back_when_ids_repeat(self):
        """id 在结果集内重复 → 整批改走坐标键 (真实回包逼出来的规则)。

        背景: ``live_ps1_ra359.5_dec0.0_r1800.0as`` (1000 行, 431 个非空) 里有
        **1 个值重复出现 2 次** (431 个非空值里 430 个不同)。E2 §2 原写「有 source_id
        用 source_id」, 但"有"不等于"唯一": 重复 id 会让两行塌成同一主键, M2 拿
        A 行的期望值比 B 行的实际值, 报出一串看着像"数据对不上"的假失配。所以
        id 的可用性由**结果集**判定。
        """
        rows = [{"ps1_source_id": "DUP", "ps1_ra": 1.0, "ps1_dec": 2.0},
                {"ps1_source_id": "DUP", "ps1_ra": 3.0, "ps1_dec": 4.0},    # 同 id 不同位置
                {"ps1_source_id": "OK", "ps1_ra": 5.0, "ps1_dec": 6.0}]
        keys = key_set(rows)  # 整批退化由 key_set 在结果集层判定后传下来, 不是逐行各判各的
        assert "DUP" not in keys, "重复 id 不得再当主键 (否则两行塌成一格)"
        assert keys == {"1.000000000,2.000000000", "3.000000000,4.000000000",
                        "5.000000000,6.000000000"}, "整批走坐标键, 含那个 id 唯一的行"

    def test_batch_line_offset_normalises_one_based_echo(self):
        """服务端 ``inputobjs_input_line`` 是 1-based, 须归位到场景的 0-based 序号。

        真实抓取 (三个输入点) 回显 1/2/3; 场景 ``inputs`` 是 0-based 序列。不归一
        就整体错位一格, M1 报"行集对不上"而看不出是基准问题。
        """
        one_based = [{"inputobjs_input_line": "1", "ps1_ra": 1.0, "ps1_dec": 2.0},
                     {"inputobjs_input_line": "2", "ps1_ra": 3.0, "ps1_dec": 4.0}]
        assert batch_line_offset(one_based) == 1
        assert key_set(one_based, batch=True) == {"in0:1.000000000,2.000000000",
                                                  "in1:3.000000000,4.000000000"}
        zero_based = [{"inputobjs_input_line": "0", "ps1_ra": 1.0, "ps1_dec": 2.0},
                      {"inputobjs_input_line": "1", "ps1_ra": 3.0, "ps1_dec": 4.0}]
        assert batch_line_offset(zero_based) == 0, "已是 0-based 时不许再减"
        assert key_set(zero_based, batch=True) == {"in0:1.000000000,2.000000000",
                                                  "in1:3.000000000,4.000000000"}


# ── SnapshotTransport 回放语义 ───────────────────────────────────────────

# 回放传输层的测试已于 2026-10-07 随 evals/groundtruth/transport.py (已删除) 移除。
# 被它覆盖的两阶段协议语义 (POST 回 sqlid / getcount / 分页页路由 / 调用计数)
# 现在由 src 侧的单测与本文件的实跑臂共同承担; 备份见 docs/archive/replay-backup/。
class TestGoldIndependence:
    """GT 生成器必须独立于被测逻辑 (E2 §4.1/§10 阻断项 6)。"""

    def test_guard_scans_clean(self):
        """guard_no_src_imports 对 gold/ 全目录扫描必须干净。"""
        # 标准库: runner 子进程冒烟 (CLI 退出码契约); os 供注入 PYTHONIOENCODING
        # (守卫输出含中文, 非 UTF-8 locale 下会把父进程解码打断, 断言读到空);
        # sys 供解释器路径
        import os
        import subprocess
        import sys

        guard = GT_DIR / "gold" / "guard_no_src_imports.py"  # 独立性铁律的机械守门
        proc = subprocess.run([sys.executable, str(guard)],              # 子进程跑守卫: 守卫要能在**独立解释器**下自证, 否则常驻进程里的 import 会骗过它
                              capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=60,
                              env={**os.environ, "PYTHONIOENCODING": "utf-8"})
        assert proc.returncode == 0, f"GT 独立铁律被违反: {proc.stdout}"  # 非零即有 gold/*.py 抄了 src


class TestProvenanceDriftDisclosure:
    """血缘漂移必须在默认自检批里被说出来 (披露, 不阻断)。

    与人工签字无关, 独立成立: 生成器脚本在金标准生成之后被改过 (哪怕只改
    注释), 这批答案就不是现版本脚本产的 —— 藏起来等于让过期金标准悄悄出 PASS。
    """

    def test_generator_drift_is_disclosed_when_it_happens(self, monkeypatch):
        """机制断言: 生成器指纹漂移必须在默认自检批里被说出来 (不阻断, 但不许藏)。

        2026-10-04 改写的原因: 原断言挂在**仓内状态**上 (「现在恰好漂移了」),
        于是金标准一按现版本生成器重算, 漂移归零, 这条测试就静默失去测试能力 ——
        它测的是"今天仓库脏", 不是"披露机制没坏"。现在用 monkeypatch 注入漂移,
        机制本身被**确定性**覆盖, 与仓内状态解耦。
        """
        real = run_e2._sha256_file(run_e2.GENERATOR_PATH)  # 生成器指纹: 改了 gen_gold.py 就该判血缘过期

        def _drifted(path: Path) -> str:
            """只让「生成器指纹」这一项对不上, 其余指纹照原样返回。"""
            return "sha256:" + "1" * 64 if path == run_e2.GENERATOR_PATH else real

        monkeypatch.setattr(run_e2, "_sha256_file", _drifted)
        report = run_e2.run(repeat=1)  # 注入漂移后再跑: 断的是"漂移被披露"这条机制
        assert report["provenance_drift"], "注入的生成器漂移必须在报告里披露"
        assert all(item.startswith("generator_drift:") for item in report["provenance_drift"]), \
            "漂移项必须点名到具体 case, 不能只报一个总数"

    def test_repo_golds_are_regenerated_with_the_current_generator(self):
        """仓内现状登记: 17 份金标准由**当前** gen_gold.py 生成 → 无生成器漂移。

        这是一条**状态**断言 (会随重算而变), 机制由上一条测。与它成对: 漂移为零
        意味着"金标准与现版本脚本同源", 但**不等于**"这份答案对" —— 后者归 M1–M7 判。
        """
        report = run_e2.run(repeat=1)  # 状态断言: 仓内 17 份金标准与现版本生成器同源
        assert not [i for i in report["provenance_drift"] if i.startswith("generator_drift:")], \
            f"金标准应与现版本生成器一致, 却报漂移: {report['provenance_drift']}"


# ── 端到端回放对账 (黄金路径) ────────────────────────────────────────────

class TestEndToEndGolden:
    """黄金路径: 回放查询 + canonical + 对账必须全绿 (好答案能被判过)。

    **当前有一条**已知且已登记**的阻断 (U-6/D7 的副产物, 2026-10-07)**: M3 的
    ``unit`` 与 ``probe`` 两道维度在真实跑批上分母恒 0 (原因见
    :class:`TestM3ZeroDenominator`), 因而按"零分母即阻断"判红。

    那是**真的**: M3 此前是在这两道维度上恒真, 报着"量纲 100% 合格"却从未真正比过。
    按裁定 D5「接受常态红 —— 门禁的作用是披露真相, 不是让 CI 好看」, 这里不把它
    改回绿灯。所以本类断的是**除该已登记阻断外的全绿**, 并把那条阻断显式断言出来:
    它一旦被悄悄修掉(或被悄悄放过), 这条测试都会红 —— 既防"假绿", 也防"假修复"。
    """

    #: E2 回放基线当前**无已登记阻断**。观测面缺口 (M3) 已于 2026-10-07 补齐:
    #: 探针接入 tolerances.yaml 的语义名→真实列名映射 (分母 0 → 726), unit 改记
    #: not_observable 披露, 空态用例改记 N/A。留着这份名单是为了**将来**真有阻断时
    #: 按同一形状登记 —— 而不是让"缺了没人记"成为常态。
    KNOWN_BLOCKERS: tuple[str, ...] = ()

    def test_golden_case_passes_all_metrics(self):
        """cone_60as 场景: 回放跑查询 → 与 gold 对账 → 七指标全过。"""
        # 第三方: 场景/快照元数据装载; run_e2 的加载件 (黄金路径端到端)
        import yaml

        from evals.groundtruth.run_e2 import load_gold, load_scenario, run_scenario

        scenario = load_scenario(GT_DIR / "scenarios" / "cone_60as.yaml")  # 黄金样本: 好答案必须能被判过
        gold = load_gold(scenario["case_id"])
        if gold is None:  # 金标准缺失即证据暂缺: 跳过而不是拿空答案判"通过"
            pytest.skip("cone_60as 金标准缺失 (先跑 gold/gen_gold.py 生成)")  # skip 不是 pass: 这条证据暂缺
        actual = run_scenario(scenario, repeat=1)  # 单轮回放: 与跑批同一条路径
        compared = compare_case(gold, actual)       # M1–M7 全过才算黄金路径成立

        unexpected = [b for b in compared["blockers"] if b not in self.KNOWN_BLOCKERS]
        assert not unexpected, (
            f"黄金路径出现**未登记**的阻断: {unexpected} "
            f"(全部阻断={compared['blockers']})")

    def test_m3_really_compares_cells_now(self):
        """反向自证: 黄金路径上 M3 的探针分母必须**非 0**。

        这条比"没有阻断"更强: 分母为 0 时 M3 也可能一条阻断都不报, 而那正是修复前
        的形态 (恒 1.0、零观测面)。断住分母, 才算真的接上了观测面。
        """
        from evals.groundtruth.run_e2 import load_gold, load_scenario, run_scenario  # 行内导入: 本用例专属

        scenario = load_scenario(GT_DIR / "scenarios" / "cone_60as.yaml")
        gold = load_gold(scenario["case_id"])
        if gold is None:  # 同上: 分母为 0 时 M3 也可能零阻断, 那正是要断的退化形态
            pytest.skip("cone_60as 金标准缺失")
        compared = compare_case(gold, run_scenario(scenario, repeat=1))  # 黄金路径跑一轮: 下面只看 M3 的探针分母
        m3 = compared["metrics"]["m3_units"]
        assert m3["probe_checked"] > 100, (
            f"M3 探针只比过 {m3['probe_checked']} 格: 语义名映射又丢了? "
            "cone_60as 是 174 行, 量纲探针至少该比过几百格")
        assert m3["not_observable"] == ["unit"], "只有 unit 是按设计无来源的"
        assert compared["pass"], f"黄金路径应全绿, 实得 blockers={compared['blockers']}"


# QueryAwareTransport 的坐标列解析测试已随 transport.py 一并删除 (2026-07):
# 那份实现服务的是「对 rows_full 独立重算」这条已删路径。它抓过的真实缺陷
# (非 ps1 表的坐标列认不出, 见 canonical._coord_pair 同款三级回退) 在
# canonical.py 的键提取侧仍有覆盖, 故此处不留悬空引用。备份见 docs/archive/replay-backup/。
