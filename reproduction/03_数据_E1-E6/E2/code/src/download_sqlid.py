"""src.download_sqlid — 按 sqlid 的分页下载与断点续传 (区域/约束之外的第三条取数路径)。

能力边界: 拿到服务端 ``sqlid`` 之后的分页拉取、页级 checkpoint 落盘/恢复/删除,
以及从断点原地续传。**不建 sqlid** (那是 phase-1 的职责, 见
``BestDownloader.download_by_constraints``); 也不做格式写出 (在
``src/serialization``)。

为什么单独成文: sqlid 下载的断点状态机 (next_page 语义 / 历史源前缀回交 /
成功即删断点) 是与"区域下载"正交的一条路径, 混在一个文件里会让 downloader
突破 400 行净代码预算, 也会让"一次下载经历什么"多出第三条分支要读。

分页参数 (page_size/max_rows) 属于断点的一部分而不是调用方的自由: phase-2
是偏移翻页, 步长一变就等于跳过整段行, 故 ``resume_paging_params`` 是
"断点 → 分页参数"的唯一复原点, 缺键即抛 (fail-closed), 绝不回落缺省。
"""
from __future__ import annotations

# 标准库: 日志 (续传恢复与断点删除留痕) / 类型标注与 observer 回调签名
import logging
from typing import Callable, Optional

# 本地: 单源数据模型 (checkpoint 里历史源的反序列化) /
# 协议层星表解析 (导航组 id 在此转 ValueError) / 软 404 错误码
from src.models import BestSource
from src.protocol import SOFT_404_ERROR_CODE, resolve_catalog

logger = logging.getLogger(__name__)                                                            # 模块级 logger: 续传与断点消息只从这里出


class SqlidExpiredError(RuntimeError):
    """服务端 sqlid 会话已过期或失效 (E_SOFT_404)。

    继承自 RuntimeError 以保持向后兼容。
    当抛出该异常时，表示当前断点记录中的 sqlid 在服务端已不复存在，
    偏移翻页无法继续，需要清理失效 checkpoint 并重新提交 Phase 1 查询。
    """


def resume_paging_params(
    ckpt: dict,
    *,
    job_id: str = "",
    default_page_size: int = 1000,
    default_max_rows: int = 50000,
) -> tuple[int, int]:
    """从断点复原分页参数 (page_size/max_rows), 缺键时 fail-closed。

    phase-2 是**偏移翻页**: 实测同一会话下 ``page=2&rows=100`` 返回的 100 行
    与 ``page=1&rows=1000`` 的 ``[100:200]`` 逐行相同。因此 ``next_page``
    只有与当初那把 ``page_size`` 成对才有意义 —— 断点丢了步长, 续传就会按
    缺省步长去数偏移, 中间整段行被跳过: 无重复、无异常、终态 done。

    Args:
        ckpt: 读回来的断点状态 (只读, 本函数不改它)。
        job_id: 作业标识 (只进错误文案: 得让人知道该删哪一份断点)。
        default_page_size: ``next_page <= 1`` 时的步长缺省 (还没翻过页, 偏移
            尚未建立, 缺省无歧义), 以及调用方自报步长时的回落基线。
        default_max_rows: ``max_rows`` 缺项时的回落值 (它只封顶, 不参与偏移)。

    Returns:
        ``(page_size, max_rows)``: 断点说了算, 调用方改了也不采纳。

    Raises:
        RuntimeError: 已翻过页 (``next_page > 1``) 却没有 ``page_size`` ——
            旧格式断点缺这个键, 此时任何缺省都是猜偏移语义, 宁可拒绝续传
            (铁律 5: 目标缺失/未签字 = FAIL, 不许静默按缺省续)。
    """
    next_page = int(ckpt.get("next_page") or 1)  # 缺 next_page 视为没翻过页: 旧断点仍可从头续
    if next_page <= 1:  # 还没拉过任何页: 偏移未建立, 缺省值无歧义
        return int(default_page_size), int(default_max_rows)
    if ckpt.get("page_size") is None:  # 翻过页却没记步长 = 旧断点, 不猜
        raise RuntimeError(
            f"checkpoint '{job_id}' has no page_size but already reached page "
            f"{next_page}: offset paging needs the original stride, guessing it "
            f"would silently skip rows — delete the checkpoint and resubmit"
        )
    max_rows = ckpt.get("max_rows") or default_max_rows  # 上限缺项可回落: 它只封顶, 不影响行区间
    return int(ckpt["page_size"]), int(max_rows)  # 断点值即真值: 续传的偏移语义由它定义


def download_sqlid(
    downloader,                                                                                 # 下载器: 提供断点存储与取数出口, 本函数不自建
    sqlid: str,                                                                                     # 会话号: 阶段一已提交, 此处只翻页
    catalog: str = "ps1",
    output_format: str = "csv",
    output_file: Optional[str] = None,                                                            # 输出文件名可空: 缺省名带会话号, 便于回溯
    max_rows: int = 50000,                                                                          # 取回上限: 与页大小解耦, 便于分批
    page_size: int = 1000,                                                                          # 页大小: 末页自然不足一页
    job_id: Optional[str] = None,                                                                   # 作业标识可空: 缺省按会话号与星表生成
    resumable: bool = False,                                                                        # 断点开关: 开了才每页写断点
    on_page_observer: Optional[Callable[[int, list], None]] = None,                                 # 逐页回调可空: 进度与取消都靠它
) -> str:
        """按已有 sqlid 下载数据到本地文件 (断点续传的核心通道)。

        适用于已持有 sqlid 的会话 (phase-1 已提交过, 服务端会话仍有效)。
        断点语义: resumable=True 时每页成功即更新 checkpoint (next_page +
        已累积 sources), 中途被杀后可用同一 job_id 从断点页继续; 全部完成
        即删 checkpoint。job_id 缺省按 ``sqlid_{sqlid}_{catalog}`` 生成 —
        同一 sqlid 重复提交复用同一断点。

        Args:
            sqlid: 服务端 SQL 查询 ID (如 "s2623")
            catalog: 目标星表
            output_format: csv, txt, json, votable
            output_file: 输出文件名
            max_rows: 最大行数
            page_size: 每页行数
            job_id: 断点 checkpoint 的作业标识
            resumable: True 时每页保存进度并按 checkpoint 续传
            on_page_observer: 每页回调 (page, sources)

        Returns:
            落盘文件路径。

        Raises:
            ValueError: 星表 id 不可查询 (导航组如 ``std`` 没有 ``/q`` 路由)。
            RuntimeError: 分页拉取失败。
        """
        try:
            resolve_catalog(catalog)  # 先探星表: 导航组没有 /q 路由, 早失败好过拉半程才发现
        except ValueError as exc:
            # 看似合法但不可查询的 id (导航组) 必须转 ValueError: 以 KeyError
            # 冒出的话, 调用方无法区分"id 写错"与"代码缺陷"。
            raise ValueError(str(exc)) from exc  # 统一成 ValueError: 调用方不必为"组 id"单开一个 except 分支
        # job_id 缺省按 sqlid+星表生成 (仅可续传时): 同一会话重复提交复用断点
        effective_job_id = job_id or (f"sqlid_{sqlid}_{catalog}" if resumable else None)  # 非续传不生成 id: 无断点语义的路径不该留断点键

        start_page = 1                                                                             # 起始页缺省为 1: 断点里没有页号时从头续
        initial_sources: list[BestSource] = []  # 续传恢复的历史源前缀: 交给分页器, observer 才看得到全量累计视图
        eff_page_size = page_size  # 实际下发的步长: 续传时以断点为准 (见 resume_paging_params)
        eff_max_rows = max_rows  # 实际下发的上限: 同上

        if resumable and effective_job_id:  # 两条件都要真: 给了 job_id 但没开 resumable 仍是一次性下载
            # 断点读取 (外部 IO): 决定从第几页继续、恢复哪些历史源
            ckpt = downloader.checkpoint.load(effective_job_id)                                   # 读断点是外部 IO: 缺失返回空值而不是抛错
            if ckpt:                                                                                # 有断点才恢复: 无断点就是一次性下载
                # next_page 是"下一页"语义: 断点前的所有页已在 checkpoint
                # 的 sources 里, 恢复时既不重拉也不跳过
                start_page = ckpt.get("next_page", 1)  # 缺 next_page 回落 1 页: 旧格式断点仍可续, 不静默跳页
                eff_page_size, eff_max_rows = resume_paging_params(  # 步长与上限从断点取: 偏移翻页下这是行完整性的前提
                    ckpt, job_id=effective_job_id, default_page_size=page_size, default_max_rows=max_rows,
                )
                if (eff_page_size, eff_max_rows) != (page_size, max_rows):  # 调用方改了步长: 断点说了算, 否则中途改步长即丢行
                    logger.warning(  # 显式留痕: 静默忽略调用方的分页参数会让"我明明给了 1000"变成无解之谜
                        "job %s resumes with checkpoint paging page_size=%d max_rows=%d "
                        "(caller asked %d/%d)", effective_job_id, eff_page_size, eff_max_rows, page_size, max_rows,
                    )
                cached_sources = ckpt.get("sources", [])
                # 还原时带上 catalog: 列前缀剥离与逐星表星等映射都依赖它 —
                # 缺失时续传来的源会丢掉 catalog/magnitudes/magnitude_errors,
                # 是一处静默数据缺损。
                initial_sources = [  # catalog 必须回填: 缺它 from_row 复原不出 magnitudes 与列前缀
                    BestSource.from_row(d, catalog=d.get("catalog", catalog))
                    for d in cached_sources                                                       # 逐行复原历史源: 字典回模型才能参与后续投影
                ]
                logger.info(                                                                        # 恢复即记日志: 排障时要看出从哪一页续的
                    "Resuming download for %s from page %d (%d sources already restored)",
                    effective_job_id, start_page, len(initial_sources),                           # 三个值入日志: 作业标识、起始页与已恢复行数
                )

        accumulated_sources = list(initial_sources)  # 拷贝而非直接引用: 闭包后续 extend 不能改到已恢复的那份

        def _on_page_fetched(page_num: int, page_sources: list[BestSource]) -> None:
            """每页回调: 先落页级 checkpoint, 再转发调用方 observer。

            由 client.fetch_page 在每页数据到手后调用 — 也是取消异常
            (JobCancelledError) 注入分页循环的位置 (经 observer 抛出,
            穿透 client_paging.fetch_sqlid_data 的分页 while 循环向上
            冒泡, 不会被当成普通异常吞掉)。
            """
            if resumable and effective_job_id:                                                   # 两条件才写断点: 给了标识但没开开关仍是一次性
                accumulated_sources.extend(page_sources)                                         # 累积源先扩: 断点里要落全量累计, 不只是本页
                # 页级断点 (外部 IO): 每页一写 (原子), 断点粒度 = 页;
                # 已累积源全量入 checkpoint, 恢复时不必重拉历史页
                downloader.checkpoint.save(effective_job_id, {  # 每页一写: 断点粒度=页, 进程被杀最多丢一页
                    "job_id": effective_job_id,
                    "sqlid": sqlid,
                    "catalog": catalog,
                    "next_page": page_num + 1,
                    "sources": [s.to_dict() for s in accumulated_sources],  # 落 dict 不落模型: checkpoint 要跨进程读, 存不了对象图
                    "output_format": output_format,
                    "output_file": output_file,
                    "page_size": eff_page_size,  # 步长入断点: 偏移翻页下 next_page 脱离它就没有意义
                    "max_rows": eff_max_rows,  # 上限同样入断点: 续传不靠缺省猜 phase-2 封顶值 (A2-03)
                })
            if on_page_observer is not None:                                                       # 有回调才转发: 不可续传时回调可以整个不给
                on_page_observer(page_num, page_sources)                                        # 回调在本页数据到手后调用: 也是取消异常的注入点

        # 协议阶段二 (phase 2, HTTP 调用点): 按 sqlid 分页拉数据。
        # on_page_fetched 挂 checkpoint/observer (取消注入点);
        # initial_sources 把续传恢复的历史页前缀交还分页器, 保证
        # observer 与最终结果看到的是全量累计视图而非仅本次新拉部分
        result = downloader.client.fetch_page(  # 唯一的 HTTP 出口: 恢复/续传/observer 三条语义在此汇合
            sqlid,                                                                                  # 会话号传首位: 被委派方按位置参数接住
            page=start_page,                                                                      # 页码取恢复后的起始页: 断点页不重拉也不跳过
            page_size=eff_page_size,                                                              # 步长下传的是**复原后**的值: 偏移翻页要求与断点同口径
            catalog=catalog,                                                                        # 星表下传: 错误信封与列前缀都靠它
            max_rows=eff_max_rows,                                                                # 取回上限同口径下传: 不让缺省与断点各说各话
            on_page_fetched=_on_page_fetched if resumable and effective_job_id else None,  # 条件挂载: 不可续传时不做每页 IO
            initial_sources=initial_sources,                                                  # 历史源前缀交还分页器: 最终结果与回调看的是全量累计
        )
        if not result.success:  # 抛而不落空文件: 半途失败必须让调用方看见, 不能伪装成空结果
            err_msg = result.error or "unknown error"
            if result.error_code == SOFT_404_ERROR_CODE or SOFT_404_ERROR_CODE in err_msg:
                hint = (
                    f"sqlid session '{sqlid}' is expired or dead ({err_msg}). "
                    f"Offset pagination cannot continue. "
                )
                if resumable and effective_job_id:
                    hint += (
                        f"Please delete checkpoint '{effective_job_id}' "
                        f"(downloader.checkpoint.delete('{effective_job_id}')) and re-submit query."
                    )
                else:
                    hint += "Please re-submit query to acquire a fresh sqlid."
                raise SqlidExpiredError(hint)
            raise RuntimeError(f"sqlid {sqlid} fetch failed: {result.error}")

        if not output_file:                                                                        # 没给文件名才自动生成: 显式名一律原样尊重
            # 缺省名带 sqlid: 人可从文件名回溯到服务端查询会话
            output_file = f"best_sqlid_{sqlid}.{output_format}"  # 文件名带 sqlid: 从落盘产物就能回溯到服务端会话

        saved_path = downloader._save_result(result, output_file, output_format)                 # 落盘走统一出口: 消毒、编码与原子写都在那一侧

        if resumable and effective_job_id:  # 只在续传路径删: 非续传压根没创建过断点
            # 成功落盘即删断点 (外部 IO): 残留 checkpoint 会让下次同
            # job_id 提交误判为"可续传"而重复导出, 磁盘随之泄漏
            downloader.checkpoint.delete(effective_job_id)  # 成功才删: 残留会让下次同 job_id 重复导出

        return saved_path


def resume_job(
    downloader,
    job_id: str,
    on_page_observer: Optional[Callable[[int, list], None]] = None,
) -> str:
    """从 checkpoint 原地续传一个未完成的下载作业。

    断点语义: 读 checkpoint 取 (sqlid, next_page, sources, catalog,
    output_format/output_file), 以同一 job_id 重新进入分页 — 查询不
    重发 (phase-1 的 sqlid 仍有效), 历史页不重拉。分页参数 (page_size /
    max_rows) 一律**从断点取**而不是用缺省: phase-2 是偏移翻页, 步长
    变了等于跳过整段行。checkpoint 缺失或其中没有 sqlid 时, 说明该
    作业从未进入可分页状态, 抛 FileNotFoundError (调用方应改走重新提交
    而不是重试 resume); 断点已翻过页却没有 page_size 时抛
    RuntimeError (旧断点, 偏移步长不可猜, 铁律 5)。

    组作业 (``catalog="std"`` 展开, B5): 组级 checkpoint 带 ``group`` 键,
    成员断点落在 ``{job_id}_{member}`` 派生键下 — 这时以同一 job_id 重新
    进入组展开 (成员各自从自己的断点页续拉), 而不是按 sqlid 续传; 组级不落
    checkpoint 的话, 这类作业 resume 一律 FileNotFoundError。

    Args:
        downloader: ``BestDownloader`` 实例 (提供 checkpoint 与
            download_region/download_sqlid)。
        job_id: 启动可续传下载时使用的作业标识。
        on_page_observer: 逐页回调 (page, sources), 两条续传分支都**必须**
            转发。缺它则续传期间进度停止累加、取消标志也不再被检查
            (取消静默失效) — 理由与 ``downloader.download_region`` 的
            续传分支同源, 见该文件里同名的警告注释。

    Returns:
        落盘文件路径。
    """
    ckpt = downloader.checkpoint.load(job_id)  # 读不到就是"从未进入可分页状态", 下面统一转 FileNotFoundError
    if ckpt and ckpt.get("group"):  # 先判组: 组级断点只存展开参数, 按 sqlid 续会取不到键
        # std 组展开作业: 组级断点只存展开参数, 真正的页级断点在成员键下
        # — 以同一 job_id 重入组展开即完成原地续传 (成员键由
        # {job_id}_{member} 派生, 各自的 next_page 决定从哪页继续)
        if ckpt.get("page_size") is None:  # 组级断点必带步长 (download_region 落盘时即写入): 缺了就无法复原成员翻页偏移, 不猜
            raise RuntimeError(
                f"group checkpoint '{job_id}' has no page_size: member offsets cannot be "
                f"restored, guessing would silently skip rows — delete the checkpoint and resubmit"
            )
        return downloader.download_region(
            ra_center=ckpt["ra"], dec_center=ckpt["dec"],
            radius_arcsec=ckpt["radius"], catalog=ckpt["group"],
            bands=ckpt.get("bands"),
            output_format=ckpt.get("output_format", "csv"),
            output_file=ckpt.get("output_file"),
            max_rows=ckpt.get("max_rows", 50000),
            page_size=ckpt["page_size"],  # 必存键: 上方已 fail-closed 校验, 不再回落缺省
            job_id=job_id, resumable=True,                                                      # 同一作业标识重入: 组展开路径靠它复用成员派生键
            on_page_observer=on_page_observer,  # observer 必须转发: 缺它进度不累加且取消静默失效
        )
    if not ckpt or not ckpt.get("sqlid"):  # 两条件缺一不可: 有断点但无 sqlid 同样续不了
        raise FileNotFoundError(f"No resumable checkpoint found for job_id '{job_id}'")
    page_size, max_rows = resume_paging_params(ckpt, job_id=job_id)  # 显式从断点取步长/上限: 用缺省即丢行
    return downloader.download_sqlid(  # 同 job_id 回灌: 查询不重发, phase-1 的 sqlid 仍有效
        sqlid=ckpt["sqlid"],
        catalog=ckpt.get("catalog", "ps1"),
        output_format=ckpt.get("output_format", "csv"),
        output_file=ckpt.get("output_file"),
        max_rows=max_rows,  # 上限来自断点: phase-2 封顶值不靠缺省复原 (A2-03)
        page_size=page_size,  # 步长来自断点: 偏移翻页的行区间由它定义
        job_id=job_id,                                                                          # 会话号从断点取: 查询不重发, 阶段一会话仍有效
        resumable=True,                                                                             # 强制走断点: 这一段的语义就是原地续传
        on_page_observer=on_page_observer,  # observer 必须转发: 缺它进度不累加且取消静默失效 (取消检查就住在这个回调里)
    )
