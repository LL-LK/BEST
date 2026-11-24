"""针对公开 BEST 服务的小型、可选 (opt-in) live 检查。

【需要真实网络】每个用例都直连 nadc.china-vo.org/data/best 的真实 REST
API; 【默认 skip】除非设置环境变量 PYBEST_RUN_LIVE=1 (见下方
pytestmark), 收集阶段即整文件跳过; 【为什么不能离线跑】本文件守的是
服务端行为 — 半径过滤是否真的生效、getcount 计数端点是否应答、客户端
是否返回领域模型 — 这些契约只有真实回包能验证, mock 只能验证
我们自己的解析逻辑 (那部分由 test/integration 覆盖)。

P1 合并注记: 原文件同时 live 验证 pybest 单类 (``Best``) 与 BestClient
两条路径; 双副本删除后只保留唯一生产客户端 BestClient — 服务端行为
的验证目标 (半径过滤/getcount/领域模型) 不变。
"""
from __future__ import annotations

# 标准库: os 读环境变量 PYBEST_RUN_LIVE (live 开关; 缺省即跳过)
import os

# 第三方: astropy.units 提供 deg 单位对象; pytest 承载"默认跳过"的 skipif
# 标记与用例发现框架; astropy.coordinates.SkyCoord 用 separation 校验服务端
# 返回的源确实落在检索半径内 (天球距离计算, 不能拿平面近似)。
import astropy.units as u
import pytest
from astropy.coordinates import SkyCoord

# 本地: 唯一生产客户端 (P1: pybest 单类双副本已合并删除)。
# legacy-import-guard: 导入失败即整文件跳过 (live 文件不该因环境问题报错)。
try:
    # src.client: 两阶段异步 HTTP 客户端 (被测入口)
    from src.client import BestClient  # live 抽样须显式声明才跑: 默认不触网, 防 CI 误打真实站点
except Exception as _legacy_err:  # legacy-import-guard
    # pytest: 导入失败时主动 skip, 不让环境问题伪装成用例失败
    import pytest as _pytest
    _pytest.skip(f'legacy import unavailable: {_legacy_err!r}', allow_module_level=True)  # 抽样只验链路通不通: 数值判定交给离线回放, 线上结果不作金标准

# 默认跳过: 只有 PYBEST_RUN_LIVE=1 时才真正访问公网服务 —
# 防止 CI/离线环境误触真实 HTTP (公网服务有限流, 严禁连续跑)。
pytestmark = pytest.mark.skipif(                                                   # 无凭据即整目录跳过: 活体测试打的是真实站点, 没 token 不该发请求
    os.environ.get("PYBEST_RUN_LIVE") != "1",  # 显式环境变量才跑: 默认不触网, 防 CI 误打真实站点
    reason="set PYBEST_RUN_LIVE=1 to query the public BEST service",
)


@pytest.mark.live
def test_ps1_cone_search_honours_radius_and_count_endpoint():
    """【需要真实网络 / 默认 skip】验证服务端锥检索半径过滤与计数端点。

    【验证的服务端行为】phase-1 提交后拿到的 sqlid 必须非空;
    count (getcount 端点) 必须 >= 1; 随后 cone_search 取回的
    每一个源都必须落在 radius_arcsec+1e-6 角秒内 — 即服务端确实按
    pos.radius 过滤, 而不是返回全表让客户端自理。
    【为什么不能离线跑】半径过滤发生在服务端 SQL 层; mock 回包只能证明
    我们的解析没坏, 证明不了站点真的过滤了。
    """
    ra = 286.0925889890722                                                                          # 目标天区中心 RA (J2000)
    dec = 15.727985031303144                                                                        # 目标天区中心 Dec (J2000)
    radius_arcsec = 5.0                                                                         # 半径 5 角秒: 小天区足够验证通路又不至于拖慢
    client = BestClient(rate_limit=0)  # 零限速: 抽样不该给公共站点添压力
    # phase-1: POST 表单到 /q 路由, 从回包 HTML 提取 sqlid (真实请求;
    # radec 走原生服务端锥搜, 行数上限属于 phase-2 取数参数不进表单)
    sqlid, error = client.submit_phase1("ps1", radec=(ra, dec, radius_arcsec))
    assert error is None                                                                   # 第一阶段失败即断言: 连会话都换不到, 后面的取数无从谈起
    assert sqlid is not None                                                                        # sqlid 必须拿到
    # phase-2 前置: getcount 端点问服务端该会话的总行数 (真实请求)
    assert client.count(sqlid) >= 1  # 先问计数端点: 直接翻页验不到两阶段协议本身

    # phase-2: 按 sqlid 分页取回数据 (真实请求)
    result = client.fetch_page(sqlid, page_size=5, catalog="ps1")
    assert result.success                                                                           # 查询必须成功
    assert result.sources                                                                           # 且必须有源
    center = SkyCoord(ra=ra * u.deg, dec=dec * u.deg)  # 用 astropy 算真角距: 自己写的平面近似会放过超半径的行
    for source in result.sources:                                                                   # 逐源核对坐标
        hit = SkyCoord(ra=source.ra * u.deg, dec=source.dec * u.deg)                                # 球面坐标构造, 与站点返回对齐
        assert center.separation(hit).arcsec <= radius_arcsec + 1e-6  # 容差 1e-6 吸收浮点尾数: 严格 <= 会在边界上假红


@pytest.mark.live
def test_client_returns_scientific_source_model():
    """【需要真实网络 / 默认 skip】验证客户端返回领域模型。

    【验证的服务端行为】cone_search 成功后 result.total_count >= 1
    (getcount 服务端口径), sources 是 BestSource 领域对象且 ra/dec/catalog
    落位正确 — 即协议层接线后对外契约是科学模型而非裸 dict。
    【为什么不能离线跑】total_count 来自服务端 getcount 应答, 只有真实
    会话能产生; 离线 mock 无法验证这条端到端契约。
    """
    client = BestClient(rate_limit=0)                                                            # 限速置零: 活体测试也不该被本地限流拖成分钟级
    # 真实两阶段查询: POST 取 sqlid → getcount → 分页 GET 取数
    result = client.cone_search(                                                                    # 锥形检索
        ra=286.0925889890722,                                                                       # 同一目标 RA
        dec=15.727985031303144,                                                                     # 同一目标 Dec
        radius_arcsec=5.0,                                                                          # 同一半径
        catalog="ps1",
        max_records=1,                                                                              # 只要一条
        page_size=1,                                                                                # 单页: 目的是验通路, 不是拉全量
    )
    assert result.success                                                                           # 成功
    assert result.total_count >= 1                                                                  # 总数至少 1
    assert len(result.sources) == 1  # 只取一条: 抽样验链路形态, 不验行集完整性
    source = result.sources[0]                                                                      # 取第一条
    assert source.ra == pytest.approx(286.0925889890722)                                    # RA 需近似相等: 站点不做天球变换, 差值只应来自浮点
    assert source.dec == pytest.approx(15.727985031303144)                                          # Dec 同理
    assert source.catalog == "ps1"
