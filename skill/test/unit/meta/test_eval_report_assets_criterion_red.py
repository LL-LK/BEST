# -*- coding: utf-8 -*-
"""``verify_eval_report_assets`` 的**判据级**红测试 (N9 / P0-C 补齐, 2026-10-07)。

起因 (P0-C 实测): 第十道硬门禁 ``verify_eval_report_assets`` **零判据级覆盖** ——
把它的 :func:`verify_eval_report_assets.scan` 改成 ``return []`` 之后, 357 个 meta
测试**零反应**。同形变异在别的门禁上能被抓红 (说明那些测试确实在测判据), 唯独这道
抓不住, 于是"门禁已被改废"这件事在全仓测试里没有任何一处会响。

为什么这道门偏偏需要判据级测试: 它守的是"入库的 ``evals/**/REPORT.md`` 与 HEAD
一致", 触发条件极其日常 —— ``make evals-all`` 每跑一次就刷新一次「生成时间」一行。
判据一旦退化 (``scan`` 恒返空), ``make audit`` 恒绿, 而真正危险的形态 (报告里某个
指标掉了、某个 blocker 消失, 报告已不再描述当前行为) 同样没人拦。

取证纪律沿用 ``test_tree_integrity_criterion_red.py`` 与
``test_gate_criterion_red.py``: **每条"必须判红"都配一道干净对照**。少了对照,
"门禁恒红"与"门禁恒绿"同样能满足 ``!= 0``, 证据等于零。

假仓造法: 本门禁的 ``root`` 是**显式参数** (它自己的模块头就写了这条参数化是留给
判据级红测试的), 所以不必复制门禁脚本 —— 直接在 ``tmp_path`` 下 ``git init`` 一个
真仓, 提交一份 REPORT.md, 再按用例改它。**真仓自始至终不被触碰**: 门禁的
"只报不改"纪律 (不 ``git checkout``) 在假仓上同样成立, 脏文件留在 ``tmp_path`` 里
随用例结束而弃。
"""
from __future__ import annotations

# 标准库: os 传给子进程的环境 / subprocess 跑真 git / sys 解释器 / pathlib 路径
import os
import subprocess
import sys
import tempfile
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[3]  # 仓根: 本文件在 test/unit/meta/, 上溯三级
GATE_MODULE = "ops.audit.verify_eval_report_assets"  # 门禁真身: 在 ops/audit/ 下, 与树门禁 (ops/ 根) 不同

# 假仓提交用的身份与禁签名配置: 门禁只读 git 清单, 但造仓要真能 commit 成功。
_GIT_ENV = {  # 局部覆盖而不改 os.environ: 真仓的 git 配置一律不碰
    "GIT_AUTHOR_NAME": "gate-test", "GIT_AUTHOR_EMAIL": "gate@example.invalid",
    "GIT_COMMITTER_NAME": "gate-test", "GIT_COMMITTER_EMAIL": "gate@example.invalid",
    "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull,  # 隔离机器上的全局配置
    "GIT_OPTIONAL_LOCKS": "0",
}

_REPORT_BODY = "# 报告\n\n生成时间: 2026-10-07 22:00:00\nmetascore: 1.0000\n"  # 基线报告内容


def _git(fake: Path, *args: str) -> subprocess.CompletedProcess:
    """在假仓里跑一条 git 命令。

    Args:
        fake: 假仓根目录。
        *args: git 子命令与参数 (如 ``"init"`` / ``"add"`` / ``"commit"``)。

    Returns:
        已完成的子进程对象; 失败时直接抛 —— 造仓失败会让红绿都失去意义。
    """
    proc = subprocess.run(  # noqa: S603  argv 全是本仓常量与 tmp_path, 无 shell
        ["git", "-C", str(fake), *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=300, env={**os.environ, **_GIT_ENV}, check=False,
    )
    if proc.returncode != 0:  # 造仓失败必须炸: 否则下面的红绿只是在测一个空目录
        raise AssertionError(f"造仓用的 git 命令失败: git {args}\n{proc.stdout}\n{proc.stderr}")
    return proc


def build_committed_repo(tmp_path: Path, *, with_report: bool = True) -> Path:
    """造一个已提交的真 git 假仓, 内含一份 ``evals/<实验>/REPORT.md``。

    ``with_report=False`` 用来造"扫描面为空"的形态: 那条形态门禁必须**判红**,
    零输入的绿灯只蕴含「没有触发任何条件」。

    Args:
        tmp_path: pytest 提供的临时目录。
        with_report: 是否提交 REPORT.md。

    Returns:
        假仓根目录。
    """
    fake = tmp_path / "fakerepo"
    (fake / "evals" / "demo").mkdir(parents=True)  # 与真仓同构: evals/<实验>/REPORT.md
    if with_report:  # 两种造法共用一条造仓路径: 只有内容不同
        (fake / "evals" / "demo" / "REPORT.md").write_text(_REPORT_BODY, encoding="utf-8")
    else:
        (fake / "evals" / "demo" / "keep.txt").write_text("占位, 但不是 REPORT.md\n", encoding="utf-8")
    _git(fake, "init", "-q")                 # 真 git 仓: 门禁靠 git ls-files / git diff 取数
    _git(fake, "add", "-A")                  # 先暂存再提交: 新仓无 HEAD 时 git diff HEAD 会失败
    _git(fake, "commit", "-q", "-m", "基线提交")
    return fake


def run_gate(fake: Path) -> subprocess.CompletedProcess:
    """以子进程跑第十道门禁, 并把 ``--root`` 指向假仓。

    走子进程而不是直接调 ``main()``: 门禁的中文理由是直写 stderr 字节通道的
    (``_emit``), 编码随 locale 变 —— 子进程能连"理由有没有真的打到 stderr"一起验。

    Args:
        fake: 假仓根目录。

    Returns:
        已完成的子进程对象 (取 ``returncode`` / ``stderr``)。
    """
    return subprocess.run(  # noqa: S603  argv 全是本仓常量与 tmp_path, 无 shell
        [sys.executable, "-m", GATE_MODULE, "--root", str(fake)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=300, cwd=str(SKILL_ROOT),  # cwd 给真仓: 门禁模块要从真仓 import
        env={**os.environ, "PYTHONIOENCODING": "utf-8"}, check=False,
    )


class TestEvalReportAssetsIsNotVacuous:
    """第十道门禁: 跑批报告资产与 HEAD 不一致必须判红, 干净仓必须判绿。"""

    def test_clean_repo_is_green(self):
        """对照: 已提交且未再改动的假仓必须 exit 0。

        没有这条对照, 下面几条的 ``!= 0`` 可能只是"git diff 根本没跑起来" ——
        门禁恒红与门禁恒绿在这条断言上无法区分。
        """
        with tempfile.TemporaryDirectory() as tmp:  # 对照: 干净仓必须绿 (证明红绿可区分)
            fake = build_committed_repo(Path(tmp))
            proc = run_gate(fake)
        assert proc.returncode == 0, (
            f"干净假仓必须 exit 0, 实得 {proc.returncode}\nstderr: {proc.stderr[-400:]}"
        )

    def test_rerun_timestamp_only_change_is_rejected(self):
        """反证: 只刷新了「生成时间」一行 (make evals-all 的日常产物) 必须判红。"""
        with tempfile.TemporaryDirectory() as tmp:  # 只改时间戳: 这是跑批留下的最常见脏法
            fake = build_committed_repo(Path(tmp))
            report = fake / "evals" / "demo" / "REPORT.md"
            report.write_text(_REPORT_BODY.replace("22:00:00", "23:30:00"), encoding="utf-8")  # 只动时间戳
            proc = run_gate(fake)
        assert proc.returncode != 0, (
            f"跑批刷新了报告却判绿 = 门禁空转, 实得 exit={proc.returncode}\nstderr: {proc.stderr[-400:]}"
        )
        assert "REPORT.md" in proc.stderr, f"必须点名这个报告文件: {proc.stderr[-400:]}"

    def test_substantive_metric_regression_is_rejected(self):
        """反证: 指标真的掉了 (metascore 1.0 -> 0.8) 必须判红 —— 这是本门禁的**核心**。

        时间戳那种最好分辨 (人 ``git diff`` 一眼看到), 指标回归才是危险形态: 报告
        依然"读起来正常", 但入库那份已不再描述当前代码的行为。
        """
        with tempfile.TemporaryDirectory() as tmp:  # 指标真掉了: 人 git diff 看不出来的那一类
            fake = build_committed_repo(Path(tmp))
            report = fake / "evals" / "demo" / "REPORT.md"
            report.write_text(_REPORT_BODY.replace("metascore: 1.0000", "metascore: 0.8000"), encoding="utf-8")
            proc = run_gate(fake)
        assert proc.returncode != 0, (
            f"指标回归却判绿 = 本门禁最该抓的形态没抓到, 实得 exit={proc.returncode}"
        )
        assert "实质回归" in proc.stderr, f"理由里必须提示区分时间戳与实质回归: {proc.stderr[-400:]}"

    def test_untracked_report_is_out_of_this_gate(self):
        """边界: **未跟踪**的 REPORT.md 不由本门禁报 (那道归 TestGitTrackingCoverage)。

        刻意钉住这条边界: 门禁若把未跟踪文件也收进来, 两道门会重叠, 整改者就得
        同时改两处。少报的那一侧由另一道门兜住, 这是设计, 不是漏洞。
        """
        with tempfile.TemporaryDirectory() as tmp:  # 边界: 新报告不 add, 留给另一道门
            fake = build_committed_repo(Path(tmp))
            (fake / "evals" / "fresh").mkdir()
            (fake / "evals" / "fresh" / "REPORT.md").write_text(_REPORT_BODY, encoding="utf-8")  # 不 add
            proc = run_gate(fake)
        assert proc.returncode == 0, (
            f"未跟踪报告不属本门禁范围, 实得 exit={proc.returncode}\nstderr: {proc.stderr[-400:]}"
        )

    def test_no_tracked_report_is_red(self):
        """零扫描面必须判红 (fail-closed): 一个被跟踪的 REPORT.md 都没有时不得报绿。"""
        with tempfile.TemporaryDirectory() as tmp:  # fail-closed 那一面: 一个 REPORT.md 都没有
            fake = build_committed_repo(Path(tmp), with_report=False)
            proc = run_gate(fake)
        assert proc.returncode != 0, (
            f"扫描面为空却判绿 = 零输入的假绿, 实得 exit={proc.returncode}\nstderr: {proc.stderr[-400:]}"
        )
        assert "扫描面为空" in proc.stderr, f"理由必须点名是扫描面为空: {proc.stderr[-400:]}"

    def test_degenerate_gate_would_pass_the_wiring_checks(self):
        """P0-C 的可执行证据: 把 ``scan`` 改成恒返 ``[]``, 接线级检查**照样全绿**。

        这条是本文件存在的理由。判据级测试必须能区分"门禁在判"与"门禁只是接上了":
        造一份同形变异门禁 (判据退化成 ``return []``), 跑同一个脏仓, 要求它 exit 0 ——
        若它红了, 说明本仓还有别的检查能兜住, 本文件的必要性就要重估; 它绿了,
        就坐实了"只有本文件能看见这件事", 上面五条才是这道门唯一的牙齿。
        """
        with tempfile.TemporaryDirectory() as tmp:  # 同一个脏仓上并列跑真门禁与变异件
            fake = build_committed_repo(Path(tmp))
            report = fake / "evals" / "demo" / "REPORT.md"
            report.write_text(_REPORT_BODY.replace("metascore: 1.0000", "metascore: 0.8000"),
                              encoding="utf-8")  # 同一个脏仓: 指标回归
            mutant = self._mutant_gate(tmp)  # 判据退化的同形变异件
            proc = subprocess.run(  # noqa: S603  argv 全是本仓常量与 tmp_path, 无 shell
                [sys.executable, str(mutant), "--root", str(fake)],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=300, env={**os.environ, "PYTHONIOENCODING": "utf-8"}, check=False,
            )
            # 同一脏仓上真门禁必须红 (否则下面那个"变异件绿"就没有对照意义)
            real = run_gate(fake)
        assert real.returncode != 0, f"真门禁在同一脏仓上必须判红, 实得 {real.returncode}"
        assert proc.returncode == 0, (
            f"判据退化的变异件本该 exit 0 (这正是 P0-C: 接线级检查看不出问题); "
            f"实得 {proc.returncode} —— 若它红了, 说明本文件必要性需重估"
        )

    @staticmethod
    def _mutant_gate(tmp: str) -> Path:
        """造一份判据退化的同形变异门禁 (``scan`` 恒返空列表)。

        Args:
            tmp: 临时目录。

        Returns:
            变异件路径 (可直接 ``python <path> --root <repo>`` 运行)。
        """
        source = (SKILL_ROOT / "ops" / "audit" / "verify_eval_report_assets.py").read_text(encoding="utf-8")
        marker = "def scan(root: Path) -> list[str]:"  # 判据函数的唯一定义处
        head, sep, _tail = source.partition(marker)  # 只切判据函数那一段: 其余原样, 测的仍是真门禁
        assert sep, "门禁源码里找不到 scan 的定义 —— 同形变异造不出来, 本文件的证据链断了"
        degenerate = (  # 同签名、同返回类型, 但恒返空: 正是 P0-C 记录的那种退化
            'def scan(root: Path) -> list[str]:\n'
            '    """变异件: 判据退化成恒返空列表 (P0-C 记录的真实退化形态)。"""\n'
            '    return []\n'
        )
        mutant = Path(tmp) / "mutant_gate.py"
        mutant.write_text(head + degenerate, encoding="utf-8")  # 只替判据, 其余原样
        return mutant
