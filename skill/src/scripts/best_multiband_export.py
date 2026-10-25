"""scripts.best_multiband_export — Multi-band photometry export (static catalog snapshot, not multi-epoch).

能力边界: 多波段测光导出 (export_multiband_photometry/batch_export_multiband_photometry)。边界: 批量导出逐源隔离; output_format 白名单 csv/json 且扩展名与内容一致 (A2); 落盘走 downloader 的消毒与编码约定。
白盒锚点: references/ALGORITHM-SPEC.md §2 (multiband_photometry 锚点)。
"""
from __future__ import annotations

# 标准库: 输出目录路径处理
from pathlib import Path

# 标准库: 可选类型标注
from typing import Optional

# 本地: client 层提供 REST 会话 (BestMultiBandPhotometry.from_client 内部发起查询)
from src.client import BestClient

# 本地: 多波段测光领域对象 (to_csv/to_json 落盘)
from src.multiband_photometry import BestMultiBandPhotometry

# A2: output_format 白名单 — 扩展名必须与内容类型一致。只有 "csv" 与 "json" 合法,
# 其余值一律显式抛 ValueError, 不静默降级。切勿对未列入白名单的值按 json 写却把
# 该值原样当扩展名: output_format="txt" 会落一个 .txt 里装 JSON 的文件, 下游按
# 扩展名分派解析器时静默解析失败 (比显式报错危险得多)。
_OUTPUT_FORMATS = ("csv", "json")  # 元组而非集合: 白名单顺序稳定, 报错消息可复现


def export_multiband_photometry(source_id: str, band: Optional[str] = None, output_format: str = "csv", output_dir: str = ".", allow_empty: bool = False) -> str:
    """导出单个源的多波段静态测光 (BEST 是均一定标星表, 无时序数据)。

    注意: 现网 BEST 接口返回的是定标后测光快照 (一行 = 一个源的一套
    定标测光值), 没有逐历元序列; 需要时序请改用 ZTF/ATLAS/ASAS-SN 等
    测光巡天源。本函数按源 ID 取该源的定标测光记录并落盘。

    A2: ``output_format`` 白名单化 (``csv``/``json``) — 扩展名与内容类型
    严格一致; 其他值显式抛 ``ValueError``, 不再静默按 json 写。

    **0 点不产出文件** (G1-03): 该天区真空 (查询成功、0 命中) 与查询失败
    早先都落成同一个仅表头的几十字节文件, 并被本函数与批量函数计成
    "导出成功" —— 产物与"写坏的空文件"不可区分。缺省拒绝落盘, 确需为
    真空区留档时显式 ``allow_empty=True`` (落盘日志标 ``row_status=empty``,
    与 ``src/download_artifacts.py`` 同一套词表)。

    Args:
        source_id: 源标识 (写入文件名)。
        band: 可选波段过滤。
        output_format: 输出格式, 只接受 ``csv`` 或 ``json`` (白名单)。
        output_dir: 输出目录 (不存在则创建)。
        allow_empty: 是否允许 0 点容器落盘 (缺省拒绝, 见上)。

    Returns:
        落盘文件路径。

    Raises:
        ValueError: ``output_format`` 不在白名单 (``csv``/``json``) 内;
            ``source_id`` 不是可解析的 ``POS_<ra>_<dec>`` 形态。
        RuntimeError: 0 点容器且未显式 ``allow_empty=True`` (不落盘);
            或底层锥形检索失败 (错误码在异常消息里)。
    """
    # A2: 入口即校验格式白名单 (fail-fast: 不建 client/不建目录/不落盘)
    if output_format not in _OUTPUT_FORMATS:  # fail-fast: 非法格式在建客户端与建目录之前就退出
        raise ValueError(
            f"output_format must be one of {_OUTPUT_FORMATS}, got {output_format!r}"  # 报错带白名单全文: 调用方不必翻源码查允许值
        )  # fail-fast: 非法格式在建 client/建目录之前就退出
    # 新建 BestClient 并发起源查询 (BestMultiBandPhotometry.from_client 内部走 REST)
    client = BestClient()  # 单源导出用一次性 client, 不共享会话 (批量路径另走共享实例)
    lc = BestMultiBandPhotometry.from_client(client, source_id, band=band)  # 查询在此发生: 域对象负责把 REST 回包转成行
    # IO 点: 确保输出目录存在 (批量导出前预先建好, 避免逐源 mkdir 竞争)
    p = Path(output_dir)  # 先把目录规整成路径对象: 后续拼接不必反复转字符串
    p.mkdir(parents=True, exist_ok=True)  # 存在即放过: 批量导出时逐源建目录会互相抢
    fn = f"mbp_{source_id}_{band or 'all'}.{output_format}"  # 扩展名取自已校验的白名单值
    fp = str(p / fn)  # 用路径运算符拼: 免得手写分隔符在 Windows 上出错
    if output_format == "csv":  # 按已校验的白名单分派: 不再对未知格式做猜测
        # IO 点: CSV 落盘 (编码/消毒/原子写约定见 src.scripts.guards)
        return lc.to_csv(fp, allow_empty=allow_empty)  # 0 点闸透传: 出口层不自己判, 域对象是唯一判据
    # IO 点: JSON 落盘
    return lc.to_json(fp, allow_empty=allow_empty)  # 走到这里只可能是 json: 前面已 fail-fast 拦掉其余值

def batch_export_multiband_photometry(source_ids: list[str], band: Optional[str] = None, output_dir: str = "multiband_photometry") -> list[str]:
    """批量导出多个源的多波段测光 (逐点隔离, 单点失败不中断批次)。

    0 点源与查询失败源**同走 except 分支**: 报告原因且不进返回值。批量
    路径不暴露 ``allow_empty`` (整批留档应由调用方逐个走单源函数显式
    决定), 因此真空区在批量模式下不会被计成导出成功。

    Args:
        source_ids: 源标识列表。
        band: 可选波段过滤。
        output_dir: 统一输出目录。

    Returns:
        成功落盘的路径列表 (失败的源被跳过, 不计入)。
    """
    paths = []  # 只收成功落盘的路径, 失败源不进返回值
    for sid in source_ids:  # 逐源循环: 失败隔离靠循环体内的 try, 循环本身不吞异常
        try:
            paths.append(export_multiband_photometry(sid, band=band, output_dir=output_dir))  # 逐源独立落盘
        except Exception as e:
            # 逐点隔离: 单源失败只报告并跳过, 不让一个坏源废掉整批导出
            print(f"Error exporting {sid}: {e}")  # 只报告不中断: 一个坏源不该废掉整批导出 (0 点与查询失败都从这里如实报出)
    return paths
