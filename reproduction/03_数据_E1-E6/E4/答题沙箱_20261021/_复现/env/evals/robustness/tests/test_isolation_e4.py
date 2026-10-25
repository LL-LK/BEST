# -*- coding: utf-8 -*-
"""evals/robustness/tests/test_isolation_e4 — E4 答案隔离自测 (生成器 + 自检器, 正反成对)。

职责: 证明「跑批输入包里没有判分依据」这件事有代码守着, 而不是靠人的自觉。
E1 的同款测试在 ``evals/nl2tool/tests/test_isolation.py``; 本件按铁律 6
(零跨实验 import) 自带一份, 不 import E1 —— 两套判定逻辑的漂移由
``evals/equivalence/tests`` 的跨实验断言另行守护。

所属实验: E4 鲁棒与安全 (68 条 = Tier P 35 / Tier W 33); 防污染口径见
docs/eval-E4-robustness-safety.md §5 (标注 schema) 与 §11 (执行流程)。

对外接口: ``TestBatchInputGenerator`` 四条断言校验白名单剥壳与产出自检;
``TestLeakageDetector`` 八条断言校验"脏的必须被抓、干净的不得误报"。

依赖与数据流: 输入是 ``evals/robustness/items.yaml`` (68 条标注, 已冻结);
产物只有 pytest 结论与一个临时跑批包, 一律落
``temp/robustness/_isolation_selftest/`` (gitignored, 只写不删 —— 不使用
pytest 的 ``tmp_path``: 它的自动回收会对用户目录发起删除, 与「临时夹具不许
碰工作区之外、更不许删东西」的约定冲突)。

关键契约与不变量: 全离线 —— 不联网、不调模型。指纹一律从标注现场抽取,
不在测试里硬编码某条用例的答案串: 标注一改硬编码就假红, 而"答案串是哪句"
本就不是本测试该关心的, 它关心的是"抽得出、抓得住"。

陷阱与边界: 最容易写出**永远绿**的假测试 —— 若 ``build_answer_fingerprints``
哪天返回空列表, 所有"未检出泄漏"的断言依然全绿, 而自检器实际已瞎。故
``test_fingerprints_nonempty`` 是这组测试的命门: 抽不出指纹必须判红。
反过来, 检测器过严会永远红 (人就不跑它了), 故同族豁免与干净文本不误报
也各钉一条断言, 两头堵死。
"""
from __future__ import annotations

# 标准库: 路径锚定
from pathlib import Path

# 第三方: pytest 夹具
import pytest

# 本地: 被测两件 (泄漏自检器 与 跑批包生成器)
from evals.robustness.check_leakage import (
    BLOCKED_PATHS,
    build_answer_fingerprints,
    build_request_index,
    load_items,
    scan_model_root,
    scan_text,
    synthesize_request,
)
from evals.robustness.make_batch_input import (
    ALLOWED_KEYS,
    ITEMS_PATH,
    load_requests,
    render_tasks_md,
    selfcheck,
    write_bundle,
)

# 临时跑批包落点: temp/ 是 gitignored 的跑批暂存区, 与 §11「产物落盘」同址;
# parents: [0]=tests/ [1]=robustness/ [2]=evals/ [3]=skill 根
SELFTEST_DIR = Path(__file__).resolve().parents[3] / "temp" / "robustness" / "_isolation_selftest"

# 用例字典 (按 id 取标注, 供污染夹具现场取真答案串 —— 不硬编码答案文本)
ITEMS_BY_ID = {str(i.get("id")): i for i in load_items(ITEMS_PATH)}


@pytest.fixture(scope="module")
def fps():
    """答案指纹表 (只建一次: 68 条标注扫一遍不便宜, 且本组用例都不改标注)。"""
    return build_answer_fingerprints(load_items(ITEMS_PATH))


@pytest.fixture(scope="module")
def reqs_and_families():
    """请求索引与同族表 (串题检测的豁免依据)。"""
    return build_request_index(load_items(ITEMS_PATH))


@pytest.fixture(scope="module")
def bundle_dir() -> Path:
    """临时跑批包目录 (只写不删; 重跑覆盖同名文件, 不留垃圾累积)。"""
    d = SELFTEST_DIR / "bundle"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _scan(text: str, owner: str, fps, reqs_and_families) -> list[str]:
    """扫一段文本, 只取 ERROR (弱信号不参与阻断判定)。"""
    reqs, families = reqs_and_families
    errs, _warns = scan_text(text, owner, fps, reqs, families)
    return errs


class TestBatchInputGenerator:
    """生成器: 白名单剥壳是否真的只留三个字段, 且产出经得起自检。"""

    def test_whitelist_only_allowed_keys(self):
        """白名单提取: 每条只剩 id/tier/request (+来源标记), 答案字段一个不留。"""
        items = load_requests(ITEMS_PATH)
        assert len(items) == 68                                 # 68 = Tier P 35 + Tier W 33
        for it in items:
            extra = set(it) - set(ALLOWED_KEYS) - {"request_source"}
            assert extra == set(), f"{it['id']} 漏出了非白名单字段: {extra}"

    def test_tier_filter_counts(self):
        """分层筛选: --tier P 只出 35 条话术题, --tier W 只出 33 条线路层题。"""
        assert len(load_requests(ITEMS_PATH, tier="P")) == 35
        assert len(load_requests(ITEMS_PATH, tier="W")) == 33

    def test_tier_w_request_has_no_injection_script(self):
        """Tier W 的请求里绝不能出现注入剧本 —— 那是隐藏变量, 剧透即 M5 假绿。"""
        utt_by_id = {k: str(i.get("utterance", "")).strip()
                     for k, i in ITEMS_BY_ID.items() if i.get("utterance")}
        for item in load_items(ITEMS_PATH):
            if item.get("tier") != "W":
                continue
            text, _src = synthesize_request(item, utt_by_id)
            inject = str((item.get("fault") or {}).get("inject", ""))
            if len(inject) >= 8:                                # 太短的剧本不入指纹, 也无从剧透
                assert inject not in text, f"{item['id']} 的合成请求里混进了注入剧本"

    def test_bundle_passes_selfcheck(self, bundle_dir, fps):
        """整包自检: 生成的 68 个单题文件里不得残留任何答案字段名或答案串。"""
        items = load_requests(ITEMS_PATH)
        write_bundle(items, bundle_dir, ITEMS_PATH,
                     Path(__file__).resolve().parents[1] / "rubric.yaml",
                     Path(__file__).resolve().parents[3] / "references" / "tools.schema.json")
        assert len(list((bundle_dir / "per_item").glob("*.txt"))) == 68
        assert selfcheck(bundle_dir, fps) == []


class TestLeakageDetector:
    """自检器: 脏的必须被抓 (五条), 干净的不得误报 (三条)。"""

    def test_fingerprints_nonempty(self, fps):
        """命门断言: 抽不出指纹时所有"未检出"都是假绿 —— 必须判红。"""
        assert len(fps) >= 50, f"答案指纹只抽出 {len(fps)} 条, 自检器可能已瞎"

    def test_clean_request_no_false_positive(self, fps, reqs_and_families):
        """不得误报: 干净的题面 (Tier P 原话 / Tier W 合成请求) 一律放行。"""
        for tid in ("RB-05", "RB-22", "RB-38"):
            item = ITEMS_BY_ID[tid]
            utt_by_id = {k: str(i.get("utterance", "")).strip()
                         for k, i in ITEMS_BY_ID.items() if i.get("utterance")}
            text, _src = synthesize_request(item, utt_by_id)
            assert _scan(text, tid, fps, reqs_and_families) == [], f"{tid} 干净题面被误报"

    def test_suggest_text_caught(self, fps, reqs_and_families):
        """拒绝建议原话 = B 级标准答案文本, 必须被抓。"""
        suggest = ITEMS_BY_ID["RB-03"]["reject"]["suggest"][0]
        errs = _scan(f"查 RA = abc, Dec = 30 附近的 ps1 源。\n提示: {suggest}", "RB-03",
                     fps, reqs_and_families)
        assert any("RB-03" in e for e in errs), f"建议原话未被抓: {errs}"

    def test_injection_script_caught(self, fps, reqs_and_families):
        """注入剧本被写进题面 = 提前剧透故障, M5 会假绿, 必须被抓。"""
        inject = ITEMS_BY_ID["RB-22"]["fault"]["inject"]
        errs = _scan(f"查 ps1 源。\n(注意: {inject})", "RB-22", fps, reqs_and_families)
        assert any("RB-22" in e for e in errs), f"注入剧本未被抓: {errs}"

    def test_stop_report_caught(self, fps, reqs_and_families):
        """停止报告原话 = D 级该说的答案文本, 必须被抓。"""
        report = ITEMS_BY_ID["RB-19"]["stop"]["report"][0]
        errs = _scan(f"查 M31。\n{report}", "RB-19", fps, reqs_and_families)
        assert any("RB-19" in e for e in errs), f"停止报告原话未被抓: {errs}"

    def test_answer_field_name_caught(self, fps, reqs_and_families):
        """标注字段名出现 = 整段 YAML 粘进来了, 必须被抓。"""
        errs = _scan('expect_envelope: {ok: false, error_code: E_BACKEND}', "RB-22",
                     fps, reqs_and_families)
        assert any("expect_envelope" in e for e in errs), f"答案字段名未被抓: {errs}"

    def test_prohibit_phrase_caught(self, fps, reqs_and_families):
        """『不许调 X』句式 = 直接告诉模型别碰哪个工具, 必须被抓。"""
        errs = _scan("查 ps1 源。禁止调用 cone_search", "RB-01", fps, reqs_and_families)
        assert any("禁调句式" in e for e in errs), f"禁调句式未被抓: {errs}"

    def test_cross_item_caught(self, fps, reqs_and_families):
        """串题: 别题原题面混进本题输入, 必须被抓。"""
        other = str(ITEMS_BY_ID["RB-05"]["utterance"])
        errs = _scan(f"查点别的。\n{other}", "RB-07", fps, reqs_and_families)
        assert any("串题" in e for e in errs), f"串题未被抓: {errs}"

    def test_shared_family_not_flagged(self, fps, reqs_and_families):
        """同族豁免: 复合题复用基础题原话是**有意的**, 不得判成串题。"""
        base = str(ITEMS_BY_ID["RB-45"]["utterance"])
        errs = _scan(base, "RB-C01", fps, reqs_and_families)
        assert errs == [], f"复合题复用基础题原话被误判成串题: {errs}"


class TestModelRootBlocklist:
    """模型可见根目录体检 (与 E1 同构, 铁律 6 下自带一份)。"""

    def test_blocklist_nonempty(self):
        """命门: 黑名单清空后体检验恒绿 — 必须判红。"""
        assert BLOCKED_PATHS, "黑名单为空 — 模型根目录体检将永远通过, 等于没设闸"

    def test_clean_skill_root_passes(self):
        """正: 拿仓内真实 skill 正文目录 (static/) 当样本, 不得误报。"""
        static = Path(__file__).resolve().parents[3] / "static"
        assert scan_model_root(static) == [], "干净的 skill 根目录被误判为含答案"

    def test_eval_dir_is_caught(self):
        """反: 根目录里出现 evals/ (标注 + 判分器 + 注入剧本), 必须判红。"""
        d = SELFTEST_DIR / "model_root_with_evals"
        (d / "evals" / "robustness").mkdir(parents=True, exist_ok=True)
        (d / "evals" / "robustness" / "items.yaml").write_text("items: []\n", encoding="utf-8")
        hits = scan_model_root(d)
        assert any(h.startswith("evals/") for h in hits), f"evals/ 出现在模型视野却未被抓: {hits}"


class TestTasksSheet:
    """单文件题卷 TASKS.md: 68 条题面一册, 且自带禁看清单。

    命门是 ``test_sheet_is_clean``: 题卷要印黑名单, 而黑名单的**理由文字**与
    来源标记都可能变成泄漏源 —— 实测踩过一次 (复合题的来源标记写成了字段名
    ``base_case``, 于是题卷自己触发了字段名告警)。
    """

    @pytest.fixture(scope="module")
    def sheet(self) -> str:
        """渲染题卷 (与生成器同一函数: 测的就是跑批时真正拿到的那份)。"""
        return render_tasks_md(load_requests(ITEMS_PATH))

    def test_all_requests_verbatim(self, sheet):
        """68 条一字不改全在: 漏一条或改一个字, 跑批就少测/错测一道题。"""
        reqs = {it["id"]: it["request"] for it in load_requests(ITEMS_PATH)}
        assert len(reqs) == 68
        for tid, text in reqs.items():
            assert tid in sheet, f"题卷缺 {tid}"
            assert text in sheet, f"{tid} 的请求未逐字出现在题卷里"

    def test_one_session_warning_present(self, sheet):
        """元守卫: 题卷把 68 条摆在一起, 警示语被删就成了串题说明书。"""
        assert "一次只复制一个题块" in sheet, "题卷缺'一次只复制一个题块'的警示"

    def test_injection_warning_present(self, sheet):
        """Tier W 那 33 条必须带"别剧透注入剧本"的提醒 (M5 假绿的头号来源)。"""
        assert "注入器现场施加" in sheet, "题卷缺 Tier W 的注入剧透警告"

    def test_blocklist_present(self, sheet):
        """禁看清单在题卷里: 拿题卷的人就是喂模型的人, 规矩得跟着题走。"""
        assert "不许让模型看到的文件" in sheet
        rendered = sum(1 for rel, _ in BLOCKED_PATHS if rel in sheet)
        assert rendered >= 10, f"禁看清单只渲染出 {rendered} 条 — 黑名单没接进题卷"

    def test_sheet_is_clean(self, sheet, fps, reqs_and_families):
        """命门: 题卷本身不得含任何答案串/字段名 (黑名单理由与来源标记也算)。"""
        reqs, families = reqs_and_families
        errs, _warns = scan_text(sheet, "", fps, reqs, families, skip_cross=True)
        assert errs == [], f"题卷自身泄漏了判分依据: {errs}"
