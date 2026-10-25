# -*- coding: utf-8 -*-
"""评分判据的**变更登记**门禁 (N1-01/N1-02) —— 权重与合格线不许静默改掉结论。

被守护的判据 (每条都是先实测复现过的, 不是假想):

  N1-01 权重与合格线是零守护的自由参数。实测 (``temp/N1-probe1.py``):
    * 权重和校验只管"和 == 1.0", 不管分配 —— 把 correctness 0.30→0.05、
      provenance 0.10→0.35 (和仍精确 1.000000, 顺利通过校验), 4 条真 MAJOR
      findings 的批次从 FAIL (0.88) 翻成 PASS (0.98)。
    * pass_score 0.90→0.88 一行即把同一批翻成 PASS, 且 0.88 > WARN 线 0.85
      **不会**触发 ``pass_score <= WARN_LINE`` 的自洽校验。
    * 更严重的一处 (本文件新增守护的重点): 权重和校验**连维度集合都不管** ——
      把 correctness 整维从量规删掉 (权重挪给 provenance, 和仍精确 1.0),
      4 条真 MAJOR findings 下门禁报 ``overall=1.0 / passed=true``:
      决定性维度被摘掉反而全绿。循环遍历的是量规声明的维度, 少声明的那一维
      根本不进加权总分。已在 ``evaluate_rubric`` 里改为集合自洽即判配置错误。

  为什么是"登记簿"而不是"硬锁" (本文件的核心权衡):
    权重与合格线是**可调参数** —— 标定漂移时必须能改。把它们硬锁成"改了必红"
    等于焊死调参通道, 反而逼人绕过门禁 (改门禁永远比改参数更容易下决心)。
    真正要守护的不是"值不许变", 而是"**变必须留痕**": 单改量规 → 红;
    同步登记 → 绿。改动从"一行静默改掉结论"变成"两处留痕的显式决定"。
    残留风险如实登记在 ledger 文件抬头: 有心人可同时改两处, 这道门拦的是
    "顺手改一下"和"复核者漏看", 不是恶意绕过 —— 后者任何仓内门禁都拦不住。

  N1-02 量规里"写着但没人读"的字段是死配置。本文件把量规顶层字段分成
    "runner 真读"与"显式声明为声明性"两类, **未登记即红** —— 消除
    "改量规的人以为改了, 实际没改"这一形态。实测依据:
    ``warn_line`` 此前在 YAML 里写着 0.85 而 runner 硬编码 0.85 (改 YAML 零
    行为变化); ``gates_thresholds`` 与 ``evals/cases/*.yaml`` 的 threshold
    块重复同一组阈值, 构成第二个 SSOT, 已从量规删除。

用法: 改 evals/scoring-rubric.yaml 的权重/合格线时, **必须**同时在
``evals/_data/scoring-weights-ledger.yaml`` 的 ``approved`` 改基线 (改标定)
或在 ``deviations`` 追加一条带 ``reason`` 的偏离 (临时调整), 否则本门禁红。
"""
from __future__ import annotations

# 标准库: ast 解析 runner 源码 (验豁免写法只存在于代码而非注释) / copy 深拷贝
# (构造篡改样本) / importlib 按文件加载被测 runner / json 读 CLI 报告 /
# subprocess 真跑 CLI / sys.modules 注册 + 子进程解释器路径 / pathlib 定位仓根
import ast
import copy
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

# 第三方: pytest 提供测试框架; yaml 用于解析量规与登记簿 (两者都是 YAML,
# 与 runner 自身用的是同一个解析器, 免得门禁按另一套方言读判据)
import pytest
import yaml

SKILL_ROOT = Path(__file__).resolve().parents[3]      # 仓根: 本文件在 test/unit/meta/, 上溯三级
RUBRIC_PATH = SKILL_ROOT / "evals" / "scoring-rubric.yaml"           # 判据真值
LEDGER_PATH = SKILL_ROOT / "evals" / "_data" / "scoring-weights-ledger.yaml"  # 变更登记簿
RUNNER_PATH = SKILL_ROOT / "evals" / "eval_runner.py"                # 判据实现


def _load_yaml(path: Path) -> dict:
    """读一份 YAML 为 dict。

    Args:
        path: YAML 文件路径。

    Returns:
        解析后的字典; 文件不存在时直接失败 (登记簿缺失 = 无法核对 = 红, 不兜空)。
    """
    assert path.is_file(), f"文件缺失: {path}"  # 缺失即红: 兜空字典会让核对恒绿
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}   # 解析不出内容时也不兜空: 空登记簿 = 无基线可比


def _load_runner():
    """按文件路径加载 eval_runner (它不在包内, 且顶层用兄弟裸导入)。

    Returns:
        刚执行完模块体的模块对象; 每次现取, 避免缓存住旧源码。
    """
    spec = importlib.util.spec_from_file_location("eval_runner_ledger_under_test", RUNNER_PATH)
    module = importlib.util.module_from_spec(spec)                    # 先建对象再注册: dataclass 解析注解要回查模块名
    sys.modules[spec.name] = module               # dataclass 解析字符串注解要回查模块名
    parent = str(RUNNER_PATH.resolve().parent)                       # runner 顶层用兄弟裸导入, 同目录必须在路径上
    if parent not in sys.path:                      # 顶层 from paths/case_executor 依赖同目录在路径上
        sys.path.insert(0, parent)                 # 只在缺席时插入: 重复 insert 会让解析顺序漂移
    spec.loader.exec_module(module)                 # 真正执行模块体, 拿到当前源码的行为
    return module


def _summary(**over):
    """构造一份全绿的汇总 (镜像 main() 对 measured=True 的定义)。"""
    base = {"total": 10, "passed": 10, "rate": 1.0,
            "details": [{"type": "gate", "passed": True}], "measured": True}   # 必须带 gate 明细: 空 details 会让 gate_compliance 算成 0.0
    base.update(over)                                                            # 覆盖项改写基线
    return base


def _audit(n_findings: int = 0) -> dict:
    """构造审计汇总, findings 全部为 MAJOR (真扣分档)。"""
    findings = [{"severity": "MAJOR", "auditor": "a", "target": "t", "message": "m"}
                for _ in range(n_findings)]           # MAJOR 真扣分: INFO 豁免另由专门用例覆盖
    return {"auditors": [], "findings": findings, "passed": True, "measured": True}


def _docstring() -> dict:
    """构造 docstring 维度汇总 (覆盖率满分)。"""
    return {"coverage": 1.0, "total_public_functions": 10, "missing_count": 0,
            "documented": 10, "measured": True}        # measured=True: 未测维度会被判 NOT_MEASURED 并阻断


def _baseline_ledger() -> dict:
    """取登记簿但**清空 deviations** (保留 approved 基线与字段登记)。

    与 _baseline_rubric() 同理: 验"核对函数逻辑"的用例不该被"磁盘登记簿当前
    登记了什么"影响。approved 基线仍取自真实登记簿 (那是基线的权威表述),
    只把偏离列表归零 —— 否则有人登记了一条偏离, 这些用例就因为夹具脏了而红。
    需要验"磁盘登记簿现状"的用例 (基线自洽 / 字段登记) 仍直读磁盘。
    """
    ledger = copy.deepcopy(_load_yaml(LEDGER_PATH))     # 深拷贝: 下面的清空不许污染磁盘读到的对象
    ledger["deviations"] = []                            # 归零: 让夹具与"当前登记了什么"无关
    return ledger


def _baseline_rubric() -> dict:
    """从登记簿 approved 基线**合成**一份量规 (不读磁盘量规)。

    为什么不用磁盘上的量规当夹具: 那会让本文件里"构造篡改样本"的用例反过来
    依赖磁盘状态 —— 一旦磁盘量规被真的改动 (比如有人正在调参), 这些用例会因为
    夹具脏了而红, 与它们各自要验的东西无关。登记簿的 approved 块正是"基线"的
    权威表述, 用它做夹具让每条用例只依赖自己要验的那一个变量。
    需要验"磁盘现状"的用例 (字段登记 / 删 gates_thresholds / 端到端) 仍直读磁盘。
    """
    approved = (_load_yaml(LEDGER_PATH).get("approved") or {})   # 缺 approved 即无基线: 后续全靠它
    return {                                                     # criterion 只是回显字段, 占位即可
        "dimensions": {name: {"weight": float(w), "criterion": f"{name} criterion"}
                       for name, w in (approved.get("weights") or {}).items()},
        "pass_score": approved.get("pass_score"),
        "warn_line": approved.get("warn_line"),
    }


def _evaluate(rubric: dict, n_findings: int = 0) -> dict:
    """用给定量规跑一次 evaluate_rubric, 其余四份汇总全绿。"""
    return _load_runner().evaluate_rubric(rubric, _summary(), _summary(),   # 每次现取 runner: 缓存即失效
                                          _audit(n_findings), _docstring())


# --- 偏离核对的核心: 纯函数, 不碰磁盘, 便于逐条构造反证样本 -----------------

def _unregistered_deviations(rubric: dict, ledger: dict) -> list[str]:
    """列出"量规与登记簿 Approved 基线不一致, 且未在 deviations 逐条登记"的项。

    逐条 (而非整包) 判定: 一条登记只豁免它自己那一条。整包豁免会让"只登记了
    权重改动"顺手放过同批的 pass_score 下调 —— 那正是这道门要拦的形态。
    另查两类簿记卫生问题:
      * **空理由**: 登记了等于没登记 —— reason 非空是登记的**必要条件**;
      * **陈旧条目**: 登记了但值已回到基线。僵尸条目会让登记簿慢慢失去可信度,
        到那时没人再读它, 守护随之失效。

    Args:
        rubric: 解析后的 evals/scoring-rubric.yaml。
        ledger: 解析后的登记簿。

    Returns:
        人类可读的问题描述列表; 空列表表示完全一致或每条偏离都已带理由登记。
    """
    approved = ledger.get("approved") or {}
    approved_weights = approved.get("weights") or {}
    deviations = ledger.get("deviations") or []
    problems: list[str] = []

    # 登记索引: 只收**带非空理由**的条目。空理由的条目在此处直接被拒,
    # 不能用来豁免任何偏离 (登记不等于放行)。
    registered: set[tuple[str, float]] = set()
    for dev in deviations:                        # 逐条过: 空理由的条目在此被拒, 不能豁免任何偏离
        field = str(dev.get("field", ""))
        reason = str(dev.get("reason", "")).strip()
        if not reason:
            problems.append(f"偏离登记缺理由 (等于未登记): field={field!r}")
            continue
        try:
            registered.add((field, float(dev.get("to"))))          # (字段, 新值) 是豁免的唯一凭据
        except (TypeError, ValueError):
            problems.append(f"偏离登记的 to 字段不是数值: field={field!r} to={dev.get('to')!r}")

    def _is_registered(field: str, value: float) -> bool:
        """该 (字段, 值) 是否有一条带理由的登记豁免它。"""
        return (field, value) in registered

    live_weights = {k: float(v.get("weight", 0)) for k, v in (rubric.get("dimensions") or {}).items()}

    for name in sorted(set(approved_weights) | set(live_weights)):   # 并集: 新增与删除两个方向同一处判定
        base = approved_weights.get(name)
        live = live_weights.get(name)
        if base is None:                            # 新增维度: 没有基线可比, 一律要求登记
            problems.append(f"维度 {name} 在量规里存在但登记簿 approved 无基线")
        elif live is None:                          # 删维: 决定性维度被摘掉曾实测能报全绿, 必须登记
            problems.append(f"维度 {name} 在登记簿有基线但量规已删除")
        elif abs(float(base) - live) > 1e-9:
            field = f"weight:{name}"
            if not _is_registered(field, live):
                problems.append(f"权重 {name}: 量规 {live} != 登记基线 {base} (且未登记偏离)")

    for key in ("pass_score", "warn_line"):
        base, live = approved.get(key), rubric.get(key)
        if base is None:
            problems.append(f"{key}: 登记簿 approved 缺该键")                    # 合格线必须登记
        elif live is None:
            problems.append(f"{key}: 量规缺该键")
        elif abs(float(base) - float(live)) > 1e-9:
            if not _is_registered(key, float(live)):
                problems.append(f"{key}: 量规 {live} != 登记基线 {base} (且未登记偏离)")

    for dev in deviations:                          # 陈旧条目: 登记了但值已回到基线
        field, to = str(dev.get("field", "")), dev.get("to")
        if field.startswith("weight:") and field.split(":", 1)[1] in live_weights:
            name = field.split(":", 1)[1]           # 只查权重类偏离: 合格线的陈旧判定在上面的循环里
            try:
                # 陈旧的定义是"活值已回到**基线**" —— 即这条登记已不再描述任何
                # 偏离。刻意不是"活值 == to": 那正是一条**生效中**的登记。
                if abs(float(live_weights[name]) - float(approved_weights[name])) <= 1e-9:
                    problems.append(f"陈旧偏离登记: {field} 已回到基线, 条目应删除")
            except (TypeError, ValueError, KeyError):
                pass                                # 非数值 to 已在上方报过, 不重复
    return problems


class TestLedgerIsNotVacuous:
    """先证登记簿这道门本身不是恒绿 —— 否则下面所有"红"都是假的。"""

    def test_baseline_repo_is_green(self):
        """当前仓内状态必须绿: 不然下面每条红测试都失去参照系。"""
        assert _unregistered_deviations(_load_yaml(RUBRIC_PATH), _load_yaml(LEDGER_PATH)) == []

    def test_unregistered_weight_change_is_caught(self):
        """反证: 只改量规权重 (和仍 1.0) → 必须被抓出来。

        这正是 N1-01 实测能翻结论的那一刀; 守护生效后它不再是静默的。
        """
        rubric = _baseline_rubric()
        rubric["dimensions"]["correctness"]["weight"] = 0.05        # 决定性维度被抽掉
        rubric["dimensions"]["provenance"]["weight"] = 0.35        # 和仍精确 1.0
        assert abs(sum(float(d["weight"]) for d in rubric["dimensions"].values()) - 1.0) < 1e-9
        problems = _unregistered_deviations(rubric, _baseline_ledger())   # 降权零登记: 必须点名 correctness
        assert any("correctness" in p for p in problems), problems

    def test_unregistered_pass_score_change_is_caught(self):
        """反证: pass_score 0.90→0.88 (实测能翻 FAIL→PASS) 必须被抓出来。"""
        rubric = _baseline_rubric()
        rubric["pass_score"] = 0.88
        problems = _unregistered_deviations(rubric, _baseline_ledger())   # 合格线下调零登记: 必须被点名
        assert any("pass_score" in p for p in problems), problems

    def test_deleted_dimension_is_caught(self):
        """反证: 整维删除 (实测能报 overall=1.0 全绿) 必须被抓出来。"""
        rubric = _baseline_rubric()
        del rubric["dimensions"]["correctness"]                        # 摘掉决定性维度, 权重和随之不再是 1.0
        problems = _unregistered_deviations(rubric, _baseline_ledger())   # 删维零登记: 必须被点名
        assert any("correctness" in p for p in problems), problems

    def test_registered_deviation_is_accepted(self):
        """反向自证: 登记过的偏离**不**红 —— 否则这道门把调参通道也焊死了。

        这是"登记簿"与"硬锁"的分界: 登记即放行, 但必须留痕。改动权重时
        同步登记, 门禁转绿; 这不是漏洞, 是设计意图 (见 ledger 文件抬头)。
        """
        rubric = _baseline_rubric()
        rubric["dimensions"]["correctness"]["weight"] = 0.05
        rubric["dimensions"]["provenance"]["weight"] = 0.35
        ledger = _baseline_ledger()                                          # 两条都登记: 应整体放行
        ledger["deviations"] = [
            {"field": "weight:correctness", "from": 0.30, "to": 0.05,
             "reason": "E1 实测 convert 维塌分, 需重标定 (示例条目)"},
            {"field": "weight:provenance", "from": 0.10, "to": 0.35,
             "reason": "配套再平衡, 权重和须仍为 1.0 (示例条目)"},
        ]
        assert _unregistered_deviations(rubric, ledger) == [], \
            "登记过的偏离应放行 —— 若这里红, 说明退化成硬锁, 调参通道被焊死"

    def test_partial_registration_does_not_excuse_the_rest(self):
        """一条登记只豁免它自己: 只登记权重改动不得顺手放过 pass_score 下调。"""
        rubric = _baseline_rubric()
        rubric["dimensions"]["correctness"]["weight"] = 0.05
        rubric["dimensions"]["provenance"]["weight"] = 0.35
        rubric["pass_score"] = 0.88                       # 顺手下调合格线, **不**登记
        ledger = _baseline_ledger()                                          # 只登记两条权重, 不含 pass_score
        ledger["deviations"] = [
            {"field": "weight:correctness", "from": 0.30, "to": 0.05, "reason": "重标定"},
            {"field": "weight:provenance", "from": 0.10, "to": 0.35, "reason": "配套再平衡"},
        ]
        problems = _unregistered_deviations(rubric, ledger)              # 未登记的合格线下调必须仍被报出
        assert any("pass_score" in p for p in problems), problems

    def test_deviation_without_reason_is_caught(self):
        """登记不等于放行: 空 reason 的偏离仍红 (且不得豁免任何一项)。"""
        rubric = _baseline_rubric()
        rubric["pass_score"] = 0.88
        ledger = _baseline_ledger()                                          # 登记了但理由是空白
        ledger["deviations"] = [
            {"field": "pass_score", "from": 0.90, "to": 0.88, "reason": "   "},
        ]
        problems = _unregistered_deviations(rubric, ledger)              # 空理由既报"缺理由"也不豁免
        assert any("缺理由" in p for p in problems), problems
        assert any("pass_score" in p for p in problems), \
            "空理由的条目不得豁免它声称要豁免的那一项"

    def test_stale_deviation_is_caught(self):
        """陈旧条目红: 登记簿不许养僵尸条目, 否则没人再信它。

        刻意用 _baseline_rubric() 而非磁盘量规: 本条验的是核对**函数**对陈旧条目的
        判定, 不该受"磁盘量规当前是什么值"影响 (否则有人一调参, 这条就因为
        夹具脏了而红, 与它要验的东西无关)。
        """
        ledger = _baseline_ledger()                                          # deviations 归零的登记簿
        ledger["deviations"] = [
            {"field": "weight:correctness", "from": 0.30, "to": 0.30, "reason": "示例"},
        ]
        problems = _unregistered_deviations(_baseline_rubric(), ledger)  # 基线量规 + 带陈旧条目的登记簿
        assert any("陈旧" in p for p in problems), problems

class TestRubricFieldsAreEitherReadOrDeclared:
    """N1-02: 量规里的字段要么被 runner 真读, 要么显式声明为声明性。"""

    def test_every_rubric_field_is_accounted_for(self):
        """量规顶层字段必须全部有归属: 被 runner 读, 或在登记簿声明为声明性。"""
        ledger = _load_yaml(LEDGER_PATH)
        consumed = set(ledger.get("consumed_by_runner") or [])
        declared = {str(d.get("field")) for d in (ledger.get("declared_only") or [])}
        live = set(_load_yaml(RUBRIC_PATH).keys())
        assert not (live - consumed - declared), \
            f"量规里有字段既没被 runner 读也没声明为声明性 (死配置): {sorted(live - consumed - declared)}"

    def test_declared_only_entries_carry_a_reason(self):
        """声明性字段必须写清"为什么没有机器消费方", 不许裸登记。"""
        for entry in (_load_yaml(LEDGER_PATH).get("declared_only") or []):
            assert str(entry.get("reason", "")).strip(), f"声明性字段缺理由: {entry.get('field')}"

    def test_warn_line_is_actually_read(self):
        """``warn_line`` 必须真被读 —— 此前 YAML 写 0.85 而代码硬编码 0.85。

        反证形态: 改量规里的 warn_line 必须**改变**门禁行为, 否则仍是死配置。
        """
        module = _load_runner()                                              # 现取 runner, 不复用别的用例加载过的对象
        base = _load_yaml(RUBRIC_PATH)                                      # 真量规: 本条要验磁盘现状
        high = copy.deepcopy(base)                                          # 只动 warn_line 一处
        high["warn_line"] = 0.99                    # 拉到 0.99: 0.9 分的 correctness 应从 WARN 变 FAIL
        a = module.evaluate_rubric(base, _summary(), _summary(), _audit(1), _docstring())   # 基准: warn_line 0.85
        b = module.evaluate_rubric(high, _summary(), _summary(), _audit(1), _docstring())   # 对照: warn_line 0.99
        status_a = {d["dimension"]: d["status"] for d in a["dimensions"]}    # 逐维取状态, 顺序不定故转字典
        status_b = {d["dimension"]: d["status"] for d in b["dimensions"]}
        assert status_a["correctness"] == "WARN", status_a
        assert status_b["correctness"] == "FAIL", status_b
        assert a["warn_line"] == base["warn_line"] and b["warn_line"] == 0.99   # 生效值还要回显到结果里

    def test_no_orphan_gates_thresholds(self):
        """``gates_thresholds`` 必须已从量规删除 (与用例文件的 threshold 块重复)。"""
        assert "gates_thresholds" not in _load_yaml(RUBRIC_PATH), \
            "gates_thresholds 与 evals/cases/*.yaml 的 threshold 块构成第二个 SSOT, 应删除而非接线"


class TestRunnerFailsClosedOnTamperedRubric:
    """N1-01 的运行时守护: 判据被篡改时 evaluate_rubric 必须当场判败。"""

    def test_dropping_a_dimension_is_a_config_error(self):
        """整维删除 (实测能报 overall=1.0 全绿) → 必须 error + passed=False。"""
        rubric = _baseline_rubric()                                           # 夹具与磁盘量规解耦
        del rubric["dimensions"]["correctness"]
        rubric["dimensions"]["provenance"]["weight"] = 0.40      # 和仍精确 1.0
        result = _evaluate(rubric, n_findings=4)                               # 4 条真 MAJOR: 摘维前的真实场景
        assert result["passed"] is False
        assert "correctness" in str(result.get("error")), result

    def test_declaring_an_uncomputable_dimension_is_a_config_error(self):
        """反向: 声明了代码算不出的维度 → 同样 fail-closed (原会按 0.0 静默计分)。"""
        rubric = _baseline_rubric()
        rubric["dimensions"]["nonexistent"] = {"weight": 0.0, "criterion": "x"}  # 权重 0 不改权重和, 只改维度集合
        result = _evaluate(rubric)
        assert result["passed"] is False and "nonexistent" in str(result.get("error")), result

    def test_weight_sum_violation_still_fails(self):
        """原有权重和校验不得被本轮改动削弱 (反向自证)。"""
        rubric = _baseline_rubric()
        rubric["dimensions"]["correctness"]["weight"] = 0.9
        result = _evaluate(rubric)
        assert result["passed"] is False and "权重和" in str(result.get("error")), result

    def test_pass_score_below_warn_line_still_fails(self):
        """原有 pass_score > WARN 线自洽校验不得被削弱 (反向自证)。"""
        rubric = _baseline_rubric()
        rubric["pass_score"] = 0.80
        result = _evaluate(rubric)
        assert result["passed"] is False and "WARN 线" in str(result.get("error")), result


class TestWarnIsObservableButNotBlocking:
    """N1-03: WARN 维必须可观测, 但**不得**变成 FAIL。"""

    def test_warn_dimensions_are_reported(self):
        """存在 WARN 维时, 汇总层必须点名是哪一维 (此前只有 dim_reports 供人读)。"""
        result = _evaluate(_baseline_rubric(), n_findings=1)   # 1 条 MAJOR → correctness 0.9
        assert result["warn_dimensions"] == ["correctness"], result["warn_dimensions"]

    def test_warn_does_not_block(self):
        """反向自证: WARN 仍不阻断 —— 加可观测面不是改判据语义。"""
        result = _evaluate(_baseline_rubric(), n_findings=1)                  # 同一份输入: 只验阻断位没被牵动
        assert result["passed"] is True, "WARN 若开始阻断, 就是把加守护做成了改判据"
        assert not any(result["blocking"].values()), result["blocking"]

    def test_all_pass_has_no_warn_dimensions(self):
        """全绿时不得凭空报 WARN (观测面不许自己制造噪声)。"""
        result = _evaluate(_baseline_rubric(), n_findings=0)                  # 零 finding: 全部维度满分
        assert result["warn_dimensions"] == []

    def test_main_json_exposes_warn_fields(self):
        """机读出口 (--json) 必须带 warn 字段, 否则 CI 侧仍然看不见。

        刻意走**子进程**真跑 ``eval_runner.py --json`` 而不是直调函数: 本条要
        验的是 main() 拼装的那份报告 (函数返回值不等于 CLI 出口), 而 CLI 出口
        正是 CI 与 make 消费的那一份。

        2026-10-07 改写: 原断言钉的是 ``warn_dimensions == ["correctness"]``,
        那是**仓内状态**不是**机制** —— 它假设"当前这份素材恰好有一处 correctness
        WARN"。素材修好之后 (实测五维全 PASS、overall 1.0), 这条红了, 而红的
        原因恰恰是**缺陷被修好了**。这类断言最坏的地方在于: 它会诱使人把
        判据改松以迁就一个已经变好的事实。

        改为断**机制本身**且与状态无关: ``has_warn`` 必须**恰好**等于
        ``warn_dimensions`` 非空, 且两个字段都必须出现在出口里。这样
        - 素材有 WARN 时: has_warn=True 且维名非空 (可观测, 仍放行);
        - 素材全绿时:   has_warn=False 且维名为空 (不凭空制造噪声)。
        两种情形都判红的情形只剩一种: 有人把这两个字段拆散了, 或者让
        has_warn 脱离了 warn_dimensions。
        """
        proc = subprocess.run(                                                 # 真跑一次, 走 CLI 解析与退出码
            [sys.executable, str(RUNNER_PATH), "--json"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            cwd=str(SKILL_ROOT), timeout=900,                                 # runner 用相对路径定位 evals/, cwd 必须是仓根
        )
        assert proc.returncode == 0, proc.stderr[-2000:]
        report = json.loads(proc.stdout)                                      # 出口即契约: 字段名就是 CI 读的东西
        for key in ("warn_line", "warn_dimensions", "has_warn"):
            assert key in report, f"--json 缺 {key}: {sorted(report)}"
        # 机制: 两个字段必须由同一份事实驱动, 不能各说各的
        assert report["has_warn"] is bool(report["warn_dimensions"]), (
            f"has_warn={report['has_warn']} 与 warn_dimensions={report['warn_dimensions']} "
            "不自洽: 机读侧会同时出现'有告警'和'无告警'两种口径"
        )
        # WARN 维名必须真的是表里声明过的维度, 不是随便填的字符串
        declared = {d["dimension"] for d in report.get("dimensions", [])}
        assert set(report["warn_dimensions"]) <= declared, (
            f"warn_dimensions 里有表外维度: {sorted(set(report['warn_dimensions']) - declared)}"
        )
        assert report["audit"]["n_waived"] >= 0, "豁免量必须可读 (INFO finding 计入不扣分)"


class TestInfoWaiverIsVisibleAndClosed:
    """N1-04: INFO 豁免必须可见, 且豁免集合是封闭的。"""

    def test_waived_findings_are_listed(self):
        """99 条 INFO 与"没有 finding"此前在报告上完全一样; 现在必须列出。"""
        audit = {"auditors": [], "measured": True, "passed": True,
                 "findings": [{"severity": "INFO", "auditor": "a", "target": "t", "message": "m"}
                              for _ in range(99)]}
        result = _load_runner().evaluate_rubric(_baseline_rubric(), _summary(), _summary(),  # 99 条全豁免
                                                audit, _docstring())
        assert len(result["waived_findings"]) == 99
        assert result["overall_score"] == 1.0, "INFO 仍不扣分 —— 本轮不改判据语义"

    def test_unknown_severity_is_not_waived(self):
        """未登记的严重度必须按扣分处理 (fail-closed), 不许靠字符串相等蒙混过关。"""
        audit = {"auditors": [], "measured": True, "passed": True,
                 "findings": [{"severity": "info", "auditor": "a", "target": "t", "message": "m"}]}
        result = _load_runner().evaluate_rubric(_baseline_rubric(), _summary(), _summary(),  # 小写 info
                                                audit, _docstring())
        assert result["waived_findings"] == [], "小写 info 不在封闭白名单里, 必须扣分"
        assert result["overall_score"] < 1.0

    def test_non_deducting_set_is_explicit(self):
        """豁免集合必须是显式常量, 而不是散在判定式里的字符串比较。"""
        module = _load_runner()                                              # 豁免集合必须是可枚举的常量而非内联字面量
        assert isinstance(module.NON_DEDUCTING_SEVERITIES, frozenset)
        assert frozenset({"INFO"}) == module.NON_DEDUCTING_SEVERITIES
        # 反向: 代码 (不含注释/docstring) 里不许再出现裸的 != "INFO" 豁免写法。
        # 刻意走 AST 字符串字面量而非全文正则: 注释里正当地解释"此前写死
        # severity != INFO" 时, 全文正则会把说明文字误判成代码。
        tree = ast.parse(RUNNER_PATH.read_text(encoding="utf-8"))           # 静态读源码, 不执行
        docs: set[int] = set()
        for node in ast.walk(tree):                                         # 四类节点的首个元素都可能是 docstring
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                body = getattr(node, "body", None)
                if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                        and isinstance(body[0].value.value, str):
                    docs.add(id(body[0].value))
        bare = [n.value for n in ast.walk(tree)                              # 只认真正的 != "INFO" 比较节点
                if isinstance(n, ast.Compare) and isinstance(n.ops[0], ast.NotEq)
                and isinstance(n.comparators[0], ast.Constant)
                and n.comparators[0].value == "INFO" and id(n.comparators[0]) not in docs]
        assert not bare, f"又出现裸的 != \"INFO\" 豁免写法: 豁免必须走封闭白名单 ({bare})"
