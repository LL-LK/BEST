# -*- coding: utf-8 -*-
"""eval_runner 自身回归测试 (覆盖矩阵 G-cov-8)。

评测执行器是**质量门禁的实现者**, 却长期没有任何 pytest 覆盖 —— 只能靠人工跑
``--mode all`` 看输出。这意味着 D1 (fail-open) 那类"门禁自己坏掉"的缺陷可以
无限期存在而无人发现: 一个测不出问题的检查比没有检查更危险。

本文件锁死四条缺陷对应的行为, 防回归 (编号 D1/D2/D4/D5 各自独立, 跳号无 D3):

  D1 ``measured`` 语义: 未跑的模式必须让相应维度记 0.0 并报 NOT_MEASURED,
     同时加入阻断项 —— 单模式运行不得宣布通过 (预置 rate=1.0 会使
     ``--mode audit`` 在零行为证据下也能拿高综合分)。
  D4 ``run_audit()`` 的 docstring 不得声称执行 docstring 维度 (实际由 main() 调
     ``run_docstring_dimension()``), 文档范围超出实际会让复核者漏看一个维度。
  D2 ``VERSION_MARKER_RE`` 必须覆盖 YAML 列表项与带引号键两种写法 —— 只认
     行首键的正则会放过那两种写法, 禁版本号铁律在审计层等于有后门。
  D5 ``KnowledgeAuditor.REQUIRED_TOP`` 必须真正参与判定 (只定义不参与等于没有),
     且 ``TestsAuditor`` 不得把同一文件读两遍。
"""
from __future__ import annotations

# 标准库: AST 解析 runner 源码 (验证 docstring 与结构, 不执行 runner) / 正则 /
# 动态加载模块 / sys.modules 注册 (dataclass 字符串注解解析需要)
import ast
import importlib.util
import inspect
import re
import sys
from pathlib import Path

# 第三方: pytest — 测试发现
import pytest

# 本地: 被测的评分函数与审计器 (延迟导入, 避免把 evals 拖进收集期)
# 本地: 被测的评分函数与审计器所在路径 (parents[3] = skill 根 astro-best)
RUNNER = Path(__file__).resolve().parents[3] / "evals" / "eval_runner.py"                        # 评测执行器路径: 它不在包内, 只能按文件加载

# 评分量规的最小组件 (与 evals/scoring-rubric.yaml 同构, 但本地构造以免耦合文件)
RUBRIC = {                                                                                        # 本地构造的量规: 与仓内量规同构但不耦合文件
    "dimensions": {                                                                                 # 维度段
        "correctness": {"weight": 0.30, "criterion": "c"},                                          # 正确性权重最高: 它是其余维度的前提
        "gate_compliance": {"weight": 0.25, "criterion": "g"},                                      # 门禁遵循
        "determinism": {"weight": 0.15, "criterion": "d"},                                          # 确定性
        "provenance": {"weight": 0.10, "criterion": "p"},                                           # 血缘
        "docstring_coverage": {"weight": 0.20, "criterion": "s"},                                   # 文档串覆盖
    },
    "pass_score": 0.9,                                                                              # 通过线
    "warn_line": 0.85,                                                                              # 告警线
}


def _summary(**over):
    """构造一份汇总字典, 镜像 main() 对两种状态的定义。

    ``measured=True`` (默认): 全过 + 带一条 gate 用例明细 —— ``gate_compliance``
    取自 ``details`` 里 ``type == "gate"`` 的真实通过率, 空列表会算成 0.0,
    与"没测"不是一回事, 所以正常路径的夹具必须带 gate 明细。
    ``measured=False``: rate 同时置 0.0, 与 main() 里未跑模式的初始值一致
    (预置成 1.0 正是零行为证据也能拿高综合分的病根)。
    """
    base = {"total": 10, "passed": 10, "rate": 1.0,                                                 # 全绿的基线样本
            "details": [{"type": "gate", "passed": True}], "measured": True}                        # 已测量的审计摘要
    base.update(over)                                                                               # 用覆盖项改写基线
    if not base["measured"]:                                                                       # 未测量时必须改写结论: 这是 D1 的核心
        # 与 main() 的初始值一致: 未跑模式不留任何用例明细, 否则 gate_compliance
        # 会从 details 里算出 1.0, 与"没测"混淆 (那正是 D1 的 fail-open 形态)
        base["rate"] = 0.0  # 预置 1.0 会让零行为证据也能拿高综合分
        base["passed"] = 0                                                                          # 未测量就不许计通过
        base["details"] = []  # 清空明细: 否则 gate_compliance 从 details 反算出 1.0
    return base


def _load_module(name: str, path: Path):
    """按文件路径加载模块, 并注册进 sys.modules。

    注册是必须的: ``evals/audit`` 用了 ``from __future__ import annotations``
    + ``@dataclass``, dataclasses 在解析字符串注解时要按模块名回查
    ``sys.modules``; 不注册会抛 "cannot resolve annotation" 类的内部错误,
    与被测代码无关。

    另需把**模块所在目录**插入 sys.path: 拆分后 eval_runner.py 顶层
    ``from paths / case_executor / probes import ...``, 按文件路径加载时这些同包
    模块不在 sys.path 上会 ImportError。
    """
    spec = importlib.util.spec_from_file_location(name, path)                                       # 按路径造模块规格
    module = importlib.util.module_from_spec(spec)                                                  # 先建模块对象
    sys.modules[name] = module  # 必须先注册: dataclass 解析字符串注解要回查模块名
    parent = str(path.resolve().parent)  # 补 sys.path: 顶层同包 import 才找得到
    if parent not in sys.path:                                                                      # 父目录未在路径里才注入
        sys.path.insert(0, parent)                                                                  # 挂到最前: 否则可能解析到别的同名模块
    spec.loader.exec_module(module)                                                                 # 真正执行模块体
    return module


def _evaluate(scenarios, cases, audit, docstring):
    """调 evaluate_rubric, 每次现取模块以保证读到当前源码。

    刻意不复用 import 期拿到的模块对象: 被测的正是这个 runner, 缓存一次就
    意味着改了源码而断言仍对着旧行为, 门禁会在最需要它的时候静默失效。
    """
    module = _load_module("eval_runner_under_test", RUNNER)  # 每次现取: 缓存即失效
    return module.evaluate_rubric(RUBRIC, scenarios, cases, audit, docstring)


def _load_audit_module():
    """现取 evals/audit 包 (避免 import 期拖入依赖, 也保证读到当前源码)。"""
    return _load_module("audit_under_test", RUNNER.parent / "audit" / "__init__.py")


class TestMeasuredSemantics:
    """D1: 未测的维度必须记 0.0 + NOT_MEASURED + 阻断, 不得伪装成测过。"""

    def test_audit_only_mode_cannot_pass(self):
        """--mode audit (behavior 未跑) 必须判 FAILED, 且行为三维为 0.0/NOT_MEASURED。

        回归锚点: 把未跑模式的 rate 预置成 1.0 的话, 纯审计模式在零行为
        证据下 correctness/determinism 都按满分计, 报出高综合分 (fail-open)。
        """
        result = _evaluate(                                                                         # 喂一份全测量的输入
            _summary(measured=False), _summary(measured=False),  # 行为两路都未跑
            {"auditors": [], "findings": [], "passed": True, "measured": True},                     # 审计摘要
            {"coverage": 1.0, "measured": True},                                                    # 文档串覆盖率
        )
        assert result["passed"] is False  # 单模式运行不得宣布通过 (D1 核心断言)
        assert result["blocking"]["behavior_not_measured"] is True  # 阻断项要显式列出原因
        dims = {d["dimension"]: d for d in result["dimensions"]}  # 按名索引: 顺序不定
        for name in ("correctness", "gate_compliance", "determinism"):                              # 只挑三个维度验: 其余维度不参与本条
            assert dims[name]["score"] == 0.0  # 预置 1.0 = 零证据拿满分
            assert dims[name]["status"] == "NOT_MEASURED"                                           # 未跑的模式必须记未测量

    def test_behavior_only_mode_cannot_pass(self):
        """--mode behavior (审计与 docstring 未跑) 同样必须判 FAILED。"""
        result = _evaluate(                                                                         # 只喂一条未测量的审计摘要
            _summary(), _summary(),                                                                 # 两条全绿的基线
            {"auditors": [], "findings": [], "passed": True, "measured": False},                    # 审计侧显式未测量
            {"coverage": 0.0, "measured": False},                                                   # 文档串侧显式未测量
        )
        assert result["passed"] is False                                                            # 单模式运行不得宣布通过
        assert result["blocking"]["audit_not_measured"] is True  # 两条阻断项各自独立上报
        assert result["blocking"]["docstring_not_measured"] is True                                 # 必须进阻断项: 不阻断就等于没修
        dims = {d["dimension"]: d for d in result["dimensions"]}                                    # 按维度名索引: 断言全靠它
        assert dims["docstring_coverage"]["score"] == 0.0                                           # 分数必须记零而不是默认值
        assert dims["docstring_coverage"]["status"] == "NOT_MEASURED"                               # 状态必须是未测量

    def test_all_measured_passes(self):
        """四类汇总都标记 measured=True 且全过时, 必须照常判通过。

        这条是防"把 measured 语义做成恒 FAIL": 修复不得把正常路径也堵死。
        """
        result = _evaluate(                                                                         # 四条输入全测量
            _summary(), _summary(),                                                                 # 两条基线
            {"auditors": [], "findings": [], "passed": True, "measured": True},                     # 审计侧已测量
            {"coverage": 1.0, "measured": True},                                                    # 文档串侧已测量
        )
        assert result["passed"] is True  # 正常路径不许被 D1 修复误伤成恒 FAIL
        assert not any(result["blocking"].values())  # 全测过时不得留任何阻断项
        assert all(d["status"] == "PASS" for d in result["dimensions"])                             # 全部维度都该是 PASS

    def test_blocking_keys_are_complete(self):
        """blocking 必须含全部六项, 漏一项就等于给那条路径开了后门。

        判的是键集相等而非"包含": 多出来的键会与下游遍历逻辑脱节而无人察觉,
        少出来的键则直接放行一路未阻断的评测, 两种都得在键集层面暴露。
        """
        result = _evaluate(                                                                         # 喂全测量输入
            _summary(), _summary(),                                                                 # 两条基线
            {"auditors": [], "findings": [], "passed": True, "measured": True},                     # 审计侧
            {"coverage": 1.0, "measured": True},                                                    # 文档串侧
        )
        assert set(result["blocking"]) == {                                                         # 阻断项集合必须完整
            "scenarios", "cases", "audit",                                                          # 逐个列出场景与用例侧
            "behavior_not_measured", "docstring_not_measured", "audit_not_measured",                # 三个未测量侧的阻断项也要在
        }


class TestAuditDocstringScope:
    """D4: run_audit 的文档范围必须与实际执行范围一致。

    文档说多了比说少了更难发现: 复核的人照着 docstring 以为某个维度已经跑过,
    实际它归 main() 管, 于是少跑一个维度也不会有人发现。
    """

    def test_run_audit_docstring_does_not_claim_docstring_dimension(self):
        """docstring 不得声称本函数执行 docstring 维度 (那由 main() 单独调)。

        文档范围超出实际, 复核者会误以为少跑一个维度也无所谓 —— 正是 D4 的危害。
        判定用正则而非子串: 正确的 docstring 也会**提到** docstring 维度
        (说明它不归本函数管), 但不许出现"运行/执行 ... docstring 维度"的声明。
        """
        tree = ast.parse(RUNNER.read_text(encoding="utf-8"))  # 只解析源码, 不执行 runner
        func = next(n for n in ast.walk(tree)  # 按名定位, 不依赖定义顺序
                    if isinstance(n, ast.FunctionDef) and n.name == "run_audit")                    # 找到目标函数的定义节点
        doc = ast.get_docstring(func) or ""                                                         # 取它的 docstring
        assert not re.search(r"[运行执行].{0,12}docstring\s*维度", doc), (                               # 不得声称自己执行 docstring 维度
            "run_audit docstring 仍声称执行 docstring 维度")                                               # 报出实际是谁在跑那个维度
        # 同时确认它明确声明了该维度由 main() 负责 (范围澄清到位, 不是含糊其辞)
        assert re.search(r"docstring\s*维度.{0,30}main\(\)", doc, re.S) or "main()" in doc    # 必须指向 main(): 文档范围超出实际会让复核者漏看
        assert "审计器" in doc  # 不得因澄清归属而把本函数职责也一并删掉

    def test_docstring_dimension_is_invoked_by_main(self):
        """main() 必须显式调 run_docstring_dimension() (维度不能没人跑)。"""
        tree = ast.parse(RUNNER.read_text(encoding="utf-8"))                                        # 解析执行器源码
        func = next(n for n in ast.walk(tree)                                                       # 找到目标函数
                    if isinstance(n, ast.FunctionDef) and n.name == "main")                         # 按函数名筛
        called = {n.func.id for n in ast.walk(func)  # 收直接以名字调用的函数名
                  if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}                   # 收集它调用的名字: 用来钉"真的调了这个函数"
        assert "run_docstring_dimension" in called  # 收窄到调用而非整棵 AST


class TestKnowledgeAuditorRequiredTop:
    """D5: REQUIRED_TOP 必须真正参与判定, 且每项检查都要有反证夹具。"""

    def test_required_top_is_used_in_run(self):
        """run() 必须引用 REQUIRED_TOP —— 定义了不用的常量等于没有这项检查。"""
        source = inspect.getsource(_load_audit_module().KnowledgeAuditor.run)                       # 取被审计方法的源码: 结构判据只能看源码
        assert "REQUIRED_TOP" in source  # 源码级引用: 常量被摘掉即红

    def test_missing_topic_is_detected(self):
        """缺一个必需主题文件必须产生 finding 并判败 (反证: 检查真的在干活)。"""
        auditor = _load_audit_module().KnowledgeAuditor()  # 现取模块, 读到当前源码
        # 只给一个无关主题文件 -> 四个必需主题全部缺失
        broken = auditor.broken_samples()["missing_topic"]  # 审计器自带的反证夹具
        assert auditor.check_rejects("missing_topic", broken) is True  # 缺主题必须判败

    def test_all_topics_present_is_accepted(self):
        """四个主题齐备时不得误报 (反证的另一半: 检查不是恒失败)。

        只写"缺主题要报错"这一半的话, 一条恒失败的实现同样能过; 两半合在
        一起才说明这项检查真的在按内容判, 而不是无论输入都报同一个结论。
        """
        auditor = _load_audit_module().KnowledgeAuditor()                                           # 实例化知识审计器
        good = "\n".join(auditor.REQUIRED_TOP)  # 四个主题名各占一行 = 齐备形态
        assert auditor.check_rejects("missing_topic", good) is False                                # 缺 topic 的条目必须被拒


class TestTestsAuditorSinglePass:
    """D5: TestsAuditor 不得把同一文件读两遍。

    重复读取不只是慢: 它把"同一份代码被两个循环各自判定"的窗口打开了, 两处
    判据一旦不同步, 同一文件就会同时出现在通过集与问题集里。
    """

    def test_single_read_per_file(self, tmp_path):
        """每个测试文件只应 read_text 一次 (两个 rglob 循环读两遍即为浪费)。"""
        reads: list[str] = []  # 记录被读的文件名: 断言对象是"读了几遍"
        real_read_text = Path.read_text  # 留住原实现, 计数后照常真读

        def counting_read_text(self, *args, **kwargs):  # noqa: ANN001 - 透传签名
            """记录被读的测试文件名后转调真实实现, 不改任何读取行为。

            计数而非拦断: 拦断会让审计器拿到空内容而报出一堆假 finding, 那样
            就分不清"读了两遍"与"审计器坏了", 反证夹具反而失去指向性。
            """
            if self.name.startswith("test_") and self.suffix == ".py":                              # 只算测试文件: 样例里的数据文件不算
                reads.append(self.name)  # 只记测试文件: 非测试读取与本断言无关
            return real_read_text(self, *args, **kwargs)  # 照常真读, 不改行为

        # TestsAuditor.run 约定 root 下的 test/ 子目录为扫描目标, 夹具须照此布局
        (tmp_path / "test").mkdir()                                                                 # 先建测试目录
        # 夹具内容刻意拼装而不写字面量: TestsAuditor 用文本正则 ``assert\s+True``
        # 扫**本仓库的测试文件**, 本文件若出现该字面量会被它判成"含空断言"而报
        # CRITICAL (实测踩中)。测试数据是"一个断言恒真常量的函数", 用
        # 拼接表达同等语义, 别为了"看起来直观"改回字面量 —— 那会让审计门禁误红。
        broken_body = "def test_ok():\n    assert " + "True\n"  # 拼装, 勿改回字面量
        (tmp_path / "test" / "test_sample.py").write_text(                                          # 写一个语法错的测试文件
            broken_body, encoding="utf-8")                                                         # 坏正文: 这里要验的是审计器会不会二次读它
        with pytest.MonkeyPatch.context() as mp:  # 上下文管理器: 出块即自动还原
            mp.setattr(Path, "read_text", counting_read_text)  # 类级打桩
            _load_audit_module().TestsAuditor().run(tmp_path)                                       # 跑审计: 坏文件不该让整轮崩掉
        assert reads.count("test_sample.py") == 1, f"读取了 {len(reads)} 次: {reads}"  # 恰一次


class TestVersionMarkerCoverage:
    """D2: 禁版本号正则必须覆盖全部常见 YAML 写法, 不许有后门。

    正则类门禁的两种失效都危险: 漏一种写法等于铁律有后门, 而命中得太宽则
    审计输出被误报淹没, 久了就没人看 —— 所以正向与反向必须成对守。
    """

    # 四种合法 YAML 写法, 全部必须被判违规。
    # 前两种是旧正则的盲区 (D2 修复的动机), 后两种是原有覆盖 (防改坏)。
    SPELLINGS = (                                                                               # 各种版本号拼写: 少认一种就是禁版本号铁律的后门
        "version: 1.2.3\n",                       # 行首键 (原有覆盖)
        "dependencies:\n  - version: 1.2.3\n",    # YAML 列表项 (旧正则盲区)
        "meta:\n  'version': 1.2.3\n",            # 单引号键 (旧正则盲区)
        'meta:\n  "version": 1.2.3\n',            # 双引号键 (旧正则盲区)
    )

    @pytest.mark.parametrize("text", SPELLINGS)
    def test_all_version_spellings_are_flagged(self, text):
        """每种写法都必须被 VERSION_MARKER_RE 命中 (漏一种 = 铁律有后门)。"""
        regex = _load_audit_module().VERSION_MARKER_RE                                              # 取被测正则
        assert regex.search(text), f"漏杀: {text!r}"                                                  # 逐条必须命中

    @pytest.mark.parametrize("text", (
        "# 说明里提到 version 字段但不是声明\n",                                                                # 说明里提到该词但不是声明
        "api_version_string: 1.2.3\n",     # 词中缀, 不是 version 键
        "conversions:\n  - from: a\n  - to: b\n",                                                   # 列表项里也不该命中
    ))
    def test_non_declarations_are_not_flagged(self, text):
        """反向: 行内提及/词中缀不得命中, 否则审计会被误报淹死。

        api_version_string 与 conversions 这两条是特意挑的中缀与近形词: 只按
        "行内含 version 六个字母"来写的正则会一并命中, 而按词边界写的正确
        形态才过得去, 这组载荷正是用来区分两者的。
        """
        regex = _load_audit_module().VERSION_MARKER_RE                                              # 取被测正则
        assert regex.search(text) is None, f"误报: {text!r}"                                          # 逐条不得命中

    def test_repo_files_have_no_version_markers(self):
        """全仓扫描: contracts/ templates/ references/ rag/knowledge 不得有版本键。

        这条是 D2 的**实效**证据 —— 正则修好后拿真实文件跑一遍, 确认既没漏报
        (有版本键而没抓到) 也没误报 (抓到的其实不是版本键)。
        """
        regex = _load_audit_module().VERSION_MARKER_RE                                              # 取被测正则
        offenders: list[str] = []  # 命中清单: 路径:行号, 便于定位残留
        for rel in ("contracts", "templates", "references", "rag/knowledge"):                       # 逐个目录扫: 声明面分布在多处
            base = RUNNER.parent.parent / rel  # 四个裁定过的 SSOT 目录
            if not base.is_dir():                                                                  # 目录不存在就跳过: 裁剪克隆时子树可能缺失
                continue  # 裁剪克隆里目录可能不存在, 跳过而非崩
            for path in sorted(base.rglob("*.yaml")) + sorted(base.rglob("*.md")):                  # 两种扩展名都要扫
                if "skills-spec.local" in path.name:                                                # 本地切片本身豁免: 它是规范不是产物
                    continue  # 本地 spec 切片自带 schema 版本标识, 已裁定保留
                for i, line in enumerate(path.read_text(encoding="utf-8",                           # 逐行读, 抗解码失败
                                                        errors="replace").splitlines(), 1):         # 带行号: 报错要能直接定位
                    if regex.search(line):  # 逐行扫: 正则只看单行, 不跨行匹配
                        offenders.append(f"{path.relative_to(RUNNER.parent.parent)}:{i}")           # 记下相对路径与行号
        assert not offenders, "发现版本键残留:\n" + "\n".join(offenders[:20])


class TestScoringCannotBeRigged:                                                       # 反作弊: 最终判定必须真的由实测证据决定
    """A6-03: ``eval_runner`` 的最终判定不得被一行恒真化掰绿。

    起因 (2026-10-04 突变实验): 真实探针失败时 runner 判红**是正确的**
    (``0/25 · 0.7000 · FAILED · exit 1``), 但只要在
    ``run_scenario_evals()`` 里加一行 ``ok, note = True``, 整轮就变成
    ``SUCCESS / 1.0000 / exit 0`` —— 而**全量 1374 个测试零反应**。
    对照组: 同类突变打在 E1 会被 ``test_exact_grader`` 抓住, 唯独这个
    legacy runner 缺反作弊测试。

    也就是说: 上面那些 ``TestMeasuredSemantics`` 只验"配置形态" (喂什么摘要
    得什么分), 而最终判定那一层 (``evaluate_rubric`` 的阻断项 + ``main``
    的退出码) 从没被反向验证过 —— 没人证明过"**真的坏了**时它会红"。

    本类补的就是这一层: 注入一个"探针真的失败"的事实, 断言 runner 判红。
    恒真化会让这些断言当场爆红, 因为断言读的是 runner **真跑**出来的判定。
    """

    @staticmethod
    def _runner():
        """现取 runner 模块 (缓存即失效: 被测的正是它的当前源码)。"""
        return _load_module("eval_runner_antirig", RUNNER)

    def test_failing_probe_makes_final_verdict_red(self, monkeypatch):
        """一个探针真失败 -> 场景通过率 <1.0 -> 必须进阻断项且整体判红。

        走 ``main()`` 的真实路径 (``--mode behavior`` 只跑探针与用例, 不牵
        审计), 并把 ``SCENARIO_PROBES`` 换成"一个必失败的探针"。若有人把
        ``ok, note = probe()`` 改成 ``ok, note = True``, 本断言立刻红 ——
        那正是本条存在的意义。
        """
        module = self._runner()
        monkeypatch.setitem(module.SCENARIO_PROBES, "cone_search", lambda: (False, "注入的失败"))  # 必败探针: 事实层
        monkeypatch.setitem(module.SCENARIO_PROBES, "task_log", lambda: (False, "注入的失败"))      # 再败一个: 防止"恰好是最后一个"的巧合
        scenarios = module.run_scenario_evals({"evaluations": [{"id": "cone_search"}, {"id": "task_log"}]})  # 真跑汇总层
        assert scenarios["rate"] < 1.0, "必败探针却算出满通过率 = 判定被恒真化"
        # 再往上走一层: 汇总层的失败必须**传导**到最终判定, 否则修汇总层也没用
        result = _evaluate(scenarios, _summary(), _summary(), _summary())  # 其余三路喂全绿基线
        assert result["passed"] is False, "真实探针失败却判整体通过 = 恒定 1.0000 的假门禁"
        assert result["blocking"]["scenarios"] is True, "失败必须落在 blocking.scenarios 上"

    def test_exception_raising_probe_counts_as_failure(self, monkeypatch):
        """探针抛异常必须记失败, 不得被 ``except`` 吞成通过或整轮中断。"""
        module = self._runner()

        def boom():
            """必抛异常的探针: 验证异常路径不被当成通过。"""
            raise RuntimeError("注入的探针异常")

        monkeypatch.setitem(module.SCENARIO_PROBES, "cone_search", boom)  # 换成必炸探针
        scenarios = module.run_scenario_evals({"evaluations": [{"id": "cone_search"}]})
        assert scenarios["rate"] == 0.0, "抛异常的探针被算成通过 = 异常路径恒真化"
        result = _evaluate(scenarios, _summary(), _summary(), _summary())
        assert result["passed"] is False, "探针异常却判整体通过"

    def test_unknown_scenario_id_is_failure(self, monkeypatch):
        """未登记的场景 id 必须显式判失败 (EVAL-04: 杜绝"文件存在即过")。"""
        module = self._runner()
        monkeypatch.delitem(module.SCENARIO_PROBES, "cone_search", raising=False)  # 注销: 制造未登记 id
        scenarios = module.run_scenario_evals({"evaluations": [{"id": "cone_search"}]})
        assert scenarios["rate"] == 0.0, "未登记场景 id 被放行 = '存在即过'"
        result = _evaluate(scenarios, _summary(), _summary(), _summary())
        assert result["passed"] is False, "未登记场景却判整体通过"

    def test_failed_case_is_a_blocking_condition(self):
        """用例侧失败 (cases_summary.rate <1.0) 同样必须阻断并判红。"""
        failing_cases = _summary(rate=0.5, passed=5)  # 10 条里过 5 条
        result = _evaluate(_summary(), failing_cases, _summary(), _summary())
        assert result["passed"] is False, "用例失败却判通过 = 门禁只看加权分不看阻断"
        assert result["blocking"]["cases"] is True, "用例失败必须落在 blocking.cases 上"

    def test_failed_audit_is_a_blocking_condition(self):
        """审计器判败 (audit.passed=False) 必须阻断并判红。"""
        result = _evaluate(_summary(), _summary(), {"auditors": [], "findings": [], "passed": False, "measured": True}, _summary())
        assert result["passed"] is False, "审计判败却判通过"
        assert result["blocking"]["audit"] is True, "审计失败必须落在 blocking.audit 上"

    def test_exit_code_follows_passed_flag(self):
        """``main()`` 的退出码必须跟着 ``passed`` 走, 不得恒 0 或恒 1。"""
        module = self._runner()
        assert module.main(["--mode", "behavior", "--json"]) in (0, 1), "退出码必须落在 {0,1}"
        # 判红的具体退出码: 把审计维度按"未测量"喂进去必然阻断, 只验它 != 0
        result = _evaluate(_summary(), _summary(), {"auditors": [], "findings": [], "passed": True, "measured": False}, _summary())
        assert result["passed"] is False

