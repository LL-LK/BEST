# -*- coding: utf-8 -*-
"""evals/repro/tests/test_e6_metrics.py — E6 指标面守门 (拆分件 2/2)。

覆盖对照 (docs/eval-E6-reproducibility.md):
  §5.1-§5.4 四一致率各至少一正 (全一致=1.0) 一反 (扰动后 <1.0 或降级);
  §4.3 分层归因七行决策表 (顺序铁律: 自上而下第一条命中即用);
  §6   EF1..EF7 (理论最小请求数 / η 比值 / 含不含 rate_limit 两口径墙钟);
  §7   U1..U6 客观机读判据 + U7 无评阅人返回 None 且不进门禁;
  §9   反证夹具 12 条扰动 (BF 一致性 6 类 + TI trace 完整性 6 类) 必须全部 detected;
  §11  R0 地板线 (18×2 四一致率全 1.0) + 32 任务集硬约束 (禁相对时间);
  §12  runner 冒烟: CLI 退出码 0。

拆分缘由 (budget R2): 原单文件 743 净行超 400 预算 — 与
test_e6_foundation.py (输入面/统计) 对切, 共享夹具构造落 support_e6.py。
纪律: 只测不补; "软 404 记成空 rowset"(r0_lane) 一处真缺陷的修法, 钉在对应
test 的 docstring 里。

职责: 守住 E6 的**指标面** —— 四一致率 (TSC/PAC/RDC/FCC) 的正反例、分层归因
  的七行决策表与顺序铁律、EF1..EF7、U1..U7、12 条反证夹具, 以及 R0 地板线
  必须四率全 1.0 这条阻断项。
所属实验: E6 可复现与效率 (32 任务 + R0 路实跑); 判据真值是
  docs/eval-E6-reproducibility.md §4.3 / §5.1-§5.4 / §6 / §7 / §9 / §11 /
  §12, 本文件只断言代码与那几节一致, 不重新定义指标。
对外接口: 无 (pytest 收集面)。TestConsistency / TestAttribution /
  TestEfficiency / TestUsability / TestBrokenSelftest / TestR0LaneFloor
  六个类, 分别对应上列六节。
依赖与数据流: 输入 = evals/repro/tests/support_e6.py 里共享的夹具构造
  (_call_run / _attr_run / _write_trace / _BASE_CARD / _MODE_CALLS 等) 与
  fixtures/ 下的真实快照 (经 run_lane 离线回放); 产物 = pytest 断言结果,
  不落盘、不联网。
关键契约与不变量: 全程离线 —— R0 那一节跑的是真实客户端但网络被整体换成
  ReplayTransport, 一条真实请求都发不出去; 零跨实验 import (只引
  evals.repro.*); 同一份代码重复跑必须得到同一结论, 所以这里不断言墙钟
  绝对值, 也不依赖任何跨进程状态。跨实验等价性由 evals/equivalence/ 的
  断言守护。
陷阱与边界: 归因决策表的**顺序**比内容更容易坏 —— 七行规则改顺序时每行
  单独测都还过, 只有"两个缺陷同时出现"的四条顺序铁律用例才抓得住, 那些
  用例是本文件最不能删的部分。R0 地板线同理: 四率全 1.0 看着像理所当然,
  一旦代码里混进任何隐藏随机源, 它是唯一会在 CI 里立刻报警的地方。
"""
from __future__ import annotations

# 标准库: JSON (报告与 schema) / 环境变量 (子进程编码) / 子进程 (runner 冒烟) /
#         sys (子进程编码注入)
import json
import os
import subprocess
import sys

# 第三方: pytest / requests (FakeResponse 抛 HTTPError 与真实 requests 同语义)
import pytest
import requests

# 本地: 被测模块 (指标面: 一致率/归因/效率/可用性/反证/R0/冒烟)
from evals.repro.attribution import (  # noqa: E402
    ATTRIBUTION_CODES,  # 归因码全集: 断言按全集比, 少一个码会静默漏检那一类失真
    SCHEMA_TOOLS,  # 工具面权威 schema: 用例按它构造夹具, 不在测试里硬编码工具名
    attribute_lane,
    attribute_run,
)

# 本地: 被测指标面 (本文件的守门对象)
from evals.repro.broken import (  # noqa: E402
    FIXTURES,
    run_broken_selftest,
    tsc_order_sensitivity_check,  # 顺序敏感探针: 集合相等却语义相反的两条路径, 靠它才抓得到
)
from evals.repro.consistency import (  # noqa: E402
    fcc,
    pac,
    rdc,
    tsc,
)

# 本地: 效率面被测件 (EF1..EF7 与理论最小请求数)
from evals.repro.efficiency import (  # noqa: E402
    ef1_request_ratio,
    ef2_wall_clock,
    ef3_redundant_calls,
    ef4_ineffective_retries,
    ef5_paging,
    ef6_zero_request_completion,
    ef7_tokens,
    summarize_efficiency,
    theoretical_min_requests,
)

# 本地: R0 路预写序列 (地板线判据的输入)
from evals.repro.r0_lane import (  # noqa: E402
    R0_SEQUENCES,  # R0 预写序列表: 32 条任务的工具序列都在这里, 改它等于改跑批口径
    run_lane,  # R0 路入口: 唯一不经 mock 的那条路, 离线实跑的证据来自它
    run_once,
)

# 本地: 编排入口 (清单与跑批的绑定面)
from evals.repro.run_e6 import bind_manifest  # noqa: E402

# 本地: 共享夹具 (对账单点 — bootstrap/常量/最小现场)
from evals.repro.tests.support_e6 import (  # noqa: E402
    _BASE_ARGS,
    _BASE_CARD,
    _BASE_HASH,
    _MODE_CALLS,
    _MODE_CARD,
    _SKILL_ROOT,
    FIXTURES_DIR,
    REPRO_DIR,
    RUNNER,
    TOOLS_SCHEMA,
    _attr_run,
    _break_seq,
    _call_run,
    _cone,
    _drop_final,
    _drop_header,
    _drop_result,
    _mutated,
    _valid_manifest,
    _write_manifest_file,
    _write_trace,
)

# 本地: 可用性面被测件 (U1..U7)
from evals.repro.usability import (  # noqa: E402
    STABLE_ERROR_CODES,
    summarize_usability,
    u1_first_usable,
    u2_error_operability,
    u3_clarify_quality,
    u4_self_explaining,
    u5_step_ratio,
    u6_honest_degradation,
    u7_cognitive_load,
)

# ── 5. consistency: 四一致率 ─────────────────────────────────────────────

class TestConsistency:
    """TSC/PAC/RDC/FCC: 每项至少一正 (全一致=1.0) 一反 (扰动后 <1.0 或降级)。"""

    # 每个指标都必须同时有正反两例: 只有正例的话, 一个恒返回 1.0 的实现
    # 就能全绿, 而恒 1.0 恰恰是"指标失效"最常见的形态

    def test_tsc_identical_runs(self):
        """正: N 次工具序列全同 → tsc=1.0 且众数序列正确。"""
        result = tsc([["cone_search", "count"]] * 5)   # 5 次同序列: 众数与一致率都可判
        # 两个断言分工: tsc 断指标值, mode_sequence 断参照本身 ——
        # 参照错了比值也可能仍是 1.0, 只断比值就看不出参照出了什么问题
        assert result["tsc"] == 1.0 and result["mode_sequence"] == ["cone_search", "count"]  # 挡住恒返回 1.0 的空转实现

    def test_tsc_order_sensitivity(self):
        """反: 同集合反序 → strict<1.0 而 set=1.0 (序列口径的意义, 文档 §5.1)。

        这条守的是 TSC 存在的理由: 只看工具集合的话, resolve_name→cone_search
        与 cone_search→resolve_name 语义相反却会被判成一致。
        """
        result = tsc([["cone_search", "resolve_name"]] * 4 + [["resolve_name", "cone_search"]])  # 4+1: 反序那条是少数
        assert result["tsc_strict"] < 1.0         # 挡住主口径退化成集合比法
        # 断 set 仍为 1.0: 宽松档与严格档必须同时成立, 才证明"差异来自顺序
        # 而不是来自少调了哪个工具"
        assert result["tsc_set"] == 1.0
        assert result["pairwise"] < 1.0

    def test_tsc_empty_runs(self):
        """反: 空运行集 → tsc=0.0 (不虚报一致)。

        断 0.0 而不是 1.0: 没数据不是"完美一致", 报 1.0 会让这个任务在
        汇总里以满分混进均值 (铁律 5 禁 fail-open 的同源要求)。
        """
        assert tsc([])["tsc"] == 0.0              # 挡住"空输入报 1.0": 满分混进均值的入口

    def test_pac_normalized_equal_forms(self):
        """正: 不同写法 (时角/角分/大小写表名) 归一同形 → pac_call=1.0。

        三条异写 + 两条规范写混在一起: 正是这种"语义相同、写法不同"的
        组合最容易让归一退化成一个恒等函数而看不出来。
        """
        runs = [[{"ra": "12h30m", "dec": -20.4, "radius_arcsec": "5'", "catalog": "ps1"}]] * 3  # 三条异写
        runs += [[{"ra": 187.5, "dec": -20.4, "radius_arcsec": 300.0, "catalog": "PS1"}]] * 2  # 两条规范写占多数
        assert pac(runs)["pac_call"] == 1.0        # 归一退化成恒等函数时必红

    def test_pac_radius_drift_caught(self):
        """反: 半径 300→600 → pac_call<1.0 且 unstable_fields 定位到 radius_arcsec。

        断两件事: 比值掉下来 + 归因指到具体字段。只断比值的话, "哪一项在
        抖"就丢了, 归因表会变成一堆无法定位的 0.8。
        """
        runs = [_call_run() for _ in range(4)] + [_call_run(radius_arcsec=600.0)]  # 漂移项是少数
        result = pac(runs)                                                               # 算完即断两件事: 比值掉下来只是抓到, 归因指到字段才是可定位
        assert result["pac_call"] < 1.0
        assert "radius_arcsec" in result["unstable_fields"]  # 归因要指到字段, 否则报告只剩一堆 0.8

    def test_pac_column_qualification_is_strict(self):
        """反: 裸列名 vs 全限定列名 → pac_call<1.0 (E6 口径, 文档 §5.2)。

        这条与 E1 的去前缀归一口径**相反**: 宽比对会把投影抖动洗掉, 而
        E6 要抓的恰恰是投影稳定性。
        """
        runs = [_call_run(columns=["scr_galah_rztf"]) for _ in range(4)]  # 四次同形基准
        runs += [_call_run(columns=["rztf"])]                            # 加一次裸列名
        assert pac(runs)["pac_call"] < 1.0  # 宽比对会把投影抖动洗掉, 而 E6 要抓的恰是它

    def test_pac_empty_runs(self):
        """反: 空运行集 → pac_call=0.0。"""
        assert pac([])["pac_call"] == 0.0            # 空集记 0.0: 与 tsc 空集同一 fail-closed 约定

    def test_rdc_consistent_runs(self):
        """正: 三级 (hash/行集/关键值) 全等 → rdc=1.0。

        三个值断成链式相等: 这样"哪一档没跟上"一眼能看出来, 而只断 rdc
        会把三档的口径问题一起糊过去。
        """
        rows = [{"data_hash": "sha256:" + "a" * 64, "row_keys": {"K1", "K2", "K3"},
                 "key_values": {"n": 3}} for _ in range(5)]  # 5 次同形: 三档都该判 1.0
        result = rdc(rows, lane="R1")
        assert result["l1"] == result["l2"] == result["l3"] == result["rdc"] == 1.0  # 链式相等: 哪档掉了一眼看出

    def test_rdc_row_dropped_caught(self):
        """反: 删一行 → L2 行集集合不等 (文档 §9 BF-4)。

        断 l2 与 rdc 两项: 在线主口径走 L2, 只断 rdc 就无法区分"主口径选错"
        与"集合比法失效"这两种完全不同的故障。
        """
        rows = [{"data_hash": "sha256:" + "a" * 64, "row_keys": {"K1", "K2", "K3"},
                 "key_values": {"n": 3}} for _ in range(4)]
        # 第五条同时换了 hash 与行集: 两档都该掉, 而"只掉一档"正是分页
        # 行序不稳那种服务端特性, 两者必须可分
        rows += [{"data_hash": "sha256:" + "b" * 64, "row_keys": {"K1", "K2"},
                  "key_values": {"n": 2}}]  # 第五条同时换 hash 与行集: 两档都该掉
        result = rdc(rows, lane="R1")
        assert result["l2"] < 1.0 and result["rdc"] < 1.0  # 只断 rdc 分不清"主口径选错"与"比法失效"

    def test_rdc_main_level_by_lane(self):
        """正: 主口径按 lane 选 — R3 回放走 L1 (hash), 在线走 L2 (集合)。

        断 level 字符串而不只是 rdc 值: level 是报告里解释"为什么这批数据
        看起来不可复现"的唯一依据, 值对了而 level 标错就误导了评审。
        """
        rows = [{"data_hash": "sha256:" + "a" * 64, "row_keys": {"K1"}, "key_values": {"n": 1}}] * 4
        rows += [{"data_hash": "sha256:" + "b" * 64, "row_keys": {"K1"}, "key_values": {"n": 1}}]  # hash 变而行集不变
        # 这组数据刻意做成"hash 变但行集不变": 只有 R3 会因此判不一致,
        # 在线两路不会 —— 正是分页行序不稳那个坑的反面
        assert rdc(rows, lane="R3")["level"] == "L1"   # R3 回放走 L1: hash 变即不一致
        assert rdc(rows, lane="R1")["level"] == "L2"   # R1 在线走 L2: 行集不变即一致
        assert rdc([], lane="R3")["rdc"] == 0.0

    def test_fcc_identical_cards(self):
        """正: N 张结论卡全同 → fcc=1.0 且 mode_card 为归一后的众数卡。

        断 mode_card 的 kind: fcc=1.0 也可能来自"参照取错"——比如把空卡
        当成了众数, 那样全等的假象会掩盖真正的问题。
        """
        result = fcc([{"card": dict(_BASE_CARD)} for _ in range(5)])  # 5 张全同卡
        assert result["fcc"] == 1.0
        assert result["mode_card"]["kind"] == "rowset"  # 断参照本身: 把空卡当众数也会得 fcc=1.0

    def test_fcc_kind_swap_is_caught(self):
        """反: ERROR→EMPTY 互换 (kind 翻转) 必须被抓并定位到 kind 子项 (文档 §9 BF-5)。

        断 sub_item_failures 里含 kind: 只断 fcc<1.0 的话, "抓到了但归错
        了子项"这种失真诊断不会被发现, 归因表就指错了方向。
        """
        runs = [{"card": dict(_BASE_CARD, kind="refusal")} for _ in range(4)]
        runs += [{"card": dict(_BASE_CARD)}]
        result = fcc(runs)                                                            # 先造众数卡再插一张异类: 顺序是「先同后异」, 反过来会被众数吸收掉
        assert result["fcc"] < 1.0 and "kind" in result["sub_item_failures"]  # 只断 fcc<1.0 会放过"抓到了但归错子项"

    def test_fcc_number_drift_is_caught(self):
        """反: 结论数值改一位 (12→13) → 抓并定位 key_numbers (文档 §9 BF-6)。

        12→13 是 8% 的偏差, 远超 1e-6 容差却远小于肉眼可辨的范围 ——
        这种"数字看着差不多"的情况正是结论卡最常见的真实缺陷。
        """
        runs = [{"card": dict(_BASE_CARD)} for _ in range(4)]
        runs += [{"card": dict(_BASE_CARD, key_numbers=[{"field": "row_count", "value": 13}])}]  # 12->13: 超容差又肉眼难辨
        result = fcc(runs)                                                           # 只改一个数字: 8% 偏差远超容差又肉眼难辨, 正是结论卡最常见的缺陷
        assert result["fcc"] < 1.0 and "key_numbers" in result["sub_item_failures"]  # 数值子项被 kind 掩盖时要红

    def test_fcc_sqlid_volatility_is_normalized_away(self):
        """正: 实体里的 sqlid 易失 → 归一剥离后仍判一致 (文档 §5.2 地雷)。

        去掉它等于让 FCC 无意义地归零: 每次运行的 sqlid 都不同, 不剥离
        就没有任何任务能拿到 fcc=1.0, 指标会整体失真到没法用。
        """
        stable = dict(_BASE_CARD, key_entities=["scr_galah", "best://scr_galah/sqlid/s9001"])
        other = dict(_BASE_CARD, key_entities=["scr_galah", "best://scr_galah/sqlid/sOTHER"])
        assert fcc([{"card": stable}] * 3 + [{"card": other}] * 2)["fcc"] == 1.0  # 不剥 sqlid 则没有任务能拿满分

    def test_fcc_empty_runs(self):
        """反: 空运行集 → fcc=0.0 且 mode_card=None。"""
        result = fcc([])                                                                   # 空集也要算: 空运行集是真实输入形态, 不是可以跳过的边界
        # 断 mode_card 是 None: 报告要靠它区分"没参照"与"参照是个空卡"
        assert result["fcc"] == 0.0 and result["mode_card"] is None  # mode_card=None 才能区分"没参照"与"空卡"


# ── 6. attribution: 七行决策表 ───────────────────────────────────────────

# 决策表现读表: (用例说明, 运行构造, 期望归因码, 基线 data_hash) — 文档 §4.3 七行
_SOFT_404 = [{"ok": False, "error_code": "E_SOFT_404", "data_hash": None}]  # 软 404 不报错, 靠 error_code 表达
_UNLISTED = [{"ok": False, "error_code": "E_WEIRD", "data_hash": None}]     # 未登记码不得误判成后端故障
_ATTR_CASES = [                                                                         # 决策表逐行写死: 期望码与文档表逐行对照, 改内容会红改顺序不会
    ("稳定无异常", lambda: _attr_run(), "OK", None),
    ("工具名不在七原子工具内", lambda: _attr_run(tool_calls=[{"tool": "guess_table", "args": {}}]),
     "ERR_ROUTE", None),
    ("半径越界18000角秒", lambda: _attr_run(tool_calls=[_cone(radius_arcsec=30000.0)]),
     "ERR_PARAM_SCHEMA", None),
    ("RA越界360度", lambda: _attr_run(tool_calls=[_cone(ra=400.0)]), "ERR_PARAM_SCHEMA", None),
    ("Dec越界-90度", lambda: _attr_run(tool_calls=[_cone(dec=-95.0)]), "ERR_PARAM_SCHEMA", None),
    ("半径类型错", lambda: _attr_run(tool_calls=[_cone(radius_arcsec="abc")]),
     "ERR_PARAM_SCHEMA", None),
    ("半径与众数不符", lambda: _attr_run(tool_calls=[_cone(radius_arcsec=600.0)]),
     "ERR_PARAM_UNSTABLE", None),
    ("表选错与众数不符", lambda: _attr_run(tool_calls=[_cone(catalog="xpsp")]),
     "ERR_PARAM_UNSTABLE", None),
    ("调用条数与众数不符", lambda: _attr_run(tool_calls=[_cone(), {"tool": "count", "args": {}}]),
     "ERR_PARAM_UNSTABLE", None),
    ("多传一个参数", lambda: _attr_run(tool_calls=[_cone(band="g")]), "ERR_PARAM_UNSTABLE", None),
    ("服务端软404", lambda: _attr_run(results=_SOFT_404), "ERR_BACKEND", None),
    ("未登记错误码不误判后端", lambda: _attr_run(results=_UNLISTED), "OK", None),
    ("data_hash与基线不符", lambda: _attr_run(), "ERR_BACKEND_DRIFT", "sha256:" + "a" * 64),
    ("data_hash与基线一致", lambda: _attr_run(results=[{"ok": True, "error_code": None,
                                                       "data_hash": _BASE_HASH}]),
     "OK", _BASE_HASH),
    ("原样重试", lambda: _attr_run(retries=[{"strategy_changed": False}]),
     "ERR_RETRY_INEFFECTIVE", None),
    ("换策略重试", lambda: _attr_run(retries=[{"strategy_changed": True}]), "OK", None),
    ("结论卡kind漂移", lambda: _attr_run(card={"kind": "refusal"}), "ERR_CONCLUSION_UNSTABLE",
     None),
    ("结论卡与众数一致", lambda: _attr_run(card=dict(_BASE_CARD)), "OK", None),
]


class TestAttribution:
    """分层归因决策表: 七行码机读正确 + 顺序铁律 (第一条命中即用)。"""

    @pytest.mark.parametrize(("case", "factory", "expected", "baseline"), _ATTR_CASES,
                             ids=[case[0] for case in _ATTR_CASES])                   # 用中文行名做 id: 失败输出里能直接看出是哪一行判错, 不必数下标
    def test_decision_table_first_hit_wins(self, case, factory, expected, baseline):
        """决策表每一行的归因码必须与文档 §4.3 表一致 (含 OK 兜底)。

        18 行参数化共用一条用例体: 每一行只构造一种现场, 期望码逐行对照
        文档写死。七行规则改内容时这条会红, 改**顺序**时它不会 —— 顺序由
        下面四条专门的用例守。
        """
        assert attribute_run(factory(), _MODE_CALLS, _MODE_CARD, baseline) == expected  # 18 行共用一条体: 改内容红, 改顺序不红

    def test_backend_error_with_param_drift_is_param_unstable(self):
        """顺序铁律: 后端错误 + 参数漂移 → 必须判 ERR_PARAM_UNSTABLE (不甩锅后端)。

        参数问题在前、后端错误在后: 顺序一换, 一次参数写错就会被报成
        "服务端坏了", 归因方向整个反过来, 修的人会去查错的地方。
        """
        run = _attr_run(tool_calls=[_cone(radius_arcsec=600.0)],                            # 参数漂移与后端错误同时给: 只给其一时顺序铁律根本走不到
                        results=[{"ok": False, "error_code": "E_BACKEND", "data_hash": None}])  # 参数在前, 后端在后
        assert attribute_run(run, _MODE_CALLS, _MODE_CARD) == "ERR_PARAM_UNSTABLE"  # 顺序一换, 归因方向整个反过来

    def test_drift_with_ineffective_retry_is_param_unstable(self):
        """顺序铁律: 数据漂移 + 无效重试 → 参数层先命中 (漂移判定以参数一致为前提)。"""
        # 参数一漂, "数据漂移"这个结论就不成立了 —— 没有稳定参数就没有
        # 稳定基线可比, 所以参数层必须排在前面
        run = _attr_run(tool_calls=[_cone(catalog="xpsp")], retries=[{"strategy_changed": False}])
        assert attribute_run(run, _MODE_CALLS, _MODE_CARD) == "ERR_PARAM_UNSTABLE"

    def test_retry_rule_precedes_conclusion_rule(self):
        """顺序铁律: 第 6 条先于第 7 条 — 无效重试 + 结论漂移 → ERR_RETRY_INEFFECTIVE。

        原样重试是因, 结论漂移是果: 先报结论漂移会把修的方向指到下游,
        而重试策略才是真正要改的地方。
        """
        run = _attr_run(card={"kind": "refusal"}, retries=[{"strategy_changed": False}])  # 因: 原样重试; 果: 结论漂移
        assert attribute_run(run, _MODE_CALLS, _MODE_CARD) == "ERR_RETRY_INEFFECTIVE"  # 先报结论漂移会把修的方向指到下游

    def test_no_mode_card_skips_conclusion_rule(self):
        """无反: 无众数卡 (mode_card=None) 时第 7 条不判 — 不凭空造结论漂移。

        没有参照就没有"漂移"可言: 硬判等于每次单次运行都被记成结论不稳,
        指标会从第一天起就全红, 于是没人再看它。
        """
        assert attribute_run(_attr_run(card={"kind": "whatever"}), _MODE_CALLS, None) == "OK"

    def test_column_order_is_not_instability(self):
        """columns 顺序不敏感 (文档 §5.2): 乱序列与升序列归一同形 → 不判参数不稳定。

        这条是"不该报的别报"的正例: 归一只做排序而保留重复列, 顺序抖动
        不会进来, 真正的漏列与错列仍会被抓住。
        """
        shuffled = _attr_run(tool_calls=[_cone(columns=["dec", "ra"])])
        assert attribute_run(shuffled, _MODE_CALLS, _MODE_CARD) == "OK"

    def test_lane_distribution_counts_each_run(self):
        """一批运行的归因分布必须逐条计数 (报告 §12 第 7 个数)。

        三条断法合起来才够: 两个有值 + 一个显式 0。断 0 是为了抓住
        "未命中的码被算成了 None 而在 JSON 里消失"这类问题。
        """
        drifted = _attr_run(tool_calls=[_cone(catalog="xpsp")])
        distribution = attribute_lane([_attr_run(), _attr_run(), drifted], _MODE_CALLS, _MODE_CARD)  # 逐条计数, 非按类型去重
        assert distribution["OK"] == 2
        assert distribution["ERR_PARAM_UNSTABLE"] == 1
        # 断 0 而不是"不在字典里": 报告要能看到"这类问题一次都没出现"
        assert distribution["ERR_ROUTE"] == 0

    def test_attribution_tables_match_schema_json(self):
        """正: 七原子工具表与归因码表必须与 trace.schema.json 的登记面一致。

        与 foundation 件里的 schema 锁同源: 那条守 trace 的事件面, 这条
        守归因面, 两边各改各的会让报告的机读校验和实际判定脱节。
        """
        schema = json.loads((REPRO_DIR / "trace.schema.json").read_text(encoding="utf-8"))  # 读点: 归因面须与 schema 同源
        tools = set(schema["payload_by_type"]["tool_call"]["properties"]["tool"]["enum"])
        # 滤掉 $ 开头的键: schema 里那是 JSON Schema 的关键字 (如 $schema),
        # 不是归因码, 不过滤会让等值判定恒不成立
        codes = {key for key in schema["attribution_codes"] if not key.startswith("$")}  # 剔关键字, 否则等值恒不成立
        assert set(SCHEMA_TOOLS) == tools       # 等值: 多一个少一个都算与 schema 脱节
        assert codes == set(ATTRIBUTION_CODES)  # 归因码表同样等值锁, 防双写漂移


# ── 7. efficiency: EF1..EF7 ──────────────────────────────────────────────

class TestEfficiency:
    """EF1..EF7: 理论最小请求数 / η 比值 / 两口径墙钟 / 冗余 / 重试 / 分页 / 零请求。"""

    @pytest.mark.parametrize(("tool", "expected"), [
        ("cone_search", 2), ("count", 1), ("fetch_page", 1), ("resolve_name", 1),
        ("crossmatch_batch", 2), ("list_catalogs", 0), ("describe_catalog", 0),
        ("unknown_tool", 1),
    ])
    def test_theoretical_min_requests(self, tool, expected):
        """理论最小请求数按工具表累加 (未知工具保守按 1 计 — 不低估代价)。

        八个期望值就是 EF1 的全部口径: cone_search 记 2 是因为两阶段协议
        要先 POST 建 sqlid; 两个元数据工具记 0 是 EF6 硬门槛的地基;
        未知工具按 1 计才不会让新增工具在 EF1 上白捡满分。
        """
        assert theoretical_min_requests([{"tool": tool, "args": {}}]) == expected  # 未知工具按 1 计, 新增工具不白捡满分

    def test_ef1_ratio_perfect_and_wasteful(self):
        """η: 恰好最小请求数 → 1.0; 翻倍请求 → 0.5 (按 run 求均值得 0.75)。

        断 per_run 再断均值: 只断 0.75 的话, "两次都算 0.75"这种分摊错误
        也会通过, 而效率归因恰恰需要知道是哪一次运行浪费的。
        """
        calls = [{"tool": "cone_search", "args": {}}]
        result = ef1_request_ratio([{"tool_calls": calls, "cost": {"http_requests": 2}},
                                    {"tool_calls": calls, "cost": {"http_requests": 4}}])
        assert result["per_run"] == [1.0, 0.5]       # 逐 run 断: 只断均值会让"分摊错误"也通过
        assert result["ef1"] == pytest.approx(0.75)  # 均值 = (1.0+0.5)/2, 两个口径都要能算

    def test_ef1_metadata_zero_request_is_perfect(self):
        """元数据类零请求 = 完美效率 (不是除零, 也不是 0 分)。

        这条与下一条构成对照: 同样是 http_requests=0, 分母是 0 还是 2
        决定了满分还是零分, 判据不能混。
        """
        run = {"tool_calls": [{"tool": "list_catalogs", "args": {}}], "cost": {"http_requests": 0}}  # 理论 0 实际 0
        assert ef1_request_ratio([run])["ef1"] == 1.0  # 分母为 0 记满分, 不记除零也不记 0 分

    def test_ef1_zero_requests_with_pending_work_is_zero(self):
        """有理论请求却零实际请求 → η=0 (不白送满分 — fail-closed)。

        一次请求都没发却声称完成了要访问数据的任务, 那是链路失败而不是
        高效; 报 1.0 等于把失败洗成了亮点。
        """
        run = {"tool_calls": [{"tool": "cone_search", "args": {}}], "cost": {"http_requests": 0}}
        assert ef1_request_ratio([run])["ef1"] == 0.0  # 一次没发却称完成: 是链路失败, 报 1.0 等于洗成亮点

    def test_ef2_wall_clock_two_scopes(self):
        """墙钟分含/不含 rate_limit 两口径 (默认 2.0s/请求会把墙钟拉长数倍)。

        断大小关系而不只是具体值: 7.0 - 1.0 = 6.0 恰好等于 2×(2+1) 的部分,
        关系断言能在容差放宽时仍守住"两口径必须不同"这个契约。
        """
        runs = [{"tool_calls": [], "cost": {"http_requests": 2, "elapsed_s": 5.0}},
                {"tool_calls": [], "cost": {"http_requests": 4, "elapsed_s": 9.0}}]
        result = ef2_wall_clock(runs, rate_limit_seconds=2.0)   # 扣掉 rate_limit×请求数才是真实服务耗时
        assert result["with_rate_limit_p50"] == pytest.approx(7.0)      # p50 而非均值: 单条离群不污染口径
        assert result["without_rate_limit_p50"] == pytest.approx(1.0)
        # 只报一个口径的话, 读者无法判断耗时到底是服务慢还是被节流
        assert result["with_rate_limit_p50"] > result["without_rate_limit_p50"]

    def test_ef3_redundant_calls(self):
        """冗余调用: 同工具同参数重复记 1/3; 无重复 → 0。

        分母 3 里有一次 count: 冗余率的分母是总调用数, 只拿数据类调用当
        分母会把重复查询的占比虚高一倍以上。
        """
        duplicate = {"tool_calls": [{"tool": "cone_search", "args": {"ra": 1.0}},
                                    {"tool": "cone_search", "args": {"ra": 1.0}},
                                    {"tool": "count", "args": {}}]}
        assert ef3_redundant_calls([duplicate])["ef3"] == pytest.approx(1 / 3)  # 分母含 count, 否则重复率虚高一倍
        assert ef3_redundant_calls([{"tool_calls": [{"tool": "count", "args": {}}]}])["ef3"] == 0.0

    def test_ef4_ineffective_retries(self):
        """无效重试: strategy_changed=false 的原样重试记 1/2; 无重试 → 0。

        混一次换策略的重试是故意的: 分母 2 而分子 1, 断 0.5 才能确认
        "只数 strategy_changed 为 False 的那些"而没把全部重试都算进来。
        """
        run = {"tool_calls": [], "retries": [{"strategy_changed": False},
                                             {"strategy_changed": True}]}
        assert ef4_ineffective_retries([run])["ef4"] == 0.5  # 只数 strategy_changed=False 的那些
        assert ef4_ineffective_retries([{"tool_calls": []}])["ef4"] == 0.0

    def test_ef5_paging_exact_and_over(self):
        """分页效率: 恰好补齐末页 → 0 次过量; 多翻 3 页 → 记 3 (过量翻页=0 次门槛)。

        7 行 / 每页 5 → 理论 2 页, 首页已含在 cone_search 里, 所以只该
        再 fetch 一次。翻成 4 次就多出 3 页 —— 断 3 而非"大于 0"才能确认
        累计的是超出量, 报告要拿它折算成可省的请求数。
        """
        exact = {"tool_calls": [{"tool": "cone_search", "args": {}},
                                {"tool": "fetch_page", "args": {"page": 2}}],
                 "cost": {"rows_returned": 7}}
        assert ef5_paging([exact], page_size=5)["ef5_over_paging"] == 0   # 恰好补齐末页: 过量 0 次
        over = {"tool_calls": [{"tool": "cone_search", "args": {}}] +
                               [{"tool": "fetch_page", "args": {"page": i}} for i in (2, 3, 4, 5)],
                "cost": {"rows_returned": 7}}
        assert ef5_paging([over], page_size=5)["ef5_over_paging"] == 3   # 断精确 3 而非 >0: 报告要拿它折算可省请求数

    def test_ef6_zero_request_completion(self):
        """零请求完成率: 元数据类任务混入一次带请求的 → 0.5 (硬门槛 = 100%)。

        第二个断法守的是另一侧: 一个**非**元数据任务 (count) 混进来不会
        进入分子分母, 所以仍是 1.0。分子分母只在元数据子集上算。
        """
        zero = {"tool_calls": [{"tool": "list_catalogs", "args": {}}], "cost": {"http_requests": 0}}
        wired = {"tool_calls": [{"tool": "describe_catalog", "args": {}}], "cost": {"http_requests": 1}}
        result = ef6_zero_request_completion([zero, wired])            # 两个元数据 run 各进一次分母
        assert result["ef6"] == 0.5 and result["metadata_runs"] == 2    # 一半零请求, 且分母规模要看得见
        # EF6 承重断言: 整批没有元数据类任务时必须记 **None** 而不是 1.0。
        # 1.0 读作"全部零请求达标"的满分, 而这里一条都没跑 —— "没测过"被伪装成
        # "测过且全对", 门禁看到 1.0 就放行 (fail-open)。None 与 0.0 必须分开:
        # 0.0 是"跑了且全违规"(该红), None 是"没跑"(缺证据)。
        assert ef6_zero_request_completion(
            [{"tool_calls": [{"tool": "count", "args": {}}]}])["ef6"] is None

    def test_ef7_tokens_external_null_not_estimated(self):
        """EF7 由外部 harness 提供; 缺失记 null (禁止估算填数)。

        断逐元素列表而不是只断长度: 长度对但第二个元素被填成 0 的实现
        也能过, 而那正是"估了个数"被误当真值引用后的样子。
        """
        result = ef7_tokens([{"usage": {"tokens_in": 10, "tokens_out": 2}}, {}])
        assert result["ef7_tokens_in"] == [10, None]   # 缺失记 None: 长度对但被填 0 的实现也要被挡住
        assert result["ef7_tokens_out"] == [2, None]
        # note 是给报告看的口径声明, 删了它下游就可能把 null 当 0 求和
        assert "禁止估算" in result["note"]

    def test_summarize_covers_ef1_to_ef7(self):
        """汇总必须覆盖 EF1..EF7 七项 (报告 §12 第 8 个数的一次性来源)。

        断七个代表键: 少一项报告就缺一列, 而"缺列"与"该项为零"在渲染
        出来之前是看不出来的。
        """
        summary = summarize_efficiency([{"tool_calls": [{"tool": "cone_search", "args": {}}],
                                         "cost": {"http_requests": 2, "elapsed_s": 1.0}}],
                                       rate_limit_seconds=0.0)  # 单 run 汇总: 七个键一次产出
        for key in ("ef1", "with_rate_limit_p50", "ef3", "ef4", "ef5_over_paging", "ef6",
                    "ef7_tokens_in"):
            assert key in summary                                                          # 逐键断存在: 七个键一次产出, 少一个键下游汇总就会取不到


# ── 8. usability: U1..U7 ─────────────────────────────────────────────────

class TestUsability:
    """U1..U6 客观机读判据 + U7 主观分不进分/不进门禁。"""

    def test_u1_first_usable(self):
        """正: 无澄清且 success → 1.0; 反: 有澄清或失败 → 记 0。

        成功但问过一轮的不算首次可用: U1 量的是首轮交互成本, 不是最终
        成功率, 两者的分母一样但含义完全不同。
        """
        good = {"outcome": "success", "events": []}
        assert u1_first_usable([good])["u1"] == 1.0   # U1 量首轮交互成本, 不是最终成功率
        clarified = {"outcome": "success", "events": [{"type": "clarification", "payload": {}}]}
        assert u1_first_usable([good, clarified])["u1"] == 0.5
        assert u1_first_usable([{"outcome": "fail", "events": []}])["u1"] == 0.0

    def test_u2_error_operability_three_elements(self):
        """错误可操作性三要素 (稳定错误码+人话原因+下一步) 缺一即不全 (硬门槛)。

        三条断法覆盖三个侧面: 齐全=1.0、混入缺项=0.5、以及"没有失败样本
        时按满分但 failed_runs=0"。最后一条最容易改坏: 把"没失败"当成
        "不可操作"会让硬门槛在任何健康批次上直接失败。
        """
        complete = {"outcome": "fail",
                    "answer_text": "E_SOFT_404: 查询失败, 因为会话过期; 请稍后重试或换 catalog"}
        # partial 缺"下一步动作": 说了是什么错、为什么错, 却没告诉用户
        # 怎么办, 用户依然接不下去
        partial = {"outcome": "fail", "answer_text": "E_SOFT_404: 因为服务端错误"}
        assert u2_error_operability([complete])["u2"] == 1.0
        assert u2_error_operability([complete, partial])["u2"] == 0.5  # 缺一项不能等于完全不可操作
        assert u2_error_operability([{"outcome": "success"}])["u2"] == 1.0

    def test_u2_stable_codes_match_schema(self):
        """稳定错误码表必须与 trace.schema.json 的 status.error_code 登记面一致。

        代码侧多认或少认一个码, U2 的判定就会与 trace 记下来的事实脱节;
        等值比较加上剔 None 才能把"schema 允许为空"这件事排除掉。
        """
        schema = json.loads((REPRO_DIR / "trace.schema.json").read_text(encoding="utf-8"))
        declared = set(schema["payload_by_type"]["tool_result"]["properties"]["status"]
                       ["properties"]["error_code"]["enum"]) - {None}
        assert set(STABLE_ERROR_CODES) == declared   # 等值锁: 多认少认一个码, U2 就与 trace 脱节

    def test_u3_clarify_quality(self):
        """正: 澄清点明缺失维度 + 给可选项 → 1.0; 反: 空洞澄清记 0。

        vague 同时缺维度与选项, 两个条件任意一个不满足都该记 0 ——
        "能具体点吗"这种反问对用户毫无帮助。
        """
        good = {"events": [{"type": "clarification",
                            "payload": {"missing_dims": ["radius"], "options": ["60", "300"]}}]}
        vague = {"events": [{"type": "clarification",
                             "payload": {"missing_dims": [], "options": []}}]}
        assert u3_clarify_quality([good])["u3"] == 1.0
        assert u3_clarify_quality([vague])["u3"] == 0.0  # "能具体点吗"这种空洞反问记 0
        # 没有澄清回合不是澄清质量差, 而是这项没被触发; 按满分记并给
        # clarified_runs=0, 报告必须照实写出这个 0
        assert u3_clarify_quality([{"events": []}])["u3"] == 1.0  # 没澄清回合是没被触发, 不是质量差

    def test_u4_self_explaining(self):
        """答案自解释四子项 (单位/版本/uri/trust) 按齐全率计: 3/4 → 0.75; 裸数字 → 0。

        分母是 4 不是 1: 合成一个布尔量就永远说不清缺了哪一项, 而报告要
        做的恰恰是告诉读者"这次缺的是 trust 声明"。
        """
        full = {"outcome": "success",
                "answer_text": "共 12 行, 半径 60 角秒; 快照 replay-fixtures",
                "events": [{"type": "final_answer",
                            "payload": {"conclusion_card": {"key_entities": ["best://ps1/cone",
                                                                            "sha256:abc"]}}}]}
        # 3/4 而非 1.0: 刻意没写 trust, 断的就是"缺一项时也能算出部分分"
        assert u4_self_explaining([full])["u4"] == pytest.approx(0.75)  # 分母是 4: 合成布尔量就说不清缺哪项
        assert u4_self_explaining([{"outcome": "success", "answer_text": "12", "events": []}])["u4"] == 0.0

    def test_u5_step_ratio(self):
        """步数比: 有真实比值支撑时给数, 量不出来时给 None (反例: 真空满分)。

        分母是工具**步数**而不是 EF1 的请求数 (D-8): 两阶段查询的
        cone_search 花 2 次请求却只算 1 步, 混用两个口径会让同一批 run 在
        效率表和可用性表里给出互相矛盾的结论。

        2026-10-07 改口径 (审计 D3 / AK1-P0-b): 原断言是
        ``list_catalogs`` 单跑 ``== 1.0``, 也就是把「理论步数表认不出这个工具」
        钉成了契约 —— 那正是被审计点名的真空满分: 测量失效被读成最好的用户体验。
        现在它必须显式给 ``None`` 并报告 ``measured_runs=0``, 由上层判不可用。
        """
        # 反例: 工具名不在 theoretical_min_steps 的四个名字里 -> 量不出来, 不得记满分
        unknown_only = [{"tool_calls": [{"tool": "list_catalogs", "args": {}}]}]
        result = u5_step_ratio(unknown_only)
        assert result["u5"] is None, "工具表认不出输入时必须显式标记不可用, 不得回落到最优值"
        assert result["measured_runs"] == 0, "不可用时必须报出参与判定的 run 数, 否则看不出是量还是没量"
        assert result["per_run"] == [], "per_run 为空正是「量不出来」的信号, 必须一并给出"
        # 正常 run 仍给出真实比值 (回归: 别把真能算的情形也一起判死)
        normal = [{"tool_calls": [{"tool": "cone_search", "args": {}}]}]
        assert u5_step_ratio(normal)["u5"] == pytest.approx(1.0)
        heavy = {"tool_calls": [{"tool": "list_catalogs", "args": {}},
                                {"tool": "describe_catalog", "args": {}},
                                {"tool": "cone_search", "args": {}},
                                {"tool": "count", "args": {}}]}
        # 断越阈而不是精确值: 阈值 1.3 是硬门槛, 取最差值而非均值, 一次
        # 绕远路就足以让整批不可用
        assert u5_step_ratio([heavy])["u5"] > 1.3    # 断越阈不取均值: 一次绕远路就够判不合格

    def test_u6_honest_degradation(self):
        """诚实降级: 显式标注 not_computable/未配置 记 1; 编造记 0 (硬门槛 = 100%)。"""
        honest = {"degraded": True, "answer_text": "无法计算: 未配置波段映射"}
        fake = {"degraded": True, "answer_text": "大概是 5 颗星"}
        assert u6_honest_degradation([honest])["u6"] == 1.0
        assert u6_honest_degradation([honest, fake])["u6"] == 0.5
        # degraded=False 的运行不进分母: 正常完成的答案里本来就不该有降级
        # 标记, 混进来会让 U6 退化成"正常完成率"
        assert u6_honest_degradation([{"degraded": False}])["u6"] == 1.0  # 不进分母, 否则退化成"正常完成率"

    def test_u7_without_raters_returns_none(self):
        """U7 无评阅人 → None + 效力不足注记 (不得用于门禁, 文档 §7.2)。

        断 None 而不是 0.0: 0 分会被下游当成"评阅人打了最低分", 而真相
        是根本没人评 (R0 路无评阅人)。
        """
        result = u7_cognitive_load([])                                                      # 空评分表: R0 路没有评阅人, 这是真实输入而不是异常
        assert result["u7"] is None and result["n_raters"] == 0   # 断 None 不断 0.0: 0 会被当成"打了最低分"
        assert "效力不足" in result["note"]

    def test_u7_not_in_gate(self):
        """R0 无评阅人: 汇总里 u7=None (主观分不进分 — 文档 §8.1)。

        守的是"汇总不会把 None 折成 0": 一旦折成 0, 报告里的可用性总分
        就会因为一条本来就不该计分的主观项而被拉低。
        """
        summary = summarize_usability([{"outcome": "success", "events": [], "answer_text": ""}])
        assert summary["u7"] is None   # 折成 0 会因一条本不该计分的主观项拉低可用性总分


# ── 10. broken: 反证夹具 ─────────────────────────────────────────────────

class TestBrokenSelftest:
    """12 条已知扰动 (BF 一致性 6 类 + TI trace 完整性 6 类) 必须全部 detected。"""

    def test_metascore_is_one(self):
        """metascore 必须 = 1.00 且 pass (漏任一 → 判定器失效 → E6 FAIL)。

        断精确的 1.0 而不是 >0.9: 反证夹具的价值全在"一条都不能漏",
        漏一条就意味着某个判定器已经悄悄失效了。
        """
        result = run_broken_selftest()                                           # 自证结果: metascore 精确 1.0, 少一条即意味着某个判定器已失效
        assert result["metascore"] == 1.0   # 断精确 1.00 而非 >0.9: 漏一条即判定器失效
        assert result["pass"] is True

    def test_all_fixtures_detected(self):
        """逐条报告 detected (BF 组对应文档 §9 表; TI 组对应 trace 完整性扰动)。

        先断集合齐备再断逐条 detected: 少一个夹具时, 遍历结果的断言会
        静默地什么都不查而通过 —— 那正是"把难那条删掉"能骗过 CI 的原因。
        """
        result = run_broken_selftest()                                                    # 先拿整份结果再断集合: 少一个夹具时遍历断言会静默什么都不查
        required = {"BF-1", "BF-2", "BF-3", "BF-4", "BF-5", "BF-6",   # 12 个 id 写死, 少一个要立刻可见
                    "TI-1_event_missing", "TI-2_fingerprint_mismatch", "TI-3_rerun_inconsistent",
                    "TI-4_cost_falsified", "TI-5_timestamp_disorder", "TI-6_redaction_miss"}
        assert required <= set(result["results"]), required - set(result["results"])  # 挡住"把难那条删掉"
        for fixture_id, spec in result["results"].items():
            assert spec["detected"] is True, fixture_id
            # expect_caught_by 指明该由哪个判定器负责: 留空的话, 夹具即使
            # "被抓了"也说不清是被谁抓的, 漏检就无从定位
            assert spec["expect_caught_by"]

    def test_bf_group_matches_rubric(self):
        """BF 组夹具必须与 rubric.yaml 的 selftest_fixtures 一致 (配置漂移即抓)。"""
        # 第三方: 任务集硬约束 (禁相对时间) 的文本断言来源
        import yaml

        rubric = yaml.safe_load((REPRO_DIR / "rubric.yaml").read_text(encoding="utf-8"))
        # 等值而非子集: 夹具表多出一条同样算漂移, 少一条则说明有判定器
        # 悄悄失去了反证
        declared = {item["id"] for item in rubric["selftest_fixtures"]}
        assert declared == set(FIXTURES)   # 等值: 少一条说明有判定器悄悄失去了反证
        # 门槛写死在 rubric 里: 改成 0.9 就能让一条漏检悄悄通过, 所以断它
        assert rubric["selftest_required_metascore"] == 1.0  # 断门槛本身: 改成 0.9 就能让漏检悄悄通过

    def test_trace_group_is_labelled(self):
        """TI 组夹具必须带 group=trace_integrity 标记 (与 BF 组可分账统计)。"""
        result = run_broken_selftest()                                           # 取 group 集合: TI 组与 BF 组要能分账统计, 混在一起就没法归因
        groups = {spec.get("group") for spec in result["results"].values()}
        # 断两个组都在: 少标一个 group, 报告里那批夹具就成了无主项,
        # 评审分不清"trace 有问题"还是"一致率有问题"
        assert "trace_integrity" in groups
        assert "consistency (doc §9)" in groups

    def test_tsc_order_sensitivity_fixture(self):
        """TSC 反证: 同集合反序必须判不一致 (序列口径自证)。

        这条是给 TSC 本身上的锁: 哪天有人把主口径改成集合比, 逐条用例
        未必立刻全红, 而这条会直接指出"顺序敏感性没了"。
        """
        assert tsc_order_sensitivity_check() is True   # 给 TSC 上锁: 主口径改成集合比时只有这条会红


# ── 11. R0 路: 地板线与任务集 ────────────────────────────────────────────

class TestR0LaneFloor:
    """R0 工具层固化回放: 四一致率必须全 1.0 (文档 §8.2 阻断项 3)。"""

    def test_lane_repeat_two_all_four_rates_one(self):
        """18 条预写序列 × 2 次: TSC/PAC/RDC/FCC 必须全 1.0 (代码与环境确定性)。

        这是整个 E6 最重的一条: R0 把模型/网络/服务端/时间全冻住, 所以四
        率有任何一项不为 1.0, 就只剩代码这一种可能 —— 立即阻断。
        """
        lane = run_lane(repeat=2)   # 18 条预写序列各跑 2 次; 全程 ReplayTransport, 零真实请求
        coverage = lane["coverage"]
        # 18/32 的覆盖率要连 note 一起断: 冒充 100% 比只有 18 条更糟,
        # 因为那会让评审以为剩下 14 条也被验过了
        assert coverage["covered"] == 18 and coverage["total"] == 32   # 断分子与分母, 不只看比例
        assert coverage["uncovered"] == 14 and coverage["note"]       # 未覆盖数与说明都要写进报告
        for task_id, runs in lane["runs"].items():
            # 四个集合各从 runs 投影出来: 一致率是四个不同层面的指标,
            # 合成一个就会掩盖"只有某一项不稳"
            calls = [[c["tool"] for c in r["tool_calls"]] for r in runs]  # TSC 口径: 只投影工具名序列
            args = [[c["args"] for c in r["tool_calls"]] for r in runs]
            data = [{"data_hash": r["data_hash"], "row_keys": r["row_keys"],
                     "key_values": {"n": r["cost"]["rows_returned"]}} for r in runs]
            cards = [{"card": r["card"]} for r in runs]
            # 每个断言都带 task_id 消息: 18×4 个断点里红一个时, 不知道是
            # 哪条任务就只能靠二分重跑
            assert tsc(calls)["tsc"] == 1.0, task_id   # 任一非 1.0 就只剩代码这一种可能, 立即阻断
            assert pac(args)["pac_call"] == 1.0, task_id
            # lane 传 R0 而不是默认 R1: R0 是回放, 该走 L1 的严格档
            assert rdc(data, lane="R0")["l2"] == 1.0, task_id   # R0 是回放, 该走严格档而非在线档
            assert fcc(cards)["fcc"] == 1.0, task_id

    def test_metadata_tasks_make_zero_requests(self):
        """REPRO-01/32 元数据任务必须零 HTTP 请求 (EF6 地板, 文档 §3.1)。"""
        lane = run_lane(repeat=1)                                                        # 实跑一次即可: 这条要验的是零请求这条硬门槛, 不需要多次重复
        # 断到 0 而不是"很少": 元数据走 wire 是 EF6 的硬门槛, 一次往返
        # 就足以判不合格, 没有"少量可接受"这回事
        for task_id in ("REPRO-01", "REPRO-32"):
            assert lane["runs"][task_id][0]["cost"]["http_requests"] == 0, task_id  # 断到 0 而非"很少": 一次往返即不合格

    def test_reject_path_is_fail_not_success(self):
        """REPRO-31 越界半径 (20000″>18000″) → outcome=fail (拒绝路径可复现)。"""
        lane = run_lane(repeat=1, task_ids=["REPRO-31"])
        run = lane["runs"]["REPRO-31"][0]
        # outcome 与 results[0].ok 两个断点: 只断 outcome 的话, "抛了异常
        # 才置 fail"那种实现仍能过, 而软 404 那类不抛的失败就漏了 (D-3)
        assert run["outcome"] == "fail"
        assert run["results"][0]["ok"] is False   # 再断 ok: 软 404 那类不抛异常的失败靠它兜住

    def test_single_run_deterministic(self):
        """同任务两次 run_once 的 data_hash 一致 (无隐藏随机源)。

        两次独立调用而不是复用上一次的 lane 结果: 复用会让两条用例共享
        同一个 transport, call_count 之类的累积状态会互相污染。
        """
        fixture, sequence = R0_SEQUENCES["REPRO-04"]
        first = run_once("REPRO-04", fixture, sequence)
        second = run_once("REPRO-04", fixture, sequence)
        # 断 data_hash 而不是整条记录: 记录里有 elapsed_s, 两次必然不同,
        # 拿它做等值断言会让这条永远红
        assert first["data_hash"] == second["data_hash"]  # 断 hash 不断整条记录: 记录含 elapsed_s

    def test_all_sequence_fixtures_exist(self):
        """预写序列引用的快照必须都在 fixtures/ 下 (缺快照即跑不了 — fail-closed)。"""
        for task_id, (fixture, _sequence) in R0_SEQUENCES.items():                       # 逐条带消息: 32 条里少一个夹具时, 没有消息就只能靠肉眼数
            assert (FIXTURES_DIR / fixture).is_dir(), f"{task_id} 缺快照 {fixture}"

    def test_task_set_complete_and_no_relative_time(self):
        """32 条任务齐套且显式声明无相对时间表述 (硬约束 — 发现即剔除)。

        断的是那句显式声明而不是"文本里没有'今天'" —— 后者靠黑名单永远
        抓不全, 前者是发布前逐题签字的口径。
        """
        tasks = sorted((REPRO_DIR / "tasks").glob("REPRO-*.yaml"))
        assert len(tasks) == 32                                                    # 断 32 而非 ≥32: 少一条说明有判定器悄悄失去了反证, 门禁必须精确
        for path in tasks:                                                            # 逐题读签字声明: 断的是那句显式声明, 不是靠黑名单扫「今天」这类词
            assert "relative_time_expression: false" in path.read_text(encoding="utf-8"), path.name  # 断签字声明而非黑名单

    def test_soft404_not_recorded_as_empty_rowset(self):
        """REPRO-30 软 404 不得被记成空 rowset (文档 §3.1: 严禁 ERROR 报成 EMPTY)。

        r0_lane 不得只在抛异常时置 fail: 抛异常之外的非成功结果 (结果 ok=False
        → outcome=fail + card.kind=refusal 带错误码) 同样要显式落账, 否则
        软 404 会被记成"成功但 0 行" —— 与 E2-M5/E4-M5 同一判据。
        """
        lane = run_lane(repeat=1, task_ids=["REPRO-30"])
        run = lane["runs"]["REPRO-30"][0]
        # 断 kind 不等于 rowset 而非断等于 refusal: 将来若合法地增加了第三
        # 种 kind, 这条不该被迫跟着改, 而 ERROR 被记成 rowset 必须红
        assert run["card"]["kind"] != "rowset"   # 断"不等于 rowset"而非"等于 refusal": 加第三种 kind 时不必跟着改
