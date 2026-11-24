"""回归: DOMAIN_BOOST 领域加权通道必须对现有知识库真实生效 (budget §6.1 C1)。

缺陷形态 (修复前实测确认):
  * ``load()`` 把 ``inner.name`` (带 ``.yaml`` 扩展名) 写进 ``entry.source``;
  * ``DOMAIN_BOOST`` 的键是无扩展名领域词 (``best``/``nadc``/``tap``/...),
    且 5 个知识文件词干 (best_practices / citations / domain_rules /
    known_issues / lessons_learned) 与旧键表无一匹配;
  * 于是 ``_bm25`` 里的 ``entry.source in DOMAIN_BOOST`` 对当前知识库恒为
    False — 领域加权是永不触发死代码。

本组测试钉两侧: 结构上键表与装载条目的 source 必须同口径 (接线正确), 行为上
加权必须真实改变 _bm25 分数与最终检索排序 (不是"代码路径走到了"而是"结果
变了")。修复前结构断言与行为断言全部失败 (RED), 修复后全绿 (GREEN)。
"""
from __future__ import annotations

# 标准库: importlib 按文件路径装载 rag/ 执行器 (rag/ 不是包, 无 __init__.py,
# 与 ops/astro_best_cli.py 的降级装载路径同口径) + skill 根锚定
import importlib.util
import sys
from pathlib import Path

# 第三方: pytest (approx 浮点比较 + monkeypatch 注入空加权表)
import pytest

# 路径锚点: 本文件位于 test/unit/meta/, 上溯 3 层即 skill 根
SKILL_ROOT = Path(__file__).resolve().parents[3]  # parents[3] 是硬编码层级: 文件挪一层就静默指向错目录
RAG_PATH = SKILL_ROOT / "rag" / "astro_rag.py"    # rag/ 不是包: 只能按路径装载, 走 import 会直接 ImportError
KNOWLEDGE_DIR = SKILL_ROOT / "rag" / "knowledge"  # 词干集合要与之逐字一致: 键表对不上文件名, 加权就是死代码

# 旧导入守门: PyYAML 缺失或 rag/ 执行器不可装载时整模块 skip 而非 collection
# error (依赖缺失是环境事实, 不是回归)
try:
    # 本地: 被测执行器 — 以唯一模块名按路径装载, 杜绝多 skill 同进程互踩
    _spec = importlib.util.spec_from_file_location("astro_rag_best_under_test", RAG_PATH)     # 按文件路径装载: 知识库不在包内, 只能走文件级导入
    if _spec is None or _spec.loader is None:  # pragma: no cover - 文件必然存在
        raise ImportError(f"cannot load {RAG_PATH}")
    astro_rag = importlib.util.module_from_spec(_spec)                                            # 先建模块对象: 装载器要的是一个还没执行的壳
    # 先注册再执行: 模块内的 @dataclass 装饰器要经 sys.modules 反查自身
    # 模块命名空间 (dataclasses._is_type), 漏注册会在装载期 AttributeError
    sys.modules[_spec.name] = astro_rag                                                # 先注册进模块表: 模块内自引用与 dataclass 都要它先在册
    _spec.loader.exec_module(astro_rag)                                                             # 真正执行模块体: 类与常量此时才存在
except Exception as _legacy_err:  # legacy-import-guard
    # 延迟导入: pytest 只在 legacy 模块装载失败时用于模块级 skip
    import pytest as _pytest
    _pytest.skip(f'legacy import unavailable: {_legacy_err!r}', allow_module_level=True)            # 模块级跳过: 导入树问题不该算用例失败


def _loaded_rag():
    """装载真实知识库的执行器 (每次调用独立实例, 防测试间状态串味)。

    非空断言放在这里: 各条用例都以下载到条目为前提, 知识库为空时它们会
    一并变成恒真的空集断言, 而表面上仍然是"全绿"。
    """
    rag = astro_rag.AstroRAG(KNOWLEDGE_DIR)  # 每次新建实例: 装载器带可变状态, 复用会让用例之间串味
    loaded = rag.load()                      # 真读盘才谈得上一致性: 键表与 source 是否同口径只能在这里验
    assert loaded > 0, "知识库必须非空 (5 个 YAML 至少产出 1 条)"                                          # 非空断言: 知识库为空时下面各条会变成恒真的空集断言
    return rag


class TestDomainBoostKeyTable:
    """结构守门: DOMAIN_BOOST 键表必须与知识库文件词干同口径 (C1 接线面)。"""

    def test_keys_are_exactly_the_knowledge_file_stems(self):
        """键表必须恰好覆盖全部知识文件词干, 不多也不少。

        旧键表是 14 个领域术语 (``tap``/``adql``/``sqlid``/...), 与 5 个真实
        文件词干零交集 — 领域加权因此永不触发。键集即加权偏好, 新增知识文件
        不同步登记词干时本测试红灯。
        """
        stems = {path.stem for path in KNOWLEDGE_DIR.glob("*.y*ml")}                                # 取全部知识文件词干: 键表必须与它同口径
        assert stems, "rag/knowledge/ 下必须有 YAML 知识文件"  # 空目录先断: 否则下面那条等值断言会双空假通过
        assert set(astro_rag.DOMAIN_BOOST) == stems    # 等值而非包含: 键表多一个死键同样要红, 多余键永远不触发加权

    def test_every_loaded_entry_source_is_a_boost_key(self):
        """装载后每个条目的 source 必须命中加权表 (load 侧接线正确)。

        load() 侧传的必须是词干, 键表也是无扩展名词干 —— 两侧口径一旦脱节,
        命中的条目就永远拿不到加权; source 必须落在键表内。
        """
        rag = _loaded_rag()                                                                         # 装载一次真实知识库
        sources = {entry.source for entry in rag.entries}  # 取装载后的实际 source: 键表对但 load 写错后缀时只有这步能发现
        assert sources <= set(astro_rag.DOMAIN_BOOST), (                                         # 子集而非等值: 多出的死键由上面那条等值断言管
            f"有条目的 source 不在加权表里: {sorted(sources - set(astro_rag.DOMAIN_BOOST))}"                  # 报出脱节的那几条: 整改的人要看得见是谁
        )

    def test_source_has_no_yaml_extension(self):
        """source 不得带 .yaml 扩展名 (键表是无扩展名词干形态的硬约束)。

        两侧口径必须逐字相同: 词干与"词干.yaml"在集合判据里是两个不同
        的键, 差一个后缀就意味着这条知识的加权静默失效, 而分数看上去
        仍然正常。
        """
        rag = _loaded_rag()                                                                         # 装载一次真实知识库
        assert all(not entry.source.endswith((".yaml", ".yml")) for entry in rag.entries)  # 逐条判后缀: 差一个词干就是两个键, 加权静默失效


class TestDomainBoostChangesScores:
    """行为守门: 领域加权必须真实改变分数 (修复前清空键表分数恒等, 故 RED)。"""

    # 查询同时命中英文术语与中文词, 保证 BM25 稀疏通道对多个知识文件有条目
    # 进榜 (加权是加性常数, 只有进榜条目的分数才会被改变)
    QUERY = "checksum 下载"                                                             # 同时命中英文术语与中文词: 加权是加性常数, 只有进榜条目分数才会变

    def test_bm25_scores_change_when_boost_table_is_emptied(self, monkeypatch):
        """清空加权表后 _bm25 分数必须不同 — 证明加权通道真的在打分。

        修复前 source (带 .yaml) 与键表零交集, 加权恒不触发, 两侧分数恒等,
        本断言失败; 修复后每个装载条目都按其文件词干加权, 分数必然不同。
        """
        rag = _loaded_rag()                                                                         # 装载一次真实知识库
        tokens = astro_rag._tokenize(self.QUERY)                                              # 用被测自己的分词器: 换一套分词就测不到它的加权通道
        with_boost = rag._bm25(tokens)                                                              # 带加权的分数
        assert with_boost, "查询必须至少命中一个条目 (否则本测试空转)"                                                 # 非空断言: 零命中时本测试会空转
        monkeypatch.setattr(astro_rag, "DOMAIN_BOOST", {})  # 置空而非改值: 这里要证的是通道存在性, 与具体权重取值无关
        without_boost = rag._bm25(tokens)                                                         # 清空键表后的分数: 两侧之差才是加权的净效果
        assert with_boost != without_boost  # 挡住加权退化成死代码: 两侧 source 脱节时这份分数必然恒等

    def test_boost_delta_equals_the_registered_weight(self, monkeypatch):
        """逐条核对: 加权增量必须恰好等于该条目 source 登记的权重。

        不只是"分数变了", 而是"按表内权重精确地变" — 防止加权来源漂移成
        别的魔法数。
        """
        rag = _loaded_rag()                                                                         # 装载一次真实知识库
        table = dict(astro_rag.DOMAIN_BOOST)                                                        # 复制一份权重表: 下面要按它算期望增量
        # 至少一个装载条目必须真的登记了权重 — 否则"增量恒为 0"会让本测试
        # 在脱节状态下空转通过 (旧键表与 source 零交集时正是如此)
        assert any(table.get(entry.source) for entry in rag.entries)                     # 至少一条真的登记了权重: 否则"增量恒为 0"会让本条空转通过
        tokens = astro_rag._tokenize(self.QUERY)                                                    # 同一套分词: 两侧只该差在加权这一项
        with_boost = rag._bm25(tokens)                                                              # 带加权的分数
        monkeypatch.setattr(astro_rag, "DOMAIN_BOOST", {})                                  # 置空而非改值: 这里要证的是通道存在性, 与权重取值无关
        without_boost = rag._bm25(tokens)                                                           # 清空后的分数
        for idx, entry in enumerate(rag.entries):                                                   # 逐条目核对增量
            expected = without_boost.get(idx, 0.0) + table.get(entry.source, 0.0)  # 未进榜项按 0 兜底: 没命中的条目不该凭空长出权重增量
            assert with_boost.get(idx, 0.0) == pytest.approx(expected), entry.source

    def test_search_ranking_changes_with_boost(self, monkeypatch):
        """最终检索排序必须随加权改变 (RRF 融合的输入端被真实影响)。

        加权只进 BM25 一路; 若它足以改变该路排名, RRF 终序就会变。修复前
        终序与清空键表后完全一致 (加权是死代码), 本断言失败。

        取回全量并按**条目全文**比对 (而非只看 source 文件名 + top10): 文件名
        粒度太粗 —— 同一文件里多条条目重排时 source 序列可以完全不动, 判据
        就会随语料增删而假红/假绿; 条目全文才是 RRF 终序的最小可辨单位。
        """
        rag = _loaded_rag()                                                                         # 装载一次真实知识库
        with_boost = rag.search(self.QUERY, top_k=len(rag.entries))                                 # 带加权的最终排序 (全量)
        monkeypatch.setattr(astro_rag, "DOMAIN_BOOST", {})                                 # 置空键表: 终序若不变, 就说明加权没进 RRF 的输入端
        without_boost = rag.search(self.QUERY, top_k=len(rag.entries))                                  # 清空后的最终排序 (同样全量)
        assert [hit["content"] for hit in with_boost] != [hit["content"] for hit in without_boost]  # 终序必须不同: 加权退化成死代码时这两列会完全一致
