# -*- coding: utf-8 -*-
"""evals/nl2tool/tests/test_graders — E1 归一化器与评分器单测 (含反证夹具自证)。

职责: 钉死 E1 判分链路最底层的两件事 —— 七族归一化器是否把等价的书写
形态收敛成同一个值 (坐标/半径/星表名/列名/波段/数值/集合), 以及评分器
是否会拒绝坏输入而不是悄悄放过; 再用 ``broken/`` 里的反证夹具证明判定器
真的能抓住错误轨迹。

所属实验: E1 NL→工具决策 (方案真值见 docs/eval-E1-nl2tool.md), 直接对应
E1 的放行条件之一: 反证夹具 metascore 必须为 1.0。

对外接口: ``TestNormCatalog``/``TestNormColumn``/``TestNormCoord``/
``TestNormRadius``/``TestNormBand``/``TestNormNumberAndSet`` 六组各给正例
与"归一不了就原样返回"反例; ``TestGraders`` 校验权重和恰为 1、篡改必抛、
未知归一化器名必抛; ``TestBrokenFixtures`` 逐条断言坏轨迹命中声明项,
并汇总 metascore = 1.0。

依赖与数据流: 输入是 ``evals/nl2tool/tasks.yaml`` 的任务标注与
``references/tools.schema.json`` 的工具入参 schema, 二者现读不缓存;
产物只有 pytest 结论, 本文件不写报告。

关键契约与不变量: 全离线回放 —— 判分输入是已落盘的轨迹与标注, 不打真实
站点、不接真实模型, rate_limit 归零, 因此本文件可反复重跑且结果稳定;
归一化失败一律"原样返回或 None", 由调用方判错, 归一化器自身绝不猜值
(无 fail-open); E1 零跨实验 import, 唯一共享件是 ``evals/_data/`` 纯数据
字典, 等价性由 ``evals/equivalence/`` 断言守护。

陷阱与边界: 反证夹具断言的是"必须被抓到", 不是"必须按某种方式抓到" ——  # 金标准轨迹必须判满分: 这是判定器管线的自证
若某天夹具红了, 先怀疑判定器变松 (fail-open) 而不要去删夹具; 归一化器
的正例表只覆盖登记在册的形态, 新增星表别名必须同步进表, 否则它会走
原样返回分支, 在 E1 表现为看似合理的错答。
"""
from __future__ import annotations

# 标准库: 夹具查表 (task_id → 标注)
import json  # 红灯类为空才算放行: 高分但踩红线一样不放
from pathlib import Path

# 第三方: pytest
import pytest

# 本地: 被测归一化器/评分器/反证夹具
from evals.nl2tool.broken import BROKEN_TRACES, metascore, run_broken_selftest
from evals.nl2tool.graders import (  # 拆成两个函数: 后续接真实跑批轨迹时不必改判据
    _ALT_WORDS,  # 兜底词表本体: 近恒真条目 (如"如") 要能被单测钉住
    GRADER_WEIGHTS,  # 权重表本体: 篡改反例要直接改它, 所以必须 import 到手
    check_weight_sum,  # 权重和校验: 正例与篡改反例都调它
    declared_rejection,  # 拒绝声明的结构识别: 本次修正的正例与反例都由它承担
    grade_exact,  # 严格相等档: 工具名与理由码走这一支
    grade_normalized,  # 归一化档: 参数比对的主路径
    grade_task,  # 单任务六维打分: 反证夹具经它判
    match_reason_alias,  # 别名三档比对: 弱档不得退化成近恒真判据
    norm_band,  # 波段归一: 正例覆盖系统名大写与多波段写法
    norm_catalog,  # 星表名归一: 别名与分组路径前缀都要收敛到同一 id
    norm_column,  # 列名归一: 只剥最外层星表前缀, 列内形态不动
    norm_coord,  # 坐标归一: 时分秒与度分秒都要收
    norm_number,  # 数值容差比较: 绝对与相对两个容差位都在这里
    norm_radius,  # 半径归一: 角秒、角分、度三种单位换算
    norm_set,  # 无序集合归一: 通用 set 档按全等比
    norm_set_covers,  # 列投影集合: 标注列必须齐全, 多投影放行
    norm_sort,  # 排序列归一: schema 声明 ps1.rpsf 与裸名 rpsf 同义
)

# 目录锚点: parents[1] 从 tests/ 退回 evals/nl2tool/, 下面拼 tasks.yaml 用
NL2TOOL_DIR = Path(__file__).resolve().parents[1]  # 任务集锚在本实验目录: 测试不跨实验 import (零跨实验 import 铁律)


def _task_by_id(task_id: str) -> dict:  # 按 id 取单题: 归一用例要固定输入, 顺序变化不该影响结论
    """从 tasks.yaml 取一条标注 (反证夹具的判分基准)。

    每次调用现读盘: 标注是本测试的判分事实源, 进程内缓存会在标注热修后
    继续用旧值, 让反证夹具对着过期期望判定, 红灯含义因此变得不可查。
    """
    # 第三方: 任务标注/快照元数据装载 (golden 轨迹生成的事实源)
    import yaml

    data = yaml.safe_load((NL2TOOL_DIR / "tasks.yaml").read_text(encoding="utf-8"))  # 现读 tasks.yaml: 改了任务集不必重启即可被测到
    # 兼容两种 YAML 形态: 顶层带 tasks 键的包装式, 与直接是列表的裸式。
    # 判据只认结构不看写法, 免得有人调整顶层包装就把所有反证测试打空
    tasks = data.get("tasks") if isinstance(data, dict) else data
    # next 而非下标: 夹具引用的 id 不存在时立刻 StopIteration, 属于
    # 夹具自身写错, 不该被静默当成"没这条标注"
    return next(t for t in tasks if t.get("id") == task_id)


def _schema_props() -> dict:  # 参数面: 幻觉与伪造工具名两条红线的唯一权威
    """读 references/tools.schema.json, 抽成 ``{工具名: 入参属性}``。

    每次调用现读盘: 参数面是红线的判分事实源, 缓存会在 schema 热修后继续
    用旧值, 让"参数已下线"的调用照旧判干净。
    """
    # schema 走 NL2TOOL_DIR.parents[1] 退回 evals/ 再进 references/:
    # tools.schema.json 是全仓唯一的工具入参契约, 不在 E1 目录内
    schema = json.loads(                                                                   # 参数面现读: 全仓唯一的入参契约不在 E1 目录内
        (NL2TOOL_DIR.parents[1] / "references" / "tools.schema.json")
        .read_text(encoding="utf-8")
    )
    # 抽成 工具名 -> 入参属性 两级映射, 供 grade_task 逐参数比对;
    # get 默认空字典: 无数入参的工具不该在这里变成 KeyError
    return {                                                                          # 抽成工具名到入参属性两级映射, 供逐参数比对
        t["name"]: t.get("inputSchema", {}).get("properties", {})
        for t in schema.get("tools", [])
    }


# ── 归一化器正反例 (每族 ≥5 组) ──────────────────────────────────────────

class TestNormCatalog:
    """星表名归一: 别名/分组前缀/大小写。"""

    @pytest.mark.parametrize("raw,expected", [  # 大小写与路径前缀都要归一: 用户会写 GAIA_DR3 / std/scr_galah
        ("gaia_dr3", "gaia_dr3_18"),  # 大小写两种写法都归到同一星表: 用户会写 GAIA_DR3
        ("GAIA_DR3", "gaia_dr3_18"),
        ("std/scr_galah", "scr_galah"),  # 路径前缀要剥: std/scr_galah 与 scr_galah 是同一个目标
        ("calib/landolt", "landolt"),
        ("ps1", "ps1"),
    ])
    def test_positive(self, raw, expected):
        """合法写法必须归一到 12 张可查表 id。"""
        assert norm_catalog(raw) == expected  # 正例必须归一到登记 id; 走透传分支的情形由下一条反例管

    @pytest.mark.parametrize("raw", ["ztf", "std", "gaia", ""])  # 认不出的星表名原样透传: 静默改写会让调用方以为归一成功了
    def test_unresolvable_passthrough(self, raw):  # 认不出的原样透传: 静默改写会让调用方以为归一成功
        """无法归一的原样小写返回 (由调用方判错, 不静默映射)。"""
        assert norm_catalog(raw) == raw.strip().lower()  # 原样加小写: 归一不了不等于原封不动, 书写仍要归一


class TestNormColumn:
    """列名归一: 星表前缀双向命中。"""

    @pytest.mark.parametrize("raw,expected", [
        ("scr_galah_rztf", "rztf"),
        ("ps1_gpsf", "gpsf"),
        ("gaia_dr3_18_phot_g_mean_mag", "phot_g_mean_mag"),
        ("rztf", "rztf"),
        ("PS1_Ra", "Ra"),  # 只剥最外层星表前缀, 列内形态不动: PS1_Ra 的 R 不能被小写化
    ])
    def test_positive(self, raw, expected):
        """带前缀与裸名必须归一到同一形态。"""
        assert norm_column(raw) == expected  # 带前缀与裸名收敛到同一个列名, 逐列比对才有着落


class TestNormCoord:
    """坐标归一: 六十进制/度分秒/十进制度。"""

    @pytest.mark.parametrize("raw,expected", [  # 坐标多种书写都要收: 时分秒 / 度分秒 / 冒号 / 裸数
        ("12h30m00s", 187.5),  # 时分秒/度分秒/冒号/裸数都要收: 用户写法差异极大
        ("12 30 00", 187.5),
        ("+20°00′00″", 20.0),
        ("-20:30:00", -20.5),
        (187.5, 187.5),                                                                         # 裸数值原样收: 已经是度数的输入不该被再解析一次
    ])
    def test_positive(self, raw, expected):
        """各书写形态必须化为度数。"""
        assert norm_coord(raw) == pytest.approx(expected)  # approx 而非 ==: 时分秒换算出的 187.5 带浮点尾数

    @pytest.mark.parametrize("raw", ["abc", None, ""])
    def test_unparsable(self, raw):  # 解不出返 None 而不是 0: 0 度是赤经上一个真实存在的位置
        """不可解析返回 None (调用方记失败, 不猜)。"""
        assert norm_coord(raw) is None  # 解不出返 None: 0 度是赤经上一个真实位置, 不能当缺测


class TestNormRadius:
    """半径归一: 角秒/角分/度。"""

    @pytest.mark.parametrize("raw,expected", [  # 角分与角秒都要认: 只认一种会让半径整体差 60 倍
        ("5″", 5.0),
        ("5''", 5.0),
        # 角分与度的两条是本组最容易写错的换算: 角分 ×60 得角秒、度 ×3600
        # 得角秒, 都必须落在 pos.radius 的原生单位上, 否则 E1 会把
        # 5 角分当成 5 角秒判答错 (半径差三个数量级)
        ("5′", 300.0),  # 角分要乘 60: 只认一种单位会让半径整体差 60 倍
        ("5°", 18000.0),  # 角度要乘 3600: 同上, 差的是三个数量级
        (5, 5.0),                                                                                # 裸数值入池: 数值半径已是角秒, 不带单位后缀
    ])
    def test_positive(self, raw, expected):
        """各单位必须化为角秒 (服务端 pos.radius 原生单位)。"""
        assert norm_radius(raw) == pytest.approx(expected)  # 同理: ×60 与 ×3600 之后仍有尾数, 严格相等会假红

    def test_unparsable(self):
        """不可解析返回 None。"""
        assert norm_radius("五") is None  # 解不出的数词返 None, 绝不去猜弧度或弧秒


class TestNormBand:
    """波段标签归一: 系统+波段 → 标准标签。"""

    @pytest.mark.parametrize("system,band,expected", [
        ("ZTF", "g", "ztf.g"),  # 波段随系统大写而变: PS1.r 与 gaia.G 的形态不同
        ("ztf", "r", "ztf.r"),
        ("Gaia DR3", "G", "gaia.G"),
        ("gaia", "BP", "gaia.BP"),
        ("PS1", "r", "ps1.r"),
    ])
    def test_positive(self, system, band, expected):
        """登记在册的组合归一到标准标签。"""
        assert norm_band(system, band) == expected                                              # 登记组合必须归一到标准标签: 波段维靠它逐条比对

    def test_unregistered_passthrough(self):  # 未登记系统原样透传: 猜一个星表前缀会指向不存在的星表
        """未登记组合原样拼回 (BandAcc 判错的依据, 不静默归一)。"""
        assert norm_band("BEST", "u") == "BEST.u"  # 未登记组合原样拼回: 静默归一会把错答洗成对答


class TestNormNumberAndSet:
    """数值容差与无序集合。"""

    @pytest.mark.parametrize("a,b,ok", [
        (180.0, 180.0000000001, True),                                                        # 差 1e-10 判等: 这是浮点表示误差, 不是错值
        (180.0, 180.1, False),                                                              # 差 0.1 判不等: 容差不是橡皮章, 大偏差必须露出来
        ("15.23", 15.23, True),
        ("abc", 1.0, False),
    ])
    def test_number(self, a, b, ok):
        """容差内判等, 容差外判不等, 不可转数判假。"""
        # 两个容差位: 绝对 1e-6 吃浮点表示误差, 相对 0.0 表示不做相对放宽容差
        # (相对容差一开, 大数量级的值会掩盖真实错值, E1 就成了橡皮图章)
        assert norm_number(a, b, 1e-6, 0.0) is ok  # 参数序是 (a, b, atol, rtol): 写反会让差 0.1 的也判等

    @pytest.mark.parametrize("a,b,ok", [
        (["a", "b"], ["b", "a"], True),
        (["a"], ["a", "b"], False),
        ([], [], True),                                                                             # 空集对空集判等: 两侧都没给集合不算判错
    ])
    def test_set(self, a, b, ok):
        """集合无序相等; 元素不同判假。"""
        assert norm_set(a, b) is ok  # 空集对空集判等: 两侧都没给集合不算判错


# ── grader 基础件 ─────────────────────────────────────────────────────────

class TestGraders:
    """三类 grader 与权重校验。"""

    def test_weight_sum_is_one(self):
        """权重和必须恰为 1.00 (启动即校验的纪律本身也要被守住)。"""
        check_weight_sum()                                                                         # 权重和纪律本身也要被守住: 配置漂了当场抛

    def test_weight_sum_check_rejects_tampering(self, monkeypatch):
        """权重被改坏必须抛 ValueError (无 fail-open)。"""
        # 改单项为 0.31 让权重和偏离 1.00; monkeypatch 保证用例结束后
        # 字典复原, 否则这条测试会污染同进程里后续的权重断言
        monkeypatch.setitem(GRADER_WEIGHTS, "toolset", 0.31)  # 0.31 让和偏离 1e-9 容差, 刚好逼出校验分支
        with pytest.raises(ValueError):                                             # 篡改权重必须抛而不是返回错误码: 无 fail-open 的判据才守得住
            check_weight_sum()                                                                   # 越界权重在这里就该炸, 不许等到出报告时才发现

    def test_exact_grader(self):
        """exact: 严格相等 (工具名/枚举/理由码)。"""
        assert grade_exact("cone_search", "cone_search")
        assert not grade_exact("cone_search", "crossmatch_batch")

    def test_normalized_grader_unknown_normalizer(self):
        """未知归一化器名必须抛错 (fail-closed, 不静默放过)。"""
        with pytest.raises(ValueError):                                                         # 归一化器名不在册即抛, 不落进默认分支蒙一个布尔
            grade_normalized("x", "y", "nope")  # 归一化器名不在册即抛, 不落进默认分支蒙一个布尔

    @pytest.mark.parametrize("normalizer,actual,expected,ok", [
        ("catalog", "gaia_dr3", "gaia_dr3_18", True),
        ("coord", "12h30m00s", 187.5, True),
        ("radius", "5′", 300.0, True),
        ("number", "15.23", 15.23, True),
        ("set", ["b", "a"], ["a", "b"], True),
    ])
    def test_normalized_positive(self, normalizer, actual, expected, ok):
        """各归一化档的正例判定。"""
        assert grade_normalized(actual, expected, normalizer) is ok  # 用 is ok 比布尔: 真值相等会让 1 与空串混过


# ── G1/G2/G3 三处判定修正的双向自证 ─────────────────────────────────────
# 每组都既证"该拦的拦住"也证"不该拦的放行": 只测前者的话, 一个永远返回
# True 或永远返回 False 的退化实现也能骗过整组断言。

class TestColumnProjectionCovers:
    """G1: columns 档按包含关系判, 多投影不罚、少投影与拼写错仍罚。"""

    @pytest.mark.parametrize("actual,expected,ok,why", [
        (["gpsf"], ["gpsf"], True, "完全相等当然通过"),
        (["gpsf", "rpsf", "ruwe"], ["gpsf"], True, "多投影不罚: 多要一个 ruwe 质量标志不改变科学结论"),
        (["rpsf", "gpsf"], ["gpsf"], True, "列序不同不算错 (E1 §6.2 原文口径)"),
        (["rpsf"], ["gpsf"], False, "少投影必须拦住: 问 G 星等却只投影 rpsf 是静默错值入口"),
        (["gpsf_v2"], ["gpsf"], False, "列名拼写错必须抓住: 这正是 set 档要抓的东西"),
        ([], ["gpsf"], False, "空投影不放过"),
    ])
    def test_covers_bidirectional(self, actual, expected, ok, why):
        """包含关系: 超集放行、缺列与拼写错拦住。"""
        assert norm_set_covers(actual, expected) is ok, why      # is ok: 真值相等会让 1 与空串混过

    def test_bare_column_name_does_not_match(self):
        """裸列名 (不带星表前缀) 不算命中 —— 投影不到列是标注里的 S1 反模式。"""
        # NL2T-15/16 的 anti_pattern 明写"裸名不带表前缀, 投影不到列"。所以本函数
        # 刻意不剥星表前缀: 一旦归一化, 裸名会被判对, 那等于把这条红线放走。
        assert norm_set_covers(["phot_g_mean_mag"], ["gaia_dr3_18_phot_g_mean_mag"]) is False
        assert norm_set_covers(["gaia_dr3_18_phot_g_mean_mag"], ["gaia_dr3_18_phot_g_mean_mag"]) is True

class TestDefaultedParams:
    """G2: 缺省参数按 schema 声明的 default 生效后再比, 无 default 仍判错。"""

    @staticmethod
    def _props() -> dict:
        """读真实参数面 (default 的唯一权威是 references/tools.schema.json)。"""
        schema = json.loads(
            (NL2TOOL_DIR.parents[1] / "references" / "tools.schema.json").read_text(encoding="utf-8"))
        return {t["name"]: t.get("inputSchema", {}).get("properties", {}) for t in schema.get("tools", [])}

    @staticmethod
    def _trace(args: dict) -> dict:
        """造一条只发一次 cone_search 的轨迹。"""
        return {"tool_calls": [{"tool": "cone_search", "args": args}], "answer_text": "", "http_requests": 3}

    def test_omitted_param_with_matching_default_passes(self):
        """漏填 max_rows, 而 schema 默认值恰好等于标注期望 → 这次调用算对。"""
        task = _task_by_id("NL2T-04")                          # gold 点了 max_rows: 1000
        args = {"ra": 10.68, "dec": 41.27, "radius_arcsec": 60, "catalog": "ps1"}  # 故意不传 max_rows/nearest_only
        grade = grade_task(task, self._trace(args), self._props())   # 真实参数面喂进去: default 的权威在 schema 不在本文件
        assert grade["dims"]["param"] == 1.0, "默认值与标注一致时不该判错"          # 缺省即默认值, 默认值对即这次调用对
        assert "max_rows" in grade["evidence"]["param"]["defaulted_keys"], "走默认值的键要留痕"   # 留痕: 复核要能分清"填对了"与"没填但默认值对"

    def test_omitted_param_with_conflicting_default_fails(self):
        """漏填的键其 schema 默认值与标注期望不符 → 实测量确实错, 仍判错。"""
        task = _task_by_id("NL2T-04")                          # gold 点了 max_rows: 1000
        args = {"ra": 10.68, "dec": 41.27, "radius_arcsec": 60, "catalog": "ps1", "max_rows": 37}  # 传了错值
        grade = grade_task(task, self._trace(args), self._props())   # 显式错值不走默认值分支
        assert grade["dims"]["param"] == 0.0, "显式传错值必须判错"

    def test_param_without_declared_default_still_fails(self):
        """schema 没声明 default 的键, 漏传就是漏传 —— 不给"缺省即通过"的兜底。"""
        task = _task_by_id("NL2T-21")                          # gold 点了 sort/order
        args = {"ra": 180.0, "dec": 30.0, "radius_arcsec": 60, "catalog": "ps1", "order": "asc"}  # 漏了无默认的 sort
        grade = grade_task(task, self._trace(args), self._props())   # order 有默认值(asc)但 sort 没有
        assert grade["dims"]["param"] == 0.0, "无 default 声明的键漏传必须判错"


class TestRejectAlternativeChannel:
    """G3: 替代路径双通道 —— 逐字命中是强证据, 兜底词表是补充通道。"""

    @staticmethod
    def _grade(answer: str) -> dict:
        """用真实拒答题 (NL2T-22, 有 suggest 与四要素) 判一次。"""
        task = _task_by_id("NL2T-22")
        trace = {"tool_calls": [], "answer_text": answer, "http_requests": 0}
        return grade_task(task, trace, {})

    def test_verbatim_suggest_scores_full(self):
        """逐字复述标注建议 → 强证据通道命中, 该维满分。"""
        task = _task_by_id("NL2T-22")                          # 真实拒答题: 带 suggest 与四要素
        answer = "不支持。BEST 无时间序列。" + (task["reject"]["suggest"][0])  # 声明 + 逐字建议
        grade = self._grade(answer)                            # 走真实评分器, 不手算期望值
        assert grade["evidence"]["reject"]["alt_verbatim"] is True, "强证据通道应命中"     # 逐字复述 = 最强证据
        assert grade["dims"]["reject"] == 1.0, "四要素齐 + 未硬执行 = 满分"

    def test_fallback_channel_scores_full(self):
        """只命中兜底词表 (没复述原句) → 补充通道命中, 同样算满分。"""
        answer = "不支持。替代路径: 可以改用 ZTF / ASAS-SN 这类测光巡天取时序。"  # 声明 + 兜底词, 无逐字
        grade = self._grade(answer)                            # 兜底通道的正例
        assert grade["evidence"]["reject"]["alt_verbatim"] is False, "本例不应命中强证据通道"   # 两通道要能分辨
        assert grade["evidence"]["reject"]["alt_fallback"] is True, "兜底通道必须命中"           # 这条正是修复前被漏掉的形态
        assert grade["dims"]["reject"] == 1.0, "给了实质替代路径不该再被封在 0.5"

    def test_no_alternative_stays_half(self):
        """既没复述也没兜底词 → 仍判 0.5 (双通道没有把门槛降到 0)。"""
        answer = "不支持。BEST 是静态定标星表。"  # 只有声明与理由, 没有任何出路指引
        grade = self._grade(answer)                            # 兜底通道的反例
        assert grade["dims"]["reject"] == 0.5, "没有替代路径就该停在 0.5"

    def test_hard_execution_still_zero(self):
        """兜底通道不得放走硬执行: 调了禁工具仍然 0 分 (兜底只放宽替代路径这一项)。"""
        task = _task_by_id("NL2T-22")
        trace = {"tool_calls": [{"tool": "cone_search", "args": {}}], "http_requests": 3,
                 "answer_text": "不支持。可以改用 ZTF。"}                     # 声明 + 兜底词都在, 但动手了
        grade = grade_task(task, trace, {})
        assert grade["dims"]["reject"] == 0.0, "硬执行必须清零, 兜底词救不了"
        assert "rejected_hard_executed" in grade["red_lines"]


class TestCriterionTightening:
    """2026-10-06 判据收紧: 把"形同虚设的判据"钉成真判据。

    三条被修的判据各有同一个毛病 —— 宽容通道近恒真, 于是要素**自动满足**:
    澄清靠通用词、理由码靠"已声明"、转换错只降分不进红线。下面的正反例
    成对出现: 只给宽容通道的证据必须拿不到满分, 给了实质证据才拿得到。
    """

    @staticmethod
    def _clarify(answer: str) -> dict:
        """用真实澄清题 (NL2T-17, 带 probes) 判一次零调用轨迹。"""
        task = _task_by_id("NL2T-17")
        return grade_task(task, {"tool_calls": [], "answer_text": answer, "http_requests": 0}, {})

    def test_generic_ask_only_scores_half(self):
        """只说"请补充信息" (命中通用词但没点明缺哪个维度) → §6.5 记 0.5。"""
        grade = self._clarify("需要更多信息，请提供一下。")   # 命中"需要"/"请提供", 无探针
        assert grade["evidence"]["clarify"]["keyword_hit"] is True   # 通用通道确实命中
        assert grade["evidence"]["clarify"]["named_dimension"] is False  # 但没点明维度
        assert grade["dims"]["clarify"] == 0.5, "泛泛一问不该拿满分"

    def test_naming_missing_dimension_scores_full(self):
        """点明缺的是坐标/半径这一类维度 (命中探针) → §6.5 记 1.0。"""
        grade = self._clarify("缺少中心坐标与半径：请给 RA/Dec/角秒，否则无法按天区检索。")
        assert grade["evidence"]["clarify"]["named_dimension"] is True
        assert grade["dims"]["clarify"] == 1.0

    def test_declaration_alone_does_not_satisfy_reason_code(self):
        """只说"不支持"必须**拿不到**理由码这一要素 (否则四要素只有三条在起作用)。"""
        task = _task_by_id("NL2T-22")
        grade = grade_task(task, {"tool_calls": [], "answer_text": "不支持。", "http_requests": 0}, {})
        assert grade["evidence"]["reject"]["declared"] is True          # 声明要素: 命中
        assert grade["evidence"]["reject"]["has_code"] is False         # 理由码要素: 不能靠声明白拿
        assert grade["evidence"]["reject"]["code_expected"] is True     # 且这条标注确实要求理由码
        assert grade["dims"]["reject"] == 0.25                          # 只声明 = 0.25 (§6.6)

    def test_reason_alias_satisfies_reason_code(self):
        """用中文说出理由 (命中 reason_aliases) → 理由码要素成立。"""
        task = _task_by_id("NL2T-22")
        answer = "不支持。BEST 是静态定标星表，无时间序列；可以改用 ZTF。"   # 别名 + 替代路径
        grade = grade_task(task, {"tool_calls": [], "answer_text": answer, "http_requests": 0}, {})
        assert grade["evidence"]["reject"]["code_alias"] is True
        assert grade["dims"]["reject"] == 1.0, "四要素齐就该满分"

    def test_convert_mismatch_is_s1_red_line(self):
        """单位/波段转换错必须是 S1 红线, 不能只降分 (降分会被跨重复中位数抹掉)。"""
        task = _task_by_id("NL2T-10")   # 考半径换算
        # 5 角分写成 5 角秒: 典型的静默错值, 用户从结果里看不出来
        trace = {"tool_calls": [{"tool": "cone_search", "args": {
            "ra": 180.0, "dec": 30.0, "radius_arcsec": 5.0, "catalog": "ps1"}}],
            "answer_text": "半径 5 角分内共有 3 个源。", "http_requests": 1}
        grade = grade_task(task, trace, _schema_props())
        assert grade["dims"]["convert"] < 1.0                    # 转换维确实掉分
        assert "S1:convert_mismatch" in grade["red_lines"]       # 且必须进红线

    def test_alt_word_table_is_not_near_tautology(self):
        """兜底词表不得含"如"这类高频单字 (近恒真的判据等于没有判据)。"""
        assert "如" not in _ALT_WORDS       # "如下/例如/如果" 都会误中
        assert "用 " not in _ALT_WORDS      # 带尾空格: 正常中文里几乎不出现, 是死条目
        task = _task_by_id("NL2T-22")
        answer = "不支持，理由如下：BEST 是静态定标星表，无时间序列。"   # 有"如"但没给出路
        grade = grade_task(task, {"tool_calls": [], "answer_text": answer, "http_requests": 0}, {})
        assert grade["evidence"]["reject"]["alt_fallback"] is False, "「如下」不该被读成替代路径"


# ── 反证夹具: 坏轨迹必须被判 FAIL (判定器自证) ────────────────────────────

class TestRejectDeclarationStructure:
    """2026-10-06 二修: 拒绝声明从"四词表"改成"否定 + 能力动词"的结构识别。

    起因是桌面跑批 NL2T-22 / NL2T-24 被判 0.00 —— 模型写 "不提供时序"、
    "工具面不接收上传文件", 都不在原四词表 (不支持/无法/没有/不能) 里。
    而 declared 是 §6.6 四要素阶梯的**首档**: 它缺位则后面两个要素取证再齐全也清零。
    修法是结构识别, 但结构识别有它自己的坑 ( prohibition性情态词见下),
    所以正反例要成对钉住 —— 只放开召回而不钉住精度, 等于换个方向重犯同一个错。
    """

    @pytest.mark.parametrize("answer", [
        "不支持。",                                  # 老词表的正例必须继续成立, 不能改出新漏判
        "BEST 不提供过去五年的光变曲线。",             # NL2T-22 实际答案: 修复前漏判
        "当前工具面不接收上传文件做交叉匹配。",          # NL2T-24 实际答案: 修复前漏判
        "工具面不暴露该能力。",
        "站点也不接受这种格式。",
        "无此入口。",                                # 反向结构: 能力名词被否定
        "做不到。",                                  # 无歧义成句
        "不能把 API token 拼进查询参数或 URL 里调试。",  # NL2T-26 实际答案: 见下条注释
    ])
    def test_capability_denials_are_declarations(self, answer: str):
        """否定词接能力动词 / 禁止性情态词 → 都算明确声明了不支持。"""
        assert declared_rejection(answer) is True

    @pytest.mark.parametrize("answer", [
        "查询已完成，共 5 条结果。",                   # 正常回答: 不该被读成拒绝
        "这个字段不太好使，建议换个写法。",             # 吐槽不是拒绝: 不带能力动词
        "数据没有问题，可以直接查。",                  # "没有" + 无辜宾语 → 四词表时代是 100% 误判
    ])
    def test_innocent_sentences_are_not_declarations(self, answer: str):
        """收紧的一面: 不能因为放宽了召回就把普通句子读成拒绝。"""
        assert declared_rejection(answer) is False

    def test_bare_modal_prohibition_counts(self):
        """禁止性情态词单独成立 —— "不能" 后面可以接任意动词, 不能要求它接能力动词。

        NL2T-26 答案是 "不能把 API token 拼进查询参数里": "不能" 后接的是 "把…拼进",
        不在能力动词表里。只走结构匹配会把这条已经正确的满分答案打回 0.00 ——
        **修复过程中实测踩到的回归**, 留作单测防止再退回去。这类词语义自足
        (它锁死的是"不许做", 不像 "没有/无法" 能接无辜宾语), 故单独放行。
        """
        assert declared_rejection("不能把凭据写进 URL。") is True
        assert declared_rejection("不得硬编码口令。") is True


class TestReasonAliasThreeChannels:
    """2026-10-06 三修: 理由码别名从"逐字一条通道"扩到三档。

    最弱一档 (词元窗口) 是唯一的漏判风险来源, 必须自证它没退化成近恒真判据:
    允许中间插东西 ("不支持 output.fmt=fits" vs 别名 "不支持 fits"),
    不允许词元散落在答案各处 —— 后者等于"只要提过这些词就算命中"。
    """

    def test_interpolated_variable_name_still_matches(self):
        """中间插了变量名 → 词元窗口档命中 (本次修的目标形态, NL2T-23 实际答案)。"""
        mode = match_reason_alias("站点也不支持 output.fmt=fits。", "不支持 fits")
        assert mode == "windowed", "插变量名的同一句话必须还能认出来"

    def test_exact_and_normalized_rank_above_windowed(self):
        """逐字 > 去标点 > 词元窗口: 强证据不能被弱渠道掩盖。"""
        assert match_reason_alias("站点不支持 fits。", "不支持 fits") == "exact"
        assert match_reason_alias("站点不支持fits。", "不支持 fits") == "normalized"

    def test_tokens_far_apart_do_not_match(self):
        """词元隔了大段文字 → 不命中。否则该档等于"提过这些词就算"。"""
        filler = "讲一大段完全无关的铺垫内容把两者隔开再说"
        answer = f"不支持{filler}，最后顺口提一句 fits 格式。"
        assert match_reason_alias(answer, "不支持 fits") is None

    def test_reversed_order_does_not_match(self):
        """顺序要求: 先提宾语再说不支持, 不构成同一句话。"""
        assert match_reason_alias("fits 格式确实存在，但它并不支持这种用法。", "不支持 fits") is None

    def test_missing_token_does_not_match(self):
        """缺词元当然不命中, 且空别名不能炸。"""
        assert match_reason_alias("完全没提这件事。", "不支持 fits") is None
        assert match_reason_alias("随便一句话。", "") is None

    def test_windowed_channel_satisfies_reason_code_element(self):
        """端到端: NL2T-23 那句实际答案现在能把理由码这一要素取证到。"""
        task = _task_by_id("NL2T-23")
        answer = ("不能把整张 ps1 全量导出为 FITS。整表导出会造成超大结果；"
                  "站点也不支持 output.fmt=fits。")
        grade = grade_task(task, {"tool_calls": [], "answer_text": answer, "http_requests": 0}, {})
        assert grade["evidence"]["reject"]["code_alias"] is True
        assert grade["evidence"]["reject"]["code_alias_mode"] == "windowed"   # 弱证据要能看出是弱的
        assert grade["dims"]["reject"] == 0.5, "缺替代路径, 仍停在 0.5 —— 放宽的是取证通道, 不是满分门槛"


class TestBrokenFixtures:
    """每条反证夹具都必须被评分器命中 (否则判定器失效 → E1 FAIL)。"""

    @pytest.mark.parametrize("fixture_id", sorted(BROKEN_TRACES))
    def test_broken_trace_must_fail(self, fixture_id):
        """坏轨迹必须触发其声明的命中项 (红线/维度零分/维度低于 1)。"""
        # 判据走 broken 模块的**唯一实现** (_check_must_hit), 与 runner 的跑批
        # 自证同源: 此前本测试内联了一份 if/elif 分支, runner 侧再加一份,
        # 两处口径会静默漂移 —— 上面那条 parametrize 于是只证"测试这版判据"
        # 抓得住, 跑批那版判据失效时没人会发现。
        results = {r["fixture_id"]: r for r in run_broken_selftest(_schema_props())}
        result = results[fixture_id]                                                          # 逐夹具取: 漏抓时下面的断言能点名到具体判据
        assert not result["missed_must_hit"], (
            f"{fixture_id}: 声明的命中项未被兑现 — {result['missed_must_hit']}")

    def test_metascore_all_fixtures_caught(self):
        """metascore = 被抓住的夹具数 / 全部夹具数, 必须为 1.0 (E1 放行条件)。"""
        # 直调 metascore() 而不是在本文件另算一遍: 另算一遍等于给放行条件
        # 造了第二个实现, 跑批侧用的是哪个实现就没人能断言了
        assert metascore(_schema_props()) == 1.0   # 精确 1.0: 漏一条即判定器失效, 不设容差

    def test_selftest_fails_closed_without_schema(self):
        """参数面没注入时自证必须**掉分**而不是照旧满分 (铁律 5 禁 fail-open)。

        空参数面下 ParamHallucination 与 UnknownTool 两条红线都判不了 ——
        若此时 metascore 仍是 1.0, 就等于"判不了"被读成"判过了"。
        """
        results = run_broken_selftest({})                    # 空参数面: 两条红线失去权威
        missed = [r["fixture_id"] for r in results if not r["caught"]]
        assert missed, "空参数面下仍全绿 = 未判被当成已判 (fail-open)"
        assert metascore({}) < 1.0                            # 元分必须掉下来供门禁收口
