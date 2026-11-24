# -*- coding: utf-8 -*-
"""evals.nl2tool.gen_golden — E1 金标准轨迹生成 (标注 → 期望轨迹, 离线自证)。

能力边界: 从 tasks.yaml 的标注合成"标准受试轨迹" — answer 路由取
expect_tools 的非 optional 项; clarify/reject 路由零调用 + 含关键词与
候选的话术。用途: 判定器与标注的**一致性自证** (金标准必须被判高分,
否则标注或判定器有洞 — 与 E2 gold/ E5 ScriptedLLM 同模式)。
边界: 只读标注只写 traces/golden/; 真模型跑批的轨迹另放 traces/。

白盒锚点: docs/eval-E1-nl2tool.md §3 (标注 schema) / §7 (双通道判定);
evals/nl2tool/tasks.yaml (26 条标注)。
"""
from __future__ import annotations

# 标准库: JSON (轨迹落盘) / 路径
import json
from pathlib import Path

# 本地: 任务集路径
NL2TOOL_DIR = Path(__file__).resolve().parent      # 锚点按文件位置算, 换机可跑
TASKS_PATH = NL2TOOL_DIR / "tasks.yaml"            # 标注只读, 本文件从不写回
GOLDEN_DIR = NL2TOOL_DIR / "traces" / "golden"     # 金标准只进 golden/, 不与真实跑批混放


def _answer_text(task: dict) -> str:
    """按路由合成标准话术 (clarify/reject 的关键词通道必须命中)。"""
    route = task.get("route", "answer")             # 三路由决定话术形态 (缺省按 answer)
    if route == "clarify":
        clarify = task.get("clarify") or {}         # 标注缺字段也能合成话术 (不崩)
        missing = "、".join(str(m) for m in clarify.get("missing") or []) or "关键维度"  # 必须问出缺什么
        options = "；".join(str(o) for o in clarify.get("options") or [])   # 候选值分号隔, 便于人读
        text = f"需要补充信息: 缺少 {missing}。"    # "需要/缺少" 是 E1 澄清关键词通道的锚
        if options:                                 # 有候选才追加: 无候选只问不诱导
            text += f" 可选: {options}。"
        return text
    if route == "reject":
        reject = task.get("reject") or {}
        code = str(reject.get("reason_code") or "E_INVALID_INPUT")   # 缺理由码兜底成契约内合法码
        suggest = "；".join(str(s) for s in reject.get("suggest") or [])
        text = f"不支持该请求 ({code}), 无法执行。"  # "不支持/无法" 命中拒绝关键词通道
        if suggest:                                 # 替代路径缺失时只声明拒绝, 不编造
            text += f" 建议: {suggest}。"
        return text
    return "已按工具面完成查询并汇报结果 (含 total/returned/truncated 三元组)。"  # answer 路由须报截断三元组


# 占位符 → 具体合法值 (标注里 <...> 形态的运行时依赖值; 金标准轨迹必须可判 —
# 非数值的 ra/dec 会被参数判幻觉红线抓住, 故按固定替换表具化)。
# 取值与仓内回放设施一致 (E2 快照的标准天区 RA=180/Dec=30; M31 为标准解算名)。
_PLACEHOLDER_VALUES = {                                                                       # 取值须与回放设施同源: 换一套数金标准就与快照对不上
    "ra": 180.0,        # 标准天区 RA, 与 E2 快照同值
    "dec": 30.0,        # 标准天区 Dec
    "name": "M31",      # 标准解算名 (CDS Sesame 侧的可复现名)
    "sqlid": "s0001",   # 会话占位: 形如上一步回填的 sqlid
    "page": 2,          # 第二页: 覆盖分页分支, 免得金标准只走第一页
}


def _concretize(args: dict) -> dict:
    """占位符具化: "<...ra...>" → 180.0 等 (键名子串匹配, 保序其余原样)。"""
    out = {}                                        # 保序回填: 输出序 = 标注书写序
    for key, value in (args or {}).items():         # args 缺省按空处理 (标注可省 args)
        if isinstance(value, str) and value.startswith("<") and value.endswith(">"):  # 只具化 <...> 形态
            for token, concrete in _PLACEHOLDER_VALUES.items():                                     # 按表序试命中: 这张表本身就是优先级
                if token in key or token in value:   # 键名或占位正文命中即算 (键名更可靠)
                    out[key] = concrete              # 命中即止: 一个占位符只具化一次
                    break
            else:
                out[key] = value                    # 表外占位符原样留 (不猜值, 交 grader 判)
        else:
            out[key] = value                        # 非占位符值原样透传
    return out


def golden_trace(task: dict) -> dict:
    """一条标注 → 金标准轨迹 (deterministic; 只增不改)。"""
    calls = []                                      # 只有 answer 路由才有调用序列
    if task.get("route", "answer") == "answer":
        for step in task.get("expect_tools") or []:
            if step.get("optional"):                # optional 是白名单, 不进必需轨迹
                continue
            calls.append({"tool": step.get("tool"),
                          "args": _concretize(step.get("args"))})  # 参数具化后才可机比
    return {"task_id": task.get("id"),             # 回链标注 id: runner 按它配对
            "route": task.get("route", "answer"),  # 路由原样带出, 供人核对期望口径
            "tool_calls": calls,                    # 期望调用序列 (保序)
            "answer_text": _answer_text(task),      # 合成话术 (关键词通道必须命中)
            "source": "golden-from-annotation"}     # 关键: 标记合成来源, 防被读成模型跑批


def generate(tasks_path: Path = TASKS_PATH, out_dir: Path = GOLDEN_DIR) -> list[Path]:
    """全量生成金标准轨迹 → 落盘路径清单 (缺 tasks 即抛 — fail-closed)。"""
    # 第三方: 任务标注装载 (金标准轨迹的期望序列来源)
    import yaml

    if not tasks_path.is_file():                                                            # fail-closed: 缺任务集即抛, 不产出空金标准
        raise FileNotFoundError(f"E1 任务集缺失: {tasks_path}")
    data = yaml.safe_load(tasks_path.read_text(encoding="utf-8")) or {}   # 空文件按空 dict
    tasks = data.get("tasks") if isinstance(data, dict) else data  # 兼容顶层列表/带 tasks 键
    if not tasks:                                                                                   # 空任务集也算缺陷: 零条会被读成全过
        raise ValueError(f"E1 任务集为空: {tasks_path}")
    out_dir.mkdir(parents=True, exist_ok=True)     # 目录可重复创建 (轨迹只增不改)
    written = []                                   # 落盘清单即返回值, 调用方靠它对账
    for task in tasks:                                                                       # 逐条生成, 任一条抛异常即停: 便于定位是哪条标注坏了
        path = out_dir / f"{task.get('id')}.json"  # 文件名 = 任务 id, 与 runner 的 trace 键一致
        # newline="\n" 不可省: Windows 文本模式会把 \n 转成 \r\n, 而 .gitattributes
        # 对 *.json 钉了 eol=lf —— 省掉它会让这 26 个受跟踪产物在工作区变 CRLF
        # (与 ops/audit/check_line_endings.py 的 LF 约定矛盾; docs/diagrams/drawio_io.py
        # 踩过同一个坑, 那里的处置是改 write_bytes)。
        path.write_text(json.dumps(golden_trace(task), ensure_ascii=False, indent=2),  # indent 固定: 金标准是受跟踪产物, 格式漂移会污染 diff
                        encoding="utf-8", newline="\n")
        written.append(path)                        # 逐个登记, 顺序即任务顺序
    return written


if __name__ == "__main__":
    paths = generate()                                                                           # 直跑入口: 落盘清单直接回显, 便于人眼核条数
    print(f"generated {len(paths)} golden traces -> {GOLDEN_DIR}")
