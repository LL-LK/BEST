# -*- coding: utf-8 -*-
"""evals.groundtruth.run_e2 — E2 编排入口 (query→run→compare→meta→report)。

能力边界: 编排件 — 对每个场景跑查询, 收集规范化结果与信封/provenance/请求计数,
调 metrics 对账, 汇总报告。退出码沿用 eval_runner 约定 (0 全过 / 1 有 fail)。

**只剩实跑 (2026-10-07)**。回放臂 (``--mode replay``) 与它的
``evals/groundtruth/transport.py`` + 11 个快照目录 (20.1 MB) 已整链删除:

- 删除前的逐条判据承接映射: ``docs/REPLAY-RETIREMENT-CRITERIA.md``;
- 完整备份 (可独立还原): ``docs/archive/replay-backup/`` (已推远程)。

**如实登记的失守** (不是悄悄消失, 见口径文档 §3.2):

- **逐行 P/R**: 实跑下没有等价物 —— 实测同一查询快照记 1 行、真站点返 174 行,
  拿会过期的行集比对必然大面积失配。改判**不变量** (主键唯一 / 截断自洽 /
  行数不超预算), 见 :func:`~evals.groundtruth.metrics.m1_rows._live_invariants`。
- **确定性 (M7)**: 站点数据会变, 同一查询两次跑行集本就该不同。M7 降级为
  「请求契约能不能解释全部调用」, 不再声称"同输入同输出"。

:data:`MODE_REPLAY` 常量名留着但**没有实现** —— 这样"这条臂没了"在 grep 里仍可查,
而不会有人误以为还能接线。

限速: :data:`~evals.groundtruth.live_policy.RATE_LIMIT_SECONDS` (1.5s, 铁律 7 (b)
的串行 + 强制间隔)。**归零的那条路随回放一起消失** —— 归零打的是本地文件,
不触网就不存在对站点的礼仪问题; 现在每条请求都出网, 归零等于把站点当压力源。

**默认值的方向**: 库函数与 CLI 的 ``mode`` 缺省**一律 live**。此前是"库函数缺省
replay (离线安全)", 那条规则的前提是回放臂还在; 前置没了, 留着一个指向空实现的
默认只会在有人误传 mode 时炸出难懂的错。

M7 诚实性 (BC-05): ``declared_http_requests`` 不再抄 ``call_count``, 而是按
两阶段契约逐条分类请求轨迹得出 (见
:func:`~evals.groundtruth.live_policy.accounted_calls`)。两侧来自不同观测面,
差值才可能是非零。

白盒锚点: docs/eval-E2-groundtruth.md §9 (执行流程与产物) / §10 (阻断项)。
"""
from __future__ import annotations

# 标准库: 参数/JSON/hash/路径/时钟
import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

# 本地: 中立载体 + canonical/metrics。
# 脚本直跑 (`python evals/groundtruth/run_e2.py`) 时 sys.path[0] 只含本目录,
# 下面把 evals/ 与仓根一并挂上, 脚本入口与 pytest 入口才都 import 得到。
_HERE = Path(__file__).resolve()             # 以本文件反推路径, 不依赖调用时的 cwd
sys.path.insert(0, str(_HERE.parents[1]))   # evals/ (paths 兄弟裸导入)
sys.path.insert(0, str(_HERE.parents[2]))   # skill 根 (evals.* 命名空间包)

# 本地: 兄弟裸导入的 YAML 装载件 (evals/ 在路径上, 与 eval_runner 同约定)
from paths import load_yaml_file  # noqa: E402

# 本地: 规范化层 (四个输出面 → 标准行集; bootstrap 之后才可导入)
from evals.groundtruth.canonical import from_query_result  # noqa: E402

# 本地: 实跑纪律的单一真源 (间隔/重试/请求计数/轨迹分类)
from evals.groundtruth.live_policy import (  # noqa: E402
    RATE_LIMIT_SECONDS,
    CountingSession,
    accounted_calls,
    pace,
)

# 本地: 对账编排与反证自证 (M1–M7 的汇总入口)
from evals.groundtruth.metrics import compare_case, metascore  # noqa: E402

GT_DIR = Path(__file__).resolve().parent     # 本实验根 (编排件与三份资产同级)
SCENARIOS_DIR = GT_DIR / "scenarios"         # 场景 YAML: E2 §5 查询口径的输入
GOLD_DIR = GT_DIR / "gold"                   # 金标准 JSON: 只留语义与不变量, 不含固定行集

MODE_LIVE = "live"      # 放行闸: 直连真站点, 只判不变量
MODE_REPLAY = "replay"  # **历史口径, 2026-10-07 起无实现**: 快照与 transport 已删, 留名只为让"这条臂没了"在 grep 里可查


def _sha256_obj(obj) -> str:
    """对象的确定性 sha256 (排序键 JSON; data_hash 的口径)。"""
    return "sha256:" + hashlib.sha256(         # 前缀固定: 一眼认出"这是行集指纹不是主键 id"
        json.dumps(obj, sort_keys=True, default=str, ensure_ascii=False).encode("utf-8")  # 排序键+不转义: 同一份数据两次哈希必须同值
    ).hexdigest()


def load_scenario(path: Path) -> dict:
    """读场景 YAML (case_id + 查询参数 + 期望状态)。

    ``snapshot_id`` 只对 replay 层是必需: live 层不读快照目录一个字节, 强求它
    只会让场景文件绑死一份与本次跑批无关的旧素材。
    """
    scenario = load_yaml_file(path)                                                      # 坏 YAML / 空文件在此炸, 不让半截 dict 流进对账
    for key in ("case_id", "query"):  # 两个键是对账的全部输入, 缺一后面必然对错行集
        if key not in scenario:                                                               # fail-closed: 缺字段直接停, 不猜默认值 (猜错会让整批对到错的行集上)
            raise ValueError(f"场景缺必需字段 {key}: {path}")
    return scenario


def wire_client(scenario: dict, mode: str = MODE_LIVE):
    """造被测客户端, 返回 ``(client, counter)``。

    2026-10-07: 回放臂已随 ``evals/groundtruth/transport.py`` 与全部快照一并删除
    (备份见 ``docs/archive/replay-backup/``, 承接口径见
    ``docs/REPLAY-RETIREMENT-CRITERIA.md``)。本函数现在是**唯一**接线, 不再按 mode
    分派 —— 参数 ``mode`` 保留是为了让调用点的口径声明继续有效 (它同时决定 M1 走
    不变量还是 P/R), 但**没有第二条分支可走了**。

    失去的判据如实登记: 逐行 P/R 与确定性 (M7) 在实跑下没有等价物, 前者靠
    ``m1_rows`` 的 live 不变量口径补位, 后者降级为"请求契约能不能解释全部调用"。
    这两条失守写在口径文档 §3.2, 不是悄悄消失。

    Args:
        scenario: 场景字典 (实跑臂不再消费它, 保留是为了签名稳定与可读性)。
        mode: 口径声明位, 但**只接受** :data:`MODE_LIVE` —— 传别的值当场抛错。
            它之所以仍是活参数 (而不是被删掉的死签名), 是因为它是这条退役边界的
            唯一机械闸: 回放臂删掉后, 一个还按旧口径写 ``mode="replay"`` 的调用点
            必须**炸**, 而不是被静默当成实跑继续跑 —— 那正是铁律 5 禁的 fail-open。

    Returns:
        ``(BestClient, 计数器)``。计数器统一只暴露 ``call_count`` / ``calls``
        两个成员, 所以下游不必知道底下是回放还是实跑 —— 那是 M7 声明侧
        (:func:`~evals.groundtruth.live_policy.accounted_calls`) 的活。

    限速: live 走 :data:`RATE_LIMIT_SECONDS` (1.5s, 铁律 7 (b) 的串行 + 强制间隔)。

    Raises:
        ValueError: ``mode`` 不是 :data:`MODE_LIVE` 时 —— fail-closed, 不降级。
    """
    if mode != MODE_LIVE:  # fail-closed: 退役口径只炸不降级, 免得旧调用点被静默当成实跑
        raise ValueError(
            f"wire_client 只支持实跑臂; mode={mode!r} 属已退役口径 "
            "(回放臂 2026-10-07 删除, 见 docs/REPLAY-RETIREMENT-CRITERIA.md)")

    # 本地: 被测客户端 (延迟导入 — 只有跑批路径需要, 启动不拖重依赖)
    from src.client import BestClient  # 唯一被测面; 禁的是 gold/ 抄 src, 编排侧接线必须用真客户端

    client = BestClient(rate_limit=RATE_LIMIT_SECONDS)  # 限速不归零: 实跑必须守铁律 7 (b)
    # BestClient 无 session 入参 (会话由它自己按 trust_env=False 建好), 所以这里
    # **包住它自己的会话**而不是另造一个 —— 换掉会丢掉它建的重试适配器与认证头。
    counter = CountingSession(client.session)  # 只计数不改写: 回包一个不少地放行
    client.session = counter                   # 换回去: 被测代码照常用 session.get/post, 无需知道被包了
    return client, counter


def _data_version(mode: str, snap_dir: Path | None = None) -> str | None:
    """数据版本标识 (M6 版本对账的 actual 侧来源)。

    回放臂已于 2026-10-07 整链删除, 所以本函数**恒返 None**: 真站点不提供任何版本
    标识面, 而编一个版本号去和 gold 比对正是本函数当初要防的那件事。M6 据此改判
    「无法对账即不判失败」(见
    :func:`~evals.groundtruth.metrics.m6_version.score_m6`)。

    Args:
        mode: 仅保留以兼容既有调用签名; 本函数不消费它。
        snap_dir: 回放时代的快照目录; 已无来源, 恒不使用。

    Returns:
        恒为 ``None``。
    """
    return None  # 真站点无版本标识面: 留空并让 M6 显式记「不可对账」, 不伪造


def _build_constraints(query: dict, catalog: str) -> list[dict]:
    """场景 query → client 实参的约束表 (``source_id`` 查询在此降级成列约束)。"""
    constraints = list(query.get("constraints") or [])  # 拷一份: 下面追加不改场景 YAML 原件
    if query.get("source_id") and not query.get("ra"):
        constraints.append({                                                                # 按 id 取源降级成等值列约束, 与用户约束同一张表下发
            "name": query.get("source_id_column") or f"{catalog}_source_id",  # 列名可由场景显式声明: xpsp/dr3xpcorr 的主键在共享位置表里, 按 catalog 拼出来的列名不存在
            "op": "equal",                                                                  # 按 id 取源: BEST 无该端点, 降级成等值列约束
            "value": str(query["source_id"]),
        })
    return constraints


def run_scenario_once(scenario: dict, mode: str = MODE_LIVE) -> dict:
    """跑一次查询, 返回规范化结果 + 信封 + provenance + 请求计数。

    查询翻译 (场景 YAML → client 实参):
      - ``source_id`` 且无 ra/dec → 转 equal 列约束 (BEST 无按 id 取源端点,
        E1 已确立; 列名按 ``{catalog}_source_id`` 拼真实投影列);
      - 期望 result_state=error 的场景: 客户端抛错即被测行为本身 —
        捕获后转成 ERROR 态信封 (M5 判据: 拒绝必须显式, 不得降级空结果)。
    """
    client, counter = wire_client(scenario, mode)      # 每场景独立接线, 请求计数不跨场景累加
    query = scenario.get("query") or {}                 # 缺 query 也照发, 让被测自己判非法输入
    catalog = query.get("catalog", "ps1")               # 目录名即投影列前缀 (ps1_* / gaia_*)
    provenance = {                                                                     # provenance 是自报面: 与实测面分列, 版本漂移才看得见
        "mode": mode,                                           # 显式标注接线: 报告读者必须知道这批比的是行集还是不变量
        "snapshot_id": None,                           # 回放臂已删: 恒留 None, 不从场景里取一个已不存在的身份
        "data_version": _data_version(mode),                  # M6 声明面: 真站点无版本标识面, 恒 None 不填
        "catalog": catalog,                                     # 声明面留 catalog, 便于发现"查错目录"
        "endpoint": f"/data/best/{catalog}/q",                  # 声明的端点; 挡串台到别的路径
        "queried_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),    # 抓取时刻: 实跑下"数据是哪一刻的"是判据的一部分
    }
    try:
        if query.get("inputs"):
            # 批量匹配场景: inputs → crossmatch_batch (服务端 proximity 一次提交)
            inputs = query["inputs"]
            result = client.crossmatch_batch(                                           # 批量路径与单查路径不合并: 服务端 proximity 只此一条
                ra_list=[float(i["ra"]) for i in inputs],
                dec_list=[float(i["dec"]) for i in inputs],
                catalog=catalog,
                radius_arcsec=float(query.get("radius_arcsec", 3.0)),  # 场景未给半径时的缺省值
                columns=query.get("columns"),
                max_rows=int(query.get("max_rows", 50000)),  # 只为不撞服务端硬上限, 截断归 M4 判
            )
        else:
            result = client.query_result(                                                   # 单查路径必须走真客户端的正式接口, 不拼 URL 走后门
                catalog=catalog,
                constraints=_build_constraints(query, catalog),
                ra=query.get("ra"),
                dec=query.get("dec"),
                radius_arcsec=query.get("radius_arcsec"),
                max_rows=int(query.get("max_rows", 50000)),  # 默认 5 万远超单页, 末页不满由 M4 兜
                columns=query.get("columns"),
                sort=query.get("sort"),
                order=query.get("order", "asc"),
            )
    except Exception as exc:  # 期望 error 的场景: 异常即被测行为
        rows, envelope = [], {"success": False, "error_code": _error_code(exc),
                              "total_count": None, "returned_count": None,
                              "truncated": None}  # ERROR 态三计数留 None: 不许补 0
        transport_error = _is_transport_error(exc)   # 传输层失败与站点契约错误分开记账
    else:
        rows, envelope = from_query_result(result)  # 规范化层: 四个输出面收敛成标准行集
        transport_error = False                      # 成功路径恒 False: 没有异常就没有传输层失败
    return {
        "rows": rows,                          # 声明面行集: M1 主键、M2 逐格、M3 语义都对它
        "envelope": envelope,                  # 信封面: M4 截断三元组 + M5 状态判定的唯一来源
        "mode": mode,                          # M1 据此选口径 (行集 P/R 还是不变量); 缺省按 replay 判
        "batch_keys": bool(query.get("inputs")),  # 只有 proximity 批量才用 in<N>: 复合主键 (E2 §2)
        "provenance": provenance,              # 声明面: M6 逐字比对, 版本/端点漂移即红
        "transport_error": transport_error,    # M7 的域闸依据: 传输层瞬断不是被测代码的随机性
        **_counts(counter),                   # M7 的两侧观测面, 口径见 live_policy.accounted_calls
    }


def _counts(counter) -> dict:
    """M7 计数两面 (观测侧与声明侧来自**不同**观测面, 差值才可能非零)。"""
    observed = int(getattr(counter, "call_count", 0))  # 观测侧: 计数器说的"一共发了几次"
    declared, unaccounted = accounted_calls(list(getattr(counter, "calls", ())))  # 声明侧: 按两阶段契约逐条分类
    return {
        "observed_http_requests": observed,    # 实测: 报错前的请求数也要留痕
        "declared_http_requests": declared,    # 契约能解释的那几次; 与 observed 同源时 M7 恒真, 那就没有判据了
        "unaccounted_calls": unaccounted,      # 解释不了的调用原样留痕: 报告能指出"多发的是哪一次"
    }


def _error_code(exc: Exception) -> str:
    """异常 → 稳定错误码 (契约前缀优先; 否则按类型归常见码)。

    对齐 contracts/error-codes.contract.yaml 的五码: E_INVALID_INPUT /
    E_SOFT_404 / E_NAME_UNRESOLVED / E_NO_SQLID / E_BACKEND。
    """
    message = str(exc)                                                                     # 只读消息文本判契约码: 客户端没有单独暴露 code 字段
    for code in ("E_SOFT_404", "E_NO_SQLID", "E_NAME_UNRESOLVED",
                 "E_INVALID_INPUT", "E_BACKEND"):
        if code in message:                                                                   # 五码按契约序试匹配, 命中即定, 不再按类型二次推断
            return code  # 契约码优先: 消息里出现即认定, 不再按类型二次推断
    # 本地: 软错误异常类型 (错误信封翻译的判定分支)
    from src.protocol import Soft404Error  # 只认这一个软错类: 其余异常一律按类型兜底

    if isinstance(exc, Soft404Error):                                                          # 软错只认这一个类, 免得把软 404 归成后端故障
        return "E_SOFT_404"    # 类型兜底: 软 404 是软错, 绝不上滑成 E_BACKEND
    if isinstance(exc, ValueError):                                                             # 入参非法归调用方, E4 才能区分用法错与服务挂
        return "E_INVALID_INPUT"  # 入参非法: 归因到调用方, 便于 E4 区分"用法错"与"服务挂"
    return "E_BACKEND"          # 兜底归后端错; 绝不下滑成空结果 (M5 判据)


# 传输层失败的异常类名 (按 MRO 名字判, 不 import requests —— 少一条第三方依赖耦合)。
# 实测样本: requests.exceptions.ConnectionError("Connection aborted.", RemoteDisconnected(...))。
# 覆盖三类: 连接级 (ConnectionError / ProtocolError / RemoteDisconnected)、
# 超时级 (Timeout 及两个子类)、读断级 (ChunkedEncodingError / IncompleteRead)。
_TRANSPORT_EXC_NAMES = frozenset({
    "ConnectionError", "ProtocolError", "RemoteDisconnected",
    "Timeout", "ReadTimeout", "ConnectTimeout",
    "ChunkedEncodingError", "IncompleteRead", "NewConnectionError",
})


def _is_transport_error(exc: Exception) -> bool:
    """异常是否属**传输层**失败 (连接中断 / 超时 / 读断), 而非站点给出的契约错误。

    为什么要单独分一类 (2026-10-10): M7 的确定性半边要求 repeat 次的行集指纹全等,
    而传输层瞬断会让某一轮拿到空行集 —— 那是网络天气, 不是被测代码的随机性。同一
    函数内的 ``http_requests_honest`` 半边早已因同类理由在 ERROR 态记 N/A
    (2026-10-08, 见 :func:`score_m7` docstring), 确定性半边此前漏了这道域闸。

    证据 (两轮全量跑批 + 一次专项探针):
      - 第 1 轮 M7 挂在 ``huge_3700rows``, 第 2 轮挂在 ``boundary_maxrows`` ——
        **换 case 挂**说明是瞬态而非固定缺陷; 两轮 stderr 均见对 ``ps1/q`` 的
        POST 被 ``RemoteDisconnected`` 打断 (POST 按铁律 7 (a) 不重试)。
      - 专项探针 (``temp/e2_m7_probe.py``, 4 个 case × 3 轮实跑) 在**全部轮次都成功**
        时, 有序指纹 / 无序指纹 / 主键集三者**三轮全等** —— 行数据本身是稳的。
      两条合起来指向: 指纹差异来自某一轮被传输层打断, 而不是行集漂移。

    判据只认**异常类型**: 站点回了 HTTP 响应再报出的错 (E_SOFT_404 等契约码) 一律
    不算传输层失败 —— 那是被测行为本身, 不能被这道闸洗掉。
    """
    # 沿 MRO 逐级查: requests 的封装类多继承自 IOError 一族; 命中即认定传输层, 不按消息文本二次推断
    return any(cls.__name__ in _TRANSPORT_EXC_NAMES for cls in type(exc).__mro__)


def run_scenario(scenario: dict, repeat: int = 3, mode: str = MODE_LIVE) -> dict:
    """跑一个场景 (repeat 次, 主结果取首次, data_hashes 供 M7 判确定性)。"""
    hashes, first, states = [], None, []       # states 逐轮记账: M7 的域闸靠它认出被瞬断的那一轮
    for _ in range(max(1, repeat)):                                                           # 至少跑一轮: repeat 传 0 也不允许空跑充数
        outcome = run_scenario_once(scenario, mode=mode)   # 每轮都是完整跑批, 校验层不缓存
        hashes.append(_sha256_obj(outcome["rows"]))   # 逐轮行集指纹: M7 据此判"同一场景同结果"
        states.append({                                    # 逐轮只留判据需要的两面, 不留整份行集 (体积)
            "success": bool((outcome.get("envelope") or {}).get("success")),
            "transport_error": bool(outcome.get("transport_error")),
        })
        first = first or outcome                      # 主结果取首次: 与单次跑批逐字同源
    first["data_hashes"] = hashes                     # 多条指纹全等才算确定性成立
    first["repeat_states"] = states                   # M7 据此判断"指纹差异是否可归因到传输层"
    return first


def load_gold(case_id: str) -> dict | None:
    """读金标准 (不存在返回 None — 调用方记 missing, 不静默打 0)。"""
    path = GOLD_DIR / f"{case_id}.json"
    if not path.is_file():                                                           # 缺金标准返 None, 与空 dict 严格区分 (阻断 vs 零行)
        return None  # None 与空 dict 分开: 缺金标准是阻断项, 不是"零行金标准"
    return json.loads(path.read_text(encoding="utf-8"))


GENERATOR_PATH = GOLD_DIR / "gen_gold.py"     # 金标准生成器: gold 自报的 script_sha256 要与它的实况对齐


def _sha256_file(path: Path) -> str:
    """文件字节指纹 (与 gen_gold 同一口径: 内容哈希, 带 sha256: 前缀)。"""
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def detect_provenance_drift(case_id: str, gold: dict, mode: str = MODE_LIVE) -> list[str]:
    """血缘核对: 生成器指纹是否过期。

    与签字无关, 独立成立: 生成器脚本在金标准生成之后被改过 (哪怕只改注释),
    这批答案就不是现版本脚本产的 —— 藏起来等于让过期金标准悄悄出 PASS。

    2026-10-07 删掉"快照身份并集有交"这一条: live 层的 provenance 根本没有
    快照身份 (见 :func:`_data_version`), 保留它只会变成一条恒红的空判据 ——
    空判据比没有判据更坏, 它让人以为验过了。

    返回阻断项清单 (空 = 血缘齐备)。
    """
    problems: list[str] = []
    recorded_gen = str((gold.get("generator") or {}).get("script_sha256") or "")
    if not recorded_gen:                                             # 没记生成器指纹 = 来路不明
        problems.append(f"generator_unrecorded:{case_id}")
    elif GENERATOR_PATH.is_file() and recorded_gen != _sha256_file(GENERATOR_PATH):
        # 脚本在金标准生成之后被改过 (哪怕只改注释): 这批答案不是现版本脚本产的
        problems.append(f"generator_drift:{case_id}")
    return problems


def run(scenarios_dir: Path = SCENARIOS_DIR, repeat: int = 3, mode: str = MODE_LIVE,
        require_independent_verify: bool = False) -> dict:
    """全量对账: 逐场景 run→compare, 汇总 case 结果 + 阻断项 + metascore。

    **缺省 ``live``, 且这是唯一的臂**: 回放已删, 库里没有任何 offline 分支可切。
    此前「库函数缺省 replay、CLI 缺省 live」的规则是为了让单测不挂在网络上; 那条意图
    仍然成立, 但实现方式换成了打桩会话而不是切换臂。

    ``require_independent_verify``: 打开时额外跑 §4.3.1 的七项独立核验, 并把
    "21/21 全过"纳入放行条件 —— 核验器与 gold 生成器是**两份独立实现**, 它答的是
    "金标准本身站不站得住", 而不是"被测代码对不对"。缺省关闭 (核验读全部快照,
    有 I/O 成本); 收口时显式打开。
    """
    # 两张清单分开: "跑挂"与"没跑"在报告里必须能区分, 否则缺件会被读成通过
    case_results, missing_gold = [], []                                                                 # 跑挂与没跑必须可区分
    drift_disclosure: list[str] = []                                                            # 血缘漂移 (自检批也披露, 但不阻断)
    for path in sorted(scenarios_dir.glob("*.yaml")):  # 排序保证报告逐次可复现
        scenario = load_scenario(path)                                                             # 字段校验在装载层做, 循环里只处理合法场景
        case_id = scenario["case_id"]
        if mode == MODE_LIVE:
            pace(case_id)                       # 场景间隔: 铁律 7 (b) 的串行要求, 与限速器叠加 (回放不触网, 不必等)
        gold = load_gold(case_id)                                                                # 金标准按 case_id 取
        if gold is None:                                                                           # 缺金标准是阻断不是零分, 直接记账不进对账
            missing_gold.append(case_id)      # 金标准缺失 = 阻断 (fail-closed, 铁律 5)
            continue
        # 血缘漂移逐 case 现查现记: 生成器指纹过期, 原样收进披露列
        drift_disclosure += detect_provenance_drift(case_id, gold, mode)   # 阻断项自带 "码:case_id", 再拼一遍就成了 "x:x"
        actual = run_scenario(scenario, repeat=repeat, mode=mode)   # 产出声明面/实测面两侧
        compared = compare_case(gold, actual)            # M1–M7 逐项对账并收集阻断项
        case_results.append({"case_id": case_id, **compared})
    n_pass = sum(1 for c in case_results if c["pass"])  # 全过才算 PASS, 不按加权分和算
    meta = metascore(load_broken_results())  # 反证夹具自证: 判定器不灵则本次分数不作数
    verify_report = None
    if require_independent_verify:           # 七项独立核验: 只在收口时跑, 不进日常冒烟
        # 本地: 独立核验器 (与 gen_gold 各写一份, 刻意不共用算法)
        from evals.groundtruth.verify_independent import verify_all
        # 核验的永远是**全量金标准**: 它是"金标准站不站得住"的检查, 与本次
        # 跑批选了哪批场景无关 (拿 smoke 子集去核会因缺场景把其余判 FAIL)
        verify_report = verify_all(gold_dir=GOLD_DIR, scenarios_dir=SCENARIOS_DIR)
    return {
        "mode": mode,                            # 批次级口径自报: 报告读者一眼分清这批判的是行集还是不变量
        "cases": case_results,                  # 逐 case 明细: 失败时按 case_id 回到场景
        "n_cases": len(case_results),
        "n_pass": n_pass,
        "missing_gold": missing_gold,          # 缺件清单进报告, 供人判断是流程漏还是数据缺
        "metascore": meta,
        # 独立核验摘要 (未打开时为 None): 只报计数与总判定, 逐项明细走 verify_independent 的 CLI
        "independent_verify": (None if verify_report is None else {
            "pass": verify_report["pass"], "n_pass": verify_report["n_pass"],
            "n_cases": verify_report["n_cases"], "n_na": verify_report["n_na"],
            "failed": [c["case_id"] for c in verify_report["cases"] if not c["pass"]],
        }),
        # 血缘披露: 生成器指纹漂移。它证明的是管线自洽, 不阻断跑批,
        # 但把它藏起来就等于让过期金标准悄悄出 PASS。
        "provenance_drift": drift_disclosure,
        # 三条缺一即 FAIL (含空跑批)。第三条是 metascore: 判定器漏抓注入故障时,
        # 上面两条照样可能全绿 —— 那时的 1.00 是「没被证伪」而不是「被证伪过」,
        # 报告正文却照印「必须 1.00」, 于是 fail-open 藏在注释与实现之间。
        # 夹具被误删时 metascore() 返回 0.0, 所以这一条同时兜住"夹具没了"。
        # 第四条只在 --require-independent-verify 时生效: 金标准自身未经独立核验,
        # 放行就是让"管线自洽"冒充"金标准正确"。
        "pass": (n_pass == len(case_results)) and case_results
                and not missing_gold and meta >= 1.0
                and (verify_report is None or verify_report["pass"]),
    }


def load_broken_results() -> list:
    """反证夹具自证 (broken/ 下每个坏样本必须被判 FAIL)。"""
    # 本地: 反证夹具自证 (判定器有效性的门槛证据)
    from evals.groundtruth.broken import run_broken_selftest  # 坏样本全被抓 = 指标不空转

    return run_broken_selftest()


def render_markdown(report: dict) -> str:
    """Markdown 报告 (数字以 JSON 为准)。"""
    live = report.get("mode") == MODE_LIVE
    lines = [                                                                              # 摘要先于明细: 人工复核先看结论, 再回 case 找证据
        "# E2 查询结果与金标准一致性 跑批报告",
        "",
        ("> **本批为实跑 (live)**: 直连站点, 行集类判据走不变量 (分页无重无漏 / "
         "排序单调 / 行数不超预算), 语义类判据走真值。回放层已于 2026-10-07 退役 "
         "(逐行 P/R 随快照一并删除, 承接登记见 docs/REPLAY-RETIREMENT-CRITERIA.md)。"
         if live else
         "> **本批为回放 (replay)**: 该臂已于 2026-10-07 整链删除, 见到这份抬头说明 "
         "调用方还在传 mode=replay —— 那条实现不存在, 判据无法计算。"),
        "",
        f"- 接线: {report.get('mode', '?')}",
        f"- case 数: {report['n_cases']} (pass {report['n_pass']})",
        f"- 缺金标准: {', '.join(report['missing_gold']) or '无'}",
        f"- metascore (反证夹具): {report['metascore']:.2f} (必须 1.00)",
        f"- 血缘漂移: {', '.join(report.get('provenance_drift') or []) or '无'}",
        (f"- 独立核验 (§4.3.1 七项): "
         f"{report['independent_verify']['n_pass']}/{report['independent_verify']['n_cases']} PASS "
         f"(N/A {report['independent_verify']['n_na']})"
         if report.get("independent_verify") else
         "- 独立核验: 未跑 (加 --require-independent-verify 打开)"),
        f"- 判定: {'PASS' if report['pass'] else 'FAIL'}",
        "",
        "| case | 加权分 | 阻断项 |",
        "|------|--------|--------|",
    ]
    for case in report["cases"]:
        lines.append(f"| {case['case_id']} | {case['weighted']:.4f} "
                     f"| {', '.join(case['blockers']) or '—'} |")  # 阻断项逐条列, 复现按它查
    lines.append("")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    """构造 E2 CLI 解析器 (抽成函数是为了让 ``--mode`` 的缺省可被直接断言)。

    单独成函数而不是写在 :func:`main` 里: 「CLI 缺省 live」这条规则本身就是要被
    钉住的性质, 藏在 main 体内就只能靠读源码验证。

    ``--mode`` 仍接受 ``replay``: 那是**历史口径**, 库内已无实现 (传入即显式报错)。
    留这个取值是为了让"命令行悄悄传了 replay 却跑出了 live 结果"这件事成为一次
    可见失败, 而不是被 argparse 静默改写。
    """
    parser = argparse.ArgumentParser(description="E2 groundtruth runner")
    parser.add_argument("--scenarios", default=str(SCENARIOS_DIR), help="场景目录 (默认 evals/groundtruth/scenarios)")
    parser.add_argument("--mode", choices=(MODE_LIVE, MODE_REPLAY), default=MODE_LIVE,
                        help="接线: live=直连真站点作放行闸(默认且唯一); replay=已退役, 传入即报错")
    parser.add_argument("--repeat", type=int, default=3, help="每场景重复次数 (供 M7 判确定性; 至少 1)")
    parser.add_argument("--json", default="", help="汇总 JSON 落盘路径")
    parser.add_argument("--md", action="store_true", help="把 Markdown 报告打到 stdout")
    parser.add_argument("--md-out", default="", help="Markdown 报告落盘路径 (docs §12 的 REPORT.md 永久资产)")
    parser.add_argument("--require-independent-verify", action="store_true",
                        help="跑 §4.3.1 七项独立核验, 全过才放行 (缺省关闭; 核验读全部快照, 有 I/O 成本)")
    return parser


def main(argv=None) -> int:
    """CLI: --mode live|replay --repeat N --json out --md; 退出码 0 全过 / 1 有 fail。

    默认 ``live`` (放行闸)。``--mode replay`` 给确定性回归用: 离线、可复现、
    逐行对账, 是单测与 CI 快速自检的那一层。

    人工签字闸门 (``--require-human-review``) 已于 2026-10-04 取消 (E2 拆法 A),
    整套签字工具链随后删除 —— 放行只看 case 全过 / 无缺件 / metascore=1.0。
    """
    args = build_parser().parse_args(argv)             # argv 显式传入: 同一份解析器才能被自测直接调用
    report = run(Path(args.scenarios), repeat=args.repeat, mode=args.mode,
                 require_independent_verify=args.require_independent_verify)   # 唯一跑批入口 (编排件不自建判据)
    if args.json:                                                                                   # 两路输出各自可选: 只给一种也不该崩
        Path(args.json).write_text(                                                       # JSON 落盘前不建目录: 路径写错就当场炸, 不留半份产物
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")  # JSON 是数字真值
    if args.md:                                                                              # Markdown 与 JSON 同源, 不另算一遍数字
        print(render_markdown(report))  # Markdown 给人读: 与 JSON 同源, 不另算一遍
    else:
        print(json.dumps({k: v for k, v in report.items() if k != "cases"},
                         ensure_ascii=False, indent=2))  # 默认只打汇总, 逐 case 走 --json
    if args.md_out:                                                                          # 落盘版: 与 --json 同形, 路径由调用方指定
        md_path = Path(args.md_out)                                                          # REPORT.md 是永久资产 (docs §12), 打印到终端不算入库
        md_path.parent.mkdir(parents=True, exist_ok=True)                                    # 目录自建: 首次生成时父目录可能还不存在
        md_path.write_text(render_markdown(report) + "\n", encoding="utf-8", newline="\n")   # newline="\n": 跨平台不写成 CRLF
    return 0 if report["pass"] else 1  # 退出码契约: 0 全过 / 1 任一阻断或缺件


if __name__ == "__main__":
    raise SystemExit(main())
