# 文档导航

[仓库首页](../README.md)

| 主题 | 入口 |
| --- | --- |
| 查询实现与开发 | [development.md](development.md) |
| 实验复现与数据 | [experiments.md](experiments.md) · [reproduction/README.md](../reproduction/README.md) |
| 图表与 Release | [paper.md](paper.md) |
| 全仓文档目录 | [catalog/README.md](catalog/README.md) |

`skill/` 存放查询客户端、协议契约与测试；`reproduction/` 存放矢量图、按 Release 组织的实验数据、跨组复算脚本与专家盲评表。

增删文档后，从根目录运行 `python docs/build_catalog.py` 刷新索引，用 `python docs/build_catalog.py --check` 校验一致。
