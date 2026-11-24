"""src.download_artifacts — 下载产物的落盘辅助 (路径解析/行构建/组合并/复核 sidecar)。

能力边界: 只处理"已经取到的结果怎么变成磁盘上的文件"—— 输出路径解析与
防逃逸、行记录构建、导航组成员文件合并、provenance sidecar、原始数据列表导出。
**不发网络请求、不做查询**; 查询与分页在 ``src/downloader.py``。
消费方: ``src/downloader.BestDownloader`` (全部下载路径的最终出口; 查询行
落盘的权威路径) 与 ``src.download_region``/``src.download_sqlid`` (区域/会话
下载的落盘出口)。

为什么单独成文: 这些是与"取数"正交的关注点, 混在 downloader 里会让
"一次下载经历什么"被落盘细节冲散; 且 ``400 行净代码预算`` 约束的是必须读的
逻辑量, 取数主链比落盘细节更该占额度。
"""
from __future__ import annotations

# 标准库: csv 读写 (成员临时文件按 DictReader 读回) / SHA-256 与恒定时间比对 (校验和) /
# 内存缓冲 (先拼内容再原子落盘) / JSON 读成员文件与写 sidecar / XML 解析 (VOTable 成员
# 读回) / 日志 / 路径与目录 / 类型标注与回调签名
import csv  # 标准库: 成员临时文件的 CSV 读写 (组合并时按 DictReader 读回)
import hashlib  # 标准库: SHA-256 摘要 (分块流式算, 防大文件 OOM)
import hmac  # 标准库: 恒定时间摘要比对, 防时序侧信道
import io  # 标准库: 内存缓冲, 先拼全文再一次性原子落盘
import json  # 标准库: 读 JSON 成员文件 / 写 provenance sidecar
import logging  # 标准库: 校验与 sidecar 失败的 warning 出口
import xml.etree.ElementTree as ET  # 标准库: VOTable 成员文件读回 (不引 astropy 这类新依赖)
from pathlib import Path  # 标准库: 输出路径解析与防逃逸校验
from typing import Callable, Optional, Sequence  # 标准库: 注入回调与可缺参数标注

# 本地: CSV 公式注入消毒 (Q-06, 合并产物导出用) / 查询结果数据模型 /
# 原子写 (tmp + os.replace, Rule 12 防线二) /
# 格式白名单归一 (fail-closed 出口) 与 VOTable 命名空间常量 (读写共用同一份)
from src.csv_safety import sanitize_row  # 本地唯一消毒实现: 导出层不复制 (Q-06)
from src.models import BestQueryResult  # 数据模型: sidecar 的计数/截断/查询参数来源
from src.protocol import CATALOG_GROUPS  # 导航组成员表: 合并台账要把 part 认回"哪个星表", 不靠猜文件名
from src.scripts.guards import atomic_write_text  # 原子写 (tmp + os.replace), 落盘唯一入口
from src.serialization import VOTABLE_XMLNS, normalize_output_format  # 白名单归一 + VOTable 命名空间: 与写出端同源

logger = logging.getLogger(__name__)  # 模块级 logger: 只 warn 不 raise, 不改调用方的日志配置

# 格式 -> 可接受的文件扩展名 (与 ``BestDownloader._save_result`` 的 ext_aliases
# 同一张表, 且两边都只从 :func:`normalize_output_format` 的白名单放行): 名实
# 不符即拒 —— TSV 内容落进 .csv / JSON 内容落进 .txt 这类错误只有下游才会发现。
# 别名 (.txt / .votable) 是 live 实证的既有调用姿势, 容忍; 跨格式的名字不放行。
EXT_ALIASES: dict[str, frozenset[str]] = {
    "csv": frozenset({"csv"}),
    "txt": frozenset({"tsv", "txt"}),  # txt 的规范容器是 .tsv (内容为制表符分隔)
    "json": frozenset({"json"}),
    "votable": frozenset({"xml", "votable"}),
    "fits": frozenset({"fits"}),
}

# 自动命名用的规范扩展名 (与 ``download_by_constraints`` 的 ext_map 同一口径):
# 拿 output_format 直接当后缀会让 .txt/.votable 与规范名分家两处约定。
CANONICAL_EXT: dict[str, str] = {
    "csv": "csv", "txt": "tsv", "json": "json", "votable": "xml", "fits": "fits",
}


# 落盘结果的行状态 (写进 sidecar 的 data 块 row_status 键): 复核者据此区分
# "有数据" 与 "真空区", 而不是靠文件大小猜。
STATUS_OK = "ok"  # 有行: 产物可直接消费
STATUS_EMPTY = "empty"  # 0 行且 total_count=0: 有产物但无数据, 与损坏文件必须可区分
# 落盘产物的**列结构形态** (sidecar data 块的 schema 键): 同一张星表在"这片天区
# 有源"与"没源"两种情形下落出的**表头宽度不同** (有行走行投影的完整列集, 0 行
# 没有任何行可并集, 只能退到固定列), 复核人靠表头判 schema 就会建错表结构。
# 因此形态显式登记在 sidecar 里, 而不靠"读文件碰巧发现"。
# 与 :data:`STATUS_EMPTY` 同源不另立判据: 0 行 ⟺ minimal (两条落盘路径都如此) ——
# 0 行时表头是 :data:`serialization.BASE_COLUMNS` (组合并走 export_results 时是
# ``EMPTY_EXPORT_COLUMNS``, 同样只是兜底列)。
SCHEMA_FULL = "full"  # 有行: 表头 = 行投影完整列集
SCHEMA_MINIMAL = "minimal"  # 0 行: 表头 = 兜底固定列, 行数必为 0
# 0 行合并产物的兜底表头: 没有任何行就没有列可并, 只剩投影的必存列可用。
EMPTY_EXPORT_COLUMNS: tuple[str, ...] = ("source_id",)


def verify_nonempty(result: BestQueryResult, path: str | Path) -> str:
    """落盘行数回核 (四条落盘路径共用的空结果闸)。

    Args:
        result: 即将落盘 (或已落盘) 的查询结果。
        path: 产物路径 (只进错误文案与日志, 本函数不写盘)。

    Returns:
        :data:`STATUS_OK` (有行) 或 :data:`STATUS_EMPTY` (真空区); 调用方
        要把返回值原样记进 sidecar, 让调用方能区分"没源"与"产物坏了"。

    Raises:
        RuntimeError: 0 行但 ``total_count > 0`` —— 服务端说有行却一行没落地,
            判不出成因就不算成功 (铁律 5: 不许静默交付空壳)。

    Note:
        四条落盘路径 (region / sqlid / 约束 / 精准) 的最终出口都是
        ``BestDownloader._save_result``, 闸装在那里一次覆盖四条 ——
        此前只有精准下载自己有回核, 另外三条对 ``success=True`` + 0 行
        毫无防护, 落出只含 BOM 的 3 字节文件而终态是 done。
    """
    rows = len(result.sources or [])  # 实得行数: 唯一能证明"拿到数据"的判据
    if rows:
        return STATUS_OK  # 有行即正常: 截断另有 truncated 标志, 不在此判
    total = int(result.total_count or 0)  # 服务端自报总数: 缺省零, 不拿它编数
    if total > 0:
        raise RuntimeError(  # 抛而不落盘: 有数据却交付 0 行, 产物本身就是错的证据
            f"0 rows written to {path} but server reported total_count={total}: "
            f"refusing to deliver an empty artifact as a success"
        )
    logger.warning("Empty result for %s (total_count=0): recorded as status=%s", path, STATUS_EMPTY)  # 真空区留痕: 调用方要能分辨它与成功有数据
    return STATUS_EMPTY  # 真空区不是失败, 但必须显式记状态, 不能只留一个空文件


def compute_sha256(filepath: str | Path, chunk_size: int = 65536) -> str:
    """分块流式计算文件 SHA-256 哈希值 (Rule 12 防线二/四: 防内存 OOM 与完整性校验)。

    Args:
        filepath: 目标文件路径。
        chunk_size: 分块大小 (字节); 默认 64KB。

    Returns:
        小写十六进制摘要。

    Raises:
        FileNotFoundError: 目标不是文件。

    Note:
        分块流式读 (外部 IO, 64KB/块): 区域导出可达上百 MB, 一次性读入会 OOM
        (Rule 12 防线二)。
    """
    p = Path(filepath)  # 收 str|Path 两种入参: 调用方有直接传字符串的
    if not p.is_file():                                                    # 目录不是文件: 这层先判存在, 省得后面 open 抛 IsADirectoryError
        raise FileNotFoundError(f"Target file not found: {p}")  # 抛而非返 None: 算不出哈希时下游无从判断
    hasher = hashlib.sha256()  # 增量接口: 分块 update 才不会把整文件读进内存
    with open(p, "rb") as f:  # 二进制读: 文本模式会改写换行, 哈希必然对不上
        while chunk := f.read(chunk_size):  # 64KB/块: 区域导出上百 MB, 一次读完会 OOM
            hasher.update(chunk)  # 按块序累加, 顺序错一次摘要就全废
    return hasher.hexdigest()


def text_sha256(content: str, encoding: str) -> str:
    """文本内容按**落盘编码**算出的 SHA-256 (写前算的"意图摘要")。

    存在的理由 (A3-05): 落盘后只读回算一次哈希, 得到的 ``sha256`` 与
    同一个函数再算一次必然相同 —— 那证明不了任何事。要让 ``checksum_match``
    门禁真的可判定, 就得有两个**独立来源**的摘要: 写前按编码算一遍 (意图),
    写后从盘上读回算一遍 (事实), 两者一致才算通过。

    Args:
        content: 即将逐字落盘的文本。
        encoding: 与落盘一致的编码名 (``utf-8`` / ``utf-8-sig``)。

    Returns:
        小写十六进制摘要。

    Note:
        与 :func:`compute_sha256` 的落盘口径对齐的前提是写出侧用
        ``newline=""`` (``src.scripts.guards.atomic_write_text`` 已如此),
        内容不被平台再翻译一次。
    """
    return hashlib.sha256(content.encode(encoding)).hexdigest()


def digests_match(left: str, right: str) -> bool:
    """两个十六进制摘要是否一致 (恒定时间比较, 全仓唯一比较实现)。

    Args:
        left: 左值摘要。
        right: 右值摘要 (大小写与首尾空白都不敏感)。

    Returns:
        一致返回 True。

    Note:
        用 ``hmac.compare_digest`` 而不是 ``==``: 后者在首个不同字节处即
        返回, 攻击者可据响应时间逐字节猜出正确哈希。
    """
    return hmac.compare_digest(left.strip().lower(), right.strip().lower())


def verify_checksum(filepath: str | Path, expected_sha256: str) -> bool:
    """恒定时间哈希比对 (Rule 12 防线四: 防时序侧信道攻击)。

    Args:
        filepath: 待校验文件路径。
        expected_sha256: 期望的十六进制摘要 (大小写不敏感)。

    Returns:
        一致返回 True; 文件不存在或读取失败返回 False (只记 warning)。

    Note:
        比较走 :func:`digests_match` (全仓唯一比较实现, 恒定时间): ``==``
        在首个不同字节处即返回, 攻击者可据响应时间逐字节猜出正确哈希。
        读取失败不抛错 — 校验是下载后的附加步骤, 不该让"算不出哈希"变成
        比"哈希不符"更难诊断的崩溃。
    """
    try:
        actual = compute_sha256(filepath)  # 先算实际值, 再做恒定时间比对
        return digests_match(actual, expected_sha256)  # 不用 ==: 后者会泄露首个不同字节的位置
    except Exception as exc:  # noqa: BLE001 - 校验失败记 warning 后返回 False
        logger.warning("Checksum verification failed for %s: %s", filepath, exc)  # 读取失败只 warn: 校验不该比"哈希不符"更难诊断
        return False  # 统一收敛成"校验不通过": 调用方只需判 False, 不必区分崩与不符


def resolve_output_path(output_dir: Path, filename: str) -> Path:
    """把文件名解析到输出目录内, 并拒绝越界 (防路径逃逸)。

    Args:
        output_dir: 输出根目录 (已由调用方 resolve)。
        filename: 调用方给的文件名 (可能含 ``..`` 或绝对路径)。

    Returns:
        解析后的绝对路径。

    Raises:
        ValueError: 解析结果越出 ``output_dir``。

    Note:
        ``resolve()`` 之后再校验, 因为 ``..`` 只有在解析后才能识别;
        只看字符串前缀会被 ``output_dir_evil/`` 这类同前缀目录绕过。
    """
    path = (output_dir / filename).resolve()  # 先 resolve 再校验: .. 只有解析后才认得出
    root = output_dir.resolve()  # 两侧都取绝对形态, 否则相对路径比较毫无意义
    if root not in path.parents and path.parent != root:  # 比 parents 而非字符串前缀: output_dir_evil/ 能骗过前缀
        raise ValueError(f"Path traversal denied: {path}")  # 抛而非夹回目录: 逃逸请求必须让调用方看见
    return path


def rows_from_result(result: BestQueryResult) -> list[dict]:
    """从查询结果取行记录 (供落盘层消费)。

    Args:
        result: 查询结果。

    Returns:
        行 dict 列表; 空结果返回 ``[]``。

    Note:
        统一走这一层而不是让每个发射端各自 ``result.sources`` — 将来若要在
        行级加脱敏/截断, 只需改一处。
    """
    return [dict(row) for row in (result.sources or [])]  # 统一取行: 将来加脱敏/截断只改这一处


def resolve_export_format(filename: str, output_format: Optional[str]) -> str:
    """把 (文件名, 声明格式) 收敛成一个已校验的格式名 (白名单 fail-closed)。

    Args:
        filename: 目标文件名 (扩展名即"名实相符"的判据)。
        output_format: 调用方声明的输出格式; ``None`` 时按扩展名反查 (老调用点
            ``BestDownloader.export_results`` 不传格式, 文件名是它唯一的事实源)。

    Returns:
        归一后的格式名 (必落在 :data:`serialization.LOCAL_EXPORT_FORMATS` 内)。

    Raises:
        ValueError: 格式不在白名单 (由 :func:`normalize_output_format` 抛), 或
            扩展名与声明格式不相配, 或扩展名无法反查到任何格式。

    Note:
        这条门是 ``contracts/io-contract.md`` 的 ``fmt_in_whitelist`` 在落盘
        侧的落点: **未知格式显式报错, 绝不静默回落 JSON** —— 合并产物曾按
        ``.csv`` 后缀分派, 于是 ``.txt``/``.votable`` 名下装的是 JSON 内容,
        下游按名判格式必然读错 (已实测: TSV 读回塌成一列)。
    """
    ext = Path(filename).suffix.lstrip(".").lower()  # 去点取小写: .CSV 与 .csv 应当等价
    if output_format is None:  # 未声明格式: 扩展名是唯一事实源, 反查后仍要过白名单
        for fmt, exts in EXT_ALIASES.items():
            if ext in exts:
                return normalize_output_format(fmt)  # 反查结果照走归一: 白名单是唯一放行口
        raise ValueError(  # 反查不到即报错: 猜一个格式写下去, 等于换个名字继续骗下游
            f"文件名 {filename!r} 的扩展名 .{ext or '(无)'} 无法反查输出格式; 请显式传 output_format"
        )
    fmt = normalize_output_format(output_format)  # 白名单 fail-closed: 不在白名单即抛
    if ext not in EXT_ALIASES.get(fmt, frozenset()):  # 名实不符即拒: 错配只有下游才会发现
        raise ValueError(
            f"output_file {filename!r} 的扩展名 .{ext or '(无)'} 与"
            f"格式 {output_format!r} 不相配 (可接受: {sorted(EXT_ALIASES.get(fmt, frozenset()))})"
        )
    return fmt


def read_rows_file(path: Path, fmt: str) -> list[dict]:
    """把成员临时文件按其产出格式读回行记录 (组合并的读回单点)。

    Args:
        path: 成员临时文件路径。
        fmt: 成员文件的产出格式 (:func:`normalize_output_format` 的归一名)。

    Returns:
        行 dict 列表。

    Raises:
        ValueError: 该格式无法按行读回 (FITS 是二进制, 读回需 astropy)。

    Note:
        VOTable 分支只解析本仓 :func:`serialization.votable_document` 写出的
        子集 (``FIELD`` 文档序即列序, ``TR``/``TD`` 即行), 命名空间常量取自
        序列化层 —— 读写两端共用同一个常量, 换 VOTable 版本不会两边分家。
        此前该分支按 JSON 解析, 组合并 votable 直接抛 ``JSONDecodeError``。
    """
    if fmt in ("csv", "txt"):
        delimiter = "\t" if fmt == "txt" else ","  # txt 即 TSV: 读错分隔符会把整行塞进一个键
        with open(path, "r", encoding="utf-8-sig", newline="") as handle:  # utf-8-sig 吃掉 BOM; newline="" 是 csv 的硬要求
            return [dict(row) for row in csv.DictReader(handle, delimiter=delimiter)]
    if fmt == "json":
        return json.loads(path.read_text(encoding="utf-8")) or []  # 纯 utf-8 无 BOM; or [] 兜住 null
    if fmt == "votable":
        # 输入是本仓 votable_document 刚落盘的本地文件 (非外部 XML): 外部实体
        # / DTD 展开面不成立, 故按标准库实现解析, 不引 defusedxml 新依赖
        root = ET.fromstring(path.read_text(encoding="utf-8"))  # noqa: S314 (见上: 自产本地文件, 非不可信输入)
        fields = [f.get("name", "") for f in root.iter(f"{{{VOTABLE_XMLNS}}}FIELD")]  # FIELD 文档序即列序
        rows: list[dict] = []
        for tr in root.iter(f"{{{VOTABLE_XMLNS}}}TR"):  # 逐行取单元格
            cells = [(td.text or "") for td in tr.iter(f"{{{VOTABLE_XMLNS}}}TD")]  # text 为 None 即空单元格
            rows.append(dict(zip(fields, cells)))  # 按列序配对: 错位比缺列更难查
        return rows
    raise ValueError(  # fail-closed: 读不回就明说, 不猜也不静默跳过成员
        f"{fmt} 产物无法按行读回 (FITS 是二进制, 读回需 astropy); 导航组逐成员下载+合并这条路不支持该格式"
    )


def _member_counts(sidecar: Path, n_rows: int) -> tuple[int, bool, bool]:
    """读成员 sidecar 取 (服务端自报总行数, 是否被截断, 计数是否可信)。

    Args:
        sidecar: 成员 sidecar 路径。
        n_rows: 从该成员文件实际读回的行数 (sidecar 不可用时的诚实兜底)。

    Returns:
        ``(total_count, truncated, counts_known)``。``counts_known=False`` 时
        ``total_count`` 只是**可证下界** (= 实读行数), 而 ``truncated`` 一律
        置 ``True``: 宁可声称可能不完整, 不可声称完整 (铁律 5)。

    Note:
        成员 sidecar 由 ``_save_result`` 落盘时写, 记着服务端自报总数与
        ``max_rows`` 截断标记; 合并产物必须继承它们, 否则被截断的成员会被
        并成一份"看起来完整"的文件。按行数计是可证的 (文件里就这么多行),
        截断与否就无从回答。

        **计数不可知时不得沉默** (P0 修复): 此前这条路径只 warn 并
        ``return n_rows, False``, 于是 sidecar 一丢, 成员真值
        ``total_count=99999, truncated=True`` 被读成 ``(2, False)`` ——
        台账照记 ``status=ok``, 合并产物 ``truncated=false``, 一个缺了 99997
        行的文件自称完整 (实跑复现见 ``temp/r4_p0_repro.py``)。这与本函数
        上一版的 docstring 承诺 ("不能悄悄当成未截断") 直接矛盾, 故现在
        把它显式记成**不可知**并向保守方向倒 (``truncated=True``)。
    """
    try:
        payload = json.loads(sidecar.read_text(encoding="utf-8"))  # 载荷是 envelope, 计数字段在 data 键下
        data = payload.get("data") if isinstance(payload, dict) else None  # 形态守卫: 合法 JSON 也可能不是对象 (如裸数组)
        if isinstance(data, dict):  # 形态对才敢取字段: 否则下一行 .get 会抛 AttributeError, 不在本 except 的覆盖内
            return int(data.get("total_count", n_rows)), bool(data.get("truncated", False)), True
        reason = f"载荷形态非 data 对象: {type(payload).__name__}"  # 记形态而非记 None: 复核的人才知道该去查什么
    except (OSError, ValueError, KeyError, TypeError) as exc:  # 逐类列举: 读不到/解不开/字段不可强转, 不吞真正的缺陷
        reason = f"{type(exc).__name__}: {exc}"
    logger.warning("成员 sidecar 不可用, 计数判为不可知 (按保守方向记为已截断): %s (%s)", sidecar, reason)
    return n_rows, True, False  # 第三位 False 是"不可信"信号: 调用方据此登记台账, 不得当成未截断


def merge_region_files(
    parts: Sequence[str],
    catalog: str,
    ra_center: float,
    dec_center: float,
    radius_arcsec: float,
    bands: Optional[list[str]],
    output_format: str,
    output_file: Optional[str],
    output_dir: Path,
) -> str:
    """把导航组各成员星表的临时落盘文件合并为一份导出 (并补 sidecar 溯源)。

    Args:
        parts: 各成员星表的临时文件路径。
        catalog: 导航组 id (用于合并产物命名)。
        ra_center: 区域中心赤经 (度)。
        dec_center: 区域中心赤纬 (度)。
        radius_arcsec: 检索半径 (角秒)。
        bands: 波段清单 (参与命名)。
        output_format: 输出格式 (决定成员文件怎么读回 + 合并产物怎么写)。
        output_file: 显式输出名; None 时按区域参数自动生成。
        output_dir: 输出根目录 (合并产物在此落盘并过防路径穿越那一关)。

    Returns:
        合并产物的路径。

    Raises:
        ValueError: 输出格式不在白名单, 或显式文件名与格式不相配。

    Note:
        - 合并策略是**行级并集**, 不做跨表去重 — 不同星表的 ``source_id``
          空间相互独立, 撞 id 也是不同源;
        - 任何成员文件缺失即跳过而不是报错: 组内某星表查询失败不该炸掉
          整个区域下载 (否则一个坏星表让整批白跑);
        - **被跳过的成员必须在 sidecar 里看得见** (H3-05): 逐成员台账
          (``query_params.members``) 记 ``member`` / ``status`` / ``rows`` /
          ``total_count`` / ``truncated`` / ``counts_known``。0 行成员尤其关键
          —— 它的列整个不在合并表头里 (0 行则无行可并集), 只看表头会以为那些
          列本来就不存在; ``counts_known=False`` 则表示该成员的服务端口径读不
          到 (``total_count`` 退成可证下界、``truncated`` 按保守方向置真), 复核
          人据此知道"这份产物的缺口是未知量"而不是"没有缺口";
        - 成员临时文件 (含其 sidecar) 读毕即删, 不留中间产物;
        - 落盘走 :func:`export_results` 并在成功后补 :func:`write_provenance`:
          合并产物是主路径产物, 必须与单表路径同样可复核 (此前它既不过格式
          白名单, 也完全没有 sha256 / query_params / completeness)。

    Warning:
        合并产物走的是**已投影的扁平行字典** (``sources`` 里装 dict 而非
        ``BestSource``) —— 成员是按文件读回的, 行早已是投影后的形态;
        因此本函数产出的 ``BestQueryResult`` 只能喂给落盘/溯源出口, 不可再
        交给 ``_save_result`` (那侧要对源对象调 ``to_dict``)。
    """
    fmt = normalize_output_format(output_format)  # 归一前置: 白名单外的格式在任何 IO 之前就失败
    rows: list[dict] = []  # 行级并集不跨表去重: 不同星表的 source_id 空间相互独立
    total_count = 0  # 各成员服务端自报总数之和: 与取回数的差额即"被截断了多少"
    truncated = False  # 任一成员被截断, 合并产物整体就不完整
    members = list(CATALOG_GROUPS.get(catalog, []))  # 导航组成员表名: parts 与它同序 (调用方按 members 逐个下载), 据此把台账写成"哪个星表"
    # 只有**长度一致**时才按位置配对: 少传/多传文件时位置已不可信, 那时退回按
    # 文件名登记 (绝不猜), 数量差异由 members_expected / members_seen 显式暴露。
    paired = len(parts) == len(members)  # 位置配对是否可信
    ledger: list[dict] = []  # 逐成员台账 (H3-05): 缺成员/0 行成员在合并产物里不留任何痕迹, 台账是复核人唯一的可见出口
    for index, part in enumerate(parts):                                              # 逐个成员读回: 缺一个跳一个, 不让单表失败炸掉整批区域
        path = Path(part)                                                      # 调用方给的是字符串路径, 先转 Path 才能用同一套 exists/unlink
        name = members[index] if paired else path.name  # 成员表名按同序配对; 数量对不上就退回文件名, 不猜
        if not path.exists():  # 成员缺失即跳过: 一个坏星表不该炸掉整批区域下载
            ledger.append({"member": name, "part": path.name, "status": "missing", "rows": 0, "total_count": 0, "truncated": False})  # 缺失成员必须留痕: 少掉的列/行就是它造成的
            continue
        part_rows = read_rows_file(path, fmt)  # 读回单点: 成员按自己的产出格式解析, 不猜
        rows.extend(part_rows)
        sidecar = path.with_suffix(path.suffix + ".provenance.json")  # 成员 sidecar 与数据文件同名加后缀
        member_total, member_truncated, counts_known = _member_counts(sidecar, len(part_rows))  # 第三位: 服务端口径是否可信
        total_count += member_total  # 不可信时它只是可证下界; 缺口由下面的 truncated 显式承担, 不靠 total_count 少算来暗示
        truncated = truncated or member_truncated  # 计数不可知即按已截断计: 保守方向, 不猜"完整"
        # 0 行成员同样进台账: 它把自己的列整个留在了合并表头之外 (0 行 → 无行可并),
        # 复核人若只看表头, 会以为那些列"本来就不存在"。
        ledger.append({"member": name, "part": path.name, "status": STATUS_OK if part_rows else STATUS_EMPTY,
                       "rows": len(part_rows), "total_count": member_total, "truncated": member_truncated,
                       "counts_known": counts_known})  # counts_known 单列而非改写 status: status 讲"有没有行", 讲不了"服务端本来有几行"
        sidecar.unlink(missing_ok=True)  # sidecar 读毕即删: 它记的数据文件已经不在, 留着只会误导复核人
        path.unlink(missing_ok=True)  # 读毕即删: 不留中间产物; missing_ok 容忍已删/未写

    if not output_file:                                                                # 没给显式文件名才自动生成: 显式优先, 否则用户指定的落点会被覆盖
        bands_str = f"_{''.join(bands)}" if bands else ""  # 波段进文件名: 同天区不同波段要能分辨
        # 自动名用规范扩展名 (txt->tsv / votable->xml, 与同层 ext_map 同一口径):
        # 拿 output_format 直接当后缀会让 .txt/.votable 与规范名分家两处约定
        output_file = (                                                                   # 自动名把区域参数编进文件名: 同一天区不同半径的产物才能分辨
            f"best_{catalog}_ra{ra_center:.1f}_dec{dec_center:.1f}"
            f"_r{radius_arcsec:.0f}arcsec{bands_str}.{CANONICAL_EXT.get(fmt, fmt)}"
        )
    saved, written_sha256 = export_results_with_digest(rows, output_file, output_dir, fmt)  # 统一出口: 白名单/扩展名校验 + 原子写 + 写前意图摘要都在那一侧
    merged = BestQueryResult(  # 合并结果的溯源载体: 计数与截断由各成员汇总而来
        success=True,  # 走到这里说明所有存在的成员都读完了; 缺失成员的影响已体现在计数里
        total_count=total_count,  # 各成员自报总数之和: 与 returned_count 的差额即被截断的部分
        returned_count=len(rows),  # 实际并进来的行数
        truncated=truncated,  # 任一成员被截断即整体不完整: 复核人据此决定能不能当全量用
        sources=rows,  # 已投影的扁平行 (见 Warning)
        query_params={  # 合并产物的查询参数: 复核人靠它回答"这份文件是哪片天区、哪个组合出来的"
            "catalog": catalog,
            "ra": ra_center,
            "dec": dec_center,
            "radius_arcsec": radius_arcsec,
            "bands": list(bands or []),
            "merged": True,  # 标明这是导航组合并而非单表查询
            "format": fmt,  # 归一后的格式名: 复核时先对名实, 再对内容
            "members": ledger,  # 逐成员台账: 谁有几行、谁 0 行、谁压根没落盘 —— 合并表头缺列的原因只能从这里看出来 (H3-05)
            "members_expected": len(members),  # 组应有的成员数: 与 members_seen 不等即"调用方少传了文件", 不靠猜
            "members_seen": len(parts),  # 实际交到合并器的文件数 (含随后被判缺失的)
        },
    )
    # sidecar 哈希必须读回落盘文件重算 (防"写了但没真落"的空气写);
    # checksum_match 取**写前意图摘要**与**写后读回摘要**的比对结果 ——
    # 两个独立来源才判得动, 恒写 "unknown" 会让 blocking 门禁永不满足 (A3-05)。
    row_status = verify_nonempty(merged, saved)  # 空结果共用闸: 0 行合并产物同样不许只留一个空壳
    checksum_match = digests_match(written_sha256, compute_sha256(Path(saved)))  # 意图 vs 事实: 不一致即如实记 False
    write_provenance(Path(saved), merged, fmt, checksum_match, row_status, compute_sha256)
    return saved


def write_provenance(
    path: Path,
    result: BestQueryResult,
    output_format: str,
    checksum_match: bool,
    row_status: str,
    sha256_of: Callable[[Path], str],
) -> Optional[str]:
    """给下载产物写 provenance sidecar (人工复核用, best-effort)。

    Args:
        path: 数据文件路径。
        result: 查询结果 (提供计数/截断/查询参数)。
        output_format: 输出格式名 (写进 sidecar 供复核)。
        checksum_match: 校验和判定结果 (布尔): True = 写前意图摘要与写后
            读回摘要逐字节一致 (``checksum_match`` 阻断门禁比的就是它),
            False = 两者不一致。**不再接受 "unknown"**: 恒假的门禁条件
            等于没有门禁 (A3-05), 无法判定时调用方必须给 False。
        row_status: 行状态 (:func:`verify_nonempty` 的判定: ``ok`` / ``empty``)。
            写进 data 块的 ``row_status`` 键, 与信封自身的 ``status``
            (ready/needs_review, 讲的是复核态) 是两回事, 故不重名。同一判定
            还决定 ``schema`` 键 (``full`` / ``minimal``): 0 行产物的表头只
            含兜底固定列, 与有行产物的完整列集不是同一套 schema (H3-04),
            复核人据此选读法, 不靠撞见列数变化。
        sha256_of: 文件哈希回调 (由 ``BestDownloader.compute_sha256`` 注入,
            避免本模块反向依赖下载器)。

    Returns:
        sidecar 路径; 任何失败返回 ``None`` (只 warn 不 raise)。

    Note:
        复核产物**不得阻断下载本身** — 所以整段包在 try 里, 失败只记 warning。
        sidecar 的哈希必须由调用方**读回刚落盘的文件**重算, 防"写了但没真落"
        的空气写; 这一点由 ``sha256_of`` 回调保证。
    """
    try:
        # 延迟导入: provenance 会连带拉起 src.auth (OAuth/token 存储),
        # 只在真正需要写复核产物时才付这份导入成本, 也避免下载主链
        # 与复核生态形成模块级耦合
        from src.provenance import build_envelope

        envelope = build_envelope(  # 整段包在 try 里: 复核产物不得阻断下载本身
            {                                                                       # sidecar 的字段集是复核契约: 少一个键, 复核人就没法判断完整性
                "file": path.name,
                "format": output_format,
                "total_count": result.total_count,
                "returned_count": result.returned_count,
                "truncated": result.truncated,
                "checksum_match": checksum_match,  # 布尔: 写前意图摘要 vs 写后读回摘要 (blocking 门禁比的就是它)
                "row_status": row_status,  # ok/empty 显式入契约: 0 行不再只表现为 completeness=0
                "schema": SCHEMA_MINIMAL if row_status == STATUS_EMPTY else SCHEMA_FULL,  # 列结构形态: 表头宽度随有无数据而变, 显式登记免得下游按错列集建表 (H3-04)
                "sha256": sha256_of(path),  # 由调用方读回落盘文件重算: 防"写了但没真落"的空气写
                "query_params": result.query_params,
            },
            completeness={                                                        # completeness 单独成段: 有行才算完整, 零行导出的完整性记 0
                "required": True,
                "value": 1.0 if result.sources else 0.0,  # 有行才算完整: 零行导出的完整性为 0
            },
        )
        sidecar = path.with_suffix(path.suffix + ".provenance.json")  # 数据文件名加后缀: 按 glob 就能把两者配回一对
        atomic_write_text(                                                                  # sidecar 也走原子写: 复核产物半截落盘比没有更糟
            sidecar, json.dumps(envelope, indent=2, ensure_ascii=False),  # 纯 utf-8 无 BOM: sidecar 供程序读, 不做 Excel 兼容
            encoding="utf-8",
        )
        return str(sidecar)
    except Exception as exc:  # noqa: BLE001 - 复核产物不得阻断下载
        logger.warning("provenance sidecar for %s failed: %s", path, exc)  # best-effort: 失败只留证据, 不抛给下载主链
        return None  # None 即"无 sidecar"信号, 调用方据此判断要不要提示复核人


def export_results(
    data: list[dict],
    filename: str,
    output_dir: Path,
    output_format: Optional[str] = None,
) -> str:
    """把原始数据列表导出为文件 (CSV/TSV/JSON/VOTable, 合并产物的落盘点)。

    薄壳: 只取 :func:`export_results_with_digest` 返回的路径, 写前意图摘要
    由需要它的那一侧 (合并出口要拿它填 ``checksum_match``) 单独调用。

    Returns:
        落盘文件的绝对路径。
    """
    return export_results_with_digest(data, filename, output_dir, output_format)[0]  # 只取路径: 本出口的契约一直是"给字符串路径"


def export_results_with_digest(
    data: list[dict],
    filename: str,
    output_dir: Path,
    output_format: Optional[str] = None,
) -> tuple[str, str]:
    """导出文本格式并同时给出**写前意图摘要** (校验和门禁的事实源之一)。

    Args:
        data: 行记录列表 (可异构)。
        filename: 目标文件名 (扩展名须与格式相符, 见 :data:`EXT_ALIASES`)。
        output_dir: 输出根目录。
        output_format: 声明的输出格式; ``None`` 时按文件名扩展名反查 (老调用点
            ``BestDownloader.export_results`` 不传格式)。两种入参都要过
            :func:`resolve_export_format` 的白名单与名实相符校验。

    Returns:
        ``(落盘文件绝对路径, 写前意图摘要)``。摘要按落盘编码算出, 与
        :func:`compute_sha256` 读回落盘文件的结果比对即得 ``checksum_match``。

    Raises:
        ValueError: 格式不在白名单 (fail-closed, 绝不静默回落 JSON)、扩展名与
            格式不相配, 或 FITS (二进制, 走 ``_save_result`` 的 tmp+replace
            通道 —— 本出口是文本写)。

    Note:
        表格类表头取全部记录键的并集 (异构行各保留其列), 每个值都过
        CSV 消毒器; 经共享 helper 原子落盘 (tmp + os.replace)。
        列序取**首次出现顺序**而不是排序 — 这是合并产物的导出, 保留上游
        列序更利于人工比对 (与 ``serialization.delimited_text`` 的排序口径
        刻意不同)。**0 行也要写表头**: 空数据无列可并, 退到
        :data:`EMPTY_EXPORT_COLUMNS` —— 否则这里落出只含 BOM 的 3 字节文件,
        与"写坏的空文件"在字节层不可区分。
        格式分派只看 ``output_format``, 不再看后缀: 此前按 ``.csv`` 后缀分流,
        自动名带 ``.txt`` / ``.votable`` 的合并产物便全落进 JSON 分支 ——
        TSV 名下装 JSON, 按 TSV 读回整表塌成一列 (已实测)。
    """
    fmt = resolve_export_format(filename, output_format)  # 白名单 + 名实相符: 分派前先把格式钉死
    if fmt == "fits":  # FITS 在白名单内, 但本出口写的是文本: 显式报错而不是悄悄给个 JSON
        raise ValueError(  # fail-closed: 调用方请求 FITS 却拿到 JSON 文件, 且无任何提示
            "FITS 是二进制格式, 走 BestDownloader._save_result (tmp + os.replace); 本出口只写文本格式"
        )
    path = resolve_output_path(output_dir, filename)  # 路径逃逸在此统一拦: 导出层不重复实现
    if fmt in ("csv", "txt"):
        delimiter = "\t" if fmt == "txt" else ","  # txt 即 TSV: 导出端与成员读回端同一套约定
        columns: list[str] = []  # 首次出现顺序而非排序: 保留上游列序, 利于人工比对
        for record in data:                                                                   # 遍历全部记录而非首行: 异构行的列并集只有扫完才知道
            for key in record:                                                                 # 逐键看: 同一行的键序即该行列序, 列并集靠它累积
                if key not in columns:                                                            # 未见过的列才补: 重复列会让表头出现同名字段
                    columns.append(key)                                                    # 按首次出现序追加: 排序会打乱上游列序, 人工比对就费劲了
        if not columns:                                                                       # 0 行即无列可并: 退到兜底表头, 不再落 3 字节空壳
            columns = list(EMPTY_EXPORT_COLUMNS)  # 唯一可确认的列名: 让空结果在字节层可辨认
        buffer = io.StringIO()  # 先拼全文再落盘: 交给共享 helper 一次性原子写
        writer = csv.DictWriter(buffer, fieldnames=columns, delimiter=delimiter,  # 分隔符由格式决定: txt 走制表符
                                extrasaction="ignore")  # extrasaction: 丢表外列, 否则 ValueError
        writer.writeheader()                                                      # 表头先落: 异构行缺的列由 DictWriter 补空, 不靠行去凑
        for record in data:                                                              # 再走一遍记录写行: 列并集在上一次遍历才定型, 这里才敢写
            writer.writerow(sanitize_row(record))  # 逐行过消毒器: 公式向量原样进表格即注入
        content = buffer.getvalue()                                                          # 先在内存拼全文再交给原子写: 避免边写边算留下半截文件
        encoding = "utf-8-sig"  # CSV/TSV 带 BOM: Excel 双击打开不乱码
    else:
        # 函数内导入: JSON / VOTable 序列化 (只在非表格分支才需要, 与序列化层共用一份实现)
        from src.serialization import json_document, votable_document

        # VOTable 走序列化层的唯一实现: 不在导出层再手写一份 XML (否则两处形状各自漂移)
        content = votable_document(data) if fmt == "votable" else json_document(data)
        encoding = "utf-8"  # JSON/VOTable 纯 utf-8: BOM 会破坏标准解析器

    written_sha256 = text_sha256(content, encoding)  # 写**前**按落盘编码算一遍: 这是"意图"侧的独立摘要
    atomic_write_text(path, content, encoding=encoding)  # 原子落盘 (tmp + replace): 不留半截文件
    logger.info("Exported %d records to %s (format=%s)", len(data), path, fmt)  # 记条数/落点/格式: 排查"导出了什么、什么格式"的第一手线索
    return str(path.resolve()), written_sha256  # 路径 + 意图摘要: 写后读回算出的事实摘要由调用方比

