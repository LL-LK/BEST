# -*- coding: utf-8 -*-
"""针对公开 BEST 服务的可选 (opt-in) live 冒烟测试。

【需要真实网络 / 默认 skip】运行方式:
    $env:PYBEST_RUN_LIVE='1'
    python -m pytest test/live -q

这些用例有意不进常规离线套件: 公网服务有限流, 因此默认冒烟坐标与行数
上限都保持很小, 且不要连续运行。未设置 PYBEST_RUN_LIVE 时整文件在收集阶段
跳过, 离线环境零网络触碰。

2026-10-02: 开关名由 ``BEST_LIVE`` 并入 ``PYBEST_RUN_LIVE`` (与同目录另两个
live 文件统一)。此前三文件用两个不同开关, 只设 ``PYBEST_RUN_LIVE`` 时本文件
会整份静默 skip, 而报告上看"live 跑过了" —— 一个开关必须能开全部 live 面。

P1 合并注记: 原经 pybest 单类 (``Best``) 驱动; 双副本删除后改用唯一生产
客户端 ``BestClient`` + ``BestDownloader`` — 断言从"裸行字典"相应改为
信封/源模型形态 (行为验证目标不变)。

抽样须显式声明: 任何 live 结论只能来自显式开启 (``PYBEST_RUN_LIVE=1``)
的那一次运行; 未声明的运行不产出 live 结论, 报告上也不得记成"live 跑过了"。
本文件因此只做存在性冒烟, 不承担服务端可用性结论。
"""
from __future__ import annotations

# 标准库: os 读环境变量 PYBEST_RUN_LIVE (live 开关; 缺省即跳过)
import os  # 唯一开关来源: 缺省即整份文件在收集阶段跳过, 离线零网络触碰

# 第三方: pytest 提供夹具/参数化/跳过机制
import pytest  # live 标记/参数化/skipif 三个机制都由它提供

# 本地: 唯一生产客户端 + 认证处理器 + 下载器 + 星表注册表 — live 面覆盖
# 查询、下载与登录失败语义
from src.auth.session import BestAuth
from src.client import BestClient
from src.downloader import BestDownloader
from src.protocol import CATALOG_DISPLAY

# 双重守卫: live 标记 (可按 -m "not live" 排除) + 开关未设置即跳过;
# 公网服务有限流, 默认绝不发起真实请求。
pytestmark = [                                                                              # live 标记: 收集时按此标记跳过, 绝不混进常规跑批
    pytest.mark.live,                                                                               # 同上
    pytest.mark.skipif(not os.getenv("PYBEST_RUN_LIVE"),
                       reason="set PYBEST_RUN_LIVE=1 to run real BEST API smoke"),
]

# 冒烟坐标 (默认天区): 与其余 live 文件保持一致的小半径/少行数配置,
# 既省服务端配额又足够触发各星表的返回路径。
RA = 180.0  # 天区中心赤经 (度): 固定值, 让多次 live 结果可直接对照
DEC = 30.0                                                                                          # 目标 Dec
RADIUS_ARCSEC = 60.0  # 1 角分: 密度足够高的星表也能命中若干源, 又不拉大返回体


@pytest.fixture(scope="module")
def best() -> BestClient:
    """模块级共享 BestClient (rate_limit=0.4 尊重公网限流; 用完 close)。"""
    client = BestClient(rate_limit=0.4)                                                        # 活体测试要限速: 打真实站点, 不能像回放那样置零
    yield client
    client.close()                                                                                  # 显式关闭会话: 不留连接池在进程里


def test_live_info_connected(best: BestClient) -> None:
    """【需要真实网络 / 默认 skip】连通性探测必须为真且星表数达下限。

    【验证的服务端行为】check_connection 为 True; CATALOG_DISPLAY 登记数
    >= 12 且含 ps1 — 星表数量允许增长, 故只钉文档下限而非精确相等
    (防脆弱等值断言)。
    【为什么不能离线跑】连通性取决于服务端应答, mock 无法验证。
    """
    assert best.check_connection() is True  # 挡住"探测恒真"的空转实现
    # 星表数允许增长; 断言文档下限而非脆弱等值
    assert len(CATALOG_DISPLAY) >= 12                                                           # 星表数量是硬指标: 少于 12 说明登记表被裁了
    assert "ps1" in CATALOG_DISPLAY  # 挡住主星表缺席: live 查询主线全靠它


# 只列 live /q 路由真实接受的 id。``gaia_dr3`` 作为旧别名探针保留;
# ``std`` 缺席因为它导航组而非表 — 直送会被服务端以 {"error":"Not Found"}
# 拒绝 (软 404)。
@pytest.mark.parametrize(
    "catalog",                                                                                      # 参数名 (逐 catalog 参数化)
    ["ps1", "stripe82", "gaia_dr3", "gaia_dr3_18", "scr_lamost", "xpsp", "dr3xpcorr"],
)
def test_live_catalog_cone_search_returns_sources(best: BestClient, catalog: str) -> None:
    """【需要真实网络 / 默认 skip】每个可查询星表锥检索必须返回成功信封。

    【验证的服务端行为】对 7 个星表 id (含旧别名 gaia_dr3) 各发一次真实
    锥检索, 信封必须 success — 即路由表把每个 id 都送到了服务端真实
    路径, 没有把旧别名漏成软 404。
    【为什么不能离线跑】路由是否正确只有服务端应答能证明。
    """
    result = best.cone_search(  # 每个 id 各真发一次: 路由漏接只会在这里露成软 404
        ra=RA,                                                                                      # 用模块级常量, 各用例一致
        dec=DEC,                                                                                    # 同上
        radius_arcsec=RADIUS_ARCSEC,                                                                # 同上
        catalog=catalog,                                                                            # 逐张星表
        max_records=3,                                                                              # 只要三条
    )
    assert result.success is True  # 断言的是信封成功位, 而非"没抛异常"


def test_live_ps1_cone_returns_sources(best: BestClient) -> None:
    """【需要真实网络 / 默认 skip】ps1 默认天区必须取回带坐标列的源。

    【验证的服务端行为】sources[0] 的原始投影含 ps1_ra/ps1_dec 列 — 即
    列投影与解析在真实回包上成立 (带表前缀的原始投影)。
    【为什么不能离线跑】列名形态来自服务端 CSV 表头, 离线无法验证。
    """
    result = best.cone_search(  # 单表真检: 目的只验回包列名形态, 不统计天体数
        ra=RA,                                                                                      # cone_search 形态
        dec=DEC,                                                                                    # 同上
        radius_arcsec=RADIUS_ARCSEC,                                                                # 同上
        catalog="ps1",
        max_records=3,                                                                              # 三条足够验通路
    )
    assert result.success is True                                                                   # 成功
    assert len(result.sources) >= 1                                                                 # 且非空
    assert "ps1_ra" in result.sources[0].raw_data  # 原始投影带表前缀: 解析器不得自造列名
    assert "ps1_dec" in result.sources[0].raw_data  # 缺任一坐标列, 上层就无法定位源


# 服务端实际供的格式: csv/json/txt/votable。``fits`` 被有意排除 —
# 该端点返回 HTML 结果页而非 FITS 文档 (实测形态)。
@pytest.mark.parametrize("fmt", ["csv", "json", "txt", "votable"])
def test_live_download_formats(best: BestClient, tmp_path, fmt: str) -> None:
    """【需要真实网络 / 默认 skip】四种格式真实下载必须落盘非空文件。

    【验证的服务端行为】服务端实际供的格式是 csv/json/txt/votable; 每种
    都必须产出 size>0 的文件。``fits`` 被有意排除: 该端点返回 HTML 结果
    页而非 FITS 文档 (实测形态, 见注释)。
    【为什么不能离线跑】服务端支持哪些 emitter 只有真实应答能证明。
    """
    dl = BestDownloader(best, str(tmp_path))  # 落 pytest 临时目录, 不污染工作树
    path = dl.download_region(  # 每种 emitter 真下一次: 服务端供哪些格式只有它能证明
        ra_center=RA,                                                                               # 天区下载形态
        dec_center=DEC,                                                                             # 同上
        radius_arcsec=RADIUS_ARCSEC,                                                                # 同上
        catalog="ps1",
        output_format=fmt,                                                                          # 逐格式验证落盘
        output_file=f"live.{fmt}",
        max_rows=2,                                                                                 # 只要两行
    )
    assert path is not None  # 失败语义是 None 而非抛异常, 调用方按此判失败
    assert tmp_path.joinpath(f"live.{fmt}").stat().st_size > 0  # 挡住"0 字节也算下载成功"


def test_live_sqlid_roundtrip(best: BestClient) -> None:
    """【需要真实网络 / 默认 skip】sqlid 全链路往返 (submit→count→fetch)。

    【验证的服务端行为】submit_phase1 产的表单能被服务端接受并换回
    sqlid; getcount >= 1; fetch_page 行含 ps1_ra — 两阶段协议在真实
    服务上的完整闭环。
    【为什么不能离线跑】三个调用全部触网, 且验证的是服务端会话状态机。
    """
    # phase-1: POST 表单取 sqlid (真实请求; radec 走原生服务端锥搜)
    sqlid, error = best.submit_phase1("ps1", radec=(RA, DEC, RADIUS_ARCSEC))  # 失败走 error 返回, 不抛
    assert error is None  # 第一阶段就失败时, 后面两步必然假绿
    assert sqlid is not None  # 挡住"服务端回空会话 id 仍继续往下走"
    # getcount: 服务端会话总数 (真实请求)
    assert best.count(sqlid) >= 1  # 挡住会话建了却查不到行 (协议走空的典型形态)
    # phase-2: 按 sqlid 取数 (真实请求)
    result = best.fetch_page(sqlid, page_size=2, catalog="ps1")  # 单页 2 行: 够验列投影又不触配额
    assert result.success is True                                                              # 下载后查询必须成功: 验的是"落盘数据可被再读回"
    assert len(result.sources) >= 1  # 挡住翻页解析把行整页丢掉
    assert "ps1_ra" in result.sources[0].raw_data  # 坐标列缺失, 结果就无法回投查询


def test_live_auth_failure_is_false() -> None:
    """【需要真实网络 / 默认 skip】错误凭据登录必须返回 False (不抛异常)。

    【验证的服务端行为】用刻意构造的不存在用户 + 错密码走真实登录协议
    (GET 登录页取 CSRF → POST 凭据), 服务端拒绝后 login 返回 False —
    即认证判定不看状态码而看最终 URL 是否仍在 login 页。
    【为什么不能离线跑】登录协议的 CSRF/重定向行为是服务端实现的,
    mock 只能复述我们自己的假设。
    """
    auth = BestAuth()  # 走真实 CSRF 取页 + POST 凭据, 不带任何缓存会话
    assert auth.login("__pybest_live_no_such_user__", "bad-password") is False  # 失败须是 False: 认证判定看最终 URL 而非状态码
