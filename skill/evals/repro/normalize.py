# -*- coding: utf-8 -*-
"""evals.repro.normalize — E6 参数归一 + 结论卡归一 (一致率比对的前站)。

能力边界: 把多次运行间"不同写法的同一个东西"化成规范形态 — 参数侧 (星表/
坐标/半径/列/枚举/集合) 与结论卡侧 (kind/key_numbers/key_entities/caveats)。
边界: 纯函数零 IO; 容差读 evals/_data/tolerances.yaml 单点 (L1 配置层)。

**与 E1 normalizers 的口径差异 (文档 §5.2, 勿混)**: 列名必须**全限定** —
``scr_galah_rztf`` 与裸 ``rztf`` 视为**不一致** (E1 的去前缀归一只服务
于"标注↔实测"的宽比对; E6 抓的正是投影稳定性, 宽比对会把抖动洗掉)。
角度统一为度 (容差 1e-6), 半径统一为角秒 (容差 1e-3)。

白盒锚点: docs/eval-E6-reproducibility.md §5.2 (PAC 归一化表) /
§5.4 (结论卡四子项); evals/_data/tolerances.yaml (容差权威)。

职责: 一致率比对的前站 —— 把多次运行之间"不同写法的同一个东西"化成规范
  形态, 参数侧管角度/半径/列名/枚举/集合, 结论卡侧管 kind/数值/实体/限定语。
所属实验: E6 可复现与效率 (32 任务 + R0 路实跑); 归一化表真值是
  docs/eval-E6-reproducibility.md §5.2 与 §5.4, 容差权威是
  evals/_data/tolerances.yaml (唯一允许的跨实验共享件, 且只是纯数据)。
对外接口: norm_angle_deg / norm_radius_arcsec 两个单位归一; norm_args
  参数级归一 (PAC 的输入); norm_card 结论卡归一 (FCC 的输入);
  cards_equal 两张归一卡的四子项全等判定; strip_session_id 剥易失会话号;
  _norm_number_value 是数值整备的内部件。
依赖与数据流: 输入 = 各次运行记录下来的参数字典与结论卡字典 (形态不统一
  正是要归一的原因); 产物 = 规范形态的字典, 被 evals/repro/consistency/
  消费后汇入报告, 本模块自身零 IO 不落盘。
关键契约与不变量: 纯函数零 IO — 同一份输入归一多少次都得到逐字段相同的
  结果, 这是"可复现"指标自身可复现的前提; 零跨实验 import, 只从
  evals._data 读纯数据字典 (容差), 逻辑全在本文件, 与其它实验的等价性
  由 evals/equivalence/ 的断言守护。
陷阱与边界: 列名坚持**全限定**, ``scr_galah_rztf`` 与裸 ``rztf`` 判不一致
  —— 这与 E1 的去前缀归一口径相反且刻意: E1 归一服务"标注↔实测"的宽
  比对, 而 E6 抓的正是投影稳定性, 用宽口径会把抖动洗掉 (文档 §5.2 勿混)。
  stable_uri 的 sqlid/session_id 是文档明列的地雷, 每次运行都不同, 不剥
  就会让 FCC 无意义地归零。角度解析的四种形态按 h→时角、符号→度分秒的
  次序消歧, 顺序写反会把 12h 误当 12 度。
"""
from __future__ import annotations

# 标准库: 正则 (坐标/单位形态) / 集合运算
import re

# 本地: 容差表 (唯一共享数据字典; 判定逻辑不进来)
import sys
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # 只为读 evals._data 这一个纯数据字典, 别顺手加别的实验
# 本地: 归一化的输入件 (结论卡/参数形态的来源模块)
from evals._data import load_tolerances  # noqa: E402

_TOL = load_tolerances()  # 容差单点: 改容差只改这一处, 不散落在各判定里

# 半径单位 → 角秒 (文档 §5.2: 半径统一角秒, 容差 1e-3)
_RADIUS_UNITS = {"″": 1.0, "''": 1.0, '"': 1.0, "角秒": 1.0, "arcsec": 1.0, "as": 1.0,
                 "′": 60.0, "'": 60.0, "角分": 60.0, "arcmin": 60.0, "am": 60.0,
                 "°": 3600.0, "度": 3600.0, "deg": 3600.0}  # 换算因子收在表里, 不写死在代码中
# 坐标形态 (自包含实现; 与 E1 的消歧次序一致: 带 h → 时角, 带符号 → 度分秒)
_HMS_RE = re.compile(r"^\s*([+-]?\d+(?:\.\d+)?)\s*[hH]\s*(?:(\d+(?:\.\d+)?)\s*[mM]\s*)?(?:(\d+(?:\.\d+)?)\s*[sS]\s*)?\s*$")  # 时角形态: 12h 要按 12×15 度读, 试序必须排在 DMS 之前
_COLON_DMS_RE = re.compile(r"^\s*([+-]?\d+(?:\.\d+)?):(\d+(?:\.\d+)?):(\d+(?:\.\d+)?)\s*$")      # 冒号形态: 没有角度单位标记, 一律按度分秒读
_DMS_RE = re.compile(r"^\s*([+-]?\d+(?:\.\d+)?)\s*[°dD]\s*(?:(\d+(?:\.\d+)?)\s*['′mM]\s*)?(?:(\d+(?:\.\d+)?)\s*[\"″sS]\s*)?\s*$")  # 带度符号或 d/D 的形态, 与冒号形态互为备份
_BARE_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)[\s:]+(\d+(?:\.\d+)?)[\s:]+(\d+(?:\.\d+)?)\s*$")  # 裸三元组: 按天文学惯例当时角


def norm_angle_deg(value: Any) -> Optional[float]:
    """角度归一 → 度 (ra/dec 通用; 不可解析返回 None 由调用方判不一致)。

    作用: 把四种常见角度写法折成度。关键参数 value 是原始角度 (数值或
    字符串)。Returns: 度数, 不可解析返回 None。抛什么: 不抛。
    """
    if value is None:  # None 透传: 缺字段不等于 0 度
        return None
    # bool 显式排除: 它是 int 的子类, 不挡掉的话 True 会被当成 1.0 度,
    # 让一次布尔误传伪装成合法的角度
    if isinstance(value, (int, float)) and not isinstance(value, bool):              # bool 是 int 的子类, 不挡掉 True 会被当成 1.0 度
        return float(value)
    text = str(value).strip()  # 先压成文本: 四条正则都只吃字符串
    # 消歧次序不能换: 带 h 的是时角(×15), 冒号与度符号的是度分秒(×1),
    # 纯空白分隔的三个数按天文学惯例也是时角 — 先试 h 再试 DMS 正是为了
    # 让 "12h30m" 落到时角分支而不是被裸三元组抢走
    for regex, scale in ((_HMS_RE, 15.0), (_COLON_DMS_RE, 1.0), (_DMS_RE, 1.0), (_BARE_RE, 15.0)):  # 次序本身就是消歧规则: 换序会把 12 时角读成 12 度
        m = regex.match(text)  # 逐条试: 第一条命中即用, 后面形态不再看
        if m:                                                                                       # 第一条命中即用: 形态有歧义也不回头复判
            a, b, c = (float(g) if g else 0.0 for g in m.groups())                              # 缺段补 0: 只写 12h 这种形态不该在这里崩
            # 符号只作用于第一段, 所以先取绝对值再乘符号: 直接把符号带进
            # 每一段会让 "-0:30:00" 变成正 0.5 度
            sign = -1.0 if str(m.group(1)).startswith("-") else 1.0
            return sign * (abs(a) + b / 60.0 + c / 3600.0) * scale  # 分→/60, 秒→/3600; scale 把时角换成度
    # 兜底按纯数字试: "16.5" 这种没写单位的裸值按度算, 是 E6 的既定约定
    try:
        return float(text)  # 兜底裸值按度算
    except ValueError:
        return None


def norm_radius_arcsec(value: Any) -> Optional[float]:
    """半径归一 → 角秒 (文档 §5.2; 无量纲数字按角秒 — 服务端原生单位)。

    作用: 把带单位的半径折成角秒。关键参数 value 是原始半径。
    Returns: 角秒数, 不可解析返回 None。抛什么: 不抛。
    """
    if value is None:                                                                               # None 透传: 缺字段不等于 0 角秒
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):                  # 同样排 bool: True 不是半径, 不能当 1 角秒收下
        return float(value)  # 无量纲数字即角秒: 服务端原生单位
    # 小写并去空格: "12 arcsec" 与 "12ARCSEC" 必须归到同一个值, 否则同
    # 一半径的两种写法会被判成参数漂移
    text = str(value).strip().lower().replace(" ", "")
    for unit, factor in _RADIUS_UNITS.items():  # 后缀匹配: 因子由表给, 不写死在代码里
        if text.endswith(unit):                                                                  # 按后缀定单位: 换算因子查表, 不写死在换算里
            try:
                return float(text[: -len(unit)]) * factor  # "12arcmin" → 720 角秒
            except ValueError:
                # 剥掉后缀仍不是数字 (如 "约 1 度" 里的中文), 交回 None 让
                # 调用方判不一致, 不在这里猜一个值
                return None
    try:
        return float(text)
    except ValueError:
        return None


def norm_args(args: dict) -> dict:
    """参数归一 (E6 口径): 角度→度 / 半径→角秒 / 列名全限定 / 枚举精确 / 集合。

    - ``ra``/``dec`` → 度 (容差来自 tolerances.fields.ra_deg);
    - ``radius_arcsec``/``radius`` → 角秒;
    - ``columns`` → 排序集合 (顺序不敏感 — 顺序敏感会误杀);
    - ``catalog`` → 小写 strip (不做别名归一 — 表选错正是 PAC 要抓的);
    - 其余标量原样 (bool/None 精确)。
    """
    out: dict[str, Any] = {}  # 输出恒为同构字典: 缺键由分派补齐, 不留空洞
    for key, value in (args or {}).items():                                                    # 逐字段分派: 同一个数字落在不同字段下语义完全不同
        # 按字段名分派而不是按值形态猜: 同一个数字放在 ra 与 rows_limit
        # 下语义完全不同, 靠形态猜会把 30 (行数) 当成 30 度
        if key in ("ra", "dec"):
            out[key] = norm_angle_deg(value)                                                 # ra 与 dec 共用一套角度归一: 单位制一致才可比
        elif key in ("radius_arcsec", "radius"):
            out[key] = norm_radius_arcsec(value)  # 两种字段名都收: 被测链路两种都发过
        elif key == "columns":
            out[key] = sorted(str(c).strip() for c in (value or []))  # 排序而非去重: 重复列名是实质错误
        elif key == "catalog":
            out[key] = str(value or "").strip().lower()  # 只做大小写与空白归一, 别名归一会洗掉"选错表"
        else:
            # 其余原样透传: 枚举精确与 bool/None 精确都是硬要求, 任何
            # "顺手转一下类型"都会放宽 PAC
            out[key] = value                                                                      # 其余原样透传: 顺手转一下类型就会放宽一致率
    return out


def strip_session_id(uri: str) -> str:
    """stable_uri 去 session_id (sqlid 易失, 严禁进比对 — 文档 §5.2 地雷)。

    作用: 把 URI 里的会话标识换成固定占位符。关键参数 uri 是原始 URI。
    Returns: 去会话号后的 URI; 无会话号则原样返回。抛什么: 不抛。
    """
    text = str(uri or "")  # None 也走这条路: 按空串处理, 不抛
    # 三种形态都要覆盖: 查询串 (?session_id=x)、路径段 (/sqlid/x)、以及
    # 裸的 sqlid= 变体 —— 只判一种会让另外两种漏过, FCC 又会无意义地归零
    for marker in ("session_id=", "sqlid=", "/sqlid/"):
        if marker in text:                                                                         # 三种形态逐个试: 只判一种会让另外两种漏过
            head, _, tail = text.partition(marker)                                                  # 只切一次: 值部分留给下一行按分隔符再截
            # 值截到下一个 & 或 / 为止, 否则会把后面的路径段一起吞掉,
            # 同一个 sqlid 在两个不同页面下就会归一成两个不同字符串
            tail = tail.split("&", 1)[0].split("/", 1)[-1]  # 只留到分隔符: 免得吞掉后面的路径段
            return f"{head}{marker}<SESSION>"  # 占位符固定: 只看"有没有会话号", 不看它是什么
    return text  # 无会话号即原样返回, 不做别的改写


def norm_card(card: dict) -> dict:
    """结论卡归一 (文档 §5.4 四子项): kind 精确 / 数值按字段容差整备 /
    entities 与 caveats 集合化 / stable_uri 去 session。

    归一后形态可直接跨 run 机器比对: ``key_numbers`` 按 (field, 值) 排序,
    ``key_entities``/``caveats`` 转 set (顺序不敏感), URI 剥离易失会话号。
    """
    card = card or {}  # 缺卡按空卡处理: 结论卡缺失是常态而非异常
    numbers = []  # 只收可比数值项
    for item in card.get("key_numbers") or ():
        # 缺 field 或 value 的条目直接丢弃: 结论卡允许有"提及但没量化"的
        # 数字, 那些在 FCC 口径下不可比, 硬塞进比对只会制造恒假的漂移
        if isinstance(item, dict) and "field" in item and "value" in item:
            numbers.append({"field": str(item["field"]),
                            "value": _norm_number_value(item["value"])})
    entities = set()  # 用 set 而非 list: 顺序已被声明不承载语义
    for entity in card.get("key_entities") or ():  # 只遍历, 不改原卡: 纯函数无副作用
        text = str(entity)                                                                      # 先转字符串: 实体名里混着数字时集合比较才不会炸
        # 只对带会话号的实体做剥离: 无会话号的实体原样进集合, 多做一次
        # 字符串扫描没必要, 也避免误伤名字里恰好含 "sqlid" 的实体
        entities.add(strip_session_id(text) if "sqlid" in text or "session_id" in text else text)
    return {
        # kind 缺省成 "none" 而不是空串: 空串会让"没写 kind"与"写了空 kind"
        # 在比对时同形, 两种都是缺陷, 归到同一桶反而掩盖了区别
        "kind": str(card.get("kind", "none")),
        # 排序键把值也 str 化: 同一 field 下混有 float 与 str 时, 直接按
        # 值排序会在 Python 3 抛 TypeError
        "key_numbers": sorted(numbers, key=lambda n: (n["field"], str(n["value"]))),
        "key_entities": entities,
        "caveats": set(str(c) for c in card.get("caveats") or ()),  # 限定语同口径集合化: 顺序不敏感
    }


def _norm_number_value(value: Any) -> Any:
    """结论卡数值整备: 可转 float 的转 float (供 1e-6 相对容差比对)。

    作用: 把 "16.812" 这类字符串数值拉回数值域。关键参数 value 是原始值。
    Returns: 能转的返回 float, 不能转的原样返回 str。抛什么: 不抛。
    """
    try:
        return float(value)  # 字符串数值拉回数值域: 容差比较只对 float 有意义
    except (TypeError, ValueError):
        # 转不动就当文本留档 (如 "无"/"未测到"): 丢成 None 会让"明确说
        # 没有"和"漏填"在比对时同形, 那正是最不该被放过的一类差异
        return str(value)


def cards_equal(a: dict, b: dict, rtol: float = 1e-6) -> bool:
    """两张归一化结论卡是否一致 (四子项: kind/数值容差/实体集合/限定集合)。

    作用: 结论卡的全等判定。关键参数 a/b 是已归一的两张卡, rtol 是数值
    相对容差。Returns: 四子项全等即 True。抛什么: 不抛。
    """
    if a["kind"] != b["kind"]:  # 先判 kind: 结论类型不同就没必要逐项比
        return False
    # 集合比而非列表比: 实体与限定语在归一阶段已声明顺序不承载语义
    if set(a["key_entities"]) != set(b["key_entities"]):
        return False
    if set(a["caveats"]) != set(b["caveats"]):
        return False
    # 先比长度: 长度不等直接判否, 否则 zip 会静默截断, 少一个数也会
    # 走到最后 return True
    if len(a["key_numbers"]) != len(b["key_numbers"]):
        return False
    for left, right in zip(a["key_numbers"], b["key_numbers"]):  # 按位配对: 归一时已排序, 位置才有意义
        if left["field"] != right["field"]:
            return False
        if isinstance(left["value"], float) and isinstance(right["value"], float):  # 两侧须都是 float
            # 1e-30 保底: 两个值都极小时 max(...) 会取到 0 而除零, 那
            # 种量级在星表里是视差 (mas), 是真实存在的数据
            if abs(left["value"] - right["value"]) > rtol * max(abs(left["value"]), abs(right["value"]), 1e-30):
                return False
        # 非数值 ("无"/"未测到") 退回精确比: 限定语与缺失声明不接受容差,
        # "无" 与 "未测到" 在 E6 口径下是两回事
        elif left["value"] != right["value"]:
            return False
    return True  # 四子项全过: 两张归一卡逐字段一致
