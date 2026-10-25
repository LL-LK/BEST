# -*- coding: utf-8 -*-
"""门禁自覆盖: 证明 ``make audit`` 的六条硬门禁本身没有退化。

起因 (2026-10-02 实测): ``ops/audit/code_fingerprint.py`` 把 git 仓根硬编码成
父目录 ``<SKILLS_ROOT>``, 而本 skill 是独立 git root、父仓已不再跟踪本目录
—— ``git show HEAD:astro-best/<rel>`` 恒 exit 128, 251 个 .py 全落进"新增
未跟踪"分支, ``compared`` 恒为 **0**, 工具"比对过 0 个文件"却照样 exit 0。

**一个恒返回 0 且什么都没比的门禁, 比没有门禁更危险**: 它在 ``make audit`` /
``make check`` / ``make all`` 里显示为通过。而当时全仓 ``test/`` 对
``code_fingerprint`` 零覆盖, 没有任何测试会发现。

本文件补的就是这一层: 门禁自身的回归保护。四道断言 ——
  1. 五条「必须 exit 0」的硬门禁逐条 exit 0 (接线不断) —— 第六条 code_fingerprint
   按设计不断言 exit 0, 见下方 FINGERPRINT_GATE 的说明;
  2. ``code_fingerprint`` 的 ``compared`` 必须 > 0 且与仓内受跟踪 .py 数一致
     (**反 fail-open**: 空转必须红);
  3. ``ops/audit/*.py`` 不得残留硬编码绝对仓路径 (换机可跑);
  4. Makefile 的 audit 目标确实列了全部六条 (改名字/漏接线必须红)。
"""
from __future__ import annotations

# 标准库: ast 解析内联样本 / io 读文件 / os 环境 / re 正则 / subprocess 跑门禁 /
# sys 解释器 / pathlib 仓根定位
import ast  # 内联样本要能 ast.parse, 才能喂给门禁的公开分析器
import io  # 读文件按字节再解码: 门禁崩在非 UTF-8 时也要读得到内容
import os  # 环境变量: 子进程只覆盖编码, 其余原样继承
import re  # 解释器路径: 门禁要用当前解释器跑, 换版本行为会漂
import shutil  # 造假仓: 门禁副本要连同同目录依赖一起复制过去
import subprocess  # 仓根定位: 硬编码盘符会让这条用例在别的机器上直接崩
import sys
from pathlib import Path  # 路径拼装: 门禁脚本目录由仓根推出

# 第三方: pytest 提供 skip 语义
import pytest  # skip 语义: 环境缺失时不判失败

SKILL_ROOT = Path(__file__).resolve().parents[3]  # 仓根: 本文件在 test/unit/meta/, 上溯三级
AUDIT_DIR = SKILL_ROOT / "ops" / "audit"          # 门禁脚本所在目录: 全部硬门禁都从这里拉起

# 共享: 实跑门禁清单的唯一真源解析器 (2026-10-07 起 audit: 收成单行转发后,
# "哪些门禁在跑"这个事实住在 run_all_gates.HARD_GATES 里, 不再能从 Makefile 解析出来)
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # test/ 目录: conftest.py 在此
from conftest import audit_gate_names  # noqa: E402  conftest 需在 sys.path 注入之后导入

# 直接 import 门禁实现, 让"判据本身"可被断言 (见 TestTrailingCommentCriterion):
# 只 subprocess 跑黑盒只能看到"退出码红/绿", 看不出红的是哪一条判据, 判据写
# 反了也只能靠人眼发现。注入 sys.path 必须在 import 之前完成。
sys.path.insert(0, str(AUDIT_DIR))                                                                 # 必须先注入再导入, 否则门禁模块根本找不到
import comment_audit  # noqa: E402  (须在 sys.path 注入之后导入)

# make audit 接线的硬门禁 (顺序即 Makefile 中的顺序)
HARD_GATES = (                                                                                 # 硬门禁的名与参数表: 少一条接线就等于少一道闸
    ("count_code_lines", []),                                                                    # 净行预算门禁: 硬接线, 少一行就等于少一道闸
    ("comment_audit", []),                                                                      # 注释规范门禁: 同样要验接线
    ("verify_import_graph", []),                                                                    # 导入图门禁: 拦跨实验与跨目录非法引用
    ("verify_crossrefs", []),                                                                      # 交叉引用门禁: 注释里提到的路径要真的存在
    ("verify_doc_consistency", []),                                                                # 文档一致性门禁: 文档与代码的声明不许分叉
    ("verify_no_version_keys", []),                                                                # 铁律 1 阻断门禁 (A6-02 补): 曾只进 Makefile 未进本表
    ("verify_evidence_anchors", []),                                                               # E3 证据指针门禁 (A8-01 补): 锚点失准即事实基座不存在
)
# code_fingerprint 单独断言 (见 TestFingerprintIsNotVacuous): 它的职责就是
# 比对工作区与 HEAD, 因此"有未提交代码改动"时 exit 1 属正常业务, 不能混进
# "必须 exit 0"那一组 —— 否则开发到一半的每次全量跑测都会红。
FINGERPRINT_GATE = ("code_fingerprint", ["check"])                               # 指纹门禁的职责就是比对工作区与 HEAD, 有改动时 exit 1 属正常业务
# 报告型工具: 刻意**不阻断**, 因此"不得出现在 make audit 段"是一条要守的不变量。
# 为什么要守 (门禁失败方向审计 2026-10-05 实测): 这四个工具的结论需要人判读,
# 强行阻断会误伤正常重构 —— 最典型的是 verify_no_code_loss 把"删掉一处重复定义"
# 报成 token 减少 (ops/audit/README.md「已知局限」第 1 条有实测样本)。而这条不变量
# 此前**只守住了 1/4**: check_line_endings 有 TestLineEndingsIsNotVacuous 钉"恒 exit 0",
# 另外三个在 test/ 下零命中 —— 明天有人把 verify_no_code_loss 改出 exit 1、或直接接进
# make audit, 测试不会响, 而文档早就写着口径, 两者会「自洽」地一起骗过读者。
REPORT_TYPE_TOOLS = (                                                                       # 报告型工具清单: 少收一个, 那一个就失去"不阻断"守卫
    "verify_no_code_loss",                                                                   # git HEAD vs 工作区的 token 零丢失: 合法清理会被报成 token 减少
    "scan_code_smells",                                                                      # 代码异味清单: 需人判读哪些是真问题
    "version_scan",                                                                          # 版本号文本形态扫描: 恒 return 0, 已被 verify_no_version_keys 取代
    "version_scan2",                                                                         # 同上, 第二个脚本: 同样恒 return 0
    "check_line_endings",                                                                    # 行尾体检: 三档分类, 退出码恒 0
)

# 硬编码绝对仓路径的探测形态: Windows 盘符路径 / 双反斜杠串
HARDCODED_PATH = re.compile(r"""r?["'][A-Za-z]:\\\\?[A-Za-z0-9_\\.-]+""")  # 匹配 r" 与普通串两种写法  # 同时匹配 r 前缀与普通串两种写法, 否则换个写法就绕过


def run_gate(name: str, args: list[str]) -> subprocess.CompletedProcess:
    """跑一条门禁, 统一钉死解码与工作目录后返回子进程结果。

    作用: 把 ``python ops/audit/<name>.py <args>`` 拉成独立子进程执行一遍。
    关键参数: name 是门禁脚本的模块名 (不带 .py), args 是命令行参数表。
    返回: ``CompletedProcess`` —— 刻意不代判 returncode, 空转的门禁正是
    exit 0 却什么都没查, 判定权必须留在调用方与它的断言里。
    """
    # 子进程而非同进程 import: 门禁脚本各自定位仓根并依赖 cwd, 复用本进程会
    # 把 sys.path 与 os.getcwd 搅在一起, 测出来的失败原因会指错方向
    return subprocess.run(                                                            # 子进程拉起: 门禁各自定位仓根并依赖 cwd, 复用本进程会指错方向
        [sys.executable, str(AUDIT_DIR / f"{name}.py"), *args],                                    # 脚本路径由目录与模块名拼出, 避免手抄漏字
        capture_output=True, text=True, encoding="utf-8", errors="replace",  # errors=replace: 门禁崩在非 UTF-8 也要读得到
        # 300s 上限来自全仓最慢的一档 (整仓扫描类门禁冷启动), 再慢就不是门禁
        # 本身的问题而是机器卡住, 让它超时红掉比无限期挂着有用
        timeout=300, cwd=str(SKILL_ROOT),  # cwd 必须是仓根: 门禁按相对路径读 README/树清单
        # 只覆盖编码这一个环境变量: 其余环境原样继承, 否则子进程会丢掉
        # 开发者本地的 PYTHONPATH 等配置, 红的原因就不是被测门禁了
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},              # 只覆盖编码这一个环境变量: 其余原样继承, 否则红的原因就不是被测门禁
    )


class TestHardGatesRunGreen:
    """每条硬门禁都必须真的能跑并 exit 0 (防"文件不在/崩了"被当成通过)。

    参数化而非逐条写成五个方法: 五条门禁的判据完全同构, 拆开写等于把同一
    段断言抄五遍, 而门禁一改名就会漏改其中一份。
    """

    @pytest.mark.parametrize("name,args", HARD_GATES,                                      # 参数化而非逐条写五个方法: 判据同构, 抄五遍必然漏改一份
                             ids=[g[0] for g in HARD_GATES])                                    # 用例 id 用门禁名: 红了能一眼看出是哪一道闸
    def test_gate_exits_zero(self, name, args):
        """门禁脚本在盘上且 exit 0; 崩了或被挪走都必须红而不是静默跳过。

        这里挡的正是"接线断了但没人发现": make audit 里少一行就等于少一道
        闸, 而少一道闸的全绿与全跑通的全绿在 CI 输出里长得一模一样。
        """
        # 先确认脚本存在: 文件被挪走时 subprocess 抛的是 FileNotFoundError,
        # 与 returncode≠0 是两种完全不同的失败形态, 不先判会把诊断信息丢掉
        script = AUDIT_DIR / f"{name}.py"                                                 # 先定位脚本: 挪走与崩了是两种失败形态, 不先判会丢诊断信息
        assert script.is_file(), f"门禁脚本缺失: {script}"                                                # 先确认脚本在: 挪走与崩了是两种失败形态
        proc = run_gate(name, args)  # 刻意不在这里判 returncode: 空转门禁正是 exit 0 却什么都没查
        assert proc.returncode == 0, (  # 挡"接线断了但没人发现": 少一道闸与全跑通在 CI 里长得一样
            f"{name} exit={proc.returncode}\n"                                               # 带上子进程输出: 光有退出码排障时看不出是哪条判据红的
            f"stdout: {proc.stdout[-800:]}\nstderr: {proc.stderr[-400:]}"                   # 把子进程输出带出来: 光有退出码排障看不出是哪条判据红的
        )


class TestFingerprintIsNotVacuous:                                                    # 空转门禁比没有门禁更危险: 它在 make audit 里显示为通过
    """code_fingerprint 必须真的比对, 而不是 compared=0 的空转 (铁律 5)。"""

    def test_fingerprint_runs_and_reports_all_counters(self):
        """工具能跑通并输出全部计数 (removed/unparseable 是真故障, 必须为 0)。

        注意不断言 exit 0: 该门禁比对工作区与 HEAD, 有未提交代码改动时
        exit 1 属正常业务; 把 exit 0 当契约会逼着人绕过门禁。
        """
        name, args = FINGERPRINT_GATE                                                               # 取门禁名与参数表
        proc = run_gate(name, args)                                                                 # 跑门禁, 但不在这里判退出码
        out = proc.stdout  # 只读 stdout: 计数全走 print, 退出码属正常业务信号不断言
        for key in ("compared=", "code-changed=", "new-untracked=",                         # 五个计数缺一即说明工具形态变了, 不能当"值为 0"继续
                    "removed=", "unparseable="):                                                    # 五个计数逐个点名
            assert key in out, f"输出缺 {key} 计数, 工具形态变了: {out[:400]}"                          # 缺任一计数即说明工具形态变了, 不能当"值为 0"继续
        assert re.search(r"removed=(\d+)", out).group(1) == "0", (                                  # 删除计数必须为零
            f"有受跟踪文件被删除: {out[:400]}")                                                              # 报出实际输出
        assert re.search(r"unparseable=(\d+)", out).group(1) == "0", (                              # 语法错误计数必须为零
            f"有 .py 语法错误无法比对: {out[:400]}")                                                      # 报出实际输出: 这两项非零就说明比对本身不完整

    def test_compared_is_positive_and_covers_all_tracked_files(self):
        """compared 必须等于 **HEAD 里**的 .py 数 —— 空转立即红。

        基准取 ``git ls-tree HEAD`` 而不是 ``git ls-files``: 后者把**已暂存
        未提交**的新文件也算进去, 而 code_fingerprint 只能比对 HEAD 里存在的
        那些 (``git show HEAD:<新文件>`` 必然 exit 128), 两者在开发到一半时
        天然差一个数, 用它当基准会让本测试在正常开发状态下误红。
        """
        name, args = FINGERPRINT_GATE                                                               # 取门禁名与参数表
        proc = run_gate(name, args)                                                                 # 跑门禁
        out = proc.stdout                                                              # 只读 stdout: 计数全走 print, 退出码属正常业务信号
        m = re.search(r"compared=(\d+)", out)  # 计数缺失先判: 形态变了不能当"值为 0"继续
        assert m, f"输出里没有 compared= 计数, 工具形态变了: {out[:400]}"                                     # 计数缺失先判: 形态变了不能当"值为 0"继续
        compared = int(m.group(1))                                                                  # 取计数
        ls = subprocess.run(                                                                     # ls-tree 递归列出 HEAD 里的文件名
            ["git", "ls-tree", "-r", "HEAD", "--name-only"], cwd=str(SKILL_ROOT),                 # 递归且只取名字: 这是"基准"该用的那条命令
            capture_output=True, text=True, encoding="utf-8", errors="replace",                # 在仓根下执行: git 的相对路径基准就是 cwd
            timeout=120,                                                                            # 120 秒上限: 列一次树不该更慢
        )
        in_head = len([ln for ln in ls.stdout.splitlines() if ln.strip().endswith(".py")])  # HEAD 里的 .py 全集
        assert compared > 0, (  # 反 fail-open: 比对 0 个文件却 exit 0, 是最危险的一种门禁
            "code_fingerprint 比对了 0 个文件 = 空转 (历史故障: REPO 硬编码父仓 "                                # 把历史故障写进消息: 后来人得知道这条为什么存在
            "导致 git show 恒 exit 128, 门禁恒返回 0 却什么都没查)"                                               # 后半句说明后果: 空转比没有门禁更危险
        )
        assert compared == in_head, (                                                              # 两者必须相等: 差一个数就说明基线仓指错了
            f"compared={compared} 与 HEAD 里的 .py 数 {in_head} 不符 —— "                                 # 不符时要指明可能的两类成因
            f"基线仓指错, 或有文件的 HEAD 版本取不到 (unparseable/removed 非零?)"                                    # 基线仓指错与文件取不到是两种不同的修法
        )


class TestAuditToolsArePortable:                                                                # 可移植性与空转事故同根: 写死仓根的工具换机就崩
    """ops/audit/ 不得残留硬编码绝对仓路径 (换机/换克隆目录必须能跑)。

    这条与空转事故是同一根因的两端: 当年仓根写死成父目录, 换台机器就是
    "找不到仓", 而工具的默认反应往往是静默跳过, 于是可移植性问题会伪装成
    门禁通过。
    """

    def test_no_hardcoded_absolute_repo_path(self):                                   # 逐个审计脚本都要扫, 报告型工具同样会被 make audit 调用
        """每个审计工具都靠 parents[2] 定位仓根, 不得写死盘符路径。

        扫的是 ops/audit/ 下的全部脚本而不是 HARD_GATES 那几份: 报告型工具
        同样会被 make audit 调用, 写死路径会让它们在别人的克隆目录里崩掉。
        """
        # 逐行收集而不是整文件 search 一次: 命中信息要带行号, 整改的人才能
        # 直接定位到那一行, 否则只能自己再搜一遍
        offenders = []                                                                             # 先攒违规行: 一次报全比首错即抛更利于整改
        for script in sorted(AUDIT_DIR.glob("*.py")):  # 排序让失败信息次序可复现
            text = io.open(script, "rb").read().decode("utf-8", "replace")                        # 按字节读再解码: 工具崩在半截也要读得出内容
            for lineno, line in enumerate(text.splitlines(), start=1):                             # 带行号收集: 整改的人要能直接定位到那一行
                if HARDCODED_PATH.search(line):                                                     # 命中即记违规行
                    offenders.append(f"{script.name}:{lineno}: {line.strip()[:80]}")  # 截断到 80: 整行太长反而读不动
        assert not offenders, (                                                                  # 报出全部违规行: 换机即崩或指错仓都属于硬失败
            "ops/audit/ 出现硬编码绝对路径 (换机即崩/或指错仓):\n  "                                              # 报出全部违规行: 换机即崩或指错仓都属于硬失败
            + "\n  ".join(offenders)
        )


class TestMakefileWiring:
    """Makefile 的 audit 目标必须真的列全六条 (漏接线 = 门禁形同虚设)。"""

    def test_audit_target_lists_every_hard_gate(self):                                              # 读 Makefile 的 audit 段
        """读 Makefile 的 audit 段, 逐个硬门禁都要出现, 缺一条即红。

        这里挡的是"门禁还在、接线没了": 工具本身跑得通不代表它进了 make
        audit, 而没进线的门禁在 CI 输出里根本不存在, 退化是零信号的。

        口径注: ``HARD_GATES`` 曾经漏收 ``verify_no_version_keys`` —— 那道门禁
        由 F7 直接写进了 Makefile 并在 ``test_gate_criterion_red.py`` 里自证,
        唯独没进本表, 于是"必须 exit 0"的逐条自覆盖与这里的接线核对都当它
        不存在。**接线与自覆盖必须同源**, 否则总有一道门只受一半的检验。

        2026-10-07 改动: 判据从「Makefile 配方块里出现 ``ops/audit/<名>.py`` 子串」
        换成「``conftest.audit_gate_names()`` 返回的清单里含该名」。原因是 ``audit:``
        已从九行 recipe 改成单行转发 ``run_all_gates.py`` (逐行 recipe 是 fail-fast 的,
        第 5 道判红后它后面 4 道从不执行) —— 继续匹配子串会恒失败, 而恒失败的断言会被
        当成环境问题忽略, 于是"接线核对"这条门禁就此静默消失。
        """
        names = audit_gate_names()  # 实现层真源: 与逐条自覆盖共用同一份清单
        # Makefile 必须真的转发到那个模块: 否则改配方会让本测试对着一个没被调用的清单比对
        text = io.open(SKILL_ROOT / "Makefile", "rb").read().decode("utf-8", "replace")  # 按字节读再解码: Makefile 里可能有非 UTF-8 字符
        m = re.search(r"^audit:\n((?:\t.*\n)+)", text, re.M)  # 配方块必以 tab 缩进, 顶层目标行首无缩进
        assert m, "Makefile 里找不到 audit: 目标"  # 找不到目标就红: 那等于整条 audit 线不存在
        assert "run_all_gates.py" in m.group(1), (
            f"audit: 配方没有转发到 run_all_gates.py, 实跑清单与本测试的真源已脱钩: {m.group(1)!r}"
        )
        all_gates = [g[0] for g in HARD_GATES] + [FINGERPRINT_GATE[0]]  # 五条恒绿 + 指纹门禁
        missing = [name for name in all_gates if name not in names]  # 逐个硬门禁都要在实跑清单里
        assert not missing, f"make audit 未接线: {missing}"


class TestReportTypeToolsStayUnwired:                                                             # 报告型"刻意不阻断"是一条不变量, 此前只守住了 1/4
    """报告型工具**不得**接进 make audit —— 否则"需人判读"就变成了"阻断一切"。

    背景见 ``REPORT_TYPE_TOOLS`` 的注释: 门禁失败方向审计 (2026-10-05) 实测确认
    「报告型恒不阻断」这条不变量当时只由 ``check_line_endings`` 一条用例守着, 另外
    四个在 ``test/`` 下零命中。本类把这条不变量补成**清单级**断言: 五个工具逐个点名,
    少守一个就是缺口。

    与上一类互补: ``TestMakefileWiring`` 断的是"硬门禁**必须**在", 本类断的是
    "报告型**必须不在**"。两条合起来才把 audit 段的成员钉死 —— 只钉前者的话,
    往 audit 段里加一行报告型工具不会让任何测试变红。
    """

    @staticmethod
    def _audit_block() -> str:
        """取出 Makefile 里 audit 目标自己的配方块 (不含其它目标的命令行)。"""
        text = io.open(SKILL_ROOT / "Makefile", "rb").read().decode("utf-8", "replace")  # 按字节读再解码: Makefile 里可能有非 UTF-8 字符
        m = re.search(r"^audit:\n((?:\t.*\n)+)", text, re.M)  # 配方块必以 tab 缩进, 顶层目标行首无缩进
        assert m, "Makefile 里找不到 audit: 目标 —— 整条 audit 线不存在, 本类无从判断"
        return m.group(1)

    def test_no_report_type_tool_is_wired_into_audit(self):
        """逐个点名: 五个报告型工具一个都不许出现在实跑清单里。

        2026-10-07 从「配方块里没有 ``ops/audit/<名>.py`` 子串」改成查
        ``audit_gate_names()``: 配方已收成一行转发, 子串判定会**恒通过** ——
        而恒通过的断言等于没有断言, 正是本类要防的那类空转。
        """
        names = audit_gate_names()  # 实现层真源: 与接线核对共用同一份清单
        wired = [name for name in REPORT_TYPE_TOOLS if name in names]  # 逐个点名, 不抽样
        assert not wired, (
            f"报告型工具被接进了 make audit: {wired} —— 它们的结论需要人判读, "
            f"阻断会误伤正常重构 (CLAUDE.md 与 ops/audit/README.md 都写明刻意不阻断)"
        )

    def test_report_type_tool_count_is_not_shrinking(self):
        """清单条数不得被静默删减 —— 删一个名字就等于给那个工具撤掉守卫。"""
        assert len(REPORT_TYPE_TOOLS) == 5, (
            f"报告型工具清单变成 {len(REPORT_TYPE_TOOLS)} 条 (原 5 条): "
            f"{REPORT_TYPE_TOOLS} —— 新增工具请连同'不阻断'口径一起登记, 退役的请写明理由"
        )


class TestTrailingCommentCriterion:                                                            # 这条判据写反过, 复测才发现整改全做在了反方向
    """反例守卫: Q7「行尾注释」判据必须真的要求"代码在左", 而不只是"缩进非零"。

    要防的退化: 用「COMMENT token 起始列 > 0」判行尾时, 函数体里顶在代码
    **上方**的 ``    # 说明`` 恰好满足该条件 —— 把上方注释保持缩进就能把
    指标刷满。实测下 154/226 个文件真实行尾注释为 0: 指标度量错了对象。

    这组断言就是防它再退化: 纯上方缩进注释**必须**判不达标, 真行尾注释
    **必须**判达标, 两者都靠内联小样本喂给门禁的公开函数, 不依赖全仓现状。
    """

    # 上方缩进注释形态: 每条注释左边**没有代码**, 只有空白 —— 不是"注释在右"
    ABOVE_ONLY = (                                                                            # 反例样本: 每条注释左边只有空白, 不是"注释在右"
        "def f(a):\n"                                                                          # 函数定义: 样本要像真实代码, 判据才会走同一条路
        "    # 这是上方注释, 左边只有空白\n"                                                                    # 上方注释形态, 左边无代码
        "    x = a + 1\n"                                                                           # 真代码行, 左边什么都没有
        "    # 这也是上方注释\n"                                                                           # 又一个上方注释
        "    y = x * 2\n"                                                                           # 真代码行
        "    return y\n"                                                                            # 收尾行
    ) * 8
    # 真行尾形态: 每条注释左边**站着代码**
    TRAILING_OK = (                                                                                 # 正例样本: 每条注释左边都站着代码
        "def g(a):\n"                                                                               # 代码在左
        "    x = a + 1  # 上方空着, 这行左边有代码\n"                                                          # 注释在右
        "    y = x * 2  # 同上\n"
        "    return y  # 返回值也要说明\n"
    ) * 8                                                                                           # 样本末尾

    def _kinds(self, source: str) -> list[str]:                                              # 喂给真实分析器: 复制判据只能证明"我理解的判据自洽"
        """把一段源码喂给门禁的公开分析器, 取出它报的违规 kind 列表。

        走的是 ``analyse_trailing_style`` 真实实现而不是复制一份判据:
        复制判据的测试只能证明"我理解的判据自洽", 证明不了"门禁真是这么判的"。
        """
        lines = source.splitlines()                                                                # 切成物理行: 分析器要按行判左侧有没有代码
        raw = source.encode("utf-8")                                                         # tokenize 要字节: 与 ast 的输入形态不同
        return [f["kind"] for f in comment_audit.analyse_trailing_style(                            # 走门禁的公开函数, 断言它报的 kind
            "<probe>", ast.parse(source), lines, comment_audit.comment_tokens(raw))]

    def test_indented_comment_above_code_is_not_trailing(self):                                     # 这条守住"刷指标的那条退路"必须被堵死
        """只写"上方缩进注释"必须判不达标 —— 挡住刷指标的那条退路。"""
        kinds = self._kinds(self.ABOVE_ONLY)                                                        # 把反例样本喂进去
        assert "trailing_comment_ratio_low" in kinds, (                                     # 必须报占比不达标: 判据被钻空子就会放行"上方缩进注释"
            "Q7 判据被钻了空子: 顶在代码上方的缩进注释被当成行尾注释计数, "
            "于是'保持缩进就能刷满占比'。判据必须是'同一行 # 左侧有代码'。"
        )

    def test_real_trailing_comments_pass(self):                                                    # 这条守住"矫枉过正成不可能满足"也要被堵死
        """真写成"代码在左、注释在右"必须判达标 —— 防止矫枉过正成不可能满足。"""
        kinds = self._kinds(self.TRAILING_OK)                                                       # 把正例样本喂进去
        assert "trailing_comment_ratio_low" not in kinds, (                                   # 必须不报占比不达标: 真行尾注释被判红说明口径写反了
            f"真行尾注释被判不达标, Q7 口径写反了: {kinds}"
        )

    def test_one_space_before_comment_is_flagged(self):                                             # 单空格是 PEP 8 明确不接受的形态
        """行尾注释前只隔 1 个空格必须报 Q8 (PEP 8 的两空格)。"""
        bad = "def h(a):\n" + "".join(                                                              # 先造一个两空格的对照样本
            f"    v{i} = a + {i}  # 第 {i} 条\n" for i in range(1)) + "    return v0\n"          # 拼够行数: 占比判据要看比率, 一行样本起不到作用
        bad = "def h(a):\n" + "".join(                                                            # 覆盖掉对照: 这一份才是真正要断的单空格样本
            f"    v{i} = a + {i} # 第 {i} 条只有一个空格\n" for i in range(1)                               # 每行注释前只留一个空格
        ) + "    return v0\n"
        assert "trailing_comment_spacing" in self._kinds(bad), (                            # 必须报间距违规: 门禁与 PEP 8 的两空格约定脱钩了
            "Q8 没抓到单空格行尾注释 —— 门禁与 PEP 8 的两空格约定脱钩了"
        )


class TestReferencedPathCriterion:                                                       # 这条判据容易被两头带偏: 抓太松等于没加, 抓太紧会逼人删实话
    """反例守卫: Q9「注释引用的仓内路径」判据必须既能抓真悬空, 又不误伤如实登记。

    要覆盖的空白: Q1–Q8 全是**结构性**检查 —— 有没有 docstring、是不是
    中文、密度够不够、注释写在哪, **「注释说的是不是真的」一项都没有**。于是形如
    docs/eval-E1-nl-to-tool.md (真名 eval-E1-nl2tool.md) 这类悬空引用能在两门禁
    全绿时长期存活; 更坑的是 evals/test-scenarios.yaml **真实存在**却是另一套的
    行为场景表, 按注释找会落到一个存在却完全无关的文件上。

    Q9 的判据容易被两头带偏: 抓太松等于没加, 抓太紧则逼人把「已失效」的实话从
    注释里删掉。这组断言用内联小样本同时钉住两头 —— 走 ``analyse_referenced_paths``
    真实实现, 不复制判据。
    """

    # 仓内顶级目录 + 一个**确定不存在**的 ASCII 文件名 (带下划线后缀, 不会被误认为
    # 占位符; 路径不用中文 —— Q9 的路径正则只认 ASCII 段, 含中文的不是路径形态)
    DANGLING = "def f():\n" "    # 见 src/definitely_missing_zzq.py 的定义\n" "    return 1\n"  # 行内注释形态: Q9 对行内注释按行判豁免

    def _findings(self, source: str) -> list[dict]:                                                 # 喂给 Q9 的真实分析器
        """喂一段源码给 Q9 的真实分析器, 取出它报的 finding 列表。"""
        raw = source.encode("utf-8")  # tokenize 要字节, ast 要文本: 同一份样本两种形态
        return comment_audit.analyse_referenced_paths(  # 走真实实现: 复制判据的测试证明不了门禁真是这么判的
            "<probe>", ast.parse(source), source.splitlines(),
            comment_audit.comment_tokens(raw))                                            # 注释 token 一并喂进去: Q9 的判据要读行尾注释原文

    def test_dangling_repo_path_is_flagged(self):                                        # 引用一个不存在的仓内路径必须被抓, 这是 Q9 存在的全部理由
        """引用一个不存在的仓内路径必须被抓 —— 这是 Q9 存在的全部理由。"""
        hits = [f["detail"] for f in self._findings(self.DANGLING)]                                 # 取出每条 finding 的详情
        assert any("definitely_missing_zzq.py" in d for d in hits), (                      # 必须命中那个文件名: 漏了就意味着注释与代码不符无人可发现
            f"Q9 漏掉了悬空路径 (注释与代码不符无人可发现): {hits}"
        )

    def test_retired_annotation_is_not_flagged(self):                                  # 如实登记失效锚点的注释是**正确**的, 逼人删实话是门禁的反作用
        """注释已如实标注该路径失效时**必须放过** —— 逼人删实话是门禁的反作用。"""
        src = ('def f():\n'                                                                # docstring 形态的样本: 注释写在文档串里同样要判
               '    """说明: 见 src/早已删除_zzq.py 的旧定义 (2026-10-03 实测已不存在)。"""\n'                     # 注释里带一个已失效的路径, 并如实标注已不存在
               '    return 1\n')
        hits = [f["detail"] for f in self._findings(src)]                                           # Q9 报出的 finding 列表, 一条都不该有
        assert not hits, (                                                                          # 放过: 逼人删实话是门禁的反作用
            f"Q9 误伤了如实登记失效锚点的注释 —— 那类注释是**正确**的: {hits}"
        )

    def test_external_and_example_paths_are_not_flagged(self):                         # 历史/外部/举例写法必须放过, 否则 Q9 上线即全红而被整体关掉
        """历史/外部前缀与举例写法必须放过, 否则 Q9 上线即全红而被整体关掉。"""
        src = ('def f():\n'                                                                         # docstring 形态的样本
               '    """出处: pybest/tap/adql.py 旧包; 见 _shared/skill-engine/x.md; 例: ops/audit/x.py。"""\n'  # 三种不该管的形态: 旧包名、母仓 skill、举例占位符
               '    return 1\n')
        hits = [f["detail"] for f in self._findings(src)]                                           # 同样取 finding 列表, 用来确认外部形态不误伤
        assert not hits, (                                                                          # 同理放过历史/外部/举例路径
            f"Q9 把历史/外部/举例路径当成悬空引用: {hits}"
        )

    def test_existing_repo_path_is_not_flagged(self):                                        # 真实存在的路径必须放过, 防门禁退化成"见路径即报错"
        """真实存在的仓内路径必须放过 —— 防门禁退化成"见路径即报错"。"""
        src = ('def f():\n'                                                                         # docstring 形态的样本
               '    """实现见 src/downloader.py 的 _save_result。"""\n'                                  # 引用一个真实存在的仓内源文件
               '    return 1\n')
        hits = [f["detail"] for f in self._findings(src)]                                           # 同样取 finding 列表, 真实路径不该在这里出现
        assert not hits, f"Q9 误报了真实存在的路径: {hits}"


class TestSelfConsistency:
    """守卫: 门禁**自己**声明的类数/序列号必须等于 `totals` 的真实键数。

    要防的病: Q10 加入后 `totals` 已是 15 个键、检查序列是 Q1–Q10,
    而 `comment_audit.py` 的模块 docstring 与若干行尾注释仍写「十三类 / 十四类 /
    Q1–Q9」—— 专门修「注释与代码不符」时, 门禁文件自己犯了这个病。
    Q9 (`referenced_path_missing`) 查得了路径、查不了数字断言, 所以没被自动抓到。

    这组断言把「加了一类检查却忘了改声明」变成一次必然的红。
    """

    def test_declared_class_count_matches_totals(self):
        """模块里「N 类违规 / N 类计数 / 写全 N 类」的声明必须等于 `totals` 的键数。

        只管 **kind 数**这一个维度。「Q1–Q10 十个检查组」说的是**检查组**数, 与
        kind 数不等 (一个 Q 组可覆盖多个 kind, 如 Q1/Q2/Q3 共用一遍遍历), 不能
        混进同一断言 —— 早先版本把「十类检查」也当成 kind 数, 守卫对着**正确的**
        措辞报错。措辞已消歧为「检查组」。
        """
        src = (SKILL_ROOT / "ops/audit/comment_audit.py").read_text(encoding="utf-8")
        totals = re.search(r"totals = \{(.*?)\}\n", src, re.S)   # 抓 totals 字面量
        assert totals, "找不到 totals 定义"
        keys = re.findall(r'"([a-z_]+)":\s*0', totals.group(1))
        declared = []                                                                               # 收集与门禁口径相关的声明
        for ln in src.splitlines():                                                                 # 逐行
            if not re.search(r"(违规|计数|写全)", ln):
                continue
            for word in re.findall(r"([零一二三四五六七八九十]+)类", ln):
                declared.append((word, ln.strip()[:50]))                                            # 入表
        assert declared, "模块里找不到任何指代 kind 数的「N 类违规/计数」声明"
        cn = {"零": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6,
              "七": 7, "八": 8, "九": 9, "十": 10, "十一": 11, "十二": 12,
              "十三": 13, "十四": 14, "十五": 15, "十六": 16}
        for word, ln in declared:                                                                   # 逐条核对
            assert cn[word] == len(keys), (                                                         # 不一致即红: 加了检查类却没改声明
                f"注释声明「{word}类」, 而 totals 实际有 {len(keys)} 个 kind: "
                f"加了检查类却没改声明, 门禁会对读者说错自己的口径\n    出处: {ln}"
            )

    def test_declared_check_range_matches_group_count(self):
        """「Q1–Qn」的 n 必须与同处措辞的中文个数一致 (检查组数这一维度)。"""
        src = (SKILL_ROOT / "ops/audit/comment_audit.py").read_text(encoding="utf-8")
        cn = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6,
              "七": 7, "八": 8, "九": 9, "十": 10}
        for line in src.splitlines():                                                               # 逐行找 Q 序列声明
            hi = re.search(r"Q1–Q(\d+)", line)
            if not hi:                                                                              # 没有 Q 序列的行跳过
                continue
            word = re.search(r"([零一二三四五六七八九十]+)个\*\*检查组\*\*", line)
            assert word, (                                                                          # 措辞必须消歧为「检查组」
                f"Q1–Q{hi.group(1)} 的措辞未消歧, 应写成「N 个**检查组**」以免"
                f"与 kind 数混淆: {line.strip()[:60]}"
            )
            assert cn[word.group(1)] == int(hi.group(1)), (                                         # 组数与序列终点必须一致
                f"声明检查组数「{word.group(1)}个」与序列终点 Q{hi.group(1)} 不符"
            )

    def test_kind_count_is_not_equal_to_group_count(self):
        """kind 数 (15) 必须**大于**检查组数 (10) —— 两者本就不等, 不得互相断言。

        要防的错法: 把「Q1–Q10」当成「15 类」来断言, 结果对着正确措辞报错。
        Q 组与 kind 是两个维度, 一个 Q 组可覆盖多个 kind。
        """
        src = (SKILL_ROOT / "ops/audit/comment_audit.py").read_text(encoding="utf-8")
        totals = re.search(r"totals = \{(.*?)\}\n", src, re.S)
        kinds = len(re.findall(r'"([a-z_]+)":\s*0', totals.group(1)))
        groups = max(int(x) for x in re.findall(r"Q1–Q(\d+)", src))
        assert groups < kinds, (                                                                   # 组数应小于 kind 数: 两者是不同维度
            f"检查组数 {groups} 不应大于 kind 数 {kinds}: 若相等说明两者的措辞混用了"
        )


class TestLineAlignmentCriterion:
    """反例守卫: Q10「一行对一行」的分母必须只留**非平凡语句**。

    用户诉求是「代码注释尽量一行对一行, 左右对照, 而不是上下
    代码注释」。Q7 的口径偏粗 —— 它的分母含**样板行**(import / return /
    收尾括号)与**数据行**(星表列名列表、指标定义表), 于是"给列名逐行写右注"也能把
    指标刷上去, 那是注水不是对照。Q10 换掉分母: 样板行与数据行都剔除。

    判据一旦写错, 后果是整改做反方向(与 Q7 首版判据同类事故), 且门禁自己不会喊。
    所以这里用内联小样本钉住两头: 该报必报 / 不该报必放过, 全部走
    ``analyse_line_alignment`` 真实实现。
    """

    # 15 行非平凡语句, 每行都写行尾注释 —— 必须判达标
    ALL_TRAILING = "".join(f"    v{i} = base + {i}  # 第 {i} 行\n" for i in range(1, 16))
    # 同样 15 行非平凡语句, 一条右注都没有 —— 必须判不达标
    NONE_TRAILING = "".join(f"    v{i} = base + {i}\n" for i in range(1, 16))
    # 样板行堆到 30 行, 但 15 个非平凡语句全有右注 —— 样板不进分母, 必须判达标
    TRIVIAL_HEAVY = ("    import os\n" * 10 + "    import sys\n" * 10           # 函数内 import 也是合法样板行
                     + "".join(f"    w{i} = base * {i}  # 非平凡 {i}\n" for i in range(1, 16))
                     + "    return w1\n" * 5)

    def _kinds(self, body: str) -> list[str]:
        """把样本喂给 Q10 的真实分析器, 取出它报的 kind 列表。

        走 ``analyse_line_alignment`` 真实实现而不是复制判据: 复制判据的测试只能
        证明「我理解的判据自洽」, 证明不了「门禁真是这么判的」。
        """
        src = "def f(base):\n    \"\"\"样本。\"\"\"\n" + body
        raw = src.encode("utf-8")
        return [f["kind"] for f in comment_audit.analyse_line_alignment(
            "<probe>", ast.parse(src), src.splitlines(), comment_audit.comment_tokens(raw))]

    def test_full_trailing_passes(self):
        """非平凡语句逐行都有右注必须判达标 —— 否则这条门禁成了不可能满足。"""
        kinds = self._kinds(self.ALL_TRAILING)                                                      # 全右注样本
        assert "line_alignment_low" not in kinds, f"全右注却被判不达标: {kinds}"

    def test_no_trailing_is_flagged(self):
        """非平凡语句一条右注都没有必须判红 —— 这是 Q10 存在的全部理由。"""
        kinds = self._kinds(self.NONE_TRAILING)                                                     # 全无右注样本
        assert "line_alignment_low" in kinds, (
            "Q10 漏掉了完全没有行尾注释的文件: 门禁度量错对象, 整改会做反方向"
        )

    def test_trivial_lines_are_excluded_from_denominator(self):
        """样板行(import/return)不计入分母 —— 否则"堆样板"就能刷高比例。"""
        kinds = self._kinds(self.TRIVIAL_HEAVY)                                                     # 样板行堆叠样本
        assert "line_alignment_low" not in kinds, (
            f"样板行被算进了 Q10 分母: 堆 import/return 就能刷高对照率: {kinds}"
        )

    def test_data_literal_rows_are_excluded(self):
        """长数据表的元素行不计入分母 —— 给列名写右注是注水, 不是对照。"""
        rows = "".join(f'        "col_{i}",\n' for i in range(1, 21))         # 元素行缩进比 TABLE 深一级
        body = ("    TABLE = [\n" + rows + "    ]\n"
                + "".join(f"    u{i} = base + {i}  # 非平凡 {i}\n" for i in range(1, 16)))
        kinds = self._kinds(body)                                                                   # 数据表样本
        assert "line_alignment_low" not in kinds, (
            f"数据表行被算进了 Q10 分母: 给列名逐行写右注就能刷分: {kinds}"
        )

    def test_threshold_is_actually_enforced(self):
        """半对照(15 行里 3 行有右注)必须判红 —— 防止阈值被改成永远达标。"""
        rows = "".join(f"    v{i} = base + {i}{'  # 有' if i <= 3 else ''}\n"
                       for i in range(1, 16))                                                       # 造半对照样本
        kinds = self._kinds(rows)                                                                   # 比例明显不足
        assert "line_alignment_low" in kinds, (
            f"Q10 阈值形同虚设: 3/15 的对照率竟然达标: {kinds}"
        )


class TestCrossrefsFailClosed:
    """verify_crossrefs 的必读源守卫: 零覆盖不得绿灯 (铁律 5 禁 fail-open)。

    ``load_yaml`` 只在「读不到 / 解析失败」时记 ``[YAML]``;
    文件存在但**内容为空**时 ``yaml.safe_load`` 返回 None 且一声不吭, 于是五节
    ``if spec:`` 之类守卫整节跳过 —— 门禁 exit 0 而那一节的覆盖是零。读者会把
    「零覆盖」误读成「这一节没问题」。同文件第 7 节早有 else 分支记账的正确写法,
    这五节只是没照做。
    """

    @staticmethod
    def _load_gate():
        """加载 verify_crossrefs 脚本体并接住它的 SystemExit。

        它是「导入即执行」的脚本体 (顶层直接跑完九类检查并按发现数退出), 所以
        ``exec_module`` 一定抛 SystemExit —— 不接住的话本用例连第一行断言都到不了,
        还会白拿一个「exit 0」当成通过 (那是门禁自己的退出码, 不是本判据的结果)。
        """
        import importlib.util

        path = AUDIT_DIR / "verify_crossrefs.py"
        spec = importlib.util.spec_from_file_location("verify_crossrefs_under_test", path)
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except SystemExit as exc:                     # 门禁跑完整批后自行退出
            module.gate_exit_code = exc.code
        else:
            module.gate_exit_code = None
        return module

    def test_empty_source_is_reported_not_skipped(self):
        """空内容必须记 ``[EMPTY]`` 问题, 而不是静默跳过该节。"""
        mod = self._load_gate()
        assert mod.gate_exit_code == 0, f"前置: 真实仓下门禁应零问题, 实得 {mod.gate_exit_code}"
        before = len(mod.issues)
        mod.require_source(None, "fake/emptied.yaml")      # 文件在但内容为空
        newly = mod.issues[before:]
        assert len(newly) == 1 and newly[0].startswith("[EMPTY]"), (
            f"空必读源未被记账 (零覆盖绿灯 = fail-open): {newly}"
        )

    def test_populated_source_is_not_reported(self):
        """有内容时不得记问题, 且返回值原样传出 (否则守卫会变成见谁都报)。"""
        mod = self._load_gate()
        before = len(mod.issues)
        payload = {"skills": {"astro-best": {"algorithms": []}}}
        returned = mod.require_source(payload, "fake/filled.yaml")
        assert not mod.issues[before:], f"有内容却被误报: {mod.issues[before:]}"
        assert returned is payload, "返回值必须原样传出, 否则调用方的 if 判据会失真"

    def test_every_required_source_goes_through_require_source(self):
        """五处必读源必须全部接上 —— 少接一处就等于那一节仍然是 fail-open。"""
        src = (AUDIT_DIR / "verify_crossrefs.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        calls = [n for n in ast.walk(tree)
                 if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "require_source"]
        assert len(calls) == 5, (
            f"接 require_source 的守卫点应为 5 个 (spec/pipe/frag/mani/ec), 实得 {len(calls)}; "
            f"漏接的那一节就是零覆盖仍绿灯的 fail-open"
        )


class TestBudgetRegistryRowNeedsArgument:
    """登记簿: 一行空表格**不能**把超限文件变成"已登记" (判据审计 D5-02 修复)。

    R2 的字面要求是"超出 400 行的文件必须在本文档登记**必要性论证与拆分预案**",
    而旧实现只取表格首列的文件名 —— 于是一行空表格 (例如登记行写成只有文件名、
    论证列全空的那种) 就把任意超限文件合法化, "论证"部分零强制力 (D5 实测 exit=0)。
    修复后: 该行必须同时含 >=8 个实质字符的中文/小节引用, 否则不计入登记。

    取证: 造一棵假仓 (含登记簿), 注入 450 净行的超标文件。两种登记簿写法
    必须给出**不同**退出码 —— 空论证判红, 真论证判绿。少了绿的那一侧, "判红"可能
    只是因为门禁崩了或恒红。
    """

    @staticmethod
    def _fake_repo(tmp_path: Path, registry_row: str) -> Path:
        """造假仓: 门禁副本 + 登记簿 + 一份 450 净行的未登记文件。

        Args:
            tmp_path: pytest 临时目录。
            registry_row: 登记簿里那一整行的原文 (文件名 + 各列)。

        Returns:
            假仓根目录 (门禁的仓根会自动落到这里)。
        """
        fake = tmp_path / "fakerepo"
        (fake / "ops" / "audit").mkdir(parents=True)  # 门禁落位: parents[2] 即假仓根
        for script in sorted(AUDIT_DIR.glob("*.py")):  # 整个目录: 门禁间同目录裸名互导
            shutil.copy(script, fake / "ops" / "audit" / script.name)  # 原样复制: 测的是真门禁
        budget = fake / "docs" / "architecture" / "file-size-budget.md"  # 登记簿路径与门禁一致
        budget.parent.mkdir(parents=True)
        budget.write_text(
            "# 规模预算\n\n| 文件 | 净代码行 | 物理行 | 状态 |\n|---|---|---|---|\n"
            + registry_row + "\n", encoding="utf-8",
        )
        (fake / "src").mkdir()
        (fake / "src" / "fat.py").write_text(  # 450 净行: 超 400 预算, 全靠登记簿那一行决定放不放行
            "".join(f"V{i} = {i} + 1\n" for i in range(450)), encoding="utf-8",
        )
        return fake

    def test_row_without_argument_is_not_registration(self, tmp_path):
        """反证: 只写文件名、论证列留空 -> 必须判红 (D5-02 的绕过形态)。"""
        fake = self._fake_repo(tmp_path, "| `src/fat.py` | 450 | 450 |  |")  # 论证列留空
        proc = subprocess.run(  # noqa: S603  argv 全是本仓常量, 无 shell
            [sys.executable, str(fake / "ops" / "audit" / "count_code_lines.py")],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=300, cwd=str(fake), check=False,
            env={**os.environ, "PYTHONIOENCODING": "utf-8", "ASTRO_BEST_MIN_SCAN_FILES": "1"},  # 假仓故意只有十几个 .py, 显式声明下限
        )
        assert proc.returncode != 0, (
            f"空论证的登记行不得放行 450 净行的文件 (D5-02 回归), 实得 exit={proc.returncode}\n"
            f"stdout: {proc.stdout[-500:]}"
        )

    def test_row_with_argument_is_accepted(self, tmp_path):
        """对照组: 同一行补上真实论证 -> 必须 exit 0 (证明前一条的红来自论证缺失)。"""
        fake = self._fake_repo(
            tmp_path,
            "| `src/fat.py` | 450 | 450 | 已论证例外: 单一数据表模块, 拆分预案见 §3.99 |",
        )
        proc = subprocess.run(  # noqa: S603  argv 全是本仓常量, 无 shell
            [sys.executable, str(fake / "ops" / "audit" / "count_code_lines.py")],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=300, cwd=str(fake), check=False,
            env={**os.environ, "PYTHONIOENCODING": "utf-8", "ASTRO_BEST_MIN_SCAN_FILES": "1"},  # 假仓故意只有十几个 .py, 显式声明下限
        )
        assert proc.returncode == 0, (
            f"写了论证的登记行必须放行: {proc.stdout[-500:]}{proc.stderr[-300:]}"
        )
