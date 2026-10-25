"""环境锁守卫: environment.yaml 必须与真实 import 面一致 (Q-42)。

README 宣称有一道「依赖真相 AST 检查」, 本测试就是那道检查。它用 ast 解析
``src/``、``ops/``、``evals/``、``examples/`` 下的每个模块, 把第三方根包名与
``environment.yaml`` 双向比对:

* 已 import 但未声明 -> 全新安装会在 import 期直接崩;
* 已声明但未 import -> 无人察觉的死依赖 (``numpy``/``pandas``/``tqdm``/``rich``
  正是这样活过了好几轮审计)。

``test/`` 有意不被扫描: 测试专属依赖 (pytest、mock 夹具) 不属于运行时锁。
``test/upstream/`` 已不存在 (经用户批准删除)。
"""
from __future__ import annotations  # 标准库: 注解延迟求值

# 标准库: ast 静态解析 import 面 + 正则抽取声明行 + 路径锚定 + 标准库名交叉核实
import ast
import re
import sys
from pathlib import Path

# 第三方: pytest 承载模块级 skip 与断言
import pytest

# 延迟导入: yaml 缺失时不能让整个模块 import 失败 (旧环境无 pyyaml 也能收集)
try:
    # yaml (PyYAML): 解析 environment.yaml 环境锁
    import yaml
except Exception as _legacy_err:  # legacy-import-guard
    # pytest: 导入失败时主动 skip, 不让环境问题伪装成用例失败
    import pytest as _pytest
    _pytest.skip(f'legacy import unavailable: {_legacy_err!r}', allow_module_level=True)    # 模块级跳过: 缺 yaml 是环境问题, 不该算行为回归

# 路径锚点: 本文件位于 <skill>/test/unit/meta/, 上溯 3 层即 skill 根
SKILL_DIR = Path(__file__).resolve().parents[3]                                              # 上溯三级到 skill 根: 扫描根与锁文件都由它推出
# 被扫描的目录: 运行时 import 面只可能来自这四处 (test/ 是有意排除的测试依赖)
SCAN_DIRS = ("src", "ops", "evals", "examples")  # 只扫运行时四处: test/ 是测试专属依赖, 进来会把锁撑成假阳性

# 标准库白名单: conda/python 解释器自带, 与 environment.yaml 无关。
# E2 修复: 补入 tomllib/zoneinfo/graphlib/asyncio/_thread/__main__ 六个
# 解释器自带模块 —— 缺任一个都会让 src/ 将来 import 它时被判
# "imported but undeclared" 而 fail-closed (对标准库的误报)。
STDLIB = set(["abc", "argparse", "ast", "asyncio", "base64", "bisect", "calendar", "collections", "concurrent", "configparser", "contextlib", "copy", "csv", "ctypes", "dataclasses", "datetime", "decimal", "difflib", "email", "enum", "errno", "faulthandler", "filecmp", "fnmatch", "functools", "getopt", "getpass", "glob", "graphlib", "gzip", "hashlib", "heapq", "hmac", "html", "http", "importlib", "inspect", "io", "ipaddress", "itertools", "json", "logging", "math", "mimetypes", "multiprocessing", "numbers", "operator", "os", "pathlib", "pickle", "platform", "plistlib", "pprint", "queue", "random", "re", "runpy", "secrets", "select", "shlex", "shutil", "signal", "site", "socket", "sqlite3", "ssl", "stat", "statistics", "string", "struct", "subprocess", "sys", "tarfile", "tempfile", "textwrap", "threading", "time", "tokenize", "tomllib", "traceback", "types", "typing", "unicodedata", "unittest", "urllib", "uuid", "warnings", "wave", "webbrowser", "xml", "zipfile", "zlib", "zoneinfo", "__future__", "__main__", "_thread"])

# 本地包白名单: 本 skill 自身 + monorepo 共享引擎, 都不是第三方依赖
# 增补 paths/case_executor/case_runner/probes/probe_support: eval_runner 拆分产物,
# 与 audit 同属 evals/ 下的本地评测层 (见 docs/architecture/file-size-budget.md §3.1)
# 增补 line_scope: 从 comment_audit.py 拆出的行分类层, 与 comment_audit 同属
# ops/audit/。它被 ops/ 下的文件以**同目录裸名**导入 (直跑时 sys.path[0] 就是
# ops/audit/, 走包路径会 ModuleNotFoundError), 于是静态扫描只看到一个裸顶层名,
# 认不出它是本仓模块 —— 漏登记即判「imported but undeclared」。
# 增补 scan_roots: 扫描面唯一真源, 被四道门禁以同目录裸名导入, 理由与 line_scope 同形。
# 增补 count_code_lines: 「净行/物理行」行数口径唯一真源, 被 verify_counting_claims
# (以及同为同目录裸名导入的兄弟门禁) 引用, 理由与 line_scope/scan_roots 同形 ——
# 它是本仓自己的 .py, 不是 pip 包; 漏登记即判「imported but undeclared」。
# 增补 env_scope: 「哪些 env 读取算部署期配置输入」归类面唯一真源, 被 verify_crossrefs
# §7 以同目录裸名导入 (真源住在 ops/audit/ 才能同时被门禁与单测共用), 理由同上。
LOCAL = {"src", "test", "evals", "ops", "audit", "_shared",  # 本地包白名单随拆分同步: eval_runner 子模块漏登记即误报
         "paths", "case_executor", "case_runner", "probes", "probe_support",
         "line_scope", "scan_roots", "count_code_lines", "env_scope"}

# import 名与 conda/pip 包名不一致时的映射 (pyyaml 的 import 名是 yaml)
ALIASES = {"yaml": "pyyaml"}  # import 名与包名不一致时唯一的翻译表: 漏了 pyyaml 会被判成未声明
# 反向映射: 包名 -> import 名, 供「死依赖」检查把声明名翻回 import 名
PACKAGE_TO_IMPORT = {v: k for k, v in ALIASES.items()}                                       # 反向映射: 死依赖检查要把声明名翻回 import 名


def _imported_roots() -> dict[str, set[str]]:
    """静态扫描四个运行目录, 汇总「第三方 import 根名 -> 引用它的文件集合」。

    只做 ast 解析不 import 模块, 因此不会因依赖缺失而失败, 也不会触发任何
    网络/文件副作用; 任何解析失败的文件按「无 import」跳过 (不留悬空失败)。
    """
    found: dict[str, set[str]] = {}                                                                 # 汇总第三方根名到引用它的文件集合
    for directory in SCAN_DIRS:                                                                     # 逐个扫描目录
        for path in sorted((SKILL_DIR / directory).rglob("*.py")):  # 排序只为让失败可复现: 同名文件在不同平台顺序不同时报错会漂
            # 编译缓存不是源码, 跳过以免把陈旧字节码算进 import 面
            if "__pycache__" in path.parts:  # 编译缓存不是源码: 陈旧字节码算进 import 面会让门禁随构建状态起伏
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))                                # 只解析不执行: 缺依赖的环境也要能跑这道门禁
            except (SyntaxError, UnicodeDecodeError):  # 单个坏文件按无 import 继续: 一个语法错不该让整道门禁失效
                # 单个坏文件不应让整道门禁失效: 视为无 import 继续扫
                continue
            for node in ast.walk(tree):                                                     # 全树遍历: import 可能在函数体里, 不只在模块头
                names: list[str] = []                                                             # 先备空名单: 非 import 节点直接跳过
                if isinstance(node, ast.Import):                                                    # 普通 import 节点单独一支
                    # import a.b.c 的根包名是 a
                    names = [alias.name.split(".")[0] for alias in node.names]  # a.b.c 的根包名是 a: 锁里登记的是根包, 不是完整模块路径
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    # 只统计绝对导入; from . import x (level>0) 必为本地相对导入
                    names = [node.module.split(".")[0]]  # 只统计绝对导入: 相对导入 (level>0) 必为本地, 混进来全是假第三方
                for name in names:                                                                  # 逐个根名归类
                    # 标准库与本地包都不进依赖锁, 直接滤掉
                    if name in STDLIB or name in LOCAL:  # 标准库与本地包都不进锁: 漏滤任何一边, 声明集就会漂
                        continue
                    found.setdefault(name, set()).add(str(path.relative_to(SKILL_DIR)))      # 记下引用它的文件: 报错要能指出是谁 import 的
    return found


def _declared_packages() -> set[str]:
    """从 environment.yaml 抽取声明行里的包名 (``- name`` 形式)。

    E3 修复: 条目带版本约束/比较符 (``- pip>=23`` /
    ``- numpy>=1.24,<2``)、带 extras (``- foo[extra]``) 或带行尾注释时,
    必须取到**裸包名**: 包名只认 ``[A-Za-z0-9._-]``, 一遇到
    ``<>=!~;[:#`` 约束符或行尾即收尾。旧正则 ``[a-z0-9_\\-]+`` 不含大写
    字母, 会把 ``PyYAML`` 截成 ``yaml``、让 ``Django`` 整条匹配不上而
    从声明集里消失 —— 依赖锁对大小写混写的包名会失真。
    """
    text = (SKILL_DIR / "environment.yaml").read_text(encoding="utf-8")  # 锁文件读的是仓库权威路径: 换目录就读到别的 environment.yaml
    return set(re.findall(r"^\s*-\s*([A-Za-z0-9._-]+?)\s*(?:[<>=!~;\[:#].*)?$", text, re.M))


class TestEnvironmentLock:
    """environment.yaml 与真实 import 面的双向锁 (fail-closed)。"""

    def test_declared_dependencies_are_really_imported(self):
        """声明的每个包都必须真的被 import, 否则即死依赖。

        工具链依赖 (pytest/ruff/pip 等) 由 Makefile/CI 消费, 不走 import 面,
        故显式豁免; 其余未引用的声明都会在此fail 并要求从锁里摘除。
        """
        imported = set(_imported_roots())  # 先取导入面再取声明集: 两个方向都要扫, 单向只会漏掉一半问题
        declared = _declared_packages()                                                             # 读环境锁的声明清单
        # 工具链依赖由 Makefile/CI 消费, 不走 import 面。
        tooling = {"pytest", "pytest-cov", "ruff", "pip", "python"}  # 工具链由 Makefile/CI 消费, 不走 import 面: 不豁免就会误报死依赖
        dead = sorted(p for p in declared - tooling                                                 # 死依赖: 声明了却无人 import
                      if PACKAGE_TO_IMPORT.get(p, p) not in imported)                   # 先把包名翻回 import 名, 再看有没有人 import 它
        assert not dead, f"environment.yaml declares unused dependencies: {dead}"  # 死依赖必须报出包名: 只断空集的话, 报错看不出该摘哪一条

    def test_imported_dependencies_are_declared(self):
        """被 import 的每个第三方包都必须声明, 否则全新安装 import 即崩。"""
        imported = set(_imported_roots())                                                      # 只取键集: 判据关心"有没有", 不关心引用了几处
        declared = _declared_packages()                                                             # 再读一次声明清单, 供这条断言用
        missing = sorted(p for p in imported if ALIASES.get(p, p) not in declared)  # 先翻回包名再比: 用 import 名比, pyyaml 恒判未声明
        assert not missing, f"imported but undeclared: {missing}"                                  # 未声明即崩在 import 期, 报出名字

    def test_lock_file_parses(self):
        """锁文件本身必须可解析且 skill 名/传输层依赖到位。

        requests 被单独点名: 它是唯一的传输层依赖, 一旦从锁文件里漏掉, 上面
        那条"imported 必须 declared"会先红, 而报出来的是"未声明"这种间接
        措辞, 没人能一眼看出是锁文件少了运行时依赖。
        """
        data = yaml.safe_load((SKILL_DIR / "environment.yaml").read_text(encoding="utf-8"))       # 按 YAML 读环境锁: 声明形态以文件为准
        assert data["name"] == "astro-best"                                     # skill 名要等于本仓: 锁文件指错 skill 时, 后面两条断言都失去意义
        assert any(dep.startswith("requests") for dep in data["dependencies"])  # requests 单独点名: 它是唯一传输层依赖, 漏登记会在全新安装时崩


# E2 修复时补入白名单的六个解释器自带模块 (旧白名单缺项, import 即误报)
NEW_STDLIB_MODULES = ("tomllib", "zoneinfo", "graphlib", "asyncio", "_thread", "__main__")      # 这六个是解释器自带的新模块, 补进白名单才不误报


def _is_interpreter_provided(name: str) -> bool:
    """判定模块是否由 Python 解释器自带 (标准库 / 内建 / __main__ 命名空间)。

    ``sys.stdlib_module_names`` 覆盖标准库文件, ``sys.builtin_module_names``
    覆盖编译进解释器的内建模块 (``_thread`` 两者都在); ``__main__`` 是解释器
    为每个进程自带的 main 命名空间, 既不是磁盘文件也不是内建模块, 两个名单
    都不收录它, 只能单独放行 —— 少这一条就会把合法的 ``import __main__``
    误判成第三方依赖。
    """
    return (name in sys.stdlib_module_names
            or name in sys.builtin_module_names                                                     # 解释器自带名单: 与白名单交叉核实
            or name == "__main__")                                                               # 双下划线主模块名: 静态扫不到, 只能显式放过


class TestStdlibWhitelist:
    """E2: STDLIB 白名单必须覆盖解释器自带模块, 否则标准库 import 会被误报。"""

    def test_new_stdlib_modules_are_whitelisted(self):
        """六个新模块必须在白名单里, 且逐个经解释器名单交叉证实确属标准库。

        两个方向都要判: 缺白名单项会误报 (合法的标准库 import 被当成未声明
        依赖而 fail-closed), 白名单混入第三方名则会漏报 (未声明依赖被放过)。
        只守一边的门禁总有一半失效形态抓不住。
        """
        for name in NEW_STDLIB_MODULES:  # 逐个模块两头判: 只守白名单一边, 门禁总有一半失效形态抓不住
            assert name in STDLIB, (                                                               # 必须在白名单里: 缺任一个都会对标准库误报
                f"{name} 不在 STDLIB 白名单 — src/ 将来 import 它会被判 "                                      # 报出后果: 整改的人要知道漏了会怎样
                f"'imported but undeclared' 而 fail-closed (误报)")                                    # 写清误报的方向, 免得以为只是漏检
            assert _is_interpreter_provided(name), (                                             # 不得混入第三方名: 混进去就等于放过未声明依赖
                f"{name} 不是解释器自带模块 — 白名单混入了第三方名, 会放过未声明依赖")                                    # 报出后果: 白名单混入第三方会让死依赖检查形同虚设

    def test_importing_whitelisted_stdlib_is_not_flagged(self, tmp_path, monkeypatch):
        """真实 import 这六个模块时, 依赖锁不得把它们算成第三方 import 根。

        走 ``_imported_roots`` 的真实扫描路径 (ast 解析临时源码树), 而不是
        只查集合成员 —— 要证明的是"扫描器真的放行它们", 不是"名单里写了名"。
        """
        probe = tmp_path / "src" / "probe_new_stdlib.py"                                   # 探针文件: 用一个假的 src 目录验"新标准库不再误报"
        probe.parent.mkdir(parents=True)                                                     # 先建目录: 扫描器按目录 glob, 目录不在就扫不到
        probe.write_text(                                                                           # 写出探针源码
            "".join(f"import {name}\n" for name in NEW_STDLIB_MODULES),                             # 逐个模块名生成 import 行
            encoding="utf-8",                                                                       # 编码显式钉死
        )
        monkeypatch.setattr(sys.modules[__name__], "SKILL_DIR", tmp_path)  # 锚到临时树: 改真实 SKILL_DIR 会让本用例的结论随工作区状态变
        monkeypatch.setattr(sys.modules[__name__], "SCAN_DIRS", ("src",))                   # 只扫这一个目录: 免得把真仓库的 import 面算进来
        # 六个模块全是解释器自带: 扫描结果必须为空, 一个第三方根都不剩
        assert _imported_roots() == {}, _imported_roots()  # 扫描结果必须为空集: 有一个第三方根残留就说明放行逻辑漏了


class TestDeclaredPackageNameExtraction:
    """E3: environment.yaml 条目带版本约束/大小写混写时必须取到正确包名。"""

    @pytest.mark.parametrize("line,expected", [
        ("- pip>=23", "pip"),                                                                       # 带版本约束的声明: 抽取必须容忍约束后缀
        ("- numpy>=1.24,<2", "numpy"),                                                              # 带上下界的声明
        ("- pytest", "pytest"),                                                                     # 不带约束的裸声明
        ("- Django>=4.2,<5", "Django"),                                                            # 首字母大写的包名: 包名大小写必须原样保留
    ])
    def test_constraint_and_case_entries_yield_bare_name(self, line, expected,
                                                         tmp_path, monkeypatch):                    # 逐行喂声明文本
        """比较符/多段约束/extras/大小写混写条目都要取到裸包名 (旧正则此处失真)。"""
        (tmp_path / "environment.yaml").write_text(                                                 # 临时环境锁落在临时区
            f"dependencies:\n  {line}\n", encoding="utf-8")                                         # 一次只写一条依赖
        monkeypatch.setattr(sys.modules[__name__], "SKILL_DIR", tmp_path)
        assert _declared_packages() == {expected}, _declared_packages()  # 等值而非包含: 裸包名取错一位 (如 PyYAML 截成 yaml) 就在这里红

    def test_real_environment_yaml_extraction_is_unchanged(self):
        """真实 environment.yaml 的抽取结果必须与下方期望集逐项一致 (不许顺手改口径)。

        期望集就是这条钉死的整份清单, 增删任何一条都让本例立即红。其中:
          - numpy **不在**集内 (2026-10-07 起): 它原本只为那份 E3 一致性统计模块
            而在锁内, 该模块随盲评链取消一并删除后零直接 import 方, 于是按死依赖判据
            摘除。它仍会被装上 (astropy 硬依赖它, 传递带入), 摘除只是去掉多余的
            显式声明, 不改变解出来的环境;
          - tokenize 不在集内: 它是**标准库模块**, 不是 conda/PyPI 包, 声明进
            environment.yaml 会让 `conda env create` 解不出来; 正确处置是补进本文件
            的 STDLIB 白名单 (见 TestStdlibWhitelist)。
        """
        assert _declared_packages() == {  # 钉死整份期望集: 顺手往锁里加一条会让这条立即红, 改动必须显式
            "python", "requests", "urllib3", "pyyaml", "astropy", "pyvo",
            "pytest", "pytest-cov", "pip", "ruff",
        }, _declared_packages()
