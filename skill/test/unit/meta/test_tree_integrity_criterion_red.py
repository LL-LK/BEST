# -*- coding: utf-8 -*-
"""``verify_tree_integrity`` 的**判据级**红测试 (D5-23 补齐, 2026-10-05)。

起因: 判据审计实测八道硬门禁里 7 道都有"注入缺陷 → 断言退出码非零"的判据级红
测试, **唯独缺这一道**。而这道恰恰最需要它 —— 树门禁是本仓宣称的"文件树 SSOT
守门人", 它的判据一旦退化 (例如把 :func:`verify_tree_integrity.main` 改成永远
``return 0``), ``make verify`` 恒绿、``make check`` 恒绿、全仓测试无一有声, 而被废
的代码仍留在盘上。接线级断言 (``TestHardGatesRunGreen`` 那种"脚本在盘上且 exit 0")
挡不住任何一种退化, 因为把它改成 ``return 0`` 一样 exit 0。

取证纪律沿用 ``test_gate_criterion_red.py``: **每条"必须判红"都配一道干净对照**。
少了对照, "门禁恒红"与"门禁恒绿"同样能满足 ``!= 0``, 证据等于零。

假仓造法与门禁的仓根定位耦合: 树门禁用
``Path(__file__).resolve().parent.parent`` 定位仓根且**没有** root 参数, 所以把脚本
复制到 ``假仓/ops/`` 下, 它的仓根就自动变成假仓。**真仓自始至终不被触碰** ——
这正是本文件必须存在的原因之一: 树门禁的 ``--write`` 会**改写 README**, 若在真仓
上做这类实验就会污染 SSOT。``--write`` 在这里只对 ``tmp_path`` 下的假仓执行。

已知盲区 (不在本文件断言, 免得把缺陷钉成契约): 树门禁把 ``docs/`` 列为不透明目录
(``OPAQUE_DIRS``), 因此 ``docs/`` 内文件的增删改名一律放行 —— 判据审计 D5-22 记的
就是这一条, 属另一条待办 (改动会牵动 README 树清单的口径, 不在本轮范围)。
"""
from __future__ import annotations

# 标准库: os 传给子进程的环境 / shutil 复制门禁脚本 / subprocess 跑真门禁 /
# sys 解释器 / pathlib 路径
import os
import shutil
import subprocess
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[3]  # 仓根: 本文件在 test/unit/meta/, 上溯三级
GATE_SRC = SKILL_ROOT / "ops" / "verify_tree_integrity.py"  # 门禁真身: 树门禁在 ops/ 根下, 不在 ops/audit/


def build_baselined_repo(tmp_path: Path) -> Path:
    """造假仓、复制门禁、建一棵最小文件树, 并用 ``--write`` 生成 README 树基线。

    ``--write`` 必须在注入缺陷**之前**跑: 树门禁判的是"实际树 vs 清单", 没有基线
    时它对任何结构都判 FAIL, 那样红绿都说明不了判据, 只说明基线不存在。

    Args:
        tmp_path: pytest 提供的临时目录。

    Returns:
        已建好基线的假仓根目录。
    """
    fake = tmp_path / "fakerepo"
    (fake / "ops").mkdir(parents=True)  # 门禁落位: parents[1] 即假仓根
    shutil.copy(GATE_SRC, fake / "ops" / GATE_SRC.name)  # 原样复制: 测的是真门禁, 不是复刻品
    (fake / "README.md").write_text("# 假仓\n\n最小 README: 树块由 --write 生成。\n", encoding="utf-8")
    (fake / "src").mkdir()
    (fake / "src" / "keep.py").write_text("VALUE = 1\n", encoding="utf-8")  # 基线里的一项: 供删除实验用
    run_in(fake, ["--write"])  # 建基线: 只写 tmp_path 下的假仓 README, 真仓不被触碰
    return fake


def run_in(fake: Path, args: list[str]) -> subprocess.CompletedProcess:
    """在假仓里以子进程跑树门禁。

    Args:
        fake: 假仓根。
        args: 传给门禁的命令行参数 (如 ``["--write"]``)。

    Returns:
        已完成的子进程对象 (取 ``returncode`` / ``stdout``)。
    """
    return subprocess.run(  # noqa: S603  argv 全是本仓常量, 无 shell
        [sys.executable, str(fake / "ops" / GATE_SRC.name), *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=300, cwd=str(fake),  # cwd 指向假仓: --write 写的是假仓 README
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},  # 只覆盖编码, 其余环境原样继承
        check=False,
    )


class TestTreeIntegrityIsNotVacuous:
    """树门禁: 未授权结构变更必须判红, 干净的树必须判绿。"""

    def test_baseline_repo_is_green(self):
        """对照: 刚 ``--write`` 建好基线的假仓必须 exit 0。

        没有这条对照, 下面两条的 ``!= 0`` 可能只是"基线根本没建成" —— 门禁恒红
        与门禁恒绿在这条断言上无法区分。
        """
        import tempfile  # noqa: PLC0415  仅本用例要现造假仓, 不进模块级依赖

        with tempfile.TemporaryDirectory() as tmp:
            fake = build_baselined_repo(Path(tmp))
            proc = run_in(fake, [])
        assert proc.returncode == 0, f"基线假仓必须 exit 0: {proc.stdout[-400:]}{proc.stderr[-400:]}"

    def test_unauthorized_new_file_is_rejected(self):
        """反证: 清单外的文件被新增 (未授权结构变更) 必须判红。"""
        import tempfile  # noqa: PLC0415  仅本用例要现造假仓

        with tempfile.TemporaryDirectory() as tmp:
            fake = build_baselined_repo(Path(tmp))
            (fake / "src" / "added.py").write_text("EXTRA = 2\n", encoding="utf-8")  # 清单外新增
            proc = run_in(fake, [])
        assert proc.returncode != 0, (
            f"清单外新增文件必须判红, 实得 exit={proc.returncode}\nstdout: {proc.stdout[-400:]}"
        )
        assert "added.py" in proc.stdout, (
            f"必须点名这个新增文件, 否则红的原因与它无关: {proc.stdout[-400:]}"
        )

    def test_deleted_registered_file_is_rejected(self):
        """反证: 清单里登记过的文件被删除必须判红 (另一条报法, 同样要覆盖)。"""
        import tempfile  # noqa: PLC0415  仅本用例要现造假仓

        with tempfile.TemporaryDirectory() as tmp:
            fake = build_baselined_repo(Path(tmp))
            (fake / "src" / "keep.py").unlink()  # 清单有、磁盘无 = 被删/被移
            proc = run_in(fake, [])
        assert proc.returncode != 0, (
            f"登记过的文件被删必须判红, 实得 exit={proc.returncode}\nstdout: {proc.stdout[-400:]}"
        )
        assert "keep.py" in proc.stdout, (
            f"必须点名被删的文件: {proc.stdout[-400:]}"
        )

    def test_missing_tree_block_is_rejected(self):
        """反证: README 的树块被整段删掉必须判红 (不得 fail-open 成"跳过校验")。"""
        import tempfile  # noqa: PLC0415  仅本用例要现造假仓

        with tempfile.TemporaryDirectory() as tmp:
            fake = build_baselined_repo(Path(tmp))
            readme = fake / "README.md"
            text = readme.read_text(encoding="utf-8")
            keep = [ln for ln in text.splitlines() if "TREE:" not in ln]  # 只留块外文字
            readme.write_text("\n".join(keep) + "\n", encoding="utf-8")  # 块被整段抹掉
            proc = run_in(fake, [])
        assert proc.returncode != 0, (
            f"树块缺失必须判红 (fail-closed), 实得 exit={proc.returncode}\nstdout: {proc.stdout[-400:]}"
        )
