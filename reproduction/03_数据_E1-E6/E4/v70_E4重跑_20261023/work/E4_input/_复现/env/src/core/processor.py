"""src.core.processor — [deprecated shim] 已迁移到 src.core.source_postprocess (P0 命名整改)。

能力边界: 本文件只做兼容转发, 不含任何实现, 登记二期删除。更名原因:
"processor" 空泛 — 实际职责是源记录的领域级后处理 (球面去重/亮度筛选/
波段统计); 权威实现: src.core.source_postprocess.BestProcessor。
"""
# 本地: 领域级后处理 (球面去重/亮度筛选/波段统计) —— 原写「数据模型与协议层」, 但数据模型在 src/models/, 与本行 import 无关
from src.core.source_postprocess import BestProcessor  # noqa: F401

__all__ = ["BestProcessor"]                                                                         # 公开面只此一个符号: 内部类不进契约
