# astro-best 架构重构实施计划 v1（苏格拉底对齐 5 轮成果 · 存档版）

> 状态: 已存档待深化。后续将纳入 `docs/CODE-QUALITY-FIX-LIST.md` 与 `<LOCAL_PATH>` agent 接入网站文档, 产出 v2 详细计划。
> 本文件位于 docs/ (local-only, gitignored), 不随 git 分发。
>
> **存档说明 (2026-10-05)**: 本文是**当时**的决策记录, 正文按原样保留不改写
> (改写即篡改历史)。其中两处已被后续决策推翻, 读正文时须知:
> ① 「CHANGELOG.md 进 gitignore 转本地历史」(决策 19) 已于 2026-10-05 **改判为
> 入版本控制** —— 变更历史是删改记录的唯一载体, 留在仓外等于无记录;
> ② 上一行「本文件位于 docs/ (local-only, gitignored)」同样已过期: `docs/` 自
> 2026-09-28 起整体入版本控制, 本文件现在随仓分发。现行口径见 `README.md`
> 治理规则 3/5 与 `architecture.md` §0.1。

## 一、对齐决策总览（5 轮 18 问）

| # | 决策点 | 结论 |
|---|--------|------|
| 1 | 作用域 | 仅 astro-best 单仓库验证，后续可作模板推广 |
| 2 | SKILL→README 强制阅读 | 三位一体：manifest always_load + SKILL.md 首步指令 + verify 同步校验 |
| 3 | 文件树防损坏 | 硬门禁：README 内嵌树清单 = canonical 快照，`verify_tree_integrity.py` diff 实际树 |
| 4 | README 树清单 | 脚本自动生成的文件级全树 + 每目录能力边界注释 |
| 5 | 临时文件 | 只允许 `temp/`（gitignored），.qdeep 两份移入并留档 |
| 6 | 结构变更通道 | ask_user_question 请示；计划清单一次性批量批准，计划外变更单独请示 |
| 7 | 权限矩阵 | 既有文件内容编辑自由；被跟踪文件/目录的新增删移改名、.gitignore 增删、README 树变更需批准 |
| 8 | test/ 定位 | 能力实现回归测试（我们的能力是否正常实现） |
| 9 | evals/ 定位 | 全 skill 质量评审层，覆盖面尽可能广和全，警惕无效评估文件 |
| 10 | evals 靶目录 | test/ references/ rag/knowledge/ templates/ contracts/ static/ 全覆盖 |
| 11 | evals 重建 | 全面重建（真断言、无 fail-open、-O 安全、喂真实输入、接 make eval 阻断） |
| 12 | test/ 重组 | 能力域子目录 + 按被测对象合并去重 + upstream 去版本号，断言零丢失 |
| 13 | 死测试 | 删 test_auth_store.py、test_server_api.py（目标模块不存在，一行未执行过） |
| 14 | conftest | 删 `_DEFAULT_SPEC` 三级降级链，契约缺失即红 |
| 15 | 场景文件 | `__twh_2` 为基线合并 5 份为唯一 canonical，删 4 变体 |
| 16 | docs/ | 取消 git 跟踪 + gitignore，README 树清单标注 local-only |
| 17 | schemas/ | 删 message.proto（全库零引用）及整个目录 |
| 18 | 双层 scripts | 并存 + 边界声明（scripts/=运维入口，src/astro_best/scripts/=包内模块） |
| 19 | 版本号 | 全仓禁止：所有发布版本号 + schema_version/template_version 等标记全删；SKILL.md 写入铁律；CHANGELOG.md 进 gitignore 转本地历史 |
| 20 | pyproject | 剥离 [build-system]/[project]，只留 pytest/ruff 工具配置 |

## 二、目标架构：根目录能力边界表（将写入 README.md）

| 目录 | 能力边界 | 治理规则 |
|------|----------|----------|
| `src/astro_best/` | 唯一 Python 实现；`scripts/` 子包=功能模块 | 内容编辑自由；新增模块需请示 |
| `test/` | 能力实现回归：`unit/<能力域>/`、`integration/`、`live/`、`upstream/`、`fixtures/` | 重组按批准的计划执行 |
| `evals/` | 质量评审层：行为评测（cases/）+ 内容质量审计（audit/ 覆盖 6 靶目录） | 审计器须附反证夹具 |
| `contracts/` | 跨节点 I/O 契约 SSOT | 被 evals 审计 |
| `references/` | 白盒算法长文档（五要素） | 被 evals 审计 |
| `rag/` | 知识检索执行器 + knowledge/ 结构化规则 | 被 evals 审计 |
| `templates/` | 生成/渲染模板 | 被 evals 审计 |
| `static/` | 提示词静态规则（core/ + fragments/） | 被 evals 审计 |
| `scripts/` | 运维入口：cli.py、cloud_modelscope/、verify_tree_integrity.py | 与包内 scripts/ 边界声明 |
| `agents/` | Persona 决策提示词 | — |
| `bridge/` | 外部 harness 注册脚本 | — |
| `examples/` | 用法示例（人读） | 被 lint 覆盖 |
| `models/` | 权重声明（无二进制权重） | README only |
| `docs/` | local-only：计划/审计/图表，gitignored | 零运行时引用 |
| `best_data/` | 运行时数据落盘，gitignored | AI 只读写 |
| `temp/` | 唯一临时文件区，gitignored | 其他位置临时文件=违规 |
| `schemas/` | 删除 | — |
| 缓存目录 | `__pycache__/.pytest_cache/.ruff_cache/.checkpoints` | 不进树清单，随时可删 |

## 三、test/ 目标结构（能力域映射）

```
test/unit/
  client/      ← test_gen_algo_bestauth + bestclient + single_class（按被测对象合并去重）
  query/       ← test_gen_algo_bestquery + bestqueryresult
  download/    ← test_downloader + downloader_resumable + gen_algo_bestdownloader
  crossmatch/  ← test_crossmatch + gen_algo_bestcrossmatch + crossmatch_with_gaia
  lightcurve/  ← test_lightcurve + gen_algo_bestlightcurve
  pipeline/    ← test_core + test_processor + test_quality_gate + gen_algo_astrobestpipeline
  protocol/    ← test_protocol + test_protocol_safety
  contracts/   ← test_gen_contracts + fields + gates + delegation
  scripts/     ← test_gen_algo_cone_search + validate_adql_query
  config/      ← test_gen_algo_astrobestconfig
  meta/        ← test_gen_smoke + ledger + fixes + catalog_registry_live
test/upstream/  ← upstream_pybest_0_3_2_8 去版本号，tap_* 8 个等按 topic 合并为 ~5 个文件 + README 说明 skip 现状
test/live/      ← 并入 integration/ 下两个 live 门控测试（执行时核对 gate 标记后归位）
```

硬约束：每次合并后跑 pytest，断言只增不减；基线 175 passed 保持。

## 四、evals 质量评审层设计（防刷分六机制）

1. 反证夹具：每个 audit 审计器必须附 `broken/` 故意构造的坏样本，坏样本不过 = 审计器无效（变异测试式自检）
2. 无 fail-open：目标文件缺失/损坏 → FAIL，绝不再现"文件存在即过"
3. -O 安全：校验逻辑不用 `assert`，改用显式返回/抛出
4. 输入必喂：所有用例必须消费 `given:` 夹具并校验输出；未知场景 id → 报错，不再"generic verified"
5. 权重代码校验：权重和 ≠1.0 即启动失败；pass_score 与 WARN 线拉开差距
6. 接阻断链：`make eval` 并入 `make check`/`make all`，红了就阻断

## 五、分阶段执行（Conventional Commits，每阶段一棵树绿灯）

| 阶段 | 内容 | Commit |
|------|------|--------|
| Phase 0 | .gitignore(docs/temp/CHANGELOG) + docs 去跟踪 + temp/ 留档 + verify 脚本 + README 重写（边界表+树 SSOT+治理规则）+ SKILL.md/manifest 必读规则 + Makefile 接线 + architecture.md 治理面更新 | `chore(astro-best): establish README tree SSOT, integrity gate and temp policy` |
| Phase 1 | 全仓去版本号/标记 + pyproject 剥离 + 删 schemas/ + 删 2 死测试 + 场景 5→1 合并 + BOM 清除 + 陈旧路径修复 + __test_tmp__ 迁 temp/ | `chore(astro-best): purge version fields and dead assets` + `refactor(astro-best): consolidate eval scenarios` |
| Phase 2 | test/ 能力域重组 + upstream 改名合并 + live 归位 + conftest 去降级链 | `refactor(astro-best): reorganize test suite by capability domain` |
| Phase 3 | eval_runner 重建 + rubric 重建 + cases 重写 + audit/ 六审计器 + 反证夹具 | `feat(astro-best): rebuild evals as whole-skill quality gate` |
| Phase 4 | README 树终版 regenerate + 全链路验收（pytest/eval/ruff/verify/make all 全绿） | `test(astro-best): lock full-chain acceptance` |

## 六、验收标准（量化）

- `python -m pytest test/ -q`：≥175 passed、0 failed；skip 数 ≤40 且每个有文档化理由
- `python evals/eval_runner.py`：行为 + 审计双模式全绿，且全部反证夹具按预期失败
- `python scripts/verify_tree_integrity.py`：README 树清单与实际零 diff
- `ruff check src/ test/ evals/ rag/ scripts/ examples/`：零告警
- `make all` 一键全绿

## 七、待确认事项

1. git 基线：当前仓库有未提交 WIP（CHANGELOG.md 改动、.qdeep.py、docs/CODE-QUALITY-FIX-LIST.md 等）。Phase 0 先从 git status 审查开始，现有 WIP 作为基线提交再动结构。
2. `astro-envelope-v1`：线协议名称（非版本字段），保留标识符，仅删 version 字段。

## 八、v2 深化方向（本轮对话产出）

- 纳入 `docs/CODE-QUALITY-FIX-LIST.md` 的全部 Q-* 条目
- 纳入 `<LOCAL_PATH>` agent 接入网站文档的接入契约与质量要求
- 基线实测（2026-09 会话）：pytest 175 passed / 42 skipped；eval_runner 5/5 + 16/16、综合 1.0000（ISSUES.md 实证为 fail-open 假象）
