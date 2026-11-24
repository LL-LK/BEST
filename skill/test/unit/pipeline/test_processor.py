"""src.core.source_postprocess (BestProcessor) 回归测试。

覆盖从 pybest 打包产物 (git 6f00efeb^〔本仓历史已无此对象〕〔本仓历史已无此对象〕) 还原的三项后处理能力: 天球去重 / 亮度筛选 / 波段统计。
重点是上游修正过的两个语义: 坐标缺失的行必须保留 (不能被当成 (0,0) 静默
丢弃), 以及 ≈-1000 测光哨兵必须视为"无测光"而不是"极亮"。
"""
from __future__ import annotations

# 第三方: pytest (approx 浮点比较 / parametrize)
import pytest

# 本地: 刚还原的 BestProcessor (迁移自 pybest 上游实现, 白盒锚点
# references/ALGORITHM-SPEC.md §2) — 纯函数后处理, 不发请求不落盘
from src.core.source_postprocess import BestProcessor


class TestDeduplicate:
    """deduplicate: 大圆距离去重 + 缺失坐标保留语义。"""

    def test_removes_positional_duplicate(self):
        """同一天区位置的两行只保留首条 (输入顺序稳定)。"""
        rows = [                                                                        # 同位置两行: 星等不同, 用来验"留的是首条"而非"留亮的那条"
            {"ra": 10.0, "dec": 20.0, "best_mag": 15.0},                                           # 首条: 去重契约要求保留输入顺序里的第一条
            {"ra": 10.00005, "dec": 20.0, "best_mag": 18.0},                                  # 位置几乎相同但星等更暗: 若实现按亮度挑, 这条会红
        ]
        # 偏移取 0.00005 度 = 0.18 角秒, 卡在 0.5 容差内且离边界很远:
        # 取值太小会被浮点噪声干扰判定, 太大又可能落到容差外让这条测不到去重
        kept = BestProcessor.deduplicate(rows, tolerance_arcsec=0.5)                         # 容差取 0.5 角秒: 0.18 角秒的偏移稳稳落在内
        # 断"只剩首条"而非断长度: 保留哪一条是契约的一部分, 等价的两条都能过
        assert kept == [rows[0]]                                                             # 断"只剩首条": 等价的两条都能过, 保留哪条才是契约

    def test_keeps_far_neighbour(self):
        """超出容差的位置不去重。"""
        rows = [                                                                                    # 相距 36 角秒的两行: 只验不去重
            {"ra": 10.0, "dec": 20.0},                                                              # 第一行
            {"ra": 10.01, "dec": 20.0},  # 0.01 度 = 36 角秒, 远离 0.5 容差: 这一对只验不去重, 不该被边界噪声牵动
        ]
        assert BestProcessor.deduplicate(rows, tolerance_arcsec=0.5) == rows  # 断整表等值而非条数: 少留/多留/换序三类故障一次断净

    def test_ra_wraparound_is_not_a_jump(self):
        """ra 349.9999 与 0.0001 在天球上相邻, 必须判为重替 (跨 0/360 圈)。"""
        rows = [                                                                                    # 跨 0/360 圈的两行
            {"ra": 359.9999, "dec": 0.0},                                                           # 圈内的第一行
            {"ra": 0.0001, "dec": 0.0},  # 0.0001 跨 0/360 圈: 朴素相减得 359.9998 度, 正是这条的考点
        ]
        kept = BestProcessor.deduplicate(rows, tolerance_arcsec=1.0)  # 容差取 1.0 角秒: 0.72 角秒的圈间邻域刚好落在内, 放宽就断不出
        assert len(kept) == 1                                                              # 必须判成重复: 朴素相减会得出 359.9998 度而放过

    def test_rows_with_unusable_coordinates_survive(self):
        """坐标缺失/越界的行保留: 去重是清洗, 不是裁剪。"""
        rows = [                                                                                    # 五行里只有一组坐标可比
            {"ra": None, "dec": None, "best_mag": 9.0},                                             # 坐标全缺: 去重没有依据, 这行必须留下
            {"ra": "not-a-number", "dec": 30.0},  # 字符串坐标复刻真实 CSV 单元格: 数值化失败时这行不能被当成坐标 0
            {"ra": 10.0, "dec": 95.0},          # dec 越界
            {"ra": -1.0, "dec": 30.0},          # ra 越界
            {"ra": 10.0, "dec": 20.0},          # 唯一可用坐标
        ]
        kept = BestProcessor.deduplicate(rows, tolerance_arcsec=0.5)  # 五行里只有一组可比: 判据必须跳过不可比行, 而不是把整批清掉
        # 断"一条不少"而不是断去重结果: 这四行坐标都不可用, 去重没有依据可判,
        # 把它们静默丢掉就把清洗做成了裁剪 —— 坐标字段仍可被下游人工核对
        assert len(kept) == len(rows)                                                             # 断"一条不少": 静默丢掉就把清洗做成了裁剪

    def test_missing_coordinate_rows_do_not_collide_with_each_other(self):
        """两行都缺坐标时不能互相当作重复 (None 不参与距离比较)。"""
        rows = [{"ra": None, "dec": None}, {"ra": None, "dec": None}]               # 两条一模一样的缺测行: 若把 None 当 0 参与比较, 会被判成重复
        # 两条一模一样的缺测行: 若实现把 None 当 0.0 参与大圆距离, 距离恰好
        # 为 0 会被判成重复而只剩一条, 用户平白少掉一个源
        assert BestProcessor.deduplicate(rows, tolerance_arcsec=0.5) == rows                        # 整表等值: 少一条就是用户平白少掉一个源

    def test_rejects_invalid_tolerance(self):
        """容差必须有限且非负, 否则 ValueError (防止负容差静默删光)。"""
        # 三个坏值各打一类: -1 是负数, inf 会让任何两点都"在容差内"从而删光,
        # nan 比较恒假会让去重静默失效 —— 只有显式拒绝才能暴露
        for bad in (-1.0, float("inf"), float("nan")):                                            # 三个坏容差: 负数、无穷、NaN 都必须被拒
            with pytest.raises(ValueError):                                                 # 抛 ValueError 是契约: 静默跳过会让非法容差变成悄悄删光全部源
                BestProcessor.deduplicate([{"ra": 1.0, "dec": 2.0}], tolerance_arcsec=bad)  # 单行且坐标合法: 唯一变量只剩容差

    def test_empty_input(self):
        """空输入守门: 返回空 list, 不抛异常 (纯函数边界, 上游空结果不得炸)。"""
        assert BestProcessor.deduplicate([]) == []  # 空输入是真实上游状态: 查无结果不该让整批处理崩在半路


class TestBrightSources:
    """bright_sources: 星等筛选 + 哨兵/缺测处理。"""

    def test_filters_by_best_mag(self):
        """按 best_mag 严格小于 mag_limit 筛选, 保持输入顺序 (可复现)。"""
        rows = [                                                                                    # 三行不同星等: 亮度筛选的输入
            {"best_mag": 15.0},                                                                     # 最暗的一条
            {"best_mag": 18.0},                                                                     # 中间那条
            {"best_mag": 12.0},                                                                     # 最亮的一条
        ]
        kept = BestProcessor.bright_sources(rows, mag_limit=16.0)  # 限值 16 卡在 15 与 18 之间: 一留一弃, 边界写错 (< vs <=) 也未必红
        assert [r["best_mag"] for r in kept] == [15.0, 12.0]       # 断值序列而非条数: 输出须按输入序而非星等排序, 复现性是契约

    def test_sentinel_is_not_bright(self):
        """≈-1000 哨兵是"无测光", 绝不能当成极亮星放行。"""
        rows = [{"best_mag": -1004.07}, {"best_mag": -999.0}]                                 # 两条哨兵值: 打成星等会造出"极亮源"这种科学废数据
        # -1004.07 是站点实测的真实哨兵值, -999.0 是它的整数变体; 两条都排在
        # mag_limit=16 之前, 若被当成真实星等就会被判成"最亮的目标"放进来
        assert BestProcessor.bright_sources(rows, mag_limit=16.0) == []                             # 两条都得被筛掉: 哨兵不是星等

    def test_falls_back_to_any_mag_column(self):
        """无 best_mag 时回退到任意 *mag 列 (按 key 排序取首个, 可复现)。"""
        # 值是字符串: 站点 CSV 单元格统一是文本, 回退路径要自己数值化
        rows = [{"ps1_gmag": "19.4"}, {"ps1_gmag": "21.0"}]                              # 字符串星等: 真实 CSV 单元格是文本, 数值化失败不该误筛
        kept = BestProcessor.bright_sources(rows, mag_limit=20.0)                                   # 走真实的亮度筛选入口
        # 断"只留第一条"而不是断第一条的值: 落选的是 21.0 超限那条, 断值能看出
        # 筛选确实按 mag_limit 发生过而不只是碰巧只回了一行
        assert kept == [rows[0]]                                                              # 只剩 19.4 那条: 21.0 超出 20 的上限

    def test_fallback_is_order_independent(self):
        """回退按 key 排序取列, 与 dict 插入顺序无关 (同输入同输出)。"""
        a = {"zmag": "15.0", "amag": "18.0"}                                                     # 列名不同但语义相同: 波段取值不能依赖列名前缀
        b = {"amag": "18.0", "zmag": "15.0"}  # 同一个 dict 换插入序: 证明回退按 key 排序取列而非碰巧取到首个
        assert BestProcessor._best_magnitude(a) == BestProcessor._best_magnitude(b)                 # 两个字典必须算出同一个最佳星等

    def test_non_numeric_magnitude_is_dropped(self):
        """非数值星等守门: "null"/""/None 一律剔除 — 缺测不等于暗, 不能
        靠默认值放行 (与 _as_float 统一口径)。"""
        rows = [{"best_mag": "null"}, {"best_mag": ""}, {"best_mag": None}]             # 三种"无值"形态: null 串、空串与 None 都要归成无值
        assert BestProcessor.bright_sources(rows, mag_limit=16.0) == []                             # 一条都不该留下: 无星等就没有亮度可言


class TestBandSummary:
    """band_summary: 波段计数。"""

    def test_counts_and_sorts(self):
        """波段计数守门: 按波段名排序输出 (dict 序可复现, 不依赖输入顺序)。"""
        rows = [{"band": "r"}, {"band": "g"}, {"band": "g"}]  # 输入序 r-g-g, 期望序 g 在前: 统计输出的键序也属于对外契约
        assert BestProcessor.band_summary(rows) == {"g": 2, "r": 1}                               # 逐波段计数: 统计口径是"每波段各有多少行"

    def test_missing_band_counts_as_unknown(self):
        """缺 band 键/空值/None 守门: 计为 unknown 而不是静默丢弃行 —
        统计口径必须能反映"有多少行没标波段"。"""
        rows = [{}, {"band": ""}, {"band": None}]                                          # 三种空波段形态: 都要归进 unknown 而不是各算一档
        assert BestProcessor.band_summary(rows) == {"unknown": 3}                            # unknown 收三条: 空波段不该让统计表凭空多几档

    def test_empty(self):
        """空输入守门: 返回空 dict (无数据不出虚构统计)。"""
        assert BestProcessor.band_summary([]) == {}                                              # 空输入返回空字典: 空表比零值表更不容易被误读


class TestAsFloat:
    """_as_float: 单元格数值化的统一口径。"""

    @pytest.mark.parametrize("raw", ["", "   ", "null", "NULL", "abc", None, "nan", "inf"])
    def test_unusable_values_return_none(self, raw):
        """不可用值守门: 空/空白/null/NULL/非数值/None/nan/inf 一律 None —
        站点返回的空值与哨兵变体必须被同一口径收口。"""
        assert BestProcessor._as_float(raw) is None  # 八个坏值收口到同一个 None: 分叉处理会让下游按类型再判一遍

    def test_parses_numeric_strings(self):
        """数值解析守门: 带空白的字符串与 int 输入都要正确转 float
        (CSV 单元格统一是字符串, int 来自上游归一化行)。"""
        assert BestProcessor._as_float(" 19.4 ") == pytest.approx(19.4)                           # 前后空白必须被吃掉: CSV 单元格常带空格
        assert BestProcessor._as_float(-5) == pytest.approx(-5.0)                                # 整数也要转成浮点: 数值化口径统一才谈得上比较

    def test_sentinel_floor(self):
        """哨兵下限守门: -900 及以下视为"无测光" (与
        BestSource.NULL_MAGNITUDE_SENTINEL 同口径), -899.9 是真值必须保留 —
        两层哨兵判据漂移会让"极亮源"幽灵重现。"""
        assert BestProcessor._as_float(-900.0) is None  # -900.0 正好压在下限: 阈值取小于等于, 写成严格小于这条立刻红
        # -899.9 紧贴阈值下沿: 间隔只有 0.1 是刻意的, 阈值若被写成严格大于
        # 而不是大于等于, 这条会立刻红 —— 边界语义不能靠"取个整数试试"
        assert BestProcessor._as_float(-899.9) == pytest.approx(-899.9)                # 负值不是哨兵: -899.9 离 -1000 很远, 必须原样存活

    def test_haversine_tolerance_behaviour(self):
        """大圆距离口径自检: 赤经方向 60 角秒的两点, 1 角秒容差不重, 120 角秒容差重。"""
        # 偏移 60/3600 度: 在赤经方向上 1 度约 3600 角秒, 于是这 0.01667 度
        # 恰是 60 角秒, 用它配 1 与 120 两个容差能分别落在两侧且都远离边界
        rows = [{"ra": 10.0, "dec": 0.0}, {"ra": 10.0 + 60.0 / 3600.0, "dec": 0.0}]     # 相距恰好 1 角秒的两行: 卡在容差边界上验"刚好容差内不去重"
        assert len(BestProcessor.deduplicate(rows, tolerance_arcsec=1.0)) == 2                      # 必须留两条: 边界判成 <= 就会误删
        assert len(BestProcessor.deduplicate(rows, tolerance_arcsec=120.0)) == 1  # 120 角秒容差对 60 角秒实测间距: 大圆距离算错一个量级就会断红
