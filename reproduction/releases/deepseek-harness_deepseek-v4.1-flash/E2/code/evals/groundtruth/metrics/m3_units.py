# -*- coding: utf-8 -*-
"""evals.groundtruth.metrics.m3_units — M3 单位与精度正确率 (权重 0.10)。

职责: 抓"单位声明对了但数值错了"这一类最容易蒙混过关的错误 —— 坐标被
当成角秒输出 (×3600)、星等超出物理范围、精度被悄悄降级, 这些在只看
字符串相等时全部看不出来。

口径 (E2 §6 M3), 三道独立检查缺一不可:
  (a) 单位: SUT 声明/输出的 unit 与 GT unit_map 逐字段一致;
  (b) 量纲探针: 坐标必须落 [0,360)/[-90,90]、角距非负、星等物理合理 —
      坐标被当 arcsec 输出 (×3600) 会立刻越界, 防"声明对了但数值错了";
  (c) 精度: decimal.Decimal 数有效位数, 低于 GT precision_map 下限判错
      (降精度), 整数补 .000000 的假精度不判错但记 warn。

所属实验: E2 金标准一致性 (方案真值 docs/eval-E2-groundtruth.md §6 M3),
在 ``metrics/__init__.py`` 的 M_WEIGHTS 里占 0.10。

对外接口: ``score_m3(gold, actual)`` 返回 score/pass/三条分率/四类错误
明细/blockers; ``_significant_digits`` 是精度判定的唯一有效位数算法。

依赖与数据流: 输入是金标准的 unit_map/precision_map 与被测结果的标准行集,
量程区间与单位表从 ``evals/_data/tolerances.yaml`` 单点读取; 产物只进
E2 报告 JSON, 本件自己不落盘。

关键契约与不变量: 三道检查**都要过**才算 pass, 不是加权平均后放过 ——
单位对而数值越界, 仍是错的答案; 各分率的分母是"实际检查过的项数",
未被声明或不可解析的项不计入, 但因此分母为 0 时一律记满分 (无从判定
不等于判错, 判定完整性由 M6 负责); 全离线回放, rate_limit 归零。
零跨实验 import, 跨实验单位语义一致性由 ``evals/equivalence/`` 断言守护。

陷阱与边界: 精度判定用 decimal 而不是 float, 因为 float 的 repr 会把
"整数补零"和"真实多位数"都变成同一种字符串形态, 用 float 数位会把
假精度全判成真精度; 量程上界默认可取等号, 只有探针显式声明
max_exclusive (如赤经 360) 才用半开区间 —— 赤经 360 与 0 是同一个天区,
判它越界属于口径错误而非数据错误。
"""
from __future__ import annotations

# 标准库: decimal 有效位数统计 (精度判定的唯一可信算法)
import decimal

# 标准库: math 判非有限值 (探针分母只收可比较的观测量)
import math

# 本地: 量纲探针区间与单位表 (evals/_data 单点)
from evals._data import load_tolerances

# 本地: 星等列与哨兵判定的唯一真源 (探针表两处都不另抄一份)
from src.serialization import is_magnitude_column, is_missing_sentinel


def _resolve_probe_columns(semantic: str, mapping: dict, row: dict) -> list[str]:
    """把一个探针的**语义名**解析成这一行里真实存在的列名 (实测表驱动)。

    三种匹配形态, 全由 ``tolerances.yaml::dimension_probe_columns`` 声明:
    ``exact`` 逐字相等、``suffix`` 后缀命中、``predicate`` 交给仓内已有判据
    (``magnitude_column`` → :func:`src.serialization.is_magnitude_column`)。
    表里的每一项都来自实测 (扫 85 份快照 CSV 表头), 不是凭印象写的。

    ``exclude`` 里的列**形状对但语义不对**: 实测 ``inputobjs_input_ra`` 以 ``_ra``
    结尾, 却是**锥心坐标**而非源的赤经, 且恒落在合法区间内。放进来等于让探针只
    检查一个恒真的量 —— 比不检查更坏, 因为它看起来在查。

    Args:
        semantic: 探针语义名 (``ra_deg`` 等)。
        mapping: 整张映射表。
        row: 当前行 (决定哪些真实列**此刻**存在)。

    Returns:
        命中的真实列名, 按键排序 ⇒ 同一行多次调用必得同一序 (可复现)。
    """
    spec = mapping.get(semantic) or {}
    excluded = {str(x).lower() for x in spec.get("exclude") or ()}
    exact = {str(x).lower() for x in spec.get("exact") or ()}
    suffixes = tuple(str(x).lower() for x in spec.get("suffix") or ())
    predicate = spec.get("predicate")
    hit: list[str] = []
    for key in sorted(row):  # 排序遍历: 多列同时命中时顺序可复现
        low = str(key).lower()
        if low in excluded:  # 排除名单优先于一切: 它是"形状像但语义不同"的坑
            continue
        if low in exact or (suffixes and low.endswith(suffixes)) or (
                predicate == "magnitude_column" and is_magnitude_column(key)):
            hit.append(key)  # 三条命中路径的并集
    return hit


def _probe_row(semantic: str, probe: dict, mapping: dict, row: dict) -> tuple[int, int, list]:
    """对一个语义探针跑遍本行所有命中列, 返回 ``(分母, 分子, 越界明细)``。

    Returns:
        三元组: ``checked`` 实际比过的格子数、``ok`` 落在区间内的格子数、越界明细。
        不可转数的格子 (含哨兵字符串) **既不奖也不罚**, 归 M2/M5 管辖 ——
        在这里判错会让"有缺失值"被重复计成量纲错误。
    """
    checked = ok = 0                              # 本行内的 (分母, 分子)
    errors: list[dict] = []                        # 越界明细: 带列名与探针副本, 复现不必回查表
    for column in _resolve_probe_columns(semantic, mapping, row):
        raw = row.get(column)
        if raw is None:  # 空值不是越界, 是缺测: 归 M5, 不进本探针分母
            continue
        try:
            value = float(raw)  # 先转 float 再判区间: 转不过去的字符串由 except 分支兜
        except (TypeError, ValueError):
            continue  # 不可转数 (含哨兵字符串) 跳过而非判错, 同上
        if not math.isfinite(value):  # NaN/inf 与任何界比较都没意义, 且会污染均值
            continue  # 非有限值一律不作为观测量
        # **哨兵值不进分母** (2026-10-07, 观测面接通后立刻暴露的一类): 回包里
        # "没有测光" 的表示是哨兵带 (ps1 实测 -1001.9 ~ -1004.1, 共 870 格里的
        # 多数)。它是**缺测标记**不是测量值, 拿它去比 [-10, 40] 会把"这行没测光"
        # 报成"量纲错"—— 实测让 magnitude 通过率掉到 0.2345, 而那不是缺陷。
        #
        # 判据复用 :func:`src.serialization.is_missing_sentinel` (全仓唯一哨兵真源,
        # 已含下侧哨兵带 + 上侧 99.0 + 豁免列名单), **不在这里另抄一份阈值**。
        # 注意它按**列**判: 坐标列的 -1500 是真的"当 arcsec 输出了赤经" (P0 那
        # 一类真缺陷), 不是哨兵, 所以坐标探针照样会把它抓出来。
        if is_missing_sentinel(column, value):
            continue  # 缺测标记: 既不奖也不罚, 与 None 同档
        checked += 1  # 只有成功取到有限、且非哨兵的格子才进分母
        lo, hi = probe.get("min"), probe.get("max")  # 两端都可缺省: 只约束一端是合法配置
        # in_range 用 and 累加而非提前 break: 一个探针可以同时约束
        # 下界、上界与非负, 逐条累加才不会漏掉后面的约束
        in_range = True  # 从真起步逐条收紧: 任一约束不过即出界, 不做提前 break
        if lo is not None:  # 下界缺省即不约束: 表里没写的界不参与判定
            in_range = in_range and value >= lo  # 累乘式收紧: 已出界后不会被后续条件翻回真
        if hi is not None:  # 上界同理可选, 闭半开另由表里的 max_exclusive 决定
            # 上界默认闭区间; 只有探针显式声明 max_exclusive (如赤经 < 360)
            # 才半开, 因为 360 度与 0 度是同一片天区, 不该判越界
            #
            # 两条分支**都要与 in_range 相与**, 不能写成
            # `in_range = in_range and value < hi if excl else value <= hi` ——
            # Python 的条件表达式优先级使那一行等价于
            # `in_range = (in_range and value < hi) if excl else (value <= hi)`,
            # 于是 max_exclusive 缺省时, 本行**整体覆盖**掉上一行 (min) 已经
            # 收紧出的结果: 下界越界的格子只要同时满足上界就被判回 in_range,
            # 下界约束形同虚设 (P0-15「上界三元优先级」)。
            if probe.get("max_exclusive"):  # noqa: SIM108 — ruff 建议的三元写法正是本处修复前的缺陷, 见上三行
                in_range = in_range and value < hi  # 半开: 端点本身不算在区间内
            else:
                in_range = in_range and value <= hi  # 闭: 端点算在内; 仍要与已有结论相与
        if probe.get("non_negative"):
            in_range = in_range and value >= 0  # 非负单列一档: 角距这类量纲靠它兜, 不必在表里重复写 min
        if in_range:  # 全部约束都满足才记一致, 不设"部分出界"的中间档
            ok += 1  # 分子与 checked 同一批格子, 两条率同口径
        else:
            errors.append({"column": column, "value": value, "probe": probe, "semantic": semantic})
    return checked, ok, errors


def _significant_digits(value) -> int:  # 用 Decimal 数有效位数: 走 float 尾数已丢, 数出来的位数不可信
    """有效位数 (decimal.Decimal 归一后数位; 不可解析返回 0)。"""
    try:  # 容差与 E2 同档: 严格相等会把 18.2 与 18.200000 判成两个数
        # 走 str() 再进 Decimal: 直接 Decimal(0.1) 拿到的是二进制展开的
        # 无限尾数, 数出来 55 位有效数字, 任何精度判据都会失效
        d = decimal.Decimal(str(value)).normalize()  # 归一去尾零: "1.230" 与 "1.23" 的差是书写形态, 不是有效位数
    except (decimal.InvalidOperation, ValueError):  # 缺单位不判失败: 没有单位不等于单位错
        return 0
    exponent = d.as_tuple().exponent
    # NaN/Inf 的 exponent 是**字符串** ('n'/'F'), 拿它跟 0 比会抛 TypeError。
    # 站点在真实回包里大量回字面量 nan (见 canonical._as_float), 这类值没有
    # 可数的有效位, 与"解析失败"同档返 0。
    if not isinstance(exponent, int):
        return 0
    digits = len(d.as_tuple().digits)  # 数 as_tuple 的数位: repr 会被科学计数法骗, str 会被前导零骗
    # exponent >= 0 说明 normalize 后仍带尾零 (如 1.230→1.23 的补零形态),
    # 那个"零"不是有效位, 减一; exponent < 0 时数位即为全部有效位
    return max(digits - 1, 0) if exponent >= 0 else digits


def _is_padded_precision(value) -> bool:
    """值是不是「补零假精度」形态 (如 ``18.000000`` / ``18.20``)。

    判据只有一条: 文本形态的小数部分**以 0 结尾**。小数末尾的零一个有效位都
    不贡献 —— ``18.200000`` 与 ``18.20`` 的有效位都是 3, 多出来的零只是书写
    形态。所以这是「声称了并不存在的精度」, 与「降精度」是两回事: 真降精度
    是有效位真的少了 (``18.200000`` → ``18.2``), 那种值文本里根本没有尾零,
    仍按 errors 判错。分开是因为 E2 §6 M3 (c) 写明「整数补 .000000 的假精度
    不判错但记 warn」—— 判错会把一个格式选择当成精度缺陷, 属误伤。
    """
    text = str(value).strip()
    if "." not in text:      # 没有小数点就没有补零可言 (整数 18 不算假精度)
        return False
    return text.split(".", 1)[1].endswith("0")


def score_m3(gold: dict, actual: dict) -> dict:
    """M3: 单位一致率与精度达标率 (两道各自 pass, 汇总取均值)。

    **本批没有行 ⇒ 整体记 N/A** (``score=None``), 不判红。这不是"放宽", 而是
    E2 §6.5 的 N/A 口径: 空结果态的用例 (边界半径 0 / 空快照 / 软 404) 本来就
    **一行都没有**, 逐格判定的对象不存在, 记 0 分是把"没东西可比"说成"数据错了"。
    这三道的状态由 M5 裁决, 不该由 M3 拦。

    与"零分母"是两回事, 别混:

    - **没有行** → M3 不适用 (``score=None``), 不阻断 —— 对象不存在;
    - **有行但某维度映射没接上** → 阻断 (``zero_denominator:<dim>``) —— 口径有洞。

    2026-10-07 之前这两者都记成"零分母阻断", 于是三类空态用例被 M3 拦下, 而
    它们本该由 M5 判; 修完映射表后剩下的正是这三类。
    """
    rows = actual.get("rows") or ()
    if not rows:                                # 空结果态用例 (边界半径 0 / 空快照 / 软 404) 走这条
        # 一行都没有: 逐格判定无对象。M5 会去核"报的态对不对", 那才是这类用例的判据。
        return {
            "score": None,          # N/A: 不进分母, 也不折成 0.0 (记 0 是 §11 阻断项 3)
            # pass=True 与 M2 的同类 N/A 保持一致 (m2_fields:110): aggregate 用
            # `m.get("pass") is False` 判失败, N/A 若写 pass=False 会被读成"判了不过"。
            # 真正的分数是 None —— 看分数的人不会把它当满分。
            "pass": True,
            "note": "本批无行: 逐格判定无对象, M3 记 N/A (状态由 M5 裁决)",
            "unit_rate": None, "probe_rate": None, "precision_rate": None,
            "unit_checked": 0, "probe_checked": 0, "prec_checked": 0,
            "zero_denominator": [], "not_observable": ["unit"],
            "unit_errors": [], "probe_errors": [], "precision_errors": [],
            "precision_warnings": [],
            "blockers": [],          # 不阻断: 没有行不是缺陷
        }
    tolerances = load_tolerances()  # 经 lru_cache 缓存: 改容差表须先清缓存或重启进程, 否则本进程仍读旧值
    unit_map = gold.get("unit_map") or {}  # GT 未声明即空表: 没有期望就没有可判错的列
    precision_map = gold.get("precision_map") or {}  # 同理: 精度下限缺失时不判降精度, 空表不该造出假错误
    probes = tolerances.get("dimension_probes") or {}  # 量程表单点读取: 改阈值只改表, 历史报告才可比
    declared_units = (actual.get("declared_units") or {})  # 无来源 => 该维度记 not_observable  # or {} 兜 None: 完全不报单位应体现为全列未声明, 而不是异常

    unit_checked = unit_ok = 0                                                       # 单位核对计数从零起: 分子分母分开记, 便于报告"查了几条、过了几条"
    unit_errors = []  # 单位失配明细: 每条带两侧原值, 报告才能指出是哪一列错
    for column, gold_unit in unit_map.items():  # 单位逐列核: 混用单位会让整列测光全部失真
        declared = declared_units.get(column)  # 逐列取对方声明: 声明可能只覆盖部分列
        if declared is None:  # 未声明即跳过而非判错: 少报与报错是两种问题, 声明完整性归 M6
            continue  # 未声明不猜 (由 M6 版本面对账声明完整性)
        # 分母只数"对方确实报了"的列: 拿没声明的列当错, 会让"少报"与
        # "报错"混成同一种失分, 报告里看不出到底是哪种问题
        unit_checked += 1  # 分母只长在实际比较过的列上: 没比的列不得进分母
        # 大小写与空白不敏感: 单位符号 "DEG"/"deg" 指同一件事, 但 "deg"
        # 与 "arcsec" 必须判错, 所以只归一书写形态, 不做单位换算
        if str(declared).strip().lower() == str(gold_unit).strip().lower():  # 大小写与空白归一后再比: 否则 "Deg" 与 "deg" 会被判成两种单位
            unit_ok += 1  # 分子与分母同口径累加, 两条率才可比
        else:
            unit_errors.append({"column": column, "gold": gold_unit, "declared": declared})

    probe_checked = probe_ok = 0  # 探针维度同一套计数: 分母只长在真正比过的格子上
    probe_errors = []  # 越界明细带 probe 副本: 复现时不必回查容差表就能核对口径
    probe_columns = tolerances.get("dimension_probe_columns") or {}  # 语义名 → 真实列名 (实测采样的数据表)
    for row in actual.get("rows") or ():
        # 逐行逐列跑探针: 量纲检查看的是值本身落在不落在物理区间, 与该列有没有被
        # 声明过单位无关, 所以这里不看 unit_map。
        #
        # **为什么必须先解析语义名** (U-6/D7): 探针表的键是 ``ra_deg`` / ``magnitude``
        # 这类语义名, 而回包行里的列是 ``ps1_ra`` / ``ps1_rpsf`` 这类逐表真实名。
        # 原实现直接 ``column not in row`` 一跳了事 —— 交集恒空 ⇒ 分母恒 0 ⇒
        # ``probe_rate`` 恒 1.0, 于是 M3 一直在对**零个格子**报"量纲 100% 合格"。
        for column, probe in probes.items():
            got, ok, errs = _probe_row(column, probe, probe_columns, row)
            probe_checked += got  # 分母: 只算真正取到数值的格子
            probe_ok += ok  # 分子: 与分母同一批格子, 两条率同口径
            probe_errors.extend(errs)

    prec_checked = prec_ok = 0                                                                      # 精度维度同一套计数
    precision_warnings, precision_errors = [], []  # 假精度只进 warnings: 整数补零不算降精度, 判错会误伤合法实现
    for row in actual.get("rows") or ():
        # 精度检查与量纲检查读同一批行但口径不同: 这里问"给了几位有效数字",
        # 不问"落在不在物理区间", 降精度的值往往是区间内的合法值
        for column, min_digits in precision_map.items():  # 小数位逐行核: 报告里"18.2"冒充"18.20"是常见失真
            if column not in row or row[column] is None:  # 缺列与 None 同样跳过: 两者都不是精度不够, 归 M2/M5
                continue
            prec_checked += 1  # 分母只数有值的格子: 空结果 case 不该白扣精度分
            digits = _significant_digits(row[column])  # 唯一算法入口: 有效位数口径散在多处就一定会漂
            # 达标线取自 GT 的 precision_map 下限, 不写死在代码里 ——
            # 改判据只改金标准, 代码跟着变会让历史报告不可比
            if digits >= int(min_digits):  # 下限转 int 再比: 表里写成字符串也不该让判据崩
                prec_ok += 1  # 达标即计入分子, 不足则进 errors 并带上位数与下限
            elif _is_padded_precision(row[column]):  # 补零形态单独分流: 整数补 .000000 是声称了
                # 不存在的精度, 不是把有效位丢了 —— 判错会误伤合法实现 (M3 (c) 原意)。
                # 计入分子而不是只记 warning: 记错会拉低 prec_rate, 那正是注释说要避免的误伤。
                precision_warnings.append({"column": column, "value": row[column],
                                           "digits": digits, "min": min_digits})
                prec_ok += 1
            else:
                precision_errors.append({"column": column, "value": row[column],
                                         "digits": digits, "min": min_digits})

    # 三条分率的分母都是"实际检查过的项数"; 分母为 0 时**不记满分也不记 0 分**,
    # 而是判为"不可判定"并升级成阻断项 (U-6/D7)。
    #
    # 为什么不记 1.0: 零分母给满分会让这道闸在真实数据上**恒绿**。实测 7180 行
    # 真实数据下, 量纲探针的探针键与列名交集全空 ⇒ probe_checked 恒 0 ⇒
    # probe_rate 恒 1.0 ⇒ 任何单位/量纲错误都抓不到, 而报告上写着"量纲 100% 合格"。
    # 恒真的判据比没有判据更坏: 它让人以为验过了。
    # 为什么不记 0.0: 那会把"没数据可比"误报成"数据错了", 且让空结果 case 白扣分。
    #
    # 所以: 率照给 (便于排序), 但 pass 必须为 False, 且 blocker 点名哪几项没验。
    # 分母同时导出 (unit_checked/probe_checked/prec_checked), 复核者不看 blocker
    # 也能自己看出"这一项是零样本"而不是"这一项满分"。
    unit_rate = unit_ok / unit_checked if unit_checked else 1.0   # 分母为 0 时率取 1.0 **仅为可排序**, 真正的判定在下面的 passed/blockers
    probe_rate = probe_ok / probe_checked if probe_checked else 1.0  # 同上
    prec_rate = prec_ok / prec_checked if prec_checked else 1.0  # 同上
    zero_denominator = [  # 逐项点名零分母: 报告读者要知道是"没验"而不是"验过了"
        name for name, checked in (("unit", unit_checked), ("probe", probe_checked),
                                   ("precision", prec_checked)) if not checked
    ]
    # **零分母要分成两种, 混为一谈就是本条目最初踩的坑** (2026-10-07):
    #
    #   not_observable —— 这道维度**按设计就没有第二个来源**, 谁来跑都是 0。
    #     实测 `unit` 正属此类: 回包行**不带任何单位字段** (全 1046 个实测列名里
    #     没有一个 unit), 仓内也没有逐列单位注册表 (protocol_catalog_tables 无此项)。
    #     于是 "GT 声明的单位 vs SUT 声明的单位" 根本无从比起 —— 拿 tolerances.yaml
    #     的 units 表去比 gold 的 unit_map, 那是**同一份表的自我对照**, 恒真的
    #     假判据, 比不判更坏。按 E2 §6.5 的 N/A 口径与 M6 的 ``reconcilable``
    #     先例, 它应被**显式披露为不可观测**, 而不是判红 —— 判红只会逼着人编一个
    #     假的单位来源出来。
    #
    #   zero_denominator(阻断) —— 这道维度**本该**有观测面却没接上 (比如探针语义名
    #     与真实列名没映射), 那是口径缺陷, 必须判红逼修。``probe`` 曾经就在这一类里,
    #     现已由 tolerances.yaml 的 dimension_probe_columns 补齐 (分母 0 → 726)。
    not_observable = ["unit"] if not declared_units else []  # 回包行不带单位字段, 全仓也无单位注册表  # 无来源即不可观测, 不阻断只披露
    blocking_zero = [name for name in zero_denominator if name not in not_observable]
    # 三道全过才算 pass: 单位对而数值越界, 答案仍然是错的, 不可用均值放过。
    passed = (unit_rate == 1.0 and probe_rate == 1.0 and prec_rate == 1.0
              and not blocking_zero)
    blockers = []  # 默认空: 只有量纲越界升级为阻断, 单位/精度只是扣分
    # 只有量纲越界升级为阻断项: 它意味着这份数据的物理量纲整体错了,
    # 后续所有基于它的比对都不可信; 单位/精度不一致是"扣分"而非"证伪"
    if probe_rate < 1.0:  # 探针未全过即阻断: 物理不可能的值出现时不该只看单位
        blockers.append("dimension_probe_violation")
    # 零分母**只对"本该可观测却没接上"的维度阻断**: 那不是"这道题没考",
    # 而是"判据口径有洞"。按设计无来源的维度走下面的 not_observable 披露。
    blockers.extend(f"zero_denominator:{name}" for name in blocking_zero)
    return {
        # score 是三率均值, 只用于报表排名; 真正的放行看 pass, 不看这个均值
        "score": (unit_rate + probe_rate + prec_rate) / 3.0,
        "pass": passed,
        "unit_rate": unit_rate, "probe_rate": probe_rate, "precision_rate": prec_rate,
        # 三个分母一并导出 (U-6/D7): 没有它们, 复核者看到 probe_rate=1.00 只知道
        # "满分", 不知道满分是"查了 726 格全对"还是"一格都没查"
        "unit_checked": unit_checked, "probe_checked": probe_checked, "prec_checked": prec_checked,
        "zero_denominator": zero_denominator,  # 全量零分母名单 (含不可观测的)
        "not_observable": not_observable,  # 其中"按设计无来源"的那几项: 只披露, 不阻断
        "unit_errors": unit_errors[:10], "probe_errors": probe_errors[:10],
        "precision_errors": precision_errors[:10],
        "precision_warnings": precision_warnings,
        "blockers": blockers,
    }
