# -*- coding: utf-8 -*-
"""evals.groundtruth.broken — E2 反证夹具 (每个判定器配一个已知坏答案)。

纪律 (E2 §8, 沿用本仓 evals/ 约定): 每个判定器都要配一个"已知坏答案",
它必须报 FAIL; 要是报 PASS, 说明判定器是摆设 → 该判定器 FAIL → E2 总评
FAIL。``run_broken_selftest`` 返回逐夹具结果, metascore = 被判 FAIL 的比例。
"""
from __future__ import annotations

# 标准库: 脚本直跑时把 skill 根挂上 sys.path (供 evals.* 命名空间包导入)
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))  # parents[3] 才是仓库根: 脚本直跑时 evals.* 命名空间包才导得进

# 本地: 对账入口 (坏样本经同一 compare_case — 判定器自证用被测判定器本身)
from evals.groundtruth.metrics import compare_case

# 迷你金标准 (合成; 覆盖行集/字段/单位/结构/状态/版本六个判定面)
_GOLD = {  # 金标准行: 这批行是"判据应该判成什么"的锚
    "snapshot_id": "syn_boundary",
    "data_version": "ps1@fixture",
    "catalog": "ps1",
    "row_keys": ["B1", "B2", "B3", "B4"],
    "row_count": 4,  # 行数与 row_keys 长度互为对照, 两处写岔了 M1 的分母就是假的
    "key_field": "source_id",
    "field_values": {
        "B1": {"ra": {"v": 359.99, "kind": "numeric", "atol": 1e-9, "rtol": 0.0},
               "ps1_rpsf": {"v": 18.123456, "kind": "numeric", "atol": 0.01, "rtol": 0.0}},
        "B2": {"ra": {"v": 0.01, "kind": "numeric", "atol": 1e-9, "rtol": 0.0}},
    },
    "null_semantics": {"B2": {"ps1_rpsf": "null"}},
    "unit_map": {"ra": "deg", "ps1_rpsf": "mag"},
    "precision_map": {"ra": 9, "ps1_rpsf": 6},
    # 默认**不声明排序**: live 口径的 M4 只在 gold 声明了排序键时才判单调性, 不声明
    # 即本项不判 (不能判"没要求")。合成行集本身对 ra 不单调 (359.99 / 0.01 / 180 /
    # 181), 默认声明会让每条夹具都顺手带一个 M4 排序红, 归因就指不准了 —— 要测排序
    # 的那条自带 gold_override 声明。见 m4_order_break_not_monotonic。
    "ordering": None,
    "pagination": {"page_size": 2, "pages": 2},
    "truncation": {"expected_total": 4, "expected_truncated": False,
                   "expected_returned": 4},
    "result_state": "rows",
    "review": {"signed": True},
}

_ROWS = [  # 故意与金标准错开的一组行: 判据必须能看出差异
    {"source_id": "B1", "ra": 359.99, "ps1_rpsf": 18.123456},
    {"source_id": "B2", "ra": 0.01, "ps1_rpsf": None},
    {"source_id": "B3", "ra": 180.0, "ps1_rpsf": 19.5},
    {"source_id": "B4", "ra": 181.0, "ps1_rpsf": 20.0},
]

_PROVENANCE = {"snapshot_id": "syn_boundary", "catalog": "ps1",  # 溯源面: provenance 缺字段也是一类可判失真
               "endpoint": "/data/best/ps1/q"}
_ENVELOPE = {"total_count": 4, "returned_count": 4, "truncated": False,  # 信封面: total/returned/truncated 三者对不上即 M4 失真
             "success": True}


def _actual(rows=None, envelope=None, provenance=None, **extra):  # 逐字段可覆盖: 每个反证只写与金标准的差异
    """拼一个对账输入 (默认用黄金行集 — 坏样本只改指定维度)。

    **缺省 ``mode="live"``** (2026-10-07, 随回放层退役): 此前缺省是 ``replay``,
    理由是"M1 有两套实现, 忘了传 mode 就走严的那套"。但回放臂整链删除后, M4 的
    replay 分支已改成**显式 ``NotImplementedError``** —— 缺省留在 replay 上等于让
    整条 metascore 自证链在第一夹具就崩掉, 整批 E2 恒红而红的原因是接线遗留, 与
    判定器无关。判定器自证必须跑在被测代码**现行**的口径上。
    """
    payload = {                                                                         # 只覆盖与金标准不同的维度: 每个反证只写一处差异, 归因才指得准
        "mode": "live",                                                                  # 唯一的臂: 实跑口径 (replay 已于 2026-10-07 整链删除)
        "rows": _ROWS if rows is None else rows,
        "envelope": dict(_ENVELOPE if envelope is None else envelope),
        "provenance": dict(_PROVENANCE if provenance is None else provenance),
        "declared_units": {"ra": "deg", "ps1_rpsf": "mag"},
        "data_hashes": ["sha256:x", "sha256:x", "sha256:x"],  # 三条相同: 确定性分项默认通过, 别让别的夹具顺带把它测了
        "declared_http_requests": 2,
        "observed_http_requests": 2,
    }
    payload.update(extra)  # extra 最后合入: 可覆盖上面任一维度, 用于临时构造额外坏样本
    return payload


def _live_actual(**extra):  # 显式声明实跑口径的对账输入
    """造一个 ``mode="live"`` 的对账输入 —— 与 :func:`_actual` 等价, 保留只为可读性。

    2026-10-07 起 :func:`_actual` 本身就缺省 live, 所以这个壳不再改变任何字段。
    它留着是因为注释里那些"必须显式声明 mode 否则 M1 会走回放分支"的理由值得留档
    —— 那条推理本身是对的 (夹具必须打在被现行判据上), 只是它防的那个分支已经没了。
    """
    return _actual(mode="live", **extra)


_FIXTURES = {  # 每条反证注明"该判成什么", 报告才有可核对的期望
    # ── M1: 内部不变量 (无跨时间期望值), 判据 violations 非空 ──
    # 2026-10-07 回放层退役前, M1 有两套实现 (行集 P/R 与内部不变量), 两套各配三条
    # 反证。原三条 ``m1_replay_*`` 判的是行集 P/R —— **该判据已随快照一并删除**
    # (实跑下拿会过期的冻结行集比对活数据必然大面积失配, 见
    # docs/REPLAY-RETIREMENT-CRITERIA.md §3.2「行集逐行 P/R」行)。它们不是"漏抓",
    # 是**没有可破的东西**: 实跑口径下"少一行 / 多一行"不构成不变量破例。诚实做法
    # 是删掉并在退役文档登记, 而不是改判定器去迁就一条已废的判据。
    #
    # 注意 key_collision 那条**保住了**, 但换了个打法: 它原先靠"同一行两次"让
    # 行集 P/R 的键塌成同一个 (precision 掉下来); 实跑口径下同一条构造恰好命中
    # ``duplicate_keys`` 不变量 (行数 5 > 键数 4), 判据含义从"与 GT 比"变成
    # "自身内部不唯一" —— 破的是同一类缺陷 (同一行被算了两次), 依据换了。
    # 超预算这条必须**换 gold**: M1 从 gold 侧读 max_rows, 沿用 _GOLD 构造不出"超预算"。
    "m1_live_key_collision": (lambda: _actual(rows=_ROWS + [dict(_ROWS[0])]), "m1_rows", None),  # 同一行两次 -> 主键塌陷
    "m1_live_over_budget": (lambda: _actual(rows=_ROWS, mode="live"), "m1_rows",
                            {**_GOLD, "max_rows": 2}),  # 4 行 > 预算 2 行
    "m1_live_returned_gt_total": (lambda: _actual(mode="live", envelope={"total_count": 2, "returned_count": 9,
                                                                         "truncated": False, "success": True}),
                                  "m1_rows", None),  # 返回数比总量还多
    "m1_live_truncation_undisclosed": (lambda: _actual(mode="live", envelope={"total_count": 99, "returned_count": 4,
                                                                               "truncated": False, "success": True}),
                                       "m1_rows", None),  # 少给了却不说
# M2a 字段值改 1 位小数 (ra atol 1e-9 容不下)
    "m2_field_digit": (lambda: _actual(rows=[
        {**r, "ra": r["ra"] + 1e-6} if r["source_id"] == "B1" else r for r in _ROWS]), "m2_fields", None),
    # M2b 哨兵换 0 (null_semantics 类别错)
    "m2_sentinel_as_zero": (lambda: _actual(rows=[
        {**r, "ps1_rpsf": 0.0} if r["source_id"] == "B2" else r for r in _ROWS]), "m2_fields", None),
    # M3a 坐标 ×3600 (单位错 → 量纲探针越界)
    "m3_unit_times_3600": (lambda: _actual(rows=[
        {**r, "ra": r["ra"] * 3600.0} if r["source_id"] == "B1" else r for r in _ROWS]), "m3_units", None),
    # M3b 星等截 2 位 (值在 atol 0.01 内 — 只有精度 dipped, 隔离 M3)
    "m3_precision_cut": (lambda: _actual(rows=[
        {**r, "ps1_rpsf": 18.12} if r["source_id"] == "B1" else r for r in _ROWS]), "m3_units", None),
    # M4a 排序非单调。
    # 2026-10-07 改写: 原 ``m4_order_swap`` 交换两行, 断的是"序列与 gold 的
    # sequence 逐位一致"—— 那是回放口径的判据, 实跑下不判 (要冻结行集)。实跑
    # 只判**单调性**, 故改成造一条真正非单调的列值。gold 必须**显式声明排序键**:
    # 不声明即本项不判 (见 _GOLD["ordering"] 的注释), 那这条夹具就永远抓不到。
    "m4_order_break_not_monotonic": (lambda: _actual(
        rows=[{"source_id": "B1", "ra": 10.0, "ps1_rpsf": 18.0},
              {"source_id": "B2", "ra": 30.0, "ps1_rpsf": 19.0},   # 30 后掉回 20: 升序声明被破
              {"source_id": "B3", "ra": 20.0, "ps1_rpsf": 20.0},
              {"source_id": "B4", "ra": 40.0, "ps1_rpsf": 21.0}],
        pages=None), "m4_structure",
        {**_GOLD, "ordering": {"key": "ra", "order": "asc", "sequence": None}}),
    # M4b 截断三元组不自洽 (returned > total)。
    # 2026-10-07 改写: 原 ``m4_truncation_flip`` 把 truncated 取反, 断的是"三元组
    # 与 gold 完全一致"—— 同样是回放口径判据。实跑口径下 truncated=True 且
    # returned==total 并不违反任何不变量 (站点多给不出错), 所以那条构造在 live 下
    # 抓不到任何东西。换成本口径真能破的: 报的返回数比总量还多。
    "m4_truncation_self_inconsistent": (lambda: _actual(
        envelope={"total_count": 2, "returned_count": 9, "truncated": True,
                  "success": True}), "m4_structure", None),
    # M5a 软错误体被报成"成功但 0 行" (ERROR→EMPTY 阻断; gold 换成 error
    # 态才隔离 — 坏样本的关键是 SUT 把故障**降级**成空结果)
    "m5_error_as_empty": (lambda: _actual(
        rows=[], envelope={"total_count": 0, "returned_count": 0,
                           "truncated": False, "success": True,
                           "error_code": None}), "m5_states",
        {**_GOLD, "result_state": "error", "row_keys": [], "row_count": 0,
         "truncation": {"expected_total": 0, "expected_truncated": False,
                        "expected_returned": 0}}),
    # M6a provenance 写错 snapshot_id (跨版本污染阻断)
    "m6_wrong_snapshot": (lambda: _actual(
        provenance={"snapshot_id": "syn_empty", "catalog": "ps1",
                    "endpoint": "/data/best/ps1/q"}), "m6_version", None),
    # M6b live 层不可把"版本不可对账"装作"已验证": 站点无版本标识面, 那一项移出
    # 声明集 (见 m6_version.not_reconcilable), 但 catalog/endpoint 仍要对得上。
    # 端点写错必须被抓 —— 若实现漏了 live 分支, snapshot_id 声明会留在分母里,
    # 而身份键两侧都空 (actual 无 provenance) 恰好与"并集不交"同形, 容易把这条
    # 误判成通过。所以 gold 侧必须**显式声明 endpoint**, 才有得比。
    "m6_live_endpoint_wrong": (lambda: _actual(
        mode="live",
        provenance={"snapshot_id": None, "data_version": None, "catalog": "ps1",
                    "endpoint": "/data/best/gaia/q"}), "m6_version",
        {**_GOLD, "endpoint": "/data/best/ps1/q", "data_version": None}),
    # M7a 计数不诚实 (BC-05 的承重断言): 声明侧比实测侧少 2 = 存在契约解释不了的
    # 请求。旧实现把 declared 与 observed 都赋成 call_count, 差值恒 0, 于是这条
    # 夹具恒"抓不到" —— 把两侧改成同源会立刻让它在这里现形。
    "m7_hidden_request": (lambda: _actual(
        declared_http_requests=1, observed_http_requests=3,
        unaccounted_calls=["GET https://example.invalid/secret"]), "m7_determinism", None),
    # M7b 确定性被破坏: 三次跑出的行集指纹不全等
    "m7_nondeterministic": (lambda: _actual(
        data_hashes=["sha256:x", "sha256:y", "sha256:x"]), "m7_determinism", None),
}


def run_broken_selftest() -> list:  # 跑一遍判据, 期望全部被抓; 漏抓即判定器退化
    """逐夹具对账, 返回 [{fixture_id, must_fail, pass, caught, target_metric}]。

    抓中判定 = **目标指标** pass=False 或其 blockers 非空 (指标级自证 —
    单个指标的缺陷不该被加权总分容忍掉, 反之亦然)。
    """                                                                        # 只改 key_numbers 一项: 结论卡其余子项保持不变, 才能定位到数值子项
    results = []                                                                           # 结果逐夹具攒: metascore 的分子分母都从这一份出
    for fixture_id, (build, target, gold_override) in _FIXTURES.items():                  # 逐夹具跑: 注册表新增一条就自动获得同等自证覆盖, 不会漏网
        gold = gold_override or _GOLD                                                # 可覆盖金标准: 有些反证要换 gold 才能构造, 不覆盖就构造不出来
        compared = compare_case(gold, build())                                               # 走正式对账入口: 自己拼结果会绕过「七指标全跑」这道关
        metric = compared["metrics"].get(target, {})
        caught = (not metric.get("pass", True)) or bool(metric.get("blockers"))  # 缺 pass 键按没失败算: 指标没实现不该被当成抓到了坏样本
        results.append({"fixture_id": fixture_id, "must_fail": True,
                        "pass": compared["pass"], "caught": caught,
                        "target_metric": target,
                        "blockers": compared["blockers"]})
    return results


def selftest_report() -> str:  # 自证报告走文本: 人能直接读, 不必打开 JSON
    """人读自证报告 (哪个夹具被抓/漏抓 — 目标指标级判定)。"""
    lines = ["E2 反证夹具自证:", ""]
    for r in run_broken_selftest():                                                              # 逐条渲染: 报告要能一眼看出哪条被抓、哪条漏抓
        mark = "CAUGHT" if r["caught"] else "MISSED"
        lines.append(f"- [{mark}] {r['fixture_id']} → {r['target_metric']} "
                     f"(case blockers: {r['blockers']})")
    return "\n".join(lines)


if __name__ == "__main__":
    print(selftest_report())                                                                    # 直跑即出自证报告: 不落盘, 便于人工在终端核对
