"""test/unit/serialization/test_output_formats.py — 输出格式层的回归测试。

守四类回归, 每一类都对应一个已经真实发生过的静默事故:
  1. VOTable 列类型按取值推断 (数值列不得塌缩成 char) — 塌缩后按列类型解析的
     下游全部拿到文本; 推断必须在每条写出路径上都生效, 不能只修一条分支;
  2. 标识符列 (source_id 等) 即使全数值也保持字符串 — 前导零/大整数精度/相等比较;
  3. 未知格式显式抛错而不是静默回落 JSON — 回落会让请求 fits 的调用方拿到
     .json 文件, 扩展名与内容互相矛盾且无任何提示;
  4. TSV 分隔符判别只看表头行 — 数据行里的逗号会错拆列且不抛异常。
"""
from __future__ import annotations

# 标准库: csv 读回分隔符文本做列序断言 / io 把文本包成文件对象给 csv 模块 /
# json 解析 JSON 导出做 round-trip 断言
import csv
import io
import json

# 第三方: pytest — 参数化与 importorskip (astropy 缺失时跳过而不是失败)
import pytest

# 本地: protocol 的 CSV/TSV 解析入口 (分隔符判别的被测对象) /
# serialization 是被测的输出格式单一事实源 (白名单/类型推断/写出)
from src.protocol import parse_csv_rows  # 分隔符判别的被测对象 (只看表头行)
from src.serialization import (  # 被测的输出格式单一事实源: 白名单/类型推断/写出
    LOCAL_EXPORT_FORMATS,  # 本地可导出集: 比线上集多一项
    SUPPORTED_OUTPUT_FORMATS,  # 线上支持集: 传给服务端的格式只能取自这里
    column_is_numeric,  # 列数值性判定: 类型推断的依据
    delimited_text,  # 分隔文本写出: 判别与写出是同一层
    is_identifier_column,  # 标识符列判定: 决定该列保持字符串
    is_magnitude_column,  # 星等列判定: 决定该列的物理单位
    json_document,  # JSON 文档构造
    normalize_output_format,  # 格式归一: 未知格式必须抛错而不是静默回落
    votable_document,  # VOTable 文档构造: 类型推断的输出面
)


class TestFormatWhitelist:
    """格式白名单: 线上格式与本地格式必须分开声明。"""

    def test_local_superset_of_server_formats(self):
        """本地可导出集必须是线上支持集的超集 (只多一个 fits)。"""
        assert set(SUPPORTED_OUTPUT_FORMATS) < set(LOCAL_EXPORT_FORMATS)                  # 本地集必须是线上集的真超集: 少一种就是本地导出能力静默流失
        # 差集必须恰好是 fits 一项: 写成"只增不减"就挡不住"顺手把某个线上格式
        # 从本地集合里删掉"这种改动 —— 那会让本地导出突然少一种可写格式
        assert set(LOCAL_EXPORT_FORMATS) - set(SUPPORTED_OUTPUT_FORMATS) == {"fits"}  # 恰好一项

    def test_fits_is_not_a_server_format(self):
        """fits 不得混进线上格式集 — 那会让人以为能给服务端传 output.fmt=fits。"""
        assert "fits" not in SUPPORTED_OUTPUT_FORMATS  # 挡"本地格式被当线上格式下发"

    @pytest.mark.parametrize("fmt", ["csv", "txt", "json", "votable", "fits"])
    def test_whitelisted_formats_normalise(self, fmt):
        """白名单内的格式原样归一小写。"""
        # 大小写两向都断言: 大小写归一若被摘掉, 只测小写输入的用例会永远通过
        assert normalize_output_format(fmt) == fmt                                                  # 小写原样返回
        assert normalize_output_format(fmt.upper()) == fmt  # 挡"只测小写"的半边覆盖

    @pytest.mark.parametrize("fmt", ["dbgrid", "ipac", "hdf5", "parquet", "", "xml"])
    def test_unknown_formats_raise_instead_of_silent_fallback(self, fmt):
        """未知格式必须显式抛错, 列出可选值 — 绝不静默改格式。

        静默回落等价于在 else 分支把任何未知格式写成 JSON 并改扩展名为 .json:
        调用方请求 FITS 拿到一个 JSON 文件且无任何提示, 下游按 FITS 解析
        以难懂的格式错误失败, 而按扩展名判断的调用方以为拿到的是 JSON。
        """
        with pytest.raises(ValueError, match="unsupported output format"):                # 错误文案是唯一线索: 静默回落会让调用方以为拿到了请求的格式
            normalize_output_format(fmt)                                                            # 未知格式必须抛而不回落


class TestColumnTypeInference:
    """列类型推断: 按取值判数值, 但标识符列永远保持字符串。"""

    def test_numeric_column_detected(self):
        """全数值列判 True (含负号/小数/科学计数法)。"""
        rows = [{"a": "1.5"}, {"a": "-2"}, {"a": "3e4"}]  # 三种数值形态各一格
        assert column_is_numeric(rows, "a") is True                                      # 全数值列判为数值: 列类型塌缩成 char 就是这条要挡的事故

    def test_mixed_column_is_text(self):
        """任一非空值解析失败即判字符列。"""
        rows = [{"a": "1.5"}, {"a": "GOOD"}]                                                       # 一列里混了非数值: 该列就不该被当成数值列
        # GOOD 是站点真实的品质标记值: 一列里混进它就说明这列是文本, 强行按数值
        # 写出会在 VOTable 里留下无法解析的 cell, 且不抛任何异常
        assert column_is_numeric(rows, "a") is False                                          # 混合列必须判否: 强行转 double 会产出垃圾值

    def test_sparse_column_not_punished_by_empty_cells(self):
        """稀疏列不因空 cell 被误判成字符列。"""
        rows = [{"a": "1.5"}, {"a": ""}, {"a": ""}]  # 仅首格有值, 后两格缺测
        # 判据要跳过空 cell 而不是让空值否掉整列: 站点的缺测列天然大面积为空,
        # 一旦按"任一失败即文本"实现, 所有稀疏数值列都会塌成 char
        assert column_is_numeric(rows, "a") is True                                                 # 整列都是数值串

    @pytest.mark.parametrize(
        "col",                                                                                      # 标识符列的样本清单: 逐个列名都要被认出
        ["ps1_source_id", "source_id", "calibstars_id", "id", "obj_ids", "rowid"],                  # 六个真实列名, 覆盖裸名与带前缀两种形态
    )
    def test_identifier_columns_are_never_numeric(self, col):
        """标识符列即使全数值也判为标识符 (必须保持字符串)。

        写成 double 会: ① 丢前导零 (``007`` → ``7``); ② 超过 2^53 的 id
        精度丢失; ③ 下游按 ID 做相等比较时 ``"123"`` 与 ``123.0`` 不再相等。
        """
        assert is_identifier_column(col) is True  # 挡"按取值判类型"覆盖掉标识符特例

    @pytest.mark.parametrize("col", ["ps1_ra", "ps1_rpsf", "ps1_ebv", "obj_name"])
    def test_measurement_columns_are_not_identifiers(self, col):
        """测量列不得被误判成标识符 (否则数值列会全变字符串)。"""
        assert is_identifier_column(col) is False                                           # 非标识符列不得被误认成标识符: 误认会让星等列保持字符串

    @pytest.mark.parametrize(
        "col",                                                                                      # 星等列的样本清单
        ["ps1_rpsf", "ps1_gmag", "splus_dr4_u_pstotal", "gaia_dr3_18_phot_g_mean_mag"],             # 四个真实列名, 覆盖带前缀与嵌套命名空间
    )
    def test_magnitude_suffixes_come_from_the_protocol_table(self, col):
        """星等列后缀必须覆盖各星表的真实列名 (来自 CATALOG_MAG_COLUMNS 推导)。

        旧规则只判 ``endswith("mag")``, 漏掉全部 PSF 星等 (``ps1_rpsf``) 与
        S-PLUS 的 ``u_pstotal`` 一类列名 —— 这些列拿不到 ``unit="mag"``,
        TOPCAT 侧无法做星等换算且不抛异常。
        """
        assert is_magnitude_column(col) is True  # 挡"退回 endswith('mag')"的旧窄规则

    @pytest.mark.parametrize("col", ["ps1_ra", "n_matches", "ps1_source_id"])
    def test_non_magnitude_columns_are_not_magnitudes(self, col):
        """坐标/计数/标识符列不得被误判成星等列。"""
        assert is_magnitude_column(col) is False                                       # 非星等列不得被误认: 误认会挂上物理单位, 科学消费端据此读错量纲


class TestVotableDocument:
    """VOTable 写出: 类型/单位/转义三条硬约束。"""

    ROWS = [                                                                                        # 固定样本行: 类型推断与转义都靠它
        {"ps1_source_id": "123456789", "ps1_ra": "180.0", "ps1_dec": "30.0",                    # 标识列刻意用纯数字: 证明标识列不会被当成数值列
         "ps1_rpsf": "15.23", "ps1_rflags": "GOOD", "note": "a & b < c"},                           # 坐标、星等、标志位与含元字符的备注
    ]

    def test_numeric_columns_get_double_datatype(self):
        """数值列必须写 datatype=double — 塌缩成 char 会让科学消费端按文本处理数值。"""
        doc = votable_document(self.ROWS, catalog="ps1")                                            # 走真实的 VOTable 构造
        # 同时断言 char 侧: 只查 double 的话, "全部塌成 char"与"全写成 double"
        # 两种故障会互相抵消, 必须两头都钉住
        assert 'datatype="double"' in doc                                               # 数值列必须声明成 double: 塌缩成 char 就是类型事故
        assert 'datatype="char"' in doc  # 反向锚: 防"一律 double"的过度修复

    def test_identifier_column_stays_char(self):
        """source_id 即使全数值也必须是 char。"""
        doc = votable_document(self.ROWS, catalog="ps1")                                            # 同样构造一次
        assert 'name="ps1_source_id" datatype="char"' in doc  # 挡"全数值 id 被判数值列"

    def test_coordinate_and_magnitude_columns_carry_units(self):
        """ra/dec 补 unit=deg, 星等列补 unit=mag — 缺了单位 TOPCAT 无法换算。

        星等列的判定后缀来自协议层权威星等列映射, 因此 ``ps1_rpsf`` (PSF 星等)
        与 ``ps1_gmag`` (平均星等) 都必须拿到 mag 单位; 旧规则只判
        ``endswith("mag")``, 漏掉全部 PSF 星等列。
        """
        doc = votable_document(self.ROWS, catalog="ps1")                                            # 同样构造一次
        assert 'unit="deg"' in doc                                                      # 单位必须落在坐标列上: 缺 unit 的角坐标会让人误读成度以外
        assert 'unit="mag"' in doc  # 缺它: 科学端拿不到星等量纲

    def test_psf_magnitude_columns_also_carry_mag_unit(self):
        """PSF 星等列 (ps1_rpsf 等) 必须补 mag 单位 — 旧规则只认 *mag 后缀。"""
        doc = votable_document([{"ps1_rpsf": "15.2"}], catalog="ps1")  # 单列最小复现
        assert 'name="ps1_rpsf" datatype="double" unit="mag"' in doc  # 类型与单位要同时对

    def test_non_magnitude_numeric_columns_get_no_unit(self):
        """非坐标非星等的数值列不得臆造单位 (如计数列)。"""
        doc = votable_document([{"n_matches": "3"}], catalog="ps1")                              # 无前缀的普通列: 列名识别不能只对带前缀的生效
        assert 'name="n_matches" datatype="double"' in doc                                          # 该列同样要按数值声明
        assert 'name="n_matches" datatype="double" unit' not in doc  # 挡"给所有数值列补单位"

    def test_values_are_xml_escaped(self):
        """列值与列名写入前必须 XML 转义 (站点数据构成的 XML 注入面)。"""
        doc = votable_document(self.ROWS, catalog="ps1")                                            # 同样构造一次
        # 反向断言是这处的重点: 只查转义后的串存在, 挡不住"转义了但也把原文留着"
        # 的实现, 而那仍然是可被下游解析器重新解释的注入面
        assert "a &amp; b &lt; c" in doc                                                            # 元字符必须转义: 不转义就是畸形 XML
        assert "<TD>a & b < c</TD>" not in doc  # 原文残留 = 转义可被下游还原

    def test_empty_rows_still_produce_a_table(self):
        """空结果也要产出带 TABLE 的合法文档 (下游据此看到"0 行"而非解析失败)。"""
        doc = votable_document([], catalog="ps1", nrows=0)                                       # 空行数也要产出合法文档: 零结果同样要能被解析
        assert "<TABLE nrows=\"0\">" in doc  # 挡"空结果抛异常或写空文档"
        assert "</VOTABLE>" in doc                                                                  # 收尾标签必须在: 缺了它整份文档不合法


class TestDelimitedText:
    """CSV/TSV 文本: 列序稳定 + 公式注入消毒。"""

    def test_columns_are_sorted_union(self):
        """列序取排序后的列名并集 — 异构行各保留其列, 回读不错位。"""
        rows = [{"b": "1"}, {"a": "2"}]  # 两行各缺一列: 逼出并集逻辑
        text = delimited_text(rows, ",")                                                            # 写出分隔文本
        # 用 csv.reader 回读而不是字符串 find: 断言的是"回读后列序是什么",
        # 这才是调用方真正看到的契约, 直接比文本会在引号转义上误报
        assert next(csv.reader(io.StringIO(text))) == ["a", "b"]  # 排序后而非出现序

    def test_formula_vectors_are_sanitised(self):
        """公式向量必须消毒 (CSV 公式注入面 Q-06)。"""
        rows = [{"note": "=cmd|'/c calc'!A1"}]  # 以 = 开头: 表格软件会当公式执行
        text = delimited_text(rows, ",")                                                            # 同样写出
        # 消毒形态是前置单引号而非删除: 删除会静默改写用户数据, 前缀是表格软件
        # 通用且可逆的"这是文本"标记
        assert "'=cmd|'/c calc'!A1" in text  # 挡"消毒被摘掉"的注入回归

    def test_negative_numbers_are_not_quoted(self):
        """负数不是公式向量, 必须原样 (旧消毒器把 -5.0 也加引号, 在线数据损坏)。

        样例值取 ``-5.0`` 而不是原版的 ``-1004.07``: 后者正是 ps1 的**缺测
        哨兵带**带心之一 (P0-14 起星等列上的它会被转成 NaN, 见
        ``test_sentinel_export.py``)。本用例要守的是「消毒器别把负号当公式
        起始符」, 与哨兵语义正交 —— 换成同样合法、但不在哨兵带内的负数, 意图
        不变而两类语义不再互相冒充。负到 -1004 的"星等"在物理上不存在
        (最亮恒星约 -30), 故原样例值实为误选。
        """
        rows = [{"ps1_gpsf": "-5.0"}]  # 合法负值 (超新星/极亮源在 -5 量级), 不是缺测
        text = delimited_text(rows, ",")                                                            # 同样写出
        # 双重断言: 正向看值还在, 反向看消毒前缀没被误加 — 少任何一边,
        # "全列加引号"这种过度消毒都能混过去
        assert "-5.0" in text  # 合法负值必须原样写出: 消毒误伤负数时这条会红
        assert "'-5.0'" not in text  # 挡"负号被当成公式起始符"

    def test_sentinel_band_value_is_not_mistaken_for_a_legit_negative(self):
        """反向对照: 哨兵带内的负值走的是「缺测」支, 不走「原样写出」支。

        与上一条成对: 上一条守「合法负值不被消毒误伤」, 本条守「哨兵负值不被
        当成合法负值」。两条都只断自己那一半, 少一条就会有一类错改混过去。
        """
        text = delimited_text([{"ps1_gpsf": "-1004.07"}], ",")                              # 哨兵带内的值
        assert "-1004.07" not in text, "哨兵带内的值被当合法负值原样写出了 (P0-14 回归)"
        assert "nan" in text.lower(), "哨兵带内的值应转 NaN"

    def test_empty_rows_yield_empty_text(self):
        """空输入返回空串 (由调用方决定是否写表头)。"""
        assert delimited_text([], ",") == ""                                                        # 空输入写空串: 不许凭空造一个表头


class TestJsonDocument:
    """JSON 导出: total 语义让人能区分"只有这么多"与"被截断"。"""

    def test_total_is_recorded_when_provided(self):
        """给了 total 就写入 — 调用方据此判断是否被 max_rows 截断。"""
        payload = json.loads(json_document([{"a": "1"}], total=1870))  # 1870 远大于本页 1 条
        assert payload["total"] == 1870  # 挡"total 被 max_rows 覆盖成本页条数"
        assert payload["sources"] == [{"a": "1"}]                                             # sources 必须是数组: 消费方按列表取第一个源

    def test_total_absent_when_not_provided(self):
        """没给 total 就不写这个键 (不臆造 0)。"""
        payload = json.loads(json_document([{"a": "1"}]))  # 不传 total
        # 键必须缺席而不是取 0: 调用方用 "total" in payload 区分"这就是全部"与
        # "总数未知", 写成 0 会让下游把未知当成空集来汇报
        assert "total" not in payload  # 挡"缺失即填 0"让未知伪装成空集


class TestDelimiterSniffing:
    """分隔符判别: 只看表头行, 数据行里的逗号会错拆列且不抛异常。"""

    def test_comma_is_the_default(self):
        """无制表符即按逗号 (站点 output.fmt=csv 是唯一线上取数格式)。"""
        assert parse_csv_rows("a,b\n1,2\n") == [{"a": "1", "b": "2"}]                               # 逗号分隔的 CSV

    def test_tab_is_detected_from_header(self):
        """表头只含制表符即按 TSV 读 (站点 txt 导出 / 人工另存的 TSV)。"""
        assert parse_csv_rows("a\tb\n1\t2\n") == [{"a": "1", "b": "2"}]                           # 制表符分隔的 CSV: 分隔符判别只看表头行

    def test_comma_inside_a_tsv_value_does_not_split_columns(self):
        """TSV 数据行里的逗号不得导致拆列 — 判别只看表头行。

        真实场景: ``output.fmt=txt`` 回的是 TSV, 而 ``obj_name`` 列的值可能
        含逗号 ("M31, NGC 532")。若据**数据行**判别分隔符, 会选中逗号并把
        一列错拆成三列, 整表列序静默偏移且不抛异常 — 这是最难排查的一类
        数据损坏。表头行是列名, 不会含分隔符本身, 是唯一安全的判别位置。
        """
        text = "obj_name\tps1_ra\nM31, NGC 532\t180.0\n"  # 值含逗号, 表头不含
        rows = parse_csv_rows(text)                                                                 # 走真实的解析入口
        assert rows[0]["obj_name"] == "M31, NGC 532"  # 挡"据数据行判别"的静默错拆
        assert rows[0]["ps1_ra"] == "180.0"  # 后一列未整体右移一位

    def test_mixed_header_prefers_comma(self):
        """表头同时含两种分隔符时按逗号 (站点默认口径, 不做天文语义猜测)。"""
        rows = parse_csv_rows("a,b\tc\n1,2\n")  # 表头同时含逗号与制表符
        # 期望的键是 {"a", "b\tc"}: 即分隔符选逗号后, 制表符退化成普通字符留在
        # 列名里, 而不是把这一行再拆一次
        assert set(rows[0]) == {"a", "b\tc"}
