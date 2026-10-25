"""src.tap.formats — TAP 结果序列化 (votable / csv / fits)。

能力边界: 把执行器产出的行记录序列化为 TAP 结果文档: VOTable (astropy,
QUERY_STATUS INFO + OVERFLOW 标记按 DALI 置于 TABLE 之后)、CSV (公式注入消毒接
src.csv_safety; 截断位走响应头而非体内)、FITS (astropy BinTable, 截断位走头卡
TAPOVR 关键字); 空结果与 MAXREC=0 元数据响应保留列名。截断位一律由
SerializedResult.overflow 外带, 供同步/异步两面挂同一个 X-TAP-Overflow 头。
边界: BEST ≈-1000 空值哨兵转 NaN (与 src.models.BestSource 同一阈值);
XML 只由 ElementTree/astropy 生成, 绝不解析外部 XML。
白盒锚点: references/ALGORITHM-SPEC.md §6 (TAP 适配层锚点)。

历史来源: pybest 打包产物 (git 6f00efeb^〔本仓历史已无此对象〕〔本仓历史已无此对象〕) ``pybest/tap/formats.py`` (git 6f00efeb^〔本仓历史已无此对象〕); 原
``pybest.serialization`` 的两个helper 按能力边界改写: 哨兵转换本地实现,
CSV 消毒改接本包唯一实现 src.csv_safety (Q-06)。DALI: ivo://ivoa.net/std/TAP
(规范引用, 无 DOI)。

TAP 结果序列化器。
"""
from __future__ import annotations

import csv  # 标准库: CSV 写出 (DictWriter, 公式注入消毒后逐格写入)
import math  # 标准库: NaN 产生 (哨兵值转换的落点)
from dataclasses import dataclass  # 标准库: 序列化结果载体
from io import BytesIO, StringIO  # 标准库: 二进制/文本内存缓冲 (XML 与 FITS 落盘前拼接)
from typing import Any, Sequence  # 标准库: 行记录与列名序列类型标注

# ElementTree 仅用于生成对外 XML, 绝不解析外部输入 (注入面为零)
from xml.etree import ElementTree as ET  # nosec B405

from src.csv_safety import sanitize_cell  # 本仓唯一消毒实现, 序列化层不复制 (Q-06 跨能力边界)

# 哨兵判据只认 src.serialization.is_missing_sentinel 这一个单点 —— 与泛用导出
# (delimited_text / votable_document / write_fits) 同源。此前本函数自带一份
# "所有列一律 <= -999 即 NaN" 的判据, 与导出侧的"只判星等列"分叉, 同一行
# pmra=-1500.0 走 TAP 变 NaN、走 delimited_text 保住 (X7-P0-1 / AK4-004)。
from src.serialization import is_missing_sentinel, must_stay_text  # 哨兵单点 + 标识符护栏 (YZ-50)

try:  # astropy 为可选依赖 (environment.yaml 数据互操作面); 缺失时 votable/fits
    from astropy.io.votable import from_table  # 通道显式失败而非静默降级
    from astropy.io.votable.tree import Info
    from astropy.table import Table
except ImportError:  # pragma: no cover - 环境相关
    from_table = None  # type: ignore[assignment]
    Info = None  # type: ignore[assignment]
    Table = None  # type: ignore[assignment]


# DALI 截断信号的头名与取值: 同步面 (service._sync) 与异步面
# (uws_service._range_response) 必须同口径。两处各写一份字面量迟早漂成两个名字,
# 客户端便只在一条路径上认得截断 —— 那正是 A4-03 的失灵形态。
OVERFLOW_HEADER = "X-TAP-Overflow"  # 头名: 服务端自定义, DALI 只规定 VOTable 的 INFO 标记
OVERFLOW_VALUE = "true"  # 取值固定字符串: 客户端按字面量判, 写成布尔会读成 None


@dataclass(frozen=True)
class SerializedResult:
    """一次序列化产出: 响应体字节 + media_type + 建议文件扩展名 + 截断位。"""

    body: bytes  # 响应体字节, 已在序列化阶段定型
    media_type: str  # TAP 出口的 media type (与 FORMAT 归一结果一致)
    extension: str  # 建议落盘扩展名, 免得调用方自己猜
    # 截断位随序列化结果一起出来: 只有它能跨过"先落盘、后取回"那道异步边界 ——
    # CSV 的载荷里放不下标记 (见 serialize_result), 位不外带就会在异步面上丢失
    overflow: bool = False


# FORMAT 别名表: DALI 允许客户端传短名或 media type; 权威消费方是 normalize_format,
# 上游来源为 IVOA TAP/DALI 的 FORMAT 参数约定 (短名与 MIME 双向归一)。
_FORMAT_ALIASES = {  # 出口只认三个规范名, 客户端传什么都先过这张表
    "votable": "votable",
    "application/x-votable+xml": "votable",
    "application/xml": "votable",
    "text/xml": "votable",
    "csv": "csv",
    "text/csv": "csv",
    "fits": "fits",
    "application/fits": "fits",
}


def normalize_format(value: str | None) -> str:
    """把 TAP FORMAT 参数归一到 ``votable`` / ``csv`` / ``fits`` 三选一。

    Args:
        value: 客户端 FORMAT 值; None/空串按 DALI 默认 votable 处理,
            大小写与首尾空白不敏感。

    Raises:
        ValueError: 不在别名表内 — 显式拒绝而非猜一个格式, 避免客户端拿到
            非预期 media type。

    Returns:
        str: 归一后的规范格式名。
    """
    key = (value or "votable").strip().lower()  # DALI 缺省 votable; 大小写/空白不敏感
    if key not in _FORMAT_ALIASES:                                               # 未知格式名直接报错: 静默回落会把"请求 FITS 拿到 CSV"变成静默错误
        raise ValueError("Unsupported TAP FORMAT; choose votable, csv, or fits")  # 显式拒绝, 不替客户端猜
    return _FORMAT_ALIASES[key]  # 归一后出口只有三种规范名


def convert_table_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """BEST 空值哨兵 (约 -1000) 转 NaN, 真数字解析为 float。

    与 ``BestSource.NULL_MAGNITUDE_SENTINEL`` 共用同一阈值: 类型化 TAP 导出
    与行模型对"无测量"的定义必须一致 (实测锚点: ps1_gpsf=-1004.07 /
    ps1_gpsf_err=-999.0)。空串与 None 归一为 None; 非数字字符串原样透传,
    不猜测、不强转。

    **能 float() 不等于该转 float** (YZ-50 的第二个消费方): 标识符列过
    :func:`src.serialization.must_stay_text` 后原样留文本 —— 站点给的
    ``gaia_dr3_18_source_id`` 是 ``4512921183874236032`` (>2^53), 转成 double
    变 ``4.512921183874236e+18``, 标识符就此不可逆地丢精度, 而 VOTable 出口
    经 :func:`src.serialization.column_is_numeric` 有同一道护栏: 两个出口对
    同一份数据给出两个不同的标识符, 下游按哪一份去 join 都是错的。
    护栏判据只认值形态 (前导零 / 超 2^53 整数字面量), 不按列名猜, 所以新
    星表新增的标识符列不必改这里就自动受保护。

    **哨兵判据不在本函数里** (X7-P0-1 / W5b-P1-1): 下侧哨兵原先在此处
    ``if number <= floor`` 对**所有列**无差别生效, 而泛用导出侧只判星等列,
    于是同一行 ``pmra = -1500.0`` (合法自行) 经 TAP 出口变 NaN、经
    :func:`src.serialization.delimited_text` 原样保住。现两侧同调
    :func:`src.serialization.is_missing_sentinel`, 该单点先按**站前缀归一**查
    ``pmra``/``pmdec``/``radial_velocity`` 豁免名单 (``gaiaxp_photinfo_replenish_pmra``
    这类带站前缀的写法也因此命中, 见 :func:`src.serialization.sentinel_exempt_column`),
    再判上下两侧哨兵带 —— 同一份事实只可能有一个版本。
    """
    converted: list[dict[str, Any]] = []                                                            # 转换结果表
    for row in rows:                                                                                # 逐行
        out: dict[str, Any] = {}                                                                    # 输出行
        for key, value in row.items():                                                              # 逐键值
            text = str(value).strip() if value is not None else ""  # None 与空串先归一
            if not text:                                                                            # 空值不算数字
                out[key] = None                                                    # 空值原样留 None, 不转 0.0 (记 0 会把"无值"伪装成"零")
                continue
            if must_stay_text(text):                                                                # 护栏先行: 前导零/超 2^53 的整数字面量必须保持文本
                out[key] = value  # 原样留字符串: 写成 double 即不可逆损坏 (见 docstring)
                continue
            try:
                number = float(text)                                                                # 非空才尝试转数字
            except ValueError:
                out[key] = value  # 非数字原样透传: 不猜测、不强转
                continue
            if is_missing_sentinel(key, number):  # 单点哨兵判据: 与泛用导出同一函数, 含豁免名单与上下两侧带
                out[key] = math.nan
            else:
                out[key] = number                                                                 # 真值原样出函
        converted.append(out)                                                                       # 收进行
    return converted


def _table(
    rows: list[dict[str, Any]],
    columns: Sequence[str] | None = None,
) -> "Table":
    """把行记录包装成 astropy Table (空结果时用列名占位保住元数据)。

    Raises:
        RuntimeError: astropy 未安装 — 明确要求改用 FORMAT=csv 走零依赖导出,
            不静默降级成空表 (那会把"缺依赖"伪装成"无数据")。

    Note:
        ``Table(rows=...)`` 对含 None/空值的列一律给 object dtype: VOTable
        写出时 astropy 兜底成 unicodeChar, 而 FITS 对 object 列直接抛
        TypeError —— 异常再逃出 ``service._sync`` 的软错误收敛, 同步面就是
        零 HTTP 响应 (YZ-05)。这里把 object 列归一为字符串列 (None -> ""),
        让 VOTable/FITS 两个出口对同一份空值口径一致。
    """
    if Table is None:  # pragma: no cover - 环境相关
        raise RuntimeError(
            "votable/fits TAP output requires astropy; use FORMAT=csv for a "
            "dependency-free export"
        )
    converted = convert_table_rows(rows)                                                            # 先做类型归一
    if converted:                                                                                   # 转换后才判非空
        table = Table(rows=converted)                                                               # 行记录直接成表: 含 None 的列会给 object dtype
        for name in table.colnames:                                                                 # 逐列检查 dtype
            if table[name].dtype == object:  # object 列 = 含 None 或混合类型: FITS 写不了, 必须归一 (YZ-05)
                table[name] = ["" if value is None else str(value) for value in table[name]]  # None 归空串: 与 VOTable 的 unicodeChar 兜底同口径
        return table
    if columns:                                                                                     # 有列才写表头
        return Table(names=list(columns), dtype=["U1"] * len(columns))  # 空表保列名, TOPCAT 才看得到表结构
    return Table()  # 无行又无列名: 交空表, 不编造列


def serialize_result(
    rows: list[dict[str, Any]],
    output_format: str,
    *,
    columns: Sequence[str] | None = None,
    overflow: bool = False,
) -> SerializedResult:
    """把行记录序列化为请求的 TAP media type。

    Args:
        rows: 执行器产出的行记录。
        output_format: 客户端 FORMAT (经 :func:`normalize_format` 归一)。
        columns: 显式列清单 (空结果/元数据响应用于保住列名)。
        overflow: MAXREC 是否截断; 三个分支各有可判定的标记 ——
            votable 走 DALI 的 ``QUERY_STATUS=OVERFLOW`` INFO, fits 走
            BinTable 头卡的 ``TAPOVR`` 关键字, csv 走响应头
            ``X-TAP-Overflow`` (由调用方从 :attr:`SerializedResult.overflow`
            取出后挂上)。CSV 载荷内**不**插注释行: 注释不是 RFC 4180 的一等
            公民, 严格解析器会把那行读成一条列数不符的数据行, 凭空多出
            一行 NaN —— 那是用一个假信号换一个真故障。头字段对三种格式
            等价可判, 故 CSV 的截断位走头而不走体内。

    Raises:
        ValueError: FORMAT 不受支持。
        RuntimeError: votable/fits 需要 astropy 而环境缺失。

    Returns:
        SerializedResult: 响应体 + media_type + 扩展名。
    """
    fmt = normalize_format(output_format)  # 先归一: 下面三个分支只认规范名
    if fmt == "votable":
        if from_table is None or Info is None:  # pragma: no cover - 环境相关
            raise RuntimeError(
                "votable TAP output requires astropy; use FORMAT=csv for a "
                "dependency-free export"
            )
        votable = from_table(_table(rows, columns))                                     # VOTable 走标准序列化器: 免得手拼 XML 与规范不一致
        votable.resources[0].type = "results"  # DALI 要求结果型资源标 results
        if not overflow:  # 截断时只发 OVERFLOW 不发 OK (YZ-51): 两个状态同现且 OK 在前, 取首个 INFO 的客户端会把截断结果当成完整的
            votable.resources[0].infos.insert(0, Info(name="QUERY_STATUS", value="OK"))  # 状态标记置首
        xml_buffer = BytesIO()                                                                      # 先渲到内存
        votable.to_xml(xml_buffer)                                                                  # 序列化为字节
        body = xml_buffer.getvalue()  # 纯内存字节: 下面的标记插桩不触网
        if overflow:                                                                                # 有截断才需要补 INFO
            # Astropy 把 Resource.infos 写在 TABLE 之前, 而 DALI 要求 OVERFLOW
            # 标记位于 TABLE 之后; 此处字节是本地 Astropy 刚生成的, 因此按
            # 固定锚点做字节级插入, 绝不重新解析外部 XML。
            closing_resource = b" </RESOURCE>"                                                      # 闭合标签位置
            insert_at = body.rfind(closing_resource)  # 末个 </RESOURCE> 即结果集收尾锚点
            if insert_at < 0:                                                                       # 找不到插入点就只能在末尾追加
                raise RuntimeError("Astropy generated a VOTable without RESOURCE")  # 缺锚点即停, 不猜位置
            overflow_info = b'  <INFO name="QUERY_STATUS" value="OVERFLOW"/>\n'                     # 截断标记的 XML 片段
            body = body[:insert_at] + overflow_info + body[insert_at:]                              # 在闭合标签前插入
        return SerializedResult(
            body,                                                                                   # 拼回
            "application/x-votable+xml",  # DALI 规定的 VOTable media type
            ".xml",
            overflow,                                                                                # 截断位外带: 体内已有 INFO, 头再挂一份让非 XML 消费方也能判
        )

    if fmt == "csv":
        # P0-03: CSV 出口必须与 VOTable/FITS 用**同一套**空值语义。三个出口里
        # 只有 CSV 绕开了 convert_table_rows (另两个经 _table 在 :138 调它),
        # 于是同一份数据 FORMAT=csv 把 -1004.07 当**真数字**写盘, 而
        # FORMAT=votable 出 NaN —— 两套相反语义; 而 CSV 恰恰是零依赖出口、
        # 也是生产落盘实际走的那一条 (W5b / X7 各自命中)。
        rows = convert_table_rows(rows)  # 先归一再写: 空值→None、哨兵→NaN, 与 _table 同一函数同一阈值
        output_columns: list[str] = list(columns or ())  # 列序: 显式 columns 优先
        for row in rows:                                                                            # 收集出现过的列
            for column in row:                                                                      # 逐行
                if column not in output_columns:                                                    # 未登记的列记下来
                    output_columns.append(column)  # 新列按首次出现顺序追加, 列序因此稳定
        csv_buffer = StringIO(newline="")  # newline="" 交给 csv 模块管换行, 避免双写
        writer = csv.DictWriter(csv_buffer, fieldnames=output_columns, extrasaction="ignore")  # 丢表外列
        if output_columns:                                                                          # 有输出列才写表头
            writer.writeheader()                                                                    # 写表头
            for row in rows:                                                                        # 逐行写出
                writer.writerow(                                                                    # 写单行
                    {                                                                               # 逐键
                        column: sanitize_cell(row.get(column, ""))  # 逐格消毒, 拦住公式注入
                        for column in output_columns                                                # 只写已登记的列, 保证列序稳定
                    }
                )
        return SerializedResult(  # 截断位外带: CSV 体内插不进合法标记, 全靠响应头 —— 位丢了就是静默交付不完整结果
            csv_buffer.getvalue().encode("utf-8"), "text/csv", ".csv", overflow
        )  # 零依赖出口

    fits_buffer = BytesIO()  # 走到这里即 fits: 前两个分支已各自 return
    table = _table(rows, columns)  # 先取表对象: meta 要在 write 之前挂好, 写完就来不及了
    if overflow:  # 截断位写进 BinTable 头卡: FITS 有原生扩展头, 比往数据区塞东西干净
        table.meta["TAPOVR"] = True  # TAPOVR=T: 读表的人在头卡里就能看到"这份结果被 MAXREC 截断过"
    table.write(fits_buffer, format="fits")
    return SerializedResult(fits_buffer.getvalue(), "application/fits", ".fits", overflow)  # BinTable 二进制体


def votable_error(message: str) -> bytes:
    """生成最小 TAP 错误文档 (QUERY_STATUS=ERROR, 文本经 ElementTree 转义)。

    Args:
        message: 面向用户的错误说明; 由 ElementTree 负责 XML 转义, 调用方
            不得自行拼 XML。

    Returns:
        bytes: 带 XML 声明的 VOTable 错误文档字节。
    """
    root = ET.Element(                                                                              # VOTable 根元素
        "VOTABLE",
        {"version": "1.3", "xmlns": "http://www.ivoa.net/xml/VOTable/v1.3"},
    )  # 1.3 是 DALI 要求的最低 VOTable 版本
    resource = ET.SubElement(root, "RESOURCE", {"type": "results"})
    info = ET.SubElement(                                                                           # RESOURCE 子元素
        resource,                                                                                   # 挂到 resource 下
        "INFO",
        {"name": "QUERY_STATUS", "value": "ERROR"},  # 错误也走 INFO, 与 DALI 约定一致
    )
    info.text = str(message)  # 转义交给 ElementTree, 调用方不得自行拼 XML
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)
