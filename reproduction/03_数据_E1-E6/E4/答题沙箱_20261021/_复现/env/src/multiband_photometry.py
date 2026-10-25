"""src.multiband_photometry — Multi-band static photometry container for BEST sources.

能力边界: BestMultiBandPhotometry: 多波段静态测光容器 (n_points/magnitudes/bands/summary)。BEST 是均一定标星表 (一行 = 一个源的一套定标后测光值, 全库无 MJD/观测时刻列), 本容器**不是时间序列**; points 中每个点是同一次锥搜返回的一个源 (BestSource)。边界: 未识别列必须显式失败 (Q-29), 不返回'看起来成功'的空结果; 点计数供 QualityGate.min_points 消费。
白盒锚点: references/ALGORITHM-SPEC.md §2 (multiband_photometry 锚点)。

【权威学术来源锚定】
  - NADC China-VO BEST REST API 规范 (2023): 多批次/多波段测光数据检索与导出口径, 公式定位: 规范全文。规范引用（无 DOI）。
  - 开源依赖: 无第三方数值依赖 (纯 stdlib + astropy 系表容器可选)。
Rule 9 状态: [VERIFIED_ALGO]（标准基准算法; 物理可解释输出, 无伪概率打分）。
"""
from __future__ import annotations

# 标准库: csv/io 在内存拼 CSV 再一次性落盘, json 序列化, math 判非有限值,
# os/pathlib 做路径锚定与父目录创建
import csv  # 标准库: CSV 写出, 固定表头 + 一行一波段的长表
import io  # 标准库: 内存缓冲, 先拼全文再一次性原子落盘
import json  # 标准库: JSON 序列化 (JSON 导出分支)
import logging  # 标准库: 检索与导出过程的日志出口
import math  # 标准库: 非有限值判定 (float("nan")/float("inf") 不抛异常, 靠它兜住)
import os  # 标准库: os.pardir 判定, 导出路径穿越防护
from pathlib import Path  # 标准库: 输出路径锚定与父目录创建
from typing import Any, Optional  # 标准库: 摘要字典与可缺参数标注

# 本地: BestClient 提供锥形检索 (跨网络能力边界); sanitize_cell 防 CSV
# 公式注入; BestSource 为测光点数据模型; atomic_write_text 是全包唯一的
# 原子落盘实现 (Rule 12 防线二)
from src.client import BestClient  # 锥形检索入口: 本模块唯一触网处
from src.csv_safety import sanitize_cell  # 本地唯一消毒实现: 每格过一遍 (Q-06)
from src.download_artifacts import STATUS_EMPTY, STATUS_OK  # 行状态词表的唯一事实源: 容器侧不另造一套 empty 语义
from src.models import (  # 本地: 测光点数据模型 + 波段→物理列反查所需的权威映射表
    CATALOG_ALIASES,  # 星表旧拼写别名: 反查前先归一, 与 from_row 的查表口径同源
    CATALOG_MAG_COLUMNS,  # 权威波段表 (列名 -> 波段字母): CSV 归因列的唯一来源
    BestSource,  # 测光点数据模型 (一个点 = 一个源, 非历元)
)
from src.scripts.guards import atomic_write_text  # 全包唯一原子落盘实现 (Rule 12 防线二)

logger = logging.getLogger(__name__)  # 模块级 logger: 命中与落盘都留痕, 便于事后核对导出了什么


def _guard_output(path):
    """规范化输出路径: 拒绝父目录引用穿越 (安全审计要求)。

    Args:
        path: 调用方给的原始输出路径 (``str`` 或 ``Path`` 均可)。

    Returns:
        解析后的绝对 ``Path``; 含父目录引用时直接拒绝。

    Raises:
        ValueError: 路径任一段是 ``..`` — 导出目录一律由本包内约定,
            开放穿越会让调用方把结果写到星表数据之外。
    """
    p = Path(path)  # 收 str|Path 两种入参: CLI 与库调用方都直接传
    if os.path.pardir in p.parts:  # 只查字面 "..": 先 resolve 会展开符号链接, 掩盖越界写
        raise ValueError(f"error: --output must not contain {os.path.pardir!r} traversal")  # 抛而非夹回: 开放穿越会把结果写到星表数据之外
    return p.resolve()  # 解析后才交给原子写: 落点唯一, 便于回显绝对路径


def _magnitude_source_column(catalog: str, band: str) -> str:
    """把波段标签反查成该星表**真实发布**的星等列名 (CSV 归因用)。

    :func:`src.protocol.magnitude_column` 是正查 (波段 -> ``{表}.{列}`` 表单键,
    供构造查询用); CSV 要的是**响应列的裸名**: ``ps1`` 的 r 波段是 ``rpsf``,
    ``landolt`` 的是 ``vmag``, ``gaia_dr3_18`` 的是 ``phot_rp_mean_mag``。
    只落波段字母会让同一列在不同星表下混成一批无法归因的数 (G1-06) ——
    下游按 band 列直接混算, 等于把不同测光系统的星等当同一量。

    别名先过 ``CATALOG_ALIASES`` 归一, 与 ``BestSource.from_row`` 的查表
    口径逐字一致; 复用 models 的再导出而不新开一条 ``src.protocol`` 依赖边,
    免得同一张映射表出现第二条 import 路径。

    Args:
        catalog: 星表 id 或旧拼写别名 (大小写不敏感)。
        band: 波段标签 (大小写不敏感)。

    Returns:
        该星表发布的裸列名; 该星表**没有**权威波段表时 (``from_row`` 走了
        首字母启发式回退) 返回空串 —— 那种行的真实列名只能从
        :meth:`to_json` 的 ``raw_data`` 取, 宁留空也不猜一个列名顶上。
    """
    name = str(catalog or "").lower()  # 归一一次: 别名表与波段表的键都是小写 id
    columns = CATALOG_MAG_COLUMNS.get(CATALOG_ALIASES.get(name, name), {})  # 权威表反查, 不按 f"{band}psf" 拼名
    for column, label in columns.items():  # 逐项比对标签: 标签相等才认, 不做前缀猜测
        if label == str(band or "").strip().lower():
            return column
    return ""  # 无权威条目即如实留空: 猜出来的列名会让产物看似可归因, 实则不可


class BestMultiBandPhotometry:
    """BEST 源的多波段静态测光容器。

    BEST 是均一定标标准星数据库: 一行 = 一个源的一套定标后测光值,
    没有观测时刻列 (全库无 MJD, 唯一含 epoch 的 gaia_dr3_18_ref_epoch
    是 Gaia 天体测量参考历元, 不是观测时刻)。本类把一次锥形检索取回的
    测光信息包装成"多波段容器"供导出与下游消费; ``points`` 中每个点是
    同一次检索返回的一个源 (BestSource), **不是历元** — 拿它当光变曲线
    用是科学误用 (E3 语义轴 A 的典型错误)。
    """

    def __init__(
        self,
        source_id: str,                                                                          # 源标识: 测光记录的归属锚, 后续按它回溯查询
        points: Optional[list[BestSource]] = None,                                                # 该源下的测光点: 缺省空列表, 下游不必判空
        band: Optional[str] = None,                                                             # 波段可空: 缺省表示不限波段, 整表测光一并返回
    ) -> None:
        """直接构造容器: points 每点是一个**源** (BestSource), 不是历元 —— 本模块头把
            「把静态多波段测光讲成时序」列为头号科学误用, 行尾「光变点」措辞与之矛盾。

        Args:
            source_id: 源标识; 未检索到时调用方可给合成 ``POS_<ra>_<dec>``。
            points: 测光点列表 (每点是一个源, 非历元)。``None`` 归一为
                空列表, 使 ``n_points``/``bands`` 无需判空即可消费。
            band: 可选波段过滤标记, 仅作记录不参与筛点。

        构造本身不做校验也不联网, 因此本方法不抛异常。
        """
        self.source_id = source_id  # 原样留存: 未命中时调用方可给合成 POS_<ra>_<dec>
        self.points = points or []  # None 归一为空列表: n_points/bands 无需判空
        self.band = band  # 仅作记录, 不参与筛点 (契约如此, 见 docstring)

    @classmethod
    def from_position(
        cls,                                                                                        # 类方法: 从客户端一次取回该源的全部测光
        client: BestClient,                                                                         # 客户端: 锥检索与解析都经它
        ra: float,                                                                                  # 中心赤经(度): 值域由客户端入口校验
        dec: float,                                                                                 # 中心赤纬(度): 与赤经共同定位天区
        band: Optional[str] = None,                                                                 # 波段可空: 给了就按真实星等列过滤
        radius_arcsec: float = 3.0,                                                           # 匹配半径(角秒): 缺省三角秒, 与交叉匹配口径一致
        catalog: str = "ps1",
    ) -> BestMultiBandPhotometry:
        """按位置检索源并装配多波段测光容器。

        用锥形检索找到源并提取各波段星等。**"查不到"与"查询失败"走两条
        不同的分支**: 检索成功但锥区内无源时返回空容器 (source_id 退化为
        ``POS_<ra>_<dec>`` 形态, 只 warning 不抛 — 空结果由调用方判读);
        检索本身失败 (软错误/网络) 则显式抛 :class:`RuntimeError`, 绝不返回
        0 点容器 —— 那会被导出层落成"仅表头的成功空文件"。

        Args:
            client: BestClient 实例
            ra: RA (单位: 度)
            dec: Dec (单位: 度)
            band: 可选的波段过滤
            radius_arcsec: 检索半径
            catalog: 目标星表

        Returns:
            含源测光的 BestMultiBandPhotometry; 检索成功且锥区内无源时是
            0 点容器。

        Raises:
            RuntimeError: 锥形检索失败 (``result.success`` 为假)。错误码与
                原因进异常消息, 调用方据此判重试还是改输入。
        """
        result = client.cone_search(  # HTTP 调用点: 只取最近邻 (单历元星表, 一位置对应一源)
            ra=ra, dec=dec,                                                                         # 坐标透传
            radius_arcsec=radius_arcsec,                                                            # 半径
            catalog=catalog,                                                                        # 星表
            band=band,                                                                              # 单波段
            max_records=1,  # 只取最近邻: 单历元星表一个位置对应一个源
        )
        if not result.success:
            # 查询失败 ≠ 无源, 两条分支必须分开。此处早先与下面的"无源"分支
            # 合并, 于是站点一次软错误 (实跑: 故意错 base_url 前缀 → 底层
            # E_NO_SQLID, 会话压根没建成) 被如实误报成 "No source found at
            # RA=…", 日志与结论双双与事实相反 (G1-02 实跑证据) —— 比静默
            # 归零更坏: 下一个查日志的人会被带偏, 并据此下"天区为空"的结论。
            code = result.error_code or "E_BACKEND"  # 取客户端分类码: 消息措辞会随站点改版漂移, 码不会
            logger.error("Cone search FAILED at RA=%.4f, Dec=%.4f [%s]: %s",   # 错误分支独立文案: 绝不出现 "No source found"
                         ra, dec, code, result.error)
            raise RuntimeError(  # 显式失败 (Q-29): 0 点容器会被导出层落成"仅表头的成功空文件", 还被计成导出成功
                f"cone search failed at RA={ra:.4f} Dec={dec:.4f} [{code}]: "
                f"{result.error}"
            )
        if result.sources:  # 成功且有行才装配 (走到这里 success 已为真)
            src = result.sources[0]  # 只取一行: 多取会让 n_points 与"源个数"语义脱钩
            lc = cls(source_id=src.source_id, points=[src], band=band)  # 单元素 points: 与多点容器同口径
            logger.info(                                                                            # 逐源记一笔: 取数结果要可追溯到每个源
                "Multi-band photometry for %s: %d bands, SNR=%.1f",
                src.source_id, len(src.magnitudes), src.snr or 0,                                   # 源 id / 星等数 / SNR
            )
            return lc
        logger.warning("No source found at RA=%.4f, Dec=%.4f", ra, dec)  # 只警告不抛: 这里**确实查过**且确实无源
        return cls(source_id=f"POS_{ra:.4f}_{dec:.4f}", band=band)  # 合成 ID: 记录检索位置, 便于回溯

    @classmethod
    def from_client(
        cls,
        client: BestClient,
        source_id: str,
        band: Optional[str] = None,
        catalog: str = "ps1",
    ) -> BestMultiBandPhotometry:
        """按 source_id 检索多波段测光数据。

        仅支持 ``POS_<ra>_<dec>`` 形态的合成 ID (解析出坐标后转
        :meth:`from_position`)。

        P2-12: 其他 ID 形态**显式抛 ValueError** — 静默返回 0 点容器的话,
        ``best_multiband_export`` 会把它落盘成仅表头文件、导出"成功",
        调用方拿到一个看起来完好的空文件 (Q-29"未识别列须显式失败"的反例)。
        BEST 没有按 ID 检索的公开端点, 伪造数据更不行。

        Args:
            client: BestClient 实例
            source_id: 源标识 (必须是 ``POS_<ra>_<dec>`` 合成形态); 站点回
                空 source_id 时该合成 ID 会被保成容器的 ``source_id``
            band: 可选的波段过滤
            catalog: 目标星表

        Returns:
            含源测光的 BestMultiBandPhotometry

        Raises:
            ValueError: source_id 不是可解析的 ``POS_<ra>_<dec>`` 形态。
        """
        sid = str(source_id or "").strip()  # str+strip: 调用方可能给 None 或带空白
        # 前缀判别而非正则: 只接受本包自己造出来的合成 ID 形态,
        # 任何真实星表 ID 走不到这里 (BEST 无按 ID 检索端点)。
        if sid.startswith("POS_"):  # 前缀判别而非正则: 真实星表 ID 走不到这里
            parts = sid[len("POS_"):].split("_")
            # 恰好两段: RA/Dec 本身不含下划线, 多段即非本包造出的形态。
            if len(parts) == 2:  # 恰好两段: RA/Dec 不含下划线, 多段即非本包形态
                try:
                    ra, dec = float(parts[0]), float(parts[1])                                      # 解析 "ra,dec" 两段: band 走形参, 不进 ID
                except ValueError as exc:
                    # 转成 ValueError 统一抛出: 让"ID 不可解析"只有
                    # 一种失败形态, 便于 CLI 侧一处捕获。
                    raise ValueError(  # 统一失败形态: CLI 侧只需捕一处
                        f"unresolvable POS_ source_id {source_id!r}: {exc}"
                    ) from exc
                # 非有限值单独拦: float("nan")/float("inf") **不抛 ValueError**,
                # 上面那个 except 接不住, 于是 POS_nan_2.0 会一路把 NaN 坐标
                # 递进 cone_search (ConeSearchInput 不自校验, 注释明写"由调用方保证"),
                # 最后落成一条来自站点的含混软错误 —— 恰好是本函数下面那段
                # "显式失败 (Q-29)" 要防的结果: 静默产出垃圾而不是当场报错。
                if not (math.isfinite(ra) and math.isfinite(dec)):
                    raise ValueError(  # 显式失败: NaN/inf 坐标无法定位天区, 不拿它冒充坐标
                        f"non-finite coordinate in POS_ source_id {source_id!r}: "
                        f"ra={ra!r} dec={dec!r}"
                    )
                lc = cls.from_position(client, ra=ra, dec=dec, band=band,
                                       catalog=catalog)  # 星表透传
                # 保住调用方给的合成 ID: from_position 用站点的 source_id 建容器,
                # 而线上 ps1 的 ps1_source_id 实测就是**空串** —— 于是调用方
                # 辛苦解析出来的 POS_<ra>_<dec> 在这里被空串顶掉, 导出的 CSV
                # 首列整列为空, 血缘断在第一列 (G1 LIVE-2a 的真实形态)。
                # 只在站点确实没给出 id 时才回填: 站点给了真 id 就用它的,
                # 两处都是真实标识, 不存在编造。H4-1 实跑于 2026-10-05。
                if not lc.source_id:
                    lc.source_id = sid  # 合成 ID 是本包自己造的, 形态已在本方法开头校验过
                return lc
        # 兜底抛错即 P2-12 的"显式失败": 静默返回空容器会被导出层
        # 落成仅表头的 CSV, 对外看是成功的空文件 (Q-29 反例)。
        raise ValueError(  # 显式失败 (Q-29): 静默空容器会落成"仅表头的成功空文件"
            f"unrecognized source_id {source_id!r}: only synthetic "
            f"'POS_<ra>_<dec>' ids are resolvable (BEST publishes no "
            f"by-id lookup endpoint)"
        )

    @property
    def n_points(self) -> int:
        """测光点计数属性 (points 个数 = 源个数, **不是观测历元数** — BEST 无时序; 供 QualityGate.min_points 门控消费)。"""
        return len(self.points)

    @property
    def magnitudes(self) -> dict[str, float]:
        """跨所有测光点合并波段星等 (后点覆盖先点的同波段值)。

        Returns:
            ``{波段: 星等}`` 字典; 同波段多点时取 points 里靠后者,
            因为单历元星表的同波段重复只可能是重复行而非真时序。
        """
        mags: dict[str, float] = {}  # 合并口径: 同波段后点覆盖先点
        for p in self.points:                                                                       # 逐点
            # update 而非 setdefault: 单历元下"后点"不含更多信息,
            # 覆盖可保证结果只依赖 points 顺序, 便于回放比对。
            mags.update(p.magnitudes)  # update 而非 setdefault: 结果只依赖 points 顺序, 便于回放
        return mags

    @property
    def bands(self) -> list[str]:
        """可用波段列表 (取自合并得到的 magnitudes 的键)。

        Returns:
            合并得到的星等的键顺序列表; 顺序随 points/magnitudes 插入序,
            下游不应把它当波段的规范排序。
        """
        return list(self.magnitudes.keys())  # 插入序而非排序: 下游不应当规范波段序

    def summary(self) -> dict[str, Any]:
        """测光摘要 (n_points/band 覆盖; 无时间跨度 — 静态星表)。

        Returns:
            含 source_id/band/n_points/bands/magnitudes 的浅字典,
            直接可 JSON 序列化; 不含 ra/dec/时间字段 (BEST 无历元)。
        """
        return {
            "source_id": self.source_id,
            "band": self.band,
            "n_points": self.n_points,
            "bands": self.bands,
            "magnitudes": self.magnitudes,
        }

    def to_csv(self, filepath: str, allow_empty: bool = False) -> str:
        """导出多波段测光为 CSV (Rule 12 防线二原子落盘)。

        长表一行一波段, 固定 10 列, **每行自带归因三件套**: ``catalog``
        (来自哪个星表) + ``band`` (波段标签) + ``source_column`` (该星表
        真实发布的物理列名)。只落 band 是不够的: ``r`` 在 ``ps1`` 是
        ``rpsf``、在 ``landolt`` 是 ``rmag``、在 ``gaia_dr3_18`` 是
        ``phot_rp_mean_mag``, 三个不同测光系统的量混在一列里, 跨表合并
        后无法追回是哪张表哪一列 (G1-06)。需要**整行**原始列时用
        :meth:`to_json` (``raw_data`` 全量留档), CSV 是可归因的窄投影。

        ``source_id`` 逐级回退到容器 id: 线上 ``ps1`` 的 ``ps1_source_id``
        实测发空串, 原样落盘会得到一整列空 id (血缘断在第一列)。容器 id
        是调用方给的真实标识 (``from_client`` 侧是 ``POS_<ra>_<dec>``),
        拿它兜底不构成编造; 两者都空才留空 (直接构造容器的场景, 站点没有
        给出过任何标识)。

        Args:
            filepath: 输出路径
            allow_empty: 是否允许 0 点容器落盘。**缺省 False** —— 0 点容器
                落盘就是一个仅表头 (几十字节) 的文件, 与"写坏的空文件"不可
                区分, 还会被导出层计成"导出成功" (Q-29 反例)。确需为真空区
                留档时显式置 True, 落盘日志按 ``row_status=empty`` 标记
                (与 :mod:`src.download_artifacts` 同一套词表)。

        Returns:
            绝对路径

        Raises:
            RuntimeError: ``n_points == 0`` 且未显式 ``allow_empty=True``;
                **不落盘**, 也不进调用方的成功列表 (铁律 5)。
        """
        self._guard_nonempty(filepath, allow_empty)  # 0 点闸先于任何 IO: 拒绝就不该建目录
        path = _guard_output(filepath)  # 路径穿越在此统一拦: 两个导出方法共用同一防线
        # 允许调用方直接给嵌套输出路径 (如 out/lc/xxx.csv) 而无需预建目录
        path.parent.mkdir(parents=True, exist_ok=True)  # 允许嵌套输出路径: 免得调用方先预建目录
        # 内存里拼完整 CSV 再落盘: 数据量 = 点数×波段数 (数十行量级),
        # 流式写只会多一次 flush 分支, 换不到性能。
        buffer = io.StringIO()  # 内存拼全文: 数据量数十行, 流式写换不到性能
        writer = csv.writer(buffer)  # 交给 csv 管引号转义, 不手写 join
        writer.writerow(["source_id", "catalog", "ra", "dec", "band", "source_column",  # 表头即列序契约: 长表固定这 10 列
                         "magnitude", "magnitude_error", "snr", "class_star"])
        for p in self.points:                                                                       # 逐点
            # 归因列逐点取一次即可: catalog 与 id 在一个点的所有波段行里恒定
            catalog = p.catalog  # 逐行的解析上下文: 同一容器内不同点可能来自不同表
            pid = p.source_id or self.source_id  # 逐级回退: 站点发空 id 时用容器 id 兜住, 不让整列空掉
            for band, mag in p.magnitudes.items():  # 长表一行一波段: 宽表在波段不等长时会留空洞
                # 该波段无误差时留空, 不填 0: 0 会被当成"误差为零"的
                # 真实测量参与加权。
                err = p.magnitude_errors.get(band)  # 无误差留空不填 0: 0 会被当零误差真值参与加权
                # 每格过 sanitize_cell: 站点侧 class_star 等字段可含
                # "=" 开头文本, 直接落盘会被表格软件当公式执行。
                writer.writerow([  # 逐格 sanitize_cell: "=" 开头文本会被表格软件当公式
                    sanitize_cell(pid), sanitize_cell(catalog),
                    sanitize_cell(p.ra), sanitize_cell(p.dec),
                    sanitize_cell(band),
                    # 物理列名走权威表反查 (r -> rpsf), 不按 f"{band}psf" 拼名:
                    # 拼出来的名字在别的星表上根本不存在, 那才叫不可归因
                    sanitize_cell(_magnitude_source_column(catalog, band)),
                    sanitize_cell(mag),
                    # 显式判 None 而非 `x or ""`: 0.0 是**真实测量值**不是缺测 ——
                    # `or` 会把 0.0 抹成空串。天文上 class_star=0.0 表示确定的星系
                    # (0 星系 / 1 恒星 / 0.5 未定), snr=0.0 是合法低信噪比测量;
                    # 抹成空会让下游把"测到 0"误读成"没测到"。
                    sanitize_cell(err if err is not None else ""),
                    sanitize_cell(p.snr if p.snr is not None else ""),
                    sanitize_cell(p.class_star if p.class_star is not None else ""),
                ])
        content = buffer.getvalue()  # 取出全文: 落盘交给共享原子写
        # Q-60: CSV 落盘 utf-8-sig (与 downloader / io.to_csv 同口径); 原子写走
        # src.scripts.guards.atomic_write_text (全包单一实现)。
        atomic_write_text(path, content, encoding="utf-8-sig")  # utf-8-sig 与 downloader 同口径 (Q-60)
        logger.info("Multi-band photometry saved to %s (%d rows, row_status=%s)", path, len(self.points), self._row_status)
        return str(path.resolve())  # 回绝对路径: CLI 回显与后续目录级检查都按绝对路径走

    def to_json(self, filepath: str, allow_empty: bool = False) -> str:
        """导出多波段测光为 JSON (Rule 12 防线二原子落盘)。

        Args:
            filepath: 输出路径
            allow_empty: 与 :meth:`to_csv` 同义 —— 缺省拒绝 0 点容器落盘,
                显式 True 才允许为真空区留档 (日志标 ``row_status=empty``)。

        Returns:
            绝对路径

        Raises:
            RuntimeError: ``n_points == 0`` 且未显式 ``allow_empty=True``;
                **不落盘**, 也不进调用方的成功列表 (铁律 5)。
        """
        self._guard_nonempty(filepath, allow_empty)  # 同一道 0 点闸: 两个出口口径必须一致
        path = _guard_output(filepath)  # 与 to_csv 同一防线, 不各写一份
        # 同样先建父目录: 两个导出方法共用同一份"调用方不必预建目录"
        # 约定, 否则 CLI 的 --output a/b/c.json 会在 JSON 路径上炸掉。
        path.parent.mkdir(parents=True, exist_ok=True)  # 同一约定: --output a/b/c.json 不该炸
        data = {                                                                                    # 构造结果信封
            "source_id": self.source_id,
            "band": self.band,
            "n_points": self.n_points,
            # to_dict 保留每个源的完整原始列, 与 CSV 的窄投影互补:
            # CSV 给人看, JSON 供程序做类型保真的二次消费。
            "points": [p.to_dict() for p in self.points],  # 完整原始列: 与 CSV 窄投影互补
        }
        # ensure_ascii=False: 星表里的中文类星源标签直出可读, 转义
        # 只会让 JSON 体积翻倍且不可人工核对。
        content = json.dumps(data, indent=2, ensure_ascii=False)  # ensure_ascii=False: 中文标签直出可读
        atomic_write_text(path, content, encoding="utf-8")  # 纯 utf-8 无 BOM: JSON 供程序读
        logger.info("Multi-band photometry saved to %s (row_status=%s)", path, self._row_status)  # 同 to_csv: 落盘行状态显式外带
        return str(path.resolve())  # 同 to_csv: 一律回绝对路径

    def _guard_nonempty(self, filepath: str, allow_empty: bool) -> None:
        """0 点导出闸: 缺省拒绝落盘 (两个导出方法共用同一道闸)。

        0 点容器落成的仅表头文件 (CSV 约 60~70 字节) 与"写坏了的空文件"
        不可区分, 而调用方会把它读成"这个天区真的没有源" —— 本模块
        ``from_client`` 的 docstring 已把这个形态点名为 Q-29 反例, 却在
        ``from_position`` 侧仍在生产它 (G1-03 实跑证据: 真实空天区与查询
        失败两种情形都落了同一形态的文件)。**抛而不落盘**: 显式失败不会
        留下一个看起来完好、实则无数据的产物。

        Args:
            filepath: 目标路径 (只进错误消息, 不做 IO)。
            allow_empty: 调用方显式要求为真空区留档时才放行。

        Raises:
            RuntimeError: 0 点且未显式 ``allow_empty=True``。
        """
        if not self.points and not allow_empty:
            raise RuntimeError(  # 抛而不落盘: 仅表头文件与写坏的空文件不可区分 (铁律 5)
                f"refusing to export 0-point photometry to {filepath!r}: a "
                f"header-only artifact is indistinguishable from a broken "
                f"write; pass allow_empty=True to record a genuinely empty "
                f"region explicitly (row_status=empty)"
            )

    @property
    def _row_status(self) -> str:
        """落盘行状态 (复用 :mod:`src.download_artifacts` 的同一套词表, 不另造一套)。

        Returns:
            ``"ok"`` (有测光点) 或 ``"empty"`` (0 点, 仅在调用方显式
            ``allow_empty=True`` 时才会真正落盘)。词表取自
            ``STATUS_OK``/``STATUS_EMPTY``, 容器侧不再自造同义值。
        """
        return STATUS_EMPTY if not self.points else STATUS_OK  # 与下载侧同词表: 同一个 empty 只有一种含义
