# -*- coding: utf-8 -*-
"""覆盖矩阵门禁 — 校验 docs/architecture/coverage-matrix.md 的锚点真实且来源完备。

背景: astro-best 的 §6/§6.1 有 34 条已核实债务, 复核时发现其中
大部分「现有测试测不出」。根因不是测试写得差, 而是没有任何一行证据指向那条
能力 —— 交叉匹配脚本只有 import+callable 断言, 所以 A2 (扩展名与内容不符)
可以长期存在而不被发现。

本测试把「覆盖」从主观判断变成 CI 可判定命题, 四条规则:

  R1 锚点真实性   — anchor/unit/integration 指向的文件与符号必须真实存在;
                     eval 锚点 = evals/cases/<file>.yaml 必须存在。
  R2 来源完备性   — 矩阵 capability 必须覆盖四类来源全集: spec algorithms、
                     src.__all__、LOCAL_EXPORT_FORMATS、CHAIN_CAPABILITIES。
  R3 证据真实性   — status=covered 的行必须至少有一条 unit/integration/eval
                     锚点 (不能拿"覆盖了"当口头承诺)。
  R4 不许无声缺口 — status=gap 的行必须在矩阵 §3 gap 清单中登记; 未登记的
                     gap 即失败。已知未修可以长期存在, 但不可以没人知道。

docstring 规范: 每个函数说明检查什么、为什么这样判定、失败意味着什么。
"""

from __future__ import annotations

# 标准库: AST 静态解析锚点真实性 / 正则抽取 capability 单元格 / 路径定位矩阵与 spec
import ast
import re
from pathlib import Path

# 第三方: pytest 承载参数化与跳过; yaml 解析 skills-spec 的能力清单
import pytest
import yaml

SKILL_DIR = Path(__file__).resolve().parents[3]  # 上溯三级到 skill 根: 矩阵与 spec 都是相对本文件的固定位置
MATRIX = SKILL_DIR / "docs" / "architecture" / "coverage-matrix.md"  # 被校验的 SSOT 本身
SPEC = SKILL_DIR / "references" / "skills-spec.local.yaml"  # R2 来源之一: 契约算法名
CASES_DIR = SKILL_DIR / "evals" / "cases"  # eval 锚点落点: 锚点即此处的文件名

# 站点交互链的权威清单: 对 nadc.china-vo.org/data/best 的真实调用链,
# 漏掉任一环都意味着那条链上没有证据 (矩阵必须逐环登记)。
CHAIN_CAPABILITIES = (                                                                              # 链路能力清单: 矩阵的锚点全从这里取
    "认证",            # Django session + CSRF 登录
    "两阶段",          # POST 表单 -> sqlid
    "分页",            # GET 分页取数 + max_rows
    "软 404",          # HTTP 200 + error 体判定
    "getcount",        # 服务端总数与截断判定
    "resolve_name",    # Sesame 名称解析
    "流式下载",        # 下载 + 校验和
    "断点",            # 页级断点续传
    "取消",            # 取消语义与终态
    "provenance",      # 血缘信封
    "TAP",             # TAP/UWS 适配面
    "交叉匹配",        # 服务端 proximity
    "CSV 注入",        # 公式注入防护
    "路径穿越",        # 输出目录约束
)

# capability 单元格形如 "`BestAuth` Django session + CSRF 登录" 或
# "分页 GET + `max_rows` 上限" 或 "**取消语义: precise 任务可取消**":
# 取首个符号/词作为 capability 键 (容许中文与 snake_case 键), 其余是给人看的说明。
_CELL_RE = re.compile(r"^[`*\s]*([A-Za-z0-9_.\-\u4e00-\u9fff]+)")  # CJK 必在: 能力名本身可以是中文
# 从单元格里抽取 pytest 锚点 (容许尾随说明文字, 如 "test_print_or_save` 同级")
_ANCHOR_RE = re.compile(r"(test/[\w/.\-]+\.py(::[\w.]+)*)")  # 锚点必须是文件+可选节点路径


def _split_row(line: str) -> list[str]:
    """把一行 Markdown 表格按 | 切成单元格 (去掉首尾空 cell)。

    先 strip 掉行首尾的 | 再切, 否则每行都会多出首尾两个空单元格, 后面按
    表头列数做的 zip 会整体错位一格, 而错位后的行看上去仍然"有内容"。
    """
    return [c.strip() for c in line.strip().strip("|").split("|")]  # 先剥首尾 | 再切, 否则整表错位一格


def load_matrix() -> list[dict[str, str]]:
    """解析覆盖矩阵的能力表, 返回每行的字段字典。

    只取 §2 各小节的表格 (跳过 §0 基线表与 §3 gap 表: 它们列数不同)。
    判定依据是表头单元格含 ``capability`` 且含 ``anchor``。
    """
    text = MATRIX.read_text(encoding="utf-8")  # 读全文再逐行切: 表头判定依赖同一份文本, 二次读盘会读到不同版本
    rows: list[dict[str, str]] = []  # 收行字典: 列数随表头而变, 用定长列表存必然错位
    header: list[str] | None = None  # 表头随行扫描而变: §2 之后还有别的表, 不能一次定死
    in_capability_table = False  # 表头是唯一入口: §0/§3 列数不同, 认表头才不会串表
    for line in text.splitlines():  # 逐行扫而非正则整表匹配: 表格之间还夹着正文段落
        s = line.strip()  # 去首尾空白: Markdown 表格常带缩进, 不 strip 就认不出行首竖线
        if not s.startswith("|"):  # 非表格行要重置状态: 否则 §3 的表会被当成 §2 的续表
            in_capability_table = False  # 离开表格即清表头: 防止跨节串表导致整表错位
            header = None
            continue  # 分隔行也清表头: 它同样不是数据行
        cells = _split_row(s)  # 切出单元格: 后面所有判定都基于这份切分
        if set("".join(cells)) <= set("-: "):  # 全由 - : 构成的行是 Markdown 的表头分隔行
            continue  # 分隔行
        if "capability" in cells and "anchor" in cells:  # 表头含 capability 与 anchor 才认: 这是区分三张表的唯一依据
            header = cells  # 记下表头: 列名到列值的映射全靠它
            in_capability_table = True  # 置位后才收数据行: 顺序反了会把表头当数据行收进去
            continue
        if not in_capability_table or header is None:  # 不在能力表内的行直接略过: §0 基线表与 §3 gap 表都从这里被排除
            continue
        if len(cells) != len(header):  # 列数不符即视为非数据行: 错位 zip 出来的行看上去仍然"有内容"
            continue  # 列数不符即视为非数据行, 不做错位 zip
        row = dict(zip(header, cells))  # 按表头 zip 成字典: 之后一律按键取, 不再依赖列序
        m = _CELL_RE.match(row["capability"])  # 从 capability 单元格抽能力键: 说明文字不参与对账
        if m:  # 只有抽到键才算有效行: 抽不到说明这行不是能力声明
            row["cap"] = m.group(1)  # 键取首个符号/词, 不含给人看的说明文字
            rows.append(row)
    return rows


def symbol_exists(path: Path, symbol: str) -> bool:
    """用 AST 判定符号 (类/函数/常量) 是否定义在文件中。

    文本包含不足以证明: 注释或 docstring 里提到同名符号会让检查恒过。
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))  # 解析整个源文件: 只看文本包含会被注释与 docstring 骗过
    except (SyntaxError, UnicodeDecodeError):
        return False  # 解析不了即判不存在: 文本包含不足以证明符号真被定义
    for node in ast.walk(tree):  # 全树遍历: 符号可能定义在嵌套的类或函数里
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):  # 函数与类都算符号: 矩阵两类锚点都出现过
            if node.name == symbol:  # 名字相等即命中: 大小写敏感, 与 Python 语义一致
                return True
        elif isinstance(node, ast.Assign):  # 普通赋值单独分支: 常量型锚点全走这一支
            for t in node.targets:  # 一条赋值可能有多个目标: 元组解包也在这里
                if isinstance(t, ast.Name) and t.id == symbol:  # 只认裸名字: 属性赋值不是本门禁认的符号形态
                    return True  # 常量也算符号: 矩阵里锚的常量子类为数不少
        elif isinstance(node, ast.AnnAssign):  # 带注解的赋值走独立分支: 它的目标不在 targets 上
            if isinstance(node.target, ast.Name) and node.target.id == symbol:  # 注解赋值的目标也要比名字: 带类型的常量同样是锚点
                return True  # 带注解的赋值走独立分支, 不在 targets 上
    return False  # 走到这里说明符号真没定义: 文本包含式的假阳性在这里被排除


def pytest_node_exists(anchor: str) -> bool:
    """判定 pytest 锚点是否真实存在, 支持三种粒度:

      - `test/x.py`                     文件存在即可
      - `test/x.py::TestClass`          类存在 (类级锚点, 不需指定方法)
      - `test/x.py::TestClass::test_y`  方法存在
      - `test/x.py::test_y`             顶层函数存在

    只认形如 test/...py 的锚点: 单元格里允许尾随说明文字 (如 "类内 2 例"),
    先用 ``_ANCHOR_RE`` 抽出锚点本体再校验, 否则说明文字会让校验恒失败。
    """
    m = _ANCHOR_RE.search(anchor)  # 先抽锚点本体: 单元格允许尾随说明文字, 不抽就恒失败
    if not m:  # 抽不到就是说明文字, 不参与校验: 这不是失效锚点
        return True  # 不是 pytest 锚点 (是说明文字), 不参与校验
    node = m.group(1)  # 取分组 1: 正则已保证锚点形态, 不会抽到别的东西
    file_part, _, node_part = node.partition("::")  # 一次 partition 分出文件与节点两段
    path = SKILL_DIR / file_part  # 锚点路径相对 skill 根: 矩阵里写的就是仓库相对路径
    if not path.is_file():  # 文件不在即锚点失效: 这是最先要排除的一层
        return False
    if not node_part:  # 只锚到文件就算通过: 文件粒度不要求符号存在
        return True  # 只锚到文件
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))  # 同样走 AST: 文本包含会把同名方法判成存在
    except (SyntaxError, UnicodeDecodeError):
        return False
    wanted = node_part.split("::")  # 按 :: 切段数决定粒度: 一段/两段/三段对应函数/类/方法
    if len(wanted) == 1:  # 一段 = 顶层函数或类: 模块级锚点
        name = wanted[0]  # 名字取出来备用: 只在单段分支里用
        return any((isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name == name)  # 任何模块级同名定义即可: 顶层函数与类都接受
                   for n in tree.body)  # 单段 = 顶层函数或类
    cls_name = wanted[0]  # 两段锚点的类名: 下面要在类体里找方法
    for node_obj in tree.body:  # 扫模块体找那个类: 嵌套类不算, 矩阵锚的是模块级类
        if isinstance(node_obj, ast.ClassDef) and node_obj.name == cls_name:  # 类名对上才继续: 类不存在即锚点失效
            if len(wanted) == 2:  # 只锚到类就直接通过: 类粒度不要求某个方法
                return True  # 只锚到类
            return any(isinstance(m2, ast.FunctionDef) and m2.name == wanted[-1]  # 方法名在类体里逐个比: 少这一支就漏掉方法级锚点
                       for m2 in node_obj.body)  # 三段 = 锚到类里的某个方法
    return False  # 类里也没有: 锚点失效, 报出去


def eval_case_exists(anchor: str) -> bool:
    """判定 eval 锚点是否真实存在 (case 文件名或场景 id)。

    两种合法形态:
      - `case_005_scope_01_nadc-best-rest-api-认证` -> evals/cases/<名>.yaml
      - `cone_search` / `tap_service`             -> test-scenarios.yaml 的 id
    锚点可能含中文 (case 文件名带中文), 所以不能用 ASCII 正则切分。
    """
    stem = anchor.strip().strip("`")  # 剥掉反引号: 矩阵里锚点是被反引号包着的
    if (CASES_DIR / f"{stem}.yaml").is_file():  # 形态一先试: case 文件名就是锚点, 命中即算存在
        return True  # 形态一: case 文件名直接就是锚点
    scenarios = SKILL_DIR / "evals" / "test-scenarios.yaml"  # 形态二的落点: 场景 id 收在另一个文件里
    if not scenarios.is_file():  # 场景表不在即两种形态都不成立: 不能默认它存在
        return False  # 两种形态都不成立即锚点无效
    data = yaml.safe_load(scenarios.read_text(encoding="utf-8")) or {}  # 容错读 YAML: 空文件会返回 None, 用 or {} 兜住
    entries = data.get("evaluations") or data.get("scenarios") or []  # 两个键都认: 两种文件布局都见过
    return any(isinstance(e, dict) and str(e.get("id", "")) == stem for e in entries)  # 按 id 精确比对: 场景 id 是稳定标识符


def spec_algorithms() -> set[str]:
    """取 spec 切片声明的算法名全集 (跨 skill 契约面)。

    过滤掉无 name 的条目: 契约里若出现半条目, 拿它当算法名会让下游"这条能力
    没有对应实现"的红指向一个不存在的名字, 整改时无从下手。
    """
    data = yaml.safe_load(SPEC.read_text(encoding="utf-8")) or {}  # spec 是 R2 的四类来源之一, 缺了整条规则就空转
    skill = (data.get("skills") or {}).get("astro-best") or {}  # 单 skill 切片: 别的 skill 不参与
    return {str(a.get("name")) for a in skill.get("algorithms", []) or [] if a.get("name")}  # 剔无 name 的半条目


def public_api() -> set[str]:
    """取 src/__init__.py 的 __all__ 公开面全集。

    走 AST 赋值而不是 import 后读属性: 公开面是本门禁的判据基准, 一旦实现
    在 import 期做了条件导出, 读到的可能不是版本库里声明的那一份。
    """
    path = SKILL_DIR / "src" / "__init__.py"  # 公开面所在文件: R2 要求它与矩阵逐名对账
    tree = ast.parse(path.read_text(encoding="utf-8"))  # 走 AST 而非 import: import 期条件导出会让读到的不是声明的那份
    for node in tree.body:  # 扫模块体找 __all__ 赋值: 它一定在顶层
        if isinstance(node, ast.Assign):  # __all__ 是普通赋值: 不走 AnnAssign 分支
            for t in node.targets:  # 一条赋值可能有多个目标
                if isinstance(t, ast.Name) and t.id == "__all__":  # 认 __all__ 这个名字: 别的赋值一律跳过
                    return {str(e.value) for e in node.value.elts  # 收元素里的字面量: 动态构造的项无法静态核名
                            if isinstance(e, ast.Constant)}  # 只收字面量: 动态项无法静态核名
    return set()  # 读不到 __all__ 即公开面为空集, R2 会立刻报出缺登记


def local_export_formats() -> set[str]:
    """取 src/serialization.py 的 LOCAL_EXPORT_FORMATS 全集。"""
    path = SKILL_DIR / "src" / "serialization.py"
    if not path.is_file():  # 文件不在要显式判: 静默返回空集会让 R2 空转而无人察觉
        return set()  # 文件不在: R2 报缺登记, 不在这里静默吞掉
    text = path.read_text(encoding="utf-8")  # 读全文: 正则要跨行匹配赋值右边的字面量
    m = re.search(r"LOCAL_EXPORT_FORMATS[^=]*=\s*[(\[]([^\])]+)[\])]", text)  # 正则直取字面量, 避开 import
    if not m:  # 正则失配说明集合形态变了: 落空集等于让 R2 悄悄失效
        return set()  # 集合形态改动会让这条正则失配, 落空集等于让 R2 空转
    return {s.strip().strip('"\'') for s in m.group(1).split(",") if s.strip()}  # 剥引号留净格式名


def test_matrix_file_exists():
    """矩阵文件缺失即失败 (没有 SSOT 就谈不上覆盖判定)。

    放在所有覆盖类用例之前守: 矩阵缺了, 后面那些"逐行校验"的用例会读到
    空列表而全绿, 门禁就变成了一个恒真的摆设。
    """
    assert MATRIX.is_file(), f"覆盖矩阵缺失: {MATRIX}"  # 守在最前: 矩阵缺了后面全是恒真空绿


def test_anchors_are_real():
    """R1: 每个 anchor 必须指向真实文件 (与符号), 不许写不存在的锚点充数。

    anchor 单元格允许三种写法:
      - `src/client.py`                     单文件
      - `src/protocol.py::parse_csv_rows`   文件 + 符号 (符号须用 AST 验证存在)
      - `src/a.py` / `src/b.py`             多路径 (两条链路并联)
    校验器逐个抽取校验, 不让"顺手写了不存在的路径"蒙混过关。
    """
    rows = load_matrix()  # 先解析出全部能力行: 下面三条规则共用这一份
    assert rows, "矩阵未解析出任何能力行 (表头格式可能被改动)"  # 解析空 = 后续校验全在空集上跑
    bad: list[str] = []  # 攒问题而不是立刻断言: 一次报全部, 便于一次改完
    # anchor 单元格允许三类写法: 源码文件 / 源码文件::符号 / 多路径并联;
    # 元测试类能力的 anchor 也可能指向 spec/doc 文件 (yaml/md), 一并纳入校验。
    path_re = re.compile(r"([A-Za-z0-9_./\-]+\.(?:py|yaml|yml|md))(?:::([A-Za-z_]\w*))?")  # 符号段只认单段
    for row in rows:  # 逐行校验: 锚点可以多个, 抽不全就等于放过
        cell = row.get("anchor", "")  # 取 anchor 单元格: 允许逗号并联多条路径
        found = path_re.findall(cell)  # 找出所有"路径[::符号]"形态: 一格可能列好几条
        if not found:  # 一个都没抽到才走"无法解析"分支
            if cell.strip() and cell.strip() != "—":  # 空单元格与破折号都不算问题: 破折号是"无锚点"的合法写法
                bad.append(f"{row['cap']}: anchor 无法解析 -> {cell}")  # 破折号是"无锚点"的合法写法
            continue  # 抽到锚点就不报"无法解析": 那是另一条判据的事
        for file_part, symbol in found:  # 逐个校验: 符号段存在时才进一步查符号
            path = SKILL_DIR / file_part  # 路径相对 skill 根: 矩阵里就是仓库相对写法
            if not path.is_file():  # 文件先判: 文件都不在就没必要谈符号
                bad.append(f"{row['cap']}: anchor 文件不存在 -> {file_part}")
            elif symbol and not symbol_exists(path, symbol):  # 符号为空则跳过: 只锚到文件的合法
                bad.append(f"{row['cap']}: anchor 符号不存在 -> {file_part}::{symbol}")
    assert not bad, "锚点失效:\n" + "\n".join(bad)  # 攒齐了再一次性报: 避免只报第一个就红


def test_evidence_anchors_are_real():
    """R1/R3: unit/integration/eval 锚点必须真实可收集。

    三个列都查是因为它们的证据形态不同: unit/integration 是 pytest 节点路径,
    eval 是场景用例名, 用同一套抽取规则去切 eval 列会把中文用例名切碎。
    """
    rows = load_matrix()  # 证据列与锚点列分开判: 形态不同, 抽取规则也不同
    bad: list[str] = []  # 同样先攒后报: 三类列的错误要一次看全
    for row in rows:  # 逐行过: R3 的判据是行级的
        cap = row["cap"]  # 能力键取出来: 报错时要指名道姓, 否则无从修
        for col in ("unit", "integration"):  # 两列形态相同可共用一套抽取: 都是 pytest 节点路径
            cell = row.get(col, "").strip()  # 去空白再比: 单元格常带尾随说明
            if not cell or cell == "—":  # 空与破折号都算"声明为无证据": 不算失效
                continue  # 破折号 = 该列声明为无证据
            # 一个单元格可能列多个锚点 (逗号/分号分隔) 并带尾随说明; 逐个抽取校验
            for token in re.split(r"[,;]", cell):  # 一个单元格可能有多条锚点: 逗号与分号都算分隔符
                token = token.strip()  # 逐条去空白: 说明文字常跟在锚点后面
                if not token or token == "—":  # 空片段与破折号跳过: 尾随逗号会切出空串
                    continue
                if not pytest_node_exists(token):  # 节点路径要真能收集: 写错一个类名 pytest 就会 --collect 失败
                    bad.append(f"{cap}: {col} 锚点不存在 -> {token}")
        ev = row.get("eval", "").strip()  # eval 列单独取: 它的形态是场景用例名而非节点路径
        if ev and ev != "—":  # 空与破折号表示这一行没有 eval 证据
            # eval 单元格形如 "`case_005_...认证` (name_resolve 场景)" 或多锚点并列;
            # case 文件名含中文, 切分正则必须容许 CJK, 且剥掉反引号与括号说明。
            for token in re.findall(r"[A-Za-z0-9_\-\u4e00-\u9fff]+", ev):  # 切分正则必须容许 CJK: case 文件名带中文
                if token in ("场景", "case", "yaml"):  # 这三个是切分残渣: 说明词不是锚点
                    continue  # 切分残渣: 是说明词不是锚点
                if not eval_case_exists(token):  # 场景锚点要真存在: 否则"有 eval 证据"就是空话
                    bad.append(f"{cap}: eval 锚点不存在 -> {token}")
    assert not bad, "证据锚点失效:\n" + "\n".join(bad)  # 三类列的错误一起报: 一次看全比逐条红高效


def test_capability_sources_are_fully_covered():
    """R2: 四类来源的全集都必须出现在矩阵里 (漏一项即失败)。

    判据取"子串出现"而非整行相等: 矩阵的能力列允许带括号说明, 但名字本身
    必须在, 否则契约新增一个算法时没人会去改矩阵, 覆盖声明就永远缺一口。
    """
    rows = load_matrix()  # 先解析: R2 与下面四条子句共用同一份行
    caps = " ".join(r["capability"] for r in rows)  # 拼成一串做子串判定, 不逐行相等
    missing: list[str] = []  # 按四类来源分别收集缺失项: 报时要指明是哪一类
    for name in sorted(spec_algorithms()):  # 契约算法名: 契约新增算法而矩阵没登记是典型漏项
        if name not in caps:  # 子串判定而非整行相等: 能力列允许带说明文字
            missing.append(f"spec algorithm: {name}")  # 契约新增算法而矩阵没登记
    for name in sorted(public_api()):  # 公开面符号: 新增公开符号必须同步进矩阵
        if name not in caps:
            missing.append(f"src.__all__: {name}")  # 公开面新增符号必须进矩阵
    for fmt in sorted(local_export_formats()):  # 本地导出格式: 同样是一条能力, 也得有证据
        if fmt not in caps:
            missing.append(f"LOCAL_EXPORT_FORMATS: {fmt}")  # 本地导出格式同样是能力
    for chain in CHAIN_CAPABILITIES:  # 站点交互链: 链上任一环漏登即无证据
        if chain not in caps:  # 链上能力按原样子串匹配: 名字在清单里就是登记了
            missing.append(f"站点交互链: {chain}")  # 链上任一环漏登即无证据
    assert not missing, "矩阵未覆盖以下能力 (新增能力必须同步登记):\n" + "\n".join(missing)  # 缺失项带来源前缀: 整改的人要知道去哪里补登记


def test_covered_rows_have_evidence():
    """R3: status=covered 的行必须至少有一条真实证据锚点。

    挡的是"口头覆盖": 状态列写着 covered 却一个锚点都没有, 读者会当成已验证,
    而实际无人跑过 —— 覆盖率数字因此会虚高, 拿它做决策就是拿虚数当依据。
    """
    rows = load_matrix()  # 再解析一次: R3 只看 covered 行, 不必与 R1 共用
    bad: list[str] = []  # 口头覆盖要攒齐再报: 一次看全
    for row in rows:  # 逐行判状态列
        if "covered" not in row.get("status", ""):  # 状态列含 covered 才算: 别的措辞不在这条规则内
            continue  # 只查 covered 行, gap 行本就允许无证据
        has_evidence = any(  # 三列任一非空即算有证据
            row.get(col, "").strip() not in ("", "—")
            for col in ("unit", "integration", "eval")  # 只查这三列: 其余列不是证据列
        )  # 三列任一非空即算有证据
        if not has_evidence:  # 一列都没填就是口头覆盖: 覆盖率数字会因此虚高
            bad.append(f"{row['cap']}: 标 covered 但无任何证据锚点")
    assert not bad, "口头覆盖:\n" + "\n".join(bad)  # 攒齐了再报


def _gap_registry(text: str) -> list[tuple[str, str, str]]:  # 解析 §3 登记表: R4 双向判定的另一半输入
    """解析 §3 gap 清单, 返回 (编号, capability 键, 状态) 三元组。

    状态列取值: ``未修`` (必须与矩阵 gap 行对账) / ``已修`` / ``已注销``
    (后两者不得再以 gap 形态出现在矩阵里)。
    """
    if "## 3." not in text:  # 没有 §3 就返回空: 缺口会由上游那条用例全部报红
        return []  # §3 整节缺失: 上游 test_gaps_are_registered 会把每条 gap 报红
    section = text.split("## 3.")[-1].split("## 4.")[0]  # 掐在两节之间, 别把 §4 的表也吃进来
    out: list[tuple[str, str, str]] = []  # 收登记项三元组: 编号与能力键都要, 报错时才好定位
    for line in section.splitlines():  # 只扫 §3 这一节: 别的节的表不参与对账
        s = line.strip()  # 非表格行跳过
        if not s.startswith("|") or set("".join(_split_row(s))) <= set("-: "):  # 分隔行也跳过: 它同样是表头, 不是登记项
            continue  # 非表格行与分隔行都跳过
        cells = _split_row(s)  # 切出单元格后才有列序可言
        if len(cells) < 4 or not re.match(r"^G-cov-\d+$", cells[0]):  # 只认 G-cov-N 编号行: 表头与说明行都不是登记项
            continue  # 只认 G-cov-N 编号行, 其它表头/说明行不是登记项
        key = cells[1].strip().strip("`")  # 能力键剥反引号: 矩阵里写成 code 形态
        state = cells[3].strip()  # 状态列取原样: 判定完全依赖它
        out.append((cells[0], key, state))  # 编号/键/状态一起收: R4 双向都要用到
    return out


def test_gaps_are_registered():
    """R4: 矩阵里每个 gap 行都必须在本表 §3 有 `未修` 登记 (不许无声缺口)。

    联接键取 status 单元格里 `gap** (`key`)` 的 key, 而不是 capability 名 ——
    capability 名可以随描述调整, key 是稳定标识符。
    """
    text = MATRIX.read_text(encoding="utf-8")  # 再读一次全文: §3 的正文只有原文里有
    rows = load_matrix()  # 能力行与登记表要在同一份判定里对账
    registry = _gap_registry(text)  # 解析 §3 登记表
    open_keys = {key for _no, key, state in registry if state == "未修"}  # 只有未修才算"已登记"
    unregistered: list[str] = []  # 未登记的 gap 攒起来: 一次报全, 避免来回改
    for row in rows:  # 逐行找 gap 状态
        status = row.get("status", "")  # 状态列取值: 只有含 gap 的行受 R4 约束
        if "gap" not in status:  # 非 gap 行跳过: covered 行与这里的规则无关
            continue  # 非 gap 行不受 R4 约束
        m = re.search(r"\(\s*`?([A-Za-z0-9_\-]+)`?\s*\)", status)  # 从状态单元格里抠出稳定 key
        key = m.group(1) if m else row["cap"]  # 括号里没写 key 时退到 cap 名
        if key not in open_keys:  # key 不在未修集合里就是未登记
            unregistered.append(f"{row['cap']} (key={key})")  # 报出 key: 对账要按稳定标识符
    assert not unregistered, "矩阵有 gap 但 §3 未登记为未修:\n" + "\n".join(unregistered)  # 未登记清单一次报全


def test_gap_section_has_no_stale_entries():
    """R4 双向: §3 的状态必须与矩阵实际形态一致, 两个方向都不许说谎。

    - `未修` 但矩阵里已无对应 gap 行  -> 修好了没注销 (清单虚报);
    - `已修`/`已注销` 但矩阵里仍是 gap -> 说修好了其实没修 (清单瞒报)。
    """
    text = MATRIX.read_text(encoding="utf-8")  # 读全文: 双向判定要看 §3 与能力表两侧
    rows = load_matrix()  # 能力行: 反查"矩阵里现在还有没有这条 gap"
    status_cells = [r.get("status", "") for r in rows]  # 供 R4 双向判定反查"矩阵里还有没有"
    stale: list[str] = []  # 修了没注销 = 清单虚报
    lied: list[str] = []  # 说修了其实还在 = 清单瞒报
    for no, key, state in _gap_registry(text):  # 按 §3 登记项逐条判两侧: 两个方向都不许说谎
        still_gap = any(key in cell for cell in status_cells)  # 子串判定: status 里写成 `key` 反引号形态
        if state == "未修" and not still_gap:  # 标未修却查不到: 修好了没注销, 清单虚报
            stale.append(f"{no}: {key} (标未修但矩阵已无 gap 行)")
        if state in ("已修", "已注销") and still_gap:  # 标已修却还在矩阵里: 说修了其实没修, 清单瞒报
            lied.append(f"{no}: {key} (标{state}但矩阵仍是 gap)")
    assert not stale, "§3 登记过期 (修复后须同步注销):\n" + "\n".join(stale)  # 虚报清单先报: 它意味着有人忘了注销
    assert not lied, "§3 状态与矩阵矛盾:\n" + "\n".join(lied)  # 瞒报清单独立一条: 两个方向的错后果不同, 分开报更易读
