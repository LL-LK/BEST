# -*- coding: utf-8 -*-
"""TAP 鲁棒性回归: 异步截断信号 (A4-03)、非 UTF-8 请求体 (A4-02)、端点推导 (A4-04)。

职责: 守住三条"看起来能跑、实际静默给错答案或直接崩连接"的回归 ——
  1. A4-03: 异步面必须给出与同步面同口径的 MAXREC 截断信号, 且 CSV/FITS 也有
     可判定的标记; 这三条缺任何一条, "结果被 MAXREC 截断"都会退化成一份与
     全集无法区分的残缺数据 (fail-open, 与 A2-01 半行不可见同族);
  2. A4-02: 非 UTF-8 POST 体必须回 400 错误文档, 而不是让解码异常冒到 socket
     层把连接关成零 HTTP 响应;
  3. A4-04: 带子路径的 base_url 也要推出正确的交换端点, 不靠定长切片。

所属层次: test/unit 层。对应被测模块是 src/tap/service.py (请求体解码与同步面
截断头)、src/tap/uws_service.py (异步结果响应头)、src/tap/jobs.py (截断位落库)、
src/tap/formats.py (三格式的截断标记) 与 src/tap/client.py (端点推导)。
对外接口: 三类用例各成一类 —— 异步截断信号走真实环回 HTTP (127.0.0.1:0),
格式级截断标记直接断序列化产物, 端点推导走注入的假 service_factory。
依赖与数据流: 后端是 _FakeBest 替身 (query() 无视参数原样回吐脚本化行), 整条
链路零外网; 夹具只有 tmp_path, sqlite 库与结果目录都落在它下面, 是本文件唯一
的写盘面。
关键契约与不变量: 同步面与异步面的截断头**必须同名同值** (常量取自
src.tap.formats, 两处不各写一份), 断这条等于断"两面同口径"; 截断信号只在真被
截断时出现, 干净结果挂上去是误报, 会让客户端白白丢掉一次全量结果。
陷阱与边界: 替身必须"无视参数原样回吐" —— 它一旦去校验 radius_arcsec 之类,
就会把执行器的单位换算 bug 一起遮住; 环回一律用 ephemeral 端口 (127.0.0.1:0),
写死 8000 会在并行跑时 bind 失败。
"""
from __future__ import annotations

# 标准库: 环回 HTTP 客户端 (发原始字节体与读响应头)、线程、路径、上下文管理器
import http.client
import threading
import time
from contextlib import contextmanager
from io import BytesIO
from pathlib import Path
from urllib.parse import urlparse

# 第三方: pytest 承载测试发现与 tmp_path 结果目录夹具
import pytest

# 本地: 执行器 (ADQL plan -> 协议参数)、序列化层 (三格式的截断标记) 与异步作业存储 (sqlite + 结果目录)
from src.tap.executor import TapExecutor
from src.tap.formats import (  # 截断头名/取值与被测代码同源: 断"两面同口径"要断名字, 不重复写一份
    OVERFLOW_HEADER,
    OVERFLOW_VALUE,
    serialize_result,
)
from src.tap.jobs import TapJobStore

# 本地: 被测网关本体 + 其 stdlib socket 适配器
from src.tap.service import TapGateway, TapHTTPServer

# 模块级常量: 贯穿全文件的锥形 ADQL, 与 test_service.py 同句, 保证可比
CONE_QUERY = (  # 与 test_service.py 同句: 两处问同一个问题, 截断与非截断才可比
    "SELECT ra, ps1_rpsf FROM best.ps1 "
    "WHERE CONTAINS(POINT('ICRS', ps1_ra, ps1_dec), CIRCLE('ICRS', 180.0, 30.0, 0.1)) = 1"
)
# 模块级常量: 截断用例专用的十行数据 — MAXREC=3 对十行, 差得足够大才让溢出位真假可辨
TRUNCATED_ROWS = [{"ps1_ra": str(i), "ps1_rpsf": "15.0"} for i in range(10)]  # 探针行(第 4 行)必然取到, 溢出位无歧义


class _FakeBest:
    """替身后端: query() 无视参数原样回吐脚本化行, 隔离真实星表 HTTP。"""

    def __init__(self, rows: list[dict] | None = None) -> None:
        """装入脚本化结果行; 不传时回一行 ps1 结果。"""
        self.rows = rows if rows is not None else [{"ps1_ra": "180.0", "ps1_rpsf": "15.5"}]

    def query(self, **_kwargs):
        """无视入参原样回吐脚本化行, 隔离真实星表 HTTP 依赖。"""
        return list(self.rows)  # 无视入参: 替身一旦校验参数就会遮住执行器换算 bug


def _gateway(tmp_path: Path, *, rows=None) -> TapGateway:
    """搭一个作业库与结果目录都落在 tmp_path 的网关 (带作业存储, 异步面要测)。"""
    executor = TapExecutor(_FakeBest(rows))  # 执行器只认替身, 整条链路零外网
    store = TapJobStore(str(tmp_path / "tap.db"), str(tmp_path), executor)  # 库与结果目录同锚 tmp_path
    return TapGateway(executor, job_store=store)  # 异步路径要求作业存储在场


@contextmanager
def _served(gateway: TapGateway):
    """把网关装上环回 ephemeral 端口起服务, 退出时确保三件事都做完。

    借真实 socket 而非直调 handle(): 两条被测回归都发生在 HTTP 事务层
    (响应头写没写出去、解码异常会不会冒到 handle_error), 直调 handle() 只能
    验证到 TapResponse 这一层, 恰好漏掉 A4-02 的失灵点。
    """
    server = TapHTTPServer(("127.0.0.1", 0), gateway)  # 端口 0: 由内核分配, 并行跑不撞
    thread = threading.Thread(target=server.serve_forever, daemon=True)  # 守护线程: 不该挡住进程退出
    thread.start()
    try:
        yield server.server_address[1]  # 只交出端口: 客户端连法由调用方按需要挑
    finally:
        # 三个动作缺一不可: shutdown 停循环, server_close 放端口, join 收线程;
        # 只做前者会让端口与线程在同进程内残留, 后续用例 bind 失败
        server.shutdown()
        server.server_close()
        if thread.is_alive():
            thread.join(timeout=5)


def _post_form(port: int, path: str, fields: dict[str, str]) -> tuple[int, dict[str, str], bytes]:
    """POST 一份 urlencoded 表单并回 (状态码, 头, 体)。"""
    from urllib.parse import urlencode  # 局部导入: 只有本辅助用得上, 放模块级会拉长表头

    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)  # 标准库客户端: 零依赖探路
    try:
        body = urlencode(fields)  # 表单编码: POST 建单走 DALI 的 x-www-form-urlencoded
        conn.request("POST", path, body=body, headers={"Content-Type": "application/x-www-form-urlencoded"})
        response = conn.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        conn.close()  # 不关连接: keep-alive 的套接字会占着端口与 fd


def _get_raw(port: int, path: str) -> tuple[int, dict[str, str], bytes]:
    """GET 一个路径并回 (状态码, 头, 体); 头按小写键归一便于查。"""
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    try:
        conn.request("GET", path)
        response = conn.getresponse()
        return response.status, {k.lower(): v for k, v in response.getheaders()}, response.read()
    finally:
        conn.close()


def _post_raw_body(port: int, path: str, body: bytes) -> tuple[int, dict[str, str], bytes]:
    """POST 任意字节体 (含非 UTF-8) 并回 (状态码, 头, 体)。"""
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)  # 不设 charset: 体由调用方原样给
    try:
        conn.request("POST", path, body=body, headers={"Content-Type": "application/x-www-form-urlencoded"})
        response = conn.getresponse()
        return response.status, {k.lower(): v for k, v in response.getheaders()}, response.read()
    finally:
        conn.close()


def _run_async_csv_job(port: int, maxrec: str) -> int:
    """经环回建一个 csv 异步作业并跑到终态, 返回 job id。"""
    status, headers, _ = _post_form(port, "/tap/async", {"QUERY": CONE_QUERY, "FORMAT": "csv", "MAXREC": maxrec, "PHASE": "RUN"})  # PHASE=RUN 建单即跑, 省掉一次轮询触发
    assert status == 303, f"建单应回 303, 实际 {status}"  # 303 而非 200: UWS 要求客户端跟 Location 轮询
    job_id = headers["Location"].rsplit("/", 1)[-1]  # id 从 Location 末段切出
    deadline = time.monotonic() + 10.0  # deadline 用单调时钟: 墙钟被校时会跳过轮询或拖满全程
    while time.monotonic() < deadline:  # 轮询 /phase 直到终态; 替身驱动, 通常一两次就收敛
        phase_status, _, phase_body = _get_raw(port, f"/tap/async/{job_id}/phase")
        assert phase_status == 200, f"读相位应回 200, 实际 {phase_status}"
        if phase_body.decode() in ("COMPLETED", "ERROR", "ABORTED"):
            assert phase_body.decode() == "COMPLETED", f"作业应收敛到 COMPLETED, 实际 {phase_body!r}"
            return job_id
        time.sleep(0.05)  # 50ms: 替身驱动的作业几乎瞬时完成, 睡太长纯属浪费
    raise AssertionError("作业相位 10s 内未收敛")


class TestAsyncOverflowSignal:
    """A4-03 核心: async + csv + MAXREC 截断, 响应里必须判定得出被截断。"""

    def test_async_csv_truncation_is_signalled_over_loopback(self, tmp_path):
        """端到端: 环回建 csv 作业 → 触发 MAXREC 截断 → 结果响应必须带 X-TAP-Overflow。

        这是 A4-03 的验收点: 截断信号此前只存在于同步面, 异步面取到的响应
        里没有任何可判定的截断痕迹, 客户端把 maxrec 行当全集 — 与作业失败
        无关、也不报错, 属静默 fail-open。
        """
        with _served(_gateway(tmp_path, rows=TRUNCATED_ROWS)) as port:  # 环回起真服务: 截断头要经 socket 才算真写出去, 直调 handle() 验不到这一层
            job_id = _run_async_csv_job(port, maxrec="3")  # MAXREC=3 对十行: 探针行必然命中, 溢出位无歧义
            status, headers, body = _get_raw(port, f"/tap/async/{job_id}/results/result")
        assert status == 200, f"取结果应回 200, 实际 {status}"  # 未完成会先撞 409, 那是相位问题不是本条
        # 头名与取值都要对: 少头名客户端无从判定, 取值不是字面量 "true" 则按真值判定会读成 False
        assert headers.get(OVERFLOW_HEADER.lower()) == OVERFLOW_VALUE, (
            f"异步结果响应缺 {OVERFLOW_HEADER}: 实际头 {sorted(headers)}"
        )
        # 截断确实发生了 — 载荷本身只有 3 行数据 + 1 行表头, 断这一条防"头无条件挂"
        assert len(body.decode().strip().splitlines()) == 4, "载荷应是 3 行数据 + 表头, 与 MAXREC=3 一致"

    def test_async_untruncated_result_has_no_overflow_header(self, tmp_path):
        """负向对照: 未被截断 (MAXREC=20 > 十行) 的异步结果**不得**挂截断头。

        无条件挂头是反向的 fail-open: 客户端会把一次完整结果误当残缺, 白白
        丢掉或重查 —— 修"漏挂"时最容易顺手改成"总是挂", 这条守住那个边界。
        """
        with _served(_gateway(tmp_path, rows=TRUNCATED_ROWS)) as port:  # 环回起真服务: 负向对照, 未截断时这个头必须不出现
            job_id = _run_async_csv_job(port, maxrec="20")  # 上限给足十行, 探针行取不到, 不截断
            status, headers, body = _get_raw(port, f"/tap/async/{job_id}/results/result")
        assert status == 200
        assert OVERFLOW_HEADER.lower() not in headers, "未截断却挂了截断头: 误报会让客户端丢掉一次完整结果"
        assert len(body.decode().strip().splitlines()) == 11, "十行数据 + 表头, 确系未截断"

    def test_sync_and_async_use_identical_overflow_header(self, tmp_path):
        """同口径: 同步面与异步面的截断头必须同名同值 (同一份常量, 不各写一份)。"""
        with _served(_gateway(tmp_path, rows=TRUNCATED_ROWS)) as port:  # 环回起真服务: 同一套替身同时喂同步面与异步面, 两面才可比
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)  # 同步面用 GET + 查询串
            try:
                from urllib.parse import urlencode as _ue  # 查询串编码, 局部导入理由同 _post_form

                query = "/tap/sync?" + _ue({"QUERY": CONE_QUERY, "FORMAT": "csv", "MAXREC": "3"})
                conn.request("GET", query)
                sync_response = conn.getresponse()
                sync_headers = {k.lower(): v for k, v in sync_response.getheaders()}
                sync_response.read()  # 读完才换请求: 不读会占着连接
            finally:
                conn.close()
            job_id = _run_async_csv_job(port, maxrec="3")  # 同样 MAXREC=3 对十行, 只换"同步还是异步"这一个变量
            _, async_headers, _ = _get_raw(port, f"/tap/async/{job_id}/results/result")
        # 两面都挂, 且挂的是同一个头同一个值: 客户端写一套判定逻辑即可, 换面不会漏判
        assert sync_headers.get(OVERFLOW_HEADER.lower()) == OVERFLOW_VALUE, "同步面截断头缺失或口径不同"
        assert async_headers.get(OVERFLOW_HEADER.lower()) == OVERFLOW_VALUE, "异步面截断头缺失或口径不同"

    def test_overflow_bit_survives_in_the_job_row(self, tmp_path):
        """作业行必须真记下截断位 (结果面靠它挂头; 不落库则异步面上无处可取)。"""
        store = TapJobStore(str(tmp_path / "tap.db"), str(tmp_path), TapExecutor(_FakeBest(TRUNCATED_ROWS)))  # 直连存储层, 验落库这一环
        job = store.create_job(CONE_QUERY, "csv", 3, owner_key="anonymous:10.0.0.1", authenticated=False)
        store.start_job(job["id"])  # 排进线程池, 与 HTTP 建单同一条执行路径
        for _ in range(200):  # 有界轮询: 200 * 50ms = 10s 上限, 免得异常时挂死
            if (current := store.get_job(job["id"]))["phase"] in ("COMPLETED", "ERROR", "ABORTED"):
                break
            time.sleep(0.05)
        current = store.get_job(job["id"])  # 回读终态: 迁移刚发生的那一行里溢出位才是真值
        assert current["phase"] == "COMPLETED", f"作业应收敛到 COMPLETED, 实际 {current['phase']}"
        assert current["overflow"] == 1, f"截断位未落库, 实际 {current['overflow']!r}"
        store.close()  # 收尾关线程池: 不关会在同进程内留下悬空线程


class TestLegacyJobTableMigration:
    """老库 (建于截断位落库之前) 必须被补列, 否则老部署会静默丢截断信号。"""

    def test_missing_overflow_column_is_added_on_startup(self, tmp_path):
        """按老 schema 建一张没有 overflow 列的表, 再起存储: 列必须被补上。

        CREATE TABLE IF NOT EXISTS 只保证表在、不保证列齐; 补列这步漏掉时,
        老库上的作业行压根没有溢出位, 响应便挂不出截断头 — 与本列从未存在
        同一种 fail-open。
        """
        import sqlite3  # 标准库: 直接造一张缺列的老表

        db_path = str(tmp_path / "legacy.db")  # 独立库文件: 不与其它用例的库混用
        conn = sqlite3.connect(db_path)  # 直连 sqlite: 造一张缺列的老表, 走真实 DDL
        try:
            # 刻意抄一份**不含** overflow 列的老 schema (即本次改动之前的建表语句)
            conn.execute("""
                CREATE TABLE tap_jobs (
                    id TEXT PRIMARY KEY, owner_key TEXT NOT NULL, authenticated INTEGER NOT NULL DEFAULT 0,
                    query TEXT NOT NULL, output_format TEXT NOT NULL, maxrec INTEGER NOT NULL,
                    phase TEXT NOT NULL, error TEXT, result_path TEXT, media_type TEXT, checksum TEXT,
                    size INTEGER, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                )
            """)
            conn.commit()
        finally:
            conn.close()

        store = TapJobStore(db_path, str(tmp_path), TapExecutor(_FakeBest()))  # 起存储即触发 _init_db 的补列
        try:
            with store._db() as conn:  # 走存储自己的连接入口, 退出即关: 裸 __enter__ 的连接会被 GC 关掉
                columns = {row["name"] for row in conn.execute("PRAGMA table_info(tap_jobs)")}  # 实探补列结果
            assert "overflow" in columns, "老库未补出 overflow 列: 存量部署会静默丢截断信号"
            # 存量行的取值必须是"未截断"而不是 NULL: NULL 会让 job.get("overflow") 走到假分支之外
            job = store.create_job(CONE_QUERY, "csv", 10, owner_key="k", authenticated=False)  # 补列后建单必须仍能跑通
            assert job["overflow"] == 0, "新行溢出位缺省应为 0 (未截断)"
        finally:
            store.close()


class TestNonUtf8PostBody:
    """A4-02: 非 UTF-8 请求体回 400 错误文档, 不得崩成零 HTTP 响应。"""

    def test_non_utf8_body_returns_400_not_a_dropped_connection(self, tmp_path):
        """裸 0xFF 0xFE 体: 必须回 400 且带可读错误信息。

        修复前: strict 解码抛 UnicodeDecodeError, 异常一路冒到 socketserver 的
        handle_error, 连接被直接关掉 —— 客户端连状态码都读不到, 与"服务崩了"
        同形, 且同进程内该连接后续请求一并失效。
        """
        with _served(_gateway(tmp_path)) as port:  # 环回起真服务: 解码异常冒到 socket 层才看得出来, 直调 handle() 验不到
            status, headers, body = _post_raw_body(port, "/tap/sync", b"\xff\xfe")
        assert status == 400, f"非 UTF-8 体应回 400, 实际 {status} (0 表示连接被关, 无任何响应)"
        # 错误信息要可读且说清原因, 客户端与排障者才知道该重发编码还是改端点
        assert b"UTF-8" in body, f"错误文档要点名 UTF-8: 实际 {body[:200]!r}"
        assert headers.get("content-type", "").startswith("application/x-votable+xml"), "错误文档沿用 VOTable 形态, 与其余 4xx 一致"

    def test_valid_utf8_body_with_bad_adql_still_returns_400(self, tmp_path):
        """对照组: 合法 UTF-8 体 + 错 ADQL 仍回 400 (证明上一条不是"碰巧都 400")。"""
        with _served(_gateway(tmp_path)) as port:  # 环回起真服务: 对照组走同一条解码路径, 排除「碰巧都 400」
            status, _, body = _post_form(port, "/tap/sync", {"QUERY": "SELECT bogus FROM nowhere", "FORMAT": "csv"})
        assert status == 400, f"错 ADQL 应回 400, 实际 {status}"
        assert b"QUERY_STATUS" in body, "错误体应是带 QUERY_STATUS 的 VOTable 文档"

    def test_valid_utf8_body_still_executes(self, tmp_path):
        """对照组: 正常 UTF-8 表单体仍能跑出 200 (解码这层不能把好请求也拒了)。"""
        with _served(_gateway(tmp_path, rows=TRUNCATED_ROWS)) as port:  # 环回起真服务: 正常请求必须仍跑通, 断这条防把解码层写成一律拒
            status, _, body = _post_form(port, "/tap/sync", {"QUERY": CONE_QUERY, "FORMAT": "csv", "MAXREC": "3"})
        assert status == 200, f"正常表单应回 200, 实际 {status}"
        assert b"ps1_ra" in body, "响应体应是 CSV 数据, 证明解码后参数被正常消费"


class TestFormatLevelOverflowMarkers:
    """A4-03 第二问: 载荷内也要有可判定标记, 不能只有 VOTable 有。"""

    def test_fits_carries_tapovr_header_keyword(self):
        """FITS: 截断位写进 BinTable 头卡 (TAPOVR), 读表的人在头卡里就能看到。"""
        pytest.importorskip("astropy.io.fits")  # 软依赖: 缺 astropy 时跳过而不是判失败
        result = serialize_result([{"ps1_ra": "180.0"}], "fits", overflow=True)  # 截断的 FITS 产物
        from astropy.io import fits  # 局部导入: 只这一条要读头卡

        header = fits.open(BytesIO(result.body))[1].header  # [1] 是 BinTable 扩展, 头卡挂在扩展上
        assert header.get("TAPOVR") is True, f"FITS 头卡缺 TAPOVR: 实际 {dict(header)}"

    def test_csv_result_carries_overflow_bit_out_of_band(self):
        """CSV: 体内不插注释行, 截断位由 SerializedResult.overflow 外带给调用方挂头。

        刻意断"载荷里没有 `#` 注释行": 严格 CSV 解析器会把那行读成一条列数
        不符的数据行, 凭空多出一行 NaN —— 用一个假信号换一个真故障。位走
        响应头才是对 CSV 解析器无害的形态。
        """
        result = serialize_result([{"ps1_ra": "180.0"}], "csv", overflow=True)
        assert result.overflow is True, "截断位没外带: 调用方无处挂头, 异步面必然丢信号"
        assert b"#" not in result.body, "CSV 体内不得插注释行: 会污染严格解析器的数据行"

    def test_clean_csv_result_carries_no_overflow_bit(self):
        """负向对照: 未截断的 CSV 结果 overflow 位必须为 False。"""
        result = serialize_result([{"ps1_ra": "180.0"}], "csv", overflow=False)
        assert result.overflow is False, "未截断却置位: 客户端会把完整结果误当残缺"


class _FakeResponse:
    """假响应: 只提供 raise_for_status 与 json, 供交换端点推导用例使用。"""

    def raise_for_status(self):
        """假成功: 端点推导的成败与状态码无关, 不引入无关的失败分支。"""

    def json(self):
        """回一个带 api_key 的载荷: 让 exchange 正常返回, 用例只关心 URL。"""
        return {"api_key": "k"}


class TestGatewayEndpointDerivation:
    """A4-04: 交换端点由 urljoin 推导, 不再用 base_url[:-4] 定长切片。"""

    @pytest.mark.parametrize("base", ["http://127.0.0.1:8000/tap", "http://127.0.0.1:8000/tap/"])
    def test_plain_tap_base_url_derives_gateway_root(self, base):
        """标准 /tap 端点 (含尾斜杠) 推出网关根下的交换路径。"""
        from src.tap.client import _gateway_api_url  # 局部导入: 测的是端点推导这个纯函数

        assert _gateway_api_url(base.rstrip("/"), "/api/v1/auth/nadc/token") == "http://127.0.0.1:8000/api/v1/auth/nadc/token"

    def test_subpath_base_url_does_not_produce_double_slash(self):
        """带子路径的 base_url (.../tap/sync) 不得拼出 .../tap//api/v1/... 这类双斜杠端点。"""
        from src.tap.client import _gateway_api_url  # 局部导入: 测的是端点推导这个纯函数, 不必构造真客户端

        endpoint = _gateway_api_url("http://127.0.0.1:8000/tap/sync", "/api/v1/auth/nadc/token")  # 完整 sync 端点作输入: 正是定长切片失灵的那种形态
        assert "//" not in urlparse(endpoint).path, f"路径里出现双斜杠: {endpoint}"
        assert endpoint == "http://127.0.0.1:8000/api/v1/auth/nadc/token"

    def test_exchange_nadc_token_posts_to_derived_endpoint(self):
        """经 BestTapClient 走一遍: 真实发出的 URL 必须是推导出来的那个, 不含双斜杠。"""
        from src.tap.client import BestTapClient  # 局部导入: 只这一条要构造真客户端

        posted: list[str] = []  # 记录实际发出的 URL: 替身只看 URL 够验, 不必造响应体

        class _FakeFactory:
            """假 service_factory: 只需接住构造参数, 换 token 不走它。"""

            def __call__(self, base_url, session=None):
                """接住 TAPService 的构造位置参数, 替身不碰端点推导那条路。"""
                self.base_url = base_url  # 原样存下: 构造接线本身不在本条断言范围内
                self.session = session  # 同上: 会话由客户端自己持, 替身只是引用
                return self  # 返回自身: search/download 若被调也不会 AttributeError

        client = BestTapClient(mode="local", local_url="http://127.0.0.1:8000/tap/sync", service_factory=_FakeFactory())  # 给完整 sync 端点: 正是切片推导失灵的那种输入
        client.session.post = lambda url, **kwargs: posted.append(url) or _FakeResponse()  # 换掉真实网络调用: 只验端点拼接
        client.exchange_nadc_token("upstream-token")  # 触发端点推导
        assert len(posted) == 1, f"应只发一次交换请求, 实际 {len(posted)} 次"
        assert "//api" not in posted[0], f"端点被拼成双斜杠: {posted[0]}"
        assert posted[0].endswith("/api/v1/auth/nadc/token"), f"端点路径不对: {posted[0]}"
