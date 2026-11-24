# BEST-Skill

BEST-Skill 将自然语言请求转为 [BEST 测光标准星数据库](https://nadc.china-vo.org/data/best/) 的查询，记录查询条件、执行状态和结果来源。本仓库提供查询实现、实验数据和复现材料。

[文档导航](docs/README.md) 汇集实验、图表、开发和归档入口。

## 下载入口

- [最新 BEST-Skill 独立技能包（BEST_skill.zip）](https://github.com/LL-LK/BEST/releases/tag/best-skill)
- [复算命令与各批次口径](reproduction/portable/README.md)

## 复算入口

以下命令在仓库根目录执行。E2 从当前仓库读取保留原始行尾的冻结文件。

```text
python "reproduction/03_数据_E1-E6/E2/reproduce_e2.py" --verify-only
python "reproduction/05_溯源台账/复算脚本/verify_e1_paper.py"
python "reproduction/05_溯源台账/复算脚本/verify_e5_contrasts.py"
```

第一条核对 E2 的冻结输入、代码和 21 个 Gold 用例。第二条复算论文 E1 重判的均值 0.9530。第三条复算原论文 E5 的 B3 与 B2b 比较。[完整复算说明](reproduction/README.md)

## 仓库内容

| 目录 | 内容 |
| --- | --- |
| [skill](skill/) | BEST 查询、结果解析及 TAP/ADQL 网关源码与测试 |
| [实验图表](reproduction/02_图表/) | 最新 SVG 与出图数据 |
| [实验数据](reproduction/03_数据_E1-E6/) | E1–E6 原批和补测的材料、判分与执行记录 |
| [数字溯源](reproduction/05_溯源台账/) | 论文数值对应的结果和复算脚本 |

BEST 提供静态测光目录。逐历元时序、周期恢复和变星识别属于本论文所用访问接口的数据边界之外。复用代码时请保留 [MIT 许可](LICENSE)。引用数据或结果请同时注明所用 Release 与批次。
