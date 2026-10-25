"""src.tap.uws_service — UWS 作业生命周期 (建单/阶段迁移/执行/删除) 与作业结果面。

从 ``src.tap.service`` 拆出: 作业存储门禁、属主判定、create/phase/run/abort/
delete 状态机、作业 XML, 以及 ``/results`` 清单与 ``/results/result`` 结果文件
的 Range 读取, 全部收敛到本模块的 :class:`TapUWSMixin`; ``service.py`` 只保留
HTTP 动词到网关的零依赖映射。方法名/签名/返回类型与原内嵌实现逐字一致, 行为
零变更 (IVOA UWS 1.0: ivo://ivoa.net/xml/UWS/v1.0; 规范引用, 无 DOI)。

边界: 只用标准库 (http 事务归 service, 存储归 jobs); 属主不符一律 403, 绝不
静默穿透; 未完成就取结果是 409, 结果文件缺失是 410, 结果被 MAXREC 截断必挂
X-TAP-Overflow (与同步面同口径) — 前三个回归锚点由
test/unit/tap/test_service.py 钉死, 截断信号由 test/unit/tap/
test_tap_robustness.py (环回端到端) 钉死。

历史来源: 路由语义逐条对应 pybest 打包产物 (git 6f00efeb^〔本仓历史已无此对象〕〔本仓历史已无此对象〕)
``pybest/tap/router.py`` + ``pybest/services/server.py`` 的 UWS 部分。

基于标准库的零依赖 UWS 作业面。
"""
from __future__ import annotations

# 标准库: Range 头正则 (结果文件部分内容) / 类型标注
import re  # Range 头正则: 只认单个 bytes=start-[end] 区间, 多区间/后缀范围一律 416
from typing import Any, Optional

# ElementTree 仅用于生成对外 XML, 绝不解析外部输入 (注入面为零)
from xml.etree import ElementTree as ET  # nosec B405

# 本地导入: ADQL 预解析入口与错误类型 (建单前语法门禁, 跨解析能力边界)
from src.tap.adql import ADQLError, parse_adql  # 建单前的语法门禁: 错 ADQL 在 HTTP 层就 400, 不占 pending 配额

# 本地导入: 截断信号的头名/取值常量 — 同步面与异步面共用一份, 同口径由此保证
from src.tap.formats import OVERFLOW_HEADER, OVERFLOW_VALUE  # 异步结果面靠它挂 X-TAP-Overflow: 与 _sync 同一个头名

# 本地导入: 作业存储类型与配额/作业错误 (跨作业能力边界)
from src.tap.jobs import TapJobError, TapJobStore, TapQuotaError

# 本地导入: 响应载体与 XML 响应构造 (作业状态机的出口; 住在 response 以打破与 service 的循环依赖)
from src.tap.response import TapResponse, xml_response  # 出口类型集中在此, 状态机内部不构造裸 HTTP 响应

# UWS 命名空间前缀注册: 让 ElementTree 写出 uws:/xlink: 前缀而非 ns0: (TOPCAT 等客户端按前缀读)
ET.register_namespace("uws", "http://www.ivoa.net/xml/UWS/v1.0")  # 不注册会写成 ns0:, 按前缀读的客户端认不出
ET.register_namespace("xlink", "http://www.w3.org/1999/xlink")  # href 属性必须带 xlink: 前缀, 同理

# Range 头正则: 仅支持单个 bytes=start-[end] 区间 (多区间/后缀范围一律 416)。
# 刻意不支持多区间与 "bytes=-500" 后缀范围: UWS 客户端只用单区间, 而多区间
# 支持会把拼接逻辑带进切片路径, 一个 off-by-one 就是返回错乱的结果文件。
# \Z 而非 $: 防止 "bytes=0-10\r\nX-Injected: 1" 这类尾部注入绕过 fullmatch
_RANGE_RE = re.compile(r"bytes=(\d+)-(\d*)\Z")  # \Z 而非 $: 锁死尾部, 防 "bytes=0-10\r\nX-Injected: 1" 绕过 fullmatch


class TapUWSMixin:
    """UWS 作业生命周期混入: 由 :class:`src.tap.service.TapGateway` 继承装配。

    只含作业存储门禁、属主判定、建单与阶段迁移、作业 XML 和结果文件读取;
    自身不持有状态、不碰 socket — 存储由 ``self.job_store`` 提供, sync/async
    共用的查询校验由 ``self._check_common_query_params`` / ``self._maxrec``
    提供 (两者仍定义在 service 的网关类上)。拆成 mixin 只为把作业生命周期从
    HTTP 动词映射中剥离, ``gateway._async_action(...)`` 一类既有调用方式与
    ``from src.tap.service import TapJobStore`` 的导入路径均保持不变。
    """

    # 网关注入的作业存储: 为 None 时所有 async 路由统一 503 (未配置存储)
    job_store: Optional[TapJobStore]                                                          # 网关注入的作业存储: 未配置时异步路由统一回 503

    # -- 作业存储与属主 -----------------------------------------------------

    def _require_store(self) -> tuple[Optional[TapJobStore], Optional[TapResponse]]:
        """取作业存储; 未配置 (无 db_path/output_dir) 时 async 路由统一 503。"""
        # 503 而非 404/501: "服务端没配异步存储"是部署态问题, 客户端退避重试
        # 可能成功; 报成 404 会让客户端以为作业真的不存在而放弃
        if self.job_store is None:  # 未配置存储是部署态问题, 不是"作业不存在"
            return None, TapResponse(status=503, body=b"TAP async storage is not configured",
                                     media_type="text/plain")  # 503 而非 404: 客户端退避重试可能成功
        return self.job_store, None

    def _owner_key(self, authenticated: bool, client_host: str) -> str:
        """属主键: 认证/匿名前缀 + 客户端地址 (配额与越权判定的 principal)。

        认证位进键是刻意的: 同一客户端先匿名后认证是两个**不同** principal,
        否则匿名建的作业会被认证态直接接管, 构成越权。
        """
        return f"auth:{client_host}" if authenticated else f"anonymous:{client_host}"  # 认证位进键: 前缀不同即不同 principal

    def _job_or_error(
        self, job_id: str, owner_key: str                                                           # 实例与两个入参: 作业标识与属主键
    ) -> tuple[Optional[dict[str, Any]], Optional[TapResponse]]:
        """按 ID 取作业并校验属主; 不存在 404, 属主不符 403 (绝不静默放行)。"""
        store, error = self._require_store()                                                     # 先确认存储已配置: 未配置不该走到取作业这一步
        if error is not None:                                                                      # 有错误响应即返回: 三〇三之后不该再取作业
            return None, error
        job = store.get_job(job_id)                                                                 # 按标识取作业: 存储层是唯一事实源
        if not job:                                                                                 # 取不到即判不存在: 空行与缺行同义
            return None, TapResponse(status=404, body=b"TAP job not found", media_type="text/plain")
        # 属主不符一律 403 (不静默穿透): 作业 ID 是可枚举的短串, 放过就等于
        # 任何人都能读别人的查询结果
        if job["owner_key"] != owner_key:  # 属主不符一律 403: 作业 ID 是可枚举短串, 放过就等于任人可读
            return None, TapResponse(status=403, body=b"TAP job belongs to another principal",
                                     media_type="text/plain")
        return job, None

    def _create_async_job(
        self, params: dict[str, str], authenticated: bool, client_host: str                         # 实例: 建单编排器
    ) -> TapResponse:
        """UWS 建单: 校验 → 预解析 ADQL → 落 PENDING → 303 指向作业 URL。

        预解析的意义: 语法错误在 HTTP 层就返回 400, 不占用 pending 配额;
        ``PHASE=RUN`` 时立即排入线程池 (UWS 允许建单即跑)。配额超限转 429。
        """
        # 延迟导入: 错误文档出口住在 service (service 顶层导入本模块, 回导会成环)
        from src.tap.service import _tap_error  # 延迟导入: 错误文档出口住在 service, 回导会成环

        store, error = self._require_store()  # 三道校验同序: 存储 → 查询参数 → 配额
        if error is not None:                                                                    # 存储校验先过: 三道校验同序, 后两道才有意义
            return error
        query, output_format, error = self._check_common_query_params(params)  # 复用网关的共用校验, 不在本模块重写
        if error is not None:                                                                       # 查询参数有错即返回: 复用网关那一套校验
            return error
        maxrec, error = self._maxrec(params, authenticated)  # 上限随认证态而变, 与 jobs 的配额计数同一口径
        if error is not None:                                                                       # 配额校验有错即返回: 上限随认证态而变
            return error
        owner_key = self._owner_key(authenticated, client_host)  # 属主在建单时定死, 之后每次访问都拿它比对
        try:
            # 先解析再建单: 语法错误的 ADQL 在 HTTP 层就 400 返回, 不占用
            # pending 配额也不留下一条永远不会被执行的作业行
            parse_adql(query)  # 先解析再建单: 语法错不占 pending 配额, 也不留永远不执行的作业行
            job = store.create_job(  # 落 PENDING: "建单成功但未起跑"这个中间态必须可表达
                query,                                                                             # 查询文本: 原样落进作业行, 执行时才解析
                output_format,                                                                      # 输出格式: 决定结果文件的形态
                maxrec,                                                                          # 生效行数上限: 建单时就定死, 避免执行期再议
                owner_key=owner_key,                                                              # 属主键在建单时定死: 之后每次访问都拿它比对
                authenticated=authenticated,                                                        # 认证位进键: 匿名与认证是两个不同的属主
            )
            # PHASE=RUN 允许建单即跑 (UWS 规范允许), 但仍先落 PENDING 再迁移:
            # 直接建 RUN 态会让"建单成功但执行未开始"这个中间态无法表达
            if params.get("PHASE", "").upper() == "RUN":  # 建单即跑 (UWS 允许), 但仍先落 PENDING 再迁移
                store.start_job(job["id"])  # 迁移到 EXECUTING 并排队, 配额检查在 jobs 内做
        except TapQuotaError as exc:  # 单独一类: 配额是软错误, 429 让客户端退避重试有意义
            # 配额是软错误: 429 + VOTable 错误文档, 客户端可退避后重试
            return _tap_error(str(exc), 429)  # 429 而非 400: 报参数错会误导客户端去改本没问题的查询
        except (ADQLError, TapJobError, ValueError, UnicodeError) as exc:  # 显式枚举: 未知异常该冒泡, 不被宽泛 except 吞掉
            return _tap_error(str(exc))  # 默认 400: 调用方的查询本身有问题
        # 303 而非 201: UWS 要求客户端跟 Location 轮询作业 URL, 201 会让
        # 客户端把建单响应当最终结果读
        location = f"/tap/async/{job['id']}"  # Location 指向作业根 URL (不含 /results), 客户端据此轮询相位
        return TapResponse(status=303, body=b"", media_type="text/plain",
                           headers={"Location": location})  # 空体: 303 的信息全在 Location 上

    def _async_action(
        self,                                                                                       # 实例: 动作分发器
        method: str,                                                                          # 请求方法: 同一面下 GET 与 POST 语义不同
        job_id: str,                                                                                # 作业标识: 路由正则限死了字符集
        action: str,                                                                                # 动作段: 空串或三选一, 由上游正则约束
        params: dict[str, str],                                                                     # 参数: 相位面从它取值
        client_host: str,                                                                           # 客户端地址: 与凭据一起重建属主键
        *,                                                                                          # 关键字参数: 后面两项是可选上下文
        authenticated: bool = False,                                                                # 认证位: 与历史路由同一口径
        headers: Optional[dict[str, str]] = None,                                                   # 请求头可空: 结果面要从它读区间头
    ) -> TapResponse:
        """UWS 作业动作分发: 作业 XML/DELETE、phase RUN/ABORT、results 清单与结果文件。

        属主校验与历史 router 完全一致: 属主键由调用方凭据 + 客户端地址重建,
        不匹配即 403, 绝不静默穿透到他人作业。``action`` 由 :meth:`handle` 的
        路由正则约束在空/``/phase``/``/results``/``/results/result`` 四者之内。
        """
        # 延迟导入: 错误文档出口住在 service (service 顶层导入本模块, 回导会成环)
        from src.tap.service import _tap_error

        # 属主校验与历史 router 逐条一致: 键由调用方凭据重建, 不匹配即 403, 绝不静默穿透
        owner_key = self._owner_key(authenticated, client_host)  # 用当前凭据重建属主键, 不信 URL 里的任何身份信息
        job, error = self._job_or_error(job_id, owner_key)                                        # 先取作业再校验属主: 顺序与历史路由逐条一致
        if error is not None:                                                                   # 有错误响应即返回: 四〇三与四〇四都在这一步给出
            return error
        store, error = self._require_store()                                                       # 存储再确认一次: 动作面自己也要能独立工作
        if error is not None:                                                                      # 有错误响应即返回: 不重复上面那套错误响应
            return error
        if action == "":  # 空动作 = 作业根 URL: GET 作业 XML / DELETE 删单
            if method == "GET":
                return self._job_xml(job)  # 作业 XML 是客户端轮询的主出口
            if method == "DELETE":
                try:
                    store.delete_job(job_id)                                                        # 删单: 存储层负责行与产物两处的清理
                except TapJobError as exc:
                    return TapResponse(status=404, body=str(exc).encode(),
                                       media_type="text/plain")
                # 删除后 303 回集合: 客户端跟随后拿到的是"作业已不在"的
                # 确定答案, 而非对已删 URL 反复轮询
                return TapResponse(status=303, body=b"", media_type="text/plain",
                                   headers={"Location": "/tap/async"})
            return TapResponse(status=405, body=b"GET or DELETE required",
                               media_type="text/plain")
        if action == "/phase":  # 相位面: GET 读相位, POST 才改相位
            if method == "GET":
                # 回裸文本而非 XML: UWS 1.0 规定 /phase 的 GET 返回纯文本相位
                return TapResponse(status=200, body=str(job["phase"]).encode(),  # 裸文本是规范要求, 包 XML 会破坏客户端轮询
                                   media_type="text/plain")
            if method == "POST":
                # 大写归一: 规范里 PHASE 是大写字面量, 容忍小写是给手写
                # curl 的调用方方便, 不改变规范语义
                phase = params.get("PHASE", "").upper()  # 大写归一: 容忍小写是给手写 curl 方便, 不改变规范语义
                try:
                    if phase == "RUN":
                        store.start_job(job_id)                                                     # 改相位为运行: 配额检查在存储层做
                    elif phase == "ABORT":
                        store.abort_job(job_id)                                                  # 改相位为中止: 与运行相位互斥, 同样要过配额
                    else:
                        # 非法相位显式抛错: 静默忽略会让调用方以为已提交
                        raise TapJobError("PHASE must be RUN or ABORT")  # 显式抛: 静默忽略会让调用方以为已提交
                except TapQuotaError as exc:
                    return _tap_error(str(exc), 429)
                except TapJobError as exc:
                    return _tap_error(str(exc))
                return TapResponse(status=200, body=b"", media_type="text/plain")
            return TapResponse(status=405, body=b"GET or POST required",
                               media_type="text/plain")
        if action == "/results":  # 结果清单面: 只回答"有没有结果", 不吐数据
            root = ET.Element("{http://www.ivoa.net/xml/UWS/v1.0}results")  # 硬编码命名空间: 客户端按 UWS 1.0 固定前缀解析
            # 结果清单**只列 COMPLETED**: 提前给出 href 会让客户端立刻去取
            # 一个还不存在的文件, 把 409 状态当成作业失败
            if job["phase"] == "COMPLETED":  # 提前给 href 会让客户端把 409 误读成作业失败
                ET.SubElement(root, "result", {
                    "id": "result",
                    "{http://www.w3.org/1999/xlink}href": f"/tap/async/{job_id}/results/result",
                })
            return xml_response(root)
        if action == "/results/result":  # 结果实体面: 到这里才真正读文件
            if job["phase"] != "COMPLETED" or not job.get("result_path"):  # 两条件缺一不可: COMPLETED 但路径未登记同样取不到
                # 未完成/无结果文件是状态冲突: 409 而非 404, 让客户端知道"再等等"
                return TapResponse(  # 409 而非 404: 作业在, 只是没好, 客户端该等而不是重试建单
                    status=409,                                                                  # 状态取冲突: 作业在, 只是没好, 客户端该等
                    body=f"TAP job is in phase {job['phase']}".encode(),
                    media_type="text/plain",
                )
            path = job["result_path"]
            try:
                # 全量读进内存再按 Range 切: 单个作业结果的大小受 maxrec 配额
                # 约束, 换来实现简单的流式切片却要在拼接上多写三处逻辑
                with open(path, "rb") as handle:  # 全量读再切: 大小受 maxrec 配额约束, 换流式要多写三处拼接逻辑
                    body = handle.read()  # 外部 IO: 结果文件是唯一数据出口, 只在此处读盘
            except OSError:  # 结果文件被外部清掉: 作业行还在, 但文件不可恢复
                # 结果文件被外部清掉: 410 Gone (作业行还在, 文件已不可恢复)
                return TapResponse(status=410, body=b"TAP result file is missing",  # 410 而非 404: 作业行可查说明它本应存在, 只是不可恢复, 404 会误导下游重试
                                   media_type="text/plain")
            return self._range_response(body, job, headers)
        # action 理论上已被 handle 的路由正则限死四选一; 落到这里说明路由正则
        # 与本分发器脱节, 明确 404 比隐式 None 更容易在测试里发现
        return TapResponse(status=404, body=b"Not Found", media_type="text/plain")

    def _job_xml(self, job: dict[str, Any]) -> TapResponse:
        """UWS 作业 XML: phase/creationTime, 失败带 errorSummary, 完成带 result 链接。"""
        job_id = str(job["id"])
        root = ET.Element("{http://www.ivoa.net/xml/UWS/v1.0}job", {"id": job_id})
        ET.SubElement(root, "jobId").text = job_id
        ET.SubElement(root, "phase").text = str(job["phase"])
        ET.SubElement(root, "creationTime").text = str(job["created_at"])
        # errorSummary 只在有错误时出现: 客户端按元素存在性判断成败, 输出一个
        # 空的成功态 summary 会被误读成"作业失败但无详情"
        if job.get("error"):  # 只在有错误时出现: 空的成功态 summary 会被读成"失败但无详情"
            summary = ET.SubElement(root, "errorSummary", {"type": "fatal", "hasDetail": "false"})
            ET.SubElement(summary, "message").text = str(job["error"])
        # results 段与 /results 清单同判据 (仅 COMPLETED), 否则两个出口对
        # "有没有结果"给出不一致的答案
        if job["phase"] == "COMPLETED":  # 与 /results 清单同判据, 两个出口不能对"有没有结果"打架
            results = ET.SubElement(root, "results")
            ET.SubElement(results, "result", {
                "id": "result",
                "{http://www.w3.org/1999/xlink}href": f"/tap/async/{job_id}/results/result",
            })
        return xml_response(root)

    def _range_response(
        self,                                                                                       # 实例: 区间响应构造器
        body: bytes,                                                                               # 结果字节: 已全量读入内存, 切片在此完成
        job: dict[str, Any],                                                                        # 作业行: 校验和与登记大小都从它取
        headers: Optional[dict[str, str]] = None,                                                   # 请求头可空: 没有区间头就回全量
    ) -> TapResponse:
        """按单个 ``bytes=a-b`` Range 提供结果文件 (206 部分内容/416 不可满足)。

        无条件返回 ``Accept-Ranges: bytes`` 与 ``X-Checksum-SHA256``; 无 Range
        头时 200 全量。区间非法 (语法不符、start 越界、end<start) 一律 416 并
        带 ``Content-Range: bytes */<total>``; 合法区间 206, Content-Range 里
        的总长优先用库里登记的 size, 缺失才回退实际字节数。
        作业被 MAXREC 截断时 (库里的 ``overflow`` 位) 额外挂
        ``X-TAP-Overflow: true`` —— 与同步面 ``_sync`` 同一个头名同口径 (常量
        取自 :mod:`src.tap.formats`, 两处不各写一份)。缺这一个头, 异步面
        取到的就是一份与全集无法区分的残缺结果。
        """
        headers = headers or {}                                                                     # 头字典缺省新建: 不改调用方那份
        # 大小写两种键都取: BaseHTTPRequestHandler 的头字典不保证统一大小写,
        # 只认 "Range" 会让部分客户端的区间请求被静默忽略 (退化成全量返回)
        range_header = headers.get("Range") or headers.get("range") or ""  # 两种大小写都取: 头字典不保证统一大小写, 只认一种会静默退化成全量
        response_headers = {                                                                        # 响应头容器: 两条无条件头先写死
            "Accept-Ranges": "bytes",
            # 无条件带校验和: 客户端据此验证分段拼回的结果与原文件一致,
            # 缺了就失去了 Range 续传的全部意义
            "X-Checksum-SHA256": str(job.get("checksum") or ""),
        }
        if job.get("overflow"):                                                                    # 只有真被截断才挂: 干净结果不挂截断提示
            response_headers[OVERFLOW_HEADER] = OVERFLOW_VALUE  # 与同步面同口径: 头名/取值都取常量, 免得两条路径各写一份而漂移
        status = 200                                                                                # 状态缺省全量: 有区间头才改成部分内容
        if range_header:                                                                            # 有区间头才解析: 无区间时直接回全量
            # fullmatch 而非 search: 前缀匹配会让 "bytes=0-10, 20-30" 这种
            # 多区间请求被当成单区间处理
            match = _RANGE_RE.fullmatch(range_header.strip())  # fullmatch 而非 search: 前缀匹配会把多区间请求当单区间
            if not match:                                                                         # 语法不符即不可满足: 回总长让客户端自行修正
                return TapResponse(
                    status=416,                                                                     # 状态四一六: 区间语法错与越界是同一类
                    body=b"",                                                                       # 响应体为空: 错误响应不回数据
                    media_type="text/plain",
                    headers={"Content-Range": f"bytes */{len(body)}"},
                )
            start = int(match.group(1))                                                             # 起点取自区间: 闭区间左端
            # end 省略 (bytes=100-) 时取到文件末尾, 故用 len(body)-1 而非 len
            end = int(match.group(2)) if match.group(2) else len(body) - 1  # end 省略时取到末尾, 故用 -1 (闭区间上界)
            # start 越界或 end<start 都不可满足: 416 并回传总长, 让客户端
            # 能据 Content-Range 自行修正
            if start >= len(body) or end < start:                                                  # 起点越界或终点在前: 都不可满足, 回总长
                return TapResponse(
                    status=416,                                                                # 状态四一六: 与语法错同一支, 客户端处理方式相同
                    body=b"",                                                                       # 响应体为空: 同上, 不回数据
                    media_type="text/plain",
                    headers={"Content-Range": f"bytes */{len(body)}"},
                )
            # 末段越界按 RFC 允许截到文件末尾, 不算错误
            end = min(end, len(body) - 1)                                                           # 末段越界截到末尾: 规范允许, 不算错误
            # 切片右端 +1: Python 区间右开, 少一个 +1 会永远丢掉最后一个字节,
            # 客户端按 Content-Range 校验时才发现
            body = body[start:end + 1]  # 右端 +1: Python 区间右开, 少一个 +1 会永远丢掉最后一个字节
            status = 206  # 部分内容: 与全量 200 的差别只在这一行和 Content-Range
            # 总长优先用库里登记的 size: body 刚被切成片段, len(body) 已不是
            # 文件真实长度
            response_headers["Content-Range"] = f"bytes {start}-{end}/{job.get('size', len(body))}"  # 登记 size 优先: len(body) 此刻只是切片长
        response_headers["Content-Length"] = str(len(body))
        return TapResponse(
            status=status,                                                                        # 状态与片段: 全量是二百, 有区间是二百零六
            body=body,                                                                              # 片段即响应体: 切片结果直接就是回包内容
            # media_type 缺省给二进制流而非 text/plain: 结果可能是 fits/votable
            media_type=str(job.get("media_type") or "application/octet-stream"),  # 缺省二进制流: 结果可能是 fits/votable, 标 text/plain 会被乱解
            headers=response_headers,                                                              # 响应头随状态走: 区间头只在有区间时才存在
        )
