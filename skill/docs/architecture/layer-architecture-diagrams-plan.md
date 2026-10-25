# astro-best 分层实现架构图计划（苏格拉底式 · Phase 10）

> 用户第 9 轮指示（2026-10）：从 README.md 的架构出发，对 evals / test / src 等**每一类内容**，
> 模仿 drawio-diagram-author skill 里 math_model 流程图的设计做**实现架构图**，加入**能力边界**
> 等内容，**颜色和布局不变**；每一层 （evals 算一层）按设计图做一张实现架构；总的 best 就是
> 把这些架构连接汇总起来。**本文件是计划文档，批准前不动任何源文件。**
>
> 裁决口径：承接此前各轮"裁定也由你定"的授权 — 本文所有问号都由我给出裁定与理由，用户可单项否决。
>
> **口径订正 (2026-10-05)**: 本文提到的 `CHANGELOG.md local-only` 是**当时**的
> 状态，已于 2026-10-05 改判为**入版本控制**（变更历史是删改记录的唯一载体，
> 留在仓外等于无记录）。按本计划画图时该条按"已入库"标注，别照抄旧措辞。

---

## 0. 结论先行

> **第 10 轮完善说明（2026-10）**：本计划经三轮并行事实核验（图示目录与生成器 / 门禁体系 /
> 文档缺口，证据见 §11）与主窗口自查后发现：Q1-Q10 的方向性裁定全部成立，但**基线数字、
> 范式归属、缺口清单、门禁计数、渲染估算五类陈述与仓库现状已有系统性偏差**，且发现一个
> **开工前必须先拆的红灯（树 SSOT 门禁当前 RED）**。本轮新增 Q11-Q21 十一问逐条裁定，
> 缺口清单从 G-5 扩充到 G-10，门禁从"新增 6 项"扩为"新增 8 项"。以下表格已按核验结果更新。

| 项 | 裁定 |
|---|---|
| 层数 | README"逐文件能力边界"的 13 个顶层分组 = 13 张层图；local-only 目录不单独成图，进汇总图边界带 |
| 汇总 | 1 张 `astro-best-layer-summary.drawio`: 13 个层容器 + 五类语义边 + 一条闭环回边 + 外框轨道 |
| 范式来源 | math_model 流程图**结构范式**迁 9 项；口径表/闭环走廊的**本仓先例**另来自数模国赛 A 题 panorama 生成器（Phase 9 已落地，见 §2）；Macaron 配色/论文竖版画布**不迁**（用户明示颜色布局不变）|
| 视觉语言 | 完全沿用既有宏流程图：Slate 工程调色盘（FLOWCHART_PALETTE **11 键**）+ 横向泳道 + 纯正交 Manhattan 走线 + 零 Emoji |
| 坐标 | 新层图走**确定性网格布局**：宽固定 4400、高按 section/行数累加计算并在数据表头声明；卡宽随列数机械计算（Q12）；既有两张图的手写坐标**不动** |
| 产物 | **30 个新受跟踪文件**（14 `.drawio` + 3 脚本 + 13 数据表，`git add -f`）；PNG/SVG/PDF 只本地渲染不跟踪（延续 Phase 9 裁定）|
| 门禁 | 既有 **18 项不回归**（final_gates_phase8.py 的 17 条判定 + comment_audit，口径见 §8）+ 新增 **8 项**图示门禁（N1-N8）；两道门禁从 glob 升级 rglob（修真实缺口）|
| 红灯 | **树 SSOT 门禁当前 RED**（实际 281/清单 278，多出 `.workbuddy/` 三条目）— Phase A step 0 先拆，否则"既有门禁不回归"无基线（Q14）|
| 工作量 | 5 个 Phase（B 分 3 次原子提交，共 7 个提交）；每 Phase 前 `git status` 确认无残留 |

---

## 1. 苏格拉底式提问与裁定（21 问）

### Q1 "每一个类型"到底是多少层？会不会太细？

README 的"逐文件能力边界"表已有 13 个顶层分组 （根目录文件 / agents / contracts / evals /
examples / ops / rag / references / src / static / templates / test / weights）+ local-only 目录。

**裁定：13 张层图 + 1 张汇总图。** 理由：① 用户明示"每一个层次 （evals 算一层）"，层 = README
分组是最强 SSOT，不另发明分层；② agents / weights / examples / 根目录文件这四个薄层不省略，
用紧凑的单段图 （1-2 个阶段容器）表达，成本低且保证"全覆盖"承诺不破；③ local-only 目录
（docs/ temp/ best_data/ 等）不是能力层，在汇总图里作为"边界带"说明，不占层号。

### Q2 会不会和既有两张架构图重复？

**裁定：三视角互补，既有两张图结构零改动。**

| 图 | 视角 | 读者问题 |
|---|---|---|
| `astro-best-macro-flowchart` （既有）| **运行时数据流**：人/入口 → 五状态机 → 两阶段协议 → 12 星表 → 存证/闭环 | "一次查询在系统里怎么流"|
| `astro-best-layer-*.drawio` （新 ×13）| **仓库组成**：每个目录内部的阶段结构、模块分工、边界 | "evals 这一层内部由什么构成、边界在哪"|
| `astro-best-layer-summary` （新）| **层间治理拓扑**：谁回归谁、谁审计谁、谁咨询谁 | "改 src 会牵动哪些层"|

既有图只在 `docs/diagrams/README.md` 增加交叉引用，不改卡片文案 — 改它就要重跑漂移闸门，
收益不足以抵消风险。**"结构零改动"的精确边界见 Q14：纯文案修正（陈旧路径）不在此列。**

### Q3 math_model 流程图迁哪些范式？哪些不迁？

先读 `<USER_HOME>\.agents\skills\drawio-diagram-author\scripts\generate_math_modeling.py`
（508 行）得到的结构解剖：外框闭环轨道 + 5 左徽章 + 5 右阶段标签 + 5 个虚线阶段容器 +
阶段内 （核心卡/子问题树/数据分叉/假设与适用范围/三阶段虚线管道/口径表/策略堆叠/归因堆叠/
双箭对比桥/参数对比表）+ 环内循环节点 + 段间块箭头 + 落盘后跑安全 lint。

**裁定：迁 9 项结构范式，不迁 3 项视觉范式。**

| # | 迁移项 | math_model 原型 | astro-best 层图落地 |
|---|---|---|---|
| P1 | 外框闭环轨道 | 左/右/底分段轨道闭环 | 汇总图与层图的外环返回走线 （层图即闭环走廊返回段）|
| P2 | 左徽章 + 右阶段标签 | 5 chevron + 5 竖排标签 | 每层 N 个阶段徽章 （左）+ N 个阶段名 （右），与 math_model 同构 |
| P3 | 阶段主线 + 段间箭头 | arrow_1_2..4_5 块箭头 | 层内阶段容器自上而下，段间 south 块箭头 |
| P4 | 核心引擎卡 + 虚线多阶段管道 + 内向指针 | s2_core_card / s2_pipeline_box / ptr 三角 | 每层一张"本层主引擎"卡 + 虚线管道 + 内向指针 （如 evals 的 装载→探针→执行→审计→评分）|
| P5 | 口径表一级元素 | math_model 指标口径三行表；**"温度 °C / 浓度 kg/kg 独立成卡"的先例出自数模国赛 A 题 panorama 生成器（本仓 Phase 9 已落地，非 math_model）** | 每层一张口径表 （阈值/单位/预算数值，行内注释标明源码出处 — 与宏流程图 FLOWCHART_UNITS_STRIP 同规则）|
| P6 | 边界卡 | "模型假设 ①-⑥ / 适用范围界定"| **能力边界卡**：本层做什么 / 不做什么 / 委派给谁 / 失败语义 （用户点名的"加入能力边界"）|
| P7 | 环内循环节点 | s5_loop_box 三弯箭闭环 | 每层一条内循环 （evals：评审→修复→复评；test: RED→GREEN→REFACTOR; rag：任务→经验回写→检索增强）|
| P8 | 双箭对比桥 | "统一引擎口径 横向可比"doubleArrow | 层内横向对照 （如 evals 五维权重 vs test 分层覆盖；src in-scope vs 委派 out-scope）|
| P9 | 落盘后安全 lint | main（）里 verify + check | 生成器对 14 个产物逐个跑 `verify_drawio_security` + 碰撞审计，**不过不渲染**（与宏图实际顺序一致，见 Q13）|

**不迁**: Macaron 六色配色 （本仓是 Slate 工程调色盘，`FLOWCHART_PALETTE` **11 个语义色键** —
title/banner/blue/green/cyan/indigo/amber/red/purple/neutral/muted）、
论文竖版画布 （本仓是横向泳道语言，画布 4400×3200 vs math_model 1000×1450）、论文装饰性版式
（六边形改进方向/树形总线等留待确有语义时再议）。用户原话"颜色和布局不用变换"即此边界。

### Q4 13 张图的坐标手写还是自动？

**裁定：新层图用确定性网格布局；既有两张图手写坐标不动。**

`layout_data.py` 的既有约定是"坐标显式手写 + 行序即添加序"，适合 2 张图；13 张图手写
≈ 500+ 个魔法数字，人不可审计。新数据表只声明**逻辑内容** （阶段、卡片文案、列数、色键），
坐标由生成器的网格函数确定性计算。既有常数（实测）：容器 x=200、容器内宽 3890、卡局部
x=55、卡宽 570、列距 94（6 列网格：55/719/1383/2047/2711/3375，步长 664）；s4 星表段有
710/85 变体，**层图不引入该变体，统一走标准常数**。既有图不动的第二个理由：它们的逐字节
漂移闸门是安全网，不为新图改旧图。**卡宽/卡高的完整计算规则见 Q12。**

### Q5 要不要抽取共享样式/审计模块 （会动到两个既有生成器）？

**裁定：抽 `diagram_style.py` （样式工厂，按 palette 绑定）与 `diagram_audit.py`
（安全 lint + 零 Emoji + AABB 碰撞），旧生成器改为 import 并删除自有副本。**

核验修正了抽取范围的事实基础：两个旧生成器**并不**各持一份审计代码 —
`gen_astro_best_architecture.py` 无内联审计（审计在独立脚本 `audit_local.py`），
`gen_best_macro_flowchart.py` 的内联审计又与 `check_macro_collisions.py` 重复。
因此：**样式抽取涉及两个生成器；审计抽取 = macro 内联审计 + check_macro_collisions.py
合并进 diagram_audit.py（check_macro_collisions.py 退化为薄 CLI 或吸收），arch 生成器不动。**
硬验收：现有 `test_generator_output_matches_tracked_artifact` 逐字节闸门必须全绿 —
它就是"抽取无行为变化"的机械证明。**若抽取出现任何字节差异，立即回退为第三份副本方案**
（新生成器内自带副本），不纠缠、不调旧图迁就新图。

### Q6 13 个层数据表放哪？平铺还是子目录？

**裁定：`docs/diagrams/layers/` 子目录，一层一模块 `layer_<id>.py` （13 个）。**
平铺会让图示目录从 7 个脚本变成 20+ 个文件，索引门禁虽能覆盖但目录语义混乱。
子目录暴露一个**真实缺口**：现有两道门禁 `test_readme_index_covers_every_script`（:160
`glob("*.py")`）与 `test_every_source_file_is_git_tracked`（:186-187 `iterdir()`）都只查
docs/diagrams/ 顶层 — 子目录里的文件会逃过 git 跟踪门禁 （正是 Phase 9 `drawio_io.py` 被
静默跳过那一类故障，两道门禁的 docstring 自述守的就是它）。**本计划把两道门禁升级为 rglob
递归**，缺口随子目录一起修掉。
**配套（核验新增）：rglob 后 `layers/` 下 13 个数据表文件名也必须出现在
`docs/diagrams/README.md` §3（索引门禁逐文件名比对）— §3 增加 layers/ 分组行并以紧凑枚举
列全 13 个文件名，Phase D 的文档同步量比原估更大。**

### Q7 渲染产物 （PNG/SVG/PDF）管不管？

**裁定：延续 Phase 9 口径 — `.drawio` 源与全部脚本 `git add -f` 入库；渲染产物只落本地、
不跟踪。** 14 张新图若全渲，本地新增位图对 git 是纯噪音。**体积估算按实测基线修正**
（原估 ~50MB 过乐观）：宏流程图单图实测 PNG 4.53MB + SVG 11.35MB + PDF 0.58MB ≈ 16.5MB；
层图内容少，预计 3-8MB/图。**格式策略：层图渲 PNG+PDF 为主，SVG 按需**（仅大屏展示场景），
预计本地新增 40-120MB，Phase E 记录实测值。`docs/diagrams/README.md` §1 表与 §5 渲染状态
同步更新；根 README 规则 5 与 §1 表的大小口径**三处漂移一并修**（README:9 与根 README:27
写"约 270 KB"、governance §13.4 写"约 280 KB"、实测受跟踪 298,632 B≈292 KB；渲染产物
README 写 27.9MB、实测 30,278,056 B≈28.9MB）— 统一改为"按目录实测，随 Phase E 刷新"的
表述，不再写死数值。

### Q8 能力边界卡的内容从哪来？能不能概括？

**裁定：逐字转写，禁止二次概括。** 来源按优先级：README 逐文件能力边界表 → SKILL.md
in_scope/out_scope + 委派表 → architecture.md §1 失败隔离（L63-67）与门禁表（L56-61）。
这与既有铁律"每张卡的 HTML 都是 SKILL.md / architecture.md / 契约文件的逐字转写，图与文档
不一致即视为缺陷"同一条。**转写会发现文档缺口 （见 §3.2），那些是内容编辑（README 治理
规则 1 权限矩阵之"内容编辑自由"），在 Phase A 先修文档再转写**，否则层图会把错误固化进去。
**新增回退规则（Q20）：三个来源均未载明的层，边界卡显式写"文档未载明，待补"，禁发明。**

### Q9 汇总图连什么？怎么连？

**裁定：五类语义边 + 一条闭环回边，层容器按依赖层级排布。**

| 边类 | 颜色/线型 | 连接 |
|---|---|---|
| 实现依赖 | 靛实线 | 根目录入口 → src; ops → src; static → （manifest 路由）|
| 契约约束 | 青实线 | contracts ↔ src; contracts → evals （被审计）|
| 回归覆盖 | 绿实线 | test → src （每个能力域一条）；test → evals （行为用例消费场景 SSOT）|
| 评审审计 | 橙实线 | evals → references / templates / contracts / test （六审计器靶目录）|
| 知识咨询 | 紫实线 | rag → src （VALIDATE/GATE 态）；references → rag （引文下沉）|
| 闭环回边 | 紫虚线 sw=2.4 | evals 评审不通过 → src/test 修复 → 复评 （外框轨道收口，与宏流程图 e_e6_a1 同范式）|

五类边所需的靛/青/绿/橙/紫全部在 FLOWCHART_PALETTE 11 键内（#4F46E5/#0891B2/#059669/
#EA580C/#9333EA），**不新增色键**；若未来确需新语义色，优先复用最近键并在图例记录映射。
排布：入口声明 （根目录/agents）→ 实现 （src）→ 契约 （contracts）→ 回归 （test）→
评审 （evals）→ 知识规则 （references/rag/static/templates）→ 运维出口 （ops）→
外围声明 （examples/weights）→ local-only 边界带。委派越界 （astro-catalog / astro-clean）
在边界带标出，不进层容器。**边界带的 docs/ 条目须带精确措辞："docs/ local-only（例外：
docs/diagrams/ 的 .drawio 源与脚本受跟踪）"** — 与根 README 规则 5 的例外描述一致，
避免重蹈 §12.2-4 记录过的"README 与 git 事实矛盾"。

### Q10 怎么算"做完"？验收是什么？

**裁定：§8 门禁清单全绿才算完** — 14 个产物齐全且受跟踪、逐字节可复现、每张层图必含
能力边界卡与口径表、禁旧措辞、既有 18 项门禁不回归、`python evals/eval_runner.py --mode all`
1.0000。不接受"图生成了但门禁没扩"— 那正是旧图残留 S4 文案数周无人发现的同一故障模式
（该故障模式已成文于 test_diagram_ssot.py docstring）。

---

### Q11 "既有 18 项门禁"到底是几项？以什么为 SSOT？

核验发现三处计数口径：temp/final_gates_phase8.py 实测 **17 条判定**（ASTRO 9 + MONO 5 +
单模式 2 + 400 行预算 1），加上单独运行的 comment_audit（temp/comment_audit.json 六类全 0）
= 18。历史文档（governance §12.4/§13.3 与本计划 §8）写"18 项全绿"可追溯，但**计数依据
分散**。

**裁定：§8 改为机械定义 — "既有 18 项 = final_gates_phase8.py 的 17 条判定行 +
comment_audit 六类全 0；Phase 10 终验以 temp/final_gates_phase10.py 的判定行数为准
（预计 17+comment_audit，新增 N1-N8 内嵌进"图示定位门禁"这一条判定行的测试文件里）。"
另：实测发现"既有门禁全绿"的基线前提当前不成立（树 SSOT RED），处置见 Q14。**

### Q12 13 张层图 + 汇总图的画布多大？坐标怎么算？

原计划只说了汇总图"4400×3200 与宏流程图同规格"，没给计算规则；而 13 个层容器 × 3-5 卡 +
边界带在 3200 高度内放不下（粗算 5 行容器 ≈ 2900 + 横幅/口径/图例/边界带 ≈ 1100 > 3200）。

**裁定：确定性网格 + 计算后声明，不写死。**
- **宽固定 4400**（与宏图同一视觉语言；容器 x=200、内宽 3890 不变）；**高由网格函数累加计算**：
  H = 顶横幅 + Σ(阶段容器高) + 边界卡 + 口径表 + 内循环盒 + 外框轨道余量 + 底边距；
  每张图的 canvas=(4400, H) **在数据表头声明**，审计模块核对实际节点不越界。
- 汇总图预计 4400×3600~4000（13 容器 5 行 + 边界带）；厚层图（src/evals/test）预计
  4400×3300~3600；薄层图（agents/examples/weights）单段 ≈ 4400×1400~1800。
- **卡宽 = (3890 − (列数−1)×94) / 列数**（3 列≈1234、4 列≈902、6 列≈570）；列距 94 为间隙。
- **卡高按内容机械计算**：HTML `<br/>` 行数 × 行高 + 上下 padding，取整到 5px；数据表可给
  显式高度覆盖（可选字段），AABB 碰撞审计兜底 — 任何算错都会在审计里现形。
- "布局不变"= 同一泳道视觉语言（画布宽/容器坐标/色盘/正交走线），**不是**同一像素高度；
  高度是内容的机械函数。math_model 的 1000×1450 竖版与 Macaron 配色仍不迁。

### Q13 落盘、审计、渲染的顺序到底是什么？

原计划 §4 写"渲染后逐个跑 diagram_audit，全部过才落盘 — 与宏流程图'先审后渲染'同序"，
自相矛盾且与事实不符。核验实测：宏流程图生成器的真实顺序是
**save_clean 落盘 → verify_drawio_security + 碰撞审计 → 不过不渲染（export 跳过）** —
审计拦的是渲染，不是落盘；且 macro 的 main() 并未调用 check_drawio（math_model 才调）。

**裁定：新生成器与宏图实际顺序严格同构 — ① drawio_io.save_clean 落盘（禁裸 doc.save）
② 对 14 个产物逐个跑 verify_drawio_security（8 类）+ 零 Emoji + AABB 碰撞审计
③ 任一不过：不渲染、exit 1。修正 §4 与 P9 的表述。漂移闸门（N2）比对的正是已落盘的
.drawio — 先落盘再审不影响"逐字节可复现"的证明力。**

### Q14 "既有两张图内容零改动"与图文一致性冲突时听谁的？

核验发现宏流程图 4 个节点共 **7 处陈旧路径**：node_a2 `src/astro_best/cli.py` 与
`scripts/cli.py`、node_a3 `src/astro_best/pybest.py`、node_a5 `best_standalone.py`/
`best_query.ps1`/`best_query.sh`、node_a6 `scripts/cloud_modelscope/` — 磁盘与树清单中
**无一存在**（src/ 是平包无 astro_best 子包、根目录无 scripts/、三个独立脚本已不在树）。
新层图按 Q8 逐字转写真实树，两套图并存会自相矛盾 — 正是 Phase 8 清理过的"半迁移文案"
同一故障模式（§12.2-3）。

**裁定：Q2 的"零改动"精确化为"零结构改动"；纯文案修正不属于结构改动。**
- Phase A 对两张既有图跑路径 token 扫描：宏图 7 处按 Phase 8 先例（6dabf230 纯文案 diff）
  修 layout_data.py + 重生成；legacy 图实测 0 命中，不动。
- **新增 N8 门禁永久把守**：所有受跟踪 .drawio 内的路径 token（`dir/file` 形态）必须存在于
  磁盘/树清单；白名单 = URL、外部绝对路径（盘符/~/）、环境变量、目录级 token。
- 另实测发现**树 SSOT 门禁当前 RED**（实际 281/清单 278，多出 `.workbuddy/`、
  `.workbuddy/memory/`、`.workbuddy/memory/2026-09-28.md` — .gitignore 已忽略但树门禁扫盘），
  "既有门禁不回归"没有干净基线。**Phase A step 0：① 将 `.workbuddy/memory/2026-09-28.md`
  移入 `temp/` 并删除空目录（规则 2/4：临时文件只在 temp/；§12.6 遗留 2 已登记"待确认后
  移入 temp/"，本轮即确认点）；② 给 ops/verify_tree_integrity.py 的排除列表补
  `.workbuddy*/`（与 .gitignore 对齐 — Phase 9 只加了 ignore 没加树门禁排除，工具一重建
  就复红，这是根治）；③ 复跑树门禁绿后才进后续步骤。** 若用户否决移动，回退为
  `--write` 登记三条目（属规则 1 结构变更，需单独批准）。

### Q15 层图内容新鲜度怎么保证？N2 只证确定性不证新鲜。

N2（逐字节可复现）证明"同一生成器产出同一字节"，但目录新增文件（如 src/tap/ 再加一个模块）
后层图静默过期 — 与 S4 文案残留数周无人发现是同一故障模式。README 四张表经 G-1~G-6 补齐 +
树门禁把守 README↔磁盘，但**没有任何机制把住 图↔README**。

**裁定：新增 N7 门禁 — "层图↔README token 一致"。** 每张层图的模块 token 集合必须等于
README 该目录表行 token 集合：README 表首列的文件路径须逐一作为子串出现在对应层图的
.drawio 文本中；层图中新出现的路径 token 必须能在该目录表行中找到（或命中白名单：聚合行
如 `cases/case_001~004_*.yaml` 的区间写法归一化后匹配）。机械可判，误伤面用白名单控制。
N7 + N8 + 树门禁三者形成闭环：磁盘→README→层图→（路径回磁盘）。

### Q16 文档同步放 Phase D 集中做，还是随 Phase 增量做？

原计划把 `docs/diagrams/README.md` §1/§2/§3/§5 与根 README 规则 5 的全部更新放在 Phase D。
但 Phase B1 就会新增 4 个 `.drawio` — 若既有"图示定位门禁 8 项"中任何一项要求 README §1
列举全部 `.drawio`（或索引门禁随 rglob 升级后要求 §3 列举 layers/ 全部 .py），
B→D 之间会出现中间态门禁红。

**裁定：文档同步增量化 — 哪个 Phase 加产物，就在同一提交更新 `docs/diagrams/README.md`
§1 表与 §3 脚本表（B1 加 4 行 + gen_best_layers/diagram_style/diagram_audit 三行；
B2/B3 增量；C 加汇总图行 + §2 叙述）；Phase D 只负责 N1-N8 门禁（RED 证明后全绿）、
§5 渲染状态、根 README 规则 5 实测口径、governance-debt-plan.md §14 记录。
每个提交保持全绿 — 与提交纪律"每 Phase 前 git status 确认无残留"一致。**

### Q17 渲染到底渲多少？~50MB 的估算哪来的？

原计划估"~50MB 位图"。实测基线：宏流程图单图 PNG 4.53MB + SVG 11.35MB + PDF 0.58MB ≈ 16.5MB
（12 个本地渲染产物共 30,278,056 B≈28.9MB）。14 张层图若全式样全渲可能 100-230MB。

**裁定（并入 Q7，此处留裁决记录）：层图渲 PNG + PDF 为主、SVG 按需；预计 40-120MB 本地
不跟踪；渲染失败不阻断门禁（与宏图 export 同策略）；Phase E 把实测值写进 README §5，
同时修 §1 大小列漂移（macro.drawio 实查 80,210 B，表写 75.1KB）与三处 KB 口径不一
（270/280/292）→ 统一为"按目录实测"表述。渲染命令走 draw.io CLI 封装
（ASTRO_BEST_DRAWIO_EXE），不依赖 make（本机未安装 make，见 Q21）。**

### Q18 口径表里的数值从哪来？"739 passed"能上图吗？

原计划 L3 口径表写"739 passed / 24 skipped" — 这是 pytest 活数，无任何文档出身；测试数一涨，
图就静默过期。而 math_model/panorama 的口径表规矩是"每个数值行内注明源码出处"。

**裁定：口径表只收有文档出身的数值。** 三类可靠来源：① 契约/门禁定义（pass_score 0.9、
completeness_gate=1.0、BEST_1001~1099）；② README/SKILL/architecture 成文数值（24 场景、
9+2 引文）；③ 代码常数（rows=1000、rate_limit=3.0s、k1=1.5/b=0.75）。
**活数（pytest 通过数、门禁判定数）不进门** — 除非先钉进受跟踪文档（如 coverage-matrix.md）
再引用，否则口径表只写门禁阈值不写实测值。"739 passed / 24 skipped"从 L3 口径表移除，
留在本计划正文作为基线记录。**薄层豁免机械化：weights 为唯一 units_strip 豁免层
（本层无数值口径），豁免名单作为数据写进 N4 门禁；边界卡（N3）不豁免。**

### Q19 计划文档自己和治理债文档受跟踪吗？

核验发现：git ls-files docs/ 仅 15 个文件 — `docs/architecture/implementation-plan.md` 与
`implementation-plan-phase0-8.md` **受跟踪**，但**本计划文档与 `governance-debt-plan.md` 都在
docs/ 被 ignore 且从未 force-add**。Phase 9 的 drawio_io.py 被 `git add` 静默跳过是同类
故障（门禁 docstring 自述守的就是它）— 计划文档若丢失，本轮全部裁定与证据链无据可查。

**裁定：Phase A 将 `docs/architecture/layer-architecture-diagrams-plan.md` 与
`docs/architecture/governance-debt-plan.md` 一并 `git add -f`**，与 implementation-plan.md
的既有跟踪惯例对齐。本计划 §0 即该项结构变更的授权载体（规则 1：结构变更需用户明确批准 —
 批准本计划即批准此项）；Phase D 的 §14 记录随后落进受跟踪文件。**

### Q20 转写来源沉默时怎么办？历史轮次编号怎么引用？

两个转写纪律漏洞：① 薄层（agents/examples/weights）在 SKILL.md/README/architecture 三来源
中的记载密度低，Q8 没规定来源沉默时的回退；② L5 口径表引用"（Q-31）"是 implementation-plan-v2
的历史轮次编号，在本文档内不可解析。

**裁定：① 三来源均未载明的层，边界卡显式写"文档未载明，待补"并列入 Phase B 该层的
转写待办，禁发明内容 — 与 Q8"逐字转写"同一条铁律的两面；② "（Q-31）"改为可解析锚点
`test/unit/meta/test_phase4_wiring.py::Q-31`（该测试即"模板 defaults 键子集"实证）；
本计划内所有历史轮次引用一律带文档:行号或测试锚点，禁裸编号。**

### Q21 Phase A 之前还有哪些"计划外文档欠账"要一起清？

核验在 G-1~G-5 之外又发现四笔欠账，全部会污染层图转写，且全部属内容编辑（规则 1 自由区）：

| # | 欠账 | 证据 | 处置 |
|---|---|---|---|
| U-1 | ~~**G6 违反**：SKILL.md 实测 137 行 > "≤100 行（G6）"~~ ✅ **已修，欠账关闭（R2 订正, 2026-10-05）**：`SKILL.md` **现仅 98 行，已满足 G6 ≤100**，`CHANGELOG.md` 载有「SKILL.md 137→98 行 (G6 ≤100 达标)」的修复记录。原证据坐标亦全失效：`SKILL.md:133`（自检项）与 `SKILL.md:118` **越界**（98 行），`README:40` 实为 `README.md` 逐文件边界表的 `SKILL.md` 行（现 43），`manifest.yaml:72` 亦已漂 | 原证据「三处成文 + ReadAllLines=137」已不成立 | ~~Phase A 修剪 SKILL.md~~ **已执行完毕**，欠账 U-1 关闭。层图 L10 可直接转写「≤100 行（G6，已达标）」，无需登记豁免 |
| U-2 | **治理面数量口径不一**（结论仍成立，坐标已订正）：`README.md` 逐文件边界表的 `architecture.md` 行与 `architecture.md` 标题/`## 2.` 段写"12 横切治理面"，`SKILL.md` 组件地图段写"16"，`architecture.md` 正文实为 16（§2 的 12 + §2.1 的 4 附加结构面） | 三处口径 | Phase A 统一为精确表述"12 横切治理面 + 4 附加结构治理面 = 16"，三处同步；L10 转写统一后口径 |
| U-3 | **file-size-budget.md §3 登记簿过时**：仍列两个图生成器 793/584 净行，实测 259/105（755fbe78 拆分后未更新登记簿） | budget §3 L62/L64 vs 实测 | Phase A 顺手修订（内容编辑）；新生成器与 layers/*.py 在该预算覆盖范围内（budget §2 明示覆盖 docs/diagrams/） |
| U-4 | **Makefile 与命令口径**：L10 写"12 目标"实为 **16 个 target**；本机未安装 make；Phase E 的 `make eval --mode all` 三重错误（无 make / make 不接 --mode / --mode all 本就是默认值 eval_runner.py:513） | Makefile:4 与 :6-61 | L10 改"16 目标"并注明本机无 make、命令一律 python 直调；Phase E 改 `python evals/eval_runner.py --mode all` |

---

## 2. 设计范式来源：math_model 流程图结构解剖 + 本仓先例

`generate_math_modeling.py` 的范式清单 （读码结论，508 行）：

1. **画布与外框**: `canvas_bg` 底卡 + 顶部主题横幅锚定 + 左/右/底**分段零重叠轨道**
   （节点处断开，避开徽章），整图收口成闭环；
2. **双轨导航**：左 5 枚竖排徽章 （破题分析/假设符号/建模导优/求解结果/评价推广）+
   右 5 枚竖排阶段标签 （问题重述/模型准备/核心方法/结果对比/结论展望），左右语义错位
   互补 （动作 vs 产出）；
3. **阶段容器**: 5 个虚线圆角框，每段一个主色系，段间 south 块箭头；
4. **阶段内部件**：核心界定卡 → 子问题三分支 （树形叉线）；数据三输入 → 数据整备 →
   假设与适用范围 → 符号与口径；**统一评估引擎卡 （各问共用）** + 三阶段虚线管道 +
   左右内向指针；指标口径三行表；策略堆叠 → 竖向导轨 → 核心卡 ← 归因分析 ← 因素堆叠；
   上/下视角徽章 （约束/松弛）向双向导轨汇聚；基准评估结构化四行卡 + 双箭对比桥 +
   参数对比表；稳健性五检验堆叠 + **环内三弯箭循环盒** + 随机种子复算 + 核心推广卡 +
   场景拓展 （向上箭头）+ 六边形改进方向 + 评价树形总线落四支柱；
5. **质量闭环**: `main()` 落盘后依次跑 `verify_drawio_security` （8 类）与
   `check_drawio` （结构），不过即 exit 1（check 仅脚本存在时跑）。

对 astro-best 的映射要点：math_model 的"问"是论文题目，astro-best 的"问"是**一层目录的
职责**；它的"假设与适用范围界定"就是用户要的**能力边界**；它的"指标口径三行表"就是每层的
阈值/预算数值表；它的"评估引擎共用卡"就是每层的主引擎 （如 eval_runner / protocol /
verify_tree_integrity）；它的"环内循环"就是该层的反馈环。**迁移的是骨架，不是皮。**

**本仓先例（第 10 轮核验补充）**：口径表提为画布级一级元素、闭环反馈走廊提为可见容器带
这两项范式的**成文来源是数模国赛 A 题 `generate_panorama_architecture.py`**
（governance-debt-plan.md:542；layout_data.py:89-90 注释自述"参考数模国赛 A 题全景架构图
的口径表做法"），Phase 9 已落地于宏流程图（FLOWCHART_UNITS_STRIP + loop_corridor 六容器带）。
原计划把"温度 °C / 浓度 kg/kg"当作 math_model 原型系误植 — math_model 有口径三行表但无该
例证。层图的口径表/闭环走廊按**本仓已落地范式**做（与宏图同规则），结构骨架仍取 math_model。

---

## 3. 现状基线：硬约束与转写前必须修的文档缺口

### 3.1 硬约束

| 约束 | 对本计划的影响 |
|---|---|
| 规则 1 权限矩阵（内容编辑自由/结构变更需批准） | 本计划即用户对新增图示文件的结构授权；执行后 `python ops/verify_tree_integrity.py`（默认比对模式）复核 — docs/ 在树清单里是单条目，图示文件增删不改变树清单（核验证实）|
| 规则 3 禁版本号 | 14 个产物禁版本号字面量 （门禁已含 FORBIDDEN_PATTERN 3 正则 + evals VERSION_MARKER_RE）|
| 规则 5 local-only 例外 | 新 `.drawio` + 脚本走 `docs/diagrams/` 例外，`git add -f` |
| 规则 7 400 净行预算 + 中文 docstring | 每个新 `.py` < 400 净行；生成器拆 build_layer/build_summary 两函数族；数据表纯数据；budget §2 明示覆盖 docs/diagrams/（核验证实）|
| 图示铁律 | 走 `drawio_io.save_clean`（禁裸 doc.save — 成文于 docs/diagrams/README.md §5 与 test_diagram_ssot.py:211-212,260）；落盘后安全 lint + 碰撞审计；零 Emoji；正交走线。**注意：图示铁律未进 SKILL.md 六条治理铁律，归属以图示 README 与漂移闸门为准** |

### 3.2 转写前必须修的文档缺口 （层图转写会暴露，Phase A 修）

层图卡片要求"逐字转写 README 表"，而 README 四张表与树清单 SSOT 已有系统性偏差 —
不先修，层图就把错误画进去。以下均为**内容编辑（规则 1 自由区）**，不需要额外批准：

| # | 缺口 | 证据（README 表 vs 磁盘/树） |
|---|---|---|
| G-1 | `contracts/` 表缺 `oauth.contract.yaml` | 树 L271 有；architecture.md:93 §2.1 第 16 治理面引用 |
| G-2 | `references/` 表缺 `data-formats.md` | 树 L333 有（125 行） |
| G-3 | `src/` 表缺 **11** 个在树文件 | serialization L398 / protocol_catalog_tables L393 / auth/session L346 / core/source_postprocess / best_export L379 / download_artifacts L383 / download_region L388 / download_sqlid L389 / **scripts/__init__.py L358（第 10 轮补）** / tap/response L373 / tap/uws_service L375；且"src/tap/（7 个模块）"实为 **9 个文件**（src 磁盘共 51 文件，表+聚合行只覆盖 40） |
| G-4 | `test/` 表与树偏差系统性（比第 9 轮记录的更大） | 计数改 9 处：client 2→1、download 9→10、lightcurve 2→1、meta 5→11、models 1→4、scripts 1→4、auth 2→3、**crossmatch 2→1、audit_round 2→3（第 10 轮补）**；`unit/query`/`unit/config` 两行各写"（1 个）"实为空目录占位（源文件已删，仅剩陈旧 .pyc）；integration 删幽灵行 `test_integration.py`（磁盘/树均无，已拆成 7 个 chain 文件）并补 7 行（query/data_semantics/server_count/soft404/name_resolution/crossmatch/lightcurve _chain）；补 2 行：`unit/serialization/`（1 个）、`test/upstream/`（空占位）。test 全树共 68 个 test_*.py |
| G-5 | 三处大小口径漂移 | README:9 与根 README:27"约 270 KB"、governance §13.4"约 280 KB"、实测受跟踪 298,632 B≈292 KB（.drawio+脚本 290,987 B≈284 KB）；渲染产物 README 写 27.9MB、实测 30,278,056 B≈28.9MB；README §1 大小列亦漂移（macro.drawio 表写 75.1KB、实查 80,210 B）。统一改为"按目录实测"表述 |
| G-6 | `evals/` 表缺 4 个在树文件 | probes.py L309 / probe_support.py L308 / case_runner.py L305 / paths.py L307 均在树，表只有 eval_runner/scoring-rubric/test-scenarios/cases/audit 共 5 组行 — 而表头声称"全树全覆盖" |
| G-7 | ~~**SKILL.md 137 行 > G6 "≤100 行"且无豁免记录**~~ ✅ **已修（R2 订正, 2026-10-05）**：`SKILL.md` 现 98 行，已达标，故「层图 L10 若转写"≤100 行"会固化一条未满足的规则」这一顾虑**不再成立** —— L10 可以直接写「≤100 行（G6，已达标）」。原坐标 `README:40` / `SKILL.md:133` / `manifest.yaml:72` 均已漂（`SKILL.md:133` 越界）。处置见 Q21 U-1（已关闭） |
| G-8 | 宏流程图 4 节点 7 处陈旧路径 | node_a2/a3/a5/a6：src/astro_best/*、scripts/*、best_standalone.py、best_query.ps1/sh、scripts/cloud_modelscope/ — 磁盘无一存在。处置见 Q14 |
| G-9 | 治理面数量口径不一（结论仍成立，坐标已订正） | `README.md` 逐文件边界表与 `architecture.md` 标题"12" vs `SKILL.md` 组件地图段"16" vs 正文实为 16。处置见 Q21 U-2 |
| G-10 | budget §3 登记簿过时 | 仍列两个图生成器 793/584 净行（实测 259/105，755fbe78 后未更新）。处置见 Q21 U-3 |

修法：以树清单为 SSOT 补四张表的行（新增行的"能力边界"列从文件自身 docstring 与 SKILL.md
摘录，治理规则列按同类行惯例），然后 `python ops/verify_tree_integrity.py`（默认模式）
复核；`test/unit/meta/test_coverage_matrix.py` 等既有门禁不得红；U-1~U-4 与 G-7~G-10
同批处置（Q21）。

---

## 4. 分层架构图统一模板（每张层图的 9 类结构件）

13 张层图共用同一骨架 （math_model 范式 P1-P9 的落地），差异只在数据表：

```
┌──────────────────────────────────────────────────────────────┐
│ 顶部横幅: 层名 + 定位一句话 + 主理/委派声明 (画布级)            │
├──────┬───────────────────────────────────────────────────────┤
│ 左   │  阶段容器① (虚线泳道)                                   │
│ 徽   │   主引擎卡 + N 张模块卡 (网格)                           │
│ 章   ├───────────────────────────────────────────────────────┤
│ 列   │  阶段容器② ...                                         │
│      │  ...                                                   │
│      ├───────────────────────────────────────────────────────┤
│      │  能力边界卡: 做什么 / 不做什么 / 委派给谁 / 失败语义      │
│      ├───────────────────────────────────────────────────────┤
│      │  口径表: 阈值·单位·预算数值 (行内注释标源码出处)          │
│      ├───────────────────────────────────────────────────────┤
│      │  内循环盒: 该层反馈环 (虚线弯箭) + 外框返回走线           │
├──────┴───────────────────────────────────────────────────────┤
│ 右阶段标签列 (与左徽章语义错位互补)                             │
└──────────────────────────────────────────────────────────────┘
```

数据表 schema （每层一个 `layers/layer_<id>.py`，纯数据无逻辑）：

```python
LAYER = {
    "id": "evals",                      # 产物名 astro-best-layer-evals.drawio
    "canvas": (4400, 3450),             # 宽固定 4400, 高由网格函数计算后声明 (Q12)
    "thin": False,                      # True = 薄层: 单段紧凑图, 省徽章/标签列 (L11-L13)
    "banner": "...",                    # 顶部横幅 HTML
    "columns": 4,                       # 网格列数 (3/4/6)
    "badges": [...],                    # 左徽章文案 (逐阶段)
    "labels": [...],                    # 右阶段标签 (逐阶段)
    "sections": [...],                  # 阶段容器: (id, 标题)
    "cards": [...],                     # (section_id, 节点 id, 列, 行, 色键, HTML[, 高覆盖])
    "engine": (section_id, HTML),       # 主引擎卡 (P4)
    "boundary": HTML,                   # 能力边界卡 (P6; 来源沉默时写"文档未载明, 待补", Q20)
    "units": HTML,                      # 口径表 (P5; 只收有文档出身的数值, Q18; weights 豁免)
    "loop": {"stations": [...], "edges": [...]},   # 内循环 (P7)
    "edges": [...],                     # 跨阶段连线 (与宏流程图同格式)
}
```

生成器 `gen_best_layers.py` 据表算坐标（网格函数 `grid_x(col)`/`grid_w(cols)`/卡高按内容
行数机械计算），**顺序与宏图严格同构（Q13）：save_clean 落盘 → 逐产物 verify_drawio_security
+ Emoji + AABB 碰撞审计 → 不过不渲染、exit 1**。为满足 N2 漂移闸门的子进程 import 模式，
生成器暴露 `build_layer(layer_id, out_dir)` 与 `build_summary(out_dir)` 两个纯函数
（与既有"import 生成器调 build()"约定一致，diagrams README §4），输出目录参数化
（ASTRO_BEST_DIAGRAM_DIR 环境变量优先，未设回落 docs/diagrams/）。

---

## 5. 十三张层图设计规格

### L1 `src/` 实现层 — 阶段主线 6 段

| 阶段 | 徽章 | 主卡内容 （转写源）|
|---|---|---|
| ① 接入面 | 客户端族 | `client.BestAuth/BestClient` （两阶段异步）、`pybest.Best` 单类、`query.BestQuery` 构造器、`lightcurve`、`crossmatch` （proximity 批量）|
| ② 协议引擎 | 权威协议 | `protocol` （表单键集/CSV 解析/软 404/名称解算/重试）、`protocol_catalog_tables`、`csv_safety` （负数放行）|
| ③ 下载栈 | 后台下载 | `downloader` + `download_manager/progress/hooks/precise/region/sqlid/task_log` （hook ask 纪律）+ `download_artifacts`|
| ④ 编排门禁 | 五状态机 | `core/pipeline` （AstroBestPipeline）、`core/source_postprocess`、`QualityGate` （fail-closed）|
| ⑤ 交付身份 | 产物血缘 | `serialization`、`best_export`、`models/*`、`provenance` （astro-envelope-v1）、`auth/nadc_oauth`、`auth/session`|
| ⑥ 工具适配 | 对外工具面 | `ai_tools` （ToolBox 7 原子）、`tap/*` （IVOA TAP 1.1 **9 个文件**：__init__/adql/client/executor/formats/jobs/response/service/uws_service）、`scripts/*` 入口 |

能力边界卡：in-scope 八项 （SKILL.md）不委派；out-scope 两项 （通用检索→astro-catalog、
清洗→astro-clean）；"BEST 自身数据查询/批量匹配仍归本 skill"。
口径表：净代码行 ≤400 （client.py 553 已登记例外，budget §3.2）；rows=1000/max_rows=50000、
rate_limit=3.0s、min_snr≥5.0/fwhm≤5.0/class_star≥0.8、SHA-256。
内循环：GATE 失败 → hook ask/闭环走廊 → 参数调整重执行 （转写 node_e6）。

### L2 `evals/` 质量评审层 — 阶段主线 5 段

① 场景装载 （`test-scenarios.yaml` 24 场景 SSOT，禁再分叉；`paths.py` 路径/YAML 装载中枢 —
eval_runner/case_executor/probes 三方共用以防互相相对导入；`cases/` 25 个用例 YAML 按 README
六分组：门禁行为 001-004 / 主理能力场景 005-007 / 字段契约 008-011 / 门禁边界 012-013 /
算法 014-016 / 下载栈与工具面 017-025）→ ② 行为探针
（`probes.py`/`probe_support.py` 零外网，`Session.request` 守卫实证）→ ③ 用例真实执行
（`case_executor.py` 四类执行当 gate/algorithm/scope/field，EVAL-10 禁 hasattr 假校；actual
由软 404 判定器产出）→ ④ 六审计器 （`audit/__init__.py`:
references 白盒五要素/knowledge schema/templates 键位/contracts 交叉引用/static entry/tests
有效性，每器附反证夹具）→ ⑤ 五维加权评分 （`eval_runner.py` **428 行** + `scoring-rubric.yaml`,
权重和=1.0, `measured` 语义）。

能力边界卡：**单模式不得宣布通过 （规则 10）**: audit/behavior 单模式相应维度记 0.0 报
NOT_MEASURED；禁 fail-open；探针零外网。
口径表：pass_score 0.9 > WARN 0.85; docstring 100% （260/260）；24 场景/25 用例；seed=42。
（739 passed/24 skipped 为 pytest 活数，按 Q18 不进口径表。）
内循环：评审 → 缺陷修复 → 复评 （知识飞轮入口）。
主引擎卡：`eval_runner.py` （各维度共用的 measured 加权内核）。

### L3 `test/` 能力回归层 — 阶段主线 5 段

① 配置与夹具 （`conftest.py` fail-closed spec 解析 + `fixtures/mock_*`）→ ② 单元域
（unit/ 各能力域目录，按 README 表；全树 68 个 test_*.py）→ ③ 集成链 （integration/ 10 个
文件：7 条能力链 query/data_semantics/server_count/soft404/name_resolution/crossmatch/
lightcurve + download_feature_integration + pipeline + release_regressions）→
④ 元测试门禁 （meta/ 11 个：覆盖矩阵/module path/图示 SSOT/环境锁/eval 维度/台账/冒烟/
星表登记 live/phase4 wiring/修复回归/rag domain boost）→ ⑤ live 受控 （live/ 3 个，
BEST_LIVE=1 预算）。

能力边界卡：禁 mock `__init__` （Q-11/12）；禁 `assert True`/零断言 （审计器检出）；
零真实网络 （除 live 门控）；新能力不破坏旧能力。
口径表：单测 <1.0s；本地样本 <100 （G8）；seed=42。（pytest 通过数按 Q18 不进门。）
内循环：RED （改坏就红的定向断言）→ GREEN → REFACTOR （audit_round 三文件的形态）。

### L4 `contracts/` I/O 契约层 — 阶段主线 5 段

① 双态信封 （`envelope.contract.yaml` data/decision）→ ② 输入输出 （`input`/`output`,
后者为 schema 索引，事实标准是 `src/provenance.build_envelope`）→ ③ 字段级 （`fields/`
四件：data/status/sql/token）→ ④ 阶段与血缘 （`pipeline-stage`/`provenance`,
completeness_gate）→ ⑤ 错误码 （`error-codes`: BEST_1001~1099，软 404 显式失败）+
`io-contract.md` 人类面孔 + `oauth.contract.yaml` （G-1 补入）。

能力边界卡：契约↔实现双向一致；`module:` 路径必须可导入且符号存在 （规则 9, fail-closed）；
input.contract 已标 legacy 勿当现输入面。
口径表：astro-envelope-v1; data_hash SHA-256; completeness_gate=1.0；错误码段 1001-1099。
内循环：契约变更 → module path 门禁 → 覆盖矩阵登记 （规则 8/9 联动）。

### L5 `templates/` 模板层 — 阶段主线 4 段

① 配置模板 （`best-config.yaml` 键收 defaults，去 BOM）→ ② 生成物配置/报告
（`gen_config_template.yaml`/`report_template.yaml`）→ ③ 用例准备 （`gen_case_prep_sql/token`）
→ ④ 结果字段 （`gen_result_field_data/status`/`gen_result_summary`/`gen_report_appendix`）。

能力边界卡：每个模板文件头声明唯一消费者；无代码消费者必须显式声明 （历史生成物，
生成器已不在树）；evals templates 审计器盯键位。
口径表：键集合 = defaults 子集（锚点：`test/unit/meta/test_phase4_wiring.py::Q-31`，Q20）；
无版本号标记。
内循环：模板 → 实例化 → evals 审计 → 修正。

### L6 `references/` 白盒文档内容层 — 阶段主线 5 段

① 算法白盒 （`ALGORITHM-SPEC.md` G7 五要素，§4 OAuth/§5 proximity/§6 TAP/§7 工具面）
→ ② 领域指南 （`best-database-guide.md`/`photometric-systems.md` 19 测光系统/8 个
Well-Calibrated 表）→ ③ 站点实测 （`site-endpoints-and-interactions.md` 2026-09-30 深潜）
→ ④ 使用向 playbook （`download-playbook.md`/`data-formats.md` G-2 补入）→ ⑤ 发现与兼容
（`llms.txt`/`pybest-api-reference.md`/`fallback-protocols.md`/`tools.schema.json`/
`skills-spec.local.yaml`）。

能力边界卡：**文档分层铁律**: references=智能体怎么用；rag/knowledge=结构化规则与引文，
两者不混放 （引文下沉 citations.yaml）；唯一白盒出处。
口径表：引文 9 verified / 2 unverified （DOI 经 Crossref）；工具 schema 7 原子工具。
内循环：站点行为变化 → 文档更新 → evals references 审计 → 引用核验。

### L7 `rag/` 知识检索层 — 阶段主线 5 段

① 检索执行器 （`astro_rag.py` BM25+词桶+RRF, DOMAIN_BOOST 提权）→ ② 最佳实践
（`best_practices.yaml`）→ ③ 引文库 （`citations.yaml`）→ ④ 领域规则
（`domain_rules.yaml`, VALIDATE/GATE 态咨询）→ ⑤ 已知问题与经验 （`known_issues.yaml`
degradation 加载 / `lessons_learned.yaml` 每次任务回写）。

能力边界卡：检索失败不阻断主链 （降级 WARN）；verified 才可静默引用；全树唯一 RAG
（BestRAGEngine 已删，禁第二实现）。
口径表：k1=1.5/b=0.75; top-k 默认 3; 9+2 引文状态。
内循环：任务经验 → lessons_learned 回写 → 检索增强 → 下一轮判定 （知识飞轮）。

### L8 `static/` 提示词静态规则层 — 阶段主线 4 段

① always_load 三件 （`stance.md`/`workflow.md`/`output-format.md`）→ ② algo_mode 片段
（`best_auth_mode.yaml`/`best_two_phase.yaml`/`two_stage_async_mode.yaml`）→ ③ data_source
片段 （`best_catalogs.md`/`nadc_endpoints.md`）→ ④ target_type 片段 （`best_ttype.md`/
`photometry_region.md`/`standard_star.md`）。

能力边界卡：会话注入 vs 按需路由 （manifest axes）；algo_mode entry 符号须可 resolve;
与 client/protocol 联动守护。
口径表：always_load 含 README.md; on_demand 五类片段。
内循环：规则 ↔ 代码联动测试 → 片段更新。

### L9 `ops/` 运维入口层 — 阶段主线 5 段

① 运维 CLI （`astro_best_cli.py` doctor/rag/log/config/refs/oauth/download, `_safe_path` 锚定）
→ ② 树门禁 （`verify_tree_integrity.py` 默认比对/--write 重写/--diff 集合差；排除列表含
`.workbuddy*/`（Q14 增补）与 `.worktrees/`（2026-10-06 增补））→ ③ 登记辅助
（`register_skill.py` 只打印不写）。
（2026-10-06 起本仓**不再有** MCP 工具面与云端规格入口：原 ③ MCP 传输层
`best_mcp_server.py` 与 ⑤ `cloud_modelscope/dispatch.py` 已整体移除，业务面只经
`src/ai_tools.ToolBox` 直调或 function-calling 暴露；故本走廊与下方口径表不再有
selftest 与 G8 云端规格两项。）

能力边界卡：路径调用零 import；零网络零凭据；成功退出码必须 0 （Q-19）；业务在 src/ai_tools。
口径表：doctor <1.0s。
内循环：doctor 自检 → 缺陷 → 修复 → 复检。

### L10 根目录文件层 — 阶段主线 4 段

① 必读入口链 （SKILL.md **98 行（G6 ≤100 已达标，U-1 已关闭）** →
README 逐文件边界+树 SSOT → manifest.yaml 加载地图 → architecture.md 五状态机+
**12 横切治理面 + 4 附加结构治理面 = 16（U-2 统一口径后）**）→ ② 声明面 （pipeline.yaml tool
符号须可 resolve / environment.yaml 双向锁 / pyproject.toml 仅工具配置）→ ③ 工程入口
（Makefile **16 个 target**；本机无 make，命令一律 python 直调，U-4）→ ④ 分发边界
（.gitignore / .env.example 双向一致 Q-16 / CHANGELOG.md local-only）。

能力边界卡：SKILL.md 首步必读 README；禁版本号 （规则 3）；树块仅 --write 可改；
structure 变更需批准。
口径表：治理规则 10 条 / SKILL 铁律 6 条 / 门禁 2 项 （http_status==200, checksum==True）。
内循环：manifest ↔ README ↔ tree 三方一致门禁。

### L11 `agents/` Persona 层 — 单段紧凑图

① 角色定义 （`openai.yaml` AI 角色与决策 Prompt）→ ② 逐状态对应 （architecture.md 五状态机）
→ ③ 工作流编排 （11-closed-loop 联动）。能力边界卡：内容编辑自由；与 architecture.md 表述
联动。口径表：always_load 注入；决策信封 needs_review 三态。
（来源未载明处按 Q20 写"文档未载明，待补"。）

### L12 `examples/` 人读示例层 — 单段紧凑图

① 库 API 演示 （`example_skill_usage.py` BestSkillClient/BestCrossMatch/BestClient）→
② 端到端快速上手 （`example_quickstart_pybest.py` 查询→下载最小闭环）。
能力边界卡：随 API 演进更新；`test/examples/` 离线桩执行防腐烂 （零真实网络，docstring
预期输出断言）。内循环：API 变更 → 示例更新 → 离线执行门禁。

### L13 `weights/` 权重声明层 — 单段紧凑图

① 声明式立场 （`README.md` 无二进制权重）。能力边界卡：纯规则/协议 skill，保持声明式，
禁引入二进制权重。口径表：无 （本层无数值口径，**唯一 units_strip 豁免层**，N4 门禁持
豁免名单数据；边界卡不豁免 — 图示以边界卡为主体，薄层不硬凑口径表）。

---

## 6. 汇总图设计：`astro-best-layer-summary.drawio`

- **画布**: 宽 4400（与宏图同一视觉语言），**高由网格函数计算后声明，预计 3600~4000**
  （Q12：13 个层容器按依赖层级五行排布 + local-only 边界带；宏图的 3200 高度装不下，
  不再写死"同规格"）。
  行1 入口声明 （根目录/agents/static）→ 行2 实现与契约 （src/contracts/templates）→
  行3 回归与评审 （test/evals）→ 行4 知识规则 （references/rag）→ 行5 出口与外围
  （ops/examples/weights）；local-only 边界带置底 （docs/temp/best_data/.checkpoints/
  .progress/.logs + 委派越界 astro-catalog/astro-clean；docs/ 条目带"例外：docs/diagrams/
  源与脚本受跟踪"精确措辞，Q9）。
- **层容器内**：每层 3-5 张小卡 = 阶段徽章摘要 + 该层边界一句话 + 关键数值 （从层图转写，
  不发明；数值仅限 Q18 三类有出处来源）。
- **连线**: Q9 五类语义边 + 闭环回边 （外框轨道收口，与宏流程图 e_e6_a1 同范式）。
- **口径表**：全 skill 关键数值总表 （与宏流程图 FLOWCHART_UNITS_STRIP 同规则，标注出处）。
- **图例**：五类边 + 色键 + 虚线语义。

---

## 7. 落地计划（5 个 Phase，7 个原子提交）

| Phase | 内容 | 提交 | 出口验收 |
|---|---|---|---|
| A | **step 0 红灯处置**（Q14：`.workbuddy/` 移 temp/ + 树门禁排除项补 `.workbuddy*/` + 树门禁复绿）；G-1~G-6 文档表补齐；G-7~G-10 + U-1~U-4 同批处置（SKILL.md G-6 修剪或豁免登记、治理面口径统一、budget §3 修订、Makefile 口径修正）；宏图 7 处陈旧路径修 + 重生成（G-8）；抽 `diagram_style.py`/`diagram_audit.py`，旧生成器改 import（审计抽取范围按 Q5 修正）；两道门禁 glob→rglob；计划文档与治理债文档 `git add -f`（Q19） | `chore(phase10a): ...` | **树门禁复绿**；既有逐字节漂移闸门全绿（抽取无行为变化的机械证明）；pytest 全绿；ruff 双通道；覆盖矩阵不红；README 四表+evals 表与树一致 |
| B1 | `layers/` 数据表 ×4 （src/evals/test/contracts）+ `gen_best_layers.py` 骨架；**同提交更新 diagrams README §1/§3**（Q16） | `feat(phase10b1): ...` | 4 张层图生成 + 审计过 + git add -f |
| B2 | 数据表 ×5 （templates/references/rag/static/ops）；增量同步 §1/§3 | `feat(phase10b2): ...` | 同上 |
| B3 | 数据表 ×4 （根目录/agents/examples/weights）+ 薄层紧凑规则；增量同步 §1/§3 | `feat(phase10b3): ...` | 13 张层图齐 |
| C | 汇总图 `astro-best-layer-summary.drawio` （build_summary）；§1/§3 + §2 叙述 | `feat(phase10c): ...` | 14 产物齐 + 审计过 |
| D | 门禁扩展（N1-N8 进 `test/unit/meta/test_diagram_ssot.py`，漂移闸门 snippet 增加 gen_best_layers 子进程重生成）+ diagrams README §5 + 根 README 规则 5 实测口径 + governance-debt-plan §14 | `test(phase10d): ...` | 新增门禁 RED 证明后全绿 |
| E | 本地重渲 14 张图（PNG+PDF 为主，SVG 按需；不跟踪）+ 全量 18 门禁（`temp/final_gates_phase10.py`）+ `python evals/eval_runner.py --mode all` | `docs(phase10e): ...` | §8 清单全绿，present 交付 |

提交纪律：Conventional Commits；每 Phase 前 `git status` 确认无上一 Phase 残留；禁用裸
`git stash`（RED 证据用 `git stash push -- <自有文件>`）；文档同步随 Phase 增量（Q16），
禁止把 README 更新堆积到 Phase D。

---

## 8. 验收门禁（机械可判）

**既有 18 项必须不回归**（口径：`temp/final_gates_phase8.py` 的 17 条判定 + comment_audit
六类全 0；Phase 10 以 `temp/final_gates_phase10.py` 判定行数为准）：

| 组 | 项 |
|---|---|
| astro-best 本地（9） | ruff 双通道（全仓 + 显式 docs/diagrams 路径，绕过 extend-exclude）/ pytest 全量（基线 739 passed / 24 skipped）/ 覆盖矩阵 / module path / eval_runner 自测 / 图示定位门禁 / 树 SSOT 278 / evals --mode all 1.0000 |
| monorepo（5） | registry pytest / strength coherence / G1 ledger / routing coherence / astro skills |
| 单模式 eval（2） | audit 0.3000 FAILED 与 behavior 0.8000 FAILED 正确失败（规则 10 measured 语义） |
| 预算（1） | 400 净行仅 client.py 已登记例外 |
| 注释（1） | comment_audit 六类全 0 |

**开工前置**：树 SSOT 门禁当前 RED（Q14）— Phase A step 0 复绿前，"不回归"无基线。

**新增 8 项图示门禁**（进 `test/unit/meta/test_diagram_ssot.py`，与既有 3 类 6 函数结构兼容）：

| # | 门禁 | 判据 |
|---|---|---|
| N1 | 14 产物齐全且受跟踪 | `layers/` rglob 递归后每个 `.py`/`.drawio` 都在 `git ls-files`（rglob 升级后；git ls-files 本身递归，basename 比对仍成立）|
| N2 | 逐字节可复现 | 子进程 import `gen_best_layers` 调 build_layer/build_summary 重生成 14 个 `.drawio`，与受跟踪产物 LF 归一后一致（漂移闸门 snippet 扩展，构建库缺失/超时 skip 不判失败 — 与既有行为一致）|
| N3 | 每层图含能力边界 | 每张 `astro-best-layer-*.drawio` 必含边界卡节点（id 前缀 `boundary_`）与"委派"措辞；weights 不豁免 |
| N4 | 每层图含口径表 | 每张层图必含口径条（id `units_strip`）；weights 按门禁内置豁免名单（数据，非硬编码分支）|
| N5 | 禁旧措辞/版本号 | FORBIDDEN_LITERAL（17 串）+ FORBIDDEN_PATTERN（3 正则）覆盖扩到 14 产物 |
| N6 | 定位文案在场 | 每张层图必含 "BEST 数据源主理"与其层目录 token（如 `evals/`）|
| N7 | 层图↔README token 一致 | 每张层图模块 token 集合 = README 该目录表行 token 集合（区间行归一化 + 白名单，Q15）|
| N8 | 图示路径真实性 | 所有受跟踪 .drawio 内路径 token 必须存在于磁盘/树（白名单：URL/外部绝对路径/env/目录级 token，Q14） |

**文档同步**: `docs/diagrams/README.md` §1 表（14 新产物 + git 列）/ §2 叙述（十三层 +
汇总）/ §3 脚本表（gen_best_layers/diagram_style/diagram_audit + layers/ 分组行枚举 13 个
数据表文件名 — 索引门禁逐文件名比对，Q6）/ §5 渲染状态（随 Phase E 实测刷新）；根 README
规则 5 例外描述按实测更新；`docs/architecture/governance-debt-plan.md` §14 记录本轮
（含 math_model 研读结论、迁移/不迁移裁定、第 10 轮核验发现与 Q11-Q21 裁定）。

---

## 9. 风险与回退

| 风险 | 概率 | 回退 |
|---|---|---|
| **树 SSOT 门禁当前 RED**（.workbuddy/ 三条目） | **已发生** | Phase A step 0：移 temp/ + 树门禁排除项对齐 .gitignore；用户否决则 --write 登记（需单独批准）。不拆掉此灯，后续"不回归"验收全无效 |
| 共享模块抽取改变既有产物字节 | 中 | 漂移闸门红 → 立即回退第三份副本方案，旧生成器还原（Q5 修正：审计抽取只动 macro + check_macro_collisions，arch 无内联审计不动）|
| 13 张图坐标碰撞/越界 | 中 | 生成器前置 `diagram_audit`（不过不渲染）；网格函数单测钉死列距/卡宽常数；卡高按内容机械计算 + AABB 兜底（Q12）|
| `git add` 静默跳过 layers/ 新文件 | 高 （已知故障模式）| `git add -f` + N1 门禁（rglob）双保险；计划/治理债两文档同批 force-add（Q19）|
| N7/N8 门禁误伤（区间行/聚合路径/外部路径） | 中 | 白名单数据化（区间行归一化、URL/盘符/~/ 模式）；门禁自带反证夹具（每类白名单一条必须放行的样本）|
| 新 `.py` 超 400 净行 | 中 | 生成器按 build_layer/build_summary 拆函数族；数据表一层一文件天然小；budget §2 覆盖范围已确认 |
| 渲染耗时/磁盘（40-120MB，Q17 修正）| 低 | PNG+PDF 为主 SVG 按需；渲染失败不阻断门禁；本机无 make，渲染走 python 直调 draw.io CLI |
| 外部构建库/渲染器依赖（drawio_builder 不在仓内、draw.io 桌面端） | 中（既有前提）| env 变量优先（ASTRO_BEST_DRAWIO_BUILDER_DIR/ASTRO_BEST_DRAWIO_EXE/ASTRO_BEST_DIAGRAM_DIR，diagrams README §4 已文档化）；N2 门禁对构建库缺失 skip — 与既有漂移闸门同口径，不因新图加严 |
| README 表修订引发覆盖矩阵红 | 低 | 修订只补"在树文件"的行，不动 anchor/status 列语义；Phase A 出口复跑覆盖矩阵 |

---

## 10. 苏格拉底记录（留档）

**第 9 轮十问**（全部由我裁定，用户预授权"裁定也由你定"）：Q1 十三层+汇总 / Q2 三视角互补
既有图零改动 / Q3 迁 9 项结构范式不迁配色版式画布 / Q4 新图网格布局旧图坐标不动 / Q5 抽共享
模块以逐字节闸门为证、可回退 / Q6 layers/ 子目录 + 门禁 rglob 化（修真实缺口）/ Q7 渲染
产物本地化 / Q8 逐字转写禁概括 / Q9 五类边+闭环回边 / Q10 §8 门禁全绿才算完。

**第 10 轮十一问**（Q11-Q21，基于三轮并行事实核验 + 主窗口自查，证据见 §11）：
Q11 门禁计数改机械定义（17 判定 + comment_audit，终验以 phase10 脚本行数为准）/
Q12 画布宽固定 4400 高按网格计算后声明，卡宽随列数、卡高按内容机械计算 /
Q13 落盘-审计-渲染顺序与宏图实际同构（先落盘再审、不过不渲染），修正原"不过不落盘"表述 /
Q14 "既有图零改动"精确化为零结构改动：宏图 7 处陈旧路径按 Phase 8 先例修 + 新增 N8 路径
真实性门禁；树门禁红灯 step 0 处置（.workbuddy 移 temp/ + 排除项对齐 .gitignore）/
Q15 新增 N7 层图↔README token 一致门禁，堵死图静默过期 /
Q16 文档同步增量化（随 Phase 同提交），Phase D 只留门禁与 §14 /
Q17 渲染估算按实测基线修正（单图≈16.5MB），层图 PNG+PDF 为主 /
Q18 口径表只收有文档出身的数值，活数禁入（739 passed 移出 L3 口径表）；weights 唯一
units 豁免且名单数据化 /
Q19 计划文档与治理债文档 Phase A force-add，对齐 implementation-plan 跟踪惯例 /
Q20 来源沉默写"文档未载明，待补"禁发明；历史轮次引用锚点化（Q-31→test_phase4_wiring.py::Q-31）/
Q21 四笔计划外欠账同批清：U-1 SKILL.md 违反 G6（**已修：137→98 行达标，欠账关闭**）、U-2 治理面
12/16 口径统一、U-3 budget §3 登记簿修订、U-4 Makefile 16 目标 + 本机无 make + Phase E
命令改 python 直调。

**待用户否决项**：层数粒度（Q1）、共享模块抽取（Q5）、薄层紧凑图形态（L11-L13）、
N7/N8 两道新门禁（Q14/Q15）、SKILL.md 修剪（Q21 U-1）、`.workbuddy/` 移动（Q14 step 0）、
计划/治理债文档 force-add（Q19）。
批准后从 Phase A 开工；任一单项被否决，只回退该项，不影响其余 Phase 排序。

---

## 11. 第 10 轮事实核验记录（留档）

核验方式：三个只读子代理并行（A 图示目录与生成器 / B 门禁与测试体系 / C 文档缺口）+ 主窗口
自查（目录盘点、树清单逐行比对、磁盘实测、git 跟踪实况、门禁脚本实跑）。全程未改任何源文件。

### 11.1 核验 A：图示目录与生成器

| 论断 | 判定 | 证据 / 修正 |
|---|---|---|
| 图示目录 7 个脚本 | 证实 | audit_local/check_macro_collisions/export_diagram/drawio_io/gen_astro_best_architecture/gen_best_macro_flowchart/layout_data |
| 既有两张架构图 | 证实 | macro-flowchart.drawio（80,210 B）+ legacy-architecture.drawio（72,395 B，4 页）；本地渲染 12 个（5PNG+5SVG+2PDF）未跟踪 |
| diagrams README §1/§2/§3/§5 存在 | 证实 | :7-22 / :26-42 / :46-56 / :65-70；§5:71 禁裸 doc.save 成文 |
| 容器 x=200、卡局部 x=55、卡宽 570、列距 94 | 基本证实 | 6 列网格 55/719/1383/2047/2711/3375（步长 664）；s4 星表段有 710/85 变体，层图不引入 |
| FLOWCHART_PALETTE 十键 | **证伪** | 实为 **11 键**（+title/banner/neutral/muted 等），已修正 Q3 |
| 宏图 main() 跑 verify_drawio_security | 证实 | gen:360-361,487，不过 return 1；**未调 check_drawio**（math_model 才调） |
| 宏图顺序"先审后落盘" | **证伪** | 实际 save_clean 落盘 → 审计 → 不渲染；审计拦渲染不拦落盘 → Q13 裁定 |
| math_model 508 行、P1-P9 范式逐项 | 证实 | 508 行 38,659B；范式条目逐条命中（:95-470）；main() verify+check exit 1（:489-502） |
| "温度°C/浓度kg/kg"出自 math_model | **证伪** | 出自数模国赛 A 题 panorama 生成器（governance:542；layout_data:89-90 自述）→ §2 已改 |
| drawio_io.save_clean 行为 | 证实 | doc.save→剥 mxfile 根 4 属性→CRLF→LF→write_bytes；两生成器 import；Phase 9（df7738ee）引入 |
| git ls-files docs/diagrams/ = 10 | 证实 | README + 2 drawio + 7 脚本；.gitignore docs/ → 新文件须 git add -f |
| Q5"两生成器各持一份审计代码" | **证伪** | arch 无内联审计（在 audit_local.py）；macro 内联审计与 check_macro_collisions.py 重复 → 抽取范围修正 |
| 图示铁律出自 README 治理规则 | **部分证伪** | 成文于 diagrams README §5 + 漂移闸门测试；SKILL.md 六铁律未列 → §3.1 归属修正 |

### 11.2 核验 B：门禁与测试体系

| 论断 | 判定 | 证据 / 修正 |
|---|---|---|
| 两道门禁只查顶层（Q6） | 证实 | test_diagram_ssot.py:160 `glob("*.py")`、:186-187 `iterdir()`；git ls-files 侧本身递归 |
| 图示定位门禁 8 项 | 证实 | 参数化×2 + 参数化×2 + 星表数 + 索引 + 跟踪 + 漂移 = 8 个收集项 |
| 漂移闸门机制 | 证实 | :198-260：子进程 import 两生成器 + save_clean 到 tmp + LF 归一二进制比对 + 安全 lint 双侧；构建库缺失/超时 skip |
| pytest 739 passed / 24 skipped | 证实 | 全量实测 14.07s；--collect-only 763 项吻合 |
| evals --mode all 1.0000；单模式 0.3000/0.8000 FAILED | 证实 | 实测 docstring 100%（260/260）、场景 25/25、用例 25/25、六审计器 0 失败 |
| meta/ 11 个文件 | 证实 | 与树 L482-492 一致 |
| FORBIDDEN_LITERAL 17 串 + 3 版本正则 | 证实 | test_diagram_ssot.py:55-82；另 evals VERSION_MARKER_RE（audit:42-46） |
| "既有 18 项全绿" | **部分证伪** | 17 条脚本判定 + comment_audit 可追溯；但**树 SSOT 门禁实测 RED**（实际 281/清单 278，.workbuddy/ 三条目）→ Q11/Q14 |
| L10 "Makefile 12 目标" | **证伪** | 实为 16 个 target；本机无 make；`make eval --mode all` 三重错误 → Q21 U-4 |
| budget §3 仅 client.py 超限 | 证实 | count_code_lines 实测仅 client.py 553；但登记簿仍列已拆完的 793/584 → G-10/U-3 |
| monorepo 五门禁 | 证实 | final_gates_phase8.py:41-51；ledger locked tests=956 等在 APPROVED_DEFICITS 白名单内 |
| ruff 双通道 | 证实 | 两次 ruff check（全仓 + 显式 docs/diagrams 三脚本绕过 extend-exclude），非 check+format |

### 11.3 核验 C：文档缺口（G-1~G-6 详见 §3.2）

| 论断 | 判定 | 证据 |
|---|---|---|
| 树清单 278 条目 | 证实 | README L255-532 共 278 行（50 目录 + 228 文件）；门禁输出"清单 278" |
| G-1 oauth.contract.yaml | 证实 | 磁盘+树 L271+architecture.md:93；表缺行 |
| G-2 data-formats.md | 证实 | 磁盘+树 L333；表缺行 |
| G-3 src 缺 10 文件 + tap 9 | 证实 | 10 个全在树不在表；**另缺 scripts/__init__.py L358（第 11 个）**；src 磁盘 51 文件 vs 表覆盖 40 |
| G-4 test 表偏差 | 证实且更大 | 9 处计数 + 2 空占位行 + 1 幽灵行 + 7 个 chain 缺行 + serialization/upstream 两行缺失（crossmatch 2→1、audit_round 2→3 为第 10 轮新发现）；test 全树 68 个 test_*.py |
| G-5 约 270 KB | 证实且更严重 | 实测受跟踪 298,632 B≈292 KB；渲染 30,278,056 B≈28.9MB；governance:559 另写 280 KB — 三处不一 |
| G-6 evals 表缺 4 文件 | 证实 | probes/probe_support/case_runner/paths 在树 L305-311，表无行 |
| ~~G-7 SKILL.md 137 行违反 G6~~ | **已推翻（R2, 2026-10-05）** | 原结论建立在 `ReadAllLines=137`；实测 `SKILL.md` 现 **98 行**、G6 ≤100 **已达标**（`CHANGELOG.md` 有 137→98 修复记录），故本条不再是活跃缺陷。原坐标 `README:40`/`SKILL:133`/`manifest:72` 均已漂 |
| architecture.md 五状态机 + 失败隔离/门禁表 | 证实 | `architecture.md` 的状态机段与门禁表段 |
| 16 治理面 = 12+4 | 部分证实 | §2 的 12 + §2.1 的 4；但标题与 `README.md` 逐文件边界表写"12"、`SKILL.md` 组件地图段写"16" → G-9（坐标已订正） |
| governance §14 空闲 | 证实 | 末节 §13 止于 L561 |
| verify_tree_integrity --write 性质 | 修正 | --write 是直接重写不做校验（破坏性）；复核用默认模式；docs/ 为 opaque 单条目 |

### 11.4 主窗口自查补充

| 项 | 结论 |
|---|---|
| evals/ 实际结构 | cases/ 25 个用例 YAML（README 六分组）+ paths.py（装载中枢）— 原计划 L2 转写遗漏，已补 |
| 宏图文案陈旧路径 | node_a2/a3/a5/a6 共 7 处（src/astro_best/*、scripts/*、best_standalone.py、best_query.ps1/sh、scripts/cloud_modelscope/）磁盘无一存在；legacy 0 命中 → G-8/Q14 |
| 规则编号引用 | 计划原文"规则 4 内容编辑自由"有误：README 规则 4 是文件树 SSOT，内容编辑自由属规则 1 权限矩阵 → 已改 |
| eval_runner.py 行数 | 实测 428 行（原计划 L2 写 381）→ 已修正 |
| 路由与入口 | astro-route.ps1 实测 PRIMARY → astro-best/SKILL.md，与本任务一致 |
| git 仓库根 | 在 <SKILLS_ROOT>（monorepo）；docs/ ignore，15 文件 force-add；计划文档与治理债文档未跟踪 → Q19 |
| field-journal | CLAUDE.md 规则 5 的回写目标 field-journal/_index.md 不存在（新建目录属规则 1 结构变更）→ 列入待批准项 |
