# -*- coding: utf-8 -*-
"""evals.nl2tool.runner — E1 跑批入口 (读轨迹 → 打分 → 出报告)。

能力边界: 编排件 — 读 tasks.yaml 标注与 traces/ 实际轨迹, 调 graders 打分,
输出 JSON/Markdown 双份报告。边界: 不联网、不调大模型、不写标注 (标注冻结
后任何改动必须记 CHANGELOG, E1 §9); 轨迹文件只增不改。

白盒锚点: docs/eval-E1-nl2tool.md §8 (数据落地与执行方式) / §9 (防污染)。
"""
from __future__ import annotations

# 标准库: 参数解析 / JSON 读写 / 路径锚定 / 类型标注 / 中位数
import argparse
import json
import sys
from pathlib import Path
from statistics import median
from typing import Optional

# 本地: 中立载体 (skill 根 + YAML 装载; evals/ 兄弟裸导入约定) 与评分器。
# 脚本直跑 (`python evals/nl2tool/runner.py`) 时 sys.path[0] 只含本目录 —
# 同时挂 skill 根 (供 evals.* 包导入) 与 evals/ (供 paths 兄弟裸导入)。
_HERE = Path(__file__).resolve()  # 先 resolve: 经软链调用时上溯层级会算错, 路径锚必须先归一
sys.path.insert(0, str(_HERE.parents[1]))   # evals/ (paths 兄弟裸导入)
sys.path.insert(0, str(_HERE.parents[2]))   # skill 根 (evals.* 命名空间包)
# 本地: 兄弟裸导入 (skill 根与 YAML 装载件, 与 eval_runner 同约定)
from paths import SKILL_DIR, load_yaml_file  # noqa: E402

# 本地: 打分入口 (任务级评分、跨重复聚合与汇总裁决)
from evals.nl2tool.graders import (  # noqa: E402
    DIM_MIN_N,
    DIM_PASS_LINES,
    DIM_WARN_LINES,
    GRADER_WEIGHTS,
    grade_task,
    score_run,
    weighted_score,
)
# 本地: 反证夹具自证入口 (判定器**自身**的门禁, 与被测模型无关)
from evals.nl2tool.broken import run_broken_selftest  # noqa: E402
# 本地: 上下文前缀台账 (占位符具化表的唯一来源; 判分不直接读 yaml, 走本件)
from evals.nl2tool.context_primers import load_context_bindings  # noqa: E402

NL2TOOL_DIR = Path(__file__).resolve().parent  # 本实验根: 标注与轨迹都挂在它下面
TASKS_PATH = NL2TOOL_DIR / "tasks.yaml"       # 标注集已冻结, 任何改动须先记 CHANGELOG
TRACES_DIR = NL2TOOL_DIR / "traces"           # 轨迹按 case 分子目录, 目录名即 source

# 每任务的重复次数口径 (docs/eval-E1-nl2tool.md §8: 每条任务跑 3 次并报方差)。
# 缺省 1 是为金标准自证批准备的: traces/golden/ 每题只有一条合成轨迹, 拿 3 当
# 缺省会让管线自证永远红。模型评测批必须显式传 --expect-attempts 3。
DEFAULT_EXPECT_ATTEMPTS = 1
UNSTABLE_VARIANCE = 0.05    # 跨重复方差阈值: 超过即标"不稳定" (E1 §8 稳定性口径)


def _attempt_sort_key(trace: dict, stem: str) -> tuple:
    """轨迹的重复序键: (run_id, attempt, 文件名)。

    attempt 允许是数字或字符串 (采集侧两种都见过), 按 (类型标记, 值) 分支排序,
    避免数字与字符串直接比较抛 TypeError; 文件名兜底保证顺序确定可复现。
    """
    raw = trace.get("attempt", trace.get("run_index"))
    try:
        attempt = (1, int(raw))          # 数字序: attempt=2 排在 attempt=10 之前
    except (TypeError, ValueError):
        attempt = (0, str(raw))         # 非数字按字符串排: 只求稳定, 不求语义
    return (str(trace.get("run_id") or ""), attempt, stem)


def load_trace_attempts(traces_dir: Path = TRACES_DIR) -> dict[str, list[dict]]:
    """按 task_id 归组读轨迹目录 (同任务的多次重复保留为列表, 按重复序排序)。

    归组而非覆盖: 同名多条轨迹就是"这条任务跑了 N 次"的事实, 早先按 task_id
    建字典时被后写的静默覆盖, 3 次重复只剩 1 次, 方差与重复覆盖无从谈起。

    2026-10-06 修正: 原先只 glob 顶层 ``*.json`` —— 而轨迹实际按来源分子目录
    (``traces/golden/`` 28 条、某来源子目录 78 条 —— 原 ``traces/live-m3/`` 属 M3
    批次, 已于 2026-10-11 移出仓库), 顶层只有 1 条示例。
    于是方案 §8 写的 ``--traces evals/nl2tool/traces`` 只吃到那 1 条, 报告上
    "28 条跑完" 与 "1 条跑完" 长得一模一样 (覆盖门禁虽会拦, 但拦下来的是
    25 条"缺轨迹", 读者只会以为是批量没采全)。改递归收集后该命令才成立。
    """
    attempts: dict[str, list[dict]] = {}   # task_id → 该任务的各次轨迹 (缺目录当空集)
    if not traces_dir.is_dir():            # 目录缺失当空集: 缺轨迹由 run() 逐条列进 missing
        return attempts
    stems: dict[int, str] = {}             # 轨迹对象 → 文件名: 排序兜底键, 靠对象身份取不依赖 dict 可哈希
    # rglob 而非 glob: 轨迹按来源分子目录, 只扫顶层会漏掉绝大多数轨迹。
    # sorted(): 遍历顺序固定, 跑批结果可复现。
    for path in sorted(traces_dir.rglob("*.json")):
        trace = json.loads(path.read_text(encoding="utf-8"))  # 每个轨迹一次解析; 解析失败即炸, 不跳过后继续跑
        task_id = trace.get("task_id") or path.stem          # 文件名兜底: 轨迹漏写 task_id 时仍能配对
        stems[id(trace)] = path.stem                        # 身份键: 文件名只作排序兜底, 不进结果
        attempts.setdefault(task_id, []).append(trace)
    for group in attempts.values():         # 组内排序: 重复序要稳定, 否则方差算在乱序上
        group.sort(key=lambda item: _attempt_sort_key(item, stems[id(item)]))
    return attempts


def aggregate_attempts(task: dict, batch: list[dict], schema_props: dict,
                       context_bindings: Optional[dict] = None) -> dict:
    """把一条任务的多次重复并成一份裁决: 逐维取中位数, 红线取并集。

    中位数而非均值: 重复次数少 (N=3/5), 一次离群就能把均值拖走; 红线并集
    而非交集 —— 任一次出现幻觉就该标红, 多数派不能替少数派洗白。

    ``context_bindings``: 占位符具化表 (来自 context_primers.yaml)。模型评测批
    必须注入 —— 否则 NL2T-09/10/12 这类续接题的 ``<上下文天区的 ra>`` 一律通配,
    杜撰坐标照样拿满分, 分数含水分。金标准自证批可不注入 (合成轨迹本就按标注走)。
    """
    graded = [grade_task(task, trace, schema_props, context_bindings) for trace in batch]     # 每次重复都真判: 少判一次就少一份证据
    dims: dict[str, Optional[float]] = {}
    for dim in GRADER_WEIGHTS:                                            # 按权重表列序输出: 报告列序因此稳定
        values = [g["dims"].get(dim) for g in graded]
        scored = [v for v in values if v is not None]                     # 不适用维不参与中位数
        dims[dim] = median(scored) if scored else None                    # 整组都不适用即 None, 与"得了 0 分"严格区分
    scores = [weighted_score(g["dims"]) for g in graded]                  # 每次重复一个总分: 方差算在总分上
    mean = sum(scores) / len(scores)
    variance = sum((s - mean) ** 2 for s in scores) / len(scores)          # 总体方差: N 很小, 样本方差会低估波动
    red_lines = sorted({line for g in graded for line in g["red_lines"]})  # 并集去重后排序: 同一红线不重复列
    # 2026-10-06 修正: 原先只留 graded[0]["evidence"], 其余重复的证据**全部丢弃** ——
    # 三次重复里第二次调错了工具, 报告上却只看得到第一次的参数比对明细, 复核者
    # 拿着这份 JSON 无法复现"这道題为什么被判过/判挂"。现在逐次证据全量留下;
    # 顶层的 evidence 仍是首次 (老消费方的读取位置不变), 但**明确标注它是首次**。
    return {"task_id": task.get("id"), "dims": dims, "red_lines": red_lines,
            "evidence": graded[0]["evidence"],        # 首次重复的证据 (兼容老消费方); 逐次全量见 attempt_evidence
            "attempt_evidence": [g["evidence"] for g in graded],   # 逐次证据全留: 少留一次就少一份可复核材料
            "evidence_is_first_attempt_only": True,   # 显式声明顶层 evidence 的口径, 免得被当成"代表整组"
            # 中位数会抹掉离群的那一次: 某维出现过比中位数更低的得分时, 这里
            # 逐维点名 (不阻断, 但"1.00 里藏着一次 0.0"必须看得见)。
            "dims_worst": {
                dim: min((g["dims"].get(dim) for g in graded
                          if g["dims"].get(dim) is not None), default=None)
                for dim in GRADER_WEIGHTS
            },
            "attempts": len(graded), "attempt_scores": scores,
            "variance": variance, "unstable": variance > UNSTABLE_VARIANCE}


def load_tasks(tasks_path: Path = TASKS_PATH) -> list[dict]:
    """读标注集 (YAML); 文件缺失/空 → fail-closed 抛错 (不静默出空报告)。"""
    if not tasks_path.is_file():  # 标注缺失即抛: 静默出空报告会被读成"全过"
        raise FileNotFoundError(f"E1 标注集缺失: {tasks_path}")
    data = load_yaml_file(tasks_path)     # 走 paths 的装载件: 同一套 YAML 方言, 不各写各的
    # 两种标注形态都收: 早期 tasks.yaml 是裸列表, 现版是 {"tasks": [...]}
    tasks = data.get("tasks") if isinstance(data, dict) else data  # 两种标注形态都收: 早期是裸列表, 现版包在 tasks 键下
    if not tasks:  # 空标注同样 fail-closed: 有文件没内容不是合法输入
        raise ValueError(f"E1 标注集为空: {tasks_path}")
    return tasks


def load_traces(traces_dir: Path = TRACES_DIR) -> dict[str, dict]:
    """读轨迹目录并按 task_id 归组 (**只取每次任务的首条轨迹**)。

    单次视图: 只想知道"这条轨迹判得怎么样"的调用方 (单测、装载自检) 用它。
    要看重复覆盖与跨重复方差的调用方必须用 :func:`load_trace_attempts` ——
    这里按首次生效, 是"每任务一条"的旧口径, 拿它算重复次数必然少算。
    """
    return {task_id: batch[0] for task_id, batch in load_trace_attempts(traces_dir).items() if batch}


def load_schema_props() -> dict[str, dict]:
    """读工具参数面 (references/tools.schema.json — ParamHallucination 权威)。"""
    schema_path = SKILL_DIR / "references" / "tools.schema.json"  # 参数面挂在 skill 根下, 与鲁棒性护栏读同一份, 不另存
    if not schema_path.is_file():        # 返空字典 = 只跳过值域判定; 幻觉维随之退化为"未判"而非"干净"
        return {}
    schema = json.loads(schema_path.read_text(encoding="utf-8"))   # 按路径读, 不 import E1 判定器
    return {  # 返回"工具名 → 参数名": 幻觉判定只比名字, 不比类型与取值
        tool["name"]: tool.get("inputSchema", {}).get("properties", {})  # 逐层取参数名, 缺键兜空字典而不是崩在半路
        for tool in schema.get("tools", [])  # 工具清单缺失即空表: 幻觉维退化为"未判", 不等于"干净"
    }


def run(tasks_path: Path = TASKS_PATH, traces_dir: Path = TRACES_DIR,
        expect_attempts: int = DEFAULT_EXPECT_ATTEMPTS,
        require_threshold: bool = False,
        primers_path: Optional[Path] = None) -> dict:
    """评分一次跑批; 返回汇总报告 (含逐任务明细、重复覆盖与证据)。

    expect_attempts: 每任务的应有重复次数 (E1 §8 模型评测口径 = 3)。缺轨迹或
    重复数不足的任务**都阻断** —— 少跑的那几条绝不能靠"缩小分母"让加权分
    照旧达标, 那样 1.0 与"只跑了 1/26 条"在报告上长得一模一样。

    require_threshold: 开启后执行 E1 §6.7 的**逐维**通过线 (§6.7 表格第三列)。
    缺省关闭, 理由与 E2/E3/E4/E5 五处闸门同款: 离线自检批不该被打红。
    开启后加权总分达标但某维不过线即阻断 —— 这两件事不是一回事, 见
    ``DIM_PASS_LINES`` 处的注释 (高权重维能靠低权重维塌分把总分抬过 0.90)。

    primers_path: 上下文前缀台账 (context_primers.yaml)。给了就按它把标注里的
    ``<...>`` 占位符**具化**成上文声明的值再比对 —— 续接题的杜撰坐标因此现形。
    不给 (None) 则占位符维持通配, 报告会在 ``context_binding`` 段点名"未具化",
    提醒读者这批分数含水分。模型评测批应当显式给。
    """
    tasks = load_tasks(tasks_path)      # 标注必到: 缺失即抛, 不出空报告
    batch_by_task = load_trace_attempts(traces_dir)    # 轨迹按任务归组: 重复数要看得见
    schema_props = load_schema_props()  # 参数面: ParamHallucination 红线的唯一权威
    # 占位符具化表: 题号 → {参数键: 上文声明的值}。台账读不到 = 空表 (全通配),
    # 这不是失败 —— 但报告要点名, 免得"未具化"被当成"已严格判过"。
    bindings_all: dict[str, dict] = {}
    if primers_path is not None and primers_path.is_file():
        bindings_all = load_context_bindings(primers_path)
    grades, missing, short = [], [], []  # 缺轨迹/重复不足单列: 两者都不得悄悄算成满分
    for task in tasks:  # 逐标注配对: 标注是主表, 轨迹是附属, 少的一边不能反客为主
        task_id = task.get("id")
        batch = batch_by_task.get(task_id) or []
        if not batch:  # 一条都没有: 记缺失并跳过评分, 分母因此不含它 (但 pass 仍被阻断)
            missing.append(task_id)  # 缺一条记一个 id: 报告要能直接点名哪几条没跑
            continue
        if len(batch) < max(1, expect_attempts):   # 有但不够: 仍评分 (留证据), 但进阻断清单
            short.append({"task_id": task_id, "got": len(batch), "expect": max(1, expect_attempts)})
        grades.append(aggregate_attempts(task, batch, schema_props,
                                         bindings_all.get(task_id)))  # 判分三件套齐了才调
    report = score_run(grades) if grades else {  # 全缺轨迹时给固定骨架: 结构不变, 分数字段仍为 0
        "dims": {}, "weighted": 0.0, "pass": False, "warn": False,
        "red_line_tasks": [], "n_tasks": 0,
    }
    # ── 判定器自证门禁 (反证夹具 metascore) ──
    # 2026-10-06 接线: 「坏轨迹必须被判 FAIL, 否则判定器失效」此前只存在于
    # test_graders.py 里, runner 从不调用 —— 判定器自身失效只会让 pytest 变红,
    # 跑批照样 exit 0 并出一份看起来正常的报告。判定器不可信时, 本批所有分数
    # 都不作数 (铁律 5 禁 fail-open), 故与覆盖门禁同级收口、同样把 pass 按 False。
    # 夹具自带最小标注, 不借本次装载的 tasks.yaml: 自证验的是判定器, 标注集被
    # 裁剪时 (单测常态) 不该让整轮跑批崩掉, 也不该把"标注集缺题"误报成"判定器失效"
    selftest = run_broken_selftest(schema_props)
    missed_selftest = [r["fixture_id"] for r in selftest if not r["caught"]]
    mscore = (sum(1 for r in selftest if r["caught"]) / len(selftest)) if selftest else 0.0
    report["metascore"] = round(mscore, 4)      # 元分进报告: §9 反证纪律要求可复核
    report["grader_selftest"] = selftest        # 逐夹具明细: 漏抓要能点名是哪一条判据
    blockers = ([] if not missing else ["missing_traces"]) + ([] if not short else ["attempts_below_expected"])
    if missed_selftest:                          # 判定器失效与"没跑够"是两种阻断, 分开记
        blockers = blockers + ["grader_selftest_failed"]
    report["missing_traces"] = missing          # 缺轨迹必须显式进报告, 不能只体现在分数里
    report["short_attempts"] = short            # 重复不足同样逐条列 id: 少跑不是"跑过"
    report["blockers"] = blockers                # 阻断项独立成列: 与红线任务分开读
    report["coverage_complete"] = not blockers   # 覆盖不完整时上面那个加权分只是"已跑部分的分"
    report["expect_attempts"] = max(1, expect_attempts)
    report["task_grades"] = grades              # 逐任务证据落 JSON, 供人工复核 (E1 §8)
    report["unstable_tasks"] = [g["task_id"] for g in grades if g.get("unstable")]  # 跨重复方差超阈: 单独点名
    # 轨迹来源披露 (防 vacuous 绿): 金标准轨迹由 gen_golden.py 从标注合成
    # (source=golden-from-annotation), 跑的是**判定器管线自证** — 好答案能
    # 被判过; 它不是模型评测结果 (模型评测用 traces/ 下的真实跑批轨迹,
    # source=live-run)。报告必须显式声明, 否则 1.0 会被误读成模型成绩。
    sources = sorted({str(t.get("source") or "live-run") for batch in batch_by_task.values() for t in batch})
    report["trace_sources"] = sources           # 来源集合进报告: golden 与 live 必须可区分
    # 混合来源必须阻断 (2026-10-06): 轨迹收集改成递归后, ``--traces traces`` 会把
    # golden/ 与 live-m3/ 一起收进来并按 task_id 归组 —— 同一任务于是同时含一条
    # 合成的满分轨迹与 N 条真实轨迹, 中位数被合成那条抬住, 真实成绩凭空变好。
    # 两种来源混在一批里, 报告上的分数不属于任何可解释的口径, 故与覆盖门禁同级收口。
    if len(sources) > 1:
        blockers = list(blockers) + ["mixed_trace_sources"]
        report["blockers"] = blockers
        report["coverage_complete"] = False
    if "golden-from-annotation" in sources:     # 合成轨迹必须打免责声明, 防 vacuous 绿
        report["provenance_note"] = (  # 免责声明写进报告正文: 输出被重定向时它也必须留下
            "本批轨迹为金标准合成轨迹 (source=golden-from-annotation): "
            "用于判定器管线自证 (期望轨迹必须被判满分), **不是模型评测结果**; "
            "模型评测请用 traces/ 下的真实跑批轨迹 (source=live-run)。")
    # 占位符具化披露 (2026-10-06): 标注里的 ``<上下文天区的 ra>`` 之类占位符,
    # 在有上文可依时按 primer 具化后比对 (杜撰坐标现形), 无上文时只能通配
    # (杜撰不扣分)。**这两批分数不是同一口径**, 报告必须写清是哪种, 否则
    # "未具化批"的高分会被当成"已严格判过"的成绩来解读。
    report["context_binding"] = {
        "primers_path": str(primers_path) if primers_path is not None else None,
        "bound_tasks": sorted(bindings_all),        # 已具化的题: 占位符按上文声明值比对
        "unbound_note": (                            # 未具化的题: 占位符通配, 分数含水分
            None if bindings_all else
            "本批未注入上下文前缀台账, 所有 <...> 占位符按通配处理 — "
            "续接题 (NL2T-06/08/09/10/12) 杜撰坐标不扣分, 该批分数不可与具化批横评。"
        ),
    }
    # 覆盖门禁在最后一道收口: score_run 只看分数与红线, 看不到"少跑了哪几条"。
    # 缺轨迹/重复不足时把 pass 强行按 False 收 —— 加权分仍留在报告里供诊断,
    # 但它只是"已跑那几条的分", 不能被读成本批通过 (铁律 5 禁 fail-open)。
    if blockers:
        report["pass"] = False
        report.setdefault("coverage_note", "")
        report["coverage_note"] = (f"覆盖不完整 → 本批不放行 (加权分仅覆盖已跑的 "
                                   f"{len(grades)}/{len(tasks)} 条): 缺轨迹 {len(missing)} 条, "
                                   f"重复不足 {len(short)} 条。")
        if "mixed_trace_sources" in blockers:      # 混合来源不是"没跑够", 原因要单独说清楚
            report["coverage_note"] += ("本批混入了来源不同的轨迹 "
                                        f"({', '.join(sources)}): 合成轨迹与真实轨迹不得同批取中位数, "
                                        "请按来源分子目录分别跑批。")
    if missed_selftest:      # 判定器自证不通过: 单独一条横幅, 不混进覆盖说明 (两者成因不同)
        report["pass"] = False
        report["selftest_note"] = (
            f"判定器自证未通过 → 本批分数不作数: metascore={mscore:.2f}, "
            f"{len(missed_selftest)}/{len(selftest)} 条已知坏轨迹未被抓住 "
            f"({', '.join(missed_selftest)})。判定器失效时, 任何得分都不构成证据。")
    # 逐维通过线门禁 (E1 §6.7): 与覆盖门禁同一道收口, 但**判的是另一件事** ——
    # 覆盖门禁问"该跑的跑了没", 逐维门禁问"跑了的是否达标"。26 条全跑、3 次重复齐、
    # 加权分 0.92, 只要 convert 维低于 1.00 就是不达标: 转换错是 §6.7 红线性质的问题,
    # 不允许被别的维的高分稀释。样本不足的维 (thin_dims) 不阻断, 但已在报告点名。
    dim_failures = report.get("dim_failures") or []
    report["threshold_required"] = bool(require_threshold)
    if require_threshold and dim_failures:
        report["blockers"] = list(report["blockers"]) + ["below_dimension_threshold"]
        report["pass"] = False
        report["threshold_note"] = (
            "逐维未达 §6.7 通过线 → 本批不放行: "
            + "; ".join(f"{item['dim']}={item['value']:.4f}<{item['line']:.2f}"
                        f"(n={item['n']})" for item in dim_failures)
            + "。加权总分达标不覆盖逐维不过线。")
    return report


def render_markdown(report: dict) -> str:
    """汇总报告的 Markdown 渲染 (人工复核面; 数字以 JSON 为准)。"""
    lines = [  # 抬头与汇总数字一次铺好, 后面只追加明细段
        "# E1 自然语言→工具调用 跑批报告",
        "",
        f"- 任务数: {report['n_tasks']}/{len(report['missing_traces']) + report['n_tasks']}"
        f" (缺轨迹: {len(report['missing_traces'])}"
        f" — {', '.join(report['missing_traces']) or '无'})",
        f"- 重复次数: 每任务期望 {report.get('expect_attempts', 1)} 次"
        f" (不足: {len(report.get('short_attempts') or [])}"
        f" — {', '.join(item['task_id'] for item in report.get('short_attempts') or []) or '无'})",
        f"- 加权总分: {report['weighted']:.4f} "
        f"(通过线 0.90 / 警戒线 0.85)",
        f"- 判定: {'PASS' if report['pass'] else 'FAIL'}"
        f"{' (WARN)' if report['warn'] and not report['pass'] else ''}",
        f"- 红线任务: {', '.join(report['red_line_tasks']) or '无'}",
        f"- 判定器自证: 反证夹具 metascore = {report.get('metascore', 0.0):.2f}"
        f" ({sum(1 for r in report.get('grader_selftest') or () if r['caught'])}/"
        f"{len(report.get('grader_selftest') or ())} 条坏轨迹被抓住)",
        "",
    ]
    if report.get("selftest_note"):     # 判定器失效横幅最靠前: 判定器不可信时, 后面的分数都无意义
        lines += [f"> **阻断**: {report['selftest_note']}", ""]
    if report.get("coverage_note"):      # 覆盖不完整的横幅必须置顶: 读者先看到"这批不放行"再看到分数
        lines += [f"> **阻断**: {report['coverage_note']}", ""]
    if report.get("threshold_note"):    # 逐维不过线的横幅与覆盖横幅同级: 两件事都要先看见
        lines += [f"> **阻断**: {report['threshold_note']}", ""]
    lines += [
        "## 六维得分",
        "",
        "| 维度 | 权重 | 得分 | 样本数 | §6.7 通过线 | 判定 |",
        "|------|------|------|--------|--------------|------|",
    ]
    for dim, weight in GRADER_WEIGHTS.items():      # 权重直接引 graders: 报告与判分同一事实源
        value = report["dims"].get(dim)  # 缺维度即 N/A 不落 0: 不适用与得零分在报告里必须能分
        n = (report.get("dim_n") or {}).get(dim)     # 样本数与得分同表: "1.00" 必须看得见是几道题撑起来的
        line = DIM_PASS_LINES.get(dim)               # 逐维通过线直接引 graders: 文档改了这里跟着改
        if value is None:
            verdict = "N/A"                          # 不适用: 既不判达标也不判不过
        elif n is not None and n < DIM_MIN_N:
            verdict = "样本不足"                      # n 太小的 1.00 不冒充达标 (clarify/reject 分母天然小)
        elif value >= line:
            verdict = "达标"
        else:
            verdict = "未达标" + ("(警戒线以下)" if value < DIM_WARN_LINES.get(dim, 0.0) else "")
        lines.append(f"| {dim} | {weight:.2f} | "
                     f"{'N/A' if value is None else f'{value:.4f}'} | "
                     f"{n if n is not None else '-'} | "
                     f"{'N/A' if line is None else f'{line:.2f}'} | {verdict} |")
    thin = report.get("thin_dims") or []            # 样本不足的维单列: 不阻断, 但"不算达标"这件事必须写出来
    if thin:
        lines += ["", "> 样本不足的维度 (n < "
                  f"{DIM_MIN_N}, 不参与阻断, 其分数不代表该能力): "
                  + ", ".join(f"{item['dim']} (n={item['n']}, {item['value']:.4f})" for item in thin)
                  + "。"]
    lines += ["", "## 红线明细", ""]
    for grade in report["task_grades"]:            # 逐任务列红线: 报告要能定位挂在哪条判据
        if grade["red_lines"]:  # 只列有红线的任务, 否则报告会被大量无红线项淹没
            lines.append(f"- {grade['task_id']}: {', '.join(grade['red_lines'])}")  # 逐任务列红线名: 复核者要能直接定位到具体判据
    if not report["red_line_tasks"]:               # 显式写"(无)"而非留空: 空白会被读成没跑
        lines.append("- (无)")  # 显式写"(无)": 留空会被读成这一节根本没渲染
    unstable = report.get("unstable_tasks") or []  # 跨重复方差超阈的任务: 结论要跟着重复次数一起读
    lines += ["", "## 稳定性 (跨重复方差)", ""]
    lines.append(f"- 不稳定任务 (方差 > 0.05): {', '.join(unstable) or '无'}")
    lines.append("")  # 节尾补空行: 后面若接来源小节, 缺它两段会粘成一段
    if report.get("provenance_note"):              # 轨迹来源小节: 合成轨迹批次的必读项
        lines += ["## 轨迹来源 (必读)", "", f"> {report['provenance_note']}", ""]
    return "\n".join(lines)


def main(argv: Optional[list] = None) -> int:
    """CLI 入口: 退出码沿用 eval_runner 约定 (0 全过 / 1 有 fail)。"""
    parser = argparse.ArgumentParser(description="E1 nl2tool runner")  # 帮助文本只写实验名: 口径不进 CLI 描述, 口径在方案文档里
    parser.add_argument("--tasks", default=str(TASKS_PATH))  # tasks 默认可注入: 离线跑批常用临时标注集验证判分
    parser.add_argument("--traces", default=str(TRACES_DIR))  # traces 同样可注入: 换轨迹目录不必改模块级常量
    parser.add_argument("--json", default="", help="JSON 报告输出路径")  # json 留空表示不落盘: 默认只打标准输出, 不污染别处
    parser.add_argument("--md", action="store_true", help="打印 Markdown 报告")  # md 是开关: 默认给机器可读摘要, 逐任务明细按需再看
    parser.add_argument("--md-out", default="", help="Markdown 报告落盘路径 (docs §8 要求的 REPORT.md 永久资产)")  # 与 --json 同形的落盘开关: 报告要入库, 打印到终端不算数
    parser.add_argument("--expect-attempts", type=int, default=DEFAULT_EXPECT_ATTEMPTS,
                        help="每任务应有重复次数 (docs §8 模型评测口径 = 3); 不足即阻断, 不缩小分母放行")  # 缺省 1 只服务金标准自证批
    parser.add_argument("--require-threshold", action="store_true",
                        help="实验门禁: 执行 §6.7 逐维通过线, 任一维不过线即阻断 (总分达标不覆盖逐维不过线)")  # 缺省关: 离线自检批不被打红, 与 E2--E5 五处闸门同款
    parser.add_argument("--primers", default="",
                        help="上下文前缀台账路径; 给了就把标注里的 <...> 占位符按上文具化后再比对 "
                             "(续接题杜撰坐标因此现形)。模型评测批应当给; 不给则占位符通配, "
                             "报告会点名该批未具化")  # 缺省空 = 不注入: 金标准自证批不需要上文
    args = parser.parse_args(argv)   # argv 缺省走 sys.argv[1:], 故 main() 可被单测直调
    report = run(Path(args.tasks), Path(args.traces),
                 expect_attempts=args.expect_attempts,
                 require_threshold=args.require_threshold,
                 primers_path=Path(args.primers) if args.primers else None)   # 显式传路径与重复数: CLI 覆盖不落到模块级常量
    if args.json:  # 未给 json 就不落盘: 跑批默认无副作用
        out = Path(args.json)  # 输出路径由命令行决定, 不写死到某个临时层级
        out.parent.mkdir(parents=True, exist_ok=True)   # 目录自建: 报告落到 temp/ 新层级也跑得动
        out.write_text(  # 显式 UTF-8 且不转义: 中文说明在 JSON 里要能直接读
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.md_out:                # 落盘版: 与 --json 同样显式给路径, 不猜默认落点
        md_path = Path(args.md_out)  # 报告是永久资产, 路径由调用方 (Makefile) 指定
        md_path.parent.mkdir(parents=True, exist_ok=True)   # 目录自建: 首次生成 REPORT.md 时父目录可能还不存在
        md_path.write_text(render_markdown(report) + "\n", encoding="utf-8", newline="\n")  # newline="\n": 跨平台不写成 CRLF
    if args.md:                     # --md 给人看, 否则只打机器可读摘要 (省掉逐任务明细)
        print(render_markdown(report))  # Markdown 面向人工复核, 与 JSON 同一份数据两种呈现
    else:
        print(json.dumps({k: v for k, v in report.items() if k != "task_grades"},  # 默认摘要剔掉逐任务明细: 终端保持可读, 完整证据走 json
                         ensure_ascii=False, indent=2))
    if report.get("provenance_note"):    # 免责声明同时走 stderr: Markdown 被重定向时不丢
        print(f"[provenance] {report['provenance_note']}", file=sys.stderr)
    return 0 if report["pass"] else 1   # 退出码即门禁: eval_runner 靠它判 SUCCESS/FAIL


if __name__ == "__main__":
    raise SystemExit(main())
