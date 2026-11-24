# -*- coding: utf-8 -*-
"""evals.robustness.make_answer_box — E4 答题沙箱 (答题面与答案面的物理隔离)。

存在理由: ``make_batch_input`` 只解决了"题干干净"的一半问题 —— 它保证**题面**
不含判分依据, 但模型在哪答题并没有约束。跑批的人随手把工作目录开在仓库里,
``evals/`` 就在它眼前; 开在桌面某个堆着上一轮实验的文件夹里, 别家的答卷就在
它眼前。这两件事 oggi 都没有机制兜底, 只能靠人记得。

本件要解决的是后者, 一种隐蔽程度高于答案泄漏的污染:

- **答案泄漏**让模型看到"标准答案怎么答", 至少还有人会因为文件名写着 items.yaml 而警觉;
- **异源答卷**让模型看到"另一个模型是怎么答的", 文件名叫 ``NL2T-05.json``、
  ``E1-traces/`` 之类, 看起来是普通产物 —— 照抄一遍同样是满分, 而这份满分与
  "独立作答"在分数上无法区分。更重要的是, 它连方向都能带偏: 复述上一位
  模型的措辞, 恰好落在 8 种失败包装形态词表上时, M5 (红线) 会**假红**,
  人们会误以为被测模型变坏了。

沙箱的做法是把两件事在空间上切开:

- **答题面** (`answer_box/`): 模型能看到的世界 —— 只有被测对象本体 + 干净题卷;
- **答案面** (`answers/<run_id>/`): 模型答出来的东西落在**沙箱之外**,
  下一轮/下一个模型站在同一个沙箱里时, 物理上翻不到前人的答案。

为什么不干脆只净化、不隔离: 净化是"删除已知的脏", 隔离是"只放已知的白"。
二者在本仓库的取舍已由铁律 6 定下 —— 黑名单会随时间被人以"这个文件应该没事"
逐条放行, 白名单则把举证责任反过来: 想塞东西进来, 先证明它该进来。

能力边界: 只读本实验的 items.yaml/rubric.yaml 与 skill 白名单目录, 只写 temp/。
不联网、不调大模型、不改标注, 也不改被测对象本体 (``src/`` 里残留的用例号注释
单独 WARN 报出, 由人决定是否动源码 —— 那属于改被测对象, 超出本件职权)。

白盒锚点: docs/eval-E4-robustness-safety.md §11.1 (§11.1 黑名单)。
"""
from __future__ import annotations

# 标准库: 参数解析 / 标注键正则 / 文件复制 / 路径锚定 / 类型标注
import argparse
import re
import shutil
import sys
from pathlib import Path
from typing import Iterable

_HERE = Path(__file__).resolve()
sys.path.insert(0, str(_HERE.parents[1]))   # evals/ 目录: 供 paths 兄弟裸导入
sys.path.insert(0, str(_HERE.parents[2]))   # skill 根: 供 evals.robustness 包导入

from paths import SKILL_DIR  # noqa: E402  # 共享路径工具: 所有路径锚点以它为唯一来源
# 本地: 同实验的泄漏自检器与题卷生成器 (黑名单 / 指纹 / 题面合成的唯一来源,
# 这三件东西各写一份就是漂移的开端 —— "包是干净的但自检器认为脏")
from evals.robustness.check_leakage import (  # noqa: E402
    ITEM_ID_RE,
    META_FILES,
    build_answer_fingerprints,
    build_request_index,
    load_items,
    scan_model_root,
    scan_text,
)
from evals.robustness.make_batch_input import (  # noqa: E402
    RUBRIC_PATH,
    SCHEMA_PATH,
    load_requests,
    write_bundle,
)

RB_DIR = Path(__file__).resolve().parent
ITEMS_PATH = RB_DIR / "items.yaml"
# 沙箱落在 temp/: 它是跑批时的一次性舞台, 不入库 (铁律 3 临时产物只进 temp/),
# 更不能被下一批当成"上一轮的参考"。
DEFAULT_BOX = SKILL_DIR / "temp" / "robustness" / "answer_box"
# 答案面在沙箱**之外**: answers/ 与 answer_box/ 同级而非其子树。
# 这一格之差就是隔离本身 —— 模型站在 box 里, 抬头看不到任何 <run_id> 目录。
DEFAULT_ANSWERS = SKILL_DIR / "temp" / "robustness" / "answers"

# 对**被测对象本体** (src/ 等白名单文件) 只查这个: 标注的 YAML 键成建制出现。
#
# 为什么不拿 build_answer_fingerprints 的答案串去扫被测对象: 那些串里有
# `catalog`、`gaia_dr3_18` 这类**技术通用词**, 在 README / SKILL.md 里出现
# 完全正常。实测试点沙箱时对被测对象全文扫指纹, 5 项 ERROR 全是假红 ——
# 假红淹没真信号的后果是这道闸被人绕过去, 比不检更糟。
#
# 改用「YAML 键 + 冒号」形式则两头兼顾: 整段标注被搬进来时必然是
# `disposal: B` / `- expect_envelope: {...}` 的形态, 抓得住; 而源码里的
# 同名标识符 (如函数名叫 expect_route) 不带冒号, 不会误伤。
OBJECT_KEY_RE = re.compile(
    r"(?m)^\s*(disposal|expect_envelope|expect_route|must_not_call|should_call_best"
    r"|reason_code|legal_range|fault_family|combo_with|base_case|anti_patterns"
    r"|must_not_output|scored_in_main|second_round)\s*:")

# 复制被测对象时跳过的东西: 编译产物与版本库元信息, 与被测内容无关。
SKIP_DIRS = frozenset({"__pycache__", ".git", ".pytest_cache", ".mypy_cache", "node_modules"})
SKIP_SUFFIX = frozenset({".pyc", ".pyo", ".pyd", ".so"})

# ── 异源答卷: 别家实验 / 别的模型 / 上一轮跑批答出来的东西 ─────────────────
# 路径记号命中即阻断: 这些东西出现在答题环境里, 说明有人把工作目录开在了
# 历史产物堆上 (本仓库最常见的情况是把沙箱建在某些历史目录的旁边)。
FOREIGN_PATH_TOKENS = (
    "NL2T-",            # E1 题号: E1 的 26 题卷答卷
    "E1-", "E2-", "E3-",  # 别家实验的产出前缀
    "-traces", "traces", "answers", "answer",  # 答卷目录/文件的通名
    "grade", "judgment", "live-", "report-",   # 判分结果与跑批归档
    "batch_input", "leak_probe", "_isolation_selftest",  # E1/E4 的生成包与自检废料
)

# 内容记号: E1 轨迹的 schema 字段名与判分段落标题。**比路径更难藏** ——
# 就算把文件改名成 notes.txt, E1 trace 里的这些串仍在。
FOREIGN_CONTENT_TOKENS = (
    '"answer_text"', '"tool_calls"', '"http_requests"',  # E1/本实验 trace 的顶层字段
    "## 判定", "**路由类型**", "**结论**",                 # E1 答卷 md 的段落标题
    "golden-from-annotation", "judge: program",           # 判分层内部标记
)

# 弱信号: 不阻断但点名 —— 单个字段可能只是同名变量,成对出现才可疑。
FOREIGN_WARN_TOKENS = ('"task_id"', '"isolation_note"')

# 被测源码注释里残留的 E4 用例号 (src/protocol.py / client_paging.py / models)。
# **不阻断**: src/ 是被测对象本体, 动它等于改被测物, 超出本件职权。
# 报出来是为了让它不被遗忘 —— 这条每批都得报一次, 直到有人决定动源码。
SRC_LEAK_RE = ITEM_ID_RE


def _split_allowed() -> tuple[list[str], list[str]]:
    """把白名单拆成 (顶层文件, 顶层目录), 由 ALLOWED_IN_MODEL_ROOT 单点决定。

    不在这里抄一遍清单: 白名单改了而此处没跟上, 沙箱就会漏放或漏禁。
    """
    from evals.robustness.check_leakage import ALLOWED_IN_MODEL_ROOT
    files = [p for p in ALLOWED_IN_MODEL_ROOT if not p.endswith("/")]
    dirs = [p.rstrip("/") for p in ALLOWED_IN_MODEL_ROOT if p.endswith("/")]
    return files, dirs


def _guard_rebuild_target(box: Path) -> None:
    """删除守卫: 只许清理"看起来确实是本件维护的沙箱", 绝不误删别处。

    三个条件缺一不可 —— 名字含 answer_box、在 temp/ 下、且不是文件系统根。
    写这段是因为 `rmtree` 一旦指错地方没有第二次机会, 而守卫的成本是三行。
    """
    if box.name != "answer_box" or "temp" not in box.parts or box == box.parent:
        raise SystemExit(f"拒绝清理: {box} 不像本件的答题沙箱 (要求: 目录名 answer_box 且位于 temp/ 下)")


def _copy_tree(src: Path, dst: Path) -> int:
    """白名单子树复制 (跳过编译产物), 返回复制文件数。

    用 copy 而非 symlink: 软链会让模型顺着真实路径读到 link 指向之外的东西,
    等于把沙箱的边界凿了个洞 —— 边界必须是物理的。
    """
    n = 0
    dst.mkdir(parents=True, exist_ok=True)
    for path in sorted(src.rglob("*")):
        if any(p in SKIP_DIRS for p in path.relative_to(src).parts):
            continue
        rel = path.relative_to(src)
        target = dst / rel
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        elif path.is_file() and path.suffix not in SKIP_SUFFIX:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
            n += 1
    return n


def write_isolation_md(box: Path, answers_root: Path, n_items: int) -> None:
    """写沙箱入口说明: 规矩、边界、答案该往哪写。

    这份文件给**跑批的人**看, 不是给被测模型看的: 边界一旦没人解释,
    下次就会有人"为了方便"把 answers 挪进 box, 然后把成绩作废。
    """
    text = f"""# E4 答题沙箱（answer_box）

> 生成件，勿手改 —— 由 `evals/robustness/make_answer_box.py` 白名单填充。

## 这里是给被测模型用的唯一舞台

本目录已剔除全部评测标注、判分器、注入剧本，以及**任何别家模型的答卷**。
被测模型的工作目录应当直接指向本层（不要再多给一层）。

## 三条边界

1. **答案写到 `{answers_root}/<run_id>/<题号>.json`**
   —— 在沙箱**外面**。`<run_id>` 每轮一个（如 `r1`/`r2`），多轮重估时
   前一轮的答案不会被后一轮的模型看到。
2. **不要往本目录里拷贝任何历史产物**（`E1-traces/`、`NL2T-*.json`、
   `*-grade*`、上一轮的 `answers/`）。它们会让模型照抄别人的答卷，
   而这跟"答对"在分数上无法区分。
3. **被测模型不许挂载仓库其余部分**。本目录已经是它该知道的全部。

## 可以看的

被测对象本体：`SKILL.md`、`README.md`、`manifest.yaml`、`architecture.md`、
`contracts/`、`static/`、`references/`、`src/`、`agents/`、`templates/`、`rag/`。

## 题卷

`questions/TASKS.md`（{n_items} 条题面一册，一次只复制一个题块）；
`questions/per_item/<题号>.txt`（一文件一句请求，直接粘贴）。

## 体检

```bash
python evals/robustness/make_answer_box.py --check
```

命中任意一条即 exit 1。Tier W 的故障仍只由注入器现场施加，别写进题面。
"""
    (box / "ISOLATION.md").write_text(text, encoding="utf-8")


def iter_checked(box: Path, allow_dirs: list[str], allow_files: list[str]) -> Iterable[Path]:
    """收集待检疫文件: 沙箱内**非被测对象本体**的东西。

    为什么要排除被测对象本体: 它是模型本来就该读的东西, 里面出现
    `"task_id"` 或 `catalog` 之类记号是正常内容; 用答案串去扫它只会制造假红,
    而假红一多这道闸就被人绕过去了。被测对象走单独的 ``scan_object_keys``,
    只查"整段标注有没有被搬进来"。
    """
    for path in sorted(box.rglob("*")):
        if not path.is_file() or path.suffix in SKIP_SUFFIX:
            continue
        if any(p in SKIP_DIRS for p in path.relative_to(box).parts):
            continue
        if path.name in META_FILES:                       # 生成器自己的警示语
            continue
        rel = path.relative_to(box)
        if rel.parts and (rel.parts[0] in allow_dirs or rel.parts[0] in allow_files):
            continue                                       # 被测对象本体: 走自己的检疫口径
        yield path


def scan_object_keys(box: Path, allow_dirs: list[str], allow_files: list[str]) -> list[str]:
    """检疫被测对象本体: 只查"标注被成建制搬进来", 不查通用词。

    白名单拷进来的 src/ README.md SKILL.md 是模型**本该看到**的东西, 扫它们
    的尺度必须与 vb 题面不同 —— 否则每批都红, 这道闸就名存实亡。
    """
    hits: list[str] = []
    targets: list[Path] = [box / name for name in allow_files if (box / name).is_file()]
    for dirname in allow_dirs:
        base = box / dirname
        if base.is_dir():
            targets.append(base)
    for base in targets:
        paths: Iterable[Path] = [base] if base.is_file() else sorted(base.rglob("*"))
        for path in paths:
            if not path.is_file() or path.suffix in SKIP_SUFFIX:
                continue
            if any(p in SKIP_DIRS for p in path.relative_to(base).parts if base.is_dir()):
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for m in OBJECT_KEY_RE.finditer(text):
                line = text.count("\n", 0, m.start()) + 1
                hits.append(f"{path.relative_to(box)}:{line} — 被测对象里出现标注键 "
                            f"'{m.group(1)}:' (整段标注被搬进来了?)")
    return hits


def scan_src_leaks(box: Path, allow_dirs: list[str]) -> list[str]:
    """扫被测源码注释里残留的 E4 用例号 → WARN 清单 (不阻断)。

    这是一个**已知且未修**的缺口: src/ 在可看白名单内 (它毕竟是被测物本体),
    但源码注释里直接刻了 `RB-29` / `RB-24 包装形态 #2` 这类字样。黑名单对它
    无解 —— 除非把 src 一起禁掉, 但那就没东西可测了。
    每批报一次, 直到有人决定是把用例号摘掉还是接受它。
    """
    hits: list[str] = []
    for dirname in allow_dirs:
        base = box / dirname
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.py")):
            if any(p in SKIP_DIRS for p in path.relative_to(base).parts):
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for m in SRC_LEAK_RE.finditer(text):
                line = text.count("\n", 0, m.start()) + 1
                hits.append(f"{path.relative_to(box)}:{line} — 源码注释含用例号 {m.group(0)}")
    return hits


def check_box(box: Path, answers_root: Path, items_path: Path) -> tuple[list[str], list[str]]:
    """沙箱检疫 → (阻断项, 警告项)。

    三层, 按危害排序:

    1. **黑名单路径** (复用 ``scan_model_root``): 评测目录/归档/工作日志成建制出现;
    2. **E4 答案 fingerprint**: 题面里混进了标注原话 (复用 ``scan_text``);
    3. **异源答卷**: 别家实验或上一轮的答案——本件相对既有两件的新增量。
    """
    errors: list[str] = []
    warns: list[str] = []
    _allow_files, _allow_dirs = _split_allowed()

    # ── 第 1 层: 黑名单路径 ────────────────────────────────────────────
    for hit in scan_model_root(box):
        errors.append(f"黑名单路径 {hit}")

    # ── 第 1.5 层: 被测对象本体 (只用 YAML 键检疫, 不用答案串) ────────────
    for hit in scan_object_keys(box, _allow_dirs, _allow_files):
        errors.append(hit)

    # ── 第 2 层: E4 答案泄漏 (指纹/字段名/禁调句式/串题) ─────────────────
    # **只扫"给模型的输入面"** —— TASKS.md 与 questions/。
    # 理由与上一层同源: 答案串里有 catalog / gaia_dr3_18 这类技术通用词。实测
    # 若放宽到"沙箱里任何非白名单文件", 跑批的人往里放一份普通技术笔记就会
    # 被判答案泄漏 —— 那种假红不需要第二次, 这道闸就会被架空。
    # 真正会被粘进会话的只有题卷, 那是风险面; 其余文件由第 1/1.5/3 层守住。
    items = load_items(items_path)
    fps = build_answer_fingerprints(items)
    reqs, families = build_request_index(items)
    from evals.robustness.check_leakage import CROSS_EXEMPT_FILES
    input_face: list[Path] = []
    if (box / "questions").is_dir():
        input_face += list(iter_checked(box / "questions", [], []))
    if (box / "TASKS.md").is_file():
        input_face.append(box / "TASKS.md")
    for path in input_face:
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if not text.strip():
            continue
        owner_m = ITEM_ID_RE.search(path.name)
        errs, wrns = scan_text(text, owner_m.group(0) if owner_m else "", fps,
                               reqs, families, skip_cross=path.name in CROSS_EXEMPT_FILES)
        errors.extend(f"[{path.relative_to(box)}] {e}" for e in errs)
        warns.extend(f"[{path.relative_to(box)}] {w}" for w in wrns)

    # ── 第 3 层: 异源答卷 (本件的新增量) ─────────────────────────────────
    allow_dirs = _split_allowed()[1]
    for path in sorted(box.rglob("*")):
        rel = path.relative_to(box)
        if any(p in SKIP_DIRS for p in rel.parts):
            continue
        for token in FOREIGN_PATH_TOKENS:
            if token in str(rel):
                errors.append(f"异源答卷痕迹: 路径 '{rel}' 命中 '{token}' — "
                              f"别家/上一轮的答卷不许出现在答题环境里")
                break
    for path in iter_checked(box, allow_dirs, _split_allowed()[0]):
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        low = text.lower()
        for token in FOREIGN_CONTENT_TOKENS:
            if token.lower() in low:
                errors.append(f"[{path.relative_to(box)}] 异源答卷内容特征值 '{token}' "
                              f"— 改了名也认得出")
        for token in FOREIGN_WARN_TOKENS:
            if token.lower() in low:
                warns.append(f"[{path.relative_to(box)}] 疑似答卷字段 '{token}' — 请确认不是别家的产物")

    # ── 第 4 层: 边界自洽 (答案面不得落在答题面里) ───────────────────────
    try:
        if answers_root.resolve().is_relative_to(box.resolve()):
            errors.append(f"答案面 {answers_root} 落在答题面 {box} 之内 — 下一轮会看到上一轮的答案")
        elif box.resolve().is_relative_to(answers_root.resolve()):
            errors.append(f"答题面 {box} 落在答案面 {answers_root} 之内 — 边界方向反了")
    except OSError:
        pass

    return errors, warns


def build(box: Path, answers_root: Path, items_path: Path) -> dict:
    """搭沙箱: 清场 → 白名单填充 → 题卷落地 → 答案面备好 (在盒外)。"""
    if box.exists():
        _guard_rebuild_target(box)
        shutil.rmtree(box)
    box.mkdir(parents=True, exist_ok=True)

    files, dirs = _split_allowed()
    n_copy = 0
    for name in files:                                     # 被测对象的顶层说明件
        src = SKILL_DIR / name
        if src.is_file():
            shutil.copy2(src, box / name)
            n_copy += 1
    for name in dirs:                                      # 被测对象本体
        src = SKILL_DIR / name
        if src.is_dir():
            n_copy += _copy_tree(src, box / name)

    items = load_requests(items_path)
    write_bundle(items, box / "questions", items_path, RUBRIC_PATH, SCHEMA_PATH)
    (box / "TASKS.md").write_text(
        (box / "questions" / "TASKS.md").read_text(encoding="utf-8"), encoding="utf-8")

    answers_root.mkdir(parents=True, exist_ok=True)
    write_isolation_md(box, answers_root, len(items))
    return {"n_files": n_copy, "n_items": len(items)}


def main() -> int:
    """命令行入口: ``--build`` 搭箱并自检, ``--check`` 只自检。命中断阻项即 exit 1。"""
    ap = argparse.ArgumentParser(description="E4 答题沙箱 (答题面与答案面物理隔离)")
    ap.add_argument("--build", action="store_true", help="搭沙箱 (先清场再白名单填充)")
    ap.add_argument("--check", action="store_true", help="检疫沙箱 (默认在 --build 后自动跑)")
    ap.add_argument("--box", default=str(DEFAULT_BOX), help=f"答题面根目录 (默认 {DEFAULT_BOX})")
    ap.add_argument("--answers", default=str(DEFAULT_ANSWERS),
                    help=f"答案面根目录, 必须在答题面之外 (默认 {DEFAULT_ANSWERS})")
    ap.add_argument("--items", default=str(ITEMS_PATH), help="用例标注 (默认 items.yaml)")
    args = ap.parse_args()

    box = Path(args.box)
    answers_root = Path(args.answers)
    items_path = Path(args.items)

    if not args.build and not args.check:
        ap.error("须给 --build / --check 之一")

    if args.build:
        info = build(box, answers_root, items_path)
        print(f"[OK] 答题面已就绪: {box}")
        print(f"     被测对象 {info['n_files']} 个文件 (白名单: "
              f"{', '.join(sorted(_split_allowed()[0] + _split_allowed()[1]))})")
        print(f"     题卷 {info['n_items']} 条: {box / 'TASKS.md'} / questions/per_item/")
        print(f"     答案面在外面: {answers_root}/<run_id>/<题号>.json")

    errors, warns = check_box(box, answers_root, items_path)
    src_leaks = scan_src_leaks(box, _split_allowed()[1])

    print(f"\n检疫: 答题面 {box} · 答案面 {answers_root}")
    if errors:
        print(f"\n[FAIL] {len(errors)} 项必须为 0 — 不干净的环境跑出来的分数不作数:", file=sys.stderr)
        for e in errors:
            print(f"  ✗ {e}", file=sys.stderr)
    if src_leaks:
        print(f"\n[WARN] 被测源码注释里有 {len(src_leaks)} 处 E4 用例号残留 "
              f"(黑名单管不到 src/ — 被测对象本体本来就该给模型看):", file=sys.stderr)
        for s in src_leaks[:10]:
            print(f"  ! {s}", file=sys.stderr)
        print("  ! → 建议把用例号从 src 注释摘掉, 只留行为描述。属源码改动, 本件不动。",
              file=sys.stderr)
    if warns:
        print(f"\n[WARN] {len(warns)} 处弱信号 (不阻断, 请确认):", file=sys.stderr)
        for w in warns[:15]:
            print(f"  ! {w}", file=sys.stderr)

    if errors:
        return 1
    print("[OK] 答题面干净: 无评测标注、无判分器、无注入剧本、无别家答卷。")
    print("     仍须守住: 一题一会话; 答案写到答案面; Tier W 剧本只由注入器现场施加。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
