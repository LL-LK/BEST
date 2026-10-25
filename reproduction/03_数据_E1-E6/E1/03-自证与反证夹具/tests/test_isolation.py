# -*- coding: utf-8 -*-
"""evals/nl2tool/tests/test_isolation — E1 答案隔离自测 (生成器 + 自检器, 正反成对)。

职责: 证明「跑批输入包里没有答案」这件事有代码守着, 而不是靠人的自觉。
两条被测件各有分工: ``make_batch_input`` 保证**生成器产出**干净 (白名单剥壳),
``check_leakage`` 保证**人最终喂给模型的文本**干净 (剪贴板管不到, 只能事后扫)。

所属实验: E1 NL→工具决策; 防污染铁律见 docs/eval-E1-nl2tool.md §9。

对外接口: ``TestBatchInputGenerator`` 三条断言校验白名单剥壳与产出自检;
``TestLeakageDetector`` 五条断言校验"脏的必须被抓、干净的不得误报"。

依赖与数据流: 输入是 ``evals/nl2tool/tasks.yaml`` (26 条标注, 已冻结) 与
``references/tools.schema.json`` (版本 hash 锚); 产物只有 pytest 结论与一个
临时跑批包, 一律落 ``temp/nl2tool/_isolation_selftest/`` (gitignored, 只写不删
—— 不使用 pytest 的 ``tmp_path``: 它的自动回收会对用户目录发起删除, 与
「临时夹具不许碰工作区之外、更不许删东西」的约定冲突)。

关键契约与不变量: 全离线 — 不联网、不调模型; 测试**不写**仓库内任何目录
(只用 tmp_path), 因此可反复重放。指纹一律从标注现场抽取, 不在测试里硬编码
某条题目的具体答案串 —— 标注一改硬编码就假红, 而"答案串是哪句"本就不是
本测试该关心的, 它关心的是"抽得出、抓得住"。

陷阱与边界: 最容易写出**永远绿**的假测试 —— 若 ``build_answer_fingerprints``
哪天返回空列表, 所有"未检出泄漏"的断言依然全绿, 而自检器实际已瞎。
故 ``test_fingerprints_nonempty`` 是这组测试的命门: 抽不出指纹必须判红。
反过来, 检测器过严会永远红 (人就不跑它了), 故 ``test_clean_text_no_false_positive``
把"不得误报"也钉成断言, 两头堵死。
"""
from __future__ import annotations

# 标准库: JSON 落盘 (构造污染夹具) / 路径
import json
from pathlib import Path

# 第三方: pytest
import pytest

# 本地: 被测两件 (生成器 与 泄漏自检器)
from evals.nl2tool.check_leakage import (
    BLOCKED_PATHS,
    build_answer_fingerprints,
    build_utterance_index,
    load_tasks,
    scan_model_root,
    scan_text,
)
from evals.nl2tool.context_primers import load_context_bindings
from evals.nl2tool.graders import grade_task
from evals.nl2tool.make_batch_input import (
    ANSWER_KEYS,
    PRIMERS_PATH,
    SCHEMA_PATH,
    TASKS_PATH,
    load_primers,
    load_utterances,
    render_tasks_md,
    selfcheck,
    write_bundle,
)


# 临时跑批包落点: temp/ 是 gitignored 的跑批暂存区, 与 §8「真实跑批产物落 temp/」同址;
# parents: [0]=tests/ [1]=nl2tool/ [2]=evals/ [3]=skill 根
SELFTEST_DIR = Path(__file__).resolve().parents[3] / "temp" / "nl2tool" / "_isolation_selftest"


@pytest.fixture(scope="module")
def bundle_dir() -> Path:
    """临时跑批包目录 (只写不删; 重跑覆盖同名文件, 不留垃圾累积)。"""
    d = SELFTEST_DIR / "bundle"
    d.mkdir(parents=True, exist_ok=True)
    return d


@pytest.fixture(scope="module")
def tasks() -> list[dict]:
    """26 条标注 (模块级只读一次, 标注已冻结, 全程不写)。"""
    return load_tasks(TASKS_PATH)


@pytest.fixture(scope="module")
def fingerprints(tasks) -> list[tuple[str, str]]:
    """从标注现场抽出的答案指纹 (不硬编码具体题目内容)。"""
    return build_answer_fingerprints(tasks)


@pytest.fixture(scope="module")
def utterances(tasks) -> dict[str, str]:
    """题号 → 用户原话 (用于构造串题夹具)。"""
    return build_utterance_index(tasks)


class TestBatchInputGenerator:
    """生成器侧: 白名单剥壳是否真的把答案剥干净了。"""

    def test_bundle_contains_only_id_and_utterance(self, bundle_dir: Path):
        """正: 产出每条只有 id + utterance, 一个答案字段都不许有。"""
        items = load_utterances(TASKS_PATH)
        # 2026-10-07: 题数由 26 增至 28 (新增 NL2T-27/NL2T-28 两条 reject 路由)
        assert len(items) == 28, f"标注集应 28 条, 实得 {len(items)}"

        out = bundle_dir
        write_bundle(items, out, SCHEMA_PATH, TASKS_PATH)

        for line in (out / "prompts.jsonl").read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            obj = json.loads(line)
            assert set(obj) == {"id", "utterance"}, f"跑批包混入了多余字段: {sorted(obj)}"

    def test_bundle_selfcheck_clean(self, bundle_dir: Path):
        """正: 生成器产出自检必须干净 (否则产出物本身就有答案残留)。"""
        out = bundle_dir
        write_bundle(load_utterances(TASKS_PATH), out, SCHEMA_PATH, TASKS_PATH)
        assert selfcheck(out) == [], f"产出自检未过: {selfcheck(out)}"

    def test_no_answer_key_leaks_into_per_task_files(self, bundle_dir: Path):
        """正: 单题纯文本文件 (人直接粘贴的面) 里不得出现任何答案字段名。"""
        out = bundle_dir
        write_bundle(load_utterances(TASKS_PATH), out, SCHEMA_PATH, TASKS_PATH)

        files = sorted((out / "per_task").glob("*.txt"))
        # 2026-10-07: 随题卷增至 28 条 (一个文件一句话的规矩不变)
        assert len(files) == 28, f"单题文件应 28 个, 实得 {len(files)}"
        for f in files:
            text = f.read_text(encoding="utf-8")
            for key in ANSWER_KEYS:
                assert key.lower() not in text.lower(), f"{f.name} 残留答案字段 '{key}'"


class TestContextPrimerGuard:
    """上下文前缀的护栏: 补上文能救活续接题, 但补错了方向会把澄清题喂饱。"""

    def test_no_context_list_is_declared(self):
        """正: 反向清单必须存在且非空 —— 空清单意味着 clarify/reject 题随时可能被喂饱。"""
        primers, no_ctx = load_primers(PRIMERS_PATH)
        assert no_ctx, "no_context 清单为空 — 缺指代就是考点的那几题将无人守护"
        assert primers, "未配置任何 primer — 续接题 ('刚才那片天区') 会变成无解题"
        assert not (set(primers) & no_ctx), f"同一题既补上文又声明禁止: {set(primers) & no_ctx}"

    def test_priming_a_no_context_task_is_rejected(self):
        """反: 给『缺指代就是考点』的题补上文, 必须显式失败 (否则该题从应澄清变可作答)。"""
        bad = SELFTEST_DIR / "bad_primer_noctx.yaml"
        bad.write_text(
            "primers:\n  NL2T-18:\n    intent: '手滑补的'\n    turns:\n      - {role: user, text: '那个源是 M31'}\n"
            "no_context:\n  - NL2T-18\n",
            encoding="utf-8",
        )
        with pytest.raises(SystemExit, match="no_context"):
            load_primers(bad)

    def test_assistant_turn_in_primer_is_rejected(self):
        """反: primer 里写上一轮助手的回答 = 示范正确调用, 比漏题更直接, 必须显式失败。"""
        bad = SELFTEST_DIR / "bad_primer_assistant.yaml"
        bad.write_text(
            "primers:\n  NL2T-06:\n    turns:\n      - {role: user, text: '这个天区有多少源?'}\n"
            "      - {role: assistant, text: '先调 cone_search 再调 count'}\n",
            encoding="utf-8",
        )
        with pytest.raises(SystemExit, match="assistant"):
            load_primers(bad)


class TestContextBinding:
    """占位符具化 + convert 维口径: 杜撰必须现形, 澄清不得被当错值, 诚实不得误伤。

    背景 (2026-10-06 实测): 未注入上文时, 标注里 ``<上下文天区的 ra>`` 按通配处理,
    模型杜撰坐标照样满分 —— 实测 NL2T-09/10/12 杜撰作答 0.800 且零红线, 而规矩
    澄清只拿 0.100 还背 ``S1:convert_mismatch`` 红线。判分器在**奖杜撰、罚诚实**。
    本组把修好的口径钉住, 两头都要断言 (只测一边等于没测)。
    """

    def _grade(self, tid: str, calls: list, bindings: dict | None):
        """按题号取标注并判分 (schema 不注入: 本组只关心占位符与 convert 口径)。"""
        task = next(t for t in load_tasks(TASKS_PATH) if t["id"] == tid)
        return grade_task(task, {"tool_calls": calls, "answer_text": "…", "http_requests": 0},
                          {}, bindings)

    def test_fabricated_coord_is_free_without_binding(self):
        """正(旧行为留档): 不注入上文时占位符通配, 杜撰坐标不扣分。

        这条断言**不是**在夸这个行为好 —— 它是在钉住"未具化批的分数含水分"
        这一事实, 并逼报告用 ``context_binding.unbound_note`` 点名它。
        """
        g = self._grade("NL2T-10", [{"tool": "cone_search", "args": {
            "ra": 99.9, "dec": -11.1, "radius_arcsec": 300.0, "catalog": "ps1", "max_rows": 1000}}], None)
        assert g["dims"]["param"] == 1.0, "未具化时杜撰坐标应通配过关 (这正是水分来源)"

    def test_fabricated_coord_is_punished_with_binding(self):
        """反: 注入上文后占位符具化, 杜撰坐标必须现形 (param/convert 掉分 + 红线)。"""
        b = load_context_bindings().get("NL2T-10")
        assert b, "NL2T-10 应配置 bindings, 否则具化形同虚设"
        g = self._grade("NL2T-10", [{"tool": "cone_search", "args": {
            "ra": 99.9, "dec": -11.1, "radius_arcsec": 300.0, "catalog": "ps1", "max_rows": 1000}}], b)
        assert g["dims"]["param"] == 0.0, f"具化后杜撰坐标应判错, 实得 {g['dims']['param']}"
        assert g["dims"]["convert"] == 0.0, "杜撰坐标的换算同样不该算对"
        assert "S1:convert_mismatch" in g["red_lines"], "杜撰坐标应触发静默错值红线"

    def test_honest_coord_still_passes_with_binding(self):
        """正: 用上文声明的坐标作答必须满分 —— 具化只罚杜撰, 不得误伤诚实。"""
        b = load_context_bindings().get("NL2T-10")
        g = self._grade("NL2T-10", [{"tool": "cone_search", "args": {
            "ra": b["ra"], "dec": b["dec"], "radius_arcsec": 300.0,
            "catalog": "ps1", "max_rows": 1000}}], b)
        assert g["dims"]["param"] == 1.0, "按上文作答应满分 — 具化不得误伤"
        assert g["red_lines"] == [], f"诚实作答不该有红线: {g['red_lines']}"

    def test_zero_call_convert_is_na_not_s1(self):
        """正: 零调用 (合法澄清) 的 convert 记 N/A, 不得记 0 分更不得触发 S1 红线。

        这是本次修正的**核心**: S1 的定义 (§3) 是"拿到了看起来正常的错误结果",
        零调用连结果都没有。把"没做"当"做错"会让模型被逼去杜撰上下文。
        """
        g = self._grade("NL2T-10", [], None)
        assert g["dims"]["convert"] is None, f"零调用的 convert 应记不适用, 实得 {g['dims']['convert']}"
        assert "S1:convert_mismatch" not in g["red_lines"], "合法澄清不得背静默错值红线"

    def test_wrong_conversion_still_triggers_s1(self):
        """反: 确实调用了但换算错, 仍须触发 S1 红线 —— 不能为了修误伤而放走真错。"""
        task = next(t for t in load_tasks(TASKS_PATH) if t["id"] == "NL2T-10")
        g = grade_task(task, {"tool_calls": [{"tool": "cone_search", "args": {
            "ra": 10.68, "dec": 41.27, "radius_arcsec": 5.0, "catalog": "ps1"}}],
            "answer_text": "…", "http_requests": 0}, {}, {"ra": 10.68, "dec": 41.27})
        assert g["dims"]["convert"] == 0.0, "半径 5 角秒 (未换算) 应判换算错"
        assert "S1:convert_mismatch" in g["red_lines"], "真换算错误必须进红线"


class TestLeakageDetector:
    """自检器侧: 脏的必须被抓 (反), 干净的不得误报 (正)。"""

    def test_fingerprints_nonempty(self, fingerprints):
        """命门断言: 抽不出指纹 = 自检器已瞎, 后面所有"未检出"都是假的。"""
        assert fingerprints, (
            "答案指纹为空 — 检测器将永远报『未检出』, 本组其余断言全部失去意义"
        )

    def test_answer_fingerprint_is_caught(self, fingerprints):
        """反: 输入里出现 anti_patterns 的赋值式指纹, 必须判 ERROR。"""
        fp, src = fingerprints[0]
        errors, _warns = scan_text(f"提示: 注意别写成 {fp}", "NL2T-01", fingerprints, {})
        assert errors, f"指纹 '{fp}' (出自 {src}) 出现在输入里却未被检出 — 检测器漏判"

    def test_answer_field_name_is_caught(self, fingerprints):
        """反: 输入里出现标注字段名 (说明整段 YAML 被粘进来了), 必须判 ERROR。"""
        errors, _warns = scan_text(
            "route: clarify\nexpect_tools:\n  - tool: describe_catalog", "NL2T-01", fingerprints, {}
        )
        assert errors, "标注字段名出现在输入里却未被检出 — 检测器漏判"

    def test_cross_task_contamination_is_caught(self, utterances):
        """反: 某题输入里混进别题原话 (26 条被一次性灌进同一会话), 必须判 ERROR。"""
        assert len(utterances) >= 2
        tids = sorted(utterances)
        owner, other = tids[0], tids[1]
        errors, _warns = scan_text(
            f"{utterances[owner]}\n\n另外一道: {utterances[other]}", owner, [], utterances
        )
        assert any("串题" in e for e in errors), f"混进 {other} 的原话却未判串题 — 检测器漏判"

    def test_clean_text_no_false_positive(self, fingerprints, utterances):
        """正: 干净的单题输入不得误报 (检测器过严会让人干脆不跑它)。"""
        text = "查找 RA=120.3°、Dec=−20.4°、半径 5″ 内的标准星。"
        errors, warns = scan_text(text, "NL2T-11", fingerprints, utterances)
        assert errors == [], f"干净输入被误判为泄漏: {errors}"
        assert warns == [], f"干净输入触发弱信号: {warns}"

    def test_golden_trace_marker_is_warn_not_error(self, fingerprints):
        """正: 金标准轨迹标记只告警不阻断 — 它提示人拿错了文件, 不是答案泄漏本身。"""
        errors, warns = scan_text(
            "source: golden-from-annotation", "NL2T-01", fingerprints, {}
        )
        assert errors == [], f"金标准标记不该判 ERROR: {errors}"
        assert any("golden" in w for w in warns), "金标准标记应告警提示人核对文件来源"


class TestModelRootBlocklist:
    """模型可见根目录体检: 大模型一旦有文件读取能力, "求它别看"不如"不给它看"。

    命门同样是防假绿: 若黑名单哪天被清空, ``scan_model_root`` 恒返空,
    所有"模型视野干净"的结论都还是绿的。故第一条断言黑名单本身非空。
    """

    def _root(self, name: str) -> Path:
        """造一个模型可见根目录 (每用例一个目录: 本目录只写不删, 共用会被上一条污染)。"""
        d = SELFTEST_DIR / name
        d.mkdir(parents=True, exist_ok=True)
        (d / "SKILL.md").write_text("# skill\n", encoding="utf-8")
        (d / "references").mkdir(exist_ok=True)
        (d / "references" / "tools.schema.json").write_text("{}", encoding="utf-8")
        return d

    @pytest.fixture
    def clean_root(self) -> Path:
        """干净根: 直接拿仓内真实的 skill 正文目录 (static/) 当样本。

        不用临时目录是因为本目录"只写不删": 上一条造污染的用例会在同一目录里
        留下 evals/, 再来一轮干净用例就被自己的残渣判红。取**真实目录**还多一层
        收益 —— 哪天有人把评测文件塞进 static/, 这条会真红, 而那本来就该红。
        """
        return Path(__file__).resolve().parents[3] / "static"

    def test_blocklist_nonempty(self):
        """命门: 黑名单清空后体检验恒绿 — 必须判红。"""
        assert BLOCKED_PATHS, "黑名单为空 — 模型根目录体检将永远通过, 等于没设闸"

    def test_clean_skill_root_passes(self, clean_root):
        """正: 只有 skill 正文的根目录不得误报。"""
        assert scan_model_root(clean_root) == [], "干净的 skill 根目录被误判为含答案"

    def test_eval_dir_is_caught(self):
        """反: 根目录里出现 evals/ (标注 + 判分器 + 轨迹), 必须判红。"""
        d = self._root("model_root_with_evals")
        (d / "evals" / "nl2tool").mkdir(parents=True, exist_ok=True)
        (d / "evals" / "nl2tool" / "tasks.yaml").write_text("tasks: []\n", encoding="utf-8")
        hits = scan_model_root(d)
        assert any(h.startswith("evals/") for h in hits), f"evals/ 出现在模型视野却未被抓: {hits}"

    def test_eval_doc_is_caught(self):
        """反: 方案文档 (§5 是 26 题答案表) 单独被拷出来, 也要被抓。"""
        d = self._root("model_root_with_doc")
        (d / "docs").mkdir(exist_ok=True)
        (d / "docs" / "eval-E1-nl2tool.md").write_text("# E1\n", encoding="utf-8")
        hits = scan_model_root(d)
        assert any("eval-E1-nl2tool.md" in h for h in hits), f"方案文档未被抓: {hits}"


class TestTasksSheet:
    """单文件题卷 TASKS.md: 26 条题面一册, 且自带"哪些文件不许看"。

    这一组的命门是 ``test_sheet_is_clean``: 题卷里印了黑名单, 而黑名单的**理由
    文字**本身就可能变成泄漏源 —— 实测踩过一次 (理由里写了
    ``radius_arcsec = 60/3600``, 于是题卷自己触发了答案指纹告警)。题卷是要拿去
    喂模型的人看的, 它自己脏了就是最讽刺的泄漏。
    """

    @pytest.fixture(scope="module")
    def sheet(self) -> str:
        """渲染题卷 (与生成器同一函数: 测的就是跑批时真正拿到的那份)。"""
        primers, no_ctx = load_primers(PRIMERS_PATH)
        return render_tasks_md(load_utterances(TASKS_PATH), primers, no_ctx)

    def test_all_utterances_verbatim(self, sheet):
        """28 条一字不改全在: 漏一条或改一个字, 跑批就少测/错测一道题。"""
        utts = {it["id"]: it["utterance"] for it in load_utterances(TASKS_PATH)}
        assert len(utts) == 28
        for tid, utt in utts.items():
            assert tid in sheet, f"题卷缺 {tid}"
            assert utt in sheet, f"{tid} 的原话未逐字出现在题卷里"

    def test_one_session_warning_present(self, sheet):
        """元守卫: 题卷把 26 条摆在一起, 警示语被删就成了串题说明书。"""
        assert "一次只复制一个题块" in sheet, "题卷缺'一次只复制一个题块'的警示 — 等于串题说明书"

    def test_blocklist_present(self, sheet):
        """禁看清单在题卷里: 拿题卷的人就是喂模型的人, 规矩得跟着题走。"""
        assert "不许让模型看到的文件" in sheet
        rendered = sum(1 for rel, _ in BLOCKED_PATHS if rel in sheet)
        assert rendered >= 15, f"禁看清单只渲染出 {rendered} 条 — 黑名单没接进题卷"

    def test_sheet_is_clean(self, sheet, fingerprints, utterances):
        """命门: 题卷本身不得含任何答案串/字段名 (黑名单的理由文字也算)。"""
        errors, warns = scan_text(sheet, "", fingerprints, utterances, skip_cross=True)
        assert errors == [], f"题卷自身泄漏了答案: {errors}"
        assert warns == [], f"题卷触发弱信号: {warns}"
