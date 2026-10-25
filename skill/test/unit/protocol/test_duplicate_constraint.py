# -*- coding: utf-8 -*-
"""同列多约束必须 fail-closed 的回归 (P0-16)。

职责: 钉住 ``build_query_form`` 对「同一个约束列被写两次」的处理。

缺陷形态 (审计轮次 AH3 §7 P0-16 实跑复现): 表单键是
``{prefix}.operation`` 这一**对**, 同一个前缀写第二次就是静默覆盖 ——
同一列先给 ``greaterequal 15.0`` 再给 ``lessequal 18.0`` 时, 产出只剩后者
(operation 键数 = 1), 于是「15 <= r <= 18 的区间」悄悄退化成「r <= 18」。
返回集里混进大量 r < 15 的源, 而调用方以为自己限了下界 —— **不抛错、不改退出码、
结果集看着完全正常**, 与铁律 5 禁的 fail-open 同一类。

处置选择显式抛错而非自动合并成 ``between``: 合并不总是合法的 —— 两次
``greaterequal``、或 ``contains`` 与 ``lessequal`` 的组合都无从合并, 猜一个
语义出来仍是静默给错答案。与同一函数里「未知操作符一律 ValueError」同处置。

依赖: 纯内存调用 ``build_query_form``, 零网络。
"""
from __future__ import annotations

# 第三方: pytest (raises / 参数化)
import pytest

# 本地: 约束项载体 + 表单构造单点 (被测)
from src.models import ColumnConstraint
from src.protocol import build_query_form


class TestDuplicateConstraintOnSameColumn:
    """同列两条约束: 静默覆盖是最坏结果, 必须显式拒绝。"""

    def test_lower_then_upper_is_rejected(self):
        """先下界后上界 (语义上是区间) 必须被拒, 而不是丢掉下界。"""
        items = [
            ColumnConstraint(name="ps1_rpsf", constraint="greaterequal", min=15.0),
            ColumnConstraint(name="ps1_rpsf", constraint="lessequal", max=18.0),
        ]
        with pytest.raises(ValueError, match="duplicate constraint on column"):
            build_query_form("ps1", items)

    def test_error_names_both_operations(self):
        """报错要点名冲突双方与合并键, 只说「重复」等于让人自己回溯。"""
        items = [
            ColumnConstraint(name="ps1_rpsf", constraint="greaterequal", min=15.0),
            ColumnConstraint(name="ps1_rpsf", constraint="lessequal", max=18.0),
        ]
        with pytest.raises(ValueError) as excinfo:
            build_query_form("ps1", items)
        message = str(excinfo.value)
        assert "greaterequal" in message and "lessequal" in message, message  # 冲突双方都在
        assert "between" in message, f"报错须给出路 (合并成 between): {message}"  # 不是只报错不给修法

    def test_order_does_not_matter(self):
        """反序同样被拒 —— 判据是「本列已有约束」, 不是「谁先谁后」。"""
        items = [
            ColumnConstraint(name="ps1_rpsf", constraint="lessequal", max=18.0),
            ColumnConstraint(name="ps1_rpsf", constraint="greaterequal", min=15.0),
        ]
        with pytest.raises(ValueError, match="duplicate constraint on column"):
            build_query_form("ps1", items)  # 反序也命中: 守卫记的是"已占用", 不看先后

    def test_same_operation_twice_is_also_rejected(self):
        """两次同操作符也拒: 第二次仍然是静默丢弃第一次的取值。"""
        items = [
            ColumnConstraint(name="ps1_rpsf", constraint="lessequal", max=18.0),
            ColumnConstraint(name="ps1_rpsf", constraint="lessequal", max=17.0),
        ]
        with pytest.raises(ValueError, match="duplicate constraint on column"):
            build_query_form("ps1", items)  # 同名同操作也要拒: 丢的是取值, 同样无人察觉


class TestSingleConstraintPathsUnaffected:
    """反向对照: 合法用法一个都不能被新守卫误伤。"""

    def test_single_between_constraint_still_builds(self):
        """单条 between 照旧产出四键 (这是最常见的正常用法)。"""
        form = build_query_form("ps1", [
            ColumnConstraint(name="ps1_rpsf", constraint="between", min=15.0, max=18.0),
        ])
        assert form["ps1.rpsf.operation"] == "between"  # 操作符逐字下发
        # 取值走 str() 落表单, 故是 "15.0" 而非 "15" —— 断逐字值而不是断"差不多":
        # 表单键值变了服务端就换了个查询, 容忍写法等于放行静默改写。
        assert form["ps1.rpsf.min"] == "15.0" and form["ps1.rpsf.max"] == "18.0"

    def test_two_different_columns_still_both_emit(self):
        """不同列的两个约束照旧各出一组 —— 守卫判的是列不是「第二条」。"""
        form = build_query_form("ps1", [
            ColumnConstraint(name="ps1_rpsf", constraint="greaterequal", min=15.0),
            ColumnConstraint(name="ps1_gpsf", constraint="lessequal", max=18.0),
        ])
        operations = sorted(k for k in form if k.endswith(".operation"))
        assert operations == ["ps1.gpsf.operation", "ps1.rpsf.operation"]  # 两个都在
        assert form["ps1.rpsf.constraint"] == "15.0" and form["ps1.gpsf.constraint"] == "18.0"

    def test_no_constraints_at_all_is_fine(self):
        """空约束集不触守卫 (守卫只在逐项循环里登记列)。"""
        form = build_query_form("ps1", [])
        assert not [k for k in form if k.endswith(".operation")]
