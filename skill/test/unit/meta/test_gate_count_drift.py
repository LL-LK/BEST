# -*- coding: utf-8 -*-
"""门禁数量声明与 ``Makefile`` 实现的一致性 —— 防「指令层骗人」的承重断言。

2026-10-07 实测的漂移: ``CLAUDE.md`` 写「**六个**硬门禁」、``README.md:16`` 写「五项」、
``README.md:34`` 写「**六项**」并只列 6 个名字, 而 ``Makefile`` 的 ``audit:`` 实跑 **9** 个
(多出 ``verify_no_version_keys`` / ``verify_evidence_anchors`` / ``verify_counting_claims``)。

后果不是"文档不好看", 而是**照文档理解治理面的人会被误导** —— 那次审计的核实员
自己就是按「六个硬门禁」的口径工作的, 直到实跑才发现铁律 1 (版本键)、E3 锚点、
计数型断言三道门禁**根本不在它的工作模型里**。``CLAUDE.md`` 正是每个新会话里
AI 协作者的权威指令文件, 所以这条漂移会持续污染后续每一次会话。

**为什么不能用既有门禁顺手看掉**: ``verify_crossrefs.py`` 的治理文档检查只校验
反引号路径是否存在, 不解析清单条数也不比对集合; ``comment_audit`` / ``count_code_lines``
都不读 ``Makefile``。所以这条一致性只能由独立的 meta 测试承担 —— 它也正是
``ops/audit/README.md`` 里点名的那个"无任何门禁覆盖"的缺口。

判据设计成**集合相等 + 条数相等**而不是"文档里提到了几个": 只比条数的话, 文档
少写一个同时多写一个别的, 条数照样对得上而集合已经错了 (2026-10-07 那次漂移正是
"六项"里塞着 6 个真名 + 漏掉 3 个, 条数与集合**同时**错, 两条判据都能抓住)。
"""
from __future__ import annotations

import re  # 标准库: 从 Makefile 配方与文档行里抽门禁名
import sys  # 标准库: 路径锚定
from pathlib import Path  # 标准库: 仓根定位

import pytest  # 参数化与断言

SKILL_ROOT = Path(__file__).resolve().parents[3]  # 仓根: 本件在 test/unit/meta/ 下三级
MAKEFILE = SKILL_ROOT / "Makefile"  # 实现层的唯一真源
AUDIT_DIR = SKILL_ROOT / "ops" / "audit"  # 门禁脚本所在目录: 用来核"配方里的名字真有文件"

# 声明层的三处: 每处都写过"几道硬门禁"。少一处不构成漏网 (新增声明面时本测试会漏判),
# 多写一处则是冗余维护 —— 但**刻意只收这三处**, 因为它们是真实存在且被实测漂移过的。
DECLARATION_SURFACES = ("CLAUDE.md", "README.md")  # 声明层: 这两份实测漂移过, 且都是人真会读的地方

# 报告型工具: 刻意不阻断的四件。文档里提到它们是**正确**的 (那正是"刻意不阻断"的披露),
# 不算门禁数的一部分; 但它们不能出现在 audit: 配方里 —— 那条由
# TestBlockingGatesWiringDisclosure 守。version_scan2 是 version_scan 的姊妹件, 同档。
REPORT_ONLY = ("verify_no_code_loss", "scan_code_smells", "version_scan", "version_scan2",
               "check_line_endings")

# 共享辅助模块: 本身不是门禁, 是被门禁 import 的覆盖面/度量真源。
# 它们**必须**存在 (少一个门禁就 import 失败), 但把它们算进"文档提到的门禁"会
# 产出假阳性 —— README 讲扫描面口径时提到 scan_roots 是在讲机制, 不是在宣称它拦东西。
HELPERS = ("scan_roots", "line_scope", "env_scope")  # 共享辅助模块: 不是门禁, 文档提它们是在讲覆盖面机制

# 门禁名在文档/配方里的形态: ops/audit/xxx.py 或裸名 xxx
GATE_NAME_RE = re.compile(r"(?:ops/audit/)?([a-z_][a-z0-9_]*)\.py")  # 带后缀形态: 文档与配方里都可能出现

# 非门禁的 audit 目录成员: 报告型 + 辅助模块。用于把"文档提到的 audit 脚本"过滤成
# "文档声称的门禁"。刻意从**文件系统**取全集再减, 而不是手抄名单 —— 手抄会在
# 新增辅助模块时立刻过期, 而过期的名单会伪装成"文档提到了不存在的门禁"。
def _non_gate_audit_modules() -> set[str]:
    """audit 目录下**不是门禁**的成员名 (报告型 + 辅助模块), 实测得出不硬编码。"""
    on_disk = {p.stem for p in AUDIT_DIR.glob("*.py")}  # 落盘全集: 辅助模块与报告型工具都在里面
    recipe = set(_audit_recipe_gate_names())  # 实现层真源: 差集即"不是门禁"的那部分
    # 落盘 - 配方 = 非门禁; 再并上显式名单, 防某天有人把辅助模块误加进配方后
    # 它从"非门禁"集合里消失、进而被当成必须披露的门禁
    return (on_disk - recipe) | set(HELPERS) | set(REPORT_ONLY)  # 并集: 显式名单兜底


def _audit_recipe_gate_names() -> list[str]:
    """抽出 ``make audit`` 实跑的门禁名 (实现层唯一真源)。

    真源是 :data:`ops.audit.run_all_gates.HARD_GATES` —— 2026-10-07 起 ``Makefile`` 的
    ``audit:`` 配方只做转发 (单行调 ``run_all_gates.py``), 因为逐行 recipe 是 fail-fast 的,
    会让第 5 道判红后**它后面 4 道从不执行**。清单因此搬进那个模块, 本函数 import 它
    而不是解析 Makefile: 解析 Makefile 只能看到转发那一行, 看不到"9 个名字"的真源。

    Returns:
        门禁名集合, 已排序 —— 排序让失败信息跨机可比。
    """
    if str(AUDIT_DIR) not in sys.path:  # 幂等: 同目录裸名导入 (与门禁自身同纪律)
        sys.path.insert(0, str(AUDIT_DIR))
    from run_all_gates import HARD_GATES  # noqa: PLC0415  延迟导入: 门禁目录不在默认 sys.path 上

    names = sorted({gate for gate, _args in HARD_GATES})  # 去重后排序: 让失败信息跨机可比
    # 顺带核一遍配方确实转发到了本模块: 否则改 Makefile 会让本测试继续对着旧真源比对
    makefile_audit = _audit_recipe_body()  # 取配方正文: 确认 Makefile 确实转发到了本模块
    assert "run_all_gates.py" in makefile_audit, (
        f"Makefile 的 audit: 配方没有转发到 run_all_gates.py —— 实际内容: {makefile_audit!r}"
    )
    return names


def _audit_recipe_body() -> str:
    """取 ``Makefile`` 里 ``audit:`` 目标的配方正文 (拼接后的命令行)。

    Returns:
        配方正文; 找不到目标时返回空串。
    """
    text = MAKEFILE.read_text(encoding="utf-8")
    collected: list[str] = []
    in_recipe = False          # 是否已定位到 audit: 目标
    for line in text.splitlines():  # 逐行找目标块
        if line.strip().startswith("audit:"):
            in_recipe = True
            continue
        if not in_recipe:
            continue
        if not line.startswith("\t"):  # 顶格行 = 目标块结束
            break
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        for report in REPORT_ONLY:  # 报告型工具若混进配方即判红 (两件事分开报, 便于定位)
            assert report not in stripped, f"报告型工具 {report} 不得进 audit: 配方 (它刻意不阻断)"
        collected.append(stripped)
    return "\n".join(collected)


def _declared_gate_names(doc_name: str) -> set[str]:
    """抽出某份声明文档里提到的**门禁**名 (裸名形态)。

    两类形态都认: 带 ``.py`` 的 (``comment_audit.py``) 与裸名 (``comment_audit``)。
    文档两种都写 —— ``CLAUDE.md`` 的清单用裸名并把后缀留给 ``code_fingerprint check``
    这种带参数的形式, ``README.md`` 则多处用 ``.py``。只认一种会让另一处**整段漏判**,
    而漏判的表现恰恰是"测试全绿但漂移还在"。

    裸名只在**清单语境**里找: 含"硬门禁"二字的那一段, 以及紧跟其后的若干行
    (``CLAUDE.md`` 的清单跨了四行才列完九个名字, 只看含标记的那一行会漏掉八个)。
    再与**实测非门禁集合**求差, 于是 README 讲扫描面机制时提到的 ``scan_roots`` /
    ``line_scope`` 被正确排除, 而不会被误报成"宣传了不存在的门禁"。

    Args:
        doc_name: 仓根下的文件名。

    Returns:
        该文档声称的门禁名集合 (裸名形态)。
    """
    text = (SKILL_ROOT / doc_name).read_text(encoding="utf-8")  # 全文: 两种形态都要从同一份文本里找
    non_gate = _non_gate_audit_modules()  # 实测非门禁集: 用来滤掉辅助模块与报告型工具
    names: set[str] = set()  # 累加器: 两形态都往里塞
    # 形态一: 带后缀, 全文范围 (它们散落在正文各处, 靠"文件真存在"收窄)
    names.update(n for n in GATE_NAME_RE.findall(text) if (AUDIT_DIR / f"{n}.py").is_file())  # 与落盘求交: 滤掉无关提及
    # 形态二: 裸名, 只在清单段内 (标记行 + 其后若干行)
    lines = text.splitlines()  # 按行切: 清单形态的判定要靠"同一行/邻近行"的语境
    for index, line in enumerate(lines):  # 逐行找"硬门禁"标记行
        if "硬门禁" not in line:
            continue
        for word in re.findall(r"[a-z_][a-z0-9_]{3,}", line):  # 标记行本身: 抽裸名候选
            if (AUDIT_DIR / f"{word}.py").is_file():
                names.add(word)
        for follow in lines[index + 1:index + 5]:  # 清单常跨行: 往后多看四行
            if "报告型" in follow or "刻意不阻断" in follow:  # 到报告型那段就停
                break
            for word in re.findall(r"[a-z_][a-z0-9_]{3,}", follow):  # 清单续行: 同样抽裸名
                if (AUDIT_DIR / f"{word}.py").is_file():
                    names.add(word)
    return names - non_gate  # 最后统一减: 非门禁不参与一致性比对


class TestGateCountDeclarationMatchesMakefile:
    """声明层与实现层必须一致 —— 数量与集合两个判据同时成立。"""

    def test_makefile_recipe_is_non_empty(self):
        """阳性对照: 实现层解析本身要能跑出东西。

        没有这条, 下面所有断言都能被"解析器返回空集合"骗过 —— 那是本仓审计
        点名过两次的形态 (「按标题抽条目返回 0 条, 看起来像没有发现」)。
        """
        names = _audit_recipe_gate_names()  # 先解析实现层: 阳性对照的前提是解析器本身没坏
        assert len(names) >= 9, f"audit: 配方只解析出 {len(names)} 个门禁: {names} —— 解析口径坏了"
        assert "verify_no_version_keys" in names, "铁律 1 的执行者必须真的在配方里"

    @pytest.mark.parametrize("doc", DECLARATION_SURFACES)
    def test_declared_set_is_a_superset_of_implementation(self, doc):
        """声明层提到的**门禁**必须都在配方里 (不许宣传不存在的门)。

        报告型工具从这项判据里排除: 文档**应该**点名它们 (那正是"刻意不阻断"的披露),
        它们不在配方里是正确的。若把它们算进 phantom, 本用例会对一份正确的文档判红。
        """
        recipe = set(_audit_recipe_gate_names())  # 实现层真源
        declared = _declared_gate_names(doc) - set(REPORT_ONLY)  # 报告型不该被算成"宣传的门禁"
        phantom = declared - recipe  # 差集: 文档说有、配方里没有的
        assert not phantom, (
            f"{doc} 提到但 audit: 配方里没有的门禁: {sorted(phantom)} —— "
            f" 照文档理解治理面的人会以为这些门在拦"
        )

    @pytest.mark.parametrize("doc", DECLARATION_SURFACES)
    def test_every_gate_is_named_in_declaration(self, doc):
        """配方里每道门禁都必须在声明层被点名 (不许有门禁没被文档覆盖)。

        这是本测试真正要抓的方向: 漏点名的门禁等于**不存在**的门禁 —— 核实员按文档
        建立工作模型时不会想到它, 于是它的失败不会引起任何人的注意。
        """
        recipe = set(_audit_recipe_gate_names())
        declared = _declared_gate_names(doc)
        unnamed = recipe - declared
        assert not unnamed, (
            f"audit: 里有但 {doc} 没点名的门禁: {sorted(unnamed)} —— "
            f" 声明层与实现层漂移 (2026-10-07 实测: CLAUDE.md 写六件而实跑九个)"
        )


class TestGateCountNumberIsNotStale:
    """数字本身也不许陈旧 —— 「几道」与「哪几道」是两个独立判据。"""

    @pytest.mark.parametrize("doc", DECLARATION_SURFACES)
    def test_declared_number_equals_recipe_length(self, doc):
        """文档里写的道数必须等于配方实跑条数。

        刻意同时断**集合**与**数量**: 只断集合时, "少一个多一个"会互相抵消;
        只断数量时, 同数量下换名字也会通过。两条都断才封住 2026-10-07 那次的形态。
        """
        recipe = _audit_recipe_gate_names()
        text = (SKILL_ROOT / doc).read_text(encoding="utf-8")
        # 匹配"九个/9 项/九件/9 条"这类中文数字与阿拉伯数字混写的道数声明
        found = re.findall(r"([一二三四五六七八九十]|\d+)\s*(?:项|道|个|件|条)\s*硬门禁", text)
        assert found, (
            f"{doc} 里找不到「N 项/道/个/件/条 硬门禁」式的道数声明 —— "
            f" 本测试要求声明显式写出数量 (若确已删除该声明, 请连同本用例一起改)"
        )
        for raw in found:
            value = _cn_number(raw)
            assert value == len(recipe), (
                f"{doc} 声明「{raw} 个硬门禁」而 audit: 实跑 {len(recipe)} 个: {recipe} —— "
                f" 照文档理解治理面的人会被误导"
            )


def _cn_number(text: str) -> int:
    """中文数字或阿拉伯数字转 int (只覆盖 1–99 的门禁数场景, 不引中文数字库)。

    Args:
        text: 已匹配的单个数字串 (中文或阿拉伯)。

    Returns:
        对应的整数。
    """
    if text.isdigit():
        return int(text)
    digits = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
    if text in digits:  # 一位中文数字: 九/六 是门禁数声明里最常见的写法
        return digits[text]
    if text == "十":
        return 10
    if len(text) == 2 and text[0] == "十":  # 十几
        return 10 + digits[text[1]]
    if len(text) == 2 and text[1] == "十":  # 几十
        return digits[text[0]] * 10
    if len(text) == 3 and text[1] == "十":  # 几十几
        return digits[text[0]] * 10 + digits[text[2]]
    raise AssertionError(f"无法解析的中文数字: {text!r}")


if __name__ == "__main__":  # 手动跑也能看结论: python test/unit/meta/test_gate_count_drift.py
    sys.exit(pytest.main([__file__, "-v"]))
