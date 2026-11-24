"""H1 修复回归网 — 交叉匹配与多波段测光的「失败不得伪装成无数据」。

三条互不依赖的契约, 全部对应 G1 实跑证实的问题 (证据见
temp/AUDIT-G1-src-modules.md 的 LIVE-4a/4b/4c 与 LIVE-2b):

- **H1-01** 逐点交叉匹配: 查询失败必须与「无匹配」可分。站点一次软错误
  (故意错 base_url 前缀 → 底层 ``E_NO_SQLID``, 会话压根没建成) 绝不能变成
  ``success=True / returned=0 / n_errors=0`` 的信封 —— 那是「整批静默归零」。
- **H1-02** 多波段取源: 查询失败走**独立分支 + 独立日志文案**。断言打在
  日志文本上, 不只看返回值: 早先的 bug 恰恰是「返回了容器、日志说了假话」。
- **H1-03** 0 点导出: 缺省拒绝落盘 (不产出仅表头文件), 显式
  ``allow_empty=True`` 才放行, 且行状态复用 ``src.download_artifacts`` 的
  ``row_status`` 词表 (ok/empty), 不另造第二套 empty 语义。

每个用例都成对钉住**两个方向** (失败不得伪装成空 / 真空区不得被误判成
失败): 只钉单向的话, 「把所有失败一律报成失败」那种过度 fail-closed 也能
骗过回归网。

全部离线: ``cone_search`` 被打桩, 零网络; 写操作只落 ``tmp_path``。
"""
from __future__ import annotations

import logging  # 标准库: caplog 级别判定需要 logging.ERROR/WARNING 常量

# 第三方: pytest (raises 断言负路径, caplog 抓日志文本, monkeypatch 换模块依赖)
import pytest

# 本地: 被测门面与数据模型 (三个被测对象都走 import 后的真实类, 不断言别家改动的列序)
from src.client import BestClient
from src.crossmatch import BestCrossMatch
from src.models import BestQueryResult, BestSource
from src.multiband_photometry import BestMultiBandPhotometry
from src.scripts import best_multiband_export as export_mod

# G1-01 复现用的失败信封: 与实跑一致 —— HTTP 200 但响应体是软错误页,
# 客户端判 success=False 且带分类码 E_NO_SQLID (client.py 的两阶段查询在
# 第一阶段没拿到 sqlid 时就是这个形态)。
_SOFT_FAILURE = BestQueryResult(  # 模块级共享夹具: 三处用它复现同一种站点侧失败
    success=False,
    total_count=0,
    returned_count=0,
    error="E_NO_SQLID: No sqlid found — the query may have returned no results or the form was invalid",
    error_code="E_NO_SQLID",
)


class TestH101CrossMatchFailureIsNotEmpty:
    """H1-01: 逐点交叉匹配的失败信封必须与「真空区」可分。"""

    def test_all_coordinates_failed_is_never_reported_as_success(self):
        """全部坐标查询失败 → 信封必须 success=False 并带码, 绝不报「0 匹配 0 错误」。

        验证的行为: ``cone_search`` 全部返回 ``success=False/E_NO_SQLID`` 时,
        ``crossmatch_coords`` 返回 ``success=False`` + ``error_code="E_NO_SQLID"``
        + ``n_errors=2``。为什么重要: 修复前这里返回
        ``success=True, error_code=None, returned=0, n_errors=0``, 调用方
        读到的是「这些坐标没有对应源」而不是「查询压根没建成」—— 铁律 5
        明令禁止的 fail-open, 且整批匹配静默归零。
        """
        client = BestClient(rate_limit=0)  # 限流归零: cone_search 已打桩, 不该再等节流
        xm = BestCrossMatch(client)  # 真实门面: 信封语义住在 crossmatch_coords 里
        with pytest.MonkeyPatch.context() as mp:  # 局部打桩: 出上下文即复原, 不污染本模块其它用例
            mp.setattr(client, "cone_search", lambda **kw: _SOFT_FAILURE)  # 每次调用都失败
            result = xm.crossmatch_coords([180.0, 181.0], [30.0, 31.0])  # 两个坐标全灭

        # 核心断言: 三件套不得同时成立 (这正是原 bug 的形态)
        assert not (result.success and result.returned_count == 0 and result.query_params.get("n_errors") == 0), (
            "整批查询失败被报成 success=True/returned=0/n_errors=0: "
            "调用方会把站点故障读成「这批坐标没有对应源」"
        )
        assert result.success is False  # 0 行交付不得配一个「成功」信封
        assert result.error_code == "E_NO_SQLID"  # 分类码必须上浮: 调用方按码分支, 不嗅文本
        assert result.query_params["n_errors"] == 2  # 两个坐标都失败, 失败数必须如实计
        assert "E_NO_SQLID" in (result.error or "")  # 可读原因里也带码: 排障不必翻 query_params

    def test_partial_failure_reports_both_counts(self):
        """部分失败: 交出已取回的真实行, 但 error_code 与失败计数必须非空。

        验证的行为: 3 个坐标里 1 个命中、1 个真空、1 个查询失败 →
        ``success=True`` (行可用), ``returned_count=1``, ``n_errors=1``,
        ``error_code`` 取失败坐标的码, ``error`` 明写「1/3 坐标查询失败」。

        **语义取舍 (为什么部分失败不报 success=False)**: 整批判失败等于把
        **已经取回的真数据**也一并丢掉, 那才是二次造假 —— 丢数据与说假话都是
        fail-open, 只是方向不同。但报 ``success=True`` 也不等于「这批都查到了」,
        所以 ``error_code`` 在此**必置位**: 契约是「``success`` 表示取回的行
        可用, 完整性看 ``error_code`` / ``n_errors``」。绝不允许的只有一件事:
        把失败的坐标当成 0 命中 (那正是原 bug)。
        """
        client = BestClient(rate_limit=0)  # 限流归零: 三个结局全由下面的分派表给
        xm = BestCrossMatch(client)  # 门面同上: 换 client 构造这一处即可
        hit = BestQueryResult(success=True, sources=[BestSource(source_id="HIT", ra=180.0, dec=30.0)])
        by_ra = {180.0: hit, 181.0: BestQueryResult(success=True, sources=[]), 182.0: _SOFT_FAILURE}  # 三种结局各一坐标
        with pytest.MonkeyPatch.context() as mp:  # 局部打桩: 分派表不外泄
            mp.setattr(client, "cone_search", lambda ra, **kw: by_ra[ra])  # 按 ra 分派
            result = xm.crossmatch_coords([180.0, 181.0, 182.0], [30.0, 31.0, 32.0])

        assert result.success is True  # 命中的那一行是真的, 不用为别人的失败买单
        assert result.returned_count == 1  # 交出 1 行
        assert result.query_params["n_errors"] == 1  # 失败的坐标必须被计数, 不许混进 n_matched
        assert result.query_params["n_matched"] == 1
        assert result.error_code == "E_NO_SQLID"  # 部分失败同样给码: 调用方据此知道这批**不完整**
        assert "1/3" in (result.error or "")  # 成功/失败两数都外带, 调用方不必自己减

    def test_genuine_empty_sky_is_still_a_success(self):
        """真空区 (查询成功、0 命中) 必须仍是合法成功结果 —— 不得被过度 fail-closed。

        验证的行为: ``cone_search`` 全部 ``success=True`` 但无源时, 信封是
        ``success=True, error_code=None, n_errors=0, returned=0``。为什么重要:
        这条与前两条成对: 只钉「失败不得报成功」的话, 把「所有 0 命中一律判失败」
        那种改法也能全绿 —— 而那会把「这个天区真的没有源」这个合法科学结论
        变成错误, 是另一种 fail-closed 过头。
        """
        client = BestClient(rate_limit=0)  # 限流归零: 本例只关心空结果不被升级成失败
        xm = BestCrossMatch(client)  # 门面同上: 断言全在信封上
        empty = BestQueryResult(success=True, sources=[])  # 查询成功但锥区内无源
        with pytest.MonkeyPatch.context() as mp:  # 局部打桩: 空结果信封是本例唯一的输入
            mp.setattr(client, "cone_search", lambda **kw: empty)  # 每次都成功但没源
            result = xm.crossmatch_coords([180.0, 181.0], [30.0, 31.0])

        assert result.success is True  # 查询确实完成了, 0 命中是合法结果
        assert result.error_code is None  # 没有失败就没有码: 真空区不是错误
        assert result.query_params["n_errors"] == 0
        assert result.returned_count == 0


class TestH102QueryFailureMustNotSayNoSourceFound:
    """H1-02: 取源失败走独立分支, 日志里不得出现 "No source found"。"""

    def test_query_failure_raises_and_never_logs_no_source_found(self, caplog):
        """锥形检索失败 → 抛 RuntimeError, 且日志里绝不出现 "No source found"。

        验证的行为: ``cone_search`` 返回 ``success=False`` 时, ``from_position``
        抛 ``RuntimeError`` (消息带错误码), 日志级别为 ERROR 且含
        ``E_NO_SQLID``, **不含** "No source found"。为什么重要: 修复前两者
        都被如实误报成 "No source found at RA=10.6847, Dec=41.2687" ——
        会话压根没建成, 结论与日志双双与事实相反, 下一个查日志的人会被带偏。
        断言打在日志文本上而非返回值, 因为原 bug 的危害正在于「说了假话」。
        """
        client = BestClient(rate_limit=0)  # 限流归零: 失败信封由打桩给, 无真实请求
        with pytest.MonkeyPatch.context() as mp:  # 局部打桩: 只换这一条出口
            mp.setattr(client, "cone_search", lambda **kw: _SOFT_FAILURE)  # 站点侧软错误
            with caplog.at_level(logging.DEBUG, logger="src.multiband_photometry"):  # 抓本模块 logger 的全部记录
                with pytest.raises(RuntimeError) as excinfo:
                    BestMultiBandPhotometry.from_position(client, 10.6847, 41.2687)  # G1 LIVE-4c 的同一坐标

        assert "No source found" not in caplog.text, (
            f"查询失败被说成了「无源」: {caplog.text!r}"
        )
        assert "E_NO_SQLID" in caplog.text  # 失败分支必须打出错误码
        assert "E_NO_SQLID" in str(excinfo.value)  # 异常消息同样带码: 调用方不装日志也能判
        assert [r.levelname for r in caplog.records if r.levelno >= logging.ERROR]  # 至少一条 ERROR 记录

    def test_query_failure_never_yields_a_zero_point_container(self):
        """查询失败不得返回 0 点容器 —— 那会被导出层落成「仅表头的成功空文件」。

        验证的行为: 失败时 ``from_position`` 抛错而不是构造空容器; 导出层的
        0 点闸 (H1-03) 因此拿不到「看起来成功」的空容器可落盘。
        """
        client = BestClient(rate_limit=0)  # 限流归零: 失败信封由打桩给
        with pytest.MonkeyPatch.context() as mp:  # 局部打桩: 同上, 只换 cone_search
            mp.setattr(client, "cone_search", lambda **kw: _SOFT_FAILURE)
            with pytest.raises(RuntimeError):  # 显式失败即预期: 返回空容器才是 bug
                BestMultiBandPhotometry.from_position(client, 10.6847, 41.2687)

    def test_genuine_no_match_still_logs_no_source_found(self, caplog):
        """真空区 (查询成功、0 命中) 仍返回 0 点容器并打 "No source found"。

        验证的行为: ``success=True`` + ``sources=[]`` 时不抛错, 容器
        ``n_points==0`` 且 source_id 退化为 ``POS_<ra>_<dec>``, 日志里**确实**
        出现 "No source found"。为什么重要: 与前两条成对 —— 只有把失败摘出去
        之后, 这句文案才重新成为「真的查过且真的没有」的可信信号; 修复前它是
        一句会骗人的万能话术。
        """
        client = BestClient(rate_limit=0)  # 限流归零: 空结果信封是本例唯一的输入
        empty = BestQueryResult(success=True, sources=[])  # 查询成功, 锥区内无源
        with pytest.MonkeyPatch.context() as mp:  # 局部打桩: 保证零网络
            mp.setattr(client, "cone_search", lambda **kw: empty)  # 每次都成功但没源
            with caplog.at_level(logging.DEBUG, logger="src.multiband_photometry"):  # 抓本模块 logger
                lc = BestMultiBandPhotometry.from_position(client, 10.0, -30.0)  # G1 LIVE-2b 的空天区坐标

        assert lc.n_points == 0  # 真空区是合法科学输出, 不该抛错阻断批处理
        assert lc.source_id == "POS_10.0000_-30.0000"  # 合成 ID 记录检索位置, 便于回溯
        assert "No source found" in caplog.text  # 这句文案只属于「真·无源」这一支


class TestH103ZeroPointExportIsNotSuccess:
    """H1-03: 0 点容器不得被落成「仅表头文件 + 导出成功」。"""

    def test_zero_point_container_refuses_csv_and_json_without_writing(self, tmp_path):
        """0 点容器缺省拒绝导出, 且**不产出任何文件**。

        验证的行为: ``to_csv`` / ``to_json`` 对 0 点容器抛 ``RuntimeError``,
        目标文件不存在。为什么重要: 修复前两者都落一个仅表头的几十字节文件
        并返回其路径, 产物与「写坏的空文件」不可区分, 还会被计成导出成功
        (Q-29 反例)。**抛而不落盘**: 显式失败不留看起来完好的空壳。
        """
        empty = BestMultiBandPhotometry(source_id="POS_10.0000_-30.0000")  # 0 点容器: 查询成功但真空区
        for name, exporter in (("mbp.csv", empty.to_csv), ("mbp.json", empty.to_json)):
            target = tmp_path / name  # 两个出口都要挡: 只挡一个就是留下另一半缺口
            with pytest.raises(RuntimeError) as excinfo:
                exporter(str(target))  # 缺省不放行: 0 点容器不产出文件
            assert not target.exists(), f"{name} 仍被落盘: 仅表头文件与写坏的空文件不可区分"
            assert "0-point" in str(excinfo.value)  # 消息要指名真实原因, 便于调用方改调用方式

    def test_allow_empty_writes_file_and_marks_row_status_empty(self, tmp_path, caplog):
        """显式 allow_empty=True 才放行, 且落盘日志按 row_status=empty 标记。

        验证的行为: 放行后文件真的落盘, 日志含 ``row_status=empty``; 有数据
        时同一行日志是 ``row_status=ok``。为什么重要: 词表直接复用
        ``src.download_artifacts`` 的 ``STATUS_EMPTY``/``STATUS_OK`` (同一套
        ``ok``/``empty`` 语义), 复核者按状态判, 不靠文件大小猜 —— 与下载侧
        的 sidecar ``row_status`` 口径完全一致, 不造第二套 empty 语义。
        """
        empty = BestMultiBandPhotometry(source_id="POS_10.0000_-30.0000")  # 0 点容器, 显式要求留档
        with caplog.at_level(logging.INFO, logger="src.multiband_photometry"):  # 抓落盘那一条日志
            empty.to_csv(str(tmp_path / "empty.csv"), allow_empty=True)  # 显式留档
        assert (tmp_path / "empty.csv").exists()  # 显式要求就该给文件
        assert "row_status=empty" in caplog.text  # 状态显式外带, 0 行不只表现为「文件很小」

        point = BestSource(source_id="HIT", ra=10.0, dec=20.0, catalog="ps1", magnitudes={"r": 15.0})  # 单点单波段
        with caplog.at_level(logging.INFO, logger="src.multiband_photometry"):  # 同一 logger, 便于两态对照
            BestMultiBandPhotometry(source_id="HIT", points=[point]).to_csv(str(tmp_path / "ok.csv"))
        assert "row_status=ok" in caplog.text  # 有数据时同一行是 ok: 两个状态互斥且都可判

    def test_script_export_does_not_count_zero_point_as_success(self, tmp_path, monkeypatch):
        """导出脚本遇 0 点容器必须抛错, 批量路径不得把它计进成功列表。

        验证的行为: 单源 ``export_multiband_photometry`` 抛 ``RuntimeError``
        且目录里没有产物; ``batch_export_multiband_photometry`` 返回空列表
        (该源不进成功列表)。为什么重要: 修复前 0 点容器被当「导出成功」返回
        路径并进批量成功列表, 调用方拿到的是一批看起来完好的空文件。
        """

        class _EmptyContainer:  # 替身: 只回 0 点容器, 隔离 ID 解析与网络两件事
            """域对象替身: from_client 回 0 点容器, 不碰坐标解析也不发请求。"""

            @classmethod
            def from_client(cls, client, source_id, band=None, catalog="ps1"):
                """回一个 0 点容器 (与 G1-02 修复后 from_position 的真空区出口同形态)。"""
                return BestMultiBandPhotometry(source_id=source_id, band=band)

        monkeypatch.setattr(export_mod, "BestClient", object)  # 零网络: client 换成空壳类
        monkeypatch.setattr(export_mod, "BestMultiBandPhotometry", _EmptyContainer)  # 域对象也走替身

        with pytest.raises(RuntimeError):
            export_mod.export_multiband_photometry("POS_10.0000_-30.0000", output_dir=str(tmp_path))
        assert list(tmp_path.glob("mbp_*")) == []  # 失败源不得留下任何产物

        out_dir = tmp_path / "batch"
        paths = export_mod.batch_export_multiband_photometry(["POS_10.0000_-30.0000"], output_dir=str(out_dir))
        assert paths == []  # 批量成功列表里不得有它: 空列表是诚实的「一个都没成」
        assert list(out_dir.glob("mbp_*")) == []


class TestReassignedIdListIsFailClosed:
    """H4 转派 1: crossmatch_source_list 的 id_list 兜底必须 fail-closed (G1-07 同形)。

    判据与 H4 在 ``src/ai_tools.py`` 的 id_list 收集点逐条对齐: 逐级取值、
    ``None`` 与空串/纯空白都视作缺失、最后兜底到输入下标、一批一条告警。
    """

    def _labels_for(self, sources):
        """跑一次 crossmatch_source_list 并取回它下传给逐点路径的 id_list。"""
        client = BestClient(rate_limit=0)  # 限流归零: 本例只断 id 收集, HTTP 全程打桩
        xm = BestCrossMatch(client)  # 门面: 收集逻辑在 crossmatch_source_list 里
        with pytest.MonkeyPatch.context() as mp:  # 局部打桩: 逐点路径整体替掉
            seen = {}

            def fake_coords(ra_list, dec_list, catalog, radius, id_list=None, **kw):
                """替身逐点路径: 只把实收的 id_list 记下来, 返回一个成功信封。

                本组用例要断的是**id 收集逻辑**, 匹配本身由别的用例守; 打桩到
                这一层就够, 再往下走真实网络只会让断言依赖站点回包。
                """
                seen["id_list"] = id_list  # 只记 id_list: 坐标解析另有专门用例
                return BestQueryResult(success=True)

            mp.setattr(xm, "crossmatch_coords", fake_coords)
            xm.crossmatch_source_list(sources)  # 走公开入口
        return seen["id_list"]

    def test_none_and_blank_ids_never_become_literal_strings(self):
        """``id=None`` / ``id=""`` / 缺键 三种脏输入都不得产出字面串。

        验证的行为: ``[{'id': None, 'source_id': 'ps1_123'}, {'id': ''}, {}]``
        得到 ``['ps1_123', '1', '2']``。为什么重要: 旧的
        ``str(source.get("id", source.get("source_id", index)))`` 只在**键缺失**
        时回落, 值为 None 时原样返回, ``str(None)`` 把 Python 关键字变成字面串
        ``"None"`` 混进 ``source_id`` 前缀 (``"None -> ps1_123"``) —— 真实 id
        被吞, 且该前缀与合法 id 无法区分, 比缺前缀更难发现。
        """
        labels = self._labels_for([{"ra": 10.0, "dec": 20.0, "id": None, "source_id": "ps1_123"},
                                   {"ra": 11.0, "dec": 21.0, "id": ""},
                                   {"ra": 12.0, "dec": 22.0}])
        assert labels == ["ps1_123", "1", "2"]  # 逐级兜底: id 缺失取 source_id, 再缺取下标
        assert "None" not in labels  # 显式钉住: 关键字 None 不得字符串化后混进查询
        assert "" not in labels  # 空串同理: 拼出来的是无主前缀, 一样不可追踪

    def test_usable_ids_pass_through_unchanged(self):
        """真实 id 必须原样透传, 含数字 id; 纯空白视作缺失。

        验证的行为: ``[{'id': 'S4'}, {'id': 7}, {'id': '   '}]`` →
        ``['S4', '7', '2']``。为什么重要: 兜底逻辑不能变成"一律换成下标"的
        过度过滤 —— 那会把明明有 id 的行也标成兜底名, 血缘一样丢。
        """
        labels = self._labels_for([{"ra": 10.0, "dec": 20.0, "id": "S4"},
                                   {"ra": 11.0, "dec": 21.0, "id": 7},
                                   {"ra": 12.0, "dec": 22.0, "id": "   "}])
        assert labels == ["S4", "7", "2"]  # 数字 id 统一转字符串; 纯空白按缺失兜底

    def test_one_warning_per_batch_names_the_fallback_count(self, caplog):
        """兜底行数必须留痕, 且一批只报一条 (逐行 warn 会刷爆千行坐标的日志)。

        验证的行为: 4 个源里 2 个在**两级**取值后仍无可用 id 时, 恰好一条
        warning 且含 ``2/4``。注意计数口径只算**真的落到下标兜底**的行 ——
        ``{'id': None, 'source_id': 'ps1_123'}`` 取到了 source_id, 属成功取值,
        不该混进兜底数 (否则告警会把脏输入的规模报错, 排查方向就跑偏)。
        为什么重要: 告警而非抛错 —— 坐标本身有效, id 脏不该让整批匹配消失;
        但**绝不**静默换名 (铁律 5: 目标缺失不静默跳过)。
        """
        client = BestClient(rate_limit=0)  # 限流归零: 逐点路径全程打桩
        xm = BestCrossMatch(client)  # 门面: 收集逻辑在 crossmatch_source_list
        with pytest.MonkeyPatch.context() as mp:  # 局部打桩: 只断 id 收集
            mp.setattr(xm, "crossmatch_coords", lambda *a, **k: BestQueryResult(success=True))
            with caplog.at_level(logging.INFO, logger="src.crossmatch"):
                xm.crossmatch_source_list([{"ra": 10.0, "dec": 20.0, "id": None, "source_id": "ps1_123"},
                                           {"ra": 11.0, "dec": 21.0, "id": ""},
                                           {"ra": 12.0, "dec": 22.0, "id": "S4"},
                                           {"ra": 13.0, "dec": 23.0}])
        warns = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warns) == 1  # 一批一条: 1000 坐标不该刷出 1000 行 warn
        assert "2/4" in warns[0].getMessage()  # 告警要指名兜底了几行, 便于判断是脏输入还是解析 bug


class TestReassignedAmbiguousEchoNeverMislabels:
    """H4 转派 2: 回显基准不可判时宁缺勿错, 绝不把 B 的匹配挂上 A 的 id。

    处置选择 (与 H4 建议方向一致, 但落点不同): ``_input_line_index`` 的
    "1 基优先" 兜底是**有记录在案的兼容映射**, 且被两处他人拥有的锚点钉死
    (``test/unit/crossmatch/test_crossmatch.py`` 的参数化 ``("2", 3, 1)`` 与
    ``evals/probes.py`` 的 ``_input_line_index("1", 2) == 0``), 故**该函数一行
    未改**; 缺陷在**调用方** ``crossmatch_batch`` 拿那个猜测去定 id 归属。故修
    调用方: 基准不可判 (``line_convention="ambiguous"``) 时一律不挂前缀。
    ``evals/`` 无需改动 —— 全仓无任何评测数据引用 ``n_labelled``/
    ``line_convention``。
    """

    def _batch_with_echo(self, echo_line):
        """跑一次两坐标的 proximity 批量, 只让回显行号为 ``echo_line`` 的那一行命中。"""
        client = BestClient(rate_limit=0)  # 限流归零: HTTP 层整体打桩
        xm = BestCrossMatch(client)  # 门面: 标注逻辑在 crossmatch_batch
        row = {"inputobjs_input_line": echo_line,  # 回显行号: 唯一的行↔输入定位依据
               "ps1_source_id": "PS1-99", "ps1_ra": "11.0", "ps1_dec": "21.0", "ps1_rpsf": "15.0"}
        result = BestQueryResult(success=True, sources=[BestSource.from_row(row, catalog="ps1")], total_count=1)
        with pytest.MonkeyPatch.context() as mp:  # 局部打桩: 保留真实标注逻辑
            mp.setattr(client, "crossmatch_batch", lambda *a, **k: result)
            return xm.crossmatch_batch([10.0, 11.0], [20.0, 21.0], catalog="ps1", id_list=["ID_A", "ID_B"])

    def test_zero_based_batch_with_only_second_hit_stays_unlabelled(self):
        """0 基批次只命中第 2 个坐标时, 该行不得挂上第 1 个坐标的 id。

        验证的行为: 回显 "1"、``n_inputs=2`` → 既无 0 基地板值也无 1 基天花板值,
        基准不可判 → ``n_labelled == 0`` 且 ``source_id`` 保持 ``"PS1-99"``。
        为什么重要: 修复前 1 基兜底把 "1" 映射成 0, 结果是 ``"ID_A -> ps1_99"``
        而真值是 ``ID_B`` —— 行在、坐标对, **只有 id 是假的**, 这类错挂比缺
        前缀更难发现。
        """
        result = self._batch_with_echo("1")  # 0 基批次: 第一个坐标没命中, 只有第二个回显 "1"
        assert result.query_params["line_convention"] == "ambiguous"  # 前提: 两条决定性信号都没出现
        assert result.query_params["n_labelled"] == 0  # 基准不可判即弃标
        assert result.sources[0].source_id == "PS1-99"  # 保留匹配源自己的 id, 不加来路不明的前缀
        assert "ID_A" not in result.sources[0].source_id  # 显式钉住被修掉的那个错挂

    def test_decisive_one_based_batch_still_labels_correctly(self):
        """有决定性 1 基信号时标注必须照旧工作 (不得把宁缺勿错做成一律不标)。

        验证的行为: 回显 "2" 且 ``n_inputs=2`` → "2" 是 1 基天花板值, 基准定为
        1 基 → 该行挂 ``ID_B``。为什么重要: 修的是「猜错」不是「标注」, 正例
        必须仍然标对, 否则血缘能力被我一并削掉了。
        """
        result = self._batch_with_echo("2")  # "2" == n_inputs: 1 基的决定性天花板信号
        assert result.query_params["line_convention"] == "1-based"  # 基准可判
        assert result.query_params["n_labelled"] == 1  # 正常标注
        assert result.sources[0].source_id == "ID_B -> PS1-99"  # 1 基语义: 第 2 行就是 ID_B

    def test_decisive_zero_based_batch_still_labels_correctly(self):
        """有决定性 0 基信号时标注必须照旧工作。

        验证的行为: 回显 "0" → 0 基地板值, 基准定为 0 基 → 该行挂 ``ID_A``。
        为什么重要: 与上一条成对 —— 基准**可判**时一律照标, 基准**不可判**时
        才弃标; 只钉弃标那半边的话, "全都不标" 也能骗过回归网。
        """
        result = self._batch_with_echo("0")  # "0" 只可能出自 0 基批次
        assert result.query_params["line_convention"] == "0-based"  # 基准可判
        assert result.query_params["n_labelled"] == 1  # 正常标注
        assert result.sources[0].source_id == "ID_A -> PS1-99"  # 0 基语义: 第 0 行就是 ID_A

