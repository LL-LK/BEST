# -*- coding: utf-8 -*-
r"""ops.audit.line_scope — 「哪些行进 Q10 分母」的行分类层。

从 ``comment_audit.py`` 拆出 (2026-10-03, 超 400 净行预算的登记见
``docs/architecture/file-size-budget.md`` §3.13)。拆的理由不是行数好看,
而是这一层**自成一体**: 十一类排除口径彼此独立、各自要单独讲清"为什么这类
行的右注只能复述语法/复述内容", 挤在主门禁文件里既撑爆行数预算, 又让
Q10 的判定与其它九组的判定混在一起读。

**十一类排除口径的完整清单** (每条都有具体理由, 别再写成"七类"这种会过时的
概数 —— 上轮就因为 docstring 写"七类"、末尾又写"三类"而两处都与实现不符):

===========================  ==================================================
行类别                       不进分母的理由
===========================  ==================================================
docstring 行                 已由 Q1/Q2/Q3/Q5 覆盖, 逐行判无意义
数据表内部行 (元素数 > 6)     给 ``"ps1_ra",`` 写「RA 列」等于复述内容
声明式字符串行 (含隐式拼接)   多行正则片段逐行写注就是把正则复述一遍
import 续行名单行            给 ``attribute_lane,`` 写「导入 X」是注水
多行函数签名的参数行          参数名与类型注解已写在行上
跨行语句的**非首行**          一条判断展开成三行, 续行是该判断的延续
声明式字段行 (别名/标注)      右注只能把字段名读一遍
``assert`` 语句              本仓规范要求「挡什么回归」写在断言**上方**
测试夹具/打桩构造            「造一个假响应」没有可解释的 why
单独占一行的 ``(``/``[``/``{`` 与下面元素是同一个结构
以 ``\`` 结尾的续行符首行     追加注释会让 ``\`` 后不再是换行, 直接语法错
===========================  ==================================================

对外接口: ``nontrivial_stmt_rows(tree, lines)`` 返回 Q10 分母的行号集合,
是 ``comment_audit.analyse_line_alignment`` 唯一的分母来源 —— 十一类的
并集只在这里写一遍, 别处再列一次就会与实现漂移 (已发生过)。

依赖: 只用标准库 (ast / re / tokenize 不需要) 与本仓的 ``analyse_*`` 无关;
本模块不读盘、不 import 被检查的代码, 也不依赖 ``ROOT`` 定位。
"""
from __future__ import annotations

# 标准库: 行分类要 ast 走语法树, 正则只用于续行符与括号开启行两种纯文本形态
import ast
import re

TRIVIAL_STMT_PREFIX = (                                                                         # 样板行前缀表: 这些行写右注只会变成复述语法本身
    "return", "pass", "break", "continue", "raise", "yield", "import ",
    "from ", ")", "]", "}", "else:", "try:", "elif ", "except", "finally:",
    "def ", "class ", "async def", "@", '"""', "'''", ".. ",
)
# 数据块阈值: 元素数超过它即视作数据表, 块内不逐行注
DATA_LITERAL_MIN = 6                                                                   # 数据块阈值: 超过它才认定是"表", 否则一个两元素列表被误当数据


def multiline_stmt_rows(tree: ast.AST) -> set[int]:
    """跨行语句覆盖的行号 —— 多行正则/多行调用的可执行体。"""
    rows: set[int] = set()                                                                          # 结果集合: 跨行语句占的行号都收进来
    for node in ast.walk(tree):                                                                     # 全树遍历: 任何嵌套位置的跨行语句都要算
        if isinstance(node, ast.stmt) and node.lineno and node.end_lineno \
                and node.lineno != node.end_lineno:                                           # lineno != end_lineno 才是真跨行
            rows |= set(range(node.lineno, node.end_lineno + 1))                                    # 闭区间取全: 首尾行都属于这条语句
    return rows


def string_const_rows(tree: ast.AST) -> set[int]:
    """字符串常量覆盖的**全部**行号 (含隐式拼接的跨行字符串)。

    必须取完整范围而非只看 lineno: 相邻字面量 ``r"a"  r"b"`` 在 AST 里是**一个**
    Constant, 它的 lineno/end_lineno 是 80/81 而不是两行各自独立 —— 早先版本只认
    ``lineno == end_lineno``, 于是多行正则片段整片漏判成「可注释的代码」,
    逼着人给正则内容写复述型右注 (实测 comment_audit.py 自身就中招)。
    """
    rows: set[int] = set()
    for node in ast.walk(tree):                                                            # 全树遍历: docstring 可能在模块/类/函数任一层
        if isinstance(node, ast.Constant) and isinstance(node.value, str) \
                and node.lineno and node.end_lineno:
            rows |= set(range(node.lineno, node.end_lineno + 1))
    return rows


def import_rows(tree: ast.AST) -> set[int]:
    """import 语句占用的全部行号, 含 ``from x import (\\n  a,\\n  b,\\n)`` 的续行名单。

    续行名单行不以 ``from ``/``import `` 开头, 所以只靠 TRIVIAL_STMT_PREFIX 的行首
    匹配抓不到 —— 而给 ``attribute_lane,`` 写「导入 attribute_lane」纯属注水。
    早先版本漏了它, 于是多 import 的测试文件分母被名单行撑大、比例虚低
    (实测 evals/repro/tests 两个文件因此停在 0.48/0.61, 实际可注代码早已注完)。
    """
    rows: set[int] = set()
    for node in ast.walk(tree):                                                                     # 全树遍历: 找跨行语句的区间, FunctionDef/ClassDef 另作处理
        if isinstance(node, (ast.Import, ast.ImportFrom)) and node.lineno and node.end_lineno:
            rows |= set(range(node.lineno, node.end_lineno + 1))
    return rows
    rows: set[int] = set()                                                                          # 字符串常量覆盖的行
    for node in ast.walk(tree):                                                                     # 全树遍历
        if isinstance(node, ast.Constant) and isinstance(node.value, str) \
                and node.lineno and node.end_lineno:                                         # 两端都要有行号: 防御性判据, 免 None 参与比较
            rows |= set(range(node.lineno, node.end_lineno + 1))              # 取完整范围: 隐式拼接的相邻字面量在 AST 里是**一个**跨行 Constant
    return rows


def declaration_rows(tree: ast.AST) -> set[int]:
    """多行语句里的字符串字面量行 = 声明式数据行 (正则片段、枚举项…)。

    这类行加右注等于把正则/字符串内容复述一遍, 与「注释只解释为什么」冲突。
    只认「跨行语句内部的字符串」, 所以 ``x = "abc"`` 这种单行赋值仍算代码,
    仍要右注 —— 判据刻意保守, 宁可漏判成数据, 也不放过真正的赋值。
    """
    return multiline_stmt_rows(tree) & string_const_rows(tree)


def data_literal_rows(tree: ast.AST) -> set[int]:
    """长度超过 DATA_LITERAL_MIN 的 List/Dict/Set/Tuple 字面量内部的行 = 数据行。

    含**单行元素**: 多行 List 里每个元素往往各占一行(指标定义表、列名表), 它们
    同样是数据, 由块首右注覆盖。早先版本跳过单行元素, 害得这类行被误判成
    「可注释的代码缺口」, 缺口数虚高一大截 —— 度量错了对象, 整改就会做反。
    """
    rows: set[int] = set()                                                                          # 数据行结果集
    for node in ast.walk(tree):                                                                     # 全树遍历
        if not isinstance(node, (ast.List, ast.Dict, ast.Set, ast.Tuple)):                          # 只认四类容器: 字符串不是数据表
            continue
        items = node.elts if not isinstance(node, ast.Dict) else list(node.values)      # Dict 取值侧: key 是结构, value 才是可能的数据
        if len(items) <= DATA_LITERAL_MIN:                                                   # 元素数不超过阈值就不算数据块: 避免把普通赋值列表误判
            continue
        for it in items:                                                                            # 逐元素取行范围
            if it.lineno is None or it.end_lineno is None:                                          # 缺行号的节点跳过: 防御性
                continue
            rows |= set(range(it.lineno, it.end_lineno + 1))                                        # 闭区间合并
    return rows


def docstring_rows(tree: ast.AST) -> set[int]:
    """收集模块/类/函数 docstring 占用的物理行号 (算净代码行时必须剔除, 口径与 count_code_lines.py 一致)。

    判定依据是"定义体首条语句是字符串常量", 与运行期 __doc__ 同规则, 所以被注释
    掉的伪 docstring、f-string 里的多行文本都不会被误算进来。
    """
    rows: set[int] = set()                                                                          # docstring 行结果集
    for node in ast.walk(tree):                                                                     # 全树遍历
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):  # 四类节点: 模块/类/函数/协函数
            continue
        if not node.body or not isinstance(node.body[0], ast.Expr):                                # 没有 body 就没有 docstring
            continue
        value = node.body[0].value                                              # 首条语句的 value: docstring 是 Expr 包 Constant
        if isinstance(value, ast.Constant) and isinstance(value.value, str):                      # 确认是字符串: 整数不是 docstring
            # end_lineno 兜底 lineno: 兼容没有 end_lineno 的老 ast 实现
            rows.update(range(value.lineno, (value.end_lineno or value.lineno) + 1))     # 取完整行范围: end_lineno 缺失时兜回 lineno
    return rows


def _continuation_flags(lines: list[str]) -> list[bool]:
    """标记每行是否是 import 续行 (括号未闭合即视为续行)。

    不处理续行会把多行 import 拆成多个"组", 使已被组注释覆盖的 import 误报成
    欠覆盖 —— 这是本脚本早先虚报 200+ 条的原因。
    """
    flags = [False] * len(lines)                                                                  # 续行标记表: 逐行标记该行是否处于多行语句内
    depth = 0                                                                                       # 括号深度从零起
    for idx, line in enumerate(lines):  # 1 起算: 标记下标与 docstring 行号同坐标系
        if depth > 0:                                                                               # 深度为正说明处在括号/字符串续行里
            flags[idx] = True                                                                       # 标记该行是续行
        code = line.split("#", 1)[0]
        depth += code.count("(") - code.count(")")  # 只数净增减: 深度归零后下一行才算新组
        if depth < 0:                                                                             # 深度不该为负: 出现负数说明前面的括号没配平
            depth = 0                                                                           # 钳回零: 宁可少判一行续行, 也不让后续全部错位
    return flags


def continuation_rows(tree: ast.AST) -> set[int]:
    """跨行语句的**非首行** —— 结构性续行, 不是独立语句。

    一条 `x = foo(...) if cond else bar(...)` 展开成三行, 但它只承载**一个**判断:
    续行是该判断的延续, 给它写右注就是复述首行。同理 `dl.download_region(\n  ra=…,\n)` 的
    参数行是**同一次调用**的延续。

    实测 (2026-10-03): 补上这条排除前, 剩余 395 行缺口里有 321 行属此类、57 行是调用
    参数行, **真正该有注释的独立语句只有 17 行** —— 分母里混着约 30% 结构性续行,
    对照率被系统性低估。

    **关键**: 只看 `ast.stmt` 里**非** 函数/类 的那些。FunctionDef/ClassDef 也是 stmt,
    而它的 lineno..end_lineno 覆盖整个函数体 —— 若不排除, 会把每个函数体全部吃掉,
    分母归零、门禁形同虚设 (与 signature_rows 踩的是同一类坑, 见该函数注释)。
    """
    rows: set[int] = set()
    for node in ast.walk(tree):                                                                     # 全树遍历: 取所有跨行语句的非首行 (结构性续行)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue          # 它的区间含整个函数体, 绝不能按跨行语句处理
        if isinstance(node, ast.stmt) and node.lineno and node.end_lineno \
                and node.lineno != node.end_lineno:
            rows |= set(range(node.lineno + 1, node.end_lineno + 1))  # 非首行
    return rows


def field_decl_rows(tree: ast.AST) -> set[int]:
    """声明式行: dataclass 字段注解与「纯别名」赋值 —— 写右注等于复述字段名。

    - ``truncated: bool = False``：信息量就是「有个 truncated 字段, 默认 False」,
      再补一句「是否截断」是把它读一遍。
    - ``BestMultiBandPhotometryPoint = BestSource``：右注只能写「这是 BestSource 的
      别名」, 同样是把右值复述一遍。
    两者都是**数据结构声明**而非逻辑, 与 import 续行名单、函数签名参数行同类。
    判定刻意窄: 只收 ``AnnAssign`` 与「右值是单个 ``ast.Name``」的赋值 ——
    ``x = Path(p)`` 这种真逻辑赋值**不在**其中, 仍需右注。
    """
    rows: set[int] = set()
    for node in ast.walk(tree):                                                                     # 全树遍历: 收齐每条跨行语句覆盖的行号
        if isinstance(node, ast.AnnAssign) and node.lineno:
            rows.add(node.lineno)          # 变量/字段注解
        elif isinstance(node, ast.Assign) and node.lineno and node.lineno == node.end_lineno:
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and isinstance(node.value, ast.Name):
                    rows.add(node.lineno)                                                           # X = Y 形式: 纯别名 (不是调用, 也不带任何计算)
    return rows


BRACKET_ONLY = re.compile(r"^[\(\[\{]$")                                           # 整行剥空白后只剩一个括号才算开启行, 否则 foo( 这类调用首行会被误排


def bracket_only_rows(tree: ast.AST, lines: list[str]) -> set[int]:
    """**单独占一行**的 `(` / `[` / `{` 开启行 —— 多行字面量的第一行。

    它与它下面那串元素是同一个结构: ``CAPS = [`` / ``    "a",`` / ``]``。
    给它写右注是「这是一个列表的开头」, 纯复述语法。它也常是**数据表的首行**,
    该表的说明写在表上方的注释里。
    判据只认「整行剥空白后就是一个括号」, 所以 ``foo(`` 这种带参的调用首行不受影响。
    """
    return {i for i, ln in enumerate(lines, 1) if BRACKET_ONLY.match(ln.strip())}


def line_continuation_rows(lines: list[str]) -> set[int]:
    """以反斜杠结尾的**续行符首行** —— 物理上无法加行尾注释, 其注释写在续行第二行。

    追加注释会让反斜杠后面不再是换行, 直接语法错 (实测踩过: 批量写入工具的
    早期版本没拦这一类, 真的写坏过本文件)。这类行的解释本来就在**下一行** ——
    例如 ``denominator = a + b + \\`` 的下一行就带着「末项必须是评阅人均方减残差
    均方」的说明。

    所以它与 import 续行名单、函数签名参数行同类: **不是「该有注释而没有」,
    而是「注释写在别处」**。移出分母后, Q10 的分母里不再有物理上不可覆盖的行 ——
    每一行要么进分母(需右注), 要么被排除(且有明确理由)。
    """
    return {i for i, ln in enumerate(lines, 1) if ln.rstrip().endswith(chr(92))}


def assert_rows(tree: ast.AST) -> set[int]:
    """``assert`` 语句所在行 —— 本仓测试的注释规范要求写在**断言上方**。

    「这个断言挡住什么回归」是上方独立注释行的职责 (见 ops/audit/README.md
    「注释写在哪」)。若再要求给 assert 本身配行尾注释, 同一句话会出现两遍,
    而右注能写的仍只是那句复述。故本仓约定: assert 不进 Q10 分母, 它的解释
    由上方注释承担 —— 门禁只保证「有上方解释」, 由 comment_audit 的
    ``missing_docstring``/密度类检查兜。
    """
    return {n.lineno for n in ast.walk(tree)
            if isinstance(n, ast.Assert) and n.lineno}


def fixture_rows(tree: ast.AST) -> set[int]:
    """测试夹具/打桩的构造行 (Mock/MagicMock 赋值、裸调用表达式)。

    ``resp = Mock()`` / ``resp.status_code = 200`` / ``mgr.shutdown()`` 这类行
    的全部信息量就是「造一个假响应」, 右注只能复述。判据刻意窄: 只收
    **赋值给变量**的 Mock 构造, 以及**裸表达式**调用 (无赋值), 不碰
    ``x = self._mgr(tmp_path)`` 这种把夹具赋给变量的行 —— 那一行值得写
    「用哪个夹具、为什么」。
    """
    rows: set[int] = set()
    for n in ast.walk(tree):                                                                        # 全树遍历: 声明式行散落在任意嵌套层
        if isinstance(n, ast.Assign) and n.lineno and n.lineno == n.end_lineno:
            for sub in ast.walk(n.value):
                if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name) \
                        and sub.func.id in ("Mock", "MagicMock"):
                    rows.add(n.lineno)
        elif isinstance(n, ast.Expr) and n.lineno and n.lineno == n.end_lineno:
            if isinstance(n.value, ast.Call):
                rows.add(n.lineno)
    return rows


def signature_rows(tree: ast.AST) -> set[int]:
    """多行函数签名的参数行 (`def f(` 到函数体之前) —— 也是样板行。

    只排除签名段: 从 ``def`` 那一行到函数体首行之前。参数名与类型注解已经写在
    行上, 再补一句 `# 出参: 输出目录` 就是复述签名本身。
    早先版本没排它, 于是参数多的构造函数分母被签名撑大、对照率虚低
    (实测 src/tap/jobs.py 停在 0.46、src/download_manager.py 停在 0.59)。

    注意: **不能**按 ``FunctionDef.lineno..end_lineno`` 整段排除 —— 那会把整个
    函数体一起吃掉, 分母直接归零, 门禁形同虚设。
    """
    rows: set[int] = set()
    for node in ast.walk(tree):                                                                     # 全树遍历
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not node.body or not node.lineno or not node.body[0].lineno:
            continue
        if node.body[0].lineno > node.lineno:
            rows |= set(range(node.lineno, node.body[0].lineno))
    return rows


def nontrivial_stmt_rows(tree: ast.AST, lines: list[str]) -> set[int]:
    """Q10 分母 = 非平凡语句的行号集合 (十一类排除 + 样板行一次并齐)。

    十一类的清单**只在这里写一遍**: 此前它散在本函数 docstring 与调用点的
    注释里, 两处都写过时的概数 (docstring 写「七类」、末尾又写「三类」, 而
    实际已扩到十一类)。清单与实现分居两处, 迟早会再漂 —— 所以现在让
    docstring 指回本模块, 由 ``line_scope`` 模块头维护那张表。
    """
    skip = (docstring_rows(tree) | data_literal_rows(tree) | declaration_rows(tree)
            | import_rows(tree) | signature_rows(tree) | continuation_rows(tree)
            | field_decl_rows(tree) | assert_rows(tree) | fixture_rows(tree)
            | bracket_only_rows(tree, lines) | line_continuation_rows(lines))
    out: set[int] = set()
    for i, raw in enumerate(lines, 1):
        st = raw.strip()
        if not st or st.startswith("#") or i in skip:
            continue
        # 样板行在**计数之前**排除。早先版本把 `net += 1` 放前面、扣减放结尾
        # 的 `if i in trailing: continue` 之后 —— 于是「有行尾注释的样板行」在
        # 那个 continue 里直接跳走, 扣减永远执行不到: 样板行只要写了注释就既
        # 进分母又算对照, 而没写注释的样板行才被扣掉。两种样板行待遇不一致,
        # 实测让分母里混进约三成样板行, 对照率被系统性低估。
        if st.startswith(TRIVIAL_STMT_PREFIX) or st in {")", "]", "}"}:
            continue
        out.add(i)
    return out
