# -*- coding: utf-8 -*-
"""ops/cli_download.py — astro-best CLI 的 download 子系统 (抽离件)。

能力边界: download 子命令族 (start/status/progress/cancel/resume/asks/list)
的**子解析器接线 + 命令实现**。线程后台模型: start 前台运行并渲染实时进度条;
宿主要真正后台 (不占前台对话) 时, 由宿主把本命令作为后台任务运行, 任何进程
都可经 status/progress 读同一 .progress/<job_id>.json (GUI 同源)。agent
进程内直接用 src.download_manager.DownloadManager.submit 即非阻塞。

抽离缘由 (docs/architecture/file-size-budget.md R2): 原实现内嵌于
ops/astro_best_cli.py (拆分前该文件 454 净行超 400 预算; 本轮
`ops/audit/count_code_lines.py` 实测已回到 331 净行)。本族自带懒导入栈
(src.client/download_manager/download_progress), 只有 download 子命令
才拉 — 外移后非 download 路径不再连带导入下载栈。

路径安全 (P1-7): argv 来的 --out 经 src.scripts.guards.resolve_data_path
数据根锚定 (全仓单点; 原 astro_best_cli._safe_path 薄委派的唯一调用点
随迁到此处, 直接走单点)。
"""
from __future__ import annotations

# 标准库: argparse (子解析器接线) / JSON (hook ask 载荷与进度 JSON) /
#         sys (stderr 用法提示)
import argparse
import json
import sys


def register_download(sub: argparse._SubParsersAction) -> None:
    """注册 download 子命令族到子命令容器 (start/status/progress/... /list)。

    Args:
        sub: 子命令容器 (ArgumentParser.add_subparsers() 的返回值)。
    """

    # 下载管理 (后台线程 + 进度文件 + hook 分级拦截)
    p_dl = sub.add_parser("download", help="下载管理 (start/status/list/progress/cancel/resume/asks)")  # 其余六个子命令都挂在它下面
    dl_sub = p_dl.add_subparsers(dest="dl_cmd")  # dest 固定 dl_cmd, 下游只认这一个属性名
    p_start = dl_sub.add_parser("start", help="提交下载并前台渲染进度条")  # 唯一会建连接与后台线程的子命令
    p_start.add_argument("--ra", type=float, default=None)
    p_start.add_argument("--dec", type=float, default=None)
    p_start.add_argument("--radius", type=float, default=600.0,  # 角秒; 缺省 600 约合 Gaia 常规视场
                         help="半径 (角秒)")
    p_start.add_argument("--catalog", default="ps1")  # 星表短名; 非法名由业务层报 E_INVALID_INPUT
    p_start.add_argument("--fmt", default="csv",  # 输出格式; choices 限定, 不给自由串
                         choices=["csv", "txt", "json", "votable"])
    p_start.add_argument("--bands", nargs="*", default=None)
    p_start.add_argument("--sqlid", default=None, help="已有 sqlid 直接下载")  # 复用服务端已编译的查询, 不重下整张星表
    p_start.add_argument("--source-ids", default=None,
                         help="精准下载: 逗号分隔的 source_id 列表 (in 约束)")
    p_start.add_argument("--file", default=None, help="单文件 URL (字节级续传)")  # 走字节级续传而非 ADQL 路径
    p_start.add_argument("--name", default=None, help="单文件保存名")
    p_start.add_argument("--out", default="best_data")  # 仅是目录名, 落地前必过 resolve_data_path 锚定
    p_start.add_argument("--max-rows", type=int, default=50000)  # 硬上限, 防一次拖垮本机内存
    p_start.add_argument("--workers", type=int, default=2, help="并行并发度")  # 只在 start 上注册, 别处一律 getattr 兜底
    p_start.set_defaults(func=cmd_download)  # 分发靠 func 属性, 七个子命令共用一个处理函数
    # 只读型子命令: 复用同一 cmd_download, 按 dl_cmd 分发; asks 的 job_id 可省略
    for name, helptext in [("status", "单任务进度 JSON"),  # 表项在循环里建, 省五份重复样板 (start/list 各自单建, 不在本循环内)
                           ("progress", "单任务文本进度条"),
                           ("cancel", "取消任务"),
                           ("resume", "从 spec 恢复任务"),
                           ("asks", "列出待决 hook ask (非零=必须 ask)")]:
        p = dl_sub.add_parser(name, help=helptext)  # 每条子命令都指向同一处理函数
        p.add_argument("job_id", nargs="?" if name == "asks" else None)  # asks 允许零参: 列出全部待决 ask
        p.set_defaults(func=cmd_download)                                                           # download 子命令的默认处理函数
    p_list = dl_sub.add_parser("list", help="全部任务文本进度条")  # 不接 job_id 位置参数, 直接列全量
    p_list.set_defaults(func=cmd_download)                                           # list 子命令共用同一个处理函数 (靠 --job-id 区分行为)
    # 裸 `download` (无子命令) 落到 cmd_download 并由其打印用法
    p_dl.set_defaults(func=cmd_download, dl_cmd=None)  # dl_cmd=None 是未给子命令的哨兵, 用来打帮助


def cmd_download(args: argparse.Namespace) -> int:
    """下载管理: start(前台+进度条)/status/list/progress/cancel/resume/asks。

    线程后台模型: ``start`` 前台运行并渲染实时进度条; 宿主要真正后台
    (不占前台对话) 时, 由宿主把本命令作为后台任务运行 (harness background
    job / ``start-process``), 任何进程都可经 ``status/progress`` 读同一
    .progress/<job_id>.json (GUI 同源)。agent 进程内直接用
    ``src.download_manager.DownloadManager.submit`` 即非阻塞。

    Returns:
        0 任务成功/命令语义完成; 1 失败或 job 不存在; 2 hook 拦截需 ask 用户;
        130 用户 Ctrl-C 取消。
    """
    # 延迟导入下载栈: 只有 download 子命令才拉客户端/管理器/进度渲染;
    # 路径安全走 src.scripts.guards.resolve_data_path 全仓单点 (P1-7)
    import time as _time

    from src.client import BestClient
    from src.download_manager import (
        DownloadManager,  # 精确测光批量任务: 一次提交多组 source_id
        FileJob,  # 单文件字节级任务: Range 断点续传走这条
        PreciseDownloadJob,  # 精确测光任务类型
        RegionJob,  # 天区下载任务
        SqlidJob,  # 已有 sqlid 的续取任务
    )
    from src.download_progress import render_text_bar
    from src.scripts.guards import resolve_data_path

    mgr = DownloadManager(BestClient(), max_workers=getattr(args, "workers", 2))  # workers 只注册在 start 上, 其余靠 getattr 兜底

    if not getattr(args, "dl_cmd", None):  # 未给子命令: 打用法而不是抛栈
        print("download subcommands: start / status / progress / list / "
              "cancel / resume / asks", file=sys.stderr)
        return 0

    if args.dl_cmd == "start":
        job: object                                                                # job 类型注解刻意放宽成 object: 四种任务类由下面的分支各自构造
        # 四种作业类型按参数互斥选择; 优先级: 精准 ID > 单文件 URL > sqlid > 天区
        if getattr(args, "source_ids", None):
            ids = [s.strip() for s in args.source_ids.split(",") if s.strip()]  # 空段一并剔掉, 别让连续逗号变成两个空约束
            job = PreciseDownloadJob(source_ids=ids, catalog=args.catalog,                          # --precise 分支: 批量精确测光
                                     output_format=args.fmt,                                        # 输出格式由 --fmt 决定
                                     max_rows=args.max_rows)                                        # 行数上限
        elif args.file:
            # P1-7: argv 来的 --out 先过 resolve_data_path 数据根锚定 —
            # 只做文件名分隔符消毒等于绕过数据根, 路径安全铁律在 CLI 面整体失效
            # (README 声称的锚定必须真接线, 不能只写在文档里)
            job = FileJob(url=args.file, savedir=str(resolve_data_path(args.out)),                  # --file 分支: 单文件
                          filename=args.name)                                                       # 文件名可显式指定
        elif args.sqlid:
            job = SqlidJob(sqlid=args.sqlid, catalog=args.catalog,                                  # --sqlid 分支: 已有会话 id
                           output_format=args.fmt, max_rows=args.max_rows)                          # 格式同上
        else:
            job = RegionJob(ra=args.ra, dec=args.dec,                                               # --ra/--dec 分支: 天区锥形
                            radius_arcsec=args.radius, catalog=args.catalog,                        # 半径与星表
                            output_format=args.fmt, bands=args.bands or None,                       # 波段可空: 不给就按站点默认全波段
                            max_rows=args.max_rows)                                                 # 行数上限
        job_id = mgr.submit(job)  # type: ignore[arg-type]
        print(f"[download] submitted {job_id}", file=sys.stderr)  # job_id 走 stderr, 让 stdout 保持可解析
        # 前台渲染实时进度条 (轮询进度文件, 2Hz; Ctrl-C 即 cancel)
        try:
            while True:                                                                             # 进度轮询循环
                rec = mgr.status(job_id)  # 轮询进度态; rec 为 None 表示任务已不在, 退出轮询
                if rec is None:                                                                    # 任务还没登记进 manager 就先返回空
                    break
                print("\r" + render_text_bar(rec), end="", flush=True)
                if rec["status"] in ("done", "failed", "cancelled", "blocked"):  # 四个终态才收尾, 其余继续轮询
                    print()                                                                         # 每轮打一个空行: 让进度条视觉上分行
                    if rec["status"] == "blocked" and rec.get("hook"):
                        # hook 拦截: 打印 ask 载荷 (调用方必须向用户 ask)
                        print(json.dumps({"hook_ask": rec["hook"]},
                                         ensure_ascii=False, indent=2))                             # --json 出口
                        return 2
                    if rec["status"] == "done":
                        print(json.dumps({"job_id": job_id,
                                          "path": rec["result"]["path"]},
                                         ensure_ascii=False))                                       # 文本出口
                        return 0
                    print(f"[download] {rec['status']}: {rec.get('error')}",
                          file=sys.stderr)                                                   # 出错走 stderr: 进度这类正常输出不能混进错误流
                    return 1
                _time.sleep(0.5)  # 2Hz 轮询; 再快只是白烧 CPU, 进度条也刷不出来
        except KeyboardInterrupt:
            # 用户中断: 必须显式 cancel, 否则后台线程会继续跑完整个下载
            mgr.cancel(job_id)  # Ctrl-C 要显式撤单, 否则后台线程会继续下载
            print(f"\n[download] cancelled {job_id}", file=sys.stderr)
            return 130
        return 0

    if args.dl_cmd == "status":
        rec = mgr.status(args.job_id)                                                               # 查单个任务状态
        if rec is None:                                                                             # 查不到即非零
            print(f"job not found: {args.job_id}", file=sys.stderr)
            return 1
        print(json.dumps(rec, ensure_ascii=False, indent=2))                                        # JSON 形态的状态
        return 0

    if args.dl_cmd == "list":
        for rec in mgr.list_jobs():                                                                 # 列出全部任务
            print(render_text_bar(rec))                                                             # 文本形态用进度条渲染
        return 0

    if args.dl_cmd == "progress":
        rec = mgr.status(args.job_id)                                                               # resume 的前置查询
        if rec is None:                                                                             # 任务不存在即非零
            print(f"job not found: {args.job_id}", file=sys.stderr)
            return 1
        print(render_text_bar(rec))                                                                 # 文本形态
        return 0

    if args.dl_cmd == "cancel":
        ok = mgr.cancel(args.job_id)  # 返回布尔: 任务可能早已终态, 撤单未必成功
        print(json.dumps({"job_id": args.job_id, "cancelled": ok},
                         ensure_ascii=False))                                                       # --json 形态
        return 0 if ok else 1

    if args.dl_cmd == "resume":
        # 原地续传: 返回原 job_id (file/precise 以原参数原地重跑, 旧进度
        # 记录被推到新终态; region/sqlid 从页级 checkpoint 断点页继续)
        resumed_id = mgr.resume(args.job_id)                                            # 续跑: 终态作业会原样返回 job_id 而不是误报"没有断点"
        print(json.dumps({"resumed_from": args.job_id, "job_id": resumed_id},
                         ensure_ascii=False))                                                       # 续跑结果回显
        return 0

    if args.dl_cmd == "asks":
        asks = mgr.pending_asks()  # 待决 hook 快照; 调用方必须逐条向用户 ask
        print(json.dumps({"pending_asks": asks}, ensure_ascii=False, indent=2))
        return 1 if asks else 0  # 有待决 ask 时非零: 调用方必须 ask 用户

    print(f"unknown download subcommand: {args.dl_cmd}", file=sys.stderr)  # 兜底分支: 防新增子命令漏接线时静默无输出
    return 1
