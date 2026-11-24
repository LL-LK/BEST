# -*- coding: utf-8 -*-
"""交叉引用机械核实脚本 (只读不写; make audit 的硬门禁之一)。

核实九类引用 (序号与下方 ``# ── N.`` 分节一一对应; 覆盖面**必须**在本 docstring
里逐条列全 —— 靠 docstring 判断门禁范围的人, 漏掉第 5~9 项就会严重误判
门禁覆盖面):

1. references/skills-spec.local.yaml 里 ``algorithms[].module`` 是否可解析;
2. contracts/ 与 templates/ 下全部 YAML 的 ``module:`` / ``<Class>.module:`` 值;
3. pipeline.yaml workflows 各 step 的 ``tool`` 符号;
4. static/fragments/algo_mode/two_stage_async_mode.yaml 的 ``entry`` 符号;
5. manifest.yaml 的 always_load/on_demand/entry_points 路径是否存在;
6. src/__init__.py 的 ``__all__`` 导出是否可解析;
7. .env.example 与**全仓**代码读取点 (scan_roots 黑名单覆盖面) 的环境变量双向对账;
   哪一类读取算"部署期配置输入"由 ops/audit/env_scope.py 的在册裁定决定 (归类面,
   与覆盖面分工: 前者答"扫谁", 后者答"算不算"); 四种读取形态走 **AST** 而非源码文本
   —— 文本匹配分不清"代码"与"关于代码的话": 注释/docstring 里的示意写法、测试夹具里
   嵌成字符串的源码都不是读取点 (噪声源), 而实参前置行尾注释又会让真读取漏掉
   (``BEST_LOCAL_TAP_URL``, src/tap/client.py:108-109);
8. contracts/error-codes 契约里的常量是否真被代码引用 (双向: 契约登记了代码要用,
   代码在用的码也要在契约登记), 防止契约与代码各写一份互不知道 (防的是"契约写了
   没人用"与"代码加了码忘了登记"两半, 且登记号按**字典键**形态收集 —— 旧判据
   只扫 code/name/id 三个值键位, 对本仓的键形态契约恒收 0 个码, 整节零覆盖);
9. 治理文档 (README/architecture/*.md 等) 中反引号引用的仓内路径是否存在,
   以及 ``模块.符号`` 形式的引用能否真解析 (后者是本条判据的**两个口径**:
   路径口径管"文件搬走了", 符号口径管"符号挂错模块了" —— 实测 SKILL.md 曾把
   ``BestQueryResult`` 挂在 ``src.query_builder`` 上 (真实在 ``src.models``),
   路径口径看不见这种错, 而本门禁照样 exit 0)。
"""
# 标准库: ast 静态解析 (§7 认 env 读取点与声明, 只解析不执行) / importlib 文档路径解析
#         (交叉引用体检的读取层) / os 环境与遍历 / re 字面量与键形 / sys 路径与退出码 /
#         仓根定位 (Path)
import ast
import importlib
import os
import re
import sys
from pathlib import Path

import yaml

# 仓根 = 本文件上溯两级 (ops/audit/x.py -> ops/audit -> ops -> 仓根)。
# parents[2] 的索引 2 = 级数 2 (ops/audit/x.py 的 parents[0]=ops/audit、
# [1]=ops、[2]=仓根), 仓内约定是「索引=级数」—— 把索引当级数就会数错一级,
# 落到 ops/ 上, 于是下方所有 ROOT 相对路径全部错位 (第 7 节读
# src/scripts/config.py 时直接 FileNotFoundError 崩溃), contracts/ 与
# templates/ 从未被真正遍历。
ROOT = str(Path(__file__).resolve().parents[2])                      # 仓根: 本文件在 ops/audit/ 下, parents[2] 即仓根 (索引 2 = 级数 2)
os.chdir(ROOT)                                                                   # chdir 到仓根: 下面所有相对路径都以仓根为基准, 不依赖调用时的 cwd
sys.path.insert(0, ROOT)                                                                     # 注入 sys.path: 第二遍要真导入目标模块查名字

issues = []                                                                                         # 问题累积而非首错即退: 一轮跑批要报全量


def check_symbol(dotted):
    """核实点分符号路径: 优先整体当模块导入, 否则按最长前缀回退为属性链。

    必须先试整体: 声明值多为模块路径本身 (``src.download_manager``)。若直接从
    ``len(parts) - 1`` 起回退, 二段路径会被误判成"``src`` 的属性 ``download_manager``"
    并报假失败 —— 实测 7 处误报, 相关模块全部真实存在。
    """
    try:
        importlib.import_module(dotted)                                                        # 真导入: 静态查名字不够, 活代码里有没有才是事实
        return
    except ImportError:
        # 整体不是模块路径 — 继续按前缀回退, 尾部当作符号链
        pass
    parts = dotted.split(".")
    # 从最长模块名向最短回退, 尾部为符号链
    for cut in range(len(parts) - 1, 0, -1):                                         # 从最长的前缀开始截: "a.b.c" 先试 a.b.c, 再退 a.b
        mod_name = ".".join(parts[:cut])
        try:
            mod = importlib.import_module(mod_name)                                                 # 截到可用前缀才导入
        except ImportError:
            # 该前缀不是可导入模块 — 继续回退 (不是静默吞: 全都失败上抛 FileNotFoundError)
            continue
        obj = mod                                                                                   # 逐段取属性
        for attr in parts[cut:]:                                                                    # 属性链逐层解析
            try:
                obj = getattr(obj, attr)                                                            # 取到目标符号
            except AttributeError:
                issues.append(f"[SYMBOL] {dotted}: 模块 {mod_name} 无属性 {'.'.join(parts[cut:])}")
                return
        return
    issues.append(f"[IMPORT] {dotted}: 无法导入任何前缀模块")   # 一个前缀都导不进 = 死路径


def load_yaml(path):
    """读取 yaml 文件, 失败则记录问题。"""
    try:
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f)
    except Exception as e:
        # 解析失败只记问题不崩: 一份坏 yaml 不该让其余八类检查全部消失 (本文件共九类)
        issues.append(f"[YAML] {path}: 解析失败 {e}")
        return None


def require_source(loaded, path):
    """必读源为空即记问题, 返回原值供调用方接着判。

    **为什么 load_yaml 不够**: 它只在「读不到 / 解析失败」时记 ``[YAML]``;
    文件存在但内容为空时 ``yaml.safe_load`` 返回 None, 它**一声不吭**地返回 None。
    于是下面五节的 ``if spec:`` 之类守卫会整节跳过 —— 门禁照样 exit 0,
    而那一节的覆盖是零。读的人只会把"零覆盖"误读成"这一节没问题",
    这正是本仓铁律 5 (禁 fail-open) 要治的形态。空与坏要分开记账,
    所以这里补一条 ``[EMPTY]``, 而不是把两者混成同一类。
    """
    if loaded is None:
        issues.append(f"[EMPTY] {path}: 读得到但内容为空, 本节零覆盖 (fail-open 已阻断)")
    return loaded


# ── 1. skills-spec.local.yaml 的 skills.<name>.algorithms[].module ──────
spec = require_source(load_yaml("references/skills-spec.local.yaml"), "references/skills-spec.local.yaml")   # 读本地 spec: 它是 algorithms[].module 的权威源; 为空即本节零覆盖, 必记问题
if spec:                                                                                        # 读不到/为空由 require_source 记账, 这里只判有内容才继续
    # 结构: {meta: ..., skills: {astro-best: {..., algorithms: [...]}}}。
    # algorithms 挂在 skills.<name> 之下 (不是顶层), 取错层级会恒报"无 algorithms 字段"。
    skills = spec.get("skills") or {}
    if not skills:                                                                                  # 没有 skill 条目即无事可查
        issues.append("[SPEC] references/skills-spec.local.yaml 无 skills 段")
    for skill_name, skill in skills.items():                                                        # 逐 skill 走
        algos = skill.get("algorithms") or []   # 每个 skill 自己持有一份算法清单
        if not algos:                                                                               # 该 skill 没登记算法即跳过
            issues.append(f"[SPEC] skills.{skill_name} 无 algorithms 字段")
        for a in algos:                                                                             # 逐算法走
            mod = a.get("module")
            if mod:                                                                                 # 有 module 声明才进检查
                check_symbol(mod)              # 声明了就得真能导入 (规则 9 的 fail-closed)
            else:
                issues.append(f"[SPEC] algorithm {a.get('name')} 缺 module 字段")

# ── 2. contracts / templates 中全部 module: 值 ───────────────────────────
targets = []                                                                                        # 目标文件清单
for base in ("contracts", "templates"):
    for dirpath, _dirs, files in os.walk(base):                                                     # 遍历目录收集契约文件
        for fn in files:                                                                            # 逐文件
            if fn.endswith((".yaml", ".yml")):
                targets.append(os.path.join(dirpath, fn))   # 收集面, 不在此处判有效性

def walk_collect_modules(obj, out, src_file):
    """递归收集 yaml 树中的 module 键值。

    键有两种真实形态 (实测本仓并存): ``module:`` 与 ``<ClassName>.module:``。
    只认前者会让 ``templates/gen_config_template.yaml`` 的 12 条声明全部漏检
    (表现为"module 声明 0 条"却不报任何问题 —— 静默空转)。
    """
    if isinstance(obj, dict):                                                                       # 字典才递归取值
        for k, v in obj.items():                                                                    # 逐键值
            is_module_key = isinstance(k, str) and (                       # module 声明的键形态有两种: 裸 module 与 `<Class>.module`
                k == "module" or k.endswith(".module")           # 两种键形态本仓并存
            )
            if is_module_key and isinstance(v, str):                                                # 是 module 声明且值是字符串才继续
                out.append((src_file, v))                        # 命中即收, 后面统一验可导入
            else:
                walk_collect_modules(v, out, src_file)                                              # 模块路径里不含字典, 按字符串处理
    elif isinstance(obj, list):
        for item in obj:                                                                            # 列表逐项递归
            walk_collect_modules(item, out, src_file)                                               # 列表项同样是递归入口

module_decls = []                                                                                   # 收集到的 module 声明
for t in targets:                                                                                   # 逐个目标文件
    data = load_yaml(t)                                                                  # 读 YAML (返回 None 表示坏文件, 已在别处记问题)
    if data is not None:                                                                            # 只有读成功才继续
        walk_collect_modules(data, module_decls, t)                                                 # 递归收集该文件里的 module 声明

for _src_file, mod in module_decls:                                                                 # 逐条核对
    if mod and "." in mod and not mod.startswith(("http", "/")):
        check_symbol(mod)      # 形如 a.b.c 才可能是 python 路径; URL/绝对路径不是

# ── 3. pipeline.yaml workflows tool 符号 ─────────────────────────────────
pipe = require_source(load_yaml("pipeline.yaml"), "pipeline.yaml")                     # 读管线契约; 为空即本节零覆盖, 必记问题
if pipe:                                                                                            # 有内容才继续, 空与坏都已在上一行记账
    for wf in pipe.get("pipeline", {}).get("workflows", []):
        for step in wf.get("steps", []):
            tool = step.get("tool")
            if tool:                                                                                # 有 tool 段才查
                check_symbol(tool)      # 编排里写的工具名必须真存在, 否则跑批时才炸

# ── 4. static/fragments entry 符号 ───────────────────────────────────────
frag = require_source(load_yaml("static/fragments/algo_mode/two_stage_async_mode.yaml"), "static/fragments/algo_mode/two_stage_async_mode.yaml")   # 读核心片段: 两阶段异步协议的锚点
if frag:                                                                                            # 它是入口符号的权威源, 空与坏都由 require_source 记成问题
    entry = frag.get("entry")
    if isinstance(entry, str) and "." in entry:
        check_symbol(entry)     # 两种 entry 形态: 字符串 或 映射表
    elif isinstance(entry, dict):
        for v in entry.values():                                                                    # 逐个 entry
            if isinstance(v, str) and "." in v:
                check_symbol(v)                                                                     # 入口符号必须可解析

# ── 5. manifest 路径存在性 ───────────────────────────────────────────────
mani = require_source(load_yaml("manifest.yaml"), "manifest.yaml")                     # 读清单; 为空即路径存在性整节零覆盖, 必记问题
if mani:                                                                                            # 有内容才继续
    paths = list(mani.get("always_load", [])) + list(mani.get("on_demand", {}).get("two_phase_query", []))
    od = mani.get("on_demand", {})
    for v in od.values():                                                                           # 逐个 output_dashboard
        if isinstance(v, list):                                                                     # 列表逐项
            paths += v          # on_demand 下的每个键都是一份待加载清单
    ep = mani.get("entry_points", {})
    for v in ep.values():                                                                           # 逐个 env_profile
        if isinstance(v, dict):                                                                     # 字典逐项
            for vv in v.values():                                                                   # 二层嵌套的值
                if isinstance(vv, str):                                                             # 字符串才查
                    paths.append(vv)   # 入口点声明的必须是单文件路径
    for p in paths:                                                                                 # 路径逐个判存在
        if p.endswith((".py", ".md", ".yaml")) and not os.path.exists(p):
            issues.append(f"[MANIFEST] 路径不存在: {p}")   # 清单写了却不存在 = 加载期必炸

# ── 6. src/__init__.py __all__ 解析 ──────────────────────────────────────
try:
    # 标准库: 文档路径解析 (交叉引用体检的读取层)
    import src  # noqa
    for name in getattr(src, "__all__", []):
        if not hasattr(src, name):                                                                  # 缺属性即报: 契约里写的符号必须真存在
            issues.append(f"[EXPORT] src.__all__ 声明 {name} 但不可解析")   # 门面虚标能力
except Exception as e:
    issues.append(f"[EXPORT] src 包导入失败: {e}")

def _env_key_literal(node):
    """从 AST 节点取 env 键名; 不是全大写字面量则 None (键名字形判据在此收口)。"""
    if isinstance(node, ast.Constant) and isinstance(node.value, str) and RE_ENV_KEY.match(node.value):
        return node.value                                              # 字面量直取: 键名就在调用点上
    return None                                                        # 其他表达式: 不硬凑


def _env_read_key(node):
    """判定一个节点是不是 env 读取点, 是则返回键名 —— 形态 (a)/(b)。

    **必须走 AST 而不是源码文本正则** (2026-10-05 W1 实测, 三类错全出在文本匹配上):

    1. 散文不是读取点。注释与 docstring 里天天写着 ``os.environ.get("KEY")`` 这类
       **示意**写法 —— 连**本门禁自己的注释**都写着, 于是它把自己的说明文字当成了一个
       真实 env 键 ``KEY``; 单测文件 docstring 里的 ``os.getenv("K")`` 同理。
    2. 嵌在字符串里的源码不是读取点。测试夹具常把 Python 源码写在字符串里传给
       ``write_text``: ``'return os.environ.get("KEY", "")'``。文本上它与真调用逐字
       同形, 而它只是**要写进假仓的文本**。
    3. 换行与行尾注释不该让真读取消失。``src/tap/client.py:108-109`` 的
       ``os.environ.get(`` 后跟行尾注释、字符串实参在下一行, 正则里的 ``\\s*`` 匹配
       不过去 —— ``BEST_LOCAL_TAP_URL`` 就这样被误报成"代码未读取"的。

    三类的共同根因都是"文本匹配分不清代码与关于代码的话"; AST 没有这个歧义。
    """
    if isinstance(node, ast.Subscript):                               # os.environ["KEY"] 形态: 是下标不是调用
        owner = node.value
        if isinstance(owner, ast.Attribute) and owner.attr == "environ":
            return _env_key_literal(node.slice)                       # 常量下标才是键名
        return None
    if not isinstance(node, ast.Call):                                # 其余形态都是方法调用
        return None
    func = node.func
    if isinstance(func, ast.Attribute):
        if func.attr == "getenv" and isinstance(func.value, ast.Name) and func.value.id == "os":
            return _env_key_literal(node.args[0]) if node.args else None        # os.getenv("KEY")
        if func.attr == "get" and isinstance(func.value, ast.Attribute) and func.value.attr == "environ":
            return _env_key_literal(node.args[0]) if node.args else None        # os.environ.get("KEY")
    if isinstance(func, ast.Name) and func.id.startswith("_env_"):     # 本地包装器: _env_int("KEY", 1)
        return _env_key_literal(node.args[0]) if node.args else None
    return None                                                        # 其余调用与 env 无关


def _env_named_const_keys(tree):
    """形态 (d): 赋给 **env 形左值**的字符串常量 (``ENV_TOKEN = "KEY"``)。

    左值形状是判据本身 (``RE_ENV_NAMED``), 所以本函数可以**全仓**用 —— 这正是
    ``src/scripts/guards.py`` 的 ``DATA_ROOT_ENV`` 与 ``src/auth/nadc_oauth.py``
    的 ``ENV_CLIENT_ID`` 等不再被漏掉的原因 (旧判据把它们关在配置面名单里)。
    字典字面量的键 (形态 c) **不在**本函数里: 它不可判别, 由调用方按配置面名单认。
    """
    keys = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):                            # ENV_TOKEN = "KEY"
            pairs = [(t, node.value) for t in node.targets]
        elif isinstance(node, ast.AnnAssign):                      # 带标注的同一形态: ENV_TOKEN: str = "KEY"
            pairs = [(node.target, node.value)]
        else:
            continue
        for target, value in pairs:
            if isinstance(target, ast.Name) and RE_ENV_NAMED.match(target.id) \
                    and isinstance(value, ast.Constant) and isinstance(value.value, str):
                keys.add(value.value)                              # 左值自称 env 名 + 值是字符串 = 一条声明
    return keys


# ── 7. .env.example vs 代码读取点 环境变量集合 ───────────────────────────
# .env.example 自称"每个键都必须能被代码真实读取 (Q-16)", 故本节判**双向**: 登记了
# 没人读的键会误导部署方, 代码读了没人登记的键则无从注入。
# 覆盖面与归类面是两个真源, 分工别混 (2026-10-05 W1 实测踩过): **覆盖面** (哪些
# .py 要扫) 走 scan_roots 的全仓黑名单口径; **归类面** (哪些读取点算"部署期配置
# 输入") 走 env_scope 的在册裁定 —— 判据若不分这两层, 就会把"排除面"错当成
# "覆盖面缺口", 或反过来。
env_keys = set()                                                                                    # env 键集合
env_example = os.path.join(ROOT, ".env.example")                                                    # env 示例文件路径
if os.path.exists(env_example):                                                                     # 示例不存在就跳过这一类
    with open(env_example, encoding="utf-8") as f:
        for line in f:                                                                              # 逐行读
            m = re.match(r"^([A-Z][A-Z0-9_]*)=", line.strip())   # 只认赋值形态, 注释行不算键
            if m:                                                                                   # 匹配到赋值行
                env_keys.add(m.group(1))                                                            # 键入库
else:
    issues.append("[ENV] .env.example 不存在")   # 缺了这条就没法做双向对账

# **四种**真实读取形态都要认 (实测本仓四种并存; 原注释写"三种"是漏的):
#   (a) os.environ.get("KEY") / os.getenv("KEY") / os.environ["KEY"]  —— 字面量直取
#   (b) _env_int("KEY", 1) 等本地包装器                              —— **第四种, 原先漏认**
#   (c) "KEY": "字段名"                                              —— env_map 映射表
#   (d) ENV_XXX = "KEY"                                              —— 模块级常量再引用
# (a)/(b) 认**调用实参**、只走 AST (_env_read_key, 理由见其 docstring); (c)/(d) 认
# **声明** (字典键 / 常量赋值), 同样走 AST。三者共用下面的字形判据, 别再退回源码正则。
RE_ENV_KEY = re.compile(r"^[A-Z][A-Z0-9_]*$")   # env 键名字形: 与 .env.example 的解析同口径, 别放宽成普通文案
# 形态 d 的**左值必须自带 env 形状** (``ENV_`` 前缀或 ``_ENV`` 段: ENV_TOKEN /
# DATA_ROOT_ENV / AUTH_PASSWORD_ENV)。这是**键自身的形状判据, 不是又一份文件名单**:
# 少了它, 全仓扫会把 E_BACKEND / PENDING / INFO / SIGNED 这类大写数据字典键与常量一并
# 收进来 (实测收紧 9 键 vs 放开 33 键, 多收 24 条噪声), 噪声面一大判据迟早被整体关掉。
# 带上它之后形态 d 可以**全仓认**, 于是 ASTRO_BEST_DATA_ROOT (src/scripts/guards.py:32)
# 与 NADC_OAUTH_* 三键 (src/auth/nadc_oauth.py:76-78) 不再因"不在配置面名单里"而被漏判。
RE_ENV_NAMED = re.compile(r"^(?:ENV_|[A-Z0-9_]+_ENV)[A-Z0-9_]*$")   # 形态 d 左值形状
# 为什么只有形态 c 还需要文件名单 (下一个改名单的人请先读这一段):
#   形态 d 靠左值形状**自我指认**, 故不需要名单, 全仓认;
#   形态 c 的字典字面量键**没有任何形状特征** —— ``"A3": 3`` 这种数据字典与
#   ``env_map`` 的键位在语法上完全同形 (实测全仓扫会收进 A3/E1..E6/HOME/MAXREC/
#   PENDING 等 40+ 噪声), 唯一能区分它们的只有"这个字面量是不是配置映射表"。
#   所以 (c) 认一份**显式配置面名单**。它**不是覆盖面缺口**: 扫描面仍是全仓
#   scan_roots, 这里收窄的只是"哪种字面量算 (c) 的证据" —— 一句话: (d) 能用形状
#   判, (c) 只能靠人裁定, 因此它需要且只需要一份可审的小名单。要加配置面时, 在这里
#   加一行并说明它承载哪张映射表, 别顺手把名单当覆盖面清单用。
ENV_MAP_FILES = ("src/scripts/config.py", "src/auth/nadc_oauth.py", "src/__main__.py")

cfg_keys = set()                                                                                    # 从代码里抽出的键全集
missing_consumers = []                                                                              # 消费方缺失单列: 缺文件与缺键是两类问题
# 扫**全仓** .py 而不是列几个"落点": env 键的真实读取面已实测超出三个文件
# (src/tap/client.py 读 BEST_TAP_URL / src/auth/nadc_oauth.py 读 NADC_OAUTH_* 等),
# 而白名单只认 3 个文件时, 门禁会把"代码读了但不在名单里"误报成"代码未读取" ——
# 与 SCAN_DIRS 同一类白名单缺口。
# 取扫描面用 scan_roots 那个**单一黑名单真源**, 不在这里另列一份目录。
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # 同目录裸名导入: 直跑时 sys.path[0] 就是它
import env_scope  # noqa: E402  PLC0415  归类面真源 (非覆盖面): 与单测共用同一份在册裁定
import scan_roots  # noqa: E402  PLC0415  局部导入: 注入 sys.path 之后才可导

for rel_path, _abs in scan_roots.iter_py_files(str(ROOT)):                                        # 全仓 .py 逐个当消费方
    cfg_path = os.path.join(ROOT, *rel_path.split("/"))
    # 存在性前置判断: 文件缺失时记问题并继续, 不能裸 open 崩掉整个体检
    if not os.path.isfile(cfg_path):                                                                # 文件不存在记入缺失清单
        missing_consumers.append(rel_path)                                                          # 缺失要报, 不能静默跳过
        continue
    with open(cfg_path, encoding="utf-8") as f:
        source = f.read()                                                                           # 读源码原文 (只解析, 不执行)
    try:
        tree = ast.parse(source)                                                                    # 只解析不 import: import 等于执行
    except SyntaxError as e:                                                                        # 解析不了 = 判据对它零覆盖
        issues.append(f"[ENV] {rel_path}: 解析失败, 本文件 env 读取点零覆盖 ({e})")   # fail-closed: 不当"没读到"放过
        continue
    cfg_keys |= {k for k in map(_env_read_key, ast.walk(tree)) if k}                                # 形态 (a)/(b): 认调用实参
    cfg_keys |= _env_named_const_keys(tree)                                                        # 形态 (d): env 形常量, 全仓认
    if rel_path in ENV_MAP_FILES:                                                                   # 形态 (c): 字典键只在配置面认
        cfg_keys |= {k for k in map(_env_key_literal, (k for d in ast.walk(tree)                     # 字典字面量的键
                                                    if isinstance(d, ast.Dict)
                                                    for k in d.keys)) if k}
if missing_consumers:                                                                               # 缺消费方即无法三方比对
    issues.append(f"[ENV] 环境变量消费方文件不存在: {missing_consumers}")
if not cfg_keys:                                                                                    # 零覆盖守卫: 提取逻辑整体退化
    # 为什么只守"整体"而不逐形态守: 一棵最小假仓 (门禁判据级红测试用的对照组) 可以
    # 合法地没有 env_map 映射, 逐形态要求非空会让门禁在假仓上恒红 —— 那等于逼人把
    # 守卫改成"关掉"。逐形态的覆盖改由单测在**真仓**上守 (形态退化必须表现为判红)。
    issues.append("[ENV] 四种形态合计收 0 个 env 键 —— 本节覆盖为零 (提取逻辑已退化, 与全绿无法区分)")

only_env = env_keys - cfg_keys                                                      # 只在 .env.example 里出现: 配置没读它, 部署时不会被采纳
# 归类面扣账: 已被 env_scope 逐条裁定为"非部署期输入"的键 (测试开关 / 系统代理 /
# 本机渲染路径) 不要求登记进 .env.example —— 照它配并不改变 skill 行为, 登记反而是
# 误导。**只扣在册的那几个**: 尚未裁定的同类键照样判红 (漏裁定会红, 不是静默放过)。
# 反向也判: 被裁定为非部署期的键若又登记进了 .env.example, 说明两侧裁定打架。
only_cfg = (cfg_keys - env_keys) - set(env_scope.EXCLUDED_ONLY)
ruled_but_declared = sorted(set(env_scope.EXCLUDED_ONLY) & env_keys)
if ruled_but_declared:                                                                               # 两侧裁定不一致: 登记了就等于宣称它是部署配置
    issues.append(f"[ENV] 已裁定为非部署期输入却又登记进 .env.example 的键: {ruled_but_declared} —— "
                  f"要么从 .env.example 删登记, 要么改 ops/audit/env_scope.py 的裁定并写明理由")
if only_env:                                                                                        # 单向不一致
    issues.append(f"[ENV] .env.example 有而代码未读取: {sorted(only_env)}")   # 写了没人读 = 误导部署方
if only_cfg:                                                                                        # 报 env 侧多出来的键
    issues.append(f"[ENV] 代码读取而 .env.example 缺: {sorted(only_cfg)}")    # 读了没人写 = 无从注入

# ── 8. error-codes 契约常量被代码引用 (双向) ──────────────────────────────
ec = require_source(load_yaml("contracts/error-codes.contract.yaml"), "contracts/error-codes.contract.yaml")   # 读 error-codes 契约; 为空即死码检查零覆盖, 必记问题
RE_BEST_ID = re.compile(r"^BEST_\d+$")                # 契约里的**登记号**形态 (本仓是 codes 段的字典键)
RE_CODE_LITERAL = re.compile(r"""["'](E_[A-Z0-9_]+)["']""")   # 代码侧错误码的**书写形态**: 引号包住的 E_ 字面量
# 只收引号形态而不收裸 \bE_[A-Z0-9_]+\b: 裸形态把 EMPTY/ERROR/EVENT_*/ENV_* 一并收进来
# (实测噪声面 60+ 项), 判据会立刻变成噪声源 —— 而噪声源迟早被整体关掉, 那才是真的 fail-open。

if ec:                                                                                              # 有内容才继续
    # 收集「登记号 -> 码字面量」。**键形态是本仓的真身**: BEST_NNNN 是 codes 段的字典**键**,
    # 而 code/name/id 三个**值**键位在这份契约里装的是 E_* 字面量 —— 旧判据只扫值并拿
    # ^BEST_\d+$ 去匹配, 于是恒收 0 个码, 整节覆盖为零而门禁照样 exit 0 (G1-09 实测)。
    # 两个键形态都收, 是为了别把"只认值键位"的假设再写死一次。
    pairs = {}                                                                                       # BEST_NNNN -> 码字面量
    def collect_codes(o):
        """递归收集错误码契约里登记的全部 BEST_NNNN 码 (键形态与值形态都收)。

        键形态: 字典键本身形如 ``BEST_NNNN``, 其值里的 ``code`` 才是代码引用的字面量;
        值形态: 仓内另一种写法把 ``BEST_NNNN`` 放在 ``code``/``name``/``id`` 的**值**上。
        两种都收, 缺任一种都会让本节静默零覆盖 —— 那正是本次修掉的病灶。
        """
        if isinstance(o, dict):                                                                     # 字典逐项
            for k, v in o.items():                                                                  # 键值递归
                if isinstance(k, str) and RE_BEST_ID.match(k) and isinstance(v, dict):              # 键形态: 登记号做键
                    literal = v.get("code")                                                         # 码字面量在同一层级的 code 字段
                    if isinstance(literal, str) and literal:
                        pairs[k] = literal                                                          # 登记号与字面量成对入表 (判据要按字面量找引用)
                    collect_codes(v)                                                               # 继续下沉, 别在命中处提前返回
                elif k in ("code", "name", "id") and isinstance(v, str) and RE_BEST_ID.match(v):    # 值形态: 登记号做值
                    pairs[v] = v                                                                   # 登记号即字面量 (无独立 code 层)
                collect_codes(v)                                                                   # 两条分支都要下沉
        elif isinstance(o, list):
            for i in o:                                                                             # 列表逐项
                collect_codes(i)                                                                    # 递归收集
    collect_codes(ec)                                                                               # 从契约根开始收集
    if not pairs:                                                                                   # 收集到 0 个 = 形态又变了, 本节静默零覆盖
        issues.append("[ERRCODE] 错误码契约未收集到任何 BEST_NNNN 登记号 (键/值形态都未命中), 本节零覆盖")   # 零覆盖必须显式判红: 否则退化后与全绿无法区分
    code_srcs = []                                                                                  # 代码侧源码
    for base in ("src", "ops", "evals"):
        for dirpath, _d, files in os.walk(base):                                                    # 遍历消费目录
            for fn in files:                                                                        # 逐文件
                if fn.endswith(".py"):
                    with open(os.path.join(dirpath, fn), encoding="utf-8") as f:
                        code_srcs.append(f.read())                                                  # 把整份源码并进来
    all_code = "\n".join(code_srcs)     # 全文拼接: 只判"有没有出现", 不判语义对错
    # 契约里 declared (未接线) 注释块显式声明保留的登记号 —— 这些码零引用是**纪律**
    # (边界声明), 不是死码。门禁认这份声明, 而不是硬编一份名单: 硬编就是第二事实源,
    # 改契约的人不会同步改它, 它会静默过期 (与"只认值键位"同一类病灶)。
    declared_block = re.search(r"^[^\S\n]*#.*declared\s*\(未接线\).*?\n((?:[^\S\n]*#.*\n)+)",
                               open("contracts/error-codes.contract.yaml", encoding="utf-8").read(), re.M)
    declared = set(re.findall(r"BEST_\d+", declared_block.group(1))) if declared_block else set()   # 声明保留的登记号集合
    for best_id, literal in sorted(pairs.items()):                                                  # 方向 A: 契约 -> 代码
        if literal in all_code:
            continue                                                                                 # 有引用即合规
        if best_id in declared:                                                                     # 声明块里点名保留 = 纪律刻意为之
            continue                                                                                 # 放过, 但依据在契约注释里可查
        issues.append(f"[ERRCODE] 契约错误码 {best_id} ({literal}) 未被任何 src/ops/evals 代码引用 —— "
                       f"删条目, 或在契约 declared 段写明未接线原因 (刻意保留的未接线码须有注释依据)")   # 点名登记号与字面量, 便于定位
    # 方向 B: 代码 -> 契约。只在 src/ 与 ops/ 下扫 (evals 会引入测试专用的合成码, 如
    # evals/repro/tests 里的 E_WEIRD, 那些不是运行时契约的一部分, 混进来判据必误报)。
    # 这一向是"代码加了码忘了登记"的那半边 (G1-09 本体), 只做方向 A 时它完全无人看守。
    prod_parts = []                                                                                 # src/+ops/ 源码分片
    for base in ("src", "ops"):
        for dirpath, _d, files in os.walk(base):
            for fn in files:
                if fn.endswith(".py"):
                    with open(os.path.join(dirpath, fn), encoding="utf-8") as f:
                        prod_parts.append(f.read())
    prod_code = "\n".join(prod_parts)                                                               # 生产代码全文
    registered = set(pairs.values())                                                                 # 契约登记的字面量全集
    for literal in sorted(set(RE_CODE_LITERAL.findall(prod_code)) - registered):                   # 逐个未登记字面量
        issues.append(f"[ERRCODE] 代码使用的错误码字面量 {literal} 未在 error-codes 契约登记 —— "
                       f"补 codes 段条目 (登记号 + code 字面量), 或确认它不是错误码")   # 代码在发而契约无条目 = 上层拿不到稳定分支

# ── 9. 治理文档中反引号引用的仓库路径存在性 + `模块.符号` 可解析性 ──────
doc_files = ["SKILL.md", "README.md", "architecture.md", "manifest.yaml",
             "contracts/io-contract.md", "references/ALGORITHM-SPEC.md",
             "references/download-playbook.md", "references/site-endpoints-and-interactions.md"]
path_re = re.compile(r"`((?:src|ops|rag|evals|test|references|contracts|templates|static|docs|examples|weights|best_data)/[A-Za-z0-9_\-./]+\.(?:py|md|yaml|yml|json|txt|toml))`")  # 治理文档里反引号路径的提取正则
# `模块.符号` 提取正则 —— 仓内治理文档里符号引用的**两种真实书写形态**都要收:
#   形态 A: `src.downloader.BestDownloader`
#   形态 B: `src.downloader`(BestDownloader)      ← 仓内更常见 (SKILL.md API 快查全是这种)
# 形态 B 的括号段必须**整段**是 `符号/符号` 列表才收 (``\(...\)`` 同时锚定右括号):
# 不锚定右括号的话 `src.tap`(IVOA TAP 1.1, stdlib 零依赖; …) 会被截成
# `src.tap.IVOA` 误报, `src.ai_tools`(ToolBox 7 原子工具 + …) 同理。
# 前缀只收仓内可导入的顶层包, 否则 HTML 标签/端点串 (`pos.type`、`table.load.votable`) 全被当 python 路径。
symbol_re = re.compile(
    r"`((?:src|ops|evals|rag|test)\.[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*)`"   # 形态 A/B 共有的模块部分
    r"(?:\(([A-Za-z_][A-Za-z0-9_]*(?:/[A-Za-z_][A-Za-z0-9_]*)*)\))?"                         # 形态 B 尾巴: (符号/符号), 整段锚定
)
missing_docs = set()                                                                                # 缺失路径集合
doc_symbols = {}                                                                                     # 符号 → 引用它的文档集合 (同一符号只查一次, 报错时点名全部出处)
for df in doc_files:                                                                                # 逐份治理文档
    if not os.path.exists(df):                                                                   # 文档不存在即报: 登记册本身缺了是更严重的问题
        missing_docs.add(f"[DOC] 文档自身不存在: {df}")   # 文档没了先报缺文档, 不再扫内容
        continue
    with open(df, encoding="utf-8") as f:
        text = f.read()                                                                             # 读文档全文
    for m in path_re.finditer(text):                                                                # 逐个反引号路径
        p = m.group(1)                                                                              # 取路径文本
        if not os.path.exists(p):                                                                  # 从仓根解析: 治理文档里的路径都是仓根相对
            missing_docs.add(f"[DOCPATH] {df} 引用路径不存在: {p}")   # 文档指向已搬走的文件
    for m in symbol_re.finditer(text):                                                               # 逐个符号引用 (两种书写形态)
        base, paren = m.group(1), m.group(2)                                                           # 形态 A: paren 为 None; 形态 B: 括号内是 符号/符号 列表
        names = paren.split("/") if paren else [""]                                                    # 形态 B 要逐个符号拼回点分路径 (`mod`(A/B) → mod.A 与 mod.B)
        for name in names:
            doc_symbols.setdefault(f"{base}.{name}" if name else base, set()).add(df)                # 只收不判: 判定集中在下面一轮
issues.extend(sorted(missing_docs))   # 排序让每次输出稳定可比对

# 符号口径判定: 复用 check_symbol (整体当模块导 → 最长前缀回退成属性链), 真导入才算过。
# 为什么必须独立成一条: path_re 只认以 .py/.md/.yaml 结尾的**文件**, 而治理文档里更常见
# 的是 `模块.符号` 引用 —— 符号挂错模块 (真实在 src.models 却写成 src.query_builder) 时,
# 路径口径一条都抓不到, 门禁却照样 exit 0。
for sym in sorted(doc_symbols):                                                                     # 每个不同符号只查一次 (重复引用不重复导入)
    mark = len(issues)                                                                              # check_symbol 把失败原因直接追加进 issues
    check_symbol(sym)                                                                               # 活代码里有没有才是事实
    if len(issues) > mark:                                                                           # 解析失败: 给报错补上出处文档, 否则只看到符号名无从定位
        detail = issues.pop()                                                                        # 取出刚追加的那条 (check_symbol 一次只追加一条)
        issues.append(f"{detail} (治理文档出处: {', '.join(sorted(doc_symbols[sym]))})")   # 点名是哪几份文档写错了

print(f"核实完成: module 声明 {len(module_decls)} 条, 治理文档符号引用 {len(doc_symbols)} 个")    # 先报覆盖面, 便于判读"零覆盖"
print(f"发现 {len(issues)} 个问题:")                                                                     # 问题总数
for i in issues:                                                                                    # 逐条打印
    print(" -", i)
# 退出码: 有问题即非零, 供门禁接线 (恒返回 0 的工具无法作为门禁使用)
raise SystemExit(1 if issues else 0)
