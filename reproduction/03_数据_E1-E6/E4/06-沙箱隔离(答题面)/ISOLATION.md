# E4 答题沙箱（answer_box）

> 生成件，勿手改 —— 由 `evals/robustness/make_answer_box.py` 白名单填充。

## 这里是给被测模型用的唯一舞台

本目录已剔除全部评测标注、判分器、注入剧本，以及**任何别家模型的答卷**。
被测模型的工作目录应当直接指向本层（不要再多给一层）。

## 三条边界

1. **答案写到 `<REPO_ROOT>\temp\robustness\answers/<run_id>/<题号>.json`**
   —— 在沙箱**外面**。`<run_id>` 每轮一个（如 `r1`/`r2`），多轮重估时
   前一轮的答案不会被后一轮的模型看到。
2. **不要往本目录里拷贝任何历史产物**（`E1-traces/`、`NL2T-*.json`、
   `*-grade*`、上一轮的 `answers/`）。它们会让模型照抄别人的答卷，
   而这跟"答对"在分数上无法区分。
3. **被测模型不许挂载仓库其余部分**。本目录已经是它该知道的全部。

## 可以看的

被测对象本体：`SKILL.md`、`README.md`、`manifest.yaml`、`architecture.md`、
`contracts/`、`static/`、`references/`、`src/`、`agents/`、`templates/`、`rag/`。

## 题卷

`questions/TASKS.md`（68 条题面一册，一次只复制一个题块）；
`questions/per_item/<题号>.txt`（一文件一句请求，直接粘贴）。

## 体检

```bash
python evals/robustness/make_answer_box.py --check
```

命中任意一条即 exit 1。Tier W 的故障仍只由注入器现场施加，别写进题面。
