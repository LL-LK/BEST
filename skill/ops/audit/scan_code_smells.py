# -*- coding: utf-8 -*-
"""源码异味机械扫描: 同文件重复定义 / 裸 except / except-pass / 遗留待办标记 / 可变默认参数。

职责: 对全仓 .py 做纯语法层的异味体检, 只报不改 —— 发现列表打到 stdout 即止。
  度量对象是 AST 节点与源码行, 不做跨文件推理, 所以"检出"与"确属问题"之间刻意
  留一道人工裁定; 本工具的价值是把重复定义这类肉眼几乎扫不出的形态全量摊开。
所属子系统: 仓库治理层 ops/audit/ 的**报告型**工具, 不接 make audit 的硬门禁
  (退出恒为 0 的隐式行为见下文), 上游无任何代码依赖它, 下游是读 stdout 的人决定
  是否修 —— 与六个硬门禁的分工是: 硬门禁管"必须干净", 本工具管"值得看一眼"。
对外接口: 无导出函数, 模块顶层即扫描 (import 这个文件就会触发全仓遍历), 因此
  只能当脚本运行、不可当库引用; 唯一可依赖的 seam 是 stdout 的行格式
  ``[KIND] 路径:行 说明`` —— 解析时必须容忍首行 ``发现 N 个源码异味:``。
依赖与数据流: 只依赖标准库 ast 做静态解析、os.walk 遍历六个源码目录; 不落盘任何
  产物, 全部结果在 stdout, 因此没有可被下游程序消费的稳定文件接口。
关键契约与不变量: 扫描目录清单不得擅自增删 —— 少一个就会出现"报告显示零异味 =
  没人写坏代码"的假绿, 触犯铁律 5 (禁 fail-open); __pycache__ 必须跳过, 否则编译
  产物里复制出的 .py 会被当源码再扫一遍, 报出并不存在的重复定义。
陷阱与边界: 顶层的 os.chdir(ROOT) 改的是**进程**工作目录, 被 import 会污染调用方,
  这是本文件只能脚本执行的根本原因; 遗留标记检查是裸子串匹配且只看行内有没有
  noqa, 所以连本文件自己的注释里写出那些标记名都会自曝一条, 因此这里一律用
  "遗留标记"指代; 读盘用的 open 未指定 errors, 非 UTF-8 源文件会在读盘阶段抛
  UnicodeDecodeError 而不是被跳过 —— 已知局限, 目前靠各源目录均为 UTF-8 兜住。
"""
# 标准库: AST 静态扫描 (代码异味探针的解析层) / 仓根定位 (Path)
import ast
import os
from pathlib import Path

ROOT = str(Path(__file__).resolve().parents[2])  # 仓根上溯两级; 下一行 chdir 到此, 相对路径扫描才成立
os.chdir(ROOT)  # 改的是**进程**工作目录, 被 import 会污染调用方 —— 只能当脚本跑
issues = []                                                                                         # 问题累积而非首错即退

for base in ("src", "ops", "rag", "evals", "examples", "test"):
    for dirpath, dirs, files in os.walk(base):                                                      # 逐目录遍历
        dirs[:] = [d for d in dirs if d != "__pycache__"]  # 原地改写才剪枝; 否则上轮编译产物旁的 .py 副本会被当源码重扫一遍
        for fn in files:                                                                            # 逐文件
            if not fn.endswith(".py"):
                continue
            p = os.path.join(dirpath, fn)                                                           # 拼绝对路径
            src = open(p, encoding="utf-8").read()
            try:
                tree = ast.parse(src)  # 只做语法层解析, 不跨文件推理 —— 检出到确属问题之间留一道人工裁定
            except SyntaxError as e:
                # 语法错是扫描结果本身 (记录后继续扫其余文件), 不是静默吞掉
                issues.append(f"[PARSE] {p}: {e}")
                continue
            # 1. 同文件顶层重复定义 (函数/类同名)
            seen = {}  # 顶层名 -> 首次定义行号, 重复时用它同时报出首次与再次两处位置
            for node in tree.body:                                                              # 只取模块顶层: 嵌套在函数里的同名定义不算重定义
                name = getattr(node, "name", None)
                if name and isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):  # 有名字且是可挂名的那种
                    if name in seen:                                                                # 重复定义
                        issues.append(                                                              # 记一条
                            f"[DUPDEF] {p}: {type(node).__name__} '{name}' "
                            f"重复定义 (首次行 {seen[name]}, 再次行 {node.lineno})"
                        )
                    else:
                        seen[name] = node.lineno  # 只记首次: 走 else 分支天然幂等, 第三次定义仍指向第一处
            # 2. 裸 except / except-pass
            for node in ast.walk(tree):                                                             # 全树找异常处理
                if isinstance(node, ast.ExceptHandler):                                             # 裸 except 是吞异常的典型形态
                    if node.type is None:                                                          # type 为 None 即裸 except
                        issues.append(f"[BAREEXCEPT] {p}:{node.lineno} 裸 except")
                    # 剔掉纯字符串表达式: 否则带 docstring 的 except 体会被误判成 except-pass,
                    # 而 except 体里放一段说明是本仓的常见写法, 误报会淹没真的裸 except
                    body = [n for n in node.body if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant))]  # 剔掉 docstring 行再判空: 只含说明的 except 才是真空
                    if not body:                                                                    # 剔完为空
                        issues.append(f"[EXCEPTPASS] {p}:{node.lineno} except 体为空 (pass-only)")
            # 3. TODO/FIXME/XXX/HACK 注释
            for i, line in enumerate(src.splitlines(), 1):                                          # 逐行扫
                for marker in ("TODO", "FIXME", "XXX", "HACK"):
                    if marker in line and "noqa" not in line:
                        issues.append(f"[MARKER] {p}:{i} {marker}: {line.strip()[:80]}")
            # 4. 可变默认参数
            for node in ast.walk(tree):                                                             # 全树找函数
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):                       # 只看函数/协程
                    for d in node.args.defaults + node.args.kw_defaults:  # 位置默认与关键字默认一起查, 漏掉 kw_defaults 就漏掉一半场景
                        if isinstance(d, (ast.List, ast.Dict, ast.Set)):                            # 可变默认参数是共享状态陷阱
                            issues.append(f"[MUTDEF] {p}:{node.lineno} {node.name} 可变默认参数")

print(f"发现 {len(issues)} 个源码异味:")                                                                   # 问题总数
for i in issues:                                                                                    # 逐条打印
    print(" -", i)
