# E6 可复现性、效率与用户可用性 — 跑批报告 (REPORT)

> **本文件是人工撰写的归档，不由跑批覆盖**（`make eval-e6` 只把结果打印到终端）。
> 原因：runner 的 `--md` 只渲染 R0 一致率与归因分布，效率面（EF1–EF7）、
> 可用性面（U1–U7）、反证自证与「交付后修复记录」7 条都是人写的分析，
> 覆盖会丢失。需要重跑请用
> `python evals/repro/run_e6.py --lane R0 --repeat 5 --selftest --score
> --efficiency --usability --md`。

> 由 `python evals/repro/run_e6.py --lane R0 --repeat 5 --score --efficiency
> --usability` 实测生成 (2026-09-28)。R0 路 (无模型, 预写调用序列直打工具,
> 离线回放) **已实跑**; R1/R3 路需真模型 API, 留 adapter 接口 (本仓离线
> 纪律, 本轮不接模型 — 跑批器只报 adapter_required, 不造假数据)。

## 头部 (文档 §12 必披露 12 个数中的离线可得项)

- 任务集: 32 条 (REPRO-01..26 映射 E1 的 26 条 + REPRO-27..32 新增);
  任务集指纹由 manifest.task_set_fingerprint() 实算 (改一字即不可比);
- 回放: `evals/repro/transport.py` (自包含两阶段回放; 与 E2 transport 的
  等价性由 P7 的 `evals/equivalence/` 字节级断言守护 — 本实验零跨实验 import);
- frozen manifest: 八项指纹 (任务集/tools.schema/system prompt/model_id/
  temperature/seed/数据版本) — 缺一即抛 (fail-closed, validate_manifest);
- skill_fp / bestfp before-after / prompt_fp / tools_schema_fp: 由
  `--freeze-manifest` 落 temp/repro/runs/ (临时产物只进 temp/ 铁律);
- model_id/temperature/seed.honored: R0 路为 none-R0 / 0.0 / false (如实记);

## R0 路结果 (预写序列 × 5 次重复, 实测)

区间口径：**按任务分组重抽样**（`stats.bootstrap_mean_ci`，百分位法，固定种子
20260928）—— 四一致率是"每任务一个比值再跨任务平均"，推断单位是**任务**，
故重抽任务而非重抽 Bernoulli 观测。样本量随附：计分任务 18、总重复 90 次。

| 指标 | 点估计 (跨任务均值) | 95% 区间 (分组重抽样) |
|------|--------|------------|
| TSC | 1.0000 | [1.000, 1.000] |
| PAC | 1.0000 | [1.000, 1.000] |
| RDC | 1.0000 | [1.000, 1.000] |
| FCC | 1.0000 | [1.000, 1.000] |

> ⚠ **零宽区间 = 任务间零离散度，不是"可复现性被证明为 1.0"**。18 条任务的
> 取值全为 1.0，重抽样只能抽出同一个值，区间必然退化为零宽（`ci_degenerate`
> 四项全中）。零方差样本给不出有限样本宽度的区间；这条界面的诚实结论是
> "R0 覆盖的 18 条上未观测到任何任务间差异"，而不是"复现性为 1.0 的确定结论"。

> **口径修正记录**：早先实现把跨任务均值 `×100` 当成"成功次数"再除以固定
> `100`（`wilson_interval(round(v*100), 100)`），于是 **5/5 与 100/100 会算出
> 同一个 [0.963, 1.000]** —— 区间宽度与真实重复次数、覆盖任务数完全脱钩。
> 该口径已废除；`wilson_interval` 仍保留给真正的二项比例（如 §5.5 引用的
> 5/5 参考值），但不再用于跨任务均值。

- 覆盖: 18/32 (未覆盖 = 需 LLM 决策的 clarify/reject-utterance/safety 类, 属 R1/R3 路);
  未覆盖的 14 条需 LLM 决策 (clarify/reject-utterance/safety), 属 R1/R3 路;
  `--require-full-coverage` 可把该缺口升为阻断项;
- 归因分布: ERR_BACKEND=5, ERR_PARAM_SCHEMA=5, OK=80
  (ERR_BACKEND = REPRO-30 软 404 的 5 次回放, 非我方缺陷; ERR_PARAM_SCHEMA
   = REPRO-31 越界半径的 5 次回放 — 拒绝路径的确定性即被测对象);

## 清单绑定 (冻结 ≠ 锁住)

`--freeze-manifest` 落盘的清单**必须被执行路径认领**：`--manifest <path>` 在跑批前
逐项核对 `execution.lane` / `execution.repeat` / `tool_schema.code_side` 与
`exposed_side` 指纹，与本次实跑不符即阻断（`manifest_mismatch`，退出码 1）。

| 情形 | 结论 |
|------|------|
| 带 `--manifest` 且逐项核对通过 | `manifest_binding.bound=true`，可作为"按清单复现"的证据 |
| 不带 `--manifest` | `bound=false` + `manifest_note`：只证明"这一轮跑批是什么样"，**不是**复现成功证据 |
| 带 `--manifest` 但参数/指纹不符 | 退出码 1，阻断项随报告同出 |

> 早先 `--freeze-manifest` 分支落盘即 `return`，后续 R0 执行既不读清单也不接受
> 清单路径 —— "落盘即冻结"因此锁不住任何东西：换一组参数重跑，报告照样出得来。
> 仓内现有历史清单（`temp/repro/runs/manifest-*.json`）为修复前产物，未绑定。

## 效率 (EF, 实测; 阈值未标定 — rubric.yaml calibrated:false)

- EF1 请求效率比 η = 0.7069 (预写序列接近理论最小; R1 真模型
  场景才有优化空间);
- EF3 冗余调用率 = 0.0000 (0/0);
- EF4 无效重试率 = 0.0000 (R0 无重试);
- EF5 过量翻页 = 10 次;
- EF6 零请求完成率 = 1.0000 (元数据类 REPRO-32 实测 0 请求);
- EF2 墙钟: 回放不计网络等待 (报告注明); EF7 tokens: R0 无模型, 记 null;

## 可用性 (U, 实测; R0 结构性边界须声明)

- U1 首次可用率 = 0.9444; U3 澄清质量 = 1.0000;
- U2 错误可操作性 = 0.0000 (failed_runs=5: R0
  回放不产用户面答案三要素 — 该指标的硬门槛判定在 R1 路 (真 agent 答案);
  R0 的 U2=0 是** lane 结构性事实**, 已在报告声明, 不粉饰);
- U4 答案自解释性 = 0.0000 (同上, 依赖 R1 的 final_answer 文本);
- U5 步数比 = 0.6667; U6 诚实降级率 = 1.0000;
- U7 认知负荷: 无评阅人 (效力不足, 不进门禁 — 文档 §7.2);

## 反证夹具自证 (两组 12 件, 实测)

- metascore = 1.00 (12/12 检出,
  pass=True);
- 第一组 (文档 §9 六类一致性扰动): BF-1 半径漂移 / BF-2 表漂移 /
  BF-3 单位错 / BF-4 删行 / BF-5 EMPTY-ERROR 翻转 / BF-6 结论数值改位;
- 第二组 (trace 完整性六类): 事件缺失 / 指纹不匹配 / 重跑不一致 /
  成本造假 / 时间戳乱序 / 脱敏遗漏 — 检测器 trace.validate_trace + redact
  (TI-2/TI-4 原为恒真自证式夹具, 2026-09-29 改为调独立检测器);

## 交付后修复记录 (2026-09-29, 测试摸底暴露的真缺陷)

1. **manifest.canary_fingerprint 值盲** (只指纹列名): 同列名不同数值的数据
   漂移漏检 → 改整行 (键+值) 规范化 JSON; 原 xfail 已转正;
2. **trace.validate_trace 不复核 payload_fp** (写时算而不验): 纯内容篡改
   漏检 → 增 payload_fp_mismatch 重算校验 + 成本跨字段一致性校验
   (tool_call>0 却 http_requests=0 → cost_inconsistent);
3. **r0_lane 软 404 记成空 rowset** (ERROR→EMPTY, 文档 §3.1 严禁): 任一
   工具结果 ok=False → outcome=fail + card.kind=refusal + caveats 带错误码;
4. **fcc.sub_item_failures 定位不准** (kind 翻转连带多报 key_numbers):
   key_numbers 子项改单独比对 (带 1e-6 容差);
5. **attribution 规则 3 对 list 精确比较** (与 §5.2 columns 集合口径不符):
   list 值改排序键集合比对;
6. **usability.U5 单位不一致** (请求数 ÷ 工具步数): 新增
   theoretical_min_steps (锥搜/count/fetch_page/crossmatch=1 步, 元数据=0
   步), U5 回归"工具步数 ÷ 理论最小步数"口径;
7. **rubric.yaml 未登记 TI 组**: 补 selftest_fixtures_trace_integrity 六条。

## 已知边界 (实验设计声明, 不粉饰)

1. R1/R3 路 (真模型 × 同环境 / 真模型 × 异环境) 需模型 API — adapter 接口
   已留 (run_e6.py --lane R1/R2/R3 返回 adapter_contract), 接入后判定逻辑
   (tsc/pac/rdc/fcc/attribution/efficiency/usability) 直接复用;
2. R0 覆盖 18/32 (工具层确定性任务); 覆盖率显式披露, 不当作 32/32;
3. U2/U4 在 R0 路为结构性低分 (无用户面答案) — 硬门槛判定以 R1 为准;
4. 二项比例上 `N=5` 的区间仍宽（5/5 一致 → 约 [0.57, 1.0]）—— 只报点估计+区间,
   不做达标强断言 (文档 §5.5); 跨任务均值改用分组重抽样区间并随附任务数/重复数,
   零宽区间已按"任务间零离散度"标注; McNemar 效力约 0.6–0.7, 须声明;
5. tokens 缺失记 null, 禁止估算填数 (cost_est 需单价与计价日期同报);
6. 跨日 R2 与 E7 (漂移定量) 联动, 单独排期 (D+7); E6 只做 DRIFTED 门禁。
