"""src.best_export — BEST 字节级流式下载实现 (HTTP Range 续传 + 取消)。

能力边界: 只承载**字节级流式下载**一个关注点 — 分块迭代、Content-Disposition
文件名、``.part`` 半成品按 Range 续传、进度累加、取消中止、原子替换。本模块
不构造查询、不解析协议、不写查询结果文件 (查询行落盘的权威实现是
``src.downloader.BestDownloader._save_result``, 经 ``src.serialization`` 单点);
下载只消费调用方注入的请求可调用体 (``BestClient._request``), 限流与重试仍归
客户端。边界: URL 主机白名单校验 (P1-10) 先于任何 IO; 错误状态码响应绝不进入
流式写盘 (P0-2)。

白盒锚点: references/ALGORITHM-SPEC.md §2 (download_file 的真源码锚点)。
"""
from __future__ import annotations

# 标准库: contextlib.suppress (尽力而为的清理, SIM105) / 日志 / 文件原子替换与
# 临时文件清理 / 路径与目录 / 文件名路径分隔符消毒 / 类型标注 / requests 异常类型
import contextlib
import logging
import os
import re
from pathlib import Path
from typing import Any, Optional

import requests

# 本地: 入参校验单点 — 下载 URL 主机白名单 (P1-10)
from src.scripts.guards import validate_external_url

logger = logging.getLogger(__name__)                                                         # 模块级 logger: 下载成败两条终态日志只从这里出

# 流式下载分块大小 (字节), 消费方是 download_file 的 iter_content
CHUNK_SIZE = 8192  # 8 KiB: 与 requests 默认块一致, 换成更大只增峰值内存不增吞吐


def download_file(
    url: str,                                                                                # 待下载地址: 主机白名单校验在下一行, 先于任何 IO
    savedir: str = "./",
    overwrite: bool = True,                                                                         # 是否覆盖: 假值且目标已存在时按跳过处理
    filename: Optional[str] = None,                                                               # 显式文件名可空: 缺省取响应头再退到地址末段
    job_id: Optional[str] = None,                                                              # 作业标识可空: 仅日志上下文, 不参与 IO 决策
    progress_tracker: Any = None,                                                                   # 进度累加器可空: 为空则不落盘进度
    cancel_event: Any = None,                                                                    # 取消标志可空: 置位即中止, 半成品保留供续传
    request: Any = None,                                                                       # 请求体可空: 由客户端薄壳注入, 限流与重试都靠它
) -> Optional[str]:
    """Download a file with chunked streaming + Content-Disposition.

    Like pylamost.download(): iter_content(8192), filename from header.
    Skips if file exists and overwrite=False.
    Security: path traversal prevented for both savedir and filename.

    字节级断点续传: 已存在的 ``<name>.part`` 半成品按
    HTTP Range 续传; 服务端不支持 Range (200 而非 206) 时退化为整文件
    重下 (半成品丢弃)。进度经 ``progress_tracker`` (ProgressTracker)
    累加字节并落盘; ``cancel_event`` (threading.Event) 置位即中止。

    Args:
        url: 待下载文件的 URL。
        savedir: 目标目录 (不存在则创建)。
        overwrite: 目标已存在时是否覆盖 (False 则跳过并返回既有路径)。
        filename: 显式文件名; 缺省时取 Content-Disposition 或 URL 末段。
        job_id: 调用方作业标识 (仅日志上下文: 成功/失败两条终态日志带上,
            不参与 IO 决策)。由 ``BestClient`` / ``crossmatch`` / ``downloader``
            注入, 用于在并发下载里定位是哪一个作业出的问题。
        progress_tracker: 可选进度跟踪器 (累加字节并落盘)。
        cancel_event: 可选 ``threading.Event``; 置位即中止下载。
        request: 已带节流/重试的请求可调用体 (即 ``BestClient._request``); 由
            ``BestClient.download_file`` 薄壳注入, 使限流与软错误检查仍由
            客户端单点负责。
    """
    # P1-10: URL 主机白名单校验 (下载栈唯一入口, 先于任何 IO) — 无校验时
    # FileJob.url 可直连内网/云元数据口, 响应体被完整写盘并报"下载成功"
    # (SSRF 原语); 校验失败即拒, 不建目录不发起请求。
    url = validate_external_url(url)                                                              # 白名单校验先于建目录: 校验失败连目录都不建
    out = Path(savedir).resolve()  # 先 resolve 再拼路径: 不 resolve 就无法判目录逃逸
    # IO: 创建目标目录 (批量下载时目录可能尚未存在)
    out.mkdir(parents=True, exist_ok=True)  # exist_ok: 并发下载同一目录不该互相报错
    if filename:                                                                                # 有显式名才消毒: 缺省名走响应头与地址末段那条路
        # IO 前置消毒: 文件名里的路径分隔符一律换成下划线, 防目录逃逸
        filename = re.sub(r'[\\/]', "_", filename)  # 正则同时吃反斜杠: Windows 的分隔符也必须换掉
    try:
        # IO 前置消毒 + 白名单已过的 URL; allow_redirects=False (P1-10:
        # 不跟随跳转 — 跳转目标绕过主机白名单, 重定向即失败)
        resp = request("GET", url, stream=True, allow_redirects=False)  # 唯一的网络出口: 限流与重试都由注入的 request 负责
    except requests.RequestException as e:
        logger.error("Download failed: %s", e)
        return None  # 返回 None 而非抛: 批处理里单文件失败不该掀掉整批
    # P0-2: 状态码前置校验 —— 注入的 request 是任意可调用体, 404 等错误页的
    # HTML 正文一旦进入下面的流式写盘, 就会经 os.replace 变成"下载成功"的
    # 正式产物 (线上 401 token 过期会被读成一次成功下载)。
    if resp.status_code != 200:  # 严格判 200 而非 2xx: 206 走的是下面的续传分支
        logger.error("Download aborted: HTTP %s for %s", resp.status_code, url)
        resp.close()                                                                                # 先关响应再返回: 句柄不留给回收时机
        return None
    cd = resp.headers.get("Content-Disposition", "")
    m = re.search(r'filename=["\']?([^"\'\n]+)', cd)
    filename = filename or (m.group(1).strip() if m                                             # 三级回退取名: 显式名 > 响应头 > 地址末段
                            else url.split("/")[-1].split("?")[0])  # 三级回退: 显式名 > 响应头 > URL 末段
    filename = re.sub(r'[\\/]', "_", filename)
    if not filename:                                                                                # 空名兜底: 空文件名会让后缀操作抛值错误
        filename = "download.dat"  # 兜底名: 空文件名会让 with_suffix 抛 ValueError
    filepath = (out / filename).resolve()                                                       # 落盘路径解析成绝对形态: 目录逃逸判定以此为基准
    if out not in [filepath] + list(filepath.parents) and filepath.parent != out:                   # 归属判定: 逃逸即拒, 一个字节都不落
        logger.error("Path traversal blocked: %s", filepath)
        return None  # 逃逸即拒: 不落任何字节
    if filepath.exists() and not overwrite:                                                         # 已存在且不许覆盖: 跳过也是一次成功结果
        logger.info("File exists (skip): %s", filepath)
        return str(filepath)  # 返回既有路径而非 None: 跳过也是一次成功结果

    total_bytes = int(resp.headers.get("Content-Length") or 0)  # 缺头即 0: 后面的回核对"无声明"一律跳过
    if progress_tracker is not None and total_bytes:                                               # 有声明才设总量: 零会被进度器当成总量为零
        progress_tracker.set_total_bytes(total_bytes)  # 只在有声明时设: 0 会被 tracker 当成"总量为零"

    # 断点续传: .part 半成品 + Range
    part = filepath.with_suffix(filepath.suffix + ".part")  # .part 与正式名同目录: 跨盘 rename 会失败
    resume_from = part.stat().st_size if part.exists() else 0  # 以实际落盘大小为准, 不信任何自报进度
    if resume_from > 0:                                                                            # 有半成品才走续传: 没有半成品就是全新下载
        logger.info("Resuming %s from byte %d", filepath, resume_from)
        try:
            resp.close()  # 先关首包: Range 请求要另开一条连接, 不关会占着池位
            # P1-10: 续传请求同样禁重定向 (跳转目标会绕过主机白名单)
            resp = request(                                                                   # 续传另发一条请求: 换行首包, 不关会占着连接池位位
                "GET", url, stream=True,
                headers={"Range": f"bytes={resume_from}-"},
                allow_redirects=False)                                                            # 续传同样禁重定向: 跳转目标会绕过主机白名单
        except requests.RequestException as e:
            logger.error("Range resume request failed: %s", e)
            return None
        # P0-2: 续传请求同样前置校验状态码 —— 错误页正文不得进入追写路径
        if resp.status_code not in (200, 206):  # 200/206 都接受: 服务端可能忽略 Range 而回整文件
            logger.error("Range resume aborted: HTTP %s for %s",
                         resp.status_code, url)                                                   # 日志带状态码与地址: 排障要看出是哪一次请求
            resp.close()                                                                         # 状态异常即关响应: 错误页正文不得进入追写路径
            return None
        if resp.status_code == 206:                                                           # 只有二百零六才是真续传: 二百是服务端忽略了区间请求
            total_bytes = int(                                                                  # 长度按剩余段算: 这里的头是剩余部分, 不是全量
                resp.headers.get("Content-Length") or 0) + resume_from  # 206 的长度是剩余段, 须加回已下载量
            if progress_tracker is not None:                                                    # 有进度器才刷新总量: 续传后总量变了, 必须重设
                progress_tracker.set_total_bytes(total_bytes)
        else:
            # 服务端不支持 Range: 丢弃半成品整文件重下 (诚实降级)
            logger.info("Server ignored Range (%s); restarting full "
                        "download for %s", resp.status_code, filepath)
            resume_from = 0                                                                     # 退化即从头写: 服务端不支持区间时不能追写半成品
            # SIM105: 半成品丢弃失败不阻断整文件重下
            with contextlib.suppress(OSError):                                                 # 删半成品失败不阻断: 整文件重下才是这一分支的目的
                part.unlink()
    try:
        mode = "ab" if resume_from > 0 else "wb"  # 追加 vs 截断: 续传绝不能用 wb, 否则已下内容被清空
        # IO: 流式分块写出 — 全程只写 .part 一个半成品名。
        # 此前全新下载写 .tmp, 于是「中途取消/断流」留下的半成品不是续传凭据:
        # 下次找不到 .part 只能判 resume_from=0, 以 "wb" 截断重下, 已下字节全废。
        # 统一落 .part 后, 无论全新还是续传, 半成品都是下一次 Range 续传的基线。
        with open(part, mode) as f:                                                                 # 续传追加, 全新截断: 续传用截断模式会把已下内容清空
            for chunk in resp.iter_content(chunk_size=CHUNK_SIZE):                                  # 按块流式读: 块大小固定, 峰值内存有界
                if not chunk:  # 跳过 keep-alive 空块: 空字节写进文件只会虚增大小
                    continue
                if cancel_event is not None and cancel_event.is_set():                       # 取消标志置位即中止: 每块都查, 响应越晚中止粒度越粗
                    logger.info("Download cancelled at %d bytes: %s",
                                f.tell(), filepath)                                            # 日志带已写字节: 复核要看出取消发生在大约什么位置
                    # P2-10: 取消路径也关闭响应: 只有续传分支关的话, 取消
                    # 作业的句柄会一路累积
                    resp.close()                                                             # 取消路径也关响应: 漏关的句柄会一路累积
                    return None  # 保留 .part 下次续传, 不清理 — 这正是统一的理由: 此刻写的正是 .part
                f.write(chunk)                                                               # 写块: 空块已在上面跳过, 写进去的每个字节都算进大小
                if progress_tracker is not None:                                                  # 有进度器才累加: 累加的是字节差, 不是块数
                    progress_tracker.advance_pages(0, bytes_delta=len(chunk))
        # P2-10: 流读尽即关响应 — 不 close() 的话, 连接随响应对象悬挂直到
        # GC (批量下载时句柄累积)
        resp.close()                                                                             # 流读尽即关响应: 否则连接随响应对象悬挂到回收
        target = part                                                                            # 成品取半成品名: 全程只有这一个落点, 无需二选一
        # P2-10: 大小回核 — 服务端声明了 Content-Length 时, 实落字节必须与
        # 声明一致; 不一致即截断/损坏, 按失败处理并保留半成品供续传, 不再
        # 静默 os.replace 成"下载成功"的产物 (与 BestDownloader 的 Q-54
        # 强制校验口径对齐 — 那条路校验和, 这条路回核大小)
        written = target.stat().st_size  # 量实际落盘大小, 不采信 tracker 的累计值
        if total_bytes and written != total_bytes:  # 仅在服务端声明过长度时回核: 无声明无从判截断
            logger.error(                                                                         # 大小不符即报: 服务端声明过长度就必须对得上
                "Size mismatch for %s: server declared %d bytes, wrote %d — "
                "treating as truncated download", filepath, total_bytes, written,
            )
            return None  # 保留 target 不删: 半成品正是下次 Range 续传的凭据
        # IO: 原子替换 — 下载完成后 .part 才变成正式文件
        os.replace(target, filepath)  # 同目录内 rename: 跨文件系统会退化成复制, 失去原子性
        logger.info("Downloaded: %s (%d bytes) [job_id=%s]", filepath,
                    filepath.stat().st_size, job_id)                                         # 日志带实际大小与作业标识: 并发下载要靠它定位是哪一个
        return str(filepath)
    except Exception as e:
        logger.error("Save failed (job_id=%s): %s", job_id, e)
        # 半成品 (.part) 一律保留: 全新下载写的就是 .part, 它同样是已付费的字节,
        # 下次 Range 续传要用。旧的"全新失败清 .tmp"分支已随统一落 .part 移除 ——
        # 把续传凭据删掉等于每次断网都从 0 字节重来。
        return None  # 统一以 None 表示失败: 调用方只需判 falsy, 不必区分失败原因
