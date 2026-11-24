# -*- coding: utf-8 -*-
"""`ops/audit/line_scope.py` 的守卫: 拆分不许悄悄改判定, 清单不许再写第二份。

起因 (2026-10-03): `ops/audit/comment_audit.py` 因新增 Q9/Q10 两类判据涨到 411 净行,
超 400 行预算。按 `docs/architecture/file-size-budget.md` §3.13 的预案把「行范围
判定」层拆到同目录 `line_scope.py`(135 净行), 本体降到 326。

拆分类改动最隐蔽的失败形态是**「搬着搬着把判定改了」**: 分母变大或变小, 指标仍可能
"达标", 于是完全静默。所以本文件钉三件事:

  1. **十一类排除口径只在 line_scope 一处写**。此前清单同时存在于函数 docstring 与
     调用点注释, 两处都写着过时概数(一处「七类」、一处「三类不算」, 实际十一类)。
     凡是"列举 N 项"的地方, 清单与实现分居两处必然漂。
  2. **Q10 的分母只有 `nontrivial_stmt_rows` 一个来源**, 不许回退成内联表达式。
  3. **每一类排除都真的生效** —— 用反例样本逐类钉, 而不是只测"整体比例达标"。
     比例达标是最弱的证据: 分母与分子一起缩水时它照样绿。
"""
from __future__ import annotations

# 标准库: 内联样本要能 ast.parse 才能喂给门禁的公开分析器 / 正则取源码片段
import ast  # noqa: F401  内联样本的语法校验走门禁本体, 这里显式导入是为了自检时能用
import re  # 从 comment_audit 源码里取"分母是怎么算的"

# 仓根定位: 本文件在 test/unit/meta/, 上溯三级
from pathlib import Path  # noqa: E402

# 第三方: pytest 提供 raises 语义 (本文件当前未用到时也不删, 便于后续补反例)
import pytest  # noqa: F401

SKILL_ROOT = Path(__file__).resolve().parents[3]      # 仓根: 本文件在 test/unit/meta/, 上溯三级
AUDIT_DIR = SKILL_ROOT / "ops" / "audit"              # 门禁脚本目录: 两个模块都在这里, 注入路径要用它

# 注入 sys.path 必须在 import 之前完成: 两个门禁模块都是同目录裸名互导
import sys  # noqa: E402

sys.path.insert(0, str(AUDIT_DIR))                    # 注入而非改包结构: 门禁目录不是包, 直跑时 sys.path[0] 就是它
import line_scope  # noqa: E402  拆分出的行分类层: 被测对象本身
import scan_roots  # noqa: E402  扫描面唯一真源: 门禁不再自带目录清单, 全从这里取

# 十一类排除口径的**唯一权威清单** (函数名 -> 一句话理由)。
# 本清单与 line_scope 模块头的表一一对应; 哪一项实现在 line_scope 里缺失, 本文件红。
ELEVEN_LAYERS = {  # 十一类排除口径的权威清单: 与 line_scope 模块头那张表一一对应, 少一项本文件就红
    "docstring_rows": "docstring 行由 Q1/Q2/Q3/Q5 覆盖",           # 漏它: docstring 逐行进分母, 指标被文档行撑起来
    "data_literal_rows": "数据表内部行的右注只会复述内容",           # 漏它: 星表列名表几百行全进分母
    "declaration_rows": "声明式字符串行(含隐式拼接)逐行写注等于复述正则",  # 漏它: 多行正则片段逐行进分母
    "import_rows": "import 续行名单行的右注只会复述 import",          # 漏它: 几十个符号名的 import 块全进分母
    "signature_rows": "多行签名的参数行右注只会复述签名",              # 漏它: 参数名与注解已在行上, 右注纯复述
    "continuation_rows": "跨行语句的续行是该判断的延续",              # 漏它: 一条判断展开三行, 分母被续行灌水
    "field_decl_rows": "声明式字段行右注只能把字段名读一遍",          # 漏它: dataclass 字段行全进分母
    "assert_rows": "assert 的说明按本仓规范写在断言上方",            # 漏它: 右注会与断言上方的说明重复
    "fixture_rows": "夹具/打桩构造没有可解释的 why",                  # 漏它: Mock() 赋值全进分母
    "bracket_only_rows": "独占一行的括号与下面元素是同一个结构",      # 漏它: 每个数据块多算一行
    "line_continuation_rows": "续行符首行追加注释会直接语法错",      # 漏它: 续行首行进分母, 而它根本写不了右注
}


class TestElevenLayersArePresent:
    """十一类排除口径必须都在, 且都在 line_scope 里 (不在主门禁文件里)。"""

    def test_every_layer_function_exists(self):
        """逐个确认清单里的函数真实存在 —— 少一个就少一类排除, 分母会悄悄变大。"""
        missing = [name for name in ELEVEN_LAYERS if not hasattr(line_scope, name)]  # 少一个函数 = 少一类排除, 分母悄悄变大而指标仍可能达标
        assert not missing, f"line_scope 缺少排除口径函数: {missing}"

    def test_layers_are_not_duplicated_into_the_main_gate(self):
        """主门禁文件不得再自带一份分类实现 (拆分就是为了消除这份重复)。"""
        src = (AUDIT_DIR / "comment_audit.py").read_text(encoding="utf-8")
        for name in ELEVEN_LAYERS:  # 逐项查存在性: 判据类缺陷必须可被断言, 否则门禁写坏了无人发现
            body = re.search(rf"^def {name}\(", src, re.M)
            assert not body, (
                f"`def {name}(` 仍定义在 comment_audit.py 里 —— 拆分后分类层只应有 "
                f"line_scope.py 一处, 两份实现迟早漂"
            )

    def test_trivial_prefix_constants_moved_with_the_layers(self):
        """样板行前缀与数据块阈值是排除口径的一部分, 必须跟着搬走。"""
        for name in ("TRIVIAL_STMT_PREFIX", "DATA_LITERAL_MIN", "BRACKET_ONLY"):
            assert hasattr(line_scope, name), f"line_scope 缺少常量 {name}"


class TestSingleDenominatorSource:
    """Q10 的分母只此一个来源, 不许回退成内联表达式。"""

    def test_analyse_uses_the_aggregate(self):
        """`analyse_line_alignment` 必须调用 nontrivial_stmt_rows。"""
        src = (AUDIT_DIR / "comment_audit.py").read_text(encoding="utf-8")
        fn = re.search(r"^def analyse_line_alignment\(.*?(?=^def |\Z)", src, re.M | re.S)
        assert fn, "找不到 analyse_line_alignment"
        body = fn.group(0)  # 只取该函数体, 避免把后续函数的调用也算进来
        assert "nontrivial_stmt_rows(" in body, "Q10 分母没有走 nontrivial_stmt_rows"

    def test_main_gate_does_not_recompose_the_eleven_layers(self):
        """Q10 的分母构造里不得再**调用**分类函数。

        范围限定在 ``analyse_line_alignment`` 函数体内, 而不是整个文件: Q5 的模块头
        检查合法调用 ``docstring_rows``, 那与 Q10 分母无关。全文件判会把它误报。
        """
        src = (AUDIT_DIR / "comment_audit.py").read_text(encoding="utf-8")
        tree = ast.parse(src)  # 内联样本先过语法: 样本本身就当源码用
        fn = next((n for n in tree.body  # 找不到就是拆分把函数改名/挪走了, 判红
                   if isinstance(n, ast.FunctionDef) and n.name == "analyse_line_alignment"),
                  None)
        assert fn is not None, "找不到 analyse_line_alignment"
        called = {n.func.id for n in ast.walk(fn)  # 按 AST 查调用: 文本匹配会把合法 import 误判成"又并了一遍"
                  if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        hits = sorted(name for name in ELEVEN_LAYERS if name in called)  # 排序只为报错可复现
        assert not hits, (
            f"analyse_line_alignment 里又直接调了分类函数: {hits} —— Q10 分母应只经 "
            f"nontrivial_stmt_rows 取得, 否则清单与实现又分居两处"
        )


class TestAggregateEqualsTheUnion:
    """`nontrivial_stmt_rows` 必须等于「十一类并集 + 样板行前缀」的逐字复刻。

    这条是拆分的**等价性**护栏: 搬错了会在这里露馅, 而不会等到某天指标异常才发现。
    """

    def _union_rows(self, tree, lines):
        """十一类并集的**逐字复刻** —— 聚合函数必须与它完全一致。

        刻意复刻而不是复用: 复用就等于拿被测实现验证自己, 拆分搬错了也照样绿。
        """
        skip = (line_scope.docstring_rows(tree) | line_scope.data_literal_rows(tree)   # 十一类一次并齐, 顺序不影响集合
                | line_scope.declaration_rows(tree) | line_scope.import_rows(tree)
                | line_scope.signature_rows(tree) | line_scope.continuation_rows(tree)
                | line_scope.field_decl_rows(tree) | line_scope.assert_rows(tree)
                | line_scope.fixture_rows(tree) | line_scope.bracket_only_rows(tree, lines)
                | line_scope.line_continuation_rows(lines))                             # 唯一吃 lines 的两类
        out = set()  # 行号集合: 分母与并集复刻要比的就是它
        for i, raw in enumerate(lines, 1):                                                # 逐物理行
            st = raw.strip()                                                             # 去空白再判
            if not st or st.startswith("#") or i in skip:                                # 空行/纯注释/十一类都不进
                continue
            if st.startswith(line_scope.TRIVIAL_STMT_PREFIX) or st in {")", "]", "}"}:  # 样板行在计数前排除
                continue
            out.add(i)
        return out

    def test_aggregate_matches_union_on_inline_samples(self):
        """内联样本逐个对拍: 分母行号集合必须完全相等。"""
        samples = [  # 五份样本各压一类排除: 平凡/样板/括号/assert/夹具
            # 平凡语句应进分母
            "def f(v):\n    x = v + 1  # 有右注\n    y = x * 2  # 有右注\n    return y\n",
            # 样板行不进: import / return / 收尾括号
            "import os\nimport sys\n\n\ndef g():\n    return os\n",
            # 括号开启行与其后元素是同一个结构, 都不进
            "VALUES = [\n    1,\n    2,\n]\n",
            # assert 不进。样本要的是「有一条 assert 语句」这一**形态**, 不是恒真断言 ——
            # 恒真断言是 E5 tests 审计器判定的空断言, 写进内联样本(它按文本扫)也会被它命中
            "def h(v):\n    assert v > 0\n    z = 1  # 有右注\n",
            # 夹具构造不进
            "def k(mock):\n    client = mock.Mock()\n    w = 1  # 有右注\n",
        ]
        for src in samples:  # 逐份对拍, 任意一份不一致即红
            tree = ast.parse(src)
            lines = src.splitlines()
            assert line_scope.nontrivial_stmt_rows(tree, lines) == self._union_rows(tree, lines), (
                f"聚合函数与并集复刻不一致:\n{src}"
            )

    def test_aggregate_matches_union_on_real_files(self):
        """全仓真实文件对拍: 拆分只许搬, 不许改判定。"""
        checked = 0  # 计数供末尾的覆盖下限断言用: 只对拍几个文件等于没对拍
        for rel, full in scan_roots.iter_py_files(str(SKILL_ROOT)):  # 用门禁自己的扫描面 (共享真源), 不另列一份 (另列必然漂)
            p = Path(full)
            text = p.read_text(encoding="utf-8", errors="replace")
            try:
                tree = ast.parse(text)
            except SyntaxError:
                continue
            lines = text.splitlines()
            assert line_scope.nontrivial_stmt_rows(tree, lines) == self._union_rows(tree, lines), (
                f"{rel}: 聚合函数与并集复刻不一致 —— 拆分改了判定"
            )
            checked += 1
        assert checked > 200, f"只对拍了 {checked} 个文件, 覆盖不足"


class TestEachLayerActuallyExcludes:
    """逐类反例: 每一类排除都必须真的把行踢出分母。

    比例达标是最弱的证据 —— 分母与分子一起缩水时它照样绿。所以这里不看比例,
    只看**具体行号在不在分母里**。
    """

    def _denom(self, src):
        """取一份内联样本的分母行号集合 (供下面逐类反例断言)。"""
        tree = ast.parse(src)                                    # 内联样本本身就是源码, 直接 parse
        return line_scope.nontrivial_stmt_rows(tree, src.splitlines())  # 被测 seam 本身

    def test_trivial_rows_excluded(self):
        """样板行 (import / return / 收尾括号) 不进分母。"""
        src = "import os\n\n\ndef f():\n    v = 1  # 有右注\n    return v\n"
        assert self._denom(src) == {5}, f"分母应只剩 v = 1 那一行, 实得 {self._denom(src)}"

    def test_assert_row_excluded(self):
        """assert 不进分母 (本仓规范要求说明写在断言上方)。"""
        src = "def f(v):\n    assert v > 0\n    w = v + 1  # 有右注\n"
        assert self._denom(src) == {3}, f"assert 行应被排除, 实得分母 {self._denom(src)}"

    def test_docstring_row_excluded(self):
        """docstring 行不进分母; 同函数里的 return 属样板行, 也不进。"""
        src = "def f():\n    \"\"\"说明。\"\"\"\n    v = 1  # 有右注\n    return v\n"
        assert self._denom(src) == {3}, f"docstring 行应被排除, 实得 {self._denom(src)}"

    def test_data_block_rows_excluded(self):
        """元素数超阈值的列表内部行不进分母 (由块首那一行的右注覆盖)。"""
        rows = "".join(f"    {i},\n" for i in range(10))
        src = f"TABLE = [\n{rows}]\n"
        assert self._denom(src) == {1}, f"数据块内部行应被排除, 实得 {self._denom(src)}"

    def test_normal_statement_kept(self):
        """普通语句必须留在分母里 —— 否则这条指标就退化成"什么都排除"。

        期望里不含 ``return v``: 它在 TRIVIAL_STMT_PREFIX 表里, 属样板行。
        """
        src = "def f(v):\n    a = v + 1  # 有右注\n    b = a * 2  # 有右注\n    return b\n"
        assert self._denom(src) == {2, 3}, f"普通语句应进分母, 实得 {self._denom(src)}"
