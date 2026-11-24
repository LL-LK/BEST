"""CSV/TXT 导出器的共用安全辅助 (公式注入消毒)。

能力边界: CSV 公式注入消毒器 (sanitize_cell): 正确放行纯数字 (含负数), 仅对真公式向量(=,+,-,@ 开头且非数字) 加单引号。边界: 全包唯一消毒实现; 各 emitter 必须接本模块而非内联副本 (Q-06 数据损坏教训)。
白盒锚点: references/ALGORITHM-SPEC.md §2 (csv_safety 锚点); OWASP CSV 注入惯例。

不得内联 ``v[0] in ("=", "+", "-", "@")`` 这类首字符判定: 它会把合法负数字符串
损坏掉 (南天的 ``dec = "-5.0"`` 被写成 ``"'-5.0"``)。每个 emitter 都必须调
``sanitize_row`` / ``sanitize_cell``, 漏接即静默失去消毒, 比显式报错更危险。
本模块的辅助函数只对真正的公式注入向量加前缀: 以 ``=`` / ``+`` / ``@`` 开头的
字符串, 或以 ``-`` / ``+`` 开头但后续不是数字的字符串。纯数字字符串 (``"-5.0"``、
``"+1.25e-3"``) 原样透传。
"""
from __future__ import annotations

# 标准库: 单元格值可能是任意类型 (数字/None/对象), 用 Any 标注并用 isinstance 分流。
from typing import Any

# 公式注入前缀: 以这三者开头的单元格会被 Excel/LibreOffice 当公式执行。
# 消费方: sanitize_cell (全包唯一消毒入口, 各 emitter 复用)。
_FORMULA_PREFIXES = ("=", "+", "@")                    # Excel/LibreOffice 会把这类前缀的单元格当公式执行
# TAB/CR 前缀同样危险 (可被用来拆列/注入控制序列), 用单引号前缀中和
# (与 Excel 自身的中和写法一致)。消费方同上。
_TAB_CR = ("\t", "\r")                                # 拆列与控制序列面, 威胁等级与公式前缀同级


def _looks_numeric(text: str) -> bool:
    """判断文本是否可整体解析为一个数字 (含负号与科学计数法)。

    Args:
        text: 待判定的单元格文本。

    Returns:
        True 表示这是纯数字 (含 ``-5.0`` / ``+1.25e-3``), 不应被当作公式向量。
    """
    if not text:  # 空串没有首字符可取, 提前退掉免得下面下标越界
        return False
    try:
        float(text)  # 用 float 试解析是唯一能同时吃下负号与科学计数的判定
        return True
    except ValueError:
        return False


def sanitize_cell(value: Any) -> Any:
    """返回 ``value`` 的 CSV 安全表示。

    非字符串值原样返回 (csv writer 会自己做字符串转换)。看起来是数字的字符串
    —— 包括负数 —— 原样返回。只有以公式字符开头且**不是**数字的字符串才被加
    一个前导 ``'``, 使表格软件把它当字面文本而不是公式。

    Args:
        value: 单个单元格值。

    Returns:
        消毒后的值 (可能原样, 也可能加了 ``'`` 前缀的字符串)。
    """
    if not isinstance(value, str):                       # 非字符串不进消毒: 交给 csv writer 自己转, 免得把整列数字加引号
        return value
    if not value:  # 空单元格直接放行: 被加引号会在表里显示成一个裸引号
        return value
    first = value[0]                                    # 判定只看首字符: 向量表全部是前缀式触发
    if first in _TAB_CR:  # TAB/CR 先于公式字符判: 这类向量不落在公式前缀表里
        # TAB/CR 开头: 加单引号 + 一个空格, 既中和又保留可读性。
        return "' " + value
    if first in _FORMULA_PREFIXES:  # 三个前缀同判: 拆开写只是把同一套放行逻辑抄三遍
        # "+12" / "-3.5" 是真实数字; "=cmd|..." / "@SUM(...)" 不是。
        if _looks_numeric(value):                       # 合法数值优先放行: 误加引号会把数值列变成文本列
            return value
        return "'" + value
    if first == "-":  # 负号单列: 它既像数值前缀又像注入前缀, 只能靠试解析分流
        # 单独的 "-" 不危险, 但 "-1+2|..." 这类负载确实存在。
        # 负数字符串透传; 只有非数字的 "-" 字符串才被加引号。
        if _looks_numeric(value):                       # 判据同上: 只有非数字的 "-" 才被当注入向量
            return value
        return "'" + value
    return value


def sanitize_row(row: dict) -> dict:
    """返回 ``row`` 的副本, 其中每个单元格都经过消毒。

    Args:
        row: 一行数据 (列名 -> 单元格值)。

    Returns:
        新 dict (不改动入参), 单元格值经 :func:`sanitize_cell` 处理。
    """
    return {key: sanitize_cell(value) for key, value in row.items()}   # 返回新 dict: 入参行不被就地改, 调用方的原值不受消毒副作用污染


def sanitize_rows(rows: list[dict]) -> list[dict]:
    """返回 ``rows`` 的副本, 其中每一行都经过消毒。

    Args:
        rows: 多行数据。

    Returns:
        新 list (不改动入参), 每行经 :func:`sanitize_row` 处理。
    """
    return [sanitize_row(row) for row in rows]                        # 同为新 list: 逐层拷贝是消毒器"绝不改入参"的代价
