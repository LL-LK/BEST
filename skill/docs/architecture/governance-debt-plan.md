# astro-best 治理债清偿与能力补全实施计划（苏格拉底对齐版）

> 状态：**已完成**（Phase 0~7 全部落地并提交；13 项门禁全绿；详见 §10 与 §11）。
> 落点：`docs/architecture/governance-debt-plan.md`（`docs/` 自 2026-09-28 起入版本控制，
> 本文档随仓分发；本行原写「`docs/` 被 `.gitignore` 忽略，本文档为本地规划工件，
> 不进 git」，与 git 事实矛盾——同 `governance-debt-plan.md` §12.2 遗留观察项 4
> 记的是 README 规则 5 的同一处矛盾，两处一起更正）。
> 规划依据：`docs/architecture/file-size-budget.md` §6/§6.1/§7/§8/§9 + 本轮逐项复核取得的实证（见 §2，全部带 `文件:行`）。
>
> **执行进展记于本文档 §10**（每 Phase 的提交号、验收证据、以及执行中发现的计划外问题）；
> **终验结果与遗留观察项记于 §11**。

---

## 1. 苏格拉底对齐记录（10 轮裁定）

| # | 提问 | 用户裁定 |
|---|---|---|
| 1 | 本轮交付什么？ | **只产出计划文档，暂不动代码** |
| 2 | 38 条债务与 evals/test 覆盖盲区，谁是根因？ | **先 evals/test 覆盖 + contracts**（债务修复效果当前无法被检测到） |
| 3 | E1 要跨出 astro-best 边界改 monorepo 根生成器，如何处理？ | **授权跨仓修改生成器** |
| 4 | evals/test 覆盖的验收口径？ | **关键路径全覆盖 + 行覆盖不低于现基线** |
| 5 | 计划文档落盘位置？ | **`docs/architecture/`** |
| 6 | 同一授权是否适用于 MASTER-ROUTING 路由缺陷？ | **授权跨仓修改（与 E1 同级）** |
| 7 | §6/§6.1 的 34 条债务本轮纳入哪些组？ | **A / B / C+G / D+E+F 四组全纳入**（只定 Phase 归属，不动代码） |
| 8 | 「无全覆盖」如何变成可判定的？ | **能力矩阵 SSOT + meta 测试校验** |
| 9 | contracts「能力不完整」的修法？ | **扩 spec 切片 + 加 module 路径真实性断言** |
| 10 | templates/examples 的处置？ | **修死路径+重命名统一前缀 / examples 纳入测试执行 / 每个模板声明唯一消费者** |

---

## 2. 问题全景与实证

### 2.1 大仓路由缺陷 —— 根因是「强度 SSOT 漂移」，不是一处笔误

**表面症状**（用户指出，**均已随 Phase 0 修正**）：

- `docs/routing/MASTER-ROUTING.md`「星表查询」行 — 曾把 `astro-best` 列为 `legacy_deprecated`；现该行支持 skill 列即 `astro-best`，无 legacy 标记
- `docs/routing/MASTER-ROUTING.md`「BEST 数据」行 — 曾以 `astro-catalog` 为 PRIMARY（redirect: astro-best → S4）；现 PRIMARY 已是 `astro-best`，支持列为 `astro-catalog, astro-lightcurve`
- `docs/routing/routing.md` 上述两行 — 同一缺陷的第二份副本，现已同步

**根因（本轮新查实）——四份强度 SSOT 互相矛盾：✅ 已修（Phase 0，提交 `8327a21d`，见 §10）**

> **订正（R2，2026-10-05）**：下表左列记的是**发现当时**的取值，四份 SSOT 现已全部对齐 S2
> （本文件 §10 已登记该提交）。原表的行号坐标已随父仓后续变更漂移，故改为内容锚点。
> 跨仓坐标指父仓 `<WORKSPACE>

| SSOT（跨仓，父仓 `<SKILLS_ROOT>\`） | 发现当时的记载 | 现值（2026-10-05 逐行复核） |
|---|---|---|
| `_shared/astro-skill-registry.yaml` astro-best 条目 | `strength: S4` / `strength_label: legacy` / `pipeline_role: legacy` / `standalone: false` | `S2` / `specialist` / `specialist` / `true`（条目上方已有 2026-10 收敛注释，明写「旧值 S4/legacy/standalone:false 与强度矩阵矛盾，已按 S2 对齐」） |
| `SKILL-INDEX.md` astro-best 行 | `S4`，`[Legacy 归档]` | `S2` + `✅`，描述含 `(PRIMARY; astro-best-sync 已合并下沉)` |
| `docs/system_architecture/SKILL-STRENGTH-MODEL.md`「当前分布」表 S2 行 | **`S2`** | `S2`（结论本就对，只是原行号已漂） |
| `docs/system_architecture/build.md` 强度矩阵 S2 行 | **`S2`**（Specialist） | `S2`，名单含 `astro-best`（本就准确） |
| 根 `SKILL.md` 采集行 | `S1/S2` | `S1/S2`（本就一致） |

即：registry 与 SKILL-INDEX 说 S4/Legacy，强度模型与 build 文档说 S2。`MASTER-ROUTING.md` 的 redirect 是 **registry 强度漂移的下游后果**——只改路由单元格不改 registry，下次任何按 registry 生成的产物都会把 S4 带回来。**该 redirect 已随 Phase 0 一并修正。**

**三条反向证据（证明 astro-best 不该是 Legacy）：**

1. `SKILL-STRENGTH-MODEL.md`「当前分布」表的 S4 行（9 个，含 `astro-best-sync`、**不含** astro-best）与 `build.md` 强度矩阵的 S4 行里**都没有** astro-best；真正的 S4 legacy 是 `astro-best-sync`（`build.md` 目录树里标 `# S4 legacy`、`_shared/astro-skill-registry.yaml` 的 `astro-best-sync` 条目带 `replacement: astro-best`）。
2. `SKILL-INDEX.md:76` 明确 `astro-best-sync → astro-best (合并下沉)`：astro-best 是**合并后的存活方**，把存活方标成归档方是方向性错误。
3. `MASTER-ROUTING.md:4-5` 的门槛规则是「PRIMARY 必须是 S0~S3」——astro-best 按强度模型是 S2，**本就够格做 PRIMARY**。
4. 工程质量侧证据：622 passed / 22 skipped、evals 25/25 场景 25/25 用例、MCP selftest 13/13、docstring 100.00%——与 S2「能独立完成专项子任务」定义相符，与 S4「不再作为新任务入口」不符。

**门禁盲区（这是缺陷能长期存在的真正原因）：**

- `_shared/skill-engine/scripts/verify-astro-skills.ps1:48,113,114` 只校验每个 SKILL.md **存在** `strength: S[0-4]` 与 `standalone: true|false` 两个字段，**不校验与 registry/INDEX 一致**。
- `_shared/skill-engine/scripts/verify-routing-coherence.ps1:112-114` 只校验 canonical skill 的 SKILL.md 存在、且 skill 名出现在 `routing.md` 正文里，**不校验 PRIMARY 指向与强度是否自洽**。

结论：**没有任何门禁能发现这次矛盾**。因此 Phase 0 改文件、Phase 1 补门禁，两者必须成对，否则三个月后必然复发。

**附带发现（同一簇，建议同 Phase 处理）：**

- `docs/system_architecture/build.md:471` 残留 `pybest-v0.3.2.6` 发布版本号，违反全仓禁版本号铁律（budget doc §7 的同源问题）。
- `SKILL-INDEX.md:53` 的 canonical 名是 `astro-catalog`，而本会话 skill 目录里登记的仍是 `astro-catalog-query`；物理目录已改名为 `astro-catalog`（`verify-routing-coherence.ps1:82` 要求 `astro-catalog/SKILL.md` 存在且当前通过）。这是**索引与运行期目录已一致、仅注册表层滞后**，属低风险，登记待核。

### 2.2 §6/§6.1 的 34 条已核实债务

清单与逐条影响见 `docs/architecture/file-size-budget.md` §6.1（行 439-500）。按「能否被现有测试发现」重排风险分级——**分级依据正是用户裁定的第 2 条（先补检测能力）**：

| 组 | 条数 | 内容 | 现有测试能否发现 | 风险级 |
|---|---|---|---|---|
| A | 5 | 脚本层会话泄漏 / 扩展名与内容不符 / 权限位 / 空导出 | 除 A5 外**全部不能**（`best_multiband_export`/`best_crossmatch_pipeline` 只有 import+callable 断言） | **P0** |
| B | 6 | 下载取消语义 / 终态错记 / 输出覆盖 / 续传不对称 / 断点键丢失 | 部分能（有 download_manager 用例，但取消终态无断言） | **P0** |
| C | 2 | RAG 领域加权死代码 / 版本号字样 | 不能（死代码无断言即无失败） | P1 |
| D | 5 | evals fail-open / 版本号模式盲区 / 审计器反证默认值 / docstring 维度范围 / 死常量 | **不能**——D1 恰是「审计可报满分而零行为证据」，会**掩盖**本轮要补的覆盖缺口 | **P0** |
| E | 10 | 生成器注释寿命 / 环境锁白名单 / 正则失真 / 空门禁 / 死夹具 / 弱断言 / 死代码 / 命名误导 / sys.path 泄漏 / 明文口令 | 部分能 | P1 |
| F | 3 | 图脚本硬编码绝对路径 / ruff 违规 / 过期路径 | 不能（`docs/` 在 ruff `extend-exclude`） | P2 |
| G | 3 | 模型 6 字段不填充 / 默认波段非法 / 路由硬编码 | 不能（字段停留默认值时无断言失败） | **P0** |

> 关键观察：**D1（audit 模式预置 rate=1.0）与 A/B/G 三组的不可检测性是同一件事的两面**——evals 现在能对未覆盖能力报满分。所以「先补覆盖」不是排序偏好，是清偿债务的前置条件。

### 2.3 E1 —— 生成器把版本号与注释一起回潮

- `<SKILLS_ROOT>\scripts\refactor\common.py:273` 与 `scripts/refactor/materialize_tests.py:34` 仍产出 `Master Plan v8.0` 字样。
- 受影响产物面：`contracts/`、`templates/`、`evals/cases/`、`test/unit/{contracts,meta}/test_gen_*`（6 个）。
- 后果有两条，都比字面量更严重：
  1. 下次重新物化会把 `Master Plan v8.0` **带回**已清净的文件（budget doc §7 行 526-531 已登记）；
  2. 本轮补的中文注释写在产物文件里，**注释寿命只有一次物化周期**——与「每个函数都有解释」的注释铁律直接冲突。
- 修法（用户已授权跨仓）：把注释模板**固化进生成器**（模板字符串 + 单元测试断言产物头部含中文注释），而不是继续在产物上手工补。

### 2.4 evals / test 覆盖盲区（实测）

**单元层缺口**

| 位置 | 现状 | 后果 |
|---|---|---|
| `src/scripts/best_multiband_export.py` | 仅 `test/unit/pipeline/test_core.py:141-146` 断言「可导入且 callable」 | **A2（`output_format="txt"` 写出 `.txt` 扩展名但内容是 JSON）正是这条盲区的直接产物** |
| `src/scripts/best_crossmatch_pipeline.py` | 同上，仅 import+callable（`test_core.py:149-154`） | A1（每次调用新建 `BestClient` 泄漏 session）无法被测出 |
| `src/query_builder.py` / `src/best_export.py` / `src/kb/__init__.py` | 无专属行为测试文件 | DSL 与导出层行为无回归网 |
| `src/__main__.py` | 仅 `test/integration/test_release_regressions.py:29-30` 覆盖 `_print_or_save`/`build_parser` | 6 个 CLI 子命令面大部分无行为断言 |

**evals 层缺口**（`evals/test-scenarios.yaml` 现有 24 个场景）

| 无场景覆盖的能力 | 证据 |
|---|---|
| `output.fmt` 的 csv / txt / json / votable / fits 五格式落盘与类型推断 | 24 个场景中无一涉及格式层；本轮新增的 `src/serialization.py` 与 52 项格式回归**只在 unit 层** |
| provenance / error-codes 契约 | 无场景 |
| TAP UWS 作业生命周期（create/phase/async action/range） | 仅 `tap_service` 场景，无 job 状态机场景 |
| 断点续传的跨进程恢复 | 有 `download_resume` 场景但仅进程内 |
| crossmatch / multiband_photometry 的 eval 行为抽查 | 有 `crossmatch`/`multiband_photometry` 场景，但 `derived_from` 未绑定到 `src.crossmatch`/`src.multiband_photometry` 的算法条目 |

**无覆盖率基线**：pytest 未配置 `--cov`，行覆盖**没有任何数字基线**，因此用户裁定 4 的「不低于现基线」当前无法验证。Phase 3 第一件事就是建立基线数字并写入矩阵文档。

### 2.5 templates / examples 失效

| 文件 | 问题 | 证据 |
|---|---|---|
| `templates/config_template.yaml` | **6 处 module 死路径**：`BestSkillClient→src.__init__`（真实 `src.core`）、`BestCrossMatchJob→src.__init__`（真实 `src.models`）、`BestCrossMatchResult→src.__init__`（真实 `src.models`）、`BestQueryResult→src.__init__`（真实 `src.models`，且本地 spec `references/skills-spec.local.yaml:47` 已写 `src.models`）、`AstroBestConfig→src.config`（真实 `src.scripts.config`）、`AstroBestPipeline→src.pipeline`（真实 `src.core.pipeline`） | 逐条比对 `src/` 真实定义位置 |
| `templates/gen_*.yaml`（6 个） | **零消费者**：仅被 evals TemplatesAuditor 计行数（README.md:184「模板层（被 evals 审计）」），无任何代码读取 | 全仓 grep 仅命中 `test_gen_ledger.py:71` 的行数目标 |
| `templates/best-config.yaml` | 唯一有真实消费者的模板（`test/unit/meta/test_phase4_wiring.py:328-335`），但 `bands` 默认含 `"clear"`——正是 G2 登记的非法波段标签，模板在**传播**这个缺陷 | budget doc §6.1 G2 |
| `examples/` | README.md:86 明确「人读示例（lint 覆盖，**不被 test 执行**）」→ 示例可静默腐烂而不被发现 | — |
| 命名 | `example_skill_usage.py` vs `quickstart_pybest.py` 前缀不一致；`best-config.yaml` vs `config_template.yaml` 同目录两种命名风格 | README.md:307-309, 413-422 |

### 2.6 contracts 能力不完整

| 问题 | 证据 |
|---|---|
| 契约引用不存在的模块 | `contracts/io-contract.md:51` 写 `BestQueryResult (astro_best)`；`src/` 下无 `astro_best` 模块，真实位置 `src.models`。而 `references/skills-spec.local.yaml:47` 已修正为 `src.models` —— **契约与 spec 已经漂移** |
| 能力面过窄 | spec 只声明 12 个 algorithms / 2 个 gates / 4 个 fields（`references/skills-spec.local.yaml:24-36`），而 `src/` 有 57 个模块。TAP-UWS、DownloadManager、PreciseDownloadJob、序列化格式、provenance、TaskLog、AiTools/MCP 工具面、OAuth TokenStore、checkpoint 全部不在契约内 |
| 门禁只有 2 条 | `http_status == 200` 与 `checksum_match == true`；无 `rows_nonneg`、`fmt_in_whitelist`、`sqlid_resolved`、`path_within_output_dir` 等可执行门禁 |
| fields 只有 4 个 | `sql`/`token`/`data`/`status`；无 `ra`/`dec`/`radius_arcsec`/`fmt`/`rows`/`page`/`job_id`/`progress`/`checksum`——下游按契约装配 envelope 时拿不到这些键的 type/unit 权威声明 |
| 无路径真实性校验 | `test/unit/contracts/test_gen_contracts.py` 只校验文件存在与 gates 相等（行 77-114），**不校验 `module:` 路径可导入**——这正是 `config_template.yaml` 6 处死路径能长期存活的原因 |

---

## 3. 覆盖矩阵 SSOT 设计（用户裁定 8）

**新文件**：`docs/architecture/coverage-matrix.md`

一行 = 一个**关键路径能力**。列定义：

| 列 | 含义 |
|---|---|
| `capability` | 能力名（与 spec algorithm 名或公开 API 名一致） |
| `anchor` | 权威源码锚点 `文件:行`（符号定义处） |
| `unit` | 单元测试锚点 `test/...py::Class::test_x`，无则 `—` |
| `integration` | 集成测试锚点，无则 `—` |
| `eval` | `evals/cases/case_xxx.yaml` 场景名，无则 `—` |
| `fmt` | 若为格式能力，标注 csv/txt/json/votable/fits |
| `status` | `covered` / `gap` / `by-design`（附理由） |

**覆盖行来源（四类并集，缺一即矩阵不完整）：**

1. `references/skills-spec.local.yaml` 的 `algorithms`（扩能后的全集）
2. `src/__init__.py::__all__` 公开面 + 各模块公开类/函数
3. `output.fmt` 全集（`src/serialization.py::LOCAL_EXPORT_FORMATS`）
4. 站点真实交互链（认证 → 两阶段查询 → 分页 → 落盘 → 校验和 → 续传 → 取消 → TAP/UWS → 名称解析 → 交叉匹配）

**新 meta 测试**：`test/unit/meta/test_coverage_matrix.py`，四条断言：

1. 矩阵每一行的 `anchor` 必须指向真实存在的文件与符号（AST 校验，防文档腐烂）；
2. 矩阵必须覆盖上述四类来源的**全集**（漏一行即失败，逼使新增能力时同步登记）；
3. `status: covered` 的行，其 `unit`/`integration`/`eval` 锚点必须真实存在且可收集；
4. `status: gap` 的行必须带 `by-design` 理由或已登记到 budget doc §6.1 —— **不允许无声缺口**。

> 这条门禁是「先补检测能力」裁定的落地形态：它把「无全覆盖」从一句主观判断变成 CI 可判定命题。

---

## 4. Phase 计划

> 提交单位：**单一 git 仓库，根为 `G:/tw/twskills`**（`astro-best/` 是其子目录，221 个受跟踪文件；`docs/routing`、`SKILL-INDEX.md`、`_shared/astro-skill-registry.yaml`、`scripts/refactor` 同仓受跟踪）。因此「跨仓」在本机实为**同仓跨目录**，可作原子提交，无需多仓协调——但 skill 归属边界仍按治理规则划分，写入范围必须在 Phase 表内声明。

### Phase 0 — 路由强度收敛（4 个 SSOT 一次性对齐）

- **目标**：消除 §2.1 的强度矛盾，让 BEST 数据路由指向 astro-best。
- **写范围**（跨 skill 归属，已获用户授权）：
  - `_shared/astro-skill-registry.yaml:208-220` — `strength: S4→S2`、`strength_label: legacy→specialist`、`pipeline_role: legacy→specialist`、`standalone: false→true`；`maturity: alpha` 与 `version: 0.3.1` **不动**（maturity 是生命周期字段，非强度；version 属 registry 既有字段，改动需单独裁定）
  - `SKILL-INDEX.md:54` — `S4→S2`，去掉 `[Legacy 归档]`，描述改为「FP08: BEST 数据库查询（PRIMARY，外部数据源驱动）」
  - `docs/routing/MASTER-ROUTING.md:19` — 支持 skill 列的 `astro-best (legacy_deprecated)` → `astro-best`
  - `docs/routing/MASTER-ROUTING.md:20` — PRIMARY `astro-catalog`（redirect: astro-best → S4）→ `astro-best`；支持 skill 列改 `astro-catalog, astro-lightcurve`
  - `docs/routing/routing.md:16-17` — 同步上述两行
- **不动**：`astro-best/manifest.yaml` 与 `SKILL.md` frontmatter 的 `strength: S4` 机器字段——上一轮已裁定「机器字段暂留原值，叙事层去 Legacy 化」，并已在 16 个文件加注释说明。**若本轮要一并改，需你追加一句授权**（见 §8 未决 1）。
- **回归/门禁**：`verify-routing-coherence.ps1`、`verify-astro-skills.ps1`、`scripts/governance/lock/verify-astro-all.ps1`、astro-best 全套 pytest + evals（确认无测试依赖 S4 字样）
- **Commit**：`docs(routing): promote astro-best to S2 PRIMARY and align four strength SSOTs`

### Phase 1 — 强度一致性门禁（防复发，Phase 0 的必要的另一半）

- **目标**：让 §2.1 的矛盾**下一次不可能静默发生**。
- **写范围**：`scripts/governance/lock/verify-strength-coherence.ps1`（新增）+ 挂入 `verify-routing-coherence.ps1` 或 `verify-astro-all.ps1`
- **校验规则**：
  1. registry 的 `strength`/`strength_label`/`pipeline_role`/`standalone` 四字段自洽（S4 ⇔ legacy+standalone:false）
  2. registry ↔ `SKILL-INDEX.md` 强度列逐行相等
  3. registry ↔ `SKILL-STRENGTH-MODEL.md` 当前分布表逐行相等
  4. `MASTER-ROUTING.md` 每个 PRIMARY 的强度 ∈ S0~S3（对齐该文件自身的 4-5 行规则）
  5. `MASTER-ROUTING.md` 中标记 `legacy_deprecated` 的 skill，其 registry `strength` 必须是 S4
- **Commit**：`test(governance): add strength-coherence gate across four SSOTs`

### Phase 2 — E1 生成器根治（跨仓，已授权）

- **写范围**：`scripts/refactor/common.py`（约 273 行）、`scripts/refactor/materialize_tests.py`（约 34 行）、`scripts/refactor/materialize_contracts.py`、`scripts/refactor/materialize_templates.py`、`scripts/refactor/spec/skills-spec.yaml`
- **动作**：
  1. 删除 `Master Plan v8.0` 字面量 → `Master Plan`（与 budget doc §7 已完成的 47 处同规则）
  2. 把中文注释头部**模板化**：生成器内置注释模板常量（中文、C1-C6 规范、无版本号），产物头部由模板渲染，而非事后手补
  3. 生成器侧新增自测：断言产物头部含中文注释且不含版本号字样
  4. 复跑物化，`git diff` 必须**只有**注释头与版本号字样两类变化；若出现代码变化立即停止并上报
- **回归/门禁**：astro-best 全套 pytest + evals + tree SSOT + `verify_no_code_loss.py` 指纹比对
- **Commit**：`chore(refactor): template Chinese header comments into generators and drop Master Plan v8.0`

### Phase 3 — 覆盖矩阵 SSOT + 缺口补齐（astro-best 内，用户裁定 2 的最高优先）

- **写范围**：`docs/architecture/coverage-matrix.md`（新增）、`test/unit/meta/test_coverage_matrix.py`（新增）、按缺口补的 `test/**`、`evals/cases/**`
- **动作**：
  1. 建 `--cov` 基线（`pytest --cov=src --cov-report=term-missing`），把数字写进矩阵文档头——用户裁定 4 的「不低于现基线」从此可判定
  2. 生成矩阵初版，逐行标 `covered`/`gap`
  3. **优先补 P0 盲区对应的检测**（顺序即 §2.4 表）：`best_multiband_export` 行为测试（直接覆盖 A2）、`best_crossmatch_pipeline` 会话复用测试（覆盖 A1）、`output.fmt` 五格式 eval 场景、下载取消终态断言（覆盖 B1/B2）、`BestSource.from_row` 六字段填充断言（覆盖 G1）
  4. D1 修完之前，**矩阵的 `eval` 列不得作为覆盖证据**（audit 模式预置 1.0 会虚报）——故 D1 提到本 Phase 第一步
- **Commit**：`test(coverage): land capability-evidence matrix SSOT and close P0 detection gaps`

### Phase 4 — contracts / spec 扩能力 + 路径真实性（用户裁定 9）

- **写范围**：`references/skills-spec.local.yaml`、`contracts/io-contract.md`、`contracts/fields/*`（新增）、`test/unit/contracts/*`、`test/unit/meta/*`
- **动作**：
  1. 修 `contracts/io-contract.md:51` `astro_best` → `src.models`
  2. spec 扩 `algorithms`：补 `TapGateway`/`TapUWSMixin`（`src.tap.service`）、`DownloadManager`（`src.download_manager`）、`PreciseDownloadJob`（`src.download_precise`）、`ProgressStore`（`src.download_progress`）、`ProvenanceStore`（`src.provenance`）、`TaskLog`（`src.task_log`）、`ToolBox`（`src.ai_tools`）、`TokenStore`（`src.auth.nadc_oauth`）、`DownloadCheckpoint`（`src.scripts.checkpoint`）、序列化面（`src.serialization`）
  3. spec 扩 `fields`：`ra`/`dec`/`radius_arcsec`/`fmt`/`rows`/`page`/`job_id`/`checksum`（各带 type/unit/direction）
  4. spec 扩 `gates`：`fmt_in_whitelist`、`rows_nonneg`、`sqlid_resolved`、`path_within_output_dir`
  5. **新增路径真实性 meta 测试**：spec / contracts / templates 里每个 `module:` 必须可导入——这是挡住 `config_template.yaml` 那类死路径的门禁
  6. weights 与 `test/unit/meta/test_gen_ledger.py::APPROVED_DEFICITS` 的关系复核（spec 扩项会改变计数，需同步裁定）
- **Commit**：`feat(contracts): extend spec capability surface and enforce module-path truth`

### Phase 5 — templates / examples 规范化（用户裁定 10）

- **写范围**：`templates/*`、`examples/*`、`README.md`（树 SSOT 需同步）、`ops/verify_tree_integrity.py` 结果
- **动作**：
  1. 修 `templates/config_template.yaml` 6 处死路径（对齐 Phase 4 的路径真实性门禁）
  2. `templates/best-config.yaml` 的 `bands` 去掉 `"clear"`（G2 根因）
  3. **每个模板声明唯一消费者**：有消费者者写入文件头注释（如 `best-config.yaml → test/unit/meta/test_phase4_wiring.py::Q-31`）；无消费者者（`gen_*.yaml` 6 个）裁定去留——建议降级为 `templates/archive/` 或删除，**需你确认**（见 §8 未决 2）
  4. 命名统一：`example_*.py` / `quickstart_*.py` 二选一（建议统一 `example_*.py`）；`*_template.yaml` 统一为一种风格（建议 `best-*.yaml` 与 `gen-*.yaml` 按「人读配置」/「生成器产物」分前缀）
  5. **examples 纳入测试执行**：`test/examples/test_examples_run_offline.py`，用 stub session 跑通两个示例的主路径，断言不发真实网络请求；README.md:86 的「不被 test 执行」描述同步改写
  6. 树 SSOT 重算：`python ops/verify_tree_integrity.py --write`
- **Commit**：`refactor(templates): fix stale module paths, declare consumers, and execute examples in tests`

### Phase 6 — 34 条债务清偿（用户裁定 7，四组全纳入）

每组一个原子提交 + 配套回归。**依赖 Phase 3 的检测能力先生成**（否则修完无法证明修好了）。

| 子阶段 | 组 | 关键动作 | 配套回归 |
|---|---|---|---|
| 6a | A1-A5 | 脚本层共享 client 复用（对齐 Q-18 `_SHARED_CLIENT`）；`export_multiband_photometry` 白名单化 `output_format`；`TokenStore.save` 后 `os.chmod(0o600)`；`to_csv` 空列表写表头 | `test/unit/scripts/` 新建 3 个测试文件 |
| 6b | B1-B6 | precise 取消回调贯通；`FileJob` 取消抛 `JobCancelledError` 而非返 None；`precise_output_file` 加 job_id/时间戳粒度；`resume` 对称化（file/precise 也走原地续传）；std 组展开透传 job_id；`list_jobs` 排除 `.provenance.json` | `test/unit/download/` 扩 6 组断言，重点断言**终态字符串** |
| 6c | C1-C2 + G1-G3 | `DOMAIN_BOOST` 改传 `stem` 或键表对齐；docstring 去 `Master Plan v8.0`；`BestSource.from_row` 填充六字段（含 `ps1_parallax` 等真实列名映射）；`DownloadInput.bands` 默认去 `"clear"`；`BestResultSet.handoff` 的 `next_skills` 从 manifest 读取而非硬编码 | RAG 领域加权触发断言；六字段填充断言；manifest 驱动断言 |
| 6d | D1-D5 + E1-E10 + F1-F3 | `--mode audit` 不预置 rate；`VERSION_MARKER_RE` 支持列表项与引号形式；审计器注册表强制反证夹具；`run_audit` docstring 范围修正；删死常量/重复 IO；环境锁补 6 个 stdlib；`_declared_packages` 正则加固；ledger 缺失时校验计数；删死 fixture 与重复定义；E6/E7/E8 正名；E9 去硬编码深度与 sys.path 泄漏；E10 口令改 env/getpass；F1 路径参数化；F2 ruff 清违规；F3 过期路径 | 每条一个回归；D1 的回归必须构造「零行为证据但 audit 报满分」的反向用例 |

- **Commit**：`fix(<group>): ...`（ Conventional Commits，每组一条）

### Phase 7 — 收口与全量验收

- **写范围**：`docs/architecture/file-size-budget.md`（§6/§6.1 标记已修 + §3 更新）、`CHANGELOG.md`
- **动作**：剩余 5 个超 400 行文件按 budget doc §3 已登记方案处理（`evals/eval_runner.py` 971 → `evals/probes/`；两个图生成器 794/580 → `layout_data.py`；`test_integration.py` 560 → 按链路拆 + `conftest.py` 上移；`src/client.py` 553 维持 §3.2 的不可行论证或走 P1-9 双入口合并）
- **Commit**：`docs(budget): close §6 backlog and refresh line registry`

---

## 5. 边界与铁律（执行期必须遵守）

1. **本轮只读**：Phase 0 之前不改任何文件；每 Phase 开始前重读目标文件（并发写会撞 `ReplaceFileW EIO`，优先用行号补丁脚本而非长中文 `old_string`）。
2. **结构变更需显式批准**：本计划中新建 `docs/architecture/coverage-matrix.md`、`test/unit/meta/test_coverage_matrix.py`、`test/examples/`、`contracts/fields/*` 新增项、`scripts/governance/lock/verify-strength-coherence.ps1` —— 均在本计划范围内，**批准本计划即视为批准这些新文件**；若你要收窄，请在批准时点名排除。
3. **注释规范**：所有新增/修改代码遵守 `docs/architecture/file-size-budget.md` §4（C1 中文唯一、C2 每个类/函数 docstring、C3 import 组中文注记、C5 禁版本号）。块级判定，不逐行。
4. **400 行净代码预算**：任何被改到超限的文件必须同 Phase 内拆完（抽正交关注点到新模块 + 留委派薄壳）。
5. **CRLF**：每次提交前跑 `python temp/classify_crlf.py`（本轮已三次复发）。
6. **G1 资产守恒**：`scripts/refactor/verify_ledger.py` 预提交钩子 + `test/unit/meta/test_gen_ledger.py`；删除任何文件前先更 ledger。
7. **禁版本号**：新增内容不得含发布版本号；IVOA 协议常量（VOTable v1.3 / UWS v1.0 等）与 git 追溯锚点按 budget doc §7 B 类豁免处理。
8. **树 SSOT**：新增/删除/重命名文件后跑 `python ops/verify_tree_integrity.py --write`，README 树与磁盘必须一致。
9. **零网络依赖**：所有新增测试必须离线可跑（stub session）；live 测试维持 skip 纪律。

---

## 6. 风险与回滚

| 风险 | 概率 | 影响 | 缓解 | 回滚 |
|---|---|---|---|---|
| registry 改 S2 触发下游按 strength 分流的逻辑（`astro-route.ps1` 路由锁） | 中 | 路由范围变化 | Phase 0 后立即跑 `verify-astro-all.ps1` + `astro-route.ps1 -Hint` 抽查 BEST 任务文本 | `git revert` 该提交（四文件一次原子提交，可整组回退） |
| 生成器复跑物化产生非预期代码 diff | 中 | 大面积污染 | Phase 2 要求 `git diff` 只有两类变化，否则停机上报 | `git checkout -- contracts templates evals test` |
| spec 扩项改变 `test_gen_ledger` 计数 → G1 钩子失败 | 高 | 提交被拦 | Phase 4 先算清新计数并同步 `APPROVED_DEFICITS`/`PLAN_TARGETS`，再改 spec | 单独提交计数调整 |
| 补测试暴露新的真实缺陷（预期内） | 高 | Phase 延期 | 缺陷按 §6.1 同规则登记，不就地扩范围 | — |
| 删除 `gen_*.yaml` 触发 TemplatesAuditor 行数目标下降 | 中 | evals 审计 findings | 删除前先跑 evals，按 findings 调整 weights | 恢复文件 |

---

## 7. 总验收门禁（Phase 7 结束时必须全绿）

| 门禁 | 命令 | 期望 |
|---|---|---|
| lint | `ruff check .` | All checks passed |
| 单元+集成 | `pytest -q` | 全通过，零回归；新增测试数 ≥ 缺口行数 |
| 覆盖基线 | `pytest --cov=src` | 行覆盖 ≥ Phase 3 建立基线，且矩阵无未登记 `gap` |
| evals | `python evals/eval_runner.py --mode audit` | 24/24 → 场景数增长；6 审计器 0 findings；docstring 100% |
| 覆盖矩阵 | `pytest test/unit/meta/test_coverage_matrix.py` | 四类来源全集覆盖，锚点全部真实 |
| 契约路径真实性 | `pytest test/unit/meta -k module_path` | spec/contracts/templates 的 module 全部可导入 |
| 强度一致性 | `verify-strength-coherence.ps1` | 四份 SSOT 逐行相等 |
| 路由一致性 | `verify-routing-coherence.ps1` / `verify-astro-skills.ps1` / `verify-astro-all.ps1` | 全通过 |
| 树 SSOT | `python ops/verify_tree_integrity.py` | OK，条目数与 README 一致 |
| 400 行预算 | `python ops/audit/count_code_lines.py` | 超限文件数 ≤ 1（仅 `src/client.py`，附 §3.2 论证） |
| 注释体检 | `python ops/audit/comment_audit.py` 等 | 缺失 docstring 0 / 非中文 0 / import 组缺口 0 / TODO 0 |
| CRLF | `python temp/classify_crlf.py` | 0 |
| 版本号 | `python ops/audit/version_scan2.py` | tracked 文件 A 类 0 |

---

## 8. 未决项（需你再裁定，不阻塞 Phase 0-3 启动）

> **本节 5 项已全部裁定（R2 订正，2026-10-05）**：原文按「提问当时的悬置状态」保留作决策轨迹，
> 裁定结果见 §10 开头的 ①~⑤。逐项落点：
> ① 已升 —— `SKILL.md` frontmatter 与 `contracts/io-contract.md` 现均为 `strength: S2`；
> ② 保留 —— `templates/gen_*.yaml` 保留，文件头声明唯一消费者；
> ③ 不动 —— registry 的 `maturity` / `version` 未随强度更新（原行号坐标 `216-217` 已漂，
> 实际在 `astro-best` 条目末的 `maturity: alpha` 与 `version: 0.3.1` 两行）；
> ④ 已授权并落地 —— 新增 `verify_strength_coherence.py` 并挂入两个门禁（提交 `8327a21d`）；
> ⑤ 已按「正确性先于结构」执行。
> 下文 1/3/4 三项若按原文重读会得出「仍未裁定」的错误结论，故在此显式关闭。

1. **astro-best 自身 frontmatter/manifest 的 `strength: S4` 机器字段是否同步升 S2？** ✅ 已裁定为**升 S2**（§10 ①）。上一轮裁定「机器字段暂留原值 + 注释说明」已被本轮推翻：若不升，registry 说 S2 而 skill 自述 S4，Phase 1 的门禁规则 1/2 会**直接报失败**——两个裁定之间的硬冲突已按「升 S2」消解。
2. **`templates/gen_*.yaml`（6 个，零消费者）删除还是保留？** 删除会降 TemplatesAuditor 行数并影响 weights 目标；保留则「作用不明显」的问题依旧。
3. **`_shared/astro-skill-registry.yaml` astro-best 条目的 `maturity: alpha` / `version: 0.3.1` 是否随强度一并更新？** ✅ 已裁定为**不动**（§10 ③）。version 属禁版本号铁律的既有字段，改动需单独授权。（原坐标 `216-217` 已漂，现为该条目 `standalone` 两行之后的 `maturity` / `version` 两行；跨仓坐标不受本仓门禁管理。）
4. **是否授权在 Phase 1 新增 `verify-strength-coherence.ps1` 并挂进 `verify-astro-all.ps1`？** ✅ 已授权并落地（§10 ④；实际实现名为 `verify_strength_coherence.py`，六条规则，随提交 `8327a21d` 挂入两个门禁）。
5. **`evals/eval_runner.py`（971 行）是否本轮就拆？** 它是 Phase 3 要改的对象（D1/D4/D5 都在其中），先拆后改会让 diff 更干净，但拆分会放大 Phase 3 的改动面。

---

## 9. 建议启动顺序

```
Phase 0（路由对齐，4 文件，低风险高能见度）
   ↓
Phase 1（门禁，防复发）  ← 与 Phase 0 同一次会话完成，中间不提交其他变更
   ↓
Phase 3（覆盖矩阵 + P0 检测缺口）  ← 用户裁定的最高优先
   ↓
Phase 4（contracts 扩能力 + 路径真实性）
   ↓
Phase 5（templates/examples 规范化）
   ↓
Phase 2（E1 生成器根治，跨仓，需复跑物化，放后面避免反复）
   ↓
Phase 6（34 条债务，四组）
   ↓
Phase 7（收口 + 剩余 400 行 + 全量验收）
```

> Phase 2 后置的理由：生成器一旦模板化，后续任何物化都会重写产物头部；若把它放在 contracts/templates 规范化之前，Phase 4/5 的改动会被下一次物化覆盖，白做一遍。

---

## 10. 执行进展（2026-10）

用户裁定「严格按照计划进行，裁定也由你定，完成所有任务」后，五个原「未决项」由主控裁定：
① astro-best 自身 frontmatter/manifest 的 `strength: S4` 一并升 S2（否则 Phase 1 门禁自相矛盾）；
② `templates/gen_*.yaml` 保留不删，但文件头声明唯一消费者；
③ registry 的 `version`/`maturity` 不动（version 属禁版本号铁律既有字段）；
④ 授权新增 `verify-strength-coherence.ps1` 并挂入 `verify-astro-all.ps1`；
⑤ `eval_runner.py` 先修 D1/D4/D5 再拆（正确性先于结构）。

### 已落地并提交

| Phase | 提交 | 内容 |
|---|---|---|
| 0 + 1 | `8327a21d` | 四份强度 SSOT 对齐到 S2；新增 `verify_strength_coherence.py` 六条规则并挂入两个门禁；修好 3 处既有坏门禁 |
| 3 | `3f9355a4` | 覆盖矩阵 SSOT + 七条断言门禁 + 反向对照；修 D1/D4/D5 |
| 3e | `77d3c806` | 补 G-cov-1/8 检测能力；矩阵 §3 gap 清单升级为带生命周期状态 |
| 4 | `97416462` | spec 扩片 12→31 条 + `executable_gates` 4 条 + module 路径真实性门禁；monorepo spec 同步 |
| 5 | `fe47788a` | templates 死路径/命名/消费者声明；examples 纳入离线测试执行 |
| 2 | `b2a806b2` | 生成器版本号清除 + 中文注释模板固化 |
| 2 清扫 | `ffdfdf26` | 全仓 1693 个文件机械清除计划书版本号字样 |

### 执行中发现的计划外问题（均已处置）

1. **`verify-astro-skills.ps1` 原本恒红 9 条**（`astro-best/sync/SKILL.md` 陈旧期待项、
   `temp/` vendored 产物被扫、astro-best 缺 maturity/mode 标记）——坏门禁等于没门禁，
   已在 Phase 0 一并修好（该门禁从 9 失败转为通过）。
2. **`tests/test_astro_skill_registry.py` 原本恒红**：registry 里 `astro-best-sync` 的
   path 指向不存在的 `astro-best/sync`。已按其他已吸收别名的模式改为指向 `astro-best`。
3. **`SKILL-STRENGTH-MODEL.md` 的「当前分布」表是全域重组前的快照**：缺 10 个 canonical
   skill、列有 2 个已改名 skill、6 个档位与 registry 相反。已按 registry 全量重建。
4. **清扫事故（已修复并留档）**：豁免匹配用完整路径与白名单项全等比较，恒不生效，
   误改了 `CHANGELOG.md` 的历史记录，还把记载变更本身的句子改成自我矛盾。已以 HEAD
   为基准重建（diff 变为纯新增），脚本改为后缀匹配并复跑预检确认 0 命中。
5. **我的反证夹具被审计器误判**：`test_eval_runner_dimensions.py` 里的字面量
   `assert True` 被 TestsAuditor 的文本正则判成 CRITICAL。已改为拼装构造并注释说明
   「别为了直观改回字面量」。
6. **Phase 4/5 边界遗漏**：`gen_report_appendix.yaml` 的 7 处死路径与
   `gen_config_template.yaml` 的 `BestAuth.module` 指薄壳，由 Phase 4 子代理发现、
   主控补修；同时更新 `materialize_templates.py` 的 catalog 文件名，否则下次物化会
   以旧名重建文件并使树门禁 FAIL。
7. **G1 台账不需要 relock**：四类计数全部 ≥ locked 基线（tests 983/956、
   templates 411/411、evals 904/904、contracts 1003/1003），钩子通过；动治理工件
   收益有限，登记为观察项。

### 验收基线（Phase 6 启动前）

astro-best：ruff All checks passed；pytest 652 passed / 23 skipped；树 SSOT 261 条目；
evals `--mode all` 25/25 + 25/25、6 审计器 0 failed、docstring 100.00%、综合评分 1.0000 SUCCESS。
monorepo：registry pytest 5 passed；strength coherence passed；G1 ledger 通过；
routing coherence 通过；astro skills 通过。十项门禁全绿。

---

## 11. 终验结果（Phase 7d）

### 提交清单（`6e541e65` 之后共 8 个）

| 提交 | 内容 |
|---|---|
| `3bf61494` | Phase 6a：A 组 5 条债务（会话复用/导出白名单/令牌权限/空导出） |
| `37de2c27` | Phase 6b：B 组 6 条债务（取消语义/resume 对称/输出唯一/sidecar） |
| `3aa520e4` | Phase 6c：C+G 组 5 条债务（RAG 领域加权/六字段/bands/next_skills） |
| `b43c9102` | Phase 6d：D2 + E2~E10 + F1~F3 共 13 条债务 |
| `56d227ea` | Phase 6 收口：树清单 261→270 + budget doc 清偿台账 §6.4 |
| `7522bfe6` | Phase 7a：`eval_runner.py` 990→381（拆 probes / case_runner / paths） |
| `e3f8ce7b` | Phase 7c：`test_integration.py` 577→7 个链路文件（68 项测试零丢失） |
| `755fbe78` | Phase 7b：两个图生成器 793/584→236/104（常量表抽 `layout_data.py`） |

### 13 项门禁全绿

| 门禁 | 结果 |
|---|---|
| ruff（全仓） | All checks passed |
| ruff（diagrams 显式路径） | All checks passed |
| pytest | **728 passed / 24 skipped / 0 failed** |
| 覆盖矩阵门禁（7 条断言） | 7 passed |
| module 路径真实性门禁 | 通过 |
| eval_runner 自身回归（18 例） | 18 passed |
| 树 SSOT | OK，**280 条目** |
| evals `--mode all` | 场景 25/25、用例 25/25、6 审计器 0 failed、docstring 100.00%（260/260）、**综合评分 1.0000 SUCCESS** |
| evals `--mode audit` | 0.3000 **FAILED**（行为三维 NOT_MEASURED —— 单模式不得通过） |
| evals `--mode behavior` | 0.8000 **FAILED**（docstring NOT_MEASURED —— 单模式不得通过） |
| registry pytest（monorepo） | 5 passed |
| 强度一致性门禁（monorepo） | passed（27 canonical skills / 5 份 SSOT） |
| G1 台账 + 路由一致性 + astro skills（monorepo） | 全部 passed |

### 400 行净代码预算：9 → 1

超限文件从本轮开始时的 **9 个**降到 **1 个**（`src/client.py` 553，§3.2 已论证并裁定为例外）。
其余拆分成果：`eval_runner.py` 990→381、`test_integration.py` 577→7 文件（最大 171）、
`gen_best_macro_flowchart.py` 793→236、`gen_astro_best_architecture.py` 584→104、
`probes.py` 387、`case_runner.py` 380、`layout_data.py` 230。

### 执行期两次协作事故（已恢复，留档）

1. **`git stash` 误卷并行工作**：6d 子代理为取 RED 证据执行裸 `git stash push -- astro-best/`，
   把其余三个子代理未提交的 32 个文件一并收进 stash。恢复方式：先比对 stash 与工作树的
   测试函数名集合，发现 **18 个回归测试只在 stash 里**（源码修复在工作树、护航测试丢失），
   再对 7 个测试文件精确 `git checkout stash@{0} --` 取回；对 3 个工作树已有更新的文件
   保留工作树版本。恢复后全量 728 passed 零失败，才 `git stash drop`。
   **教训**：并行子代理取 RED 证据必须用 `git stash push -- <自己的文件>` 或
   `git checkout HEAD -- <自己的文件>`，绝不许裸 `git stash`。
2. **拆分与锚点校验的耦合**：`test_integration.py` 按链路拆分会让覆盖矩阵 15 条 integration
   锚点失效（矩阵门禁 AST 硬校验文件+类+方法存在）。子代理正确拒绝用「再导出壳」造假门禁，
   上报后由主控按「只改路径段、类名/方法名不动」机械替换收口。
   **教训**：拆文件前先 grep 覆盖矩阵锚点，把锚点更新列入同一改动。

### 遗留观察项（均不阻塞，已登记）

1. `docs/diagrams/astro-best-legacy-architecture.drawio` 与生成器产物有 85 行文案差异
   （6d 轮次发现）：生成器现已产出 "data-source 主理" 新文案，受跟踪产物仍是旧文案。
   重新生成会带来大 diff，建议单开任务。
2. G1 台账四类计数全部 ≥ locked 基线（tests 983/956、templates 411/411、
   evals 904/904、contracts 1003/1003），不需要 relock。
3. `evals/case_executor.py` 14 条 import 组、`test/unit/meta/test_coverage_matrix.py` 5 条
   import 组等 comment_audit 欠账（共 25 条），多为本轮新拆文件的 import 组中文说明缺失，
   可在下一轮注释专项一次清掉。
4. `src/download_progress.py` 的 `os.replace` 在 Windows 遇并发读者会 WinError 5，且异常从
   `_run` 的 try 外穿出可杀死 worker（6b 上报；测试侧已用「内存 Event + Future 等待 +
   收敛后单次读」规避）；建议后续在 `save()` 加重试。
5. 已成功且 checkpoint 已删的 region/sqlid 任务 resume 仍 FileNotFoundError（6b 上报，
   B5 只解决了 std 组分支）。

---

## 12. Phase 8 —— 图示链路治理与三项观察项清偿（2026-10，苏格拉底第二轮）

### 12.1 苏格拉底三问与裁定

用户续问：「这个生成器是很必要的东西吗？能不能进行拆分？目前的影响怎么样？」

| 问题 | 追问问证 | 裁定 |
|---|---|---|
| 生成器必要吗 | 全仓 grep：test/evals/ops/scripts 对图示零引用；SKILL.md 无引用；覆盖矩阵 88 行无锚点；README:242 自述 `docs/`「零运行时引用」。`.drawio` 本身可手工编辑 | **不是必要基础设施，但是唯一可重复的生产工具**。按仓库治理标准（被门禁/测试/契约引用才算必要）它不达标；删掉则 28MB 产物只剩手工编辑通道，几何审计与确定性重建同时失效。定位改述为「归档级构建工具」 |
| 能不能拆分 | 400 行预算已满足（6 个脚本净代码行 224/95/226/146/52/51，Phase 7b 已拆） | **行数上不需要再拆**。layout_data 按图拆两半只会多一个模块（两个生成器本就只 import 自己那半）。真问题在三处结构不对称：入口契约不一致（macro 一条龙 vs arch 只生成）、审计口径两套、**无漂移契约** |
| 目前的影响 | 见 12.2 | 见 12.2 |

### 12.2 实测影响（6 项，全部有证据）

1. **强度收敛还有一处活口**：受跟踪产物含 `S4 Legacy` ×10（架构图 8 + 流程图 2）、「旧入口 → canonical」旧措辞；`verify_strength_coherence.py` 查 5 份 SSOT，不查图。
2. **铁律 3 漏网字面量**：受跟踪 `astro-best-legacy-architecture.drawio` 含 `版本: v0.3.1`，1693 文件大清扫漏改（生成器侧已改成「变更史见 CHANGELOG」）。
3. **生成器自身半迁移**：`layout_data.py` banner 已写「12 大定标星表」（与 SKILL.md:47「12 张可查星表」、`CATALOG_DISPLAY` 12 项一致），但同文件 3 处仍写「9 大」、2 处仍写 S4、3 处仍写「兼容」——**直接重生成会产出一张自相矛盾的图**。
4. **README 规则 5 与 git 事实矛盾**：README:27/:278 声明 `docs/`「不随 git 分发」，但 21 个文件 / 28.2MB 跟踪在 HEAD 里（`9f1aca18` force-add）；树完整性门禁只比对 README 树块与文件系统存在性，从不比对 git index，所以这个矛盾一直绿灯。28.2MB 中 99.1% 是渲染产物。
5. **可移植性有隐藏前提**：重生成依赖外部 skill 的 `drawio_builder`（`<USER_HOME>\.agents\skills\drawio-diagram-author\scripts`）与 draw.io 桌面端（`<TOOL_ROOT>\draw.io.exe`）；F1 已改环境变量优先，但 `docs/diagrams/README.md` 只列了 3 个脚本（实际 6 个），依赖与环境变量只字未提。
6. **漂移已在发生且无人发现**：受跟踪 vs 当前生成器，架构图 12/341 行（3.5%）、流程图 3/399 行（0.8%）不同，几何部分逐字节相同——漂移 100% 在 `value=` 文案属性。**更正 §11 遗留观察项 1 的数字：不是 85 行，实测 15 行。**

### 12.3 执行（4 个原子提交）

| 提交 | 内容 |
|---|---|
| `6dabf230` | 补完 `layout_data.py` 31 处半迁移文案（`9 大`→`12 张可查`、去全部 S4 字样、兼容→主理、重定向→委派、删除与 PRIMARY 裁定矛盾的「不新增 PRIMARY 场景」、图内不再复制强度等级改指向 registry）；重生成两个 `.drawio`（几何审计全过，diff 仅 35 个文案单元格）；新增 `test/unit/meta/test_diagram_ssot.py` 7 项常驻门禁；重写 `docs/diagrams/README.md`（6 脚本全表 + 依赖/环境变量 + 「位图产物落后 `.drawio` 一个修订」声明） |
| `28b77e1f` | 清零 comment_audit 23 条 import 组欠账 + 2 条缺 docstring（`evals/case_runner.py` 14 条为函数内延迟导入，逐点说明「为什么延迟」）；四件套验收 code-changed=0 |
| `192307d6` | `download_progress.save()` 的 `os.replace` 加 3 次退避重试（20/50/100ms），Windows 瞬时占用不再杀死下载线程；新增 2 项回归 |
| `54c2535e` | `DownloadManager.resume()` 终态检查前置：已完成的 region/sqlid 作业返回原 job_id 而非误报「没有断点」；RED 证明（退回 HEAD 精确复现 FileNotFoundError） |

### 12.4 门禁结果（`temp/final_gates_phase8.py`，18 项全绿）

ruff 双通道 / pytest **738 passed** / 覆盖矩阵 / module path / eval_runner 自测 / **图示定位门禁（新）** / 树清单 281 / evals `--mode all` **1.0000 SUCCESS**（docstring 100%）/ 单模式 audit **0.3000 FAILED** 与 behavior **0.8000 FAILED**（均正确不得通过）/ monorepo 五门禁 / 400 行预算仅 `client.py` 一个已登记例外。

### 12.5 遗留观察项状态

| 原 # | 状态 |
|---|---|
| 1（.drawio 漂移） | **已清**（`6dabf230`）：文案迁移补完 + 重生成 + 常驻漂移门禁。位图/矢量产物按裁定不重渲染，README 已声明落后一个修订 |
| 2（G1 台账） | 不变（四类计数全部 ≥ locked，无需 relock） |
| 3（comment_audit 25 条） | **已清**（`28b77e1f`，实测 23+2，六类计数全 0） |
| 4（save() WinError 5） | **已清**（`192307d6`，重试 + 2 项回归） |
| 5（已完成作业 resume 误报） | **已清**（`54c2535e`，终态检查前置 + RED 证明） |

### 12.6 新遗留（不阻塞）

1. `docs/diagrams/` 的 28.2MB 受跟踪资产与 README 规则 5「docs/ 不随 git 分发」矛盾：要么把渲染产物移出 git（只跟踪 `.drawio` + 生成器，约 270KB），要么改 README 规则 5 的措辞。两者都是结构变更，需单独授权。
2. `astro-best/.workbuddy-ai/memory/2026-09-27.md` 是工具生成的未跟踪文件，落在 skill 根目录（规则 4 要求临时文件只在 `temp/`）；属其他工具的状态目录，未擅自删除，待确认后移入 `temp/` 或加入 `.gitignore`。
3. 两个 `.drawio` 头部的 `version="24.0.0"` 是 draw.io 构建库自带的工具元数据（重新生成也在），不属项目发布版本号；若要彻底统一口径，需在生成器侧剥离，属另一类改动。

---

## 13. Phase 9 —— 仓库卫生与图示架构严谨化（2026-10，用户第 8 轮指示）

用户四项指示：①渲染产物移出 git ②`.workbuddy-ai` 移走 temp ③消除噪音 ④整体科学严谨，可参考
`<USER_HOME>\Desktop\数模国赛\A` 的流程图架构。

### 13.1 参考模板的研读结论

该工程（数模国赛 A 题·药材烘干）的全景架构图生成器
`02_code/架构图生成/generate_panorama_architecture.py` 的架构范式：
**5 阶段纵向主线 + 左右双轨导航 + 外框闭环轨道 + 分阶段配色 + 口径表 + 环内循环节点**，
落盘后还跑 `verify_drawio_security` 安全 lint。迁移时**只取结构范式，不取配色与版式**
（那是论文图语言，与本仓 Slate 工程调色盘不是一套体系），选中两个最契合天文数据 skill 的：

| 模板要素 | 本仓对应问题 | 迁移方式 |
|---|---|---|
| 口径表（温度°C/浓度kg/kg/几何η 独立成卡） | 量纲单位塞在「12 大横切治理面」横幅的 ② Units 一行里，读者要读完 12 条治理面才看见单位 | 提为画布级**数据口径表**（7 组口径 + 3 个质量门限，每个数值行内注明源码出处） |
| 外框轨道 + 环内循环节点 | 生成器 docstring 从第一版就写「外环专用闭环反馈走廊」，旧实现只落成一条绕画布边缘的连线，读者读不出闭环经过哪几站 | 补为第 6 条横向容器带**闭环反馈走廊**，四站推进 + 容器标题说明返回走线 |
| 落盘后跑安全 lint | 本仓图示无任何安全/结构 lint | `verify_drawio_security` 收进 `test_diagram_ssot.py` 漂移闸门（8 类检查，对新产物与受跟踪产物各审一遍） |

### 13.2 执行（2 个提交）

| 提交 | 内容 |
|---|---|
| `df7738ee` | ① `git rm --cached` 12 个 PNG/SVG/PDF（27.9 MB，磁盘保留、落入既有 `docs/` ignore）；README 规则 5 与 `docs/` 表格行改为精确描述该拆分。② 新增 `docs/diagrams/drawio_io.py`（`save_clean`）：落盘后剥离构建库写死的 `host/agent/version/type` 四属性 + 行尾归一为 LF（踩坑：`write_text` 在 Windows 文本模式会把 `\n` 转回 `\r\n`，必须 `write_bytes`）。③ `.workbuddy-ai/` 移入 `temp/`，`.gitignore` IDE 段加 `.workbuddy-ai/`、`.workbuddy/`。④ 门禁增强：漂移闸门加安全 lint；新增 `test_every_source_file_is_git_tracked`（本提交自己踩的坑：`drawio_io.py` 是 `docs/` 下新文件被 ignore 挡住、`git add` 静默跳过，提交成功但克隆机 import 即失败——已用临时探针文件做 RED 证明） |
| `38d83f5e` | 流程图补**数据口径表**与**闭环反馈走廊**（四站：异常触发→决策信封→重观测请求→知识飞轮）。新元素全部落在原有空白带（s5 底 2950→画布底 3200），间距 12/12/24px，零重叠零越界；几何审计 5 泳道 37 卡 → 6 容器 42 卡，0 collisions。本地 12 个渲染产物已同步重渲（不跟踪，仅本地可见） |

### 13.3 门禁结果（`temp/final_gates_phase8.py`，18 项全绿）

ruff 双通道 / pytest **739 passed** / 覆盖矩阵 / module path / eval_runner 自测 / **图示定位门禁 8 项**（含 git 跟踪检查与安全 lint）/ 树清单 278 / evals `--mode all` **1.0000 SUCCESS** / 单模式 audit 0.3000 与 behavior 0.8000 均正确 FAILED / monorepo 五门禁 / 400 行预算仅 `client.py` 一个已登记例外。

### 13.4 分发口径现状

`docs/diagrams/` 受跟踪 = 2 个 `.drawio` + 7 个脚本 + README（约 280 KB）；27.9 MB 渲染产物 local-only。
README 规则 5 的「docs/ 不随 git 分发」已改为精确表述（唯一例外即本目录的源与脚本），
§12.6 遗留 1/2/3 全部清偿。

---

## 14. Phase 10 —— 全仓本轮时间戳噪音清除（用户第 10 轮指示）

用户指示：「将 reference 等文件中的 2026-09-30 内容清除，其他文件除改动文件也整改，
严格对照修改轮次即可，reference 保持严谨性，消除类似的噪音」。

### 14.1 范围裁定（三类日期，两种命运）

| 类别 | 例 | 处置 |
|---|---|---|
| 本轮时间戳（我们何时验/何时建/何时批准） | `2026-09-26` `2026-09-27` `2026-09-30` `2026-09-02` `2026-08-14` `2026-10` | **清除**：变更史唯一载体是 `CHANGELOG.md`，行内时间戳是会说谎的噪音（站点行为已变而戳还在，读者误以为刚验过） |
| 变更记录载体 | `CHANGELOG.md`（22 处）、`governance-debt-plan.md`（4 处）、`implementation-plan*.md`、`ISSUES-2026-09-28-source-audit.md`、本轮计划文档 | **豁免**：日期即其用途，动了就把历史记录改成自我矛盾（Phase 2 清扫事故的同一故障） |
| 外部事实/功能常量 | `2025-01-13`（NADC OAuth 规范文档日期）、`2025/05/20`（官网 news 首发）、`2024-11-05`（MCP `PROTOCOL_VERSION`）、文献年份、git 哈希 `6f00efeb`、`temp/boundaries_2_4_5_deep_dive_2026-09-27.md` 等存档文件名 | **保留**：是世界/协议的事实不是我们的轮次戳；删了反而伤 references 严谨性 |

### 14.2 执行（1 个提交，69 文件 162 处）

| 提交 | 内容 |
|---|---|
| `6f6183b1` | 六类本轮时间戳全仓清除：references/ 8、static/ 3、rag/knowledge/ 4、evals/ 14、src/ 12、ops/ 1、test/ 22、根声明 4（README/architecture/manifest/io-contract）、docs/diagrams/ 2、docs/architecture/coverage-matrix.md、.gitignore 注释 4 处 |

轮次身份不丢：`Phase N`、`D2/E3/B4/E4`、`P0-3/P1-8`、「下载能力轮次」等标识全部留在原句；
实证方法（Crossref REST / 逐路由实测 / 实机浏览器深潜）、证据路径（`temp/*.json`）、
阈值数值一律保留 —— references 只失去「何时」，不失去「怎么知道的」。

### 14.3 工程约束与踩坑

1. **`.py` 零代码变动**：全部日期都在注释/docstring 里，`code_fingerprint.py check`
   报 `compared=140 code-changed=0`；`verify_no_code_loss.py` 0/38；
   `comment_audit.py` 六类计数全 0。
2. **跨行合并 4 处**（`citations.yaml`、`best_export.py`、`tap/adql.py`、
   `best_mcp_server.py`、`test_server_count_chain.py` 的括号日期独占一行），
   已按原注释排版折回，避免超长行。
3. **中文语法残留 7 处**已逐条修：「锚定 的 live」「, 的 live」「为 下载能力」
   「—— 主控按」「； 逐路由实测」「** 实测匿名会话挂起**」「行尾空格」。
4. **`.gitignore` 首批漏扫**：文件系统级复扫（`temp/verify_date_cleanup.py`，
   不受 gitignore 影响）才发现，补清 4 处。
5. **CRLF 归一**：`evals/probes.py`、`references/skills-spec.local.yaml`、
   `test/unit/meta/test_module_paths.py` 工作树为 CRLF，违反 `.gitattributes`
   的 `eol=lf`（仓库内 blob 本就是 LF），已归一并消除 autocrlf 警告。
6. **树门禁 FAIL 的真相**：`.workbuddy/memory/2026-09-28.md` 是工具重建的状态目录
   （§12.6 遗留 2 的同型复发），非本轮变更；按 Phase 9 对 `.workbuddy-ai/` 的裁定
   移入 `temp/.workbuddy/`，树清单回到 278，门禁转绿。

### 14.4 门禁结果（全绿）

ruff check 全过 / pytest **739 passed · 24 skipped** / 树 SSOT **278** /
evals `--mode all` **1.0000 SUCCESS**（25/25 场景 + 25/25 用例，6 审计器 0 failed，
docstring 100%）/ code_fingerprint code-changed=0 / verify_no_code_loss 0/38 /
comment_audit 六类全 0 / monorepo skill、strength、routing 三门禁全绿 /
日期复扫 241 文件 0 残留（豁免与外部事实按预期保留）。

---

## 15. Phase 11 —— 仓库拓扑收口与治理工具修复（用户第 11 轮指示）

### 15.1 本文档的基线空档（必须先说清）

本文档此前停在 **Phase 10**，其记录的基线是 **树 SSOT 278 条目 / pytest 739 passed**。
此后仓库又长了一整代，本文档**零覆盖**：

| 维度 | 本文档记录（Phase 10） | 本轮实测 |
|---|---|---|
| 树 SSOT 条目 | 278 | **675** |
| pytest | 739 passed / 24 skipped | **1175 passed / 24 skipped** |
| `evals/` Python 文件 | 27 | **96**（E1–E6 六套实验全部建成） |
| 净代码行超限 | 1（`client.py`） | 3（`protocol_catalog_tables.py` 662 / `client.py` 536 / `protocol.py` 483，**均已登记**） |
| 门禁条数 | 18 项脚本 | 18 项脚本 + `make audit` 五项硬门禁 |

**E1–E6 六套实验的建设轮次（`docs/eval-E1..E6-*.md` 为方案真值）**：E1 NL→工具决策 /
E2 金标准一致性 / E3 语义与幻觉 / E4 鲁棒与安全 / E5 基线与消融 / E6 可复现与效率，
各自自包含（零跨实验 import，唯一共享件 `evals/_data/`），跑批入口为
`make eval-e1..e6` / `make evals-all`。编号终版裁决见工作区长期记忆：
E5 归「基线与消融」，在线漂移检测顺延 E7、TAP 面一致性顺延 E8。

### 15.2 用户第 11 轮指示与裁定

用户指示：「使用 `astro-best/.git`；更新所有治理文档，继续苏格拉底提问修复所有问题」。

| # | 提问 | 裁定 |
|---|---|---|
| 1 | 父仓 `G:/tw/twskills` 用普通文件模式跟踪 `astro-best/**`（235 文件），要改成只由 `astro-best/.git` 管。移除跟踪要不要直接提交？ | **直接提交**（只 stage `astro-best` 相关，父仓其他无关改动不碰） |
| 2 | 子仓 55 个已跟踪文件未提交 + `ops/audit/` 未跟踪，怎么入库？ | **按主题分批提交** |
| 3 | 三份登记册基线过期（ISSUES / CODE-QUALITY-FIX-LIST / 本文档） | **加过期声明 + 补当前基线**（保留原文作取证历史） |
| 4 | `ops/audit` 九个工具 ROOT 三套基准并存、两处崩溃/误判 | **全部统一 + 接入门禁** |

### 15.3 执行（按主题分提交）

| 提交主题 | 内容 |
|---|---|
| 仓库拓扑 | 父仓 `git rm -r --cached astro-best` + 父仓 `.gitignore` 加 `astro-best/`，父仓一条提交；子仓文档写明"权威版本库 = `astro-best/.git`" |
| 行尾治理 | `.gitattributes`：修正 `*.ps1 text eolcrlf`（缺 `=`，无效属性）；补 `*.py/*.md/*.yaml/*.json/*.toml/*.txt text eol=lf`（与父仓同口径，解决 `core.autocrlf=true` 下 70 个 .py 工作区为 CRLF、与 `check_line_endings.py` 的 LF 约定互相矛盾）；数据类资产改为 `-text -eol` |
| 护栏修复 | `ops/audit/` 11 文件入库；九个工具 ROOT 统一 `parents[2]`；`verify_crossrefs.py` 修崩溃 + 4 个潜伏缺陷；`verify_no_code_loss.py` 改 token 序列比对并指向子仓；`verify_import_graph.py` 按「ops/ 路径调用，零 import」限定扫描范围 |
| 门禁扩展 | 新增 `TestGitTrackingCoverage`（`git ls-files --others --exclude-standard` 必须为空）；`make audit` 五项硬门禁接入 `make check` / `make all` |
| 文档回正 | CLAUDE.md（门禁清单 + 仓库拓扑 + E4 数字回正）、README 树清单重生成、三份登记册加过期声明、source-audit 标已修条目、`ops/audit/README.md` 修正两处误诊 |

### 15.4 本轮修出的"潜伏缺陷"（都不是本文档原有条目）

1. **`verify_crossrefs.py` 无法运行**：ROOT 只上溯两级（落在 `ops/`），第 162 行
   无保护的 `open(ops/src/scripts/config.py)` 直接 `FileNotFoundError`。
2. **同文件 `_src_file` 未定义**：`walk_collect_modules` 用了不存在的名字 —— 因 ROOT
   错位导致 `contracts/`/`templates/` 从未被真正遍历，这个 `NameError` **从未触发**。
3. **`<Class>.module` 键漏检**：`templates/gen_config_template.yaml` 的键是
   `BestAuth.module` 而非 `module`，于是"module 声明 0 条"却零问题 —— **静默空转**。
4. **`check_symbol` 把模块路径误判为属性链**：`src.download_manager` 被当作
   "`src` 的属性 `download_manager`"，7 处假失败。
5. **`verify_no_code_loss.py` 读错仓库**：ROOT 指向父仓，拿父仓陈旧 HEAD 当基线，
   把子仓早已提交的重写误报成"代码丢失"。原文把这类红归因为"基线过时"是误诊。
6. **`verify_import_graph.py` 会执行被测入口**：`ops/skill_cli.py` 与
   `ops/cloud_modelscope/run.py` 是 runpy 转发 shim，模块级 `run_path(..., "__main__")`，
   import 即执行 → 打印 CLI 用法后 `SystemExit(0)`，体检后半段全部不再执行。
7. **`.gitattributes` 的 `-text` 不清 `eol`**：`*.json text eol=lf` 先设了 `eol=lf`，
   后面 `evals/**/snapshots/** -text` 只清 `text` 属性，`eol` 残留 —— renormalize
   会把 27 个快照文件从 CRLF 改成 LF（实测 `git check-attr` 显示 `text:unset` 但
   `eol:lf`）。必须写 `-text -eol`。

### 15.5 遗留（不阻塞）

1. `verify_no_code_loss.py` 与 `scan_code_smells.py` 存在已知语义误报（删除重复定义 /
   正则字面量里的 TODO），故只作报告型工具，不入硬门禁；口径已写入
   `ops/audit/README.md` §已知局限。
2. `version_scan.py` 与 `version_scan2.py` 职责重叠（前者扫 A/B 两类，后者按
   外部事实白名单分类），后续可合并为单工具。
3. 本文档 §3 的覆盖矩阵与 `docs/architecture/coverage-matrix.md` 需按 675 条目的
   新树复核锚点有效性（本轮未展开）。
