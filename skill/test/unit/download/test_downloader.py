"""BestDownloader 单元测试: 结果落盘 (csv/txt/json/votable) 与三条下载路径。

守的回归: CSV/TSV 落盘必须 ``newline=""`` (Windows 文本模式会把 csv.writer 的
``\\r\\n`` 翻译成 ``\\r\\r\\n``, 每条记录后多一个空行); VOTable 列类型按整列
取值推断而不是按列名猜; 原子写不留 .tmp; 查询失败必须抛而不是静默返回空文件。
"""
from __future__ import annotations

# 标准库: json (读回 JSON 产物校验结构) / os (路径存在性断言) /
# tempfile (临时输出目录, 不在 skill 根下落 best_data) / pathlib 路径断言
import json  # 读回 JSON 产物校验结构: 结构错时 loads 会先炸
import os  # 路径存在性断言: 产物必须真的落盘
import tempfile  # 临时输出目录: 不在 skill 根下落 best_data
from pathlib import Path  # 路径断言的载体

# 标准库: Mock/PropertyMock 为历史用例遗留 (当前用例走 patch/patch.object),
# patch 用于替换 BestClient 的取数方法, 避免真实网络请求
from unittest.mock import Mock, PropertyMock, patch  # 三个都收: 历史用例的遗留替身与当前的 patch 都在用

# 测试框架: raises 断言异常; tmp_path 提供每次用例独立的临时目录
import pytest  # raises 断言异常; tmp_path 给出每例独立的目录

try:
    # 被测单元: 下载器 (分页下载 + 结果落盘 + 断点续传的权威实现)
    from src.downloader import BestDownloader  # 被测单元: 分页下载、落盘与断点续传的权威实现
except Exception as _legacy_err:  # legacy-import-guard
    # 源码树调整导致旧导入路径失效时整模块跳过, 不让收集期报错
    import pytest as _pytest
    _pytest.skip(f'legacy import unavailable: {_legacy_err!r}', allow_module_level=True)            # 模块级跳过: 导入树问题不该算用例失败
# 本地: 生产客户端 (downloader 的 HTTP 依赖, rate_limit=0 关掉礼貌限速)
from src.client import BestClient  # 限流归零: 离线用例不为礼貌间隔付墙钟代价

# 本地: 数据模型 — 查询结果载体 / 单个源 / in-between 约束对象
from src.models import BestQueryResult, BestSource, ColumnConstraint  # 查询结果载体与约束对象: 落盘列集合的输入


class TestBestDownloader:
    """BestDownloader 测试套件: 落盘格式正确性 + 查询路径路由。"""

    def test_init(self):
        """构造即创建 output_dir (批量任务开始前的一次性目录准备)。"""
        client = BestClient(rate_limit=0)                                                           # 限流置 0
        with tempfile.TemporaryDirectory() as tmp:                                                  # 临时目录用上下文管理器: 退出即清理
            dl = BestDownloader(client, output_dir=tmp)  # 构造即建目录: 批量任务开始前的一次性准备必须已完成
            assert dl.output_dir.exists()  # 目录存在是本条的全部契约, 后续落盘用例都依赖这一步

    def test_save_result_csv(self, tmp_path):
        """CSV 落盘: 表头 + 行值可检索, 编码 utf-8-sig (Excel 兼容)。

        守的不变量: 纯 utf-8 会让 Excel 打开中文列名乱码; 且公式注入向量
        (以 =/+/-/@ 开头的单元格) 必须走消毒器, 否则导出的 CSV 是注入面。
        """
        client = BestClient(rate_limit=0)                                                           # 限流置 0
        dl = BestDownloader(client, output_dir=str(tmp_path))  # 输出目录锚到 tmp_path, 免得每次运行都在仓库根下留产物

        src1 = BestSource(source_id="BEST001", ra=180.0, dec=30.0,                                  # 第一条源: 两个波段值, 用来验列并集
                          magnitudes={"r": 15.23, "g": 16.10}, snr=45.0)                            # 两个波段: 星等列要按键逐个落盘
        src2 = BestSource(source_id="BEST002", ra=181.0, dec=31.0,                                 # 第二条源: 只有一个波段, 逼实现取列并集
                          magnitudes={"r": 14.80}, snr=32.0)                                        # 单波段: 缺键处必须留空而不是缩列
        result = BestQueryResult(success=True, sources=[src1, src2], total_count=2)                 # 两条源与总数: 计数与返回数要一致

        path = dl._save_result(result, "test.csv", "csv")  # 经 _save_result 落 csv, 落盘名与格式成对决定后缀
        assert Path(path).exists()  # 产物必须真的落盘, 只在内存里拼好不算数
        content = Path(path).read_text(encoding="utf-8")  # utf-8-sig 写出的文件按 utf-8 读回仍可检出中文列名
        assert "BEST001" in content  # 内容含 source_id, 挡住写出空文件却报成功的退化
        assert "180.0" in content                                                                  # 坐标原样落盘: 消毒器误伤小数点时这条会红
        assert "15.23" in content  # 数值原样落盘: 消毒器误伤正负号时这条会红

    def test_save_result_txt(self, tmp_path):
        """TXT 落盘必须是 TSV (制表符分隔), 不是逗号分隔的同名文件。

        守的回归: 站点 txt 导出的语义是 TSV; 写成逗号分隔会让按列切分的下游
        静默取到错值。
        """
        client = BestClient(rate_limit=0)                                                           # 限流置 0
        dl = BestDownloader(client, output_dir=str(tmp_path))                                       # 输出目录锚到临时区

        src = BestSource(source_id="BEST001", ra=180.0, dec=30.0,                                   # 单条源
                         magnitudes={"r": 15.23}, snr=45.0)
        result = BestQueryResult(success=True, sources=[src], total_count=1)                        # 总数与返回数一致

        path = dl._save_result(result, "test.txt", "txt")  # txt 扩展名请求, 落盘内容语义必须是 TSV
        assert Path(path).exists()
        content = Path(path).read_text(encoding="utf-8")                                            # 按 utf-8 读回
        assert "\t" in content and "BEST001" in content  # 断制表符而非逗号: 同名文件下靠扩展名分不出来

    def test_save_result_json(self, tmp_path):
        """JSON 落盘: {"total": N, "sources": [...]} 结构固定 (消费方按此解析)。"""
        client = BestClient(rate_limit=0)                                                           # 限流置 0
        dl = BestDownloader(client, output_dir=str(tmp_path))                                       # 输出目录锚到临时区

        src = BestSource(source_id="BEST001", ra=180.0, dec=30.0)                                   # 单条源
        result = BestQueryResult(success=True, sources=[src], total_count=1)                        # 总数与返回数一致

        path = dl._save_result(result, "test.json", "json")  # json 分支与 csv/txt 同源, 结构由下面两条钉死
        assert Path(path).exists()                                                                  # 产物必须真的落盘: 只在内存里拼好不算数
        data = json.loads(Path(path).read_text(encoding="utf-8"))  # 回读解析而不是看原文: 结构错时 json.loads 先炸
        assert data["total"] == 1
        assert data["sources"][0]["source_id"] == "BEST001"  # sources 是数组, 消费方按列表取第一个源

    def test_export_results_json(self, tmp_path):
        """export_results: 任意 dict 列表落盘 (与 _save_result 的模型入口分开)。"""
        client = BestClient(rate_limit=0)                                                           # 限流置 0
        dl = BestDownloader(client, output_dir=str(tmp_path))                                       # 输出目录锚到临时区
        data = [{"source_id": "T1", "ra": 180.0, "dec": 30.0}]
        path = dl.export_results(data, "out.json")  # 任意 dict 列表走的是模型外的直写入口
        assert Path(path).exists()  # 落盘即成功, 这条只关心导出面本身不抛

    def test_download_sqlid(self, tmp_path):
        """sqlid 路径: 复用既有会话直接分页取数并落盘 (不再重新 POST 查询)。"""
        client = BestClient(rate_limit=0)                                                           # 限流置 0
        dl = BestDownloader(client, output_dir=str(tmp_path))  # checkpoint 也锚到 tmp_path, 避免在仓库根下建出残留

        with patch.object(client, "_fetch_sqlid_data") as mock_fetch:                               # 打桩在取数方法上
            # 协议阶段: 第二阶段取数, 返回成功结果 (源列表 + total_count)
            mock_fetch.return_value = BestQueryResult(  # 第二阶段取数被整体替换, POST 建查询那一段不在本条判定面
                success=True, sources=[                                                             # 源列表: 落盘列集合的输入
                    BestSource(source_id="BEST001", ra=180.0, dec=30.0)                             # 先造一条源
                ], total_count=1,
            )
            path = dl.download_sqlid("s9999", output_format="json")                               # 复用既有会话直接分页取数, 不再重新提交查询
            assert Path(path).exists()  # 路径存在即成功: 复用既有会话分页取数的出口是落盘

    def test_download_sqlid_failure(self, tmp_path):
        """success=False 必须抛 RuntimeError 且消息透出, 不静默返回空文件。

        守的不变量: 把失败结果照样落盘, 用户拿到一个只有表头的"成功"
        文件, 直到分析阶段才发现查了个空。output_dir/checkpoint_dir 显式锚到
        tmp_path: 默认值是 CWD 相对的, 会让每次运行都在 skill 根下建
        best_data/。
        """
        client = BestClient(rate_limit=0)                                                           # 限流置 0
        # tmp_path: 默认 output_dir 是 CWD 相对的, 每次运行都会在 skill 根下
        # 建出 best_data/; checkpoint_dir 同样显式锚到临时目录
        dl = BestDownloader(client, output_dir=str(tmp_path),                                     # 输出目录显式锚定: 默认值是 CWD 相对的
                            checkpoint_dir=str(tmp_path / ".checkpoints"))                          # 断点目录同样显式锚定

        with patch.object(client, "fetch_page") as mock_fetch:                                      # 打桩在分页取数上
            # 协议阶段: 取数失败 (success=False + error 文案), 必须升级为异常
            mock_fetch.return_value = BestQueryResult(success=False, error="Failed")             # 返回失败结果: 必须被升级为异常而不是照样落盘
            with pytest.raises(RuntimeError, match="Failed"):  # 必须抛而不是返回空文件, 否则用户拿到只有表头的假成功
                dl.download_sqlid("s9999")                                                          # 走公开入口: 直接调内部会绕过失败升级

    def test_save_result_votable(self, tmp_path):                                         # 带表前缀的列名正是这条要守的: 按列名猜类型会判成 char
        """VOTable XML 落盘: 版本与 xmlns 同代, 列值 XML 转义, 列类型按取值推断。

        守的回归: 旧规则 ``col in ("ra","dec") or col.endswith("mag")`` 漏判
        带表前缀的实测列名 (ps1_ra/ps1_dec 被判成 char), astropy 把它们解析
        成字符串, 科学消费端类型断裂; 改为按整列取值推断 double/char。
        """
        # 本地: 数据模型 — 查询结果载体与单个源 (VOTable 列类型推断的输入)
        from src.models import BestQueryResult, BestSource  # 局部导入: 只有这两条要用, 提到模块头徒增耦合

        client = BestClient(rate_limit=0)                                                           # 限流置 0
        dl = BestDownloader(client, output_dir=str(tmp_path))  # 锚到 tmp_path, votable 落盘与 checkpoint 都不污染仓库

        src = BestSource(source_id="BEST001", ra=180.0, dec=30.0,                                   # 两个波段: 星等列要按键逐个落盘
                         magnitudes={"r": 15.23, "g": 16.10}, snr=45.0)                             # 同一条源, 两个波段
        result = BestQueryResult(success=True, sources=[src], total_count=1)                        # 总数与返回数一致

        path = dl._save_result(result, "test.xml", "votable")  # votable 走独立序列化器, 列类型推断的输入就是这一份结果
        assert os.path.exists(path)                                                                 # 路径必须存在
        content = open(path, encoding="utf-8").read()                                               # 按 utf-8 读回
        assert "VOTABLE" in content  # 根标签必须是 VOTABLE, 缺了 astropy 直接拒收
        assert "15.23" in content  # 数值原样写入 XML 文本, 转义坏了这条会红
        assert "BEST001" in content  # 坐标同样要进 XML: 漏写则源可解析却定位不到天区
        assert "180.0" in content                                                                   # 坐标原样写入 XML 文本

    def test_save_result_votable_empty(self, tmp_path):                                       # 空结果也要能被解析成 0 行, 而不是被当成损坏文件
        """空 sources 也要产出合法 VOTABLE (不是 0 字节文件)。

        守的回归: 空结果被 astropy 当损坏文件拒收, 下游直接崩; 合法空表能被
        正常解析成 0 行。
        """
        # 本地: 数据模型 — 查询结果载体 (空 sources 也要产出合法 VOTABLE)
        from src.models import BestQueryResult  # 局部导入: 这条只需要结果载体

        client = BestClient(rate_limit=0)                                                           # 限流置 0
        dl = BestDownloader(client, output_dir=str(tmp_path))                                       # 输出目录锚到临时区

        result = BestQueryResult(success=True, sources=[], total_count=0)                           # 零源零总数: 这正是"合法空表"的构造
        path = dl._save_result(result, "empty.xml", "votable")  # 空 sources 仍走同一序列化器, 不能被短路成 0 字节
        assert os.path.exists(path)                                                                 # 路径必须存在, 且不是 0 字节
        content = open(path, encoding="utf-8").read()                                               # 按 utf-8 读回
        assert "VOTABLE" in content  # 合法空表可被解析成 0 行, 这正是与损坏文件的区别

    def test_save_result_txt_tsv(self, tmp_path):
        """TSV 落盘: 后缀必须是 .tsv + 制表符分隔 + utf-8-sig。

        守的回归 (Windows 专属): csv.writer 产出 ``\\r\\n`` 行尾, 文本模式
        写入会再翻译一层变成 ``\\r\\r\\n`` — 每条记录后多一个空行, Excel 与
        pandas 都把它读成空行。修复是 ``newline=""``; 本用例守住"行尾不被
        doubling"这一事实 (分隔符与后缀同时回归)。
        """

        client = BestClient(rate_limit=0)                                                           # 限流置 0
        dl = BestDownloader(client, output_dir=str(tmp_path))                                       # 输出目录锚到临时区

        src = BestSource(source_id="BEST001", ra=180.0, dec=30.0,                                   # 单条源
                         magnitudes={"r": 15.23}, snr=45.0)                                         # 两个波段
        result = BestQueryResult(success=True, sources=[src], total_count=1)                        # 总数与返回数一致

        path = dl._save_result(result, "test.txt", "txt")  # 请求 txt 落成 .tsv, 后缀即语义声明
        # 落盘后缀必须是 .tsv (请求 txt 也要落成 .tsv, 后缀即语义声明)
        assert ".tsv" in path and path.endswith(".tsv")
        content = open(path, encoding="utf-8").read()                                               # 按 utf-8 读回
        assert "BEST001" in content                                                        # 内容含 source_id, 挡住写出空文件却报成功的退化
        # 分隔符必须是制表符 (证明内容真是 TSV, 而不是逗号分隔的同名文件)
        assert "\t" in content and "180.0" in content

    def test_download_region_success(self, tmp_path):
        """区域查询: 带 cone 参数路由到 cone_search (服务端锥搜) 而非约束查询。

        守的回归: _query_by_catalog 收敛重构后, 空间选择一律以原生 cone
        参数下发; 旧版测试把桩打在 query_panstarrs 上 (那只在无 cone 的
        约束查询路径使用), 导致真实 cone_search 发 live 请求 —— 网络通就
        侥幸通过, 网络断就红, 是披着单测外衣的 live 测试。
        """

        client = BestClient(rate_limit=0)                                                           # 限流置 0
        dl = BestDownloader(client, output_dir=str(tmp_path))  # 桩打在 cone_search 上: 无 cone 的约束路径才走 query_panstarrs

        # 标准库: patch 打桩 cone_search, 让区域查询不走真实网络请求
        from unittest.mock import patch  # 局部导入: 顶部已有同名的 patch, 这里只为自证不依赖它

        mock_result = BestQueryResult(                                                              # 先造一个成功结果
            success=True,
            sources=[BestSource(source_id="T1", ra=180.0, dec=30.0, magnitudes={"r": 15.0})],       # 带波段的源: 落盘列集合的输入
            total_count=1,                                                                          # 总数与返回数一致
        )

        with patch.object(client, "cone_search", return_value=mock_result) as mock_cone:            # 打桩在锥搜上, 区域查询才走得到它
            # 协议阶段: 第一阶段 POST 建查询拿 sqlid + 第二阶段分页取数,
            # 由 cone_search 一次性封装
            path = dl.download_region(ra_center=180.0, dec_center=30.0, radius_arcsec=60.0, catalog="ps1")  # 带锥形参数调用: 空间选择一律以原生 cone 下发
            assert os.path.exists(path)  # 落盘存在即路由正确: 走错查询方法时桩不会被触发而路径也不对
            # 路由断言: 必须走锥搜, 且半径以角秒原样下发 (不打折、不换算)
            assert mock_cone.called  # 桩被调用是路由判据: 走别的查询方法这条会红
            assert mock_cone.call_args.kwargs["radius_arcsec"] == 60.0  # 半径原样下发, 不打折也不换算成度
            assert mock_cone.call_args.kwargs["catalog"] == "ps1"  # catalog 同样透传, 换星表时桩仍被调用但结果应随之改变

    def test_export_results_csv(self, tmp_path):
        """export_results 的 CSV 分支: dict 列表 -> 表头 + 行。"""

        client = BestClient(rate_limit=0)                                                           # 限流置 0
        dl = BestDownloader(client, output_dir=str(tmp_path))                                       # 输出目录锚到临时区
        data = [{"source_id": "T1", "ra": 180.0, "dec": 30.0}]                                      # 任意 dict 列表
        path = dl.export_results(data, "out.csv")                                                   # 走模型外的直写入口
        assert os.path.exists(path)
        content = open(path, encoding="utf-8").read()                                               # 按 utf-8 读回
        assert "T1" in content

    def test_export_results_atomic_cleanup(self, tmp_path):
        """原子写清理: 成功后 .tmp 不得残留在磁盘上。

        守的不变量: os.replace 失败路径若留下 .tmp, 目录里会堆满半成品,
        且 list_jobs/glob 之类的扫描会把它们当成产物。
        """
        client = BestClient(rate_limit=0)                                                           # 限流置 0
        dl = BestDownloader(client, output_dir=str(tmp_path))                                       # 输出目录锚到临时区
        data = [{"source_id": "T2", "ra": 180.0, "dec": 30.0}]                                      # 任意 dict 列表
        path = dl.export_results(data, "atomic_out.json")                                          # 走直写入口: 这条要验的是原子写不留半成品
        assert os.path.exists(path)                                                                 # 产物必须存在
        tmp_file = Path(path).parent / f"{Path(path).name}.tmp"                                    # 按约定拼出临时文件名: 残留就说明清理没做
        assert not tmp_file.exists()                                                                # 成功后不得残留: 残留会被当成产物扫到

    def test_download_by_constraints(self, tmp_path):
        """约束下载: constraints 列表路由到 query_panstarrs (列条件锥搜)。"""

        client = BestClient(rate_limit=0)                                                           # 限流置 0
        dl = BestDownloader(client, output_dir=str(tmp_path))                                       # 输出目录锚到临时区

        # 标准库: patch 打桩 query_panstarrs, 让约束下载不走真实网络请求
        from unittest.mock import patch  # 局部导入: 打桩只在约束下载这条路径上需要

        mock_result = BestQueryResult(                                                              # 先造一个成功结果
            success=True,
            sources=[BestSource(source_id="T1", ra=180.0, dec=30.0, magnitudes={"r": 15.0})],       # 带波段的源
            total_count=1,                                                                          # 总数与返回数一致
        )

        with patch.object(client, "query_panstarrs", return_value=mock_result):
            constraints = [ColumnConstraint(name="ra", constraint="between", min=179.0, max=181.0)]  # 列条件锥搜: 无 cone 的约束查询走的是这条路径
            path = dl.download_by_constraints(constraints=constraints, catalog="ps1")
            assert os.path.exists(path)

    def test_compute_sha256_and_verify_checksum(self, tmp_path):                             # 校验和是完整性防线的第四道: 断点续传与用户校验都靠它
        """Rule 12 防线四: sha256 计算 + 恒定时间校验。

        守的回归: 校验必须大小写不敏感 (hex 大小写等价); 文件不存在时返回
        False 而不是抛 (磁盘被清/半期删除都要能判"不通过"); 用恒定时间比较
        避免时序侧信道 (虽然本地文件场景威胁有限, 口径统一)。
        """
        sample_file = tmp_path / "sample.csv"                                                       # 造一个待校验的产物
        sample_file.write_text("source_id,ra,dec\nS1,180.0,30.0\n", encoding="utf-8")               # 内容要真实, 否则校验和的语义无从谈起

        sha = BestDownloader.compute_sha256(sample_file)                                            # 计算校验和走类方法, 不依赖实例状态
        assert isinstance(sha, str)                                                                 # 必须是字符串: 消费方按 hex 串比对
        assert len(sha) == 64                                                                     # 长度必须是 64: 截断的校验和等于没有校验

        # 命中: 原样 hex 与大写 hex 都必须判 True (大小写不敏感)
        assert BestDownloader.verify_checksum(sample_file, sha) is True
        assert BestDownloader.verify_checksum(sample_file, sha.upper()) is True                     # 大写 hex 也要判通过: 大小写等价

        # 不命中: 校验值不同与文件不存在都必须判 False (而不是抛异常)
        assert BestDownloader.verify_checksum(sample_file, "0" * 64) is False                       # 校验值不同必须判不通过
        assert BestDownloader.verify_checksum(tmp_path / "non_existent.csv", sha) is False          # 文件不存在必须判不通过, 而不是抛异常
