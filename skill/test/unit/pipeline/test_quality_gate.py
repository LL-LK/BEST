"""astro-best core 门控与客户端的最小回归集 (真实 BEST API 口径)。

与 test_core.py 的分工: 本文件是精简冒烟集, 只钉 QualityGate 放行/拦截
边界、光变点数门控与 BestSkillClient 的质量配置透传; 完整编排行为在
test_core.py。全部离线, 不打站点。
"""
from __future__ import annotations

# 本地: skill 编排层 (QualityGate 质量门控 Q-14/15/56, BestSkillClient
# 配置透传) + 光变容器 (点数门控的输入) + models 行模型 (测试数据构造)
from src.core import BestSkillClient, QualityGate
from src.models import BestSource
from src.multiband_photometry import BestMultiBandPhotometry


class TestQualityGate:
    """QualityGate 冒烟守门: 阈值透传、好源放行、低 SNR 拦截、光变点数。"""

    def test_init(self):
        """自定义阈值必须原样透传 (min_snr/max_fwhm 双键都要接住)。"""
        qg = QualityGate(min_snr=10.0, max_fwhm=3.0)                                       # 双阈值都显式给: 只给一个键时另一键会被静默吞掉也无从发现
        # 双键都断: 只断一个的话, 另一个键在构造时被静默吞掉也无从发现
        assert qg.min_snr == 10.0                                                                   # 下限必须原样透传
        assert qg.max_fwhm == 3.0                                                                   # 上限同样要接住, 漏一个就是静默丢配置

    def test_validate_good_source(self):
        """好源守门: SNR/FWHM/class_star/星等都过线时必须放行 (门控存在的
        前提是"好数据过得去")。"""
        qg = QualityGate()                                                                          # 默认阈值: 放行用例要用默认门限
        # 参数取明显过线的值 (snr=20 远高于默认 min_snr=5), 这样一旦门控被改成
        # 无条件 fail-closed, 这条"放行"用例会第一个红, 挡住过度拦截
        src = BestSource(source_id="T1", snr=20.0, fwhm=2.0, class_star=0.95,
                         magnitudes={"r": 15.0})
        report = qg.validate_source(src)                                                            # 走真实校验入口
        assert report["passed"]   # 门控的前提是好数据过得去, 误杀即回归

    def test_validate_bad_snr(self):
        """低 SNR 拦截守门: 必须拒之且报告点名 min_snr 检查项失败
        (可诊断性 — 拦截理由必须可追溯)。"""
        qg = QualityGate(min_snr=10.0)                                                          # 显式抬高下限: 让"低 SNR 必拒"这条可判定
        # snr=3 明确低于阈值 10, 不留边界歧义: 这条要验的是"该拒就拒",
        # 边界值归 test_core.py 的完整编排集管
        src = BestSource(source_id="T1", snr=3.0)
        report = qg.validate_source(src)                                                            # 走真实校验入口
        assert not report["passed"]   # snr=3 明确低于阈值 10, 该拒就拒
        # 点名具体检查项而不只是断言 not passed: 无差别地拒一切同样能过上面
        # 一条, 报告点名才能让排障知道该看哪个字段
        assert any(not c["passed"] for c in report["checks"] if c["check"] == "min_snr")

    def test_validate_multiband_photometry_empty(self):
        """空光变拦截守门: 0 个历元不得通过 min_points 门控。"""
        qg = QualityGate()                                                                          # 默认阈值: 光变点数门控的默认值
        lc = BestMultiBandPhotometry(source_id="TEST")
        report = qg.validate_multiband_photometry(lc, min_points=3)                                 # 空光变送进门控: 0 历元必须被拦
        assert not report["passed"]   # 0 个历元做周期分析无本之木, 必须拦

    def test_validate_multiband_photometry_ok(self):
        """点数达标守门: 5 个历元 ≥ min_points=3 必须放行 (门控只拦不够的,
        不拦"够多"的)。"""
        qg = QualityGate()                                                                          # 默认阈值
        # 5 与阈值 3 留出两档余量: 若门控误写成 "点数 > min_points 才放行",
        # 恰好等于阈值的正常光变会被拦下, 用 3 造不出这个差异
        points = [BestSource(source_id=f"T{i}") for i in range(5)]
        lc = BestMultiBandPhotometry(source_id="TEST", points=points)
        report = qg.validate_multiband_photometry(lc, min_points=3)                                 # 达标光变送进门控
        assert report["passed"]   # 门控只拦"不够的", 不拦"够多的"


class TestBestSkillClient:
    """BestSkillClient 冒烟守门: 质量配置透传与 crossmatch 接线。"""

    def test_init(self):
        """quality_config 部分键守门: 只传 min_snr 时必须覆盖默认值, 未传的
        键 (max_fwhm) 回退默认 — 部分配置不得让构造失败。"""
        client = BestSkillClient(quality_config={"min_snr": 15.0})                                  # 只传一个键: 部分配置不得让构造失败
        # 15.0 高于默认 5.0, 断的是"真覆盖了"而非"恰好等于默认"; 只传一个键
        # 不报错是这条的另一半契约, 冒烟集不重复断 max_fwhm 的具体值
        assert client.quality.min_snr == 15.0

    def test_crossmatch_available(self):
        """接线守门: crossmatch 实例必须挂载且暴露 crossmatch_coords
        (P0-1 服务端批量匹配入口的调用面)。"""
        client = BestSkillClient()                                                                  # 默认构造: 接线守门不需要任何配置
        assert hasattr(client.crossmatch, "crossmatch_coords")
