# -*- coding: utf-8 -*-
"""evals.probe_support — 探针离线化设施 (桩管理器 / 桩客户端 / 探针共用常量)。

能力边界: 本模块提供"让探针不触网也能跑完整链路"的基础设施 ——
``_stub_manager`` 造一个不落真实文件的 DownloadManager, ``_StubFileClient``
冒充文件下载客户端, 三个常量是多个探针共用的期望值基准。

为什么独立成模块: 这些设施与"探针测什么"是正交关注点。二十多个探针 + 设施同文件时
probes.py 会超出 400 行净代码预算; 且设施的替换 (例如换一种桩策略) 不应牵动任何
探针。承 docs/architecture/file-size-budget.md §3.1 的拆分纪律。
(探针个数随场景增删变动, 真正的真值是 evals/probes.py 的 ``_exec_*`` 函数与
evals/eval_runner.py 的 SCENARIO_PROBES 注册表 —— 故此处不写死数字。)

白盒锚点: references/ALGORITHM-SPEC.md §3。
"""
from __future__ import annotations


class _StubFileClient:
    """FileJob 探针用桩: 不联网, 模拟一个 0.15s 的字节下载。

    0.15s 的睡眠是故意留的: 足以让"后台线程"与"前台轮询"产生真实竞态窗口,
    把 submit 的同步/异步语义暴露出来 (0s 的话任何实现都能秒过)。
    """

    def download_file(self, url, savedir="./", filename=None, job_id=None,
                      progress_tracker=None, cancel_event=None, **kw):
        """桩下载: 睡 0.15s 后假报 100 字节完成, 返回不存在的路径。

        这 0.15s 睡眠是故意留的: 足以让"后台线程"与"前台轮询"产生真实竞态窗口,
        把 submit 的同步/异步语义暴露出来 (0s 的话任何实现都能秒过)。

        Args:
            url: 下载地址 (桩不使用)。
            savedir: 保存目录 (桩不使用)。
            filename: 文件名; None 时用 ``file.dat``。
            job_id: 任务 id (桩不使用)。
            progress_tracker: 进度跟踪器; 非 None 时上报 100 字节总量并推进。
            cancel_event: 取消事件 (桩不检查 — 由被测代码负责传递)。
            **kw: 忽略其余关键字参数, 保持与真实客户端签名兼容。

        Returns:
            形如 ``/stub/<filename>`` 的假路径; 文件并不存在。
        """
        # 函数内导入: 只在走进桩下载路径时才需要 time (避免模块级依赖)
        import time
        time.sleep(0.15)  # 延迟导入 time: 只在替身里模拟网络耗时, 不占模块级
        if progress_tracker is not None:                                                         # 有进度跟踪器才推进: 无跟踪器时不该凭空造进度
            progress_tracker.set_total_bytes(100)  # 先把总量定死, 下面只推进增量: 复现真实下载的回调顺序
            progress_tracker.advance_pages(0, bytes_delta=100)
        return f"/stub/{filename or 'file.dat'}"
def _stub_manager(tmpdir: str, **kw):
    """构造一个全部 IO 都落在临时目录里的 DownloadManager (探针共用)。

    Args:
        tmpdir: 临时目录路径; 进度/断点/输出三个子目录都锚在它里面。
        **kw: 透传给 DownloadManager (如 max_workers)。

    Returns:
        配好桩客户端与临时目录的 DownloadManager 实例。
    """
    # 函数内导入: 下载管理器 (探针要用桩客户端 + 隔离的临时目录构造它)
    from src.download_manager import DownloadManager

    return DownloadManager(_StubFileClient(), output_dir=tmpdir,
                           progress_dir=f"{tmpdir}/.progress",
                           checkpoint_dir=f"{tmpdir}/.checkpoints", **kw)
# 锥搜 ADQL 常量: 被 tap_adql / tap_service 两个探针共用, 抽成常量避免两边漂移
CONE_ADQL = (                                                                                  # 锥搜的 ADQL 模板: 三个字段的排布在这里定死
    "SELECT ra, ps1_rpsf FROM best.ps1 "
    "WHERE CONTAINS(POINT('ICRS', ps1_ra, ps1_dec), CIRCLE('ICRS', 180.0, 30.0, 0.1)) = 1"
)
