"""深度审计轮的缺陷回归 (波段映射、取消传播、落盘消毒)。

职责: 每个用例都钉住一个旧测试套看不见的缺陷 —— 旧套在 bug 所在层之上打桩,
于是断言全绿而缺陷存活。这批断言守的其实是"打桩层级"本身: 替身只允许落在
协议层之下, 一旦往被测方法那一层打桩, 测的就变成替身自己了。
所属层次: test/unit 层 (audit_round 组); 被测模块横跨 src.client (两阶段异步
HTTP 客户端)、src.crossmatch (坐标交叉匹配)、src.download_manager 与
src.downloader (后台下载栈与落盘)、src.protocol (端点常量与列名映射)、
src.scripts.checkpoint 与 src.scripts.guards (断点存取与路径/CSV 工具)。
对外接口: 十四个测试类按缺陷族切分 —— TestBandResolution (波段列名解析)、
TestCancellationPropagates (取消必须外泄)、TestDownloaderSafety (指纹隔离与
公式消毒与路径穿越)、TestCrossMatchOrdering (输出与输入同序)、
TestSharedIoHelpers (列并集与目录内解析)、TestCsvWireFormat (线上字节格式)、
TestTypedErrorCodes (错误码必须透出)、TestStdGroupMergeIsolation (组合并的失败
隔离与总量封顶)、TestDataRootAnchoring (数据根锚定)、
TestDownloadUrlAllowlist (SSRF 白名单)、TestBackendContract (后端契约)、
TestSaveResultFormatContract (落盘名与格式自洽)、
TestSingleDefinitionAndBudgetClamp (重复定义与预算钳制)、
TestProgressStorePathGuard (进度文件路径守卫)。
依赖与数据流: 夹具全在内存里现造, 网络侧一律 session/替身回放 (铁律 7: 评测与
测试都不得打真实站点); 写操作只落 pytest 的 tmp_path (CSV、断点、进度文件),
跑完即弃不碰工作区; 断言直接读回落盘字节 —— 行分隔符这类线上格式问题读内存
对象是读不出来的, 必须是盘上的真实字节。
关键契约与不变量: 替身钉在协议层之下 (session.get / _execute_query), rate_limit
归零防真发请求; 数据根用 monkeypatch 指向 tmp_path, 越界路径必须 ValueError 而
不是静默写到别处; 落盘名的扩展名与格式必须自洽, 显式名不纠也不放行。
陷阱与边界: 本文件里的断言都是"已知该绿"的契约, 红了就是真回归 —— 顺手改断言
去迁就现状是这里最坏的一种修法; 各用例 docstring 记的是这条断言挡住的不变量
(以及"放开它会出什么事"), 判断断言松紧时以那套说法为准。
"""
from __future__ import annotations  # 标准库: 注解延迟求值

# 标准库: Mock/patch 在协议层之下打桩 (让真实业务逻辑照跑)
from unittest.mock import Mock, patch

# 第三方: pytest.raises 承载负路径断言; requests 异常层级 (P2-8 替身)
import pytest
import requests

# 本地: 传输层 client / 交叉匹配 / 下载管理 / 落盘与协议工具 (跨能力边界一次导入)
try:
    # src.client: 两阶段异步 HTTP 客户端 (被测入口); src.crossmatch: 坐标交叉匹配 (服务端 proximity 批量匹配); src.download_manager: 后台下载栈 (并行/断点/进度/hook); src.downloader: 流式下载 + 校验和; src.models: 查询结果/单源/约束的数据模型; src.protocol: 协议层 (端点常量/表单拼装/软 404 判定/列名映射); src.scripts.checkpoint: 页级断点存取; src.scripts.guards: ADQL 语法校验与原子落盘
    from src.client import BestClient
    from src.crossmatch import BestCrossMatch
    from src.download_manager import JobCancelledError
    from src.download_progress import ProgressStore
    from src.downloader import BestDownloader, _constraint_fingerprint
    from src.models import BestQueryResult, BestSource, ColumnConstraint
    from src.protocol import (
        GETCOUNT_PATH,
        NameResolveError,
        Soft404Error,
        magnitude_column,
        quality_column,
    )

    # 标准库: 被测源码读取与补丁 (audit_round 的静态审查夹具)
    from src.scripts.checkpoint import DownloadCheckpoint
    from src.scripts.guards import (
        resolve_data_path,
        resolve_within,
        to_csv,
        validate_external_url,
    )
except Exception as _legacy_err:  # legacy-import-guard
    # 任一模块缺失即整模块 skip: 这些回归只在完整交付里才有意义
    import pytest as _pytest
    _pytest.skip(f'legacy import unavailable: {_legacy_err!r}', allow_module_level=True)

# 标准库: 读回落盘字节做 CRLF 断言 (放在 skip 守卫之后, 故需 noqa E402)
from pathlib import Path  # noqa: E402


class TestBandResolution:
    """波段名 -> 各星表真实列名: 映射错就会 constrain 一个不存在的列。

    断言按"每张星表一条"来写而不是只测一张: 解析逻辑是按 catalogue 分支的,
    只测 ps1 等于放行另外四张表的分支各自写错。
    """

    def test_band_maps_onto_the_real_column_per_catalogue(self):
        """每个星表的波段列名必须按该星表真实 schema 解析 (无统一猜测)。

        五条断言覆盖五个分支, 尤其 gaia_dr3 的 bp 要跨命名空间拼成
        ``gaia_dr3_18.phot_bp_mean_mag`` —— 少一段点号就是一条静默的零结果
        查询, 服务端不报错, 数据文件却是空的。
        """
        assert magnitude_column("ps1", "g") == "ps1.gpsf"  # 五条各钉一个分支, 少测一张即放行其余
        assert magnitude_column("stripe82", "u") == "stripe82.u_h22"  # 第二条分支: 列名带通配风格, 猜错就是静默零结果
        assert magnitude_column("landolt", "v") == "landolt.vmag"  # 第三条分支: 波段名直接等于列名
        assert magnitude_column("splus_dr4", "j0378") == "splus_dr4.j0378_pstotal"  # 第四条分支: 波段名带时间戳前缀
        assert magnitude_column("gaia_dr3", "bp") == "gaia_dr3_18.phot_bp_mean_mag"  # 跨命名空间拼装

    def test_unknown_band_raises_instead_of_constraining_a_phantom_column(self):
        """星表不发布的波段必须抛错, 不得拿幻影列去 constrain (静默零结果)。"""
        with pytest.raises(ValueError, match="publishes no 'q'-band"):  # 错误串钉住: 实现改了措辞也该先被看见
            magnitude_column("gaia_dr3_18", "q")  # 不存在的波段即抛错, 不得拿幻影列去 constrain
        with pytest.raises(ValueError, match="quality column"):  # 质量列另一条路径, 同样不得拿幻影列
            quality_column("gaia_dr3_18", "snr")  # 质量列是另一条解析路径, 同样不许退化成幻影列

    def test_quality_columns_resolve_where_the_catalogue_publishes_them(self):
        """质量列同样按星表解析: 有则给真实列名, 与波段列区分开。

        splus_dr4 这条是重点: 质量列在库里叫 s2n_det_auto, 与它常被当成同义词的
        snr 完全是两列, 解析器若图省事套用波段列的映射就会 constrain 一个
        服务端不认的列名。
        """
        assert quality_column("ps1", "class_star") == "ps1.class_star"  # 同名同列: 多数星表的常规形态
        assert quality_column("splus_dr4", "snr") == "splus_dr4.s2n_det_auto"  # 唯一例外: 质量列真名另有一套


class TestCancellationPropagates:
    """取消语义: 用户在分页途中取消, 循环必须停下且异常必须外泄。

    取消是唯一一种"用户主动要求停下"的路径, 它一旦失效, 长查询上的 Ctrl-C
    会被安静忽略, 下载照跑到底并覆盖已有文件。
    """

    def test_page_observer_cancellation_aborts_the_paging_loop(self):
        """page observer 里抛出的取消异常必须原样到达调用方。

        模拟对象与协议阶段: ``fake_get`` 替身返回一页 CSV 文本 (协议阶段 =
        分页取数), ``client._count`` 被钉成 5000 以强制进入多页循环;
        observer 在第一页抛 JobCancelledError。

        ``BestClient._fetch_sqlid_data`` 不得吞掉 observer 抛出的任何异常:
        一旦吞掉, 长查询上的 Ctrl-C 被忽略, 下载照样跑完并覆盖文件。
        """
        client = BestClient(rate_limit=0)  # rate_limit=0: 分页循环照跑, 但一个真请求都发不出去
        pages = {"n": 0}  # 可变计数: 闭包改它, 块外才能验循环真的停了

        def observer(page_num, page_sources):
            """页观察者: 第一页即抛 JobCancelledError (模拟用户中途取消)。"""
            pages["n"] += 1  # 先计数再抛: 不计数就证明不了"循环真的停了"
            raise JobCancelledError("cancelled by test")

        def fake_get(url, **kwargs):
            """替身: GET 恒定回一页 CSV (HTTP 200), 模拟分页取数阶段。

            留在 session 这一层而不是 fetch_page 里, 是为了让真实分页循环与
            取消异常的传播链整条跑起来。
            """
            resp = Mock()  # 只补状态码与正文: 替身停在 HTTP 响应这一层
            resp.status_code = 200                                                                  # 状态码定死为 200
            resp.text = "ps1_ra,ps1_dec\n180.0,30.0\n"  # 最小可解析页: 有表头 + 一条记录
            return resp  # 交回响应对象: 分页循环要读它

        with patch.object(client.session, "get", side_effect=fake_get), \
                patch.object(client, "_count", return_value=5000), pytest.raises(JobCancelledError):
            client.fetch_page("s9999", page_size=1, catalog="ps1",
                              max_rows=1000, on_page_fetched=observer)
        assert pages["n"] == 1, "the paging loop must stop at the cancelled page"  # 只跑到第一页


class TestDownloaderSafety:
    """落盘安全: 指纹隔离、公式消毒、路径穿越防护、坏文件容错。

    四条防线各有各的失效后果: 指纹撞车会串作业, 公式消毒失效是数据文件被
    Excel 执行, 路径穿越能把文件写到 output_dir 之外, 而坏 checkpoint 不容错
    会让一次可续传的下载从头再来。
    """

    def test_distinct_constraints_get_distinct_checkpoint_ids(self):
        """两组不同的约束条件绝不能共用一个 checkpoint (续传会串作业)。

        指纹只认约束内容, 与列表对象身份无关 (同内容的新列表必须同指纹)。
        """
        first = [ColumnConstraint(name="ps1_rpsf", constraint="between",  # 第一组约束
                                  min=15.0, max=15.5)]
        second = [ColumnConstraint(name="ps1_rpsf", constraint="between",  # 第二组只改阈值: 内容不同, 指纹必须跟着变
                                   min=16.0, max=16.5)]  # 只差阈值: 指纹必须因此不同
        assert _constraint_fingerprint("ps1", first, "csv") != \
            _constraint_fingerprint("ps1", second, "csv")  # 内容不同 -> 不同作业
        assert _constraint_fingerprint("ps1", first, "csv") == \
            _constraint_fingerprint("ps1", list(first), "csv")  # 同内容新列表 -> 同一作业

    def test_csv_export_neutralises_formula_vectors(self, tmp_path):  # 消毒与数值保真是一对断言, 不能只做一半
        """export_results 必须中和公式向量, 同时不动真实负数 dec。

        两条断言是一对: 只加引号不做区分的实现会把 -5.0 也包成 '-5.0, 那列
        就从数值列退化成文本列, 下游画图与筛选全错 —— 消毒不能以损坏数据为代价。
        """
        downloader = BestDownloader(Mock(), output_dir=str(tmp_path),  # client 传 Mock: 落盘路径不该触发任何请求
                                    checkpoint_dir=str(tmp_path / ".checkpoints"))  # 断点目录隔离: 断言只关心输出文件
        path = downloader.export_results(  # 显式文件名: 这条要验的就是"给什么名写什么名"
            [{"source_id": "A", "dec": "-5.0", "note": "=cmd|' /C calc'!A0"}],  # 公式向量与真实负数同批: 一次就能看出消毒有没有伤到数据
            "safe.csv",
        )
        text = open(path, encoding="utf-8-sig").read()  # utf-8-sig: 读掉 BOM, 否则首列名对不上
        assert "'-5.0" not in text  # 真实负数保持原样, 不被引号包住
        assert "-5.0" in text  # 数值列仍是数值: 包引号会让画图与筛选全错
        assert "'=cmd|' /C calc'!A0" in text  # 公式向量被引号中和

    def test_checkpoint_rejects_escaping_job_ids(self, tmp_path):
        """job id 含 ``..``、绝对路径或子目录必须被拒 (路径穿越防护)。

        四个载荷代表四类越界: 相对上溯、盘符绝对路径、子目录、以及退化成
        ``..`` 的裸值。只测第一类的话, 实现改成"禁止含 .. 即可"就会漏掉
        绝对路径那条 —— 而后者恰恰是 Windows 上最常被利用的形态。
        """
        checkpoint = DownloadCheckpoint(str(tmp_path / ".checkpoints"))  # 断点目录锚在临时区: 越界用例不许碰到真实目录
        for bad in ("../evil", "C:/evil.json", "sub/dir.json", ".."):  # 四类越界载荷, 逐个试
            with pytest.raises(ValueError):  # 越界载荷必须抛错而不是换个路径照写
                checkpoint.save(bad, {"sqlid": "s1"})  # 写入侧与读取侧都要守, 只守一侧等于没守
        assert checkpoint.load("../evil") is None  # 读取侧同样守: 返回 None 而非读到别的作业

    def test_corrupt_checkpoint_returns_none(self, tmp_path):
        """损坏的 checkpoint 必须降级为 None (重新下载), 不得向上抛异常。"""
        checkpoint = DownloadCheckpoint(str(tmp_path / ".checkpoints"))  # 先造出断点存储: 损坏用例要在真实存储上验降级
        (tmp_path / ".checkpoints" / "broken.json").write_text("{not json", encoding="utf-8")  # 写一个语法错误的 JSON: 这是"损坏"最真实的形态
        assert checkpoint.load("broken") is None  # 降级重下, 不炸掉整条续传路径


class TestCrossMatchOrdering:
    """交叉匹配的顺序契约: 输出必须与输入坐标同序。

    顺序是这里唯一被守的东西: 交叉匹配是逐坐标的批量操作, 调用方靠位置把
    结果对回自己的输入行, 一旦服务端返回顺序与请求顺序不一致就全盘错位,
    而错位后的数据看上去仍然"有内容有坐标", 极难人工发现。
    """

    def test_matches_come_back_in_input_order(self):
        """结果行序必须复刻输入坐标序 (打乱即无法与输入行对齐)。

        挡的是"排序实现顺手按某个字段排了"这类回归: 交叉匹配的调用方按位置
        对回输入行, 而重排后的结果每一条都合法, 错位要到下游按坐标比对时
        才暴露, 那时已经离出错点隔了好几层。
        """
        client = BestClient(rate_limit=0)  # 限流置 0: 顺序逻辑不该依赖真实网络
        xm = BestCrossMatch(client)  # 真实对象: 顺序逻辑住在 crossmatch_coords 里

        def fake_single(ra, dec, catalog, radius_arcsec):
            """替身: 按 ra 查表给出预定源与 None 失败位, 用于钉死输出顺序。

            替身故意按入参的 ra 直接决定返回哪条记录, 于是实现无论怎么重排
            请求顺序, 断言都会因为 source_id 与输入坐标不再对应而失败。
            返回形状与 :meth:`_cone_search_single` 的三元组契约一致
            (源, 失败码, 失败原因), 两个失败位都置 None 表示"无匹配"。
            """
            index = {"180.0": 0, "181.0": 1, "182.0": 2}[str(ra)]  # 按入参坐标查表: 替身据此让输出与输入一一对应
            return BestSource(source_id=f"PS1-{index}", ra=ra, dec=dec), None, None  # 失败位返回 None: 这里只验顺序, 失败语义另有专门用例

        with patch.object(xm, "_cone_search_single", side_effect=fake_single):  # 打桩在单坐标搜索这一层: 保留批量与排序逻辑
            result = xm.crossmatch_coords([180.0, 181.0, 182.0],  # 三个坐标刻意递增: 顺序被打乱时才看得出来
                                          [30.0, 31.0, 32.0])  # 对应的三个赤纬: 与赤经同序, 错位会双向露馅
        assert [s.source_id for s in result.sources] == ["PS1-0", "PS1-1", "PS1-2"]  # 与输入坐标逐一对应

    def test_missing_coordinate_raises_instead_of_querying_the_origin(self):
        """缺 ra/dec 的输入必须抛错, 不得退化成查 (0,0) 拿回一堆无关源。

        这是最容易悄悄错的一类: 用 0.0 兜底不会报错, 只会返回一片与用户
        毫不相干的天区数据, 而它们看上去与正常结果没有任何区别。
        """
        client = BestClient(rate_limit=0)  # 限流置 0
        xm = BestCrossMatch(client)  # 真实对象: 顺序与坐标校验都在里面
        with pytest.raises(ValueError, match="no ra/dec"):  # 缺坐标即拒: 0.0 兜底会返回一片无关天区
            xm.crossmatch_source_list([{"dec": 30.0}])  # 缺赤经的输入: 0.0 兜底会返回一片无关天区


class TestSharedIoHelpers:
    """共享 IO 工具: 列并集与目录内解析。

    这两个 helper 被多条落盘路径复用, 所以缺陷会被放大到每一个调用方 ——
    列并集丢键会让不同批次的源在合并时缺列, 目录内解析放过越界名会让所有
    走它的写操作一起失去边界。
    """

    def test_to_csv_uses_the_union_of_record_keys(self, tmp_path):
        """异形记录的列必须取并集, 后出现的键不得被静默丢弃。

        第一行 records 缺 b, 若表头按第一条记录定死, 第二行那条独有的 b
        就会对不上列而整个丢失 —— 丢字段的 CSV 打开时看不出异常, 直到下游
        按列名取值才报 KeyError。
        """
        target = tmp_path / "hetero.csv"  # 目标文件落在临时区: 断言只读盘上那份
        to_csv([{"a": 1}, {"a": 2, "b": 3}], str(target))  # 第一条缺 b: 逼表头取并集
        text = target.read_text(encoding="utf-8-sig")  # 同样按 utf-8-sig 读: 磁盘 CSV 带 BOM
        lines = [ln for ln in text.splitlines() if ln]  # 去空行: 只按行号比内容
        assert lines[0] == "a,b"  # 表头必须是并集, 否则第二条的 b 无处安放
        assert lines[1] == "1,"  # 缺键处留空, 不缩列
        assert lines[2] == "2,3"  # 后出现的键必须存活, 不被静默丢弃

    def test_resolve_within_rejects_absolute_and_traversing_names(self, tmp_path):
        """目录内解析必须拒绝绝对路径、``..`` 穿越与子目录名 (写穿出 output_dir)。"""
        assert resolve_within(tmp_path, "ok.json") == tmp_path / "ok.json"  # 合法名放行
        for bad in ("../x.json", "/etc/passwd", "C:/x.json", "a/b.json"):  # 四类越界形态
            with pytest.raises(ValueError):  # 越界即抛 ValueError
                resolve_within(tmp_path, bad)  # 逐个断言: 少试一类就等于给那一类开了口子


class TestCsvWireFormat:
    """落盘 CSV 的线上字节格式: 行分隔符与导出列集合。

    这里读的是盘上的真实字节而不是内存里的字符串: 行分隔符被翻译两次这类
    缺陷只在"经过 write_text 落到磁盘"之后才显形, 内存断言永远是绿的。
    """

    def test_csv_records_are_separated_by_one_crlf(self, tmp_path):
        """csv.writer 产出 ``\\r\\n`` 行分隔; 文本模式不得把它再翻译一遍。

        模拟对象与协议阶段: BestDownloader 的 client 传 Mock (协议阶段 =
        落盘, 不走网络); 断言直接读磁盘字节。

        实测教训: 每条记录后都跟一个空行 (盘上是 ``\\r\\r\\n``),
        因为 ``write_text`` 把 writer 的换行又翻译了一遍, Excel/pandas 全读错。
        """
        # 标准库: csv — 读回落盘字节做 CRLF 行分隔符断言 (线上格式, 非内存对象)
        import csv as _csv  # 读回落盘字节要用标准库 csv 解析器: 内存断言看不出行分隔符问题

        # 本地: BestDownloader — 落盘 emitter 的被测对象 (CRLF 断言, client 传 Mock)
        from src.downloader import BestDownloader  # 只做落盘: client 传 Mock, 这条与网络无关

        downloader = BestDownloader(Mock(), output_dir=str(tmp_path),  # client 传 Mock: 落盘路径不该触发请求
                                    checkpoint_dir=str(tmp_path / ".checkpoints"))  # 断点目录隔离: 不碰真实断点
        result = BestQueryResult(  # 构造一个成功的结果对象: 落盘器要读计数与源列表
            success=True,  # 成功标志: 落盘前先看它
            total_count=2,  # 总数与返回数一致: 两者不一致时部分实现会走另一条分支
            returned_count=2,  # 两条源: 单条测不出"记录序与输入序一致"
            sources=[  # 第一条源
                BestSource(source_id="A", ra=180.0, dec=30.0, magnitudes={"r": 15.2}),  # 第二条源: 顺序断言要靠它们对调才暴露
                BestSource(source_id="B", ra=181.0, dec=31.0, magnitudes={"r": 16.1}),  # 各自不同的星等: 列集合才是这条要看的
            ],
        )  # 源列表: 落盘器按它的顺序逐行写
        path = downloader._save_result(result, "wire.csv", "csv")  # 显式名 + 显式格式: 落盘名与格式自洽是这条的主题
        raw = Path(path).read_bytes()  # 读字节: 行分隔符只有落到盘上才看得见
        assert b"\r\r" not in raw, "doubled CR: blank line after every record"  # 翻译两次的征兆
        with open(path, encoding="utf-8-sig", newline="") as handle:  # newline="": 禁二次翻译
            rows = list(_csv.reader(handle))  # 用标准库解析器读, 不用手写 split
        assert len(rows) == 3, rows  # 表头 + 2 条记录, 无幻影空行
        id_column = rows[0].index("source_id")  # 按列名取值: 不靠固定下标
        assert rows[1][id_column] == "A" and rows[2][id_column] == "B"  # 记录序与输入序一致

    def test_match_metadata_is_not_exported_as_a_column(self, tmp_path):
        """``inputobjs_`` 交叉匹配元数据不得变成导出列 (内部字段泄漏到数据文件)。"""
        # 本地: BestDownloader — 落盘 emitter 的被测对象 (列集合断言, client 传 Mock)
        from src.downloader import BestDownloader  # 同样只做落盘

        downloader = BestDownloader(Mock(), output_dir=str(tmp_path),  # 构造落盘器
                                    checkpoint_dir=str(tmp_path / ".checkpoints"))
        row = {"inputobjs_input_line": "1", "inputobjs_dist_arcsec": "0.4",  # 带交叉匹配元数据的行: 这些字段绝不该出现在导出列里
               "ps1_ra": "180.0", "ps1_dec": "30.0", "ps1_rpsf": "15.2"}  # 其余是正常投影字段: 它们必须在, 才能证明是"剔除"而非"丢光"
        result = BestQueryResult(  # 先造结果壳
            success=True, returned_count=1,
            sources=[BestSource.from_row(row, catalog="ps1")],  # 从裸行构造源: 与线上路径同构
        )
        path = downloader._save_result(result, "meta.csv", "csv")  # 显式名 + csv 格式
        header = Path(path).read_text(encoding="utf-8-sig").splitlines()[0]  # 只看表头即知列集合
        assert "inputobjs_" not in header  # 交叉匹配元数据不得泄漏进数据文件
        assert "gmag" in header or "rmag" in header  # 归一化后的星等列必须在, 证明投影成立


class TestTypedErrorCodes:
    """错误码必须从提交阶段透出 (软 404 也要能编程识别)。

    只回一个 success=False 的话, 调用方无法区分"天上有零个源"与"查询根本
    没发出去", 只能靠解析错误文案 —— 而文案会随版本漂移, 程序化调用方
    通常根本没读它。
    """

    def test_soft_404_surfaces_as_a_typed_code(self):
        """提交阶段返回 ``E_SOFT_404`` 时必须把它带进 result.error_code。

        模拟对象与协议阶段: ``fake_submit`` 替身返回 (None, "E_SOFT_404:
        dead route"), 对应提交-取 sqlid 阶段; 断言 error_code 被如实透出,
        而不是只剩一个 success=False 让调用方无法区分死路由与其他失败。
        """
        client = BestClient(rate_limit=0)  # 限流置 0
        result = BestQueryResult(success=False, error="boom")  # 先造一个没失败的结果: 错误码的默认值要在失败之前就钉住
        assert result.error_code is None  # 默认无错误码: 未失败时不得预填任何值

        def fake_submit(catalog_path, form_data):  # 替身装在提交这一层: 错误码要能从提交一路走到 result
            """替身: 提交阶段返回 (None, 软 404 错误串), 模拟死路由。

            留在提交这一层而非更下层, 是为了让错误码从提交结果一路走到
            result.error_code, 中间任何一段吞码的改动都会让断言变红。
            """
            return None, "E_SOFT_404: dead route"  # 返回软 404 错误串: 提交阶段拿不到 sqlid 就是这个形态

        with patch.object(client, "_submit_query_for_sqlid", side_effect=fake_submit):  # 打桩在提交方法上, 保留后面所有传递环节
            failed = client.submit_query("ps1")  # 走公开入口: 直接调内部方法会绕过错误码的传递
        assert failed.success is False  # 失败状态照旧, 但错误码必须可编程识别
        assert failed.error_code == "E_SOFT_404"  # 逐字比对: 码变了就是跨 skill 契约破坏


class TestStdGroupMergeIsolation:
    """P2-5: std 导航组合并的单点失败隔离 + 溯源 + 总量封顶。

    "标准星"是横跨三张表的一次逻辑查询, 用户要的是一张结果表; 因此任一成员
    坏掉都不该让另外两张本来可用的表也查不成, 而合并结果又必须说清自己由谁
    合并而来, 否则出了问题没人知道该怀疑哪张表。
    """

    def _stub_members(self, client, fail_member=None):  # 替身只打在 HTTP 层之下: 打在被测方法上就变成测替身自己
        """把 phase-2 执行替身装到 client 上 (可选指定一个成员抛错)。

        打桩点在 ``_execute_query`` (phase-1 之后的真实 HTTP 路径), 而不是
        公开方法 cone_search — 后者正是被测对象 (std 分支住在它里面), 换掉
        它测的就是替身自己了。坏波段成员的 ValueError 由 cone_search 内的
        magnitude_column 真实抛出, 与线上路径一致。
        """

        def fake_execute(path, form, max_rows=50000, page_size=1000, **kwargs):  # 替身按路径首段认出成员: 与 std 展开后的真实形态一致
            # **kwargs 收下 sort/order**: 2026-10-07 起 ``_execute_query`` 带排序透传,
            # 而 std 展开的每个成员都会收到这一对。签名不接的话每个成员都撞
            # ``TypeError: unexpected keyword argument 'sort'``, 三条成员全废 ——
            # 而 std 组的"单成员失败不拖垮全组"恰恰在这种情形下最需要被验证。
            # 刻意用 **kwargs 而不是抄全签名: 本用例守的是隔离性, 不是参数接线,
            # 参数接线由 test/unit/client/ 下的委派缝用例逐个守。
            """替身: 每成员回 2 个源; fail_member 抛 ValueError (坏波段)。"""
            catalog = path.split("/")[0]  # 成员由路径首段给出, 正是 std 展开后的真实形态
            if catalog == fail_member:  # 只让被指定的成员失败: 其余成员要能正常返回
                raise ValueError(  # 抛的错就是真实解析器会抛的那一种
                    f"BEST catalogue {catalog!r} publishes no 'u'-band magnitude "
                    f"(available bands: g, bp, rp)"
                )  # 错误串与线上口径一致: 证明解析器真的走到了波段校验
            part = BestQueryResult(success=True, total_count=2, returned_count=2)  # 成员结果壳: 成功路径要有确定值可比
            part.sources = [BestSource.from_row({"ps1_ra": "180.0"},  # 从裸行构造源, 与真实成员返回同构
                                                catalog="ps1")] * 2  # 两条相同源: 数量要确定, 封顶断言才可算
            return part  # 交回成员结果

        client._execute_query = fake_execute  # type: ignore[method-assign]  # 打在真实 HTTP 层之下

    def test_single_member_failure_does_not_kill_the_group(self):
        """一个成员的坏波段不得炸掉整个组查询 (组内必须逐成员 try)。

        band="u" 时 magnitude_column("xpsp","u") 抛 ValueError, 循环内必须
        把它拦住: 否则用户对标准星全集合的一次查询整体失败, 另外两张本来
        可用的表也查不成。
        """
        client = BestClient(rate_limit=0)  # 限流置 0
        self._stub_members(client, fail_member="xpsp")  # 指定坏成员: 这是"单点失败"的前提
        merged = client.cone_search(ra=180.0, dec=30.0, radius_arcsec=60.0,  # 带波段参数查询: 坏波段才会在解析阶段抛错
                                    catalog="std", band="u", max_records=100)  # 一次性给出三个成员与上限
        # 另外两个成员的结果必须保留
        assert len(merged.sources) == 4  # 坏一个不影响另外两个各 2 条
        # 失败被显式记录 (不静默吞, 也不炸掉调用方)
        assert merged.success is False  # 整组标记为失败, 便于上游提示
        assert "xpsp" in (merged.error or "")  # 错误串须指名坏的是哪张表

    def test_merged_result_carries_provenance(self):
        """合并结果必须带 query_params 溯源 (恒 {} 就无法回答谁合并的)。"""
        client = BestClient(rate_limit=0)  # 限流置 0
        self._stub_members(client)  # 不指定坏成员: 三个成员都健康
        merged = client.cone_search(ra=180.0, dec=30.0, radius_arcsec=60.0,  # 不传波段: 走的是纯组并路径
                                    catalog="std")
        assert merged.query_params["catalog"] == "std"  # 溯源标明这是组合并, 非单表查询
        assert set(merged.query_params["members"]) == {  # 成员全集: 出了问题知道该怀疑谁
            "scr_galah", "scr_lamost", "xpsp"}
        assert merged.success is True  # 三成员都健康时不得被标失败

    def test_total_is_capped_at_max_records(self):
        """成员各取 max_records 会让合并 N 倍超限 — 总量必须封顶且如实截断。

        SA-P3-4 复过的现: 三个成员各取 max_records, 合并可 3 倍超限,
        与单表路径语义不一致 (调用方按 max_records 预分配下游缓冲)。替身
        故意无视分摊额度各回 2 个源 (模拟旧行为的超限成员), 封顶必须兜底。
        """
        client = BestClient(rate_limit=0)  # 限流置 0
        self._stub_members(client)  # 成员都健康, 只看封顶
        merged = client.cone_search(ra=180.0, dec=30.0, radius_arcsec=60.0,  # 上限给 5 而成员各有 2 条: 总量必须被封
                                    catalog="std", max_records=5)  # 5 而成员各有 2 条: 总量必须被封
        assert len(merged.sources) <= 5  # 封顶兜底, 不允许 3 倍超限流下去
        assert merged.truncated is True  # 如实标记被截: 消费方才知道结果不完整


class TestDataRootAnchoring:
    """P1-5/P1-6/P1-7: 目录级锚定 (起点校验) — 终点校验可被参数化绕过。"""  # 目录级锚定才是有效防线: 终点校验可被参数化绕过

    def test_relative_path_anchors_to_data_root(self, tmp_path, monkeypatch):
        """相对路径必须锚定数据根解析, 而不是相对 cwd (cwd 随时会变)。

        挡的是"看起来能跑、换个目录就找不到文件"这一类: 以 cwd 为基准的实现
        在交互式会话里恰好正确, 一旦被调度器或库从别的目录调用就全线失效。
        """
        monkeypatch.setenv("ASTRO_BEST_DATA_ROOT", str(tmp_path))  # 数据根指向临时目录, 不碰工作区
        assert resolve_data_path("best_data") == (tmp_path / "best_data").resolve()  # 相对路径锚到根
        assert resolve_data_path("a/b.csv") == (tmp_path / "a/b.csv").resolve()  # 多级相对路径同理

    def test_absolute_path_inside_root_is_accepted(self, tmp_path, monkeypatch):
        """数据根内的绝对路径放行 (部署把数据盘指过来时就靠这条)。

        与"越界即拒"那条成对: 只守拒不放行的话, 一条"绝对路径一律拒绝"的
        实现也能全绿, 而部署把数据盘挂在别处时就再也读不到数据了。
        """
        monkeypatch.setenv("ASTRO_BEST_DATA_ROOT", str(tmp_path))  # 数据根指向临时目录
        inside = tmp_path / "deep" / "x.csv"  # 根内的绝对路径: 部署挂数据盘时走这条
        assert resolve_data_path(inside) == inside.resolve()  # 放行, 不一律拒绝

    def test_escape_attempts_are_rejected(self, tmp_path, monkeypatch):
        """越界即拒: ``..`` 上溯、根外绝对路径都必须 ValueError。

        复过的现 (P1-5/P1-6): ``Best.download`` 的 output_dir 与
        ``python -m src --output`` 的父目录由调用方直接给定, 落盘侧的
        resolve_output_path 只校验"文件是否逃出 output_dir" — 基准本身
        不受校验, 防逃逸被参数化绕过。
        """
        monkeypatch.setenv("ASTRO_BEST_DATA_ROOT", str(tmp_path))  # 数据根指向临时目录
        with pytest.raises(ValueError, match="越出数据根"):  # 相对上溯
            resolve_data_path("../outside.csv")  # 相对上溯的载荷
        with pytest.raises(ValueError, match="越出数据根"):  # 绝对路径也逃出去
            resolve_data_path(Path(tmp_path).parent / "elsewhere.csv")  # 绝对路径逃出根: 只测相对上溯的实现会漏掉这条

    # P1 合并注记: 原 test_best_download_output_dir_escape_is_rejected 守
    # pybest 门面 Best.download 的 output_dir 数据根锚定; 双副本删除后,
    # 数据根锚定收敛在 resolve_data_path 单点 (上面两条用例直接守),
    # CLI 入口 (python -m src --output) 经同一单点校验, 门面条目移除。


class TestDownloadUrlAllowlist:  # 没有白名单校验时, 用户可控 URL 就是 SSRF 原语
    """P1-10: 下载 URL 主机白名单 — 无校验时 FileJob.url 是 SSRF 原语。"""

    def test_official_host_is_accepted(self):
        """官方数据面主机 (含 www 别名) 必须原样通过 (不破坏正常下载)。

        白名单只写裸主机名会让 www 别名被拒 —— 而它和裸名指向同一台服务器,
        用户从浏览器地址栏抄来的链接偏偏常带 www, 于是正常下载全被误杀。
        """
        url = "https://nadc.china-vo.org/data/best/x.csv"  # 裸主机名
        assert validate_external_url(url) == url  # 原样返回, 不做规范化改写
        assert validate_external_url(  # 分开调用: 别名要单独占一行才看得出它是否被拒
            "https://www.nadc.china-vo.org/data/best/x.csv"  # www 别名: 同一台服务器
        ) == "https://www.nadc.china-vo.org/data/best/x.csv"  # 也必须放行

    @pytest.mark.parametrize(
        "url",
        [
            "http://nadc.china-vo.org/x.csv",        # scheme 非 https
            "https://evil.com/x.csv",                # 非官方主机
            "https://10.0.0.1/x.csv",                # 内网 IP
            "https://169.254.169.254/latest/meta-data",  # 云元数据口
            "https://127.0.0.1:8080/x.csv",          # 回环
            "https://user:pass@nadc.china-vo.org/x.csv",  # 内嵌凭据
            "ftp://nadc.china-vo.org/x.csv",         # 非 HTTP(s) scheme
        ],
    )
    def test_dangerous_urls_are_rejected(self, url):
        """SSRF 载荷必须显式 ValueError (先直连再写盘会让载荷生效并报成功)。

        七个载荷是七类不同的绕过手法, 逐条列出来是因为只测 https+陌生主机
        的话, 一条"先连上再判主机"的实现同样能过前两条而漏掉后面五条 ——
        而连上再判, 响应内容已经进到本地了。
        """
        with pytest.raises(ValueError):  # 载荷必须显式报错
            validate_external_url(url)  # 载荷逐条入参: 每类绕过都要单独判红

    def test_download_file_rejects_foreign_host_before_any_io(self, tmp_path):
        """公开入口守门: download_file 对非白名单 URL 在发起请求前即拒。

        404/内网响应体若被完整写盘并作为"下载成功"产物返回, 白名单就形同
        虚设; 校验必须先于建目录与请求 (Fail-fast, 不留半成品目录)。

        被测入口是权威实现 ``best_export.download_file``。白名单校验在请求
        注入体被调用之前发生, 故 request 替身永不被触达 (返回 None 只为
        签名完整)。
        """
        # 标准库: 静态审查夹具 (ast 解析/补丁/临时目录)
        from src.best_export import download_file  # 只导这一个函数: 守的是公开入口, 不是内部实现

        with pytest.raises(ValueError, match="not the BEST data host"):  # 错误串钉住白名单语义
            download_file("https://evil.com/x.csv", savedir=str(tmp_path),  # 把请求注入体传进去: 校验若真在请求前, 它永不被触达
                          request=lambda *a, **k: None)
        assert not (tmp_path / "x.csv").exists()  # 连半成品文件都不许留下


class TestBackendContract:
    """后端契约守门: 这些语义全部由 BestClient 一个入口承载。"""

    def test_cone_search_expands_std_group(self):
        """P2-6 守门: cone_search(catalog="std") 必须展开成员表合并。

        resolve_catalog("std") 必须返回成员表而不是抛 ValueError (-> None
        -> []), "标准星"概念在两种入口上语义分叉, 唯一入口必须展开。
        (成员级细节由本文件 TestStdGroupMergeIsolation 逐条守, 此处守入口形态。)
        """
        client = BestClient(rate_limit=0)  # 限流置 0
        seen: list[str] = []  # 记账用: 断言要的是"发过哪三条路径", 不是返回值

        def fake_execute(catalog_path, form, *args, **kwargs):  # 替身只记账不回源数据: 成员级细节由别的类守
            """替身 _execute_query: 记账成员表路径并回一个成功结果。

            只记账不回源数据: 本用例守的是"入口有没有展开 std", 成员级的
            细节由本文件别的类逐条守, 两处混在一起就都守不实。
            """
            seen.append(catalog_path)  # 记账成员路径
            return BestQueryResult(success=True, sources=[])  # 回一个空的成功结果: 入口形态才是这条要验的

        client._execute_query = fake_execute  # type: ignore[method-assign]  # 打在 HTTP 层, 不打 cone_search
        client.cone_search(ra=180.0, dec=30.0, radius_arcsec=60.0,  # 走公开入口: 直接调内部方法会绕过展开逻辑
                           catalog="std")  # 三个成员各发一次
        assert set(seen) == {"scr_galah/q", "scr_lamost/q", "xpsp/q"}  # 三成员各发一次裸 id 路径

    def test_query_returns_raw_row_projection(self):  # 裸行投影是 TAP 后端的硬要求: 归一化字典会被转成字符列
        """P1 守门: BestClient.query 只回裸行投影 (归一化由 BestSource 承担)。

        TAP 后端的硬要求: 归一化行追加的 magnitudes 字典会被 VOTable 转换层
        str() 成字符列, 污染科学消费端的列类型 (file-size-budget §5.3)。
        """
        client = BestClient(rate_limit=0)  # 限流置 0

        def fake_execute(catalog_path, form, fmt, max_rows, page_size, **kwargs):  # 位置形参照抄被测方法: 少传或错位会直接 TypeError
            """替身 _execute_query: 回一行带原始投影的源。

            位置形参照抄被测方法的签名, 是为了让"调用方该传什么"这件事也被
            顺带钉住: 少传或错位会直接 TypeError, 而不会静默取到默认值。
            """
            src = BestSource.from_row({"ps1_ra": "180.0", "ps1_rpsf": "15.2"},  # 从裸行构造源
                                      catalog="ps1")
            return BestQueryResult(success=True, sources=[src])  # 回一个成功结果

        client._execute_query = fake_execute  # type: ignore[method-assign]  # 形参照抄被测方法, 少传即 TypeError
        rows = client.query(catalog="ps1", constraints=[])  # 走公开入口, 走真实参数翻译
        assert rows == [{"ps1_ra": "180.0", "ps1_rpsf": "15.2"}]  # 裸行投影, 不得夹带 magnitudes 字典

    def test_query_raises_on_soft_404_instead_of_empty_list(self):
        """P1 守门: query 遇软错误体必须抛 Soft404Error, 不降级为空结果。

        把"路由不存在"翻译成 [] 会让调用方无法区分"天上没源"与"查询根本
        失败" (P0-3 的四态混淆)。
        """
        client = BestClient(rate_limit=0)  # 限流置 0
        client._execute_query = lambda *a, **k: BestQueryResult(  # type: ignore[method-assign]
            success=False, error="E_SOFT_404: Not Found",
            error_code="E_SOFT_404",
        )
        with pytest.raises(Soft404Error):  # 抛错而非返回 []: 四态混淆正是 P0-3 的病根
            client.query(catalog="ps1", constraints=[])  # 走公开入口

    def test_tap_query_kwargs_carry_the_raw_row_contract(self):
        """TAP 执行器的分支翻译: 约束/锥形/上限齐备, 且不传归一化开关。

        裸行投影是 BestClient.query 的固有契约 (见上一个用例), 调用点
        不需要 (也不能再传) normalize 开关。
        """
        # 本地: TAP 执行器 — _query_kwargs 是被测的翻译点 (只在守门时导入)
        from src.tap.executor import QueryBranch, TapExecutor  # 只做守门时才导入: 平时不必把 TAP 执行器拉进测试进程

        executor = TapExecutor(BestClient(rate_limit=0))  # 执行器套真实客户端
        # 一个最小 plan: 直接调 _query_kwargs 不需要完整 plan 对象
        branch = QueryBranch(constraints=[])  # 空约束: 钉的是参数翻译本身
        kwargs = executor._query_kwargs(  # 参数翻译是这条的被测点
            type("Plan", (), {"catalog": "ps1", "columns": None})(), branch, 10  # 伪 plan 对象: 只需 catalog 与 columns 两个属性
        )
        assert kwargs["catalog"] == "ps1"  # catalog 透传
        assert kwargs["max_rows"] == 10  # 上限形参须接到 max_rows
        assert "normalize" not in kwargs  # 归一化开关已退场, 不得复活

    def test_resolve_name_converges_network_errors(self):
        """P2-8 守门: resolve_name 的网络失败必须收敛为 NameResolveError。

        裸抛 requests.ConnectionError 与"调用方只需捕一种异常"的契约相反。
        """
        client = BestClient(rate_limit=0)  # 限流置 0

        def boom(url, **kwargs):  # 替身装在传输层之下
            """替身 session.get: 模拟网络层失败。

            抛的是 requests 自己的异常类型而非自定义错误: 只有这样才能验证
            resolve_name 真的把网络失败收敛成了 NameResolveError, 用自定义
            异常测的话, 实现原样透传也会"看起来是绿的"。
            """
            raise requests.exceptions.ConnectionError("refused")  # 抛 requests 自己的异常: 用自定义异常测等于原样透传也绿

        client.session.get = boom  # type: ignore[method-assign]  # 钉在传输层之下
        with pytest.raises(NameResolveError):  # 收敛成一种异常, 调用方只需捕这一种
            client.resolve_name("M31")

    def test_getcount_soft_404_returns_none(self):
        """P2-8 守门: getcount 遇软 404 按"计数未知"收敛 (None), 不穿透。

        Soft404Error 是 RuntimeError 而非 RequestException, 因此 except
        RequestException 抓不到它 —— 计数端点故障会把整个查询拖失败。
        """
        client = BestClient(rate_limit=0)  # 限流置 0

        def soft_404(url, **kwargs):  # 替身装在传输层之下
            """替身 session.get: 模拟死亡 sqlid 会话的软错误体 (HTTP 200)。"""
            resp = Mock()  # 只补状态码与正文: 200 加错误体就是软 404
            resp.status_code = 200                                                                  # 状态码定死为 200
            resp.text = '{"error":"Not Found"}'  # 200 + 错误体 = 软 404, 不是 HTTP 失败
            return resp

        client.session.get = soft_404  # type: ignore[method-assign]
        assert client.count("s9999") is None  # None = 计数未知, 不冒充 0 也不向上抛

    def test_crossmatch_batch_accepts_page_size(self):
        """P2-7 守门: crossmatch_batch 必须有 page_size 形参 (分页口径一致)。"""
        # 标准库: inspect 取公开签名 (形参契约断言)
        import inspect  # 签名契约要用反射读: 静态文本匹配会漏掉默认值

        params = inspect.signature(BestClient.crossmatch_batch).parameters  # 反射取形参表
        assert "page_size" in params  # 形参必须存在: 与 cone_search 同一套分页口径
        assert params["page_size"].default == 1000  # 默认值也钉住, 改了就是静默改口径

    def test_query_convenience_methods_reject_bogus_formats(self):
        """P2-9 守门: 三个便捷查询入口对非法 output_format 显式抛错。"""
        client = BestClient(rate_limit=0)  # 限流置 0
        for call in (  # 三个便捷入口逐一喂非法格式, 任何一个放行即红
            lambda: client.query_panstarrs(output_format="fits"),  # 第一个入口
            lambda: client.query_calibrated(survey="stripe82", output_format="xml"),  # 第二个入口: 格式名不同但同样是白名单外
            lambda: client.query_standard_stars(output_format="parquet"),  # 第三个入口: 三个都放行就等于没有校验
        ):
            with pytest.raises(ValueError, match="unsupported output format"):  # 错误串钉住语义
                call()

    def test_export_format_is_normalized_in_query_params(self):
        """P2-9 守门: 合法格式大小写归一化后进 query_params (可溯源)。"""
        client = BestClient(rate_limit=0)  # 限流置 0
        captured: dict = {}  # 捕获形参: 断言要的是"发出去的是小写", 不是返回值

        def fake_fetch(**kwargs):  # 替身装在取数层
            """替身 _fetch_sqlid_data: 捕获 output_format, 回空成功结果。"""
            captured.update(kwargs)  # 把形参收下来供断言
            return BestQueryResult(success=True)  # 回空成功结果: 归一化不该影响成功与否

        client._fetch_sqlid_data = fake_fetch  # type: ignore[method-assign]
        client._submit_query_for_sqlid = (  # type: ignore[assignment]
            lambda path, form: ("s9999", None)
        )
        result = client.query_panstarrs(output_format="VOTable")  # 故意用大写格式名
        assert captured["output_format"] == "votable"  # 大写归一: 服务端只认小写
        assert result.success is True  # 归一后仍走通, 不因改写而误判非法格式


class TestSaveResultFormatContract:
    """P3-3/P3-4: 落盘文件名与格式必须自洽; 死分支已清。

    名字与内容对不上是最阴的一类缺陷: 文件确实生成了, 也有内容, 只是下游
    按扩展名选解析器时全盘读错, 而报错点在用户自己的脚本里, 极难回溯。
    """

    def _downloader(self, tmp_path):
        """构造只做落盘的 downloader (client 传 Mock, 不发起请求)。"""  # 只做落盘, client 传 Mock: 这组格式契约用例与网络无关
        # 本地: BestDownloader — 落盘 emitter 的被测对象 (格式契约断言)
        from src.downloader import BestDownloader  # 只做落盘: 这组用例与网络无关

        return BestDownloader(Mock(), output_dir=str(tmp_path),  # 构造落盘器
                              checkpoint_dir=str(tmp_path / ".checkpoints"))  # 断点目录隔离

    def test_explicit_name_must_match_format(self, tmp_path):
        """P3-4 守门: fmt=txt 却给 .csv 名必须显式 ValueError。

        ext_map 只用于自动生成名, 显式名分支若不校验, TSV 内容就会写进 .csv
        文件, 下游按扩展名解析即烂。
        """
        dl = self._downloader(tmp_path)  # 同一个只落盘的 downloader: 显式名与格式的矛盾是这里要验的
        result = BestQueryResult(success=True, sources=[  # 造一个最小成功结果
            BestSource.from_row({"ps1_ra": "180.0"}, catalog="ps1")])  # 显式名与格式矛盾, 必须显式报错
        with pytest.raises(ValueError, match="不相配"):  # 错串钉住: 名字与格式矛盾
            dl._save_result(result, "x.csv", "txt")  # 名称与格式不相配即抛错

    def test_explicit_votable_alias_name_is_preserved(self, tmp_path):
        """live 实证的调用姿势: 显式 .votable 名必须原样保留 (不纠成 .xml)。

        BestDownloader._save_result 不得无条件 with_suffix(".xml") ——
        调用方按自传路径 stat 即 FileNotFoundError。
        """
        dl = self._downloader(tmp_path)  # 同一个只落盘的 downloader: 别名保留是这条的主题
        result = BestQueryResult(success=True, sources=[  # 造一个最小成功结果
            BestSource.from_row({"ps1_ra": "180.0"}, catalog="ps1")])
        path = dl._save_result(result, "live.votable", "votable")  # 显式别名 + 匹配格式
        assert path.endswith("live.votable")  # 别名保留: 调用方按自传路径 stat
        assert Path(path).is_file()  # 盘上确有该名, 不是被改写后返回的旧路径

    def test_canonical_xml_name_is_kept(self, tmp_path):
        """规范名 (.xml) 同样原样保留 (两条落盘路径同一套别名口径)。

        与 .votable 那条成对: 别名保留与规范名保留必须是同一个决策, 分头实现
        就会出现"有的扩展名被纠、有的不被纠", 调用方无法形成稳定预期。
        """
        dl = self._downloader(tmp_path)  # 同一个只落盘的 downloader: 规范名保留与别名保留同属一个决策
        result = BestQueryResult(success=True, sources=[  # 造一个最小成功结果
            BestSource.from_row({"ps1_ra": "180.0"}, catalog="ps1")])
        path = dl._save_result(result, "canonical.xml", "votable")  # 规范名 + 匹配格式
        assert path.endswith("canonical.xml")  # 规范名不动: 与 .votable 同一条决策

    def test_txt_alias_name_is_normalised_to_tsv(self, tmp_path):
        """显式 .txt 名归一到规范容器 .tsv (live 实证的既有行为不动)。

        这条与上一条方向相反且是有意的: txt 是别名故归一到规范容器 tsv, 而
        votable 是别名但调用方按自传路径 stat, 归一会直接 FileNotFoundError。
        两者都写在这里, 是为了让下一个人改这条时看到取舍而不是以为写反了。
        """
        dl = self._downloader(tmp_path)  # 同一个只落盘的 downloader: 归一方向与前两条相反且是有意的
        result = BestQueryResult(success=True, sources=[  # 造一个最小成功结果
            BestSource.from_row({"ps1_ra": "180.0"}, catalog="ps1")])
        path = dl._save_result(result, "result.txt", "txt")  # 显式别名 + 匹配格式
        assert path.endswith("result.tsv")  # 唯一归一的一条: txt 是别名, 规范容器是 tsv


class TestSingleDefinitionAndBudgetClamp:
    """P3-1 重复定义 / P3-8 展示预算钳制 / P3-2 端点常量接线。

    三条看似不相干, 归在一起是因为它们同属"配置与契约写了但没真正生效":
    同名函数写两份等于协议层成了死代码, 预算只报不钳等于配置了不执行,
    端点路径写死等于协议层常量形同虚设。
    """

    def test_crossmatch_has_no_duplicate_proximity_helper(self):  # 重复定义会让协议层的薄别名成为死代码
        """P3-1 守门: _proximity_radec_text 全模块只允许一份定义。

        复过的现: 同名函数定义两次, 生效的是后一份 (重写 zip 逻辑), 协议层
        薄别名成为死代码 — 线格式单一事实源被打破。AST 级断言防再犯。
        """
        # 标准库: ast 解析源文件数定义 (重复定义的结构化判据)
        import ast  # AST 解析源文件数定义

        tree = ast.parse(Path("src/crossmatch.py").read_text(encoding="utf-8"))  # 路径相对当前工作目录: 门禁在仓库根运行
        names = [n.name for n in ast.walk(tree)  # 收集全部函数名, 定义与再定义都算
                 if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]  # 两类定义形态都要收
        assert names.count("_proximity_radec_text") == 1  # 恰一份: 两份即后者覆盖前者

    def test_context_truncate_clamps_to_max_sources(self):
        """P3-8 守门: max_sources 必须真正钳制展示预算。

        复过的现: max_sources 被构造、被 summary() 报告, 却无任何读取点
        做钳制 — 调用方传多大的 max_records 都放行 (配置了不执行)。
        """
        # 本地: QueryContext — 展示预算钳制的被测对象
        from src.scripts.context import QueryContext  # 只导入被测的上下文对象

        ctx = QueryContext(max_sources=50)  # 预算 50, 远小于记录数 4000
        ctx.record("cone_search", {}, 4000)  # 记一次真实结果
        view = ctx.truncate(max_records=5000)  # 请求 5000 远大于预算: 让预算成为唯一约束
        assert sum(h["n_results"] for h in view) <= 50  # 钳制生效, 不是只报不钳
        # summary 仍报真实计数 (摊薄只影响视图)
        assert ctx.summary()["total_results"] == 4000  # 钳制不得改写真实计数

    def test_getcount_url_comes_from_the_protocol_constant(self):
        """P3-2 守门: getcount URL 必须走协议层端点常量 (不再硬编码路径)。"""
        client = BestClient(rate_limit=0)  # 限流置 0
        seen: list[str] = []  # 记账 URL: 端点常量才是唯一事实源

        def fake_get(url, **kwargs):  # 替身装在传输层之下
            """替身 session.get: 记录 URL, 回可解析的计数字符串。

            记账而不是直接返回常量: 断言要的是"URL 由协议层常量拼出来",
            只看返回值的话, 端点被写死成某个具体路径也照样是绿的。
            """
            seen.append(url)  # 记账 URL
            resp = Mock()
            resp.status_code = 200  # 只补状态码: 解析走真实路径
            resp.text = "42"  # 可解析的计数字符串: 让 _count 走完解析再返回
            return resp

        client.session.get = fake_get  # type: ignore[assignment]
        assert client._count("s9999") == 42  # 先确认真的取到了数, 不止是发了请求
        assert seen[0].endswith(GETCOUNT_PATH.format(count="9999"))  # URL 由协议层常量拼出


class TestProgressStorePathGuard:
    """P3-6: 进度文件路径校验委托 resolve_within 单点 (旧自制校验放过绝对路径)。"""

    def test_absolute_and_traversal_job_ids_are_rejected(self, tmp_path):
        """job_id 带目录成分/绝对路径/盘符都必须 ValueError (自制校验的盲区)。"""
        store = ProgressStore(str(tmp_path))  # 进度存储锚在临时区
        for bad in ("../evil", "/etc/passwd", "a/b", "C:\\windows\\x"):  # 四类越界形态
            with pytest.raises(ValueError):
                store._path(bad)  # 越界即抛错

    def test_plain_job_id_still_resolves_with_json_suffix(self, tmp_path):
        """正常 job_id 行为不变: 仍落在 progress_dir 下且带 .json 后缀。"""
        store = ProgressStore(str(tmp_path))  # 进度存储锚在临时区
        path = store._path("region_abc123")  # 正常 id 也要能解析
        assert path == tmp_path / "region_abc123.json"  # 补后缀但不加工内容, 名字仍可预期
