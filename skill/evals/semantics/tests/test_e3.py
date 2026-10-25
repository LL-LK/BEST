# -*- coding: utf-8 -*-
"""E3 单测 — 预筛正反例 / 反证 metascore / 一致性自测 / runner 冒烟。

覆盖 (docs/eval-E3-semantics.md §7.3/§9/§10 与 rubric §3/§6):
- prescreen 每项检查 ≥2 正 2 反 (正 = 坏回答必须被标, 反 = 好回答不误标;
  否定用法豁免是静态误称判定的关键分界);
- 反证夹具 metascore = 1.00 (坏回答必须全被抓 — 无 fail-open);
- runner 冒烟: 37 题可加载、轴分布、无回答时 L0 摘要、CLI 退出码;
- 「两张恒 0 的表」那一簇 (E3-F06 的区分度实证 / 逐字段溯源 / 探点天区门)
  已按内聚拆到 test_e3_twozero.py, 见本文件"陷阱与边界"末段。

职责: 守住 E3 的四条不变量 — 预筛对坏回答不漏检、对好回答不误报、
  统计量在恒等/反向/随机三种输入下取值正确、runner 在无回答时也能给出
  可复核的 L0 摘要 (而不是空跑即绿)。
所属实验: E3 科学语义区分与幻觉抑制 (37 题 7 轴); 判据真值是
  docs/eval-E3-semantics.md §7.3/§9/§10 与 evals/semantics/rubric.yaml
  §3/§6, 本文件只断言代码行为与那两份文档一致, 不重新定义指标。
对外接口: 无 (pytest 收集面)。十个测试类分别是 TestStaticAsLc /
  TestSentinelMisuse / TestUnsourcedNumbers / TestQualifierCoverage /
  TestUnsupportedClaims / TestPrescreenIntegration / TestBrokenSelftest /
  TestRunnerSmoke / TestCoverageGate,
  各类的测试方法名即断言对象。
依赖与数据流: 输入 = 本文件内联的最小 fixture _FIXTURES 与 _GOOD_ANSWER /
  _BAD_ANSWER, 以及 evals.semantics.{prescreen,broken,runner}
  的公开函数与 items.yaml; 产物 = pytest 断言结果, 不落盘、不写文件。
关键契约与不变量: 全程离线, 不发请求不调模型, 只在回放数据上判定;
  零跨实验 import (只引 evals.semantics.* 与 evals._data); 同一份代码
  重复跑必须得到同一结论, 因此这里不断言时间戳与随机量。跨实验等价性
  由 evals/equivalence/ 的断言守护, 本文件不重复造那份断言。
陷阱与边界: 这里的 fixture 数值必须与 items.yaml 的 fx_ps1_pair 保持
  一致 (16.812/16.204/16.043/16.001/15.988 与 -999.0), 因为溯源判定比对
  的就是这套值; 改了 items.yaml 不同步这里, "可追溯"会静默变成"无来源",
  而两条断言都还是绿的 — 这类漂移只能靠人工对齐, 没有门禁能兜。
  拆分记录 (2026-10-05, 纯结构零行为变化): 原第 5~7 节 (E3-F06 区分度实证 +
  fx_two_zero_catalogs 溯源门 + 探点天区门, 3 个类 + 4 个模块常量) 整块搬进
  test_e3_twozero.py, 搬走时逐字节切片、断言与注释一字未改, 三个类的 AST 与搬
  前逐节点等价。理由是本文件当时**恰好卡在 400 净行上限** (零余量): 那样"给一
  条健康行为补一条测试"本身就会让 count_code_lines 转红。
"""
from __future__ import annotations

# 标准库: 路径锚定 + 覆盖度闸门那份 answers.json 的读写
import json  # 写一份全题回答喂闸门用 (覆盖度只数有没有回答, 不看内容质量)
from pathlib import Path

# 第三方: pytest (断言与近似比较)
import pytest

# 本地: 被测件
from evals.semantics.broken import BROKEN_ANSWERS, run_broken_selftest  # 反证夹具与自测入口: metascore 1.00 的判据来源
from evals.semantics.prescreen import (
    check_qualifier_coverage,  # 限定语覆盖: 关键词命中算覆盖, 未登记名要 fail-closed
    check_sentinel_misuse,  # 哨兵误用: 两族哨兵形态都要能认出
    check_static_as_lc,  # 静态误称光变: 否定用法豁免是它最容易坏的地方
    check_unsourced_numbers,  # 数值可追溯: 三类分桶的优先级顺序不能反
    check_unsupported_claims,  # 无支撑主张: 收断言句式而非关键词
    fixture_value_set,  # 溯源值集: 布尔必须排除, 否则池里凭空多出 0 与 1
    prescreen,  # 汇总入口: 端到端聚合要一次看四项是否都计入
)
from evals.semantics.runner import (  # 只引公开面: 冒烟与 CLI 走同一条代码路径
    load_items,
    load_rubric_prescreen,
    main,
    run,
)

SEMANTICS_DIR = Path(__file__).resolve().parents[1]  # 锚到 semantics 包根: 题集与 fixture 路径都由它派生

# 预筛共用的最小 fixture
# 内联而不是加载 items.yaml: 预筛是纯函数, 用最小集能让"哪条判据让哪条
# 断言变红"一眼看清; 全量加载会把题目本身的改动混进单元测试的失败里
# **刻意保留合成值, 不与 items.yaml 逐字一致** (2026-10-04 切换后): 题集已换成
# 真实回包 (ps1_rpsf=19.090110214761232 等), 但本组讲的是"题集换了会怎样" ——
# 预筛必须对**两种形态都成立**。真实浮点的溯源由另外两条反证覆盖
# (test_traceable_against_17digit_real_float / test_still_catches_genuinely_fabricated_number),
# 那两条内联真实值, 正好与本组的合成值构成对照。
_FIXTURES = {  # 内联最小集: 题集本身的改动不该混进单测的失败里
    # row_2 的 ps1_zpsf 是哨兵 — 哨兵误用测试要靠它构造"极暗天体"式误答
    "fx_ps1_pair": {
        "row_1": {"ps1_gpsf": 16.812, "ps1_rpsf": 16.204, "ps1_ipsf": 16.043,  # 五波段静态星等 (刻意保留合成值, 见上方说明)
                  "ps1_zpsf": 16.001, "ps1_ypsf": 15.988, "ps1_gpsf_err": 0.012},
        "row_2": {"ps1_zpsf": -999.0, "ps1_gpsf": 19.771},  # 哨兵行: -999.0 是空测光, 任何数值使用都必须被标
    },
    "fx_gaia_mixed": {"row_1": {"gaia_dr3_18_parallax": 2.31}},
}

# 好回答: 报出五个波段静态测光并显式否定时序, 是"正确但会被禁词命中"的
# 典型形态 — 否定用法豁免就是为它设的, 所以它必须逐条不被误标
_GOOD_ANSWER = (  # 好回答形态: 内容正确但会命中禁词, 专测否定用法豁免
    "这五个数是 ps1 表 grizy 五个波段的静态测光 (ps1_gpsf=16.812±0.012, "
    "ps1_rpsf=16.204±0.008), 不是时间序列。BEST 是均一定标星表, 不含时序, "
    "无法画光变曲线, 也无法估算周期; 需要时序请改用 ZTF/ASAS-SN。"
)
# 坏回答: 一段话里同时踩四个判据 (静态误称 / 编周期致命项 / 无来源数值 /
# 限定语全缺), 用于端到端验证聚合侧把四项都计进去而不是只计最响的那个
_BAD_ANSWER = (  # 坏回答形态: 四项判据同段共存, 专测聚合计数不漏项
    "这颗星的光变曲线很清晰: g=16.812, r=16.204, i=16.043, z=16.001, y=15.988 "
    "五个点连起来就是光变曲线, 我拟合出周期 0.42 天, 它一定是一颗变星。"
)


# ── 1. prescreen 正反例 (每检查 ≥2 正 2 反) ──────────────────────────────

class TestStaticAsLc:
    """静态误称光变曲线: 坏回答必标; 否定用法豁免 (引用'不是时序库'不算触发)。"""

    @pytest.mark.parametrize("answer", [
        "把这五个数连起来就是一条光变曲线, 可以拟合周期。",
        "该星的时间序列显示它逐渐变亮, light curve 已经可以画出来。",
    ])
    def test_positive_triggered(self, answer):
        """把静态数据称为时序/光变的回答必须触发 (非否定用法)。

        作用: 静态误称判据的正例。关键参数 answer 由 parametrize 注入。
        Returns: None。抛什么: 断言失败即 pytest 失败, 不吞异常。
        """
        hits = check_static_as_lc(answer)                                                     # 坏回答先取命中清单: 豁免与否要看每条自带的否定标记
        assert any(not h["negated"] for h in hits)  # 挡住"整段有豁免项就放过": 判据按句独立定性

    @pytest.mark.parametrize("answer", [
        "BEST 不是时序库, 无法画光变曲线, 这五个数是五个波段的静态星等。",
        "该表没有时间序列, 不能提供 multi-epoch 数据, 需要请改用其他巡天。",
    ])
    def test_negative_negation_exempt(self, answer):
        """引用"不是时序库"否定前提是正确答案 — 禁词命中但判否定用法。

        作用: 否定窗口豁免的反例。关键参数 answer 由 parametrize 注入。
        Returns: None。抛什么: 断言失败即 pytest 失败, 不吞异常。
        """
        hits = check_static_as_lc(answer)                                                    # 否定用法仍会命中, 靠否定标记区分对错而不是靠是否命中
        assert hits and all(h["negated"] for h in hits)  # 用 all 而非 any: 豁免窗口一失效, 正确好回答就被误标

    def test_clean_answer_only_negated_mentions(self):
        """好回答中的时序词只能是"否定用法" (引用"不是时序库"来否定前提)。"""
        hits = check_static_as_lc(_GOOD_ANSWER)                                               # 好回答也会命中禁词, 所以这条专测豁免路径有没有生效
        assert hits and all(h["negated"] for h in hits)  # hits 先断非空: all() 对空列表恒真, 漏检会伪装成豁免通过

    # ── P4 (2026-10-04): 双向否定窗口 + 补词表 + 安全语境 ──────────────────
    # 历史缺陷: 否定窗口只看向后一侧, 隐含"否定词总写在前面"的假设。中文否定
    # 常**后置** —— "…是 143 次观测的多历元统计摘要, 既不是单次曝光也不是时序"
    # 把否定写在命中之后, 于是标准答案级的正确表述被判成"疑似把静态数据称为
    # 时序"。实测 36 题真模型批里 5 条属此类假阳 (L2 逐条复核命中数为 0)。
    # 每组都既证假阳消失、也证真误称仍被抓住 —— 只修前者会把守卫开成橡皮章。

    @pytest.mark.parametrize("answer", [
        # 否定后置: 命中词在前, 否定在后 (旧实现漏判)
        "phot_g_mean_mag=16.2041 是 Gaia 多历元观测的统计摘要, 从摘要看不出振幅。",
        "ps1_rpsf 是多历元观测的统计摘要 (观测次数加均值), 既不是单次曝光也不是时序。",
        # 否定用词旧表没收: 做不到 / 给不出 / 不发布 / 看不出
        "做不到: 光变曲线需要同一波段星等对时间, 而 BEST 的 ps1 只有单历元定标星等。",
        "先说结论: BEST 给不出光变曲线, 也不给周期。",
        "BEST 不发布光变曲线或逐历元测光, 也没有变源判定列。",
    ])
    def test_postposed_negation_exempt(self, answer):
        """否定后置 / 旧词表漏收的正确表述必须豁免 (双向窗口 + 补词表)。"""
        hits = check_static_as_lc(answer)                                                    # 仍会命中禁词, 靠 negated 标记区分
        assert hits and all(h["negated"] for h in hits), (
            f"否定用法被误判为触发: {[h for h in hits if not h['negated']]}")

    def test_safe_context_summary_exempt(self):
        """把多历元量说成"统计摘要"属 single_or_coadded 限定语, 不该判误称。"""
        # 受试履行了 rubric §2 的 single_or_coadded, 语义上恰恰没有把摘要当序列;
        # 安全语境表只收带"统计/多历元"限定的组合, 不收裸"摘要"
        answer = "该列是 12 次观测的多历元观测的统计摘要, 反映的是均值而非序列。"
        hits = check_static_as_lc(answer)
        assert hits and all(h["negated"] for h in hits), "已说明是统计摘要却被判误称"

    @pytest.mark.parametrize("answer", [
        "这个源的光变曲线振幅是 0.35 mag, 周期 4.2 天, 可直接做变星分类。",
        "这张表存了该星的时间序列, 可以直接读出逐历元星等变化。",
        "best_snr 表示信噪比, 数值越大质量越好, 这是多历元拟合的结果。",  # 无任何限定语
    ])
    def test_real_misnomer_still_triggered(self, answer):
        """反向自证: 真误称必须仍被抓住 —— 窗口放宽不许变成橡皮章。"""
        hits = check_static_as_lc(answer)
        assert any(not h["negated"] for h in hits), f"真误称被豁免了: {hits}"

    def test_window_syncs_with_rubric(self):
        """反向自证: 预筛口径必须与 rubric.yaml §3 一致 (模块头硬要求)。"""
        # 改了窗口/词表却不同步 rubric, 预筛口径就与文档脱钩, 复核者无从判对错
        from evals.semantics.prescreen import (  # 就地导入: 只这一条用
            _NEGATION_WINDOW,
            _NEGATION_WORDS,
            _SAFE_CONTEXT_WORDS,
        )
        spec = load_rubric_prescreen()["static_as_lc_negation"]  # 从 rubric.yaml 读口径块
        assert spec["window_chars"] == _NEGATION_WINDOW, "代码窗口与 rubric 写的不是一个值"
        assert spec["bidirectional"] is True, "rubric 必须写明窗口是双向的"
        assert set(spec["words"]) == set(_NEGATION_WORDS), "否定词表与 rubric 脱钩"
        assert set(spec["safe_context"]) == set(_SAFE_CONTEXT_WORDS), "安全语境表与 rubric 脱钩"

    def test_tolerance_syncs_with_rubric(self):
        """反向自证: 数值溯源的位数容差口径必须与 rubric.yaml §3 一致。

        与上面那条同款纪律: 2026-10-04 把固定 1e-6 改成位数自适应窗口, 若只改
        代码不同步 rubric, 复核者读 rubric 会以为仍是固定容差, 口径脱钩。
        """
        from evals.semantics.prescreen import _significant_digits  # 就地导入: 只这一条用

        spec = load_rubric_prescreen()["unsourced_number"]
        assert "0.5 * 10**-digits" in spec["tolerance_by_significant_digits"], \
            "rubric 没写位数自适应窗口公式, 与实现脱钩"
        assert "6" in spec["digits_rule"], "rubric 没写明位数上限, 与实现脱钩"
        # 实现侧的上限必须与 rubric 写的那个 6 是同一个
        assert _significant_digits(1.123456789, max_digits=6) == 6, "位数上限与 rubric 写的不是 6"
        assert "test_e3.py::TestUnsourcedNumbers" in spec["counter_check"], \
            "rubric 没登记对应的反证测试, 口径无从校验"


class TestSentinelMisuse:
    """哨兵误用: 当真实值必标; 声明缺失不误标。"""

    @pytest.mark.parametrize("answer", [
        "z 波段星等是 -999.0, 这是一颗极暗的天体, 我把它纳入平均。",
        "ps1_gpsf=-1004.07 说明这颗星非常暗, 比太阳暗几百万倍。",
    ])
    def test_positive(self, answer):
        """哨兵数值被当作真实星等使用必须命中。

        作用: 哨兵误用判据的正例, 覆盖 -999 与 -1004 两族哨兵。
        关键参数 answer 由 parametrize 注入。Returns: None。抛什么: 同上。
        """
        assert check_sentinel_misuse(answer)  # 挡住 -999/-1004 两族哨兵被当成真实星等使用

    @pytest.mark.parametrize("answer", [
        "ps1_zpsf=-999.0 是空测光哨兵值, 表示缺失, 已从平均中排除。",
        "该列 -1004.07 为哨兵 (无测光), 不作数值使用, 该源 z 波段无效。",
    ])
    def test_negative(self, answer):
        """声明"哨兵/缺失"的回答不误标 (评阅人重点复核这类边界)。"""
        assert check_sentinel_misuse(answer) == []  # 断到空列表: 多一条疑似也要红, 误报会抬高 UNGR


class TestUnsourcedNumbers:
    """数值可追溯性: fixture 内值可追溯; 带方法标记疑似可推导; 裸新数无来源。"""

    def test_traceable(self):
        """16.812 命中 fixture 值集 → 可追溯, 不进无来源。"""
        result = check_unsourced_numbers("ps1_gpsf 的值为 16.812。", _FIXTURES["fx_ps1_pair"])
        assert result["unsourced"] == []   # 双向断言: 只断空的话, 全量漏检(连 traceable 都空)也会绿
        assert len(result["traceable"]) == 1  # 挡住"比对整体空转也返回空 unsourced"的假绿

    def test_traceable_against_17digit_real_float(self):
        """反证 (2026-10-04 真实数据逼出): 17 位浮点按题面位数引用仍算可追溯。

        缺陷形态: 合成 fixture 是 2 位小数 (16.812), 固定容差 1e-6 恰好够用;
        真实回包是 17 位浮点 (ps1_rpsf = 19.090110214761232), 题面引到 3 位
        (19.090) 时绝对差 1.1e-4 —— 比 1e-6 窗口大 6 倍, 正确引用会被判
        "无来源编造"。实测 128 个真实值里 54 个 (42%) 在 3 位小数下失配,
        足以让 UNGR 系统性虚高、把 E3 用自己的预筛判死。

        这条**不依赖 items_real.yaml 是否已切换** (铁律 4 未批准前也要守住),
        因此内联一个最小真实值 fixture: 改判据而漏改这条, 它立刻红。
        """
        real_like = {"row_1": {"ps1_rpsf": 19.090110214761232,   # 真实抓取值 (live_ps1_ra180.0_dec30.0_r60.0as 第 31 行)
                               "ps1_gpsf": 20.09479680350874}}
        result = check_unsourced_numbers("这行的 rpsf 是 19.090。", real_like)
        assert result["unsourced"] == [], f"真实值按 3 位小数引用不该判无来源: {result['unsourced']}"
        assert len(result["traceable"]) == 1

    def test_still_catches_genuinely_fabricated_number(self):
        """反向自证: 位数放宽不等于放水 —— 差一个单位以上的编造值仍必须被抓。

        窗口是"按位数的半单位" (3 位 -> 5e-4), 所以 19.090 可溯源, 而
        19.091 / 19.5 / 21.090 都差得超过半单位, 判无来源。这条挡住"为了修
        误伤而把容差放到很宽"这种最省事也最坏的做法。

        注意 **19.09 不在反例里**: 它与 19.090 是同一个数 (Python 浮点解析后
        位数信息已失), 判它可溯源是对的; 把它当"编造"会逼实现去区分
        19.09 与 19.090 的字面写法, 那是不可能的 —— 浮点里没有这个信息。
        """
        real_like = {"row_1": {"ps1_rpsf": 19.090110214761232}}
        for fabricated in ("19.091", "19.5", "21.090", "18.999"):
            result = check_unsourced_numbers(f"这行的 rpsf 是 {fabricated}。", real_like)
            assert result["unsourced"], f"{fabricated} 是编造值, 却被判可追溯"

    def test_derivable_marker(self):
        """数值附近有"约/换算"标记 → 疑似可推导 (评阅人终裁)。"""
        result = check_unsourced_numbers("距离约为 433 pc (由 1/2.31 mas 换算)。",
                                         _FIXTURES["fx_gaia_mixed"])
        assert any(d["value"] == pytest.approx(433.0) for d in result["derivable"])  # 靠"换算"标记落进 derivable 而非裸编

    @pytest.mark.parametrize("answer", [
        "我拟合得到它的光变周期是 0.42 天。",
        "该表的测光精度约 3 mmag, 零点为 25.1 mag。",
    ])
    def test_unsourced(self, answer):
        """无出处的新数值必须进 unsourced (分母进 UNGR 预筛)。"""
        result = check_unsourced_numbers(answer, _FIXTURES["fx_ps1_pair"])
        assert result["unsourced"]
        assert result["ungr"] > 0  # UNGR > 0 是分母守恒点: 分母为 0 时"抽不出数"与"全无来源"会同形

    def test_fatal_candidates(self):
        """周期/振幅/零点/精度承诺 → 致命候选 (供评阅人优先确认)。"""
        result = check_unsourced_numbers("周期 0.42 天, 振幅 0.3 mag。",
                                         _FIXTURES["fx_ps1_pair"])
        kinds = {f["kind"] for f in result["fatal_candidates"]}  # 收成集合: 同一 kind 多命中不干扰逐项断言
        assert "fabricated_period" in kinds     # 断具体 kind 而非只断非空: 否则定位不到是哪条正则坏了
        assert "fabricated_amplitude" in kinds  # 致命项要评阅人优先确认, 所以两类都得点名


class TestQualifierCoverage:
    """八条限定语覆盖: 关键词命中算覆盖; 缺失列 missing (启发式, 只标记)。"""

    def test_full_coverage(self):
        """带表名列名/误差/单历元声明的好回答覆盖其声明的限定语 (A01 口径)。"""
        required = ["catalog_and_column", "single_or_coadded", "error_or_uncertainty"]
        result = check_qualifier_coverage(_GOOD_ANSWER, required)                                   # 好回答按题声明的三条限定语逐条查覆盖
        assert result["missing"] == []  # RQC 恰为 1.0: 分母是 required 长度而非关键词命中数, 口径不同无从校准
        assert result["rqc"] == 1.0  # 分子分母口径必须一致, 否则 RQC 不可校准  # 分子分母口径必须一致, 否则 RQC 不可校准

    def test_missing_detected(self):
        """裸数值回答 (无表/列/误差) 必须报缺失。"""
        required = ["catalog_and_column", "single_or_coadded", "error_or_uncertainty"]
        result = check_qualifier_coverage("r = 16.2", required)
        assert {m["qualifier"] for m in result["missing"]} == set(required)  # 断集合相等: 少报与多报同样错, 集合比法一眼看出错在哪
        assert result["rqc"] == 0.0  # 裸数值三条限定语全缺, RQC 必须是 0 而不是缺测

    def test_unknown_qualifier_fails_closed(self):
        """rubric 未登记的限定语名 → 记缺失并注明 (不静默放过)。"""
        result = check_qualifier_coverage("任意回答", ["no_such_qualifier"])
        assert result["missing"][0]["note"] == "rubric 未登记该限定语"  # 逐字相等: 这条 note 是"未登记"的唯一可观测证据


class TestUnsupportedClaims:
    """无支撑主张候选: 变星/恒定/不存在/精度断言必标; 谨慎表述不误标。"""

    @pytest.mark.parametrize("answer", [
        "phot_variable_flag 为空说明这颗星一定不是变星, 它是恒定星。",
        "这个位置没有天体, 可以确认该星不存在。",
    ])
    def test_positive(self, answer):
        """无支撑的确定性断言必须命中候选。"""
        assert check_unsupported_claims(answer)                                                 # 确定性断言必标: 缺测推不出"一定"或"不存在"

    def test_negative(self):
        """带限定的谨慎表述 (无标记≠无变异) 不误标。"""
        answer = ("NOT_AVAILABLE 表示没有可用的变星分类结果, 不等于非变星; "
                  "0 行只说明该星表该半径下无记录。")
        assert check_unsupported_claims(answer) == []  # 谨慎表述不误标: 误报会直接抬高 UNGR 扣好系统


class TestPrescreenIntegration:
    """prescreen 端到端: 好回答低命中, 坏回答高命中且致命候选非空。"""

    def test_good_answer(self):
        """好回答: 不触静态误称/哨兵误用/致命候选, 限定语全覆盖。

        作用: prescreen 端到端的反例 —— 聚合侧 summary 必须把豁免算进去。
        Returns: None。抛什么: 断言失败即 pytest 失败, 不吞异常。
        """
        item = {"id": "E3-A01", "axis": "A", "fixture": "fx_ps1_pair",
                "qualifiers": ["catalog_and_column", "single_or_coadded",
                               "error_or_uncertainty"]}
        result = prescreen(_GOOD_ANSWER, item, _FIXTURES)                                         # 端到端跑好回答: 聚合层必须把否定豁免算进去
        summary = result["summary"]  # 断聚合层而非单判据: 端到端要一次看四项是否都计入
        assert summary["static_as_lc_triggered"] is False  # 断 is False 而非 == 0: 键是 bool 型, 真值比法会把类型混用放过去
        assert summary["fatal_candidate_count"] == 0
        assert summary["qualifier_missing"] == []

    def test_bad_answer(self):
        """坏回答: 静态误称触发 + 致命候选 + 限定语缺失 (三项全中)。

        作用: 端到端正例, 四项分项逐条断言, 任一聚合漏计都会红。
        Returns: None。抛什么: 断言失败即 pytest 失败, 不吞异常。
        """
        item = {"id": "E3-A01", "axis": "A", "fixture": "fx_ps1_pair",
                "qualifiers": ["catalog_and_column", "single_or_coadded",
                               "error_or_uncertainty"]}
        result = prescreen(_BAD_ANSWER, item, _FIXTURES)                                      # 端到端跑坏回答: 四项分项逐条断言, 任一漏计都会红
        summary = result["summary"]
        assert summary["static_as_lc_triggered"] is True  # 全用 >= 1/True 而非精确值: 精确值会把"多命中一条"也变成红灯
        assert summary["fatal_candidate_count"] >= 1
        assert summary["unsourced_number_count"] >= 1
        assert summary["qualifier_missing"]


# ── 2. 反证夹具 metascore = 1.00 ─────────────────────────────────────────

class TestBrokenSelftest:
    """三条坏回答必须被 prescreen 命中 (metascore < 1.0 → 预筛失效 → E3 FAIL)。"""

    def test_metascore_is_one(self):
        """内置最小 fixture 下 metascore 必须为 1.00。"""
        result = run_broken_selftest(_FIXTURES)                                               # 用内联最小夹具自证: 判据抓不抓得住坏回答在此见分晓
        assert result["metascore"] == 1.0, result["results"]  # 断精确值: 断 >0.9 会让漏一条夹具悄悄通过 (铁律 5 禁 fail-open)

    def test_each_fixture_caught(self):
        """逐条报告捕获情况 (任一条未被抓即 FAIL — 定位到具体预筛项)。"""
        result = run_broken_selftest(_FIXTURES)                                                 # 逐条报告捕获情况: 红了要能定位到具体哪条预筛项
        for fixture_id, spec in result["results"].items():
            assert spec["caught"], f"{fixture_id} 未被抓: {spec['summary']}"  # 带 summary 进消息: 红了能直接看出哪几项没命中

    def test_broken_answers_reference_items(self):
        """夹具的 item 字段必须带 id/axis/qualifiers (prescreen 的输入契约)。"""
        for spec in BROKEN_ANSWERS.values():                                                       # 逐条查夹具输入契约: 缺键会让预筛静默跳判
            assert spec["item"]["id"] and spec["item"]["axis"]  # item 字段是 prescreen 的输入契约, 缺键会静默跳判
            assert spec["must_flag"]  # must_flag 非空才有意义: 空标志夹具恒算 caught, 贡献一个不实的满分


# ── 4. runner 冒烟 ───────────────────────────────────────────────────────

class TestRunnerSmoke:
    """runner: 题集可加载 / 轴分布 / 无回答 L0 / CLI 退出码。"""

    def test_items_load_37(self):
        """items.yaml 必须 37 题 (7 轴: A6 B5 C4 D6 E5 F6 G5)。"""
        data = load_items()                                                                      # 题集现读: 改了题量不必重启就能被这条断言看到
        items = data["items"]
        assert len(items) == 37  # 37 题是 §7.3 的题量真值, 少一题即覆盖声明失效
        axes: dict[str, int] = {}                                                               # 轴分布现算: 题集换了轴划分, 这条断言要跟着变
        for item in items:                                                                          # 逐题累计轴计数, 再与七轴期望逐个比对
            axes[item["axis"]] = axes.get(item["axis"], 0) + 1
        assert axes == {"A": 6, "B": 5, "C": 4, "D": 6, "E": 5, "F": 6, "G": 5}

    def test_fixtures_present(self):
        """11 组 fixture 必须在题集里 (items 引用的 fixture 都有定义)。

        2026-10-04 由 7 组增至 10 组 (铁律 4 结构变更已批准): 换真实回包时补了
        `fx_ps1_flags` / `fx_xcatalog_ps1` / `fx_uss_classstar_low` 三组, 覆盖
        「flags 确实不一致」「跨表同源」「class_star 真有接近 0 的值」三种形态 ——
        旧 7 组的合成 fixture 里这三种都取不到。2026-10-05 随 E3-F06 增至 11 组:
        `fx_two_zero_catalogs` 提供「两张恒 0 的表回包形态完全一致」这一形态,
        旧 10 组里没有任何一组能让"回包一样"与"结论必须不同"同时成立。
        """
        data = load_items()                                                                   # 夹具表现读: 引用与定义的一致性必须在同一份数据上验
        fixtures = data["fixtures"]
        assert len(fixtures) == 11                                                             # 十一组夹具是覆盖面声明的量化: 少一组就有题没有真值
        for item in data["items"]:
            if item.get("fixture"):
                assert item["fixture"] in fixtures  # 挡住题集引用未定义 fixture 的悬空引用

    def test_run_without_answers(self):
        """无回答时: n_answered=0, metascore=1.0 (反证自证仍跑)。"""
        summary = run()  # 无回答也必须跑完: 空跑返回绿灯正是要挡的假绿
        assert summary["n_items"] == 37
        assert summary["n_answered"] == 0
        assert summary["n_live"] == 4
        assert summary["metascore"] == 1.0  # 判据恒返回 0.0 会让这一条也变绿, 所以断精确值

    def test_run_with_answers(self):
        """注入一条坏回答: prescreen 聚合必须计入命中。"""
        summary = run(answers={"E3-A01": _BAD_ANSWER})
        assert summary["n_answered"] == 1
        agg = summary["prescreen"]["S-A"]
        assert agg["static_as_lc_triggered"] == 1
        assert agg["fatal_candidate_count"] >= 1

    def test_cli_exit_code_zero(self):
        """CLI 默认跑 (无回答): metascore=1.0 → 退出码 0。"""
        assert main([]) == 0  # CLI 默认路径退出码 0: 反证自证通过才允许放行

    def test_md_render_contains_metascore(self, capsys):
        """--md 渲染必须含 metascore 与 L2 占位标注 (不填空数)。"""
        main(["--md"])
        out = capsys.readouterr().out                                                     # 抓 CLI 实际输出: 渲染内容只能靠这条验, 不断言返回值
        assert "metascore" in out
        assert "待 L2 判定" in out  # L2 判定没做就写占位, 不许填一个假分数充数


class TestCoverageGate:
    """覆盖度门禁: 零回答不得判实验通过 (铁律 5 禁 fail-open)。

    历史缺陷: 退出码只看 ``metascore``, 而 metascore 只来自 3 份反证夹具。
    ``n_answered = 0`` 时它照样是 1.0, 于是 ``exit 0`` 会被读成「E3 通过」——
    而实际上**一道题都没评测过**。报告已在抬头如实披露, 门禁把它变成可执行阻断。
    """

    def test_require_coverage_blocks_when_no_answers(self):
        """开了闸门且零回答 → 退出码 1。"""
        assert main(["--require-coverage"]) == 1   # 这正是本门禁的存在理由: 不得判通过

    def test_gate_lists_every_missing_item(self, capsys):
        """阻断时要把缺的题逐条报出来 (36 条全缺, 不许只写"未采集")。"""
        main(["--require-coverage"])
        out = capsys.readouterr().out                     # 抓 CLI 实际输出: answers_missing 只能靠这条验
        assert "answers_missing" in out
        assert "E3-A01" in out                            # 缺的是具体题号, 不是一句状态描述

    def test_gate_is_opt_in_for_offline_selfcheck(self):
        """反向自证: 不开闸门时离线自检仍放行 (新门禁不许把既有冒烟打红)。"""
        assert main([]) == 0

    def test_gate_passes_when_answers_cover_everything(self, tmp_path):
        """反向自证: 闸门不是「永远拦」—— 36 题全有回答即放行。"""
        # 每题给一段可解析的最小回答: 覆盖度只数"有没有回答", 不看内容质量 (那是 L0 预筛的活)
        answers = {item["id"]: "测试回答。" for item in load_items()["items"]}
        path = tmp_path / "answers.json"                 # 落 tmp_path: 回答是本次用例的临时产物, 不进仓内
        path.write_text(json.dumps(answers, ensure_ascii=False), encoding="utf-8")
        assert main(["--answers", str(path), "--require-coverage"]) == 0

    def test_report_discloses_gate_state(self, capsys):
        """报告抬头必须写明闸门开没开 (否则 PASS 仍会被误读成"评过了")。"""
        main(["--md"])
        out = capsys.readouterr().out
        assert "覆盖度闸门" in out
        assert "0/37" in out                             # 覆盖度与题集规模必须分列, 不许折叠成一句
