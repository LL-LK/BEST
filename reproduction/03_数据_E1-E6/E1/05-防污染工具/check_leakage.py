# -*- coding: utf-8 -*-
"""evals.nl2tool.check_leakage — E1 答案泄漏自检 (跑批前必跑的一道闸)。

为什么需要它: ``make_batch_input.py`` 保证**生成器**的产出干净, 但保证不了
**人最终喂给模型的东西**干净 —— 人会在输入框里顺手贴上"这条是 convert 题,
注意单位"、"上一轮它答错了, 让它再想想", 甚至把整段 YAML 粘进去。生成器
管不到剪贴板。本件把检查对象从"生成器"换成"实际文本", 补上这一段。

查三类污染, 按危害排序:

1. **答案串泄漏** (ERROR): 文本里出现 ``expect_tools`` / ``anti_patterns`` 等
   标注字段名, 或出现 anti_patterns 里的赋值式指纹 (如 ``radius_arcsec = 5/3600``)。
   这类一旦出现, 该题分数直接作废 —— 模型是照着答案抄的。
2. **串题污染** (ERROR): 某题的输入里混进了**别的题的用户原话**。典型是图省事把
   28 条一次性粘进同一个对话: NL2T-10 (角分→300) 教会模型换算, NL2T-12 (度→1800)
   顺势做对, UnitAcc 看着是 1.0, 实际是抄的。
3. **弱信号** (WARN, 不阻断但要点名): ``category``/``route`` 的值字面出现 (如写
   "这条该 clarify"), 或把金标准轨迹 (``golden-from-annotation``) 当输入喂了。

能力边界: 只读不写, 不联网、不调大模型、不改标注。判定是**子串匹配**, 不是
语义理解 —— 它能抓住"粘了原文", 抓不住"用自己的话把答案复述了一遍"。后者
只能靠 §9 的人工纪律 (不看答案、不引导、不复述)。

白盒锚点: docs/eval-E1-nl2tool.md §9 (标注流程与防污染) / §6.3 (转换三项 S1 口径)。
"""
from __future__ import annotations

# 标准库: 参数解析 / 正则 (指纹抽取) / 路径锚定 / 题号识别 / 类型标注
import argparse
import re
import sys
from pathlib import Path
from typing import Iterable

_HERE = Path(__file__).resolve()
sys.path.insert(0, str(_HERE.parents[1]))   # evals/
sys.path.insert(0, str(_HERE.parents[2]))   # skill 根

from paths import load_yaml_file  # noqa: E402

NL2TOOL_DIR = Path(__file__).resolve().parent
TASKS_PATH = NL2TOOL_DIR / "tasks.yaml"

# 7 个原子工具名是**合法工具面**, 出现在输入里不算泄漏 (模型本来就该知道工具有哪些)。
# 不排除的话, anti_patterns 里凡是提到工具名的条目都会误报, 自检就没人信了。
TOOL_NAMES = frozenset({
    "resolve_name", "list_catalogs", "describe_catalog", "cone_search",
    "crossmatch_batch", "count", "fetch_page",
})

# 答案字段名: 命中即判定"YAML 原文进上下文了"
ANSWER_KEYS = (
    "expect_tools", "expect_tools_after_clarify", "anti_patterns", "should_call_best",
    "key_fields", "partial_credit", "must_not_call", "reason_code",
    "verify_cmd", "verify:", "anchor:", "probes:",
)

# 赋值式指纹的抽取规则: anti_patterns 里最有价值的泄漏物是"写成什么样算错"的
# 具体表达式, 形如 `radius_arcsec = 5/3600` / `catalog = 'std'`。整句中文太长、
# 漏抄一半就匹配不上, 而这类赋值串即使只漏进来一半也足以泄题。
ASSIGN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_.]*\s*=\s*[^\s,，。;；(（]{1,40}")

# 题号识别: 文件名或路径里出现 NL2T-nn 即归属该题 (用于串题检测)
TASK_ID_RE = re.compile(r"NL2T-\d{2}")

# 元文件豁免: 本件与生成器的源码、以及生成器产出的 manifest/模板, 内容里都含
# 字段名或路由词 (是警示语不是泄漏物), 扫到自己头上会永远红, 必须跳过。
META_FILES = ("check_leakage.py", "make_batch_input.py", "manifest.json", "system_prompt.txt")

# 串题检测豁免名单: 这些文件**天然**含多条题目的原话, 但都不是污染 ——
#   * prompts.jsonl 是 28 条的总索引, 不是"喂给模型的一段输入";
#   * TASKS.md 是给人照着跑的**题卷** (28 条一册), 抬头明写"一次只复制一个题块"。
#     它是索引而非输入 —— 但正因它把 28 条摆在一起, 一旦有人整份粘进会话就是
#     最典型的串题, 所以豁免它的同时必须由单测钉住"警示语还在" (见
#     tests/test_isolation.py::TestTasksSheet), 否则豁免就成了永久的口子;
#   * context/ 下是上下文前缀, 它刻意复用别题原话 (NL2T-10「刚才那片天区」的上文
#     就是 NL2T-04 的题面) —— 这是**有意且受控**的补充, 由 context_primers.yaml
#     逐条声明, 与"28 条一股脑灌进同一会话"是两回事。
# 一律判红会让每次自检都假红, 假红一多人就不跑自检了, 反而更不安全。
# 注意豁免范围**只限串题一项**: 答案串检测照做不误 (粘一段标注进索引同样被抓)。
CROSS_EXEMPT_FILES = ("prompts.jsonl", "TASKS.md")
CROSS_EXEMPT_DIRS = ("context",)


# ── 模型可见根目录的黑名单 (§9.2: 哪些文件压根不该出现在模型的视野里) ─────────
# 上面三个常量管的是"一段文本脏不脏", 这一段管的是另一件事: **模型能看到的整个
# 目录里有没有答案**。人最容易忽略的恰恰是后者 —— 给被测模型挂载了整个仓库/整个
# skill 目录, 于是它一个 grep 就能读到标注。下面每条都写清"为什么不能看",
# 因为黑名单一旦没有理由, 下一次就会被人以"这个文件应该没事"为由逐条放行。
BLOCKED_PATHS = (
    ("evals", "整个评测目录: E1–E6 全是标注与判分器, 一条都不该给模型"),
    # 2026-10-07: 题卷由 26 条增至 28 条 (新增 NL2T-27/NL2T-28), 理由文案同步。
    # 本表是**描述性理由**, 不参与答案指纹匹配 (指纹由 build_answer_fingerprints
    # 从标注动态生成), 所以改这里不会让自检自撞 —— 改完重新生成 TASKS.md 即可。
    ("evals/nl2tool/tasks.yaml", "28 条标注原文: 期望工具 / 错法清单 / 澄清选项 / 拒绝理由"),
    ("evals/nl2tool/context_primers.yaml", "bindings 段是占位符具化值 (= 坐标答案); 只有 turns 段可喂"),
    ("evals/nl2tool/traces", "golden = 满分合成轨迹; live-m3 = 上一批模型的真实回答"),
    # 理由里**不许出现答案串本身**: 早先这条写成了"如 radius_arcsec = 60/3600",
    # 于是黑名单自己就成了泄漏源 (自检当场抓到) —— 描述答案的**位置**即可。
    ("evals/nl2tool/graders.py", "判据与逐题澄清探测词 —— 关键词表本身就是答案"),
    ("evals/nl2tool/gen_golden.py", "按标注合成满分轨迹, 等于答案生成器"),
    ("evals/nl2tool/runner.py", "判分与门禁逻辑, 含通过线与红线口径"),
    ("evals/nl2tool/normalizers.py", "归一化判据 (什么算'同一个参数')"),
    ("evals/nl2tool/REPORT.md", "逐维得分与红线清单 = 直接告诉模型哪题错了"),
    ("evals/nl2tool/live-2026-10-04.json", "历史跑批原始结果 (含逐条轨迹与判定) —— 属 M3 批次，2026-10-11 已移出仓库；此条保留以拦截同名残留"),
    ("evals/nl2tool/tests", "单测内联期望工具与答案指纹"),
    ("evals/nl2tool/broken", "反证夹具 (坏样本本身就是'错法示范')"),
    ("docs/eval-E1-nl2tool.md", "§5 是 28 题的完整答案表: 题面 + 期望调用 + 坑位, 一眼看全"),
    ("docs/EVAL-LIVE-RUN-2026-10-04.md", "逐题错法诊断, 还含一条满分回答原文 (NL2T-20)"),
    ("docs/architecture/naming-alignment-record.md", "点名 NL2T-22 的'头号 S1 陷阱'"),
    ("CHANGELOG.md", "变更记录里引用了具体题号与答案指纹 (描述答案原样照搬, 位置见各条)"),
)

# 白名单: 模型**可以**看到的 skill 正文 (被测对象本体 + 它本该知道的工具面)。
# 列出来是为了让体检输出能直接告诉人"该给的是这些", 而不只是"不许给那些"。
ALLOWED_IN_MODEL_ROOT = (
    "SKILL.md", "README.md", "manifest.yaml", "architecture.md",
    "contracts/", "static/", "references/", "src/", "agents/", "templates/", "rag/",
)


def scan_model_root(root: Path) -> list[str]:
    """体检模型可见根目录: 命中黑名单即返回问题清单 (空列表 = 干净)。

    ``evals`` 目录命中时**不再逐条重复报**里面的文件 —— 一次报一行"整个目录不该在",
    比刷 12 行更容易让人照做; 只有 evals/ 不在但个别文件被单独拷出来时才逐条点名。
    """
    hits: list[str] = []
    evals_hit = (root / "evals").exists()
    for rel, why in BLOCKED_PATHS:
        if evals_hit and rel.startswith("evals"):               # 目录级已报, 跳过其下逐条
            continue
        if (root / rel).exists():
            hits.append(f"{rel} — {why}")
    if evals_hit:
        hits.insert(0, "evals/ — 整个评测目录 (E1–E6 标注、判分器、轨迹) 不该出现在模型视野里")
    return hits


def load_tasks(tasks_path: Path) -> list[dict]:
    """装载标注 (结构容错同 runner: 裸 list 或 {tasks: [...]} 都收)。"""
    raw = load_yaml_file(tasks_path)
    tasks = raw.get("tasks", raw) if isinstance(raw, dict) else raw
    return [t for t in tasks if isinstance(t, dict)] if isinstance(tasks, list) else []


def build_answer_fingerprints(tasks: list[dict]) -> list[tuple[str, str]]:
    """从标注抽取答案指纹 → [(指纹串, 出自哪条任务)]。

    只取**赋值式**与**理由码**两类硬指纹。中文整句不取: 太长, 漏一段就匹配不上,
    且"忘记换算"这类描述性文字命中了也可能是人在讨论别的, 信噪比低。
    """
    fps: list[tuple[str, str]] = []
    for t in tasks:
        tid = str(t.get("id", "?"))
        for ap in t.get("anti_patterns") or []:
            pattern = str(ap.get("pattern", "")) if isinstance(ap, dict) else str(ap)
            for m in ASSIGN_RE.findall(pattern):
                token = m.strip().rstrip("）)")
                # 纯工具名 (如 "catalog = ps1" 里的 ps1 不是, 但 "tool = cone_search" 这种) 不算
                if token.split("=")[0].strip() in TOOL_NAMES:
                    continue
                if len(token) >= 8:
                    fps.append((token, tid))
        rc = (t.get("reject") or {}).get("reason_code") if isinstance(t.get("reject"), dict) else None
        if rc and str(rc).upper() not in ("NONE", "NULL"):
            fps.append((str(rc), tid))
    # 去重保序: 同一指纹多条题共用时只报一次
    seen: set[str] = set()
    uniq: list[tuple[str, str]] = []
    for fp, tid in fps:
        if fp not in seen:
            seen.add(fp)
            uniq.append((fp, tid))
    return uniq


def build_utterance_index(tasks: list[dict]) -> dict[str, str]:
    """题号 → 用户原话。用于串题检测 (别题原话出现在本题输入里 = 串题)。"""
    return {
        str(t["id"]): str(t.get("utterance", "")).strip()
        for t in tasks if t.get("id") and len(str(t.get("utterance", ""))) >= 8
    }


def scan_text(text: str, owner: str, fps: list[tuple[str, str]], utts: dict[str, str],
              skip_cross: bool = False) -> tuple[list[str], list[str]]:
    """扫一段文本, 返回 (errors, warns)。owner = 该文件归属题号 (空串表示未知)。

    ``skip_cross=True`` 关闭串题检测 (总索引文件专用): 索引天然含全部原话,
    但答案串检测照做 —— 粘一段标注进索引同样会被抓。
    """
    errors: list[str] = []
    warns: list[str] = []
    low = text.lower()

    for key in ANSWER_KEYS:
        if key.lower() in low:
            errors.append(f"答案字段名 '{key}' 出现在输入里 — 标注原文进了模型上下文")

    for fp, src in fps:
        if fp.lower() in low:
            errors.append(f"答案指纹 '{fp}' (出自 {src} 的 anti_patterns/reject) 出现在输入里")

    if skip_cross:
        pass
    elif owner:
        for tid, utt in utts.items():
            if tid == owner:
                continue
            if utt in text:
                errors.append(f"串题: 本题 {owner} 的输入里混进了 {tid} 的用户原话 — 28 条必须一题一会话")
    else:
        # 归属未知时退化成"数有几条原话": ≥2 条即高度疑似一次性灌了多题
        hit = [tid for tid, utt in utts.items() if utt in text]
        if len(hit) >= 2:
            errors.append(
                f"串题: 单个输入里出现 {len(hit)} 条题目的原话 ({', '.join(sorted(hit)[:5])}…) "
                f"— 一题一会话是硬要求"
            )

    if "golden-from-annotation" in low:
        warns.append("输入里出现 'golden-from-annotation' — 是否把金标准轨迹当成了跑批输入?")
    for word in ("route: clarify", "route: reject", "category: convert", "category: clarify",
                 "该澄清", "该拒绝", "这条是 convert"):
        if word in low:
            warns.append(f"弱信号: 输入里出现 '{word}' — 等于直接告诉模型该怎么路由")
    return errors, warns


def iter_files(target: Path) -> Iterable[Path]:
    """收集待检文件: 目录递归 (跳过本件与生成器自身), 单文件即它自己。"""
    if target.is_file():
        yield target
        return
    for p in sorted(target.rglob("*")):
        if not p.is_file() or p.name in META_FILES:
            continue
        if "traces" in p.parts:      # 轨迹是判分输入, 不是跑批输入, 不参与本检
            continue
        yield p


def main() -> int:
    ap = argparse.ArgumentParser(description="E1 答案泄漏自检 (扫实际喂给模型的文本)")
    ap.add_argument("--dir", help="待检目录 (如跑批输入包)")
    ap.add_argument("--file", help="待检单文件 (如准备粘贴的 prompt 文本)")
    ap.add_argument("--model-root",
                    help="体检模型可见根目录 (被测模型能读到哪一层就指哪一层): "
                         "命中黑名单即 exit 1 —— 大模型有文件读取能力时, "
                         "不给它看比求它不看重看更可靠")
    ap.add_argument("--tasks", default=str(TASKS_PATH), help="标注文件路径")
    args = ap.parse_args()

    if args.model_root:                                         # 目录体检模式: 与文本扫描互斥
        root = Path(args.model_root)
        if not root.is_dir():
            raise SystemExit(f"不是目录: {root}")
        hits = scan_model_root(root)
        print(f"模型可见根目录: {root}")
        if hits:
            print(f"\n[FAIL] {len(hits)} 项不该出现在模型视野里 (模型有文件读取能力即等于开卷):",
                  file=sys.stderr)
            for h in hits:
                print(f"  ✗ {h}", file=sys.stderr)
            return 1
        print("[OK] 该目录不含评测标注与判分器 — 可放心让模型看到。")
        print(f"     允许可见: {', '.join(ALLOWED_IN_MODEL_ROOT)}")
        print("     仍须守住: 被测模型侧不挂载仓库文件读取 / grep / 检索能力。")
        return 0

    if not args.dir and not args.file:
        ap.error("须给 --dir / --file / --model-root 之一")
    target = Path(args.file) if args.file else Path(args.dir)
    if not target.exists():
        raise SystemExit(f"路径不存在: {target}")

    tasks = load_tasks(Path(args.tasks))
    fps = build_answer_fingerprints(tasks)
    utts = build_utterance_index(tasks)

    n_files = 0
    all_errors: list[str] = []
    all_warns: list[str] = []
    for path in iter_files(target):
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if not text.strip():
            continue
        n_files += 1
        m = TASK_ID_RE.search(path.name) or TASK_ID_RE.search(str(path))
        owner = m.group(0) if m else ""
        skip_cross = path.name in CROSS_EXEMPT_FILES or path.parent.name in CROSS_EXEMPT_DIRS
        errs, warns = scan_text(text, owner, fps, utts, skip_cross=skip_cross)
        for e in errs:
            all_errors.append(f"[{path.name}] {e}")
        for w in warns:
            all_warns.append(f"[{path.name}] {w}")

    print(f"待检文件 {n_files} 个 · 答案指纹 {len(fps)} 条 · 题目原话 {len(utts)} 条")

    if all_errors:
        print(f"\n[FAIL] 检出 {len(all_errors)} 处答案泄漏 — 本批跑完也不作数, 先清干净:", file=sys.stderr)
        for e in all_errors:
            print(f"  ✗ {e}", file=sys.stderr)
    if all_warns:
        print(f"\n[WARN] {len(all_warns)} 处弱信号 (不阻断, 但请确认):", file=sys.stderr)
        for w in all_warns:
            print(f"  ! {w}", file=sys.stderr)

    if all_errors:
        return 1
    print("\n[OK] 未检出答案泄漏 — 该输入包可用于跑批。")
    print("     仍须守住两条机器查不出的纪律: 一题一会话; 不向模型复述答案/提示路由。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
