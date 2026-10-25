# -*- coding: utf-8 -*-
r"""ops.audit.verify_eval_report_assets — 跑批报告资产门禁 (N9)。

**它守的失效形态 (2026-10-07, ACTION-BACKLOG N9)**: ``make evals-all`` 每跑一次就
覆盖刷新 ``evals/{nl2tool,semantics,ablation}/REPORT.md``, 其中「生成时间」逐次不同。
于是跑批结束必然留下三个 dirty 的**被跟踪**文件, 而现有三道门各管一段, 没有一道
覆盖这个面:

  - ``code_fingerprint``      —— 只扫 .py (实测 compared=321), .md 不在扫描面
  - ``verify_tree_integrity`` —— 只比**结构清单**, 不比文件内容
  - ``TestGitTrackingCoverage``—— 只管**未跟踪**文件, 管不到"已跟踪但被改写"

**为什么这在实践上是危险而不只是脏**: 只变时间戳无所谓; 但 REPORT.md 里若出现
**实质**回归 (某个指标掉了、某个 blocker 消失), 同样没人响 —— 门禁显示全绿,
而入库的那份报告已经不再描述当前代码的行为。

**本门禁的判据 (快、通用、不重跑评测)**: 门禁跑在**干净树**上, 所以
「入库的 REPORT.md 与 HEAD 不一致」这一条就够判红 —— 它精确对应"有人跑过评测、
结果还留在工作区没提交"。人看到之后只需 ``git diff`` 一眼分辨是时间戳还是实质回归。

刻意**不**在本门禁里重跑评测去比对内容: E3/E5/E6 都需要凭据或 live 采集 (按裁定
D5 长期红), 把它们塞进门禁会让 `make audit` 变成一条要联网、要凭据的线, 反而不可用。

============================  ====================================================
边界
============================  ====================================================
- 只看 ``evals/**/REPORT.md`` 这类**被跟踪的报告资产**; 其它 .md 不在范围内
  (文档改动是正常的, 这里要抓的是"跑批产物与入库版本不一致")。
- **只报不改**: 命中即红并列出文件, 门禁自己绝不 ``git checkout`` —— 擦掉现场
  等于毁掉证据。
- 扫描面为空 (仓里一个 REPORT.md 都没有) 时**判红**, 不静默通过: 零输入的绿灯
  只蕴含"没有触发任何条件"。这条与本仓其余八道门的负对照闸同一纪律。

对外接口: :func:`scan` (root) -> 违规清单; :func:`main` (argv) -> 退出码。
``root`` 显式参数化: 判据级红测试要在临时目录里注入脏文件后实跑, 否则
"它能不能抓住自己该抓的东西"永远没人知道。
"""
from __future__ import annotations

# 标准库: argparse / os / subprocess / sys / 路径
import argparse
import os
import subprocess
import sys
from pathlib import Path


# 本地: 判红理由必须直写 UTF-8 字节 (中文 Windows 控制台会把文字转成替换字符,
# 门禁"红了但没人知道红在哪"正是本门禁要消灭的状态, 自己不能先犯)
def _emit(text: str) -> None:
    """把一行门禁输出直写 stderr 的字节通道, 编码与 locale 无关。

    Args:
        text: 要写出的整行文字 (含换行)。

    Returns:
        无。拿不到字节通道时退回文本流 —— 编码随环境, 但绝不因此崩。
    """
    buffer = getattr(sys.stderr, "buffer", None)  # 真解释器下是 BufferedWriter; 替身下可能是 None
    if buffer is None:
        print(text, end="", file=sys.stderr)  # 兜底: 拿不到字节通道仍要把话说出来
        return
    buffer.write(text.encode("utf-8", errors="replace"))  # replace: 宁可损一个字也不让理由丢失
    buffer.flush()  # 立即刷: 门禁随后就要以非零码退出


# 报告资产的**发现**规则: 仓内所有被 git 跟踪的 evals/**/REPORT.md。
# 刻意用 git 而不是 glob: glob 会把未跟踪的新报告也算进来, 而"未跟踪"归
# TestGitTrackingCoverage 管 —— 两道门各管一段, 边界才不重叠。
def _tracked_reports(root: Path) -> list[str]:
    """列出 git 跟踪的 ``evals/**/REPORT.md`` (相对路径, 排序)。

    Args:
        root: 仓根。

    Returns:
        相对路径清单; 取不到 git 清单时返回空列表 (由调用方按零扫描面判红)。
    """
    proc = subprocess.run(  # noqa: S603 - argv 全是本仓常量, 无 shell
        ["git", "-C", str(root), "ls-files", "--", "evals"],  # ls-files 只列**已跟踪**的
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"},
    )
    if proc.returncode != 0:  # 不是 git 仓 / git 不可用: 交由零扫描面闸判红, 不猜
        return []
    return sorted(p for p in proc.stdout.splitlines()  # 只收报告资产: 文档改动不算
                  if p.strip().endswith("REPORT.md"))


def scan(root: Path) -> list[str]:
    """找出「入库报告资产在 HEAD 之外还有改动」的文件清单。

    Args:
        root: 仓根。

    Returns:
        违规文件相对路径; 空列表 = 全绿。
    """
    tracked = _tracked_reports(root)
    if not tracked:  # 负对照: 零扫描面必须判红, 否则"一个都没看"会被读成"都干净"
        return ["__no_tracked_report_assets__"]
    proc = subprocess.run(  # noqa: S603 - argv 全是本仓常量, 无 shell
        ["git", "-C", str(root), "diff", "--name-only", "HEAD", "--"] + tracked,
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"},
    )
    if proc.returncode != 0:
        return ["__git_diff_failed__"]
    return sorted(p for p in proc.stdout.splitlines() if p.strip())


def main(argv: list[str] | None = None) -> int:
    """门禁入口: 有未提交的报告资产改动即判红。"""
    parser = argparse.ArgumentParser(description="跑批报告资产一致性门禁 (N9)")
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[2]),
                        help="仓根 (默认按本文件位置上溯两级)")
    args = parser.parse_args(argv)
    findings = scan(Path(args.root))

    if findings == ["__no_tracked_report_assets__"]:
        _emit("[verify_eval_report_assets] 扫描面为空: 仓内一个被跟踪的 evals/**/REPORT.md "
              "都没有 —— 判红。零输入的绿灯只蕴含「没有触发任何条件」。\n")
        return 1
    if findings == ["__git_diff_failed__"]:
        _emit("[verify_eval_report_assets] 取不到 git diff —— 判红 (无法确认报告资产是否与 HEAD 一致)。\n")
        return 1
    if findings:
        _emit(f"[verify_eval_report_assets] {len(findings)} 个入库报告资产与 HEAD 不一致 —— 判红 (N9):\n")
        for path in findings:
            _emit(f"  - {path}\n")
        _emit("  多半是跑过 `make evals-all` 但没提交。请 `git diff` 一眼分辨:\n"
              "    只变「生成时间」一行 ⇒ 无实质变化, 直接提交或还原均可;\n"
              "    指标/blocker 有变 ⇒ 那是**实质回归**, 必须查明来源再提交, 不要直接带过。\n"
              "  门禁只报不改: 擦掉现场等于毁掉证据。\n")
        return 1
    _emit("[verify_eval_report_assets] 全部入库报告资产与 HEAD 一致 —— 通过 (N9)。\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
