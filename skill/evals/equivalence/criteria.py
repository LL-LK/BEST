# -*- coding: utf-8 -*-
"""evals.equivalence.criteria — 跨实验「判定口径」等价守护 (退役回放层后的继承形)。

背景: 本包原本的第一类断言是"三家 transport 对同一份冻结快照必须吐出逐字节相同
的回包"。2026-10-07 裁定「全盘删回放改实跑」后, evals/groundtruth/transport.py
已删除 (该文件现已不存在), ``evals/equivalence/snapshots/`` 一并清空, 那条断言失去
比对对象 (docs/REPLAY-RETIREMENT-CRITERIA.md §3.2 末行给的就是这个处方:
「裁判读的是三家的 transport 实现逐字对比」→「改为对比**判定口径**而非传输实现」)。

被继承下来的是同一个风险: **同源功能多份实现各自漂移**。传输实现走了, 判定实现还在
——行主键 ``row_key`` 与哨兵 ``is_sentinel`` 各有独立副本, 任何一侧改了口径而另一侧
没改, 就会得到两套互斥的答案, 而 M1 的 P/R 与 M5 的状态判别都建在它们之上。

所属实验: 横向守护 E2/E4/E6 (本身不对应实验编号), 是铁律 6
「零跨实验 import」的机械落地件 —— 裁判可读选手件, 选手之间仍不得互相 import。

对外接口:
- ``scan_row_key_divergence()`` —— E2 归一层与 E2 独立 oracle 的行主键口径对账;
- ``scan_sentinel_divergence()`` —— 三份哨兵实现 (E2 归一层 / E2 oracle / E5 harness)
  的哨兵判定对账;
- ``ADVERSARIAL_ROWS`` / ``SENTINEL_PROBE_VALUES`` —— 对账用的对抗输入集,
  导出是为了让测试能对"换掉一侧实现"这类变异自证 (反证夹具需要自己造行)。

依赖与数据流: 输入只读, 全部来自本模块内的行字面量与 ``evals/_data`` 哨兵字典;
不发请求、不读快照、不落盘 —— 回放层退役后这条路径必须**零外部资产**, 否则
"等价性"又会被某份离线内容的存亡绑架。

关键契约与不变量: 两侧实现是**格式契约而非共享代码** (oracle 不得 import 被测逻辑),
因此只能靠"同一批对抗输入上给出同一答案"来证明它们没漂。默认比对的是
``row_key(row, batch=False)`` 与 ``row_key(row)`` —— **必须显式关掉批量判据**:
``batch=None`` 会靠"行里有没有 inputobjs_input_line"推断批量, 而锥搜回包同样带这一列
(单输入恒为 0), 真实回包形态上两侧必然分歧, 那是 ``batch=None`` 这条遗留支路的已知
性质 (CHANGELOG 第 6 条), 不是漂移。

陷阱与边界:
- **两个方向都要测**: 判据写反 (``left``/``right`` 装反) 时, 只跑一遍照样全绿,
  所以测试里另有「换实现即报分歧」的反证;
- **不比对 E5 的 ``row_key``**: ``evals/ablation/harness/run_batch.py`` 那份是 E5 自用
  的简化件 (硬编码 ps1 列名、坐标缺测塌成 ``0.000000000,0.000000000``), 与本仓
  "格式契约"逐字对齐的只有 E2 归一层与 E2 oracle 这一对。把简化件拉进来比,
  红的会是设计差异而不是漂移;
- **别把"两侧一致"当成"两侧正确"**: 本模块只证明没漂移, 对错由 E2 自己的用例判。
"""
from __future__ import annotations

# 标准库: 类型标注
from typing import Any, Callable

# 本地: 哨兵数据字典 (阈值与豁免列的唯一出口 — 本模块不写死任何阈值) 与三份被比对
# 的判定实现 (裁判可读选手件, 铁律 6 唯一合法出口)
from evals._data import load_null_sentinel
from evals.ablation.harness.support import is_sentinel_value as _e5_is_sentinel  # E5 harness 侧那份
from evals.groundtruth import canonical as _e2_canonical  # E2 归一层
from evals.groundtruth.gold import gold_algorithms as _e2_gold  # E2 独立 oracle (刻意不复用被测逻辑)

# 对抗输入集: 每一行对应一个真实回包形态, 或 CHANGELOG/注释里登记过的坑。
# 顺序即报告顺序, 便于整改者按行定位。
ADVERSARIAL_ROWS: tuple[tuple[str, dict], ...] = (
    ("裸 source_id", {"source_id": "BEST001", "ra": 1.0, "dec": 2.0}),
    ("带前缀 source_id", {"ps1_source_id": "PS1-1", "ps1_ra": 1.0, "ps1_dec": 2.0}),
    # stripe82 的真主键是 calibstars_id: 只认 *_source_id 时 27 行全部退化成坐标键
    ("stripe82 calibstars_id", {"stripe82_calibstars_id": "CALIBSTARS_0813769",
                                "stripe82_ra": 29.967632, "stripe82_dec": 0.024272}),
    # gaia 的 solution_id 是解算批次 ID 且字典序排在 source_id 前面: 取错就拿重复 id 当主键
    ("gaia 解算批次 ID 陷阱", {"gaia_dr3_18_solution_id": "batch-1",
                              "gaia_dr3_18_source_id": "4512921183874236032",
                              "gaia_dr3_18_ra": 286.1016964504027,
                              "gaia_dr3_18_dec": 15.6194192817014}),
    ("只有坐标", {"ps1_ra": 180.123456789123, "ps1_dec": 30.5}),
    ("id 空串退坐标", {"ps1_source_id": "", "ps1_ra": 180.0, "ps1_dec": 30.0}),
    # 坐标与主键都取不到: 两侧必须落到同一个整行 JSON 兜底, 否则这些行互相塌成一格
    ("整行 JSON 兜底", {"ps1_class_star": "0.99", "ps1_rflags": "16892216.0"}),
    ("坐标缺一半", {"ps1_ra": 180.0, "ps1_dec": ""}),
    # 超 2^53 整数字面量: 转 float 会丢末几位, 同一条记录两侧算出两个主键
    ("超 2^53 整数主键", {"gaia_dr3_18_source_id": "4512921183874236032",
                          "gaia_dr3_18_ra": 1.0, "gaia_dr3_18_dec": 2.0}),
    # 站点在大量幅值列回字面 nan/inf: float() 转得"成功"但不可比较, 必须当缺测
    ("非有限坐标 nan", {"ps1_ra": "nan", "ps1_dec": 30.0}),
    ("非有限坐标 inf", {"ps1_ra": "inf", "ps1_dec": 30.0}),
    ("裸名 ra/dec", {"ra": 10.0, "dec": -5.0}),
    ("只有 ra", {"ps1_ra": 10.0}),
    ("空行", {}),
)

# 哨兵探针值: 阈值两侧 + 豁免列真值 + 非数值格 + 空串, 一格都不能判错
SENTINEL_PROBE_VALUES: tuple[Any, ...] = (
    "-1004.0910078678945", "-999.0", "-1.0", "0.0", "99.0", "20.09",
    "16892216.0", "", "nan", "not-a-number", None,
)

# 对账用的列名: 一个普通数值列 + 三个豁免列的**全部实测形态**。三种形态都得在:
# 裸名 (pmra) / 含下划线的豁免名自身 (radial_velocity) / 带星表前缀的真实列
# (landolt_pmra 与 landolt_pmdec 确在 1001 个注册列名里)。前缀形态是 2026-10-07
# 实跑对齐时补上的: 旧口径里 E2 只做精确相等 (漏前缀), E5 只剥第一个下划线
# (把 radial_velocity 剥成 velocity), 两侧各漏一半, 合起来刚好没人管前缀形态。
SENTINEL_PROBE_COLUMNS: tuple[str, ...] = (
    "ps1_rpsf", "pmra", "pmdec", "radial_velocity", "landolt_pmra", "landolt_pmdec",
)


def scan_row_key_divergence(
    rows: tuple[tuple[str, dict], ...] = ADVERSARIAL_ROWS,
    *,
    left: Callable[[dict], str] | None = None,
    right: Callable[[dict], str] | None = None,
    coords_only: bool = False,
) -> list[str]:
    """行主键口径对账: 两侧对同一批对抗行必须给出同一个键。

    Args:
        rows: ``(形态名, 行)`` 序列; 缺省即本模块登记的对抗集。
        left: 左侧实现, 签名 ``row -> str``; 缺省为 E2 归一层。
        right: 右侧实现, 签名 ``row -> str``; 缺省为 E2 独立 oracle。
        coords_only: 是否走"结果集内 id 重复即退坐标键"的分支; 两侧须同步。

    Returns:
        分歧描述列表, 每条含形态名与两侧各自的键。**空列表 = 无分歧**。
    """
    # 延迟绑定默认实现: 模块导入期就把三个实验的包全拉进来, 会让
    # "只想 import 这份判据"的调用方被迫装载它们
    if left is None:
        def left(row: dict) -> str:  # noqa: E306 — 闭包吃 coords_only, 故必须 def 不能 lambda
            """左侧缺省 = E2 归一层; 显式关掉批量判据 (见模块头「陷阱与边界」)。"""
            return _e2_canonical.row_key(row, batch=False, coords_only=coords_only)
    if right is None:
        def right(row: dict) -> str:  # noqa: E306 — 同上
            """右侧缺省 = E2 独立 oracle。"""
            return _e2_gold.row_key(row, coords_only=coords_only)

    problems: list[str] = []                     # findings 列表: 空列表即"两侧一致"
    for name, row in rows:
        left_key = left(row)                     # 两侧各算一次: 共用会掩盖实现里的状态
        right_key = right(row)                   # 算完立刻比, 不留到循环外
        if left_key != right_key:                    # 只比键本身: 键相等即口径相等
            problems.append(f"[{name}] 归一层={left_key!r} oracle={right_key!r}")
    return problems


def scan_sentinel_divergence(
    columns: tuple[str, ...] = SENTINEL_PROBE_COLUMNS,
    values: tuple[Any, ...] = SENTINEL_PROBE_VALUES,
    *,
    left: Callable[[str, Any], bool] | None = None,
    mid: Callable[[str, Any], bool] | None = None,
    right: Callable[[str, Any], bool] | None = None,
) -> list[str]:
    """哨兵判定口径对账: 三份实现对同一批 (列, 值) 必须给出同一个结论。

    三份分别是 E2 归一层、E2 独立 oracle、E5 harness。前两份读字典, E5 那份
    由调用方把阈值传进来 —— 它不自己读字典, 所以对账时传的是**字典现值**,
    这样"阈值抄错"与"判定写错"会在同一处暴露, 归因不必猜。

    Args:
        columns: 探针列名, 含三个豁免列。
        values: 探针值, 覆盖阈值两侧与非数值格。
        left/mid/right: 三份实现, 签名 ``(column, value) -> bool``; 缺省为仓内三份。

    Returns:
        分歧描述列表, 每条含列名、值与三方的结论。**空列表 = 无分歧**。
    """
    threshold = float(load_null_sentinel()["threshold"])   # E5 那份不自读字典, 阈值由对账方给
    if left is None:
        left = _e2_canonical.is_sentinel              # 左侧缺省 = E2 归一层
    if mid is None:
        mid = _e2_gold.is_sentinel                    # 中间 = E2 独立 oracle
    if right is None:
        def right(column: str, value: Any) -> bool:  # noqa: E306 — 闭包吃 threshold, 故必须 def
            """右侧缺省 = E5 harness 那份 (签名多一个 threshold, 故不能直接赋值)。"""
            return _e5_is_sentinel(column, value, threshold)

    problems: list[str] = []                          # findings 列表: 空列表即"三方一致"
    for column in columns:
        for value in values:
            verdicts = (left(column, value), mid(column, value), right(column, value))  # 三方各判一次
            if len(set(verdicts)) != 1:               # 三方必须同一个结论, 任意两方分歧即记
                problems.append(f"[{column}={value!r}] 归一层={verdicts[0]} "
                                f"oracle={verdicts[1]} E5={verdicts[2]}")
    return problems
