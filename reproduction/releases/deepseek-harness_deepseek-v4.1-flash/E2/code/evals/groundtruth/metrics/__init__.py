# -*- coding: utf-8 -*-
"""evals.groundtruth.metrics — E2 七指标 (M1–M7) 与汇总。

职责: 把 SUT 规范化结果 (canonical 行集 + 信封) 与金标准 (gold JSON)
逐指标对账, 产出每指标得分/pass/失败明细 + 阻断项清单, 并按权重汇成一个
case 级判定。它是 E2 的判分中枢, 七个指标件都不直接写报告。

能力边界: 纯 Python 计算, fail-closed; 容差与哨兵字典外置 (evals/_data),
不在代码硬编码。边界: 不负责抓数据 (那是 ``canonical.py`` 与
``transport.py`` 的活), 也不负责跑批编排 (那是 ``run_e2.py``)。

所属实验: E2 金标准一致性, 方案真值 docs/eval-E2-groundtruth.md §6 (指标
体系与确定性判定算法) 与 §8 (反证夹具 metascore); 容差/单位/精度/量程
四张表在 evals/_data/tolerances.yaml。

对外接口: ``compare_case()`` 对账一个 case 并给汇总判定; ``metascore()``
算反证夹具覆盖率; ``check_weight_sum()`` 校验权重和恰为 1.00;
``M_WEIGHTS``/``PASS_SCORE``/``WARN_SCORE`` 是报表与门禁共享的阈值常量。

**按接线分派 (2026-10-07, 裁定 D6 两层职责)**: 各指标件读 ``actual["mode"]``
决定判哪一套 —— ``replay`` 判逐行对账 (固定 gold 行集), ``live`` 判内部不变量
(活数据随时间变, 固定行集必然过期)。目前只有 M1 与 M6 分派: M6 在 live 下把
版本身份移出声明集并显式记 ``reconcilable=False``。其余指标两套共用, 因为它们
判的是字段/量纲/结构/状态这些**不依赖跨时间期望值**的性质。

依赖与数据流: 输入是 gen_gold.py 产出的金标准 JSON 与被测侧对账输入字典。
replay 层来自离线快照回放 (不发真实请求, rate_limit 归零); live 层来自
真站点直连。产物随 E2 的报告 JSON 落盘, 本包自己不写文件。

关键契约与不变量: 权重和必须恰为 1.00, 每个 case 判分前先校验 ——
配错权重会让所有历史报告失去可比性, 属于必须在跑批前就炸的配置损坏;
阻断项任一命中即 pass=False, **加权分不得覆盖阻断** (分数高不能洗掉
"版本污染"这类证伪级问题); 指标不适用时以 score=None 退出分母而不是
记 0 分; 零跨实验 import, 唯一共享件是 ``evals/_data/`` 纯数据字典,
跨实验判定口径的一致性由 ``evals/equivalence/`` 断言守护。

陷阱与边界: 阈值 0.90 / 0.85 是放行与告警的分界, 调它们等于改 E2 的
判定标准, 必须同步改方案文档, 否则门禁与文档会各说一套; metascore 的
分母是夹具总数, 少算一条会让"夹具没被发现"看起来仍满分 —— 新增反证
夹具后这里要跟着验证, 它是判定器自身有效性的证据, 不是被测对象的分数。
"""
from __future__ import annotations

# 本地: 七指标实现 (每个文件一个指标, 守 400 行预算)
from evals.groundtruth.metrics.m1_rows import score_m1
from evals.groundtruth.metrics.m2_fields import score_m2
from evals.groundtruth.metrics.m3_units import score_m3
from evals.groundtruth.metrics.m4_structure import score_m4
from evals.groundtruth.metrics.m5_states import score_m5
from evals.groundtruth.metrics.m6_version import score_m6
from evals.groundtruth.metrics.m7_determinism import score_m7

# E2 §6 加权汇总 (和 = 1.00; 启动即校验)。权重按"对错后果"分配: 行集
# 错 (0.30) 与字段错 (0.25) 直接让用户拿到错数据; 结构 (0.15) 关系到
# 分页/截断语义; 单位与状态各 0.10; 版本与确定性各 0.05 —— 后两项是
# 自证性判据, 正常实现都该满分, 给高权重等于奖励"报得很自信"
M_WEIGHTS: dict[str, float] = {  # 七项权重之和恒为 1.0, 由 check_weight_sum 在导入时钉死
    "m1_rows": 0.30,  # 行集精度权重最高: 分页重复/截断是最常见的失真, 代价最大
    "m2_fields": 0.25,
    "m3_units": 0.10,
    "m4_structure": 0.15,  # 结构判据次高: total/returned/truncated 对不上等于结论不可信
    "m5_states": 0.10,
    "m6_version": 0.05,
    "m7_determinism": 0.05,
}

# 放行线 0.90 与告警线 0.85 的间距 0.05 是刻意留的: 刚好卡在门槛上的
# 实现与稳定越过门槛的实现不该拿同一个评价, 告警线给的是"还没坏但要盯"
PASS_SCORE = 0.90  # 放行线与 E1 同款 0.90, 便于跨实验读分
WARN_SCORE = 0.85  # 告警线: 与放行线留 0.05 间距, 刚卡门槛与稳定越线不该同评


def check_weight_sum() -> None:
    """M_WEIGHTS 和必须恰为 1.00 (启动即校验)。"""
    total = sum(M_WEIGHTS.values())  # 七项各自维护, 单看某一项无从发现配错
    # 容差 1e-9 只吃浮点求和噪声: 七个 0.05/0.10 之类十进制字面量在
    # 二进制下求和不可能精确为 1, 但任何真实配置错误都远大于这个量级
    if abs(total - 1.0) > 1e-9:  # 权重和偏离即抛: 静默跑完会给出"看起来完整"的假综合分
        raise ValueError(f"M_WEIGHTS 和 {total} != 1.00 — 权重配置损坏")


def compare_case(gold: dict, actual: dict) -> dict:
    """对账一个 case: 七指标各自打分 + 阻断项 + 汇总。

    Args:
        gold: gen_gold.py 产出的金标准 JSON (含 row_keys/field_values/
            null_semantics/unit_map/precision_map/ordering/pagination/
            truncation/result_state/snapshot_id/data_version)。
        actual: SUT 侧对账输入 ``{"rows": [标准行], "envelope": {...},
            "provenance": {...}, "data_hashes": [3 次跑批哈希],
            "declared_http_requests": n, "observed_http_requests": n}``。

    Returns:
        ``{"metrics": {m1..m7: {...}}, "blockers": [...], "weighted": float,
        "pass": bool}`` — 阻断项任一命中即 pass=False (加权分不得覆盖)。
    """
    check_weight_sum()  # 每次对账先验权重, 防止有人改表后忘了验
    # 七个指标全跑而不是遇到失败就短路: 报告要一次给全, 让人在一处看到
    # 全部失分点; 短路会让"先修哪个"变成反复跑批才能回答的问题
    metrics = {  # 七项全跑不短路: 报告要一次给全, 短路会让"先修哪个"必须反复跑批才答得出
        "m1_rows": score_m1(gold, actual),
        "m2_fields": score_m2(gold, actual),
        "m3_units": score_m3(gold, actual),
        "m4_structure": score_m4(gold, actual),
        "m5_states": score_m5(gold, actual),
        "m6_version": score_m6(gold, actual),
        "m7_determinism": score_m7(gold, actual),
    }
    # 阻断项加指标名前缀: 不同指标可能用同一个 blocker 词, 不带前缀的报告
    # 无法回答"是哪一条判据在拦", 排查就得回去逐个函数读
    blockers: list[str] = []  # 攒全而非只留首条: 一次对账常命中多条, 只报一条会误导排查顺序
    for name, result in metrics.items():  # 逐指标收集, 遍历序即报告里的展示序
        blockers.extend(f"{name}:{b}" for b in result.get("blockers", ()))  # 逐项收集阻断原因: 报告要能指名是哪一项哪一条, 不给笼统的 FAIL
    # None = 该指标对本 case 不适用 (如空结果态无比对字段) — 不进分母
    weighted = sum(  # 只对 score 非 None 的指标加权: 不适用项退出分母而不是记 0 分
        M_WEIGHTS[name] * result["score"]  # 权重 × 得分: 权重按对错后果分配, 不按实现难度
        for name, result in metrics.items() if result.get("score") is not None  # 与下方分母同一过滤条件, 两处必须一致
    )
    # 分母是"实际参与打分的权重和"而非 1.00: 不适用指标退出后必须按比例
    # 归一, 否则空结果态 case 会被剩下几个指标摊薄成虚低分
    weight_total = sum(  # 分母另算一份: 直接除 1.00 会把不适用项算成丢分
        M_WEIGHTS[name]  # 只累加参与打分的权重, 不适用项不按 0 计
        for name, result in metrics.items() if result.get("score") is not None  # 与分子同一过滤条件, 缺一处归一就失真
    )
    # 权重和为 0 (所有指标都不适用) 记 0.0 而非 1.0: 这种 case 等于
    # 什么都没验出来, 不该拿满分混进报表均值
    weighted = weighted / weight_total if weight_total else 0.0  # 分母用实际参与项的权重和, 缺项不按 0 计也不虚抬总分
    return {
        "metrics": metrics,  # 原样带回七项: 报告与门禁都读这一份, 不二次计算
        "blockers": blockers,  # 阻断项独立成字段: 加权分再高也洗不掉证伪级问题
        "weighted": weighted,  # 归一后的综合分: 缺项按剩余权重缩放, 不按 0 摊薄
        # 加权分只管"够不够好", 阻断项管"是不是错到不能信";
        # 但**单项不过就是不过**: 放行判据取「七项全过 + 零红线」, 与
        # docs/eval-E2-groundtruth.md ③ 放行行 (「7 项全过 + 零红线才 exit 0;
        # 任一不过即阻断」) 以及 run_e2.py 里 n_pass 那行的注释一致。
        #
        # 此前这里是 `(weighted >= PASS_SCORE) and not blockers` —— 只看加权
        # 均分, 单项的 pass 位不进判据, 于是"某项不过但均分仍 ≥ 0.90"的
        # case 照放行。实测 17 个 case 里 12 个是这种情形 (失败项全是 m3_units)。
        # 一句指标不过可以被别的指标把均值拉回来洗掉, 正是铁律 5 禁的那类:
        # 门禁显示通过, 而它本该拦下的事发生了。
        # weighted 仍随结果返回: 报告要用它排序和看差距, 只是不再当放行条件。
        "pass": not any(m.get("pass") is False for m in metrics.values()) and not blockers,  # 七项全过且零红线
    }


def metascore(broken_results: list) -> float:
    """反证夹具 metascore = 被抓中的坏样本数 / 全部坏样本数 (E2 §8)。

    "被抓中" = 目标指标 pass=False 或其 blockers 非空 (指标级自证)。
    metascore < 1.0 → E2 FAIL (判定器自身失效, 不是被测对象的问题)。
    """
    if not broken_results:  # 空输入判失败而非放过: 没有反证夹具就没有证据证明判定器有效
        # 空输入记 0.0 而不是 1.0: 没有反证夹具等于没有证据证明判定器有效,
        # 记满分会让"夹具被误删"这件事在报表上完全看不出来 (fail-closed)
        return 0.0
    # must_fail 与 caught 同时为真才算抓到: 只看 caught 会把"没声明期望失败"
    # 的样本也算进去, 让 metascore 虚高
    caught = sum(1 for r in broken_results if r.get("must_fail") and r.get("caught"))  # 反证夹具必须被抓住才算元分: 判定器漏抓注入故障等于没有判定器
    return caught / len(broken_results)
