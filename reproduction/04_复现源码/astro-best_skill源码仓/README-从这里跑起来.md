# 可运行镜像（原仓相对路径）

本目录按**仓库原始相对路径**铺开 —— 脚本内部大量用 `Path(__file__).resolve().parents[N]` 定位仓库根，
顶层那些按主题重排过的目录只是**阅读视图**，直接跑会因路径解析失败。
**要复现请进入本目录执行。**

## 环境

```bash
pip install pyyaml requests
```

## E1（金标准自证）

```bash
python evals/nl2tool/gen_golden.py
python -m evals.nl2tool.runner --traces evals/nl2tool/traces/golden \
    --require-threshold --primers evals/nl2tool/context_primers.yaml \
    --json temp/nl2tool/report.json --md-out evals/nl2tool/REPORT.md
```

## E4

```bash
python -m evals.robustness.runner --tier all --md \
    --answers temp/robustness/answers/r1 --require-execution
python evals/robustness/check_disposal_scope.py    # 越界即 exit 1
```

> ⚠️ `evals/` 没有 `__init__.py`，请用 `python -m ...` 或 `PYTHONPATH=.`，
> 不要直接 `python evals/robustness/runner.py`（E1 走 importlib 桩，两者都可）。
