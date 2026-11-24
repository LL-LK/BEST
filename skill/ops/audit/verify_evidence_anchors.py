# -*- coding: utf-8 -*-
"""verify_evidence_anchors.py — E3 题集 evidence 锚点的**阻断式**门禁 (A8-01)。

为什么需要它 (2026-10-04 突变实验 A8-01): ``evals/semantics/items.yaml`` 的
``evidence`` 字段是 36 道语义题的**证据指针** (这道题的断言在仓里哪条代码/哪份
文档处成立), 但它此前**既无门禁也无任何消费者** —— 全仓 ``*.py`` 搜
``evidence``/``must_state`` 零命中, 指针指错了没有任何机制会发现。实测后果:
6 题的锚点指向与断言无关的代码 (``E3-D01``/``D02`` 指到"列名小写化"的注释行,
而哨兵阈值真身在另一处; ``E3-A02`` 指到 ``POS_`` 前缀判别而非 ``n_points``
定义; ``E3-D04`` 指到 ``XPSP`` 常量而非 ``*_corr`` 列语义), 本轮复核又新发现
第 7 处 (``E3-D05`` 断言讲 ruwe/ipd_frac_multi_peak, 锚点却落在
``phot_variable_flag`` 那一段)。**指针失准 = 这道题的事实基座不存在。**

判据钉在**符号**上而不是行号上 —— 这是本门禁最关键的一处取舍。行号会随
``src/`` 上方任何一次注释增删而整体平移 (本轮实测 ``src/models/__init__.py``
在任务进行中从 524 行长到 526 行, 哨兵常量从 378 漂到 380;
``src/multiband_photometry.py`` 更从 309 行被扩到 440 行, 同一批符号整体
下移 35~56 行), 而符号跟着代码一起走。因此锚点语法取本仓覆盖矩阵已在用的
``path:N-M::symbol`` 形态 (见 ``test_coverage_matrix.py::test_anchor_paths_exist``),
门禁分两档判, 边界是**实测**划出来的而不是拍的:

  1. **文件存在** —— 硬失败。文件被改名/挪走时指针即失效;
  2. **行号在范围内** (``1 <= a <= b <= len(lines)``) —— 硬失败, 挡住越过
     文件末尾的悬空行号 (重写文件后行号大幅前移的典型形态);
  3. **符号确实存在于该文件** —— 硬失败。这是"指向了别的代码"这一族缺陷的
     真正判据: 符号名写错、符号被删、符号被改名, 三种都会红。

**为什么"符号落点偏移"只告警不阻断** (这条是被实测推翻的初版设计, 留档说明):
初版把"符号必须落在锚点 ±8 行内"当硬判据, 理由是它能挡住 288-vs-380 那一类
误指。实跑阶段它确实立刻抓到了真问题 —— 但抓到的是**并发编辑造成的合法漂移**:
另一个 agent 在本任务进行中把 ``src/multiband_photometry.py`` 从 309 行扩到
440 行, ``BestMultiBandPhotometry`` 从 54 漂到 89、``n_points`` 从 196 漂到
252, **语义一字未改**。两个数据点摆在一起说明: 行距证明不了"指错"与"文件长大"
的区别 (误指是 37~92 行, 合法漂移是 35~56 行, 区间重叠), 拿它当阻断判据等于
把正常重构报成缺陷, 而门禁一旦成为噪声源, 迟早被整体关掉 —— 那才是真正的
fail-open。故降为告警, 并在告警里**直接给出符号当前行号**, 复位只需改一个数。

降级不等于放弃: 结构性防线仍在 —— 每条行锚点**必须**带 ``::符号`` 段, 不带
就告警点名, 因此锚点无法静默退化成"某文件里随便一个行号"; 而 A8-01 那 7 处
误指的共同特征 (符号写错/指到无关常量) 仍由第 3 档硬判据覆盖。

对外接口: ``scan(root)`` 返回 (违规, 告警) 二元组, ``main()`` 返回退出码。
``root`` 是**显式参数** —— 判据必须能在临时目录里注入缺陷后实跑验证, 否则
"它能不能抓住自己该抓的东西"永远没人知道 (这正是本门禁要修的那类假绿)。
所属子系统: 仓库治理层 ``ops/audit/`` 的**硬门禁** (``make audit`` 接线)。
只读不写: 命中即报, 修不修由人决定, 门禁自己绝不擦除现场。

不变量与已知局限 (不掩盖):
  - 不判定**语义相关性**: 符号存在只证明"指针没指错地方", 不证明"这道代码支持
    这句断言"。后者需要人或模型判读, 本门禁刻意不猜。
  - **行号是提示不是判据**: 符号被整个挪走而锚点行号恰好还在容差内时, 本门禁
    放行 (符号存在性照过)。真正防住这一类的是告警里的当前行号提示 + 人工复核。
  - 散文形态锚点 (``references/xxx.md 概述段``) 只能校验文件存在 —— 它们不带
    行号也不带符号, 会以 WARN 形式列出待改写清单。
  - 只覆盖 E3 (``evals/semantics/``)。E1/E4/E5/E6 的题集**没有** ``evidence``
    字段, 因此它们的"证据指针失准"这一族缺陷本门禁看不见。

**非 Python 锚点: 智能体可见知识面 (2026-10-05 H7-01 扩展)**: 上面第 3 档的"符号"
对 ``.py`` 才有意义 (绑定名 / 字符串字面量)。E3 测的是"模型**该不该**知道某条知识",
而这条知识现在要指到 ``static/fragments/`` —— 那是 Markdown, 没有绑定名可言,
它的"符号"就是**小节标题**。故本门禁对 Markdown 锚点按 **标题行字面量**解析
(见 ``heading_lines``): 标题被改名/删除立刻判红, 正文里提到同一句话**不算** ——
否则锚点仍能退化成"文件里随便一句提及", 恰好是 A8-01 要防的形态。其余非 ``.py``
后缀 (YAML 等) 没有定义过符号约定, 一律**判红**而不是放行 (fail-closed)。

**知识面被测面口径 (2026-10-05 用户批准)**: ``static/fragments/`` 被正式列入 E3 的
S-A 被测面 (``docs/eval-E3-semantics.md`` §2) —— 在此之前该目录有 9 个小节承载着
E3 正在测的领域语义规则, 却**不在** S-A 的可见面里, 于是 E3 测的是模型先验而非
"本 skill 教给模型的东西"。口径既已确立, 删掉片段锚点就能把 S-A 悄悄退回原状,
因此本门禁新增两档**硬判据** (见 :func:`knowledge_surface_problems`):
带知识面锚点的题数**下界** + 无锚点题目的**显式登记**。刻意不采"逐题必须都有" ——
那会把经复核成立的"不该落"题判红, 而让它们转绿只能靠硬灌条目 (第二份会漂移的副本)。
"片段小节 × 题目覆盖率"**只告警**: 该不该落需人判读, 机器不裁定。
"""
from __future__ import annotations

# 标准库: ast 解析符号 / io 按字节读再解码 / re 拆锚点 / pathlib 仓根
import ast  # 符号解析靠语法树: 文本包含会被注释与 docstring 里的同名提及骗过
import io  # 按字节读再解码: 文件含非 UTF-8 字节时也要读得出行数再判
import re  # 锚点语法解析: path[:N-M][::symbol] 三段
import sys  # 命令行参数 (--fix) 与子进程无关, 但入口要读 argv
from pathlib import Path  # 路径拼装: 仓根由本文件位置推出, 不写死盘符

ROOT = str(Path(__file__).resolve().parents[2])  # 仓根上溯两级: 硬编码绝对路径换机即失效

# 锚点语法: 路径可含字母数字与 . _ / - ; 行号段可省 (散文锚点) 或写成 N / N-M ;
# 符号段写成 :: 后跟标识符或带引号的字面量 (星表列名带引号才能与标识符区分)。
ANCHOR_RE = re.compile(
    r"""^(?P<path>[A-Za-z0-9_][A-Za-z0-9_./\-]*)          # 仓内相对路径
        (?::(?P<start>\d+)(?:-(?P<end>\d+))?)?              # 可选行号段: N 或 N-M
        (?:::(?P<sym>[A-Za-z_][A-Za-z0-9_]*|"[^"]+"))?$     # 可选符号段: 标识符或带引号字面量
    """,
    re.X,
)
# 散文锚点的路径部分: 整串第一个空格之前那一段 ("references/x.md 概述段" -> "references/x.md")
PROSE_SPLIT_RE = re.compile(r"\s+")  # 散文锚点按空白切成 [路径, 描述] 两段
DRIFT_TOLERANCE_LINES = 8  # 符号位置容差 (行): 取值依据见模块 docstring
# 按"标题行字面量"解析符号的后缀白名单: 智能体可见知识面是 Markdown 小节, 标题
# 就是它的符号。白名单而非"所有非 .py" —— YAML 的 # 是注释不是标题, 放进来会把
# 注释行误当符号, 而"没定义过符号约定的后缀一律判红"才是 fail-closed 的那一侧。
HEADING_ANCHOR_SUFFIXES = {".md", ".markdown"}

# 题集清单: 门禁扫哪些文件。E3 保留 items_real.yaml 是切换前的同内容副本
# (其 _status 自述"与 items.yaml 内容一致"), 故两份都必须过门禁 —— 只查一份
# 等于给"改一份留一份"留后门。
ITEM_FILES = ("evals/semantics/items.yaml", "evals/semantics/items_real.yaml")  # 两份都要查
# --fix 用的**行级**锚点正则: 只认题集 evidence 列表项里的 "path:start-end::symbol" 形态。
# 与 ANCHOR_RE 的区别是本正则**要求**行号段存在 —— 漂移复位对散文锚点无从下手 (没有落点),
# 放进同一张表会让 --fix 去改不该改的行。
ANCHOR_LINE_RE = re.compile(  # --fix 专用: 与 ANCHOR_RE 的区别是**要求**行号段存在
    r"(?P<rel>[A-Za-z0-9_][A-Za-z0-9_./\-]*):(?P<start>\d+)-(?P<end>\d+)::(?P<sym>.+)"  # 行号段不可省: 散文锚点没有落点可复位
)
AGENT_KNOWLEDGE_PREFIX = "static/fragments/"  # 智能体可见知识面: E3 测"该不该知道", 指向它 0 条即等于没测
# 带知识面锚点的题数**下界** (硬判据)。``static/fragments/`` 于 2026-10-05 被用户批准
# 正式列入 E3 的 S-A 被测面 (docs/eval-E3-semantics.md §2), 于是"题集里有没有
# 知识面锚点"从"建议"变成"口径的一部分", 必须有门禁守住, 否则删掉片段锚点即可
# 把 S-A 悄悄退回"只测模型先验"的原状而无人发现 (基线: 0 条)。
# 取 MIN 而不是当前实得 34: 题集增删不该立刻打红, 但**整类倒退**必红。
MIN_KNOWLEDGE_ITEMS = 30                                                                   # 题数下界, 取值依据见上方注释
# 无知识面锚点但**经复核不该有**的题 (显式登记, 铁律 5: 未签字 = FAIL)。
# 每条都必须在 docs/eval-E3-semantics.md §2.3 有对应论证 —— 登记不是豁免,
# 是"这一题的知识落在仓内实现事实上, 沉淀进片段=第二份会漂移的副本"的签字。
UNCOVERED_BY_DESIGN = {                                                                      # 登记簿: 题号 -> 不该落的理由
    "E3-A02": "n_points 是本仓 BestMultiBandPhotometry 的输出字段, 与该 dataclass 同生共死; "
              "通用层(BEST 不给时序)已由「能力边界」小节承载并由 A01/A04/G04/G05 实测",
    "E3-E04": "scr_lamost 无 Teff/logg 是表自身的列清单事实, 与列登记表同生共死; "
              "推论层(不得为不存在的列编覆盖范围)已由「列定义未登记」小节承载并由 C03/E03 实测",
}


def parse_anchor(raw: str) -> tuple[str, int, int, str] | None:
    """把一条 evidence 拆成 (路径, 起行, 止行, 符号); 无法解析返回 None。

    行号段缺省时起止行都是 0, 调用方据此区分"散文锚点"与"行锚点"。符号段
    保留引号形态 (星表列名字面量带引号才有意义), 去引号交给符号解析那一步。
    """
    m = ANCHOR_RE.match(raw.strip())              # 首尾空白常来自 YAML 缩进
    if m:                                          # 规范形态: 整串匹配
        start = int(m.group("start") or 0)         # 缺省 0 = 无行号段
        end = int(m.group("end") or start)         # 缺省与 start 同 (单行锚点)
        return m.group("path"), start, end, m.group("sym") or ""
    head = PROSE_SPLIT_RE.split(raw.strip(), 1)[0]  # 散文形态: 取首段当路径
    if not head:
        return None                                 # 空串: 交给调用方报错
    return head, 0, 0, ""                           # 无行号无符号 = 散文锚点


def symbol_lines(path: Path, symbol: str) -> list[int]:
    """返回 symbol 在该文件里的全部定义行号; 找不到或文件不可解析返回空表。

    ``.py`` 走语法树 (下方实现), Markdown 走 :func:`heading_lines` 的标题行字面量,
    其余后缀一律返回空表 (即判红) —— 没有定义过符号约定的文件类型不能放行。

    ``.py`` 分支识别四类定义 (类/函数/赋值/带注解赋值) 与**字符串字面量** —— 最后
    一项是本门禁相对 ``test_coverage_matrix.symbol_exists`` 的扩展: 星表列名表是
    巨型字典字面量 (``"ps1_rpsf_corr"``), 它们不是任何绑定名, 却恰恰是 E3 断言
    最需要指到的那种代码。
    """
    if path.suffix in HEADING_ANCHOR_SUFFIXES:
        return heading_lines(path, symbol)               # 知识面锚点: 小节标题就是它的"符号"
    if path.suffix != ".py":
        return []                                       # 未定义符号约定的后缀: 判红, 不猜
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))  # 解析源码: 注释/docstring 里的同名提及不算定义
    except (OSError, SyntaxError, UnicodeDecodeError):
        return []                                   # 读不了或语法坏即视为找不到: 解析不了不足以证明符号存在
    want = symbol[1:-1] if symbol.startswith('"') else symbol  # 带引号字面量去掉引号后按值比
    literal = symbol.startswith('"')                # 是否按字符串常量比 (否则按标识符比)
    hits: list[int] = []
    for node in ast.walk(tree):                     # 全树遍历: 符号可能定义在类体或函数体里
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if not literal and node.name == want:   # 标识符形态: 类与函数按名字比
                hits.append(node.lineno)
        elif isinstance(node, ast.Assign):          # 普通赋值: 常量型锚点走这一支
            if not literal and any(isinstance(t, ast.Name) and t.id == want for t in node.targets):
                hits.append(node.lineno)
        elif isinstance(node, ast.AnnAssign):       # 带注解赋值: 仓内大常量表几乎都是这种形态
            if not literal and isinstance(node.target, ast.Name) and node.target.id == want:
                hits.append(node.lineno)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if literal and node.value == want:      # 字面量形态: 星表列名等字符串键
                hits.append(node.lineno)
    return hits


def heading_lines(path: Path, symbol: str) -> list[int]:
    """返回 symbol 作为**标题行**出现的行号; 读不出或不是标题返回空表。

    智能体可见知识面 (``static/fragments/*.md``) 是 Markdown 小节, 没有绑定名,
    它的"符号"就是 ``##`` 标题的正文。只认标题行是刻意的: 正文里出现同一句话
    **不算**命中, 否则锚点可以退化成"文件里随便一句提及", 也就是 A8-01 那 7 处
    误指的形态。标题被改名会被本门禁判红 —— 知识面条目改名本就该牵动引用方。
    """
    want = symbol[1:-1] if symbol.startswith('"') else symbol  # 带引号字面量去引号后按值比
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []                                   # 读不出即视为没有该标题: 放行等于替它担保
    hits: list[int] = []
    for lineno, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if not stripped.startswith("#"):
            continue                                # 只认标题行, 正文提及不算
        if stripped.lstrip("#").strip() == want:
            hits.append(lineno)
    return hits


def count_lines(path: Path) -> int:
    """数文件的物理行数 (锚点范围校验用); 读不出按 0 计, 由调用方判失败。"""
    try:
        return len(io.open(path, "rb").read().decode("utf-8", "replace").splitlines())  # 按字节读再解码: 非 UTF-8 也要读得出行数
    except OSError:
        return 0                                    # 读不到即视为 0 行: 任何锚点都越界, 判红而不是静默放行


def iter_evidence(root: str):
    """逐条产出 (题号, 锚点原文) ; 题集文件缺失或 YAML 不可解析时产出解析错误。"""
    import yaml  # 局部导入: 只有真的走到读题集时才需要 yaml, 符号解析路径不依赖它

    for rel in ITEM_FILES:                          # 两份都要查 (见 ITEM_FILES 注释)
        path = Path(root) / rel
        if not path.is_file():
            yield rel, None, "题集文件不存在"
            continue
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))  # 安全加载: 题集是纯数据
        except Exception as exc:                    # noqa: BLE001 - 任何解析失败都不得静默放行
            yield rel, None, f"题集 YAML 不可解析: {type(exc).__name__}"
            continue
        for item in (data or {}).get("items") or []:
            ev = item.get("evidence") or []
            if isinstance(ev, str):
                ev = [ev]                          # 单条写成字符串是合法 YAML, 归一成列表
            for raw in ev:
                yield rel, f"{item.get('id', '?')}: {raw}", None


def knowledge_surface_problems(root: str, warnings: list[str]) -> list[str]:
    """守 ``static/fragments/`` 属 E3 被测面这条口径 (2026-10-05 用户批准), 返回违规清单。

    两档判据, 都是**硬判据** (非空即阻断):

    1. **下界**: 带知识面锚点的题数不得少于 :data:`MIN_KNOWLEDGE_ITEMS`。
       这是"纳入"的最低含义 —— 退回"一条锚点都没有"的原状 (基线 0 条) 即判红。
    2. **登记**: 每道无知识面锚点的题必须在 :data:`UNCOVERED_BY_DESIGN` 里带理由登记。
       挡住"新增题忘配知识面"与"有人把登记悄悄清空"两种退化 (铁律 5: 未签字 = FAIL)。

    **为什么是"下界 + 登记"而不是"逐题必须都有"**: 后者会把经复核成立的
    "不该落"题 (A02/E04, 论证见 docs/eval-E3-semantics.md §2.3) 判红, 而让它们
    转绿的唯一办法是往片段里硬灌条目 —— 那正是会产生第二份会漂移的副本的失败模式。
    门禁一旦逼人造假就会被人整体关掉, 那才是真正的 fail-open。

    "上界"(片段小节 × 题目覆盖率) **刻意只告警**: 该不该落需人判读, 机器不裁定。
    """
    import yaml  # 局部导入: 与 iter_evidence 同理, 只有真读到题集才需要 yaml

    # **适用前提**: 被扫的仓里必须真的有智能体可见知识面。没有它时这两档判据
    # 无从谈起 —— 拿"没有片段的仓"去问"片段覆盖够不够"只会得到一堆假红。
    # 判据级红测试里那些只验锚点可达性的最小假仓正属此类, 它们不该被这一档牵连
    # (那会让"另一条判据的用例"因无关原因变红, 证据等于零)。
    # 前提取**目录存在**而非"读到几条锚点": 目录在而锚点被清空, 恰恰是下界
    # 判据必须抓住的缺陷, 不能被这个前提顺手放过去。
    if not (Path(root) / AGENT_KNOWLEDGE_PREFIX).is_dir():
        warnings.append(
            f"知识面判据跳过: 被扫仓根下没有 {AGENT_KNOWLEDGE_PREFIX} 目录, "
            f"该仓不承载智能体可见知识面 (非 fail-open: 真仓有该目录, 判据照常生效)"
        )
        return []

    per_file: dict[str, set[str]] = {}                # 题集文件 -> 带知识面锚点的题号集合
    seen_ids: set[str] = set()                        # 题集里出现过的全部题号 (查僵尸登记用)
    for rel in ITEM_FILES:                                    # 两份题集都要过下界与登记: 只查一份等于给"改一份留一份"留后门
        path = Path(root) / rel
        if not path.is_file():
            continue                                 # 文件缺失由 iter_evidence 报, 这里不重复报
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:          # 只接"读不了/解不开"两类: 其余异常照常炸出来
            warnings.append(f"{rel}: 题集读不出, 知识面判据跳过该文件 ({type(exc).__name__})")
            continue
        hit: set[str] = set()
        for item in (data or {}).get("items") or []:
            item_id = str(item.get("id", "?"))        # 题号: 登记与下界都以它为单位
            ev = item.get("evidence") or []
            if isinstance(ev, str):
                ev = [ev]                             # 单条写成字符串是合法 YAML, 归一成列表
            seen_ids.add(item_id)
            if any(str(a).startswith(AGENT_KNOWLEDGE_PREFIX) for a in ev):
                hit.add(item_id)                      # 这道题的知识落在智能体可见面上
        per_file[rel] = hit

    if not per_file:                                 # 一份题集都没读到: 由 iter_evidence 判红, 此处不重复
        return []

    problems: list[str] = []
    for rel, hit in sorted(per_file.items()):             # 逐份题集独立判: 顺序固定便于复现
        if len(hit) < MIN_KNOWLEDGE_ITEMS:           # 第 1 档: 下界
            problems.append(
                f"{rel}: 带 {AGENT_KNOWLEDGE_PREFIX} 锚点的题只有 {len(hit)} 道, "
                f"低于下界 {MIN_KNOWLEDGE_ITEMS} —— 该知识面已列入 E3 的 S-A 被测面, "
                f"退回覆盖不足即等于把 E3 变回'只测模型先验' (docs/eval-E3-semantics.md §2)"
            )
        for item_id in sorted(set(seen_ids) - hit):    # 第 2 档: 无锚点者必须已登记
            if item_id not in UNCOVERED_BY_DESIGN:
                problems.append(
                    f"{item_id}: 无 {AGENT_KNOWLEDGE_PREFIX} 锚点, 且未在 "
                    f"UNCOVERED_BY_DESIGN 里带理由登记 —— 新增题忘了配知识面, "
                    f"或有人把登记清空了 (铁律 5: 未签字 = FAIL)"
                )
    for item_id in sorted(set(UNCOVERED_BY_DESIGN) - set(seen_ids)):   # 登记项在题集里已不存在 = 僵尸登记
        problems.append(
            f"UNCOVERED_BY_DESIGN 登记的 {item_id} 在题集里已不存在 —— "
            f"僵尸登记会让下界判据名存实亡, 请清理登记簿"
        )
    return problems


def scan(root: str = ROOT) -> tuple[list[str], list[str]]:
    """扫全部 evidence 锚点, 返回 (违规清单, 告警清单)。

    Args:
        root: 仓根。**必须是显式参数** —— 判据级测试要把缺陷注入临时目录后
            实跑本函数; 写死 ROOT 会让"门禁能否抓住该抓的"永远无法验证。

    Returns:
        ``(problems, warnings)``。``problems`` 非空即 exit 1; ``warnings`` 只打印,
        不影响退出码 (刻意不阻断: 相关性强弱与知识面分布需要人判读)。
    """
    problems: list[str] = []
    warnings: list[str] = []
    problems.extend(knowledge_surface_problems(root, warnings))  # 知识面被测面口径: 下界 + 登记 (见该函数 docstring)
    checked = 0                                     # 已校验的锚点条数, 空转门禁要靠它自证非空
    knowledge_hits = 0                              # 指向 agent 可见知识面的锚点数 (见 AGENT_KNOWLEDGE_PREFIX)
    for src_rel, raw, err in iter_evidence(root):   # 逐条锚点过判据
        if err:                                     # 题集层面的错误 (文件缺失/解析失败)
            problems.append(f"{src_rel}: {err}")
            continue
        checked += 1
        item_id, _, body = str(raw).partition(": ")  # 拆出题号与锚点原文, 报错信息要指名道姓
        parsed = parse_anchor(body)
        if parsed is None:
            problems.append(f"{item_id}: 锚点无法解析 -> {body!r}")
            continue
        rel, start, end, symbol = parsed
        if rel.startswith(AGENT_KNOWLEDGE_PREFIX):
            knowledge_hits += 1                     # 统计知识面覆盖: 见 main() 的告警口径
        target = Path(root) / rel
        if not target.is_file():                    # 第 1 档: 文件必须存在
            problems.append(f"{item_id}: 锚点文件不存在 -> {rel}")
            continue
        if start == 0:                              # 散文锚点: 只能校验到文件存在这一层
            warnings.append(f"{item_id}: 散文锚点无行号无符号, 只校验了文件存在 -> {rel}")
            continue
        total = count_lines(target)
        if not (1 <= start <= end <= total):         # 第 2 档: 行号必须在文件范围内
            problems.append(
                f"{item_id}: 行号越界 {start}-{end} (文件共 {total} 行) -> {rel}"
            )
            continue
        if not symbol:                              # 无符号段: 第 3 档无从判起
            warnings.append(f"{item_id}: 锚点无符号段, 未校验落点 -> {rel}:{start}-{end}")
            continue
        hits = symbol_lines(target, symbol)         # 第 3 档: 符号必须真实存在于该文件
        if not hits:
            problems.append(f"{item_id}: 符号不存在于文件 -> {rel}::{symbol}")
            continue
        near = [n for n in hits if start - DRIFT_TOLERANCE_LINES <= n <= end + DRIFT_TOLERANCE_LINES]
        if not near:
            # 落点偏移只**告警**不阻断, 理由见模块 docstring「为什么位置偏移不阻断」:
            # 本轮实测 src/multiband_photometry.py 被他人从 309 行扩到 440 行, 同一批
            # 符号整体下移 35~56 行而语义一字未改 —— 行距**证明不了**"指错"与"文件长
            # 大"的区别, 拿它当阻断判据等于把正常重构报成缺陷。符号存在性才是硬判据。
            warnings.append(
                f"{item_id}: 锚点位置已漂移 —— 符号 {symbol} 现位于第 "
                f"{','.join(map(str, hits))} 行, 锚点仍写 {start}-{end} "
                f"(±{DRIFT_TOLERANCE_LINES} 行容差), 改这一处即可复位 -> {rel}"
            )
    if checked == 0:                                # 一条都没读到 = 题集读空了, 那是失败不是通过
        problems.append("未读到任何 evidence 锚点 (题集是否为空或结构已变)")
    warnings.append(
        f"知识面分布: {knowledge_hits}/{checked} 条锚点指向 {AGENT_KNOWLEDGE_PREFIX}"
        " (E3 测的是'模型该不该知道', 智能体可见知识面里没有对应条目即等于没测)"
    )
    return problems, warnings


def repair_drifted_anchors(root: str = ROOT) -> tuple[int, int, list[str]]:
    """把**行号漂移**的锚点按实测落点整体平移, 就地写回题集 (--fix 的实现)。

    为什么需要它: 落点偏移只告警不阻断 (理由见 :func:`scan` 内的注释), 于是每轮编辑都在
    往上叠 —— 实测一度积到 **91 条 WARN**, 其中 70 条集中在同一个文件, 且前 5 条偏移量
    **恰为 +62 行**, 即"一次 62 行插入把整块内容推下去"被算成了 70 个独立缺陷。
    能力本来就在 (符号落点算得出来), 缺的只是把它接回题集的动作。

    平移而非重算区间长度: 锚点写的是"这一段讲这件事"的范围, 文档里那一段的**行数**
    没变 (只是整体下移), 所以按 ``delta = 实际落点 - 原 start`` 整体平移是最忠实的复位。
    取 ``hits`` 的**最小值**作落点: 同一符号在文件里出现多次时取最靠前那个, 与
    :func:`symbol_lines` 的命中集合一致, 避免把锚点推到文件尾���去。

    只动**行号**, 不动符号段与文件路径 —— 符号不存在属于硬违规 (problems), 那不是
    漂移, 不在本函数射程内, 也不该被"修复"掩盖。

    两份题集 (``items.yaml`` 与 ``items_real.yaml``) 都改: 它们本就是同内容副本
    (:data:`ITEM_FILES` 的注释解释了为什么两份都要过门禁), 只改一份等于让漂移在
    副本里继续存在 —— 而门禁会同时扫两份, 于是改完仍报 WARN。

    Args:
        root: 仓根。

    Returns:
        ``(修复条数, 扫描到的锚点总数, 人可读的动作清单)``。
    """
    fixed = 0                                               # 实际复位条数: 与 seen 的比值就是"漂移有多普遍"的度量
    seen = 0                                                # 扫到的带行号锚点总数 (散文锚点不计入: 无从复位)
    touched: list[str] = []                                 # 人可读动作清单: 改了什么必须打印出来, 不做静默改写
    for rel_item in ITEM_FILES:                      # 两份题集逐份改: 见 docstring 的理由
        items = Path(root) / rel_item
        if not items.is_file():
            continue
        raw = items.read_bytes()                    # 按字节读: 保住原行尾 (下面按 newline="" 回写时才能原样落回)
        text = raw.decode("utf-8")
        original = text
        for line in text.splitlines():               # 逐行处理: 锚点写在 evidence 列表项里, 一行一条
            match = ANCHOR_LINE_RE.search(line)
            if not match:
                continue
            seen += 1
            rel = match.group("rel")
            start, end = int(match.group("start")), int(match.group("end"))
            symbol = match.group("sym")
            target = Path(root) / rel
            if not target.is_file():
                continue                              # 文件不存在是硬违规, 那是 problems 不是漂移
            hits = symbol_lines(target, symbol)
            if not hits:
                continue                              # 符号不存在是硬违规, 不该被 --fix 掩盖
            if any(start - DRIFT_TOLERANCE_LINES <= n <= end + DRIFT_TOLERANCE_LINES for n in hits):
                continue                              # 已在容差内: 不动
            delta = min(hits) - start                # 取最靠前的落点, 平移整段
            new_start, new_end = start + delta, end + delta
            text = text.replace(line, line.replace(f"{rel}:{start}-{end}", f"{rel}:{new_start}-{new_end}"), 1)
            fixed += 1
            touched.append(f"{rel_item} {rel}:{start}-{end} -> {new_start}-{new_end} (delta {delta:+d})")
        if text != original:                         # 本份题集真的被改过才回写, 避免无谓地重写文件
            # 按字节回写而不是 write_text: 后者在 Windows 上会把 LF 翻译成 CRLF,
            # 把一次 68 行的行号复位变成整个文件 1141 行的行尾变更 (实测踩过)。
            # 本仓 .gitattributes 统一按 LF 收, 混进 CRLF 等于给 diff 灌水。
            items.write_bytes(text.encode("utf-8"))
    return fixed, seen, touched


def main(argv: list[str] | None = None) -> int:
    """入口: 扫 E3 全部 evidence 锚点, 有违规即非零 (硬门禁退出码契约)。

    Args:
        argv: 可选命令行; 带 ``--fix`` 时先按实测落点复位漂移的锚点再扫描。

    返回: int —— 0 = 干净, 1 = 有违规。本门禁**必须**阻断: 锚点是 E3 事实基座的
    指针, 指针失准而无人拦截, 等于 36 道题里有若干道在给一个不存在的事实判分。
    """
    args = list(sys.argv[1:] if argv is None else argv)  # 默认读真命令行, 传参则用传入的 (测试用)
    if "--fix" in args:                              # 复位模式: 先改题集再扫描, 让人立刻看到修完的样子
        fixed, seen, touched = repair_drifted_anchors(ROOT)
        print(f"--fix: 按实测落点复位 {fixed}/{seen} 条漂移锚点")
        for item in touched:
            print("  ", item)
        if not fixed:
            print("   (无漂移可复位)")
    problems, warnings = scan(ROOT)  # 复位之后再扫: 让这次运行的输出就是"修完的样子"
    for w in warnings:                              # 告警先打: 违规为零时这些就是本次全部产出
        print("WARN:", w)
    if not problems:                                # 干净时也要报条数: 空转门禁比没有门禁更危险
        if warnings:  # 存在非阻断漂移告警时显式披露条数
            print(f"evidence 锚点全部可达 (披露 {len(warnings)} 处非阻断性位置漂移) (A8-01 通过)")  # 区分无告警与带告警通过
        else:  # 零告警与零问题时的经典输出
            print("evidence 锚点全部可达且符号落点有效 (A8-01 通过)")  # 完美全达通过
        return 0
    print(f"发现 {len(problems)} 处 evidence 锚点问题 (E3 证据指针失准):")
    for p in problems:                              # 逐条不截断: 门禁红时要能直接定位
        print(" -", p)
    return 1                                        # 阻断: 恒返回 0 的门禁挡不住任何东西


if __name__ == "__main__":
    raise SystemExit(main())                        # 退出码契约: 0 干净 / 1 有违规
