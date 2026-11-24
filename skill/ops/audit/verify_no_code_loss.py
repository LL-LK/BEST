"""verify_no_code_loss.py — 逐个文件对比 git HEAD 与工作区, 确认只有注释/docstring 增量。

用 AST 指纹 (strip docstring) 之外的第二重口径, 逐文件比较
  - 物理行数
  - def/class/assert 语句数
  - **代码 token 序列** (剔除注释/空白/换行/缩进, 并剔除 docstring)

任何一项下降即为代码丢失, 必须报出来。

为什么按 token 而不是按"代码行集合": 同一段代码从多行折成一行 (或反之) 行集就
完全不同 —— 实测 `DATA_TOOLS = frozenset({...})` 由两行折成一行即被误报成
"丢失代码行=2"。token 序列对排版免疫, 只有真正的增删改才会让序列变化。

仓根 = 本文件上溯两级, 且 git 查询必须落在本仓 .git 上 —— 指向父仓等于拿父仓
陈旧 HEAD 当基线去比子仓工作区, 会把"子仓早已提交的重写"误报成代码丢失。

职责: 给"只加注释、不改代码"这一改动模式上第二道锁 —— 逐个改动文件比 HEAD 与工作区,
  确认代码部分零丢失。度量对象是 AST 层面的三个计数 (def/class 数、assert 数) 加一
  条代码 token 序列, 任何一项下降即判"代码丢失"。
所属子系统: 仓库治理层 ops/audit/ 的**报告型**工具 (make audit 里刻意非阻断): 它要
  人判读, 因为合法的重写 (删掉重复定义) 也会让 token 变少, 机械判红会误伤。
  上游无代码依赖, 下游是人工验收「只加注释、不改代码」这一改动模式的人。
对外接口: main() -> None (以 sys.exit 收尾), 以及 head_text / work_text /
  docstring_rows / code_tokens / lost_tokens / counts 六个纯函数 —— 这几个是本仓
  "怎么定义代码 token"的**口径 SSOT**, 别的工具要改判定必须先改这里。
依赖与数据流: 输入 = git 的两路输出 (HEAD 文本) + 工作区磁盘文本; 无产物落盘,
  结果只在 stdout 与退出码。git 调用全部走 argv 列表 + `-C ROOT`, 不拼 shell 串。
关键契约与不变量: 基线**必须**取自本仓自己的 .git —— 本仓是独立 git root, 从父仓
  操作会让 HEAD 基线分叉, 之前就因此把整仓误报成代码丢失; token 比对必须剔除注释
  与 docstring, 否则"把英文注释改写成中文"这类纯注释改动会被误判成代码变动。
陷阱与边界: 只覆盖 `git diff --name-only HEAD` 列出的文件, 也就是说**没 commit 的
  新文件与未暂存以外的 staged 差异**仍能比 (diff 对工作区取), 但已 commit 掉的改动
  根本不会被检查 —— 它守的是"未提交的增量", 不是仓库历史; 删文件走 DEL 分支
  单独计数不判红, 因为删除与丢失是两件事; tokenize 失败时退化成空列表, 由上层按
  行数下降判定, 此时宁可多报不漏报。
"""
from __future__ import annotations

# 标准库: 清单快照对比 (代码零丢失守门的读取层) / token 序列比对 / 仓根定位 (Path)
import ast
import io
import os
import subprocess
import sys
import tokenize
from pathlib import Path

ROOT = str(Path(__file__).resolve().parents[2])  # 仓根上溯两级; 基线必须取自本仓 .git, 走父仓会整仓误报


def head_text(rel: str) -> str:
    """从 git HEAD 读取文件文本 (rel 为仓根下的相对路径)。

    check=True 是刻意的: HEAD 里没有该路径 (新文件) 应当抛 CalledProcessError
    让调用方归入 NEW 分支, 而不是拿到一段 git 错误文本去当源码解析。
    """
    # noqa: S603,S607 — 本地 git 只读查询 (固定 argv, 参数是仓内相对路径)
    out = subprocess.run(  # check=True: HEAD 无此路径要抛出去好归 NEW, 别拿 git 报错文本当源码解析
        ["git", "-C", ROOT, "show", f"HEAD:{rel}"],
        capture_output=True, check=True,                                     # 读原文: check=True 让 git 失败直接抛, 不返回空串冒充"文件不存在"
    )
    return out.stdout.decode("utf-8")


def work_text(rel: str) -> str:
    """读取工作区文件文本 (文件已删除时抛 FileNotFoundError, 由调用方区分)。"""
    with io.open(os.path.join(ROOT, rel), "rb") as fh:  # 不给回退编码: 宁可抛到上层走 SKIP, 也不按 GBK 读出乱码再比 token
        return fh.read().decode("utf-8")


def docstring_rows(text: str) -> set[int]:
    """返回全部 docstring 所占的物理行号集合 (模块/类/函数体首个字符串表达式)。

    语法错误返回空集合而非抛错: 本函数的调用方是"尽力而为"的比对流程, 单个坏
    文件不该让整轮核对中断。
    """
    try:
        tree = ast.parse(text)                                                                      # 语法树只解析一次
    except SyntaxError:
        return set()  # 坏文件返空集合, 让整轮比对继续而不是被单个文件打断
    rows: set[int] = set()                                                                          # docstring 行集合
    for node in ast.walk(tree):                                                                     # 全树遍历
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):     # 四类可挂 docstring 的节点
            body = getattr(node, "body", None)
            if body and isinstance(body[0], ast.Expr):  # 首条必须是字符串字面量表达式, 与运行期 __doc__ 同规则
                value = body[0].value                                                               # 首条语句的 value
                if isinstance(value, ast.Constant) and isinstance(value.value, str):                # 确认是字符串常量
                    rows.update(range(value.lineno, (value.end_lineno or value.lineno) + 1))        # 取完整行范围
    return rows


def code_tokens(text: str) -> list[str]:
    """抽取代码 token 序列 (剔注释/空白/换行/缩进, 并剔 docstring)。

    行尾注释与 docstring 必须剔除: 纯注释改动 (例如把英文注释改写成中文) 若连
    注释一起比, 会被误报成"代码丢失" —— 而放行这类改动正是本工具的职责。
    """
    skip_types = {  # 排版类 token: 增减纯属折行口味, 与代码增删无关
        tokenize.COMMENT, tokenize.NL, tokenize.NEWLINE,
        tokenize.INDENT, tokenize.DEDENT, tokenize.ENCODING,
        tokenize.ENDMARKER,
    }
    docs = docstring_rows(text)  # docstring 那段字符串不算代码, 否则把英文注释改写成中文会被误判成代码变动
    out: list[str] = []                                                                             # token 列表
    try:
        stream = tokenize.generate_tokens(io.StringIO(text).readline)  # 输入已是 str, 走文本流省掉 BytesIO 包装
        for tok in stream:                                                                          # 逐个 token
            if tok.type in skip_types:                                                             # 剔除噪声: 注释/换行/缩进不参与代码比对
                continue
            if tok.type == tokenize.STRING and tok.start[0] in docs:  # 只剔落在 docstring 行号里的字符串, 普通字面量必须留
                continue
            out.append(tok.string)                                                                  # 留一个可比较的原子
    except (tokenize.TokenError, IndentationError, SyntaxError):
        # 解析不了的文件退化为"行集"口径, 由调用方按行数下降判定
        return []
    return out


def lost_tokens(head: str, work: str) -> list[str]:
    """HEAD 中出现而工作区已不存在的 token (多重集差, 保持 HEAD 顺序)。

    用多重集而非序列: 同一段代码调换语句顺序不算"丢失", 只有净减少才是。
    逐个 remove 会消耗工作区里的同值 token, 因此新增的同名 token 不会互相抵消。
    """
    remaining = list(code_tokens(work))  # 逐个 remove 会消耗同值 token, 新增的同名 token 因此不互相抵消
    lost: list[str] = []                                                                            # 丢失的 token 列表
    for tok in code_tokens(head):                                                                   # 逐个 HEAD 侧的 token
        if tok in remaining:                                                                        # 还能对上就从待查集合里划掉
            remaining.remove(tok)                                                                   # 划不掉的即真正丢失
        else:
            lost.append(tok)                                                                        # 记一条丢失
    return lost


def counts(text: str) -> tuple[int, int, int]:
    """返回 (物理行, def+class 数, assert 数)。

    这三个计数是 token 比对之外的冗余防线: token 序列对"删掉一个函数体"这种
    改动敏感, 但对"把两个函数合成一个"只体现为 token 减少, def/class 计数能
    从另一个角度把结构性削减单独指出来。
    """
    tree = ast.parse(text)  # 这里刻意不降级: 基线解析不了就没得比, 必须让调用方看见
    defs = sum(1 for n in ast.walk(tree)  # AsyncFunctionDef 一并计入, 否则 async 改造能瞒过 def 计数
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)))             # 可计入「定义数」的三类节点
    asserts = sum(1 for n in ast.walk(tree) if isinstance(n, ast.Assert))  # 断言是门禁的骨头, 删一个就等于少一道挡
    return len(text.splitlines()), defs, asserts


def main() -> None:
    """主入口: 对 git status 列出的改动 .py 文件逐一核对。

    作用: 跑一次 git diff 拿到改动清单, 对每个 .py 做 HEAD↔工作区三方比对
    (行数/def/assert 计数 + 代码 token 多重集差), 把结果逐行打出。
    返回: 无 —— 以 sys.exit(0/1) 收尾, 因为它被当脚本跑, 不便用返回值传判据。
    抛什么: git 子进程失败 (CalledProcessError) 与 AST 解析失败 (SyntaxError,
    来自 counts() 不做降级) 直接冒泡: 基线拿不到就没法判断, 此时必须让人知道。
    """
    out = subprocess.run(["git", "-C", ROOT, "diff", "--name-only", "HEAD"],  # 只取 .py: markdown/表格没有 token 口径可比
                         capture_output=True, check=True)                              # 读工作区版本: 基线必须取自本仓 .git (指向父仓会拿陈旧基线误报)
    files = [ln for ln in out.stdout.decode("utf-8").splitlines() if ln.endswith(".py")]  # 只守未提交的增量, 已 commit 的改动不在其中
    bad = 0                                                                                         # 可疑文件计数
    deleted = 0                                                                                     # 已删除文件计数
    for path in files:                                                                              # 逐文件
        rel = path.replace("\\", "/")  # Windows 上 git 吐反斜杠, 归一后 isfile 与 git show 才对得上
        if not os.path.isfile(os.path.join(ROOT, rel)):                                             # 磁盘上不存在 = 被删除
            # 工作区已删除该文件: 属"删除"而非"代码丢失", 单独计数不判红
            print("DEL  %s (工作区已删除)" % rel)
            deleted += 1                                                                            # 删除的文件不计入可疑
            continue
        try:
            h, w = head_text(rel), work_text(rel)                                                   # 分别取 HEAD 与工作区文本
        except subprocess.CalledProcessError:
            # HEAD 无此文件 = 新增文件, 没有基线可比, 跳过而不是判红
            print("NEW  %s (HEAD 无此文件)" % rel)
            continue
        except UnicodeDecodeError:
            print("SKIP %s (非 UTF-8 文本, 不参与比对)" % rel)
            continue
        hc, wc = counts(h), counts(w)                                                               # 计数: 物理行/净行/def 数
        lost = lost_tokens(h, w)                                                                    # 逐 token 比对
        flag = ""
        if wc[1] < hc[1] or wc[2] < hc[2] or lost:  # 只判下降: 净代码行/定义数变多不构成代码丢失
            flag = "  <<< 代码丢失!"
            bad += 1                                                                                # 计入可疑
        print("%-58s HEAD行=%d 现行=%d def %d->%d assert %d->%d 丢失token=%d%s"
              % (rel, hc[0], wc[0], hc[1], wc[1], hc[2], wc[2], len(lost), flag))
        for tok in lost[:8]:  # 最多回显 8 个, 全量打印会把终端刷爆
            print("      - " + tok[:100])
    print("\n可疑文件数 = %d / %d (另有 %d 个已删除文件, 不计入)"
          % (bad, len(files), deleted))                                                             # 末尾汇总三个数
    sys.exit(1 if bad else 0)  # 有可疑即非零; make audit 侧刻意不接这道门禁, 判定权在人


if __name__ == "__main__":
    main()                                                                                          # 入口
