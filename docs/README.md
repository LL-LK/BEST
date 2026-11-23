# 文档导航

| 要找什么 | 从这里开始 |
| --- | --- |
| 阅读或引用论文，下载原论文及补充复现包 | [论文、图表与发布包](paper.md) |
| 复算论文数字，核对评分、原始记录和批次 | [复现说明](../reproduction/README.md) · [E1–E6 实验资料](experiments.md) |
| 使用 BEST 查询、查接口规范、开发和测试 | [使用与开发](development.md) |
| 追查旧版源码、评分变更和交接记录 | [历史材料](history.md) |
| 按目录查找具体文件 | [仓库文档目录](catalog/README.md) |

`skill/` 放置查询实现及其文档。`reproduction/` 按编号保存稿件、图表、实验数据、复现源码、溯源台账、盲评表、脱敏记录和封存清单。导航链接指向这些材料的原路径。

新增文档时，先在对应主题下更新阅读入口。文件加入 Git 暂存区后，从根目录运行 `python docs/build_catalog.py` 刷新文件目录，运行 `python docs/build_catalog.py --check` 检查目录是否最新。
