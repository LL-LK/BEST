# -*- coding: utf-8 -*-
"""repro_all.py — E1 实验全流程复现编排器。

覆盖五步：闸门检查 → 泄题审计 → 四部验收 → 判分 → （可选）重建沙箱。

为什么不直接 subprocess 调 `builder/*.py`:
  那些脚本用 `ROOT = Path(__file__).parent.parent` 锚定沙箱根 —— 副本放进 `_repro/builder/`
  后 ROOT 会算成 `_repro`，指向不存在的 `_repro/sb1`。所以这里用 importlib 载入模块、
  **覆盖模块级 ROOT**（以及 archive_and_reset 的 ARCH），再调它的 main()。原脚本一字未改。

用法:
  python repro_all.py                  # 闸门 + 审计 + 验收 + 判分（不动答案）
  python repro_all.py --rebuild        # 额外重建三箱（先自动备份答案）
  python repro_all.py --skip-verify    # 跳过四部验收（它较慢）
  python repro_all.py --only grade     # 只判分

产物: out/repro_all-<时间戳>.log
"""
from __future__ import annotations

import argparse
import importlib.util
import io
import shutil
import subprocess
import sys
import time
from contextlib import redirect_stdout
from pathlib import Path

HERE = Path(__file__).resolve().parent
SANDBOX = HERE.parent                 # 三箱所在（真实沙箱根）
BUILDER = HERE / "builder"

sys.path.insert(0, str(HERE))
import repro  # noqa: E402  （同目录，判分复现的实现）


# ── 工具 ────────────────────────────────────────────────────────────────────

def load_builder(name: str, **overrides):
    """载入 builder 副本模块并覆盖其模块级路径常量（不修改源文件）。"""
    path = BUILDER / f"{name}.py"
    if not path.is_file():
        raise SystemExit(f"[error] 缺少过程脚本: {path}")
    spec = importlib.util.spec_from_file_location(f"_rb_{name}", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    for k, v in overrides.items():
        if hasattr(mod, k):
            setattr(mod, k, v)
    return mod


def call_main(mod, argv: list[str]) -> int:
    """以给定 argv 调模块的 main()，返回其退出码。"""
    old = sys.argv
    sys.argv = [str(getattr(mod, "__file__", "mod"))] + argv
    try:
        return int(mod.main())
    except SystemExit as exc:
        return int(exc.code or 0)
    finally:
        sys.argv = old


def section(title: str) -> None:
    print("\n" + "═" * 66)
    print(f"  {title}")
    print("═" * 66)


# ── 各步骤 ──────────────────────────────────────────────────────────────────

def step_gate() -> bool:
    """闸门：三箱 progress + verify（脚本在每箱 _lock 内，直接用子进程）。"""
    section("① 闸门检查（progress / verify）")
    ok = True
    for box in ("sb1", "sb2", "sb3"):
        d = SANDBOX / box
        if not (d / "_lock" / "sandbox_lock.py").is_file():
            print(f"{box}: [skip] 无 _lock/sandbox_lock.py")
            continue
        for cmd in ("progress", "verify"):
            r = subprocess.run(
                [sys.executable, "_lock/sandbox_lock.py", cmd],
                cwd=str(d), capture_output=True)
            out = (r.stdout + r.stderr).decode("utf-8", "replace").strip().splitlines()
            line = out[-1] if out else "(无输出)"
            print(f"{box} {cmd:9} → {line}")
            if cmd == "verify" and "PASS" not in line:
                ok = False
    return ok


def step_audit() -> bool | None:
    """泄题审计：拿 tasks.yaml 标注原文当探针去搜沙箱。

    返回 None 表示"有 P0/P1 命中，需人工复核" —— 审计器的中文长探针存在已知撞车
    （标注描述本身就是从 skill 事实推出来的），不能让它直接阻断流程。
    """
    section("② 泄题审计（audit_leak）")
    mod = load_builder("audit_leak", ROOT=SANDBOX)
    rc = call_main(mod, ["--repo", str(HERE)])
    if rc == 0:
        print("  无泄漏 ✅")
        return True
    print("  ⚠ 存在 P0/P1 命中 —— 请人工复核 _验收/泄题审计报告.md")
    print("    （典型假阳性：clarify.options 的客观事实句与 skill 内容撞车）")
    return None


def step_verify() -> bool:
    """四部验收（默认跳过负向测试：它会临时改沙箱文件）。"""
    section("③ 四部验收（verify_all · 已跳过负向测试）")
    mod = load_builder("verify_all", ROOT=SANDBOX)
    rc = call_main(mod, ["--no-negtest"])
    print(f"  退出码 {rc}")
    return rc == 0


def step_grade(combined: bool = True) -> bool:
    """判分：三箱 + 合并。"""
    section("④ 判分（逐箱 + 三次重复）")
    per_box: dict[str, Path] = {}
    for box in ("sb1", "sb2", "sb3"):
        out = HERE / "out" / box
        tr = out / "traces"
        repro.to_traces(box, tr)
        r = repro.grade(tr, out, attempts=1)
        per_box[box] = tr
        dims = {k: round(v, 4) for k, v in r["dims"].items() if v is not None}
        print(f"  {box}: weighted={r['weighted']:.4f}  pass={r['pass']}  red={r['red_line_tasks']}")
        print(f"        {dims}")
    if combined:
        tr = repro.combine(per_box)
        r = repro.grade(tr, HERE / "out" / "combined-out", attempts=3)
        dims = {k: round(v, 4) for k, v in r["dims"].items() if v is not None}
        print(f"  combined: weighted={r['weighted']:.4f}  pass={r['pass']}  red={r['red_line_tasks']}")
        print(f"            {dims}")
        print(f"            unstable={r.get('unstable_tasks')}")
    return True


def step_rebuild() -> bool:
    """重建三箱。**会清空 answers**，所以先备份。"""
    section("⓿ 重建三箱（会清空 answers —— 先备份）")
    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup = HERE / "out" / f"answers-backup-{stamp}"
    n = 0
    for box in ("sb1", "sb2", "sb3"):
        src = SANDBOX / box / "answers"
        if not src.is_dir():
            continue
        dst = backup / box
        dst.mkdir(parents=True, exist_ok=True)
        for p in src.glob("*.md"):
            shutil.copy2(p, dst / p.name)
            n += 1
    print(f"  已备份 {n} 个文件 → {backup}")
    if n == 0:
        print("  [提示] 没有答案可备份（可能是空箱）")

    mod = load_builder("build_sandboxes", ROOT=SANDBOX)
    rc = call_main(mod, ["--repo", str(HERE), "--dest", str(SANDBOX),
                         "--apply", "--force", "--acl"])
    print(f"  退出码 {rc}")
    if rc == 0:
        print("\n  ⚠ 重建会重置 ACL。请重放执行侧读锁：")
        print("    见 README §六，或重新执行建锁清单（_exec / 题卷 per_task+context / 净化日志 / _repro）")
        print(f"  ⚠ 答案备份在 {backup}，确认无误后可删")
    return rc == 0


# ── 主流程 ──────────────────────────────────────────────────────────────────

class Tee:
    """同时写屏与日志文件 —— 复现过程要留档，但别让用户看不到进度。"""

    def __init__(self, *streams):
        self.streams = streams

    def write(self, s: str) -> int:
        for st in self.streams:
            st.write(s)
        return len(s)

    def flush(self) -> None:
        for st in self.streams:
            st.flush()


def main() -> int:
    ap = argparse.ArgumentParser(description="E1 全流程复现")
    ap.add_argument("--rebuild", action="store_true", help="重建三箱（会清空答案，自动备份）")
    ap.add_argument("--skip-verify", action="store_true", help="跳过四部验收")
    ap.add_argument("--skip-audit", action="store_true", help="跳过泄题审计")
    ap.add_argument("--only", choices=["grade"], help="只跑某一步")
    ns = ap.parse_args()

    log_path = HERE / "out" / f"repro_all-{time.strftime('%Y%m%d-%H%M%S')}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    results: dict[str, object] = {}
    t0 = time.time()
    with open(log_path, "w", encoding="utf-8") as log:
        tee = Tee(sys.__stdout__, log)
        with redirect_stdout(tee):
            if ns.only == "grade":
                results["grade"] = step_grade()
            else:
                if ns.rebuild:
                    results["rebuild"] = step_rebuild()
                else:
                    results["gate"] = step_gate()
                if not ns.skip_audit:
                    results["audit"] = step_audit()
                if not ns.skip_verify:
                    results["verify"] = step_verify()
                results["grade"] = step_grade()

            section("汇总")
            for k, v in results.items():
                mark = "✅ 通过" if v is True else ("⚠ 需人工复核" if v is None else "❌ 未通过")
                print(f"  {k:9} {mark}")
            print(f"  耗时 {time.time() - t0:.1f}s")
            print(f"  日志 → {log_path}")

    # None（审计有命中）不算失败 —— 它需要人看报告，不该阻断整条链路
    return 0 if all(v is not False for v in results.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
