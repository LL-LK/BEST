# BEST-Skill

BEST-Skill 将自然语言请求转为 [BEST 测光标准星数据库](https://nadc.china-vo.org/data/best/) 的查询，记录查询条件、执行状态和结果来源。本仓库提供访问实现、论文和复现材料。

[文档导航](docs/README.md) 汇集论文、实验、开发和归档入口。

## 论文与下载

- [论文 PDF](reproduction/01_稿件/main.pdf) · [补充材料 LaTeX](reproduction/01_稿件/supplementary_material.tex)
- [原论文复现包](https://github.com/LL-LK/BEST/releases/tag/paper-reproduction) · [原包 SHA-256](https://github.com/LL-LK/BEST/releases/download/paper-reproduction/SHA256SUMS.txt)
- [复现说明与各批次口径](reproduction/README.md)

以下补充包给出四个框架与模型组合在 E1、E3、E4 和 E5 上的评分记录。每包附有可离线执行的复算脚本。

| 框架 | 模型 | 复现包 |
| --- | --- | --- |
| Pi | DeepSeek V4.1 Flash | [下载](https://github.com/LL-LK/BEST/releases/tag/paper-reproduction-pi-deepseek-v4.1-flash) |
| Hermes | DeepSeek V4.1 Flash | [下载](https://github.com/LL-LK/BEST/releases/tag/paper-reproduction-hermes-deepseek-v4.1-flash) |
| DSH | GLM 5.3 Flash | [下载](https://github.com/LL-LK/BEST/releases/tag/paper-reproduction-dsh-glm-5.3-flash) |
| DSH | MiMo 2.6 Flash | [下载](https://github.com/LL-LK/BEST/releases/tag/paper-reproduction-dsh-mimo-2.6-flash) |

## 复算入口

以下命令在仓库根目录执行。E2 从当前仓库读取保留原始行尾的冻结文件。原论文 Release 中的 E2 副本有换行字节差异，运行冻结核验时请使用此处的入口。

```text
python "reproduction/03_数据_E1-E6/E2/reproduce_e2.py" --verify-only
python "reproduction/05_溯源台账/复算脚本/verify_e1_paper.py"
python "reproduction/05_溯源台账/复算脚本/verify_e5_contrasts.py"
```

第一条核对 E2 的冻结输入、代码和 21 个 Gold 用例。第二条复算论文 E1 重判的均值 0.9530，旧评分链见 `verify_e1_batches.py`。第三条复算原论文 E5 的 B3 与 B2b 比较。四个补充包在解压目录运行 `python recompute.py`，即可核验文件并从包内评分记录重算主指标。 [完整复算说明](reproduction/README.md)

## 仓库内容

| 目录 | 内容 |
| --- | --- |
| [skill](skill/) | BEST 查询、结果解析及 TAP/ADQL 网关源码与测试 |
| [稿件与图表](reproduction/01_稿件/) | 论文、补充材料及插图 |
| [实验数据](reproduction/03_数据_E1-E6/) | E1–E6 原批和补测的材料、判分与执行记录 |
| [数字溯源](reproduction/05_溯源台账/) | 论文数值对应的结果和复算脚本 |

BEST 提供静态测光目录。逐历元时序、周期恢复和变星识别属于本论文所用访问接口的数据边界之外。复用代码时请保留 [MIT 许可](LICENSE)。引用数据或结果请同时注明所用 Release 与批次。
