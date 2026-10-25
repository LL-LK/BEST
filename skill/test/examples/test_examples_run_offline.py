# -*- coding: utf-8 -*-
"""test/examples — examples/ 人读示例的离线执行防腐烂测试。

背景: examples/ 若只被 lint 覆盖而不被执行, 示例就会随 API 演进而静默腐烂 ——
读者照着示例跑直接炸, 而全部门禁一声不响。本目录把两个示例的主路径用离线桩
真实跑通, 并把示例 docstring 里声明的预期输出变成断言。

离线手段 (双层保险, 保证零真实网络请求):
  1. ``requests.Session.request`` 整体替换为确定性桩 —— ``session.get`` /
     ``session.post`` 内部都汇入该方法, 一处替换即全量拦截;
  2. ``requests.adapters.HTTPAdapter.send`` 换成显式抛错的卫兵 —— 任何绕过
     桩的真实出口都会让测试立刻红, 而不是悄悄打到线上站点。

覆盖的示例:
  - ``examples/example_skill_usage.py``: BestSkillClient 质量门控锥搜 +
    BestCrossMatch 逐点交叉匹配;
  - ``examples/example_quickstart_client.py``: Best 单类「查询 -> 下载 ->
    约束查询 -> 交叉匹配 -> 元信息」最小闭环。

F4 修的四条门禁盲区 (断言一律落在**请求体**与**真值比对**上, 不再只信打印):
  - A1-01 打印列名写错: 逐行解析 ``ra=``/``dec=`` 输出, 与 ``raw_data``
    真值比对并断言不含 ``N/A`` (示例的 ``.get(..., "N/A")`` 兜底会把错列名
    安静地打成 N/A, 旧门禁只断言 "Found N sources" 一行, 看不见);
  - A1-02 几何量纲: 桩额外记 ``pos.radius``/``pos.deccenter``, 断言半径
    真的是角秒值 (60 角秒写成度数 0.0167 曾全绿; pitfalls.md E-1);
  - A1-03 band: 断言 phase-1 表单里的 ``ps1.rpsf.operation == "notequal"``,
    换 band 或删掉 band= 都必须红 (旧断言 ``"r" in row["magnitudes"]`` 与
    band 无关, 是同义反复);
  - A1-08 import 副作用: 示例已挂 ``__main__`` 守卫, 本目录断言"import
    示例模块不发任何请求"。

圆心等请求侧记账一律用 :class:`collections.Counter` 比计数而非 ``set`` 比
成员 —— 压成集合后"3 次请求"与"5 次请求"不可区分。
"""
from __future__ import annotations

# 标准库: importlib.util 以非 __main__ 身份导入示例模块 (守 import 无副作用);
# re 解析示例打印的 ra=/dec= 行; runpy 以 __main__ 身份执行示例主路径;
# Counter 按次数比请求侧记账; sys.modules 供导入探针登记/撤销模块名;
# pathlib 锚定示例目录与落盘产物断言; time 用于屏蔽限流睡眠 (见 offline fixture)
import importlib.util
import re
import runpy
import sys
import time
from collections import Counter
from pathlib import Path

# 第三方: monkeypatch 经 pytest fixture 注入; requests 是两个网络替换点
# (Session.request 请求桩 + HTTPAdapter.send 真网卫兵) 的所在包
import pytest
import requests
from requests.adapters import HTTPAdapter

# 本地: 协议层权威常量 —— BEST 站点基地址 (桩路由对照) 与 ps1 列清单
# (示例第 6 步 "PS1 has K columns" 的期望值来源, 不把数字写死);
# magnitude_column 是 band→真实列名的唯一权威, 用来证明 band 确实换列
from src.protocol import BEST_BASE_URL, CATALOG_COLUMNS, magnitude_column

# 本文件位于 test/examples/ 下, 上溯两级即 skill 根; 示例目录与 skill 根同层级锚定
SKILL_DIR = Path(__file__).resolve().parents[2]                                          # 上溯两级到 skill 根: 示例目录与 skill 根同层级
EXAMPLES_DIR = SKILL_DIR / "examples"                                                               # 示例目录由此锚定

# 离线桩的确定性数据: 固定 sqlid 与 ps1 仿真 CSV。列名取协议层登记的 ps1 真实
# 投影; 两个数据行都带 class_star/snr/rpsf, 使质量门控有可判指标 (Q-14:
# 无任何指标的源会被 fail-closed 拒收, 示例第 2 步将返回空列表)。
FAKE_SQLID = "s9999"                                                                                # 固定会话号: 桩的路由靠它
FAKE_ROW_COUNT = 2                                                                                  # 行数也要固定: 示例输出里印的是这个数
FAKE_CSV_HEADER = "ps1_source_id,ps1_ra,ps1_dec,ps1_class_star,ps1_rpsf,ps1_snr\n"                 # 表头带质量指标: 缺了它们质量门控会 fail-closed 拒收
# 仿真 CSV 的数据行模板。两行都取高 class_star / 高 snr: 质量门控(min_snr=10,
# class_star>=0.8)必须放行, 否则示例第 2 步返回空列表, "Found N high-quality
# sources" 这行输出就没了。
FAKE_ROW_TEMPLATES = (
    ("BEST_SIM_0001", 0.99, 18.20, 25.0),  # 第一条仿真源: 高恒星分类概率与高信噪比
    ("BEST_SIM_0002", 0.98, 18.40, 30.0),  # 第二条仿真源: 与第一条一起构成两行的期望
)
FAKE_CSV = FAKE_CSV_HEADER + "".join(  # 旧形态: 固定坐标版的整段 CSV, 保留给不关心位置的断言比对
    f"{sid},180.000{i + 1},30.000{i + 1},{cls},{rpsf},{snr}\n"
    for i, (sid, cls, rpsf, snr) in enumerate(FAKE_ROW_TEMPLATES))


def _csv_near(ra_center: float, dec_center: float) -> str:
    """按**单个**查询圆心造一份仿真 CSV (真实锥搜就是这么回的)。"""
    return _csv_near_all([(ra_center, dec_center)])  # 单圆心就是一个圆心的批量


def _csv_near_all(centers: list[tuple[float, float]], nearest_only: bool = False) -> str:
    """按**本次提交的全部**圆心造一份仿真 CSV。

    为什么 2026-10-07 才补上: 桩原先对任何查询都回**同一份固定 CSV** (ra≈180.0/
    dec≈30.0)。而 quickstart 的交叉匹配一次 proximity 提交**两个**坐标
    (180,30) 与 (181,31), 半径 3 角秒 —— 于是第二个点会"匹配"上一个 3600 角秒外的源。

    当时没人发现, 因为 src/crossmatch 只**报告**角距、从不**拒绝**越界匹配
    (审计 D1 / AA4-P0-1)。复核接上之后这条立刻变红 —— 那是复核在如实报告桩的谎,
    不是产品退化。所以这里改桩而不是放松复核: **位置失明的桩教不出正确的行为**,
    而复核正是为了让这种谎无处可藏。
    """
    # 偏移量取 0.0001 度 ≈ 0.36 角秒, 稳稳落在 3 角秒半径内 (真实锥搜的命中量级)
    # source_id **按圆心序号**编号: 真实站点下不同天区的源当然是不同源, 而复用同一
    # 模板会让两个坐标各自回一行 BEST_SIM_0001 —— 结果集按 source_id 去重后只剩 1 条,
    # 于是 "Matched M sources" 印出 1, 看起来像少匹配了一个点, 实际是桩造了两条
    # **同 id** 的源。刻意不复用: 让桩的错误与真实站点的行为一致。
    # proximity 批量且 nearest_only (默认) 时: 真实站点每个输入点只回最近的一条,
    # 所以行数 = 输入点数。锥搜 (单圆心) 则回整个锥内结果。
    # 两者不能用同一个行数: 将来“批量返回行数”当成固定常量会让
    # 区分两条路径的门禁失效。
    templates = FAKE_ROW_TEMPLATES[:1] if nearest_only else FAKE_ROW_TEMPLATES
    return FAKE_CSV_HEADER + "".join(
        f"{sid}-{ci + 1},{ra_center + 0.0001 * (i + 1):.6f},{dec_center + 0.0001 * (i + 1):.6f},{cls},{rpsf},{snr}\n"
        for ci, (ra_center, dec_center) in enumerate(centers)
        for i, (sid, cls, rpsf, snr) in enumerate(templates))

# band="r" 经协议层映射后 phase-1 表单里应当出现的列约束键值对 (A1-03 的
# 断言对象): 键名带真实星等列, 值是"非空"哨兵。换 band="z" 时键名整体变成
# ps1.zpsf.*, 删掉 band= 时整对键消失 —— 两种改法都让断言红, 而返回行里的
# 星等字典两种情况下都照旧含 "r" (桩 CSV 固定带 ps1_rpsf), 所以断言只能
# 落在请求体上。
EXPECTED_BAND_FORM = {"ps1.rpsf.operation": "notequal", "ps1.rpsf.constraint": "null"}

# quickstart 示例第 2 步打印的坐标行形态 ("  ra=<值> dec=<值>")。解析它是为了
# 拿打印值与 raw_data 真值对账: 示例用 .get(..., "N/A") 兜底, 列名写错时
# 不抛异常、只印 N/A, 旧门禁只断言 "Found N sources" 一行因此全绿 (A1-01)。
PRINTED_RA_DEC_RE = re.compile(r"^\s*ra=(?P<ra>\S+)\s+dec=(?P<dec>\S+)\s*$")


class _StubResponse:
    """requests.Response 的最小替身 (只实现被测链路用到的成员)。

    被测链路只读 ``text``/``status_code`` 并调 ``raise_for_status``; 流式迭代
    (``iter_content``) 不实现 —— 两个示例都不走字节级 ``download_file`` 路径。
    """

    def __init__(self, text: str, status_code: int = 200) -> None:
        """记录响应体与状态码 (默认 200, 与线上成功回包一致)。

        状态码取 200 作默认: 大多数回包是成功路径, 显式传非 200 的只有专门
        验错误分支的用例, 让默认值等于常态可以少写一个噪声参数。
        """
        self.text = text                                                                            # 正文由用例给: 桩要按路由回不同形态
        self.status_code = status_code                                                              # 状态码同样由用例给

    def raise_for_status(self) -> None:
        """HTTP 层失败判定: 仅 4xx/5xx 抛 RequestException (与 requests 同语义)。"""
        if self.status_code >= 400:                                                            # 错误状态码走异常分支: 静默当成功回包就是静默失真
            raise requests.RequestException(f"stub HTTP {self.status_code}")


class _OfflineStub:
    """requests.Session.request 的确定性离线替身, 兼记录全部调用。

    路由按 BEST 两阶段协议 + 计数端点 + 连通性探测四类回包; 未预期的
    (方法, URL) 组合显式抛错 —— 示例换了调用形态而桩没跟上, 必须红。
    另外从阶段 1 表单里记下几何三元 (圆心/赤纬/半径) 与列约束键, 供测试断言
    "调用方给的参数真的上了线" (防请求体被静默丢弃)。半径与赤纬必须一起记:
    只记圆心时"把 60 角秒当成度下发"这类量纲漂移在请求侧完全不可见
    (A1-02, pitfalls.md E-1 列为最高频坑)。
    """

    def __init__(self) -> None:
        """初始化调用记录表与四张请求侧记账表 (测试据此做请求体断言)。"""
        self.calls: list[tuple[str, str]] = []                                                   # 逐次记账: 断言要回查"示例真的发了哪些请求"
        self.centers: list[str] = []                                                                # 锥搜圆心 (pos.racenter) 记账
        self.decs: list[str] = []                                                                   # 锥搜赤纬 (pos.deccenter) 记账: 圆心只覆盖半个天区
        self.radii: list[str] = []                                                                  # 锥搜半径 (pos.radius) 记账: 量纲漂移的唯一可核查产物
        self.proximity: list[str] = []                                                              # 邻近文本记账
        self.band_ops: list[dict[str, str]] = []                                                   # 每次 POST 的列约束键值对: 波段映射的产物在这里
        # sqlid -> 该次提交的圆心 (2026-10-07 新增): 数据页要按**本次查询**的圆心回行,
        # 否则桩位置失明, 交叉匹配的第二点会拿到 3600 角秒外的源 (见 _csv_near 的说明)。
        # 每次 POST 发一个唯一 sqlid, 于是这里天然是「哪个会话对应哪个圆心」。
        self._centers_by_sqlid: dict[str, list[tuple[float, float]]] = {}
        self._nearest_by_sqlid: dict[str, bool] = {}  # 该会话是否 proximity 批量 (nearest_only 入参为假)
        self._sqlid_seq = 0

    def __call__(self, method: str, url: str, **kwargs) -> _StubResponse:
        """按 (方法, URL) 路由到确定性回包, 并记录本次调用。

        Args:
            method: HTTP 方法。
            url: 目标 URL。
            **kwargs: 请求参数 (POST 时从 ``data`` 里取几何三元、列约束与
                proximity 坐标记账)。

        Returns:
            对应的 _StubResponse 替身回包。

        Raises:
            AssertionError: 请求不匹配任何已知路由 (说明示例调用形态已变)。
        """
        self.calls.append((method.upper(), url))  # 先记账: 异常路径也要留下调用痕迹
        if method.upper() == "POST" and url.endswith("/q"):                                         # 提交阶段的路由: 走 q 路径才算建查询
            # 阶段 1: 记账锥搜中心 (证明天区参数真的进了请求体), 回含 sqlid 的
            # 结果页 HTML (parse_sqlid 的正则锚点); proximity 批量匹配的坐标
            # 走 radecTextarea (一次 POST 全部坐标), 同样记账
            form = kwargs.get("data") or {}  # POST 表单: 锥搜与 proximity 都走这里
            # 几何三元逐项记账: 任一项缺席说明调用方没给, 给了却被静默改写
            # (量纲) 才是要挡的那类漂移 —— 圆心正常而半径是 "0.0167" 时,
            # 只看圆心的门禁全绿, 真实站点却回一个恒空的锥搜。
            for key, bucket in (("pos.racenter", self.centers), ("pos.deccenter", self.decs), ("pos.radius", self.radii)):  # 三键对三表: 键名即归属
                value = form.get(key)  # 位置键可能缺席 (非锥搜的提交)
                if value is not None:  # 缺席与"下发了错的"要分得开: 缺席只是没用这项, 不记账
                    bucket.append(str(value))  # 统一存字符串: 表单值本就是 str, 断言照抄即可
            # 列约束键记账 (形如 {table}.{column}.operation / .constraint):
            # band 过滤的唯一产物就在这里, 换波段换的是键名而非值。
            self.band_ops.append({  # 每次 POST 记一份快照: 断言能逐次回查, 也能按集合比对
                key: str(value)  # 统一字符串化: operation 与 constraint 值都要照原文断言
                for key, value in form.items()  # 逐键筛
                if key.endswith(".operation") or key.endswith(".constraint")  # 只留约束键: 几何键已有专表记账
            })
            radec_text = form.get("pos.radecTextarea")  # 批量坐标, 验"一次 POST 全部坐标"
            if radec_text is not None:                                                              # 邻近文本可能缺席
                self.proximity.append(str(radec_text))                                              # 有邻近文本才记
            # 每次 POST 发一个**唯一** sqlid 并记下本次圆心: 数据页据此回对应位置的行。
            # proximity (radecTextarea) 没有单一圆心, 取第一对坐标作为代表圆心。
            self._sqlid_seq += 1  # 序号自增即唯一: 会话号只需可区分, 不必好看
            sqlid = f"s{9000 + self._sqlid_seq}"  # 形如 s9001/s9002: 必须匹配 protocol._SQLID_RE 的 s?\d+
            if radec_text is not None:  # 批量坐标: 一次提交**所有**坐标, 回包要覆盖每一对
                pairs = str(radec_text).split()  # 空白切分得到每一对 "ra,dec"
                self._centers_by_sqlid[sqlid] = [tuple(float(v) for v in pair.split(",")[:2])
                                                 for pair in pairs if "," in pair]  # 只取 ra/dec
                self._nearest_by_sqlid[sqlid] = "proximity_nearestonly" in form  # 键名无 pos. 前缀且不同于锥搜的 cone_nearestonly (见 protocol)
            elif form.get("pos.racenter") is not None:  # 锥搜: 圆心由几何三元给出
                self._centers_by_sqlid[sqlid] = [(float(form["pos.racenter"]), float(form["pos.deccenter"]))]
            return _StubResponse(
                f"<html><a href='/data/best/sqlid/{sqlid}'>results</a></html>"                   # 回包里必须带会话号: phase-2 靠它拼地址
            )  # 只给 sqlid: 数据页由下面的分支回, 模拟两阶段协议
        if "/getcount" in url:                                                                      # 计数端点分支: 服务端总数从这条路来
            # 阶段 2 计数端点 (P0-2): 服务端真实总数, 与 CSV 数据行数一致
            return _StubResponse(f'{{"total": {FAKE_ROW_COUNT}}}')  # 与 FAKE_CSV 行数同源
        if "/sqlid/" in url:                                                                        # 数据页分支: 按列投影回 CSV
            # 阶段 2 分页取数: 不足一页即末页, 每个 sqlid 只发一次 GET
            path_part = url.split("?", 1)[0]  # 先剥查询串: 数据页 URL 带 ?output.fmt=csv&...
            sqlid = path_part.rstrip("/").rsplit("/", 1)[-1]  # 从路径尾部取会话号
            centers = self._centers_by_sqlid.get(sqlid)  # 该会话对应的全部圆心
            body = (_csv_near_all(centers, self._nearest_by_sqlid.get(sqlid, False))
                    if centers else FAKE_CSV)  # 无圆心记录时回落固定 CSV
            return _StubResponse(body)  # 无表头投影, 交协议层按列名解析
        if url.rstrip("/") == BEST_BASE_URL:                                                        # 基址探测分支: 元信息那一步靠它
            # Best.info() 的连通性探测: 200 回包 -> connected=True
            return _StubResponse("<html>best</html>")
        raise AssertionError(f"离线测试未预期的请求: {method} {url}")  # 未声明出口 = 立刻红


@pytest.fixture
def offline(monkeypatch):
    """装配离线网络环境: 全量请求桩 + 真网卫兵 + 限流睡眠屏蔽。

    Returns:
        _OfflineStub 实例 (测试经它读取调用记录与请求体记账表)。
    """
    stub = _OfflineStub()                                                                           # 构造离线桩
    # 替换点 1: Session.request 是 session.get/post 的共同汇入点; 挂在类上的
    # 普通可调用对象经实例调用时不注入 self, 故签名为 (method, url, **kwargs)
    monkeypatch.setattr(requests.Session, "request", stub)                                          # 整体替换会话请求: 一处替换即全量拦截

    def _forbid_real_send(self, *args, **kwargs):
        """真网卫兵: 任何绕过桩的真实出口都让测试立刻红 (零外泄证据)。

        挂在 HTTPAdapter.send 上是因为它是 requests 真正发包前的最后一道关口:
        只拦 Session.request 的话, 示例哪天改用 requests.get() 或换了个
        session 实现, 请求就直接打到真网去了, 而测试仍然全绿。
        """
        raise AssertionError("离线测试不允许真实网络出口 (HTTPAdapter.send 被调用)")

    # 替换点 2: 适配器层卫兵 —— 桩漏路由时请求会打到真网, 这里显式炸掉
    monkeypatch.setattr(HTTPAdapter, "send", _forbid_real_send)                                     # 真网卫兵: 绕过桩的出口会让这条立刻红
    # 限流睡眠屏蔽: 被测语义是示例主路径与返回契约, 与节流时长无关; 不屏蔽的
    # 话两个示例按默认 rate_limit (2~3s/请求) 要白等 50s 以上
    monkeypatch.setattr(time, "sleep", lambda _seconds: None)                                  # 屏蔽限流睡眠: 桩是瞬时的, 不该为礼貌间隔付墙钟
    return stub


def _assert_traffic_all_stubbed(stub: _OfflineStub) -> None:
    """断言请求确实发生过, 且每一个都打在权威站点基地址上。

    防腐烂点: 示例主路径死掉 (一次请求都不发) 或请求偏离权威站点 (多 host
    泄露) 都必须红 —— 前者说明调用形态已断, 后者说明有未声明的网络出口。
    """
    assert stub.calls, "示例没有发出任何请求 — 主路径已死或桩未接线"  # 零请求 = 防腐烂失效
    for _method, url in stub.calls:                                                                 # 逐条核对请求都经过桩
        assert url.startswith(BEST_BASE_URL), f"请求偏离权威站点: {url}"  # 多 host 泄露即红


class TestExampleSkillUsageOffline:
    """examples/example_skill_usage.py 的离线执行与预期输出断言。"""

    def test_main_path_runs_offline(self, offline, capsys):
        """示例主路径 (质量门控锥搜 + 逐点交叉匹配) 离线跑通且输出符合 docstring。

        验证什么: 以 __main__ 身份执行示例, 断言 (1) 请求全被桩拦截且只打
        权威站点; (2) 几何三元的**值**真的进了请求体 (圆心/赤纬按次数比,
        半径按角秒值比); (3) band 过滤的产物是 ``ps1.rpsf`` 那对约束键;
        (4) 打印的两行与 docstring 声明的预期输出形态一致 ("Found N
        high-quality sources" / "Matched M sources"); (5) 质量门控阈值真的
        生效 (snr/class_star 下限), 每个源都带 quality 判定明细。
        为什么重要: 该示例是读者学 BestSkillClient 用法的第一现场, 一旦
        cone_search 签名或返回值契约漂移, 读者照抄即炸, 而 lint 覆盖发现
        不了 (示例不被 test 执行)。几何与 band 两项尤其关键: 圆心对而半径
        量纲错, 或 band 悄悄换列, 都是"请求发出去了、结果也回来了、但要的
        是另一个天区/另一个波段"这类肉眼看不见的静默漂移。
        """
        ns = runpy.run_path(str(EXAMPLES_DIR / "example_skill_usage.py"),                       # 以主模块身份执行示例: 守卫只在 __main__ 下放行
                            run_name="__main__")  # 显式主模块名: 守卫读的就是 __name__
        _assert_traffic_all_stubbed(offline)                                                        # 执行后立刻核对流量
        printed = capsys.readouterr().out                                                           # 接住示例的打印输出
        summary = ns["SUMMARY"]                                                                     # 示例主路径的返回值: 真值比打印行可信

        # 请求侧几何: 第 2 步一次 180.0/30.0/60 角秒, 第 3 步逐点两次
        # 180.0/30.0/3 角秒与 181.0/31.0/3 角秒。按**次数**比而不是比集合:
        # 压成 set 后"3 次请求"与"5 次请求"看起来一模一样, 多发两次查询这类
        # 漂移就不可见了 (逐点并发完成次序不定, 故用 Counter 而非顺序比)。
        assert Counter(offline.centers) == {"180.0": 2, "181.0": 1}, offline.centers
        assert Counter(offline.decs) == {"30.0": 2, "31.0": 1}, offline.decs
        # 半径必须是角秒值: 60 角秒写成度数 (0.0167) 曾全绿, 真实站点却回一个
        # 恒空的锥搜 (docs/architecture/pitfalls.md E-1 列为最高频坑)。
        assert Counter(offline.radii) == {"60.0": 1, "3.0": 2}, offline.radii

        # 请求侧 band: band="r" 的唯一可核查产物是 phase-1 表单里这对键。
        # 换 band="z" → 键名变 ps1.zpsf.*; 整个删掉 band= → 键消失。旧断言
        # ("r" in row["magnitudes"]) 与 band 无关: 桩 CSV 固定含 ps1_rpsf,
        # 两种改法下它都成立, 是同义反复。
        assert EXPECTED_BAND_FORM in offline.band_ops, offline.band_ops
        # 顺带钉住"波段映射确实换列"这个前提: 若协议层哪天让 band 退化成
        # 不敏感的装饰参数, 上面那条断言会因为键还在而继续绿, 这里先红。
        assert magnitude_column("ps1", "r") == "ps1.rpsf"  # r 波段 → ps1 真实星等列
        assert magnitude_column("ps1", "z") == "ps1.zpsf"  # 换波段必须换列名, 否则映射形同虚设

        # docstring 预期输出 1: "Found N high-quality sources" (N=桩内仿真行数)
        assert f"Found {FAKE_ROW_COUNT} high-quality sources" in printed  # 示例承诺的输出形态
        sources = summary["sources"]                                                                 # 取示例返回的源列表
        assert isinstance(sources, list)                                                         # 必须是列表: 返回别的类型说明示例内部换了契约
        assert len(sources) == FAKE_ROW_COUNT  # 桩回两行就必须有两行, 少一行是解析吞了
        for row in sources:                                                                         # 逐行核对质量指标
            # quality_filter=True 的契约: 每个源 dict 附带门控判定明细且通过
            assert row["quality"]["passed"] is True  # 挡"门控被静默摘掉": 无条件放行
            # quality_config={"min_snr": 10.0} 与点源分类下限 0.8 真的生效
            assert row["snr"] >= 10.0                                                               # 信噪比必须过门限
            assert row["class_star"] >= 0.8                                                         # 恒星分类概率必须过门限
            # 星等字典只断言非空 —— 它由站点回包解析而来, 桩 CSV 固定带
            # ps1_rpsf, 因此无论传不传 band 都非空。**这条不是 band 门禁**,
            # band 的门禁在上面的请求体断言 (A1-03: 旧版把它当 band 门禁)。
            assert row["magnitudes"]

        # docstring 预期输出 2: "Matched M sources" (两个输入坐标各命中一个源)
        assert f"Matched {FAKE_ROW_COUNT} sources" in printed                                    # 示例自己印的那行必须出现: 读者看到的就是这行
        result = summary["result"]                                                                   # 取结果对象
        assert result.success is True  # 逐点路径全命中, 不该落失败信封
        assert result.returned_count == FAKE_ROW_COUNT                                              # 返回条数必须与桩给的行数一致
        assert result.query_params["n_matched"] == FAKE_ROW_COUNT  # query_params 也要如实回填


class TestExampleQuickstartClientOffline:
    """examples/example_quickstart_client.py 的离线执行与预期输出断言。"""

    def test_end_to_end_loop_runs_offline(self, offline, tmp_path, monkeypatch, capsys):
        """BestClient 最小闭环 (查询→下载→约束查询→交叉匹配→元信息) 离线跑通。

        验证什么: 以 __main__ 身份执行示例 (chdir 到临时目录, 下载产物落在
        tmp 下而非仓库 best_data/), 断言 (1) 请求全被桩拦截; (2) 几何三元
        真的进了请求体且半径是角秒值; (3) 打印的坐标行与 ``raw_data`` 真值
        逐行对账且不含 N/A; (4) 下载文件真实存在且是带表头的 CSV; (5) 约束
        查询回裸投影行 (站点原始列名); (6) 交叉匹配回领域模型源。
        为什么重要: 这是端到端快速上手示例, 覆盖 BestClient 五个公开入口,
        任一路径漂移都会让新手第一步就失败。第 2 步的坐标行是本示例里唯一
        显式演示"安全读法"的地方, 它带 .get(..., "N/A") 兜底 —— 列名写错
        时不炸、只印 N/A, 所以这条断言必须与真值对账, 只断言"Found N
        sources"是挡不住的 (A1-01)。
        """
        #  chdir 到临时目录: 示例内的相对路径 (best_data/ 默认 output_dir)
        # 与其它产物同样不污染仓库
        monkeypatch.chdir(tmp_path)  # 换工作目录: 落盘断言才有可比的绝对路径
        ns = runpy.run_path(str(EXAMPLES_DIR / "example_quickstart_client.py"),                     # 另一个示例同样以主模块身份跑
                            run_name="__main__")                                                   # 显式主模块名: 守卫读的就是 __name__
        _assert_traffic_all_stubbed(offline)                                                        # 执行后核对流量
        printed = capsys.readouterr().out                                                           # 接住打印输出
        summary = ns["SUMMARY"]                                                                     # 示例主路径的返回值: 真值比打印行可信

        # 请求侧几何: 第 2 步锥搜与第 3 步下载各一次 180.0/30.0/60 角秒
        # (第 5 步 proximity 的半径内联在 radecTextarea 每行里, 不走 pos.radius)。
        # 半径按角秒值断: 把 60 角秒当成度下发 (0.0167) 曾全绿, stdout 与
        # 基线逐行相同, 真实站点却恒返空锥搜 (pitfalls.md E-1)。
        assert Counter(offline.centers) == {"180.0": 2}, offline.centers                            # 两次圆心: 锥搜 + 下载
        assert Counter(offline.decs) == {"30.0": 2}, offline.decs                                   # 赤纬同样要断: 只断圆心会漏掉换 dec 的漂移
        assert Counter(offline.radii) == {"60.0": 2}, offline.radii                                  # 半径单位是角秒, 60.0 才是对的
        # 交叉匹配的两个坐标必须进同一次 proximity 提交的 radecTextarea
        # (P0-1 一次 POST 全部坐标)
        assert any("180.0,30.0" in text and "181.0,31.0" in text                                    # 邻近文本必须同时含两组坐标
                   for text in offline.proximity), offline.proximity                                # 逐条邻近文本比

        # 第 2 步 docstring 预期输出: "Found N sources" (锥搜信封的源个数)
        assert f"Found {FAKE_ROW_COUNT} sources" in printed                                         # 示例印的找到行数必须出现
        result = summary["result"]                                                                  # 取锥搜信封
        # A1-01 打印列名门禁: 示例用 .get(..., "N/A") 兜底, 列名写错 (如
        # ps1_ra → ps1_raX) 时不抛异常、只印 N/A。旧门禁从不断言 ra=/dec=
        # 两行, 那种改动照样 2 passed。这里逐行解析打印值, 与 raw_data 真值
        # 对账: 印 N/A 直接红, 印错数也红。
        printed_pairs = [  # 逐行取坐标行: 示例印的每条预览都必须可解且与真值一致
            PRINTED_RA_DEC_RE.match(line.strip())  # 正则锚定整行形态 "ra=<值> dec=<值>"
            for line in printed.splitlines()  # 逐行扫
            if "ra=" in line  # 只认含 ra= 的行, 避免误抓别的输出
        ]
        assert len(printed_pairs) == min(3, FAKE_ROW_COUNT), printed  # 预览行数必须与"前 3 条"一致
        for matched, source in zip(printed_pairs, result.sources):  # 打印行与源对象逐位对账
            assert matched is not None, f"坐标行形态变了, 解析失败: {matched}"  # 形态变了说明示例改了输出契约
            assert matched.group("ra") != "N/A" and matched.group("dec") != "N/A", "示例打印了 N/A — 列名写错被 .get 兜底吞掉"  # 兜底值出现 = 列名漂移
            # raw_data 是站点原始投影, 坐标值是字符串; 两侧都转 float 再比,
            # 免得"类型不同"被误读成"值不同"
            assert float(matched.group("ra")) == pytest.approx(float(source.raw_data["ps1_ra"]))  # 印的赤经必须等于真值
            assert float(matched.group("dec")) == pytest.approx(float(source.raw_data["ps1_dec"]))  # 印的赤纬必须等于真值
        # 真值侧再钉一道: 桩 CSV 确实带这两列, 示例的列名必须读得到
        assert "ps1_ra" in result.sources[0].raw_data  # 直断列存在: 键名写错时这一步更早红

        # 第 3 步 docstring 预期输出: "Saved to: <路径>" 且文件真的落在 best_data/ 下
        saved = summary["path"]  # 示例把落盘路径回传, 供断言取用
        assert isinstance(saved, str) and f"Saved to: {saved}" in printed                           # 落盘提示行必须出现
        saved_file = Path(saved).resolve()                                                          # 落盘路径取自示例返回值
        assert saved_file.is_file()  # 真落盘: 只打印路径不算下载成功
        assert saved_file.suffix == ".csv"  # 挡"扩展名写错": 下游按后缀选解析器
        assert saved_file.parent == (tmp_path / "best_data").resolve()                            # 必须落在临时数据目录下: 写到工作区就是污染
        csv_lines = saved_file.read_text(encoding="utf-8-sig").splitlines()  # utf-8-sig: 容忍 BOM
        # 落盘列序取排序并集 (serialization.delimited_text), 断言列存在而非列序
        assert "ps1_source_id" in csv_lines[0] and "ps1_ra" in csv_lines[0]                         # 表头必须含标识列与赤经列
        assert len(csv_lines) == FAKE_ROW_COUNT + 1  # 表头 + 两数据行: 少一行即丢数据

        # 第 4 步: 列约束查询 (docstring 声明无打印), 返回站点原始投影行
        rows = summary["rows"]                                                                      # 取约束查询行
        assert isinstance(rows, list) and len(rows) == FAKE_ROW_COUNT                               # 行数必须与桩一致
        assert "ps1_ra" in rows[0]  # 裸投影行: 键是站点列名而非模型字段名

        # 第 5 步 docstring 预期输出: "Cross-matched M sources"; 回包是
        # BestQueryResult 信封, sources 是 BestSource 领域对象 (ra/magnitudes)
        assert f"Cross-matched {FAKE_ROW_COUNT} sources" in printed                                 # 交叉匹配那行提示必须出现
        matches = summary["matches"]                                                                # 取匹配结果
        assert matches.success is True  # proximity 批量路径应一次成功, 不该回退逐点
        assert len(matches.sources) == FAKE_ROW_COUNT                                               # 匹配数必须与桩一致
        for source in matches.sources:                                                              # 逐个源核对
            # 赤经必须落在**本次提交的两个输入点**之一的附近 (180 与 181)。
            # 原断言只钉了 180.0001/180.0002 —— 那是在桩**位置失明**的前提下写的:
            # 两个坐标都拿到同一份固定 CSV, 于是"只可能"出现这两个值。桩改成按圆心
            # 回行之后, 181 附近的源同样合法, 继续钉死 180 就变成在钉桩的谎。
            assert any(abs(source.ra - ra_in) < 2e-4 for ra_in in (180.0, 181.0)), (
                f"赤经 {source.ra} 既不靠近 180 也不靠近 181 —— 与提交的两个坐标都对不上"
            )
            assert "r" in source.magnitudes                                                         # 星等字典必须非空

        # 第 6 步 docstring 预期输出: "PS1 has K columns" (K=协议层登记列数)
        expected_columns = len(CATALOG_COLUMNS["ps1"])  # 取协议层登记值, 不写死数字
        assert f"PS1 has {expected_columns} columns" in printed                                   # 列数提示必须出现: 数字取自协议层, 不写死
        assert len(summary["columns"]) == expected_columns  # 元信息列数与协议层同源

        # 第 7 步 docstring 预期输出: 连通状态 (布尔; 禁版本号铁律 — 连接面
        # 无 version 信封可残留, 星表注册表由 test/unit/meta 守护)
        assert "Connected: True" in printed  # 桩回 200 -> 探测结果必须是 True


class TestExampleImportSideEffects:
    """A1-08: 导入示例模块不得发出任何网络请求 (示例已挂 __main__ 守卫)。"""

    @pytest.mark.parametrize("script", ["example_quickstart_client.py", "example_skill_usage.py"])  # 两个示例都要断: 改一个漏一个正是本条要防的
    def test_import_sends_no_request(self, offline, monkeypatch, script):
        """以非 __main__ 身份导入示例: 零请求, 且只绑定出可调用的 main。

        验证什么: ``import examples.*`` / IDE 索引 / 文档工具扫描都只导入
        不运行 —— 改前两个示例是"导入即执行", 任何一次索引都立刻打真实站点
        并绕过全套离线桩 (桩只在这套测试里装, 索引器可没有)。所以这条门禁
        断言的是**导入本身零副作用**, 而不只是"示例跑得对"。为什么重要:
        "随便 import 就打站点"不是好性质, 真实联网必须由显式运行触发。
        """
        module_name = f"_f4_import_probe_{script.replace('.', '_')}"  # 唯一模块名: 避免与已缓存的示例模块互相干扰
        spec = importlib.util.spec_from_file_location(module_name, EXAMPLES_DIR / script)  # 按路径建 spec, 模块名刻意不是 __main__
        assert spec is not None and spec.loader is not None, f"无法为 {script} 建 import spec"  # 建不出 spec 就不算"导入成功", 必须红
        module = importlib.util.module_from_spec(spec)  # 按 spec 造模块对象, 尚未执行
        monkeypatch.setitem(sys.modules, module_name, module)  # 登记后再执行: 被 import 的子模块能按名找到它
        spec.loader.exec_module(module)  # 真正执行模块顶层 —— 这一步以前就会发请求
        assert not offline.calls, f"import {script} 即发出请求: {offline.calls} (示例必须挂 __main__ 守卫)"  # 零请求 = 导入无副作用
        assert callable(getattr(module, "main", None)), f"{script} 未暴露 main(): 守卫下主路径应可显式调用"  # 守卫不等于把主路径删掉
