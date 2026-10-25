"""src.tap — 基于已验证 BEST 两阶段协议的 IVOA TAP 1.1 网关。

能力边界: 本包是 BEST 的 VO 标准适配面 (ISSUE-LIST 第 4 步「VO 适配器」):
adql (有界 ADQL 子集解析) → executor (翻译为两阶段表单协议) → formats
(VOTable/CSV/FITS 序列化) → jobs (UWS 异步作业) → service (stdlib http.server
TAP 路由) → client (pyvo 消费端, 可选依赖)。让 pyvo / astroquery / TOPCAT 可
直连 BEST, 而不改上游站点一行代码。
边界: BEST 上游不执行 SQL — 任何查询都先解析为白名单计划再翻译为表单;
JOIN/GROUP/子查询/聚合一律拒绝; 不引 FastAPI/starlette/pyvo 硬依赖。
白盒锚点: references/ALGORITHM-SPEC.md §6 (TAP 适配层锚点)。

历史来源: pybest 打包产物 (git 6f00efeb^〔本仓历史已无此对象〕〔本仓历史已无此对象〕) 的 pybest/tap/ 与
pybest/oauth.py; TAP+OAuth 实现已按本 skill 能力边界落在 src/tap/。
IVOA TAP 1.1: ivo://ivoa.net/std/TAP (规范引用, 无 DOI)。
"""
from __future__ import annotations

# 本地导入: ADQL 子集解析层 — 查询计划/约束/排序项类型与 parse_adql 入口 (跨解析能力边界)
from src.tap.adql import (
    ADQLError,  # 解析失败异常: 语法层错误统一由它报
    ConeConstraint,  # 锥搜约束节点: 白名单计划里唯一允许的位置条件
    OrderTerm,  # 排序项: 只允许白名单列名, 不透传任意表达式
    QueryBranch,  # 布尔分支: 可组合的只有与, 其余一律拒绝
    TapConstraint,  # 列约束节点: 算子与取值都在白名单内
    TapQueryPlan,  # 解析产物: 执行器只认这个结构, 不碰原始查询串
    parse_adql,  # 解析入口: 有界子集, 越界即抛错不降级
)

# 本地导入: 消费端客户端 — pyvo 为可选依赖且惰性导入 (跨客户端接入边界)
from src.tap.client import BestTapClient  # 导入本包不触发 pyvo: 惰性导入在 client 构造期

# 本地导入: 执行层 — 把查询计划翻译为 BEST 两阶段表单调用 (跨执行能力边界)
from src.tap.executor import TapExecutionError, TapExecutor  # 错误类型与执行器同源, 不另设异常层

# 本地导入: 序列化层 — VOTable/CSV/FITS 输出、哨兵转换与错误文档 (跨序列化能力边界)
from src.tap.formats import (
    SerializedResult,  # 序列化产物: 载荷与 MIME 成对, 不让二者脱钩
    convert_table_rows,  # 行结构转换: 哨兵值在序列化之前归一
    normalize_format,  # 格式名归一: 大小写与别名在此收口
    serialize_result,  # 序列化单点: 三种输出格式共用这一份实现
    votable_error,  # 错误文档: TAP 规范要求用 VOTable 形状回错
)

# 本地导入: UWS 异步作业存储与有界并发执行 (跨作业能力边界)
from src.tap.jobs import TapJobError, TapJobStore, TapQuotaError  # 配额异常独立成类, 便于调用方单独捕获

# 本地导入: HTTP 网关面 — 路由/handler/server 与工厂函数 (跨 HTTP 路由能力边界)
from src.tap.service import (
    TapGateway,  # 路由层: 把请求路径映射到六种标准动作
    TapHTTPServer,  # 服务器实例: 持有网关与处理器工厂
    TapRequestHandler,  # 请求处理器: 只做协议解析与写回, 不含业务逻辑
    TapResponse,  # 响应对象: 状态码与正文分离, 便于测试断言
    build_gateway,  # 组装入口: 调用方不必自己逐层拼装
    serve,  # 启动入口: 阻塞式服务, 供脚本层直接调用
)

__all__ = [  # 公开面白名单: 删改任一项即外部契约变更
    # ADQL 子集解析
    "ADQLError", "parse_adql", "TapQueryPlan", "TapConstraint", "ConeConstraint",
    "QueryBranch", "OrderTerm",
    # 执行
    "TapExecutor", "TapExecutionError",
    # 序列化
    "serialize_result", "normalize_format", "convert_table_rows", "votable_error",
    "SerializedResult",
    # UWS 异步作业
    "TapJobStore", "TapJobError", "TapQuotaError",
    # HTTP 面
    "TapGateway", "TapResponse", "TapRequestHandler", "TapHTTPServer",
    "build_gateway", "serve",
    # 消费端客户端
    "BestTapClient",
]
