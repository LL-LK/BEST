# 文档导航

| 要找什么 | 从这里开始 |
| --- | --- |
| 下载最新 Skill 包与原论文复现包、查看实验图表 | [实验图表与发布包](paper.md) |
| 复算论文数字，核对评分、原始记录和批次 | [复现说明](../reproduction/README.md) · [E1–E6 实验资料](experiments.md) |
| 使用 BEST 查询、查接口规范、开发和测试 | [使用与开发](development.md) |
| 按目录查找具体文件 | [仓库文档目录](catalog/README.md) |

`skill/` 放置查询实现及其文档。`reproduction/` 按编号保存图表、实验数据、便携复现脚本、溯源台账与盲评表。导航链接指向这些材料的原路径。

新增文档时，先在对应主题下更新阅读入口。文件加入 Git 暂存区后，从根目录运行 `python docs/build_catalog.py` 刷新文件目录，运行 `python docs/build_catalog.py --check` 检查目录是否最新。
