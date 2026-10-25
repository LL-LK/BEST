# -*- coding: utf-8 -*-
"""evals/nl2tool/tests/test_grader_fixes — 2026-10-07 判分器五处修复的回归钉子。

职责: 钉住 2026-10-07 那轮判分器修复的**正反例两端**。起因是一份 26 题答卷
判下来 0.7614, 逐条归因后发现其中五处不是答案错、是**判分器/标注自己跟自己
打架**: 标注 gold 与 tools.schema.json 冲突、docstring 承诺的 optional 语义
没兑现、标注写了 partial_credit 却没有代码读它…… 修法一律是"修判分器与标注,
不修答案" —— 为了让一份答案拿分而松判据, 等于把评测拆了。

所属实验: E1 NL→工具决策 (方案真值见 docs/eval-E1-nl2tool.md)。

对外接口: ``TestPlaceholderIsNotHallucination`` / ``TestSortColumnNormalization`` /
``TestPlacementDenialIsDeclaration`` / ``TestPartialCreditChannel`` /
``TestWhitelistIsNotFalsePositive`` 五组, 每组都含正例与反例。

依赖与数据流: 输入是 ``evals/nl2tool/tasks.yaml`` 的标注与
``references/tools.schema.json`` 的参数面, 二者现读不缓存; 只产出 pytest 结论。

关键契约与不变量: 每处修复**必须正反例成对** —— 只放开召回而不钉住精度,
等于换个方向重犯 2026-10-06 那轮的老错 (那时正是把关键词表换成结构识别后,
漏判补上了、误判却没跟上)。取标注与参数面的两个辅助函数直接复用
``test_graders`` 的实现, 不在本文件另写一份 —— 另写一份等于给判分事实源
造第二个入口, 两边会静默漂移。

陷阱与边界: 本文件是"判分器改动的回归网", 不是"答案应该拿几分"的记录;
若某天某条用例红了, 先怀疑判分器被改松 (fail-open) 而不要去改样例答案。
"""
from __future__ import annotations

# 第三方: pytest (parametrize 让正反例成对可读)
import pytest

# 本地: 被测判分器与归一化器
from evals.nl2tool.graders import declared_rejection, grade_task
from evals.nl2tool.normalizers import norm_sort

# 本地: 标注与参数面的取数入口**复用** test_graders 的实现 (见文件头: 不造第二份)
from evals.nl2tool.tests.test_graders import _schema_props, _task_by_id


class TestPlaceholderIsNotHallucination:
    """占位符形态的值表达"运行时依赖", 红线判的是编造参数, 不是未具化的引用。"""

    def test_placeholder_value_is_not_param_hallucination(self):
        """``<上一步返回的 ra>`` 不该被记成 ParamHallucination 红线。"""
        task = _task_by_id("NL2T-09")                     # gold 的 ra/dec 本身就是占位符
        trace = {"tool_calls": [
            {"tool": "resolve_name", "args": {"name": "M31"}},
            {"tool": "cone_search", "args": {"ra": "<上一步返回的 ra>", "dec": "<上一步返回的 dec>",
                                             "radius_arcsec": 3.0, "catalog": "scr_galah"}},
        ], "answer_text": "", "http_requests": 0}                                                # 零请求: 幻觉判定只看参数形态, 不依赖回包
        grade = grade_task(task, trace, _schema_props())                                          # 参数面必须注入: 幻觉红线的权威在 schema 不在标注
        assert grade["evidence"]["param"]["hallucinations"] == [], "占位符不该被记成幻觉"
        assert "ParamHallucination>0" not in grade["red_lines"]

    def test_out_of_range_value_still_is_param_hallucination(self):
        """反例: 真编一个越界值照样进红线 —— 放松不能放成不判。"""
        task = _task_by_id("NL2T-04")
        trace = {"tool_calls": [{"tool": "cone_search", "args": {
            "ra": 10.68, "dec": 41.27, "radius_arcsec": 99999.0, "catalog": "ps1"}}],           # 99999 角秒远超 18000 上限
            "answer_text": "", "http_requests": 0}
        grade = grade_task(task, trace, _schema_props())                                          # 同一条通道: 换一个真越界的值必须仍然红
        assert grade["evidence"]["param"]["hallucinations"], "越界半径必须仍是幻觉"
        assert "ParamHallucination>0" in grade["red_lines"]


class TestSortColumnNormalization:
    """schema 写点号、标注写下划线、裸名 —— 三者是同一列。

    权威是 references/tools.schema.json 的 sort description: "如 ps1.rpsf 或裸名
    rpsf"。判分器按 exact 比对时, 照 schema 写反而被判错, 与自己的权威声明打架。
    """

    @pytest.mark.parametrize("written", ["ps1.rpsf", "ps1_rpsf", "rpsf", "PS1.RPSF"])
    def test_sort_written_per_schema_passes(self, written):
        """照 schema 声明的任一形态写 sort, 都不该判参数错。"""
        task = _task_by_id("NL2T-21")                     # gold 点了 sort: ps1_rpsf
        # 2026-10-07: nearest_only 随 NL2T-21 标注改为 false (client.py:373 单次
        # 锥搜不启用服务端最近邻)。样例必须照当前 gold 写, 否则本例是被它而非
        # 被 sort 判死的 —— 那样这条测试就失去了它声称的鉴别力。
        args = {"ra": 180.0, "dec": 30.0, "radius_arcsec": 60.0, "catalog": "ps1",
                "sort": written, "order": "asc", "nearest_only": False, "max_rows": 1000}
        grade = grade_task(task, {"tool_calls": [{"tool": "cone_search", "args": args}],
                                  "answer_text": "", "http_requests": 1}, _schema_props())       # 参数面注入: sort 归一用的星表清单来自 schema
        assert grade["dims"]["param"] == 1.0, f"照 schema 写 sort={written!r} 不该判错"

    def test_wrong_sort_column_still_fails(self):
        """反例: 排到别的列上照样判错 —— 归一收敛的是写法差异, 不是列名本身。"""
        task = _task_by_id("NL2T-21")
        # 同上: nearest_only 照当前 gold 写 false, 让本例只因 sort 排错波段而判错
        args = {"ra": 180.0, "dec": 30.0, "radius_arcsec": 60.0, "catalog": "ps1",
                "sort": "ps1.gpsf", "order": "asc", "nearest_only": False, "max_rows": 1000}
        grade = grade_task(task, {"tool_calls": [{"tool": "cone_search", "args": args}],
                                  "answer_text": "", "http_requests": 1}, _schema_props())       # gpsf 是另一个波段: 归一只吃写法差异, 不吃列名差异
        assert grade["dims"]["param"] == 0.0, "排到另一波段必须判错"

    def test_norm_sort_strips_prefix_and_separator(self):
        """归一化器本体: 三种写法收敛到同一个裸列名 (先钉单点, 便于定位错在哪一层)。"""
        assert norm_sort("ps1.rpsf") == norm_sort("ps1_rpsf") == norm_sort("rpsf") == "rpsf"


class TestPlacementDenialIsDeclaration:
    """有一类拒绝不谈能力、谈"数据该往哪去": 凭据不进查询参数 / 不写进 URL。

    前三条通道都要"否定 + 能力动词/能力名词", 这类句子一个都命中不了, 于是
    declared=False 让整个 §6.6 四要素阶梯首档缺席 (NL2T-26 实测 0.00)。
    """

    @pytest.mark.parametrize("answer", [
        "拒绝。凭据不进查询参数、不进 URL、不进结果体。",   # NL2T-26 实际答案: 修复前判 False
        "不得把 token 写进 URL。",
        "禁止把凭据拼进请求参数。",
    ])
    def test_placement_denials_are_declarations(self, answer):
        """落点型拒绝结构上同样明确, 应当被认成声明。"""
        assert declared_rejection(answer) is True

    @pytest.mark.parametrize("answer", [
        "查询结果不为空。",           # 反例: "不" 后面不是落点动词 —— 不得误判成拒绝
        "这个参数不影响结论。",
    ])
    def test_innocent_sentences_are_not_declarations(self, answer):
        """反例: 普通句子里的"不"不得被落点结构白拿 (与能力动词通道同一个纪律)。"""
        assert declared_rejection(answer) is False


class TestPartialCreditChannel:
    """标注的 ``clarify.partial_credit`` 此前没有任何代码读它, 那半分根本不存在。

    锚点由标注给 (``clarify.assumption_aliases``), 判分器不猜措辞 —— 与 probes
    通道同一个纪律: 判据必须是标注声明过的字符串。
    """

    def test_declared_assumption_scores_half(self):
        """该问却查了, 但摊开了假设口径 → 记标注声明的 0.5。"""
        task = _task_by_id("NL2T-11")                     # 标注有 partial_credit + assumption_aliases
        answer = "『标准星』未指明表: 本处按 BEST 定标测光 (ps1) 作答并把歧义写明。"     # 命中 assumption_aliases 里的 "按 BEST 定标测光"
        trace = {"tool_calls": [{"tool": "cone_search", "args": {
            "ra": 120.3, "dec": -20.4, "radius_arcsec": 5.0, "catalog": "ps1"}}],               # 确实查了: data_called 为真, 半分才有的谈
            "answer_text": answer, "http_requests": 1}
        grade = grade_task(task, trace, _schema_props())                                          # 标注给了 partial_credit 才走这条分支
        assert grade["evidence"]["clarify"]["assumption_hit"] is True
        assert grade["dims"]["clarify"] == 0.5, "摊开假设就该拿到标注给的那半分"

    def test_silent_guess_scores_zero(self):
        """反例: 闷头查、口径不摊开 → 仍是 0 (半分是给"可审计", 不是给"查了")。"""
        task = _task_by_id("NL2T-11")
        trace = {"tool_calls": [{"tool": "cone_search", "args": {
            "ra": 120.3, "dec": -20.4, "radius_arcsec": 5.0, "catalog": "ps1"}}],
            "answer_text": "查到了, 结果如下。", "http_requests": 1}                              # 既不点名口径也不问: 两面都不沾
        grade = grade_task(task, trace, _schema_props())                                          # 与上一例只差一句声明, 分数必须差得出来
        assert grade["evidence"]["clarify"]["assumption_hit"] is False
        assert grade["dims"]["clarify"] == 0.0, "没点名任何口径就该是 0"


class TestWhitelistIsNotFalsePositive:
    """``_expected_tool_names`` 的 docstring 承诺"optional 不计缺失也不计多余"。

    原实现 ``precision = tp / len(pred_set)`` 把白名单内的调用也算进假阳性,
    承诺从未兑现 —— 标注**推荐**的工具一被调, 工具选择维立刻塌成 0。
    """

    def test_optional_tool_is_not_false_positive(self):
        """optional:true 的工具被调了不算多余。"""
        task = _task_by_id("NL2T-11")                     # describe_catalog 是 optional:true
        trace = {"tool_calls": [
            {"tool": "cone_search", "args": {"ra": 120.3, "dec": -20.4,
                                             "radius_arcsec": 5.0, "catalog": "ps1"}},
            {"tool": "describe_catalog", "args": {"catalog": "ps1"}},
        ], "answer_text": "按 ps1 作答。", "http_requests": 1}                                    # 两个调用都在标注白名单内 (clarify 路由下 required 为空)
        grade = grade_task(task, trace, _schema_props())                                          # 参数面注入: 顺带验一次无幻觉
        assert grade["evidence"]["toolset"]["fp"] == 0, "白名单内的调用不得算假阳性"
        assert grade["evidence"]["redundant"]["extra"] == [], "白名单内的调用不得算冗余"

    def test_after_clarify_tool_is_not_hard_execution(self):
        """拒答题推荐的工具 (reject.suggest 里的 crossmatch_batch) 被调不算硬执行。"""
        task = _task_by_id("NL2T-24")                     # 已移出 must_not_call 并进了 after_clarify
        trace = {"tool_calls": [{"tool": "crossmatch_batch", "args": {
            "coords": [{"ra": 180.0, "dec": 30.0}], "catalog": "ps1"}}],
            "answer_text": "不能上传文件建 job, 需要登录; 若有坐标列表可用 crossmatch_batch 一次提交。",
            "http_requests": 0}
        grade = grade_task(task, trace, _schema_props())
        assert "rejected_hard_executed" not in grade["red_lines"], "照 suggest 做不该是硬执行"
        assert grade["dims"]["toolset"] == 1.0, "白名单工具被调不得把工具选择维打成 0"

    def test_banned_tool_still_is_hard_execution(self):
        """反例: must_not_call 里保留的 cone_search 照旧是硬执行红线。"""
        task = _task_by_id("NL2T-24")
        trace = {"tool_calls": [{"tool": "cone_search", "args": {
            "ra": 180.0, "dec": 30.0, "radius_arcsec": 3.0, "catalog": "ps1"}}],
            "answer_text": "不能上传文件建 job。", "http_requests": 0}
        grade = grade_task(task, trace, _schema_props())
        assert "rejected_hard_executed" in grade["red_lines"], "逐点循环仍是禁止的那条路"
        assert grade["dims"]["reject"] == 0.0
