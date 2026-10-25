# -*- coding: utf-8 -*-
"""evals.repro.r0_lane — R0 路 (工具层固化回放) 执行件: 无模型, 预写调用序列直打工具。

能力边界: R0 是四路对照的**地板线** (文档 §2.1) — 模型/网络/服务端/时间全部
冻住, 只有代码与环境在跑; 连 R0 都不一致 = 代码层确定性 bug (立即阻断)。
本件按预写调用序列 (agent 的固化替身) 经 ReplayTransport 打真实客户端,
采集每次运行的调用/结果/成本/结论卡供四一致率计算。

覆盖边界 (诚实声明): R0 只覆盖**工具层确定性任务** (cone/count/fetch_page/
list/describe/reject-guard); 需 LLM 决策的任务 (clarify/reject-utterance/
safety) 属 R1/R3 路范围, 不在离线 R0 覆盖内 — 覆盖率在报告中显式披露,
不冒充 100%。

白盒锚点: docs/eval-E6-reproducibility.md §2.1 (R0 定义) / §11 (执行流程);
evals/repro/transport.py (回放底座); fixtures/ (固化快照)。

职责: 跑 E6 四路对照里的**地板线** R0 —— 用预写调用序列 (agent 的固化替身)
  经 ReplayTransport 打真实客户端, 采集每次运行的调用/结果/成本/结论卡,
  为 TSC/PAC/RDC/FCC 四个一致率提供数据。
所属实验: E6 可复现与效率 (32 任务 + R0 路实跑); R0 的定义与定位真值是
  docs/eval-E6-reproducibility.md §2.1, 执行流程见 §11, 回放底座是
  evals/repro/transport.py, 快照在 fixtures/。
对外接口: run_once(task_id, fixture, sequence, attempt) 跑一次并返回 run
  记录; run_lane(task_ids, repeat) 跑整路并附覆盖率披露; 内部
  _rows_hash / _row_keys 为 RDC 提供数据指纹与行主键集; R0_SEQUENCES 是
  预写调用序列的登记表。
依赖与数据流: 输入 = fixtures/ 下的快照目录 + R0_SEQUENCES 里预写的调用
  序列; 产物 = 逐次运行的记录字典 (含 cost/card/data_hash/row_keys), 被
  evals/repro/consistency/* 消费后汇入报告, 自身不落盘。
关键契约与不变量: 零网络 — session 的 get/post 被整体换成回放实现, R0 的
  rate_limit 恒 0.0, 跑多少次都不产生一次真实往返; 同一序列重复跑必须
  得到逐字段相同的记录, 这是 R0 作为"地板线"的前提 —— 连它都不一致就
  只能怪代码, 没有任何外部因素可以解释; 零跨实验 import (只引
  evals.repro 内部件与 src.client), 与其它实验的等价性由
  evals/equivalence/ 的断言守护。
陷阱与边界: R0 只覆盖工具层确定性任务, 需 LLM 决策的那批 (clarify /
  reject-utterance / safety) 不在离线覆盖内 —— 覆盖率在 run_lane 的
  coverage 里显式给出, 绝不冒充 100%。服务端软 404 必须记 fail 而不是
  "成功但 0 行" (D-3 / ERROR→EMPTY, REPRO-30 明令), 因为那会让拒绝路径
  的确定性无从检验: 静默变空看起来和"真的没数据"完全一样。
"""
from __future__ import annotations

# 标准库: 哈希 (data_hash) / 时间 / 路径
import hashlib

# 本地: 回放传输层 (自包含) 与 skills 根锚定
import sys
import time
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # 挂仓根, 让 src.client 与 evals.repro 按包路径导入
# 本地: 自包含回放 (预写序列的传输面)
from evals.repro.transport import ReplayTransport  # noqa: E402

REPRO_DIR = Path(__file__).resolve().parent  # 按本文件定位: 换机换 cwd 都不影响
FIXTURES_DIR = REPRO_DIR / "fixtures"  # 固化快照根: R0 的全部 IO 都在这下面, 别处不读

# R0 预写调用序列 (agent 固化替身): task_id → (fixture, 调用序列)
# 调用序列每项: (tool, kwargs, page?) — page 仅 fetch_page 用
R0_SEQUENCES: dict[str, tuple[str, list[dict]]] = {  # 预写序列登记表: agent 在 R0 里的固化替身
    "REPRO-01": ("ps1_5rows", [{"tool": "list_catalogs", "args": {}}]),
    "REPRO-02": ("ps1_5rows", [{"tool": "describe_catalog", "args": {"catalog": "ps1"}}]),
    "REPRO-04": ("ps1_5rows", [{"tool": "cone_search", "args": {
        "ra": 180.0, "dec": 30.0, "radius_arcsec": 60.0, "catalog": "ps1",
        "max_records": 10, "page_size": 1000}}]),
    "REPRO-05": ("ps1_5rows", [{"tool": "crossmatch_batch", "args": {
        "ra_list": [180.0, 181.0], "dec_list": [30.0, 31.0], "catalog": "ps1",
        "radius_arcsec": 3.0}}]),
    "REPRO-06": ("ps1_5rows", [
        {"tool": "cone_search", "args": {"ra": 180.0, "dec": 30.0,
                                         "radius_arcsec": 60.0, "catalog": "ps1"}},
        {"tool": "count", "args": {}}]),
    "REPRO-08": ("ps1_singlepage", [
        {"tool": "cone_search", "args": {"ra": 180.0, "dec": 30.0,
                                         "radius_arcsec": 5.0, "catalog": "ps1",
                                         "page_size": 5}},
        {"tool": "fetch_page", "args": {"page": 2}}]),
    "REPRO-10": ("ps1_5rows", [{"tool": "cone_search", "args": {
        "ra": 180.0, "dec": 30.0, "radius_arcsec": 300.0, "catalog": "ps1"}}]),
    "REPRO-11": ("scr_galah_0rows", [{"tool": "cone_search", "args": {
        "ra": 120.3, "dec": -20.4, "radius_arcsec": 5.0, "catalog": "scr_galah"}}]),
    "REPRO-12": ("ps1_5rows", [{"tool": "cone_search", "args": {
        "ra": 180.0, "dec": 30.0, "radius_arcsec": 1800.0, "catalog": "ps1"}}]),
    "REPRO-14": ("ps1_5rows", [{"tool": "cone_search", "args": {
        "ra": 187.5, "dec": 20.0, "radius_arcsec": 60.0, "catalog": "ps1"}}]),
    "REPRO-15": ("ps1_5rows", [{"tool": "cone_search", "args": {
        "ra": 180.0, "dec": 30.0, "radius_arcsec": 60.0, "catalog": "gaia_dr3_18",
        "columns": ["gaia_dr3_18_phot_g_mean_mag"]}}]),
    "REPRO-16": ("ps1_5rows", [{"tool": "cone_search", "args": {
        "ra": 180.0, "dec": 30.0, "radius_arcsec": 60.0, "catalog": "splus_dr4",
        "columns": ["splus_dr4_r_pstotal"]}}]),
    "REPRO-21": ("ps1_5rows", [{"tool": "cone_search", "args": {
        "ra": 180.0, "dec": 30.0, "radius_arcsec": 60.0, "catalog": "ps1",
        "sort": "ps1_rpsf", "order": "asc"}}]),
    "REPRO-27": ("ps1_singlepage", [
        {"tool": "cone_search", "args": {"ra": 180.0, "dec": 30.0,
                                         "radius_arcsec": 5.0, "catalog": "ps1",
                                         "page_size": 5}},
        {"tool": "fetch_page", "args": {"page": 2}}]),
    "REPRO-28": ("ps1_singlepage", [
        {"tool": "cone_search", "args": {"ra": 180.0, "dec": 30.0,
                                         "radius_arcsec": 5.0, "catalog": "ps1",
                                         "page_size": 5}},
        {"tool": "count", "args": {}}]),
    "REPRO-30": ("soft404", [{"tool": "cone_search", "args": {
        "ra": 180.0, "dec": 30.0, "radius_arcsec": 60.0, "catalog": "stripe82"}}]),
    # REPRO-31 用 20000 角秒的大半径: 覆盖服务端"半径过大直接拒绝"这条
    # 守卫路径, 与 REPRO-12 的 1800 角秒(合法)构成边界对照
    "REPRO-31": ("ps1_5rows", [{"tool": "cone_search", "args": {
        "ra": 180.0, "dec": 30.0, "radius_arcsec": 20000.0, "catalog": "ps1"}}]),
    "REPRO-32": ("ps1_5rows", [  # 唯一的多调用元数据任务: 两次零请求调用
        {"tool": "list_catalogs", "args": {}},
        {"tool": "describe_catalog", "args": {"catalog": "ps1"}}]),
}


def _rows_hash(rows: list[dict]) -> str:
    """行集数据指纹 (规范化 JSON 的 sha256; 供 RDC L1 与 data_hash 用)。

    作用: 给"拿回来的数据本身"一个指纹。关键参数 rows 是累计的行字典
    列表。Returns: "sha256:" 前缀的十六进制串。抛什么: 不抛。
    """
    # 标准库: 成本 JSON 读取 (进度/请求数的记录面)
    import json

    # sort_keys 让行内字段序不影响指纹: 同一份数据由不同代码路径构造出的
    # 键序可能不同, 不排序就会让 RDC 的 L1 档凭空判漂移
    canonical = json.dumps(rows, sort_keys=True, ensure_ascii=False, default=str)  # default=str 兜住非 JSON-native 值: 少了它会在算指纹时炸
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()  # 行序也进指纹: L1 档的严格性来源


def _row_keys(rows: list[dict]) -> set:
    """行主键集 (source_id 优先; 与 E2 canonical 同口径的本地精简实现)。

    作用: 给 RDC 的 L2 档提供行身份。关键参数 rows 是累计行字典。
    Returns: 字符串集合。抛什么: 不抛。
    """
    keys = set()                                                                               # 集合语义: 同一批行重复出现不该让 L2 判成漂移
    for row in rows:                                                                            # 逐行取身份: 身份策略分两支, id 优先于坐标
        # source_id 优先: 它是 BEST 的稳定跨表标识, 比坐标更抗精度差异
        sid = row.get("source_id") or row.get("ps1_source_id")
        if sid not in (None, ""):  # 空串与 None 同义: 两者都不是合法行标识
            keys.add(str(sid))                                                          # 统一转字符串: id 可能是数字也可能是串, 不能按原类型入集合
        else:
            # 退化到坐标对: 没有 id 的行只能靠位置辨认, 精度不同的两次
            # 运行会在 L2 档被判不一致 —— 这正是 L2 比 L1 宽松的代价,
            # 报告要能解释这种漂移从哪来
            keys.add(f"{row.get('ra')},{row.get('dec')}")
    return keys


def run_once(task_id: str, fixture: str, sequence: list[dict],
             attempt: int = 1) -> dict:
    """执行一次 R0 运行 (回放 + 采集); 返回 run 记录。

    Args:
        task_id: REPRO-nn。
        fixture: fixtures/ 下的快照名。
        sequence: 预写调用序列。
        attempt: 第几次尝试 (R0 一般为 1; 重跑递增)。

    Returns:
        ``{"task_id", "tool_calls", "results", "cost", "card", "outcome",
        "data_hash", "row_keys", "events"}``。
    """
    from src.client import BestClient  # 延迟导入: 脚本直跑时才拉重依赖

    # 每次运行新建 transport: call_count 是 per-run 计数, 复用同一个实例
    # 会让第二次运行的请求数从上次累计, EF1 的分母就全错了
    transport = ReplayTransport(FIXTURES_DIR / fixture)                        # 每次运行新建回放口: call_count 是 per-run 计数, 复用会累计
    client = BestClient(base_url="http://replay.local", rate_limit=0.0)  # 节流恒 0: R0 测的是纯代码耗时
    # 整体替换 session 的两个方法而非改 client 的实现: 被测链路一行不用改,
    # 就这样在完全离线的前提下跑的是真实客户端而不是替身
    client.session.get = transport.get                                                            # 换网卡不换客户端: 跑的是真实链路而不是替身
    client.session.post = transport.post  # post 同样换回放: 两阶段第一步也不能漏

    tool_calls: list[dict] = []                                                                 # 调用序列独立记账: 一致率与序列长度判定都要读它
    results: list[dict] = []  # 归因与成本一致性检查的输入
    all_rows: list[dict] = []  # 跨调用累计的行: data_hash 与 row_keys 都由它算
    sqlid: Optional[str] = None  # 两阶段协议的状态: 第一步拿到, 后续调用复用
    t0 = time.monotonic()  # 单调钟而非 wall clock: NTP 调时会让耗时出负数或巨跳
    outcome = "success"  # 默认成功: 任一环节翻成 fail 的路径在下面统一改写
    answer_bits: list[str] = []  # 拼答案的人话片段: 供 U1/U4 的关键词取证

    for step in sequence:                                                                  # 按预写序列推进: R0 不含 LLM 决策, 顺序完全确定
        tool = step["tool"]
        # 拷一份 args: 客户端可能就地改参数, 直接传登记表的字典会让
        # 第二次运行拿到被上一次污染过的参数, PAC 就永远看不出真实漂移
        args = dict(step["args"])
        call_record = {"tool": tool, "args": args}  # PAC 比的就是这份 args, 须与实调同一份
        # 记调用在执行之前: 抛异常的调用同样是一条调用, 漏记会让 TSC
        # 的序列长度与实际尝试数不符
        tool_calls.append(call_record)                                                   # 记在执行之前: 抛异常的调用同样是一条调用, 漏记序列长度就错
        result_record: dict = {"ok": False, "error_code": None}  # 失败为默认: 成功要显式改写
        try:
            if tool == "cone_search":
                result = client.cone_search(**args)  # 打的是真实客户端, 回放只换网卡
                # sqlid 沿用上一次的值: 快照里 sqlid 是固定的, 而两次
                # 拿不到就说明链路已经出问题, 此时静默沿用旧值会掩盖它
                sqlid = getattr(result, "query_params", {}).get("sqlid") if hasattr(result, "query_params") else sqlid
                result_record["ok"] = bool(result.success)  # 成功与否取自客户端, 不看回包内容
                result_record["error_code"] = getattr(result, "error_code", None)  # 软失败也带码: D-3 才拦得住
                for source in getattr(result, "sources", None) or ():  # None 与空元组等价, or () 统一可迭代
                    all_rows.append(dict(getattr(source, "raw_data", {}) or {}))  # 转 dict 快照: 之后只拿纯数据算指纹
                answer_bits.append(f"{len(getattr(result, 'sources', None) or [])} rows")  # 人话片段供关键词取证
            elif tool == "count":
                total = client.count(sqlid or "s9001")  # 兜底 sqlid: 快照回包里就是这个值
                result_record["ok"] = total is not None  # 有回包即成功: 回放下失败表现为 None
                answer_bits.append(f"count={total}")
            elif tool == "fetch_page":
                result = client.fetch_page(sqlid or "s9001", page=args.get("page", 2),
                                           page_size=args.get("page_size", 5),  # 默认 5: 与快照页大小一致
                                           catalog=args.get("catalog", "ps1"))
                result_record["ok"] = bool(result.success)
                for source in getattr(result, "sources", None) or ():
                    all_rows.append(dict(getattr(source, "raw_data", {}) or {}))
                answer_bits.append(f"+{len(getattr(result, 'sources', None) or [])} rows")  # 加号: 续页可与首查区分
            elif tool == "crossmatch_batch":
                result = client.crossmatch_batch(**args)  # 批量交叉匹配: 与锥搜同走回放, 无额外往返
                result_record["ok"] = bool(result.success)
                for source in getattr(result, "sources", None) or ():
                    all_rows.append(dict(getattr(source, "raw_data", {}) or {}))
                answer_bits.append(f"{len(getattr(result, 'sources', None) or [])} matched")
            elif tool == "list_catalogs":
                # 本地: 星表展示名 (list_catalogs 零请求替身的答案载荷)
                from src.protocol import CATALOG_DISPLAY

                result_record["ok"] = True  # 恒记成功: 零请求本地元数据没有服务端失败
                answer_bits.append(f"{len(CATALOG_DISPLAY)} catalogs")  # 星表数进答案, 供 U4 取证
            elif tool == "describe_catalog":
                columns = client.describe_columns(args.get("catalog", "ps1"))  # 列定义同走零请求路径
                result_record["ok"] = True
                answer_bits.append(f"{len(columns)} columns")
            else:
                raise ValueError(f"R0 序列未知工具: {tool}")  # 序列表与客户端脱节是配置错, 不是被测缺陷
        except Exception as exc:  # R0 也要记录失败 (拒绝路径的确定性即被测对象)
            outcome = "fail"  # 兜住整类异常: 拒绝路径的确定性正是 R0 要测的东西
            result_record["ok"] = False
            result_record["error_code"] = type(exc).__name__  # 用异常类名当码: 离线也有稳定取值
            answer_bits.append(type(exc).__name__)                                             # 异常类名也进答案文本: 关键词取证要能看见失败形态
        results.append(result_record)  # 失败也进表: 归因第 4/5 条要读它

    elapsed = time.monotonic() - t0  # 墙钟不含节流: rate_limit 已是 0.0, 差值即纯代码耗时
    data_hash = _rows_hash(all_rows)  # L1 档输入: 逐位全等, 快照被动过就整条归零
    # D-3 修复: 任一工具结果失败 (ok=False) → outcome 必须记 fail, 结论卡
    # kind 记 refusal 并带上错误码 — 严禁把服务端软 404 记成"成功但 0 行"
    # (ERROR→EMPTY, E6 §3.1 REPRO-30 明令禁止; 与 E2-M5/E4-M5 同判据)。
    # 注意判定依据是 results 里的 ok 而不是 except 分支: 服务端软失败
    # 不会抛异常, 只看 except 会把 ERROR→EMPTY 漏过去
    failed = [r for r in results if not r.get("ok")]
    # 去重排序: 同一错误码在多次调用里重复出现不该让 caveat 列表变长,
    # 排序则保证两次运行的结论卡逐字可比 (FCC 靠这个)
    error_codes = sorted({str(r.get("error_code")) for r in failed if r.get("error_code")})  # 去重+排序: 两次运行的卡要逐字可比
    if failed:  # 判据是 results 里的 ok 而非 except 分支: 软失败不抛异常
        outcome = "fail"
    card = {                                                                               # 结论卡只留两项数值: kind 与行数, 足够暴露头号漂移
        "kind": "rowset" if outcome == "success" else "refusal",  # 只这两种: 成功↔拒绝对翻转就是头号漂移
        "key_numbers": [{"field": "row_count", "value": len(all_rows)}],  # 唯一数值项: 最能暴露漂移
        "key_entities": ["replay.local"],
        "caveats": [f"error_code:{code}" for code in error_codes],
    }
    return {
        "task_id": task_id,
        "tool_calls": tool_calls,
        "results": results,
        "cost": {"http_requests": transport.call_count,  # 取自唯一出口: 自己数会漏客户端内部往返
                 "elapsed_s": round(elapsed, 6),
                 "rows_returned": len(all_rows)},
        "card": card,
        "outcome": outcome,
        "data_hash": data_hash,
        "row_keys": _row_keys(all_rows),  # L2 档行主键集: 集合语义吸收分页行序不稳
        "answer_text": "; ".join(answer_bits),  # 可用性取证面: 关键词判据全靠这段文本
        "attempt": attempt,
    }


def run_lane(task_ids: Optional[list] = None, repeat: int = 3) -> dict:
    """跑 R0 路: 对每个预写序列任务重复 ``repeat`` 次, 返回逐任务 runs。

    Args:
        task_ids: 限定任务子集 (默认全部已定义序列)。
        repeat: 每任务重复次数 (文档默认 5; R0 冒烟可 3)。

    Returns:
        ``{"runs": {task_id: [run, ...]}, "coverage": {...}}`` — coverage
        显式披露"R0 覆盖任务数 / 32"与未覆盖原因 (LLM 决策类属 R1/R3)。
    """
    # 排序保证遍历序稳定: runs 字典的键序会进 JSON 产物, 不排序的话
    # 同一批 run 两次落盘的 JSON 字节不同, 复现比对会被无谓地判失败
    selected = task_ids or sorted(R0_SEQUENCES)  # 排序保遍历序稳定: 落盘 JSON 要逐字节可比
    runs: dict[str, list[dict]] = {}  # task_id → 该任务的 N 次运行: 一致率的分组单位
    for task_id in selected:                                                               # 按选定集合遍历: 实际覆盖数由 coverage 如实披露
        if task_id not in R0_SEQUENCES:                                                # 未覆盖的 id 跳过而非报错: 调用方常按大集合传 task_id
            # 跳过而非报错: 调用方常按大集合传 task_id, 因 R0 不覆盖而
            # 抛错会让整路跑不成; 少跑的任务由 coverage 如实披露
            continue
        fixture, sequence = R0_SEQUENCES[task_id]  # 快照名与序列成对取出, 都由登记表定
        runs[task_id] = [run_once(task_id, fixture, sequence, attempt=i + 1)  # attempt 从 1 起
                         for i in range(repeat)]                                       # 逐次独立运行: 复用同一实例会让 per-run 计数被上一次污染
    uncovered = 32 - len(runs)  # 分母是 32 全集, 不是已定义序列数: 否则永远是 100%
    return {"runs": runs,  # coverage 必带: 少跑的任务要显式说, 不靠调用方自己数
            "coverage": {"covered": len(runs), "total": 32, "uncovered": uncovered,
                         "note": "未覆盖 = 需 LLM 决策的 clarify/reject-utterance/safety 类, 属 R1/R3 路"}}
