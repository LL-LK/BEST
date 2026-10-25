"""src — BEST 数据库 Python 查询与下载工具。

能力边界: 包门面: 仅再导出 13 项公开 API (__all__); 不含业务逻辑。边界: 不实例化客户端, 不发请求; 禁止在此加版本号 (全仓禁版本号铁律)。
白盒锚点: references/ALGORITHM-SPEC.md §1/§2 (两阶段协议与真源码锚点表)。

通过 form-based REST API 连接 nadc.china-vo.org/data/best 的真实 BEST 数据库,
提供 Standard Stars、Pan-STARRS All-Sky、Well-Calibrated 三大类可查询星表的
检索与坐标上传交叉匹配能力, 避免下载全量 20 亿行星表。

公开面共 13 个符号 (见 ``__all__``): 6 个核心类
(BestClient/BestAuth/BestQuery/BestMultiBandPhotometry/BestCrossMatch/BestDownloader)
+ 5 个领域模型 (CatalogType/ColumnConstraint/BestSource/BestQueryResult/
ResolvedName) + 2 个 scripts 命名空间的脚本级入口 (cone_search/crossmatch_coords)。
所有业务逻辑均在权威子模块内, 本文件只做再导出, 不实例化客户端、不发请求。
(P1: pybest 单类 Best 双副本已合并删除 — 唯一生产客户端是 BestClient。)
"""
from __future__ import annotations

# 模块级作者署名 (元信息, 非能力面; 不进入 __all__)
__author__ = "StarWhisper Team / FAST-BEST Collaboration"  # 元信息, 不进入 __all__

# ---------------------------------------------------------------------------
# __all__ — 包公开 API 白名单: 只有列在此处的符号才是稳定契约,
# `from src import *` 与外部复核者都以此为准; 删改任何一项即公开面变更。
# ---------------------------------------------------------------------------
__all__ = [  # 公开面 SSOT: 只有列在此处的 13 个符号是对外稳定契约
    # 核心类: 认证/客户端/查询构造/多波段测光/交叉匹配/下载 (权威实现在各子模块)
    "BestClient", "BestAuth", "BestQuery", "BestMultiBandPhotometry",
    "BestCrossMatch", "BestDownloader",
    # 领域模型: 星表枚举/约束编码/单源/结果信封/名称解析结果
    "CatalogType", "ColumnConstraint", "BestSource", "BestQueryResult",
    "ResolvedName",
    # scripts 命名空间脚本级入口: 带入口校验/共享 client 的便捷函数
    "cone_search", "crossmatch_coords",
]

# 本地: 认证与 REST 客户端 — BestAuth 管 Django session+CSRF 登录,
# BestClient 是两阶段查询 (POST 取 sqlid → GET 分页取数) 的权威实现,
# crossmatch/downloader/CLI 均消费它, 不自建会话。
from src.client import BestAuth, BestClient  # 再导出而非包装: 外部拿到的就是权威类本身

# 本地: 交叉匹配 — 权威实现在 src.crossmatch; 跨模块边界: 消费 BestClient
# 的锥检索能力, 对上层 (scripts/CLI) 屏蔽逐点 HTTP 细节。
from src.crossmatch import BestCrossMatch

# 本地: 下载器 — 区域下载 (两阶段协议落地) + 四种格式落盘 (csv/txt/json/votable)
# 的权威实现; download_manager 的后台任务最终也调用它。
from src.downloader import BestDownloader

# 本地: 领域模型 — BestQueryResult (成功/总数/截断/错误信封),
# BestSource (单源: 坐标+星等+raw_data), CatalogType (12 个可查询星表 +
# 导航组枚举), ColumnConstraint (协议约束编码), ResolvedName (名称解析
# 结果 + remark_external 外部内容标记)。
from src.models import (
    BestQueryResult,
    BestSource,
    CatalogType,
    ColumnConstraint,
    ResolvedName,
)

# 本地: 多波段静态测光容器 — 单源多波段定标测光的承载与 CSV/JSON 导出;
# 不发起网络请求, 数据由调用方 (查询结果) 灌入。BEST 无时序 (非光变曲线)。
from src.multiband_photometry import BestMultiBandPhotometry

# 本地: 流畅查询构造器 — build() 产参数字典, to_form() 委托 protocol 层
# 生成 pos.* 表单键集; 与 BestClient._build_form 同一权威表单层。
from src.query_builder import BestQuery

# 本地: scripts 命名空间公开锥检索入口 — 比裸调 BestClient 多入口坐标/
# 半径校验 (validate_coordinate/validate_search_radius) 与模块级共享
# client (防 session 泄漏)。
from src.scripts.best_cone_search import cone_search  # 函数级入口: 自带坐标/半径校验, 非裸调客户端
from src.scripts.best_crossmatch_pipeline import crossmatch_coords  # 逐点异常隔离 (Q-17), 单点失败不中断整批
