# -*- coding: utf-8 -*-
"""import 图机械核实: src/rag/evals 各模块的导入与 from-import 目标存在性检查。

**覆盖范围刻意不含 `ops/`**: README 把 ops/ 定义为「运维入口层 (路径调用, 零 import)」。
其中的 skill_cli.py 与 cloud_modelscope/run.py 是 runpy 转发 shim (模块级
``runpy.run_path(..., run_name="__main__")``), ops/audit/*.py 是路径调用的测量脚本
(模块级直接扫描并打印) —— 对它们做 import 检查等于**执行**这些入口本身:
实测会让体检脚本打印 CLI 用法并 SystemExit(0), 后面的检查全部不再执行。

另做一条轻量 AST 分层判据: 可导入层 (src/rag/evals) 不得反向 import ops 层。
"""
# 标准库: AST 依赖图 (导入关系统计的解析层) / 仓根定位 (Path)
import ast
import importlib
import os
import sys
from pathlib import Path

# 仓根 = 本文件上溯两级 (ops/audit/x.py -> ops/audit -> ops -> 仓根)
ROOT = str(Path(__file__).resolve().parents[2])  # 独立 git root: 上溯两级到 astro-best, 不是父仓
os.chdir(ROOT)                                   # 两遍遍历全按仓根相对路径发起, cwd 必须是根
sys.path.insert(0, ROOT)                         # 让 src.* 可导入, 第二遍要真导入目标模块查名字

# 可导入层: 包形态, 模块级无副作用, 可安全 import
IMPORTABLE_BASES = ("src", "rag", "evals")                                                # 可导入层: 包形态、模块级无副作用, 才允许真 import
# 路径调用层: 只由 `python ops/xxx.py` 调用, 禁止被 import (见模块 docstring)
PATH_INVOKED_TOP = "ops"                         # 分层判据的阈值: 从可导入层里抓反向依赖

problems = []                                    # 累积而非首错即退: 一轮跑批要报全量


def check_module(fullname):
    """导入模块并检查其全部 from-import 目标存在。"""
    try:
        importlib.import_module(fullname)  # noqa: F841 — 导入本身即检查 (副作用: 环现形)
    except Exception as e:
        problems.append(f"[IMPORT] {fullname}: {type(e).__name__}: {e}")


def target_exists(fullname):
    """导入目标模块判定存在性 (导入失败记问题并返回 False)。"""
    try:
        importlib.import_module(fullname)                                                        # 真导入: 导入失败本身就是「目标不存在」的证据
        return True                               # 导得进就算存在: 本门禁不深查模块内部
    except Exception as e:                          # 宽收: 模块自身抛的异常同样算"目标不可用"
        problems.append(f"[ASTIMPORT] {fullname}: {type(e).__name__}: {e}")
        return False                                # 记完问题才返回, 调用方 if not 即可


# 第一遍: 可导入层每个模块自身必须可导入
for base in IMPORTABLE_BASES:                                                                    # 第一遍: 给每个可导入层注入 sys.path
    # 兄弟裸导入契约 (SA-P3-7, 见 evals/eval_runner.py 模块 docstring): evals/ 内模块
    # 以裸模块名互相引用 (import paths / from probe_support import ...), 只在"脚本方式
    # 调用"下成立, 且该约定被明确要求**保持不变**。体检必须复现这一调用方式, 否则会把
    # 一份有文档的约定误报成 4 个导入失败。
    base_dir = os.path.join(ROOT, base)                                                             # 目录锚点
    if base_dir not in sys.path:                                                              # 已注入就不重复: 重复注入会让同一模块出现两份类对象
        sys.path.insert(0, base_dir)                                                                # 插在首位
    for dirpath, dirs, files in os.walk(base):                                                      # 遍历该层
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for fn in files:                                                                            # 只看 .py
            if not fn.endswith(".py"):
                continue
            rel = os.path.join(dirpath, fn)[:-3].replace(os.sep, ".")  # 文件路径 -> 点分模块名, 交给 importlib 用
            if rel.endswith(".__init__"):
                rel = rel[: -len(".__init__")]       # __init__.py 对应包名本身, 去掉尾缀才可导入
            check_module(rel)                                                                       # 逐模块检查

# 第二遍: AST 级 from-import 目标存在性 (比 import 更严: 导入成功不代表名字存在)
checked = 0                                         # 走到属性检查的 from-import 组数, 0 即第二遍空转
for base in IMPORTABLE_BASES:                                                                    # 第二遍: 静态扫 from-import 目标
    for dirpath, dirs, files in os.walk(base):                                                      # 逐层遍历
        dirs[:] = [d for d in dirs if d != "__pycache__"]  # 就地裁剪即剪枝, 缓存目录不进遍历
        for fn in files:                                                                            # 只看 .py
            if not fn.endswith(".py"):
                continue
            p = os.path.join(dirpath, fn)                                                           # 拼绝对路径
            try:
                tree = ast.parse(open(p, encoding="utf-8").read())  # 静态读, 不执行被检模块
            except (OSError, SyntaxError) as e:
                problems.append(f"[PARSE] {p}: {e}")  # 单个坏文件只记问题, 不中断整轮体检
                continue
            for node in ast.walk(tree):                                                             # 全树找 from-import
                if not isinstance(node, ast.ImportFrom) or not node.module:  # 只认有 module 的 from-import (裸 from . import x 的 module 为 None)
                    continue
                head = node.module.split(".")[0]      # 只取顶层包: 分层判据只关心有没有碰到 ops
                if head == PATH_INVOKED_TOP:                                                 # 反向依赖判据: 可导入层不得 import 运维入口层
                    # 分层判据: 可导入层反向依赖路径调用层 = 架构违规
                    problems.append(f"[LAYER] {p}: 可导入层反向 import ops 层 ({node.module})")
                    continue
                if head not in IMPORTABLE_BASES:                                                    # 头不在可导入层内即放行
                    continue                          # 标准库与三方包不归本门禁管
                if not target_exists(node.module):                                                  # 目标必须可导入
                    problems.append(f"[FROM] {p}: 模块 {node.module} 不可导入")
                    continue                          # 导不进就不用再看属性
                m = importlib.import_module(node.module)  # 已确认可导入, 取模块对象查名字
                for alias in node.names:                                                            # 逐个名字
                    if alias.name == "*":
                        continue                      # 星号导入无法静态判定, 显式跳过而不是猜
                    try:
                        getattr(m, alias.name)                                                      # 真取属性: 属性不存在才算断链
                    except AttributeError:
                        problems.append(                                                            # 记一条问题
                            f"[SYMBOL] {p}: {node.module}.{alias.name} 不存在"
                        )
                checked += 1                                                                        # 已核实的组数

print(f"from-import 组核实: {checked}")                                                               # 先报核实量: 零问题也可能是「一个都没查」
print(f"发现 {len(problems)} 个 import 图问题:")                                                          # 问题总数
for i in problems:                                                                                  # 逐条打印
    print(" -", i)                                   # 逐条不截断: 门禁红时要能直接定位
# 退出码: 有问题即非零, 供门禁接线 (恒返回 0 的工具无法作为门禁使用)
raise SystemExit(1 if problems else 0)
