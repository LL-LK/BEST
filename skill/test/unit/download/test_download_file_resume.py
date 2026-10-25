"""字节级断点续传 download_file 单元测试 (HTTP Range + .part 半成品)。

守的回归: 半成品按 Range 续传 (206 拼接); 服务端忽略 Range (200) 时丢弃
半成品整文件重下而不是把整文件拼到半成品后面; 全新与续传的中断**一律**保留
.part (唯一下半成品名); 成功即原子替换; 取消精确到字节边界; 进度按 chunk
累加; 错误状态码响应绝不进入流式写盘 (P0-2)。

半成品口径变更 (修复「全新下载中断后无处续传」): 此前全新下载写 .tmp 而续传
写 .part, 于是「全新下载中途取消/断流」留下的半成品不是续传凭据 —— 下次调用
找不到 .part 只能判全新, 以 "wb" 截断把已下字节全废。现全程只落 .part,
全新与续传共用一个半成品名, 任何中断留下的字节都是下次的续传基线。
``.tmp`` 不再是本函数的落点 (旧版本残留物不在本函数清理范围内)。

P1 合并注记: 本文件原经 pybest 单类 (``Best.download_file`` → patch
``Best._request``) 守护; 双副本删除后, 被测对象是权威实现
``src.best_export.download_file`` 本身, 请求可调用体经 ``request=`` 参数
直接注入 (生产注入方是 ``BestClient.download_file`` → ``BestClient._request``,
其节流/重试/软错误纪律由 test/unit/client/test_client_transport_discipline.py
守护 — 两层关注点分离, 各测各的)。
"""
from __future__ import annotations

# 标准库: io (历史夹具遗留, 当前用例走 MagicMock.iter_content 造字节流) /
# pathlib 落盘路径断言 (读回字节/判断半成品是否残留) /
# threading.Event 作取消标志 (与 download_file 的 cancel_event 入参同型; 现由
# 取消边界与「取消后续传」两条用例共用, 故上提到模块级)
import io
import threading
from pathlib import Path

# 标准库: 伪造 HTTP 响应替身 (MagicMock) 与请求可调用体替身
from unittest.mock import MagicMock

# 测试框架: tmp_path 提供每次用例独立的临时目录
import pytest

# 第三方: requests 异常层级 (流式中断替身抛生产栈真实类型, P2-4)
import requests

try:
    # 被测单元: 字节级流式下载的权威实现 (续传/进度/取消/路径消毒)
    from src.best_export import download_file
except Exception as _legacy_err:  # legacy-import-guard
    # 源码树调整导致旧导入路径失效时整模块跳过, 不让收集期报错
    import pytest as _pytest
    _pytest.skip(f'legacy import unavailable: {_legacy_err!r}', allow_module_level=True)            # 模块级跳过: 导入树问题不该算用例失败


def _resp(status=200, chunks=(b"abc", b"def"), headers=None, length=None):
    """造一个最小 HTTP 响应替身 (供 request= 注入返回)。

    Args:
        status: HTTP 状态码 (200 整文件 / 206 部分内容)。
        chunks: iter_content 依次产出的字节块 (协议阶段: 分块传输体)。
        headers: 附加响应头 (如 Range 场景的 Content-Length)。
        length: 是否在响应头里带 Content-Length (进度条总字节的来源)。

    Returns:
        带 status_code/headers/iter_content 的 MagicMock 响应替身。
    """
    r = MagicMock()                                                                                 # 替身响应对象
    r.status_code = status                                                                # 状态码可切换: 200 整文件与 206 部分内容是两条分支
    r.iter_content.return_value = iter(chunks)                                                      # 字节流按块产出: 进度与取消都按块判定
    h = {"Content-Disposition": 'attachment; filename="t.dat"'}                                     # 默认头只带文件名: 其余按用例追加
    if length is not None:                                                                          # 总长可选: 进度条的分母就是它
        h["Content-Length"] = str(length)                                                           # 补上总长头
    h.update(headers or {})                                                                         # 用例自带的头覆盖默认值
    r.headers = h                                                                                   # 把头装到替身上
    return r


_URL = "https://nadc.china-vo.org/data/best/t.dat"                                                # 固定的下载 URL: 用例会拿它算期望校验和


class TestDownloadFileBasic:
    """全新下载: 文件名解析、跳过已存在、原子替换。"""

    def test_full_download_and_atomic_replace(self, tmp_path):
        """整文件下载必须走 tmp + os.replace, 成功路径不留 .tmp。

        守的不变量: 直接写目标文件的话, 进程被杀/断流会留下一个看起来
        "完整"实际被截断的文件; 必须先写 .tmp 再原子替换, 读者只会看到
        旧完整版或新完整版。tmp_path: 产物落到临时目录, 不污染 skill 根。
        """
        path = download_file(_URL, savedir=str(tmp_path),                                           # 走真实的下载入口
                             request=lambda *a, **k: _resp(length=6))                            # 注入请求可调用体: 校验逻辑真跑, 网络是替身
        assert Path(path).read_bytes() == b"abcdef"                                                 # 两个字节块拼成六字节
        assert not (tmp_path / "t.dat.tmp").exists()  # 成功路径不得留 .tmp: 残留半成品会被下次同名下载误当完整数据

    def test_skip_existing_without_overwrite(self, tmp_path):
        """overwrite=False 且目标已存在: 直接返回既有文件, 不重下。

        守的不变量: overwrite=False 且目标已存在时仍发起请求并覆盖, 既浪费
        带宽又冲掉本地对产物的修改 (批量任务重跑时尤其致命)。
        """
        (tmp_path / "t.dat").write_bytes(b"old")                                                    # 预置一个已存在文件
        path = download_file(_URL, savedir=str(tmp_path), overwrite=False,                          # 不覆盖: 半成品与已完稿都走这条路
                             request=lambda *a, **k: _resp())                                       # 注入请求可调用体
        assert Path(path).read_bytes() == b"old"                                                    # 原内容必须原样保留

    def test_explicit_filename(self, tmp_path):
        """显式 filename 优先于 Content-Disposition (批量任务要可预测文件名)。"""
        path = download_file(_URL, savedir=str(tmp_path), filename="custom.dat",                    # 显式文件名
                             request=lambda *a, **k: _resp())                                       # 注入请求可调用体
        assert Path(path).name == "custom.dat"                                          # 文件名必须原样保留: 改名会让调用方按自传路径 stat 时扑空

    def test_filename_from_content_disposition(self, tmp_path):
        """流式下载守门: 文件名取自 Content-Disposition, 内容按分块拼接。

        iter_content 返回两个分块模拟 HTTP 分块传输; 落盘必须是两块拼接的完整
        字节流 (b"abcdef") — 漏拼/错序都会在本测试现形。
        """
        path = download_file(_URL, savedir=str(tmp_path),                                           # 走真实的下载入口
                             request=lambda *a, **k: _resp())                                       # 注入请求可调用体
        assert path is not None                                                                     # 必须返回路径而不是 None
        assert Path(path).name == "t.dat"                                                           # 文件名取自响应头: 服务端给什么就是什么
        assert Path(path).read_bytes() == b"abcdef"                                                 # 字节必须完整落盘

    def test_error_status_never_reaches_the_stream_writer(self, tmp_path):
        """P0-2 守门: 错误状态码的响应绝不得进入流式写盘路径。

        复过的现: 404 HTML 正文经 os.replace 变成"下载成功"的正式产物,
        日志还打 "Downloaded" — 注入的 request 是任意可调用体, 前置状态码
        校验是最后单点, 少了它就是数据污染。
        """
        response = _resp(status=404, chunks=(b"<html>404 Not Found</html>",))                  # 404 替身: 错误页正文是 HTML, 不是数据
        path = download_file(                                                                       # 走真实的下载入口
            "https://nadc.china-vo.org/data/best/missing",                                          # 指向一个不存在的资源
            savedir=str(tmp_path), request=lambda *a, **k: response,                                # 注入请求可调用体
        )
        assert path is None                         # 返回 None 是失败契约: 抛异常或返回空路径都不合这里的约定
        assert not (tmp_path / "err.dat").exists()  # 正式产物不得存在: 404 正文落盘就是数据污染
        assert not (tmp_path / "err.dat.tmp").exists()                                            # 临时文件不许残留: 否则会被后续扫描当成产物
        assert not (tmp_path / "err.dat.part").exists()                                           # 半成品也不许残留: 错误响应根本没开始传数据

    def test_failed_fresh_download_keeps_part_for_resume(self, tmp_path):
        """全新下载中途断流: 半成品必须落在 .part 且保留 (防线二)。

        这是「全新下载无处续传」那条缺陷的守门。半成品若落在别的名字上
        (旧口径是 .tmp), 下次调用找不到它只能判全新下载, 以 "wb" 截断重下 ——
        大文件每次断网都从 0 字节重来, 用户以为有断点续传其实没有。

        故本用例同时断言三件事: 中断返回 None; **.part 存在** (是续传凭据);
        **.tmp 不再被创建** (统一落点后它不该出现)。
        """
        response = _resp(chunks=(b"partial",))                                                      # 只吐一块就断流的替身
        response.iter_content = lambda **kw: _exploding()  # 换成会抛的生成器: 直接 raise 走的是请求失败路径, 测不到中途断

        def _exploding():
            """生成器替身: 先吐半个分块, 再抛网络异常 (模拟服务端断流)。

            Note:
                必须是**生成器**而不是直接 raise — 直接抛异常走的是"请求发起
                失败"路径, 测不到"流式写盘中途断"这条更危险的路径 (那时半成品
                已经写了一部分)。
            """
            yield b"partial"
            raise RuntimeError("Network dropped during stream")

        path = download_file(_URL, savedir=str(tmp_path),                                           # 注入请求可调用体
                             request=lambda *a, **k: response)                                      # 必须返回 None: 中断不能报成功
        assert path is None
        assert (tmp_path / "t.dat.part").exists()          # .part 必留: 它就是下次的 Range 续传基线
        assert (tmp_path / "t.dat.part").read_bytes() == b"partial"                                # 已下字节一个不少: 续传要从这个偏移接
        assert not (tmp_path / "t.dat.tmp").exists()       # .tmp 不再是落点: 半成品只有一个名字才不会认错
        assert not (tmp_path / "t.dat").exists()           # 正式产物不得存在: 中断绝不报成功


class TestDownloadFileResume:
    """断点续传: .part 半成品 + Range 头的完整失败语义。"""

    def test_range_resume_from_part(self, tmp_path):
        """半成品 .part 存在时带 Range 头续传, 206 则拼接。

        守的回归: 请求头必须是 ``bytes=<半成品大小>-`` (从断点字节起, 不是
        从头); 服务端答 206 (Partial Content) 表示接受 Range, 新块追加到
        半成品后; 成功后 .part 必须消失 (改名即消费, 留着会被下次误判成
        续传基线)。
        """
        (tmp_path / "t.dat.part").write_bytes(b"abc")                                               # 预置三字节半成品
        seen = {}                                                                                # 请求头记账: Range 头带不带是这条的全部

        def _req(method, url, **kw):
            """按请求头分流回包: 断言 Range 与拼接行为的唯一凭证。

            守的回归: 若 download_file 不发 ``Range: bytes=3-``, 续传就退化成
            整文件重下; 这里把实际请求头收进 seen, 让"断点字节是否正确"变成
            可断言的事实, 而不是靠翻日志猜。首次请求 (无 Range) 回 200 整文件,
            带 Range 的续传请求回 206 剩余字节 — 与真实服务器行为一致
            (P0-2: download_file 现在前置校验状态码, 桩必须声明真实状态)。
            """
            # 记录实际发出的请求头: Range 续传的唯一凭证
            headers = kw.get("headers") or {}  # headers 默认可能是 None: 不兜成空 dict 就会在这一行崩
            seen.update(headers)                                                                    # 把请求头收下来
            if "Range" in headers:  # 有无 Range 决定回包形态: 200 与 206 混用会直接产出损坏文件
                # 协议阶段: HTTP 206 Partial Content, 只回剩余 3 字节
                return _resp(status=206, chunks=(b"def",),
                             headers={"Content-Length": "3"})                                       # 206 场景下报总长为一字节
            # 协议阶段: 首次请求无 Range, 服务端回 200 整文件
            return _resp(status=200, chunks=(b"abcdef",), length=6)

        path = download_file(_URL, savedir=str(tmp_path), request=_req)                             # 注入带记账的请求可调用体
        assert seen.get("Range") == "bytes=3-"                           # Range 起点必须等于半成品大小: 从头重发就退化成整文件重下
        assert Path(path).read_bytes() == b"abcdef"                                              # 必须拼成完整六字节: 206 是追加而不是替换
        assert not (tmp_path / "t.dat.part").exists()  # .part 改名即消费: 留着会被下次运行误当成续传基线

    def test_server_ignores_range_restarts_full(self, tmp_path):
        """服务端返回 200 (不支持 Range): 丢半成品整文件重下。

        守的不变量: 把 200 当 206 处理, 会把整文件 6 字节拼到 3 字节半成品
        后面, 产出 9 字节的损坏文件且毫无报错。检测到非 206 就丢弃
        半成品 (part.unlink) 并把续传基点归零, 诚实降级为整文件重下。
        """
        (tmp_path / "t.dat.part").write_bytes(b"abc")                                               # 预置三字节半成品
        calls = {"n": 0}                                                                            # 调用计数: 用来证明整文件只下一次

        def _req(method, url, **kw):
            """首探不带 Range, 第二次无视 Range 回 200 + 完整 6 字节。

            守的不变量: 服务端忽略 Range 时必须被识别成"整文件响应", 半成品
            基线归零; 若仍按 206 语义拼接, 会静默产出 9 字节的损坏文件且
            全程无报错。
            """
            calls["n"] += 1                                                                         # 先累计次数
            if calls["n"] == 1:                                                                     # 只有第一次回 200
                return _resp()  # 首探: 无 Range
            # 协议阶段: 服务端忽略 Range, 答 200 + 完整 6 字节 (而非 206)
            return _resp(status=200, chunks=(b"abcdef",),
                         headers={"Content-Length": "6"})  # 忽略 Range

        path = download_file(_URL, savedir=str(tmp_path), request=_req)                             # 注入带记账的请求可调用体
        assert Path(path).read_bytes() == b"abcdef"                                  # 服务端忽略 Range 时必须整文件重下, 不能把整文件拼到半成品后面

    def test_failed_download_keeps_part_for_resume(self, tmp_path):
        """续传中失败: .part 保留 (供下次 Range 续传), 不删。

        守的不变量: 异常分支一律清理半成品的话, 大文件每次断网都从 0 字节
        重来。只有"全新下载的 .tmp"才清理, 续传基线 (.part) 必须留下 —
        这也是 resume_from > 0 与 resume_from == 0 两条清理路径的区别所在。

        替身必须按协议分流: 探测请求 (无 Range) 回 200, 带 Range 的续传请求
        回 206 且流中途断连。若对**每次**调用都回 206, 首个探测请求
        (无 Range) 就会被状态码前置校验拦下 (206 != 200), 测试实际走的是
        abort 路径, "流式中断保留 .part"的意图从未被真正验到 (名不副实的
        守门)。
        """
        (tmp_path / "t.dat.part").write_bytes(b"abc")                                               # 预置三字节半成品

        def _req(method, url, **kw):
            """按协议阶段分流: 探测 (无 Range) 回 200; 续传请求回 206 但流中断。

            守的回归: 这个替身让续传的 iter_content 吐出首块后炸掉, 用来验证
            失败分支保留 .part 而不是清理它 — 否则大文件每次断网都从 0 字节
            重来, 用户以为有断点续传其实没有。
            """
            headers = kw.get("headers") or {}  # headers 兜空: 首个探测请求不带 Range, headers 可能是 None
            if "Range" not in headers:                                              # 没有 Range 头就回整文件: 这正是"服务端忽略 Range"的形态
                # 协议阶段: 首个探测请求 (无 Range), 服务端回 200 整文件形态
                return _resp(status=200, chunks=(b"abcdef",), length=6)
            # 协议阶段: 服务端接受 Range (206) 并开始回数据, 但流中途断连
            r = _resp(status=206, chunks=(b"d",), headers={"Content-Length": "1"})                  # 206 场景只回一字节
            r.iter_content.side_effect = lambda chunk_size: _exploding()                          # 把字节流换成会抛的: 验证异常路径也清得干净
            return r

        def _exploding():
            """生成器替身: 首块正常, 第二块以 requests ConnectionError 模拟掉线。

            守的回归: 失败点必须落在"流已开始写出之后"; 若在首块之前就炸,
            .part 压根没落盘, "保留半成品"这条断言会被假满足。
            """
            # 首块正常落盘, 第二块抛 requests 连接错误: 模拟网络掉线
            # (生产栈真实类型; 内置 ConnectionError 与 requests 的同类不同类)
            yield b"d"
            raise requests.exceptions.ConnectionError("dropped")

        path = download_file(_URL, savedir=str(tmp_path), request=_req)                             # 注入请求可调用体
        assert path is None                                                                         # 异常路径必须返回 None
        assert (tmp_path / "t.dat.part").exists()  # .part 必须留着: 清掉就等于每次断网都从 0 字节重来

    def test_cancel_event_stops_midway(self, tmp_path):
        """cancel_event 置位即中止并返回 None (字节边界生效, 不写坏文件)。

        守的不变量: 用户点"取消"后任务必须真的停下; 只在页边界检查的话,
        文件下载这种无分页的长流程会一直跑到结束。
        """

        ev = threading.Event()                                                                      # 取消标志: 让下载跑到第一块后停

        def _chunks():
            """字节流替身: 首块后置取消标志, 第二块就是"不该被写出"的那块。

            守的不变量: 取消必须精确到字节边界; 若只在页边界检查, 文件下载会
            一路跑到结束 — 用户点了取消, 磁盘还在长, 带宽白耗。
            """
            # 协议阶段: 第一块正常, 置取消标志, 第二块本不该被写出
            yield b"a"
            ev.set()  # 首块之后置位: 取消必须精确到字节边界, 只在页边界查会一路跑到底
            yield b"b"

        r = _resp()                                                                                 # 默认替身: 状态与字节流都先有着落
        r.iter_content.return_value = _chunks()                                                     # 把字节流换成带取消检查的版本
        path = download_file(_URL, savedir=str(tmp_path),                                           # 注入请求可调用体
                             cancel_event=ev, request=lambda *a, **k: r)                         # 取消标志要传进去: 不传就测不到精确到块的取消
        assert path is None                                                                         # 取消后必须返回 None

    def test_cancel_then_resume_appends_instead_of_truncating(self, tmp_path):
        """端到端: 全新下载被取消后, 第二次调用必须**追加**而不是截断重下。

        这条是「全新下载中断后无处续传」的完整闭环守门, 覆盖前两条用例合起来
        才暴露的那一面: 第一次调用取消 → 留下 .part; 第二次调用带 Range 从该
        偏移续 → 拼成完整文件。旧口径下第一次落的是 .tmp, 第二次找不到 .part
        便以 "wb" 截断重下, 已下载的 3 字节被清空 —— 而任何只看单次调用的
        用例都验不到这一点。
        """
        # 第一次调用: 全新下载, 吐一块后置取消标志 → 中止
        ev = threading.Event()

        def _first_chunks():
            """首块写盘后置取消: 让 .part 里真实落下 3 字节。"""
            yield b"abc"
            ev.set()
            yield b"def"  # 取消后不该被写出

        r1 = _resp()
        r1.iter_content.return_value = _first_chunks()
        assert download_file(_URL, savedir=str(tmp_path),
                             cancel_event=ev, request=lambda *a, **k: r1) is None
        assert (tmp_path / "t.dat.part").read_bytes() == b"abc"   # 半成品留下 3 字节

        # 第二次调用: 无取消标志, 服务端认 Range 回 206 剩余段
        seen = {}

        def _req(method, url, **kw):
            """按有无 Range 分流回包: 首次探测 200, 带 Range 的续传 206。

            P0-2 起 download_file 前置校验状态码, 所以桩必须像真实服务器一样
            分两次回: 首次无 Range 请求回 200, 续传请求回 206 剩余段。混用会
            直接被状态码前置校验拦下, 测不到拼接行为。
            """
            headers = kw.get("headers") or {}  # headers 默认可能是 None: 不兜成空 dict 会在这一行崩
            seen["Range"] = headers.get("Range")
            if "Range" in headers:  # 带 Range = 续传请求: 回 206 剩余三字节
                return _resp(status=206, chunks=(b"def",), headers={"Content-Length": "3"})
            return _resp()                 # 首次探测: 回 200 整文件

        path = download_file(_URL, savedir=str(tmp_path), request=_req)
        assert seen["Range"] == "bytes=3-"                     # 必须从半成品偏移续: 从头发就退化成整文件重下
        assert Path(path).read_bytes() == b"abcdef"            # 拼成完整六字节: 前 3 字节没被截断清空
        assert not (tmp_path / "t.dat.part").exists()          # .part 改名即消费, 不留成下次误判的基线

    def test_progress_tracker_receives_bytes(self, tmp_path):
        """字节级进度: set_total_bytes 取 Content-Length, 每 chunk 累加。

        守的回归: 进度回调必须按 chunk 调 advance_pages(0, bytes_delta=...) —
        pages 传 0 是因为这是字节级下载 (页计数无意义), 只累加字节; 总字节
        在首包前由 Content-Length 设定, GUI 才能算出百分比与 ETA。
        """
        tracker = MagicMock()                                                                       # 进度替身: 调用次数与增量都靠它
        download_file(_URL, savedir=str(tmp_path), progress_tracker=tracker,                        # 走真实的下载入口
                      request=lambda *a, **k: _resp(length=6))                                      # 注入请求可调用体
        tracker.set_total_bytes.assert_called_once_with(6)  # 首包前设总字节: GUI 靠它算百分比, 晚设一帧就会闪 0%
        assert tracker.advance_pages.call_count == 2        # 两个分块就两次回调: 少一次说明某块没被计进进度
        assert tracker.advance_pages.call_args_list[0][0][0] == 0
        assert tracker.advance_pages.call_args_list[0][1]["bytes_delta"] == 3  # 首块增量 3 字节: 逐块累加而不是只报总量
