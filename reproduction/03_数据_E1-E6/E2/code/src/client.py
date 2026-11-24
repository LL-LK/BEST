"""src.client — BEST database REST API client.

能力边界: BestClient (两阶段异步 REST: POST 表单→sqlid→分页 GET) 的唯一生产客户端; BestAuth (Django session+CSRF) 已迁至 src.auth.session, 本模块 re-export 保留公开导入路径 (既有 ``from src.client import BestAuth`` 不受影响; 认证态与客户端态是同一份 Django 会话, 接线见 BestClient.__init__ 的 export_session() 显式移交)。边界: 表单键集/表头判定/计数解析全部委托 src.protocol (权威协议层, Q-01~05); 不做清洗/匹配 (越权即拒, 转 canonical)。
白盒锚点: references/ALGORITHM-SPEC.md §1/§2; contracts/input.contract.yaml。

【权威学术来源锚定】
  - NADC 中国虚拟天文台 (China-VO) BEST 数据库 REST API 规范 (2023): 两阶段查询协议 (POST /data/best/{catalog}/q → GET /data/best/sqlid/{sqlid}), 公式定位: 接口规范全文（§查询会话/分页/codes）。
    规范引用（无 DOI）: https://nadc.china-vo.org/data/best 官方文档, 关联数据集 DOI 见 docs/plans/doi_truth_registry.json (该文件在本仓不存在,
        2026-10-03 实测)。
  - 开源依赖: requests (Apache-2.0), urllib3 (MIT)。
Rule 9 状态: [VERIFIED_ALGO]（标准基准算法; 物理可解释输出, 无伪概率打分）。

两阶段查询协议 (全部请求都走 requests.Session, 失败语义见各方法):
  阶段 1 (POST): POST /data/best/{catalog}/q, output.fmt=html — 在服务端
     创建 SQL 查询会话并回传 sqlid (这是唯一能取回 sqlid 的提交形态)。
  阶段 2 (GET): GET /data/best/sqlid/{sqlid}?output.fmt=...&rows=N&page=P —
     按会话内约束分页拉取数据。
  计数 (GET): GET /data/best/sqlid/{numeric_id}/getcount → {"total": N} —
     服务端真实总行数 (getcount 只认 sqlid 的数字部分, 如 s3839 → 3839)。

支持 12 个可查询星表 (裸 id; ``calib/`` 等导航组会被 /q 路由拒绝): ps1,
stripe82, gaia_dr3_18, jplus_dr3, smss_dr4, landolt, uss_dr1, splus_dr4,
scr_galah, scr_lamost, xpsp, dr3xpcorr。
"""

from __future__ import annotations

# 标准库: 日志 / 限流锁 / 节流等待 / 回调类型标注 (obj 参数 URL 编码已随
# 名称解析面迁至 client_resolve, 本模块不再拼 Sesame 查询串)
import logging  # 模块级 logger 按 __name__ 派生: 失败走日志, 不污染返回信封
import threading  # 限流时钟的互斥锁: 线程池并发下读-睡-写必须原子
import time  # 节流与探测超时的唯一时间源, 离线回放时可整体替换
from typing import Any, Callable, Optional  # 公开签名的类型词表: 运行期无依赖, 纯标注

# 第三方: requests 会话 + HTTPAdapter + urllib3 Retry (唯一重试层, 见 BestClient.__init__)
import requests  # 唯一出网栈: 离线回放靠替换这一层, 不混用 urllib 直连
from requests.adapters import HTTPAdapter  # 把 urllib3 Retry 挂上 session, 全类重试只有这一层
from urllib3.util.retry import Retry  # 白名单收窄到 GET 是刻意的: POST 重试会泄漏 sqlid 会话

# 本地: 认证态 (Django session + CSRF) 已迁至 src.auth.session — 原共处一案的理由
# "认证态与客户端态是同一份 Django 会话"由该模块的 export_session() 显式移交
# (见 BestClient.__init__); 此处 re-export 保留公开导入路径, 既有
# ``from src.client import BestAuth`` 一类调用不受影响 (src.__init__ /
# src.__main__ 等现有 import 全部不用改)
from src.auth.session import BestAuth  # re-export 保旧导入路径; 认证态经 export_session 移交

# 本地: 会话构造的唯一出口 — 锁 trust_env=False, 防止环境变量改写出网路由 (C2)
from src.http_session import build_session

# 本地: 数据模型 — 查询结果载体 (BestSource/BestQueryResult)、列约束、名称解析结果
from src.models import (
    BestQueryResult,  # 结果信封: 查询成功与失败两态的唯一载体
    BestSource,  # 单行归一载体: 站点原始列名与物理量在此对齐
    ColumnConstraint,  # 列约束值对象: 表单生成只认它, 不认裸 dict
    ResolvedName,  # 名称解析结果: 坐标加原始目标名, 供锥搜直接取用
)

# 本地: 权威协议层 (Q-01~05) — 表单键集/sqlid 解析/软错误判定/列名映射/重试
# 常量的单一事实源; 本客户端不私建任何第二份协议副本。
# (phase-2 取数面的 parse_csv_rows/build_page_url/count_sqlid/GETCOUNT_PATH 等
# 归 src.client_paging 持有; 名称解析面的 NSS_SOLVE_PATH/parse_name_resolve/
# is_name_resolve_failure 归 src.client_resolve 持有; 锥形与 proximity 查询面
# (CATALOG_GROUPS/magnitude_column/proximity_radec_text/Q-51 两个 guard) 归
# src.client_query 持有; 本模块不持第二份。)
from src.protocol import (
    CATALOG_COLUMNS,  # 静态列清单: 列内省接口的唯一数据源, 站点新增列需同步
    MAX_BACKOFF_S,  # 退避封顶(秒): 指数项的硬上限, 见构造函数里 backoff_max 的接线
    MAX_RETRIES,  # 重试次数上限的单一事实源: 构造函数默认值从此取
    RETRY_BACKOFF_S,  # 退避基数(秒): 服务端 Retry-After 优先, 此值只作兜底
    RETRY_STATUS_CODES,  # 可恢复状态码白名单: 业务性 4xx 重试没有意义
    Soft404Error,  # 路由或会话级软失败异常: 与业务性空结果严格分开
    is_soft_error,  # 判 200 携带的软错误体: 状态码白名单看不见它
    normalize_sqlid,  # sqlid 归一: 格式非法时抛错, 不静默返回 None
    resolve_catalog,  # 星表 id 归一(含旧别名): 导航组名在此被拒
    soft_error_detail,  # 从软错误体取可读 detail: 取不到时调用方要自己兜底
)

logger = logging.getLogger(__name__)  # 库级 logger: handler 交调用方配置, 本模块不装

# 连接常量从协议层再导出 (重试策略常量与端点常量的单一事实源在 protocol);
# 名字保持可从本模块 import
from src.protocol import BEST_BASE_URL, REQUEST_TIMEOUT  # noqa: E402

# 错误码契约: 定义上收至 protocol (单一事实源; 分层上收也是破除 Import 环
# 的一步)。名字保持可从本模块 import (既有调用方零改动)。
# 2026-10-05 R5-03 补回: 这一行再导出曾随上收一并漏删, 而本文件上方注释仍在
# 承诺"名字保持可从本模块 import"。后果是实打实的 —— test/integration/
# test_query_chain.py 的 ``from src.client import E_NO_SQLID`` 随之 ImportError,
# 被该文件的 legacy-import-guard 整文件 skip 掉, 11 个用例静默退出收集集,
# 门禁仍全绿 (Q8 检测报告 P1-1)。漏删的是"再导出"这一半, 故此处按承诺补回。
# MUTATION: 再导出被删 (复现 2026-10-05 之前的状态)



class BestClient:
    """BEST 数据库 REST 客户端 (两阶段查询)。

    两阶段查询:
      1. POST 表单约束 → 在服务端创建 SQL 查询会话, 从 HTML 回包提取 sqlid
      2. GET sqlid API → 按会话约束分页取回 JSON/CSV 数据

    可查询星表 (12 个裸 id; /q 路由只接受裸 id):
      - CatalogType.PS1: Pan-STARRS All-Sky (导航组中发布为 calib/ps1)
      - CatalogType.CALIB_STRIPE82: Calibrated Stripe82
      - CatalogType.CALIB_GAIA_18: Calibrated Gaia DR3 (旧别名 CALIB_GAIA)
      - CatalogType.CALIB_JPLUS: Calibrated J-PLUS DR3
      - CatalogType.CALIB_SMSS: Calibrated SMSS DR4
      - CatalogType.CALIB_LANDOLT: Calibrated Landolt
      - CatalogType.CALIB_USS: Calibrated USS DR1
      - CatalogType.CALIB_SPLUS: Calibrated S-PLUS DR4
      - CatalogType.SCR_GALAH / SCR_LAMOST / XPSP: Standard Stars 各表
      - CatalogType.DR3XPCORR: Corrected Gaia DR3 XP spectra
    """

    def __init__(
        self,  # 实例自身: 节流时钟与重试策略都挂在实例上
        base_url: str = BEST_BASE_URL,  # 站点根: 默认取协议层常量, 离线回放时换成快照源
        auth: Optional[BestAuth] = None,  # 可选登录态: 已认证时经 export_session 显式移交 cookie
        rate_limit: float = 2.0,  # 全局最小请求间隔(秒): 线程池共享同一时钟, 不能各算各的
        max_retries: int = MAX_RETRIES,  # 只作用于 HTTPAdapter: 全类唯一的重试层
        timeout: int = REQUEST_TIMEOUT,  # 单请求超时(秒): 实例级默认值, 各请求点经 self.request_timeout 取用
    ) -> None:
        """构造客户端: 节流时钟 + 唯一重试层 + 可选认证态继承。

        契约:
          - ``rate_limit`` 是全局最小请求间隔, 交叉匹配线程池共享同一时钟
            (锁保护, 见 :meth:`_rate_limit_wait`);
          - ``max_retries`` 只作用于 session 的 HTTPAdapter — 全类只有这一层
            重试 (P1-6: 不得在其上手写第二层循环, 那会把一次瞬时失败放大成
            十几次线网请求, 并双倍站点看到的退避);
          - ``timeout`` 是**真正生效**的单请求超时: 阶段 1 POST、阶段 2 分页
            GET、``getcount``、名称解析一律经 :attr:`request_timeout` 取它。
            缺省即协议层 ``REQUEST_TIMEOUT``, 故未显式配置时行为与该常量
            完全一致 (A2-02: 此前本参数只被存下来、六个请求点全取常量, 配置里
            写 timeout 静默不生效, 而 core 层文档宣称"全量透传");
          - ``auth`` 已认证时经 ``export_session()`` 显式移交 cookie 与 CSRF 头,
            之后本客户端共享登录态; 关闭本客户端不会关闭 ``BestAuth`` 的会话
            (多客户端可共享认证)。
        """
        self.base_url = base_url.rstrip("/")  # 去尾斜杠: 后续拼接一律带前导 /, 防出双斜杠
        self.auth = auth  # 存引用而非拷贝: 多个客户端可共享同一份认证态
        self.rate_limit = rate_limit   # 全局最小请求间隔, 交叉匹配线程池共享同一时钟
        self.timeout = timeout         # 实例级单请求超时: 各请求点经 request_timeout 统一取用
        self._last_request_time = 0.0  # 零值表示从未请求过, 首个请求因此不必空等一轮
        # 保护交叉匹配线程池共享的节流时钟: 读-睡-写三步必须原子
        self._rate_limit_lock = threading.Lock()  # 锁粒度只覆盖间隔判定本身, 不包住 IO

        self.session = build_session()  # 硬化会话: trust_env=False (唯一出口见 src.http_session)
        # P1-6: 重试策略来自协议层常量 (与 Best 共享的单一事实源);
        # Retry-After 头由 respect_retry_after_header 显式兑现, 不自写退避
        # P3-5: allowed_methods 只放 GET — 表单 POST (phase-1 建 sqlid 会话)
        # 在 429/5xx 时重试会让服务端创建多个 sqlid 会话, 前两个成孤儿会话
        # (泄漏服务端查询配额); phase-2 分页 GET 才是幂等可重试的那一半
        retry_strategy = Retry(                           # 常量外置才有一处可改: 站点调退避口径时不必动客户端代码
            total=max_retries,                            # 总次数封顶: 再多也不把一次瞬时抖动放大成十几轮请求
            backoff_factor=RETRY_BACKOFF_S,               # 实测容忍的退避基数; 服务端 Retry-After 优先于此值
            status_forcelist=sorted(RETRY_STATUS_CODES),  # 只重试可恢复码: 业务性 4xx 重试没有意义
            allowed_methods=["GET"],                      # 代价是阶段一 POST 不自动重发: 建会话失败即如实报错给调用方
            respect_retry_after_header=True,              # 站点明说等待时长就别自己猜, 提前打只会再吃 429
            backoff_max=MAX_BACKOFF_S,                     # 封顶 60s: 常量在此被消费才不是死符号。total=3 时退避序列只有 2/4/8s,
                                                        #   故本条当前不改行为 —— 它防的是日后调大 total 或 backoff_factor 时
                                                        #   指数项失控 (而 Retry-After 不受此封顶约束, 那是服务端意图)
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)  # 适配器与策略一对一: 挂上即对两个 scheme 同时生效
        # https/http 双 scheme 挂载: 站点升级或镜像切换时重试策略不丢失
        self.session.mount("https://", adapter)  # 同一 adapter 实例供两个 scheme 复用, 策略不因协议分叉
        self.session.mount("http://", adapter)   # http 兜底镜像切换场景, 仍走同一套退避策略
        # UA + Accept 声明: 服务端按 Accept 分发 html/json 回包
        self.session.headers.update({                    # UA 与 Accept 在此定死: 服务端按 Accept 分发 html 还是 json
            "User-Agent": "astro-best",                  # 标识来意, 便于站点侧排障时认得出本客户端
            "Accept": "text/html,application/json,*/*",  # 阶段 1 要 html 取 sqlid, 阶段 2 要 csv 与 json 拉数据
        })
        # 已认证则显式移交会话材料 (cookie + CSRF 头): 匿名查询不带认证态,
        # 避免无谓的登录态泄漏; headers 整体不套用 — 那会用 requests 默认
        # 请求头覆盖本客户端上方声明的 UA/Accept, 只取 cookie 与 X-CSRFToken
        if self.auth:                                                                     # 未传认证就走匿名路径: 匿名查询不携带多余登录态
            material = self.auth.export_session()                                         # 显式移交而非共用对象: 多客户端可共享一份 BestAuth
            if material["authenticated"]:                                                 # 未登录时 material 同样存在, 判 authenticated 才算拿到会话
                self.session.cookies.update(material["cookies"])                          # 只搬 cookie: 整包 headers 会覆盖上面声明的 UA 与 Accept
                if material["csrf_token"]:                                                # 无 token 的会话不必塞空头, 空 CSRF 头会被站点拒
                    self.session.headers.update({"X-CSRFToken": material["csrf_token"]})  # CSRF 头是写操作的通行证, 缺了阶段 1 的 POST 会被 403

    @property
    def request_timeout(self) -> int:
        """本实例实际生效的单请求超时 (秒): 出网点超时的**主要**取值口。

        六个出网点里五个经本属性取值: 阶段 1 POST、阶段 2 分页 GET、
        ``getcount``、名称解析、``_request`` 的 ``setdefault`` 兜底。**第六个**
        ``check_connection`` 的连通性探测刻意写死 30s 独立超时 (:662) 不经本
        属性 —— 探测不该被查询的长超时拖住。故本属性不是"六个点的唯一取值口":
        新增**查询**出网点取它, 写死独立超时则须像 check_connection 那样在
        调用点注明理由。

        存在的理由是 A2-02: 修复前 ``self.timeout`` 只被存下来, 阶段 1 POST、
        阶段 2 分页 GET、``getcount``、名称解析四处全取协议层 ``REQUEST_TIMEOUT``,
        于是 ``BestClient(timeout=7)`` 实测三次请求都是 120s, 配置层
        (``src/core/pipeline.py`` 读 ``timeout``) 宣称的全量透传是假的。
        缺省仍取 ``REQUEST_TIMEOUT``, 所以未显式配置时行为逐字节不变。
        """
        return self.timeout  # 查询侧统一取值口: 新增查询出网点取它, 写死独立超时须注明理由

    @property
    def tap_url(self) -> str:
        """历史调用面别名: TAP 端点 = 当前 REST base_url。

        Returns:
            与 ``base_url`` 相同的字符串。保留此属性是因为 TAP 后端
            消费者 (脚本层与 E5 消融) 仍按旧名取端点; 它**不是**另一
            个端点, 也不带任何额外路径段。
        """
        return self.base_url  # 别名而非第二端点: 旧名消费方拿到的就是同一串地址

    def _rate_limit_wait(self) -> None:
        """按 ``rate_limit`` 节流: 与上次请求间隔不足则睡满差额 (跨线程共享)。

        读-睡-写三步在同一把锁内完成: 否则并发 worker 各自算出的 elapsed 都
        已超限, 节流被静默绕过 (典型竞态), 直接触发上游封禁。
        """
        with self._rate_limit_lock:                          # 三步同锁: 否则并发 worker 都判定已超限, 节流被静默绕过
            elapsed = time.time() - self._last_request_time  # 相对上次发出时刻计算, 睡完还要再刷新一次
            if elapsed < self.rate_limit:                    # 不足才睡: 间隔已够时不再制造无谓延迟
                time.sleep(self.rate_limit - elapsed)        # 睡满差额而非固定值: 多 worker 排队时不叠加惩罚
            self._last_request_time = time.time()            # 记在睡眠之后: 记在之前会让下一个 worker 少等一轮

    def _count(self, sqlid: str) -> Optional[int]:
        """服务端真实总行数 (phase-0 计数; 实现已抽至 client_paging)。

        委派壳: 同名同签名保留 — 测试对实例方法的 patch 依然生效
        (file-size-budget §3.2 实测性质); 失败降级语义 (计数不可用 →
        None, 查询继续) 由 client_paging.count_sqlid_rows 承担。
        """
        # 延迟导入: phase-2 取数引擎抽离件 (budget §3.2 阶段 1; 函数内导入
        from src.client_paging import count_sqlid_rows  # 函数内导入: 破 import 环, 代价是每次调用查一次模块缓存

        return count_sqlid_rows(self, sqlid)  # 降级在下游: 计数不可用返回 None, 主查询不中断

    def count(self, sqlid: str) -> Optional[int]:
        """:meth:`_count` 的公开缝 (agent 工具面 / 脚本调用)。

        sqlid 格式非法时抛 ``ValueError`` 而不是静默返回 None: 静默 None 会
        让调用方把"打错 id"误读成"服务端没有这个会话的计数", 两种失败
        语义无法区分。
        """
        return self._count(normalize_sqlid(sqlid))  # 先归一再委派: 格式错抛 ValueError 而非静默 None

    # ------------------------------------------------------------------
    # 天体名解析 (P1-8): /nss/solve 端点代理 CDS Sesame
    # ------------------------------------------------------------------

    def resolve_name(self, name: str) -> ResolvedName:
        """``/nss/solve`` 名称解析 (实现已抽至 client_resolve, 阶段 3)。

        委派壳: 同名同签名保留 — 测试对实例方法的 patch 依然生效
        (file-size-budget §3.2 实测性质)。五种失败语义 (空名/网络失败/
        软错误体/回包不可解析/200 加失败标记) 全部由 client_resolve 承担,
        本壳只做转发, 不在此复制第二份判定。
        """
        # 延迟导入: 名称解析面抽离件 (预算 §3.2 阶段 3; 别名避与壳同名)
        from src.client_resolve import resolve_name as _resolve_name_impl

        return _resolve_name_impl(self, name)  # 位置直传: 壳只有一个自由参数, 无错位余地

    # ------------------------------------------------------------------
    # 两阶段查询引擎 (POST 取 sqlid -> GET 分页拉数据)
    # ------------------------------------------------------------------


    def _submit_query_for_sqlid(
        self,  # 实例: 阶段 1 走本客户端的会话与同一把限流
        catalog_path: str,  # 星表 /q 路径: 直接取自路径映射表, 不现场拼
        form_data: dict[str, str],  # 阶段 1 表单键值: 由协议层生成, 客户端不改键
    ) -> tuple[Optional[str], Optional[str]]:
        """阶段 1 提交与 sqlid 抽取 (实现已抽至 client_phase1, 阶段 6)。

        委派壳: 同名同签名保留 —— 六处测试打桩与钩子分级都依赖这个绑定。
        「软错误/无 sqlid 返回 (None, 消息) vs 传输失败原异常上抛」这条
        不可合并的分流由 client_phase1 承担, 本壳只做转发。
        """
        # 延迟导入: phase-1 引擎抽离件 (预算 §3.2 阶段 6; 别名避与壳同名)
        from src.client_phase1 import _submit_query_for_sqlid as _submit_impl

        return _submit_impl(self, catalog_path, form_data)  # 位置直传: 三个位置参数, 无错位余地

    def _execute_query(
        self,  # 实例: 阶段 2 分页复用同一会话与同一把限流
        catalog_path: str,  # 路径只进错误信封: 让调用方知道是哪张表出的问题
        form_data: dict[str, str],  # 阶段 1 已提交的表单键值: 此处不用但签名要留
        output_format: str = "csv",  # 声明式格式只进溯源: 阶段 2 一律按 csv 拉后本地解析
        max_rows: int = 50000,  # 取回上限: **phase-2 本地封顶**, 不进阶段 1 表单、不影响服务端会话 (A2-03)
        page_size: int = 1000,  # 每页行数: 太大则单次回包难中断, 太小则往返过多
        sort: Optional[str] = None,  # 显式排序列: 2026-07 起必须透传到分页 URL, 否则请求无序
        order: str = "asc",  # 排序方向: 与 sort 成对转发; 本壳不判定有效性, 有效性由 client_phase1 单点持有
        start_page: int = 1,  # 起始页: 断点续传靠它跳过已取页
        on_page_fetched: Optional[Callable[[int, list[BestSource]], None]] = None,  # 逐页回调: 进度落盘与取消检查都挂在这一个钩子上
        initial_sources: Optional[list[BestSource]] = None,  # 续传已取行: 与起始页成对, 单给其一会让行号错位
    ) -> BestQueryResult:
        """两阶段一次查询的执行主体 (实现已抽至 client_phase1, 阶段 6)。

        委派壳: 同名同签名保留 —— 三处打桩与全部查询方法的出口都依赖它。
        阶段 1 失败在此还原成失败信封 (本方法对调用方「只回信封不抛」)、
        成功后整份委派阶段 2, 这条契约由 client_phase1 承担。
        """
        # 延迟导入: phase-1 引擎抽离件 (两阶段编排委派)
        from src.client_phase1 import _execute_query as _execute_query_impl

        # 位置参数直传: 与 client_phase1 的签名逐位对齐, 尾部两项用关键字
        # 以免 start_page/on_page_fetched/initial_sources 三者错位。
        return _execute_query_impl(
            self, catalog_path, form_data, output_format, max_rows, page_size,  # 前六项顺序固定
            sort=sort, order=order,  # 排序列透传: 缺这一对则分页 URL 里没有 sort
            start_page=start_page,  # 续传页号: 与已取行成对
            on_page_fetched=on_page_fetched,  # 回调不下传会丢进度与取消
            initial_sources=initial_sources,  # 续传已取行: 计数与截断由下游重算
        )

    def _fetch_sqlid_data(
        self,  # 实例: 被委派方靠它读会话、节流时钟与配置
        sqlid: str,  # 阶段 1 交回的会话 id: 阶段 2 的唯一入口
        output_format: str = "csv",  # 声明式格式: 仅进溯源, 解析一律按 csv
        max_rows: int = 50000,  # 取回上限: 与页大小解耦, 便于分批跑批
        page_size: int = 1000,  # 每页行数: 决定单次请求体积与中断粒度
        max_pages: Optional[int] = None,  # 页数硬上限 (P0-04): None 即由 client_paging 按 max_rows/page_size 推
        catalog_path: str = "",  # 可空: 续取调用方通常不重复给星表, 强制要求会到处补参
        sort: Optional[str] = None,  # 显式排序列: 2026-07 起必须透传到分页 URL, 否则请求无序
        order: str = "asc",  # 排序方向: phase-2 分页 URL 的拼装位; sort 为空时 order 无意义, 拼装由 client_paging 单点持有
        start_page: int = 1,  # 起始页: 断点续传入口, 1 表示从头
        on_page_fetched: Optional[Callable[[int, list[BestSource]], None]] = None,  # 逐页回调: 进度与取消的唯一钩子, 不下传就丢两者
        initial_sources: Optional[list[BestSource]] = None,  # 续传已取行: 与起始页成对传入, 缺一即错位
    ) -> BestQueryResult:
        """phase-2 取数引擎 (实现已抽至 client_paging.fetch_sqlid_data)。

        委派壳: 同名同签名保留 — 测试对实例方法的 patch 依然生效
        (file-size-budget §3.2 实测性质)。失败语义 (首页断网显式
        E_BACKEND / 分页中断 truncated=True / 软错误体 E_SOFT_404 /
        结构半行跳过并计数) 由 client_paging 承担, 本壳只做转发。
        """
        # 延迟导入: phase-2 取数引擎抽离件 (预算 §3.2 阶段 1 委派壳)
        from src.client_paging import fetch_sqlid_data  # 函数内导入: 取数引擎已抽离, 顶部导入会成环

        return fetch_sqlid_data(
            self, sqlid, output_format=output_format, max_rows=max_rows,  # self 传首位: 被委派方靠它读会话与节流时钟
            page_size=page_size, catalog_path=catalog_path,  # 两项挤一行: 委派壳只转发, 不在此改口径
            max_pages=max_pages,                             # 页数上限同样只转发: 口径由 client_paging 单点持有
            sort=sort, order=order,                             # 排序列透传: 此前这一对参数在此**被吞掉**, 分页永远无序
            start_page=start_page, initial_sources=initial_sources,  # 断点续传两件套同传: 单给其一会让页号与已取行错位
            on_page_fetched=on_page_fetched,                         # 逐页回调透传: 进度落盘与取消检查都挂在这一个钩子上
        )

    def query_standard_stars(
        self,  # 实例: 三个查询方法共用同一出口, 失败语义因此一致
        constraints: Optional[list[ColumnConstraint]] = None,  # 可选列约束: None 与空列表等价, 键集仍固定下发
        output_format: str = "csv",  # 声明式格式: 只进溯源, 阶段 2 一律按 csv 拉
        max_rows: int = 50000,  # 取回上限: 与页大小解耦, 批处理时好按批切
        page_size: int = 1000,  # 每页行数: 单页过大时一次失败就要重跑整页
        table: str = "scr_lamost",  # 标准星成员表: 导航组名本身会被 /q 路由拒绝
        columns: Optional[list[str]] = None,  # 可选列投影: 不给就按该星表的完整实测列清单下发
        sort: Optional[str] = None,  # 服务端排序键: 拼错时站点静默退回默认序, 不报错
        order: str = "asc",  # 升序为默认: 最近邻类查询要先取到角距最小的一批
        nearest_only: bool = False,  # 只留最近邻: 跨匹配批量时按输入位置去冗余
    ) -> BestQueryResult:
        """Standard Stars 组成员表查询 (实现已抽至 client_query, 阶段 5)。

        委派壳: 同名同签名保留。格式白名单前置校验与"表名→路径→表单→执行"
        四步的失败语义由 client_query 承担, 本壳只转发。
        """
        # 延迟导入: 查询表面抽离件 (预算 §3.2 阶段 5; 别名避与壳同名)
        from src.client_query import query_standard_stars as _query_standard_stars_impl

        # 位置参数直传: 与 client_query 的签名逐位对齐, 错位不报错只查空。
        return _query_standard_stars_impl(
            self, constraints, output_format, max_rows, page_size,  # 前五项顺序固定: 错位会把表名当页大小
            table, columns, sort, order, nearest_only,  # 尾部五项: 少传即静默少一项能力
        )

    def query_panstarrs(
        self,  # 实例: 本方法只固定表名, 其余能力与另两个查询方法同源
        constraints: Optional[list[ColumnConstraint]] = None,  # 可选列约束: 空列表也要建表单, 键集固定
        output_format: str = "csv",  # 声明式格式: 走同一份白名单校验
        max_rows: int = 50000,  # 取回上限: 缺省值与另两个查询方法一致, 便于横向比较
        page_size: int = 1000,  # 每页行数: ps1 行宽, 页太大回包解析压力高
        columns: Optional[list[str]] = None,  # 可选列投影: ps1 列数多, 投影能显著缩小回包
        sort: Optional[str] = None,  # 服务端排序列: 与页序一致才能拿到稳定的前 N 行
        order: str = "asc",  # 升序默认: 与排序键配对才有确定含义
        nearest_only: bool = False,  # 最近邻开关: 批量匹配时才需要, 单次全表查不置
    ) -> BestQueryResult:
        """Pan-STARRS All-Sky 查询 (实现已抽至 client_query, 阶段 5)。

        委派壳: 同名同签名保留。表名写死 ps1 与路径硬编码 "ps1/q" 的口径
        (与 CATALOG_PATHS 表项同值) 由 client_query 承担, 本壳只转发。
        """
        # 延迟导入: 查询表面抽离件 (ps1 巡天查询缝委派; 表名写死不开放换表)
        from src.client_query import query_panstarrs as _query_panstarrs_impl

        return _query_panstarrs_impl(
            self, constraints, output_format, max_rows, page_size,  # 前五项顺序固定: 错位会把表名当页大小
            columns, sort, order, nearest_only,  # 尾部四项: 少一个就静默少一项能力
        )

    def query_calibrated(
        self,  # 实例: 旧别名归一后才允许进路径表查路径
        survey: str = "stripe82",  # 巡天名: 接受旧别名, 归一后写进表单的是新拼写
        constraints: Optional[list[ColumnConstraint]] = None,  # 可选列约束: 归一后按目标表的可选列判定
        output_format: str = "csv",  # 声明式格式: 走同一份白名单, 避免建会话后才发现非法
        max_rows: int = 50000,  # 取回上限: 与另两个查询方法同口径
        page_size: int = 1000,  # 每页行数: 巡天表行宽不同, 页大小只影响往返次数
        columns: Optional[list[str]] = None,  # 可选列投影: 不给则取该表完整实测列
        sort: Optional[str] = None,  # 服务端排序列: 排序键的表前缀要跟归一后的表名一致
        order: str = "asc",  # 升序默认: 站点对未知值不报错, 写错只会静默换序
        nearest_only: bool = False,  # 最近邻开关: 仅在按坐标批匹配时有意义
    ) -> BestQueryResult:
        """well-calibrated 巡天表查询 (实现已抽至 client_query, 阶段 5)。

        委派壳: 同名同签名保留。旧别名归一 (gaia_dr3 -> gaia_dr3_18) 必须在
        查路径表**之前**完成这条口径由 client_query 承担, 本壳只转发。
        """
        # 延迟导入: 查询表面抽离件 (巡天查询缝委派; 旧别名须先归一再查表)
        from src.client_query import query_calibrated as _query_calibrated_impl

        return _query_calibrated_impl(
            self, survey, constraints, output_format,  # 前四项顺序固定: 错位会把巡天名当约束
            max_rows, page_size, columns,  # 尾部三项: 少传则站点按自己的默认列返回
            sort, order, nearest_only,  # 排序三件套齐传: 本壳不设默认, 漏一个就静默少一项能力
        )

    def cone_search(
        self,  # 实例: 锥搜与巡天查询共用同一出口
        ra: float,  # RA(度, ICRS): 入口即校验, 负值直接拒
        dec: float,  # Dec(度, ICRS): 越界值在入口拒, 否则服务端只回空集
        radius_arcsec: float = 180.0,  # 角秒半径: 天文语境下比度更贴近使用习惯
        catalog: str = "ps1",  # 星表 id: 导航组名会被展开成成员逐个查再合并
        band: Optional[str] = None,  # 波段过滤: 经协议层映射成真实列, 不给即不限波段
        max_records: int = 1000,  # 返回记录上限: 组查询时按成员数分摊, 总量仍以此封顶
        page_size: int = 1000,  # 每页行数: 默认与上限同值, 便于单页取完
        columns: Optional[list[str]] = None,  # 可选列投影: 不给则按该表完整列清单
        sort: Optional[str] = None,  # 服务端排序列: 按角距排才便于取最近邻
        order: str = "asc",  # 升序: 最近邻语义要求角距由小到大
        nearest_only: bool = False,  # 只留最近邻: 批量输入时每个位置只留一条
    ) -> BestQueryResult:
        """锥形检索 (实现已抽至 client_query.cone_search, 阶段 4)。

        委派壳: 同名同签名保留 — 测试对实例方法的 patch 依然生效
        (file-size-budget §3.2 实测性质)。std 组的成员展开/配额分摊/合并、
        Q-51 入参校验、波段→真实列映射全部由 client_query 承担, 本壳只转发。
        """
        # 延迟导入: 查询表面抽离件 (预算 §3.2 阶段 4; 别名避与壳同名)
        from src.client_query import cone_search as _cone_search_impl

        # 位置参数直传: 与 client_query 的签名逐位对齐, 少一个就错位到
        # max_records/columns 且不会报错 —— 只表现为筛不出结果。
        return _cone_search_impl(
            self, ra, dec, radius_arcsec, catalog, band,  # 前六项顺序固定: 错位只表现为查错天区
            max_records, page_size, columns,  # 上限与页大小: 组内各表保持同形
            sort, order, nearest_only,  # 排序三件套齐传: 少传即少能力, 站点对缺项不报错
        )

    def _build_form(
        self,  # 实例: 委派方要读它的会话与限流时钟
        catalog: str,  # 星表 id: 必须是已归一的裸 id, 导航组名会被表单层拒
        constraints: list[ColumnConstraint],  # 列约束: 空列表也要建表单, 服务端据此判定返回列
        max_rows: int,  # 取回上限: 本参数不进表单 — build_query_form 无此键; 截断判定在分页器 (A2-03)
        ra: Optional[float] = None,  # RA 可空: 非锥搜路径不传, 服务端按普通列约束查询
        dec: Optional[float] = None,  # Dec 可空: 与 RA 同进同出, 单给一个是非法组合
        radius_arcsec: Optional[float] = None,  # 角秒半径: 三者齐备才构成原生锥搜
        radec_text: Optional[str] = None,  # 已序列化的坐标块: proximity 批量路径用它取代三元组
        default_radius_arcsec: Optional[float] = None,  # 逐行默认半径: 服务端对没带 radius 的行套用此值
        columns: Optional[list[str]] = None,  # 列投影: 不给则下发该表完整列清单
        sort: Optional[str] = None,  # 排序列: 站点按字符串直传, 拼错静默退回默认序
        order: str = "asc",  # 升序缺省: 排序键缺省时方向没有意义, 仍写全以免错位
        nearest_only: bool = False,  # 最近邻开关: 只在按坐标查时有意义
    ) -> dict[str, str]:
        """Phase-1 检索表单 (实现已抽至 client_query.build_form, 阶段 2)。

        委派壳: 其余五个查询方法 (query_standard_stars/query_panstarrs/
        query_calibrated/cone_search/submit_query) 的调用点零改动;
        表单键集权威仍在 protocol.build_query_form (Q-01)。
        """
        # 延迟导入: query 表面抽离件 (预算 §3.2 阶段 2; 别名避与壳同名)
        from src.client_query import build_form as _build_form_impl

        return _build_form_impl(
            self, catalog, constraints, max_rows, ra=ra, dec=dec,  # 位置参数直传: 与实现签名逐位对齐, 少一个就错位到排序项
            radius_arcsec=radius_arcsec, radec_text=radec_text,  # 两种几何入口同传: 锥搜给三元组, 批量给坐标块
            default_radius_arcsec=default_radius_arcsec, columns=columns,  # 默认半径与列投影同传: 少传则站点按自己的默认列返回
            sort=sort, order=order, nearest_only=nearest_only,  # 排序三件套按名传: 位置直传会与 max_rows 错位
        )

    # ------------------------------------------------------------------
    # 下载层 / agent 工具层的公开缝
    # ------------------------------------------------------------------
    # 这些包装存在的意义: src.downloader、src.crossmatch、src.ai_tools 不再
    # 直接摸 _build_form / _submit_query_for_sqlid / _fetch_sqlid_data —
    # 两阶段协议每个阶段只有这一个公开入口, 私有副本无处生长。

    def submit_phase1(
        self,  # 实例: 阶段 1 走本客户端的会话与同一把限流
        catalog: str,  # 星表 id: 导航组名在此抛错, 而不是等一个软 404 回包
        constraints: Optional[list[ColumnConstraint]] = None,  # 可选列约束: 已给表单时这份被忽略, 优先级见下面分支
        form_data: Optional[dict[str, str]] = None,  # 预构造表单: 给定则原样 POST, 不做二次加工
        max_rows: int = 50000,  # 取回上限: 只在需要现构造表单时才有意义
        radec: Optional[tuple[float, float, float]] = None,  # 锥搜三元组: 顺序与表单参数一致, 传反不报错只查错天区
    ) -> tuple[Optional[str], Optional[str]]:
        """只做阶段 1: 构造并 POST 表单, 返回 (sqlid, error) (实现已抽至 client_phase1, 阶段 6)。

        委派壳: 同名同签名保留 —— 下载器在翻页前靠它把 sqlid 存成检查点。
        「form_data 优先, 未给才从 constraints 现构造」这条双入口口径
        (两条入口可能产出不同键集, 是为兼容既有调用方刻意保留的) 未动。
        """
        # 延迟导入: phase-1 引擎抽离件 (公开的只建会话缝委派)
        from src.client_phase1 import submit_phase1 as _submit_phase1_impl

        return _submit_phase1_impl(
            self, catalog, constraints, form_data, max_rows, radec,  # 位置直传: 与实现签名逐位对齐
        )

    def submit_query(
        self,  # 实例: 阶段 1 与阶段 2 都经本客户端的会话
        catalog: str,  # 星表 id: 导航组名会在阶段 1 被拒
        form_data: Optional[dict[str, str]] = None,  # 预构造表单: 给定即原样使用, 键集正确性由调用方自负
        constraints: Optional[list[ColumnConstraint]] = None,  # 列约束: 仅在未给表单时参与构造
        max_rows: int = 50000,  # 取回上限: phase-2 本地封顶, 不写进阶段 1 会话约束 (A2-03)
        output_format: str = "csv",  # 声明式格式: 只进溯源, 阶段 2 一律按 csv 拉
        page_size: int = 1000,  # 每页行数: 决定阶段 2 的往返次数
        sort: Optional[str] = None,  # 显式排序列: 2026-07 起必须透传到分页 URL
        order: str = "asc",  # 排序方向: 阶段 1/2 缝的转发位 —— 与 sort 成对进 client_phase1.submit_query
        start_page: int = 1,  # 起始页: 断点续传入口
        radec: Optional[tuple[float, float, float]] = None,  # 可选锥搜三元组: 给了就走服务端原生锥搜
        on_page_fetched: Optional[Callable[[int, list[BestSource]], None]] = None,  # 逐页回调: 进度与取消的下游唯一钩子
        initial_sources: Optional[list[BestSource]] = None,  # 续传已取行: 与起始页必须成对给
    ) -> BestQueryResult:
        """公开的阶段 1+2 缝 (实现已抽至 client_phase1, 阶段 6)。

        委派壳: 同名同签名保留。本方法对调用方「只回信封不抛」的契约, 与
        ``_execute_query`` 同一失败口径 (传输失败也在此还原成 E_BACKEND 信封),
        由 client_phase1 承担。
        """
        # 延迟导入: phase-1 引擎抽离件 (公开的两阶段缝委派)
        from src.client_phase1 import submit_query as _submit_query_impl

        # 前七项位置直传, **尾部全部用关键字**。
        # 这不是风格偏好, 是硬约束: ``client_phase1.submit_query`` 的第 7/8 位是
        # ``sort``/``order``, ``start_page`` 排在第 9 位。把 start_page 当第 8 个
        # 位置参数传过去, 它会绑到 ``sort`` 上, 再叠加下面的 ``sort=sort`` 就是
        # ``TypeError: submit_query() got multiple values for argument 'sort'``。
        # 2026-10-07 由门禁 ``TestDelegationSeamIsGuarded`` 当场抓出 —— 上一版
        # 注释写的是"前八项顺序固定", 那句话在 sort/order 插进签名后就过期了,
        # 而注释与实现不一致时门禁会跟着注释一起错。
        return _submit_query_impl(
            self, catalog, form_data, constraints, max_rows, output_format, page_size,  # 前七项
            start_page=start_page,  # 起始页: 关键字, 位置会随签名插参而漂
            sort=sort, order=order,  # 排序列透传: 缺这一对则分页 URL 里没有 sort
            radec=radec,  # 锥搜三元组: 给了就走服务端原生锥搜
            on_page_fetched=on_page_fetched,  # 回调透传: 不下传会同时丢进度与取消
            initial_sources=initial_sources,  # 续传已取行: 与起始页必须同时给
        )

    def fetch_page(
        self,  # 实例: 续取也走同一会话与同一把限流
        sqlid: str,  # 已有会话 id: 续取不重新提交表单
        page: int = 1,  # 页码从 1 起: 与服务端页序一致, 少一即重取一页
        page_size: int = 1000,  # 每页行数: 与缺省上限同值, 保证单页取完
        catalog: str = "",  # 可空: 续取通常不重复给星表, 强制要求会到处补参
        max_rows: Optional[int] = None,  # 可空上限: 为空时按页大小封顶一页
        on_page_fetched: Optional[Callable[[int, list[BestSource]], None]] = None,  # 逐页回调: 单页也要回调, 否则进度条不动
        initial_sources: Optional[list[BestSource]] = None,  # 续传已取行: 累计计数由下游重算
    ) -> BestQueryResult:
        """只取一个会话页 (公开的阶段 2 缝; 实现已抽至 client_paging.fetch_page)。

        委派壳: 同名同签名保留。「max_rows 缺省取 page_size, 即恰好一页」
        这条防呆口径 (漏传上限就不该把整个会话剩余页拉完) 由 client_paging 承担。
        """
        # 延迟导入: phase-2 取数引擎抽离件 (单页续取缝委派)
        from src.client_paging import fetch_page as _fetch_page_impl

        return _fetch_page_impl(
            self, sqlid, page, page_size, catalog, max_rows,  # 前六项位置直传: 错位会把页号当页大小
            on_page_fetched=on_page_fetched,  # 回调透传: 单页调用也要能报进度
            initial_sources=initial_sources,  # 续传已取行透传: 让分页器算准累计计数
        )

    def crossmatch_batch(
        self,  # 实例: 批量匹配复用同一会话与限流
        ra_list: list[float],  # RA 列表(度): 与 Dec 列表按位配对, 长度必须相等
        dec_list: list[float],  # Dec 列表(度): 长度不等时宁可判失败也不截断配对
        catalog: str = "ps1",  # 星表 id: 一次 POST 只打一张表
        radius_arcsec: float = 3.0,  # 默认三角秒: 交叉匹配按此半径筛同一天区
        columns: Optional[list[str]] = None,  # 可选列投影: 回显列只在 csv 形态稳定出现
        nearest_only: bool = True,  # 默认只要最近邻: 批量匹配的常规诉求
        max_rows: int = 50000,  # 取回上限: 覆盖全部输入点的期望返回量
        page_size: int = 1000,  # 每页行数: 大批量时页数决定总往返次数
    ) -> BestQueryResult:
        """服务端 proximity 批量交叉匹配 (实现已抽至 client_query, 阶段 4)。

        委派壳: 同名同签名保留 —— 唯一下游消费方 src/crossmatch.py 按公开缝
        调它 (直连私有方法会破坏封装, 私有签名一变这条路径就无声失效)。
        空表/长度不齐两种前置拒绝与 csv 硬编码格式口径由 client_query 承担。
        """
        # 延迟导入: 查询表面抽离件 (proximity 批量缝委派)
        from src.client_query import crossmatch_batch as _crossmatch_batch_impl

        return _crossmatch_batch_impl(
            self, ra_list, dec_list, catalog, radius_arcsec,  # 前五项位置直传: 错位会让坐标对到别的星表
            columns, nearest_only, max_rows, page_size,  # 尾部四项顺序固定: 错位不报错只静默少一项能力
        )

    def query_result(
        self,  # 实例: 信封版查询走同一会话
        catalog: str = "ps1",  # 星表 id: 导航组名会被归一层拒掉
        constraints: Optional[list[dict]] = None,  # 约束用裸 dict: 脚本层按站点原生键名给, 容忍双拼写
        ra: Optional[float] = None,  # RA 可空: 非锥搜路径不传
        dec: Optional[float] = None,  # Dec 可空: 与 RA 同进同出, 单给一个是非法组合
        radius_arcsec: Optional[float] = None,  # 角秒半径: 三者齐备才是原生锥搜
        max_rows: int = 50000,  # 取回上限: 与裸行版同口径, 便于两种调用面对照
        columns: Optional[list[str]] = None,  # 列投影: 不给则取该表完整列
        sort: Optional[str] = None,  # 排序列: 站点直传字符串, 拼错静默退回默认序
        order: str = "asc",  # 升序缺省: 与排序键同传才构成确定次序
        nearest_only: bool = False,  # 最近邻开关: 默认关, 交由调用方显式要求
    ) -> BestQueryResult:
        """``query`` 的同参信封版: 完整 BestQueryResult (E2 对账消费)。

        实现已抽至 client_query.query_result (阶段 2); 本壳转发。
        """
        # 延迟导入: query 表面抽离件 (信封 seam 委派)
        from src.client_query import query_result as _query_result_fn

        # 位置参数直传: 与 client_query 的签名逐位对齐, 少写一个关键字
        # 就可能错位到 order/nearest_only, 且不会报错只筛不出结果。
        return _query_result_fn(
            self, catalog, constraints, ra, dec, radius_arcsec, max_rows,  # 位置直传: 与实现签名逐位对齐, 少一个就错位到排序项
            columns, sort, order, nearest_only,  # 尾部四个位置参数: 顺序不能调换, 错位只表现为筛不出结果
        )

    def query(
        self,  # 实例: 裸行投影走同一会话与限流
        catalog: str = "ps1",  # 星表 id: 归一在下游做, 这里保持调用面简洁
        constraints: Optional[list[dict]] = None,  # 约束用裸 dict: 两种方言拼写的容忍由下游归一
        ra: Optional[float] = None,  # RA 可空: 非锥搜路径不传
        dec: Optional[float] = None,  # Dec 可空: 与 RA 同进同出
        radius_arcsec: Optional[float] = None,  # 角秒半径可空: 少给一个就退化成无空间约束的查询
        max_rows: int = 50000,  # 取回上限: 与信封版同口径, 便于横向对照两种调用面
        columns: Optional[list[str]] = None,  # 列投影: 不给则取该表完整列
        sort: Optional[str] = None,  # 排序列: 站点直传字符串, 拼错静默退回默认序
        order: str = "asc",  # 升序缺省: 裸行投影与信封版同口径
        nearest_only: bool = False,  # 最近邻开关: 默认关, 免得调用方误以为已去冗余
    ) -> list[dict]:
        """通用列约束查询 → **裸行投影** (TAP 后端与脚本式调用面)。

        实现已抽至 client_query.query (阶段 2, budget §3.2); 本壳转发。
        返回站点原始列名的裸行 (``BestSource.raw_data`` 拷贝), 不做归一化。
        """
        # 延迟导入: query 表面抽离件 (裸行投影 seam 委派)
        from src.client_query import query as _query_impl

        return _query_impl(
            self, catalog, constraints, ra, dec, radius_arcsec, max_rows,  # 位置直传: 与共享主体签名逐位对齐
            columns, sort, order, nearest_only,  # 尾部四项顺序固定: 错位不报错, 只表现为结果不对
        )

    def _query_result(
        self,  # 实例: 共享主体要读会话与限流时钟
        catalog: str,  # 星表 id: 裸 id, 归一在更下一层做
        constraints: Optional[list[dict]],  # 裸 dict 约束: 双拼写容忍在共享主体里完成
        ra: Optional[float],  # RA: 可空表示非锥搜路径
        dec: Optional[float],  # Dec: 与 RA 同进同出, 单给一个是非法组合
        radius_arcsec: Optional[float],  # 角秒半径: 与赤经赤纬同进同出, 单给一个非法
        max_rows: int,  # 取回上限: phase-2 本地封顶, 不进表单故也不存在"写进表单后不可改" (A2-03)
        columns: Optional[list[str]],  # 列投影: 可空表示取完整列
        sort: Optional[str],  # 排序列: 可空表示不排序, 由服务端默认序兜底
        order: str,  # 排序方向: 缺省升序由上层给值, 这里不再兜一层
        nearest_only: bool,  # 最近邻开关: 显式传入, 不设隐式默认
    ) -> BestQueryResult:
        """query/query_result 共享的执行主体 (实现已抽至 client_query)。

        委派壳 (阶段 2, budget §3.2): 约束方言双拼写容忍与失败语义
        (软错误体 Soft404Error / 其余 RuntimeError, 不降级空结果) 由
        client_query._query_result 承担, 本壳只做转发。
        """
        # 延迟导入: query 表面抽离件 (共享执行主体委派)
        from src.client_query import _query_result as _query_result_impl

        return _query_result_impl(
            self, catalog, constraints, ra, dec, radius_arcsec, max_rows,  # 位置直传: 与下游共享主体逐位对齐
            columns, sort, order, nearest_only,  # 尾部四项: 顺序固定, 错位不报错只静默改变结果
        )

    def check_connection(self) -> bool:
        """探测 BEST 站点是否可达 (只 GET 根路径, 不发任何查询)。

        连通性探测: 超时/连接错误一律 False, 不向外抛异常 — 调用方
        (CLI info/doctor) 需要的是一个布尔值, 不是堆栈。

        判据是**状态码 + 软错误体**两件套: BEST 对失效路由/会话一律回
        HTTP 200 加 ``{"error":"Not Found"}`` (A7-04), 只看 200 会把
        故障读成健康 —— 而这正是 CLI info/doctor 判"站点可达"的唯一依据。
        """
        try:
            # 根路径 200 即视为可达; 用独立超时 (30s) 与查询超时解耦
            resp = self.session.get(f"{self.base_url}/", timeout=30)  # 独立超时: 探测不该被查询的长超时拖住
            return resp.status_code == 200 and not is_soft_error(resp.text)  # 200 不等于可达: 软错误体同样是"站点在说不行"
        except Exception:
            # 宽捕获是有意的: 探测的契约就是"返回一个布尔", 连
            # requests 的具体异常类型都不该泄漏给 CLI/doctor 面板。
            return False

    def describe_columns(self, catalog: str = "ps1") -> list[str]:
        """返回该星表的已知列名清单 (查询前的列内省, IVOA TAP_SCHEMA 语义)。

        还原自 pybest 打包产物 (git 6f00efeb^〔本仓历史已无此对象〕〔本仓历史已无此对象〕) 的 ``Best.describe_columns`` (该树在 best 分支
        扁平化时丢失)。诚实声明: 这是 ``protocol.CATALOG_COLUMNS`` 的**静态
        清单**, 不是实时抓取表单页 — 站点新增列时以 references/ 的实测列名
        记录为准, 静态表需同步更新。

        Args:
            catalog: 星表 id (ps1/stripe82/gaia_dr3_18/...); 导航组名
                (std/calib/other) 会像 /q 路由一样被拒绝

        Returns:
            列名列表 (如 ["ps1_ra", "ps1_dec", ...])

        Raises:
            ValueError: 星表 id 无法解析
        """
        return list(CATALOG_COLUMNS[resolve_catalog(catalog)])

    def close(self) -> None:
        """释放本客户端连接池 (幂等)。

        只关自己的 ``session``: 认证会话由 :class:`BestAuth` 自持, 多个
        ``BestClient`` 可共享同一 ``BestAuth``, 在此关闭会波及其他客户端。
        """
        # hasattr 而非直接 self.session.close(): close() 允许在构造
        # 失败后被调用 (异常清理路径), 那时 session 可能尚未建立。
        if hasattr(self, "session"):  # 先探测再关: 构造失败后的清理路径上会话可能还不存在
            self.session.close()  # 只关自己的会话: 认证会话由认证态自持, 关它会波及其他客户端

    def _request(self, method: str, url: str, **kwargs) -> requests.Response:
        """发一次带节流的请求, 并检查响应体的软错误契约 (流式下载注入缝)。

        重试只存在于一个地方: session 的 ``HTTPAdapter`` (P1-6) — 全类没有
        第二层手写重试循环。本方法承担适配器做不到的四件事: 限流、超时默认值、
        P0-2 的状态码显式失败 (``raise_for_status`` 先于软错误检查 —
        401/403/404 一律显式抛 ``requests.HTTPError``, 直通的话
        "token 过期"被读成"天上没有源", 404 错误页甚至被当下载产物写盘)、
        以及 P0-3 的响应体软错误检查 (BEST 用 HTTP 200 + 短 JSON 错误体宣告
        路由不存在/会话过期, 状态码白名单看不见)。

        与查询路径的分工: 查询方法 (count/resolve_name/cone_search/...) 各自
        的错误语义不同 (计数降级 None / 名称解析归 NameResolveError / 查询归
        Soft404Error), 保持站点内联; 本方法是**流式下载** (best_export.
        download_file 的 ``request`` 注入体) 与任何"只要一次干净请求"的调用方
        的统一入口 — 限流与软错误检查因此仍由客户端单点负责。

        Args:
            method: HTTP 方法 (GET/POST)。
            url: 目标 URL。
            **kwargs: 透传 ``requests.Session.request`` 的参数。

        Returns:
            已通过状态码与软错误检查的响应对象。

        Raises:
            requests.HTTPError: 非 2xx 状态码 (P0-2)。
            Soft404Error: 响应体是软错误 (P0-3)。
        """
        self._rate_limit_wait()  # 统一入口先过限流: 下载请求同样受站点配额约束
        # setdefault 而非强制: 调用方显式给的 timeout 优先 (流式下载要
        # 更长的读超时), 这里只兜底那些没说的。
        kwargs.setdefault("timeout", self.request_timeout)  # 兜底而非强制: 流式下载要更长的读超时, 调用方显式值优先
        resp = self.session.request(method, url, **kwargs)  # 走 session: 连接池与适配器上的重试只有这一条路径能拿到
        # 先状态码后软错误体: 顺序反了会让 404 错误页被读成响应体内容,
        # 正是 P0-2 修掉的那个洞。
        resp.raise_for_status()  # 状态码先判: 顺序反了会把 404 错误页当成响应体内容
        if is_soft_error(resp.text):  # 再判软错误体: BEST 用 200 加短错误体宣告路由不存在
            raise Soft404Error(soft_error_detail(resp.text) or "soft error", url)
        return resp

    def download_file(
        self,  # 实例: 注入本客户端的请求体, 下载栈因此共用同一策略
        url: str,  # 待下载地址: 主机白名单校验在落盘那侧做
        savedir: str = "./",  # 目标目录: 不存在则创建, 路径消毒同样在落盘那侧
        overwrite: bool = True,  # 默认覆盖: 断点续传依赖同名文件被重写
        filename: Optional[str] = None,  # 显式文件名: 缺省时取响应头或地址末段
        job_id: Optional[str] = None,  # 作业标识只进日志: 不参与任何落盘决策
        progress_tracker: Any = None,  # 进度累加器: 可空, 为空则不落盘进度
        cancel_event: Any = None,  # 取消标志: 置位即中止, 走续传时已下字节不丢
    ) -> Optional[str]:
        """字节级流式下载 (HTTP Range 断点续传 + 取消), 薄壳委托 best_export。

        权威实现是 :func:`src.best_export.download_file` (续传/进度/取消/
        路径消毒的单点); 本方法只负责把带节流/重试/软错误检查的
        :meth:`_request` 注入进去 — 下载栈因此与查询栈共享同一会话与同一层
        重试 (P1-6/P1-10), 不再需要第二个客户端包装。

        Args:
            url: 待下载文件的 URL (主机白名单校验在 best_export 侧, P1-10)。
            savedir: 目标目录 (不存在则创建)。
            overwrite: 目标已存在时是否覆盖 (False 则跳过并返回既有路径)。
            filename: 显式文件名; 缺省时取 Content-Disposition 或 URL 末段。
            job_id: 调用方作业标识 (仅日志上下文, 不参与 IO 决策)。
            progress_tracker: 可选进度跟踪器 (累加字节并落盘)。
            cancel_event: 可选 ``threading.Event``; 置位即中止下载。

        Returns:
            落盘文件路径; 取消或网络失败返回 None (由调用方按取消标志分流)。
        """
        # 函数内延迟导入: best_export -> serialization 链只在真下载时才需要,
        # 放顶部会让每个 import src.client 的调用方都拖起落盘格式化层
        # (与 download_manager 的 FileJob 延迟导入同一纪律)。
        from src.best_export import download_file

        # request=self._request: 注入带限流/重试/软错误检查的请求体,
        # 使下载走的是本客户端的会话与策略, 而不是另开一个裸连接。
        return download_file(
            url, savedir=savedir, overwrite=overwrite, filename=filename,  # 位置加关键字混传: 前两项按位置, 其余必须写全名免得错位
            job_id=job_id, progress_tracker=progress_tracker,  # 作业标识与进度累加器同传: 两者互不依赖, 缺一不影响另一
            cancel_event=cancel_event, request=self._request,  # 取消标志与请求体是关键注入: 少一个就退回裸连接
        )

    def __enter__(self) -> "BestClient":
        """with 语法入口: ``with BestClient() as client:``。"""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """with 语法出口: 关闭连接池, 异常继续向外传播。

        刻意返回 ``None`` (不抑制异常): ``with`` 块里的查询失败必须
        原样冒泡, 被 ``__exit__`` 吞掉的话, 调用方只会看到"正常退出"
        却拿不到数据, 直接违反禁 fail-open。
        """
        self.close()  # 出口只关池子: 刻意不吞异常, 否则查询失败会被读成正常退出
        return
