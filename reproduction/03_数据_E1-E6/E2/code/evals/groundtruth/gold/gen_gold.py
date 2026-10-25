# -*- coding: utf-8 -*-
"""evals.groundtruth.gold.gen_gold — E2 独立金标准生成器 (oracle 编排层)。

铁律 (docs/eval-E2-groundtruth.md §4.1, 最重要的一条):
  本目录 (gold/) 全部代码**严禁 import 任何被测判定逻辑** (``src.*`` 一律
  禁止); 锥搜角距/筛选谓词/排序/分页切片的手写实现在 gold_algorithms.py,
  字典映射在 gold_dictionaries.py, 本文件只做编排 (快照装载 → 分支 →
  gold 组装)。允许的 import: math/json/csv/pathlib/hashlib/
  decimal/yaml/argparse/sys/typing + evals._data (数据字典) +
  evals.groundtruth.gold.* (GT 自身分层)。
  自检: ``python evals/groundtruth/gold/guard_no_src_imports.py`` (扫描本
  目录全部 .py; 非零问题退出码非 0 — CI 断言, E2 §10 阻断项 6 的守门)。

为什么必须独立: GT 若抄被测代码的算法, 被测代码的一个 bug 会被 GT 原样复制,
两边"完美吻合", 实验静默失效 — 这是一致性实验最经典的翻车点 (E2 §4.1)。

产物 (E2 §4.2 结构):
  gold/<case_id>.json        — 金标准 (GT 独立生成, 直接就是对账基准)

人工签字一族 (签字单联 / 审核清单 / 回填工具链) 已于 2026-10-04 裁定取消并
整体删除, 本生成器不再产出任何复核面或签名段。

调用契约: 脚本方式调用 (``python evals/groundtruth/gold/gen_gold.py``) 或经
包路径 import (``evals.groundtruth.gold.gen_gold``, 命名空间包 — 本文件
bootstrap 仓库根到 sys.path, 两种入口都可用; 承 evals/ 兄弟导入纪律)。

白盒锚点: docs/eval-E2-groundtruth.md §4 (金标准生成) / §5 (场景) /
§6 (指标); haversine 口径核对见 gold_algorithms.angular_separation_arcsec。
"""
from __future__ import annotations

# 标准库: 参数解析 / CSV 读盘 / 指纹 / JSON 序列化 / 路径引导 / 类型标注 /
# YAML 读取场景与字典
import argparse
import csv
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Optional

import yaml

# 路径引导: 以脚本位置反推仓库根 (gold -> groundtruth -> evals -> 仓库根),
# 使 evals.* 命名空间包可导入 (仓内 evals/ 无 __init__.py)
_REPO_ROOT = Path(__file__).resolve().parents[3]                                 # 上溯三级才是仓根: 本件在 gold/ 下, 少一级会挂到 evals/ 上去
if str(_REPO_ROOT) not in sys.path:                                                        # 先判是否已在路径里: 重复插入会让同一模块被加载成两份对象
    sys.path.insert(0, str(_REPO_ROOT))                                                      # 插到最前: 仓内命名空间包必须优先于任何已安装的同名包

# 本地: GT 自身分层 (算法层/字典层 — 手写实现与字典映射, 零被测代码) +
# 容差表加载件 (纯数据字典; 哨兵字典由算法层内部加载, E2 §4.4 唯一共享件)
from evals._data import load_tolerances  # noqa: E402
from evals.groundtruth.gold.gold_algorithms import (  # noqa: E402
    angular_separation_arcsec,  # 算法面十件是 GT 的全部依赖: 编排层不自己实现判定, 免得两份实现漂移
    id_keys_unique,  # id 唯一性判据 (结果集层): 真实回包的 source_id 既可能整列为空、也可能重复
    match_constraint,  # 约束谓词单点: 假服务器与 oracle 共用同一套判定, 才能互为独立实现
    page_hash,  # 页指纹算法: M4 复算用的就是它, 换实现等于换判据
    paginate,  # 分页切片: 末页自然变短, 切片层不凑整页, 自洽性归 M4 判
    resolve_column,  # 列名解析: 裸名/前缀名/后缀三形态, 是逻辑列到真列的唯一出口
    row_key,  # 主键构造: 两侧主键不同尺会造出成对假失配
    sort_key,  # 混合排序键: 数值优先、空值殿后, 顺序即 M4 判单调的输入
    synthesize_rows,  # 合成行: 快照缺失时的确定性兜底, 全程无随机
    to_float,  # 安全转 float: 转不了返 None 而非抛, 一格脏值不该打断整批
)
from evals.groundtruth.gold.gold_dictionaries import (  # noqa: E402
    row_cells,  # 逐格双口径: 值与语义态必须同一次遍历产出, 分叉会自相矛盾
    unit_precision_maps,  # 单位与精度两表: M3a/M3c 各取一份, 合成一张会互相覆盖
)

# 快照目录默认根 (evals/groundtruth/snapshots/<snapshot_id>/)
_DEFAULT_SNAPSHOTS_ROOT = _REPO_ROOT / "evals" / "groundtruth" / "snapshots"  # 绝对路径反推: 脚本可能从仓根/gold/pytest 三处调起

_DEFAULT_PAGE_SIZE = 1000  # 站点单页上限: 取大了测不出末页不满, 取小了 M4 的三元组判据永不触发

_FIELD_VALUES_SAMPLE_CAP = 200  # 体积与覆盖率折中: 全量逐格会让 gold 膨胀到读不完

_PAGE_HASH_ALGO = "sha256(json.dumps(rows, sort_keys=True, ensure_ascii=False, separators=(',', ':')))"  # 格式契约: M4 侧按此声明复算页指纹


# ---------------------------------------------------------------------------
# 1. 快照/场景装载 (rows_full.csv 是 GT 唯一数据源; 被测面永远不读它)
# ---------------------------------------------------------------------------

def _load_snapshot_rows(snap_dir: Path) -> Optional[list[dict]]:
    """读快照全量真值 rows_full.csv (utf-8-sig 兼容 BOM; 无表头素材由 freeze 保真)。"""
    rows_path = snap_dir / "rows_full.csv"   # GT 唯一数据源; 被测面永远不读它
    if not rows_path.is_file():                                             # 缺文件返 None 而非空列表: None 才是「走 synthesize 回退」的信号
        return None                          # None = 走 synthesize 回退分支, 不是"零行快照"
    with rows_path.open("r", encoding="utf-8-sig", newline="") as handle:  # utf-8-sig 吃 BOM; newline 交给 csv
        return [dict(row) for row in csv.DictReader(handle)]  # 全量入内存: gold 要按主键随机访问


def _load_snapshot_meta(snap_dir: Path) -> dict:
    """读快照元数据 (snapshot.yaml: data_version/page_size/sort_key/抓取时间)。"""
    meta_path = snap_dir / "snapshot.yaml"  # 血缘与页宽的快照侧来源 (GT 唯一的"站点口径"记录)
    if not meta_path.is_file():                                                            # 缺元数据不阻断: 下游默认值全部显式写死, 只损失站点口径
        return {}                           # 缺元数据不阻断, 但下游默认值全部显式写死
    return yaml.safe_load(meta_path.read_text(encoding="utf-8")) or {}  # 空文件归 {}


def _load_server_count(snap_dir: Path) -> Optional[int]:
    """读 getcount 回包 (count.json) — 与 rows_full 行数交叉核对, 不一致记 warn。"""
    count_path = snap_dir / "count.json"   # 冻结的服务端计数: 只作交叉核对, 不作权威
    if not count_path.is_file():                                       # 缺 count.json 返 None: 它只作交叉核对, 不是权威, 缺失不影响 gold 成立
        return None
    try:
        return int(json.loads(count_path.read_text(encoding="utf-8"))["total"])
    except (ValueError, KeyError, TypeError):
        return None                         # 解析不了就当没这项, 绝不猜一个计数


def _snapshot_fingerprint(snap_dir: Path) -> str:
    """快照指纹: 有 manifest.json 取其内容 sha256, 否则对目录内文件算聚合指纹。"""
    manifest = snap_dir / "manifest.json"  # 有 manifest 就用它: 与 freeze 工具同口径
    if manifest.is_file():                                                    # 有 manifest 就用它: 与 freeze 工具同口径, 免得两套指纹算法并存
        return "sha256:" + hashlib.sha256(manifest.read_bytes()).hexdigest()
    if not snap_dir.is_dir():                                                         # 缺目录给显式哨兵值: 便于 M6 判「数据不存在」而不是「数据变了」
        return "sha256:absent"             # 缺目录是显式哨兵值, 便于 M6 判"数据不存在"
    parts = []                                                                           # 先攒条目再聚合: 遍历顺序依赖文件系统, 不排序会算出两个指纹
    for path in sorted(snap_dir.rglob("*")):  # 排序: 聚合指纹不得依赖文件系统遍历顺序
        if path.is_file():                                                                  # 只收文件: 目录条目会让同一份快照算出两个不同的聚合指纹
            parts.append(f"{path.relative_to(snap_dir).as_posix()}|{path.stat().st_size}|"
                         + hashlib.sha256(path.read_bytes()).hexdigest())  # 路径+字节: 改名与改内容都会变
    return "sha256:" + hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


def _synthesize_rows(spec: dict) -> list[dict]:
    """S 类回退委托算法层 (见 gold_algorithms.synthesize_rows; 保留本名供旧调用)。"""
    return synthesize_rows(spec)  # 委托算法层: 编排件不自己造行, 免得两份实现漂移


# ---------------------------------------------------------------------------
# 2. 抽样索引 (M2 逐格期望值的取样口径)
# ---------------------------------------------------------------------------

def _sample_indices(total: int, rows: list[dict], compare_columns: list[str],
                    page_size: int) -> tuple[list[int], str]:                            # 抽样索引独立成函数: 抽样规则要能被复核, 不能散在组装代码里
    """抽样索引: ≤50 全取 / 51–1000 取 20% / >1000 取 2%,
    必含: 边界前后各 3 行、末行、极值行 (最亮/最暗)、哨兵行、分页边界行。
    返回 (排序后的索引, 应用的规则说明)。"""
    if total <= 50:                                                                                # 50 行内全取: 再抽样等于让期望值面残缺
        return list(range(total)), "all(<=50)"  # 50 行内全取: 再抽样等于让期望值面残缺
    ratio = 0.2 if total <= 1000 else 0.02      # 比例随规模递减: 固定比例会抽出几万行的期望值集
    step = max(1, int(1 / ratio))               # max(1,...) 兜底: 比例再小也不退化成步长 0
    sampled = set(range(0, total, step))                                        # 等距抽样而非随机: 随机抽样不可复现, 同一份 gold 两次生成会得到不同抽样集
    sampled.update(range(0, min(3, total)))            # 前 3 行 (必抽项)
    sampled.update(range(max(0, total - 3), total))    # 末 3 行: 末页不满只在这里显形
    for column in compare_columns[:1]:                 # 极值行 (首个比较列)
        # 只看第一个比较列: 极值行必抽项要的是"一眼能看出算错了"的样本,
        # 每列都抽会让期望值集爆炸, 而下游实际只看得到第一列
        values = [(idx, to_float(row.get(column))) for idx, row in enumerate(rows)]      # 连下标一起取: 极值行要能定位回具体行, 只留值没法回快照找它
        # 过滤掉转不了数的行: 哨兵/脏值参与 min/max 会把极值行选成一行
        # 哨兵, 那是缺失不是极值, 取它没有意义
        numeric = [(idx, value) for idx, value in values if value is not None]        # 滤掉转不了数的行: 哨兵参与 min/max 会把极值行选成一行缺失
        if numeric:                                                                             # 有数值才谈极值: 全是哨兵时抽不出有意义的极值行
            sampled.add(min(numeric, key=lambda item: item[1])[0])  # 最小值行: 容差写错在这里最显眼
            sampled.add(max(numeric, key=lambda item: item[1])[0])  # 最大值行: 排序/筛选算反也在这里
    for page_start in range(page_size, total, page_size):  # 分页边界行
        sampled.update((page_start - 1, page_start))  # 边界前后各一行: 跨页重复只在这里显形
    # 排序输出: sampled 是 set, 直接返回顺序不确定, 同一份 gold 两次生成
    # 的抽样集会字节不同, M7 确定性判据会因此判红
    return sorted(sampled), f"sampled(ratio={ratio}, step={step})"  # 规则串进 gold: 抽多少可复核


# ---------------------------------------------------------------------------
# 3. 金标准组装
# ---------------------------------------------------------------------------

def _passes_constraints(row: dict, constraints: list, header: list[str], catalog: str) -> bool:
    """AND 全部列约束 (谓词手写实现; 解析不到的列 → 该约束不成立, fail-closed)。"""
    for constraint in constraints:                                                              # 逐条约束: AND 语义, 任一不成立这行就出局
        resolved = resolve_column(header, constraint["column"], constraint["column"], catalog)
        if resolved is None:                                                        # 列解析不到即不成立: 不当「没这条约束」放行 (fail-closed)
            return False  # 列解析不到即约束不成立: 不当"没这条约束"放行 (fail-closed)
        if not match_constraint(row.get(resolved), constraint["op"], constraint.get("value")):
            return False
    return True  # 空约束列表 = 全通过 (不做任何过滤)


def _compare_columns(query: dict, header: list[str], catalog: str,
                     sort_col: Optional[str]) -> list[str]:                            # 比对列集独立成函数: 投影/约束/排序/主键四路来源汇到一起后必须去重
    """M2 逐格比对列集: query.columns (投影) + 约束列 + 排序列 + 主键/坐标列。"""
    columns = list(query.get("columns") or [])    # 起点: 场景显式投影的列
    columns.extend(constraint["column"] for constraint in query.get("constraints") or [])  # 约束列必比: 否则约束对了也验不到值
    if sort_col:                                                                               # 排序列必进比对集: M4 判排序靠的就是这些格的值
        columns.append(sort_col)                  # 排序列必比: M4 排序判据的直接输入
    for logical in ("source_id", "ra", "dec"):
        resolved = resolve_column(header, logical, None, catalog)                     # 主键与坐标列按逻辑名解析: 快照可能带星表前缀, 解析后才拿得到真列
        if resolved:                                                                     # 解析到才追加: 快照里没有的列不能进比对集, 否则每格都会缺值
            columns.append(resolved)              # 主键/坐标列: M1 主键比对与跨行回连靠它
    seen: set[str] = set()                                                                      # 去重集合先建: 重复列会把 M2 的比对分母虚高
    unique = []                                                           # 保序去重的结果容器: 顺序决定 field_values 的写入序, 会影响 gold 字节
    for column in columns:                                                                # 逐列判重: 保序去重不能退化成 set, 那样会丢掉原始顺序
        if column not in seen:                                                                      # 已见即跳过: 同一列只断言一次
            seen.add(column)                      # 去重保序: 重复列会把 M2 的比对分母虚高
            unique.append(column)                                                         # 首次出现才追加: 与 seen 必须同步改, 两处分开放会漏
    return unique


def _proximity_gold(gold: dict, query: dict, rows: list[dict], tolerances: dict,
                    header: list[str], catalog: str) -> dict:                      # 批量语义独立成函数: 它的键形态与锥搜分支不同, 混在一个函数里会互相污染
    """批量 proximity 金标准 (E2 §5 #5): 每输入取半径内最近邻 (并列取主键小者)。

    行键 = ``in<idx>:<row_key>`` (input_index 复合键, E2 §2); 无匹配的输入
    不产行, 但在 batch_inputs 明细里记 matched_key=null (覆盖 一对一 /
    一对多(近者胜) / 无匹配三类); inputobjs_* 回连由明细的 input_index 承担。
    默认语义 nearest_only=True (src/crossmatch.py submit_upload_job 默认值:
    每个输入位置只保留最近匹配) — 与 E2 §5 #5"每个输入的最佳匹配"一致。

    dist 交叉核对: 行若带 inputobjs_dist_arcsec (快照冻结的响应形态), GT 用
    独立 haversine 复算并与冻结值比对 — 不一致记 dist_cross_check (冻结值仍是
    field_values 的期望值: 回放里 SUT 返回的就是冻结响应, GT 不篡改 frozen truth)。
    """
    radius = float(query.get("radius_arcsec") or 0.0)      # 0 = 无半径语义, 全不过滤
    ra_col = resolve_column(header, "ra", query.get("ra_column"), catalog)  # 逻辑列 → 快照实际列
    dec_col = resolve_column(header, "dec", query.get("dec_column"), catalog)
    inputs_detail, out_rows, dist_warnings = [], [], []  # 明细/行集/dist 警告三份, 缺一不可
    for index, point in enumerate(query["inputs"]):
        ra, dec = float(point["ra"]), float(point["dec"])  # 输入点强转 float: 场景里是字符串形态
        candidates = []                                                                          # 候选表逐输入重建: 每个输入点的最近邻互不影响
        for row in rows:                                                                    # 逐行扫全量: 半径过滤在内存里做, 快照行集是唯一数据源
            row_ra = to_float(row.get(ra_col)) if ra_col else None                                  # 行坐标现取: 裸名与前缀名两种形态都要试
            row_dec = to_float(row.get(dec_col)) if dec_col else None                 # dec 同理: 与 ra 保持同一套回退顺序, 两处写岔会只剩一半行
            if row_ra is None or row_dec is None:                                       # 缺坐标即跳过: 当 0 度会在赤经 0 附近凭空造出一批「命中」
                continue  # 坐标脏值/缺列: 判不了锥内, 跳过而不是当 0 度
            distance = angular_separation_arcsec(ra, dec, row_ra, row_dec)  # 独立 haversine, 不借被测实现
            if distance <= radius:                                                     # 边界含等号: 与 E2 §5 #2 同口径, 否则锥边界行成对失配
                candidates.append((distance, row_key(row), row))  # 带主键: 并列距离时有确定次序
        candidates.sort(key=lambda item: (item[0], item[1]))  # 距离优先、主键次级: 近者胜且并列可复现
        detail = {"input_index": index, "input_ra": ra, "input_dec": dec,
                  "matched_key": None, "separation_arcsec": None,
                  "candidates": len(candidates)}  # 无匹配也留 candidates=0, 三类覆盖才查得动
        if candidates:                                                                 # 无候选也要进明细: 三类匹配 (一对一/一对多/无匹配) 都得可查
            distance, key, row = candidates[0]  # 只留最近匹配: 与 crossmatch 的 nearest_only 默认一致
            out_rows.append({"input_index": index, "key": f"in{index}:{key}", "row": row})  # 复合键含 input_index
            detail["matched_key"] = key
            detail["separation_arcsec"] = distance
            frozen_dist = to_float(row.get("inputobjs_dist_arcsec"))
            if frozen_dist is not None and abs(frozen_dist - distance) > 1e-6:     # 超过 1e-6 才记警告: 浮点尾数差属正常, 只有肉眼可见的偏离才值得报
                dist_warnings.append({                                                    # 警告同时带两个值: 只报「不一致」没法判断是冻结错还是算法错
                    "input_index": index, "key": key,
                    "gt_haversine_arcsec": round(distance, 6),
                    "frozen_inputobjs_dist_arcsec": frozen_dist,
                    "warning": "快照冻结 dist 与独立 haversine 不一致 (冻结值仍为期望值; "
                               "建议 freeze 侧按 haversine 重修 dist 列)"})  # 只记警告, 期望值仍取冻结值
        inputs_detail.append(detail)  # 无匹配的输入同样入明细: "无匹配"这一类要可查
    compare_columns = _compare_columns(query, header, catalog, None)  # 批量侧不按 input_index 排
    field_values, null_semantics = {}, {}                                                           # 两张表先建空: 键是复合键而不是行号
    for item in out_rows:                                                               # 只对产出的行填: 没有匹配的行压根没被断言, 不该出现在期望值里
        entries, states = row_cells(item["row"], compare_columns, header, catalog, tolerances)  # 手写逐格实现
        field_values[item["key"]], null_semantics[item["key"]] = entries, states
    unit_map, precision_map = unit_precision_maps(compare_columns, header, catalog, tolerances)  # 单位与精度表在末尾统一出: 依赖最终比对列集, 早算会漏列
    return {
        "row_keys": [item["key"] for item in out_rows],   # M1 比对单位: 与主结果用同一套键
        "row_count": len(out_rows),
        "key_field": "input_index:source_id",            # 复合键声明: 排序/回连都按这两段
        "field_values": field_values,                     # M2 逐格期望值
        "field_values_sampled": False,                   # 批量侧行数可控, 一律不采样
        "null_semantics": null_semantics,                # M3 语义声明 (缺失/零/有值)
        "unit_map": unit_map,
        "precision_map": precision_map,
        "ordering": {"key": "input_index", "order": "asc", "declared": True,
                     "sequence": [item["key"] for item in out_rows], "monotonic": True},  # 按输入序, 天生单调
        "pagination": {"page_size": int(query.get("page_size") or _DEFAULT_PAGE_SIZE),
                       "pages": 0, "page_hashes": [], "page_hash_algo": _PAGE_HASH_ALGO,
                       "note": "proximity 批量一次响应不分页, 分页指标记 N/A"},  # M4 分页项记 N/A 而非编页数
        "truncation": {"expected_total": len(out_rows), "expected_truncated": False,
                       "expected_returned": len(out_rows)},  # 一次响应不截断: 期望总数 = 产出行数
        "result_state": "rows" if out_rows else "empty",  # M5 状态: 有行/空, 无 error 形态
        "batch_inputs": inputs_detail,                    # 三类匹配的证据都在这里
        "dist_cross_check": dist_warnings,                # 冻结 dist 与独立 haversine 的分歧清单
        "notes": query.get("notes", ""),
        "_rows": [item["row"] for item in out_rows],       # 中间态: 构完审核清单即从 gold 里 pop
    }


def build_gold(scenario_path: Path, snapshots_root: Path) -> dict:
    """主入口: 场景 YAML → gold dict。"""
    scenario = yaml.safe_load(Path(scenario_path).read_text(encoding="utf-8"))
    case_id = scenario["case_id"]             # case 唯一标识: 产物文件名由它决定
    snapshot_id = scenario["snapshot_id"]     # 场景点名要回放哪份快照
    query = scenario.get("query") or {}       # 查询段: 三个分支共用同一份口径
    expect = scenario.get("expect") or {}     # 期望态只用来选分支, 不直接进金标准
    tolerances = load_tolerances()            # 容差取 evals/_data 单点, 绝不硬编码数值

    snap_dir = Path(snapshots_root) / snapshot_id                                       # 快照目录由场景点名拼出: 不猜目录, 猜错就是拿别份数据当金标准
    expect_error = expect.get("result_state") == "error"  # 错误态走独立分支 (M5 不许降级 EMPTY)
    rows = _load_snapshot_rows(snap_dir)                                                  # 先读真值行: None 与空列表语义不同, 后面要据此选分支
    rows_source = f"snapshot:{snapshot_id}/rows_full.csv"  # 血缘写进 gold: M6 靠它追数据出处
    if rows is None:                                                                       # 没有 rows_full 才进回退分支: 有真值就绝不合成
        spec = None if expect_error else scenario.get("synthesize")
        if spec is None:                                                            # 错误态不给 synthesize: 错误态本就不该有行集, 合成等于编造
            if expect_error:                                                             # 错误态与普通场景分流: 两者产物形态完全不同, 不能共用一条路
                # 错误态快照 (软 404 等) 只有 phase1.html/count.json, 无行集 —
                # GT 不产行, 不需要 rows_full (E2 §5 soft404)
                rows, rows_source = [], f"snapshot:{snapshot_id} (error-state, 无行集)"  # 显式标注无行集
            else:
                raise FileNotFoundError(
                    f"快照缺失且无 synthesize 回退: {snap_dir}/rows_full.csv "
                    f"(case={case_id}); L 类快照由 freeze 阶段生成")  # 既无快照又无回退: 停, 不编空金标准
        else:
            rows = _synthesize_rows(spec)  # S 类场景: 由算法层造行, 血缘改标 synthesize
            rows_source = "scenario:synthesize"
    meta = _load_snapshot_meta(snap_dir)                                                   # 元数据读在分支之前: catalog 与页宽两条分支都要用
    server_count = _load_server_count(snap_dir)                                   # 交叉核对的输入: 与行集行数不等时只记警告, 权威始终是 rows_full
    header = list(rows[0].keys()) if rows else []  # 列名以行集为准: 快照 CSV 表头即 schema
    catalog = query.get("catalog") or meta.get("catalog") or "ps1"  # 优先级 场景 > 快照 > ps1
    page_size = int(query.get("page_size") or meta.get("page_size") or _DEFAULT_PAGE_SIZE)  # 页宽同一优先级
    max_rows = query.get("max_rows")
    max_rows = int(max_rows) if max_rows is not None else None  # None = 不截断, 与 M4 期望三元组对齐
    # 主键列解析一次, 三条分支共用: 12 张表实测 5 种列名形态, dr3xpcorr/xpsp 的主键
    # 是 `gaiaxp_photinfo_replenish_source_id` —— 硬编码 source_id/ps1_source_id
    # 两个名字会让它们恒判成"无主键", 单对象精确查询整条退化成 0 行。
    sid_col = resolve_column(header, "source_id", query.get("source_id_column"), catalog)

    gold: dict[str, Any] = {                                                          # 基础字段先建: 三条分支共用这一份, 分支只做 update 不重写
        "gold_id": f"gold_{case_id}",
        "case_id": case_id,
        "snapshot_id": _snapshot_fingerprint(snap_dir),  # 存指纹不存目录名: 数据换了必须一眼看出
        "data_version": meta.get("data_version") or (
            "synthetic@" + case_id if rows_source.endswith("synthesize") else snapshot_id),  # 数据血缘字段
        "generator": {"script": "gen_gold.py",                    # 生成器自报家门: 复算不一致要能定位
                      "script_sha256": "sha256:" + hashlib.sha256(
                          Path(__file__).read_bytes()).hexdigest()},  # 脚本指纹: 改算法必改指纹
        "rows_source": rows_source,                              # 与上面的指纹配对: 数据来自哪、是谁产的
        "max_rows": max_rows,  # 用于判定达到客户端行数上限后是否还应探测空页
        "key_field": "source_id" if any(
            str(row.get(sid_col)).strip()
            for row in rows) else "(ra,dec)@9digits",  # 主键形态: 有 id 用 id, 否则量化坐标
    }
    if server_count is not None and server_count != len(rows):                  # 两个数都在且不等才记: 缺 count.json 属「没这项」, 不是「不一致」
        gold["count_cross_check"] = {"server_count": server_count,          # 冻结的服务端计数
                                     "rows_full_count": len(rows),            # 权威行集行数
                                     "warning": "count.json 与 rows_full.csv 不一致, 以 rows_full 为权威"}  # 只记警告

    # ---- 分支 1: 批量 proximity (E2 §5 #5) ----
    if query.get("inputs"):
        result = _proximity_gold(gold, query, rows, tolerances, header, catalog)       # 批量分支整体覆盖基础字段: 键形态不同, 逐字段 merge 必漏
        gold.update(result)                                    # 批量语义整体覆盖基础字段
        gold.pop("_rows", None)                               # 原始行不进产物: 体积大且会被误当期望值
        return gold

    # ---- 分支 2: 错误态 (E2 §5 soft404; M5 阻断项: ERROR 不得降级 EMPTY) ----
    if expect_error:                                                                     # 错误态独立分支: M5 明令 ERROR 不得降级 EMPTY
        gold.update({                                                                   # 整块 update: 错误态字段集固定, 少写一个键下游就取不到
            "row_keys": [], "row_count": 0,                   # 错误态零行: 这里不能塞"空结果"的行集
            "field_values": {}, "null_semantics": {},
            "unit_map": {}, "precision_map": {},
            "ordering": {"key": None, "order": None, "sequence": [], "declared": False},  # 无排序可断言
            "pagination": {"page_size": page_size, "pages": 0, "page_hashes": [],
                           "page_hash_algo": _PAGE_HASH_ALGO},  # 页数 0 而非 None: 不分页是确定事实
            "truncation": {"expected_total": 0, "expected_truncated": False,
                           "expected_returned": 0},           # 三计数全 0: ERROR 态不得伪装成截断
            "result_state": "error",                          # M5 判定的锚点: error 不得降级 empty
            "expected_error_code": expect.get("error_code"),  # 场景声明的错误码是 M5 的期望值
            "notes": scenario.get("notes", ""),
        })
        return gold  # 错误态也是一份完整金标准: 零行零格, 但每个判据都有明确的期望值

    # ---- 分支 3: 锥搜 + 列约束 + 单对象精确 (E2 §5 #1/#2/#3) ----
    ra_col = resolve_column(header, "ra", query.get("ra_column"), catalog)  # 逻辑列 → 快照实际列名
    dec_col = resolve_column(header, "dec", query.get("dec_column"), catalog)
    # 主键列已在基础字段处解析一次 (三条分支共用), 此处不再重复解析
    radius = float(query.get("radius_arcsec") or 0.0)          # 半径取场景口径, 0 = 不做锥筛
    kept: list[dict] = []                                      # 过滤后的行集: GT 只对它们下断言
    for row in rows:                                                                             # 逐行筛: 空间过滤先做, 缩小候选集再逐列过滤
        if query.get("source_id"):
            sid = str(row.get(sid_col, "")).strip() if sid_col else ""  # 主键列解析不到即空串: 与 query 的 id 必不等, fail-closed 出局
            if sid != str(query["source_id"]).strip():
                continue                                      # 按 id 取源: 不等即出局
        else:
            ra = to_float(row.get(ra_col)) if ra_col else None                          # 行坐标现取: 两种列名形态都要试, 缓存会与后续约束看到不同形态
            dec = to_float(row.get(dec_col)) if dec_col else None                                 # dec 同理: 与 ra 保持同一套回退顺序
            if ra is None or dec is None:                                                        # 缺坐标即出局: 不猜, 猜错会把脏行混进金标准
                continue                                      # 坐标脏值: 判不了锥内, 不猜
            distance = angular_separation_arcsec(float(query["ra"]), float(query["dec"]), ra, dec)  # 独立 haversine
            if distance > radius:      # d <= radius 含等号 (E2 §5 #2)
                continue
        if not _passes_constraints(row, query.get("constraints") or [], header, catalog):
            continue  # 列约束在锥筛之后判: 先缩小候选集, 再逐列过滤
        kept.append(row)                                                                    # 空间与列约束都过才收: 任一不过这行就不该出现在期望值里
    total = len(kept)                                                                # 总量取过滤后: M4 的期望总数是「本该返回多少」, 不是快照有多少行
    # id 唯一性判据 (2026-10-04): 真实回包里 ps1_source_id 既可能整列为空、也可能重复,
    # 重复 id 当主键会让两行塌成同一格 → M2 拿 A 行期望比 B 行实际, 报成假失配。
    # 判据取**过滤后的完整行集**(不是当页): 分页不该改变主键形态。
    coords_only = not id_keys_unique(kept)
    truncated = max_rows is not None and total > max_rows  # 截断判据: 过滤后总数超上限才算
    returned = min(total, max_rows) if max_rows is not None else total  # 期望返回行数, M4 三元组的一元
    sort_col = resolve_column(header, query.get("sort", ""), query.get("sort"), catalog) if query.get("sort") else None
    order = query.get("order", "asc")                          # 只认 asc/desc, 其它值按 asc 处理
    if sort_col:                                                                    # 有排序列才排: 未声明排序时给的是参考序, declared=false
        kept.sort(key=lambda row: (sort_key(row.get(sort_col)), row_key(row, coords_only=coords_only)),  # 主键次级: 并列才有确定序
                  reverse=(order == "desc"))
        keys = [sort_key(row.get(sort_col)) for row in kept]                                  # 排序键现取: 必须与 M4 判单调用的是同一套键函数
        ordered = all(a <= b for a, b in zip(keys, keys[1:])) if order == "asc" else \
            all(a >= b for a, b in zip(keys, keys[1:]))                                # 升序降序各判一次: 共用一个 all() 会让降序场景永远判不通过
        if not ordered:                                                                  # GT 自己不单调即停: 不产出脏金标准, 错误要显形而不是被吞
            raise ValueError(f"GT 内部不一致: 排序键非单调 (case={case_id})")  # GT 自己错就停, 不产出脏金标准
    else:
        kept.sort(key=lambda row: row_key(row, coords_only=coords_only))   # 未声明排序: GT 给确定性参考序, declared=false
    shown = kept[:returned] if truncated else kept   # 截断时只留应返回部分: GT 断言的就是这批
    pages = paginate(shown, page_size)               # 按页宽切页: M4 要页数与逐页指纹

    compare_columns = _compare_columns(query, header, catalog, sort_col)                       # 比对列集在排序确定后算: 排序列本身就是比对列之一
    missing_columns = [column for column in (query.get("columns") or [])
                       if resolve_column(header, column, column, catalog) is None]  # 快照缺列清单
    field_values: dict[str, dict] = {}                                                              # 先建空表: 键是行主键, 逐行填入
    indices, rule = _sample_indices(len(shown), shown, compare_columns, page_size)     # 抽样索引与规则一起出: 规则串要进 gold, 事后能复核抽了多少
    if len(shown) <= _FIELD_VALUES_SAMPLE_CAP or len(indices) <= _FIELD_VALUES_SAMPLE_CAP:  # 行数或抽样数超上限才截断: 任一条件满足就说明清单会过大
        value_indices, sampled_values = indices, len(shown) > 50   # 全量入 gold; >50 行标"已抽样"
    else:
        value_indices, sampled_values = indices[:_FIELD_VALUES_SAMPLE_CAP], True  # 超上限截断到 cap
    null_semantics: dict[str, dict] = {}                                                  # 语义表独立建: 值与语义态分开存, M2 与 M3 各读各的
    for index in value_indices:                                                   # 只对选中的行逐格算: 未选中的行不进 field_values, 分母要如实
        key = row_key(shown[index], coords_only=coords_only)                                 # 主键现算: 与 M1 的主键函数同源, 两处自己造必然失配
        entries, states = row_cells(shown[index], compare_columns, header, catalog, tolerances)  # 手写逐格
        field_values[key], null_semantics[key] = entries, states                          # 两表同一次遍历产出: 语义态与值必须同源, 分开算会自相矛盾
    # 缺列显式 null (E2 §5 #7: 不得填 0、不得编造、不得判失败)
    for key in null_semantics:                                                                 # 缺列声明只走已产出的行: 没有行的键不需要声明缺列
        for column in missing_columns:                                                  # 逐个缺列补声明: 缺列显式为 null, 既不填 0 也不判失败
            null_semantics[key][column] = "null"  # 显式语义声明: 缺列是"该列缺失", 不是 0 值
            field_values[key][column] = {"v": None, "t": "null", "unit": None,
                                         "atol": None, "rtol": None, "raw": None,
                                         "note": "column absent in snapshot"}  # 期望值留 None 供 M2 判
    unit_map, precision_map = unit_precision_maps(compare_columns, header, catalog, tolerances)   # 单位与精度表在末尾统一出: 依赖最终比对列集
    gold.update({                                                                          # 整块 update: 字段集固定, 少写一个键下游就取不到
        "row_keys": [row_key(row, coords_only=coords_only) for row in shown],   # M1 比对单位: 顺序即 gold 断言的顺序
        "row_count": len(shown),
        "field_values": field_values,                  # M2 逐格期望值 (可含采样标记)
        "field_values_sampled": sampled_values,       # 采样事实必须显式: 否则"没这条"会被读成"值一致"
        "field_values_sampling_rule": rule,
        "null_semantics": null_semantics,             # M3 语义声明
        "unit_map": unit_map,
        "precision_map": precision_map,
        "ordering": {"key": sort_col, "order": order, "declared": bool(sort_col),  # declared=false 时 M4 不判单调
                     "sequence": [row_key(row, coords_only=coords_only) for row in shown], "monotonic": True},
        "pagination": {"page_size": page_size, "pages": len(pages),
                       "page_hashes": [page_hash(page) for page in pages],  # 逐页指纹: M4 查重/查漏
                       "page_hash_algo": _PAGE_HASH_ALGO,
                       "last_page_full": bool(pages) and len(pages[-1]) == page_size,  # 末页满 → 该多翻一页
                       "extra_page_expected_empty": (bool(pages) and len(pages[-1]) == page_size
                           and (max_rows is None or returned < max_rows))},  # 达到max_rows会停翻, 否则满页后应验证空页
        "truncation": {"expected_total": total, "expected_truncated": truncated,
                       "expected_returned": returned},  # M4 三元组: 任一错即该项 fail
        "result_state": "rows" if shown else "empty",  # M5 状态锚点: 零行是 empty, 不是 error
        "missing_columns": missing_columns,            # 缺列清单随 gold 走: 审核时要能核对
        "notes": scenario.get("notes", ""),
    })
    return gold


def main(argv: Optional[list[str]] = None) -> int:
    """CLI: 场景 YAML → gold JSON。退出码 0/1。"""
    parser = argparse.ArgumentParser(                                                 # 三个入参都由调用方给: 场景/输出/快照根, 脚本不自己猜
        description="E2 独立金标准生成器 (oracle; 严禁 import 被测判定逻辑, "
                    "自检: guard_no_src_imports.py)")
    parser.add_argument("--scenario", required=True, help="场景 YAML 路径")
    parser.add_argument("--out", required=True, help="gold JSON 输出路径")
    parser.add_argument("--snapshots-root", default=str(_DEFAULT_SNAPSHOTS_ROOT),
                        help="快照根目录 (默认 evals/groundtruth/snapshots)")
    args = parser.parse_args(argv)                                              # argv 为 None 时读 sys.argv: 脚本直跑与被当模块调用都要能用
    gold = build_gold(Path(args.scenario), Path(args.snapshots_root))  # 唯一生成路径, CLI 不重写逻辑
    out_path = Path(args.out)                                                            # 输出路径由入参决定: CLI 不自己猜落点, 临时产物不进仓内
    out_path.parent.mkdir(parents=True, exist_ok=True)  # 目录不存在就建: 产物目录由调用方给
    # newline="\n": 仓内 .gitattributes 对 *.json/*.yaml 钉 LF, 不显式钉住就会按
    # 平台默认写成 CRLF, 于是 git 每次 add 都报 "CRLF will be replaced by LF"、
    # 工作区与版本库长期不一致 (check_line_endings 也会把它列出来)
    out_path.write_text(json.dumps(gold, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")  # 写金标准
    print(f"gold: {out_path} (rows={gold['row_count']}, state={gold['result_state']}, "
          f"source={gold['rows_source']})")  # 摘要行: 行数/状态/来源, 一眼看出分支走对没有
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
