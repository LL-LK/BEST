"""count_code_lines.py — 统计每个 .py 的净代码行 (排除空行/注释/docstring)。

口径 (与 docs/architecture/file-size-budget.md 一致):
  净代码行 = 物理行 - 空行 - 纯注释行 - docstring 行
超过 400 的行需在 docs 登记必要性论证 (R2: **未登记即视为违规**)。

职责: 给"单文件 ≤400 净行"这条铁律提供唯一数字来源, 并核对超限文件是否在预算
  文档里登记了必要性论证。度量对象是 .py 的物理行减去三类非代码行; 它刻意**不**
  统计注释行, 所以加注释不会让文件超预算 —— 注释密度门禁与本门禁互不打架。
所属子系统: 仓库治理层 ops/audit/ 的**硬门禁**之一 (make audit 接线): 未登记的
  超限文件即非零退出。上游无代码依赖 (纯离线统计), 下游是 Makefile 与人工看超限榜。
对外接口: main() -> int (未登记超限的个数即退出码); registered_files() /
  docstring_lines() / measure() 是可外部依赖的 seam —— 同一套"docstring 行号"口径
  被 ops/audit/comment_audit.py 的密度计算直接复用, 两边改动必须同步。
依赖与数据流: 输入是工作区磁盘上的 .py 文本 + docs/architecture/file-size-budget.md
  的登记表格; 扫描面 (哪些 .py 进门禁) 全部来自同目录 scan_roots.iter_py_files,
  本文件不另列目录清单; 不产出 JSON 产物, 结果只经 stdout 表格与退出码外传。
关键契约与不变量: 退出码口径是"未登记的超限文件数是否为 0", 登记过就放行 —— 改
  BUDGET 或改 scan_roots 的排除项都会静默改变门禁覆盖面, 属于改判据; 登记簿缺失时
  输出里显式打"缺失"而不是当作零违规, 避免铁律 5 的 fail-open。
陷阱与边界: 语法错误文件返回净行 -1, **但不再静默放过** —— main() 会把它收进
  unparseable 列表单列一段并直接判红 (若放行, 负数恒不满足 > BUDGET, 坏文件就在
  本门禁与 comment_audit 的双重沉默里消失, 两边都指望对方兜底, 属 fail-open);
  docstring 行号靠 AST 取, 因此 f-string 里的多行字符串、以及被注释
  掉的伪 docstring 都不会误算; 反过来, 靠正则猜 docstring 会在这些形态上翻车,
  故一律走 ast。
"""
from __future__ import annotations

# 标准库: ast 解析结构与引用判定 / io 统一按 utf-8 读盘 / os 遍历 / re 正则 /
# pathlib 仓根定位
import ast
import io
import os
import re
from pathlib import Path

# 本地: 扫描面 (哪些 .py 进门禁) 的唯一真源。同目录兄弟模块, 按同目录裸名导入 ——
# 直跑本文件时 sys.path[0] 就是 ops/audit/, 单测注入 AUDIT_DIR 后 import 亦然; 走
# ops.audit. 包路径反而会在直跑时 ModuleNotFoundError。覆盖面**不写在本文件**:
# 2026-10-05 判据审计 D5-01 实测, 目录白名单漏掉 agents/ 时 900 净行的文件全门禁
# 判绿, 且同款白名单被四道门禁各抄一份, 一处缺口同时废掉四条判据。
from scan_roots import iter_py_files  # noqa: E402  同目录裸名导入, 理由见上方三行

ROOT = str(Path(__file__).resolve().parents[2])  # 上溯两级到仓根; 原硬编码绝对路径, 换机即失效
BUDGET = 400  # 铁律 2 的硬上限; 改它等于改门禁覆盖面, 须同改预算文档
# 登记簿: file-size-budget.md §3 的超限登记表 (首列形如 | `src/client.py` | ...)
BUDGET_DOC = os.path.join(ROOT, "docs", "architecture", "file-size-budget.md")             # 登记簿路径: 超限文件必须在册, 缺登记簿则本门禁无从核对
RE_TABLE_ROW = re.compile(r"^\|\s*`([^`]+\.py)`\s*\|(.*)$", re.M)  # 整行捕获: 论证列必须一起读, 否则一行空表格就能合法化任意超限文件
MIN_ARG_CHARS = 8  # 论证单元格的最短实质字数: 纯数字/破折号不算论证 (判据见 _row_has_argument)
ARG_PLACEHOLDERS = frozenset({"—", "-", "–", "/", "无", "n/a", "na", "tbd", "todo", "待补", "同上"})  # 占位符不算论证
CJK_OR_SECTION = re.compile(r"[一-鿿§]")  # 论证必须是中文 (R3 铁律 3) 或指向登记簿小节 (§)


def _row_has_argument(cells: str) -> bool:
    """判断登记簿的一行是否真的写了"必要性论证" (R2 的字面要求, D5-02 修复)。

    旧口径的注释写着"后两列是给人读的, 解析它们只会引入误判" —— 实测正因如此,
    一行空表格 (例如 ``| `src/fat.py` |  |  |``) 就把任意超限文件变成"已登记",
    R2 的"论证"部分零强制力。判据刻意取**词法**最低门槛而不是语义判定 (语义判定
    必误报): 至少一个单元格含 >= MIN_ARG_CHARS 个实质字符, 且含中文或指向登记簿
    小节 (§)。

    Args:
        cells: 表格行首列之后的部分 (含首尾竖线)。

    Returns:
        True 表示这一行写了可读的论证, 算"已登记"。
    """
    for cell in cells.split("|"):  # 逐格看: 论证可能落在任何一列 (登记簿的列名各小节不统一)
        text = cell.strip().strip("*` ").strip()  # 去掉 markdown 强调与反引号, 只留文字
        if not text or text.lower() in ARG_PLACEHOLDERS:  # 空格子与占位符一律不算论证
            continue
        if len(text) >= MIN_ARG_CHARS and CJK_OR_SECTION.search(text):  # 够长且是中文/小节引用
            return True
    return False


def registered_files() -> set[str]:
    """从预算文档的登记表提取"已登记超限"文件名 (R2 判据的来源)。

    登记表的语法约定: 首列是形如 ``| `src/client.py` | ...`` 的管道表格行; **该行
    必须同时写了必要性论证** (见 :func:`_row_has_argument`), 否则不计入登记 ——
    只认首列等于"加一行空表格就能合法化任意超限文件" (判据审计 D5-02 实测)。
    返回集合里做过 ``./`` 前缀剥离, 因为文档里两种写法混用。
    """
    if not os.path.isfile(BUDGET_DOC):                                                   # 登记簿缺失即判红: 静默跳过会让"没登记"与"没这个检查"同形
        return set()  # 登记簿缺失 = 判据失效, 绝不能当成零违规放行 (铁律 5)
    with io.open(BUDGET_DOC, encoding="utf-8") as fh:
        text = fh.read()                                                                       # 一次读入: 登记簿不大, 但要保证与磁盘同一份快照
    return {  # 只收"真登记": 文件名 + 同行必须有可读论证
        m.group(1).strip().lstrip("./")  # 剥 ./ 前缀: 文档里两种写法混用
        for m in RE_TABLE_ROW.finditer(text)
        if _row_has_argument(m.group(2))
    }


def docstring_lines(tree: ast.AST) -> set[int]:
    """收集所有 docstring 占用的物理行号 (模块/类/函数级)。

    判定方式是"定义体的第一条语句是不是字符串常量表达式", 与 Python 取
    __doc__ 的规则一致; 只有这样才对得上运行期语义, 正则扫描做不到这点。
    """
    rows: set[int] = set()  # 物理行号集合, 供 measure() 逐行剔除
    for node in ast.walk(tree):                                                          # 遍历全部节点: docstring 可能在模块/类/函数任一层
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):  # 四类节点都收: 模块头也是 docstring, 净行口径必须一致
            doc = ast.get_docstring(node, clean=False)                               # 取原始 docstring: clean 会改缩进, 与物理行数对不上
            if doc is None:                                                                 # 没有 docstring 就没行可剔: 空集合是正确结果
                continue
            body = node.body                                                             # 取 body 列表: 后面要判断首条是不是 docstring
            if not body or not isinstance(body[0], ast.Expr):  # 首条必须是表达式, 否则会在 __doc__ 赋值习惯的文件上错位
                continue
            value = body[0].value                                                # 首条的 value: docstring 是 Expr 包着 Constant
            if isinstance(value, ast.Constant) and isinstance(value.value, str):         # 确认是字符串常量: 非字符串(如整数)不是 docstring
                rows.update(range(value.lineno, (value.end_lineno or value.lineno) + 1))  # end_lineno 兜底, 兼容老 ast
    return rows


def measure(path: str) -> tuple[int, int, int]:
    """返回 (物理行, 净代码行, docstring 行)。

    净行 = 物理行中既不是空行、也不是纯注释行、也不落在 docstring 行号集合里
    的那部分; 语法错误返回净行 -1 作哨兵, 调用方据此跳过 (见模块头"陷阱")。
    """
    with io.open(path, "rb") as fh:
        raw = fh.read()  # 二进制读再解码: 文本模式会吃掉换行, 物理行数随机器而变, 门禁数字不可复现
    text = raw.decode("utf-8", "replace")
    lines = text.splitlines()                                                                       # 按物理行拆: 净行判定要逐行进行
    try:
        tree = ast.parse(text)                                                            # 语法树只解析一次: 拆行与剥 docstring 共用同一份
    except SyntaxError:
        return len(lines), -1, -1  # 哨兵 -1: 调用方据此判红, 而不是把坏文件默默算成合规
    docs = docstring_lines(tree)                                                                # docstring 行集合: 净行计算时整体剔除
    net = 0                                                                                        # 净行从零累加: 每行只判一次, 不重复计数
    for idx, line in enumerate(lines, start=1):                                                   # 行号从 1 起: 与编辑器和报告里的行号一致
        if idx in docs:  # 先排 docstring 行: 缩进续行以空格开头, 靠 startswith 认不出来
            continue
        stripped = line.strip()                                                                  # 去掉首尾空白: 缩进不该影响"这行算不算代码"
        if not stripped or stripped.startswith("#"):  # 空行与纯注释行都不占预算, 所以加注释不会撞 400 线
            continue
        net += 1                                                                               # 非空且非纯注释才算: 空行与注释行都不占净代码预算
    return len(lines), net, len(docs)


def main() -> int:
    """主入口: 扫描全仓 .py 并打印超预算文件与汇总; 返回"未登记超限"的个数判定。

    作用: 走 :func:`scan_roots.iter_py_files` 给出的全量清单, 对每个 .py 调
    measure() 拿三元组, 再按 BUDGET 与登记簿切出三段输出。关键输入除 BUDGET 外
    全部来自共享扫描面, 无调用方形参。
    返回: int —— 未登记的超限文件数 (0 或正数), 直接当退出码用。
    抛什么: 读盘/解码失败会冒 OSError/UnicodeDecodeError, 不降级 —— 那说明扫描
    本身没跑完, 必须让调用方看见。
    """
    rows = []                                                                        # 行结果表: (相对路径, 物理行, 净行, docstring 行数)
    unparseable: list[str] = []                                                  # 单独收集语法错文件: 坏文件不能被静默丢弃 (fail-closed 修复点)
    for rel, full in iter_py_files(ROOT):  # 覆盖面由共享真源给出: 仓内全部 .py (排除项见 scan_roots 模块头)
        row = (rel,) + measure(full)                                                    # 度量并把相对路径放在元组首位: 报告与排序都按它
        rows.append(row)                                                                    # 结果入表: 一行一个文件
        # 负净行 = 语法错误哨兵。原先它只是"不进超限榜"就算完, 坏文件
        # 会在本门禁与 comment_audit 的双重沉默里消失 (两边都指望对方
        # 兜底), 属 fail-open (铁律 5)。现在显式收集并直接判红。
        if row[2] < 0:                                                 # 净行为负 = 解析失败: 该落进 unparseable 而不是被当成 0 行放行
            unparseable.append(rel)                                      # 失败文件单列: 两处(本门禁与 comment_audit)互相兜底会双重沉默
    over = [r for r in rows if r[2] > BUDGET]  # r[2] 是净行不是物理行 —— 拿物理行比会大面积假阳性
    print("=== 净代码行超 %d 的文件 (%d 个) ===" % (BUDGET, len(over)))
    for _rel, _phys, net, _docs in sorted(over, key=lambda r: -r[2]):                           # 超限清单按净行倒序: 最大的排最前, 便于先处理
        print("  %4d 净行  %5d 物理  %s" % (net, _phys, _rel))
    # 接近线 (250~400) 是提前预警: 等真超限再登记就等于事后补台账
    print("=== 净代码行 250~%d 的接近文件 ===" % BUDGET)
    near = [r for r in rows if 250 < r[2] <= BUDGET]                                    # 接近预算的也报: 250..400 是预警区, 不报就等着它越线
    for _rel, _phys, net, _docs in sorted(near, key=lambda r: -r[2])[:12]:                      # 取最接近的 12 个: 全量刷屏, 预警只看头部
        print("  %4d 净行  %5d 物理  %s" % (net, _phys, _rel))
    registered = registered_files()  # R2 判据的输入: 超限必须在预算文档 §3 登记过
    unregistered = [r for r in over if r[0] not in registered]  # 登记过就放行, 这是未登记即违规的另一半
    print("=== 未登记的超限文件 (%d 个, 登记簿 %s) ==="
          % (len(unregistered), "已读到" if registered else "**缺失**"))
    for _rel, _phys, net, _docs in unregistered:                                        # 未登记的超限: 登记簿里查无此文件 = 无理由放行 (铁律 5)
        print("  %4d 净行  %5d 物理  %s" % (net, _phys, _rel))
    # 语法坏文件单列一段并直接判红: 净行量不出来 = 预算判据失效, 不能当合规
    print("=== 语法错误导致无法计量的文件 (%d 个, 必须为 0) ===" % len(unparseable))
    for rel in unparseable:                                                                   # 语法错清单: 与超限分开报, 两类问题的处置方式不同
        print("  [PARSE]  %s" % rel)
    # 汇总行是门禁数字的复现入口: 总净行是全仓真实体量, 改动应能在这里对账
    print("文件数=%d  总物理行=%d  总净代码行=%d"
          % (len(rows), sum(r[1] for r in rows), sum(r[2] for r in rows)))                     # 末尾统计: 文件数/物理行/净行三数, 供趋势比对
    return 1 if (unregistered or unparseable) else 0  # 退出码 = 未登记超限数与坏文件数是否都为 0


if __name__ == "__main__":
    raise SystemExit(main())
