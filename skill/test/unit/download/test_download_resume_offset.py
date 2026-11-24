"""断点续传的偏移完整性回归 (A3-01)。

守的不变量: phase-2 是**偏移翻页** —— 实测同一会话 (sqlid) 下
``page=2&rows=100`` 返回的 100 行, 与 ``page=1&rows=1000`` 的 ``[100:200]``
逐行完全相同。因此 ``next_page`` 只有与当初那把 ``page_size`` 成对才有意义:
断点不记步长、续传再回落缺省 1000, 首跑 ``page_size=250`` 被杀在第 3 页之后,
续传实际发出的是 ``(page=4, rows=1000)``, 服务端按 1000 的步长数偏移直接回空页,
于是落盘 750 行、缺失区间 750..999 —— **无重复、无异常、终态 done**, 是最难查
的一类静默数据缺损。

本文件刻意不打桩 ``_fetch_sqlid_data``: 那样等于把要验的偏移翻页逻辑本身一起
替掉。桩只落在 ``session.get`` (真实分页引擎照跑: build_page_url / 偏移切片 /
CSV 解析 / 页级断点 / 续传参数复原全在被测链内), 全程零真实网络请求。
"""
from __future__ import annotations

# 标准库: csv 按表头读回落盘产物 / urllib.parse 拆查询串 (从分页 URL 取回 rows/page)
import csv  # 落盘列序是排序并集: 取列必须按表头名, 不能按位置

# 标准库: patch 替换取数出口 (phase-1 会话建立 / phase-2 分页), 离线复现断点现场
from unittest.mock import patch  # 换掉网络面: 本文件全程不碰真实站点
from urllib.parse import parse_qs, urlparse  # 标准库 URL 拆解, 不手写字符串切

# 测试框架: raises 断言 fail-closed 冒泡; tmp_path 提供每次用例独立的临时目录
import pytest  # 两条用例分别守"不丢行"与"缺键即抛", 都要能断言异常类型

# 本地: 生产客户端 (rate_limit=0 关掉礼貌限流, 桩在 session 层故不发真请求)
from src.client import BestClient

# 本地: 被测单元 — 下载器 (断点状态机 + 落盘出口的权威实现)
from src.downloader import BestDownloader

TOTAL = 1000  # 会话总行数: 取 4 的整数倍, 便于断言"缺失区间恰好是最后 250 行"
PAGE_SIZE = 250  # 首跑步长: 与续传缺省 1000 不同, 正是丢行的触发条件
CSV_HEADER = "ps1_source_id,ps1_ra,ps1_dec,ps1_rpsf,ps1_snr\n"  # ps1 真实投影: 解析层按 catalog 剥前缀


class _Resp:  # 最小回包: 分页引擎只用到 .text 与 raise_for_status()
    """仿真 HTTP 回包 (只实现被测链真正调用的两个成员)。"""

    def __init__(self, text: str) -> None:
        """存正文: 计数端点与分页端点的区别全在正文里。"""
        self.text = text  # 回包正文: getcount 是 {"total": N}, phase-2 是 CSV

    def raise_for_status(self) -> None:
        """恒成功: 本文件不测 HTTP 状态码, 故障一律用"抛异常"表达。"""
        return  # 200 即无动作


class _OffsetSite:
    """按实测偏移语义供数的假站点 (phase-2 的 ``rows`` 是偏移步长)。

    守的回归: 若桩按"第 N 页 = 第 N 段"以外的语义供数 (例如按页号线性切片),
    这条用例就测不出断点丢步长; 偏移语义是本文件与真实站点一致的唯一依据。
    """

    def __init__(self, kill_on_page: int | None = None) -> None:
        """构造站点。

        Args:
            kill_on_page: 第几次 phase-2 分页请求时抛错 (模拟进程被杀)。
                ``None`` 表示不杀, 供续跑那一轮正常跑完。
        """
        self.kill_on_page = kill_on_page  # 杀点: 断点现场由此造出
        self.phase2_calls = 0  # phase-2 计数: 杀点按调用序判定, 不按页号 (页号会随续跑变化)
        self.requests: list[tuple[int, int]] = []  # 记账 (page, rows): 断言续传步长要用

    def get(self, url: str, **kwargs) -> _Resp:
        """按 URL 分派: getcount 回总数, 分页 URL 回按偏移切出的那一页。"""
        if "getcount" in url:  # 计数端点: 少了它 total_count 只能报诚实但无用���本地行数
            return _Resp('{"total": %d}' % TOTAL)  # 总数照实报: 截断判定与空结果闸都靠它
        params = parse_qs(urlparse(url).query)  # 协议键是 rows/page (protocol.build_page_url)
        page = int(params["page"][0])  # 页码: 偏移 = (page-1) * rows
        rows = int(params["rows"][0])  # 步长: 与 page 成对才解释得通
        self.requests.append((page, rows))  # 记账: 续传那一轮发了什么, 事后可逐条核
        self.phase2_calls += 1
        if self.kill_on_page is not None and self.phase2_calls == self.kill_on_page:
            # 抛非 requests 异常: 分页引擎只把网络错降级为"已取部分", 其它异常直接冒泡,
            # 断点因此留在磁盘上 (这才是"进程被杀"的现场; 网络错会走成功落盘+删断点)
            raise RuntimeError("simulated kill on phase-2 request %d" % self.phase2_calls)
        start = (page - 1) * rows  # 偏移起点: 实测 page=2&rows=100 == page=1&rows=1000 的 [100:200]
        body = "".join(  # 逐行造本页数据: 行序即服务端行序, 偏移才有意义
            "SRC_%05d,%.4f,30.0000,18.20,25.0\n" % (i, 180.0 + i / 1000.0)
            for i in range(start, min(start + rows, TOTAL))
        )
        return _Resp(CSV_HEADER + body)  # 带表头: 解析层据此判定 has_header 并剥前缀


def _dl(tmp_path) -> BestDownloader:
    """造一个锚定临时区的下载器 (两个运行时目录都不许落在 CWD 相对默认上)。"""
    return BestDownloader(  # 限流归零: 桩在 session 层, 但仍不该让用例等礼貌 sleep
        BestClient(rate_limit=0),
        output_dir=str(tmp_path / "data"),
        checkpoint_dir=str(tmp_path / "ckpt"),
    )


def _source_ids(csv_path: str) -> set[str]:
    """从落盘 CSV 读回 source_id 集合 (断言要的是集合相等, 不是"两轮并集非空")。"""
    with open(csv_path, encoding="utf-8-sig", newline="") as fh:  # utf-8-sig 吃 BOM; newline="" 是 csv 的硬要求
        rows = list(csv.DictReader(fh))  # 按表头取列: 落盘列序是排序并集, 不能按位置猜
    return {r["source_id"] for r in rows}  # 投影后的规范列名, 非站点原始前缀列


def test_resume_after_kill_keeps_full_row_set(tmp_path):
    """首跑 page_size=250 被杀 → resume_job: 最终 source_id 集合必须等于全集。

    守的回归: 断点丢了 ``page_size`` 且 ``resume_job`` 不透传时, 续传会按缺省
    1000 请求第 4 页, 服务端回空页, 落盘 750 行而终态 done —— 缺失的 250 行
    无重复、无异常、只在事后对账时才看得见。故这里断的不是"有没有续上", 而是
    **续上之后的行集合是否等于全集**。
    """
    dl = _dl(tmp_path)
    job_id = "offset_resume_job"
    first = _OffsetSite(kill_on_page=4)  # 第 4 次 phase-2 请求时被杀: 前 3 页 (750 行) 已落断点

    with patch.object(dl.client, "submit_phase1", return_value=("s4242", None)), \
         patch.object(dl.client.session, "get", side_effect=first.get):
        with pytest.raises(RuntimeError, match="simulated kill"):  # 杀点必须冒泡: 断点留在磁盘上才谈得上续传
            dl.download_by_constraints(  # 走约束通道: 它是 phase-1 + 页级断点的真实入口
                constraints=[], catalog="ps1", output_format="csv",
                output_file="offset.csv", page_size=PAGE_SIZE, max_rows=TOTAL,
                job_id=job_id, resumable=True,
            )

    state = dl.checkpoint.load(job_id)  # 读回断点: 它是续传的唯一事实源
    assert state is not None, "被杀后断点必须还在磁盘上, 否则续传名存实亡"
    assert state["next_page"] == 4  # 断点是"下一页": 3 页已取, 下一趟从第 4 页起
    assert state["page_size"] == PAGE_SIZE  # 步长必须入断点: 偏移翻页下它与 next_page 成对
    assert state["max_rows"] == TOTAL  # 上限同样入断点: 续传不靠缺省猜 phase-2 封顶值 (A2-03)
    assert len(state["sources"]) == 3 * PAGE_SIZE  # 断点里恰好三页: 断在第 4 页之前

    second = _OffsetSite()  # 续跑这一轮不杀: 让它跑到底
    with patch.object(dl.client.session, "get", side_effect=second.get):
        saved = dl.resume_job(job_id)  # 走公共续传入口: 参数复原的 bug 就暴露在这里

    # 核心断言: 集合等于全集。修复前这行会少掉 SRC_00750..SRC_00999 这 250 行
    assert _source_ids(saved) == {"SRC_%05d" % i for i in range(TOTAL)}, "续传后的行集合必须等于全集"
    # 步长复原的直接证据: 续跑首个请求必须是 (page=4, rows=250), 而不是 (4, 1000)
    assert second.requests[0] == (4, PAGE_SIZE), "续传首个分页请求必须沿用断点里的步长"
    assert all(rows == PAGE_SIZE for _page, rows in second.requests), "续传全程步长不得中途变形"
    assert dl.checkpoint.load(job_id) is None, "成功后断点必须删除, 否则下次同 id 重复导出"


def test_resume_refuses_checkpoint_without_page_size(tmp_path):
    """断点已翻页却没有 page_size: resume_job 必须显式抛错, 且一个请求都不发。

    守的回归 (铁律 5 禁 fail-open): 旧格式断点缺步长时, 任何缺省都是**猜偏移
    语义** —— 实测偏移下猜错即静默丢整段行, 且终态是 done。此处宁可拒绝续传,
    也不能替调用方决定一个它没给过的步长。
    """
    dl = _dl(tmp_path)
    job_id = "legacy_ckpt_job"
    dl.checkpoint.save(job_id, {  # 预置"第 1 页已下完"的旧格式断点: 只有 next_page, 没有 page_size
        "job_id": job_id,
        "sqlid": "s4343",
        "catalog": "ps1",
        "next_page": 2,  # 已翻过页: 偏移已经建立, 步长不可缺
        "sources": [{"source_id": "SRC_00000", "ra": 180.0, "dec": 30.0, "magnitudes": {"r": 18.2}}],
        "output_format": "csv",
        "output_file": "legacy.csv",
    })

    def _forbidden_get(*args, **kwargs):  # pragma: no cover - 只在闸失效时才会被调到
        """任何真实/桩请求都让用例失败: 拒绝续传必须发生在发请求之前。"""
        raise AssertionError("拒绝续传时不得发出任何请求")

    with patch.object(dl.client.session, "get", side_effect=_forbidden_get), \
         patch.object(dl.client.session, "post", side_effect=_forbidden_get):
        with pytest.raises(RuntimeError, match="page_size"):  # 错误文案要指名缺失的键与补救动作
            dl.resume_job(job_id)  # 断点缺步长 + 已翻页 = 不可安全续传

    # 断点必须原样留着: 拒绝续传不等于替用户删掉现场
    assert dl.checkpoint.load(job_id) is not None, "拒绝续传不得顺手删掉断点: 证据要留给排障"
