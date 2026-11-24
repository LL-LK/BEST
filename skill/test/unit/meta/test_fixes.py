"""缺陷修复的回归测试 — 只覆盖当前 astro-best 源码里真实实现的行为。

断言范围只取 ``src/`` 里确实存在的 API。星表前缀星等解析、带 cos-dec 的
球面去重、查询构造器校验、downloader/checkpoint 路径穿越防护、``tap_query``、
交叉匹配最近邻挑选这些能力 ``src/`` 均未实现, 因此本文件不对它们做任何断言:
断言不存在的功能只会得到恒绿或恒红的假结论。
本文件保留的只验证今天确实存在的 API:

  - :func:`src.csv_safety.sanitize_cell` — CSV 注入防护, 且不误伤合法负数;
  - :func:`src.protocol.qualify_column` / :func:`parse_csv_rows` —
    带校验的列名限定与旧版 CSV 解析;
  - :func:`src.crossmatch._angular_separation_arcsec` — haversine 大圆角距;
  - :class:`src.client.BestClient` — 5xx 单层重试 (线上尝试次数恒为
    :data:`src.protocol.MAX_RETRIES` + 1), 以及
    :class:`src.scripts.context.QueryContext` 对空历史的截断。
"""
from __future__ import annotations  # 标准库: 注解延迟求值

# 标准库: 读回落盘 CSV 校验内容 + mock/patch 在重试层之下打桩 (真实重试逻辑照跑)
from pathlib import Path
from unittest import mock

# 第三方: pytest.raises 承载负路径断言
import pytest

# 本地: 跨匹配角距 / CSV 注入清洗 / 查询结果数据模型
from src.crossmatch import _angular_separation_arcsec
from src.csv_safety import sanitize_cell
from src.models import BestQueryResult, BestSource

# --------------------------------------------------------------------------
# #6 — haversine 大圆角距 (实现已迁至 src.crossmatch)
# --------------------------------------------------------------------------

def test_angular_separation_haversine():
    """haversine 角距必须是大圆距离, 且对 dec 收缩因子 honest。

    赤道处 1° = 3600" 钉住单位换算; 近极点情形钉住 cos(dec) 收缩 ——
    dec=89° 处的 1° RA 只有约 63", 平面近似会把它错算成 3600"。
    """
    # 大圆上 1 度 = 3600 角秒 (钉住单位换算)
    assert abs(_angular_separation_arcsec(0, 0, 0, 1) - 3600.0) < 1e-6                      # 赤道处一度必须正好 3600 角秒: 单位错一次整条就废
    # 对称性: 点到自身的角距为 0
    assert abs(_angular_separation_arcsec(10, 20, 10, 20)) < 1e-9                                # 自身角距必须为零: 对称性是球面距离的基本性质
    # 近极点处 cos(dec) 收缩必须生效: dec=89° 上 1° 的 RA 只有约 63",
    # 平面近似会错算成 3600"。
    polar = _angular_separation_arcsec(0.0, 89.0, 1.0, 89.0)                                   # 近极点取样: 平面近似在这里会错到 3600 角秒
    assert polar < 100.0  # 阈值 100 角秒卡在真值 63 与平面近似 3600 之间: 两类实现都断得掉


# --------------------------------------------------------------------------
# #15 — CSV 注入防护不破坏负数
# --------------------------------------------------------------------------

class TestCSVSafety:
    """sanitize_cell 的契约: 公式向量加引号, 合法数值原样透传。

    这一组全部落在"不得误伤"一侧: 消毒一旦过度, 赤经赤纬这种最普通的列就
    全部退化成文本, 而退化后的 CSV 打开时完全正常, 要到下游按数值筛选时
    才暴露, 那时已经没人想得到是落盘这一步动了手脚。
    """

    def test_formula_cell_escaped(self):
        """以 ``=`` 开头的公式向量必须被引号前缀中和 (CSV 注入)。

        载荷是真实可执行的 calc 调用串: 只判"以 = 开头"不够, 还得确保输出
        确实被引号包住, 否则在 Excel 里双击这个文件就会执行。
        """
        assert sanitize_cell("=cmd|' /C calc'!A0").startswith("'")  # 只断 startswith 而非等值: 中和允许保留原文, 供人眼识别这格被改过

    def test_negative_numeric_string_preserved(self):
        """负数字符串是合法天体测量值, 绝不能被当成公式误加引号。

        -5.0 取的是南天赤纬的常见形态: 它既以符号位开头又像表达式, 正是
        那些"看到符号就当中和"的实现最容易误伤的一类。
        """
        assert sanitize_cell("-5.0") == "-5.0"  # 整值与两位小数成对: 只测一个整数形态的实现按前缀截断照样能过
        assert sanitize_cell("-12.34") == "-12.34"                                          # 合法负数必须原样返回: 消毒误伤负数会让数值列退化成文本

    def test_positive_numeric_string_preserved(self):
        """``+`` 开头的正数同样合法, 不得被引起来。

        这条与 @ 前缀那条成对: 同一个"符号位即危险"的判据会同时误伤 + 与漏防
        @, 两条一起守才能把"按符号判危险"这种省事实现挡在外面。
        """
        assert sanitize_cell("+12.0") == "+12.0"  # 正号与负号成对: 同一套符号位判据会同时误伤 + 与漏防 @

    def test_scientific_notation_negative_preserved(self):
        """科学计数法负数不得被误判为公式 (``-1.5e-3`` 里的 e 不是命令)。"""
        assert sanitize_cell("-1.5e-3") == "-1.5e-3"  # 科学计数法里的 e 不是命令名: 只扫 =+-@ 三个前缀就误伤真值

    def test_at_prefixed_non_numeric_escaped(self):
        """``@`` 开头的非数值 (Excel 函数调用) 必须被中和。

        @ 在旧版 Excel 里是公式的另一种触发前缀, 与 = 互不替代: 只防 = 的
        实现对 @ 完全失守, 而这条断言就是守住那个缺口。
        """
        assert sanitize_cell("@SUM(A1:A2)").startswith("'")  # @ 是公式的另一种触发前缀, 与 = 互不替代: 只防 = 的实现对 @ 完全失守

    def test_non_formula_string_untouched(self):
        """普通字符串与星表名 (含 ``+`` 的 BD 名) 必须原样通过。

        BD+17_4708 是真实存在的星表编号格式: 中间的 + 必须活下来, 一旦被
        引号包住, 交叉匹配时按星表名建的索引就对不上这条记录。
        """
        assert sanitize_cell("18.5") == "18.5"                                                      # 普通数值同样原样返回
        assert sanitize_cell("BD+17_4708") == "BD+17_4708"  # BD 编号含 + 是真实星表编号形态: 被引号包住后按名建的索引就对不上

    def test_non_string_passthrough(self):
        """非字符串输入原样返回 (float/None 都不是注入向量)。

        None 也要覆盖: 缺测值在数据里是常态, 实现若把它转成字符串 "None",
        导出文件里就会多出一列字面量 None, 统计时被当成一次有效观测。
        """
        assert sanitize_cell(18.5) == 18.5  # float 原样返回: 中和逻辑若强转 str, 数值列会整体退化成文本
        assert sanitize_cell(None) is None  # None 不能变成字符串 None: 导出里会多出一列字面量, 统计时算一次有效观测

    def test_southern_dec_row_not_corrupted(self, tmp_path):
        """端到端: 落盘 CSV 里的 -5.0 dec 不得变成被引号包住的 ``'-5.0``。

        模拟对象/协议阶段: BestDownloader 内部走真实 _save_result (csv 分支),
        client 仅用于构造 (rate_limit=0 表示不发真实请求)。
        """
        # src.client: 两阶段异步 HTTP 客户端 (被测入口); src.downloader: 流式下载 + 校验和
        from src.client import BestClient
        from src.downloader import BestDownloader
        result = BestQueryResult(                                                                   # 成功标志
            success=True, total_count=1, returned_count=1,                                          # 总数与返回数
            sources=[BestSource(source_id="s1", ra=10.0, dec=-5.0, magnitudes={"r": 15.0})],        # 带负赤纬的源: 消毒误伤时这条会红
        )
        dl = BestDownloader(BestClient(rate_limit=0), output_dir=str(tmp_path))  # 限流归零 + 落盘进 tmp_path: 零真实请求, 也不污染仓库工作区
        path = dl._save_result(result, "out.csv", "csv")                         # 走真实 _save_result: 消毒发生在写文件那一刻, 只测 sanitize_cell 断不到
        text = Path(path).read_text(encoding="utf-8")                                               # 回读落盘字节
        assert "'-5" not in text  # 断「没有被引起来」: 过度消毒在这里表现为整列退化成带引号文本
        assert "-5.0" in text                                                                       # 负赤纬必须原样落盘


# --------------------------------------------------------------------------
# #20 — qualify_column 必须校验 (不允许「含点即绕过」)
# --------------------------------------------------------------------------

class TestQualifyColumn:
    """列名限定白名单: 含点、含控制字符都不得绕过校验。

    这道校验挡的是查询构造被污染, 它的失效不会抛错, 只会让一条畸形的列
    引用原样送到服务端 —— 所以"看起来是合法字符串"必须在这里就被拒掉。
    """

    def test_dot_bypass_rejected(self):
        """带点列名 (``evil.col``) 不得靠「含点即已限定」绕过白名单。

        名字里带点不等于调用方已自行限定 —— 按这条省事判据放行, 任意列引用
        都能穿过协议层校验, 查询构造被污染且无任何报错 (静默失守)。
        """
        # 函数内导入: qualify_column 是列名白名单校验入口 (本条验"含点不得绕过")
        from src.protocol import qualify_column
        with pytest.raises(ValueError):                                                             # 非法列名必须抛错
            qualify_column("ps1", "evil.col")  # 含点不得视为已限定: 任意列引用都能穿过协议层校验且不报错

    def test_invalid_chars_rejected(self):
        """含 NUL 等控制字符的列名必须被拒, 白名单是显式字符集校验 (Q-20)。

        控制字符会随列名进入下游协议请求与落盘输出, 污染响应解析/文件格式
        且极难排查 — 静态拒绝是唯一可靠的防线。
        """
        # 函数内导入: 同一条校验入口 (本条验"控制字符必须被拒")
        from src.protocol import qualify_column
        with pytest.raises(ValueError):                                                             # 另一类非法输入同样抛错
            qualify_column("ps1", "rpsf\x00")  # NUL 进列名会污染请求与落盘: 静态拒绝比下游解析时才发现可靠

    def test_valid_column_qualified(self):
        """合法列名要被正确限定: 裸列名加 catalog 前缀, 自带前缀的归一化。

        ``ps1_rpsf`` 与 ``rpsf`` 必须都归一到 ``ps1.rpsf`` 这一种形态; 同一
        列若存在两种写法, 下游按名匹配会静默漏算 (丢数据而不报错)。
        """
        # 函数内导入: 同一条校验入口 (本条验"裸名与带前缀名归一到同一形态")
        from src.protocol import qualify_column
        assert qualify_column("ps1", "rpsf") == "ps1.rpsf"  # 裸名与带前缀名归一到同一形态: 两种写法并存会让按名匹配静默漏算
        assert qualify_column("ps1", "ps1_rpsf") == "ps1.rpsf"                                      # 列名限定必须补表前缀: 裸列名服务端不认


# --------------------------------------------------------------------------
# #21 — parse_csv_rows 遇未登记星表不得 KeyError
# --------------------------------------------------------------------------

class TestParseCsvRows:
    """CSV 行解析: 未登记 catalog 降级为普通表头, 无表头行用真实列名。"""

    def test_unknown_catalog_no_keyerror(self):
        """未登记 catalog 不得抛 KeyError, 必须降级为普通表头解析 (Q-21)。

        新星表上线时服务端先返数据、本地列登记后更新, 此时 KeyError 会让
        整次查询静默崩溃 (用户只看到异常或空结果) — 降级解析保证数据可用。
        """
        from src.protocol import parse_csv_rows
        # catalog 非空但未登记时不得抛 KeyError (否则整次查询崩在解析期)
        rows = parse_csv_rows("a,b\n1,2", catalog="unknown_cat")  # 未登记 catalog 降级成普通表头: KeyError 会让整次查询崩在解析期
        assert rows == [{"a": "1", "b": "2"}]                                                       # 解析结果必须逐项相等

    def test_std_headerless_uses_first_real_columns(self):
        """无表头 std 行必须用该星表真实前几列, 不得一律标成 ra/dec。

        把 col0 固定标成 std_ra 会让 std_id 被当赤纬、坐标全部偏移却无任何
        报错 (静默数据污染); 按 CATALOG_COLUMNS 真实列名映射后, 5 个值正好
        对上 std_id/std_name/std_ra/std_dec/std_mag。
        """
        from src.protocol import parse_csv_rows
        # 一个每格都是数字的无表头 std 行会落进「无表头」分支。前两列按该星表
        # 真实列名映射 (std_id, std_name, std_ra, std_dec, std_mag) 共 5 列,
        # 不是一律标成 ra/dec。
        rows = parse_csv_rows("1,2,180.0,30.0,15.0", catalog="std")  # 五列全数字才会落进无表头分支: 少一列就换成分支, 这条就测不到
        # 5 个值正好映射到 5 个 std 列, 因此表头 == CATALOG_COLUMNS["std"]
        assert "std_id" in rows[0]                                                                  # 带前缀的键必须在
        assert "std_ra" in rows[0]                                                                  # 赤经键必须在
        assert "std_mag" in rows[0]                                                                 # 星等键必须在
        assert rows[0]["std_id"] == "1"  # col0 必须是 std_id: 标成 std_ra 会让坐标整体偏移却不报错
        assert rows[0]["std_ra"] == "180.0"                                                        # 赤经值也要对上: 键在而值错同样是解析事故


# --------------------------------------------------------------------------
# #8 — 单层重试 (不得重复计数)
# --------------------------------------------------------------------------

class TestRetry:
    """钉住 urllib3 Retry 只装一层: 持续 5xx 的线上尝试次数 = MAX_RETRIES+1。"""

    @staticmethod
    def _patched_transport(status: int, headers: dict | None = None, body: bytes = b""):
        """在 urllib3 传输层打桩, 让真实重试循环照跑并变得可计数。

        模拟对象与协议阶段: 只补丁 ``_make_request`` —— 它位于重试循环之下、
        socket 之上, 唯有在这里尝试次数才可观测; mock ``Session.request``
        会整层跳过 adapter, 双层重试将完全不可见。

        urllib3 2.x 移除了 ``HTTPConnectionPool.ResponseCls`` 类属性 (响应构造
        已下沉到 ``connection.py`` 的 ``HTTPConnection.getresponse``), 所以不再
        需要把响应类换成直通桩: ``_make_request`` 直接返回真实的
        ``urllib3.HTTPResponse`` 即可。

        调用方还需配 ``_new_conn`` 替身连接 (见 ``_fake_conn``) —— 否则本机
        网络不可用时请求死于 connect 阶段, 本桩一次未达 (attempts=0), 测试
        随环境假失败。
        """
        # io: 字节流构造 (CSV/响应体夹具); urllib3: 直连底层以验证适配器重试是唯一一层
        import io as _io

        import urllib3

        attempts = {"n": 0}                                                                         # 尝试计数: 断言要数"真的重试了几次"

        def make_request(self, *args, **kwargs):
            """传输层打桩: 每被调用一次即记一次真实线上尝试, 并回脚本化响应。

            计数是「单层重试」断言的唯一事实源 — mock ``Session.request``
            会整层跳过 adapter, 旧版测试正因此漏看了双层重试。
            """
            attempts["n"] += 1  # 每次被调即记一次线上尝试: 计数点在传输层, 上层重试几次就记几次
            return urllib3.HTTPResponse(
                body=_io.BytesIO(body), status=status,                                              # 造一个传输层响应
                headers=headers or {}, preload_content=False,                                       # 不预读响应体: 让重试判定走真实路径
            )

        return attempts, make_request

    @staticmethod
    def _fake_conn():
        """最小连接替身: urlopen 只 touch ``is_dropped``/``close`` (不建真实 socket)。

        存在理由: 2026-09-30 实测 — 本机网络不可用 (或中间盒改写 SSL) 时,
        请求在 connect 阶段就被 Retry 吞掉, ``_make_request`` 桩一次未达,
        ``attempts`` 恒 0, 测试随环境假失败。补丁 ``_new_conn`` 回本替身后,
        计数只反映 adapter 的重试层数, 全程零真实 socket。
        """

        class _FakeConn:
            """替身连接: 标记未断开 + 关闭空操作 — 让 _make_request 桩可到达。"""

            is_dropped = False                                                              # 模拟"连接被丢弃": 这是 5xx 之外最常见的重试触发
            sock = None                                                                            # 套接字替身: 重试时会重连, 没有它连不上

            def close(self):
                """空操作 — 替身没有真实句柄可关 (只为让连接状态字段存在)。

                刻意不做任何标记: 本用例数的是重试次数, 不该让"关过连接"
                这类旁路状态参与判据, 否则关闭动作的副作用会混进计数。
                """

        return _FakeConn()

    def test_single_layer_retry_on_503(self, monkeypatch):
        """持续 503 必须只花费 MAX_RETRIES+1 次线上尝试 (单层重试)。

        重试必须收敛到 session adapter 的 ``Retry`` 单一层: 在其之上再叠一层
        手写重试循环, 一次瞬时失败会放大成最多 16 次真实请求。

        桩必须打在 ``_make_request`` —— 打 ``Session.request`` 会整层跳过
        adapter, 双层重试根本不可见。唯一客户端入口 (BestClient) 由此被钉住。
        """
        # requests: 打桩/直连 HTTP 层; urllib3: 直连底层以验证适配器重试是唯一一层; src.client: 两阶段异步 HTTP 客户端 (P1 后唯一生产入口)
        import requests as req
        import urllib3

        from src.client import BestClient
        from src.protocol import MAX_RETRIES

        # 隔离代理环境变量: 机器若配了 HTTP(S)_PROXY, requests 会先跟代理建隧道,
        # 请求根本进不到连接池的 _make_request, 计数恒为 0 -> 测试假失败。
        # 这是环境噪音不是产品缺陷, 所以在测试内清掉而不是放宽断言。
        for var in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",                                    # 清掉代理变量: 本机代理会让打桩请求绕过连接池
                    "http_proxy", "https_proxy", "all_proxy"):                                      # 大小写两套代理变量名都要清
            monkeypatch.delenv(var, raising=False)                                                  # 逐个清: 漏一个就足以让打桩失效

        client = BestClient(rate_limit=0)  # 限流归零: 本用例数的是重试次数, 不该被真实 sleep 拖慢
        attempts, make_request = self._patched_transport(503)                                       # 先把 5xx 传输层与连接替身都装好
        fake_conn = self._fake_conn()                                                               # 连接替身必须先造好: 两次重试要各连一次
        conn_cls = urllib3.connectionpool.HTTPConnectionPool                                        # 连接池类是打桩目标
        with mock.patch.object(conn_cls, "_make_request", make_request), \
                mock.patch.object(conn_cls, "_new_conn", lambda self: fake_conn), \
                mock.patch("time.sleep"), pytest.raises(req.RequestException):                      # 屏蔽退避睡眠: 让重试用例不付墙钟
            # http (非 https): 重试层被测行为与协议无关; https 会在断网时
            # 死于 SSL connect, 桩达不着 (环境假失败), 见 _fake_conn 说明
            client.session.get("http://x.invalid/")                                                 # 走公开的会话出口
        assert attempts["n"] == MAX_RETRIES + 1, (  # 等式而非上界: 双层重试会让次数翻倍, 上界断言会放它过去
            f"expected one retry layer ({MAX_RETRIES + 1} attempts), "                              # 报告应尝试次数
            f"observed {attempts['n']}"                                                             # 报告实到次数
        )


# --------------------------------------------------------------------------
# #27 — 空历史上下文截断
# --------------------------------------------------------------------------

class TestScripts:
    """QueryContext 截断: 空历史也必须返回空视图而非报错。

    截断函数在每次会话开场都会被调一次, 它的"最坏输入"不是超大历史而是
    完全没有历史 —— 而那恰恰是第一次查询时的常态。
    """

    def test_context_truncate_empty_no_error(self):
        """空历史调 truncate 必须返回空视图, 不得报错 (Q-27)。

        每条会话开场都是空历史, agent 侧每次都会调 truncate 构造上下文;
        这里抛异常等于第一次查询就崩, 且现象是静默的空上下文。
        """
        # src.scripts.context: 查询上下文 (token 预算 + 血缘)
        from src.scripts.context import QueryContext
        ctx = QueryContext()                                                                        # 查询上下文: 令牌预算与审计载体
        assert ctx.truncate(max_records=10) == []  # 空视图而非报错: 每条会话开场都是空历史, 抛异常等于第一次查询就崩
