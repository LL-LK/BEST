# -*- coding: utf-8 -*-
"""门禁盲区回归: examples/ 导入纯度 (A1-08 的仓级护栏)。

背景: ``examples/`` 里的示例会发真实网络请求。若某个示例没有
``if __name__ == "__main__":`` 守卫, 那么任何一次 ``import examples.*``、
IDE 索引、文档工具扫描都会立刻打真实站点 —— 离线桩只装在 pytest 里, 索引器
可没有, 于是"随便 import 就打站点"绕过了全套离线纪律。

``test/examples/test_examples_run_offline.py`` 的 import 副作用用例按文件枚举,
新增第三个示例时会被漏掉 (枚举清单不会自己长)。本文件改为**按目录扫描**:
``examples/`` 下每个 ``.py`` 都必须有 main 守卫, 新增示例自动进覆盖范围。
"""
from __future__ import annotations

# 标准库: ast 判 main 守卫 (靠文本 grep 会误中 docstring 与注释) / pathlib 定位 examples 目录
import ast
from pathlib import Path

EXAMPLES_DIR = Path(__file__).resolve().parents[3] / "examples"  # examples/ 与 test/ 同级: 由仓根推出


def _example_files() -> list[Path]:
    """列出 examples/ 下的全部 .py (排除缓存目录), 排序保证失败信息次序可复现。"""
    if not EXAMPLES_DIR.is_dir():  # 裁剪克隆时子树可能缺失
        return []
    return sorted(p for p in EXAMPLES_DIR.glob("*.py") if "__pycache__" not in p.parts)


def _has_main_guard(path: Path) -> bool:
    """判该模块体里是否有 ``if __name__ == "__main__":`` 形式的守卫。

    只认 ``==`` 的比较: ``!=``/``in`` 之类不算守卫, 否则守卫名存实亡时这道门
    仍会绿。判定走语法树而非文本匹配 —— 注释与 docstring 里出现的
    ``__main__`` 字样不该算数。比较两侧的形态也不同: 左端是标识符
    ``__name__``, 右端是字符串字面量 ``"__main__"``, 故分别取 ``id`` 与
    ``value`` 来比。
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))  # 语法错误直接抛: 导入时同样会炸
    for node in ast.walk(tree):  # 递归扫: 守卫惯例在模块层, 但不假设它一定在最外层
        if not isinstance(node, ast.If):  # 只看 if 语句
            continue
        test = node.test  # 守卫条件本身
        if not isinstance(test, ast.Compare) or len(test.ops) != 1:  # 形态必须是单比较 (A == B)
            continue
        if not isinstance(test.ops[0], ast.Eq):  # 只认相等: 取反比较不是守卫
            continue
        left, right = test.left, test.comparators[0]  # 比较两侧
        # 一侧取标识符名, 一侧取字面量值; 两侧都可能是任一形态, 故交叉比
        ids = {getattr(side, "id", None) for side in (left, right)}
        values = {getattr(side, "value", None) for side in (left, right)}
        if "__name__" in ids and "__main__" in values:  # 名称 + 字面量都在即命中
            return True
    return False


def test_examples_dir_is_not_empty():
    """examples/ 至少有两个脚本 —— 空目录时下面那条会 vacuous pass, 必须先断掉。"""
    assert len(_example_files()) >= 2, f"examples/ 脚本数异常: {[p.name for p in _example_files()]}"


def test_every_example_has_main_guard():
    """每个示例都必须有 main 守卫, 否则 import 即打真实站点。"""
    offenders = [p.name for p in _example_files() if not _has_main_guard(p)]  # 收集缺守卫的示例名
    assert not offenders, f"这些示例导入即执行 (会打真实站点): {offenders} —— 需要 if __name__ == \"__main__\": 守卫"
