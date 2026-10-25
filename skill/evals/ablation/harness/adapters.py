# -*- coding: utf-8 -*-
"""evals.ablation.harness.adapters — E5 装配层: 三个工具面适配器 + ScriptedLLM 替身。

能力边界 (docs/eval-E5-baseline-ablation.md §3.1 装配表 / §10 落地清单):
  - ``SkillToolBoxAdapter``: 生产 7 工具面 (src/ai_tools.py ToolBox), B3/A* 走这条;
  - ``RawProtocolAdapter``   : BestClient 裸协议 (不经 ToolBox), B2a 走这条;
  - ``ScriptedAdapter``      : 预写调用序列直打快照 CSV, 不建客户端 — R0 式离线
    确定性跑 (E6 r0_lane 同款纪律), 供无 requests 环境下的冒烟与回归;
  - ``ScriptedLLM``          : 按 items.yaml 的 expect_tools 产出确定性 tool_call
    序列与路由的**模型替身**。本仓离线纪律: 不调真实模型; 接口留 ``LLMAdapter``
    抽象, 未来接真模型时实现同名的 plan/render 即可 (答案渲染在 render.py)。

**消融如何落地 (code_seam, 生产码零改动)**: 组件拆/装只在适配器层表达 —
  - 参数校验 (A1): ``param_validation=false`` 时绕过 guards, 手拼表单经
    ``BestClient.submit_query`` 原样下发 (非法参数不进 E_INVALID_INPUT);
  - 字段语义 (A2): 答案渲染改用裸列名, 不注入波段→列映射短语;
  - 拒绝规则 (A3): reject/clarify 路由退化成 answer, 并按 must_not_call 硬查;
  - 来源版本 (A4): 信封摘掉 provenance 分区, 答案不声明 stable_uri/快照,
    且注入载荷失去 untrusted 标记 (S-2 防线随 provenance 一起拆掉);
  - 结果后验证 (A5): 哨兵不当缺失、截断三元组误判成全量。

**零跨实验 import 纪律**: 本模块不 import evals/ 下任何其它实验的代码; 只按
路径**读数据文件** (evals/_data 哨兵字典)。回放传输层的同语义精简版在
harness/run_batch.py; E2 那份权威实现 evals/groundtruth/transport.py 已删除
(2026-10-07「全盘删回放改实跑」), 故该精简版现已**无对照物**。evals/equivalence
现守的是**判定口径**等价 (行主键/哨兵), 传输实现不在对账范围内。

白盒锚点: docs/eval-E5-baseline-ablation.md §3.1 (装配表) / §5.2 (任务 schema) /
§6 (三门) / §7 (反证夹具); src/ai_tools.py (ToolBox 7 工具); src/client.py
(两阶段协议唯一生产客户端)。
"""
from __future__ import annotations

# 标准库: CSV 行集读取 / 计时 / dataclass 载体 / 抽象基类 / 类型标注
import csv
import math
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

# 本地: 哨兵数据字典 (唯一共享件 — 阈值的唯一出处)
from evals._data import load_null_sentinel
from evals.ablation.harness import render as answer_render
from evals.ablation.harness.support import (
    column_of,
    coord_of,
    haversine_arcsec,
    illegal_param_reason,
    is_sentinel_value,
    stable_hash,
    to_float,
)

# 路径锚定: evals/ablation → evals/ → skill 根 (脚本直跑与包导入两条路都成立)
_HERE = Path(__file__).resolve()   # 本文件
EVALS_DIR = _HERE.parents[2]       # evals/
SKILL_DIR = _HERE.parents[3]       # 仓根 astro-best/
SNAPSHOTS_DIR = EVALS_DIR / "groundtruth" / "snapshots"   # 按路径读, 不 import E2 的生成件

# sqlid 占位符: expect_tools 里写 "<上一步返回的 sqlid>", 执行时由上一信封回填
SQLID_PLACEHOLDER = "<上一步返回的 sqlid>"   # 标注侧的字面量, 执行侧据此判定"待回填"

# 需要数据锚点才能执行的工具 (C/R 类零请求设计下调用它们即离线纪律拦截)
DATA_TOOLS = frozenset({"cone_search", "crossmatch_batch", "count", "fetch_page", "resolve_name"})  # 会取数的工具全集: 纯查询类工具不产生行集, 不计入请求成本

# A3 硬查时的默认猜测参数 (无数据锚点, 只会被离线纪律拦截 — 留下 trace 证据)
GUESS_ARGS: dict[str, Any] = {"ra": 180.0, "dec": 30.0, "radius_arcsec": 60.0,
                              "catalog": "ps1"}


def _arg(args: dict, key: str, default: Any) -> Any:
    """取参数 (键缺失或空串才用缺省 — **0 是合法值**, 不能因 falsy 被替掉)。"""
    value = args.get(key)   # 先取原始值: 判"是否给了"必须区分 0 与缺失
    return default if value in (None, "") else value   # 只把 None/空串当没给, 0 是合法值


def _cone_form(args: dict) -> dict:
    """phase-1 锥搜表单 (protocol.build_query_form 锥形键集的精简同语义版)。

    只在**绕过 guards** 的路径上使用 (A1 消融缝 / B2a 裸协议) — 校验在就不走这里。
    """
    form = {"output.fmt": "html", "pos_group": "ra,dec", "pos.type": "cone",
            "pos.racenter": str(args.get("ra")), "pos.deccenter": str(args.get("dec")),
            "pos.radius": str(args.get("radius_arcsec"))}
    if args.get("nearest_only"):
        form["cone_nearestonly"] = "on"   # 可选键不进表单: 少传强于传错, 免触发上游默认值
    if args.get("sort"):
        form["sort"] = str(args["sort"])  # sort 与 order 成对下发, 只给一个语义不完整
        form["order"] = str(args.get("order") or "asc")   # 缺省升序: 与生产 submit_query 同向
    return form


class OfflineNoAnchor(Exception):
    """离线纪律拦截: 任务没有数据锚点, 不得发出真实请求。"""


# ── 数据结构 ────────────────────────────────────────────────────────────────

@dataclass
class RunOutcome:
    """一次 (系统 × 任务) 运行的完整轨迹 (trace 的进程内形态)。

    ``reported`` 是**系统声称**的结构化结果 (行集/截断三元组/关键字段值/
    来源句柄) — 它与 ``rows`` (实际观测行) 分开存, 因为 A1/A5 这类消融的
    失败恰恰是"声称的"与"实际的"不一致 (E5 §6.1 决策门的 S1 静默错值)。
    """

    route: str = "answer"   # 三路由: answer / clarify / reject
    tool_calls: list[dict] = field(default_factory=list)   # 复制一份: 改它不回写标注输入
    envelopes: list[dict] = field(default_factory=list)    # 逐调用原始信封, 与 rows 分开存
    rows: list[dict] = field(default_factory=list)   # 实际观测行, 与声称值分开 (差异即 S1)
    reported: dict = field(default_factory=dict)   # 系统声称的结构化结果 (行集/三元组/句柄)
    answer_text: str = ""
    http_requests: int = 0                                                                  # 请求计数零起: 成本口径要求实测, 缺省 0 而不是估算
    turns: int = 1   # 单轮为 1; 澄清的"第二轮"是另一次 execute, 不在这里累加
    # 成本口径 (E5 §6.7): API usage 缺失记 null, **禁止估算填数**
    tokens_in: Optional[int] = None   # 缺 usage 记 None, 不按字符数折算 token
    tokens_out: Optional[int] = None  # 输出侧同理, 缺失也不填
    elapsed_s: float = 0.0   # monotonic 差值, 系统时钟回拨不该算出负耗时
    notes: list[str] = field(default_factory=list)                                      # 备注逐条追加: 消融效应要在 run 记录里留痕, 便于事后归因


class LLMAdapter(ABC):
    """模型替身抽象: 未来接真模型时实现同名的 plan/render 即可 (接口留缝)。"""

    @abstractmethod
    def plan(self, item: dict) -> tuple[str, list[dict]]:
        """产出 (路由, 工具调用序列) — 不含答案文本 (答案要等工具结果)。"""

    @abstractmethod
    def render(self, item: dict, outcome: RunOutcome) -> str:
        """依据工具结果渲染最终回答文本。"""


# ── 数据读取 (只读数据文件, 零跨实验 import) ────────────────────────────────

# ── ScriptedLLM: 确定性模型替身 ─────────────────────────────────────────────

class ScriptedLLM(LLMAdapter):
    """按 items.yaml 的 expect_tools 产出确定性轨迹与路由的模型替身。

    确定性保证 (E6 R0 同款): 同一 (items, 系统) 重复跑 N 次, ``plan`` 与
    ``render`` 的输出逐字节一致 — 不读时钟、不读随机源。路由按装配表降级:
    A3 拆掉拒绝规则后 reject/clarify 退化成 answer (该拒的硬查)。
    """

    def __init__(self, system: dict) -> None:
        """记住系统装配 (组件开关是路由降级与答案渲染的唯一依据)。"""
        self.system = system                                                                        # 装配体存下: 开关判断与答案渲染都要读它
        self.components: dict = system.get("components") or {}   # 开关快照: 跑批中途不再读 yaml

    def plan(self, item: dict) -> tuple[str, list[dict]]:
        """产出 (路由, 工具调用序列); 组件缺失时路由按装配表降级。"""
        route = item.get("route", "answer")   # 缺省 answer: 老标注无 route 键时不算拒答题
        comp = self.components                # 短别名: 下面四条分支都读它
        if route == "reject":
            # 拒绝**策略**与理由码来自 Skill (refusal_rules); 唯一例外是**无数据
            # 通路**的 B1 — 它本来就不能查, 只能凭公共文档的事实边界作答 (E5 §5.1:
            # "R 类 B0/B1 也能答对" 的关键子集)。有数据通路却无拒绝规则 (B2a/B2b/A3)
            # → 该拒的硬查 (E5 §3.2: "应拒绝任务大概率硬查")。
            can_refuse = (comp.get("refusal_rules")
                          or (comp.get("best_site_docs") and not comp.get("data_path")))
            if not can_refuse:                                                        # 无拒绝规则时降级: 该拒的请求被路由降级取代, 这正是 A3 的效应
                # A3: 拒绝规则被拆掉 → 该拒的硬查 (按 must_not_call 首项发出调用)
                banned = (item.get("reject") or {}).get("must_not_call") or []
                first = banned[0] if banned else "cone_search"   # 取首项: 一次违规即够判红线
                args = dict(GUESS_ARGS)   # 用统一猜参, 让 A3 的 trace 可与别的系统对齐
                if "FILTER" in str((item.get("reject") or {}).get("reason_code") or ""):
                    # E1 NL2T-17 口径: 伪造过滤参数按 hallucination 记
                    args["filter"] = "rpsf_err<0.01"   # 故意不在 schema 内, 让幻觉判据抓到
                return "answer", [{"tool": first.split("_with_")[0], "args": args}]
            if not comp.get("param_validation") and item.get("expect_tools"):
                # A1: 拒绝规则还在但参数校验被拆掉 → 边界题 (半径 0/越界) 的
                # 入站拦截消失, 按 expect_tools 硬发非法参数 — 真系统的对应
                # 行为就是 ParamHallucination (A1 的预期效应, 见
                # systems/a1_no_validation.yaml probe_items)。
                return "answer", self._expected_calls(item)
            return "reject", []
        if route == "clarify":
            # 澄清阶段期望零调用 (E1 口径); A3 拆掉策略后该问不问, 仍零调用
            return ("clarify" if comp.get("refusal_rules") else "answer"), []
        if not comp.get("data_path"):
            return "answer", []   # B0/B1 无数据通路: 结构性不可完成, 零调用才是正确行为
        return "answer", self._expected_calls(item)   # 其余路由: 按 expect_tools 保序发

    def _expected_calls(self, item: dict) -> list[dict]:
        """取 expect_tools 的全部项 (保序); A2 退化时列名去表前缀。"""
        calls = []   # 保序: TSC 比的是调用序列而非集合
        for step in item.get("expect_tools") or []:
            args = dict(step.get("args") or {})
            if not self.components.get("field_semantics"):   # A2 关掉字段语义 ⇒ 改发裸列名
                args = answer_render.bare_column_args(args)   # 不注入波段→列映射短语
            calls.append({"tool": step["tool"], "args": args,   # optional 透传, 判分时才分必需/白名单
                          "optional": bool(step.get("optional"))})
        return calls

    def render(self, item: dict, outcome: RunOutcome) -> str:
        """按路由与组件开关拼装答案 (段落缺失即该组件的消融效应)。"""
        return answer_render.render(item, outcome, self.components, self.system)


# ── 三个工具面适配器 ────────────────────────────────────────────────────────

def _result_envelope(result: Any, rows: list, http_requests: int) -> dict:
    """装配 harness 统一消费的结果信封 (data / status / cost / provenance 四段)。

    离线桩 (``_UnvalidatedConeAdapter``) 与裸协议面 (``RawProtocolAdapter``)
    共用这一个装配点: 两个面的结果信封必须**逐字同形**, 只差
    ``http_requests`` (离线 0 / 真发 1)。信封一旦分家, E 门的关键断言
    短语就有两处可改, 漏一处就出现"两个适配器给出不同结构"的静默分叉。

    Args:
        result: 客户端查询结果对象 (读取 total_count/returned_count/success/
            truncated/error_code/query_params)。
        rows: 已转 dict 的行集。
        http_requests: 本次执行真实发出的 HTTP 次数 (成本段口径)。

    Returns:
        四段式结果信封。
    """
    return {"data": {"rows": rows, "total_count": result.total_count,
                     "returned_count": result.returned_count},
            "status": {"ok": result.success, "truncated": result.truncated,
                       "error_code": result.error_code},
            "cost": {"http_requests": http_requests, "rows_returned": len(rows)},
            "provenance": {"session_id": result.query_params.get("sqlid"),
                           "stable_uri": "", "data_hash": "", "lineage": {}}}


class _ToolFaceAdapter:
    """工具面适配器公共基类: 执行调用序列 → 信封/行/声称值/成本。

    子类只实现 ``_invoke`` (单个工具怎么调)。回放接线、sqlid 回填、
    ``reported`` 结构化、成本计数都在这里 — 三个工具面因此共用同一套
    观测口径 (否则"同一把尺子量九次"不成立)。
    """

    face = "toolbox"   # 类属性: 子类覆盖, 值进 trace 的 tool_face 字段

    def __init__(self, system: dict, transport: Any = None) -> None:
        """记住装配与回放传输层 (transport 缺省表示不接回放 — 禁真实网络)。"""
        self.system = system                                                                        # 同样存下装配: 本适配器的工具面由它决定
        self.components: dict = system.get("components") or {}
        self.transport = transport   # None = 不接回放, 真实网络即被禁
        self._threshold = float(load_null_sentinel()["threshold"])   # 哨兵阈值取共享字典 (带三键校验与批内缓存), 各处硬编码才是漂移源
        self._client = None    # 惰性建: 脚本适配器全程不建客户端
        self._toolbox = None   # 同上, 且裸协议面即使建了 client 也不建它

    def _snapshot_id(self, item: dict) -> Optional[str]:
        """本题的数据锚点 (D 类快照名; 非 D 类返 None)。"""
        anchor = item.get("data_anchor") or {}   # 只有 kind=snapshot 才当锚点, 别的没有回放可指
        return anchor.get("ref") if anchor.get("kind") == "snapshot" else None

    def _wire(self, with_toolbox: bool) -> None:
        """惰性建 BestClient (可选 ToolBox) 并接回放; 每次运行一份, 计数器不串。"""
        if self._client is not None:   # 每运行一份: 计数不跨 run 串, 否则成本口径会漂
            return
        # 本地: 被测客户端 (裸协议工具面的执行体)
        from src.client import BestClient

        client = BestClient(base_url="http://snapshot.local", rate_limit=0.0)
        if self.transport is not None:   # 换 session.get/post: 客户端代码一行不改
            client.session.get = self.transport.get                                              # 读路径挂上回放: 装的是传输层, 客户端照常用
            client.session.post = self.transport.post                                            # 写路径同样挂回放: 漏挂会让建会话打到真实站点
        self._client = client   # 先存 client, ToolBox 构造还要拿它
        if with_toolbox:                                                                   # 工具箱可选装: 无工具面系统不装它, 工具类指标才记不适用
            # 本地: agent 工具面 (SkillToolBoxAdapter 的 7 工具入口)
            from src.ai_tools import ToolBox

            self._toolbox = ToolBox(client)   # with_toolbox=False 时留 None, 裸协议面不用

    def _invoke(self, tool: str, args: dict, item: dict) -> dict:
        """执行单个工具调用, 返回原始返回 (信封 dict 或裸行 dict)。"""
        raise NotImplementedError

    def execute(self, item: dict, calls: list[dict], route: str) -> RunOutcome:
        """跑完一条任务: 逐个调用 → 汇总行集 → 结构化声称值 → 成本。"""
        started = time.monotonic()   # monotonic: 系统时钟回拨不该算出负耗时
        outcome = RunOutcome(route=route, tool_calls=list(calls))   # list() 复制, 不改调用方的
        session_id: Optional[str] = None                                                            # 会话号先备空: 只有非幂等调用才会有值
        for call in calls:                                                                      # 逐调用执行: 一次调用一个信封, 顺序即编排顺序
            args = dict(call.get("args") or {})   # 每次一份副本: sqlid 回填不污染标注
            if args.get("sqlid") in (None, "", SQLID_PLACEHOLDER):
                args["sqlid"] = session_id or ""   # 回填上一信封: 首轮空串, 与生产同
            before = self.transport.call_count if self.transport is not None else 0                # 记调用前计数: 请求数按差值算, 不靠估算
            try:
                if call["tool"] in DATA_TOOLS and self._snapshot_id(item) is None:
                    # 离线纪律: 无数据锚点的任务 (C/R 类零请求设计) 一律不发请求
                    raise OfflineNoAnchor(call["tool"])
                raw = self._invoke(call["tool"], args, item)   # 三个工具面唯一的分歧点
            except OfflineNoAnchor as blocked:
                raw = {"data": {"error": f"offline: {blocked} 无数据锚点, 未发请求"},
                       "status": {"ok": False, "error_code": "E_BACKEND"},
                       "cost": {"http_requests": 0}, "provenance": {}}
                outcome.notes.append(f"{call['tool']} 被离线纪律拦截 (无数据锚点)")
            except Exception as exc:  # noqa: BLE001 — 失败本身是被测行为
                raw = {"status": {"ok": False, "error_code": "E_BACKEND"},
                       "data": {"error": f"{type(exc).__name__}: {exc}"},
                       "cost": {"http_requests": 0}, "provenance": {}}
                outcome.notes.append(f"{call['tool']} 抛异常: {type(exc).__name__}")
            outcome.envelopes.append(raw)   # 逐调用留信封: 判定要定位"哪一次调用出的错"
            # 实测兜底: ToolBox 的计数器包 session.request, 回放替换的是 get/post,
            # 声明值可能恒 0 — 以 transport 的调用计数为下界 (成本字段才可复核)
            measured = (self.transport.call_count - before) if self.transport is not None else 0  # 本次调用的实测请求数: 成本口径的分子, 要写进 run 记录
            outcome.http_requests += max(   # 声明值与实测取大: ToolBox 的自报计数可能恒 0
                int((raw.get("cost") or {}).get("http_requests") or 0), measured)
            sid = (raw.get("provenance") or {}).get("session_id")   # A4 关掉后恒 None
            if sid:   # 有 session 才回填: 空串/None 不该覆盖上一个有效值
                session_id = sid                                                              # 会话号记下来: 重复提交同一会话是孤儿会话判据的现场
            rows = (raw.get("data") or {}).get("rows")
            if rows:                                                                                # 有行才进首行与行键: 空结果没有首行可取
                outcome.rows.extend(rows)   # 跨调用累加: 多次翻页拼成一个结果集
        outcome.reported = self._summarise(item, outcome)   # 末尾一次性汇总, 与 rows 同时点
        outcome.elapsed_s = round(time.monotonic() - started, 6)   # 6 位小数: 免浮点噪声
        return outcome

    def _claim_row(self, row: dict) -> dict:
        """系统声称的行: 哨兵值与空格归一成 None (缺失不当值, 不当 0)。"""
        claimed = {}   # 逐列归一: 哨兵与空格一律记缺失, 不记 0
        for column, value in row.items():   # 列名原样保留: 剥前缀是渲染层的事
            claimed[column] = (None if value in (None, "")
                               or is_sentinel_value(column, value, self._threshold)            # 哨兵值在清洗时就剔掉: 免得它后面被当真值参与均值
                               else value)                                                    # 非哨兵才留原值: 清洗口径与判定口径必须用同一份阈值
        return claimed

    def _summarise(self, item: dict, outcome: RunOutcome) -> dict:
        """把原始返回汇总成"系统声称"的结构化结果 (消融效应在此显现)。"""
        primary = outcome.envelopes[0] if outcome.envelopes else {}   # 缺省取首个, 下面再改选
        for envelope in outcome.envelopes:   # 选"有行或报错"的那一个: 后续翻页不作主
            status = envelope.get("status") or {}
            if not status.get("ok", True) or (envelope.get("data") or {}).get("rows") is not None:
                primary = envelope                                                                # 主信封取第一个: 多次调用时以首个响应为口径
                break
        status = primary.get("status") or {}
        data = primary.get("data") or {}
        prov = primary.get("provenance") or {}
        rows = outcome.rows                                                                         # 行集现取: 后面几项判定都以它为事实源
        state = "error" if not status.get("ok", True) else ("rows" if rows else "empty")
        total = data.get("total_count")   # 信封声明值, 未必等于实际行数 (A5 的断链处)
        returned = data.get("returned_count", len(rows))   # 缺则按实得兜底, 不记 0
        truncated = bool(status.get("truncated"))   # 先取声明值, A5 分支会抹成 false
        # A5: 结果后验证被拆掉 → 截断三元组不再对账 (truncated 一律报 false,
        # returned 当成 total 报告); 哨兵不当缺失
        if not self.components.get("post_verify"):
            truncated = False   # 抹掉截断标记: 截断被当成全量, 正是 A5 的核心滑坡
            total = returned    # total 顶成 returned: 三元组看着自洽, 失配就再也查不出
        # A4: provenance 被拆掉 → 信封不带来源键, 答案无法声明快照与 URI
        if not self.components.get("provenance"):
            prov = {}   # 抹掉来源段: stable_uri 与 snapshot_id 随之为空
        first_args = (outcome.tool_calls[0].get("args") or {}) if outcome.tool_calls else {}
        page_size = int(_arg(first_args, "page_size", 1000))   # 从首个调用反推, 决定页数估算
        pages = math.ceil((returned or 0) / page_size) if returned else 0   # 空结果记 0 页
        sentinels_present = extra_page_empty = False   # 双标志: 循环只置位不清零
        for row in rows:                                                                      # 逐行数哨兵: 被剔除的条数要如实上报, 不能悄悄消失
            sentinels_present = sentinels_present or any(   # 只看有无, 不计数
                is_sentinel_value(c, v, self._threshold) for c, v in row.items())            # 行内任一列命中即算脏行: 阈值按列豁免表判, 不是按行
        extra_page_empty = any(   # fetch_page 返回空页 = 翻页已到头
            call.get("tool") == "fetch_page" and not (env.get("data") or {}).get("rows")
            for call, env in zip(outcome.tool_calls, outcome.envelopes))                       # 调用与信封配对统计: 两者不同序就说明编排中间有漏
        # post_verify 开 → 声称的行把哨兵/空格归一成 None (缺失不当值);
        # A5 关掉后验证 → 哨兵原样进"声称值" (取数门字段一致率因此掉分)
        claimed = ([self._claim_row(row) for row in rows]   # 归一与否全看 post_verify 开关
                   if self.components.get("post_verify") else rows)
        return {
            "state": state, "error_code": status.get("error_code"), "rows": claimed,
            "row_count": len(rows), "pages": pages, "extra_page_empty": extra_page_empty,
            "total_count": total if total is not None else len(rows),
            "returned_count": returned if returned is not None else len(rows),
            "truncated": truncated, "stable_uri": prov.get("stable_uri"),   # 两段都可能被 A4/A5 抹空
            "session_id": prov.get("session_id"),
            "snapshot_id": self._snapshot_id(item) if self.components.get("provenance") else None,
            "sentinels_removed": sentinels_present and bool(self.components.get("post_verify")),
            "tool_face": self.face,   # 进 trace: 报告要能分辨结论出自哪个工具面
        }


class SkillToolBoxAdapter(_ToolFaceAdapter):
    """生产 7 工具面 (src/ai_tools.py ToolBox) — B3/A2/A3/A4/A5 走这条。

    ``param_validation=false`` (A1/B2b) 时绕过 guards 与 schema 约束段:
    改走 ``BestClient.submit_query`` 的手拼表单缝, 非法参数原样下发 —
    这正是 A1 的消融语义 ("非法参数原样下发", §4 A1 行)。
    """

    face = "toolbox"

    def _invoke(self, tool: str, args: dict, item: dict) -> dict:
        """调 7 工具之一; 校验旁路时走 submit_query 手拼表单缝。"""
        self._wire(with_toolbox=True)   # 每次调用前保证接线: 客户端可能被别的面先建过
        box = self._toolbox              # 短别名: 下面七条工具分支都要它
        if tool == "list_catalogs":
            return box.list_catalogs().to_dict()
        if tool == "describe_catalog":
            return box.describe_catalog(str(args.get("catalog") or "ps1")).to_dict()
        if tool == "resolve_name":
            return box.resolve_name(str(args.get("name") or "")).to_dict()
        if tool == "count":
            return box.count(str(args.get("sqlid") or "")).to_dict()
        if tool == "fetch_page":
            return box.fetch_page(
                str(args.get("sqlid") or ""), page=int(args.get("page") or 1),
                page_size=int(_arg(args, "page_size", 1000)),
                catalog=str(args.get("catalog") or ""),
                max_rows=args.get("max_rows")).to_dict()
        if tool == "crossmatch_batch":
            coords = args.get("coords") or []
            return box.crossmatch_batch(
                coords=[{"ra": float(c["ra"]), "dec": float(c["dec"])} for c in coords],
                catalog=str(args.get("catalog") or "ps1"),
                radius_arcsec=float(_arg(args, "radius_arcsec", 3.0)),
                nearest_only=bool(args.get("nearest_only", True)),
                max_rows=int(_arg(args, "max_rows", 50000))).to_dict()
        if tool == "cone_search":
            if self.components.get("param_validation"):   # 校验在 ⇒ 走 ToolBox 正规入口
                return box.cone_search(
                    ra=float(args["ra"]), dec=float(args["dec"]),
                    radius_arcsec=float(_arg(args, "radius_arcsec", 180.0)),
                    catalog=str(args.get("catalog") or "ps1"),
                    columns=args.get("columns"), sort=args.get("sort"),
                    order=str(args.get("order") or "asc"),
                    nearest_only=bool(args.get("nearest_only", False)),
                    max_rows=int(_arg(args, "max_rows", 1000))).to_dict()
            return self._unvalidated_cone(args)   # A1 旁路: 手拼表单绕过 guards 直发
        return {"status": {"ok": False, "error_code": "E_INVALID_INPUT"},
                "data": {"error": f"unknown tool: {tool}"}, "cost": {}, "provenance": {}}

    def _unvalidated_cone(self, args: dict) -> dict:
        """A1 消融缝: 手拼 phase-1 表单经 submit_query 下发, 不经 guards。"""
        result = self._client.submit_query(                                                         # 走客户端真提交: 工具面差异在这一层体现
            catalog=str(args.get("catalog") or "ps1"), form_data=_cone_form(args),
            max_rows=int(_arg(args, "max_rows", 1000)),
            page_size=int(_arg(args, "page_size", 1000)))
        rows = [s.to_dict() for s in result.sources]   # 逐源转 dict, 行集口径与另两面一致
        return _result_envelope(result, rows, 0)   # 声明 0: 成本由基类的 transport 实测兜底


class RawProtocolAdapter(_ToolFaceAdapter):
    """BestClient 裸协议面 (不经 ToolBox) — B2a 走这条。

    与 SkillToolBoxAdapter 的差别: 不建 ToolBox, 也不做参数校验 (B2a 装配表
    该列为 —); 协议调用按语义映射到最近邻工具名记录, 以便 ToolSetF1 可比
    (trace 里 tool_face=raw_protocol 显式标注)。
    """

    face = "raw_protocol"

    def _invoke(self, tool: str, args: dict, item: dict) -> dict:
        """裸协议执行: 锥搜/proximity 走 submit_query, count 走 client.count。"""
        self._wire(with_toolbox=False)                                                      # 不装工具箱: 这一支验证裸接口面, 工具类指标应为不适用
        if tool == "count":   # count 直达 client: ToolBox 里没有对应工具
            total = self._client.count(str(args.get("sqlid") or ""))
            return {"data": {"sqlid": args.get("sqlid"), "total": total},
                    "status": {"ok": total is not None, "truncated": False,
                               "error_code": None},
                    "cost": {"http_requests": 1}, "provenance": {}}
        if tool == "crossmatch_batch":
            coords = args.get("coords") or []   # 坐标对拆成 ra/dec 两条并行数组 (裸协议签名)
            result = self._client.crossmatch_batch(   # 直调 client: 不经 ToolBox 的参数校验
                ra_list=[float(c["ra"]) for c in coords],
                dec_list=[float(c["dec"]) for c in coords],
                catalog=str(args.get("catalog") or "ps1"),
                radius_arcsec=float(args.get("radius_arcsec") or 3.0),
                nearest_only=bool(args.get("nearest_only", True)),
                max_rows=int(_arg(args, "max_rows", 50000)))
        elif tool in ("cone_search", "fetch_page"):
            result = self._client.submit_query(                                                     # 同上一支: 裸接口面的查询入口
                catalog=str(args.get("catalog") or "ps1"), form_data=_cone_form(args),
                max_rows=int(_arg(args, "max_rows", 1000)),
                page_size=int(_arg(args, "page_size", 1000)))
        else:
            return {"status": {"ok": False, "error_code": "E_INVALID_INPUT"},
                    "data": {"error": f"raw protocol has no {tool}"},
                    "cost": {}, "provenance": {}}
        rows = [s.to_dict() for s in result.sources]   # 同另两个面的行集口径, 三面才可比
        return _result_envelope(result, rows, 1)   # 声明 1: 裸协议确实发了请求


class ScriptedAdapter(_ToolFaceAdapter):
    """预写调用序列 + 快照 CSV 直读 — R0 式离线确定性跑 (不建客户端)。

    覆盖边界 (诚实声明): 只覆盖**能用快照 CSV 回答**的调用 (锥搜/proximity/
    count/fetch_page/list/describe); resolve_name 需 CDS Sesame 属 live 路,
    不在离线覆盖内。存在意义: 无 requests/无 src 依赖的环境下仍能跑通
    "任务 → 装配 → 三门 → 归因" 全管线, 并作为真模型跑批的确定性基线。
    """

    face = "scripted"

    def __init__(self, system: dict, transport: Any = None) -> None:
        """不建客户端; 直接读快照目录 (transport 仅为成本计数保留)。"""
        super().__init__(system, transport)                                                      # 复用基类装配: 快照传输层与公共字段不在此重写
        self._rows_cache: dict[str, list[dict]] = {}   # 缓存: 一个系统跑 30 任务不该重读 30 次
        self._last_selection: list[dict] = []   # 最近一次空间过滤的结果, count 问的就是它的行数

    def _load(self, snapshot_id: str) -> list[dict]:
        """读快照 rows_full.csv (utf-8-sig 保真; 缺失即空 — 错误态快照)。"""
        if snapshot_id in self._rows_cache:   # 命中即返回, 空集也缓存: 缺失只读一次
            return self._rows_cache[snapshot_id]
        path = SNAPSHOTS_DIR / snapshot_id / "rows_full.csv"
        rows: list[dict] = []   # 缺文件即空: 错误态快照也要能产出一条确定 trace
        if path.is_file():                                                                  # 快照文件不存在按空行集: 缺快照时"0 行"才是真实结论
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                rows = [dict(r) for r in csv.DictReader(handle)]                           # 每行转普通字典: 后续按列名取值不依赖 reader 状态
        self._rows_cache[snapshot_id] = rows                                                     # 按快照号缓存: 同一快照多题跑批时不必重复读盘
        return rows

    def _invoke(self, tool: str, args: dict, item: dict) -> dict:
        """按查询语义对快照行集现场算答案 (haversine 独立实现, 不信 GT)。"""
        snapshot_id = self._snapshot_id(item)                                                      # 快照号由题目数据锚推导: 不从命令行参数取
        if tool in ("list_catalogs", "describe_catalog", "resolve_name"):
            return {"data": {"rows": [], "note": f"{tool} 零请求/离线替身"},
                    "status": {"ok": True, "truncated": False, "error_code": None},
                    "cost": {"http_requests": 0}, "provenance": {}}
        if snapshot_id is None:  # 无数据锚点 (C/R 类零请求设计)
            return {"data": {"error": "no data anchor"}, "cost": {"http_requests": 0},
                    "status": {"ok": False, "error_code": "E_BACKEND"}, "provenance": {}}
        # 参数校验层 (A1 消融缝): param_validation=true 时按 guards.py 合法域
        # 预检, 非法参数显式 E_INVALID_INPUT 且**不发请求**; false (A1/B2a/B2b)
        # 时旁路 — 非法参数原样进入查询语义 (零半径 → 空行集冒充合法结果,
        # 正是 A1 预登记的滑坡形态)。
        if self.components.get("param_validation"):
            illegal = illegal_param_reason(args)                                       # 参数预检: 非法参数原样下发正是 A1 要量的滑坡, 这里只判不拦
            if illegal:                                                                     # 非法即记: 消融系统仍会把参数发下去, 越界由判定门记账
                return {"data": {"error": illegal}, "cost": {"http_requests": 0},
                        "status": {"ok": False, "error_code": "E_INVALID_INPUT"},
                        "provenance": {}}
        if tool == "count":
            # count 只认 sqlid — 语义上问的是"上一个查询会话的服务端总数"
            total = len(self._last_selection)                                                    # 总数取本地选中集: 少返与多返要能被取数门对账
            return {"data": {"sqlid": args.get("sqlid"), "total": total},
                    "status": {"ok": True, "truncated": False, "error_code": None},
                    "cost": {"http_requests": 1}, "provenance": {}}
        selected = self._select(snapshot_id, args)   # 现场按查询语义过滤, 不信快照里的 GT 标记
        self._last_selection = selected               # 记住: 紧随的 count 只能这样算总数
        page_size = int(_arg(args, "page_size", 1000))   # 分页按调用参数切, 不按 CSV 原始行序
        max_rows = int(_arg(args, "max_rows", page_size))   # 缺省即页大小: 单页即上限
        page = int(_arg(args, "page", 1))
        if page > 1:   # 显式翻页: 直接切片, 不重跑前面的页
            collected = selected[(page - 1) * page_size: page * page_size]                     # 单页切片: 页序与页长都按请求参数走, 不自行归一
        else:
            # 复刻 _fetch_sqlid_data 的分页循环: 翻到短页或撞 max_rows 即停
            collected = []                                                               # 越界页给空: 与站点末页之后的形态一致, 客户端据此判续取终止
            current = 1                                                                             # 游标从第一页起: 整表取回按页序累加
            while len(collected) < max_rows:   # 撞上限即停, 与生产分页循环同
                chunk = selected[(current - 1) * page_size: current * page_size]                 # 逐页切片: 页序错了会静默漏行, 所以按游标推
                if not chunk:   # 空块 = 已翻过头, 直接收尾
                    break
                collected.extend(chunk)                                                           # 累加当页: 顺序即返回顺序, 行集口径依赖它
                if len(chunk) < page_size:   # 短页即最后一页, 再翻只会拿到空块
                    break
                current += 1                                                                        # 页游标前移: 循环条件在下一轮重新判空
        return {"data": {"rows": collected, "total_count": len(selected),
                         "returned_count": len(collected)},
                "status": {"ok": True, "truncated": len(selected) > len(collected),
                           "error_code": None},
                "cost": {"http_requests": 2, "rows_returned": len(collected)},
                "provenance": {"session_id": "s0001"}}

    def _select(self, snapshot_id: str, args: dict) -> list[dict]:
        """空间过滤 (cone/proximity) + 最近邻 + 排序 (协议语义的精简落实)。"""
        rows = self._load(snapshot_id)   # 行集来自缓存的 CSV, 完全不经客户端
        coords = args.get("coords")      # 有 coords 即 proximity 语义: 按 input_line 取最近邻
        if coords:                                                                                  # 有坐标输入才做就近: 无输入时原样放行
            best: dict[int, dict] = {}                                                             # 按输入行号分组: 一个输入坐标对应一行结果
            for row in rows:                                                                        # 逐行归组: 行号即分组键, 不按内容聚类
                line = int(float(row.get("inputobjs_input_line") or 0))
                dist = to_float(row.get("inputobjs_dist_arcsec"))
                current = best.get(line)                                                          # 取出该输入行当前的最近候选, 后面与它比角距
                if current is None or (dist is not None and dist < to_float(                # 角距更小才替换: 距离缺失时让位, 不可比的行不当最近邻
                        current.get("inputobjs_dist_arcsec"))):
                    best[line] = row                                                                # 记下当前最优: 遍历结束即每行一个最近邻
            return [best[k] for k in sorted(best)]
        ra_c = to_float(args.get("ra"))   # 锥心/半径缺任一就无法判空间, 原样返回全部
        dec_c = to_float(args.get("dec"))
        radius = to_float(args.get("radius_arcsec"))
        if ra_c is None or dec_c is None or radius is None:   # C 类零请求设计的合法形态
            return list(rows)
        kept = [r for r in rows                                                               # 锥形过滤用角秒比: 不用弦长近似, 免得边界行被误剔
                if haversine_arcsec(ra_c, dec_c, *coord_of(r)) <= radius]                         # 含等号: 边界角距(正好等于半径)必须收进来
        sort = args.get("sort")
        if sort:   # 只在显式 sort 时排序: 顺序本身也是判据, 不给就不动
            kept.sort(key=lambda r: to_float(column_of(r, str(sort))) or 0.0,               # 按排序列排序: 不可解析值按 0 排, 免得排序时抛异常
                      reverse=str(args.get("order") or "asc") == "desc")
        return kept


def make_adapter(system: dict, transport: Any = None) -> _ToolFaceAdapter:
    """按系统装配的 tool_face 建适配器 (b0/b1 无工具面也返回脚本适配器)。"""
    face = system.get("tool_face") or "scripted"   # 缺省 scripted: b0/b1 也走它, 批次不断
    if face == "toolbox":
        return SkillToolBoxAdapter(system, transport)   # 生产 7 工具面: B3 与 A2..A5
    if face == "raw_protocol":
        return RawProtocolAdapter(system, transport)   # 裸协议面: B2a, 不建 ToolBox
    return ScriptedAdapter(system, transport)   # 兜底不抛: 未知 face 不该中断整批


def make_llm(system: dict, capture: Optional[dict] = None) -> LLMAdapter:
    """建模型层: 有采集表走真模型回放, 否则回 ScriptedLLM 替身。

    Args:
        system: 装配字典。
        capture: 真模型采集表 (形态见 captured_llm 模块头); 缺省/None 即替身批。

    Returns:
        ``CapturedLLM`` (live 臂) 或 ``ScriptedLLM`` (离线替身批)。

    本函数是模型层的**唯一**构造点, 留缝即在这里: 真模型实现同名接口即可热替换,
    调用点零改动 (E5 §14 记的"接真模型是待写代码"由 captured_llm 落地)。
    就地导入 captured_llm 是不想在此模块顶部就把它拉进来 —— 替身批不该为
    live 臂的依赖付费。
    """
    if capture is not None:  # 给了采集表就是 live 臂: 换实现, 判据与执行层一律不动
        from evals.ablation.harness.captured_llm import CapturedLLM  # noqa: PLC0415 — 就地导入避免替身批拖入 live 依赖
        return CapturedLLM(system, capture)
    return ScriptedLLM(system)   # 留缝: 真模型实现同名接口即可换, 调用点零改动


def trace_fingerprint(outcome: RunOutcome) -> str:
    """轨迹指纹 (E6 同款口径): 同一 (items, 系统) 重复跑必须逐字节一致。"""
    payload = {"route": outcome.route, "tool_calls": outcome.tool_calls,   # 只对行为事实取指纹
               "rows": outcome.rows,
               "reported": {k: v for k, v in outcome.reported.items() if k != "rows"},
               "answer_text": outcome.answer_text,
               "http_requests": outcome.http_requests}
    return stable_hash(payload)   # 稳定哈希: 不逐字节一致就不得谈显著性
