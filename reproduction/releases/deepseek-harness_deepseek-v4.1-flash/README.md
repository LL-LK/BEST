# DSH × DeepSeek V4.1 Flash（D0）E1–E6 复现

解压后在包的根目录使用 Python 3.13 运行：

    python -m pip install -r requirements.txt
    python recompute.py

E1、E3、E4、E5 使用 D0 组的逐条成绩。 E2 和 E6 使用原实验的共享材料。E2 将冻结响应回放 63 次并和接受轨迹逐条比较。E6 从原批和 R3 的逐题记录复算重复性指标。使用已归档的成绩和响应，运行复算无需调用模型或观测站点。

D0 的历史 E5 使用 DSH 0.2.0-rc.2。MiMo 和 GLM Flash 补充组的 DSH 版本是 0.2.2-rc.3。

---

## 开源发布与论文对照说明

- **论文组别**：原主实验（归档代号 D0） — `DeepSeek Harness 0.2.0-rc.2` × `deepseek-v4.1-flash`
- **覆盖实验**：E1–E6（含 E2 确定性冻结回放与 E6 重复性检验）
- **代号说明**：数据记录中的 `D0 / D1 / D2 / P1 / H1` 仅作归档内部标识，分别对应论文中的 DeepSeek Harness 0.2.0 (`deepseek-v4.1-flash`)、DeepSeek Harness 0.2.2 (`mimo-v2.6-flash`)、DeepSeek Harness 0.2.2 (`glm-5.3-flash`)、Pi CLI 1.5.2 (`deepseek-v4.1-flash`)、Hermes CLI 0.23.2 (`deepseek-v4.1-flash`)。
- **外部数据与夹具说明**：`E2/accepted_run/snapshots/` 中的实采查询快照源自公开天文档案服务（Gaia DR3、Pan-STARRS1）在评测时点的查询响应片段，压力测试夹具为合成数据；`E2/accepted_run/preregistration.json` 已对本机 `pip_freeze` 做匿名与最小依赖脱敏，未改动任何受哈希保护的冻结输入与代码。
- **开源许可**：本复现包遵循 **Apache License 2.0**（见根目录 `LICENSE`，Copyright 2026 The Authors）。
