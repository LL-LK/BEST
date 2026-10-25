"""续传期逐页观察者接线 (K2-01) + resume 阻塞契约 (K2-02) + 认证超时口径 (K2-03)。

守的不变量 (全部来自 J6 真实并发负载实测, 见 temp/VERIFY-J6-concurrency.md):
  K2-01  — region/sqlid 的 ``resume_job`` 必须把 ``on_page_observer`` 转发进
    ``download_sqlid``。进度累加 (``tracker.advance_pages``) 与取消检查
    (``_check_cancelled``) **都只住在这一个回调里**: 缺它时续传照样跑完并
    落 done, 但进度冻结、取消静默失效 —— J6 实测"续传取回 page=3 后
    done_pages 仍停在 1", 且续传中 cancel() 对两个 job 都返回 False。
    同仓 ``downloader.download_region`` 的续传分支早就在注释里警告过这件事,
    而 ``resume_job`` 正是没转发的那一个 (注释说对了, 代码没做)。
  K2-01b — 续传必须**换新取消标志**: 沿用上次被置位的那个, 重跑会在第一个
    页边界立刻自我取消 (与 ``_spawn`` 同一理由, 不换标志就等于把 observer
    接上之后反而把续传打死)。
  K2-02  — region/sqlid 的 ``DownloadManager.resume()`` 是**同步内联**调用
    (与 file/precise 的异步语义刻意不对称), 返回即终态。这里把该契约钉住:
    日后有人按"submit 都是异步"的直觉改它, 就会把"返回即终态"这条既有
    承诺 (以及 CLI/GUI 的调用时序) 一起改掉。
  K2-03  — ``BestAuth`` 的两个请求点 (登录页 GET / 登录 POST) 必须取实例
    ``request_timeout``: 此前本类不收 timeout, 两个请求点恒用协议层 120s,
    调用方把查询超时调快也管不到认证路径。

本文件不打桩分页引擎: 桩只落在 ``session.get`` (真实 build_page_url / 偏移
切片 / CSV 解析 / 页级断点 / 续传参数复原全在被测链内), 全程零真实网络请求。
"""
from __future__ import annotations

# 标准库: threading Event (造可控的"正在跑"窗口, 钉住 submit 的异步语义)
import threading  # 没有它就测不到"submit 已返回但任务还在跑"这个窗口

# 标准库: patch 替换 session 层 (换掉网络面: 首轮断流与续传窗口都在这里造)
from unittest.mock import patch  # 只换最后一跳: 分页引擎与断点状态机照跑

# 标准库: urllib.parse 拆查询串 (从分页 URL 取回 rows/page, 断的是"续传步长复原")
from urllib.parse import parse_qs, urlparse  # 标准库 URL 拆解, 不手写字符串切

# 测试框架: raises 断言首轮失败冒泡; tmp_path 提供每次用例独立的临时目录
import pytest  # 首轮断流必须冒泡, 否则构造不出续传现场

# 本地: 认证层 (K2-03: 登录两个请求点的超时取值口)
from src.auth.session import BestAuth

# 本地: 生产客户端 (rate_limit=0 关掉礼貌限流, 桩在 session 层故不发真请求)
from src.client import BestClient

# 本地: 被测单元 — 管理器 (resume/cancel 的编排) 与任务载体 (sqlid 走页级断点)
from src.download_manager import (
    DownloadManager,  # resume/cancel 的权威实现: 同步内联续传就在这一侧
    FileJob,  # 反例样本: file 的 resume 走 _spawn, 是异步那一侧
    SqlidJob,  # 正例样本: sqlid 走页级断点, 是同步那一侧
)

# 本地: 进度状态机枚举 (断言终态用, 不写字面量免得枚举改名后集体红)
from src.download_progress import (
    STATUS_CANCELLED,  # 续传期取消的终态: 与 failed/done 严格区分
    STATUS_DONE,  # 续传成功的终态
    STATUS_FAILED,  # 续传失败后必须收口到的终态: 停在 running 就再也续不回来
    STATUS_RUNNING,  # 续传进行中的非终态: cancel() 必须认它 (不认就返回 False)
)

# 本地: 协议层常量 (缺省超时口径: 断言"未配置时行为不变"要拿它当基准)
from src.protocol import REQUEST_TIMEOUT

TOTAL = 1000  # 会话总行数: 取 PAGE_SIZE 整数倍, 便于逐页断言页号
PAGE_SIZE = 250  # 首跑步长: 故意小于缺省 1000, 断点必须把它原样带走
SQLID = "s4242"  # 已有会话号: sqlid 任务跳过 phase-1, 全程只发 GET
CSV_HEADER = "ps1_source_id,ps1_ra,ps1_dec,ps1_rpsf,ps1_snr\n"  # ps1 真实投影: 解析层按 catalog 剥前缀


class _Resp:  # 最小回包: 分页引擎只用到 .text 与 raise_for_status()
    """仿真 HTTP 回包 (只实现被测链真正调用的两个成员)。"""

    def __init__(self, text: str, url: str = "") -> None:
        """存正文与最终 URL: getcount 看正文, 登录判定看 URL。"""
        self.text = text  # 回包正文: getcount 是 {"total": N}, phase-2 是 CSV
        self.url = url  # 最终 URL: login() 靠它判"是否还停在登录页"

    def raise_for_status(self) -> None:
        """恒成功: 本文件不测 HTTP 状态码, 故障一律用"抛异常"表达。"""
        return  # 200 即无动作


class _FakeSite:
    """按实测偏移语义供数的假站点 (可杀点 / 可在页响应到手前挂探针)。

    守的回归: 桩必须按 ``(page-1)*rows`` 切偏移而不是按页号线性切 —— 否则
    "续传起点 == 断点 next_page" 这条断言就分不清真续上与全量重下。
    """

    def __init__(self, kill_on_call: int | None = None, on_fetch=None) -> None:
        """构造站点。

        Args:
            kill_on_call: 第几次 phase-2 请求时抛错 (模拟进程被杀, 造断点现场)。
            on_fetch: 可选探针 ``(page, call) -> None``, 在页响应到手**之前**调用
                (取消指令要趁 observer 还没跑时发出去, 才测得到页边界取消)。
        """
        self.kill_on_call = kill_on_call  # 杀点: 断点现场由此造出
        self.on_fetch = on_fetch  # 探针: 续传窗口里的动作 (发 cancel) 靠它注入
        self.phase2_calls = 0  # phase-2 计数: 杀点按调用序判定, 不按页号
        self.pages: list[tuple[int, int]] = []  # 记账 (page, rows): 断言续传步长要用

    def get(self, url: str, **kwargs) -> _Resp:
        """按 URL 分派: getcount 回总数, 分页 URL 回按偏移切出的那一页。"""
        if "getcount" in url:  # 计数端点: 少了它 total_count 只能报诚实但无用的本地行数
            return _Resp('{"total": %d}' % TOTAL)  # 总数照实报: 截断判定与空结果闸都靠它
        params = parse_qs(urlparse(url).query)  # 协议键是 rows/page (protocol.build_page_url)
        page = int(params["page"][0])  # 页码: 偏移 = (page-1) * rows
        rows = int(params["rows"][0])  # 步长: 与 page 成对才解释得通
        self.pages.append((page, rows))  # 记账: 这一趟实际发了什么, 事后可逐条核
        self.phase2_calls += 1
        if self.kill_on_call == self.phase2_calls:
            # 抛非 requests 异常: 分页引擎只把网络错降级为"已取部分", 其它异常
            # 直接冒泡, 断点因此留在磁盘上 (这才是"进程被杀"的现场)
            raise RuntimeError("simulated kill on phase-2 request %d" % self.phase2_calls)
        if self.on_fetch is not None:
            self.on_fetch(page, self.phase2_calls)  # 探针先动手: 取消必须赶在 observer 之前
        start = (page - 1) * rows  # 偏移起点: 实测 page=2&rows=100 == page=1&rows=1000 的 [100:200]
        body = "".join(  # 逐行造本页数据: 行序即服务端行序, 偏移才有意义
            "SRC_%05d,%.4f,30.0000,18.20,25.0\n" % (i, 180.0 + i / 1000.0)
            for i in range(start, min(start + rows, TOTAL))
        )
        return _Resp(CSV_HEADER + body)  # 带表头: 解析层据此判定 has_header 并剥前缀


def _mgr(tmp_path) -> DownloadManager:
    """造管理器: 三个运行时目录全部锚到 tmp_path (测试不得碰真实 .progress/.ckpt)。"""
    return DownloadManager(BestClient(rate_limit=0),  # rate_limit=0: 桩在 session 层, 但仍不该让用例等礼貌 sleep
                           output_dir=str(tmp_path / "out"),
                           progress_dir=str(tmp_path / ".progress"),  # 进度目录隔离: 断言 list_jobs 只看得到本次任务
                           checkpoint_dir=str(tmp_path / ".checkpoints"))  # 断点目录隔离: 同键断点会跨用例串味


def _interrupt(mgr: DownloadManager, job_id: str, site: _FakeSite) -> None:
    """首轮取满 1 页后被杀, 造出"有断点 + 记录 failed"的续传现场。

    Args:
        mgr: 被驱动的管理器 (submit 与 result 都在它上面)。
        job_id: 待中断的作业标识 (由本函数内的 submit 产生后回传)。
        site: 带杀点的假站点 (第 2 次 phase-2 请求抛错)。
    """
    with patch.object(mgr.client.session, "get", side_effect=site.get):
        with pytest.raises(RuntimeError, match="not done"):  # 首轮失败要冒泡: 否则构造不出可续传的中断态
            mgr.result(job_id, timeout=30)  # 等首轮收敛: 断点要留在磁盘上才谈得上续传


def _cancel_round(mgr: DownloadManager, job_id: str) -> bool:
    """首轮取满 1 页后被取消, 造出"取消标志已置 + 记录 cancelled"的现场。

    与 :func:`_interrupt` 的区别在终态: 这里走的是**用户主动取消**那条路
    (标志已置), 正是"被取消的作业还要再续"这个场景的前提 —— failed 终态的
    作业压根不能被 cancel (直接返回 False), 复现不了这条路径。

    Args:
        mgr: 被驱动的管理器。
        job_id: 作业标识。

    Returns:
        首轮那次 ``cancel()`` 的返回值 (本用例断言它是 True, 即确实被受理)。
    """
    accepted: list[bool] = []  # 记返回值: 调用方只看得到这个布尔

    def _cancel_on_second_page(page: int, call: int) -> None:
        """第 2 页响应到手前发取消 (页边界取消的标准时序)。"""
        if call == 2:  # 第 1 页留着落断点, 第 2 页发取消: 现场 = 断点 + 已置位的标志
            accepted.append(mgr.cancel(job_id))

    site = _FakeSite(on_fetch=_cancel_on_second_page)  # 不设杀点: 这次要的是取消而不是失败
    with patch.object(mgr.client.session, "get", side_effect=site.get):
        with pytest.raises(RuntimeError, match="not done"):  # result() 只报 done; 取消终态走异常是既有契约
            mgr.result(job_id, timeout=30)  # 等首轮收敛到 cancelled 终态
    return accepted[0]


class TestResumeObserverForwarded:  # K2-01: 观察者转发 —— 进度与取消共用这一个钩子
    """region/sqlid 的 resume_job: observer 必须转发, 且续传要换新取消标志。"""

    def test_resume_advances_done_pages_through_the_observer(self, tmp_path):
        """续传取回 3 页后 done_pages 必须从 1 走到 4 (K2-01 核心断言)。

        守的回归: observer 不转发时, 续传一路跑完并落 done, 但
        ``done_pages`` **仍停在首轮的 1** —— J6 真实负载下就是这个现象。
        终态 done 掩盖了它, 于是"进度条不动"被读成"任务已经很快"。
        """
        mgr = _mgr(tmp_path)  # 三个目录全锚临时区: 断点与进度都不许落在 CWD
        first = _FakeSite(kill_on_call=2)  # 第 2 次 phase-2 请求时被杀: 第 1 页 (250 行) 已落断点
        job_id = mgr.submit(SqlidJob(sqlid=SQLID, catalog="ps1", page_size=PAGE_SIZE, max_rows=TOTAL))
        _interrupt(mgr, job_id, first)  # 首轮断流: 现场 = 断点 next_page=2 + 记录 failed
        assert mgr.status(job_id)["done_pages"] == 1, "首轮只取到 1 页: 这是续传前的进度基线"

        second = _FakeSite()  # 续跑这一轮不杀: 让它跑到底, 才看得到 done_pages 走多远
        with patch.object(mgr.client.session, "get", side_effect=second.get):
            assert mgr.resume(job_id) == job_id  # 原地续传: 同一 job_id, 不新建任务

        rec = mgr.status(job_id)  # 续传后的权威记录 (进度文件为事实源)
        assert rec["status"] == STATUS_DONE  # 续传成功终态: 断点续跑的常规出口
        # 核心断言: 1 (首轮) + 3 (page=2/3/4) = 4。修复前这一行是 1。
        assert rec["done_pages"] == 4, "续传期逐页观察者没接上: done_pages 停在首轮基线"
        # 续传起点与步长一并守住: 起点必须是断点的 next_page, 步长必须是断点的那把
        assert second.pages[0] == (2, PAGE_SIZE), "续传必须从断点 next_page 起、用断点里的步长"
        assert mgr._downloader().checkpoint.load(job_id) is None, "成功后断点必须删除"
        mgr.shutdown()  # 收线程池: 首投与续传都已收尾, 不留悬挂 worker

    def test_cancel_during_resume_is_accepted_and_stops_the_transfer(self, tmp_path):
        """续传进行中 cancel(): 返回 True 且真在页边界停下 (K2-01 取消口径)。

        守的回归 (两道独立阻断, 少修一道都还会静默失效):
          1. 记录停在 failed 终态时 ``cancel()`` 直接 ``return False``, 标志
             连置都置不上 —— 故续传必须先把记录推到 running;
          2. 标志置上了, 续传路径也得有人读它 —— 那个人只可能是 observer。
        """
        mgr = _mgr(tmp_path)  # 三个目录全锚临时区: 断点与进度都不许落在 CWD
        job_id = mgr.submit(SqlidJob(sqlid=SQLID, catalog="ps1", page_size=PAGE_SIZE, max_rows=TOTAL))
        _interrupt(mgr, job_id, _FakeSite(kill_on_call=2))  # 首轮断流: 造出可续传的现场
        accepted: list[bool] = []  # 记 cancel() 的返回值: 调用方只看得到这个布尔

        def _cancel_during_resume(page: int, call: int) -> None:
            """在续传第一个页响应到手前发取消 (趁 observer 还没跑)。"""
            if call == 1:  # 只发一次: 续传窗口只有第一次请求是"进行中"
                accepted.append(mgr.cancel(job_id))  # 返回 False 即"取消请求未受理"

        second = _FakeSite(on_fetch=_cancel_during_resume)  # 探针挂在页响应之前
        with patch.object(mgr.client.session, "get", side_effect=second.get):
            mgr.resume(job_id)  # 同步内联续传: 被取消后自行收口, 不抛给调用方

        assert accepted == [True], "续传期 cancel() 必须受理: 返回 False 即取消静默失效"
        assert mgr.status(job_id)["status"] == STATUS_CANCELLED, "取消终态: 不得被读成 done/failed"
        assert len(second.pages) == 1, "取消必须页边界生效: 3 页的剩余量只取了 1 页就停"
        mgr.shutdown()  # 收线程池: 取消路径同样要回收, 否则退出时挂住

    def test_resume_does_not_inherit_a_stale_cancel_flag(self, tmp_path):
        """被取消过的作业再 resume: 必须能真跑完, 而不是第一页自我取消 (K2-01b)。

        守的回归: 接上 observer 之后, 若续传沿用上次被置位的取消标志, 重跑会在
        第一个页边界抛 JobCancelledError —— 续传功能被 observer 的修复本身打死。
        """
        mgr = _mgr(tmp_path)  # 三个目录全锚临时区: 取消现场同样不许落进真实运行目录
        job_id = mgr.submit(SqlidJob(sqlid=SQLID, catalog="ps1", page_size=PAGE_SIZE, max_rows=TOTAL))
        assert _cancel_round(mgr, job_id) is True  # 先取消一次: 标志置上, 复现"被取消后还要续"的真实场景
        assert mgr.status(job_id)["status"] == STATUS_CANCELLED  # 前提确认: 上一次确实是被取消的, 不是失败的

        second = _FakeSite()  # 续跑这一轮不杀也不取消
        with patch.object(mgr.client.session, "get", side_effect=second.get):
            mgr.resume(job_id)  # 续传: 必须换新标志, 否则第一页就被上次那次的取消打死

        assert mgr.status(job_id)["status"] == STATUS_DONE  # 跑完才是 done: cancelled 即标志被继承
        mgr.shutdown()  # 收线程池: 续跑已跑完, 正常回收即可


class TestCrossProcessResumePreservesRecord:  # N1-03: 跨进程重建 tracker 不得抹掉盘上记录
    """跨进程 resume: 重建 tracker 时进度与 result 必须从盘上旧记录继承。

    跨进程的现场造法: 首轮管理器 ``shutdown()`` 之后另起一个 ``_mgr(tmp_path)``
    —— 新实例内存注册表为空 (``_trackers`` 查不到), 指向同一份 ``.progress`` /
    ``.checkpoints``。这与「换个进程接着续」逐项等价, 且不需要真的起子进程。
    """

    def test_cross_process_resume_keeps_done_pages_cumulative(self, tmp_path):
        """跨进程续传后 done_pages 必须是 1+3=4, 而不是被重建归零后的 3。

        守的回归 (N1-03): 跨进程时内存注册表为空, 管理器按 job_id 重建
        tracker。此前重建走的是「另起一条全零 ProgressRecord」, 于是上一轮
        已取回的 1 页在盘上凭空消失, 进度条**回退**—— 同一个作业在同一个
        进程里续传就不会退, 差别只在于有没有跨进程, 极难凭直觉联想到。
        """
        mgr1 = _mgr(tmp_path)  # 首轮进程: 三个目录全锚临时区
        job_id = mgr1.submit(SqlidJob(sqlid=SQLID, catalog="ps1", page_size=PAGE_SIZE, max_rows=TOTAL))
        _interrupt(mgr1, job_id, _FakeSite(kill_on_call=2))  # 首轮断流: 第 1 页已落, 记录转 failed
        assert mgr1.status(job_id)["done_pages"] == 1, "首轮只取到 1 页: 这是跨进程前的进度基线"
        spec_before = mgr1.status(job_id)["result"]["resume_spec"]  # 记下 spec: 后面要逐字比对它还在不在
        mgr1.shutdown()  # 进程退出: 内存注册表随之消失, 只剩盘上记录

        mgr2 = _mgr(tmp_path)  # 新进程: 同一份 .progress/.checkpoints, 全新内存注册表
        assert job_id not in mgr2._trackers, "前提确认: 内存注册表确实是空的, 必须走重建分支"

        second = _FakeSite()  # 续跑这一轮不杀: 让它跑到底, 才看得到 done_pages 走多远
        with patch.object(mgr2.client.session, "get", side_effect=second.get):
            assert mgr2.resume(job_id) == job_id  # 原地续传: 同一 job_id

        rec = mgr2.status(job_id)  # 续传后的权威记录 (进度文件为事实源)
        assert rec["status"] == STATUS_DONE  # 续传成功终态
        # 核心断言: 1 (首轮) + 3 (page=2/3/4) = 4。修复前跨进程这一行是 3。
        assert rec["done_pages"] == 4, "跨进程重建把 done_pages 归零了: 进度条会从 1/4 退回 3/4"
        assert rec["result"]["path"], "产物路径必须落盘: 调用方拿它读文件"
        assert rec["result"]["resume_spec"] == spec_before, "resume_spec 必须逐字沿用: 变了就说明不是同一份快照"
        mgr2.shutdown()  # 收线程池: 续跑已收尾

    def test_cross_process_failed_resume_stays_resumable(self, tmp_path):
        """跨进程续传**失败**后 resume_spec 仍须在盘上, 作业才能再续 (N1-03 fail-open)。

        守的回归 (本组最要紧的一条): 重建 tracker 时若不继承旧记录, 那条全零
        快照会在构造期把 ``result`` 一并抹掉。于是续传再失败时盘上只剩
        ``status=failed`` + ``result=None`` —— ``resume()`` 第一步就因
        ``not rec.result`` 抛 FileNotFoundError, **这个作业永远续不回来**,
        而磁盘上没有任何损坏迹象可供排查。按铁律 5 这属 fail-open。

        因此用三个进程把整条链走完: 首轮断流 -> 第二进程续传再失败 ->
        第三进程仍能续成功。前两段任一失守, 最后一段就红。
        """
        mgr1 = _mgr(tmp_path)  # 首轮进程
        job_id = mgr1.submit(SqlidJob(sqlid=SQLID, catalog="ps1", page_size=PAGE_SIZE, max_rows=TOTAL))
        _interrupt(mgr1, job_id, _FakeSite(kill_on_call=2))  # 断流: 现场 = 断点 next_page=2 + 记录 failed
        spec_before = mgr1.status(job_id)["result"]["resume_spec"]  # 逐字留一份: 后面两次都比它
        mgr1.shutdown()  # 进程退出: 只剩盘上记录

        mgr2 = _mgr(tmp_path)  # 第二进程: 空注册表, 走重建分支
        with patch.object(mgr2.client.session, "get", side_effect=_FakeSite(kill_on_call=1).get):
            with pytest.raises(RuntimeError):  # 续传本体抛错上抛 (既有契约), 但记录已收口到 failed
                mgr2.resume(job_id)

        rec = mgr2.status(job_id)  # 失败续传后的盘上记录
        assert rec["status"] == STATUS_FAILED, "续传失败必须收口到 failed: 停在 running 就再也续不回来"
        # 核心断言: spec 仍在。修复后这一行是 False —— 记录被全零快照抹成了 None。
        assert rec["result"] is not None and rec["result"]["resume_spec"] == spec_before, \
            "跨进程重建抹掉了 resume_spec: 盘上记录看起来正常, 该作业却已永远续不回来 (fail-open)"
        assert rec["done_pages"] == 1, "上一轮实绩必须仍在盘上: 归零即进度说谎"
        mgr2.shutdown()  # 收线程池: 本次续传已抛错收场

        mgr3 = _mgr(tmp_path)  # 第三进程: 证明作业没被毁掉 —— 换个进程仍然续得动
        with patch.object(mgr3.client.session, "get", side_effect=_FakeSite().get):
            assert mgr3.resume(job_id) == job_id  # 这一行能返回, 就说明 spec 还在
        final = mgr3.status(job_id)  # 终态记录
        assert final["status"] == STATUS_DONE, "第三进程必须能续成功: 续不回来说明记录已在第二进程被毁"
        assert final["done_pages"] == 4, "跨两轮跨进程后仍是 1+3: 进度不得在任何一次重建时归零"
        mgr3.shutdown()  # 收线程池: 三个进程都干净退出

    def test_cross_process_resume_keeps_record_kind(self, tmp_path):
        """跨进程续传 sqlid 作业: 盘上 kind 仍须是 sqlid, 不得被改写成 region。

        守的回归 (与 N1-03 同一处重建): 重建 tracker 时若只传
        ``(store, job_id)`` 而漏掉 ``kind``, ``ProgressRecord`` 会取默认值
        ``"region"`` 并把它**落盘** —— 一次续传就把作业类型改掉了。GUI 的
        图标/文案与 CLI 的分类都按 kind 分支, 改写后两个作业会显示成同一种。
        """
        mgr1 = _mgr(tmp_path)  # 首轮进程
        job_id = mgr1.submit(SqlidJob(sqlid=SQLID, catalog="ps1", page_size=PAGE_SIZE, max_rows=TOTAL))
        _interrupt(mgr1, job_id, _FakeSite(kill_on_call=2))  # 断流: 造出可续传的现场
        mgr1.shutdown()  # 进程退出

        mgr2 = _mgr(tmp_path)  # 第二进程: 走重建分支
        with patch.object(mgr2.client.session, "get", side_effect=_FakeSite().get):
            mgr2.resume(job_id)
        assert mgr2.status(job_id)["kind"] == "sqlid", \
            "重建时漏传 kind 会让 sqlid 作业被落盘成 region: GUI 分类随之走错分支"
        mgr2.shutdown()  # 收线程池: 续跑已收尾


class TestResumeBlockingContract:  # K2-02: 同步内联是既定契约, 不是待修的缺陷
    """region/sqlid 的 resume 返回即终态; file 的 submit 立即返回 (刻意不对称)。"""

    def test_sqlid_resume_returns_only_after_reaching_a_terminal_state(self, tmp_path):
        """sqlid resume 返回时进度记录**已经是终态** (同步内联, K2-02 契约)。

        守的回归: 改成异步 (与 submit 对称) 会让"返回即终态"这条既有承诺
        消失 —— 调用方 (CLI/GUI) 现在是拿 resume 的返回值就直接读产物路径的。
        本用例把同步语义钉住, 任何"顺手改成异步"的改动都必须先改这里。
        """
        mgr = _mgr(tmp_path)  # 三个目录全锚临时区: 同步语义用例与其它用例互不串味
        job_id = mgr.submit(SqlidJob(sqlid=SQLID, catalog="ps1", page_size=PAGE_SIZE, max_rows=TOTAL))
        _interrupt(mgr, job_id, _FakeSite(kill_on_call=2))  # 首轮断流: 现场就绪

        second = _FakeSite()  # 续跑这一轮不杀: 绑定 .get, 直接把实例传给 side_effect 会被 mock 当迭代器
        with patch.object(mgr.client.session, "get", side_effect=second.get):
            mgr.resume(job_id)  # 同步续传: 这一行返回时下载已经跑完

        # 不调 result() 就已是终态: 这正是"同步内联"的证据 (异步侧此刻多半还在 running)
        assert mgr.status(job_id)["status"] == STATUS_DONE, "resume 返回即终态: 异步化会打破这条承诺"
        mgr.shutdown()  # 收线程池: 同步续传已返回, 池里无在途任务

    def test_submit_returns_before_the_job_reaches_a_terminal_state(self, tmp_path):
        """submit 立即返回且记录非终态 (异步, 与 resume 的同步语义对照)。

        守的不变量: 「提交即返回」是管理器对外的前台承诺 (agent 前台不阻塞在
        网络 IO 上)。与上一条并读才说得清不对称: submit 异步、region/sqlid 的
        resume 同步, 两者是刻意取舍而非其中一条写错了。
        """
        mgr = _mgr(tmp_path)  # 三个目录全锚临时区: 异步语义只看状态, 不需要断点
        entered, release = threading.Event(), threading.Event()  # 两个 Event 造出可控的"正在跑"窗口

        class _BlockingBest:
            """假客户端: 进入后阻塞, 把任务钉在 running 态。"""

            def download_file(self, url, savedir="./", filename=None, job_id=None,
                              progress_tracker=None, cancel_event=None, **kw):  # noqa: ANN001 签名要吃住全套实参
                """置 entered 后等 release: 让断言落在"submit 已返回但任务还在跑"这个窗口。"""
                entered.set()  # 先报到达: 测试据此确认 worker 真的进了下载面
                release.wait(timeout=10)  # 阻塞在此: 直到测试放行
                return "/tmp/fake.fits"  # 产物路径: 收尾用, 断言不靠它

        mgr.client = _BlockingBest()  # 整体换客户端: 本用例不测协议面, 只要一个可控的运行窗口
        jid = mgr.submit(FileJob(url="https://nadc.china-vo.org/data/best/f.fits"))  # 真实主机名: 免得白名单校验先把它判失败
        assert entered.wait(timeout=5)  # worker 已进下载面 (任务确实在跑)
        assert mgr.status(jid)["status"] == STATUS_RUNNING  # submit 早已返回: 此刻仍是非终态
        release.set()  # 放行: 不然退出时会挂在 10 秒超时上
        mgr.shutdown()  # 收线程池


class TestAuthTimeoutWiring:  # K2-03: 认证路径的超时取值口
    """BestAuth 的两个请求点必须取实例 request_timeout。"""

    def test_configured_timeout_reaches_both_auth_request_points(self):
        """``BestAuth(timeout=7)``: 登录页 GET 与登录 POST 都必须真的用 7s。

        守的回归: 此前本类 ``__init__`` 不收 timeout, 两个请求点都写死取协议层
        120s —— 调用方把 ``BestClient(timeout=7)`` 调快, 启动期这两个请求照样
        能挂 120s 再静默降级匿名, 与"设 7s 快速失败"的意图正好相反。
        """
        auth = BestAuth(timeout=7)  # 显式收窄: 这正是运维"单请求封顶"的那把旋钮
        seen: list[object] = []  # 记两个请求点各自收到的 timeout 实参

        class _AuthSite:
            """登录端点替身: 记录 timeout 后回一个停在登录页的响应。"""

            def get(self, url, **kwargs):  # noqa: ANN001 替身签名随 requests 变化, 收 **kwargs 即可
                """第一步取登录页: 记下 timeout, 回带 csrf 字面量的 HTML。"""
                seen.append(kwargs.get("timeout"))  # 实参而非"应该用多少": 写死常量这里就会露馅
                return _Resp('<input name="csrf_token" value="csrf_token = \\"tok\\"">', url=url)

            def post(self, url, **kwargs):  # noqa: ANN001 同上
                """第二步提交凭据: 记下 timeout, 停在登录页即"被拒"分支。"""
                seen.append(kwargs.get("timeout"))  # 两个请求点必须是同一个值
                return _Resp("<html>bad credentials</html>", url=url)  # URL 仍含 login 即失败

        with patch.object(auth, "session", _AuthSite()):
            assert auth.login("someone", "wrong-password") is False  # 失败出口: 凭据是假的, 不发真凭据
        assert seen == [7, 7], "两个认证请求点必须都取实例超时, 而不是协议层常量"

    def test_default_auth_timeout_is_still_the_protocol_constant(self):
        """未显式配置时: ``BestAuth()`` 的有效超时仍等于 ``REQUEST_TIMEOUT``。

        守的回归: 新增构造参数最容易踩的坑就是顺手改了缺省值。补上超时旋钮
        不许改变任何既有调用方的字节级行为 (全仓 ``BestAuth()`` 都是无参构造)。
        """
        assert BestAuth().request_timeout == REQUEST_TIMEOUT  # 缺省口径不变: 未配置者行为逐字节一致
