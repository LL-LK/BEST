"""code_fingerprint.py — 证明"只改了注释/docstring, 代码逻辑零改动"的护栏。

原理: 解析 AST, 把模块/类/函数级 docstring (以及所有 COMMENT token) 剥掉后做规范化
dump 并取哈希。docstring 文本、行内注释、空行的变化不影响指纹; 任何代码结构/字面量/
标识符的变化都会改变指纹。

关键细节: 剥离 docstring 时必须**整条语句删除**而不是替换成 ``Pass`` —— 否则"给一个
原本没有 docstring 的函数新增 docstring"会被误判成代码变更 (插入的 Pass 节点改变了
AST)。整条删除后还要做一次空体归一化:
    有 docstring + 代码  -> [代码...]
    只有 docstring        -> []      -> 归一化为 [Pass]
    只有 pass / ...       -> [Pass]
    只有代码              -> [代码...]
四种形态与"是否写过 docstring"无关, 因此新增/改写 docstring 不影响指纹。

基线取自 git HEAD 的原始内容 (不是工作区快照), 因此可以在改动进行中/完成后随时校验。

用法:
    python ops/audit/code_fingerprint.py check
退出码 0 = 无代码改动; 1 = 有代码改动或被跟踪文件被删除。
"""
from __future__ import annotations

# 标准库: 指纹计算 (结构指纹的哈希层)
import ast
import hashlib
import io
import os
import subprocess
from pathlib import Path

# 仓根 = 本文件上溯两级 (ops/audit/x.py -> ops/audit -> ops -> 仓根)。
# 且必须落在本仓 .git 上: 硬编码父仓路径并拼 `HEAD:astro-best/<rel>` 是错的 ——
# 本仓是独立 git root, 父仓已不再跟踪本目录, 那样 git show 恒 exit 128,
# 251 个 .py 全落进"新增未跟踪"分支, compared 恒为 0, 门禁空转且恒返回 0
# (铁律 5 禁 fail-open)。本文件与 ops/audit/ 其余 10 个工具同口径, 换机可跑。
REPO = str(Path(__file__).resolve().parents[2])  # 独立 git root: 指到父仓就等于拿陈旧基线比
# 扫描面 (哪些 .py 进门禁) 来自同目录 scan_roots: 本文件曾与三道门禁各抄一份同款
# 目录白名单, 判据审计 D5-01 实测白名单漏目录时四道门禁一起判绿, 故收敛为单一真源。
from scan_roots import (  # noqa: E402  同目录裸名导入: 直跑时 sys.path[0] 就是 ops/audit/
    is_excluded_dir,
    iter_py_files,
    require_nonempty_scan,
)


def _git_show(rel_path: str) -> bytes | None:
    """取 git HEAD 中该文件的原始字节; 未跟踪返回 None。"""
    proc = subprocess.run(  # noqa: S607 — 本地 git 只读查询 (参数是仓内相对路径, 无外部输入)
        ["git", "show", f"HEAD:{rel_path}"],  # noqa: S603 — 同上: 固定 argv, 无 shell
        cwd=REPO, capture_output=True,                                               # 读 git 对象: cwd 必须是本仓, 否则会读父仓的陈旧 HEAD
    )
    return proc.stdout if proc.returncode == 0 else None  # 未跟踪/路径不存在时 git 报 128, 一律归 None


def _walk_py(root: str):
    """产出 (相对路径, 绝对路径或 None)。None 表示工作区中已不存在该文件。

    覆盖面 = **HEAD 里的 .py 全集**, 而不是工作区遍历 —— 这是 2026-10-06 修掉的
    fail-open: 原实现直接转手 :func:`scan_roots.iter_py_files` (文件系统遍历),
    于是**被删除的文件根本不会被产出**, ``removed`` 计数在结构上恒为 0, 那个
    ``if not os.path.exists(...)`` 分支只在"遍历后并发删除"时才可能命中, 对真正的
    删除是死代码。实测后果: 删掉 4 个受跟踪 .py 时门禁照样报 ``removed=0``,
    只把 compared 悄悄减 4, 退出码仍只看 changed/removed/broken → **删文件不红**,
    正是铁律 5 禁的那一类。

    改从 HEAD 取清单后: 磁盘上还在的照常比对, 不在的计入 removed 并参与退出码,
    删文件必然响。排除口径仍只用 :func:`scan_roots.is_excluded_dir` 这一份真源。
    """
    for rel in _head_py_files(root):
        yield rel, (str(Path(root) / rel) if os.path.exists(str(Path(root) / rel)) else None)


def _head_py_files(root: str) -> list[str]:
    """HEAD 里受跟踪的 .py 相对路径全集 (已按共享黑名单过滤), 排序稳定。

    Args:
        root: 仓根 (``git`` 命令的 cwd)。

    Returns:
        正斜杠相对路径的排序列表; git 不可用时回退为工作区遍历 (退化但不为空,
        与旧行为同构 —— 只是失去"发现删除"的能力, 不会反过来制造假红)。
    """
    proc = subprocess.run(  # noqa: S607 — 本地 git 只读查询 (固定 argv, 无外部输入)
        ["git", "ls-tree", "-r", "HEAD", "--name-only"],  # 递归列 HEAD 的文件名
        cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if proc.returncode != 0:  # 非 git 目录 / 无 HEAD: 退化到工作区遍历
        return [rel for rel, _full in iter_py_files(root)]
    out: list[str] = []
    for line in proc.stdout.splitlines():  # 逐行判定: 后缀 + 逐级目录排除
        rel = line.strip()
        if not rel.endswith(".py"):
            continue
        parts = rel.split("/")
        if any(is_excluded_dir(seg) for seg in parts[:-1]):
            continue  # 与 iter_py_files 同口径: 被排除目录里的 .py 不是本仓资产
        out.append(rel)
    return sorted(out)


def strip_docstrings(tree: ast.AST) -> ast.AST:
    """整条删除模块/类/函数体的首个 docstring 语句 (见模块 docstring 的关键细节)。"""
    targets = [                                                                                     # 收集可挂 docstring 的节点
        n for n in ast.walk(tree)                                                                   # 全树取
        if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))         # 四类节点
    ]
    for node in targets:                                # 四类定义节点各剥各的首条语句, 互不干扰
        body = node.body                                                                            # 取 body
        if body and isinstance(body[0], ast.Expr) and isinstance(                       # 首条是 Expr 包 Constant 才是 docstring
            body[0].value, ast.Constant                                                            # 拆行写: 这个 isinstance 太长
        ) and isinstance(body[0].value.value, str):
            node.body = body[1:]                        # 整条删除而非换成 Pass: 多出的 Pass 节点会改 AST
        # 空体归一化: "只有 docstring" 与 "只有 pass/..." 剥离后必须同形,
        # 否则补 docstring 会被误判为代码变更。
        if not node.body:                                                                           # 没有 body 的节点跳过
            node.body = [ast.Pass()]                   # 补 Pass 只为让"空体"有唯一形态
    return tree


def fingerprint_bytes(raw: bytes) -> str | None:
    """字节内容 -> 代码指纹; 语法错误返回 None (调用方按失败处理)。"""
    try:
        tree = ast.parse(raw)                                                               # 解析一次即可: 指纹只需要 docstring 的行集合
    except SyntaxError:
        return None                                     # 解析不了不等于"没变化", 上层要计入 unparseable
    tree = strip_docstrings(tree)                       # 先剥 docstring 再 dump: 顺序反了会把补 docstring 判成改动
    dumped = ast.dump(tree, annotate_fields=True, include_attributes=False)  # 不带属性: 行号缩进不该改指纹
    return hashlib.sha256(dumped.encode("utf-8")).hexdigest()


def main() -> int:
    """入口: 对比 git HEAD 与工作区的结构指纹 (清单外文件 = 未登记结构变更)。"""
    root = REPO                                                                            # 从仓根开始 (本仓是独立 git root, 不是父目录)
    changed: list[str] = []                             # 指纹与 HEAD 不符: 真代码改动
    removed: list[str] = []                             # HEAD 里有、工作区已不存在 (清单来自 git ls-tree, 不是遍历撞见)
    broken: list[str] = []                              # 文件在却解析不了
    added: list[str] = []                               # HEAD 里没有的新文件: 只报, 不判失败
    compared = 0                                        # 两侧都解析成功才算"比对过" (自覆盖测试盯它 > 0)

    head_set = set(_head_py_files(root))                                                                 # HEAD 侧全集: 删除判定与"新增"的反向依据都靠它
    for rel, full in _walk_py(root):                                                                # 逐个受跟踪文件 (清单来自 HEAD)
        if full is None:                                                                          # 磁盘上不存在 = 已被删除 (不再靠遍历撞见)
            removed.append(rel)                         # 删除是**基线侧**的事实, 枚举 HEAD 时就已确定, 不必等遍历碰巧遇到
            continue
        with io.open(full, "rb") as fh:                 # 读原始字节: ast.parse 要看得到编码声明
            current_raw = fh.read()                                                                 # 读工作区当前字节
        current = fingerprint_bytes(current_raw)                                                    # 算当前指纹
        if current is None:                                                                         # 算不出指纹即坏文件
            broken.append(rel)                                                             # 记入坏文件清单 (fail-closed: 不能静默跳过)
            continue
        head_raw = _git_show(rel)                       # 基线取 HEAD 原文: 取工作区快照等于自己印证自己
        if head_raw is None:                                                                        # HEAD 版本取不到即新增文件
            added.append(rel)          # 未跟踪的新文件 (结构变更, 另行报批)
            continue
        head = fingerprint_bytes(head_raw)                                                          # 算 HEAD 侧指纹
        if head is None:                                                                            # 算不出即坏文件
            continue                   # 基线本身就不可解析, 无可比性
        compared += 1                                                                               # 计入已比对
        if head != current:                                                                         # 指纹不同 = 代码真变了
            changed.append(rel)                         # 只改注释或 docstring 走不到这一行

    # 新增面单独扫工作区: 上一段遍历的是 HEAD 清单, 工作区多出来的文件走不到那里,
    # 若不补这一扫, "新写了 .py 但还没提交" 就彻底看不见 (new-untracked 恒 0)。
    work_files = iter_py_files(root)  # 工作区全集 (黑名单口径与 HEAD 侧同源)
    # 负对照 (2026-10-07): 零输入时本门禁实测打印 compared=0 且 exit 0 —— "代码零改动"
    # 在一个根本没扫到文件的仓上成立。闸在两侧清单都拿到之后, 比较之前。
    if not require_nonempty_scan("code_fingerprint", [rel for rel, _full in work_files]):
        return 1
    for rel, _full in work_files:
        if rel not in head_set and rel not in added:                                                # HEAD 没有且本轮未记过 = 新增
            added.append(rel)                                                                       # 只报不判失败: "还没提交" 不等于 "代码被改了"
    added.sort()                                                                                    # 排序: 报告顺序稳定可比对

    print(f"compared={compared} code-changed={len(changed)} "
          f"new-untracked={len(added)} removed={len(removed)} unparseable={len(broken)}")
    for label, items in (                                                                           # 分类打印
        ("!! 代码被改动", changed),
        ("-- 被跟踪文件被删除", removed),
        ("?? 语法错误", broken),
        ("++ 新增未跟踪文件 (结构变更需批准)", added),
    ):
        for item in items:                              # 分类打印: 一眼看出是改动还是登记问题
            print(f"  {label}: {item}")
    return 1 if (changed or removed or broken) else 0   # added 不计入: "还没提交" 不等于 "代码被改了"


if __name__ == "__main__":
    raise SystemExit(main())                            # 退出码直接透传给 make audit
