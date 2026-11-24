# -*- coding: utf-8 -*-
"""evals.groundtruth.metrics.m7_determinism — M7 确定性与计数诚实率 (权重 0.05)。

口径 (E2 §6 M7):
  - 确定性: 同快照同参数跑 3 次, data_hash 全等 → 1.0 (防隐藏随机/集合无序);
  - 计数诚实: cost.http_requests 是否等于「实际翻页数 + 计数 + 提交」的
    真实请求数 (防虚报成本 — 回放 transport 的 call_count 是实测值)。
"""
from __future__ import annotations


def score_m7(gold: dict, actual: dict) -> dict:
    """M7: 3 次 data_hash 全等性 + http_requests 声明/实测一致性。

    **ERROR 态下"计数诚实"记 N/A** (2026-10-08): 查询失败时请求计数本就不完整
    (失败可发生在两阶段协议的任何一步), 拿它与声明侧比对只会把站点/网络的抖动
    读成"客户端成本造假"。实测踩到过: 站点 POST 返 RemoteDisconnected, 该 case
    整体 ERROR, M7 却报 determinism_or_count_dishonest —— 那是把网络天气记在
    被测代码账上。故 ERROR 态只判确定性那一半, 计数诚实项记 None (不进分母)。

    **传输层瞬断轮下"确定性"记 N/A** (2026-10-10): 上一条只补了 ``honest`` 半边,
    确定性半边仍要求 repeat 次行集指纹全等 —— 而某一轮被传输层打断时它拿到的是
    **空行集**, 指纹必然与其余轮不同, 于是同样把网络天气记成"被测代码不确定"。
    实测两轮全量跑批各挂一个**不同**的 case (huge_3700rows / boundary_maxrows),
    两轮 stderr 均见对 ``ps1/q`` 的 POST 被 RemoteDisconnected 打断; 而专项探针
    (``temp/e2_m7_probe.py``) 在全部轮次成功时, 4 个 case 的有序/无序/主键集指纹
    **三轮全等** —— 行数据本身不漂。故: 只要有一轮属传输层失败, 确定性分项记 None
    (不进分母), 并把是哪几轮记进 ``transport_error_repeats`` 供人复核。

    这道闸**只认传输层异常类型** (见 ``run_e2._is_transport_error``), 站点回了
    HTTP 响应再报出的契约错误一律照旧判确定性 —— 那是被测行为, 不许被洗掉。
    """
    envelope = actual.get("envelope") or {}
    errored = envelope.get("success") is False or bool(envelope.get("error_code"))  # ERROR 态: 计数不完整
    data_hashes = actual.get("data_hashes") or []  # 只认重复跑出的多条指纹; 少于两条判不了确定性
    # 逐轮状态 (run_e2.run_scenario 记账): 缺该字段时退成"无传输层失败", 保持旧口径不变
    repeat_states = actual.get("repeat_states") or []
    transport_repeats = [i + 1 for i, s in enumerate(repeat_states)   # 轮次按 1 起编号: 报给复现者看
                         if (s or {}).get("transport_error")]
    # 传输层瞬断 ⇒ 指纹差异不可归因到被测代码: 确定性这一半无域可判, 记 None 不进分母
    deterministic = (None if transport_repeats
                     else (len(set(data_hashes)) == 1 if len(data_hashes) >= 2 else None))  # 全部相同才算确定性: 任一条不同即 fail
    declared = actual.get("declared_http_requests")
    observed = actual.get("observed_http_requests")
    # 缺一侧或 ERROR 态不判诚实性 (None 不进分母)
    honest = (None if errored or declared is None or observed is None  # 申报与实测请求数必须相等: 少报即成本口径造假
              else int(declared) == int(observed))
    components = [v for v in (deterministic, honest) if v is not None]  # 只对有结论的分项取均值: 缺数据不算失败项, 也不虚报满分
    # 分母为 0 时给 1.0: 两项都没数据即"无从证伪", 不给 0 分制造假红
    score = sum(1.0 if c else 0.0 for c in components) / len(components) if components else 1.0  # 全中才 1.0: 分母为空时按"无可测项"记满分, 不记 0 分
    passed = all(c for c in components) if components else True
    return {
        "score": score,
        "pass": passed,
        "deterministic": deterministic,
        "http_requests_honest": honest,
        "declared_http_requests": declared,
        "observed_http_requests": observed,
        # 披露面 (不参与判定, 只让人看得见"这一轮为什么没判"): 空列表 = 本轮无传输层瞬断
        "transport_error_repeats": transport_repeats,
        "determinism_domain": ("n/a (传输层瞬断轮 " + ",".join(map(str, transport_repeats)) + ")"
                               if transport_repeats else "judged"),
        "blockers": [] if passed else ["determinism_or_count_dishonest"],  # 阻断项写明性质: 排障要一眼看出是漂移还是计数不诚实
    }
