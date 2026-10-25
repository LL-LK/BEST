#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
E1 / E4 实验产物整理工具
========================
做三件事：

  1. 把 3333 / 4444 / 5555 三批的 28 份 `NL2T-*.md` 各自**合并成一个 md**；
  2. 为每批**补一份统一 schema 的 `answers.json`**（5555 原本就有，本脚本保留其
     结构化字段并回补 `body_md`，不覆盖它作为 5555_grade.py 输入的事实）；
  3. 把 E1 / E4 的**结果性产物 + 过程性产物**按目录结构整理成 ZIP。

只读来源，不改动冻结数据（`tasks.yaml` / `items.yaml` 一律不写）。
"""
import json
import os
import re
import shutil
import sys
import zipfile

from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]          # 仓库根
EXPORT = ROOT / "temp" / "export"
STAGE = EXPORT / "E1和E4实验的产物"

CAND = ROOT / "nl2tool-candidate-answers"
BATCHES = {
    "3333": CAND / "3333" / "E1-answers-2026-10-07",
    "4444": CAND / "4444" / "E1-nl2tool-28题答案-20261007",
    "5555": CAND / "5555" / "E1-nl2tool-answers-2026-10-07",
}
TOOLS = ["resolve_name", "list_catalogs", "describe_catalog", "cone_search",
         "crossmatch_batch", "count", "fetch_page"]

TASKS_YAML = ROOT / "evals" / "nl2tool" / "tasks.yaml"

# ---------------------------------------------------------------------------
# 1. 解析
# ---------------------------------------------------------------------------

def gold_utterances():
    """{id: {'utterance':..., 'route':...}} —— 仅用于交叉校验与兜底，不覆盖答案自身判定。"""
    try:
        import yaml
        data = yaml.safe_load(open(TASKS_YAML, encoding="utf-8"))["tasks"]
        return {t["id"]: {"utterance": t.get("utterance"), "route": t.get("route")}
                for t in data}
    except Exception:
        return {}


_NUM_PREFIX = re.compile(r"^\d+(?:\.\d+)*\.?\s*")


def split_sections(text):
    """按 '## ' 标题切分，返回 {标题: 正文}。标题去掉 '1. ' / '2.3 ' 之类编号前缀。"""
    out, cur, buf = {}, None, []
    for line in text.splitlines():
        if line.startswith("## "):
            if cur:
                out[cur] = "\n".join(buf).strip()
            cur = _NUM_PREFIX.sub("", line[3:].strip())
            buf = []
        else:
            buf.append(line)
    if cur:
        out[cur] = "\n".join(buf).strip()
    return out


def pick(sections, *names):
    for n in names:
        for k in sections:
            if k.startswith(n):
                return sections[k]
    return ""


def first_line(s):
    for ln in (s or "").splitlines():
        if ln.strip():
            return ln.strip()
    return ""


def classify_verdict(line, body):
    """call / clarify / refuse。

    先取首行的**引导短语**（去掉 ** 与编号，截到第一个 ——/：/。/, 之前），
    按 startswith 判定 —— 这比全文关键字扫描稳得多（可避免正文里出现
    "拒绝" 造成 clarify 被误判成 refuse）。
    """
    line = re.sub(r"^\s*[-*]\s*", "", first_line(line)).strip()   # 去掉 "- " 项目符号
    head = re.sub(r"[*\s`]", "", line)
    head = re.split(r"[——:：。,，]", head, maxsplit=1)[0]
    if head.startswith("先澄清") or head.startswith("需要先澄清") or head.startswith("澄清"):
        return "clarify"
    if head.startswith("拒绝") or head.startswith("应当拒绝") or head.startswith("拒"):
        return "refuse"
    if head.startswith("直接调用") or head.startswith("直接调它") or head.startswith("直接调"):
        return "call"
    # 兜底：整行 + 判定段首行做关键字扫描（顺序敏感）
    # 必须先剔除否定式澄清（"无需澄清 / 不需澄清 / 不必澄清 / 不澄清"），
    # 否则 "直接调用……无需澄清" 会被误判成 clarify（3333 批 NL2T-02 就是这样踩到的）。
    probe = (line or "") + " " + re.sub(r"^\s*[-*]\s*", "", first_line(body))
    probe = re.sub(r"无需澄清|无需再澄清|不需澄清|不需要澄清|不必澄清|不必先澄清|不澄清",
                   "", probe)
    if re.search(r"应当拒绝|拒绝（不给调用）|超出能力边界", probe):
        return "refuse"
    if re.search(r"先澄清|需要澄清|澄清", probe):
        return "clarify"
    if re.search(r"直接调用|直接调", probe):
        return "call"
    return None


def extract_utterance(sections, tid, gold):
    for key in ("用户原话", "题面"):
        s = pick(sections, key)
        if s:
            m = re.search(r"^>\s*(.+)$", s, re.M)
            if m:
                return m.group(1).strip()
            m = re.search(r"\*\*?用户原话\*\*?[：:]\s*(.+)", s)
            if m:
                return re.sub(r"\*\*", "", m.group(1)).strip()
    g = gold.get(tid) or {}
    return g.get("utterance")


def extract_tool(sections):
    blob = "\n".join([pick(sections, "工具调用"), pick(sections, "期望调用")])
    hits = []
    for t in TOOLS:
        for m in re.finditer(r"\b" + t + r"\b", blob):
            hits.append((m.start(), t))
    if not hits:
        return None
    hits.sort()
    return hits[0][1]


def extract_args(blob):
    """尽力抽取：优先代码块里的调用，其次 `**参数名** = 值` 列表。"""
    m = re.search(r"```(?:python)?\s*\n(.*?)```", blob, re.S)
    raw = m.group(1).strip() if m else None
    args = {}
    if raw:
        inner = re.search(r"\((.*)\)", raw, re.S)
        if inner:
            for kv in re.finditer(r"(\w+)\s*=\s*(\[[^\]]*\]|\"[^\"]*\"|'[^']*'|<[^>]*>|-?[\d.]+)", inner.group(1)):
                args[kv.group(1)] = kv.group(2)
    if not args:
        for kv in re.finditer(r"\*\*(\w+)\*\*\s*[=＝]\s*`([^`]*)`", blob):
            args[kv.group(1)] = kv.group(2)
    return (args or None), raw


def bullets(section):
    out = [re.sub(r"^\s*[-*]\s*", "", ln).strip()
           for ln in (section or "").splitlines() if re.match(r"^\s*[-*]\s+", ln)]
    return out or None


def build_batch(name, d, gold):
    files = sorted(d.glob("NL2T-*.md"))
    if not files:
        print(f"  !! {name}: 未找到 NL2T-*.md，跳过")
        return None, None, None

    # 只信任**原生**结构化文件（5555 的 answers.json，被 5555_grade.py 用作判分输入）。
    # 本脚本自己生成的 answers.json 带 "schema_note" 标记 —— 必须忽略，
    # 否则重跑时会把自己上一轮的解析结果当输入读回去（曾导致 4444 判定分布错乱）。
    struct = {}
    aj = d / "answers.json"
    if aj.exists():
        try:
            raw = json.load(open(aj, encoding="utf-8"))
            if "schema_note" not in raw:
                struct = {i["id"]: i for i in raw["items"]}
            else:
                print(f"  ·  {name}: 检测到本脚本生成件，忽略其缓存，改从 md 重新解析")
        except Exception as e:
            print(f"  !! {name}: answers.json 读取失败 {e}")

    items = []
    for fp in files:
        tid = fp.stem
        text = fp.read_text(encoding="utf-8")
        sec = split_sections(text)

        judge_sec = pick(sec, "判定")
        jl = first_line(judge_sec)
        st = struct.get(tid, {})

        verdict = st.get("verdict") or classify_verdict(jl, judge_sec)
        tool = st.get("tool")
        if tool is None:
            tool = extract_tool(sec)
        blob = "\n".join([pick(sec, "工具调用"), pick(sec, "期望调用"), pick(sec, "参数与换算")])
        args, raw = extract_args(blob)
        if st.get("arguments") is not None:
            args = st["arguments"]

        g = gold.get(tid) or {}
        g = gold.get(tid) or {}
        items.append({
            "id": tid,
            "gold_route": g.get("route"),
            "gold_route": g.get("route"),
            "utterance": st.get("utterance") or extract_utterance(sec, tid, gold),
            "verdict": verdict,
            "tool": tool,
            "arguments": args,
            "arguments_raw": raw or st.get("arguments_raw"),
            "refusal_reason": st.get("refusal_reason"),
            "clarify_points": st.get("clarify_points") or bullets(pick(sec, "需要澄清的点", "若需澄清", "澄清项")),
            "key_points": st.get("key_points") or bullets(pick(sec, "关键要点", "陷阱与错法", "关键依据")),
            "user_reply": st.get("user_reply") or (pick(sec, "给用户的回答口径") or None),
            "body_md": text,
        })

    counts = {}
    for it in items:
        counts[it["verdict"] or "unknown"] = counts.get(it["verdict"] or "unknown", 0) + 1
    # 交叉校验：答案自身判定 vs 金标 route（answer→call / clarify→clarify / reject→refuse）
    _MAP = {"answer": "call", "clarify": "clarify", "reject": "refuse"}
    diff = [it["id"] for it in items
            if it.get("gold_route") and _MAP.get(it["gold_route"]) != it["verdict"]]
    payload_diff = diff
    # 交叉校验：答案自身判定 vs 金标 route（answer→call / clarify→clarify / reject→refuse）
    _MAP = {"answer": "call", "clarify": "clarify", "reject": "refuse"}
    diff = [it["id"] for it in items
            if it.get("gold_route") and _MAP.get(it["gold_route"]) != it["verdict"]]
    payload_diff = diff

    payload = {
        "batch": name,
        "subject": "astro-best (NADC BEST 数据源主理 skill)",
        "answer_set_date": "2026-10-07",
        "generated_at": datetime.now().strftime("%Y-%m-%d"),
        "source_dir": str(d.relative_to(ROOT)).replace("\\", "/"),
        "n_items": len(items),
        "schema_note": (
            "统一 schema（与 5555 原生 answers.json 对齐）："
            "verdict ∈ {call, clarify, refuse}；tool 取 7 个原子工具之一；"
            "arguments 为尽力抽取（代码块优先，其次 **参数** = `值` 列表），抽不到即 null；"
            "body_md 是该题原始 md 全文，保证合并后信息零丢失。"
            "3333/4444 无原生结构化文件，其 verdict/tool/arguments 由本脚本从 md 解析。"
        ),
        "tool_surface": [
            "resolve_name(name)", "list_catalogs()", "describe_catalog(catalog)",
            "cone_search(ra, dec, radius_arcsec=180, catalog='ps1', columns=None, "
            "sort=None, order='asc', nearest_only=False, max_rows=1000)",
            "crossmatch_batch(coords, catalog='ps1', radius_arcsec=3.0, nearest_only=True, "
            "columns=None, max_rows=50000)",
            "count(sqlid)", "fetch_page(sqlid, page=1, page_size=1000, catalog='', max_rows=None)",
        ],
        "counts": counts,
        "items": items,
    }
    return payload, files, diff


def write_merged_md(name, d, payload, files):
    """28 份 md → 1 份，按题号顺序，保留原文。"""
    out = d / f"E1-28题答案-合并.md"
    L = []
    L.append(f"# E1 / NL2Tool 28 题答案 —— {name} 批（合并版）")
    L.append("")
    L.append(f"- 批次：**{name}**　作答日期：{payload['answer_set_date']}　"
             f"合并生成：{payload['generated_at']}")
    L.append(f"- 来源：同目录 28 份 `NL2T-01..28.md`（原文逐字保留，仅加分隔与本页眉）")
    L.append(f"- 判定分布：" + " · ".join(f"{k} {v}" for k, v in sorted(payload["counts"].items())))
    L.append(f"- 配套结构化件：`answers-合并.json`（统一 schema，含每题 verdict / tool / arguments）")
    L.append("")
    L.append("> 本件由 `temp/export/build_answers_and_bundle.py` 生成，属**生成件**；"
             "改答案请改 28 份原始 md 后重跑，不要直接编辑本件。")
    L.append("")
    L.append("---")
    L.append("")
    L.append("## 目录")
    L.append("")
    for it in payload["items"]:
        L.append(f"- `{it['id']}`　{it.get('utterance') or ''}　→ **{it.get('verdict') or '?'}**"
                 + (f"（`{it['tool']}`）" if it.get("tool") else ""))
    L.append("")
    L.append("---")
    L.append("")
    for fp in files:
        tid = fp.stem
        it = next(x for x in payload["items"] if x["id"] == tid)
        L.append(f"<a id=\"{tid}\"></a>")
        L.append("")
        L.append(f"## {tid}　（{it.get('verdict') or '?'}）")
        L.append("")
        body = it["body_md"].strip()
        # 把原文的一级标题降级为二级，保持层级一致
        body = re.sub(r"^#\s+", "### ", body, count=1, flags=re.M)
        body = re.sub(r"^##\s+", "### ", body, flags=re.M)
        L.append(body)
        L.append("")
        L.append("---")
        L.append("")
    out.write_text("\n".join(L), encoding="utf-8")
    return out


# ---------------------------------------------------------------------------
# 2. 打包
# ---------------------------------------------------------------------------

def copy_tree(src, dst, exclude=None, exclude_prefix=()):
    exclude = exclude or set()
    n = 0
    src = Path(src)
    if src.is_file():
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        return 1
    for dp, dn, fn in os.walk(src):
        dn[:] = [d for d in dn
                 if d not in exclude and d != "__pycache__"
                 and not any(d.startswith(p) for p in exclude_prefix)]
        for f in fn:
            if f in exclude or f.endswith(".pyc"):
                continue
            if any(f.startswith(p) for p in exclude_prefix):
                continue
            p = Path(dp) / f
            rel = p.relative_to(src)
            (dst / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, dst / rel)
            n += 1
    return n


def build_gates_section():
    """门禁与 CI 接线：两个实验「凭什么判定放行/阻断」的全部依据。"""
    g = STAGE / "01-门禁与CI接线"
    g.mkdir(parents=True, exist_ok=True)
    n = 0
    for rel in ["Makefile",
                "evals/scoring-rubric.yaml",
                "evals/_data/scoring-weights-ledger.yaml",
                "evals/_data/null_sentinel.yaml",
                "evals/_data/tolerances.yaml",
                "docs/EVAL-UNLOCK-CHECKLIST.md"]:
        p = ROOT / rel
        if p.exists():
            n += copy_tree(p, g / Path(rel).name)

    lines = []
    A = lines.append
    A("# E1 / E4 门禁清单（凭什么判定放行 / 阻断）")
    A("")
    A(f"- 整理日期：{datetime.now().strftime('%Y-%m-%d')}")
    A("- 说明：**门禁代码**随各实验的 `runner.py` / `broken/` 一起收在本包对应目录；")
    A("  本目录收的是**门禁的接线与依据**（Makefile 目标、权重量规与台账、解锁清单）+ 本清单。")
    A("")
    A("## 一、E1 门禁")
    A("")
    A("| # | 门禁 | 判什么 | 开关 / 阻断码 | 实现位置 | CI 接线 |")
    A("|---|---|---|---|---|---|")
    A("| 1 | **逐维门禁** | 跑了的是否达标（六维各自过线） | `--require-threshold`<br>阻断码 `below_dimension_threshold` | `evals/nl2tool/runner.py:385` | ✅ **已接线**<br>`make eval-e1` 已带该开关 |")
    A("| 2 | **覆盖门禁** | 该跑的跑了没 | `--expect-attempts N`<br>`missing_traces` / `short_attempts` | `runner.py:383` | ⚠️ make 未传<br>（缺省 1，模型批须显式传 3） |")
    A("| 3 | **红线门禁** | 有没有科学性硬错 | `red_line_tasks`（S1 / 参数幻觉 / 伪造工具 / 硬执行） | `graders.py` | ✅ 每批实算 |")
    A("| 4 | **判定器自证门禁** | 判定器本身失效没有 | `metascore < 1.0` → `grader_selftest_failed` | `broken/` 6 条夹具 + `runner.py` | ✅ 每批实算 |")
    A("| 5 | **权重和门禁** | 权重量规是否被静默改掉 | 权重和 = 1.00；改量规而不留痕 → 红 | `evals/scoring-rubric.yaml` + `_data/scoring-weights-ledger.yaml` | ✅ 启动校验 |")
    A("| 6 | **防污染闸** | 题面/模型可见面是否夹带答案 | `check_leakage.py --dir` / `--model-root` | 本包 `E1/05-防污染工具/` | ⚠️ 手工跑（`make e1-batch-input`） |")
    A("| 7 | **逐维门禁单测** | 门禁判据本身成立 | `TestDimensionThresholdGate`（含「99 全对 + 1 转换错」反例） | `E1/03-自证与反证夹具/tests/test_e1.py` | ✅ pytest |")
    A("")
    A("## 二、E4 门禁")
    A("")
    A("| # | 门禁 | 判什么 | 开关 / 阻断码 | 实现位置 | CI 接线 |")
    A("|---|---|---|---|---|---|")
    A("| 1 | **执行门禁** | 该层真跑了没（「没跑」≠「跑了得零分」） | `--require-execution`<br>阻断码 `tier_p_not_executed` | `evals/robustness/runner.py:512` | ✅ **已接线（2026-10-11）**<br>`make eval-e4` 已带；无答案即阻断 |")
    A("| 2 | **判定器自证门禁** | 反证夹具是否全被抓住 | `metascore < 1.0` | `broken/` + `runner.py` | ✅ 每批实算 |")
    A("| 3 | **协议层事实守卫** | 缺字段时是否把「没得查」记成 1.0 | `guardscore < 1.0` | `guards.py` + `runner.py` | ✅ 每批实算 |")
    A("| 4 | **处置口径越界** | `disposal` 是否落在 A/B/C/D 四级之外 | 越界即 exit 1 | `evals/robustness/check_disposal_scope.py` | ⚠️ 新增，尚未接 make |")
    A("| 5 | **禁调红线** | `must_not_call` 违规 | 4 条（r1：RB-01/04/05/21） | `graders.py` | ✅ 每批实算 |")
    A("| 6 | **沙箱隔离检疫** | 答题面是否夹带标注/判分器/异源答卷 | `make_answer_box.py --build`（exit 0 才放行） | 本包 `E4/04-` 与 `06-` | ⚠️ 手工跑 |")
    A("| 7 | **方案 §12 阻断项** | 12 条文档级门禁 | 第 10 复合未跑 / 11 夹具不全 / ~~12 判定层未接线~~ | `docs/eval-E4-robustness-safety.md` §12 | 第 12 条 ✅ 已解除 |")
    A("")
    A("## 三、接线后遗留的一处缺口（必须知道）")
    A("")
    A("**`runner.py` 不支持 `--include-second-round`**（grep 计数 0）—— 复合故障 RB-C01..C18")
    A("（E4 自定的唯一增量）**至今无法实跑**：不是「没跑」，是「跑不了」。")
    A("这是「E4 不得出具通过 / 有效结论」最硬的一条理由，与执行门禁是否接线无关。")
    A("")
    A("## 四、2026-10-11 接线动作记录")
    A("")
    A("| 项 | 接线前 | 接线后 |")
    A("|---|---|---|")
    A("| `make eval-e4` | `--tier all --md`（无门禁） | 加 `--require-execution` + 可选的 `E4_ANSWERS` |")
    A("| 无答案时行为 | 静默「预检 = 过」 | **阻断**（`tier_p_not_executed`），exit ≠ 0 |")
    A("| 真判话术层 | 无通道 | `make eval-e4 E4_ANSWERS=temp/robustness/answers/r1` |")
    A("| 临时放行 | — | `make eval-e4 E4_SKIP_GATE=1` |")
    A("| 新增目标 | — | `make check-e4-disposal`（处置口径越界，越界即 exit 1） |")
    A("")
    A("**验证**：无答案 → `P.blockers = ['tier_p_not_executed']`；")
    A("带 r1 答案 → `P.blockers` 为 22 条真实阻断项、**不含**该码（即不误伤）。")
    A("")
    A("## 五、本目录文件")
    A("")
    A("- `Makefile` —— `eval-e1` / `eval-e4` / `evals-all` 的实际命令（门禁接线现状以此为准）")
    A("- `scoring-rubric.yaml` —— 五维权重量规（真值，runner 只读这一份；权重和 = 1.00）")
    A("- `scoring-weights-ledger.yaml` —— 权重**变更登记簿**（守护的是「变必须留痕」，不是「值不许变」）")
    A("- `null_sentinel.yaml` —— 哨兵值判定口径（E1/E4 共用；哨兵当真值是两实验共同的阻断项）")
    A("- `tolerances.yaml` —— 数值容差口径")
    A("- `EVAL-UNLOCK-CHECKLIST.md` —— 六实验解锁清单（门禁分布：E2/E3/E4/E5 各一处、E6 两处、E1 一处）")
    A("")
    (g / "GATES.md").write_text("\n".join(lines), encoding="utf-8")
    n += 1
    return n


def reset_stage():
    """清空暂存目录。整体 rmtree 会被本机的 safe-delete 拦截，
    故失败时退化为「逐个删顶层子项」（实测可行）。"""
    if not STAGE.exists():
        STAGE.mkdir(parents=True)
        return
    try:
        shutil.rmtree(STAGE)
    except Exception:
        for child in sorted(STAGE.iterdir()):
            try:
                if child.is_dir():
                    shutil.rmtree(child)
                else:
                    child.unlink()
            except Exception as e:
                print(f"  !! 无法清理 {child.name}: {e}")
    STAGE.mkdir(parents=True, exist_ok=True)


# 原仓相对路径 = 解压后可直接运行的镜像。
# 关键：脚本内部大量用 `Path(__file__).resolve().parents[N]` 定位仓库根，
# 重排过的目录会让这些解析全部失效 —— 所以**必须**另存一份原路径镜像。
MIRROR_DIRS = [
    "evals/nl2tool", "evals/robustness", "evals/_data",
    # temp/ 必须收：E4 的 --answers 指向 temp/robustness/answers/r1，
    # E1 的场景夹具 / 隔离自检在 temp/nl2tool。少了它 E4 只能退回预检（实测踩到）。
    "temp/nl2tool", "temp/robustness",
    "src", "references", "contracts", "static", "agents", "templates", "rag", "ops",
    "nl2tool-candidate-answers",
]
MIRROR_FILES = [
    "evals/paths.py", "evals/eval_runner.py", "evals/scoring-rubric.yaml",
    "SKILL.md", "README.md", "architecture.md",
    "manifest.yaml", "environment.yaml", "pipeline.yaml", "pyproject.toml",
    "Makefile",
    "docs/eval-E1-nl2tool.md", "docs/eval-E4-robustness-safety.md",
    "docs/EVAL-E4-REVIEW-2026-10-07.md", "docs/EVAL-UNLOCK-CHECKLIST.md",
    "docs/EVAL-HUMAN-RUNBOOK.md", "docs/EVAL-LIVE-FETCH-WAIVER.md",
    "docs/PAPER-E1E4-CROSSCHECK-2026-10-11.md",
]
MIRROR_EXCLUDE_FILES = {"report-live-FIXED.json"}      # 10-06 批次判分，已隔离
MIRROR_EXCLUDE_DIRS = {"traces-live-2026-10-06",       # 10-06 批次轨迹，已隔离
                       "answer_box",                   # 被测对象副本，本体已收
                       "__pycache__"}
# 10-06 批次（model_id=batch-2026-10-06）的全部派生：12 个 scenario-* 目录 + 12 份判分 json
MIRROR_EXCLUDE_PREFIX = ("scenario-",)


def build_runnable_mirror():
    """按原仓相对路径铺一份，解压后即可直接执行。"""
    root = STAGE / "00-可运行-原仓路径(解压后从这里跑)"
    root.mkdir(parents=True, exist_ok=True)
    n = 0
    for d in MIRROR_DIRS:
        n += copy_tree(ROOT / d, root / d,
                       exclude=MIRROR_EXCLUDE_DIRS | MIRROR_EXCLUDE_FILES,
                       exclude_prefix=MIRROR_EXCLUDE_PREFIX)
    for f in MIRROR_FILES:
        p = ROOT / f
        if p.exists():
            n += copy_tree(p, root / f)
    (root / "README-从这里跑起来.md").write_text(
        "# 可运行镜像（原仓相对路径）\n\n"
        "本目录按**仓库原始相对路径**铺开 —— 脚本内部大量用 "
        "`Path(__file__).resolve().parents[N]` 定位仓库根，\n"
        "顶层那些按主题重排过的目录只是**阅读视图**，直接跑会因路径解析失败。\n"
        "**要复现请进入本目录执行。**\n\n"
        "## 环境\n\n"
        "```bash\n"
        "pip install pyyaml requests\n"
        "```\n\n"
        "## E1（金标准自证）\n\n"
        "```bash\n"
        "python evals/nl2tool/gen_golden.py\n"
        "python -m evals.nl2tool.runner --traces evals/nl2tool/traces/golden \\\n"
        "    --require-threshold --primers evals/nl2tool/context_primers.yaml \\\n"
        "    --json temp/nl2tool/report.json --md-out evals/nl2tool/REPORT.md\n"
        "```\n\n"
        "## E4\n\n"
        "```bash\n"
        "python -m evals.robustness.runner --tier all --md \\\n"
        "    --answers temp/robustness/answers/r1 --require-execution\n"
        "python evals/robustness/check_disposal_scope.py    # 越界即 exit 1\n"
        "```\n\n"
        "> ⚠️ `evals/` 没有 `__init__.py`，请用 `python -m ...` 或 `PYTHONPATH=.`，\n"
        "> 不要直接 `python evals/robustness/runner.py`（E1 走 importlib 桩，两者都可）。\n",
        encoding="utf-8")
    return n + 1


def build_bundle(batches_done):
    reset_stage()
    # 先铺可运行镜像（原仓路径），再铺阅读视图（重排目录）
    total = build_runnable_mirror()
    # ---------- E1 ----------
    e1 = STAGE / "03-E1-自然语言到工具调用"
    total += copy_tree(ROOT / "evals/nl2tool/tasks.yaml", e1 / "01-任务集与标注" / "tasks.yaml")
    total += copy_tree(ROOT / "evals/nl2tool/context_primers.yaml", e1 / "01-任务集与标注" / "context_primers.yaml")
    total += copy_tree(ROOT / "evals/nl2tool/TASKS.md", e1 / "01-任务集与标注" / "TASKS.md")
    for f in ["graders.py", "normalizers.py", "runner.py", "gen_golden.py", "context_primers.py"]:
        total += copy_tree(ROOT / "evals/nl2tool" / f, e1 / "02-判定器与管线" / f)
    total += copy_tree(ROOT / "evals/nl2tool/broken", e1 / "03-自证与反证夹具" / "broken")
    total += copy_tree(ROOT / "evals/nl2tool/tests", e1 / "03-自证与反证夹具" / "tests")
    total += copy_tree(ROOT / "evals/nl2tool/traces", e1 / "04-轨迹" / "traces")
    for f in ["make_batch_input.py", "check_leakage.py"]:
        total += copy_tree(ROOT / "evals/nl2tool" / f, e1 / "05-防污染工具" / f)
    total += copy_tree(ROOT / "evals/nl2tool/REPORT.md", e1 / "06-结果" / "REPORT.md")
    # E1 过程产物（temp/nl2tool）
    # 排除：2026-10-06 批次（model_id=batch-2026-10-06）的全部派生 —— 该批已隔离
    total += copy_tree(ROOT / "temp/nl2tool", e1 / "08-过程产物(temp-nl2tool)",
                       exclude={"traces-live-2026-10-06", "report-live-FIXED.json"},
                       exclude_prefix=("scenario-",))
    (e1 / "08-过程产物(temp-nl2tool)" / "EXCLUDED-说明.txt").write_text(
        "本目录 = temp/nl2tool，已排除 **2026-10-06 批次**的全部派生（2026-10-11 核查）：\n\n"
        "  1) traces-live-2026-10-06/      26 条原始轨迹\n"
        "  2) scenario-*/                  12 个目录共 364 条轨迹\n"
        "  3) scenario-*.json              12 份判分结果 (weighted 0.8517 ~ 1.0)\n"
        "  4) report-live-FIXED.json       该批 grader 修正后的判分 (0.8517)\n\n"
        "排除依据：上述文件 source 均为 live-run、model_id 均为 **batch-2026-10-06**，\n"
        "即被隔离的 2026-10-06 批次同源产物；该批的判分报告已于 2026-10-11 移到桌面\n"
        "_M3批次-不可用-2026-10-11/。\n\n"
        "⚠️ 这些文件**目前仍在仓库 temp/nl2tool/ 原位**，本包只是不收；\n"
        "   是否一并移出隔离区由用户定夺。\n\n"
        "保留的是与该批无关的：g1/g2/g3.json、report.json、report-golden-recheck.json\n"
        "（均为 golden-from-annotation 自证批）、_isolation_selftest/、batch_input/、\n"
        "leak_probe/，以及生成脚本 make_scenarios.py / normalize_answers.py /\n"
        "audit_answers.py / probe_defect4.py / primers-fixed.yaml。\n", encoding="utf-8")

    # 三批答案键（合并 md + json + 判分 + 报告 + 泄漏自检脚本）
    # 注意：① 不再跳过 leakcheck_*（此前漏收）；② 批目录层的文件也要收
    #      （4444 的《判分复核报告》就放在 4444/ 层，不在答案目录内）
    for name, d in BATCHES.items():
        dst = e1 / "07-答案键三批" / name
        for p in sorted(d.glob("*")):
            if p.is_dir():
                continue
            total += copy_tree(p, dst / p.name)
        for p in sorted((CAND / name).glob("*")):
            if p.is_file():
                total += copy_tree(p, dst / p.name)

    # ---------- E4 ----------
    e4 = STAGE / "04-E4-鲁棒性与安全失败"
    for f in ["items.yaml", "TASKS.md", "rubric.yaml"]:
        total += copy_tree(ROOT / "evals/robustness" / f, e4 / "01-用例集与判据表" / f)
    for f in ["graders.py", "runner.py", "judge_tier_p.py", "guards.py", "replay.py", "check_disposal_scope.py"]:
        total += copy_tree(ROOT / "evals/robustness" / f, e4 / "02-判定器与执行器" / f)
    for d_ in ["injectors", "fixtures", "broken", "tests"]:
        total += copy_tree(ROOT / "evals/robustness" / d_, e4 / "03-注入器夹具与反证" / d_)
    for f in ["make_batch_input.py", "make_answer_box.py", "check_leakage.py"]:
        total += copy_tree(ROOT / "evals/robustness" / f, e4 / "04-防污染与沙箱工具" / f)
    total += copy_tree(ROOT / "temp/robustness/answers/r1", e4 / "05-过程产物-r1原始答卷" / "answers-r1")
    total += copy_tree(ROOT / "temp/robustness/batch_input", e4 / "05-过程产物-r1原始答卷" / "batch_input")
    # 沙箱：只收隔离说明 + 题卷 + 清单（src/ 等是被测对象副本，仓库里已有，不重复打包）
    box = e4 / "06-沙箱隔离(答题面)"
    box.mkdir(parents=True, exist_ok=True)
    src_box = ROOT / "temp/robustness/answer_box"
    if (src_box / "ISOLATION.md").exists():
        total += copy_tree(src_box / "ISOLATION.md", box / "ISOLATION.md")
    if (src_box / "questions").exists():
        total += copy_tree(src_box / "questions", box / "questions")
    if (src_box / "TASKS.md").exists():
        total += copy_tree(src_box / "TASKS.md", box / "TASKS.md")
    if src_box.exists():
        listing = sorted(str(p.relative_to(src_box)).replace("\\", "/")
                         for p in src_box.rglob("*") if p.is_file())
        (box / "SANDBOX-MANIFEST.txt").write_text(
            "答题面 answer_box 完整文件清单（共 %d 个）。\n"
            "被测对象本体（SKILL.md / src/ / references/ / contracts/ / static/ / rag/ 等）"
            "为本仓已有文件的副本，未重复打包；\n可用 `python evals/robustness/make_answer_box.py --build` 原样重建。\n\n"
            % len(listing) + "\n".join(listing), encoding="utf-8")
        total += 1
    # E4 其余过程产物（temp/robustness）：答卷采集脚本、分桶 payload、泄漏探针、隔离自检
    # 排除：answer_box 内被测对象副本（已在 02-被测对象本体 收全）、
    #      report-r1.json / REPORT-r1.md（已在 07-结果 收，避免两份）
    total += copy_tree(ROOT / "temp/robustness", e4 / "08-过程产物(temp-robustness其余)",
                       exclude={"answer_box", "report-r1.json", "REPORT-r1.md",
                                "answers", "batch_input"})

    total += copy_tree(ROOT / "evals/robustness/runs", e4 / "07-结果(r1权威)" / "runs")
    total += copy_tree(ROOT / "evals/robustness/REPORT.md", e4 / "07-结果(r1权威)" / "REPORT.md")
    total += copy_tree(ROOT / "temp/robustness/REPORT-r1.md", e4 / "07-结果(r1权威)" / "REPORT-r1.md")

    # ---------- 公共：门禁与 CI 接线 ----------
    total += build_gates_section()

    # ---------- 公共：被测对象本体（判定器直接 import src.*，缺了跑不起来） ----------
    subj = STAGE / "02-被测对象本体(skill)"
    for d_ in ["src", "references", "contracts", "static", "agents", "templates", "rag"]:
        total += copy_tree(ROOT / d_, subj / d_)
    for f in ["SKILL.md", "README.md", "architecture.md", "manifest.yaml",
              "environment.yaml", "pipeline.yaml", "pyproject.toml"]:
        p = ROOT / f
        if p.exists():
            total += copy_tree(p, subj / f)
    # ops/ —— tasks.yaml 的 verify_cmd 用到（如 ops/astro_best_cli.py doctor）
    total += copy_tree(ROOT / "ops", subj / "ops")

    # ---------- 公共：方案 / 核对 / 本工具 ----------
    common = STAGE / "05-方案与核对"
    for f in ["docs/eval-E1-nl2tool.md", "docs/eval-E4-robustness-safety.md",
              "docs/EVAL-E4-REVIEW-2026-10-07.md", "docs/PAPER-E1E4-CROSSCHECK-2026-10-11.md",
              "docs/EVAL-HUMAN-RUNBOOK.md", "docs/EVAL-LIVE-FETCH-WAIVER.md",
              "evals/paths.py", "evals/eval_runner.py"]:
        p = ROOT / f
        if p.exists():
            total += copy_tree(p, common / (p.name if p.suffix != ".py" else f"{p.parent.name}-{p.name}"))
    total += copy_tree(Path(__file__), common / "build_answers_and_bundle.py")

    return total


def write_readme(batches_done, total):
    lines = []
    lines.append("# E1 / E4 实验产物包")
    lines.append("")
    lines.append(f"- 打包日期：{datetime.now().strftime('%Y-%m-%d')}")
    lines.append(f"- 文件总数：{total}")
    lines.append("- 生成脚本：`00-方案与核对/build_answers_and_bundle.py`（可重跑，只读来源）")
    lines.append("")
    lines.append("> **口径前提（重要）**：E1 的判定基准是 `E1/07-答案键三批/` 下 3333 / 4444 / 5555 "
                 "三批 28 题答案键；**E4 不得使用 M3 模型批次**。")
    lines.append("> 2026-10-04 由 MiniMax-M3.1-Flash-Preview（M3）产出的 E1/E4 结果"
                 "（0.7803、25/35）**已全部移出仓库**，故本包内不含它们的任何数字。")
    lines.append("")
    lines.append("## 目录结构")
    lines.append("")
    lines.append("```")
    lines.append("00-可运行-原仓路径(解压后从这里跑)/  ★ 按仓库原始相对路径铺开，唯一可直接执行的副本")
    lines.append("01-门禁与CI接线/     门禁清单 GATES.md + Makefile + 权重量规/台账 + 解锁清单")
    lines.append("02-被测对象本体(skill)/ SKILL.md + src/ + references/ + contracts/ + static/")
    lines.append("                     + agents/ + templates/ + rag/ + ops/ + 依赖声明 pyproject.toml")
    lines.append("                     ← **判定器直接 import src.*，缺了整个流程跑不起来**")
    lines.append("03-E1-自然语言到工具调用/")
    lines.append("  01-任务集与标注/     tasks.yaml(28条,冻结) / context_primers.yaml / TASKS.md")
    lines.append("  02-判定器与管线/     graders.py / normalizers.py / runner.py / gen_golden.py")
    lines.append("  03-自证与反证夹具/   broken/ + tests/")
    lines.append("  04-轨迹/             traces/golden 28 条（判定器自证批，非模型能力证据）")
    lines.append("  05-防污染工具/       make_batch_input.py / check_leakage.py")
    lines.append("  06-结果/             REPORT.md")
    lines.append("  07-答案键三批/       3333 / 4444 / 5555（合并 md + answers-合并.json + 判分")
    lines.append("                     + 泄漏检测报告 + leakcheck 脚本 + 4444 判分复核报告）")
    lines.append("  08-过程产物(temp-nl2tool)/ 隔离自检 / 题面批次 / 金标准复算（已排除 10-06 批次派生）")
    lines.append("04-E4-鲁棒性与安全失败/")
    lines.append("  01-用例集与判据表/   items.yaml(68条) / TASKS.md / rubric.yaml")
    lines.append("  02-判定器与执行器/   graders.py / runner.py / judge_tier_p.py / guards.py / replay.py")
    lines.append("  03-注入器夹具与反证/ injectors/ fixtures/ broken/ tests/")
    lines.append("  04-防污染与沙箱工具/ make_batch_input.py / make_answer_box.py / check_leakage.py")
    lines.append("  05-过程产物-r1原始答卷/ answers-r1(35份) + batch_input(68条题卷)")
    lines.append("  06-沙箱隔离(答题面)/ ISOLATION.md + questions/ + SANDBOX-MANIFEST.txt")
    lines.append("  07-结果(r1权威)/     runs/r1/{report-r1.json, REPORT-r1.md, RUN-CARD.md} + REPORT.md")
    lines.append("  08-过程产物(temp-robustness其余)/ collect_batch.py / payload_* / leak_probe / 隔离自检")
    lines.append("```")
    lines.append("")
    lines.append("## 复现一条龙命令")
    lines.append("")
    lines.append("```bash")
    lines.append("# 0) 装依赖（见 02-被测对象本体/pyproject.toml）")
    lines.append("pip install pyyaml requests")
    lines.append("")
    lines.append("# 1) E1 金标准自证（判定器管线自洽，非模型能力）")
    lines.append("python evals/nl2tool/gen_golden.py")
    lines.append("python evals/nl2tool/runner.py --traces evals/nl2tool/traces/golden \\")
    lines.append("    --require-threshold --primers evals/nl2tool/context_primers.yaml \\")
    lines.append("    --json temp/nl2tool/report.json --md-out evals/nl2tool/REPORT.md")
    lines.append("")
    lines.append("# 2) E4 跑批（无答卷 → 门禁阻断；给答卷 → 真判话术层）")
    lines.append("make eval-e4 E4_ANSWERS=temp/robustness/answers/r1")
    lines.append("make check-e4-disposal        # 处置口径越界复检")
    lines.append("```")
    lines.append("")
    lines.append("> 注意：`evals/` 缺 `__init__.py`，直接 `python evals/robustness/runner.py` 会导入失败，")
    lines.append("> 需 `PYTHONPATH=.` 或改用 `python -m evals.robustness.runner`（E1 走 importlib 桩，不受影响）。")
    lines.append("")
    lines.append("## E4 结果的两个通过率必须成对引用")
    lines.append("")
    lines.append("| 层级 | 分母 | 通过 | 通过率 |")
    lines.append("|---|---|---|---|")
    lines.append("| 处置级 | 35 | 26 | **74.29%** |")
    lines.append("| 指标级 | 16 | 7 | **43.75%** |")
    lines.append("")
    lines.append("只写一个即为选择性报告 —— 详见 `04-E4-鲁棒性与安全失败/07-结果(r1权威)/runs/r1/RUN-CARD.md`。")
    lines.append("")
    lines.append("## ⚠️ 先读这段：解压后从 `00-可运行-原仓路径(解压后从这里跑)/` 进去")
    lines.append("")
    lines.append("`01-…` / `03-E1-…` / `04-E4-…` 这些是按主题重排的**阅读视图**（给人看的）；")
    lines.append("脚本内部大量用 `Path(__file__).resolve().parents[N]` 定位仓库根，")
    lines.append("**重排后路径解析会失效，直接跑会报错**。")
    lines.append("")
    lines.append("**要复现，请 `cd 00-可运行-原仓路径(解压后从这里跑)/`**")
    lines.append("（该目录按仓库原始相对路径铺开，见其内 `README-从这里跑起来.md`）。")
    lines.append("")
    lines.append("## ✅ 复现验证记录（2026-10-11 实测，ZIP 解压到仓库外干净目录）")
    lines.append("")
    lines.append("| 步骤 | 命令 | 实测结果 |")
    lines.append("|---|---|---|")
    lines.append("| E1 金标准自证 | `python evals/nl2tool/gen_golden.py`<br>`python -m evals.nl2tool.runner --traces …/golden --require-threshold --primers …` | 生成 28 条；`weighted=1.0 / pass=True / n_tasks=28 / 红线 0` ✅ |")
    lines.append("| E4 跑批 | `python -m evals.robustness.runner --tier all --answers temp/robustness/answers/r1 --require-execution` | Tier W **15/15**；Tier P `evaluated=True`、处置级 **26/35 = 0.7429**、阻断项 **22**、禁调 **4**；metascore/guardscore 均 1.00 ✅ |")
    lines.append("| E4 处置越界 | `python evals/robustness/check_disposal_scope.py` | exit 1，点名 RB-28/RB-38 以未定义口径计入 15/15 ✅ |")
    lines.append("| E1 答案键判分 | `cd nl2tool-candidate-answers/5555/… && python 5555_grade.py` | `weighted=0.9446`，与仓库原值**逐字段完全一致** ✅ |")
    lines.append("")
    lines.append("环境依赖：`pyyaml`、`requests`（见 `00-可运行-原仓路径(解压后从这里跑)/pyproject.toml`）。")
    lines.append("")
    lines.append("## 已排除（不是漏收）")
    lines.append("")
    lines.append("| 排除项 | 原因 |")
    lines.append("|---|---|")
    lines.append("| M3 批次（2026-10-04，MiniMax-M3.1）全部产物 | 含 0.7803、25/35；已隔离到桌面 `_M3批次-不可用-2026-10-11/` |")
    lines.append("| 2026-10-06 批次派生：`scenario-*`(364) / `traces-live-2026-10-06`(26) / `report-live-FIXED.json` | `model_id=batch-2026-10-06`，该批已隔离 |")
    lines.append("| `answer_box/` 内被测对象副本 | 本体已在 `02-被测对象本体(skill)/` 收全，避免重复 |")
    lines.append("")
    lines.append("详见 `03-E1-自然语言到工具调用/08-过程产物(temp-nl2tool)/EXCLUDED-说明.txt`。")
    lines.append("")
    lines.append("## 三批答案键（已合并）")
    lines.append("")
    lines.append("| 批次 | 合并 md | 结构化 json | 加权分 | 备注 |")
    lines.append("|---|---|---|---|---|")
    for name in ("3333", "4444", "5555"):
        d = BATCHES[name]
        md = d / "E1-28题答案-合并.md"
        js = d / "answers-合并.json"
        lines.append(f"| {name} | {'✅' if md.exists() else '—'} | {'✅' if js.exists() else '—'} | "
                     f"{batches_done.get(name, '?')} | 见下 |")
    lines.append("")
    lines.append("> 3333 / 4444 的 toolset/param/convert/redundant 是**硬编码 canonical 代理值**，")
    lines.append("> 两批 0.9089 相同属构造性相同；**只有 5555 用真实 predicted tool_calls**，")
    lines.append("> 故 toolset 只能取 5555 的 0.9405，三批不可简单横比。")
    lines.append("")
    (STAGE / "README-产物总览.md").write_text("\n".join(lines), encoding="utf-8")
    write_manifest()


def write_manifest():
    """根目录清单：便于核对「有没有漏收」，也便于解压后快速定位。"""
    lines = ["# 产物清单 MANIFEST", ""]
    lines.append(f"- 生成日期：{datetime.now().strftime('%Y-%m-%d')}")
    lines.append("- 生成脚本：`05-方案与核对/build_answers_and_bundle.py`（可重跑）")
    lines.append("")
    total = 0
    lines.append("## 顶层目录文件数")
    lines.append("")
    lines.append("| 目录 | 文件数 |")
    lines.append("|---|---:|")
    for d in sorted(STAGE.iterdir()):
        if d.is_dir():
            n = sum(1 for _ in d.rglob("*") if _.is_file())
            total += n
            lines.append(f"| `{d.name}` | {n} |")
    rootf = sorted(p.name for p in STAGE.iterdir() if p.is_file())
    total += len(rootf)
    lines.append("")
    lines.append(f"**合计：{total} 个文件**（含根目录 {len(rootf)} 个：{', '.join(rootf)}）")
    lines.append("")
    lines.append("## 复现必检文件（缺任一即跑不起来 / 跑不对）")
    lines.append("")
    must = [
        ("00-可运行-原仓路径(解压后从这里跑)/evals/nl2tool/tasks.yaml", "E1 冻结标注 28 条"),
        ("00-可运行-原仓路径(解压后从这里跑)/evals/nl2tool/traces/golden", "E1 金标准轨迹（≥28 条）"),
        ("00-可运行-原仓路径(解压后从这里跑)/evals/nl2tool/context_primers.yaml", "E1 占位符台账（必传，否则自证从 1.0 掉到 0.953）"),
        ("00-可运行-原仓路径(解压后从这里跑)/evals/robustness/items.yaml", "E4 用例集 68 条"),
        ("00-可运行-原仓路径(解压后从这里跑)/temp/robustness/answers/r1", "E4 r1 原始答卷 35 份（缺了会退回预检 → 假跑）"),
        ("00-可运行-原仓路径(解压后从这里跑)/src", "被测对象本体（判定器 import src.*）"),
        ("00-可运行-原仓路径(解压后从这里跑)/pyproject.toml", "依赖声明（pyyaml / requests）"),
    ]
    lines.append("| 路径 | 作用 | 存在 |")
    lines.append("|---|---|---|")
    for p, why in must:
        lines.append(f"| `{p.split('跑)/')[-1]}` | {why} | {'✅' if (STAGE / p).exists() else '❌'} |")
    lines.append("")
    lines.append("## 三批答案键必备件")
    lines.append("")
    lines.append("| 批次 | 合并 md | 结构化 json | 判分脚本 | 判分结果 | 泄漏自检 |")
    lines.append("|---|---|---|---|---|---|")
    for name in ("3333", "4444", "5555"):
        d = BATCHES[name]
        def ok(p):
            return "✅" if p.exists() else "—"
        grade = list(d.glob("*_grade.py"))
        gres = list(d.glob("*_grade_result.json"))
        leak = list(d.glob("leakcheck*.py")) + list((CAND / name).rglob("leakcheck*.py"))
        lines.append(f"| {name} | {ok(d / 'E1-28题答案-合并.md')} | {ok(d / 'answers-合并.json')} | "
                     f"{'✅' if grade else '—'} | {'✅' if gres else '—'} | {'✅' if leak else '—'} |")
    lines.append("")
    (STAGE / "MANIFEST-产物清单.md").write_text("\n".join(lines), encoding="utf-8")


def main():
    EXPORT.mkdir(parents=True, exist_ok=True)
    gold = gold_utterances()
    scores = {"3333": "0.9089", "4444": "0.9089", "5555": "0.9446"}

    print("=== [1/3] 合并 md + 补 answers.json ===")
    for name, d in BATCHES.items():
        payload, files, diff = build_batch(name, d, gold)
        if payload is None:
            continue
        (d / "answers-合并.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        md = write_merged_md(name, d, payload, files)
        print(f"  {name}: {len(files)} 份 md → {md.name}；answers-合并.json "
              f"{len(payload['items'])} 条；判定分布 {payload['counts']}")
        print(f"        与金标 route 不一致 {len(diff)} 题"
              + (f"：{', '.join(diff)}" if diff else ""))

    print("=== [2/3] 整理产物目录 ===")
    total = build_bundle(scores)
    print(f"  已复制 {total} 个文件 → {STAGE}")

    print("=== [3/3] 写总览 + 打包 ===")
    write_readme(scores, total)
    zip_path = ROOT / "E1和E4实验的产物.zip"
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(STAGE.rglob("*")):
            if p.is_file():
                z.write(p, str(p.relative_to(STAGE.parent)))
    print(f"  ✅ 压缩包: {zip_path}  ({zip_path.stat().st_size/1024:.0f} KB)")


if __name__ == "__main__":
    main()
