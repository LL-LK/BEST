# 论文复现与五组对照

[复现说明](../README.md) · [实验图表](../../docs/paper.md)

## 原论文

[下载原论文便携复现包](https://github.com/LL-LK/BEST/releases/latest)，解压后在顶层运行。Python 3.13 环境已验证。

```text
python -m pip install -r reproduction/portable/requirements-paper.txt
python reproduction/portable/recompute_paper.py --e2-replay replay-e2
```

命令从记录复算 E1、E3、E4、E5、E6 和 v15 交叉匹配，输出 `paper-results.json`。E2 在新目录中核对 21 个 Gold 场景，并逐条比较 63 次冻结回放。省略 `--e2-replay` 时运行输入、冻结代码和独立 Gold 校验。原论文与各实验批次的口径见 [复现说明](../README.md)。

- E3 原稿复算使用原批次 192 份离线答卷的评分计数。24 份在线答卷单列。历史主评助手接触过组别映射，原批次的主评独立性与后续五组统一自动盲评不同。
- E4 用 r2 的三轮处置与加权判分。图 5 采用 103/105 与 15/15，源数据按正式判分生成。
- E5 主实验公开 56 题、12 臂、3 轮的评分和统计。v15 交叉匹配独立报告 1,024 对主验证与 96 对诊断记录。受保护 Gold 的重新判分需要授权。模型的新一轮生成和真实 NADC 查询按各自的环境条件执行。
- E6 从原批和 R3 的逐题分数分别重算宏平均与题级区间。逐题分数来自归档的重复记录。原始执行材料见 [实验索引](../../docs/experiments.md)。

## 五组对照

以下命令在五组对照归档的解压目录中运行。

```text
python -m pip install -r reproduction/portable/requirements-five-groups.txt
python reproduction/portable/recompute_five_groups.py
python reproduction/portable/build_appendix.py
```

生成 `five-group-results.json` 和 `appendix-B/` 下的表 B3–B8、图 B1 与源表。输入含五组共 12,375 个评价单元。E3 共 1,080 份答卷，其中 960 份离线、120 份在线。图 B1 使用热力图，百分比以各端点对应的样本为分母。

跨组区间和 Holm 检验按题配对重算。E3 的部分组内指标和 E5 的组内辅助统计读取已归档的统计表，同步核对 SFA 和 E5 主比较的逐条计数。D0 来自历史批次，跨历史差仅给描述性估计与区间。历史 E3 在线快照存在输入差异，公开表保留等价性标记。

## 数据来源及材料范围

| 结果 | 冻结输入 |
| --- | --- |
| 原论文 E1 | v55 的 28 题三轮重判 |
| E2 | run-07 场景、Gold、响应夹具、代码指纹及接受轨迹 |
| 原论文 E3 | 原批 216 份答卷的逐答复计数，含 192 份主测 |
| E4 | v70/r2 逐条判分与协议故障夹具的判分结果 |
| E5 | v5.1 的 2,016 条规则评分及用量分项 |
| 交叉匹配 | v15 `formal-scores.json` 的配对键、臂、主验证/诊断标记及成功标签 |
| E6 | 原批和 R3 的独立逐题分数，论文使用 R3 |
| 五组 | 历史 D0 和四个补充组公开的分项成绩，E3 来自统一盲评归档。E3 源归档 SHA-256 为 `08501464cf5db35188a978f50e62b8c7ee9f8e89e571159b617ba741a79fab55` |

便携包采用统计复算所需字段。早期实验材料可通过 [历史材料](../../docs/history.md) 查找。设备设置、账号回执、私人映射和受保护答案遵循各自原授权。使用 BEST 数据时可引用 [国家天文科学数据中心的 BEST 条目](https://nadc.china-vo.org/data/best/)；第三方资料按原来源许可使用。
