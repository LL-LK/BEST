# -*- coding: utf-8 -*-
"""TAP 网关测试: VOSI/TAP_SCHEMA、同步/异步查询、配额、Bearer 认证、属主判定。

路由语义还原自 pybest 打包产物 (git 6f00efeb^〔本仓历史已无此对象〕); 传输层用 stdlib TapGateway 直接调
handle(), 除最后一个 socket 冒烟用例外都不监听真实端口。

职责: 守住网关路由与治理语义的回归 —— 每条路径的响应体形态 (VOSI 能力文档 /
  SYNC 查询 / ASYNC 轮询 / ERROR VOTable) 与状态码、配额窗口与 429 出口、Bearer
  令牌的准入判定、以及异步作业的属主隔离。这类回归的特征是"路由分错"或
  "鉴权绕过"时外部完全无感, 只会让 TAP 客户端在生产环境拿到错答案。
所属层次: test/unit 层 (唯一的 socket 冒烟用例用回环端口, 不对外), 对应被测模块
  src/tap/service.py (TapGateway 路由分发/配额/认证/属主判定), 协作件是
  src/tap/executor.py (ADQL plan -> 协议参数) 与 src/tap/jobs.py (sqlite 作业存储)。
对外接口: 各类用例按路由切分 —— VOSI/TAP_SCHEMA 查能力文档与表元数据, 同步查询
  查即时 VOTable, 异步查询查提交/轮询/取结果三段, 另有配额、Bearer 认证、
  作业属主与 socket 冒烟各成一类; CONE_QUERY 常量让所有路由问同一个问题。
依赖与数据流: 后端是 _FakeBest 替身 (query() 无视参数原样回吐脚本化行), 因此
  整条链路零网络; 夹具只有 tmp_path, 异步作业的 sqlite 库与结果目录都落在它下面,
  是全文件唯一的写盘面; 断言读的是 handle() 返回的 (状态码, 头, 体) 三元组,
  轮询用单调时钟避免墙钟跳变影响退避判断。
关键契约与不变量: 网关层只认 TapExecutionError, 站点级故障必须包成
  QUERY_STATUS=ERROR 的 VOTable 而非裸 500; 异步作业的下载必须按属主过滤,
  别人的 job_id 拿不到结果; 配额超限走 429 而非静默截断, 让客户端知道要退避。
陷阱与边界: 替身必须"无视参数原样回吐" —— 若替身去校验 radius_arcsec 之类,
  就会把执行器的单位换算 bug 一起遮住, 网关用例便名不副实; 轮询退避用 time.
  monotonic 而非 time.time, 后者在 CI 机器上被 NTP 校时打断会立刻重试风暴。
"""
from __future__ import annotations

# 标准库: 相位轮询用单调时钟、路径拼接、XML 响应断言解析
import time
from pathlib import Path
from xml.etree import ElementTree as ET

# 第三方: pytest 承载测试发现与 tmp_path 结果目录夹具
import pytest

# 本地: 执行器 (ADQL plan -> 协议参数) 与异步作业存储 (sqlite + 结果目录)
from src.tap.executor import TapExecutor
from src.tap.jobs import TapJobStore

# 本地: 被测网关本体 —— 路由分发、配额、认证、属主判定的汇聚点
from src.tap.service import TapGateway

# 模块级常量: 贯穿全文件的锥形 ADQL 查询, 保证各路由用例问的是同一个问题
CONE_QUERY = (  # 全文件共用同一句 ADQL: 各路由可比, 且只有一处需要跟着协议演进改
    "SELECT ra, ps1_rpsf FROM best.ps1 "  # 取两列够验序列化, 又不至于把用例绑死在星表全字段上
    "WHERE CONTAINS(POINT('ICRS', ps1_ra, ps1_dec), CIRCLE('ICRS', 180.0, 30.0, 0.1)) = 1"  # 锥形查询是执行器换算的主战场
)
# 模块级常量: 固定客户端主机地址, 兼作"作业属主"身份 (换地址即换人)
CLIENT_HOST = "10.0.0.1"  # 属主即主机地址: 匿名通道下换地址就等于换身份


class _FakeBest:
    """替身后端: query() 无视参数原样回吐脚本化行, 隔离真实星表 HTTP。"""

    def __init__(self, rows: list[dict] | None = None) -> None:
        """装入脚本化结果行; 不传 rows 时默认回一行 ps1 结果 (见下)。"""
        # 默认回一行 ps1 结果; 调用方传 rows 以构造空结果/多行结果
        self.rows = rows if rows is not None else [  # rows 缺省时给一行 ps1, 让最短用例不必各自造数据
            {"ps1_ra": "180.0", "ps1_rpsf": "15.5", "ps1_source_id": "PS1-1"}  # 刻意给非空行: 空结果集会走另一条序列化分支
        ]

    def query(self, **_kwargs):
        """无视入参原样回吐脚本化行, 隔离真实星表 HTTP 依赖。"""
        return list(self.rows)  # 无视入参原样回吐: 替身一旦校验参数就会遮住执行器换算 bug


def _gateway(tmp_path: Path, *, with_store=True, token_validator=None, rows=None) -> TapGateway:
    """搭一个结果目录落在 tmp_path 的网关; with_store=False 专测"无作业存储"分支。"""
    executor = TapExecutor(_FakeBest(rows))  # 执行器只认替身, 整条链路因此零网络
    store = None  # 默认无存储, 503 用例要的就是这个中间态
    # with_store 开关是 503 用例的唯一入口: 作业存储缺位必须表现为"功能不可用",
    # 所以要能造出"网关配了但没给存储"这个中间态, 而不是靠 mock 整个 handle
    if with_store:                                                                         # 有 job_store 才测配额分支: 无库时该分支不可达
        store = TapJobStore(str(tmp_path / "tap.db"), str(tmp_path), executor)  # sqlite 库与结果目录同锚 tmp_path, 是全文件唯一写盘面
    return TapGateway(executor, job_store=store, token_validator=token_validator)  # 开关关掉时存储为 None, 503 用例靠这个中间态


def _get(gateway: TapGateway, path: str, *, params=None, headers=None, client_host=CLIENT_HOST):
    """GET 快捷方式: 默认带固定属主地址, 免去每个用例重复三个默认参数。"""
    return gateway.handle("GET", path, params=params or {}, headers=headers or {},
                          client_host=client_host)  # 属主地址给默认值: 属主隔离另有专门用例改它


class TestVosiAndSchema:
    """VOSI 可用性/能力/tables 三个只读端点与未知路由 404。"""

    def test_availability(self, tmp_path):
        """/tap/availability 回 available=true (VOSI 探活的第一个被探测端点)。"""
        response = _get(_gateway(tmp_path), "/tap/availability")  # 探活是最先被探测的端点, 形态错会让客户端直接弃用网关
        root = ET.fromstring(response.body)  # 解析成树再断言, 免得靠子串匹配漏掉结构错误
        # endswith 而非等值比较: VOTable 根标签带命名空间前缀, 那是序列化细节,
        # 这条要守的是"根节点确实是 availability"而不是绑死前缀写法
        assert root.tag.endswith("availability")
        # 探活端点的 available 必须是字符串 "true": 真客户端按文本取, 写成布尔
        # 会让 XML 序列化出错或让客户端读到 None
        assert root.find("available").text == "true"  # available 必须是字符串: 真客户端按文本取, 布尔会让读到 None

    def test_capabilities_advertise_tap_11(self, tmp_path):
        """capabilities 必须宣告标准 ID ivo://ivoa.net/std/TAP 且给出两个 accessURL (sync+async)。"""
        # 显式带 Host 头: accessURL 拼装依赖请求 Host, 缺了会回退成裸主机名,
        # 那正是客户端拿不到可用端点的那类故障
        response = _get(_gateway(tmp_path), "/tap/capabilities", headers={"Host": "127.0.0.1:8000"})
        root = ET.fromstring(response.body)  # 能力文档是嵌套结构, Host 决定 accessURL 怎么拼
        # 两个 accessURL 分别是同步与异步端点; 少一个客户端就只会退化成同步,
        # 查大结果集时被迫在网关侧同步阻塞
        assert root.find(".//capability").get("standardID") == "ivo://ivoa.net/std/TAP"  # 标准 ID 是客户端判别 TAP 协议版本的唯一依据
        assert len(root.findall(".//accessURL")) == 2  # 两个 accessURL 分别是同步与异步, 少一个就只能退化同步

    def test_tables_lists_catalogs_and_columns(self, tmp_path):
        """/tap/tables 要列出星表 (best.ps1) 与列名 (ps1_ra), 客户端据此发现可查字段。"""
        response = _get(_gateway(tmp_path), "/tap/tables")
        root = ET.fromstring(response.body)  # 表元数据端点, 客户端靠它拼 schema 查询
        names = [node.text for node in root.findall(".//table/name")]  # 先收表名, 下面两条断言都建立在它非空的前提上
        # 表名带 best. 前缀: 客户端拿它拼 schema 查询, 前缀丢了就查不到
        assert "best.ps1" in names  # 带 best. 前缀: 客户端拿它拼 schema 查询, 丢了就查不到
        # 列名断言限定在 type='table' 的子树: schema 节点下也有 name, 不限定
        # 会把表名本身也当成列名收进来, 掩盖真正的漏列
        columns = [node.text for node in root.findall(".//table[@type='table']/column/name")]  # 限定 table 子树, 否则表名会被收成列名
        assert "ps1_ra" in columns  # 列名必须能被发现, 漏列等于客户端无从构造查询

    def test_unknown_route_is_404(self, tmp_path):
        """未登记路径一律 404, 不静默落到某个默认处理器上。"""
        assert _get(_gateway(tmp_path), "/tap/nope").status == 404  # 未登记路径一律 404, 不静默落到某个默认处理器上


class TestSyncQuery:
    """同步查询路由: GET/POST、参数名大小写、错误 VOTable、MAXREC 语义。"""

    def test_sync_get_returns_csv(self, tmp_path):
        """GET 带 REQUEST=doQuery/LANG=ADQL/FORMAT=csv 要回 200 且 media_type 为 text/csv。"""
        response = _get(_gateway(tmp_path), "/tap/sync", params={  # 同步查询的四个参数一次给全, 缺一个就走不到执行器
            "REQUEST": "doQuery", "LANG": "ADQL", "QUERY": CONE_QUERY, "FORMAT": "csv",  # MAXREC 不给即无限制, 这里要的是默认全量路径
        })
        assert response.status == 200  # 状态码先过: 类型错时的 200 仍会被下面那条抓住
        # media_type 单独断: 状态码 200 但类型错成 application/json 时, 按扩展名
        # 判断的客户端会拿到 .csv 后缀却装着 JSON, 是最难排查的一类错配
        assert response.media_type == "text/csv"  # media_type 单独断: 按扩展名判断的客户端会拿到 .csv 装着 JSON
        assert b"ps1_ra" in response.body  # 表头名在场才证明数据行真的落了盘

    def test_sync_post_accepts_lowercase_param_names(self, tmp_path):
        """POST 的参数名大小写不敏感 (lang/query/request), 容忍不规范客户端。"""
        response = _gateway(tmp_path).handle(  # POST 入口: 参数名大小写不敏感是这条要守的东西
            "POST", "/tap/sync",  # 路径与 GET 同一条, 证明两入口共用同一路由
            params={"lang": "adql", "query": CONE_QUERY, "request": "doquery", "format": "csv"},  # 参数名全用小写: 故意违反规范, 看网关是否容忍
            headers={}, client_host=CLIENT_HOST,  # 空头 + 固定属主: 排除鉴权因素干扰参数大小写这条
        )
        assert response.status == 200  # 参数名大小写不敏感, 容忍不规范客户端
        assert b"ps1_ra" in response.body  # 与 GET 同一条数据回吐, 证明两条入口共用同一执行器

    def test_unsupported_adql_returns_error_votable(self, tmp_path):
        """白名单外 ADQL 要回 400 + QUERY_STATUS=ERROR 的 VOTable, 而不是裸 500 或空响应。"""
        response = _get(_gateway(tmp_path), "/tap/sync", params={
            "QUERY": "SELECT ra FROM best.ps1 JOIN best.stripe82 ON 1 = 1",  # 白名单外语句: 引用了两张表, 执行器应当直接拒
        })
        assert response.status == 400  # 错误体必须是 ERROR VOTable: 裸 500 客户端无从解析
        assert b'QUERY_STATUS" value="ERROR"' in response.body  # 点明状态字段的值, 客户端靠它区分成功与失败

    def test_wrong_lang_rejected(self, tmp_path):
        """LANG=SQL 要拒, 且错误体里要点明只有 LANG=ADQL 可用 (客户端自愈线索)。"""
        response = _get(_gateway(tmp_path), "/tap/sync",  # 只给 LANG 不给别的, 制造"语言不对"这一种失败
                        params={"QUERY": CONE_QUERY, "LANG": "SQL"})  # SQL 是白名单外语言, 错误体须点名唯一可用语言
        assert response.status == 400  # 错误体要给出可自愈线索, 只回状态码用户无从下手
        assert b"LANG=ADQL" in response.body  # 错误体要写明可用语言, 这是客户端自愈的唯一线索

    def test_missing_query_rejected(self, tmp_path):
        """缺 QUERY 参数回 400, 不能拿空查询去打后端。"""
        response = _get(_gateway(tmp_path), "/tap/sync", params={"LANG": "ADQL"})  # 缺 QUERY 直接拒, 不拿空查询去打后端
        assert response.status == 400  # 缺 QUERY 必须 400, 不能拿空查询去打后端

    def test_overflow_header_set_when_truncated(self, tmp_path):
        """MAXREC=3 截断 10 行结果时, 响应必须带 X-TAP-Overflow: true 告知客户端还有数据。"""
        # 截断用 MAXREC=3 对 10 行: 差得足够大才让"探针行"判定有对象可比,
        # 若两者接近, 探针多取的一行会落在边界上让溢出位真假难辨
        rows = [{"ps1_ra": str(i), "ps1_rpsf": "15.0"} for i in range(10)]  # 十行数据配 MAXREC=3, 差得够大才让溢出位真假可辨
        response = _get(_gateway(tmp_path, rows=rows), "/tap/sync",  # 注入十行结果, 让 MAXREC=3 真正触发截断
                        params={"QUERY": CONE_QUERY, "MAXREC": "3", "FORMAT": "csv"})  # MAXREC=3 配十行: 差得够大才让溢出位真假可辨
        assert response.status == 200  # 截断仍回 200: 溢出是正常信号不是错误
        # 头必须叫 X-TAP-Overflow 且值为字符串 "true": 少这个头客户端会把
        # 截断结果当全集, 用户以为天区里只有 3 个源
        assert response.headers.get("X-TAP-Overflow") == "true"  # 溢出头名与值都要对, 少它客户端会把 3 行当全集

    def test_maxrec_zero_is_metadata_only(self, tmp_path):
        """MAXREC=0 是"只要元数据": 只回表头行, 不取任何数据行。"""
        response = _get(_gateway(tmp_path), "/tap/sync",  # MAXREC=0 走的是只读元数据分支, 与截断分支不同
                        params={"QUERY": CONE_QUERY, "MAXREC": "0", "FORMAT": "csv"})  # 零值即"只要元数据", 与 MAXREC=3 的截断语义相反
        assert response.status == 200  # MAXREC=0 是只读元数据的约定, 语义被改就会多吐数据行
        # 断整个响应体等于那一行表头: 多一行数据说明 MAXREC=0 被当成了无限制,
        # 少一行则客户端连可用列名都拿不到, 两种都要挡住
        assert response.body.decode().splitlines() == ["ps1_ra,ps1_rpsf"]  # 整份响应体等值: 多一行说明被当成无限制, 少一行则列名都拿不到


class TestBearerAuth:
    """Bearer 认证: 无效/畸形/缺失三种失败都要 401, 不得降级成匿名放行。"""

    def test_invalid_bearer_is_401_not_anonymous_downgrade(self, tmp_path):
        """token 校验器不认的 Bearer 必须 401, 不能静默按匿名处理。

        回归锚点: 静默降级会让配额与属主判定全部错位 —— 已登录用户的超额请求会被
        当成新匿名请求放行。
        """
        gateway = _gateway(tmp_path, token_validator=lambda token: token == "good")  # 校验器只认 good, 用来制造已认证与未认证两种配额通道
        response = _get(gateway, "/tap/sync", params={"QUERY": CONE_QUERY},  # 带一个校验器不认的令牌, 制造已认证通道被拒的场景
                        headers={"Authorization": "Bearer bad"})  # 令牌值故意取 bad: 校验器只认 good
        assert response.status == 401  # 401 而非匿名放行: 静默降级会让配额与属主判定全部错位

    def test_malformed_bearer_is_401(self, tmp_path):
        """Authorization 头不是 Bearer 方案 (如 Basic) 一律 401, 不做方案协商。"""
        gateway = _gateway(tmp_path, token_validator=lambda token: True)  # 校验器恒真, 制造\通过了鉴权但方案不对\这一种失败
        response = _get(gateway, "/tap/sync", params={"QUERY": CONE_QUERY},  # 校验器恒真, 失败原因就只剩"方案不是 Bearer"这一条
                        headers={"Authorization": "Basic abc"})  # Basic 方案: 不做方案协商, 非 Bearer 一律拒
        assert response.status == 401  # 方案不协商: 非 Bearer 一律拒, 不做降级解释

    def test_valid_bearer_gets_authenticated_quota(self, tmp_path):
        """校验器放行的 Bearer 走已认证配额通道, 正常回 200。"""
        gateway = _gateway(tmp_path, token_validator=lambda token: token == "good")  # 同一校验器放行 good, 与上面两条构成正反对照
        response = _get(gateway, "/tap/sync", params={"QUERY": CONE_QUERY, "FORMAT": "csv"},  # 同一个校验器 + 合法令牌, 与上面两条构成正反对照
                        headers={"Authorization": "Bearer good"})  # 令牌取 good: 校验器认它, 期望走已认证通道
        assert response.status == 200  # 已认证通道正常回 200, 挡住把配额门写成恒拒绝的实现

    def test_bearer_without_validator_is_401(self, tmp_path):
        """网关未配置 token 校验器时, 任何 Bearer 都 401 (不配置=不开放认证通道)。"""
        response = _get(_gateway(tmp_path), "/tap/sync", params={"QUERY": CONE_QUERY},  # 不配校验器等于不开放认证通道, 任何 Bearer 都得拒
                        headers={"Authorization": "Bearer anything"})  # 任何令牌都该被拒: 不配校验器就不开放认证通道
        assert response.status == 401  # 未配置校验器时不得放行, 否则等于默认开了一个后门


class TestAsyncUws:
    """UWS 异步作业: 创建/相位轮询/取结果/Range 206 与 416/属主 403/删除/配额 429。"""

    def _create(self, gateway, **kw):
        """POST /tap/async 建作业并直接置 PHASE=RUN (不等 PENDING)。"""
        return gateway.handle(  # 置 PHASE=RUN 跳过 PENDING: 轮询用例不必等排队态
            "POST", "/tap/async",  # 异步建作业的路径, 与同步入口完全分开
            params={"QUERY": CONE_QUERY, "FORMAT": "csv", "PHASE": "RUN", **kw},  # 建作业参数一次给全, 下面的轮询与取结果都靠这个 job_id
            headers={}, client_host=CLIENT_HOST,  # 固定属主: 后面所有轮询与取结果都靠这个身份
        )

    def _wait_phase(self, gateway, job_id, timeout=10.0):
        """轮询 /phase 直到终态 (COMPLETED/ERROR/ABORTED), 超时返回 "TIMEOUT" 让断言失败。"""
        # 用 time.monotonic 而非 time.time: 墙钟被 NTP 校时打断会让 deadline
        # 突然前移或后移, 前移就跳过轮询直接 TIMEOUT, 后移则让故障用例挂满 10s
        deadline = time.monotonic() + timeout  # deadline 用单调时钟, 墙钟被校时会跳过轮询或拖满全程
        while time.monotonic() < deadline:  # 轮询直到终态或超时, 三种终态任一都算收敛
            response = gateway.handle("GET", f"/tap/async/{job_id}/phase", params={}, headers={},  # 相位轮询是纯文本响应, 不用解析 XML
                                      client_host=CLIENT_HOST)  # 属主保持一致: 否则会先撞 403 而测不到相位
            if response.body.decode() in ("COMPLETED", "ERROR", "ABORTED"):  # 三种终态任一都算收敛, 继续轮询只会空转
                return response.body.decode()
            # 50ms 间隔是替身驱动的作业几乎瞬时完成, 睡太长纯属浪费; 太短则在
            # 真实负载下变成忙等, 两者取中间
            time.sleep(0.05)
        # 返回哨兵串而不是 raise: 让调用方的等值断言自然红, 失败信息里
        # "TIMEOUT" 比一长串 traceback 更容易看出是相位没转过来
        return "TIMEOUT"

    def test_create_run_complete_and_fetch_result(self, tmp_path):
        """UWS 主链路: 建作业回 303 + Location, 相位转 COMPLETED, 结果可读且带 SHA256 校验头。

        回归锚点: 303 Location 里的 job id 是客户端唯一句柄; 缺 X-Checksum-SHA256 会
        让断点续传无法校验完整性。
        """
        gateway = _gateway(tmp_path)  # 建带存储的网关: 异步路径要求作业存储在场
        created = self._create(gateway)  # 建作业并置 PHASE=RUN, 跳过排队态让用例更快
        assert created.status == 303  # 303 是 UWS 规定的 See Other, 换成 200 就断了标准客户端
        job_id = created.headers["Location"].rsplit("/", 1)[-1]  # job id 从 Location 末段切出, 后面所有请求都靠它

        assert self._wait_phase(gateway, job_id) == "COMPLETED"  # 等相位收敛是取结果的前置, 未完成时取会得到 409

        # 读作业 XML: phase 必须已是 COMPLETED (而非仍显示 PENDING)
        job_xml = gateway.handle("GET", f"/tap/async/{job_id}", params={}, headers={},  # 作业元数据 XML: 相位字段是状态机的对外投影
                                 client_host=CLIENT_HOST)  # 属主不变: 元数据读取同样受属主判定约束
        root = ET.fromstring(job_xml.body)  # 解析后再查 phase 字段, 不用子串匹配
        assert root.find("phase").text == "COMPLETED"  # 相位必须已是 COMPLETED, 仍显示 PENDING 说明状态机没推进

        # 取结果: 200 + 数据体 + 完整性校验头
        result = gateway.handle("GET", f"/tap/async/{job_id}/results/result", params={},  # 取结果走独立路径, 与读元数据不是同一个端点
                                headers={}, client_host=CLIENT_HOST)  # 空头 + 同属主: 这条不测 Range, 只测基本可用性
        assert result.status == 200  # 取结果先过状态码: 未完成会先撞 409
        assert b"ps1_ra" in result.body  # 数据体含列名, 证明这确实是 CSV 而非空壳
        assert result.headers["X-Checksum-SHA256"]  # 校验头非空即可: 断点续传靠它验完整性, 缺头等于无从校验

    def test_result_range_request_returns_206(self, tmp_path):
        """Range: bytes=0-9 要回 206 且只给 10 字节, Content-Range 带总长度。"""
        gateway = _gateway(tmp_path)  # 另起网关: 作业库与前一例隔离, 避免 id 撞车
        job_id = self._create(gateway).headers["Location"].rsplit("/", 1)[-1]  # job id 仍从 Location 末段切, 这是客户端的唯一句柄
        assert self._wait_phase(gateway, job_id) == "COMPLETED"  # Range 用例同样要先收敛相位, 未完成时取结果会先撞 409
        response = gateway.handle("GET", f"/tap/async/{job_id}/results/result", params={},  # Range 请求头是这条用例的全部变量, 其余照常
                                  headers={"Range": "bytes=0-9"}, client_host=CLIENT_HOST)  # 取前 10 字节: 范围要短到能精确验证长度
        assert response.status == 206  # 206 是部分内容的唯一合法状态码
        # 长度与 Content-Range 三者一起断: 状态码 206 而长度不对, 等于给了
        # 客户端一段名不副实的区间, 续传拼出来的文件会在拼接处错位
        assert len(response.body) == 10  # 长度必须精确等于 10, 状态码对而长度错等于给了错区间
        assert response.headers["Content-Range"].startswith("bytes 0-9/")  # Content-Range 要带总长度, 客户端据此判断还有多少可拉

    def test_invalid_range_returns_416(self, tmp_path):
        """语法非法的 Range (bytes=abc) 要回 416 并带 Content-Range: bytes */total 形态。

        回归锚点: 非法 Range 必须回 416 — 当成普通请求回 200 全量, 客户端续传逻辑
        随即错乱。
        """
        gateway = _gateway(tmp_path)  # 另起网关: 每例独立存储, 断点与相位互不污染
        job_id = self._create(gateway).headers["Location"].rsplit("/", 1)[-1]  # 先建作业拿 id, 再对它发非法 Range
        assert self._wait_phase(gateway, job_id) == "COMPLETED"  # 非法 Range 用例同样要先收敛相位, 否则会先撞 409
        response = gateway.handle("GET", f"/tap/async/{job_id}/results/result", params={},  # 请求路径与合法 Range 用例完全相同, 只换头
                                  headers={"Range": "bytes=abc"}, client_host=CLIENT_HOST)  # bytes=abc 语法非法: 必须走 416 而不是当普通请求
        assert response.status == 416  # 416 而非 200 全量: 客户端续传逻辑据此改走别的分支

    def test_job_belongs_to_another_principal_is_403(self, tmp_path):
        """换客户端主机地址读别人作业要 403 (属主隔离), 而不是 404 或 200。"""
        gateway = _gateway(tmp_path)  # 另起网关: 属主隔离这条要独立的存储与作业
        job_id = self._create(gateway).headers["Location"].rsplit("/", 1)[-1]  # 用属主自己的身份建作业, 稍后再换身份去读
        # 换 client_host 即换身份 (匿名主体以主机地址为准), 凭同一个 job_id
        # 读别人的作业必须被拒; 用别的地址而不换 token 是因为匿名通道没有 token
        response = gateway.handle("GET", f"/tap/async/{job_id}", params={}, headers={},  # 换 client_host 即换身份, 凭同一个 job_id 去读
                                  client_host="10.9.9.9")  # 匿名通道下换地址就是换人, 没有 token 可换
        # 403 而非 404: 404 会把"存在但无权"与"不存在"混成同一答案, 客户端
        # 便无法区分该重试还是该放弃
        assert response.status == 403  # 403 而非 404: 无权与不存在必须给出不同答案

    def test_authenticated_owner_follows_token_not_ip(self, tmp_path):
        """AF2-05: 认证态的属主是令牌身份, 与出口地址无关 (换 IP 仍是同一人)。

        这条守的是"同一用户换出口读不回自己的作业"那半: 修前 owner_key 是
        ``auth:{client_host}``, 于是多网卡 / 移动出口 / 容器 NAT 轮换都会把
        自己判成别人, 作业建完即失联。
        """
        gateway = _gateway(tmp_path, token_validator=lambda tok: tok == "tok-a")  # 只认一个令牌: 单主体即可验换 IP 不换人
        headers = {"Authorization": "Bearer tok-a"}  # 凭据全程不变
        created = gateway.handle("POST", "/tap/async",
                                 params={"QUERY": CONE_QUERY, "FORMAT": "csv"},
                                 headers=headers, client_host=CLIENT_HOST)  # 从第一条出口地址建作业
        job_id = created.headers["Location"].rsplit("/", 1)[-1]  # id 切自 Location, 客户端拿它轮询
        response = gateway.handle("GET", f"/tap/async/{job_id}", params={}, headers=headers,
                                  client_host="203.0.113.7")  # 换一条完全不同的出口地址, 令牌不变
        assert response.status == 200  # 200 才是对的: 同一个人换了出口, 不该被自己挡住

    def test_two_tokens_same_ip_are_different_owners(self, tmp_path):
        """AF2-05: 同一出口 IP 上的两个合法令牌是两个属主, 不能互相读作业。

        这是缺陷的越权面那一半: 修前 owner_key 只由 IP 拼成, 于是 NAT/代理/
        同机房里的**不同用户**被判成同属主, 任一方都能读走对方的查询结果。
        """
        gateway = _gateway(tmp_path, token_validator=lambda tok: tok in ("tok-a", "tok-b"))  # 两个都合法的主体
        created = gateway.handle("POST", "/tap/async",
                                 params={"QUERY": CONE_QUERY, "FORMAT": "csv"},
                                 headers={"Authorization": "Bearer tok-a"}, client_host=CLIENT_HOST)  # A 用自己的令牌建作业
        job_id = created.headers["Location"].rsplit("/", 1)[-1]  # id 切自 Location
        response = gateway.handle("GET", f"/tap/async/{job_id}", params={},
                                  headers={"Authorization": "Bearer tok-b"}, client_host=CLIENT_HOST)  # B 用**自己合法的**令牌、同一条 IP 来读
        assert response.status == 403  # 403: 地址相同不等于同一人, 越权面就此关上

    def test_anonymous_without_client_address_is_rejected(self, tmp_path):
        """AF2-05 fail-closed: 匿名请求拿不到客户端地址时拒建作业, 不并公共桶。

        缺省哨兵 ``unknown`` 若被当成一个真地址, 所有无 socket 来源的调用方会
        共用 ``anonymous:unknown`` 这一个属主 —— 互相读到对方作业。判据是
        "显式失败", 不是"换成别的猜法"。
        """
        gateway = _gateway(tmp_path)  # 匿名通道: 无 token_validator
        created = gateway.handle("POST", "/tap/async",
                                 params={"QUERY": CONE_QUERY, "FORMAT": "csv"},
                                 headers={}, client_host="unknown")  # 缺省哨兵 = 没有地址
        assert created.status == 403  # 403 而非 303: 属主不可判定就不建单, 作业不会被落进公共桶
        # 对照: 给出真实地址的匿名建单照旧放行 (本条不是把匿名异步面整个关掉)
        ok = gateway.handle("POST", "/tap/async",
                            params={"QUERY": CONE_QUERY, "FORMAT": "csv"},
                            headers={}, client_host=CLIENT_HOST)  # 有地址 = 有判据
        assert ok.status == 303  # 303: 匿名作业保留, 隔离面只收紧到"没有身份"这一支

    def test_owner_key_is_not_raw_token(self, tmp_path):
        """属主键里只允许出现令牌摘要, 不得落令牌原文 (作业行会进 sqlite)。"""
        # 本地: 摘要折法与网关同源 (src/tap/uws_service.py)
        from src.tap.uws_service import principal_from_token

        gateway = _gateway(tmp_path, token_validator=lambda tok: tok == "tok-secret-value")  # 令牌取一个可辨识的字面量
        created = gateway.handle("POST", "/tap/async",
                                 params={"QUERY": CONE_QUERY, "FORMAT": "csv"},
                                 headers={"Authorization": "Bearer tok-secret-value"}, client_host=CLIENT_HOST)
        job_id = created.headers["Location"].rsplit("/", 1)[-1]  # id 切自 Location
        stored = gateway.job_store.get_job(job_id)["owner_key"]  # 直接读存储层: 只验落库形态, 不靠 HTTP 回显
        assert "tok-secret-value" not in stored  # 凭据原文绝不能出现在属主键里
        assert stored == f"auth:{principal_from_token('tok-secret-value')}"  # 键由摘要构成, 且与折法同源

    def test_unknown_job_is_404(self, tmp_path):
        """不存在的 job id 回 404。"""
        response = _gateway(tmp_path).handle("GET", "/tap/async/nope", params={}, headers={},  # 不存在的 id 必须 404, 不能落到某个默认处理器
                                             client_host=CLIENT_HOST)  # 属主保持默认, 排除 403 干扰这条
        assert response.status == 404  # 404 证明路由认得出"作业不存在"这态态态状态

    def test_result_before_completion_is_409(self, tmp_path):
        """作业未完成就取结果要 409 (冲突), 不能回半个文件让客户端误当完整结果。"""
        gateway = _gateway(tmp_path)  # 建带存储的网关: 409 用例需要真作业存在
        created = gateway.handle("POST", "/tap/async",  # 这里不置 PHASE=RUN, 作业停在 PENDING
                                 params={"QUERY": CONE_QUERY, "FORMAT": "csv"},  # 建作业参数: 故意不传 PHASE, 留着未完成态
                                 headers={}, client_host=CLIENT_HOST)  # 空头 + 同属主: 只让"未完成"这一个变量起作用
        job_id = created.headers["Location"].rsplit("/", 1)[-1]  # id 从 Location 切出: 客户端拿它取结果
        response = gateway.handle("GET", f"/tap/async/{job_id}/results/result", params={},  # 作业未完成就取结果, 这正是 409 的触发条件
                                  headers={}, client_host=CLIENT_HOST)  # 无 Range 头: 排除部分内容分支的干扰
        assert response.status == 409  # 409 表示状态冲突, 回半个文件会被客户端误当完整结果

    def test_abort_phase(self, tmp_path):
        """POST PHASE=ABORT 后相位变 ABORTED (UWS 取消语义)。"""
        gateway = _gateway(tmp_path)  # 另起网关: 取消语义要独立的作业
        created = gateway.handle("POST", "/tap/async",  # 建作业后不置相位, 保留可操作状态
                                 params={"QUERY": CONE_QUERY, "FORMAT": "csv"},  # 建单参数: 只要 QUERY 与 FORMAT 就够
                                 headers={}, client_host=CLIENT_HOST)  # 空头: 本例只验取消语义, 不掺鉴权
        job_id = created.headers["Location"].rsplit("/", 1)[-1]  # id 切自 Location: 取消动作要打在真作业上
        response = gateway.handle("POST", f"/tap/async/{job_id}/phase",  # 相位端点用 POST 改状态, 这是 UWS 的取消入口
                                  params={"PHASE": "ABORT"}, headers={}, client_host=CLIENT_HOST)  # ABORT 是 UWS 规定的取消相位, 写别的会被当成非法
        assert response.status == 200  # 取消本身回 200: 失败该走 4xx 而不是静默不改
        phase = gateway.handle("GET", f"/tap/async/{job_id}/phase", params={}, headers={},  # 再读一次相位: 取消要真落到存储里才算数
                               client_host=CLIENT_HOST)  # 同属主读取: 换身份只会多出一条无关的 403
        assert phase.body == b"ABORTED"  # 必须精确等于 ABORTED: 相位没推进就是取消没生效

    def test_delete_job(self, tmp_path):
        """DELETE 作业回 303, 之后再读同一 id 必须 404 (删除要真生效)。"""
        gateway = _gateway(tmp_path)  # 另起网关: 删除用例要独立作业
        created = gateway.handle("POST", "/tap/async",  # 建作业后取 id, 删除动作才能打在真对象上
                                 params={"QUERY": CONE_QUERY, "FORMAT": "csv"},  # 建单参数: 与取消用例同构, 只换动作
                                 headers={}, client_host=CLIENT_HOST)  # 空头 + 同属主: 排除鉴权把 403 混进来
        job_id = created.headers["Location"].rsplit("/", 1)[-1]  # id 切自 Location: DELETE 的目标必须是真的
        deleted = gateway.handle("DELETE", f"/tap/async/{job_id}", params={}, headers={},  # DELETE 走 UWS 规定的方法, 不是 POST 加标志
                                 client_host=CLIENT_HOST)  # 同属主才有权删: 换身份会得到 403 而非 303
        assert deleted.status == 303  # 303 是 UWS 删除的响应约定, 换成 200 就断了标准客户端
        gone = gateway.handle("GET", f"/tap/async/{job_id}", params={}, headers={},  # 删除后再读同一 id, 这是"删真生效"的唯一证据
                              client_host=CLIENT_HOST)  # 同一个 id: 若被重建则这条断言就失去意义
        assert gone.status == 404  # 必须 404: 删除只删存储, 不该留可读残影

    def test_async_without_store_is_503(self, tmp_path):
        """网关没配作业存储时, /tap/async 要回 503 (功能不可用) 而不是 500。"""
        response = _gateway(tmp_path, with_store=False).handle(  # with_store=False 造出"配了网关但没给存储"的中间态
            "POST", "/tap/async", params={"QUERY": CONE_QUERY}, headers={},  # 异步端点在无存储时必须自答 503, 而不是崩成 500
            client_host=CLIENT_HOST)  # 同属主: 排除鉴权把 503 换成 401
        assert response.status == 503  # 503 表达"功能不可用", 与 500 的"网关自己坏了"是两回事

    def test_quota_error_is_429(self, tmp_path):
        """匿名待处理作业数打到上限后, 第二个建作业请求要 429 (限流)。"""
        gateway = _gateway(tmp_path)  # 建带存储的网关: 配额用例需要真能建作业
        # 直接把匿名待处理计数顶到上限, 免去真跑满作业: 配额判据读的是这个
        # 计数, 手动置位与真跑满走的是同一条判断路径, 且不占 CI 时间
        gateway.job_store.anonymous_pending = 1                                                 # 把匿名在途上限压到 1, 才能确定地触发限流拒绝
        first = gateway.handle("POST", "/tap/async",  # 第一条建作业请求: 它必须仍被放行
                               params={"QUERY": CONE_QUERY, "FORMAT": "csv"},  # 带 FORMAT: 与后续那条逐字相同, 只看状态码差异
                               headers={}, client_host=CLIENT_HOST)  # 同属主: 两次请求要落在同一配额桶里
        # 第一条仍要 303: 配额判据是"达到上限才拒", 不是"有待处理作业就拒",
        # 断掉这条就看不出上限语义被写成了 >= 还是 >
        assert first.status == 303
        second = gateway.handle("POST", "/tap/async",  # 第二条建作业请求: 匿名待处理数已达上限
                                params={"QUERY": CONE_QUERY, "FORMAT": "csv"},  # 参数与第一条逐字相同, 差异只应来自配额计数
                                headers={}, client_host=CLIENT_HOST)  # 同属主: 换了身份就换了配额桶, 这条就测不到了
        assert second.status == 429  # 429 而非静默截断: 客户端要靠它知道该退避

    def test_socket_level_smoke(self, tmp_path):
        """一次真实 socket 往返: 证明 stdlib TapHTTPServer 到网关的接线真能跑。"""
        from src.tap.service import TapHTTPServer

        # 绑 ephemeral 端口起服务, 测完即关 (不需要外部端口规划)
        server = TapHTTPServer(("127.0.0.1", 0), _gateway(tmp_path))
        thread = None  # 先置空: finally 里靠它判断要不要 join
        try:
            # threading: 并发起服务线程, 验证端口绑定与关闭
            import threading
            thread = threading.Thread(target=server.serve_forever, daemon=True)  # 守护线程: 服务线程不该挡住进程退出
            thread.start()  # 起服务线程: 不起就没有可打的端口
            # urllib.request: 标准库 HTTP 客户端 (零依赖探路)
            import urllib.request
            # 端口取 server_address[1] (内核分配的 ephemeral 端口): 并行跑测试时
            # 不会撞端口, 写死 8000 会在占用时直接 bind 失败
            with urllib.request.urlopen(  # 走真实 HTTP 客户端: 这是唯一验证接线的一例
                f"http://127.0.0.1:{server.server_address[1]}/tap/availability", timeout=10  # 端口取内核分配的 ephemeral 值, 并行跑不会撞
            ) as resp:  # 用上下文管理器: 读完响应体才谈状态码
                body = resp.read()  # 读完再断言: 流没读完就断会拿到半截内容
            assert resp.status == 200  # 200 证明回环这条链路真的通了
            assert b"availability" in body  # 响应体含 availability: 光看状态码不足以证明路由对
        finally:
            # 三个动作缺一不可: shutdown 停事件循环, server_close 释放端口,
            # join 回收线程; 只做前者会让端口与线程在同进程内残留
            server.shutdown()
            server.server_close()  # 释放端口: 只调 shutdown 端口还占着, 换例就 bind 失败
            if thread is not None:  # 线程可能压根没起来, 判一下再 join
                thread.join(timeout=5)  # 回收线程: 残留线程会让同进程内后续用例行为不确定


class TestJobStoreConnectionLifecycle:
    """P2-11: 数据库连接必须即开即关 (建连即弃让句柄累积, close() 空转等于没关)。"""

    def test_db_helper_closes_connection_on_success(self, tmp_path, monkeypatch):
        """_db() 退出时连接必须关闭 (成功路径先提交再关)。

        复过的现: ``with self._lock, self._connect() as conn:`` —
        ``sqlite3.Connection.__exit__`` 只提交事务、不关闭连接, 每作业
        4~6 次建连即弃, 句柄累积, ``database is locked`` 概率上升。
        关闭判定: sqlite3 连接关闭后再使用抛 ProgrammingError。
        """
        # 标准库: sqlite3 — 连接关闭的判定依据 (关闭后再用即抛 ProgrammingError)
        import sqlite3

        # 本地: jobs 模块 — 在模块命名空间打桩 sqlite3.connect, 记录连接生命周期
        import src.tap.jobs as jobs_module

        store = TapJobStore(str(tmp_path / "tap.db"), str(tmp_path),  # 建作业存储, 库与结果目录都锚在 tmp_path
                            TapExecutor(_FakeBest()))  # 执行器仍用替身: 这条只关心连接生命周期
        created: list[sqlite3.Connection] = []  # 收集每一条被建出的连接, 关闭判定要逐个查
        real_connect = jobs_module.sqlite3.connect  # 先存真实现: 打桩之后仍要真连, 否则测不到关闭

        def tracking_connect(*args, **kwargs):
            """替身 sqlite3.connect: 真连 + 记录 (关闭判定靠"再用即抛")。"""
            conn = real_connect(*args, **kwargs)  # 真建连接: 只记账不真连就测不出"关闭后再用即抛"
            created.append(conn)  # 每建一条就记一条: 漏记就等于这条连接没被验证
            return conn

        monkeypatch.setattr(jobs_module.sqlite3, "connect", tracking_connect)
        with store._db() as conn:  # 上下文管理器退出点正是连接该关的地方
            conn.execute("SELECT 1")  # 随便跑一条语句: 让连接真的被用过才有"用过即抛"
        assert created, "一次连接都没建 — _db() 接线断了"
        for conn in created:  # 逐条验关闭: 只查最后一条会漏掉中途建的那些
            with pytest.raises(sqlite3.ProgrammingError):  # 关闭后再用抛 ProgrammingError 是 sqlite 的既定行为
                conn.execute("SELECT 1")  # 关闭后不可用, 不可用即已关闭

    def test_writes_survive_the_connection_close(self, tmp_path):
        """写入必须真提交 (关闭未提交连接 = 回滚, 建单后会查不到作业)。

        复过的现 (修复试错中实测): 只 close 不 commit 时 create_job 的
        INSERT 随连接关闭回滚, get_job 返回 None, 建单链路 KeyError 'id'。
        """
        store = TapJobStore(str(tmp_path / "tap.db"), str(tmp_path),  # 另建一个存储: 避免与上一例的连接状态互相影响
                            TapExecutor(_FakeBest()))  # 同样用替身执行器: 这条只验提交是否落盘
        job = store.create_job(CONE_QUERY, "csv", 100, owner_key="k",  # 建单: 这一步的写入若没提交, 后两条断言会一起红
                               authenticated=False)  # 显式给属主与认证态: 两列都有值才验得出提交
        # 后续操作换新连接读: 提交过的行必须在 (回滚过就查不到)
        assert store.get_job(job["id"]) is not None  # 换新连接读回: 提交过的行必须在, 回滚过就查不到
        assert store.get_job(job["id"])["phase"] == "PENDING"  # 相位必须是 PENDING: 说明读到的是刚写入的那一行
        store.close()  # 收尾关库: 不关会在同进程内留下悬空句柄
