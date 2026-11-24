# -*- coding: utf-8 -*-
"""evals.ablation.harness.subagent_capture — 用子代理产出 E5 的 live 臂采集表。

能力边界: 只做一件事 —— 把「子代理对每道题给出的决策」写成
:mod:`evals.ablation.harness.captured_llm` 约定的采集表形态。决策逻辑、工具面、
打分判据一概不在本模块 (那是 adapters / metrics 的活)。

为什么需要它 (2026-10-07): ``CapturedLLM`` 的契约早就在, 但**仓内没有任何东西能
产出它所需的采集文件** —— 实测 ``evals/ablation/`` 下那两个 ``live-*.json`` 是
**报告** (含 blockers/cards), 不是采集表, 且都**没有 provenance 段** (审计实测:
78 份 live 轨迹零模型字段、零模型名字符串)。于是 ``--require-live`` 至今没有
通过路径。本模块补上生产端。

**同源偏差必须显式披露** (用户裁定: 接受同源偏差, 但在报告里写明): 轨迹由子代理
产生, 而子代理与被判定的判定器同族 —— 它**不能**用来声称"模型 X 的能力", 只能
用来证"换掉脚本化替身后, 决策形态确实变了"。所以采集表里强制写
``provenance.model_kind = "subagent"``, 且 :func:`check_capture_provenance` 会
拒收没有 provenance 的采集表 —— 缺声明的 live 批次等于没说是谁跑的, 那正是
审计点名的问题。

对外接口: :func:`build_capture` (把逐题决策装配成采集表) / :func:`check_capture_provenance`
(把关采集表的来源声明) / :data:`CAPTURE_SCHEMA_VERSION` (表格式版本)。

依赖: 只用标准库 + 本实验内件。不 import 被测产品代码 —— 采集表是**输入**, 不是
被测对象。
"""
from __future__ import annotations

# 标准库: JSON 读写 / 时间戳 / 路径 / 类型标注
import json
import time
from pathlib import Path
from typing import Any, Callable

# 表格式版本: 采集表的形态会变 (attempt 分槽就是后加的), 版本号让消费方能拒收旧表
CAPTURE_SCHEMA_VERSION = 2

# provenance 里 model_kind 的合法取值。**只有两种**, 且都不是"某个厂商的模型":
#   subagent —— 子代理产生的决策 (本模块); 本仓不连真实模型/付费 API。
#   human    —— 人工录入的决策 (仓外流程)。
# 不设 "llm:<厂商>" 之类的自由值: 那会让"到底是谁跑的"重新变成一个不可核查的口头声明,
# 而这正是审计 78 份轨迹零归属的成因。
ALLOWED_MODEL_KINDS = ("subagent", "human")


class CaptureProvenanceError(ValueError):
    """采集表缺来源声明或声明非法 —— fail-closed, 不替调用方编一个。"""


def check_capture_provenance(capture: dict) -> dict:
    """校验采集表的来源声明, 原样返回那段 provenance。

    为什么单列一个函数而不是在 :func:`build_capture` 里顺手写: 消费方
    (:class:`~evals.ablation.harness.captured_llm.CapturedLLM`) 必须能对**别人给的**
    采集表做同样的把关 —— 仓外采集脚本、CI 传参都可能塞进一份没有归属的表。

    Args:
        capture: 采集表顶层字典。

    Returns:
        校验通过的 provenance 字典。

    Raises:
        CaptureProvenanceError: 缺 ``provenance``、缺必填字段、或 ``model_kind``
            不在 :data:`ALLOWED_MODEL_KINDS` 内。
    """
    prov = capture.get("provenance")  # 来源段取顶层键
    if not isinstance(prov, dict) or not prov:  # 必须是非空字典
        # 缺声明不是"小事": 一份不说清谁跑的 live 批次, 其分数无法归因到任何模型能力
        raise CaptureProvenanceError(
            "采集表缺 provenance 段 —— 无法归因到任何决策来源, 拒收 "
            "(审计实测: 78 份 live 轨迹零模型字段, 分数无从归属)"
        )
    kind = prov.get("model_kind")  # 读取决策模型分类
    if kind not in ALLOWED_MODEL_KINDS:  # 限制在白名单之内
        raise CaptureProvenanceError(
            f"provenance.model_kind={kind!r} 不在 {ALLOWED_MODEL_KINDS} 内 —— "
            f"只接受子代理或人工录入, 不接受自由文本(那会让来源重新变成口头声明)"
        )
    for required in ("producer", "captured_at"):  # 遍历必填凭证字段
        if not prov.get(required):  # 缺凭证字段直接拦截
            raise CaptureProvenanceError(f"provenance 缺必填字段 {required!r}")
    return prov  # 校验通过返回原始 provenance


def build_capture(decisions: dict[str, dict[str, dict[str, dict[str, Any]]]],
                  *, producer: str, model_kind: str = "subagent",
                  notes: str = "") -> dict:
    """把逐题决策装配成采集表 (形态见 :mod:`captured_llm` 模块头)。

    Args:
        decisions: ``{系统 id: {任务 id: {attempt 号: {"route", "tool_calls", "answer_text"}}}}``。
            三层嵌套与采集文件形态逐字对应, 装配层只做校验与加版本, 不改内容。
        producer: 谁产出的这份表 (必填, 如 ``"mavis-subagent"``)。它进 provenance,
            是"这批决策由谁产生"的唯一可核查凭据。
        model_kind: ``subagent`` 或 ``human`` (见 :data:`ALLOWED_MODEL_KINDS`)。
        notes: 自由注记, 会原样进 provenance。

    Returns:
        可直接喂给 :class:`~evals.ablation.harness.captured_llm.CapturedLLM` 的采集表。

    Raises:
        CaptureProvenanceError: 决策矩阵形状不对, 或来源声明非法。
    """
    if model_kind not in ALLOWED_MODEL_KINDS:  # 来源类别白名单校验
        raise CaptureProvenanceError(f"model_kind={model_kind!r} 非法 (只接受 {ALLOWED_MODEL_KINDS})")
    if not producer:  # 生产方标识判空检查
        raise CaptureProvenanceError("producer 必填: 说不清谁跑的采集表不可归因")
    for system_id, per_system in (decisions or {}).items():  # 逐系统遍历
        if not isinstance(per_system, dict):  # 校验系统层字典类型
            raise CaptureProvenanceError(f"系统 {system_id!r} 的任务层必须是 dict, 收到 {type(per_system)}")
        for item_id, per_attempt in per_system.items():  # 逐测试用例遍历
            if not isinstance(per_attempt, dict) or not per_attempt:  # 校验轮次记录非空
                # 空 attempt 槽会让 CapturedLLM 在 repeat>1 时于第 2 轮抛, 与"采集缺失"同形
                raise CaptureProvenanceError(f"{system_id}/{item_id} 没有任何 attempt 决策")
    return {
        "schema_version": CAPTURE_SCHEMA_VERSION,
        # 来源声明放在**嵌套层内** (decisions 下), 不与系统 id 平铺:
        # CapturedLLM 是按 "capture[系统 id][任务 id][attempt]" 取的, 平铺会把
        # provenance 变成一个"名叫 provenance 的系统", 取值时看着像覆盖完整。
        # 放嵌套层则它对每个系统都可见, 且不会污染键空间。
        "decisions": decisions,
        "provenance": {
            "model_kind": model_kind,
            "producer": producer,
            "captured_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            # 同源偏差的正面披露: 决策来源与被测判定器同族, 该批次**不得**用来
            # 声称任何模型的性能, 只能证"决策形态相对脚本化替身发生了变化"。
            "same_family_bias": True,
            "claim_scope": "仅可证『决策形态变了』; 不可用于声称任何模型的能力或性能",
            "notes": notes,
        },
    }


def strip_provenance(capture: dict) -> dict:
    """返回**只有决策**的那一份采集表 (喂给 :class:`CapturedLLM` 的形态)。

    为什么需要: 本模块把 provenance 放在 ``decisions`` 嵌套层以免污染键空间, 而
    ``CapturedLLM`` 直接在顶层按系统 id 取键。两者形态不同是刻意的 —— 一个要
    自证归属, 一个要按 id 取决策, 合成一层会让归属键被当成系统。
    本函数是那条缝合线, 且只留一层: 消费方一律 ``CapturedLLM(system,
    strip_provenance(capture))``。

    Args:
        capture: :func:`build_capture` 的产物 (或等价的既有采集表)。

    Returns:
        ``{系统 id: {任务 id: {attempt: 决策}}}`` 形态的字典。
    """
    nested = capture.get("decisions")  # 探测嵌套层决策键
    if isinstance(nested, dict):  # 存在嵌套决策则直取
        return nested  # 本模块产的形态: 取嵌套层
    # 既有采集表 (平铺决策): 剔掉本模块自己那两个元数据键即可
    return {k: v for k, v in capture.items() if k not in ("provenance", "schema_version")}  # 剥离元数据键后返回纯决策表


def save_capture(capture: dict, path: Path) -> Path:
    """把采集表落盘 (产物只进 temp/, 铁律 3)。

    Args:
        capture: :func:`build_capture` 的产物。
        path: 目标路径 (应在 temp/ 下)。

    Returns:
        落盘后的路径。
    """
    path = Path(path)  # 收成 Path: 调用方传 str 也能用
    path.parent.mkdir(parents=True, exist_ok=True)  # 父目录现建: 产物目录不该是调用方的义务
    path.write_text(json.dumps(capture, ensure_ascii=False, indent=2), encoding="utf-8")  # 缩进 2: 这份表要被人读
    return path


def decisions_from_records(records: list[dict], *, system_key: str = "system",
                           item_key: str = "item_id", attempt_key: str = "attempt",
                           payload_key: str = "decision") -> dict:
    """把 :func:`evals.ablation.harness.run_batch.run_matrix` 的逐 run 记录转成决策矩阵。

    存在的理由: 跑批记录是**扁平的 run 列表**, 而采集表是**三层嵌套**。手工转录会
    抄错一层, 而抄错的采集表会让 CapturedLLM 拿到错的决策而无人察觉。

    Args:
        records: 逐 run 记录 (每条至少带系统/任务/attempt 三个键与决策负载)。
        system_key / item_key / attempt_key: 三级键在记录里的字段名。
        payload_key: 决策负载所在字段 (含 route / tool_calls / answer_text)。

    Returns:
        ``{系统: {任务: {attempt: 决策}}}`` 形态的矩阵, 可直接交给 :func:`build_capture`。
    """
    matrix: dict[str, dict[str, dict[str, dict[str, Any]]]] = {}  # 决策矩阵字典初始化
    for record in records or ():  # 逐条扫描扁平运行记录
        system_id = record.get(system_key)  # 缺键会在下面 IndexError/KeyError 处炸, 不静默跳过
        item_id = record.get(item_key)  # 题目用例标识提取
        # attempt 键必须落成**字符串**: 采集表要经 JSON 落盘, 而 JSON 对象的键恒为字符串。
        # 用 int 建键的话, 内存里查得到、落盘再读回来就查不到 —— 那个 bug 会在
        # "跑批通过但复跑失败"时才暴露, 极难归因。
        attempt = str(int(record.get(attempt_key, 1)))  # 规整为规范字符型轮次
        payload = record.get(payload_key) or {}  # 缺负载给空 dict: 决策为空是合法状态 (模型没给动作)
        matrix.setdefault(system_id, {}).setdefault(item_id, {})[attempt] = payload  # 存入三层字典目标分槽
    return matrix  # 装配完成返回决策矩阵


# 子代理决策的最小契约: 传进来的 callable 只拿到 (item, attempt), 返回决策 dict。
# 刻意不给它任何打分/判据入口 —— 采集端能做的只有"记下决策了什么", 判分在跑批侧。
SubagentDecider = Callable[[dict, int], dict]
