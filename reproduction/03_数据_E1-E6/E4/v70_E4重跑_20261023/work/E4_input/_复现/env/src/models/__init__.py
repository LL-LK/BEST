"""src.models — BEST 查询结果的数据模型层 (基于 nadc.china-vo.org/data/best 线上库真实响应结构建模)。

职责: 把 TAP/下载回来的**原始行** (dict, 列名是线上真实拼写) 归一化成稳定的
Python 对象 (BestSource 等), 并在模型层单点维护"线上列名 -> 领域字段名"的映射。
本层不含查询、不发网络、不落盘。

所属子系统: 位于 src/ 的数据模型层, 处在 TAP 协议层的**下游**。上游是
``src/tap`` (返回原始行) 与 ``src/core`` (做后处理); 下游是脚本层与
Agent 侧 (消费归一化后的字段)。归一化只做一次, 之后的流水线都面向字段名编程。

对外接口:
- ``BestSource``: 归一化源记录; 外部可依赖的 seam —— 它的字段名是全仓事实标准,
  改字段名等于改公开 API。
- ``SourceQueryInput`` / ``from_row``: 查询输入模型与行 -> 对象的
  转换入口; 外部可依赖的 seam —— 脚本层只通过它们拿对象。
- ``CATALOG_*`` 列映射常量: 逐星表星等列与误差列的声明; 外部可依赖的 seam ——
  protocol 层据此决定服务端返回什么。
- ``PROXIMITY_META_COLUMNS*``: proximity 元数据列集合 (含/不含星表前缀两种形态)。

依赖与数据流: 跨"协议层 -> 模型层"能力边界, 从 :mod:`src.protocol` 引入权威的
星等列映射与 proximity 列定义 (P0-1 波段误归属修复后, 模型层不再自建波段表)。
数据流是**进程内内存**: 上游行 dict 进, ``BestSource`` 对象出, 不落盘、不跨进程。

关键契约与不变量:
- 列名映射必须取自 protocol 层线上真实发布的拼写, **不许按列名前缀猜波段** ——
  猜错会把某波段的星等静默归到另一波段, 且不报任何错。
- 表单表名 (``gaiaxp_photinfo_replenish_``) 与星表名 (``xpsp_``) 是两套前缀:
  只剥星表前缀会让 xpsp/dr3xpcorr 的位置与星等整列消失 (2026-09-29 live 验收
  发现的真实事故)。
- ``lru_cache`` 缓存列前缀集是性能不变量: from_row 每行调用一次, xpsp 有 139 张
  表单表, 现算前缀会让每行付出一次全表扫描。

陷阱与边界: 新增星表或新增列时, 映射要以线上 showcol 的真实拼写为准
(CATALOG_COLUMNS 是判据), 不要"按惯例推名字"; 另外模型层只认归一化后的字段,
把原始行直接传进下游会绕过全部缺测与哨兵处理 (BEST 用约 -1000 表示无测光)。
"""
from __future__ import annotations

# 标准库: dataclass 承载字段声明 / datetime+timezone 给查询结果打 UTC 时间戳 /
# Enum 做星表类型枚举 / typing 提供可选与任意类型注解 / lru_cache 缓存列前缀集
# (from_row 每行都会用一次, xpsp 有 139 张表单表, 不能每行现算) /
# math 做非有限值判定 (float("nan")/float("inf") 不抛异常, 靠它兜住)。
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from functools import lru_cache
from typing import Any, Optional

# 本地: 跨"协议层 -> 模型层"能力边界, 引入协议层的显式星等映射与 proximity
# 元数据列定义 (P0-1 波段误归属修复的权威来源), 模型层不再自建波段表。
# 逐星表星等映射的权威出处在协议层 (服务端真正返回什么的唯一判定处); 模型层消费
# 它们, 于是波段字母再也不会被从列名前缀猜出来。
# catalog_tables: 该星表 showcol 可取列的表名 —— xpsp/dr3xpcorr 的响应列以
# **表单表名** (``gaiaxp_photinfo_replenish_``) 而非星表名 (``xpsp_``) 为前缀,
# 只剥星表前缀会让这两张星表的位置/星等整列静默丢失 (2026-09-29 live 验收发现)。
from src.protocol import (
    CATALOG_ALIASES,
    CATALOG_DISPLAY,
    CATALOG_MAG_COLUMNS,
    CATALOG_MAG_ERROR_COLUMNS,
    PROXIMITY_META_COLUMNS,
    PROXIMITY_META_COLUMNS_BARE,
    catalog_tables,
)

# G1: BestSource 六个历史从不填充字段的**真实列名 -> 字段名** 映射。键是剥掉
# 星表前缀后的小写列名; 权威来源是 protocol_catalog_tables.CATALOG_COLUMNS 的
# 响应列清单 (各星表线上真实发布的拼写), 不猜名字:
#   * ra_err/dec_err: stripe82 发布 ``rarms``/``decrms`` (坐标 RMS, 即位置
#     误差); 其余星表不发布坐标误差列, 字段保持 None;
#   * parallax: ps1/gaia_dr3_18/landolt/xpsp/dr3xpcorr 均发布 ``parallax``;
#   * parallax_err: ps1 发布 ``parallax_err``, gaia_dr3_18 发布
#     ``parallax_error`` (误差列拼写不同, 两种真实拼写都收; 比例列
#     ``parallax_over_error`` 不是误差, 故意不收);
#   * fwhm/quality_flag: 当前没有任何星表发布 (fwhm 在 QUALITY_COLUMNS 里无列;
#     字段保留缺省值; 上游将来发布或本包导出列回读时按同名字直接流入。
# 通用拼写 (``ra_err``/``dec_err``/``parallax_err``/``fwhm``/``quality_flag``)
# 一并收录, 供非星表来源的行 (导出列回读/上游新表) 原样落入同名字段。
_ASTROMETRIC_COLUMNS: dict[str, str] = {                                                         # 天体测量列映射: 哨兵值判定要按列逐个区分量纲
    "ra_err": "ra_err", "rarms": "ra_err",      # stripe82 的位置误差线上发布为 RMS 而非 _err
    "dec_err": "dec_err", "decrms": "dec_err",  # 同上 dec 方向; 其余星表不发布坐标误差列
    "parallax": "parallax",                     # ps1/gaia18/landolt/xpsp/dr3xpcorr 都发布此列
    "parallax_err": "parallax_err", "parallax_error": "parallax_err",
    "fwhm": "fwhm",                             # 当前无星表发布, 字段位先留着
    "quality_flag": "quality_flag",             # 同上; QUALITY_COLUMNS 本身**非空** (13 键, 如 ps1 -> {class_star: class_star}), fwhm 单列无发布
}

# P2-3: -999 哨兵豁免列 — 带符号的真实物理量, 合法取值本就可以低于 -999
# (高自行星 pmra/pmdec 可达 ±1e4 mas/yr; radial_velocity 可为大负值)。
# live 证据 (temp/live_sentinel_evidence.py): ps1 与 gaia_dr3_18 各 200 行
# 响应里, 这批列没有任何 <= -999 的取值 —— 站点不用 ≈-999 作它们的缺失
# 哨兵 (视差/自行缺失呈空值)。豁免规则先立, 防止这些列将来映射到字段时
# 再次把合法值静默抹成 None。
_SENTINEL_EXEMPT_COLUMNS = frozenset({"pmra", "pmdec", "radial_velocity"})                      # 豁免列: 这几列的哨兵是物理量, 不能当缺测剔除


@lru_cache(maxsize=None)  # 无上限: 星表集合是闭集, 缓存项数等于被查过的星表数
def _column_prefixes(catalog: str) -> tuple[str, ...]:
    """星表 -> 列名前缀剥离集 (星表名 ∪ 该星表全部表单表名, 长前缀优先)。

    为什么要含表单表名: xpsp/dr3xpcorr 的位置与 Gaia 测光列在共享表单表
    ``gaiaxp_photinfo_replenish``, 响应列名是 ``gaiaxp_photinfo_replenish_ra``
    而非 ``xpsp_ra`` (2026-09-29 live 验收) — 只剥星表名会让这两张星表的
    位置/星等整列静默丢失。长前缀优先防 ``jpas_u_`` 误剥 ``jpas_ujava_`` 列。
    uss_dr1 的 CSV 响应是裸名 (``ra_u``), 剥不中即原样判定, 其星等列以裸名
    直接命中 CATALOG_MAG_COLUMNS。

    Args:
        catalog: 星表 id 或旧拼写别名 (小写形式由调用方保证)。

    Returns:
        长前缀优先的前缀元组; 按 catalog 缓存 (from_row 的热路径)。
    """
    prefixes = [f"{catalog.lower()}_"]
    prefixes.extend(f"{t.lower()}_" for t in catalog_tables(catalog))  # 表单表名也是合法前缀: xpsp 的列挂在 gaiaxp_photinfo_replenish 上
    prefixes.sort(key=len, reverse=True)  # 长前缀优先, 否则 jpas_u_ 会误剥掉 jpas_ujava_ 列
    return tuple(prefixes)


# 位置列的历史拼写: RA/Dec 各有三种写法, 剥掉星表前缀后按名认列而不猜前缀,
# 所以这里的集合必须与 from_row 的坐标判定是同一套名字, 改一处就要改另一处。
_COORD_RA_NAMES = frozenset({"ra", "raj2000", "alpha"})  # 三种拼写, 不按前缀猜位置列
_COORD_DEC_NAMES = frozenset({"dec", "dej2000", "delta"})  # dec 侧对称集合


def _is_proximity_meta(column: str) -> bool:
    """列名是否是 proximity 匹配元数据列 (两种拼写都收)。

    带 ``inputobjs_`` 前缀的形态与无前缀裸名形态是同一批列的两种拼写, 由
    ``PROXIMITY_META_COLUMNS*`` 定义 (protocol 层权威)。

    为什么判据要能在**剥掉星表/表单表前缀之后**再用一次: 带星表前缀的形态
    (``<cat>_inputobjs_dist_arcsec``) 在剥之前既不以 ``inputobjs_`` 开头, 也
    不等于任何裸名, 只会穿过一道"剥前缀前"的守卫; 剥完才还原成元数据列名。
    而 ``inputobjs_*`` 的首字母是 ``i``, 漏过一次就等于把角距/行号当成
    i 波段星等 —— 那条首字母回退路径正由 from_row 的 docstring 点名要防。
    """
    return column.startswith("inputobjs_") or column in PROXIMITY_META_COLUMNS_BARE


def malformed_coordinate_reason(row: dict, catalog: str = "") -> str | None:
    """行结构判定: 坐标列**存在但值为空** → 返回理由串 (结构半行)。

    E4 F-E4-01 的判定据: "有 ra 无 dec" 的行经 from_row 老实落成
    ra=值/dec=None 后**照样入库** — 一颗没有完整位置的"源"进入结果集,
    下游按 None 坐标做匹配/去重时静默出错 (P1-4 已保证缺值不落 0.0 原点,
    但"半行入库"本身仍是数据面事故, 与传输截断半行 (RB-29) 同类)。

    只判**列存在但空值**: 响应里根本没有坐标列的星表 (如 uss_dr1 无规范化
    ra/dec) 不是本行的错 — 那种行照常放行, 由 from_row 的 None 语义承担。
    列名解析 (剥星表/表单表前缀) 与 from_row 共用 ``_column_prefixes``。

    Args:
        row: 原始 CSV 行 dict (键为列名, 值为字符串)。
        catalog: 星表 id (透传给 _column_prefixes)。

    Returns:
        理由串 (哪个坐标列为空); 结构完好返回 None。
    """
    prefixes = _column_prefixes(catalog) if catalog else ()   # 无 catalog 上下文就无前缀可剥, 列名原样判定
    for key, value in row.items():                             # 逐列扫, 不预设响应一定带坐标列
        kl = key.lower().strip()                               # 大小写与空白差异不该改变判定 (PS1_RA ≡ ps1_ra)
        for pfx in prefixes:
            if kl.startswith(pfx):
                kl = kl[len(pfx):]
                break
        text = str(value if value is not None else "").strip()  # None 与空白串同判空: 都是"列在值缺"的半行
        # 星表缺失标记: CSV 里 "null"/"NaN"/"none" 是非空串, 只判 `not text` 会放行,
        # 而它们落到 from_row 后要么成 None (null) 要么成 nan (nan, 已被 _parse_num
        # 收口) —— 两种都是"坐标列在而值缺", 与空串同性质, 不能只当普通文本放过。
        is_blank = (not text) or text.lower() in ("null", "nan", "none")
        if kl in _COORD_RA_NAMES:                              # 只认三种历史拼写, 不做前缀猜测
            if is_blank:                                       # 列在而值为空: 判半行而不是放行
                return f"ra 列 {key!r} 值为空或无效标记({text!r})"  # 带原始列名与原值, 便于回查是哪张表的哪一列
        elif kl in _COORD_DEC_NAMES and is_blank:              # dec 同理, 有 ra 无 dec 同样是半行
            return f"dec 列 {key!r} 值为空或无效标记({text!r})"
    return None


class CatalogType(str, Enum):
    """星表类型枚举: 值为线上可查询星表 id (与 protocol.CATALOG_PATHS 对齐)。"""

    # STD 是 Standard Stars 导航分组, 不是可查询表; 其线上成员是 SCR_GALAH、
    # SCR_LAMOST 与 XPSP。
    STD = "std"
    PS1 = "ps1"
    CALIB_STRIPE82 = "stripe82"
    CALIB_GAIA = "gaia_dr3"       # 标准星表: 取 Gaia DR3 的定标源子集
    CALIB_GAIA_18 = "gaia_dr3_18"  # 另一发布批次: 误差列拼写多一个 or, 故映射表两种都收
    CALIB_JPLUS = "jplus_dr3"
    CALIB_SMSS = "smss_dr4"
    CALIB_LANDOLT = "landolt"     # Landolt: 多次曝光合成单星等列 (vmag 形态)
    CALIB_USS = "uss_dr1"         # CSV 响应是裸列名, 无规范化 ra/dec
    CALIB_SPLUS = "splus_dr4"
    SCR_GALAH = "scr_galah"       # 巡天星表, 与 STD 导航分组不同源
    SCR_LAMOST = "scr_lamost"
    XPSP = "xpsp"                 # 139 张表单表共用一张表单, 列以表单表名为前缀
    DR3XPCORR = "dr3xpcorr"       # 校正列 (*_corr): 同星表内不得覆盖原始测光

    @property  # 只读: 显示名的单一出处在 protocol, 本层不做副本也不缓存
    def display_name(self) -> str:
        """星表中文显示名 (单一出处: protocol.CATALOG_DISPLAY, 不再本地副本)。"""
        return CATALOG_DISPLAY.get(self.value, self.value)


@dataclass
class ColumnConstraint:
    """BEST 表单查询的单条列约束。

    ``constraint`` 取 ``between`` (需 min/max) 或单值操作 (``greater`` /
    ``greaterequal`` / ``less`` / ``lessequal`` / ``equal`` / ``contains`` /
    ``in``, 需 value; 缺省时由 build_query_form 按操作类型回退取 min 或 max)。
    ``file``/``show``/``sort`` 三个字段**协议层从不读取**, 属死参数: 传了
    (或 ``show=False``) 会在 :func:`src.protocol.build_query_form` 阶段抛
    ``ValueError``, 而不是静默丢弃后返回一个未经这三者处理的结果集 (A2-04)。
    字段命名兼容 dict 与属性对象两种调用写法。
    """

    name: str = ""                             # 受约束的列名, 必须是该表真实发布的列
    constraint: str = "between"                # 操作类型; 缺省区间, 单值操作改用 value
    min: Optional[float] = None                # 区间下界; 单值操作缺省时由 build_query_form 回退
    max: Optional[float] = None                # 区间上界
    value: Optional[str] = None                # 单值操作的操作数 (contains/in 的值集也走这里)
    file: Optional[str] = None                 # 死参数 (A2-04): 值文件上传未实现, 传非 None 即抛错
    show: bool = True                          # 死参数 (A2-04): 传 False 即抛错; showcol 由 show_columns 决定
    sort: Optional[str] = None                 # 死参数 (A2-04): 排序走 build_query_form(sort=...), 传非 None 即抛错


@dataclass
class BestSource:
    """BEST 查询结果中的单个源 (一行)。

    同时承载解析后的天文字段 (ra/dec/星等/误差/视差等) 与原始 CSV 行
    (``raw_data``), 使下游既能用规范字段也能追溯服务端原值。
    """

    source_id: str = ""                                                      # 各星表 ID 拼写不一, 统一在 from_row 别名支路归一
    # P1-4: ra/dec 缺值即 None, 不填 0.0 —— (0,0) 是真实天球位置 (天球原点),
    # 填 0.0 会让畸形行静默落到原点并被 deduplicate 当成同一位置互相去重
    # (src/crossmatch.py 的注释已把该做法点名为反模式)。
    ra: Optional[float] = None                                               # 缺值即缺失; 位置列只认三种历史拼写
    dec: Optional[float] = None                                              # dec 与 ra 成对, 缺一即半行 (见上方判定)
    ra_err: Optional[float] = None                                           # stripe82 才发布 (列名 rarms/decrms)
    dec_err: Optional[float] = None                                          # 坐标误差不从星等残差反推
    magnitudes: dict[str, float] = field(default_factory=dict)               # 波段 -> 星等; 键只由显式映射表产出
    magnitude_errors: dict[str, Optional[float]] = field(default_factory=dict)  # 误差单列: 有的波段发星等不发误差
    snr: Optional[float] = None                                              # ps1 系信噪比; 无此列的星表保持 None
    fwhm: Optional[float] = None                                             # 目前无星表发布此列, 字段仅为兼容保留
    quality_flag: str = "good"                                               # 缺省 good: 空串列不当有效值
    class_star: Optional[float] = None                                       # class/class_star/objclass 三种拼写共用
    parallax: Optional[float] = None                                         # 视差 (mas); 属天体测量, 不套 -999 哨兵
    parallax_err: Optional[float] = None                                     # gaia18 的 parallax_error 归到同一字段
    catalog: str = ""                                                        # 来源星表 id, 供下游按表去重/合并
    raw_data: dict[str, str] = field(default_factory=dict)                   # 原始行全量留档: 追溯服务端原值

    @classmethod
    def from_row(cls, row, catalog=""):
        """从 CSV 行构造 BestSource; catalog 透传以剥离列前缀 (Q-04)。

        前缀剥离覆盖星表名与该星表全部表单表名 (长前缀优先):
        xpsp/dr3xpcorr 的响应列以表单表名 (``gaiaxp_photinfo_replenish_ra``)
        为前缀, 只剥星表名 (``xpsp_``) 会让这两张星表的位置/星等整列静默丢失;
        uss_dr1 的 CSV 响应是裸名 (``ra_u``), 剥不中即原样判定, 其星等列以裸名
        直接命中 CATALOG_MAG_COLUMNS (该星表无规范化 ra/dec, 按波段各自测量)。

        P0-1/V-1: proximity 批量匹配的响应自带匹配元数据列
        (``inputobjs_input_line`` / ``inputobjs_dist_arcsec`` /
        ``inputobjs_input_ra`` / ``inputobjs_input_dec``; 未提交 showcol 时是
        无前缀拼写 ``input_line`` / ``dist_arcsec`` / ...)。这些列**不是测光
        列**, 但 ``inputobjs_*`` 以波段字母 "i" 开头, 旧波段首字母匹配会把
        角距/行号吞成 i 波段星等 (live 实证前不可见的数据污染)。元数据列只进
        ``raw_data``, 不参与 magnitudes/magnitude_errors 推断。

        这条保证对**两种前缀形态**同时成立: 带星表前缀的拼写
        (``<cat>_inputobjs_dist_arcsec`` / ``<cat>_input_line``) 要先剥前缀
        才认得出是元数据列, 故元数据判定在剥前缀前后各做一次 (裸名形态在剥
        前就拦下, 带前缀形态在剥后拦下) —— 只在剥前缀前判一次, 带前缀形态会
        穿过守卫, 落到下面的首字母回退里被当成 i 波段星等。
        (这批列不是 proximity 专属: 锥搜回包同样带, live 快照 31 份里 30 份
        带, 例外是 uss_dr1, 见 references/site-endpoints-and-interactions.md §11.4。)

        波段归属以 protocol 的显式星表映射表为准 (CATALOG_MAG_COLUMNS /
        CATALOG_MAG_ERROR_COLUMNS): 按列名首字母猜波段会把
        ``ps1_gflags=16416`` 当 g 星等、``ps1_ruwe`` 当 r 星等, 还会把
        ``gaia_dr3_18_phot_g_mean_mag`` / ``landolt_vmag`` 整列丢掉
        (live 行实测)。显式表缺失的星表才回退到首字母启发式,
        且同星表内绝不再回退 — 修正列 (``*_corr``) 不会覆盖原始测光。

        G1: ``ra_err``/``dec_err``/``parallax``/``parallax_err``/``fwhm``/
        ``quality_flag`` 六个字段按真实列名填充 (映射表见模块顶部
        ``_ASTROMETRIC_COLUMNS``, 键集锚定 CATALOG_COLUMNS 响应列清单) —
        只把它们留在 ``raw_data`` 的话, 下游读 ``obj.parallax`` 会静默拿到
        None。空值/非数字/≈-1000 哨兵一律按缺失处理 (不写默认值冒充真实值)。
        """
        obj = cls(catalog=catalog, raw_data=row)  # raw_data 整行留档: 归一化有偏差也能回溯原值
        # 启发式回退时认可的波段字母集合 (仅在显式映射表缺失时使用)。
        known_bands = ["u", "g", "r", "i", "z", "y", "j", "h", "k"]
        # 列名前缀剥离集: 星表名前缀 + 该星表全部表单表名前缀 (长前缀优先) —
        # 响应列可能以任一表名为前缀 (``ps1_ra`` / ``gaiaxp_photinfo_replenish_ra``),
        # uss_dr1 的 CSV 响应则是裸名 (``ra_u``), 剥不中即原样参与判定, 裸名
        # 直接命中显式映射表。无 catalog 上下文时前缀集为空, 列名原样参与判定。
        # (集由 _column_prefixes 按星表缓存, 不在每行现算。)
        prefixes = _column_prefixes(catalog) if catalog else ()                     # 列前缀集按星表取: 没给 catalog 就没有前缀可剥, 此时一律不剥
        # 显式映射表: 有表就不用猜 (protocol 权威层); 无表 (未知/旧星表) 才
        # 保留首字母启发式作为兼容回退。
        mag_map = CATALOG_MAG_COLUMNS.get(      # 权威表: 键=剥前缀后的列名, 值=波段字母
            CATALOG_ALIASES.get(catalog.lower(), catalog.lower()), {}) if catalog else {}
        err_map = CATALOG_MAG_ERROR_COLUMNS.get(  # 误差表与星等表分列, 有的星表只发其中一种
            CATALOG_ALIASES.get(catalog.lower(), catalog.lower()), {}) if catalog else {}
        use_maps = bool(mag_map)  # 判据: 星等表非空才禁掉首字母启发式 (误差表可以缺)
        for key, val in row.items():                                                    # 逐列比对: 前缀匹配不上的列原样保留, 交给上层判是不是标识符列
            # 列名统一小写并去空白, 使 ``PS1_RA``/`` ps1_ra `` 与规范拼写等价。
            kl = key.lower().strip()  # 判定键空间的唯一形式, 后面所有分支都比它
            if _is_proximity_meta(kl):
                continue  # proximity 匹配元数据 (无前缀拼写): 原样留在 raw_data, 不当星等
            for pfx in prefixes:
                if kl.startswith(pfx):
                    # 剥掉表名前缀, 使 ``ps1_gpsf`` / ``gaiaxp_photinfo_replenish_g_mag``
                    # 与 ``gpsf`` / ``g_mag`` 落在同一判定空间 (显式映射表的键就是
                    # 剥前缀后的列名)。
                    kl = kl[len(pfx):]  # 剥到裸列名, 与显式映射表的键空间对齐
                    break
            # 剥完前缀**必须复判一次**元数据列: 带星表前缀的形态
            # (``<cat>_inputobjs_dist_arcsec`` / ``<cat>_input_line``) 在上面那道
            # 守卫处还看不出是元数据列, 剥完才还原成 PROXIMITY_META_COLUMNS* 里的
            # 名字; 漏判则 ``inputobjs_*`` 的首字母 ``i`` 会把角距/行号/输入坐标
            # 当成 i 波段星等 (静默数据污染, 无异常无日志)。
            if _is_proximity_meta(kl):
                continue  # 带星表前缀的元数据形态: 同样只进 raw_data
            nv = cls._parse_num(val)  # 先统一成 float/None, 之后每个分支只判 None
            # P2-3: -999 哨兵只作用于测光/质量类列 (没有任何天文星等到 -999);
            # 天体测量列 (视差/自行/坐标误差, 见 _ASTROMETRIC_COLUMNS 与
            # _SENTINEL_EXEMPT_COLUMNS) 是带符号真实物理量, 高自行星 pmra 可达
            # ±1e4 mas/yr —— 无差别套用会把合法值静默抹成 None。
            if (nv is not None and nv <= cls.NULL_MAGNITUDE_SENTINEL
                    and kl not in _ASTROMETRIC_COLUMNS
                    and kl not in _SENTINEL_EXEMPT_COLUMNS):
                nv = None  # ≈-1000 sentinel: 无测光, 不当星等/误差
            if kl in ("id", "source_id", "objid", "obj_id", "calibstars_id"):
                # calibstars_id: stripe82 的 ID 列 (live 实证其响应
                # 用裸列名, 不在 {catalog}_ 前缀体系内, 旧别名表漏它导致 ID 丢失)
                obj.source_id = str(val)  # 原样转字符串: 星表 ID 带前导零与连字符, 不可数值化
            elif kl in ("ra", "raj2000", "alpha"):
                # 位置列取三种历史拼写; 空值/非数字落 None (P1-4: 缺值即缺失,
                # 不拿 0.0 冒充天球原点)。
                obj.ra = nv  # 缺值写 None: 半行判定交给 malformed_coordinate_reason
            elif kl in ("dec", "dej2000", "delta"):
                obj.dec = nv  # 与 ra 同策略, 不单独兜底 0.0
            elif kl in ("snr", "s_n"):
                obj.snr = nv  # snr / s_n 两种拼写, 都没有则保持 None
            elif kl in ("class_star", "class", "objclass"):
                obj.class_star = nv  # 分类列同样只认这三种线上拼写
            elif kl in _ASTROMETRIC_COLUMNS:
                # G1: 六个历史从不填充字段按真实列名落值 (映射表见模块顶部)。
                # 数值字段只在解析成功时写 (nv 为 None 即空值/非数字, 不拿默认值
                # 冒充真实值); P2-3: 本分支不套 -999 哨兵 (豁免, 见上方
                # _SENTINEL_EXEMPT_COLUMNS 说明与 live 证据); quality_flag 是
                # 字符串字段, 空串列不当有效值 (保留缺省 "good")。
                field_name = _ASTROMETRIC_COLUMNS[kl]  # 映射表把多种线上拼写收敛到同一字段名
                if field_name == "quality_flag":
                    text = str(val).strip()  # 字符串列: 不走 float 解析, 免得 "good" 变 None
                    if text:
                        obj.quality_flag = text  # 空串不当有效值, 保留缺省 good
                elif nv is not None:
                    setattr(obj, field_name, nv)  # 只在解析成功时写, 不覆盖缺省
            elif use_maps:
                # 显式映射优先: 列名必须在星表的测光表内才算波段值。
                if kl in err_map and nv is not None:
                    obj.magnitude_errors[err_map[kl]] = nv  # 误差列先判: 名称带 err 的列不进星等字典
                elif kl in mag_map and nv is not None:
                    obj.magnitudes[mag_map[kl]] = nv  # 值即波段字母, 键空间由 protocol 决定
            elif "err" in kl and nv is not None:
                # 启发式回退 (仅无显式表的星表): 误差列按首字母归波段;
                # 显式表存在时上面的分支已处理, 不会走到这里。
                for b in known_bands:
                    if kl.startswith(b):
                        obj.magnitude_errors[b] = nv  # 无显式表时才走: 波段来自首字母启发式
                        break
            elif nv is not None:
                # 启发式回退: 普通测光列按首字母归波段 (与上一支互斥, 因为
                # 含 "err" 的列已在前面命中)。
                for b in known_bands:
                    if kl.startswith(b):
                        obj.magnitudes[b] = nv  # 与误差支互斥, 同一列不会双写
                        break
        return obj

    @staticmethod
    def _parse_num(val):
        """把单元格文本转 float; 空值/``null``/非数字/**非有限值**一律返回 ``None``。

        非有限值必须在这里收口: ``float("nan")`` 与 ``float("inf")`` **不抛异常**,
        只靠 ``except (ValueError, TypeError)`` 拦不住, 而 ``nan <= -999.0`` 恒为
        ``False`` 所以哨兵分支同样拦不住 —— 结果 ``obj.ra`` 直接落成 ``nan``,
        且坐标/测光/SNR/视差等**所有**数值列一起被灌。口径与
        ``src.core.source_postprocess`` 的非有限值剔除一致。
        """
        if not val or val in ("null", "NULL", ""):  # CSV 的 null 字面量/空串/None 同判缺失
            return None
        try:
            number = float(val)
        except (ValueError, TypeError):
            return None  # 非数字一律 None: 缺测与脏值在这里被吸收, 不外泄异常
        return number if math.isfinite(number) else None  # nan/inf 与缺测同义: 任何比较对它们都不可预期

    # ps1 (以及共用其加载器的其他 SCR/calib 表) 用约 -1000 的**哨兵带**表示"无测量",
    # **不是某一个浮点值**。2026-10-05 实测 (ps1 @180,30 60", 整页 174 行): ps1_gpsf
    # 148/174 行哨兵, 在 2 位小数上就分裂成 -1004.07(103) + -1004.08(45), 完整浮点
    # 散布 -1004.0787842744421 ~ -1004.0726439746845 —— 浮点精确相等只命中 1/174;
    # 各波段带心还各不相同 (g≈-1004.07 / r≈-1003.88 / i≈-1003.54 / z≈-1002.88 /
    # y≈-1001.94), *_err 列则是精确的 -999.0。故**枚举两三个点覆盖不了**, 判定口径
    # 只能是**带**: 小于等于该阈值的值按缺失处理, 不算测光 (没有任何天文星等到 -999)。
    # 安全窗口 = (全带上沿 -1001.9397837161488, 带外最近合法值 16.20364086044799),
    # 本阈值落在其中, 距带顶 2.94、距最近合法值 1015.2。src.tap.formats 共用同一阈值,
    # 守门测试 test/unit/models/test_sentinel_band.py 把带内每个实测端点都钉成缺测。
    NULL_MAGNITUDE_SENTINEL = -999.0  # 阈值取在实测哨兵**带顶** (-1001.94) 之上、最近合法值之下, 覆盖整族写法

    def to_dict(self) -> dict[str, Any]:
        """BestSource -> dict (原始行 + 解析字段 + 质量元数据)。"""
        # 显式标注 dict[str, Any]: raw_data 是 dict[str, str], 不标注时 mypy 把
        # d 收窄成 str 值字典, 下面 update 混进 float/None/dict 即报不兼容 —— 与
        # 本方法 -> dict[str, Any] 的签名自洽。
        d: dict[str, Any] = dict(self.raw_data)  # 先铺原始行: 未归一化的列仍能出现在导出结果里
        d.update({                                                                    # 逐字段落地: 未在站点行里出现的字段按 dataclass 缺省补齐
            "source_id": self.source_id,
            "ra": self.ra,
            "dec": self.dec,
            "magnitudes": self.magnitudes,
            "magnitude_errors": self.magnitude_errors,  # 值可含 None: 该波段发星等却没发误差
            "snr": self.snr,
            "fwhm": self.fwhm,
            "quality_flag": self.quality_flag,          # 缺省 good 只表示"没收到该列", 非站点判定
            "class_star": self.class_star,
            "catalog": self.catalog,
        })
        return d


@dataclass
class BestQueryResult:
    """BEST 查询的整体响应 (一次查询的汇总结果)。"""

    success: bool = False      # 整次查询是否成功; 失败时看 error_code 而非嗅 error 文本
    total_count: int = 0       # 服务端自报总行数: 判截断的唯一依据
    returned_count: int = 0    # 实际落地行数; 与 total_count 不等即被截断
    # P0-2: 服务端报告的行数多于实际返回的行数时为 True (客户端停在 ``max_rows``
    # 或分页提前结束)。没有这个标记, 上层无法区分"完整结果"和"被静默截断的结果"。
    truncated: bool = False
    sources: list = field(default_factory=list)  # 归一化源对象; 空列表是合法结果而非失败
    query_time: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())  # UTC: 跨时区可比
    query_params: dict = field(default_factory=dict)  # 原始查询参数留档, 复现同结果时依赖它
    error: Optional[str] = None  # 人类可读消息; 机器分支请改用 error_code
    # 类型化失败码 (E_SOFT_404 / E_NO_SQLID / E_INVALID_INPUT / ...), 使调用方能
    # 按稳定的契约值分支, 而不是去嗅人类可读的 ``error`` 字符串。
    error_code: Optional[str] = None

    def __len__(self):
        """返回本结果中的源个数 (``len(result)`` 即 returned_count 的实测量)。"""
        return len(self.sources)


@dataclass
class ResolvedName:
    """``/nss/solve`` 的天体名解算结果 (P1-8)。

    该端点代理 CDS Sesame。失败是 HTTP 200 响应体内部的哨兵对
    (``ra=dec=-1000``), 绝不是错误状态码 —— 客户端因此抛
    :class:`src.protocol.NameResolveError` 而不是返回一个失败实例。

    S-3: ``remark`` 来自外部 Sesame 服务, 可能含外部 URL。它被放在一个显式标注
    为外部的字段里, 因此永远不会被当成可信内容进入自动抓取链。
    """

    name: str = ""               # 服务端回显的 obj 名; payload 缺该字段时回退请求名
    ra: float = 0.0               # 哨兵预检已在 protocol 层完成, 这里只装可信值
    dec: float = 0.0              # 同上: -1000 哨兵对不会走到构造器
    remark: str = ""              # 外部 Sesame 服务的自由文本, 可能含外部 URL (S-3)
    remark_external: bool = True  # 恒为 True: remark 永远不进可信内容链

    @classmethod
    def from_payload(cls, name: str, payload: dict) -> "ResolvedName":
        """从已通过哨兵预检的 ``/nss/solve`` payload 构造 ResolvedName。

        Args:
            name: 调用方请求的天体名 (payload 无 ``obj`` 字段时用作回退)。
            payload: :func:`src.protocol.parse_name_resolve` 的解析结果,
                调用前必须已用 :func:`src.protocol.is_name_resolve_failure`
                排除失败哨兵。

        Returns:
            填好 name/ra/dec/remark 的实例。
        """
        return cls(
            name=str(payload.get("obj") or name),  # payload 无 obj 时用调用方请求的天体名
            ra=float(payload.get("ra", 0.0)),
            dec=float(payload.get("dec", 0.0)),
            remark=str(payload.get("remark") or ""),  # 外部文本只做透传, 不做清洗或信任
        )

    def to_dict(self) -> dict[str, Any]:
        """ResolvedName -> dict (remark 始终带外部来源标注, S-3)。"""
        return {
            "name": self.name,
            "ra": self.ra,
            "dec": self.dec,
            "remark": self.remark,
            "remark_external": self.remark_external,
        }


@dataclass
class BestCrossMatchJob:
    """提交给 BEST 的交叉匹配作业 (批量坐标匹配的任务描述)。"""

    job_id: str = ""                              # 服务端返回的作业标识, 轮询与取产物都用它
    status: str = "pending"                       # 提交前的缺省态; 实际取值由服务端推进
    created: str = ""
    input_sources: int = 0                        # 提交的输入坐标条数, 与 matched 对照可查漏匹配
    matched: int = 0                              # 命中条数; 小于 input_sources 即有坐标未匹配上
    output_url: Optional[str] = None              # 产物 URL: 这里只记录不下载, 取不取由调用方决定


@dataclass
class BestCrossMatchResult:
    """单个输入坐标对某个 BEST 星表的交叉匹配结果。

    与 BestSource 的区别: 它记录输入坐标、是否在匹配半径内找到对应体, 以及角距
    —— 即"这次匹配发生了什么", 而不只是"匹配到的那一行是什么"。
    """

    input_id: str = ""                                            # 调用方自己的输入标识, 用来回填结果
    input_ra: float = 0.0                                         # 输入坐标: 角距以此为参考点
    input_dec: float = 0.0
    matched: bool = False                                         # 仅表示"半径内找到", 不代表测光合格
    separation_arcsec: Optional[float] = None                     # 实际角距; 未匹配为 None 而非 0
    match_radius_arcsec: float = 3.0                              # 3 角秒是 BEST 交叉匹配默认半径, 随行留档
    catalog: str = ""                                             # 命中哪张星表: 同一坐标可对多表各匹配一次
    matched_source: Optional[BestSource] = None                   # 未匹配显式 None, 与 matched 互为冗余校验

    def to_dict(self) -> dict[str, Any]:
        """BestCrossMatchResult -> dict (输入坐标/匹配态/分离角)。"""
        return {
            "input_id": self.input_id,
            "input_ra": self.input_ra,
            "input_dec": self.input_dec,
            "matched": self.matched,
            "separation_arcsec": self.separation_arcsec,
            "match_radius_arcsec": self.match_radius_arcsec,
            "catalog": self.catalog,
            "matched_source": self.matched_source.to_dict() if self.matched_source else None,  # 未匹配落 None 而非空 dict
        }


# 历史别名 (BestCrossMatchResult 现在是上面独立的 dataclass); 保留以不破坏既有 import。
BestMultiBandPhotometryPoint = BestSource


# 本地: 输入/输出契约模型 (contracts/input.contract.yaml 与 output.contract.yaml
# 的逐字段落地)。沿既有布局放在文件底部导入; 这两个模块**不止**依赖 typing (output.py 还用 pathlib 与第三方 yaml), 也不反向
# 引用本文件, 因此导入顺序不影响初始化。
from src.models.input import ConeSearchInput, DownloadInput, SourceQueryInput  # noqa: E402
from src.models.output import BestResultSet, DownloadOutput, QualityReport, QueryOutput  # noqa: E402
