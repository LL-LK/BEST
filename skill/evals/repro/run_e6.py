# -*- coding: utf-8 -*-
"""evals.repro.run_e6 — E6 编排入口 (R0 实跑 / R1-R3 留 adapter / 计分 / 自证)。

能力边界: CLI 编排件 —
  - ``--freeze-manifest``: 组装八项固定清单并落盘 (缺项 fail-closed);
  - ``--lane R0 --repeat N``: 工具层固化回放实跑 (无模型), 采集 runs;
  - ``--lane R1/R2/R3``: 需外部 LLM harness (离线不接模型), 只校验 lane
    参数并提示 adapter 契约 (留接口不造假);
  - ``--score``: 四一致率 (TSC/PAC/RDC/FCC) + 归因分布 + Wilson 区间;
  - ``--efficiency`` / ``--usability``: EF1..EF7 / U1..U7;
  - ``--selftest``: 反证夹具 12/12 才放行 (metascore=1.0) —— 两组: 一致性扰动 6 + trace 完整性 6,
  分母见 broken/__init__.py::run_broken_selftest。
退出码沿用 eval_runner 约定: 0 全过 / 1 有 fail。

白盒锚点: docs/eval-E6-reproducibility.md §11 (执行流程与产物) / §8 (门槛);
evals/repro/r0_lane.py (R0 执行件); consistency/ (四一致率)。
"""
from __future__ import annotations

# 标准库: 参数 / JSON / 路径 / 时间
import argparse
import json
import sys
import time
from pathlib import Path

# 本地: 各指标件与编排依赖 (脚本直跑自挂路径)
_HERE = Path(__file__).resolve()                                    # resolve 先消软链: 经软链调用时 parents 才指向真实仓根, 否则 sys.path 挂错
sys.path.insert(0, str(_HERE.parents[1]))   # evals/ (paths 兄弟裸导入)
sys.path.insert(0, str(_HERE.parents[2]))   # skill 根 (evals.* 命名空间包)

# 本地: 指标面六件 (归因/反证/四一致率/效率/清单/归一/R0/统计/可用性)
from evals.repro.attribution import attribute_lane  # noqa: E402
from evals.repro.broken import run_broken_selftest  # noqa: E402
from evals.repro.consistency import fcc, pac, rdc, tsc  # noqa: E402
from evals.repro.efficiency import summarize_efficiency  # noqa: E402
from evals.repro.manifest import (  # noqa: E402
    build_manifest,  # 清单面四件之一: 组装与校验必须同源, 分两处写就会出现两套必填项
    canary_fingerprint,  # 数据版本探针: 清单里那对 before/after 指纹由它产出
    load_manifest,  # 复跑读回冻结的那一份: 不重新生成, 否则清单锁不住任何东西
    save_manifest,  # 落盘即冻结: 复跑比的是这份文件, 不重新生成, 否则清单锁不住任何东西
    sha256_file,  # 文件指纹: 工具面与暴露面两个键都由它算, 两处必须同算法
    validate_manifest,  # 校验器: 冻结后要独立复验一次, 不信任组装方自己说的通过
)
from evals.repro.normalize import norm_args, norm_card  # noqa: E402
from evals.repro.r0_lane import run_lane  # noqa: E402
from evals.repro.stats import bootstrap_mean_ci  # noqa: E402
from evals.repro.usability import summarize_usability  # noqa: E402

REPRO_DIR = _HERE.parent                      # 本实验根: 任务 / 夹具 / 清单都挂在它下面
FIXTURES_DIR = REPRO_DIR / "fixtures"         # 回放快照目录: R0 唯一的"数据源"
RUBRIC_PATH = REPRO_DIR / "rubric.yaml"       # 人评量表: 不进机判, 只作冻结口径
# 放行线/观察线常量 (0.90 / 0.85) 一律不得在本文件定义: E1/E4/E2 各自在自己的
# graders/metrics 里定义阈值, R0 不做加权评分用不上; 这里再放一份只会让人以为
# 改它能调 R0 的放行线。任务集路径同理, 只由 manifest.py 持有
# (task_set_fingerprint 的默认参数), 本文件不重复定义。


def _freeze_manifest(args) -> dict:
    """组装并落盘固定清单。

    **为什么 canary 必须冻结输入** (2026-10-07 复核): 本函数证的是"同一输入前后
    一致", 而输入一旦接活站点, 站点数据漂移就会让 canary 变红 —— 而那与被测代码
    毫无关系。实测同一查询 (ps1/180/30/60") 快照记 1 行、真站点返 174 行。所以:

    - ``replay`` 探针 (本实现): 走固化快照, 判的是**代码层确定性** (R0 的地板线
      定义, 见 docs/eval-E6-reproducibility.md §2.1)。这一路的价值恰恰在于它**不看**
      站点 —— 换句话说它是"剥离环境噪声后的纯代码侧"判据。
    - ``live`` 探针 (:func:`_live_canary_probe`): 额外打一次真站点, 把站点侧
      观测**显式记进清单**。它不进指纹, 也不参与"稳定/漂移"判定 —— 只作为
      "这次跑批时站点在什么状态"的留痕, 让报告读者能区分"代码变了"与"站点变了"。

    换句话说: 冻结输入的探针不是"离线内容", 它是**消融对照** —— 与 live 探针
    并存, 才能把代码侧变化与环境侧变化分开归因。
    """
    # 本地: 自包含两阶段回放 (与 E2 transport 同语义, 可读不可 import)
    from evals.repro.transport import ReplayTransport
    from src.client import BestClient

    probes = []                                                                     # 五个探针的结果行集: 顺序即 canary 指纹的输入, 循环次序不能改
    failed_probes: list[str] = []                                                   # 探针失败清单: 空行集不能兼作「失败」与「零命中」两种含义
    for fixture in ("ps1_5rows", "scr_galah_0rows", "ps1_singlepage"):
        transport = ReplayTransport(FIXTURES_DIR / fixture)   # 每探针一个独立回放口, 不跨探针串状态
        # rate_limit=0.0 在这里是对的: 请求全被下一行的 transport 拦下, 整批零外网
        # 流量, 节流只会把跑批睡死 —— 触不触网是 transport 决定的, 不是限速器。
        client = BestClient(base_url="http://replay.local", rate_limit=0.0)
        client.session.get = transport.get    # 猴补丁取数口: BestClient 自身逻辑一行不改
        client.session.post = transport.post  # POST 一并换掉, 将来加写操作不会漏回放口
        try:
            result = client.cone_search(ra=180.0, dec=30.0, radius_arcsec=60.0,         # 探针走真客户端逻辑: 只换传输口, 被测的解析与取数路径一字不改
                                        catalog="ps1", max_records=5)
            rows = [dict(getattr(s, "raw_data", {}) or {}) for s in (result.sources or [])]
        except Exception as exc:      # 探针抛错要记账, 不能吞成空行集
            # fail-closed: 异常绝不能吞成 `rows = []` —— canary_after 直接复用
            # before, 那样「探针全挂」与「跑批稳定」在指纹上**同形**, 一条恒真的
            # 稳定性证据比没有证据更糟。失败单独记进 failed_probes, 循环结束后
            # 显式抛错阻断跑批; 探针成功时本分支不执行, 判定语义与指纹值均不变。
            rows = []
            failed_probes.append(f"{fixture}: {exc!r}")
        probes.append(rows)   # 顺序即指纹输入, 循环次序不能改
    if failed_probes:                                                               # 探针全挂 = 没有稳定性证据, 不得按「稳定」放行
        raise RuntimeError(                                                        # 铁律 5: 目标缺失/未签字 = FAIL, 不得静默跳过
            f"E6 canary 探针失败 {len(failed_probes)}/{len(probes)}, 稳定性无证据, "
            f"拒绝按 STABLE 出清单: {failed_probes}")
    # 补足 5 探针 (ps1/gaia_dr3_18/scr_galah/stripe82/xpsp 的口径: 回放路用
    # 三快照行 + 两次 count 探针凑满 5 个, 指纹只要求"前后一致")
    while len(probes) < 5:                                                     # 补足到 5 个: 探针数是硬契约, 少一个会让「数据没变」退化成「这一种表没差异」
        probes.append([{"probe": "count", "value": len(probes)}])
    before = canary_fingerprint(probes)   # 只算一次: 冻结输入下 R0 无漂移源, 前后必同值
    live = _live_canary_probe()  # 站点侧留痕: 不进指纹、不参与判定, 只记录"这次站点在什么状态"
    manifest = build_manifest(                                      # R0 无模型可调: model/provider/endpoint 一律显式占位, 留空会被读成配置缺失
        lane="R0", repeat=args.repeat,
        canary_before=before, canary_after=before, drift_state="STABLE",
        model_id="none-R0", provider="none", endpoint="",
        prompt_text="", prompt_template_id="r0-fixed-sequence",
        tools_schema_fp=sha256_file(Path(__file__).resolve().parents[2] / "references" / "tools.schema.json"),
        exposed_schema_fp=sha256_file(Path(__file__).resolve().parents[2] / "references" / "tools.schema.json"),
        snapshot_id="replay-fixtures", snapshot_manifest_fp="",
        temperature=0.0, seed_requested=None, seed_honored=False,                              # 温度与种子显式钉死: 有采样随机性就没有一致率可言
        rate_limit_seconds=0.0,                                                       # 节流归零: 回放路不存在排队, 写进清单才能与在线路的耗时分位区分开
    )
    # 站点侧观测挂进清单的独立字段 (不走 canary_*): 它的作用是让读报告的人能区分
    # 「代码变了」与「站点数据变了」。放进 canary_before/after 会让一次站点更新
    # 被误读成代码层的确定性 bug —— 那正是 R0 要排除的那类噪声。
    manifest["live_site_probe"] = live  # 缺网络时为 {"reachable": False, ...}, 不抛: 无网不等于跑批失败
    # 临时产物只进 temp/ (仓内铁律): 固定清单落 temp/repro/runs/, 不进 evals/
    out = REPRO_DIR.parents[1] / "temp" / "repro" / "runs" / f"manifest-{int(time.time())}.json"
    save_manifest(manifest, out)   # 落盘即冻结: 复跑比的就是这份指纹, 不重新生成
    return {"manifest": manifest, "path": str(out)}


def _live_canary_probe(catalog: str = "ps1", ra: float = 180.0, dec: float = 30.0,
                       radius_arcsec: float = 60.0) -> dict:
    """打一次真站点, 记录站点侧观测 (2026-10-07 新增)。

    **它判什么**: 只回答"这次跑批时, 站点对同一条查询给的是什么量级的答案"。
    实测同一查询固化快照记 1 行、真站点返 174 行 —— 看到这个差, 报告读者就知道
    canary 的"稳定"来自冻结输入而不是站点没变。

    **它不判什么**: 不进 canary 指纹、不参与 drift_state、不阻断跑批。把活数据
    的漂移混进稳定性判定, 恰好会摧毁 R0 作为"地板线"的意义 (它要证明的是
    **代码层**确定性, 见 docs/eval-E6-reproducibility.md §2.1)。

    失败不抛: 无网 / 站点不可达时返回 ``reachable: False``, 因为"探不到站点"
    与"跑批失败"是两件事 —— 前者不该让一次纯本地的 R0 跑批红掉。

    Returns:
        ``{"reachable", "n_rows", "catalog", "queried_at", "error"}`` 形态的字典。
    """
    # 本地: 真客户端 (延迟导入: 只有本函数真要触网时才拉)
    from evals.repro.live_policy import RATE_LIMIT_SECONDS  # 间隔纪律与其他实验同源
    from src.client import BestClient
    from src.protocol import BEST_BASE_URL  # 端点来自协议层真源, 不在此写死

    probed_at = time.strftime("%Y-%m-%dT%H:%M:%S%z")  # 先记时刻: 失败时也知道自己探的是哪一刻
    try:
        client = BestClient(rate_limit=RATE_LIMIT_SECONDS)  # 限速不归零: 真的要触网就得守间隔
        result = client.cone_search(ra=ra, dec=dec, radius_arcsec=radius_arcsec,
                                    catalog=catalog, max_records=5)
        return {"reachable": True, "n_rows": len(result.sources or []),
                "catalog": catalog, "endpoint": BEST_BASE_URL, "queried_at": probed_at,
                "error": None if result.success else repr(result.error)}
    except Exception as exc:  # 探不到站点不是跑批失败, 但必须留痕 (静默吞掉会读成"站点没变")
        return {"reachable": False, "n_rows": None, "catalog": catalog,
                "queried_at": probed_at, "error": f"{type(exc).__name__}: {exc}"}


def bind_manifest(manifest_path: str, repeat: int) -> tuple[dict, list[str]]:
    """把冻结清单与本次跑批绑在一起: 加载 → 校验 → 比对执行参数。

    冻结清单此前只落盘即返回, 后续 R0 执行既不读它也不接受它的路径 —— 于是
    "清单锁住了任何东西" 这句话是空的: 换一组参数重跑, 报告照样出得来。
    这里让跑批必须认同一份清单, 并逐项核对清单记的 lane/repeat/工具面指纹
    与本次实跑一致; 任一不符即阻断 (铁律 5 禁 fail-open)。

    Returns:
        ``(manifest, problems)``; problems 非空即不得出正式结论。
    """
    path = Path(manifest_path)
    manifest = load_manifest(path)                     # 缺失/坏 JSON 直接抛: 拿不到清单就不该跑"正式批"
    problems = validate_manifest(manifest)             # 清单自身先过校验, 下面的比对才有意义
    execution = manifest.get("execution") or {}
    if execution.get("lane") != "R0":                  # 本函数只服务 R0 路: 拿 R1/R2/R3 的清单来跑 R0 是张冠李戴
        problems.append(f"manifest_lane_mismatch:{execution.get('lane')}")
    if int(execution.get("repeat") or 0) != int(repeat):   # 重复次数是一致率的分母, 与清单不符即这批不是清单那一批
        problems.append(f"manifest_repeat_mismatch:{execution.get('repeat')}!={repeat}")
    live_schema = sha256_file(Path(__file__).resolve().parents[2] / "references" / "tools.schema.json")
    for side in ("code_side", "exposed_side"):         # 工具面两侧都核: 清单记的指纹与现版本工具面不符 = 中途改过被测面
        recorded = (manifest.get("tool_schema") or {}).get(side) or ""
        if recorded and recorded != live_schema:
            problems.append(f"manifest_tool_schema_drift:{side}")
    return manifest, problems


def _score(lane_result: dict, lane: str = "R0") -> dict:
    """四一致率 + 归因 + Wilson (一个 lane 的 runs → 分数)。"""
    per_task = {}                                                                     # 先按任务出分再跨任务平均: 直接对 run 求均值会把任务数差异抹平
    distributions = []                                                                # 各任务归因分布逐个攒: 最后合并成报告里的一个数, 但要能逐任务回溯
    for task_id, runs in lane_result["runs"].items():   # 逐任务算: 一致率先按任务出, 再跨任务取均值
        calls_per_run = [[c for c in r["tool_calls"]] for r in runs]
        args_per_run = [[c["args"] for c in r["tool_calls"]] for r in runs]
        rdc_runs = [{"data_hash": r["data_hash"], "row_keys": r["row_keys"],
                     "key_values": {"n": r["cost"]["rows_returned"]}} for r in runs]
        cards = [{"card": r["card"]} for r in runs]   # FCC 只吃最终卡片, 中间过程不进判据
        tsc_res = tsc([[c["tool"] for c in run] for run in calls_per_run])
        pac_res = pac(args_per_run)      # PAC: 逐调用参数归一后取众数
        rdc_res = rdc(rdc_runs, lane=lane)   # RDC 显式传 lane: 取数门判据按 R0 口径分档
        fcc_res = fcc(cards)            # FCC: 众数卡与多卡计数, 分歧越大越低
        # 归因: 众数调用 + 众数卡
        mode_calls = [norm_args(c) for c in pac_res["mode_calls"]]
        mode_card = norm_card(fcc_res["mode_card"] or {})
        attr_runs = [{"tool_calls": r["tool_calls"], "results": r["results"],
                      "card": r["card"], "retries": []} for r in runs]
        distribution = attribute_lane(attr_runs, mode_calls, mode_card)              # 归因吃归一后的参照: 众数调用与众数卡必须与被比较的 run 同一口径
        distributions.append(distribution)                                                # 按任务顺序追加: 合并结果要能逐任务回溯, 顺序乱了就对不上
        per_task[task_id] = {"tsc": tsc_res, "pac": pac_res, "rdc": rdc_res,
                             "fcc": fcc_res, "attribution": distribution}
    n = len(per_task)   # 分母 = 有 runs 的任务数; 为 0 时各一致率记 0.0 (阻断), 不记 N/A
    # 逐任务先出比值, 再跨任务平均: 两级都要留痕。报告侧因此能分开读
    # "单任务重复一致率"与"跨任务平均值", 不会把两件事揉成一个数。
    rates = {  # 每档一致率的逐任务取值序列 (bootstrap 的重抽单元就是这些)
        "tsc": [t["tsc"]["tsc"] for t in per_task.values()],
        "pac": [t["pac"]["pac_call"] for t in per_task.values()],
        "rdc": [t["rdc"]["rdc"] for t in per_task.values()],
        "fcc": [t["fcc"]["fcc"] for t in per_task.values()],
    }
    means = {key: (sum(values) / n if n else 0.0) for key, values in rates.items()}  # 跨任务平均: 分母是任务数, 不是 run 数
    # 区间按**任务**分组重抽样: 分母是真实任务数, 不再把均值乘 100 冒充成功次数
    # (旧口径下 5/5 与 100/100 会算出同一个 [0.963,1], 区间与重复次数完全脱钩)。
    # 逐任务重复一致率看 per_task, 跨任务平均值与区间看这里, 两处各自标样本量。
    ci_95 = {key: list(bootstrap_mean_ci(values)) for key, values in rates.items()}
    # 退化标记: 组内取值全同时重抽样只能抽出同一个值, 区间必然零宽。那是**观测到的
    # 任务间离散度为零**, 不等于"真实可复现性被证明为 1.0" —— 零方差样本给不出
    # 有限样本宽度的区间, 必须说出来, 否则 [1.0, 1.0] 会被读成无限确定的结论。
    degenerate = sorted(key for key, values in rates.items() if values and max(values) == min(values))
    n_runs = sum(len(runs) for runs in lane_result["runs"].values())   # 总 run 数: 报告要能核对"每任务几次"
    return {"per_task": per_task, "means": means, "ci_95": ci_95,
            "n_tasks_scored": n,          # 区间与点估计的真实样本量 (任务数), 与 run 数分开披露
            "n_runs_total": n_runs,       # 总重复次数: 用来核对每任务重复是否齐
            "ci_method": "cluster-bootstrap-over-tasks/percentile/seed=20260928",
            "ci_degenerate": degenerate,   # 非空即区间零宽: 任务间零离散度, 见 _render 的措辞
            "coverage": lane_result["coverage"],   # 覆盖面随分数同出: 一致率必须配它读
            "attribution_total": _merge_distributions(distributions)}


def _merge_distributions(distributions: list[dict]) -> dict:
    """合并各任务归因分布 (报告 §12 第 7 个数)。"""
    merged: dict[str, int] = {}                                             # 扁平 {code: count} 逐项累加: 不做跨任务的语义归并, 归并会掩盖分歧类型
    for dist in distributions:   # 分布是扁平 {code: count}, 逐项累加即可
        for code, count in dist.items():                                                    # 按码累加: 同一码在多个任务出现时, 报告要给出的是总量
            merged[code] = merged.get(code, 0) + count                                 # 缺键当 0 起算: 不预置全码表, 预置会让报告出现从未发生过的码
    return merged


def _render(report: dict) -> str:
    """Markdown 报告 (人工复核面; 数字以 JSON 为准)。"""
    lines = ["# E6 跑批报告 (R0 离线)", "",
             f"- 覆盖任务: {report['coverage']['covered']}/{report['coverage']['total']}"
             f" ({report['coverage']['note']})",
             f"- 计分任务数 (区间样本量): {report.get('n_tasks_scored', 0)}"
             f" · 总重复次数: {report.get('n_runs_total', 0)}",
             "- 区间口径: 分组重抽样 (按任务重抽, 百分位法) —— "
             "分母是上行的任务数, **不是**把均值乘 100 冒充成功次数", "",
             "| 一致率 | 点估计 (跨任务均值) | 95% 区间 |", "|---|---|---|"]
    for key, value in report["means"].items():      # 只渲染 means: 权重不在报告层另算一份
        low, high = report["ci_95"][key]   # 区间取自计分层, 渲染不重算, 免两处口径分叉
        lines.append(f"| {key.upper()} | {value:.4f} | [{low:.3f}, {high:.3f}] |")
    if report.get("ci_degenerate"):
        # 只用 GBK 覆盖的字符: --md 直接打到 stdout, Windows 控制台默认 GBK,
        # 一个 U+26A0 之类的符号就能让整批跑批在渲染阶段 UnicodeEncodeError 崩掉
        lines += ["", f"> **注意** {'/'.join(k.upper() for k in report['ci_degenerate'])} 的区间为零宽: "
                      "这批**任务间离散度为零** (重抽只能抽到同一个值), 不是"
                      "「真实可复现性被证明为 1.0」。零方差样本给不出有限样本宽度的区间。"]
    lines += ["", "## 归因分布", ""]
    for code, count in sorted(report["attribution_total"].items()):
        lines.append(f"- {code}: {count}")
    binding = report.get("manifest_binding") or {}
    if not binding.get("bound"):                       # 未绑定清单必须写在报告里, 不能只活在命令行历史中
        lines += ["", "## 清单绑定", "", f"> {report.get('manifest_note', '本批未绑定冻结清单。')}"]
    elif binding.get("problems"):
        lines += ["", "## 清单绑定", "", f"> 已绑定 `{binding['path']}`, 但存在阻断项: {binding['problems']}"]
    else:
        lines += ["", "## 清单绑定", "", f"> 已绑定 `{binding['path']}` 并逐项核对通过 (lane/repeat/工具面指纹)。"]
    lines.append("")
    return "\n".join(lines)


def main(argv=None) -> int:
    """CLI 入口 (退出码 0/1)。"""
    parser = argparse.ArgumentParser(description="E6 reproducibility runner")
    # A4 实测订正: 清单原记「--require-live / --require-full-coverage 连 help 都没写」。
    # **实测两条都已有 help** (`--allow-adapter-required` 与 `--require-full-coverage`
    # 见下), 所以 A4 关于这两条的判断是陈旧的, 不作改动。真正缺 help 的是下面这
    # 七个无参开关 —— `--help` 里它们只留一个光秃秃的名字, 而这几个开关各自决定
    # "跑哪条 lane / 记哪几类指标", 语义只能靠读代码才知道。补齐。
    parser.add_argument("--freeze-manifest", action="store_true",
                        help="把本次 lane/repeat/工具面指纹冻结成清单文件 (配合 --manifest 复核)")
    parser.add_argument("--lane", choices=["R0", "R1", "R2", "R3"], default="R0",
                        help="R0=离线回放确定性; R1/R2/R3=在在线路, 需模型 harness")
    parser.add_argument("--repeat", type=int, default=3,
                        help="每任务重复次数 (确定性判据据此比对多次跑批是否逐字节一致)")
    parser.add_argument("--score", action="store_true", help="算 R0 确定性分数")
    parser.add_argument("--efficiency", action="store_true", help="算效率类指标 (EF1–EF7)")
    parser.add_argument("--usability", action="store_true", help="算可用性类指标 (U1–U5)")
    parser.add_argument("--selftest", action="store_true", help="跑判定器反证夹具自证")
    parser.add_argument("--json", default="", help="JSON 报告输出路径")
    parser.add_argument("--md", action="store_true", help="把 Markdown 报告打到 stdout")
    parser.add_argument("--allow-adapter-required", action="store_true",
                        help="R1/R2/R3 未接模型时仍返回 0 (仅探 adapter 接口的语义; 缺省为 fail-closed 非 0)")
    parser.add_argument("--require-full-coverage", action="store_true",
                        help="实验门禁: R0 有未覆盖任务时记 tasks_uncovered 阻断 (铁律 5 禁 fail-open)")
    parser.add_argument("--manifest", default="",
                        help="绑定冻结清单路径 (--freeze-manifest 的落盘文件); 执行前后按它核对 lane/repeat/工具面指纹")
    args = parser.parse_args(argv)                                          # argv 为 None 时读 sys.argv: 脚本直跑与被当模块调用两种形态都要能用

    exit_code = 0                                                                      # 默认成功: 任一环节出问题都要显式改成 1, 不靠异常传播隐式表达
    manifest_binding: dict = {"bound": bool(args.manifest), "path": args.manifest, "problems": []}
    if args.manifest and not args.freeze_manifest:   # 绑定只对跑批有意义: 与 --freeze-manifest 同开时后者先返回
        _manifest, bind_problems = bind_manifest(args.manifest, args.repeat)  # 清单对不上就是这批不是清单那一批
        manifest_binding["problems"] = bind_problems
        if bind_problems:
            print(json.dumps({"blocker": "manifest_mismatch", "path": args.manifest,   # 阻断项随分数同出
                              "problems": bind_problems}, ensure_ascii=False, indent=2))
            exit_code = 1
    if args.selftest:     # 反证夹具先跑: 12/12 全过才放行 (两组, 勿按单组 6 条记), 不过则把退出码钉成 1
        # 自证不短路: 结果计入退出码, 继续跑后续请求的路面 (make eval-e6
        # 的目标是 --selftest 与 R0 跑批同批出, 不是二选一)
        result = run_broken_selftest()   # broken/ 自证件自带 ReplayTransport, 零网络
        print(json.dumps(result, ensure_ascii=False, indent=2))                         # 自证结果先打印再判退出码: 即使退出码非 0, 也要留下可读证据
        if not result["pass"]:   # 不 return: 后面的 R1-R3 提示与 R0 实跑还要照常跑
            exit_code = 1                                                           # 不提前返回: 后面的路面还要照常跑, 一次调用要能同时拿到自证与跑批结果

    if args.freeze_manifest:   # 冻结清单是独立动作: 落盘校验完即返回, 不与跑批叠加
        result = _freeze_manifest(args)                                                        # 冻结是独立动作: 落盘校验完即返回, 不与跑批叠加
        problems = validate_manifest(result["manifest"])   # 八项缺任一即非空 ⇒ 退出码 1
        print(json.dumps({"path": result["path"], "problems": problems},
                         ensure_ascii=False, indent=2))                                # 连 problems 一起打: 调用方要能直接看出是缺项还是格式错
        return 1 if problems else 0

    if args.lane in ("R1", "R2", "R3"):   # 需外部 LLM harness: 留接口不造假, 打契约即返回
        # 需外部 LLM harness — 离线不接模型, 不造假; 只提示 adapter 契约。
        # 退出码: 默认非 0 (这条 lane 根本没跑, 给 0 就是铁律 5 意义上的 fail-open ——
        # CI 里 "E6 通过" 与 "E6 压根没跑" 长得一模一样)。确属"仅探接口"语义时用
        # --allow-adapter-required 显式放行, 让意图留在命令行里而不是藏在默认值里。
        print(json.dumps({                                           # 在线路只打契约不假跑: 没有 harness 时报 adapter_required, 而不是伪造分数
            "lane": args.lane,
            "status": "adapter_required",
            "executed": False,                                      # 显式记账: 这条 lane 没跑过任何任务
            "allow_adapter_required": bool(args.allow_adapter_required),
            "note": "R1/R2/R3 需外部 LLM harness (model_id/temperature/seed 外部代入); "
                    "本轮仅建离线设施, 留 adapter 接口不跑批",
            "adapter_contract": {
                "input": "utterance + tool schema + system prompt",
                "output": "trace events (model_request/model_response/tool_call/tool_result/final_answer)",
            },
        }, ensure_ascii=False, indent=2))
        return 0 if args.allow_adapter_required else 1

    # R0 实跑
    lane_result = run_lane(repeat=args.repeat)   # R0 走 r0_lane: 工具层固化回放, 无模型可调
    # 无显式选择器时默认出全量报告 (make eval-e6 的 --md 即全量意图)
    show_score = args.score or not (args.efficiency or args.usability)         # 无显式选择器时出全量: 只点 --efficiency 时不该顺手把一致率也打出来
    if show_score:                                                                           # 分数与两个附加面互不依赖: 单独请求哪一项就只算哪一项
        report = _score(lane_result, lane="R0")   # 口径锁 R0: 分数不随 --lane 参数漂
        report["manifest_binding"] = manifest_binding  # 清单绑定状态与分数同出: 不绑定的批次不能被读成"复现成功"
        if not manifest_binding["bound"]:
            report["manifest_note"] = ("本批**未绑定**冻结清单 (未传 --manifest): "
                                       "结果只能证明'这一轮跑批是什么样', 不能作为'按清单复现成功'的证据。")
        payload = json.dumps(report, ensure_ascii=False, indent=2, default=str)      # 先序列化一次: 落盘与 stdout 必须逐字相同, 免得两处各拼一次
        if args.json:                                                                       # 给了路径才落盘: 临时产物只进临时目录, 不写进实验目录
            Path(args.json).write_text(payload, encoding="utf-8")
        if args.md:                                                           # 显式要 Markdown 才渲染: 渲染层是人工复核面, 数字一律以 JSON 为准
            print(_render(report))                                               # Markdown 给人看: 区间直接取计分层结果, 渲染层不重算免两处口径分叉
        else:
            print(payload)                                                             # 没要 Markdown 就打 JSON: 机器消费面不能掺渲染文本
        # R0 任一致率 < 1.0 即阻断 (文档 §8.2 #3: 地板线必须全一致)
        if any(v < 1.0 for v in report["means"].values()):
            exit_code = 1                                                         # 任一一致率不足 1.0 即阻断: 地板线要求全一致, 不给「大部分一致」放行
        # 覆盖度门禁: 四一致率全 1.0 只在**已跑的 18 条**上成立。R0 不覆盖需 LLM 决策的
        # 14 条 (clarify / reject-utterance / safety), 所以"全 1.0"与"32 条全验过"
        # 是两回事 —— 不额外阻断, 后者会被读成前者 (铁律 5 意义上的 fail-open)。
        if args.require_full_coverage and report["coverage"]["uncovered"]:
            print(json.dumps({"blocker": "tasks_uncovered",          # 阻断项随分数同出: 不能只在注释里说
                              "covered": report["coverage"]["covered"],
                              "total": report["coverage"]["total"],
                              "note": report["coverage"]["note"]},
                             ensure_ascii=False, indent=2))
            exit_code = 1
    if args.efficiency:                                                                      # 效率面独立请求: 它的分母是调用数, 与一致率不可混算
        runs = [r for rs in lane_result["runs"].values() for r in rs]
        print(json.dumps(summarize_efficiency(runs, rate_limit_seconds=0.0),         # 节流传 0.0: 回放路没有真实排队, 传非零会凭空扣掉一段假想的等待
                         ensure_ascii=False, indent=2))
    if args.usability:                                                                  # 可用性面同样独立: 它读答案文本, 依赖一致率结果但可以单独请求
        runs = [r for rs in lane_result["runs"].values() for r in rs]
        print(json.dumps(summarize_usability(runs), ensure_ascii=False, indent=2))    # 可用性不涉耗时口径: 消费逐 run 记录, 传节流参数只会误导读数
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
