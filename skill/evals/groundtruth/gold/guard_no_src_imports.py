# -*- coding: utf-8 -*-
"""evals.groundtruth.gold.guard_no_src_imports — GT 独立性质检 (E2 §4.1/§10 守门)。

铁律守门: 静态扫描 gold/ 目录**全部 .py** 的 import 面 —
  1. **严禁** ``src.*`` (被测判定逻辑; 出现即阻断, E2 §10 阻断项 6);
  2. 白名单制: 只允许 math/json/csv/pathlib/hashlib/decimal/yaml/argparse/
     sys/typing/__future__ + ``evals._data`` (数据字典加载件, E2 §4.4) +
     ``evals.groundtruth.gold.*`` (GT 自身分层: gen_gold/gold_algorithms/
     gold_dictionaries — 同目录 GT 代码, 非被测实现);
  3. 禁止相对 import 与动态 import 逃逸 (importlib/__import__/eval/exec)。

退出码: 0 = 干净; 1 = 有违规 (CI 断言, 违规必须修 GT, 严禁放宽门禁)。
用法: python evals/groundtruth/gold/guard_no_src_imports.py [目录或 .py 路径]
"""
from __future__ import annotations

# 标准库: AST 静态解析 (不执行被测脚本) / 路径 / 系统退出码
import ast
import sys
from pathlib import Path

# 白名单 (E2 §4.1: math/json/csv/pathlib/hashlib + 本实现额外所需的最小集;
# ast 是本守卫自身解析 import 面所用, 属质检工具不是被测逻辑)
# 白名单而非黑名单: 新增一个第三方库时必须显式加进来, 于是"顺手 import
# 一个包"会立刻变红, 而不是安静地混进 GT 的依赖面
_ALLOWED_MODULES = frozenset({  # 白名单是显式登记的: 金标准层必须自包含, 不能借 src 的实现
    "__future__", "argparse", "ast", "csv", "decimal", "hashlib", "json", "math",
    "pathlib", "sys", "typing", "yaml",
})

# 允许的非标准库 import 前缀: 数据字典加载件 (纯数据) + GT 自身分层 (同目录)
# 前缀放行而非逐个模块名: 新增一个 GT 分层文件不必改本守卫
_ALLOWED_PREFIXES = ("evals._data", "evals.groundtruth.gold")  # evals._data 是唯一允许的跨实验共享件 (纯数据字典, 不含判定逻辑)

# 动态 import 逃逸面 (ast.Call 的 func 名): 命中即视为规避静态扫描。
# 静态 import 面扫描看不到 importlib.import_module("src.…") 这类写法,
# 不封这个口子, 整个守卫就只挡住老实人
_DYNAMIC_IMPORT_NAMES = frozenset({"__import__", "import_module"})  # 两种形态都封: 裸函数名与 importlib 方法名, 少封一种就留着门
_DYNAMIC_EXEC_NAMES = frozenset({"eval", "exec"})                            # 与 import 名单分开登记: 两类逃逸的处置不同, 混成一张表报出来的信息量少一半


def _is_forbidden(module: str) -> bool:  # 只管 src.* 这一类; 其余越界归 _is_allowed 的白名单, 两职不混
    """被测判定逻辑判定: src.* 或其任何子模块 (E2 §4.1 点名的模块全覆盖)。"""
    # 用 startswith("src.") 连子模块一起盖住: 只挡 "src" 顶层的话,
    # from src.protocol import parse_csv_rows 就能从门禁底下钻过去
    return module == "src" or module.startswith("src.")


def _is_allowed(module: str) -> bool:
    """白名单判定: 标准库最小集 + 数据字典前缀 + GT 自身分层前缀。"""
    if module in _ALLOWED_MODULES:  # 精确匹配顶层模块名, 带点的子模块留给前缀判据
        return True
    # 前缀匹配要带 "." 边界: 否则 "evals._database" 会被 "evals._data" 放行,
    # 这类"名字碰巧开头相同"的目录正是白名单最常见的漏法
    return any(module == prefix or module.startswith(prefix + ".") for prefix in _ALLOWED_PREFIXES)


def _check_import(node: ast.AST) -> list[str]:
    """单 import 节点的违规判定; 返回违规描述列表 (空 = 该节点干净)。"""
    problems: list[str] = []                                                       # 返回列表而非布尔: 一次扫描要给出全部违规, 早返回会漏掉同文件里的第二处
    if isinstance(node, ast.ImportFrom):                             # 两种 import 形态走不同分支: ImportFrom 的 module 与 names 要分开判
        # level>0 即相对 import (from . import x / from ..gold import y):
        # 相对写法能绕过模块名判据, 静态扫不出它到底引的是谁
        if node.level and node.level > 0:  # level=0 是绝对 import, 不算逃逸; 只要带点就归相对 import
            problems.append(f"line {node.lineno}: 禁止相对 import (level={node.level})")  # 带行号: 多文件扫描时, 只有一个行号无法定位到具体文件
        module = node.module or ""
        # names 一并写进违规描述: 违规点常常是"从哪引"而不是"引了什么",
        # 只报模块名会让人来回翻文件
        names = ", ".join(alias.name for alias in node.names)  # 取 alias 而非 asname: 违规在被导入的一侧, 不是绑定的新名字
        label = f"from {module} import {names}"                # 整句还原成源码形态, 报告里能直接复制去改
    elif isinstance(node, ast.Import):
        # 逗号 import 要逐个 alias 判: "import src, math" 里的 math 合法,
        # 但只要有一个 alias 违规, 整条语句就是违规
        for alias in node.names:                                # 逗号 import 逐个 alias 判: 「import src, math」里的 math 合法但整条仍违规
            if _is_forbidden(alias.name):                                      # forbidden 优先报: 它的严重级别高于「不在白名单」, 混报会误导处置方向
                problems.append(                                                    # 描述里带模块名原样: 报告要能照着改, 不必回文件里数第几个 alias
                    f"line {node.lineno}: 禁止 import 被测逻辑 {alias.name!r}")
            elif not _is_allowed(alias.name):
                problems.append(                                                   # 白名单外单列一条: 与 forbidden 分开, 否则看起来像同一类问题
                    f"line {node.lineno}: import 白名单之外 {alias.name!r}")
        return problems
    else:
        return problems
    # ImportFrom 侧: forbidden 优先于 allowed 报错, 因为 src.* 违规的
    # 严重级别高于"不在白名单", 混成一条会让人以为是加个白名单就行
    if _is_forbidden(module):                                             # ImportFrom 侧同样 forbidden 先判: 混成一条会让人以为加白名单就能放过
        problems.append(f"line {node.lineno}: 禁止 import 被测逻辑 {module!r} ({label})")
    elif not _is_allowed(module):
        problems.append(f"line {node.lineno}: import 白名单之外 {module!r} ({label})")
    return problems


def _check_dynamic(tree: ast.AST) -> list[str]:
    """动态 import/exec 逃逸扫描: importlib/__import__/eval/exec 调用即违规。"""
    problems = []                                                                 # 动态逃逸单独收集: 它藏在函数体任意深度, 与 import 面不是同一遍扫
    for node in ast.walk(tree):                                                       # 全树而非只看顶层: 逃逸写在函数体里是最常见写法, 只扫顶层等于留门
        if not isinstance(node, ast.Call):                                               # 只看调用节点: 动态 import 的形态必然是一次 Call
            continue
        func = node.func                                                            # 取被调对象本身: 名字挂在 func 上, args 里没有可比对的东西
        # 先取 id (裸函数名) 再取 attr (方法名), 两种调用形态都要覆盖:
        # __import__ 是前者, importlib.import_module 是后者
        name = getattr(func, "id", None) or getattr(func, "attr", None)  # 裸名走 id、方法走 attr, 两种调用形态各取一次再比名单
        if name in _DYNAMIC_IMPORT_NAMES:                                               # 裸名与 attr 名归到一起后再比名单: 两种调用形态共用一张逃逸表
            problems.append(f"line {node.lineno}: 动态 import 逃逸 {name}()")
        elif name in _DYNAMIC_EXEC_NAMES:
            problems.append(f"line {node.lineno}: 动态执行逃逸 {name}()")
    return problems


def _scan_file(target: Path) -> list[str]:
    """单文件扫描: 语法 + import 白名单 + 动态逃逸; 返回该文件违规列表。"""
    # 只读文本做静态分析, **不执行**被扫文件: 守卫若去 import 它, 本身就
    # 变成了加载被测代码的那一方, 铁律当场作废
    source = target.read_text(encoding="utf-8")         # utf-8 固定: 非 utf-8 文本会被判成语法错误, 变成假红
    try:
        tree = ast.parse(source, filename=str(target))  # 显式传 filename: 语法错信息里要带得是被扫文件名
    except SyntaxError as exc:
        # 语法错误按违规报而不是跳过: 解析不了的 GT 文件等于没被守卫看过,
        # 静默跳过会让"写坏一个文件"变成绕过门禁的手段
        return [f"语法错误 (GT 脚本自身损坏): {exc}"]
    problems: list[str] = []                                                              # 单文件违规先攒后报: 报告要按文件分组, 边扫边打会混成一团
    for node in ast.walk(tree):                                                   # 同样全树 walk: import 写在函数体内的 GT 脚本同样受铁律约束
        if isinstance(node, (ast.Import, ast.ImportFrom)):                                 # 两种形态交给同一个判定函数: 分成两处写必然出现判据不一致
            problems.extend(_check_import(node))  # 逐节点 extend: 同一条 import 可同时报出相对与越界两处违规
    # 动态逃逸单独一遍全树 walk: 它藏在函数体内的任意深度, 不必也不该
    # 只扫顶层
    problems.extend(_check_dynamic(tree))                                          # 独立再跑一遍: 与 import 面分开判定, 合并会让人误以为同一条规则
    return problems


def main(argv: list[str]) -> int:
    """入口: 扫描目标 (默认 gold/ 全目录), 打印违规并返回退出码 (0 干净 / 1 违规)。"""
    # 缺省目标取本文件所在目录而不是 CWD: 从仓库根跑和从 gold/ 里跑
    # 必须扫同一批文件, 否则"换个目录跑就干净了"会成为现成的绕过手法
    target = Path(argv[1]) if len(argv) > 1 else Path(__file__).resolve().parent  # argv[0] 是脚本自身, 用户给的路径从 argv[1] 起读
    if target.is_file():                                                                # 单文件与目录两条路: 显式传 .py 时不该把整个父目录都扫一遍
        files = [target]                                                                        # 单文件不入 rglob: 用户指名了文件就只扫它
    elif target.is_dir():
        # rglob 递归扫子目录: gold/ 下的分层子包同样受铁律约束,
        # 只扫顶层等于给新增子目录留了个后门
        files = sorted(path for path in target.rglob("*.py") if path.is_file())
    else:
        print(f"FAIL: 目标不存在: {target}")
        return 1
    # 目标存在却一个 .py 都没有 → 判 FAIL: 这几乎总意味着路径写错或目录
    # 被清空, 报 OK 等于给"扫了个空目录"发通行证 (无 fail-open)
    if not files:                                                                # 目标存在却零 .py 判 FAIL: 报 OK 等于给「扫了个空目录」发通行证
        print(f"FAIL: 目标下没有 .py 文件: {target}")
        return 1
    all_problems: list[str] = []                                                          # 跨文件汇总一份: 退出码只看它, 边扫边退出会漏掉后面的文件
    for path in files:                                                                     # 按排序后的文件序遍历: 同一批违规两次跑出的报告要逐字相同
        for problem in _scan_file(path):                                                    # 单文件内多条违规逐条带文件名: 只给行号分不清是哪张文件
            # 每条带上文件名: 多文件扫描时只给行号会分不清是哪张文件
            all_problems.append(f"{path.name}: {problem}")
    if all_problems:                                                                    # 有任何一条即 FAIL: 白名单制不承认「大部分合规」这种中间态
        print(f"FAIL: GT 独立铁律被违反 ({len(all_problems)} 处, {len(files)} 个文件):")
        for problem in all_problems:  # 一行一条: 违规条数与文件数已在上方报过, 这里只管可逐项处置
            print(f"  - {problem}")
        print("处置: 修改 GT 代码去掉违规 import — 严禁放宽本门禁 (E2 §10 阻断项 6)")
        return 1
    print(f"OK: {len(files)} 个 GT 文件 import 面干净 "  # 成功也报文件数: 扫了 0 个与扫了 9 个不能显示成同一种 OK
          f"(无 src.* / 无白名单外 / 无动态逃逸): {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
