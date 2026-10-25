"""src.core — BEST skill 级核心层 (质量门控 + 客户端封装)。

职责划分:
  - ``QualityGate``: fail-closed 质量门控 — 逐项检查 SNR/FWHM/class_star/
    星等, 无任何指标可判时判不过 (Q-14)。
  - ``BestSkillClient``: 在 ``src.client`` 之上包一层质量过滤与查询审计,
    不依赖 pybest, 是独立自洽的 skill 实现。
  - 编排入口 ``AstroBestPipeline`` 与领域后处理 ``BestProcessor`` 分别见
    ``src/core/pipeline.py`` 与 ``src/core/source_postprocess.py``。
"""
from __future__ import annotations

import logging
from typing import Any, Optional

# 本地: client 层持有 REST 会话与锥检索实现; crossmatch/multiband_photometry
# 提供领域对象。本模块只做门控与编排, 不重复实现协议细节。
from src.client import BEST_BASE_URL, BestClient
from src.crossmatch import BestCrossMatch
from src.multiband_photometry import BestMultiBandPhotometry

logger = logging.getLogger(__name__)  # 模块级 logger: 本层不发请求, 只在门控与审计上留痕


class QualityGate:
    """BEST 源数据质量门控 (fail-closed 语义)。

    以 SNR / FWHM / class_star / 星等等阈值逐项判定; 任何一项不满足即整体
    不通过。当源上没有任何一项指标可判时, 同样判不通过 (Q-14) — "无法
    判定" 不等于 "合格", 防止无指标幻影源被静默放行进入下游。
    """

    def __init__(self, min_snr: float = 5.0, max_fwhm: float = 5.0) -> None:
        """初始化质量门控阈值。

        Args:
            min_snr: 最低信噪比; 低于此值的源判不过。
            max_fwhm: 最大 FWHM (星像半高全宽); 大于此值的源判不过。
        """
        self.min_snr = min_snr  # 阈值挂实例: 不同客户端可以各持一套门控口径
        self.max_fwhm = max_fwhm  # 阈值同样挂实例: 不同客户端可各持一套门控口径

    def validate_source(self, source: Any) -> dict[str, Any]:
        """对单个 BEST 源执行质量门控, 返回逐项判定明细。

        四个检查项 (任何一项不满足, ``passed`` 即为 False):
          1. ``min_snr``: 信噪比低于 ``min_snr`` 判不过 — 低 SNR 源的坐标
             与星等误差大, 放进交叉匹配会污染下游结果。
          2. ``max_fwhm``: FWHM 超过 ``max_fwhm`` 判不过 — 星像越胖越可能
             是混合源/坏源, 不宜当标准星用。
          3. ``class_star``: 点源分类值低于 0.8 判不过 — 该值越低越可能是
             星系或伪影而非点源。
          4. ``has_magnitude``: 所有波段星等均缺失判不过 — 没有测光的源
             无法参与任何星等相关下游。

        Q-14 fail-closed 语义: 若源上四个指标一个都不存在, 追加
        ``no_metrics`` 项并判不过 — 此处放行就是让无指标幻影源进下游, 宁可
        误杀不可误放。

        Args:
            source: BestSource 对象 (鸭子类型; 允许缺字段, 缺项跳过)。

        Returns:
            ``{"passed": bool, "checks": [{"check": str, "passed": bool}]}``;
            ``checks`` 记录每一项的判定明细, 供人工审计复核。
        """
        checks = []    # 逐项明细而非单一 bool: 复核者要能看出卡在哪一项
        passed = True  # 起手 True 再逐项打 False: 任一项不过就再也回不去
        # 检查项 1 (min_snr): 信噪比下限; 字段缺失或为 None 时跳过该项
        if hasattr(source, "snr") and source.snr is not None:  # hasattr + is not None 双判: 缺字段与字段为 None 是两种"不可判"
            if source.snr < self.min_snr:  # 低于下限即不过: 低信噪比源的坐标误差会污染交叉匹配
                checks.append({"check": "min_snr", "passed": False})  # 记明细再翻总判: 复核者要看出卡在哪一项
                passed = False
            else:
                checks.append({"check": "min_snr", "passed": True})  # 过阈也要记一条: 缺项会让审计看不出这一项判过
        # 检查项 2 (max_fwhm): 星像半高全宽上限; 越胖越可能是混合/坏源
        if hasattr(source, "fwhm") and source.fwhm is not None:  # 半高全宽同样双判: 缺字段与字段为空是两种不可判
            if source.fwhm > self.max_fwhm:  # 越胖越可能是混合源: 超过上限即不过
                checks.append({"check": "max_fwhm", "passed": False})  # 记明细并翻总判: 判定与审计在同一步完成
                passed = False
            else:
                checks.append({"check": "max_fwhm", "passed": True})  # 过阈记一条: 审计需要看到这一项确实判过
        # 检查项 3 (class_star): 点源分类值下限 0.8 (低于此更像星系/伪影)
        if hasattr(source, "class_star") and source.class_star is not None:  # 点源分类值双判: 缺字段与 None 都不能当合格
            if source.class_star < 0.8:  # 严格小于才判不过: 恰好 0.8 的点源应当放行
                checks.append({"check": "class_star", "passed": False})  # 低于 0.8 即不过: 该值越低越可能是星系或伪影
                passed = False
            else:
                checks.append({"check": "class_star", "passed": True})  # 达标记一条: 与不过分支成对, 审计口径才完整
        # 检查项 4 (has_magnitude): 至少一个波段有有效星等 (全缺失判不过)
        if hasattr(source, "magnitudes") and source.magnitudes:  # 真值判断顺带排掉空 dict: 空容器同样算"没有测光"
            # 至少一个有效星等 (None 不算测光)
            valid_mags = [v for v in source.magnitudes.values() if v is not None]  # 只算非空值: 星等位为 None 等于没测光, 不参与判定
            if not valid_mags:  # 全波段皆空即不过: 没有测光的源无法参与星等相关下游
                checks.append({"check": "has_magnitude", "passed": False})  # 记明细并翻总判: 与其余三项同构
                passed = False
            else:
                checks.append({"check": "has_magnitude", "passed": True})  # 至少一个有效值即过: 判定标准是存在性而非个数
        # Q-14: 无任何质量指标可判时 fail-closed: 此处放行就是让幻影源进下游
        if not checks:  # 判据是"一项都没判过": 缺指标即不可判, 不可判即不过 (Q-14)
            checks.append({"check": "no_metrics", "passed": False})  # 无任何指标可判即判不过: 无法判定不等于合格
            passed = False
        return {"passed": passed, "checks": checks}  # 同构返回: 与 validate_multiband_photometry 共用一套审计消费面

    def validate_multiband_photometry(self, lc: BestMultiBandPhotometry, min_points: int = 3) -> dict[str, Any]:
        """按测光点个数校验多波段容器 (点太少不足以做任何统计判定)。

        注意: ``n_points`` 是 points 个数 (同一次检索返回的源个数),
        **不是观测历元数** — BEST 无时序, 不存在历元概念。

        Args:
            lc: BestMultiBandPhotometry 对象。
            min_points: 最少测光点数。

        Returns:
            ``{"passed": bool, "checks": [{"check": "min_points", ...}]}``;
            与 validate_source 返回同构, 便于统一审计。
        """
        passed = lc.n_points >= min_points  # n_points 是源个数不是历元数: BEST 无时序, 别当测光变暗曲线读
        return {"passed": passed, "checks": [{"check": "min_points", "passed": passed}]}


class BestSkillClient:
    """带质量门控的 BEST skill 客户端 (src.client 的薄封装)。

    不依赖 pybest — 这是 skill 内独立自洽的实现; 会话参数 (rate_limit/
    timeout/max_retries) 全量透传, 并挂接 QueryContext 查询审计。
    """

    DEFAULT_BASE_URL = BEST_BASE_URL  # 直接引用常量而非复制字面量: 基地址只该有一处真值
    # BEST 无 TAP 服务；此键名只是旧调用面别名，必须指向真实基地址
    # (best.astro.tsinghua.edu.cn 经核实无 A 记录)。
    DEFAULT_TAP_URL = BEST_BASE_URL  # 旧调用面别名: 键名保留, 但值必须指向真实基地址

    def __init__(self, tap_url: str = "", quality_config: Optional[dict] = None,
                 rate_limit: float = 2.0, timeout: int = 120, max_retries: int = 3) -> None:  # 会话参数全量透传: 少透传一个字段, 配置里的那一项就静默失效
        """构造 skill 级客户端; 会话参数全量透传给 BestClient。

        Args:
            tap_url: 旧调用面的 TAP 门面地址; 为空时回退 DEFAULT_BASE_URL。
            quality_config: 质量门控阈值覆盖 (min_snr/max_fwhm)。
            rate_limit: 请求间隔 (秒); Q-15/56 要求透传, 不再静默丢弃。
            timeout: 单请求超时 (秒); Q-15/56 要求透传。
            max_retries: 最大重试次数; Q-15/56 要求透传。

        Note:
            SA-P2-3: 旧签名有 ``api_token`` 形参并存入 ``self.api_token``, 但
            BestClient 没有 token 通道 (认证走 BestAuth Django session), 该值
            存而不用 — env ``BEST_API_TOKEN`` -> AstroBestConfig.api_token ->
            本处的全链是死路, 已删。配置层的 api_token 字段保留 (doctor 的
            token_configured 报告消费它; static/core/workflow.md 已声明它
            "不是凭据来源")。
        """
        # tap_url 兼容旧调用面 (清华 TAP 门面); 缺省时默认使用 NADC 官方 REST 基地址 BEST_BASE_URL。
        # Q-15/56: rate_limit/timeout/max_retries 全量透传: 丢一个字段, 配置里
        # 那一项就静默失效, 调用方看不到任何报错。
        self.client = BestClient(  # 只建一个底层客户端: 会话与限流时钟因此全实例共享
            base_url=tap_url or self.DEFAULT_BASE_URL,  # 空串回落缺省基址: 旧调用面给了门面地址就用它
            rate_limit=rate_limit,  # 限流秒数下传: 不在本层另设时钟, 免得两把锁互相绕开
            timeout=timeout,  # 超时秒数下传: 与底层取同一口径
            max_retries=max_retries,  # 重试次数下传: 重试层只在底层存在一处
        )
        qc = quality_config or {}  # or {} 兜底: None 与 {} 两种传法收敛成同一条路径
        self.quality = QualityGate(  # 缺省回落 5.0: 与 QualityGate 自身缺省一致, 免得两处默认值漂移
            min_snr=qc.get("min_snr", 5.0),  # 阈值取自配置字典: 缺省 5.0 与门控自身缺省一致
            max_fwhm=qc.get("max_fwhm", 5.0),  # 同上口径: 两处默认值漂移会让门控形同虚设
        )
        self.crossmatch = BestCrossMatch(self.client)  # 交叉匹配对象复用同一客户端: 不另开会话, 节流才生效
        # Q-52: provenance 载体接线 (QueryContext.record 原生产零调用, 现由本客户端喂服)
        # 函数内延迟导入: src.scripts 是 CLI 层, 模块加载期引入会形成
        # core -> scripts -> client 的历史导入环; 推迟到实例化时再导入,
        # 保证 import src.core 本身不拖拽 CLI 依赖。
        from src.scripts.context import QueryContext

        self.context = QueryContext()  # 每实例一个上下文: 审计按实例隔离, 不跨实例串记录

    def audit_summary(self) -> dict[str, Any]:
        """查询审计摘要 (QueryContext.summary 的可读出口)。

        读侧出口: 记录侧 record() 每次查询都被喂服, 没有读出口的话, "一共回了
        多少源、覆盖哪些天区" 事后无法回答。
        """
        return self.context.summary()  # 直通 summary: 读侧出口不加工, 免得审计口径出现第二套

    def audit_history(self, max_records: int = 100) -> list[dict]:
        """查询审计历史 (超预算时按比例摊薄的展示副本, 源记录不改)。"""
        return self.context.truncate(max_records)

    def cone_search(self, ra: float, dec: float, radius_arcsec: float = 60.0,
                    catalog: str = "ps1", band: Optional[str] = None,  # 波段可空: 缺省不限波段, 整表测光一并返回
                    quality_filter: bool = True) -> list[dict]:  # 门控默认开: skill 层的存在意义就是替调用方挡掉坏源
        """锥形检索 + 可选质量门控过滤。

        Args:
            ra: 赤经 (度, ICRS)。
            dec: 赤纬 (度, ICRS)。
            radius_arcsec: 检索半径 (角秒)。
            catalog: 目标星表 (ps1/std/stripe82/gaia_dr3 等)。
            band: 可选波段过滤。
            quality_filter: 是否对每个源跑质量门控; 不过的源直接剔除。

        Returns:
            源 dict 列表; 开启 quality_filter 时每个 dict 附带 ``quality``
            判定明细 (复核者可见每个源为何被保留)。
        """
        result = self.client.cone_search(ra, dec, radius_arcsec, catalog=catalog, band=band)  # 检索本体全权交给 client
        # Q-52: 查询审计入上下文 (记录真实计数; truncate 只影响展示视图)
        self.context.record("cone_search", {"ra": ra, "dec": dec,  # 审计入上下文: 记真实计数, 摊薄只发生在展示视图上
                                            "radius_arcsec": radius_arcsec,  # 半径入审计: 半径变了返回集就变, 复核时要能看见
                                            "catalog": catalog},  # 星表入审计: 同参数不同表的结果不可混用
                            len(result.sources))  # 计数取真实取回数: 不是过滤后的条数, 免得审计口径失真
        sources = []  # 另建输出列表: 只收过了门控的源
        for src in result.sources:  # 逐源判定: 门控是行级变换, 不改写底层结果
            report = None  # 缺省 None: quality_filter=False 时没有报告可附, 也不该伪造一个
            if quality_filter:  # 门控可关: 关掉时没有报告可附, 也不该伪造一个
                # 同一 source 只跑一次门控: 跑两次可能给出不一致的结论, 报告与去留会自相矛盾
                report = self.quality.validate_source(src)  # 一次判定两处复用: 既决定去留, 又作为报告附回输出
                if not report["passed"]:  # 不过即跳过: 该源既不落盘也不计数
                    continue
            d = src.to_dict()  # 转成裸行: 输出面是 dict 列表, 不是域对象
            if quality_filter:  # 同一分支复判: 与上面同条件, 避免报告挂错行
                d["quality"] = report  # 报告随行返回: 调用方看得到每个源为何被留下, 不必重跑门控
            sources.append(d)  # 只收过了门控的源: 不过的已 continue, 既不落盘也不计数
        return sources
