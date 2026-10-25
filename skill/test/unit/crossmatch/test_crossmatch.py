"""BestCrossMatch 交叉匹配单元测试。

守两条匹配路径的回归:
- 逐点路径: CSV 坐标入口 (含 UTF-8 BOM 表头) 与单点 cone_search 的成败语义;
- 服务端 proximity 批量路径 (P0-1): 一次 POST 替代 N 次 cone search, 失败回退逐点。
另守 P0 波段误归属: proximity 的 inputobjs_* 元数据列以字母 i 开头, 不得被当成
i 波段星等写入 magnitudes。
所有用例以 rate_limit=0 构造 BestClient, 关掉客户端限速以免测试被 sleep 拖慢。
"""
from __future__ import annotations

# 标准库: json 读回落盘的任务结果 (脏 id 前缀就写在那份产物里) / Path 定位
# 任务目录 / unittest.mock 打桩 cone_search 与 _execute_query
# (Mock/PropertyMock 为备用替身)
import json  # 读 results.json: 前缀错挂只有落盘产物里看得见
from pathlib import Path  # 由作业句柄给出的 output_url 定位结果文件
from unittest.mock import Mock, PropertyMock, patch  # 替身层: 打桩 cone_search/_execute_query, 零网络

# 第三方: pytest (parametrize: 1-based/0-based 行号两解的参数化驱动)
import pytest

try:
    # 本地: 交叉匹配门面 —— 逐点路径与 proximity 批量路径都从这里进入
    from src.crossmatch import BestCrossMatch
except Exception as _legacy_err:  # legacy-import-guard
    # 旧源码树布局缺失时整包跳过, 不让历史导入失败伪装成本用例失败
    import pytest as _pytest
    _pytest.skip(f'legacy import unavailable: {_legacy_err!r}', allow_module_level=True)       # 模块级跳过: 旧源码树布局不该被误读成匹配行为回归
# 本地: HTTP 客户端 (cone_search/_execute_query 被打桩的对象) 与查询结果/源行模型
from src.client import BestClient
from src.models import BestQueryResult, BestSource


class TestBestCrossMatchUnit:
    """BestCrossMatch 边界用例: CSV 入口、BOM 表头、单点 cone search 三态。"""

    def test_crossmatch_from_csv(self, tmp_path):
        """CSV 坐标文件能被读成 (ra, dec) 两列并转交逐点匹配。

        回归锚点: CSV 上传是最常用的坐标入口; 列解析回归会让用户上传即静默错配。
        """
        # 写最小测试夹具: ra/dec/id 三列两行, 覆盖多坐标批量场景
        csv_path = tmp_path / "coords.csv"                                                          # 坐标文件落在临时区
        csv_path.write_text("ra,dec,id\n180.0,30.0,S1\n181.0,31.0,S2", encoding="utf-8")            # 三列两行: 覆盖多坐标批量场景

        client = BestClient(rate_limit=0)  # rate_limit=0: 逐点路径会连发请求, 限速会拖成分钟级
        xm = BestCrossMatch(client)                                                                 # 构造编排对象

        # 打桩 crossmatch_coords: 隔离 CSV 解析与真实 HTTP, 固定返回"成功且零源"
        with patch.object(xm, "crossmatch_coords") as mock_xm:                              # 打桩逐点匹配: 只验 CSV 解析, 隔离真实 HTTP
            mock_xm.return_value = BestQueryResult(success=True, sources=[])                        # 回一个成功的空结果
            result = xm.crossmatch_from_csv(str(csv_path), catalog="ps1")                           # 走公开的 CSV 入口
            assert result.success  # 挡"读到文件就算成功"的空转: 必须真转交了逐点匹配

    def test_crossmatch_from_csv_with_utf8_bom(self, tmp_path):
        """带 UTF-8 BOM 的 CSV 表头必须被剥掉, 否则首列列名变成 \\ufeffra (Rule 12 防线三)。

        回归锚点: Excel 另存的 CSV 常带 BOM, 不剥掉就会把 ra 列识别不到而抛错。
        """
        # 以字节写 BOM 前缀: 模拟 Excel/Windows 工具链导出的真实文件形态
        csv_path = tmp_path / "coords_bom.csv"                                                      # 带 BOM 的坐标文件
        csv_path.write_bytes("\ufeffra,dec,id\n180.0,30.0,S1\n181.0,31.0,S2".encode("utf-8"))       # 按字节写: BOM 只有字节层才写得出来

        client = BestClient(rate_limit=0)  # 零限速: 逐点匹配被桩掉, 但客户端构造仍带限速器
        xm = BestCrossMatch(client)                                                                 # 构造编排对象

        # 打桩 crossmatch_coords 并断言其入参: 证明 BOM 剥离后 ra/dec/id 三列均被正确识别
        with patch.object(xm, "crossmatch_coords") as mock_xm:                                      # 打桩逐点匹配
            mock_xm.return_value = BestQueryResult(success=True, sources=[])                        # 回一个成功的空结果
            result = xm.crossmatch_from_csv(str(csv_path), catalog="ps1", id_col="id")              # 指定 id 列: 溯源标识从这一列取
            assert result.success                                                                   # 带 BOM 仍须成功
            # 首元素是 180.0 而非缺失值: BOM 未剥时这里会先炸 KeyError
            mock_xm.assert_called_once_with([180.0, 181.0], [30.0, 31.0], "ps1", 3.0, id_list=["S1", "S2"])  # 实参逐项比对: 坐标、id 列表与半径错一项都会错配

    def test_submit_upload_job_with_utf8_bom(self, tmp_path):
        """字符串形态的上传内容同样要剥 BOM (Rule 12 防线三)。

        回归锚点: submit_upload_job 既收文件路径也收内存字符串, 两条入口都要过 BOM 剥离。
        """
        client = BestClient(rate_limit=0)                                                           # 限流归 0
        xm = BestCrossMatch(client)                                                                 # 构造编排对象

        # 内存中的上传体: BOM + 一行坐标, 不走磁盘
        content_with_bom = "\ufeffra,dec,id\n180.0,30.0,S1\n"                                       # 带 BOM 的上传内容
        # 打桩 _cone_search_single: 让作业在无网络下跑完, 返回 (源, 错误) 空对
        with patch.object(xm, "_cone_search_single", return_value=(None, None)):                    # 打桩单点搜索: 这条只看上传作业的解析
            job = xm.submit_upload_job(content_with_bom, catalog="ps1", output_dir=tmp_path)        # 走公开的上传作业入口
            assert job.status == "completed"  # 挡"只提交不入队"就报完成的空转作业
            assert job.input_sources == 1  # 挡"整份上传体被当成 0 个输入源"

    def test_submit_upload_job_dirty_id_falls_back_to_row_index(self, tmp_path):
        """id 列存在但值为 None / 空串时必须回落到输入序号, 不得拼出 "None" 前缀。

        回归锚点 (H1 报告同款缺陷, fail-open 同族): 原写法
        ``str(row.get("id", i))`` 只在**键缺失**时回落 ``i``, 而 DictReader 对
        「表头有 id、该行字段不足」填的是 ``None`` —— 于是 ``str(None)`` 把
        Python 关键字变成字面串 "None" 混进 source_id 前缀
        (``"None -> ps1_123"``)。真实 id 被吞, 且该前缀与合法 id 无法区分,
        比缺前缀更难被发现; 空串则拼出无主前缀 ``" -> ps1_123"``, 同样丢掉
        可追踪性。三级兜底口径与 ``crossmatch_source_list`` / ``src/ai_tools.py``
        的 id 收集点一致 (G1-07)。
        """
        client = BestClient(rate_limit=0)                                                           # 限流归 0
        xm = BestCrossMatch(client)                                                                 # 构造编排对象

        # 三行各脏一种: 第 0 行字段不足 (DictReader 填 None), 第 1 行 id 为空串,
        # 第 2 行有干净 id。逐行错开是为了让「回落到输入序号」与「原样保留真 id」
        # 在同一份产物里同时可判定。
        content = "ra,dec,id\n180.0,30.0\n181.0,31.0,\n182.0,32.0,S3\n"
        with patch.object(xm, "_cone_search_single", return_value=(None, None)):                    # 打桩单点搜索: 这条只看 id 收集
            job = xm.submit_upload_job(content, catalog="ps1", output_dir=tmp_path)                 # 走公开的上传作业入口

        assert job.status == "completed"                                                            # 挡"脏 id 让整批作业失败": 坐标有效就不该因 id 脏丢数据
        results = json.loads(Path(job.output_url).read_text(encoding="utf-8"))["results"]           # 读回落盘产物: 前缀就写在这里
        got = sorted(r["input_id"] for r in results)                                               # 取每行输入标识并排序
        # 排序后再比: 任务队列按 as_completed 的**完成顺序**落 records, 顺序不固定
        # (与 crossmatch_coords 那个按输入下标回放的路径不同)。本例只关心每行
        # 拿到了哪个标识, 不关心行的先后 —— 行的先后由 results 里的 input_ra /
        # input_dec 自证, 排序比才不会把线程调度当成回归。
        assert got == ["0", "1", "S3"], f"脏 id 未回落到行序号: {got}"                               # 脏行取序号, 干净行原样保留
        assert "None" not in got                                                                     # 显式再钉一次: "None" 前缀是最难发现的那种错挂
        assert "" not in got                                                                         # 空串同样不行: 无主前缀丢掉可追踪性

    def test_cone_search_single_match(self):
        """单点 cone search 命中时返回 (源, None, None), 两个失败位必须为空。

        回归锚点: (源, 失败码, 原因) 三元组是逐点路径的错误传播契约, 任一失败位
        残留都会让调用方把成功的坐标误判为失败。
        """
        client = BestClient(rate_limit=0)  # 零限速: 单点路径会发一次真实调用形态的请求
        xm = BestCrossMatch(client)                                                                 # 构造编排对象
        # 替身 cone_search: 模拟网关 HTTP 200 且返回一条匹配源
        with patch.object(client, "cone_search") as mock_cs:                                        # 打桩锥搜
            mock_cs.return_value = BestQueryResult(                                                 # 回一个带源的命中
                success=True,                                                                       # 成功标志
                sources=[BestSource(source_id="B_MATCH", ra=180.0, dec=30.0)],                      # 命中的源
            )
            src, code, err = xm._cone_search_single(180.0, 30.0, "ps1", 3.0)                      # 走单点搜索的内部入口: 成功/无匹配/失败三态都在这里判
            assert src is not None  # 挡"命中被判成空": 三元组契约要求源与失败位同时到位
            assert src.source_id == "B_MATCH"                                                       # 源必须原样返回
            assert (code, err) == (None, None)  # 成功时失败位残留会让调用方误判整批坐标失败

    def test_cone_search_single_no_match(self):
        """锥区内无源是正常结果而非错误: (None, None, None) —— 与"查询失败"严格可分。

        回归锚点: 把空结果当异常上报, 会让批量坐标里一个空锥区就中断整轮; 反过
        来把查询失败折叠成同一个形状, 整批坐标会被静默读成"天区无源" (铁律 5)。
        """
        client = BestClient(rate_limit=0)  # 零限速: 空锥区也要走完一次调用形态
        xm = BestCrossMatch(client)                                                                 # 构造编排对象
        # 替身 cone_search: HTTP 200 但 sources 为空列表
        with patch.object(client, "cone_search") as mock_cs:                                        # 打桩锥搜
            mock_cs.return_value = BestQueryResult(success=True, sources=[])                        # 回一个成功的空结果
            src, code, err = xm._cone_search_single(180.0, 30.0, "ps1", 3.0)                      # 走单点搜索的内部入口
            assert src is None  # 空结果不是错误: 失败位同时为 None 才是契约要求的组合
            assert (code, err) == (None, None)  # 挡"空锥区上报异常", 同时挡"无匹配与查询失败同形"

    def test_cone_search_single_error(self):
        """底层网络异常要被收敛成 (None, E_BACKEND, 原因), 不得向上炸穿批量循环。"""
        client = BestClient(rate_limit=0)                                                           # 限流归 0
        xm = BestCrossMatch(client)                                                                 # 构造编排对象
        # 替身 cone_search: 模拟传输层超时抛出的原始异常
        with patch.object(client, "cone_search") as mock_cs:                                        # 打桩锥搜
            mock_cs.side_effect = Exception("Network timeout")                                    # 让锥搜抛异常: 网络异常必须被收敛而不是冒泡
            src, code, err = xm._cone_search_single(180.0, 30.0, "ps1", 3.0)                      # 走单点搜索的内部入口
            assert src is None                                                                      # 源必须为 None
            assert err is not None  # 挡"异常被吞成 (None, None)": 调用方会以为只是没匹配上
            assert code == "E_BACKEND"  # 异常路径同样必须给码: 无码时调用方只能去嗅错误文本


# --- P0-1: 服务端 proximity 批量交叉匹配 ----------------------

def _proximity_row(line: str, ra: str, dec: str, mag: str) -> dict[str, str]:
    """构造一行 proximity 服务端响应: 匹配元数据列 + 一条星表行。

    列名前缀模拟 showcol 开启时的服务端输出: inputobjs_* 是输入侧元数据,
    ps1_* 是匹配到的星表列。用来验证 BestSource.from_row 的列归类。
    """
    return {
        "inputobjs_input_line": line,  # 行号是回填坐标的唯一定位依据, 缺它整批错配
        "inputobjs_dist_arcsec": "0.42",  # 0.42" 远小于默认半径: 证明 nearest_only 生效
        "inputobjs_input_ra": ra,
        "inputobjs_input_dec": dec,
        "ps1_source_id": f"PS1-{line}",
        "ps1_ra": ra,  # 与输入同坐标: 匹配成功时两侧应当重合
        "ps1_dec": dec,
        "ps1_rpsf": mag,  # 15.x 量级: r 波段 (rpsf), 首字母即波段键
    }


class TestProximityBatch:
    """P0-1: 一次 proximity POST 替代 N 次 cone search, 含 1/0 基行号两解与回退。"""

    def test_radec_text_format(self):
        """radecTextarea 文本必须是 "ra,dec,radius" 每坐标一行 (服务端 proximity 协议)。"""
        # src.crossmatch: 坐标交叉匹配 (服务端 proximity 批量匹配)
        from src.crossmatch import _proximity_radec_text

        text = _proximity_radec_text([180.0, 181.0], [30.0, 31.0], 3.0)                             # 邻近文本构造: 行号与坐标必须逐行对应
        assert text == "180.0,30.0,3.0\n181.0,31.0,3.0"  # 挡逗号/换行错位: 服务端按行拆坐标

    @pytest.mark.parametrize(
        "raw,n_inputs,expected",                                                                    # 参数化表头: 两种行号基准各取一解
        [                                                                                           # 样本清单
            ("1", 3, 0), ("3", 3, 2),      # 服务端行号按 1-based
            ("0", 3, 0),                    # 无歧义的 0-based 取值
            # "2" 在两种约定下都合法; 线上服务端是 1-based,
            # 因此按 1-based 取值 (记录在案的偏好)。
            ("2", 3, 1),
            ("4", 3, None), ("-1", 3, None), ("abc", 3, None), ("", 3, None),
        ],
    )
    def test_input_line_index_accepts_both_conventions(self, raw, n_inputs, expected):
        """input_line 回填索引同时接受 1-based 与 0-based, 越界/非数字一律判 None。

        回归锚点: 线上服务端按 1-based 回行号, 而文档与部分部署按 0-based; 歧义值
        "2" 按 1-based 取值是记录在案的偏好, 改它会静默错配一整批坐标。
        """
        # src.crossmatch: 坐标交叉匹配 (服务端 proximity 批量匹配)
        from src.crossmatch import _input_line_index

        assert _input_line_index(raw, n_inputs) == expected                                         # 行号换算必须两种基准都对

    def test_input_line_index_zero_based_has_no_collision(self):
        """0 基回显的整批映射必须无碰撞 (缺陷 #5 守门)。

        回归锚点: 旧实现两条分支区间在 ``1 <= line < n`` 上重叠 (1 基分支先行),
        于是 0 基响应 ``[0,1,2]`` 被映射成 ``[0,0,1]`` —— line 0 与 line 1 撞到
        同一输入位置, 整批坐标挂错输入 id。显式 ``zero_based=True`` 修掉这一面。

        与上面那条锚点的分工: 那条锁"基准未定时的 1 基偏好"不动, 这条锁
        "基准已定为 0 基时映射唯一"。
        """
        # src.crossmatch 的出处注释本类已有两处, 此处不重复 (comment_audit 的
        # duplicated_comment 会数同名注释的份数)
        from src.crossmatch import _input_line_index

        mapped = [_input_line_index(str(i), 3, zero_based=True) for i in (0, 1, 2)]
        assert mapped == [0, 1, 2]                                          # 三个行号三个下标, 不得塌成 [0,0,1]
        assert len(set(mapped)) == 3                                         # 显式再钉一次: 无重复即无碰撞
        assert _input_line_index("3", 3, zero_based=True) is None           # 0 基批次最大是 n-1, n 越界
        assert _input_line_index("0", 3, zero_based=False) is None          # 1 基批次最小是 1, 0 越界

    def test_match_metadata_columns_never_become_magnitudes(self):
        """P0 波段误归属: inputobjs_* 以字母 i 开头, 不得被解析成 i 波段星等。

        回归锚点: 列名首字母一旦被当作波段代码, dist_arcsec/input_ra 等
        匹配元数据就会污染进 magnitudes["i"], 进而毁掉按波段取星等的全部下游。
        """
        src = BestSource.from_row(                                                                  # 标准形状的 proximity 行
            _proximity_row("1", "180.0", "30.0", "15.2"), catalog="ps1"                             # 带上行号、坐标与距离
        )
        assert src.magnitudes.get("r") == 15.2  # 挡"rpsf 不落星等": 按波段取星等的下游全靠它
        assert "i" not in src.magnitudes  # dist_arcsec/input_* 是匹配元数据, 不是测光
        assert src.raw_data["inputobjs_dist_arcsec"] == "0.42"  # 元数据仍要留 raw_data 供审计

    def test_bare_metadata_columns_are_also_skipped(self):
        """V-1: showcol 关闭时元数据列不带 inputobjs_ 前缀 (input_line/dist_arcsec), 同样不得入星等。"""
        src = BestSource.from_row(                                                                  # 列名不带前缀的 proximity 行
            {"input_line": "1", "dist_arcsec": "0.42", "ps1_rpsf": "15.2"},                         # 同样三列
            catalog="ps1",                                                                          # 星表名
        )
        assert "i" not in src.magnitudes  # 无前缀形态同样不得被首字母规则吃进星等
        assert src.magnitudes.get("r") == 15.2                                                      # 星等必须落进波段: 少了它下游无从折叠

    def test_crossmatch_batch_uses_one_proximity_submission(self):
        """批量匹配只发一次 proximity POST, 并按输入行号回填 source_id。

        回归锚点: 按坐标逐个 cone search 的话, N 个坐标就是 N 次 HTTP; 表单字段名
        (pos.type/pos.radecTextarea/proximity_nearestonly) 与服务端不一致时整批静默失败。
        """
        client = BestClient(rate_limit=0)  # 零限速: 批量路径只发一次 POST, 限速无意义
        xm = BestCrossMatch(client)                                                                 # 构造编排对象
        captured: dict = {}                                                                         # 表单记账: 断言要看的是真发出去的表单

        # 替身 _execute_query: 模拟网关"表单提交层"——收下 POST 路径与表单体,
        # 返回 HTTP 200 的 proximity 两行结果 (不触网)
        def fake_execute(path, form, *args, **kwargs):
            """替身表单提交层: 收下路径与表单体, 回两行 proximity 结果 (零网络)。

            Args:
                path: 被测代码提交的 POST 路径 (捕获以断言路由正确)。
                form: 被测代码提交的表单体 (捕获以断言是"一次批量提交")。
                *args: 位置参数占位。
                **kwargs: 关键字参数占位。

            Note:
                捕获 ``form`` 是这条用例的核心 — 批量匹配必须把全部坐标塞进
                一次 ``pos.type=proximity`` 提交; 若退化成就逐点锥搜, 请求数
                会从 2 变成 N, 上游限流下直接拖垮调用方。
            """
            captured["path"] = path                                                                 # 记下星表路径
            captured["form"] = form                                                                 # 记下表单
            return BestQueryResult(
                success=True,                                                                       # 成功标志
                sources=[                                                                           # 第一条源
                    BestSource.from_row(_proximity_row("1", "180.0", "30.0", "15.2"), catalog="ps1"),  # 第二条源
                    BestSource.from_row(_proximity_row("2", "181.0", "31.0", "16.1"), catalog="ps1"),  # 同样带上行号与距离
                ],
                total_count=2,                                                                      # 总数为二
            )

        with patch.object(client, "_execute_query", side_effect=fake_execute):                 # 打桩在 HTTP 层: 走真实编排才验得到批量提交
            result = xm.crossmatch_batch(                                                           # 走公开的批量入口
                [180.0, 181.0], [30.0, 31.0], catalog="ps1",                                        # 两个坐标
                radius_arcsec=3.0, id_list=["S1", "S2"],                                            # 半径
            )

        # 断言表单语义: 单次提交、proximity 定位类型、半径按 arcsec 传、只取最近邻
        assert captured["path"] == "ps1/q"  # 挡"批量走错路由": 表单对但 POST 到别处仍全废
        form = captured["form"]                                                                     # 取回表单
        assert form["pos.type"] == "proximity"  # 退回 cone 就会退化成逐点搜索
        assert form["pos.radecTextarea"] == "180.0,30.0,3.0\n181.0,31.0,3.0"  # 两坐标必须同批
        assert form["pos.defaultRadius"] == "3.0"  # 半径按 arcsec 直传, 不换算成度
        assert form["proximity_nearestonly"] == "on"  # 挡"最近邻开关丢失"拉回一堆远源
        assert result.query_params["mode"] == "proximity"  # 挡"静默回退却报成功模式"
        assert result.query_params["n_matched"] == 2                                           # 匹配数必须落进查询参数: 调用方据此判断批量的效果
        assert result.query_params["n_labelled"] == 2  # 带 id_list: 两条都该回填上标签
        # "S1 -> PS1-1" 证明输入行号与星表行按行对齐, 而非按结果顺序猜测
        assert result.sources[0].source_id == "S1 -> PS1-1"                                  # 源标识要带上输入 id: 否则结果没法对回用户自己的行
        assert result.sources[1].source_id == "S2 -> PS1-2"  # 第二行同样按行对齐, 不许整体错一位

    def test_crossmatch_batch_falls_back_to_per_coordinate_on_failure(self):
        """proximity 批量失败时必须回退逐点 cone search, 且错误原因要透出。

        回归锚点: E_SOFT_404 一类软失败若让批量路径直接抛错, 可用性就没了;
        回退逐点并记录 mode=per_coordinate_fallback 与 batch_error 才保得住。
        """
        client = BestClient(rate_limit=0)  # 零限速: 回退后要逐点发请求, 限速会成倍拖慢
        xm = BestCrossMatch(client)                                                                 # 构造编排对象
        # 批量层替身: 模拟网关返回"路由不存在"的失败结果 (success=False)
        failure = BestQueryResult(success=False, error="E_SOFT_404: dead route")                    # 服务端回软 404
        # 逐点层替身: 模拟回退后单点 cone search 命中的一条源
        fallback = BestQueryResult(                                                                 # 回退路径的成功结果
            success=True,                                                                           # 成功标志
            sources=[BestSource(source_id="PS1-1", ra=180.0, dec=30.0)],                            # 单个源
            query_params={},                                                                        # 查询参数置空: 走的是回退路径
        )

        with patch.object(client, "_execute_query", return_value=failure), \
                patch.object(xm, "crossmatch_coords", return_value=fallback) as mock_coords:        # 同时打桩逐点路径: 验证它确实被回退调用
            result = xm.crossmatch_batch([180.0], [30.0], catalog="ps1")                            # 走公开的批量入口

        mock_coords.assert_called_once()  # 挡"回退两次"或"根本没回退"
        assert result.query_params["mode"] == "per_coordinate_fallback"  # 模式要如实上报
        assert "E_SOFT_404" in result.query_params["batch_error"]  # 挡"回退原因被吞掉"
        assert result.sources[0].source_id == "PS1-1"                                               # 回退结果必须原样返回

    def test_crossmatch_batch_rejects_mismatched_lists(self):
        """ra/dec 两个列表长度不一致时必须拒绝, 不允许按短的一侧静默截断。"""
        client = BestClient(rate_limit=0)  # 零限速: 校验失败, 一个请求都不该发
        xm = BestCrossMatch(client)                                                                 # 构造编排对象
        result = xm.crossmatch_batch([180.0], [30.0, 31.0])  # ra 1 个 / dec 2 个
        assert result.success is False  # 静默截断会让用户以为两条坐标都匹配过了
        assert "length mismatch" in result.error

    # 权威实现 BestCrossMatch.crossmatch_batch 由**本文件**的 TestProximityBatch
    # 全量覆盖 (radec 文本格式 / input_line 索引 / 元数据不落星等 / 单次提交 /
    # 失败回退 / 长度不齐拒绝), 无第二处覆盖, 改语义时只须看这一处。
