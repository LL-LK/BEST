# -*- coding: utf-8 -*-
r"""守护: 两条 blocking 门禁的**接线状态**宣称必须与生产代码对账 (E5 P1-02)。

缺陷形态 (2026-10-05 E5 对外声明面审计, temp/DETECT-E5-external-surface.md P1-02,
本轮 V1 修复): ``http_status == 200`` 与 ``checksum_match == True`` 被三处声明为
**blocking** 门禁 —— ``SKILL.md`` 的门禁表 / ``agents/openai.yaml`` 的
``gate_stance.blocking`` / ``manifest.yaml`` 的 ``quality_gates`` —— 而**生产链路
里没有任何一处会产生这两个值**。求值实现 (``BestResultSet.gates_passed()``) 本身
正确且 fail-closed, 但它所在的类 ``BestResultSet`` 在 ``src/`` 内**零构造点**。

**危害**: ``SKILL.md`` 要求"门禁不足即 needs_review", 而真实运行中该门禁对象根本
不存在 —— 模型无从求值, 只能凭空声称通过或假装判定。定性为"无门可判", 与
``src/models/output.py`` 警告的"恒真的假门禁"是同一族问题的镜像。

本轮选的修法是 **(b) 文档明确标注"设计上保留、当前未接线"** (留但说清), 与 H6-02
当时的判断一致 —— 理由与被否掉的 (a)/(c) 见 :data:`DECISION_REASON`。

**本件守的是"披露不许腐烂"**: 披露一旦写下就会过期 (Q-08 接线完成后它就成了新的
不实陈述)。故本件判**两个方向**:

- 未接线时: 三个声明面必须**都**带未接线标记 (漏一处即红);
- 接线完成后: 生产侧一旦出现 ``BestResultSet`` 构造点, 本件立刻红, 提示人
  **删掉披露** —— 否则仓内会留下"接线了却仍在说没接线"的反向不实陈述。

方向性纪律沿用本仓既有做法 (``test_dead_channel_claims.py``
``test_rule_does_not_repeat_the_retired_unknown_claim``): 判据随代码事实翻转, 不
把"某一种说法"钉成永久正确。
"""
from __future__ import annotations

# 标准库: ast 静态扫生产构造点 (不 import, 免副作用进测试进程) / re 切文本 /
#         sys 注 sys.path / pathlib 锚仓根
import ast
import re
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[3]   # 仓根: 本件在 test/unit/meta/ 下三级
AUDIT_DIR = SKILL_ROOT / "ops" / "audit"           # 扫描面唯一真源所在目录
if str(AUDIT_DIR) not in sys.path:                 # 幂等: 同目录裸名导入 (与门禁自身同纪律)
    sys.path.insert(0, str(AUDIT_DIR))

import scan_roots  # noqa: E402  覆盖面唯一真源 (D5-01: 不自列目录)

# 本轮 (b) 路线的理由, 写在代码里是因为"为什么保留而不接线"是下一个人的必答项。
DECISION_REASON = (
    "(a) 接线需改 src/ 的构造链并决定架构 (Q-08 已登记为路线项, 属产品决定, "
    "且半接线比不接线更坏: 门禁会给出无意义的判定); "
    "(c) 降级为 docs 声明会丢掉与 contracts/output.contract.yaml 的契约绑定, "
    "而跨 skill 消费方按 result_json 这个 sink 名取件。"
)

# 必须在带未接线标记时才为真的声明面 (逐个给出为什么模型会读到它)。
GATE_DECLARATION_SURFACES: tuple[tuple[str, str], ...] = (
    ("SKILL.md", "门禁表 (模型每次会话的 always_load 首面)"),
    ("agents/openai.yaml", "gate_stance.blocking (agent persona 契约)"),
    ("manifest.yaml", "quality_gates + result_json sink (宿主加载地图)"),
)

# 判定"这一行已经披露了未接线"的措辞锚: 只认明说未接线的说法, 不认泛泛的
# "保留"/"实验" —— 放得太宽就成了永远绿的橡皮图章。本清单与三处披露逐字对应,
# 由 ``test_unwired_markers_are_all_real_substrings_of_the_surfaces`` 钉住不许虚列。
UNWIRED_MARKERS = ("未接线", "无填充点", "无生产构造点")


def _production_construction_sites() -> list[str]:
    """生产面 (``src/`` + ``ops/``) 里 ``BestResultSet(...)`` 的构造点 (file:line)。

    只认**调用形态** (Name 上下文里的 Call), 因此 ``src/models/__init__.py`` 的
    re-export 与 ``output.py`` 的类定义都不算 —— 真正的"填充点"必须有人 ``new`` 它。
    """
    sites: list[str] = []
    for rel, full in scan_roots.iter_py_files(str(SKILL_ROOT)):   # 覆盖面来自唯一真源, 不自列目录
        if not rel.startswith(("src/", "ops/")):
            continue                                      # 只看生产面: test/ 的构造不算填充点
        try:
            tree = ast.parse(Path(full).read_text(encoding="utf-8-sig"), filename=full)   # 只解析, 不 import
        except SyntaxError:
            continue                                      # 语法错由 count_code_lines 判红, 此处不重复报
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == "BestResultSet"):
                sites.append(f"{rel}:{node.lineno}")      # 记 file:line: 接线后要能直接跳过去改
    return sites


def _unwired_lines(path: Path, names: tuple[str, ...]) -> list[str]:
    """在该文件里点名 ``names`` 中任一关键词、且带未接线标记的行。

    按**行**判而非整篇: 整篇含标记会让文件里任何位置的免责话替所有话背书, 而
    引用与转述时人只会摘走半句。
    """
    hits: list[str] = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), start=1):
        if any(name in line for name in names) and any(marker in line for marker in UNWIRED_MARKERS):
            hits.append(f"{lineno}: {line.strip()}")     # 带行号: 判红时能直接跳过去看
    return hits


class TestBlockingGatesWiringDisclosure:
    """两条 blocking 门禁的接线状态宣称必须与生产代码事实一致。"""

    GATE_NAMES = ("http_status", "checksum_match")

    def test_wiring_status_is_disclosed_on_every_declaration_surface(self):
        """未接线时, 三个声明面必须都披露 —— 漏一处即红 (模型可能只读到那一面)。"""
        sites = _production_construction_sites()      # 先取事实: 生产面一旦接线, 披露就该被删
        assert not sites, (
            f"生产面已出现 BestResultSet 构造点 {sites}: 门禁接线已完成, "
            "SKILL.md / agents/openai.yaml / manifest.yaml 的\"未接线\"披露已过期, "
            "请删掉披露并同步更新本件的期望 (否则仓内留下反向的不实陈述)"
        )
        missing: list[str] = []
        for name, why in GATE_DECLARATION_SURFACES:
            path = SKILL_ROOT / name
            assert path.is_file(), f"声明面 {name} 不存在: 路径漂移会让下面的对账空转"
            lines = _unwired_lines(path, ("quality_gates", "gate_stance", "质量门禁",
                                          "result_json", "blocking"))   # 按行判: 任一处的免责话不能替别处背书
            if not lines:
                missing.append(f"{name} ({why})")        # 记"哪一面漏了"和"为什么这一面会被读到"
        assert not missing, (
            "这些声明面提到 blocking 门禁却未标明接线状态: "
            + "; ".join(missing)
            + f" —— 模型被要求\"门禁不足即 needs_review\"却无从求值, 只能凭空声称通过 "
            f"(处置口径见本模块 DECISION_REASON: {DECISION_REASON})"
        )

    def test_disclosure_survives_a_half_rewritten_surface(self):
        """半改写防线: 只留"保留"而不留未接线措辞 → 判红 (措辞被磨掉的情形)。

        守的是措辞被**逐步磨掉**的过程: 有人把披露缩成"设计上保留"就以为意思还在,
        而模型读到的是"门禁可用"。措辞锚必须真的在行里。
        """
        surface = SKILL_ROOT / "SKILL.md"
        text = surface.read_text(encoding="utf-8-sig")
        softened = text.replace("未接线", "设计上保留").replace("无生产构造点", "按契约声明")
        assert softened != text, "反证夹具失效: SKILL.md 里找不到待替换的措辞锚"
        hits = [ln for ln in softened.splitlines()
                if any(k in ln for k in ("质量门禁", "blocking", "quality_gates"))
                and any(m in ln for m in UNWIRED_MARKERS)]
        assert not hits, f"措辞被磨成\"保留\"后仍被判为已披露 —— 锚定太宽: {hits}"

    def test_unwired_marker_vocabulary_is_not_too_broad(self):
        """反证: 一句不含未接线措辞的宣称不得被判为已披露 (橡皮图章防线)。"""
        decoy = "\n".join([
            "## 质量门禁 (阻断性, 不足即 needs_review)",
            "| http_status | == | 200 | count |",
            "| checksum_match | == | True | bool |",
        ])
        hits = [ln for ln in decoy.splitlines()
                if any(k in ln for k in ("质量门禁", "blocking", "quality_gates"))
                and any(m in ln for m in UNWIRED_MARKERS)]
        assert not hits, f"没有未接线措辞的宣称被判为已披露 —— UNWIRED_MARKERS 放得太宽: {hits}"

    def test_unwired_markers_are_all_real_substrings_of_the_surfaces(self):
        """前提: 每个措辞锚在本仓真的出现过 (否则判据会悄悄退化成"永不命中")。"""
        corpus = "\n".join(
            (SKILL_ROOT / name).read_text(encoding="utf-8-sig") for name, _ in GATE_DECLARATION_SURFACES
        )
        unused = [m for m in UNWIRED_MARKERS if m not in corpus]
        assert not unused, (
            f"这些措辞锚在三个声明面里一个都没出现: {unused} —— "
            "它们此刻不承重, 却在扩大判据的判定面 (删掉比留着更诚实)"
        )

    def test_gate_thresholds_are_unchanged_by_this_disclosure(self):
        """披露不得顺手改阈值 —— 两处的比较符与值仍须逐字一致。

        钉住"这次只加披露、不改判据": 阈值一漂, "成功"的定义就变了, 而那属于
        另一个议题, 不该由一条披露修复顺带做掉。
        """
        skill_md = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8-sig")
        manifest = (SKILL_ROOT / "manifest.yaml").read_text(encoding="utf-8-sig")
        for name, cmp_, value in (("http_status", "==", "200"), ("checksum_match", "==", "True")):
            skill_row = re.search(rf"^\|\s*{name}\s*\|\s*{cmp_}\s*\|\s*{value}\s*\|", skill_md, re.M)
            assert skill_row, f"SKILL.md 门禁表里 {name} 的判定/阈值被改动 (应仍是 {cmp_} {value})"
            manifest_row = re.search(rf"name:\s*{name},\s*cmp:\s*\"{cmp_}\",\s*value:\s*{value}", manifest)
            assert manifest_row, f"manifest.yaml 里 {name} 的判定/阈值被改动 (应仍是 {cmp_} {value})"
