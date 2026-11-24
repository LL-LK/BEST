# -*- coding: utf-8 -*-
"""TAP 序列化测试: 格式别名归一、哨兵转 NaN、CSV 公式中和、VOTable 错误文档。

核心回归是"双阈值同口径": TAP 序列化与 BestSource 必须使用同一个
NULL_MAGNITUDE_SENTINEL 判 NaN, 否则星表里的缺测值会在导出时一半变 NaN 一半变
数字, 下游统计直接失真。
"""
from __future__ import annotations

import pytest

# 本地: 源行模型 —— 提供权威哨兵阈值 NULL_MAGNITUDE_SENTINEL (序列化侧必须与它同口径)
from src.models import BestSource

# 本地: TAP 序列化四件套 —— 行转换/格式归一/结果序列化/VOTable 错误文档
from src.tap.formats import (
    convert_table_rows,  # 行转换: 哨兵阈值与数值解析都在这一层
    normalize_format,  # 格式别名归一: 大小写与 MIME 两种写法都要认
    serialize_result,  # 结果序列化: CSV 中和与 VOTable 转义都在这里
    votable_error,  # 错误文档: 客户端靠它区分成功与失败
)


class TestNormalizeFormat:
    """FORMAT 请求参数别名归一: 大小写、MIME、None 默认值、未知值拒绝。"""

    @pytest.mark.parametrize(
        "value,expected",                                                                 # 参数名表头: 参数化靠它把下面每行接成 (输入, 期望) 对
        [                                                                         # 三个真实格式各带大小写与 MIME 两种写法, 加一条代表规范里的"未指定"
            ("votable", "votable"),
            ("VOTABLE", "votable"),
            ("application/x-votable+xml", "votable"),  # MIME 形态与裸名同归一: 客户端两种写法都得认, 只认一种会在网关侧报错
            ("csv", "csv"),
            ("text/csv", "csv"),
            ("fits", "fits"),
            ("application/fits", "fits"),
            (None, "votable"),  # None 代表规范里的未指定: 缺省必须回落 votable 而不是抛错
        ],
    )
    def test_aliases(self, value, expected):
        """大小写/MIME 别名都要归一到 votable/csv/fits 三选一, 未传时默认 votable (TAP 规范)。"""
        # 参数化把"值形态"与"归一结果"排成对: 三个真实格式各带大小写与 MIME 两种
        # 写法, 加一条 None 代表规范里的"未指定即默认", 少一类就漏一类客户端
        assert normalize_format(value) == expected  # 参数化逐行驱动: 归一是纯查表, 期望值写死即可, 不必构造请求

    def test_unknown_format_rejected(self):
        """子集外格式 (parquet) 必须拒绝并给出 "Unsupported TAP FORMAT", 不放行成默认值。"""
        # match 钉的是错误文案而不只是异常类型: 静默回落默认值会让调用方以为
        # 拿到了 parquet, 而实际拿到的是默认格式, 错误文案是唯一的线索
        with pytest.raises(ValueError, match="Unsupported TAP FORMAT"):             # 错误文案是唯一线索: 静默回落默认值会让调用方以为拿到了 parquet
            normalize_format("parquet")  # 子集外格式必须抛而不回落: 回落会让调用方以为拿到了 parquet


class TestSentinelConversion:
    """缺测哨兵转 NaN: 与 BestSource 同一阈值, 且不能误伤真实负星等。"""

    def test_sentinels_become_nan_and_numbers_parse(self):
        """哨兵值 (<= -999.0) 变 NaN, 可解析数字转 float, 空串转 None, 真实负值保持原样。

        回归锚点: 哨兵判定只认 <= -999.0 — 一旦无差别套用, -30.5 这样的合法负星等
        会跟着被打成 NaN; 空字符串也要和哨兵区分开 (一个是缺测, 一个是无值)。
        """
        converted = convert_table_rows([                                               # 一行四种值形态: 哨兵、坐标、字符串、空串, 转换器的分支一次走完
            {"gmag": "-999.0", "ra": "1.5", "name": "abc", "empty": ""},  # 一行四种值形态: 哨兵/坐标/字符串/空串, 转换器的四条分支一次走完
            {"gmag": "-30.5"},                                                                     # 第二行只放合法负星等: 它必须与哨兵区分开
        ])
        # NaN 用 "自己不等自己" 判定而不是 isnan: 转换侧若漏了转换而原样返回
        # 字符串 "-999.0", 字符串也不等自己, 这条会混过去 —— 所以同组还并排
        # 断着 ra 的 float 与 empty 的 None, 三种形态各自锚一个代表值
        assert converted[0]["gmag"] != converted[0]["gmag"]  # NaN
        # 坐标列必须转成 float: 留字符串会让下游按字典序排序坐标
        assert converted[0]["ra"] == 1.5                                                   # 坐标列必须转 float: 留字符串会让下游按字典序排坐标
        # 非数值列原样透传: 转换只该管数值列, 名字列被 str() 一把抓会很显眼
        assert converted[0]["name"] == "abc"                                                        # 非数值列原样透传: 转换只该管数值列
        # 空串归 None 而不是留 "" : 两者在下游统计里是"无值"与"空字符串"两种
        assert converted[0]["empty"] is None                                               # 空串归 None: 与哨兵是两回事, 一个是缺测一个是无值
        # 合法负星等必须存活: -30.5 是真实暗星, 被哨兵逻辑打成 NaN 就静默少数据
        assert converted[1]["gmag"] == -30.5                                                    # 合法负星等必须存活: 打成 NaN 就静默少数据

    def test_identifier_columns_stay_text(self):
        """标识符列必须留文本: 写成 double 会不可逆地丢精度与前导零 (YZ-50)。

        回归锚点是**真实站点取值**: ``gaia_dr3_18_source_id`` 给的是
        ``4512921183874236032`` (>2^53), float() 之后变
        ``4.512921183874236e+18`` —— 这不是精度损失而是**换了标识符**,
        下游拿它去 join 就再也对不上了。同一份数据走 VOTable 有
        ``column_is_numeric`` 那道护栏, 两出口给出两个不同的 source_id
        更糟 (不知道该信哪个); 护栏判据按**值形态**定, 不按列名猜, 所以
        新星表新增标识符列不必改代码就自动受保护。
        """
        # 四个真实受损形态: 超 2^53 整数 / 前导零 / 精确小整数 (对照) / 测量值 (对照)
        converted = convert_table_rows([{
            "gaia_dr3_18_source_id": "4512921183874236032",  # 真实 ps1/gaia 标识符形态: 超 2^53
            "obj_id": "00001234567890",  # 前导零: 写成 double 就永久丢零
            "small_index": "1234567",  # 对照: 精确整数仍该转 float
            "ra": "1.5",  # 对照: 测量列照常转 float, 不被护栏误伤
        }])
        row = converted[0]
        assert row["gaia_dr3_18_source_id"] == "4512921183874236032"  # 逐字保留: 不是"精度够就行", 是标识符不能改
        assert row["obj_id"] == "00001234567890"  # 前导零保留
        assert row["small_index"] == 1234567.0  # 精确整数转 float 无损, 不必一律留文本
        assert row["ra"] == 1.5  # 测量列不受护栏影响

    def test_identifier_guard_is_the_same_single_point_as_votable(self):
        """护栏必须是单点: CSV 与 VOTable 两出口共用 ``must_stay_text``。

        两处各写一份判据是本缺陷的成因 (CSV 侧当初就没这道门), 所以这条
        守的是"仍然只有一份判据"——任一侧改判据而另一侧没跟上, 这里就红。
        """
        from src.serialization import column_is_numeric, must_stay_text  # 函数内导入: 只在本用例用, 不进模块级导入

        big = "4512921183874236032"  # 真实受损取值
        rows = [{"source_id": big}]  # 单行单列
        assert must_stay_text(big) is True  # 单点判据: 该留文本
        assert convert_table_rows(rows)[0]["source_id"] == big  # CSV 出口遵守它
        assert column_is_numeric(rows, "source_id") is False  # VOTable/FITS 出口也遵守它

    def test_threshold_shared_with_row_models(self):
        """序列化侧判 NaN 的阈值必须与源行模型同源 (双阈值漂移防护)。

        回归锚点: 两侧各写一个魔法数时, 星表侧判缺测而导出侧不判 (或反之), 用户看到
        的 CSV 与 API 结果会对不上; 这里用 floor-0.001 卡住阈值下沿。
        """
        # TAP 序列化与 BestSource 使用同一哨兵阈值 (双阈值漂移防护)
        floor = BestSource.NULL_MAGNITUDE_SENTINEL                   # 阈值取自行模型而非字面量: 双侧各写一个魔法数正是这里要挡的漂移
        converted = convert_table_rows([{"v": str(floor - 0.001)}])  # floor-0.001 贴着下沿: 阈值高一点这条就红, 边界语义被钉死
        assert converted[0]["v"] != converted[0]["v"]                                # NaN 用"自己不等自己"判定: 漏转换时字符串也不等自己, 混得过去


class TestSerializeResult:
    """结果序列化: CSV 公式注入中和、空结果表头、VOTable 转义与状态标记。"""

    def test_csv_output_is_sanitised(self):
        """CSV 单元格里的公式前缀 (=cmd|...) 必须被中和, 否则 Excel 打开即执行命令。

        回归锚点: CSV 注入是真实攻击面; 中和后仍保留 "=cmd" 文本供人眼识别, 但不落
        成可执行公式。同时锁住 media_type/extension 两个响应契约字段。
        """
        result = serialize_result(                                                        # 注入载荷用 Excel 公式前缀: 只过滤分号的实现照样能过
            [{"ps1_ra": "180.0", "note": "=cmd|' /C calc'!A0"}], "csv"  # 注入载荷用 Excel 公式前缀: 中和实现若只过滤分号, 这条照样过
        )
        text = result.body.decode("utf-8")                                                          # 读回响应体: 中和效果只能从落盘字节上看
        # media_type 与 extension 成对断: 网关靠这两个字段决定响应头与下载文件名,
        # 只断文本内容的话, 响应声明成 JSON 而内容是 CSV 照样通过
        assert result.media_type == "text/csv"                                                  # media_type 要对: 网关靠它决定响应头
        assert result.extension == ".csv"                                                      # extension 要对: 网关靠它决定下载文件名
        assert "'=cmd" in text  # 公式向量被中和, 不是原样落盘
        # 同组里的正常数值列必须完好: 中和若实现成"给整行加引号前缀"会连带
        # 污染数值, 这条数值断言就是挡那种过度中和的
        assert "180.0" in text                                                               # 正常数值列必须完好: 挡"给整行加引号前缀"的过度中和

    def test_csv_keeps_declared_columns_for_empty_results(self):
        """零结果也要按调用方声明的列输出表头, 否则客户端拿不到字段结构。"""
        # 传 columns 是关键: 不传的话实现可以退化成"输出空文本", 客户端拿到
        # 连表头都没有, 分不清"查到了 0 条"与"查询失败了"
        result = serialize_result([], "csv", columns=["ps1_ra", "ps1_dec"])              # 传 columns 是关键: 不传的话实现可以退化成输出空文本
        # 只取首行比对: 断整个 body 会把"表头后多出一行空数据"也放过去
        assert result.body.decode("utf-8").splitlines()[0] == "ps1_ra,ps1_dec"           # 只取首行比对: 断整个 body 会放过"表头后多一行空数据"

    def test_votable_error_document_escapes_text(self):
        """错误文档必须 XML 转义用户文本 (<,>,&), 否则畸形 VOTable 让客户端解析崩。"""
        body = votable_error("bad <query> & \"quotes\"").decode("utf-8")  # 三种元字符齐发: 少转义任一种, 客户端解析器就在这里崩
        assert "&lt;query&gt;" in body                                                      # 尖括号必须转义: 少转义任一种, 客户端解析器就在这里崩
        assert "&amp;" in body                                                                      # 与号同样要转义
        assert "QUERY_STATUS" in body                                                             # 状态字段必须在场: 客户端靠它区分成功与失败

    def test_votable_serialization_needs_astropy(self):
        """VOTable 输出依赖 astropy; 缺失时本用例 skip 而不是 fail (软依赖契约)。"""
        pytest.importorskip("astropy.io.votable")                                               # 软依赖: 缺 astropy 时跳过而不是判失败
        result = serialize_result([{"ps1_ra": "180.0", "ps1_rpsf": "15.0"}], "votable")            # 最小成功结果: 这条验的是序列化而不是数据
        assert result.media_type == "application/x-votable+xml"                            # media_type 必须是 VOTable 的 MIME
        assert b"VOTABLE" in result.body                                                            # 根标签在场: 只断标签挡不住状态位缺失
        assert b'name="QUERY_STATUS" value="OK"' in result.body  # QUERY_STATUS=OK 是客户端的成功判据: 只断 VOTABLE 标签挡不住状态位缺失

    def test_votable_overflow_marker_is_appended(self):
        """overflow=True 时 VOTable 必须带 QUERY_STATUS=OVERFLOW, 告知客户端结果被截断。"""
        pytest.importorskip("astropy.io.votable")                                                  # 同样按软依赖跳过: 这条也要真正序列化一次
        result = serialize_result([{"ps1_ra": "180.0"}], "votable", overflow=True)  # overflow 要透传到文档: 截断却报 OK 即事故说成成功
        assert b'value="OVERFLOW"' in result.body                                     # 状态位必须标 OVERFLOW: 截断却报 OK 就是把事故说成成功
