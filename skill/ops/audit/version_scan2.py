"""version_scan2.py — 版本号复扫 (A 类明确违规 / B 类裁定保留), 只读不写。

A 类模式: Master Plan v8.0 / pybest-0.3.2.8 / v1.0.0 / 版本: vX.Y.Z
B 类白名单: IVOA 命名空间版本 / 星表 DR 编号 / DOI/arXiv / 协议标准名 / CHANGELOG

职责: 版本号铁律的**第二口径**, 与 version_scan.py 互为交叉验证 —— 两者正则表
  不同、扫描根也不同 (本脚本从仓根整树扫), 所以任一漏掉的形态通常会被另一方补上。
  职责边界严格限于"发现并分类", 命中即报不改。度量对象是文本行与两组正则。
所属子系统: 仓库治理层 ops/audit/ 的**报告型**工具 (make audit 非阻断)。上游无
  代码依赖; 下游是人工裁定与铁律 1 的执行现场。它与 version_scan.py 唯一的
  结构性差别是"不设 SCAN_DIRS 白名单" (扩展名白名单两边都有, 本脚本内联在遍历处
  而非抽成 SCAN_EXTS 常量), 覆盖面更大、噪声也更多。
对外接口: main() -> None (无返回值、无退出码语义 —— 调用方只能读 stdout)。
  A_PATTERNS / B_PATTERNS / SKIP_DIRS / SKIP_FILES 是可依赖的 seam, 改它们等于
  同时改"扫什么"和"算什么"。
依赖与数据流: 输入 = 仓根整棵树的文本文件, 读盘用 errors="replace" 容错;
  不读 git、不落盘、不产出 JSON, 结果只在 stdout 两段清单。
关键契约与不变量: A/B 两类必须同一次扫描完成 —— 若先判 A 再判 B 并提前跳出,
  一行同时命中两类时只会报其中一类, 分类信息就丢了; 因此内层两个 for 都不
  break/continue, 允许一行进两类清单。B 类的存在意义是"这些数字不是发布版本号",
  删掉 B 类会让 IVOA 协议标准与文献编号被当成违规, 误报率会淹没真违规。
陷阱与边界: 开头那行 sys.stdout 重包是 Windows 控制台默认 GBK 导致的乱码补丁,
  代价是它会**持有**原 stdout 缓冲, 所以本文件不能再被当库反复 import/执行;
  跳过 temp 与 .git 靠的是目录名黑名单, 谁在仓根新建一个顶层临时目录就会漏扫;
  B 类清单按 (文件, 标签) 去重后才打印, 因为同一个 DOI/协议名会在全文里出现
  几十次, 全打出来没有信息量 —— 但 A 类**不去重**, 一处版本号就是一处待改。
"""
from __future__ import annotations

# 标准库: 正则扫描 (版本号铁律的第二口径) / 路径 (skill 根相对定位)
import io
import os
import re
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")  # 强制 UTF-8 输出: 控制台默认编码在中文 Windows 上会把结果打成乱码, 门禁输出必须可读

# skill 根定位: 本文件位于 ops/audit/, 上溯两级即仓库根 (相对定位, 换机可跑)
ROOT = str(Path(__file__).resolve().parents[2])                                       # 仓根: parents[2] = 从 ops/audit/ 上跳两级
SKIP_DIRS = {"__pycache__", ".git", ".pytest_cache", ".ruff_cache", ".checkpoints",
             ".progress", ".logs", "best_data", ".workbuddy-ai", "temp"}
SKIP_FILES = {"CHANGELOG.md"}                                                                       # 豁免文件: 变更历史是规则明确允许的载体

A_PATTERNS = [                                                                                      # A 类模式表 (需人工判定是否违规)
    (re.compile(r"Master Plan\s+v\d+(\.\d+)*"), "Master Plan 版本号"),
    (re.compile(r"pybest-0\.\d+(\.\d+)*"), "pybest 版本号字面量"),
    (re.compile(r"package-stage-0\.\d+(\.\d+)*"), "打包阶段版本号"),
    # 两侧否定环视缺一不可: 只加左侧会把 2.0 里的点当小数切, 只加右侧会把
    # "0.3.2.8" 的第三段切出来报成发布版本, 而它其实是打包产物名
    (re.compile(r"(?<![\w.])v\d+\.\d+(\.\d+)+(?![\w.])"), "营销版本号 vX.Y.Z"),
    (re.compile(r"版本[:：]\s*v?\d+\.\d+"), "版本字段"),
    (re.compile(r"schema_version\s*[:=]\s*[\"']?\d"), "schema_version 标记"),
]
# B 类: 这些不是本 skill 的发布版本, 删了会破坏协议/文献/指表
B_PATTERNS = [                                                                                     # B 类模式表 (历史锚点, 单列由人决定)
    (re.compile(r"(VOTable|UWS|VOSI|VODataService|TAP)\s*v?\d+(\.\d+)*"), "IVOA 协议标准版本"),
    (re.compile(r"ADQL\s*\d+(\.\d+)*"), "ADQL 标准版本"),
    # \b 边界很重要: 否则 DR 编号正则会连 "DRAGONS" 这类词里的 DR 也咬住
    (re.compile(r"\bDR\d+\b"), "巡天数据发行编号"),
    (re.compile(r"10\.\d{4,}/"), "DOI"),
    (re.compile(r"arXiv[:：\s]*\d{4}\.\d{4,}"), "arXiv 号"),
    (re.compile(r"OAuth2\.0|JSON-RPC\s*2\.0|skills-spec-local-v1"), "协议/schema 标识符"),
]


def main() -> None:
    """主入口: 扫描并分类报告版本号字样。

    作用: 从仓根整树 walk, 对每个文本文件逐行同时套 A_PATTERNS 与 B_PATTERNS,
    命中分装两个列表; 打印时 A 类全量、B 类按 (文件, 标签) 去重。
    关键输入: 全部来自模块级常量 (SKIP_DIRS/SKIP_FILES 与两组正则), 无形参。
    返回: 无 (脚本以 main() 收尾, 不设退出码语义)。抛什么: 读盘 OSError 在
    循环内跳过, 其余不主动抛 —— 它是报告型工具, 崩掉就没有报告了。
    """
    a_hits, b_hits = [], []                                                                         # 两类命中各自收集
    checked = 0                                                                                     # 已检查文件数
    # 从仓根整树扫 (不是 SCAN_DIRS 白名单): 本脚本刻意做全量覆盖, 与
    # version_scan.py 的白名单口径互补, 两者的差集就是需要人看的地带
    for dirpath, dirnames, filenames in os.walk(ROOT):                                     # 从仓根整树遍历 (本工具刻意不设目录白名单, 覆盖面更大)
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]  # 原地剪枝: .git 与缓存/临时目录里全是数字串与依赖名
        for name in filenames:                                                                      # 逐文件
            # 扩展名过滤是唯一的"跳过文件"入口, 故把 CHANGELOG 显式列进来
            if name in SKIP_FILES or not name.endswith((".py", ".md", ".yaml", ".yml", ".txt", ".json", ".toml")):
                continue
            full = os.path.join(dirpath, name)                                                      # 拼绝对路径
            rel = os.path.relpath(full, ROOT).replace(os.sep, "/")  # 正斜杠: 与 README 树清单、门禁报告的路径写法一致
            try:
                with io.open(full, encoding="utf-8", errors="replace") as fh:  # errors=replace 容错全树非 UTF-8; 代价是这类文件不可信
                    text = fh.read()                                                                # 一次读入
            except OSError:
                # 权限/竞态导致的读不到一律跳过, 不猜内容
                continue
            checked += 1  # 只数真正读成功的: 读盘失败算未检查, 不等于已检查且干净
            for _lineno, line in enumerate(text.splitlines(), start=1):                             # 逐行扫
                # A 类不使用 break: 一行里可能同时藏着"打包名 + 营销号", 都要报
                for pat, label in A_PATTERNS:                                                       # A 类逐模式
                    if pat.search(line):                                                            # 命中
                        a_hits.append((rel, _lineno, label, line.strip()[:110]))  # A 类不去重: 一处版本号就是一处待改, 少一条即漏改
                # B 类同样不 break: 分类信息要全, 去重留到打印阶段做
                for pat, label in B_PATTERNS:                                                       # B 类逐模式
                    if pat.search(line):                                                            # 命中
                        b_hits.append((rel, _lineno, label, line.strip()[:90]))  # B 类此处也不去重, 统一留到打印阶段按 (文件, 标签) 收敛
    print("checked=%d" % checked)  # 先打分母: 没有 checked 就无法判断后面的 A/B 计数是否扫全了
    # A 类全量打印: 每一处都是一个待改点, 少一条就漏改
    print("A 类 (明确违规) = %d" % len(a_hits))
    for rel, _lineno, label, text in a_hits:                                                        # A 类逐条打印
        print("   %s:%d  [%s]  %s" % (rel, _lineno, label, text))
    print("B 类 (裁定保留) = %d" % len(b_hits))
    # B 类按 (文件, 标签) 去重: 同一个 DOI 在全文出现几十次, 打印全量无信息量;
    # 注意计数行报的是**去重前**的条数, 与下面实际打印的行数不等, 这是刻意的
    seen = set()  # 去重键 = (文件, 标签): 同一 DOI 全文出现几十次, 全打没有信息量
    for rel, _lineno, label, text in b_hits:                                                        # B 类逐条打印
        key = (rel, label)                                                                          # 去重键: 同一文件的同一标签只报一次
        if key in seen:                                                                             # 已报过
            continue
        seen.add(key)  # 只在真要打印前登记, 保证 seen 与实际输出行数一一对应
        print("   %-46s [%s]  %s" % (rel, label, text[:70]))


if __name__ == "__main__":
    main()                                                                                          # 入口
