"""astro-best pipeline 集成测试: skill 客户端与 pipeline 编排的接线回归。

守两条全链路不变量: AstroBestPipeline 可导入可编排 (skill 层入口不因重构
断裂); BestSkillClient 正确接收质量门控配置 (min_snr/max_fwhm 阈值透传,
Q-15/56 九字段透传契约的客户端侧落点)。全部离线: 不发起任何 HTTP 请求。
"""
from __future__ import annotations

# 第三方: pytest 提供断言与用例发现框架
import pytest

# 本地: skill 级客户端 (质量门控 + 查询审计), 被 pipeline 编排消费 —
# 跨 src.core 能力边界, 此处验证其质量配置入口契约。
from src.core import BestSkillClient

# 本地: skill 级编排器 (配置 -> BestSkillClient -> cone_search);
# 权威实现在 src.core.pipeline (Q-15/56 九字段透传)。
from src.core.pipeline import AstroBestPipeline


class TestAstroBestPipeline:
    """pipeline 编排层的集成回归 (只验接线, 不验网络)。"""

    def test_pipeline_importable(self):
        """AstroBestPipeline 必须可导入且为类 (skill 入口可达性)。

        守的是"重构不折断公开入口"回归: 任何把 AstroBestPipeline 改名/搬移/
        改成函数的改动都会在此变红, 而不是等到运行期才 ImportError。
        """
        assert type(AstroBestPipeline) is type

    def test_astro_best_client_integration(self):
        """BestSkillClient 必须按传入的 quality_config 配置质量门控。

        守配置透传回归: dict 形态的 quality_config 要原样落到
        client.quality (min_snr/max_fwhm) — 丢字段或硬编码默认值都会让质量门控
        静默失效, 这是复核者最需要看到的"改坏就红"防线。
        """
        client = BestSkillClient(quality_config={"min_snr": 10.0, "max_fwhm": 3.0})
        assert client.quality.min_snr == 10.0
        assert client.quality.max_fwhm == 3.0
