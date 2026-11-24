"""守卫不得 skip: 带模块级 skip 守卫的测试模块, 当前必须导入干净。

要守的形态 (Q8 检测报告 P1-1, 2026-10-05 R5-03 复现): 某个 test 模块在导入被测
符号时写 ``except Exception -> pytest.skip(..., allow_module_level=True)``。这个
守卫本身无害的前提是"导入失败只可能来自环境差异"; 但本仓的真实故障恰好相反 ——
``src/client.py`` 的错误码再导出 (``E_NO_SQLID`` / ``E_INVALID_INPUT``) 随"定义
上收至 protocol"一并漏删, 是一次**生产代码回归**, ImportError 被守卫降级成模块级
skip, 于是该文件 11 个用例**根本不在 pytest 收集集内**: 跑批报"1746 passed /
30 skipped / 全绿", 而真实规模是 1786, 真实未执行数是 40。其中
``test_default_query_path_spends_no_csrf_homepage_request`` 是 P1-7 的回归锚点,
一度无人看守。守卫把生产回归伪装成了环境问题, 这是 fail-open 的教科书形态 (铁律 5)。

本门禁的判据是**运行态**而不是"禁止这个写法": 这套守卫是本仓 31 个测试文件的
统一习语 (统一到逐字相同的一段 try/except), 把它连根拔掉要动 31 个文件, 而
"守卫存在但导入健康"并不损失任何覆盖率 —— 文件照常进收集集。真正要禁的是
**守卫正在生效**那一刻。所以本门禁在干净子进程里把测试面**全部**模块逐个真导入,
任何一个抛异常即红: 守卫一旦触发, ``pytest.skip(allow_module_level=True)`` 会以
``Skipped`` 异常穿出导入过程, 与裸导入失败一样被抓住。全量而不是"只查带守卫的
那几个", 是因为 2026-10-05 补回再导出时, 那个文件的守卫已被删掉 —— 它不在
"带守卫"名单里, 却恰恰是必须被看见的那一个。

为什么不"断言文件里不含 allow_module_level": 那种禁令判据在本仓会同时 (a) 逼人
改 31 个无关文件, (b) 把一份解释"本文件为何不需要模块级守卫"的注释也判红。

判据用 AST 而不是子串: 子串 ``allow_module_level`` 会被注释与 docstring 命中 ——
包括本文件自己那两处"我们讲的是这个模式"的说明, 以及刚被清除守卫的
``test/integration/test_query_chain.py`` 里解释历史的那段注释。AST 只认真调用节点。

所属层次: test/unit/meta 层 (治理门禁面), 与
``test/unit/meta/test_gate_blindspots.py`` 同族 —— 那份守结构盲区, 本份守"测试
用例自己从收集集里消失"这一类盲区。本文件全程离线, 只读源码 + 起一个只做 import
的子进程, 不触网、不改工作区。
"""

from __future__ import annotations

# 标准库: ast 做调用点扫描 (子串判据会被注释/docstring 骗到) / json 在父子进程间传参 /
# pathlib 定位仓库根 / subprocess 起子进程做真实导入 (同进程 import 会污染 pytest 模块缓存)
import ast  # ast 做调用点扫描: 只有语法树分得清"真调用"与"注释里提到"
import json  # json: 模块名清单走 argv 传参, 探针结果走 stdout 传回, 两头都要结构化
import subprocess  # subprocess 起干净子进程做 import: 同进程 import 会被 pytest 的导入缓存短路
import sys  # sys.executable: 子进程必须用同一个解释器, 否则换机器结论就不可比
from pathlib import Path  # 定位仓库根: 扫描目录由它推出, 不依赖 conftest

SKILL_ROOT = Path(__file__).resolve().parents[3]  # 仓库根: 本文件在 test/unit/meta/, 上溯三级即 skill 根
SCAN_DIRS = ("test", "evals")  # 只扫测试面: 生产代码里没有 pytest.skip, 扫它是噪声

# 子进程内执行的导入探针 — 结果以 JSON 打到 stdout, 由父进程判红绿。
# 按 (父目录, 模块名) 逐个导入而不是拼点号全名: test/ 下没有 __init__.py, pytest
# 走的是 "prepend" 模式 (把文件所在目录塞进 sys.path, 按**裸模块名**导入), 探针
# 必须复刻同一机制, 否则报出来的失败全是探针自己的错, 与守卫无关。
IMPORT_PROBE = '''\
import importlib, json, sys
targets = json.loads(sys.argv[1])
failed = []
for parent, stem in targets:
    sys.path.insert(0, parent)
    try:
        importlib.import_module(stem)
    except BaseException as exc:  # 守卫触发时抛的是 Skipped, 不是 ImportError: 两者都要算失败
        failed.append(f"{parent}/{stem}: {type(exc).__name__}: {exc}")
print(json.dumps(failed))
'''


def _has_module_level_skip_guard(source: str, filename: str = "<synthetic>") -> bool:
    """源码里是否存在 ``skip(..., allow_module_level=True)`` 调用。

    判据只认真正的调用节点: 函数名是 ``skip`` 的裸名或属性 (``pytest.skip`` /
    ``_pytest.skip`` / ``skip`` 三种写法都收), 且带一个值为真的 ``allow_module_level``
    关键字。``@pytest.mark.skipif(...)`` 不收 —— 它是逐用例条件跳过, 可见可数,
    与"整份文件静默退出收集集"是两种东西。
    """
    tree = ast.parse(source, filename=filename)  # 解析失败向上抛: 语法错归编译门禁, 这里不降级成"无守卫"
    for node in ast.walk(tree):  # 逐节点找调用: 调用点可以藏在任何层级的 try 里
        if not isinstance(node, ast.Call):  # 非调用节点与本门禁无关
            continue
        func = node.func  # 被调用的表达式: 裸名或属性两种形态
        is_skip = ((isinstance(func, ast.Name) and func.id == "skip")
                   or (isinstance(func, ast.Attribute) and func.attr == "skip"))  # 两种拼写都算守卫
        if not is_skip:  # 不是 skip 调用就跳过这个节点
            continue
        for keyword in node.keywords:  # 逐个关键字判: allow_module_level 必须显式为真
            if keyword.arg == "allow_module_level" and getattr(keyword.value, "value", None) is True:  # 常量 True 才算模块级 skip; 变量传参不在本门禁射程内
                return True  # 命中即止: 一次就够定性
    return False  # 扫完未命中即判否


def _test_files() -> list[Path]:
    """测试面全部 ``test_*.py`` (排除 ``__pycache__``); 排序保证报错次序可复现。"""
    files: list[Path] = []  # 收集清单: 两个目录都要, evals/ 下同样有测试模块
    for name in SCAN_DIRS:  # 逐个扫描目录
        base = SKILL_ROOT / name  # 目录由仓根与目录名拼出
        if not base.is_dir():  # 目录不存在就跳过: 裁剪克隆时子树可能缺失
            continue
        for path in sorted(base.rglob("test_*.py")):  # 排序遍历: 失败信息次序必须跨机可复现
            if "__pycache__" in path.parts:  # 缓存目录不是源码: 里面的副本会造出假阳性
                continue
            files.append(path)  # 收进清单
    return files  # 交给调用方按序扫描


class TestGuardedModulesMustNotBeSkipped:
    """模块级 skip 守卫的运行态禁令 (阻断): 守卫一旦生效即红。"""

    def test_every_test_module_imports_cleanly(self):
        """测试面每个模块都必须导入干净 —— "用例退出收集集"这件事不许绿灯通过。

        判据是**全量模块导入**而不是"只查带守卫的那几个", 因为两种退化必须同时被
        看见, 而它们的可见性不同:
          - 无守卫且导入坏: pytest 自己报收集期 ERROR, 门禁本来就红 (冗余但无害);
          - **有守卫且导入坏**: 守卫把 ERROR 降级成模块级 skip, 文件静默退出
            收集集, 跑批照报全绿 —— 这才是本门禁要抓的那一类, 而它只有"在进程
            外真导入一次"才看得见 (同进程里 pytest 已经导入过, 会被模块缓存短路)。
        守卫触发时 ``pytest.skip(allow_module_level=True)`` 抛的是 ``Skipped`` 而
        不是 ``ImportError``, 所以探针收 ``BaseException``, 两者一视同仁。
        """
        files = _test_files()  # 取全量语料
        assert files, "测试面扫描结果为空 — 门禁本身失效 (SCAN_DIRS 与 test_*.py 命名约定脱节?)"  # 空语料下"全过"是恒真
        targets = [[p.parent.relative_to(SKILL_ROOT).as_posix(), p.stem] for p in files]  # (父目录, 裸模块名) 对: 复刻 pytest 的 prepend 导入
        proc = subprocess.run(  # 子进程里逐个真实导入: 同进程 import 会被 pytest 已导入的模块缓存短路
            [sys.executable, "-c", IMPORT_PROBE, json.dumps(targets)],
            cwd=SKILL_ROOT, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=600)  # 600s 上限: 全量子树一次性导入, 冷启动要留够
        assert proc.returncode == 0, (  # 探针自身崩了就不是"守卫没触发", 不能当合规放过
            f"导入探针自身异常退出 (rc={proc.returncode}): {proc.stderr.strip()[:400]}")
        failed = json.loads(proc.stdout.strip() or "[]")  # 探针输出的是失败清单; 空即全过
        if not failed:  # 全过是本用例的正常态, 无需额外说明
            return
        # 逐条点名并标出成因分类: 有守卫 = 失败被守卫吞掉 (本门禁的主目标);
        # 无守卫 = 裸导入坏, pytest 自己会报 ERROR, 但列出来便于一次看全。
        guarded = {p.stem for p in files if _has_module_level_skip_guard(p.read_text(encoding="utf-8", errors="ignore"), str(p))}  # 静态扫一遍只为诊断用
        detail = "\n  ".join(f"[{'守卫吞掉' if name.rsplit('/', 1)[-1] in guarded else '裸导入坏'}] {item}"  # 按成因分组标注
                             for name, item in (line.split(": ", 1) for line in failed))
        raise AssertionError(  # 判红: 判读指引写进消息, 免得下一个人去调判据
            f"以下测试模块在干净进程里导入失败 ({len(failed)} 个) —— 它们的用例要么已退出 "
            f"pytest 收集集而跑批仍报全绿 (Q8 报告 P1-1 形态), 要么在收集期报错:\n  {detail}\n"
            "  判读: 若成因是生产代码漏导出 (不是环境问题), 修生产代码并删掉那层守卫; "
            "不要为了让它变绿而调这条门禁的判据。"
        )

    def test_detector_sees_the_guard_shape_it_watches(self):
        """检测器自证: 阳性对照必判 True, 两组阴性对照必判 False。

        这条是本门禁的诊断层防空转闸。静态守卫扫描用于给失败消息分类成因, 扫描一旦
        失灵 (例如把关键字判据写成只看属性调用, 漏掉裸名与别名两种形态) 就会安静
        扫出空集, 于是"守卫吞掉"这顶帽子永远戴不上, 而本门禁自己的判据 (导入探针)
        仍然是好的 —— 于是分类信息静默失真。故必须证明判据仍能看见它盯着的东西。
        """
        positive = '''\
try:
    from src.client import E_NO_SQLID, BestClient
except Exception as err:
    import pytest as _pytest
    _pytest.skip(f"legacy import unavailable: {err!r}", allow_module_level=True)
'''  # 阳性对照: 取自 2026-10-05 被清除前的原文形态 (含别名 import, 验证不漏 _pytest.skip)
        assert _has_module_level_skip_guard(positive), (  # 阳性必须判 True
            "检测器对已知的模块级 skip 守卫判否 — 守卫分类已失效, 判据被改坏了")
        assert not _has_module_level_skip_guard("import pytest\n\npytest.skip('无凭证', allow_module_level=False)\n"), (  # 显式 False 不是模块级 skip
            "检测器把 allow_module_level=False 判成模块级 skip — 判据过宽会误伤合法的条件跳过")
        assert not _has_module_level_skip_guard("# 这里只是注释里提到了 allow_module_module\n"), (  # 注释不是调用
            "检测器被注释文本触发 — 说明判据退化成了子串匹配")

