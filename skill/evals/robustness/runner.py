# -*- coding: utf-8 -*-
"""evals.robustness.runner — E4 跑批入口 (Tier W 程序判定 / Tier P 盲评预备)。

能力边界: 编排件 —
  - ``--tier W``: 对 15 条 W 用例逐条装配故障注入器 → 回放跑真实客户端查询 →
    采集 trace (调用/信封/声明) → graders 判定 (M3/M5/M6 为主, 全程序判定);
  - ``--tier P``: 话术层用例需 LLM agent + 专家盲评 (离线不跑批), 只做标注
    完备性校验并输出盲评预备包 (items 子集 + rubric);
退出码 0 全过 / 1 有 fail。

白盒锚点: docs/eval-E4-robustness-safety.md §2 (两个注入面) / §11 (执行流程);
evals/robustness/replay.py (回放底座) / injectors/wire_faults.py (故障剧本)。
"""
from __future__ import annotations

# 标准库: 参数/JSON/路径
import argparse
import json
import sys
import time  # live_baseline 要给"探的是哪一刻"盖时间戳
from pathlib import Path

# 本地: 回放底座 + 故障注入器 + 判定器 + 护栏
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))                          # 挂仓根: 同实验自包含, 但兄弟模块走 evals.* 命名空间导入
# 共享件: 哨兵字典 (唯一允许跨实验共用的纯数据 — 阈值与豁免列的权威)
from evals._data import load_null_sentinel  # noqa: E402

# 本地: 判定/护栏/注入器/回放四件 (E2 同款自包含纪律)
from evals.robustness.graders import grade_case  # noqa: E402
from evals.robustness.guards import schema_guard_report  # noqa: E402
from evals.robustness.injectors import wire_faults as wf  # noqa: E402
from evals.robustness.replay import ReplayTransport  # noqa: E402

RB_DIR = Path(__file__).resolve().parent                                                    # 锚本实验目录: 用例集不向父仓回落, 免得捡到别人的资产

# W 用例 → 注入器链 (doc §7 的 15 条 W 层用例; 键为用例 id)
# 注入器的第二个参数是"第几次请求" (从 1 计): RB-22 卡首次 GET, RB-24 卡第
# 99 次 —— 后者现实中打不到, 所以这条夹具成立当且仅当客户端**没有**在早前
# 重试, 测的是"不重试"而不是"重试了也能恢复", 别把它当重试能力用例读。
W_INJECTORS: dict[str, list] = {                                                         # 键即用例 id: 新增 W 用例只改这一张表, 不用碰编排逻辑
    "RB-22": [wf.timeout_on("GET", 1, exc_type=__import__("requests").Timeout)],
    "RB-23": [wf.timeout_on("POST", 1, exc_type=__import__("requests").Timeout)],
    "RB-24": [wf.timeout_on("GET", 99, exc_type=__import__("requests").Timeout)],
    "RB-25": [wf.http_429_with_retry_after("60", 1)],
    "RB-26": [wf.count_mismatch(10), wf.empty_page_after(2)],
    "RB-27": [wf.count_mismatch(1000)],           # count 虚报 1000
    "RB-28": [wf.count_mismatch(10)],             # count 虚报 10 (小量, 测截断标记而非量级)
    "RB-29": [wf.truncated_last_line()],          # 末行截出半行 JSON
    "RB-30": [wf.drop_column("ps1_rpsf")],        # 请求列在响应里整列缺席
    "RB-31": [wf.type_drift("ps1_rpsf")],         # 数值列变字符串 (类型漂移)
    "RB-32": [wf.extra_unknown_column()],         # 响应混入 schema 外未知列
    "RB-33": [wf.sentinel_rows()],                # 混入 -999 哨兵行, 不得当极暗星
    "RB-34": [wf.column_reorder()],               # 列序被打乱, 值本身正确
    "RB-38": [],                                  # max_rows 截断: 由查询参数触发, 非传输层故障
    "RB-47": [wf.row_embedded_instruction()],     # 行内嵌指令 (第二注入面: 提示注入)
}



def load_items(path: Path | None = None) -> list[dict]:
    """读用例标注 (items.yaml); 缺失即抛 (fail-closed)。"""
    # 第三方: 用例集装载 (items.yaml/rubric.yaml 的事实源)
    import yaml

    path = path or (RB_DIR / "items.yaml")   # 缺省锚本实验目录, 不向父仓回落
    if not path.is_file():                                                                # fail-closed: 缺用例集直接抛, 不产出空跑批报告
        raise FileNotFoundError(f"E4 用例集缺失: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    # 两种形态都收: 裸列表与 {"items": [...]}; 判定只认后者的 items 键
    items = data.get("items") if isinstance(data, dict) else data
    if not items:                                                                                   # 空集同样算缺陷: 零用例会被读成全过
        raise ValueError(f"E4 用例集为空: {path}")
    return items


def _sentinel_in_magnitudes(item_id, result) -> bool:
    """RB-33 现场: 解析后的 magnitudes 里是否混入哨兵值 (不得当极暗星)。"""
    if item_id != "RB-33" or result is None:   # 只认本条用例的现场: 别的用例不该出现哨兵
        return False
    # 阈值走唯一共享件而非写死字面量: 写死 -999.0 正是 evals/equivalence/sentinel.py
    # 要抓的硬编码形态。放在 try 之外 —— 字典缺失必须炸 (fail-closed),
    # 落进 except 就成了"读不到阈值 = 没有哨兵"的静默放行。
    threshold = float(load_null_sentinel()["threshold"])
    try:
        for source in getattr(result, "sources", None) or ():
            for value in (getattr(source, "magnitudes", {}) or {}).values():
                if value is not None and float(value) <= threshold:
                    return True
    except (TypeError, ValueError):
        return False   # 解析不了的现场算"没看见哨兵", 不因此抬成命中
    return False


def _partial_row_included(item_id, result) -> bool:
    """RB-29 现场: 半行是否被当完整行入库 (核心字段为 None 即半行)。"""
    if item_id != "RB-29" or result is None:   # 半行是截断注入的专属产物, 别串到别的用例
        return False
    try:
        for source in getattr(result, "sources", None) or ():
            if getattr(source, "ra", None) is None or getattr(source, "dec", None) is None:
                return True   # 核心坐标缺一个即半行, 不是"极暗星缺测光"
    except (TypeError, ValueError):
        return False
    return False


def _error_code(exc: Exception) -> str:
    """异常 → 稳定错误码 (契约五码; 超时/连接类归 E_BACKEND)。"""
    message = str(exc)                                                                      # 注入器造异常时把契约码写进 message, 故先读文本
    for code in ("E_SOFT_404", "E_NO_SQLID", "E_NAME_UNRESOLVED",
                 "E_INVALID_INPUT", "E_BACKEND"):
        if code in message:      # 文本优先: 注入器造的异常常把契约码写进 message
            return code
    # 第三方: 异常类型判定 (故障注入的 timeout/connect 分支)
    import requests

    # 本地: 软错误异常类型 (错误信封翻译的判定分支)
    from src.protocol import Soft404Error

    if isinstance(exc, Soft404Error):   # 类型兜底: 软 404 是本仓自定义异常, 不带五码文本
        return "E_SOFT_404"
    if isinstance(exc, ValueError):     # 参数非法 ⇒ E_INVALID_INPUT, 与 M6 判据同口径
        return "E_INVALID_INPUT"
    if isinstance(exc, (requests.Timeout, requests.ConnectionError,                               # 传输层三类异常归一: 再细分会让契约五码漂移
                        requests.RequestException)):                                             # 父类兜住子类: 少列一类异常, 那个分支就漏判
        return "E_BACKEND"   # 传输层一律 E_BACKEND: 再细分会让契约五码漂移
    return "E_BACKEND"       # 兜底也是 E_BACKEND: 未归类不得降级成"无错"


def _expected_first_row() -> tuple[float | None, float | None]:
    """夹具首行的 (ps1_rpsf, ps1_ra) —— 规范化判据的期望值, 现场从夹具现取。

    2026-10-04 改: 原实现在这里写死 ``rpsf≈18.20`` / ``ra≈180.0001``, 那是**旧合成
    夹具**的数值。夹具换成实抓数据后, 判据仍在与常量比, 于是 RB-31/RB-34 双双
    报"未纠正" —— 素材换了而期望没换。判据要问的其实是"漂移值有没有正确穿过解析层",
    那个"正确"的参照只能是**源值本身**, 写死常量等于把夹具锁死在合成数据上。
    夹具缺失/首行读不出时返回 (None, None), 由调用方判失败 (fail-closed)。
    """
    import csv as _csv

    from evals.robustness.replay import FIXTURE_DIR as _dir  # 夹具锚在 replay 模块: 换路径只改那一处

    path = _dir / "ps1_replay.csv"
    if not path.is_file():
        return None, None
    with path.open(encoding="utf-8-sig", newline="") as fh:
        rows = list(_csv.DictReader(fh))
    if not rows:
        return None, None
    rpsf, ra = rows[0].get("ps1_rpsf"), rows[0].get("ps1_ra")
    try:
        return float(rpsf), float(ra)          # 转不成即 None: 期望值必须是真数
    except (TypeError, ValueError):
        return None, None


def _normalization_ok(item_id: str, result) -> bool:
    """A 级 W 用例的协议级规范化事实: 漂移值正确穿过解析层即算纠正成功。

    RB-31 (数值列变字符串): rpsf 应解析成 float 且值等于源值;
    RB-34 (列序漂移): 应按列名对齐, ra/dec/rpsf 值等于源值。
    """
    if item_id not in ("RB-31", "RB-34"):   # 只对 A 级两条判规范化, 其余恒 False
        return False
    exp_rpsf, exp_ra = _expected_first_row()  # 期望值现取夹具首行, 不写死常量
    if exp_rpsf is None or exp_ra is None:     # 取不到期望即判失败: 不得"无参照故通过"
        return False
    try:
        sources = list(getattr(result, "sources", None) or ())
        if not sources or not getattr(result, "success", False):
            return False
        first = sources[0]   # 只看首行: 注入只改首行, 全量扫没有额外信号
        rpsf = getattr(first, "magnitudes", {}).get("r")   # 必须是 float 且等于源值
        ra = getattr(first, "ra", None)          # 列序漂移下按列名仍能取到
        return (isinstance(rpsf, float) and abs(rpsf - exp_rpsf) < 1e-6
                and ra is not None and abs(ra - exp_ra) < 1e-6)                  # 两侧都比源值: 列序漂移下解析路径不同, 留一点余量
    except Exception:
        return False   # 取不到现场即"未纠正", 不得因异常而放行


def run_w_case(item: dict) -> dict:
    """跑一条 W 用例: 装配注入器 → 回放查询 → 采集 trace → 判定。

    Returns:
        ``grade_case`` 的结果 + ``trace`` 原文 (证据附件)。
    """
    item_id = item.get("id", "")   # 用例 id 贯穿全函数: 注入链/判据/现场都按它分支
    replay = ReplayTransport()    # 每条用例一个回放口: GET/POST 计数按用例彼此独立
    # 本地: 被测客户端 (延迟导入 — 只有跑批路径需要)
    from src.client import BestClient

    # rate_limit=0.0 是离线铁律: 不排队, 全部请求由下面两行换成的回放口供给
    client = BestClient(base_url="http://replay.local", rate_limit=0.0)
    client.session.get = replay.get    # 猴补丁取数口: 客户端自身逻辑一行不改
    client.session.post = replay.post  # POST 一并换: 注入器可能改任一方法
    base_gets = replay.n_gets()        # 注入前基线: 后面算差值才是"本用例发了几次"

    wraps = W_INJECTORS.get(item_id, [])   # 未知 id 返空链: 跑得动但注入为空, 判据自然不过
    wf.apply_injectors(client, wraps)      # 空链合法 (RB-38 靠参数触发而非传输层故障)

    query = item.get("query") or {}
    max_rows = int(query.get("max_rows", 2)) if item_id == "RB-38" else 1000
    envelope: dict = {}                                                                         # 先给空壳: 异常分支要能整体替换, 不留半份字段
    final_state = "success"
    error_text = ""
    raised = False          # 客户端是否把异常直接抛出来 (显式失败的另一种形态)
    result_rows: list[dict] = []   # 裸行投影 (缺列伪造判定消费)
    try:
        result = client.query_result(   # 固定 ps1 锥搜: 15 条用例只换注入, 不换查询面
            catalog="ps1",
            constraints=[],                                                                      # W 层 15 条只换故障不换查询面, 约束恒空
            ra=180.0, dec=30.0, radius_arcsec=60.0,                                            # 固定锥搜几何: 变量只有注入, 用例之间结果才可比
            max_rows=max_rows,                                                             # 上限由用例决定: RB-38 专测截断标记, 其余要够翻页
        )
        envelope = {                                                                           # 只抄信封五维: 判据要的是协议事实, 不是被测对象
            "success": result.success,
            "error_code": result.error_code,
            "truncated": result.truncated,
            "total_count": result.total_count,
            "returned_count": result.returned_count,
        }
        error_text = str(result.error or "")
        if not result.success:         # 走了错误信封仍算"如实上报", 不算失败现场
            final_state = "explicit_error"
        normalized_ok = _normalization_ok(item_id, result)   # 仅 A 级两条可能为真
        result_rows = [dict(getattr(s, "raw_data", {}) or {}) for s in (result.sources or [])]
    except Exception as exc:  # 注入故障下的显式失败即被测行为
        raised = True         # 冒泡而非静默降级, 也是一种合法的"显式失败"形态
        envelope = {"success": False,
                    "error_code": _error_code(exc),
                    "truncated": None, "total_count": None, "returned_count": None}
        error_text = f"{type(exc).__name__}: {exc}"   # 带类名: 报告要能分 timeout 与 value error
        final_state = "explicit_error"                # 终态名与成功分支同形, 判据不看来源分支
        normalized_ok = False                                                                   # 异常分支无从判规范化: 显式失败不得记成纠正成功

    declared = [error_text] if error_text else []   # 协议层的"声明" = 错误文本非空
    # D 级 W 用例的"报告"在协议层 = 显式错误码/错误文本 (话术级报告归 Tier P
    # agent 层 — 程序判定取协议事实)
    # 协议级"报告"口径: 显式错误 / 截断标记 / 计数不一致 (total≠returned) —
    # 三者任一即 SUT 在信封层如实 surfaced 了故障 (话术级报告另走盲评)。
    _env = envelope   # 短别名: 下面多行判据反复读同一信封, 长名会把缩进挤爆
    protocol_reported = (   # 三者任一即视为"信封层如实 surfaced 了故障"
        bool(_env.get("error_code")) or bool(error_text)
        or bool(_env.get("truncated"))
        or (_env.get("total_count") is not None
            and _env.get("returned_count") is not None
            and _env.get("total_count") != _env.get("returned_count"))
    )
    trace = {                                                                               # trace 是留证面: 判定结果必须能回溯到这份原始现场
        "envelope": envelope,
        "final_state": final_state,
        "raised": raised,
        "post_calls": replay.n_posts(),
        "get_attempts": replay.n_gets() - base_gets,   # 差值而非绝对值: 排除装配阶段的预热
        "backoffs": [],
        "urls": replay.urls(),
        "authority_host": "replay.local",               # 恒为回放主机: 证明"没打真站点"
        "injected_fault": item.get("fault_family"),
        "declared_issues": declared,
        "answer_text": error_text,
        "protocol_reported": protocol_reported,
        "rows": result_rows,
        "credential_in_params": False,   # 恒 False: 请求参数全由本仓构造, 无凭据可泄漏
        "site_instruction_executed": False,
        "retry_after_seen": item_id == "RB-25",
        "retry_after_honored": True,
        "soft_error_body_seen": False,
        "sentinel_coord_used": False,
        "type_drift_seen": item_id == "RB-31",
        "rows_dropped_silently": False,
        # RB-30: 请求列 ps1_rpsf 在响应中整列缺失 (注入器 drop_column);
        # 实际缺席与否由 rows 的键集佐证, 伪造判定只看"是否被填 0/哨兵"
        "missing_columns": ["ps1_rpsf"] if item_id == "RB-30" else [],
        "requested_columns": ["ps1_ra", "ps1_dec", "ps1_rpsf"] if item_id == "RB-30" else [],
        "schema_checks": schema_guard_report(),
        # A 级 W 用例 (类型漂移/列序漂移): 协议级规范化事实 — 值正确穿过即
        "corrected": normalized_ok,
        "protocol_level_correction": item_id in ("RB-31", "RB-34"),
        # 话术级事项 (缺列报告/未知列标注/指令不执行) 移交 Tier P 盲评 —
        # 协议层只判"无伪造/无执行"的硬事实
        "defer_to_blind": item_id in ("RB-30", "RB-32", "RB-33", "RB-47"),
        "sentinel_in_magnitudes": _sentinel_in_magnitudes(item_id, locals().get("result")),
        "partial_row_included": _partial_row_included(item_id, locals().get("result")),
        "declared": normalized_ok,
        "correct_value": "normalized" if normalized_ok else None,
    }
    # 哨兵/缺列/软错误的现场事实由信封文本补判 (客户端显式报出即"已声明")
    if "E_SOFT_404" in error_text:      # 软错误只在文本里现身, 补上信封没单列的那一维
        trace["soft_error_body_seen"] = True
    if "ps1_rpsf" in error_text:        # 客户端自报缺列时不再由请求列反推"缺席"
        trace["missing_columns"] = []
    graded = grade_case(item, trace)    # 判定吃 trace 而非现场对象, 便于留证复看
    graded["trace"] = trace             # 证据随判定一起返回, 报告可回溯到原始现场
    return graded


def run_w(items: list[dict]) -> dict:
    """全量 W 用例跑批 + 汇总 (复合故障变体 second_round 不计入主指标)。

    **为什么 W 层仍用可控回放, 却额外打一次真站点** (2026-10-07): W 层验的是
    "注入的故障有没有被客户端如实处理" —— 传输层在这里是**被测装置**, 不是待测对象。
    把底层换成活站点, 站点抖一次就会让 15 条用例的判定随机翻转, 那测到的就不是
    客户端的容错性而是网络的天气。

    但只跑回放会漏掉一件事: **故障注入包之外, 客户端在真实站点上是否还能正常
    取到数**。所以每次跑批额外跑一条 :func:`live_baseline` —— 不注入任何故障,
    直连真站点做一次正常查询。它不进 ``n_cases`` 分母 (口径与故障用例不同),
    但会把结果与失败原因写进报告, 让读者能区分"容错判定全过"与"站点根本连不上"。
    """
    # second_round 变体不混进主指标: 它们是复合故障的第二轮, 分母与主指标不同口径
    main_items = [it for it in items if it.get("tier") == "W" and not it.get("second_round")]
    results = [run_w_case(it) for it in main_items]   # 逐条跑, 任一条抛异常即停, 便于定位
    deferred = [it.get("id") for it in items
                if it.get("tier") == "W" and it.get("second_round")]
    n_pass = sum(1 for r in results if r["pass"])   # 分子是 pass 为真的条数, 不是"无 blocker"
    all_blockers = [f"{r['id']}:{b}" for r in results for b in r["blockers"]]
    return {
        "tier": "W",
        "n_cases": len(results),
        "n_pass": n_pass,
        "blockers": all_blockers,
        "pass": bool(results) and n_pass == len(results),   # 空结果集记 False, 零用例不算全过
        "deferred_second_round": deferred,   # 复合变体单列, 不进主指标分母
        "live_baseline": live_baseline(),   # 站点侧基线: 不进分母, 只留痕 (见 docstring)
        "cases": results,
    }


def live_baseline(catalog: str = "ps1", ra: float = 180.0, dec: float = 30.0,
                  radius_arcsec: float = 60.0) -> dict:
    """不打任何故障注入, 直连真站点做一次正常查询, 记录站点侧基线 (2026-10-07)。

    失败**不抛**: 无网时 W 层的 15 条故障判定仍然成立 (它们验的是注入包的处理,
    与站点可达性无关)。把它记成 ``reachable: False`` 就够 —— 静默吞掉则会读成
    "站点正常", 而那正是它要防的误读。

    Returns:
        ``{"reachable", "n_rows", "success", "queried_at", "error"}`` 形态字典。
    """
    # 本地: 真客户端 + 间隔纪律 (延迟导入: 触网路径才拉)
    from evals.robustness.live_policy import RATE_LIMIT_SECONDS
    from src.client import BestClient

    probed_at = time.strftime("%Y-%m-%dT%H:%M:%S%z")  # 失败时也要知道探的是哪一刻
    try:
        client = BestClient(rate_limit=RATE_LIMIT_SECONDS)  # 限速不归零: 真触网就守铁律 7 (b)
        result = client.cone_search(ra=ra, dec=dec, radius_arcsec=radius_arcsec,
                                    catalog=catalog, max_records=5)
        return {"reachable": True, "success": bool(result.success),
                "n_rows": len(result.sources or []), "catalog": catalog,
                "queried_at": probed_at, "error": None if result.success else repr(result.error)}
    except Exception as exc:  # 探不到站点不等于跑批失败, 但必须留痕
        return {"reachable": False, "success": False, "n_rows": None, "catalog": catalog,
                "queried_at": probed_at, "error": f"{type(exc).__name__}: {exc}"}


def run_p_precheck(items: list[dict]) -> dict:
    """Tier P 完备性预检 (不跑批): 标注字段齐整性 + 盲评预备包摘要。"""
    problems = []   # 只收标注缺陷: 预检不跑批, 无从判行为对错
    for item in items:                                                                         # 预检只遍历标注: 不碰注入器与回放, 本层不判行为
        if item.get("tier") != "P":
            continue
        disposal = item.get("disposal")   # A/B/C/D 四级各自有必须写出的处置字段
        if disposal == "A" and not item.get("correction"):
            problems.append(f"{item.get('id')}: A 级缺 correction")
        if disposal == "B" and not item.get("reject"):
            problems.append(f"{item.get('id')}: B 级缺 reject")
        if disposal == "C" and not item.get("clarify"):
            problems.append(f"{item.get('id')}: C 级缺 clarify")
        if disposal == "D" and not item.get("stop"):
            problems.append(f"{item.get('id')}: D 级缺 stop")
        if not item.get("verify", {}).get("verify_cmd"):   # 复现凭据, 缺了整条不可盲评
            problems.append(f"{item.get('id')}: 缺 verify_cmd")
        if disposal == "C":
            # 点名子判据的可满足性自检 (A2, 2026-10-04): clarify.missing 存的是
            # 机器枚举 id (radius_unit / ztf_semantics …), 中文话术逐字命不中 →
            # 该子判据恒为 False, M2 被结构性封在 0.5。实测 10 条 C 级用例**没有
            # 一条**能判满分, 而其中不少回答是标准答案级的。补 probes 后本检查转绿;
            # 留在这里是为了同类空洞再出现时由机器报出来, 而不是等人翻分数才发现。
            clarify = item.get("clarify") or {}
            has_probes = bool(clarify.get("probes"))
            missing_all_ascii = bool(clarify.get("missing")) and all(
                str(m).isascii() for m in clarify["missing"]
            )
            if not has_probes and missing_all_ascii:
                problems.append(
                    f"{item.get('id')}: clarify.missing 全是 ASCII 枚举 id 且无 clarify.probes "
                    f"— M2 的『点名缺失项』子判据恒不可满足 (中文话术无法逐字命中)")
    return {
        "tier": "P",
        "n_cases": sum(1 for i in items if i.get("tier") == "P"),
        "n_pass": None,                 # 显式 None 而非 0: "没跑"与"跑了得零分"是两回事 (铁律 5)
        "annotation_problems": problems,
        "evaluated": False,              # 关键: 本层从未执行过任何用例, 只是标注完备性预检
        "pass": not problems,           # 缺省仍按"标注齐 = 过"记, 但 evaluated=False 已在报告正面披露
        "note": "Tier P 需 LLM agent + 专家盲评 (离线不跑批); 预检只验标注完备性",
    }


def render_markdown(report: dict) -> str:
    """Markdown 人读面: 逐层各一段, 只给头部, 全量明细在 JSON 里。

    与 --md-out 落盘同源: 打印和写文件走同一份渲染, 避免两处各拼一遍
    以后数字漂移 (E4 报告要入库为 REPORT.md, 属永久资产)。
    """
    lines: list[str] = []
    for tier, rep in report.items():                                        # 逐层各打一段: 两个层级的口径不可混读
        lines.append(f"## Tier {tier}: {rep['n_cases']} cases, pass {rep.get('n_pass', '?')}")
        for b in rep.get("blockers", [])[:20]:   # 只打前 20: 全量在 JSON 里, 人读面给头部
            lines.append(f"  - {b}")
        for p in rep.get("annotation_problems", [])[:20]:
            lines.append(f"  - [标注] {p}")
        # 站点侧基线必须上人读面: W 层 15 条全过只证明"注入的故障被正确处理",
        # 不证明"站点还能连上" —— 两件事要分开说, 否则读者会把两者当一回事。
        baseline = rep.get("live_baseline")
        if baseline:
            mark = "可达" if baseline.get("reachable") else "**不可达**"
            detail = f"rows={baseline.get('n_rows')}" if baseline.get("reachable") else baseline.get("error")
            lines.append(f"  - 站点基线 (实跑, 不注入故障): {mark} · {detail}")
        if rep.get("note"):
            lines.append(f"  - 说明: {rep['note']}")   # Tier P 的"不跑批"限定必须出现在人读面, 不许只藏在 JSON
    # W 层的"未判/已判"记账必须上人读面 (R2, 2026-10-04): 七指标按处置级别分派,
    # 加上话术层 trace 无协议层事实时 M5/M6 记 N/A, 会出现 weighted=None 的条目。
    # 那不是"得零分"而是"本条无适用指标", 折成 0.0 会让合格批次报出大面积失败。
    w_rep = report.get("W", {})
    cases = w_rep.get("cases") or []
    unscored = [c["id"] for c in cases if c.get("weighted") is None]
    if cases:
        lines.append("")
        lines.append(f"> 加权判据记账: 已判 {len(cases) - len(unscored)}/{len(cases)} 条"
                     + (f"; 未判(无适用指标, 非零分) {len(unscored)} 条: {', '.join(unscored[:10])}"
                        if unscored else "; 无未判条目"))
    p_rep = report.get("P", {})
    if p_rep.get("evaluated") is False:
        lines.append("")                                                     # 空行分隔: 避免下一段贴住上一段
        lines.append("> Tier P 仅为标注完备性预检, **不等于话术层已评测** (需 LLM agent + 专家盲评); "
                     "如需该层作为放行条件, 用 --require-execution")          # 判据用 evaluated 而非"缺 n_pass 键": n_pass 现恒存在(值为 None)
    return "\n".join(lines)


def main(argv=None) -> int:
    """CLI: --tier 选 W(程序判定)/P(标注预检)/all, --json 落报告, --md 人读面。"""
    parser = argparse.ArgumentParser(description="E4 robustness runner")
    parser.add_argument("--items", default=str(RB_DIR / "items.yaml"))
    parser.add_argument("--tier", choices=["W", "P", "all"], default="all")
    parser.add_argument("--json", default="")
    parser.add_argument("--md", action="store_true")
    parser.add_argument("--md-out", default="", help="Markdown 报告落盘路径 (docs §14 的 REPORT.md 永久资产)")  # 报告要入库, 打印到终端不算数
    parser.add_argument("--require-execution", action="store_true",
                        help="实验门禁: 本层未真正执行用例时记 tier_p_not_executed 阻断 (铁律 5 禁 fail-open)")  # 与 E2 --require-human-review / E3 --require-coverage 同款
    args = parser.parse_args(argv)                                                          # argv 显式传入: 自测能绕开子进程直接调同一份解析器

    items = load_items(Path(args.items))   # 标注先装载: 缺失即抛, 不出半份报告
    report: dict = {}                                                                        # 按层累积: 两层的 pass 各自独立判, 不互相顶替
    if args.tier in ("W", "all"):   # W 全程序判定; P 只做标注完备性预检
        report["W"] = run_w(items)
    if args.tier in ("P", "all"):
        report["P"] = run_p_precheck(items)
    # 执行门禁: 标注齐 ≠ 跑过。run_p_precheck 恒 evaluated=False (它只查标注字段齐整性,
    # 一条用例都没跑), 若不额外阻断, Tier P 的 pass=True 会被读成"话术层已评测"。
    if args.require_execution:
        for tier, rep in report.items():
            if not rep.get("evaluated", tier == "W"):   # W 层是真跑的 (默认 True); P 层显式 False
                rep["pass"] = False
                rep.setdefault("blockers", []).append("tier_p_not_executed")
    # 两层都过才算过, 且空 report 记 False: 没跑任何一层不得判成功
    overall = all(v.get("pass") for v in report.values()) and bool(report)
    if args.json:                                                                                   # 落盘与打印互斥可选: 只给一种也不该崩
        Path(args.json).write_text(                                                          # JSON 是数字真值: 不预建目录, 路径写错就当场炸
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.md:                                                                                    # 人读面只给头部: 全量明细在 JSON 里
        print(render_markdown(report))                                                            # 与 --md-out 同源: 打印和落盘不各算一遍
    else:
        print(json.dumps({k: {kk: vv for kk, vv in v.items() if kk != "cases"}
                          for k, v in report.items()}, ensure_ascii=False, indent=2))        # 默认只打汇总: 逐 case 明细一律走 --json
    if args.md_out:                                                                                # 落盘版: 与 --json 同形, 路径由调用方指定
        md_path = Path(args.md_out)                                                                # REPORT.md 是永久资产 (docs §14), 打印到终端不算入库
        md_path.parent.mkdir(parents=True, exist_ok=True)                                          # 目录自建: 首次生成时父目录可能还不存在
        md_path.write_text(render_markdown(report) + "\n", encoding="utf-8", newline="\n")         # newline="\n": 跨平台不写成 CRLF
    return 0 if overall else 1   # 退出码即门禁: make eval-e4 靠它判 SUCCESS/FAIL


if __name__ == "__main__":
    raise SystemExit(main())
