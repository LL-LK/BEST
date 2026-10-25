"""comment_audit.py — 注释规范全套体检 (比 docstring_lang 更严)。

回答十个问题:
  Q1 每个 class/function/method 是否都有 docstring (缺失即违规, 不看语言);
  Q2 每个 import 语句上方/本行是否有中文说明 (覆盖不足即违规);
  Q3 docstring 是否全中文 (CJK 判定);
  Q4 注释质量红旗: 空 docstring、纯标点 docstring、与函数名重复的废话 docstring、
     注释行重复粘贴 (同一注释在同一文件出现 >=3 次)、TODO/FIXME 未登记;
  Q5 **模块头注释**: 每个文件开头的模块级 docstring 必须存在、必须含中文、
     且长度 >= HEADER_MIN_CHARS (对应"每个文件开头都有整个文件的详细注释"的要求
     — 详见 ops/audit/README.md 的注释密度标准);
  Q6 **注释密度**: 注释行数 / 净代码行 >= DENSITY_FLOOR (对应"每一行代码都有
     对应注释"的要求)。净代码行 < DENSITY_MIN_NET 的小文件 (多为空的
     __init__.py) 不判密度, 噪声大于收益;
  Q7 **行尾注释占比**: 行尾注释行 / 净代码行 >= TRAILING_FLOOR —— 落实
     "代码在左边、注释在右边": **语句级**注释一律写在代码同一行的行尾, 只有
     文件头/成组说明留在代码上方;
  Q8 **行尾注释间距**: 行尾注释与代码之间至少留 TRAILING_GAP 个空格
     (PEP 8 的两空格), 且同一块内建议对齐成列;
  Q9 **注释引用的仓内路径是否真实存在**: 注释与 docstring 里以仓内顶级目录
     开头的路径, 从「仓根 / 本文件所在目录 / 其父目录」三处都解析不到即判缺失
     —— 前八项检查 (Q1 到 Q8) 全部管「注释写没写」, Q9 是唯一管「注释说的是不是
     真的」的一条;
  Q10 **逐行对照率**: 非平凡语句里带行尾注释的比例 >= ALIGN_FLOOR
     —— 诉求「尽量一行对一行、左右对照」的可判定形式; 样板行/数据行不进分母,
     十一类排除口径的清单与逐项理由见 `ops/audit/line_scope.py` 的模块头 (行分类层
     已拆出, 分母只经 :func:`line_scope.nontrivial_stmt_rows` 取得)。

Q5–Q8 的阈值取自全仓实测分位 (254 个 .py: 模块头 p10=156 字符、注释密度
p25=0.083、行尾占比 p25=0.093), 刻意卡在分位线下方一点 —— 目标是"消灭尾巴",
不是逼出注水。

职责: 一处回答"这个仓库的注释写没写好" —— 十五类违规 (缺 docstring / import 无
  中文说明 / docstring 非中文 / 废话与重复注释 / 模块头单薄 / 注释密度不足 /
  行尾占比不足 / 行尾间距不足) 一次扫完, 写 JSON 产物 + 人类可读清单。度量对象
  是 AST 定义节点、tokenize 出的注释 token 与模块 docstring 字符数, 不看注释
  "写得对不对" (那由 verify_doc_consistency 管)。
所属子系统: 仓库治理层 ops/audit/ 的**硬门禁** (接在 make audit 上), 它是注释
  体系的 SSOT —— Q5–Q8 四个阈值、净代码行口径、豁免登记簿都以本文件为准,
  comment_audit 自己也在被扫描范围内 (自指是刻意的: 注释规范的工具不能豁免)。
  上游无代码依赖; 下游是 ops/audit/README.md 的口径说明与逐文件整改。
对外接口: main() -> int (十五类计数任一非 0 即 1); analyse_docstrings /
  analyse_module_header / analyse_inline_density / analyse_trailing_style /
  analyse_imports / analyse_comments / analyse_line_alignment /
  analyse_referenced_paths / net_code_lines / count_comments / comment_tokens
  是可依赖的 seam —— 单元测试 test/unit/meta/test_audit_gate_contracts.py 直接
  import 本文件调它们, 既验判据行为、也用它锁住判据本身不被改坏 (判据一松动,
  整改就会朝反方向做 —— 例如把上方缩进注释误当成行尾时, 指标立刻失真)。行分类层
  (十一类排除口径) 已拆到同目录 line_scope.py,
  它的 seam 是 nontrivial_stmt_rows —— Q10 分母只此一个来源, 消费方直接从
  line_scope 取, 不经本文件转手 (本文件只 import 自己用得到的三个符号)。
依赖与数据流: 输入 = 共享扫描面 (同目录 scan_roots.iter_py_files) 给出的全量 .py 的
  原始字节 (一次读盘, 同时喂给
  tokenize 与 ast); 输出 temp/comment_audit.json + stdout 清单。temp/ 是
  gitignored 的一次性目录, 产物不进版本库。
关键契约与不变量: 退出码口径是"十五类计数是否全 0", 任一非 0 即失败 —— 铁律 5
  禁 fail-open, 所以不存在"扫不到就当干净"的路径; 净代码行口径必须与
  count_code_lines.py 完全一致, 否则"加注释拉高密度"会反过来顶破 400 行预算,
  两个门禁会互相逼死; DIRECTIVE 白名单必须先于重复判定, 否则分隔线与 noqa
  会被当成"重复粘贴的注释"刷屏 —— Q7/Q8 的计数同样先剔 DIRECTIVE, 否则一堆
  `# noqa: E402` 就能把行尾占比刷上去, 指标随即失去意义。
陷阱与边界: 注释计数走 tokenize 而不是正则, 因为字符串字面量里的 '#' 会被正则
  误计 —— 一次 JSON 模板字符串就能凭空造出几条注释, 让密度假性达标; Q7 的行尾
  判据是"同一行 # 左侧有代码", **不是**"缩进非零" —— 后者会把顶在代码上方的
  缩进注释一并算成行尾, 于是"保持缩进就能刷满占比", 门禁度量错了对象而毫无
  察觉 (该判据已由
  test_audit_gate_contracts.py::TestTrailingCommentCriterion 钉死); 密度豁免
  登记簿 DENSITY_EXEMPT 允许登记理由后放行, 但**无理由不许豁免**, 加条目等于
  公开承认某文件补不动, 这正是把它做成显式常量而非环境变量的原因; Q6 与 Q7
  是两个**互补**指标 —— Q6 管"有没有注释", Q7 管"注释写在哪", 两者同时低才是
  真的没写, 只低一个通常说明注释位置摆错了。
"""
from __future__ import annotations

import ast
import io
import json
import os
import re
import tokenize
from pathlib import Path

# 本地: Q10 分母的行分类层 (十一类排除口径)。同目录兄弟模块, 按同目录裸名导入 ——
# 本文件既可能被 `python ops/audit/comment_audit.py` 直跑 (此时 sys.path[0] 就是
# ops/audit/), 也可能被单测注入 AUDIT_DIR 后 `import comment_audit` 拉起 (两种情况
# 同目录都在 path 上); 走 `ops.audit.` 包路径反而会在直跑时 ModuleNotFoundError。
# 只导入本文件真用到的三个: docstring_rows 被 Q5 模块头检查用, _continuation_flags
# 被 import 分组检查用, nontrivial_stmt_rows 是 Q10 分母的唯一来源。其余分类函数在
# 拆分后本文件一处也不调 —— 需要它们的消费方直接从 line_scope 导入, 别在这里转手。
from line_scope import (  # noqa: E402  拆分后新增: 行分类层在同目录, 放在 pathlib 之后
    _continuation_flags,
    docstring_rows,
    nontrivial_stmt_rows,
)

# 本地: 扫描面 (哪些 .py 进门禁) 的唯一真源。同目录兄弟模块, 按同目录裸名导入, 理由
# 与上面一行相同。覆盖面**不写在本文件**: 2026-10-05 判据审计 D5-01 实测, 目录白名单
# 漏掉 agents/ 时那一片的注释问题全门禁判绿, 且同款白名单被四道门禁各抄一份。
from scan_roots import iter_py_files  # noqa: E402  同目录裸名导入, 与 line_scope 同理

# skill 根定位: 本文件位于 ops/audit/, 上溯两级即仓库根 —— 相对定位, 换机 /
# 换克隆目录都能跑 (硬编码绝对路径的脚本一换机就失效)
ROOT = str(Path(__file__).resolve().parents[2])  # resolve 先消软链: 经软链调用时 parents 才指向真实根
# 产物落 temp/ (gitignored 的一次性目录), 不进版本库 —— 报告型工具的产物不该被门禁盯上
OUT = os.path.join(ROOT, "temp", "comment_audit.json")                               # 报告落 temp/: gitignored, 不进版本库也不污染树清单
# 扫描面 (哪些 .py 进门禁) 不在本文件声明: 唯一真源是同目录 scan_roots.iter_py_files
CJK = re.compile(r"[\u4e00-\u9fff]")                                               # CJK 统一表意文字区间: 中日韩表意文字区, 比逐字列表省事且覆盖常用字
# 常见"废话 docstring": 只含功能词的堆砌, 无信息量
FLUFF = re.compile(                                                                   # 灌水 docstring 的形态表: 名字类与职责类都算"没写内容"
    r"^(?:do|handle|process|run|main|helper|utility|util|function|method|class|"
    r"执行|处理|运行|主函数|辅助|工具|函数|方法|类)[\s._:：-]*$",
    re.IGNORECASE,                                                                        # IGNORECASE: "Run"/"run" 是同一种灌水
)
# 待办标记的正则: 只认 "#" 紧跟标记的形态, 免得把正文里讨论这些词的句子
# (比如本文件自己的模块 docstring) 判成未登记待办
TODO_RE = re.compile(r"#\s*(TODO|FIXME|XXX|HACK)\b")                                # 只认 "#" 紧跟标记: 正文里讨论 TODO 这类词不该被当成待办标记
# Q5 阈值: 模块级 docstring 的字符数下限 (实测 p10=156, 取 160 留一点余量)
HEADER_MIN_CHARS = 160  # 实测 p10=156, 留 4 字符余量防边界抖动
# Q6 阈值: 注释行数 / 净代码行 的下限 (实测 p25=0.083, 取 0.10)
DENSITY_FLOOR = 0.10  # 实测 p25=0.083, 卡在其下: 目标是消灭尾巴
# 净代码行不足此值不判密度: 空 __init__.py / 极小 shim 判了纯噪声
DENSITY_MIN_NET = 15                                                                          # 小文件不判密度: 三行函数加两条注释就能凑出假高密度
# 密度豁免登记簿: 路径 -> 豁免理由 (无理由不许豁免, 铁律 5 禁 fail-open)
DENSITY_EXEMPT: dict[str, str] = {}  # 无理由不许豁免: 加条目等于承认某文件补不动
# Q7 阈值: 行尾注释行数 / 净代码行 的下限 (实测 p25=0.093, 取 0.10)
TRAILING_FLOOR = 0.10  # 行尾占比下限: 低于它说明注释全顶在代码上方
# Q8 阈值: 行尾注释与代码之间的最小空格数 (PEP 8 的两空格; 0 = 贴太紧难读)
TRAILING_GAP = 2  # PEP 8 两空格; 设 0 等于允许贴着写

# --- Q10: 「一行对一行、左右对照」的逐行口径 ----------------------------------
# Q7 算的是「行尾注释行 / 净代码行」, 口径偏粗: 它把**样板行**(import / return /
# 收尾括号)与**数据行**(星表列名列表、指标定义表)也算进分母, 于是"给列名逐行写
# 右注"也能把指标刷上去 —— 那是注水, 不是对照。
#
# Q10 换一个口径: 分母只留**非平凡语句** —— 样板行与数据行都剔除, 数据行由所在
# 数据块**块首那一行**的右注覆盖即可(块内逐行写等于把列名复述一遍)。
# 这才是诉求「代码注释尽量一行对一行, 左右对照, 而不是上下代码注释」的可判定形式。
ALIGN_FLOOR = 0.70  # 逐行对照率下限。起步设 0.45 只是"不倒退"的护栏, 整改完成后
#                     已于 2026-10-03 上提到 0.70: 当时全仓无一个文件低于该值, 而
#                     0.45 对 0.98 的现状毫无约束力。再加一类判据时可考虑提到 0.80。
ALIGN_MIN_NET = 15  # 与 DENSITY_MIN_NET 同口径: 小文件不判对照率, 3 行文件上算比例没有意义

# --- Q9: 注释里引用的仓内路径必须真的存在 -------------------------------------
# Q9 存在的理由: 结构性检查 (Q1-Q8) 全部管「注释写没写」,
# 没有一条管「注释说的是不是真的」, 于是形如 docs/eval-E1-nl-to-tool.md (真名是
# eval-E1-nl2tool.md) 的悬空引用能在两门禁全绿时长期存活 —— 按注释去找会扑空, 或更糟:
# 落到一个真实存在但完全无关的文件上 (evals/test-scenarios.yaml 就是 25 条行为场景表)。
#
# 只扫仓内真实顶级目录: pybest/ _shared/ bridge/ scripts/ astro-best/ 这类是
# **历史或外部**引用 (旧包名、母仓 skill、运行时产物), 刻意不查 —— 查了必然全红,
# 而把它们塞进白名单只会掩盖新问题。
RE_PATH_IN_COMMENT = re.compile(                                                                    # 路径正则: 只认以仓内顶级目录开头的形态
    r"\b((?:src|evals|ops|test|docs|rag|templates|contracts|examples|references)/"
    r"[A-Za-z0-9_./-]+\.(?:py|md|yaml|yml|json|toml|txt|ps1|ini|cfg|drawio))\b")
# 注释里已如实标注「这东西没了/不存在/只是示例」时, 门禁不重复报 —— 那种注释恰恰
# 是**正确**的 (如实登记失效锚点), 再报它等于逼人把实话删掉。代价是可被
# 「加个词就绕过」, 这是有意取舍, 已写进 ops/audit/README.md 的已知局限。
_PATH_RETIRED_HINTS = ("不存在", "已删除", "已随", "已移除", "已下线", "示例", "例如", "形如")
# 形如 x.py / xxx.py / a/b/c.json / *.py 这类**举例**不是引用
_PATH_IS_PLACEHOLDER = re.compile(r"(?:^|/)(?:x|xxx|\.\.\.|\*|[abc])\.[a-z]+$")  # 占位符形态: x.py / xxx.py / a/b/c.json / *.py 是举例不是引用
# 指令/分隔线白名单: 这些注释在同一文件重复出现是正常且必须的
DIRECTIVE = re.compile(  # 白名单必须先于重复判定: 否则 noqa 会刷屏
    r"^\s*#\s*($"
    r"|[-=~*#/_ ]{3,}"          # 分隔线
    r"|[\u2500-\u257f]{3,}"     # 制表符风格分隔线
    r"|!.*"                     # shebang
    r"|noqa"
    r"|pragma:\s"
    r"|legacy-import-guard"
    r"|type:\s"
    r"|pylint:"
    r"|mypy:"
    r"|fmt:\s"
    r"|nosec"
    r")"
)


def _has_cjk(text: str) -> bool:  # 空串/None 兜 False: 缺 docstring 另由 Q1 报
    """判定文本是否含中文字符 (CJK 统一表意文字区间)。"""
    return bool(CJK.search(text or ""))  # or 兜住 None: 调用方会拿未取到的 docstring 直接问


def comment_tokens(raw: bytes) -> list[tokenize.TokenInfo]:
    """返回全部注释 token (一次 tokenize 供 Q4/Q6/Q7/Q8 共用, 避免重复解析)。

    解析不了时返回空列表: 报不出来的文件走 ``unparseable`` 那一路, 在这里
    连带抛异常只会打断整轮扫描 (铁律 5 要的是"红", 由红的那一路负责红)。
    """
    try:
        return [tok for tok in tokenize.tokenize(io.BytesIO(raw).readline)
                if tok.type == tokenize.COMMENT]                            # 只要 COMMENT token: 字符串里的 # 不算, tokenize 已正确区分
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return []


def count_comments(raw: bytes) -> int:
    """统计真正的注释 token 行数 (字符串字面量里的 '#' 不算, 需 tokenize)。

    必须吃原始字节而不是已解码的文本: tokenize 需要走 BytesIO 才能正确识别
    编码声明行, 而编码声明本身就是一条真实注释, 漏掉它阈值就偏了一线。
    """
    return len(comment_tokens(raw))


def analyse_docstrings(rel: str, tree: ast.AST) -> list[dict]:
    """AST 遍历, 找出所有缺 docstring 的定义与 docstring 不含中文的定义。

    作用: 遍历全部定义节点, 判定"有没有 docstring"与"docstring 里有没有中文"。
    关键输入是已解析的 AST (由 main 只解析一次后共用), 不再各自 parse。
    返回: list[dict] —— 每条带 kind/name/line; 节点无 docstring 时不再继续
    判中文 (缺失比非中文更根本, 两条一起报是噪声)。
    """
    findings: list[dict] = []                                                                # findings 累积而非首错即退: 一轮跑批要报全量
    for node in ast.walk(tree):                                                                     # 全树遍历
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):                 # 三类可挂 docstring 的定义
            doc = ast.get_docstring(node, clean=True)                                       # clean=True: 判定「是不是中文」不该被缩进影响
            name = getattr(node, "name", "<lambda>")  # clean=True 归一缩进: 长度按字符算, 不受排版影响
            # 属性/魔术方法允许极短 docstring, 但仍必须有
            if doc is None:  # 缺失优先于非中文: 缺 docstring 是更根本的问题
                findings.append(                                                                    # 缺 docstring 一条
                    {"kind": "missing_docstring", "name": name, "line": node.lineno,
                     "node": type(node).__name__}
                )
                continue
            if not _has_cjk(doc):  # 长但全英文同样报: 读者并没拿到中文说明
                findings.append(                                                                    # 非中文一条
                    {"kind": "docstring_not_chinese", "name": name, "line": node.lineno,
                     "node": type(node).__name__, "text": doc[:80]}
                )
                continue
            # 两类红旗都放在"有中文"之后判: 一条纯英文的废话 docstring 报
            # docstring_not_chinese 更有指向性, 再报一遍 fluff 是噪声
            if not doc.strip() or FLUFF.match(doc.strip()):  # 两类红旗二选一: 同一条 docstring 只报更具体的
                findings.append(                                                                    # 灌水一条
                    {"kind": "fluff_docstring", "name": name, "line": node.lineno,
                     "node": type(node).__name__, "text": doc[:80]}
                )
    return findings


def analyse_module_header(rel: str, tree: ast.AST) -> list[dict]:
    """Q5: 模块头 docstring 必须存在、必须含中文、且长度达 HEADER_MIN_CHARS。

    判据说明: 用 ``clean=True`` 取值 (缩进归一), 长度按字符计; 缺中文单列一种
    kind, 便于读者一眼分辨"没写"与"写了但没写中文"。
    """
    doc = ast.get_docstring(tree, clean=True) or ""  # or 兜 None: 缺 docstring 时下面还要 .strip()
    # 缺失与单薄分开报: 缺 docstring 是"根本没写", 两者整改动作完全不同
    if not doc.strip():  # 缺失与单薄分开报: 两种整改动作完全不同
        return [{"kind": "module_header_missing", "name": rel, "line": 0,
                 "detail": "文件开头没有模块级 docstring"}]
    findings: list[dict] = []                                                                       # 模块头 findings
    if len(doc) < HEADER_MIN_CHARS:  # 只比长度: 中文与否交给下面独立一条检查
        findings.append({                                                                     # 缺模块头: 报在第 0 行, 文件级问题没有精确行号
            "kind": "module_header_thin", "name": rel, "line": 1,
            "detail": f"{len(doc)} 字符 < {HEADER_MIN_CHARS}",
        })
    # 有中文检查放在长度检查之后且独立成 kind: 只报"单薄"会漏掉"长但全英文"
    # 的文件, 而后者同样是"没给读者任何中文说明"
    if not _has_cjk(doc):  # 独立成条而非并入上面: 只报单薄会漏掉全英文
        findings.append({                                                                           # 过薄/无中文: 两条都指向文件头
            "kind": "module_header_not_chinese", "name": rel, "line": 1,
            "detail": "模块头无中文说明",
        })
    return findings


def net_code_lines(tree: ast.AST, lines: list[str]) -> int:
    """净代码行 = 物理行 - 空行 - 纯注释行 - docstring 行 (Q6/Q7 共用分母)。

    口径必须与 ``count_code_lines.py`` 一致: 两个门禁用同一个分母, "加注释"
    才只会抬高分子, 不会一边补注释一边把净代码行预算顶破。
    """
    docs = docstring_rows(tree)  # 行号集合一次算出, 下面每行 O(1) 查
    net = 0                                                                                         # 净行从零累加
    for idx, line in enumerate(lines, start=1):                                                     # 行号从 1 起: 与报告里的行号口径一致
        # 三类非代码行: docstring 行 (靠行号, 缩进续行认不出来)、空行、纯注释行
        if idx in docs or not line.strip() or line.strip().startswith("#"):  # 三类非代码行一次判掉; docstring 缩进续行靠行号认
            continue
        net += 1                                                                                    # 每行只判一次
    return net


def analyse_inline_density(rel: str, tree: ast.AST, lines: list[str], comments: int) -> list[dict]:
    """Q6: 注释密度 (注释行 / 净代码行) 不得低于 DENSITY_FLOOR。

    小文件 (net < DENSITY_MIN_NET) 与已登记豁免项不判 —— 空的 __init__.py
    判了纯噪声, 加条目豁免等于公开承认某文件补不动。
    """
    if DENSITY_EXEMPT.get(rel):                                                              # 已登记豁免优先: 豁免是显式决策, 不能被密度反证推翻
        return []  # 已登记豁免 (豁免必须带理由, 见 DENSITY_EXEMPT 定义处)
    net = net_code_lines(tree, lines)                               # 复用 net_code_lines: 与 count_code_lines 同源, 两门禁口径才不会打架
    if net < DENSITY_MIN_NET:  # 小文件不判密度: 判了噪声大于收益
        return []
    density = comments / net  # 分子注释数除以分母净行: 加注释只抬分子
    if density < DENSITY_FLOOR:                                                                     # 低于下限才报
        return [{
            "kind": "inline_comment_density_low", "name": rel, "line": 0,
            "detail": f"{comments}/{net} = {density:.2f} < {DENSITY_FLOOR}",
        }]
    return []


def analyse_trailing_style(
    rel: str, tree: ast.AST, lines: list[str], tokens: list[tokenize.TokenInfo],                    # Q7/Q8 的入参
) -> list[dict]:
    """Q7/Q8: 语句级注释应写在**代码右侧**的行尾, 且与代码至少隔两个空格。

    判据: 行尾 = 同一行 ``#`` **左侧有代码**, 即
    ``lines[行号-1][:起始列].strip()`` 非空。
    ⚠️ 判据不可换成「COMMENT token 起始列 > 0」: 后者会把**任何缩进的独立注释
    行**都算成行尾 —— 函数体里那种顶在代码上方的 ``    # 说明`` 恰好满足
    col>0, 于是指标能被"把上方注释保持缩进"一路刷高, 而那恰恰是本标准要反对的
    形态; 按严格口径实测, 226 个文件里有 154 个真实行尾注释为 0 —— 门禁度量错了
    对象, 整改就白做。一行注释只有在它左边真的站着代码时才算"注释在右"。该判据
    现由 ``test/unit/meta/test_audit_gate_contracts.py::TestTrailingCommentCriterion``
    的反例样本钉死, 防止再退化。

    DIRECTIVE 白名单 (noqa / type: ignore / 分隔线) 一律不计 —— 否则一堆
    ``# noqa: E402`` 就能把行尾占比刷上去, 指标随即失去意义 (与 Q4 同理由)。

    占比低于 TRAILING_FLOOR 报 Q7; 间距不足 TRAILING_GAP 报 Q8 (逐行报, 带行号)。
    """
    findings: list[dict] = []                                                                       # findings 累积
    real = [t for t in tokens if not DIRECTIVE.match(t.string)]  # 先剔指令: 一堆 noqa 就能把行尾占比刷上去
    # 左邻代码非空才算行尾 (见上方 docstring 的判据修正说明)
    trailing = [t for t in real                                                                     # 真行尾 = 同行 # 左侧有代码
                if lines[t.start[0] - 1][:t.start[1]].strip()]                                   # 左侧只有空白的是"上方缩进注释", 不计入占比
    for tok in trailing:                       # Q8: 行尾注释与代码的间距
        head = lines[tok.start[0] - 1][:tok.start[1]]                                               # 取 # 之前的代码部分
        gap = len(head) - len(head.rstrip(" \t"))
        if gap < TRAILING_GAP:                                                                      # 少于两空格即违反 PEP 8
            findings.append({                                                                       # Q8 逐行报
                "kind": "trailing_comment_spacing", "name": rel,
                "line": tok.start[0],
                "detail": f"行尾注释前只有 {gap} 个空格 (< {TRAILING_GAP})",
            })
    net = net_code_lines(tree, lines)           # Q7: 行尾占比
    if net < DENSITY_MIN_NET or DENSITY_EXEMPT.get(rel):                                            # 小文件与已豁免不判 Q7
        return findings
    ratio = len(trailing) / net  # 分子分母都剔过 DIRECTIVE: 指标不被撑起来
    if ratio < TRAILING_FLOOR:   # 只判下限不判上限: 满屏注释同样是坏形态
        findings.append({                                                                           # Q7 报文件级
            "kind": "trailing_comment_ratio_low", "name": rel, "line": 0,
            "detail": f"{len(trailing)}/{net} = {ratio:.2f} < {TRAILING_FLOOR} "
                      f"(语句级注释应写成代码右侧的行尾, 而不是上方独立行)",
        })
    return findings


def string_literal_lines(raw: bytes) -> set[int]:
    """返回**多行字符串字面量内部**的行号集合 (1 基)。

    用途: import 组检查要把"字符串内容里的 import"与"真 import 语句"分开。
    ``comment_tokens`` 只留 COMMENT token (那是 Q4/Q6/Q7/Q8 的正确口径), 里面
    已经没有 STRING token 了, 所以这里单独走一趟 tokenize 只取字符串行。

    解析不了时返回空集: 退化成旧行为 (把字符串内的行也算成 import), 那会多报
    不会漏报 —— 误报方向是安全的, 与 ``comment_tokens`` 的兜底同一取向。
    """
    lines_in: set[int] = set()
    try:
        for tok in tokenize.tokenize(io.BytesIO(raw).readline):
            if tok.type == tokenize.STRING and tok.end[0] > tok.start[0]:  # 跨行才需要标记
                lines_in.update(range(tok.start[0], tok.end[0]))           # 起点行到终点行之间全是内容
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return set()                                                      # 兜底空集: 退化到旧口径, 不引入漏报
    return lines_in


def analyse_imports(rel: str, lines: list[str], str_lines: set[int] | None = None) -> list[dict]:
    """按「import 组」判定中文说明覆盖 (组内任一行或组尾注释含中文即覆盖)。

    组 = 连续的 import 语句/注释行/空行构成的最大区间, 且至少含一条 import
    (续行归属同一组)。这样一条写在 import 块上方的中文组注释即可覆盖整个块,
    与"import 组全覆盖"的规则口径一致。

    **多行字符串里的 import 不算 import**: 本仓的判据级测试会把待检形态**当样本
    原文抄进三引号字符串** (阳性对照就是这种形态)。tokenize 能分清"这行是语句"
    与"这行只是字符串里的一段文字", 纯文本扫描分不清 —— 缺了这一层, 门禁会去要求
    给一个字符串里的英文 import 配中文说明, 那不是质量问题而是扫描口径漏洞。
    这层只**排除字符串内部的行**, 不放宽任何真实 import 的判据。

    参数 rel 只用于报告里的文件名字段; lines 是待判定的物理行; str_lines 是多行
    字符串内部的行号集合 (1 基, 缺省 None = 不排除, 保持旧行为)。
    返回: list[dict] —— 缺中文说明的 import 一条一条列出来, 便于逐条补。
    """
    findings: list[dict] = []                                                                       # import 组 findings
    total = 0                                                                                       # 组数从零累加
    covered = 0                                                                                     # 已覆盖的 import 数
    continuation = _continuation_flags(lines)  # 续行先标好: 否则多行 import 被拆组而虚报
    in_string: set[int] = str_lines or set()  # 字符串内部行号: 那类行不是 import 语句 (见 docstring 末段)
    n = len(lines)                                                                                  # 行数上限
    idx = 0                                                                                         # 扫描游标
    while idx < n:                                                                                  # 外层循环逐行推进
        if (idx + 1) in in_string:                                                                   # 该行整行落在多行字符串里
            idx += 1                                                                                # 跳过: 它是字符串内容, 不是 import
            continue
        stripped = lines[idx].strip()                                                               # 去空白后判断
        if not stripped.startswith(("import ", "from ")):
            idx += 1                                                                                # 消费当前行后前移
            continue
        start = idx                                                                          # 回看起点: import 组要连同上方的中文说明一起算
        # 向上并入紧邻的注释/空行, 好让组上方的说明注释落进组内参与覆盖判定
        while start > 0:                                                                            # 向上回溯直到非 import 行
            prev = lines[start - 1].strip()                                                         # 上一行内容
            if prev == "" or prev.startswith("#"):
                start -= 1                                                                          # 继续上移
            else:  # 并入上方注释与空行: 组注释才落进组内参与覆盖
                break
        end = idx                                                                                   # 组的结束下标
        # 向下并入续行与后续注释/空行, 直到遇到非 import 的实代码
        while end + 1 < n:                                                                   # 向后并进续行: 多行 import 的括号内容都算组内
            if continuation[end + 1]:                                                               # 续行则继续
                end += 1                                                                            # 下标推进
                continue
            nxt = lines[end + 1].strip()                                                            # 下一行内容
            if nxt == "" or nxt.startswith("#") or nxt.startswith(("import ", "from ")):  # 向下并入到遇见实代码为止, 组才是最大连续区间
                end += 1                                                                            # 再前进一位
            else:
                break
        block = lines[start:end + 1]                                                               # 整块取出来: 交给下一步判断是否带中文说明
        imports_here = [                                                                          # 本组的 import 行 (行号 + 原文)
            (start + off + 1, ln.strip())                                                           # 偏移量换算成绝对行号
            for off, ln in enumerate(block)                                                         # 逐行取原文
            if ln.strip().startswith(("import ", "from "))
               and not ln.strip().startswith("from __future__")
               and not ln.strip().startswith(("from .", "from .."))
        ]
        if imports_here:                                                                            # 这一组确实含 import 才算一组
            total += len(imports_here)                                                             # 组数累加: 报告里的"共 N 组"取自这里
            # 任一行含中文即整组覆盖: 追求的是"每块 import 有一句人话说明",
            # 不是逐个模块都写一行, 否则 import 块会被注释淹没
            if any(_has_cjk(ln) for ln in block):  # 任一行有中文即整组覆盖: 追求一句人话, 不是逐模块一行
                covered += len(imports_here)                                                        # 有中文说明的 import 数
            else:
                for lineno, text in imports_here:                                                   # 逐条判定是否带中文说明
                    findings.append(                                                                # 缺说明的一条
                        {"kind": "import_group_no_chinese_note", "name": text, "line": lineno}
                    )
        # 逐行推进而不是正则扫全文: 组是"连续区间", 正则表达不了这个跨行概念
        idx = end + 1                                                                               # 游标跳到组尾之后: 同一行不能进两组
    if total:                                                                                       # 有组才报占比, 空文件报 0/0 没意义
        print("import 组覆盖: %d/%d" % (covered, total))
    return findings


def analyse_comments(tokens: list[tokenize.TokenInfo]) -> list[dict]:
    """注释质量红旗: 重复粘贴的注释块与未登记的 TODO/FIXME。

    作用: 把注释分成"未登记待办"与"重复 ≥3 次的 ≥12 字长注释"两类发现返回。
    tokens 由调用方传入 (comment_tokens 过滤后的纯注释列表) —— 与 Q7/Q8/Q10 共用
    同一次 tokenize, 本函数既不重复解析也不重复判类型; 形参只有 tokens 一个
    (rel/raw/lines 三个形参在函数体内零引用, 不作为形参存在)。
    返回: list[dict], 可为空列表; tokens 为空 (tokenize 失败) 时返回空列表而不
    抛异常 —— 解析类失败已由 unparseable 那一路单独报, 重复报只会制造噪声。
    """
    findings: list[dict] = []                                                                       # 注释类 findings
    seen: dict[str, list[int]] = {}                                                         # 按文本聚合: 机械复制注释的特征就是"同一句话出现多次"
    for tok in tokens:                                                                              # 逐个注释 token
        # 去掉 # 与首尾空白后作为去重键: 同一句话缩进不同不该算两次
        text = tok.string.lstrip("#").strip()
        if not text:                                                                        # 空文本跳过: 分隔线在 DIRECTIVE 里已单独处理
            continue
        if TODO_RE.search(tok.string):                                                              # 待办标记
            findings.append(                                                                        # 报一条
                {"kind": "todo_in_code", "name": tok.string.strip(), "line": tok.start[0]}
            )
            continue
        if DIRECTIVE.match(tok.string):                                                    # 指令注释(分隔线/noqa 等)白名单: 它们重复是正常的
            continue  # 指令/分隔线: 重复是正常形态, 不算"重复粘贴的注释"
        if len(text) >= 12:  # 只统计有信息量的长注释, 短注释重复属正常
            seen.setdefault(text, []).append(tok.start[0])  # 存全部行号: 报重复时指出第一处, 便于回溯
    for text, positions in seen.items():                                                            # 逐个文本分组
        # 3 次是阈值不是 2 次: 分节横幅与样板注释天然会重复两遍, 两次即报会
        # 把正常形态全打成违规
        if len(positions) >= 3:                                                                     # 出现三次以上才报: 一两次是正常复用
            findings.append(                                                                        # 报机械复制一条
                {"kind": "duplicated_comment", "name": text[:60],
                 "line": positions[0], "count": len(positions)}
            )
    return findings


def analyse_line_alignment(rel: str, tree: ast.AST, lines: list[str],
                           tokens: list[tokenize.TokenInfo]) -> list[dict]:                         # Q10 的入参签名
    """Q10: 非平凡语句里「有右注」的比例 (一行对一行、左右对照的逐行口径)。

    与 Q7 的区别是分母: Q7 分母含样板行与数据行, 粗; Q10 分母只留非平凡语句。
    十一类排除口径 (样板行/数据行/签名行/assert/夹具/…) 由
    :func:`line_scope.nontrivial_stmt_rows` 判定, 清单与逐项理由见该模块头 ——
    本函数不再自带那份清单: 清单与实现分居两处时已经漂过一次 (此处原写
    「七类」而末尾另有一条「三类不算」, 实际已扩到十一类)。
    """
    trailing: set[int] = set()                                                                      # 真行尾行号集合
    for tok in tokens:                                                                              # 逐个注释 token
        ln, col = tok.start                                                                         # 取起始列
        if col > 0 and lines[ln - 1][:col].strip():                                                 # 同一行 # 左侧有代码才算行尾
            trailing.add(ln)                                                                        # 记进集合
    denom = nontrivial_stmt_rows(tree, lines)                                                        # 分母行号集合: 唯一来源是 line_scope
    net = len(denom)                                                                                # 分母行数即非平凡语句数
    aligned = len(denom & trailing)                                                                  # 对照数 = 分母里带行尾注释的行
    if net < ALIGN_MIN_NET:                                                                        # 小文件不判: 比例在 3 行文件上没有意义
        return []
    ratio = aligned / net                                                                           # 算比例
    if ratio >= ALIGN_FLOOR:                                                                        # 达标就不报
        return []
    return [{"kind": "line_alignment_low", "name": rel, "line": 0,
             "detail": f"逐行对照率 {ratio:.3f} < {ALIGN_FLOOR} (分母 {net} 非平凡语句)"}]


def analyse_referenced_paths(rel: str, tree: ast.AST, lines: list[str],
                             tokens: list[tokenize.TokenInfo]) -> list[dict]:                       # Q9 的入参签名
    """Q9: 注释与 docstring 引用的仓内路径必须真实存在。

    判据: 路径以仓内顶级目录开头, 且从「仓根 / 本文件所在目录 / 其父目录」三处
    都解析不到 → 判缺失 (``referenced_path_missing``)。

    两处刻意放过, 都是为了不逼人把实话删掉:
      1. 同一处注释已如实标注该路径失效 (含"不存在/已随…删除"等词) —— 那种注释
         恰恰是**正确**的, 例如登记「pybest 打包产物的 git 锚点已不在本仓历史」;
      2. ``x.py`` / ``a/b/c.json`` 这类举例形态, 以及 ``*``/``…`` 通配写法。
    局限: 放过条件可被"加个词就绕过"。取舍与白名单口径见 ops/audit/README.md。
    """
    out: list[dict] = []                                                                            # findings 列表
    here = os.path.dirname(os.path.join(ROOT, rel))                                                 # 本文件所在目录: 路径解析的第二个基准
    texts: dict[int, str] = {}                                                                      # 行号 -> 文本 的映射
    for node in ast.walk(tree):                                                                     # 全树找 docstring
        if not isinstance(node, (ast.Module, ast.ClassDef,                                          # 只认四类可挂 docstring 的节点
                                 ast.FunctionDef, ast.AsyncFunctionDef)):                           # 类型判断拆行写: 这行太长, 拆开可读
            continue
        doc = ast.get_docstring(node, clean=False)                                                  # 取原始 docstring
        if not doc or not node.body:                                                                # 没有就跳过
            continue
        # docstring 的豁免按**整段**判, 不按行: 失效标注常写在段首或另一行
        # (「该文件与 docs/plans/ 目录在本仓均不存在」与路径本身分行),
        # 按行判会把如实登记的注释误报成缺陷 —— 那是逼人把实话删掉
        if any(hint in doc for hint in _PATH_RETIRED_HINTS):                                # 整段判失效标注: 标注常写在段首或相邻行, 按行判会误伤
            continue
        base = getattr(node.body[0], "lineno", 1)
        for i, line in enumerate(doc.splitlines()):                                                 # 逐行映射回物理行号
            if line.strip():                                                                        # 空行不进
                texts.setdefault(base + i, line)                                                # 已有行尾注释的行不覆盖 (setdefault)
    # 行内注释按行判: token 的原文带 # 前缀, 失效标注常紧跟在同一行
    for tok in tokens:                                                                   # 行内注释直接写入: 它的原文带 # 前缀, 失效标注常紧跟其后
        texts[tok.start[0]] = tok.string                                        # token 覆盖 docstring 行: 同一行两者都算时以 token 为准
    for lineno, text in sorted(texts.items()):                                                      # 按行号排序: 报告顺序稳定
        if any(hint in text for hint in _PATH_RETIRED_HINTS):                                       # 行内注释按行判豁免
            continue
        for m in RE_PATH_IN_COMMENT.finditer(text):                                                 # 逐个路径候选
            cand = m.group(1)                                                                       # 取路径文本
            if _PATH_IS_PLACEHOLDER.search(cand) or "…" in cand:
                continue
            if any(os.path.exists(os.path.join(base, cand))                                         # 三处基准任一存在即通过
                   for base in (ROOT, here, os.path.dirname(here))):                                # 仓根 / 本文件目录 / 其父目录
                continue
            out.append({"kind": "referenced_path_missing", "name": rel,
                        "line": lineno, "detail": cand})
    return out


def main() -> int:
    """主入口: 扫描全仓 .py, 汇总违规并写 JSON + 打印清单; 十五类计数全 0 才返回 0。

    作用: 走 :func:`scan_roots.iter_py_files` 给出的全量清单, 对每个 .py 一次读盘,
    把同一份原始字节同时喂给 tokenize 与 ast, 串起
    Q1–Q10 十个**检查组**, 汇总成 report 与 totals 两张表。两个维度别混:
    检查组数 (10) 与违规 kind 数 (15) 不等 —— 一个 Q 组可覆盖多个 kind
    (如 Q1/Q2/Q3 共用「逐个函数取 docstring」这一遍遍历)。
    返回: int —— ``1 if any(totals.values()) else 0``, 直接当退出码用。
    抛什么: 读盘失败会冒 OSError/UnicodeDecodeError, 不降级 —— 那说明扫描本身
    没跑完, 必须让调用方看见而不是当成"零违规"。
    """
    report: dict[str, list[dict]] = {}                                                       # 报告表: 文件 -> 该文件的 findings 列表
    # totals 的键集合 = 全部违规 kind, 写全是为了让"新增一种 kind 却忘了计入
    # 退出码判定"变成一次肉眼可见的 diff, 而不是一次静默的口径漏洞
    totals = {"missing_docstring": 0, "docstring_not_chinese": 0, "fluff_docstring": 0,  # 写全十五类: 新增 kind 忘了计入就是一次 diff
              "import_group_no_chinese_note": 0, "todo_in_code": 0, "duplicated_comment": 0,
              "unparseable": 0, "module_header_missing": 0, "module_header_thin": 0,
              "module_header_not_chinese": 0, "inline_comment_density_low": 0,
              "trailing_comment_ratio_low": 0, "trailing_comment_spacing": 0,
              "referenced_path_missing": 0, "line_alignment_low": 0}
    for rel, full in iter_py_files(ROOT):  # 覆盖面由共享真源给出: 仓内全部 .py (排除项见 scan_roots 模块头)
        with io.open(full, "rb") as fh:
            # 读原始字节: 同一份数据要同时喂给 tokenize(要字节) 与
            # ast(要文本), 读一次就够
            raw = fh.read()                                            # 读原始字节: 同一份数据要同时喂 tokenize(要字节) 与 ast(要文本)
        text = raw.decode("utf-8", "replace")
        lines = text.splitlines()                                                           # 拆物理行: 各项检查都要按行定位
        # AST 只解析一次: 各检查共用同一棵树 (性能 + 避免多处各判一次语法)
        try:
            tree = ast.parse(text)                                                          # AST 只解析一次: 各检查共用同一棵树
        except SyntaxError as exc:
            # 语法错只报 unparseable 一条, 不再往下跑各项检查 ——
            # 在坏树上判密度/import 覆盖只会产出二次噪声
            found = [{"kind": "unparseable", "name": rel, "line": 0,
                      "detail": str(exc)}]
        else:
            # tokenize 也只做一次: 注释 token 同时供 Q4/Q6/Q7/Q8 使用
            tokens = comment_tokens(raw)                         # tokenize 也只做一次: 注释 token 同时供 Q4/Q6/Q7/Q8/Q10 使用
            found = analyse_docstrings(rel, tree)                               # Q1-Q3: docstring 存在性 / 中文 / 是否灌水
            found += analyse_module_header(rel, tree)                                       # Q5: 模块头存在性、过薄、无中文
            found += analyse_inline_density(rel, tree, lines, len(tokens))                  # Q6: 注释密度
            found += analyse_trailing_style(rel, tree, lines, tokens)                       # Q7/Q8: 行尾占比与两空格间距
            found += analyse_imports(rel, lines, string_literal_lines(raw))                  # import 组覆盖 (字符串内的行不算 import)
            found += analyse_comments(tokens)                                               # Q4: 待办标记与机械复制注释
            found += analyse_referenced_paths(rel, tree, lines, tokens)                     # Q9: 注释引用的仓内路径是否真实存在
            found += analyse_line_alignment(rel, tree, lines, tokens)                       # Q10: 非平凡语句的逐行对照率
        if found:                                                               # 有违规才入表: 干净文件不进报告, 免得 JSON 被空条目淹没
            report[rel] = found                                                             # 挂到该文件名下
            for item in found:                                                              # 逐条累加到 totals
                # 用 get 兜底而非直接下标: 出现新 kind 时不至于 KeyError
                # 崩掉整轮报告, 那样就一个字也看不到了
                totals[item["kind"]] = totals.get(item["kind"], 0) + 1  # get 兜底: 新 kind 不会 KeyError 崩掉整轮报告
    # 产物目录不存在就建: temp/ 是 gitignored 的一次性目录, fresh clone 上本来就没有,
    # 缺目录时本门禁会以 FileNotFoundError 崩掉 —— 红的理由变成"环境缺目录"而不是
    # "注释有问题", 那正是判据审计 D5-05 指出的失败方向错误 (修复成本一行)。
    os.makedirs(os.path.dirname(OUT), exist_ok=True)  # exist_ok: 跑批产物反复覆写, 目录已存在不是错
    with io.open(OUT, "w", encoding="utf-8") as fh:
        json.dump({"totals": totals, "files": report}, fh, ensure_ascii=False, indent=1)
    print(json.dumps(totals, ensure_ascii=False))                                   # totals 一行 JSON: 便于脚本/钩子直接读退出码之外的量化口径
    print("--- 违规最多的 15 个文件 ---")
    # 只打前 15 是刻意截断: 全量清单会刷屏, 真正要逐条处理的人会读 JSON 产物
    for rel, items in sorted(report.items(), key=lambda kv: -len(kv[1]))[:15]:      # 只打前 15 个: 全量清单会刷屏, 真正要处理的人会读 JSON 产物
        kinds: dict[str, int] = {}                                                                  # 按 kind 聚合计数
        for it in items:                                                                            # 逐条归类
            kinds[it["kind"]] = kinds.get(it["kind"], 0) + 1
        print(f"  {len(items):3d}  {rel}  {kinds}")
    # 退出码: 十五类计数必须全 0 (README §7 的强制护栏口径)
    return 1 if any(totals.values()) else 0


if __name__ == "__main__":
    raise SystemExit(main())  # 退出码即门禁结果, 直接交给 make audit
