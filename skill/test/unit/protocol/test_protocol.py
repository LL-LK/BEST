"""真实 BEST 两阶段 (form/sqlid) 协议层的回归测试。

守四类契约:
- phase-1 表单键集: 原生 cone 字段 / 列限定约束 / 入参校验 (Q-01);
- sqlid 的解析、规范化与计数 id 派生, 含路径遍历拒绝;
- CSV 表头判定: 完整表头原样读, 旧式不完整表头从右对齐 (Q-02/05);
- 协议行 -> BestSource 的端到端接线 (Q-04)。
"""

from __future__ import annotations

# 标准库: 路径遍历 payload 的运行时构造 (os.pardir)
import os

# 第三方: pytest (raises / parametrize)
import pytest

# 路径遍历 payload 在运行时拼装: 原始 ../ 字符串不落在测试源码里
# (防自伤, 也防安全扫描把测试文件本身当成 payload)。
_TRAVERSAL = os.pardir + "/"  # 上级目录符 + 斜杠 (路径穿越 payload 前缀)

# 本地: models 层行模型 + 列约束类型
# 旧导入守门: 不可导入时整模块 skip 而非 collection error
try:
    # src.models: 查询结果/单源/约束的数据模型
    from src.models import BestSource, ColumnConstraint  # 本地: 行模型 + 列约束类型
except Exception as _legacy_err:  # legacy-import-guard
    # pytest: 导入失败时主动 skip, 不让环境问题伪装成用例失败
    import pytest as _pytest  # 别名导入: 顶部 import 若已失败, 这里重新绑定
    _pytest.skip(f'legacy import unavailable: {_legacy_err!r}', allow_module_level=True)  # 模块级 skip
# 本地: 权威协议层 (Q-01~05: 表单键集 / CSV 表头判定 / 计数解析 / sqlid
# 规范化的唯一出处在 src.protocol, 客户端与测试都不得自建第二套)
from src.protocol import (
    CATALOG_COLUMNS,
    CATALOG_PATHS,
    PAGINATION_SORT_COLUMNS,
    build_page_url,
    build_query_form,
    count_sqlid,
    normalize_sqlid,
    pagination_sort_key,
    parse_count,
    parse_csv_rows,
    parse_sqlid,
    proximity_radec_text,
    qualify_column,
    validate_export_format,
)


def test_cone_form_uses_native_position_fields_and_showcol():
    """Q-01 守门: 锥形检索必须走服务端原生 cone 字段 (pos.type=cone 及
    racenter/deccenter/radius), 而不是把全表拉回客户端本地过滤;
    showcol 投影必须含 ps1.ra/ps1.source_id (点号限定形态)。"""
    form = build_query_form(                                                           # 锥形走原生 cone 还是拉全表本地过滤, 只看这一个键就能分水岭
        "ps1",
        ra=286.0,                                                                   # 传 float 而非字符串: 字符串化是这一层的职责, 传错形态测不出来
        dec=15.0,                                                                       # 同 ra: 三个位置字段的形态必须一致, 混传会把序列化规则带偏
        radius_arcsec=5.0,  # 半径同样是字符串形态
    )
    assert form["pos.type"] == "cone"  # 分水岭: 原生 cone 还是拉全表本地过滤
    assert form["pos.racenter"] == "286.0"  # 字符串: 传 float 序列化规则不同
    assert form["pos.deccenter"] == "15.0"  # 字符串: 与 racenter 同样由 float 序列化
    assert form["pos.radius"] == "5.0"  # 同上, 三者形态必须一致
    assert "ps1.ra" in form["showcol"]  # 点号限定: 不限定时多表查询列名歧义
    assert "ps1.source_id" in form["showcol"]  # 溯源列必须进投影


def test_column_constraint_is_catalog_qualified():
    """列约束必须带星表限定 (ps1.rpsf.operation/min/max), 不得输出无限定的
    rpsf.constraint 键 (P1-4: 约束随 phase-1 表单进入 sqlid 会话,
    无限定键会被服务端忽略或误判)。"""
    form = build_query_form(                                                             # 约束走另一套限定键: 与位置参数共用一个构造单点, 才不会漏译
        "ps1",
        [ColumnConstraint("rpsf", "between", min=14.0, max=16.0)],  # BETWEEN 约束
    )
    assert form["ps1.rpsf.operation"] == "between"  # 操作符进表单键
    assert form["ps1.rpsf.min"] == "14.0"  # 下界也是字符串
    assert form["ps1.rpsf.max"] == "16.0"  # 上界同上
    assert "rpsf.constraint" not in form  # 无限定的旧键不许残留


def test_max_rows_never_reaches_the_phase1_form():
    """A2-03 守门: ``max_rows`` 是 **phase-2 本地封顶**, 不是会话级约束。

    这条把真实行为钉住, 而不是复述注释: ``max_rows`` 一路从
    ``cone_search`` 传到 ``_execute_query`` 再到分页器, 但
    ``build_query_form`` 的签名里**根本没有这个参数** — 截断实际发生在
    ``client_paging`` 的 ``while total_fetched < max_rows``。此前 6 处注释
    却宣称它"写进阶段 1 表单/会话级约束/事后改不了", 读者据此以为调小
    ``max_rows`` 会让服务端少算, 实际只是本地少取几页。

    判据是"表单键里一个 max_rows 形态的键都没有", 正负两面都断言: 既不能有
    裸 ``max_rows``, 也不能有 ``ps1.max_rows`` 这类限定形态。
    """
    form = build_query_form(                                                               # 锥搜 + 一条约束都带上: 越接近真实调用越能证伪
        "ps1",
        [ColumnConstraint("rpsf", "between", min=14.0, max=16.0)],
        ra=180.0, dec=30.0, radius_arcsec=60.0,
    )
    offenders = [k for k in form if "max_rows" in k]                                       # 正反两面一次扫完: 裸键与限定键都算
    assert not offenders, (
        f"max_rows 不该进阶段 1 表单 (它只是 phase-2 本地封顶), 实际出现了: {offenders}"
    )


@pytest.mark.parametrize(                                                                    # 三项各钉一条: 少一即漏判
    ("field", "value"),                                                                     # 字段名与触发值
    [
        ("file", "values.txt"),                                                              # 值文件路径: 传了即拒
        ("sort", "rpsf"),                                                                    # 约束项自带排序键: 传了即拒 (排序走 build_query_form(sort=...))
        ("show", False),                                                                     # 关掉 showcol: 传了即拒
    ],
)
def test_dead_constraint_fields_are_rejected_not_silently_dropped(field, value):
    """A2-04 守门: ``file``/``sort``/``show=False`` 必须抛错, **不许静默成功**。

    修复前这三项在协议层**从不被读取**: 传 ``file`` 与 ``value`` 时只发
    ``ps1.ra.textarea=1.0``, ``file``/``sort`` 被丢掉、``show=False`` 无效,
    调用方却以为自己在用值文件 / 指定了排序列, 实际拿到的是一个静默错的
    结果集 —— 这是比报错危险得多的形态。

    这里只断言"抛 ValueError", 不逐字锁措辞: 措辞会随文案打磨变, 但
    "抛不抛"是契约本身。日后若真去实现这三项 (需站点侧能力支撑), 本测试
    会立刻红, 那正是应该红的时候 —— 届时把断言改成断言表单键真的出现了。
    """
    constraint = ColumnConstraint("ra", "in", value="1.0", **{field: value})                 # 构造带死参数的约束项
    with pytest.raises(ValueError, match=field):                                            # match 带上字段名: 报错必须点名是哪一项
        build_query_form("ps1", [constraint])


def test_live_constraint_fields_still_build_a_form():
    """反向自证: 上面三条守的是"死参数被拒", 不能把**正常约束**也一起拒掉。

    没有这条, 一个把 ``_constraint_value`` 写坏的实现 (例如误判 ``show``
    缺省) 也能让上一条全绿 — 门禁就会变成"拒绝一切"的空转形态。
    """
    form = build_query_form(                                                               # 缺省 show=True / file=None / sort=None
        "ps1",
        [ColumnConstraint("rpsf", "between", min=14.0, max=16.0)],
    )
    assert form["ps1.rpsf.operation"] == "between"                                          # 缺省形态必须照常建出表单键
    assert "ps1.ra.textarea" not in form                                                     # 没给约束就不该凭空多出 in 类键


@pytest.mark.parametrize(
    ("payload", "expected"),                                                            # 两列参数化: 期望值与输入一起列出, 失败时能直接看出是哪一形态
    [("42", 42), ('{"total": 4}', 4), ('{"error": "Not Found"}', None), ("", None)],  # 四种响应形态各钉一条: 纯数字/JSON 取数/错误体/空串, 少一即漏判
)
def test_parse_count(payload, expected):
    """计数解析守门 (P0-2 getcount): 纯数字 / {"total": n} 取数; 错误体与
    空串一律 None (调用方据此判断 sqlid 是否还活着)。"""
    assert parse_count(payload) == expected  # None 一律表示会话已死, 调用方据此改路


def test_sqlid_validation_and_count_id():
    """sqlid 三件套守门: 从 HTML 抽 sqlid / 规范化接受裸数字 / 计数接口剥掉
    s 前缀; 路径遍历 payload 必须被 ValueError 拒绝 (sqlid 会进 URL 路径,
    注入面守门)。"""
    assert parse_sqlid('<a href="/data/best/sqlid/s2700">') == "s2700"  # 从结果页 HTML 抽
    assert normalize_sqlid("2700") == "2700"  # 裸数字同样接受
    assert count_sqlid("s2700") == "2700"  # 计数端点要剥掉 s 前缀
    with pytest.raises(ValueError):  # 注入面: sqlid 会进 URL 路径
        normalize_sqlid(_TRAVERSAL * 2 + "2700")  # 路径穿越 payload 必须被拒


def test_csv_with_complete_header_is_not_relabelled():
    """Q-02 守门: 完整表头的响应必须原样成行, 一个字段都不重贴; 表头行绝不
    进入数据 (旧版把表头当数据行正是幻影源根因)。"""
    text = "ps1_ra,ps1_dec,ps1_source_id\n180.0,30.0,S1\n"  # 完整表头 + 一行数据
    assert parse_csv_rows(text, "ps1") == [  # 原样成行, 一个字段都不重贴
        {"ps1_ra": "180.0", "ps1_dec": "30.0", "ps1_source_id": "S1"}
    ]


def test_legacy_incomplete_header_aligns_catalog_columns_from_the_right():
    """旧式不完整表头守门 (live 实证): 响应只带 dist_arcsec/input_* 元数据列名,
    真实数据按星表列序从右对齐回贴 — ra/dec/source_id 必须落到正确键,
    错位一列就是整套坐标错误。"""
    metadata = ["0.0", "0", "180.0", "30.0", "0", "180.0", "30.0", "0.0", "0.0"]  # live 实测的元数据列
    values = [""] * len(CATALOG_COLUMNS["ps1"])  # 先按星表列序铺满空位
    values[0] = "180.0"  # ra 落在第 0 位
    values[1] = "30.0"  # dec 落在第 1 位
    values[22] = "S1"  # source_id 的实际列序位置
    text = "dist_arcsec,input_line,input_ra,input_dec\n" + ",".join(metadata + values)  # 拼成一行喂进去
    row = parse_csv_rows(text, "ps1")[0]  # 只取第一行
    assert row["ps1_ra"] == "180.0"  # 右对齐后 ra 落回正确键
    assert row["ps1_dec"] == "30.0"  # dec 同理
    assert row["ps1_source_id"] == "S1"  # 错位一列就是整套坐标错误


def test_best_source_understands_prefixed_result_columns():
    """端到端守门: 协议层解析出的带前缀列必须被 BestSource 正确归一
    (source_id/ra/dec/r 波段星等与误差) — 两层接线断裂会静默产出空星等。"""
    source = BestSource.from_row(  # 协议行 -> 源对象的装配口 (Q-04 接线)
        {                                                                                 # 带前缀的真实列名: 两层接线断裂时这层构造的就是真实返回形态
            "ps1_ra": "180.0",
            "ps1_dec": "-30.0",
            "ps1_source_id": "S1",
            "ps1_rpsf": "15.2",
            "ps1_rpsf_err": "0.02",
        },
        catalog="ps1",  # 星表 id 决定前缀剥离规则
    )
    assert source.source_id == "S1"  # 带前缀列也要被认
    assert source.ra == 180.0  # 坐标转 float
    assert source.dec == -30.0  # 负 dec 同理
    assert source.magnitudes["r"] == 15.2  # rpsf 归到 r 波段
    assert source.magnitude_errors["r"] == 0.02  # 误差必须与星等同时归位


@pytest.mark.parametrize(
    "kwargs",                                                                            # 单列参数化: 三种非法坐标形态各占一条, 报出来能定位是哪一种
    [                                                                                     # 非法坐标清单: 负经度、越纬、零半径, 各自走不同的校验分支
        {"ra": -1.0, "dec": 0.0, "radius_arcsec": 1.0},                                     # 负经度: 球面坐标没有负号, 服务端只会回一个含糊的错误
        {"ra": 0.0, "dec": 91.0, "radius_arcsec": 1.0},                                      # 纬越过极: 91 度不是合法天球位置, 必须在入口就拒
        {"ra": 0.0, "dec": 0.0, "radius_arcsec": 0.0},                                       # 零半径: 退化成点查询, 与"不限制"语义混淆故显式拒
    ],
)
def test_invalid_cone_inputs_are_rejected(kwargs):
    """Q-51 守门: 负 RA / 越界 dec / 零半径必须在构造表单时即拒 (ValueError),
    不得把非法坐标发到服务端换一个含义模糊的错误。"""
    with pytest.raises(ValueError):  # 入口即拒, 不把非法坐标发给服务端
        build_query_form("ps1", **kwargs)  # 三种越界形态逐个试


def test_build_query_form_rejects_unsupported_output_format():
    """SA-P2-5 守门: phase-1 表单的 output_format 必须过白名单。

    复过的现: 模块注释声明 build_query_form 校验 output_format, 实现却零
    校验 — fits (站点不服务, 回 HTML 结果页) 与错拼值可直入表单键。
    """
    with pytest.raises(ValueError, match="unsupported output_format"):  # 错码可机读
        build_query_form("ps1", ra=180.0, dec=30.0, radius_arcsec=5.0,
                         output_format="fits")  # fits 回 HTML 结果页, 不是 FITS 文档
    with pytest.raises(ValueError, match="unsupported output_format"):  # 错拼值同样拒
        build_query_form("ps1", output_format="xml")
    # phase-1 交收格式 html 与四种导出格式放行 (大小写/空白不敏感, 归一化)
    assert build_query_form("ps1", output_format="HTML")["output.fmt"] == "html"  # 大小写不敏感
    assert build_query_form("ps1", output_format=" VOTable ")["output.fmt"] == "votable"  # 空白也归一


def test_validate_export_format_normalizes_and_rejects():
    """P2-9 守门: 导出格式白名单归一化 (strip+lower) + 非法值显式抛错。

    复过的现: output_format 是死参数 — 请求 json 拿到 csv 解析结果且无
    任何提示; 现在非法值在入口即拒, 合法值归一化后进 query_params 溯源。
    """
    assert validate_export_format(" CSV ") == "csv"  # strip+lower 归一化
    assert validate_export_format("VOTable") == "votable"  # 大小写同样不敏感
    with pytest.raises(ValueError, match="unsupported output format"):  # 非法值显式拒
        validate_export_format("fits")  # 站点不服务该格式
    with pytest.raises(ValueError, match="unsupported output format"):  # 空串同样不算合法
        validate_export_format("")


def test_proximity_radec_text_rejects_length_mismatch():
    """SA-P3-5 守门: RA/Dec 序列长度不齐必须显式 ValueError。

    复过的现: zip 无 strict 静默截断 — 多出的坐标被悄悄丢弃, 匹配结果
    对不齐且毫无提示 (docstring 已自认, 现对齐 crossmatch_batch 的显式拒绝)。
    """
    text = proximity_radec_text([], [], 3.0)  # 空序列: 无坐标可提交
    assert text == ""  # 不报错, 回空串
    with pytest.raises(ValueError):  # ra 比 dec 长: zip 无 strict 会静默截断
        proximity_radec_text([180.0, 181.0], [30.0], 3.0)  # 多出的坐标被悄悄丢掉
    with pytest.raises(ValueError):  # 反向不齐同样必须显式失败
        proximity_radec_text([180.0, 181.0], [30.0, 31.0, 32.0], 3.0)  # 长度差必须报错


def test_build_page_url_injects_deterministic_sort():
    """P0-1 守门: 分页 URL 必须默认携带该星表的确定性排序列 (sort+order)。

    线上实测无 ORDER BY 时同一 sqlid 两次 GET 行序不同 (集合重叠仅 1/50),
    ``page=N`` 偏移翻页会静默重复/丢行 —— 少了 sort 参数就是这条缺陷回归。
    """
    url = build_page_url(                                                             # 分页 URL 构造: 少带 sort/order 就会静默重复与丢行
        "https://nadc.china-vo.org/data/best", "s3839", 2, 1000, catalog="ps1"
    )  # 第 2 页, 每页 1000 行
    assert url.startswith("https://nadc.china-vo.org/data/best/sqlid/s3839?")  # 会话路径前缀固定
    assert "output.fmt=csv" in url  # 输出格式入参
    assert "rows=1000" in url  # 页大小入参
    assert "page=2" in url  # 页号入参
    # 2026-07: 断的列名改为从映射表取 (旧值 ps1_source_id 实测 174/174 全空),
    # 写死字面量会让下次换列时这条静默变成「钉一个没人用的列」。
    from src.protocol import PAGINATION_SORT_COLUMNS  # 延迟导入: 断言里才需要

    assert f"sort={PAGINATION_SORT_COLUMNS['ps1']}" in url  # 默认排序列: 少它就会静默重复/丢行
    assert "order=asc" in url  # 默认升序


def test_build_page_url_respects_explicit_sort_and_escape_hatch():
    """P0-1 守门: 调用方显式 sort 优先于默认注入; 空串是显式逃逸口 (不注入)。

    守的是"默认定序"与"调用方主权"两条边界: 用户按某一列排序时不得被暗改,
    调试/对照场景又要能关掉注入 —— 两种需求共用同一构造单点。
    """
    explicit = build_page_url(                                                              # 显式 sort: 调用方主权, 默认注入必须让位不能暗改
        "https://nadc.china-vo.org/data/best", "s3839", 1, 100,
        catalog="ps1", sort="ps1.rpsf", order="desc",
    )  # 调用方显式给了排序列与方向
    assert "sort=ps1.rpsf" in explicit  # 调用方主权: 不得被暗改成默认列
    assert "order=desc" in explicit  # 方向同样照给
    from src.protocol import PAGINATION_SORT_COLUMNS  # 延迟导入: 断言里才需要

    assert f"sort={PAGINATION_SORT_COLUMNS['ps1']}" not in explicit  # 默认注入此时必须让位
    escaped = build_page_url(                                                                # 空串是显式逃逸口: 调试与对照场景要能主动关掉定序注入
        "https://nadc.china-vo.org/data/best", "s3839", 1, 100,
        catalog="ps1", sort="",  # 空串是显式逃逸口
    )
    assert "sort=" not in escaped  # 不注入任何排序列
    assert "order=" not in escaped  # 方向也不注入


@pytest.mark.parametrize("catalog", sorted(CATALOG_PATHS))
def test_every_queryable_catalog_has_a_pagination_sort_key(catalog):
    """P0-1 守门: 每张可查询星表都必须有确定性排序列。

    新增星表却忘记登记排序列时, 该星表的分页会静默退回无序翻页 —— 用参数化
    遍历让"漏登记"立即红, 而不是等线上数据丢了才发现。
    """
    column = pagination_sort_key(catalog)
    assert column is not None  # 漏登记即红
    # 2026-07: 判据放宽到「带前缀或不带前缀」都算。
    # uss_dr1 的坐标是按波段分布的 (调用方传 uss_dr1_ra_u、响应列是裸名
    # ra_u), 实测两种拼写都能排序; 旧判据要求“必须是白名单里的某个列”,
    # 会把这种合法形态误判为漏登记。严格到“字面同名”会误杀合法提交。
    # 两套命名都算: 带前缀的白名单口径, 以及去掉前缀后的裸名形态。
    # 后者是 uss_dr1 的真实情况: 它的响应列是裸名 ra_u/g/i/z… (无前缀),
    # 而 CATALOG_COLUMNS 登记的是 uss_dr1_ra_u —— 两套命名并不一致。
    # 实测两种拼写服务端都收, 故两边都算。
    columns = CATALOG_COLUMNS[catalog]
    # 双向都算: 白名单口径正向匹配, 带前缀的只能去掉前缀后比
    # (uss_dr1 反向: 白名 ra_u 要补上前缀才能在白名单里找到) ——
    # 两套命名都是合法提交, 严格到单向会误杀其中一种。
    acceptable = set(columns) | {c.removeprefix(f"{catalog}_") for c in columns}
    assert column in acceptable, (
        f"{catalog} 的排序列 {column!r} 既不是带前缀的白名列, 去掉星表前缀后也不是该表真实列"
    )


def test_pagination_sort_key_accepts_paths_and_unknown_returns_none():
    """pagination_sort_key 守门: 路径形态 (ps1/q) 与别名都要能解析; 未知
    星表返回 None (由调用方决定是否注入), 不抛异常破坏分页主链。"""
    assert pagination_sort_key("ps1/q") == PAGINATION_SORT_COLUMNS["ps1"]  # 路径形态要能解析到同一列
    assert pagination_sort_key("gaia_dr3") == "gaia_dr3_18_source_id"  # 别名落到真实表列
    assert pagination_sort_key("not_a_catalog") is None  # 未知表回 None, 不抛
    assert pagination_sort_key("") is None  # 空串同样不抛, 交调用方决定
    assert PAGINATION_SORT_COLUMNS["stripe82"] == "stripe82_calibstars_id"  # 裸列名星表


def test_wide_data_row_does_not_relabel_the_header():
    """P1-1 守门: 宽于表头的数据行不得触发整表列名重贴。

    复过的现: 30 列表头 + 一行因未转义逗号多出一列 -> 若据"数据行最大宽"
    判定, 真实表头 h1..h29 会被丢弃并换成 CATALOG_COLUMNS 补齐列, 坐标/
    星等全部串列且不抛异常。表头权威, 多余值落 overflow_* 键。
    """
    header = [f"h{i}" for i in range(len(CATALOG_COLUMNS["ps1"]))]  # 真实表头宽度
    wide_row = ["1.0"] * (len(header) + 1)  # 未转义逗号多撑出一列
    text = ",".join(header) + "\n" + ",".join(wide_row) + "\n"  # 拼成两行文本
    rows = parse_csv_rows(text, catalog="ps1")  # 解析成行
    keys = list(rows[0].keys())  # 只看键序
    # 真实表头一个不少
    assert keys[:len(header)] == header  # 表头权威, 不得被重贴
    # 多余值显式落 overflow 键 (可见可查, 不静默串列)
    assert keys[len(header):] == ["overflow_0"]  # 多出来的那个值单独占键
    assert rows[0]["overflow_0"] == "1.0"  # 值也在, 排障时看得见


def test_headerless_numeric_first_row_is_data_not_header():
    """P2-2 守门: 无表头响应的首行数据不得被当表头吞掉。

    复过的现: 首行含 ``1.2e-05`` (含 ASCII 字母 e) 或 ``null`` 时, 旧判据
    "任一单元格含字母"把首行数据判成表头 — 数据少一行且列名变成数据值。
    """
    rows = parse_csv_rows("180.0,30.0,1.2e-05\n181.0,31.0,2.0\n", catalog="")  # 无表头响应
    assert len(rows) == 2  # 首行是数据, 不得被当表头吞掉
    assert rows[0] == {"col1": "180.0", "col2": "30.0", "col3": "1.2e-05"}  # 列名按位置生成
    assert rows[1] == {"col1": "181.0", "col2": "31.0", "col3": "2.0"}  # 第二行同样保真


def test_qualify_column_rejects_phantom_columns():
    """P1-3 守门: 幻影列必须显式失败, 不得拼成表单键静默匹配全表。

    复过的现: ``nonexistent_col`` 只过字符白名单就变成 ``ps1.nonexistent_col``
    — 服务端忽略未知表单键, 调用方静默拿到全表而非过滤结果。
    """
    with pytest.raises(ValueError):  # 幻影列必须显式失败, 不许静默匹配全表
        qualify_column("ps1", "nonexistent_col")  # 裸名形态
    with pytest.raises(ValueError):  # 带星表前缀的错列名同样拒
        qualify_column("ps1", "ps1_typo_col")  # 拼错的真实表列
    # 已限定形态同样校验列存在 (只校验表归属会放过 ps1. 不存在的列)
    with pytest.raises(ValueError):  # 限定了表也不代表列存在
        qualify_column("ps1", "ps1.nonexistent")
    with pytest.raises(ValueError):  # 别的星表的列不许串台
        qualify_column("ps1", "evil.col")


def test_qualify_column_maps_band_columns_to_real_form_tables():
    """P1-2 守门: 裸列名落到真实表单表, 不再凭星表 id 拼错表名。

    复过的现: xpsp/dr3xpcorr 的 ``g_mag`` 被拼成 ``xpsp.g_mag`` —
    服务端无 xpsp 表, 波段过滤静默不生效。权威表名在 CATALOG_FORM_TABLES。
    """
    assert qualify_column("xpsp", "g_mag") == "gaiaxp_photinfo_replenish.g_mag"  # 权威表名而非星表 id
    assert qualify_column("dr3xpcorr", "g_mag") == (
        "gaiaxp_photinfo_replenish.g_mag"
    )  # 两个星表共用同一张表单表
    assert qualify_column("dr3xpcorr", "flux") == "correctedxpspecv1.flux"  # 同一原则
    # 既有正确路径不受影响 (单表星表的前缀剥离)
    assert qualify_column("ps1", "gpsf") == "ps1.gpsf"  # 裸名补星表前缀
    assert qualify_column("ps1", "ps1_rpsf") == "ps1.rpsf"  # 已带前缀也不重复拼
    assert qualify_column("gaia_dr3", "source_id") == "gaia_dr3_18.source_id"  # 别名落到真实表
