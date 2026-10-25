# -*- coding: utf-8 -*-
"""TAP ADQL 子集解析器测试 (路由语义还原自 pybest 打包产物, git 6f00efeb^〔本仓历史已无此对象〕)。

分两类互锁的回归:
- TestSupportedSubset: 守"该放行的必须放行" (锥形查询/表别名/BETWEEN/ORDER BY 混序/
  OR 拆分支/裸 CONTAINS);
- TestRejectedQueries: 守"该拒的必须拒" (JOIN/聚合/子查询/UNION/未登记列/越界几何/
  注入串/非整数 TOP/非 ICRS 坐标系), 每一条都对应一次真实误用或攻击面。
"""
from __future__ import annotations

import pytest  # 第三方: 参数化 + 负路径 raises

# 本地: TAP ADQL 子集解析器权威入口; 任何不接受的结构都抛 ADQLError
from src.tap.adql import ADQLError, parse_adql


class TestSupportedSubset:
    """ADQL 白名单子集: 这些写法必须解析成结构化 plan, 不能误拒。"""

    def test_simple_cone_query(self):
        """锥形查询要解析出 catalog、TOP 限数、投影列与分支内的锥几何 (ra/dec/半径)。

        回归锚点: 半径单位是度 (CIRCLE 第三参), 与表单的 arcsec 不同, 换算在执行器做。
        """
        plan = parse_adql(  # 完整锥形查询: 投影 + TOP + 几何条件
            "SELECT TOP 5 ra, dec, ps1_rpsf FROM best.ps1 "
            "WHERE CONTAINS(POINT('ICRS', ps1_ra, ps1_dec), "
            "CIRCLE('ICRS', 180.0, 30.0, 0.1)) = 1"
        )
        assert plan.catalog == "ps1"  # best.ps1 -> catalog 不带表前缀
        assert plan.limit == 5  # TOP 5 落成 limit
        assert plan.columns == ("ps1_ra", "ps1_dec", "ps1_rpsf")  # ra/dec 归一成星表实际列名
        cone = plan.branches[0].cone  # 无 OR 时只有一个分支
        assert cone is not None  # 锥形不能被降级塞进普通约束
        assert cone.ra == 180.0 and cone.dec == 30.0 and cone.radius_deg == 0.1  # 半径单位是度

    def test_star_select_and_alias(self):
        """SELECT * 时 columns 为 None (全列), 表别名 AS p 不得污染约束列名。"""
        plan = parse_adql("SELECT * FROM best.ps1 AS p WHERE p.ps1_rpsf BETWEEN 15 AND 16")  # 别名 + BETWEEN
        assert plan.columns is None  # SELECT * 记 None, 不展开成列清单
        assert plan.branches[0].constraints[0].column == "ps1_rpsf"  # 别名 p. 不得留在列名里
        assert plan.branches[0].constraints[0].operation == "between"  # 操作符归一成小写

    def test_order_by_asc_and_desc(self):
        """ORDER BY 支持多键混合升降序; 列名归一成星表实际列名 (ra -> ps1_ra)。"""
        plan = parse_adql("SELECT ra FROM best.ps1 ORDER BY ps1_rpsf DESC, ra ASC")  # 多键混排
        assert [t.column for t in plan.order_by] == ["ps1_rpsf", "ps1_ra"]  # ra 也要归一成 ps1_ra
        assert [t.descending for t in plan.order_by] == [True, False]  # 逐键记方向, 不只记首个

    def test_and_or_branches(self):
        """OR 顶层拆成两个分支 —— 执行器据此分别取数再合并去重。"""
        plan = parse_adql(                                                                         # 解析 ADQL: 计划对象是后续断言的基准
            "SELECT ra FROM best.ps1 WHERE ps1_rpsf < 16 OR ps1_rpsf > 18"
        )  # OR 不合并条件, 顶层就拆成两个分支
        assert len(plan.branches) == 2  # 执行器据此分别取数再合并去重

    def test_contains_without_comparison(self):
        """裸 CONTAINS(...) (不带 = 1 比较) 也要识别为锥形条件。"""
        plan = parse_adql(                                                                          # 同上, 另一条查询
            "SELECT ra FROM best.ps1 WHERE CONTAINS(POINT('ICRS', ps1_ra, ps1_dec), "
            "CIRCLE('ICRS', 10.0, 20.0, 0.5))"
        )  # 裸 CONTAINS 不带 = 1 也算锥形
        assert plan.branches[0].cone is not None  # 少写比较值不等于不认锥


class TestRejectedQueries:
    """ADQL 白名单之外一律拒: 解析器是安全边界, 不是通用 SQL 前端。"""

    @pytest.mark.parametrize(
        "query",
        [
            # 结构化语法: JOIN / 聚合 / GROUP BY / 子查询 / UNION 均不在子集内
            "SELECT ra FROM best.ps1 JOIN best.stripe82 ON 1 = 1",
            "SELECT COUNT(*) FROM best.ps1",
            "SELECT ra FROM best.ps1 GROUP BY ra",
            "SELECT ra FROM (SELECT ra FROM best.ps1)",
            "SELECT ra FROM best.ps1 UNION SELECT ra FROM best.stripe82",
            # 白名单: 未登记星表 (best.nope) 与未登记列名 (nope) 必须拒
            "SELECT ra FROM best.nope",
            "SELECT nope FROM best.ps1",
            # 几何语义: POINT 的 ra/dec 写反、ra=400 越界、半径 0 都拒
            "SELECT ra FROM best.ps1 WHERE CONTAINS(POINT('ICRS', ps1_dec, ps1_ra), CIRCLE('ICRS', 10, 20, 0.1)) = 1",
            "SELECT ra FROM best.ps1 WHERE CONTAINS(POINT('ICRS', ps1_ra, ps1_dec), CIRCLE('ICRS', 400, 20, 0.1)) = 1",
            "SELECT ra FROM best.ps1 WHERE CONTAINS(POINT('ICRS', ps1_ra, ps1_dec), CIRCLE('ICRS', 10, 20, 0)) = 1",
            # 注入与注释: 分号叠句、SQL 行注释
            "SELECT ra FROM best.ps1; DROP TABLE x",
            "SELECT ra FROM best.ps1 -- comment",
            # TOP 必须是非负整数: 0 与 1.5 都拒
            "SELECT TOP 0 ra FROM best.ps1",
            "SELECT TOP 1.5 ra FROM best.ps1",
            # CONTAINS 比较值只能是 1; 坐标系只认 ICRS
            "SELECT ra FROM best.ps1 WHERE CONTAINS(POINT('ICRS', ps1_ra, ps1_dec), CIRCLE('ICRS', 10, 20, 0.1)) = 2",
            "SELECT ra FROM best.ps1 WHERE CONTAINS(POINT('Galactic', ps1_ra, ps1_dec), CIRCLE('ICRS', 10, 20, 0.1)) = 1",
        ],
    )
    def test_rejected(self, query: str):
        """白名单外语法/越界几何/注入串一律抛 ADQLError, 不得静默放行到执行层。"""
        with pytest.raises(ADQLError):  # 拒必须发生在解析层, 不得下沉到执行层
            parse_adql(query)  # 逐条喂白名单外的串

    def test_empty_query_rejected(self):
        """纯空白查询要在入口处拒绝, 错误消息含 "cannot be empty"。"""
        with pytest.raises(ADQLError, match="cannot be empty"):  # 消息钉住入口校验
            parse_adql("   ")  # 纯空白串

    def test_or_branch_bomb_is_capped(self):
        """OR 分支数超过 max_branches 必须拒绝, 防止分支炸弹把执行器拖死。

        回归锚点: OR 分支数必须有上限 — 照单全收时每个分支一次 HTTP,
        40 个 OR 就足以把服务端打挂。
        """
        clauses = " OR ".join(f"ps1_rpsf < {16 + i * 0.001}" for i in range(40))  # 造 40 个 OR 分支
        with pytest.raises(ADQLError, match="too many OR branches"):  # 分支炸弹在解析层被挡
            parse_adql(f"SELECT ra FROM best.ps1 WHERE {clauses}", max_branches=16)  # 上限由调用方给

    def test_only_one_cone_per_branch(self):
        """同一分支只允许一个锥形: 两个 CIRCLE 用 AND 连要拒 (球面交集不在子集内)。"""
        with pytest.raises(ADQLError, match="Only one cone"):  # 球面交集不在子集内
            parse_adql(
                "SELECT ra FROM best.ps1 WHERE "
                "CONTAINS(POINT('ICRS', ps1_ra, ps1_dec), CIRCLE('ICRS', 10, 20, 0.1)) = 1 AND "
                "CONTAINS(POINT('ICRS', ps1_ra, ps1_dec), CIRCLE('ICRS', 11, 21, 0.1)) = 1"
            )  # 两个 CIRCLE 用 AND 连, 仍算同一个分支
