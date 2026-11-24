# -*- coding: utf-8 -*-
"""verify_doc_consistency.py — 注释与代码结构一致性门禁 (只读不写; make audit 硬门禁之一)。

两类检查, 都取高置信形态以免制造噪声:

A. STRUCT — **结构声明漂移**: 模块 docstring 里的编号清单条数, 与文件里实际
   顶层分节横幅 (``# ── N.``) 的最大序号不一致。
   本条检查的存在理由: 覆盖面**只能**从 docstring 读到, docstring 少列几条,
   下面那些分节就等于从未被任何 docstring 提及 —— 靠 docstring 判断门禁覆盖面的
   人会严重误判。例: ``verify_crossrefs.py`` 的 docstring 一度只列 4 条
   (原文写的是"核实四类引用"), 而文件实际有 9 个分节 —— 第 5~9 项 (manifest 路径 /
   __all__ 解析 / env 三方 / error-codes 契约 / 治理文档反引号路径) 从未被任何
   docstring 提及 (该 docstring 现已按九类逐条重写)。

B. DEADPARAM — **假用途声明**: docstring 显式为某形参写了说明, 但该形参在函数
   体内**零引用**; 且说明里**没有**"不使用/不参与/占位/签名对齐"这类免责措辞。
   免责措辞的存在是刻意的: 桩替身写"替身不使用, 只为签名对齐"是**诚实声明**,
   应当放行; 而 ``best_export.download_file`` 声明的"仅日志上下文"在函数体里连
   一行日志都没打, 属假声明, 必须拦。

退出码: 任一发现即非零 (供 make audit 接线)。

职责: 拦住两类"注释说谎" —— 一是 docstring 声称覆盖的结构与代码实际结构不符,
  二是 docstring 为某个形参写了用途、而函数体里根本没引用它。度量对象是 AST 上
  的定义节点加 docstring 文本本身, 不碰文件内容, 因此是纯只读门禁。
所属子系统: 仓库治理层 ops/audit/ 的**硬门禁**之一 (make audit 接线)。它是本仓
  注释体系的守门人: comment_audit 管"注释够不够", 本工具管"注释说的对不对"。
  上游无代码依赖; 下游是 make audit 与 CI, 以及依赖注释判断门禁覆盖面的读者。
对外接口: main() -> int (issues 非空即非零); check_struct / check_dead_params /
  parse_file 是可外部依赖的 seam —— ``issues`` 是模块级累加列表, 重复调用
  main() 不会自动清空, 单测里必须自己处理这一点。
依赖与数据流: 输入只有工作区的 .py 源文本, 不读 git、不读任何登记簿、不落盘;
  结果经 stdout 逐条 ``[KIND] 位置 说明`` 打印 + 退出码外传。
关键契约与不变量: 判据只取高置信形态 —— STRUCT 要求 docstring 条目 >=2 且分节
  横幅 >=2 才比, DEADPARAM 要求 docstring 确实写了 ``名: 说明`` 才比。宁可不报也
  不误报是这个门禁的设计前提: 一个爱误报的门禁, 大家就会习惯性忽略它, 那才是
  真正的 fail-open。退出码口径是"发现数是否为 0", 与 issues 列表同步累积。
陷阱与边界: 写本文件的注释时最容易踩两件事 —— 一是别在模块 docstring 里写编号
  清单 (本文件没有 ``# ── N.`` 分节横幅, 写了会被自己的 STRUCT 判据判红),
  二是别为没在函数体里引用的形参写 ``名: 说明`` 格式的行 (会被自己的 DEADPARAM
  判红), 确实没用的形参必须带"不使用/占位/签名对齐"这类免责措辞。
  另外 issues 用的是 re.M 的行首匹配, 所以 docstring 里任意一行以 ``word:`` 开头
  都会被当成形参说明, 写"职责:"这类字段名时要注意别撞上真实形参名。
"""
from __future__ import annotations

# 标准库: AST 解析 (结构与引用判定) / io 统一按 utf-8 读盘 / re 正则 /
# pathlib 仓根定位 (目录遍历已整体交给 scan_roots, 本文件不再自己 walk)
import ast
import io
import re
from pathlib import Path

# 本地: 扫描面 (哪些 .py 进门禁) 的唯一真源。同目录兄弟模块, 按同目录裸名导入 ——
# 直跑本文件时 sys.path[0] 就是 ops/audit/, 走 ops.audit. 包路径会在直跑时
# ModuleNotFoundError。覆盖面**不写在本文件**: 2026-10-05 判据审计 D5-01 实测,
# 目录白名单漏掉 agents/ 时那片的注释/结构不一致全门禁判绿, 且同款白名单被
# 四道门禁各抄一份 —— 一处缺口同时废掉四条判据。
from scan_roots import iter_py_files, require_nonempty_scan  # noqa: E402  同目录裸名导入, 理由见上方四行

ROOT = str(Path(__file__).resolve().parents[2])  # 仓根上溯两级; 硬编码绝对路径换机即失效

# 顶层分节横幅: 行首 # + 至少两个装饰字符 + 序号 (只认顶格, 避开函数内编号注释)
BANNER = re.compile(r"^\s*#\s*[─-═=\-_*]{2,}.*?(\d{1,2})\s*[.、)]")  # 只认顶格: 函数内的编号注释不是分节, 认进来全是噪声
# docstring 内的编号清单条目
NUMLIST = re.compile(r"^\s*(\d{1,2})[.、)]\s+\S", re.M)              # 编号清单形态: "1. " / "1、 " / "1) " 三种都认, 否则中文文档里最常见的那种会被漏
# 形参说明条目: "name: 说明" (Google 风格 docstring)
DOCPARAM = re.compile(r"^\s*(?:\*\*)?([A-Za-z_][A-Za-z0-9_]*)(?:\*\*)?\s*[:：]\s*(\S.{0,70})", re.M)  # 参数说明行: 抓 "name: 含义" 的行尾, 用来核对 docstring 声明与签名是否一致
# 免责措辞: 出现任一即视为"诚实声明未使用", 放行
DISCLAIMER = re.compile(                                                           # 免责声明正则: "注意"/"Note"/"Disclaimer" 都要覆盖
    r"(不使用|未使用|不消费|不参与|不检查|占位|忽略|签名对齐|替身|桩不|仅用于对齐|"
    r"不落盘|由调用方|不参与 IO|基类默认|unused)",
    re.I,                                                                         # IGNORECASE: 免责声明里 "Note"/"注意" 两种写法都要覆盖
)

issues: list[str] = []  # 模块级累加器: 换来解析失败也能留下证据这一点


def parse_file(path: str) -> tuple[str, ast.AST] | None:
    """按 utf-8 读盘并解析; 语法错误记 [PARSE] 并跳过。

    返回 (原始文本, 语法树) 或 None。原始文本要原样带回, 因为 STRUCT 判据要
    在**全文** (含注释) 上找分节横幅, 那是词法层的信息, AST 里拿不到。
    """
    raw = io.open(path, "rb").read().decode("utf-8", "replace")  # errors 用 replace 而非忽略: 坏字节不该让整轮扫描停摆
    try:
        return raw, ast.parse(raw)
    except SyntaxError as exc:
        # 记 PARSE 而不是静默跳过: 坏文件本身就是问题, 静默会让"零发现"变成
        # "什么都没扫到" (铁律 5 禁 fail-open)
        issues.append(f"[PARSE] {path}: {exc}")  # 记 PARSE 不静默跳过, 否则零发现与什么都没扫到同形
        return None


def check_struct(rel: str, raw: str, tree: ast.AST) -> None:
    """docstring 编号清单条数 vs 代码实际分节数。

    作用: 只判"结构性声明漂移"这一类; 发现不一致就往模块级 issues 追加一条
    [STRUCT] 记录, 本函数自身不返回值、不抛异常。
    关键参数: rel 是仓根相对路径 (只用于拼消息前缀); raw 是文件全文, 分节横幅
    只能在这里找 (那是词法信息, AST 树里没有); tree 提供模块 docstring。
    返回: None。抛什么: 都不抛 —— 判据的"宁可不报不误报"是靠 return 早退实现
    的, 不是靠异常。
    """
    doc = ast.get_docstring(tree, clean=False)                                   # 模块头原文: 用 clean=False 取, 首行缩进会影响字符数门槛的判定
    if not doc:                                                             # 没有模块头直接跳过: 缺失由 comment_audit 的 Q1 报, 本门禁不重复计
        return
    items = NUMLIST.findall(doc)                                                             # 编号项清单: 逐条比对「声明了几条」与「实际列了几条」
    if len(items) < 2:  # 少于 2 条不判, 单条编号清单没有漂移可言
        return
    n_doc = max(int(i) for i in items)  # 取最大序号而非条数, 清单从 1 起编时二者才等价
    banners = {int(m.group(1)) for m in                                        # 分节横幅编号: 形如 "# ── 3." 的行, 用来抓「编号跳号/删除后未同步」
               (BANNER.match(ln) for ln in raw.splitlines()) if m}                         # 生成器表达式里过滤未匹配行: 只有匹配到编号的横幅才进集合
    if len(banners) < 2:                                                                         # 少于两个横幅无从比对: 单横幅文件按无问题处理
        return
    n_code = max(banners)  # 分节数同样取最大序号, 两侧口径必须对称
    if n_code != n_doc:  # 只在两边都自称有分节结构时比, 不等即以代码为准回正 docstring
        issues.append(                                                                 # 报的是「清单条数 vs 横幅最大编号」: 两处口径不同即视为不一致
            f"[STRUCT] {rel}: docstring 列 {n_doc} 项, 代码实际有 {n_code} 个分节"
            f" (以代码为准回正 docstring)"
        )


def check_dead_params(rel: str, tree: ast.AST) -> None:
    """docstring 声称用途但函数体零引用的形参 (排除诚实声明的桩替身)。

    作用: 遍历整棵树里每个函数定义, 把"docstring 写了用途、形参却没用"的情况
    记成 [DEADPARAM]。关键参数 rel 只进消息文本; tree 是唯一的判据来源。
    返回: None (结果累积在模块级 issues)。抛什么: 不抛, 判据不访问 IO, 因此
    解析已由 parse_file 完成, 这里失败只可能是本函数自身的逻辑错误。
    """
    for node in ast.walk(tree):                                                        # 逐个函数走: 参数声明检查只能落在有 docstring 的节点上
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):                      # 只查函数/协程: 类与模块的参数语义不适用这套判据
            continue
        doc = ast.get_docstring(node, clean=False)                                  # 原始 docstring: 参数说明常写在首行之外的段落, 不能只看首行
        if not doc:                                                      # 无 docstring 放过: 缺 docstring 是 Q1 的事, 这里只管「有但写错」
            continue
        args = node.args                                                                       # 取参数列表: 三类形参(位置/关键字/可变)都在内
        params = [x.arg for x in args.posonlyargs + args.args + args.kwonlyargs]  # 五类形参都收, 漏 vararg 就永远抓不到 *args 的假声明
        if args.vararg:                                                             # 可变位置参数: *args 的名字同样要在 docstring 里有说明
            params.append(args.vararg.arg)                                                          # 可变位置参数名
        if args.kwarg:                                                                        # 可变关键字参数: **kwargs 同理, 常被漏写
            params.append(args.kwarg.arg)                                                           # 可变关键字参数名
        if not params:                                                                              # 一个参数都没有: 无参数可核, 直接放过
            continue
        body = list(node.body)                                  # 从 body 切掉 docstring 自身: 它是 Expr 节点, 混进来会把 docstring 当参数名
        if body and isinstance(body[0], ast.Expr) and isinstance(  # 摘掉 docstring, 否则里面出现的形参名会被当成引用, 判据永远为假
            body[0].value, ast.Constant                                                   # 确认首条就是 docstring: 结构不符就跳过, 不硬解
        ):
            body = body[1:]                                                                       # 剩余的才是真参数名: 局部变量已在上一步过滤
        used = {n.id for n in ast.walk(ast.Module(body=body, type_ignores=[]))  # 用 Name 集合而非源码子串, self.x 与字符串同名字符都不算引用
                if isinstance(n, ast.Name)}                                                 # 参数名集合: 供下一步与 docstring 声明做差集
        docmap = {m.group(1): m.group(2).strip() for m in DOCPARAM.finditer(doc)}  # 同名条目后写的覆盖先写的, 判据只关心有没有声明
        for prm in params:                                                                 # 逐参数核对: 报的是「docstring 声明了它, 函数体却零引用」
            if prm in ("self", "cls") or prm in used:  # self/cls 是绑定约定, 不算对形参的用途声明
                continue
            claim = docmap.get(prm)                                                              # 取该参数的声明行: 报出来要能直接定位改哪一行
            if not claim or DISCLAIMER.search(claim):  # 没写等于无声明可查; 带免责措辞等于诚实声明, 两种都放过
                continue
            issues.append(                                                       # 报的是「docstring 为某形参写了说明, 但该形参在函数体内零引用」
                f"[DEADPARAM] {rel}:{node.lineno} {node.name}(... {prm} ...): "     # 反向的「docstring 声明了签名里没有的参数」本判据不查, 交人工判读
                f"docstring 称「{claim[:60]}」但函数体内零引用"
            )


def main() -> int:
    """扫描全仓 .py (扫描面由 scan_roots 给出), 汇总两类发现。

    作用: 遍历共享扫描面给出的每个 .py, 先 parse_file 再依次跑两个检查, 末尾打印
    扫描数与发现数, 并用发现数是否为空决定退出码。关键输入全来自模块级常量。
    返回: int (0 = 干净, 1 = 有发现)。抛什么: 读盘 OSError 不捕获 —— 读不到
    文件意味着这次扫描不完整, 报 0 个发现就是假绿。
    """
    scanned = 0                                                                               # 计数从零开始: 报告里的"扫描 N 个文件"取自这里
    py_files = iter_py_files(ROOT)  # 扫描面先落变量: 负对照闸与遍历用同一份清单
    # 负对照 (2026-10-07): 本门禁实测会在「扫描 0 个 .py」时打印该行却仍 exit 0 ——
    # 打印扫描数给人看是好的, 但退出码没跟上, 于是 make audit 照样判绿。闸把两者绑在一起。
    if not require_nonempty_scan("verify_doc_consistency", [rel for rel, _full in py_files]):
        return 1
    for rel, full in py_files:  # 覆盖面由共享真源给出: 仓内全部 .py (排除项见 scan_roots 模块头)
        parsed = parse_file(full)                                                        # 解析一次: 同一份内容要喂给结构检查与参数检查
        if parsed is None:                                           # 解析失败记 None: 语法错由 count_code_lines 判红, 这里不重复
            continue
        raw, tree = parsed                                                                  # 解包原文与语法树: 两个检查各取所需
        scanned += 1  # 只数解析成功的, 坏文件已在 parse_file 里记过 PARSE
        check_struct(rel, raw, tree)                                                        # 结构一致性: 清单条数 vs 横幅编号
        check_dead_params(rel, tree)                                                  # 死参数: docstring 声明了它, 函数体却零引用
    # 打印扫描数是刻意的: 读者据此判断"0 发现"是真干净还是根本没扫到文件
    print(f"扫描 {scanned} 个 .py")  # 先打扫描数, 读者据此判断零发现是真干净还是没扫到
    print(f"发现 {len(issues)} 个注释/结构不一致:")
    for item in issues:                                                                         # 统一打印: 报告要给人判读, 不能只落 JSON
        print(" -", item)
    return 1 if issues else 0  # 退出码 = 发现数是否为 0, 与模块级 issues 同步累积


if __name__ == "__main__":
    raise SystemExit(main())
