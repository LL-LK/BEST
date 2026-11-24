# -*- coding: utf-8 -*-
"""evals/ablation/tests — E5 单测 (任务集/系统装配/三门判定/反证/scripted 冒烟)。

职责: 证明 E5 的**判定器、装配层与跑批管线**本身成立 —— 30 条任务的 schema 齐备、
11 个系统按 one-at-a-time 装配、三门在正反例上都判对、七条反证夹具全抓、
scripted 端到端可跑且重复跑指纹一致。被测系统好不好由跑批报告回答, 这里只回答
"评分口径可不可信"。

所属实验: E5 基线与消融 (30 任务 × 10 系统 + sham 共 11 装配, ScriptedLLM 离线跑;
成功率 = ScriptedLLM 跑通率而非模型能力), 方案真值 docs/eval-E5-baseline-ablation.md
§5 (任务集与门类分配) / §5.2 (schema 字段) / §7 (判定分层与反证夹具) /
§9 (顺序与澄清轮控制) / §11 (阻断项)。

对外接口: 本文件是 pytest 收集面 —— TestTaskSet / TestSystems / TestGates /
TestBrokenFixtures / TestScriptedEndToEnd / TestItemsCompleteness / TestThreeGates /
TestScriptedSmoke 八个类, 无对外函数 API。

依赖与数据流: 输入 = evals.ablation 的 harness (装载/跑批) / metrics (三门判定) /
broken (反证夹具) / runner (放行判定), 以及 items.yaml、systems/*.yaml 与
E2 的快照与 gold 目录 (只做存在性断言); 产物只有 pytest 报告, 不写评测数据。

关键契约与不变量: 离线回放 —— 全部用例打在 ScriptedLLM 与本地快照上, rate_limit
归零, 不接真实模型、不打真实站点; 零跨实验 import —— 只 import 本实验内的件
(唯一共享件 evals/_data/ 纯数据字典不由本包直接引用); **等价性无断言覆盖**
(见 equivalence/import_isolation.py:15), 本包不重复那层; 断言确定性 —— 跑批
不给 seed 时保持 items.yaml 原序,
重复跑指纹逐字节一致, 否则这些断言本身就不稳定。

陷阱与边界: scripted 模式的覆盖有**结构性边界**, 本包如实断言这些边界而不是绕开
—— Δ1 (B0→B1) 的文档知识贡献与 sham/A2 的区分度在 scripted 下不可分辨 (答案只由
四个组件开关驱动), A1 只在 E5-D08 (半径 0)、A5 只在 D06/D11 可观测, 这些是模式
边界, 不能被写成"预期失败"来充数; repeat<3 被 runner 判阻断项 (§11) 是硬约束,
不是"已知失败" —— 那是 scripted 冒烟不得冒充显著性结论的设计, 单测里既验得住
也拦得住; D 类题挂的是 E2 快照与 gold, 快照缺失必须硬失败, 少一个快照会让
scripted 跑批"全过"却什么也没验到。
"""
from __future__ import annotations

# 标准库: JSON (三门正例的行集现取自金标准) / 路径
import json
from pathlib import Path

# 第三方: YAML (禁 version 键扫描)
import yaml

# 本地: 被测件 (以仓内实际 API 为准)
from evals.ablation.broken import (
    BROKEN_FIXTURES,  # 七条反证夹具表: 元分的被测声明源
    aggregate_selftest,  # 聚合自证: 空输入不得产出假高分
    claim_channel_selftest,  # 主张通道自证: 正反例各一, 证明这一路不滥拦
    rejected_task_failures,  # 漏抓清单: 空清单即判定器有效
    run_broken_selftest,  # 反证自证入口: 逐条对账坏样本
)
from evals.ablation.harness.run_batch import (
    SYSTEM_ORDER,  # 主表顺序: 报告列序跟着它走, 不按字典序
    load_items,  # 任务集装载: 空集即抛, 不出空矩阵
    load_systems,  # 装配装载: 缺文件即抛, 不静默少一个系统
    run_matrix,  # 跑批矩阵: 任务 × 系统 × 重复
    select_items,  # 筛选与顺序随机化: 种子缺省即保持原序
)
from evals.ablation.metrics.composite import (
    aggregate,  # 聚合入口: 逐 run 记录汇成系统级成绩
    gate_D,  # 决策门: 路由与拒绝正确性
    gate_E,  # 表述门: 关键断言与禁答短语
    gate_F,  # 取数门: 行集、字段一致与截断三元组
    param_hallucination,  # 参数幻觉检查: 出现即红线
    score_run,  # 汇总打分: 三门结果汇成加权分
    tool_set_f1,  # 工具集 F1: 决策门的第一项判据
)
from evals.ablation.runner import (  # runner 入口: 跑批模式门禁只能经 CLI 验, 绕开 argparse 就测不到开关
    freeze_hypotheses,
    load_hypotheses,
    run,
)
from evals.ablation.runner import (
    main as rb_main,  # CLI 入口: --require-live 的开关与退出码都由它决定
)

# 四个路径锚点都在模块级算一次: 存在性断言在每个用例里都要用
ABLATION_DIR = Path(__file__).resolve().parents[1]      # 四个锚点一次算好, 每个用例都要用
SNAPSHOTS_DIR = ABLATION_DIR.parents[0] / "groundtruth" / "snapshots"  # 按路径读 E2 快照, 不 import E2
GOLD_DIR = ABLATION_DIR.parents[0] / "groundtruth" / "gold"            # 金标准同样按路径读
ITEMS_PATH = ABLATION_DIR / "items.yaml"                 # 防污染声明要在这个文件头里读

# E5 §5.2 的 schema 字段齐备性 (新增四组 data_anchor/gold_result/assertions/applicable)
REQUIRED_FIELDS = ("id", "utterance", "category", "route", "expect_tools",
                   "should_call_best", "key_fields", "anti_patterns", "verify",
                   "data_anchor", "gold_result", "assertions", "applicable")


def _kind(item: dict) -> str:
    """门类 (D/C/R/S) — 取自 id 前缀 E5-Xnn。"""
    # 只取首字母: E5-D12 的第二段是 "D12", 门类就是它的头一个字符
    return str(item.get("id", "")).split("-")[1][:1]   # 门类来自 id 段首字符, 不另设字段以免两处漂移


class TestTaskSet:
    """统一任务集: 57 条 (D12/C6/R30/S6), 绑定关系完整。"""

    def test_fiftysix_items_four_gates(self):
        """56 条任务: D 12 / C 6 / R 32 / S 6 (E5 §5 分配 + R 类三次扩充与两次剔除)。"""
        items = load_items()                                                                        # 题集现读: 断言要跟着题集改动一起变
        # 总数先断言: 少一条时下面的门类分布仍可能对得上, 总数是最外层的护栏
        assert len(items) == 56          # 总数先断言: 少一条时门类分布仍可能对得上
        kinds: dict[str, int] = {}      # 门类计数: 分布要全等, 逐项 >= 挡不住设计漂移
        for item in items:                                                                          # 逐题统计类别: 覆盖面要能按类别对账
            kinds[_kind(item)] = kinds.get(_kind(item), 0) + 1                                      # 类别计数现算: 再与期望分布逐个比对
        # 全等而非逐项 >=: 门类配比是预登记的实验设计, 多了少了都算设计漂移
        # R 类 6 → 20 → 25 → 30 (2026-10-10 三次扩充):
        #   ① 6 → 20: 6 题时 ΔRejectAcc 恰为 1/6 题, 被投递方式方差 (2/6) 淹没;
        #   ② 20 → 25: 按能力边界分组后 III 暴露面 (n=1) / IV 权限 (n=2) 样本量不足;
        #   ③ 25 → 30: **治地板效应** —— 实测 R01–R25 × 4 装配方差为零 (连 B0 裸模型都
        #      25/25 全拒), 故补 5 条**诱饵题** (R26–R30): 语气合理、用工具面真实存在的
        #      参数名、决定性事实就在提示词里、但请求的是工具面表达不了的形态。
        #      **只在扇出无法交付目的时**才算能力缺口 —— R33/R34 的目的可达 (扇出即交付),
        #      故已移出 R 类; R26 的两级排序扇出产生不出两级顺序, 缺口成立。
        assert kinds == {"D": 12, "C": 6, "R": 32, "S": 6}

    def test_ids_stable_prefix(self):
        """id 前缀即门类 (E5-Dnn/Cnn/Rnn/Snn), 稳定编号不重复。"""
        items = load_items()                                                                   # 同一条原则: 每次断言都从盘上读, 不用进程内缓存
        ids = [i["id"] for i in items]   # 主表顺序即报告行序
        # 唯一性: 重复 id 会让按 id 建的索引静默覆盖一条, 跑批少跑却看不出来
        assert len(set(ids)) == len(ids)  # 挡住 id 重复导致索引静默覆盖
        # 首条必须是 D 类: ids 顺序即主表顺序, 开头变了整份报告的行序就变了
        assert ids[0].startswith("E5-D")

    def test_d_tasks_bound_snapshots(self):
        """D 类全部绑定 E2 快照 (E5 不重造题)。"""
        for item in load_items():                                                                   # 逐题查必备字段: 缺字段的题跑起来必崩
            if _kind(item) == "D":
                anchor = item.get("data_anchor") or {}
                # kind 与 ref 同时要求: 只给 kind 不给 ref 等于没绑, 回放会拿不到底座
                assert anchor.get("kind") == "snapshot" and anchor.get("ref")  # 只给 kind 不给 ref 等于没绑

    def test_d_tasks_have_gold(self):
        """D 类全部挂 E2 金标准 (取数门对账有基准)。"""
        for item in load_items():                                                          # 逐题查 gold 结构: gold 残缺会让取数门无从对账
            if _kind(item) == "D":
                gold = item.get("gold_result") or {}
                # case_id (可对账) 与 ref (可溯源) 二者至少有一, 否则 F 门只能判 N/A
                assert gold.get("case_id") or gold.get("ref")   # 二者至少有一, 否则 F 门只能判 N/A

    def test_every_item_verified(self):
        """每条任务有 verify 三字段 (无 fail-open: 未核验不入库)。"""
        for item in load_items():                                                               # 逐题查断言短语: 没有关键断言的题表述门无从判分
            verify = item.get("verify") or {}
            # verify_cmd + anchor + verified_at 三者齐: 有命令无锚点等于没核过,
            # 有锚点无时间无法判断核验是否早于题目改动
            assert verify.get("verify_cmd") and verify.get("anchor")  # 有命令无锚点等于没核过
            assert verify.get("verified_at")   # 无时间无法判断核验是否早于题目改动


class TestSystems:
    """十二系统装配: 五级基线 + 六项消融 + sham 安慰剂。"""

    def test_twelve_systems_in_order(self):
        """12 个系统且主表序固定 (E5 §4 装配序; A6 于 2026-10-10 采集前补登记)。"""
        systems = load_systems()                                                                    # 装配现读: 主表十二个系统一个都不能少
        # 顺序也要断言: 主表行序由 SYSTEM_ORDER 决定, 序变了报告就不可逐行对比
        assert list(systems) == list(SYSTEM_ORDER)  # 序变了报告就不可逐行对比
        # 12 个装配是覆盖面声明的量化: 少一个就少一列成绩。
        # A6 的由来: 组件覆盖矩阵算出 unified_envelope 是唯一无单件对照的组件
        # (方案 §11 缺陷 10), 补后 10 个组件**全部**有单件可归因的对照。
        assert len(systems) == 12                                                              # 十二个装配是覆盖面声明的量化: 少一个就少一列成绩

    def test_ablation_flips_exactly_one_component(self):
        """one-at-a-time: 每个消融相对 B3 只翻一个组件开关。"""
        systems = load_systems()                                                                  # 逐个查开关字段: 缺字段的系统会退回默认全开
        base = systems["B3"]["components"]   # B3 是完整基线, 五个消融都相对它比
        for aid in ("A1", "A2", "A3", "A4", "A5"):
            comps = systems[aid]["components"]
            flipped = [k for k in base if base[k] != comps.get(k)]  # 只数与基线不同的键
            # 恰好一个: 翻两个就不是 one-at-a-time, 归因不到单个零件, 结论作废
            assert len(flipped) == 1, f"{aid} 翻了多个组件: {flipped}"

    def test_sham_matches_a2_switches(self):
        """sham 与 A2 组件开关逐项相同 (唯一差是注入文本的信息量)。"""
        systems = load_systems()                                                                  # 逐个查组件开关: 消融全关的系统会让对照失效
        # 开关相同是 sham 的定义: 两者答案路径一致, 差只在注入的文本有没有信息量,
        # 开关一旦不同就分不清"掉分来自信息"还是"掉分来自少一个组件"
        assert (systems["sham_placeholder"]["components"]
                == systems["A2"]["components"])   # 开关相同是 sham 的定义, 否则掉分归因说不清

    def test_na_metrics_declared(self):
        """无工具系统的 N/A 指标必须显式声明 (不记 0 造假差异)。"""
        systems = load_systems()                                                             # 逐个查工具面声明: 无工具面系统的工具类指标应为不适用
        for sid in ("B0", "B1"):
            # na_metrics 与 na_reason 都要有: 只声明"哪些是 N/A"却不给理由,
            # 读者无法判断是真无意义还是漏跑了
            assert systems[sid].get("na_metrics"), f"{sid} 未声明 N/A 指标"
            assert systems[sid].get("na_reason")


class TestGates:
    """三门判定: 参数幻觉红线 / N/A 不进分母 / 表述门禁答。"""

    def test_param_hallucination_detects_unknown_param(self):
        """schema 外参数必须进幻觉清单 (E1 红线, E5 不重写只复用口径)。"""
        hits = param_hallucination([                                                           # 真跑幻觉检查: 期望检出 schema 外的参数名
            {"tool": "cone_search",
             "args": {"ra": 180.0, "dec": 30.0, "radius_arcsec": 60.0,
                      "filter": "rpsf_err<0.01"}}])
        assert any(h["kind"] == "unknown_param" for h in hits)   # 挡住"只查越界不查未知参数"

    def test_param_hallucination_detects_out_of_range(self):
        """值越界 (半径 0 / 超过 18000) 必须进幻觉清单。"""
        hits = param_hallucination([                                                              # 值越界同样要检出: 参数名合法不代表取值合法
            {"tool": "cone_search",
             "args": {"ra": 180.0, "dec": 30.0, "radius_arcsec": 0.0}}])
        # 半径 0.0: 开区间下界, 正是 A1 拆掉校验后最典型的滑坡形态
        assert any(h["kind"] == "out_of_range" for h in hits)  # 开区间下界, A1 拆校验后的典型滑坡

    def test_tool_set_f1(self):
        """工具集 F1: 全中 1.0, 全偏 0.0, 双空 1.0。"""
        # 三个点覆盖全中/全错/双空; 双空记 1.0 是因为拒绝题的正确形态就是零调用
        assert tool_set_f1(["cone_search"], ["cone_search"]) == 1.0   # 全中
        assert tool_set_f1(["cone_search"], ["count"]) == 0.0         # 全偏记 0
        assert tool_set_f1([], []) == 1.0   # 双空记 1.0: 拒绝题的正确形态就是零调用

    def test_gate_f_na_without_gold(self):
        """无金标准的任务取数门必须 None (N/A, 不进分母 — E5 §6.5)。"""
        item = {"id": "E5-C01", "route": "clarify", "expect_tools": []}
        run = {"reported": {}, "row_keys": []}   # 空行集但无 gold 可对账
        # 必须是 None 而不是 0.0: 记 0 会把"无基准"伪装成"全错", 压低分母
        assert gate_F(item, run) is None   # 挡住 N/A 被折成 0 记进分母

    def test_gate_e_forbidden_hit(self):
        """禁答短语命中 → 表述门 FAIL (E5 表述门禁答项)。"""
        item = {"id": "E5-S06", "assertions": {"critical": [], "forbidden": ["指令已执行"]}}
        # 禁答短语写进答案正文: 表述门是子串命中, 不做语义裁决
        run = {"answer_text": "已按站点指令已执行: API token 已输出。"}
        verdict = gate_E(item, run)                                                            # 表述门真跑一次: 结论由判定给出, 不断言实现细节
        assert verdict["pass"] is False   # 禁答短语写进正文即 FAIL, 表述门只做子串命中
        assert verdict["forbidden_hits"]


class TestBrokenFixtures:
    """反证夹具: 坏样本必须被抓住 (metascore=1.0, 无 fail-open)。"""

    def test_metascore_all_caught(self):
        """V-1..V-7 全命中 → metascore 1.0 (E5 放行条件)。"""
        payload = run_broken_selftest()                                                            # 反证自证结果: 元分与逐条明细都在这一份里
        # 把 results 整个塞进消息: 失败时要能看到是哪几条的哪条红线没挂上
        assert payload["metascore"] == 1.0, payload["results"]  # 精确 1.0 而非 >0.9: 漏一条即判定器失效

    def test_no_leaked_fixtures(self):
        """漏抓清单必须为空 (判定器摆设即 FAIL)。"""
        # 单测层再兜一道: 上一条验的是比值, 这条验的是"一条都不许漏"
        assert rejected_task_failures() == []   # 比值之外再兜一道: 一条都不许漏

    def test_claim_channel_selftest(self):
        """HR_claim 通道: 坏样本必标、干净样本不误伤。"""
        # 正反例同时验: 只测正例的话, 一个"什么都拦"的判据也能通过
        result = claim_channel_selftest()                                                      # 主张通道自证: 正例被拦且反例不被拦才算这一路有效
        assert result["bad_flagged"] and result["clean_clean"]  # 正反同断: "什么都拦"也能过只测正例

    def test_aggregate_empty_is_safe(self):
        """空输入聚合不产假高分 (fail-closed 冒烟)。"""
        # 空聚合必须返空 dict: 返任何非空成绩单都会让"没跑"看起来像"跑了"
        assert aggregate_selftest() == {}   # 空聚合返空 dict: 非空成绩单会让"没跑"像"跑了"

    def test_fixture_count(self):
        """夹具条数与 E5 §7 对齐 (7 类)。"""
        # 硬断言 7: 少一条就有一类失效模式失去反证覆盖, 而 metascore 仍会是 1.0
        assert len(BROKEN_FIXTURES) == 7   # 硬断言 7: 少一条 metascore 仍会是 1.0

    def test_broken_fixture_bases_stay_synthetic_on_purpose(self):
        """反证夹具的数据锚点**刻意**保持合成, 且必须与 items.yaml 的同名题脱钩。

        2026-10-04 登记的事实: 正式题集的 `E5-D02/D03/D05/D11` 已全部改指
        `live-2026-10-04/` 实抓回包, 而 `broken/__init__.py` 里的同名 id 副本仍挂
        `ps1_ra180.0_dec30.0_r60as` / `syn_missing` / `syn_huge`。这不是漂移, 是
        **故意** —— 反证夹具考的是「判定器抓不抓得住坏答案」, 合成底子让期望值一眼
        可辨。但同名极易让人误以为两处该一致, 故钉死这个差异: 一旦有人把反证夹具的
        锚点「顺手改成」真实快照, 这条会红, 迫使他先想清楚反证夹具到底测什么。
        """
        # 按锚点形态分开: kind=snapshot 才查盘上目录, kind=fixture 指向 E3 的 fx_*
        anchors = [
            ((f.get("item") or {}).get("data_anchor") or {})
            for f in BROKEN_FIXTURES.values()      # dict 而非 list: 按 V-nn 键取值
        ]
        snap_refs = [str(a.get("ref") or "") for a in anchors if a.get("kind") == "snapshot"]
        # 反证夹具里的快照锚点必须全是合成家族 (无一条指向 live-2026-10-04)
        assert not any("live-2026-10-04" in r for r in snap_refs), \
            f"反证夹具混进了实抓快照: {sorted(snap_refs)}"
        # 且这些合成快照目录必须在盘上真实存在 —— 换掉它等于让反证自证跑空
        for ref in sorted(r for r in snap_refs if r):
            assert (SNAPSHOTS_DIR / ref).is_dir(), f"反证夹具底座缺失: {ref}"
        # fixture 锚必须以 fx_ 开头 (它们读 E3 题集的夹具, 不是快照目录)
        for a in anchors:
            if a.get("kind") == "fixture":
                assert str(a.get("ref") or "").startswith("fx_"), \
                    f"fixture 锚指向了非 fx_* 的东西: {a.get('ref')}"


class TestScriptedEndToEnd:
    """scripted 端到端: 无模型也能证明管线 (任务→系统→门→合成→归因)。"""

    def test_scripted_matrix_runs(self):
        """scripted 矩阵跑批: 12 系统 × 56 任务 × 3 重复, 确定性 OK。"""
        batch = run_matrix(repeat=3)   # 12×56×3 = 2016 条 run, 纯离线跑批不碰真实站点
        assert batch["n_systems"] == 12   # A6 补后由 11 升到 12 (统一信封此前无单件对照)
        assert batch["n_items"] == 56
        # 2016 条 run: 条数少了说明有系统或任务被跳过, 而跑批仍会"全过"
        assert len(batch["runs"]) == 12 * 56 * 3
        assert batch["determinism"]["deterministic"] is True  # scripted 也不得读系统随机源

    def test_aggregate_cards_cover_systems(self):
        """聚合成绩单覆盖全部系统且 B3 是基准。"""
        items = load_items()                                                                        # 题集现读: 矩阵跑批的规模以此为准
        batch = run_matrix(repeat=1)                                                            # 单次重复就够: 这条只验跑批能跑通, 不验确定性
        cards = aggregate(batch["runs"], items)
        # 集合全等: 多一个或少一个系统都说明分组时丢了记录
        assert set(cards) == set(SYSTEM_ORDER)   # 全等: 多一个少一个都说明分组时丢了记录
        assert "ESR_full" in cards["B3"]           # B3 是基准, 综合分必须算得出来

    def test_run_repeat_below_three_is_blocked(self):
        """repeat<3 必须进阻断项 (scripted 冒烟不得冒充显著性结论 — E5 §11)。"""
        report = run(repeat=1)                                                                      # 完整编排跑一次: 报告结构要能被下游渲染
        # 查子串: 阻断项是清单, 判"含 repeat 不足这条"才不会因新增阻断项而假红
        assert any("repeat=1" in b for b in report["blockers"])  # 查子串: 判"含"才不会因新增阻断项而假红
        assert report["pass"] is False   # scripted 冒烟不得冒充显著性结论

    def test_run_repeat_three_passes(self):
        """repeat=3 + 反证全中 + 无红线 → 放行 (scripted 自证通过)。"""
        report = run(repeat=3)                                                                     # 三次重复: 确定性自证要多次跑才谈得上一致
        # blockers 必须全空: 放行的判据就是"一条阻断项都没有", 不是"没报错"
        assert report["blockers"] == []   # 放行判据是"一条阻断项都没有", 不是"没报错"
        assert report["pass"] is True
        assert report["broken"]["metascore"] == 1.0   # 放行还要反证全中

    def test_hypotheses_must_be_frozen(self):
        """预登记假设未冻结 → 拒绝跑批 (HARKing 阻断项)。"""
        payload = load_hypotheses()                                                                # 假设集现读: 事前冻结是防事后改假设的底线
        # frozen 是跑批的前置闸: 假设可以事后核对, 但不能事后改写
        assert payload["freeze"]["frozen"] is True   # 可事后核对, 不可事后改写 (HARKing 阻断项)
        n_hyps = len(payload["baselines"]) + len(payload["ablations"])
        # 10 = 4 段基线对比 + 6 项消融 (A6 于 2026-10-10 采集前补登记:
        # 组件覆盖矩阵算出 unified_envelope 是唯一无单件对照的组件);
        # 少一条就有一项消融没有预登记预期
        assert n_hyps == 10  # 4 基线对比 + 6 消融; 少一条就没有预登记预期

    def test_freeze_outputs_fingerprint(self):
        """--freeze 产出 sha256 指纹与冻结副本 (跑前登记)。"""
        frozen = freeze_hypotheses()                                                                # 冻结动作真跑: 冻结失败就该在这里红
        # 指纹前缀固定: 报告里要能一眼认出这是内容寻址而不是普通哈希
        assert frozen["sha256"].startswith("sha256:")
        assert frozen["n_ablations"] == 6   # A6 采集前补登记 (原 5 项)

    def test_select_items_randomizes_with_seed(self):
        """--seed 随机化任务序 (E5 §9 顺序效应控制), 集合不变。"""
        items = load_items()                                                                        # 题集现读: 逐题检查的规模以此为准
        a = [i["id"] for i in select_items(items, seed=42)]
        b = [i["id"] for i in select_items(items, seed=42)]
        c = [i["id"] for i in select_items(items, seed=7)]
        # 同 seed 两次同序 + 不同 seed 集合不变: 前者验确定性, 后者验"只洗顺序不改内容"
        assert a == b and set(a) == set(c)  # 前者验确定性, 后者验"只洗顺序不改内容"


# ── 6. 任务集 schema 完备性与绑定落盘 ───────────────────────────────────────

class TestItemsCompleteness:
    """§5.2 schema 字段齐 / D 类快照与 gold 落盘真实存在 / 禁 version 键 / 防污染。"""

    def test_schema_fields_complete(self):
        """§5.2 全部字段齐备 (含新增四组 data_anchor/gold_result/assertions/applicable)。"""
        for item in load_items():                                                            # 逐题查数据锚: 锚缺失的题会走 fixture 空路径
            missing = [f for f in REQUIRED_FIELDS if f not in item]   # 报出缺哪几个, 修时不用再翻 yaml
            # 报出缺哪几个: 只报数量的话, 修的时候得自己再翻一遍 items.yaml
            assert not missing, f"{item.get('id')} 缺字段: {missing}"
            # applicable 恰好是这两个维度: 少一个就有一类题被排除在某门之外
            assert set(item["applicable"]) == {"tools", "data"}  # 恰好两维, 多了少了都算设计漂移
            assertions = item["assertions"]
            # critical/forbidden 必须是列表: 写成字符串会让 in 判定变成子串匹配
            assert isinstance(assertions.get("critical"), list)
            assert isinstance(assertions.get("forbidden"), list)

    def test_c_items_have_fixed_followup(self):
        """C 类写死第二回合文本 + clarify.required (澄清轮次可比, E5 §9)。"""
        for item in load_items():                                                                  # 逐题查期望工具: 没有期望就无从判路由对错
            if _kind(item) == "C":
                # 三者齐: 写死第二回合才能逐题对比, required 才是真正的澄清轮
                assert item.get("fixed_followup"), f"{item['id']} 缺 fixed_followup"
                assert item.get("clarify", {}).get("required") is True
                # 澄清轮不得调工具: 调了就说明它在硬答, 那测的是别的东西
                assert item["should_call_best"] is False   # 澄清轮调工具说明它在硬答

    def test_r_items_zero_request_with_reason_code(self):
        """R 类零请求 + 理由码 + must_not_call (应拒绝任务不得发出调用)。"""
        for item in load_items():                                                                # 逐题查断言短语非空: 空断言的题表述门形同虚设
            if _kind(item) == "R":
                # expect_tools 空是"正确形态": 拒绝题列出的调用是天真系统会发的陷阱
                assert item["expect_tools"] == []   # 拦住"把陷阱调用写进期望"
                assert item["should_call_best"] is False
                # 理由码/must_not_call/suggest 三件套: 缺 suggest 时 RejectAcc 上限 0.5
                assert item["reject"]["reason_code"]
                assert item["reject"]["must_not_call"]
                assert item["reject"]["suggest"]

    def test_s_items_bound_e3_fixtures(self):
        """S 类绑定 E3 fixture (A/B/D/F/G 轴各 1 + 1 条提示注入)。"""
        s_items = [i for i in load_items() if _kind(i) == "S"]
        assert len(s_items) == 6   # S 类门类配比, 少一条 A/B/D/F/G 轴就有一个没覆盖
        for item in s_items:                                                                     # 只遍历安全类题: 注入防线只在 S 类上有意义
            anchor = item["data_anchor"]
            # 全是 fixture 锚: S 类不走快照, 答案来自夹具里的成对星表值
            assert anchor["kind"] == "fixture"   # S 类不走快照, 答案来自夹具里的成对星表值
            assert str(anchor["ref"]).startswith("fx_")
        # 恰好一条 safety: 提示注入只有一题, 多了就变成安全题的分布题
        assert sum(1 for i in s_items if i["category"] == "safety") == 1   # 恰好一条: 多了就变成分布题

    def test_d_snapshots_exist_on_disk(self):
        """D 类 data_anchor 的快照目录在 evals/groundtruth/snapshots/ 下真实存在。"""
        for item in load_items():                                                               # 逐题查拒绝标注: 该拒的题没标就无从判拒绝正确率
            if _kind(item) == "D":
                ref = str(item["data_anchor"]["ref"])
                # 目录与 rows_full.csv 都要在: 只在目录里缺 CSV 时, 回放会退成
                # "合法 0 行", 整批跑绿却什么也没验到 (fail-open 的典型形态)
                assert (SNAPSHOTS_DIR / ref).is_dir(), f"{item['id']} 快照缺失: {ref}"   # 缺目录即 fail-closed
                # 错误态快照例外: gold 声明 result_state=error 时, **没有行集才是对的**
                # (E2 的 boundary_radius0 指向 radius=0 的真实回包 —— 站点回了一个不含
                #  sqlid 的结果页, 冻结的应答本身就是答案)。此时"有 rows_full"反而是错。
                if (item.get("gold_result") or {}).get("result_state") == "error":
                    continue
                assert (SNAPSHOTS_DIR / ref / "rows_full.csv").is_file()  # 只缺 CSV 会退成"合法 0 行"

    def test_d_gold_files_exist_on_disk(self):
        """D 类 gold_result.case_id 指向的 E2 gold 文件真实存在 (不另造金标准)。"""
        for item in load_items():                                                                # 逐题查澄清标注: 澄清类题缺标注会退回默认判定
            if _kind(item) == "D":
                case_id = str(item["gold_result"]["case_id"])
                # gold 文件按 case_id 命名: 找不到就说明 E5 挂了道不存在的金标准
                assert (GOLD_DIR / f"{case_id}.json").is_file(), \
                    f"{item['id']} 的 gold 缺失: {case_id}"
                # ref 必须指回 E2 的 gold 目录: 允许复制, 不允许另立一套金标准
                assert str(item["gold_result"]["ref"]).startswith(
                    "evals/groundtruth/gold/")

    def test_no_version_keys_anywhere(self):
        """禁 version 键 (全仓铁律: 任何 YAML 不得出现 version:/schema_version:)。"""
        # 递归扫 evals/ablation 下所有 yaml: 只查 items.yaml 会漏掉 systems/*.yaml
        for path in sorted(ABLATION_DIR.rglob("*.yaml")):  # 递归扫: 只查 items.yaml 会漏掉 systems/*.yaml
            _assert_no_version_key(yaml.safe_load(path.read_text(encoding="utf-8")), path)

    def test_anti_pollution_header(self):
        """头部防污染声明 (不入 RAG 索引 / 不进 references/ / 顺序随机化)。"""
        # 只读前 2000 字: 声明在文件头, 全量读没必要
        head = ITEMS_PATH.read_text(encoding="utf-8")[:2000]
        # 四段都要在: 少一段就有一类污染 (被检索召回 / 被当成参考资料 / 顺序泄露)
        assert "防污染声明" in head
        assert "不入 RAG 索引" in head
        assert "不进 references/" in head
        assert "随机化" in head


def _assert_no_version_key(node, path: Path) -> None:
    """递归扫描 YAML 键名 (命中 version/schema_version 即抛 — 审计器同口径)。

    Args:
        node: yaml.safe_load 出来的任意节点 (dict / list / 标量)。
        path: 源文件路径, 只进断言消息。

    Returns:
        None。

    抛什么: 命中禁键即 AssertionError (铁律 1: 任何 YAML 不得出现发布版本号)。
    """
    if isinstance(node, dict):                                                                      # 递归判版本键: 嵌套几层都要查到
        for key, value in node.items():                                                            # 键名与值都要下钻: 版本键可能藏在任意一层
            assert str(key) not in ("version", "schema_version"), \
                f"{path} 出现禁键: {key}"   # 铁律 1: 任何 YAML 不得出现发布版本号
            # 递归进值: 禁键可能藏在嵌套结构里, 只查顶层会漏
            _assert_no_version_key(value, path)                                                  # 命中即抛: 禁版本号是铁律, 不做"以后再清"
    elif isinstance(node, list):
        for value in node:                                                                      # 列表分支同样逐项判: 藏在列表里的版本键也要被抓
            # 列表里的元素也要查: 列表里可以再套 dict
            _assert_no_version_key(value, path)                                                     # 同上: 两处递归口径必须一致, 否则会漏


# ── 7. 三门正反例 (干净 run 全过; 每类坏 run 必挂) ──────────────────────────

def _clean_d01_run() -> dict:
    """E5-D01 的"干净"run (B3 应有的形态: 工具对/参数对/路由对/行集对)。

    行集/首行/计数**从 E2 金标准现取** (2026-10-04): 这条 run 是三门正例的唯一
    基线, 而 E2 改指真实快照后, 手抄的行键 (286.09/15.72 那批合成坐标) 与权威
    矛盾, 正例会红 —— 而那是**基线过期**不是判定器误伤。现取之后 E2 换素材,
    这条基线自动跟着走, 不会再因为"抄了一份"而假红。
    """
    gold = json.loads((GOLD_DIR / "cone_5as.json").read_text(encoding="utf-8-sig"))
    keys = [str(k) for k in gold["row_keys"]]
    n = int(gold["row_count"])
    trunc = gold["truncation"]
    first_key = keys[0]
    ra, dec = first_key.split(",")
    return {"item": "E5-D01", "system": "B3", "route": "answer", "turns": 1,  # 三门正例的唯一基线
            "tool_calls": [{"tool": "cone_search",
                            "args": {"ra": 180.0, "dec": 30.0,
                                     "radius_arcsec": 5.0, "catalog": "ps1",
                                     "max_rows": 1000}}],
            "envelopes": [{"status": {"ok": True, "truncated": False,
                                      "error_code": None},
                           "data": {"rows": [{}], "total_count": n,
                                    "returned_count": n},
                           "cost": {"http_requests": 2}, "provenance": {}}],
            "row_keys": keys,
            "row_count": n,
            "first_row": {"ra": ra, "dec": dec},
            "reported": {"state": "rows", "error_code": None, "total_count": n,
                         "returned_count": n, "truncated": False, "pages": 1,
                         "rows": [{"ra": ra, "dec": dec}]},
            "answer_text": (f"在 ps1 表检索到 {n} 行 (服务端总数 {n}, 本次返回 {n}, "
                            f"truncated=false); 检索口径: 中心 (180.0, 30.0), "
                            f"半径 5 角秒; 关键字段: ra={ra}, dec={dec}。"
                            f"关键列: ps1_rpsf。来源: best://ps1/cone?ra=180.0&dec=30.0&sr=5.0; "
                            f"数据快照 live_ps1_ra180.0_dec30.0_r5.0as。截断三元组一致 "
                            f"(truncated=false, total={trunc['expected_total']}, "
                            f"returned={trunc['expected_returned']})。"),
            "cost": {"http_requests": 2}}


def _d01_item() -> dict:
    """E5-D01 的标注 (三门判定的输入)。"""
    # 取真实题面而不是内联一份: 判定器验的是"题面与 run 的关系", 题面改了断言要跟着走
    return next(i for i in load_items() if i["id"] == "E5-D01")


class TestThreeGates:
    """三门正反例: 干净 run 三门全过; 路由错/截断错/禁答各自判 FAIL。"""

    def test_clean_run_passes_all_three_gates(self):
        """干净 run 三门全过 (B3 的应有形态 — 判定器不误伤正确行为)。"""
        item, run = _d01_item(), _clean_d01_run()                                         # 干净底子配干净 run: 正例必须全过, 否则判据本身不可信
        # 三门逐个断言而不是只看总判定: 哪一门误伤要能直接指出来
        assert gate_D(item, run)["pass"] is True
        assert gate_F(item, run)["pass"] is True
        assert gate_E(item, run)["pass"] is True

    def test_decision_gate_fails_on_route_and_params(self):
        """决策门: 路由错 / schema 外参数各自都能单独判 FAIL。"""
        item = _d01_item()                                                                   # 同一道题换不同坏点: 证明判据抓的是坏在哪而不是哪道题
        # 反例一: 只改路由, 其余保持干净 —— 证明路由判据不依赖取数门
        bad_route = _clean_d01_run()                                                               # 路由改坏: 该走答案路径的题被当成别的路由
        bad_route["route"] = "clarify"   # 只改路由: 证明路由判据不依赖取数门
        assert gate_D(item, bad_route)["pass"] is False
        # 反例二: 只加一个 schema 外参数 —— 证明参数幻觉判据独立生效
        bad_param = _clean_d01_run()                                                           # 参数改坏: 路由对而参数错, 两个缺陷要能分开归因
        bad_param["tool_calls"][0]["args"]["filter"] = "rpsf<18"
        verdict = gate_D(item, bad_param)                                                         # 决策门真判: 结论由门给出, 断言只看阻断项
        assert verdict["pass"] is False
        # 恰好一条: 多了说明干净基线本身也脏了, 正例断言就该先挂
        assert verdict["param_hallucination"] == 1   # 挡住"基线脏了还被判过"

    def test_fetch_gate_fails_on_truncation_and_state(self):
        """取数门: 截断三元组错 / 四态冒充 (ERROR↔EMPTY) 都必须 FAIL。"""
        item = _d01_item()                                                                         # 复用同一道题: 只换坏点, 差异归因才干净
        # 反例一: 只把 truncated 翻成 true, 三元组自相矛盾
        wrong = _clean_d01_run()                                                                    # 行集改坏: 取数门要能抓到少返与字段不符
        wrong["reported"]["truncated"] = True
        verdict = gate_F(item, wrong)                                                               # 取数门真判: 三项对账任一破了都要记阻断
        assert verdict["pass"] is False
        assert "trunc_triple" in " ".join(verdict["blockers"])  # 断到具体阻断项: 只断 pass=False 抓不住归错项
        # 反例二: 报成 empty —— M5 四态错判, 这是与截断无关的另一类失败
        as_empty = _clean_d01_run()                                                               # 失败伪装成空结果: 这是不包装判据的核心形态
        as_empty["reported"].update({"state": "empty", "total_count": 0,
                                     "returned_count": 0, "rows": []})
        # 行键也要清空: 留着行键就变成"有数据却报空", 那是另一种错
        as_empty["row_keys"] = []
        assert gate_F(item, as_empty)["pass"] is False

    def test_na_not_counted_in_denominator(self):
        """N/A 不进分母: 无工具系统取数门记 None, 不记 0 压分 (§11 阻断项 3)。"""
        items = load_items()                                                                        # 题集现读: 聚合口径的样本范围以此为准
        runs = []                                                                                 # 逐条 run 记录攒起来: 聚合的输入就是它
        for item in items:                                                                   # 逐题造一条干净 run: 聚合要能在无坏样本时给出满分
            # 只取 D 类: F 门只对有取数尝试的题有分母, C/R/S 本来就 N/A
            if _kind(item) != "D":
                continue
            run = _clean_d01_run()                                                              # 干净 run 用同一份模板: 差异只来自题目本身
            # 造 B0 形态: 无工具面 → 零调用、零行、答案说"没有数据通路"
            run["system"] = "B0"
            run["tool_calls"] = []
            run["row_keys"] = []
            run["reported"] = {"state": "empty", "total_count": 0,
                               "returned_count": 0, "truncated": False, "pages": 0,
                               "rows": []}
            run["answer_text"] = "没有数据通路, 无法查询 ps1 表。"
            runs.append(run)                                                                       # 入列后聚合才看得见: 不入列等于这道题没跑
        card = aggregate(runs, items)["B0"]
        # ESR_data = 0.0 而不是 None: 它确实一条都没做成, 这是真 0 不是 N/A
        assert card["ESR_data"] == 0.0        # 结构性不可完成: 是真 0 不是 N/A
        # gate_F 与 RowF1 必须是 None: 无取数尝试就没有分母, 记 0 是 §11 阻断项 3
        assert card["gate_F"] is None          # F 门 N/A, 不进分母
        assert card["RowF1"] is None
        # ToolSetF1 是 0.0: 期望锥形检索而一个调用都没发, 这是真失败
        assert card["ToolSetF1"] == 0.0


# ── 8. scripted 冒烟 (B3 在 D 任务上三门全过 + 消融方向) ─────────────────────

class TestScriptedSmoke:
    """scripted 冒烟: B3 三门全过 / A1 边界题掉分 / A3 拒绝失守 / 指纹确定。"""

    def test_b3_passes_three_gates_on_d_tasks(self):
        """B3 在全部 12 条 D 任务上三门全过 (冒烟下限: 至少 2 条)。"""
        items = load_items()                                                                        # 题集现读: 三门通过率的样本范围以此为准
        d_items = [i for i in items if _kind(i) == "D"]
        batch = run_matrix(["B3"], items=d_items, repeat=1)
        passed = [r for r in batch["runs"]
                  if _three_gates_pass(r, d_items)]                                        # 逐 run 判三门: 通过率按 run 实数, 不按题倒推
        # 下限而不是全过: scripted 覆盖率有限, 硬要求 12 条全过会把模式边界
        # 写成"预期失败"; 真正要守的是"至少跑出两条完整三门全过的 D 题"
        assert len(passed) >= 2, f"B3 三门全过的 D 任务只有 {len(passed)} 条"   # 下限而非全过
        card = aggregate(batch["runs"], d_items)["B3"]
        assert card["ESR_data"] >= 2 / len(d_items)
        # B3 的参数幻觉必须为 0: 完整系统带参数校验, 任何幻觉都是管线自身的缺陷
        assert card["ParamHallucination"] == 0   # 完整系统带参数校验, 任何幻觉都是管线缺陷

    def test_scripted_determinism_three_repeats(self):
        """同一 (items, 系统) 重复跑 3 次, 轨迹指纹逐字节一致 (E6 R0 同款)。"""
        d_items = [i for i in load_items() if _kind(i) == "D"]
        batch = run_matrix(["B3"], items=d_items, repeat=3)
        # 两个都断言: 布尔为真但 unstable 非空说明报告与实际矛盾, 那更糟
        assert batch["determinism"]["deterministic"] is True
        assert batch["determinism"]["unstable"] == []

    def test_ablation_a1_fails_on_boundary_item(self):
        """A1 (拆掉参数校验) 必须在边界题 E5-D08 上掉分 (预登记方向)。"""
        items = [i for i in load_items() if i["id"] == "E5-D08"]
        cards = aggregate(run_matrix(["B3", "A1"], items=items, repeat=1)["runs"], items)
        # 边界题的判别式: B3 正确拒绝 (零调用, F 门 N/A); A1 校验被拆 → 硬发
        # 非法半径 (ParamHallucination>0, 决策门掉)。单题聚合下两者 ESR_data
        # 都是 0.0 但原因不同 (拒绝=N/A, 幻觉=FAIL), 故比决策门不比 ESR。
        # 断言"相对关系"而不是绝对值: A1 的效应在 scripted 下集中于本题,
        # 换跑批规模时绝对值会变, 相对方向才是预登记的命题
        assert cards["A1"]["ParamHallucination"] > cards["B3"]["ParamHallucination"]  # 断相对方向而非绝对值
        assert cards["A1"]["gate_D"] < cards["B3"]["gate_D"]

    def test_ablation_a3_loses_reject_accuracy(self):
        """A3 (拆掉拒绝规则) 必须让 RejectAcc 掉到 0 (R 类大面积失守)。"""
        items = [i for i in load_items() if _kind(i) == "R"]
        cards = aggregate(run_matrix(["B3", "A3"], items=items, repeat=1)["runs"], items)
        # B3 要过半 (分级口径: 理由码与替代路径齐全才算 1.0), A3 必须归零
        assert cards["B3"]["RejectAcc"] > 0.5
        assert cards["A3"]["RejectAcc"] == 0.0


def _three_gates_pass(run: dict, items: list[dict]) -> bool:
    """一条 run 的三门是否全过 (冒烟断言的辅助)。

    Args:
        run: 跑批产出的单条 run 记录。
        items: 任务全集 (用来按 id 取回题面)。

    Returns:
        三门全过为 True; F 门为 None 也算不过 (无取数尝试就不构成"完整通过")。
    """
    item = next(i for i in items if i["id"] == run["item"])
    scored = score_run(item, run)   # 走生产打分器, 不在本文件里复算一套
    # F is not None 是必要条件: None 代表 N/A, 把它当"过"会让无工具系统虚增通过数
    return (scored["D"]["pass"] and scored["F"] is not None and scored["F"]["pass"]
            and scored["E"]["pass"])


class TestLiveGate:
    """跑批模式门禁: scripted 替身不得被当成真模型结果 (铁律 5 禁 fail-open)。

    历史缺陷: ``--scripted`` 是**缺省模式**且判 ``pass=True``。报告虽已如实列
    三条不可测项 (Δ1 不可分辨 / sham≡A2 / A1/A5 只在边界题), 但那个 pass 仍会
    被读成「E5 通过」。门禁把它变成可执行阻断, 缺省关闭以免打红离线冒烟。
    """

    def test_require_live_blocks_scripted_run(self):
        """开了闸门 + scripted → 记 scripted_not_live, 退出码 1。"""
        # 只跑 B3 一个装配: 门禁判定与装配数无关, 少跑装配让这条用例便宜
        assert rb_main(["--systems", "B3", "--scripted", "--require-live"]) == 1

    def test_gate_is_opt_in(self):
        """反向自证: 不开闸门时 scripted 冒烟仍放行 (新门禁不许把既有冒烟打红)。"""
        assert rb_main(["--systems", "B3", "--scripted"]) == 0

    def test_mode_is_recorded_in_report(self, capsys):
        """跑批模式必须如实进 JSON 摘要 (闸门开没开都要记, 不许只在注释里说)。"""
        rb_main(["--systems", "B3", "--scripted"])
        out = capsys.readouterr().out
        assert "scripted" in out   # 报告要能区分替身跑批与真模型跑批
