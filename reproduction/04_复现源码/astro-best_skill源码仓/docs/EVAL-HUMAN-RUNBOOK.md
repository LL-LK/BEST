## 0.0 总览：六个实验合起来要证伪什么

> **本节回答一个所有方案都没正面回答的问题**：E1–E6 各自都说「我缺什么」，
> 但没有一处说「六个做完之后，我们知道了什么」。缺这一层，
> 就会出现「六处闸门全 0」却写不出一句结论的局面 —— 这正是本手册存在的理由。

**一句话总命题**：**这个 agent 在天文数据检索任务上是否可信？** 「可信」拆成六个可分别证伪的命题：

| 实验 | 它证伪/证实的是 | 失败意味着什么 |
|------|----------------|----------------|
| **E1** | 自然语言 → 工具决策**选对工具、传对参数** | agent 听不懂人话，或听懂了却调错工具 |
| **E2** | 取回来的数**和人工审核过的标准答案一模一样** | 数据链路有静默错值（S1），而 S1 是最危险的一类 |
| **E3** | 解释**语义保真、不编造** | 话说得通顺但科学上是错的 —— 用户看不出区别 |
| **E4** | 出错/被诱导时**站得住** | 故障时把失败包装成成功，或越界乱来 |
| **E5** | **比基线好在哪**，每个组件值多少分 | 分数不可归因，改动无法决策 |
| **E6** | 结果**可复现**，代价与可用性可接受 | 分数不可信，横向对比无意义 |

**分层完成度**（这张表比「六处闸门全 0」更能回答「还差多远」）：

| 层 | 含义 | 判据 | 现状 |
|----|------|------|------|
| **L0 管线自证** | 判定器本身可信（坏样本判 FAIL，好样本判 PASS） | 六个 runner `exit 0` + 反证夹具 metascore=1.0 | ✅ **已达到** |
| **L1 金标准可信** | 正确答案有人签过字 | E2 报告 `human_review_complete` 转 true | ⚠️ **不只是缺签字**（见右）；签字闸门已于 2026-10-04 取消，本层改由披露追踪 |
> ⚠️ **L1 的实际缺口比「差一个人」大（2026-10-03 双路核验后修正）**：
> E2 17 份金标准已做**双路独立核验**（人工路径独立 haversine 重算 +
> skill 路径 VizieR 真实 PS1 查询），结论有两面：
> - ✅ **作为一致性实验是站得住的**：行集/排序/截断三元组/四态裁决全部自洽；
> - 🔴 **但素材 16/17 是合成的**，唯一那份真实快照还掺了 1 颗人造星。
> **所以「签了字」不等于「金标准可信」** —— 给合成素材盖章只会把
> 「结论不可外推」这件事藏进「人工已审」四个字。
> **正确顺序：先做 E2 §4.6.6 的 P0 记账改造（补 `material_class`）→
> 补 live 素材 → 最后签字。** 详见 `docs/eval-E2-groundtruth.md` §4.6。

| **L2 决策可信** | 真实模型的工具决策达标 | E1 `--require-threshold` 转 0 且 `trace_sources` 出现 `live-run` | ❌ 差「豁免 + API + adapter」 |
| **L3 语义可信** | 语义判定层有人评过 | E3 `--require-coverage` 转 0 + 按档位达标 | ❌ 差跑批（`n_answered=0`） |
| **L4 鲁棒可信** | 话术层处置正确 | E4 `--require-execution` 转 0 | ❌ 差跑批（Tier P 未跑） |
| **L5 归因可信** | 相对基线/消融的差异有统计支撑 | E5 `--require-live` 转 0 + T4/T5 出表 | ❌ 差真模型 adapter |
| **L6 复现可信** | 跨次/跨日稳定 | E6 R0/R1/R3 三路 | ⚠️ R0 已实跑（18/32），R1/R3 差跑批 |

> **L0 已满、L1 差一个人、L2–L6 全差同一件事**。所以资源分配的答案很清楚：
> **先把 E2 签字做完**（成本最低、且完全不依赖铁律 7 豁免），
> 再一次性解决「豁免 + API 出口 + `LLMAdapter`」这三件，五个实验一起解锁。
> **不要在 E2 上等豁免** —— E2 不需要它。

---

## 0.1 为什么现在不需要人（2026-10-03 全面去人工化）

> **本手册已从「人工评测作业手册」改写为「执行说明」。**
> 原稿假设 R1/R2/R3 三名评阅人 + 一名金标准签字人，但**方案从未定义这些人从哪来**；
> 而双评要 216 次评分、κ ≥ 0.60 是硬门禁，**κ 只能由两个真正独立的人算出**。
> 一人评自己两次没有意义 —— 于是原 §3–§5 是三份「动作描述精确、执行主体不存在」的文件。
> **这就是「人工根本不知道要做什么」的真正来源。**

**现在的人工量：0。** 三项依据（都可复现、可核查）：

| 原步骤 | 原成本 | 现在的替代 | 依据 |
|--------|--------|-----------|------|
| E2 签字 17 份 | ≈1.5 h | **七项自动化独立核验**（E2 §4.3.1） | 几何/行集/排序/分页/截断/状态机全是确定性函数，独立重算比抽样更全 |
| E2「A 类 3 份非人不可」 | 20 min | **判据 5：程序镜像** | 实测 `guards.validate_search_radius(0)` 抛 `ValueError: must be positive, got 0` —— 「半径 0 该记什么」是 guards 行为的镜像，不是科学语义判断 |
| E3 双评 + 仲裁 | ≈216 次 | **LLM-only + 反证夹具 metascore=1.00** | κ 从未点亮过（`n_answered=0`）；反证夹具直接检验「坏回答有没有被判好」，且不依赖评阅人是谁 |
| E4 C/D 级盲评 | 12 次 + 仲裁 | **LLM 依 §3 四级处置决策表判定** | 判据可判性远高于 E3，且 E4 已有 8 个反证夹具当自证门禁 |
| E5 L2 抽检 20% | 6 题 × 2 | **取消** | 本就是代理指标；跨系统横向比较用即可 |

**代价（必须披露，不得隐藏）**：

- **E2** 不再对「这个查询设计上该不该有结果」做人工背书；
- **E3** 不再有任何人类评阅，语义保真结论**降为「LLM 判定的一致性」而非「专家判定」**；
- **E4** 的 C/D 级可能出现 LLM 判「澄清得够不够」偏宽松 →
  报告必须并列给出 **C/D 与 L0 程序判定不一致的题号清单**。

三条代价的共同报告口径（**每份报告抬头都必须有**）：

```
review_mode: llm-only (no human reviewer, no kappa)
verification: automated-independent (no human design review)
```

> **保留的人工动作只有两类，都不是「评分」**：
> ① **拍板**（铁律 7 豁免、入库时点）—— 这是决策，不是执行；
> ② **发起跑批 / 触发 R2** —— 需要人点一下命令，且无法自动（涉及外部 API 与跨日等待）。
> 其余全部脚本。

---

## 0.2 通用门禁 `evals/eval_runner.py` 的判分口径（**代码为准，2026-10-05 补登**）

E1–E6 各有各的闸门，但**唯一给整个评测层出 `SUCCESS/FAILED` 与退出码的**是
`evals/eval_runner.py`，也是 `CLAUDE.md` 门禁命令直接跑的那一条。
六份实验文档都只说"我这套分数**不并入** `scoring-rubric.yaml` 的五维加权"，
**却没有任何一处说明那把锁的判据是什么** —— 于是口径只存在于代码里。
本节把它补上（逐条给出 `文件:行`，改代码时本节要跟着改）。

### 0.2.1 判据原文

| 判据 | 位置 | 原文 |
|------|------|------|
| **放行判定** | `evals/eval_runner.py:485` | `"passed": overall_score >= pass_threshold and not any(blocking.values())` |
| **六项阻断** | `:470-480` | `scenarios` / `cases` / `audit` / `behavior_not_measured` / `docstring_not_measured` / `audit_not_measured` |
| 权重和校验 | `:399-403` | 和 ≠ 1.0 即 `passed: False`（不许凑一个分） |
| 配置自洽 | `:459-463` | `pass_score` 必须 > `WARN_LINE`，否则当场判败 |
| 维度状态（**只报告**） | `:449` | `status = "PASS" if s >= 0.95 else ("WARN" if s >= WARN_LINE else "FAIL")` |
| 审计总判定 | `:306-307` | `n_failed == 0 and not any(CRITICAL)` |

### 0.2.2 ★ 纠正一个流传的说法：「单维 FAIL 否决」**不存在**

`status` 在 `:449` 算出来，但 `:485` 的表达式**一个 `status` 都不读** ——
它只进 `dim_reports` 供人读。**规则是「六项 `blocking` 任一为真即否决」，
既不是「单维否决」，也不是「综合分达标」。**

实测（`temp/DETECT-probe-k7.py`，直接调 `evaluate_rubric` 喂合成汇总，不落盘）：

| 场景 | `correctness` | `status` | `overall` | `passed` | `blocking` |
|------|------|------|------|------|------|
| 基线（1 条非 INFO finding） | 0.90 | `WARN` | 0.9700 | **True** | `[]` |
| 2 条非 INFO finding | 0.80 | **`FAIL`** | 0.9400 | **True** | `[]` |
| 3 条非 INFO finding | 0.70 | **`FAIL`** | 0.9100 | **True** | `[]` |
| 4 条非 INFO finding | 0.60 | `FAIL` | 0.8800 | False | `[]` |
| 2 条 finding **+ 审计器判败** | 0.80 | `FAIL` | 0.9400 | **False** | `['audit']` |

**`correctness` 掉到 0.70（远低于 0.85 WARN 线、状态明写 `FAIL`）时整体仍 `passed=True`。**
反向印证：真实跑批基线 `correctness=0.90 / status=WARN` 也一样放行（exit 0）。

### 0.2.3 ★ 元信息能直接决定整套评测的判定

上一循环的实测：某个**零断言测试**（`test_gate_scan_coverage.py::test_gate_defines_no_own_scan_dir_tuple`，
MAJOR）把 `correctness` 从 0.9 压到 0.8、`overall` 到 **0.9400**，而整套评测 **FAILED**。

按 0.2.2 的表，`overall 0.9400` 本身**是放行的**（0.94 > 0.9），
所以那次 FAILED **只能来自 `blocking`**，链条是：

```
零断言测试 → 审计器报 MAJOR 且自评 passed=False（:284）
          → audit_summary["passed"] 为假（:306-307）
          → blocking["audit"] 为真（:474）
          → 整体 FAILED
```

**即「有没有一个测试是零断言」这种元信息，决定整套评测的通过与否，
而它与 `correctness` 的分数无关。** 写题、写测试的人必须知道这条：
**一个零断言测试能单独把整套 `eval_runner` 拉红。**

### 0.2.4 ★ `pass_score: 0.9` 的真实语义不是「质量分达到 0.9」

在 `blocking` 全假（`rate == 1.0` 且审计通过）的前提下，
`correctness = 1.0 × (1 − 0.1n)`（n = 非 INFO findings，`:409` / `:422-426`），其余四维满分，于是

```
overall = 1.00 − 0.03n
```

| n（非 INFO findings） | 0 | 1 | 2 | 3 | 4 |
|------|---|---|---|---|---|
| `overall` | 1.0000 | 0.9700 | 0.9400 | 0.9100 | 0.8800 |
| `passed` | True | True | True | True | **False** |

**所以 0.9 这条线的真实语义是「非 INFO 审计 findings 不得超过 3 条」**，
翻转窗口极窄（n=3 → n=4）。而 `blocking` 要求 `scenarios` / `cases` 的 `rate`
都等于 1.0（`:472-473`）—— **任一行为用例失败早就 FAILED，加权线不再参与。**
两头挤压的结果：加权质量分的分辨力窗口只有 findings 数这一个维度，
**别把它读成"整体质量达到 0.9"。**

### 0.2.5 ★ WARN 线 0.85 是**死配置**，复核时别去调它

`WARN_LINE = 0.85` 硬编码在 `:83`；`evaluate_rubric` 只读 `rubric.get("pass_score")`（`:459`），
**从不读** `evals/scoring-rubric.yaml:22` 的 `warn_line`。
把 YAML 里那个值改成 0.99 或直接删掉，**门禁行为零变化** ——
一个看起来可调的参数实际不可调，复核者改它只会得到"改了没用"的假象。
（另：0.85 只影响人读的报告文字 `:617`，不影响任何放行决策。）

### 0.2.6 ★ `make evals-all` 里五处实验闸门**一个都没开**

`Makefile:61-78` 六个目标逐字核对：`eval-e1` 无 `--require-threshold`、
`eval-e3` 无 `--require-coverage`、`eval-e4` 无 `--require-execution`、
`eval-e5` 无 `--require-live`、`eval-e6` 无 `--require-full-coverage`。
**`make evals-all` 是冒烟跑批，不是放行跑批**；放行必须按 §7 逐条显式开闸门。
（`eval-e1` 还把 `--traces` 硬编码成 `golden`，真实模型轨迹进不了 make ——
详见 `docs/eval-E1-nl2tool.md` §6.8。）

### 0.2.7 恒真化绕过：**已堵死**，但残留"WARN 静默放行"

F7 的 A6-03 反作弊测试在
`test/unit/meta/test_eval_runner_dimensions.py::TestScoringCannotBeRigged`（6 条）。
**本轮重跑突变实验**（把 `evals/eval_runner.py:224` 的 `"passed": ok` 改成
`"passed": True`，即 A6 同款的无条件恒真化叠加）：

| 组 | 实测结果 |
|----|------|
| 干净副本（对照） | `24 passed`，**exit 0** |
| 注入恒真化 | **`2 failed, 22 passed`，exit 1** —— `test_failing_probe_makes_final_verdict_red` + `test_exception_raising_probe_counts_as_failure` 爆红 |
| `python evals/eval_runner.py` 本体 | `0.9700 / SUCCESS`，**exit 0**（`correctness [WARN]`） |

**结论：A6 那条恒真化路径在当前 HEAD 已被判据级反作弊测试堵死**
（断言读的是 runner **真跑**出来的判定，不是拿判定逻辑复述一遍）。

**但残留一条不同形态的宽松**：维度 `WARN` 对机读消费方**不可见** ——
`--json` 的 `dimensions[].status` 带 `WARN`，却**没有任何汇总级布尔量**
表达"存在 WARN 维"，`passed=true` + exit 0 与全绿**完全同形**。
人读路径看得到（`:612-614` 逐维打 `[WARN]`），机读路径看不到。
**已知不合格的维度会安静地放行，且退出码与全绿不可区分。**

---

## 1. 唯一的两个人工决策点（卡住 5/6 的实验）

### 1.1 铁律 7 豁免决定

铁律 7（`CLAUDE.md`）：「离线纪律: 评测一律回放; **不接真实模型/不打真实站点**」。
E1/E3/E4/E5/E6 的解锁条件全部与之冲突。

- **要做的决定**：是否豁免铁律 7，允许接入真实模型跑批。
- **若豁免**：记录豁免范围（哪几个实验、哪个 `model_id`、温度、日期、commit），
  写进 `CHANGELOG.md`，并在报告头部声明。
- **若不豁免**：五个实验永久停在「管线自证」，L2–L6 全部无法升级。

> **⚠️ 豁免不是一次勾选，是三件有先后的事**：

| # | 事项 | 性质 | 现状 |
|---|------|------|------|
| 1 | 是否豁免铁律 7 | **规则问题**，你拍板 | 未决 |
| 2 | 取得可程序调用的模型出口 | **外部依赖** | **无**：`config.yaml:7` 的 `apiKey` 是字面量 `sk-xxx` 占位符；环境变量 0 个 LLM key |
| 3 | 实现 `LLMAdapter` 的真模型子类 | **工程活，约 1 天** | **无**：`evals/ablation/harness/adapters.py:139` 的 `ScriptedLLM` 是唯一实现 |

> **第 3 项不是配置项，是待写代码。** ⚠️ 特别更正
> `docs/EVAL-UNLOCK-CHECKLIST.md` 此前那句「去掉 `--scripted` 即接真模型」——
> `evals/ablation/runner.py:180-186` 无条件把 `mode` 写成 `"scripted"`，**没有 live 分支**。
> 照那句话操作会得到「看似接了模型、实则仍是替身」的静默结果。
>
> **所以：E1/E3/E4/E5/E6 卡在跑批，不在评阅** —— 现在评阅已全自动，
> 这五项的进度**完全取决于上面三件事**。

### 1.2 铁律 8 入库

- **现状**：工作区有未提交改动（`code_fingerprint` 以 git HEAD 为基线，不入库就一直红）。
- **要做的决定**：入库时点与批次。

---

## 2. E2 金标准核验（零人工）

**E2 是唯一不依赖真模型、此刻就能推进的实验**，所以它排在最前。

### 2.1 当前真实状态

| 项 | 状态 |
|----|------|
| 判定管线 | ✅ 自证通过（行集/排序/截断三元组/四态裁决独立重算全对） |
| 金标准审核 | ❌ **不适用** —— 人工已取消，改自动化核验 |
| 素材真实性 | 🔴 **16/17 为合成**，唯一真实快照掺了 1 颗人造星 |
| 独立核验器 | ❌ **未实现**（七项判据已在核验中跑通，需固化成常驻门禁） |

> **一句话**：E2 现在证明的是「被测代码与独立 oracle 在同一批素材上对得上」，
> **不是**「对真实天文数据的取数正确」。详见 `docs/eval-E2-groundtruth.md` §4.6。

### 2.2 执行（三步，全脚本）

```bash
# 1) 重新生成金标准（消除 generator_drift）
python evals/groundtruth/gold/gen_gold.py

# 2) 七项自动化独立核验 —— ⚠️ 尚未实现，需先批准（铁律 4）
python evals/groundtruth/run_e2.py --repeat 3 --require-independent-verify

# 3) 期望：全表 PASS、退出码 0
```

> **步 2 的门禁还没建。** 在它建起来之前，E2 **只能声称「管线自证」**，
> 不能声称「金标准正确」—— 这与 §4.6.5 的口径一致。
> 七项判据见 E2 §4.3.1；其中第 7 项（独立 oracle）**已实装**
> （`gold/guard_no_src_imports.py`），第 1–6 项待固化。

### 2.3 原审计工具（可选，不参与放行）

`evals/groundtruth/review/`（`gen_review_sheet.py` / `backfill_reviews.py` /
`HUMAN_REVIEW_SHEET.csv`）**保留在仓内**，想留人工审计时仍可手动跑，但
**不参与放行判定**。
`--require-human-review` 闸门已于 **2026-10-04 取消**（拆法 A）：17 份金标准全为
生成器自签，该闸门从未放行过任何一个 case，启用即整批恒 FAIL —— 产出「没通过」
而非证据。签字状态改由报告**如实披露**（`review_provenance` /
`sidecar_signed` / `human_review_complete` / `review_disclosure` 逐 case 点名），
案值 `docs/eval-E2-groundtruth.md` §4.3.0。
理由：它们绑的是「谁来签」，而真正要防的东西（几何/行集/截断/状态机）
**与签字人是谁无关**，全部可自动检出。
留一个不参与放行的开关，只会让报告上多一个 `human_review_complete=false` 的红字噪声。

---

## 3. E3 / E4 / E5：全 LLM 判定（零人工）

| 实验 | 判定方式 | 门禁 | 人工 |
|------|---------|------|------|
| **E3** | LLM 依 `rubric.yaml` 判 37 题 | `--require-coverage` + 反证夹具 metascore=1.00 | 0 |
| **E4** | LLM 依 §3 四级处置决策表判 Tier P | `--require-execution` + 8 个反证夹具 | 0 |
| **E5** | 机器预筛（`prescreen.py`）+ L2 归 LLM | `--require-live` + T4/T5 出表 | 0 |

**E3 的校准流程（替代原 κ 门禁）**：

```bash
# 8 题 pilot → 3 份反证夹具必须全判对（metascore=1.00）
# 任一份判过 → 判定器或 rubric 有歧义 → 修完重跑，不调权重、不换评阅人
python evals/semantics/runner.py --answers <回答.json> --require-coverage --md
```

**E3 已取消的项**（不得再出现在任何报告里）：Cohen's κ / Gwet's AC1 /
Krippendorff's α / ICC / 仲裁。**在没有人类评阅的情况下引用这些统计是伪造证据**
（E3 §12 阻断项 10）。

**E4 必须并列披露**：C/D 两级与 L0 程序判定**不一致的题号清单** ——
让读者自己看分歧落在哪，而不是只看到一个聚合通过率。

---

## 4. E1 / E6：人只做「发起」

这两个不需要人评分，但需要人**发起**（涉及外部 API 与跨日等待，无法自动）。

### 4.1 E1

- **人要做**：决定 `model_id`、提供 3 次重复跑批的执行、把产物放进
  `evals/nl2tool/traces/`（`source: live-run`）。
- **注意**：`traces/golden/` 的 26 条合成轨迹**不要删** —— 它们是判定器管线自证基线。
- **验收**：`--require-threshold` 转 0，且 `trace_sources` 出现 `live-run`。

### 4.2 E6

- **人要做**：接 R1 / R3。
- **R2（D+7）不阻塞主结论**（E6 §14.1）—— `R2−R1` 的漂移定量已移交 E7，
  **E6 没有理由为 E7 的需求等满 7 天**。R2 仍是延后项，未跑时报告写
  「未测（D+7 未到）」，**不能留空也不能填 0**。
- **人工量**：R2 那 1 次手动触发（约 5 分钟）。
- **统计诚实**：N=5 时 Wilson 区间是 `[0.963, 1.000]`，**不是** `[1, 1]`。

---

## 5. 执行顺序

```
阶段零  ① 铁律 7 豁免决定（规则，你拍板）        ← 唯一的阻塞点
        ② 取得模型 API 出口（外部依赖）
        ③ 实现 LLMAdapter 真模型子类（工程）
   │    ④ 铁律 8 入库
   ├─► E2 核验器落地 + 补 live 素材               ← 不依赖 ①②③
   │
阶段一  模型跑批（E1 轨迹 / E3 runs / E4 TierP / E5 / E6 R1R3）
   │
阶段二  E3 8 题 pilot → 反证夹具全对才继续
   │
阶段三  E3 全量 LLM 判分 37 题 + E4 TierP 全量 LLM 判分
   │
阶段四  E5 真模型跑批 + T4/T5 出表
   │
主线收口  E6 的 R0/R1/R3 三路 → E6 出结论        ← R2 不在此处
   │
延后项  E6 R2（D+7，不阻塞上述任何结论）
```

**E2 不在阶段零之后** —— 它不依赖铁律 7 豁免，可与阶段零**并行**。

---

## 6. 常见坑

| 坑 | 后果 | 怎么避 |
|---|---|---|
| 报告里引用 κ / AC1 / α / ICC | 无人类评阅却报一致性 = 伪造证据 | 三项统计全部取消；抬头只写 `review_mode: llm-only` |
| 把 E2 的「管线自证」读成「金标准可信」 | 16/17 是合成素材，结论不可外推 | 引用 E2 分数时必须同时给 `material_class` |
| 给合成素材盖「人工已审」的章 | 把「结论不可外推」藏进四个字 | 先补 `material_class` 记账 + live 素材，再谈收口 |
| 去掉 `--scripted` 就以为接了真模型 | 静默替身，比直接报错更危险 | `runner.py:180-186` 无条件写 `mode=scripted`，**没有 live 分支** |
| 拿 L0 预筛当 L2 结论 | 语义类指标被高估 | E5 §6.4 已声明是代理指标 |
| N=5 就说「完全一致」 | Wilson 区间是 `[0.963, 1.000]` 而非 `[1,1]` | 报点估计 + 区间，不做强断言 |
| 只做单盲评不算一致性 | κ 无从算起，等于没测 | κ 已取消；用反证夹具 metascore 代替 |

---

## 7. 一句话验收标准

**六个实验全部解锁 = 七处闸门全部转为 0**（闸门清单：E1 一处、E2 一处、E3 一处、
E4 一处、E5 一处、**E6 两处** —— 与 `docs/eval-E1-nl2tool.md` §6.8 的「闸门分布」一致）：

```bash
python evals/nl2tool/runner.py --traces <真实跑批目录> --require-threshold; echo $?  # E1 期望 0
python evals/groundtruth/run_e2.py --repeat 3 --require-independent-verify; echo $?  # E2 期望 0
python evals/semantics/runner.py --answers a.json --require-coverage; echo $?          # E3 期望 0
python evals/robustness/runner.py --tier all --require-execution; echo $?             # E4 期望 0
python evals/ablation/runner.py --systems all --repeat 3 --require-live; echo $?       # E5 期望 0
python evals/repro/run_e6.py --lane R0 --repeat 5 --require-full-coverage; echo $?    # E6 期望 0
```

> **E2 那一行目前必然非 0** —— `--require-independent-verify` 尚未实现（§2.2）。
> 这是真实状态，不是待修的 bug。

> ⚠️ **「七处」与上面 6 行命令不是 1:1**（别拿这个清单去数闸门）：
> ① E6 占**两处** —— 上面只列了带开关的 `--require-full-coverage`，
> 另一处是「R1/R2/R3 未接模型即退出码非 0」的**缺省行为修正**，没有开关可传；
> ② E2 那一行用的 `--require-independent-verify`（§4.3.1 的七项核验闸门）
> **与已取消的 `--require-human-review` 不是同一个开关** —— 后者已于 2026-10-04
> 改为只披露不阻断（§2.3），**它永远不会"转为 0"，也不该被数进待解锁清单**。
>
> 另注：`docs/EVAL-UNLOCK-CHECKLIST.md` 的闸门表把 **E1 的 `--require-threshold`
> 那行逐字重复了两遍**（`:142` 与 `:143` 完全相同），按那张表数行会得到 7 行 ——
> 那个"多出来的一处"是表格笔误，不是第 7 道闸门。该文件不在本轮改动范围内。
