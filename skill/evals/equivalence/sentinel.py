# -*- coding: utf-8 -*-
"""evals.equivalence.sentinel — 哨兵字典单点静态守护 (Q15 第二类断言)。

纪律: 各实验代码**不得硬编码**哨兵阈值/形态, 必须读
``evals/_data/null_sentinel.yaml`` (唯一共享件)。本模块静态扫描
``evals/`` 下全部实验代码, 命中硬编码形态即列出 (白名单: evals/_data 自身
与 evals/equivalence 的守卫代码)。

三条扫描各管一种**形态** (缺一条就等于放掉一类重复真源):

1. ``scan_hardcoded_sentinels`` —— **数值**形态 (``<= -999`` / ``== -999``),
   配 USub 还原分支, 对负哨兵才真正命中;
2. ``scan_hardcoded_exempt_columns`` —— **字符串集合**形态
   (``frozenset({"pmra", ...})``): 里面没有任何数值字面量, 第 1 条对它恒不命中,
   而它恰恰是"哨兵豁免列"这份真源最容易出现的形态 (2026-10-05 R3 收敛前,
   E5 与 src/models 各抄了一份);
3. ``scan_local_sentinel_readers`` —— **自建读法**形态: 把哨兵字典的文件名写进
   代码 (SENTINEL_PATH / Path(...)), 而不是走 ``load_null_sentinel()``。
   自建读法拿不到 SSOT 的三键校验与 lru_cache: 少一个键照样跑 (fail-open 分裂),
   跑批中改表还会让本实验的数值漂而别的实验不动。

为什么第 3 条按"文件名出现在非 docstring 字符串里"判: docstring / 模块头里
提到该路径是**白盒锚点与契约说明** (本仓大量这么写), 属合法引用; 真正要禁的是
把它写进可执行语句 —— 那才意味着本地另有一套哨兵读法。
"""
from __future__ import annotations

# 标准库: AST 静态解析 / 路径
import ast
from pathlib import Path

EVALS_ROOT = Path(__file__).resolve().parents[1]   # 扫描根: 上溯一级即 evals/, 不依赖 cwd

# 硬编码哨兵形态 (数值字面量; 字符串形态的 -999 出现在断言文本里属合法
# 引用, 只扫**数值比较**面: `<= -999` / `== -999` / `< -999` 之类)
_SENTINEL_LITERALS = {-999, -999.0, -1000, -1000.0, -1004.09}   # int/float 两形态并列收

# 哨兵豁免列的列名 (字符串形态): 这三列是带符号真实物理量, 不参与哨兵判定。
# 本守卫自身必须列出它们 (判据要认得命中什么), 故 evals/equivalence 在白名单内。
_EXEMPT_COLUMN_NAMES = frozenset({"pmra", "pmdec", "radial_velocity"})  # 与 evals/_data 的 exempt_columns 逐字对齐

# 哨兵字典的文件名: 实验代码不得自行锚这个路径 (唯一合法读法是 evals._data.load_null_sentinel)
_SENTINEL_FILENAME = "null_sentinel.yaml"

# 集合字面量的构造名: frozenset({...}) 是"调用包一层", 外层构造名本身不含列名
_COLLECTION_CALLS = frozenset({"frozenset", "set", "list", "tuple"})  # 逐个认: 换一种写法不该让硬编码溜过去

# 守卫白名单: 数据字典自身 + 本守卫 + 说明性文档字符串不算硬编码判定
# (正反斜杠各存一份: 拼出来的路径串在 Windows 与 POSIX 上形态不同)
_WHITELIST_PARTS = ("evals\\_data", "evals/_data", "evals\\equivalence",
                    "evals/equivalence")


def _is_whitelisted(path: Path) -> bool:
    """守卫自身与数据字典不扫 (它们就是单点的载体)。"""
    text = str(path).replace("\\", "/")          # 归一成分隔符再比对, 否则 Windows 路径全部漏判
    return any(part.replace("\\", "/") in text for part in _WHITELIST_PARTS)


def _parse_or_report(path: Path, problems: list[str]) -> ast.AST | None:
    """解析文件; 解析不了即记一条问题 (扫不动必须报, 静默跳过等于放行)。"""
    try:
        return ast.parse(path.read_text(encoding="utf-8"))   # 静态读盘解析, 不 import 被扫模块
    except SyntaxError as exc:
        problems.append(f"{path.name}: 语法错误 {exc}")    # 扫不动即视为违规, 不静默跳过
        return None


def _string_members(node: ast.AST) -> set[str]:
    """节点内的全部字符串字面量 (容器嵌一层也收全)。"""
    return {n.value for n in ast.walk(node)   # 只取字符串常量: 列名以 str 形态写死才叫硬编码
            if isinstance(n, ast.Constant) and isinstance(n.value, str)}


def _collection_literal(node: ast.AST) -> ast.AST | None:
    """取节点代表的集合字面量: ``{..}`` / ``[..]`` / ``(..)`` 或 ``frozenset({..})``; 不是则 None。"""
    if isinstance(node, (ast.Set, ast.List, ast.Tuple)):
        return node                                                # 裸集合字面量
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id in _COLLECTION_CALLS and node.args
            and isinstance(node.args[0], (ast.Set, ast.List, ast.Tuple))):
        return node.args[0]                                        # 构造名包一层: 收内层字面量
    return None


def _code_string_constants(tree: ast.AST) -> list[ast.Constant]:
    """树里全部字符串字面量, 但**剔除裸字符串语句** (即各层 docstring)。"""
    parents: dict[ast.AST, ast.AST] = {}   # 先建父子表: 只有父节点是 Expr 的常量才是裸字符串语句
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[child] = parent
    return [n for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
            and not isinstance(parents.get(n), ast.Expr)]   # 裸字符串语句 = docstring, 是说明不是代码


def _numeric_literal(node: ast.AST) -> float | None:
    """取节点代表的数值字面量; 不是字面量返回 None。

    **为什么必须单列 USub 分支**: Python 把 ``-999.0`` 解析成
    ``UnaryOp(USub, Constant(999.0))``, 而不是 ``Constant(-999.0)``。
    只认 ``ast.Constant`` 的判据因此对**任何**负哨兵恒不命中 —— 而本守卫
    声称扫的恰恰是 ``<= -999`` / ``== -999`` 这类负数形态, 于是它静默失效:
    报出来永远是一份空清单, 读的人只会以为"全仓干净"。这类"检查存在但恒真/
    恒不命中"的守卫比没有守卫更危险, 所以负数取绝对值后按负号还原。
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) \
            and not isinstance(node.value, bool):   # bool 是 int 的子类, 显式排除否则 True 会被当成 1
        return float(node.value)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):     # 一元负号: 取内层再取负
        inner = _numeric_literal(node.operand)
        return None if inner is None else -inner
    return None


def scan_hardcoded_sentinels(root: Path = EVALS_ROOT) -> list[str]:
    """扫描 evals/ 下实验代码的硬编码哨兵比较 (返回违规清单)。"""
    problems: list[str] = []                     # 收全量违规而非首遇即抛, 便于一次扫完当整改清单
    for path in sorted(root.rglob("*.py")):      # 排序保输出确定: rglob 顺序随文件系统变
        if _is_whitelisted(path):                                                                  # 单点载体自己必然硬编码, 先摘出去才不刷屏
            continue                              # 单点载体自己必然"硬编码", 先摘出去
        tree = _parse_or_report(path, problems)
        if tree is None:
            continue                              # 语法错已记账, 不再往下扫
        for node in ast.walk(tree):              # 递归下钻: 比较常嵌在 if 条件里, 只看顶层会漏
            if not isinstance(node, ast.Compare):                                                 # 只认比较节点: 哨兵硬编码的落点必然落在这里
                continue                          # 哨兵硬编码的落点必然是比较节点
            has_sentinel = any(                                                                   # 左右两侧一起查: 常量写在左还是右都是硬编码
                (lit := _numeric_literal(operand)) is not None                                    # 字面量取值: 负数走 USub 还原, 否则负哨兵永远查不到
                and lit in _SENTINEL_LITERALS                                                     # 转 float 再查表: -999 与 -999.0 是同一个阈值
                for operand in [node.left, *node.comparators]                                      # 链式比较的每一段都要查, 不能只看头尾两段
            )                                      # 两侧都查: `-999 > x` 写成常量在左也一样是硬编码
            if has_sentinel:                       # 命中即报, 不判比较方向: 哨兵判定本就双向
                problems.append(                                                            # 带 file:line 记账: 整改时要能直接跳到那一行
                    f"{path.name}:{node.lineno}: 硬编码哨兵比较 (应读 evals/_data/null_sentinel.yaml)")
    return problems


def scan_hardcoded_exempt_columns(root: Path = EVALS_ROOT) -> list[str]:
    """扫描 evals/ 下实验代码硬编码的哨兵**豁免列**集合 (返回违规清单)。

    为什么单列一条: ``scan_hardcoded_sentinels`` 只认**数值**比较, 而豁免列是
    **字符串集合** (``frozenset({"pmra", "pmdec", "radial_velocity"})``), 里面
    一个哨兵数值都没有 —— 原守卫对这份真源恒不命中, 而它恰恰是最容易各抄一份的
    形态: 抄一份后生产新增豁免列, 本实验静默沿用旧集, 真实物理量被当脏值清掉,
    报告里看不出来。

    判据覆盖三种写法: 裸集合字面量 ``{..}`` / ``[..]`` / ``(..)`` 与
    ``frozenset({..})`` 这类构造包装; 只要与豁免列名**有交集**即命中 (抄一半
    也是抄)。
    """
    problems: list[str] = []                  # 空清单 = 通过
    for path in sorted(root.rglob("*.py")):  # 排序遍历: 清单顺序稳定, CI diff 才有意义
        if _is_whitelisted(path):            # 守卫与数据字典自身必然列出列名, 不算违规
            continue
        tree = _parse_or_report(path, problems)
        if tree is None:
            continue                         # 语法错已记账
        seen: set[int] = set()              # 按行去重: frozenset({..}) 的外层 Call 与内层 Set 同行, 只报一条
        for node in ast.walk(tree):          # 递归下钻: 豁免列也可能写在函数体内的局部集合里
            literal = _collection_literal(node)
            if literal is None:
                continue                     # 不是集合字面量形态, 交给别的判据
            hit = sorted(_string_members(literal) & _EXEMPT_COLUMN_NAMES)
            if hit and node.lineno not in seen:
                seen.add(node.lineno)
                problems.append(                                              # 带 file:line 与命中列名: 整改者一眼看出抄漏了哪几列
                    f"{path.name}:{node.lineno}: 硬编码哨兵豁免列 {hit} "
                    f"(应读 evals/_data/null_sentinel.yaml 的 exempt_columns)")
    return problems


def scan_local_sentinel_readers(root: Path = EVALS_ROOT) -> list[str]:
    """扫描 evals/ 下实验代码**自建哨兵读法**的痕迹 (返回违规清单)。

    收敛到 ``evals/_data/`` 之后仍可能复发的一种形态: 实验里自己锚
    ``SENTINEL_PATH`` 并 ``safe_load`` 一遍。它能跑通、值也对, 但拿不到 SSOT 的
    **三键校验** (少一个键照样跑 → fail-open 分裂: E2/E3/E4 炸掉而本实验继续)
    与 **lru_cache** (跑批中改表 → 本实验数值漂而别的实验不动)。这两种后果在
    报告里都看不出来, 只能靠静态判据拦。

    判据: 非 docstring 的字符串字面量里出现哨兵字典文件名即违规 —— 模块头与
    docstring 里提到该路径是**白盒锚点/契约说明** (本仓普遍这么写), 属合法引用。
    """
    problems: list[str] = []                  # 空清单 = 通过
    for path in sorted(root.rglob("*.py")):  # 排序遍历: 清单顺序稳定
        if _is_whitelisted(path):            # evals/_data 自己当然要写这个文件名
            continue
        tree = _parse_or_report(path, problems)
        if tree is None:
            continue                         # 语法错已记账
        for node in _code_string_constants(tree):   # 只看代码里的字符串: docstring 已在层内剔掉
            if _SENTINEL_FILENAME in node.value:     # 文件名出现在可执行语句里 = 本地另有一套读法
                problems.append(                                              # 带 file:line: 违规要能直接跳到那一行看
                    f"{path.name}:{node.lineno}: 自建哨兵读法 (文件名 {node.value!r} 进了代码; "
                    f"应改走 evals._data.load_null_sentinel)")
    return problems


def selftest() -> bool:
    """守卫自证: 当前 evals/ 树必须零硬编码 (三条扫描全过才有清单为空)。"""
    problems = (scan_hardcoded_sentinels()             # 数值形态
                + scan_hardcoded_exempt_columns()       # 字符串集合形态
                + scan_local_sentinel_readers())        # 自建读法形态
    for p in problems:                                                                             # 逐条打印, 自证输出可直接当 CI 日志贴
        print(f"- {p}")                          # 逐条打印, 自证输出可直接当 CI 日志
    return not problems                           # 空清单才通过, 与"有即 FAIL"的语义对齐


if __name__ == "__main__":
    raise SystemExit(0 if selftest() else 1)      # 退出码即门禁码, 可直接串进 make audit
