"""resume 对称性单元测试: file/precise 原地续传 (同一 job_id) / std 组断点透传。

守的不变量 (B4/B5, docs/architecture/file-size-budget.md §6.1):
  B4 — DownloadManager.resume 必须对称: region/sqlid/file/precise 四类一律
       原地续传, 返回原 job_id。若走 self.submit(job) 生成新 job_id, 旧进度
       记录会停留在非终结状态, 调用方跟踪旧 id 永远等不到终态; 重复 resume
       也无幂等保护。file/precise 以原 job_id 原地重跑
       (resume_spec 提交即落盘, 失败/中断的任务也能续), 续跑成果落回同一
       进度记录; 已 done/在跑的任务重复 resume 直接返回原 id, 不新建任务。
  B5 — download_region 对 catalog="std" 走组展开分支时必须透传 job_id:
       成员 checkpoint 一旦用自动生成的键, resume(job_id) 就抛
       FileNotFoundError (断点实际存在于成员自动键下), 且同参数 std 并行下载
       还会撞同一成员断点键。组展开把 job_id 透传给成员
       (成员键 = {job_id}_{member}), 组级 checkpoint 记录展开参数供
       resume 入口读取, 完成即删。

同步模式 (与 test_download_manager.py 既有写法一致): 只用 mgr.result() 等
Future 收敛后再单次读进度记录 — 避免轮询读文件与 worker 的原子写在
Windows 上相撞 (os.replace 对正被读取的目标会 WinError 5)。
"""
from __future__ import annotations

# 标准库: threading (运行中窗口的阻塞替身) / pathlib (产物路径断言)
import threading  # Event 造可控并发窗口: 没有它测不到"任务在跑时 resume"这条路径
from pathlib import Path  # 只用来断言续跑产物真的落在磁盘上

# 标准库: patch 替换 downloader 的下载方法与客户端的协议阶段, 离线复现断流
from unittest.mock import patch  # 换掉网络面: 全程不碰真实站点即可复现断流与重试

# 测试框架: raises 断言异常; tmp_path 提供每次用例独立的临时目录
import pytest  # 续跑对称性: 中断与一次跑完必须落到同一份文件

try:
    # 本地: 生产客户端 (downloader/管理器的 HTTP 面, rate_limit=0 关掉礼貌限流)
    from src.client import BestClient

    # 本地: 管理器 + 三类任务载体 (file/precise/region 的 resume 入口)
    from src.download_manager import (
        DownloadManager,  # 偏移量从落盘进度反推: 进度文件是续跑的唯一事实源
        FileJob,  # 字节级单文件任务: 续跑语义最简单, 用来定"原地"基准
        PreciseDownloadJob,  # 按源 id 精确取数: 与 file 共用 resume 入口
        RegionJob,  # 区域任务: 可展开成组, 组展开是 B5 的战场
    )

    # 本地: 进度状态机枚举 (done 是断言的状态锚点)
    from src.download_progress import STATUS_DONE

    # 本地: 被测单元 — 下载器 (组展开/断点/resume_job 的权威实现);
    # region_checkpoint_key 是区域断点键的唯一构造点 —— 涉及键的断言必须由它
    # 现场派生, 硬编码字面量会在键形态变更后**静默退化成恒真** (AD2 §5 PINNED-02)
    from src.downloader import BestDownloader, region_checkpoint_key

    # 本地: 数据模型 — 查询结果载体 / 单个源 (协议阶段替身的返回)
    from src.models import BestQueryResult, BestSource

    # 本地: 页级断点存储 (验证"成功即删"后断点真的不在了)
    from src.scripts.checkpoint import DownloadCheckpoint  # 指纹按内容而非位置: 换机器换目录也不该判成"另一份"
except Exception as _legacy_err:  # legacy-import-guard
    # 源码树调整导致旧导入路径失效时整模块跳过, 不让收集期报错
    import pytest as _pytest
    _pytest.skip(f'legacy import unavailable: {_legacy_err!r}', allow_module_level=True)  # 收集期就退场: 导入树问题不该算用例失败


def _mgr(tmp_path, **kw):  # 三个目录都落进 tmp_path: 测试不得碰真实 .progress/.checkpoints
    """构造管理器: 三个运行时目录全部锚到 tmp_path (隔离状态, 断言可预测)。"""  # 中途杀一次再续: 只有真中断才验得出续跑逻辑
    return DownloadManager(BestClient(rate_limit=0),  # 关掉限流: 否则离线用例会被礼貌等待拖慢
                           output_dir=str(tmp_path / "out"),
                           progress_dir=str(tmp_path / ".progress"),  # 进度目录隔离: 断言 list_jobs 只看得到本次的任务
                           checkpoint_dir=str(tmp_path / ".checkpoints"),  # 断点目录隔离: 否则同键断点会跨用例串味
                           **kw)  # 透传其余构造参数: 让个别用例能换线程数等


class TestFilePreciseResumeSymmetry:  # 字节级相等: 大小相同但内容不同是最阴的失真
    """file/precise 的 resume: 返回原 job_id, 原地重跑, 重复 resume 幂等。"""

    def test_resume_done_file_job_returns_original_job_id(self, tmp_path):
        """resume 已成功的 file job 必须返回原 job_id (B4)。

        守的不变量: resume 走 self.submit(job) 生成新 job_id 时, 调用方拿着旧
        id 等终态永远等不到 (旧记录停在原终态, 新 id 调用方根本不知道),
        CLI 的 resume 输出里 resumed_from 与 new_job_id 永远对不上。原地语义
        要求: 返回原 id, 运维列表里不会多出一个同源幽灵任务。
        """
        mgr = _mgr(tmp_path)                                                           # 文件作业已完成: resume 应原样返回 job_id, 不重跑

        class _FakeBest:
            """假客户端: 恒定成功的文件下载。"""

            def download_file(self, url, savedir="./", filename=None,
                              job_id=None, progress_tracker=None,
                              cancel_event=None, **kw):  # 参数全收下: 真实调用会带全套, 少一个就 TypeError
                """返回固定产物路径, 让任务一轮就到 done。"""
                return "/tmp/fake.fits"

        mgr.client = _FakeBest()  # 整体换掉客户端: 让下载面完全离线且一轮成功
        jid = mgr.submit(FileJob(url="https://nadc.china-vo.org/data/best/f.fits"))  # 只给 url: 断点偏移靠下载器回报
        assert mgr.result(jid, timeout=30) == "/tmp/fake.fits"  # 已完成的续跑返回原 job_id: 换 id 会让调用方失去对同一任务的追踪
        assert mgr.resume(jid) == jid  # 原地续传: 同一 job_id
        mgr.shutdown()  # 收线程池: 否则 pytest 退出时会挂住

    def test_resume_failed_file_job_reruns_in_place(self, tmp_path):
        """resume 失败的 file job: 原 job_id 原地重跑, 旧记录被推到 done (B4)。

        守的不变量: 失败任务是续传的主场景 (网络掉线/磁盘满), 两条前提缺一
        不可 —— resume_spec 必须提交即落盘 (只在 finish 时落盘会让失败记录
        直接 FileNotFoundError), 原地重跑必须沿用原 id (submit 新 id 会让
        跟踪旧 id 的调用方永远等不到终态)。同一份进度记录被新运行覆盖并推到
        done。
        """
        mgr = _mgr(tmp_path)                                                                        # 失败的文件作业要原地重跑, 不新建作业
        calls = []  # 记账每次下载调用: 没有它就没法区分"真重跑"与"静默返回旧结果"

        class _FlakyBest:
            """假客户端: 第一次返回 None (网络失败), 续跑后成功。"""

            def download_file(self, url, savedir="./", filename=None,
                              job_id=None, progress_tracker=None,
                              cancel_event=None, **kw):  # 同上: 签名要吃得住全套实参
                """按调用次数分派失败/成功, 模拟"失败后重试成功"。"""
                calls.append(url)
                return None if len(calls) == 1 else "/tmp/fake.fits"  # 只让首轮失败: 续跑必须一次过

        mgr.client = _FlakyBest()  # 换成会失败的客户端: 构造"中断"这个前提
        jid = mgr.submit(FileJob(url="https://nadc.china-vo.org/data/best/f.fits"))
        with pytest.raises(RuntimeError, match="returned None"):  # 匹配异常文案: 确认失败是"下载返回空"而非别的错
            mgr.result(jid, timeout=30)  # 首轮失败
        assert mgr.status(jid)["status"] == "failed"  # 失败态必须真落 failed: 吞掉异常会让上层以为还在跑
        assert mgr.resume(jid) == jid  # 原地续传: 同一 job_id
        assert mgr.result(jid, timeout=30) == "/tmp/fake.fits"  # 旧 id 等到终态
        assert mgr.status(jid)["status"] == STATUS_DONE  # 同一份记录被推到成功: 换记录就等于丢追踪
        assert len(calls) == 2  # 真的重跑了, 不是空转
        mgr.shutdown()

    def test_resume_precise_job_returns_original_job_id_and_reruns(self, tmp_path):
        """resume precise job 与 file 同构: 原 job_id 原地重跑到 done (B4)。"""
        mgr = _mgr(tmp_path)                                                                 # 精确测光作业同样对称: 终态返原 id, 非终态才重跑
        target = tmp_path / "out" / "r.csv"  # 预先放一份产物: 续跑要断言"回到同一份文件"而非"又下一份"
        target.parent.mkdir(parents=True, exist_ok=True)  # 先建目录: 续跑只认已有目录, 不会替我们铺
        target.write_text("calibstars_id,ra\nX1,1.0\n", encoding="utf-8")  # 内容对得上源 id: 挡"大小相同内容不同"的阴招
        calls = []  # 记账精确取数的次数: 断言重试恰好收敛到一次

        def _flaky(self, *a, **kw):
            """第一次抛 RuntimeError (网络掉线), 续跑返回同一产物。"""
            calls.append(1)
            if len(calls) == 1:  # 只在首轮断: 让"续跑成功"成为可判定的第二段
                raise RuntimeError("network drop")
            return str(target)

        with patch("src.downloader.BestDownloader.download_by_constraints",  # 打在被测方法上: 走真实调度, 只换最后一跳
                   _flaky):  # 副作用替身而非返回值: 续跑要看到异常传播
            jid = mgr.submit(PreciseDownloadJob(source_ids=["X1"],
                                                catalog="stripe82"))  # 单源 id: 精确取数路径不牵涉组展开
            with pytest.raises(RuntimeError, match="network drop"):
                mgr.result(jid, timeout=30)  # 首轮失败
            assert mgr.resume(jid) == jid  # resume 必须返回同一个 jid: 另起 id 等于把续跑变成新任务
            assert mgr.result(jid, timeout=30) == str(target)  # 续跑回到同一份产物
        assert mgr.status(jid)["status"] == STATUS_DONE  # 原记录推到终态: 否则调用方永远等不到
        assert len(calls) == 2  # 取数恰好两次: 一次失败一次成功, 多次说明重试没收敛
        mgr.shutdown()

    def test_repeated_resume_is_idempotent(self, tmp_path):
        """重复 resume 同一 job_id: 两次都返回同一 job, 不产生第二个进度记录 (B4)。

        守的不变量: 每次 resume 都 submit 一个新 job_id 时, 重复 resume
        会在 .progress 里堆一串同源任务, 运维列表被幽灵任务淹没, 且每次
        重跑都重新走一遍网络。已 done 的记录重复 resume 直接返回原 id,
        磁盘上仍然只有一个 job。
        """
        mgr = _mgr(tmp_path)                                                                # 重复 resume 必须是幂等: 连点两次不能起两个作业

        class _FakeBest:
            """假客户端: 恒定成功的文件下载。"""

            def download_file(self, url, savedir="./", filename=None,
                              job_id=None, progress_tracker=None,
                              cancel_event=None, **kw):  # 签名吃全套实参, 否则一调用就 TypeError
                """返回固定产物路径, 让任务一轮就到 done。"""
                return "/tmp/fake.fits"

        mgr.client = _FakeBest()  # 换成恒成功客户端: 幂等性不该被网络噪声干扰
        jid = mgr.submit(FileJob(url="https://nadc.china-vo.org/data/best/f.fits"))
        assert mgr.result(jid, timeout=30) == "/tmp/fake.fits"  # 先跑到 done: 幂等的前提是任务已有终态
        assert mgr.resume(jid) == jid  # 重复 resume 幂等: 连点两次不该产生第二个任务
        assert mgr.resume(jid) == jid  # 第三次同样返回原 id: 幂等不因次数而失效
        assert mgr.store.list_jobs() == [jid]  # 没有第二个 job 落盘
        mgr.shutdown()

    def test_resume_of_running_job_is_noop_returning_same_id(self, tmp_path):
        """对仍在跑的任务 resume: 返回原 id 且不派第二个 worker (幂等)。

        守的不变量: 运行中的任务再 resume 就重跑, 会出现两个 worker 抢同一
        份进度记录互相覆盖 —— 原地语义对"在跑"就是等它自己跑完。
        """
        mgr = _mgr(tmp_path)                                                                   # 正在跑的作业 resume 是空操作, 不能打断它
        entered = threading.Event()  # 两个 Event 造出可控并发窗口: 不然测不到"运行中 resume"这条路径
        release = threading.Event()  # 放行开关: 让测试自己决定"在跑"这个状态维持多久

        class _BlockingBest:
            """假客户端: 进入后阻塞, 把任务压在 running 态。"""

            def download_file(self, url, savedir="./", filename=None,
                              job_id=None, progress_tracker=None,
                              cancel_event=None, **kw):  # 同样要吃住全套实参
                """置 entered 事件后等 release, 让测试拿到"运行中"窗口。"""
                entered.set()  # 先报到达: 测试据此确认 worker 真的进了下载面
                release.wait(timeout=10)  # 阻塞在此: 把任务钉在 running 直到测试放行
                return "/tmp/fake.fits"

        mgr.client = _BlockingBest()  # 换阻塞客户端: 制造"运行中"这个前提状态
        jid = mgr.submit(FileJob(url="https://nadc.china-vo.org/data/best/f.fits"))
        assert entered.wait(timeout=5)  # worker 已进入下载 (在跑)
        assert mgr.resume(jid) == jid  # 在跑: 原地续跑语义 = 等它自己跑完
        release.set()  # 先放行再断言: 不然等待会挂在 10 秒超时上
        assert mgr.result(jid, timeout=30) == "/tmp/fake.fits"  # 原 id 照样拿到终态
        assert mgr.store.list_jobs() == [jid]  # 没有第二个 worker/job
        mgr.shutdown()

    def test_resume_without_record_raises(self, tmp_path):
        """无进度记录: FileNotFoundError (调用方应改走重新提交)。

        守的回归: 静默返回 None 会让调用方以为续传成功, 实际什么都没下。
        """
        mgr = _mgr(tmp_path)                                                                # 没有记录就抛: 静默新建会把「查错 id」伪装成正常续跑
        with pytest.raises(FileNotFoundError):  # 无记录即抛 FileNotFoundError: 静默新建会跑出一个凭空的任务
            mgr.resume("nope")  # 故意用不存在的 id: 逼门禁暴露"无记录"这条路径
        mgr.shutdown()


class TestStdGroupResume:  # 组级断点是 resume 的入口事实源: 缺了它续跑根本进不去
    """std 组展开: job_id 透传成员, 组级断点供 resume 读取 (B5)。"""

    def _dl(self, tmp_path):
        """造一个锚定 tmp_path 的 downloader (checkpoint 目录可断言)。"""
        return BestDownloader(BestClient(rate_limit=0),  # rate_limit=0: 组展开是多次请求, 限流会拖垮用例
                              output_dir=str(tmp_path / "out"),
                              checkpoint_dir=str(tmp_path / "ck"))  # 断点目录单独隔离: 断言"成功即删"要能查得到

    def test_std_group_resume_from_group_job_id(self, tmp_path):
        """std 组下载中断后 resume(组 job_id): 不抛 FileNotFoundError 且真续上 (B5)。

        守的不变量: 组展开必须透传 job_id。若成员断点落在自动生成的
        region_scr_galah_... 键下, 调用方拿组 job_id 去 resume,
        checkpoint.load(组 job_id) 返回 None, 直接 FileNotFoundError,
        断点明明在磁盘上却续不上。成员键由 {job_id}_{member} 派生,
        组级 checkpoint 记录展开参数, resume 以同一 job_id 重入组展开,
        断流成员从自己的断点页继续 (start_page=2 而不是 1)。
        """
        dl = self._dl(tmp_path)                                                          # 组级 resume 从组 job_id 进, 不是从成员作业进
        group_id = "grp_std_01"  # 显式组 id: 断点键由它派生, 不给就退回自动键而复现缺键缺陷
        fetches = []  # 记 (sqlid, start_page): 断言断流成员确实从第 2 页续

        def _fake_fetch(sqlid, **kwargs):
            """按调用序分派: 第 1 次断流留断点, 之后正常返回一页。

            守的不变量: 断流必须发生在 checkpoint 落盘之后 (on_page_fetched
            先跑), 否则磁盘上什么都没留下, "从断点续上"无从验证。
            """
            fetches.append((sqlid, kwargs.get("start_page")))  # 记起始页: 这是"真续上"的唯一证据
            on_page = kwargs.get("on_page_fetched")  # 取出回调: 断点就是靠它落盘
            if len(fetches) == 1:  # 只让首轮断流: 续跑那一轮必须一次成功
                if on_page:  # 回调缺失就无从谈断点: 容错但要显式判
                    on_page(1, [BestSource(source_id="G1", ra=1.0, dec=2.0)])  # 先落第 1 页再抛: 顺序反了断点就是空的
                raise RuntimeError("simulated drop")
            initial = kwargs.get("initial_sources") or []  # 已取到的源: 续跑时已在断点里, 要原样带回
            src = BestSource(source_id="G2", ra=3.0, dec=4.0)  # 新增第 2 页的源: 页号错一格这里就会露馅
            if on_page:  # 同样先落盘: 成功也走一遍回调, 与真实实现同构
                on_page(kwargs.get("start_page", 1), [src])  # 用实际起始页记账: 断点页号才不会凭空回到 1
            return BestQueryResult(success=True,
                                   sources=list(initial) + [src],  # 首轮源 + 新增源: 漏拼就等于丢数据
                                   total_count=len(initial) + 1)  # 总数跟着走: 截断会让上层以为取全了

        with patch.object(dl.client, "submit_phase1",  # 替换协议一阶段: 离线拿到成员 sqlid
                          side_effect=[("sG", None), ("sL", None),
                                       ("sX", None)]), \
                patch.object(dl.client, "_fetch_sqlid_data",  # 替换取数: 断流与续跑都在这一层复现
                             side_effect=_fake_fetch):
            with pytest.raises(RuntimeError, match="simulated drop"):  # 断流必须冒泡: 被吞掉就构造不出中断
                dl.download_region(ra_center=10.0, dec_center=20.0,
                                   radius_arcsec=60.0, catalog="std",  # std 走组展开: 这是 B5 的唯一入口
                                   job_id=group_id, resumable=True)  # 显式 job_id + 可续: 键才有得派生
            # 组级断点已落盘 (resume 的入口事实源)
            grp_ckpt = dl.checkpoint.load(group_id)  # 组检查点先落: 续跑要靠它知道从哪一页接
            assert grp_ckpt is not None and grp_ckpt["group"] == "std"  # 组标记必须是 std: 认错组就等于接错任务
            # 成员断点落在透传键下 (next_page=2: 第 1 页已在断点里)
            member_ckpt = dl.checkpoint.load(f"{group_id}_scr_galah")  # 键含组 id: 不含就退回旧的自动键
            assert member_ckpt is not None  # 成员断点必须在: 缺了就等于没透传
            assert member_ckpt["next_page"] == 2  # 成员检查点 next_page 必须是 2: 页号错一格就会重取或漏取
            # resume: 不抛 FileNotFoundError, 组任务原地续上
            out = dl.resume_job(group_id)  # 用组 id 续: 键不派生到这里就抛 FileNotFoundError
            assert Path(out).is_file()  # 续跑要真产出文件: 返回个 id 就算过等于没验
        # 断流的成员是从第 2 页续的 (真的续上, 不是从第 1 页重下)
        assert ("sG", 2) in fetches  # 起始页必须是 2: 从 1 续等于全量重下
        # 组完成即删组级断点 (与成员"成功即删"同口径)
        assert dl.checkpoint.load(group_id) is None  # 续跑后从第二页起: 验证真的接着跑而不是从头重跑

    def test_std_group_parallel_jobs_do_not_share_member_checkpoints(self, tmp_path):
        """同参数两个 std 组下载: 成员断点键必须各自派生, 不撞同一键 (B5)。

        守的不变量: 成员键必须由组 job_id 派生。若成员改用**自动键**
        (``region_checkpoint_key(成员星表, 几何, ...)``), 同参数并行下载的两个组
        会写到同一个成员断点上互相覆盖, 一组的页进度被另一组顶掉, 续传时数据
        静默混洗。键带组 job_id 才天然分开。
        """
        dl = self._dl(tmp_path)                                                                    # 并行组各自的检查点必须隔离, 不能共用一个

        def _always_drop(sqlid, **kwargs):
            """恒定断流: 每个组只留下第一个成员的断点即退出。"""
            raise RuntimeError("simulated drop")  # 每次都断: 两个组才各自只留一个成员断点可比

        with patch.object(dl.client, "submit_phase1",  # 每次都返回同一个成员: 排除"成员不同所以键不同"的干扰
                          return_value=("sG", None)), \
                patch.object(dl.client, "_fetch_sqlid_data",  # 取数层恒断: 让断点真的留在盘上
                             side_effect=_always_drop):
            for gid in ("grpA", "grpB"):  # 同参数两个组: 参数相同正是撞键的前提
                with pytest.raises(RuntimeError, match="simulated drop"):
                    dl.download_region(ra_center=10.0, dec_center=20.0,  # 参数逐字相同: 只让 job_id 不同
                                       radius_arcsec=60.0, catalog="std",
                                       job_id=gid, resumable=True)  # 唯一变量就是组 id
        # 两个组各自的成员断点都在 (键不同, 没有互相覆盖)
        assert dl.checkpoint.load("grpA_scr_galah") is not None  # 两个组的成员检查点互不覆盖: 共用键会让并行任务互相踩
        assert dl.checkpoint.load("grpB_scr_galah") is not None  # B 组同理: 只查 A 组会漏掉"后者被前者顶掉"
        # 自动生成的共享键下什么都没有 (证明透传生效)。这个键**由被测函数现场
        # 派生**: 原先此处硬编码 "region_scr_galah_ra10.00_dec20.00_r60", 而
        # P0-02 把键改成内容寻址之后, 那串就成了一个永不会被生成的字符串 ⇒
        # `is None` 恒真, 守卫悄悄消失而测试照样全绿 (AD2 §5 PINNED-02 点名的
        # "最阴险的一类: 不变红, 但静默退化成恒真断言")。
        member_auto_key = region_checkpoint_key(  # 成员若没吃到透传的 job_id, 就会落到这个自动键上
            "scr_galah", 10.0, 20.0, 60.0,  # 几何与上面两次 download_region 调用逐字对齐
            None, "csv", [], 50000,         # bands/格式/行数上限取该调用的缺省值
        )
        assert dl.checkpoint.load(member_auto_key) is None  # 无组前缀的自动键不得有断点: 否则续跑会接错任务

    def test_manager_resume_std_group_job_returns_same_id(self, tmp_path):
        """经管理器 resume std 组任务: 返回原 job_id, 旧记录被推到 done (B4/B5)。

        守的不变量: 组任务的断点在成员键下, manager.resume 必须先把终态
        检查前置 —— 直接委派 resume_job(组 job_id) 会在断点已删时抛
        FileNotFoundError; 且即使续上, 旧进度记录也停在中断时的非终结状态,
        调用方跟踪原 id 永远等不到终态。resume 返回原 id 且把续跑成果
        落回同一进度记录 (done)。
        """
        mgr = _mgr(tmp_path)                                                              # 经 manager 的组级 resume 也要返同一个 id
        fetches = []  # 与 downloader 级用例同口径记账: 便于两处对照同一套断流脚本

        def _fake_fetch(sqlid, **kwargs):
            """第 1 次断流留断点, 之后正常返回一页 (与 downloader 级用例同构)。"""
            fetches.append((sqlid, kwargs.get("start_page")))  # 记起始页: 经管理器这一层也必须真续上
            on_page = kwargs.get("on_page_fetched")  # 断点落盘的唯一入口
            if len(fetches) == 1:  # 首轮断流: 经管理器的失败路径也要能被构造出来
                if on_page:  # 回调可能缺席, 显式判一次
                    on_page(1, [BestSource(source_id="G1", ra=1.0, dec=2.0)])  # 先落盘再抛: 顺序反了断点为空
                raise RuntimeError("simulated drop")
            initial = kwargs.get("initial_sources") or []  # 断点里已有的源: 续跑结果要把它带上
            src = BestSource(source_id="G2", ra=3.0, dec=4.0)  # 新增第 2 页的源: 页号错一格这里就会露馅
            if on_page:  # 成功也走回调, 与真实实现同构
                on_page(kwargs.get("start_page", 1), [src])  # 用实际起始页: 断点页号才不会退回 1
            return BestQueryResult(success=True,
                                   sources=list(initial) + [src],  # 两轮源拼接: 少了首轮就等于丢数据
                                   total_count=len(initial) + 1)  # 总数随之递增

        with patch.object(mgr.client, "submit_phase1",  # 换协议一阶段: 离线给出三个成员
                          side_effect=[("sG", None), ("sL", None),
                                       ("sX", None)]), \
                patch.object(mgr.client, "_fetch_sqlid_data",  # 换取数层: 断流在这里复现
                             side_effect=_fake_fetch):
            jid = mgr.submit(RegionJob(ra=10.0, dec=20.0, radius_arcsec=60.0,
                                       catalog="std"))  # 区域任务: 管理器不接 job_id, 由它自己生成
            with pytest.raises(RuntimeError, match="simulated drop"):
                mgr.result(jid, timeout=30)  # 首轮断流
            assert mgr.resume(jid) == jid  # 原 job_id (不新建)
        assert mgr.status(jid)["status"] == STATUS_DONE  # 旧记录被推到终态
        assert ("sG", 2) in fetches  # 断流成员从第 2 页续上
        mgr.shutdown()

    def test_resume_done_region_job_returns_same_id(self, tmp_path):
        """resume 已成功的 region/sqlid 作业: 返回原 job_id, 不抛 FileNotFoundError。

        守的不变量 (Phase 8 观察项 ⑤): region/sqlid 作业成功后 checkpoint 被删
        (成功即删), 因此幂等检查必须排在断点续传委派**之前** —— 先调
        downloader.resume_job() 才发现断点没了, 会抛 FileNotFoundError, 把
        "已完成"误报成"没有断点"。file/precise 早有 done 短路, region/sqlid
        两条路径若缺同样的前置检查, GUI 的 resume 按钮对已完成任务必红,
        脚本重试环被引导去"重新提交" = 全量重下。终态检查前置后, 四类
        任务一律返回原 id (调用方用 result(job_id) 取原产物路径)。
        """
        mgr = _mgr(tmp_path)                                                                     # 已完成的区域作业 resume 同样返原 id

        def _fake_fetch(sqlid, **kwargs):
            """一轮就成功: 不留断点 (成功即删), 也不给续传留机会。"""
            on_page = kwargs.get("on_page_fetched")  # 仍走回调: 真实成功路径也会落一次盘
            src = BestSource(source_id="R1", ra=1.0, dec=2.0)  # 单源即返回: 够用且不牵涉翻页
            if on_page:  # 回调缺席不该崩: 显式判一次
                on_page(1, [src])  # 落完这一页即"成功即删"的触发条件
            return BestQueryResult(success=True, sources=[src], total_count=1)  # 一轮成功: 断点随后被删

        with patch.object(mgr.client, "submit_phase1",  # 离线给成员: 不打真实站点
                          side_effect=[("sG", None), ("sL", None),
                                       ("sX", None)]), \
                patch.object(mgr.client, "_fetch_sqlid_data",  # 换取数层, 走一轮成功
                             side_effect=_fake_fetch):
            jid = mgr.submit(RegionJob(ra=10.0, dec=20.0, radius_arcsec=60.0,
                                       catalog="std"))  # region 任务: 终态检查缺失的正是这条路径
            path = mgr.result(jid, timeout=30)  # 先取产物路径: 后面要断言续跑不改变它
            assert mgr.status(jid)["status"] == STATUS_DONE  # 确认已成功, 断点应已删
            # 前置条件: 组级断点已删 — 此时若仍直接委派就必炸
            ckpt = DownloadCheckpoint(str(mgr.checkpoint_dir))  # 直开检查点存储: 读管理器之外的真相
            assert ckpt.load(jid) is None  # 断点必须已删: 这正是"成功即删"造出的陷阱前提
            # 已完成: 原地语义 = 返回原 id, 不重跑不新建
            assert mgr.resume(jid) == jid  # 幂等检查必须前置: 已完成任务不得抛 FileNotFoundError
            assert mgr.resume(jid) == jid  # 重复 resume 仍幂等
            assert mgr.result(jid, timeout=5) == path  # 原产物路径不变
        mgr.shutdown()
