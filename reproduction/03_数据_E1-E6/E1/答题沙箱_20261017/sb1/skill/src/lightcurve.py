"""src.lightcurve — [deprecated shim] 已迁移到 src.multiband_photometry (P0 命名整改)。

能力边界: 本文件只做兼容转发, 不含任何实现, 登记二期删除。更名原因:
BEST 是均一定标星表 (一行 = 一个源的一套定标后测光值, 全库无 MJD/观测
时刻列), "lightcurve" 一名主动误导科学结论 — 把静态多波段测光讲成时序
是 E3 语义轴 A 的头号陷阱, E1 的 [已净化]2 也以误用本类为红线反模式。
权威实现: src.multiband_photometry.BestMultiBandPhotometry。
"""
from src.multiband_photometry import (  # noqa: F401 -- 权威实现直转, 零包装
    BestMultiBandPhotometry,  # 新名 (权威): 静态多波段测光, 非时序
)
from src.multiband_photometry import (
    BestMultiBandPhotometry as BestLightCurve,  # deprecated 别名 (P0 兼容期, 二期删除)
)

__all__ = ["BestMultiBandPhotometry", "BestLightCurve"]  # 新名在前, 旧名仅留兼容期
