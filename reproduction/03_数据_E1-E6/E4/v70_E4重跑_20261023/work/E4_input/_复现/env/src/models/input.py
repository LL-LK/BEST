"""src.models.input — BEST 查询的输入模型。

能力边界: 输入模型 (ConeSearchInput/DownloadInput/SourceQueryInput)。边界: 与 contracts/input.contract.yaml 逐字段对齐; 不被 from_yaml 之外的路径消费。
白盒锚点: contracts/input.contract.yaml; contracts/fields/sql|token.contract.yaml。
"""

from __future__ import annotations

# 标准库: 可选类型标注 (输入字段允许缺省, 由调用方或契约默认值补齐)。
from typing import Optional


class ConeSearchInput:
    """锥形检索的输入参数 (天球上一小片区域 + 记录数上限)。

    字段与 contracts/input.contract.yaml 的 cone search 段逐字段对齐;
    ``band`` 为 ``None`` 表示不按波段过滤 (全部波段一并返回)。
    """

    def __init__(
        self,  # 实例: 字段逐项落到属性上
        ra: float,  # 检索中心赤经(度): 与赤纬共同定位天区
        dec: float,  # 检索中心赤纬(度): 缺测坐标无法定位, 由调用方保证
        radius_arcsec: float = 60.0,  # 检索半径(角秒): 60 角秒覆盖典型单源邻域
        band: Optional[str] = None,  # 波段标签可空: 缺省表示全波段一并返回
        max_records: int = 1000,  # 返回行数上限: 超限即截断并如实标记
    ) -> None:
        """构造锥形检索输入 (字段语义见类 docstring 与逐属性行内注释)。"""
        # 检索中心 (度) 与半径 (角秒); 半径默认 60 角秒, 覆盖典型单源邻域查询。
        self.ra = ra  # 赤经落属性: 契约字段名与属性名一致, 便于逐字段对账
        self.dec = dec  # 赤纬落属性: 与赤经同属定位三元组
        self.radius_arcsec = radius_arcsec  # 半径落属性: 区域边界的唯一口径, 落盘不再二次裁剪
        # 波段过滤标签 (``None`` = 不过滤); 取值必须是 protocol.CATALOG_MAG_COLUMNS
        # 中该星表发布的波段, 否则 magnitude_column() 会 fail-closed。
        self.band = band  # None = 全波段一并返回; 非法标签由下游 fail-closed 拦下
        # 客户端侧返回行数上限: 超过即截断 (结果带 truncated=True, P0-2),
        # 防止一次拉回过大响应。
        self.max_records = max_records  # 只截返回行数, 不改写服务端报的真实总数


class SourceQueryInput:
    """按 source_id 或坐标查询单个源的输入参数。

    两种定位方式二选一: 直接给 ``source_id`` (服务端精确查找), 或给
    ``ra``/``dec`` + ``tolerance_arcsec`` (坐标邻域内找最近邻)。
    """

    def __init__(
        self,  # 实例: 两种定位方式共用一个输入对象
        source_id: Optional[str] = None,  # 源标识可空: 给了就走服务端精确定位
        ra: Optional[float] = None,  # 赤经可空: 走坐标邻域模式时才需要
        dec: Optional[float] = None,  # 赤纬可空: 与赤经同进同出
        tolerance_arcsec: float = 3.0,  # 匹配容差(角秒): 默认与交叉匹配半径一致
    ) -> None:
        """构造单源查询输入 (两种定位方式二选一, 见类 docstring)。"""
        # 服务端源 id; 给定时坐标参数被忽略。
        self.source_id = source_id  # 非空即走服务端精确定位, 不再落到坐标邻域分支
        # 坐标定位模式下的中心 (度); 与 source_id 一样允许为 None。
        self.ra = ra  # 赤经落属性: 与源标识二选一, 不做隐式互斥校验
        self.dec = dec  # 赤纬落属性: 同上
        # 坐标定位的匹配容差 (角秒); 默认 3 角秒, 与交叉匹配默认半径一致。
        self.tolerance_arcsec = tolerance_arcsec  # 超出容差即判无匹配, 不自动放宽半径


class DownloadInput:
    """批量下载的输入参数 (一次抓取一个天区并落盘)。

    ``resume`` 控制断点续传: 已存在的输出文件被跳过而不是重新下载。
    ``bands`` 默认只收各星表 ``CATALOG_MAG_COLUMNS`` 真实发布的波段标签
    (g/r/i/z) — ``"clear"`` 不是任何星表的波段标签, 透传给
    ``protocol.magnitude_column()`` 会抛 ``ValueError``, 故不进默认清单。
    """

    def __init__(
        self,  # 实例: 批量下载的参数集
        ra: float,  # 下载区中心赤经(度): 面向建库而非单源查询
        dec: float,  # 下载区中心赤纬(度): 与赤经共同界定天区
        radius_arcsec: float = 600.0,  # 下载半径(角秒): 默认比单源检索大一个量级
        bands: Optional[list[str]] = None,  # 波段列表可空: 缺省只收各星表真实发布的波段
        output_dir: str = "best_data",  # 输出目录: 相对当前工作目录解析, 创建由下载方负责
        resume: bool = True,  # 续传开关: 只影响已存在文件这一分支
    ) -> None:
        """构造批量下载输入 (字段语义见类 docstring 与逐属性行内注释)。"""
        # 下载区中心 (度) 与半径 (角秒); 默认 600 角秒比 ConeSearchInput 大一个
        # 量级, 面向批量建库而不是单源查询。
        self.ra = ra  # 赤经落属性: 与半径共同界定下载区
        self.dec = dec  # 赤纬落属性: 同上
        self.radius_arcsec = radius_arcsec  # 区域边界的唯一口径, 落盘不再二次裁剪
        # 需要落盘的波段列表; 缺省取 g/r/i/z。"clear" 不是任何星表
        # CATALOG_MAG_COLUMNS 里的波段标签 (budget doc §6.1 G2 登记的缺陷),
        # 透传给 protocol.magnitude_column() 会抛 ValueError, 故从默认清单
        # 中移除 (templates/best-config.yaml 的同一缺陷已在 Phase 5 修复,
        # 此处与模板保持同一口径)。
        self.bands = bands or ["g", "r", "i", "z"]  # 空列表按缺省处理; 显式传空即回落默认波段
        # 输出目录 (相对路径相对当前工作目录解析); 目录创建由下载方负责。
        self.output_dir = output_dir  # 目录落属性: 路径消毒在落盘那侧统一做
        # 断点续传开关: True 时跳过已完成的输出文件。
        self.resume = resume  # 只影响"已存在文件"这一分支, 不改变本次请求范围
