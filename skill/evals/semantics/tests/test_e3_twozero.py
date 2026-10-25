# -*- coding: utf-8 -*-
"""E3 单测 (自 test_e3.py 拆出) — 两张恒 0 的表: 区分度实证 / 逐字段溯源 / 探点天区门。

为什么这个文件存在: 下面三类断言全部围绕**同一件事** —— ``fx_two_zero_catalogs``
这道题 (E3-F06) 测的"两张回包同形的表必须分开报告"到底站不站得住。它们与
test_e3.py 里的预筛正反例、agreement 统计量、runner 冒烟**不共享任何夹具**,
只共享 evals.semantics 的公开面, 因此是天然的一簇。此前它们与那几簇挤在同一个
文件里, 把该文件顶到 400 净行预算的**上限** (零余量): 于是"给一个健康行为补一条
测试"这件事本身会立刻让 ``count_code_lines`` 转红 —— 给正确行为埋地雷。按
"内聚优先"的最小越界口径拆开, 先例是
``test/unit/meta/test_knowledge_surface_gate.py`` 从
``test_gate_criterion_red.py`` 拆出, 理由与写在那里的一样 (行数预算)。

三道门各管一段, 少任何一段都留一个可被误用的口子:
- 区分度实证 (正反成对): 合并两张恒 0 表的坏回答必须被判错, 分开报告的好回答
  必须零命中, 并且题面必须真的钉住那个**不对称** —— 只有"必须分开"而无两侧各自
  的结论就是废题;
- 逐字段溯源: fixture 里每个数都要对回**已入库快照**实测 (字节数/表头列数/数据
  行数/状态码/sqlid/计数), 取不到快照即判红。这道门是把"逐字段溯源"从文档里的
  一句承诺变成每次跑批都执行的断言, 由来是 ``page_header_columns`` 曾被写成 57
  而快照实为 53 列;
- 探点天区门: jplus_dr3 的探点必须落在它自己的公认天区内, 否则这道题会惩罚**更
  正确**的答案 —— 区外探到的 0 用天区覆盖就能解释, 题面却要求答"疑似站点侧异常"。

职责: 守住 E3-F06 这一题的三条不变量 — 判别力有实证、fixture 的每个数都真的来自
  真实回包、题面的前提与知识面片段登记的天区一致。
所属实验: E3 科学语义区分与幻觉抑制 (37 题 7 轴); 判据真值是
  docs/eval-E3-semantics.md §7.3/§9/§10 与 evals/semantics/rubric.yaml §3/§6,
  本文件只断言代码行为与那两份文档及入库快照一致, 不重新定义指标。
对外接口: 无 (pytest 收集面)。三个测试类分别是
  TestTwoZeroCatalogsItemDiscriminates (区分度实证) /
  TestTwoZeroFixtureIsTraceable (逐字段溯源) /
  TestTwoZeroProbeIsInsideJplusRegion (探点天区门), 各自的测试方法名即断言对象。
依赖与数据流: 输入 = evals/semantics/items.yaml 里的 ``fx_two_zero_catalogs`` 与
  E3-F06 题条目 (现读, 改了题集不同步这里即红), 以及
  evals/groundtruth/snapshots/live-2026-10-04/ 下那两份**已入库**的抓取快照;
  中间件 = evals.semantics.prescreen / broken / runner 的公开函数; 产物 = pytest
  断言结果, 不发请求、不写文件、不落盘。
关键契约与不变量: 全程离线 —— 快照是已入库资产, 门禁只验 fixture 与它一致, 不重抓、
  不碰站点 (真值性由抓取时的 manifest.json 哈希负责); 零跨实验 import, 只引
  evals.semantics.*; 同一份代码重复跑必须得到同一结论, 因此这里不断言时间戳与
  随机量。跨实验等价性由 evals/equivalence/ 的断言守护, 本文件不重复造那份断言。
陷阱与边界: (1) 下面三节横幅的编号 **5/6/7 是从 test_e3.py 原样搬来的**, 不是
  本文件自己的分节序号 —— 保留原编号是为了让"这段代码原先住在哪"可追溯, 拆文件
  不该顺手改注释文本。副作用是本文件的 docstring 刻意**不写成编号清单**形态:
  写成 1./2./3. 会与横幅的 5/6/7 撞上 verify_doc_consistency 的 STRUCT 判据
  (它比对的是"docstring 最大序号 vs 横幅最大序号"), 而原文件正是靠"docstring 用
  破折号条目"规避同一处。
  (2) ``_SNAPSHOT_ROOT`` 的 parents[2] 与原文件同级同深, 换文件名不改深度, 仍指向
  evals/groundtruth/snapshots/。
  (3) 快照缺失一律判红不静默跳过 (铁律 5 禁 fail-open): 溯源件没了还让题集继续
  声称"逐字段溯源到真实回包", 那是把一句承诺悬空。
"""
from __future__ import annotations

# 标准库: csv/io 数分页 CSV 的表头列数 (本轮抓到 57/53 偏差, 必须现算不能抄) /
# json 读 capture_log 的逐请求实测记录 / pathlib 锚定快照目录
import csv  # 数分页 CSV 的表头列数: 本轮抓到 57/53 偏差, 列数必须现算不能抄
import io  # StringIO 把 CSV 字节流喂给 csv.reader
import json  # 读 capture_log.json 的唯一入口: 逐请求的实测记录 (与 fixture 逐字段对源)
from pathlib import Path

# 第三方: pytest (parametrize 把两张表各自跑一遍, 缺表即红)
import pytest

# 本地: 被测件, 只引本文件真正用到的那几个公开符号
from evals.semantics.broken import run_broken_selftest  # B-4 反证夹具必须被抓住: 否则 metascore 恒 1.00 就是假绿
from evals.semantics.prescreen import prescreen  # 汇总入口: 跑一遍 E3-F06 的正反回答, 看聚合侧有没有把命中计进去
from evals.semantics.runner import load_items  # 题集现读: fx_two_zero_catalogs 与 E3-F06 题条目都从它来

# ── 5. 新题 E3-F06 的区分度实证 (正反成对) ──────────────────────────────

# 坏回答: 把两张**回包形态完全一致**的恒 0 表合并成"两张表都没数据", 并顺势
# 断言"这个天区没有任何源" + 编一个锥内源数。这是"不知道要分开报告"的典型形态。
_MERGED_ANSWER = (
    "这两张表我都查了, 回包完全一样: total=0、HTTP 200、只有一个表头的 CSV。"
    "说明 BEST 的 landolt 和 jplus_dr3 两张表都没有数据, 都是空表, "
    "建议直接从流程里去掉; 这个天区没有任何源。jplus_dr3 我按 0.5 度锥估了一下, "
    "里面应该有 60 多颗源, 现在一颗都没有, 肯定是站点那边出问题了。"
)
# 好回答: 分开报告, 并写清两者的**证据等级不同** (landolt 统计可解释 vs jplus 待确认)。
# 刻意避开"404"字样: 那是软错误的**名字**不是测量值, 被抽数器抽成 404 会算成
# 无来源数值 (L0 是上界, 报告已披露; 这里避开来让对照干净可读)。
_SPLIT_ANSWER = (
    "这两张表必须分开报告, 回包形态一样不代表结论一样。landolt 的 0 命中是统计正常的稀疏: "
    "全表 45712 行摊到全天约 1 行 / 3.7 deg2, 0.5 度锥的期望命中只有 0.018 行, "
    "所以 0 完全在预期内, 不是故障; 要用它必须先有已知标准星坐标, 因为锥搜按位置找, "
    "按名字找不到。jplus_dr3 是另一回事: 在它自己的公认天区 Dec -79..-45 内探测 24 处、"
    "含最大半径 5 度 (约 385 deg2) 仍全部 total=0, 密度解释不了, 只能记为疑似站点侧覆盖异常、"
    "待站方确认, 不能断言它已经坏了。留档快照里 getcount 与分页自洽, 站内没有软错误形态, "
    "站点此刻的表现与该锥内真无源无法区分; 要坐实坏表得拿站方日志, 改客户端代码没用。"
)


class TestTwoZeroCatalogsItemDiscriminates:
    """E3-F06 的区分度实证: 坏回答必须被判错, 好回答必须不被误判。

    为什么这道题值得单独取证: 它测的是**知识面小节**「两张恒 0 的表必须分开报告」
    (static/fragments/data_source/best_catalogs.md), 此前无任何题目指到。若一答就对,
    它就是废题 —— 与其事后被评阅人质疑, 不如在这里用正反成对的回答把判别力钉住。

    判别点具体是什么: 两张表的回包**完全同形** (total=0 + HTTP 200 + 只有表头的
    CSV + 0 数据行), 合并成一句"两张表没数据"在回包上完全自洽、看着最省事 ——
    那正是不知道这个区分的回答会写的东西。正确回答必须给出**不对称**的结论:
    landolt 统计可解释 (期望 0.018 行), jplus_dr3 密度解释不了但**只能记待确认**。

    诚实边界 (2026-10-05 修坐标后复核, 结论不变): L0 预筛是**只标记不裁定**的启发式,
    它抓的是"合并"的**下游后果** (断言无源 → 无支撑主张; 编锥内源数 → 无来源数值),
    不是"合并"这个动作本身; "分开报告"这条断言本身由 L2 依 must_state /
    must_not_state 判定, **机器判不了**。换言之: 纯合并、"说要分开但没给结论"、
    以及方向颠倒 (landolt=坏表 / jplus=确认坏) 三种坏回答**都漏过 L0** ——
    只有同时带无关通用缺陷 (凭空断言无源、编数值) 的才被抓到。

    本轮修的是**前提**不是**判据**: 探点此前落在 jplus 天区外, 那会让"指出探点在区外"
    这个更正确的回答被判错。坐标修对后题面与 must_state 自洽了, 但机器判别力**仍是零增量**。
    未新增"跨表结论一致性"预筛, 理由 (会碰 rubric.yaml 并抬高全部 37 题误报率) 见
    `temp/FIX-M1-e3-f06.md` §M1-03 与题集 `E3-F06._change`。
    """
    ITEM = {"id": "E3-F06", "axis": "F", "fixture": "fx_two_zero_catalogs",
            "qualifiers": ["subset_scope", "catalog_and_column"]}

    def _run(self, answer: str) -> dict:
        """用**题集里的真 fixture** 跑一遍预筛 (不内联副本: 改了题集不同步这里即红)。"""
        data = load_items()
        return prescreen(answer, self.ITEM, data["fixtures"])

    def test_merged_answer_is_flagged(self):
        """坏回答 (合并成"两张表没数据") 必须命中: 无支撑主张 + 无来源数值。"""
        summary = self._run(_MERGED_ANSWER)["summary"]
        assert summary["unsupported_claim_count"] >= 1, (
            f"合并两张恒 0 表还断言'没有任何源'却没被判无支撑主张: {summary}")
        assert summary["unsourced_number_count"] >= 1, (
            f"编的锥内源数 (60) 未被判无来源: {summary}")

    def test_split_answer_is_not_flagged(self):
        """反向自证 (对照组): 分开报告的好回答必须**零命中**, 否则判据成了橡皮章。"""
        summary = self._run(_SPLIT_ANSWER)["summary"]
        assert summary["unsupported_claim_count"] == 0, f"正确表述被误判: {summary}"
        assert summary["qualifier_missing"] == [], f"正确表述被判限定语缺失: {summary}"
        # 正文中引用的一切数值都必须在 fixture 溯源池内, 否则 UNGR 会被这道题虚高
        assert summary["unsourced_number_count"] == 0, (
            f"正确表述里的数值被判成无来源 —— fixture 漏收了真值: {summary}")

    def test_item_states_the_asymmetry_not_just_the_zeroth_row(self):
        """题面本身必须钉住**不对称**: 只有"必须分开"而无两侧各自的结论 = 废题。"""
        item = next(i for i in load_items()["items"] if i["id"] == "E3-F06")
        joined = " ".join(item["must_state"] + item["must_not_state"])
        assert "landolt" in joined and "jplus_dr3" in joined, "两侧都要出现在断言里"
        for needed in ("分开报告", "45712", "0.018", "24", "待站方确认"):
            assert needed in joined, f"断言里缺 {needed} —— 该题的判别点被稀释了"
        # must_not_state 必须同时挡住两个方向的合并误判 (都当没数据 / 都当坏表)
        assert any("合并" in s for s in item["must_not_state"]), "没禁'合并成一张表没数据'"
        assert any("坐实" in s for s in item["must_not_state"]), "没禁'断言 jplus 已坐实为坏表'"

    def test_broken_fixture_b4_is_caught(self):
        """B-4 反证夹具必须被抓住 —— 这条错了 metascore 恒 1.00 就是假绿。"""
        result = run_broken_selftest(load_items()["fixtures"])
        assert result["results"]["merged_zero_catalogs"]["caught"], result["results"]
        assert result["metascore"] == 1.0, result["results"]


# ── 6. fx_two_zero_catalogs 的溯源门: fixture 的每个数字都对回入库快照 ────────

# 两张表 → 入库快照目录名。取不到快照即判红 (铁律 5 禁 fail-open): 溯源件没了
# 还让题集继续声称"逐字段溯源到真实回包", 那是把一句承诺悬空。
# jplus_dr3 指向**区内**探点那份 (2026-10-05 补抓): 旧的那份探的是 (120.3, -20.4),
# 那是 uss_dr1 的天区 —— 见 TestTwoZeroProbeIsInsideJplusRegion 的说明。
_SNAPSHOT_DIRS = {
    "landolt": "live_landolt_ra10.68_dec41.27_r300.0as",
    "jplus_dr3": "live_jplus_dr3_ra10.0_dec-60.0_r300.0as",
}
_SNAPSHOT_ROOT = Path(__file__).resolve().parents[2] / "groundtruth" / "snapshots" / "live-2026-10-04"  # 锚: evals/groundtruth/snapshots/


class TestTwoZeroFixtureIsTraceable:
    """fx_two_zero_catalogs 的每个数必须与**入库快照**逐字段对得上。

    这道门的由来是一次真抓到的缺陷: `page_header_columns` 被写成 57, 快照里的
    `rows_full.csv` 表头实际是 53 列。一个没人核过的数进了题集, 而题集里的数会被
    当作"站点真值"喂给评阅人 —— 这正是本仓吃过亏的那一类 (`class_star=0.02`)。
    故把"逐字段溯源"从文档里的一句承诺, 变成**每次跑批都会执行的断言**。

    口径: 逐字段**核对**而不是重抓 —— 快照是已入库资产, 门禁只验证 fixture 与它
    一致; 真值性由抓取时的 `manifest.json` 哈希负责, 本门不重复验站。
    """

    @staticmethod
    def _spec(catalog: str) -> dict:
        """取题集里该表那一条回包登记 (缺表即红, 不静默跳过)。"""
        entries = load_items()["fixtures"]["fx_two_zero_catalogs"]["tool_returns"]
        spec = next((e for e in entries if e["catalog"] == catalog), None)
        assert spec is not None, f"fixture 里没有 {catalog} 的回包登记"
        return spec

    @pytest.mark.parametrize("catalog", sorted(_SNAPSHOT_DIRS))
    def test_recorded_sizes_and_shapes_match_snapshot(self, catalog: str):
        """字节数/表头列数/数据行数三项必须与快照文件实测一致。"""
        spec = self._spec(catalog)
        snap = _SNAPSHOT_ROOT / _SNAPSHOT_DIRS[catalog]  # 该表的快照目录 (缺即红)
        assert snap.is_dir(), f"溯源快照缺失: {snap}"

        # 字节数按**原始字节**比 (不是解码后的字符数): 回包是 HTTP body, 口径是字节
        assert spec["getcount_bytes"] == len((snap / "count.json").read_bytes())  # getcount 体
        assert spec["page_bytes"] == len((snap / "rows_full.csv").read_bytes())  # 分页 CSV
        assert spec["form_page_bytes"] == len((snap / "phase1.html").read_bytes())  # 表单页

        # 表头列数现算: 这是本轮抓到 57/53 偏差的那一项, 必须由代码数出来而不是抄
        raw = (snap / "rows_full.csv").read_bytes()
        assert raw[:3] == b"\xef\xbb\xbf", "分页 CSV 应带 BOM (题面按 BOM 描述其形态)"
        rows = list(csv.reader(io.StringIO(raw.decode("utf-8-sig"))))
        assert spec["page_header_columns"] == len(rows[0]), "表头列数与快照不符"
        assert spec["page_data_rows"] == len(rows) - 1, "数据行数与快照不符"

    @pytest.mark.parametrize("catalog", sorted(_SNAPSHOT_DIRS))
    def test_recorded_statuses_match_capture_log(self, catalog: str):
        """状态码/字节数/sqlid/计数四项必须与 capture_log 的 request_log+observed 一致。"""
        spec = self._spec(catalog)
        log = json.loads((_SNAPSHOT_ROOT / _SNAPSHOT_DIRS[catalog] / "capture_log.json")
                         .read_text(encoding="utf-8"))  # 逐请求的实测记录 (与 fixture 逐字段对源)
        posted = [r for r in log["request_log"] if r["method"] == "POST"][0]  # 提交查询那一条
        assert spec["form_page_status"] == posted["status"] == 200  # 表单页必须 200 (软错误也是 200)
        assert spec["form_page_bytes"] == posted["bytes"]  # 表单页字节数
        # sqlid 取自分页 URL 里的 s<id> (形如 /sqlid/s4784), 抄错会指到别的查询
        paged = [r for r in log["request_log"] if "output.fmt=csv" in r["url"]][0]  # 分页那一条
        assert spec["sqlid"] == int(paged["url"].split("/sqlid/s")[1].split("?")[0])  # sqlid
        assert spec["page_status"] == paged["status"] == 200  # 分页 200
        assert (spec["total"], spec["success"], spec["truncated"], spec["error_code"]) == (
            log["observed"]["total_count"], log["observed"]["success"],
            log["observed"]["truncated"], log["observed"]["error_code"])


# ── 7. E3-F06 的探点必须在 jplus_dr3 **自己的天区内** ───────────────────────

class TestTwoZeroProbeIsInsideJplusRegion:
    """**jplus_dr3 的探点必须落在它自己的公认天区内**, 否则这道题会惩罚正确答案。

    这道门是为一次真抓到的缺陷立的。`E3-F06` 测的是"landolt 的 0 是统计可解释的稀疏、
    jplus_dr3 的 0 可疑"这个**不对称**, 而它的 fixture 当时把 jplus 探在
    (120.3, -20.4) —— 那是 **`uss_dr1`** 的天区, 不在 jplus 公认天区 Dec -79..-45 内。
    于是题面自相矛盾: 区外探到的 0 恰恰是"该表没覆盖这里"**能解释**的结果, 而
    `must_state` 却要求答"疑似站点侧覆盖异常"。读了知识面的被测模型会指出这一点,
    而那个**更正确**的回答会被判错 —— 一道惩罚正确答案的题比没有这道题更糟。

    所以这里把"探点在区内"钉成断言: 它读的是知识面片段自己写的 Dec 范围, 不是
    本测试内联的常数 —— 片段改口径时这道门会跟着红, 而不是默默放过新的区外探点。
    """

    #: jplus_dr3 公认天区 (赤纬区间), 取自 static/fragments/data_source/best_catalogs.md
    #: 「两张恒 0 的表必须分开报告」一节原文 "Dec −79..−45"。
    REGION_DEC_RANGE = (-79.0, -45.0)                              # 片段原文口径, 不在本测试另立一个数

    def _specs(self) -> tuple[dict, dict]:
        """返回 (jplus 回包登记, E3-F06 题条目) —— 下面的断言都要这一对。"""
        data = load_items()                                         # 一次读盘: 下面所有断言都对着同一份题集数据
        spec = next(e for e in data["fixtures"]["fx_two_zero_catalogs"]["tool_returns"]
                    if e["catalog"] == "jplus_dr3")
        return spec, next(i for i in data["items"] if i["id"] == "E3-F06")

    def test_probe_is_in_region_prompt_matches_and_excuse_is_banned(self):
        """探点赤纬落在片段登记的 Dec -79..-45 内、题面坐标与 fixture 一致、
        且 `must_not_state` 显式禁掉"探点不在覆盖天区内"这个借口。

        前两条是本轮修的 (区外探到的 0 用天区覆盖就能解释, 题面却要求答"疑似站点侧
        异常")。第三条的理由: 坐标修对后这个借口的前提已是假的, 但它**语义上仍然读得通**
        (天区覆盖确实是 0 的一类成因, 只是不适用于这次探测) —— 不显式禁掉, L2 评阅人
        就没有可对照的判据。
        """
        spec, item = self._specs()                                   # 探点坐标与禁答项取自同一次读盘
        assert self.REGION_DEC_RANGE[0] <= spec["cone_dec"] <= self.REGION_DEC_RANGE[1], (
            f"jplus_dr3 探点 Dec={spec['cone_dec']} 在其公认天区 {self.REGION_DEC_RANGE} 之外 —— "
            "这个 0 用天区覆盖就能解释, 题面要求答的'疑似站点侧异常'就成了错判")
        assert f"({spec['cone_ra']}, {spec['cone_dec']})" in item["prompt"], "题面坐标与 fixture 不一致"
        assert any("覆盖天区" in s or "没覆盖" in s for s in item["must_not_state"]), (
            "must_not_state 没禁'探点不在覆盖天区内'这个借口 —— L2 评阅人无从判它")

    def test_in_region_snapshot_matches_out_of_region_bytewise(self):
        """区内那份的 `rows_full.csv` 必须与区外那份**逐字节相同** (0 行表头 CSV)。

        "回包形态完全一致、结论必须不同"这个判别点就架在这两份快照的**同形**上:
        区内那份若不是同样的形态, 这道题测的就不再是"回包一样但结论不同"。读不到文件
        会抛 FileNotFoundError, 同样是红 (不靠缺文件蒙过去)。
        """
        new = _SNAPSHOT_ROOT / _SNAPSHOT_DIRS["jplus_dr3"]
        old = _SNAPSHOT_ROOT / "live_jplus_dr3_ra120.3_dec-20.4_r300.0as"
        assert (new / "rows_full.csv").read_bytes() == (old / "rows_full.csv").read_bytes(), (
            "区内与区外两份的分页 CSV 不再逐字节相同 —— '回包同形、结论不同'的判别前提没了")
