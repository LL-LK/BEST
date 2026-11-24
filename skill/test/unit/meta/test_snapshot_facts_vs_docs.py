# -*- coding: utf-8 -*-
"""快照实测事实 ↔ 代码/注释里写下的数字, 必须**逐处一致** (S4-02)。

背景: ``gaia_dr3_18_solution_id`` 是解算批次 ID, 它的"1000 行里只有几个不同值"
被当作"不能当主键"的论据写进了三处 (canonical / gold oracle / 自证测试)。那个
数字一度写成 2, 实测是 **1** —— 论据的**结论**没错 (它确实唯一到不能当主键), 但
**数字**错了, 而数字恰恰是可被复核的那一半。

本门禁把两侧钉在一起:
  - 左侧: 从 ``evals/groundtruth/snapshots/`` 的 ``rows_full.csv`` **现场重算**
    (不同值个数 / 重复值个数 / 出现次数), 快照是只读真值;
  - 右侧: 用正则把注释与 docstring 里写下的数字**抠出来**, 与重算值逐个比对。

两侧都从各自的源头取值, 不在本文件另抄一份常量 —— 抄常量的话, 注释与快照
一起漂移时门禁会跟着一起错。

⚠ 这里刻意区分两件**不同**的事, 无差别替换会改错正确的地方:
  - **不同值个数** (gaia ``solution_id``): 1000 行里 1 个不同值;
  - **重复** (ps1 ``source_id``): 431 个非空里 430 个不同, 即 1 个值出现 2 次。
  两者都叫"个数", 但一个是"取值基数", 一个是"重复组数", 判据与措辞都不同。

只读快照: 本门禁只 ``open(..., "r")`` 读 ``rows_full.csv``, 绝不写回 —— 快照是
E2 全链路的素材真值, 改了会让已签字的金标准悄悄换素材。
"""
from __future__ import annotations

# 标准库: csv 读快照 / re 抠注释里的数字 / sys 路径锚定 / pathlib
import csv  # 读快照 CSV: 标准库够用, 不引 pandas
import re  # 归一化与抠数字
import sys  # 路径锚定
from collections import Counter  # 频次统计: 不同值/重复值都靠它
from pathlib import Path  # 路径拼装

import pytest  # parametrize: 三处/两处逐个判

SKILL_ROOT = Path(__file__).resolve().parents[3]  # 仓根: 本件在 test/unit/meta/ 下三级
if str(SKILL_ROOT) not in sys.path:              # 门禁被单文件跑时也得能 import 仓内模块
    sys.path.insert(0, str(SKILL_ROOT))           # 幂等插入: 已在路径里就不重复插

SNAPSHOTS = SKILL_ROOT / "evals" / "groundtruth" / "snapshots"  # 素材真值目录 (只读)
GROUNDTRUTH = SKILL_ROOT / "evals" / "groundtruth"              # 注释真值目录 (被检查方)

# gaia 侧: 论据是"不同值个数" —— 一个值铺满 1000 行, 拿它当主键必塌
GAIA_SNAPSHOT = SNAPSHOTS / "live-2026-10-04" / "live_gaia_dr3_18_ra286.1_dec15.7_r300.0as"  # 1000 行那份
GAIA_COLUMN = "gaia_dr3_18_solution_id"          # 解算批次 ID: 计数论据针对的列
# ps1 侧: 论据是"重复" —— 存在重复值, 故 id 不能当主键 (与上面是两码事)
PS1_SNAPSHOT = SNAPSHOTS / "live-2026-10-04" / "live_ps1_ra359.5_dec0.0_r1800.0as"  # 1000 行那份
PS1_COLUMN = "ps1_source_id"                     # 真正的主键候选列: 本列有重复

# 注释里写法的两种措辞。归一化后 (去空白 + 去行内注释符) 才能跨折行匹配 ——
# "1000 行只有 1 个\n    不同值" 与 "1000 行只有 1 个\n# 不同值" 指的是同一句话。
_DISTINCT_PATTERN = re.compile(r"(\d+)个不同值")            # 抠 gaia 侧写的"不同值个数"
_REPEAT_PATTERN = re.compile(r"(\d+)个值重复出现(\d+)次")    # 抠 ps1 侧写的"(几个值, 几次)"


def _normalize(text: str) -> str:  # 归一化一步到位: 注释折行不该让判据失效
    """归一化: 去全部空白 + 去 ``#`` 行内注释符。

    去空白是为了跨折行匹配 (注释按 ~78 列硬折, 一个句子常断成两三行);
    去 ``#`` 是因为 ``gold_algorithms.py`` 那一处在**整行注释**里, 折行后
    第二行开头会多一个 ``#``, 不去掉就接不上。
    """
    return re.sub(r"\s+", "", text).replace("#", "")  # 先压空白再剔注释符


def _column_facts(snapshot: Path, column: str) -> tuple[int, int, int, int]:  # 四个事实一次算齐
    """从快照重算一列的四个事实: (总行数, 非空数, 不同值数, 重复组数)。

    只读: 用完即弃, 绝不回写 ``rows_full.csv``。
    """
    with (snapshot / "rows_full.csv").open(encoding="utf-8-sig", newline="") as handle:  # utf-8-sig: 容忍 BOM
        rows = list(csv.DictReader(handle))         # DictReader: 表头行不算数据行
    values = [row.get(column, "") for row in rows]  # 列不存在时取空串: 缺列退化成"全空"而不是 KeyError
    nonempty = [value for value in values if value not in ("", None)]  # 空串与 None 一律算缺测
    counts = Counter(nonempty)                      # 频次: 不同值数=len, 重复组数=出现>1 的个数
    duplicated = sum(1 for count in counts.values() if count > 1)  # 重复**组**数, 不是多余行数
    return len(rows), len(nonempty), len(counts), duplicated  # 四个事实整份返回


class TestGaiaSolutionIdDistinctCount:  # gaia 侧: "不同值个数"口径
    """gaia ``*_solution_id``: 写下的"不同值个数"必须等于快照重算值。"""

    def test_recomputed_facts_are_stable(self):  # 先钉住重算值本身
        """先把重算值本身钉住 —— 快照若换了素材, 这里是第一道响。"""
        rows, nonempty, distinct, duplicated = _column_facts(GAIA_SNAPSHOT, GAIA_COLUMN)  # 一次算齐四个事实
        assert rows == 1000, f"gaia 快照应是 1000 行, 实得 {rows}"                          # 行数变了说明素材换了
        assert nonempty == 1000, f"{GAIA_COLUMN} 应整列非空, 实得 {nonempty} 个非空"        # 缺测会让"不同值"失去意义
        assert distinct == 1, f"{GAIA_COLUMN} 应只有 1 个不同值, 实得 {distinct}"            # 这就是 S4-02 订正的那个数
        # 1 个不同值铺满 1000 行 => 唯一的那组"重复"就是它本身, 组数必然也是 1
        assert duplicated == 1, f"重复组数应同为 1 (单值铺满), 实得 {duplicated}"            # 交叉校验, 防 Counter 口径写反

    @pytest.mark.parametrize(  # 三处论据逐个判, 漏一处就红
        "relative_path",
        [                                                               # 三处都写下了这个数字
            "canonical.py",                  # _source_id_of docstring: 名单不比照 from_row 全部别名
            "gold/gold_algorithms.py",       # oracle 侧 _ID_LOGICAL_COLUMNS 注释: 同一论据
            "tests/test_e2.py",              # 反向自证用例 docstring
        ],
    )
    def test_documented_distinct_count_matches_snapshot(self, relative_path: str):  # 数字逐字比对
        """三处写下的"不同值个数"必须逐字等于重算值。"""
        source = _normalize((GROUNDTRUTH / relative_path).read_text(encoding="utf-8"))  # 归一化后才能跨折行抠
        found = [int(value) for value in _DISTINCT_PATTERN.findall(source)]             # 抠出全部写法
        assert found, f"{relative_path} 里找不到「不同值个数」的写法 —— 措辞变了须同步本门禁"  # 判据失效要显式炸, 不当通过

        _, _, distinct, _ = _column_facts(GAIA_SNAPSHOT, GAIA_COLUMN)                    # 重算侧现取, 不抄常量
        assert all(value == distinct for value in found), (                              # 逐个比, 不取首个
            f"{relative_path} 写下 {found}, 快照重算是 {distinct} "
            f"({GAIA_COLUMN} 实测不同值个数)"
        )

    @pytest.mark.parametrize(  # 反向钉死: 错值不得复发
        "relative_path", ["canonical.py", "gold/gold_algorithms.py", "tests/test_e2.py"]
    )
    def test_stale_value_two_is_gone(self, relative_path: str):  # 专盯那个错值
        """反向钉死: 那个错值 (2) 不得再回来。"""
        source = _normalize((GROUNDTRUTH / relative_path).read_text(encoding="utf-8"))  # 同一套归一化
        assert "2个不同值" not in source, (                                             # 归一化后跨折行也躲不掉
            f"{relative_path} 又写回 '2 个不同值' —— 实测是 1 "
            "(gaia 1000 行里 solution_id 只有一个取值)"
        )


class TestPs1SourceIdRepeatFacts:  # ps1 侧: "重复"口径 (与上面不同)
    """ps1 ``ps1_source_id``: 写下的"重复"必须等于快照重算值 (与上面不同口径)。"""

    def test_recomputed_facts_are_stable(self):  # 先钉住重算值本身
        """ps1 侧的重算值: 431 非空 / 430 不同 / 1 个值出现 2 次。"""
        rows, nonempty, distinct, duplicated = _column_facts(PS1_SNAPSHOT, PS1_COLUMN)  # 一次算齐
        assert rows == 1000, f"ps1 快照应是 1000 行, 实得 {rows}"                          # 素材行数
        assert nonempty == 431, f"{PS1_COLUMN} 应 431 个非空, 实得 {nonempty}"             # 该列并非整列有值
        assert distinct == 430, f"{PS1_COLUMN} 应 430 个不同值, 实得 {distinct}"           # 与非空数差 1 即一组重复
        assert duplicated == 1, f"应有 1 个值重复, 实得 {duplicated} 个"                   # 重复组数, 不是多余行数

    def test_repeated_value_occurs_twice(self):  # 把"出现 2 次"落到实处
        """那唯一 1 个重复值恰好出现 2 次 —— 写"出现 2 次"才有着落。"""
        with (PS1_SNAPSHOT / "rows_full.csv").open(encoding="utf-8-sig", newline="") as handle:  # 只读打开
            rows = list(csv.DictReader(handle))                                           # 表头不算数据行
        counts = Counter(                                                                # 频次统计
            row[PS1_COLUMN] for row in rows if row.get(PS1_COLUMN) not in ("", None)    # 剔掉缺测再数
        )
        occurrences = sorted(count for count in counts.values() if count > 1)             # 只留出现>1 的
        assert occurrences == [2], f"重复值的出现次数应恰为 [2], 实得 {occurrences}"       # 恰一组, 恰两次

    @pytest.mark.parametrize(  # ps1 侧论据写了三处: canonical 两处 + test_e2 一处
        "relative_path, expected_mentions",
        [
            ("canonical.py", 2),  # row_key docstring + id_keys_unique docstring, 两处
            ("tests/test_e2.py", 1),  # 重复降级用例的 docstring
        ],
    )
    def test_documented_repeat_matches_snapshot(self, relative_path: str, expected_mentions: int):  # 处数也钉
        """写下的"(几个值重复出现几次)"必须逐字等于重算值, 且处数不能少。"""
        source = _normalize((GROUNDTRUTH / relative_path).read_text(encoding="utf-8"))  # 归一化后才能跨折行抠
        found = [(int(a), int(b)) for a, b in _REPEAT_PATTERN.findall(source)]            # 抠出全部写法
        assert len(found) == expected_mentions, (                                        # 处数也要对
            f"{relative_path} 应有 {expected_mentions} 处'重复出现'写法, 实得 {len(found)} 处 {found}"
        )

        _, _, _, duplicated = _column_facts(PS1_SNAPSHOT, PS1_COLUMN)                     # 重算侧现取
        for value_count, occurrence in found:                                             # 逐个比, 不取首个
            assert value_count == duplicated, (                                            # 值个数
                f"{relative_path} 写 {value_count} 个值重复, 快照重算是 {duplicated} 个"
            )
            assert occurrence == 2, f"{relative_path} 写出现 {occurrence} 次, 实测应为 2 次"  # 出现次数

    @pytest.mark.parametrize("relative_path", ["canonical.py", "tests/test_e2.py"])  # 反向钉死
    def test_stale_repeat_wording_is_gone(self, relative_path: str):  # 专盯那个含糊措辞
        """反向钉死: 那个说不清计数的旧措辞 (2 个重复) 不得再回来。"""
        source = _normalize((GROUNDTRUTH / relative_path).read_text(encoding="utf-8"))  # 同一套归一化
        assert "2个重复" not in source, (                                                 # 旧措辞回来了
            f"{relative_path} 又写回 '2 个重复' —— 实测是 1 个值出现 2 次; "
            "'2 个重复'既可读成 2 个值也可读成 2 行, 两种读法里只有后者碰巧对"
        )
