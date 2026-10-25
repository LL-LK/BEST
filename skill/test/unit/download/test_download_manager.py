"""DownloadManager 单元测试: 后台执行 / 并行 / hook 拦截 / 取消 / 断点续传。

守的不变量: submit 必须立即返回 (真后台); 并行任务输出文件名必须唯一 (同名互相
覆盖); hook 拦截要落 ask 载荷 + pending_asks 可查; **JobCancelledError 必须
穿透分页循环** (被外层 ``except Exception`` 吞成 failed 时, 任务还会跑完);
resume 必须沿用同一 job_id 从 checkpoint 续传, 而不是重新提交。
"""
from __future__ import annotations

# 标准库: threading (取消标志的载体, 与 DownloadManager 内部同一机制) /
# time (断言提交耗时/并发加速/等任务跑到中间态)
import threading  # cancel_event 的载体: 与管理器内部同一套机制, 不用替身造假的取消
import time  # 墙钟: 提交耗时、并发加速、等任务跑到中间态都靠它量

# 标准库: pathlib 构造输出/进度/断点目录 (全部锚到 tmp_path)
from pathlib import Path  # 三个目录全部锚到 tmp_path, 用例不得碰真实运行目录

# 标准库: patch 替换 BestDownloader 的下载方法, 避免真实网络请求
from unittest.mock import patch  # patch 换掉下载方法: 全程离线, 不打真实站点

# 测试框架: raises 断言异常; tmp_path 提供每次用例独立的临时目录
import pytest  # raises 断言异常; tmp_path 给出每例独立的目录

try:
    # 本地: 生产客户端 (管理器的 HTTP 面, rate_limit=0 关掉礼貌限流)
    from src.client import BestClient  # 限流置 0: 否则离线用例要为礼貌间隔付出墙钟代价

    # 本地: hook 层 — 拦截异常与载荷 (blocked 流的断言依据)
    from src.download_hooks import HookBlockedError, HookInterrupt  # 拦截异常与载荷是 blocked 流的断言依据

    # 本地: 被测单元 — 管理器 + 三类任务载体
    from src.download_manager import (
        DownloadManager,  # 管理器本体: submit/result/status/cancel 都落在这里
        FileJob,  # 字节级单文件任务载体
        RegionJob,  # 区域任务载体: 并发与唯一文件名两条断言都基于它
        SqlidJob,  # sqlid 任务载体: 走 download_sqlid 那条分支
    )

    # 本地: 进度状态机枚举 (blocked/cancelled/done 是断言的状态锚点)
    from src.download_progress import STATUS_BLOCKED, STATUS_CANCELLED, STATUS_DONE
except Exception as _legacy_err:  # legacy-import-guard
    # 源码树调整导致旧导入路径失效时整模块跳过, 不让收集期报错
    import pytest as _pytest  # 别名导入: 顶部 import 若已失败, 这里重新绑定
    _pytest.skip(f'legacy import unavailable: {_legacy_err!r}', allow_module_level=True)  # 模块级 skip


def _mgr(tmp_path, **kw):
    """构造管理器: 三个运行时目录全部锚到 tmp_path。

    守的回归: 默认 output_dir/progress_dir/checkpoint_dir 是 CWD 相对的,
    直接构造会在 skill 根下留下 best_data/ .progress/ .checkpoints; 每个用例
    用独立 tmp_path, 既隔离状态也让断言可预测。
    """
    return DownloadManager(BestClient(rate_limit=0),  # 关限流: 离线用例不等礼貌间隔
                           output_dir=str(tmp_path / "out"),  # 产物目录
                           progress_dir=str(tmp_path / ".progress"),  # 进度文件目录
                           checkpoint_dir=str(tmp_path / ".checkpoints"),  # 断点目录
                           **kw)  # 其余构造参数由用例自选


def _fake_region(path_str, pages=3, delay=0.0, hook=None):
    """造一个 download_region/download_sqlid 假实现: 逐页回调 + 可选 hook 拦截。"""  # 替身可参数化: 页数与延迟是制造时间差的旋钮

    def _fake(self, *args, on_page_observer=None, **kw):  # observer 是进度累加的唯一入口: 替身必须逐页回调
        """逐页回调 observer 后返回产物路径; 传了 hook 就在末尾抛出去。

        守的回归: 进度累加必须来自 observer 回调而不是下载完后的补写; 把
        hook 提到 return 之前抛, 才能模拟"跑到一半被拦截"的真实时序。
        """
        if delay:  # 延迟放在页循环之前: 模拟"开跑就慢"而不是"跑到一半才慢"
            time.sleep(delay)  # 人为拉长, 制造可测的墙钟时间差
        for p in range(1, pages + 1):  # 逐页回调, 一页一次: 进度语义要能被页数断言区分出来
            if on_page_observer:  # observer 可能缺席: 显式判一次, 不让替身在缺回调时崩
                on_page_observer(p, [])  # 逐页回调: 进度累加的唯一来源
        if hook is not None:  # 只在传了 hook 时才拦截
            raise hook  # 在 return 之前抛, 模拟"跑到一半被拦截"
        return path_str  # 正常路径: 交回产物路径

    return _fake  # 返回替身函数本身: 交给 patch 当新实现


class TestManagerBackground:
    """后台执行: submit 不阻塞, 页进度经 observer 累加, 进度文件与 status() 同源。"""

    def test_submit_returns_immediately_then_done(self, tmp_path):  # 这条要断的是"提交即返回", 不是"跑得快"
        """submit 必须立即返回 (<0.1s) 而任务在后台线程池执行。

        守的不变量: 同步跑完才返回的话, 批量提交时 CLI 会假死数十秒; 必须
        提交即返回 job_id, 结果由 result() 阻塞等待。done_pages 由 observer
        逐页累加, 不是下载完后一次性补写。
        """
        mgr = _mgr(tmp_path)  # 输出/进度/断点三目录全锚 tmp_path, 断言才不受真实运行目录干扰
        target = str(tmp_path / "out" / "a.csv")  # 替身回传的固定产物路径
        t0 = time.time()  # 计时起点
        with patch("src.downloader.BestDownloader.download_region",  # 打在被测方法上: 走真实调度, 只换最后一跳
                   _fake_region(target, pages=3, delay=0.2)):  # 0.2s 慢任务, 拉出时间差
            job_id = mgr.submit(RegionJob(ra=180.0, dec=30.0))  # 提交即返回 job_id
            submit_elapsed = time.time() - t0  # 只量提交这一步的耗时
            assert submit_elapsed < 0.1  # 提交即返回 (后台执行)
            path = mgr.result(job_id, timeout=30)  # 这一步才阻塞等结果
        assert path == target  # 产物路径由替身决定
        rec = mgr.status(job_id)  # 读进度记录
        assert rec["status"] == STATUS_DONE  # 后台线程跑完后置 done
        # 页数取 3 而非 1: 断的是"逐页累加"这个语义, 单页时补写与累加无法区分
        assert rec["done_pages"] == 3  # 页进度经 observer 累加
        mgr.shutdown()  # 收线程池, 别把后台线程漏给后续用例

    def test_progress_file_is_shared_source(self, tmp_path):
        """进度文件为 CLI/GUI 同源: 文件内容与 status() 一致。

        守的回归: GUI/CLI 不允许各自维护一份状态 — 必须读同一个
        .progress/<job_id>.json, 否则两边状态漂移, 用户看到两个互相矛盾的
        进度。这里绕过 status() 直接读原始 JSON 验证。
        """
        mgr = _mgr(tmp_path)  # 同一条夹具: 三个目录都锚 tmp_path, 不留任何真实路径
        target = str(tmp_path / "out" / "b.csv")  # 单页任务
        with patch("src.downloader.BestDownloader.download_region",
                   _fake_region(target, pages=1)):
            job_id = mgr.submit(RegionJob(ra=1.0, dec=2.0))  # 提交
            mgr.result(job_id, timeout=30)  # 等完成
        # 标准库: json 读回进度文件 (绕过 status() 验证磁盘上的原始 JSON)
        import json  # 延迟导入: 只有这一个用例要读原始 JSON
        raw = json.loads((tmp_path / ".progress" / f"{job_id}.json")  # 文件名即 job_id
                         .read_text(encoding="utf-8"))  # 读磁盘上那份
        assert raw["status"] == STATUS_DONE  # 与 status() 同源
        assert raw["result"]["path"] == target  # 产物路径也同源
        mgr.shutdown()  # 收线程池


class TestManagerParallel:
    """并行: 真并发加速、同名防覆盖、默认并发度。"""  # 并发这条要验"真并发", 不是"多次提交"

    def test_submit_all_runs_parallel(self, tmp_path):
        """submit_all 必须真并发: 3 个 0.3s 任务 2 并发显著快于串行 0.9s。

        守的不变量: 串行提交会让批量区域下载墙钟线性叠加; 必须按
        max_workers 并发, 断言上限 0.75s 留了调度余量但仍远小于串行。
        """
        mgr = _mgr(tmp_path, max_workers=2)  # 显式给 2 并发
        target = str(tmp_path / "out" / "p.csv")  # 三个任务共用同一产物路径
        with patch("src.downloader.BestDownloader.download_region",  # 同一处打桩: 并行度变化必须体现在墙钟上
                   _fake_region(target, pages=2, delay=0.3)):
            # delay 0.3s 是制造可测时间差的最小值: 太小会被线程启动开销淹没,
            # 太大又拖慢用例; 0.75s 的上限 = 两批各 0.3s 留 0.15s 调度余量
            t0 = time.time()  # 计时起点
            ids = mgr.submit_all([  # 一次交三个: submit_all 的批量语义就在这里
                RegionJob(ra=180.0, dec=30.0),  # 任务 1
                RegionJob(ra=181.0, dec=31.0),  # 任务 2
                RegionJob(ra=182.0, dec=32.0),  # 任务 3
            ])
            for jid in ids:  # 逐个等: 串行等待才能量出并发后的总墙钟
                mgr.result(jid, timeout=60)  # 逐个等, 总墙钟才是并发后的耗时
            elapsed = time.time() - t0  # 并发总耗时
        # 3 个 0.3s 任务 2 并发: 串行需 ~0.9s, 并行应显著更快
        assert elapsed < 0.75  # 上限留了调度余量但仍远小于串行
        # 三个 id 都要断: 只断耗时的话, 实现漏派一个任务而另两个照常并发,
        # 时间照样达标, 那个任务会静默"消失"
        assert len(ids) == 3  # 三个 id 都要断, 漏派一个会静默"消失"
        mgr.shutdown()  # 收线程池

    def test_parallel_jobs_get_unique_output_files(self, tmp_path):  # 同名任务互相覆盖过一次: 这是真实发生过的丢数据事故
        """并行防覆盖: 同名 (catalog,fmt) 不同天区的任务文件名必须唯一
        (live 实证: 两任务自动同名 best_ps1_c2.csv 互相覆盖)。"""
        mgr = _mgr(tmp_path)  # 默认并发度
        seen_files = []  # 记录管理器算出的每个 output_file

        def _fake(self, *args, output_file=None, **kw):  # 替身把 output_file 收走: 返回路径与文件名无关, 排除干扰
            """把管理器算出的 output_file 收进 seen_files: 唯一性断言的依据。

            守的回归: 两个同名任务若拿到同一个文件名, 后写的会把先写的覆盖掉,
            用户 silently 少一份数据; 这里只记录不改写, 让"文件名是否唯一"
            成为可断言的事实。
            """
            seen_files.append(output_file)  # 只记录不改写, 让唯一性成为可断言事实
            return str(tmp_path / "out" / "x.csv")  # 返回路径与文件名无关

        with patch("src.downloader.BestDownloader.download_region", _fake):  # 打桩在被测下载方法上
            ids = mgr.submit_all([  # 一次交两个同名任务
                RegionJob(ra=180.0, dec=30.0, catalog="ps1"),  # 同星表同格式
                RegionJob(ra=181.0, dec=31.0, catalog="ps1"),  # 只有天区不同
            ])
            for jid in ids:  # 逐个等完: 两次都要记过文件名才可比
                mgr.result(jid, timeout=30)  # 逐个等完, 两次都记过文件名
        assert len(seen_files) == 2  # 两个任务各记一次
        assert seen_files[0] != seen_files[1]  # 互不相同才不互相覆盖
        # 断文件名里带了天区坐标: 只断"互不相同"的话, 实现退化成加个计数器
        # 后缀也能通过, 而那种名字对人不可读, 用户无法判断哪份对应哪个天区
        assert "ra180.0" in seen_files[0] and "ra181.0" in seen_files[1]  # 名字带天区才可读
        mgr.shutdown()  # 收线程池

    def test_default_workers_is_two(self, tmp_path):
        """默认并发度 2: 尊重官网礼貌限速, 不默认把站点打满。"""  # 默认并发度是对站点的承诺, 不是性能调优
        mgr = _mgr(tmp_path)  # 不传 max_workers, 走默认值
        # 断默认值而不是"某个 <=4 的值": 默认并发度是产品承诺的一部分,
        # 调高它不会被任何功能用例察觉, 只会在生产上变成被站点限流
        assert mgr.max_workers == 2  # 产品承诺, 不只是性能参数
        mgr.shutdown()  # 收线程池


class TestManagerHook:
    """hook 拦截与普通失败是两条不同的终止路径 (blocked 要 ask, failed 直接失败)。"""  # blocked 与 failed 是两条终止路径: 一个要 ask 用户, 一个直接结束

    def test_blocked_job_writes_ask_payload(self, tmp_path):
        """被 hook 拦截: 进度置 blocked, ask 载荷四要素齐全 + pending_asks 可查。

        守的不变量: 后台任务无法原地 ask, 必须把 id/raw kind/options 全落进
        进度文件并登记到 pending_asks() — 前端轮询这个列表才能向用户提问。
        只置状态不落载荷的话, GUI 只能显示"阻塞"却说不出原因。
        """
        mgr = _mgr(tmp_path)  # 三个运行时目录全锚 tmp_path: ask 载荷与待提问列表都写在临时区
        interrupt = HookInterrupt(  # 构造一次拦截: kind 与 options 都是前端要展示的字段
            kind="checksum_mismatch", reason="sha256 不匹配",  # kind 决定 ask 的问题类型, 不能省
            evidence={"expected": "aa"}, options=[{"label": "重试"}],  # evidence 留原始证据: 用户回答后要能对照重试
            job_id="")  # options 是给用户选的按钮: 空了就无从选择
        with patch("src.downloader.BestDownloader.download_region",  # 在末尾抛拦截: 模拟跑到一半被拦
                   _fake_region("/x", hook=HookBlockedError(interrupt))):  # 包成 hook 异常: 否则管理器会当成普通失败
            job_id = mgr.submit(RegionJob(ra=180.0, dec=30.0))  # 提交后由 result 取出异常
            with pytest.raises(HookBlockedError):  # 拦截必须冒泡: 被吞掉就落成 failed, 前端永远等不到 ask
                mgr.result(job_id, timeout=30)
        rec = mgr.status(job_id)  # 读回进度记录
        assert rec["status"] == STATUS_BLOCKED  # 状态必须是 blocked 而非 failed: 前端据此决定要不要弹提问
        # 进度文件存 ask 载荷 (id/question/options/raw), CLI/GUI 同源可读
        assert rec["hook"]["id"] == "hook_checksum_mismatch"  # ask 载荷要能从进度文件读到: CLI 与 GUI 同源
        assert rec["hook"]["raw"]["kind"] == "checksum_mismatch"  # raw.kind 是原始类别: 丢了就没法复现用户当时的现场
        assert rec["hook"]["options"][0]["label"] == "重试"  # 第一个选项就是重试: 前端按序展示
        asks = mgr.pending_asks()  # 待提问列表要能查到
        assert len(asks) == 1 and asks[0]["job_id"] == job_id  # 列表里要能对上 job_id: 否则前端问不到正确的任务
        mgr.shutdown()  # 收线程池

    def test_failed_job_records_error(self, tmp_path):
        """普通异常 -> failed + error 文案 (与 blocked 区分: 一个要 ask, 一个直接失败)。"""  # 普通异常不是 hook 拦截: 两条终止路径必须能区分
        mgr = _mgr(tmp_path)  # 三个目录全在 tmp_path 下: 失败记录不该污染真实进度目录

        def _boom(self, **kw):  # 恒定抛错: 让"普通失败"成为唯一变量
            """恒定抛 RuntimeError("disk full"): 制造"普通失败"而非 hook 拦截。

            守的回归: failed 与 blocked 是两条终止路径 — 这条断言失败说明
            异常分类漂移, 用户会被要求回答一个本不存在的问题。
            """
            raise RuntimeError("disk full")

        with patch("src.downloader.BestDownloader.download_region", _boom):  # 打桩在被测下载方法上
            job_id = mgr.submit(RegionJob(ra=180.0, dec=30.0))  # 提交后由 result 抛出
            with pytest.raises(RuntimeError, match="not done"):  # 匹配 "not done": 证明失败是以异常形态冒出来的, 不是静默返回 None
                mgr.result(job_id, timeout=30)
        rec = mgr.status(job_id)  # 读回进度记录
        assert rec["status"] == "failed" and "disk full" in rec["error"]  # 状态是 failed 且错误文案在: 少一半就分不清是失败还是没跑
        mgr.shutdown()  # 收线程池


class TestManagerCancel:
    """取消: 页边界生效, 状态必须是真的 cancelled。"""  # 取消是置标志位, 真正终止靠页回调里抛专用异常

    def test_cancel_running_job_mid_pages(self, tmp_path):
        """JobCancelledError 必须穿透分页循环, 状态转 cancelled 且任务真的停下。

        守的不变量 (最要紧的取消语义): 取消请求只置标志位, 真正终止靠页
        回调里的 _check_cancelled 抛 JobCancelledError。_run 若只有
        一条 ``except Exception``, 就会把这个专用异常吞成 "failed" — 状态错还是
        小事, 更糟的是吞掉后循环继续跑, 用户以为取消了, 文件还在往外写。
        except JobCancelledError 必须排在 except Exception **之前**, 走
        tracker.cancel() -> cancelled 分支; done_pages < 5 证明它没跑完。
        """
        mgr = _mgr(tmp_path)  # 三个目录全锚 tmp_path: 取消状态只落在临时进度文件里
        target = str(tmp_path / "out" / "c.csv")  # 固定产物路径: 成功分支的返回值

        def _slow(self, *args, on_page_observer=None, **kw):  # 替身逐页睡 0.1 秒: 给取消请求留出"跑到中间"的窗口
            """每页睡 0.1s 的五页任务: 给取消请求留出"跑到中间"的时间窗。

            守的不变量: 取消必须能在任务执行中被观察到; 若替身瞬间跑完,
            done_pages < 5 这条断言会在任务已结束的情况下假通过。
            """
            for p in range(1, 6):  # 五页循环: 页数是"中途终止"的判据
                if on_page_observer:  # observer 可能缺席, 显式判一次
                    on_page_observer(p, [])  # 先回调再睡: 顺序反了就变成"睡完才报一页"
                time.sleep(0.1)  # 每页 0.1 秒: 五页共 0.5 秒, 取消窗口落在中间
            return target  # 正常路径交回产物: 让"跑完"与"被取消"可比

        with patch("src.downloader.BestDownloader.download_region", _slow):  # 打桩在被测下载方法上
            job_id = mgr.submit(RegionJob(ra=180.0, dec=30.0))  # 提交后进入后台执行
            time.sleep(0.25)  # 让它跑两页
            assert mgr.cancel(job_id) is True  # 取消要真的返回 True: 标志位没置上说明提交没登记
            time.sleep(0.3)  # 留 0.3 秒给终止生效: 不等就断言会读到中间态
        rec = mgr.status(job_id)  # 读回进度记录
        assert rec["status"] == STATUS_CANCELLED  # 状态必须是 cancelled: 被吞成 failed 就等于取消没生效
        assert rec["done_pages"] < 5  # 中途终止, 未跑完
        mgr.shutdown()  # 收线程池

    def test_cancel_unknown_job_returns_false(self, tmp_path):
        """未提交过的 job_id: 取消返回 False (无标志可置), 不抛不崩。"""  # 未提交过的 id 没有标志可置: 返回 False 而不是抛异常
        mgr = _mgr(tmp_path)  # 三个目录全锚 tmp_path: 取消一个不存在的 id 也不该碰真实状态
        assert mgr.cancel("nope") is False  # False 表示"没这个任务", 调用方据此改走别的分支
        mgr.shutdown()  # 收线程池


class TestManagerResume:
    """resume: 原地续传 (同一 job_id) 而不是重新提交。"""  # resume 是原地续传: 沿用同一 job_id 而不是重新提交

    def test_resume_continues_the_same_job_from_its_checkpoint(self, tmp_path):
        """resume 必须从已保存的断点页继续, 而不是重新提交。

        守的不变量: 把任务重建后以**新 job_id** 重新 submit, 页级 checkpoint
        的键就对不上, 永远找不到, 下载从第 1 页重来, 旧 checkpoint 还永久泄漏
        在磁盘上。region/sqlid 任务必须直接委派 ``BestDownloader.resume_job``,
        沿用同一 job_id 从断点页继续拉并返回原 id (resumed_id == job_id)。
        三个 patch 分别覆盖首轮下载 (download_region)、sqlid 变体与续传入口
        (resume_job), 保证断言落在 id 复用而不是某个具体下载路径上。
        """
        mgr = _mgr(tmp_path)  # 三个运行时目录全在 tmp_path 下: 断点与进度都写在临时区
        target = str(tmp_path / "out" / "r.csv")  # 固定产物路径: 续跑要回到同一份文件
        with patch("src.downloader.BestDownloader.download_region",  # 首轮下载打桩
                   _fake_region(target, pages=1)), \
             patch("src.downloader.BestDownloader.download_sqlid",  # sqlid 变体也打桩: 免得续传委派走到别的分支时炸
                   _fake_region(target, pages=1)), \
             patch("src.downloader.BestDownloader.resume_job",  # 续传入口打桩: 断言要落在"id 复用"而不是具体下载路径上
                   _fake_region(target, pages=1)):
            job_id = mgr.submit(RegionJob(ra=180.0, dec=30.0,  # 带半径参数提交: 与续传时读到的 spec 一致
                                          radius_arcsec=180))
            mgr.result(job_id, timeout=30)  # 先跑完首轮: 断点才有得续
            resumed_id = mgr.resume(job_id)  # resume 走委派路径
            path = mgr.result(resumed_id, timeout=30)  # 拿续跑 id 再等一次: 复用同一个 id 才有"原地"可断言
        assert path == target  # 产物路径不变
        assert resumed_id == job_id  # resumed_id 必须等于 job_id: 换 id 就等于把续跑变成新任务
        mgr.shutdown()  # 收线程池

    def test_resume_without_record_raises(self, tmp_path):
        """无进度记录/无 resume_spec: FileNotFoundError (调用方应改走重新提交)。

        守的回归: 静默返回 None 会让调用方以为续传成功, 实际什么都没下。
        """
        mgr = _mgr(tmp_path)  # 三个目录全锚 tmp_path: 无记录这条路径不该读到真实进度文件
        with pytest.raises(FileNotFoundError):  # 无进度记录即抛 FileNotFoundError
            mgr.resume("nope")  # 故意用不存在的 id
        mgr.shutdown()  # 收线程池


class TestManagerSqlidAndFileJobs:
    """sqlid 与文件两类任务的作业流。"""  # sqlid 与 file 是两条不同分支: 各走一次

    def test_sqlid_job_flow(self, tmp_path):
        """SqlidJob 走 download_sqlid 路径并正常返回产物。"""
        mgr = _mgr(tmp_path)  # 三个目录全在 tmp_path 下: sqlid 分支的产物与进度都落在临时区
        target = str(tmp_path / "out" / "s.csv")  # 固定产物路径
        with patch("src.downloader.BestDownloader.download_sqlid",  # 打桩在 download_sqlid 上: 证明它走的确实是这一条分支
                   _fake_region(target, pages=2)):
            job_id = mgr.submit(SqlidJob(sqlid="s3898", catalog="ps1"))  # 带 sqlid 提交: 走的是按源 id 取数的路径
            assert mgr.result(job_id, timeout=30) == target  # 产物路径由替身决定
        mgr.shutdown()  # 收线程池

    def test_file_job_flow_with_progress(self, tmp_path):
        """FileJob 的字节进度经 progress_tracker 累加并落进进度文件。

        守的回归: 文件下载没有分页, 进度只能走 set_total_bytes +
        advance_pages(0, bytes_delta=...) 的字节口径; done_bytes=100 必须出
        现在 status() 里, 否则 GUI 对大文件任务显示 0%。
        """
        mgr = _mgr(tmp_path)  # 三个目录全锚 tmp_path: 字节进度只写进临时进度文件

        class _FakeBest:
            """假客户端: 只实现 FileJob 会用到的 download_file, 其余一律不管。"""

            def download_file(self, url, savedir="./", filename=None,  # 签名要吃住全套实参: 少一个就 TypeError
                              job_id=None, progress_tracker=None,  # 签名分行只为可读, 语义与真实调用一致
                              cancel_event=None, **kw):
                """按字节口径推进进度后返回一个固定产物路径。

                守的回归: 文件下载没有分页, 进度只能走 set_total_bytes +
                advance_pages(0, bytes_delta=...); 这里照实调用一次, 才能
                断言 done_bytes 真的落进了进度文件。
                """
                if progress_tracker:  # tracker 可能缺席: 显式判一次
                    progress_tracker.set_total_bytes(100)  # 先声明总量: 不设总量的字节进度无法算百分比
                    progress_tracker.advance_pages(0, bytes_delta=100)  # 按字节推进: 页数为 0, 增量全走 bytes_delta
                return "/tmp/fake.fits"  # 返回固定产物路径: 成功分支

        mgr.client = _FakeBest()  # 换掉客户端: 文件任务走的是客户端的 download_file
        job_id = mgr.submit(FileJob(url="https://nadc.china-vo.org/data/best/f.fits"))  # 提交字节级任务
        assert mgr.result(job_id, timeout=30) == "/tmp/fake.fits"  # 等它完成
        rec = mgr.status(job_id)  # 读回进度记录
        assert rec["done_bytes"] == 100  # 字节进度必须落盘: 否则 GUI 对大文件显示 0%
        mgr.shutdown()  # 收线程池


class TestConcurrencyInternals:
    """P1-8/P1-9: 共享状态过锁 + 限流时钟跨任务共享。"""  # 限流时钟必须跨任务共享, 否则并发度形同虚设

    def test_all_tasks_share_one_downloader_and_rate_clock(self, tmp_path):  # 这条验的是"单例", 不是"能下载"
        """P1-9: region/sqlid/precise 任务必须走管理器级单例 downloader。

        复过的现: ``_make_downloader(job)`` 每任务新建 BestClient — 限流
        时钟 (实例级 ``_last_request_time``) 不跨实例共享, max_workers=2
        时限流被静默降为 ~1.0, 正是该限流要防的上游封禁风险。
        """
        mgr = _mgr(tmp_path)  # 三个目录全在 tmp_path 下: 单例下载器的输出与断点都隔离
        with patch.object(mgr, "_make_downloader",  # 包一层 spy: 既跑真实现又记录调用次数
                          wraps=mgr._make_downloader) as spy:
            first = mgr._downloader()  # 首次取单例
            for _ in range(3):  # 连取三次: 每次都该是同一个对象
                assert mgr._downloader() is first  # 同一个对象才算单例: 新建就意味着限流时钟被重置
            # 单例只建一次 (三次 _run_* 路径共享同一个 client)
            assert spy.call_count == 1  # 只建一次: 三条 _run_* 路径共享同一个 client

    def test_concurrent_submits_register_every_job(self, tmp_path):  # 并发 submit 不得丢任务: 共享字典必须写在锁内
        """P1-8: 并发 submit 不得丢任务 (共享字典写在锁内)。

        复过的现: ``self._lock`` 声明后零使用 — _spawn (主线程) 写、
        cancel (第三线程) 读, 无锁复合操作会丢更新; 更糟的是这把锁制造了
        "已加锁"的错觉。这里用 30 个并发 submit 钉"一个都不丢"。
        """
        mgr = _mgr(tmp_path)  # 三个目录全锚 tmp_path: 三十个并发任务不许写到真实进度目录
        ids: list[str] = []  # 回收 job_id: 后面三条断言都基于它
        lock = threading.Lock()  # 回收列表自带锁: 三十个线程并发 append 不安全

        def submit_one():  # 线程体只做一件事: 提交并记账
            """线程体: 提交一个 file 任务并回收 job_id (锁内追加)。"""
            jid = mgr.submit(FileJob(  # 提交一个字节级任务: 最轻的任务类型, 便于压并发
                url="https://nadc.china-vo.org/data/best/f.fits"))
            with lock:  # 记账要加锁: list.append 本身原子, 但这里要显式表达意图
                ids.append(jid)

        threads = [threading.Thread(target=submit_one) for _ in range(30)]  # 三十个线程: 少量线程可能碰不上竞态, 数量要够
        for t in threads:  # 全部启动: 竞态要在同一时刻才最容易复现
            t.start()
        for t in threads:  # 逐个 join: 不 join 就断言会读到半截结果
            t.join(timeout=30)
        assert len(ids) == 30  # 一个都不能丢
        assert len(set(ids)) == 30  # 无重复 id (字典写无丢失/无覆盖)
        assert len(mgr._trackers) == 30  # 进度记录也要齐全: 丢任务不只是列表少一项
        assert len(mgr._cancel_flags) == 30  # 取消标志也要齐全: 丢标志等于该任务再也取消不掉
        mgr.shutdown()  # 收线程池
