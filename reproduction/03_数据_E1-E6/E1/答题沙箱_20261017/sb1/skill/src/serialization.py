"""src.serialization — BEST 原生输出格式的单一事实源 (CSV/TSV/JSON/VOTable/FITS)。

能力边界: 把已取回的查询行 (``list[dict]``) 序列化为本地文件, 是
``src/downloader.py`` 下载路径的落盘层 (唯一存留的落盘路径)。
边界: 只做"行 -> 文件"的转换, 不发网络请求、不做查询; 线上取数格式恒为 CSV
(见 ``protocol.parse_csv_rows``), 这里的 txt/json/votable/fits 都是**本地导出**。

为什么单独成文: 写出逻辑只能有一份 — 多份副本必然出现"同一处 bug 只在一个分支
修掉"的局面 (典型症状: ``downloader`` 侧的 VOTable 把全部列一律写成
``datatype="char"``, 数值列被科学消费端读成字符串, 修好后另一侧仍是错的)。
本模块即那一份实现, 消费方统一走它。

格式白名单 (权威): 线上 ``output.fmt`` 支持集见 ``protocol.SUPPORTED_OUTPUT_FORMATS``
(csv/txt/json/votable); 本模块另加 ``fits`` —— 它是**纯本地转换格式**, 服务端
不返回 FITS (请求 fits 拿到的是结果页 HTML)。两个集合的差异与依据见
``references/data-formats.md``。
"""
from __future__ import annotations

# 标准库: csv 写出分隔符文本 / 内存缓冲 (先拼内容再交调用方原子落盘) /
# 日志 / 路径与目录 / 类型标注与序列签名
import csv  # 标准库: CSV/TSV 写出与引号转义, 不手写 join 是为躲引号破行
import io  # 标准库: 内存缓冲, 先拼全文再交调用方一次性落盘
import logging  # 标准库: 模块级 logger 出口
from pathlib import Path  # 标准库: FITS 落盘路径类型
from typing import Any, Optional, Sequence  # 标准库: 行记录/信封与可选参数的标注

# 本地: CSV 公式注入消毒 (Q-06, 每个单元格出口) /
# 协议层权威表 (星等列后缀集现场推导 + 线上格式白名单) /
# 哨兵豁免裸名单 (P2-3 窄名单, 附量程证据; 按私有名取而不复制一份字面量 ——
# 抄一份必然与模型层漂移, 而漂移的后果正是 X7-P0-1: 同一个 pmra 在模型侧保住、
# 在导出侧被抹成 NaN)
from src.csv_safety import sanitize_cell  # 本地唯一消毒实现: 序列化层不复制 (Q-06)
from src.models import _SENTINEL_EXEMPT_COLUMNS as SENTINEL_EXEMPT_BARE_NAMES  # 豁免裸名单的单一出处仍在 models
from src.models import BestSource  # 测光缺失哨兵阈值的真源 (P0-14: 与 TAP 出口/行模型同一阈值, 不另抄一份)
from src.protocol import (  # 协议层权威: 不另写第二份清单
    CATALOG_ALIASES,  # 旧拼写别名: 也是合法的站名前缀
    CATALOG_FORM_TABLES,  # 表单表名: xpsp 的列挂在共享表 gaiaxp_photinfo_replenish 上
    CATALOG_MAG_COLUMNS,  # 星等列映射 (推导星等后缀集)
    CATALOG_MAG_ERROR_COLUMNS,  # 误差列映射 (推导误差后缀集, 用于把误差列排除出星等判定)
    CATALOG_PATHS,  # 星表 id 全集 (推导站名前缀)
    SUPPORTED_OUTPUT_FORMATS,  # 线上格式白名单
)

logger = logging.getLogger(__name__)                                                      # 模块级 logger: 落盘层的失败也要留痕, 不能静默丢行


def _magnitude_suffixes() -> frozenset[str]:
    """从协议层权威星等列映射推导"星等列名后缀"集合。

    Returns:
        所有星表发布过的星等列名 (如 ``rpsf`` / ``phot_g_mean_mag`` / ``u_pstotal``)。

    Note:
        后缀集合**由 ``CATALOG_MAG_COLUMNS`` 现场推导**而不是另写一份清单:
        另写清单必然与协议层漂移, 而漂移的后果是新增星表的星等列拿不到
        ``unit="mag"`` (TOPCAT 侧无法做星等换算), 且不抛任何异常。
    """
    out: set[str] = set()                                                                           # 收集所有星表的星等列后缀
    for table in CATALOG_MAG_COLUMNS.values():                                                      # 逐张星表
        out.update(table)  # update 而非逐表判后缀: 不假设任何命名规律, 值里有多少列就并多少
    return frozenset(out)


MAGNITUDE_SUFFIXES: frozenset[str] = _magnitude_suffixes()                                  # 后缀集合在导入时算一次: 逐行判断时不能反复遍历全部星表


def _magnitude_error_suffixes() -> frozenset[str]:
    """从协议层权威**误差列**映射推导"误差列名后缀"集合 (与 :func:`_magnitude_suffixes` 对称)。

    存在的理由是**后缀匹配的固有漏洞**: 误差列名往往**以星等列名结尾**
    (``splus_dr4_e_u_pstotal`` 以 ``u_pstotal`` 结尾, ``ps1_gpsf_err`` 以
    ``gpsf`` 结尾), 于是纯 ``endswith`` 判定会把**误差列当成星等列**。
    实测后果: ``votable_document`` 给误差列挂上 ``unit="mag"`` (TOPCAT 侧会把
    0.003 角秒的不确定度当星等换算), 而按列取代表星等的调用点可能把
    0.003 当成一颗极亮源。

    Returns:
        所有星表发布过的误差列名 (如 ``gpsf_err`` / ``e_u_pstotal``)。
    """
    out: set[str] = set()                                                                         # 收集所有星表的误差列后缀
    for table in CATALOG_MAG_ERROR_COLUMNS.values():                                              # 逐张星表
        out.update(table)  # 同 _magnitude_suffixes: 值里有多少列就并多少, 不假设命名规律
    return frozenset(out)


MAGNITUDE_ERROR_SUFFIXES: frozenset[str] = _magnitude_error_suffixes()                      # 与星等后缀集同样在导入时算一次

# 本地可导出的格式全集 = 服务端支持集 + fits (本地转换)。
# fits 单列而不是并进 SUPPORTED_OUTPUT_FORMATS: 那个常量描述的是**线上**能力,
# 混进来会让人以为能给服务端传 output.fmt=fits。
LOCAL_EXPORT_FORMATS: tuple[str, ...] = tuple(SUPPORTED_OUTPUT_FORMATS) + ("fits",)  # fits 单列: 那个常量描述的是**线上**能力, 本地落盘多支持一种

# VOTable 的 version 属性与 xmlns namespace 必须同代: version="1.4" 配
# v1.3 namespace 会被严格校验的解析器直接拒收。这两个字面量是协议常量, 不随本仓
# 发布版本变化, 故不受"禁版本号"铁律约束。
VOTABLE_VERSION = "1.3"  # 协议常量非发布版本号: 不受"禁版本号"铁律约束
VOTABLE_XMLNS = "http://www.ivoa.net/xml/VOTable/v1.3"  # 必须与 version 同代, 混搭会被严格解析器拒收

# 落盘编码: CSV/TSV 用 utf-8-sig (Excel 双击打开不乱码的约定);
# JSON/VOTable/FITS 保持纯 utf-8 (BOM 会破坏标准解析器)。
BOM_ENCODING = "utf-8-sig"  # 仅分隔符文本用: Excel 双击打开不乱码
PLAIN_ENCODING = "utf-8"  # JSON/VOTable/FITS 用: BOM 会破坏标准解析器

# 行投影的固定列 (与 BestDownloader._rows_from_result 同一份): 0 行结果没有
# 行可并集, 表头只能由它出 —— 另写一份清单必然与行投影漂移, 而漂移的后果是
# "有行时列名是 A、0 行时表头是 B", 下游按表头建表结构时会静默错位。
BASE_COLUMNS: tuple[str, ...] = ("source_id", "ra", "dec", "snr", "class_star", "quality_flag")


def must_stay_text(text: str) -> bool:
    """判定一个**能解析为 float** 的取值是否仍必须保持字符串 (YZ-50 护栏)。

    两类形态能过 float() 却会在写成 double 时静默失真:
      1. **前导零** (``"007"``): 整数段长度 >1 且以 0 开头 — 写成 double 后
         前导零永久丢失, 下游按字符串做相等比较时不再命中;
      2. **超精度整数**: 纯整数字面量且绝对值 > 2^53 — double 只有 53 位
         尾数, ``9007199254740993`` 转过去静默变成 9007199254740992。
    带小数点/指数的取值本就是近似浮点语义, 不在此列。

    **本函数是全仓这类判定的单点**, 两个消费方都只认它:
    - :func:`column_is_numeric` —— VOTable/FITS 的列类型推断;
    - :func:`src.tap.formats.convert_table_rows` —— TAP 三格式 (含 CSV) 的
      单元格归一。缺了第二个消费方时, CSV 出口会把 ``gaia_dr3_18_source_id``
      的 ``4512921183874236032`` 写成 ``4.512921183874236e+18``, 且 VOTable
      与 CSV 对同一份数据给出两个不同的标识符 (实测 39 份真实快照 744,344
      个非空格里有 1,074 格不可逆损坏, 本判据 1,074/1,074 全中)。

    Args:
        text: 已 strip 的非空取值文本 (调用方保证能解析为 float)。

    Returns:
        必须保持字符串返回 True; 可安全写成 double 返回 False。
    """
    digits = text.lstrip("+-")  # 先去符号: 正负号不改变前导零与精度语义
    int_part = digits.split(".", 1)[0].split("e", 1)[0].split("E", 1)[0]  # 取整数段: 前导零只看它, 小数/指数段无关
    if len(int_part) > 1 and int_part.startswith("0"):  # 前导零: 写成 double 会永久丢零 (YZ-50)
        return True
    return digits.isdigit() and int(digits) > 2**53  # 超 2^53 整数: double 尾数装不下, 转过去静默丢精度 (YZ-50)


def column_is_numeric(rows: Sequence[dict], col: str) -> bool:
    """当 ``col`` 列全部非空取值都能解析为 float 时返回 True。

    Args:
        rows: 查询行记录 (``dict`` 列表)。
        col: 待判定的列名。

    Returns:
        全部非空取值可解析为 float 且不触发 :func:`must_stay_text` 护栏时
        返回 True; 列不存在或全为空返回 False。

    Note:
        按**实际取值**推断而不是按列名猜 (ra/dec/*mag): 实测列名带表前缀
        (``ps1_ra`` / ``gaia_dr3_18_ra``), 名称规则覆盖率不了, 猜错会让数值列
        被写成字符串列, 科学消费端的类型链条整段断裂。
        空值不参与判定 —— 稀疏列不该因个别空 cell 被误判成字符列。
        能解析为 float 不等于可以写成 double: 前导零与 >2^53 的整数字面量
        必须保持字符串 (:func:`must_stay_text`, YZ-50), 否则写出即静默失真。
    """
    seen = False                                                                                    # 是否见过任何行
    for row in rows:                                                                                # 逐行
        raw = row.get(col, "")
        if raw is None or str(raw).strip() == "":  # 空值跳过: 稀疏列靠非空取值定类型
            continue
        text = str(raw).strip()  # strip 一次复用: 下面的 parse 与护栏判的是同一份文本
        try:
            float(text)  # 经 str() 再 parse: 异常统一归一到 ValueError
        except (TypeError, ValueError):
            return False  # 整列统一判 char: 一个 FIELD 只有一个 datatype, 混排无法表达
        if must_stay_text(text):  # 前导零/超精度整数: 能 parse 也必须保持字符串, 写成 double 即静默失真 (YZ-50)
            return False
        seen = True                                                                                 # 标记有数据
    return seen  # seen 为假即列不存在或全空: 宁可保守也不给空列编造数值类型


def is_identifier_column(col: str) -> bool:
    """当列名看起来是**标识符**（而非测量值）时返回 True。

    Args:
        col: 列名。

    Returns:
        以 ``id`` / ``_id`` / ``_ids`` 结尾，或列名就是 ``id`` 时返回 True。

    Note:
        标识符列即使每个取值都能解析成 float 也必须保持字符串:
        ``ps1_source_id`` = ``"123456789"`` 写成 ``double`` 后，
        ① 前导零丢失 (``"007"`` → ``7``)；② 超过 2^53 的 id 精度丢失；
        ③ 下游按 ID 做相等比较时 ``"123"`` 与 ``123.0`` 不再相等。
        这是复测发现的真 bug: 按取值推断把 source_id 当成了数值列，
        而它在本仓的既有回归里是被钉死为字符串的。
    """
    key = str(col).strip().lower()  # 先归一: 列名大小写/空白方言不固定
    # 末尾兜底 endswith("id") 而非只认 _id/_ids: 形如 ps1objid 的列名
    # 真实存在, 漏判就会让它在 FITS/VOTable 里变成 double。
    return key == "id" or key.endswith("_id") or key.endswith("_ids") or key.endswith("id")  # 兜底含 ps1objid 这类实列名


def is_magnitude_column(col: str) -> bool:
    """当列名是星等列时返回 True (后缀来自协议层权威星等列映射)。

    Args:
        col: 列名 (可能带表前缀, 如 ``ps1_rpsf``)。

    Returns:
        列名以任一星表发布过的星等列名结尾时返回 True。

    Note:
        旧规则只判 ``endswith("mag")``, 漏掉 ``ps1_rpsf`` / ``splus_dr4_u_pstotal``
        这类实测列名 — 这些列拿不到 ``unit="mag"``, TOPCAT 侧无法做星等换算,
        且不抛任何异常。后缀集合改为由 :data:`CATALOG_MAG_COLUMNS` 现场推导
        (见 :func:`_magnitude_suffixes`), 不再有第二份会漂移的清单。
    """
    key = str(col).strip().lower()  # 与 is_identifier_column 同一归一, 两个判据共用一套列名口径
    if any(key.endswith(suffix) for suffix in MAGNITUDE_ERROR_SUFFIXES):  # 误差列先判: 它的名字往往以星等列名结尾
        return False  # 误差列不是星等列: 判成星等会让 unit="mag" 落到 0.003 角秒的不确定度上
    return any(key.endswith(suffix) for suffix in MAGNITUDE_SUFFIXES)  # any + 早停: 后缀表几十项, 命中即返回


def is_magnitude_error_column(col: str) -> bool:
    """当列名是星等**误差**列时返回 True (后缀同样来自协议层权威误差列映射)。

    Args:
        col: 列名 (可能带表前缀, 如 ``ps1_gpsf_err`` / ``splus_dr4_e_u_pstotal``)。

    Returns:
        列名以任一星表发布过的误差列名结尾时返回 True。

    Note:
        与 :func:`is_magnitude_column` 是**互补**的两半, 不是同一件事: 误差列
        被前者显式排除 (否则 ``unit="mag"`` 会挂到不确定度上), 于是本函数成为
        误差列的唯一入口。缺了它, 误差列的缺测哨兵就没有任何判据认领 ——
        实测 ps1 落盘 15,644 格 ``-999.0`` 全部来自 ``*_err`` 列 (AF4-P0-1),
        因为"只看星等列"的规则对它们一个都不成立。
    """
    key = str(col).strip().lower()  # 与另两个列名判据同一归一: 三处口径必须一致
    return any(key.endswith(suffix) for suffix in MAGNITUDE_ERROR_SUFFIXES)  # any + 早停: 命中即返回


def _station_prefixes() -> tuple[str, ...]:
    """推导**全部站名前缀**候选集 (星表 id ∪ 旧拼写别名 ∪ 全部表单表名), 长前缀优先。

    Returns:
        形如 ``("gaiaxp_photinfo_replenish_", "gaia_dr3_18_", ...)`` 的前缀元组。

    Note:
        长前缀优先是硬要求: ``jpas_u_`` 与 ``jpas_`` 同时存在时, 先剥短前缀会把
        ``jpas_ujava_`` 剥成 ``java_`` 开头的假列名。
        与 :func:`src.models._column_prefixes` 同源口径 (星表名 ∪ 表单表名), 但
        后者需要调用方给出 catalog; 序列化/导出路径拿到的是**已经拼好的列名**,
        没有站信息, 故这里取全站并集 —— 单站集合是它的子集, 不会漏判。
    """
    names: set[str] = set(CATALOG_PATHS)  # 星表 id 全集: 可查询站名
    names.update(CATALOG_ALIASES)  # 旧拼写别名同样是线上出现过的站名前缀
    for tables in CATALOG_FORM_TABLES.values():  # 逐星表
        names.update(tables)  # 表单表名: xpsp 的自行/视差列挂在共享表 gaiaxp_photinfo_replenish 上
    return tuple(sorted((n.lower() + "_" for n in names), key=len, reverse=True))  # 长前缀优先: 防 jpas_u_ 误剥 jpas_ujava_


STATION_PREFIXES: tuple[str, ...] = _station_prefixes()  # 导入时算一次: 逐格判定不能反复排序全体站名


def sentinel_exempt_column(col: str) -> bool:
    """按 **(站, 列)** 语义判定该列是否豁免下侧哨兵 (AH1-5 / AH3-04)。

    豁免名单 :data:`SENTINEL_EXEMPT_BARE_NAMES` 存的是**裸列名**
    (``pmra`` / ``pmdec`` / ``radial_velocity``), 而导出路径拿到的是**带站前缀**
    的响应列名。不先归一就比对, 等于"名单恒不命中"—— 实测 7 个真实需要豁免的
    列名里, 裸名规则只能命中 1 个:

    ==================================  ==========================
    真实列名                            剥站前缀后
    ==================================  ==========================
    ``gaia_dr3_18_pmra``                ``pmra``
    ``gaiaxp_photinfo_replenish_pmra``  ``pmra``
    ``stripe82_pmdec``                  ``pmdec``
    ``landolt_radial_velocity``         ``radial_velocity``
    ``jpas_u_pmra``                     ``pmra``
    ``ps1_rpsf`` (不得豁免)             ``rpsf``  -> 不命中
    ``xpsp_ra``  (不得豁免)             ``ra``    -> 不命中
    ==================================  ==========================

    Args:
        col: 列名 (带或不带站前缀均可)。

    Returns:
        剥掉最长站前缀后的裸名落在豁免名单内返回 True。
    """
    key = str(col).strip().lower()  # 与其余列名判据同一归一
    for prefix in STATION_PREFIXES:  # 长前缀优先: 先命中者即该列的站
        if key.startswith(prefix):
            return key[len(prefix):] in SENTINEL_EXEMPT_BARE_NAMES  # 剥站前缀后按裸名判: 列义与站无关
    return key in SENTINEL_EXEMPT_BARE_NAMES  # 无前缀的裸列名 (uss_dr1 的响应就是裸名)


def is_missing_sentinel(col: str, number: float) -> bool:
    """**全仓唯一的哨兵判定**: 该列该数值是否表示"无测量" (X7-P0-1 / AK4-004)。

    下侧(≈-1000)与上侧(99.0)两族哨兵在这里一次判完, 两个消费方都只调它:
      - 本模块 :func:`_sentinel_aware_cell` —— 泛用导出五格式 (CSV/TSV/JSON/VOTable/FITS);
      - :func:`src.tap.formats.convert_table_rows` —— TAP 三出口 (votable/csv/fits)。
    两侧各写一份判据正是 X7-P0-1 的成因: 同一行 ``pmra=-1500.0`` 走 delimited_text
    保住、走 TAP 出口变 NaN, 同一份事实出现两个版本。

    Args:
        col: 列名 (带站前缀; 前缀剥离在 :func:`sentinel_exempt_column` 内完成)。
        number: 已解析出的数值 (调用方保证是 float)。

    Returns:
        是"无测量"哨兵返回 True。
    """
    if number != number:  # NaN 已经是缺测表示, 不是"待判的哨兵"
        return False
    # 豁免列先退出: 高自行星的 pmra/pmdec 可达 ±1e4 mas/yr, radial_velocity 可为大负值,
    # 把它们抹成 NaN 就是 P0-03b 记的「静默丢真实自行」。
    if sentinel_exempt_column(col):
        return False
    if number <= BestSource.NULL_MAGNITUDE_SENTINEL:  # 下侧哨兵带 (≈-1000): 与行模型同阈值
        return True
    # 上侧哨兵 99.0 只在**测光族**判 (视差等天体测量列的 99.0 可以是合法毫秒值), 且
    # 误差列与星等列同判 —— 实测 splus_dr4 的 e_*_pstotal 与 *_pstotal 的 99.0 逐列同数
    # (各 54), 只判星等列就会漏掉误差列那一半。
    return (number >= BestSource.NULL_MAGNITUDE_UPPER_SENTINEL
            and (is_magnitude_column(col) or is_magnitude_error_column(col)))


def xml_escape(value: str) -> str:
    """对 VOTable 列名或单元格值做 XML 转义。

    Args:
        value: 待转义文本。

    Returns:
        转义后的文本; ``&`` 第一个被替换 (否则 ``&lt;`` 会被二次转义)。

    Note:
        必须逐字符转义而不是 f-string 直拼原始值: 某一列含 ``&``/``<``/``>``
        就产出坏 XML —— 这是一个由站点返回数据构成的 XML 注入面。
    """
    return (
        str(value)                                                                            # 统一转字符串: 数值与 None 都要能落进文本格式
        .replace("&", "&amp;")  # 顺序不可调换: & 必须第一个替, 否则 &amp; 会被二次转义
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")  # " 也转义: 列名会进 FIELD name 属性, 不转义会截断属性值
    )


def normalize_output_format(fmt: str) -> str:
    """把输出格式归一到白名单内; 不在白名单即抛错 (绝不静默回落)。

    Args:
        fmt: 调用方请求的输出格式 (大小写不敏感)。

    Returns:
        归一化后的小写格式名。

    Raises:
        ValueError: 格式不在 :data:`LOCAL_EXPORT_FORMATS` 内。

    Note:
        **这是本模块最重要的语义**: 未知格式 (含 ``fits``) 绝不能静默写成
        JSON 并把扩展名改成 ``.json`` —— 调用方请求 FITS 却拿到一个 JSON 文件,
        且**没有任何提示。静默给错格式比报错危险: 下游按 FITS 解析会以难懂的
        格式错误失败, 而按扩展名判断的调用方会以为拿到的是 JSON。因此一律
        显式抛错。
    """
    key = str(fmt).strip().lower()                                                               # 格式名归一: 大小写与空白差异不该落到未知键上
    # 白名单校验而非 if/elif 分发: 未知格式必须走到这里抛错。if/elif 分发的
    # else 分支正是"漏网之鱼"的来源 (见 docstring)。
    if key not in LOCAL_EXPORT_FORMATS:                                                             # 不在白名单即报错, 绝不静默改格式
        raise ValueError(  # 显式抛错而非回落 JSON: 静默给错格式, 下游会按错格式解析
            f"unsupported output format {fmt!r}; choose one of "
            f"{', '.join(LOCAL_EXPORT_FORMATS)}"
        )
    return key


def _sentinel_aware_cell(col: str, value: Any) -> Any:
    """把单元格里的测光缺失哨兵转 NaN, 其余原样透传 (P0-14 / AF4-P0-1)。

    审计轮次 AH3 记「serialization 五格式零哨兵转换」, 本轮按行为复验属实:
    ``ps1_gpsf = -1004.07`` 经本模块落盘后仍是 ``-1004.07`` —— 一个**缺测**
    被导出成一颗 "-1004 等" 的源, 而同仓 TAP 出口
    (:func:`src.tap.formats.convert_table_rows`) 早已把它转成 NaN。两个出口
    对同一份数据给出两个值, 且前者会把任何按该列做的统计彻底带偏 (均值被拉到
    -1004 量级)。

    **判据不写在这里** —— 本函数只负责"取到值、转 NaN、否则原样", 判定本身下沉到
    :func:`is_missing_sentinel`, TAP 出口调的是同一个函数。此前两侧各写一份
    (这里是 ``is_magnitude_column`` + 下侧阈值, TAP 侧是"所有列" + 下侧阈值),
    于是 ``ps1_gpsf_err = -999.0`` 在本出口原样落盘、在 TAP 出口变 NaN,
    ``pmra = -1500.0`` 则恰好相反 —— 同一份事实两个版本 (X7-P0-1)。

    Args:
        col: 列名 (可能带表前缀, 如 ``ps1_gpsf``)。
        value: 原始单元格值 (任意形态)。

    Returns:
        判为缺测哨兵时返回 ``float('nan')``; 否则原样返回。
    """
    try:
        number = float(str(value).strip())  # 经 str 再转: 单元格里存的多是 "18.2" 这类文本
    except (TypeError, ValueError):
        return value  # 不可解析即非数值, 交给上层按文本处理
    if is_missing_sentinel(col, number):  # 单点判据: 与 TAP 出口同一函数, 两侧不可能再分叉
        return float("nan")  # 写 NaN: 与 TAP 出口同表示, 两边读回一致
    return value  # 真实取值原样透传


def delimited_text(rows: Sequence[dict], delimiter: str) -> str:
    """把行记录渲染为分隔符文本 (CSV 或 TSV), 统一做公式注入消毒。

    Args:
        rows: 查询行记录。
        delimiter: 字段分隔符 (``","`` 或 ``"\\t"``)。

    Returns:
        含表头的完整文本; 空输入返回空串 (由调用方决定是否写表头)。

    Note:
        列序取**排序后的列名并集**而不是 ``rows[0].keys()``: BEST 的响应可能
        因约束不同而列集不同, 取首行键会让缺列的行在回读时错位。
        每个单元格都过 ``csv_safety.sanitize_cell`` (Q-06): 公式向量
        (``=cmd|...``) 原样进电子表格就是 CSV 公式注入。
    """
    if not rows:                                                                                   # 空结果单独处理: 空表与"没查到"语义不同
        return ""
    cols = sorted({key for row in rows for key in row})  # 排序并集: 与另两处同一口径, 换格式后列序不变
    buffer = io.StringIO()  # 内存缓冲先拼全文: 交给调用方一次性原子落盘
    writer = csv.writer(buffer, delimiter=delimiter)  # 交给 csv 管引号转义: 手写 join 遇分隔符就破行
    writer.writerow(cols)  # 表头即列序来源: 回读按位置对齐, 顺序一漂移整表错位
    for row in rows:                                                                                # 逐行写出
        # get(col,"") 补空串 + 逐格消毒 + 星等列哨兵转 NaN (P0-14, 顺序不可换:
        # 先把缺测变成 NaN 再消毒, 反过来会让 "nan" 被当普通文本再走一遍公式消毒)
        writer.writerow([sanitize_cell(_sentinel_aware_cell(col, row.get(col, ""))) for col in cols])
    return buffer.getvalue()


def empty_table_text(columns: Sequence[str], delimiter: str) -> str:
    """只写表头的分隔文本 (0 行结果的可辨识产物形态)。

    Args:
        columns: 表头列名 (0 行场景通常取 :data:`BASE_COLUMNS`)。
        delimiter: 字段分隔符 (``","`` 或 ``"\\t"``)。

    Returns:
        只有一行表头的文本; ``columns`` 为空时返回空串。

    Note:
        0 行结果落一个空串会在 CSV 路径上变成**只含 BOM 的 3 字节文件** ——
        字节上与"写坏的空文件"不可区分, 下游读成"这片天区没源"。补一行表头
        之后两者在字节层即可分辨, 且表结构仍然可解析成 0 行。
    """
    if not columns:  # 连列名都没有: 退成空串, 由调用方的空结果闸去判, 这里不编列
        return ""
    buffer = io.StringIO()  # 与 delimited_text 同一拼装口径: 交给调用方一次性原子落盘
    csv.writer(buffer, delimiter=delimiter).writerow(list(columns))  # 交给 csv 转义: 列名同样可能含分隔符
    return buffer.getvalue()


def json_document(rows: Sequence[dict], *, total: Optional[int] = None) -> str:
    """把行记录渲染为 JSON 文本 (``sources`` 列表 + 可选 ``total``)。

    Args:
        rows: 查询行记录。
        total: 服务端报告的总行数; 提供时一并写入, 让调用方能区分
            "只有这么多" 与 "被 max_rows 截断"。

    Returns:
        indent=2 的 JSON 文本 (``ensure_ascii=False`` 保中文可读)。
    """
    payload: dict[str, Any] = {"sources": list(rows)}  # 键名与线上响应同构, 消费端解析器不必分叉
    if total is not None:  # is not None 而非真值: total=0 是"确认零行", 不是"未报告"
        payload["total"] = total
    import json  # 函数内导入: JSON 序列化 (只在 json_document 被调用时才需要)

    return json.dumps(payload, indent=2, ensure_ascii=False)


def votable_document(
    rows: Sequence[dict],
    *,
    catalog: str = "",
    nrows: Optional[int] = None,
) -> str:
    """把行记录渲染为 VOTable XML 文本 (IVOA 标准表格式, 供 TOPCAT/astropy 读)。

    Args:
        rows: 查询行记录。
        catalog: 星表 id (写进 ``RESOURCE`` 名, 供溯源)。
        nrows: 表头 ``nrows`` 属性值; 缺省按 ``len(rows)``。

    Returns:
        完整 VOTable 文档文本。

    Note:
        列类型按**实际取值**推断 (:func:`column_is_numeric`): 数值列写
        ``datatype="double"``, 否则 ``char`` + ``arraysize="*"``。
        ra/dec 列补 ``unit="deg"``, 星等列补 ``unit="mag"`` —— 缺了 unit,
        TOPCAT 侧无法做坐标/星等运算。
        所有列名与单元格值都过 :func:`xml_escape` (P2-12/S-1 XML 注入面);
        **不过** ``sanitize_cell`` —— 公式消毒是电子表格 (CSV/TSV) 的威胁模型,
        VOTable 由 XML 解析器读取, 加引号前缀是对科学数据的永久改写 (YZ-49)。
        0 行结果仍按 :data:`BASE_COLUMNS` 出列头, 与 CSV 出口的
        ``empty_table_text`` 同口径 (YZ-48): 同一份空结果在两个出口给出
        两套表结构, 下游按表头建表时会静默错位。
    """
    out = ['<?xml version="1.0" encoding="UTF-8"?>\n']  # 逐段拼字符串再 join: 转义只在这一层发生
    out.append(f'<VOTABLE version="{VOTABLE_VERSION}" xmlns="{VOTABLE_XMLNS}">\n')
    # catalog 为空时用中性占位名: RESOURCE 的 name 是必填属性, 空串会让
    # 严格校验的解析器拒收整个文档。
    resource = xml_escape(catalog) if catalog else "query"  # 空值用中性占位: name 必填, 空串会被拒收
    out.append(f'  <RESOURCE name="BEST {resource}" type="results">\n')  # type="results": 与 src/tap/formats.py 的 VOTable 出口同口径 (YZ-52)
    # nrows 优先用调用方报的值 (服务端总行数): 它与实际写出的行数可能
    # 不同 (截断场景), 混用会误导下游判断数据是否完整。
    out.append(f'    <TABLE nrows="{nrows if nrows is not None else len(rows)}">\n')  # 截断场景下与服务端总行数一致, 不混用
    # 0 行时列头取 BASE_COLUMNS 而非空集 (YZ-48): CSV 出口的 0 行产物就是这
    # 六列表头, VOTable 若一个 FIELD 都不写, 两个出口对同一份空结果给出两套
    # 表结构。0 行无值可推断类型, 全部按 char 声明。
    cols = sorted({key for row in rows for key in row}) if rows else list(BASE_COLUMNS)  # 排序并集: 与另两处同一口径, 换格式后列序不变
    for col in cols:                                                                                # 逐列判断类型
        # 标识符列 (source_id 等) 即使全数值也保持字符串 — 见 is_identifier_column
        numeric = bool(rows) and column_is_numeric(rows, col) and not is_identifier_column(col)  # 标识符列豁免: 前导零/精度靠类型保住
        datatype = "double" if numeric else "char"
        attrs = f' datatype="{datatype}"'
        # arraysize="*" 是 VOTable 1.3 对变长字符串的必需属性:
        # 缺了它, 严格解析器会把 char 列当成单字符。
        if not numeric:                                                                         # 非数值列不进数值数组
            attrs += ' arraysize="*"'  # 1.3 对变长字符串的必需属性, 缺了 char 列被当单字符
        # 坐标列判定容忍表前缀 (ps1_ra): 实测列名都带前缀, 精确
        # 相等会全部落空, unit="deg" 一个都加不上。
        if col in ("ra", "dec") or col.endswith(("_ra", "_dec")):
            attrs += ' unit="deg"'  # 容忍表前缀: 精确相等会让实测列名全部落空
        elif is_magnitude_column(col):
            attrs += ' unit="mag"'  # 星等后缀集判定: 漏判则 TOPCAT 侧无法换算, 且不报错
        out.append(f'      <FIELD name="{xml_escape(str(col))}"{attrs}/>\n')  # 列名过转义: 坏 XML 面
    if rows:                                                                                        # 有行才写数据段: 0 行只出列头
        out.append('      <DATA>\n')
        out.append('        <TABLEDATA>\n')
        for row in rows:                                                                            # 逐行填值
            # 单元格只过 xml_escape 不过 sanitize_cell (YZ-49): 公式消毒防的是
            # 电子表格把 =cmd|... 当公式执行, VOTable 的消费方是 XML 解析器,
            # 在这里加引号前缀是把 "-2+3" 永久改写成 "'-2+3" 的数据损坏。
            cells = "".join(  # 每格只转义不消毒: 消毒是 CSV/TSV 出口的威胁模型
                # 星等列的测光哨兵先转 NaN (P0-14, 与 CSV 出口同判据): FIELD
                # 已按 double 声明 unit="mag", 单元格里留 -1004.07 等于告诉
                # TOPCAT 这是一颗 -1004 等的源。
                f"<TD>{xml_escape(str(_sentinel_aware_cell(col, row.get(col, ''))))}</TD>"
                for col in cols                                                                     # 逐列取值
            )
            out.append(f"          <TR>{cells}</TR>\n")
        out.append('        </TABLEDATA>\n')
        out.append('      </DATA>\n')
    out.append('    </TABLE>\n')
    out.append('  </RESOURCE>\n')
    out.append('</VOTABLE>\n')
    return "".join(out)


def write_fits(path: Path, rows: Sequence[dict], catalog: str = "") -> None:
    """把查询行写成 FITS 二进制表 (本地转换; 服务端不支持 fits 输出)。

    Args:
        path: 目标文件路径 (由调用方保证已做路径穿越校验)。
        rows: 查询行记录。
        catalog: 星表 id (写进 HDU 头字段 ``CATALOG`` 供溯源)。

    Raises:
        RuntimeError: astropy 未安装 —— 明确提示改用 csv/votable 走零依赖导出,
            不让 ``ImportError`` 裸奔。
        ValueError: 列数超过 999 —— FITS 标准对 BinTable 的 TFIELDS 硬顶就是
            999 列, 超了写出来也是非法文件 (YZ-45); 显式 fail-closed 并让
            调用方裁剪列清单或改用 votable/csv。

    Note:
        服务端不返回 FITS (请求 fits 拿到的是结果页 HTML), 故按
        ``references/best-database-guide.md`` 的"导出需本地转换"口径在本地由
        行记录构造 ``BinTableHDU``。数值列 float64 (``format="D"``), 空 cell 写
        NaN 保持列类型不塌; 字符列定长字符串, 宽度按 **utf-8 字节数**取该列
        最长值 (``{width}A`` 的单位是字节, 按字符数算会让非 ASCII 列整份
        UnicodeEncodeError, YZ-25)。
    """
    try:
        # 延迟导入: astropy 是重依赖, 仅 fits 导出路径需要; 装不上时其余格式
        # (csv/txt/json/votable) 仍可用
        from astropy.io import fits
    except ImportError as exc:  # pragma: no cover - 环境相关
        raise RuntimeError(
            "fits export requires astropy (pip install astropy); "
            "use fmt='csv'/'votable' for a dependency-free export"
        ) from exc

    rows = list(rows)  # 先物化成 list: 下面按行多次遍历, 生成器只能消费一次
    # 列集取排序后的并集而不是首行键序 (YZ-24): 与 delimited_text /
    # votable_document 同一口径 —— 首行缺的列按旧写法会整列静默丢失,
    # 而同一份行记录换 FORMAT 后列集不该变。
    cols = sorted({key for row in rows for key in row})  # 排序并集: 与 CSV/VOTable 同一口径, 缺列行按空值补齐
    if len(cols) > 999:  # FITS 标准对 BinTable 的 TFIELDS 硬顶 999 列: 超了写出来也是非法文件, 显式 fail-closed (YZ-45)
        raise ValueError(
            f"FITS supports at most 999 columns (got {len(cols)}); "
            "narrow the column list or use fmt='votable'/'csv'"
        )
    columns = []                                                                                    # 列定义表
    for col in cols:                                                                                # 逐列
        # 标识符列保持字符串 (与 votable_document 同一口径)
        if column_is_numeric(rows, col) and not is_identifier_column(col):  # 与 votable_document 同一口径
            columns.append(                                                                         # 加入列
                fits.Column(                                                                        # 构造 FITS 列
                    name=col,                                                                       # 列名
                    # D = float64: 星表数值列是双精度, 写 E(单精度) 会
                    # 丢掉 astrometric 级别的小数位。
                    format="D",  # D = float64: 写 E 会丢 astrometric 级小数
                    array=[                                                                         # 值数组
                        float(str(_sentinel_aware_cell(col, r.get(col, ""))).strip())
                        if str(r.get(col, "")).strip() else float("nan")  # 空 cell 写 NaN, 列类型不塌
                        for r in rows                                                               # 逐行取该列的值
                    ],
                )
            )
        else:
            # 字符列: 定长字符串, 宽度按 utf-8 字节数取该列最长值 (空表退化为 1)。
            # {width}A 的单位是字节不是字符: 按 len(str) 算, 非 ASCII 取值
            # (中文目标名等) 会在 astropy 写出时整份崩 UnicodeEncodeError (YZ-25)。
            width = max((len(str(r.get(col, "")).encode("utf-8")) for r in rows), default=1) or 1  # 宽度按字节数: 按字符数算非 ASCII 列必崩
            columns.append(                                                                         # 文本列同理
                fits.Column(                                                                        # FITS 列
                    name=col, format=f"{width}A", array=[str(r.get(col, "")) for r in rows]  # {width}A 定长: 写死会截断长取值
                )
            )
    hdu = fits.BinTableHDU.from_columns(columns, name="BEST")  # HDU 名固定 BEST: 下游按 HDU 名而非文件名识别来源
    # 头字段记录来源星表与行数, 供下游溯源 (不写版本号, 全仓铁律)
    hdu.header["CATALOG"] = (catalog or "unknown", "BEST catalog id")  # 空 catalog 记 unknown, 不留空值
    hdu.header["NROWS"] = (len(rows), "rows in this export")
    # 落盘 (IO): overwrite=True 让重跑导出覆盖旧文件, 由调用方决定覆盖语义
    fits.HDUList([fits.PrimaryHDU(), hdu]).writeto(path, overwrite=True)  # 必须带 PrimaryHDU 才成合法 FITS
