# -*- coding: utf-8 -*-
"""错误码契约与代码常量**双向**对齐 (G1-09, H4-2)。

为什么要有这个门: ``contracts/error-codes.contract.yaml`` 自己的注释写着"代码
在用的码必须有契约条目", 但没有任何门禁守这句话 ——
``test/unit/contracts/test_gen_contracts.py:61`` 的 ``EXPECTED_FILES`` 只断言
**文件存在**, 不看内容。而 ``ops/audit/verify_crossrefs.py`` 第 8 项
("契约错误码被代码引用") 从这份文件收集到 **0 个** 码: ``BEST_NNNN`` 是字典
**键**, 而那段检查只认 ``code``/``name``/``id`` 三个**值**键位, 于是
"死码检查"对 error-codes 契约零覆盖。G1 实测据此发现 ``E_BACKEND`` 代码在
用 (``src/ai_tools.py:58`` 定义、:225 实发, ``src/client_paging.py:187`` 也发)
而契约无条目。

所以这里补两个方向:
  1. 代码里的错误码常量 ⊆ 契约 codes 段 (``code`` 字段) —— 挡住"代码加了码
     忘了登记" (G1-09 本体);
  2. 契约里的码要么代码在引用, 要么在契约注释里被显式声明为未接线 ——
     挡住"契约登记了没人用"且没人说明 (declared 段是刻意保留的, 有注释依据)。

本文件离线运行: 只读 YAML 与模块常量, 零网络。
"""
from __future__ import annotations

# 标准库: ast 走符号面 (子串判据会被注释/docstring 骗到) / re 做标识符边界匹配 /
# pathlib 仓根锚定
import ast  # ast 是本判据的立足点: 注释根本不在语法树里, docstring 可按节点精确剔除
import re  # re 做码名的标识符边界匹配: 裸子串会被同前缀的其他码骗到
from pathlib import Path  # 仓根锚定: 不依赖 conftest 的 spec 降级链

# 第三方: pytest 参数化 (逐个错误码一条用例, 失败时点名是哪一个)
import pytest

# 第三方: YAML 解析契约文件 (契约的权威载体就是这份 YAML)
import yaml

CONTRACT = Path(__file__).resolve().parents[3] / "contracts" / "error-codes.contract.yaml"  # 三级上溯 = skill 根 (本文件在 test/unit/contracts/ 下)

# 契约侧: declared (未接线) 段 —— 生态级委派/门禁码在本单机 skill 无消费点,
# 按纪律保留声明, 但必须在注释里写明原因 (见契约 lines 33-41)。
DECLARED = frozenset({"E_GATE_FAILED", "E_DELEGATE_STREAM", "E1004_DELEGATE_CROSSMATCH",  # 门禁码
                      "E1005_DELEGATE_DATA_CLEAN", "E199_INTERNAL"})  # 收敛码


def _contract() -> dict:
    """读错误码契约; 文件缺失直接判失败 (不留静默缺口)。"""
    assert CONTRACT.is_file(), f"契约文件缺失: {CONTRACT}"  # 缺文件即真回归, 不能 skip 成绿灯
    return yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))


def _contract_codes() -> dict[str, str]:
    """契约 codes 段 -> ``{BEST_NNNN: code 字面量}``。"""
    return {key: value["code"] for key, value in _contract()["codes"].items()}  # 键是 BEST_NNNN, 值里的 code 才是码字面量


def _code_constants() -> dict[str, str]:
    """代码侧在定义或实发的错误码 -> ``{字面量: 定义处}``。

    收三处: ``src/ai_tools.py`` 的工具面常量、``src/protocol.py`` 的协议层常量
    (含 ``NameResolveError.code``)、``src/client_paging.py`` 里以字面串下发的
    分页失败码。三处都收, 因为 G1-09 的缺口正是"某处发码而契约没登记"。
    """
    from src import ai_tools, protocol  # 本地: 两个错误码权威层 (导入即证明符号存在)
    found: dict[str, str] = {}  # 码字面量 -> 定义处, 供失败信息点名
    for module in (ai_tools, protocol):  # 两个模块都要扫: 同一字面量在两处各有一份常量
        for name in dir(module):  # 扫模块级属性: 错误码都以 E_ 前缀常量暴露
            value = getattr(module, name)  # 取值: 下面按类型筛, 非字符串直接放过
            # 只收形如 E_XXX 的字符串常量: 排除函数/类/其他类型, 也排除误命中的业务字段
            if name.startswith("E_") and isinstance(value, str):  # 双重判据: 前缀定语义, 类型定形态
                found.setdefault(value, f"{module.__name__}.{name}")  # setdefault: 同字面量只记第一处定义
    found.setdefault(getattr(protocol.NameResolveError, "code", ""), "src.protocol.NameResolveError.code")  # 类属性上的码也算一处
    return {k: v for k, v in found.items() if k}  # 剔掉空键: NameResolveError.code 缺失时不留空串真源


def _docstring_nodes(tree: ast.AST) -> set[int]:
    """该模块里全部 docstring 常量节点的 id。

    docstring 在 AST 里就是普通字符串字面量, 所以"剔注释"是白送的 (注释压根不进
    语法树), "剔 docstring"必须按节点做 —— 靠 ``isinstance(node, ast.Expr)`` 之类
    的位置猜测会在 ``X = "E_FOO"`` 旁边误伤。
    """
    out: set[int] = set()  # 节点 id 集合: 按对象身份比, 不用字符串内容 (两个 docstring 内容可能相同)
    for node in ast.walk(tree):  # 逐节点找"身兼语句与字符串"的位置: 那正是 docstring
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):  # 只有这四类容器有 docstring 位
            continue
        body = getattr(node, "body", None)  # 取体首行: docstring 只能在第一位
        if (body and isinstance(body[0], ast.Expr)  # 位置 + 形态双判
                and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str)):  # 必须是纯字符串常量
            out.add(id(body[0].value))  # 记下这个常量节点的 id
    return out  # 交给调用方从全集里减掉


def _code_string_literals(path: Path) -> set[str]:
    """文件里"真代码"中的字符串字面量全集 (docstring 剔除, f-string 片段计入)。

    这是死码防线的立足点。旧判据是 ``code in path.read_text()`` —— 对整份文件文本
    做子串匹配, 于是注释与 docstring 里提过一次的死码照样算"有人引用", 防线从
    旁边漏过去 (Q8 报告 §3 的构造: 一个只有注释与 docstring 提到
    ``E_FAKE_TOTALLY_UNREFERENCED`` 的文件让原判据恒真)。

    口径边界 (写明免得日后误以为它比实际更严):
      - 计入: ``E_X = "E_X"`` 定义、``raise ValueError("E_X: ...")`` 这类把码写进
        错误文案的字面量, 以及 f-string 的**常量片段**。凡是以字符串常量形态出现
        的码名都算引用, 匹配按标识符边界做 (见 :func:`_code_references`)。
      - 不计: 注释 (不进语法树)、docstring (按节点剔除)。
      - 不计: 以变量插值形态出现的码名 —— ``f"{E_NO_SQLID}: ..."`` 里的
        ``E_NO_SQLID`` 是 ``ast.Name``, 不是字面量。这不是漏判, 而是"该码的字面量
        在它的定义处 (src/protocol.py) 就已命中"; 换个角度说, 本判据认的是
        **码字面量在代码里在场**, 不判"该常量在别处被调用了几次"。
      - 仍计: 纯日志/文案里的码名。这是刻意保留的 —— 生产诊断信息里出现码名
        本身是有意为之的维护动作, 把它判成"死码"会逼人删掉有用的日志。
    残留弱点 (不掩盖): 契约码只要在 src/ 里有**定义处**就算"有引用", 即"定义了
    但全仓无人调用"这一形态仍在本判据射程之外 —— 这与原判据同源, 不是本次改写
    引入的退化; 要收这一半需要另立"常量零调用"门禁, 不在本轮范围。
    """
    tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"), filename=str(path))  # 解析失败向上抛: 语法错归编译门禁, 不降级成"无引用"
    docs = _docstring_nodes(tree)  # 先算 docstring 节点集
    literals: set[str] = set()  # 代码侧字符串字面量全集
    for node in ast.walk(tree):  # 逐节点收字符串
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docs:  # 纯字符串常量且非 docstring
            literals.add(node.value)  # 收进全集
        elif isinstance(node, ast.JoinedStr):  # f-string 在 AST 里是拼接节点, 不含 Constant 分支
            for part in node.values:  # 逐个片段看: 只有常量片段是字面量, 插值表达式不算
                if isinstance(part, ast.Constant) and isinstance(part.value, str):
                    literals.add(part.value)  # f-string 里的错误文案前缀也是真实代码痕迹
    return literals  # 交给调用方做等值匹配


def _code_references(files: list[Path], code: str) -> list[Path]:
    """在 ``files`` 里找出**以真代码字面量**引用了该码的文件。

    匹配在"真代码字面量"这一层做 (见 :func:`_code_string_literals`), 而不是全文文本;
    在字面量内部再按**标识符边界**匹配, 而不是裸子串。两层各挡一类假绿:

      - 第一层挡注释与 docstring —— ``code in read_text()`` 会把一句注释算成引用,
        于是死码只要被人提过一句就判"活着" (Q8 报告 §3 的构造)。
      - 第二层挡同前缀的另一个码 —— 裸子串会让 ``E_NO_SQLID_V2`` 冒充
        ``E_NO_SQLID``, 于是真正没被引用的那条被判成有引用。边界用"码名首尾
        不得紧邻标识符字符"表达, 所以 ``"E_NO_SQLID: 未回会话号"`` (冒号在前缀后)
        算命中, ``"E_NO_SQLID_V2"`` (下划线紧邻) 不算。
    """
    pattern = re.compile(rf"(?<![A-Za-z0-9_]){re.escape(code)}(?![A-Za-z0-9_])")  # 边界环视: 码作为完整标识符出现才算
    hits: list[Path] = []  # 命中清单: 逐文件累积
    for path in files:  # 按序扫, 命中即收
        if any(pattern.search(literal) for literal in _code_string_literals(path)):  # 任一真代码字面量里出现即算引用
            hits.append(path)  # 收进清单
    return hits  # 交给调用方判红绿


class TestCodeConstantsAreRegistered:
    """方向一 (G1-09 本体): 代码里在用的码必须在契约里有条目。"""

    @pytest.mark.parametrize("code", sorted(_code_constants()))  # 收集期展开: 每个码一条用例, 失败时点名是哪一个
    def test_code_constant_is_in_the_contract(self, code):
        """逐个码断言: 代码常量出现在契约 codes 段的某个 ``code`` 字段里。

        失败信息必须点名是哪个码: "少登记一个" 只有被指名才看得见。
        """
        registered = set(_contract_codes().values())  # 契约登记的码字面量全集
        assert code in registered, (  # 断言即门禁: 缺一条即红
            f"错误码 {code!r} (定义于 {_code_constants()[code]}) 代码在用但契约无条目 —— "
            f"契约已登记: {sorted(registered)}"
        )


class TestContractCodesAreUsedOrDeclared:
    """方向二: 契约里的码要么代码引用, 要么在 declared 段显式说明未接线。"""

    @pytest.mark.parametrize("best_id,code", sorted(_contract_codes().items()))  # 逐条 BEST_NNNN 展开
    def test_contract_code_is_referenced_or_declared(self, best_id, code):
        """契约码不得既无人引用又无未接线说明 (否则是纯装饰)。

        2026-10-05 R5-02 改写: 原判据是 ``code in p.read_text()`` 的全文子串匹配,
        把写在注释/docstring 里的码名也算成代码引用, 于是"死码防线"能被一句注释
        击穿 (Q8 报告 §3)。现在走 AST 符号面 —— 只认真代码里的字符串字面量, 且
        要求全等。反例见 :meth:`TestCriterionCounterExamples.test_comment_only_mention_is_not_a_reference`。
        """
        if code in DECLARED:  # declared 段是纪律刻意保留的, 不是缺口
            pytest.skip(f"{best_id} ({code}) 是 declared 段刻意保留的未接线码, 依据见契约注释")  # 显式跳过并写明依据
        files = sorted((CONTRACT.parents[1] / "src").rglob("*.py"))  # 递归扫: 码可能定义在任意深度; 排序让报错次序跨机可复现
        assert files, "src/ 下无 .py 文件 — 扫描语料为空, 本门禁已失效"  # 空语料时"无引用"恒成立, 必须先断语料
        src_hits = _code_references(files, code)  # 符号面等值匹配: 注释与 docstring 一律不算引用
        assert src_hits, f"{best_id} ({code}) 契约登记了但 src/ 代码里无任何引用 —— 删条目或在 declared 段写明未接线原因"  # 死码防线


class TestCriterionCounterExamples:
    """判据自证: 把 Q8 §3 的假绿构造固化成回归用例 (防空转闸)。

    这组用例不测生产代码, 只测**判据本身**。存在的理由: 原判据在被写下的当天就
    已经能假绿, 而当时没有任何用例能在"判据被击穿"这个状态下把它照出来。判据
    强度是测试可信度的一部分, 与被测对象同等对待。
    """

    def test_comment_only_mention_is_not_a_reference(self, tmp_path):
        """Q8 §3 构造: 只在注释与 docstring 里提到某码的文件, 必须判为**无引用**。

        原判据 ``code in read_text()`` 对这份文件返回 True, 即死码只要有人留了
        一句注释就判"活着"。修法必须让同一份文件返回 False。
        """
        fake = "E_FAKE_TOTALLY_UNREFERENCED"  # 假码: 不在契约里, 只为喂判据
        decoy = tmp_path / "fake_module.py"  # 诱饵文件: 整份源码只有注释与 docstring 提到该码
        decoy.write_text(
            f"# 历史遗留: 曾计划接入 {fake}, 后来没做\n"
            f"def helper(x):\n"
            f'    """docstring 里也提一句 {fake}, 同样不算引用。"""\n'
            f"    return x + 1\n",
            encoding="utf-8")  # 逐字取 Q8 的构造: 零代码引用, 一条注释 + 一条 docstring
        assert not _code_references([decoy], fake), (  # 判据必须判否
            "判据把只含注释/docstring 提名的文件判成有引用 —— 死码防线被注释击穿 (Q8 §3 构造未复现为红)"
        )

    def test_real_code_use_is_still_a_reference(self, tmp_path):
        """阳性对照: 真正用上该码的两种形态必须判为**有引用**。

        没有这条, 上一条可以靠"判据恒否"作弊变绿 —— 那就是把假绿换成漏报。
        """
        fake = "E_FAKE_BUT_REAL"  # 另一枚假码: 这次要被真用上
        defined = tmp_path / "defined.py"  # 定义形态: 常量赋值
        defined.write_text(f'{fake} = "{fake}"\n', encoding="utf-8")  # 仓内最常见的形态
        raised = tmp_path / "raised.py"  # 使用形态: 错误文案带码前缀
        raised.write_text(f'class E:\n    pass\n\n\nraise E("{fake}: 阶段 1 未回会话号")\n', encoding="utf-8")  # 码写进错误文案
        fstring = tmp_path / "fstring.py"  # f-string 形态: 码以**常量片段**出现
        fstring.write_text(f'class E:\n    pass\n\n\nraise E(f"{fake}: 阶段 1 未回会话号")\n', encoding="utf-8")  # 片段是字面量, 故应命中
        assert _code_references([defined], fake), "判据漏掉了常量定义形态的引用"  # 定义即引用
        assert _code_references([raised], fake), "判据漏掉了 raise 文案里的码引用 (字符串字面量形态)"  # 使用即引用
        assert _code_references([fstring], fake), "判据漏掉了 f-string 常量片段里的码引用"  # f-string 片段即引用
        assert not _code_references([defined], "E_SOMETHING_ELSE"), "判据把不相关的码也判成命中"  # 阴性对照: 不能靠"来者不拒"蒙对

    def test_same_prefix_other_code_does_not_count_as_a_reference(self, tmp_path):
        """同前缀的另一个码不得冒充目标码 (旧子串判据的第二类假绿)。

        目标 ``E_FAKE_TARGET`` 在源里一次都没出现, 只出现了
        ``E_FAKE_TARGET_V2`` —— 裸子串会命中, 于是真正没人用的码被判成"有引用"。
        这一条是"把假绿改成真绿"的另一半: 只挡注释而不挡同前缀, 判据仍会假绿。
        """
        target = "E_FAKE_TARGET"  # 目标码: 契约里有、生产代码里没用
        decoy = tmp_path / "decoy.py"  # 诱饵文件: 只出现同前缀的另一枚码
        decoy.write_text('OTHER = "E_FAKE_TARGET_V2: 另一条链的码"\n', encoding="utf-8")  # 真代码字面量, 但不是目标码
        assert not _code_references([decoy], target), (  # 必须判否
            "同前缀的另一枚码 (E_FAKE_TARGET_V2) 冒充了 E_FAKE_TARGET —— 判据退化成裸子串匹配 (Q8 §3 第二类构造)"
        )

