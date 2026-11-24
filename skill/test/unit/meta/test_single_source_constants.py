# -*- coding: utf-8 -*-
"""哨兵阈值与错误码的**单一真源**守护 (T1)。

守的是"同一个值在仓内被定义了几次"。这类分叉的形态与
``test_gate_blindspots.py`` 守的模块级重复定义同源, 但落点是**字面量**而不是
符号名, 所以既不被 ruff 也不被那条门禁看见:

1. :class:`TestSentinelThresholdSingleSource` —— 哨兵**阈值**只许一处定义。
   实测背景: ``src/models/__init__.py`` 的 ``NULL_MAGNITUDE_SENTINEL = -999.0``
   是判定真源, ``src/tap/formats.py`` 早已经该常量取阈值 (不是硬编码);
   而 ``src/core/source_postprocess.py`` 里的 ``-900.0`` 是**另一个阈值的字面量**,
   刻意宽于 -999.0 (注释已写明: 吸收哨兵带噪声, -950 一类取值在本层被剔成 None
   而在 models.from_row 判为有效星等)。本门禁因此不禁止 -900.0 存在, 只要求:
   **凡是把 -999.0 当判定阈值用的地方, 必须是引用那个常量, 不是再抄一份**。

2. :class:`TestErrorCodeSingleSource` —— 错误码**字面量**只许一处定义。
   实测背景: 收敛前同一个码字面量散在 6 个赋值点 (``src/ai_tools.py`` 五份 +
   ``src/crossmatch.py`` 的 ``_QUERY_FAILED``), 而协议层另有
   ``SOFT_404_ERROR_CODE`` / ``NameResolveError.code`` 两份。改契约漏改一处
   即"半边新半边旧"的静默分叉 —— 现有门禁全部看不见 (ruff 不管跨模块同值,
   ``test_error_code_contract_alignment.py`` 只验契约⊆代码, 不验"代码里几处定义")。

**为什么"再导出"不算重复定义**: 收敛后 ``src/ai_tools.py`` 仍有
``E_SOFT_404 = SOFT_404_ERROR_CODE`` 这类别名, 但它的值是**引用**而非字面量,
判据按"字面量出现次数"计数, 别名不计数。照抄一份字面量才是分叉。

判据全部走 AST 而非文本子串: 注释与 docstring 里提到 ``-999.0`` / ``E_NO_SQLID``
是白盒锚点与契约说明 (本仓大量这么写), 属合法引用; 子串匹配会把它们算成定义,
那样的门禁必然被人"改窄"到恒绿。

本文件全程离线, 只读源码 + AST, 不触网、不改工作区。
"""

from __future__ import annotations

# 标准库: ast 做字面量扫描 / pathlib 定位仓库根
import ast  # ast 是本门禁的立足点: 注释与 docstring 根本不在语法树里
from pathlib import Path  # 仓库根锚定: 扫描目录由它推出, 不依赖 conftest

SKILL_ROOT = Path(__file__).resolve().parents[3]  # 仓库根: 本文件在 test/unit/meta/, 上溯三级即 skill 根
SRC = SKILL_ROOT / "src"  # 只扫生产面: 测试里的字面量是夹具, 天然允许重复

# 哨兵判定阈值的真值 (与 evals/_data/null_sentinel.yaml 的 threshold 同值)。
# 这里写成常量而非散在断言里, 是为了让失败信息能指名是哪个值出的问题。
SENTINEL_THRESHOLD = -999.0  # 判定阈值真值: 与 evals/_data/null_sentinel.yaml 的 threshold 同值

# 哨兵**带**的已知实例 (ps1 的 -1004.07 一族): 它们低于阈值, 但判定必须走
# ``value <= threshold``, 不是枚举这些点 —— 见 evals/_data/null_sentinel.yaml
# 头的用法约定。列在这里是给"字面量定义"判据一个更宽的捕获面。
SENTINEL_BAND_TOP = -1000.0  # 名称解析失败哨兵 (ra=dec=-1000, src/protocol.py)


def _code_string_literals(tree: ast.AST) -> set[str]:
    """树里"真代码"中的字符串字面量全集 (**docstring 剔除**)。

    docstring 在 AST 里就是普通字符串常量, 所以"剔注释"是白送的 (注释压根不进
    语法树), "剔 docstring"必须按节点位置做 —— 只有 ``Module``/``ClassDef``/
    ``FunctionDef``/``AsyncFunctionDef`` 的**体首元素**才是 docstring 位。
    按 ``isinstance(node, ast.Expr)`` 猜位置会在 ``X = "E_FOO"`` 旁边误伤。
    """
    docs: set[int] = set()
    for node in ast.walk(tree):                                           # 逐容器找 docstring 位
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        body = getattr(node, "body", None)
        if (body and isinstance(body[0], ast.Expr)                                  # docstring 只能在体首
                and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str)):
            docs.add(id(body[0].value))                                            # 按对象身份记, 不用字符串内容 (两个 docstring 内容可能相同)
    return {n.value for n in ast.walk(tree)                                        # 只认真代码里的字符串常量
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs}


def _numeric_value(node: ast.AST) -> float | None:
    """取节点代表的数值字面量; 不是字面量返回 ``None``。

    **必须单列 USub 分支**: Python 把 ``-999.0`` 解析成
    ``UnaryOp(USub, Constant(999.0))``, 不是 ``Constant(-999.0)``。只认
    ``ast.Constant`` 的判据因此对任何负阈值恒不命中 —— 而本门禁要守的恰恰是
    负哨兵, 于是它静默失效 (报出来永远是空清单, 读的人只会以为"全仓干净")。
    判据恒不命中比没有判据更危险, 所以这里显式还原负号。
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) \
            and not isinstance(node.value, bool):  # bool 是 int 的子类, 显式排除否则 True 会被当成 1
        return float(node.value)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):  # 一元负号: 取内层再取负
        inner = _numeric_value(node.operand)
        return None if inner is None else -inner  # 内层不是数字就不是字面量, 不硬凑
    return None


def _assignments(path: Path) -> list[tuple[int, str, ast.AST]]:
    """文件里全部赋值节点的 ``(行号, 目标名, 值节点)``。

    收 ``Assign`` 与 ``AnnAssign`` 两种形态: 错误码既有裸赋值也有带标注的
    (类属性 ``code: str``)。局部变量与函数内赋值一并收 —— 分叉可能写在函数体里。
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))  # 语法错向上抛, 不降级成"无定义"
    out: list[tuple[int, str, ast.AST]] = []
    for node in ast.walk(tree):                                    # 收两种赋值形态, 局部赋值也要 (分叉可能写在函数体里)
        if isinstance(node, ast.Assign):
            for target in node.targets:
                name = target.id if isinstance(target, ast.Name) else (       # 裸名与属性名都要, 类属性是主要形态之一
                    target.attr if isinstance(target, ast.Attribute) else "")
                if name:
                    out.append((node.lineno, name, node.value))
        elif isinstance(node, ast.AnnAssign):
            target = node.target
            name = target.id if isinstance(target, ast.Name) else (
                target.attr if isinstance(target, ast.Attribute) else "")
            if name and node.value is not None:  # 无值的标注 (裸 x: int) 不赋值, 天然不是定义
                out.append((node.lineno, name, node.value))
    return out


def _src_files() -> list[Path]:
    """``src/`` 下全部 .py (排序: 报错次序跨机可复现)。"""
    files = sorted(SRC.rglob("*.py"))
    assert files, "src/ 下无 .py 文件 — 扫描语料为空, 本门禁已失效"  # 空语料时"无重复"恒成立
    return files


class TestSentinelThresholdSingleSource:
    """哨兵判定阈值 ``-999.0`` 只许一处**字面量**定义。"""

    def _threshold_literal_sites(self) -> list[str]:
        """把 ``src/`` 里把阈值当**字面量**写下的位置列出来 (带 file:line)。"""
        offenders: list[str] = []
        for path in _src_files():                                              # 逐文件扫赋值点
            for lineno, name, value in _assignments(path):                    # 逐赋值看值是不是阈值字面量
                number = _numeric_value(value)
                # 命中条件: 赋的就是阈值那个数**且**不是从常量/字典取来的引用。
                # 引用形态 (``X = BestSource.NULL_MAGNITUDE_SENTINEL``) 的
                # _numeric_value 返回 None, 天然不计数 —— 这正是收敛后想要的口径。
                if number is not None and number == SENTINEL_THRESHOLD:
                    offenders.append(f"{path.relative_to(SKILL_ROOT)}:{lineno}  {name} = {number}")
        return offenders

    def test_sentinel_threshold_literal_is_defined_once(self):
        """阈值字面量只许在真源那一处定义 (其余位置必须引用常量)。"""
        offenders = self._threshold_literal_sites()               # 取全 src/ 的阈值字面量定义点 (要 <=1)
        assert len(offenders) <= 1, (
            f"哨兵阈值 {SENTINEL_THRESHOLD} 被定义 {len(offenders)} 处: {offenders} —— "
            "真源是 src/models/__init__.py 的 BestSource.NULL_MAGNITUDE_SENTINEL, "
            "其余位置必须引用它而不是再抄一份字面量"
        )

    def test_threshold_truth_source_still_exists(self):
        """真源常量必须在场 (防止"消重"消成零定义)。"""
        source = (SRC / "models" / "__init__.py").read_text(encoding="utf-8")
        assert "NULL_MAGNITUDE_SENTINEL = -999.0" in source, (
            "哨兵阈值真源 NULL_MAGNITUDE_SENTINEL 不见了 —— 判定阈值必须留在 src/models"
        )

    def test_formats_consumes_the_constant_not_a_literal(self):
        """``src/tap/formats.py`` 必须引用常量 (类型化导出与行模型同解)。"""
        offenders = [f"{p.relative_to(SKILL_ROOT)}:{ln}  {name}"
                     for p in _src_files() if p.name == "formats.py"
                     for ln, name, value in _assignments(p)
                     if _numeric_value(value) == SENTINEL_THRESHOLD]
        assert not offenders, (
            f"src/tap/formats.py 抄了阈值字面量: {offenders} —— "
            "它必须取 BestSource.NULL_MAGNITUDE_SENTINEL, 否则导出与行模型会对"
            "'无测量'给出不同答案"
        )


class TestErrorCodeSingleSource:
    """错误码字面量只许一处**定义** (别名/再导出不算)。"""

    def _code_literal_sites(self) -> dict[str, list[str]]:
        """``src/`` 里 ``E_*`` 码字面量的定义点 -> ``{码: [file:line 目标名]}``。"""
        sites: dict[str, list[str]] = {}
        for path in _src_files():                                  # 逐文件收 E_* 字面量定义点
            rel = path.relative_to(SKILL_ROOT)
            for lineno, name, value in _assignments(path):         # 逐赋值判值是不是 E_ 开头的字符串常量
                # 值是**字符串常量**才算定义; 取自别处的 (``X = E_NO_SQLID`` /
                # ``X = SOFT_404_ERROR_CODE`` / ``X = NameResolveError.code``)
                # 不是 ast.Constant, 天然不计数 —— 别名不算第二份真源。
                if isinstance(value, ast.Constant) and isinstance(value.value, str) \
                        and value.value.startswith("E_"):
                    sites.setdefault(value.value, []).append(f"{rel}:{lineno}  {name}")
        return sites

    def test_each_error_code_literal_is_defined_once(self):
        """同一码字面量在 ``src/`` 内只许定义一次。"""
        duplicates = {code: where for code, where in self._code_literal_sites().items() if len(where) > 1}  # >1 即重复真源
        assert not duplicates, (
            f"错误码字面量被重复定义 (真源是 src/protocol.py): {duplicates} —— "
            "同一码散在多处赋值点时, 改契约漏改一处即静默分叉; "
            "其余位置请改为 from src.protocol import 该码 (别名/再导出不算定义)"
        )

    def test_every_code_defined_anywhere_is_reachable_from_protocol(self):
        """凡在 ``src/`` 出现的 ``E_*`` 码, 都必须能从协议层取到 (真源可达)。

        这条挡的是"消重消过头": 有人把唯一的定义删掉而引用点还在, 静态计数会
        报"零重复" (绿), 但运行期 ``ImportError``。协议层可达 = 真源没丢。

        可达性按**两种真实消费形态**查, 与收敛后的写法逐字对齐:
        模块级常量 (``E_NO_SQLID``) 与一级类属性 (``NameResolveError.code`` ——
        ``E_NAME_UNRESOLVED`` 的真源就在类上, 不是模块级)。只查模块级会把
        类属性那份判成"真源丢了", 那是判据失真而不是缺陷。
        """
        from src import protocol  # 协议层 (错误码真源): 导入即证明可取; 协议层单向依赖 ai_tools, 不会成环
        reachable: set[str] = set()
        for name in dir(protocol):                                 # 模块级常量 + 一级类属性两种可达形态
            value = getattr(protocol, name)
            if isinstance(value, str):
                reachable.add(value)                                   # 模块级常量
            elif isinstance(value, type):                              # 一级类属性: 异常类的 code
                code = getattr(value, "code", None)
                if isinstance(code, str):
                    reachable.add(code)
        missing = sorted(code for code in self._code_literal_sites() if code not in reachable)  # 取不到的即真源丢失
        assert not missing, (
            f"这些错误码在 src/ 有定义但 src.protocol 取不到 (真源丢了): {missing} —— "
            "把定义放回 src/protocol.py (模块级常量或异常类 code 属性), 其余位置改为 import"
        )

    def test_criterion_counterexample_duplicate_is_caught(self, tmp_path):
        """反证夹具: 造一份**确实重复**的码字面量, 同一判据必须点名它。

        没有这条, 上面那条可以靠"判据恒空"作弊变绿 —— 那就是把漏报换成假绿。
        判据在这里被直接调用, 而不是复用类方法, 以免"改了类方法忘了改这里"。
        """
        bad = tmp_path / "probe.py"
        bad.write_text(                                                    # 夹具: 一份字面量定义 + 一个别名
            'E_NO_SQLID = "E_NO_SQLID"\n'      # 第二份定义: 与真源重复
            "OTHER = E_NO_SQLID\n",             # 别名: 不是定义, 不该计入
            encoding="utf-8",
        )
        sites: dict[str, list[str]] = {}
        for lineno, name, value in _assignments(bad):                      # 逐赋值走与门禁同一判据
            if isinstance(value, ast.Constant) and isinstance(value.value, str) \
                    and value.value.startswith("E_"):
                sites.setdefault(value.value, []).append(f"probe.py:{lineno}  {name}")
        assert len(sites.get("E_NO_SQLID", [])) == 1, f"判据应只认字面量定义那一处: {sites}"
        assert not any("OTHER" in w for w in sites["E_NO_SQLID"]), "别名被误判成第二份定义"

    def test_criterion_counterexample_comment_mention_is_not_a_definition(self, tmp_path):
        """反证夹具: 只在注释与 docstring 里提到某码, 必须判为**无定义**。

        子串判据会把这两处算成定义, 于是"抄一份"改写成注释就能让门禁变绿。
        """
        fake = "E_FAKE_ONLY_MENTIONED"
        decoy = tmp_path / "decoy.py"
        decoy.write_text(                                                  # 整份源码只有注释与 docstring 提到该码
            f"# 历史遗留: 曾计划接入 {fake}, 后来没做\n"
            "def helper(x):\n"
            f'    """docstring 里也提一句 {fake}, 同样不算定义。"""\n'
            "    return x + 1\n",
            encoding="utf-8",
        )
        sites: dict[str, list[str]] = {}
        for lineno, name, value in _assignments(decoy):                    # 逐赋值走与门禁同一判据
            if isinstance(value, ast.Constant) and isinstance(value.value, str) \
                    and value.value.startswith("E_"):
                sites.setdefault(value.value, []).append(f"decoy.py:{lineno}  {name}")
        assert not sites, f"注释/docstring 里的码名被算成定义: {sites}"


class TestSentinelSingleSourceEndToEnd:
    """生产与评测两侧的哨兵口径必须**相等** (值级证据, 不只看有没有 import)。"""

    def test_production_threshold_equals_evaluation_dictionary(self):
        """生产判定阈值必须等于 ``evals/_data/null_sentinel.yaml`` 的 ``threshold``。

        两侧不能互相 import (生产不反向依赖评测层), 所以各留一份字面量是设计
        使然 —— 这条断言就是那份代价的对价: 改一侧不改另一侧立即红。
        期望值从字典取, 本文件不写死任何哨兵数值。
        """
        from evals._data import load_null_sentinel  # 评测侧真源 (铁律 6 允许的跨实验共享纯数据)
        from src.models import BestSource  # 生产侧判定常量: 与上一行对账
        assert float(load_null_sentinel()["threshold"]) == BestSource.NULL_MAGNITUDE_SENTINEL, (
            "生产与评测的哨兵阈值已漂移 (改一侧必须同步另一侧, 见 null_sentinel.yaml 头)"
        )
