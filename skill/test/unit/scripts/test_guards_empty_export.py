"""astro-best src.scripts.guards.to_csv 空导出语义回归 (A4)。

钉住两件事: 空 records + 显式 fieldnames 时产出"只写表头"的文件 (可被
csv 读回 0 行, 下游按"查询无结果"处理); 空 records 且无 fieldnames 时
显式抛 ValueError, 不再产出 0 字节文件 (那让"空导出"与"写出失败"在下游
不可区分)。全部离线: 只写临时目录, 无网络。
"""
from __future__ import annotations

import csv  # 标准库: 读回验证表头行数与数据行数

import pytest  # 第三方: raises 断言负路径

from src.scripts.guards import to_csv  # 本地: 被测导出, 空 records 的两种语义分叉点


class TestEmptyExport:
    """A4 回归: 空导出 = 只写表头, 表头来源为显式 fieldnames。"""

    def test_empty_records_with_fieldnames_writes_header_only(self, tmp_path):
        """空 records + fieldnames: 文件含表头且 csv 读回 0 数据行。

        验证的行为: to_csv([], path, fieldnames=[...]) 落盘, 文件唯一一行
        是表头, csv.reader 读回只有表头行。
        为什么重要: 0 字节文件让"空导出"与"写出失败"不可区分 (打不开/解析
        错 vs 真的没数据); 带表头的空文件可被 csv.DictReader 正常读出 0 行,
        下游按"查询无结果"处理。回归背景: docs/architecture/file-size-budget.md
        §6 A4。
        """
        target = tmp_path / "empty.csv"                  # tmp_path 隔离, 导出炸了也不污染仓库
        out = to_csv([], str(target), fieldnames=["ra", "dec", "mag"])  # 空 records + 显式表头 = 合法
        assert out == str(target)                       # 返回落盘路径, 下游可接着往下传
        text = target.read_text(encoding="utf-8-sig")   # utf-8-sig 与 csv.BOM 写出端对齐
        assert text.splitlines() == ["ra,dec,mag"]      # 唯一一行是表头, 文件绝不是 0 字节
        with open(target, newline="", encoding="utf-8-sig") as fh:  # newline="" 是 csv 模块硬要求
            rows = list(csv.reader(fh))                 # 读回一遍证明它是合法 CSV 而非裸文本
        assert rows == [["ra", "dec", "mag"]]           # 数据行 0 条 + 表头行 1 条

    def test_empty_records_without_fieldnames_raises(self, tmp_path):
        """空 records 且无 fieldnames: 显式抛 ValueError, 不落 0 字节文件。

        验证的行为: to_csv([], path) 抛 ValueError (消息指名 fieldnames),
        且目标文件不存在。为什么重要: 空列表没有 records[0] 可推头, 此时
        唯一诚实的选择是显式失败 — 静默写出的空文件正是 A4 要消灭的歧义。
        """
        target = tmp_path / "ambiguous.csv"  # 负路径: 这个文件本不该被创建出来
        with pytest.raises(ValueError, match="fieldnames"):  # match 钉住错误消息, 防退化
            to_csv([], str(target))  # 缺 fieldnames: 无 records[0] 可推表头
        assert not target.exists()  # 显式失败 ≠ 静默写一个 0 字节文件
