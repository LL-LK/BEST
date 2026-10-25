# -*- coding: utf-8 -*-
"""module 路径真实性门禁 — spec 与契约声明的每条模块路径都必须真实可导入。

风险形态: contracts/io-contract.md 很容易把 BestQueryResult 标成
``astro_best`` 模块, 而 src/ 下从来没有这个包 (权威处是 src.models);
templates/gen_config_template.yaml 也带着 6 处死路径活了很久。根因不是没人 review,
而是**没有任何测试校验 ``module:`` 路径可导入** — test_gen_contracts 只查契约
文件存在与 gates 相等, 于是死路径可以无限期存在而不被发现。

本文件把「路径真实」变成 CI 可判定命题, 四个来源全覆盖:

  S1 ``references/skills-spec.local.yaml`` 的每个 ``algorithms[].module`` 必须
     可导入 (importlib.import_module), 且该模块里必须存在同名符号 (AST 静态
     判定, 不执行模块体, 因此不触发 import 副作用);
  S2 ``contracts/io-contract.md``「核心白盒算子」表里每个 `` `符号` (module) ``
     同样必须可导入且符号存在 — 那里正是 astro_best 死路径的案发地;
  S3 ``contracts/*.yaml`` 与 ``contracts/fields/*.yaml`` 里出现的每个
     ``module:`` 值必须可导入 (当前契约尚无该键, 扫描逻辑先行落地, 补键即生效)。
  S4 ``references/ALGORITHM-SPEC.md`` 白盒锚点: 文中每个
     `` `src/xxx.py`` `` 模块引用必须真实存在且可导入; §2 锚点表的关键符号另用
     钉住表逐条校验 — 该表很容易把 BestQueryResult 锚到 src/query.py (权威处是
     src.models)、BestAuth 只标再导出壳 src/client.py, 而 S1/S2/S3 都扫不到它。

失败信息必须指名「哪个文件哪一行的哪个模块路径无效」, 因此行号一律取自 YAML
节点的 ``start_mark`` 与 Markdown 的物理行号, 不做模糊的集合差集报告。

依赖缺失 (如 astropy 未安装) 与「模块不存在」是两件事, 必须分开: 前者显式
skip 并说明缺哪个包, 后者直接 fail — 否则没装依赖的环境会让门禁恒红, 装齐的
环境恒绿, 两种都等于没有门禁。
"""
from __future__ import annotations  # 标准库: 注解延迟求值

# 标准库: importlib 动态导入 (可导入性判定) / AST 静态解析 (符号存在性判定) /
# 正则抽取 Markdown 算子条目 / lru_cache 缓存节点树 / sys.path 锚定 /
# 路径与类型标注
import ast  # AST 静态解析: 符号存在性判定必须零依赖零副作用
import importlib  # 动态导入: 可导入性判定的唯一手段, 静态路径运算替代不了
import re  # 正则抽取 Markdown 算子条目与模块引用: 两处扫描都要靠它
import sys  # sys.path: 本文件脱离 conftest 单独跑时也要能定位 src.*
from functools import lru_cache  # lru_cache: spec 节点树同一次运行只读一次盘
from pathlib import Path  # 路径与类型标注: 源文件定位与节点遍历的返回类型都靠它
from typing import Any, Iterator

# 第三方: pytest 断言与 skip + yaml.compose (组成节点树并保留行号)
import pytest  # pytest 断言与 skip: 缺依赖要跳过而不是判死路径
import yaml  # compose 而非 safe_load: 只有节点树带行号, 失败信息必须指名行

# 路径锚点: 本文件位于 <skill>/test/unit/meta/, 上溯 3 层即 skill 根
SKILL_DIR = Path(__file__).resolve().parents[3]  # 上溯三级到 skill 根: 本文件位于单元测试的 meta 层
# 本门禁的四个扫描对象: 规范切片 / 契约目录 / I/O 契约的算子表 / 白盒 spec
SPEC_PATH = SKILL_DIR / "references" / "skills-spec.local.yaml"  # S1 的声明源
CONTRACTS_DIR = SKILL_DIR / "contracts"  # S3 的扫描根
IO_CONTRACT_MD = CONTRACTS_DIR / "io-contract.md"  # S2 的算子表 (astro_best 死路径的案发地)
ALGO_SPEC_MD = SKILL_DIR / "references" / "ALGORITHM-SPEC.md"  # S4 的白盒锚点表

# 已知可选第三方依赖: 缺失时判「依赖缺失」(skip) 而非「模块不存在」(fail)
OPTIONAL_DEPS = frozenset({"astropy"})  # 只登记已知可选项: 其余缺包一律按第三方报

# io-contract.md 算子条目形如 "- `BestAuth` (src.auth.session)": 抽符号与模块路径
_OPERATOR_RE = re.compile(r"^-\s*`([A-Za-z_]\w*)`\s*\(([A-Za-z_][\w.]*)\)\s*$")  # 行尾锚定: 正文里的提及不误抓

# S4: ALGORITHM-SPEC.md 里的模块文件引用形如 `src/client.py` / `src/auth/session.py`
_SPEC_MODULE_RE = re.compile(r"`(src/[\w/]+\.py)`")  # 只认反引号包裹的文件路径

# S4: §2 锚点表的关键符号 -> 权威模块 (与文档措辞一一对应; 这张表钉住的原因是
# BestQueryResult 容易被锚到 src/query.py, BestAuth 容易被只标再导出壳
# src/client.py, csv_safety 容易被当模块名而非符号; 这些漂移 S1/S2/S3 都扫不到)
ALGO_SPEC_SYMBOL_ANCHORS: tuple[tuple[str, str], ...] = (
    ("BestQueryResult", "src.models"),
    ("BestAuth", "src.auth.session"),
    ("sanitize_cell", "src.csv_safety"),
    ("validate_adql_query", "src.scripts.guards"),
    ("build_query_form", "src.protocol"),
    ("parse_csv_rows", "src.protocol"),
    ("BestDownloader", "src.downloader"),
    ("DownloadManager", "src.download_manager"),
    ("ToolBox", "src.ai_tools"),
    ("BestClient", "src.client"),
)

# 把 skill 根挂上 sys.path: 脱离 conftest 单独运行本文件时也能定位 src.*
if str(SKILL_DIR) not in sys.path:  # 只在缺席时插入: 重复插入会让 sys.path 里出现两条同样的根
    sys.path.insert(0, str(SKILL_DIR))  # 挂到最前: src.* 必须先于任何已安装的同名包被解析


def _module_source_path(module_name: str) -> Path | None:
    """把点分模块名解析成 skill 内的源文件 (纯路径运算, 不导入任何父包)。

    不走 ``importlib.util.find_spec``: find_spec 为定位子模块会先导入父包,
    于是 ``src/__init__.py`` 的整条客户端依赖链被拖进来, 缺 requests 的环境
    连「路径拼写对不对」都判不了。纯路径运算让符号检查零依赖、零副作用。

    Args:
        module_name: 点分模块名, 例如 ``src.tap.service``。

    Returns:
        源文件路径; 既不是 ``<名>.py`` 也不是 ``<名>/__init__.py`` 时返回 None。
    """
    base = SKILL_DIR.joinpath(*module_name.split("."))  # 纯路径运算: 不 import, 故无父包副作用
    # 两种候选形态都要试: 叶子既可能是 <名>.py, 也可能是 <名>/__init__.py 的包,
    # 只认前者会把合法的包声明误判成"路径无效"
    for candidate in (base.parent / f"{base.name}.py", base / "__init__.py"):  # 叶子既可能是模块也可能是包: 只认前者会把合法包判成死路径
        if candidate.is_file():  # 命中任一候选即算定位成功
            return candidate  # 定位到的文件交给静态符号检查
    return None  # 两种形态都不中即路径无效: 这才是真正的死路径形态


def _top_level_symbols(path: Path) -> set[str]:
    """抽取模块顶层符号名: 定义 (类/函数/常量) 与再导出 (import 别名) 都算。

    再导出算符号的理由: ``from src.auth.session import BestAuth`` 之后
    ``src.client.BestAuth`` 运行时就存在, ``hasattr`` 也为真 — 薄壳路径是既有
    公开面, 判死它会误伤。真正的死路径是两者都找不到 (例如 ``astro_best``)。

    Args:
        path: 模块源文件路径。

    Returns:
        顶层符号名集合 (含 import 别名)。
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))  # 解析整个源文件: 只做文本包含会被注释与 docstring 骗过
    names: set[str] = set()  # 顶层符号名集合: 类/函数/常量/再导出都收进来
    for node in tree.body:  # 只扫模块体: 嵌套定义不算顶层公开面
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):  # 类与两种函数形态都算符号
            names.add(node.name)  # 函数名直接入集合
        elif isinstance(node, ast.Assign):  # 普通赋值的裸名字目标
            names.update(t.id for t in node.targets if isinstance(t, ast.Name))  # 一行可解包出多个目标, 逐个收
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):  # 带注解的赋值单列一支: 它的目标不在 targets 上
            names.add(node.target.id)  # 带注解的赋值目标不在 targets 上, 单列一支
        elif isinstance(node, (ast.Import, ast.ImportFrom)):  # import 与 from import 都要看: 再导出就是公开面
            names.update(a.asname or a.name.split(".")[0] for a in node.names)  # 再导出即公开面
    return names  # 顶层符号收齐后返回: 薄壳路径正是靠这一支被判为合法


def _import_module(module_name: str) -> tuple[Any, str, str]:
    """导入模块并分类结果, 返回 (模块对象或 None, 状态, 详情)。

    状态四义:
      ``ok``         导入成功;
      ``missing``    模块路径本身不存在 (缺的正是目标模块或它的某个父包);
      ``dependency`` 缺第三方依赖或环境不兼容 — 与「路径不存在」必须分开;
      ``broken``     导入即抛非 ImportError 异常 (真实缺陷, 不许静默)。

    Args:
        module_name: 被导入的点分模块名。

    Returns:
        (模块对象或 None, 状态, 人类可读详情)。
    """
    try:  # 真正动手导入: 静态判据管不了"能不能导进来"
        return importlib.import_module(module_name), "ok", ""  # 成功即返回三元组: 状态字面量是下游分支的入口
    except ModuleNotFoundError as exc:  # 缺模块要细看 exc.name: 目标模块缺与依赖缺是两件事
        gone = exc.name or ""  # exc.name 指向真正缺的那个包, 而未必是目标模块本身
        # exc.name 指向真正缺的那个包: 只有它等于目标模块本身或其前缀时, 才能
        # 断定是"声明的路径写错了"; 否则是第三方依赖没装, 判错会让没装环境恒红
        if gone == module_name or module_name.startswith(f"{gone}."):  # 前缀匹配才认: 父包缺等于目标模块同样不可达
            return None, "missing", gone  # 前缀匹配才认: 父包缺 = 目标模块同样不可达
        kind = "已知可选依赖" if gone in OPTIONAL_DEPS else "第三方依赖"  # 已知可选项单独措辞: 报错要说清是"可选"还是"必须"
        return None, "dependency", f"{kind} {gone} 缺失"  # 缺依赖走 skip, 不判死路径
    except ImportError as exc:  # 导入了但链上缺包: 同样归为依赖缺失, 不判死路径
        return None, "dependency", f"ImportError: {exc}"  # 导入了但链上某个包不在
    except Exception as exc:  # noqa: BLE001 - 记入失败, 不静默吞
        return None, "broken", f"{type(exc).__name__}: {exc}"  # 非 ImportError = 导入即崩, 真实缺陷


def check_symbol_static(module_name: str, symbol: str, where: str) -> tuple[str, str]:
    """只做静态符号检查 (不导入模块), 返回 (结论, 说明); 结论为 pass/skip/fail。

    与 :func:`check_module_ref` 的分工: 这条零依赖也能跑 — 「路径写错」是拼写
    问题, 不需要把 requests/astropy 装齐就能判死, 因此它是最基础的一道闸。

    Args:
        module_name: 被声明的模块路径。
        symbol: 该模块里必须存在的同名符号。
        where: 声明出处 (``文件:行``), 失败信息必须带它。

    Returns:
        (``pass``, "") / (``skip``, 原因) / (``fail``, 原因)。
    """
    path = _module_source_path(module_name)  # 先定位源文件: 静态判据要先知道文件在哪
    if path is None:  # 定位不到就跳过: 这不是结论, 让位给导入判定
        return "skip", f"{where}: 源文件定位不到 {module_name} (交由导入检查判定)"  # 不是结论, 是让位
    if symbol in _top_level_symbols(path):  # 顶层符号命中即通过
        return "pass", ""
    return "fail", f"{where}: 模块 {module_name} ({path.name}) 不存在顶层符号 {symbol}"  # 带上文件名便于人工核对


def check_module_ref(module_name: str, symbol: str | None, where: str) -> tuple[str, str]:
    """校验一条 (模块, 符号) 声明, 返回 (结论, 说明); 结论为 pass/skip/fail。

    先判可导入 (依赖缺失只 skip 不 fail), 再判符号存在 (优先 AST 静态判定,
    源文件定位不到才退回运行期 ``hasattr``); ``symbol`` 为 None 表示只校验
    模块路径本身 (contracts YAML 的 ``module:`` 就是这种形态)。

    Args:
        module_name: 被声明的模块路径 (点分名)。
        symbol: 该模块里必须存在的同名符号; None 表示不校验符号。
        where: 声明出处 (``文件:行``)。

    Returns:
        (``pass``, "") / (``skip``, 原因) / (``fail``, 原因)。
    """
    module, status, detail = _import_module(module_name)  # 先做导入判定: 可导入性是符号判定的前提
    # 判定次序即语义次序: 先分清"依赖缺失"与"路径无效", 再谈符号。顺序颠倒
    # 会把没装 astropy 的环境报成死路径, 那正是本门禁最初最招人烦的误报
    if status == "dependency":  # 依赖缺失先分出来: 顺序颠倒会把没装包的环境报成死路径
        return "skip", f"{where}: 依赖缺失无法判定 {module_name} ({detail})"  # skip 而非 fail: 没装 astropy 不等于声明写错了
    if status == "missing":  # 模块路径无效才是 fail: 这条才是门禁真正要抓的东西
        return "fail", f"{where}: 模块路径无效 {module_name} (不存在: {detail})"  # 把真正缺的那个包名带上: 整改的人要据此去改声明
    if status == "broken":  # 导入即崩也判 fail: 崩了是缺陷, 不能降级成环境问题
        return "fail", f"{where}: 模块 {module_name} 导入即崩 ({detail})"  # 崩了是真实缺陷, 不降级成 skip
    if symbol is None:  # symbol 为 None 表示只校验路径
        return "pass", ""  # 只校验路径形态 (contracts YAML 的 module: 就是这种)
    static, static_detail = check_symbol_static(module_name, symbol, where)  # 静态符号判据作为首选: 零依赖且比 hasattr 严格
    if static == "fail":  # 静态判出 fail 就到此为止
        return "fail", static_detail  # 静态判据优先: 零依赖且比 hasattr 更严格
    # 静态判据走到 skip (源文件定位不到) 才退回运行期 hasattr: 宁可多跑一次
    # 导入, 也不愿因路径解析器覆盖不全而漏判一个真死符号
    if static == "skip" and not hasattr(module, symbol):  # 静态判据只能 skip 时才退回运行期: 宁可多导一次也不漏判
        return "fail", f"{where}: 模块 {module_name} 可导入但不存在符号 {symbol}"  # 可导入但没这个符号: 这是最隐蔽的一类死声明
    return "pass", ""  # 两条判据都过才算真的过


@lru_cache(maxsize=1)
def _spec_root() -> yaml.Node:
    """组成 spec 节点树并缓存 (同一次运行内多次扫描只读一次盘)。

    缓存用 maxsize=1 而不是按路径分键: 全仓只有这一份 spec 切片, 键再细也
    只有一个取值, 而多一次键计算就多一次出错机会。
    """
    return yaml.compose(SPEC_PATH.read_text(encoding="utf-8"))  # compose 出节点树: 行号信息只有它带


def _dig(node: Any, *keys: str) -> Any:
    """按键路径在 YAML 映射节点里逐层下钻, 任一层缺失返回 None。

    Args:
        node: 起始节点 (通常是文档根映射)。
        keys: 依次下钻的键名, 例如 ``("skills", "astro-best", "algorithms")``。

    Returns:
        末键对应的值节点, 或 None。
    """
    current: Any = node  # 下钻起点就是根节点
    for key in keys:  # 按给定键序逐层下钻
        if not isinstance(current, yaml.MappingNode):  # 当前层不是映射即中断: 半条目不该抛异常
            return None  # 键没走到映射就断了 = 该层不存在, 不抛
        nxt = None  # 线性扫键: 节点树没有索引, 而这些映射的键数很少
        for key_node, value_node in current.value:  # 线性扫: 节点树无索引, 键少时够用
            if key_node.value == key:  # 键名相等即命中: YAML 键是标量字符串
                nxt = value_node  # 记住值节点: 命中后还要继续往下走
                break
        if nxt is None:  # 没命中就是缺键
            return None  # 缺键即 None, 由调用方决定是不是"半条目"
        current = nxt  # 下沉一层: 下一轮按同一个键继续找
    return current  # 走完全部键才返回


def _iter_module_values(node: Any) -> Iterator[tuple[int, str]]:
    """递归遍历 YAML 节点树, 产出每个 ``module:`` 值的 (行号, 模块路径)。

    用 ``yaml.compose`` 而不是 ``safe_load``: 只有节点树带 ``start_mark``,
    失败信息才能指名「哪个文件哪一行」; safe_load 会把行号信息全丢掉。

    Args:
        node: 待遍历的 YAML 节点。

    Yields:
        (行号, 模块路径) — 行号为 1 基物理行。
    """
    if isinstance(node, yaml.MappingNode):  # 映射节点才有键值对
        for key_node, value_node in node.value:  # 逐对处理
            if key_node.value == "module" and isinstance(value_node, yaml.ScalarNode):  # 键名与节点类型都要对: 非标量的 module 值不是路径
                yield value_node.start_mark.line + 1, str(value_node.value)  # 1 基物理行: 与报错口径一致
            else:  # 非 module 键要继续下钻, 不能就此停下
                yield from _iter_module_values(value_node)  # 非 module 键: 递归进值里继续找
    elif isinstance(node, yaml.SequenceNode):  # 序列节点也要遍历
        for item in node.value:  # 序列项逐个下钻
            yield from _iter_module_values(item)  # 序列项也要下钻, 否则漏掉数组里的契约


def spec_algorithm_refs() -> list[tuple[int, str, str]]:
    """抽出 spec algorithms 的 (行号, 模块路径, 符号名)。

    Returns:
        三元组列表; 行号取自条目内 ``module`` 键所在行 (缺 module 时退到条目首行)。
    """
    seq = _dig(_spec_root(), "skills", "astro-best", "algorithms")  # 按技能名定位到 algorithms 序列
    if not isinstance(seq, yaml.SequenceNode):  # 结构不符就返回空: 让下游的非空断言顶回来
        return []  # 切片结构变了: S1 两条用例的非空断言会顶回来
    refs: list[tuple[int, str, str]] = []  # 收 (行, 模块, 符号) 三元组
    for item in seq.value:  # 逐条算法条目
        if not isinstance(item, yaml.MappingNode):  # 非映射项不是算法条目
            continue  # 非映射项不是算法条目
        name_node = _dig(item, "name")  # 算法名节点
        module_node = _dig(item, "module")  # 模块节点: 这两个都可能缺
        # 缺 module 时锚到条目首行: 半条目本身就是漂移信号, 行号得指向条目
        # 让人看得见"这里少了 module", 而不是指向一个不存在的键
        anchor = module_node if module_node is not None else item  # 缺 module 时锚到条目首行: 让报错指得准
        refs.append((anchor.start_mark.line + 1,  # 行号取自锚点节点: 键级锚点比条目级精确
                     str(module_node.value) if module_node is not None else "",  # 空串=半条目, 交给断言判红
                     str(name_node.value) if name_node is not None else ""))  # 符号名同样容许为空串: 空串由断言判成半条目
    return refs  # 收齐后返回: 下面两条用例共用这一份


def io_contract_operator_refs() -> list[tuple[int, str, str]]:
    """抽出 io-contract.md 算子表的 (行号, 符号, 模块路径)。

    Returns:
        三元组列表; 只认 ``- `符号` (模块)`` 形态的列表项, 正文与说明块不误抓。
    """
    refs: list[tuple[int, str, str]] = []
    text = IO_CONTRACT_MD.read_text(encoding="utf-8")  # 读全文逐行扫: Markdown 没有节点树, 行号只能按物理行算
    for lineno, line in enumerate(text.splitlines(), 1):  # 物理行号: Markdown 没有节点树
        matched = _OPERATOR_RE.match(line.strip())  # 正则要行首锚定: 正文里提到的符号名不该被误抓成条目
        if matched:  # 只认行首列表项形态
            refs.append((lineno, matched.group(1), matched.group(2)))  # 收 (行, 符号, 模块): 注意顺序与校验器要的相反
    return refs  # 算子条目收齐后返回


def contract_module_refs() -> list[tuple[str, int, str]]:
    """扫描 contracts/ 下所有 YAML, 产出 (文件, 行号, 模块路径)。

    Returns:
        三元组列表; 文件为相对 skill 根的 POSIX 风格路径。
    """
    refs: list[tuple[str, int, str]] = []  # 收 (文件, 行, 模块) 三元组
    # sorted 是为了失败信息的次序稳定: rglob 的遍历顺序随文件系统而变, 同一
    # 份契约在不同机器上会报出不同顺序的同名问题, 整改时难以逐条销账
    for path in sorted(CONTRACTS_DIR.rglob("*.yaml")):  # 排序遍历: 失败信息的次序必须跨机稳定, 否则无法逐条销账
        try:  # 解析失败不能中断整轮
            root = yaml.compose(path.read_text(encoding="utf-8"))  # 逐个契约文件 compose 出节点树
        except yaml.YAMLError:  # 语法错由另一条门禁负责: 这里重复报只会双份噪声
            continue  # 解析失败的契约由 test_gen_contracts 报, 不在这里重复
        for line, module in _iter_module_values(root):  # 从节点树里收所有 module 值
            refs.append((path.relative_to(SKILL_DIR).as_posix(), line, module))  # 相对路径: 跨机报错可比对
    return refs


def _collect(entries: list[tuple[str, str, str | None]]) -> tuple[list[str], list[str]]:
    """逐条校验 (声明处, 模块, 符号), 汇总失败与跳过两类信息。

    Args:
        entries: (where, module, symbol) 三元组列表; symbol 为 None 表示只校验模块。

    Returns:
        (失败信息列表, 跳过信息列表)。
    """
    failures: list[str] = []  # 失败与跳过分开收: 两者对人的含义完全不同
    skips: list[str] = []  # 跳过也必须留痕: "全 skip"看着像"全过"
    for where, module, symbol in entries:  # 逐条声明送进校验器
        outcome, detail = check_module_ref(module, symbol, where)  # 校验器返回 (结论, 说明) 二元组
        if outcome == "fail":  # 只有 fail 进失败清单
            failures.append(detail)  # 收集而非首错即抛: 一次跑批给全清单
        elif outcome == "skip":  # skip 单独归类
            skips.append(detail)  # skip 也要留痕, 否则"全 skip"看着像全过
    return failures, skips  # 两类信息一并返回: 调用方按用例决定怎么报


def algo_spec_module_refs() -> list[tuple[int, str]]:
    """抽出 ALGORITHM-SPEC.md 里每个 `` `src/xxx.py` `` 引用的 (行号, 点分模块名)。

    Returns:
        (物理行号, 模块名) 列表; 模块名由文件路径推导 (去掉 .py, / 换 .)。
    """
    refs: list[tuple[int, str]] = []  # 收 (行号, 模块名) 二元组
    for lineno, line in enumerate(ALGO_SPEC_MD.read_text(encoding="utf-8")  # 读白盒 spec 全文: Markdown 侧只能按物理行扫
                                  .splitlines(), 1):
        for match in _SPEC_MODULE_RE.finditer(line):  # 一行可能引用多个模块路径
            rel = match.group(1)  # 取反引号里的文件路径
            # 文档里写的是文件路径, 判定要的是点分模块名: 去后缀 + 换分隔符。
            # 不做这层换算, 后面所有 importlib 判定都会以"路径不存在"收场
            module = rel[:-3].replace("/", ".") if rel.endswith(".py") else rel.replace("/", ".")  # 文档写文件路径而判定要点分模块名: 不换算后面全部会以"不存在"收场
            refs.append((lineno, module))  # 换算后连行号一起收: 报错要能指名是哪一行
    return refs  # 引用收齐后返回


def test_scanners_find_their_targets():
    """防真空: 扫描器必须各自抓到声明, 否则「全绿」可能是什么都没查。

    门禁最隐蔽的失效形态不是报错, 是正则/路径写错后 silently 扫到 0 条 —
    那时断言恒真, 覆盖率为零。这里用非空断言把这种形态顶回来。
    """
    assert SPEC_PATH.is_file(), f"spec 切片缺失: {SPEC_PATH}"  # spec 切片必须真的在: 缺了 S1 整组用例都在空集上跑
    assert io_contract_operator_refs(), "io-contract.md 算子表扫描为空 (正则可能失效)"  # 扫到 0 条时断言恒真
    assert spec_algorithm_refs(), "spec algorithms 扫描为空 (切片结构可能被改动)"  # 非空断言挡"正则悄悄失效": 扫到 0 条时断言恒真
    assert list(CONTRACTS_DIR.rglob("*.yaml")), "contracts/ 下没有 YAML 可扫"  # 没有 YAML 可扫时 S3 无从谈起
    assert ALGO_SPEC_MD.is_file(), f"白盒 spec 缺失: {ALGO_SPEC_MD}"  # 白盒 spec 必须在
    assert algo_spec_module_refs(), "ALGORITHM-SPEC.md 模块引用扫描为空 (正则可能失效)"  # S4 同样要非空: 扫不到引用等于这条门禁从未生效


def test_spec_algorithm_symbols_exist_statically():
    """S1 静态半边: spec algorithms 的每个符号必须能在其模块顶层找到 (不导入)。"""
    failures: list[str] = []  # 静态半边不导入: 缺依赖的环境也要能判路径与符号
    skipped = 0  # 跳过计数: 全跳过是失效信号, 不是通过
    for line, module, symbol in spec_algorithm_refs():  # 逐个算法条目
        where = f"references/skills-spec.local.yaml:{line}"  # 行号让报错能直接定位到条目
        if not module or not symbol:  # 半条目直接判红: 缺 module 或缺 name 都是漂移
            failures.append(f"{where}: algorithms 条目缺 module/name (半条目即漂移)")  # 报出文件与行号: 整改的人要能直接跳过去
            continue
        outcome, detail = check_symbol_static(module, symbol, where)  # 走静态符号判据
        if outcome == "fail":  # 只有 fail 才累加
            failures.append(detail)
        skipped += outcome == "skip"  # 布尔加法: 计数不必写 if
    assert not failures, "spec algorithms 符号缺失:\n" + "\n".join(failures)  # 失败清单一次报全
    # 全部 skip 意味着源文件一个都定位不到, 那不是"通过"而是路径基准整体错了;
    # 少了这条, 路径前缀写错时整条用例会静静地产出 0 条失败并显示绿
    assert skipped < len(spec_algorithm_refs()), "全部条目都定位不到源文件 (路径基准可能错了)"  # 全跳过说明路径基准整体错了: 少了这条, 路径前缀写错时会静静地产出 0 条失败


def test_spec_algorithm_modules_are_importable():
    """S1 动态半边: spec algorithms 的每个 module 必须可导入且存在同名符号。

    ``astro_best`` 这类死路径在此处必红 — 它既不在 src/ 下, 也没人再导出。
    """
    entries: list[tuple[str, str, str]] = []  # 收 (出处, 模块, 符号) 三元组
    malformed: list[str] = []  # 半条目单独收: 不与导入失败混在一起
    for line, module, symbol in spec_algorithm_refs():  # 逐个算法条目
        where = f"references/skills-spec.local.yaml:{line}"  # 出处带行号: 报错必须指名哪一行
        if module and symbol:
            entries.append((where, module, symbol))  # 齐备的才进导入判定
        else:
            malformed.append(f"{where}: algorithms 条目缺 module/name")  # 半条目单独报, 不混进 failures
    assert not malformed, "spec algorithms 存在半条目:\n" + "\n".join(malformed)
    assert entries, "spec 未解析出 algorithms 条目"  # 空集会让下面两条断言恒真
    failures, skips = _collect(entries)  # 一次校验全部条目
    assert not failures, "spec algorithms 模块路径失效:\n" + "\n".join(failures)  # 路径失效清单报全
    # 全军覆没才 skip: 缺一两个包与"整条判定从未生效"必须能区分开, 否则一个
    # 恒真的 skip 会长期伪装成通过, 门禁就此失效而无任何信号
    if len(skips) == len(entries):  # 全跳过才 skip: 缺一两个包与"判定从未生效"必须能区分
        pytest.skip("全部条目因依赖缺失无法判定: " + "; ".join(skips))  # 带出原因再跳过: 让人知道该装什么包


def test_io_contract_operator_paths_are_real():  # S2 盯着 astro_best 事故原址: 契约里的模块路径需有人校验
    """S2: io-contract.md 算子表的每条 (符号, module) 都必须真实存在。

    这条直接盯着 astro_best 事故原址: 契约文档里的模块路径一旦没有测试
    校验, 写错就能活很久。
    """
    refs = io_contract_operator_refs()  # 抽出算子条目
    entries = [(f"contracts/io-contract.md:{line}", module, symbol)  # 出处带行号
               for line, symbol, module in refs]  # 扫描器给的是 (行, 符号, 模块), 校验器要 (出处, 模块, 符号)
    assert entries, "io-contract.md 未解析出算子条目 (表格式可能被改动)"  # 空表时后续断言全恒真
    failures, skips = _collect(entries)  # 统一走校验器
    assert not failures, "io-contract.md 算子路径失效:\n" + "\n".join(failures)  # 算子路径失效清单报全
    if len(skips) == len(entries):  # 全跳过才 skip
        pytest.skip("全部条目因依赖缺失无法判定: " + "; ".join(skips))


def test_contract_yaml_module_paths_are_importable():  # S3 只要求可导入: 契约目前没有 module 键, 补键即生效
    """S3: contracts/**.yaml 里的 module: 值必须可导入 (当前无该键则显式 skip)。"""
    refs = contract_module_refs()  # 先扫出所有 module 声明
    if not refs:  # 一条都没有就显式跳过: 留痕好过悄悄通过
        pytest.skip("contracts/ 下暂无 module: 声明 (扫描逻辑已落地, 补键即生效)")
    # 契约 YAML 只声明 module, 不强制要求符号 — 模块能导入即算过
    entries = [(f"{rel}:{line}", module, None) for rel, line, module in refs]  # symbol=None = 只校验可导入
    failures, skips = _collect(entries)  # 统一走校验器
    assert not failures, "contracts YAML 模块路径失效:\n" + "\n".join(failures)  # 契约路径失效清单报全
    if len(skips) == len(entries):  # 全跳过才 skip: 否则恒真的 skip 会长期伪装成通过
        pytest.skip("全部条目因依赖缺失无法判定")


def test_algo_spec_module_paths_are_real():  # S4 动态半边: 白盒 spec 的锚点表不在前三道门的扫描范围内
    """S4 动态半边: ALGORITHM-SPEC.md 引用的每个 src 模块必须可导入。

    要覆盖的空白: 白盒 spec 的锚点表 (端点/超参/真源码锚点) 不在
    S1/S2/S3 任何一门禁的扫描范围内, BestQueryResult 被锚到 src/query.py
    这类漂移可以无限期存活。本测试把 spec 里的模块引用纳入 CI。
    """
    refs = algo_spec_module_refs()  # 抽出模块引用
    entries = [(f"references/ALGORITHM-SPEC.md:{line}", module, None)  # 出处带行号
               for line, module in refs]  # 文档只给了文件路径, 无符号可校验
    failures, skips = _collect(entries)  # 统一走校验器
    assert not failures, "ALGORITHM-SPEC.md 模块引用失效:\n" + "\n".join(failures)  # 模块引用失效清单报全
    if len(skips) == len(entries):  # 全跳过才 skip
        pytest.skip("全部条目因依赖缺失无法判定: " + "; ".join(skips))


def test_algo_spec_symbol_anchors_hold():  # S4 符号半边: 防锚点从权威模块漂到别处
    """S4 符号半边: §2 锚点表的关键符号必须钉在权威模块上 (防锚点漂移)。

    钉住表 :data:`ALGO_SPEC_SYMBOL_ANCHORS` 与 ALGORITHM-SPEC.md §2 的措辞
    一一对应; 文档改锚点而忘了改钉住表 (或反之) 时, 这里先红 — 两类漂移
    (符号搬到别的模块 / 文档锚点写错) 都逃不过。
    """
    failures: list[str] = []  # 失败逐条收
    for symbol, module in ALGO_SPEC_SYMBOL_ANCHORS:  # 钉住表逐条查, 漂哪条报哪条
        outcome, detail = check_symbol_static(  # 静态判据即可: 这一半不依赖运行环境
            module, symbol, f"ALGO_SPEC_SYMBOL_ANCHORS:{symbol}->{module}")
        if outcome == "fail":  # 只有 fail 才累加
            failures.append(detail)
    assert not failures, "白盒 spec 符号锚点漂移:\n" + "\n".join(failures)  # 锚点漂移清单报全


def test_executable_gates_are_decidable():
    """可执行门禁必须四键齐备 (name/cmp/value/unit) 且阈值类型可判定。

    半条门禁比没有门禁更危险: 名字在、阈值缺, 读的人会以为有判定, 跑的人
    根本无从比起。
    """
    spec = yaml.safe_load(SPEC_PATH.read_text(encoding="utf-8")) or {}  # safe_load 即可: 这条只看结构, 不需要行号
    gates = ((spec.get("skills") or {}).get("astro-best") or {}).get("executable_gates") or []  # 取可执行门禁清单
    assert gates, "spec 未声明 executable_gates (四条可执行门禁)"  # 空列表会让下面的坏键检查恒真
    required = {"name", "cmp", "value", "unit"}  # 四键缺一即不可判定
    bad = [f"executable_gates[{i}] ({g.get('name')}): 缺键 {sorted(required - set(g))}"  # 攒出缺了哪些键
           for i, g in enumerate(gates) if not required <= set(g)]
    assert not bad, "可执行门禁结构不完备:\n" + "\n".join(bad)  # 结构不完备清单报全
    for gate in gates:  # 逐条门禁看阈值类型
        value = gate["value"]  # 取阈值
        # cmp 决定阈值能是什么类型: 恒等门禁额外接受 bool (True/False 本身就是
        # 有意义的阈值), 比较型不接受 —— 否则 False 会被当成 0 静默通过
        if gate["cmp"] == "==":  # 恒等门禁单独判: 它额外接受布尔, 那是有效阈值
            # 恒等门禁只允许标量, 否则求值时类型不匹配会静默误判
            assert isinstance(value, (bool, int, float, str)), (  # 恒等门禁只允许标量: 否则求值时类型不匹配会静默误判
                f"门禁 {gate['name']} 的 value 不是标量: {value!r}")
        else:
            # 比较型必须排除 bool: Python 里 False 会当 0 静默通过
            assert isinstance(value, (int, float, str)) and not isinstance(value, bool), (  # 比较型必须排除布尔: Python 里 False 会当 0 静默通过
                f"门禁 {gate['name']} 的 value 不可比较: {value!r}")
