# -*- coding: utf-8 -*-
"""BestClient 分页 URL 定序守门 (P0-1)。

职责: 守住分页 URL 的定序契约 (P0-1) —— 同一组排序参数在翻页时必须生成逐页
  不同的 URL, 且参数顺序稳定。这类回归的表现是"第一页就取到全量"或"第二页
  返回与第一页相同的数据", 在客户端一侧几乎无感, 只会让大结果集静默截断。
所属层次: test/unit 层, 对应被测模块 src/client.py 的 BestClient 分页接线 ——
  即拼分页 URL 并按序消费多页的这段逻辑; 传输由 Mock 骨架的 session 替身接管,
  本文件不建立任何真实连接。
对外接口: 文件内用例直接验分页 URL 的生成与消费: 一条验单页结果不进分页逻辑,
  其余验多页场景下每页 URL 的差异、参数顺序与最终合并顺序, 以及排序字段缺失时
  的降级行为; 断言从替身 session 的调用记录里回查实际请求过的 URL。
依赖与数据流: 替身 session.get 是 Mock 骨架, 按调用次序吐出脚本化页面; 没有
  临时目录与落盘, 也没有真实快照文件 —— 页面数据全部内联在用例里, 便于一眼看清
  每页到底返回了什么; 断言只读调用记录与合并结果, 零写盘。
关键契约与不变量: 离线回放 —— 分页全过程不得触网, 替身没被调用到即视为违规;
  排序参数缺失或全空时不得凭空造一个默认排序 (那会悄悄改掉用户的取数顺序),
  应当按缺省语义走; 合并后的行序必须与页序一致, 否则跨页排序结果不可复现。
陷阱与边界: 断言盯的是"第 N 次请求的 URL 彼此不同且参数序稳定", 而不是简单
  比较最终结果 —— 后者在只有一页数据的替身下会永远通过, 恰好放过分页错序这种
  真实故障; 替身用 Mock 而非 fake 的原因是要拿到逐次调用的实参, 固定返回值
  的 fake 记不下请求。
"""
from __future__ import annotations

# 标准库: mock 骨架 (替身 session.get) / pathlib 定位仓根以读实测登记表
from pathlib import Path
from unittest.mock import Mock

# 旧导入守门: src.client 不可导入 (依赖缺失等) 时整模块 skip 而不是
# collection error, 让 legacy 树被单独收集时不污染整套结果。
try:
    # src.client: 两阶段异步 HTTP 客户端 (被测入口)
    from src.client import BestClient
except Exception as _legacy_err:  # legacy-import-guard
    # pytest: 导入失败时主动 skip, 不让环境问题伪装成用例失败
    import pytest as _pytest
    _pytest.skip(f'legacy import unavailable: {_legacy_err!r}', allow_module_level=True)            # 模块级跳过: 导入树问题不该算用例失败


def load_sort_column_observations() -> list[dict]:
    """读实测登记表 (`contracts/measurements/sort-columns.yaml`) 的观测列表。

    刻意**不复刻**登记表结构: 门禁 ``verify_measurement_registry`` 才是它的判据方,
    本函数只做"读出来"。表结构变了这里跟着报错, 而不是静默取到空列表 ——
    空列表会让下面那条断言变成空转绿。

    Returns:
        观测字典列表; 登记表缺失或结构不对即抛, 不返回空表。
    """
    import yaml  # 局部导入: 只在真正读到表时才需要

    from src.protocol import BEST_BASE_URL  # noqa: F401  — 仅为确认 src 包可导入 (仓根在 sys.path 上)

    path = Path(__file__).resolve().parents[3] / "contracts" / "measurements" / "sort-columns.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))  # 登记表是纯数据, 无版本键 (铁律 1)
    assert isinstance(data, dict) and isinstance(data.get("observations"), list), (
        f"实测登记表结构不对 (顶层须含 observations 列表): {path}")
    return data["observations"]


def test_bestclient_pagination_url_carries_deterministic_sort(monkeypatch):
    """P0-1 守门: BestClient 分页 URL 必须真实携带 sort+order。

    复过的现: ``base_q`` 自构 ``output.fmt=csv&rows&page``, 不带定序参数 —
    服务端无序翻页静默重复/丢行 (线上实测集合重叠仅 1/50)。这一条守的是
    "协议层单点接线"不断: 只看 build_page_url 单测是不够的, 客户端真的走
    单点才算修好。
    """
    client = BestClient(rate_limit=0)  # 限流归零: 本用例只验 URL 拼装, 不该被真实 sleep 拖慢
    seen_urls: list[str] = []                                                                     # 观测点: 断言回查的是客户端真发过的 URL

    def fake_get(url, **kwargs):
        """替身 session.get: 记录真实分页 URL, 回一张空表 (0 行即末页)。"""
        seen_urls.append(url)  # 先记账再回包: 断言回查的是客户端真发过的 URL, 不是构造函数的入参
        resp = Mock()                                                                               # 回包对象
        resp.status_code = 200                                                                      # 空表即末页: 0 行是分页终止的正常信号
        resp.text = ""                                                                             # 空正文即末页: 0 行是分页终止的正常信号
        return resp

    # _count 走网络问服务端总数, 离线守门置 0 (不影响分页 URL 构造)
    monkeypatch.setattr(client, "_count", lambda sqlid: 0)                               # 计数离线置 0: 本例只验 URL 拼装, 不该被真实请求拖慢
    monkeypatch.setattr(client.session, "get", fake_get)                                # 把替身装到真实 session 上: 走真实分页入口才管得住接线
    client._fetch_sqlid_data("s3839", catalog_path="ps1/q", max_rows=1000)  # 走真实分页入口: 委派壳与模块函数两层在这行汇合, 断这里才管得住接线

    assert seen_urls, "分页一次都没发起 — 接线断了"                        # 空列表先断: 否则下面两条 in 断言会在空表上假通过
    # 2026-07 订正: 原断言钉的是 ps1_source_id, 而实测该列 174/174 全空 → 服务端当
    # 空操作 → 排序等于没发。ps1 已改注入坐标列 ps1_ra (protocol.PAGINATION_SORT_COLUMNS)。
    # 这里从映射表取而不是写死字面量: 写死的话下次换列这条会静默变成"钉一个没人用的列"。
    from src.protocol import PAGINATION_SORT_COLUMNS  # 延迟导入: 断言里才需要, 不占模块级导入

    expected_sort = PAGINATION_SORT_COLUMNS["ps1"]
    assert f"sort={expected_sort}" in seen_urls[0], seen_urls[0]  # 排序键钉到具体列名: 断「含 sort=」的话, 排序列写错也照样过
    assert "order=asc" in seen_urls[0], seen_urls[0]           # 升序同样是契约: 排序列对了但方向反了, 跨页拼接结果仍不可复现


def test_default_sort_column_is_not_a_measured_dead_column():
    """默认注入的排序列不能是「实测为空 / 回包里根本没有」的列。

    **判据从实测登记表取** (`contracts/measurements/sort-columns.yaml`), 不再把结论
    硬编码成测试里的一个字面量集合。2026-10-07 查出原写法
    ``known_empty = {"ps1_source_id", "uss_dr1_ra_u"}`` **两条都被证伪**:

      · ``ps1_source_id`` 的空值率**位置相关** —— (180,30) 样本 0/174 非空, 而
        (286.1,15.7) 实测 128/300 非空。按旧断言的口径, 该表只要碰上那个天区就会
        被冤枉成"死列"。
      · ``uss_dr1_ra_u`` 在 96 列回包里**根本不存在同名列** (回包是裸名 ``ra_u``)
        —— 它不是空列, 是登记名写错。"不存在"与"恒空"是两个病, 混进一张集合就
        两个都治不了。

    现在的判据分成两条, 与登记表的两类观测一一对应:

      ① **表头里不存在** (`present_in_payload: false`) —— 注入它服务端不认;
      ② **处处为空** (所有观测的 ``non_empty_rows`` 都是 0) —— 注入等于白送。

    「某天区恰好为空」**不**判红: 那是位置相关, 不是列的属性, 且恰恰是它当时被
    误登记成死列的原因。
    """
    from src.protocol import PAGINATION_SORT_COLUMNS  # 延迟导入: 同上

    observations = load_sort_column_observations()  # 实测事实的唯一出口: 登记表
    offenders: list[str] = []
    for catalog, column in PAGINATION_SORT_COLUMNS.items():
        hits = [o for o in observations
                if o["catalog"] == catalog and o["column"] == column]
        if not hits:
            continue  # 没有实测记录 = 未知; 未知不等于空 (缺口由 verify_measurement_registry 披露)
        if all(o["present_in_payload"] is False for o in hits):
            offenders.append(f"{catalog} -> {column}: 回包表头里没有这一列 (登记名写错)")
        # **只看有数据的观测** (2026-10-07 修正): ``non_empty_rows == 0`` 只有在真的
        # 取到数据行时才说明「这一列是空的」。``sample_rows == 0`` 说明**这个天区没覆盖**。
        # 实测 landolt (全天约 1 行 / 3.2 deg2)、jplus_dr3 与 splus_dr4 都是「表头有该列
        # + 0 数据行」—— 原判据会把它们判成死列, 而这三张的排序列恰恰是**唯一合法选择**。
        # 判据与 verify_measurement_registry 的同一条规则逐字对齐: 门禁与承重测试
        # 必须同一口径, 否则改了一边另一边立刻红, 逼着人把两边改成互相打架的样子。
        with_data = [o for o in hits if o["sample_rows"] > 0]
        if with_data and all(o["non_empty_rows"] == 0 for o in with_data):
            offenders.append(f"{catalog} -> {column}: 所有**有数据**的实测样本里该列都为空")
    assert not offenders, (
        "注入的排序列被实测登记表证伪 (服务端会当空操作处理):\n  " + "\n  ".join(offenders))


def test_measurement_registry_actually_contradicts_the_retired_claim():
    """反证: 登记表必须真的记着那两条证伪事实, 否则上面那条是空转绿。

    若有人把登记表清空成"ps1_source_id 在任何天区都为空""uss_dr1_ra_u 处处为空",
    上面那条会立刻判红 —— 那正是 2026-10-07 之前的错误口径。本条把"事实本身"
    钉住, 使那条错误口径无法悄悄复活。
    """
    observations = load_sort_column_observations()

    ps1_hits = [o for o in observations if o["column"] == "ps1_source_id"]
    assert ps1_hits, "登记表里没有 ps1_source_id 的观测 —— 证伪事实被抹掉了"
    assert any(o["non_empty_rows"] > 0 for o in ps1_hits), (
        "ps1_source_id 被登记成处处为空 —— 那是 2026-10-07 已被推翻的说法"
        " ((286.1,15.7) 实测 128/300 非空)")
    assert any(o["present_in_payload"] is False
               for o in observations if o["column"] == "uss_dr1_ra_u"), (
        "uss_dr1_ra_u 未被登记为'表头里不存在' —— 该列名是错的, 回包用裸名 ra_u")


def test_malformed_half_row_skipped_and_counted(monkeypatch):
    """E4 F-E4-01 守门: 坐标列存在但为空的结构半行不得入库。

    复过的现: 响应里混入"有 ra 无 dec"的行 — from_row 老实落成 ra=值/
    dec=None 后照样进 sources, 下游按 None 坐标匹配/去重时静默出错
    (与传输截断半行 RB-29 同类, 与 ERROR→EMPTY 同族的"结构事故包装")。
    修复口径: _fetch_sqlid_data 显式跳过并计入
    query_params.skipped_malformed_rows; 服务端计数大于实收时 truncated
    必须为 True (不得把"少收"说成"已取全")。
    """
    body = ("ps1_source_id,ps1_ra,ps1_dec,ps1_rpsf\n"                                          # 三行样本: 中间那行故意缺一个坐标, 模拟结构半行
            "S1,180.0001,30.0001,18.2\n"                                                            # 完整行: 坐标齐全, 必须留下
            "S2,180.0002,,19.1\n"                                                                 # 半行: 有赤经无赤纬, 这就是不许入库的那种
            "S3,180.0003,30.0003,20.0\n")                                                         # 完整行: 与首行一起构成"只跳过半行"的对照

    def fake_get(url, **kwargs):
        """替身 session.get: getcount 回 3 (服务端视角), 数据页回三行 (含半行)。"""
        resp = Mock()                                                                               # 回包对象
        resp.status_code = 200                                                                      # 计数页与数据页共用一个替身
        resp.text = '{"total": 3}' if "getcount" in url else body  # getcount 与数据页共用一个替身: 靠 URL 关键字分流才模拟得出真实两次请求
        return resp

    client = BestClient(rate_limit=0)                                                               # 限流置 0
    monkeypatch.setattr(client.session, "get", fake_get)                                            # 把替身装到真实 session 上
    result = client._fetch_sqlid_data("s9001", catalog_path="ps1/q", max_rows=1000)  # 实收 2 条 vs 计数 3: 差额即 truncated 的来源

    assert [s.source_id for s in result.sources] == ["S1", "S3"]  # 断 ID 列表而非条数: 顺序错乱与漏行是两类故障, 只断长度看不出
    assert result.query_params["skipped_malformed_rows"] == 1     # 跳过计数必须可查: 静默丢行且不留痕, 用户无从判断结果是否完整
    assert result.total_count == 3 and result.returned_count == 2                                 # 总数与实收数分开记: 差额就是截断标志的来源
    assert result.truncated is True  # 少收必须说成截断: 报成「已取全」等于把数据事故包装成成功


def test_row_without_coordinate_columns_is_kept(monkeypatch):
    """反向守门: 响应根本没有坐标列的星表行不得被误跳过。

    uss_dr1 一类星表无规范化 ra/dec 列 — malformed_coordinate_reason 只判
    "列存在但空值", 列不存在是该星表的正常形态 (由 from_row 的 None 语义
    承担), 不是本行的错。
    """
    # 本地: 被测分页链路 (client_paging 抽离件 + 半行判据的协作者)
    from src.models import malformed_coordinate_reason

    row = {"uss_source_id": "U1", "ra_u": "190.1", "u_mag": "18.2"}                              # 无坐标列的星表行: 列不存在是该星表的正常形态
    assert malformed_coordinate_reason(row, "uss_dr1") is None                                    # 反向守门: 不得把"列不存在"误判成结构半行
    half = {"ps1_source_id": "S2", "ps1_ra": "180.0002", "ps1_dec": ""}                             # 真正的半行: 列存在但值为空
    assert malformed_coordinate_reason(half, "ps1") is not None                                     # 半行必须被认出来
    assert malformed_coordinate_reason({"ra": "", "dec": "1.0"}, "ps1") is not None             # 赤经空而赤纬有同样算半行: 判据不能只看其中一列


def test_paging_delegation_seam_signature_compatible():
    """抽离缝守门 (budget §3.2): 委派壳与模块函数签名逐参对齐。

    ``_fetch_sqlid_data``/``_count`` 的实现抽至 src/client_paging.py,
    原方法留同名同签名壳 (测试对实例方法的 patch 依赖该性质)。本用例钉住
    "壳签名 == 模块函数签名" — 任一侧加参数而另一侧漏改即红。
    """
    # 本地: 被测分页链路 (client_paging 抽离件 + 半行判据的协作者)
    import inspect

    from src.client import BestClient
    from src.client_paging import count_sqlid_rows, fetch_sqlid_data

    shell_params = list(inspect.signature(BestClient._fetch_sqlid_data).parameters)                # 反射取委派壳的形参表: 签名漂移只能这样钉
    fn_params = list(inspect.signature(fetch_sqlid_data).parameters)                                # 反射取模块函数的形参表
    # 模块函数第一参是 client (壳的第一参是 self) — 其余必须逐参同名同序
    assert fn_params[0] == "client"                                             # 模块函数第一参必须是 client: 壳的第一参是 self, 去掉才谈得上对齐
    assert shell_params[1:] == fn_params[1:], (  # 两端逐位比对: 壳去掉 self 后须与模块函数同名同序, 任一侧漏改即红
        f"委派壳与模块函数签名漂移: {shell_params} vs {fn_params}")                                            # 两端逐位比对: 任一侧加参而另一侧漏改即红

    count_shell = list(inspect.signature(BestClient._count).parameters)                             # 计数委派壳的形参表
    count_fn = list(inspect.signature(count_sqlid_rows).parameters)                                 # 计数模块函数的形参表
    assert count_fn[0] == "client"                                                                  # 计数模块函数同样以 client 打头
    assert count_shell[1:] == count_fn[1:]

    # 模块函数可脱离实例直调 (client 参数穿透 session/base_url/限流)
    assert callable(fetch_sqlid_data) and callable(count_sqlid_rows)                            # 模块函数必须可脱离实例直调: 抽离的收益就在这里
