# -*- coding: utf-8 -*-
"""交叉匹配的**客户端半径复核** —— D1 / AA4-P0-1 的判据级红测试。

被测命题: ``_cone_search_single`` 只接受**真正落在请求锥内**的源。

为什么这条值得单独立件: 本仓最贵的一类腐烂是「防御函数存在 ≠ 防御被调用」。
``_angular_separation_arcsec`` 早就在仓里, 但它只被用来**报告**角距, 从不用来
**拒绝**越界匹配 —— 于是 ``_cone_search_single`` 裸着 ``return result.sources[0]``,
站点返回什么就收什么。审计实测: 请求 **3 角秒**半径, 接受 **519.9 角秒**外的源,
失败码与原因都还是 ``None`` (即对外表现为「匹配成功」)。

修法是把**已有的**角距判据接到真实路径上, 不是新写一份 —— 所以本件要防的退化是
"哪天又有人把复核摘掉", 而那只会表现为下面第一条用例转红。

三条用例对应三种结局: 锥内照收、锥外拒收、**坐标缺失时不得当作锥内**。
最后一条是 fail-closed 的那一侧: 缺坐标算不出角距, 放行就等于把「无法判定」读成
「在锥内」, 那与本条要修的缺陷同型。
"""
from __future__ import annotations

import sys  # sys.path 锚定
from pathlib import Path  # 路径拼装
from types import SimpleNamespace  # 最小替身: 只需要 sources 与 success 两个字段

import pytest  # 参数化与断言

SKILL_ROOT = Path(__file__).resolve().parents[3]  # 仓根: 本件在 test/unit/crossmatch/ 下三级
if str(SKILL_ROOT) not in sys.path:  # 幂等: 让本件能 import src.*
    sys.path.insert(0, str(SKILL_ROOT))

from src.crossmatch import BestCrossMatch  # noqa: E402  被测类

# 请求半径: 取审计实测里那个刺眼的 3 角秒 —— 足够小, 任何越界都会被算出来
RADIUS_ARCSEC = 3.0


def _source(ra: float | None, dec: float | None):
    """造一条最小源替身 (只需坐标字段被复核逻辑读到)。"""
    return SimpleNamespace(ra=ra, dec=dec)  # SimpleNamespace: 不必走 BestSource 的完整构造


def _matcher(monkeypatch, sources: list) -> BestCrossMatch:
    """造一个只桩掉 ``cone_search`` 的 BestCrossMatch, 返回可直接调用的实例。

    只桩**这一个**方法: 复核逻辑就落在它下游, 桩别的一层就绕过了被测代码。
    """
    matcher = BestCrossMatch.__new__(BestCrossMatch)  # 绕开 __init__: 它的依赖与本命题无关
    matcher.client = SimpleNamespace(  # noqa: SLF001  测试替身: 这是本件唯一注入点
        cone_search=lambda **kw: SimpleNamespace(success=True, sources=sources))
    return matcher


class TestClientSideRadiusRecheck:
    """客户端必须自己复核半径, 不把站点的返回当既成事实。"""

    def test_source_inside_radius_is_accepted(self, monkeypatch):
        """锥内(0 角秒)照收 —— 防止把复核做成"一律拒绝"。"""
        matcher = _matcher(monkeypatch, [_source(10.0, 20.0)])
        src, code, err = matcher._cone_search_single(  # noqa: SLF001  直接打被测单元
            10.0, 20.0, "gaia", RADIUS_ARCSEC)
        assert src is not None, "锥内源不得被拒: 复核不是把门关死"
        assert (code, err) == (None, None), "匹配成功不得带失败码"

    def test_source_outside_radius_is_rejected(self, monkeypatch):
        """锥外(约 0.14 度 ≈ 519 角秒)必须拒 —— 这条就是缺陷本身。"""
        # 纬度差 0.144 度 ≈ 518 角秒: 与审计实测的 519.9 角秒同量级, 远超 3 角秒半径
        matcher = _matcher(monkeypatch, [_source(10.0, 20.0 + 0.144)])
        src, code, err = matcher._cone_search_single(  # noqa: SLF001
            10.0, 20.0, "gaia", RADIUS_ARCSEC)
        assert src is None, (
            f"越界源被收下了 (ra/dec 差 0.144 度 ≈ 518 角秒, 请求半径 {RADIUS_ARCSEC} 角秒) —— "
            f"客户端零复核, 站点返回什么就当什么"
        )
        assert (code, err) == (None, None), "越界应按 0 命中处理, 不是错误: 失败码会污染错误统计"

    def test_missing_coordinates_are_not_treated_as_inside(self, monkeypatch):
        """坐标缺失算不出角距 —— 必须按无法判定拒收, 不得放行 (禁 fail-open)。"""
        matcher = _matcher(monkeypatch, [_source(None, None)])
        src, code, _err = matcher._cone_search_single(  # noqa: SLF001
            10.0, 20.0, "gaia", RADIUS_ARCSEC)
        assert src is None, "缺坐标的源不得当作锥内放行: 那与「守不住半径」是同一类失效"

    def test_empty_result_is_zero_hit_not_failure(self, monkeypatch):
        """站点真没命中时仍是 (None, None, None) —— 复核不许把它变成失败码。"""
        matcher = _matcher(monkeypatch, [])
        src, code, err = matcher._cone_search_single(  # noqa: SLF001
            10.0, 20.0, "gaia", RADIUS_ARCSEC)
        assert (src, code, err) == (None, None, None), "0 命中不是错误: 这是原契约, 不得被改写"


if __name__ == "__main__":  # 手动跑也能看结论
    sys.exit(pytest.main([__file__, "-v"]))  # noqa: PLR2004  退出码就是失败数
