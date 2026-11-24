# -*- coding: utf-8 -*-
"""门禁**覆盖面**的判据级红测试: 扫描面之外的文件必须仍然进门禁 (D5-01)。

起因 (2026-10-05 判据审计 D5-01, 本轮修复): ``count_code_lines.py`` /
``comment_audit.py`` / ``verify_doc_consistency.py`` / ``code_fingerprint.py``
各自抄了一份同款目录白名单 ``SCAN_DIRS = ("src", "ops", ...)``, 于是**白名单之外的
``.py` 完全免检**。实测: 在 ``agents/`` 下放一个 900 净行的文件, 四道门禁全部
exit 0 —— 铁律 2 (单文件 ≤400 净行) 被违反 900 行而门禁全绿, 一处缺口同时废掉
行数预算、注释质量、文档一致性与代码指纹四条判据。

修法是**黑名单**口径: 扫描面收敛到唯一真源 ``ops/audit/scan_roots.py`` 的
:func:`scan_roots.iter_py_files` (走遍全仓 .py, 只排除工具状态/依赖/临时区)。本文件
把那条判据钉住, 免得它退化回白名单。

取证纪律沿用 ``test_gate_criterion_red.py``: 每条"会放过 X"都配**同内容对照组** ——
把**同一份**缺陷文件分别放进"白名单内的 ``src/``"与"白名单外的 ``agents/``",
两者退出码必须不同 (src 判红 / agents 判绿 = 判据缺口; 两者都判红 = 缺口已补;
两者都判绿 = 门禁恒绿, 测试等于没写)。用同一份内容而不是两份, 是为了让唯一的
变量是**落位目录**, 红绿差异就只可能来自覆盖面。

假仓造法: 把整个 ``ops/audit/`` 复制到 ``假仓/ops/audit/`` (门禁是同目录裸名互导,
只复制单文件会 ModuleNotFoundError —— 那会伪装成"门禁判红"), 于是门禁的
``parents[2]`` 自动落到假仓, 真仓自始至终不被触碰 (铁律 3)。
"""
from __future__ import annotations

# 标准库: os 走子进程的环境 / shutil 造假仓 / subprocess 跑真门禁 / sys 解释器 /
# pathlib 路径 (相对路径用 posix 拼, 与门禁输出的路径形态一致)
import os
import shutil
import subprocess
import sys
from pathlib import Path

# 第三方: pytest 提供参数化, 让四道门禁共用一份用例体
import pytest

SKILL_ROOT = Path(__file__).resolve().parents[3]  # 仓根: 本文件在 test/unit/meta/, 上溯三级
AUDIT_DIR = SKILL_ROOT / "ops" / "audit"          # 门禁脚本真身所在目录

# 共用求解器: 造假仓时只复制「被测门禁 + 它的同目录依赖」, 理由见该函数 docstring。
# 显式把 test/ 塞进 sys.path: 本文件被 test_no_module_skip_guards.py 在**干净子进程里
# 裸导入**验过, 那时 pytest 的路径注入不存在 (详见那里的探针说明)。
sys.path.insert(0, str(SKILL_ROOT / "test"))  # test/ 目录: conftest.py 在此
from conftest import gate_dependency_closure  # noqa: E402  路径注入必须在导入之前

SKILL_ROOT = Path(__file__).resolve().parents[3]  # 仓根: 本文件在 test/unit/meta/, 上溯三级
AUDIT_DIR = SKILL_ROOT / "ops" / "audit"  # 门禁脚本真身所在目录
# 白名单时代的七个扫描根: 保留这份字面量**只用于对照实验** —— 断言"白名单漏掉的
# 目录现在必须进门禁"。门禁自己不再持有它 (那正是本轮删掉的东西)。
LEGACY_WHITELIST = ("src", "ops", "evals", "test", "examples", "rag", "docs/diagrams")


def build_fake_repo(tmp_path: Path, gate: str = "comment_audit") -> Path:
    """造假仓并只放**被测门禁 + 它的同目录依赖** (不多复制一个)。

    复制整个 ``ops/audit/`` 会让「干净对照组」被**与被测命题无关**的 .py 带红:
    假仓里每个门禁副本都进门禁扫描面, 于是任一副本自身出现违规 (注释密度 /
    DEADPARAM / 超 400 行未登记) 就让 ``test_clean_repo_exits_zero`` 变红, 而那些
    用例声称测的是「落位是否影响覆盖面」。实测两个通道 (门禁失败方向审计 2026-10-05,
    N2 复核): 只在被复制的 ``check_line_endings.py`` 副本里注入一个假声明,
    ``verify_doc_consistency`` 立刻只报那个副本而对照件干净; 把被复制的
    ``scan_code_smells.py`` 换成远超 400 净行的内容, 假仓无登记簿于是任何超限都算
    「未登记」。引爆点很近: ``comment_audit.py`` 334 净行, 距 400 只剩 66 行。

    闭包按**真实 import** 递归算出 (``test/conftest.py::gate_dependency_closure``),
    不手抄名单 —— 手抄会在门禁新增依赖时过期, 而过期的闭包会伪装成「门禁判红了」。

    Args:
        tmp_path: pytest 提供的临时目录, 假仓建在它下面。
        gate: 被测门禁名; 决定复制哪一份依赖闭包。

    Returns:
        假仓根目录 (``.../fakerepo``), 门禁的仓根会自动落到这里。
    """
    fake = tmp_path / "fakerepo"
    (fake / "ops" / "audit").mkdir(parents=True)  # 门禁落位: parents[2] 即假仓根
    for filename in gate_dependency_closure(gate):  # 被测门禁 + 递归依赖
        shutil.copy(AUDIT_DIR / filename, fake / "ops" / "audit" / filename)  # 原样复制, 测的是真门禁
    return fake


def run_in(fake: Path, gate: str) -> subprocess.CompletedProcess:
    """在假仓里以子进程跑一条门禁, 返回其退出码与输出。

    子进程而非 import: 门禁是"导入即执行"的脚本体, 在本进程里跑会污染 pytest
    的模块表与 cwd。

    Args:
        fake: 假仓根。
        gate: 门禁模块名 (对应 ``ops/audit/<gate>.py``)。

    Returns:
        已完成的子进程对象 (取 ``returncode`` / ``stdout``)。
    """
    return subprocess.run(  # noqa: S603  argv 全是本仓常量, 无 shell
        [sys.executable, str(fake / "ops" / "audit" / f"{gate}.py")],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=300, cwd=str(fake),  # cwd 指向假仓: 门禁按相对路径读登记簿/文档
        # 只覆盖编码与扫描面下限, 其余环境原样继承。
        # 下限调到 1 是**必填项**而非绕过: 本假仓按设计只有两三个 .py (闭包 + 被测对象),
        # 而负对照闸的下限是 100 (真仓 326) —— 不显式声明就会被"扫描面异常稀薄"判红,
        # 那是关于**这个假仓**的如实告警, 与本文件要测的"落位决定覆盖面"无关。
        # 声明它等于书面承认"我知道这个仓故意很小" (见 scan_roots.MIN_SCAN_OVERRIDE_ENV)。
        env={**os.environ, "PYTHONIOENCODING": "utf-8", "ASTRO_BEST_MIN_SCAN_FILES": "1"},
        check=False,
    )


# 三道门禁各配一份"该门禁本该抓住"的缺陷内容。体量都刻意压到最小 ——
# 本文件要证明的是**落位**决定判定, 不是缺陷本身的复杂度。
FAT_MODULE = "".join(f"V{i} = {i} + 1\n" for i in range(450))  # 450 净行: 超 400 预算且未登记
UNDOCUMENTED = "def helper(value):\n    return value + 1\n"  # 无 docstring: Q1 判红
DEAD_PARAM = (  # 按 Google 风格声明一个函数体里零引用的形参
    "def handler(payload, cursor):\n"
    '    """处理载荷。\n\n'
    "    payload: 载荷内容。\n"
    "    cursor: 用于分页游标, 必须参与下游查询。\n"
    '    """\n'
    "    return payload\n"
)  # 声明了 cursor 却零引用: DEADPARAM 判红

DEFECT_CASES = [  # 三道门禁各配一份该门禁本该抓住的缺陷内容
    ("count_code_lines", "fat.py", FAT_MODULE),
    ("comment_audit", "undocumented.py", UNDOCUMENTED),
    ("verify_doc_consistency", "deadparam.py", DEAD_PARAM),
]
UNSCANNED_DIR = "agents"  # 白名单时代的缺口: 该目录真实存在但不在七个扫描根内
# 干净的对照件: 模块头够长且含中文、函数有中文 docstring; 净行不足 15 行时
# Q6 密度 / Q7 行尾占比 / Q10 逐行对照率按设计跳过, 所以它不需要凑注释 ——
# 它要证明的只是"落位不改变判定"。
CLEAN_MODULE = '''"""U5 判据对照用的干净模块 (覆盖面判据的"不误报"那一半)。

本文件存在的唯一理由: 给扫描面判据配一道**干净**对照件。它与缺陷件的唯一差别是
内容本身合规, 落位目录仍由调用方决定 —— 于是"落位改变判定"这件事可以被单独观察。
合规的判据必须同时做到两件事: 该抓的抓到 (缺陷件判红), 不该抓的放过 (本件不进
违规报告); 只证明前一半的门禁, 收紧判据就会变成误报机器, 大家随即学会忽略它。

合规口径: 模块头够长 (>=160 字符) 且含中文, 每个函数都要有中文 docstring, 形参
说明与函数体引用一致。净代码行不足 15 行时, 注释密度、行尾占比与逐行对照率三条
判据按设计整组跳过, 所以本件不需要凑注释。
"""


def helper(value):
    """返回值加一后的结果。

    Args:
        value: 输入数值。

    Returns:
        加一后的数值。
    """
    return value + 1
'''


class TestScanScopeIsNotVacuous:
    """同一份缺陷, 放进白名单外的目录必须与放进 src/ 一样被判红。"""

    @pytest.mark.parametrize("gate,name,body", DEFECT_CASES, ids=[c[0] for c in DEFECT_CASES])
    def test_defect_outside_legacy_whitelist_is_rejected(self, tmp_path, gate, name, body):
        """反证: 缺陷落在 ``agents/`` (旧白名单之外) 时, 门禁必须非零退出。

        这是 D5-01 那道缺口的正面取证: 修好之前这里是 exit 0。stdout 里还必须
        点名这个文件 —— 只断退出码的话, 门禁因为别的原因红 (例如假仓缺登记簿)
        也能满足 ``!= 0``, 证据强度不够。
        """
        assert UNSCANNED_DIR not in LEGACY_WHITELIST, "对照组前提变了: 该目录本就在白名单内"
        fake = build_fake_repo(tmp_path, gate)  # 造假仓: 只放被测门禁 + 依赖闭包
        target = fake / UNSCANNED_DIR / name  # 缺陷落在旧白名单看不到的目录
        target.parent.mkdir(parents=True)
        target.write_text(body, encoding="utf-8")
        proc = run_in(fake, gate)  # 跑真门禁 (副本), 取它的退出码
        assert proc.returncode != 0, (
            f"{gate}: 落在 {UNSCANNED_DIR}/ 的缺陷必须判红 (扫描面退回白名单了?)\n"
            f"stdout: {proc.stdout[-600:]}\nstderr: {proc.stderr[-400:]}"
        )
        assert f"{UNSCANNED_DIR}/{name}" in proc.stdout, (
            f"{gate}: 报告里必须点名这个文件, 否则红的原因与它无关\nstdout: {proc.stdout[-600:]}"
        )

    @pytest.mark.parametrize("gate,name,body", DEFECT_CASES, ids=[c[0] for c in DEFECT_CASES])
    def test_same_defect_inside_src_is_rejected_too(self, tmp_path, gate, name, body):
        """对照组: **同一份**缺陷放进 ``src/`` (旧白名单内) 同样必须判红。

        这条是上一条的对照: 两者内容逐字相同, 唯一变量是落位目录。若两条都判绿,
        说明门禁恒绿 (本测试等于没写); 只在 src/ 判红而 agents/ 判绿, 则是覆盖面
        缺口 —— 上一条正是为钉住它而存在。
        """
        fake = build_fake_repo(tmp_path, gate)  # 同一棵假仓构造, 只换落位目录
        target = fake / "src" / name  # 缺陷落在旧白名单内的目录
        target.parent.mkdir(parents=True)
        target.write_text(body, encoding="utf-8")
        proc = run_in(fake, gate)  # 跑真门禁副本, 取退出码
        assert proc.returncode != 0, (
            f"{gate}: src/ 下的缺陷都必须判红, 实得 exit={proc.returncode}\n"
            f"stdout: {proc.stdout[-600:]}\nstderr: {proc.stderr[-400:]}"
        )

    @pytest.mark.parametrize("gate", ["count_code_lines", "verify_doc_consistency"])
    def test_clean_repo_exits_zero(self, tmp_path, gate):
        """对照: 无缺陷的假仓必须 exit 0 (证明上面两条的红来自缺陷本身)。"""
        fake = build_fake_repo(tmp_path, gate)  # 同一棵假仓构造, 这次不注入缺陷
        (fake / "src").mkdir()
        (fake / "src" / "ok.py").write_text("VALUE = 1\n", encoding="utf-8")
        proc = run_in(fake, gate)  # 跑真门禁副本, 取退出码
        assert proc.returncode == 0, f"{gate}: 干净假仓必须 exit 0: {proc.stdout[-400:]}"

    @pytest.mark.parametrize("place", ["src", UNSCANNED_DIR])
    def test_compliant_file_is_never_reported(self, tmp_path, place):
        """comment_audit 的对照组改断"报告成员"而不是退出码, 理由必须写清。

        假仓里躺着门禁脚本的**副本**, 而这些副本的注释里引用了真实仓才有的路径
        (如 ``docs/architecture/file-size-budget.md``), 于是 Q9 路径判据恒有命中 ——
        那是取证环境的固有噪声, 与被注入文件无关。所以这里断的是"干净的对照件
        **没有**进违规报告", 它同样是覆盖面的证据: 判据既不漏报缺陷 (上面两条),
        也不误报干净文件 (本条)。断退出码反而会把噪声算成被测行为。
        """
        fake = build_fake_repo(tmp_path, "comment_audit")  # 同一棵假仓构造 (本条只跑 comment_audit)
        target = fake / place / "clean.py"  # 干净对照件: 落位目录是唯一变量
        target.parent.mkdir(parents=True)
        target.write_text(CLEAN_MODULE, encoding="utf-8")
        proc = run_in(fake, "comment_audit")
        # 先断"门禁真的跑完了": 假仓里没有 temp/, 而 comment_audit 要往那儿写
        # 产物 —— 判据审计 D5-05 实测过"目录缺失即 FileNotFoundError 崩掉", 而崩掉
        # 时 stdout 是空的, 上面那条"不在报告里"会**空转通过**。所以必须先钉住
        # 它跑完了 (无 Traceback + totals 那行真的打出来了), 再谈报告内容。
        assert "Traceback" not in proc.stderr, (
            f"comment_audit 崩了而不是判完 —— 红的理由不是注释有问题 (D5-05 修复回退?):\n"
            f"stderr: {proc.stderr[-600:]}"
        )
        assert "docstring_not_chinese" in proc.stdout, (
            f"totals 行没打出来, 说明这一轮没跑完: {proc.stdout[-400:]}"
        )
        assert f"{place}/clean.py" not in proc.stdout, (
            f"干净的对照件被误报了: {proc.stdout[-600:]}"
        )


class TestScanScopeIsSingleSource:
    """覆盖面只能有一份定义: 四道门禁都从 ``scan_roots`` 取, 谁都不许自带清单。"""

    GATES = ("count_code_lines", "comment_audit", "verify_doc_consistency", "code_fingerprint")

    @pytest.mark.parametrize("gate", GATES)
    def test_gate_imports_shared_scope(self, gate):
        """四道门禁必须导入共享真源, 而不是自己列一份目录。"""
        src = (AUDIT_DIR / f"{gate}.py").read_text(encoding="utf-8")
        assert "from scan_roots import" in src, (
            f"{gate}.py 不再从 scan_roots 取扫描面 —— 覆盖面又有了第二份真源"
        )

    @pytest.mark.parametrize("gate", GATES)
    def test_gate_defines_no_own_scan_dir_tuple(self, gate):
        """反向断言: 门禁里不得再出现 ``SCAN_DIRS = (...)`` 这类自带清单。

        写成 ``assert not offenders`` 而不是 ``for ... pytest.fail``: 后者在
        清单不存在时**循环体一次都不执行**, 整条测试零断言恒绿 —— 评审器
        (eval_runner) 正是把它判为 MAJOR 零断言测试并把 correctness 打到 0.800。
        这里额外断一次"确实读到了非空源码", 防止把读不到文件也当成通过。
        """
        src = (AUDIT_DIR / f"{gate}.py").read_text(encoding="utf-8")
        lines = src.splitlines()
        offenders = [  # 自带清单的那一行就是覆盖面第二份真源
            (idx + 1, line) for idx, line in enumerate(lines) if line.strip().startswith("SCAN_DIRS")
        ]
        assert not offenders, (  # 断"没有"而不是"逐行 fail": 保证这条永远带断言
            f"{gate}.py 又自带了一份扫描面清单: " + ", ".join(f"L{n}: {t.strip()}" for n, t in offenders)
        )
        assert len(lines) > 10, f"{gate}.py 只读到 {len(lines)} 行, 判据可能没真正生效 (防空读)"


class TestExclusionsAreNarrow:
    """排除项必须窄到"只排非源码": 排掉的目录里不得藏着任何受跟踪的 .py。

    这是黑名单口径自带的**开后门**形态: 判据有了统一出口之后, 只要往排除项里加
    一个名字就能给整片源码免检, 而门禁仍然全绿。实测形态与 D5-01 同型, 只是方向
    反过来 —— 所以判据收紧的同时必须把"排除项"也钉住。
    """

    def test_no_excluded_dir_holds_tracked_python(self):
        """排除名单里的目录名, 不得对应任何含受跟踪 .py 的目录。"""
        sys.path.insert(0, str(AUDIT_DIR))  # 同目录裸名导入: 直跑时 sys.path[0] 就是它
        import scan_roots  # noqa: PLC0415  局部导入: 注入 sys.path 之后才可导

        tracked = subprocess.run(  # noqa: S603  argv 固定, 无 shell
            ["git", "ls-files", "*.py"], cwd=str(SKILL_ROOT),
            capture_output=True, text=True, encoding="utf-8", check=True,
        ).stdout.splitlines()
        tracked_dirs = {Path(p).parts[0] for p in tracked if p}  # 受跟踪 .py 所在的顶层目录
        hidden = {d for d in tracked_dirs if d.startswith(".")}  # 隐藏目录本就不该有受跟踪 .py
        offenders = sorted((tracked_dirs | hidden) & set(scan_roots.EXCLUDED_DIRS))  # 显式名单里的交集
        offenders += sorted(d for d in hidden if scan_roots.is_excluded_dir(d))  # 隐藏目录规则的交集
        assert not offenders, (
            f"排除项里出现了含受跟踪 .py 的目录 —— 那是给源码开了免检通道: {offenders}"
        )

    def test_scan_covers_every_tracked_python_file(self):
        """覆盖面必须是受跟踪 .py 的**超集**: 一个都不能漏 (漏即免检)。"""
        sys.path.insert(0, str(AUDIT_DIR))  # 同目录裸名导入
        import scan_roots  # noqa: PLC0415  局部导入: 注入 sys.path 之后才可导

        tracked = subprocess.run(  # noqa: S603  argv 固定, 无 shell
            ["git", "ls-files", "*.py"], cwd=str(SKILL_ROOT),
            capture_output=True, text=True, encoding="utf-8", check=True,
        ).stdout.splitlines()
        scanned = {rel for rel, _ in scan_roots.iter_py_files(str(SKILL_ROOT))}  # 全仓扫描面取回来
        missing = sorted({p.replace(os.sep, "/") for p in tracked} - scanned)
        assert not missing, f"受跟踪的 .py 落在扫描面之外 (即免检): {missing}"

    def test_brand_new_directory_is_scanned_automatically(self):
        """新建一个从未见过的目录放 .py, 必须自动进门禁 (黑名单的"默认方向")。"""
        sys.path.insert(0, str(AUDIT_DIR))  # 同目录裸名导入
        import tempfile  # noqa: PLC0415  仅本用例要现造目录树

        import scan_roots  # noqa: PLC0415  局部导入: 注入 sys.path 之后才可导

        with tempfile.TemporaryDirectory() as tmp:  # 现造目录树, 退出即回收
            root = Path(tmp)
            (root / "brand_new_dir").mkdir()
            (root / "brand_new_dir" / "m.py").write_text("V = 1\n", encoding="utf-8")
            found = [rel for rel, _ in scan_roots.iter_py_files(str(root))]
        assert found == ["brand_new_dir/m.py"], f"新目录必须自动进门禁, 实得 {found}"
