# E1–E6 实验解锁清单（谁缺什么、谁能解、解锁后跑哪条命令）

> 本清单回答一个问题：**六个实验里哪些结论是真跑出来的，哪些只是管线自证。**
> 判定口径统一为铁律 5「禁 fail-open」+ 铁律 7「离线纪律，评测一律回放」。
>
> 状态快照：2026-10-03。六个 runner 当日全部 `exit 0`，
> `evals/` 下 358 个测试全绿。但**没有一项实验测过真实模型**。

---

## 1. 一句话总览

| 实验 | 跑批结论证明了什么 | 还没证明什么 | 缺什么才能解锁 |
|------|------------------|-------------|---------------|
| E1 | 六维判定器能把「期望轨迹」判满分；逐维通过线已有闸门执行 | 真实模型的工具选择与参数正确率 | 真模型跑批轨迹 `source=live-run` |
| E2 | 回放与七指标判定管线自洽 | 金标准**经人工审核** | 17 份签字单联签字（见 `eval-E2-signing-guide.md`） |
| E3 | 37 题题集与 L0 预筛器就位 | **任何**模型语义能力 | 37 份模型回答（LLM 判定，人工已取消） |
| E4 | 传输层 15 条故障注入下处置正确 | 话术层 35 条的处置质量 | LLM agent（C/D 级亦由 LLM 判定） |
| E5 | 11 装配的离线相对排序 | 真模型下的排序与统计显著性 | 真模型跑批 ≥3 次重复 |
| E6 | R0 路 18 条工具层任务的确定性 | LLM 决策层的 14 条 + 跨日稳定性 | 模型 API（R1/R3）+ D+7（R2） |

---

## 2. 逐实验解锁条件

### E1 NL→工具决策 —— 缺真模型轨迹

- **现状**：`evals/nl2tool/traces/golden/` 26 条全部是 `gen_golden.py` 从标注反推的
  合成轨迹（`source=golden-from-annotation`）。runner 自己会打 provenance 警告：
  「用于判定器管线自证，**不是模型评测结果**」。
- **不解锁的后果**：六维全 1.0 这个数字**不能对外引用**。它衡量的是
  「标注与判定器是否自洽」，与模型能力无关。
- **解锁条件**：把真实跑批轨迹放进 `evals/nl2tool/traces/`（`source=live-run`），
  即至少 3 次重复采样（E1 §8 稳定性要求）。
- **解锁后**：`python evals/nl2tool/runner.py --traces evals/nl2tool/traces --md`
  （注意**不带** `golden/` 限定），报告里的 `trace_sources` 应出现 `live-run`。

### E2 金标准一致性 —— 缺人工签字 + **素材 16/17 为合成**（指引已备好）

- **⚠️ 2026-10-03 双路独立核验新发现（本节最重要的一条）**：
  对现有 17 份做了两路核验（人工：独立 haversine 重算 + 行集复现；
  skill：VizieR 真实 Pan-STARRS 查询），发现：
  - **作为一致性实验站得住**：行集/排序/截断三元组/四态裁决全部自洽 ✅；
  - **但素材真实性有系统问题** 🔴：
    **11 份合成（`syn_*`）+ 3 份合成却挂在名为 `ps1_*` 的「L 类真实快照」下
    + 1 份真实数据但掺了 1 颗位于锥心的人造星**（`cone_5as`）。
    `cone_60as` 声称 2 行，真实 PS1 该天区 60″ 内有 **23 行**。
  - **结论**：E2 证明的是「被测代码与独立 oracle 在同一批素材上对得上」，
    **不是**「对真实天文数据的取数正确」。引用 E2 分数时**必须同时给出
    `material_class`**（`synthetic`/`live-dirty`/`live-pure`）。
  - **改造清单**见 `docs/eval-E2-groundtruth.md` §4.6.6（P0 记账 → P1 换 live 素材 → 再签字）。
- **现状**：17 份金标准由生成器自签；17 份签字单联全未签。
- **解锁条件**：按 `docs/eval-E2-signing-guide.md` 逐份核对并签字（第二人，
  非 `gen_gold.py` 作者）。
- **解锁后**：`python evals/groundtruth/run_e2.py --repeat 3 --json <out>.json`
  报告中 `human_review_complete` 应转 `true`、`review_provenance.human = 17`、
  `review_disclosure` 为空。
- **已实装（2026-10-04 改为纯披露）**：`--require-human-review` 闸门**已取消**：
  它从未放行过任何一个 case（全为自签），启用即整批恒 FAIL。签字状态改由报告
  如实披露，双向自证测试已随之改写为「披露到位 / 不阻断」。

### E3 语义与幻觉 —— 缺口最大

- **现状**：`n_answered = 0`。`evals/semantics/runs/` 与 `gold/` **两个目录都不存在**。
  报告里九个数表是「无受试系统数据」，`review_mode: llm-only`，
  错误谱系表待判。`README.md` §12 防失真清单 8 项**全部未勾选**。
- **不解锁的后果**：E3 对模型语义能力的贡献目前**为零证据**。
- **解锁条件（两步，顺序不可颠倒）**：
  1. 接入模型跑批，产出 37 份回答（33 fixture + 4 live，live 不进主指标）；
  2. **LLM 依 `rubric.yaml` 判 37 题**（人工评阅已于 2026-10-03 取消，E3 §8）。
     **先跑 8 题 pilot 校准 rubric —— 4 份反证夹具必须全判对（metascore=1.00）方可扩全量**。
- **解锁后**：`python evals/semantics/runner.py --answers <回答.json> --md`

### E4 鲁棒性与安全 —— 缺话术层执行

- **现状**：Tier W 15/15 **真跑过**（故障注入桩真的让被测代码遇到超时/断连/畸形回包）。
  Tier P 35 条**只做了标注完备性预检**（`annotation_problems: []`），
  runner 自注「本轮不跑批」。RB-C01..C18 复合变体按文档要求 second_round 延后。
- **唯一真实工程发现**：F-E4-01 —— `BestSource.from_row` 接受「有 ra 无 dec」的
  半行并原样入库（已修复，RB-29 随之转 PASS）。
- **解锁条件**：接入 LLM agent 跑 Tier P 的 A/B 级（约 12 条，仍可程序判定）；
  C/D 级（实测 12 条）改由 LLM 依 §3 决策表判定。
- **解锁后**：`python evals/robustness/runner.py --tier P --md`

### E5 基线与消融 —— 缺真模型

- **现状**：`--scripted` 用 ScriptedLLM 替身离线跑。报告**已自列三条不可测项**：
  - Δ1（B0→B1 的文档知识贡献）**不可分辨** —— 答案渲染只由 4 个组件开关驱动，
    B1 的公共文档知识未建模；
  - sham 与 A2 **退化为等价** —— sham 的鉴别力测不出来；
  - A1/A5 的效应**只集中在边界题** —— 报告明确写「不得据此断言『仅此一题受影响』」。
  - T4 统计表（McNemar / Wilson CI / Holm / bootstrap）与 T5 错误谱系**出不来**。
- **解锁条件**：真模型跑批 ≥3 次重复（§11 阻断项 7：重复 < 3 不得下显著性结论）。
- **⚠️ 接真模型不是配置项，是待写代码**（2026-10-03 核查更正）：
  本文档此前写「去掉 `--scripted` 即接真模型」，**不成立**。
  - `evals/ablation/runner.py:180-186` 无条件把 `report["mode"]` 写成 `"scripted"`，
    `--scripted` 只是一个 `store_true` 装饰器，**代码里没有 live 分支**；
    照原说法操作会得到「看似接了模型、实则仍是替身」的静默结果。
  - `evals/ablation/harness/adapters.py:139` 的 `ScriptedLLM` 是 `LLMAdapter` 的
    **唯一**实现，docstring 自述「本仓离线纪律: 不调真实模型; 接口留 `LLMAdapter`
    抽象, 未来接真模型时实现同名的 plan/render 即可」。
  - **解锁条件三件事**（按顺序）：① 裁决是否豁免铁律 7；② 取得可程序调用的模型出口；
    ③ 实现 `LLMAdapter` 的真模型子类（`plan`/`render`）。
- **解锁后**：`python evals/ablation/runner.py --systems B0,B1,B2b,B3 --repeat 3`
  （须先有第 ③ 步的 live adapter，否则无论加不加 `--scripted` 都仍是替身批）

### E6 可复现性 —— 缺 R1/R3/R2

- **现状**：R0 路（无模型、预写序列直打工具）已实跑 5 次，四一致率
  TSC/PAC/RDC/FCC 全 1.0000，Wilson 95% `[0.963, 1.000]`，**覆盖 18/32**。
  未覆盖的 14 条需 LLM 决策（clarify / reject-utterance / safety），属 R1/R3。
- **已知结构性低分（已在报告声明，不粉饰）**：U2/U4 在 R0 下为 0
  —— 回放不产用户面答案三要素，硬门槛判定以 R1 为准。
- **⚠️ E6 综合分有一半现在不可用（2026-10-03 新增）**：三面权重 R 0.50 / E 0.25 / U 0.25，
  而 **E/U 两面阈值全部未标定**（`rubric.yaml` `calibrated: false`；方案 §6/§7.1 自述
  「占位建议，必须标注未标定」）。**标定前只有 R 面有判据**，
  任何「E6 综合分 ≥ 0.90」的表述在标定前都不成立（E6 §8.1.1）。
  标定成本很低：**10 条任务 × 5 轮 pilot ≈ 50 次 run**（不到 E5 全量的 1/25），
  且**不需要真模型**即可先标 R 面的 E/U 指标口径。
- **解锁条件**：R1（同环境真模型）/ R3（异环境真模型）需模型 API；
  R2 跨日与 E7 联动，D+7 单排。
- **解锁后**：`python evals/repro/run_e6.py --lane R1 --repeat 5 --score
  --efficiency --usability --md`

---

## 3. 已实装的 fail-closed 门禁（六处，E1 已补齐；E2 已于 2026-10-04 取消）

下列各处的口径同款：**开关 + 报告强制披露 + 开启即阻断**。
缺省全部关闭，所以离线自检照常 `exit 0`（不把既有冒烟打红）；要当放行条件用时
显式打开开关，让「未跑/未判」变成可执行阻断而不是注释里的一句话。

> **E2 例外（2026-10-04 裁定，拆法 A）**：`--require-human-review` 已从 CLI 与
> `run()` 签名删除，签字一族降级为**纯披露**。理由：17 份金标准全部由 `gen_gold.py`
> 自签，这道闸门从未放行过任何一个 case —— 启用即整批恒 FAIL，产出「没通过」而非
> 证据。披露字段一个未删（`review_provenance` / `sidecar_signed` /
> `human_review_complete` / 新增 `review_disclosure` 逐 case 点名）。
> 方案真值 `docs/eval-E2-groundtruth.md` §4.3.0。

| 实验 | 开关 | 触发条件 | 阻断项 | 双向自证测试 |
|------|------|----------|--------|------------|
| **E1** | `--require-threshold` | **逐维**低于 §6.7 通过线（样本 n<5 的维除外） | `below_dimension_threshold` | `test_e1.py::TestDimensionThresholdGate`（6 个） |
| **E1** | `--require-threshold` | **逐维**低于 §6.7 通过线（样本 n<5 的维除外） | `below_dimension_threshold` | `test_e1.py::TestDimensionThresholdGate`（6 个） |
| ~~E2~~ | ~~`--require-human-review`~~ | ~~金标准非人工签字~~ | ~~`gold_not_human_signed`~~ | **已取消，改为披露**（`review_disclosure`） |
| E3 | `--require-coverage` | 有题未采集回答 | `answers_missing` | `test_e3.py::TestCoverageGate`（5 个） |
| E4 | `--require-execution` | 本层未真正执行用例 | `tier_p_not_executed` | `test_e4.py::TestExecutionGate`（5 个） |
| E5 | `--require-live` | 跑批模式是 scripted 替身 | `scripted_not_live` | `test_e5.py::TestLiveGate`（3 个） |
| E6 | （默认行为修正） | R1/R2/R3 未接模型 | 退出码非 0 | `test_e6_runner.py`（4 个） |
| E6 | `--require-full-coverage` | R0 有未覆盖任务 | `tasks_uncovered` | 同上 |

每组测试都**双向**：既证「该拦的拦住」，也证「不该拦的放行」。只测前者的话，
一个「永远返回非 0」的退化实现也能骗过整组断言。合计 **33 个**
（E1 6 / E2 10 / E3 5 / E4 5 / E5 3 / E6 4）。

**闸门分布**：实装 7 处，覆盖 **E1–E6 全部六个实验**（E1/E2/E3/E4/E5 各一，E6 两处）。
E6 那处「默认行为修正」可用 `--allow-adapter-required` 显式放行（那是旁路，不是闸门）。

> **E1 补闸门前后的差别（2026-10-03）**：此前 E1 是六个实验里唯一没有闸门的 ——
> §6.7 定义了六条逐维通过线，但 `score_run` 只按加权总分 ≥0.90 判 `pass`，
> 逐维门槛**没有任何代码执行**。实测反例：11 题错 1 题（`convert=0.909`）时加权分仍有
> 0.9985、`pass=True`，而 §6.7 要求 `convert=1.00` —— 一个坐标/单位/波段转换出错的
> 批次可以「通过」的身份出报告。`--require-threshold` 已补上这条。

### 3.1 E3 —— 零回答不得判实验通过

- 文件：`evals/semantics/runner.py`
- 原状：`return 0 if summary["metascore"] >= 1.0 else 1`，而 `metascore` 只来自
  4 份反证夹具。`n_answered = 0` 时照样 `exit 0`。
- 现状：加 `--require-coverage`。开启时把未采集的题号逐条写进
  `summary["answers_missing"]`（37 条全缺也逐条列，不写「未采集」这种状态描述），
  退出码 1。报告新增 `answers_missing` / `coverage_ok` / `coverage_required`。
- 报告侧：`report.py` 的 `_coverage_line()` 抬头同时打出覆盖度与闸门开关状态。

### 3.2 E4 —— Tier P 未跑批不得计 pass

- 文件：`evals/robustness/runner.py`
- 原状：`run_p_precheck()` 只查标注字段齐不齐，齐了就记 `pass: True`。
- 现状：预检结果自报 `evaluated: False` 与 `n_pass: None`（「没跑」与「跑了得零分」
  是两回事）。加 `--require-execution`，开启时对 `evaluated is False` 的层记
  `tier_p_not_executed` 并把该层 `pass` 打成 `False`。**W 层真跑过，不被连坐**
  （有专门测试断这一点）。
- 报告侧：`render_markdown()` 的披露条件从「缺 `n_pass` 键」改成读 `evaluated`
  ——`n_pass` 现在恒存在（值为 `None`），沿用旧判据会让披露行静默失效。

> **2026-10-11：CI 接线已完成**（此前是「判据有、make 不传开关」，与 E1 逐维门禁当年的洞同型）。
> `Makefile` 的 `eval-e4` 现在默认带 `--require-execution`：
> ```bash
> make eval-e4                                             # 无答卷 → 阻断 (exit 1, tier_p_not_executed)
> make eval-e4 E4_ANSWERS=temp/robustness/answers/r1       # 给答卷 → 真判话术层, 门禁放行
> make eval-e4 E4_SKIP_GATE=1                              # 临时放行 (不带 --require-execution)
> make check-e4-disposal                                   # 处置口径越界复检 (越界即 exit 1)
> ```
> **阻断是预期行为，不是故障**：不给答卷时 Tier P 恒 `evaluated=False`，按铁律 5（禁 fail-open）
> 必须红。已验证：无答卷 → `P.blockers = ['tier_p_not_executed']`；
> 给 r1 答卷 → `P.blockers` 为 22 条真实阻断项且**不含**该码（不误伤）。
> ⚠️ 连带影响：`make evals-all` 在未给 `E4_ANSWERS` / `E4_SKIP_GATE` 时会因 E4 阻断而中断。

### 3.3 E5 —— scripted 替身不得当真模型结果

- 文件：`evals/ablation/runner.py`
- 原状：`--scripted` 是**缺省模式**且判 `pass: true`。
- 现状：加 `--require-live`，开启时记 `scripted_not_live` 并把 `pass` 打成 `False`。
  跑批模式 `mode` 无条件写进报告，并与 `pass` **并列回显到 stdout** ——
  「这批是替身还是真模型」是最不能只埋进 `--json` 的信息。

### 3.4 E6 —— 未接模型不得 exit 0（最直接的一处）

- 文件：`evals/repro/run_e6.py`
- 原状：`if args.lane in ("R1","R2","R3"): print(adapter_required); return 0`
  —— **要一条根本没跑的 lane 却拿到退出码 0**，CI 里「E6 通过」与「E6 压根没跑」
  长得一模一样。这是六处里唯一的 fail-open 退出门禁路径。
- 现状：默认返回**非 0**，并加 `executed: false` 记账。确属「仅探接口」语义时用
  `--allow-adapter-required` 显式放行，让意图留在命令行里而不是藏在默认值里。
  另加 `--require-full-coverage`：R0 覆盖 18/32，开启时未覆盖任务记
  `tasks_uncovered` 并把阻断项随分数同出。

### 复验

```bash
# 缺省: 六个 runner 仍全 0 (离线自检不被新门禁打红)
python evals/semantics/runner.py;                          echo $?   # 0
python evals/robustness/runner.py --tier all;              echo $?   # 0
# 注: 2026-10-11 起 `make eval-e4` 已**默认带** --require-execution, 故 make 路径不再是 0,
#     见下「E4 门禁已接线」小节。上面这行是裸 runner 的缺省行为, 仅作口径对照。
python evals/ablation/runner.py --scripted;                echo $?   # 0
python evals/repro/run_e6.py --lane R0 --repeat 2;         echo $?   # 0

# 开门禁: 各自转 1
python evals/semantics/runner.py --require-coverage;                     echo $?   # 1
python evals/robustness/runner.py --tier all --require-execution;        echo $?   # 1
python evals/ablation/runner.py --systems B3 --scripted --require-live;  echo $?   # 1
python evals/repro/run_e6.py --lane R1;                                  echo $?   # 1
python evals/repro/run_e6.py --lane R0 --repeat 2 --require-full-coverage; echo $? # 1
```

---

## 4. 复验命令

```bash
# 六个实验跑批（当前应全 0）
python evals/nl2tool/gen_golden.py
python evals/nl2tool/runner.py --traces evals/nl2tool/traces/golden --json temp/nl2tool/report.json --md-out evals/nl2tool/REPORT.md
python evals/groundtruth/run_e2.py --md --repeat 3 --json temp/e2_report.json
python evals/semantics/runner.py --json temp/semantics/report.json --md-out evals/semantics/REPORT.md
python evals/robustness/runner.py --tier all --md
python evals/ablation/runner.py --scripted --md evals/ablation/REPORT.md --json temp/ablation/report.json
python evals/repro/run_e6.py --lane R0 --repeat 5 --selftest

# E2 跑批 (签字闸门已于 2026-10-04 取消, 恒 exit 0; 签字状态看 human_review_complete)
python evals/groundtruth/run_e2.py --repeat 3 --json temp/e2_report.json; echo "exit=$?"

# 单测 + 硬门禁
python -m pytest test/ evals/ -q --tb=short
ruff check src/ test/ evals/ rag/ ops/ examples/
python ops/verify_tree_integrity.py
python ops/astro_best_cli.py doctor
```

---

## 5. 统计诚实声明（E1 §7 / E5 §8 / E6 §5.5 同款口径）

- R0 路 N=5，Wilson 95% 区间是 `[0.963, 1.000]` 而非 `[1, 1]` ——
  **只报点估计 + 区间，不做「达标」强断言**。
- McNemar 检验效力约 0.6–0.7；未达 3 次重复前不得下显著性结论（E5 §11 阻断项 7）。
- token 缺失一律记 `null`，**禁止估算填数**（E5 §6.7）。
- 反证夹具 metascore 必须 = 1.00；低于 1.00 说明判定器本身失效，该轮分数不作数。
