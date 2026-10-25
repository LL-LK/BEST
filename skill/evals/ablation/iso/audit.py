# -*- coding: utf-8 -*-
"""evals.ablation.iso.audit — 采集**后**审计 (越界 / 禁词 / 形状 / 覆盖 / 单写者)。

**为什么必须有这一道**: 结构隔离 (scratch 里没有仓库内容) 只管"投放时干不干净";
本模块管"跑完以后有没有出事"。D-17 的形状是代理**读**了答案键再按自己的话对齐路线 ——
它不会把任何禁词写进输出, 所以**只有写侧扫描抓不到它**; 能抓的是"这一批到底有几个写者"
与"输出的时间戳像不像一个人写的"。

**五项判据**:
  ① 顶层无越界新增 (只该有 prompts/ · out/ · MANIFEST.txt · .owner.json);
  ② 输出不含答案键指纹词;
  ③ 输出形状合规 (单行严格 JSON, 键集恰为 {route, tool_calls}, 零调用约定);
  ④ 覆盖率达标;
  ⑤ **单写者** —— 这是原先完全缺的一条: 输出文件按 mtime 排序后若出现**长时间空档**,
     说明这批被两个写者分两波写过 (D-18 的形状)。实测标定: 干净批的最大空档 ≤ 29.5s,
     已知双写者批 ``rep_b3_r2`` 的空档是 **95s**, 故默认阈值取 60s。

**为什么 ⑤ 要定阈值而不是"看着办"**: 判红必须可复算。阈值调得动, 但**不许**因为某批
"看起来没问题"就给它单独放行 —— 那是纪律, 不是门禁 (D-17/D-18 的共同教训)。

对外接口: ``audit_batch()`` / ``check_single_writer()`` / ``main()``。
"""
from __future__ import annotations

# 标准库: 输出 JSON 的解析 (形状判据)
import json

# 标准库: CLI 入口的 argv
import sys

from evals.ablation.iso.paths import batch_dir  # 根目录 SSOT: 与投放器共用, 杜绝路径单边漂移
from evals.ablation.iso.stage import (  # 常量与写者标记: 不在此处另抄一份口径
    CELLS_FILE,  # 分配格清单: 写了清单外的格即越界写入
    FINISHED_FILE,  # 收尾快照: 事后追加写的比对基准
    FORBIDDEN,  # 禁词表: 投放与审计同一份, 两边漂移会互相放水
    MANIFEST_FILE,  # 清单文件名: 顶层白名单要用
    OUT_DIR,  # 输出子目录: 单写者判据的扫描面
    OWNER_FILE,  # 写者标记: 无主即判红
    PROMPTS_DIR,  # 提示词子目录: 顶层白名单要用
    WRITING_FILE,  # 写会话标记: 审计时它还在 = 采集未正常收尾
    read_owner,  # 读写者标记: 与投放器同一解析
)

# 顶层白名单: 多出一个即"代理往 scratch 里带了东西进来"。
# 写会话标记 WRITING_FILE **刻意不在**白名单里 —— 它只应在采集中存在, 审计时还在即判红。
ALLOWED_TOP = frozenset({PROMPTS_DIR, OUT_DIR, MANIFEST_FILE, OWNER_FILE,
                         CELLS_FILE, FINISHED_FILE})
DEFAULT_MAX_GAP_S = 60.0                                                  # 单写者判据的默认空档阈值 (实测标定值, 见模块头)


def check_single_writer(batch: str, *, max_gap_s: float = DEFAULT_MAX_GAP_S) -> dict:
    """判一批输出**像不像一个人写的** (D-18 的检测侧)。

    Args:
        batch: 批次名。
        max_gap_s: 相邻两个输出文件 mtime 的最大允许空档 (秒)。超过即判"疑似两个写者"。

    Returns:
        ``{"n": 文件数, "max_gap_s": 最大空档, "suspect": 是否疑似多写者,
        "at": 空档出现在哪个文件之前}``。文件数 < 2 时 ``max_gap_s`` 记 0 且不判嫌疑。
    """
    root = batch_dir(batch) / OUT_DIR                                     # 只看输出: 提示词是投放时写的一次性批量, 不参与
    stamps: list[tuple[float, str]] = []                                  # (mtime, 文件名): 排序后逐对求空档
    for path in root.rglob("*.json"):                                     # 递归: 输出按 <装配>/<题号>.json 分层
        stamps.append((path.stat().st_mtime, path.name))
    stamps.sort()                                                         # 时序排序: 空档只在时序上才有意义
    worst_gap = 0.0                                                       # 最大空档: 文件少于 2 个时无从计算
    worst_at = ""                                                         # 空档位置: 排查时直接指到那个文件
    for index in range(1, len(stamps)):                                   # 逐对: 只看相邻, 全局跨度会被慢格掩盖
        gap = stamps[index][0] - stamps[index - 1][0]
        if gap > worst_gap:                                               # 取最大: 一个空档就够判嫌疑, 不取平均
            worst_gap, worst_at = gap, stamps[index][1]
    return {"n": len(stamps), "max_gap_s": round(worst_gap, 3),
            "suspect": worst_gap > max_gap_s, "at": worst_at}


def audit_batch(batch: str, *, expect: int | None = None,
                max_gap_s: float = DEFAULT_MAX_GAP_S) -> dict:
    """审一个批次 (五项判据全跑完再判, 不 fail-fast —— 一次看到全部结果)。

    Args:
        batch: 批次名。
        expect: 期望格数; 给了才判覆盖。
        max_gap_s: 单写者判据的空档阈值。

    Returns:
        ``{"ok": 是否全过, "problems": 问题清单, "n_out": 输出数,
        "writer": 单写者判据结果, "owner": 写者标记或 None}``。
    """
    dst = batch_dir(batch)                                                # 路径走 SSOT: 与投放器同源, 不可能单边漂移
    problems: list[str] = []                                              # 问题清单: 全跑完再汇总, 便于一次定位
    if not dst.is_dir():                                                  # 批次不存在: 判红而非"没审到就算过"
        return {"ok": False, "problems": [f"没有该批次: {dst}"], "n_out": 0,
                "writer": {"n": 0, "max_gap_s": 0.0, "suspect": False, "at": ""}, "owner": None}
    owner = read_owner(batch)                                             # 写者标记: 无主说明投放绕过或未留痕
    if owner is None:                                                     # 铁律 5: 不因"扫不到就当干净"而放行
        problems.append(f"无写者标记 {OWNER_FILE}: 该批无法归属到单一投放者")
    top = {p.name for p in dst.iterdir()}                                 # 顶层快照: 越界新增在这一层最容易看出来
    extra = sorted(top - set(ALLOWED_TOP))
    if extra:                                                             # 多出东西 = 代理往 scratch 里带了物料
        problems.append(f"顶层多出 {extra}")
    outs = sorted((dst / OUT_DIR).rglob("*.json"))                        # 输出清单: 禁词与形状都扫这一批
    for path in outs:                                                     # 禁词扫描: 抓"把答案键物料搬进输出"
        text = path.read_text(encoding="utf-8", errors="ignore")
        for key in FORBIDDEN:
            if key in text:
                problems.append(f"{path.name} 含答案键指纹 {key!r}")
    for path in outs:                                                     # 形状判据: 形状不对说明代理没按契约写
        raw = path.read_text(encoding="utf-8-sig").strip()                # BOM 容错: 代理工具链常带 BOM
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:                               # 半截文件也算: 非原子写的典型伤痕
            problems.append(f"{path.name} 不是合法 JSON ({exc})")
            continue
        if set(payload) != {"route", "tool_calls"}:                       # 键集不对: 该格作废, 不许猜着用
            problems.append(f"{path.name} 键集 {sorted(payload)} != {{route, tool_calls}}")
        elif payload["route"] in ("clarify", "reject") and payload["tool_calls"]:
            problems.append(f"{path.name} 违反零调用约定 ({payload['route']} 却有 "
                            f"{len(payload['tool_calls'])} 调用)")
    writer = check_single_writer(batch, max_gap_s=max_gap_s)              # 单写者判据: 原先完全缺失的一条
    if writer["suspect"]:                                                 # 判红: 空档过大 = 两个写者分两波写过
        problems.append(f"疑似多写者: 输出最大空档 {writer['max_gap_s']}s > {max_gap_s}s"
                        f" (出现在 {writer['at']} 之前) —— D-18 形状")
    if (dst / WRITING_FILE).exists():                                     # 会话未关: 采集中断或第二个写者还在写
        problems.append(f"写会话未关闭 ({WRITING_FILE} 仍在): 采集未正常收尾, 或与另一个写者并发")
    cells_path = dst / CELLS_FILE                                         # 分配格清单: 越界写入的比对基准
    if cells_path.is_file():                                              # 有清单才判: 老批次没有, 不许"没清单就当合规"
        assigned = set(json.loads(cells_path.read_text(encoding="utf-8"))["cells"])
        produced = {f"{p.parent.name}/{p.stem}" for p in outs}            # 实际写了哪些格: 与清单同一拼法
        stray = sorted(produced - assigned)                               # 写了没分配的格 = 代理越界
        if stray:
            problems.append(f"写了未分配的格 {len(stray)} 个 (如 {stray[0]})")
        missing = sorted(assigned - produced)                             # 分配了却没写: 与"覆盖不足"互补但更准
        if missing:
            problems.append(f"分配的格有 {len(missing)} 个没写 (如 {missing[0]})")
    finished = dst / FINISHED_FILE                                        # 收尾快照: 事后追加写在这里现形
    if finished.is_file():                                                # 有快照才比对: 没有即"未经收尾"
        try:
            snapshot = json.loads(finished.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            snapshot = None
            problems.append(f"{FINISHED_FILE} 解析失败: 收尾快照本身损坏")
        if snapshot is not None:
            current = {str(p.relative_to(dst / OUT_DIR)): round(p.stat().st_mtime, 3) for p in outs}
            added = sorted(set(current) - set(snapshot["files"]))          # 收尾后新增的文件
            touched = sorted(k for k, v in snapshot["files"].items()      # 收尾后被改过 mtime 的文件
                             if k in current and abs(current[k] - v) > 0.001)
            if added:                                                     # 追加写: 第二波写者的典型痕迹
                problems.append(f"收尾后又新增 {len(added)} 个输出 (如 {added[0]})")
            if touched:                                                   # 覆盖写: 收尾后有人重写了既有文件
                problems.append(f"收尾后有 {len(touched)} 个输出被重写 (如 {touched[0]})")
    elif (dst / OUT_DIR).is_dir() and outs:                               # 有输出却没收尾快照 = 未走 begin/end 流程
        problems.append(f"无收尾快照 {FINISHED_FILE}: 该批未走 begin_write/end_write, 无法证单写者")
    if expect is not None and len(outs) < expect:                         # 覆盖: 缺格即采集未完成, 不许按比例折算
        problems.append(f"覆盖不足: {len(outs)}/{expect}")
    return {"ok": not problems, "problems": problems, "n_out": len(outs),
            "writer": writer, "owner": owner}


def main(argv: list[str]) -> int:
    """CLI: ``audit.py <批次名> [期望格数] [--max-gap 秒]``。

    Returns:
        0 通过; 1 判红 (问题清单已打印); 2 用法错。
    """
    if len(argv) < 2:                                                     # 用法: 至少给批次名
        print("用法: python -m evals.ablation.iso.audit <批次名> [期望格数] [--max-gap 秒]")
        return 2
    args = argv[1:]
    gap = DEFAULT_MAX_GAP_S                                               # 空档阈值: 默认取实测标定值
    if "--max-gap" in args:                                               # 可调: 但不许为某一批单独放行
        index = args.index("--max-gap")
        gap = float(args[index + 1])
        args = args[:index]
    expect = int(args[1]) if len(args) > 1 else None                      # 期望格数可选: 不填就不判覆盖
    result = audit_batch(args[0], expect=expect, max_gap_s=gap)           # 五项判据一次跑完
    print(f"批次 {args[0]}: 输出 {result['n_out']} 个, 写者判据 {result['writer']}")
    if result["owner"] is not None:                                       # 写者标记回显: 便于对账"谁投的"
        print(f"  写者标记: {result['owner']}")
    if not result["ok"]:                                                  # 判红: 逐条列出, 不合并成一句
        for problem in result["problems"][:20]:
            print(f"  ✗ {problem}")
        return 1
    print("  ✓ 五项判据全过 (越界 / 禁词 / 形状 / 覆盖 / 单写者)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))                                      # 直接跑: 退出码即门禁判定
