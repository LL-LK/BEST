# evals/nl2tool/traces/ — 实际调用轨迹 (一次跑批一条, 只增不改)

约定 (docs/eval-E1-nl2tool.md §8/§9):
- 每条轨迹 = 一个 JSON: ``{"task_id": "NL2T-nn", "model_id": ..., 
  "system_prompt_version": ..., "tools_schema_hash": ..., "network": bool,
  "tool_calls": [{"tool": ..., "args": {...}}], "answer_text": ...,
  "http_requests": n, "s1_events": [...], "timestamp": ...}``;
- **只增不改**: 跑批历史可回溯; 重跑写新文件 (或按 run_id 子目录);
- 真实跑批产物落 ``temp/nl2tool/`` (gitignored), 人工复核后把定稿轮次的
  轨迹复制到本目录入库 (作为 REPORT.md 的证据附件);
- 本目录内的 ``example_*.json`` 是**离线自证夹具** (黄金路径样例), 不是
  真实跑批数据 — 供 runner 冒烟与 tests 消费, 永久保留。

## golden/ 子目录 — 金标准合成轨迹 (判定器管线自证, **不是模型评测**)

- ``golden/NL2T-*.json`` 由 ``gen_golden.py`` 从 tasks.yaml 标注**合成**
  (``source: "golden-from-annotation"``): 期望工具序列 + 占位符具化的答案;
- 用途只有一个: 证明**判定器管线本身有效** — 期望轨迹必须被判六维全 1.0
  且零红线 (好答案能被判过); 与 broken/ 反证夹具 (坏答案必须被抓) 互为
  正反两面;
- **严禁**把 golden 跑批的 1.0 解读为"模型达到 1.0" — 模型评测必须用
  ``traces/`` 根下的真实跑批轨迹 (``source: "live-run"``);
- runner 对 golden 跑批会在 JSON (``provenance_note``/``trace_sources``)
  与 Markdown ("轨迹来源 (必读)" 段) 显式披露该性质, stderr 亦打印警告。

