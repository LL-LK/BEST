"""仅整理既有真实结果与交付包；不调用API，不改冻结协议或评分。"""
from __future__ import annotations

import collections
import copy
import hashlib
import json
import zipfile
from pathlib import Path

import numpy as np

from common import HERE, current_batch, now, read_json, write_json
from prepare import verify_bundle
from pipeline import all_answers
from reporting import load_judged


def finalize():
    batch = current_batch()
    bundle = verify_bundle(batch)
    rows = load_judged(batch, bundle, all_answers(batch, bundle))
    result = read_json(batch / 'report.json')
    assert result['rating']['valid'] and len(rows) == 216
    audit = read_json(batch / 'final-audit.json')
    assert audit['resume_success_answers_unchanged'] and not audit['secret_matches']
    # 保留冻结报告程序的原始输出；只修正主评来源说明，不改变其统计值。
    write_json(batch / 'automated-report.json', result)
    result = copy.deepcopy(result)
    result['expert'] = {
        'status': 'pending', 'note': '当前对话助手直接主评，独立天文专家复核待完成',
        'agreement': None, 'reason': '未收到独立专家评分，不能计算AC1、α、ICC或加权κ',
    }
    result['delivery'] = {
        'at': now(), 'primary_context_isolated': False,
        'primary_model_api_verified': False, 'primary_api_calls': 0,
        'subject_model': 'deepseek-flash', 'expert_answers_required': 219,
        'annotation_status': '当前助手逐份主评及复核；独立专家尚未检验枚举完整性和判定',
        'source_note': '只修正冻结报告中遗留的GPT-6.1主评标签；未改变原始评分、主指标或协议',
    }
    # 补充所有五项主指标的配对题号bootstrap；同一题的两组与三次一起抽样。
    main = [r for r in rows if r['tier'] == 'fixture']
    ids = [i['id'] for i in bundle['items'] if i['tier'] == 'fixture']
    lookup = {(r['group'], r['item_id'], r['repeat']): r for r in main}
    fields = ['critical_hit', 'critical_total', 'unsourced_num', 'numbers_total',
              'unsupported_claim', 'claims_total', 'qualifier_hit', 'qualifier_total',
              'static_as_lc', 'slr_eligible']
    data = {}
    for group in ('S-A', 'S-B'):
        data[group] = np.array([[
            [lookup[group, i, repeat]['counts'].get(f, int(i in bundle['slr_ids']) if f == 'slr_eligible' else 0)
             for f in fields] for i in ids] for repeat in (1, 2, 3)], dtype=float)
        for ix, i in enumerate(ids):
            if i not in bundle['slr_ids']:
                data[group][:, ix, 8] = 0
    indexes = np.random.default_rng(20261006).integers(0, 32, size=(10000, 32))
    totals = {g: a[:, indexes, :].sum(axis=2) for g, a in data.items()}
    pairs = {'sfa': (0, 1), 'ungr': (2, 3), 'ucr': (4, 5), 'rqc': (6, 7), 'slr': (8, 9)}
    intervals = {}
    for field, (numerator, denominator) in pairs.items():
        values = {}
        for group, a in totals.items():
            values[group] = np.divide(a[..., numerator], a[..., denominator],
                                     out=np.full(a.shape[:2], np.nan), where=a[..., denominator] != 0)
        delta = np.median(values['S-A'], axis=0) - np.median(values['S-B'], axis=0)
        finite = np.isfinite(delta)
        intervals[field] = {
            'point_A_minus_B': result['main']['systems']['S-A']['metrics'][field]['median'] -
                               result['main']['systems']['S-B']['metrics'][field]['median'],
            'bootstrap_95': np.quantile(delta[finite], [.025, .975]).tolist(),
            'valid_resamples': int(finite.sum()), 'undefined_resamples': int((~finite).sum()),
        }
    assert intervals['sfa']['bootstrap_95'] == result['main']['sfa_difference']['bootstrap_95']
    write_json(batch / 'paired-bootstrap-all-metrics.json', {
        'resamples': 10000, 'seed': 20261006, 'unit': 'paired_item_all_three_repeats',
        'note': '负值在UNGR/UCR/SLR上有利于S-A；未作多重检验校正；专家未复核，区间只反映题目重抽而非评分偏差',
        'metrics': intervals,
    })
    write_json(batch / 'FINAL-RESULTS.json', result)
    write_json(batch / 'agreement.json', result['expert'])
    usage = read_json(batch / 'usage.json')['records']
    token_totals = {f: sum(r['usage'].get(f, 0) for r in usage if r['usage'])
                    for f in ('input_tokens', 'output_tokens', 'total_tokens')}
    redlines = collections.Counter(e['redline'] for e in result['error_taxonomy'])
    affected = len({(e['group'], e['item_id'], e['repeat']) for e in result['error_taxonomy']})
    lines = [
        '# E3 实验交付报告：真实采集与助手主评完成，专家复核待完成', '',
        f'批次 `{batch.name}`，整理时间 {now()}。采集 **216/216**（192 份离线主测、24 份在线辅测），主评分 **216/216**，三份已知坏回答全部检出。', '',
        '被测模型实际为 **deepseek-flash**，不是原计划中的 GPT-6.1。S-A 获得完整 skill 与领域材料；S-B 获得表名、列名和两阶段协议；每题每组三次独立上下文。Responses 接口，reasoning effort=max，max_output_tokens=32768，未发送 temperature。两组请求参数相同。', '',
        '主评由当前对话助手直接阅读并逐份注释，**没有调用评分 API**。助手参与准备并见过组别映射，没有独立评分上下文，不能称为独立盲评，也没有通过 API 核验主评模型身份。匿名化是材料处理措施，不能证明主评盲性。', '',
        '## 离线主测结果', '',
        '下表为三次重复的中位数，括号为最小值–最大值；32 个独立题号，三次重复不当成96道独立题。SFA/RQC 越高越好，UNGR/UCR/SLR 越低越好。', '',
        '| 指标 | S-A 完整 skill | S-B 普通包装器 |',
        '|---|---:|---:|',
    ]
    labels = {'sfa': 'SFA 关键科学断言命中率', 'ungr': 'UNGR 无来源科学数值率',
              'ucr': 'UCR 无支撑科学主张率', 'slr': 'SLR 静态误称时序率',
              'rqc': 'RQC 必要限定语覆盖率', 'pass_rate': '辅助：逐回答合格率'}
    for field, label in labels.items():
        cells = []
        for group in ('S-A', 'S-B'):
            x = result['main']['systems'][group]['metrics'][field]
            cells.append(f"{x['median']:.2%}（{x['range'][0]:.2%}–{x['range'][1]:.2%}）")
        lines.append('| ' + label + ' | ' + ' | '.join(cells) + ' |')
    mc = result['main']['mcnemar']; df = result['main']['sfa_difference']
    lines.extend([
        '', '每次重复的 critical 分母为71项，限定语分母为73项，SLR 分母为实际涉及时序语义的14题。数值及主张的逐条分子、分母、证据与理由保存在 `scores/`，分组重复汇总见 `FINAL-RESULTS.json`。', '',
        f"SFA 中位数差 S-A−S-B 为 {df['point']:.2%}，按题号成组重抽10,000次的95%区间为 {df['bootstrap_95'][0]:.2%}–{df['bootstrap_95'][1]:.2%}。逐题三次多数合格的精确 McNemar：仅A合格{mc['a_only_pass']}题、仅B合格{mc['b_only_pass']}题，双侧 p={mc['p_exact_two_sided']:.8f}。", '',
        '这些是当前主评下的结果，不包含评分者偏差的区间，也不能代替独立专家复核。其他主指标的配对区间见 `paired-bootstrap-all-metrics.json`；不把它们当作预注册的多重显著性结论。', '',
        '第六项指标是人机评分一致性：**暂缺，全部统计量为空**。尚无专家评分，不能产生AC1、α、ICC或加权κ。统计实现已用非均匀类别、常量、缺评、偏移及不足样本的独立参考算例验证，见工作流测试记录。', '',
        '## 科学表现与在线辅测', '',
        f'流程完成不等于科学合格。当前主评在S-B的{affected}份回答中检出科学红线；S-A未检出本轮红线，仍有关键断言遗漏、额外无支撑主张与列定义误读。总体不能报告“两组均科学合格”。红线逐项证据见 `FINAL-RESULTS.json/error_taxonomy`。',
        f'红线项计数：{json.dumps(dict(redlines), ensure_ascii=False)}；同一回答可有多个项，项数不等于回答数。', '',
        '在线辅测24份单独统计，没有混入离线主表。同题同次两组解释同一个真实回包，只比较解释，不评价工具选择策略。A04/F02均为PS1成功零行；G04三次为E_NAME_UNRESOLVED，未建立会话；F04三次HTTP200但正文error=Not Found，是软错误，仅证明所探测表单路由不可用，不能推断整个后端永久不存在。请求、正文与错误状态见 `live/`。', '',
        '## 需要补充和优先复核的内容', '',
        '1. 请安排一名未参与出题的天文专家，只接收下述专家压缩包，独立完成219份匿名样本的评分。不要把主持人映射、原始组别请求或助手评分一并交给专家。收到评分后才能计算人机一致性和分歧。',
        '2. E04题面假定scr_lamost表有Teff/logg，但冻结列清单没有这两个输出列，且题面附带Gaia构造样本；校准标准星的上游选择范围与公开输出列不是同一回事。正确指出缺列的回答可能仍未命中原固定critical。这是题面/评分材料问题，不能把相应失分全部归给模型。主表保留原32题，没有事后删题。专家须重点复核，后续改题需要新批次。',
        '3. 冻结领域材料包含LAMOST DR11“2.18G星”、GALAH DR4“281.5M星”等数量单位口径，尚需核验原站字段/单位。回答可溯到材料不代表该材料已经得到独立科学验证。此次未改动这些冻结材料。',
        '4. 数值/主张枚举由助手人工完成；已拆分若干原先合并的表格证据并统一无出处阈值的来源判定，但没有第二位评阅人确认枚举完整性。UNGR/UCR尤其需要专家逐量复核。“无来源”包括未给出处的近似正确背景值，不等于该数字必然为假。', '',
        '## 验证、失败与实际用量', '',
        'E3现有测试及新增工作流测试共68项通过。冻结材料和源码哈希、216份原始回包与输入、评分证据片段及原始注释血缘均已核验。封禁网络后再次执行续跑与评分，新增网络调用为0，成功回答文件哈希完全不变。两组三次主辅测配额完整，公开专家样本无显式组别/模型字段，密钥扫描除.env外无匹配，Git状态与准备时一致。见 `final-audit.json`。', '',
        '当前批次保留5次输出预算截断失败，随后按同一冻结参数重采成功；未把错误回包或截断文本替代为正式回答。重采会使正式结果条件于成功完成，失败记录仍须保留。旧16384预算及更早批次只作历史诊断，没有混入当前216份。',
        f"API实际用量共{len(usage)}条去重回包：216份正式回答、5次截断失败、1次连接检查；输入{token_totals['input_tokens']:,}、输出{token_totals['output_tokens']:,}、总计{token_totals['total_tokens']:,} tokens。包含推理token和缓存输入；没有服务商价格信息，不估算费用。助手主评未调用外部API，不能把本对话推理成本报告为零。", '',
        '原评分修订保留在 `score-revisions/`、`assistant-imports/` 和 `rating-revision-audit.json`。只修正注释中的数据误读、证据拆分和出处口径，没有改写真实回答或更换冻结提示。', '',
        '## 交付与使用', '',
        '- `E3-expert-blind-219.zip`：可直接交给专家的独立乱序包，只含专家目录。',
        '- `answers/`、`scores/`、`live/`、`failures/`：完整真实记录，供主持人复现。',
        '- `FINAL-RESULTS.json`：最终整理结果及正确主评来源；`automated-report.json`保留冻结报告器的原输出，其中专家待完成说明仍有旧GPT-6.1标签，以本报告更正后的来源为准。',
        '- `manifest.json`、`PROTOCOL.md`、`frozen-code/`：被冻结的参数、协议与代码。',
        '- `operator/`：私有映射，不交给专家。', '',
        '专家将 `scorecard.blank.json` 复制后独立填写。收到其原始JSON后，在项目根目录运行：', '',
        '```bash',
        "temp/e3-e6/venv/bin/python temp/e3-formal/run_e3.py import-expert --expert-scores '/绝对路径/专家评分.json'",
        '```', '',
        '所有219个样本必须完整有效且隐藏反证全部检出，才能认定专家复核完成；原始专家评分独立保留，不覆盖助手主评。', '',
        '环境：Python3.14.7；requests2.34.2、urllib3 2.8.0、PyYAML6.0.3、numpy2.5.3、pytest9.1.1。完整安装版本在 `temp/e3-e6/requirements.lock.txt`。',
    ])
    text = '\n'.join(lines) + '\n'
    (batch / 'FINAL-REPORT.md').write_text(text)
    (HERE / 'FINAL-REPORT.md').write_text(text + '\n完整产物目录：' + str(batch) + '\n')
    package = batch / 'expert-blind'
    # 专家无需知道隐藏对照的身份；以下只补齐六类判定的通用定义。
    (package / 'redline-definitions.json').write_text(json.dumps({
        'fatal_number': '无来源科学数值直接决定周期、振幅、概率、零点或其他科学结论',
        'static_as_lc_conclusion': '将静态测光当作时间序列并由此下科学结论',
        'sentinel_calculation': '将缺失哨兵当作真实科学数值解释或计算',
        'identity_misattribution': '将Gaia、LAMOST、GALAH等产物误称BEST独立测量',
        'absence_as_nonexistence': '无记录推为天体不存在，或将错误回包解释为成功零行',
        'unmarked_as_constant': '无变星标记推为已确认物理恒定',
    }, ensure_ascii=False, indent=2) + '\n')
    zip_path = HERE / 'E3-expert-blind-219.zip'
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as z:
        for p in sorted(package.rglob('*')):
            if p.is_file():
                z.write(p, p.relative_to(package))
    with zipfile.ZipFile(zip_path) as z:
        assert len([n for n in z.namelist() if n.startswith('samples/')]) == 219
        assert not any(x in n for n in z.namelist() for x in ('operator', 'assistant', 'scores/'))
        assert z.testzip() is None
    write_json(batch / 'finalization-manifest.json', {
        'at': now(), 'postprocessor_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'input_report_hash': hashlib.sha256((batch / 'automated-report.json').read_bytes()).hexdigest(),
        'final_results_sha256': hashlib.sha256((batch / 'FINAL-RESULTS.json').read_bytes()).hexdigest(),
        'expert_zip_sha256': hashlib.sha256(zip_path.read_bytes()).hexdigest(),
        'scores': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((batch / 'scores').glob('*.json'))},
        'postprocessor_changes_subject_protocol': False, 'network_calls': 0,
    })
    print({'report': str(HERE / 'FINAL-REPORT.md'), 'expert_package': str(zip_path),
           'answers': 216, 'primary': 216, 'expert_status': 'pending'})


if __name__ == '__main__':
    finalize()
