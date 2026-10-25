"""src.ai_tools — Agent-facing atomic tools over the verified BEST protocol.

能力边界: 7 个按 agent 意图切分的原子工具 (resolve_name / list_catalogs /
describe_catalog / cone_search / crossmatch_batch / count / fetch_page), 每个
返回统一信封 (data/status/cost/provenance) 并携带稳定 URI (best://...)。
边界: 只组合既有权威层 (protocol 表单键集 / BestClient 两阶段 / BestCrossMatch
proximity), 不得自建表单或自解析 CSV; 站点返回值一律标注 untrusted (S-2 提示
注入面); 工具层是唯一对外工具面 (P1-9 收敛), Best/BestClient 退居实现。
白盒锚点: references/ALGORITHM-SPEC.md §7 (工具面锚点);
contracts/envelope.contract.yaml (信封约定); temp/ai_ready_baseline/BASELINE.md
(L1 工具面设计, 实机验证)。

设计依据 (ISSUE-LIST A 组): Agent Readiness 的 Stable URLs (A-5, Required 档)
用 content-addressed URI 替代易失 sqlid; cost 字段 (P2-13) 让 agent 发起前能读
预算; 提示注入 (S-2) 在信封内显式标注 untrusted。设计基线:
temp/ai_ready_baseline/ 的工具面设计稿。
"""
from __future__ import annotations

# 标准库: 日志 (降级与脏输入告警的出口, 不留痕的降级等于没发生) / 耗时计时
# (monotonic, 不受系统时钟回拨影响) / 类型标注
import logging
import time
from typing import Any, Iterable, Optional

# --- 再导出: 只有本模块不再直接使用, 但属公开工具面的一部分 (T1) -----------
# `X as X` 是 ruff 认的显式再导出写法 (不加 noqa 也不报 F401)。这四条各有
# 真实消费方, 删掉即破坏契约:
#   E_INVALID_INPUT  —— 工具面五码之一, 测试与外部按码分支;
#   E_SOFT_404 / E_NAME_UNRESOLVED —— 另两支码 (协议层原名不同);
#   UNTRUSTED_CONTENT_NOTE —— S-2 注入提示原文, 下游按 status 分支时要读同一句。
from src.ai_tools_envelope import E_NAME_UNRESOLVED as E_NAME_UNRESOLVED
from src.ai_tools_envelope import E_SOFT_404 as E_SOFT_404
from src.ai_tools_envelope import UNTRUSTED_CONTENT_NOTE as UNTRUSTED_CONTENT_NOTE

# 本地: 信封构造层 (四分区载体 + 成功/失败出函点 + 引用句柄形态判据)
from src.ai_tools_envelope import (
    ToolResult,  # 四分区信封载体 (frozen dataclass)
    build_envelope,  # 成功信封构造点 (工具方法唯一出函处)
    error_envelope,  # 失败信封构造点: 异常 -> 稳定错误码的唯一映射阶梯
    is_safe_uri_segment,  # stable_uri 拼接段形态校验 (YZ-15)
    truncation_reasons,  # 截断成因清单提取 (YZ-44)
)

# 本地: 生产客户端 (两阶段 REST 的权威实现) — 工具层只调用, 不自建请求
from src.client import BestClient

# 本地: 交叉匹配执行器 (proximity 批量路径) — 复用其线程池与限流, 不重写
from src.crossmatch import BestCrossMatch

# 本地: 数据模型 — resolve_name 的返回载体 (to_dict 出口)
from src.models import ResolvedName

# 本地: 权威协议层 (Q-01~05) — 星表注册表/列清单/波段列/查询路径与
# 名称解析异常/软 404 判定, 全部单一事实源; 工具层不私建第二份副本。
from src.protocol import (
    CATALOG_COLUMNS,  # 该星表发布的响应列清单: 描述类工具的零请求答案
    CATALOG_DISPLAY,  # 星表展示名: 只进展示字段, 不参与路由判定
    CATALOG_GROUPS,  # 导航分组: 组名不是可查询路由, 只用来展开成员
    CATALOG_MAG_COLUMNS,  # 波段到星等列的映射: 供 agent 选 band 参数
    CATALOG_PATHS,  # 星表 id 到查询路径的映射: 稳定 URI 与错误信封都要它
    E_BACKEND,  # 兜底码: 网络/站点/未分类异常 (错误码真源在协议层)
    E_NO_SQLID,  # 阶段 1 未回会话号: 软 404 之外的另一类失败
    normalize_sqlid,  # sqlid 白名单归一: YZ-16 要求 fetch_page/count 边界复用它, 不自建第二份形态判据
    resolve_catalog,  # 星表归一: 工具层不自建白名单
)
from src.protocol import E_INVALID_INPUT as E_INVALID_INPUT

# --- 错误码词源与再导出 (T1: 定义上收至协议层, 本模块只做再导出) -----------
# 五个码与 contracts/error-codes.contract.yaml (BEST_1001/1006/1007/1008/1009)
# 及 temp/ai_ready_baseline/BASELINE.md 的工具面码表对齐。字面量本身是运行时
# 契约 (调用方/测试按码分支), 故保持英文不翻译。
# 2026-10-05 (H4-2, G1-09): 五个码现已**逐个**在契约里有条目 (E_BACKEND 原先
# 代码在用而契约缺失, 已补 BEST_1009); 对齐由
# test/unit/contracts/test_error_code_contract_alignment.py 双向守护。
# 2026-10-05 (T1): 定义上收至协议层。此前五个码在工具层各有一份字面量, 与
# src/crossmatch.py 的 _QUERY_FAILED 构成重复定义 —— 同一个码字面量散在多个
# 赋值点, 改契约时漏改一处即"半边新半边旧"的静默分叉。
# 2026-10-06: 再导出的名字按"协议层是否同名"分两类, 别再混成一段说:
#   - E_INVALID_INPUT / E_NO_SQLID / E_BACKEND: 协议层已用同名字段, 上面的
#     import 直接取来即用, 本模块不赋值 (E_INVALID_INPUT 因此只剩再导出用途);
#   - E_SOFT_404 / E_NAME_UNRESOLVED: 协议层用了别的名字 (SOFT_404_ERROR_CODE /
#     NameResolveError.code), 别名赋值在信封层做, 此处 `import X as X` 再导出。
# **再导出而非删名**: 既有 `from src.ai_tools import E_*` 零改动, 且
# test_error_code_contract_alignment.py 靠 dir(ai_tools) 收码, 删名会让该门禁
# 的收集集空掉一半 (恒绿)。
logger = logging.getLogger(__name__)  # 模块级 logger: 降级与脏输入留痕, 便于事后核对发了什么

# 模块内短别名: 私有名前缀在抽离后已无必要 (信封层是独立模块, 不是同文件
# 内部协作), 去掉能让调用点读起来与 `ToolResult`/`build_envelope` 同级。
_envelope = build_envelope  # 只做改名, 不做包装: 多一层函数就多一处可漂移
_error_envelope = error_envelope  # 同上
_is_safe_uri_segment = is_safe_uri_segment  # 同上
_truncation_reasons = truncation_reasons  # 同上

# fetch_page 页大小上限: references/tools.schema.json 的
# fetch_page.page_size 声明 "maximum": 10000, 而协议层不做任何边界校验 —
# 越界值会原样进 /sqlid 分页 URL 的 rows= 参数。本常量把 schema 声明变成
# 可执行契约 (工具边界 fail-closed, ValueError -> E_INVALID_INPUT)。
MAX_FETCH_PAGE_SIZE = 10000  # 与 schema 的 maximum 逐字对齐, 越界在此 fail-closed


class ToolBox:
    """挂在同一个 BEST 客户端上的原子工具集 (agent 唯一工具面, P1-9)。

    ``http_requests`` 在 session 的**请求级**出口 (``Session.request``) 处包
    一层计数, 因此 ``cost`` 字段报的是实际发出的请求调用数而非按方法名估算 ——
    分页/降级路径这样才算得准。但它**不等于线网往返次数**: urllib3 ``Retry``
    在 ``HTTPAdapter.send`` 内部重试, 不再回到 ``Session.request``, 故 429/5xx
    抖动下的重试请求**不计入**本字段 (实测: 服务端收 3 次, 本字段报 1)。agent
    按它做预算判断时要把这点算进去。
    """

    def __init__(self, client: Optional[BestClient] = None) -> None:
        """构造工具箱: 惰性建客户端 + 装计数器 + 挂交叉匹配执行器。

        Args:
            client: 可注入的 BestClient (测试替身/共享认证态); 缺省构造
                默认客户端 (含 urllib3 重试层与限流, 见 src.client)
        Raises:
            TypeError: 传入的不是 ``BestClient`` 实例。

        Note:
            类型校验是**故意加的可读性防线**: 工具面在 ``cone_search`` 之后
            要访问 ``result.success``/``result.sources`` (BestQueryResult
            信封); 传入返回裸 ``list[dict]`` 的脚本式客户端时, 会炸出
            ``AttributeError: 'list' object has no attribute 'success'`` —
            错误信息完全指不到"传错了客户端"这个根因, 排障成本极高。

            判别用 **duck-typing 查 ToolBox 真正依赖的两个入口**
            (``fetch_page`` / ``resolve_name``): 光查 ``cone_search`` 不够,
            脚本式门面也有同名方法 (只是返回裸 list), 查了也拦不住。
            不用 ``isinstance`` — 测试替身只要契约一致就应被接受。

            P1 注记: pybest 单类双副本 (``src.pybest.Best``) 已合并删除,
            本防线保留为契约守卫 — 未来任何"返回行字典"的脚本式客户端
            都会在这里被指名拒绝, 而不是在信封访问处炸成无头异常。
        """
        if client is not None and not (                                                       # 双重条件: 客户端存在且请求计数尚未开始时才装计数器
            hasattr(client, "fetch_page") and hasattr(client, "resolve_name")
        ):
            raise TypeError(
                "ToolBox requires a BestClient (two-phase REST client returning "
                f"BestQueryResult); got {type(client).__name__}. Script-style "
                "clients returning bare list[dict] are not compatible with "
                "the tool envelope - use BestClient/BestDownloader for "
                "script-style fetching instead."
            )
        self.client = client or BestClient()  # 缺省构造默认客户端 (含限流/重试/超时默认值)
        self._requests = 0  # 累计请求数, 由下面的包装层累加
        self._install_request_counter()  # 先装计数器再建 crossmatch, 否则漏计它的请求
        # 交叉匹配走 BestCrossMatch (proximity 批量路径的权威实现), 与它共享
        # 同一 client, 因此其线网请求同样落入本工具箱的计数
        self.crossmatch = BestCrossMatch(self.client)                                            # 交叉匹配对象: 复用同一会话, 节流时钟才生效

    def _install_request_counter(self) -> None:
        """在 ``session.request`` 上包一层计数器 (monkey-patch, 装一次)。

        选 ``Session.request`` 而不是各方法的 get/post: 它是 requests
        全部请求的必经之路, 一次高层调用记一次。**但它只数到这一层**:
        重试 (HTTPAdapter 层) 在 ``HTTPAdapter.send`` 内部循环, 不会再回到
        ``Session.request``, 故重试产生的额外线网请求计不进本计数器 ——
        ``cost.http_requests`` 是请求级计数, 不是线网流量实测, 别当可复核的
        流量账本用。
        """
        session = self.client.session  # requests.Session 实例, 线网唯一出口
        original = session.request  # 存原方法, 闭包里原样委托、不改语义

        def counting_request(*args: Any, **kwargs: Any) -> Any:
            """计数一次 HTTP 请求, 然后原样委托给真实 session。

            闭包持 ``original`` 引用, 不在计数处吞异常/改参数 — 计数器
            只观察, 不改变请求语义。
            """
            self._requests += 1                                                               # 计数只观察: 不吞异常也不改参数, 请求语义保持原样
            return original(*args, **kwargs)

        session.request = counting_request  # type: ignore[method-assign]

    # -- tools --------------------------------------------------------------

    def resolve_name(self, name: str) -> ToolResult:
        """resolve_name: 天体名 -> ICRS 坐标 (CDS Sesame 代理)。

        工具契约: 输入一个天体名 (如 ``"M31"``), 返回解析出的
        ra/dec/on_axis 等字段; 无结果时 NameResolveError 映射为
        ``E_NAME_UNRESOLVED``, 输入空串等非法值按 ValueError 映射为
        ``E_INVALID_INPUT``。

        参数校验: 只做"传得下去"的最小校验 — 类型/空值检查由
        ``BestClient.resolve_name`` 与协议层负责 (单一事实源), 工具层
        不复制第二套校验规则。

        返回 envelope: ``data`` 为 ResolvedName.to_dict() (含坐标与
        来源元信息); ``provenance.session_id`` 为 None (名称解析不建
        查询会话, 没有 sqlid 可续); 站点来源故 ``untrusted=True``;
        ``cost.rows_returned=1`` (名称解析是单值结果, 不是表)。

        Args:
            name: 天体名称 (Sesame 可解析形式)

        Returns:
            统一信封; 失败时 ``status.error_code`` 为 E_NAME_UNRESOLVED /
            E_INVALID_INPUT / E_BACKEND 之一
        """
        started = time.monotonic()  # 入口读数: 耗时字段的起点
        before = self._requests  # 快照: 本次调用只统计自己引发的请求 (成本按调用归因)
        try:
            resolved: ResolvedName = self.client.resolve_name(name)                               # 解析结果带类型标注: 展平形态由领域对象保证
        except Exception as exc:  # noqa: BLE001 - mapped onto the envelope
            # 异常一律收进信封而不是抛出: agent 侧读 error_code 分支即可
            return _error_envelope(exc, started=started,
                                   http_requests=self._requests - before,                           # 成本按本次调用归因: 用入口快照做差
                                   lineage={"source": "nss/solve", "name": name})
        return _envelope(
            resolved.to_dict(),                                                                     # 载荷即解析结果字典: 含坐标与来源元信息
            started=started,                                                                        # 耗时起点: 与异常路径同一读数口径
            http_requests=self._requests - before,                                                  # 本次调用引发的请求数: 快照差值
            rows=1,  # 单值结果, 不是表
            session_id=None,  # 名称解析不建查询会话, 没有 sqlid 可续
            # 稳定 URI 带原始 name 原文: 同一对象名多次解析得到同一 URI,
            # agent 侧可作引用/去重键 (易失 sqlid 不适用于本工具)
            stable_uri=(  # YZ-15: 段形态先过白名单, 非法段不生成句柄 — 不归一化, 归一化会把两个不同名压成同一句柄
                f"best://nss/solve?obj={name}" if _is_safe_uri_segment(name) else ""
            ),
            lineage={"source": "nss/solve", "name": name},  # 血缘标出走的是哪条解析通道
            untrusted=True,  # 站点来源, 按 S-2 显式标注
        )

    def list_catalogs(self) -> ToolResult:
        """list_catalogs: 可查询星表清单与分组 (零请求, 纯本地注册表)。

        工具契约: 无参数; 从协议层注册表 (CATALOG_DISPLAY/CATALOG_PATHS/
        CATALOG_GROUPS) 现场组装, 不发起任何 HTTP 请求 — ``cost``
        区因此 http_requests=0, 这是唯一能离线使用的工具。

        返回 envelope: ``data.catalogs`` 为 [{id, display, query_path}]
        (query_path 供 describe/cone 等下游拼 stable_uri), ``data.groups``
        为分组名到成员 id 列表的映射; 无失败路径 (注册表是编译期常量)。

        Returns:
            统一信封; 恒 ``status.ok=True``, ``cost.http_requests=0``
        """
        started = time.monotonic()  # 零请求工具也照记耗时, 保持信封四字段齐全
        data = {                                                                                    # 载荷容器: 清单与分组一并给出
            "catalogs": [
                {"id": key, "display": value, "query_path": CATALOG_PATHS[key]}
                for key, value in CATALOG_DISPLAY.items()                                         # 逐项组装星表条目: 查询路径供下游拼稳定引用
            ],
            "groups": {key: list(value) for key, value in CATALOG_GROUPS.items()},
        }
        return _envelope(
            data,                                                                                   # 载荷整份出函: 描述类工具走同一构造点
            started=started,                                                                        # 耗时起点: 零请求工具也照记
            # 注册表答案零线网: 成本如实记 0, 不把"读常量"算成请求
            http_requests=0,                                                                        # 成本记零线网: 读常量不算请求
            rows=len(data["catalogs"]),
            stable_uri="best://catalogs",  # 静态 URI: 清单随版本变, 不做内容寻址
            lineage={"source": "src.protocol.CATALOG_PATHS"},  # 指回注册表的单一出处
        )

    def describe_catalog(self, catalog: str) -> ToolResult:
        """describe_catalog: 单个星表的列清单、波段与单位 (零请求)。

        工具契约: 输入星表 id (裸 id, 如 ``"ps1"``; 导航组前缀如
        ``calib/`` 会被协议层拒绝), 返回该表可查询列、星等波段列映射与
        单位说明; 未知 id 由 ``resolve_catalog`` 抛异常, 按
        E_INVALID_INPUT 出函。

        参数校验: 全部委托 ``src.protocol.resolve_catalog`` (权威星表
        解析, 单一事实源); 工具层只做异常到信封的映射, 不自建合法
        星表白名单。

        返回 envelope: ``data.columns`` 为列名列表, ``data.magnitude_bands``
        为波段到星等列的映射 (用于 cone_search 的 band 参数),
        ``data.units_note`` 声明 ra/dec 单位为度、星等为 mag、半径为角秒 —
        单位写进信封, agent 不需要另外查文档。

        Args:
            catalog: 星表 id (裸 id)

        Returns:
            统一信封; 失败时 ``status.error_code=E_INVALID_INPUT``
        """
        started = time.monotonic()  # 零请求: 本地注册表就地作答
        try:
            resolved = resolve_catalog(catalog)  # 权威星表解析, 工具层不私建白名单
        except Exception as exc:  # noqa: BLE001
            # 未知/非法星表 id: 映射为输入错 (调用方改 catalog 即可),
            # 不发任何请求 — 校验在本地完成, 成本记 0
            return _error_envelope(exc, started=started, http_requests=0,
                                   lineage={"catalog": catalog})
        data = {                                                                             # 载荷容器: 描述结果一次给全, 免得 agent 再问
            "catalog": resolved,
            "display": CATALOG_DISPLAY[resolved],
            "query_path": CATALOG_PATHS[resolved],
            "columns": list(CATALOG_COLUMNS[resolved]),
            "magnitude_bands": dict(CATALOG_MAG_COLUMNS.get(resolved, {})),
            "units_note": "ra/dec in degrees; magnitudes in mag; radius in arcsec",
        }
        return _envelope(
            data,                                                                           # 整份出函: 与其它工具同构, agent 只需认一种信封
            started=started,                                                                        # 耗时起点: 本地注册表就地作答
            http_requests=0,  # 全程零线网: 列清单来自编译期常量
            rows=len(data["columns"]),  # 描述类工具: 行数记列数, 便于 agent 读规模
            stable_uri=f"best://{resolved}/describe",  # 按表 id 定址
            lineage={"catalog": resolved},  # 血缘记已归一后的表 id
        )

    def cone_search(
        self,                                                                                       # 实例: 工具集挂在同一个客户端上
        ra: float,                                                                                  # 中心赤经(度): 值域由客户端入口校验
        dec: float,                                                                                 # 中心赤纬(度): 与赤经共同定位天区
        radius_arcsec: float = 180.0,                                                      # 检索半径(角秒): 缺省 180 角秒, 覆盖常规单源邻域
        catalog: str = "ps1",
        columns: Optional[Iterable[str]] = None,                                               # 列投影可空: 只做列表归一, 列名合法性由协议层判
        sort: Optional[str] = None,                                                                 # 排序列可空: 拼错静默退回默认序
        order: str = "asc",
        nearest_only: bool = False,                                                                 # 最近邻开关: 默认关, 交调用方显式要求
        max_rows: int = 1000,                                                                      # 行数预算: 工具层显式封顶, 超出即标截断
    ) -> ToolResult:
        """cone_search: 这个天区里有什么 (服务端原生锥形检索)。

        工具契约: 输入中心坐标 (度, ICRS) 与半径 (角秒), 走 BestClient
        两阶段协议 (POST 建查询会话拿 sqlid -> GET 分页取数), 返回命中的
        源行。行数据来自站点回包, 一律 ``untrusted=True`` (S-2)。

        参数校验 (入口即拒, Q-51): ra/dec 值域、radius 上下限由
        ``BestClient.cone_search`` 委托 ``src.scripts.guards`` 校验 — 越界
        抛 ValueError, 映射为 E_INVALID_INPUT; ``columns`` 只做
        ``list()`` 归一, 列名合法性由协议层在构造 showcol 时判定;
        ``max_rows`` 是工具层显式的行数预算 (透传为 max_records), 超出即
        ``truncated=True``, 由调用方决定是否 fetch_page 续取。

        返回 envelope: ``data.rows`` 为源 dict 列表 (ra/dec/各波段星等),
        ``data.total_count`` 为服务端真实总数, ``data.returned_count`` 为
        本次实际返回数; ``provenance.session_id`` 为 sqlid (后续
        count/fetch_page 的会话句柄); 失败时 error_code 取
        BestClient 已分类的码 (E_NO_SQLID/E_SOFT_404 等), 缺省才回落
        E_NO_SQLID。

        Args:
            ra: 中心赤经 (度, ICRS)
            dec: 中心赤纬 (度, ICRS)
            radius_arcsec: 检索半径 (角秒)
            catalog: 目标星表 (裸 id)
            columns: 可选列投影 (对应协议层 showcol)
            sort: 可选服务端排序列; order 为 asc/desc
            nearest_only: 只保留最近的一个匹配
            max_rows: 行数预算 (截断阈值), 默认 1000

        Returns:
            统一信封; 失败时 ``status.error_code`` 为 E_INVALID_INPUT /
            E_NO_SQLID / E_SOFT_404 / E_BACKEND 之一
        """
        started = time.monotonic()  # 入口读数
        before = self._requests  # 快照: 让成本按本次调用归因
        try:
            result = self.client.cone_search(                                                       # 几何与星表整份传: 一次两阶段协议走完
                ra=ra, dec=dec, radius_arcsec=radius_arcsec, catalog=catalog,                       # 投影与排序同传: 少一项就静默少一项能力
                columns=list(columns) if columns else None,                                         # 列表归一在此做: 协议层只认列表形态
                sort=sort, order=order, nearest_only=nearest_only,                                  # 方向与最近邻同传: 三项共属一次查询面
                max_records=max_rows,                                                        # 行数预算即取回上限: 超出由 agent 决定是否续拉
            )
        except Exception as exc:  # noqa: BLE001
            # 输入非法/网络/站点异常统一进信封; lineage 带全量查询参数,
            # 失败信封也能回答"当时查的是哪个天区"
            return _error_envelope(
                exc, started=started, http_requests=self._requests - before,                        # 失败信封的成本: 已发出的请求照样计入
                lineage={"catalog": catalog, "ra": ra, "dec": dec,
                         "radius_arcsec": radius_arcsec},
            )
        if not result.success:                                                                      # 成功位优先判: 失败信封走单独一支构造
            # BestClient 已把失败分类成稳定 error_code; 优先信它, 不去
            # 嗅探人读消息文本 (消息措辞会随站点改版漂移, 码不会)
            code = result.error_code or E_NO_SQLID                                           # 优先信客户端的码: 不嗅探人读消息, 措辞会随站点漂移
            return _envelope(
                {"error": result.error or ""},  # 人读消息留在 data, 分支只看码
                started=started,                                                                    # 耗时起点: 与异常路径同一读数
                http_requests=self._requests - before,                                              # 成本按本次调用归因: 快照差值
                error_code=code,                                                                    # 错误码: 缺省才回落无会话号那一支
                lineage={"catalog": catalog, "ra": ra, "dec": dec,
                         "radius_arcsec": radius_arcsec},
                untrusted=True,  # P0-08: result.error 可能内嵌站点回包文本, 失败信封与成功信封同一口径
            )
        rows = [source.to_dict() for source in result.sources]  # 领域对象展平成行字典
        data_payload: dict[str, Any] = {                                                                  # 载荷容器: 三项分别是行、总数与实返
            "rows": rows,
            "total_count": result.total_count,  # 服务端真实总数, 不受 max_rows 影响
            "returned_count": result.returned_count,  # 本次实返: 与 total 的差即被截掉的部分
        }
        if result.truncated:  # YZ-44: 截断成因上浮, 布尔契约不变
            data_payload["truncated_reason"] = _truncation_reasons(result)  # 成因清单: 布尔位之外的机器可读依据
        return _envelope(
            data_payload,
            started=started,                                                                        # 耗时起点: 失败信封与成功路径同一读数口径
            http_requests=self._requests - before,                                                  # 成本按本次调用归因: 异常前已发出的请求也算在内
            rows=len(rows),                                                                     # 行数取实返条数: 与总数分开, 差值即被截掉部分
            truncated=result.truncated,  # 透传站点截断位, 由 agent 决定是否 fetch_page
            # session_id 记 sqlid: count/fetch_page 凭它续用同一查询会话,
            # 不必重新 POST 表单
            session_id=result.query_params.get("sqlid"),
            stable_uri=(                                                                          # 坐标入稳定引用: 同一坐标的多次查询天然去重
                f"best://{catalog}/cone?ra={ra}&dec={dec}&sr={radius_arcsec}"
                # YZ-15: catalog 段过形态校验, 脏段不拼句柄; 数值段已上方 guards 约束值域
                if _is_safe_uri_segment(catalog) else ""
            ),
            lineage={"catalog": catalog, "ra": ra, "dec": dec,
                     "radius_arcsec": radius_arcsec},
            untrusted=True,  # 行数据来自站点回包, 按 S-2 标注
        )

    def crossmatch_batch(
        self,                                                                                       # 实例: 批量匹配与其它工具同一信封
        coords: list[dict[str, Any]],                                                               # 坐标字典列表: 每项至少含数值型赤经赤纬
        catalog: str = "ps1",
        radius_arcsec: float = 3.0,                                                         # 匹配半径(角秒): 缺省三角秒, 与交叉匹配常规口径一致
        nearest_only: bool = True,                                                                  # 最近邻默认开: 批量匹配的常规诉求
        columns: Optional[Iterable[str]] = None,                                                    # 列投影可空: 少传一项就静默少一列
        max_rows: int = 50000,                                                                      # 行数预算: 工具层显式封顶
    ) -> ToolResult:
        """crossmatch_batch: 一次服务端调用批量匹配多个坐标。

        工具契约: 输入 ``[{"ra":..,"dec":..,"id":..}, ...]``, 走
        BestCrossMatch 的 proximity 批量路径 (单次上传坐标表, 服务端
        匹配), 避免逐坐标锥搜把一次匹配放大成 N 次线网请求。匹配行来自
        站点回包, ``untrusted=True``。

        参数校验 (入口即拒, 不进协议层): 每个元素必须含数值型
        ``ra``/``dec`` — 缺键/类型错/非数值一律 E_INVALID_INPUT; ``id``
        可选, 缺省用输入下标 (``str(index)``) 保证行可追溯回输入。
        缺失坐标绝不能静默当作 (0,0) — 那是一个真实天区 ——
        那样脏输入会悄无声息地查到赤道原点, 故这里显式抛错。

        返回 envelope: ``data.rows`` 为匹配源列表, ``data.n_inputs`` 为
        输入坐标数 (与 returned_count 对照可见匹配率), ``data.mode`` 为
        服务端实际模式 (缺省 proximity); ``provenance.session_id`` 为
        sqlid, 可用 count/fetch_page 续取; 失败码: 输入问题
        E_INVALID_INPUT, 协议/站点问题 E_SOFT_404/E_BACKEND。

        Args:
            coords: 坐标 dict 列表, 每项需 ``ra``/``dec`` (度), 可选 ``id``
            catalog: 目标星表 (裸 id)
            radius_arcsec: 匹配半径 (角秒), 默认 3.0
            nearest_only: 每个输入只保留最近匹配 (默认 True)
            columns: 可选列投影
            max_rows: 行数预算 (截断阈值), 默认 50000

        Returns:
            统一信封; 失败时 ``status.error_code`` 为 E_INVALID_INPUT /
            E_SOFT_404 / E_BACKEND 之一
        """
        started = time.monotonic()  # 入口读数
        before = self._requests  # 快照: 拆包阶段的零成本也按本次调用归因
        try:
            # 坐标拆包先于任何请求: 输入畸形时零线网成本即失败,
            # 不浪费一次站点往返
            ra_list = [float(item["ra"]) for item in coords]
            dec_list = [float(item["dec"]) for item in coords]
        except (KeyError, TypeError, ValueError) as exc:
            return _error_envelope(exc, started=started, http_requests=0,  # 拆包失败: 确定零请求
                                   lineage={"catalog": catalog, "n_inputs": len(coords)})
        # id 缺省取输入下标: 行数据回传后仍可指回"是哪个输入匹配上的"。
        # 逐级 `is None` 判定而非 `.get` 默认值 —— `.get("id", index)` 只在
        # **键缺失**时回落, 值是 None 时原样返回 None, `str(None)` 于是把
        # Python 关键字 None 变成字面串 "None" 混进 source_id 前缀
        # ("None -> ps1_123"): 真实 id 被吞, 且这个前缀与合法 id 无法区分,
        # 是比缺前缀更难发现的错挂 (G1-07 同形缺陷)。空串/纯空白同样视作缺失:
        # 空 id 拼出来的是 " -> ps1_123" 这种无主前缀, 一样不可追踪。
        id_list: list[str] = []  # 逐行收集: 长度与 ra_list/dec_list 严格对齐
        n_fallback = 0  # 走下标兜底的行数: 脏输入必须留痕, 不静默换名
        for index, item in enumerate(coords):  # 逐坐标收集: 下标即最终兜底标识
            raw_id = item.get("id")  # 首选调用方给的 id
            if raw_id is None:  # 键存在但值为 None 也算缺失 —— 这正是 .get 默认值漏掉的一支
                raw_id = item.get("source_id")  # 次选 source_id: 与 crossmatch 侧的三级兜底同序
            if raw_id is None or not str(raw_id).strip():  # None 与空串/纯空白都判缺失
                raw_id = index  # 最后落到输入下标: 至少还能指回"是哪个输入"
                n_fallback += 1  # 计数而非静默: 事后能从日志看出有多少行是兜底名
            id_list.append(str(raw_id))  # 统一转字符串: 数字 id 也要与下标兜底走同一形态
        if n_fallback:
            # 告警而非抛错: id 脏不该让整批匹配消失 (坐标是有效的), 但绝不
            # 静默把 None 变成 "None" 前缀混进结果行 (铁律 5: 目标缺失不静默跳过)。
            logger.warning(  # 一批一条: 逐行 warn 会把 1000 坐标的日志刷爆
                "crossmatch_batch: %d/%d inputs had no usable id; "
                "labelled by input index instead", n_fallback, len(coords),
            )
        try:
            result = self.crossmatch.crossmatch_batch(                                              # 坐标表整份传: 一次上传换全部匹配
                ra_list, dec_list, catalog=catalog, radius_arcsec=radius_arcsec,                    # 几何与星表随行传: 与逐点路径同口径
                id_list=id_list, columns=list(columns) if columns else None,                        # 标识列投影同传: 少传一项就静默少一列
                nearest_only=nearest_only, max_rows=max_rows,                                       # 最近邻与上限同传: 少传就静默少一项能力
            )
        except Exception as exc:  # noqa: BLE001
            return _error_envelope(
                exc, started=started, http_requests=self._requests - before,                        # 异常路径的成本: 已发出的请求照样计入
                lineage={"catalog": catalog, "n_inputs": len(coords)},
            )
        if not result.success:                                                                      # P0-07: 成功位优先判 —— 与同文件 cone_search 同一写法
            # 不判这一位, "上传作业失败"与"这批坐标真的零匹配"会被压成逐字节
            # 相同的信封 (连 provenance.data_hash 都碰撞), agent 无从分辨, 于是把
            # 站点故障当物理事实上报且不重试 (AA8 首报, Y1/Y2 同源)。
            return _envelope(
                {"error": result.error or ""},  # 人读消息留在 data, 分支一律看码
                started=started,
                http_requests=self._requests - before,
                error_code=result.error_code or E_BACKEND,                                          # 优先信客户端的稳定码: 不嗅探人读消息, 措辞会随站点漂移
                lineage={"catalog": catalog, "n_inputs": len(coords)},
                untrusted=True,  # P0-08: result.error 可能内嵌站点回包文本
            )
        rows = [source.to_dict() for source in result.sources]  # 展平为行字典
        data_payload: dict[str, Any] = {                                                                    # 载荷容器: 输入数与实返数对照即可读出匹配率
            "rows": rows,
            "total_count": result.total_count,
            "returned_count": result.returned_count,
            "n_inputs": len(coords),  # 与 returned_count 对照即可读出匹配率
            "mode": result.query_params.get("mode", "proximity"),  # 服务端实际走的模式
        }
        if result.truncated:  # YZ-44: 截断成因上浮, 与 fetch_page 同一口径
            data_payload["truncated_reason"] = _truncation_reasons(result)  # 成因清单: 布尔位只说"没取全", 这里说"为什么没取全"
        return _envelope(
            data_payload,
            started=started,                                                                        # 耗时起点: 批量匹配走同一读数口径
            http_requests=self._requests - before,                                               # 成本按本次调用归因: 拆包阶段的零成本也算在内
            rows=len(rows),                                                                     # 行数取匹配条数: 与输入数分开, 差值即未匹配数
            truncated=result.truncated,  # 透传截断位, 供 agent 判断是否续拉
            session_id=result.query_params.get("sqlid"),  # 记 sqlid 以便 count/fetch_page 续用
            stable_uri=(  # YZ-15: catalog 段过形态校验; n 与 r 是数值与长度, 不含分隔符
                f"best://{catalog}/proximity?n={len(coords)}&r={radius_arcsec}"
                if _is_safe_uri_segment(catalog) else ""
            ),
            lineage={"catalog": catalog, "mode": "proximity",
                     "n_inputs": len(coords), "radius_arcsec": radius_arcsec},
            untrusted=True,  # 匹配行来自站点回包, 按 S-2 标注
        )

    def count(self, sqlid: str) -> ToolResult:
        """count: 查询会话的服务端真实命中总数 (GET getcount)。

        工具契约: 输入 cone_search/crossmatch 返回的 sqlid, 返回服务端
        对同一会话统计的真实总行数 — 用于在拉数据前判断"值不值得拉"
        (总数 0 直接放弃, 远大于预算则收窄约束), 避免盲拉全量。

        参数校验: ``sqlid`` 先过 ``protocol.normalize_sqlid`` 白名单, 与
        :meth:`fetch_page` 同一口径 (YZ-16 的姊妹缺口 — count 是另一个公开
        缝, 此前把入参原样传给客户端, 归一只发生在客户端内部, 于是本函数
        拼 stable_uri / 记 lineage 时拿到的仍是**未归一原文**)。

        返回 envelope: ``data`` 为 ``{"sqlid":.., "total": N}``, ``sqlid``
        是**归一后**的值 (与实际发出的请求同一份, 调用方拿它续页必然对得上);
        ``provenance.session_id`` 同为归一值; ``cost.rows_returned`` 记
        total (计数值, 非行数据); 无站点行数据, 故不标 untrusted。

        Args:
            sqlid: 查询会话标识 (两阶段协议第一阶段的产物)

        Returns:
            统一信封; 失败时 ``status.error_code`` 为 E_INVALID_INPUT /
            E_BACKEND
        """
        started = time.monotonic()  # 入口读数
        before = self._requests  # 快照: 成本按本次调用归因
        try:
            sqlid = normalize_sqlid(sqlid)  # 工具边界先归一: 载荷/血缘/句柄三处都用这一份, 不混原文
            total = self.client.count(sqlid)  # 服务端真实总行数 (GET getcount)
        except Exception as exc:  # noqa: BLE001
            return _error_envelope(exc, started=started,
                                   http_requests=self._requests - before,                           # 异常路径的成本: 计数请求本身也计入
                                   lineage={"sqlid": sqlid})
        # YZ-14: total 为 None 或非 int 时与"0 行"不可区分 — 上游计数降级后
        # 信封仍须让调用方知道这不是一次"完整可信的计数"。在 status 里显式追加
        # degraded 位与原因, 不破坏 ok 布尔契约 (计数端点本身成功回来了, 只是
        # 数字不可信), 也不把 None 隐式转成 0 (0 会被读成"服务端确认 0 行").
        is_degraded = total is None or not isinstance(total, int)  # YZ-14: 非整数计数即判降级, 不隐式记 0 浑水摸鱼
        status_extra: dict[str, Any] = {}
        if is_degraded:  # YZ-14: 降级走单独状态分支, 让 agent 能把"计数未知"与"0 行"分开
            status_extra = {"degraded": True, "degraded_reason": "total_not_available"}  # 降级标记随 status 走: 不污染 data.total 的原始形态
        return _envelope(
            {"sqlid": sqlid, "total": total},  # data.total 原样暴露: None 与 0 在外层可区分, 不调包成 0
            started=started,                                                                        # 耗时起点: 与成功路径同一读数
            http_requests=self._requests - before,                                                  # 成本按本次调用归因: 计数请求本身也计入
            # YZ-14: total 非 int 时 rows 仍记 0 以维持成本字段 int 契约, 但
            # 信封 status 已带 degraded 位, 调用方应优先读 status.degraded
            rows=total if isinstance(total, int) else 0,                                    # 非整数记零: 成本字段保持整数契约, 降级由 status 显式标注
            session_id=sqlid,  # 复用入参 sqlid, 本工具不建新会话
            stable_uri=(  # YZ-15: sqlid 段先过形态校验, 脏段不拼句柄
                f"best://sqlid/{sqlid}/count" if _is_safe_uri_segment(sqlid) else ""
            ),
            lineage={"sqlid": sqlid},  # 血缘只有会话号: 本工具不接收查询参数
            extra_status=status_extra or None,  # YZ-14: 降级位原样进 status; 非降级路径不携带
        )

    def fetch_page(
        self,                                                                                       # 实例: 续拉页也走同一信封
        sqlid: str,                                                                                 # 会话标识: 凭它续用同一查询会话
        page: int = 1,                                                                              # 页码从 1 起: 越界即入参非法
        page_size: int = 1000,                                                                      # 页大小: 上限与工具声明的接口契约一致
        catalog: str = "",
        max_rows: Optional[int] = None,                                                        # 行数预算可空: 缺省取页大小, 单次调用不跨页累积
    ) -> ToolResult:
        """fetch_page: 显式续拉查询会话的某一页 (两阶段协议第二阶段)。

        工具契约: cone_search/crossmatch 因 ``max_rows`` 截断后, 凭
        sqlid 按页续取, 不必重新 POST 表单重建会话。行数据来自站点回包,
        ``untrusted=True``。

        参数校验 (全部落在本工具边界, 协议层不校验分页边界):
        ``sqlid`` 先过 ``protocol.normalize_sqlid`` 白名单 (YZ-16 —
        该白名单此前被 fetch_page 公开缝绕过, 脏 sqlid 会原样进 URL);
        ``page``/``page_size`` 必须是**严格的 int 且非 bool** (YZ-18 —
        ``int(1.5)=1`` 会把非整数页号静默取整后原样进 URL, bool 同理);
        ``1 <= page_size <= ``MAX_FETCH_PAGE_SIZE`` (=10000, 与
        tools.schema.json 的 maximum 一致, 越界即 ValueError ->
        E_INVALID_INPUT); ``max_rows`` 显式传入时必须是正整数且不超过
        ``MAX_FETCH_PAGE_SIZE`` (YZ-03/YZ-04 — 此前 max_rows 无上限,
        单次调用可驱动无界翻页, <=0 与非整数也静默通过);
        ``max_rows`` 缺省取 ``page_size`` — 单次调用的行数预算默认与
        页大小一致, 调用方要跨页累积时显式传更大值; ``catalog`` 可空
        (仅少数站点行为需要按表路由时传)。

        返回 envelope: ``data.rows`` 为本页源行, ``data.page`` 回显页码,
        ``data.returned_count``/``data.total_count`` 供调用方判断是否还有
        下一页; ``truncated`` 表示本页即达到 max_rows 预算,
        ``data.truncated_reason`` 在 truncated 时给出截断成因清单 (YZ-44 —
        布尔位只说"没取全", 成因清单才说"为什么没取全");
        ``provenance.session_id`` 为 sqlid (与 count 一致, 可继续续页)。

        Args:
            sqlid: 查询会话标识
            page: 页码 (从 1 开始)
            page_size: 每页行数 (默认 1000)
            catalog: 可选星表 id (留空由协议层按 sqlid 推断)
            max_rows: 单次调用行数预算; None 时取 page_size

        Returns:
            统一信封; 失败时 ``status.error_code`` 为 E_INVALID_INPUT /
            E_SOFT_404 / E_BACKEND 之一
        """
        started = time.monotonic()  # 入口读数
        before = self._requests  # 快照: 成本按本次调用归因
        try:
            # 全部边界校验都在发请求前完成: 任何一条不过即 ValueError ->
            # E_INVALID_INPUT, 非法值绝不进 URL 查询串。
            # YZ-16: sqlid 先过协议层白名单 — fetch_page 公开缝此前把脏 sqlid
            # 原样拼进 /sqlid 分页路径, normalize_sqlid 的防线被整条绕过。
            sqlid = normalize_sqlid(sqlid)  # 归一后再用: 白名单只认 s?\d+ 形态
            # YZ-18: page/page_size 必须严格是 int 且非 bool — bool 是 int 的
            # 子类, isinstance(True, int) 为真, 不排掉会把 True 当 1 放行;
            # int(1.5)=1 的静默取整同理, 所以先判类型再判边界, 顺序不可换。
            if isinstance(page, bool) or not isinstance(page, int):  # 先拒类型再拒边界: bool/非整数都在此拦
                raise ValueError(f"page must be an int (got {type(page).__name__})")  # 类型错: 不报值域报类型, 便于调用方定位
            if isinstance(page_size, bool) or not isinstance(page_size, int):  # 页大小同口径: 非整数原样进 URL 会把 rows=1.5 发给站点
                raise ValueError(f"page_size must be an int (got {type(page_size).__name__})")
            if page < 1:                                                              # 页号边界在此补齐: 协议层不校验, 声明与实现会脱节
                raise ValueError(f"page must be >= 1 (got {page})")  # 页号从 1 起
            if not 1 <= page_size <= MAX_FETCH_PAGE_SIZE:                                     # 页大小越界即拒: 不把非法值原样送进查询串
                raise ValueError(  # 越界即 ValueError -> E_INVALID_INPUT
                    f"page_size must be in [1, {MAX_FETCH_PAGE_SIZE}] "
                    f"(got {page_size})")
            # YZ-03/YZ-04: max_rows 显式传入时同口径校验 — 此前它无上限且
            # <=0/非整数全部静默通过, 单次调用可驱动无界翻页 (YZ-03);
            # 缺省 None 时回落 page_size 的既有口径不变。
            if max_rows is not None:  # 显式传入才校验: None 走缺省回落, 不被误拒
                if isinstance(max_rows, bool) or not isinstance(max_rows, int):  # 同 YZ-18: bool 与非整数都拒
                    raise ValueError(f"max_rows must be an int (got {type(max_rows).__name__})")
                if not 1 <= max_rows <= MAX_FETCH_PAGE_SIZE:  # 上限与页大小同口径: 单次调用的预算不应超过单页上限
                    raise ValueError(
                        f"max_rows must be in [1, {MAX_FETCH_PAGE_SIZE}] "
                        f"(got {max_rows})")
            result = self.client.fetch_page(                                                        # 会话号传首位: 续取不重新提交表单
                sqlid,                                                                              # 页码下传: 与页码起点约定一致
                page=page,                                                                          # 页大小下传: 末页自然不足一页
                page_size=page_size,                                                               # 星表可空: 少数站点行为需要按表路由时才传
                catalog=catalog,
                max_rows=max_rows if max_rows is not None else page_size,  # 预算缺省与页大小一致
            )
        except Exception as exc:  # noqa: BLE001
            return _error_envelope(exc, started=started,
                                   http_requests=self._requests - before,                           # 异常路径的成本: 已发出的请求照样计入
                                   lineage={"sqlid": sqlid, "page": page})
        if not result.success:                                                                      # P0-07: 成功位优先判 —— 与同文件 cone_search 同一写法
            # 续拉页失败 (会话过期 / 软 404 / 分页中断) 若不判这一位, 就与"这一页
            # 恰好是空的"同形: agent 读到 ok=True + 0 行, 会判成"会话已取尽"而
            # 停止续拉, 静默少收数据。
            return _envelope(
                {"error": result.error or ""},  # 人读消息留在 data, 分支一律看码
                started=started,
                http_requests=self._requests - before,
                error_code=result.error_code or E_NO_SQLID,                                         # 续取失败缺省归"无可用会话": 与该工具的语义最近
                lineage={"sqlid": sqlid, "page": page},
                untrusted=True,  # P0-08: result.error 可能内嵌站点回包文本
            )
        rows = [source.to_dict() for source in result.sources]  # 展平为行字典
        data_payload: dict[str, Any] = {                                                                # 载荷容器: 本页行数与会话总数并列
            "rows": rows,
            "returned_count": result.returned_count,  # 本页实返行数
            "total_count": result.total_count,  # 会话总数: 与本页对照判断是否还有下一页
            "page": page,  # 回显页码, 便于调用方拼下一页请求
        }
        if result.truncated:  # YZ-44: 截断时成因上浮到 data, 与 truncated 布尔位共存 (布尔契约不动)
            data_payload["truncated_reason"] = _truncation_reasons(result)  # 成因清单: 布尔位说"没取全", 这里说"为什么没取全"
        return _envelope(
            data_payload,
            started=started,                                                                        # 耗时起点: 续拉页与其它工具同一读数口径
            http_requests=self._requests - before,                                                  # 成本按本次调用归因: 续拉页与其它工具同口径
            rows=len(rows),                                                                       # 行数取本页条数: 与总数分开, 差值即剩余页
            truncated=result.truncated,  # 本页即触顶预算时为真
            session_id=sqlid,  # 与 count 同口径, 可继续续页
            # YZ-15: sqlid 段过形态校验; page/page_size 已过上方严格 int 校验, 值域可控。
            # f-string 与 stable_uri 同行是**门禁要求**, 不是排版偏好: 分页串自建
            # 双链门 (test_gate_blindspots) 以"含 page={ 且不含 stable_uri"逐行判,
            # 拆成多行会让 `page={` 落到没有 stable_uri 字样的那一行而误判成抓取路径。
            stable_uri=(f"best://sqlid/{sqlid}?page={page}&rows={page_size}" if _is_safe_uri_segment(sqlid) else ""),
            lineage={"sqlid": sqlid, "page": page, "page_size": page_size},  # 复核时据此重放本页
            untrusted=True,  # 行数据来自站点回包, 按 S-2 标注
        )


# 公开工具面 (方法名 -> 调用入口): agent 侧按名分发, 名字即契约。
# describe_catalog 与 list_catalogs 从已验证注册表就地作答, 零请求;
# 其余五个各自是一次对 src.client / src.crossmatch 的调用。
TOOL_NAMES: tuple[str, ...] = (  # agent 侧按名分发的契约清单: 名字即接口
    "resolve_name",
    "list_catalogs",
    "describe_catalog",
    "cone_search",
    "crossmatch_batch",
    "count",
    "fetch_page",
)
