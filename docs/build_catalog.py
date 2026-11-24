"""从 Git 索引生成仓库文档目录。"""

import argparse
from collections import defaultdict
from pathlib import Path, PurePosixPath
import posixpath
import subprocess
from urllib.parse import quote


ROOT = Path(__file__).resolve().parents[1]
CATALOG = "docs/catalog"
EXPERIMENTS = "reproduction/03_数据_E1-E6"
DOCUMENT_EXTENSIONS = {
    ".adoc", ".docx", ".htm", ".html", ".markdown", ".md", ".mdx",
    ".pdf", ".rst", ".tex",
}
DOCUMENT_NAMES = {
    "CITATION.cff", "LICENSE", "README", "README.txt",
    "llms.txt", "requirements.txt",
}
SECTIONS = {
    "repository": ("仓库入口与导航", "../README.md"),
    "skill": ("查询实现与开发材料", "../development.md"),
    "publication": ("实验图表与复现配套材料", "../paper.md"),
    "e1": ("E1", "../experiments.md"),
    "e2": ("E2", "../experiments.md"),
    "e3": ("E3", "../experiments.md"),
    "e4": ("E4", "../experiments.md"),
    "e5": ("E5", "../experiments.md"),
    "e6": ("E6", "../experiments.md"),
}


def tracked_documents():
    """列出 Git 已跟踪的文档及指定的说明和许可文件。"""
    output = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT)
    for path in sorted(set(output.decode("utf-8").split("\0"))):
        if not path or path.startswith(f"{CATALOG}/"):
            continue
        document = PurePosixPath(path)
        if document.suffix.lower() in DOCUMENT_EXTENSIONS or document.name in DOCUMENT_NAMES:
            yield document


def section_for(document):
    """按仓库中的位置归入相应主题。"""
    parts = document.parts
    if document.is_relative_to(EXPERIMENTS):
        experiment = parts[2].lower()
        if experiment in SECTIONS:
            return experiment
    if parts[0] == "skill":
        return "skill"
    if parts[0] == "reproduction":
        return "publication"
    return "repository"


def build_pages():
    """将文档按主题和父目录列入可浏览的 Markdown 页面。"""
    directories = {section: defaultdict(list) for section in SECTIONS}
    for document in tracked_documents():
        directories[section_for(document)][document.parent].append(document)

    index = [
        "# 仓库文档目录",
        "",
        "[文档导航](../README.md)",
        "",
        "本目录根据 Git 索引生成，收录 Markdown、HTML、PDF、Word 等文档，"
        "以及指定的说明和许可文件。每条链接指向文件原路径。",
        "实验评分表、配置、执行记录和压缩包等配套材料见 [实验资料](../experiments.md)"
        " 和 [实验图表与复现包](../paper.md)。",
        "",
        "| 分类 | 文件数 |",
        "| --- | ---: |",
    ]
    pages = {}
    total_count = 0
    for section, (title, entry) in SECTIONS.items():
        groups = directories[section]
        count = sum(len(documents) for documents in groups.values())
        index.append(f"| [{title}]({section}.md) | {count} |")
        total_count += count
        lines = [
            f"# {title}", "",
            f"[仓库文档目录](README.md) · [阅读入口]({entry})",
        ]
        for directory, documents in sorted(groups.items()):
            label = "仓库根目录" if directory == PurePosixPath(".") else directory.as_posix()
            lines.extend(["", f"## {label}", ""])
            for document in documents:
                label = document.name.replace("[", r"\[").replace("]", r"\]")
                target = quote(posixpath.relpath(document.as_posix(), CATALOG))
                lines.append(f"- [{label}]({target})")
        pages[f"{section}.md"] = "\n".join(lines) + "\n"
    index.append(f"| 合计 | {total_count} |")
    pages["README.md"] = "\n".join(index) + "\n"
    return pages


def main():
    """无参数时重建目录，--check 检测已登记的分类页是否需要更新。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="只检查生成页是否最新")
    options = parser.parse_args()
    output = ROOT / CATALOG
    pages = build_pages()

    if options.check:
        for name, content in pages.items():
            path = output / name
            if not path.is_file() or path.read_text(encoding="utf-8") != content:
                parser.exit(1, f"{CATALOG}/{name} is out of date. Run python docs/build_catalog.py.\n")
        return

    output.mkdir(parents=True, exist_ok=True)
    for name, content in pages.items():
        (output / name).write_text(content, encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
