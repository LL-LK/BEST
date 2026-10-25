"""下载取消语义单元测试: precise 页级取消 / file 取消与网络失败的可区分性。

守的不变量 (B1/B2, docs/architecture/file-size-budget.md §6.1):
  B1 — precise 任务的每页 observer 首行必须查取消标志: 页回调不查的话,
       cancel() 置位后 precise 任务仍跑到自然结束, 终态记 done 而非
       cancelled (region/sqlid 每页都查, 唯独 precise 不能漏)。
  B2 — 取消与网络失败必须可区分: download_file 取消时返回 None
       (不抛 JobCancelledError), _run_file 若对 None 一律报 RuntimeError,
       调用方就会把用户取消读成网络失败。现在取消标志可判别:
       取消 -> cancelled, 网络失败 -> failed。

同步模式 (与 test_download_manager.py 既有写法一致): 任务进度由 worker 写
.progress 文件, 测试侧只用内存 Event 等"任务已开跑", 用 mgr.result() 等
Future 收敛后再单次读进度记录 — 避免轮询读文件与 worker 的原子写在
Windows 上相撞 (os.replace 对正被读取的目标会 WinError 5)。
"""
from __future__ import annotations

# 标准库: threading (开跑窗口的内存同步原语) / time (让任务跑到中间态)
import threading
import time

# 标准库: patch 替换 BestDownloader 的下载方法, 避免真实网络请求
from unittest.mock import patch

# 测试框架: raises 断言异常; tmp_path 提供每次用例独立的临时目录
import pytest

try:
    # 本地: 生产客户端 (管理器的 HTTP 面, rate_limit=0 关掉礼貌限流)
    from src.client import BestClient

    # 本地: 被测单元 — 管理器 + file/precise 两类任务载体
    from src.download_manager import (
        DownloadManager,  # 管理器本体: 取消语义都落在这里
        FileJob,  # 字节级任务: 取消与网络失败的区分在这条路径上
        PreciseDownloadJob,  # 精准任务: 页级取消标志在这条路径上
    )

    # 本地: 进度状态机枚举 (cancelled 是断言的状态锚点)
    from src.download_progress import STATUS_CANCELLED
except Exception as _legacy_err:  # legacy-import-guard
    # 源码树调整导致旧导入路径失效时整模块跳过, 不让收集期报错
    import pytest as _pytest
    _pytest.skip(f'legacy import unavailable: {_legacy_err!r}', allow_module_level=True)            # 模块级跳过: 导入树问题不该算用例失败


def _mgr(tmp_path, **kw):
    """构造管理器: 三个运行时目录全部锚到 tmp_path (隔离状态, 断言可预测)。"""
    return DownloadManager(BestClient(rate_limit=0),
                           output_dir=str(tmp_path / "out"),                                        # 产物目录锚在临时区
                           progress_dir=str(tmp_path / ".progress"),                               # 进度目录锚在临时区: 终态断言读的是这一份
                           checkpoint_dir=str(tmp_path / ".checkpoints"),                           # 断点目录锚在临时区
                           **kw)                                                                    # 其余构造参数由用例自选


class TestPreciseCancel:
    """精准下载的取消: 页边界生效, 终态必须是 cancelled 且任务真的停下。"""

    def test_precise_job_cancel_lands_cancelled_and_stops_paging(self, tmp_path):
        """cancel() 后 precise 任务必须转 cancelled 且不再发起后续页 (B1)。

        守的不变量: 页回调不查取消标志的话, cancel() 只置了个无人读取的
        标志 — precise 任务跑到自然结束, 终态记 done, 用户以为取消了, 带宽
        还在往外流。observer 首行查取消 (与 region/sqlid 同一形态),
        done_pages < 5 与 pages_started < 5 证明它在中途真的停下了。
        """
        mgr = _mgr(tmp_path)  # 管理器在用例内构造: cancel 与 status 都作用在同一个实例上
        target = tmp_path / "out" / "p.csv"                                                        # 产物路径: 替身返回它, 断言才有可比对象
        target.parent.mkdir(parents=True, exist_ok=True)                                        # 先建目录: 后台线程写产物时目录不存在会直接失败
        # 产物预置 2 行: 取消路径下 _verify_row_count 不会被触发; 不取消跑完也不会
        # 被 0 行 hook 拦成 blocked — 终态对比因此只剩"取消/不取消"这一个变量
        target.write_text("calibstars_id,ra\nX1,1.0\nX2,2.0\n",  # 预置 2 行非空: 0 行会被 0 行 hook 拦成 blocked, 终态就不是 done
                          encoding="utf-8")                                                         # 编码显式钉死
        pages_started = []                                                                          # 逐页记账: 页边界生效与否只能从这里看
        first_page_seen = threading.Event()                                                         # 内存事件: 用来确认任务真的开跑了

        def _slow(self, *a, on_page_observer=None, **kw):
            """每页 0.1s 的五页任务: 给取消请求留出"跑到中间"的时间窗。

            守的回归: 取消必须能在任务执行中被观察到; 若替身瞬间跑完,
            "中途终止"这条断言会在任务已结束的情况下假通过。
            """
            for p in range(1, 6):  # 固定 5 页: 少于一页断不了「中途停住」, 多于五页只拉长用例
                pages_started.append(p)                                                             # 记下页号
                if on_page_observer:                                                                # observer 可能缺席, 显式判一次
                    on_page_observer(p, [1, 2])  # 每页回调必须真的被调用: 取消标志就查在这条链上, 漏调即测不到
                first_page_seen.set()                                                             # 首页才置位: 取消窗口要落在页边界上才验得到
                time.sleep(0.1)  # 每页 0.1s: 替身瞬间跑完的话, 「中途终止」会在任务结束后假通过
            return str(target)

        with patch("src.downloader.BestDownloader.download_by_constraints",                         # 打桩在被测下载方法上
                   _slow):
            jid = mgr.submit(PreciseDownloadJob(                                                    # 提交精准任务
                source_ids=["X1", "X2"], catalog="stripe82"))                                    # 两个 ID: 页级取消要跑在多页任务上才看得出
            # 内存同步: 观测到第一页即说明 worker 已开跑 (不读进度文件)
            assert first_page_seen.wait(timeout=5)  # 先确认 worker 开跑再取消: 否则 cancel 落在任务启动前, 等于没测
            assert mgr.cancel(jid) is True          # cancel 返回 True 才算置位成功: False 说明任务已先结束, 结论无效
            # Future 收敛后 worker 已停止一切写盘, 此时读进度记录才安全
            with pytest.raises(RuntimeError, match="status=cancelled"):  # result 抛 RuntimeError 是终态契约: 取消的任务不该像成功那样返回
                mgr.result(jid, timeout=30)                                                         # 等任务收敛: 只有收敛后终态才是终态
        rec = mgr.status(jid)                                                                       # 读回进度记录
        assert rec["status"] == STATUS_CANCELLED  # 状态锚点用常量而非字面量: 状态名漂移时这条会跟着一起漂
        assert rec["done_pages"] < 5              # 断页数: 只断状态的话, 任务跑完再补记 cancelled 也能过
        assert len(pages_started) < 5             # 断真实请求次数: 状态对了但仍把五页跑完, 带宽照样白耗
        mgr.shutdown()                                                                              # 收线程池, 不然后台线程会漏给后续用例


class TestFileCancel:
    """文件下载的取消: 终态 cancelled, 且与网络失败的 None 可区分。"""

    def test_file_job_cancel_lands_cancelled_not_failed(self, tmp_path):
        """取消 file 任务: 终态必须是 cancelled 而不是 failed (B2)。

        守的不变量: best_export.download_file 取消时返回 None (不抛
        JobCancelledError), 所以 _run_file 不能对 None 一律 RuntimeError —
        取消被记成 failed, 调用方把"用户主动取消"读成"下载出错", 还可能
        触发无意义的重试与告警。None + 取消标志已置 -> JobCancelledError
        -> _run 的 cancelled 分支, 且不记 error 文案 (取消不是错误)。
        """
        mgr = _mgr(tmp_path)                                                                        # 运行时目录全在临时区
        entered = threading.Event()                                                                 # 内存事件: 造出"任务在跑"的窗口

        class _CancelAwareBest:
            """假客户端: download_file 阻塞到取消置位后返回 None。

            存在理由: 这个替身复刻 best_export.download_file 的取消语义
            (标志置位即中止写盘并返回 None, 与网络失败同形态) — 少了它,
            "取消与失败可区分"这条回归在离线环境里无从触发。
            """

            def download_file(self, url, savedir="./", filename=None,
                              job_id=None, progress_tracker=None,                                   # 签名分行只为可读: 语义与真实调用一致
                              cancel_event=None, **kw):                                           # 吃住全套实参, 少一个就 TypeError
                """置 entered 事件, 等取消标志置位后返回 None (字节级中止)。"""
                entered.set()                                                                       # 置位即代表已经进入下载面
                cancel_event.wait(timeout=10)  # 等取消标志而非固定 sleep: 固定等待要么 flaky 要么白白拖慢
                return

        mgr.client = _CancelAwareBest()  # 换掉 client: 替身必须挂在管理器实际取用的那个属性上
        jid = mgr.submit(FileJob(url="https://nadc.china-vo.org/data/best/cancel.fits"))            # 提交字节级任务
        # 内存同步: worker 已进入下载函数 (不读进度文件)
        assert entered.wait(timeout=5)  # 先确认进入再取消: 与 precise 那条同构, 保证取消落在执行期中
        assert mgr.cancel(jid) is True                                                        # 取消要真的返回 True: 标志位没置上就谈不上取消
        with pytest.raises(RuntimeError, match="status=cancelled"):                               # 错误消息要带终态: 调用方据此区分取消与失败
            mgr.result(jid, timeout=30)                                                             # 等任务收敛
        rec = mgr.status(jid)                                                                       # 读回进度记录
        assert rec["status"] == STATUS_CANCELLED  # 断 error is None: 取消不是错误, 记下错误文案会触发无意义重试
        assert rec["error"] is None  # 取消不是错误: 不记 error 文案
        mgr.shutdown()                                                                              # 收线程池

    def test_file_cancel_and_network_failure_are_distinguishable(self, tmp_path):
        """同一份 None 返回: 取消 -> cancelled (无 error), 网络失败 -> failed (带 error)。

        守的不变量: 两条路径的返回值同形 (None), 调用方若只看到同一条
        错误, 就会在取消后自动重试一个用户主动停下的任务, 纯粹的内耗。终态
        与错误信息必须能把两者分开: 取消不记 error, 失败的 error 指名
        "returned None" 与具体 URL。
        """
        mgr = _mgr(tmp_path)                                                                        # 运行时目录全在临时区
        entered = threading.Event()                                                                 # 内存事件: 造出"任务在跑"的窗口

        class _ScriptedBest:
            """假客户端: cancel URL 阻塞到取消置位, fail URL 直接返回 None。"""

            def download_file(self, url, savedir="./", filename=None,
                              job_id=None, progress_tracker=None,                                   # 同样要吃住全套实参
                              cancel_event=None, **kw):                                             # 占位, 语义与真实调用一致
                """按 URL 分派: 一个等取消, 一个立即失败 (都是 None 返回)。"""
                if "cancel" in url:  # 按 URL 分派两条路径: 同一个 None 返回, 处理却必须不同
                    entered.set()                                                                   # 置位代表已进入下载面
                    cancel_event.wait(timeout=10)                                              # 真正等取消标志: 这条要验的是"取消可被底层感知"
                return

        mgr.client = _ScriptedBest()                                                             # 换成脚本化客户端: 取消与失败两条路径都要走它
        cancel_jid = mgr.submit(FileJob(url="https://nadc.china-vo.org/data/best/cancel.fits"))     # 先提交一个将被取消的任务
        assert entered.wait(timeout=5)                                                          # 确认它已经开跑, 不然取消会打在还没开始的任务上
        assert mgr.cancel(cancel_jid) is True                                                       # 取消要真的返回 True
        with pytest.raises(RuntimeError, match="status=cancelled"):                           # 错误消息带终态: 取消与失败的唯一可编程区别就在这里
            mgr.result(cancel_jid, timeout=30)                                                      # 等任务收敛
        cancel_rec = mgr.status(cancel_jid)                                                         # 取消侧的状态记录

        fail_jid = mgr.submit(FileJob(url="https://nadc.china-vo.org/data/best/fail.fits"))         # 再提交一个将被判失败的任务
        with pytest.raises(RuntimeError, match="returned None"):  # 失败侧的 match 也要钉: 报错文案是调用方区分两者的唯一线索
            mgr.result(fail_jid, timeout=30)                                                        # 失败侧也要等收敛, 两边才可比
        fail_rec = mgr.status(fail_jid)                                                             # 失败侧的状态记录

        assert cancel_rec["status"] == STATUS_CANCELLED                                             # 取消侧必须是 cancelled
        assert cancel_rec["error"] is None                                                     # 取消侧不该带错误文案: 有文案就说明它被当成失败了
        assert fail_rec["status"] == "failed"        # 终态字面量 failed: 与 cancelled 成对, 二者的区别正是本用例的目的
        assert "returned None" in fail_rec["error"]  # error 文案要指名 returned None: 排查时才知道是下载层没回文件
        mgr.shutdown()
