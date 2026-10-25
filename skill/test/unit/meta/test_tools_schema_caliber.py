# -*- coding: utf-8 -*-
"""``references/tools.schema.json`` 的 ``cost.http_requests`` ↔ ``src/ai_tools.py``
**口径对齐**门禁 (S4-01)。

为什么要有这个门禁: 那条 schema 描述原本写「真实 wire 请求数 (Session.request
计数)」—— 字段名和描述都承诺它是线网往返数, 而实现在 ``Session.request`` 出口
包了一层计数, **看不见** ``HTTPAdapter.send`` 内部的 urllib3 ``Retry`` 重试。
照描述去读这个数的调用方会拿到一个**偏小**的值, 却以为那就是站点收到的请求数。

本门禁断言的不是"schema 写了什么", 而是**实现挂在哪一层**:
  - 挂在 ``Session.request`` (非 wire 层) → 描述**不得**承诺 wire, 且**必须**
    写明不含适配器层重试;
  - 挂在 ``HTTPAdapter.send`` (真 wire 层) → 描述**必须**承诺 wire。

判据取自实现源码与**一次真实往返** (本地回环 HTTP 服务), 不抄一份字面量: 把实现
改到 wire 层, 这条门禁会要求改描述; 把描述改回"真实 wire", 门禁立刻红。

对照纪律: 每条"必须成立"都配一条"不该被误伤"的反向用例 —— ``_Layer`` 反过来
给成 wire 层时, 断言方向必须整体翻转, 否则把实现改对反而会被门禁拦住。
"""
from __future__ import annotations

# 标准库: sys 路径锚定 / ast 判挂载层 / json 读 schema / http 本地回环服务 / pathlib
import ast
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

SKILL_ROOT = Path(__file__).resolve().parents[3]  # 仓根: 本件在 test/unit/meta/ 下三级
if str(SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILL_ROOT))

from src.client import BestClient  # noqa: E402  (路径锚定之后才能导入)
from src.protocol import RETRY_STATUS_CODES  # noqa: E402

SCHEMA_PATH = SKILL_ROOT / "references" / "tools.schema.json"
AI_TOOLS_SRC = SKILL_ROOT / "src" / "ai_tools.py"

# 实现挂载计数器的两个候选层。判据是**源码里真的把哪个属性替换了**, 不是哪个名字
# 出现在注释里 —— 本仓的 docstring 恰恰会把 ``HTTPAdapter.send`` 写在注释里解释
# "重试发生在这里", 拿字符串 find 判层必然误判成 wire 层。
CLIENT_LAYER_ATTR = "request"  # Session.request: requests 高层出口, 一次高层调用记一次
WIRE_LAYER_ATTR = "send"        # HTTPAdapter.send: 适配器出口, 一次线网往返记一次
_LAYER_ATTRS = frozenset({CLIENT_LAYER_ATTR, WIRE_LAYER_ATTR})  # 只认这两种挂载点


class _Layer:
    """实现挂载层的枚举。带一个反向用例专用的"假 wire 层"取值。"""

    CLIENT = "client"  # Session.request: 一次高层调用记一次, 看不见适配器重试
    WIRE = "wire"      # HTTPAdapter.send: 一次线网往返记一次


def _load_schema() -> dict[str, Any]:
    """读工具契约 schema (utf-8, 容忍 Windows BOM)。"""
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8-sig"))  # utf-8-sig: 容忍 Windows BOM


def _http_requests_description() -> str:
    """取 ``cost.http_requests`` 的描述文本 (判据入口)。"""
    cost = _load_schema()["envelope"]["properties"]["cost"]["properties"]  # 成本区三项
    return cost["http_requests"]["description"]                          # 只取本门禁盯的那一项


def _impl_layer() -> str:
    """实测实现把计数器挂在哪一层 —— 判据是 AST 里**真的替换了哪个属性**。

    刻意走 AST 而不是字符串 find: ``src/ai_tools.py`` 的 docstring 会把
    ``HTTPAdapter.send`` 写在注释里解释"重试发生在适配器内部", 字符串判层会
    把这段解释当成"挂载点", 于是不管实现怎么改都判成 wire 层 —— 门禁当场失效。
    属性**赋值**才骗不了人: 计数器挂哪儿, 哪个属性就被换掉了。
    """
    tree = ast.parse(AI_TOOLS_SRC.read_text(encoding="utf-8"))  # 解析整模块, 挂载点必在其中
    replaced: set[str] = set()                                    # 收集被替换掉的属性名
    for node in ast.walk(tree):                                   # 全树走一遍, 不假设挂载点在哪一行
        # 只认赋值 (Assign); AugAssign 那种 `self._requests += 1` 是自增, 不是挂载点
        if isinstance(node, ast.Assign):                          # 赋值才可能是"把计数器挂上去"
            replaced.update(
                target.attr for target in node.targets
                if isinstance(target, ast.Attribute) and target.attr in _LAYER_ATTRS
            )
    if replaced == {CLIENT_LAYER_ATTR}:                           # 只换了 request 一个属性
        return _Layer.CLIENT                                      # 客户端层: 看不见适配器重试
    if replaced == {WIRE_LAYER_ATTR}:                             # 只换了 send 一个属性
        return _Layer.WIRE                                        # 真 wire 层: 一次往返记一次
    # 两层都挂或都没挂: 计数层已改成第三种形态, 判据失效 —— 显式炸出来, 不猜。
    raise AssertionError(
        f"无法判定 http_requests 计数层 (被替换的属性 = {sorted(replaced) or '无'}); "
        "实现若换层, 请同步更新本门禁与 schema 描述"
    )


def _description_says_wire(description: str) -> bool:
    """描述是否在承诺「线网往返数」。

    只认**强承诺词** ("真实 wire" / "线网往返")。"不含适配器层重试"这类排除句
    里有 "线网" 二字, 但它恰恰是在**否认** wire 口径, 不能算承诺 —— 所以判据看
    的是"wire 请求数"与"真实 wire"这种计数名词短语, 不是裸 "wire" 子串。
    """
    normalized = description.replace(" ", "")        # 去空格: 判据不因排版换行而失配
    return "真实wire" in normalized or "wire请求数" in normalized  # 两个强承诺词, 任一命中即算承诺


class TestDescriptionMatchesImplementationLayer:
    """描述对"是不是线网往返数"的承诺, 必须与实现挂载层一致。"""

    def test_impl_is_not_on_wire_layer(self):
        """实现当前挂在 ``Session.request`` (客户端层), 看不见适配器重试。

        这条把"实测结论"钉成门禁: 哪天有人把计数改到 ``HTTPAdapter.send``,
        本条转红, 提醒同步改描述 (而不是让 schema 继续骗人)。
        """
        assert _impl_layer() == _Layer.CLIENT, (
            "http_requests 计数器已不在 Session.request 层 —— "
            "请先确认线网口径, 再同步 schema 描述与本门禁"
        )

    def test_client_layer_description_must_not_promise_wire(self):
        """客户端层 ⇒ 描述**不得**承诺真实 wire 请求数 (S4-01 那条假描述)。"""
        assert not _description_says_wire(_http_requests_description()), (
            "实现挂在 Session.request (看不见 HTTPAdapter.send 内的重试), "
            "schema 描述却承诺真实 wire 请求数 —— 调用方会拿到偏小的值当线网账本用"
        )

    def test_client_layer_description_must_state_the_exclusion(self):
        """客户端层 ⇒ 描述**必须**写明不含适配器层重试 (不写等于没承诺)。"""
        description = _http_requests_description().replace(" ", "")  # 同样去空格再判关键词
        assert "重试" in description and "不含" in description, (      # 排除句两个半截都要在
            "描述必须写明本字段不含 HTTPAdapter.send 内的重试请求, "
            "否则调用方无从知道它偏小"
        )

    def test_wire_claim_detector_fires_on_wire_wording(self):
        """反向用例: 判据本身**认得** wire 承诺, 不是单向黑名单。

        没有这条, 上面两条就成了"禁止出现 wire 字样" —— 哪天有人真把计数改对
        (挂到 ``HTTPAdapter.send``), 描述理应改口说 wire, 门禁却会拦住这个
        正确修改。判据对两种说法必须给出相反结论, 才敢拿它当门禁。
        """
        # 排除句里有"线网"二字但**否认** wire 口径: 不得被判成承诺
        assert not _description_says_wire("客户端层请求计数, 不含适配器层重试 (线网往返另计)"), (
            "排除句不是 wire 承诺, 判据不能把它误判成承诺"
        )
        # 真正的承诺 (S4-01 修掉的那句原值): 必须被判成承诺
        assert _description_says_wire("真实 wire 请求数 (Session.request 计数)"), (
            "判据必须认得 S4-01 修掉的原描述, 否则那条门禁形同虚设"
        )


class _FlakyHandler(BaseHTTPRequestHandler):
    """前两次回 429 (可恢复码, 落在 ``RETRY_STATUS_CODES`` 里), 第三次回 200。

    计数放在类属性上: 请求处理在服务端线程里, 断言在测试线程里读。
    """

    received = 0  # 服务端**真实收到**的请求数: 这就是"线网往返数"的判据

    def do_GET(self) -> None:  # noqa: N802  (BaseHTTPRequestHandler 定的名字)
        """记一次到达; 前两次 429 触发适配器层重试, 第三次才给真回包。"""
        type(self).received += 1                                   # 类属性: 服务端线程写, 测试线程读
        if type(self).received <= 2:                               # 前两次才回 429, 第三次给真回包
            self.send_response(429)   # 可恢复码: 逼 HTTPAdapter.send 内部重试
            # **不发 Retry-After**: respect_retry_after_header=True 会照它睡, 门禁不该靠等待
            self.end_headers()        # 空体: 429 不带内容
            return                    # 提前返回, 不落到下面的 200 分支
        body = b'{"total": 42}'  # 计数端点回包形态: count 工具据此报 total
        self.send_response(200)     # 第三次才成功: 前两次的 429 已各触发一次重试
        self.send_header("Content-Type", "application/json")  # JSON 体: 与真实端点同形
        self.send_header("Content-Length", str(len(body)))    # 显式长度: 不靠连接关闭判界
        self.end_headers()          # 头写完才发体, 否则客户端读不全
        self.wfile.write(body)      # 写出回包, 本次往返收尾

    def log_message(self, *args: Any) -> None:
        """静音: 门禁输出只留 pytest 自己的断言结果。"""


@pytest.fixture
def flaky_client() -> BestClient:
    """起一个本地回环服务, 让 BestClient 朝它发 GET, 并把退避压到 0。

    退避压 0 是为了让门禁快: 本门禁要证的是**计数挂在哪一层**, 不是重试策略
    的退避曲线。``status_forcelist`` 仍取生产常量 ``RETRY_STATUS_CODES``,
    免得"白名单改了这条也红" —— 那是另一条门禁的事。
    """
    from requests.adapters import HTTPAdapter  # 函数内导入: 只本用例用
    from urllib3.util.retry import Retry  # 同上

    _FlakyHandler.received = 0  # 每个用例从零起算
    server = ThreadingHTTPServer(("127.0.0.1", 0), _FlakyHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = BestClient(
            base_url=f"http://127.0.0.1:{server.server_address[1]}",  # 朝本地回环发
            rate_limit=0.0,  # 关节流: 本门禁不测限流, 只测计数层
        )
        adapter = HTTPAdapter(max_retries=Retry(
            total=3,
            backoff_factor=0,  # 退避 0: 门禁要秒级, 不等真实 2/4/8s
            status_forcelist=sorted(RETRY_STATUS_CODES),  # 白名单同生产
            allowed_methods=["GET"],  # 只放 GET, 同生产 (POST 重试会造孤儿会话)
        ))
        client.session.mount("http://", adapter)
        yield client
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


class TestWireCountIsBelowReportedCount:
    """真实往返一次: 服务端收 3 次, 而 ``cost.http_requests`` 报 1 (R1 实证)。"""

    def test_three_wire_requests_reported_as_one(self, flaky_client: BestClient):
        """服务端收 3 次 (1 次首发 + 2 次适配器重试), 报 1。

        这条是 S4-01 的**经验**判据: 描述里那句"实测: 服务端收 3 次, 本字段报 1"
        不是修辞, 是本用例跑出来的。哪天计数真挪到 wire 层, 两侧数字会合拢,
        本条转红 —— 那时描述才允许改口说 wire。
        """
        from src.ai_tools import ToolBox  # 函数内导入: ToolBox 构造会建 BestCrossMatch, 只想在用到时装

        result = ToolBox(flaky_client).count("s3839")  # 一次 GET (可重试的那一半)

        assert result.status.get("ok") is True, f"重试后应成功, 实得 {result.to_dict()}"  # 先确认重试真的收敛了
        assert _FlakyHandler.received == 3, (                                           # 线下侧: 站点实收
            f"服务端应收 3 次 (首发 1 + 重试 2), 实收 {_FlakyHandler.received}"
        )
        assert result.cost["http_requests"] == 1, (                                     # 线上侧: schema 那个字段
            "Session.request 层计数看不见适配器重试: 服务端收 3 次时本字段应报 1, "
            f"实报 {result.cost['http_requests']}"
        )

    def test_reported_count_is_never_above_wire_count(self, flaky_client: BestClient):
        """反向用例: 本字段是**线网开销的下界**, 不得高报。

        没有这条, 上面那条只钉住了"恰好 3 → 1"; 哪天有人把计数器挪到会**多记**
        的地方 (例如按方法名估算), 门禁就看不见了。
        """
        from src.ai_tools import ToolBox  # 同上: 只在本用例用, 不进模块级导入

        result = ToolBox(flaky_client).count("s3839")  # 同一场景再跑一次, 取下界判据

        assert result.cost["http_requests"] <= _FlakyHandler.received, (  # 报数不得超实收
            f"报 {result.cost['http_requests']} > 线网实收 {_FlakyHandler.received}, "
            "本字段是下界口径, 高报即虚增预算"
        )
