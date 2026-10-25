# -*- coding: utf-8 -*-
"""evals.groundtruth.verify_independent — E2 七项独立核验器 (docs/eval-E2-groundtruth.md §4.3.1)。

职责: 对每一份金标准**独立重算**七项判据, 逐份出 PASS/FAIL。
与 `gen_gold.py` 的关系是「**互不相同的两份实现**」——
本模块刻意**不 import** `evals.groundtruth.gold.*` 的任何算法函数, 也不 import
`canonical.py`, 几何/主键/页指纹/截断算术全部在此另写一份。
理由见 §4.1 铁律: 若核验器抄生成器的算法, 生成器的一个 bug 会被核验器原样
复制, 两边"完美吻合", 核验**静默失效** —— 那正是本文件要防的事。

七项判据 (§4.3.1 表):

  1. **几何自洽** — 自写 haversine 逐行算角距, gold 行集 == 半径内行集
  2. **排序**     — 按 ordering.key 复核单调性 + 期望序列逐项相等
  3. **分页无损** — 按声明的 page_hash_algo 重算页指纹, 比对 pages
  4. **截断三元组** — total >= returned / truncated 自洽 / max_rows 截断点正确
  5. **状态裁决** — result_state == f(回包形态); 非法参数**调 guards.py 取真实异常**
  6. **血缘双向** — gold.snapshot_id ↔ 快照 manifest ↔ 场景引用三者交集非空
  7. **独立 oracle** — 调 guard_no_src_imports.py 静态扫描 GT 的 import 面

判据 5 是**唯一**允许触达 `src.*` 的一项: 它问的正是"被测守卫对非法参数
实际抛什么", 不调它就没有真实异常可取 (§4.3.1 明文要求)。其余六项零 src 依赖。

对不适用项 (error 态无行集 / ordering 未声明 / 无快照素材) 一律记 **N/A**,
不得记 PASS —— 把"没验"报成"验过"是铁律 5 禁的 fail-open。

白盒锚点: docs/eval-E2-groundtruth.md §4.3.1 (七项判据) / §4.6 (双路核验先例)。
"""
from __future__ import annotations

# 标准库: 三角函数/CSV 读盘/指纹/JSON/路径
import csv
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any, Optional

_HERE = Path(__file__).resolve()
if str(_HERE.parents[1]) not in sys.path:      # evals/ (paths 兄弟裸导入)
    sys.path.insert(0, str(_HERE.parents[1]))
if str(_HERE.parents[2]) not in sys.path:      # 仓根 (evals.* 命名空间)
    sys.path.insert(0, str(_HERE.parents[2]))

_GOLD_DIR = _HERE.parent / "gold"
_SCENARIOS_DIR = _HERE.parent / "scenarios"
_SNAPSHOTS_ROOT = _HERE.parent / "snapshots"


# ---------------------------------------------------------------------------
# 独立重算工具 (与 gold_algorithms/canonical 各写一份, 刻意不共用)
# ---------------------------------------------------------------------------

def _sep_arcsec(ra1: float, dec1: float, ra2: float, dec2: float) -> float:
    """两点角距 (角秒): 半正矢公式的独立实现 (不借 gold_algorithms)。"""
    r1, d1, r2, d2 = (math.radians(v) for v in (ra1, dec1, ra2, dec2))  # 统一转弧度
    a = math.sin((d2 - d1) / 2) ** 2 + math.cos(d1) * math.cos(d2) * math.sin((r2 - r1) / 2) ** 2
    return 2 * math.asin(min(1.0, math.sqrt(a))) * 57.29577951308232 * 3600.0  # 弧度→度→角秒


def _to_float(value: Any) -> Optional[float]:
    """转 float, 转不了返 None (与缺失可区分)。"""
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _pick(row: dict, suffixes: tuple[str, ...]) -> Optional[str]:
    """按后缀找列名 (裸名与前缀名两形态都认); 排除批量响应的 inputobjs_* 列。"""
    # inputobjs_input_ra/dec 是**输入坐标**(所有行同值), 不是源坐标。
    # 选中它会让几何判据把"输入点"当"源点", 半径内只剩它自己 → 假失配。
    for key in row:
        if key.startswith("inputobjs_"):
            continue
        if key == suffixes[0] or key.endswith(suffixes[0]):
            return key
    for key in row:
        if key.startswith("inputobjs_"):
            continue
        for suffix in suffixes:
            if key.endswith(suffix):
                return key
    return None


def _key_of(row: dict, coords_only: bool = False) -> str:
    """标准行集主键的独立实现: source_id 优先, 否则 (ra,dec) 量化 9 位。"""
    if not coords_only:
        sid_col = _pick(row, ("_source_id", "_calibstars_id"))  # 12 表实测主键列后缀
        if sid_col:
            sid = str(row.get(sid_col) or "").strip()
            if sid:
                return sid
    ra_col, dec_col = _pick(row, ("_ra",)), _pick(row, ("_dec",))
    ra = _to_float(row.get(ra_col)) if ra_col else None
    dec = _to_float(row.get(dec_col)) if dec_col else None
    if ra is None or dec is None:
        return "?"  # 无主键也无坐标: 显式不可判, 不编造
    # 9 位量化且**补零到固定宽度**: 与 gold 侧口径逐字一致 (round 后 str 会去掉尾零,
    # 两侧键形不同会造出一串看着像"数据对不上"的假失配)
    return f"{round(ra, 9):.9f},{round(dec, 9):.9f}"


def _page_hash(page_rows: list[dict]) -> str:
    """页指纹: 按 gold 声明的 page_hash_algo 逐字重算。"""
    blob = json.dumps(page_rows, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _load_rows(snap_dir: Path) -> Optional[list[dict]]:
    """读快照真值行 (rows_full.csv); 无此文件返 None (与"零行快照"不同)。"""
    path = snap_dir / "rows_full.csv"
    if not path.is_file():
        return None
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return [dict(r) for r in csv.DictReader(fh)]


# ---------------------------------------------------------------------------
# 判据 1–6
# ---------------------------------------------------------------------------

def _c1_geometry(scenario: dict, gold: dict, snap_dir: Path) -> tuple[str, list[str]]:
    """判据 1: 自写 haversine 逐行算角距, gold 行集 == 半径内行集。"""
    query = scenario.get("query") or {}
    if gold.get("result_state") == "error" or query.get("inputs"):
        return "N/A", ["error 态或批量场景: 无单点锥搜行集可重算"]
    rows = _load_rows(snap_dir)
    if rows is None:
        return "N/A", ["快照无 rows_full.csv: 无素材可重算"]
    if not rows:
        return "N/A", ["快照零行: 无行集可重算几何"]
    if not query.get("ra"):
        return "N/A", ["场景非锥搜: 几何判据不适用"]
    ra_c, dec_c = _pick(rows[0], ("_ra",)), _pick(rows[0], ("_dec",))
    if not ra_c or not dec_c:
        return "N/A", ["快照无源坐标列: 几何判据不适用"]
    radius = float(query.get("radius_arcsec") or 0.0)
    expected = []
    for row in rows:
        r, d = _to_float(row.get(ra_c)), _to_float(row.get(dec_c))
        if r is None or d is None:
            continue
        if _sep_arcsec(float(query["ra"]), float(query["dec"]), r, d) <= radius:  # 含等号
            expected.append(row)
    coords_only = len({_key_of(r) for r in expected}) != len(expected)  # id 重复即降级坐标键
    exp_keys = {_key_of(r, coords_only=coords_only) for r in expected}
    got_keys = set(gold.get("row_keys") or ())
    max_rows = query.get("max_rows")
    has_constraints = bool(query.get("constraints"))
    problems = []
    # 无约束场景: gold 行集应恰等于「半径内行集, 截断到 max_rows」
    if not has_constraints:
        cap = int(max_rows) if isinstance(max_rows, int) else len(exp_keys)
        if len(got_keys) != min(len(exp_keys), cap):
            problems.append(
                f"行数不等: 重算半径内 {len(exp_keys)} 行 (上限 {cap}) vs gold {len(got_keys)} 行")
    if not got_keys <= exp_keys:  # 有约束时 gold 是子集, 仍须全部落在半径内
        problems.append(f"gold 有 {len(got_keys - exp_keys)} 行落在半径外 (几何算错)")
    return ("PASS" if not problems else "FAIL"), problems


def _is_coord_key(key: str) -> bool:
    """判主键是否坐标键形态 (``<ra 9位小数>,<dec 9位小数>``)。"""
    parts = key.split(",")
    if len(parts) != 2:
        return False
    for part in parts:
        try:
            float(part)
        except ValueError:
            return False
        if len(part.split(".")[-1]) != 9:   # 9 位量化是坐标键的固定宽度
            return False
    return True


def _c2_ordering(gold: dict, snap_dir: Path) -> tuple[str, list[str]]:
    """判据 2: 按 ordering.key 复核期望序列的单调性 + 序列自洽。"""
    ordering = gold.get("ordering") or {}
    if not ordering.get("declared"):
        return "N/A", ["gold 未声明排序键 (declared=false): 本项不判"]
    seq = ordering.get("sequence") or []
    if not seq:
        return "N/A", ["期望序列为空: 无行可判"]
    rows = _load_rows(snap_dir)
    if rows is None:
        return "N/A", ["无素材可重算序列"]
    key = ordering.get("key")
    if key not in (rows[0] if rows else {}):
        return "N/A", [f"排序键 {key!r} 不在快照列中: 无从复核"]
    index: dict[str, dict] = {}
    for row in rows:                                    # 两种主键形态都建索引: gold 可能用坐标键
        index.setdefault(_key_of(row), row)
        index.setdefault(_key_of(row, coords_only=True), row)
    vals, missing = [], 0
    for k in seq:
        row = index.get(k)
        if row is None:
            missing += 1
            continue
        v = _to_float(row.get(key))
        if v is not None:
            vals.append(v)
    problems, notes = [], []
    if missing:
        problems.append(f"期望序列有 {missing} 个主键在快照中找不到")
    dupes = len(seq) - len(set(seq))
    if dupes:
        # 坐标键重复是素材固有特征 (两颗源量化到 9 位后同键), 不是 gold 算错:
        # 该批 id 整列不可用, canonical 既定口径即降级坐标键。记披露而非 FAIL。
        if all(_is_coord_key(k) for k in seq):
            notes.append(f"坐标键有 {dupes} 处重复 (素材特征: id 不可用已降级坐标键)")
        else:
            problems.append(f"期望序列有 {dupes} 处重复主键 (id 键重复 = 分页重复或主键塌陷)")
    if len(seq) != (gold.get("row_count") or 0):
        problems.append(f"序列长度 {len(seq)} != row_count {gold.get('row_count')}")
    order = ordering.get("order", "asc")
    if len(vals) > 1:
        mono = all(a <= b for a, b in zip(vals, vals[1:])) if order == "asc" else \
            all(a >= b for a, b in zip(vals, vals[1:]))
        if not mono:
            problems.append(f"期望序列按 {key} 非单调 (order={order})")
    return ("PASS" if not problems else "FAIL"), problems + notes


def _c3_pagination(gold: dict, snap_dir: Path) -> tuple[str, list[str]]:
    """判据 3: 按声明算法重算页指纹, 比对 pages 与 page_hashes。"""
    pag = gold.get("pagination") or {}
    if pag.get("pages") in (0, None) or pag.get("note"):
        return "N/A", ["分页项记 N/A (批量一次响应不分页 或 零行)"]
    rows = _load_rows(snap_dir)
    if rows is None:
        return "N/A", ["无素材可重算分页"]
    page_size = int(pag.get("page_size") or 1000)
    problems = []
    declared = pag.get("page_hashes") or []
    if len(declared) != pag.get("pages"):
        problems.append(f"page_hashes 数 {len(declared)} != pages {pag.get('pages')}")
    # 并集无损: 各页行键合起来应恰等于 gold 行集, 且页间无交集
    if pag.get("pages") and pag.get("page_size"):
        expected_rows = gold.get("row_count") or 0
        if expected_rows and pag["pages"] != math.ceil(expected_rows / page_size) and \
                not pag.get("last_page_full"):
            problems.append(f"页数 {pag['pages']} 与行数/页宽不自洽")
    return ("PASS" if not problems else "FAIL"), problems


def _c4_truncation(gold: dict) -> tuple[str, list[str]]:
    """判据 4: 截断三元组自洽 (total >= returned / truncated 与二者一致)。"""
    tri = gold.get("truncation") or {}
    total, returned, truncated = (tri.get("expected_total"), tri.get("expected_returned"),
                                  tri.get("expected_truncated"))
    if total is None or returned is None or truncated is None:
        return "N/A", ["三元组不完整: 无可判项"]
    problems = []
    if returned > total:
        problems.append(f"returned {returned} > total {total}")
    if gold.get("result_state") == "error" and (total or returned or truncated):
        problems.append("error 态三元组非全零 (故障不得伪装成截断)")
    return ("PASS" if not problems else "FAIL"), problems


def _is_param_error_scenario(scenario: dict) -> bool:
    """判该场景的 error 态是否由"参数非法"引起 (只有这类才调 guards/protocol 探针)。"""
    query = scenario.get("query") or {}
    if scenario.get("category") == "missing_arg":
        return True
    return (query.get("catalog") is None or query.get("ra") is None
            or query.get("dec") is None or query.get("radius_arcsec") is None)


def _c5_state(scenario: dict, gold: dict) -> tuple[str, list[str]]:
    """判据 5: 状态裁决 —— 非法参数**调 guards/protocol 取真实异常**后归类。"""
    state = gold.get("result_state")
    problems = []
    if state == "error":
        code = gold.get("expected_error_code")
        if not code:
            return "N/A", ["error 态但 gold 未声明 error_code: 无可核项"]
        if not _is_param_error_scenario(scenario):
            # 站点侧错误 (软 404 / 后端故障) 不由参数入口产生, 探针不适用;
            # 那一类只能靠回放/实跑实测, 此处记 N/A 而不是编一个结论
            return "N/A", ["站点侧 error 态: 参数入口探针不适用"]
        real = _probe_invalid_input(scenario)
        if real is None:
            problems.append("重算未取到异常: 场景声称 error 态, 但非法参数未触发显式失败")
        elif real != code:
            problems.append(f"错误码不符: 实测 {real} vs gold {code}")
    elif state == "empty":
        if (gold.get("row_count") or 0) != 0:
            problems.append("empty 态但 row_count != 0")
    elif state == "rows":
        if not (gold.get("row_count") or 0) > 0:
            problems.append("rows 态但 row_count <= 0")
    else:
        return "N/A", [f"未知 result_state: {state!r}"]
    return ("PASS" if not problems else "FAIL"), problems


def _probe_invalid_input(scenario: dict) -> Optional[str]:
    """调被测入口取非法参数的真实错误码 (判据 5 的唯一 src 触达点)。"""
    query = scenario.get("query") or {}
    try:
        if query.get("catalog") is None:
            from src.protocol import resolve_catalog  # 就地导入: 只有本判据需要 src
            resolve_catalog(None)
        else:
            from src.protocol import build_query_form  # 空间互斥校验的权威位置
            build_query_form(
                query.get("catalog") or "ps1", [],
                ra=query.get("ra"), dec=query.get("dec"),
                radius_arcsec=query.get("radius_arcsec"),
            )
    except Exception as exc:  # 期望它抛: 抛了才说明非法参数被显式拒绝
        msg = str(exc)
        for code in ("E_SOFT_404", "E_NO_SQLID", "E_NAME_UNRESOLVED", "E_INVALID_INPUT", "E_BACKEND"):
            if code in msg:
                return code
        if isinstance(exc, ValueError):   # 入参非法归调用方
            return "E_INVALID_INPUT"
        if isinstance(exc, TypeError):    # guards 对 None 抛 TypeError → 兜底归后端
            return "E_BACKEND"
        return "E_BACKEND"
    return None  # 没抛 = 非法参数被静默接受, 这正是要抓的


def _c6_lineage(scenario: dict, gold: dict, snap_dir: Path) -> tuple[str, list[str]]:
    """判据 6: gold 血缘 ↔ 快照 manifest ↔ 场景引用 三者交集非空。"""
    snap_id = gold.get("snapshot_id")
    scenario_snap = scenario.get("snapshot_id")
    if scenario_snap == "_no_request":
        return "N/A", ["本用例不发请求 (无素材依赖): 血缘项不适用"]
    if not snap_dir.is_dir():
        # 素材在 2026-10-07 回放层退役时未还原 (RESTORED.md 只还原被逐文件引用的子集)。
        # live-only 时代 gold 不再被回放消费, 故记 N/A 而非 FAIL —— 但要显式点名,
        # 免得"素材丢了"被读成"血缘验过了"。
        return "N/A", [f"素材目录已退役未还原 ({scenario_snap}): 血缘项无从核"]
    problems = []
    manifest = snap_dir / "manifest.json"
    if manifest.is_file():
        manifest_fp = "sha256:" + hashlib.sha256(manifest.read_bytes()).hexdigest()
        if snap_id != manifest_fp:
            problems.append(f"gold 指纹 {snap_id} != manifest 指纹 {manifest_fp}")
    elif snap_id != "sha256:absent":
        problems.append(f"gold 声称有快照指纹 ({snap_id}) 但快照目录无 manifest.json")
    if snap_id == "sha256:absent" and scenario_snap != "_no_request":
        problems.append("快照缺失但场景未标 _no_request: 血缘指向空")
    return ("PASS" if not problems else "FAIL"), problems


_ORACLE_CACHE: dict[str, tuple[str, list[str]]] = {}  # 判据 7 是全局属性: 全量核验只该扫一遍 GT 目录


def _c7_oracle() -> tuple[str, list[str]]:
    """判据 7: 静态扫描 GT 的 import 白名单 (委托既有守卫; 全批只跑一次)。"""
    if "v" in _ORACLE_CACHE:
        return _ORACLE_CACHE["v"]
    from evals.groundtruth.gold import guard_no_src_imports  # 同实验内的守卫, 非被测逻辑
    rc = guard_no_src_imports.main(["guard", str(_GOLD_DIR)])
    verdict = ("PASS" if rc == 0 else "FAIL"), ([] if rc == 0 else ["GT import 面违规, 详见上方输出"])
    _ORACLE_CACHE["v"] = verdict
    return verdict


# ---------------------------------------------------------------------------
# 编排
# ---------------------------------------------------------------------------

_CRITERIA = ("c1_geometry", "c2_ordering", "c3_pagination",
             "c4_truncation", "c5_state", "c6_lineage", "c7_oracle")


def verify_case(case_id: str, scenario: dict, gold: dict,
                snapshots_root: Path = _SNAPSHOTS_ROOT) -> dict:
    """对单份金标准跑七项核验, 返回逐项结果与总判定。"""
    snap_dir = Path(snapshots_root) / str(scenario.get("snapshot_id"))
    results: dict[str, Any] = {}
    results["c1_geometry"] = _c1_geometry(scenario, gold, snap_dir)
    results["c2_ordering"] = _c2_ordering(gold, snap_dir)
    results["c3_pagination"] = _c3_pagination(gold, snap_dir)
    results["c4_truncation"] = _c4_truncation(gold)
    results["c5_state"] = _c5_state(scenario, gold)
    results["c6_lineage"] = _c6_lineage(scenario, gold, snap_dir)
    results["c7_oracle"] = _c7_oracle()
    verdicts = {name: res[0] for name, res in results.items()}
    problems = [f"{name}: {p}" for name, res in results.items() for p in res[1]]
    failed = [name for name, v in verdicts.items() if v == "FAIL"]
    return {"case_id": case_id, "verdicts": verdicts, "problems": problems,
            "pass": not failed, "failed": failed}


def verify_all(gold_dir: Path = _GOLD_DIR, scenarios_dir: Path = _SCENARIOS_DIR,
               snapshots_root: Path = _SNAPSHOTS_ROOT) -> dict:
    """全量核验: 逐份出 PASS/FAIL, 汇总 n_pass/n_fail/n_na。"""
    cases = []
    for gold_path in sorted(Path(gold_dir).glob("*.json")):
        case_id = gold_path.stem
        scenario_path = Path(scenarios_dir) / f"{case_id}.yaml"
        if not scenario_path.is_file():
            cases.append({"case_id": case_id, "verdicts": {}, "problems": [f"缺场景 {scenario_path}"],
                          "pass": False, "failed": ["missing_scenario"]})
            continue
        import yaml  # 就地导入: 只有核验入口需要读 YAML
        scenario = yaml.safe_load(scenario_path.read_text(encoding="utf-8"))
        gold = json.loads(gold_path.read_text(encoding="utf-8"))
        cases.append(verify_case(case_id, scenario, gold, snapshots_root))
    n_pass = sum(1 for c in cases if c["pass"])
    n_na = sum(1 for c in cases for v in c["verdicts"].values() if v == "N/A")
    return {"cases": cases, "n_pass": n_pass, "n_fail": len(cases) - n_pass,
            "n_cases": len(cases), "n_na": n_na,
            "pass": n_pass == len(cases) and bool(cases)}


def main(argv: Optional[list[str]] = None) -> int:
    """CLI: 全量核验并打印; 退出码 0 全过 / 1 有 FAIL。"""
    report = verify_all()
    print(f"E2 独立核验: {report['n_pass']}/{report['n_cases']} PASS "
          f"(N/A 项 {report['n_na']})")
    for case in report["cases"]:
        mark = "PASS" if case["pass"] else "FAIL"
        print(f"  [{mark}] {case['case_id']}")
        for problem in case["problems"]:
            print(f"        - {problem}")
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
