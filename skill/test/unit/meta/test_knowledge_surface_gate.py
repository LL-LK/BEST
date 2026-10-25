# -*- coding: utf-8 -*-
"""门禁的**知识面被测面**判据级红测试: ``static/fragments/`` 属 E3 被测面这条口径。

起因 (2026-10-05 用户批准): ``static/fragments/`` 被正式列入 E3 的 S-A 被测面
(``docs/eval-E3-semantics.md`` §2)。在此之前该目录已有 9 个小节承载着 E3 正在测的
领域语义规则, 却**不在** S-A 可见面里, 且题集里指向它的 ``evidence`` 锚点实测为
**0 条** —— 那时 E3 测的是模型先验, 不是"本 skill 教给模型的东西"; 而这件事
**没有任何门禁会发现**: 把片段锚点批量删掉, 八道门禁照样全绿。

口径既已确立, 就必须有门禁守住。两档判据 (见门禁
``knowledge_surface_problems`` 的 docstring): 带知识面锚点的题数**下界** +
无锚点题目的**显式登记** (含僵尸登记反查)。刻意不采"逐题必须都有锚点": 那会把
经复核成立的"不该落"题 (A02/E04, 论证见 docs §2.3) 判红, 而让它们转绿的唯一
办法是往片段硬灌条目 —— 那正是会产生第二份会漂移的副本的失败模式。门禁一旦逼人
造假就会被人整体关掉, 那才是真正的 fail-open。

为什么单独一个文件而不是并进 ``test_gate_criterion_red.py``: 并进去会让那个文件
的净代码行越过 400 行预算 (铁律 2), 触发 ``count_code_lines`` 门禁。本文件
只依赖同目录的假仓夹具, 不与那个文件共享判据, 拆开是最小越界的形态。

方法论沿用 ``test_gate_criterion_red.py`` 开头写明的取证纪律: 门禁按
``Path(__file__).resolve().parents[2]`` 定位仓根, 没有 root 参数可传, 故每条用例
在 ``tmp_path`` 里现造一棵**最小假仓**, 把门禁脚本复制到 ``假仓/ops/audit/`` 下,
再注入该判据本该抓住的缺陷, 以子进程跑它、断言非零退出。真仓自始至终不被触碰。
每条红用例都配一道**对照**: 同一棵假仓在未注入缺陷时必须 exit 0 —— 少了对照,
"门禁恒红"与"门禁恒绿"同样能满足 ``!= 0``, 证据等于零。
"""
from __future__ import annotations

# 标准库: ast 校验注入后的门禁仍是合法 Python / importlib 读真仓门禁的常量 /
# re 定位登记表首行与删除键值条目 / shutil 建假仓并复制落点 / subprocess 跑门禁 /
# os 环境 / sys 解释器 / pathlib 路径
import ast
import importlib
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

# 第三方: yaml 用来直接读题集核对知识面覆盖 (pytest 的 tmp_path 夹具无需 import)
import yaml

SKILL_ROOT = Path(__file__).resolve().parents[3]  # 仓根: 本文件在 test/unit/meta/, 上溯三级
AUDIT_DIR = SKILL_ROOT / "ops" / "audit"          # 门禁脚本真身所在目录


def build_fake_repo(tmp_path: Path, gate: str) -> Path:
    """在 tmp_path 里现造一棵最小假仓, 并把门禁脚本复制进去。

    为什么必须造假仓而不能直接用真仓: 门禁用 ``parents[2]`` 定位仓根, **没有**
    root 参数可传。把脚本复制到 ``假仓/ops/audit/`` 下, 它的 ``parents[2]`` 就正好
    是假仓 —— 这是不改门禁代码就能把它的扫描范围换成临时目录的唯一办法。
    """
    fake = tmp_path / "fakerepo"
    (fake / "ops" / "audit").mkdir(parents=True)      # 门禁脚本的落位: 决定它的仓根
    shutil.copy(AUDIT_DIR / f"{gate}.py", fake / "ops" / "audit" / f"{gate}.py")  # 原样复制: 测的是真门禁
    return fake


def run_in(fake: Path, gate: str) -> subprocess.CompletedProcess:
    """在假仓里以子进程跑一条门禁, 返回其退出码与输出。

    子进程而非 import: 门禁是"导入即执行"的脚本体, 在本进程里跑会污染 pytest
    的模块表与 cwd。
    """
    return subprocess.run(
        [sys.executable, str(fake / "ops" / "audit" / f"{gate}.py")],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=300, cwd=str(fake),                    # cwd 指向假仓: 门禁按相对路径读题集
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},  # 只覆盖编码: 其余环境原样继承
    )


class TestKnowledgeSurfaceIsNotVacuous:
    """verify_evidence_anchors 的**知识面被测面**两档判据必须非空转 (2026-10-05)。

    起因: ``static/fragments/`` 于 2026-10-05 被用户批准正式列入 E3 的 S-A 被测面
    (``docs/eval-E3-semantics.md`` §2)。在此之前该目录有 9 个小节承载着 E3 正在测的
    领域语义规则, 却**不在** S-A 可见面里, 且题集里指向它的 ``evidence`` 锚点
    实测为 **0 条** —— 也就是说 E3 那时测的是模型先验, 不是"本 skill 教给模型的东西",
    而这件事**没有任何门禁会发现**: 把片段锚点批量删掉, 八道门禁照样全绿。

    口径既已确立, 就必须有门禁守住。两档判据 (见门禁
    ``knowledge_surface_problems`` 的 docstring):

      1. **下界**: 带知识面锚点的题数不得少于 ``MIN_KNOWLEDGE_ITEMS``;
      2. **登记**: 每道无知识面锚点的题必须在 ``UNCOVERED_BY_DESIGN`` 里带理由登记,
         且登记项不得是题集里已不存在的**僵尸** (否则下界会被架空)。

    刻意不采"逐题必须都有锚点": 那会把经复核成立的"不该落"题 (A02/E04, 论证见
    docs §2.3) 判红, 而让它们转绿的唯一办法是往片段硬灌条目 —— 那正是会产生第二份
    会漂移的副本的失败模式。门禁一旦逼人造假就会被人整体关掉, 那才是真正的 fail-open。

    取证纪律同本文件开头: 每条红用例都配一道**对照组**, 且断言的是**指定判据名
    出现在输出里**而非仅退出码 —— 只断退出码会把"因行号越界而红"当成"因符号判据
    而红"(H7 在位置漂移那组踩过, 对照组假红, 修好夹具行布局后重跑)。
    """

    GATE = "verify_evidence_anchors"
    N_ITEMS = 40   # 假仓题数: 远高于下界, 免得"下界"与"题数"两档判据互相掩盖

    @staticmethod
    def _fake(tmp_path: Path) -> Path:
        """造假仓并放入**它自己要校验的**两类落点 (片段小节 + src 源文件)。

        夹具必须自带落点: 非知识面锚点若指向不存在的文件, 门禁会因"锚点文件不存在"
        判红 —— 那是真判据, 但红的原因与本组要验的东西无关, 证据等于零。
        """
        fake = build_fake_repo(tmp_path, TestKnowledgeSurfaceIsNotVacuous.GATE)  # 门禁脚本就位即等于仓根落定
        (fake / "evals" / "semantics").mkdir(parents=True)  # 题集落位
        frag = fake / "static" / "fragments" / "data_source"
        frag.mkdir(parents=True)
        (frag / "best_catalogs.md").write_text(
            "# data_source/best_catalogs — 假仓\n\n## 探针小节：知识面条目\n\n- 探针正文。\n",
            encoding="utf-8",
        )
        (fake / "src").mkdir(parents=True)
        shutil.copy(SKILL_ROOT / "src" / "multiband_photometry.py",
                    fake / "src" / "multiband_photometry.py")
        return fake

    @staticmethod
    def _drop_real_registry(fake: Path) -> None:
        """从假仓门禁的登记表里删掉真仓那两条 (A02/E04)。

        假仓题集里没有这两个题号, 留着会被"僵尸登记"判据判红 —— 那是真判据, 但
        红的原因与本组无关, 故对照组必须先清掉。删除粒度是**整个键值条目**:
        真仓那两条的理由是跨行隐式字符串续行, 按行删会留下悬空第二段。
        只动**表体**: 这两个题号在 docstring 里还有引用, 那是文档不是数据。
        """
        path = fake / "ops" / "audit" / f"{TestKnowledgeSurfaceIsNotVacuous.GATE}.py"
        src = path.read_text(encoding="utf-8")
        m0 = re.search(r"^UNCOVERED_BY_DESIGN = \{.*$", src, re.M)   # 容忍该行的行尾注释
        assert m0, "登记表锚点没找到, 夹具前提不成立"
        start = m0.start()                                         # 表体起点
        end = src.index("\n}\n", start) + len("\n}\n")   # 表体到收尾的顶格 "}" 为止
        body = src[start:end]                                    # 只切表体, 不碰 docstring 里的同名引用
        for real_id in ("E3-A02", "E3-E04"):
            # 终止分支必须显式排除 "}" 行: 写成 \Z 时 re.S 会让最后一个条目一路吃到
            # 表尾, 把收尾花括号带走, 删完的脚本 '{' was never closed (踩过一次)。
            m = re.search(rf'^    "{real_id}":(?:.*?\n)*?(?=^    "|^}}|^    \}}|\Z)',
                          body, re.S | re.M)
            assert m, f"登记表里找不到 {real_id}, 夹具前提不成立"
            body = body[:m.start()] + body[m.end():]
        assert body.rstrip().endswith("}"), "删完收尾括号没了"
        src = src[:start] + body + src[end:]                     # 拼回完整源码
        path.write_text(src, encoding="utf-8")
        ast.parse(src)  # 删完必须仍是合法 Python: 语法坏掉会让全组假红而看不出原因

    def _write_items(self, fake: Path, n_knowledge: int,
                     extra_unregistered: str | None = None) -> None:
        """写两份题集: 前 ``n_knowledge`` 题带片段锚点, 其余只带 src 锚点并**补登记**。

        补登记是必需的: 否则对照组会被"登记"那一档判红, 红的原因是夹具没签字
        而不是被测判据 —— 那正是本文件开头警告的"证据等于零"。
        """
        self._drop_real_registry(fake)
        rest = [f"E3-P{i:03d}" for i in range(n_knowledge, self.N_ITEMS)]
        for rel in ("items.yaml", "items_real.yaml"):
            lines = ["items:"]
            for i in range(self.N_ITEMS):
                iid = f"E3-P{i:03d}"
                if i < n_knowledge:
                    lines += [f"- id: {iid}", "  evidence:",
                              '  - static/fragments/data_source/best_catalogs.md:3-4::"探针小节：知识面条目"']
                else:
                    lines += [f"- id: {iid}", "  evidence:",
                              "  - src/multiband_photometry.py:1-2::BestMultiBandPhotometry"]
            if extra_unregistered:
                lines += [f"- id: {extra_unregistered}", "  evidence:",
                          "  - src/multiband_photometry.py:1-2::BestMultiBandPhotometry"]
            (fake / "evals" / "semantics" / rel).write_text("\n".join(lines) + "\n", encoding="utf-8")
        gate = fake / "ops" / "audit" / f"{self.GATE}.py"
        src = gate.read_text(encoding="utf-8")
        # 登记表首行: 只认 "行首的键名 + 冒号", 后面有没有行尾注释都算命中
        # (给该行加过行尾注释, 按整行字符串匹配会失配, 注入静默落空)。
        m = re.search(r"^UNCOVERED_BY_DESIGN = \{.*$", src, re.M)
        assert m, "登记表锚点没找到, 注入可能落空"
        inject = "".join(f'    "{i}": "探针登记",\n' for i in rest)
        src = src[:m.end()] + "\n" + inject + src[m.end():]
        gate.write_text(src, encoding="utf-8")
        ast.parse(src)  # 注入后必须仍是合法 Python, 否则全组假红而看不出原因

    def test_control_covered_items_pass(self, tmp_path):
        """对照组: 覆盖达标且无未登记题 -> 必须 exit 0。

        少了这道对照, "门禁恒红"与"门禁恒绿"同样能满足下面几条的 ``!= 0``。
        """
        fake = self._fake(tmp_path)                                               # 对照组夹具: 覆盖达标, 无未登记题
        self._write_items(fake, n_knowledge=35)
        proc = run_in(fake, self.GATE)                                               # 对照组: 未注入缺陷必须 exit 0
        assert proc.returncode == 0, f"干净题集不得误报: {proc.stdout[-500:]}{proc.stderr[-300:]}"

    def test_knowledge_floor_is_enforced(self, tmp_path):
        """注入: 知识面锚点批量删到下界以下 (退回"只测先验"的原状) -> 必须非零。"""
        fake = self._fake(tmp_path)                                               # 下界夹具: 只留 10 题带知识面锚点
        self._write_items(fake, n_knowledge=10)
        proc = run_in(fake, self.GATE)                                           # 下界: 覆盖跌破 MIN_KNOWLEDGE_ITEMS 必须非零
        assert proc.returncode != 0, f"知识面覆盖跌破下界必须判红: {proc.stdout[-500:]}"
        assert "低于下界" in proc.stdout, (
            f"必须因下界判据而红, 而不是因别的判据: {proc.stdout[-600:]}"
        )

    def test_unregistered_item_is_rejected(self, tmp_path):
        """注入: 新增一道题, 既无知识面锚点又未登记 (未签字) -> 必须非零。"""
        fake = self._fake(tmp_path)                                              # 登记夹具: 额外加一道未签字的 E3-NEW
        self._write_items(fake, n_knowledge=35, extra_unregistered="E3-NEW")
        proc = run_in(fake, self.GATE)                                           # 登记: 无锚点且未签字的新增题必须非零
        assert proc.returncode != 0, f"未登记的新增题必须判红 (铁律 5: 未签字 = FAIL): {proc.stdout[-500:]}"
        assert "未在" in proc.stdout, (
            f"必须因登记判据而红, 而不是因别的判据: {proc.stdout[-600:]}"
        )

    def test_zombie_registration_is_rejected(self, tmp_path):
        """注入: 登记表里的题号在题集里已不存在 -> 必须非零。

        僵尸登记会让下界判据名存实亡: 登记簿越堆越大, 真正的漏配题藏在里面看不出来。
        """
        fake = self._fake(tmp_path)                                           # 僵尸夹具: 登记表里塞一个题集里没有的题号
        self._write_items(fake, n_knowledge=35)
        gate = fake / "ops" / "audit" / f"{self.GATE}.py"
        src = gate.read_text(encoding="utf-8")
        m = re.search(r"^UNCOVERED_BY_DESIGN = \{.*$", src, re.M)   # 容忍该行的行尾注释
        assert m, "登记表锚点没找到, 注入可能落空"
        src = src[:m.end()] + "\n    \"E3-GONE\": \"探针僵尸\",\n" + src[m.end():]
        gate.write_text(src, encoding="utf-8")
        proc = run_in(fake, self.GATE)                                           # 僵尸: 登记项在题集里已不存在必须非零
        assert proc.returncode != 0, f"僵尸登记必须判红: {proc.stdout[-500:]}"
        assert "僵尸登记" in proc.stdout, (
            f"必须因僵尸登记判据而红, 而不是因别的判据: {proc.stdout[-600:]}"
        )

    def test_floor_boundary_is_inclusive(self, tmp_path):
        """边界: 知识面锚点**恰好等于**下界 -> 必须 exit 0 (下界是 < 才红, 不是 <=)。"""
        fake = self._fake(tmp_path)                                              # 边界夹具: 知识面锚点恰好等于下界 30
        self._write_items(fake, n_knowledge=30)   # 30 == MIN_KNOWLEDGE_ITEMS
        proc = run_in(fake, self.GATE)                                                # 边界: 恰好等于下界不得误报
        assert proc.returncode == 0, (
            f"恰好等于下界不得误报 (判据是 '<' 不是 '<='): {proc.stdout[-500:]}"
        )

    def test_real_repo_meets_knowledge_floor(self):
        """实效证据: 真仓必须同时满足下界, 且无未登记题。

        判据级红测试之外还要有实效证据 —— 否则"新门禁上线即全红"这类问题要等
        到 ``make audit`` 才暴露。
        """
        mod = importlib.import_module("ops.audit.verify_evidence_anchors")
        problems = mod.knowledge_surface_problems(str(SKILL_ROOT), [])  # 告警列表用不到, 传空即可
        assert not problems, f"真仓违反知识面口径: {problems}"
        # 下界与当前实得之间要有余量: 余量耗尽说明题集在缩, 该复核下界取值了
        counts = []                                             # 每份题集各统计一次
        for rel in mod.ITEM_FILES:                      # 两份题集都要核: 只查一份等于给"改一份留一份"留后门
            data = yaml.safe_load((Path(SKILL_ROOT) / rel).read_text(encoding="utf-8"))
            counts.append(sum(
                1 for it in data["items"]
                if any(str(a).startswith(mod.AGENT_KNOWLEDGE_PREFIX)
                       for a in (it.get("evidence") or []))
            ))
        assert counts and all(c > mod.MIN_KNOWLEDGE_ITEMS for c in counts), (
            f"真仓知识面覆盖应高于下界 {mod.MIN_KNOWLEDGE_ITEMS}, 实得 {counts}"
        )
