# -*- coding: utf-8 -*-
"""未决标记判据的阴性/阳性对照 —— 「占位」不该被当成 TODO 的那条窄案口径。

2026-10-07 的实测缺陷: ``evals/audit/__init__.py`` 的 references 审计层用
``re.search(r"\\bTODO\\b|\\bFIXME\\b|占位", text)`` 判未决标记。``\\b`` 对 ASCII 词
有效, 但**中文没有词边界**, 于是裸子串 ``占位`` 把
``references/scientific-client-defenses.md`` §7.1 里"采用固定的极端浮点数进行
填充占位"整段判成 MAJOR —— 而那里的"占位"是本领域的正经术语 (哨兵填充写法),
不是没写完的待办。该审计层自己那行注释写的恰恰是「正文里提到『占位』二字不该被
当成未决标记」: **判据与它自己的意图相反**。

后果不是"多报一条", 是 ``evals/eval_runner.py`` 的 correctness 维度直接 FAIL
(0.30/0.80), 而仓库里没有任何东西是坏的 —— 一道假红挡住整条门禁。

修法取**窄案**: 只在占位与一个待办词同句相邻时才算未决 (占位待补 / 待补: 表格占位 /
占位 (TBD) …), 术语用法一律放过。

方法学上照本仓既有纪律 (见 test_gate_negative_control.py 模块头):
判据改窄之后, **必须同时证明两件事** —— ① 该抓的还抓得到 (阳性对照), ② 不该抓的
真的抓不到 (阴性对照)。只做 ① 的话, 判据退化成"永不触发"也能让本件全过;
只做 ② 的话, 判据退化成恒 False 同样全过。两侧都要有, 且都要是真跑。

第二个同类缺陷在同一审计层 (见 TestModuleLevelSkipDetector): tests 层用
``"allow_module_level=True" in text`` 纯文本子串判模块级跳过, 于是
``test/integration/test_query_chain.py`` 里那段"解释守卫为何被删除"的**注释**
被判成违规 —— 而那个守卫 2026-10-05 就删了, 文件里根本没有这样的调用。
两处是同一种病: **拿文本形态当判据**, 注释/docstring/字符串一律误报, 真调用若把
标志拆成变量名又一律漏报。修法都是改认 AST 里的调用身份。
"""
from __future__ import annotations

# 标准库: 路径锚定 / AST 解析 / sys.path 幂等
import ast
import sys
from pathlib import Path

# 第三方: 参数化把两侧样本一次铺开 (两侧都要逐条过, 不能只测首条)
import pytest

SKILL_ROOT = Path(__file__).resolve().parents[3]  # 仓根: 本件在 test/unit/meta/ 下三级
if str(SKILL_ROOT) not in sys.path:  # 幂等: 让本件不依赖调用方是否已把仓根挂上
    sys.path.insert(0, str(SKILL_ROOT))

from evals.audit import UNRESOLVED_MARKER_RE, _has_module_level_skip  # noqa: E402  — 被测的两个判据

# 阳性样本: 这些**读起来就是没写完**, 判据漏掉任何一条都不算修好。
# 覆盖三类形态: ASCII 整词 (TODO/FIXME)、中文待办词在前、待办词在后。
MUST_FLAG = (
    ("TODO 整词", "步骤一: TODO 补齐公式推导"),
    ("FIXME 整词", "这里的单位 FIXME 一下"),
    ("占位待补", "第 3 行是占位待补"),
    ("待补在前", "待补: 下表占位待填数据"),
    ("占位待替换", "示例值是占位待替换"),
    ("未填占位", "第 2 列未填占位"),
    ("TBD 邻近", "该阈值为占位 (TBD)"),
)

# 阴性样本: 这些是**术语或正常表述**, 判据多报任何一条都是把假红请回来。
# 第一条就是本次缺陷的现场样本 (逐字取自 scientific-client-defenses.md §7.1)。
MUST_NOT_FLAG = (
    ("术语·填充占位", "采用固定的极端浮点数进行填充占位："),
    ("术语·哨兵占位值", "-999.0 是站点的哨兵占位值, 不是真实观测"),
    ("术语·占位符定义", "占位符指该字段在本表中不适用"),
    ("裸术语·占位", "占位"),
    ("词缀不是标记", "TODOS 清单与 TODOLEN 字段都不是未决标记"),
)

# 模块级 skip 判据的阳性样本: 这些**真的是** ``pytest.skip(..., allow_module_level=True)``。
# 覆盖属性形态与裸名形态两种写法, 以及关键字不在首位的写法 (旧文本规则只认字面量形态)。
SKIP_MUST_FLAG = (
    ("属性形态", "import pytest\npytest.skip('x', allow_module_level=True)\n"),
    ("裸名形态", "from pytest import skip\nskip('x', allow_module_level=True)\n"),
    ("关键字在中间", "import pytest\npytest.skip(reason='x', allow_module_level=True, foo=1)\n"),
    ("多位置参数", "import pytest\npytest.skip('a', 'b', allow_module_level=True)\n"),
)

# 阴性样本: 形态上**看起来**像, 但没有真调用 —— 旧文本子串规则全都会误报这些。
SKIP_MUST_NOT_FLAG = (
    ("只有注释", "# 这里曾有 allow_module_level=True, 守卫已删\nimport os\nprint(os)\n"),
    ("docstring 里", '"""说明: allow_module_level=True 是被禁形态。"""\nimport os\n'),
    ("字符串字面量", "S = 'allow_module_level=True'\nimport os\n"),
    ("普通 skip", "import pytest\npytest.skip('x')\n"),
    ("置 False 不算", "import pytest\npytest.skip('x', allow_module_level=False)\n"),
    ("同名非 pytest 函数", "def skip(*a, **k):\n    pass\nskip('x', allow_module_level=True)\n"),
)


class TestUnresolvedMarkerRule:
    """窄案口径的两个方向: 该抓的抓到, 不该抓的抓不到。"""

    @pytest.mark.parametrize("label,text", MUST_FLAG,
                             ids=[label for label, _ in MUST_FLAG])  # 报告里用形态名定位, 不用整段文本
    def test_pending_markers_are_still_flagged(self, label, text):
        """阳性对照: 待办形态必须仍被判成未决标记 (漏抓 = 判据被改废)。"""
        assert UNRESOLVED_MARKER_RE.search(text), (  # search 而非 match: 形态都在行中间
            f"未决标记漏抓 [{label}]: {text!r} —— 窄案改过头, 判据已退化成永不触发")

    @pytest.mark.parametrize("label,text", MUST_NOT_FLAG,
                             ids=[label for label, _ in MUST_NOT_FLAG])
    def test_terminology_usage_is_not_flagged(self, label, text):
        """阴性对照: 术语用法必须放过 (误报 = 本次那个假红原样回来)。"""
        assert not UNRESOLVED_MARKER_RE.search(text), (  # 空匹配即放过; 非空即误报
            f"未决标记误报 [{label}]: {text!r} —— 这不是待办, 是正常术语")

    def test_shipped_reference_docs_carry_no_pending_marker(self):
        """真实回归: references/ 全部白盒文档零命中 (eval_runner 的 correctness 维度靠这条)。"""
        offenders = []  # 逐份收集而不是首个即抛: 一次跑批看清是哪几份
        for md in sorted((SKILL_ROOT / "references").glob("*.md")):  # 排序: 报告顺序稳定, 两轮可直接 diff
            text = md.read_text(encoding="utf-8-sig")  # utf-8-sig: 兼容历史 BOM 文件
            hit = UNRESOLVED_MARKER_RE.search(text)
            if hit is not None:  # 逐份判, 不把文件名与命中片段混在一起
                offenders.append(f"{md.name}: {hit.group(0)!r}")
        assert not offenders, f"references/ 里有未决标记 (correctness 维度会 FAIL): {offenders}"

    def test_old_bare_substring_rule_would_have_misjudged(self):
        """同形变异对照: 证明旧口径**真的会**误报 (否则本件的阴性样本是空转)。

        这里直接跑修复前的裸子串规则, 逐条对同一批样本比新旧两个判据。旧规则的病是
        **过宽**而不是漏抓 —— 它见 ``占位`` 就报, 于是待办与术语一视同仁。窄案不能
        靠"报得更少"冒充修好: 必须同时保住真待办的命中, 只摘掉术语那部分。
        """
        import re  # 局部导入: 只在这一条对照里用到, 不占模块级导入位

        old_rule = re.compile(r"\bTODO\b|\bFIXME\b|占位")  # 修复前的原样判据
        terminology = "采用固定的极端浮点数进行填充占位："  # 现场样本: 术语, 不是待办
        pending = "第 3 行是占位待补"  # 真待办: 窄案之后必须仍被抓

        assert old_rule.search(terminology), "旧规则本就不误报 = 归因错了, 窄案修错了对象"
        assert old_rule.search(pending), "旧规则对真待办也命中 (它是过宽, 不是漏抓)"

        assert not UNRESOLVED_MARKER_RE.search(terminology), "窄案未放过现场样本"
        assert UNRESOLVED_MARKER_RE.search(pending), "窄案把真待办也放过了 = 判据退化成永不触发"


class TestModuleLevelSkipDetector:
    """模块级 skip 判据: 认调用身份, 不认文本形态。"""

    @pytest.mark.parametrize("label,source", SKIP_MUST_FLAG,
                             ids=[label for label, _ in SKIP_MUST_FLAG])
    def test_real_module_level_skip_is_detected(self, label, source):
        """阳性对照: 真调用必须被抓 (漏抓 = 判据退化成"文本里没有就永不触发")。"""
        assert _has_module_level_skip(ast.parse(source)), f"模块级 skip 漏抓 [{label}]"

    @pytest.mark.parametrize("label,source", SKIP_MUST_NOT_FLAG,
                             ids=[label for label, _ in SKIP_MUST_NOT_FLAG])
    def test_lookalike_text_is_not_a_module_level_skip(self, label, source):
        """阴性对照: 注释/docstring/字符串/=False 一律不算 (误报 = 假红原样回来)。"""
        assert not _has_module_level_skip(ast.parse(source)), f"模块级 skip 误报 [{label}]"

    def test_no_test_file_actually_skips_at_module_level(self):
        """仓内现状登记: test/ 全树零真调用 (与 test_no_module_skip_guards.py 同向, 但那份查静态门禁)。

        这条是**状态**断言, 随新增文件而变; 机制由上面两条测。
        """
        offenders = []  # 逐份收集: 一次跑批看清是哪几份, 而不是首个即抛
        for path in sorted((SKILL_ROOT / "test").rglob("test_*.py")):  # 排序: 报告顺序稳定
            tree = ast.parse(path.read_text(encoding="utf-8-sig"))       # utf-8-sig: 兼容历史 BOM 文件
            if _has_module_level_skip(tree):
                offenders.append(path.relative_to(SKILL_ROOT).as_posix())
        assert not offenders, f"test/ 里有模块级 skip (整份文件会被静默跳过): {offenders}"
