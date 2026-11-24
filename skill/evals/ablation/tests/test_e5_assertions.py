# -*- coding: utf-8 -*-
"""evals.ablation.tests.test_e5_assertions — critical 断言表示归一的承重断言。

为什么单列一份 (2026-10-10): ``gate_E`` 的 critical 判据从"裸子串"改成"表示归一 +
显式变体"是一次**判定口径变更**, 必须有断言把两侧都钉住:
  * 该救回的 (同一事实的不同写法) 必须救回;
  * 不该放过的 (压根没说的事实) **必须继续判缺** —— 这是防"把判据改成摆设"的负对照。
"""
from __future__ import annotations

# 标准库: 断言用不到额外依赖
import pytest  # 只为 pytest.raises 一条: 非法形态必须当场抛

# 本地: 被测匹配层
from evals.ablation.metrics.assertions import canonicalize, concepts, match_critical


class TestCanonicalize:
    """字符层与数值层归一。"""

    def test_fullwidth_and_case_folded(self):
        """全角字符与大小写都归一 (模型常把 TRUE/（）写全角)。"""
        assert canonicalize("ＴＲＵＥ") == canonicalize("true")   # 全角大写 ≡ 半角小写

    def test_quotes_are_typographic_only(self):
        """引号/强调符只影响排版: 剥掉后应能命中。"""
        assert canonicalize("不等于『非变星』") == canonicalize("不等于非变星")   # 引号被剥掉

    def test_number_trailing_zeros_folded(self):
        """数值尾零不承载信息: 18.20 ≡ 18.2。"""
        assert canonicalize("rpsf=18.20") == canonicalize("rpsf=18.2")   # 尾零归一

    def test_whitespace_collapsed(self):
        """换行与多空格折叠成一个空格 (答案常带换行)。"""
        assert canonicalize("3   行\n结果") == canonicalize("3 行 结果")   # 空白折叠


class TestConcepts:
    """计数与截断布尔的量纲归一 (不合并不同量纲)。"""

    def test_row_units_unify(self):
        """行 / 个源 / 条 都指结果行数, 归一到同一概念。"""
        assert concepts("共 3 个源") == concepts("3 行")   # 两种写法同概念
        assert "count:rows=3" in concepts("命中 3 条")      # 第三条写法也认

    def test_dimensions_do_not_merge(self):
        """量纲严格分开: 行 ≠ 页 ≠ 次, 否则会造出假通过。"""
        assert concepts("2 页") != concepts("2 行")                      # 页与行不合并
        assert "count:pages=2" in concepts("约 2 页")                     # 页数概念独立
        assert "count:epochs=12" in concepts("共 12 次观测")              # 次数概念独立

    def test_truncation_both_notations(self):
        """``truncated=false`` 与 ``未截断`` 是同一个事实。"""
        assert concepts("truncated=false") == concepts("本轮未截断")   # 字面量 ≡ 中文短语
        assert concepts("truncated=true") == concepts("结果已截断")     # 同理另一边


class TestMatchCritical:
    """命中判定: 表示可换, 事实不可缺。"""

    def test_paraphrase_hits(self):
        """实测踩到的三类表示差异都要命中。"""
        # 计数单位: 「共 3 个源」要顶得住断言 "3 行"
        assert match_critical("共 3 个源", ["3 行"])["missing"] == []   # 概念级命中
        # 截断记法: 「未截断」要顶得住断言 "truncated=false"
        assert match_critical("返回 3 行，未截断。", ["truncated=false"])["missing"] == []   # 同上
        # 引号插入: 「不等于『非变星』」要顶得住断言 "不等于非变星"
        assert match_critical("既不等于『非变星』", ["不等于非变星"])["missing"] == []   # 字符层归一

    def test_genuine_omission_still_fails(self):
        """**负对照**: 压根没说的事实必须继续判缺 (防判据变摆设)。"""
        verdict = match_critical("半径 60″ 内按 r 波段升序取回 2 行。",
                                 ["ps1_rpsf", "BEST_SIM_0001", "18.20"])   # 三样断言
        # 三样都没说: 该答案只讲了"r 波段", 没给列名 ps1_rpsf、没给 id、没给星等数值
        assert verdict["missing"] == ["ps1_rpsf", "BEST_SIM_0001", "18.20"], "没说的事实被放过了 = 判据失效"
        assert set(verdict["missing_strict"]) >= {"BEST_SIM_0001", "18.20"}   # 严格侧同步报缺

    def test_wrong_number_is_not_merged(self):
        """数字不同不算同一个事实 (归一不得把 3 与 4 混为一谈)。"""
        assert match_critical("命中 4 行", ["3 行"])["missing"] == ["3 行"]   # 数字必须对上

    def test_any_of_declares_semantic_variants_explicitly(self):
        """语义近义只能**显式声明**, 不靠模糊匹配猜。"""
        assertion = {"any_of": ["不支持", "做不了", "做不到"]}   # 显式变体清单
        assert match_critical("这条做不了（NO_TIME_SERIES）", [assertion])["missing"] == []   # 声明内命中
        # 声明之外的写法仍判缺: 没声明的近义不许自动命中
        assert match_critical("此需求超出能力范围", [assertion])["missing"] != []   # 未声明即缺

    def test_strict_reading_is_reported_separately(self):
        """严格读数单独返回: 报告要能把它与归一读数一起披露。"""
        verdict = match_critical("共 3 个源", ["3 行"])   # 同一份输入看两套读数
        assert verdict["missing"] == []                 # 归一: 事实说到了
        assert verdict["missing_strict"] == ["3 行"]     # 严格: 逐字没复述模板

    def test_illegal_assertion_shape_is_rejected(self):
        """非法形态当场抛 (fail-closed), 不静默当空断言放过。"""
        with pytest.raises(ValueError):   # 形态非法必须抛, 不许静默
            match_critical("任意答案", [{"unknown_key": "x"}])   # 无 any_of/text 的映射
