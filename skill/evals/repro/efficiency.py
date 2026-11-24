# -*- coding: utf-8 -*-
"""evals.repro.efficiency — E6 效率指标 EF1..EF7 (编号避撞实验编号 E1..E7)。

能力边界: 从 trace 的 cost 信封 (http_requests/elapsed_s/rows_returned,
session 唯一出口实测计数 — 非估算) 算效率七指标。边界: 只报数不调参
(文档 §1.2 非目标); 墙钟分含/不含 rate_limit 两口径 (默认 2.0s/请求会
把墙钟拉长数倍, 不注明则数字不可解释 — 文档 §6 两坑)。

理论最小请求数 (EF1 分母): cone_search = 2 (POST 建 sqlid + 1 页 GET);
count = 1; fetch_page = 1; list_catalogs/describe_catalog = 0 (元数据零请求)。

职责: 从 trace 的 cost 信封算出 E6 的七个效率指标 EF1..EF7, 回答"这次
  运行为什么这么贵" —— 贵在请求数、墙钟、冗余调用还是重试策略。
所属实验: E6 可复现与效率 (32 任务 + R0 路实跑); 指标编号与口径真值是
  docs/eval-E6-reproducibility.md §6, 冗余口径与 E1 §6.4 对齐, 汇总值是
  报告 §12 第 8 个数的唯一来源。
对外接口: summarize_efficiency(runs, ...) 一次性给出全部七项; 另有
  ef1_request_ratio / ef2_wall_clock / ef3_redundant_calls /
  ef4_ineffective_retries / ef5_paging / ef6_zero_request_completion /
  ef7_tokens 七个可单测的分项, 以及 theoretical_min_requests 与
  _percentile 两个支撑件。
依赖与数据流: 输入 = 各次运行的 cost 信封 (http_requests / elapsed_s /
  rows_returned —— 全部是 session 唯一出口的实测计数) 与 tool_calls /
  retries / usage 记录; 产物 = 纯字典, 汇入 evals/repro/run_e6.py 的报告,
  自身不落盘、不读盘。
关键契约与不变量: 纯离线统计, 零请求零外联; 同一组 runs 重复统计必须得到
  逐位相同的结果 (分位数走固定插值公式, 不引入随机); 零跨实验 import,
  上游只有标准库, 与其它实验的等价性由 evals/equivalence/ 的断言守护。
陷阱与边界: 墙钟必须同时给含/不含 rate_limit 两种口径 —— 默认 2.0s/请求
  的节流会把墙钟拉长数倍, 只报一个数就等于让读者无法判断耗时是服务慢
  还是被节流 (文档 §6 坑 1)。EF7 的 null 一律留 null, 绝不用字符数估算
  token: 估出来的数会被当真值引用, 那比缺数据有害得多。EF1 比值封顶
  1.0, 因为理论上不可能比理论最小还省, 出现 >1 说明计数口径有错。
"""
from __future__ import annotations

# 标准库: 数学 (ceil 分页页数) 与集合 (众数)
import math

THEORETICAL_MIN_REQUESTS = {  # 理论最小请求数: EF1 的分母口径 (文档 §6)
    "cone_search": 2,
    "count": 1,
    "fetch_page": 1,
    "resolve_name": 1,
    "crossmatch_batch": 2,
    "list_catalogs": 0,
    "describe_catalog": 0,
}
METADATA_TOOLS = frozenset({"list_catalogs", "describe_catalog"})  # EF6 对象: 这两个本不该走 wire


def _percentile(values: list[float], pct: float) -> float:
    """线性插值分位数 (P50/P90; 空表返回 0.0)。

    作用: 算 EF2 用的分位点。关键参数 values 是样本, pct 是 0..100 的
    百分位。Returns: 插值后的分位值。抛什么: 不抛; 空表给 0.0。
    """
    # 空表给 0.0 而不是抛: 某个 run 没有耗时样本不该让整轮统计崩掉,
    # 0.0 在 P50 语境下是"没观测到耗时", 会被上层如实披露
    if not values:                                                                   # 空表给 0.0 而不抛: 某个 run 没有耗时样本不该让整轮统计崩掉
        return 0.0
    ordered = sorted(values)  # 先排序: 分位数靠下标取值, 与输入顺序无关
    # 单样本时分位数无插值可言, 直接返回该样本, 免得下面算 rank 时
    # 除以 0
    if len(ordered) == 1:                                                        # 单样本直接返回该样本: 下面算 rank 时会除以零, 插值对小样本也没有意义
        return ordered[0]
    # 线性插值而非取最近邻: N=5 的小样本下最近邻会把 P90 压成最大值,
    # 线性插值给出的区间端点更接近真实分位 (文档 §5.5 的诚实口径)
    rank = pct / 100.0 * (len(ordered) - 1)  # rank 可为小数: 其小数部分就是插值权重
    low = int(math.floor(rank))                                                      # 取下界下标: rank 的小数部分就是插值权重, 整数部分决定取哪两格
    high = int(math.ceil(rank))                                                            # 取上界下标: 与下界一起框出插值区间, 两者相等即无需插值
    if low == high:                                                                   # rank 恰为整数时直接取值: P0/P50 在偶数样本上会落在这里
        # rank 恰为整数 (P0/P50 在偶数样本上) 时不需要插值
        return ordered[low]
    return ordered[low] + (ordered[high] - ordered[low]) * (rank - low)  # 固定公式: 重复跑逐位相同


def theoretical_min_requests(calls: list[dict]) -> int:
    """一次运行的理论最小请求数 (按工具表累加; 未知工具按 1 计)。

    作用: 算 EF1 的分母。关键参数 calls 是该次运行的调用序列。
    Returns: 理论最小请求数总和。抛什么: 不抛。
    """
    # 未知工具按 1 计而不是跳过: 表里没有的工具说明是新加的, 按 1 计
    # 相当于"至少一次往返"的保守估计, 跳过会让 EF1 被算成满分
    return sum(THEORETICAL_MIN_REQUESTS.get(str(c.get("tool")), 1) for c in calls or ())


def ef1_request_ratio(runs: list[dict]) -> dict:
    """EF1 请求效率比 η = 理论最小请求数 ÷ 实际 http_requests (按 run 求均值)。

    作用: 衡量每次运行离理论最优有多近。关键参数 runs 是各次运行记录
    (需带 cost.http_requests 与 tool_calls)。Returns: {"ef1", "per_run"}。
    抛什么: 不抛。
    """
    ratios = []  # 逐 run 的 η: 只收"有请求"与"零请求元数据"两类样本
    for run in runs:                                                                     # 逐 run 算 η: 只收「有请求」与「零请求元数据」两类样本
        actual = int((run.get("cost") or {}).get("http_requests", 0))  # 实际请求数: session 出口实测, 非估算
        theoretical = theoretical_min_requests(run.get("tool_calls") or [])  # 分子: 同 run 调用序列查表累加
        if actual > 0:                                                              # 只在有实际请求时收样本: 零请求却声称完成数据任务是链路失败, 不是效率
            # 封顶 1.0: 比理论最小还省的 η>1 一定是计数口径出了问题
            # (比如批量接口把多次往返记成一次), 报出去会误导归因
            ratios.append(min(1.0, theoretical / actual))                              # 封顶 1.0: η>1 一定是计数口径出了问题, 报出去会误导归因
        elif theoretical == 0:
            ratios.append(1.0)  # 元数据类零请求 = 完美效率
        # actual==0 且 theoretical>0 的运行被整条略过: 一次请求都没发却
        # 声称完成了要访问数据的任务, 那是链路失败, 不是效率样本,
        # 混进均值会把 EF1 稀释
    return {"ef1": sum(ratios) / len(ratios) if ratios else 0.0,  # 分母是被收下的样本数, 不是 runs 数
            "per_run": ratios}


def ef2_wall_clock(runs: list[dict], rate_limit_seconds: float = 2.0) -> dict:
    """EF2 墙钟 P50/P90 (含/不含 rate_limit 两种口径 — 文档 §6 坑 1)。

    作用: 给出耗时的分位点。关键参数 runs 是各次运行记录, rate_limit_seconds
    是每次请求的节流秒数。Returns: 四个分位值。抛什么: 不抛。
    """
    elapsed = [float((run.get("cost") or {}).get("elapsed_s", 0.0)) for run in runs]  # 总耗时: 含节流等待
    requests = [int((run.get("cost") or {}).get("http_requests", 0)) for run in runs]
    # 不含节流口径 = 总耗时减去"纯等待节流"的理论份额。乘 2.0 是假设
    # 每次请求都真的撞上了节流窗口, 属于上界扣除 —— 宁可高估耗时,
    # 也不要给出一个偏乐观的"去掉节流后只要 0.3 秒"
    without = [e - r * rate_limit_seconds for e, r in zip(elapsed, requests)]       # 按每次请求都撞上节流窗口扣减: 属上界扣除, 宁可高估耗时也不给偏乐观值
    return {
        "with_rate_limit_p50": _percentile(elapsed, 50),
        "with_rate_limit_p90": _percentile(elapsed, 90),
        "without_rate_limit_p50": _percentile(without, 50),
        "without_rate_limit_p90": _percentile(without, 90),
    }


def ef3_redundant_calls(runs: list[dict]) -> dict:
    """EF3 冗余调用率 (多余的 cone_search/crossmatch_batch ÷ 总调用数)。

    口径对齐 E1 §6.4: 重复调用 (同工具同参数) 与元数据走 wire 均记冗余。
    """
    redundant = total = 0  # 分子/分母: 冗余调用数与总调用数
    for run in runs:                                                     # 逐 run 判重: 每个 run 独立 seen, 跨 run 的相同调用是「可复现」不是冗余
        # 跨 run 不共享 seen: 每个 run 独立判重 —— 一次运行的两次相同调用
        # 是冗余, 不同运行之间的相同调用是"可复现"的表现, 混判会把
        # EF3 与 TSC 这类一致性指标搅在一起
        calls = run.get("tool_calls") or []
        total += len(calls)  # 分母按调用数, 不按 run 数
        seen: set = set()                                                 # seen 每个 run 重建: 与 EF1 同理, 跨 run 判重会把一致性与效率搅在一起
        for call in calls:                                                                 # 按调用顺序扫: 第二次出现同工具同参数才记冗余, 首次不算
            # 键 = 工具名 + 排序后的参数对: 参数顺序不参与判重
            key = (call.get("tool"),
                   tuple(sorted((k, str(v)) for k, v in (call.get("args") or {}).items())))
            if key in seen:  # 本 run 内第二次出现同工具同参数即冗余
                redundant += 1                                                    # 分子按「第二次起」计: 首次调用是必要成本, 把它算进冗余会凭空抬高 EF3
            seen.add(key)                                                                  # 无论是否冗余都入 seen: 第三次同样参数仍要被认成冗余
    return {"ef3": redundant / total if total else 0.0,  # 分母 0 记 0.0: 没调用过不等于零冗余
            "redundant": redundant, "total": total}


def ef4_ineffective_retries(runs: list[dict]) -> dict:
    """EF4 无效重试率 (strategy_changed=false 的原样重试 ÷ 总重试)。

    作用: 抓"失败了但没换策略就再试一遍"的空转。关键参数 runs 是各次
    运行记录 (需带 retries)。Returns: {"ef4", "ineffective", "total"}。
    抛什么: 不抛。
    """
    ineffective = total = 0  # 分子/分母: 无效重试数与总重试数
    for run in runs:                                                                          # 逐 run 遍历重试: 分子分母都只在这批重试上统计
        for retry in run.get("retries") or ():
            total += 1                                                                     # 分母按重试数: 按 run 数算会让重试多的任务权重被压低
            # 只认显式 False: 字段缺失表示"链路没记录是否换策略", 判成
            # 无效重试会把记录不全的 run 一律打成空转, 那是数据问题
            # 而不是被测系统的行为
            if retry.get("strategy_changed") is False:
                ineffective += 1                                                  # 只认显式 False: 字段缺失是「没记录是否换策略」, 判成空转是数据问题
    return {"ef4": ineffective / total if total else 0.0,  # 分母 0 记 0.0: 没重试过的任务不参与平均
            "ineffective": ineffective, "total": total}


def ef5_paging(runs: list[dict], page_size: int = 1000) -> dict:
    """EF5 分页效率 (fetch_page 次数 vs ceil(count/page_size); 过量翻页记数)。

    作用: 抓"翻页翻过头"。关键参数 runs 是各次运行记录, page_size 是每页
    行数上限。Returns: {"ef5_over_paging": 累计多翻的页数}。
    抛什么: 不抛。
    """
    over = 0  # 累计多翻的页数, 不是"是否过量"的布尔
    for run in runs:                                                                     # 逐 run 累计多翻页数: 指标要的是可折算的页数, 不是布尔
        fetches = sum(1 for c in (run.get("tool_calls") or []) if c.get("tool") == "fetch_page")  # 只数 fetch_page
        total_rows = (run.get("cost") or {}).get("rows_returned")
        if total_rows is None:                                                       # 拿不到行数就跳过: 猜出来的「过量翻页」会指向一个根本没问题的 run
            # 拿不到行数就算不出应翻几页, 跳过而不是猜: 猜出来的"过量翻页"
            # 会指向一个根本没问题的 run
            continue
        # -1 是因为首页已含在 cone_search 里, 那个 GET 不再单算 fetch_page
        expected = max(0, math.ceil(int(total_rows) / page_size) - 1)  # 首页含在 cone_search 里
        # 只累计超出量而非"是否过量": 报告要的是总共多翻了几页, 才能折算
        # 成可省的请求数
        if fetches > expected:                                                          # 只累计超出部分: 报告要的是总共多翻了几页, 才能折成可省请求数
            over += fetches - expected                                                     # 累加而非置位: 多次过量要能折算成总浪费, 布尔表达不了量
    return {"ef5_over_paging": over}  # EF5 只带这一个量: 多翻的页数


def ef6_zero_request_completion(runs: list[dict]) -> dict:
    """EF6 零请求完成率 (元数据类任务实际请求数 = 0 的比例; 硬门槛)。

    作用: 守住"元数据类问题不许走 wire"这条硬门槛。关键参数 runs 是各次
    运行记录。Returns: {"ef6", "metadata_runs"}。抛什么: 不抛。
    """
    # 先筛出元数据类运行: 分子分母都只在这个子集上算, 把有数据任务的
    # 请求数混进来会凭空拉低完成率
    metadata_runs = [                                                                     # 先筛子集再算比例: 有数据任务的请求数混进来会凭空拉低完成率
        run for run in runs                                                    # 任一调用属元数据工具即入选: 元数据类 run 可能同时查了别的, 仍要受门槛约束
        if any(c.get("tool") in METADATA_TOOLS for c in (run.get("tool_calls") or []))
    ]
    if not metadata_runs:
        # **记 None 而不是 1.0** (EF6 修复, D 组同族修法: 不可判定要显式标记, 别回落到
        # 最优值)。原式返回 ``{"ef6": 1.0, "metadata_runs": 0}``, 而 1.0 读作"全部
        # 元数据问题都零请求达标"的满分 —— 可这里一条都没跑到。"没测过"被伪装成
        # "测过且全对", 门禁看到 1.0 就放行: 这是最隐蔽的一种 fail-open, 缺证据被
        # 读成了好结果。
        #
        # None 与 0.0 的区别必须保留: 0.0 是"跑了且全违规" (真结论, 该红), None 是
        # "没跑" (缺证据, 归 E6 的覆盖率判据去拦, 本项不替它判红也不替它判绿)。
        return {"ef6": None, "metadata_runs": 0}
    zero = sum(1 for run in metadata_runs  # 分子: 实际请求数为 0 的元数据类运行数
               if int((run.get("cost") or {}).get("http_requests", 0)) == 0)
    return {"ef6": zero / len(metadata_runs), "metadata_runs": len(metadata_runs)}  # n 一并报出供披露


def ef7_tokens(runs: list[dict]) -> dict:
    """EF7 token 成本 (external: 由 harness 提供 usage; 缺失记 null 不估算)。

    作用: 透传 token 成本。关键参数 runs 是各次运行记录 (可带 usage)。
    Returns: 两个逐 run 的列表 + 一句口径说明。抛什么: 不抛。
    """
    # 缺失就留 None: 任何"按字符数/按分词估算"的填补都会产出一个看起来
    # 像实测值的数字, 进了报告就被当真引用 —— 那比明确留空有害得多
    tin = [ (run.get("usage") or {}).get("tokens_in") for run in runs ]
    tout = [ (run.get("usage") or {}).get("tokens_out") for run in runs ]
    return {"ef7_tokens_in": tin, "ef7_tokens_out": tout,  # 附口径说明: 报告须原样带出"null 禁止估算"
            "note": "external; null = harness 未提供, 禁止估算填数"}


def summarize_efficiency(runs: list[dict], rate_limit_seconds: float = 2.0,
                         page_size: int = 1000) -> dict:                 # page_size 走参数: 页大小是 manifest 声明的口径, 写死会让不同批次不可比
    """EF1..EF7 汇总 (报告 §12 第 8 个数的一次性来源)。

    作用: 一次调用给出全部七项。关键参数 runs 是各次运行记录,
    rate_limit_seconds 是节流秒数, page_size 是分页行数上限。
    Returns: 七项指标合并的字典。抛什么: 不抛, 任一分项都不抛。
    """
    # 用 ** 展开而不是手工列键: 少写一次键名就少一处拼写漂移, 而报告
    # §12 的第 8 个数是直接消费这个字典的, 键名错了报告就缺项
    return {
        **ef1_request_ratio(runs),
        **ef2_wall_clock(runs, rate_limit_seconds),
        **ef3_redundant_calls(runs),
        **ef4_ineffective_retries(runs),
        **ef5_paging(runs, page_size),
        **ef6_zero_request_completion(runs),
        **ef7_tokens(runs),
    }
