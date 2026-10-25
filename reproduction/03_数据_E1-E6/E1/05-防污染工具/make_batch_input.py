# -*- coding: utf-8 -*-
"""evals.nl2tool.make_batch_input — E1 跑批输入包生成器 (答案隔离的第一道闸)。

存在理由 (E1 §9 防污染): 28 条标注 ``tasks.yaml`` 里, 每条任务都带着
``expect_tools`` / ``anti_patterns`` / ``clarify.options`` / ``reject.reason_code``
—— 这些是**标准答案**。人是手工从标注里抄 utterance 去喂模型的, 一不留神把
整段 YAML 粘进去, 模型就开卷了: NL2T-10 的 anti_patterns 白纸黑字写着
"radius_arcsec = 5 (忘记角分→角秒换算)", 看到这行的模型必然答 300 角秒,
而这 1.0 分是假的。

本件做的只有一件事: **从标注里把答案全部剥掉, 只留用户原话**, 落到独立目录。
产出目录里不允许出现任何一个答案字段名, 生成完立刻自检, 不干净就 fail-closed。

能力边界: 只读 tasks.yaml + 工具 schema, 只写产出目录。不联网、不调大模型、
不改标注 (标注冻结, E1 §9)。**不含判分逻辑** —— 判分是 runner.py 的事。

白盒锚点: docs/eval-E1-nl2tool.md §8 (数据落地) / §9 (标注流程与防污染)。
"""
from __future__ import annotations

# 标准库: 参数解析 / JSON 落盘 / 路径锚定 / 内容指纹 / 时间戳 / 类型标注
import argparse
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

# 脚本直跑 (`python evals/nl2tool/make_batch_input.py`) 时 sys.path[0] 只含本目录 —
# 同时挂 skill 根 (供 evals.* 包导入) 与 evals/ (供 paths 兄弟裸导入), 与 runner 同约定。
_HERE = Path(__file__).resolve()
sys.path.insert(0, str(_HERE.parents[1]))   # evals/
sys.path.insert(0, str(_HERE.parents[2]))   # skill 根

from paths import SKILL_DIR, load_yaml_file  # noqa: E402  # 共享路径工具: YAML 装载与仓根锚定
# 本地: 上下文前缀台账 (跑批前取 turns、判分时取 bindings, 两边必须读同一份 —
# 台账是共同上游, 判分核心与生成器都从它取, 不各写各的读取逻辑)
from evals.nl2tool.context_primers import (  # noqa: E402,F401  (PRIMERS_PATH/load_primers 在此 re-export)
    PRIMERS_PATH,
    load_primers,
)
# 本地: 同实验的黑名单 (题卷里要印"哪些文件不能看", 必须取同一份, 不能抄一遍)
from evals.nl2tool.check_leakage import (  # noqa: E402
    ALLOWED_IN_MODEL_ROOT,
    BLOCKED_PATHS,
)

NL2TOOL_DIR = Path(__file__).resolve().parent
TASKS_PATH = NL2TOOL_DIR / "tasks.yaml"
# 单文件题卷落点: 与 REPORT.md 同址随仓入库 (跑批的人打开它就能照着复制)
TASKS_MD_PATH = NL2TOOL_DIR / "TASKS.md"
SCHEMA_PATH = SKILL_DIR / "references" / "tools.schema.json"
DEFAULT_OUT = SKILL_DIR / "temp" / "nl2tool" / "batch_input"

# ── 答案字段黑名单 (产出里出现任何一个 = 生成件失职, fail-closed) ────────────
# 这些键名在 tasks.yaml 里就紧挨着答案: 命中其一说明剥壳没剥干净, 而不是
# "可能不小心" —— 剥壳是白名单提取 (只取 id/utterance), 本不该有任何残留。
ANSWER_KEYS = (
    "expect_tools",
    "expect_tools_after_clarify",
    "anti_patterns",
    "should_call_best",
    "key_fields",
    "clarify",
    "reject",
    "verify",
    "route",
    "category",
    "partial_credit",
    "must_not_call",
    "reason_code",
    "verify_cmd",
    "anchor",
    "probes",
    "optional",
)

# 白名单: 允许进入跑批输入包的字段, 且只有这两个。
# utterance = 用户原话 (必须一字不改, 否则测的不是同一道题);
# id        = 题号 (用于回写轨迹时对位, 不含任何答案信息)。
ALLOWED_KEYS = ("id", "utterance")


def _sha256(text: str) -> str:
    """短指纹: 对文本取 sha256 前 16 位, 用于 manifest 里对账 utterance 未被改字。"""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _sha256_file(path: Path) -> str:
    """文件指纹: 工具 schema / system prompt 的版本锚, 换版即换值, 可跨批次横评。"""
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def load_utterances(tasks_path: Path) -> list[dict[str, str]]:
    """从标注里白名单提取 id + utterance, 其余字段一律丢弃。

    白名单而非黑名单: 标注 schema 将来加字段时, 新字段默认**不进**跑批包,
    不会静默把新答案漏出去 —— 反过来 (黑名单) 会, 这是选白名单的唯一理由。
    """
    raw = load_yaml_file(tasks_path)
    tasks = raw.get("tasks", raw) if isinstance(raw, dict) else raw
    if not isinstance(tasks, list):
        raise SystemExit(f"tasks.yaml 结构异常: 期望 list 或 {{tasks: [...]}}, 实得 {type(raw).__name__}")

    out: list[dict[str, str]] = []
    for t in tasks:
        if not isinstance(t, dict):
            continue
        tid = str(t.get("id", "")).strip()
        utt = str(t.get("utterance", "")).strip()
        # 显式失败: 缺号或缺话的任务进了跑批包会造成"空题满分", 比报错更糟。
        if not tid:
            raise SystemExit("tasks.yaml 存在缺 id 的任务 — 跑批包无法对位, 拒绝生成")
        if not utt:
            raise SystemExit(f"任务 {tid} 缺 utterance — 空题会让模型无从作答, 拒绝生成")
        out.append({"id": tid, "utterance": utt})
    return out


def render_tasks_md(items: list[dict[str, str]], primers: dict[str, dict],
                    no_ctx: set[str]) -> str:
    """渲染**单文件题卷** TASKS.md: 28 条题面 + 上下文前缀 + 禁看清单。

    为什么要有这个文件: 26 个 per_task/*.txt 对人友好 (一文件一句话, 粘不出答案),
    但人跑批时要开 26 次文件; 而直接看 `tasks.yaml` 又会看到答案。本件把"题面"
    与"答案"分到两个文件: 本件只有题面, 答案留在标注里 —— 物理上翻不到。

    本件必须由生成器产出而非手写: 手抄 28 条就会有漏字 (测的就不是同一道题),
    更可能顺手把答案一起抄过来。生成即白名单提取, 不经过人手。

    含三条硬规矩与禁看清单, 是因为拿着题卷的人**就是**要去喂模型的那个人 ——
    规矩写在题卷里, 比写在另一份文档里更可能被看到。
    """
    lines: list[str] = []
    lines.append("# E1 跑批题卷（TASKS.md）")
    lines.append("")
    lines.append("> **生成件，勿手改** —— 由 `evals/nl2tool/make_batch_input.py` 白名单提取生成；")
    lines.append("> 重新生成：`make e1-batch-input`（或 `python evals/nl2tool/make_batch_input.py --with-primers`）。")
    lines.append("> 本件**只含题面**，不含任何答案（期望工具、错法清单、澄清选项、拒绝理由一律不在此）。")
    lines.append("")
    lines.append("## 一、三条硬规矩（做不到则该批分数作废）")
    lines.append("")
    lines.append("1. **一次只复制一个题块，一题一个新会话**。整份粘进同一会话 = 串题污染")
    lines.append("   （NL2T-10 教会模型换算，NL2T-12 顺势做对，分数是抄的）。")
    # 措辞避开 WEAK_WORDS 里的路由提示词 ("该澄清" 等): 举反面例子时把原词写出来,
    # 会让题卷自己触发弱信号告警 —— 用"是否要"这种中性说法描述即可。
    lines.append("2. **不向模型复述答案、不提示路由**。“再想想”“注意单位”“是否要澄清”都算引导。")
    lines.append("3. **被测模型侧不得挂载**仓库文件读取 / grep / 检索能力 —— 否则下面这份")
    lines.append("   禁看清单形同虚设（模型一个 grep 就能读到标注）。")
    lines.append("")
    lines.append("## 二、不许让模型看到的文件（§9.2 黑名单）")
    lines.append("")
    lines.append("| 路径 | 为什么不能看 |")
    lines.append("|------|------------|")
    for rel, why in BLOCKED_PATHS:                             # 直接取同一份黑名单, 不抄一遍
        lines.append(f"| `{rel}` | {why} |")
    lines.append("")
    lines.append("**可以看的（被测对象本体 + 它本该知道的工具面）**：")
    lines.append("`" + "`、`".join(ALLOWED_IN_MODEL_ROOT) + "`")
    lines.append("")
    lines.append("体检命令（把模型能读到的那一层指进去，命中即 exit 1）：")
    lines.append("")
    lines.append("```bash")
    lines.append("python evals/nl2tool/check_leakage.py --model-root /path/to/model-visible-root")
    lines.append("```")
    lines.append("")
    lines.append("## 三、题面（28 条，一次只取一段）")
    lines.append("")
    for it in items:                                           # 逐题成块: 每块自带前缀说明, 可单独复制
        tid = it["id"]
        lines.append(f"### {tid}")
        lines.append("")
        spec = (primers or {}).get(tid) or {}
        turns = spec.get("turns") or []
        if turns:                                              # 续接题: 先发前缀再发原话
            lines.append("**① 上下文前缀**（先发这段，再发 ②）：")
            lines.append("")
            lines.append("```text")
            for t in turns:
                role = str(t.get("role", "user"))
                lines.append(f"[{role}] {t.get('text', '')}")
            lines.append("```")
            lines.append("")
        elif tid in (no_ctx or set()):                         # 缺指代就是考点: 明写"不许补"
            lines.append("**禁止补上文** —— 本题缺指代就是考点，补一句“那个源是 M31”整题作废。")
            lines.append("")
        tag = "② **用户原话**" if turns else "**用户原话**"
        lines.append(f"{tag}（只复制这一行）：")
        lines.append("")
        lines.append(f"> {it['utterance']}")
        lines.append("")
    return "\n".join(lines) + "\n"


def write_bundle(items: list[dict[str, str]], out_dir: Path, schema_path: Path, tasks_path: Path,
                 primers_path: Path | None = None) -> dict:
    """写跑批输入包: manifest + jsonl + 单题纯文本 + system prompt 模板 (+ 可选上下文前缀)。

    单题 .txt 是给人**直接粘贴**用的: 一个文件只有一句用户原话, 物理上粘不出答案。
    上下文前缀单独落 ``context/`` 子目录 —— 与本题原话**分两个文件**, 好处是
    (a) per_task/ 仍保持"一文件一句话", 泄漏自检不会把 primer 误判成串题;
    (b) 人能一眼看出哪些题需要"先说两句再问"。
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    per_task = out_dir / "per_task"
    per_task.mkdir(parents=True, exist_ok=True)

    primers: dict[str, list[dict]] = {}
    no_ctx: set[str] = set()
    if primers_path is not None:
        primers, no_ctx = load_primers(primers_path)

    for it in items:
        # 一个文件一句话: 粘贴面最小化, 杜绝"整段 YAML 一起复制"的手滑
        (per_task / f"{it['id']}.txt").write_text(it["utterance"] + "\n", encoding="utf-8")

    primed: list[str] = []
    if primers:
        ctx_dir = out_dir / "context"
        ctx_dir.mkdir(parents=True, exist_ok=True)
        for tid, spec in primers.items():
            turns = (spec or {}).get("turns") or []
            lines = [f"# {tid} 上下文前缀 (先发这段, 再发 per_task/{tid}.txt 的原话)"]
            for t in turns:
                role = str(t.get("role", "user"))
                lines.append(f"[{role}] {t.get('text', '')}")
            (ctx_dir / f"{tid}.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
            primed.append(tid)

    # 单文件题卷: 28 条题面一册, 跑批时照着逐块复制 (只含题面, 答案仍锁在标注里)
    (out_dir / "TASKS.md").write_text(render_tasks_md(items, primers, no_ctx), encoding="utf-8")

    jsonl = "\n".join(json.dumps(it, ensure_ascii=False) for it in items) + "\n"
    (out_dir / "prompts.jsonl").write_text(jsonl, encoding="utf-8")

    schema_hash = _sha256_file(schema_path) if schema_path.is_file() else "MISSING"

    manifest: dict[str, Any] = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "n_tasks": len(items),
        "tasks_path": str(tasks_path),
        "tools_schema_path": str(schema_path),
        "tools_schema_hash": schema_hash,
        # 以下三个**由人填**: 本件不知道被测模型是谁, 编造即失真 (E1 §1 要求逐批记录)
        "model_id": "FILL-ME",
        "system_prompt_version": "FILL-ME",
        "network": "FILL-ME",
        "utterance_fingerprints": {it["id"]: _sha256(it["utterance"]) for it in items},
        # 上下文前缀台账: 哪些题补了上文, 哪些题**故意不补** —— 后者与前者同等重要,
        # 报告解读时据此判断 clarify/reject 题有没有被"喂饱"
        "context_primed": sorted(primed),
        "context_forbidden": sorted(no_ctx),
        # 警示语故意**不写字段名** (expect_tools 等): check_leakage 按字段名原文
        # 判定泄漏, 写在这里会让自检器把警示语本身当成泄漏物报出来。
        "isolation_note": (
            "本包只含题号与用户原话 (白名单提取)。标注里的期望轨迹、错法清单、澄清选项、"
            "拒绝理由、溯源命令等任何判分依据进入模型上下文, 都属答案泄漏, 该批分数作废。"
        ),
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    # system prompt 模板: 留空给人填, 填完连同版本号回填 manifest
    (out_dir / "system_prompt.txt").write_text(
        "# 在此填写本次跑批的 system prompt (全文), 并与 manifest.system_prompt_version 对齐。\n"
        "# 注意: prompt 里不得出现任何题目的答案提示 (应选哪个工具/半径换算成多少/要不要先问用户)。\n"
        f"# 本次工具 schema: {schema_path.name} @ {schema_hash}\n",
        encoding="utf-8",
    )
    return manifest


def selfcheck(out_dir: Path) -> list[str]:
    """产出自检: 扫全部产出文件, 命中答案字段名即 fail-closed。

    为什么生成完还要自检: 白名单提取本身已足够, 但人会在 per_task/*.txt 之外
    往目录里塞自己的东西 (比如备忘粘贴), 自检把"包整体"而不是"生成器"当对象。
    """
    hits: list[str] = []
    for path in sorted(out_dir.rglob("*")):
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        # manifest.isolation_note 与 system_prompt 模板本身会提到这些键名 (是警示语), 跳过它们
        if path.name in ("manifest.json", "system_prompt.txt"):
            continue
        low = text.lower()
        for key in ANSWER_KEYS:
            if key.lower() in low:
                hits.append(f"{path.relative_to(out_dir)}: 出现答案字段 '{key}'")
    return hits


def main() -> int:
    ap = argparse.ArgumentParser(description="生成 E1 跑批输入包 (只含用户原话, 答案全剥离)")
    ap.add_argument("--tasks", default=str(TASKS_PATH), help="标注文件 (默认 tasks.yaml)")
    ap.add_argument("--out", default=str(DEFAULT_OUT), help="产出目录 (默认 temp/nl2tool/batch_input)")
    ap.add_argument("--schema", default=str(SCHEMA_PATH), help="工具 schema 路径 (用于算版本 hash)")
    ap.add_argument("--with-primers", action="store_true",
                    help="一并生成上下文前缀 (给『刚才那片天区』这类续接题补上文; "
                         "no_context 清单里的题永不补)")
    ap.add_argument("--tasks-md", default=str(TASKS_MD_PATH),
                    help=f"单文件题卷落点 (默认 {TASKS_MD_PATH}; 传空字符串则不另存)")
    args = ap.parse_args()

    items = load_utterances(Path(args.tasks))
    out_dir = Path(args.out)
    manifest = write_bundle(items, out_dir, Path(args.schema), Path(args.tasks),
                            PRIMERS_PATH if args.with_primers else None)

    hits = selfcheck(out_dir)
    if hits:
        print("[FAIL] 跑批输入包自检未通过 — 产出里残留答案字段, 本批不得用于评测:", file=sys.stderr)
        for h in hits:
            print(f"  - {h}", file=sys.stderr)
        return 1

    # 题卷另存一份到 evals/nl2tool/ (与 REPORT.md 同址, 随仓入库): 跑批的人打开它
    # 就能照着复制, 不必去翻 26 个 per_task 文件, 更不必去开 tasks.yaml。
    if args.tasks_md:
        md_path = Path(args.tasks_md)
        md_path.write_text((out_dir / "TASKS.md").read_text(encoding="utf-8"), encoding="utf-8")

    print(f"[OK] 跑批输入包已生成: {out_dir}")
    print(f"     任务数 {manifest['n_tasks']} · 工具 schema hash {manifest['tools_schema_hash']}")
    print(f"     单文件题卷: {args.tasks_md or out_dir / 'TASKS.md'} (28 条题面一册, 逐块复制)")
    print(f"     单题纯文本: {out_dir / 'per_task'}/NL2T-nn.txt (一文件一句话, 直接粘贴)")
    if manifest.get("context_primed"):
        print(f"     上下文前缀: {out_dir / 'context'}/ ({len(manifest['context_primed'])} 条续接题, "
              f"先发前缀再发原话)")
        print(f"     故意不补上文: {', '.join(manifest['context_forbidden'])} — 这几题缺指代就是考点")
    print(f"     待填字段: manifest.json 的 model_id / system_prompt_version / network")
    print("[提醒] 一题一个新会话, 三条 convert 题不要连着问 (NL2T-10/11/12 会互相教答案)。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
