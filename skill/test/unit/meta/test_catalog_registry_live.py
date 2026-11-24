"""BEST 端点与星表清单的「线路事实」门禁 (wire-fact gate)。

此处每条断言均对 https://nadc.china-vo.org/data/best 实测核对过。
该服务对未知路由返回 HTTP 200 + ``{"error":"Not Found"}`` 响应体, 因此
「状态码 == 200」这类门禁根本看不出一个星表 id 是否已经死掉 — 正是下面这些
检查在保证 protocol 层星表注册表的诚实: 多登记一项就是虚构路由, 少登记一项
就是功能静默流失。
"""

from __future__ import annotations  # 标准库: 注解延迟求值 (PY310 前的泛型写法也能过)

# 第三方: pytest.raises 承载「必须抛 ValueError」的负路径断言
import pytest

# 本地: protocol 层权威星表注册表 / 查询表单构造 / 列名白名单 (跨协议能力边界)
from src.protocol import (
    CATALOG_ALIASES,  # 别名表: 旧拼写要解析到真实星表, 门禁逐条钉
    CATALOG_COLUMNS,  # 列名白名单: 虚构列与漏登记两类偏差都在这里
    CATALOG_DISPLAY,  # 展示元数据: 缺了用户侧就没有可读名字
    CATALOG_GROUPS,  # 导航组: 导航组不是星表, 不可当查询目标
    CATALOG_PATHS,  # 查询路径注册表: 这道门禁的主角
    PHASE1_HANDOFF_FORMAT,  # 交接格式: 阶段间的数据形态契约
    SUPPORTED_OUTPUT_FORMATS,  # 支持的输出格式全集
    build_query_form,  # 表单构造: 空间选择的翻译点
    catalog_tables,  # 星表表清单: 交叉匹配的输入
    count_sqlid,  # 计数端点路径
    qualify_column,  # 列名限定: fail-closed 的那道闸
    resolve_catalog,  # 星表解析: 导航组与未知星表都要显式失败
)

# 实测「可查询星表」全集 (现场核对): 注册表与此集合的任何偏差
# 都意味着向用户暴露虚构路由或悄悄丢失一个星表, 由 test_registry_* 钉住。
LIVE_CATALOGS = {                                                                          # 实测可查询星表全集: 多登记即虚构路由, 少登记即功能流失
    "ps1", "stripe82", "gaia_dr3_18", "jplus_dr3", "smss_dr4", "landolt",
    "uss_dr1", "splus_dr4", "scr_galah", "scr_lamost", "xpsp", "dr3xpcorr",
}

# 实测各星表表单页 showcol 可选列数 (2026-09-29 逐页核对): 静态列清单与线上
# 的任何偏差要么是**虚构列** (服务端静默丢弃未知 showcol 键 -> 默认投影丢列),
# 要么是**漏登记** (qualify_column fail-closed -> 该列不可请求)。两类偏差都不
# 抛异常, 只有本门禁能发现 (证据 temp/audit_column_drift_results.json:
# smss_dr4/uss_dr1 的 psf_mag/source_id 列服务端不再返回, gaia_dr3_18/scr_*/
# xpsp 的静态清单覆盖率低至 4%)。
LIVE_SHOWCOL_COUNTS = {                                                                  # 实测各表可选列数: 偏差要么虚构列要么漏登记, 两者都不抛异常
    "ps1": 30, "stripe82": 42, "gaia_dr3_18": 155, "jplus_dr3": 8,
    "smss_dr4": 8, "landolt": 49, "uss_dr1": 96, "splus_dr4": 41,
    "scr_galah": 137, "scr_lamost": 137, "xpsp": 287, "dr3xpcorr": 17,
}


def test_registry_matches_the_live_queryable_inventory():
    """CATALOG_PATHS 的键集必须与实测可查询星表逐一相等 (不多不少)。

    双向相等而非只判"都在里面": 少登记一张表是能力缺失, 多登记一张则是把
    请求发到不存在的路由上, 两种错的修法完全相反, 必须一次说清。
    """
    assert set(CATALOG_PATHS) == LIVE_CATALOGS  # 双向相等: 少登记=能力缺失, 多登记=虚构路由


def test_query_routes_take_the_bare_id_never_a_navigation_group():
    """每个星表的查询路径必须是裸 id 的 ``<catalog>/q``, 不得带导航组前缀。

    ``calib/stripe82/q``、``std/scr_galah/q`` 这类带组前缀的路径在线路上是
    软 404 (HTTP 200 + error body), 拼错即静默拿不到数据。
    """
    for catalog, path in CATALOG_PATHS.items():                                                     # 逐表核对路径形态
        assert path == f"{catalog}/q"  # 裸 id 契约: 拼错的路径在线上是软 404, 不报错
    # calib/stripe82/q 与 std/scr_galah/q 在线路上是软 404, 一律不得出现。
    assert not any(path.startswith(("calib/", "std/", "other/"))  # 导航组不是星表, 不可当查询目标
                   for path in CATALOG_PATHS.values())                                        # 导航组前缀一律不得出现: 带组前缀在线上是软 404


def test_every_catalog_has_display_metadata_and_columns():
    """每个星表都必须有展示元数据和非空列清单 (展示层与列名白名单同时成立)。

    空列清单判据要留着: 一张"登记了但列被清空"的表会退化成只投影 ra/dec,
    查询照跑、结果照出, 要到用户发现拿不到想要的量时才暴露, 那时已经很难
    定位到是注册表缺项。
    """
    for catalog in CATALOG_PATHS:                                                                   # 逐表核对展示元数据与列清单
        assert catalog in CATALOG_DISPLAY  # 缺展示元数据 = 用户侧没有可读的名字
        assert CATALOG_COLUMNS[catalog], catalog  # 非空列: 空清单会退化成只投影 ra/dec


def test_static_columns_match_the_live_showcol_counts():
    """CATALOG_COLUMNS 的列数必须与线上表单页 showcol 数逐一相等 (不多不少)。

    2026-09-29 线上审计 (temp/audit_column_drift.py) 实测出两类静默漂移:
    smss_dr4/uss_dr1 的 psf_mag/source_id 幻影列 (服务端丢弃后默认投影只剩
    ra/dec), gaia_dr3_18/scr_galah/scr_lamost/xpsp 的静态清单只覆盖线上可选列的
    4%~24%。本门禁把线上列数钉住: 站点再改列, 这里先红, 逼着同步静态表
    并重跑 temp/audit_acceptance_full_coverage.py 验收。
    """
    for catalog, count in LIVE_SHOWCOL_COUNTS.items():                                             # 逐表比列数: 少了是漏登记, 多了是虚构列
        assert len(CATALOG_COLUMNS[catalog]) == count, catalog  # 逐表等值: 少登记即 fail-closed
    # 旧拼写不保留独立副本 (否则两份清单必然分叉), 兼容改由 CATALOG_ALIASES +
    # 调用点归一承担。断言要求副本已消失, 且别名指向的规范表与被比较的表一致。
    assert "gaia_dr3" not in CATALOG_COLUMNS, (  # 副本存在即漂移源: 两份清单必然分叉
        "旧拼写不应再有独立字面副本 (会与规范表漂移)")                                                              # 报出方向: 这条要挡的是旧拼写在别处留了独立副本
    assert CATALOG_ALIASES["gaia_dr3"] == "gaia_dr3_18"  # 兼容只走别名, 不再各自持有一份列
    assert CATALOG_COLUMNS[CATALOG_ALIASES["gaia_dr3"]] == CATALOG_COLUMNS["gaia_dr3_18"]        # 别名必须解析到同一份列清单: 两份副本必然会漂


def test_navigation_groups_resolve_to_their_member_tables():
    """导航组 (std/calib/other) 只能映射到其成员表, 自身不可当查询目标。

    ``resolve_catalog("std")`` 抛 ValueError 是能力边界: 导航组不是星表,
    让它通过会把请求发到一个不存在的 /q 路由上。
    """
    assert set(CATALOG_GROUPS["std"]) == {"scr_galah", "scr_lamost", "xpsp"}  # 组->成员表是纯映射
    with pytest.raises(ValueError, match="scr_galah"):  # 导航组自身被查: 错误信息须指名成员表
        resolve_catalog("std")                                                                      # 导航组在解析层就要被拒
    with pytest.raises(ValueError, match="Unknown"):  # 完全未登记的 id 走另一条报错路径
        resolve_catalog("no_such_catalog")                                                          # 未知星表同样显式失败


def test_legacy_gaia_dr3_spelling_is_routed_onto_the_live_identifier():
    """旧拼写 ``gaia_dr3`` 必须改写到线上真实 id ``gaia_dr3_18`` 后再构造表单。

    历史教训: 表单里若残留 ``gaia_dr3.`` 前缀的 showcol, 服务端按未注册表名
    处理, 查询静默失败 — 因此这里同时断言旧前缀一列都不剩。
    """
    assert resolve_catalog("gaia_dr3") == "gaia_dr3_18"  # 别名先归一再构造表单
    form = build_query_form("gaia_dr3", ra=187.7, dec=12.37, radius_arcsec=30)                      # 用别名构造: 拼错前缀在线上是软 404
    assert form["output.fmt"] == PHASE1_HANDOFF_FORMAT  # 交接格式是契约, 不随调用点而变
    assert "gaia_dr3_18.ra" in form["showcol"]  # 列名必须已改写成规范表名
    assert not any(col.startswith("gaia_dr3.") for col in form["showcol"])  # 旧前缀一列都不剩


def test_phase_one_defaults_to_the_format_that_returns_an_sqlid():
    """Phase 1 默认格式必须选那个能拿回 sqlid 的格式 (Phase 1 交接契约)。

    /q 上 ``output.fmt=csv`` 只内联流式返回行, 永远不产出 sqlid, 后续
    分页/续传全部无从谈起; ``fits`` 从未被该端点支持, 放进支持列表即误导。
    """
    assert build_query_form("ps1")["output.fmt"] == "html"  # html 才产出 sqlid, 后续分页才有对象
    assert "fits" not in SUPPORTED_OUTPUT_FORMATS  # 端点从未支持: 写进支持列表即误导用户


def test_xp_catalog_showcol_spans_their_form_tables():
    """XP 交叉星表的 showcol 必须横跨各自全部表单表 (2026-09-29 线上核验)。

    xpsp: 139 张表 (Gaia 测光/位置共享表 + 138 张调查测光表, 只登记共享表的话
    276 个调查测光列全部 fail-closed 不可请求); dr3xpcorr: 2 张
    (gaiaxp_photinfo_replenish + correctedxpspecv1)。少登记一张表, 该表字段
    就在结果里静默缺失, 因此两个星表的表集都必须钉住。
    """
    form = build_query_form("dr3xpcorr")                                                            # 无空间参数的构造: 只验列投影与默认字段
    assert "gaiaxp_photinfo_replenish.ra" in form["showcol"]  # 测光共享表
    assert "correctedxpspecv1.flux" in form["showcol"]  # 校正光谱表
    xpsp_tables = catalog_tables("xpsp")                                                            # 取交叉匹配的表清单
    assert len(xpsp_tables) == 139  # 139 = 1 共享 + 138 调查表, 少一张即静默缺列
    assert "gaiaxp_photinfo_replenish" in xpsp_tables                                           # 目标表必须在清单里: 少一表就是匹配能力静默缺失
    assert "ps1_g" in xpsp_tables  # 调查测光表 (ps1_g.g_xpsp 形态)
    # 长表名优先: jpas_ujava 必须先于 jpas_u 剥离, 防前缀误剥
    assert xpsp_tables.index("jpas_ujava") < xpsp_tables.index("jpas_u")  # 剥离次序是唯一不变量


def test_qualified_columns_are_allowlisted_per_catalog_table():
    """列名必须走 per-catalog 白名单, 非法字符与跨表引用一律拒绝。

    ``evil.col`` 不得靠「含点即视为已限定」绕过校验, 否则等于把任意
    字符串塞进 SQL —— 两个方向 (未登记表名/未登记列名) 都必须抛错。
    """
    assert qualify_column("dr3xpcorr", "correctedxpspecv1.flux") == "correctedxpspecv1.flux"  # 已登记则原样返回
    with pytest.raises(ValueError):  # 表名未登记: 「含点即视为已限定」不得绕过校验
        qualify_column("ps1", "evil.col")                                                           # 非法列名必须被拒: 带点的列名是注入形态
    with pytest.raises(ValueError):  # 列名未登记: 另一个方向同样必须 fail-closed
        qualify_column("dr3xpcorr", "evil.flux")                                               # 另一张表的同一类非法列名: 判据不能只对一张表生效


def test_getcount_wants_the_numeric_half_of_the_sqlid():
    """getcount 端点只接受 sqlid 的数字部分 (``s3839`` -> ``3839``)。"""
    assert count_sqlid("s3839") == "3839"  # 端点只收数字部分
    assert count_sqlid("3839") == "3839"  # 已归一的值不得被二次加工


def test_rectangle_and_proximity_positions_use_the_real_form_fields():
    """三种位置输入 (矩形/多目标邻近/圆锥) 必须落在服务端真实表单字段上。

    字段名写错服务端会按默认值解释, 查询「成功」但范围全错 — 因此逐个断言
    pos.type 与对应字段; 最后两条断言互斥的位置参数必须被入口校验拒绝。
    """
    rect = build_query_form("ps1", box=(10.0, 20.0, -5.0, 5.0))                                     # 矩形选区: 与锥形、邻近三选一
    assert rect["pos.type"] == "rect"  # 字段名写错: 服务端按默认值解释, 查询"成功"但范围全错
    assert rect["pos.ramin"] == "10.0" and rect["pos.decmax"] == "5.0"  # 上下界不能被对调

    prox = build_query_form("ps1", radec_text="187.7059 12.3692\n30.0 40.0")                        # 邻近文本: 多行坐标的逐行解析
    assert prox["pos.type"] == "proximity"                                                          # 必须落成 proximity 形态
    assert prox["pos.radecTextarea"].count("\n") == 1  # 恰好一个换行 = 两条目标

    cone = build_query_form("ps1", ra=1.0, dec=2.0, radius_arcsec=30)                              # 锥形构造: 与前两条构成三种空间选择的对照
    assert cone["pos.type"] == "cone" and cone["pos.radius"] == "30"  # 半径归一成字符串

    # 互斥位置参数同时给出时必须 fail-closed, 不允许悄悄挑一个用。
    with pytest.raises(ValueError):                                                          # 同时给矩形与锥形必须报错: 两种空间选择混用结果无意义
        build_query_form("ps1", box=(1.0, 2.0, 3.0, 4.0), ra=1.0, dec=2.0, radius_arcsec=5)         # 冲突形态要抛错, 而不是按某一种悄悄生效
    with pytest.raises(ValueError):                                                                 # 另一组冲突参数
        build_query_form("ps1", radec_text="1 2", box=(1.0, 2.0, 3.0, 4.0))
