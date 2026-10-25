"""src.download_region — 区域下载编排 (std 组展开 / 断点路由 / 一次性锥搜落盘)。

能力边界: 只做"给定天区与星表, 决定走哪条下载路径并落盘"的编排; 具体的
查询/分页/checkpoint/落盘都委托 ``BestDownloader`` 的方法。
**不发网络请求、不自己拼表单**。

为什么单独成文: 区域编排是三段分支 (std 组展开 / 断点路由 / 一次性锥搜) 的
决策树, 与"怎么落盘"是正交的关注点; 混在 downloader 里会让"一次下载经历什么"
被冲散, 也把 downloader 推过 400 行净代码预算。
"""
from __future__ import annotations

# 标准库: 日志 (区域下载失败留痕) / 类型标注与 observer 回调签名
import logging
from typing import Callable, Optional

# 本地: 列约束数据模型 (波段 -> 星等列的约束输入) / 协议层权威表
# (std 导航分组成员 + 波段到星等列的映射)
from src.models import ColumnConstraint
from src.protocol import CATALOG_GROUPS, magnitude_column

logger = logging.getLogger(__name__)  # 区域编排失败留痕的唯一出口, 便于按天区回溯


def download_region(
    downloader,                                                                              # 下载器: 提供查询、落盘与断点三种能力, 本模块只编排
    ra_center: float,                                                                               # 天区中心赤经(度): 区域定位依据
    dec_center: float,                                                                              # 天区中心赤纬(度): 与赤经共同界定天区
    radius_arcsec: float = 600.0,                                                                   # 区域半径(角秒): 缺省面向小批量建库
    catalog: str = "ps1",
    bands: Optional[list[str]] = None,                                                          # 波段列表可空: 缺省不限波段, 整表测光一并返回
    output_format: str = "csv",
    output_file: Optional[str] = None,                                                            # 输出文件名可空: 缺省按星表天区半径波段生成
    max_rows: int = 50000,                                                                          # 取回上限: 与页大小解耦, 便于分批
    page_size: int = 1000,                                                                          # 页大小: 决定单次请求体积与中断粒度
    job_id: Optional[str] = None,                                                                   # 作业标识可空: 给了就带断点
    resumable: bool = False,                                                                        # 断点开关: 与作业标识给任一即生效
    on_page_observer: Optional[Callable[[int, list], None]] = None,                              # 逐页回调: 取消检查与进度累加都挂在这一个钩子
) -> str:
    """把一个天区下载为本地文件 (区域/批量下载编排入口)。

    空间选择以协议层原生的服务端锥搜 (``pos.type=cone``) 提交: RA/Dec
    *between* 列约束这个键集服务端从不接受, 查询返回空集, 调用方只看到
    一个空文件 (静默错误), 所以位置约束不能自己搓。

    ``catalog="std"`` 会展开成 Standard Stars 导航组的全部成员星表,
    逐个下载后再合并成一份导出 (与 :meth:`BestClient.cone_search` 的
    组展开口径与 :meth:`BestClient.cone_search` 一致: 静默把组窄化成单表
    会让调用方少拿一整组数据, 因此组必须完整展开。

    断点语义: ``resumable=True`` (或显式给了 ``job_id``) 时转入
    :meth:`BestDownloader.download_by_constraints` 的断点路径 — job_id 即
    checkpoint 键, 未显式给定时按 (星表, 天区中心, 半径) 生成确定性 id,
    同一区域再次提交会复用同一断点实现原地续传。``catalog="std"`` 组展开
    时 job_id 透传给每个成员 (成员键 = ``{job_id}_{member}``), 另有一份
    组级 checkpoint 记录展开参数 — ``resume_job(job_id)`` 据此重入组展开,
    同参数并行下载也不撞成员断点键。

    Args:
        downloader: ``BestDownloader`` 实例 (提供查询/落盘/合并能力)。
        ra_center: 中心赤经 (度, ICRS)
        dec_center: 中心赤纬 (度, ICRS)
        radius_arcsec: 搜索半径 (角秒)
        catalog: 目标星表 (ps1, std, stripe82, gaia_dr3 等)
        bands: 纳入过滤的波段列表 (如 ["g", "r", "i"])
        output_format: csv, txt, json, votable
        output_file: 输出文件名 (None 时按天区参数自动生成)
        max_rows: 最大行数
        page_size: 每页行数
        job_id: 可续传 checkpoint 的作业标识
        resumable: True 时把页进度落盘, 支持断点续传
        on_page_observer: 每页回调 (page, sources) — 取消检查与进度累加的挂点

    Returns:
        落盘文件路径。

    Raises:
        RuntimeError: 查询失败 (result.success 为假)。
    """
    constraints: list[ColumnConstraint] = []  # 先建空壳: 非断点与断点两条路径共用同一份波段约束
    if bands:                                                                                    # 有波段才建约束: 不限时多一个键可能被站点误解
        for b in bands:                                                                     # 逐波段建约束: 每个波段一个列约束, 少一个就少一个过滤
            # 波段 -> 该星表的真实星等列 (查 protocol 映射表): 按
            # f"{b}psf"/f"{b}mag" 之类的模式猜列名会约束到幽灵列,
            # 服务端按未知列处理, 过滤静默失效。
            constraints.append(ColumnConstraint(                                                    # 追加而非覆盖: 多个波段的约束要同时生效
                name=magnitude_column(catalog, b),                                         # 列名经协议层映射: 猜列名星表根本不发布, 过滤会静默失效
                constraint="notequal",           # 用 notequal/null 而不是 IS NOT NULL: 站点表单只认 notequal
                value="null",                   # 字符串 "null" 是站点的空值方言, 不是 Python None
            ))

    if catalog == "std":  # 组的判定走字面量 "std": 它是星表组而非真实表, 没有自己的 /q 路由
        # Q-22: 导航组 (std) 没有自己的 /q 路由, 展开为全部成员星表
        # 逐个下载, 再由 _merge_region_files 合并为一份导出
        if resumable or job_id:  # 两个条件任一为真即走断点路径: 显式 job_id 本身就蕴含可续传
            # 透传 job_id 给每个成员 (B5): 成员 checkpoint 键由
            # {job_id}_{member} 派生 — 成员若改用自动生成的
            # region_{member}_ra..._dec..._r... 键, 后果有两个:
            # (1) resume(job_id) 在组级键上找不到断点 -> FileNotFoundError
            #     (断点实际存在于成员自动键下);
            # (2) 同参数 std 并行下载撞同一成员断点键, 页进度互相覆盖。
            # 组级 checkpoint 记录展开参数 (ra/dec/radius/格式...), 是
            # resume 的入口事实源; 未显式给 job_id 时按单星表同一口径生成
            # 确定性组 id (同一区域再次提交复用同一组断点)。
            effective_job_id = job_id or (  # 确定性组 id: 同一区域再次提交命中同一组断点, 换 id 等同重新下载
                f"region_std_ra{ra_center:.2f}_dec{dec_center:.2f}_"
                f"r{radius_arcsec:.0f}"
            )
            # 组级断点 (外部 IO): 先落盘再展开成员 — 进程在任何一个成员
            # 中途被杀, 组参数都还在, resume 能重入组展开
            downloader.checkpoint.save(effective_job_id, {  # 存的是展开参数而非结果: 它是 resume 重入组的唯一事实源
                "job_id": effective_job_id,
                "group": "std",
                "ra": ra_center,
                "dec": dec_center,
                "radius": radius_arcsec,
                "bands": bands,
                "output_format": output_format,
                "output_file": output_file,
                "max_rows": max_rows,
                "page_size": page_size,
            })
        parts = [  # 逐成员串行: 并行下载会争同一份组级 checkpoint, 页进度互相覆盖
            downloader.download_region(                                                             # 逐成员下载: 成员各自落一份临时文件
                ra_center=ra_center, dec_center=dec_center,                                       # 几何参数逐成员透传: 各成员查的是同一片天区
                radius_arcsec=radius_arcsec, catalog=member,                                       # 半径与成员表: 成员表名决定请求打到哪张表
                bands=bands, output_format=output_format,                                           # 波段与格式: 与组级请求同一口径
                output_file=None, max_rows=max_rows, page_size=page_size,                   # 成员不落最终名: 合并器认文件不认名, 名字由它统一生成
                job_id=(f"{effective_job_id}_{member}"
                        if (resumable or job_id) else None),                                     # 成员断点键派生: 不给作业标识时成员不留断点键
                resumable=resumable, on_page_observer=on_page_observer,                             # 断点与回调透传: 少传就静默丢进度与取消
            )
            for member in CATALOG_GROUPS["std"]
        ]
        merged = downloader._merge_region_files(parts, catalog, ra_center,  # 只在成员全部落盘后合并: 合并器认文件不认查询
                                                dec_center, radius_arcsec,                      # 合并器收全部成员: 少一个成员就会静默少一块数据
                                                bands, output_format,                          # 波段与格式随行传: 合并产物要靠它们定形态与元数据
                                                output_file)                                        # 输出名可空: 缺省由合并器生成
        if resumable or job_id:  # 与入口同一判据: 非断点路径压根没存过组级断点, 无从删起
            # 组完成即删组级断点 (外部 IO): 与成员"成功即删"同口径 — 残留
            # 会让 resume 对一个已完成作业重复展开全部成员
            downloader.checkpoint.delete(effective_job_id)  # 成功才删: 半途失败留着才能续
        return merged  # 返回合并产物而非 parts: 调用面只认"这个天区的一份导出"

    if resumable or job_id:  # 单表断点分支: 与组分支的差别只在"要不要先展开成员"
        # 断点语义: job_id 即 checkpoint 键。未显式给定时按
        # (星表, 天区中心, 半径) 生成确定性 id — 同一区域再次提交
        # 复用同一断点实现原地续传; 换 id 则等同重新下载。
        effective_job_id = job_id or (  # 与组分支同一口径, 只是前缀换成真实星表名
            f"region_{catalog}_ra{ra_center:.2f}_dec{dec_center:.2f}_"
            f"r{radius_arcsec:.0f}"
        )
        return downloader.download_by_constraints(  # 断点语义在此出口: radec 随行, 续传才复原得出锥搜条件
            constraints=constraints,                                                             # 波段约束整份传: 断点路径与非断点路径用同一份
            catalog=catalog,                                                                        # 星表传名: 走约束下载通道
            output_format=output_format,                                                            # 格式声明: 只进溯源, 落盘层才真正转换
            output_file=output_file,                                                                # 输出名透传: 显式名原样尊重
            max_rows=max_rows,                                                                      # 取回上限透传: phase-2 本地封顶, 不改服务端会话 (A2-03)
            page_size=page_size,                                                                    # 页大小透传: 翻页粒度
            job_id=effective_job_id,                                                            # 作业标识用算出的那一份: 断点键与写入时必须一致
            resumable=True,                                                                         # 强制走断点: 走进这一段的目的就是留断点
            on_page_observer=on_page_observer,                                                      # 逐页回调透传: 缺它进度不累加且取消失效
            radec=(ra_center, dec_center, radius_arcsec),                                           # 锥搜三元组随行: 续传要靠它复原锥搜条件
        )

    # 非断点路径: 一次性锥搜 + 落盘 (无 checkpoint — 中途失败只能
    # 整任务重来, 这也是默认走断点路径的原因)
    result = downloader._query_by_catalog(                                                          # 非断点路径直查: 一次两阶段协议走完
        catalog, constraints, output_format, max_rows, page_size,                                  # 星表与约束按位传: 与约束下载通道同一签名
        radec=(ra_center, dec_center, radius_arcsec),                                               # 锥搜三元组随行: 与断点路径同一几何条件
    )
    if not result.success:  # 抛而不返回空文件: 静默产出空文件会被读成"这片天区没源"
        logger.error("Download failed: %s", result.error)  # 先留痕再抛: 异常栈之外还要一份可检索文本
        raise RuntimeError(f"Download failed: {result.error}")  # 显式抛: 空结果与查询失败在调用方必须可区分

    if not output_file:  # 未给文件名才自动生成: 显式命名优先于约定
        # 自动命名: 星表_天区_半径_波段, 人可直接认出文件对应哪次查询
        bands_str = f"_{''.join(bands)}" if bands else ""  # 无波段则不留空下划线: 文件名不该出现残缺形态
        output_file = (                                                                            # 自动名只在没给名时用: 显式命名优先于约定
            f"best_{catalog}_ra{ra_center:.1f}_dec{dec_center:.1f}"
            f"_r{radius_arcsec:.0f}arcsec{bands_str}.{output_format}"
        )

    return downloader._save_result(result, output_file, output_format)  # 落盘也走 downloader: 本模块只决定走哪条路, 不自己写文件
