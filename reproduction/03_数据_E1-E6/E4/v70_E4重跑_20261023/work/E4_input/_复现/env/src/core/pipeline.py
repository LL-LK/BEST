"""src.core.pipeline — Skill-level workflow orchestrator.

能力边界: AstroBestPipeline: skill 级编排 (配置全量透传 → BestSkillClient → cone_search)。边界: 配置**非全量**透传 —— AstroBestConfig 实有 11 字段, 本模块只读 6 个
    (min_snr/max_fwhm/base_url/rate_limit/timeout/max_retries), api_token 已按 SA-P2-3
    停透传, output_dir/log_level/quality_filter/tap_url 未取 (Q-15/56 只修了「静默丢弃」); 兼容 dict 与 AstroBestConfig 两种配置形态。
白盒锚点: references/ALGORITHM-SPEC.md §2 (pipeline 锚点)。
"""
from __future__ import annotations

# 标准库: 类型标注 (配置兼容 dict 与 dataclass 两种形态)
from typing import Any, Optional

# 本地: 复用 skill 级客户端 (质量门控 + 查询审计上下文), pipeline 只做编排
from src.core import BestSkillClient


def _quality_from(config: Any) -> dict:
    """兼容面: config 可为 dict 或 AstroBestConfig (dataclass) — 统一取质量阈值。

    AstroBestConfig 既有 min_snr/max_fwhm 字段 (0.x 兼容面), dict 走
    get(); 其余鸭子类型经 getattr 容错, 缺省值 5.0 与 QualityGate 一致。
    """
    if isinstance(config, dict):  # 分两种载体取阈值: dict 走 get, 数据类走 getattr
        min_snr = config.get("min_snr", 5.0)  # dict 载体: 缺键即用 QualityGate 同款缺省
        max_fwhm = config.get("max_fwhm", 5.0)  # 与质量门控同款缺省: 两侧默认值漂移会让门控形同虚设
    else:
        min_snr = getattr(config, "min_snr", None)  # 鸭子类型: 取不到留 None, 由 return 处兜底
        max_fwhm = getattr(config, "max_fwhm", None)  # 鸭子类型取不到就留 None: 统一交给 return 处兜底
    return {
        "min_snr": min_snr if min_snr is not None else 5.0,  # 显式 None 才兜底: 0 是有意阈值, 不能被当缺省覆盖
        "max_fwhm": max_fwhm if max_fwhm is not None else 5.0,  # 同上口径: 半高宽 0 像素是合法配置, 同样不回落
    }


def _config_field(config: Any, name: str, default: Any) -> Any:
    """从 dict 或 AstroBestConfig 取字段 (缺省 default)。"""
    # SIM108: 三元表达式替 if-else 块 (两种配置载体的同一取值语义)
    value = (config.get(name, default) if isinstance(config, dict)  # 三元替 if-else 块: 两种载体的取值语义本就只有一条
             else getattr(config, name, None))  # 两种载体同一取值语义 (SIM108)
    return default if value is None else value  # None 才回落 default: 0/空串是显式取值, 不覆盖


class AstroBestPipeline:
    """Skill 级工作流编排器 (配置 -> BestSkillClient -> cone_search)。

    不变量 (Q-15/56): 客户端会话字段必须逐项显式透传 (base_url / rate_limit /
    timeout / max_retries); 漏掉任何一项都会静默退回客户端缺省值, 调用方拿到
    的是"看着配过、其实没生效"的会话。
    """

    def __init__(self, config: Optional[Any] = None) -> None:
        """构造编排器; config 可为 dict 或 AstroBestConfig (缺省 None = 全默认)。

        Args:
            config: 调用方配置; 鸭子类型读取, 缺字段回退 QualityGate/BestClient
                同款默认值。
        """
        qc = _quality_from(config)  # 质量门控阈值在此归一, 下游只认 dict 形态
        # 会话字段全量透传 (Q-15/56): 漏传任一项即静默退回客户端缺省值。
        # SA-P2-3: api_token 不再透传 — BestSkillClient 的 token 形参已删
        # (BestClient 无 token 通道, 那是死路; 配置层字段保留供 doctor 报告)
        self.client = BestSkillClient(  # 客户端只此一个, pipeline 不另建会话
            tap_url=str(_config_field(config, "base_url", "") or ""),  # 端点取自配置: 空串表示用客户端缺省端点, 不在此硬编码
            quality_config=qc,  # 阈值已归一成字典: 下游只认这一种形态
            rate_limit=float(_config_field(config, "rate_limit", 2.0)),  # 限流秒数取自配置: 交给客户端的同一把时钟
            timeout=int(_config_field(config, "timeout", 120)),  # 超时秒数取自配置: 显式转整数, 免得字符串配置穿透
            max_retries=int(_config_field(config, "max_retries", 3)),  # 重试次数取自配置: 编排层不再自带重试口径
        )

    def search(self, ra: float, dec: float, radius_arcsec: float = 60.0) -> list[dict]:
        """锥形检索编排: 委派 BestSkillClient.cone_search (质量门控由 pipeline 配置透传)。"""
        return self.client.cone_search(ra, dec, radius_arcsec, quality_filter=True)  # 默认开质量门控
