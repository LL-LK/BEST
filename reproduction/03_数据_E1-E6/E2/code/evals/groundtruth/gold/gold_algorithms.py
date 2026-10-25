# -*- coding: utf-8 -*-
"""evals.groundtruth.gold.gold_algorithms — E2 金标准手写算法层 (铁律载体)。

铁律 (docs/eval-E2-groundtruth.md §4.1): 锥搜角距、筛选谓词、排序、分页切片
全部在本文件用 ``math`` 手写实现 — **严禁 import 任何被测判定逻辑**
(``src.*`` 一律禁止; guard_no_src_imports.py 对本目录全部 .py 生效)。
为什么: GT 若抄被测代码的算法, 被测的 bug 会被 GT 原样复制, 两边"完美吻合",
实验静默失效。

消费方: gen_gold.py (编排层)。本文件只依赖标准库 + evals._data 数据字典
(哨兵阈值/豁免列是数据不是判定逻辑, E2 §4.4 唯一允许共享件)。

对外接口: ``angular_separation_arcsec()`` 角距; ``match_constraint()``
筛选谓词; ``sort_key()`` 混合排序键; ``paginate()`` 分页切片;
``page_hash()`` 页指纹; ``sig_digits()`` 有效位数; ``synthesize_rows()``
S 类回退合成; 另有 ``to_float()``/``is_sentinel()``/``row_key()``/
``resolve_column()`` 四个基础原语。

依赖与数据流: 输入只有场景声明 (纯字典) 与已落地快照, 全部离线;
产物是 gen_gold.py 编排出的金标准 JSON, 本文件自己不读网络也不写盘。

关键契约与不变量: **独立 oracle** —— 这里所有算法都用 math 手写, 严禁
import 任何被测判定逻辑 (src.* 一律禁止, 由 guard_no_src_imports.py 对
本目录全部 .py 机械守护); 未知约束算子必须抛错而不是返回 False, 否则  # 金标准算法只认这一份实现: 判定侧与被测侧共用会掩盖错误
场景声明写错算子名会静默变成"筛不出任何行"; 零跨实验 import, 唯一共享
件是 evals/_data 纯数据字典, 格式等价性由 evals/equivalence/ 断言守护。

陷阱与边界: ``haversine`` 公式与 src/crossmatch.py 同口径但**不共享代码**,
改一边必须手工同步另一边, 这是"独立实现"必须付出的代价, 也是它仍有
交叉验证价值的前提; ``row_key`` 与 canonical.row_key 格式一致是 M1 可比的
前提, 同样靠约定而非共享代码保证。  # 主键取自 canonical: 两侧同一把尺, M1 才不会假失配

白盒锚点: docs/eval-E2-groundtruth.md §4.1 (独立 oracle 铁律) / §5 (场景);
haversine 公式口径与 src/crossmatch.py:94-111 逐字核对一致 (独立实现, 不 import)。
"""
from __future__ import annotations

# 标准库: CSV 读盘口径的字典类型 / decimal 有效位数 / hashlib 页指纹 /
# haversine 数学 / JSON 序列化 (行键兜底) / 类型标注
import decimal
import hashlib
import json
import math
from typing import Any, Iterable, Optional

# 数据字典加载件 (纯数据: 哨兵阈值与豁免列 — E2 §4.4 唯一共享件)
from evals._data import load_null_sentinel


def to_float(value: Any) -> Optional[float]:  # 转不了数返 None: 缺测与测到零在 M1 上必须可区分
    """安全转 float (失败/空/非有限 → None; 不抛 — oracle 不做输入审判)。

    **NaN / ±Inf 一律判 None**, 与 canonical._as_float 同口径 (格式契约的一部分)。
    站点在真实回包里大量回字面量 ``nan`` (uss_dr1 一份快照 37077 格): 转得
    "成功"的 NaN 会让 ``nan == nan`` 恒假, 每格成对假失配, 且 M5 会把缺测
    读成有值 —— 比报 0.0 更坏的是它不报错。
    """
    if value is None or value == "":  # 浮点比较带容差: 严格相等会把 18.2 与 18.200000 判成两个数
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None  # NaN/Inf 不携带量值: 当缺测, 不当数字


def angular_separation_arcsec(ra1: float, dec1: float, ra2: float, dec2: float) -> float:
    """两个天球位置之间的大圆角距 (单位: 角秒) — 独立 haversine 实现。

    公式: a = sin²(Δdec/2) + cos(dec1)·cos(dec2)·sin²(Δra/2);
    分离角 = 2·asin(√a)。与 src/crossmatch.py:94-111 同公式口径 (2026-09-28
    逐字核对: radians 转换、min(1.0, √a) 防越界、degrees→×3600 全部一致)。
    sin²(Δra/2) 以 360° 为周期 → RA 跨 0–360 天然 wrap-safe; cos(dec) 因子  # 单位换算单向: 金标准只认一种口径, 不做双向猜测
    保证高赤纬精度 (不做平面天球近似)。
    """
    r1, d1, r2, d2 = map(math.radians, (ra1, dec1, ra2, dec2))  # 先转弧度: haversine 的三角函数吃弧度, 直接喂度会得出无意义的角距
    # 半角式 haversine: cos(dec1)·cos(dec2) 因子是高赤纬精度的来源,
    # 去掉它换成平面近似会在 dec→±90 时把角距严重算小
    a = (                                                                               # 拆成多行只为让 cos(dec) 因子单独可见, 不改变求值顺序
        math.sin((d2 - d1) / 2.0) ** 2  # 缺字段返 None 而非默认值: 缺测与测到零必须可区分
        + math.cos(d1) * math.cos(d2) * math.sin((r2 - r1) / 2.0) ** 2                # 高赤纬精度全靠这个因子: 换成平面近似会在 ±90° 把角距严重算小
    )
    # min(1.0, √a) 挡浮点溢出: 理论上 a ≤ 1, 但两星重合或赤纬相近时
    # 浮点累加可能算出 1.0000000000000002, asin 会抛 domain error
    return math.degrees(2.0 * math.asin(min(1.0, math.sqrt(a)))) * 3600.0


def _is_exempt_column(column: str, exempt: Iterable[str]) -> bool:  # 判据逐字对齐 canonical 侧那份
    """该列是否哨兵豁免列 —— **按后缀匹配** (2026-10-07 实测对齐 canonical 侧)。

    精确相等会漏掉带星表前缀的真实列 (``landolt_pmra`` / ``landolt_pmdec`` 在 1001 个
    注册列名里确实存在); 按第一个下划线剥离又会把 ``radial_velocity`` 剥成
    ``velocity`` 漏掉它自己。故逐个下划线切点各试一次。
    """
    if column in exempt:  # 精确形态先判: 含下划线的豁免名只能靠这条命中
        return True
    parts = str(column).split("_")
    return any("_".join(parts[index:]) in exempt for index in range(1, len(parts)))


def is_sentinel(column: str, value: Any) -> bool:
    """该格是否哨兵 (缺失) — 阈值判定 + 豁免列 (字典单点, 不硬编码)。"""
    number = to_float(value)                                                                    # 先转数: 哨兵阈值是数值口径, 文本格不参与判定
    if number is None:                                                               # 非数值格永不算哨兵: 强行转会把 reason 码之类脏值也塞进缺失桶
        return False
    sentinel = load_null_sentinel()  # 经 lru_cache 缓存: 改哨兵表须先清缓存或重启进程, 否则本进程仍读旧值
    if _is_exempt_column(column, sentinel["exempt_columns"]):  # 豁免列先判: 否则真实空值会被阈值当脏值清掉
        return False
    return number <= float(sentinel["threshold"])


def _pick_column(row: dict, logical: str) -> Optional[str]:
    """从一行里挑出该逻辑列的实际列名 (确定性: 多命中取字典序最小)。

    与 :func:`resolve_column` 同一条四级回退, 但**多一条硬排除**:
    ``inputobjs_*`` 一律不参与。那几列是**查询输入坐标** (proximity/锥查
    每一行都等于锥中心), 拿它当行位置会把整个结果集并成一行。
    12 张表实测的列名形态见 references/site-endpoints-and-interactions.md §10.1。
    """
    columns = sorted(row)  # 排序遍历: 表头顺序不是契约, 靠先到先得会让同一份数据两次算出不同主键
    for column in columns:
        if column.startswith("inputobjs_"):
            continue                                                        # 查询输入坐标不是源行位置
        if column == logical or column.endswith(f"_{logical}"):
            return column
    return None                                                              # 取不到即"不适用", 由调用方兜底


# 主键列的逻辑名单 (2026-10-04 对齐 src.models.BestSource.from_row 的 ID 别名支路):
# ``source_id`` 与 ``calibstars_id``。**故意不含裸 ``id`` / ``objid`` / ``obj_id``**:
# 那三个是 from_row 的兼容别名, 但按后缀匹配放进 oracle 会误命中别的语义列 ——
# 实测 gaia 回包里 ``gaia_dr3_18_solution_id`` 是**解算批次 ID** (1000 行只有 1 个
# 不同值; 实测值由 test/unit/meta/test_snapshot_facts_vs_docs.py 从快照重算钉住),
# 字典序又排在 ``gaia_dr3_18_source_id`` 前面, 取了它就等于拿重复 id 当主键。
# from_row 是逐键精确匹配 (kl in (...)), oracle 是按后缀扫全列, 两者风险面不同,
# 不能把名单照抄。stripe82 的 ``calibstars_id`` 是真主键 (27/27 唯一), 必须补。
# 这是**格式契约**而非共享代码: oracle 不得 import 被测逻辑, 故此处独立登记一份,
# 与 canonical 侧同名单、同判定顺序 (sorted 遍历, 多命中取字典序最小)。
_ID_LOGICAL_COLUMNS = ("source_id", "calibstars_id")


def _pick_id_column(row: dict) -> Optional[str]:
    """主键列的实际列名: 按 ``_ID_LOGICAL_COLUMNS`` 逐个后缀试 (排序遍历)。

    **口径与 ``src.models.BestSource.from_row`` 及 canonical 侧一致**
    (2026-10-04 对齐): ``source_id`` 与 ``calibstars_id``。只认 ``*_source_id`` 时,
    stripe82 (真实 id 列是 ``stripe82_calibstars_id``) 的 27 行会全部判"无主键"
    退化到坐标 —— 产品代码能取到而 oracle 取不到, 两侧不同尺。
    名单**不比照 from_row 的全部别名** (裸 ``id``/``objid``/``obj_id``): 那边是
    逐键精确匹配, 这边是按后缀扫全列, 宽泛别名会命中别的语义列 (见上方常量注释)。

    与 :func:`_pick_column` 同款确定性 (排序遍历, 多命中取字典序最小),
    ``inputobjs_*`` 的硬排除同样适用。
    """
    for column in sorted(row):  # 排序遍历: 表头顺序不是契约
        if column.startswith("inputobjs_"):
            continue                                                        # 查询输入坐标不是行标识
        for logical in _ID_LOGICAL_COLUMNS:
            if column == logical or column.endswith(f"_{logical}"):
                return column
    return None


def id_keys_unique(rows: list) -> bool:
    """这批行能不能用 id 当主键 —— 判据是**集合内唯一**, 不是"列存在"。

    与 evals.groundtruth.canonical.id_keys_unique 同判据 (格式契约的一部分, 但
    刻意不复用代码: oracle 不得 import 被测逻辑)。真实回包的反例见 canonical
    侧同函数的 docstring: ps1 的 ``ps1_source_id`` 既可能整列为空、也可能重复。
    """
    seen: set = set()
    for row in rows or ():
        sid = _pick_id_column(row)
        value = None if sid is None else row.get(sid)
        if value in (None, ""):
            continue
        if value in seen:
            return False
        seen.add(value)
    return True


def row_key(row: dict, coords_only: bool = False) -> str:
    """标准行集主键 (与 evals.groundtruth.canonical.row_key 同格式契约)。

    有 source_id 用之; 无则 (ra, dec) 量化到 9 位 (浮点表示安全精度);
    坐标也缺时整行排序 JSON 兜底。格式一致是 M1 行集可比性的前提
    (格式契约, 非共享代码 — 铁律: oracle 不得 import 被测逻辑)。

    2026-10-04: 列名解析从"只认裸名 + 两个硬编码主键名"改为按形态解析。
    真实回包实测 5 种列名形态, 其中 xpsp/dr3xpcorr 的主键是
    ``gaiaxp_photinfo_replenish_source_id`` —— 旧实现对它们恒判"无主键",
    整条单对象精确查询退化成 0 行。同日再对齐 ``calibstars_id`` (stripe82)。

    ``coords_only=True`` 由 :func:`id_keys_unique` 在结果集层判定后传下来:
    id 在集合内重复时用它当主键会让两行塌成一格, M2 拿 A 行期望比 B 行实际。
    """
    if not coords_only:
        sid_col = _pick_id_column(row)
        if sid_col is not None and row.get(sid_col) not in (None, ""):
            return str(row[sid_col])
    ra_col, dec_col = _pick_column(row, "ra"), _pick_column(row, "dec")
    ra = to_float(row.get(ra_col)) if ra_col else None
    dec = to_float(row.get(dec_col)) if dec_col else None
    if ra is None or dec is None:                                                             # 坐标缺一半就构不成键: 交给整行排序 JSON 兜底
        return "row:" + json.dumps(row, sort_keys=True, default=str, ensure_ascii=False)
    return f"{round(ra, 9):.9f},{round(dec, 9):.9f}"


def resolve_column(header: list[str], logical: str, explicit: Optional[str],  # 列名解析按显式 → 逻辑 → 前缀 → 后缀四级回退
                   catalog: str) -> Optional[str]:                              # 返回 None 而非抛错: 场景声明的逻辑列可能真不在这次快照表头里, 属不适用
    """列名解析: 显式名 > 裸名/带星表前缀名 > 任何以 _<logical> 结尾的列。

    L 类素材可能是裸列名 (ra/dec/source_id) 或站点前缀形态 (ps1_ra);
    场景声明用哪个形态都可以, 解析器双向兜底 (确定性: 取排序后首个命中)。
    """
    if explicit and explicit in header:                                                 # 显式声明优先于一切猜测: 场景已指名了列, 就不该被前缀匹配抢走
        return explicit
    # 先试两种最常见形态: 裸列名与当前星表前缀列名。顺序即优先级,
    # 显式声明赢了就轮不到它们, 避免同名歧义被前缀猜测抢走
    for candidate in (logical, f"{catalog}_{logical}"):
        if candidate in header:                                                         # 裸名与带前缀名依次试: 顺序即优先级, 两者都命中时以先到者为准
            return candidate
    # 兜底: 任意以 _<logical> 结尾的列 (如 dr3_ra、ps1_dec)。必须先排序
    # 再取首个, 否则命中哪一列取决于 CSV 的列序, 同一份数据两次生成
    # 可能得到不同 GT (违反 M7 确定性判据)
    for column in sorted(header):  # 后缀匹配要排序遍历: 表头顺序不是契约, 不能靠先到先得
        if column.endswith(f"_{logical}"):
            return column
    # 解析不出来返回 None 而非抛错: 场景声明的逻辑列名可能真的不在这次
    # 快照的表头里, 这是"该指标不适用", 由上层决定怎么判
    return None


def match_constraint(value: Any, op: str, target: Any) -> bool:  # 约束判定单点: 两侧共用一份, 口径漂移无从发生
    """列约束谓词 (equal/notequal/less/greater/between/in/contains)。

    闭区间端点取等 (E2 §5 #3); 数值对数值比较, 否则字符串 strip 后比较。
    """
    number, target_number = to_float(value), to_float(target)                            # 两侧都先转数: 约束判定是数值语义, 转不成立即退到字符串分支
    if op == "equal":
        # 两侧都能转数才按数值比, 否则退到字符串比: CSV 里 "187.5" 与 187.5
        # 是同一个值, 不走数值分支会被判不等
        if number is not None and target_number is not None:                     # 双侧都可转才走数值比: 单侧可转会把 "187.5" 与 187.5 判成不等
            return number == target_number
        return str(value).strip() == str(target).strip()
    if op == "notequal":
        # 取 equal 的反: 两边在"值缺失"上行为一致, 单独再写一遍必然
        # 出现两套判定, 这是 GT 与被测侧最易漂移的一处
        return not match_constraint(value, "equal", target)
    if op in ("less", "greater"):
        # 序关系必须两侧都是数: 字符串比大小会得到字典序结果 ("9" < "10"),
        # 那是完全不同的语义, 判它成立等于放行一个错筛选
        if number is None or target_number is None:  # 类型错一律判不满足: 让异常冒出去会让整批查询崩掉
            return False
        return number < target_number if op == "less" else number > target_number
    if op == "between":
        # 闭区间两端取等 (E2 §5 #3 的场景约定); 端点缺失返回 False 而不是
        # 放宽成单边比较, 缺失的场景声明不该悄悄改变判据
        low, high = to_float((target or {}).get("min")), to_float((target or {}).get("max"))
        if number is None or low is None or high is None:  # 端点缺失即不成立: 拿半截区间比大小会得出假结论
            return False
        return low <= number <= high
    if op == "in":
        # 成员判定两侧都 strip: 候选列表里的枚举码常带缩进或换行残留
        return str(value).strip() in [str(item).strip() for item in (target or [])]
    if op == "contains":
        # 子串包含 (多值列以逗号分隔的常见场景), 方向是 target 落在 value 里
        return str(target) in str(value)
    # 未知算子必须炸: 返回 False 会被上层读成"这行不满足条件", 场景
    # 声明里打错算子名会静默筛空整个数据集, 表现为"GT 少了很多行"
    raise ValueError(f"unknown constraint op: {op!r}")


def sort_key(value: Any) -> tuple:
    """混合排序键: 数值优先 (0, float, ''), 文本其次 (1, 0.0, text)。

    数值列出现空/哨兵时退化为文本参与比较, 不与真实数值混排造成 TypeError。
    """
    number = to_float(value)                                                                # 数值档与文本档必须分开: 混排会让排序结果与金标准对不上
    if number is not None:  # 数值档与文本档分开: 混排会让排序结果与金标准对不上
        # 首元素 0/1 是分组位: Python 比较元组先看首元素, 靠它把数值档与
        # 文本档彻底隔开, 否则 "(0, 5.0, '')" 与 "(1, 0.0, '')" 会在第二
        # 位上比较出数值 5 > 0 这种无意义的顺序
        return (0, number, "")
    # 第三元素恒为字符串, 与数值分支的 '' 占位同型, 避免两档在第三位
    # 撞类型 (str 与 str 才能比, 不会 TypeError)
    return (1, 0.0, str(value).strip())


def paginate(rows: list[dict], page_size: int) -> list[list[dict]]:  # 末页自然变短: 切片越界返空页, 与"真的没有数据"同形
    """分页切片: 每页 page_size 行; 末页可不满 (空行集 → 零页)。"""
    # range 步长即页大小, 末页自然可短: 这样切分的结果与 total/returned/
    # truncated 的自洽性交给 M4 判, 切片层不该自己去凑整页
    return [rows[start:start + page_size] for start in range(0, len(rows), page_size)]


def page_hash(page_rows: list[dict]) -> str:
    """页指纹: sha256(规范化 JSON)。序列化格式契约由 gold 的
    pagination.page_hash_algo 字段声明, 供 M4 侧复算 (格式契约, 非判定逻辑)。"""
    # sort_keys + 固定分隔符: 键序与空白不进指纹, 否则同一页数据换个 CSV
    # 列序就换指纹, M4 的"同页同指纹"会变成永假
    payload = json.dumps(page_rows, sort_keys=True, ensure_ascii=False, separators=(",", ":"))  # 键排序 + 无空格序列化: 指纹必须与书写顺序无关
    # utf-8 显式编码: 平台默认编码在 Windows 上不是它, ensure_ascii=False
    # 下的中文名会直接抛 UnicodeEncodeError, 指纹只在 Linux CI 跑得通
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def sig_digits(text: Any) -> int:  # 有效位数取十进制原串: 不用 float 再数, 尾数已丢
    """有效位数 (decimal.Decimal 统计; E2 M3c 精度判据的 GT 侧)。"""
    try:
        parsed = decimal.Decimal(str(text).strip())                    # 先取 str 再进 Decimal: 直接 Decimal(0.1) 拿到的是二进制展开的无限尾数
    except (decimal.InvalidOperation, ValueError):
        return 0
    return len(parsed.as_tuple().digits)


def synthesize_rows(spec: dict) -> list[dict]:
    """S 类回退: 场景内声明式合成 (快照缺失时的确定性兜底, 无随机)。

    支持 rows (显式行列表) 与 grid (确定性网格: const / base+inner_step /
    base+block_step+block_size 三种列模板)。回退产物在 gold 里记
    rows_source=scenario:synthesize, 与快照真值可区分。当前 17 个场景全部
    绑定已落地快照 (GT 不发明数据), 本函数保留给显式声明的无快照 S 类用例。
    """
    if "rows" in spec:
        return [dict(row) for row in spec["rows"]]
    # 只认 grid 一种模板: 未知 pattern 抛错而不是回退到 rows, 因为回退会
    # 生成"看起来像数据"的空行集, 让人以为快照里真的有这些行
    if spec.get("pattern") != "grid":
        raise ValueError(f"unsupported synthesize spec: {sorted(spec)}")
    # block_size 缺省等于 count (即整块一块), 让只声明 block_step 的场景
    # 也能表达"逐块递增", 无需重复写一遍总数
    count, block_size = int(spec["count"]), int(spec.get("block_size", spec["count"]))  # 合成行按 grid 展开: 快照生成与判定共用同一份行序
    rows: list[dict] = []                                                              # 合成结果按 grid 顺序累积: 顺序是 M7 确定性判据的一部分
    for index in range(count):                                                                # 行数只由 count 决定: 少声明一列不该改变行数
        row: dict[str, Any] = {}                                                         # 每行独立 dict: 共用同一对象会让所有行被最后一个模板覆盖
        if "id_template" in spec:
            # 主键列名可配 (id_column), 默认 source_id; 模板只暴露 {i} 一个
            # 变量, 保证第 i 行总能算出同一个值 (确定性)
            row[spec.get("id_column", "source_id")] = spec["id_template"].format(i=index)
        for column, template in (spec.get("columns") or {}).items():
            if "const" in template:
                row[column] = template["const"]
            elif "block_step" in template:
                # 块级递增: 整数除决定落在第几块, 同一块内所有行同值
                row[column] = template["base"] + (index // block_size) * template["block_step"]
            else:
                # 块内递增: 取模保证不会越出本块; inner_step 缺省 0 表示
                # 这列在块内是常量, 与 const 模板的差别只在"由模板生成"
                row[column] = template["base"] + (index % block_size) * template.get("inner_step", 0.0)
        rows.append(row)                                                                 # 逐行追加: 块级与块内模板的差别必须在追加前算完, 不做后处理
    return rows
