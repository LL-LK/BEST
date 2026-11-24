# -*- coding: utf-8 -*-
"""evals.groundtruth.metrics.m4_structure — M4 排序/分页/截断 (权重 0.15)。

三项各自 pass/fail, 汇总 pass 数/3 (E2 §6 M4):
  - 排序: 序列按 sort key 单调 (升/降); 同 key 用主键次级比较;
  - 分页: 各页并集 == GT 行集 (无损)、页两两交集 == ∅ (无重)、
    末页判据正确 (不提前停/不多翻);
  - 截断: (truncated, total_count, returned_count) 三元组与 GT 完全一致,
    任一错即该项 fail — total_count 必须优先取服务端 getcount 值
    (src/client.py 已修历史 bug, E2 要钉死)。
"""
from __future__ import annotations

# 本地: 主键集合 (页际比对单位) 与标准行主键 (期望序列比对)
from evals.groundtruth.canonical import (  # 同实验内 import; 归一规则归 E2 私有, 不外借
    batch_line_offset,
    id_keys_unique,
    key_set,
    row_key,
)


def _monotonic(sequence: list, order: str) -> bool:
    """序列单调性 (数值优先; None 恒排末尾 — 与 E2 排序语义一致)。"""
    def sort_key(value):
        """排序键: 数值 (0, float) / 文本 (0, str) / 空值殿后 (1, 0.0)。"""
        if value is None:                                                             # 空值单列一档: 缺失既不是最小值也不该排最前, 混进数值档会颠倒顺序
            return (1, 0.0)  # 空值殿后: 缺失不是最小值, 也不该排到最前
        try:
            return (0, float(value))  # 数值优先: 文本序会把 "10" 排到 "9" 前面
        except (TypeError, ValueError):
            return (0, str(value))  # 转不成数的列按文本序, 至少稳定可比
    keys = [sort_key(v) for v in sequence]                                                   # 先算全序列的排序键: 单调性只看相邻对, 键算一次就够
    pairs = list(zip(keys, keys[1:]))  # 相邻对: 单调 = 每一对都不违序
    if order == "desc":
        return all(a >= b for a, b in pairs)  # 降序: 前一个不得小于后一个
    return all(a <= b for a, b in pairs)  # 升序 (含相等: 并列是允许的)


def _monotonic_live(sequence: list, order: str, sentinel_threshold: float) -> tuple[bool, int]:
    """实跑口径的排序单调性: **哨兵值不参与排序判据**。

    实测踩到的事实 (2026-07): 真站点把缺测哨兵 ``-1003.8802…`` (阈值见
    :mod:`evals._data.null_sentinel.yaml`) 当普通数值参与排序, 于是排序列头部会出现
    一串哨兵。站点**把哨兵排在哪一端没有契约**, 客户端也无权改写回包顺序 —— 所以把
    哨兵排除在判据之外才是对的: 它比较的是「**真实值**之间是否按声明方向单调」。

    **这条豁免与 2026-07 那次根因是两回事, 别混**: 那次真因是客户端给 ps1 注入了
    整列为空的 ``ps1_source_id``, 服务端当空操作 → 分页退化成无序遍历 (已改
    ``protocol.PAGINATION_SORT_COLUMNS`` 退到坐标列)。本函数处理的是**修完之后仍然
    存在**的哨兵混排: 排序列真生效后, 星等类列的头部仍是哨兵块。
    换言说: 前者改代码, 后者只改判据。

    Args:
        sequence: 行内该排序列的原始值序列。
        order: ``asc`` 或 ``desc``。
        sentinel_threshold: 哨兵阈值; 数值 <= 它即视为缺测并排除。

    Returns:
        ``(是否单调, 参与判定的真实值个数)``。真实值为 0 时返回 ``(True, 0)``:
        一列全缺测时"单调"不可判, 但那也不该算失败 (与 :func:`_monotonic` 的
        None 殿后约定同方向)。
    """
    real = [v for v in sequence if not _is_sentinel_value(v, sentinel_threshold)]
    if len(real) < 2:  # 少于两个真实值无从谈单调: 判过等于给"没数据"记满分
        return True, len(real)
    return _monotonic(real, order), len(real)


def _sentinel_threshold() -> float:
    """哨兵阈值 (唯一真源在 ``evals/_data/null_sentinel.yaml``, 不在本模块复刻)。"""
    from evals._data import load_null_sentinel  # 延迟导入: 模块级导入会让纯函数件拖上 YAML 依赖

    return float(load_null_sentinel()["threshold"])


def _is_sentinel_value(value, threshold: float) -> bool:
    """该值是不是哨兵 (缺测占位), 按 :mod:`evals._data` 的阈值口径。

    转不成数的文本 (ID / reason 码) 一律**不算**哨兵 —— 那是真文本数据, 参与排序。
    """
    try:
        return float(value) <= threshold
    except (TypeError, ValueError):
        return False  # 转不成数即真文本: 不是哨兵


def score_m4(gold: dict, actual: dict) -> dict:
    """M4: 排序/分页/截断三项对账。

    **按 ``actual["mode"]`` 分派两套口径** (2026-10-07, 依据回放层删除):

    - ``live`` (现行): 三个子项里只有**截断三元组自洽**与**排序单调性**是无条件判据;
      「序列逐位一致」「分页无损 vs 固定行集」「页数等于期望页数」三项都依赖**一份
      冻结的期望值** —— 实测同一查询快照记 1 行、真站点返 174 行, 拿会过期的行集
      比对必然大面积失配, 而失配里没有一条能指向被测代码的缺陷。故 live 口径下:
      排序只判单调、分页只判**无重** (跨页重复是纯客户端缺陷, 不依赖任何期望值)、
      截断判三元组**内部自洽**而非等于 gold 的数字。
    - ``replay`` (:func:`_replay_structure`): 回放臂已随快照一并删除, 保留是为了让
      「这条臂没了」在 grep 里可查 —— 没有实现, 传入即显式报错而不是静默降级。

    失守项如实登记在 ``docs/REPLAY-RETIREMENT-CRITERIA.md`` §3.2, 不是悄悄消失。
    """
    rows = actual.get("rows") or []          # 汇总后的标准行集
    envelope = actual.get("envelope") or {}  # 信封面: 截断三元组的实际侧
    pages = actual.get("pages") or []        # [[行...], [行...]] 各页内容
    # 主键前缀判据与 M1/M2 同源: run_e2 按**查询**给的批量标记。站点对锥搜响应
    # 同样回 inputobjs_input_line, 按行推断会把锥搜全量错判成批量行, 于是
    # 期望序列与实际序列永远对不上。
    batch = actual.get("batch_keys")
    coords_only = not id_keys_unique(rows)   # id 唯一性与 M1/M2/oracle 同一判据: 序列比对必须同尺
    line_offset = batch_line_offset(rows)    # input_line 基准: 与 M1/M2/oracle 同一判据, 序列必须同尺

    if str(actual.get("mode") or "replay") != "live":
        return _replay_structure(gold, actual, rows, envelope, pages, batch, coords_only, line_offset)

    # ── live 口径: 只判不依赖期望值的子项 ──

    # 排序: 只判**单调性**。单调是排序请求的自带契约 (站点按声明列排, 返回就必须单调),
    # 与具体有哪些行无关 —— 这是实跑下仍然成立的那一半。
    ordering = gold.get("ordering") or {}
    sort_key_name = ordering.get("key")      # None = 场景未声明排序, 本项不判
    order = str(ordering.get("order", "asc"))
    sort_pass = True                         # 未声明排序时默认过: 不给"没要求"记失败
    sort_detail: dict = {}                    # 未声明排序时为空: 报告据此分辨「没要求」
    if sort_key_name:
        if batch and sort_key_name == "input_index":
            # 批量响应不保证按 input_line 排序 —— 实测 (2026-10-08) 1000 行该列为
            # 286,259,260,275,274,... 完全无序 (1000 个唯一值, 覆盖 1..1000 无缺)。
            # 服务端对批量行顺序**没有契约**, 客户端也无权改写回包顺序; 判它单调
            # 等于给一条不存在的契约记失败。与 _monotonic_live 对哨兵的豁免同源:
            # 站点怎么排不是客户端违约。本项记 N/A (不阻断), 覆盖完整性归 M1。
            sort_detail = {"key": sort_key_name, "order": order, "monotonic": None,
                           "criterion": "N/A: 批量响应不保证按 input_line 排序 (实测无序)",
                           "sequence_match": "N/A(实跑无冻结期望序列)"}
        else:
            column = {"input_index": "inputobjs_input_line"}.get(sort_key_name, sort_key_name)  # 唯一映射
            values = [r.get(column) for r in rows]  # 取映射后的列
            # 哨兵不参与单调性: 站点把缺测占位混在排序列里 (实测 -1003.88 排在最前),
            # 那是站点的排布而不是客户端违约, 见 _monotonic_live 的完整理由。
            sort_pass, n_real = _monotonic_live(values, order, _sentinel_threshold())
            sort_detail = {"key": sort_key_name, "order": order, "monotonic": sort_pass,
                           "real_values": n_real,          # 参与判定的真实值个数: 全缺测时为 0
                           "sentinels_excluded": len(values) - n_real,  # 被排除的哨兵数, 供人核对
                           # 如实标出 live 口径**不判**序列逐位: 那是依赖冻结行集的那一半
                           "sequence_match": "N/A(实跑无冻结期望序列)"}

    # 分页: 只判**无重**。跨页重复是纯客户端缺陷 (同一行被两页各返一次), 与站点
    # 数据新旧无关, 实跑下完全可判。**无损**(并集==期望行集) 则依赖冻结行集, 不判。
    page_pass = True
    page_detail: dict = {"criterion": "无跨页重复 (无损需冻结行集, 实跑不判)"}
    if pages:
        seen, overlap = set(), 0
        for page in pages:                      # 逐页扫: 跨页重复要跟已扫过的所有页比, 只比上一页会漏掉隔页重复
            page_keys = key_set(page, batch=batch)  # 每页主键集合现算: 页与页之间不共享任何状态
            overlap += len(seen & page_keys)     # 与已扫过的所有页的交集
            seen |= page_keys                    # 并进已见集合: 下一页的交集判据依赖它
        page_pass = overlap == 0
        page_detail.update({"actual_pages": len(pages), "overlap_keys": overlap, "lossless": "N/A(实跑无冻结行集)"})

    # 截断: 三元组**内部自洽**。total/returned/truncated 三者之间必须说得通,
    # 这不需要任何期望值; 但「等于 gold 的数字」需要, 故 live 口径不判后者。
    actual_total = envelope.get("total_count")
    actual_truncated = envelope.get("truncated")
    actual_returned = envelope.get("returned_count")
    if actual_total is None or actual_returned is None:
        trunc_pass = True   # 站点没给计数 (错误态/空结果态): 无可比对象, 由 M5 判状态
        trunc_detail = {"criterion": "计数缺失 -> 不判 (M5 接管状态)"}
    else:
        trunc_pass = (actual_returned <= actual_total                    # 返回数不得多于服务端总数
                      and (not actual_truncated or actual_returned <= actual_total))  # 截断时更不能多于
        trunc_detail = {
            "criterion": "三元组内部自洽 (与 gold 数字比对需冻结行集, 实跑不判)",
            "actual": [actual_total, actual_truncated, actual_returned],
        }

    passes = sum([sort_pass, page_pass, trunc_pass])
    return {
        "mode": "live",
        "score": passes / 3.0,     # 三项等权: 结构类不分主次, 缺一项就是三分之二
        "pass": passes == 3,       # 必须三项全过: 结构错一半仍是结构错
        "ordering": {"pass": sort_pass, **sort_detail},
        "pagination": {"pass": page_pass, **page_detail},
        "truncation": {"pass": trunc_pass, **trunc_detail},
        "blockers": [] if passes == 3 else ["structure_mismatch"],  # 单一阻断项: 定位到 M4 本项
    }


def _replay_structure(gold, actual, rows, envelope, pages, batch, coords_only, line_offset) -> dict:
    """冻结 lane：对排序序列、逐页并集和截断三元组作精确核验。"""
    ordering = gold.get("ordering") or {}
    sort_key_name = ordering.get("key")
    order = str(ordering.get("order", "asc"))
    sort_pass = True
    sort_detail: dict = {}
    if sort_key_name:
        column = {"input_index": "inputobjs_input_line"}.get(sort_key_name, sort_key_name)
        values = [row.get(column) for row in rows]
        monotonic = _monotonic(values, order)
        actual_sequence = [row_key(row, batch=batch, coords_only=coords_only,
                                   line_offset=line_offset) for row in rows]
        expected_sequence = list(ordering.get("sequence") or [])
        sequence_match = not expected_sequence or actual_sequence == expected_sequence
        sort_pass = monotonic and sequence_match
        sort_detail = {"key": sort_key_name, "order": order,
                       "monotonic": monotonic, "sequence_match": sequence_match}

    pagination = gold.get("pagination") or {}
    if batch:
        # Proximity is a single submitted batch response, not a paginated SQLID session.
        # Gold declares pages=0/N/A; do not compare its rows against an empty page union.
        pagination_detail = {"expected_pages": 0, "actual_pages": 0,
                             "lossless": "N/A(batch proximity)", "overlap_keys": 0,
                             "extra_empty_page_expected": False,
                             "terminal_empty_page_seen": False,
                             "criterion": "N/A: batch proximity is not paginated"}
        ordering = gold.get("ordering") or {}
        sort_pass = True
        sort_detail = {"key": ordering.get("key"), "order": ordering.get("order"),
                       "monotonic": True, "sequence_match": True,
                       "criterion": "batch order checked by M1 compound keys"}
        truncation = gold.get("truncation") or {}
        actual_total = envelope.get("total_count")
        actual_truncated = envelope.get("truncated")
        actual_returned = envelope.get("returned_count")
        trunc_pass = (actual_total == truncation.get("expected_total")
                      and actual_truncated is truncation.get("expected_truncated")
                      and actual_returned == truncation.get("expected_returned"))
        trunc_detail = {"gold": [truncation.get("expected_total"), truncation.get("expected_truncated"), truncation.get("expected_returned")],
                        "actual": [actual_total, actual_truncated, actual_returned]}
        passes = sum((sort_pass, True, trunc_pass))
        return {"mode": "replay", "score": passes / 3.0, "pass": passes == 3,
                "ordering": {"pass": sort_pass, **sort_detail},
                "pagination": {"pass": True, **pagination_detail},
                "truncation": {"pass": trunc_pass, **trunc_detail},
                "blockers": [] if passes == 3 else ["structure_mismatch"]}
    expected_pages = int(pagination.get("pages", 0))
    gold_keys = set(gold.get("row_keys") or [])

    def page_keys(page):
        return {row_key(row, batch=batch, coords_only=coords_only,
                        line_offset=line_offset) for row in page}

    per_page = [page_keys(page) for page in pages]
    seen: set[str] = set()
    overlap = 0
    for keys in per_page:
        overlap += len(seen & keys)
        seen |= keys
    lossless = seen == gold_keys
    page_pass = len(pages) == expected_pages and lossless and overlap == 0
    extra_empty_expected = bool(pagination.get("extra_page_expected_empty"))
    terminal_empty_seen = bool(actual.get("terminal_empty_page_seen"))
    if extra_empty_expected:
        page_pass = page_pass and terminal_empty_seen
    page_detail = {"expected_pages": expected_pages, "actual_pages": len(pages),
                   "lossless": lossless, "overlap_keys": overlap,
                   "extra_empty_page_expected": extra_empty_expected,
                   "terminal_empty_page_seen": terminal_empty_seen}

    truncation = gold.get("truncation") or {}
    expected_total = truncation.get("expected_total")
    expected_truncated = truncation.get("expected_truncated")
    expected_returned = truncation.get("expected_returned")
    actual_total = envelope.get("total_count")
    actual_truncated = envelope.get("truncated")
    actual_returned = envelope.get("returned_count")
    if gold.get("result_state") in ("error", "empty") and not gold_keys:
        trunc_pass = True
    else:
        trunc_pass = (actual_total == expected_total
                      and actual_truncated is expected_truncated
                      and actual_returned == expected_returned)
    trunc_detail = {"gold": [expected_total, expected_truncated, expected_returned],
                    "actual": [actual_total, actual_truncated, actual_returned]}
    passes = sum((sort_pass, page_pass, trunc_pass))
    return {"mode": "replay", "score": passes / 3.0, "pass": passes == 3,
            "ordering": {"pass": sort_pass, **sort_detail},
            "pagination": {"pass": page_pass, **page_detail},
            "truncation": {"pass": trunc_pass, **trunc_detail},
            "blockers": [] if passes == 3 else ["structure_mismatch"]}

