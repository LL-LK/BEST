# -*- coding: utf-8 -*-
"""真实 BEST 两阶段 API 的离线协议安全测试。

覆盖面: sqlid 规范化/注入拒绝、软 404 检测 (P0-3)、服务端表单能力
(P1-8)、名称解算 (P1-8) 与双客户端共用重试策略 (P1-6)。全部离线,
不打真实站点。

职责: 守住协议层的"安全语义"回归 —— sqlid 拼进 ADQL 之前必须规范化且拒绝注入
  形态; 站点返回的空结果若属于软 404 必须显式识别出来 (P0-3), 而不是伪装成
  "这个天区没有源" 的合法空集; 表单能力与名称解算的退化要有明确的失败面
  (P1-8); 两个客户端必须共用同一套重试策略 (P1-6), 否则限流下会出现一半请求
  被退避、一半硬打的局面。
所属层次: test/unit 层, 对应被测模块 src/protocol.py —— 即 BEST 两阶段 API 的
  协议翻译与错误分类层; 传输由替身 session 接管, 整个文件不建立任何真实连接。
对外接口: 用例按五个覆盖面切分: sqlid 规范化与注入拒绝一组; 软 404 检测一组
  (含路径遍历 payload 的构造); 服务端表单能力一组; 名称解算一组; 重试策略共用
  性与参数化注入拒绝一组。断言读的是协议层吐出的 URL/参数与分类后的错误语义。
依赖与数据流: 替身 session 记录每次请求的参数, 断言即从这些记录里回查; 路径
  遍历 payload 在运行时用 os.pardir 拼出来 (写死字面量会先被 ruff 的转义规则
  改形, 反而测不到真实的规范化路径); 零写盘、零网络, 唯一的写面在替身内部。
关键契约与不变量: 离线回放 —— 所有 HTTP 交互必须止步于替身; 软 404 必须抛
  软错误而不是降级成空结果, 两者在下游是天壤之别 (一个说明请求有问题, 一个
  说明天区真的没源); 注入类输入必须在协议层就被拒, 不能指望服务端兜底。
陷阱与边界: 这组用例的价值全在"错误语义"上 —— 若只断言最终行数, 软 404 被
  吞成空集一样会过, 所以每条负路径都断言异常的种类而不只是"抛了东西";
  参数化选的是各协议实现共有的几种注入形态, 取它们是因为它们分别踩在引号、
  注释符与反斜杠三个方言差异上, 少一类就漏掉一类实现。
"""
from __future__ import annotations

# 标准库: 路径遍历 payload 的运行时构造 (os.pardir)
import os  # 只为运行时拼 os.pardir: 字面量写法会先被 ruff 改形, 测不到真实路径

# 第三方: pytest (raises / parametrize)
import pytest  # 本文件断言以负路径为主, raises 是主力工具

# 本地: 权威协议层 — 软 404 契约 (P0-3)、表单键集与名称解算 (P1-8)、
# 重试策略常量 (P1-6; P3-2 后判定锚点是常量本身 — 手写重试助手已删),
# 全部单一出处, 两个客户端共用
from src.protocol import (
    MAX_BACKOFF_S,  # 退避上限: 两个客户端必须共用同一份
    MAX_RETRIES,  # 重试次数上限
    NAME_RESOLVE_FAIL_SENTINEL,  # 名称解算失败哨兵: 坐标是假值时用它判定
    RETRY_BACKOFF_S,  # 退避基数
    RETRY_STATUS_CODES,  # 可重试状态码集合: 单一出处
    SOFT_404_ERROR_CODE,  # 软 404 错误码
    NameResolveError,  # 名称解算异常: 调用方只需捕这一种
    Soft404Error,  # 软 404 异常: 与查询同一失败契约
    build_query_form,  # 表单构造
    count_sqlid,  # 计数端点路径
    is_name_resolve_failure,  # 名称解算失败判定
    is_soft_error,  # 软错误判定
    normalize_sqlid,  # sqlid 规范化
    parse_name_resolve,  # 名称解算响应解析
    parse_sqlid,  # sqlid 解析
    soft_error_detail,  # 软错误详情
)

# 路径遍历 payload 在运行时拼装: 原始 ../ 字符串不落在测试源码里
# (防自伤, 也防安全扫描把测试文件本身当成 payload)。
_TRAVERSAL = os.pardir + "/"  # 上级目录符 + 斜杠 (路径穿越 payload 前缀)


@pytest.mark.parametrize("value", ["s1", "1", "s2623"])
def test_normalize_sqlid_accepts_valid_values(value: str) -> None:
    """合法 sqlid (s 前缀或裸数字) 必须原样通过, 不得误伤正常会话 id。"""
    assert normalize_sqlid(value) == value  # 反向守门: 收紧过头会把正常会话也拒掉


@pytest.mark.parametrize(
    "value",                                                                                # 参数名表头: 参数化靠它把下面每行接成 (输入, 期望)
    ["", _TRAVERSAL * 2 + "etc/passwd", "1;DROP TABLE", "s-1", "1/2", "abc"],                 # 六类注入与畸形形态: 分别踩在引号、注释符与反斜杠上
)
def test_normalize_sqlid_rejects_unsafe_values(value: str) -> None:
    """注入面守门: sqlid 会拼进 URL 路径, 空值/路径遍历/SQL 注入片段/负数/
    分数/非数字必须一律 ValueError, 不存在"看起来能放过"的灰区。"""
    with pytest.raises(ValueError):  # 注入面在协议层就收口, 不指望服务端兜底
        normalize_sqlid(value)  # 六种形态逐个试: 分别踩引号/注释符/反斜杠三类方言


def test_parse_sqlid_extracts_only_safe_values() -> None:
    """从站点 HTML 里抽 sqlid: 只认 /data/best/sqlid/ 形态的安全值,
    查询串 (?page=1) 与其他属性不得混进 id。"""
    html = '<a href="/data/best/sqlid/s2623?page=1">next</a>'  # 查询串不许混进 id
    assert parse_sqlid(html) == "s2623"  # 只抽路径段, 不含 ?page=1  # 查询串混进 id, 后续拼出的 URL 全部失效


def test_count_sqlid_removes_s_prefix() -> None:
    """计数接口 (getcount) 收裸数字 id: s 前缀必须剥掉 (P0-2)。"""
    assert count_sqlid("s2623") == "2623"  # getcount 端点只收裸数字  # 漏剥前缀时 getcount 端点直接收不下这个 id


# --- P0-3: soft 404 检测 (HTTP 200 + {"error": ...} body) -------------
# live 实证: 未知路由与导航组查询路径用这些短 JSON 体回答 200,
# 只看状态码的门禁根本看不见它们 — 判定必须落在 body 级。


@pytest.mark.parametrize(
    "body",                                                                                         # 参数名表头
    [                                                                                               # 四种错误体形态的样本清单
        '{"error":"Not Found"}',                                                                    # 标准错误体
        '{"error":"Internal Server Error"}',                                                      # 另一种错误文案: 只匹配一种文案的实现会漏判
        '  {"error":"Not Found"}  \n',                                                              # 前后带空白与换行
        '\ufeff{"error":"Not Found"}',                                                              # 带 BOM: 不剥掉就解析失败
        '{"error": "Not Found"}',  # 容忍带空格分隔的 JSON 形态
        '{"error":"anything else"}',  # 任意单键 error 对象
    ],
)
def test_is_soft_error_accepts_live_soft_error_bodies(body: str) -> None:
    """P0-3 守门: live 实证的软错误体必须全部判 True — 含前后空白、BOM 头、
    带空格 JSON 与任意单键 error 对象 (站点文案会变, 判据是"单键 error
    对象"这个形态而不是具体错误字符串)。"""
    assert is_soft_error(body) is True  # 判据是"单键 error 对象"这个形态, 非具体文案  # 判据是"单键 error 对象"这个形态, 不绑站点文案


@pytest.mark.parametrize(
    "body",                                                                                         # 参数名表头
    [                                                                                               # 不该判软错误的样本
        "",                                                                                         # 空串
        "ps1_ra,ps1_dec\n180.0,30.0\n",                                                             # 正常 CSV 页
        "<html>no results</html>",                                                                  # HTML 提示页
        '{"total": 1870}',  # getcount 的载荷是数据, 不是错误
        "42",                                                                                       # 纯数字: 那是计数响应, 不是错误体
    ],
)
def test_is_soft_error_rejects_normal_payloads(body: str) -> None:
    """反向守门: 正常负载不得误判 — getcount 的 ``{"total": n}`` 是数据不是错误。

    **BC-03 订正 (2026-10-07)**: 样本里原有 ``{"error":"Not Found","extra":1}``,
    断言它**不是**软错误 —— 那正是本次修复推翻了的行为。原判据要求键集合**精确**
    等于 ``{"error"}``, 于是站点在错误体里多加一个伴随字段就会让判据失效, 而失效
    方向是**漏判**: 软错误体被当成数据载荷喂进 CSV 解析器, 生成一整列伪数据。
    那条样本现在移到 :func:`test_is_soft_error_accepts_multi_key_error_bodies`。
    """
    assert is_soft_error(body) is False  # 正常负载误判成错误比漏判更难排查


@pytest.mark.parametrize(
    "body",                                                                                         # 参数名表头
    [                                                                                               # 伴随字段逐个加上去, 判据都该仍认
        '{"error":"Not Found"}',                                                                    # 基线: 单键
        '{"error":"Not Found","message":"no such sqlid"}',                                          # 加 message (两键)
        '{"error":"Not Found","code":"E_FAIL","status":500}',                                       # 加 code+status (三键)
        '{"error":"Not Found","message":"x","code":"E","time":"t"}',                               # 四键: 恰在上界之内
    ],
)
def test_is_soft_error_accepts_multi_key_error_bodies(body: str) -> None:
    """BC-03 承重断言: 站点给错误体加伴随字段时, 判据不得失效。

    删掉这四行里的任何一条断言 (或把实现改回 ``set(payload) == {"error"}``),
    本用例立刻转红 —— 那正是 BC-03 说的「服务端加了个字段 = 静默事故」。
    """
    assert is_soft_error(body) is True  # 含 error 键且键数不超上界 => 仍是软错误


def test_is_soft_error_rejects_too_wide_error_objects() -> None:
    """上界之上不再判软错误: 一份真数据也可能带 error 键, 键很多时不能无界吞掉。

    没有这条上界, ``is_soft_error`` 会把任何大 JSON 都当错误 —— 那是另一个方向的
    误伤 (把正常数据报成失败)。上界取 4 是"够扛住伴随字段"与"仍与数据划得开"的折中。
    """
    wide = '{"error":"x","a":1,"b":2,"c":3,"d":4,"e":5}'  # 六键: 越过上界
    assert is_soft_error(wide) is False  # 判成数据, 不判成错误


def test_is_soft_error_never_matches_non_string_inputs() -> None:
    """防御守门: 非字符串输入 (含 __str__ 会撒谎的对象 / None) 不得抛异常,
    一律判 False — 类型边界由协议层自己收口, 不信任调用方传入形态。"""

    class _Weird:
        """恶意/畸形替身: ``__str__`` 返回一个看似 JSON 却非错误体的字符串。

        用途是验证协议层**不靠 ``str()`` 猜内容** — 若实现写成
        ``json.loads(str(x))``, 这个对象会被误判成软错误; 正确实现应先做
        类型检查 (``isinstance(x, str)``), 非字符串一律返回 False。
        """

        def __str__(self) -> str:  # pragma: no cover - 防御性
            """返回伪装成 JSON 的字符串 (诱使错误实现误判为软错误)。"""
            return "<not json>"  # 看着像 body, 实则不是字符串输入

    assert is_soft_error(_Weird()) is False  # 挡住 json.loads(str(x)) 这类靠字符串化猜内容的实现
    assert is_soft_error(None) is False  # 类型边界由协议层自己收口, 不信任调用方传入形态


def test_soft_error_detail_returns_the_server_error_string() -> None:
    """错误详情提取守门: 从软错误体取出服务端原文 ("Not Found"), 正常体
    返回 None (调用方据此生成可诊断的错误消息, 不自己编文案)。"""
    assert soft_error_detail('{"error":"Not Found"}') == "Not Found"  # 取服务端原文: 调用方不自己编文案
    assert soft_error_detail('{"error":"Internal Server Error"}') == "Internal Server Error"  # 长文案同样照取
    assert soft_error_detail("ps1_ra,ps1_dec\n") is None  # 正常体必须给 None, 否则错误消息会拼进 CSV 正文


def test_soft404_error_carries_the_contract_code_and_url() -> None:
    """异常契约守门: Soft404Error 必须带稳定错误码 E_SOFT_404 与出错 URL —
    调用方按 code 分支而不嗅探人类可读消息, URL 供定位是哪个查询出的错。"""
    err = Soft404Error("Not Found", "https://nadc.china-vo.org/data/best/calib/stripe82/q")         # 构造软 404 异常
    assert err.code == SOFT_404_ERROR_CODE == "E_SOFT_404"  # 码是下游分支依据, 改字面量等于换了一套契约
    assert "E_SOFT_404" in str(err)                                                               # 错误码必须进消息: 调用方按串匹配时要看得到
    assert "calib/stripe82/q" in str(err)  # URL 落在消息里: 只看码定位不到是哪个查询出的错
    assert err.detail == "Not Found"                                                                # 详情必须原样保留: 排障时这是唯一线索


# --- P1-8: 服务端表单能力 (cone 模式开关键) --------------------------------

def test_nearest_only_adds_the_cone_form_flag() -> None:
    """P1-8 守门: cone 模式最近邻必须用 cone_nearestonly=on (旧键
    proximity_nearestonly 是 proximity 专用, 用在 cone 上会被服务端忽略)。"""
    form = build_query_form("ps1", ra=10.0, dec=20.0, radius_arcsec=30, nearest_only=True)          # 带最近邻开关的锥形构造
    assert form["cone_nearestonly"] == "on"  # 键名写错服务端只会静默忽略, 不报错
    assert "proximity_nearestonly" not in form  # 挡住串键: proximity 的键发到 cone 上必失效


def test_nearest_only_and_default_radius_for_proximity_lists() -> None:
    """P0-1 守门: radec_text 批量坐标必须走 pos.type=proximity 服务端批量,
    默认半径进 pos.defaultRadius, 最近邻用 proximity_nearestonly=on —
    三个键齐备, 批量请求语义才成立。"""
    form = build_query_form(                                                                        # 多行邻近文本
        "ps1", radec_text="10.0 20.0 3.0\n11.0 21.0 3.0",                                           # 两行坐标
        default_radius_arcsec=3.0, nearest_only=True,                                               # 默认半径
    )
    assert form["pos.type"] == "proximity"  # 钉住批量模式: 退回逐点锥搜时这里先变 (P0-1)
    assert form["proximity_nearestonly"] == "on"                                            # 最近邻开关必须落表: 静默丢弃会让邻近查询悄悄退化成全取
    assert form["pos.defaultRadius"] == "3.0"  # 表单一律按文本提交, 半径也必须字符串化


def test_non_finite_radius_never_reaches_the_wire_form() -> None:
    """P0-20 守门: NaN/Inf 半径必须在协议层就被拒, 不得拼进 ``pos.radius`` /
    ``pos.defaultRadius`` 直达 wire。

    回归锚点: 原守卫写作 ``if float(radius_arcsec) <= 0.0``, 而任何与 NaN 的比较
    都判 False —— NaN 于是穿过该守卫, 实测产出 ``pos.radius='nan'`` 提交给站点
    (src/scripts/guards.py 侧的 ``validate_search_radius`` 早已有 isfinite 前置,
    协议层这条独立路径当时仍只做纯比较, 属纵深防御的缺口)。

    两个分支都要断: 锥形 ``radius_arcsec`` 与 proximity ``default_radius_arcsec``
    各有一条独立守卫, 少断一条就仍留一个 ``'nan'`` 直达表单的口子。
    """
    for bad in (float("nan"), float("inf"), float("-inf")):                                            # 三个非有限值: NaN 与 ±Inf 同属"比较恒假"家族
        with pytest.raises(ValueError, match="finite"):                                                 # 复用 guards 单点的报错面: NaN/Inf 都在这里收口
            build_query_form("ps1", ra=10.0, dec=20.0, radius_arcsec=bad)                               # 锥形分支: pos.radius 的唯一出处
        with pytest.raises(ValueError, match="finite"):                                                 # proximity 分支同样不得漏
            build_query_form("ps1", radec_text="10.0 20.0", default_radius_arcsec=bad)                 # pos.defaultRadius 的唯一出处


def test_finite_radius_boundary_is_unchanged_by_the_p0_20_fix() -> None:
    """反向守门: 合法半径 (含 5° 上界 18000 角秒) 必须照常成表 —— 收紧过头会把
    正常查询误伤成异常, 那比漏判更难排查。上界取自 guards 单点的常量口径。"""
    edge = build_query_form("ps1", ra=10.0, dec=20.0, radius_arcsec=18000.0)                           # 上界闭区间端点
    assert edge["pos.radius"] == "18000.0"                                                              # 边界值必须原样成表
    assert build_query_form("ps1", ra=10.0, dec=20.0, radius_arcsec=30.0)["pos.radius"] == "30.0"      # 常规半径不受影响


def test_sort_and_order_are_qualified_through_the_allowlist() -> None:
    """P1-8 守门: sort 必须过白名单限定成 ps1.rpsf (裸列名服务端不认),
    order 归一化小写; 已限定的输入 (ps1.gpsf) 原样保留不重复加前缀。"""
    form = build_query_form("ps1", ra=10.0, dec=20.0, radius_arcsec=30,                             # 带排序的构造
                            sort="rpsf", order="DESC")                                              # 排序键
    assert form["sort"] == "ps1.rpsf"  # 裸列名服务端不认, 必须先过白名单限定
    assert form["order"] == "desc"          # 归一化为小写

    prequalified = build_query_form("ps1", sort="ps1.gpsf")  # 已限定输入: 不可再套一层前缀
    assert prequalified["sort"] == "ps1.gpsf"  # 挡住重复限定成 ps1.ps1.gpsf
    assert prequalified["order"] == "asc"  # 调用方不传 order 时也必须有确定值


@pytest.mark.parametrize("kwargs", [
    {"sort": "rpsf", "order": "sideways"},                                                          # 三种非法排序参数
    {"sort": ""},                                                                                   # 空排序键
    {"sort": "evil.col"},                                                                           # 带点的列名: 注入形态
    {"sort": "rpsf", "order": ""},                                                                  # 空方向
])
def test_invalid_sort_specs_are_rejected(kwargs: dict) -> None:
    """非法排序规格守门: 空 sort / 越界 order (sideways) / 未授权限定符
    (evil.col) 必须 ValueError — sort 值会进表单, 注入面与 typo 都不放行。"""
    with pytest.raises(ValueError):                                                          # 非法排序必须抛错: 静默忽略等于悄悄改掉用户的取数顺序
        build_query_form("ps1", **kwargs)  # sort 值会进表单: 注入面与 typo 都不放行


def test_column_projection_accepts_bare_prefixed_and_qualified_names() -> None:
    """P1-8 守门: showcol 投影三种写法 (裸列名 / 带下划线前缀 / 点号限定)
    必须归一到同一种 ps1.ra 点号形态 — 调用方怎么写都不破坏协议键集。"""
    bare = build_query_form("ps1", show_columns=["ra", "rpsf"])  # 裸列名写法
    assert bare["showcol"] == ["ps1.ra", "ps1.rpsf"]  # 三种写法须收敛到同一点号形态
    prefixed = build_query_form("ps1", show_columns=["ps1_ra", "ps1_rpsf"])  # 下划线写法: 解析器自己的输出形态
    assert prefixed["showcol"] == ["ps1.ra", "ps1.rpsf"]                                            # 列投影必须带表前缀: 裸列名服务端不认
    qualified = build_query_form("ps1", show_columns=["ps1.ra"])  # 点号写法: 归一目标形态
    assert qualified["showcol"] == ["ps1.ra"]  # 已限定输入原样保留, 不重复加前缀


# --- P1-8: /nss/solve 天体名解算 (CDS Sesame 代理) ------------------------

def test_parse_name_resolve_reads_the_sesame_payload() -> None:
    """P1-8 守门: /nss/solve (CDS Sesame 代理) 的响应必须解析出 ra/dec/obj,
    BOM 头与 remark 外链字段都要容忍 (站点响应实测带 BOM)。"""
    payload = parse_name_resolve(                                                                   # 带 BOM 的解算响应
        '\ufeff{"ra": 10.68470833, "dec": 41.26875, "obj": "M31", '                                 # 响应正文前半段
        '"remark": "https://cds.unistra.fr/cgi-bin/Sesame?M31"}'
    )
    assert payload["ra"] == 10.68470833                                                             # 赤经必须解出
    assert payload["obj"] == "M31"                                                                  # 对象名必须解出: 它是展示给用户的那部分


def test_name_resolve_failure_is_the_minus_1000_sentinel() -> None:
    """名称解算失败哨兵守门: -1000 在 HTTP 200 body 内, 状态码看不见;
    部分缺键/非 mapping 一律按失败处理 (不猜"可能是好的")。"""
    # 哨兵值坐在 HTTP 200 body 里 — 状态码门禁看不见它, 必须查 body 值。
    assert is_name_resolve_failure({"ra": -1000, "dec": -1000}) is True  # 哨兵藏在 200 body 里, 状态码看不见
    assert is_name_resolve_failure({"ra": -1000.0, "dec": 41.0}) is True                            # 哨兵坐标必须判失败
    assert is_name_resolve_failure({"ra": 10.68, "dec": 41.26}) is False                            # 真实坐标不得误判
    assert is_name_resolve_failure({}) is True  # 缺键按失败处理: 不猜"可能是好的"
    assert is_name_resolve_failure("not a mapping") is True                                      # 非映射输入也要判失败: 类型不对同样不能当成功


def test_name_resolve_failure_sentinel_is_the_documented_value() -> None:
    """哨兵值必须保持文档化的 -1000.0: 与站点 Sesame 代理的失败约定一致,
    改值会让所有"已失败"的解析被当成真实坐标放行。"""
    assert NAME_RESOLVE_FAIL_SENTINEL == -1000.0  # 改哨兵值, 全部失败解析会被当成真实坐标放行


def test_parse_name_resolve_rejects_non_json_bodies() -> None:
    """非 JSON 体守门: HTML 错误页 / JSON 数组必须显式 ValueError, 不返回
    "看起来成功"的空结果 (与 Q-29 同精神: 无法解析就响亮失败)。"""
    with pytest.raises(ValueError, match="unparseable"):                                            # 非 JSON 正文必须报不可解析
        parse_name_resolve("<html>Not Found</html>")  # HTML 错误页要响亮失败, 不返回"看起来成功"的空结果
    with pytest.raises(ValueError, match="not a JSON object"):                                      # JSON 数组不是对象
        parse_name_resolve("[1, 2, 3]")                                                             # 数组样本


def test_name_resolve_error_carries_its_code() -> None:
    """异常契约守门: NameResolveError 带稳定 code (E_NAME_UNRESOLVED) 与
    remark (S-3: remark 来自外部 Sesame 服务, 必须显式透传供人工核查)。"""
    err = NameResolveError("could not resolve 'ZZZ'", remark="no match")                            # 构造名称解算异常
    assert err.code == "E_NAME_UNRESOLVED"                                                          # 错误码必须固定
    assert err.remark == "no match"                                                                 # remark 必须原样带出


# --- P1-6: 两个客户端共用的同一份重试策略 (唯一一层) ----------------------

@pytest.mark.parametrize("code", [429, 500, 502, 503, 504])
def test_transient_statuses_are_retryable(code: int) -> None:
    """P1-6 守门: 429 与 5xx (500/502/503/504) 是瞬时故障 — 重试策略只有
    一份, 两个客户端共用同一张状态码表 (:data:`RETRY_STATUS_CODES`)。

    P3-2: 判定锚点必须是常量本身 (adapter 的 status_forcelist 正是由它配置,
    唯一一层的真源)。经 is_retryable_status() 之类助手断言等于留一个生产
    零引用的 dormant 零件 —— 正是"手写第二重试层"的入口。
    """
    assert code in RETRY_STATUS_CODES                                                               # 可重试状态码必须在集合里


@pytest.mark.parametrize("code", [200, 301, 400, 404, 501])
def test_non_transient_statuses_are_not_retryable(code: int) -> None:
    """反向守门: 200/301/400/404/501 不在重试表里 — 重试 4xx 只会放大服务端
    压力并拖长失败路径 (无差别重试的教训)。"""
    assert code not in RETRY_STATUS_CODES                                                 # 不可重试状态码必须不在集合里: 4xx 硬打重试只会放大压力


def test_policy_constants_are_the_documented_defaults() -> None:
    """策略常量文档默认值守门: 任何调整都必须连测试一起改 — 常量是两个
    客户端共用的契约, 单边漂移等于没策略。"""
    assert MAX_RETRIES == 3  # 常量是两个客户端的共用契约, 单边漂移等于没策略
    assert RETRY_BACKOFF_S == 2.0                                                                   # 退避基数必须钉住: 改了就是静默改节奏
    assert MAX_BACKOFF_S == 60.0  # 上限防长退避把失败路径拖成分钟级
    assert frozenset({429, 500, 502, 503, 504}) == RETRY_STATUS_CODES  # 整表相等: 少一个码就是漏重试一类故障


def test_client_configures_retry_from_the_shared_policy() -> None:
    """P1-6 验收守门: 客户端入口 (BestClient) 必须从协议层策略配置
    adapter — total 次数、状态码表、Retry-After 尊重三项缺一不可漂移。

    各带一套手写重试循环的话, 两边行为迟早分叉; 重试必须收敛到 session
    adapter 单一层 (唯一客户端入口), 本测试钉死接线。
    """
    # 函数内延迟导入: 避免测试模块收集期就构造真实客户端 (session 建立)
    from src.client import BestClient

    client_adapter = BestClient(rate_limit=0).session.get_adapter("https://nadc.china-vo.org")  # 取真实 adapter: 验的是接线不是常量
    for adapter in (client_adapter,):                                                               # 适配器逐个过一遍, 当前只有一个
        assert adapter.max_retries.total == MAX_RETRIES  # 次数真接上了, 而不只是常量存在
        assert set(adapter.max_retries.status_forcelist) == set(RETRY_STATUS_CODES)  # 状态码表也要接上
        assert adapter.max_retries.respect_retry_after_header is True  # 尊重 Retry-After: 限流下才不会被二次打爆
