# -*- coding: utf-8 -*-
"""code_fingerprint 的**删除方向**回归: 删掉受跟踪文件必须被门禁报出来。

守的是一处已修的真 fail-open (2026-10-06): ``_walk_py`` 原本直接转手
``scan_roots.iter_py_files`` —— 那是**文件系统遍历**, 于是被删除的文件根本不会
被产出, ``removed`` 计数在结构上恒为 0, 紧随其后的 ``os.path.exists`` 分支只在
「遍历后并发删除」时才可能命中, 对真正的删除是死代码。

实测后果: 删掉 4 个受跟踪 .py 时门禁照样打印 ``removed=0``, 退出码只看
changed/removed/broken 三项 → **删文件不红**。这正是铁律 5「禁 fail-open」要挡的
那一类: 门禁显示通过, 而它本该拦下的事发生了。

本件在**临时 git 仓**里造最小场景 (一个 .py, 提交, 删除, 跑门禁), 不碰工作区。
"""
from __future__ import annotations

# 标准库: pathlib 锚路径 / shutil 复制被测门禁 / subprocess 跑 git 与门禁 / tempfile 由 fixture 提供
import os
import shutil
import subprocess
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[3]   # 仓根: 本件在 test/unit/meta/ 下三级
GATE = SKILL_ROOT / "ops" / "audit" / "code_fingerprint.py"  # 被测门禁本体


def _git(repo: Path, *args: str) -> None:
    """在临时仓里跑一条 git 命令 (固定 argv; 只用于搭最小场景)。

    Args:
        repo: 临时仓根 (作为 cwd)。
        *args: git 子命令与参数。

    Raises:
        AssertionError: 该命令非零退出 (场景搭不起来就不该继续断言门禁行为)。
    """
    proc = subprocess.run(  # noqa: S603 — 固定 argv, 无 shell, 参数不经外部输入
        ["git", *args], cwd=str(repo), capture_output=True, text=True,
    )
    assert proc.returncode == 0, f"git {' '.join(args)} 失败: {proc.stderr}"


def _install_gate(repo: Path) -> Path:
    """把被测门禁**原样**装进临时仓的 ops/audit/, 使它的 REPO 指向该仓。

    为什么必须装进去而不是只改 cwd: 门禁的 ``REPO`` 是模块导入时由
    ``Path(__file__).resolve().parents[2]`` 算出的, 与进程 cwd 无关 —— 只改 cwd
    的话它仍然指着真仓, 本件就退化成「在真仓上跑断言」, 完全测不到临时场景。
    连同 ``scan_roots.py`` 一起复制是因为门禁对它做同目录裸名导入。

    Args:
        repo: 临时仓根。

    Returns:
        临时仓内那份门禁脚本的路径 (用它跑 check)。
    """
    target = repo / "ops" / "audit"  # 门禁在仓内的相对位置: REPO 由 parents[2] 反推, 层级必须对上
    target.mkdir(parents=True, exist_ok=True)  # exist_ok: 同一临时仓可能已装过一次
    for name in ("code_fingerprint.py", "scan_roots.py"):  # scan_roots 是它的同目录裸名依赖, 缺了整个门禁 import 就崩
        shutil.copy2(GATE.parent / name, target / name)  # 逐字复制: 测的是真门禁
    return target / "code_fingerprint.py"  # 返回装好后的入口路径, 供调用方直接跑


def _run_gate(gate: Path, repo: Path) -> subprocess.CompletedProcess:
    """在临时仓里跑一次门禁 check, 返回其 CompletedProcess。

    Args:
        gate: 临时仓内的门禁脚本路径。
        repo: 临时仓根 (作为 cwd)。

    Returns:
        含 returncode / stdout / stderr 的 CompletedProcess。
    """
    return subprocess.run(  # noqa: S603 — 固定 argv
        [sys.executable, str(gate), "check"], cwd=str(repo),
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180,
        # 临时仓按设计只有一两个 .py, 必须显式压低门禁的扫描面下限: 负对照闸
        # (scan_roots) 的默认下限是 100 (真仓 326), 不声明就会被「扫描面异常稀薄」
        # 判红 —— 那是关于**这个临时仓**的如实告警, 与本件要测的删除/新增检出无关。
        env={**os.environ, "ASTRO_BEST_MIN_SCAN_FILES": "1"},
    )


def _make_mini_repo(tmp_path: Path) -> Path:
    """造一个只含一个 .py 的临时 git 仓并提交 (于是该 .py 进了 HEAD)。

    Args:
        tmp_path: pytest 提供的临时目录。

    Returns:
        临时仓根路径。
    """
    repo = tmp_path / "mini"  # 临时仓根: 不复用真仓路径, 免得门禁读到本仓的真实文件
    repo.mkdir()  # 建目录 (parents 不必: tmp_path 已存在)
    _git(repo, "init", "-q")                                # 独立仓: 不依赖本仓历史
    _git(repo, "config", "user.email", "t@example.invalid")  # 提交要身份, 否则 git 拒绝
    _git(repo, "config", "user.name", "T")                  # 同上
    (repo / "mod.py").write_text("def f():\n    return 1\n", encoding="utf-8")  # 被测的那个 .py: 内容与门禁判定无关, 只要能解析即可
    _git(repo, "add", "mod.py")                             # 暂存后才有可提交的树
    _git(repo, "commit", "-q", "-m", "base")                # 提交: HEAD 里从此有 mod.py
    return repo  # 返回仓根供各用例继续装门禁/删文件


def test_deleted_tracked_file_is_reported(tmp_path: Path):
    """删掉 HEAD 里的受跟踪文件 → ``removed>=1`` 且退出码非 0。"""
    repo = _make_mini_repo(tmp_path)  # 先造出「HEAD 里有 mod.py」的场景
    gate = _install_gate(repo)          # 门禁装进临时仓, REPO 才会指向它
    (repo / "mod.py").unlink()          # 只删文件不 commit: 制造「基线有、工作区无」
    proc = _run_gate(gate, repo)  # 跑门禁 check: 被测行为全在这一次子进程里
    out = proc.stdout  # 读 stdout: 五行计数与分类清单都在标准输出
    assert "removed=1" in out, (  # 关键断言: 删除要被计数, 而不是只让 compared 悄悄减一
        f"删掉受跟踪 .py 后 removed 仍为 0 —— 删除方向又是空转: {out[:400]}")
    assert proc.returncode != 0, "删了受跟踪文件却 exit 0 = 门禁对该事实完全无感"


def test_intact_repo_is_not_flagged(tmp_path: Path):
    """反向对照: 文件都在且没改动时, removed=0 / code-changed=0 / exit 0。"""
    repo = _make_mini_repo(tmp_path)  # 反向对照的起点: 同样先造完整场景
    gate = _install_gate(repo)  # 装门禁 (不装则 REPO 指着真仓, 这条就成空转)
    proc = _run_gate(gate, repo)  # 完好态跑一次
    out = proc.stdout  # 读输出比对各计数
    assert "removed=0" in out, f"完好仓被误报删除: {out[:400]}"        # 防「改成恒非零」那种假修
    assert "code-changed=0" in out, f"完好仓被误报代码改动: {out[:400]}"
    assert proc.returncode == 0, f"完好仓不该非零退出: {out[:400]}"


def test_deleted_non_python_file_is_out_of_scope(tmp_path: Path):
    """删非 .py 文件不属本门禁职责 (指纹只比 .py), 不应因此变红。"""
    repo = _make_mini_repo(tmp_path)  # 先造完整场景, 再加一个非 .py 文件
    gate = _install_gate(repo)  # 写一个会被删的非 .py 文件
    (repo / "notes.md").write_text("x\n", encoding="utf-8")
    _git(repo, "add", "notes.md")        # 先提交, 使它在 HEAD 里
    _git(repo, "commit", "-q", "-m", "notes")   # 提交后才算「受跟踪且被删」
    (repo / "notes.md").unlink()         # 删掉: 指纹门禁按设计不管非 .py
    proc = _run_gate(gate, repo)
    assert "removed=0" in proc.stdout, (
        f"非 .py 的删除被算进 removed —— 覆盖面被无意放大: {proc.stdout[:400]}")  # 新文件必须落在工作区, HEAD 里还没有它


def test_new_file_is_reported_as_untracked(tmp_path: Path):
    """新增未提交 .py 仍须落在 new-untracked (改枚举方式后的反向回归)。

    修删除方向时曾把遍历源从「工作区」换成「HEAD 清单」, 那一步会让
    ``new-untracked`` 恒为 0 —— 即「新写了 .py 但还没提交」彻底看不见。
    这条守住反向那一半。
    """
    repo = _make_mini_repo(tmp_path)
    gate = _install_gate(repo)
    (repo / "fresh.py").write_text("def g():\n    return 2\n", encoding="utf-8")
    proc = _run_gate(gate, repo)
    # 不断言 new-untracked=1: 装进门禁的两份 .py 本身也是未跟踪的新文件, 计数
    # 必然大于 1。只断言两件真正要守的事 —— 计数非零, 且新增文件被点名。
    assert "new-untracked=0" not in proc.stdout, (
        f"新增未提交 .py 之后 new-untracked 仍为 0: {proc.stdout[:400]}")
    assert "fresh.py" in proc.stdout, f"报告里应点名新增文件: {proc.stdout[:400]}"
