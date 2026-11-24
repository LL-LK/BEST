# BEST-Skill

BEST-Skill 将自然语言请求转为 [BEST 测光标准星数据库](https://nadc.china-vo.org/data/best/) 查询，并记录查询条件、执行状态与结果来源。仓库导航见 [docs/README.md](docs/README.md)。

## 下载

- [BEST-Skill 技能包（BEST_skill.zip）](https://github.com/LL-LK/BEST/releases/tag/best-skill)
- [deepseek harness（deepseek-v4.1-flash）](https://github.com/LL-LK/BEST/releases/tag/exp-deepseek-harness-deepseek-v4.1-flash) — 主实验，E1–E6
- [deepseek harness（mimo-v2.6-flash）](https://github.com/LL-LK/BEST/releases/tag/exp-deepseek-harness-mimo-v2.6-flash) — E1 / E3 / E4 / E5
- [deepseek harness（glm-5.3-flash）](https://github.com/LL-LK/BEST/releases/tag/exp-deepseek-harness-glm-5.3-flash) — E1 / E3 / E4 / E5
- [pi harness（deepseek-v4.1-flash）](https://github.com/LL-LK/BEST/releases/tag/exp-pi-harness-deepseek-v4.1-flash) — E1 / E3 / E4 / E5
- [hermes harness（deepseek-v4.1-flash）](https://github.com/LL-LK/BEST/releases/tag/exp-hermes-harness-deepseek-v4.1-flash) — E1 / E3 / E4 / E5

## 复算

仓库根目录运行（Python 3.11+，离线）：

```bash
# 主实验 E1–E6（首次需 pip install -r reproduction/releases/deepseek-harness_deepseek-v4.1-flash/requirements.txt）
python reproduction/releases/deepseek-harness_deepseek-v4.1-flash/recompute.py

# 其余四组 E1 / E3 / E4 / E5
python reproduction/releases/deepseek-harness_mimo-v2.6-flash/recompute.py
python reproduction/releases/deepseek-harness_glm-5.3-flash/recompute.py
python reproduction/releases/pi-harness_deepseek-v4.1-flash/recompute.py
python reproduction/releases/hermes-harness_deepseek-v4.1-flash/recompute.py

# 五组跨组汇总（需 numpy）
python reproduction/portable/recompute_five_groups.py
```

各批次口径见 [reproduction/README.md](reproduction/README.md)。

## 目录

| 目录 | 内容 |
| --- | --- |
| [skill](skill/) | BEST 客户端、解析器、TAP/ADQL 网关与单测 |
| [reproduction/figures](reproduction/figures/) | 论文 SVG 矢量图（`figure-1.svg`–`figure-6.svg`、`figure-B1.svg`） |
| [reproduction/releases](reproduction/releases/) | 与 5 个实验 Release 一一对应的复算目录（Apache-2.0） |
| [reproduction/portable](reproduction/portable/) | 五组跨组对比汇总脚本与输入数据 |
| [reproduction/expert-review](reproduction/expert-review/) | E3 专家盲评工作簿与说明 |
| [docs](docs/) | 项目文档与目录索引 |

BEST 为静态测光目录，不含逐历元时序与变星周期分析。本仓库采用 [Apache-2.0 许可](LICENSE)。
