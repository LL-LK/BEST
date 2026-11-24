# DSH × GLM 5.3 Flash

批次 BEST_run_20261118_121244，组别 D2。用 Python 3.11 或更新版本执行：

    python recompute.py

输入来自该组已归档的逐条评分。脚本复算 E1 加权分、E3 科学语义指标、E4 处置结果和 E5 各组成功率及按任务配对的精确检验。每组六类评价记录共 2,475 条。E3 的统一盲评为模型判分，E5 沿用原端到端机械成功判据。

本包用于离线复算统计。重跑模型或重做评分使用该平台的原始归档及对应环境。E2 与 E6 是原论文实验，没有列入本批补充组。

---

## 开源发布与论文对照说明

- **论文组别**：跨模型补充组（归档代号 D2） — `DeepSeek Harness 0.2.2-rc.3` × `glm-5.3-flash`
- **覆盖实验**：E1、E3、E4、E5（2,475 条评分记录）
- **代号说明**：数据记录中的 `D0 / D1 / D2 / P1 / H1` 仅作归档内部标识，分别对应论文中的 DeepSeek Harness 0.2.0 (`deepseek-v4.1-flash`)、DeepSeek Harness 0.2.2 (`mimo-v2.6-flash`)、DeepSeek Harness 0.2.2 (`glm-5.3-flash`)、Pi CLI 1.5.2 (`deepseek-v4.1-flash`)、Hermes CLI 0.23.2 (`deepseek-v4.1-flash`)。
- **开源许可**：本复现包遵循 **Apache License 2.0**（见根目录 `LICENSE`，Copyright 2026 The Authors）。
