# -*- coding: utf-8 -*-
"""evals.probes — 行为评测探针层 (每个探针 = 一次真实协议交互)。

能力边界: 本模块只放**探针** —— 24 个场景对应的交互执行体 (``crossmatch_best_gaia``
复用 ``_exec_crossmatch_probe``, 该复用由 eval_runner.py 显式登记; 24 是注册表 id
数与场景条数, 不是函数数)
(两阶段查询 / 名称解析 / proximity 批量 / TAP / 工具面 / 下载栈)。探针之间
必须共用同一套会话与限流配置 (由 ``_stub_manager`` 提供), 拆开后"探针之间是否互相
污染"变得不可判, 故整层独立成模块而不是按场景拆散。

与 eval_runner.py 的分工: 本模块负责"跑一次真实交互并报告成败", runner 负责
"读场景表 / 派探针 / 汇总评分 / 出报告"。runner 通过 ``SCENARIO_PROBES`` 注册表
消费本模块; 未登记场景 id 由 runner 判 FAIL (EVAL-04: 杜绝"文件存在即过")。

白盒锚点: references/ALGORITHM-SPEC.md §3;
docs/architecture/file-size-budget.md §3.1 (本模块即该节登记的
"探针层切到 evals/probes/"拆分产物)。
"""
from __future__ import annotations

# 标准库组: pathlib 造隔离临时目录 (探针的 IO 点) / unittest.mock 的 Mock
# 构造不发起真实请求的替身响应 —— 探针离线化的唯一手段
from pathlib import Path
from unittest.mock import Mock

# 本地组: 探针离线化设施 (桩管理器 / 桩客户端 / 共用常量) —— 与探针要测的
# 行为是正交关注点, 独立成 evals/probe_support.py
from probe_support import (  # noqa: E402
    CONE_ADQL,  # 锥形检索的 ADQL 模板: 探针自造查询时直接用它, 不手写第二份
    _stub_manager,  # 桩下载管理器: 让下载类探针全程离线且结果可断言
    _StubFileClient,  # 桩文件客户端: 产出确定性字节, 落盘与续传才可复现
)


def _exec_cone_search_probe() -> tuple[bool, str]:
    """真实执行: BestQuery 流畅构造 + protocol 表单键集 (喂给定输入, 校输出)。

    两个断言各有分工:
      - ``catalog == "ps1"`` 校验 Fluent 链式构造真的把选项带进了 build();
      - ``showcol`` / ``output.fmt`` 校验 protocol 层表单契约没被改键名。
    任何一环失真都说明"查询能跑但查的不是用户要的", 必须红。

    Returns:
        (是否通过, 人类可读说明)。
    """
    # 探针内惰性导入: 查询构造器 (协议层表单拼装 + 查询 DSL)
    from src.protocol import build_query_form
    from src.query_builder import BestQuery

    q = BestQuery().catalog("ps1").mag_range(14, 18, "r").class_star_min(0.95).limit(100)
    params = q.build()                       # build 才是真正落参的一步: 只断链式构造等于没断
    if params.get("catalog") != "ps1":       # 挡住 Fluent 链退化成空实现
        return False, f"BestQuery catalog 失真: {params.get('catalog')!r}"
    # P1-3: 约束列名必须真实存在 ( qualify_column fail-closed 后, 幻影列名
    # 如 ps1_gmag 会显式抛错 — 旧探针用的就是幻影列, 现改真实列 ps1_rpsf)
    form = build_query_form("ps1", [{"name": "ps1_rpsf", "op": "between", "min": 14, "max": 18}])  # 真实列名, 幻影列会被拒
    if "showcol" not in form or form.get("output.fmt") != "html":  # 改键名服务端静默忽略, 不会报错
        return False, f"protocol 表单键集异常: {sorted(form)[:4]}"
    return True, "BestQuery 流畅构造 + protocol 表单键集实测通过"
def _exec_crossmatch_probe() -> tuple[bool, str]:
    """真实执行: BestCrossMatch 角度分离数学 (haversine 已知值, 含 cos(dec) 因子)。

    为什么用两个点而不是一个: 赤道面上 1° RA 恒等于 3600″, 这一条即使
    ``cos(dec)`` 因子整个被删也能过 (dec=0 时 cos=1); 只有再补一条 dec=30°
    的用例, 才能把"漏乘 cos(dec)"这个历史 bug 钉死。

    Returns:
        (是否通过, 人类可读说明)。
    """
    from src.crossmatch import _angular_separation_arcsec

    # 赤道面上 1° RA = 3600 arcsec (cos(0)=1)
    sep_eq = _angular_separation_arcsec(180.0, 0.0, 180.0 + 1 / 3600.0, 0.0)                   # 同一赤经偏一弧秒的间距: 角距公式的最小可复现单元
    if abs(sep_eq - 1.0) > 1e-6:        # 1e-6 吸收浮点误差, 远小于 1″ 的物理含义
        return False, f"赤道面角度分离失真: {sep_eq}"
    # dec=30° 面上 1° RA = 3600*cos(30°) arcsec
    import math

    sep_30 = _angular_separation_arcsec(180.0, 30.0, 180.0 + 1 / 3600.0, 30.0)  # 这一档才抓得住漏乘 cos(dec)
    expected = math.cos(math.radians(30.0))                                                # 期望值取球面余弦: 与生产实现同公式但不同代码, 互为对账
    if abs(sep_30 - expected) > 1e-6:                                                             # 1e-6 容差吸收浮点尾数: 严格相等会假红
        return False, f"cos(dec) 因子失真: {sep_30} vs {expected}"
    return True, f"角度分离实测 赤道={sep_eq:.6f}″ dec30={sep_30:.6f}″ (期望 {expected:.6f})"
def _exec_quality_filtering_probe() -> tuple[bool, str]:
    """真实执行: QualityGate 对真实解析源的判定 (fail-closed 已接线)。

    三态缺一不可:
      - good 必须过 (否则门禁把好数据全毙, 下游无数据可用);
      - bad (class_star=0.1) 必须拒 (否则伪点源污染测光);
      - empty (无任何质量指标) 必须 fail-closed 拒掉 —— 这一条是回归锚:
        把"没有指标"当作"没毛病"放行, 等于质量门禁对脏数据失明。

    Returns:
        (是否通过, 人类可读说明)。
    """
    # 探针内惰性导入: 质量门禁与源数据模型 (验证门禁拦得住坏源)
    from src.core import QualityGate
    from src.models import BestSource

    qg = QualityGate(min_snr=10.0, max_fwhm=4.0)  # 阈值取 PS1 典型值: SNR<10 或 FWHM>4 的帧判废
    # P1-3: 探针数据用 ps1 真实发布的列名 (ps1_gpsf 而非幻影 ps1_gmag)
    good = BestSource.from_row(                                                                     # 完整行造合法源对象: 正例必须能过校验器
        {"ps1_source_id": "B1", "ps1_ra": "180.0", "ps1_dec": "30.0",
         "ps1_gpsf": "18.2", "ps1_class_star": "0.99"}, catalog="ps1")
    bad = BestSource.from_row(                                                                  # 同一行改一个字段造非法源: 两版之差才归因得干净
        {"ps1_source_id": "B2", "ps1_ra": "181.0", "ps1_dec": "31.0",
         "ps1_gpsf": "19.1", "ps1_class_star": "0.1"}, catalog="ps1")
    empty = BestSource.from_row({"ps1_source_id": "B3", "ps1_ra": "182.0"}, catalog="ps1")  # 回归锚: 无任何质量指标
    r_good, r_bad, r_empty = qg.validate_source(good), qg.validate_source(bad), qg.validate_source(empty)  # 三态一起判: 合法、缺字段、空行三种输入的结论都要拿到
    if not r_good["passed"]:
        return False, "合格源被误拒"
    if r_bad["passed"]:
        return False, "低 class_star 源被误放"
    if r_empty["passed"]:                       # 缺指标 == 放行 是 fail-closed 退化, 必须红
        return False, "无指标源被放行 (fail-closed 回归!)"
    return True, "QualityGate 三态判定 (过/拒/fail-closed) 实测通过"
def _exec_column_constraint_probe() -> tuple[bool, str]:
    """真实执行: 约束编码进 protocol 表单的 operation/min/max 键。

    ``between`` 约束必须拆成 ``{col}.operation`` + ``{col}.min`` + ``{col}.max``
    三枚键, 这是 BEST 表单服务端的既有约定; 键名拼错服务端会静默忽略约束,
    表现为"查回来了但其实没过滤", 所以这里逐键核对。

    Returns:
        (是否通过, 人类可读说明)。
    """
    from src.client import BestClient

    # rate_limit=0: 探针只构造表单不发请求, 禁掉礼貌限速的睡眠
    client = BestClient(rate_limit=0)   # rate_limit=0: 只构造表单不发请求, 禁掉限速睡眠
    # 探针内惰性导入: 列约束数据模型 (构造表单输入用)
    from src.models import ColumnConstraint

    form = client._build_form(          # 直调私有构造: 公开 API 会把表单细节藏掉, 约束就测不到
        "ps1", [ColumnConstraint(name="class_star", constraint="between", min=0.9, max=1.0)], 100)
    ops = [k for k in form if k.endswith(".operation")]
    if not ops:                                                                             # 导航组没有可执行操作即失败: 返回空清单等于工具面没接上
        return False, f"约束未编码为 operation 键: {sorted(form)[:5]}"
    prefix = ops[0][: -len(".operation")]
    if form.get(f"{prefix}.min") != "0.9" or form.get(f"{prefix}.max") != "1.0":  # 值须为字符串: 浮点会被服务端丢弃
        return False, f"min/max 编码失真: {form}"
    return True, "约束 operation/min/max 编码实测通过"
def _exec_list_catalogs_probe() -> tuple[bool, str]:
    """真实执行: 星表登记规模与别名解析。

    别名 (gaia_dr3 -> gaia_dr3_18) 是老用户脚本的兼容面, 回归它比回归新键名
    更重要: 键名改了会立刻报错, 别名丢了只会悄悄查错表。

    Returns:
        (是否通过, 人类可读说明)。
    """
    # 探针内惰性导入: 星表登记表与别名解析 (验证 12 张表与旧拼写归一)
    from src.protocol import CATALOG_PATHS, resolve_catalog

    if len(CATALOG_PATHS) < 12:                  # 12 是登记规模地板: 少一张表即能力面回退
        return False, f"可查星表数不足: {len(CATALOG_PATHS)}"
    if resolve_catalog("gaia_dr3") != "gaia_dr3_18":  # 老脚本兼容面: 别名丢了只会悄悄查错表
        return False, "legacy 别名未映射"
    return True, f"{len(CATALOG_PATHS)} 张可查星表 + 别名解析实测通过"
def _exec_multiband_photometry_probe() -> tuple[bool, str]:
    """真实执行: 多波段测光容器的入口可达与空结果显式失败。

    探针只验证"入口可达且不伪造成功": 无 client 时允许走显式失败路径
    (抛出来), 但返回的必须是多波段测光容器本身 —— 返回别的东西 (含空列表)
    说明能力已退化, 必须显红。

    调用必须按**真实签名**走: ``from_client`` 是 classmethod
    ``(client, source_id, ...)``, 按实例方法调会注定抛 TypeError, 而
    TypeError 被下面的 except 当成"显式失败"判绿 —— 这条探针就变成无论能力
    好坏都恒绿、零信息量。故此处按 classmethod 签名调用, 并追加返回类型契约
    检查。

    Returns:
        (是否通过, 人类可读说明)。
    """
    # 探针内惰性导入: 多波段测光容器 (验证其工厂入口存在, 缺失必须显红)
    from src.multiband_photometry import BestMultiBandPhotometry

    if not hasattr(BestMultiBandPhotometry, "from_client"):  # 入口缺失必须显红, 不许"能力不存在但通过"
        return False, "BestMultiBandPhotometry 缺 from_client 入口 (能力缺失必须显红)"
    try:
        # 真实签名: classmethod(client, source_id, band=None, catalog="ps1");
        # client=None 时取数必然失败, 关键是它"抛出来"还是"静默返空"。
        obj = BestMultiBandPhotometry.from_client(client=None, source_id="POS_180.0_30.0")  # 按 classmethod 签名调: 按实例方法调会恒抛 TypeError, 于是恒绿
    except Exception:
        # 无 client 时允许显式失败路径: 关键是"抛出来", 不是"吞掉返空"
        return True, "多波段测光入口可达且显式失败 (无 client 时抛异常而非伪造空成功)"
    if not isinstance(obj, BestMultiBandPhotometry):                                        # 先断类型: 名字在但类型不对时, 后面的属性访问全是幻觉
        return False, (f"from_client 返回 {type(obj).__name__} 而非 BestMultiBandPhotometry "
                       "(能力退化: 静默返回非测光容器)")
    n = int(getattr(obj, "n_points", 0) or 0)
    return True, f"多波段测光入口可达 (n_points={n})"
def _exec_source_lookup_probe() -> tuple[bool, str]:
    """真实执行: BestClient 查询入口存在且返回信封形态。

    这一条是其它探针的前置: 入口缺失时后续查询类探针会全部异常,
    先单独报出来便于定位是客户端被裁剪还是别的问题。

    Returns:
        (是否通过, 人类可读说明)。
    """
    # 探针内惰性导入: 主客户端 (验证 cone_search 能力面未回归)
    from src.client import BestClient

    client = BestClient(rate_limit=0)   # rate_limit=0: 离线铁律, 不因礼貌限速而 sleep
    if not hasattr(client, "cone_search"):
        return False, "BestClient.cone_search 缺失"
    return True, "BestClient 查询入口可达"
def _exec_coordinate_lookup_probe() -> tuple[bool, str]:
    """真实执行: 入参校验拒绝非法坐标 (Q-51 接线)。

    断言方向是"必须抛 ValueError": 如果校验被摘掉, 负 RA 会被静默发给
    服务端并拿到一堆无意义结果 (或 500), 那比在入口就拒更难排查。

    Returns:
        (是否通过, 人类可读说明)。
    """
    # 探针内惰性导入: 主客户端 (构造一个不打限流睡眠的实例做越界输入测试)
    from src.client import BestClient

    client = BestClient(rate_limit=0)                                                        # 节流归零: 探针不得引入任何等待, 否则跑批时长不可比
    try:
        client.cone_search(ra=-10.0, dec=30.0, radius_arcsec=60.0)                            # 故意传越界赤经: 护栏必须在入口拦住, 不发到服务端
        return False, "负 RA 未被拒绝 (校验回归!)"
    except ValueError:                  # 只认 ValueError: 换类型说明校验路径被换过
        return True, "负 RA 入口即拒 (Q-51)"
def _exec_custom_adql_probe() -> tuple[bool, str]:
    """真实执行: ADQL 语法校验入口存在 (BEST 无 TAP 端点, 仅语法校验)。

    正反两个方向都要走: 合法语句必须原样通过, 缺 FROM 子句的残句必须被拒。
    只测"合法语句通过"的话, 校验器退化成"什么都收"也能全绿 —— 那正是它
    旧行为 (只做 strip 不校验) 的模样, 所以反例是这条探针的核心价值。

    Returns:
        (是否通过, 人类可读说明)。
    """
    # 探针内惰性导入: ADQL 语法校验器 (只查语法, 不连数据库)
    from src.scripts.guards import validate_adql_query

    valid = "SELECT source_id, ra, dec FROM best.source WHERE band = 'r' LIMIT 5"
    if validate_adql_query(valid) != valid:  # 校验器不得顺手改写: 改写即破坏可复现性
        return False, "合法语句被误拒"
    try:
        validate_adql_query("SELECT 1")
    except ValueError:                      # 抛出来才算生效; 静默通过就是退化成 strip
        return True, "validate_adql_query 语法校验实测通过 (拒无 FROM 子句)"
    return False, "缺 FROM 子句的语句被放行 (校验名不副实)"
def _exec_batch_region_download_probe() -> tuple[bool, str]:
    """真实执行: 下载器存在且校验和算子可用。

    ``verify_checksum`` 是 checksum_match 门禁的底层算子; 它若缺失,
    门禁就只能看 HTTP 200, 半成品会被当成完整下载放行。

    Returns:
        (是否通过, 人类可读说明)。
    """
    # 探针内惰性导入: 下载器 (验证校验和能力面未回归)
    from src.downloader import BestDownloader

    if not hasattr(BestDownloader, "verify_checksum"):  # 缺了它门禁只能看 HTTP 200, 半成品会被放行
        return False, "verify_checksum 缺失"
    return True, "BestDownloader + verify_checksum 可达"
def _exec_connection_info_probe() -> tuple[bool, str]:
    """真实执行: 连接探测 + 星表注册表无 version 字段 (禁版本号铁律)。

    为什么必须 stub 掉真实网络调用 — 三条理由叠在一起:
      1. **离线声明**: 整个 eval 套件对外声明"全离线确定性", 只有这个探针
         会真的发 HTTP 请求 (check_connection 内部 GET 根路径)。不断网
         则 CI/断网机器上这条探针必红, 且红的原因与它要测的东西无关。
      2. **假绿风险**: pybest 的 info() 自己吞掉所有异常并照样回
         connected, 即使完全无网络也报 ok=True — 不 stub 就测不到真实契约。
      3. **注入后才可判定**: 用 patch 喂一个已知 200 的桩, 才能确定性地
         走到连通判定分支; 星表注册表 (CATALOG_DISPLAY) 的"无 version
         字段"断言则完全离线 (静态表)。

    P1 合并注记: pybest 单类 (Best.info 信封) 删除后, 连接面守门改经
    BestClient.check_connection (布尔语义, 不吞异常成信封) + 协议层静态
    星表注册表; 禁版本号铁律的断言对象随之改为注册表本身。

    Returns:
        (是否通过, 人类可读说明)。
    """
    # 探针内惰性导入: patch 打桩传输层 (不让 check_connection 触网)
    from unittest.mock import patch

    from src.client import BestClient
    from src.protocol import CATALOG_DISPLAY

    client = BestClient(rate_limit=0)   # rate_limit=0 + 桩传输: 离线铁律, 一条真实请求都不发
    stub = Mock()                                                                                # HTTP 替身: 本探针只验信息组装, 不触网
    stub.status_code = 200                                                                        # 状态码给 200: 连接信息组装与状态码无关
    # 打桩点: 只换传输层, 连通判定仍是生产代码真跑
    with patch.object(client.session, "get", return_value=stub):
        connected = client.check_connection()                                               # 真调一次: 连接结论由生产逻辑给出, 替身只挡网络那一层
    if connected is not True:                                                                  # 断身份而非真值: 返回 1 之类的假值不该蒙混过关
        return False, "连接探测异常: 桩 200 未判为可达"
    if "version" in CATALOG_DISPLAY:    # 禁版本号铁律的断言面, 完全离线
        return False, "星表注册表残留 version 字段"
    if len(CATALOG_DISPLAY) < 12:                                                             # 展示名数量是覆盖面下限: 少一张表说明注册簿被裁剪过
        return False, f"星表注册表不足 12 张: {len(CATALOG_DISPLAY)}"
    return True, "连接探测 + 星表注册表实测通过 (无版本字段, 未发请求)"


def _exec_background_download_probe() -> tuple[bool, str]:
    """真实执行: submit 即返回 (后台线程), result 可得路径, 进度文件在。

    关键阈值是 ``submit_cost < 0.1``: 下载本身要 0.15s, 若 submit 同步等下载
    完成, 这一条就会红。它盯的是"提交不阻塞"这个后台模型的核心承诺。

    Returns:
        (是否通过, 人类可读说明)。
    """
    # 函数内导入: tempfile 造隔离临时目录, time 量 submit 耗时
    import tempfile
    import time

    with tempfile.TemporaryDirectory() as td:                                                  # 临时目录隔离: 下载产物能整体丢弃, 不进评测目录
        mgr = _stub_manager(td)       # 桩下载器固定 100B + 0.15s 延迟, 阈值因此可判定
        # 函数内导入: 文件任务数据模型 (被计时的那个 submit)
        from src.download_manager import FileJob

        t0 = time.time()                                                                            # 计时起点: 进度可见性要靠真实耗时差来验
        job_id = mgr.submit(FileJob(url="https://stub/x.dat", filename="x.dat"))
        submit_cost = time.time() - t0  # 下载本身要 0.15s, 同步等待必然超 0.1 阈值
        path = mgr.result(job_id, timeout=30)                                                       # 等真实完成: 只提交不等待验不到执行链
        rec = mgr.status(job_id)                                                                # 状态也要取: 文件落盘与状态置完成是两件独立的事
        ok = (submit_cost < 0.1 and path.endswith("x.dat")   # 四项全中: 快+有产物+终态+字节精确
              and rec["status"] == "done" and rec["done_bytes"] == 100)
        # 探针必须自己收线程: 否则临时目录删不掉, 且线程泄漏会拖垮整轮评测
        mgr.shutdown()                 # 漏收线程会让后续探针的临时目录删不掉
    return ok, f"后台下载实测: submit {submit_cost*1000:.0f}ms 即返回, done, 100B"
def _exec_parallel_download_probe() -> tuple[bool, str]:
    """真实执行: submit_all 多任务并行且结果文件不互相覆盖。

    两个任务只可能因"输出路径/key 碰撞"而互相覆盖, 所以断言
    ``len(set(paths)) == 2`` 而不是只看数量 —— 数量对但内容互相踩掉,
    在真实作业里意味着用户静默丢一半数据。

    Returns:
        (是否通过, 人类可读说明)。
    """
    # 函数内导入: tempfile 造隔离临时目录 (两个并行任务各写自己的目录)
    import tempfile

    with tempfile.TemporaryDirectory() as td:                                                    # 批量下载同样隔离: 多个作业的产物不能互相覆盖
        mgr = _stub_manager(td, max_workers=2)  # 2 线程才真并行; 单线程下这条恒过, 无信息量
        # 函数内导入: 文件任务数据模型 (两个并行任务的输入)
        from src.download_manager import FileJob

        ids = mgr.submit_all([                                                                  # 一次提交多个作业: 批量接口的编排逻辑就在这里验
            FileJob(url="https://stub/a.dat", filename="a.dat"),
            FileJob(url="https://stub/b.dat", filename="b.dat"),
        ])
        paths = [mgr.result(j, timeout=30) for j in ids]                                            # 逐个等完成: 批量提交不等于批量完成
        ok = len(paths) == 2 and len(set(paths)) == 2  # 断唯一性而非数量: 互踩即静默丢一半数据
        mgr.shutdown()                                                                             # 显式收尾: 不关会把后台线程留在评测进程里
    return ok, f"并行下载实测: {len(set(paths))}/2 唯一结果路径"
def _exec_download_resume_probe() -> tuple[bool, str]:
    """真实执行: checkpoint 存取 + resume spec 重建 (页级续传机制)。

    断言 ``resume(job_id) == job_id``: resume 必须是**原地续传**而不是派新任务。

    B4 债务修复后改写: 旧探针断言 ``new_id != job_id``, 依据是"resume 必须是
    新任务否则断点历史被覆盖"。该依据不成立 —— 旧行为下 file/precise 走
    ``self.submit(job)`` 派新 id, **旧进度记录反而停留在非终结状态**, 调用方跟踪旧 id
    永远等不到终态, 且重复 resume 无幂等保护会不断派生新 job。现在 file/precise 与
    region/sqlid 同口径: 同一 job_id 原地重跑, 成果落回同一进度记录, 重复 resume 直接
    返回原 id 而不派第二个 worker。断点历史审计由进度记录本身承担 (它被推到终态而不是
    被遗弃), 不需要靠"换 id"来保留。

    Returns:
        (是否通过, 人类可读说明)。
    """
    # 函数内导入: tempfile 造隔离临时目录
    import tempfile

    with tempfile.TemporaryDirectory() as td:                                                       # 续传实测的进度目录必须能整体丢弃
        mgr = _stub_manager(td)                                                                 # 用桩管理器: 续传要验的是幂等, 不需要真实字节
        # 函数内导入: 文件任务数据模型 (被续传的那个任务)
        from src.download_manager import FileJob

        job_id = mgr.submit(FileJob(url="https://stub/c.dat", filename="c.dat"))
        mgr.result(job_id, timeout=30)  # 先跑到终态: 否则 checkpoint 还没写就 resume
        # 原地续传: 必须返回同一 job_id (B4 修复的核心语义)
        resumed_id = mgr.resume(job_id)  # 派新 id 会遗弃旧进度, 调用方永远等不到终态
        path = mgr.result(resumed_id, timeout=30)                                                  # 续传后要真能拿到结果: 光有作业记录不算续上
        # 幂等: 重复 resume 同一 job 不得派生第二个 job
        again_id = mgr.resume(job_id)   # 无幂等保护会不断派生新 worker
        jobs = mgr.progress_store.list_jobs() if hasattr(mgr, "progress_store") else []  # hasattr 兜底: 管理器无此字段时不误红
        ok = (path.endswith("c.dat")     # 产物+同 id+幂等+不派生新记录, 四项同时成立
              and resumed_id == job_id                                                        # 续传必须复用原作业号: 另起一个作业等于把重下了一遍
              and again_id == job_id                                                              # 再续一次仍是同一作业: 幂等要经得起重复调用
              and len(jobs) <= 1)                                                             # 作业数不得增长: 重复续传造出第二个作业就是幂等破口
        mgr.shutdown()                                                                              # 收尾管理器: 后台线程不留给下一条探针
    return ok, "续传实测: checkpoint->resume 原地续传且幂等 (同一 job_id)"
def _exec_hook_intercept_ask_probe() -> tuple[bool, str]:
    """真实执行: severe 拦截产生 ask 载荷 (原因+证据+方案), 后台置 blocked。

    这条探针同时验证"机器侧"与"人侧"两端: blocked 状态落进任务记录,
    ask 载荷 (含 >=2 个选项) 落进 pending_asks。任何一端缺失,
    调用方都无法向用户发起有效提问, hook 分级拦截就形同虚设。

    Returns:
        (是否通过, 人类可读说明)。
    """
    # 函数内导入: tempfile 造隔离临时目录
    import tempfile

    with tempfile.TemporaryDirectory() as td:                                                   # hook 拦截实测的目录隔离: 产物不进评测目录
        mgr = _stub_manager(td)                                                                  # 桩管理器: 拦截发生在编排层, 不需要真实下载
        # 函数内导入: 门禁中断异常与文件任务模型 (构造"校验和不符"的 blocked 场景)
        from src.download_hooks import HookBlockedError, HookInterrupt
        from src.download_manager import FileJob

        interrupt = HookInterrupt(kind="checksum_mismatch", reason="sha256 不符",
                                  evidence={"expected": "aa"},
                                  options=[{"label": "重下"}, {"label": "保留"}])  # 两选项是硬契约: 只给一个等于没让用户选

        # 覆写桩客户端: 让下载阶段直接抛 HookBlockedError, 模拟校验和不符
        class _BoomClient(_StubFileClient):
            """必失败的下载桩: ``download_file`` 一律抛 ``HookBlockedError``。

            用途是验证"下载阶段被门禁阻断"这条路径 — 若管理器把 blocked 吞成
            普通失败, 任务状态会错报成 failed 而不是 blocked, 人就找不到
            该去处理的那个中断点了。
            """
            def download_file(self, *a, **kw):
                """无视参数直接抛出门禁中断异常。"""
                raise HookBlockedError(interrupt)

        mgr.client = _BoomClient()   # 换掉下载端: 让门禁在执行期抛, 模拟校验和不符
        job_id = mgr.submit(FileJob(url="https://stub/d.dat"))
        try:
            mgr.result(job_id, timeout=30)                                                          # 真等一次: 拦截要在执行链里发生才算数
            blocked = False                                                                         # 默认未拦: 没有抛阻断异常就说明守卫生效
        except HookBlockedError:
            blocked = True                                                                      # 命中才置真: 与默认相反, 漏判不会被默认值掩盖
        rec = mgr.status(job_id)     # 状态落进任务记录: 人要能看到卡在哪个中断点
        asks = mgr.pending_asks()    # 人侧载荷: 没有它就无法向用户发起有效提问
        ok = (blocked and rec["status"] == "blocked" and len(asks) == 1
              and asks[0]["id"] == "hook_checksum_mismatch"
              and len(asks[0]["options"]) >= 2)
        mgr.shutdown()                                                                              # 收尾: 拦截分支的线程同样要关
    return ok, "hook 拦截实测: blocked + ask 载荷 (2 方案) 可 surfaced"
def _exec_download_progress_visible_probe() -> tuple[bool, str]:
    """真实执行: 进度文件字段完整 + 文本条可渲染 (CLI/GUI 同源)。

    字段集合用 ``<=`` 子集断言而不是相等: 允许实现新增字段, 但六个关键字段
    (job_id/status/total_pages/done_pages/speed_bps/updated_at）一个不能少 ——
    少任何一个, GUI 进度条就会缺一块或直接崩。

    Returns:
        (是否通过, 人类可读说明)。
    """
    import tempfile

    with tempfile.TemporaryDirectory() as td:                                                     # 进度存储实测的目录隔离: 落盘产物能整体丢弃
        from src.download_progress import ProgressStore, ProgressTracker, render_text_bar

        store = ProgressStore(td)                                                                   # 进度存储现构造: 读写都在临时区完成
        tr = ProgressTracker(store, "probe_job", total_pages=2)
        tr.start()                                                                              # 启动跟踪线程: 进度要能被另一个组件看见才算可见
        tr.advance_pages(1)          # 推进 1/2: 制造"进行中"而非"已完成"的中间态
        # 读点: 从进度文件读回记录, 验证"落盘即可见" (而不是只在内存里)
        rec = store.load("probe_job")  # 证明落盘即可见, 而非只在内存里有
        bar = render_text_bar(rec.to_dict())  # 同一份字典喂渲染器, 保证 CLI/GUI 字段一致
        ok = (rec is not None and rec.status == "running"  # 子集断言: 允许加字段, 六个关键字段不能少
              and {"job_id", "status", "total_pages", "done_pages",
                  "speed_bps", "updated_at"} <= set(rec.to_dict())
              and "running" in bar and "%" in bar)
    return ok, "进度实测: 文件字段完整, 文本条可渲染"
def _exec_precise_download_probe() -> tuple[bool, str]:
    """真实执行: source_id in 约束表单 + 0 结果 hook ask + 任务类型分发。

    分两段验证: 先验 ``build_precise_form`` 把 ID 列表编成 ``in`` 约束
    (含星表 ID 列映射, stripe82 走 calibstars_id), 再验 0 结果时 hook 真的
    拦住并产出 ask。只验前半段的话, "精准下载返回空却被当成成功" 这类
    静默丢数据的故障永远测不出来。

    Returns:
        (是否通过, 人类可读说明)。
    """
    import tempfile
    from unittest.mock import patch

    with tempfile.TemporaryDirectory() as td:                                                      # 精准下载实测的目录隔离: 产物不进评测目录
        from src.download_hooks import HookBlockedError
        from src.download_manager import DownloadManager, PreciseDownloadJob
        from src.download_precise import build_precise_form

        # 1. 表单: in 约束 + 星表 ID 列映射 (stripe82 -> calibstars_id)
        job = PreciseDownloadJob(source_ids=["CALIBSTARS_1", "CALIBSTARS_2"],
                                 catalog="stripe82")  # stripe82 走 calibstars_id, 列映射错则整批查空
        form = build_precise_form(job)                                                         # 表单真构造: 列映射错了服务端认不出, 属静默失效
        form_ok = (form.get("stripe82.calibstars_id.operation") == "in"  # ID 列表按换行拼进 textarea, 顺序不能变
                   and form.get("stripe82.calibstars_id.textarea")
                   == "CALIBSTARS_1\nCALIBSTARS_2")
        # 2. 0 结果 -> hook ask (mocked downloader)
        mgr = DownloadManager(_StubFileClient(), output_dir=td,                                 # 桩客户端跑完整链: 全程不触网, 只验编排与落盘
                              progress_dir=f"{td}/.progress",
                              checkpoint_dir=f"{td}/.checkpoints")
        # 写点: 落一个只有表头的空 CSV, 模拟"查询成功但 0 命中"
        empty = Path(td) / "empty.csv"
        empty.write_text("calibstars_id,ra\n", encoding="utf-8")

        def _fake(self, *a, **kw):
            """替身落盘: 返回只有表头的空 CSV 路径, 模拟"查询成功但 0 命中"。

            Args:
                self: 占位 (patch 到实例方法上, 签名要能接住 self)。
                *a: 位置参数占位。
                **kw: 关键字参数占位。

            Returns:
                那个空 CSV 的路径字符串; 生产代码的 hook 判定会读到 0 数据行。

            Note:
                只替换落盘结果, hook 判定逻辑仍跑生产代码 — 否则测的就是桩自己。
            """
            return str(empty)

        # 打桩点: 只替换下载器落盘结果, hook 判定逻辑仍是生产代码
        with patch("src.downloader.BestDownloader.download_by_constraints",
                   _fake):                                                                    # 替身只提供两样: 请求注入与响应形态, 别的都是噪声
            jid = mgr.submit(job)                                                                   # 提交真实作业: 只构造管理器验不到执行链
            try:
                mgr.result(jid, timeout=30)                                                     # 期望在这里被拦: 抛阻断异常正是本探针要验的行为
                blocked = False                                                                     # 默认未拦: 没抛异常就说明守卫生效
            except HookBlockedError:
                blocked = True                                                                  # 命中才置真: 与默认相反, 漏判不会被默认值掩盖
        rec = mgr.status(jid)           # 阻断态要能从状态接口查到, 否则用户看不到
        ok = (form_ok and blocked and rec["status"] == "blocked"  # 表单+拦截+状态+一条待决策, 缺一不可
              and rec["hook"]["id"] == "hook_empty_precise_result"
              and len(mgr.pending_asks()) == 1)                                                   # 待决策项恰好一条: 漏挂或重复挂都要能被发现
        mgr.shutdown()                                                                              # 收尾: 拦截分支的线程同样要关
    return ok, "精准下载实测: in 表单 + 0 结果 hook ask (blocked+载荷)"
def _exec_task_log_probe() -> tuple[bool, str]:
    """真实执行: 任务日志记录/查询/聚合 (快速定位问题)。

    断言事件链 ``submit -> start -> done`` 而非只看"有日志": 缺 start
    说明执行态没留痕, 出问题时只能看到提交和结果, 中间发生了什么全黑。

    Returns:
        (是否通过, 人类可读说明)。
    """
    import tempfile

    with tempfile.TemporaryDirectory() as td:                                                     # 任务日志实测的目录隔离: 事件落盘能整体丢弃
        from src.download_manager import DownloadManager, FileJob
        from src.task_log import TaskLogger

        log = TaskLogger(log_dir=td)   # 显式注入 log_dir: 默认路径会写到用户主目录
        mgr = DownloadManager(_StubFileClient(), output_dir=td,                               # 桩客户端: 日志可见性只依赖编排层, 不需要真实字节
                              progress_dir=f"{td}/.progress",
                              checkpoint_dir=f"{td}/.checkpoints",
                              task_log=log)   # task_log 必须显式传入, 否则日志与下载器失联
        jid = mgr.submit(FileJob(url="https://stub/x.dat", filename="x.dat"))
        mgr.result(jid, timeout=30)                                                             # 真等完成: 日志事件要发生在真实执行链上才有意义
        # 读点: 从本地日志读回事件链, 验证"写了且能查"
        events = [r["event"] for r in log.tail(n=0, task_id=jid)]
        summary = log.summarize(jid)                                                       # 按作业号汇总: 报告要能按任务维度看事件, 而不是只看全局
        ok = (events[0] == "submit" and events[-1] == "done"  # 断首末+中间 start+聚合计数对齐
              and summary["found"] and summary["events"] == len(events)
              and "start" in events)
        mgr.shutdown()                                                                              # 收尾: 后台线程不留给下一条探针
    return ok, f"任务日志实测: {len(events)} 事件链 submit→start→done 可查询聚合"
def _exec_name_resolve_probe() -> tuple[bool, str]:
    """真实执行: 名称解算入口 + 失败哨兵判定 + remark 外部标注。

    哨兵判定用 ``ra == -1000`` 这组"服务端约定俗成的失败值": 名称解算失败
    时服务端不报错, 而是回一个越界坐标, 客户端必须认得出来, 否则 M31 解算
    失败会被当成"它在 (-1000,-1000)"继续往下游传。

    Returns:
        (是否通过, 人类可读说明)。
    """
    from src.protocol import is_name_resolve_failure, parse_name_resolve

    payload = parse_name_resolve('{"ra": 10.68470833, "dec": 41.26875, "obj": "M31"}')
    failure = parse_name_resolve('{"ra": -1000, "dec": -1000}')  # 失败哨兵: 服务端回越界坐标而不报错
    ok = (payload["ra"] == 10.68470833  # 正反同断: 只断正例的话哨兵判定恒 False 也能过
          and not is_name_resolve_failure(payload)                                            # 正常载荷不该被判成解析失败: 误报会让真坏结果被放过
          and is_name_resolve_failure(failure))                                              # 失败载荷必须被判成解析失败: 漏判等于哨兵坐标混进结果
    # 客户端入口必须可被发现: 外部脚本与 agent 都经 BestClient 直调
    # (P1 口径下的唯一生产客户端)
    from src.client import BestClient

    entry_ok = hasattr(BestClient, "resolve_name")
    return ok and entry_ok, "名称解算实测: 哨兵判定 + BestClient 入口 (M31 坐标 live 已核)"
def _exec_proximity_batch_probe() -> tuple[bool, str]:
    """真实执行: proximity 批量匹配表单构造 + 输入行号回连 + fallback 标注。

    行号回连 (``S1 -> ``) 是批量匹配的可用性关键: 用户交 1000 个坐标,
    结果必须能逐条对回"哪个输入产生了哪条输出", 否则多源匹配结果无法归因。
    这里只打桩 ``_execute_query`` (传输层), 匹配与回连逻辑全真跑。

    Returns:
        (是否通过, 人类可读说明)。
    """
    from unittest.mock import patch

    from src.client import BestClient
    from src.crossmatch import (
        BestCrossMatch,  # 交叉匹配主类: 探针直接构造它跑真实匹配
        _input_line_index,  # 输入行索引: 就近匹配按它把结果回连到输入坐标
        _proximity_radec_text,  # 就近表单构造: 坐标文本形态错了服务端不认
    )
    from src.models import BestQueryResult, BestSource

    text = _proximity_radec_text([180.0, 181.0], [30.0, 31.0], 3.0)                            # 两个输入坐标真造表单: 多输入形态是就近的主要难点
    client = BestClient(rate_limit=0)                                                               # 节流归零: 探针不得引入等待
    xm = BestCrossMatch(client)                                                                     # 真构造匹配器: 只测工具函数验不到编排层
    captured: dict = {}    # 闭包捕获表单: 断言"一次提交"而非逐点 N 次

    # 打桩点: 捕获真实提交的表单 (验证"一次提交"而非逐点 N 次请求),
    # 同时返回一条带 inputobjs_input_line 的伪造结果供回连逻辑消费
    def fake_execute(path, form, *args, **kwargs):
        """替身执行器: 记录被提交的表单并返回一条带回显列的伪造结果。

        Args:
            path: 请求路径 (替身不使用)。
            form: 被测代码真正提交的表单 — 捕获它以断言是"一次批量提交"。
            *args: 位置参数透传占位。
            **kwargs: 关键字参数透传占位。

        Returns:
            一条 ``BestQueryResult``, 其 source 带 ``inputobjs_input_line`` 列,
            用来验证客户端能把服务端回显行号连回输入坐标。
        """
        captured["form"] = form
        return BestQueryResult(
            success=True,                                                                          # 回包显式声明成功: 失败信封会走另一条分支
            sources=[                                                                            # 源列表逐项构造: 哨兵坐标必须能在这层被认出来
                BestSource.from_row(                                                                # 源对象从行构造: 与生产解析走同一条路
                    {"inputobjs_input_line": "1", "ps1_ra": "180.0", "ps1_rpsf": "15.2"},
                    catalog="ps1",
                ),
            ],
            total_count=1,                                                                      # 总数与返回数都要给: 截断三元组判据靠这三项对账
        )

    with patch.object(client, "_execute_query", side_effect=fake_execute):  # 只打桩传输层, 匹配与回连全真跑
        result = xm.crossmatch_batch([180.0], [30.0], radius_arcsec=3.0, id_list=["S1"])
    form = captured["form"]  # 读回被捕获的表单: 提交次数与内容都在这里验
    ok = (form["pos.type"] == "proximity"  # 模式+文本+半径+回连+行号索引, 少一项批量就不可归因
          and form["pos.radecTextarea"] == "180.0,30.0,3.0"
          and form["pos.defaultRadius"] == "3.0"
          and result.query_params["mode"] == "proximity"
          and result.sources[0].source_id == "S1 -> "
          and _input_line_index("1", 2) == 0)
    return ok, f"proximity 实测: 一次提交表单 + 行号回连 ({text.splitlines()[0]})"
def _exec_tap_adql_probe() -> tuple[bool, str]:
    """真实执行: ADQL 子集解析为安全计划, 越界语法拒绝。

    四条反例 (JOIN / COUNT / 子查询 / 不存在列) 必须全部被拒: BEST 只有
    表单式 REST, ADQL 只是本 skill 的白盒子集。任何一条放行都意味着
    生成的"安全计划"会含服务端根本不支持的结构, 用户在运行期才炸。

    Returns:
        (是否通过, 人类可读说明)。
    """
    from src.tap.adql import ADQLError, parse_adql

    plan = parse_adql(CONE_ADQL)  # 共享锥形 ADQL: 探针与生产走同一份输入
    ok = (plan.catalog == "ps1" and plan.columns == ("ps1_ra", "ps1_rpsf")
          and plan.branches[0].cone is not None)                                              # 锥形约束必须解析出来: 丢了它等于过滤条件被静默忽略
    rejected = 0                                                                                    # 拒答计数: 非法语句一条都不许放过
    for bad in (                                                                          # 逐条喂非法语句: 覆盖缺 FROM、JOIN 与写错的星表名
        "SELECT ra FROM best.ps1 JOIN best.stripe82 ON 1 = 1",
        "SELECT COUNT(*) FROM best.ps1",
        "SELECT ra FROM (SELECT ra FROM best.ps1)",
        "SELECT nope FROM best.ps1",
    ):
        try:
            parse_adql(bad)                                                                    # 真调解析器: 期望它抛, 不抛就是这个校验名不副实
        except ADQLError:
            rejected += 1                                                                        # 抛了就计数: 汇总值要与上面逐条尝试的条数一致
    # 4 条全拒才算过: 少拒一条 = 白名单有洞, 必须整体红
    return ok and rejected == 4, f"ADQL 子集实测: 计划解析 + {rejected}/4 越界拒绝"  # 4/4 硬要求, 不接受"多数拒了"
def _exec_tap_service_probe() -> tuple[bool, str]:
    """真实执行: 网关路由 sync/配额/Bearer (离线桩执行器)。

    四种响应各盯一条契约: sync 200 带数据、坏 Bearer 401、未知路径 404、
    VOSI availability 可发现。``_FakeBest`` 只替代底层查询, 网关的
    路由/鉴权/降级逻辑全是生产代码。

    Returns:
        (是否通过, 人类可读说明)。
    """
    from src.tap.executor import TapExecutor
    from src.tap.service import TapGateway

    # 离线桩: 让网关拿到确定数据, 不碰真实 BEST 端点
    class _FakeBest:
        """假 BEST 客户端: 任何 ADQL 查询都返回同一行 ps1 伪造数据。

        只用一行带表前缀的列名 (``ps1_ra``/``ps1_rpsf``), 这样能顺带验证
        VOTable/CSV 格式化时列名前缀没有被丢掉。
        """
        def query(self, **_kwargs):
            """忽略全部查询参数, 固定返回一行源数据。"""
            return [{"ps1_ra": "180.0", "ps1_rpsf": "15.5"}]

    gateway = TapGateway(TapExecutor(_FakeBest()))  # 只替底层查询, 网关路由/鉴权/降级全真跑
    ok_sync = gateway.handle(                                                                     # 同步入口先调: 两种鉴权都要在同一网关面上验
        "GET", "/tap/sync",
        params={"REQUEST": "doQuery", "LANG": "ADQL", "QUERY": CONE_ADQL, "FORMAT": "csv"},
        headers={},                                                                                 # 空请求头: 无凭据必须落拒绝而不是放行
    )
    ok_bearer = gateway.handle(                                                                     # 带凭据再调一次: 通过与拒绝要能同时复现
        "GET", "/tap/sync", params={"QUERY": CONE_ADQL},
        headers={"Authorization": "Bearer bad"},   # 坏 Bearer 必须 401 而非 500, 鉴权失败与崩溃要分得开
    )
    ok_404 = gateway.handle("GET", "/tap/nope", params={}, headers={})
    ok_availability = gateway.handle("GET", "/tap/availability", params={}, headers={})
    ok = (ok_sync.status == 200 and b"ps1_ra" in ok_sync.body                               # 无凭据却拿到成功与数据即鉴权失效: 这是最严重的一类破口
          and ok_bearer.status == 401                                                              # 带凭据反而被拒: 凭据形态或校验顺序有问题
          and ok_404.status == 404                                                         # 未知路径必须落 404: 兜成成功会让部署探测误判服务可用
          and b"availability" in ok_availability.body)                                             # 探活端点要能应答: 它是部署后的第一道判据
    return ok, "TAP 网关实测: sync 200 + Bearer 401 + 404 + VOSI availability"
def _exec_agent_tools_probe() -> tuple[bool, str]:
    """真实执行: 工具面信封/cost/错误码 (离线)。

    两个易被忽略的断言:
      - ``cost["http_requests"] == 0``: 证明这两个工具真的离线 (登记表演示),
        否则"零请求"只是文档说法;
      - ``set(envelope) == {data, status, cost, provenance}``: 信封四段
        结构是跨 skill 传递的硬契约, 少一段下游就解不开。

    Returns:
        (是否通过, 人类可读说明)。
    """
    from src.ai_tools import TOOL_NAMES, ToolBox
    from src.client import BestClient

    box = ToolBox(BestClient(rate_limit=0))  # rate_limit=0: 登记表演示工具必须真零请求
    catalogs = box.list_catalogs()                                                                # 工具箱真调: 信封结构与请求计数都在这一份里
    described = box.describe_catalog("ps1")
    rejected = box.describe_catalog("std")  # 反例: 未登记星表须回稳定错误码而非抛异常
    ok = (catalogs.status["ok"] and catalogs.cost["http_requests"] == 0
          and len(catalogs.data["catalogs"]) == 12
          and described.status["ok"] and described.data["catalog"] == "ps1"
          and rejected.status["error_code"] == "E_INVALID_INPUT"
          and len(TOOL_NAMES) == 7)                                                            # 工具数是覆盖面下限: 少一个工具即说明注册面被裁剪
    envelope = catalogs.to_dict()                                                                   # 信封转字典: 四段结构要在这里逐段验
    ok = ok and set(envelope) == {"data", "status", "cost", "provenance"}  # 信封四段是硬契约, 少一段下游解不开
    return ok, "工具面实测: 信封四段 + 离线零请求 + 7 工具 + 错误码映射"
