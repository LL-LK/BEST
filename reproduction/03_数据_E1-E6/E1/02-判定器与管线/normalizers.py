# -*- coding: utf-8 -*-
"""evals.nl2tool.normalizers — E1 归一化器 (标注 ↔ 实测轨迹比对的同一把尺子)。

能力边界: 把"不同写法的同一个东西"化成规范形态再比对 — 星表别名/分组前缀、
列名星表前缀、坐标六十进制、半径单位、波段标签、数值容差、无序集合七族。
边界: 纯函数、零 IO、零网络; 权威数据 (别名表/列映射) 一律取自
``src.protocol`` 单点, 不在本文件复刻第二份 (E1 §7: 归一化器清单对应该文件)。

白盒锚点: docs/eval-E1-nl2tool.md §7 (三类 grader 的 normalized 档);
src/protocol_catalog_tables.py (CATALOG_ALIASES/CATALOG_COLUMNS 权威表)。
"""
from __future__ import annotations

# 标准库: 正则 (六十进制/分组前缀拆分) 与数学 (圆周换算)
import re

# 本地: 权威协议层 — 别名表与 12 张可查表路径 (归一化的真值来源)
from src.protocol import CATALOG_ALIASES, CATALOG_PATHS

_GROUP_PREFIXES = ("std/", "calib/", "other/")   # 导航组前缀: 成员要先剥前缀才是表 id

# 坐标四形态的判别正则: 匹配次序即消歧次序 (norm_coord 依次尝试, 见下)
_COLON_DMS_RE = re.compile(          # 纯冒号三元组: "-20:30:00" → Dec 度分秒口径
    r"^\s*([+-]?\d+(?:\.\d+)?):(\d+(?:\.\d+)?):(\d+(?:\.\d+)?)\s*$"
)
_BARE_SEXAGESIMAL_RE = re.compile(   # 无标记六十进制: "12 30 00" → RA 时角口径
    r"^\s*(\d+(?:\.\d+)?)[\s:]+(\d+(?:\.\d+)?)[\s:]+(\d+(?:\.\d+)?)\s*$"
)
_HMS_RE = re.compile(                # 时角记法: 12h30m00s, 分/秒位可省
    r"^\s*([+-]?\d+(?:\.\d+)?)\s*[hH]\s*(?:(\d+(?:\.\d+)?)\s*[mM]\s*)?"
    r"(?:(\d+(?:\.\d+)?)\s*[sS]\s*)?\s*$"
)
_DMS_RE = re.compile(                # 度分秒记法: "+20°00′00″" 或冒号分隔
    r"^\s*([+-]?\d+(?:\.\d+)?)\s*[°dD:\s]\s*(?:(\d+(?:\.\d+)?)\s*['′mM:]\s*)?"
    r'(?:(\d+(?:\.\d+)?)\s*["″sS]\s*)?\s*$'
)


def norm_catalog(name: str) -> str:
    """星表名归一: 小写 + 去分组前缀 + 别名映射 (权威表在 protocol)。

    Args:
        name: 原始星表写法 (``GAIA_DR3`` / ``std/scr_galah`` / ``gaia_dr3``)。

    Returns:
        规范表 id (12 张可查表之一); 无法归一的原样小写返回 (由调用方判错)。
    """
    key = str(name or "").strip().lower()   # 别名表以"小写无空白"为键
    for prefix in _GROUP_PREFIXES:          # 一次只剥一层: "std/scr_galah" → "scr_galah"
        if key.startswith(prefix):                                                                  # 剥星表前缀
            key = key[len(prefix):]                                                           # 前缀长度即切片长度: 别名表与列名表用的是同一套前缀
    return CATALOG_ALIASES.get(key, key)    # 未登记别名原样返回 (由调用方判错)


def norm_column(name: str) -> str:
    """列名归一: 去星表前缀 (``scr_galah_rztf`` ≡ ``rztf``, 双向命中)。

    12 张可查表的任一列名前缀 (``{table}_``) 一律剥掉; 无前缀的原样返回。
    剥前缀后与带前缀形态比对相等 — E1 §6.2 columns 档的集合比较依赖此归一。
    """
    key = str(name or "").strip()
    for table in CATALOG_PATHS:                   # 12 张可查表逐个试前缀
        prefix = f"{table}_"
        if key.lower().startswith(prefix):        # 比对不区分大小写, 返回保持原写法
            return key[len(prefix):]              # 剥前缀 → 与带前缀形态同名可比
    return key                                    # 无前缀的列名原样返回


_SORT_SEP_RE = re.compile(r"[.\-/]")   # 排序列的分隔符差异: schema 写点号, 标注写下划线


def norm_sort(name) -> str:
    """排序列归一: **分隔符与星表前缀都不参与比对** (``ps1.rpsf`` ≡ ``ps1_rpsf`` ≡ ``rpsf``)。

    权威出处: ``references/tools.schema.json`` 的 ``sort`` 参数 description ——
    "服务端排序列, 如 ``ps1.rpsf`` 或裸名 ``rpsf``"。即带表前缀与裸名是**同一列**,
    而前缀分隔符在 schema 里写点号、在专家标注里写下划线。两种写法指向同一列时,
    按 exact 通道比对会让"照 schema 写"的答案被判错而"照标注写"的通过 ——
    判分器在此与自己的权威声明打架 (NL2T-21 实测: 照 schema 写 ``ps1.rpsf``
    判 0 分)。归一化后三种形态收敛到同一个裸列名。

    与 :func:`norm_column` 的差别: 列名档要求**必须带前缀** (``showcol`` 协议层
    拒收裸名, 少前缀是真的会失败); 排序列档 schema 明写裸名合法, 故这里剥前缀。
    """
    key = str(name or "").strip().lower()                                            # 先小写: 大小写不是列名的区别
    key = _SORT_SEP_RE.sub("_", key)                                                 # 分隔符统一成下划线: 点号/连字符/斜杠都是同一个前缀
    for table in CATALOG_PATHS:                                                      # 12 张可查表逐个试前缀
        prefix = f"{table}_"
        if key.startswith(prefix):
            return key[len(prefix):]                                                 # 剥前缀 → 与裸名可比
    return key                                                                       # 无前缀的原样返回 (已是裸名)


def norm_coord(value) -> float | None:
    """坐标归一: 六十进制/度分秒/十进制度 → 度 (float)。

    支持 ``12h30m00s`` (RA 时角, ×15)、``+20°00′00″``/``-20:30:00``
    (Dec 度分秒)、``187.5`` (十进制度)。无法解析返回 None (调用方记 S2)。

    Returns:
        度数 (float); 不可解析为 None。
    """
    if value is None:                             # 缺值不猜: 交调用方记 S2
        return None
    if isinstance(value, (int, float)):            # 已是数值 = 十进制度, 直接放行
        return float(value)
    text = str(value).strip()                     # 空白先剥干净再判形态
    # 判定次序即消歧次序 (E1 §7): 带 h 标记 → RA 时角; 带符号或 °/d 标记
    # → Dec 度分秒; 两者都无的裸三元组按 RA 时角 (与标注样例口径一致:
    # "12 30 00" 是 RA, "+20°00′00″" 是 Dec)。
    m = _HMS_RE.match(text)                       # 判据一: 时角记法
    if m:                                                                                           # 十进制度分匹配
        hours, minutes, seconds = (float(g) if g else 0.0 for g in m.groups())  # 缺位补 0
        return (hours + minutes / 60.0 + seconds / 3600.0) * 15.0  # 时角→度 (×15)
    m = _DMS_RE.match(text)                       # 判据二: °/d 标记的度分秒
    if m:                                                                                           # 度分秒匹配
        degrees, minutes, seconds = (float(g) if g else 0.0 for g in m.groups())          # 缺位补 0: "12 30" 里的秒是缺的, 不补会除出垃圾
        sign = -1.0 if str(m.group(1)).startswith("-") else 1.0   # 符号单独提出
        return sign * (abs(degrees) + minutes / 60.0 + seconds / 3600.0)
    m = _COLON_DMS_RE.match(text)                 # 判据三: 带符号的冒号三元组
    if m:                                                                                           # 度分秒格式一
        degrees, minutes, seconds = (float(g) if g else 0.0 for g in m.groups())                    # 同样要补位
        sign = -1.0 if str(m.group(1)).startswith("-") else 1.0   # 符号口径同上
        return sign * (abs(degrees) + minutes / 60.0 + seconds / 3600.0)
    m = _BARE_SEXAGESIMAL_RE.match(text)          # 判据四: 无标记裸三元组按 RA
    if m:                                                                                           # 时角分格式
        hours, minutes, seconds = (float(g) if g else 0.0 for g in m.groups())                      # 时角分也要补位
        return (hours + minutes / 60.0 + seconds / 3600.0) * 15.0
    try:
        return float(text)                        # 兜底: 纯十进制度写法
    except ValueError:
        return None                               # 兜底也失败 = 不可解析


def norm_radius(value) -> float | None:
    """半径归一: 度/角分/角秒 → 角秒 (float)。

    ``5″``/``5`` 视为角秒 (BEST 表单 pos.radius 的原生单位), ``5′`` 角分
    ×60, ``5°``/``5deg`` ×3600。无量纲数字按角秒 (服务端口径)。
    """
    if value is None:                                   # 缺值不猜, 与 coord 同口径
        return None
    if isinstance(value, (int, float)):                  # 裸数字 = 角秒 (BEST 表单原生单位)
        return float(value)
    text = str(value).strip().lower().replace(" ", "")   # 大小写与空格不参与单位判定
    m = re.match(r"^([+-]?\d+(?:\.\d+)?)(″|''|\"|角秒|arcsec|as)?$", text)  # 角秒/无单位
    if m:                                                                                           # 时分秒格式
        return float(m.group(1))                        # 原值即角秒
    m = re.match(r"^([+-]?\d+(?:\.\d+)?)(′|'|角分|arcmin|am)$", text)  # 角分
    if m:                                                                                           # 弧度形式
        return float(m.group(1)) * 60.0                 # 角分 → 角秒 (×60)
    m = re.match(r"^([+-]?\d+(?:\.\d+)?)(°|度|deg)$", text)            # 度
    if m:                                                                                           # 无单位裸数值
        return float(m.group(1)) * 3600.0               # 度 → 角秒 (×3600)
    try:
        return float(text)                              # 兜底: 无单位的纯数字
    except ValueError:
        return None                                     # 解析失败 = 不可解析


# 波段标签归一: 各巡天口语写法 → 标准标签 (E1 §6.3 BandAcc 的比对基线)
_BAND_ALIASES = {                                                                          # 波段别名表: 各星表同一波段的列名不统一, 归一到规范标签
    "ztf_g": "ztf.g", "ztf_r": "ztf.r", "ztf_i": "ztf.i",
    "gaia_g": "gaia.G", "gaia_bp": "gaia.BP", "gaia_rp": "gaia.RP",
    "ps1_g": "ps1.g", "ps1_r": "ps1.r", "ps1_i": "ps1.i",
    "ps1_z": "ps1.z", "ps1_y": "ps1.y",
    "sdss_u": "sdss.u", "sdss_g": "sdss.g", "sdss_r": "sdss.r",
    "sdss_i": "sdss.i", "sdss_z": "sdss.z",
}


def norm_band(system: str, band: str) -> str:
    """波段标签归一: ``(系统, 波段)`` → 标准标签 (``ztf.g`` / ``gaia.G`` ...)。

    系统名大小写/别名 (ZTF/ztf、Gaia DR3/gaia) 不敏感; 未登记的组合原样
    拼回 (调用方按 BandAcc 口径判错 — 未登记即错误, 不静默归一)。
    """
    key = f"{str(system or '').strip().lower().replace(' ', '_').replace('dr3', '')}_{str(band or '').strip().lower()}"
    key = key.replace("__", "_")   # 消掉 "Gaia DR3_" 折叠后残留的双下划线
    return _BAND_ALIASES.get(key, f"{system}.{band}")   # 未登记组合原样拼回 (BandAcc 判错)


def norm_number(actual, expected, atol: float = 1e-9, rtol: float = 0.0) -> bool:
    """数值归一比对: ``|a - b| <= atol + rtol * |b|`` (E1 §6.2 number 档)。"""
    try:
        a, b = float(actual), float(expected)   # 两侧都转 float 后才谈容差
    except (TypeError, ValueError):
        return False                            # 任一侧不可转 = 判不等, 不抛给调用方
    return abs(a - b) <= atol + rtol * abs(b)  # rtol 缺省 0, 绝对容差为主


def norm_set(actual, expected) -> bool:
    """无序集合归一比对 (columns/工具集合: 顺序差异不扣分, E1 §6.2 set 档)。"""
    try:
        return set(actual or ()) == set(expected or ())   # 顺序不参与比较 (columns 档)
    except TypeError:
        return False                                     # 元素不可哈希 = 判不等


def norm_set_covers(actual, expected) -> bool:
    """列投影集合比对: 标注点名的列**必须都在**实际投影里, 多投影不判错。

    与 :func:`norm_set` 的全等口径**故意不同** —— 两者回答的是不同问题:
    ``norm_set`` 问"两边是不是同一个集合"(通用 set 档: 工具集合、排序参数),
    本函数问"该拿的列拿全了没有"(``columns`` 档)。理由是列投影是**超集无害**
    的: 多要几列(多要一个 ``ruwe`` 质量标志、多要一个误差列)既不改变科学结论,
    也不构成参数错误, 按全等判会让"投影更规范"反而被判错; 反过来少要了
    标注点名的权威列 (例: 问 G 星等却没投影 ``gaia_dr3_18_phot_g_mean_mag``)
    必须判错 —— 那才是静默错值的入口, 由这里的包含关系兜住。

    刻意**不做**列名归一 (不剥星表前缀): 标注 anti_pattern 明写"裸名不带表
    前缀投影不到列"(NL2T-15/16), 剥前缀会让裸名也判对, 那是把红线放走。

    Args:
        actual: 实测调用里 ``columns`` 的取值 (列名列表)。
        expected: 标注点名的列名列表。

    Returns:
        标注列名全部出现在实际投影里即 True; 少一列即 False。
    """
    try:
        want = {str(c).strip() for c in (expected or ())}   # 标注侧去空白: 形态归一, 不做别名/前缀映射
        got = {str(c).strip() for c in (actual or ())}      # 实测侧同样只去空白
    except TypeError:                                         # 非可迭代 (传了字符串/数值) → 判错
        return False
    return want <= got                                        # 包含关系: 多投影通过, 少投影失败

