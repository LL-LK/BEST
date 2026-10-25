#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ops/verify_tree_integrity.py — 文件树完整性硬门禁 (README 树清单 = canonical SSOT)。

能力边界: 扫描实际文件树, 与 README.md 内嵌的树清单块 (TREE:START/END 标记) 比对。
任何未授权的结构变更 (被跟踪文件/目录的新增、删除、移动、重命名) 都会导致非零退出。
树清单的更新必须显式征求用户同意后, 以 --write 重新生成 (治理规则: 结构变更需批准)。

设计:
  - 排除机器缓存 (__pycache__/.pytest_cache/.ruff_cache/.mypy_cache/*.pyc) 与 .git;
  - local-only / gitignored 运行时目录 (docs/ temp/ best_data/ .checkpoints/) 只登记
    存在性 (单行标注), 不展开内容——其内容为本地/临时产物, 不属架构 SSOT;
  - .env 等凭据文件永不进树清单。

用法:
    python ops/verify_tree_integrity.py            # 校验模式 (make verify / CI)
    python ops/verify_tree_integrity.py --write    # 重新生成 README 树清单 (需用户批准)
    python ops/verify_tree_integrity.py --diff     # 校验并打印差异明细
"""
from __future__ import annotations

# 标准库组:
#   argparse —— --write / --diff 两个开关 (结构变更必须显式征求用户同意)
#   sys      —— 进程退出码 (校验模式用非零表达 FAIL)
#   pathlib  —— 全程路径操作 (目录遍历 + README 读写), 不用 os.path 字符串拼接
import argparse
import sys
from pathlib import Path

OPS_DIR = Path(__file__).resolve().parent  # ops/ 目录; 只用于上溯, 不做路径拼接入口
SKILL_ROOT = OPS_DIR.parent  # 上溯一层即 skill 根 = 独立 git root, 一切相对基准以此为准
README = SKILL_ROOT / "README.md"  # SSOT 载体: 实际树必须向它看齐, 而不是让清单迁就实际树

# 树清单块标记: 校验器只认这一对注释之间的内容, 块外改动不影响判定
START_MARK = "<!-- TREE:START"  # 块外改动不参与判定, 所以 README 其余部分可以随便改
END_MARK = "<!-- TREE:END -->"  # 必须与 START 成对; 缺一个就按块缺失判 FAIL

# 机器缓存与版本控制目录: 完全不进树清单
# (这些是本地构建产物, 列进去会让门禁每次跑都误报 FAIL)
# .workbuddy-ai/.workbuddy: 外部 agent 工具的工作区状态目录 (memory 等),
# 与 .gitignore 同口径排除 — 它在 skill 根被工具重建时不该让树门禁FAIL
EXCLUDE_DIRS = {                                                                     # 不入清单的目录: 版本库/缓存/构建产物与 local-only 目录
    ".git", "__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache",
    ".egg-info", "build", "dist", ".venv", "venv", "node_modules",
    ".workbuddy-ai", ".workbuddy",
    # 覆盖率报告目录 (2026-10-04 补齐 .gitignore「Testing & Coverage」一节的口径镜像):
    # `make test-cov` / coverage html 会在 skill 根生成它, 而 .gitignore 已明确忽略。
    # 本门禁不读 gitignore (见 OPAQUE_DIRS 里 statcatalog 的注), 两处必须成对维护 ——
    # 漏登记的表现是: 跑过一次覆盖统计后 make verify 恒 FAIL, 提示「疑似未授权新增」,
    # 而无论 --write 还是删文件都只是把症状按下去, 下次跑覆盖照样复发。
    "htmlcov",
}
# (.progress/.logs 由只读命令 (如 astro_best_cli log) 也会创建, 漏列即让硬门禁 FAIL)
OPAQUE_DIRS = {  # 单行标注不展开: 这些目录的内容不属架构 SSOT
    "docs": "[local-only]",
    "temp": "[local-only 临时区]",
    "best_data": "[gitignored 运行时数据]",
    # 外部星表素材区 (2026-10-03 经用户批准): 与 best_data/ 同款定位 —— 人工放入的
    # 第三方星表 (如 chenZTF_variables.csv, 123 MB)。素材不是架构, 逐个文件登记
    # 既无意义 (123 MB CSV) 也会让树清单随素材增减漂移; 其来源与指纹记在
    # docs/eval-E2-groundtruth.md §5.5。本目录亦在 .gitignore 里, 两处口径必须一致:
    # 只改 .gitignore 不改这里, 硬门禁照样 FAIL (树门禁不读 gitignore, 只认本表)。
    "statcatalog": "[gitignored 外部星表素材]",
    ".checkpoints": "[gitignored 运行时状态]",
    ".progress": "[gitignored 运行时进度]",
    ".logs": "[gitignored 运行时日量]",
}
EXCLUDE_FILES = {".env", ".DS_Store", "Thumbs.db", ".coverage"}  # 凭据永不入清单, .env 进了公开文档就是泄露; .coverage 同上 (覆盖度二进制产物, 随跑随变)


def _is_excluded_file(name: str) -> bool:
    """判断文件名是否应被排除 (凭据/系统文件 + 编译与备份产物)。

    Args:
        name: 裸文件名 (不含目录)。

    Returns:
        True 表示该文件不进树清单。
    """
    if name in EXCLUDE_FILES:  # 名单优先于后缀判断, 凭据文件必须无条件排掉
        return True
    return name.endswith((".pyc", ".pyo", ".bak"))  # 后缀类产物: 不排除就会在清单里逐版本漂移


def generate_tree() -> list[str]:
    """生成确定性树清单 (排序稳定, 目录条目以 / 结尾, opaque 目录带标注)。

    排序键 `(not p.is_dir(), p.name.lower())` 保证目录在前、大小写不敏感稳定,
    这样同一份树在不同文件系统上生成结果一致 (determinism 治理面要求)。

    Returns:
        相对 skill 根的条目行列表 (目录行带 `/` 后缀)。
    """
    lines: list[str] = []  # 累加器: 闭包 walk 往里追加, 追加顺序即输出顺序

    def walk(directory: Path, prefix: str) -> None:
        """递归把目录树渲染成 README 树清单的文本行 (闭包写入 ``lines``)。

        Args:
            directory: 当前遍历目录。
            prefix: 已累积的前缀文本 (树形缩进 + 上级路径)。

        Note:
            目录排在文件之前、同名忽略大小写 — 这个顺序就是 README 清单的
            canonical 顺序, 改了会让 SSOT 校验误报差异。
        """
        entries = sorted(  # 排序键见下一行: 目录在前且跨文件系统稳定, 这是 deterministic 的全部依据
            (p for p in directory.iterdir() if p.name not in EXCLUDE_DIRS),                         # 先剔除排除目录再排序
            key=lambda p: (not p.is_dir(), p.name.lower()),                               # 目录在前文件在后, 同类按名排序 —— 让清单顺序稳定可比对
        )
        for path in entries:                                                                        # 逐项处理
            rel = f"{prefix}{path.name}"  # 树形缩进 + 本级名; 递归时由 walk 传入更深的 prefix
            if path.is_dir():                                                                       # 目录才递归
                if path.name in OPAQUE_DIRS:                                          # 不透明目录只登记自身, 不下钻 (local-only 的大产物树)
                    lines.append(f"{rel}/  {OPAQUE_DIRS[path.name]}")  # 只登记存在性, 不递归进去
                else:
                    lines.append(f"{rel}/")  # 普通目录记一条再递归, 追加顺序即 canonical 顺序
                    walk(path, f"{rel}/")
            elif not _is_excluded_file(path.name):  # 文件也走排除名单, 否则 .pyc/.bak 会让清单反复漂移
                lines.append(rel)                                                                   # 登记一条相对路径

    walk(SKILL_ROOT, "")  # 起点用空 prefix: 树根就是 skill 根
    return lines


def read_readme_block() -> tuple[list[str], int, int] | None:
    """读取 README 中的树清单块; 返回 (行列表, 起始行号, 结束行号) 或 None。

    行列表已剥离 ``` 代码栅栏 (写回时包裹, 读回时去除, 保证与 generate_tree() 同口径)。

    Returns:
        (content, start, end); README 不存在或找不到完整标记块时返回 None
        (缺失即 FAIL, 不 fail-open —— 否则树清单被悄悄删掉也查不出)。
    """
    if not README.is_file():  # 缺 README 与缺树块同判 FAIL, 两者都不是跳过校验
        return None
    # 读点: README.md 全文 (utf-8), 全文件唯一被读的文档
    text = README.read_text(encoding="utf-8")
    lines = text.splitlines()                                                                       # README 按行拆
    start = end = None  # 成对标记: 只找到一个等于块不存在
    for i, line in enumerate(lines):                                                                # 逐行找标记
        if line.strip().startswith(START_MARK) and start is None:                      # 只认第一处起始标记: README 里若还有同名代码块不能误当清单
            start = i                                                                               # 记起始下标
        elif line.strip().startswith(END_MARK) and start is not None:
            end = i                                                                                 # 未闭合则下标为 -1
            break
    if start is None or end is None:  # 不 fail-open: 树块被悄悄删掉也必须查出来
        return None
    content = [ln for ln in lines[start + 1 : end] if not ln.strip().startswith("```")]  # 剥掉栅栏, 与 generate_tree 同口径
    return content, start, end


def write_readme_block(tree_lines: list[str]) -> None:
    """将树清单写回 README (块不存在则追加到文件末尾)。

    Args:
        tree_lines: generate_tree() 的输出, 原样嵌入代码栅栏内。

    Note:
        写回时保留 header 注释行 (start+1 之前的部分不动), 只替换栅栏内的条目,
        这样 README 里人工写的说明文字不会被 --write 冲掉。
    """
    # 读点: 先读全文再整体替换, 避免部分写导致 README 半截损坏
    text = README.read_text(encoding="utf-8")
    header = "<!-- TREE:START (canonical snapshot; 由 ops/verify_tree_integrity.py --write 生成; 结构变更需用户批准) -->"
    block = "\n".join([header, "```", *tree_lines, "```", END_MARK])
    existing = read_readme_block()                                                                  # 读现有清单块
    if existing is None:                                                                            # 块不存在即无基线
        # 块整体缺失: 追加到文件尾 (先补齐换行, 防新旧内容粘行)
        if not text.endswith("\n"):
            text += "\n"
        text += f"\n{block}\n"
    else:
        _, start, end = existing                                                                    # 只取块位置, 内容另取
        lines = text.splitlines()                                                                 # 重新按行拆 (刚读过一遍, 行号以本次为准)
        new_lines = [*lines[: start + 1], "```", *tree_lines, "```", END_MARK, *lines[end + 1 :]]
        text = "\n".join(new_lines) + "\n"
    # 写点: 覆盖写 README.md (治理规则: 结构变更需用户批准后才允许 --write);
    # newline="\n" 显式锁定 LF —— 缺省时 Windows 上会把 \n 翻译成 \r\n, 让
    # 本应保护 LF 约定的门禁自己把 README 写成 CRLF (git 每次 touch 都告警)
    README.write_text(text, encoding="utf-8", newline="\n")  # 显式锁 LF: 缺省在 Windows 上会把换行翻成 CRLF, 门禁自己破自己的约定


def main() -> int:
    """门禁入口: 校验模式 (默认) / --write 重新生成 / --diff 打印差异明细。

    Returns:
        树与清单一致 (或 --write 成功) 返回 0; 不一致/缺块返回 1。
    """
    parser = argparse.ArgumentParser(description="文件树完整性硬门禁 (README 树清单 SSOT)")
    parser.add_argument("--write", action="store_true", help="重新生成 README 树清单 (需用户批准)")
    parser.add_argument("--diff", action="store_true", help="打印差异明细")
    args = parser.parse_args()                                                                      # 命令行参数

    # 以实际文件树为准生成快照, 再与 README 中的清单比对
    actual = generate_tree()  # 以实际树为准生成快照, 再拿它跟 README 清单逐行比

    if args.write:                                                                                  # --write 才重生成
        # 破坏性模式: 直接让 README 迁就实际树; 因此调用前必须已获用户批准
        write_readme_block(actual)                                                                  # 写回 README 清单块
        print(f"README tree snapshot regenerated: {len(actual)} entries -> {README}")
        return 0

    existing = read_readme_block()                                                                  # 非 write 模式: 读现有块做比对
    if existing is None:                                                                            # 块不存在即无法比对
        # 缺块 = SSOT 丢失, 这是 FAIL 而不是"跳过校验" (无 fail-open)
        print("FAIL: README.md 中找不到树清单块 (TREE:START/END 标记)")
        print("      修复: python ops/verify_tree_integrity.py --write (需用户批准)")
        return 1

    expected, _, _ = existing                                                                       # 期望清单
    if actual == expected:  # 严格逐行相等: 顺序漂移也算 FAIL, 否则清单会慢慢失序
        print(f"OK: 文件树与 README 清单一致 ({len(actual)} entries)")
        return 0

    # 顺序无关的集合差: 把"被删/被移"与"未授权新增"分开报告, 便于人工定位
    actual_set, expected_set = set(actual), set(expected)  # 集合差把被删/被移与未授权新增分成两类报, 便于人工定位
    missing = sorted(expected_set - actual_set)  # 清单有, 实际无 (被删/被移)
    extra = sorted(actual_set - expected_set)    # 实际有, 清单无 (新增/未登记)
    print(f"FAIL: 文件树与 README 清单不一致 (实际 {len(actual)} / 清单 {len(expected)})")
    if extra:                                                                                       # 清单里有、磁盘上没有
        print("  [+] 实际存在但清单未登记 (疑似未授权新增):")
        for line in extra:                                                                          # 逐条打印
            print(f"      {line}")
    if missing:                                                                                     # 磁盘上有、清单里没有
        print("  [-] 清单登记但实际不存在 (疑似被删/被移):")
        for line in missing:                                                                        # 逐条打印
            print(f"      {line}")
    if args.diff and not extra and not missing:                                         # 无差异且要 diff 时才输出 (默认静默, 免得每次跑都刷屏)
        # 集合相等但序列不等: 只是排序/标注漂移, 仍需 --write 归一
        print("  [~] 仅顺序/标注差异")
    print("  若为已批准的结构变更: python ops/verify_tree_integrity.py --write")
    return 1


if __name__ == "__main__":
    sys.exit(main())                                                                                # 退出码直接用 main 的返回
