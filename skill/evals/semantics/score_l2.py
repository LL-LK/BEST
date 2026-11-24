# -*- coding: utf-8 -*-
"""evals/semantics/score_l2.py — E3 L2 判定汇总 (把 rubric 七格折成五项主指标)。

输入: 两份评阅人打分 (r1_part1/r1_part2) + 现有 L0 预筛报告 (提供"回答中数值
总个数"这个 UNGR 分母)。

口径诚实声明 (每一处近似都写在这里, 不藏在代码里):
  - **SFA**: rubric 定义为「Σ 每题 critical 断言命中数 / Σ 断言总数」, 但评阅
    只给了 fact∈{0,1,2} 这一格, 没给逐断言命中数。故按 `fact/2` 作为该题的
    断言命中比例取均值 —— 当一题的 must_state 条数不为 2 时这是近似。
  - **RQC**: rubric 定义为「已给限定语条数 / 应给条数」。评阅的 qualifier 格
    语义是「2=全部体现 / 1=缺 1 条 / 0=缺 ≥2 条」。故已给条数只能定界:
    qualifier=2 → L, =1 → L-1, =0 → 落在 [0, L-2]。故 RQC 报**区间**, 不报点值。
  - **UCR**: 分母「全部科学主张数」当前无采集口径 (L0 只给无支撑主张数)。
    故只报无支撑主张**计数**, 比率留空, 不拿分母凑一个假比值。
  - **UNGR**: 分母取 L0 预筛抽到的数值总个数 (与判定器同源), 分子取评阅人
    判定的无来源数值个数 (已剔除可推导量)。
  - **SLR**: 分母取 rubric 指定的时序语义题 (A+B+G 轴)。

素材分层 (铁律 3/4): 评阅人的**原始打分**是采集物, 留在 gitignored 的采集目录
(``--live-dir``, 默认 ``temp/live``); 本模块产出的**L2 汇总**才是入库资产
(``--out``)。
"""
from __future__ import annotations

# 标准库: 参数解析/JSON/路径
import argparse
import json
import pathlib

# 路径锚: evals/semantics → evals → 仓根, 故 parents[1] 是仓根
_HERE = pathlib.Path(__file__).resolve().parent          # evals/semantics/
ROOT = _HERE.parents[1]                                  # 仓库根 (evals/semantics → evals → 根)
DEFAULT_LIVE = ROOT / "temp" / "live"                    # 原始评阅采集目录 (gitignored, 非入库资产)

FIELDS = ("fact", "qualifier", "unsourced_num", "fatal_num",       # 评阅人打分的七格
          "unsupported_claim", "static_as_lc", "usability")
JUDGMENT_FILES = ("e3_judgments_r1_part1.json", "e3_judgments_r1_part2.json")  # 同一评阅人的两半
INPUT_FILES = ("e3_judge_input_part1.json", "e3_judge_input_part2.json")      # 评阅输入 (题面+回答)
L0_REPORT_FILE = "e3_report.json"                        # L0 预筛报告: 只取 UNGR 分母


def load_judgments(live: pathlib.Path) -> dict:
    """合并两份评阅人打分 (同一评阅人 R1 的两半)。"""
    out: dict[str, dict] = {}
    for fname in JUDGMENT_FILES:                           # 同一评阅人的两半, 逐份并入
        path = live / fname
        if not path.is_file():
            print(f"[WARN] 缺评阅文件: {fname}")
            continue
        for item_id, g in json.loads(path.read_text(encoding="utf-8")).items():
            out[item_id] = g
    return out


def load_items(live: pathlib.Path) -> dict:
    """读评阅输入 (题面 + 模型回答), 两半合并。"""
    items: dict[str, dict] = {}
    for fname in INPUT_FILES:                              # 评阅输入同样两半, 逐份并入
        payload = json.loads((live / fname).read_text(encoding="utf-8"))
        items.update({i["id"]: i for i in payload})
    return items


def summarize(judged: dict, items: dict, total_numbers: int) -> dict:
    """把七格折成五项主指标; 每一处近似都在 summary 里带一句口径说明。"""
    n = len(judged) or 1                                    # 分母恒为已判条数; 空批记 0/1 而不是抛错

    sfa = sum((judged[k].get("fact", 0) / 2.0) for k in judged) / n   # SFA: fact/2 作每题断言命中比例
    unsourced = sum(int(judged[k].get("unsourced_num", 0) or 0) for k in judged)
    ungr = (unsourced / total_numbers) if total_numbers else None     # 分母为 0 时留空, 不凑比值
    fatal = [k for k in judged if int(judged[k].get("fatal_num", 0) or 0) == 1]
    unsupported = sum(int(judged[k].get("unsupported_claim", 0) or 0) for k in judged)  # UCR 只报计数
    tsg = [k for k in judged if items[k]["axis"] in ("A", "B", "G")]  # SLR 分母 = 时序语义题
    slr_num = sum(1 for k in tsg if int(judged[k].get("static_as_lc", 0) or 0) == 1)
    lo = hi = need = 0                                          # RQC: 只能定界, 故累放下界与上界
    for k in judged:                                       # RQC 只能定界: 逐题累加应给条数与上下界
        length = len(items[k].get("qualifiers") or [])
        need += length
        q = int(judged[k].get("qualifier", 0) or 0)
        if q >= 2:
            lo += length                                     # 全部体现: 上下界都等于应给条数
            hi += length
        elif q == 1:
            lo += max(0, length - 1)                          # 缺 1 条: 上下界都取 L-1
            hi += max(0, length - 1)
        else:
            lo += 0                                           # 缺 ≥2 条: 只能定界到 [0, L-2]
            hi += max(0, length - 2)
    usab = [int(judged[k].get("usability", 0) or 0) for k in judged]
    usab = [u for u in usab if u > 0]                          # 0 = 未评, 不拉低均值

    return {
        "n_items": len(items), "n_judged": len(judged), "unjudged": sorted(set(items) - set(judged)),
        "SFA": round(sfa, 4), "SFA_basis": "mean(fact/2), 近似 Σ断言命中/Σ断言总数",
        "UNGR": (round(ungr, 4) if ungr is not None else None),
        "UNGR_numerator": unsourced, "UNGR_denominator_total_numbers": total_numbers,
        "fatal_num_items": fatal, "fatal_num_count": len(fatal),
        "UCR_count_unsupported_claims": unsupported,
        "UCR_ratio": None, "UCR_note": "分母「全部科学主张数」无采集口径, 只报计数",
        "SLR": (round(slr_num / len(tsg), 4) if tsg else None),
        "SLR_numerator": slr_num, "SLR_denominator": len(tsg),
        "RQC_range": [round(lo / need, 4) if need else None, round(hi / need, 4) if need else None],
        "RQC_need_total": need,
        "usability_mean": (round(sum(usab) / len(usab), 3) if usab else None),
        "usability_n": len(usab),
        "fact_distribution": {str(v): sum(1 for k in judged if judged[k].get("fact") == v) for v in (0, 1, 2)},
    }


def main(argv: list[str] | None = None) -> int:
    """主流程: 读评阅 → 折指标 → 落盘 + 打印。"""
    ap = argparse.ArgumentParser(description="E3 L2 判定汇总")
    ap.add_argument("--live-dir", type=pathlib.Path, default=DEFAULT_LIVE,
                    help="原始评阅采集目录 (默认 temp/live)")
    ap.add_argument("--out", type=pathlib.Path, default=None,
                    help="L2 汇总落盘路径 (默认只打印; 入库资产请显式指定)")
    args = ap.parse_args(argv)                             # 参数: 采集目录与落盘路径
    live = args.live_dir                                    # 采集目录: 原始评阅都在这里

    judg = load_judgments(live)
    if not judg:                                           # 一份评阅都没有 = 不出报告 (铁律 5 禁 fail-open)
        print("[FAIL] 没有任何评阅结果, 不出报告 (铁律 5 禁 fail-open)")
        return 1
    items = load_items(live)                               # 题面 + 回答
    l0_path = live / L0_REPORT_FILE
    if not l0_path.is_file():                              # UNGR 分母无来源就不出报告
        print(f"[FAIL] 缺 L0 预筛报告: {l0_path.name} (UNGR 分母无来源, 不出报告)")
        return 1
    l0 = json.loads(l0_path.read_text(encoding="utf-8"))
    # UNGR 分母: 从逐题预筛结果里取数值总个数 (与判定器同源, 不另设口径)
    total_numbers = sum(r["hits"]["unsourced_numbers"]["total_numbers"]
                        for r in l0.get("results", []))

    judged = {k: v for k, v in judg.items() if k in items}   # 评了但题面没有的条目不计入
    summary = summarize(judged, items, total_numbers)

    if args.out:                                           # 显式指定才落盘, 避免误覆盖已入库资产
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8", newline="\n")
        print(f"[OK] 已落盘: {args.out}")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
