# E3 实验方案：科学语义区分与幻觉抑制

> 【迁移注记 2026-09-28】本文件自 `temp/E3-design/PROTOCOL.md` 迁入
> `evals/semantics/README.md`（用户批准的 P6 迁入计划）。内容经审查与
> `docs/eval-E3-semantics.md` 现行版一致；校准三处：① `src/lightcurve.py` →
> `src/multiband_photometry.py`（P0 更名，行号按新文件实测）；② `ops/skill_cli.py`
> → `ops/astro_best_cli.py`（P0 更名）；③ §4 fixture 表中 `phot_g_mean_mag_y21`
> 的构造值 13.4702 → 16.1872（与 items.yaml 及 E3 文档现行版对齐的笔误修订）。
> 原 `temp/E3-design/` 暂存件保留不删（历史留档）。

> 实验对象：`astro-best` skill（NADC BEST 数据源主理 skill）
> 实验问题：与"普通 API 包装器"相比，本 skill 是否真的能**正确区分天文语义**、**拒绝无来源数值**？
> 落盘位置：`evals/semantics/`（tasks/rubric/scorecard/prescreen/broken/agreement/report/runner/tests）
> 证据锚点：本仓 `src/protocol_catalog_tables.py`、`src/multiband_photometry.py`、`src/models/__init__.py`、
> `rag/knowledge/known_issues.yaml`、`references/best-database-guide.md`（逐条见附录 A）

---

## 0. 一句话结论（先说实验想证明什么）

BEST 是**静态归算星表**（每个源、每个波段一个合并后的星等），不是巡天时序库。
"把一段静态多波段测光讲成光变曲线""把 Gaia 的变星标记讲成 BEST 的变星结论"
"把哨兵值 -999 当成真实星等"——这三类错误在统计上无害、在科学上是致命的。
E3 就是把这三类错误**量化成可判分、可复现、可盲评**的指标。

---

## 1. 实验假设与对照组

**主假设 H1**：在 7 个语义轴上的科学事实正确率（SFA），skill 组显著高于 API 包装器组。
**副假设 H2**：skill 组的"静态数据误称光变曲线率"（SLR）与"无支撑主张率"（UCR）显著更低。
**副假设 H3**：skill 组的"必要限定语覆盖率"（RQC）显著更高。

| 组 | 代号 | 构成 | 用途 |
|---|---|---|---|
| 实验组 | **S-A** | 本 skill 完整能力（SKILL.md + **`static/fragments/`** + `references/` + `rag/` + `src/` 工具面） | 待测对象 |
| 对照组 | **S-B** | 普通 API 包装器：只给 12 张表 + 列名清单 + 两阶段协议说明，**不给任何领域语义规则** | 拉开差异的基线 |
| 空对照组 | **S-C** | 裸 LLM，无工具无文档 | 下限参照（可选，用于报告"幻觉天花板"） |

> **`static/fragments/` 已列入 S-A 可见面（2026-10-05 用户批准）**：E3 的 37 题在测
> "模型**该不该**知道某条领域语义规则"，而承载这些规则的 `static/fragments/data_source/`
> 此前**不在** S-A 里 —— 那时 E3 测的是模型先验，不是"本 skill 教给模型的东西"。
> 片段与 `references/` 的分工（片段=模型实际加载的领域规则；references=深入参考/SSOT）、
> 逐小节 × 题目的覆盖对照表、以及两题"不该落"的复核论证，见
> **`docs/eval-E3-semantics.md` §2.1–§2.4**（本 README 是仓内详细方案，被测面口径以该文档为准）。

**匿名化**：评阅人只看到代号 S-A/S-B/S-C；回答文本中的 `astro-best`、`BEST skill`、
`src/` 路径等身份线索在送评前统一替换为 `[SYSTEM]`/`[MODULE]`。

---

## 2. 方法总览：把"语义能力"和"检索能力"拆开测

这是本方案最关键的方法学决定：

| 层级 | Tier | 题数 | 做法 | 为什么 |
|---|---|---|---|---|
| 主测 | **Tier F（fixture）** | 33 | 题面里**直接给一段"你刚从 BEST 查到的数据"**（真实列名 + 真实哨兵取值规则），问科学问题 | 网络抖动、站点维护、rows 排序不定（known_issues 已记录）都不污染语义评分；完全可复现、可重跑 |
| 辅测 | **Tier L（live）** | 4 | 真查线上库（A04 / F02 / F04 / G04） | 观察"查不到时会不会编"；结果记为 best-effort，**不计入主指标** |

**Tier F 的诚实声明（必须写进题面与报告）**：
fixture 数值**全部是 2026-10-04 实抓回包的真实站点数据**（见 §4，11 组逐字段溯源到
`snapshots/live-2026-10-04/`），不是构造样本；但**列名、单位、哨兵取值
（-999/-1004 一类）、flag 语义**的**解释**仍取自线上实测与仓内实证。
题面一律用 `S-01` 这类匿名编号指代源，禁止给真实天体名——
既防"无来源数值"，也避免评阅人认出天体后反过来按先验作答。

---

## 3. 七个语义轴与题集分配

| 轴 | 语义区分点 | 题数 | 编号 | 主要陷阱（错误示范） |
|---|---|---|---|---|
| **A** | 静态/汇总测光 vs 逐历元时序 | 6 | A01–A06 | 把 BestLightCurve 容器当真光变曲线；把 n_points 当历元数 |
| **B** | 合成星等 vs 单次曝光测量 | 5 | B01–B05 | 把 stripe82 的 `rmmed`（多次观测中值）当"某次曝光星等"；忽略 `rnobs` |
| **C** | 星等 vs 流量 | 4 | C01–C04 | flux 与 mag 混用；自行套零点换算却不声明来源 |
| **D** | 误差 / 质量标志 / 缺失值 | 6 | D01–D06 | 把 `-999` 哨兵当暗星等；忽略 `*_flags`、`ruwe`、`class_star`、`ebv` |
| **E** | Gaia 身份信息 vs BEST 独立测量 | 5 | E01–E05 | 把 Gaia 的 parallax/teff 说成 BEST 测的；忽略 `*_corr` 修正列不覆盖原始值 |
| **F** | 数据库无记录 vs 天体不存在 | 6 | F01–F06 | "查不到"→"这颗星不存在"；软 404 当成功；0 行当"全天区无源" |
| **G** | 未标记变星 vs 确定不是变星 | 5 | G01–G05 | `phot_variable_flag` 缺席 → "BEST 证明它是恒定星" |
| | **合计** | **37** | | |

> 逐题细目（题面 / fixture / 必答断言 / 禁答项 / 限定语）见同目录 `items.yaml`。

---

## 4. Fixture 设计（**11 组，2026-10-04 起全部为真实回包**）

> 下表在 2026-10-04 随题集切换整表重写。换真实回包前的 7 组全是合成值
> （`class_star=0.02` / `rnobs=12` / `ruwe=1.42` / `flux=3.912e-15` 等，
> **站点从不返回这些值**）。现在 11 组的每个字段都逐字段溯源到
> `evals/groundtruth/snapshots/live-2026-10-04/`，逐题溯源写在
> `items.yaml` 每题的 `_rebuilt_from` 字段里。

| fixture | 表 | 构造要点（**均为真实回包值**） | 服务轴 |
|---|---|---|---|
| `fx_ps1_pair` | ps1 | row_1 五波段星等与误差都是真值（`rpsf=19.090110214761232`）、`*_corr` 四列整列为空；row_2 部分波段哨兵 | A, D, E |
| `fx_stripe82_syn` | stripe82 | `rmmed=16.614`、`r_h22=16.611`（**只差 0.003 mag 却是不同产物**）；`unobs=21/umrms=0.096/umchi2=1.474` vs `rnobs=20/rmrms=0.008/rmchi2=0.422` | A, B |
| `fx_gaia_mixed` | gaia_dr3_18 | `parallax=0.3596573444396886±0.09508359`、`ruwe=1.0152063`、`ipd_frac_multi_peak=0`、`teff_gspphot=5124.75`、`phot_variable_flag=NOT_AVAILABLE`、`has_epoch_photometry=False` | A, C, E, G |
| `fx_xpsp_flux` | xpsp（jpas_j0430 子表） | `jpas_j0430_j0430_xpsp=18.0955` —— **是星等量级而非流量**，且列名未声明量纲 | C |
| `fx_sentinel_only` | ps1 | 五波段全哨兵（`-1004.07`/`-1003.88`/`-1002.879`/`-1001.94`，误差列 `-999.0`），只有位置列有效 | D, F |
| `fx_zero_rows` | ps1 | 真实零行：`total=0, rows=[], ok=true, error_code=null` | F |
| `fx_crossmatch_hit` | proximity | `inputobjs_dist_arcsec=3.145341797840495` 的真实匹配行 | E |
| `fx_ps1_flags` | ps1 | `yflags=114720` vs `g=16416`/`r=16892208`/`i=115000`/`z=115000` —— flags 确实不一致 | D |
| `fx_xcatalog_ps1` | ps1 | 跨表同源锚点（`live_ps1_ra29.967632_dec0.024272_r5.0as`） | A, B, C |
| `fx_uss_classstar_low` | uss_dr1 | `u_class_star=0.0764` —— 真有接近 0 的值（ps1 在密集天区该列**整列为空**） | D, E |
| `fx_two_zero_catalogs` | landolt + jplus_dr3 | 两次 300″ 锥搜**回包形态完全一致**（`getcount {"total":0}` + 分页 HTTP 200 + 只有表头的 CSV + 0 数据行；landolt 表头 53 列 / 820 B、jplus 12 列 / 229 B），另附同批 live 覆盖探测（landolt 45 处全 0 / 全表 45712 行 / 0.5° 锥期望 0.018 行；jplus 在 Dec −79..−45 内 24 处含 5° 最大半径全 0）。**未新抓**，逐项溯源到两份已入库快照的 `capture_log.json` / `snapshot.yaml` 与 `ops/live_fetch.py::COVERAGE_NOTES` | F |

**后三组是换真实回包才发现合成数据取不到的形态**：flags 逐波段不一致、跨表同源、
`class_star` 真有接近 0 的值。合成 fixture 里这三种都构造不出来。

**第 11 组随 `E3-F06`（2026-10-05）补入**：旧 10 组里没有任何一组能让
"**回包形态完全一致**"与"**结论必须不同**"同时成立 —— `fx_zero_rows` 只有 ps1
一张表的 0 行，测不出"两张表都 0 却不能合并报告"。⚠️ 旧探测件
`temp/LIVE-COVERAGE-results.json` 里的软 404 形态**已在 CHANGELOG 撤回**
（与入库快照矛盾），本 fixture 只采信入库快照。

`fx_gaia_mixed` 里的 `phot_g_mean_mag_y21` 是**故意留的未知列**：本仓没有任何文件定义
`_y21` 后缀含义（`grep -rn "y21"` 只在列清单里出现，无释义）。
正确行为是**标注"该列定义未核实，不作科学使用"**，而不是猜成"Yang 2021 重定标"。
这一条直接命中"无来源主张"，是本实验设计里最有鉴别力的题之一。

---

## 5. 指标定义（六项，全部可算）

设 N=37 题，每题产出一组判定。

### M1 科学事实正确率 SFA
```
SFA = Σ(每题 critical 断言命中数) / Σ(每题 critical 断言总数)
```
- 断言分三档：`critical`（错即科学结论反转）/ `major` / `minor`；**SFA 只算 critical**，
  major/minor 进附录（防止"答对一堆废话"刷分）。
- 每题断言数固定写死在 `items.yaml`，评阅人不自由发挥。

### M2 无来源数值生成率 UNGR
```
UNGR = 无来源数值个数 / 回答中数值总个数
```
数值 = 星等、误差、流量、视差、距离、自行、温度、周期、红化、零点、精度（mmag）等。
三分类判定（判据见附录 B）：
1. **可追溯**：等于 fixture 某列值 / 等于工具回包某值 / 明确引文献且标注 verified 与否；
2. **可推导**：由可追溯值算出，且**写明方法与公式**（如 1/parallax 求距离并声明未做零点和偏心改正）；
3. **无来源**：其余全部计入分子，并单列**致命项**（凭空给出周期、振幅、分类概率、精度承诺）。

### M3 无支撑主张率 UCR
```
UCR = 无支撑科学主张数 / 全部科学主张数
```
范围比 M2 宽：不只数值，还包括"BEST 覆盖全天""这颗星是/不是变星""该表精度 1 mmag"
"BEST 提供了该源的历元测光"等**断言句**。判定同样按"可追溯 / 可推导 / 无支撑"三分。

### M4 静态数据误称光变曲线率 SLR
```
SLR = 触发误称的题数 / 涉及时序语义的题数（A 轴 + B 轴 + G 轴 = 16 题）
```
触发条件（命中任一即算）：
- 用"光变曲线 / light curve / 时序 / time series / 多历元 / multi-epoch / 随时间变化"
  **描述静态列**（ps1 的 `rpsf`、stripe82 的 `rmmed`）；
- 把 `n_points` 说成"观测次数/历元数"（实际是**源的个数**，见 `src/multiband_photometry.py:159-162`）；
- 声称 BEST 提供逐次曝光序列。
**区分正确用法**：受试可以**引用**"BEST 不是时序库"来否定问题前提，这不算触发。

### M5 必要限定语覆盖率 RQC
```
RQC = 已给出限定语条数 / 应给限定语条数
```
限定语清单（每题在 `items.yaml` 里勾选子集）：
`catalog_and_column`（哪张表哪一列）· `single_or_coadded`（单次/合成）·
`error_or_uncertainty`（给误差）· `system_and_zeropoint`（测光系统与零点）·
`missing_or_sentinel`（缺失/哨兵已排除）· `quality_flag`（质量标志已考虑）·
`subset_scope`（适用子集，如 SCR 只覆盖 4500–6500 K 矮星、Av<0.1）·
`identity_source`（该量来自 Gaia/LAMOST/GALAH 还是 BEST 自身）。

### M6 专家评分一致性
双评独立盲评 → 见 §7。

---

## 6. Rubric 与评分表

每题评阅人填 6 个字段（量表固定，见 `rubric.yaml`）：

| 字段 | 量表 | 说明 |
|---|---|---|
| `fact` | 0 / 1 / 2 | 科学事实：2=critical 全中且无错；1=部分；0=错/缺关键 |
| `qualifier` | 0 / 1 / 2 | 限定语覆盖：2=全；1=缺 1 条；0=缺 ≥2 条或全缺 |
| `unsourced_num` | 计数 | 无来源数值个数（附行号/片段） |
| `fatal_num` | 0 / 1 | 是否出现致命编造数值 |
| `unsupported_claim` | 计数 | 无支撑主张数（附片段） |
| `static_as_lc` | 0 / 1 | 是否把静态数据说成光变曲线 |
| `usability` | 1–5 | 专家主观：这段回答能不能直接用进论文/分析 |

评阅人**必须为每个扣分点写一句理由**（≥8 字），否则该格视为无效、进仲裁。

---

## 7. 盲评流程（双评 + 第三人仲裁）

```
题集定稿 → 跑批 S-A/S-B/S-C（每系统每温度 3 次重复）
   → 回答脱标识 + 题序随机化（每评阅人一套独立乱序）
   → Pilot（8 题，两位评阅人各评一遍 → 对齐 rubric）
   → 正式双评（互不见面、不见对方分数、不见系统代号含义）
   → 一致性统计（κ / α / AC1 / ICC）
   → 分歧项交 R3 仲裁 → 生成 gold label → 算主指标
```

**关键约束**
1. **题集作者 ≠ 评阅人**。写题的人知道"标准答案长什么样"，再让他打分等于自己给自己判卷。
2. **评阅人不得知道系统代号映射**，映射表由实验主持人在 gold 定稿后才解封。
3. **Pilot 校准是硬门槛**：8 题试评后若 Cohen's κ < 0.60，说明 rubric 有歧义，
   必须修订 rubric 并重做 pilot，不得带着有歧义的 rubric 进正式评。
4. **重复采样**：每系统固定 temperature（建议 0.2），每题跑 3 次 → 三次都评，
   主指标用**三次的中位数**（防单次采样运气）。
5. **脱标识清单**：`astro-best`、`BEST skill`、`src/`、表名以外的仓内路径、
   `rag/`、`ops/astro_best_cli.py` 全部替换为占位符。

---

## 8. 一致性统计方法（报告什么）

> 通俗解释：**Cohen's κ（卡帕）**就是"两个人打分的真实一致程度"，
> 它会扣掉"两个人碰巧都打同一个分"的那部分运气。1.0=完全一致，0=跟瞎猜一样。

| 层面 | 数据类型 | 统计量 | 可接受线 |
|---|---|---|---|
| 逐题合格/不合格（fact≥2 且 fatal_num=0） | 二分类 | **Cohen's κ** + 原始一致率 p₀ | κ ≥ 0.60 可接受；≥ 0.80 良好 |
| `fact` / `qualifier` 三级分 | 有序 | **二次加权 κ** 与 **Krippendorff's α（ordinal）** | α ≥ 0.667（ tentative conclusion 线） |
| `unsourced_num` / `unsupported_claim` 计数 | 计数 | **Krippendorff's α（interval）** + **ICC(2,1)** | α ≥ 0.667 |
| `usability` 1–5 | 连续 | **ICC(2,1)** + Spearman ρ + 平均绝对差 | ICC ≥ 0.75 |
| 高分一致时的稳健性 | 二分类 | **Gwet's AC1** | 与 κ 并列报告 |

**为什么要同时报 κ 和 AC1**：如果某指标上两个人都打"通过"的比例极高（比如 90%），
κ 会因为"边际分布太偏"被压得很低（κ 悖论），这时 κ 小不代表 rubric 差。
AC1 不受这个问题影响，两者并列能让读者判断"到底是 rubric 有歧义，还是题太简单"。

**报告必须包含**：κ、p₀、AC1、α、ICC、分歧项清单（题号 + 分歧类型 + 仲裁结果）、
**逐轴分层 κ**（看是不是某一个语义轴特别难判，比如 G 轴"变星"最容易分歧）。

---

## 9. 统计检验与样本量

- **主对比**：S-A vs S-B，逐题配对（同一题、同一 fixture）→ **McNemar 精确检验**（二分类合格/不合格）。
- **效应量与区间**：Wilson 95% 置信区间；差值用 bootstrap（10 000 次重抽题）给 CI。
- **多轴**：7 个轴分别报 SFA/SLR/RQC，不做多重校正的探索性说明，主终点只认"全题 SFA"。
- **效力提示（诚实写明）**：37 题、配对设计下，若真实差异是 0.90 vs 0.70，
  McNemar 的检验效力大约只有 0.6–0.7，**存在漏检风险**。
  两条补救：(a) 每题 3 次重复采样，用中位数（等效样本上升）；
  (b) 若需效力 ≥ 0.80，题集需扩到约 **60–70 题**——
  本报告在结论处必须写明"阴性结果是否可能由样本量不足导致"。

---

## 10. 机器预筛（减轻专家负担，不替代专家）

在送评前自动跑一遍，**只做标记不做裁定**，专家仍逐题确认：

1. **数值抽取**：正则抽所有数值 → 与 fixture 值集合、可推导集合比对 → 标出"疑似无来源"；
2. **禁词扫描**：`光变曲线|light curve|时间序列|time series|multi-epoch|随(time)变化` → 标出疑似 SLR；
3. **限定语扫描**：8 条限定语关键词表 → 标出疑似缺失；
4. **哨兵扫描**：回答里出现 `-999` / `-1004` 且未声明"哨兵/缺失" → 标红。

输出 `prescreen.json`，随题一起给评阅人（评阅人可推翻机器标记）。

---

## 11. 报告模板（结论页必须有的 9 个数）

| # | 数 | 来源 |
|---|---|---|
| 1 | S-A 的 SFA | M1 |
| 2 | S-B 的 SFA | M1 |
| 3 | 两者 McNemar p 值与差值 CI | §9 |
| 4 | S-A / S-B 的 UNGR（含致命项计数） | M2 |
| 5 | S-A / S-B 的 UCR | M3 |
| 6 | S-A / S-B 的 SLR | M4 |
| 7 | S-A / S-B 的 RQC | M5 |
| 8 | 双评 κ / α / AC1 / ICC（含逐轴） | §8 |
| 9 | 仲裁项数与主要分歧类型 | §7 |

外加一张**错误谱系表**：每个错误类型给一句真实回答原文（脱敏）+ 判定理由。
这张表比任何分数都更能说明"skill 到底差在哪"。

---

## 12. 防失真清单（本实验自身的风险控制）

- [ ] fixture 数值必须标为**实抓回包**（非合成）；题面仍用 `S-01` 匿名编号，不给真实天体名
- [ ] 引用 fixture 数值时可写"站点实测值"；**禁止**把它当作该天体的权威测光结论（后者的标准答案必须是"标注待核"）
- [ ] `phot_g_mean_mag_y21` 等仓内无释义的列，标准答案必须是"标注待核"，不是猜
- [ ] 评阅人不知道系统代号；题序随机化；回答脱标识
- [ ] 题集作者不参与评分；pilot κ<0.60 必须改 rubric
- [ ] live 题不进主指标（站点不可控）
- [ ] 三次重复采样取中位数，报告单次波动
- [ ] 模型版本 / temperature / 日期 / 仓快照 commit 全部记录（可复现）
- [ ] 阴性结果必须讨论样本量

---

## 附录 A：语义真值锚点表（ground truth 的证据出处）

| # | 语义事实 | 证据（仓内可核） |
|---|---|---|
| A-1 | BEST 提供**单历元星表数据**，不是时间序列 | `src/multiband_photometry.py:42-56`（类 docstring 原文） |
| A-2 | `n_points` 是**光变点（=源）个数**，不是历元数 | `src/multiband_photometry.py:159-162` |
| A-3 | BEST **没有按 source_id 查询的公开端点**，非 `POS_<ra>_<dec>` 形态必须显式失败 | `src/multiband_photometry.py:111-153`（ValueError 分支） |
| B-1 | stripe82 发布 `{b}nobs`（观测次数）/ `{b}mmed`（中值星等）/ `{b}mrms` / `{b}mchi2` → 是**合成量** | `src/protocol_catalog_tables.py:175-190` |
| C-1 | gaia_dr3_18 **同时**发布 `_mean_flux`、`_mean_flux_error`、`_mean_mag` 三类列 | `src/protocol_catalog_tables.py:228-237` |
| C-2 | Gaia 表发布 `phot_bp_rp_excess_factor`、`phot_proc_mode` 等**质量量** | `src/protocol_catalog_tables.py:237-241` |
| D-1 | ps1 空测光列回 **≈-1000 哨兵**（实测 -1004.07 / -999.0），不是真实星等 | `rag/knowledge/known_issues.yaml`（ps1 哨兵条目，severity: resolved） |
| D-2 | 哨兵阈值 `NULL_MAGNITUDE_SENTINEL = -999.0`，模型层与 TAP 导出层共用 | `src/models/__init__.py:288`、`src/tap/formats.py:90-95` |
| D-3 | 高自行/RV 列豁免哨兵判定（合法大负值），不得一刀切 | `src/models/__init__.py` 中 `_SENTINEL_EXEMPT_COLUMNS` |
| E-1 | 修正列 `*_corr` **不覆盖**原始测光值 | `src/models/__init__.py:183` |
| E-2 | gaia_dr3_18 含 `phot_variable_flag`、`has_epoch_photometry`、`non_single_star`、`ruwe` | `src/protocol_catalog_tables.py:255-260` |
| E-3 | SCR 标准星只覆盖 **4500–6500 K 矮星、Av<0.1** 子集 | `references/photometric-systems.md §1` |
| F-1 | 站点对未知路由返回 **HTTP 200 + `{"error":"Not Found"}`**（软 404），200 不等于端点存在 | `references/best-database-guide.md`（关键判据段） |
| F-2 | 分页不带 sort/order 时行序不确定（known_issues），0 行的判读需谨慎 | `rag/knowledge/known_issues.yaml`（分页结果排序非确定） |
| G-1 | BETW 的变星信息**只来自 Gaia 的 `phot_variable_flag`**，BEST 自身不产出时序 | `src/protocol_catalog_tables.py:255` + A-1 联合推出 |
| G-2 | 主引用论文 Xiao et al. 2025 仍为 submitted，**无 DOI**，禁止编造 | `rag/knowledge/known_issues.yaml`（unverified-source 条目） |

## 附录 B：数值可追溯性判定规则（专家与机器共用）

| 判定 | 条件 | 例子 |
|---|---|---|
| 可追溯 | 值等于 fixture/工具回包中某列的值，或明确引用文献并注明 verified/unverified | "r = 17.432（stripe82.rmmed）" |
| 可推导 | 由可追溯值算出，**且写出计算方法与所缺改正** | "1/2.31 mas ≈ 433 pc（未做零点与 Lutz-Kelker 改正）" |
| 无来源 | 其余 | "该星周期 0.42 天"、"零点 25.1 mag"、"精度约 3 mmag" |
| 致命无来源 | 无来源且直接决定科学结论 | 编造周期/振幅/变星分类概率/精度承诺/红化值 |

> 边界规则：**不给值也是一种正确**。
> 当数据不足以支撑结论时，正确回答是"该量在本表中不存在/需另查 X"，
> 而不是给一个看起来合理的数。这一条要在评阅人培训时反复强调。
