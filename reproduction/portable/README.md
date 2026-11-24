# 五组跨组对照复算

[复现说明](../README.md) · [五组实验目录](../releases/README.md)

仓库根目录运行（需安装 `requirements-five-groups.txt`）：

```bash
python -m pip install -r reproduction/portable/requirements-five-groups.txt
python reproduction/portable/recompute_five_groups.py
python reproduction/portable/build_appendix.py
```

输入目录 `five-group-inputs/` 包含五组共 12,375 个评价单元，生成 `five-group-results.json` 及附录 B 的表与图数据。`crossmatch-v15.csv` 为交叉匹配独立验证表。

使用 BEST 数据时可引用 [国家天文科学数据中心 BEST 条目](https://nadc.china-vo.org/data/best/)。
