# -*- coding: utf-8 -*-
"""evals.groundtruth.metrics.m6_version — M6 数据版本一致率 (权重 0.05)。

职责: 判断"这份结果是不是拿这一版快照跑出来的" —— 把被测系统吐的
provenance 三键与金标准声明的三键逐字对账, 并在拿 A 版快照却报 B 版
(跨版本污染) 时直接阻断。

口径 (E2 §6 M6): 输出 provenance/信封必须携带 snapshot_id (或 data_version)/
catalog/endpoint 三项, 逐字比对。版本一致率 = 一致子项/声明子项; **跨版本污染**
(拿 A 版本快照跑却声明 B 版本) 直接 FAIL (阻断)。

**live 层改判「不可对账」(2026-10-07)**: 真站点**不提供任何版本标识面**
(见 :func:`evals.groundtruth.run_e2._data_version`), 于是 snapshot_id 档位在实跑下
**无从对账**。这里的处置是把它**移出声明集**并在返回值里显式记
``reconcilable=False`` / ``not_reconcilable``, 而不是:

- 拿"两侧都空"判成一致 —— 那是把"没测"报成"测过", 正是铁律 5 禁的 fail-open;
- 或留一条恒红的失配 —— 恒红比不判更坏: 它让人以为判据在工作, 实际它每天
  拦下的是"站点没有版本号"这件与被测代码无关的事。

代价要说清: live 层因此**抓不到跨版本污染**。那一类只由 replay 层兜。

snapshot_id 档位的身份判定 (仅 replay): gold 侧可能是 sha256 指纹 (快照身份) 或
data_version 标签; actual 侧可能是快照目录名 (指纹的人类可读别名) 或
data_version。**两侧各取 (snapshot_id, data_version) 两个口径的并集做匹配**
— 任一口径对上即一致; 两个口径都对不上才是跨版本污染。

所属实验: E2 金标准一致性 (方案真值 docs/eval-E2-groundtruth.md §6 M6),
本件是 M1–M7 七个指标之一, 在 ``run_e2.py`` 里按权重 0.05 计入总分。

对外接口: ``score_m6(gold, actual)`` 返回 score/pass/matched/declared/
mismatches/cross_version_pollution/reconcilable/not_reconcilable/blockers,
供 E2 聚合器消费。

依赖与数据流: 输入是金标准快照声明与被测结果的 provenance 字典。replay 层来自
离线快照回放 (不发真实请求, rate_limit 归零); live 层来自真站点直连。

关键契约与不变量: 逐字比对不做模糊匹配 —— provenance 是"数据血缘"声明,
容忍拼写差异等于允许它撒谎; 未声明的项不计入分母 (GT 没声明的账不该
记在 SUT 头上), 但 pass 要求 rate 恰为 1.0, 不给"大部分对上"的放行;
零跨实验 import, 数据血缘字段 ``data_version`` 是本仓允许的数据侧标识,
与被禁的发布版本号不是一回事。

陷阱与边界: 分母 ``declared`` 是动态的, GT 只声明两项时 rate 的分母就是
2 而不是 3 —— 直接除以 3 会让"少声明一项"的 gold 白拿满分; 反过来
``cross_version`` 要求两侧都非空, 否则 actual 完全不报 provenance 会
被误判成跨版本污染, 那属于"缺失"而非"撒谎", 归 M5 状态判据管。
"""
from __future__ import annotations


def score_m6(gold: dict, actual: dict) -> dict:
    """M6: provenance 三键 (snapshot_id/catalog/endpoint) 对账。

    live 层 (``actual["mode"] == "live"``) 把 snapshot_id 档位移出声明集并在
    ``not_reconcilable`` 里点名 —— 真站点无版本标识面, 那一项不可对账。
    """
    provenance = actual.get("provenance") or {}  # 溯源面是本判据的全部输入: 没有它就无从比
    # 两种接线两种可比性: live 无快照身份可谈, replay 才有
    live = str(actual.get("mode") or "replay") == "live"
    # 两侧的 snapshot 身份都允许两种写法, 先分别取出原始值, 下面再做并集匹配
    gold_snapshot = gold.get("snapshot_id")  # snapshot_id 与 data_version 二选一: 两种血缘字段形态本仓并存
    gold_version = gold.get("data_version")  # 两种口径在本仓同时存在, 缺一个不代表 GT 没声明
    # gold_checks 是"该比什么": 只列 GT 明确声明过的三键, 未声明的不参与判定
    gold_checks = {  # 只装 GT 声明过的三键: 未声明的账不该记在 SUT 头上
        "snapshot_id": gold_snapshot or gold_version,  # 优先指纹、回落版本标签: 两种写法指向同一份快照
        "catalog": gold.get("catalog"),  # 星表名逐字对: 换了星表就是另一批数据, 不做模糊匹配
        "endpoint": gold.get("endpoint"),  # 三字段同查: 只查一个会让"换了星表但没换快照"溜过去
    }
    # live 层显式摘掉身份键: 不是"判它一致", 是"这一项无从对账"。
    # 保留它会让 declared 分母含一项永远对不上的账, E2 恒红 —— 而红的原因是
    # 站点没有版本号, 与被测代码无关。摘掉的名字照实报进 not_reconcilable,
    # 报告读者仍看得见"这一项没验", 而不是以为它验过了。
    not_reconcilable = ["snapshot_id"] if live else []
    for key in not_reconcilable:
        gold_checks.pop(key, None)
    # checks 是"对方报了什么": 同样双口径回退, 缺项留 None 交给下面判不匹配
    checks = {  # 与 gold_checks 同构: 两侧字段名错位会让并集匹配永远为空
        "snapshot_id": provenance.get("snapshot_id") or provenance.get("data_version"),  # 取值顺序与 gold 侧一致, 免得两侧各取一个字段当身份
        "catalog": provenance.get("catalog"),  # 缺项即 None: 与"报了空串"是两回事, 失配原因要能分开
        "endpoint": provenance.get("endpoint"),  # 端点逐字比: 换域名或路径就是另一条数据通路
    }
    # snapshot_id 档位: 两侧双口径并集 (指纹 ↔ 目录名/版本标签)
    gold_ids = {str(v) for v in (gold_snapshot, gold_version) if v}  # 只收非空值: 缺字段不该被判成血缘不一致
    # 过滤 None 而非真值: 空串/0 虽是合法身份值, 但 None 明确表示"没报"
    actual_ids = {  # 非 None 才收: 空串与 0 是合法身份值, 滤掉会把合法声明判成没报
        str(provenance.get(k)) for k in ("snapshot_id", "data_version")  # 两个字段一起取: 报法不统一是常态, 只认一种会把一致判成不一致
        if provenance.get(k) is not None  # 条件写在推导式里, 不给 None 套 str(): 字符串 None 会假对上
    }
    # 分子分母都随声明项走: GT 只声明两项时, rate 的分母是 2 而不是 3,
    # 否则 gold 靠"少声明一项"就能白拿满分
    matched, mismatches = 0, []  # 分子与失配明细同步攒: 报告要能指出是哪一键错了
    for key, gold_value in gold_checks.items():  # 只遍历 gold 声明过的键: 分母跟着声明走, 少声明不得白拿满分
        if gold_value is None:  # GT 未声明即跳过, 判它等于逼 SUT 为 GT 的缺项认错
            continue  # GT 未声明该项不判 (缺的是 GT 的账, 不是 SUT 的)
        if key == "snapshot_id":  # 身份键走并集口径, 其余两键走逐字口径, 两种判据不能混用
            # 该档走并集: 指纹与人类可读目录名指向同一份快照, 不该判不一致
            ok = bool(gold_ids & actual_ids)  # 并集非空即一致: 两种叫法本就是同一份快照
        else:
            # 其余两键逐字比: 先确认对方报了, 再比字符串形态 (两侧可能给数字)
            ok = checks.get(key) is not None and str(checks[key]) == str(gold_value)  # 先判"报没报"再比值: 未报与报错是两种失配
        if ok:  # 三项全过才算 1.0, 这里刻意不给"部分一致"的档
            matched += 1  # 与 declared 同口径累加, 分子分母都只算已声明项
        else:
            # 记下两侧原值: 报告里要能直接看出是"没报"还是"报错了"
            mismatches.append({"key": key, "gold": gold_value,  # 两侧原值都留: 报告要能分辨"没报"与"报错"
                               "actual": checks.get(key)})  # 未报侧保持 None: 补成空串会让失配看起来像值不符
    declared = sum(1 for v in gold_checks.values() if v is not None)  # 分母随声明动态: 固定除 3 会让少声明的 gold 白拿满分
    # GT 一项都没声明时给满分而非除零: 这是"无从判定", 不是"判错"
    rate = matched / declared if declared else 1.0  # 零声明给满分属"无从判定", 收口靠下面的 pass 阻断项
    # 两侧都报了身份却完全对不上 = 拿这份数据报了另一份的出处, 阻断;
    # 任一侧为空不算污染, 那是缺失 (M5 状态判据的活), 不足以指控撒谎
    cross_version = not (gold_ids & actual_ids) and bool(gold_ids) and bool(actual_ids)  # 两侧非空且全不匹配才算污染, 单侧缺失归 M5 管
    return {
        "score": rate,
        # 恰为 1.0 才过: 一致率是"全有或全无"的契约, 部分一致不算通过
        "pass": rate == 1.0 and not cross_version,
        "matched": matched,
        "declared": declared,
        "mismatches": mismatches,
        "cross_version_pollution": cross_version,
        # 可对账性自报: live 层为 False 时, 上面的 1.0 只覆盖剩下的键,
        # **不代表"版本一致性已验证"**。报告读者据此知道这一项是缺证据而非过。
        "reconcilable": not live,
        "not_reconcilable": not_reconcilable,  # 点名哪几项没验: 不可判定要显式标记, 不留读者去猜
        # blockers 分两级: 污染是阻断级 (证据表明数据不对), 单纯不一致是
        # 普通失配级, 报告里要能一眼分清严重程度
        "blockers": ["cross_version_pollution"] if cross_version else (
            [] if rate == 1.0 else ["version_mismatch"]),
    }
