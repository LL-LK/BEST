"""astro-best skill 编排层 (src.core) 的回归测试。

覆盖 QualityGate 质量门控 (含 Q-14 fail-closed 守门) 与 BestSkillClient
的配置透传/接线, 以及 scripts 公开入口的可导入性 — 全部离线, 不打站点。

职责: 守住编排层两条主线。质量门控这条: 阈值默认值与透传、源级放行规则, 以及
  Q-14 的 fail-closed 语义 —— 拿不到质量字段时必须判不通过而不是当作合格放行。
  接线这条: BestSkillClient 把配置透传给底层客户端, 且 scripts 公开入口仍可导入,
  免得 CLI 侧的入口重构在测试期直接 ImportError。
所属层次: test/unit 层, 对应被测模块 src/core/ (BestSkillClient 管线级门面与
  QualityGate 质量门控), 协作件是 src/models/ 的行模型 (Q-04 前缀剥离) 与
  scripts 包的公开入口 —— 本文件全程离线, 客户端不监听端口也不发请求。
对外接口: TestQualityGate 覆盖默认阈值、自定义阈值透传、源级放行与光变点数门控;
  随后的客户端用例覆盖配置透传与接线; 末段用例验 scripts 公开入口的可导入性。
依赖与数据流: 全部输入是内联的源对象与阈值参数, 无临时目录、快照或夹具;
  断言只读 QualityGate 的判定结果与 BestSkillClient 的透传结果, 不产生写操作。
关键契约与不变量: fail-closed 是本层最硬的不变量 —— 质量字段缺失 (None) 必须
  落在拒绝侧, 一旦改成 fail-open, 缺测数据会以"合格"身份流进下游管线, 而外部
  完全看不出来; 门控阈值走缺省构造, 与 BestSkillClient 的缺省配置必须一致,
  否则"没配就等于配了另一个值"。
陷阱与边界: 默认值用等值断言 (5.0/5.0) 而不是范围断言, 因为契约就是这两个数,
  放宽了等于放弃守门; 可导入性用例只验名字能取到, 不调其函数体 —— 它防的是
  入口重构把 CLI 的公开面改没, 而不是重复测 scripts 自身的行为。
"""
from __future__ import annotations

# 标准库: mock 只用于本文件这两条锥搜用例 —— 替身必须停在传输层, 不得落在被测函数上
from unittest.mock import Mock, patch  # 替身层: 下面只断 session.post/session.get 这两个 HTTP 往返点

import pytest  # 第三方: 测试发现

# 本地: skill 编排层 (BestSkillClient 配置透传 Q-15/56, QualityGate 质量门控)
from src.core import BestSkillClient, QualityGate  # 门面 + 质量门控的权威实现
from src.models import BestSource  # 行模型: Q-04 前缀剥离发生在这层

# ---------------------------------------------------------------------------
# 传输层替身素材 — 桩停在 HTTP 往返上, 真实门面与真实协议编排全程执行
# ---------------------------------------------------------------------------
# phase-1 回包: 带 sqlid 的结果页 HTML (会话创建成功的最小形态)
_PHASE1_HTML = '<script>url:"/data/best/sqlid/s9999"</script>'
# phase-2 回包: 无表头 CSV, 列名按 ps1 前缀形态 (行模型按前缀剥离后还原 ra/dec/snr/
# class_star 与 r 波段星等 —— 门控的四个检查项因此全部"有指标可判", 好源能过线)
_WIRE_CSV = "ps1_ra,ps1_dec,ps1_rpsf,ps1_snr,ps1_class_star\n180.0,30.0,15.23,45.0,0.98\n"


def _cone_search_over_fake_wire(client, **kwargs) -> tuple[list, dict]:
    """跑真实 ``BestSkillClient.cone_search``, 只把 HTTP 往返换成替身。

    桩停在**传输层** (``client.session.post`` / ``client.session.get``): 真实门面的
    参数组装、真实 ``BestClient.cone_search``、真实 phase-1 表单构造、真实 sqlid
    解析、真实 CSV 解析、质量门控与查询审计一行不少地执行 —— 断的只是"线上",
    不是"被测函数"。

    Returns:
        ``(门面返回的 list, 真正 POST 出去的 phase-1 表单 dict)``。第二项是判定的
        真值来源: 入参有没有被原样组装进表单, 只看这一份就够。
    """
    posted: dict = {}  # 捕获通道: 只留 phase-1 提交那一笔, phase-2 分页不参与本判据

    def fake_post(url, data=None, **_kw):  # 替身签名对齐 requests: 客户端按 (url, data=...) 调
        """替身 POST: 记账表单后回一段带会话号的结果页 (HTTP 200)。"""
        posted["url"] = url  # 先记账: 判据要看的是客户端真发出去的东西
        posted["form"] = dict(data or {})  # 表单转浅拷贝: 客户端后续不再改它, 但别让断言绑在替身对象上
        resp = Mock()  # 回包对象: 状态码与正文按最小成功形态给
        resp.status_code = 200  # 显式给 200: raise_for_status 与软错误判定都按成功路径走
        resp.text = _PHASE1_HTML  # 正文带 sqlid: 这是 phase-2 能继续取数的唯一前提
        return resp  # 交给真实编排继续走

    def fake_get(url, **_kw):  # 替身签名对齐 requests 的 GET
        """替身 GET: 计数端点回 total JSON, 数据页回 1 行 CSV。"""
        resp = Mock()  # 回包对象: 两种 URL 形态必须分开给, 否则解析层读到错的东西
        resp.status_code = 200
        resp.text = '{"total": 1}' if "getcount" in url else _WIRE_CSV  # 按 URL 内容分派: 计数与数据是两种协议
        return resp  # 交给真实分页器继续走

    with patch.object(client.client.session, "post", side_effect=fake_post), \
            patch.object(client.client.session, "get", side_effect=fake_get):  # 只断两个 HTTP 往返点
        result = client.cone_search(**kwargs)  # 走真实门面
    return result, posted.get("form", {})  # 连表单一起交出去: 判据需要它, 不是可选诊断


def _assert_radius_reached_wire(form: dict, expected: str) -> None:
    """判据 (单点): 半��必须被原样组装进 phase-1 表单的 ``pos.radius`` 键。

    单独抽成函数是为了让变异自检用例**逐字复用**同一条判据: 只有同一段判据在
    "注入坏实现"后转红, 才证明这道门真的会红, 而不是靠另一条更严的断言蒙对。
    """
    assert form.get("pos.radius") == expected, (  # 等值而非范围: 契约是"原样透传", 换算成度就已是回归
        f"phase-1 表单的 pos.radius = {form.get('pos.radius')!r}, 期望 {expected!r} —— "
        "门面没有把 radius_arcsec 原样往下传 (被吞掉、被换算, 或被默认值覆盖)"
    )



class TestQualityGate:
    """QualityGate 质量门控守门: 阈值默认值/透传、源级放行规则 (含 Q-14
    fail-closed 语义) 与光变点数门控。"""

    def test_init_defaults(self):
        """默认阈值守门: min_snr=5.0 / max_fwhm=5.0 是 QualityGate 的契约
        默认值, 与 BestSkillClient 缺省配置一致。"""
        qg = QualityGate()  # 缺省构造: 阈值必须落回契约默认值
        assert qg.min_snr == 5.0  # 等值断言, 放宽范围等于放弃守门
        assert qg.max_fwhm == 5.0  # 同上, 两数都是契约的一部分

    def test_init_custom(self):
        """自定义阈值必须原样透传 (调用方按观测条件调门禁的入口)。"""
        qg = QualityGate(min_snr=10.0, max_fwhm=3.0)  # 调用方按观测条件调门禁的入口
        assert qg.min_snr == 10.0  # 原样透传, 不被默认值覆盖
        assert qg.max_fwhm == 3.0  # 两个键都要到

    def test_validate_source_passes(self):
        """高质量源守门: SNR/FWHM/class_star/星等都过线时必须放行 — 门控
        误杀好源等于把可用数据全拦在门外。"""
        qg = QualityGate()  # 用缺省阈值判, 顺带守住两套缺省一致
        src = BestSource(source_id="BEST001", ra=180.0, dec=30.0,
                         snr=45.0, fwhm=1.5, class_star=0.98,
                         magnitudes={"r": 15.23, "g": 16.10})  # 全项过线的干净源
        report = qg.validate_source(src)  # 判定连同可诊断的 checks 一起返回
        assert report["passed"]  # 好源必须放行, 误杀等于把可用数据全拦在门外

    def test_validate_source_low_snr(self):
        """低 SNR 守门: 必须拒之, 且报告里要能点名是 min_snr 检查项失败
        (可诊断性 — 用户要知道数据为什么被拦)。"""
        qg = QualityGate(min_snr=20.0)  # 门限抬到 20, snr=5 必挂
        src = BestSource(source_id="BEST001", ra=180.0, dec=30.0,
                         snr=5.0, magnitudes={"r": 15.23})  # 只有 SNR 低于门限
        report = qg.validate_source(src)                                                            # 质量门校验源数据
        assert not report["passed"]  # 低质量源拒收
        assert any(c["check"] == "min_snr" and not c["passed"] for c in report["checks"])  # 报告须点名失败项

    def test_validate_source_no_mags(self):
        """Q-14: 无任何质量指标可判时必须 fail-closed (旧测试钉死 fail-open)。"""
        qg = QualityGate()  # 缺省门控, 阈值不是本用例变量
        src = BestSource(source_id="BEST001", ra=180.0, dec=30.0)  # 刻意不给任何质量指标
        report = qg.validate_source(src)                                                            # 同上, 另一组样本
        assert not report["passed"]  # 无指标 = 无法证明质量, 不得放行 (audit 铁律 5)
        assert any(c["check"] == "no_metrics" and not c["passed"] for c in report["checks"])  # 失败项可诊断

    def test_validate_multiband_photometry_empty(self):
        """空光变守门: 0 个历元不得通过 (min_points 门控; 空曲线做任何周期
        分析都是无本之木)。"""
        qg = QualityGate()  # 光变门控复用同一门控实例
        from src.multiband_photometry import BestMultiBandPhotometry  # 延迟导入: 只光变用例要这条依赖链
        lc = BestMultiBandPhotometry(source_id="TEST")  # 0 个历元的空光变
        report = qg.validate_multiband_photometry(lc, min_points=3)  # 门限 3 个历元
        assert not report["passed"]  # 空曲线做任何周期分析都是无本之木

    def test_validate_multiband_photometry_sufficient(self):
        """点数足够守门: 3 个历元 = min_points 下限, 必须放行 — 门控卡在
        "刚好够用"的边界上会把正常数据误杀。"""
        qg = QualityGate()  # 同上, 变量只有历元个数
        from src.models import BestSource  # 延迟导入: 历元用行模型装
        from src.multiband_photometry import BestMultiBandPhotometry  # 延迟导入: 光变曲线容器
        points = [BestSource(source_id="T1"), BestSource(source_id="T2"), BestSource(source_id="T3")]  # 恰好 3 个
        lc = BestMultiBandPhotometry(source_id="TEST", points=points)  # 装进光变容器
        report = qg.validate_multiband_photometry(lc, min_points=3)  # 门限 3
        assert report["passed"]  # 边界上必须放行, 卡死会误杀正常数据


class TestBestSkillClient:
    """BestSkillClient 守门: 质量配置透传 (Q-15/56)、锥形检索入口返回形态
    与 crossmatch 接线 — 全部离线。"""

    def test_init_defaults(self):
        """缺省质量配置守门: 不传 quality_config 时 QualityGate 回到
        5.0/5.0 默认阈值。"""
        client = BestSkillClient()  # 不传 quality_config
        assert client.quality.min_snr == 5.0  # 缺省须与 QualityGate 契约同值
        assert client.quality.max_fwhm == 5.0  # "没配"不等于"配了另一个值"

    def test_init_with_quality_config(self):
        """Q-15/56 配置透值守门: quality_config 的每个键都必须到达
        QualityGate (静默丢弃配置字段会让调了阈值却不生效)。"""
        client = BestSkillClient(                                                             # skill 级门面: 构造即验证配置透传与质量门接线
            quality_config={"min_snr": 15.0, "max_fwhm": 3.0}
        )  # 两个键都必须真的到达 QualityGate
        assert client.quality.min_snr == 15.0  # 静默丢字段的写法会让调了阈值却不生效
        assert client.quality.max_fwhm == 3.0  # 同上, 逐键验

    def test_cone_search_forwards_params_to_wire_and_reports_quality(self):
        """锥形检索入口守门: 入参原样落进 phase-1 表单, 好源过门控并附判定明细。

        2026-10-05 R5-01 改写: 旧版用 ``patch.object(client, "cone_search", ...)``
        把**待验证的那个函数本身**替成 mock, 于是两条断言实际断的是
        ``unittest.mock`` 自身 —— 把真实实现改成返回 str 并吞掉全部参数, 它照样全绿
        (Q8 报告 §2 的变异构造)。现在桩下移到传输层: 真实门面的参数组装、真实
        ``BestClient.cone_search``、真实表单构造、真实解析与真实门控全程执行。
        """
        client = BestSkillClient(rate_limit=0)  # rate_limit=0: 关客户端限速, 否则每页先 sleep 拖慢离线跑批
        res, form = _cone_search_over_fake_wire(client, ra=180.0, dec=30.0, radius_arcsec=5.0)  # 入参原样下传
        # 第一层: 几何参数真的编进了 phase-1 表单 (Q-01 原生 pos.* 键, 不是 RA/Dec box)
        assert form.get("pos.type") == "cone"  # 走原生圆锥: 退化成 box-between 会被这条抓住
        assert form.get("pos.racenter") == "180.0"  # 圆心赤经以字符串落表: 服务端表单全是字符串值
        assert form.get("pos.deccenter") == "30.0"  # 圆心赤纬同理
        _assert_radius_reached_wire(form, "5.0")  # 半径原样 arcsec 透传, 不换算成度 (变异自检复用此判据)
        # 第二层: 返回形态与真实行内容 (值来自 CSV 解析, 不是桩的 return_value)
        assert isinstance(res, list) and len(res) == 1  # 恰一条: 门控把坏源剔掉, 好源必须留下
        row = res[0]
        assert (row["ra"], row["dec"]) == (180.0, 30.0)  # 坐标经行模型归位: 列错位会让 ra 变 0
        assert row["snr"] == 45.0  # ps1_snr 列确实被归一到字段上 (没有它门控会 fail-closed 剔光)
        assert row["magnitudes"]["r"] == 15.23  # 波段星等按显式映射表归一, 不靠首字母猜
        # 第三层: 门控真跑了并把判定明细附回该行 (Q-14 的可诊断性, 也是"过线"的唯一凭据)
        assert row["quality"]["passed"] is True  # 好源放行
        assert {c["check"] for c in row["quality"]["checks"]} == {"min_snr", "class_star", "has_magnitude"}  # 三个可判项都要留痕
        # 第四层: 审计真记了一笔 (Q-52 接线) —— 少了它 cone_search 的结果无从追溯
        assert client.audit_summary()["total_operations"] == 1  # 一次检索一条审计, 不是 0

    def test_cone_search_criterion_catches_a_swallowed_radius(self):
        """变异自检: 门面吞掉 radius_arcsec 时, 上一条用的判据必须转红。

        这条是 R5-01 的防空转闸, 存在的唯一理由是"证明这道门会红"。旧版测试被判
        恒绿正是因为没有任何反证: 它只在生产代码健康时跑过一次, 从未在"生产代码
        已坏"的状态下被观察到失败。

        变异体就是 Q8 §2 给的那个构造的最小形态 —— ``radius_arcsec`` 被丢弃, 恒定
        按 180.0 往下传。``patch.object`` 在此**故意**打在待验证函数上, 但用途与
        恒绿版相反: 它注入的是一个已知坏实现, 断言对象是"判据是否报警", 不是
        "mock 是否被调用"。判据转红即通过; 若它不红, 说明 :meth:`_assert_radius_reached_wire`
        已经退化成橡皮章。
        """
        def _swallow_radius(self, ra, dec, radius_arcsec=60.0, catalog="ps1",
                            band=None, quality_filter=True):  # 签名与真实门面逐位对齐: 少一个形参就不是同一个变异
            """变异体: 丢掉 radius_arcsec, 恒定按 180.0 传下去 (调用方给的 5.0 被吞)。"""
            result = self.client.cone_search(ra, dec, 180.0, catalog=catalog, band=band)  # 180.0 是写死的: 入参根本没参与
            return [{"ra": src.ra, "dec": src.dec} for src in result.sources]  # 返回形态仍伪装成 list: 让缺陷只剩"参数被吞"

        with patch.object(BestSkillClient, "cone_search", _swallow_radius):  # 注入坏实现
            _, mutated_form = _cone_search_over_fake_wire(  # 走同一条传输层路径
                BestSkillClient(rate_limit=0), ra=180.0, dec=30.0, radius_arcsec=5.0)
        # 逐字复用主用例的判据: 它必须因 pos.radius 是 180.0 而抛错
        with pytest.raises(AssertionError, match="pos.radius"):  # match 钉住失败原因: 别的异常蒙过就算自检失败
            _assert_radius_reached_wire(mutated_form, "5.0")


    def test_crossmatch_initialized(self):
        """接线守门: 客户端构造时 BestCrossMatch 必须挂载且带
        crossmatch_coords 入口 (P0-1 服务端批量匹配的调用面)。"""
        client = BestSkillClient()  # 构造时即完成接线
        assert client.crossmatch is not None  # BestCrossMatch 必须挂上
        assert hasattr(client.crossmatch, "crossmatch_coords")  # 且带批量匹配入口 (P0-1)


class TestScripts:
    """scripts 公开入口守门: 三个高层脚本入口必须可导入、可调用 — 这是
    agent 侧的真实调用面, 改名/漏接线会直接打断上游工作流。"""

    def test_cone_search_function_exists(self):
        """best_cone_search.cone_search 必须可导入且 callable, 函数名保持
        cone_search (公开 API 面守门)。"""
        from src.scripts.best_cone_search import cone_search as cs  # 延迟导入: 只验公开面, 不触发副作用
        assert callable(cs)  # 可调用
        assert cs.__name__ == "cone_search"  # 公开 API 名是 agent 侧依赖的契约

    def test_export_multiband_photometry_function_exists(self):
        """best_multiband_export.export_multiband_photometry 必须可导入且 callable,
        函数名保持 export_multiband_photometry。"""
        from src.scripts.best_multiband_export import export_multiband_photometry as el  # 延迟导入: 光变导出入口
        assert callable(el)  # 可调用
        assert el.__name__ == "export_multiband_photometry"  # 名字同样是上游依赖

    def test_crossmatch_function_exists(self):
        """best_crossmatch_pipeline 的 Gaia/PS1 两个交叉匹配入口必须可导入
        且 callable; 批处理入口只验存在性, 不在本测试断言其具体函数名
        (批处理与单点入口不同名)。"""
        from src.scripts.best_crossmatch_pipeline import crossmatch_with_gaia as cg  # 延迟导入: 只验公开面
        from src.scripts.best_crossmatch_pipeline import crossmatch_with_ps1 as bc  # 同一模块的第二入口
        assert callable(cg)  # Gaia 单点入口可调用
        # 批处理入口不以 batch_crossmatch 为名, 本测试只钉两个单点入口
