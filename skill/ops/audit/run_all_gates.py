# -*- coding: utf-8 -*-
"""ops.audit.run_all_gates — 硬门禁的**跑完再汇总**入口 (``make audit`` 的实现)。

为什么不再用 Makefile 的多行 recipe: GNU make 每条 recipe 行是独立 shell, 且默认
**fail-fast** —— 第一道判红就停, 后面几道根本不执行。实测事故 (2026-10-07):
扫描面被清空时 ``verify_crossrefs`` 排在第 5 位并判红, 于是**它后面的 4 道门禁
从不登场**, 其中包括铁律 1 的唯一执行者 ``verify_no_version_keys`` ——
「最该拦住违规的那道门, 在最需要它的场景下从不执行」。而且那道门偏偏又是零输入时
唯一会打印「**铁律 1 通过**」的, 即**误导性最强的一道恰好最容易不执行**。

本模块把执行与汇总拆开: 全部**跑完**, 逐道记录退出码, 末尾一次性报汇总并给出
合并退出码。代价是总耗时变长 (最慢的 ``verify_import_graph`` 约 40 秒), 换来的是
「一次运行看到全部的结果」—— 而这正是 fail-fast 模式下拿不到的。

判定契约 (与既有文档口径一致, 不得在本模块内另立一套):
  - **硬门禁**: 全部须 exit 0, 任一非零即整体非零。
  - **报告型**工具 (``verify_no_code_loss`` / ``scan_code_smells`` / ``version_scan*`` /
    ``check_line_endings``) 刻意**不**进本入口: 它们的结论需要人判读, 强行阻断会误伤
    正常重构 (如合法清理重复定义会被 ``verify_no_code_loss`` 报成 token 减少)。

对外接口: ``main(argv)`` 返回合并退出码 (0 = 全部通过), 可直接 ``python`` 直跑,
也可被测试 import 后调用。不依赖 ``make`` —— 本机未装 make, 而 ``CLAUDE.md`` 把
``make audit`` 写成门禁命令, 因此逐条执行的等价入口必须是纯 python 的。
"""
from __future__ import annotations

# 标准库: 子进程执行门禁 / 计时 / 退出码聚合
import subprocess  # noqa: S404  固定 argv、无 shell, 不涉用户输入
import sys  # noqa: S404
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # 仓根上溯两级: 与各门禁自身的定位口径一致
AUDIT_DIR = Path(__file__).resolve().parent  # 门禁脚本目录 (本模块与它们同目录)

# 硬门禁清单, 顺序与 Makefile 历史上的一致 (便于逐次运行结果对账)。
# 刻意写成数据而非从 Makefile 解析: 本模块**就是** Makefile audit 的实现, 反过来去读
# 被自己取代的配方会形成循环, 且解析失败时无法判断是"门禁缺失"还是"解析口径坏了"。
HARD_GATES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("count_code_lines", ("count_code_lines.py",)),
    ("comment_audit", ("comment_audit.py",)),
    ("code_fingerprint", ("code_fingerprint.py", "check")),  # 子命令 check 才是判定面
    ("verify_import_graph", ("verify_import_graph.py",)),
    ("verify_crossrefs", ("verify_crossrefs.py",)),
    ("verify_doc_consistency", ("verify_doc_consistency.py",)),
    ("verify_no_version_keys", ("verify_no_version_keys.py",)),
    ("verify_evidence_anchors", ("verify_evidence_anchors.py",)),
    ("verify_counting_claims", ("verify_counting_claims.py",)),
    # 第 10 道 (2026-10-07, N9): 跑批报告资产与 HEAD 是否一致。三道老门各管一段、
    # 都没覆盖这个面 —— code_fingerprint 只扫 .py, verify_tree_integrity 只比结构清单,
    # TestGitTrackingCoverage 只管未跟踪文件。实测放它最后: 它最便宜, 且它红了不影响
    # 前面几道已经给出的诊断。
    ("verify_eval_report_assets", ("verify_eval_report_assets.py",)),
    # 第 11 道 (2026-10-07, N10): 实测登记表自洽性与排序列真源不冲突。原来那份
    # "实测过整列为空的列" 只活在测试的一个字面量集合里, 且两条都被实跑证伪
    # (ps1_source_id 空值率位置相关; uss_dr1_ra_u 在回包表头里根本不存在)。
    # 事实移到 contracts/measurements/ 由本门禁核, 覆盖面缺口只披露不判红。
    ("verify_measurement_registry", ("verify_measurement_registry.py",)),
    # 第 12 道 (2026-10-08, N11): 归档 zip 的**独立**隐私复验。
    #
    # 为什么必须在清单之外再有一道: 清单 (MANIFEST-*.md) 是文本, 抽它的那套脱敏规则
    # 与判它的那套判据同源 —— 同错时一片绿。实测就是这个形状: 打包器自带复验报
    # 「残留 0」而包里真有 4468 处命中 (见 verify_archive_privacy 的 docstring)。
    # 本门禁**不从打包器 import 任何符号**, 判据独立重写且刻意比抹除规则**宽**。
    #
    # 排在最后: 它最慢 (要逐条目解包扫描), 且红了不影响前面已给出的诊断。
    ("verify_archive_privacy", ("verify_archive_privacy.py",)),
)


def run_one(gate: str, args: tuple[str, ...]) -> tuple[int, float]:
    """跑一道门禁, 返回 (退出码, 耗时秒)。

    不捕获 stdout: 各门禁的报告要原样透给人看 (门禁红时能直接定位到那一行是它的
    职责)。只拦退出码与计时。

    Args:
        gate: 门禁名 (用于报错时指名)。
        args: 传给该门禁的参数元组。

    Returns:
        ``(returncode, elapsed_seconds)``。
    """
    started = time.monotonic()  # 计时: 汇总表要给出耗时, 慢门禁的定位价值最高
    result = subprocess.run(  # noqa: S603  argv 全由本模块常量拼出, 无外部输入
        [sys.executable, str(AUDIT_DIR / args[0]), *args[1:]],
        cwd=str(ROOT),
        check=False,
    )
    return result.returncode, time.monotonic() - started


def main() -> int:
    """逐道跑完全部硬门禁, 打印汇总, 返回合并退出码。

    返回:
        0 = 全部通过; 1 = 至少一道非零。**任一道失败都不会阻止其余道继续跑完** ——
        这正是本模块存在的理由 (见模块 docstring 的 fail-fast 事故记录)。
    """
    results: list[tuple[str, int, float]] = []  # (门禁名, 退出码, 耗时)
    for gate, args in HARD_GATES:
        print(f"\n===== [{gate}] 开始 =====", flush=True)  # flush: 输出会穿过子进程, 不刷新会乱序
        code, elapsed = run_one(gate, args)
        results.append((gate, code, elapsed))
        print(f"===== [{gate}] 退出码 {code} (耗时 {elapsed:.1f}s) =====", flush=True)
    failed = [(gate, code) for gate, code, _ in results if code != 0]
    print("\n" + "=" * 64)  # 分隔线: 汇总段与逐道输出视觉分开, 便于滚动回看
    print("=== 硬门禁汇总 (全部跑完再判定, 非 fail-fast) ===")
    for gate, code, elapsed in results:
        mark = "PASS" if code == 0 else f"FAIL({code})"  # 非零一律标出具体码: 便于区分 1 与 2
        print(f"  {mark:<10} {gate:<26} {elapsed:6.1f}s")
    print("=" * 64)
    if failed:
        print(f"结论: {len(failed)}/{len(results)} 道判红 -> {[g for g, _ in failed]}")
        return 1
    print(f"结论: 全部通过 ({len(results)}/{len(results)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
