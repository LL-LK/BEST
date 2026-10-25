"""把 answers.json 渲染成 ANSWERS.md 汇总 + 28 份单题答案文件。

用法: python render.py
输出: ./ANSWERS.md 与 ./NL2T-01.md ... ./NL2T-28.md (UTF-8)
"""
from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent

VERDICT_LABEL = {
    "call": "直接调用",
    "clarify": "先澄清再调用",
    "refuse": "拒绝并说明",
}


def fmt_args(arguments: object) -> str:
    """把参数渲染成代码块里的可读形式。"""
    if arguments is None:
        return "(无调用)"
    if isinstance(arguments, dict) and not arguments:
        return "()"
    parts: list[str] = []
    for key, value in arguments.items():
        if isinstance(value, str):
            parts.append(f'{key}="{value}"')
        elif isinstance(value, bool):
            parts.append(f"{key}={str(value).lower()}")
        else:
            parts.append(f"{key}={value}")
    return "(" + ", ".join(parts) + ")"


def render_item(item: dict) -> str:
    """渲染单题答案正文。"""
    lines: list[str] = []
    lines.append(f"# {item['id']}")
    lines.append("")
    lines.append("## 题面")
    lines.append("")
    lines.append(f"> {item['utterance']}")
    lines.append("")
    lines.append("## 判定")
    lines.append("")
    lines.append(f"- 类别：**{VERDICT_LABEL.get(item['verdict'], item['verdict'])}**"
                 f"（`{item['verdict']}`）")
    tool = item.get("tool") or "——"
    lines.append(f"- 目标工具：`{tool}`")
    lines.append("")
    lines.append("## 期望调用")
    lines.append("")
    lines.append("```python")
    lines.append(f"{tool}{fmt_args(item.get('arguments'))}")
    lines.append("```")
    lines.append("")
    if item.get("clarifications"):
        lines.append("## 需要澄清的点")
        lines.append("")
        for note in item["clarifications"]:
            lines.append(f"- {note}")
        lines.append("")
    if item.get("refusal_reason"):
        lines.append("## 拒绝理由")
        lines.append("")
        lines.append(f"- {item['refusal_reason']}")
        lines.append("")
    lines.append("## 关键要点 / 坑位")
    lines.append("")
    for point in item["key_points"]:
        lines.append(f"- {point}")
    lines.append("")
    lines.append("## 给用户的回答口径")
    lines.append("")
    lines.append(item["user_reply"])
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    """渲染汇总与单题文件。"""
    payload = json.loads((HERE / "answers.json").read_text(encoding="utf-8"))
    items = payload["items"]

    rows: list[str] = []
    for item in items:
        summary = item["key_points"][0]
        rows.append(
            f"| {item['id']} | {VERDICT_LABEL.get(item['verdict'], item['verdict'])} "
            f"| `{item.get('tool') or '——'}` | {summary} |"
        )

    head: list[str] = []
    head.append("# E1 / NL2Tool 28 题作答汇总")
    head.append("")
    head.append(f"- 被测对象：**{payload['subject']}**")
    head.append(f"- 批次：{payload['batch']} · 作答日期：{payload['answer_set_date']}")
    head.append("- 作答口径：只依据被测对象本体可提供的信息作答（SKILL.md / README.md / "
                "manifest.yaml / architecture.md / contracts / static / references / src）；"
                "未查看任何评测标注、判分器与历史跑批结果。")
    head.append("")
    head.append("## 工具面（7 个原子工具）")
    head.append("")
    for tool in payload["tool_surface"]:
        head.append(f"- `{tool}`")
    head.append("")
    head.append("## 逐题一览")
    head.append("")
    head.append("| 题号 | 判定 | 工具 | 要点 |")
    head.append("|------|------|------|------|")
    head.extend(rows)
    head.append("")
    counts = {
        "call": sum(1 for i in items if i["verdict"] == "call"),
        "clarify": sum(1 for i in items if i["verdict"] == "clarify"),
        "refuse": sum(1 for i in items if i["verdict"] == "refuse"),
    }
    head.append(f"统计：直接调用 {counts['call']} 题 · 先澄清 {counts['clarify']} 题 · "
                f"拒绝 {counts['refuse']} 题 · 合计 {len(items)} 题。")
    head.append("")
    head.append("## 逐题详情")
    head.append("")
    for item in items:
        head.append(f"### {item['id']}")
        head.append("")
        head.append(f"> {item['utterance']}")
        head.append("")
        head.append(f"**判定**：{VERDICT_LABEL.get(item['verdict'], item['verdict'])} · "
                    f"工具：`{item.get('tool') or '——'}`")
        head.append("")
        head.append("```python")
        head.append(f"{item.get('tool') or '——'}{fmt_args(item.get('arguments'))}")
        head.append("```")
        head.append("")
        if item.get("clarifications"):
            head.append("**澄清点**")
            head.append("")
            for note in item["clarifications"]:
                head.append(f"- {note}")
            head.append("")
        if item.get("refusal_reason"):
            head.append(f"**拒绝理由**：{item['refusal_reason']}")
            head.append("")
        head.append("**要点**")
        head.append("")
        for point in item["key_points"]:
            head.append(f"- {point}")
        head.append("")
        head.append(f"**回答口径**：{item['user_reply']}")
        head.append("")
        head.append(f"（单题完整版见 `NL2T-{item['id'].split('-')[1]}.md`）")
        head.append("")

    (HERE / "ANSWERS.md").write_text("\n".join(head), encoding="utf-8")
    for item in items:
        (HERE / f"{item['id']}.md").write_text(render_item(item), encoding="utf-8")
    print(f"wrote ANSWERS.md and {len(items)} per-item files into {HERE}")


if __name__ == "__main__":
    main()
