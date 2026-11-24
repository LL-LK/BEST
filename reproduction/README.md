# 实验复现说明

[仓库首页](../README.md) · [文档导航](../docs/README.md) · [E1–E6 索引](../docs/experiments.md)

## 目录结构

| 目录 | 内容 |
| --- | --- |
| [figures](figures/) | 论文 SVG 矢量图（`figure-1.svg`–`figure-6.svg`、`figure-B1.svg`） |
| [releases](releases/) | 按 5 个实验 Release 组织的离线复算目录与脚本（Apache-2.0） |
| [portable](portable/) | 五组跨组对比统计与附录 B 复算脚本（`recompute_five_groups.py`、`build_appendix.py`） |
| [expert-review](expert-review/) | E3 专家盲评工作簿（DOCX/XLSX）与操作说明 |

## 复算命令

仓库根目录运行（无需模型 API 或外网）：

```bash
# 仅主实验 E2 回放与 E6 统计需要依赖
python -m pip install -r reproduction/releases/deepseek-harness_deepseek-v4.1-flash/requirements.txt

# 1. 原主实验（E1–E6）
python reproduction/releases/deepseek-harness_deepseek-v4.1-flash/recompute.py

# 2. 四个对照实验（每组 2,475 条评分，覆盖 E1 / E3 / E4 / E5）
python reproduction/releases/deepseek-harness_mimo-v2.6-flash/recompute.py
python reproduction/releases/deepseek-harness_glm-5.3-flash/recompute.py
python reproduction/releases/pi-harness_deepseek-v4.1-flash/recompute.py
python reproduction/releases/hermes-harness_deepseek-v4.1-flash/recompute.py

# 3. 仅验证 E2 冻结输入、代码哈希与 21 个 Gold 用例
python reproduction/releases/deepseek-harness_deepseek-v4.1-flash/E2/reproduce_e2.py --verify-only

# 4. 五组跨组汇总与附录 B
python reproduction/portable/recompute_five_groups.py
```

## 实验口径

- **E1**：28 题 × 3 轮重判，主实验加权均分 `0.9530`。
- **E2**：21 个场景 × 3 轮 = 63 次离线冻结回放；`E2/reproduce_e2.py` 校验全部冻结输入、代码与轨迹哈希。
- **E3**：原批与五组统一自动盲评各自保留评分计数；专家盲评工作簿见 [expert-review/](expert-review/)。
- **E4**：普通题 105 项与复合故障题 54 项分列计分（主实验普通题 `103/105`）。
- **E5**：56 题 × 12 配置 × 3 轮 = 2,016 格，按任务配对做 B3 与 B2b 精确检验（主实验 B3 `95/168` vs B2b `83/168`，Δ = `+7.14 pp`，p = `0.0885`）。
- **E6**：原批与 R3 补测重复性由 `deepseek-harness_deepseek-v4.1-flash/E6/statistics_e6.py` 复算，仅在主实验组开展。
