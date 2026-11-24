# -*- coding: utf-8 -*-
r"""守护: `.env.example` 的 env SSOT 宣称必须与**全仓真实读取**对账 (E5 P1-01)。

缺陷形态 (2026-10-05 E5 对外声明面审计, temp/DETECT-E5-external-surface.md P1-01,
本轮 V1 修复): `.env.example` 第 3 行自称「本文件是环境变量 SSOT: 每个键都必须
能被代码真实读取 (Q-16)。消费方共三处」—— **两个宣称都不实**:

1. 「共三处」漏了四个真实消费方: ``src/tap/client.py`` (端点)、
   ``src/tap/service.py`` (8 个网关配额)、``src/scripts/guards.py`` (数据根)、
   ``src/auth/nadc_oauth.py`` (NADC 身份三键)。
2. 按本轮**独立 AST 复扫** (不照抄 E5 清单) 实得**漏登记 14 个键**, 不是 E5 标题
   写的 9 个 —— 差在 8 个 ``BEST_TAP_*`` 配额键: 它们经 ``_env_int(name, ...)``
   形参流入 ``os.environ.get``, 按字面量直取的旧正则**结构上扫不到**。

**为什么两道既有守护腿都拦不住** (这一条决定了本件不能只是"再加一个清单"):
``test_dead_channel_claims.py::TestEnvSsotCoversRealCredentialSurface`` 的第二条腿
按名字形状 ``(PASSWORD|SECRET|TOKEN|API_KEY|CREDENTIAL)`` 过滤, ``BEST_TAP_URL`` /
``ASTRO_BEST_DATA_ROOT`` 不含这些词形 → 被过滤掉; 而
``ops/audit/verify_crossrefs.py §7`` 的 ``CONSUMER_FILES`` 硬编码三个文件
(``src/scripts/config.py`` / ``src/auth/nadc_oauth.py`` / ``src/__main__.py``),
TAP / guards / dispatch 不在名单内 → 扫不到。本件因此**不复用**那两个窄口径,
而是自建一条**全仓、按数据流解析**的抽取腿。

判据纪律 (沿用本仓"事实从代码现场取"的既有纪律):
- **扫描面不另立清单**: 直接消费唯一真源 ``ops/audit/scan_roots.iter_py_files``
  (黑名单口径), 与四道门禁同一份覆盖面 —— 新建目录放 ``.py`` 自动进门禁, 不靠补名单。
- **键名从代码解析而非抄写**: AST 静态解析 (不 import, 免副作用进测试进程),
  解析四种真实读取形态, 含三处**间接**层 (见 :func:`_env_keys_in_tree`)。
- **空转即红**: 扫不出任何键时判红 —— 否则"清单删空"就能让本件恒绿。

**排除面为什么是这三个目录** (不是"扫不到就算了", 是逐条给理由): 排除面与在册
裁定现住在唯一真源 ``ops/audit/env_scope.py`` (``EXCLUDED_SCOPE`` 按目录划界 +
``EXCLUDED_ONLY`` 逐键给理由), 本件只做监督: 现场推导出的排除面独有键必须与
``EXCLUDED_ONLY`` **集合相等**, 每项必须写明理由, 且都不该登记进 ``.env.example``。
``test/`` 与 ``evals/`` 读的是**测试自身的开关** (``PYBEST_RUN_LIVE``) 与**评测复现
元数据** (``evals/repro/manifest.py`` 的 ``HTTP_PROXY`` / ``BEST_API_TOKEN``),
``docs/diagrams/`` 读的是**本机 draw.io 渲染路径** (``ASTRO_BEST_DRAWIO_EXE`` 等) ——
它们都不构成部署期的配置输入面, 照 ``.env.example`` 配它们对用户毫无意义。判据还要求
"排除面里不得藏 runtime 读取": 真出现跨面读取 (例如 ``src/`` 去读 ``PYBEST_RUN_LIVE``)
时本件判红。

**为什么裁定住在 ops/ 而不是本件里** (2026-10-05 W1 收口时改): 门禁
``ops/audit/verify_crossrefs.py`` §7 也判同一个双向对账, 两边各持一份清单时,
同一批键会得到相反结论 (§7 要求登记那 6 个键, 本件断言不许登记)。裁定因此上移到
``ops/audit/env_scope.py``, 两边同口径导入 —— 归类面一份, 覆盖面仍只有
``scan_roots`` 一份。

反证夹具 (:meth:`TestCriterionFalsifiability`) 走与主判据**同一份**纯函数, 删掉
任一键即红 —— 证明它不是靠"清单恰好等于现状"恒绿。
"""
from __future__ import annotations

# 标准库: ast 静态扫 (不 import 被扫模块) / os 环境与假仓复制 / re 切键名与赋值行 /
#         shutil 复制门禁脚本 / subprocess 跑门禁 / sys 注 sys.path / pathlib 锚仓根
import ast
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

# 第三方: pytest 参数化 (判据级红测试的四形态注入共用一份断言体)
import pytest

SKILL_ROOT = Path(__file__).resolve().parents[3]   # 仓根: 本件在 test/unit/meta/ 下三级
AUDIT_DIR = SKILL_ROOT / "ops" / "audit"           # 扫描面唯一真源所在目录
if str(AUDIT_DIR) not in sys.path:                 # 幂等: 同目录裸名导入 (与门禁自身同纪律)
    sys.path.insert(0, str(AUDIT_DIR))
if str(SKILL_ROOT / "test") not in sys.path:       # 幂等: test/conftest.py 所在目录
    # 显式插入而不是指望 pytest 注入: 本文件被 test_no_module_skip_guards.py 在**干净
    # 子进程里裸导入**验过 (防模块级 skip 守卫把导入失败吞成静默退出收集集),
    # 那时 pytest 的路径注入不存在, 只写 ``from conftest import`` 会 ModuleNotFoundError。
    sys.path.insert(0, str(SKILL_ROOT / "test"))

import scan_roots  # noqa: E402  覆盖面唯一真源: 消费它而不是自列目录 (D5-01 的教训)

ENV_EXAMPLE = SKILL_ROOT / ".env.example"           # 声称是 SSOT 的那份文件

# 归类面真源: "哪些读取算部署期配置输入"的**在册裁定**住在 ops/audit/env_scope.py,
# 本件只做监督 (集合相等 / 理由非空 / 两侧不打架), 不再自己持第二份 (2026-10-05 W1)。
# 曾经的两份裁定直接打架: 门禁 §7 按"读到就要登记"判红那 6 个键, 本件按"非部署期
# 输入"断言它们**不许**登记 —— 同一批键两条相反的判据, 不可能同时对。
from conftest import gate_dependency_closure  # noqa: E402  造假仓只复制被测门禁 + 依赖闭包 (理由见该函数)
from env_scope import EXCLUDED_ONLY, EXCLUDED_SCOPE  # noqa: E402  归类面唯一真源

# env 键名的合法形状: 全大写 + 下划线。只收这个形状 —— 放宽会把 URL / 普通文案
# ("INFO" 这类枚举) 算成键名, 而噪声面一大, 判据迟早被人整体关掉。
KEY_SHAPE = re.compile(r"^[A-Z][A-Z0-9_]*$")   # 全大写 + 下划线: 放宽会把 INFO 这类枚举值算成键名


def _env_read_arg(node: ast.AST) -> ast.AST | None:
    """若节点是 env 读取调用/下标, 返回**键位实参**节点; 否则返回 None。

    认三种真实读取形态: ``os.environ.get("K")`` / ``os.getenv("K")`` /
    ``os.environ["K"]``。第三种是 ``Subscript`` 而非 ``Call``, 单独一个分支。

    Args:
        node: 待判定的 AST 节点。

    Returns:
        键位实参节点; 不是 env 读取则 None。
    """
    if isinstance(node, ast.Subscript):              # os.environ["KEY"] 形态
        owner = node.value
        if isinstance(owner, ast.Attribute) and owner.attr == "environ":
            return node.slice if isinstance(node.slice, ast.Constant) else None  # 常量下标才是键名
        return None                                                              # 变量下标解不出键名, 交由上层空转断言暴露
    if not isinstance(node, ast.Call):               # 其余两种都是方法调用
        return None
    func = node.func                                     # 取出被调用的那个属性访问节点
    if not isinstance(func, ast.Attribute):           # os.environ.get / os.getenv 的 func 是属性访问
        return None
    if func.attr == "getenv" and isinstance(func.value, ast.Name) and func.value.id == "os":
        return node.args[0] if node.args else None   # os.getenv("K")
    if func.attr == "get" and isinstance(func.value, ast.Attribute) and func.value.attr == "environ":
        return node.args[0] if node.args else None   # os.environ.get("K")
    return None                                      # 其余方法调用与 env 无关


def _module_key_constants(tree: ast.Module) -> dict[str, str]:
    """模块级 ``NAME = "UPPER_SNAKE"`` 字面量表 (env 键名常量的定义持有者)。

    只收模块顶层: 函数体内的局部名不是 env 键来源。收 AnnAssign 是因为类属性
    也会这样写 (``ENV_TOKEN: str = "..."``)。

    Args:
        tree: 已解析的模块语法树。

    Returns:
        ``{常量名: 键名}``; 值形状不合法的常量不入表 (那不是 env 键名)。
    """
    table: dict[str, str] = {}
    for node in tree.body:                            # 只看模块顶层: 函数体内的局部名不是 env 键来源
        if isinstance(node, ast.Assign):
            targets, value = list(node.targets), node.value   # 裸赋值形态 X = "KEY"
        elif isinstance(node, ast.AnnAssign):
            targets, value = [node.target], node.value        # 带标注形态 X: str = "KEY"
        else:
            continue
        if not (isinstance(value, ast.Constant) and isinstance(value.value, str)):
            continue                                  # 非字符串字面量不是 env 键名
        if not KEY_SHAPE.match(value.value):
            continue                                  # 形状不合法的值 (URL / 普通文案) 不算键
        for target in targets:
            if isinstance(target, ast.Name):
                table[target.id] = value.value         # 常量名 -> 键名: 供跨模块引用解析
    return table


def _env_keys_in_tree(tree: ast.Module, global_constants: dict[str, str]) -> set[str]:
    """扫一个**已解析**的模块真实读取到的 env 键名 (四种直取形态 + 三层间接)。

    收 tree 而非 path 是刻意的: 全仓扫描要对每个文件 parse 一次收常量表、再 parse
    一次收读取点, 同一棵树 parse 两遍既慢又让两遍结果可能不一致 (ruff B007 正是
    顺着这个重复读法报出来的)。

    **为什么必须解析间接层**: 本仓三种间接写法各藏着不同的一族键, 按字面量
    直取的旧正则对它们全部失明:

    1. **常量引用** (跨模块): ``ops/astro_best_cli.py`` 写
       ``os.environ.get(AUTH_PASSWORD_ENV)``, 那个常量定义在 ``src/__main__.py``。
       逐模块扫字面量永远扫不到 —— 故先收全仓常量表 (``global_constants``) 再解析。
    2. **形参流入** (``src/tap/service.py``): ``def _env_int(name, default)`` 内
       ``os.environ.get(name)``, 八个 ``BEST_TAP_*`` 键在**调用点**以字面量出现。
       故先算出"哪些函数的第 i 个形参会流入 env 读取", 再把调用点实参收为键名。
    3. **字典映射表** (``src/scripts/config.py``): ``env_map`` 的**键**才是 env 键,
       十个 ``BEST_*`` 全在这一形态里。故先找出"被 ``for`` 迭代的 dict 字面量",
       再收它的字符串键。

    静态解析而非 import: import 被扫模块等于执行它 (``ops/astro_best_cli.py``
    导入即改 ``sys.path``), 判据不该给测试进程留副作用。

    Args:
        tree: 已解析的模块语法树 (只解析, 不执行)。
        global_constants: 全仓模块级 env 键常量表, 用于解析跨模块常量引用。

    Returns:
        该模块真实读取的 env 键名集合; 扫不到即空集 (由调用方判是否为空转)。
    """
    consts = _module_key_constants(tree)           # 本模块的常量表: resolve 优先查它
    keys: set[str] = set()                        # 累加器: 各形态扫到的键名都汇到这里

    def resolve(node: ast.AST) -> str | None:
        """把键位实参节点解析成键名: 字面量直取, 或常量引用 (本模块 → 全仓)。"""
        if isinstance(node, ast.Constant) and isinstance(node.value, str) \
                and KEY_SHAPE.match(node.value):                        # 三个条件缺一不可: 形状判据在这里也生效
            return node.value                                              # 字面量直取: 键名就在调用点上
        if isinstance(node, ast.Name):                                    # 常量引用形态: 键名在别处定义
            return consts.get(node.id) or global_constants.get(node.id)   # 常量引用: 本模块优先, 否则全仓表
        return None                                                        # 其他表达式: 不硬凑, 交给空转断言暴露


    # ── 间接层 1: 形参流入 env 读取 (``_env_int(name, default)`` 形态) ──────────
    sink_positions: dict[str, set[int]] = {}   # 函数名 -> 会流入 env 读取的形参位序
    for func in [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:  # 同步与异步同形
        params = [a.arg for a in func.args.posonlyargs + func.args.args]   # 形参名与位序一一对应: 位序用来回取调用点实参
        hits = set()
        for sub in ast.walk(func):              # 函数体内部才认: 模块级的同名变量与本函数无关
            arg = _env_read_arg(sub)
            if isinstance(arg, ast.Name) and arg.id in params:
                hits.add(params.index(arg.id))                              # 只记本函数的形参: 别处的同名局部名无关
        if hits:
            sink_positions[func.name] = hits                                # 登记为"env sink": 其调用点的第 i 个实参即键名

    # ── 间接层 2: ``for`` 迭代的 dict 字面量 (``env_map.items()`` 形态) ─────────
    dict_literals: dict[str, ast.Dict] = {}    # 变量名 -> 该变量的 dict 字面量节点
    for node in ast.walk(tree):                      # 整棵树走一遍: 收全部 dict 字面量赋值
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Dict):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    dict_literals.setdefault(target.id, node.value)   # 首个定义优先: 同名变量被重绑不覆盖
        elif (isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
                and isinstance(node.value, ast.Dict)):
            dict_literals.setdefault(node.target.id, node.value)     # 带标注形态同上

    iterated_dicts: set[str] = set()           # 确认"被 for 迭代且键流入 env 读取"的 dict 名
    for loop in [n for n in ast.walk(tree) if isinstance(n, ast.For)]:   # 只认 for: while 迭代拿不到 .items()
        loop_names = {t.id for t in ast.walk(loop.target) if isinstance(t, ast.Name)}   # 解包元组目标: 只认具名的循环变量
        source = loop.iter                                                          # 被迭代的那个表达式
        if not loop_names or not (isinstance(source, ast.Call) and isinstance(source.func, ast.Attribute)):
            continue                                                                  # 不是 x.items() 形态: 收不了键, 跳过
        if source.func.attr != "items" or not isinstance(source.func.value, ast.Name):
            continue                                                                  # 同上: items() 必须挂在裸名上才认得出 dict 名
        for sub in ast.walk(loop):              # 循环体内是否有 env 读取用到该循环变量
            arg = _env_read_arg(sub)
            if isinstance(arg, ast.Name) and arg.id in loop_names:
                iterated_dicts.add(source.func.value.id)                            # 确认: 该 dict 的键就是 env 键
                break                                                                 # 一个循环只需记一次
    for name in iterated_dicts:                      # 只处理确认过的那些 dict
        for key_node in dict_literals.get(name, ast.Dict(keys=[], values=[])).keys:  # 收不到字面量即空 keys: 不硬凑
            if isinstance(key_node, ast.Constant) and isinstance(key_node.value, str) \
                    and KEY_SHAPE.match(key_node.value):
                keys.add(key_node.value)                                             # dict 的**键**才是 env 键名 (env_map 形态)

    # ── 四种直取形态 + 形参实参 ─────────────────────────────────────────────────
    for node in ast.walk(tree):                      # 整棵树走一遍: env 读取可能藏在任何嵌套层
        if isinstance(node, ast.Call):
            key = resolve(_env_read_arg(node))
            if key:
                keys.add(key)                                                        # 直取形态: os.environ.get / getenv
            if 0 in sink_positions.get(getattr(node.func, "id", ""), ()):   # 调用点字面量喂 env 形参
                for arg in node.args[:1]:
                    key = resolve(arg)
                    if key:
                        keys.add(key)                                                # 形参形态: _env_int("KEY", default)
    return keys


def _parse_all() -> list[tuple[str, ast.Module]]:
    """按覆盖面解析全仓 ``.py`` (语法错跳过: 由别处门禁负责报它)。"""
    parsed: list[tuple[str, ast.Module]] = []
    for rel, full in scan_roots.iter_py_files(str(SKILL_ROOT)):   # 覆盖面来自唯一真源, 不自列目录
        try:
            parsed.append((rel, ast.parse(Path(full).read_text(encoding="utf-8-sig"), filename=full)))  # 只解析, 不执行
        except SyntaxError:
            continue                                              # 跳过坏文件: 少扫一个文件不能让它变成假绿, 由空转断言兜底
    return parsed


def _code_env_keys() -> set[str]:
    """全仓**非排除面**代码真实读取的 env 键名全集 (事实侧唯一入口)。

    两遍走: 先收全仓模块级 env 键常量 (解析跨模块常量引用所需的全局表), 再按
    覆盖面逐文件抽取 —— 单遍做不到, 因为后扫的文件可能引用先扫文件定义的常量。
    """
    parsed = _parse_all()                          # 一次解析, 两遍共用 (ruff B007 曾顺着重复读法报出来)
    global_constants: dict[str, str] = {}
    for _, tree in parsed:
        for name, value in _module_key_constants(tree).items():
            global_constants.setdefault(name, value)    # setdefault: 首个定义优先, 同名常量不互相覆盖
    keys: set[str] = set()
    for rel, tree in parsed:
        if rel.startswith(EXCLUDED_SCOPE):
            continue                                      # 排除面: 理由见 EXCLUDED_SCOPE
        keys |= _env_keys_in_tree(tree, global_constants)
    return keys


def _declared_env_keys(text: str) -> set[str]:
    """从示例文件文本解析**已登记**的键 (只认赋值行, 注释行不算键)。

    与 ``ops/audit/verify_crossrefs.py §7`` 同口径 (``^KEY=``), 两条判据因此
    不会对同一个键给出相反结论。
    """
    return {m.group(1) for m in
            (re.match(r"^([A-Z][A-Z0-9_]*)=", line.strip()) for line in text.splitlines()) if m}


def _missing_declarations(text: str, code_keys: set[str] | None = None) -> list[str]:
    """代码真实读取、而示例文件未登记的键 (空列表 = 全覆盖 = 绿)。

    抽成纯函数是为了让反证夹具能就地喂一份"少登记一个键"的文本, 以及一份
    "多了一个读取点"的键集 —— 无需改磁盘上的真文件 (真文件由本函数在主判据里喂)。
    """
    return sorted((code_keys if code_keys is not None else _code_env_keys()) - _declared_env_keys(text))   # 缺一即红


class TestEnvSsotCoversAllCodeReads:
    """``.env.example`` 声称的"每个键都必须能被代码真实读取"必须双向成立。"""

    def test_scan_is_not_vacuous(self):
        """前提: 代码侧必须真的扫出非空键集 —— 空转时下面两条全部恒绿。"""
        found = _code_env_keys()                          # 现场扫一遍: 空集即门禁失效
        assert found, (
            "全仓 AST 扫出 0 个 env 键: 本门禁已失效 (扫描面漂移 / 键名形状判据被改窄?)"
        )
        assert len(found) >= 14, (                        # 14 = 本轮实测数; 掉下来说明解析层退化
            f"只扫出 {len(found)} 个键, 少于本轮实测的 14 个 —— 解析层退化了: {sorted(found)}"
        )

    def test_every_code_read_key_is_declared(self):
        """代码真实读取的每个 env 键都必须在示例文件里登记 (漏登记即判红)。"""
        missing = _missing_declarations(ENV_EXAMPLE.read_text(encoding="utf-8-sig"))   # 差集: 代码有而示例无
        assert not missing, (
            f"代码真实读取、而 .env.example 漏登记 {len(missing)} 个 env 键: {missing} —— "
            "照示例文件配置的用户配不出这个通道 (唯一的注入点是 env); "
            "请在 .env.example 补登记并写明消费方与缺省值"
        )

    def test_no_declared_key_is_dead(self):
        """反向: 示例文件登记的每个键都必须真有代码读取它 (多登记即判红)。

        反方向与正方向同重要: 登记一个没人读的键, 用户会以为配了它有用 ——
        那比漏登记更坏, 因为它看起来像一份可执行的部署说明。
        """
        declared = _declared_env_keys(ENV_EXAMPLE.read_text(encoding="utf-8-sig"))
        dead = sorted(declared - _code_env_keys())      # 反向差集: 示例有而代码无
        assert not dead, (
            f".env.example 登记了而代码无处读取的键: {dead} —— "
            "要么它已被消费方删掉 (则从示例文件删登记), 要么它真的该被读 (则补消费方)"
        )

    def test_excluded_scope_keys_are_pinned_and_not_registered(self):
        """排除面独有的 env 键必须**逐个在册**, 且都不该登记进 ``.env.example``。

        这条把 :data:`EXCLUDED_SCOPE` 从"兜底洞"钉成"受监督的取舍"。它比对的是
        **集合相等**, 不是"没有新东西" —— 于是三种演进各有一条明确出路:

        - 新增一个只在排除面被读取的键 → 本件红 → 人裁定它属不属于部署期配置
          (属: 登记进 ``.env.example`` 并移出排除面; 不属: 在 :data:`EXCLUDED_ONLY`
          补一行理由);
        - 某个在册键被删干净 → 本件红 → 把那一行删掉 (避免死登记);
        - 排除面某个键悄悄变成部署期配置 → :meth:`test_every_code_read_key_is_declared`
          那条正判据接手。

        逐个理由见 :data:`EXCLUDED_ONLY`。
        """
        excluded_only = self._excluded_only_keys()      # 现场算: 排除面独有 vs runtime 面独有
        assert excluded_only == set(EXCLUDED_ONLY), (
            "排除面独有的 env 键集合变了: "
            f"新增 {sorted(excluded_only - set(EXCLUDED_ONLY))}, "
            f"消失 {sorted(set(EXCLUDED_ONLY) - excluded_only)} —— "
            "前者要么该登记进 .env.example, 后者要从 EXCLUDED_ONLY 删掉"
        )
        blank = sorted(key for key, reason in EXCLUDED_ONLY.items() if not reason.strip())
        assert not blank, (
            f"EXCLUDED_ONLY 里这些键没写排除理由: {blank} —— "
            "逐项给理由是这份在册清单的全部价值: 空理由等于把取舍藏进代码"
        )
        declared = _declared_env_keys(ENV_EXAMPLE.read_text(encoding="utf-8-sig"))
        overlapped = sorted(set(EXCLUDED_ONLY) & declared)   # 两侧裁定必须一致: 不能两头占
        assert not overlapped, (
            f"这些键在 EXCLUDED_ONLY 里被裁定为非部署期输入, 却又登记进了 .env.example: "
            f"{overlapped} —— 两侧裁定必须一致 (要么登记要么排除, 不能两头占)"
        )

    @staticmethod
    def _excluded_only_keys() -> set[str]:
        """只在排除面被读取、runtime 面没有读取点的 env 键 (本件的第三类事实)。"""
        parsed = _parse_all()
        global_constants: dict[str, str] = {}
        for _, tree in parsed:
            for name, value in _module_key_constants(tree).items():
                global_constants.setdefault(name, value)
        inside: set[str] = set()
        outside: set[str] = set()
        for rel, tree in parsed:
            target = outside if rel.startswith(EXCLUDED_SCOPE) else inside
            target |= _env_keys_in_tree(tree, global_constants)
        return outside - inside


class TestCriterionFalsifiability:
    """反证: 判据必须能被证伪 —— 删掉一个登记键 / 伪造一个读取点都要变红。"""

    def test_deleting_one_declaration_turns_the_criterion_red(self):
        """删掉 ``.env.example`` 里任意一个键, 同一判据必须点名它。

        没有这条, "清单恰好等于现状"就能让主判据恒绿 —— 那测的就不是判据, 只是
        现状的复印件。
        """
        original = ENV_EXAMPLE.read_text(encoding="utf-8-sig")
        declared = _declared_env_keys(original)          # 现场解析: 不另抄一份键表来自证自洽
        assert declared, "示例文件里一个键都没有: 反证无从下手 (先修 .env.example)"
        victim = sorted(declared)[0]                    # 取字典序第一个: 确定性, 不靠随机
        line = next(ln for ln in original.splitlines() if ln.startswith(f"{victim}="))
        mutilated = original.replace(line, f"# 删除的登记: {victim}", 1)   # 注释掉那一行 = 真删登记
        assert _declared_env_keys(mutilated) < declared, (
            f"反证夹具没真删掉 {victim}: 替换未生效, 夹具本身失效"
        )
        missing = _missing_declarations(mutilated)      # 与主判据同一份纯函数
        assert victim in missing, (
            f"删掉 {victim} 后判据没有点名它 —— 本门禁对该方向失明: {missing}"
        )

    def test_planting_an_undeclared_read_turns_the_criterion_red(self, tmp_path):
        """在 runtime 面放一个未登记的读取点, 同一判据必须点名那个新键。

        与上一条构成两个方向: 少登记 (从示例文件删) 与漏登记 (往代码加), 少
        任何一条都只剩单向覆盖。
        """
        planted = "PLANTED_UNDECLARED_ENV_KEY"
        source = tmp_path / "planted.py"
        source.write_text(
            "import os\n\n\n"
            "def read_it() -> str:\n"
            f'    return os.environ.get("{planted}", "")\n',
            encoding="utf-8",
        )
        # 走与主判据同一份抽取函数: 夹具必须被认成一个真实读取点
        planted_tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
        planted_keys = _env_keys_in_tree(planted_tree, {})
        assert planted in planted_keys, f"夹具自身失效: 判据认不出字面量直取形态, 实得 {planted_keys}"
        # 再走与主判据同一份差集函数: 该键必须落在"漏登记"清单里
        text = ENV_EXAMPLE.read_text(encoding="utf-8-sig")
        assert planted not in _declared_env_keys(text)    # 前提: 真文件里确实没有它
        missing = _missing_declarations(text, code_keys=_code_env_keys() | planted_keys)
        assert planted in missing, f"未登记的读取点没被点名 —— 判据对该方向失明: {missing}"


# 假仓的九节最小骨架: 门禁一响全量, 任何一节的必读源缺失都会让整仓 exit 非零, 于是
# "这一节判红了"与"假仓本身不完整"分不开 (test_gate_criterion_red.py 踩过这个坑)。
_FAKE_EC = ("skill: astro-best\nkind: error-codes\ncodes:\n"
            "  BEST_0001:\n    code: E_DEMO_CODE\n    trigger: 演示\n    behavior: block\n")


def _write_file(fake: Path, rel: str, text: str) -> None:
    """往假仓里写一个文件 (自动建父目录)。"""
    path = fake / rel                                                    # 假仓内的相对路径 (本类所有落点都走它)
    path.parent.mkdir(parents=True, exist_ok=True)                       # 幂等: 同一节可能被两条用例各写一次
    path.write_text(text, encoding="utf-8")                              # 显式 utf-8: 假仓里有中文 docstring


def _fake_env_repo(tmp_path: Path) -> Path:
    """造假仓: 被测门禁 (+ 同目录依赖闭包) + 九节骨架 + 一对 env 键。

    门禁用 ``parents[2]`` 定位仓根且没有 root 参数, 所以唯一不改门禁代码就换扫描面的
    办法就是把门禁复制到 ``假仓/ops/audit/`` 下。只复制**依赖闭包**而不是整个
    ``ops/audit/``: 多复制一个门禁就等于往假仓扫描面里塞一个与被测命题 (env 双向对账)
    无关的 ``.py``, 它的任何违规都会让本类的「干净对照组」变红 —— 门禁失败方向审计
    (2026-10-05, N2 复核) 实测过这条污染通道, 完整记录见
    ``test/conftest.py::gate_dependency_closure``。
    """
    fake = tmp_path / "fakerepo"                                         # 门禁的仓根随之落到 tmp
    (fake / "ops" / "audit").mkdir(parents=True)                        # 门禁脚本的落位: 决定它的仓根
    for filename in gate_dependency_closure("verify_crossrefs"):        # 被测门禁 + 递归依赖, 不多不少
        shutil.copy(SKILL_ROOT / "ops" / "audit" / filename, fake / "ops" / "audit" / filename)  # 原样复制: 测的是真门禁, 不是复刻品
    _write_file(fake, "references/skills-spec.local.yaml",          # 第 1 节
                "skills:\n  astro-best:\n    algorithms:\n    - name: demo\n      module: src.app\n")
    _write_file(fake, "contracts/input.contract.yaml", "module: src.app\n")       # 第 2 节
    _write_file(fake, "pipeline.yaml",                                          # 第 3 节
                "pipeline:\n  workflows:\n    - name: demo\n      steps:\n        - tool: src.app\n")
    _write_file(fake, "static/fragments/algo_mode/two_stage_async_mode.yaml",     # 第 4 节
                "entry: src.app\n")
    _write_file(fake, "manifest.yaml", "always_load:\n  - src/app.py\n")          # 第 5 节: 路径必须真存在
    _write_file(fake, "src/__init__.py", '__all__ = ["app"]\n')                 # 第 6 节: src 包要可导入
    _write_file(fake, "contracts/error-codes.contract.yaml", _FAKE_EC)           # 第 8 节: 已登记码
    _write_file(fake, "src/app.py", 'E_DEMO_CODE = "E_DEMO_CODE"\n')             # 已登记码在用 (第 8 节两向都靠它)
    for doc in ("SKILL.md", "README.md", "architecture.md", "contracts/io-contract.md",   # 第 9 节
                "references/ALGORITHM-SPEC.md", "references/download-playbook.md",
                "references/site-endpoints-and-interactions.md"):
        _write_file(fake, doc, "# 占位文档\n")                                   # 占位即可: 第 9 节只查文件在不在
    # 第 7 节 (本类的被测对象): 一对"登记了且真被读"的键, 对照组据此必须绿
    _write_file(fake, ".env.example", "ASTRO_BEST_DEMO=1\n")                      # 登记侧
    _write_file(fake, "src/app.py", 'E_DEMO_CODE = "E_DEMO_CODE"\nimport os\n\n\n'   # 读取侧 (形态 a)
                                    'def read_demo() -> str:\n    return os.environ.get("ASTRO_BEST_DEMO", "")\n')
    return fake                                                            # 九节齐备的对照组假仓


def _run_gate(fake: Path) -> subprocess.CompletedProcess:
    """在假仓里以子进程跑 verify_crossrefs (子进程: 它是"导入即执行"的脚本体)。"""
    return subprocess.run([sys.executable, str(fake / "ops" / "audit" / "verify_crossrefs.py")],
                          capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=300, cwd=str(fake),                        # cwd 指向假仓: 门禁按相对路径读源
                          env={**os.environ, "PYTHONIOENCODING": "utf-8"})   # 只覆盖编码: 其余环境原样继承


# 四种读取形态各注入一份源码, 断言"未登记 → 门禁点名那个键"。形态名进 id, 退化时报错
# 直接告诉人是哪一条形态被改坏了。
_READ_FORMS = {                                                        # 键 = pytest 的用例 id
    "a-字面量直取": 'import os\n\n\ndef read() -> str:\n    return os.environ.get("{key}", "")\n',
    "b-本地包装器": 'def _env_int(name: str, default: int) -> int:\n    return default\n\n\n'   # 第四形态
                    'def read() -> int:\n    return _env_int("{key}", 1)\n',
    "c-env_map键": 'env_map = {{\n    "{key}": "field",\n}}\n',                     # 只在配置面认
    "d-env键常量": 'ENV_DEMO_TOKEN = "{key}"\n',                              # 左值自带 env 形状
}


class TestCrossrefsEnvSectionIsNotVacuous:
    """verify_crossrefs §7 的 env 双向对账必须真的判红 (不是恒绿, 也不是恒红)。

    **为什么这些用例放在本件而不是 ``test_gate_criterion_red.py``**: 那一份是门禁判据
    级红测试的家, 但它已到 391/400 净行 (铁律 2 的硬闸), 再加就会撞预算门禁; 而本件
    本来就是 env 对账的家, 把 §7 的红测试放这儿主题一致、预算有余。
    方法论 (假仓 + 对照组) 与那份一致: 门禁没有 root 参数, 只能在 ``tmp_path`` 里造假
    仓, 且**每条用例都配一道未注入缺陷的对照** —— 少了对照, "门禁恒红"同样能满足
    ``!= 0``, 那测的就不是判据, 只是"它会崩"。
    """

    def test_clean_fake_repo_exits_zero(self, tmp_path):
        """对照: 九节齐备、env 两侧一致的假仓必须 exit 0。"""
        proc = _run_gate(_fake_env_repo(tmp_path))                         # 直接跑对照仓, 不注入任何缺陷
        assert proc.returncode == 0, f"干净假仓必须 exit 0, 实得 {proc.returncode}: {proc.stdout[-500:]}"

    def test_deleting_a_declared_key_is_rejected(self, tmp_path):
        """方向一 (少登记): 从 .env.example 删掉一个真被读的键 -> 必须判红并点名它。

        少了这条, ".env.example 漏登记"这个方向无人看守, 而漏登记的键用户根本配不出来。
        """
        fake = _fake_env_repo(tmp_path)                                   # 九节齐备的对照仓
        _write_file(fake, ".env.example", "# 登记被删掉了\n")             # 注入: 真删登记 (留一行注释也算删)
        proc = _run_gate(fake)                                           # 跑真门禁的副本
        assert proc.returncode != 0, f"少登记必须判红, 实得 exit={proc.returncode}: {proc.stdout[-500:]}"
        assert "ASTRO_BEST_DEMO" in proc.stdout, f"必须点名那个键: {proc.stdout[-500:]}"

    def test_adding_an_unreadable_key_is_rejected(self, tmp_path):
        """方向二 (多登记): 往 .env.example 加一个没人读的键 -> 必须判红并点名它。

        反方向与正方向同重要: 登记一个没人读的键, 用户会以为配了它有用。
        """
        fake = _fake_env_repo(tmp_path)                                   # 九节齐备的对照仓
        _write_file(fake, ".env.example", "ASTRO_BEST_DEMO=1\nASTRO_BEST_NO_SUCH_READ=1\n")  # 注入死登记
        proc = _run_gate(fake)                                           # 跑真门禁的副本
        assert proc.returncode != 0, f"多登记必须判红, 实得 exit={proc.returncode}: {proc.stdout[-500:]}"
        assert "ASTRO_BEST_NO_SUCH_READ" in proc.stdout, f"必须点名那个键: {proc.stdout[-500:]}"

    @pytest.mark.parametrize("form", sorted(_READ_FORMS))
    def test_each_read_form_outside_the_example_is_reported(self, tmp_path, form):
        """四种读取形态逐个注入: 未登记时必须判红并点名 —— 少认一种就误报/漏报。

        ``c-env_map键`` 注入在 ``src/scripts/config.py`` (形态 c 只在配置面认, 见门禁里
        ``ENV_MAP_FILES`` 的理由); ``d-env键常量`` 刻意放在**配置面之外**的那个 app 模块:
        它守的正是 2026-10-05 实测的病灶 —— 形态 d 原先只在配置面名单里认, 于是
        ``guards.py`` 的 ``DATA_ROOT_ENV`` 与 ``dispatch.py`` 的 ``ENV_TOKEN`` 被误报成
        "代码未读取"。
        """
        key = "ASTRO_BEST_FORM_PROBE"                                     # 注入用的键: 刻意不在 .env.example 里
        target = "src/scripts/config.py" if form.startswith("c") else "src/app.py"   # c 形态要落配置面, 其余落配置面之外
        fake = _fake_env_repo(tmp_path)                                   # 先造九节齐备的对照仓
        body = _READ_FORMS[form].format(key=key)                          # 把键填进该形态的源码模板
        if target == "src/app.py":                       # 覆盖 app 模块时保住第 8 节要的已登记码引用
            body = 'E_DEMO_CODE = "E_DEMO_CODE"\n' + body                # 否则门禁会因第 8 节而红, 与本条无关
        _write_file(fake, target, body)                                  # 注入: 只改这一处, 其余九节不动
        proc = _run_gate(fake)                                           # 跑真门禁的副本
        assert proc.returncode != 0, (
            f"形态 {form} 的读取点未登记却判绿, 实得 exit={proc.returncode}: {proc.stdout[-500:]}"
        )
        assert key in proc.stdout, f"形态 {form} 判红必须点名那个键: {proc.stdout[-500:]}"

    def test_read_hidden_behind_an_inline_comment_is_still_found(self, tmp_path):
        """跨行的实参前置注释不得让真读取消失 (``BEST_LOCAL_TAP_URL`` 的病灶)。

        ``src/tap/client.py:108-109`` 就是这个形态: ``os.environ.get(`` 后面跟行尾
        注释, 字符串实参在下一行。旧正则的 ``\\s*`` 匹配不过注释, 于是那个键被报成
        ".env.example 有而代码未读取" —— 判据的跨行漏洞, 不是键名写错。
        """
        key = "ASTRO_BEST_COMMENTED"                                     # 注入用的键: 刻意不在 .env.example 里
        fake = _fake_env_repo(tmp_path)                                   # 先造九节齐备的对照仓
        _write_file(fake, "src/app.py", 'E_DEMO_CODE = "E_DEMO_CODE"\nimport os\n\n\ndef read() -> str:\n'
                                        '    return os.environ.get(  # 端点有兜底值\n'   # 病灶: 实参前有注释
                                        f'        "{key}", "http://127.0.0.1")\n')
        proc = _run_gate(fake)                                           # 跑真门禁的副本
        assert proc.returncode != 0, f"带注释的真读取未登记却判绿: {proc.stdout[-500:]}"
        assert key in proc.stdout, f"必须点名那个键: {proc.stdout[-500:]}"

    def test_prose_that_merely_mentions_a_read_is_not_a_read(self, tmp_path):
        """反向自证: 注释/docstring 里**示意**的读取写法不得被当成读取点。

        这条与上一条成对, 证明"剥散文"不是单向放宽: 不剥时, 门禁**自己的注释**里那句
        ``os.environ.get("KEY")`` 会被当成真实 env 键 ``KEY`` (``K`` / ``KEY`` 两个噪声
        键正是这么进来的) —— 噪声源迟早被人整体关掉, 那才是真的 fail-open。判绿才是
        本条要的结论: 散文里的键既不该被要求登记, 也不该让门禁变红。
        """
        key = "ASTRO_BEST_PROSE_ONLY"                                    # 只出现在散文里, 代码真读的是 DEMO 键
        fake = _fake_env_repo(tmp_path)                                   # 先造九节齐备的对照仓
        _write_file(fake, "src/app.py",
                    'E_DEMO_CODE = "E_DEMO_CODE"\n'
                    f'"""docstring 里的示意写法: ``os.environ.get("{key}")`` 不是读取点。"""\n'
                    f'import os  # 注释里的示意写法: os.getenv("{key}") 也不是读取点\n\n\n'
                    'def read() -> str:\n    return os.environ.get("ASTRO_BEST_DEMO", "")\n')
        proc = _run_gate(fake)                                           # 散文键若被误收, 这一条会红
        assert proc.returncode == 0, (
            f"散文里的 {key} 被当成了真实读取点 (噪声源): {proc.stdout[-500:]}"
        )

    def test_key_ruled_out_as_non_deployment_is_not_demanded(self, tmp_path):
        """在册裁定必须被门禁采纳: 非部署期输入的键不被要求登记进 .env.example。

        少了这条, 门禁会与 ``ops/audit/env_scope.py`` 的裁定对着干 (同一批键一条要求
        登记、一条断言不许登记)。也正因它才需要**真读**: 键从排除面文件里被读到, 而
        门禁仍判绿 —— 证明扣的是"裁定", 不是"扫描面" (扫描面仍是全仓)。
        """
        fake = _fake_env_repo(tmp_path)                                   # 先造九节齐备的对照仓
        ruled = sorted(EXCLUDED_ONLY)[0]                                  # 取在册裁定里的一个键 (确定性, 不靠随机)
        _write_file(fake, "test/live_probe.py", 'import os\n\n\ndef probe() -> str:\n'   # 落在排除面前缀下
                                                 f'    return os.environ.get("{ruled}", "")\n')
        proc = _run_gate(fake)                                           # 键被真读到, 但不该被要求登记
        assert proc.returncode == 0, (
            f"已在册裁定为非部署期输入的 {ruled} 不该被要求登记: {proc.stdout[-500:]}"
        )
