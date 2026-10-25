# E5 消融实验真实大模型跑批原始会话档案 (Live Transcripts)

## 一、资产定位与科学价值
本目录固化了 E5 消融实验历史实跑中留存的 **2,009 个真实大模型独立子会话文件**（Live LLM Runs）。
这是证明本系统消融实验全量由真实大模型会话跑批产出、彻底剥离测试替身（ScriptedLLM）的第一手物理铁证（Primary Empirical Evidence）。

- **物理位置**: `evals/ablation/transcripts/live_runs/`
- **文件总数**: 2,009 个实体文件（包含根目录下 2,007 个独立会话文件与 `_repair_backup/` 下的 2 个修复备份）
- **文件命名规则**: `{SystemId}__{TaskId}__{AttemptId}.prompt.txt` 与 `{SystemId}__{TaskId}__{AttemptId}.answer.json`
- **内容规范**: 
  - `.prompt.txt`: 发送给大模型的完整上下文提示词（包含工具集契约与科学问题）；
  - `.answer.json`: 真实大模型生成的结构化决策、工具调用请求与推理应答。

## 二、对应装配与决策汇入
本目录的 2,009 篇原始会话经由 `evals/ablation/harness/run_batch.py` 严格对账聚合，汇入以下标准化评测捕获表：
1. `evals/ablation/captures/all-systems-rebuild.json`（990 轮基线与消融全系统决策捕获表）
2. `evals/ablation/captures/b3-prose-rebuild.json`（B3 完整基线重构表）

## 三、治理边界与完整性要求
1. 本目录作为 E5 实验的只读历史原始凭据库，严禁随意删除或篡改；
2. 实验分发打包脚本（`scripts/package_experiments_bundle.py`）必须完整打包本目录，确保外部审稿专家与复现人员可逐题逐轮穿透核验。
