"""src.query — [deprecated shim] 已迁移到 src.query_builder (P0 命名整改)。

能力边界: 本文件只做兼容转发, 不含任何实现, 登记二期删除。更名原因:
旧名 "query" 与真正发请求的 src.client 混淆 — 本模块只是列约束**构造器**
(不发请求); 权威实现: src.query_builder.BestQuery (类名是契约层 input
schema 身份, 保持不变)。
"""
# 本地: query_builder 新模块再导出 (P0 兼容 Shim; 新代码直接用 src.query_builder)
from src.query_builder import BestQuery  # noqa: F401 -- 只保旧路径, 新代码请直接 import query_builder

__all__ = ["BestQuery"]  # 白名单单一: 名字与上面那条 import 严格一一对应
