"""src.provenance — 跨节点信封与血缘头实现 (Phase 6, Q-08 接线路线)。

能力边界: 按 contracts/provenance.contract.yaml 与 contracts/envelope.contract.yaml
构造双态信封 (data/decision): 结果 data_hash (SHA-256, 可复核) + session_id +
NADC OAuth 身份 (umtId/ldap_id, 若已授权) + lineage 上下游引用。
Q-08 不变量: 本模块必须提供真实构造注入点 — 只有 YAML 契约与空模型的接线不算实现。
"""
from __future__ import annotations

# 标准库: SHA-256 摘要 (data_hash) / 规范化 JSON 序列化 / 降级告警日志 /
# session_id 生成 (uuid4) / UTC 时间戳 / 类型标注
import hashlib
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

# 本地: NADC OAuth 身份层 (src.auth 门面) — OAuthProfile 显式身份优先,
# TokenStore 令牌缓存兜底; 跨的是"身份授权"这条能力边界, 本文件不直连
# nadc_oauth 实现细节
from src.auth import OAuthProfile, TokenStore

# 模块级 logger: 身份解析失败等"降级但不阻断主链"的事件走 warning,
# 供事后复核"是未授权还是授权服务不可达"
logger = logging.getLogger(__name__)  # 降级告警的唯一出口: 靠它把"未授权"与"服务故障"分开


def compute_data_hash(payload: Any) -> str:
    """对任意可 JSON 化载荷计算确定性 SHA-256 (排序键, 无空白差异)。

    "可复核"的含义: 规范化 JSON (``sort_keys`` + 紧凑分隔符) 把同一份
    载荷压成唯一字节序列, 因此任何一方拿到信封里的 ``data_hash`` 都能用
    同一算法重算并逐位比对, 判断结果是否被篡改、截断或在传输中变了样 —
    哈希不依赖 dict 键序、缩进或空白, 只依赖内容本身。

    失败语义: 载荷含不可 JSON 化对象 (datetime/枚举/自定义类) 时
    ``json.dumps`` 直接抛 TypeError, 本函数不兜底 — 调用方应先把模型
    结果转成 dict (见 :func:`envelope_for_result`), 让"什么能被寻址"
    保持显式。

    Args:
        payload: 任意可 JSON 化载荷 (通常是结果 dict)

    Returns:
        64 位小写十六进制 SHA-256 摘要
    """
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False,  # 排序键是关键: 同一载荷在任何机器上压出同一串字节, 哈希才可比
                           separators=(",", ":"))                        # 排序键 + 紧凑分隔符: 同一载荷在任何机器上压出同一串字节
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()          # 直接对 UTF-8 字节取摘要, 不再二次编码


# 进程级 session id: 同一次运行内构造的多个信封可归为同一会话组。
# 惰性初始化后进程内只 mint 一个 UUID4 并复用: 每次调用都换 id 会让血缘无法
# 按会话聚合, "哪些信封属于同一次运行"就无从回答
_SESSION_ID: Optional[str] = None  # 惰性初始化: 进程内复用同一 id, 血缘才能按会话聚合


def current_session_id() -> str:
    """返回本进程的 session_id (首次调用生成, 之后复用)。

    复用语义是血缘可聚合的前提: 一次流水线里 ``build_envelope`` 会被调
    多次, 若每次换 id, 下游就无法把散落各处的信封还原成一次完整执行。
    """
    global _SESSION_ID                             # 必须 global: 惰性缓存要写回模块级槽位, 否则每次调用都重新 mint
    if _SESSION_ID is None:  # 只在首次生成: 之后一律复用, 血缘才能按会话聚合
        _SESSION_ID = str(uuid.uuid4())  # 用随机四段式: 跨进程也不会撞出同一个会话标识
    return _SESSION_ID


def reset_session_id() -> str:
    """强制轮换 session_id (测试/新会话边界用)。

    两类调用方: 测试需要每个用例拿到干净会话, 避免跨用例串组; 长驻进程
    (MCP server) 开始一次新的用户会话时应显式轮换, 而不是继续沿用上一
    个会话的 id 造成血缘错归。
    """
    global _SESSION_ID                             # 同一槽位: 轮换与惰性生成互斥, 写回别处等于没轮换
    _SESSION_ID = str(uuid.uuid4())  # 强制轮换写回同一槽位: 换槽位等于压根没轮换
    return _SESSION_ID


def identity_from_token_store(store: Optional[TokenStore] = None) -> dict[str, Any]:
    """从 token 缓存取 NADC 身份 (未授权/过期返回空 dict, 不阻断主链)。

    身份解析失败会记日志: 一个静默的空 identity 让人无法判断"未授权"还是
    "授权服务不可达", 信封因此不可复核。

    Args:
        store: 可注入的 TokenStore (测试替身); 缺省构造默认缓存实例
            (``~/.astro-best/nadc_token.json``)

    Returns:
        身份 dict (umtId/ldap_id/name); 未授权、无缓存或解析失败时返回 {}

    失败语义: 本函数不抛异常 — 身份缺失是降级条件而非错误, 匿名可查的
    星表不应因未授权而整体不可用; 但每次降级都留 warning 痕迹。

    边界: 需要"保证有身份"的长跑调用方 (>3600 s, token 寿命) 不走本函数
    — 过期时应经 :func:`src.auth.ensure_access_token` 恢复 (有交互通道传
    reauth 自动重走授权, 无通道抛 ``TokenExpiredError`` 带恢复命令)。
    本函数的降级语义 (身份块整块省略) 是匿名可查场景的正确行为, 它不是
    token 过期的恢复路径, 两者分工见 references/auth-and-oauth.md §5。
    """
    store = store or TokenStore()                  # 缺省构造真实缓存; 注入替身只要有上面两个方法即可
    # 过期即视为未授权: 过期令牌换 profile 只会拿到 401, 直接短路少一次
    # 无效请求 (is_expired 无缓存时也判 True, 与"未授权"同一路径)
    if store.is_expired():                         # 过期按未授权处理: 省掉一次注定 401 的往返
        return {}
    token = store.valid_token()                    # 空令牌 (缓存损坏/已撤销) 同样按未授权, 信封照常可构造
    # 空令牌 (缓存损坏/已撤销) 同样按未授权处理, 保证信封仍可构造
    if not token:  # 空令牌按未授权处理: 信封仍可照常构造
        return {}
    try:
        # 延迟导入 get_profile: 只在真正需要身份时才触碰 OAuth 侧依赖,
        # 让本模块其余功能 (哈希/信封/血缘) 在离线环境仍可导入使用
        from src.auth import get_profile

        profile = get_profile(token)               # 真发网络请求的只有这一行: 上游短路全在它之前
    except Exception as exc:  # noqa: BLE001 - 记录后按未授权继续
        # 降级不阻断: 授权服务不可达不能让查询整体失败, 但必须留告警 —
        # 否则"未授权"与"服务故障"在信封里长得一模一样, 复核者无法区分
        logger.warning("NADC profile lookup failed; envelope identity left empty: %s", exc)  # 降级必留告警: 否则未授权与服务故障在信封里长得一模一样
        return {}                                  # 留完告警才降级: 空 identity 也带可追溯痕迹
    return profile.to_dict()


def build_envelope(
    data: Any,  # 结果载荷: 哈希覆盖的正是随信封传递的这份内容
    status: str = "ready",  # 结果状态: 复核者据此判断数据能否直接消费
    session_id: Optional[str] = None,  # 显式会话标识优先: 调用方可跨进程把信封归到一组
    inputs_ref: Optional[list[str]] = None,  # 上游引用记哈希而非路径: 路径会随缓存目录与重命名变化
    outputs_ref: Optional[list[str]] = None,  # 下游引用同理: 让本节点的产物也能被上游寻址
    profile: Optional[OAuthProfile] = None,  # 显式授权态优先于缓存: 它代表最近一次授权的结果
    identity: Optional[dict[str, Any]] = None,  # 身份直给: 供调用方复用已解析的身份, 免得再读一次缓存
    completeness: Optional[dict[str, Any]] = None,  # 完整性门的真实判定: 缺省只给诚实兜底, 不硬编码假门禁
) -> dict[str, Any]:
    """构造 astro-envelope-v1 双态信封 (data 态)。

    "可复核"的三件套:

    - ``data_hash`` — 结果内容寻址 (SHA-256), 任何人可用同一算法重算比对;
    - ``session_id`` — 同一次运行的归组线索, 把散落各处的信封还原成一次
      完整执行;
    - ``lineage.inputs_ref`` — 输入路径以**上游 data_hash 引用链**记录,
      而非可变文件路径: 路径会随缓存目录/重命名变化, 哈希不会, 上游内容
      一变引用即刻失配, 因此"结果从哪来"可沿链回溯验证。

    已授权时 ``provenance.identity`` 落 NADC 身份 (umtId/ldap_id), 回答
    "谁取的数"; 未授权时整块省略, 不落空块。

    Args:
        data: 结果载荷 (将计算 data_hash)
        status: ready/needs_review/...
        session_id: 缺省用本进程 session_id
        inputs_ref/outputs_ref: 血缘引用 (data_hash 列表)
        profile: NADC OAuth profile (优先); 缺省尝试 token 缓存
        identity: 直接给身份 dict (profile 缺省时用)
        completeness: 完整性门的真实判定 (``{"required": True, "value": x}``);
            缺省时按载荷是否为空给出诚实值, 不再硬编码 1.0 假门禁

    Returns:
        信封 dict (provenance 契约形态)
    """
    # profile 优先于 identity: 显式传入的 OAuth 对象代表最新授权态,
    # 直接覆盖调用方可能持有的陈旧 identity dict
    if profile is not None:  # 显式授权档案覆盖身份字典: 后者可能是调用方手里的陈旧值
        identity = profile.to_dict()  # 契约化转换: 身份块字段集由模型层保证, 不在此手拼
    # 两者都缺省才回落 token 缓存; 取不到身份不报错 — 匿名查询仍应拿到信封
    if identity is None:                           # 仅两者皆缺才回落缓存: 匿名可查, 取不到身份也不报错
        identity = identity_from_token_store()  # 两者皆缺才回落缓存: 兜底读盘, 失败也不阻断主链

    if completeness is None:  # 只在没给判定时兜底: 调用方给了真实值就绝不覆盖
        # 诚实默认: 空载荷 = 不完整, 非空 = 1.0。调用方应传真实判定。
        completeness = {"required": True, "value": 1.0 if data else 0.0}  # 空载荷即不完整: 硬编码满值会造出一个从不失败的假门禁

    provenance: dict[str, Any] = {  # 血缘块单独建: 身份块要按有无条件挂进去
        "skill": "astro-best",  # 技能名固定: 复核者据此知道该用哪套口径验哈希
        # UTC ISO-8601 时间戳: 跨节点对时戳; 本地时间会让不同机器上的
        # 信封无法排序, 也无法与站点侧日志对齐
        "timestamp": datetime.now(timezone.utc).isoformat(),  # 统一用 UTC: 本地时间会让跨机器的信封无法排序与对齐
        # 显式 session_id 优先 (调用方可跨进程归组), 否则复用本进程会话
        "session_id": session_id or current_session_id(),  # 显式值优先, 否则复用本进程会话: 散落的信封因此能归组
    }
    # 仅在有身份时落 identity 块: 空 identity 块会被下游误读成
    # "授权过但字段为空", 与"未授权"混淆, 破坏可复核性
    if identity:                                   # 只在真有身份时落块: 空块会被下游读成"授权过但字段为空"
        provenance["identity"] = {  # 挂身份块: 只在真有身份时, 空块会被读成授权过但字段为空
            "umtId": identity.get("umtId", ""),  # 逐字段取: 缺字段落空串, 不让下游在复核时抛 KeyError
            "ldap_id": identity.get("ldap_id", ""),  # 目录账号标识: 授权过就应存在, 空串表示该身份没有此项
            "name": identity.get("name", ""),  # 展示名: 只用于人工复核, 不参与任何判定
        }

    return {
        "schema": "astro-envelope-v1",  # 契约名固定: 下游按它选解析器, 不靠猜字段形态
        "status": status,  # 状态原样透传: 复核者据此决定这份结果能不能直接用
        # data_hash 与 data 同源: 哈希覆盖的正是随信封传递的载荷本身,
        # 收到信封的一方重算 data 即可验证完整性
        "data_hash": compute_data_hash(data),         # 哈希与 data 同源: 收到信封的一方重算 data 就能验完整性
        "data": data,  # 载荷与哈希同源: 收到信封的一方重算就能验完整性
        "provenance": provenance,  # 血缘块整体挂上: 谁在何时用什么身份取的数
        "lineage": {  # 血缘链单独一层: 上下游引用要能被逐环回溯
            # inputs_ref 记上游 data_hash (内容寻址), 不记文件路径:
            # 路径随环境变化, 哈希不随环境变化, 输入链路因此可逐环验证
            "inputs_ref": list(inputs_ref or []),   # 拷贝 + 兜底: 调用方事后改原列表不影响已发出的信封
            "outputs_ref": list(outputs_ref or []),  # 同样拷贝兜底: 调用方事后改原列表不影响已发出的信封
            "completeness_gate": completeness,  # 完整性判定入信封: 复核者据此判断这份结果可不可信
        },
    }


def envelope_for_result(result: Any, **kwargs: Any) -> dict[str, Any]:
    """把 BestQueryResult 包成信封 (to_dict 后计算 data_hash)。

    先转 dict 再哈希: 直接对模型对象 ``json.dumps`` 会因 datetime/枚举等
    类型抛 TypeError; ``to_dict`` 是模型层提供的契约化序列化出口, 保证
    同一结果在任何进程里哈希一致。无 ``to_dict`` 的普通 dict 原样透传。
    """
    payload = result.to_dict() if hasattr(result, "to_dict") else result  # 先契约化再哈希: 模型对象直送 json.dumps 会因 datetime 抛 TypeError
    return build_envelope(payload, **kwargs)
