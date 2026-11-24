# 五组实验复算目录（按 Release 组织）

本目录与仓库 5 个实验 Release 一一对应，采用 [Apache License 2.0](LICENSE) 开源（Copyright 2026 The Authors）。

| 目录 | 框架与版本 | 模型 | 覆盖实验 | Release 压缩包 | SHA-256（前 16 位） |
| --- | --- | --- | --- | --- | --- |
| [deepseek-harness_deepseek-v4.1-flash](deepseek-harness_deepseek-v4.1-flash/) | DeepSeek Harness 0.2.0-rc.2 | `deepseek-v4.1-flash` | E1–E6 | [deepseek-harness_deepseek-v4.1-flash.zip](https://github.com/LL-LK/BEST/releases/tag/exp-deepseek-harness-deepseek-v4.1-flash)（3.47 MB） | `8b717b2ca8313e7b` |
| [deepseek-harness_mimo-v2.6-flash](deepseek-harness_mimo-v2.6-flash/) | DeepSeek Harness 0.2.2-rc.3 | `mimo-v2.6-flash` | E1 / E3 / E4 / E5 | [deepseek-harness_mimo-v2.6-flash.zip](https://github.com/LL-LK/BEST/releases/tag/exp-deepseek-harness-mimo-v2.6-flash)（171.2 KB） | `a1db6106438ac116` |
| [deepseek-harness_glm-5.3-flash](deepseek-harness_glm-5.3-flash/) | DeepSeek Harness 0.2.2-rc.3 | `glm-5.3-flash` | E1 / E3 / E4 / E5 | [deepseek-harness_glm-5.3-flash.zip](https://github.com/LL-LK/BEST/releases/tag/exp-deepseek-harness-glm-5.3-flash)（155.1 KB） | `5bbd26ea124db060` |
| [pi_deepseek-v4.1-flash](pi_deepseek-v4.1-flash/) | Pi CLI 1.5.2 | `deepseek-v4.1-flash` | E1 / E3 / E4 / E5 | [pi_deepseek-v4.1-flash.zip](https://github.com/LL-LK/BEST/releases/tag/exp-pi-deepseek-v4.1-flash)（211.6 KB） | `a158bac63a161da8` |
| [hermes_deepseek-v4.1-flash](hermes_deepseek-v4.1-flash/) | Hermes CLI 0.23.2 | `deepseek-v4.1-flash` | E1 / E3 / E4 / E5 | [hermes_deepseek-v4.1-flash.zip](https://github.com/LL-LK/BEST/releases/tag/exp-hermes-deepseek-v4.1-flash)（156.8 KB） | `bb9a3d3e943cf794` |

## 运行

```bash
# 主实验 E1–E6（需先安装该目录 requirements.txt）
python reproduction/releases/deepseek-harness_deepseek-v4.1-flash/recompute.py

# 其余四组（仅需 Python 3.11+ 标准库）
python reproduction/releases/deepseek-harness_mimo-v2.6-flash/recompute.py
python reproduction/releases/deepseek-harness_glm-5.3-flash/recompute.py
python reproduction/releases/pi_deepseek-v4.1-flash/recompute.py
python reproduction/releases/hermes_deepseek-v4.1-flash/recompute.py
```

## 说明

- E2（63 次离线冻结回放）和 E6（重复性检验）仅在主实验组开展；其余四组各含 2,475 条 E1/E3/E4/E5 评分记录。
- 主实验 `E2/accepted_run/preregistration.json` 仅清理了本机 `pip_freeze` 中的路径与无关包，未修改任何受哈希锁定的冻结输入或代码。
- `E2/accepted_run/snapshots/` 中的实采快照来自 Gaia DR3、Pan-STARRS1 公开查询响应片段，6 万行压力数据为合成夹具。
- 数据表中的 `D0 / D1 / D2 / P1 / H1` 分别对应上表五组实验。
