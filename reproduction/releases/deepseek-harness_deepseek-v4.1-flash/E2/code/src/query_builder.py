"""src.query_builder — Column constraint query builder for BEST database.

能力边界: BestQuery: 列约束查询**构造器** (catalog/cone/box/mag_range/where 等流畅接口)。边界: 只构造约束描述, 不直接发请求 (发请求是 src.client 的职责); 签名与 contracts/input.contract.yaml 对齐 (Q-30)。类名 BestQuery 是契约层 input schema 身份 (contracts/fields/*.contract.yaml), 不随模块更名改动。
白盒锚点: references/ALGORITHM-SPEC.md §2 (query_builder 锚点)。

【权威学术来源锚定】
  - NADC China-VO BEST REST API 规范 (2023): 列约束表单查询范式（equal/less/between/in 等）, 公式定位: 规范全文。规范引用（无 DOI）, 见 docs/plans/doi_truth_registry.json 关联注记 (该文件在本仓
      不存在, 2026-10-03 实测)。
  - 开源依赖: 无第三方数值依赖 (纯 stdlib dataclasses)。
Rule 9 状态: [VERIFIED_ALGO]（标准基准算法; 物理可解释输出, 无伪概率打分）。

BEST 采用表单式查询系统, 每一列可带:
  - 约束类型 (equal, notequal, less, between, contains, in)
  - min/max 值
  - 文件上传
  - 排序
  - 显示/隐藏开关

本模块提供构造这类查询的流畅 (fluent) 构建器。
"""

from __future__ import annotations

# 标准库: Optional 类型标注
from typing import Optional

# 本地: ColumnConstraint 为列约束数据模型; protocol 侧提供权威表单渲染
# (build_query_form)、星表列名解析 (magnitude_column/quality_column) 与
# phase-1 唯一合法 output.fmt 常量 PHASE1_HANDOFF_FORMAT — 构建器不自建
# 表单键集 (Q-30)
from src.models import ColumnConstraint
from src.protocol import (
    PHASE1_HANDOFF_FORMAT,  # 阶段一唯一合法格式常量: 只有这个形态会交回会话标识
    build_query_form,  # 表单渲染单点: 构建器不自建键集, 与客户端不可能再漂移
    magnitude_column,  # 波段到列名映射: 未发布该波段的表在这里抛错
    quality_column,  # 质量指标列名: 按指标名查列, 查不到即抛而不是约束空气列
)


class BestQuery:
    """BEST 表单查询的流畅构建器。

    为 BEST 网页查询接口构造列约束。

    P1-10: 空间选择 (``cone``/``box``) 以原生区域形式记录, 并由权威协议层
    经 :meth:`to_form` 渲染 — 与 ``BestClient.cone_search`` 走同一条路径。
    不要改回 box-between 的 RA/Dec 约束: 服务端 ``pos.*`` 键集从不接受那一组
    键, 那样锥形检索在结构上就是坏的, 且与 client 行为分叉。
    """

    def __init__(self) -> None:
        """初始化空查询: 默认 ps1 星表/csv 输出/50000 行上限, 无空间区域。

        构造**不做校验也不联网**: 纯内存字段初始化, 因此 fluent 链可以
        在离线测试里整条跑通而无需替身站点。列名/波段合法性在真正
        ``to_form()`` 时由协议层统一判定。
        """
        self._constraints: list[ColumnConstraint] = []                 # 唯一可变状态: append 顺序即输出顺序, 重建快照也按这个序
        self._catalog: str = "ps1"                                    # 缺省 ps1: 调用面最常用的目标表。**不是唯一全波段** (CATALOG_MAG_COLUMNS
            # 里 stripe82 5 个、smss_dr4 6 个、uss_dr1 12 个、scr_galah/scr_lamost 各 30 个波段标签,
            # ps1 只有 g/i/r/y/z 5 个)
        self._output_format: str = "csv"                              # 只作自省元数据, 不上线也不校验
        self._max_rows: int = 50000                                   # 5 万行贴着站点单次返回的实际天花板, 再大只会被服务端截断
        # 锥搜区域三元组, 单位角秒: (ra_deg, dec_deg, radius_arcsec);
        # 注意半径是角秒而坐标是度 — 内部由 cone() 统一换算, 见 references 单位陷阱
        self._cone: Optional[tuple[float, float, float]] = None
        # box 存四个度的边界值 (不经换算): 协议层按 rect 键集原样渲染。
        self._box: Optional[tuple[float, float, float, float]] = None

    def catalog(self, name: str) -> BestQuery:
        """设置目标星表。

        Args:
            name: 在线星表 id — ps1, stripe82, gaia_dr3_18, jplus_dr3, smss_dr4,
                landolt, uss_dr1, splus_dr4, scr_galah, scr_lamost, xpsp, dr3xpcorr
                (``gaia_dr3`` 仍作为遗留别名接受; ``std`` 是星表组而非表)

        Returns:
            self
        """
        self._catalog = name                                         # 不校验表名: 在线 id 的合法性由 protocol 层在 to_form 时统一判
        return self  # 原样收表名: 合法性在渲染表单时由协议层统一判

    # --- Spatial constraints ---

    def cone(self, ra: float, dec: float, radius_deg: float) -> BestQuery:
        """锥形检索约束 (服务端原生 cone, P1-10)。

        与 box 互斥: 设置 cone 会清掉已设的 box。

        Args:
            ra: 中心 RA (单位: 度)
            dec: 中心 Dec (单位: 度)
            radius_deg: 半径 (单位: 度; 内部换算为角秒填入
                ``pos.radius`` 表单字段)

        Returns:
            self
        """
        # 3600.0 是度→角秒的唯一换算点: pos.radius 的表单单位是角秒,
        # 而本方法签名收的是度, 换算只此一处, 便于审计。
        self._cone = (float(ra), float(dec), float(radius_deg) * 3600.0)  # 坐标一并转 float: 免得 int/str 混进后面的数值比较
        # 互斥靠显式置 None 而非"后设者胜"的隐式规则: 留着旧的会让
        # to_form 同时带上 cone 与 box 两套 pos 键, 站点行为不可预期。
        self._box = None                                                   # 显式清位而不是删键: _box 恒为四元组或 None, 形状稳定
        return self

    def box(self, ra_min: float, ra_max: float, dec_min: float, dec_max: float) -> BestQuery:
        """矩形区域约束 (服务端原生 rect, P1-10)。

        与 cone 互斥: 设置 box 会清掉已设的 cone。

        Args:
            ra_min: RA 下限
            ra_max: RA 上限
            dec_min: Dec 下限
            dec_max: Dec 上限

        Returns:
            self
        """
        self._box = (float(ra_min), float(ra_max), float(dec_min), float(dec_max))  # 原样收度数不做换算: 协议层按 rect 键集直接渲染
        # 对称互斥: 与 cone() 同一纪律, 谁后设谁清对方。
        self._cone = None                                                              # 锥搜条件先置空: 未 set_cone 时不该带着上一次的残留条件
        return self

    # --- Magnitude constraints ---

    def mag_range(self, mag_min: float, mag_max: float, band: str = "r") -> BestQuery:
        """按星等范围过滤。

        Args:
            mag_min: 星等下限
            mag_max: 星等上限
            band: 星表发布的波段 (见 ``protocol.CATALOG_MAG_COLUMNS``);
                星表未发布的波段会抛 ``ValueError``, 而不是去约束一个
                不存在的列。

        Returns:
            self
        """
        # 列名解析委托协议层: 同一 (星表, 波段) 在 client 与 builder 两侧
        # 必须解析成同一列名, 各写一份映射迟早漂移。
        col = magnitude_column(self._catalog, band)  # 抛 ValueError 而非静默跳过: 未发布该波段的表不该被约束一个不存在的列
        # between + min/max 是本方法唯一的操作符形态: 星等区间天然双端。
        self._constraints.append(ColumnConstraint(name=col, constraint="between", min=mag_min, max=mag_max))
        return self

    def mag_brighter_than(self, mag_limit: float, band: str = "r") -> BestQuery:
        """过滤比给定极限星等更亮的源。

        Args:
            mag_limit: 星等极限 (如 18.0)
            band: 星表发布的波段

        Returns:
            self
        """
        col = magnitude_column(self._catalog, band)  # 列名解析只有协议层这一份实现, builder 不再自建映射
        # 星等越小越亮, 故"更亮"是 less (值存 max 槽) — 这里最容易
        # 写成 greater, 那样筛出来的是更暗的源, 语义正好相反。
        self._constraints.append(ColumnConstraint(name=col, constraint="less", max=mag_limit))  # 站点的 less 用 max 槽承载上界, 槽位约定与 between 相同
        return self

    # --- Quality constraints ---

    def min_snr(self, value: float) -> BestQuery:
        """最低信噪比过滤 (仅对发布 S/N 列的星表有效)。

        Raises:
            ValueError: 星表未发布 SNR 列 — 没有任何星表有字面 ``snr`` 列,
                按字面名去约束就会静默匹配不到任何源。
        """
        col = quality_column(self._catalog, "snr")  # 按指标名查列: 约束字面列名会静默匹配不到任何源
        # greaterequal (站点拼写) + 值放 min 槽: 与 mag_brighter_than 的
        # less/max 形成对照, 两条都是"越小越…就…", 别混。
        self._constraints.append(ColumnConstraint(name=col, constraint="greaterequal", min=value))  # 操作符拼写照抄站点表单
        return self

    def max_fwhm(self, value: float) -> BestQuery:
        """最大 FWHM 过滤。

        Raises:
            ValueError: 没有任何 BEST 星表发布 FWHM 列。
        """
        col = quality_column(self._catalog, "fwhm")  # 同上按指标名查列: 无星表发布 FWHM, 这条约束实际总抛
        # 越小越锐利 ⇒ 上限过滤, 站点操作符是 lessequal (无空格连写)。
        self._constraints.append(ColumnConstraint(name=col, constraint="lessequal", max=value))
        return self

    def class_star_min(self, value: float = 0.9) -> BestQuery:
        """最低 class_star (恒星相似度) 过滤。

        Args:
            value: 恒星相似度下限, 缺省 0.9 (只留高可信恒星候选)。

        Raises:
            ValueError: 星表未发布 class_star 列。
        """
        col = quality_column(self._catalog, "class_star")  # 点源分类列: 同样经协议层查列, 不猜列名
        # 缺省 0.9 而非 0.5: BEST 的 class_star 分布偏低, 中位阈值会
        # 混进大量星系; 0.9 是经验上区分度较好的起点。
        self._constraints.append(ColumnConstraint(name=col, constraint="greaterequal", min=value))
        return self

    # --- Custom constraints ---

    def where(self, column: str, constraint: str, min: Optional[float] = None,
              max: Optional[float] = None, value: Optional[str] = None) -> BestQuery:
        """追加一个列约束。

        操作符必须落在 BEST 表单实际接受的白名单内, 该白名单由协议层
        :data:`src.protocol.ALLOWED_OPERATIONS` 持有并在
        ``to_form()`` 时**强制校验**: equal, notequal, less, lessequal,
        greaterequal, between, contains, in。
        **白名单外的操作符会抛 ``ValueError``, 不是静默下发** —— 因为站点对
        未知操作符既不报错也不忽略, 而是收下后返回**空表**, 一次拼错就会让
        "按星等筛过"的结果集看起来像"这片天区没有源"。

        ..Warning::
           ``grater`` **不在**白名单内。旧文档称 strict-greater 的站点拼写是
           它, 但 2026-10-05 实站逐项实测 (``temp/h3/probe_operation2.json``):
           同一锥、同一列, ``greaterequal`` 出 1559 行而 ``grater`` 出 0 行。
           想要"大于等于"请用 ``greaterequal``; 站点的严格大于拼写尚未取证,
           本仓不做映射 —— 静默产出空结果比抛错危险得多。

        Args:
            column: 列名 (可写裸名/带表前缀/点号限定, 统一过 qualify_column)
            constraint: 约束操作符 (上面的白名单之一; 非法值在 ``to_form()`` 抛错)
            min: 下界 (greaterequal 用)
            max: 上界 (between/lessequal/less 用)
            value: 单值 (equal/contains/in 用)

        Returns:
            self (链式调用)

        Raises:
            ValueError: ``to_form()`` 时操作符不在 ``ALLOWED_OPERATIONS`` 内, 或
                列名/波段在该星表上不存在。
        """
        # 原样收 column, 不在此 qualify: 列名方言的归一由协议层做,
        # builder 再来一份就又是一次"两处规则不同"的机会。
        self._constraints.append(ColumnConstraint(name=column, constraint=constraint, min=min, max=max, value=value))  # 原样收列名: 方言归一是协议层的活, builder 再来一份必再漂移一次
        return self

    # --- Output control ---

    def limit(self, n: int) -> BestQuery:
        """设置最大返回行数。

        Args:
            n: 最多取回的记录数 (分页循环的上限, 非单页行数)

        Returns:
            self (链式调用)
        """
        # 直接覆盖而非取小: 调用方显式设 limit 就是最终意图, 静默求 min
        # 会让第二次调用悄悄失效, 排查时看不出是哪里被改写。
        self._max_rows = n  # 覆盖而非取小: 静默求 min 会让第二次调用悄悄失效
        return self

    def output_format(self, fmt: str) -> BestQuery:
        """设置输出格式 (仅元数据, 不上线)。

        phase-1 必须提交 ``output.fmt=html`` — 只有这个形态会交回 ``sqlid`` —
        因此这里设的值只由 :meth:`build` 报告, 永远不会进请求。真正的取数格式
        由 phase-2 的 ``output.fmt`` 决定 (csv/json/votable/fits)。
        """
        self._output_format = fmt  # 不校验也不上线: phase-1 恒提交 html, 这里只留给人读
        return self

    def build(self) -> dict:
        """生成查询参数字典。

        Returns:
            含 constraints / catalog / output_format / max_rows, 以及原生空间
            区域 (``cone`` 或 ``box``, 二者至多一个被设置) 的 dict。

        Note:
            这是**只读快照**形态而非表单: 键名与 :meth:`to_form` 的协议层
            键集刻意不同 (这里是 Python 侧字段名), 因为它面向调用方
            自省/序列化, 不面向站点提交。两者都返回 dict 却不可互换。
        """
        return {
            "constraints": self._constraints,
            "catalog": self._catalog,
            "output_format": self._output_format,
            "max_rows": self._max_rows,
            "cone": self._cone,
            "box": self._box,
        }

    def to_form(self) -> dict[str, str]:
        """把查询渲染成 BEST phase-1 表单 (P1-10)。

        委派 ``protocol.build_query_form`` — 与 ``BestClient`` 同一个权威层 —
        这样链式构造器与客户端对同一组参数不可能再产出不同的键集 (两边各写
        一份的话键集必然漂移)。
        """
        cone = self._cone  # 先取局部量: 三次下标读同一快照, 中途被改不会半新半旧
        # 三个三元组下标分别喂 ra/dec/radius_arcsec: 少传一个就会退化成
        # 无空间约束的表单, 而那是一次"看起来成功"的错误查询。
        return build_query_form(
            self._catalog,  # 星表传首位: 渲染层靠它解析波段与质量列
            self._constraints,  # 约束列表整份传: 顺序即输出顺序, 不重排
            output_format=PHASE1_HANDOFF_FORMAT,  # 格式固定为交接常量: 阶段一恒提交 html, 别的形态拿不回会话标识
            ra=cone[0] if cone else None,  # 赤经来自锥搜快照: 没有区域时为空而不是零
            dec=cone[1] if cone else None,  # 赤纬同理: 与赤经必须同时有或同时无
            radius_arcsec=cone[2] if cone else None,  # 半径同理: 少传一个就退化成无空间约束的错误查询
            box=self._box,  # 矩形区域整份传: 协议层按矩形键集原样渲染
        )

    def __str__(self) -> str:
        """人类可读的查询摘要 (日志与报错信息里标识"这次查了什么")。

        Returns:
            形如 ``BestQuery(catalog=ps1, constraints=3, max_rows=50000)`` 的
            一行摘要; 只报计数不报内容, 避免把用户坐标/约束写进日志。

        Note:
            刻意不实现 ``__repr__``: 默认 repr 会展开全部约束字段, 在
            traceback 里可能泄露查询参数。
        """
        return f"BestQuery(catalog={self._catalog}, constraints={len(self._constraints)}, max_rows={self._max_rows})"

