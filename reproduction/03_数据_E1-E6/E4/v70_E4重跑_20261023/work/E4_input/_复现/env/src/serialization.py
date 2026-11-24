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
# 协议层权威表 (星等列后缀集现场推导 + 线上格式白名单)
from src.csv_safety import sanitize_cell  # 本地唯一消毒实现: 序列化层不复制 (Q-06)
from src.protocol import CATALOG_MAG_COLUMNS, SUPPORTED_OUTPUT_FORMATS  # 协议层权威: 不另写第二份清单

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


def column_is_numeric(rows: Sequence[dict], col: str) -> bool:
    """当 ``col`` 列全部非空取值都能解析为 float 时返回 True。

    Args:
        rows: 查询行记录 (``dict`` 列表)。
        col: 待判定的列名。

    Returns:
        全部非空取值可解析为 float 返回 True; 列不存在或全为空返回 False。

    Note:
        按**实际取值**推断而不是按列名猜 (ra/dec/*mag): 实测列名带表前缀
        (``ps1_ra`` / ``gaia_dr3_18_ra``), 名称规则覆盖率不了, 猜错会让数值列
        被写成字符串列, 科学消费端的类型链条整段断裂。
        空值不参与判定 —— 稀疏列不该因个别空 cell 被误判成字符列。
    """
    seen = False                                                                                    # 是否见过任何行
    for row in rows:                                                                                # 逐行
        raw = row.get(col, "")
        if raw is None or str(raw).strip() == "":  # 空值跳过: 稀疏列靠非空取值定类型
            continue
        try:
            float(str(raw).strip())  # 经 str() 再 parse: 异常统一归一到 ValueError
        except (TypeError, ValueError):
            return False  # 整列统一判 char: 一个 FIELD 只有一个 datatype, 混排无法表达
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
    return any(key.endswith(suffix) for suffix in MAGNITUDE_SUFFIXES)  # any + 早停: 后缀表几十项, 命中即返回


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
        writer.writerow([sanitize_cell(row.get(col, "")) for col in cols])  # get(col,"") 补空串 + 逐格消毒
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
        所有列名与单元格值都过 :func:`xml_escape` (P2-12/S-1 XML 注入面)。
    """
    out = ['<?xml version="1.0" encoding="UTF-8"?>\n']  # 逐段拼字符串再 join: 转义只在这一层发生
    out.append(f'<VOTABLE version="{VOTABLE_VERSION}" xmlns="{VOTABLE_XMLNS}">\n')
    # catalog 为空时用中性占位名: RESOURCE 的 name 是必填属性, 空串会让
    # 严格校验的解析器拒收整个文档。
    resource = xml_escape(catalog) if catalog else "query"  # 空值用中性占位: name 必填, 空串会被拒收
    out.append(f'  <RESOURCE name="BEST {resource}">\n')
    # nrows 优先用调用方报的值 (服务端总行数): 它与实际写出的行数可能
    # 不同 (截断场景), 混用会误导下游判断数据是否完整。
    out.append(f'    <TABLE nrows="{nrows if nrows is not None else len(rows)}">\n')  # 截断场景下与服务端总行数一致, 不混用
    if rows:                                                                                        # 有行才进这一段
        cols = sorted({key for row in rows for key in row})  # 同一口径取列序: 换格式后列序不变
        for col in cols:                                                                            # 逐列判断类型
            # 标识符列 (source_id 等) 即使全数值也保持字符串 — 见 is_identifier_column
            numeric = column_is_numeric(rows, col) and not is_identifier_column(col)  # 标识符列豁免: 前导零/精度靠类型保住
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
        out.append('      <DATA>\n')
        out.append('        <TABLEDATA>\n')
        for row in rows:                                                                            # 逐行填值
            # 单元格双重处理: sanitize_cell 防公式注入, xml_escape 防
            # XML 注入 — 两者面对的字符集不同, 缺一不可。
            cells = "".join(  # 每格双重处理: 消毒防公式注入, 转义防 XML 注入
                f"<TD>{xml_escape(sanitize_cell(str(row.get(col, ''))))}</TD>"
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

    Note:
        服务端不返回 FITS (请求 fits 拿到的是结果页 HTML), 故按
        ``references/best-database-guide.md`` 的"导出需本地转换"口径在本地由
        行记录构造 ``BinTableHDU``。数值列 float64 (``format="D"``), 空 cell 写
        NaN 保持列类型不塌; 字符列定长字符串, 宽度取该列最长值。
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
    # 列集取首行键序而非并集: FITS 列一旦定为定长字符串, 混长度的并集
    # 会让所有字符列虚胖; 数值列无宽度问题, 故可接受这个简化。
    cols = list(rows[0].keys()) if rows else []  # 取首行键序: 定长字符串列用并集会虚胖
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
                        float(str(r.get(col, "")).strip())
                        if str(r.get(col, "")).strip() else float("nan")  # 空 cell 写 NaN, 列类型不塌
                        for r in rows                                                               # 逐行取该列的值
                    ],
                )
            )
        else:
            # 字符列: 定长字符串, 宽度取该列最长值 (空表退化为 1)
            width = max((len(str(r.get(col, ""))) for r in rows), default=1) or 1  # 宽度取本列最长值, 空表 default=1
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
