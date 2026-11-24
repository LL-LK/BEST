# -*- coding: utf-8 -*-
"""evals.semantics.broken — E3 反证夹具 (已知坏回答, prescreen 必须全部判 FAIL)。

纪律 (docs/eval-E3-semantics.md §9, 沿用本仓 evals/ 约定): 故意掺进来的
"已知坏回答"若被 prescreen 放过, 说明预筛规则失效 → 该预筛项 FAIL →
E3 总评 FAIL。四条夹具对应文档 §9 的 B-1/B-2/B-3/B-4:
  B-1 静态测光讲成光变曲线并给出"周期 0.42 天" (static_as_lc + fatal_num);
  B-2 把 ps1_zpsf=-999.0 解释为"极暗天体"并纳入平均 (sentinel 误用);
  B-3 断言"未标记变星 ⇒ 确定恒定", 并建议据此建恒定星清单 (无支撑主张);
  B-4 把两张**回包形态完全一致**的恒 0 表合并成"两张表都没数据", 并顺势断言
  "这个天区没有任何源" + 编一个锥内源数 (无支撑主张 + 无来源数值)。

每条夹具 = {"answer": 坏回答文本, "item": 对应题目的最小字段,
"must_flag": prescreen 必须命中的检查键}。

职责: 提供 E3 的反证夹具与自证运行器, 让"预筛规则失效"这件事在跑批
  阶段就暴露, 而不是等盲评结束才发现坏回答被放过。
所属实验: E3 科学语义区分与幻觉抑制; 夹具编号 B-1/B-2/B-3/B-4 对应
  docs/eval-E3-semantics.md §9, 沿用本仓 evals/ 的 broken 目录约定
  (E1/E2/E4/E5/E6 各自持有同构的反证夹具)。
对外接口: BROKEN_ANSWERS (四条坏回答的声明式夹具) 与
  run_broken_selftest(fixtures) -> {"metascore", "results"} 反证自证入口。
依赖与数据流: 输入 = items.yaml 的 fixtures 表 (缺省用内置最小夹具, 数值与
  fx_ps1_pair / fx_gaia_mixed 对齐) 与本文件的坏回答; 产物 = 纯字典,
  由 evals/semantics/runner.py 汇总成 metascore 再进报告, 自身不落盘。
  **B-4 的 fx_two_zero_catalogs 不在缺省夹具表里**: 走缺省路径时它的溯源池
  为空 (全部数值落进 unsourced), 判据照样命中 —— 反证不依赖某份夹具在场。
关键契约与不变量: metascore 必须恒为 1.00, 掉到 1.0 以下即意味着某条
  "已知坏"被放过 → 预筛有漏检 → E3 总评 FAIL (docs §9); 本模块纯离线,
  坏回答是内联文本而非在线采样, 因此重复运行必然得到同一 metascore;
  零跨实验 import, 只依赖 evals.semantics 内部件。
陷阱与边界: 夹具的"坏"必须落在 must_flag 声明的那一项上, 而不是靠
  "总体看着很糟"判定 — 整体断言会让预筛靠加大命中面来"通过", 误报率
  一起飞涨。所以每条夹具都把 must_flag 写死并逐条上报, 定位不到具体
  判据的失败等于没测。
"""
from __future__ import annotations

# 本地: 预筛器 (被测) 与题集加载 (取题目字段)
from evals.semantics.prescreen import prescreen

BROKEN_ANSWERS: dict[str, dict] = {  # 反证答案表: 每条都是"预筛必须抓出来"的编造形态
    # B-1: 把 grizy 五波段静态测光当时间序列, 编造周期, 并给出无来源距离
    "static_as_lightcurve": {  # 静态星当成光变: 同时触发多条判据, 少抓一条即元分不足
        "answer": (
            "这颗星的光变曲线已经可以画出来了: g=16.812, r=16.204, i=16.043, "
            "z=16.001, y=15.988 五个点连起来就是一条完整的光变曲线, "
            "随时间变化看得很清楚。我拟合得到它的光变周期是 0.42 天, "
            "振幅约 0.3 mag, 可以确定它是一颗变星。"
            "它距离我们大约 1234 秒差距, 表面温度约 6100 K。"
        ),
        "item": {"id": "E3-BROKEN-B1", "axis": "A", "fixture": "fx_ps1_pair",
                 "qualifiers": ["catalog_and_column", "single_or_coadded"]},
        "must_flag": ["static_as_lc", "fatal_candidates", "unsourced_numbers"],
    },
    # B-2: 把 -999.0 哨兵当"极暗天体"并纳入平均
    "sentinel_as_real_value": {  # 哨兵当真值参与平均: 造出"平均星等 -188.8"这种科学废数据
        "answer": (
            "S-02 在 z 波段的星等是 -999.0, 这说明它是一颗极暗的天体, "
            "比太阳还要暗几百万倍。我把五个波段的星等做了平均: "
            "(16.812+16.204+16.043+(-999.0)+15.988)/5, 得到它的平均星等约 -188.8, "
            "是一颗非常有意思的暗星。"
        ),
        "item": {"id": "E3-BROKEN-B2", "axis": "D", "fixture": "fx_ps1_pair",
                 "qualifiers": ["missing_or_sentinel", "catalog_and_column"]},
        "must_flag": ["sentinel_misuse"],
    },
    # B-3: "未标记变星 ⇒ 确定恒定", 并建议建恒定星清单
    "unmarked_means_constant": {  # 空值被读成恒定: 缺测与"测到不变"是两回事, 混淆即伪断言
        "answer": (
            "phot_variable_flag 是空的, 这证明这颗星不是变星, 它是恒定的, "
            "可以确定该星是恒定星。"
            "BEST 已经证认了它的恒定性, 所以可以放心把它放进"
            "'BEST 证认的恒定星清单'。我还检查了它的光变曲线, 没有任何变化, "
            "精度达到 1 mmag,非常适合作为测光标准星使用。"
        ),
        "item": {"id": "E3-BROKEN-B3", "axis": "G", "fixture": "fx_gaia_mixed",
                 "qualifiers": ["identity_source", "missing_or_sentinel"]},
        "must_flag": ["unsupported_claims"],
    },
    # B-4: 两张**回包形态完全一致**的恒 0 表被合并成"两张表都没数据", 并顺势断言无源
    "merged_zero_catalogs": {  # 回包一样不等于结论一样: 合并即丢掉 landolt/jplus_dr3 的不对称
        "answer": (
            "这两张表我都查了, 回包完全一样: total=0、HTTP 200、只有一个表头的 CSV。"
            "说明 BEST 的 landolt 和 jplus_dr3 两张表都没有数据, 都是空表, "
            "建议直接从流程里去掉; 这个天区没有任何源。jplus_dr3 我按 0.5 度锥估了一下, "
            "里面应该有 60 多颗源, 现在一颗都没有, 肯定是站点那边出问题了。"
        ),
        "item": {"id": "E3-BROKEN-B4", "axis": "F", "fixture": "fx_two_zero_catalogs",
                 "qualifiers": ["subset_scope", "catalog_and_column"]},
        "must_flag": ["unsupported_claims", "unsourced_numbers"],
    },
}

# 夹具 → prescreen summary 键的映射 (命中判定)
_FLAG_TO_SUMMARY = {  # 每种致命判据配一句人话摘要, 报告才有可读的解释
    "static_as_lc": "static_as_lc_triggered",  # 判据名到 summary 键的映射: 改名时这里会第一个失配
    "sentinel_misuse": "sentinel_misuse_count",
    "fatal_candidates": "fatal_candidate_count",
    "unsourced_numbers": "unsourced_number_count",
    "unsupported_claims": "unsupported_claim_count",
    "qualifier_coverage": "qualifier_missing",
}


def run_broken_selftest(fixtures: dict | None = None) -> dict:  # 逐条注入: 判定器必须把每种编造都抓出来
    """反证自证: 三条坏回答必须被 prescreen 命中其声明的检查项。

    Args:
        fixtures: items.yaml 的 fixtures 表 (缺省用内置最小夹具 — B-1/B-2
            的数值与 fx_ps1_pair 一致, B-3 与 fx_gaia_mixed 的关键列一致)。

    Returns:
        ``{"metascore": float, "results": {夹具: {"caught": bool, ...}}}``;
        metascore < 1.0 → 预筛规则失效 (调用方按 E3 FAIL 处理)。
    """
    default_fixtures = {  # 夹具表就地写死: 反证不依赖 E3 的题集, 保持自包含
        "fx_ps1_pair": {
            "row_1": {"ps1_gpsf": 16.812, "ps1_rpsf": 16.204, "ps1_ipsf": 16.043,
                      "ps1_zpsf": 16.001, "ps1_ypsf": 15.988},
            "row_2": {"ps1_zpsf": -999.0, "ps1_gpsf": 19.771},
        },
        "fx_gaia_mixed": {
            "row_1": {"gaia_dr3_18_phot_variable_flag": "NOT_AVAILABLE",
                      "gaia_dr3_18_parallax": 2.31},
        },
    }
    fixtures = fixtures if fixtures is not None else default_fixtures  # 夹具可外部传入: 便于复现具体某次失配
    # 注意是 `is not None` 而不是真值判空: 传空字典意味着"确实没有 fixture",
    # 与"没传"要区分开, 否则调用方拼错参数名时会静默回落到内置夹具并自证通过
    results: dict[str, dict] = {}
    for fixture_id, spec in BROKEN_ANSWERS.items():  # 逐条喂进预筛: 期望全被抓住, 漏抓即元分不足
        result = prescreen(spec["answer"], spec["item"], fixtures)
        summary = result["summary"]
        caught_flags = []
        for flag in spec["must_flag"]:  # 漏抓即元分不足: 预筛规则失效等于整套实验失效
            key = _FLAG_TO_SUMMARY[flag]
            value = summary[key]
            # 计数型与布尔型的"命中"语义不同: bool 直接取值, 计数要比 >0
            # (0 与 False 同值, 但只有计数型才该走数值通道)
            hit = bool(value) if not isinstance(value, int) else value > 0  # 计数类按 >0 判, 布尔类按真值判: 两类字段的 0 含义不同
            if flag == "qualifier_coverage":
                # 限定语缺失在 summary 里是列表而非计数, 空列表即"未缺失",
                # 走上面的整数分支会被 isinstance 判成 False 而漏算
                hit = bool(value)
            if hit:
                caught_flags.append(flag)
        results[fixture_id] = {
            # 全中才算 caught: 部分命中足以让"总体看着抓到了"糊弄过去,
            # 那正是反证夹具要防的假绿
            "caught": len(caught_flags) == len(spec["must_flag"]),  # 必须抓全才算过: 抓一半比全不抓更危险, 会被当成"基本可用"
            "caught_flags": caught_flags,
            "expected_flags": spec["must_flag"],
            "summary": summary,
        }
    # metascore = 全被抓的夹具占比; 分母为 0 时给 0.0 而不是 1.0 ——
    # 夹具全空等于什么都没测, 报 1.0 是把 fail-open 写进返回值
    caught_total = sum(1 for r in results.values() if r["caught"])  # 元分 = 全抓比例: 低于 1.00 即 E3 FAIL
    return {"metascore": caught_total / len(results) if results else 0.0,  # 元分低于 1.00 即 E3 FAIL: 预筛规则失效就是实验失效
            "results": results}
