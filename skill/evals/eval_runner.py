#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""eval_runner.py — astro-best 质量评审执行器 (Phase 5 重建, SSOT 闭环)。

能力边界: 跑行为评测 (cases/) + 内容质量审计 (audit/ 六审计器 + docstring 维度),
产出加权评分与阻断判定。``make eval`` / ``make check`` / ``make all`` 消费其退出码。

调用契约 (SA-P3-7): 本包用**兄弟裸导入** (``from case_executor import ...`` /
``from paths import ...`` / ``from probes import ...``) — 模块名不带包前缀
(``evals/case_runner.py`` 只是 P0 命名整改留下的 [deprecated shim], 不在导入面上),
因此 ``import evals.eval_runner`` 从仓根不可用, 必须以脚本方式调用:
``python evals/eval_runner.py`` (Makefile 的 eval 目标即此形态)。测试侧
(test/unit/meta/test_eval_runner_dimensions.py 等) 经 sys.path 注入 evals/
后 import, 是唯一的非脚本入口。新代码请保持这一约定, 不要改成包内相对导入
(那会让 Makefile 与测试两条路径同时断)。

Phase 5 重建纪律 (承 CODE-QUALITY-FIX-LIST §11 EVAL-01~10 教训):
  1. 无 fail-open: 目标缺失/损坏/未知 id 一律 FAIL, 绝不再现"文件存在即过";
  2. -O 安全: 校验逻辑用显式返回/条件, 不用 assert (python -O 不得退化);
  3. 输入必喂: 行为用例必须消费 given 夹具并校验输出, 未知场景 id 报错;
  4. 权重代码校验: 权重和 != 1.0 启动即败; pass_score 与 WARN 线保持差距;
  5. 反证夹具: 每个审计器附 broken 坏样本, 坏样本不过 = 审计器无效 (总体 FAIL);
  6. docstring 维度: 公开函数无 docstring 即计入质量赤字 (Phase 7 验收锚)。
"""
from __future__ import annotations

# 标准库组:
#   argparse   —— --mode (behavior/audit/all) 与 --json 两个开关
#   importlib  —— 按用例声明动态 import 真实生产模块 (EVAL-10: 拒绝纯 hasattr 假校验)
#   json       —— 契约/YAML 内容转文本做关键字判定 + JSON 报告输出
#   re         —— 从 derived_from 字符串里抽取 'name'/'module' 字段
#   sys        —— sys.path 注入 (使 `import src.*` 在任意 cwd 可用) 与 stderr 报错
#   pathlib    —— 定位 evals/ 下的 rubric/scenarios/cases 三个输入
#   typing     —— 汇总字典的宽松类型标注
#   unittest.mock —— 探针离线化的唯一手段: stub 掉真实 HTTP / 真实下载
import argparse
import json
import sys
from typing import Any

# 第三方组: PyYAML 读取评分量规 / 场景表 / 用例夹具 (本文件唯一第三方依赖)
from case_executor import run_cases_eval  # noqa: E402

# 本地组: 探针层 (行为场景表的每条场景各一个真实交互执行体; 场景数以
# evals/test-scenarios.yaml 的 evaluations 条数为准, 2026-10-06 移除 MCP 场景
# 后为 24 条 —— 此处不写死数字, 场景增删时本注释无需跟改) 与场景注册表 ——
# 整层拆至 evals/probes.py (docs/architecture/file-size-budget.md §3.1 登记的拆分)。
# 探针自行延迟导入被测的 src.*, 本文件只消费 SCENARIO_PROBES 注册表。
# 本地组: 中立载体 (路径/YAML) / 用例执行层 / 探针层与场景注册表 ——
# 三者分别拆自本文件 (docs/architecture/file-size-budget.md §3.1)
from paths import EVALS_DIR, SKILL_DIR, SRC_DIR, load_yaml_file  # noqa: E402
from probes import (  # noqa: E402
    _exec_agent_tools_probe,  # Agent 工具箱场景: 探针走离线注册簿, 不触网
    _exec_background_download_probe,  # 后台下载: 作业提交与完成状态都要能观测
    _exec_batch_region_download_probe,  # 批量区域下载: 多任务编排与产物落盘都要验
    _exec_column_constraint_probe,  # 列约束查询: 列名与约束条件要能正确下发
    _exec_cone_search_probe,  # 锥形检索: 表单构造与行集解析是主干路径
    _exec_connection_info_probe,  # 连接信息: 只探信息组装, HTTP 已被替身挡掉
    _exec_coordinate_lookup_probe,  # 坐标查源: 中心点与半径的口径必须一致
    _exec_crossmatch_probe,  # 交叉匹配: 角度分离数学与配对阈值
    _exec_custom_adql_probe,  # 自定义 ADQL: 计划解析与过滤条件都要落地
    _exec_download_progress_visible_probe,  # 进度可见: 进度要能从日志侧查到, 不只在内存里
    _exec_download_resume_probe,  # 续传: 重复调用不得新建第二个作业
    _exec_hook_intercept_ask_probe,  # hook 拦截: 坏和要进阻断并挂一条待决策项
    _exec_list_catalogs_probe,  # 星表清单: 离线注册簿与请求计数都要验
    _exec_multiband_photometry_probe,  # 多波段测光: 波段到列的映射不能错
    _exec_name_resolve_probe,  # 名称解析: 哨兵坐标必须被当失败而不是当坐标
    _exec_parallel_download_probe,  # 并行下载: 并发度与产物完整性都要核
    _exec_precise_download_probe,  # 精准下载: 空结果必须拦下, 不许静默产空文件
    _exec_proximity_batch_probe,  # 就近批量: 每输入行只回最近邻, 返回顺序不能乱
    _exec_quality_filtering_probe,  # 质量过滤: 过滤条件要真的落到结果行上
    _exec_source_lookup_probe,  # 按源查: 主键回连列要能对上
    _exec_tap_adql_probe,  # TAP 查询: ADQL 计划与执行两段都要验
    _exec_tap_service_probe,  # TAP 服务元数据: 表与列的描述要能取到
    _exec_task_log_probe,  # 任务日志: 事件要落盘可查, 不只在内存里
)

# 把 skill 根注入 sys.path: 探针要 `from src.xxx import ...` 真实执行生产代码
if str(SRC_DIR) not in sys.path:                # 幂等守卫: 重复 insert 会让解析顺序随调用次数漂移
    sys.path.insert(0, str(SRC_DIR))             # 插到最前: 探针的 `from src.*` 必须命中本仓实现

# 维度 WARN 线的**兜底默认值**: 真值在 evals/scoring-rubric.yaml 的 warn_line,
# evaluate_rubric 优先读量规 (N1-02: 此前代码硬编码 0.85 而量规里的 warn_line
# 无人读, 改量规的人得到"改了没用"的假象)。这里只留缺字段时的兜底。
# 语义: pass_score 必须高于它 (EVAL-09: 兜底分不得等于 WARN 线, 否则"刚过 WARN"
# 会被误判成合格, 门禁失去分辨力)。再低则"勉强可用"与"不可用"无法分辨。
WARN_LINE = 0.85

# 不扣分的严重度白名单 (N1-04): **封闭集合**, 未列出的严重度一律按扣分处理。
# 此前写死 `severity != "INFO"`, 语义上把"某个字符串"当成豁免开关; 改成显式
# 白名单后, 新增严重度必须显式登记才豁免, 拼错/漏写的严重度 fail-closed 扣分。
# 注意: 白名单只管"扣不扣分", 不改判据语义 —— INFO 仍不扣分, 豁免量改为
# 经 waived_findings 字段对调用方可见 (静默豁免与"没有 finding"长得一样)。
NON_DEDUCTING_SEVERITIES = frozenset({"INFO"})   # 封闭集合: 豁免必须登记, 不得靠字符串相等蒙混


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------





# ---------------------------------------------------------------------------
# 行为评测: 场景 (test-scenarios.yaml)
# ---------------------------------------------------------------------------























# --- 下载能力场景探针 (后台/并行/续传/hook/进度; 全离线确定性) ------















# --- 精准下载 + 任务日志探针 (全离线确定性) ------------------------





# --- P0/P1 修复 + TAP/工具面场景探针 (全离线确定性) ----------------

















# 场景 id -> 探针函数 的权威映射表。
# 消费方: run_scenario_evals()。test-scenarios.yaml 里出现的每个 id 都必须
# 在这里有登记, 未登记 id 一律显式 FAIL (EVAL-04: 杜绝"文件存在即过")。
SCENARIO_PROBES = {                                                                   # 场景 id 到探针的权威映射: 未登记 id 一律显式失败, 不放行
    "cone_search": _exec_cone_search_probe,
    "crossmatch": _exec_crossmatch_probe,
    # crossmatch_best_gaia 与 crossmatch 复用同一探针: 两者测的是同一套
    # 角度分离数学, 拆两份只会让同一处回归红两遍、报告翻倍
    "crossmatch_best_gaia": _exec_crossmatch_probe,   # 复用同一探针, 不复制实现
    "quality_filtering": _exec_quality_filtering_probe,
    "column_constraint": _exec_column_constraint_probe,
    "list_catalogs": _exec_list_catalogs_probe,
    "multiband_photometry": _exec_multiband_photometry_probe,
    "source_lookup": _exec_source_lookup_probe,
    "coordinate_lookup": _exec_coordinate_lookup_probe,
    "custom_adql": _exec_custom_adql_probe,
    "batch_region_download": _exec_batch_region_download_probe,
    "connection_info": _exec_connection_info_probe,  # HTTP 被 Mock 掉: 只探连接信息组装, 不触网
    "background_download": _exec_background_download_probe,
    "parallel_download": _exec_parallel_download_probe,
    "download_resume": _exec_download_resume_probe,  # resume 幂等: 重复调用不得新建第二个作业
    "hook_intercept_ask": _exec_hook_intercept_ask_probe,  # 坏和进 blocked 并挂一条待用户决策
    "download_progress_visible": _exec_download_progress_visible_probe,
    "precise_download": _exec_precise_download_probe,  # 空结果必须拦下, 不允许静默产空 CSV
    "task_log": _exec_task_log_probe,
    "name_resolve": _exec_name_resolve_probe,
    "proximity_batch": _exec_proximity_batch_probe,
    "tap_adql": _exec_tap_adql_probe,
    "tap_service": _exec_tap_service_probe,
    "agent_tools": _exec_agent_tools_probe,
}


def run_scenario_evals(scenarios_data: dict[str, Any]) -> dict[str, Any]:
    """执行场景评测: 每个场景必须映射到真实探针 (未知 id -> FAIL, 不再 generic 放行)。

    Args:
        scenarios_data: test-scenarios.yaml 解析结果 (取 ``evaluations`` 列表)。

    Returns:
        total/passed/rate/details/valid 五段汇总; 场景文件为空时 valid=False。
    """
    scenarios = scenarios_data.get("evaluations", [])   # 场景表缺失时降级成空列表, 由下面 valid 拦下
    if not scenarios:                                                                   # 空场景表是输入缺失: 记 valid=False 而不是"全过"
        # 空场景表 = 输入缺失, 记 valid=False 让上层知道"没测"而不是"全过"
        return {"total": 0, "passed": 0, "rate": 0.0,
                "details": [{"id": "-", "passed": False, "note": "scenarios 文件为空"}],
                "valid": False}

    results: list[dict[str, Any]] = []                 # 逐场景结果: 报告要能定位到单个 id
    for sc in scenarios:                                                                           # 逐场景执行: 单个探针抛异常不中断整轮评测
        sid = sc.get("id", "unknown")                  # 缺 id 也算未知 id, 走显式失败那一路
        probe = SCENARIO_PROBES.get(sid)               # 查注册表而非 hasattr: 拒绝"存在即过"
        if probe is None:                                                                    # 查注册表而非 hasattr: 杜绝"文件里有就算过"
            # EVAL-04: 未知场景 id 显式失败 —— 不得回退成一句泛化的"已验证"
            results.append({"id": sid, "passed": False,
                            "note": f"unknown scenario id (no registered probe): {sid}"})
            continue
        try:
            ok, note = probe()                                                                 # 真调探针: 通过与否由探针实测决定, 不在此处推断
        except Exception as exc:  # noqa: BLE001
            # 探针自身抛异常也算失败, 且把异常原文带进报告 (不吞栈)
            ok, note = False, f"probe raised: {exc!r}"  # repr 而非 str: 连类型一起留证
        results.append({"id": sid, "passed": ok, "note": note})

    pass_count = sum(1 for r in results if r["passed"])  # 分母含失败项, 通过率不会被稀释
    return {
        "total": len(results),
        "passed": pass_count,
        "rate": pass_count / len(results) if results else 0.0,  # 无样本记 0.0, 不记 1.0
        "details": results,
        "valid": True,
    }


# ---------------------------------------------------------------------------
# 行为评测: 用例 (cases/*.yaml)
# ---------------------------------------------------------------------------











# ---------------------------------------------------------------------------
# 内容质量审计 (audit/ 六审计器 + docstring 维度 + 反证夹具)
# ---------------------------------------------------------------------------

def run_audit() -> dict[str, Any]:
    """运行审计器注册表中的全部审计器; 每个审计器的 broken 样本必须被拒绝。

    D4 修复: 旧 docstring 声称本函数连带执行 docstring 覆盖维度, 实际该
    维度由 ``main()`` 单独调 ``run_docstring_dimension()`` 完成, 本函数只跑审计器
    注册表 (``audit.auditor_registry()``)。文档范围超出实际会让复核者误以为少跑
    一个维度也不会被发现, 故按实际执行范围改写。

    反证机制是关键: 光跑正向检查只能证明"现在没问题", 证明不了"检查还有效"。
    每个审计器额外交一份故意构造的坏样本, 若它连坏样本都放过去, 说明该检查
    已经退化 (正则写错/条件恒真), 此时记 CRITICAL 并让总体 FAIL ——
    一个测不出问题的检查比没有检查更危险。

    Returns:
        auditors/findings/n_auditors/n_failed_auditors/passed 五段汇总。
        ``measured`` 标记不在本函数返回 —— 它由 :func:`main` 事后注入,
        供 evaluate_rubric 判定该维度是否真的执行过。
    """
    # 本地 audit 包 (evals/audit): 延迟导入避免 behavior 模式也拖上审计依赖
    from audit import auditor_registry  # noqa: PLC0415

    findings: list[dict[str, Any]] = []                                                          # 逐条发现先攒起来: 反证失败也要并进同一份清单
    auditor_results: list[dict[str, Any]] = []        # 逐审计器小计, 反证失败要回写到对应下标

    for auditor in auditor_registry():                                                           # 逐审计器跑: 每个都要带自己的反证坏样本一起验
        result = auditor.run(SKILL_DIR)               # 传 SKILL_DIR: 审计目标固定在 skill 根
        auditor_results.append({                                                                # 逐审计器小计先落一条: 反证失败要能回写到它名下
            "auditor": auditor.name,
            "target": auditor.target,
            "findings": len(result.findings),
            "passed": result.passed,
        })
        for f in result.findings:                                                               # 逐发现打上审计器名: 报告里才知道是哪台机器报的
            findings.append({"auditor": auditor.name, **f.to_dict()})
        # 反证夹具: 坏样本必须被拒绝 (否则审计器无效)
        for check_id, broken in auditor.broken_samples().items():                                # 反证夹具逐条喂: 放过坏样本即说明该检查已退化
            if auditor.check_rejects(check_id, broken):   # 拒绝=检查还活着, 放行才是反证失败
                continue
            findings.append({                                                            # 反证失败记最高级别: 它比普通发现更重, 直接让总体 FAIL
                "auditor": auditor.name, "severity": "CRITICAL",
                "target": f"counter-evidence:{check_id}",
                "message": f"审计器反证失败: 坏样本通过了 {check_id} 检查 (审计器无效)",
            })
            auditor_results[-1]["passed"] = False     # 回写本审计器: 下标取的是刚 append 那条

    n_fail = sum(1 for a in auditor_results if not a["passed"])
    return {
        "auditors": auditor_results,
        "findings": findings,
        "n_auditors": len(auditor_results),
        "n_failed_auditors": n_fail,
        # 双条件: 无失败审计器 **且** 无 CRITICAL —— 后者覆盖反证失败那一路
        "passed": n_fail == 0 and not any(
            f["severity"] == "CRITICAL" for f in findings),
    }


def run_docstring_dimension() -> dict[str, Any]:
    """docstring 覆盖维度 (Phase 7 验收锚): src/ 公开函数无 docstring 记赤字。

    用 AST 静态扫描而非 import 后内省: 不执行生产代码也能统计, 且不会因
    某个模块 import 副作用中断整轮。只统计公开函数 (``_`` 开头跳过),
    包级 ``__init__.py`` 也跳过 (它通常只做再导出, 无函数可文档化)。

    Returns:
        total_public_functions/documented/coverage/missing/missing_count。
    """
    # 延迟导入: AST 只服务 docstring 覆盖维度, 不放模块级依赖面
    import ast

    total = 0                                       # 分母: 公开函数总数 (含未文档的)
    documented = 0                                                                              # 已文档化计数: 分子与总数同口径, 覆盖率才可比
    missing: list[str] = []                                                                         # 缺失清单: 报告要能点名是哪个函数没写
    # 读点: 递归扫 src/ 下全部 .py 源码 (只读, 不 import)
    for py in sorted((SKILL_DIR / "src").rglob("*.py")):  # 排序保证结果与文件系统顺序无关
        if py.name == "__init__.py" and py.parent == SKILL_DIR / "src":
            continue
        try:
            tree = ast.parse(py.read_text(encoding="utf-8"))  # 静态解析: 不执行 import 副作用
        except SyntaxError:
            # 语法错误的文件由 test/ 审计器负责报, 这里跳过不重复计数
            continue
        for node in ast.walk(tree):                                                                # 全树遍历: 嵌套在类里的方法同样算公开函数
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):                    # 同步异步同收: 两类都在 Phase 7 的验收口径内
                if node.name.startswith("_"):         # 私有函数不在 Phase 7 验收口径内
                    continue
                total += 1                                                                    # 分母先入账: 私有与未文档都算数, 覆盖率才不会虚高
                doc = ast.get_docstring(node)                                                 # 取运行时同源的 docstring, 不用正则扫文本
                # 长度 >= 10 才算"有文档": 一行 "TODO" 之类的占位不算
                if doc and len(doc.strip()) >= 10:                                               # 长度门槛挡占位: 一行 TODO 不算写了文档
                    documented += 1                                                                 # 分子与分母同口径, 两者不可各算各的
                else:
                    missing.append(f"{py.relative_to(SKILL_DIR).as_posix()}::{node.name}")
    coverage = documented / total if total else 1.0  # 无公开函数记满覆盖: 空集合不构成赤字
    return {
        "total_public_functions": total,
        "documented": documented,
        "coverage": round(coverage, 4),              # 4 位: 与其他维度同精度, 便于并列比较
        "missing": missing[:50],                     # 截断防报告膨胀, 完整计数在下一行
        "missing_count": len(missing),               # 截断后的清单不能当分母, 计数保持全量
    }


# ---------------------------------------------------------------------------
# 评分
# ---------------------------------------------------------------------------

def evaluate_rubric(
    rubric: dict[str, Any],
    scenarios_summary: dict[str, Any],
    cases_summary: dict[str, Any],
    audit_summary: dict[str, Any],
    docstring_summary: dict[str, Any],
) -> dict[str, Any]:
    """加权评分 (EVAL-09 修复: 权重和代码校验; 兜底分与 WARN 线保持差距)。

    两条硬约束在代码里校验而不是靠人 review:
      1. rubric 权重和必须等于 1.0, 不等则启动即败 (否则加权总分失去意义);
      2. ``pass_score`` 必须**高于** WARN 线, 否则"刚过 WARN"会被判合格,
         维度状态与总判定会互相矛盾。

    另有一组阻断条件: 行为探针 / 用例 / 审计任一失败, 不论加权分多高一律
    FAIL —— 少了这条阻断, 加权分就能独自决定放行, 恒定 1.0000 的假门禁正是
    这么来的。

    D1 落点: ``measured`` 语义。调用方没跑的模式 (如 ``--mode audit``
    不跑 behavior 探针, 或 ``--mode behavior`` 不跑审计) 必须把汇总标记为
    ``measured=False``; 此时行为三维与 docstring 维度记 0.0、状态报
    ``NOT_MEASURED``, 并加入阻断项 ``behavior_not_measured`` /
    ``docstring_not_measured`` / ``audit_not_measured``。未跑的模式**禁止**预置
    成 ``rate=1.0`` (audit 则预置 passed=True): 单模式运行在零证据下拿到高
    综合分就是 fail-open。

    Args:
        rubric: scoring-rubric.yaml 内容 (dimensions / pass_score)。
        scenarios_summary: 场景评测汇总 (含 measured 标记)。
        cases_summary: 用例评测汇总 (含 measured 标记)。
        audit_summary: 审计汇总 (含 measured 标记)。
        docstring_summary: docstring 覆盖汇总 (含 measured 标记)。

    Returns:
        overall_score/pass_threshold/passed/blocking/dimensions;
        权重或阈值配置非法时返回 error 且 passed=False。
    """
    dims_config = rubric.get("dimensions", {})        # 维度表是评分唯一真值, 不在代码里硬编码权重
    # WARN 线读量规 (N1-02): 此前代码硬编码 0.85, 量规里的 warn_line 无人读 ——
    # 改量规的人只得到"改了没用"的假象。缺字段才回落 WARN_LINE 兜底。
    # 提前算 (而非等到打分循环前): 下面每一条配置错误早退都要带上它, 否则
    # main() 的人读报告会在错误路径上打印 "WARN 线 None"。
    warn_line = float(rubric.get("warn_line", WARN_LINE))
    weight_sum = round(sum(float(d.get("weight", 0)) for d in dims_config.values()), 6)
    if abs(weight_sum - 1.0) > 1e-9:                 # 1e-9 吸收浮点累加误差, 不吸收真实配错
        # 权重和 != 1.0: 加权总分不再是 0~1 的量, 直接判败而不是凑一个分
        return {"error": f"rubric 权重和 != 1.0: {weight_sum}", "passed": False,
                "overall_score": 0.0, "dimensions": [], "warn_line": warn_line}

    # 维度**集合**自洽 (N1-01): 见上方 scores 建好后的同名注释。
    # 本段只留量规侧的自洽检查; 权重和校验与 WARN 线读取已在函数开头完成。

    gate_cases = [c for c in cases_summary["details"] if c.get("type") == "gate"]  # 只挑门禁类用例
    gate_rate = (sum(1 for c in gate_cases if c["passed"]) / len(gate_cases)) if gate_cases else 0.0
    case_rate = cases_summary.get("rate", 0.0)
    scenario_rate = scenarios_summary.get("rate", 0.0)
    # 不扣分的 finding 走封闭白名单 (N1-04), 豁免量单独计数上报:
    # "99 条 finding 一条不扣分"此前与"没有 finding"在报告上完全一样。
    waived_findings = [f for f in audit_summary.get("findings", [])
                       if f.get("severity") in NON_DEDUCTING_SEVERITIES]
    audit_findings = [f for f in audit_summary.get("findings", [])
                      if f.get("severity") not in NON_DEDUCTING_SEVERITIES]  # 未知严重度按扣分处理 (fail-closed)
    # 行为维度是否真的测过: --mode audit 不跑 behavior 探针, 此时 case_rate/
    # scenario_rate 是 0.0 而不是伪造的 1.0 (D1 修复)。measured=False 时相应
    # 维度必须显式标注 NOT_MEASURED 并参与阻断, 不允许"没测"伪装成"测过"。
    behavior_measured = bool(scenarios_summary.get("measured")) and bool(cases_summary.get("measured"))
    audit_measured = bool(audit_summary.get("measured"))   # 三个 measured 标记各自独立, 不可互相顶替
    docstring_measured = bool(docstring_summary.get("measured"))

    scores = {                                                                                    # 六个维度分先算齐, 供下面按量规里的名字取用
        # correctness: 行为用例通过率 + 场景通过率 (审计 findings 另行扣分)。
        # "无 findings" 不等于满分: 基线永远取真实通过率, findings 只做额外
        # 扣罚 (每条 -0.1, 下限 0), 因此不存在"恒真分支": 通过率为 0 时该项
        # 必然为 0, 0% 通过率不可能显示 PASS。
        "correctness": round(                                  # 等权各半: 两类行为证据互为对照
            (case_rate * 0.5 + scenario_rate * 0.5)                                              # 等权各半: 两类行为证据互为对照, 不该谁压谁
            * (1.0 if not audit_findings else max(0.0, 1.0 - 0.1 * len(audit_findings))),      # findings 只做额外扣罚, 不替代真实通过率
            4,                                                # 每条 finding 扣 0.1, 下限 0 不倒扣
        ),
        # gate_compliance: 门禁用例真实执行通过率
        "gate_compliance": round(gate_rate, 4),               # 不与 correctness 混算: 门禁须单列
        # determinism: 相同输入重复构建一致 + 场景通过率
        "determinism": round(scenario_rate, 4),               # 场景表是唯一反复重放的证据源
        # provenance: 契约存在且内容非空
        "provenance": 1.0 if _contracts_nonempty() else 0.0,  # 布尔项: 契约空文件不算有血缘
        # docstring_coverage: 公开函数 docstring 覆盖率 (Phase 7 锚);
        # 未跑 docstring 维度时记 0.0 并标注 NOT_MEASURED, 不预设 1.0。
        "docstring_coverage": round(docstring_summary.get("coverage", 0.0), 4) if docstring_measured else 0.0,
    }

    # 维度**集合**自洽 (N1-01): 权重和 == 1.0 只管分配, 不管"少评了哪一维"。
    # scores 是代码**能算**的维度全集, 下面循环遍历的是量规**声明**的维度;
    # 两者不一致时缺的那一维根本不进加权总分 —— 实测把 correctness 从量规里删掉
    # (权重挪给 provenance, 和仍精确 1.0), 4 条真 MAJOR findings 下门禁报
    # overall=1.0 / passed=true: 决定性维度被摘掉反而全绿。故两个方向都判配置错误。
    missing_dims = sorted(set(scores) - set(dims_config))
    if missing_dims:
        return {"error": f"rubric 缺维度 (代码可算但量规未声明): {missing_dims}", "passed": False,
                "overall_score": 0.0, "dimensions": [], "warn_line": warn_line}
    unknown_dims = sorted(set(dims_config) - set(scores))
    if unknown_dims:                                 # 反向同样 fail-closed: 量规声明了算不出的维度, 原会按 0.0 静默计分
        return {"error": f"rubric 声明了代码算不出的维度: {unknown_dims}", "passed": False,
                "overall_score": 0.0, "dimensions": [], "warn_line": warn_line}

    weighted_total = 0.0                                                                            # 累加器从零起: 走完循环应等于各维加权和
    dim_reports = []                                                                             # 逐维明细独立成表: 报告要能点名是哪一维在拖分
    for dim_name, dim_cfg in dims_config.items():   # 遍历量规而非 scores: 量规缺项已在上方判配置错误
        w = float(dim_cfg.get("weight", 0.0))
        s = float(scores.get(dim_name, 0.0))        # 集合已校验一致, 这里取到的必是真实算出的分
        weighted_total += w * s                     # 不变量: 结束后 weighted_total 等于各维加权和
        # 维度状态: 未测的维度报 NOT_MEASURED 而不是 PASS/FAIL ——
        # "没测"与"测了但没过"是两件事, 混为一谈正是 D1 的根因。
        if dim_name in ("correctness", "gate_compliance", "determinism") and not behavior_measured or dim_name == "docstring_coverage" and not docstring_measured:
            status = "NOT_MEASURED"                  # 0.0 分但不算 FAIL: 缺的是证据不是能力
        else:
            status = "PASS" if s >= 0.95 else ("WARN" if s >= warn_line else "FAIL")
        dim_reports.append({                                                            # criterion 原样带出: 判据文字与分数同表, 免得对不上
            "dimension": dim_name,
            "weight": w,
            "score": round(s, 4),
            "weighted": round(w * s, 4),
            "criterion": dim_cfg.get("criterion", ""),
            "status": status,
        })

    # WARN 维度对调用方**可观测** (N1-03): 此前 status 只进 dim_reports 供人读,
    # 汇总层没有任何布尔量表达"存在 WARN 维", 于是 passed=true + exit 0 与全绿
    # 对 CI/调用方完全等价 —— "有缺陷但放行"是静默的。
    # 刻意**不进 blocking**: WARN 不阻断是现行判据语义, 把它变成 FAIL 属改判据,
    # 与加守护是两件事。这里只补可观测面, 让"放行但有告警"能被机读。
    warn_dimensions = [d["dimension"] for d in dim_reports if d["status"] == "WARN"]

    pass_threshold = float(rubric.get("pass_score", 0.9))  # 0.9 兜底: 缺字段也不等于放行
    if pass_threshold <= warn_line:                                                           # 合格线不高于 WARN 线即配置自相矛盾, 当场判败
        # 合格线不高于 WARN 线 = 门禁自相矛盾, 配置错误即败
        return {"error": f"pass_score ({pass_threshold}) 必须高于 WARN 线 ({warn_line})",
                "passed": False, "overall_score": 0.0, "dimensions": dim_reports, "warn_line": warn_line}

    overall_score = round(weighted_total, 4)         # 先取整再比阈值: 避免 0.8999999 卡在边界外
    # 阻断性条件 (EVAL-02 精神): 行为探针/用例/审计任一失败, 不论加权分高低一律 FAIL
    # (无阻断条件就会退回"加权分独断"的假门禁)。
    # D1 的两条"没测即阻断": 行为维度或 docstring 维度未执行时, 不允许
    # 仅凭另一半证据宣布通过 —— 纯审计模式因此永远 passed=False。
    blocking = {                                                                                # 六项阻断各自成键: 报告要能逐条看是哪个模式没测
        # 以下六项任一为真即判 FAIL; 全部落到报告的 blocking 字段供机读
        "scenarios": scenarios_summary.get("rate", 0.0) < 1.0,
        "cases": cases_summary.get("rate", 0.0) < 1.0,
        "audit": not audit_summary.get("passed", True),
        "behavior_not_measured": not behavior_measured,  # 没测 != 测过
        "docstring_not_measured": not docstring_measured,  # 同上, 独立于行为维度
        # 审计维度同理: --mode behavior 不跑审计时 audit_summary.passed 仍是初始
        # 的 True, 不显式阻断就会让"没审计"伪装成"审计通过"。
        "audit_not_measured": not audit_measured,     # 补上第三条"没测即阻断"
    }
    return {
        "overall_score": overall_score,
        "pass_threshold": pass_threshold,
        # 双闸: 分数够 **且** 无阻断项; 任一不满足即 passed=False
        "passed": overall_score >= pass_threshold and not any(blocking.values()),
        "blocking": blocking,
        "dimensions": dim_reports,
        # 以下三项是**观测面**, 不参与上面任何布尔判定 (N1-03/N1-04):
        # 让"放行但有告警"与"完全干净"在机读出口上可区分。
        "warn_line": warn_line,
        "warn_dimensions": warn_dimensions,
        "waived_findings": [  # 不扣分的 finding 逐条列出: 此前它们与"不存在"在报告上无法区分
            {"severity": f.get("severity"), "auditor": f.get("auditor"),
             "target": f.get("target"), "message": f.get("message")}
            for f in waived_findings
        ],
    }


def _contracts_nonempty() -> bool:
    """provenance/envelope 契约存在且内容非空 (非仅文件存在)。

    Returns:
        两份契约都在且解析出非空内容返回 True; 任一缺失/为空返回 False。
    """
    for name in ("provenance.contract.yaml", "envelope.contract.yaml"):  # 两份缺一即无血缘
        p = SKILL_DIR / "contracts" / name
        if not p.is_file():                                                                        # 契约缺一即无血缘: 文件存在性替代不了内容
            return False
        # 读点: 契约 YAML; 空文件 (safe_load 回 None) 同样算不过
        data = load_yaml_file(p)                                                                    # 空文件解析出来是 None, 同样算不过
        if not data:                              # 空 dict 也算空: 存在性不是内容
            return False
    return True


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    """评测入口: 按 mode 跑行为/审计, 汇总打分并打印报告。

    ``make eval`` / ``make check`` / ``make all`` 都消费它的退出码,
    所以退出码语义必须严格: 0 = 达标, 1 = 未达标或输入缺失。

    Args:
        argv: 可选参数向量 (测试可注入); 缺省读 sys.argv。

    Returns:
        报告 passed 为 True 返回 0, 否则返回 1。
    """
    parser = argparse.ArgumentParser(description="astro-best 质量评审执行器 (Phase 5 重建)")
    parser.add_argument("--mode", choices=["behavior", "audit", "all"], default="all",
                        help="behavior=行为评测; audit=内容质量审计; all=两者 (默认)")
    parser.add_argument("--json", action="store_true", help="输出 JSON 格式报告")
    args = parser.parse_args(argv)                 # choices 限制非法 mode, 不靠运行期兜底

    # 三个输入文件: 量规 / 场景表 / 用例目录, 全部位于 evals/ 下
    rubric_file = EVALS_DIR / "scoring-rubric.yaml"
    scenarios_file = EVALS_DIR / "test-scenarios.yaml"  # 场景表缺失只降级, 由阻断项判 FAIL
    cases_dir = EVALS_DIR / "cases"                 # 用例目录整体交给 run_cases_eval 遍历

    # 量规缺失 = 无法打分, 直接失败 (不靠默认权重蒙一个分)
    if not rubric_file.is_file():                                                                  # 量规缺失即无法打分, 不靠默认权重蒙一个分
        print(f"[ERROR] 评分量规文件缺失: {rubric_file}", file=sys.stderr)
        return 1
    # 读点: 量规必读; 场景表允许缺失 (降级成 0 场景, 由阻断条件判 FAIL)
    rubric = load_yaml_file(rubric_file)                                                            # 量规必读: 权重与合格线都从这一份来
    scenarios_data = load_yaml_file(scenarios_file) if scenarios_file.is_file() else {}      # 场景表允许缺失: 降级成零场景, 由阻断项判 FAIL

    # 未跑的模式必须标记 measured=False 且 rate=0.0, 而不是预置 rate=1.0。
    # 预置 1.0 的后果: evaluate_rubric 会把 correctness/determinism 按满分计,
    # 纯审计模式 (--mode audit) 在零行为证据下也能报出高综合分, 且 blocking 不
    # 触发 —— fail-open。"没测"一律按 0 分并显式阻断 (见 evaluate_rubric)。
    scenarios_summary = {"total": 0, "passed": 0, "rate": 0.0, "details": [], "valid": True,
                         "measured": False}       # 零证据占位: rate=0.0 + measured=False 双标
    cases_summary = {"total": 0, "passed": 0, "rate": 0.0, "details": [], "valid": True,
                     "measured": False}           # 同上, 两份占位形状保持一致
    audit_summary = {"auditors": [], "findings": [], "passed": True, "measured": False}  # passed 初始 True
    docstring_summary = {"coverage": 0.0, "total_public_functions": 0, "missing_count": 0,
                         "measured": False}       # 缺这三个键会让 report 渲染时 KeyError

    if args.mode in ("behavior", "all"):
        scenarios_summary = run_scenario_evals(scenarios_data)  # 全离线: 探针只碰回放/stub
        scenarios_summary["measured"] = True   # 跑过才置位, 顺序在赋值之后不可颠倒
        cases_summary = run_cases_eval(cases_dir)                                                   # 用例逐个执行, 门禁类用例另由量规单列
        cases_summary["measured"] = True
    if args.mode in ("audit", "all"):
        audit_summary = run_audit()             # 六审计器 + 反证夹具, 读本仓静态文件
        audit_summary["measured"] = True
        docstring_summary = run_docstring_dimension()                                       # docstring 维度归审计模式, 与行为维度互不顶替
        docstring_summary["measured"] = True

    rubric_result = evaluate_rubric(                                                               # 五份汇总一次交进去: 评分层不自己回头取数
        rubric, scenarios_summary, cases_summary, audit_summary, docstring_summary)                # 参数顺序即签名顺序, 五个汇总一个都不能少

    report = {                                    # 报告是 --json 的唯一出口, 字段名即契约
        "skill": "astro-best",
        "mode": args.mode,
        "overall_score": rubric_result.get("overall_score", 0.0),
        "pass_threshold": rubric_result.get("pass_threshold"),
        "passed": rubric_result.get("passed", False),
        "dimensions": rubric_result.get("dimensions", []),
        "scenarios": {"total": scenarios_summary["total"], "passed": scenarios_summary["passed"],
                      "rate": round(scenarios_summary.get("rate", 0.0), 4)},
        "cases": {"total": cases_summary["total"], "passed": cases_summary["passed"],
                  "rate": round(cases_summary.get("rate", 0.0), 4)},
        "audit": {"n_auditors": audit_summary.get("n_auditors", 0),
                  "n_failed": audit_summary.get("n_failed_auditors", 0),
                  "n_findings": len(audit_summary.get("findings", [])),
                  # 不扣分的 finding 单独计数: n_findings=99 而 n_deducted=0 此前
                  # 与"一条 finding 都没有"在报告上长得一样 (N1-04)
                  "n_waived": len(rubric_result.get("waived_findings", [])),
                  "n_deducted": len(audit_summary.get("findings", [])) - len(rubric_result.get("waived_findings", [])),
                  "waived": rubric_result.get("waived_findings", []),
                  "passed": audit_summary.get("passed", True)},
        "docstrings": docstring_summary,
        # 观测面 (N1-03): "放行但有 WARN 维"必须与"完全干净"在机读出口上可区分。
        # 刻意不放进 passed 的判定链 —— WARN 不阻断是现行判据语义。
        "warn_line": rubric_result.get("warn_line"),
        "warn_dimensions": rubric_result.get("warn_dimensions", []),
        "has_warn": bool(rubric_result.get("warn_dimensions")),
    }
    if rubric_result.get("error"):
        # 量规配置错误要显式带进报告: 否则只看分数看不出"根本没打上分"
        report["error"] = rubric_result["error"]

    if args.json:                                  # 机器可读出口: CI / 上层编排直接解析
        # 机器可读输出: CI / 上层编排直接解析
        print(json.dumps(report, ensure_ascii=False, indent=2))                                 # 机器可读出口: 字段名即契约, 上层编排直接解析
    else:
        print("=" * 74)
        print(f"        astro-best 质量评审报告 (mode={args.mode}, Phase 5 重建)")
        print("=" * 74)
        if args.mode in ("behavior", "all"):
            print(f"场景: {scenarios_summary['passed']}/{scenarios_summary['total']} 通过  |  "
                  f"用例: {cases_summary['passed']}/{cases_summary['total']} 通过")
        if args.mode in ("audit", "all"):
            print(f"审计器: {audit_summary.get('n_auditors', 0)} 个 "
                  f"(失败 {audit_summary.get('n_failed_auditors', 0)}), "
                  f" findings {len(audit_summary.get('findings', []))} 条  |  "
                  f"docstring 覆盖: {docstring_summary.get('coverage', 0):.2%} "
                  f"({docstring_summary.get('documented', 0)}/{docstring_summary.get('total_public_functions', 0)})")
            # findings 只预览前 20 条: 全量在 --json 里, 人类报告保持可读
            for f in audit_summary.get("findings", [])[:20]:  # 截断只影响人读, 计数仍是全量
                print(f"  [{f['severity']}] {f['auditor']}: {f['target']} — {f['message']}")
        print("-" * 74)
        print(f"{'维度':<20} | {'权重':<5} | {'得分':<7} | {'加权':<7} | 状态")
        print("-" * 74)
        for d in report["dimensions"]:            # 逐维度成行: 权重/得分/加权/状态四列
            print(f"{d['dimension']:<20} | {d['weight']:<5.2f} | {d['score']:<7.4f} | "
                  f"{d['weighted']:<7.4f} | [{d['status']}]")
        print("-" * 74)
        print(f"综合评分: {report['overall_score']:.4f} (合格线 {report['pass_threshold']}, "
              f"WARN 线 {report['warn_line']})")
        # WARN/豁免必须上人读首屏 (N1-03/N1-04): 此前"放行但有缺陷"与"全绿"在
        # 终端上只差一个 SUCCESS 字样, 复核者极易读成全清。
        if report["warn_dimensions"]:
            print(f"[WARN] 以下维度处于 WARN 档 (不阻断放行, 但确有缺陷): "
                  f"{', '.join(report['warn_dimensions'])}")
        if report["audit"]["n_waived"]:
            print(f"[豁免] {report['audit']['n_waived']} 条 finding 因 severity=INFO 未扣分 "
                  f"(计入 n_findings 但不计 n_deducted)")
        if rubric_result.get("error"):
            print(f"[RUBRIC-ERROR] {rubric_result['error']}")
        status_str = "SUCCESS (通过)" if report["passed"] else "FAILED (未达标)"  # 判定行, 人读唯一出口
        print(f"判定结果: {status_str}")
        print("=" * 74)

    return 0 if report["passed"] else 1             # 退出码契约: 0 达标 / 1 未达标或输入缺失


if __name__ == "__main__":
    sys.exit(main())                                                                     # 直跑时把返回码交给外层: 门禁靠它判 SUCCESS/FAIL
