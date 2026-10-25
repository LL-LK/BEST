# -*- coding: utf-8 -*-
"""evals.ablation.runner — E5 入口 (--systems all|B3 --category D|C|R|S --repeat N --scripted)。

能力边界 (docs/eval-E5-baseline-ablation.md §10 执行流程):
  ``--scripted`` = ScriptedLLM + 快照回放, **全离线** (不接真实模型、不打真实站点);
  ``--freeze``   = 把 hypotheses.yaml 冻结到 temp/ablation/ (跑前登记, 跑后只核对)。
  编排件: 装载 → 跑批矩阵 → L0 三门合成 → 反证自测 → 五张表报告 → JSON/MD 输出。
  退出码 0 = 全过; 1 = 有 fail (含 metascore < 1.00、B3 触红线、指纹不一致)。

放行条件 (E5 §11 阻断项, 任一命中即 FAIL) —— 编号沿用文档 §11 原文, 故 4 与 6
之间的跳号**不是笔误**。落点分三层, 别当成全都住在 _blockers() 里:
  _blockers() 真正实现的: 1 (metascore < 1.00)、4 (B3 自身三条红线)、
      7 (repeat < 3), 外加一条文档未列的「scripted 指纹不稳定」;
  上游 fail-closed 直接抛错的: 2 (缺快照 → harness/run_batch.py 抛
      FileNotFoundError)、6 (hypotheses.yaml 未标 frozen: true → load_hypotheses
      抛 ValueError) —— 这两条不进 blockers 清单, 因为它们压根跑不到汇总那一步;
  文档 §11 另有两条**尚无机器判定**: 第 5 条「任务集与 E1/E3 的既有标注冲突未裁决
      就跑批」与第 8 条「盲评纪律破坏 (代号泄露 / 出题人兼任评阅人)」—— 后者依赖尚未
      启用的 L2 盲评。即 E5 对这两条只能由人工复核兜底。

白盒锚点: docs/eval-E5-baseline-ablation.md §10 (执行流程与产物) / §11 (阻断项);
evals/ablation/report.py (§12 五张表)。
"""
from __future__ import annotations

# 标准库: 参数 / JSON / 哈希 / 路径 / 时间
import argparse
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any, Optional

# 脚本直跑 (`python evals/ablation/runner.py`) 时 sys.path[0] 只含本目录 —
# 挂 skill 根 (供 evals.* 命名空间包); 本文件在 evals/ablation/ 下, 上溯两级。
_HERE = Path(__file__).resolve()                                                                   # 以本文件反推路径: 不依赖调用时的 cwd
sys.path.insert(0, str(_HERE.parents[2]))                                            # 脚本直跑时 sys.path[0] 只含本目录, 命名空间包全靠这一行

# 本地: 反证自证/跑批矩阵/合成指标/报告四件 (判据单点在此层)
from evals.ablation.broken import run_broken_selftest  # noqa: E402
from evals.ablation.harness.run_batch import (  # noqa: E402
    SYSTEM_ORDER,
    load_items,
    load_systems,
    run_matrix,
    select_items,
    write_traces,
)
from evals.ablation.metrics.composite import aggregate  # noqa: E402
from evals.ablation.report import render_report  # noqa: E402

ABLATION_DIR = _HERE.parent                            # 本实验根
HYPOTHESES_PATH = ABLATION_DIR / "hypotheses.yaml"     # 预登记假设, 跑前必须已标 frozen
TEMP_FREEZE_DIR = _HERE.parents[2] / "temp" / "ablation"   # 冻结件只进 temp/ (仓内铁律)


def _read_yaml(path: Path) -> dict:
    """读 YAML (缺文件即抛 — fail-closed, 不静默跳过)。"""
    # 第三方: 用例集/装配表装载 (items/systems 的 YAML 事实源)
    import yaml

    if not path.is_file():                                                                    # fail-closed: 资产缺失即抛, 不静默跳过
        raise FileNotFoundError(f"E5 资产缺失: {path}")
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}   # 空文件读成 None, 归一成空 dict


def load_hypotheses() -> dict:
    """读预登记假设 (未标 frozen: true 即拒绝跑批 — HARKing 阻断项 6)。"""
    payload = _read_yaml(HYPOTHESES_PATH)   # 路径写死在本实验: 跨实验 import/读表都不允许
    if not (payload.get("freeze") or {}).get("frozen"):   # 没标 frozen 即拒跑 (HARKing 阻断项 6)
        raise ValueError("hypotheses.yaml 未标记 frozen: true — 拒绝跑未冻结的假设")
    return payload


def freeze_hypotheses() -> dict:
    """把 hypotheses.yaml 冻结到 temp/ablation/ 并出 sha256 (跑前登记)。"""
    # 标准库: 预登记假设的冻结拷贝 (跑前登记落 temp/)
    import shutil

    payload = load_hypotheses()   # 先过冻结守卫, 否则等于把未冻结的假设"冻结"一遍
    TEMP_FREEZE_DIR.mkdir(parents=True, exist_ok=True)   # 幂等: 反复 --freeze 不该因目录已存在而炸
    target = TEMP_FREEZE_DIR / f"hypotheses-frozen-{int(time.time())}.yaml"
    shutil.copyfile(HYPOTHESES_PATH, target)   # 复制而非改写原件: 冻结件要与在册件可比对
    return {"frozen_at": str(target),
            "sha256": "sha256:" + hashlib.sha256(target.read_bytes()).hexdigest(),
            "declared_frozen_at": (payload.get("freeze") or {}).get("frozen_at"),
            "n_ablations": len(payload.get("ablations") or []),   # 条数进摘要: 事后增删会被 sha256 抓到
            "n_baselines": len(payload.get("baselines") or [])}


def run(system_names: Optional[list[str]] = None, category: str = "all",
        repeat: int = 3, seed: Optional[int] = None,
        capture: Optional[dict] = None) -> dict:
    """跑批 → 成绩单 + 反证自测 + 放行判定 (替身批或 live 批, 由 capture 决定)。

    Args:
        system_names: 要跑的装配 id (None = 全装配)。
        category: 只跑某一门 (D/C/R/S 或 all)。
        repeat: 每 (装配, 任务) 的重复次数。
        seed: 顺序随机化种子。
        capture: 真模型采集表 (None = ScriptedLLM 替身批)。给定时走
            :class:`CapturedLLM` 回放真实模型决策, 缺采集即抛而不回落替身。
    """
    items = load_items()   # 30 任务全集: 分类筛选在 select_items 里做, 不在这里丢
    load_hypotheses()  # 守卫: 未冻结即抛 (HARKing 阻断项); 渲染时再读一份
    systems = load_systems(system_names)   # None = 全装配; 显式列表 = 只跑指定几个
    chosen = select_items(items, category, seed)   # 任务顺序由 seed 定: 同 seed 才能复跑
    batch = run_matrix(list(systems), items=chosen, repeat=repeat, seed=seed,
                       capture=capture)   # 跑批矩阵在 harness 层: 本层只喂参数与搬运, 不自建判据
    cards = aggregate(batch["runs"], items)   # 三门合成绩在这一层, runner 只搬运不重算
    broken = run_broken_selftest()   # 与跑批同批出: 判定器失效则整批结论作废
    # T4 统计表: 逐 run 三门口径 → 题级多数票 → 与 B3 配对 (McNemar/Wilson/Holm/bootstrap)
    # add-back: 装回零件 ≡ 基线, 故退化为基线的采样稳定性检验 (见 stats.addback_check)
    # exchangeability: 重复轮次是否可交换 —— 不可交换时上面两项 repeat 统计的前提不成立
    from evals.ablation.metrics.stats import (  # 就地导入: 只有出报告才需要
        addback_check,  # §4 基线采样稳定性 (装回零件 ≡ 基线, 退化成稳定性检验)
        build_t4,  # T4 配对统计表 (McNemar / Wilson / Holm / bootstrap)
        exchangeability_check,  # 重复轮次可交换性 (2026-10-10 新增的采集侧闸)
    )
    t4 = build_t4(batch["runs"], chosen)
    addback = addback_check(batch["runs"], chosen)
    exchange = exchangeability_check(batch["runs"], chosen)
    blockers = _blockers(cards, batch, broken, repeat, exchange)   # 阻断项集中一处判, pass 即"无阻断"
    return {"meta": {"n_items": len(chosen), "n_systems": len(systems),
                     "repeat": max(1, repeat), "seed": seed,
                     "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                     "deterministic": batch["determinism"]["deterministic"],
                     "unstable": batch["determinism"]["unstable"]},
            "cards": cards, "broken": broken, "blockers": blockers,
            "t4": t4, "addback": addback, "exchangeability": exchange,
            "mode": batch["mode"], "pass": not blockers, "runs": batch["runs"],
            "items": chosen}   # 预登记核对要做逐题配对: 把题集随报告带出, 免得渲染层再猜


def _blockers(cards: dict[str, dict], batch: dict, broken: dict, repeat: int,
              exchange: Optional[dict] = None) -> list[str]:
    """汇总 E5 §11 阻断项 (任一命中即整体 FAIL; 无 fail-open)。"""
    blockers: list[str] = []   # 清单而非布尔: 报告要逐条显示挂在哪个判据上
    if broken.get("metascore", 0.0) < 1.0:   # 缺 metascore 按 0 算, 不得因"没跑"而放行
        missed = [fid for fid, r in broken.get("results", {}).items() if not r["caught"]]
        blockers.append(f"metascore={broken.get('metascore')} < 1.00 (漏抓: {missed})")
    if not batch["determinism"]["deterministic"] and batch.get("mode") != "live":
        # 指纹不稳 ⇒ 跑批不可复现, 直接阻断。**这条只对替身批成立**: 替身是确定性的,
        # 指纹不同说明跑批管线本身有问题。真模型批 (mode=live) 的多次采样**本就该有
        # 差异** (temperature=0.2), 把它当阻断等于要求模型每次输出逐字节相同的答案
        # —— 那既不真实、也不是本实验要测的东西。真模型批的不稳定任务清单仍进
        # meta.unstable, 供 §8 的「极差 >0.05 标不稳定」使用。
        blockers.append(f"scripted 指纹不稳定: {batch['determinism']['unstable'][:5]}")
    # 采集侧轮次污染 (2026-10-10): 三次重复若不是独立样本, add-back 与 T4 的前提即不成立。
    # **按门判** (2026-10-10 收紧): 实测污染只落在表述门 (E 7/7, p=4.6e-04), 而决策门
    # (D 2/11, p=0.11) 与取数门 (F 0/1, p=1.00) 由可交换数据支撑 —— 一刀切成"整批不可用"
    # 会把 D/F 上有效的消融证据一起废掉。故只点名被污染的门, 并声明其余门不受影响。
    bad_gates = (exchange or {}).get("non_exchangeable_gates") or []
    if bad_gates and batch.get("mode") == "live":
        detail = "；".join(
            f"{g} {v.get('n_attempt1_strictly_max')}/{v.get('n_systems')} (p≤{v.get('p_upper'):.2e})"
            for g, v in sorted(((exchange or {}).get("gates") or {}).items())
            if v.get("exchangeable") is False)
        blockers.append(
            f"capture_attempts_non_exchangeable: 通道 {'/'.join(bad_gates)} 的重复轮次不是独立样本"
            f" ({detail}) — 依赖该通道的 repeat 类统计 (add-back / T4 多数票) 前提不成立; "
            f"其余通道的结论不受此条影响 (采集侧缺陷, 非被测系统失败)")
    b3 = cards.get("B3") or {}   # 只审 B3: 其余系统的红线是实验对象而非放行判据
    if b3.get("ParamHallucination"):   # §11 阻断项 4: B3 自身不得出参数幻觉
        blockers.append(f"B3 自身 ParamHallucination={b3['ParamHallucination']}")
    if b3.get("HR_fatal"):             # 编出无来源的致命数值
        blockers.append(f"B3 自身出现致命编造数值 (HR_fatal={b3['HR_fatal']})")
    if b3.get("s1_tasks"):             # 说了禁答的话 + 数值错 = 静默错值
        blockers.append(f"B3 自身出现 S1 静默错值: {b3['s1_tasks']}")
    if repeat < 3:                     # §11 阻断项 7: 少于 3 次不得谈显著性
        blockers.append(f"repeat={repeat} < 3 — 不得下显著性结论 (scripted 冒烟须显式标注)")
    return blockers


def render_markdown(report: dict, hypotheses: dict, t5_verdicts_path: str = "") -> str:
    """渲染六张表 (report.render_report) + T4 统计表 + T5 错误谱系 + 放行判定行。"""
    t4_text = ""
    if report.get("t4"):   # T4 由 stats.build_t4 现算: 无 runs 时为 None, 不留空表
        from evals.ablation.metrics.stats import render_t4  # 就地导入: 只有出报告才需要
        t4_text = render_t4(report["t4"])
    addback_rows = None
    if report.get("addback"):   # add-back 检验行: 同上, 无 runs 时退回"待跑"文案
        from evals.ablation.metrics.stats import render_addback
        addback_rows = render_addback(report["addback"])
    body = render_report(report["cards"], hypotheses, report["broken"], report["meta"],
                         mode=report.get("mode", "scripted"),   # 口径进报告: 待跑项表按 live/scripted 分叉
                         t4_text=t4_text,                       # T4 插在表 3 与表 5 之间, 编号连续
                         addback_rows=addback_rows,             # add-back 实测行替换表 3 的"待跑"
                         t5_available=bool(t5_verdicts_path),   # T5 是否已出: 待跑项表据此改状态
                         runs=report.get("runs"), items=report.get("items"))  # 预登记核对的**逐题配对**证据
    verdict = "PASS" if report["pass"] else "FAIL"   # 判定行由 blockers 空否推出, 不另设人工结论
    lines = [body, ""]
    if t5_verdicts_path:   # T5 需盲评产物 (运行时物, 不入库): 给了才渲染, 不给就整张不出现
        from evals.ablation.metrics.taxonomy import build_t5_from_files, render_t5
        cases_path = str(Path(t5_verdicts_path).with_name("t5_cases.json"))
        lines += [render_t5(build_t5_from_files(cases_path, t5_verdicts_path)), ""]
    lines += [f"## 放行判定: **{verdict}**", ""]
    if report["blockers"]:           # 命中即逐条列出, 读者可照着复现阻断原因
        lines.append("阻断项 (任一命中即 E5 FAIL):")
        lines.extend(f"- {b}" for b in report["blockers"])
    else:
        lines.append("- 无阻断项命中 (metascore=1.00 / B3 无红线 / 指纹一致 / 假设已冻结)。")
    lines.append("")
    return "\n".join(lines)   # 拼接而非套模板: 五张表由 report.py 独立维护


def main(argv: Optional[list[str]] = None) -> int:
    """CLI: --systems / --category / --repeat / --scripted / --seed / --json / --md / --out。

    ``--systems`` 接受 ``all`` 或逗号分隔的系统 id (如 ``B3`` / ``B0,B3``);
    scripted 模式 = ScriptedLLM + 回放, 全离线 (真实模型跑批待 API, 见 §14 依赖风险)。
    """
    parser = argparse.ArgumentParser(description="E5 baseline & ablation runner")
    parser.add_argument("--systems", default="all",
                        help="all 或逗号分隔系统 id (B0/B1/B2a/B2b/B3/A1..A5/sham_placeholder)")
    parser.add_argument("--category", default="all", choices=["all", "D", "C", "R", "S"])
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--scripted", action="store_true",
                        help="ScriptedLLM + 快照回放 (全离线; 缺省即此模式)")
    parser.add_argument("--capture", default="",
                        help="真模型采集表路径 (JSON, 形态见 harness/captured_llm.py 模块头); "
                             "给了即 live 臂, 缺采集即抛而不回落替身")
    parser.add_argument("--seed", type=int, default=None, help="任务顺序随机化种子")
    parser.add_argument("--freeze", action="store_true", help="冻结预登记假设到 temp/")
    parser.add_argument("--json", default="", help="JSON 报告输出路径")
    parser.add_argument("--md", default="", help="Markdown 报告输出路径")
    parser.add_argument("--out", default="", help="逐 run 轨迹输出目录 (默认 evals/ablation/runs)")
    parser.add_argument("--traces", action="store_true", help="落盘逐 run 轨迹")
    parser.add_argument("--overwrite-traces", action="store_true",                 # 显式开关: 覆盖旧轨迹等于销毁上一轮数据, 默认必须拒
                        help="允许覆盖已存在的同名轨迹 (默认拒写: 只增不改)")
    parser.add_argument("--require-live", action="store_true",
                        help="实验门禁: 跑批不是 live 臂 (即替身) 即记 scripted_not_live 阻断 (铁律 5 禁 fail-open)")
    parser.add_argument("--t5-verdicts", default="",
                        help="T5 盲评产物路径 (JSON: {anon_id: 错误类型}); 给了才出 T5 错误谱系表, "
                             "案例清单默认取 temp/t5_cases.json")
    args = parser.parse_args(argv)                                                            # argv 显式传入: 自测能绕开子进程调同一份解析器

    if args.freeze:     # --freeze 是独立动作: 登记完即返回, 不与跑批叠加
        print(json.dumps(freeze_hypotheses(), ensure_ascii=False, indent=2))                     # 冻结登记只回显不落报告: 它是跑批前的独立动作
        return 0

    # 采集表: 路径给了就现读现用 (fail-closed —— 路径错/文件坏即抛, 不静默回替身批)
    capture = None
    if args.capture:
        cap_path = Path(args.capture)
        if not cap_path.is_file():
            parser.error(f"--capture 指定的采集文件不存在: {args.capture} (不回落替身: "
                         f"静默回落会让标着 live 的批次里混进替身结果)")
        capture = json.loads(cap_path.read_text(encoding="utf-8"))
        # 两种形态都要认: ① 带 provenance 的完整表 (subagent_capture.build_capture 产物,
        # 入库资产); ② 只有决策的裸表 (strip_provenance 产物)。前者先校验来源声明
        # (缺声明即拒收 —— 说不清谁跑的 live 批次不可归因), 再取 decisions 层喂 CapturedLLM。
        if "decisions" in capture and "provenance" in capture:
            from evals.ablation.harness.subagent_capture import (  # noqa: PLC0415
                check_capture_provenance,
                strip_provenance,
            )
            check_capture_provenance(capture)   # fail-closed: 缺 model_kind/producer 即抛
            capture = strip_provenance(capture)
    names = None if args.systems in ("all", "") else [   # all 与空串都归一成"跑全装配"
        s.strip() for s in args.systems.split(",") if s.strip()]
    unknown = [n for n in (names or []) if n not in SYSTEM_ORDER]   # 未知 id 早失败: 静默跳过看不出来
    if unknown:                                                                              # 未知 id 当场退出: 静默跳过会让少跑的系统看不出来
        parser.error(f"未知系统 id: {unknown} (合法: {', '.join(SYSTEM_ORDER)})")
    load_hypotheses()  # 守卫: 未冻结即抛 (HARKing 阻断项)
    report = run(names, category=args.category, repeat=args.repeat, seed=args.seed,
                 capture=capture)              # 跑批与渲染共用同一份成绩单: 中间不得再改数据
    # 跑批模式门禁: scripted 跑出来的相对排序是**替身的排序**, 不是模型能力的排序;
    # 报告虽已列三条不可测项, 但 pass=True 仍会被读成"E5 通过"。开了 --require-live
    # 而本批不是 live 臂 (没给 --capture) 即阻断 —— 反过来, 给了 --capture 的 live 臂
    # 不再被这条门禁打回, 这是该门禁第一次有通过路径 (I2, 2026-10-04)。
    report["mode"] = "live" if capture is not None else "scripted"                  # 如实记账: 无论闸门开没开, 模式都进报告
    report["live_required"] = bool(args.require_live)
    report["capture_path"] = args.capture or None
    if args.require_live and report["mode"] != "live":
        report["blockers"] = list(report["blockers"]) + ["scripted_not_live"]
        report["pass"] = False
    hypotheses = load_hypotheses()  # 渲染用 (与跑批同一份, 跑后只核对不改写)
    payload: dict[str, Any] = {k: v for k, v in report.items() if k != "runs"}
    if args.json:                                                                                   # 两路产物各自可选: 只给一种路径也不该崩
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)   # 目录自建: 落 temp/ 新层级也跑得动
        Path(args.json).write_text(json.dumps(payload, ensure_ascii=False, indent=2),  # 逐 run 轨迹不进 JSON: 体积大, 另有 --traces 出口
                                   encoding="utf-8")
    markdown = render_markdown(report, hypotheses,
                               t5_verdicts_path=args.t5_verdicts)   # T5 可选: 给了盲评产物才出错误谱系表
    if args.md:        # 给了 --md 就落盘, 末尾再回显到 stdout
        Path(args.md).parent.mkdir(parents=True, exist_ok=True)                                    # 目录自建且幂等: 反复跑不因目录已存在而炸
        Path(args.md).write_text(markdown, encoding="utf-8")
    if args.traces or args.out:   # 显式开关: 逐 run 轨迹量大, 不默认落盘
        write_traces(report, Path(args.out) if args.out else None,                                  # 轨迹量大, 只在显式开关下才落盘
                     overwrite=args.overwrite_traces)                                               # 拒覆盖是默认: 旧轮次是数据, 不是缓存
    print(json.dumps({"pass": report["pass"], "blockers": report["blockers"],
                      "mode": report["mode"],        # 替身还是真模型: 与 pass 并列回显, 不许只落在 --json 里
                      "metascore": report["broken"].get("metascore"),
                      "meta": report["meta"],
                      "ESR_full": {s: c.get("ESR_full") for s, c in report["cards"].items()},
                      "ESR_data": {s: c.get("ESR_data") for s, c in report["cards"].items()},
                      "ESR_know": {s: c.get("ESR_know") for s, c in report["cards"].items()}},
                     ensure_ascii=False, indent=2))                                        # stdout 只回显三段 ESR 与阻断项: 明细在文件里
    if args.md:                                                                                     # 回显是给人看的, 不参与门禁判定
        print(markdown)                                                                         # 同一串 Markdown 再打一遍, 不重新渲染
    return 0 if report["pass"] else 1   # 退出码即门禁: make eval-e5 靠它判 SUCCESS/FAIL


if __name__ == "__main__":
    raise SystemExit(main())
