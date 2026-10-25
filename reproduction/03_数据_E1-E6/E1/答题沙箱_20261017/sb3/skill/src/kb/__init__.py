"""src.kb — BEST 操作领域知识库的加载器。

能力边界: 程序化加载顶层 references/ 白盒文档 (内容层) 的唯一代码入口。
references/ = 文档内容, rag/knowledge/ = 结构化规则, src/kb/ = 加载代码 (三层分离)。
路径解析: 从本文件向上查找标志文件 (manifest.yaml) 定位 skill 根, 不写死层数 (Q-39)。
"""
from __future__ import annotations

# 标准库: pathlib 做跨平台路径拼装与存在性判定。
from pathlib import Path

# 标准库: 返回值允许"文档不存在" (None), 列表元素为文档 stem。
from typing import Any, Optional

# 本地: skill 根解析的唯一实现 (R4-03: 本处原有第二份副本已收敛, 兜底层数
# 与本件深度耦合, 副本分叉时静默解析到错根)。定位靠标志文件而非写死层数。
from src._paths import skill_root

# 模块级算一次: 两个消费点 (load_reference / list_references) 共用同一锚点,
# 不让每次调用各走一遍上溯, 更不让两处各算一遍而分叉。
SKILL_ROOT = skill_root(__file__)


def load_reference(name: str) -> Optional[str]:
    """按名字加载一篇参考文档 (references/ 下的 .md/.txt/.rst)。

    Args:
        name: 文档 stem (不含扩展名)。只允许文件名片段 — 含路径分隔符或
            ``..`` 段的输入会抛 ``ValueError`` (fail-closed)。

    Returns:
        文档全文 (UTF-8 解码); 三种扩展名都不存在时返回 ``None`` (调用方按
        "该文档未提供"处理, 不抛异常)。

    Raises:
        ValueError: ``name`` 含路径分隔符/``..`` 段, 或解析后越出
            ``references/`` 目录 — 加载器只读 references 下文档, 不做仓内
            任意文件读取器 (YZ-17: ``../../README`` 型输入曾实测读出仓根
            README 全文)。
    """
    # 入口形态闸: 分隔符与 ``..`` 段一律拒 — stem 语义不允许任何目录穿行
    if not name or Path(name).name != name or ".." in Path(name).parts:  # 分隔符/父目录段都到不了文件系统层
        raise ValueError(f"reference name must be a bare file stem (got {name!r})")
    ref_dir = SKILL_ROOT / "references"
    for ext in [".md", ".txt", ".rst"]:
        path = ref_dir / f"{name}{ext}"  # name 是 stem, 扩展名在此拼回
        # 文件系统探测 + 读取: 按扩展名优先级找第一个命中项并读全文。
        if path.exists():
            # 纵深第二道: 符号链接也可能越界, resolve 后复核归属 (与
            # knowledge_slots._safe_resolve 同一判据 — 只比字符串前缀会被
            # 兄弟目录骗过)
            resolved = path.resolve()  # symlink 落成真实绝对路径再判归属
            if not resolved.is_relative_to(ref_dir.resolve()):  # 越界即拒: references 外的文件不是参考文档
                raise ValueError(f"reference escapes references/ dir: {name!r}")
            return path.read_text(encoding="utf-8")  # 统一 UTF-8 解码, 不吃平台默认编码
    return None  # 三种扩展名都没有即视为"未提供", 不抛异常

def list_references() -> list[str]:
    """列出全部可用参考文档 (references/ 下的 stem 列表, 排序稳定)。

    Returns:
        文档 stem 的有序列表; references/ 目录不存在时返回 ``[]``。
    """
    ref_dir = SKILL_ROOT / "references"
    if not ref_dir.exists():                                                                      # 引用目录缺失即无白盒文档可读, 不静默返回空
        return []
    # 目录枚举: 只收白盒文档用的三种扩展名, 排序保证输出可复现。
    return sorted(
        p.stem for p in ref_dir.glob("*") if p.suffix in (".md", ".txt", ".rst")
    )
