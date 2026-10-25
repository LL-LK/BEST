# -*- coding: utf-8 -*-
"""门禁负对照闸的判据级红测试 —— 「扫描面为空必须判红」这条纪律本身的可执行证据。

2026-10-07 的实测事故: 把门禁的扫描面清空后, 九道硬门禁里**七道 exit 0**。
当时的「绿灯」只蕴含「没有触发任何条件」, 不蕴含「检查过且没问题」——
cwd 不对 / ``parents[2]`` 上溯到意外位置 / 某次重构搬走源码 / ``.gitignore`` 规则误伤,
任何一条都能让七道门禁齐刷刷报绿而**一个文件都没检查**。其中
``verify_no_version_keys`` 最误导: 0 个文件时它照样打印「**铁律 1 通过**」。

修法是给每道扫描面型门禁加一条负对照 (见 :func:`scan_roots.require_nonempty_scan` /
:func:`scan_roots.require_nonempty_yaml_scan`)。但**加了闸不等于闸有牙** ——
本件就是那道牙: 造一个扫描面为空 (或异常稀薄) 的仓, 要求门禁**真的**判红。

方法学上有三条硬纪律, 全部来自本仓上一轮审计的实测教训
(``temp/vfy/CONSTRUCTION-TRAPS.md`` §5/§8, 已随审计归档):
  1. **必须跑假仓里的副本, 不能跑真仓脚本**。门禁用 ``parents[2]`` 定位仓根,
     而 ``__file__`` 由解释器按**真实路径**解析 —— 本件第一版就踩了这个坑:
     用 ``cwd=假仓`` 去跑真仓脚本, 结果它照旧扫真仓 (自证信号: "空"仓里报出
     ``from-import 组核实: 389``)。正解是把脚本**逐字节复制进假仓**再跑。
  2. 假仓只放**依赖闭包**而不是整目录: 整目录复制会让副本自身的违规把干净对照组带红。
  3. 每条用例都要有**阳性对照** —— 扫描面充足时闸不得触发, 否则"永远判红"也能让本件全过。
"""
from __future__ import annotations

import os  # 标准库: 给子进程注入 PYTHONPATH
import shutil  # 标准库: 假仓里铺门禁副本
import subprocess  # 标准库: 以子进程真跑门禁脚本 (门禁是 __main__ 形态的脚本)
import sys  # 标准库: 解释器路径与 sys.path 锚定
from pathlib import Path  # 标准库: 路径拼装

import pytest  # 参数化与断言

SKILL_ROOT = Path(__file__).resolve().parents[3]  # 仓根: 本件在 test/unit/meta/ 下三级
AUDIT_DIR = SKILL_ROOT / "ops" / "audit"  # 门禁目录: 假仓要按同样的相对布局铺
if str(SKILL_ROOT) not in sys.path:  # 幂等: 让本件能 import conftest 的共享求解器
    sys.path.insert(0, str(SKILL_ROOT))

# 会因扫描面为空而**应该**判红的门禁 -> 闸的覆盖面类型。
# "py" = 走 scan_roots 的 .py 面; "yaml" = YAML 面; "own" = 覆盖面自成一体的 (import 图按可导入层走)。
NEGCTRL_GATES = [  # 九道里**应当**有负对照闸的七道; 另两道 (crossrefs/evidence_anchors) 本就 fail-closed, 不在表内
    ("count_code_lines", "py"),  # 超限登记簿判据: 零输入时曾打印"登记簿缺失"却不判红
    ("comment_audit", "py"),  # 十五类 totals: 零输入时全 0 -> exit 0
    ("code_fingerprint", "py"),  # 代码零改动判据: 零输入时 compared=0 -> exit 0
    ("verify_doc_consistency", "py"),  # 曾打印"扫描 0 个 .py"却仍 exit 0
    ("verify_counting_claims", "py"),  # 曾打印"0 条不符"却仍 exit 0
    ("verify_import_graph", "own"),  # 覆盖面自成一体的: 曾打印"核实: 0"却仍 exit 0
    ("verify_no_version_keys", "yaml"),  # 最误导的一道: 零输入时打印「铁律 1 通过」
]

# 填充扫描面用的合规 .py 个数: 必须高过闸的下限 (100) 又不至于让用例变慢。
PAYLOAD_FULL = 130  # 130: 高于下限 100 留出余量, 又远低于全仓 326 以免拖慢阳性对照


def _write_payload_py(target: Path, index: int) -> None:
    """写一个**注释规范达标**的占位 .py (负对照用例的扫描面填充物)。

    刻意带模块头 docstring 与行尾注释: 空文件会让 ``comment_audit`` 的 docstring 类
    判据报违规, 把"负对照闸是否触发"与"注释是否合规"两件事混进同一个失败信号里,
    那样就分不清是谁在判红。

    Args:
        target: 目标路径。
        index: 序号 (写进 docstring 与常量名, 避免多个填充物同名遮蔽)。
    """
    target.write_text(  # 一次性写出完整三行: 模块头 docstring + 带行尾注释的非平凡语句
        "# -*- coding: utf-8 -*-\n"
        f'"""占位模块 {index} —— 负对照闸判据级测试的扫描面填充物。"""\n'
        "\n"
        f"VALUE_{index} = {index}  # 常量: 非平凡语句必须带行尾注释 (逐行对照率判据)\n",
        encoding="utf-8",
    )


def _build_fake_repo(tmp_path: Path, gate: str, payload_py: int, payload_yaml: int) -> Path:
    """铺一个扫描面恰有 ``payload_py`` 个 .py / ``payload_yaml`` 个 YAML 的假仓。

    两处关键设计, 每一处都对应一个把本件第一版打红的坑:

    1. **只把入口脚本复制进去, 且刻意不带 ``.py`` 后缀**。带后缀的话门禁自己就进了
       ``iter_py_files`` 的扫描面, "扫描面为空"这个前提直接不成立。不带后缀则它是
       唯一那个"看得见跑不起来但不计入门禁面"的脚本。
    2. **依赖闭包不复制进假仓, 改用 ``PYTHONPATH`` 指向真仓的 ``ops/audit``**。
       第一版把闭包也复制成无后缀文件, 结果 ``from scan_roots import ...`` 直接
       ``ModuleNotFoundError`` —— Python 按 import 机制找的是 ``scan_roots.py``。
       用 PYTHONPATH 既让导入成立, 又保证假仓扫描面真的是空的 (闭包留在真仓不入面)。

    ``verify_import_graph`` 另有要求: 它按 ``IMPORTABLE_BASES`` 走而不是全仓黑名单,
    所以假仓必须铺出 ``src/`` 等可导入层, 否则"两遍都空"会被它的负对照闸判红 ——
    那是对的, 但会让阳性对照那一半失去意义。

    Args:
        tmp_path: pytest 提供的临时目录。
        gate: 被测门禁名。
        payload_py: 扫描面里要凑的 .py 个数。
        payload_yaml: 扫描面里要凑的 YAML 个数。

    Returns:
        假仓根目录。
    """
    root = tmp_path / "fake_repo"
    audit = root / "ops" / "audit"
    audit.mkdir(parents=True)
    shutil.copy2(AUDIT_DIR / f"{gate}.py", audit / gate)  # 去后缀: 门禁自身不进扫描面
    for layer in ("src", "evals", "ops", "test"):  # 铺可导入层: import 图门禁按层遍历, 空层会让它判红
        (root / layer).mkdir(parents=True, exist_ok=True)
    for index in range(payload_py):  # 逐个写 .py 填充物: 数量决定扫描面有多大
        _write_payload_py(root / "src" / f"payload_{index}.py", index)  # 落在 src/: 可导入层之内
    for index in range(payload_yaml):  # 逐个写 YAML: 只有 YAML 面门禁 (verify_no_version_keys) 看它
        (root / "src" / f"payload_{index}.yaml").write_text(f"name_{index}: value\n", encoding="utf-8")  # 最小合法 YAML
    _git_init(root)  # code_fingerprint 走真实 git 对账: 非 git 仓会让它因别的原因炸掉, 掩盖负对照信号
    return root


def _git_init(root: Path) -> None:
    """把假仓变成一个带一次空提交的**真** git 仓。

    上一轮审计踩过两次假阳性 (非 git 副本让依赖 git 的判据恒红), 本件沿用那条纪律:
    涉及 git 的门禁必须在带 ``.git`` 的仓里跑。空提交让 HEAD 存在, ``_git_show``
    对"未跟踪文件"返回 None 的分支才是门禁的正常路径。
    """
    for args in (  # 两步: 先 init 再造一个空提交, 让 HEAD 存在
        ["init", "-q"],  # 就地初始化: 假仓自己就是仓根, 不需要 clone
        ["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "base"],
    ):
        subprocess.run(  # noqa: S603  argv 全为常量, 无外部输入, 不经 shell
            ["git", *args],
            cwd=str(root),
            capture_output=True,
            check=False,
        )


def _run_gate_in_fake_repo(gate: str, root: Path) -> subprocess.CompletedProcess:
    """在假仓里真跑一次该门禁 (跑的是**假仓里的副本**, 不是真仓脚本)。

    ``PYTHONPATH`` 指向真仓 ``ops/audit``: 让门禁的同目录裸名导入 (``scan_roots`` /
    ``line_scope`` / ``count_code_lines``) 成立, 同时保证它们**留在真仓**因而不会
    被算进假仓的扫描面 —— 见 :func:`_build_fake_repo` 的设计说明第 2 条。

    Args:
        gate: 门禁名 (不带 ``.py``)。
        root: 假仓根。

    Returns:
        已完成的子进程对象; 调用方据 ``returncode`` 与输出判红绿。
    """
    entry = root / "ops" / "audit" / gate  # 副本刻意不带 .py 后缀: 既是"门禁自身不进扫描面"的需要, 也保证按脚本方式执行
    return subprocess.run(
        [sys.executable, str(entry)],  # 跑副本: 真仓脚本的 __file__ 会把 ROOT 拉回真仓 (见模块 docstring 第 1 条)
        cwd=str(root),
        env={**os.environ, "PYTHONPATH": str(AUDIT_DIR)},  # 闭包留在真仓: 导入成立且不进假仓扫描面
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
    )


class TestNegativeControlFiresOnEmptyScanSurface:
    """负对照: 扫描面为空时门禁必须判红 —— 这是它们被接进 ``make audit`` 的前提。"""

    @pytest.mark.parametrize("gate,surface", NEGCTRL_GATES, ids=[g for g, _ in NEGCTRL_GATES])
    def test_empty_scan_surface_must_be_red(self, tmp_path, gate, surface):
        """扫描面 0 个 .py / 0 个 YAML 时必须非零退出。

        这是本件最核心的一条: 若某道门禁在这里 exit 0, 说明它的负对照闸没接上, 或者
        接在了另一张扫描面上 —— 两种情况都意味着"绿灯不蕴含检查过"又回来了。
        """
        root = _build_fake_repo(tmp_path, gate, payload_py=0, payload_yaml=0)  # 空扫描面: 零个 .py 也零个 YAML
        result = _run_gate_in_fake_repo(gate, root)  # 真跑假仓里的副本
        assert result.returncode != 0, (
            f"{gate} 在空扫描面上 exit 0 —— 负对照闸未生效 (surface={surface})。"
            f" stdout 尾部: {result.stdout[-300:]!r} stderr: {result.stderr[-300:]!r}"
        )

    @pytest.mark.parametrize("gate,surface", NEGCTRL_GATES, ids=[g for g, _ in NEGCTRL_GATES])
    def test_empty_scan_surface_must_say_why(self, tmp_path, gate, surface):
        """判红时必须写明理由 —— 静默判红与静默放行同样不可排查。"""
        root = _build_fake_repo(tmp_path, gate, payload_py=0, payload_yaml=0)  # 同上: 空扫描面
        result = _run_gate_in_fake_repo(gate, root)  # 真跑
        assert "负对照" in (result.stdout + result.stderr), (  # stdout+stderr 都看: 闸的判红理由走 stderr
            f"{gate} 判红了但没说为什么: 负对照闸的判红理由必须落到输出上, 否则"
            f" 门禁红只能靠猜。 尾部: {(result.stdout + result.stderr)[-300:]!r}"
        )


class TestNegativeControlDoesNotFireOnFullSurface:
    """阳性对照: 扫描面充足时闸**不得**触发 —— 否则这是一道永远红的废闸。

    没有这一组, 上面的负对照可以用"无条件 return 1"这种最坏实现作弊通过。
    断的是**闸没触发**而不是"门禁必须全绿": 假仓里的门禁可能因别的判据红
    (缺治理文档等), 那与本用例的命题无关。
    """

    @pytest.mark.parametrize("gate,surface", NEGCTRL_GATES, ids=[g for g, _ in NEGCTRL_GATES])
    def test_full_scan_surface_must_not_trip_negative_control(self, tmp_path, gate, surface):
        """扫描面充足时不得出现负对照判红。"""
        root = _build_fake_repo(tmp_path, gate, payload_py=PAYLOAD_FULL, payload_yaml=PAYLOAD_FULL)  # 扫描面充足
        result = _run_gate_in_fake_repo(gate, root)  # 真跑
        combined = result.stdout + result.stderr  # 闸的判红理由走 stderr, 两边都要看
        assert "负对照" not in combined, (
            f"{gate} 在 {PAYLOAD_FULL} 个文件的扫描面上仍触发了负对照闸 —— 门槛设错了。"
            f" 尾部: {combined[-300:]!r}"
        )


class TestNegativeControlThreshold:
    """门槛本身的边界: 太松漏掉塌面, 太紧误伤正常删文件。"""

    def test_below_threshold_is_red_above_is_green(self):
        """直接打闸的函数: 低于下限判红、达到下限判绿。"""
        sys.path.insert(0, str(AUDIT_DIR))
        from scan_roots import (  # noqa: PLC0415  延迟导入: 门禁目录不在默认 sys.path 上
            MIN_EXPECTED_PY_FILES,
            require_nonempty_scan,
        )

        assert require_nonempty_scan("t", []) is False, "空扫描面必须判红"
        assert require_nonempty_scan("t", ["a.py"] * (MIN_EXPECTED_PY_FILES - 1)) is False, (
            "低于下限必须判红: 门槛的意义就是接住'扫描面塌成空/稀薄'"
        )
        assert require_nonempty_scan("t", ["a.py"] * MIN_EXPECTED_PY_FILES) is True, (
            "恰在下限必须判绿: 再紧一格就会在正常批量删文件时误报, 而误报的闸会被绕开"
        )
        assert require_nonempty_scan("t", ["a.py"] * (MIN_EXPECTED_PY_FILES + 200)) is True, (
            "正常规模的仓必须判绿"
        )

    def test_yaml_surface_has_its_own_threshold(self):
        """YAML 面门禁有独立门槛 —— 两类扫描面混用会让其中一类永远红或永远绿。"""
        sys.path.insert(0, str(AUDIT_DIR))
        from scan_roots import (  # noqa: PLC0415  同上
            MIN_EXPECTED_YAML_FILES,
            require_nonempty_yaml_scan,
        )

        assert require_nonempty_yaml_scan("t", []) is False
        assert require_nonempty_yaml_scan("t", ["a.yaml"] * (MIN_EXPECTED_YAML_FILES - 1)) is False
        assert require_nonempty_yaml_scan("t", ["a.yaml"] * MIN_EXPECTED_YAML_FILES) is True
