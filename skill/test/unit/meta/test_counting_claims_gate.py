# -*- coding: utf-8 -*-
"""``verify_counting_claims`` 的判据级红测试 + 设计契约 (V2-01)。

为什么单开一个文件而不是并进 ``test_gate_criterion_red.py``: 那份文件由**判据审计
循环**维护 (2026-10-05 循环 2 刚改过), 且它的用例全部是"复制门禁到假仓再实跑"的
同一形状。本门禁多一层职责: 除了"能不能抓住", 还要钉住**它刻意不收哪些类** ——
那些"不收"正是防噪声的设计决定, 一旦被后人"顺手补全"就会退化成噪声源, 而噪声源
的下场是被集体关掉。钉住"不收"与钉住"能抓"同等重要。

三类用例, 缺一不可:
  1. **判据级 (非空转)**: 注入错数字必须 exit 非零, 且**必须有对照组** exit 0 ——
     少了对照, "恒红"与"恒绿"都能满足 ``!= 0``, 证据等于零;
  2. **收窄级 (防噪声)**: 逐条钉住"历史语境 / 归属不可判定 / 数字修饰别的东西"
     这些形态**不得**判红。这几条是本门禁能不能长期活着的关键;
  3. **契约级**: 覆盖面必须来自 ``scan_roots`` (不另列目录), 口径必须复用
     ``count_code_lines.measure`` (不自己重写行数统计) —— 这两条一旦被破, 门禁
     就开始用自己的口径判全仓, 噪声随之而来 (D5-01 同形)。

方法论沿用仓内既有做法: 在 ``tmp_path`` 里造假仓, 把门禁脚本原样复制过去, 以子进程
实跑取真退出码。真仓自始至终不被触碰。
"""
from __future__ import annotations

# 标准库: io 复制门禁源码 / os 环境 / shutil 建假仓 / subprocess 实跑 /
# sys 解释器 / pathlib 拼路径
import io
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SKILL_ROOT = Path(__file__).resolve().parents[3]  # 上溯三级到仓根 (meta -> unit -> test -> 仓根)
GATE_SRC = SKILL_ROOT / "ops" / "audit" / "verify_counting_claims.py"  # 被测门禁本体
GATE_NAME = "verify_counting_claims"  # 门禁名: 假仓里的副本文件名与 make audit 接线都用它
# 门禁依赖两个同目录兄弟: 扫描面真源 + 行数口径真源。复制时必须一起带走, 否则
# 门禁在假仓里 import 不到 —— 这本身也是"口径只有一份"的副作用, 值得记在这里。
DEPS = ("count_code_lines.py", "scan_roots.py", "line_scope.py")  # 第三个是间接依赖, 缺了不影响


def build_fake_repo(tmp_path: Path, gate: str = GATE_NAME) -> Path:
    """造假仓并把门禁及其兄弟依赖原样复制进去 (门禁的仓根随之落到假仓)。"""
    fake = tmp_path / "fake"  # 假仓根: 门禁按自身位置推算仓根, 于是它自动指向这里
    (fake / "ops" / "audit").mkdir(parents=True)  # 门禁副本的落位目录
    (fake / "ops" / "audit" / f"{gate}.py").write_bytes(GATE_SRC.read_bytes())  # 原样复制, 不改一个字
    for dep in DEPS:  # 三个同目录依赖一起带走, 否则门禁在假仓里 import 不到
        src = SKILL_ROOT / "ops" / "audit" / dep  # 依赖本体在真仓
        if src.is_file():  # line_scope 是间接依赖, 缺了不影响本组用例
            (fake / "ops" / "audit" / dep).write_bytes(src.read_bytes())  # 一并复制
    (fake / "src").mkdir()  # 扫描根必须在, 否则是"什么都没扫到"而非"干净"
    return fake


def run_in(fake: Path, gate: str = GATE_NAME, args: list[str] | None = None) -> subprocess.CompletedProcess:
    """在假仓里以子进程实跑门禁副本, 返回带 stdout 的结果对象。"""
    env = dict(os.environ, PYTHONIOENCODING="utf-8", ASTRO_BEST_MIN_SCAN_FILES="1")  # 固定编码(否则中文报错在 GBK 控制台上会炸) + 声明假仓故意很小
    script = fake / "ops" / "audit" / f"{gate}.py"  # 假仓里的门禁副本
    argv = [sys.executable, str(script), *(args or [])]  # 解释器 + 脚本 + 可选位置参数
    return subprocess.run(  # 真跑子进程: 退出码是本组用例唯一可信的证据
        argv, capture_output=True, text=True, encoding="utf-8", env=env, timeout=180,
    )


def make_target(fake: Path, rel: str = "src/thing.py", net_lines: int = 120) -> int:
    """写出**真实**净行数的目标文件 (净行扣空行/纯注释/docstring, 只能写可执行代码)。

    父目录按需创建: 同名歧义那组要写 ``other/thing.py``, 那个目录在假仓里不存在。
    """
    body = "".join(f"V{i} = {i} + 1\n" for i in range(net_lines))  # 每行一条真赋值 = 一行净行
    target = fake / rel  # 目标文件完整路径
    target.parent.mkdir(parents=True, exist_ok=True)  # 同名歧义那组要写 other/, 目录得先建
    target.write_text(body, encoding="utf-8")  # 落盘: 门禁随后要按真实字节重算它的净行
    return net_lines  # 把真实净行数交回给用例, 供它写"正确"与"错误"两个版本


def write_claim(fake: Path, claim: str, rel: str = "src/caller.py") -> None:
    """写一个只含一条断言的注释文件 (放在 docstring 里, 模拟真实形态)。"""
    (fake / rel).write_text('"""src.caller — 夹具。\n\n%s\n"""\nX = 1\n' % claim, encoding="utf-8")


class TestCountingClaimsIsNotVacuous:
    """判据级: 注入错数字必须判红, 且干净假仓必须判绿 (非空转 + 有对照)。"""

    def test_wrong_net_line_claim_is_rejected(self, tmp_path):
        """注释说某文件 999 净行、实测 120 -> 必须非零退出。

        这正是 E3 §4.1 ``88792e1`` 那一类: 提交把 client.py 降到 380, 同一提交
        新建的模块 docstring 却写「463 净行仍超 400 预算」。门禁若抓不住它,
        下一轮重构还会原样再犯。
        """
        fake = build_fake_repo(tmp_path)  # 造假仓
        actual = make_target(fake)  # 目标文件 120 净行
        write_claim(fake, "依赖: ``src/thing.py`` 实测 999 净行, 超预算。")  # 故意写错
        proc = run_in(fake)  # 实跑门禁取退出码
        assert proc.returncode != 0, (  # 非零即判红: 这道是本门禁的存在理由
            f"错数字 (声称 999 实测 {actual}) 必须判红, 实得 exit={proc.returncode}\n"
            f"stdout: {proc.stdout[-600:]}"
        )
        assert str(actual) in proc.stdout, f"输出里应给出实测值便于复位: {proc.stdout[-400:]}"

    def test_correct_net_line_claim_passes(self, tmp_path):
        """对照: 数字改对后必须 exit 0。**没有这条, 判红就可能只是崩。**"""
        fake = build_fake_repo(tmp_path)  # 与上一条同一棵假仓, 只换断言内容
        actual = make_target(fake)  # 目标文件净行数由夹具决定
        write_claim(fake, "依赖: ``src/thing.py`` 实测 %d 净行, 未超预算。" % actual)  # 这次写对
        proc = run_in(fake)  # 实跑
        assert proc.returncode == 0, f"正确的计数断言不得误报: {proc.stdout[-400:]}"

    def test_clean_repo_without_claims_passes(self, tmp_path):
        """对照: 仓内没有任何计数型断言时 exit 0 (不是"扫到东西"才算绿)。"""
        fake = build_fake_repo(tmp_path)  # 造假仓
        make_target(fake)  # 目标文件在, 但没有任何文件去断言它
        (fake / "src" / "plain.py").write_text('"""无计数的模块。"""\nX = 1\n', encoding="utf-8")  # 干净模块
        proc = run_in(fake)  # 实跑
        assert proc.returncode == 0, f"无断言的假仓必须 exit 0: {proc.stdout[-400:]}"


class TestCountingClaimsDoesNotBecomeNoise:
    """收窄级: 逐条钉住"刻意不收"的形态 —— 这些一旦被判红, 门禁就是噪声源。

    本类的存在理由: 门禁的失败模式不是"漏抓", 而是"老红着被人关掉"。因此**收窄
    判据与判红判据同等重要**, 必须有测试钉住, 否则"顺手把扫描面放宽"这类改动
    不会有任何测试变红。
    """

    @pytest.mark.parametrize("label,claim", [
        ("历史语境", "依赖: ``src/thing.py`` 拆分前 999 净行, 现已拆走。"),
        ("转场语境", "依赖: ``src/thing.py`` 由 900 增至 999 净行。"),
        ("数字修饰别的东西", "把门禁改成 ``return 0``: 999 净行的文件照样放行。"),
    ])
    def test_non_assertive_forms_are_not_flagged(self, tmp_path, label, claim):
        """这些形态里的数字不是"某个已点名 .py 的当前净行", 不得判红。"""
        fake = build_fake_repo(tmp_path)  # 造假仓
        make_target(fake)  # 目标文件真实存在且为 120 净行, 数字"错"才有判红的机会
        write_claim(fake, claim)  # 注入该形态的断言
        proc = run_in(fake)  # 实跑门禁取退出码
        assert proc.returncode == 0, f"{label} 形态必须放过(否则门禁变噪声源): {proc.stdout[-400:]}"

    def test_ambiguous_basename_is_not_flagged(self, tmp_path):
        """仓内两个同名 .py 时归属不可判定 -> 放过, 不猜。

        真仓里确有这种形态 (``client.py`` 与 ``tap/client.py`` 同名), 门禁若靠猜,
        就会在"到底指哪个"上判错, 而这类误报无法靠改注释消除。
        """
        fake = build_fake_repo(tmp_path)  # 造假仓
        make_target(fake, "src/thing.py")  # 第一个同名文件
        make_target(fake, "other/thing.py")  # 同名 -> 歧义
        write_claim(fake, "依赖: ``thing.py`` 实测 999 净行, 超预算。")  # 只写 basename, 不指目录
        proc = run_in(fake)  # 实跑
        assert proc.returncode == 0, f"同名歧义必须放过(归属不可判定): {proc.stdout[-400:]}"

    def test_physical_line_claims_are_out_of_scope(self, tmp_path):
        """``物理行`` 刻意不收: 口径不统一 (末尾换行算不算一行两种算法都成立)。

        门禁只认口径唯一的净行。若有人日后"顺手把物理行也收进来", 本用例会红 ——
        那正是要防的: 自己算出另一个口径就开始制造噪声。
        """
        fake = build_fake_repo(tmp_path)  # 造假仓
        make_target(fake)  # 目标文件存在, 门禁才有一条"本该收"的断言可对照
        write_claim(fake, "依赖: ``src/thing.py`` 实测 999 物理行, 超预算。")  # 单位换成物理行
        proc = run_in(fake)  # 实跑
        assert proc.returncode == 0, f"物理行不在本门禁口径内: {proc.stdout[-400:]}"


class TestCountingClaimsDesignContract:
    """契约级: 覆盖面与行数口径都必须只有一份真源 (D5-01 同形, 防退化)。"""

    def test_scan_surface_comes_from_scan_roots(self):
        """扫描面必须 import ``scan_roots``, 不许自列目录清单。

        D5-01 实测: 四道门禁各抄一份目录白名单, 在 ``agents/`` 下放一个 900 净行
        的文件时**四道全部 exit 0**。覆盖面只要出现第二份定义, 缺口就会静默存在。
        """
        src = io.open(GATE_SRC, encoding="utf-8").read()
        assert "from scan_roots import" in src, "覆盖面必须来自 scan_roots 唯一真源"
        assert "SCAN_DIRS" not in src, "不得自列扫描目录清单 (覆盖面只能有一份定义)"

    def test_line_measure_is_reused_not_reimplemented(self):
        """净行口径必须复用 ``count_code_lines.measure``, 不许自己写行数统计。

        自己重写一套统计就是"门禁自己算出另一个口径" —— 本门禁全部噪声的根源。
        """
        src = io.open(GATE_SRC, encoding="utf-8").read()
        assert "from count_code_lines import measure" in src, "必须复用 count_code_lines.measure"
        assert "ast.parse" not in src, "门禁内不得自行解析源码重算行数"

    def test_gate_is_wired_into_make_audit(self):
        """必须接进 ``make audit``, 否则只是一份躺在盘上的脚本。

        2026-10-07: 判据从「Makefile 全文含 ``ops/audit/<名>.py``」改成查实跑清单。
        ``audit:`` 已收成单行转发 ``run_all_gates.py`` —— 逐行 recipe 是 fail-fast 的,
        第 5 道判红后它后面 4 道从不执行 (含铁律 1 的执行者)。子串判定会恒失败,
        而恒失败的断言会被当成环境问题忽略, 于是这条接线核对就此静默消失。
        """
        sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # test/ 目录: conftest.py 在此
        from conftest import audit_gate_names  # noqa: PLC0415  局部导入: 顶层注入会污染其他测试

        assert GATE_NAME in audit_gate_names(), f"新门禁必须接线到 make audit: {GATE_NAME}"


class TestRealRepoCountingClaimsAreConsistent:
    """真仓自检: 本门禁在 HEAD 上必须绿 (且受检面非空 = 没退化成空转)。"""

    def test_gate_exits_zero_on_real_repo(self):
        """真仓实跑: 退出码必须 0 (本轮订正过 2 条真腐烂, 不该再有新的)。"""
        proc = subprocess.run(  # 跑真门禁本体, 不是副本
            [sys.executable, str(GATE_SRC)], capture_output=True, text=True,
            encoding="utf-8", env=dict(os.environ, PYTHONIOENCODING="utf-8"), timeout=300,
        )
        assert proc.returncode == 0, f"真仓的计数型断言必须与实测一致: {proc.stdout[-800:]}"

    def test_gate_imports_cleanly(self):
        """可被 import (单测与审计工具复用 main/scan 的前提)。

        局部 import 是刻意的: 模块顶层会 ``sys.path.insert`` 到自己的目录, 顶层
        导入会污染全量测试的 import 顺序 (仓内既有门禁测试同款做法)。
        """
        import importlib.util  # 局部导入: 避免顶层 sys.path.insert 影响其他测试
        spec = importlib.util.spec_from_file_location("vcc_under_test", GATE_SRC)  # 按路径加载, 不走包
        mod = importlib.util.module_from_spec(spec)  # 先建空模块, 再交给 loader
        spec.loader.exec_module(mod)  # 真执行: 顶层语法错/导入错会在这里炸出来
        assert callable(mod.scan) and callable(mod.main)  # 两个对外接口都得可用
