# -*- coding: utf-8 -*-
"""evals.ablation.harness.support — E5 装配层共享的小工具 (哨兵/数值/行集/哈希)。

能力边界: 只放**无状态纯函数** — 哨兵判定、安全数值转换、行内取列、
大圆角距、内容寻址哈希。抽成独立模块的理由: adapters.py (三个工具面) 与
run_batch.py (回放传输层) 都要用同一套口径, 互相导入会成环, 放中立载体后两方
单向依赖本模块 — 与 evals/paths.py 的分拆理由同款。

**零跨实验 import**: 只 import evals/_data 的纯数据字典 (铁律 6 开的唯一口子),
不 import 其它实验的代码, 也不自己锚哨兵表路径/解析 yaml —— 自建读法会绕掉
SSOT 的三键校验与批内缓存; 与 E2 canonical 的哨兵/主键口径**无等价性断言** —
evals/equivalence 守护的是哨兵**字典单点** (禁各处硬编码), 不比对两边的**判据等价性**。

所属实验: E5 基线与消融 (30 任务 × 10 系统 + sham, ScriptedLLM 离线跑;
成功率 = ScriptedLLM 跑通率而非模型能力), 方案真值 docs/eval-E5-baseline-ablation.md
§6.3 (结果一致率) / §13 (哨兵坑位)。本模块是 E5 的**口径底座**: 哨兵判定、
行内取列、角距、参数合法域在这里定一次, 三个工具面与回放层共用同一套答案。

对外接口: is_sentinel_value (哨兵判定); to_float /
column_of / coord_of (安全取值); haversine_arcsec (大圆角距, 与 GT oracle 同公式
不同代码); stable_hash (内容寻址); illegal_param_reason (参数预检, A1 消融的
对照口径); SENTINEL_EXEMPT / MAX_PAGE_SIZE (豁免列与上限常量)。

依赖与数据流: 输入 = evals/_data/null_sentinel.yaml (哨兵阈值与豁免列, 唯一共享件,
经 load_null_sentinel 读: 三键校验 + lru_cache) + 调用方传来的行字典与参数;
产物全是返回值, 本模块不落盘、不读快照。

关键契约与不变量: 离线回放 —— 全部是纯本地计算, 不接真实模型、不打真实站点;
零跨实验 import —— 唯一共享件是 evals/_data/ 纯数据字典 (evals/equivalence 的
哨兵守卫逐条核对"实验代码不得自带哨兵读法与豁免列字面量"), 与 E2 canonical 的
哨兵/主键**判据等价性无断言**;
纯函数 — 无随机、
无时间、无全局可变状态, 同一输入必得同一输出, 这是轨迹指纹能逐字节一致的前提;
缺文件即抛 (哨兵字典缺失不许回落成默认值, 阈值猜错会让整批取数门失真)。

陷阱与边界: 哨兵豁免列 (pmra/pmdec/radial_velocity) 是**带符号的真实物理量**,
"数值 ≤ 阈值即缺失"对它们是错的 — 早先按统一规则判过, 把真实自行速度当成缺失
剔除, 结果整行被丢; 列名要剥到裸形再比豁免表 (回包里既有 ps1_ra 也有 ra);
haversine 的 min(1.0, sqrt(a)) 不是随手加的防抖 — 浮点误差会让 a 略大于 1,
asin 直接抛 ValueError, 边界角距 (正好等于半径) 必须靠它才判得进去;
illegal_param_reason 只在 param_validation=true 的系统上调用, A1/B2a/B2b 旁路
— 非法参数原样下发正是 A1 要量的滑坡, 预检一旦到处生效就把消融抹平了。

白盒锚点: docs/eval-E5-baseline-ablation.md §6.3 (结果一致率) / §13 (哨兵坑位);
evals/_data/null_sentinel.yaml (阈值与豁免列的权威); src/protocol.py (两阶段 URL)。
"""
from __future__ import annotations

# 标准库: 内容寻址哈希 / 数学 (haversine) / 类型标注
import hashlib
import json
import math
from typing import Any, Optional

# 跨实验: 唯一被允许的共享件是 evals/_data 纯数据字典 (铁律 6 开的口子);
# 走它的 load_null_sentinel 而非本地锚路径 + 自己 safe_load: 后者没有三键校验
# (少一个键照样跑) 也没有 lru_cache (跑批中改表会让 E5 数值漂而 E2/E3/E4 不动)
from evals._data import load_null_sentinel

# 哨兵豁免列 (带符号真实物理量, 不参与"低于阈值即缺失"判定)
SENTINEL_EXEMPT = frozenset(load_null_sentinel()["exempt_columns"])  # 读字典而非抄字面量: 抄一份则生产/字典加列时 E5 静默沿用旧集, 把真物理量当脏值清掉


def _is_exempt_column(column: str) -> bool:
    """该列是否哨兵豁免列 —— **逐个下划线切点各试一次**, 不按第一个下划线剥离。

    旧实现取 ``split("_", 1)[-1]``: 对 ``landolt_pmdec`` 正确 (剥成 pmdec), 但把
    ``radial_velocity`` 剥成 ``velocity`` —— 豁免名单里那条**自己漏判**, 于是
    合法的大负视向速度会被阈值当成哨兵清掉。豁免名含下划线是既定事实 (名单里就有),
    剥离法就不能成立。
    """
    if str(column) in SENTINEL_EXEMPT:  # 精确形态先判: 含下划线的豁免名只能靠这条命中
        return True
    parts = str(column).split("_")
    # landolt_pmdec -> pmdec; ps1_radial_velocity -> radial_velocity
    return any("_".join(parts[index:]) in SENTINEL_EXEMPT for index in range(1, len(parts)))


def is_sentinel_value(column: str, value: Any, threshold: float) -> bool:
    """哨兵判定: 数值 ≤ threshold 且列不在豁免表 (与 evals/_data 字典同口径)。"""
    # 空值不算哨兵: "没测到"与"测到的是 -999"是两回事, 混判会让空值统计失真
    if value in (None, ""):  # None 与空串都算缺测: 站点两种形态都出现过
        return False
    try:
        number = float(value)  # 强转一次, 后面只比数值: 文本形态的 -999 也要被阈值抓到
    except (TypeError, ValueError):  # 转不了数就当缺测: 非数值列不该被阈值判成脏值
        # 不可转数值的列 (如 source_id) 本来就不参与哨兵判定, 不算误判
        return False
    if _is_exempt_column(column):  # 豁免列在阈值之前查: 带符号物理量低于阈值也是合法观测
        return False
    # ≤ 而非 <: 阈值本身 (正好 -999.0) 也是哨兵, 漏判它整列就保不住
    return number <= threshold


def to_float(value: Any) -> Optional[float]:
    """安全转 float (空/不可解析 → None)。"""
    # 空值先短路: float(None) 与 float("") 都抛, 但语义上是"没有值"不是"解析失败"
    if value in (None, ""):  # 空值直接返 None 而不是 0.0: 缺测与测到零必须可区分
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        # 返 None 而不是 0.0: 调用方据此判"该值不可用", 填 0 会变成真值参与计算
        return None


def column_of(row: dict, name: str) -> Any:
    """行内取列: 依次尝试限定形 / 前缀形 / 裸形 (站点 showcol 三种同源形态)。"""
    # 四种候选一次排好: 限定名、点号换下划线形、点号后的裸名、下划线后的裸名
    for key in (name, name.replace(".", "_"), name.split(".")[-1], name.split("_", 1)[-1]):  # 四种列名形态都试: 导出方式不同, 认一种会让整列读空
        # 空串与 None 一律当"取不到": 混进返回值会让下游把它当真实空测光
        if key in row and row[key] not in (None, ""):  # 四种列名形态都取不到才算缺, 少认一种就会让整列读空
            return row[key]
    return None


def coord_of(row: dict) -> tuple[float, float]:
    """行的 (ra, dec) (全限定名与裸名两种形态; 缺失按 0.0 兜底)。"""
    # or 0.0 兜底: 坐标缺失的行仍要参与排序/输出, 不能让整条流在此断掉;
    # 代价是 (0,0) 不在真实天区, 锥形检索会自然把它滤掉, 不会伪装成有效结果
    ra = to_float(row.get("ps1_ra") or row.get("ra")) or 0.0  # 拿不到坐标才回落 0.0: 有值时以值为准
    dec = to_float(row.get("ps1_dec") or row.get("dec")) or 0.0  # 与赤经同样兜底: 缺纬度的行不能在此断流
    return ra, dec


def haversine_arcsec(ra1: float, dec1: float, ra2: float, dec2: float) -> float:
    """大圆角距 (角秒) — 独立实现 (与 GT oracle 同公式不同代码, 互为对账)。"""
    # 先转弧度: haversine 的三角函数吃弧度, 拿角度算会得到毫无意义的数
    r1, d1, r2, d2 = map(math.radians, (ra1, dec1, ra2, dec2))  # 四角一次性转弧度: 后面全是弧度制运算, 混用角度必错
    # 半角公式: sin²(Δδ/2) + cosδ1·cosδ2·sin²(Δα/2); 数值上比半正矢式更稳
    a = (math.sin((d2 - d1) / 2.0) ** 2  # 半角公式第一项: 纬度差的正弦平方
         + math.cos(d1) * math.cos(d2) * math.sin((r2 - r1) / 2.0) ** 2)  # 第二项: 两纬余弦相乘, 再乘赤经差的正弦平方
    # min(1.0, ...) 是必需的去抖: a 是 sin²cos² 形式, 浮点误差能让它略大于 1,
    # asin 随即抛 ValueError; 边界角距 (正好等于半径) 也只有这样才判得进去
    return math.degrees(2.0 * math.asin(min(1.0, math.sqrt(a)))) * 3600.0


def stable_hash(payload: Any) -> str:
    """规范化 JSON 的 sha256 (data_hash 口径; 与 src/ai_tools._data_hash 同形)。"""
    # sort_keys 是稳定性的关键: 不排序的话字典插入序一变哈希就变, 指纹立刻不稳
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)  # 键排序保证同一内容同一哈希: 插入序一变指纹就飘
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


# 参数合法域 (src/scripts/guards.py 的同口径精简; ra [0,360) / dec [-90,90] /
# radius (0,18000] / page_size ≤ MAX_FETCH_PAGE_SIZE=10000)
MAX_PAGE_SIZE = 10000  # 页长上限与协议层常量对齐, 不在此另立一套口径


def illegal_param_reason(args: dict) -> Optional[str]:
    """参数预检 (guards.py 合法域的精简同语义版); 合法返 None, 非法返理由串。

    只在 ``param_validation=true`` 的系统上调用 (B3); A1/B2a/B2b 旁路 —
    非法参数原样下发正是消融要量的滑坡 (E5 §4 A1 行)。
    """
    # 先转 float 再判界: 入参可能是字符串形态, 不转会漏判一半的越界
    ra, dec = to_float(args.get("ra")), to_float(args.get("dec"))  # 先统一转数值: 入参可能是字符串形态, 不转会漏判越界
    radius = to_float(args.get("radius_arcsec"))  # 半径同转: 三个参数量判越界的口径必须一致
    # 每个 None 都跳过: 参数缺省不等于非法, 越界判据只对"给了但超了"的参数生效
    # ra 上界开区间: 360.0 与 0.0 是同一方向, 取值域约定为 [0, 360)
    if ra is not None and not 0.0 <= ra < 360.0:  # 赤经取半开区间: 360 与 0 是同一方向, 不重复表达
        return f"ra={ra} 越界 (合法域 [0, 360))"
    # dec 闭区间 [-90, 90]: 两极是合法天区, 与 ra 的半开区间不同, 这里不能照抄
    if dec is not None and not -90.0 <= dec <= 90.0:  # 纬度用闭区间: 两极是合法天区, 不能照抄赤经的写法
        return f"dec={dec} 越界 (合法域 [-90, 90])"
    # radius 下界开: 半径 0 会退化成"只匹配中心点", 属 E5-D08 边界题要抓的形态
    if radius is not None and not 0.0 < radius <= 18000.0:  # 半径下界开: 零半径退化成只匹配中心点, 属边界题要抓的形态
        return f"radius_arcsec={radius} 越界 (合法域 (0, 18000])"
    page_size = to_float(args.get("page_size"))  # 页长同样先转数值再比上限, 避免字符串比较出岔
    # 上限对齐 src 的 MAX_FETCH_PAGE_SIZE: 超过就是超长页, 站点侧会截断
    if page_size is not None and page_size > MAX_PAGE_SIZE:  # 超上限即站点侧会截断, 属非法参数而非性能偏好问题
        return f"page_size={int(page_size)} 超上限 {MAX_PAGE_SIZE}"
    return None
