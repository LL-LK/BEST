# -*- coding: utf-8 -*-
"""src.knowledge_slots + 知识沉底管道的回归门禁 (A8-02 / A8-03 / A8-05)。

守的缺口形态: 知识沉底 A 路 (确定性槽位) 曾是**零测试覆盖**的一整块 ——
``src/knowledge_slots.py`` 224 行 (别名表 / 越界防护 / 截断 / 后缀优先级 / 维度白名单),
全仓只有 CLI、模块自身与一处注释引用它。删掉任一 fragment 或任一分支都不会有测试变红,
于是「看起来能用、实际永远不命中」的形态可以一直躺着 (A8-03 实测:
``resolve_slots({"catalog": "ps1"})`` 与 ``{"error_kind": ...}`` 恒返回 ``[]``,
而管道仍在为它们产出建议)。

本文件盯四件事:
  1. **具体 fragment 能被解析命中** —— 至少断到一个真实文件, 挡住"永远不命中";
  2. 别名解析 / 后缀优先级 / 维度白名单的确定性契约;
  3. 越界防护 (纵深防御两道) 与截断留痕 (不许静默截断);
  4. 沉底管道只给**当前可命中**的槽位建议, 且加载地图 (manifest) 覆盖全部片段。
"""
from __future__ import annotations

# 标准库: dataclasses (frozen 实例异常) / importlib 按路径装载 ops/ 件 (ops/ 不是包) /
#         sys 路径锚定 / 类型标注
# 第三方: pytest (raises / parametrize / monkeypatch) / PyYAML (manifest 解析)
# 本地: 被测两件 —— src.knowledge_slots 与 ops/knowledge_capture
import dataclasses
import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

SKILL_ROOT = Path(__file__).resolve().parents[3]      # 上溯三级 = 仓根 (本件在 test/unit/knowledge/ 下三级)
if str(SKILL_ROOT) not in sys.path:                   # 锚定导入根: 与 test/conftest.py 同一纪律, 不重复插
    sys.path.insert(0, str(SKILL_ROOT))

from src import knowledge_slots  # noqa: E402  (路径锚定之后才能导入)

FRAGMENTS_DIR = SKILL_ROOT / "static" / "fragments"    # 槽位物理根: 逐文件核用

# 至少要有一个具体 fragment 被断到 —— 键、文件路径、正文三者同时对上才算命中。
# 键里带的值是**解析后的文件 stem** (不是调用方说的短名): 这样 list_slots() 列出的
# 台账键与 resolve_slots() 返回的键是同一套命名, 两处不会各说各话。
_CONCRETE_CASE = ("algo_mode", "two_phase", "best_two_phase")   # (维度, 调用方短名, 实际文件 stem)

# 多维同时给的上下文: 用来断"结果顺序 = 维度声明顺序"
_CONTEXT_ALL_HITS = [("algo_mode", "two_phase"), ("data_source", "catalogs"), ("target_type", "ttype")]


def _load_capture() -> Any:
    """按路径装载 ops/knowledge_capture.py (ops/ 不是包, 只能这样加载; 与 CLI 同口径)。"""
    spec = importlib.util.spec_from_file_location(                                       # 路径装载 spec
        "knowledge_capture_under_test", SKILL_ROOT / "ops" / "knowledge_capture.py")      # 被测件路径
    module = importlib.util.module_from_spec(spec)                                         # 先建模块对象
    spec.loader.exec_module(module)                                                       # 再执行模块体
    return module                                                                          # 交回调用方


class TestSlotResolution:
    """槽位必须真能解析命中 —— 否则 A 路就是一套摆设。"""

    def test_concrete_fragment_is_hit(self):
        """一个具体 fragment 必须命中: 键、绝对路径、正文三者与盘上文件一致。"""
        dimension, value, stem = _CONCRETE_CASE                  # 拆出三元组, 下文按名字用
        expected = FRAGMENTS_DIR / dimension / f"{stem}.yaml"     # 盘上那个文件的应然位置
        assert expected.is_file(), f"测试锚定的片段不存在: {expected}"   # 锚点本身得先在
        slots = knowledge_slots.resolve_slots({dimension: value})        # 短名进, 应命中
        assert [slot.key for slot in slots] == [f"{dimension}/{stem}"], "短名未解析到该 fragment"
        slot = slots[0]                                           # 只此一个: 确定性契约不许多命中
        assert Path(slot.path) == expected.resolve()              # 溯源路径必须指向盘上那个文件
        assert slot.text == expected.read_text(encoding="utf-8")  # 正文是文件原文, 不是拼的摘要
        assert slot.truncated is False                            # 默认上限下不该截断
        assert expected.read_text(encoding="utf-8").strip(), "片段正文为空: 命中了等于没命中"

    def test_key_carries_resolved_stem(self):
        """键带解析后的文件 stem: 调用方按 list_slots 的台账就能原样回查。"""
        dimension, value, stem = _CONCRETE_CASE                  # 同一锚点
        (slot,) = knowledge_slots.resolve_slots({dimension: value})       # 解包: 恰好一个
        assert slot.key == f"{dimension}/{stem}"                  # 别名解析后落到实际文件名
        assert knowledge_slots.SLOT_ALIASES[(dimension, value)] == stem   # 别名表本身也登记着

    def test_alias_table_resolves_short_names(self):
        """别名表: 短名 → 实际文件 stem, 逐条都必须落到真实文件。"""
        for (dimension, value), stem in knowledge_slots.SLOT_ALIASES.items():   # 逐条核, 不抽样
            hits = knowledge_slots.resolve_slots({dimension: value})             # 短名解析
            assert len(hits) == 1, f"别名 {(dimension, value)} 未命中"            # 一对一: 不许多命中
            assert hits[0].key == f"{dimension}/{stem}"                          # 键带解析后的 stem
            expected = FRAGMENTS_DIR / dimension / f"{stem}.yaml"               # yaml 形态
            alt = FRAGMENTS_DIR / dimension / f"{stem}.md"                       # md 形态 (data_source 用它)
            assert Path(hits[0].path) in (expected.resolve(), alt.resolve()), \
                f"别名 {(dimension, value)} → {stem} 落点不对: {hits[0].path}"   # 落点必须是这两个之一

    def test_direct_stem_also_resolves(self):
        """没有别名时按原值查 (同名文件) —— 两条路径都要能取到同一片文本。"""
        dimension, _, stem = _CONCRETE_CASE                      # 短名这一路
        (aliased,) = knowledge_slots.resolve_slots({dimension: "two_phase"})     # 经别名表
        (direct,) = knowledge_slots.resolve_slots({dimension: stem})              # 直接给 stem
        assert aliased.text == direct.text and aliased.path == direct.path       # 同一片, 同一路径

    def test_suffix_priority_prefers_structured(self):
        """同名多后缀并存时取先命中者 (yaml 优先于 md): 结构化优先。"""
        (slot,) = knowledge_slots.resolve_slots({_CONCRETE_CASE[0]: _CONCRETE_CASE[2]})   # 按 stem 查
        assert slot.path.endswith(".yaml"), "结构化片段应优先于同名 .md"      # 命中的是 .yaml 那份

    def test_case_insensitive_and_whitespace(self):
        """槽位键大小写/空白不敏感: 归一化在这一步收口。"""
        (slot,) = knowledge_slots.resolve_slots({_CONCRETE_CASE[0]: "  TWO_PHASE  "})      # 脏输入
        assert slot.key == f"{_CONCRETE_CASE[0]}/{_CONCRETE_CASE[2]}"                      # 归一后同一片


class TestDeterministicContract:
    """确定性契约: 不猜、不模糊匹配、坏输入不拖垮整批。"""

    def test_no_fuzzy_fallback(self):
        """不存在的值必须落空, 绝不能退而求其次返回「最像的那个」。"""
        assert knowledge_slots.resolve_slots({_CONCRETE_CASE[0]: "two_phase_old"}) == []   # 近似名不命中
        assert knowledge_slots.resolve_slots({_CONCRETE_CASE[0]: "two"}) == []             # 前缀也不命中

    def test_unknown_dimension_is_ignored(self):
        """白名单外的键一律忽略 (新增维度必须先在 SLOT_DIMENSIONS 登记)。"""
        assert knowledge_slots.resolve_slots({"not_a_dimension": "whatever"}) == []        # 不在白名单
        assert "not_a_dimension" not in knowledge_slots.SLOT_DIMENSIONS                    # 也不该被登记

    def test_result_order_follows_dimension_declaration(self):
        """结果顺序 = SLOT_DIMENSIONS 的声明顺序 (改序会改结果序, 故要可预期)。"""
        context = {dimension: value for dimension, value in _CONTEXT_ALL_HITS}    # 三维同时给
        hits = [slot.key for slot in knowledge_slots.resolve_slots(context)]       # 实际顺序
        assert [key.split("/")[0] for key in hits] == [d for d, _ in _CONTEXT_ALL_HITS]     # 与声明序一致
        declared = [d for d in knowledge_slots.SLOT_DIMENSIONS if any(k.startswith(d + "/") for k in hits)]
        assert [key.split("/")[0] for key in hits] == declared               # 排序键就是白名单序

    def test_repeated_calls_are_identical(self):
        """同样输入永远同样输出 (A 路的立身之本是"可预测", 不是"搜索")。"""
        context = dict(_CONTEXT_ALL_HITS)                                    # 复制一份防被就地改
        first = [slot.as_dict() for slot in knowledge_slots.resolve_slots(context)]    # 第一趟
        second = [slot.as_dict() for slot in knowledge_slots.resolve_slots(context)]   # 第二趟
        assert first == second                                               # 两次必须逐字相等

    @pytest.mark.parametrize("bad", [None, "", "   ", 123, {"a": 1}, ["x"]])
    def test_garbage_never_raises(self, bad: Any):
        """坏输入 = 该维度不命中, 永远不抛异常 (A 路不能被一条脏日志打断)。"""
        assert knowledge_slots.resolve_slots({"algo_mode": bad}) == []        # 任何垃圾都只是不命中

    def test_slot_as_dict_shape(self):
        """as_dict 供日志/契约消费: 四字段浅字典, truncated 必须外带。"""
        (slot,) = knowledge_slots.resolve_slots({_CONCRETE_CASE[0]: _CONCRETE_CASE[1]})   # 取一个
        assert set(slot.as_dict()) == {"key", "path", "text", "truncated"}    # 字段集固定, 下游按名取

    def test_slot_is_immutable(self):
        """槽位不可变: 可安全缓存与按值比较。"""
        (slot,) = knowledge_slots.resolve_slots({_CONCRETE_CASE[0]: _CONCRETE_CASE[1]})   # 取一个
        with pytest.raises(dataclasses.FrozenInstanceError):                  # frozen dataclass: 赋值即拒
            slot.text = "改了"                # type: ignore[misc]            # 故意写坏, 断言被拦


class TestBoundaryGuard:
    """越界防护: 纵深防御两道 (值白名单 + 路径归属), 少一道就可能被路径穿越。"""

    def test_path_outside_skill_root_is_rejected(self, tmp_path: Path):
        """仓外的路径一律判越界: 只比字符串前缀会被 ``/root-x`` 型兄弟目录骗过。"""
        outside = tmp_path / "evil.yaml"                                     # 仓外的一个真文件
        outside.write_text("secret", encoding="utf-8")                       # 有内容, 排除"不存在"这条理由
        assert knowledge_slots._safe_resolve(outside) is None                # 归属判定放最后

    def test_traversal_value_never_reaches_filesystem(self):
        """含路径分隔符/.. 的取值在归一化那一步就被拒, 到不了文件系统层。"""
        for bad in ("../../etc/passwd", "..", "../best_two_phase", "a/b", "a\\b", "two phase"):
            assert knowledge_slots._normalize_value(bad) is None, bad         # 逐个点名, 失败时看得出是哪个

    @pytest.mark.parametrize("value", ["two_phase", "two-phase", "TWO_PHASE", "two_phase1"])
    def test_allowed_value_charset(self, value: str):
        """白名单字符集: 字母数字与 _ - , 其余一律拒。"""
        normalized = knowledge_slots._normalize_value(value)                  # 归一入口
        assert normalized == value.lower()                                    # 只做小写化, 不做别的改写

    def test_dimension_traversal_is_ignored(self):
        """维度名越界 (如 ``../..``) 不得被当目录名直接用。"""
        assert knowledge_slots.resolve_slots({"../../etc": "passwd"}) == []    # 键名不是白名单 → 忽略
        assert knowledge_slots._read_slot("..", "..") is None                 # 直调也要拒

    def test_list_slots_rejects_unknown_dimension(self):
        """list_slots 只认白名单维度, 且不因目录缺失而报错。"""
        assert knowledge_slots.list_slots("catalog") == []     # 目录不存在 → 视为无槽位, 不抛
        assert knowledge_slots.list_slots("../..") == []       # 越界维度名同样不认


class TestTruncation:
    """截断必须留痕: 静默截断会被下游当全文消费。"""

    def test_default_cap_not_truncated(self):
        """默认上限下现有片段不该被截 (若真被截, 说明片段本身超长, 需人工确认)。"""
        (slot,) = knowledge_slots.resolve_slots({_CONCRETE_CASE[0]: _CONCRETE_CASE[1]})   # 取一个
        assert slot.truncated is False and "已截断" not in slot.text        # 标志为假且正文无截断标记

    def test_truncation_marks_and_caps(self, monkeypatch: pytest.MonkeyPatch):
        """超出上限时截断 + 显式标记, 且截断事实随对象走 (不必从文本猜)。"""
        monkeypatch.setattr(knowledge_slots, "MAX_SLOT_CHARS", 20)          # 压到 20 字符必触发
        (slot,) = knowledge_slots.resolve_slots({_CONCRETE_CASE[0]: _CONCRETE_CASE[1]})   # 重读
        assert slot.truncated is True                                       # 截断事实外带
        assert slot.text.endswith("\n...[已截断]")                          # 文本里也留了痕
        source = (FRAGMENTS_DIR / _CONCRETE_CASE[0] / f"{_CONCRETE_CASE[2]}.yaml").read_text(encoding="utf-8")
        assert slot.text.startswith(source[:20])                            # 截的是前 20 字符, 不是字节
        assert knowledge_slots.MAX_SLOT_CHARS == 20                        # 猴补丁生效 (按字符数判)


class TestListSlots:
    """槽位台账: 存在的片段必须列得出来, 列出来的必须真在盘上。"""

    def test_every_listed_key_resolves(self):
        """反向核对: list_slots 列出的每个键都必须能被 resolve_slots 命中。"""
        for key in knowledge_slots.list_slots():                            # 台账逐条
            dimension, _, value = key.partition("/")                         # 拆回维度/值
            hits = knowledge_slots.resolve_slots({dimension: value})         # 回查
            assert [slot.key for slot in hits] == [key], f"台账列了 {key} 但解析不中"   # 两处命名一致

    def test_listing_is_sorted_and_filterable(self):
        """排序稳定 (两次体检可直接 diff), 且可按维度限定。"""
        keys = knowledge_slots.list_slots()                                 # 全量台账
        assert keys == sorted(keys) and keys == knowledge_slots.list_slots()  # 稳定且可重复
        algo = knowledge_slots.list_slots("algo_mode")                      # 限定单维
        assert algo and all(key.startswith("algo_mode/") for key in algo)   # 不得混进别的维度


class TestCaptureHints:
    """沉底管道只给**当前可命中**的槽位建议 (A8-03)。

    实测缺口: ``static/fragments/`` 下没有 catalog/ 与 error_kind/ 目录, 而管道对
    6 个星表名与网络/校验和类错误一律返回 ``catalog/*`` / ``error_kind/*`` ——
    指向永远不存在的槽位。仓内也没有把候选升格成 fragment 的环节, 所以处置取
    (b) 停止产出无效建议, 判据挂在"当前能否命中"上, 片段一旦建好建议自动回来。
    """

    @pytest.mark.parametrize("message, data", [
        ("query failed for ps1: timeout", {}),
        ("gaia_dr3_18 submit 5xx", {}),
        ("network exhausted on stripe82", {}),
        ("checksum sha mismatch", {}),
        ("landolt rate limited", {}),
        ("ps1 返回异常", {"catalog": "ps1"}),        # data.catalog 显式声明也算命中线索
    ])
    def test_dangling_hints_are_not_emitted(self, message: str, data: dict[str, Any]):
        """指向不存在槽位的建议一律不发: 空串比误导性的建议好。"""
        capture = _load_capture()                                          # 装被测管道
        assert capture._guess_slot_hint({"message": message, "data": data}) == ""   # 猜不出也给空

    def test_unmatched_event_yields_no_hint(self):
        """猜不出就空着 (与旧行为一致)。"""
        capture = _load_capture()                                          # 装被测管道
        assert capture._guess_slot_hint({"message": "参数校验未通过"}) == ""          # 无星表名无线索

    def test_actionable_slot_is_accepted(self):
        """判据挂"当前能否命中"上: 已存在的槽位必须被认作可给建议。"""
        capture = _load_capture()                                          # 装被测管道
        assert capture._slot_hint_actionable("algo_mode/two_phase") is True  # 盘上有 → 可给
        assert capture._slot_hint_actionable("catalog/ps1") is False         # 盘上无 → 不给

    def test_hint_returns_once_the_fragment_exists(self, monkeypatch: pytest.MonkeyPatch):
        """片段一旦建好, 同一份代码立即把建议放回来 (判据跟盘面, 不跟注释走)。"""
        capture = _load_capture()                                          # 装被测管道
        # 管道是**调用时**才 from src.knowledge_slots 取 resolve_slots, 所以打在模块对象上即可生效
        monkeypatch.setattr(knowledge_slots, "resolve_slots", lambda ctx: ["伪命中"])   # 模拟片段已建
        try:
            assert capture._guess_slot_hint({"message": "ps1 query failed"}) == "catalog/ps1"
        finally:
            monkeypatch.undo()                                             # 必还原: 别把伪命中漏给别的用例

    def test_malformed_key_is_never_actionable(self):
        """形态不对的键直接否掉, 不去查盘。"""
        capture = _load_capture()                                          # 装被测管道
        assert capture._slot_hint_actionable("nokey") is False              # 没有分隔符
        assert capture._slot_hint_actionable("algo_mode/") is False         # 有维度没值


class TestFragmentRouting:
    """加载地图必须覆盖全部片段 (A8-05): README 标 on_demand 的, manifest 也要列。"""

    def test_manifest_on_demand_covers_every_fragment(self):
        """static/fragments/ 下每一份片段都必须在 manifest.on_demand 里被列出来。

        原先只列了一小部分 —— 模型按 README 的 on_demand 标注去取, 缺的取不到
        (含 E3 语义轴 D/E 要用的 target_type/* 三条)。
        """
        manifest = yaml.safe_load((SKILL_ROOT / "manifest.yaml").read_text(encoding="utf-8"))   # 加载地图
        declared = {path for paths in (manifest.get("on_demand") or {}).values() for path in paths}   # 摊平
        on_disk = {f"static/fragments/{path.relative_to(FRAGMENTS_DIR).as_posix()}"            # 盘上全量
                   for path in FRAGMENTS_DIR.rglob("*") if path.is_file()}
        missing = on_disk - declared                                                        # 没进地图的
        assert not missing, f"片段在盘上却没进加载地图: {sorted(missing)}"                   # 一份都不许漏
        assert len(declared & on_disk) == len(on_disk)                                      # 反向也要核

    def test_manifest_on_demand_paths_exist(self):
        """清单里的路径必须真实存在 (加载期必炸的引用不算路由)。"""
        manifest = yaml.safe_load((SKILL_ROOT / "manifest.yaml").read_text(encoding="utf-8"))   # 加载地图
        for scenario, paths in (manifest.get("on_demand") or {}).items():                     # 逐场景
            for path in paths:                                                                # 逐路径
                assert (SKILL_ROOT / path).exists(), f"{scenario} 指向不存在的路径: {path}"     # 必须落盘

    def test_declared_dimensions_match_disk_layout(self):
        """SLOT_DIMENSIONS 是白名单: 维度要么有目录, 要么明确登记为「无升格环节」。"""
        for dimension in knowledge_slots.SLOT_DIMENSIONS:                       # 逐维度核盘面
            assert (FRAGMENTS_DIR / dimension).is_dir() or dimension in ("catalog", "error_kind"), \
                f"维度 {dimension} 既无目录也未登记为「按需新建」"                  # 不许含糊


class TestReadFailureIsNotSilentMiss:
    """YZ-53: 读失败 (权限/解码) 与「无槽位」必须在日志层可区分 — 不许静默归 None。"""

    def test_unreadable_slot_logs_warning(self, monkeypatch: pytest.MonkeyPatch, caplog):
        """文件存在但读不出来时, 返回值仍是 None (契约不破), 但必须留 WARN 痕迹。"""
        slot_file = FRAGMENTS_DIR / "algo_mode" / "best_two_phase.yaml"          # 借真实片段当靶子
        if not slot_file.is_file():                                              # 片段缺失时本用例无意义
            pytest.skip("algo_mode/best_two_phase.yaml 不在盘上")
        real_read = Path.read_text                                             # 留真身: 只拦目标文件

        def _deny(self: Path, *args: Any, **kwargs: Any) -> str:
            """``Path.read_text`` 的权限桩: 只对目标片段抛 PermissionError。

            只拦 ``best_two_phase.yaml`` 这一个文件名, 其余读取全部走真身 ——
            全局拦截会把框架与 pytest 自己的读取一起炸掉, 用例就不是在验被测
            件而是在验环境。
            """
            if self.name == "best_two_phase.yaml":                             # 只拦这一个: 别的读取照常
                raise PermissionError("simulated ACL deny")                    # 模拟 ACL 拒绝
            return real_read(self, *args, **kwargs)                            # 其余路径走真读

        monkeypatch.setattr(Path, "read_text", _deny)                          # 打权限桩
        try:
            with caplog.at_level("WARNING", logger="src.knowledge_slots"):     # 只收本模块的告警
                result = knowledge_slots._read_slot("algo_mode", "best_two_phase")
        finally:
            monkeypatch.undo()                                                 # 必还原: 权限桩不外漏
        assert result is None                                                  # 契约: 读失败按未命中, 不抛
        assert any("unreadable" in rec.message for rec in caplog.records)      # 但必须有 WARN 留痕


class TestLoadReferenceTraversal:
    """YZ-17: kb.load_reference 只读 references/ 下文档, 不做仓内任意文件读取器。"""

    def test_parent_traversal_rejected(self):
        """``../../README`` 型输入曾实测读出仓根 README 全文 — 现在必须 fail-closed。"""
        from src import kb  # 被测件
        with pytest.raises(ValueError):                                        # 穿行输入即拒
            kb.load_reference("../../README")

    def test_separator_and_empty_rejected(self):
        """路径分隔符与空串同样到不了文件系统层。"""
        from src import kb  # 被测件
        for bad in ("a/b", "a\\b", ""):                                        # 三种非法形态
            with pytest.raises(ValueError):
                kb.load_reference(bad)

    def test_bare_stem_still_works(self):
        """正常 stem 不受影响: 任取 references/ 下一篇真实文档能读回。"""
        from src import kb  # 被测件
        stems = kb.list_references()                                           # 先列真实清单
        if not stems:                                                          # 无文档时本用例无意义
            pytest.skip("references/ 为空")
        text = kb.load_reference(stems[0])                                     # 读第一篇
        assert isinstance(text, str) and text                                  # 必须读回非空文本
