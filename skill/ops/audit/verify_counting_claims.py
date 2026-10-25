# -*- coding: utf-8 -*-
r"""ops.audit.verify_counting_claims — 「可机械重算的计数型断言」一致性门禁 (V2-01)。

为什么需要它 (2026-10-05, E3 注释腐烂审计 §3 C 类 / §4.1): E3 从 git 历史审出
**最刺眼的一类腐烂是"同一个提交内部就自相矛盾"** —— 提交 ``88792e1`` 的标题
就是「client.py 463 -> 380 净行」, 而它**新建**的 ``src/client_phase1.py`` 模块
docstring 第 10 行却写着「client.py 实测 463 净行仍超 400 预算」。这不是"忘了改",
是"把旧数字抄进了新文件", 且抄的那一行恰好就在被改动的对象上。这类缺陷 code
review 与 ruff 都看不见: diff 里那行注释是**新增**的, 没有任何工具会比对"新写的
数字"与"被改对象的当前状态"。

本门禁把那一类断言变成可判红: 扫 .py 里的注释/docstring, 凡形如
``<某个 .py> ... <N> 净行`` 的断言, 就用 :func:`count_code_lines.measure` 重算该
文件的净行, 不一致即判红。**重算口径与门禁本体完全同一份** —— 复用 measure() 而
不另写一套行数统计, 正是为了杜绝"门禁自己算出另一个口径"这种自我噪声。

============================  ====================================================
判据设计 (每条都有实测依据, 见 temp/FIX-V2-counting-claims.md)
============================  ====================================================
**收** 只有同时满足四条才纳入检查:
  1. 断言写在 ``.py`` 的注释/docstring 里 (扫描面来自
     :func:`scan_roots.iter_py_files`, 本文件不另列目录 —— 覆盖面只有一份真源,
     这是 D5-01 的教训: 目录白名单漏一个目录就同时废掉四条判据);
  2. 形式是「文件名 + 数字 + 净行」, 且数字**不**紧跟「的」;
  3. 被点名的文件在盘上**唯一可解析** (唯一 basename, 命中一个文件);
  4. 该数字**不是**在描述一段历史/转场。

**不收** (每条都有实测理由, 逐条可复核):
  - ``物理行``: **刻意不收**。口径不统一 —— ``docs`` 与 docstring 里的
    「730 物理行」按 ``splitlines()`` 实测是 729, 按"文件末尾换行算一行"是 730。
    同一句话两种算法都对, 门禁判谁错都是噪声, 于是整类不收 (只收口径唯一的净行);
  - **裸计数** (``26 条`` / ``13 个符号`` / ``共 96 列``): 不收。它们在本仓
    绝大多数指向**外部站点事实** (BEST 有多少列、多少用例), 机械重算的输入根本
    不在仓内; 收进来必然长期红;
  - **历史/转场语境** (「拆分前 463」「当时 581」「由 971 增至 990」): 不收。
    这类断言**说的就是过去**, 拿当前磁盘去比它必然不符 —— 那不是腐烂, 是它本来的
    用途。CHANGELOG 与预算文档整篇是这一形态, 收了就是永久噪声源;
  - **窗口内出现第二个 .py**: 不收。数字归属不可判定时宁可放过, 不猜。

**为什么不会变成噪声源** (本轮在真实仓上实测, 不是推理):
判据定稿前先跑原型量精度 —— 规则收窄前是 3 红 1 误报 (误报形态: 测试文件里
"改成 ``return 0`` 并提交: 1020 净行的文件", 那个 1020 说的是被注入的假文件,
不是前面点名的门禁文件), 加了「数字不紧跟『的』」一条后归零。定稿后在 HEAD 上
实测: **受检 3 条, 误报 0 条, 真问题 2 条** (见 temp 报告逐条)。噪声来自
"扫得太宽", 所以本门禁宁可少收: **判据宁可漏, 不要让老红着的门禁被集体忽视。**

对外接口: :func:`scan` (root) -> 违规清单; :func:`main` (argv) -> 退出码。
``root`` 与 ``root`` 下的扫描面均**显式参数化** —— 判据级红测试要在临时目录里
注入缺陷后实跑, 否则"它能不能抓住自己该抓的东西"永远没人知道 (本门禁修的正是
那一类假绿)。``main`` 无参时取仓根, 供 ``make audit`` 接线。
所属子系统: 仓库治理层 ``ops/audit/`` 的**硬门禁**。只读不写: 命中即报, 门禁
自己绝不擦除现场。

不变量与已知局限 (不掩盖):
  - **只查 .py 里的断言**, 不查 Markdown。``docs/architecture/file-size-budget.md``
    的「次接近上限」清单实测 11 条里 9 条已过期 —— 但那是一张**每次改代码都要刷新
    的预警榜**, 拿它当阻断判据等于"改任何文件都红", 因此本轮只订正它的数字, 不
    纳入门禁 (理由见 temp 报告"决定不纳入"一节);
  - **不判定数字的适用范围**: 门禁只验「点名了哪个文件, 就用那个文件的数」;
    一句话里同时谈两个文件且只给一个数时, 归属靠人工判断, 门禁放过;
  - ``measure`` 返回 -1 (语法错文件) 时**判红**, 不放过 —— 与 count_code_lines
    本体同口径, 坏文件不能在两处门禁的沉默里消失。
"""
from __future__ import annotations

# 标准库: os 取环境变量 / re 拆断言 / io 按字节读再解码
import io
import os
import re
import sys
from collections import defaultdict

# 本地 (同目录裸名导入, 与兄弟门禁同形): 行数口径唯一真源 + 扫描面唯一真源。
# 走 ops.audit. 包路径会在直跑本文件时 ModuleNotFoundError (sys.path[0] 才是
# ops/audit/); 单测注入 AUDIT_DIR 后 import 亦然。**两样都不许自己重写一份** ——
# 重写行数统计就是"门禁自己算出另一个口径", 那是自我噪声的头号来源。
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # 先把同目录挂进 path, 后两行的裸名导入才成立
from count_code_lines import measure  # noqa: E402  净行口径唯一真源: 复用它才不会出现"两种口径"
from scan_roots import iter_py_files, require_nonempty_scan  # noqa: E402  扫描面唯一真源: 覆盖面只能有一份定义 (D5-01)

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # 上溯三级到仓根

# 断言形态: 文件名 + (窗口) + 数字 + 净行, 且数字后**不**紧跟「的」。
# 末尾的 (?!的) 是本门禁最关键的一条收窄: 「1020 净行的文件」里的 1020 在修饰一个
# 名词短语(在**定义**某个东西), 不是在断言前面那个文件的度量 —— 误报就出在这里。
CLAIM_RE = re.compile(r"(?P<file>[\w./\\-]+\.py)[^。；;\n]{0,60}?(?P<n>\d{1,4})\s*净行(?!的)")
PY_REF_RE = re.compile(r"[\w./\\-]+\.py")

# 历史/转场语境标记: 命中即跳过。理由见模块头「不收」一节 —— 这类断言说的就是过去,
# 拿当前磁盘比它必然不符, 那不是腐烂而是它的原用途。**这份名单是"宁可放过"的
# 方向**: 漏一个历史词的后果是多收一条本不该查的断言(可能误报), 多收一个词的后果
# 是漏掉一条真腐烂(漏报) —— 取前者, 因为误报会让门禁被整体关掉。
HIST_RE = re.compile(
    r"(拆分前|拆分后|抽离前|抽离后|抽出前|抽出后|原单|原为|原文件|原实现|原定|起初|从\s*\d|由\s*\d|"
    r"降至|降到|降为|涨到|增至|减到|→|->|曾|当时|历史|旧|增量|阶段|拆出|抽出|抽离|拆成|拆四件|"
    r"约\s*\d|回到|之前|之后|已按|已从|本轮|计划|预案|可到|可达|量级|留档|此前|曾经)"
)


def _read(path: str) -> str:
    """按字节读再解码; 读不出返回空串 (由调用方按"无可检断言"处理)。"""
    try:
        with io.open(path, "rb") as fh:  # 按字节读: 文本模式会吃掉换行, 物理行数随机器而变
            return fh.read().decode("utf-8", "replace")  # replace 兜底: 单个坏字节不该让门禁整体崩掉
    except OSError:
        return ""  # 读不出即视为无可检内容: 该文件的问题由别的门禁负责, 这里不猜


def _basename_index(root: str) -> dict[str, list[tuple[str, int]]]:
    """basename -> [(相对路径, 净行), ...]; 值多于一项即"仓内同名", 不可解析。

    相对路径一律正斜杠, 与 scan_roots 口径一致。**只用 measure 的净行那一项**,
    物理行故意不取 (口径不统一, 见模块头)。
    """
    index: dict[str, list[tuple[str, int]]] = defaultdict(list)  # 累加器: 同名文件要能全部看见
    for rel, full in iter_py_files(root):  # 覆盖面来自 scan_roots, 本文件不另列目录
        index[os.path.basename(rel)].append((rel, measure(full)[1]))  # 只取净行: 物理行口径不统一
    return index


def scan(root: str) -> list[str]:
    """扫 root 下全部 .py 的注释/docstring, 返回计数型断言与实测不一致的违规清单。

    违规项格式: ``<相对路径>:<行号>: 断言 <N> 净行, 实测 <M> (被点名文件 <rel>)``。
    空列表 = 门禁绿。

    判据见模块头表格。**逐条早退**而不是收集完再筛: 归属不可判定时立刻放过,
    一个断言至多产生一条违规, 同一行也不会被两条规则重复计入。
    """
    index = _basename_index(root)  # 一次量全仓: 逐条重算会把 measure 跑成 O(文件数 x 断言数)
    problems: list[str] = []  # 违规累加器: 空列表 = 绿
    for rel, full in iter_py_files(root):  # 覆盖面来自 scan_roots, 本文件不另列目录
        for lineno, line in enumerate(_read(full).splitlines(), 1):  # 逐行扫: 断言是行级的
            for m in CLAIM_RE.finditer(line):  # 一行可含多条断言(罕见), 故用 finditer 而非 search
                seg = m.group(0)  # 命中的整段: 下面三条排除规则都要看整段而不是单个数字
                base = os.path.basename(m.group("file"))  # 按 basename 归一: 文档里两种路径写法混用
                cands = index.get(base, [])  # 候选集: 长度必须恰为 1 才算可归属
                if len(cands) != 1:  # 0 = 点名的文件不在盘(测试夹具/已删); >1 = 仓内同名
                    continue  # 归属不可判定 -> 放过, 不猜
                if any(os.path.basename(o) != base for o in PY_REF_RE.findall(seg)):
                    continue  # 窗口内另有 .py -> 数字可能属于它 -> 放过
                if HIST_RE.search(seg):
                    continue  # 历史/转场语境 -> 断言说的就是过去 -> 放过
                claimed = int(m.group("n"))  # 断言里的数字
                target, actual = cands[0]  # 唯一候选: (相对路径, 实测净行)
                if actual < 0:  # measure 的语法错哨兵: 判红而不是当作"没超"
                    problems.append(
                        "%s:%d: 断言 %d 净行, 但 %s **无法计量**(语法错), 判据失效"
                        % (rel, lineno, claimed, target))
                    continue  # 量不出来就没法对账, 但必须报出来而不是沉默
                if claimed != actual:
                    problems.append(
                        "%s:%d: 断言 %s 是 %d 净行, 实测 %d —— 改注释或改代码, 二者必须同步"
                        % (rel, lineno, target, claimed, actual))
    return problems


def main(argv: list[str] | None = None) -> int:
    """主入口: 打印违规清单并返回退出码 (非空即 1)。

    Args:
        argv: 可选命令行参数; ``argv[1]`` 作为仓根(供判据级红测试在假仓上实跑),
            缺省用模块级 ROOT。**不引 argparse** —— 只有一个可选位置参数, 引进来
            只为这个不值得 (行数预算 400)。

    Returns:
        0 = 无不一致; 1 = 存在计数型断言与实测不符 (门禁红)。
    """
    args = list(sys.argv[1:] if argv is None else argv)
    root = os.path.abspath(args[0]) if args else ROOT
    # 负对照 (2026-10-07): 本门禁在扫描面为空时实测打印「0 条不符」并 exit 0 ——
    # 而它的判据恰恰是"文档里的计数与实测对不对", 没扫到文件时"全都对得上"是废话。
    if not require_nonempty_scan("verify_counting_claims",
                                 [rel for rel, _full in iter_py_files(root)]):
        return 1
    problems = scan(root)
    print("=== 计数型断言 vs 实测 (%d 条不符) ===" % len(problems))
    for p in problems:
        print("  [COUNT] %s" % p)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
