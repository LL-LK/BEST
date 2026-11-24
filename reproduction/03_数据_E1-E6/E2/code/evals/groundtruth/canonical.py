# -*- coding: utf-8 -*-
"""evals.groundtruth.canonical — 标准行集规范化 (任何输出面 → 同一把尺子)。

职责: 把 Skill 的四个输出面 (agent 工具信封 / 客户端结果 / CLI 落盘 CSV /
TAP 导出) 压成同一种"标准行集" (canonical row set), 供 E2 逐格对账 ——
只有先压到同一形态, 比的才是数据差异而不是序列化差异。

能力边界: 边界: 只做形态归一 (类型/前后缀/主键), **不评判**对错 (那是 metrics
的活); 哨兵语义字典读 ``evals/_data/null_sentinel.yaml`` 单点, 不在本文件复刻。

所属实验: E2 金标准一致性 (方案真值 docs/eval-E2-groundtruth.md §2 规范化层
与标准行集定义), 是 M1 行集、M2 字段、M5 状态三个指标的共同前置。

对外接口: ``row_key()`` 出行主键; ``canonical_rows()`` 逐格归一;
``from_envelope()``/``from_query_result()``/``from_csv()`` 分别接 A/B/C
三个输出面; ``key_set()`` 给 M1 的 P/R 提供比对单位; ``is_sentinel()`` 与
``normalize_value()`` 是 M2/M5 的判定原语。

依赖与数据流: 输入是三个输出面各自的原始行字典与落盘 CSV, 全部来自离线
快照回放 (不发真实请求, rate_limit 归零); 产物是内存里的标准行集, 随
E2 报告 JSON 落盘, 本文件自己不写文件。

关键契约与不变量: 归一是幂等的 —— 同一行归一两次结果必须相同, 否则
"拿 A 面比 B 面"会因归一顺序产生假差异; 哨兵值原样保留, 绝规成 null 或 0,
因为"缺失"与"零值"是两种语义 (M5 靠这个区分判状态); 无法解析的坐标
降级成整行 JSON 排序键而不是抛错, 规范化层不做判定。零跨实验 import,
唯一共享件是 ``evals/_data/`` 纯数据字典, 等价性由 ``evals/equivalence/``
断言守护。

陷阱与边界: 复合键只在行带 ``inputobjs_input_line`` 时启用 —— 单看
source_id 会把"同一颗星被两个输入行命中"误并成一行, 多输入 proximity  # 兼容裸名/带前缀两种列名: 星表导出方式不同, 两种都要认
查询会因此少算; 坐标量化到 9 位是浮点表示的安全精度 (度约 0.3mm), 再多
会把两颗真实不同的星并成一颗, 再少则同星两次回放对不上; 表头列名必须
单独返回 (``from_csv``), 因为缺列表头是 E2 的已知坑位, 归一到行集后就
看不出"没读进来"和"读进来是空"的区别。
"""
from __future__ import annotations

# 标准库: CSV 读盘 (utf-8-sig 兼容 BOM) / 路径 / 有限性判定 / 数值 rounding / 类型标注
import csv  # 缺列返空集而不是抛: 缺列与空表在 M1 上都要落成"无可对账"
import math  # isfinite: 判掉 NaN/Inf, 见 _as_float 的 docstring
from pathlib import Path
from typing import Any

# 本地: 哨兵数据字典 (唯一共享件 — 判定"这一格是缺失"的权威)
from evals._data import load_null_sentinel

    # 哨兵字典在导入期取一次: 阈值与豁免列在一次跑批内必须恒定, 每格现读
    # 既慢又会在半途读到被改的字典, 让同一份报告前后用两套阈值
_SENTINEL = load_null_sentinel()  # 导入期取一次: 阈值必须在一批内恒定, 半途读到被改的字典会让同一份报告用两套阈值


def row_key(row: dict, batch: bool | None = None, coords_only: bool = False,
            line_offset: int = 0) -> str:  # 主键唯一出口: 两侧不同尺会造出成对假失配
    """标准行集主键 (E2 §2): 批量匹配行用 (input_index, source_id) 复合键;
    其余有 source_id 用 source_id, 无则 (ra, dec) 量化到 9 位。

    ``coords_only=True`` 时**跳过 id** 直接走坐标键 —— 由 :func:`id_keys_unique`
    在**结果集层**判定后传下来。真实回包给了反例: ps1 的 ``ps1_source_id`` 在四份
    快照里整列为空, 在 ``live_ps1_ra359.5_dec0.0_r1800.0as`` (1000 行, 431 个非空)
    里却有 1 个值重复出现 2 次 —— "有 source_id 就用它"不成立, 重复 id 会让两行
    塌成同一主键, M2 拿 A 行的期望值比 B 行的实际值, 报出一串看着像"数据对不上"
    的假失配。

    复合键判定: ``batch`` 为真时行用 ``in<N>:`` 前缀, N 取 ``inputobjs_input_line``。
    **batch 是查询的属性, 不是行的属性** (2026-10-04 修正): 站点对锥搜响应
    同样回 ``inputobjs_input_line`` (单输入恒为 0), 靠"行里有没有这列"判批量
    会把**每一个锥搜结果集**都错判成批量行, 主键凭空多个 ``in0:`` 前缀, M1
    全量成对假失配。判据改为由调用方按查询显式传入。

    ``batch=None`` 保留"按行推断"的旧行为, 供不认识批量概念的调用方使用。
    复合键 (input_index, source_id) 的理由: 单看 source_id 会把"同一颗星被
    两个输入命中"误并成一行。浮点键统一保留 9 位: 再粗会并源, 再细会因浮点尾数对不上。
    量化到 9 位是浮点表示的安全精度 (度 ~ 0.3mm)。
    """
    input_line = row.get("inputobjs_input_line")  # 输入行号是最强主键: 一个输入坐标对应一行, 行号天然是分组键
    is_batch = (input_line not in (None, "")) if batch is None else batch
    if is_batch:                                                       # 批量分支: 复合键前缀来自查询判据, 不来自行内列
        # 行号规范化: CSV 文本 "0" 过 normalize_value 成 float 0.0 — 复合键
        # 统一取整数字形 (in0, 非 in0.0), 与 gold 的 input_index 口径一致。
        line_key = str(input_line)  # 先原样留着: 只有能判定为整数时下面才归一
        try:
            if float(input_line) == int(float(input_line)):  # 指纹只认主键序列: 行序变了就是变了, 不做集合化
                line_key = str(int(float(input_line)) - line_offset)  # 去 .0 尾巴并按服务端基准归位 (见 batch_line_offset)
        except (TypeError, ValueError):
            pass
        if not coords_only:                                            # id 不可用时直接跳到坐标键, 不拿重复 id 当主键
            for key in ("source_id", "ps1_source_id"):  # 主键回退一: 带前缀与裸名两种形态都要认
                value = row.get(key)  # 两种列名都试: 实测里带前缀与裸名都出现过
                if value not in (None, ""):
                    return f"in{line_key}:{value}"
            sid = _source_id_of(row)  # 形态解析: dr3xpcorr/xpsp 的主键列是共享表前缀, 硬编码两个名字会漏
            if sid is not None:
                return f"in{line_key}:{sid}"
        ra, dec = _coord_pair(row)  # 坐标列同样走形态解析: 真实回包里裸名 ra/dec 极少
        if ra is None or dec is None:  # 与非批量分支同口径: 坐标取不到就整行兜底, 不在这里崩
            return _whole_row_key(row)
        return f"in{line_key}:{round(ra, 9):.9f},{round(dec, 9):.9f}"
    if not coords_only:                                                # id 在本结果集内重复时整批跳过 id 分支
        for key in ("source_id", "ps1_source_id"):  # 主键回退二: 都没有才用坐标兜底, 且必须有限值
            value = row.get(key)  # 行号与列名都缺时, source_id 比坐标更抗量化误差
            if value not in (None, ""):
                return str(value)
        sid = _source_id_of(row)  # 形态解析: 同上, 覆盖共享表前缀形态
        if sid is not None:                                                # 形态解析到主键就用它
            return str(sid)
    ra, dec = _coord_pair(row)                                          # 坐标列按形态解析, 排除 inputobjs_*
    if ra is None or dec is None:  # 坐标缺一半就构不成键, 交给整行 JSON 兜底
        return _whole_row_key(row)  # 坐标也缺: 用整行排序后的 JSON 兜底 (去重键的最后防线)
    # 量化到 9 位: 浮点尾数噪声会让同一坐标两次回放算出不同的键, 位数再多
    # 又会把真差 0.3mm 以内的两颗星并成一颗
    return f"{round(ra, 9):.9f},{round(dec, 9):.9f}"


def _whole_row_key(row: dict) -> str:
    """坐标与主键都取不到时的最后兜底: 整行排序后的 JSON。"""
    import json

    # sort_keys 保证同一行无论字典插入顺序如何都得到同一个键; default=str
    # 让嵌套的非 JSON 原生对象也能落进键里, 否则这一行会直接抛 TypeError
    return "row:" + json.dumps(row, sort_keys=True, default=str, ensure_ascii=False)


def _as_float(value: Any) -> float | None:  # 转不了数返 None 而不是 0.0: 缺测与测到零必须可区分
    """安全转 float (失败/空/非有限 → None; 不抛 — 规范化层不做判定)。

    **非有限值 (NaN / ±Inf) 一律判 None**, 这是 2026-10-04 真实回包逼出来的:
    站点在大量幅值与误差列里回字面量 ``nan`` (uss_dr1 一份快照 37077 格,
    smss_dr4 338 格, ps1@ra359.5 45 格)。``float('nan')`` 转得"成功", 于是
    NaN 会一路流进比对层 —— 而 ``nan == nan`` 恒为 False, 每格都成对假失配,
    M5 还会把"缺测"读成"有值"。比"报 0.0"更坏的是它**不报错**。
    """
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None  # NaN/Inf 不携带量值: 当缺测处理, 不当数字


# 主键列的判定顺序: 裸名优先, 再退到任意同后缀列。**必须排除 inputobjs_*** ——
# 那是查询输入坐标 (每行都等于锥中心), 拿它当主键会把整个结果集并成一行。
_SID_SUFFIXES = ("_source_id", "_calibstars_id")                       # 主键列后缀: 裸名与任意 <表>_<后缀> 两种形态都认
_COORD_SUFFIXES = ("_ra", "_dec")                                    # 坐标列后缀; 12 张表实测形态见 reference §10.1


def _pick_column(row: dict, suffixes: tuple[str, ...]) -> str | None:
    """从一行里挑出第一个命名形态命中的列 (确定性: 多命中取字典序最小)。

    只认三种形态: 裸名 (``ra``)、任意 ``*_ra`` 前缀名 (``ps1_ra`` /
    ``gaiaxp_photinfo_replenish_ra``)。这覆盖 12 张表实测出的坐标列形态 ——
    见 references/site-endpoints-and-interactions.md §10.1。解析不到返回 None,
    由调用方决定"记不可用"还是"走兜底", 本函数不猜。
    """
    columns = sorted(row)  # 排序遍历: 表头顺序不是契约, 不能靠先到先得 (否则同一份数据两次算出不同主键)
    for column in columns:                                             # 逐列试后缀; 排序遍历保证确定性
        if column.startswith("inputobjs_"):
            continue                                   # 查询输入坐标不是源行位置, 见上方说明
        for suffix in suffixes:
            if column == suffix.lstrip("_") or column.endswith(suffix):
                return column
    return None


def _source_id_of(row: dict) -> Any:
    """该行的主键值; 取不到返回 None (调用方据此决定回退到坐标键)。

    **口径与 ``src.models.BestSource.from_row`` 的 ID 别名支路对齐**
    (2026-10-04): 那边的权威名单含 ``calibstars_id``。此前 oracle 只认
    ``*_source_id``, 于是 stripe82 (真实 id 列是 ``stripe82_calibstars_id``)
    的 27 行主键全部返回 None、退化到坐标对 —— **产品代码能取到而 oracle 取不到**,
    两侧不同尺, M1 会报出一串看着像"数据对不上"的假失配。

    **名单不比照 from_row 的全部别名** (``id`` / ``objid`` / ``obj_id``): 那边是
    逐键精确匹配, 这边是按后缀扫全列, 宽泛别名会命中别的语义列 —— 实测
    gaia 回包的 ``gaia_dr3_18_solution_id`` 是解算批次 ID (1000 行只有 1 个
    不同值, 实测值见 test/unit/meta/test_snapshot_facts_vs_docs.py), 字典序又排在
    ``*_source_id`` 前面, 取了它等于拿重复 id 当主键。

    排序遍历带来的确定性不变 (多命中取字典序最小), 同一结果集两次跑批仍得到
    逐字节相同的主键。
    """
    column = _pick_column(row, _SID_SUFFIXES)                         # 解析不到即 None, 由调用方兜底
    if column is None:                                                 # 该行没有主键列: 返回 None 让调用方走坐标兜底
        return None
    value = row.get(column)                                            # 按解析出的真列取值
    return None if value in (None, "") else value


def _coord_pair(row: dict) -> tuple[float | None, float | None]:
    """取该行的 (ra, dec); 任一取不到即返回 (None, ...) 让调用方走兜底。"""
    ra_col = _pick_column(row, ("_ra",))
    dec_col = _pick_column(row, ("_dec",))
    if ra_col is None or dec_col is None:                              # 坐标列解析不到即整对不可用: 不猜
        return None, None
    return _as_float(row.get(ra_col)), _as_float(row.get(dec_col))


def _is_nonfinite_text(text: str) -> bool:  # 与 _as_float 同源的二分: 转不动 vs 转得动却非有限
    """该文本是不是「能转成 float 但结果非有限」的数值字面量 (``nan`` / ``inf``)。

    :func:`_as_float` 把「转不成数」与「转得动却非有限」**都**返 ``None``,
    而 :func:`normalize_value` 必须把两者分开: 转不成数的是 ID / reason 码
    那类真文本 (原样保留), 转得动却非有限的是站点回包里的缺测哨兵
    (``nan`` / ``inf``), 归 ``None``。不分开, 字面 ``nan`` 就会以**文本**
    形态漏进输出列 —— 判据层读到的只是「一个解析不了的字符串」, 精度记
    0 位有效数, 报出来看着像被测对象降了精度, 而真相是**这一格没有值**。

    与哨兵 (``-1003.87…`` / ``99.0``) 分流: 哨兵是**有限**的占位数, 归一
    层按契约原样保留 (M5 靠它区分「缺失」与「零值」); 本函数只管非有限。
    """
    try:
        return not math.isfinite(float(text))
    except (TypeError, ValueError):
        return False  # 转不成数即真文本列: 交 normalize_value 原样保留, 不当缺测


def _is_exempt_column(column: str) -> bool:  # 豁免判定单点: 两侧各抄一份, 判据必须逐字一致
    """该列是否哨兵豁免列 (字典单点, 不硬编码)。

    **按后缀匹配, 不只精确相等** (2026-10-07 实测对齐): 豁免名里 ``radial_velocity``
    本身含下划线, 而回包列名带星表前缀 (``landolt_pmra`` / ``landolt_pmdec`` 是
    1001 个注册列名里真实存在的两列)。只做 ``column in exempt`` 时前缀形态全部漏判,
    那些列里合法的负自行运动会落进阈值桶被当成脏值清掉; 只做 ``split("_")[0]``
    的剥离则会把 ``radial_velocity`` 剥成 ``velocity`` 反而漏掉自己那一条。
    故逐个下划线切点各试一次 —— 命中任一即豁免。
    """
    exempt = _SENTINEL["exempt_columns"]
    if column in exempt:  # 精确形态先判: 绝大多数列走这条, 且含下划线的豁免名只能靠它
        return True
    parts = str(column).split("_")
    # 逐个切点试后缀: landolt_pmra -> pmra, ps1_radial_velocity -> radial_velocity
    return any("_".join(parts[index:]) in exempt for index in range(1, len(parts)))


def is_sentinel(column: str, value: Any) -> bool:  # 哨兵判定在此单点: 散落的阈值会让两层口径漂移
    """该格是否哨兵 (缺失) — 阈值判定 + 豁免列 (字典单点, 不硬编码)。"""
    number = _as_float(value)  # 先转数再谈阈值: 阈值是数值口径, 文本格不参与判定
    if number is None:  # 非数值格永不算哨兵: 强行转会把脏值也塞进"缺失"桶
        # 非数值格 (如 reason 码) 永远不算哨兵: 阈值是拿数字比的, 强行 str→float
        # 会把无法解析的脏值也塞进"缺失"桶, 掩盖真正的脏数据
        return False
    if _is_exempt_column(column):  # 豁免列先于阈值判: 否则真实空值会被当成脏值清掉
        # 豁免列: 这些列天然可以为 0 (计数/序号类), 0 在这里是真值不是缺失
        return False
    # 用 <= 而非 ==: 解析失败的占位值通常落在阈值以下, 精确相等会漏掉它们
    return number <= float(_SENTINEL["threshold"])


def normalize_value(column: str, value: Any) -> Any:
    """单格规范化: 字符串 strip; 数值转 float; 哨兵保留原值 (不抹零)。

    E2 §6 M2: 字符串/ID 经 strip + 去零填充 + 大小写归一后精确相等;
    数值字段转 float 后按 GT 容差比对。哨兵值**原样保留** — 把它规成
    null 或 0 都会掩盖"缺失 vs 零值"的语义区分 (M5 的判据)。

    **非有限字面量 (``nan`` / ``inf``) 归 None** (见 :func:`_is_nonfinite_text`):
    它们既不是哨兵也不是真值, 而是站点明写的"这一格没有数"。归一层是
    唯一该收口的地方 —— 上游 transport 与行模型按契约保留原始形态
    ("哨兵/空串原样才是真实回包形态"), 下游判据层只该判不该治。让它以
    文本形态流下去, M3 会读到"解析不出的字符串"并记 0 位有效数, 把
    **缺测**误报成**降精度** (实测: boundary_wrap_ra 的 ps1_rpsf)。
    """
    if value is None:  # None 保持 None: 换成别的形态会让 M5 再也分不出缺失与零值
        return None
    # bool 被显式排除: Python 里 bool 是 int 的子类, 不挡的话 True 会变成 1.0,
    # 把"是/否"列悄悄变成数值列, M2 比对时再也分不出它原本是布尔
    if isinstance(value, (int, float)) and not isinstance(value, bool):  # bool 不当数值归一: True 变成 1.0 会污染后续比较
        number = float(value)
        # 真 float NaN/Inf 走同一条收口: 行模型若已把字面 nan 转成浮点,
        # 放过它等于让 nan == nan 恒假 → M2 每格成对假失配且不报错
        return number if math.isfinite(number) else None
    text = str(value).strip()  # 文本分支统一去空白: 带空格的 ID 与不带的是同一件事
    if text == "":
        return None
    if _is_nonfinite_text(text):  # 先于哨兵判定: nan 不是哨兵, 是缺测
        return None
    number = _as_float(text)  # 转通了才可能走数值分支, 否则原样当字符串返回
    # 哨兵走字符串分支原样返回: 归一成 float 会让 M5 分不出"缺失"与"零值"
    if number is not None and not is_sentinel(column, text):  # 哨兵保持原样不归一: 归一成数字等于把缺测变成可比的假值
        if _loses_precision_as_float(text):
            return text          # 超 2^53 的整数字面量保持字符串: 见 _loses_precision_as_float
        return number
    return text


# float 能精确表示的整数上界 (2^53)。超过它的整数字面量一旦转 float, 末几位就没了
_INT_EXACT_LIMIT = 2 ** 53                                             # float 能精确表示的整数上界


def _loses_precision_as_float(text: str) -> bool:
    """该文本是不是"转成 float 就会丢精度"的整数字面量。

    真实回包里的 Gaia 系主键是 19 位十进制整数 (如
    ``gaia_dr3_18_source_id=4512921183874236032``), 超过 float 的精确整数上界
    2^53≈9.007e15。转成 float 之后末几位被抹掉, 于是
    ``4512921183874236032`` 变成 ``4.512921183874236e+18`` —— **同一条记录在两侧
    算出两个不同主键**, M1 报成对假失配, 而且这种失配看上去像"数据对不上"。
    references/data-formats.md §5 已把这条列为标识符列的硬要求, 归一层此前漏了。
    判据只看形态: 纯整数字面量 (无小数点/指数) 且绝对值超上界。
    """
    body = text.lstrip("+-")
    if not body.isdigit():                                 # 非纯整数 (有小数点或指数) 不走这条判据
        return False
    return abs(int(body)) > _INT_EXACT_LIMIT


def canonical_rows(rows: list[dict]) -> list[dict]:  # 逐列归一: 归一口径与判定口径必须同一份
    """行字典列表 → 标准行集 (逐格过 normalize_value, 保持原列名)。"""
    return [
        {column: normalize_value(column, value) for column, value in row.items()}  # 逐列走同一入口: 归一口径与判定口径必须是同一份
        for row in rows or ()  # or () 兜 None: 空输入回空行集, 不抛
    ]


def from_envelope(envelope: dict) -> list[dict]:  # 信封取值: rows 在 data 之下, 兼容 data 直接是列表的旧形态
    """A 面: ToolResult.to_dict() 信封 → 标准行集 (取 data 段行列表)。"""
    data = (envelope or {}).get("data") or {}
    # data 段有两种形态: 结构化字典 (带 rows) 或裸行列表, 都要能接住 ——
    # 形态由上游调用方决定, 这里不假设其中一种
    rows = data.get("rows") if isinstance(data, dict) else data
    return canonical_rows(rows or [])


def from_query_result(result: Any) -> tuple[list[dict], dict]:
    """B 面: BestQueryResult → (标准行集, 信封字段)。

    信封字段 (total/truncated/returned) 单独返回 — E2 M4 的三元组对账
    消费它们, 不与行集混放。
    """
    rows = []  # 逐源展开: 一个结果对象可能含多个源, 行集必须先合成一张才有主键可比
    for source in getattr(result, "sources", None) or ():
        # raw_data 是数据行本体; 浅拷一份再补 source_id, 直接改原对象会污染
        # 被测系统自己的结果对象, 让它后面再判一次时看到被评测改过的数据
        raw = dict(getattr(source, "raw_data", {}) or {})
        # setdefault 而非直写: raw_data 里若已带 source_id, 那是数据自带的身份,
        # 覆盖它就等于用"第几个源"冒充"源里的主键"
        raw.setdefault("source_id", getattr(source, "source_id", None))  # raw 里补 source_id: 导出侧按原始列取值, 补了才不会丢
        rows.append(raw)  # 存的是拷贝: 后补的列不回写被测对象, 判分才不被自己污染
    # 信封字段与行集分开返回: M4 判的是 total/returned/truncated 三者自洽,
    # 混进行集后这三列就会参与逐格比对, 把计数差异算成字段差异
    envelope = {  # 信封三计数原样带出: M4 判的就是它们对不对得上
        "total_count": getattr(result, "total_count", None),
        "returned_count": getattr(result, "returned_count", None),
        "truncated": getattr(result, "truncated", None),
        "success": getattr(result, "success", None),
        "error_code": getattr(result, "error_code", None),
    }
    return canonical_rows(rows), envelope


def from_csv(path: str | Path) -> tuple[list[dict], list[str]]:  # CSV 入口只读: 判定层绝不写盘, 快照必须保持只读
    """C 面: CLI 落盘 CSV → (标准行集, 表头列名表)。

    读盘口径: utf-8-sig (兼容 BOM); 空串保持为空 (哨兵/空值的区分在
    normalize_value)。表头单独返回 — 缺列表头是 E2 的已知坑位 (M2 判据)。
    """
    path = Path(path)  # 统一成 Path: 传字符串与传 Path 走同一条开文件路径
    # utf-8-sig 而非 utf-8: 落盘 CSV 常带 BOM, 用 utf-8 读会把 BOM 吃进第一列名,
    # 于是第一列永远对不上, 表现为"少了一列数据"这种看不懂的差异
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)  # 按表头映射取值: 列序变化不该影响取列
        # fieldnames 可能为 None (空文件), 这时表头就是"缺失"这一事实本身,
        # 交给 M2 去判, 不能在读盘层就替它补一个空列表
        header = list(reader.fieldnames or [])  # 空文件给空表头: "缺失"这个事实要如实传下去判
        rows = [dict(row) for row in reader]  # 转成普通 dict: DictRow 行为与 dict 不同, 归一层只认 dict
    return canonical_rows(rows), header


def batch_line_offset(rows: list[dict]) -> int:
    """服务端 ``inputobjs_input_line`` 的基准偏移 (转成场景的 0-based 输入序号)。

    真实抓取 (2026-10-04, ``live_ps1_proximity_n3_5d2580ec``): 三个输入点回显
    ``input_line`` = 1/2/3 —— **1-based**; 而场景的 ``inputs`` 是 0-based 序列,
    oracle 拼主键用的也是 0-based。不归一就会整体错位一格 (``in0`` 对上 ``in1``),
    M1 报成"行集对不上"而看不出是基准问题。

    判据取**集合内最小行号**: ≥1 即认定服务端是 1-based (偏移 1), 出现 0 即认定
    0-based (偏移 0)。这样两种素材都对, 不把某一侧的真实约定写死成常量。
    与 :func:`id_keys_unique` 同理: 基准是**结果集**的属性, 逐行函数看不到集合。
    """
    lines = []
    for row in rows or ():
        raw = row.get("inputobjs_input_line")
        number = _as_float(raw)                       # CSV 文本 "1" 会过归一成 float 1.0
        if number is not None:
            lines.append(number)
    return 1 if lines and min(lines) >= 1 else 0


def id_keys_unique(rows: list[dict]) -> bool:
    """这批行能不能用 id 当主键 —— 判据是**集合内唯一**, 不是"列存在"。

    2026-10-04 真实回包给出的反例: ps1 的 ``ps1_source_id`` 在四份快照里整列为空,
    在 ``live_ps1_ra359.5_dec0.0_r1800.0as`` 那份 (1000 行, 431 个非空) 里却有
    **1 个值重复出现 2 次**。
    E2 §2 原写「有 source_id 用 source_id, 无则 (ra,dec)」, 但"有"不等于"唯一":
    重复 id 会让两行塌成同一个主键, 于是 M2 拿 A 行的期望值去比 B 行的实际值,
    报出一串看似"数据对不上"的假失配。
    所以主键降级必须由**结果集**决定, 而 ``row_key`` 是逐行函数看不到集合 ——
    判据落在这里, 调用方把结论传下去。
    """
    seen: set[str] = set()
    for row in rows or ():
        sid = _source_id_of(row)
        if sid is None:
            continue                                   # 没 id 的行走坐标键, 不参与唯一性判定
        if sid in seen:
            return False                               # 第二个同 id 即判不唯一
        seen.add(sid)
    return True


def key_set(rows: list[dict], batch: bool | None = None) -> set[str]:
    """标准行集 → 主键集合 (M1 行集 P/R 的比对单位)。

    ``batch`` 由调用方按**查询**传入 (见 :func:`row_key` 的说明): None = 按行
    推断的旧行为。oracle 侧从场景的 ``inputs`` 算, 这边从 run_e2 传下来,
    两边同一个来源才谈得上"同一把尺"。id 唯一性由 :func:`id_keys_unique` 在本函数
    内部按结果集判定, 两边同一判据。
    """
    coords_only = not id_keys_unique(rows)   # 结果集内 id 有重复即整批走坐标键
    line_offset = batch_line_offset(rows)   # 服务端 input_line 的基准 → 场景的 0-based 序号
    return {row_key(row, batch=batch, coords_only=coords_only, line_offset=line_offset)
            for row in rows}
