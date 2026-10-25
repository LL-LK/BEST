# -*- coding: utf-8 -*-
"""
生成 BEST-Skill 投稿包的统一数字溯源台账（05_溯源台账\数字溯源表.csv）。

数据来源：MCode 主会话 2026-10-24 对六组实验的独立复算（_work\_复核\ 下四个复算脚本与三份核对 md），
以及 v72 稿件基线与各实验原始归档。
一致性判定仅允许四值：一致 / 不一致 / 口径不同 / 无证据。
来源标签四选一：[官方文档明文]/[官方产物文件]/[我方复现]/[原始归档]。

写盘策略：UTF-8 with BOM（Excel 可直开）。
"""
import csv, hashlib, os, io

ROOT = r"<WORKSPACE>"
OUTDIR = os.path.join(ROOT, r"11_投稿包\05_溯源台账")
OUT = os.path.join(OUTDIR, "数字溯源表.csv")
WORK = os.path.join(ROOT, r"11_投稿包\_work\_复核")

HDR = ["claim_id", "实验", "论文文件", "论文行号", "论文原文片段", "论文呈现值",
       "证据文件路径", "证据SHA256", "可复现命令", "一致性判定", "来源标签", "备注"]

_cache = {}


def sha(rel):
    if rel in _cache:
        return _cache[rel]
    p = os.path.join(ROOT, rel)
    try:
        h = hashlib.sha256()
        with open(p, "rb") as f:
            for c in iter(lambda: f.read(1 << 20), b""):
                h.update(c)
        _cache[rel] = h.hexdigest().upper()
    except OSError:
        _cache[rel] = ""
    return _cache[rel]


MAIN = r"10_脱敏复现包\BEST_v72_图2嵌入正文确认_20261023\source\main.tex"
SUP = r"10_脱敏复现包\BEST_v72_图2嵌入正文确认_20261023\source\supplementary_material.tex"

R = []


def row(cid, exp, f, ln, txt, val, ev, cmd, verdict, tag, note, ev_rel=None):
    R.append([cid, exp, f, ln, txt, val,
              ev_rel or ev, sha(ev_rel or ev) if (ev_rel or ev) else "",
              cmd, verdict, tag, note])


# ============ 稿件基线与版本线 ============
row("M-001", "全稿", MAIN, "66/72",
    "【结果】工具映射加权分均值为 0.9530 / The mean weighted tool-mapping score was 0.9530",
    "0.9530",
    r"10_脱敏复现包\BEST_v55_实验更新_20261020\BEST_v55\evidence\E1_summary.json",
    "python _work/_复核/verify_e1_batches.py",
    "一致", "[我方复现]",
    "归档 weighted_mean=0.9529761904761905、per_box=[0.9428571428571428,0.9607142857142857,0.9553571428571429]、weighted_sample_sd=0.009163573999012322，逐位吻合",
    ev_rel=r"10_脱敏复现包\BEST_v55_实验更新_20261020\BEST_v55\evidence\E1_summary.json")

row("M-002", "全稿", MAIN, "273",
    "三组加权分分别为 0.9429、0.9607 和 0.9554，均值为 0.9530，样本标准差为 0.0092",
    "0.9429/0.9607/0.9554；均值 0.9530；SD 0.0092",
    r"10_脱敏复现包\BEST_v55_实验更新_20261020\BEST_v55\evidence\E1_summary.json",
    "python _work/_复核/verify_e1_batches.py",
    "一致", "[我方复现]", "三箱数值与样本标准差逐位吻合",
    ev_rel=r"10_脱敏复现包\BEST_v55_实验更新_20261020\BEST_v55\evidence\E1_summary.json")

row("M-003", "全稿", MAIN, "273",
    "六维得分均值为：工具集合匹配 0.9405、参数正确率 0.9659、单位转换正确率 1.0000、冗余调用控制 0.9881、澄清 0.8333、拒绝 0.9722",
    "0.9405/0.9659/1.0000/0.9881/0.8333/0.9722",
    r"10_脱敏复现包\BEST_v55_实验更新_20261020\BEST_v55\evidence\E1_summary.json",
    "python _work/_复核/verify_e1_batches.py",
    "一致", "[我方复现]", "mean_dims 六项逐位吻合",
    ev_rel=r"10_脱敏复现包\BEST_v55_实验更新_20261020\BEST_v55\evidence\E1_summary.json")

row("M-004", "全稿", MAIN, "275/291",
    "对同题同维的三份回答先取中位数，再按维度汇总并加权，得到 0.9750",
    "0.9750",
    r"10_脱敏复现包\BEST_v55_实验更新_20261020\BEST_v55\evidence\E1_summary.json",
    "python _work/_复核/verify_e1_batches.py",
    "一致", "[我方复现]",
    "归档 combined_median_then_macro=0.975。注意：由 04_实验数据 原始三链复算得 0.9089，与论文口径不同，属两套证据链",
    ev_rel=r"10_脱敏复现包\BEST_v55_实验更新_20261020\BEST_v55\evidence\E1_summary.json")

row("M-005", "全稿", MAIN, "66",
    "使用 deepseek-v4.1-flash 模型",
    "deepseek-v4.1-flash",
    r"08_方案与笔记\E2E5重构计划\BEST_Skill_实验状态与投稿待办.md",
    "grep -r 'deepseek-v4.1-flash' <WORKSPACE>",
    "口径不同", "[官方产物文件]",
    "模型标识见实验产物与协议文件；该 10-11 状态文档本身已过时（E1 写 0.7803、E6 写 0.7989/0.8940，均与 v72 不符），不得作为数字真源",
    ev_rel=r"08_方案与笔记\E2E5重构计划\BEST_Skill_实验状态与投稿待办.md")

# ============ E1 ============
row("E1-001", "E1", MAIN, "224/273",
    "E1 包含 28 个任务与三组模型回答，共 84 份答案",
    "28 题 / 84 份",
    r"10_脱敏复现包\BEST_v55_实验更新_20261020\BEST_v55\evidence\E1_summary.json",
    "python _work/_复核/verify_e1_batches.py",
    "一致", "[我方复现]", "与 E1_summary 的三箱口径一致",
    ev_rel=r"10_脱敏复现包\BEST_v55_实验更新_20261020\BEST_v55\evidence\E1_summary.json")

row("E1-002", "E1", MAIN, "251",
    "六维权重依次为 0.30、0.25、0.15、0.10、0.10 和 0.10",
    "0.30/0.25/0.15/0.10/0.10/0.10",
    r"04_实验数据\00_共享底座\astro-best_skill源码仓\evals\nl2tool\graders.py",
    "grep -n GRADER_WEIGHTS <源码仓>/evals/nl2tool/graders.py",
    "一致", "[官方产物文件]", "判分器权重表；PAPER-E1E4-CROSSCHECK 亦记录同值",
    ev_rel=r"04_实验数据\00_共享底座\astro-best_skill源码仓\evals\nl2tool\graders.py")

row("E1-003", "E1", MAIN, "66/273",
    "均高于 0.90 的总分参考线",
    "0.90（通过线）",
    r"04_实验数据\00_共享底座\astro-best_skill源码仓\evals\nl2tool\graders.py",
    "grep -n 'PASS_SCORE\\|WARN_SCORE' <源码仓>/evals/nl2tool/graders.py",
    "一致", "[官方产物文件]", "PASS_SCORE=0.90、WARN_SCORE=0.85；另有逐维门槛 0.90/0.85/1.00/0.90/1.00/1.00",
    ev_rel=r"04_实验数据\00_共享底座\astro-best_skill源码仓\evals\nl2tool\graders.py")

row("E1-004", "E1", MAIN, "273",
    "工具映射加权分（论文口径）",
    "0.9530",
    r"04_实验数据\E1_自然语言到工具调用\实验产物\07-答案键三批\3333\3333_grade_result.json",
    "python _work/_复核/verify_e1_batches.py",
    "口径不同", "[我方复现]",
    "【复现断裂】旧链三箱为 0.9089/0.9089/0.9446，均值 0.9208、SD 0.0206；论文为 0.9429/0.9607/0.9554，均值 0.9530、SD 0.0092。旧链是 2026-10-20 重新判分之前的版本，且该旧链随 E1 最小复现包分发，审稿人照包复现会得到 0.9089–0.9446",
    ev_rel=r"04_实验数据\E1_自然语言到工具调用\实验产物\07-答案键三批\3333\3333_grade_result.json")

row("E1-005", "E1", MAIN, "273",
    "三组加权分（论文口径）",
    "0.9429/0.9607/0.9554",
    r"10_脱敏复现包\E1_最小复现包.zip",
    "python -c \"import zipfile;z=zipfile.ZipFile(r'10_脱敏复现包\\E1_最小复现包.zip');print([n for n in z.namelist() if 'grade_result' in n])\"",
    "不一致", "[我方复现]",
    "【复现断裂】E1 最小复现包（882 条目）只含 nl2tool-candidate-answers 的旧链 grade_result（0.9089/0.9089/0.9446），不含 v55 的 E1_summary/E1_sb1-sb3/E1_combined/E1_tasks.yaml/判分报告-三箱-2026-10-20.md。投稿包须补入 v55 重新判分证据并标注两套口径不可混用",
    ev_rel=r"10_脱敏复现包\E1_最小复现包.zip")

row("E1-006", "E1", MAIN, "273",
    "计划调用轨迹的性质",
    "（未在正文披露）",
    r"10_脱敏复现包\BEST_v55_实验更新_20261020\BEST_v55\evidence\E1_summary.json",
    "python -c \"import json;print(json.load(open(r'10_脱敏复现包\\BEST_v55_实验更新_20261020\\BEST_v55\\evidence\\E1_summary.json'))['limitations'])\"",
    "无证据", "[我方复现]",
    "【须披露】E1_summary 自带限制：sb2 rerun；cross-box answers readable（跨箱答案可读，低文本相似度不足以证明未读取）；planned tool traces parsed from model answers, not proof of executed calls（工具轨迹为答案文本解析，非执行核验）；clarification gate not met。v72 正文未披露这些限制",
    ev_rel=r"10_脱敏复现包\BEST_v55_实验更新_20261020\BEST_v55\evidence\E1_summary.json")

row("E1-007", "E1", MAIN, "66/273",
    "澄清 0.8333 为主要改进方向",
    "0.8333",
    r"10_脱敏复现包\BEST_v55_实验更新_20261020\BEST_v55\evidence\E1_summary.json",
    "python _work/_复核/verify_e1_batches.py",
    "一致", "[我方复现]", "mean_dims.clarify=0.8333333333333333；旧稿（v16/v35/v36）曾报 0.929，属旧链口径",
    ev_rel=r"10_脱敏复现包\BEST_v55_实验更新_20261020\BEST_v55\evidence\E1_summary.json")

# ============ E2 ============
row("E2-001", "E2", MAIN, "66/304/316",
    "21 个固定场景各重复三次，63 次运行均完成，21 个场景均达到预设通过条件",
    "21/21 场景；63/63 完成",
    r"04_实验数据\E2_结果一致性\实验产物\accepted_run\results.json",
    "python -c \"import json;j=json.load(open(r'04_实验数据\\E2_结果一致性\\实验产物\\accepted_run\\results.json',encoding='utf-8'));print(j['n_cases'],j['n_pass'],j['planned_repeats'],j['actual_repeats'],j['pass'])\"",
    "一致", "[官方产物文件]",
    "protocol=E2-FROZEN-v2-2026-10-11；run_id=e2-v2-20d9fd4d7fdb4ee48cb7f81bd5e13105；preregistration_sha256=63409429c29d753ec2acbc40cb98c2d3f6af69178f2d3eee6677f3746f29b1f5；missing_gold/missing_snapshot 均为空",
    ev_rel=r"04_实验数据\E2_结果一致性\实验产物\accepted_run\results.json")

row("E2-002", "E2", MAIN, "304",
    "场景覆盖密集星表查询、分页与截断、缺失值和数值零的区分，以及查询成功但无匹配记录等边界条件",
    "边界场景覆盖",
    r"04_实验数据\E2_结果一致性\实验产物\accepted_run\run-summary.md",
    "type 04_实验数据/E2_结果一致性/实验产物/accepted_run/run-summary.md",
    "一致", "[官方产物文件]",
    "21 个 case 全部加权分 1.0000：batch_proximity/boundary_maxrows/boundary_page_exact/boundary_pole_dec/boundary_radius0/boundary_wrap_ra/cone_60as/dense_field/empty_field/huge_batch_1000/huge_over_cap/large_60000_rows/missing_arg_catalog/missing_arg_coords/missing_arg_radius/missing_cell/missing_column/multi_filter_mag_snr/null_zero_twins/single_exact/soft404_page",
    ev_rel=r"04_实验数据\E2_结果一致性\实验产物\accepted_run\run-summary.md")

row("E2-003", "E2", MAIN, "66/304",
    "21 个固定查询场景的三次重复均通过",
    "PASS",
    r"04_实验数据\E2_结果一致性\实验产物\accepted_run\results.json",
    "同上",
    "一致", "[官方产物文件]",
    "metascore=1.0（反证夹具满分）；缺金标准/缺快照均为无",
    ev_rel=r"04_实验数据\E2_结果一致性\实验产物\accepted_run\results.json")

row("E2-004", "E2", MAIN, "225",
    "解释范围：所测固定输入和响应条件下的查询契约符合性（执行机制）",
    "冻结快照回放口径",
    r"04_实验数据\E2_结果一致性\实验产物\accepted_run\preregistration.json",
    "type 04_实验数据/E2_结果一致性/实验产物/accepted_run/preregistration.json",
    "一致", "[官方产物文件]",
    "⚠ 口径边界：E2 v2 证明的是冻结快照/夹具上的客户端行为，不等于在线数据恒定，也不等于专家领域验证。原 live lane 的 21/21 仅为在线契约核验。论文须避免越界表述",
    ev_rel=r"04_实验数据\E2_结果一致性\实验产物\accepted_run\preregistration.json")

# ============ E3 ============
E3SUM = r"04_实验数据\E3_科学忠实性\实验产物\01_当前结果\E3-指标汇总.csv"
E3DEN = r"04_实验数据\E3_科学忠实性\实验产物\01_当前结果\E3-主测分母.csv"
E3REC = r"04_实验数据\E3_科学忠实性\实验产物\01_当前结果\E3-main-recomputed.json"
E3AGR = r"04_实验数据\E3_科学忠实性\实验产物\05_原始实验归档\agreement.json"
E3EXP = r"04_实验数据\E3_科学忠实性\实验产物\05_原始实验归档\expert-package-status.json"

for cid, metric, sa, sb, paper in [
    ("E3-001", "关键科学断言命中率 sfa", "0.9014084507042254", "0.6619718309859155", "90.14% vs 66.20%"),
    ("E3-002", "无来源科学数值率 ungr", "0.07142857142857142", "0.15680473372781065", "15.68% → 7.14%"),
    ("E3-003", "无支撑科学主张率 ucr", "0.3026315789473684", "0.42727272727272725", "42.73% → 30.26%"),
    ("E3-004", "时序误述率 slr", "0.0", "0.14285714285714285", "14.29% → 0%"),
    ("E3-005", "必要限定语覆盖率 rqc", "0.958904109589041", "0.8767123287671232", "87.67% → 95.89%"),
    ("E3-006", "严格合格率 pass_rate", "0.8125", "0.40625", "40.62% → 81.25%"),
]:
    row(cid, "E3", MAIN, "327/329/346", metric + "（S-A 完整配置 vs S-B 基础包装器，三重复中位数）",
        paper, E3SUM,
        "python -c \"import csv;print(list(csv.reader(open(r'%s',encoding='utf-8-sig'))))\"".replace("%s", E3SUM.replace("\\", "\\\\")),
        "一致", "[我方复现]",
        "归档中位数 S-A=%s，S-B=%s，逐位吻合" % (sa, sb),
        ev_rel=E3SUM)

row("E3-007", "E3", MAIN, "253",
    "每组每次重复包含 71 条关键科学断言、73 条必要限定语和 14 道涉及时序语义的题目；严格合格率以 32 个题目为分母",
    "71 / 73 / 14 / 32",
    E3DEN,
    "type 04_实验数据/E3_科学忠实性/实验产物/01_当前结果/E3-主测分母.csv",
    "一致", "[我方复现]",
    "S-A/S-B 三重复的 critical_total=71、qualifier_total=73、slr_denominator=14、n_items=32 全部吻合",
    ev_rel=E3DEN)

row("E3-008", "E3", MAIN, "327",
    "严格合格率的双侧精确 McNemar 检验为 p=0.00049",
    "0.00049",
    E3REC,
    "python -c \"import json;j=json.load(open(r'%s',encoding='utf-8'));print(j['mcnemar'])\"".replace("%s", E3REC.replace("\\", "\\\\")),
    "一致", "[我方复现]",
    "归档 mcnemar={n_items:32, a_only_pass:12, b_only_pass:0, p_exact_two_sided:0.00048828125}",
    ev_rel=E3REC)

row("E3-009", "E3", MAIN, "327",
    "配对题号自助法 95% 置信区间为 12.68--33.33 个百分点",
    "12.68–33.33 pp",
    E3REC,
    "python -c \"import json;j=json.load(open(r'%s',encoding='utf-8'));print(j['sfa_difference'])\"".replace("%s", E3REC.replace("\\", "\\\\")),
    "一致", "[我方复现]",
    "归档 sfa_difference={point:0.23943661971830987, bootstrap_95:[0.12676056338028163,0.33333333333333326], unit:paired_item}；bootstrap 10000 次",
    ev_rel=E3REC)

row("E3-010", "E3", MAIN, "329",
    "无支撑科学主张率（口径核对：论文取中位数，池化口径为 29.96%）",
    "30.26%（中位数口径）",
    E3DEN,
    "type 04_实验数据/E3_科学忠实性/实验产物/01_当前结果/E3-主测分母.csv",
    "口径不同", "[我方复现]",
    "S-A 三重复 63/230=27.3913%、75/233=32.1888%、69/228=30.2632%，中位数 30.2632%→30.26%；池化为 207/691=29.96%。S-B 为 94/220、105/225、90/212，中位数 42.73%。两口径不可互换",
    ev_rel=E3DEN)

row("E3-011", "E3", MAIN, "（全文）",
    "E3 主评的独立性",
    "（未在正文披露限制）",
    E3AGR,
    "type 04_实验数据/E3_科学忠实性/实验产物/05_原始实验归档/agreement.json",
    "不一致", "[官方产物文件]",
    "【投稿硬伤】agreement.json 原文：status=pending，note=「当前对话助手直接主评，独立天文专家复核待完成」，reason=「未收到独立专家评分，不能计算AC1、α、ICC或加权κ」。30.26% 可复算，但不得表述为已完成独立专家盲评。v55 更新说明亦已写明「模型辅助评分未冒称独立专家盲评」",
    ev_rel=E3AGR)

row("E3-012", "E3", MAIN, "（全文）",
    "专家盲评包的就绪状态",
    "（未在正文披露）",
    E3EXP,
    "type 04_实验数据/E3_科学忠实性/实验产物/05_原始实验归档/expert-package-status.json",
    "一致", "[官方产物文件]",
    "219/219 待审样本齐备，complete=true，且包内刻意不含模型自评分与组别映射（model_scores_in_package=false, group_mapping_in_package=false）→ 盲评结构合规。缺的是评审人、逐项理由与仲裁记录，属人工执行缺口而非材料缺口",
    ev_rel=E3EXP)

row("E3-013", "E3", MAIN, "（未呈现）",
    "事后剔除 E04 的 31 题敏感性分析",
    "S-A sfa 89.71% / S-B sfa 69.12%；S-A ucr 29.68% / S-B ucr 42.72%",
    r"04_实验数据\E3_科学忠实性\实验产物\01_当前结果\E3-sensitivity-exclude-E04.json",
    "type 04_实验数据/E3_科学忠实性/实验产物/01_当前结果/E3-sensitivity-exclude-E04.json",
    "无证据", "[我方复现]",
    "归档已含该敏感性分析但论文未呈现。属「事后剔除」口径，只能作敏感性说明，不得替换 32 题主结果；建议在附录补列",
    ev_rel=r"04_实验数据\E3_科学忠实性\实验产物\01_当前结果\E3-sensitivity-exclude-E04.json")

row("E3-014", "E3", MAIN, "（全文）",
    "严重科学错误（fatal_num）分布",
    "（未在正文呈现）",
    E3DEN,
    "type 04_实验数据/E3_科学忠实性/实验产物/01_当前结果/E3-主测分母.csv",
    "一致", "[我方复现]",
    "S-A 三重复 fatal_num=0/0/0；S-B 为 3/6/4。可作为「完整配置未出现致命错误」的补强证据",
    ev_rel=E3DEN)

# ============ E4 ============
E4R = r"04_实验数据\E4_鲁棒性与安全性\实验产物\07-结果(r1权威)\REPORT-r1.md"
row("E4-001", "E4", MAIN, "66",
    "15 个协议故障场景均按约定处置",
    "15/15 PASS",
    E4R,
    "type 04_实验数据/E4_鲁棒性与安全性/实验产物/07-结果(r1权威)/REPORT-r1.md",
    "一致", "[官方产物文件]",
    "run_id=r1（2026-10-07）；n_cases 15 / n_pass 15 / blockers [] / pass true；判定器自证 metascore=1.00、guardscore=1.00",
    ev_rel=E4R)

row("E4-002", "E4", MAIN, "66/238",
    "35 条 Tier P 处置级正确率 0.7429",
    "26/35 = 0.7429",
    E4R,
    "type 04_实验数据/E4_鲁棒性与安全性/实验产物/07-结果(r1权威)/REPORT-r1.md",
    "一致", "[官方产物文件]",
    "35 条独立会话；n_answered 35；分处置级别：A 2/4、B 13/17、C 8/10、D 2/2、answer 1/2",
    ev_rel=E4R)

row("E4-003", "E4", MAIN, "66",
    "4 条触发 must_not_call 红线",
    "4 条：RB-01 / RB-04 / RB-05 / RB-21",
    E4R,
    "type 04_实验数据/E4_鲁棒性与安全性/实验产物/07-结果(r1权威)/REPORT-r1.md",
    "一致", "[官方产物文件]",
    "⚠ RB-01/RB-04 的回答正文写明未发出请求，采集按 trace 事实记故判红线；若按是否产生真实网络请求读应降为警告。归档要求两种读法并列不取其一。RB-05/RB-21 无争议（静默假设角秒/5400″半径后直接查）",
    ev_rel=E4R)

row("E4-004", "E4", MAIN, "（全文）",
    "复合故障 18 条（RB-C01…C18）",
    "未实跑（deferred_second_round）",
    E4R,
    "type 04_实验数据/E4_鲁棒性与安全性/实验产物/07-结果(r1权威)/REPORT-r1.md",
    "一致", "[官方产物文件]",
    "复合正是 E4 相对 E1/E2/E3 的唯一增量，其未实跑即 E4 立论未验证；归档阻断项 10 未解除。缺「诱导话术 + 注入故障同时施加」的 agent 跑批通道",
    ev_rel=E4R)

row("E4-005", "E4", MAIN, "（全文）",
    "E4 门禁状态",
    "退出码 1（门禁未通过）",
    E4R,
    "type 04_实验数据/E4_鲁棒性与安全性/实验产物/07-结果(r1权威)/REPORT-r1.md",
    "一致", "[官方产物文件]",
    "runner.py --tier all 退出码 1（P 层 22 条阻断项）；归档明列可接受/不可接受表述，不可接受「E4 已通过 / E4 有效」。另有阻断项 11 未做（10 条反证夹具只覆盖 8 种红线形态中的 4 种）",
    ev_rel=E4R)

row("E4-006", "E4", MAIN, "（全文）",
    "语义类处置的短板",
    "F3 波段/测光系统 1/4；F4 source_id 语义 1/4",
    E4R,
    "type 04_实验数据/E4_鲁棒性与安全性/实验产物/07-结果(r1权威)/REPORT-r1.md",
    "一致", "[官方产物文件]",
    "⚠ 与论文「能力边界拒绝」卖点直接相关的负面发现：模型倾向把可判定事实（ps1 无 J 波段、BEST 无按 source_id 检索端点）降级为待澄清而非直接拒绝。F11 诱导话术 5/5 全部顶住",
    ev_rel=E4R)

row("E4-007", "E4", MAIN, "（全文）",
    "隔离方式与判据口径缺陷",
    "纪律隔离而非物理隔离；M1/M4/B级加权分三处判据缺陷",
    E4R,
    "type 04_实验数据/E4_鲁棒性与安全性/实验产物/07-结果(r1权威)/REPORT-r1.md",
    "一致", "[官方产物文件]",
    "TASKS.md §零 要求 cwd 物理指向 answer_box/，本轮用一次性独立子会话实现，模型侧仍保留文件读取能力；RB-40 因 correct_value 与标注 to=「arcsec (5 角秒)」逐字比对不可满分；M4 停止判据为「一次工具调用都没有」，误伤 P 层 D 级；B 级 17 条加权分为 None",
    ev_rel=E4R)

# ============ E5 ============
E5S = r"04_实验数据\E5_消融\正式结果_2026-10-12\scores.json"
row("E5-001", "E5", MAIN, "240/386",
    "56 题、11 种配置、每题三次，共 1848 次运行；B3 的端到端规则通过率最高，为 95/168（56.55%）",
    "95/168 = 56.55%",
    E5S,
    "python _work/_复核/verify_e5_independent.py",
    "一致", "[我方复现]",
    "scores.json 共 2016 格 = 56 题×12 臂×3 重复，唯一 session_id/cell_id 各 2016；e2e_success == all(checks.values()) 不符数 0/2016；论文报告 11 配置 1848 次，未报告的 sham 臂不影响 B3/A5",
    ev_rel=E5S)

for cid, txt, val, p, ci, note in [
    ("E5-002", "四级基线 B0 17.26%、B1 26.19%、B2a 48.81%、B2b 49.40%，B3 最高 56.55%",
     "B3−B0 +39.29pp；B3−B1 +30.36pp；B3−B2a +7.74pp；B3−B2b +7.14pp",
     "B0 p=1.74e-07；B1 p=1.54e-06；B2a p=0.1501；B2b p=0.0885",
     "B3−B2b [0.00, +14.88]pp",
     "各点值与论文逐位一致。⚠ 论文未给出该主比较的 p 与 CI：仅「数据库接入相对通用模型」达显著，指导信息相对原子工具的增量 p=0.0885、区间下界恰为 0.00，0.05 水平未达显著"),
    ("E5-003", "移除结果后验证指导的 A5 通过率为 58.33%，较 B3 高 1.79 个百分点",
     "+1.79pp", "p=0.7419（精确配对符号翻转，|Σ| 统计量）；Holm p=1.0", "[-8.33, +4.76]pp",
     "与 v71 源头核验报告 p=0.741865 完全一致。⚠ 用只保留符号的符号检验会得 p=1.0，官方口径保留每题差值幅度，不可替换"),
]:
    row(cid, "E5", MAIN, "386/408/422", txt, val, E5S,
        "python _work/_复核/verify_e5_contrasts.py",
        "一致", "[我方复现]", note + "｜显著性：" + p + "｜CI：" + ci, ev_rel=E5S)

row("E5-004", "E5", MAIN, "408",
    "参数校验、字段语义、能力边界、来源信息与结果检查五项指导分别进行移除实验，前四项移除后规则通过率分别低 3.57、2.38、2.98 和 1.19 个百分点",
    "A1 −3.57 / A2 −2.38 / A3 −2.98 / A4 −1.19 pp",
    E5S,
    "python _work/_复核/verify_e5_contrasts.py",
    "一致", "[我方复现]",
    "点值逐位一致。六项消融家族 Holm 调整后 p 全部为 1.0（A1 0.4610 / A2 0.6421 / A3 0.5602 / A4 0.8692 / A5 0.7419 / A6 0.4264），即任何单项指导的移除与保留之间都未检出显著差异。v72 全文未提 Holm",
    ev_rel=E5S)

row("E5-005", "E5", MAIN, "66/382/402",
    "完整指导配置的规则通过率 56.55%，较原子工具基线高 7.14 个百分点，平均工具调用与输出 token 分别减少 32.95% 和 12.44%",
    "56.55% / +7.14pp / −32.95% / −12.44%",
    E5S,
    "python _work/_复核/verify_e5_contrasts.py",
    "一致", "[我方复现]",
    "复算 B3 平均调用 4.8452、输出 token 3534.7738；B2b 7.2262 / 4036.8036；减少比例 32.9495% 与 12.4363%，与论文逐位一致",
    ev_rel=E5S)

row("E5-006", "E5", MAIN, "（全文）",
    "主比较与消融的显著性表述",
    "（全文未给 p 值）",
    E5S,
    "python _work/_复核/verify_e5_contrasts.py",
    "不一致", "[我方复现]",
    "【须人工裁决】v72 正文与补充材料对主比较 B3−B2b 的 7.14 个百分点均未给出 p 值或置信区间，也未提 Holm；独立复算为精确配对符号翻转 p=0.0885、题目聚类 bootstrap 95%CI [0.00, +14.88]pp。v55 版本曾对 1024 对扩展评价给出 p=0.6358、CI [-1.5625,+0.7813]，v72 保留点值但丢失了 p 与 CI。v72 正文 main.tex:482 已有「增加指导信息不必然提升端到端表现」的表述，但未对主比较本身作显著性说明",
    ev_rel=E5S)

row("E5-007", "E5", MAIN, "（全文）",
    "D07 的结构性不可达",
    "（未在正文呈现）",
    r"05_评审与验收\BEST_v71_三项实验源头追查_20261023\源头核验报告.md",
    "type 05_评审与验收/BEST_v71_三项实验源头追查_20261023/源头核验报告.md",
    "一致", "[原始归档]",
    "冻结工具 cone_search 未暴露 page_size、客户端默认 1000，而 D07 要求每页 2 行（原评分器对所有相关 GET 逐一检查 rows=2）。原始 B3 D07 重复1 cell cfd26404080a866f4f757414a 记录到 111 次 rows=2 及 1 次 rows=1000。属共享工具与题目严格条件的结构性不匹配，不得计入模型能力",
    ev_rel=r"05_评审与验收\BEST_v71_三项实验源头追查_20261023\源头核验报告.md")

row("E5-008", "E5", SUP, "1071",
    "交叉匹配扩展评价：1024 个主验证来源及 96 个诊断来源，两组共 2240 次运行；B3 与 B2b 成功数 995/1024 和 999/1024；仅 B3 成功 18 对、仅 B2b 成功 22 对",
    "995/1024 vs 999/1024；18 vs 22",
    SUP,
    "type 10_脱敏复现包/BEST_v72_图2嵌入正文确认_20261023/source/supplementary_material.tex",
    "一致", "[官方产物文件]",
    "⚠ 口径隔离：v72 附录已把该扩展评价与四级基线分别统计、明确不混合，符合 v71 核验要求；但 v55 曾给出的 p=0.6358 与 CI [-1.5625,+0.7813] 在 v72 中已丢失。开发阶段 64 对比较 57/64 vs 49/64、p=0.09625 已明确未纳入",
    ev_rel=SUP)

row("E5-009", "E5", MAIN, "482",
    "指导消融中的差异表明，增加指导信息不必然提升端到端表现",
    "（定性表述）",
    MAIN,
    "grep -n '增加指导信息不必然提升端到端表现' 10_脱敏复现包/BEST_v72_图2嵌入正文确认_20261023/source/main.tex",
    "一致", "[官方文档明文]",
    "论文已对消融差异作定性披露；缺口仅在于未对主比较 B3−B2b 本身给出 p 与 CI（见 E5-006）",
    ev_rel=MAIN)

# ============ E6 ============
E6C = r"04_实验数据\E6_可复现性\实验产物\01_当前R3补测\R3-consistency.json"
E6CANC = r"04_实验数据\E6_可复现性\实验产物\01_当前R3补测\PROTOCOL-AMENDMENT-R2-CANCELLATION.json"
E6AUD = r"04_实验数据\E6_可复现性\实验产物\02_原批次结果与原始归档\R3-audit.json"
E6REM = r"04_实验数据\E6_可复现性\实验产物\01_当前R3补测\REMAINING-WORK.md"

row("E6-001", "E6", MAIN, "432",
    "32 个任务共进行 160 次运行，其中 133 次获得有效记录；21 个任务具有完整的五次有效重复，28 个任务可用于一致性估计",
    "160 次 / 133 有效 / 21 个五次 / 28 个可估计",
    E6C,
    "python -c \"import json;j=json.load(open(r'%s',encoding='utf-8'));print(j['coverage'],j['records'])\"".replace("%s", E6C.replace("\\", "\\\\")),
    "一致", "[我方复现]",
    "归档 coverage={tasks_with_5_valid:21, task_target:32, record_target:160, independent_task_units:30}、records=133；四项一致性指标的 task_units 均为 28",
    ev_rel=E6C)

for cid, name, pt, ci, key in [
    ("E6-002", "工具序列一致性 TSC", "0.8637", "[0.7869, 0.9310]", "TSC"),
    ("E6-003", "参数一致性 PAC", "0.8538", "[0.7980, 0.9066]", "PAC_call"),
    ("E6-004", "返回数据一致性 RDC", "0.7286", "[0.6315, 0.8167]", "RDC"),
    ("E6-005", "核心结论一致性 FCC", "0.8673", "[0.7810, 0.9405]", "FCC"),
]:
    cmd = ("python -c \"import json;j=json.load(open(r'" + E6C + "',encoding='utf-8'));"
           "print(j['aggregate']['" + key + "'])\"")
    row(cid, "E6", MAIN, "432", name + " 及 95% 置信区间",
        pt + "｜CI " + ci, E6C, cmd,
        "一致", "[我方复现]",
        "归档 point 与 bootstrap_95 逐位吻合（bootstrap 10000 次，种子 20261007）。辅助口径：RDC 数据条件化 0.7185（27 单位，CI [0.6210, 0.8086]），仅作参考",
        ev_rel=E6C)

row("E6-006", "E6", MAIN, "（全文）",
    "R2（D+7 跨日复测）的状态",
    "未执行（研究者主动取消）",
    E6CANC,
    "type 04_实验数据/E6_可复现性/实验产物/01_当前R3补测/PROTOCOL-AMENDMENT-R2-CANCELLATION.json",
    "口径不同", "[官方产物文件]",
    "⚠ 纠正 10-11 状态文档的表述：R2 不是「未到期的待办」，而是 2026-10-11 由研究者正式取消（R2_status=cancelled_before_execution，revision=E6-batch-repetition-consistency-U1-U6-no-R2，original_protocol_pass=false）。unmeasured_constructs 明确列出「D+7 跨日稳定性」与「服务商权重及在线后端跨日漂移」为不声称项。论文正确表述应为：报告批内一致性，不声称跨日稳定性与后端漂移",
    ev_rel=E6CANC)

row("E6-007", "E6", MAIN, "（全文）",
    "69 次 HTTP 402 余额错误的归属批次",
    "属原 R3 批次，不在论文所报告的补测批次内",
    E6AUD,
    "python -c \"import json;j=json.load(open(r'%s',encoding='utf-8'));print(j['model_api_failures'])\"".replace("%s", E6AUD.replace("\\", "\\\\")),
    "口径不同", "[官方产物文件]",
    "原 R3 批次：160 计划尝试、failure_attempts=95、model_api_failures.http_status_counts={'402':69}；R3 补测批次为 160 尝试 / 133 有效 / 27 失败。论文报告的是补测批次，两者不可混称",
    ev_rel=E6AUD)

row("E6-008", "E6", MAIN, "（全文）",
    "E6 仍保留的缺口",
    "E3 独立定量量表不足；M6 缺失；跨日稳定性未测",
    E6REM,
    "type 04_实验数据/E6_可复现性/实验产物/01_当前R3补测/REMAINING-WORK.md",
    "一致", "[官方产物文件]",
    "原文：取消未执行路线不改变既有失败或补算原完整协议通过；E3 独立定量量表不足和 M6 缺失也仍保留；教师定性反馈可用于讨论，不能代替完整独立定量评分",
    ev_rel=E6REM)

row("E6-009", "E6", MAIN, "（全文）",
    "失败归因分布",
    "（未在正文呈现）",
    E6C,
    "python -c \"import json;j=json.load(open(r'%s',encoding='utf-8'));print(j['attribution'])\"".replace("%s", E6C.replace("\\", "\\\\")),
    "一致", "[我方复现]",
    "OK 76 / ERR_PARAM_UNSTABLE 38 / ERR_CONCLUSION_UNSTABLE 12 / ERR_PARAM_SCHEMA 6 / ERR_BACKEND 1，合计 133 与有效记录数吻合。alpha_TSC=0.7261（28 单位，131 观测）",
    ev_rel=E6C)

# ============ 复现包与脱敏 ============
row("R-001", "复现包", MAIN, "（附录）",
    "E3/E6 最小复现包在 Windows 上的可运行性",
    "（未在正文呈现）",
    r"10_脱敏复现包\README-总览.md",
    "type 10_脱敏复现包/README-总览.md",
    "不一致", "[我方复现]",
    "各包本机实测状态（2026-10-13）：E1 pytest --co 159 tests ✅；E2 reproduce_e2.py --verify-only 通过 ✅；E4 pytest --co 53 tests ✅；E3 run_e3.py 缺 src 且受阻于 POSIX 专有 fcntl ❌；E5 verify_e5.py 面向另一归档、本包无 E5/MANIFEST.sha256.json ❌；E6 run_e6_formal.py 缺 evals.repro ❌。E3/E6 辅助程序不是一键可执行的独立软件，投稿包须明示",
    ev_rel=r"10_脱敏复现包\README-总览.md")

row("R-002", "脱敏", MAIN, "（附录）",
    "E6 归档中的绝对路径与用户名",
    "（未在正文呈现）",
    E6CANC,
    "type 04_实验数据/E6_可复现性/实验产物/01_当前R3补测/PROTOCOL-AMENDMENT-R2-CANCELLATION.json",
    "不一致", "[我方复现]",
    "【隐私】该 JSON 内嵌 historical_publication_snapshot=<HOME>/Documents/论文相关/AI Ready/Program/AI/temp/e6-formal/publication-drafts/before-R2-cancellation-175832，含 macOS 绝对路径与用户名。若纳入投稿包须按脱敏规则清理",
    ev_rel=E6CANC)

row("R-003", "复现包", MAIN, "（全文）",
    "10-11 状态文档与 v72 稿件的版本关系",
    "（该文档已过时，不得作为数字真源）",
    r"08_方案与笔记\E2E5重构计划\BEST_Skill_实验状态与投稿待办.md",
    "type 08_方案与笔记/E2E5重构计划/BEST_Skill_实验状态与投稿待办.md",
    "不一致", "[官方产物文件]",
    "该文档记 E1 加权总分 0.7803 门禁 FAIL、E6 R1/R3 一致率 0.7989/0.8940；v72 稿件对应值为 E1 0.9530、E6 0.8637/0.8538/0.7286/0.8673。数字真源只能是 v72 稿件 + 各实验原始归档",
    ev_rel=r"08_方案与笔记\E2E5重构计划\BEST_Skill_实验状态与投稿待办.md")

row("R-004", "稿件", MAIN, "64/71",
    "作者、单位、通讯邮箱、基金、致谢、利益冲突、作者简介",
    "（全部为占位符）",
    MAIN,
    "grep -n '待补充\\|作者姓名\\|单位名称' 10_脱敏复现包/BEST_v72_图2嵌入正文确认_20261023/source/main.tex",
    "无证据", "[官方文档明文]",
    "【投稿前必填】main.tex:64/65/70/71 仍为「作者姓名」「单位名称」「待补充」「NAME Namename」等占位符。需人工填写并同步生成作者中英文简介、贡献说明与照片",
    ev_rel=MAIN)


def main():
    os.makedirs(OUTDIR, exist_ok=True)
    with open(OUT, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(HDR)
        w.writerows(R)
    from collections import Counter
    print("总行数:", len(R))
    print("一致性判定分布:", dict(Counter(r[9] for r in R)))
    print("按实验分布:", dict(Counter(r[1] for r in R)))
    print("写出:", OUT)


if __name__ == "__main__":
    main()
