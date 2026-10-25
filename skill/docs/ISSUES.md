---
title: astro-best 工程配置质量问题清单（历史归档，非活动问题清单）
scope:
  - Makefile
  - environment.yaml
  - schemas/message.proto
repository_root: astro-best/.git            # 2026-10-03 更正: 本字段原写 <SKILLS_ROOT>（称 monorepo、.git 在父级）,
                                          #   与本仓铁律矛盾 —— astro-best 是**独立 git root**, 父目录
                                          #   <SKILLS_ROOT> 是另一个仓且已不再跟踪本目录。git 类工具一律在本目录内跑,
                                          #   从父目录操作会让 ops/audit/ 里按 HEAD 比对的工具读错仓库。
method: 静态审查 + 本机实测取证 + 向父仓交叉验证 + 突变（mutation）实验
revision: 6                          # 2026-10-05: 全文归档为历史件 + 加状态横幅 + 补本轮复验证据;
                                   #   §1 索引表 58 条**仍未逐条回正**, 见 §A 的复验边界声明
status: archived                     # 2026-10-05: open -> archived。本文件不再是「待办问题清单」,
                                   #   不得作为「仓里现在还有 58 个问题」的依据被引用
total_findings: 58
blocking: 10
retracted: 2
fixed_by_others: 6
reverified_2026_10_05: 13            # 本轮以命令实测复验并回写横幅的条目数, 见 §A
---

# astro-best 工程配置问题清单（ISSUES）—— **历史归档件**

> # ⚠ 状态横幅：本文是**历史盘点记录**，不是当前问题清单
>
> **`status: archived`（2026-10-05）。** 本文的盘点基线是 **monorepo 时代**，
> 此后本仓经历了独立 git root 化、`src/` 平铺、`pybest` 单类删除、E1–E6 六套
> 实验建设、`ops/audit/` 护栏入库等变动。**58 条 finding 的盘点基线早已不成立。**
>
> **引用本文的硬规则**：
> 1. **不得**用本文 §1 索引表判断"本仓现在还有哪些问题"。索引表的 `☐` 列是
>    **revision 3 盘点当时的状态**，不是当前状态 —— 58 条**全部**标 `☐`，而其中
>    至少 13 条已在本轮被命令实测证伪或证成（见 **§A**），另有 2 条已撤回。
> 2. **不得**把本文当 TODO 来源。§7「修复批次建议」是当时的排序，不是今天的排期。
> 3. 判断当前仓库状态请用**活动门禁**：`make check`
>    （= `test` + `lint` + `verify` + `audit`）与 `python ops/audit/<tool>.py`。
> 4. 本文仍有**独立价值**的部分：§8 撤回与修订记录、§14 存疑项登记 ——
>    这两节记录的是**方法与判断依据**，不随基线漂移而失效。
>
> **为什么归档而不是逐条复验 / 为什么不做三表拆分**（2026-10-05 裁决）：
>
> 三个选项逐一评估过：
>
> | 选项 | 评估 | 结论 |
> |---|---|---|
> | (a) 逐条复验回正 | 58 条需要重跑构建层 / 评测层 / 契约层 + monorepo 交叉验证 + 突变实验。本轮不具备条件，且**其中 11 条 SCH-* 的取证对象（`schemas/`）已不存在**、相当部分结论引用 `tests/`、`src/astro_best/`、monorepo 根 —— **在不可复现的前提上做复验只会产出新的假结论** | 不做 |
> | (b) 归档为历史件 + 状态横幅 | 成本最低，且直接消灭"过期清单以问题清单姿态存在"这个危害。索引表 `☐` 保留原样以留痕，但横幅明确它不是当前状态 | **采纳** |
> | (c) 拆成「已修 / 未修 / 不适用」三表 | **只有 13 条能进「已修」**（§A），**11 条进「不适用」**，剩下 34 条只能进「未修」—— 而"未修"这个判断本身**没有证据支撑**，只是"没复验"。三表会把 34 个未经检验的条目盖上"确认未修"的章，比归档更危险 | 不采纳 |
>
> **(b) + 部分 (c) 的组合**：横幅归档（(b)），同时对**廉价可验**的 13 条真复验并
> 在 §A 落成一张带实测证据的表（这部分就是 (c) 想要的东西，但只填有证据的格子）。
> 剩下 45 条明确标为「未复验」，**不假装知道它们的状态**。

## A. 2026-10-05 复验记录（本轮唯一新增的现状证据）

复验方式：`python temp/G8_probe_issues.py`（脚本在 gitignored 的 `temp/`，
结论已写进本节；复算请直接跑同口径的静态判定）。**本节只记录实测到的结果，
不外推到未测条目。**

| Finding | 盘点主张 | 2026-10-05 实测 | 结论 |
|---|---|---|---|
| MK-01 | 测试目录名写错 `tests/` | `Makefile` 的 pytest 目标全部是 `test/ evals/`，`tests/` 零出现 | **已修**（与 §13 一致） |
| MK-02 | lint 范围仅 `src/` | `Makefile:39` = `ruff check src/ test/ evals/ rag/ ops/ examples/` | **已修**（§13 记的"部分修"已过时） |
| MK-03 | Makefile 全 CRLF + 无 `.gitattributes` | `.gitattributes` 存在；`Makefile` **CRLF=0 行 / 共 111 行** | **已修**（平台绑定部分见 §9 未实机验证） |
| MK-05 | `.PHONY` 只覆盖 6/11 | `.PHONY` 现列 26 个目标（`help`…`all`） | **已修** |
| MK-10 | 无 `.DEFAULT_GOAL` | `.DEFAULT_GOAL` 仍**未出现** | **仍成立**（P3，唯一本轮确认仍成立的条目） |
| SCH-01/02/03/04/05/06/07/08/09/10/11（11 条） | `schemas/message.proto` 占位符 / 契约缺陷 | `schemas/` 目录在本仓**不存在** | **不适用**（资产已迁移至 `contracts/`）—— 11 条中的"Proto 无 presence"等主张已无对象可评 |
| X-02 | `tests/` vs `test/` 命名漂移 | `tests/` 目录在本仓**不存在** | **已修**（与 §13 一致） |
| YAM-02 | `manifest.yaml` 悬空引用 `static/fragments/target_type/best_catalogs.md` | `manifest.yaml` 中该错误路径**零出现**（现指向 `data_source/`） | **已修** |
| YAM-03 | 两个 YAML 带 BOM | 全仓 `*.yaml` 逐个读首 3 字节，**BOM 残留 0 处** | **已修** |
| EVAL-01/02/03 | 评测层 fail-open（删契约仍 SUCCESS） | `evals/eval_runner.py` 存在、`evals/cases/` 25 份 case 在库。**revision 4 核账表**（本文 §"revision 4 核账"末行）已记「25 cases 全部含 `given:` 且 runner 消费；副本上删 `contracts/` → FAILED 退出码 1（provenance 维 0.0）→ 已修，突变实验复验通过」 | **已修**（依据 revision 4 的突变实验记录；**本轮未重跑该实验**，只核了 case 数与 runner 在库） |
| TST-01 | `test/_archive` 18 个文件整模块静默 skip | `test/_archive` 目录**不存在** | **已修/不适用**（资产已移除） |
| TST-05 | `test/conftest.py` 内置契约副本 | `test/conftest.py` 仍存在，但**本轮未逐行核实**其是否仍有硬编码副本 | **未复验** |

**复验边界（必须连同上表一起读）**：

- 本表**只**覆盖**廉价静态可判**的 13 条。其余 **45 条未复验** ——
  它们的取证前提是跑构建、跑评测、突变实验或跨 monorepo 交叉验证，
  本轮**没有重跑**，因此**不得**从"本表都是好消息"推出"剩下的也没问题"。
- EVAL-01/02/03 虽在 §A 列为已修，依据是 **revision 4 核账表里那次突变实验的记录**
  （不是本轮实跑）。本轮只核了 `evals/cases/` 25 份 case 与 runner 在库。
  要独立结案仍应重跑"删 `contracts/`"实验 —— 引用这条时须带上这个限定。
- YAM-01（`case_014/015/016` 硬语法错 + runner 字符串补丁）本轮**未复验**：
  `evals/cases/` 有 25 份 case（含 014–016），但未逐个 `safe_load`。

## ⚠ 以下为 revision 5 及更早的原文（历史内容，逐字保留）

**本文的盘点基线是 monorepo 时代**：条目大量引用**已不存在的路径** ——
`schemas/message.proto`（资产已迁移到 `contracts/`）、`sync/`（目录已不存在）、
`src/astro_best/` 包布局（现已平铺为 `src/`）、`tests/`（已改名 `test/`）。
revision 4 已自陈"仓库现状远不同于 revision 3 的盘点基线"，此后仓库又经历
E1–E6 六套实验建设、`pybest` 单类删除、`ops/audit/` 护栏入库等变动。

**引用本文时请先做三件事**：
1. 对任何"某文件/某引用不存在"的否定结论，先到仓根重跑一次核实命令
   （方法论见本文 §8 结尾）；
2. 用当前基线复核条目是否仍成立 —— 已知**已修但本文未回正**的至少两例：
   EVAL-01/02/03（evals fail-open，revision 4 已判"已修，突变实验复验通过"，
   但 §1 索引表仍标 `☐`）、SCH-* 全族（`schemas/` 已不在本仓）；
3. 已确认修复的条目见本文 §13 与本仓 `CHANGELOG.md`。

**当前有效的复测入口**（不要用本文 §2–§5 里的旧命令）：
`make check`（= `test` + `lint` + `verify` + `audit`）与 `python ops/audit/<tool>.py`。

---

## revision 4 核账（2026-09-30 完善轮，逐条实测复验，历史内容不动）

> 仓库现状已远不同于 revision 3 的盘点基线：`astro-best/` 已独立成 git root
> （原 monorepo 子目录），`src/` 平铺、`pybest` 单类删除、`evals/` 六实验建成。
> 本轮对 P0/P1 关键 finding 逐条复验，结论如下（证据命令见各项）：

| Finding | revision 3 主张 | 2026-09-30 实测 | 结论 |
|---|---|---|---|
| MK-01 测试目录名 | `make test` 4 目标全失效 | Makefile 用 `test/ evals/`，`tests/` 零出现 | **已修** |
| MK-02 lint 范围 | 只扫 40%，漏 283 条 | `ruff check src/ test/ evals/ rag/ ops/ examples/`；`sync/ scripts/` 在本仓已不存在（monorepo 时代目录） | **已修** |
| MK-03 平台绑定 | make 不可用 + Makefile 全 CRLF + 无 .gitattributes | 本机仍无 make（目标命令已逐条直跑验证）；Makefile 已归一为 **纯 LF**；新增 `.gitattributes`（Makefile/\*.sh 钉 LF，snapshots/fixtures/csv 钉 -text） | **本轮已修**（make 缺席是环境事实，目标命令均有等价 python 直跑形态） |
| ENV-02 pyyaml 漏声明 | pyproject dependencies 无 pyyaml，兜底静默丢配置 | 本仓 pyproject **无构建段**（源码树分发，无 `pip install -e .` 路径）；Makefile `install` 目标含 `pyyaml`；`evals/_data` 等 YAML 消费方在装机后可用 | **按设计消解**（无 install 路径可漏；维持 Makefile install 清单即正确单点） |
| SCH-01′ message.proto 占位符 | 11 行占位符，与 SSOT 相反 | `schemas/` 在本仓不存在；契约面由 `contracts/` 9 份真契约承担（envelope/error-codes/provenance 等） | **不适用**（资产已迁移） |
| §11 evals/ 假评测 | 删 contracts/ 仍 0.9200 SUCCESS；given 使用 0 次 | 25 cases 全部含 `given:` 且 runner 消费；**副本上删 contracts/ → FAILED 退出码 1**（provenance 维 0.0） | **已修**（Phase 5 重建后门禁真实依赖契约；突变实验复验通过） |

其余 P1/P2/P3 条目（YAML 孤儿、conftest 契约副本、environment.yaml 可消费性等）
属本次点杀范围外，判据不变：**主张仍成立的才继续算债**。下轮按同口径逐节复验。

---

> 本清单覆盖 **构建门禁层（Makefile）**、**运行环境声明层（environment.yaml）** 与 **数据交换契约层（`schemas/message.proto`）** 的专项审查。
> 所有"证据"栏均为本机（Windows / PowerShell / 无 conda / 无 make）实测输出，非推断；无法实测的条目已单独标注 **[未实机验证]**。

## ⚠ 范围声明（revision 2 新增，必读）

**本项目的仓库根不是工作区，而是 monorepo `<SKILLS_ROOT>`**（`.git` 实测存在于该级），`astro-best\` 只是其中一个 skill 子目录。这直接决定了路径判定的基准：

| 事实 | 实测 |
|---|---|
| monorepo 根 `.git` | ✅ 存在 |
| monorepo 根 `tests/`（复数） | ✅ 存在 |
| monorepo 根 `src/` / `pyproject.toml` / `Makefile` | ❌ 全部不存在 |
| monorepo 根 `scripts/refactor/materialize_contracts.py` + `spec/skills-spec.yaml` | ✅ 均存在 |
| monorepo 根 `_shared/skill-engine/pipeline-contract.md` | ✅ 存在 |
| monorepo 根 `.github/workflows/ci.yml` | ✅ 存在 |

revision 1 把"仓库"等同于工作区目录，导致 2 条结论错误、1 条降级，已在 **§8 撤回与修订记录** 中逐条留痕（不静默删除）。

唯一不受影响的反向结论：Makefile 的 `tests/` **不能**用"上级有 tests/"辩护 —— 若在 monorepo 根执行，`ruff check src/` 与 `pip install -e .` 会因根上无 `src/`、无 `pyproject.toml` 立即失败。故 Makefile 只能在 `astro-best\` 内使用，那里 `tests/` 确实不存在（见 MK-01 修订根因）。

---

## 0. 严重度定义与总览

| 级别 | 判定标准 | 数量 |
|---|---|---|
| **P0 阻断** | 命令必然失败 / 静默丢数据 / 门禁形同虚设 | 10 |
| **P1 高** | 结论与事实相反、跨文件冲突、关键能力缺失 | 24 |
| **P2 中** | 可维护性与可复现性缺陷，不直接致错 | 19 |
| **P3 低** | 形式与风格 | 5 |
| （已撤回） | revision 1 误判，保留原文与撤回依据于 §8 | 2 |
| （他人已修） | revision 3 发现并发修复，见 §13 | 6 |

| 域 | 结论 | 评级 |
|---|---|---|
| `Makefile` | revision 3 时已被大幅修复（见 §13）；lint 仍缺 `sync/ scripts/ examples/ evals/ rag/` | **C+**（由 D+ 上调） |
| `environment.yaml` | conda 无法消费；自称"核对生成"的注释被自身内容证伪；零引用孤儿 | **D+**（语法 A / 可消费性 F / 真实性 F / 集成度 F） |
| `schemas/message.proto` | 11 行占位符，字段集与 monorepo SSOT 相反；同族 4 个兄弟均为 23–76 行真契约 | **F**（语法 B / 与 SSOT 一致性 F / 完成度 F / 接线 0） |
| `*.yaml`（50 个） | 无重复键/无 tab/无空文件，但 **3 个硬语法错 + 8 个真孤儿（另 16 个仅靠 glob）** | **C**（语法 B- / 一致性 C / 接线 D） |
| `evals/` | runner 报 **1.0000 满分**，但删除整个 `contracts/` 后仍得 **0.9200 → SUCCESS**；`given` 输入使用次数 = 0 | **F**（假评测，见 §11） |
| `test/` | 128+34+13 真测试、断言密度健康；但 ≥20 个整模块静默 skip + conftest 内置硬编码契约副本 | **B-**（本体良好，边界失真） |

---

## 1. 问题索引

| ID | 级别 | 文件 | 标题 | 状态 |
|---|---|---|---|---|
| MK-01 | P0 | Makefile | 测试目录名写错 `tests/` vs `test/`，4 个测试目标恒失败 | ☐ |
| MK-02 | P0 | Makefile | lint 范围仅 `src/`，漏掉 60%（283/474）代码债 | ☐ |
| MK-03 | P0 | Makefile | 全文件绑定 POSIX，Windows 环境不可执行 + 全 CRLF | ☐ |
| ENV-02 | P0 | environment.yaml × pyproject | `pyyaml` 漏声明 + 静默兜底 → 用户配置被无声丢弃 | ☐ |
| ENV-04 | P0 | environment.yaml | 注释宣称"按真实 import 核对生成"，被自身内容三处证伪 | ☐ |
| MK-04 | P1 | Makefile | `clean` 清 4 个不存在路径、漏 3 类真实产物 | ☐ |
| MK-05 | P1 | Makefile | `.PHONY` 仅覆盖 11 个目标中的 6 个 | ☐ |
| MK-06 | P1 | Makefile | `test-cov` 覆盖率目标错位，产不出人可读报告 | ☐ |
| MK-08 | P1 | Makefile × CI | ~~仓库无 CI~~ **已改写**：monorepo 有 CI，但它从不执行 astro-best 的 Makefile，两条链路互不相交 | ☐ |
| ENV-01 | P1 | environment.yaml | 缺 `name:`，`conda env create` 拒绝消费 | ☐ |
| ENV-03 | P1 | environment.yaml | `urllib3` 为直接 import 却被注释降级为"传递依赖" | ☐ |
| ENV-06 | P1 | environment.yaml × bridge | `conda_env` 同名不同值（`astro-best` vs `astro-base`） | ☐ |
| ENV-07 | P1 | environment.yaml | 声明 `pip` 却不装本项目，环境建好仍 `import` 失败 | ☐ |
| ENV-08 | P1 | environment.yaml | 自称"运行环境锁"，实为纯 `>=` 下限，锁不住任何东西 | ☐ |
| X-01 | P1 | 跨文件 | 依赖声明三头分叉（pyproject / environment.yaml / 真实 import） | ☐ |
| X-03 | P1 | 跨文件 | 无任何安装入口文档，新用户无法装配 | ☐ |
| MK-07 | P2 | Makefile | 无变量抽象、无 `help`、缺 `build`/`eval`/`contract-check` | ☐ |
| MK-09 | P2 | Makefile | `make lint` 当前为红（191 条），`check`/`all` 必然失败 | ☐ |
| ENV-05 | P2 | environment.yaml | 零引用孤儿文件 | ☐ |
| ENV-09 | P2 | environment.yaml | `conda-forge` + `defaults` 混源，无 `nodefaults` | ☐ |
| ENV-10 | P2 | environment.yaml | dev 与 runtime 平铺同层，未用 `categories:` | ☐ |
| X-02 | P2 | 跨文件 | `tests/` vs `test/` 命名漂移扩散至 SKILL.md / architecture.md | ☐ |
| SCH-03 | P0 | schemas × SSOT | proto 的 `BestSkillInput` 与 monorepo SSOT 的 `BestQuery{sql, token}` 相反 | ☐ |
| SCH-02 | P1 | schemas | 为项目不用的技术（protobuf）写契约；真实 wire format 是 REST + JSON-RPC 2.0 | ☐ |
| SCH-04 | P1 | schemas | proto3 无 presence：`(ra=0, dec=0)` 与"未提供"不可区分；`radius_arcsec` 隐式默认 0 | ☐ |
| SCH-08 | P1 | schemas × contracts | 完全绕过 envelope 层（`data_hash` / `provenance` / `checkpoint` / `human_review` 零映射） | ☐ |
| SCH-09 | P1 | schemas × src | 字段拼自两个不同实现且漏 `catalog`；`radius_arcsec` 全仓有 60/180/600/0 四种默认值 | ☐ |
| SCH-11 | P1 | schemas × astro-rag | 契约副本已扩散进 RAG 知识库（≥2 份 proto + `pybest-0.3.2.8` 快照），改契约不同步即检索到陈旧件 | ☐ |
| SCH-01 | P2 | schemas | proto 零接线（无 `protoc`、无 `*_pb2`、无 manifest 条目）—— 属**全家族常态**，非本仓孤例 | ☐ |
| SCH-05 | P2 | schemas | 违反项目 `unit:` 约定，`ra`/`dec` 无单位标注（度/弧分/弧度歧义） | ☐ |
| SCH-06 | P2 | schemas | 无 `package` 声明 + 文件名 `message.proto` 无语义 | ☐ |
| SCH-07 | P2 | schemas | 半张契约：只有 Input，无 Output/Status/Error（`contracts/` 侧五样齐全） | ☐ |
| X-04 | P2 | 跨文件 | 项目未声明路径基准（工作区=子目录，SSOT/CI/生成器=monorepo 根），MK-01 与 SCH-10 同源根因 | ☐ |
| SCH-10′ | P3 | contracts | ~~生成器与 SSOT spec 不存在~~ **已撤回**，改为：注释中相对 monorepo 根的路径未写明基准 | ☐ |
| EVAL-01 | P0 | evals | **整个评测层 fail-open**：删除全部 `contracts/` 仍得 0.9200 ≥ 0.9 → SUCCESS | ☐ |
| EVAL-02 | P0 | evals | 7 个 gate 用例把阈值与自身比较，全程不 import 任何门禁实现（零突变敏感度） | ☐ |
| EVAL-03 | P0 | evals | 用例的 `given` 输入在 runner 中出现次数 = **0**，16 个用例的输入夹具全部未使用 | ☐ |
| YAM-01 | P0 | evals/cases | case_014/015/016 硬 YAML 语法错（ScannerError），靠 runner 内置字符串补丁掩盖 | ☐ |
| TST-05 | P1 | test/conftest.py | 内置 `_DEFAULT_SPEC` 硬编码契约副本 + 三级降级“保证绝不报错” → 契约丢失测不出 | ☐ |
| TST-01 | P1 | test/_archive | 18 个上游回归测试文件全部整模块静默 skip，却占据目录看起来像覆盖 | ☐ |
| TST-02 | P1 | test/unit · integration | `test_auth_store.py` / `test_server_api.py` 因目标模块不存在而整文件 skip | ☐ |
| EVAL-04 | P1 | evals | field/input 用例 = 文件存在性；scope 用例 = `len(in_scope)>=3`，spec 缺失时 **passed=True** | ☐ |
| EVAL-05 | P1 | evals | 未知 scenario id → `passed=True`；algorithm 正则未命中 → `passed=True`（均已实测） | ☐ |
| EVAL-10 | P1 | evals | 5 个 scenario 只做 `hasattr` 存在检查，不执行任何查询行为 → 与 test/ 重叠且更弱 | ☐ |
| YAM-02 | P1 | manifest.yaml | 资产清单悬空引用：`static/fragments/target_type/best_catalogs.md`（实际在 `data_source/`） | ☐ |
| YAM-04 | P1 | *.yaml | **8 个真孤儿 + 16 个仅靠 glob 发现**（共 24/50 未被显式接线） | ☐ |
| YAM-05 | P2 | static/fragments | 同目录内 schema 不一致（`fragment` 包装 vs 裸键），三种形态 | ☐ |
| YAM-06 | P2 | templates | `best-config.yaml`（运行时参数）与 `config_template.yaml`（类能力矩阵）都叫 config，互不引用 | ☐ |
| EVAL-06 | P2 | evals | runner 已被 `make eval` 接线，但 monorepo CI 不含 `eval` 也不含 `astro-best` → 评测仅在本地 | ☐ |
| EVAL-07 | P2 | evals | 用 `assert` 做校验 → `python -O` 下退化为空操作，实测仍报 5/5 与 1.0000 | ☐ |
| EVAL-08 | P2 | evals | `_evaluate_gate` 对 None/str 做 `float()` → TypeError 未被用例循环捕获（实测 RAISES），一个非法阈值即崩整个 runner | ☐ |
| EVAL-09 | P2 | evals×rubric | 兜底分 0.85 == WARN 线 0.85 → 契约缺失维度仍标 PASS；权重和未校验 | ☐ |
| TST-03 | P2 | test/integration·live | 6 个 live 用例需 `PYBEST_RUN_LIVE=1`，默认链路 0 执行 → 真实 HTTP/checksum 从未验证 | ☐ |
| TST-04 | P2 | test | `scripts/repair.py`、`services/mcp_client.py` 全测试零引用（32 模块中 2 个） | ☐ |
| YAM-03 | P3 | *.yaml | `evals/test-scenarios.yaml`、`templates/best-config.yaml` 带 UTF-8 BOM（PyYAML 容忍，其他工具不稳） | ☐ |
| YAM-07 | P3 | environment.yaml | 已新增 `name:`（他人并发修复），但第 1–3 行 ENV-04 虚假注释仍在 | ☐ |
| MK-10 | P3 | Makefile | 无 `.DEFAULT_GOAL`，目标可读性靠注释硬撑 | ☐ |
| ENV-11 | P3 | environment.yaml | 25 行全 CRLF + U+2500 装饰分隔线 + 分组标签名不副实 | ☐ |

---

## 2. P0 阻断级

### MK-01 — 测试目录名写错，4 个测试目标全部失效

**现象**　[Makefile](../Makefile) 第 10/13/16/19 行统一使用 `tests/`（复数），仓库真实目录为 [`test/`](../test)（单数）。

**证据**
```
$ python -m pytest tests/ -q
ERROR: file or directory not found: tests/
no tests ran in 0.00s
```

**根因**（revision 2 升级）　[pyproject.toml](../pyproject.toml) 第 40 行 `testpaths = ["test"]` 本来就是对的；Makefile 用显式错误路径把正确配置**覆盖**掉了。而 `tests/`（复数）在 **monorepo 根 `<SKILLS_ROOT>\tests\` 确实存在** → 这不是手误，而是**路径从 monorepo 根抄进子目录**导致的基准漂移（与 X-04、SCH-10′ 同源）。已排除"整份 Makefile 是按 monorepo 根写的"这一辩护：根上无 `src/`、无 `pyproject.toml`、无 `Makefile`，若按根执行则 `ruff check src/` 与 `pip install -e .` 立即失败。

**影响**　`test` / `test-cov` / `test-unit` / `test-integration` 四个目标全部不可用。失败信息为"目录不存在"，极易被误读为"本项目没有测试"，而实际 `test/` 下有 **36 个** `test_*.py`（不含 `test/_archive/`）。

**修复**　删除显式路径，让 `testpaths` 生效；或改为 `test/`。
**验证**　`make test` 收集到非零用例且退出码为 0。

---

### MK-02 — lint 门禁只覆盖 40% 的债，绿了也不代表仓库干净

**现象**　第 22 行 `ruff check src/`，扫描范围排除 `test/ sync/ scripts/ examples/ evals/ rag/`。

**证据**
| 范围 | Ruff 报错数 |
|---|---|
| `ruff check src/`（= `make lint`） | **191** |
| `ruff check .`（全仓） | **474** |

漏报的 **283 条（60%）** 分布：`test/ 162`、`sync/ 116`、`scripts/ 4`、`examples/ 1`。

**根因**　既有决策「lint 范围从 `src/` 扩展至全仓 `ruff check .`」**从未落地到文件**。

**影响**　门禁双向失真：`make lint` 通过 ≠ 仓库干净；`sync/`（修复集镜像）与 `test/` 的回归债完全无人看守。

**修复**　改 `ruff check .`；若需临时豁免 `sync/`，必须显式写明豁免清单与债务台账，禁止静默漏扫。
**验证**　`make lint` 报错数与 `ruff check .` 一致。

---

### MK-03 — 整份文件绑定 POSIX，而开发环境是 Windows

**现象**　三处平台假设叠加：
1. 本机 `make --version` → 命令不存在，11 个目标全部无法调用；
2. 第 33–35 行 `clean` 用 `rm -rf`，即便装了 Windows 版 make（走 cmd.exe）也逐行报错；
3. 文件行尾实测 **CRLF = 38、纯 LF = 0**。

**影响**　当前环境下 Makefile 的全部价值 = 0；反向搬到 Linux/CI 时，GNU make 会把 `\r` 吃进 recipe 与 `.PHONY` 列表，产生"目标不匹配 / recipe 无法执行"的诡异失败。与仓库既有隐患「Git autocrlf 且缺 `.gitattributes` → 幽灵改动」同源。

**修复**　① 命令跨平台化（`RM ?= rm -rf` + 提供 PowerShell 等价 `.PHONY` 目标，或统一走 `python -m` 脚本）；② 新增 `.gitattributes`：`Makefile text eol=lf`。

---

### ENV-02 — `pyyaml` 漏声明 + 静默兜底 = 用户配置被无声丢弃

**现象**　`src/scripts/config.py` 与 `rag/astro_rag.py` 真实 `import yaml`（坐标订正 R2 2026-10-05：原文写 `src/astro_best/scripts/config.py:68` 与 `rag.py:63` —— 前者的路径**从未存在**（本仓无 `src/astro_best/` 目录），真实位置是 `src/scripts/config.py` 的延迟 `import yaml`；后者是省了目录的短路径，真实位置 `rag/astro_rag.py`）；[environment.yaml](../environment.yaml) 第 12 行正确声明了 `pyyaml>=6.0`，但 **pyproject.toml `dependencies` 完全没有它**。

**证据**
```
$ Select-String pyproject.toml -Pattern 'yaml'
（无匹配）
```
失败路径见 [config.py](../src/astro_best/scripts/config.py)：
```python
try:
    import yaml
    ...
except (FileNotFoundError, ImportError):
    return cls()          # ← 缺 pyyaml 不报错、不崩溃
```

**根因**　依赖声明双头维护 + 兜底逻辑把 `ImportError` 与"文件不存在"混为同一处理。

**影响**　**本清单中危害最大的一条。** `make install` 的 `pip install -e .[dev]` 装出的环境缺 pyyaml → `AstroBestConfig.from_yaml()` 静默返回默认值，用户按 `templates/best-config.yaml` 写的参数全部失效，且日志零提示。直接违反项目「配置文件防覆盖」红线。

**为何长期未暴露（revision 2 新增）**　monorepo 根 CI 的依赖安装步骤是：
```yaml
# <SKILLS_ROOT>\.github\workflows\ci.yml
pip install astropy pydantic numpy pyyaml scipy pytest pytest-timeout
```
→ **CI 显式装了 pyyaml**，在 CI 里永久掩盖了 pyproject 的漏声明。只有在"纯按 pyproject 装"的本地/他人/交付环境里才会触发静默丢配置。同类掩盖：CI 装了 `pydantic`，而 `src/astro_best` 全量实测 **零 pydantic 使用**（仅 6 处 `@dataclass`）。

**修复**　① pyproject `dependencies` 补 `pyyaml>=6.0`；② `except` 拆分：`ImportError` 必须 `logger.error` 或抛错，只有 `FileNotFoundError` 允许降级。
**验证**　在无 pyyaml 的干净 venv 中 `pip install -e .[dev]` → 调用 `from_yaml` 应显式报错而非静默返回。

---

### ENV-04 — "按真实 import 核对生成"的注释从未真正执行

**现象**　第 2–3 行注释是对全文件的可信度背书，被自身内容证伪三处：

| 注释断言 | 实测事实 |
|---|---|
| "标准库覆盖其余" | 第 12 行就把 `pyyaml`（非标准库）列为硬依赖 —— 自相矛盾 |
| "tqdf/rich 为 CLI 可选增强" | deps 中 **`tqdm` 无任何声明**；`rich` 声明了但全仓无人 import |
| "astropy/numpy 供下游契约互操作（导入面存在）" | src 真实 import 面中 **numpy / astropy 均未出现** |

src 真实第三方 import 面（实测去重）：`requests`、`urllib3`、`pandas`、`yaml`，其余全部为标准库。

**影响**　注释型虚假保证比没有注释更糟 —— 后来人会据此认定依赖面已被机器核对过，从而跳过验证。

**修复**　注释降级为"人工整理，未机器核对"，或直接删除并改为由脚本生成 + CI 校验（可用 `python -m pip check` + `isort --check` / `deptry` 类工具）。

---

## 3. P1 高

### MK-04 — `clean` 扫不存在的路径，真实产物一个没清
| Makefile 声明 | 是否存在 |
|---|---|
| `.checkpoints/` `data/` `logs/` `cache/` | ❌ 4 个全部不存在（空清） |
| `best_data/`（`.gitignore` 已登记） | ✅ 存在，**未清** |
| `.coverage`（`.gitignore` 已登记） | ✅ 存在，**未清** |
| `test/unit/__test_tmp__/` | ✅ 存在，**未清** |
| `__pycache__/` | 只删顶层，`src/**`、`test/**` 嵌套缓存全留 |

**修复**　路径对齐 `.gitignore`，递归清理用 `find . -name __pycache__ -type d -prune -exec rm -rf {} +`。

### MK-05 — `.PHONY` 漏 5 个目标
第 4 行只声明 `install test lint check clean`，缺 `test-cov`、`test-unit`、`test-integration`、`lint-fix`、`format`。一旦出现同名文件或目录，make **静默跳过并返回成功** —— 典型"假绿"。

### MK-06 — `test-cov` 产不出人可读报告
`--cov=src` 在 hatchling src-layout 下应指向包名 `astro_best`；缺 `--cov-report=term-missing`，跑完只落一个二进制 `.coverage`；亦未带项目约定的 `-p no:cacheprovider`。

### MK-08 — Makefile 与 monorepo CI 两条链路互不相交　*(revision 2 完整重写，原结论已撤回)*

**原误判**　"仓库无 `.github/workflows/`，Makefile 是唯一门禁" —— 仅在子目录内检索，未向 monorepo 上级验证。

**实测修正**：
- `<SKILLS_ROOT>\.github\workflows\ci.yml` **存在**（`windows-latest`），其引用的 `scripts/governance/lock/verify-astro-all.ps1`、`scripts/governance/gen-lot-contracts.py --check`、`tests/test_astro_skill_registry.py` **全部实测存在**。
- CI 含 6 个步骤：治理门禁（structure / isomorphism / **static contracts**）→ 架构与门面单测 → astro-core 基础设施 → virtual night pipeline + gold standards + regressions → physical twin → 契约幂等 `--check`。

**真问题**：CI 跑的是 **monorepo 根 `tests/` + governance 脚本**，**从不执行 astro-best 的 `Makefile`**；而 Makefile 指向的 `test/`、`src/`、`contracts/`、`evals/` 又**不在 CI 步骤里**。两条链互不相交 → 修 Makefile 不会让 CI 变绿，CI 绿也不证明 astro-best 本地门禁过。另：CI 用 Python **3.13**，与本仓 `requires-python>=3.10` / ruff `target-version=py310` / environment.yaml `python>=3.10` 构成四处版本语义不一致（归入 ENV-08）。

**修复**　在 CI 增一个 per-skill 步骤（至少 `pytest astro-best/test -q` + `ruff check astro-best/`），或将 astro-best 门禁入录 governance 脚本；二者均选一即可使两链相交。

### ENV-01 — 缺 `name:`，conda 拒绝消费　**[未实机验证：本机无 conda]**
第 4–5 行使用自造顶层键 `skill_name` / `conda_env`，而 conda `env create` 规范只认 `name:` 或 `prefix:`，自造键一律忽略 → `conda env create -f environment.yaml` 报 `You must specify a name`。**一份 26 行的"运行环境"文件建不出环境。**

### ENV-03 — `urllib3` 是直接依赖却被注释降级
`src/client.py` 真实 `from urllib3.util.retry import Retry`（坐标订正 R2 2026-10-05：原文写 `pybest.py:40` 与 `client.py:28` —— `src/pybest.py` 已由提交 `456149e`「pybest 双副本合并删除」**整体删除**，`client.py:28` 也已漂，该 import 现落在第三方 import 段）；注释称"urllib3 随 requests 传递"。直接 import 一个未声明的传递依赖，正踩 urllib3 1.x→2.x 的 Retry 语义与 OpenSSL 版本断代风险。修复：显式声明 `urllib3>=1.26,<3`。

### ENV-06 — `conda_env` 同名不同值
| 来源 | 值 |
|---|---|
| [bridge/register-astro-best.ps1](../bridge/register-astro-best.ps1) 第 18 行 / 同名 `.sh`（真实注册入口） | `astro-base` |
| environment.yaml 第 5 行 | `astro-best` |

且 environment.yaml 因 ENV-01 两个名字都建不出来。旁证同文件 `version: "0.2.0"` vs pyproject `0.3.2.6` —— 整仓版本漂移。

### ENV-07 — 声明 `pip` 却不用它装本项目
第 13 行把 `pip` 列入 conda deps，第 22–24 行 `pip:` 段只放 `rich`/`ruff`，**没有 `- -e .`** → 环境建好后 `import astro_best` 仍失败。占了 pip 的位，没干 pip 的活。

### ENV-08 — "锁"字不成立
9 个约束全为 `>=` 下限，**0 上界、0 sha256、无 `explicit` / platform 段**，两次求解结果可完全不同。三处版本语义互不认识：conda `python>=3.10`（会解到 3.13/3.14）、pyproject `requires-python>=3.10`、ruff `target-version="py310"`。真锁需 conda-lock。

### X-01 — 依赖声明三头分叉（结构性根因）
`pyproject.toml`（被 `pip install` 消费）/ `environment.yaml`（无人消费）/ 真实 import 面（无人机器校验）三者互相抄写且已漂移。完整差异表见 **§6 附录 A**。

### X-03 — 无任何安装入口文档
`README.md` 中 `install|conda|pip|依赖|环境` 关键词命中 **0 行**；Makefile 需要 make（本机无）；environment.yaml 是零引用孤儿。**三条路径同时断链，新用户无法从文档完成装配。**

---

## 4. P2 / P3

| ID | 级别 | 问题 | 要点 |
|---|---|---|---|
| MK-07 | P2 | 无变量抽象与扩展目标 | `python`/`pip`/`ruff` 全硬编码，无法切 uv/conda；无 `help`；项目核心是契约驱动 + 双层评测（`contracts/`、`evals/cases/` 16 个 case），却**没有 `make eval` / `contract-check` / `gate`**；hatchling 已配好打包却无 `build` |
| MK-09 | P2 | 门禁当前必红 | `ruff check src/` 已有 191 条 → `make check` / `make all` 今天必然失败，而 `all` 末尾仍无条件 `echo "validation passed"`，语义误导 |
| ENV-05 | P2 | 零引用孤儿 | 全仓（README / SKILL / manifest / Makefile / pipeline.yaml / evals / agents / CI）对 `environment.yaml` 引用数 = **0**，唯一提及是它自己的第 1 行 |
| ENV-09 | P2 | channel 混源 | `channels: [conda-forge, defaults]`：`defaults` 属 Anaconda 官方源（机构/商业使用 ToS 敏感），且与 conda-forge 对 numpy/pandas/astropy 依赖链混解是经典 ABI 冲突源；缺 `nodefaults` |
| ENV-10 | P2 | 依赖不分层 | pytest / pytest-cov / ruff / rich 与 requests 平铺同层，未用 conda ≥23.10 的 `categories:` → 生产环境被迫装测试框架 |
| X-02 | P2 | 命名漂移扩散 | `tests/`（复数）同样出现在 `SKILL.md:75`、`architecture.md:10`、`sync/SKILL.md:96`，非 Makefile 孤例，属全仓文档与实际目录不一致 |
| MK-10 | P3 | 无 `.DEFAULT_GOAL` | 裸 `make` 落到 `install`（有副作用），不符合"首眼给帮助"惯例 |
| ENV-11 | P3 | 形式层 | 无 BOM（✅ 避开 `utf-8-sig` 已知坑），但 25 行全 CRLF，缺 `.gitattributes` 保护；注释用 U+2500 装饰分隔线，cp936 终端显示乱码；第 18 行分组标签"本地工具 (G8)"下挂的是 pytest/pytest-cov，标签名不副实（G8 本身在 `architecture.md:64` 有定义，非悬空编号） |

---

## 5. schemas/message.proto 契约层（SCH-*）

全文 11 行，有效内容 5 个字段，第 1 行作者自标 `(placeholder)`；`schemas/` 目录仅此一件。

```protobuf
// astro-best data exchange schemas (placeholder)
syntax = "proto3";

message BestSkillInput {
  double ra = 1;
  double dec = 2;
  double radius_arcsec = 3;
  string band = 4;
  bool quality_filter = 5;
}
```

### 契约四要素判定

| 要素 | 状态 | 证据 |
|---|---|---|
| 有约束对象 | ❌ | 全仓（含 monorepo 上级）搜 `message.proto\|BestSkillInput\|protobuf\|protoc \|grpc\|schemas/` → **0 真实命中**（唯一命中为 `arxiv_lit_survey.py` 的 arxiv atom 命名空间，无关） |
| 有绑定实现 | ❌ | 全 monorepo 无任何 `*_pb2.py` / `*_pb2_grpc.py` / `protoc` / `grpc_tools` 调用点 |
| 有校验器 | ❌ | `test_gen_contracts.py` 只校验 `contracts/fields/` 的 4 个文件，不触及任何 proto 字段 |
| 有门禁与血缘 | ❌ | `manifest.yaml` 资产清单列 `contracts/io-contract.md`，**`schemas/` 从未出现** |

### SCH-03 · P0 · 字段集与 monorepo SSOT 相反（冲突已有裁判）

上级 SSOT `<SKILLS_ROOT>\scripts\refactor\spec\skills-spec.yaml` 原文：
```yaml
astro-best:
  input:
    schema: BestQuery
    fields:
      sql: {type: string, unit: "dimensionless", source: master-plan}
```

| 来源 | schema 名 | 字段 |
|---|---|---|
| **monorepo SSOT** + `contracts/input.contract.yaml` | `BestQuery` | `sql`, `token` |
| `schemas/message.proto` | `BestSkillInput` | `ra`, `dec`, `radius_arcsec`, `band`, `quality_filter` |
| `src/astro_best/models/input.py` | `ConeSearchInput` | `ra`, `dec`, `radius_arcsec`, `band`, **`max_records`** |

→ **权威定义是 ADQL + 凭据（两阶段异步查询），proto 是偏离 SSOT 的一方**。另：`input.contract.yaml` 第 5 行声明的 `schema: BestQuery` **在代码中不存在**（只有输出类 `BestQueryResult`）→ 契约→实现的命名绑定是断的。

### SCH-02 · P1 · 为项目不用的技术写契约
真实 wire format：`contracts/io-contract.md` = NADC BEST **REST API**（`sql`/`token`）；（坐标订正 R2 2026-10-05：原文引 `services/mcp_client.py:1-4`，该路径在本仓**从未存在**，`services/` 目录亦无 —— 属当时对上游姊妹包内部文件的越界引用）全链是 HTTP + JSON，**protobuf 在架构里不存在**。→ 它不是"未完成的契约"，是**方向错误的契约**。

### SCH-04 · P1 · proto3 无 presence 踩中天文坐标最经典 bug 类
`double ra/dec` 无 `optional`/wrapper → `(ra=0.0, dec=0.0)` 是赤道与本初子午线交点（合法天区，室女座），与"用户未填"**完全不可区分**；`radius_arcsec` 隐式默认 **0**（非法锥半径），也无法与缺省区分。而代码里该参数真实默认值是 60/180/600 —— proto 却把它默认为一个必然越界的 0。

### SCH-09 · P1 · 字段拼自两个不同实现，仓内无单一对应物
实测 `cone_search` 有 **4 份并行定义**，参数面互不兼容：

| 定义处 | 关键参数 |
|---|---|
| `client.py:437` `BestClient` | `radius_arcsec=180.0`, `catalog="ps1"`, `band`, `max_records=1000`, `page_size=1000`（**无 quality_filter**） |
| `core/__init__.py:101` `BestSkillClient` | `radius_arcsec=60.0`, `catalog="ps1"`, `band`, **`quality_filter=True`** |
| `pybest.py:328` `Best` | 第三套 |
| `models/input.py:8` `ConeSearchInput` | 第四套，`radius_arcsec=60.0`, `band`, `max_records` |

proto 的 `band`（BestClient 系）+ `quality_filter`（BestSkillClient 系）**同时出现，却漏掉两者都有的 `catalog`** → 描述的是一个**不存在的 API**。附带发现：`radius_arcsec` 默认值全仓 **60 / 180 / 600 / 0（proto）四种**。

### SCH-08 · P1 · 完全绕过信封层
`contracts/envelope.contract.yaml` 定义 `astro-data-envelope-v2`（含 `data_hash: sha256:...`、`provenance`）与 `astro-decision-envelope-v2`（含 `checkpoint.gate_name: astro_best_gate`、`human_review.decision`）。proto 一个字段都没映射 → 若真按它上线，**数据哈希校验、血缘追踪、Gate 状态、人在回路全部丢失**。

### SCH-11 · P1 · 契约副本已扩散进 RAG 知识库（上级视角才会发现）
```
astro-rag\rag\knowledge\world_models\WM03-...\\_links\astro-best\schemas\message.proto
astro-rag\rag\knowledge\world_models\WM03-...\\_links\astro-best\references\pybest-0.3.2.8\schemas\message.proto
```
astro-best **整目录**被复制进 `astro-rag` 知识库（至少 2 份 proto 副本 + 一份 `pybest-0.3.2.8` 快照）。→ 任何契约修改**必须同步副本**，否则 RAG 会检索到陈旧契约。

### SCH-01 · P2（降级）· 零接线属全家族常态，非本仓孤例
同族均有 `schemas/*-message.proto`：`astro-cybernetics`（76 行）、`astro-literature`（34 行）、`astro-feedback-loop`（23 行）、`10-workflows`；全 monorepo 同样**零消费者**。→ proto 在本家族的真实角色是**人读的接口文档**，不是可生成 schema。但它仍是个错误信号：放在 `schemas/` 目录、用 `.proto` 后缀，形式上承诺了 codegen 能力却不兑现。
> **本仓仍为同族最弱**：11 行 + 自标 placeholder + 缺 `catalog`/Output，而兄弟都无 placeholder 字样。

### SCH-05 / 06 / 07 · P2
- **SCH-05**　`contracts/` 里**每个字段都带 `unit:`**（`dimensionless`/`credential`/`mixed`）；proto 的 `ra`/`dec` 无单位标注（度？弧分？弧度？）——天文学里最贵的歧义；`radius_arcsec` 仅把单位塞进字段名。
- **SCH-06**　缺 `package astro.best.v1;` → 生成物落匿名命名空间，与其他 `astro-*` skill 合并必冲突；`message.proto` 文件名不携带领域信息（同族兄弟均用 `<domain>-message.proto`）。
- **SCH-07**　只有 Input，无 Output / Status / Error / Envelope / Provenance；而 `contracts/` 侧这五样齐全。覆盖率 5/11 概念，缺的正是门禁与血缘那一半。

### 定级与处置
**评级 F**。定调：**同族约定要求它存在，但 astro-best 这份是全家族唯一未完成的占位符，且字段方向与 SSOT 相反。**

- **方案 B′（主推）**　按同族水位**补齐为真接口文档**：加 `package`、`ra/dec/radius` 改用 `optional` 恢复 presence、补单位注释、补 `catalog` 与 `Output/Status/Error`、映射 envelope 的 `data_hash`/`provenance`/`checkpoint`；文件头声明「本文件是接口文档，不参与代码生成；wire format = REST + JSON-RPC 2.0」；cone-search 参数另立 message，**不占用 SSOT 已命名的 `BestQuery`**。
- **方案 A（已降级）**　原推"删除 `schemas/`"不再首选 —— 因 family isomorphism 门禁存在于 CI，且 RAG 知识库已索引该结构，删除会破坏同构性。若选此方案，必须连带清理 SCH-11 副本。
- **不论 A/B′ 均需单独修**：SCH-03（proto 与 SSOT 冲突）、SCH-04（presence 语义）、SCH-11（副本同步）。

---

## 6. 附录 A — 依赖声明一致性矩阵（实测）

| 包 | environment.yaml | pyproject `dependencies` | src 真实 import | 判定 |
|---|---|---|---|---|
| `requests>=2.28` | 硬依赖 | ✅ | ✅ `client.py` `pybest.py` | 一致 |
| `pandas>=1.5` | "可选降级" | **硬依赖** | ✅ | 语义冲突 |
| `numpy>=1.24` | "可选降级" | **硬依赖** | ❌ | 虚标（安装负担） |
| `astropy>=5.3` | "可选降级" | **硬依赖** | ❌ | 虚标（安装负担） |
| `pyyaml>=6.0` | **硬依赖** | **缺失** | ✅ `src/scripts/config.py` `rag/astro_rag.py` | **P0 漏声明**（坐标订正 R2 2026-10-05：原文 `config.py:68` `rag.py:63` 均已失效，前者路径从未存在、后者省了 `rag/` 目录前缀） |
| `urllib3` | 仅注释称传递 | ❌ | ✅ **直接 import** `src/client.py`（`pybest.py` 已随 `456149e` 删除） | P1 漏声明（坐标订正 R2 2026-10-05：原文 `pybest.py:40` 目标文件不存在、`client.py:28` 已漂） |
| `tqdm>=4.64` | 注释称可选 | ❌ | ❌ | 注释空转，声明缺失 |
| `rich>=13.0` | pip 段声明 | ❌ | ❌ | 冗余依赖 |
| `ruff>=0.1` | pip 段声明 | ❌（dev extra 无） | 门禁需要 | 工具无处安装 |
| `pytest` / `pytest-cov` | conda 段 | ✅ dev extra | 仅 test/ | 未分层 |

---

## 7. 修复批次建议

**Batch-1（P0 阻断，最小可运行）**
1. MK-01：`tests/` → 去掉显式路径（让 `testpaths` 生效）
2. ENV-02：pyproject 补 `pyyaml` + 拆 `except ImportError`（不被 CI 的显式 `pip install pyyaml` 掩盖）
3. MK-02：`ruff check src/` → `ruff check .`（含豁免台账）
4. ENV-04：删除/降级虚假"已核对"注释
5. MK-03：`.gitattributes` 锁 `Makefile text eol=lf`
6. SCH-03：proto 与 SSOT 解冲突 —— 保留 `BestQuery{sql, token}` 为权威 input，cone-search 字段另立 message；并补齐 `input.contract.yaml` 所指 `BestQuery` 在代码中的实体（或改指 `BestQueryResult` 所在层）
7. **EVAL-02 / EVAL-03**（revision 3 新增，最高优先）：gate 用例必须调用真实门禁实现（把 `http_status` / `checksum_match` 接进 `astro_best.protocol` / `downloader` 的判定函数），并把 `given:` 输入实际喂进去；否则先禁止该 runner 作为发布门禁使用
8. **EVAL-01**：消除全部 fail-open 分支（兜底 `passed = True`、未知 id 自动通过、契约缺失给高分），改为 **缺依赖即失败**；并把 `python -O` 与"删除 contracts/"两个突变纳入回归
9. **YAM-01**：修正 `case_014/015/016` 的 YAML 语法（加引号），删除 `eval_runner._load_yaml_file` 的掩盖补丁，新增一个"`evals/**/*.yaml` 必须可被 plain `safe_load` 解析"的 pytest 用例

> 注：revision 3 实测发现 MK-01/03/04/05/06 与 ENV-01（部分）已由外部并发修复（见 §13），Batch-1 中的 1/3/5 已不再待办；**但第 7–9 项（评测失真与用例语法错）一行未动，应提为当前最高优先**。

**Batch-2（P1 门禁真实性）**
MK-04 → MK-05 → MK-06 → MK-08（CI 增加 per-skill 步骤，使两链相交）→ ENV-01 → ENV-03 → ENV-06 → ENV-07 → ENV-08（含 CI Python 3.13 与仓内 3.10/py310 收敛）→ X-03（补 README 环境准备小节，并写明仓库根为 monorepo）→ SCH-02/04/08/09/11

**Batch-3（P2/P3 治理）**
MK-07（补 `help`/`build`/`eval`/`contract-check` + 变量抽象）→ SCH-01/05/06/07（按方案 B′ 将 proto 补齐为真接口文档）→ X-04（在项目内声明路径基准）→ ENV-08/09/10（conda-lock + nodefaults + categories）→ X-02 文档统一 → MK-10 / ENV-11 / SCH-10′

**SSOT 收敛方向（贯穿）**：以 `pyproject.toml` 为唯一依赖源，`environment.yaml` 只保留 conda 侧必需项（python + 不可 pip 安装者），其余经 `pip: ["-e .[dev]"]` 注入；契约以 monorepo `scripts/refactor/spec/skills-spec.yaml` 为根，经 `materialize_contracts.py` 下生 `contracts/`，`schemas/` 降为文档层；由 CI 用 `deptry` / `pip check` 机器校验 import 面，杜绝 ENV-04 类"人肉核对"注释复活。

---

## 8. 撤回与修订记录（revision 2）

> 原则：**不静默删除**。原文已在对应章节就地标注，本节只留判定变化与依据。

| ID | revision 1 原结论 | revision 2 实测事实 | 处理 |
|---|---|---|---|
| **SCH-10** | 「契约生成器 `scripts/refactor/materialize_contracts.py` 与 SSOT `spec/skills-spec.yaml` 在本仓 **不存在**，`generated_by` 是悬空引用」（定 P2） | 两者均存在于 monorepo 根：`<SKILLS_ROOT>\scripts\refactor\materialize_contracts.py`、`...\spec\skills-spec.yaml`（`Test-Path` 均为 True）。注释路径是**相对 monorepo 根**的，完全正确 | **已撤回**。重开为 **SCH-10′ / P3**：仅“未写明路径基准”成立（归入 X-04） |
| **MK-08** | 「仓库无 CI，Makefile 是唯一门禁且为最弱环」 | `<SKILLS_ROOT>\.github\workflows\ci.yml` 存在，其引用的 3 个脚本/测试文件均实测存在 | **已撤回并完整重写**。真问题改为“CI 从不执行 astro-best Makefile，两链不相交”，级别仍 P1 |
| **SCH-01** | 「proto 零消费者 = astro-best 独有缺陷」（定 P0） | 同族 4 个 skill 均有同类 proto，全 monorepo 均零消费者 | **降级 P0→P2**（属家族常态）；但本仓“同族最弱”单独保留一条事实注 |
| **MK-01** | 根因＝“手误写错目录名” | monorepo 根确实有合法 `tests/`；已排除“Makefile 按根目录写”的辩护（根无 `src/`/`pyproject`/`Makefile`） | 结论不变（仍 P0），**根因升级为“路径从 monorepo 根抄进子目录”的基准漂移**，新增 X-04 |
| **ENV-02** | 仅归因为“双头声明 + 静默兜底” | monorepo CI 显式 `pip install ... pyyaml ...` | 级别不变（仍 P0），**补充“为何长期未暴露”证据链**；附带发现 CI 装的 `pydantic` 仓内零使用 |

**方法论沉淀**：工作区仅打开 monorepo 子目录时，任何“某文件/某引用不存在”的否定性结论必须先到仓库根（`.git` 所在级）验证后才能写入本清单。revision 1 的 3 条误判全部源于未执行这一步。

---

## 9. 验证与限制声明

- 已实测取证：pytest 目录错误、ruff 191/474 分布、Makefile 与 environment.yaml 字节级行尾/BOM、clean 路径存在性、src import 面枚举、`conda_env` 冲突、README 零命中、`.gitignore` 对照；proto 层：全 monorepo 零消费者搜索、`*_pb2`/`protoc` 存在性、`skills-spec.yaml` 的 `astro-best.input` 原文、同族 4 份 proto 行数、4 份 `cone_search` 签名对比、RAG 内副本定位、monorepo 根 `.git`/`tests`/`src`/`pyproject`/`Makefile`/CI 存在性。
- **[未实机验证]**：ENV-01（conda 拒绝无 `name` 的 spec）、MK-03 第 3 点（CRLF 在 Linux make 下的具体报错）、ENV-09（channel 混解冲突）—— 本机 `Get-Command conda` 为空且未安装 GNU make，属规范级判定，修复后需在装有 conda/make 的环境回归。CI 相关结论仅读 `ci.yml` 文本，未实跑 actions。
- **审查边界**：revision 2 已向上验证至 monorepo 根 `<SKILLS_ROOT>`；未向 `<LOCAL_PATH>` 及更外层的 `_shared` 消费链（如注册表入口、Skill 平台侧）展开；SCH-11 的 RAG 副本仅确认存在，未逐份 diff 内容是否已陈旧。
- 本清单仅记录，未对任何源文件（Makefile / environment.yaml / pyproject / proto / contracts）做修改。

---

## 10. YAML 层审查（YAM-*，50 个文件）

### 整体健康度（正面结果，实测）
50 个 `.yaml/.yml` 全量解析：**0 重复键、0 tab 缩进、0 空文件、0 字节级重复**；`contracts/skills-spec.local.yaml` 与 monorepo SSOT **逐字段完全一致**；版本号 5 处（pyproject / `__init__.py` / `_version.py` / manifest / pipeline）均为 `0.3.2.6`。

### YAM-01 · P0 · 3/50 硬语法错误，且被 runner 掩盖
`evals/cases/case_014/015/016_algo_namemodule.yaml` 第 3 行：
```yaml
derived_from: algorithm:{'name': 'cone_search', 'module': 'astro_best.scripts.best_cone_search'}
```
→ `ScannerError: mapping values are not allowed here`（plain `yaml.safe_load` 直接失败）。
根因：生成器把 **Python dict repr** 直接塞进了 YAML 值位置，未加引号。
掩盖机制：`eval_runner._load_yaml_file()` 第 46–49 行用字符串处理把这行重写成带引号的形式 —— **只有 runner 能读，monorepo 的 `validation/eval_engine.py`、`gate_checker.py`、IDE、CI 仍会崩**（已实测：这三个文件均标注 UNPARSEABLE by plain yaml）。
修复：改正例本身（`derived_from: "algorithm:..."`），并删除 runner 的掩盖补丁，加一个 `pytest` 用例断言 `evals/**/*.yaml` 全部可被 plain `safe_load` 解析。

### YAM-02 · P1 · manifest 资产清单悬空
`manifest.yaml` 声明 `stream_download: static/fragments/target_type/best_catalogs.md`，但该文件实际位于 `static/fragments/data_source/best_catalogs.md`；`target_type/` 下只有 `best_ttype.md`、`photometry_region.md`、`standard_star.md`。→ 按清单加载 fragment 会 404。

### YAM-04 · P1 · 8 个真孤儿 + 16 个仅靠 glob 发现
全仓（含 monorepo `scripts/`、`_shared/`、`tests/`、`pipeline/`、`.github/`）反向引用计数结果：

| 类型 | 数量 | 清单 |
|---|---|---|
| **真孤儿**（无任何按名引用） | 8 | `environment.yaml`、`agents/openai.yaml`、`static/fragments/algo_mode/best_auth_mode.yaml`、`.../two_stage_async_mode.yaml`、`templates/gen_case_prep_sql.yaml`、`gen_case_prep_token.yaml`、`gen_result_field_data.yaml`、`gen_result_field_status.yaml` |
| **仅被 glob 发现**（无名字级接线） | 16 | `evals/cases/case_001 ~ case_016`（`eval_runner` 靠 `glob("case_*.yaml")` 发现） |
| **正常消费** | 26 | `manifest.yaml`（大量引用）、`contracts/*`（`materialize_contracts.py` + `test_gen_*.py` 按名）、`pipeline.yaml`、`sync/agents/openai.yaml`、其余模板等 |

逐个复核确认：上述 4 个 fragments/templates 文件在全 monorepo 的“按名引用”**只来自本清单自身**（`docs/ISSUES.md` 第 484/485/491 行），排除自引用后为 0。
另注意 `agents/openai.yaml`（主入口）为孤儿，而 `sync/agents/openai.yaml` 有 7 处引用 —— 引用分布倒挂。

> **测量污染警告（本次真实踩到的坑）**：第一轮统计脚本把 `ROOT` 下的 `docs/ISSUES.md` 一并当作“消费者”扫描，导致自引用将上述 8 个孤儿洗成“0 orphans”。任何“引用计数/孤儿检测”类度量，必须先把报告自身排除出搜索集。

### YAM-03 / 05 / 06 / 07 · P3/P2
- **YAM-03**　BOM：`evals/test-scenarios.yaml`、`templates/best-config.yaml`。实测 PyYAML 在 `encoding='utf-8'` 与 `'utf-8-sig'` 下**均 OK**（不致错），但仓内多个加载器写的是 `read_text(encoding="utf-8")`（如 `_shared/astro_core/io/yamlio.py:18`），与其他 YAML 工具/解析器行为不一致 → 统一去 BOM。
- **YAM-05**　`static/fragments/algo_mode/` 内三种形态：`best_auth_mode.yaml` 与 `two_stage_async_mode.yaml` 用 `fragment:` 包装，`best_two_phase.yaml` 用裸键 `two_phase/gates/env`；二者文本相似度仅 0.04（非重复，但 schema 不统一影做渲染器）。
- **YAM-06**　`templates/best-config.yaml`（`tap_url/api_url/timeout/defaults/quality/download/crossmatch`）与 `templates/config_template.yaml`（`params.<Class>.module/enabled` 矩阵）是两个不同轴的配置形状，都叫 config，互不引用。
- **YAM-07**　`environment.yaml` 已被并发修复加上 `name: astro-best`，但 ENV-04（注释自称“按真实 import 核对”）仍未处理。

---

## 11. evals/ 能力边界（EVAL-*）—— 本次最严重问题集

`evals/eval_runner.py`（353 行）实测能跑，输出：**场景 5/5、用例 16/16、四维均 PASS、综合评分 1.0000（合格线 0.9）→ SUCCESS**。
以下用**突变实验**证明这个满分不代表任何能力。

### EVAL-01 · P0 · 删除全部契约，评测仍判成功
```
实验：将 eval_runner 的 SKILL_DIR 指向一个 contracts/ 为空的目录，其余不变
结果：用例 12/16 通过（只掉了 4 个文件存在性检查）
      correctness=0.85[PASS]  gate_compliance=1.00[PASS]
      determinism=1.00[PASS]  provenance=0.80[WARN]
      overall=0.9200  passed=True   ← 仍判 SUCCESS
```
→ **评分量规宣称“gate_compliance 逐项满足阻断门禁”、“provenance 看信封 data_hash”**，但整个契约层消失后它仍给出通过。该门禁不可用于发布判定。

### EVAL-02 · P0 · gate 用例是恒真式，不接触任何被测代码
`eval_runner.py:156-167`：
```python
if "pass" in cf.name:
    test_val = threshold.get("value")                       # 取阈值本身
    eval_res = _evaluate_gate(cmp_op, test_val, threshold.get("value"))   # 阈值 == 阈值
```
实测六个 gate 用例的阈值：`http_status` 均 `cmp='==' value=200`，`checksum_match` 均 `cmp='==' value=True`。
→ `_evaluate_gate('==', 200, 200)` 恒为 True；`boundary` 分支同理；`violated` 分支靠**硬编码** `test_val = 500 if gate_name == "http_status" else False`（第 161 行）。
**整个 gate 分支未 import 任何 `astro_best` 代码** → 把仓库里的门禁实现全删，这 6 个用例仍全绿（零突变敏感度）。项目自定的「禁止假测试与突变验证」红线在此直接违反。

### EVAL-03 · P0 · 用例输入被完全丢弃
全文扫描 `eval_runner.py` 关键字出现次数：`given` = **0**，`expect` = 1（只取 `expect.status` 这个标签）。
→ 16 个用例写的 `given:` 输入夹具**一行都没被读过**；用例不喂任何输入就给结论。`expect:` 也只当“该用例期望 pass 还是 blocked”的元标签，不校输出内容。

### EVAL-04 / 05 / 10 · P1 · 多处 fail-open
- field/input 用例：`passed = field_contract.is_file()`（第 198 行）—— 文件存在即过，内容错乱不算失败。
- scope 用例：`passed = len(scopes) >= 3`；**若 spec 文件不存在 → `else: passed = True`**（第 192 行）。
- algorithm 用例：正则未命中 name/module → `else: passed = True`（第 182 行）。实测构造一个不可解析的 algorithm 用例 → `passed=True`。
- scenario 用例：id 不在 5 个硬编码分支里 → `reason="generic scenario verified"`，`passed` 保持 True。实测未知 id → `1/1 passed`。
  → 往 `test-scenarios.yaml` 加一个全新能力条目，**无需实现任何东西就能拿满分**。
- EVAL-10：5 个已实现分支只做 `hasattr` / 常量比对（如 `assert len(CATALOG_PATHS) >= 5`），不执行一次查询、不断言任何行为。

### EVAL-07 / 08 / 09 · P2
- **EVAL-07**　校验全靠 `assert` → `python -O evals/eval_runner.py` 实测仍报 **5/5 与 1.0000**（断言被编译掉，所有检查退化为空操作）。
- **EVAL-08**　`_evaluate_gate('>=', None, 200)` 实测 `RAISES TypeError: float() argument must ... not 'NoneType'`；而 `run_cases_eval` 的 `try` 只包住 `_load_yaml_file`（第 137–142 行）→ 一个非法阈值直接 crash 整个 runner。
- **EVAL-09**　兜底分 0.85 等于 WARN 线 0.85（`s >= 0.85 → PASS`），即“契约没全对”仍计入 PASS 维度；权重和靠 YAML 约定（当前 0.4+0.3+0.2+0.1=1.0，无代码校验）。

### EVAL-06 · P2
`make eval` 已接线（Makefile 第 45–46 行），但 monorepo `ci.yml` 中 **`eval` 出现次数 = 0、`astro-best` 出现次数 = 0** → 评测不会在 CI 上跑，也不会阻断任何合入。

### 边界结论
**evals/ 的真实能力 = “验证自己写的几个文件还在不在”**，与 BEST API 行为、门禁逻辑、输出质量**无任何因果连接**。它能做的：(a) 发现字段契约文件被重命名/删除；(b) import 5 个类名确认存在。它做不了的：HTTP 状态门禁、checksum 校验、ADQL 正确性、量纲/单位、血缘完整性 —— 即量规声称的全部四项。

---

## 12. test/ 能力边界（TST-*）

### 真实强度（正面实测）
| 目录 | 收集 | 结果 | 耗时 |
|---|---|---|---|
| `test/unit/` | 128 | **128 passed, 1 skipped** | **1.23s** |
| `test/integration/` | 34 | **27 passed, 8 skipped** | 1.91s |
| `test/live/` | 13 | （需 `PYBEST_RUN_LIVE=1`） | — |
| `test/_archive/` | 18 文件 | **18 skipped, 0 执行** | 1.79s |
| 合计 `test/` | **175 collected** | exit=0 | 2.40s |

断言质量扫描：**0 个“无断言测试”、0 个 `assert True`、无低断言密度文件**；src 32 个模块中仅 2 个无测试引用。这一层是仓内质量最高的部分。

### TST-05 · P1 · conftest 内置硬编码契约副本（三级降级保证不报错）
`test/conftest.py` 自带 `_DEFAULT_SPEC`：把整份 SSOT（`in_scope`、`input.schema: BestQuery`、`gates`、`algorithms` 12 项、`weights`）**拷贝进测试文件**，函数 `get_spec_data()` 的降级链是：
1. monorepo `scripts/refactor/spec/skills-spec.yaml` → 2. `contracts/skills-spec.local.yaml` → 3. **内置 dict**，docstring 自陈“三级降级保证绝对不抛出 FileNotFoundError”。
→ 契约被删、被改坏、被换掉时，契约类测试**不会失败，而是改读内置副本**。与 EVAL-01 同构的 fail-open，且藏在 fixture 层更难发现。实测：`skills-spec.local.yaml` 与 monorepo SSOT 当前逐字段一致 → 三副本共存但无同步机制，漂移不会报警。

### TST-01 / 02 · P1 · ≥20 个整模块静默 skip
- `test/_archive/upstream_pybest_0_3_2_8/` 18 个文件含真实 `def test_*`，但顶部 `import pybest.*`（已不存在的包）→ 整模块 `allow_module_level` skip，实测 **18 skipped**。
- `test/unit/test_auth_store.py:14` skip 理由：`No module named 'astro_best.services.auth_store'`（坐标订正 R2 2026-10-05：该路径在本仓**从未存在**；认证相关测试现为 `test/unit/auth/` 下的模块）；
- `test/integration/test_server_api.py:18` skip 理由：`No module named 'astro_best.services.ser…'`（同上，路径从未存在）。
→ 共 **≥20 个测试文件在本环境一行不执行**，而汇总只看得到 `128 passed, 1 skipped` 这种几乎全绿的表象。认证存储与 server API 两个能力实际上无人测。

### TST-03 / 04 · P2
- **TST-03**　6 个 live 用例靠 `PYBEST_RUN_LIVE=1` 门控，默认不跑 → http_status / checksum 这两个“阻断门禁”在默认链路上 **0 次真实执行**（这也正是 EVAL-02 无法被 test/ 补偿的地方）。
- **TST-04**　`src/astro_best/scripts/repair.py`、`src/astro_best/services/mcp_client.py` 全测试零引用。

---

## 13. revision 3 基线漂移：并发修复清单

审查期间（同一会话内）仓库被外部修改，`git status` 实测：`M Makefile / SKILL.md / architecture.md / environment.yaml / manifest.yaml / pipeline.yaml / pyproject.toml / scripts/cli.py / src 多个模块`；`D evals/test-scenarios__{swsk,twh,twh_2,v1}.yaml`；`D tests/conftest*.py`（旧 `tests/` 目录及其 4 个 fork 已删）。

| 条目 | revision 3 现状 |
|---|---|
| MK-01 | ✅ **已修**：第 22 行 `pytest test/`（单数） |
| MK-02 | ⚠ **部分修**：现为 `ruff check src/ test/`，仍缺 `sync/ scripts/ examples/ evals/ rag/` |
| MK-03 | ✅ **已修**：`clean` 改为纯 Python one-liner（跨平台）；文件现为 **54 行、CRLF=0 / 纯 LF=53**；monorepo 根已有 `.gitattributes` |
| MK-04 | ✅ **已修**：clean 覆盖 `best_data`、`.coverage`、`__test_tmp__`、递归 `__pycache__`、egg-info、htmlcov |
| MK-05 | ✅ **已修**：`.PHONY` 14 项与实际 14 个目标完全对齐 |
| MK-06 | ✅ **已修**：`--cov=astro_best --cov-report=term-missing`（仍缺 `-p no:cacheprovider`） |
| MK-07 | ⚠ **大部分修**：新增 `help` / `doctor` / `eval` 目标；仍无 `build` |
| ENV-01 | ⚠ **已加 `name: astro-best`**，但 `skill_name`/`conda_env` 自造键与 `channels: [..., defaults]` 仍在 |
| ENV-04 | ❌ **未动**：第 1–3 行“按真实 import 核对”虚假注释原封不动 |
| X-02 | ✅ **已修**：旧 `tests/` 目录与 4 个 `conftest__*.py` fork 已删除 |

**本节含义**：§2–§4 的 MK-*/ENV-*/X-* 部分条目已不再是待办项；修复集中于构建层，而 **§11/§12 的评测与测试失真（EVAL-01/02/03、TST-05）一行未动** —— 它们才是严重问题的主体。

**并发写入的直接影响（必须记录）**：本次审查使用的 5 个临时度量脚本中，`.tmp_yaml_audit.py`、`.tmp_yaml_consumers.py`、`.tmp_eval_probe.py` 在会话进

---

## 14. 存疑项登记（2026-10-03 注释去噪轮）

> 这一节是「注释去噪」轮的产出：那轮把注释里的轮次/日期/改动过程叙述剥掉、改写成
> 当前不变量，过程中撞见的**没能当场定论**的问题集中登记在此。**这些不是新缺陷**，
> 是"看过、记下、留给你定"的条目。已当场改掉的写进 `docs/architecture/pitfalls.md`。

| # | 位置 | 存疑的是什么 | 现状 |
|---|---|---|---|
| SUSP-01 | `src/tap/__init__.py:12` | `〔本仓历史已无此对象〕` 段落**重复出现两次**，判不出是刻意强调还是粘贴残留 | 未动（test 侧同类重复已去重，见 `test/unit/audit_round/test_restored_surface.py`）。**需确认**：是否刻意 |
| SUSP-02 | `evals/robustness/runner.py:310` | 报告 `note` 字段是人读文案，原带「本轮不跑批」措辞；改字符串会变更报告输出 | **已改**为「离线不跑批」（与本文件 docstring L7 统一）。无测试断言该串，报告产物随之更新 |
| SUSP-03 | `test/unit/protocol/test_protocol.py:289`、`:301` | 仍是「复过的现: …旧判据…"任一单元格含字母"…」的旧实现叙述，正则未命中 | 未动。**需确认**：是否值得改写为当前不变量 |
| SUSP-04 | `test/unit/tap/test_service.py:426` | 仍以「复过的现:」开头，但内容描述的是当前代码形态、无轮次信息 | 未动（判断为保留） |
| SUSP-05 | 全仓 147 文件 / 544 行注释 | 探测器只能判**封闭形态**（日期戳/轮次词/改动过程复述/旧实现叙述）。**规格事实的日期**（外部规范引用、实测证据日期、协议格式版本分界）判不出来，**靠人判读** | 保留 22 + 2 处（batch1/batch5 各按 (c) 口径逐条列明理由）。**这类无法自动化**，是本轮已知的判据边界 |
| SUSP-06 | `src/protocol_catalog_tables.py` 等 | 「线上核验日期」(`2026-09-29`) 标注的是**对外部站点列发布情况的实测**。站点会变，这个日期会越来越旧 | 保留（它是可核查性的锚点）。**需确认**：是否该加一条"站点列变更需重新核验"的机制 |
| SUSP-07 | `docs/architecture/governance-debt-plan.md` §12.2 遗留观察项 4 | 曾记「README 规则 5 声明 `docs/` 不随 git 分发，但 21 个文件跟踪在 HEAD」 | **已更正**：README 规则 5 与该文档的落点声明同批改掉（现为 28 个文件）。该观察项可结案 |
| SUSP-08 | 拆分 `comment_audit.py` 时的三处偏差 | 预案说搬 7 个函数、导入走 `ops.audit.line_scope` 包路径；实际搬了 14 个、用同目录裸名 | **已更正** `file-size-budget.md` §3.13（写明实际做法与原因）。不是缺陷，是预案估计偏保守 |
行期间**被外部进程删除**（实测：当前仅剩 `.tmp_boundary_probe.py`、`.tmp_yaml_cross.py`、`.tmp_orphan.py` 与两个输出文件）。叠加 `git status` 的 109 项变更，说明 **本仓当前处于多人/多 Agent 并发写入状态**；任何"已核实"结论都有时效，引用本清单时应先重跑关键实测命令。
