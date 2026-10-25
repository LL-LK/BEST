# -*- coding: utf-8 -*-
"""evals.equivalence.tests — 跨实验等价性单测 (transport 字节级 + 字典单点)。

职责: 守住仓库里最容易悄悄漂移的两条跨实验不变量 ——
一是 E2/E4/E6 三个实验各自持有一份 transport 副本, 它们对同一份离线快照
必须给出逐字节相同的回包; 二是哨兵阈值只允许存在一份真值, 实验代码不得
硬编码。

所属实验: 横向守护 E2 金标准一致性 (docs/eval-E2-groundtruth.md 的等价性
约定)、E4 鲁棒与安全、E6 可复现与效率三个实验, 自身不对应实验编号 ——
它是铁律 6 "零跨实验 import" 的机械落地件, 而不是第七个实验。

对外接口: ``TestTransportEquivalence`` 三条断言比对三份回放的数据页、
getcount 计数包与 POST 回包; ``TestSentinelDictionary.test_no_hardcoded_sentinels``
扫全树哨兵硬编码; ``TestImportIsolation`` 既扫真实树零违规, 再用现造的违规
树证明守卫不是空转。

依赖与数据流: 输入是 ``evals/equivalence/snapshots/equiv_ps1/`` 的快照与
``fixtures/ps1_equiv.csv`` 夹具; 产物只有 pytest 结论, 不落盘报告。

关键契约与不变量: 三个 transport 全部离线回放, 不发真实请求, rate_limit
归零, 因此比对结果与网络无关; 本文件是唯一被允许跨实验 import 的守门件
(选手不能互相 import, 裁判必须), 其"是否被误报/漏报"由同文件里的反证
夹具自证; 哨兵单点性由 ``evals/_data/`` 纯数据字典保证, 等价性本身由本文件断言。

陷阱与边界: 比对的是回包语义而非序列化原文 — getcount 只比 ``total``,
因为三方 JSON 键序与空格允许不同, 比字节会得到假红; 反过来数据页必须逐字节
相同, 因为它是最终落盘、要被人逐行看的产物, 格式漂移就是真 bug。
"""
from __future__ import annotations

# 标准库: CSV 读夹具 (真实回包形态的行从这里来, 不只靠现造的对抗行)
import csv

# 本地: 哨兵字典单点 (下面几条断言的期望值全从它取, 不写死字面量)
from evals._data import load_null_sentinel
from evals.ablation.harness.adapters import make_adapter  # 跨实验 import 仅此处合法: 裁判件可读选手件 (铁律 6)
from evals.ablation.harness.support import SENTINEL_EXEMPT  # 同上: E5 的豁免列是"从字典读"还是"抄一份", 看它等于什么
from evals.equivalence import EQUIV_DIR
from evals.equivalence.criteria import (
    scan_row_key_divergence,
    scan_sentinel_divergence,
)
from evals.equivalence.import_isolation import scan_cross_experiment_imports
from evals.equivalence.sentinel import (
    scan_hardcoded_exempt_columns,
    scan_hardcoded_sentinels,
    scan_local_sentinel_readers,
)

# 生产侧的哨兵豁免列 (src/models 持有一份字面量 — 生产不得反向依赖评测层,
# 故那份不消重, 改由下面的相等断言钉住; 钉不住才是重复真源的真正危害)
from src.models import _SENTINEL_EXEMPT_COLUMNS  # 私有名: 断言的就是"这份字面量"本身, 故必须按私有名取

FIXTURE_CSV = EQUIV_DIR / "fixtures" / "ps1_equiv.csv"  # 真实 ps1 回包形态的行 (含整列为空的 ps1_source_id)


def _fixture_rows():
    """夹具里的真实回包行 —— 对抗行只证"造得出来的形态", 这里证"站点真发过的那种"。"""
    # utf-8-sig: 夹具可能带 BOM, 按 utf-8 读会在第一列留下不可见字符
    with FIXTURE_CSV.open(encoding="utf-8-sig", newline="") as handle:
        return [(f"夹具第{index}行", row)
                for index, row in enumerate(csv.DictReader(handle))]


class TestJudgmentEquivalence:
    """判定口径等价: 同一份输入, 各份实现必须给出同一个答案。

    背景: 本类继承的是原 ``TestTransportEquivalence`` 守的那条不变量 —— "同源功能多份
    实现, 改一侧不改另一侧就会得到两套互斥答案"。变的是比对对象: 回放层 2026-10-07
    整体退役 (evals/groundtruth/transport.py 已删除, ``snapshots/`` 一并清空), 传输
    实现不再可比, 判定实现还在, 于是改比**判定口径** —— 这正是
    docs/REPLAY-RETIREMENT-CRITERIA.md §3.2 末行开下的处方。
    """

    def test_row_key_criterion_agrees_with_independent_oracle(self):
        """行主键: E2 归一层与独立 oracle 在对抗行集上逐条同键。"""
        problems = scan_row_key_divergence()  # 默认两侧 = canonical / gold oracle
        assert not problems, f"行主键口径漂移 (归一层与 oracle 必须同格式契约): {problems}"

    def test_row_key_criterion_agrees_on_real_payload_shape(self):
        """行主键: 真实回包形态 (夹具) 上同样零分歧。

        对抗行是现造的, 造得出来不等于站点真发过。夹具里的行 ``ps1_source_id``
        **整列为空**, 走的是"id 不可用退坐标键"那条路 —— 恰是抄漏 id 回退时
        最容易分叉的一支, 只拿有 id 的造行测不到。
        """
        problems = scan_row_key_divergence(_fixture_rows())  # 换成夹具行, 两侧实现不动
        assert _fixture_rows(), "夹具读不出行 = 这条断言在空集上假通过"
        assert not problems, f"真实回包形态上行主键口径漂移: {problems}"

    def test_row_key_criterion_agrees_on_coords_only_path(self):
        """行主键: ``coords_only`` 分支 (id 重复退坐标) 两侧同样同键。"""
        problems = scan_row_key_divergence(coords_only=True)  # 走结果集内 id 重复那条支路
        assert not problems, f"coords_only 分支上行主键口径漂移: {problems}"

    def test_sentinel_criterion_agrees_across_three_copies(self):
        """哨兵判定: E2 归一层 / E2 oracle / E5 harness 三方同判。"""
        problems = scan_sentinel_divergence()  # 阈值两侧 × 普通列与三个豁免列
        assert not problems, f"哨兵判定口径漂移 (三方必须同判): {problems}"

    def test_guard_detects_a_planted_row_key_divergence(self, tmp_path):
        """反证夹具: 换掉一侧实现必须报出分歧, 否则上面几条是空转绿。

        两侧实现是"格式契约而非共享代码", 唯一的证据力来自"变异会被抓到"。
        这里把左侧换成恒返常量的替身 —— 它对任何行都答不上真实主键。
        """
        planted = scan_row_key_divergence(left=lambda row: "PLANTED")  # 左侧恒错
        assert planted, "守卫对明显分歧放行 = 判定口径守卫空转"
        assert any("裸 source_id" in p and "PLANTED" in p for p in planted), planted  # 要报到形态名与两侧值

        # 反向: 两侧同一份替身时必须零分歧 —— 见谁都报的守卫同样没有证据力
        same = scan_row_key_divergence(left=lambda row: "X", right=lambda row: "X")
        assert not same, "守卫把两侧一致误报成分歧 (判据写反或恒真)"

    def test_guard_detects_a_planted_sentinel_divergence(self, tmp_path):
        """反证夹具: 哨兵侧恒返 False 的替身必须被抓到, 且要报到列名与值。"""
        planted = scan_sentinel_divergence(left=lambda column, value: False)  # 左侧恒判"非哨兵"
        assert planted, "哨兵守卫对明显分歧放行 = 守卫空转"
        assert any("ps1_rpsf" in p for p in planted), planted  # 定位到具体列
        # 恒返 True 的替身同样要被抓: 反向恒真的守卫会把所有真值洗成哨兵
        inverted = scan_sentinel_divergence(mid=lambda column, value: True)
        assert inverted, "哨兵守卫对恒真替身放行 = 判据只验一侧"

        # 三方**全部**换成同一个替身时才该零分歧: 只换两侧会留下一份真实现,
        # 于是报出的"分歧"是真的, 断言就成了一句自欺的话
        same = lambda column, value: value == ""  # noqa: E731 — 三个参数位同名替身, lambda 最短
        clean = scan_sentinel_divergence(left=same, mid=same, right=same)
        assert not clean, f"守卫把三方一致误报成分歧: {clean}"


class TestSentinelDictionary:
    """哨兵字典单点: 实验代码不得硬编码哨兵阈值。"""

    def test_no_hardcoded_sentinels(self):
        """evals/ 下实验代码必须零硬编码哨兵比较 (字典单点, 防漂移)。"""
        problems = scan_hardcoded_sentinels()  # 扫全树: 阈值只允许存在 evals/_data 一份
        assert not problems, f"硬编码哨兵 (应读 evals/_data 单点): {problems}"

    def test_guard_detects_a_planted_negative_sentinel(self, tmp_path):
        """反证夹具: 造的负哨兵比较必须被抓到, 否则上面那条是空转绿。

        判据必须同时认 ``isinstance(operand, ast.Constant)`` 与
        ``UnaryOp(USub, Constant(...))``: Python 把 ``-999.0`` 解析成
        ``UnaryOp(USub, Constant(999.0))``, 只认前者时这个 fail-closed 守卫对
        **任何**负哨兵恒不命中, ``scan_hardcoded_sentinels()`` 永远返回空
        清单。真实树零违规的情况下, 上面那条 ``test_no_hardcoded_sentinels``
        在守卫彻底失效时同样通过, 完全没有证据力。违规样本只能现造。
        """
        bad_dir = tmp_path / "nl2tool"
        bad_dir.mkdir()
        (bad_dir / "probe.py").write_text(
            "def f(v):\n"
            "    return float(v) <= -999.0\n",   # 守卫声称要抓的形态: 负哨兵数值比较
            encoding="utf-8",
        )
        found = scan_hardcoded_sentinels(tmp_path)
        assert found, "守卫对明显违规放行 = 守卫空转 (负哨兵在 AST 里是 UnaryOp, 不是 Constant)"

        # 反向: 非哨兵的负数、字符串形态、变量引用都不得误报 ——
        # 见谁都报的守卫同样没有证据力, 只会逼人把判据改宽。
        ok_dir = tmp_path / "repro"
        ok_dir.mkdir()
        (ok_dir / "clean.py").write_text(
            "def f(v, threshold):\n"
            "    return float(v) <= -1.0\n"      # 负数但不是哨兵
            "def g(text):\n"
            "    return '-999' in text\n"        # 字符串形态: 断言文本里的引用合法
            "def h(v, SENTINEL):\n"
            "    return float(v) <= SENTINEL\n",  # 走共享字典的变量名
            encoding="utf-8",
        )
        assert not scan_hardcoded_sentinels(ok_dir), "守卫误报了合法写法 (负数/字符串/变量)"


class TestSentinelSingleSource:
    """哨兵真源只许一份: 豁免列不得硬编码、读法不得自建、生产那份必须相等。

    这三条守的是 2026-10-05 R3 收敛前的三种重复真源形态: 字符串集合豁免列
    (数值守卫看不见)、自建 yaml 读法 (绕开三键校验与缓存)、生产字面量与字典
    脱钩 (改了任一侧无人报错)。
    """

    def test_no_hardcoded_exempt_columns(self):
        """实验代码零硬编码豁免列 (``frozenset({"pmra", ...})`` 这类字符串集合)。"""
        problems = scan_hardcoded_exempt_columns()  # 扫全树: 豁免列与阈值同属哨兵单点
        assert not problems, f"硬编码哨兵豁免列 (应读 evals/_data 单点): {problems}"

    def test_no_local_sentinel_readers(self):
        """实验代码零自建哨兵读法 (哨兵字典的文件名不得进可执行语句)。"""
        problems = scan_local_sentinel_readers()  # 扫全树: 自建读法拿不到三键校验与 lru_cache
        assert not problems, f"实验自带哨兵读法 (应走 evals._data.load_null_sentinel): {problems}"

    def test_guard_detects_a_planted_exempt_set(self, tmp_path):
        """反证夹具: 造的硬编码豁免列必须被抓到, 否则上面那条是空转绿。

        这正是收敛前 E5 的形态 (``SENTINEL_EXEMPT = frozenset({...})``): 里面
        没有任何哨兵数值, ``scan_hardcoded_sentinels`` 对它恒不命中 —— 只测
        数值那条的守卫会对此完全沉默。
        """
        bad_dir = tmp_path / "ablation"
        bad_dir.mkdir()
        (bad_dir / "probe.py").write_text(
            "SENTINEL_EXEMPT = frozenset({'pmra', 'pmdec'})\n"  # 抄一半也是抄: 漏抄的列会被当哨兵清掉
            "def keep(column):\n"
            "    return column in SENTINEL_EXEMPT\n",
            encoding="utf-8",
        )
        found = scan_hardcoded_exempt_columns(tmp_path)
        assert found, "守卫对硬编码豁免列放行 = 只扫数值的守卫恒不命中字符串集合"
        assert any("pmra" in p for p in found), found  # 命中列名要报到: 整改者才知道抄漏了哪几列

        # 反向: 非豁免列的字符串集合、与字典同源的读法都不得误报
        ok_dir = tmp_path / "repro"
        ok_dir.mkdir()
        (ok_dir / "clean.py").write_text(
            "TOOLS = frozenset({'cone_search', 'fetch_page'})\n"  # 普通集合: 不是豁免列
            "from evals._data import load_null_sentinel\n"        # 合法读法: 走共享字典
            "SENTINEL_EXEMPT = frozenset(load_null_sentinel()['exempt_columns'])\n",
            encoding="utf-8",
        )
        assert not scan_hardcoded_exempt_columns(ok_dir), "守卫误报了合法写法 (普通集合/读字典)"

    def test_guard_detects_a_planted_local_reader(self, tmp_path):
        """反证夹具: 造的本地哨兵读法必须被抓到, 且 docstring 提及不得误报。

        两者必须同时钉死: 判据若宽到把说明文字也算违规, 整改者就只能把守卫改
        窄, 窄回"只认这一种写法"就等于放掉下一种。
        """
        bad_dir = tmp_path / "ablation"
        bad_dir.mkdir()
        (bad_dir / "probe.py").write_text(
            '"""本模块读 evals/_data/null_sentinel.yaml (契约说明, 合法)。"""\n'  # docstring 提及: 合法
            "SENTINEL_PATH = EVALS_DIR / '_data' / 'null_sentinel.yaml'\n"        # 文件名进代码: 违规
            "def threshold():\n"
            "    return float(SENTINEL_PATH.read_text())\n",
            encoding="utf-8",
        )
        found = scan_local_sentinel_readers(tmp_path)
        assert found, "守卫对本地哨兵读法放行 = 三键校验与批内缓存可被静默绕开"
        assert any("probe.py" in p for p in found), found  # 定位到具体文件

        ok_dir = tmp_path / "groundtruth"
        ok_dir.mkdir()
        (ok_dir / "doc_only.py").write_text(
            '"""权威来源: evals/_data/null_sentinel.yaml (白盒锚点说明)。"""\n'  # 只有 docstring 提到
            "def rows():\n"
            "    return []\n",
            encoding="utf-8",
        )
        assert not scan_local_sentinel_readers(ok_dir), "守卫误报了 docstring 里的路径说明"

    def test_e5_reads_sentinel_from_the_dictionary(self):
        """E5 的哨兵口径必须**等于**字典现值 (数值级证据, 不只看它有没有 import)。

        静态扫描只证明"没有本地读法", 证明不了"读出来的值就是字典的值" ——
        判据写成 ``float(load_null_sentinel()["threshold"] - 1)`` 之类照样过扫描。
        这里取 E5 的两个真实出口 (豁免列常量 + 适配器建出来的阈值) 与字典对账。
        """
        sentinel = load_null_sentinel()  # 期望值从单点取, 本文件不写死任何哨兵数值
        assert frozenset(sentinel["exempt_columns"]) == SENTINEL_EXEMPT, "E5 豁免列与字典不等"
        adapter = make_adapter({})       # 空装配即走脚本面: 只要它建得起来就说明阈值读到了
        assert adapter._threshold == float(sentinel["threshold"]), "E5 阈值与字典不等"

    def test_production_exempt_columns_match_dictionary(self):
        """生产 ``src/models`` 的豁免列字面量必须与字典**相等** (钉住那份不消重的副本)。

        生产侧按 ``evals/_data/null_sentinel.yaml`` 的自述不得反向依赖评测层, 所以
        ``_SENTINEL_EXEMPT_COLUMNS`` 这份字面量保留 (它是字典自认的权威来源)。
        代价是两份可以各改各的 —— 这条断言就是那份代价的对价: 改一侧不改另一侧
        立即红, 漂移不再是"报告里看不出来"的静默故障。
        """
        sentinel = load_null_sentinel()  # 字典是评测侧唯一真值
        assert set(_SENTINEL_EXEMPT_COLUMNS) == set(sentinel["exempt_columns"]), (  # 两侧必须逐列相等
            "生产与评测的哨兵豁免列已漂移 (改一侧必须同步另一侧, 见 null_sentinel.yaml 头)"
        )


class TestImportIsolation:
    """铁律 6: 六个实验各自自包含, 不得互相 import。"""

    def test_no_cross_experiment_imports(self):
        """零跨实验 import (只允许 evals/_data 纯数据字典与 evals/equivalence)。

        这条铁律只靠人工约定是守不住的: verify_import_graph
        唯一的分层判据是"不得 import ops 层", 对 evals.* 只验能否导入,
        ``evals.semantics`` → ``evals.ablation`` 完全放行。跨实验 import 一旦
        发生, 同一段逻辑会在两处独立演化并悄悄漂移。
        """
        problems = scan_cross_experiment_imports()  # 扫真实 evals/ 树: 守现状而非只守样本
        assert not problems, f"跨实验 import 违反铁律 6 (实验须自包含): {problems}"

    def test_guard_detects_a_planted_violation(self, tmp_path):
        """守卫自证 (反证夹具): 造的跨实验 import 必须被抓到, 否则守卫是空转。

        沿用本仓 Phase 5 纪律: 守卫若对明显违规都报通过, 它对真实树的"全绿"
        没有任何证据力。真实树当前零违规, 所以违规样本只能现造。
        """
        # 造一棵最小的 evals 树: nl2tool 越界 import ablation
        bad_root = tmp_path / "bad_tree"
        bad_dir = bad_root / "nl2tool"       # 归属实验 = nl2tool
        bad_dir.mkdir(parents=True)                                                                 # 造一个跨实验 import 的坏例子
        (bad_dir / "bad.py").write_text(
            "from evals.ablation.metrics.composite import _TABLE_PREFIXES\n",  # 目标属另一实验
            encoding="utf-8",
        )
        found = scan_cross_experiment_imports(bad_root)  # 守卫必须对明显违规报红
        assert found, "守卫对明显违规放行 = 守卫空转"
        assert any("nl2tool" in p and "ablation" in p for p in found), found  # 归属与目标都要报到

        # 反向: 独立一棵树, 允许的两类目标不得被误报 (evals/_data 与
        # evals/equivalence), 实验内相对/裸引用也不报
        ok_root = tmp_path / "ok_tree"
        ok_dir = ok_root / "repro"
        ok_dir.mkdir(parents=True)                                                                  # 造一个干净例子
        (ok_dir / "ok.py").write_text(
            "from evals._data.tolerances import TOL\n"            # 白名单: 纯数据字典
            "from evals.equivalence import EQUIV_DIR\n"           # 白名单: 守门设施自身
            "from evals.repro.normalize import norm_angle_deg\n"  # 实验内跨模块: 合法
            "from .normalize import norm_angle_deg as same_exp\n",  # 相对导入: 实验内
            encoding="utf-8",
        )
        assert not scan_cross_experiment_imports(ok_root), (                                      # 干净例子必须零问题: 否则守卫是"见谁都报"
            "守卫误报了合法的 _data / equivalence / 实验内引用"
        )


class TestRelativeImportNotBlindSpot:                                                       # 相对导入曾是铁律 6 的完整后门, 不是"边角情况"
    """反证夹具: **相对**形式的跨实验 import 必须被抓到 (A6-01 突变实验修复)。

    原守卫对 ``ast.ImportFrom`` 一见 ``node.level`` 非零就 ``continue`` ——
    等于无条件放行全部相对导入。实测往 ``evals/nl2tool/`` 注入
    ``from ..repro import stats`` 后, 该 import 在运行期**真的可用**
    (``import OK -> evals.repro.stats``), 而本守卫、verify_import_graph、
    equivalence 全部断言与 E1 的 26 条测试**全绿**。绕过铁律 6 的成本低到
    一行代码, 却没有任何一道闸会响。

    判据因此从"level 大小"改成"**解析出的目标包归属**": 相对导入先还原成
    绝对点分包名 (落在 ``evals.`` 命名空间下), 再与绝对导入走同一套判定。
    下面四条把"该抓的抓得到"与"不该抓的抓不到"钉死。
    """

    def test_parent_relative_import_to_other_experiment_is_blocked(self, tmp_path):
        """``from ..repro import stats`` 必须被抓 —— 这正是原守卫放行的那一行。"""
        bad_dir = tmp_path / "nl2tool"                                    # 归属实验 = nl2tool
        bad_dir.mkdir()
        (bad_dir / "evil.py").write_text(
            "from ..repro import stats\n",                                # level=2 退到 evals/, 目标落在另一实验
            encoding="utf-8",
        )
        found = scan_cross_experiment_imports(tmp_path)
        assert found, "守卫对 `from ..repro import stats` 放行 = 铁律 6 的相对导入后门未修"
        assert any("nl2tool" in p and "repro" in p for p in found), found  # 归属与目标都要报到

    def test_relative_import_within_same_experiment_is_allowed(self, tmp_path):
        """实验内的相对导入 (``.helpers`` / ``from . import x`` / ``..sibling``) 不得误报。

        反向断言与正向同等重要: 守卫一旦见相对导入就报, 整改者就会把它改宽,
        改宽的方向通常是"全都放行" —— 那就回到了原状。
        """
        exp = tmp_path / "nl2tool"
        (exp / "sub").mkdir(parents=True)                                 # 造一个子包, 覆盖 level=2 的合法形态
        (exp / "ok.py").write_text(
            "from .helpers import h\n"                                    # level=1 停在当前包: 实验内
            "from . import helpers\n",                                    # level=1 且 module 为空: 同样实验内
            encoding="utf-8",
        )
        (exp / "sub" / "m.py").write_text(
            "from ..helpers import h\n",                                  # level=2 从子包退回实验根: 仍是 nl2tool
            encoding="utf-8",
        )
        assert not scan_cross_experiment_imports(tmp_path), (           # 合法相对导入必须零问题
            "守卫误报了实验内相对导入: 判据过宽会逼人把口子改回'全都放行'"
        )

    def test_relative_import_escaping_above_evals_root_is_out_of_scope(self, tmp_path):
        """退到 evals/ 根之上 (level 过大) 不由本守卫判, 也不得崩。

        那类形态在真实代码里本身就是错的, 但归"跨实验"报会让诊断指错方向;
        本守卫显式返回射程外, 而不是抛异常或误报到别的实验名下。
        """
        exp = tmp_path / "nl2tool"
        exp.mkdir()
        (exp / "over.py").write_text("from ... import top\n", encoding="utf-8")  # level=3 退过头
        assert not scan_cross_experiment_imports(tmp_path)                # 射程外 = 不报, 且不崩

    def test_relative_bypass_blocked_in_every_direction(self, tmp_path):
        """守住"换个实验再试一次"这条退路: 判据必须与方向无关。

        只在 nl2tool -> repro 方向测过的话, 把 ``owner`` 与 ``target`` 写反的
        实现仍能过全部断言 —— 所以两个方向各造一棵独立的树。
        """
        for owner, target in (("nl2tool", "repro"), ("repro", "nl2tool")):
            root = tmp_path / f"tree_{owner}"
            (root / owner).mkdir(parents=True)                            # 每轮一棵独立树, 互不污染
            (root / owner / "x.py").write_text(
                f"from ..{target} import thing\n",                       # 相对形态跨到另一实验
                encoding="utf-8",
            )
            found = scan_cross_experiment_imports(root)
            assert found, f"{owner} -> {target} 方向的相对导入被放行 = 判据写反了"

