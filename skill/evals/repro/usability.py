# -*- coding: utf-8 -*-
"""evals.repro.usability — E6 用户可用性 U1..U7 (客观可机读为主, 主观声明效力不足)。

能力边界: 评"终端用户拿到结果能不能直接用" — U1..U6 客观机读 (从 trace
与答案信封取证), U7 主观 5 分制只作趋势参考 (本仓无真实用户池, 评阅人
极可能 1–2 名专家代理 → 不得用于门禁, 文档 §7.2/§7.3)。
边界: 只判"可不可用"不判"对不对不对" (对错归 E1/E2/E3)。

白盒锚点: docs/eval-E6-reproducibility.md §7 (U1..U7 判据与阈值);
contracts/error-codes.contract.yaml (U2 稳定错误码的登记面)。

职责: 从 trace 事件与答案信封算出 E6 的七项可用性指标 U1..U7, 回答
  "终端用户拿到这个结果能不能直接用" —— 只判可用性, 不判对错。
所属实验: E6 可复现与效率 (32 任务 + R0 路实跑); 判据与阈值真值是
  docs/eval-E6-reproducibility.md §7.1/§7.2/§7.3, U3 与 E1 §6.5 同口径,
  U2 的稳定错误码登记面是 contracts/error-codes.contract.yaml。
对外接口: summarize_usability(runs) 一次性给出 U1..U7; 另有七个可单测
  的分项 u1_first_usable / u2_error_operability / u3_clarify_quality /
  u4_self_explaining / u5_step_ratio / u6_honest_degradation /
  u7_cognitive_load, 以及 theoretical_min_steps 与 _load_stable_codes。
依赖与数据流: 输入 = 各次运行的 events (clarification / final_answer)、
  outcome / answer_text / tool_calls / degraded / u7_ratings; 产物 =
  纯字典, 汇入 evals/repro/run_e6.py 的报告, 自身不落盘。
关键契约与不变量: 纯离线统计, 零请求零外联; 同一组 runs 重复统计必须
  得到逐位相同的结果; 零跨实验 import —— 只经 paths 兄弟导入拿仓根来读
  契约文件, 不 import evals/ 下任何其它实验, 跨实验等价性由
  evals/equivalence/ 的断言守护。
陷阱与边界: U2/U6 是硬门槛 (U6 要求 100%), 遇到"没有可判的样本"一律
  按满分返回并同时给 n=0 —— 门禁口径下"没测到"不等于"没过", 但报告
  必须把 n=0 显式写出来, 否则等于用满分掩盖了没跑。U7 永远不进门禁:
  本仓无真实用户池, 1–2 名专家代理给出的 5 分制不具统计效力, 只作趋势。
  U5 的分母是**工具步数**而不是 EF1 的请求数 (D-8 修复), 两个口径混用
  会让同一个 run 在效率表和可用性表里给出互相矛盾的结论。
"""
from __future__ import annotations

# 本地: 错误码登记面 (U2 三要素之一: 稳定错误码; paths 是 evals/ 兄弟裸导入)
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # 把 evals/ 挂上, 好按路径读契约而不 import 别的实验
from paths import SKILL_DIR  # noqa: E402

# 三张判据表: 澄清维度白名单 / 稳定错误码 / 诚实降级标记 (U2·U3·U6 共用)
CLARIFY_DIMS = ("coordinates", "catalog", "radius", "band", "time_baseline", "semantics")  # 与 E1 §6.5 同口径: 维度白名单
STABLE_ERROR_CODES = frozenset({  # U2 要素一: 契约登记的稳定错误码底清单
    "E_INVALID_INPUT", "E_SOFT_404", "E_NAME_UNRESOLVED", "E_NO_SQLID", "E_BACKEND",
})
HONEST_MARKERS = ("not_computable", "not_configured", "无法计算", "未配置")  # U6 判定词表: 对齐 honesty_stance


def _load_stable_codes() -> set:
    """从契约文件读错误码登记项 (读失败退回内置清单 — 契约是权威)。

    作用: 取 U2 三要素之一的"稳定错误码"集合。关键参数: 无。
    Returns: 错误码字符串集合。抛什么: 文件缺失或 YAML 非法都不抛,
    退回内置清单 —— 判定要继续, 但报告侧必须知道这是降级来源。
    """
    path = SKILL_DIR / "contracts" / "error-codes.contract.yaml"  # 按路径读, 不 import: 契约是纯数据
    if not path.is_file():  # 缺文件是降级而非失败: 判定要继续, 但来源要报得出
        return set(STABLE_ERROR_CODES)
    # 本地: 可用性判据的协作者 (效率口径与错误码表)
    import yaml

    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return set(STABLE_ERROR_CODES)
    # 以内置清单为底再叠加契约里出现的码: 内置清单保证集合非空可判,
    # 契约保证"登记了但内置漏写"的码也能被认出来
    codes = set(STABLE_ERROR_CODES)                                                         # 以内置清单打底: 集合必须非空可判, 契约只是补登记遗漏
    # 对整份文本做子串判定而不是解析出码表: 契约的登记面是一张人读表,
    # 结构不固定, 逐个键取值反而容易因格式微调而漏判
    text = str(data)                                                               # 整份文本做子串判定: 契约的登记面是人读表, 结构不固定, 逐键取值易漏判
    for code in STABLE_ERROR_CODES:                                                  # 只在内置清单里扫: 契约里的码已被上面收进 codes, 不必再扫一遍
        if code in text:                                                                  # 子串命中即认: 人读表里出现就当已登记, 不去解析它在哪一节
            codes.add(code)                                                                # 命中即加: 集合是内置与契约的并集, 去重由 set 承担
    return codes


def u1_first_usable(runs: list[dict]) -> dict:
    """U1 首次可用率 (无澄清回合且 success 的 run 占比; 阈值 ≥0.80)。

    作用: 判"用户是不是一问就拿到能用的结果"。关键参数 runs 是各次运行
    记录。Returns: {"u1": 比例}。抛什么: 不抛。
    """
    if not runs:  # 空表给 0.0: 缺测不是满分 (U1 门禁 ≥0.80)
        return {"u1": 0.0}
    # 两个条件缺一不可: 成功但问了三轮才成功, 对首次可用没有意义 ——
    # U1 量的是"首轮交互成本", 不是最终成功率
    usable = sum(                                                                      # 两个条件与在一起: 成功但问了三轮才成功, 对「首次可用」没有意义
        1 for run in runs                                                             # 分母是全部 run: 失败也要拉低首次可用率, 否则指标退化成成功率
        if not any(e.get("type") == "clarification" for e in run.get("events") or ())
        and (run.get("outcome") == "success")
    )
    return {"u1": usable / len(runs)}  # 分母是全部 run: 失败也要拉低首次可用率


def u2_error_operability(runs: list[dict]) -> dict:
    """U2 错误可操作性三要素齐全率 (稳定错误码 + 人话原因 + 下一步动作; 硬门槛)。

    作用: 判失败时用户能不能自己解决问题。关键参数 runs 是各次运行记录。
    Returns: {"u2", "failed_runs"}。抛什么: 不抛。
    """
    stable = _load_stable_codes()  # 要素一的取值处: 来自契约文件, 不是硬编码
    # 只在失败的 run 上判: 成功 run 的答案里当然没有错误码, 混进来会把
    # U2 压到接近 0, 指标就变成了"成功率"的重复
    failed = [run for run in runs if run.get("outcome") == "fail"]
    if not failed:  # 无失败样本按满分并报 n=0: 门禁口径下"没测到"≠"没过"
        return {"u2": 1.0, "failed_runs": 0}
    complete = 0                                                                                 # 分子只数三要素齐全的: 缺任一项用户都接不下去
    for run in failed:                                                       # 只在失败 run 上判: 成功 run 的答案里本就没有错误码, 混进来会压到接近 0
        answer = str(run.get("answer_text") or "")
        # 三要素全靠关键词取证: 没有结构化字段可依赖, 只能从答案文本里
        # 找痕迹 —— 这也是 U2 只能机读判定、不能当主观项的原因
        has_code = any(code in answer for code in stable)  # 要素一: 出现任一登记错误码
        has_reason = any(w in answer for w in ("原因", "因为", "failed", "error", "错误"))
        has_next = any(w in answer for w in ("建议", "下一步", "请", "try", "next"))  # 要素三
        # 三者同时成立才算齐全: 缺任何一项用户都接不下去
        complete += 1 if (has_code and has_reason and has_next) else 0               # 三者同时成立才累加: 求交而非求和, 避免「码对了但没说下一步」被算过
    return {"u2": complete / len(failed), "failed_runs": len(failed)}  # 分母是失败 run 数


def u3_clarify_quality(runs: list[dict]) -> dict:
    """U3 澄清质量 (点明缺失维度 + 给可选项; 只说"能具体点吗"记 0)。

    作用: 判系统反问时有没有给出可执行的选项。关键参数 runs 是各次运行
    记录。Returns: {"u3", "clarified_runs"}。抛什么: 不抛。
    """
    clarified = [run for run in runs  # 分母只取发生过澄清的 run: 没被反问过的无从判质量
                 if any(e.get("type") == "clarification" for e in run.get("events") or ())]
    if not clarified:                                                                        # 无澄清样本按满分: 那是这项没被触发, 不是澄清质量差
        # 没有澄清回合不是"澄清质量差", 而是这项没被触发; 按满分记并给
        # clarified_runs=0, 报告必须照实写出这个 0
        return {"u3": 1.0, "clarified_runs": 0}
    good = 0                                                                           # 分子跨事件累加: 一次 run 里多轮澄清, 每一轮都要单独判质量
    for run in clarified:                                                                      # 逐事件扫而非只看最后一条: 中间轮次的空转也要计入
        for event in run["events"]:
            if event.get("type") != "clarification":
                continue
            payload = event.get("payload") or {}
            dims = set(payload.get("missing_dims") or ())  # 转 set: 只看与白名单的交集, 不看顺序
            options = payload.get("options") or []
            # 两个条件同时成立才算好澄清: 点名的维度要落在 CLARIFY_DIMS
            # 白名单里 (自造维度名用户听不懂), 且选项至少 2 个 —— 只反问
            # "能具体点吗"而不给选项, 用户仍然不知道该答什么
            if dims & set(CLARIFY_DIMS) and len(options) >= 2:                              # 两个条件同时成立: 维度名要在白名单里, 且选项至少两个
                good += 1                                                             # 累加而非置位: 同一 run 的多轮澄清各自计数, 报告要看得见轮次
    return {"u3": good / len(clarified), "clarified_runs": len(clarified)}


def u4_self_explaining(runs: list[dict]) -> dict:
    """U4 答案自解释性 (单位量纲 / 数据版本或快照 id / stable_uri / content_trust)。

    作用: 判答案能否自证出处。关键参数 runs 是各次运行记录。
    Returns: {"u4": 四要素齐全比例}。抛什么: 不抛。
    """
    if not runs:                                                                              # 空表给 0.0: 缺测不是满分, 与 U1 同一口径
        return {"u4": 0.0}
    complete = 0  # 累加"齐全的要素个数", 不是"齐全的 run 数"
    for run in runs:                                                                 # 逐 run 判四要素: 分子是齐全的要素个数, 不是齐全的 run 数
        answer = str(run.get("answer_text") or "")
        entities = set()                                                      # 实体集合每个 run 重建: 跨 run 串味会把上一个 run 的出处算成这一个的
        for event in run.get("events") or ():
            if event.get("type") == "final_answer":
                # 从结论卡取实体而不是从答案文本里抓: 实体是结构化字段,
                # 文本抓取会把散落在正文里的半个 URI 误当成完整出处
                card = (event.get("payload") or {}).get("conclusion_card") or {}
                entities = set(card.get("key_entities") or ())  # 赋值非并集: 末条 final_answer 说了算
        # 四要素各判一次, 求和而非求交: 报告要的是"缺了哪一项", 合成一个
        # 布尔量就永远说不清缺什么
        has_unit = any(w in answer for w in ("角秒", "度", "mag", "星等", "单位"))  # 要素一
        # 快照 id 可以出现在正文, 也可以只以指纹形式进实体表 —— 两条路
        # 都认, 免得只走实体的正确答案被判缺项
        has_version = any(w in answer for w in ("快照", "snapshot", "数据版本", "指纹")) or \
            any("sha256" in e or "bestfp" in e for e in entities)
        has_uri = any("best://" in e or "stable_uri" in e for e in entities)
        has_trust = "untrusted" in answer or any("untrusted" in e for e in entities)
        complete += sum((has_unit, has_version, has_uri, has_trust))  # 缺几项要能被数出来
    return {"u4": complete / (len(runs) * 4)}  # 分母 ×4: 报的是"要素齐全率"而非"run 齐全率"


def theoretical_min_steps(calls: list[dict]) -> int:
    """U5 口径的理论最小**工具步数** (与 EF 的请求数口径分开, D-8 修复)。

    文档 §7.1: U5 = 实际工具步数 ÷ 理论最小步数。锥搜/count/fetch_page 各
    算 1 步 (一次工具调用即一步); list_catalogs/describe_catalog 是零请求
    元数据工具, 不占步数预算。混入实查才会超 1.0 — 阈值 ≤1.3 因此有分辨力。
    """
    return sum(1 for call in calls
               if call.get("tool") in ("cone_search", "count", "fetch_page",
                                       "crossmatch_batch"))


def u5_step_ratio(runs: list[dict]) -> dict:
    """U5 步数比 (实际工具步数 ÷ 理论最小步数; 阈值 ≤ 1.3)。

    作用: 判用户为拿到答案要付多少交互成本。关键参数 runs 是各次运行
    记录。Returns: {"u5": 最差比值 | None, "measured_runs": N, "per_run": 逐 run 比值}。
    抛什么: 不抛。

    2026-10-07 修正「真空满分」(审计编号 D3): 原实现收尾是
    ``max(ratios) if ratios else 1.0`` —— 比值表为空时**直接记满分**。而
    :func:`theoretical_min_steps` 只认四个工具名, 于是只要所有 run 的工具都落在
    那四个之外 (例如只用 list_catalogs 这类零请求元数据工具, 或将来新增任何工具),
    ratios 就空, u5 拿到 1.0, 阈值 ≤1.3 判成「用户交互成本完美」。**测量失效被读成了
    最好的用户体验**, 而 per_run=[] 这个本该暴露问题的字段一直躺在返回值里没人看。

    与 :func:`u1_answerability` 的空表口径对齐: 缺测**不得**记满分。现在空比值表
    返回 ``u5=None`` 并附 ``measured_runs=0``, 由上层判「不可用」而不是当满分 ——
    「无从判定要显式标记, 不要回落到最优值」是这一族的共同修法 (D3/D4/D5/D7 同源)。
    """
    if not runs:                                                                               # 空表给 0.0: 与 U1 同口径, 缺测不算满分
        return {"u5": 0.0}
    ratios = []                                                                           # 逐 run 比值先攒: 硬门槛取最差值, 中间量要能逐条披露
    for run in runs:                                                                       # 逐 run 遍历: 分母是该做哪些步, 分子是实际走了几步
        calls = run.get("tool_calls") or []
        theoretical = theoretical_min_steps(calls)                         # 理论步数按工具表累加: 与 EF1 的请求数口径刻意不同, 混用会让 U5 恒大于 EF1
        # 分母是"该做哪些"、分子是"实际做了多少", 两者口径都是工具步数,
        # 刻意不用 EF1 的请求数 (D-8): 两阶段查询的 cone_search 花 2 次
        # 请求却只算 1 步, 混用会让 U5 恒大于 EF1
        actual = len(calls)                                                                # 实际步数按调用条数: 一条两阶段查询算一步, 不按请求数算
        if theoretical > 0:                                                 # 理论步数为 0 时分两种情况: 实际也为 0 才是理想形态, 否则这条 run 不进比值
            ratios.append(actual / theoretical)                                    # 正常 run 收比值: 分母不为 0 才可比, 为 0 的情形在下一支处理
        elif actual == 0:
            # 理论 0 步且实际 0 步 = 一步没花, 是最理想形态, 记 1.0
            ratios.append(1.0)                                                   # 零步零耗记 1.0: 一步没花是最理想形态, 记 0.0 会被读成「完全没动」
    # 取最差值而非均值: 阈值 ≤1.3 是硬门槛, 一次绕远路就足以让整批
    # 不可用, 均值会把那条最差的 run 稀释到看不见
    if not ratios:  # 比值表空 = 没有一条 run 的工具被 :func:`theoretical_min_steps` 认出来
        # 这里必须显式返回 None 而不是 1.0: 回落到满分等于把「量不出来」说成「完美」。
    # measured_runs 一并给出, 让调用方不必靠 per_run 是否为空反推。
        return {"u5": None, "measured_runs": 0, "per_run": []}
    return {"u5": max(ratios), "measured_runs": len(ratios), "per_run": ratios}  # 取最差值: 硬门槛不容均值稀释


def u6_honest_degradation(runs: list[dict]) -> dict:
    """U6 诚实降级率 (做不到时显式标注而非编造; 硬门槛 = 100%)。

    作用: 判做不到时有没有明说。关键参数 runs 是各次运行记录。
    Returns: {"u6", "degraded_runs"}。抛什么: 不抛。
    """
    # 先筛出真正发生降级的 run: 正常完成的答案里本来就不该有降级标记,
    # 把它们当分母会让 U6 变成"正常完成率"的同义词
    degraded = [run for run in runs if run.get("degraded") is True]
    if not degraded:  # 无降级样本按满分并报 n=0: U6 是硬门槛, 但没测不等于没过
        return {"u6": 1.0, "degraded_runs": 0}
    # 只认显式 True: 字段缺失的 run 可能是"没降级"也可能是"没记录",
    # 混进来会让分母含义不明
    honest = sum(                                                                            # 只认显式降级标记: 正常完成的答案里本就不该有降级字样
        1 for run in degraded                                                             # 分子只数答案里出现诚实标记的: 降了但没说, 用户仍会被误导
        if any(m in str(run.get("answer_text") or "") for m in HONEST_MARKERS)
    )
    return {"u6": honest / len(degraded), "degraded_runs": len(degraded)}  # 分母是真正降级的 run 数


def u7_cognitive_load(scores: list[float]) -> dict:
    """U7 认知负荷 (主观 5 分制; 只作趋势参考, 不进门禁 — 文档 §7.2)。

    作用: 汇总主观打分。关键参数 scores 是各 run 收集的评分。
    Returns: {"u7", "n_raters", "note"}; 无数据时 u7 为 None。
    抛什么: 不抛。
    """
    if not scores:  # 无评分给 None 而非 0.0: 0 会被读成"评阅人打了最低分"
        return {"u7": None, "n_raters": 0, "note": "无评阅数据; 效力不足"}
    return {"u7": sum(scores) / len(scores), "n_raters": len(scores),  # 效应极弱: 只能看趋势
            "note": "主观分, 不得用于门禁; 评阅人 <3 名时效力不足"}


def summarize_usability(runs: list[dict]) -> dict:
    """U1..U7 汇总 (U7 不进分; 报告需写评阅人数)。

    作用: 一次调用给出全部七项。关键参数 runs 是各次运行记录。
    Returns: 七项合并的字典。抛什么: 不抛, 任一分项都不抛。
    """
    # U7 是主观 5 分制 — 取各 run 携带的 u7_ratings (R0 无评阅人 → 空表,
    # u7_cognitive_load 返回 None + 效力不足注记, 不进门禁)
    u7_scores = [s for run in runs for s in (run.get("u7_ratings") or [])]
    # 键展开而非手工拼: u7 的 u7/n_raters/note 三个键必须原样透出, 手工
    # 列举时最容易漏掉 note, 报告就会把主观分当客观项展示
    return {
        **u1_first_usable(runs),
        **u2_error_operability(runs),
        **u3_clarify_quality(runs),
        **u4_self_explaining(runs),
        **u5_step_ratio(runs),
        **u6_honest_degradation(runs),
        **u7_cognitive_load(u7_scores),
    }
