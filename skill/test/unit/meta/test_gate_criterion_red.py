# -*- coding: utf-8 -*-
"""门禁的**判据级**红测试: 每条硬门禁都必须有一道"它本该抓住"的题 (A6-04)。

起因 (2026-10-04 突变实验): 门禁的防退化此前只有**接线级**断言 ——
``TestHardGatesRunGreen`` 只验"脚本在盘上且 exit 0"。这种断言挡不住任何一种
真正的退化, 因为把它改成 ``return 0`` 一样 exit 0。实测把
``ops/audit/count_code_lines.py`` 改成 ``return 0`` 并提交: 1020 净行的文件
照样 exit 0、``code_fingerprint`` **不标记该文件**、全量 1374 个测试全绿,
而被废的门禁代码**仍在盘上** (``L158: return 0``)。一道门禁可以被一次提交
永久废掉, 且没有任何测试会响。

缺的是**判据级**断言: 造一个该门禁本该抓住的缺陷, 断言它 exit 非 0。
只有这样, "把 main() 改成 return 0" 才会立刻让本文件变红。

判据级覆盖的分工 (不要重复造):
  - ``comment_audit`` (Q7/Q9) -> 已有内联小样本级覆盖, 见
    ``test_audit_gate_contracts.py``;
  - ``verify_crossrefs`` 的**必读源守卫** (``require_source``) -> 同样在
    ``test_audit_gate_contracts.py::TestCrossrefsFailClosed``; 而它的**第 8 项**
    (错误码契约双向对齐) 由本文件的 ``TestCrossrefsErrorCodeContractIsNotVacuous``
    覆盖 —— 两者不是一回事, 见那个类的 docstring;
  - ``check_line_endings`` 是**报告型**工具, 恒 exit 0, 所以它的判据级测试
    只能断言 stdout (见本文件末尾的 ``TestLineEndingsIsNotVacuous``) ——
    这是唯一诚实的写法: 把报告型工具改成 exit 1 才配得上"断言非零", 那等于
    悄悄把它升级成阻断门禁, 反而违背 CLAUDE.md "报告型工具刻意不阻断" 的口径;
  - 本文件覆盖其余每一条: ``count_code_lines`` / ``verify_import_graph`` /
    ``verify_doc_consistency`` / ``verify_no_version_keys`` /
    ``verify_evidence_anchors`` (知识面那两档判据另见
    ``test_knowledge_surface_gate.py``)。

**为什么第 8 项的用例曾长期不在仓内 (2026-10-05 补记)**: 它原先只存在于
``temp/h8_gate_crossrefs_criterion.py``。``temp/`` 是 gitignored, 克隆机上跑不到,
于是"门禁修好了"与"守门禁的证据随仓库分发"是两件事 —— H8-02 把覆盖面从 0 修到
10 条, 但改判定逻辑仍无人发现。本类就是把那 5 条用例搬进版本库。

方法论: 这些门禁都用 ``Path(__file__).resolve().parents[2]`` 定位仓根, 因此
**无法**用参数把它们指向别的目录。故每条用例在 ``tmp_path`` 里现造一棵**最小
假仓**, 把门禁脚本原样复制到 ``假仓/ops/audit/`` 下 (于是它的仓根自动变成假仓),
再往假仓里注入该门禁本该抓住的缺陷, 然后以子进程跑它、断言非零退出。
真仓自始至终不被触碰 —— 突变只发生在 ``tmp_path`` 里。

每条用例都配一道**对照**: 同一棵假仓在未注入缺陷时必须 exit 0。少了对照,
"门禁恒红"与"门禁恒绿"同样能满足 ``!= 0``, 证据等于零。
"""
from __future__ import annotations

# 标准库: ast 解析门禁源码 (查退出码来源) / io 读 Makefile / os 环境 /
# re 提取 Makefile 的 audit 配方块 / shutil 建假仓 / subprocess 跑门禁 /
# sys 解释器 / pathlib 路径
import ast
import importlib
import io
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

# 第三方: pytest 提供参数化与 skip 语义
import pytest

# 共用求解器: 造假仓时只复制「被测门禁 + 它的同目录依赖」, 理由见该函数 docstring。
# 必须显式把 test/ 塞进 sys.path 而不是指望 pytest 注入 —— 本文件被
# test_no_module_skip_guards.py 在**干净子进程里裸导入**验过 (防模块级 skip 守卫
# 把导入失败吞成静默退出收集集), 那时 pytest 的路径注入不存在, 只写
# ``from conftest import`` 会 ModuleNotFoundError。
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # test/ 目录: conftest.py 在此
from conftest import audit_gate_names, gate_dependency_closure  # noqa: E402  路径注入必须在导入之前

SKILL_ROOT = Path(__file__).resolve().parents[3]  # 仓根: 本文件在 test/unit/meta/, 上溯三级
AUDIT_DIR = SKILL_ROOT / "ops" / "audit"          # 门禁脚本真身所在目录


def build_fake_repo(tmp_path: Path, gate: str) -> Path:
    """在 tmp_path 里现造一棵**最小**假仓, 只放被测门禁与它的同目录依赖。

    为什么必须造假仓而不能直接用真仓: 这些门禁都用
    ``Path(__file__).resolve().parents[2]`` 定位仓根, **没有** root 参数可传。
    把脚本复制到 ``假仓/ops/audit/`` 下, 它的 ``parents[2]`` 就正好是假仓 ——
    这是不改门禁代码就能把它的扫描范围换成临时目录的唯一办法。
    真仓不被触碰, 因此本文件不需要任何清理逻辑 (铁律 3: 临时产物只进 temp/,
    而 pytest 的 tmp_path 由框架在系统临时区回收)。

    复制**依赖闭包**而不是整个 ``ops/audit/``: 依赖同在才能 import, 但多复制一个
    门禁就等于往假仓扫描面里塞一个**与被测命题无关的 .py** —— 它的任何违规都会让
    「干净对照组」变红, 而那些用例声称测的是落位覆盖面 / 注释口径 / 版本键 / 错误码
    契约。门禁失败方向审计 (2026-10-05, N2) 实测过两个通道:

      - 通道 1: 只在被复制的 ``check_line_endends.py`` 副本末尾注入一个声明了
        ``beta_unused`` 而函数体零引用的函数, 假仓里那个干净的对照件保持无问题 ——
        ``verify_doc_consistency`` 立刻 exit 1 且只报那个副本, 于是
        ``test_clean_repo_exits_zero`` 在「被测文件毫无问题」时变红;
      - 通道 2: 把被复制的 ``scan_code_smells.py`` 换成远超 400 净行的内容。假仓没有
        ``docs/architecture/file-size-budget.md`` (登记簿), 于是**任何**超限文件
        都算「未登记超限」, ``count_code_lines`` 的对照组同样被带红。

    引爆点很近: ``comment_audit.py`` 实测 334 净行, 距 400 只剩 66 行, 按本仓注释
    密度规范一个判据增补即可吃掉。闭包怎么算见
    ``test/conftest.py::gate_dependency_closure`` (含"为什么不能手抄名单")。
    """
    fake = tmp_path / "fakerepo"
    (fake / "ops" / "audit").mkdir(parents=True)      # 门禁脚本的落位: 决定它的仓根
    for filename in gate_dependency_closure(gate):     # 被测门禁 + 递归依赖, 不多不少
        shutil.copy(AUDIT_DIR / filename, fake / "ops" / "audit" / filename)  # 原样复制: 测的是真门禁, 不是复刻品
    assert (fake / "ops" / "audit" / f"{gate}.py").is_file(), f"假仓里没有 {gate}.py"
    return fake


def run_in(fake: Path, gate: str, args: list[str]) -> subprocess.CompletedProcess:
    """在假仓里以子进程跑一条门禁, 返回其退出码与输出。

    子进程而非 import: 数条门禁是"导入即执行"的脚本体 (顶层直接
    ``raise SystemExit``), 在本进程里跑会污染 pytest 的模块表与 cwd。
    """
    return subprocess.run(
        [sys.executable, str(fake / "ops" / "audit" / f"{gate}.py"), *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=300, cwd=str(fake),  # cwd 指向假仓: 门禁按相对路径读登记簿/文档
        env={**os.environ, "PYTHONIOENCODING": "utf-8", "ASTRO_BEST_MIN_SCAN_FILES": "1"},  # 假仓故意只有两三个 .py, 显式声明下限 (见 test_gate_scan_coverage 同处注释)
    )


class TestCountCodeLinesIsNotVacuous:
    """count_code_lines: 超预算且**未登记**的 .py 必须判红 (铁律 2 + 铁律 5)。

    突变证据: 把 ``main()`` 改成 ``return 0`` 并提交, 1020 净行的文件照样
    exit 0, 全量 1374 测试全绿, 被废的门禁代码仍在盘上。
    """

    GATE = "count_code_lines"

    def test_unregistered_oversized_file_is_rejected(self, tmp_path):
        """注入一个 450 净行且未登记的 .py -> 必须非零退出。

        450 净行需要真的写出 450 行可执行代码: 判据扣掉空行/纯注释/docstring,
        只写注释是凑不出净行的 (那样反而验证不了 BUDGET 判据)。
        """
        fake = build_fake_repo(tmp_path, self.GATE)  # 造假仓: 门禁的仓根随之落到 tmp
        (fake / "src").mkdir()                          # count_code_lines 的 SCAN_DIRS 之一
        body = "".join(f"V{i} = {i} + 1\n" for i in range(450))  # 450 行真实赋值 = 450 净行
        (fake / "src" / "fat.py").write_text(body, encoding="utf-8")  # 未登记, 故必判红
        proc = run_in(fake, self.GATE, [])  # 跑真门禁 (副本), 取它的退出码
        assert proc.returncode != 0, (
            f"450 净行的未登记 .py 必须判红, 实得 exit={proc.returncode}\n"
            f"stdout: {proc.stdout[-600:]}"
        )

    def test_clean_fake_repo_exits_zero(self, tmp_path):
        """对照: 未注入缺陷的同一棵假仓必须 exit 0。

        没有这条对照, "门禁恒红"也能满足 ``!= 0`` —— 那样测的就不是判据,
        只是"它会崩"。
        """
        fake = build_fake_repo(tmp_path, self.GATE)  # 同一棵假仓, 这次不注入缺陷
        (fake / "src").mkdir()  # 扫描根必须在, 否则是"什么都没扫到"而非"干净"
        (fake / "src" / "small.py").write_text("V = 1\n", encoding="utf-8")  # 1 净行, 远低于预算
        proc = run_in(fake, self.GATE, [])  # 对照组: 门禁必须判绿
        assert proc.returncode == 0, f"干净假仓必须 exit 0: {proc.stdout[-400:]}"


class TestImportGraphIsNotVacuous:
    """verify_import_graph: 可导入层反向 import ops 层必须判红 (分层判据)。

    这道门禁的分层判据只有一条: ``src``/``rag``/``evals`` 不得 import ``ops``。
    判据级测试必须真的触发它, 否则"分层判据"只是一段没人验证过的注释。
    """

    GATE = "verify_import_graph"

    @pytest.fixture()
    def fake(self, tmp_path):
        """一棵带完整 ``src`` 包结构的假仓 (importlib 真导入需要 __init__.py)。"""
        fake = build_fake_repo(tmp_path, self.GATE)  # 造假仓
        (fake / "src").mkdir()  # 可导入层之一
        (fake / "src" / "__init__.py").write_text("", encoding="utf-8")  # 缺它 importlib 导不进 src.*
        return fake

    def test_importable_layer_importing_ops_is_rejected(self, fake):
        """``src`` 里的模块 import ``ops.*`` -> 必须非零退出。"""
        (fake / "ops" / "leaked.py").write_text("VALUE = 1\n", encoding="utf-8")  # 被引用的 ops 模块得真实存在
        (fake / "src" / "culprit.py").write_text(
            "from ops.leaked import VALUE\n", encoding="utf-8")  # 反向依赖: 可导入层碰路径调用层
        proc = run_in(fake, self.GATE, [])  # 跑门禁取退出码
        assert proc.returncode != 0, (
            f"src -> ops 的反向依赖必须判红, 实得 exit={proc.returncode}\n"
            f"stdout: {proc.stdout[-600:]}"
        )

    def test_clean_fake_repo_exits_zero(self, fake):
        """对照: 没有任何反向依赖时必须 exit 0。"""
        (fake / "src" / "clean.py").write_text("VALUE = 1\n", encoding="utf-8")  # 无 ops 引用 = 合法分层
        proc = run_in(fake, self.GATE, [])  # 对照组
        assert proc.returncode == 0, f"干净假仓必须 exit 0: {proc.stdout[-400:]}"


class TestDocConsistencyIsNotVacuous:
    """verify_doc_consistency: docstring 为形参写了用途而函数体零引用 -> 判红。

    这是 DEADPARAM 判据的全部意义 ("注释说谎")。没有判据级测试的话, 把
    ``check_dead_params`` 改成空实现同样能过全部接线级断言。
    """

    GATE = "verify_doc_consistency"

    def test_dead_param_declaration_is_rejected(self, tmp_path):
        """docstring 声称 ``unused`` 有用途, 函数体却一次都没引用它 -> 非零退出。"""
        fake = build_fake_repo(tmp_path, self.GATE)  # 造假仓
        (fake / "src").mkdir()  # 扫描根之一
        (fake / "src" / "liar.py").write_text(
            'def handler(payload, unused):\n'
            '    """处理载荷。\n'
            '    Args:\n'
            '        payload: 载荷内容。\n'
            '        unused: 用于分页游标, 必须参与下游查询。\n'
            '    """\n'
            '    return payload\n',                                          # unused 零引用 = 假声明
            encoding="utf-8",
        )
        proc = run_in(fake, self.GATE, [])  # 跑 DEADPARAM 判据
        assert proc.returncode != 0, (
            f"假用途声明 (DEADPARAM) 必须判红, 实得 exit={proc.returncode}\n"
            f"stdout: {proc.stdout[-600:]}"
        )

    def test_disclaimed_unused_param_is_not_rejected(self, tmp_path):
        """反向: 带免责措辞的诚实声明必须放过 (逼人删实话是门禁的反作用)。"""
        fake = build_fake_repo(tmp_path, self.GATE)  # 造假仓
        (fake / "src").mkdir()  # 扫描根之一
        (fake / "src" / "honest.py").write_text(
            'def handler(payload, unused):\n'
            '    """处理载荷。\n'
            '    Args:\n'
            '        payload: 载荷内容。\n'
            '        unused: 替身不使用, 只为签名对齐。\n'
            '    """\n'
            '    return payload\n',
            encoding="utf-8",
        )
        proc = run_in(fake, self.GATE, [])  # 免责措辞应让它判绿
        assert proc.returncode == 0, f"诚实声明的未用形参不得误报: {proc.stdout[-400:]}"


class TestNoVersionKeysIsNotVacuous:
    """verify_no_version_keys: 任何 YAML 出现版本键都必须判红 (铁律 1)。

    突变证据: 往 ``evals/cases/*.yaml`` (SSOT 之外的 30+ 份) 加
    ``version: 9.9.9`` -> 七道门禁全 exit 0、29 条版本专项测试全过、
    全量 pytest 仍绿。门禁必须真能拦住它, 且不得误杀 ``data_version``
    (数据血缘, 全仓 42 处合规声明)。
    """

    GATE = "verify_no_version_keys"

    def test_version_key_outside_ssot_is_rejected(self, tmp_path):
        """SSOT 之外的 ``evals/cases/*.yaml`` 加 ``version:`` -> 非零退出。"""
        fake = build_fake_repo(tmp_path, self.GATE)  # 造假仓
        (fake / "evals" / "cases").mkdir(parents=True)  # SSOT 之外的声明面
        (fake / "evals" / "cases" / "case-01.yaml").write_text(
            "id: demo\nversion: 9.9.9\n", encoding="utf-8")  # 正是 A6-02 的原样突变
        proc = run_in(fake, self.GATE, [])  # 跑版本键门禁
        assert proc.returncode != 0, (
            f"SSOT 之外的 version: 键必须判红, 实得 exit={proc.returncode}\n"
            f"stdout: {proc.stdout[-600:]}"
        )

    def test_data_version_is_not_rejected(self, tmp_path):
        """反向: ``data_version`` 属数据血缘, 铁律 1 明确豁免, 不得误杀。

        误杀它等于把 42 处数据溯源声明一并禁掉 —— 那不是修门禁, 是把门禁
        变成噪声源, 而噪声源迟早被整体关掉 (那才是真正的 fail-open)。
        """
        fake = build_fake_repo(tmp_path, self.GATE)  # 造假仓
        (fake / "evals" / "snapshots").mkdir(parents=True)  # 快照目录正是 data_version 的所在地
        (fake / "evals" / "snapshots" / "snapshot.yaml").write_text(
            "data_version: 2026-10-04T00:00:00Z\n", encoding="utf-8")  # 数据血缘, 铁律 1 豁免
        proc = run_in(fake, self.GATE, [])  # 必须判绿
        assert proc.returncode == 0, f"data_version (数据血缘豁免) 不得误报: {proc.stdout[-400:]}"

    def test_real_repo_is_clean(self):
        """实效证据: 真仓全仓扫描必须零违规 (否则这道新门禁一上线就全红)。"""
        proc = subprocess.run(
            [sys.executable, str(AUDIT_DIR / f"{self.GATE}.py")],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=300, cwd=str(SKILL_ROOT),
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
        assert proc.returncode == 0, f"真仓存在版本键残留: {proc.stdout[-800:]}"


class TestVersionGateIsWired:
    """第七条门禁必须真的进了 make audit —— 门禁不在线上等于没有。"""

    def test_makefile_audit_target_includes_version_gate(self):
        """``make audit`` 的实跑清单必须含 ``verify_no_version_keys``。"""
        # 2026-10-07: 判据从「Makefile 配方块含 ops/audit/x.py 子串」改成查实跑清单 ——
        # audit: 已收成单行转发 run_all_gates.py (逐行 recipe fail-fast 会让第 5 道判红后
        # 它后面 4 道从不执行), 子串判定会恒失败, 而恒失败的断言会被当成环境问题忽略。
        assert "verify_no_version_keys" in audit_gate_names(), (
            "铁律 1 的阻断式门禁未接线: version_scan* 恒 return 0 且不在 audit 清单内, "
            "SSOT 之外的 YAML 版本键将无人拦截 (A6-02 突变实验结论)"
        )


class TestEvidenceAnchorsIsNotVacuous:
    """verify_evidence_anchors: E3 的 evidence 指针失准必须判红 (A8-01)。

    突变证据: ``evals/semantics/items.yaml`` 的 ``evidence`` 字段**既无门禁也无
    任何消费者** (全仓 ``*.py`` 搜 evidence/must_state 零命中), 实测 7 题锚点
    指向与断言无关的代码 —— ``E3-D01``/``D02`` 指到"列名小写化"的注释行 (哨兵
    阈值真身在 92 行之外), ``E3-A02`` 指到 ``POS_`` 前缀判别而非 ``n_points``,
    ``E3-D04`` 指到 ``XPSP`` 常量而非 ``*_corr`` 列语义, 本轮复核又新发现
    ``E3-D05``。指针失准 = 那道题的事实基座不存在, 而七道门禁全绿。

    判据钉在符号上而非行号上 (锚点语法 ``path:N-M::symbol``, 与覆盖矩阵同源):
    行号会随 ``src/`` 上方任何注释增删整体平移, 符号不会。所以这组用例注入的
    缺陷形态是"**符号真实存在, 但锚点指在别处**" —— 正是 A8-01 的原样。
    """

    GATE = "verify_evidence_anchors"

    @staticmethod
    def _fake_with_sentinel(tmp_path: Path) -> tuple[Path, int]:
        """造假仓并放入一份带哨兵常量的源文件, 返回 (假仓, 常量真实行号)。"""
        fake = build_fake_repo(tmp_path, TestEvidenceAnchorsIsNotVacuous.GATE)  # 门禁脚本已复制到位
        (fake / "src" / "models").mkdir(parents=True)  # 锚点目标所在目录
        shutil.copy(SKILL_ROOT / "src" / "models" / "__init__.py", fake / "src" / "models" / "__init__.py")  # 真源码: 测的是真符号
        (fake / "evals" / "semantics").mkdir(parents=True)  # 题集落位
        (fake / "evals" / "semantics" / "items_real.yaml").write_text("items: []\n", encoding="utf-8")  # 第二份题集也要存在, 否则门禁先报文件缺失
        lines = (fake / "src" / "models" / "__init__.py").read_text(encoding="utf-8").splitlines()  # 现算行号: 写死会在 src/ 增删行后失效
        real = next(i for i, ln in enumerate(lines, 1) if "NULL_MAGNITUDE_SENTINEL = " in ln)  # 哨兵常量的定义行
        return fake, real

    @staticmethod
    def _write_items(fake: Path, anchor: str) -> None:
        """写入只含一题的题集 —— ``evidence`` 字段就是被测对象。"""
        (fake / "evals" / "semantics" / "items.yaml").write_text(
            f"items:\n- id: E3-PROBE\n  evidence:\n  - {anchor}\n", encoding="utf-8",
        )

    def test_control_clean_anchor_passes(self, tmp_path):
        """对照组: 未注入缺陷的假仓必须 exit 0。

        少了这道对照, "门禁恒红"与"门禁恒绿"同样能满足下面几条的 ``!= 0``,
        证据等于零 —— 这正是本文件开头写明的取证纪律。
        """
        fake, real = self._fake_with_sentinel(tmp_path)  # 对照组: 造干净假仓
        self._write_items(fake, f"src/models/__init__.py:{real}::NULL_MAGNITUDE_SENTINEL")  # 干净锚点
        proc = run_in(fake, self.GATE, [])  # 跑门禁
        assert proc.returncode == 0, f"干净锚点不得误报: {proc.stdout[-400:]}"

    def test_anchor_position_drift_is_warned_with_current_line(self, tmp_path):
        """符号真实存在但落点偏移 -> 记**告警**并给出当前行号, 不阻断。

        这条用例的形态与断言都在 2026-10-05 被实测证据改过一次, 留档说明:
        初版它是"锚点指在 92 行外必须判红"的硬判据。实跑阶段那道判据抓到的是
        **并发编辑造成的合法漂移** —— 本轮 ``src/multiband_photometry.py`` 被他人
        从 309 行扩到 440 行, 同一批符号整体下移 35~56 行而语义一字未改。真实误指
        是 37~92 行, 合法漂移是 35~56 行, **区间重叠: 行距证明不了"指错"**。
        故降为告警 (见门禁模块 docstring「为什么位置偏移不阻断」)。

        降级不等于放弃: 告警必须**带上符号当前行号**, 否则复位无从下手, 那才是
        真的降级没了。所以本用例断言的正是"告警 + 当前行号"这一对。
        """
        fake, real = self._fake_with_sentinel(tmp_path)  # 注入缺陷: 符号存在但锚点指在 92 行外
        far = max(1, real - 92)                      # 复刻实测误指距离 (288 vs 380)
        self._write_items(fake, f"src/models/__init__.py:{far}::NULL_MAGNITUDE_SENTINEL")  # 指到无关注释上
        proc = run_in(fake, self.GATE, [])  # 跑门禁
        assert proc.returncode == 0, (
            f"位置漂移是告警不是阻断 (误指与合法漂移行距区间重叠, 阻断会误伤正常重构); "
            f"实得 exit={proc.returncode}\nstdout: {proc.stdout[-600:]}"
        )
        assert "已漂移" in proc.stdout, f"漂移必须被点名而不是静默放过: {proc.stdout[-600:]}"
        assert str(real) in proc.stdout, (
            f"告警必须给出符号当前行号 (第 {real} 行), 否则复位无从下手: {proc.stdout[-600:]}"
        )

    def test_out_of_range_line_is_rejected(self, tmp_path):
        """行号越过文件末尾 (重写文件后行号大幅前移的典型形态) -> 非零退出。"""
        fake, real = self._fake_with_sentinel(tmp_path)  # 注入缺陷: 行号越过文件末尾
        self._write_items(fake, f"src/models/__init__.py:{real + 10 ** 6}::NULL_MAGNITUDE_SENTINEL")  # 行号远超文件末尾
        proc = run_in(fake, self.GATE, [])  # 跑门禁
        assert proc.returncode != 0, f"行号越界必须判红: {proc.stdout[-400:]}"

    def test_missing_anchor_file_is_rejected(self, tmp_path):
        """锚点文件不存在 (源文件被改名/挪走) -> 非零退出。"""
        fake, real = self._fake_with_sentinel(tmp_path)  # 注入缺陷: 锚点文件不存在
        self._write_items(fake, "src/models/gone.py:1::NULL_MAGNITUDE_SENTINEL")  # 指向不存在的文件
        proc = run_in(fake, self.GATE, [])  # 跑门禁
        assert proc.returncode != 0, f"锚点文件缺失必须判红: {proc.stdout[-400:]}"

    def test_nonexistent_symbol_is_rejected(self, tmp_path):
        """符号在文件里根本不存在 (打错/已删) -> 非零退出。"""
        fake, real = self._fake_with_sentinel(tmp_path)  # 注入缺陷: 符号名在文件里不存在
        self._write_items(fake, f"src/models/__init__.py:{real}::NO_SUCH_SYMBOL_XYZ")  # 符号根本不存在
        proc = run_in(fake, self.GATE, [])  # 跑门禁
        assert proc.returncode != 0, f"不存在的符号必须判红: {proc.stdout[-400:]}"

    def test_empty_items_file_is_rejected(self, tmp_path):
        """题集读空 (结构被改坏) 必须判红, 不能当成"零违规 = 通过"。

        挡的是 fail-open 的经典形态: 门禁扫不到东西时若返回空清单, 空转与全绿
        在退出码上长得一模一样。
        """
        fake, _real = self._fake_with_sentinel(tmp_path)  # 行号用不上, 只借它造假仓
        (fake / "evals" / "semantics" / "items.yaml").write_text("items: []\n", encoding="utf-8")  # 题集清空
        proc = run_in(fake, self.GATE, [])  # 跑门禁: 必须判红而不是当成零违规
        assert proc.returncode != 0, f"题集为空必须判红 (空转门禁比没有门禁更危险): {proc.stdout[-400:]}"

    def test_real_repo_is_clean(self):
        """实效证据: 真仓全部锚点必须零违规 (否则这道新门禁一上线就全红)。"""
        proc = subprocess.run(  # 直接跑真仓: 判据级红测试之外还要有实效证据
            [sys.executable, str(AUDIT_DIR / f"{self.GATE}.py")],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=300, cwd=str(SKILL_ROOT),
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
        assert proc.returncode == 0, f"真仓存在锚点问题: {proc.stdout[-900:]}"


class TestEvidenceGateIsWired:
    """第八条门禁必须真的进了 make audit —— 门禁不在线上等于没有。"""

    def test_makefile_audit_target_includes_evidence_gate(self):
        """``make audit`` 的实跑清单必须含 ``verify_evidence_anchors``。"""
        assert "verify_evidence_anchors" in audit_gate_names(), (  # 同上: 走实跑清单而非 Makefile 子串
            "E3 证据指针的阻断式门禁未接线: evidence 字段无门禁无消费者时, "
            "锚点指到无关代码也不会有人发现 (A8-01 突变实验结论)"
        )


class TestNoGateIsHardcodedGreen:
    """反 fail-open: 门禁的**退出码**必须由判据算出, 而不是写死的常量。

    这是本文件的第一道防线, 也是最便宜的一道: 判据级红测试能抓住"门禁被改成
    恒红", 但抓不住"门禁被改成永远放行" —— 除非额外检查**退出码的来源**。
    突变证据 (A6-04): 把 ``count_code_lines.py`` 改成 ``return 0`` 并提交,
    1020 净行的文件照样 exit 0、全量 1374 测试全绿, 而被废的门禁代码仍在盘上。

    判据精确到"**无条件**的常量退出码", 三个容易误伤的口子都已排除:
      1. 只看 ``main()`` 与模块顶层, 不看辅助函数 ——
         ``verify_import_graph.target_exists()`` 里的 ``return False`` 是
         取值函数, 不是退出码 (它在子进程里才被折成 problems 列表);
      2. 布尔不算常量退出码 —— Python 里 ``False == 0`` 为真, 只比 ``== 0``
         会把每个 ``return False`` 都报成"写死绿灯" (第一版就踩了, 报了两条
         假警报);
      3. 条件分支里的 ``return 0`` 合法 —— ``if not problems: return 0`` 的
         "0" 由判据 (problems 为空) 决定, 与"无论输入都返回 0"是两回事。
    """

    GATES = ("count_code_lines", "comment_audit", "verify_import_graph",
             "verify_crossrefs", "verify_doc_consistency", "verify_no_version_keys",
             "verify_evidence_anchors")

    @staticmethod
    def _is_literal_zero(node: ast.AST) -> bool:
        """是否"常量 0": 排除布尔 (False/True 与 0/1 在 Python 里相等)。"""
        return (isinstance(node, ast.Constant) and not isinstance(node.value, bool)
                and node.value == 0)

    @staticmethod
    def _unconditional_yields(node: ast.AST) -> bool:
        """该语句是否**无条件**执行 (不在任何 If/For/While/Try/BoolOp 内)。

        条件分支里的 ``return 0`` 由判据决定, 不算"写死"; 只有裸写在函数体
        顶层的常量返回才是恒绿 —— 那才是被废掉的形态。
        """
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.If, ast.For, ast.While, ast.Try, ast.BoolOp, ast.IfExp)):
                return False  # 落在条件里 = 由判据决定
            if TestNoGateIsHardcodedGreen._unconditional_yields(child):
                return False
        return True

    def test_gate_exit_codes_are_computed_not_literal(self):
        """逐个硬门禁检查: 退出码不得是**无条件**的常量。"""
        offenders: list[str] = []
        for gate in self.GATES:
            path = AUDIT_DIR / f"{gate}.py"
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for fn in [n for n in tree.body
                       if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                       and n.name == "main"]:
                for node in ast.walk(fn):
                    if isinstance(node, ast.Return) and node.value is not None \
                            and self._is_literal_zero(node.value) \
                            and self._unconditional_yields(node):
                        offenders.append(f"{gate}.py:{node.lineno}: main() 无条件 return 0")
            # 模块顶层的 SystemExit(0): 同样只查无条件形态
            for node in tree.body:  # 只遍历模块**直接**子节点: 函数体内部不算
                if isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call) \
                        and getattr(node.exc.func, "id", "") == "SystemExit" \
                        and node.exc.args and self._is_literal_zero(node.exc.args[0]):
                    offenders.append(f"{gate}.py:{node.lineno}: 顶层 SystemExit(0)")
        assert not offenders, (
            "硬门禁的退出码被写死成常量 —— 判据即使还在也不会生效:\n  "
            + "\n  ".join(offenders)
        )


class TestLineEndingsIsNotVacuous:
    """check_line_endings: 注入 CRLF 必须**被报出来** (H5-04 / G2-15)。

    突变证据 (G2-15 实测): 旧口径只匹配 ``.py``, 于是全仓 68 个受跟踪文件是
    CRLF 而工具只报 1 个 (``evals/repro/transport.py``)。``evals/ablation/
    REPORT.md``、60+ 份 ``capture_log.json`` 全都看不见 —— 门禁 exit 0, 报告
    却在给假安心。这正是 CLAUDE.md 所述"``gen_golden`` 缺 newline='\\n'" 那类
    坑的温床。

    判据断言的是 **stdout 而不是退出码**: 本工具是报告型, 恒 exit 0 (CLAUDE.md
    明确它"刻意不阻断")。唯一可外部依赖的 seam 就是 stdout —— 它的 docstring
    自己写着"可外部依赖的 seam 只有这条 stdout 格式"。所以这里断的是"该报的
    有没有被报出来", 而不是退出码。

    三档判据都要各自钉一道, 少一道就有盲区:
      - 应为 LF (源码/文档/配置)  -> 必须报红;
      - 按字节保真 (数据资产)    -> 必须豁免, 误杀等于逼人 renormalize 被留档的
        站点回包 (``.gitattributes:29-31`` 记的正是那次事故);
      - 允许 CRLF (.ps1/.bat)   -> 必须豁免, 判它红是误伤 Windows 脚本键。
    """

    GATE = "check_line_endings"

    def _repo_with(self, tmp_path: Path, rel: str, content: bytes) -> subprocess.CompletedProcess:
        """造假仓 -> 写入指定字节的文件 -> 跑真门禁副本, 返回子进程结果。"""
        fake = build_fake_repo(tmp_path, self.GATE)  # 门禁的仓根随之落到 tmp
        target = fake / rel                          # 缺陷文件落位 (决定它落在哪一档判据里)
        target.parent.mkdir(parents=True, exist_ok=True)  # 二级目录 (如 snapshots/ 下) 才建父目录
        target.write_bytes(content)                  # 逐字节写: CRLF 必须在字节层注入
        return run_in(fake, self.GATE, [])

    def test_crlf_markdown_is_reported(self, tmp_path):
        """H5-04 原样回归: 一个 CRLF 的 ``.md`` 旧口径看不见, 新口径必须报出。

        这条是本类的核心 —— 它把 G2-15 的盲区钉成"再也不能退化回去"。
        """
        proc = self._repo_with(tmp_path, "docs/REPORT.md", b"line one\r\nline two\r\n")
        assert "docs/REPORT.md" in proc.stdout, (
            "CRLF 的 .md 必须被报出 (旧口径只扫 .py, 这正是 G2-15 的盲区): "
            f"实得 stdout={proc.stdout[-500:]}"
        )
        assert "应为 LF 却含 CRLF 的文件 = 1" in proc.stdout, (
            f"红档计数必须为 1: {proc.stdout[-500:]}"
        )

    def test_crlf_yaml_and_json_are_reported(self, tmp_path):
        """``.yaml`` / ``.json`` 同样在旧盲区里 —— 契约与清单类文件一并钉住。"""
        proc = self._repo_with(tmp_path, "contracts/a.yaml", b"k: v\r\n")
        assert "contracts/a.yaml" in proc.stdout, f"CRLF 的 .yaml 必须被报出: {proc.stdout[-400:]}"
        proc2 = self._repo_with(tmp_path / "j", "manifest.json", b"{}\r\n")
        assert "manifest.json" in proc2.stdout, f"CRLF 的 .json 必须被报出: {proc2.stdout[-400:]}"

    def test_clean_fake_repo_reports_zero(self, tmp_path):
        """对照: 未注入 CRLF 的假仓必须报 0。

        少了这道对照, "恒红"与"恒绿"同样能满足上面两条的 ``in stdout`` ——
        证据等于零, 这正是本文件开头写明的取证纪律。
        """
        proc = self._repo_with(tmp_path, "docs/clean.md", b"only lf\nand more lf\n")
        assert "应为 LF 却含 CRLF 的文件 = 0" in proc.stdout, (
            f"干净假仓必须报 0: {proc.stdout[-400:]}"
        )

    def test_byte_exact_data_asset_is_exempt_not_red(self, tmp_path):
        """快照里的 CRLF 是**站点回包原样落盘**: 必须进豁免档, 不得报红。

        误杀它的代价不是"多一条噪音", 而是逼人去 renormalize 那些被留档的证据
        —— ``.gitattributes:29-31`` 记的正是上一次这么干、误改了 27 个快照。
        """
        proc = self._repo_with(
            tmp_path, "evals/groundtruth/snapshots/live-x/capture_log.json", b'{"a":1}\r\n',
        )
        assert "应为 LF 却含 CRLF 的文件 = 0" in proc.stdout, (
            f"快照类数据资产不得判红: {proc.stdout[-500:]}"
        )
        assert "capture_log.json" in proc.stdout, "豁免也必须列出来, 不能悄悄吞掉"
        assert "豁免" in proc.stdout, "豁免档必须在报告里显式出现"

    def test_csv_is_exempt_and_ps1_is_allowed_crlf(self, tmp_path):
        """``*.csv`` 按字节保真; ``*.ps1`` 明确允许 CRLF —— 两者都不得判红。"""
        proc = self._repo_with(tmp_path, "data/rows.csv", b"a,b\r\n1,2\r\n")
        assert "应为 LF 却含 CRLF 的文件 = 0" in proc.stdout, f".csv 不得判红: {proc.stdout[-400:]}"
        proc2 = self._repo_with(tmp_path / "p", "tools/run.ps1", b"Write-Host 1\r\n")
        assert "应为 LF 却含 CRLF 的文件 = 0" in proc2.stdout, f".ps1 不得判红: {proc2.stdout[-400:]}"

    def test_binary_file_is_not_flagged(self, tmp_path):
        """含 NUL 字节的文件不是行尾问题 —— 其 \\r\\n 是数据, 不得报出来。"""
        proc = self._repo_with(tmp_path, "assets/blob.bin", b"\x00\x01\r\n\x02\x00")
        assert "应为 LF 却含 CRLF 的文件 = 0" in proc.stdout, (
            f"二进制不得被判成行尾问题: {proc.stdout[-400:]}"
        )

    def test_scope_is_printed_so_py_only_cannot_return(self, tmp_path):
        """输出必须自带口径声明 —— 这是"只扫 .py"不可能再溜回来的锁。

        G2-15 的根因不是判据写错, 而是**报告没说自己扫了什么**: 读者无从
        判断覆盖面, 于是"报 1 个"被当成"全仓就 1 个"。所以口径必须打在输出里。
        """
        proc = self._repo_with(tmp_path, "docs/x.md", b"a\r\n")
        for token in ("全仓递归", "应为 LF", "按字节保真", "允许 CRLF"):
            assert token in proc.stdout, f"口径声明缺 {token!r}: {proc.stdout[-400:]}"

    def test_report_type_tool_never_blocks(self, tmp_path):
        """报告型工具恒 exit 0 —— 脏文件不得把它变成阻断门禁。

        钉这条是为了防"为了让判据测试好断言 exit code 而把它改成 exit 1":
        那会让 CLAUDE.md 里"报告型工具刻意不阻断"的口径失效, 也会让一个
        纯展示工具突然卡住 make audit。
        """
        proc = self._repo_with(tmp_path, "docs/dirty.md", b"a\r\nb\r\n")
        assert proc.returncode == 0, (
            f"check_line_endings 是报告型工具, 必须恒 exit 0, 实得 {proc.returncode}"
        )


# 假仓里那份最小错误码契约: 登记号做**键**, ``code`` 字段放**字面量** —— 与真仓同形。
# 只留一个已登记码, 让"方向 A"有唯一可查对象。
_EC_CONTRACT = """skill: astro-best
kind: error-codes
codes:
  BEST_1001:
    code: E_INVALID_INPUT
    trigger: 输入非法
    behavior: block
"""


class TestCrossrefsErrorCodeContractIsNotVacuous:
    """verify_crossrefs 第 8 项: 错误码契约双向对齐必须真的非空转 (H8-02)。

    病灶 (H8-02 实测): 契约 ``codes:`` 段的 ``BEST_NNNN`` 是字典**键**, 而
    ``code`` 字段装的是 ``E_*`` **字面量**。旧判据只扫 ``code``/``name``/``id``
    三个**值**键位去匹配 ``^BEST_\\d+$`` -> 恒收 **0** 个码 -> 循环体一次都不进
    -> 门禁 exit 0。也就是说"契约写了没人用"与"这条检查根本不存在"**在退出码上
    完全一样** (铁律 5 禁 fail-open 要治的正是这个形态)。H8-02 把它修到收 10 条。

    **为什么这组用例原先不在仓内**: 它们只存在于 ``temp/h8_gate_crossrefs_criterion.py``,
    而 ``temp/`` 是 gitignored —— 门禁修好了, 守门禁的证据却没随仓库分发, 克隆机上
    改判定逻辑照样零信号。本类把那 5 条用例 (含对照组) 搬进版本库。

    与 ``test_audit_gate_contracts.py::TestCrossrefsFailClosed`` 的分工: 那一条守的是
    **必读源守卫** (``require_source``: 文件在但内容为空 -> 记 ``[EMPTY]``), 与第 8 项
    的判据无关; 两者合起来才是 ``verify_crossrefs`` 的判据级覆盖。

    假仓必须**九节齐备**才能当对照组: 门禁一响全量, 任何一节的必读源缺失都会让整仓
    exit 非零, 于是"这条判据红了"与"假仓本身不完整"分不开。故把其余八节的必读源
    (spec/契约/管线/片段/清单/环境变量/消费方/治理文档) 全部补成最小可用形态,
    于是对照组绿**只可能**是第 8 项绿。
    """

    GATE = "verify_crossrefs"

    @staticmethod
    def _write(fake: Path, rel: str, text: str) -> None:
        """往假仓里写一个文件 (自动建父目录)。"""
        path = fake / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    @classmethod
    def _fake_repo(cls, tmp_path: Path) -> Path:
        """造假仓: 门禁脚本已由 ``build_fake_repo`` 复制到位, 这里补齐其余八节。"""
        fake = build_fake_repo(tmp_path, cls.GATE)  # 门禁的仓根随之落到 tmp
        cls._write(fake, "contracts/error-codes.contract.yaml", _EC_CONTRACT)  # 被测对象
        cls._write(fake, "src/app.py", 'E_INVALID_INPUT = "E_INVALID_INPUT"\n')  # 代码侧: 已登记码在用
        cls._write(fake, "src/__init__.py", '__all__ = ["app"]\n')  # 第 6 节要 src 包可导入
        cls._write(fake, "references/skills-spec.local.yaml",                  # 第 1 节
                   "skills:\n  astro-best:\n    algorithms:\n    - name: demo\n      module: src.app\n")
        cls._write(fake, "pipeline.yaml", "pipeline:\n  workflows:\n    - name: demo\n      steps:\n"  # 第 3 节
                                        "        - tool: src.app\n")
        cls._write(fake, "static/fragments/algo_mode/two_stage_async_mode.yaml",  # 第 4 节
                   "entry: src.app\n")
        cls._write(fake, "manifest.yaml", "always_load:\n  - src/app.py\n")  # 第 5 节
        cls._write(fake, ".env.example", "ASTRO_BEST_DEMO=1\n")  # 第 7 节: 两侧都要有这个键
        cls._write(fake, "src/scripts/config.py", 'DEMO_ENV = "ASTRO_BEST_DEMO"\n')  # 消费方之一
        cls._write(fake, "src/auth/nadc_oauth.py", 'OTHER_ENV = "ASTRO_BEST_DEMO"\n')  # 消费方之二
        cls._write(fake, "src/__main__.py", 'THIRD_ENV = "ASTRO_BEST_DEMO"\n')  # 消费方之三
        # 三个消费方缺一即报 [ENV] 缺文件 (实测踩过: 漏了 __main__.py 会让**对照组**
        # 假红, 于是"这条判据红了"与"假仓本身不完整"分不开 —— 证据等于零)。
        for doc in ("SKILL.md", "README.md", "architecture.md", "contracts/io-contract.md",  # 第 9 节
                    "references/ALGORITHM-SPEC.md", "references/download-playbook.md",
                    "references/site-endpoints-and-interactions.md"):
            cls._write(fake, doc, "# 占位文档\n")
        cls._write(fake, "contracts/input.contract.yaml", "module: src.app\n")  # 第 2 节
        return fake

    def test_clean_fake_repo_exits_zero(self, tmp_path):
        """对照: 未注入缺陷的九节假仓必须 exit 0。

        没有这条, "门禁恒红"同样能满足下面三条的 ``!= 0`` —— 那测的就不是判据,
        只是"它会崩"。
        """
        fake = self._fake_repo(tmp_path)
        proc = run_in(fake, self.GATE, [])
        assert proc.returncode == 0, (
            f"干净假仓必须 exit 0, 实得 {proc.returncode}\nstdout: {proc.stdout[-600:]}"
        )

    def test_unregistered_code_literal_in_source_is_rejected(self, tmp_path):
        """方向 B (代码->契约): 代码用了一个契约未登记的码 -> 必须非零且点名该码。

        这是 G1-09 本体 ("代码加了码忘了登记"), 原来完全无人看守。
        """
        fake = self._fake_repo(tmp_path)
        (fake / "src" / "app.py").write_text(
            'E_INVALID_INPUT = "E_INVALID_INPUT"\nUNREGISTERED = "E_TOTALLY_NEW_CODE"\n',
            encoding="utf-8")
        proc = run_in(fake, self.GATE, [])
        assert proc.returncode != 0, (
            f"代码用未登记码必须判红, 实得 exit={proc.returncode}\n"
            f"stdout: {proc.stdout[-600:]}"
        )
        assert "E_TOTALLY_NEW_CODE" in proc.stdout, (
            f"方向 B 判红必须点名那个码: {proc.stdout[-600:]}"
        )

    def test_contract_code_without_any_reference_is_rejected(self, tmp_path):
        """方向 A (契约->代码): 契约登记了一个代码零引用的码 -> 必须非零且点名登记号。

        这正是 H8-02 的病灶形态: 旧判据收 0 个码, 登记了没人看的码照样绿灯。
        """
        fake = self._fake_repo(tmp_path)
        (fake / "contracts" / "error-codes.contract.yaml").write_text(
            _EC_CONTRACT + "  BEST_2002:\n    code: E_NEVER_REFERENCED\n"
            "    trigger: 无人引用\n    behavior: block\n", encoding="utf-8")
        proc = run_in(fake, self.GATE, [])
        assert proc.returncode != 0, (
            f"零引用码必须判红, 实得 exit={proc.returncode}\nstdout: {proc.stdout[-600:]}"
        )
        assert "BEST_2002" in proc.stdout, (
            f"方向 A 判红必须点名那个登记号: {proc.stdout[-600:]}"
        )

    def test_declared_block_excuses_unreferenced_code(self, tmp_path):
        """反向自证: 同一个零引用码写进 ``declared`` 段 -> 必须 exit 0。

        这条是关键: 它证明上一条的红来自"**没有声明依据**", 而不是"零引用"本身。
        少了它, 判据会退化成"凡未接线即红", 逼人删掉纪律刻意保留的边界声明。
        """
        fake = self._fake_repo(tmp_path)
        (fake / "contracts" / "error-codes.contract.yaml").write_text(
            _EC_CONTRACT + "  # --- declared (未接线): 以下码刻意保留, 无消费点 ---\n"
            "  # BEST_2002 (E_NEVER_REFERENCED): 边界声明, 接线随信封维度落地\n"
            "  BEST_2002:\n    code: E_NEVER_REFERENCED\n"
            "    trigger: 无人引用\n    behavior: block\n", encoding="utf-8")
        proc = run_in(fake, self.GATE, [])
        assert proc.returncode == 0, (
            f"declared 段的码应被放过, 实得 {proc.returncode}\nstdout: {proc.stdout[-600:]}"
        )

    def test_zero_collected_codes_is_rejected(self, tmp_path):
        """零覆盖守卫: 契约收 0 个登记号 -> 必须非零。

        挡的正是"收集逻辑又退化了" —— 与 H8-02 原始病灶同形: 收 0 个码时若返回
        空问题清单, 空转与全绿在退出码上长得一模一样。
        """
        fake = self._fake_repo(tmp_path)
        (fake / "contracts" / "error-codes.contract.yaml").write_text(
            "skill: astro-best\nkind: error-codes\ncodes: {}\n", encoding="utf-8")
        proc = run_in(fake, self.GATE, [])
        assert proc.returncode != 0, (
            f"契约无任何登记号必须判红 (收集逻辑退化不可见), 实得 exit={proc.returncode}\n"
            f"stdout: {proc.stdout[-600:]}"
        )

