# astro-best 架构重构实施计划 v2（最终版 · 苏格拉底对齐 11 轮成果）

> 状态: 待批准执行。批准后按 Phase 0→8 推进, 每 Phase 结束汇报绿灯结果。
> 本文件位于 docs/ (local-only, gitignored), 不随 git 分发。
> v1 存档: docs/architecture/implementation-plan.md (治理框架)
> 增补来源: docs/CODE-QUALITY-FIX-LIST.md (62 条 Q-*)、<LOCAL_PATH> 平台接入文档、NADC OAuth2.0 官方规范
>
> **口径订正 (2026-10-05)**: 本计划是**当时**的执行方案, 正文按原样保留不改写
> (改写即篡改历史)。其中两处已被后续决策推翻, 读正文时须知:
> ① 「CHANGELOG 转 local」(项 19 / 提交步骤 3、12) 已于 2026-10-05 **改判为
> 入版本控制** —— 变更历史是删改记录的唯一载体, 留在仓外等于无记录;
> ② 上一行「本文件位于 docs/ (local-only, gitignored)」同样已过期: `docs/` 自
> 2026-09-28 起整体入版本控制, 本文件现在随仓分发。现行口径见 `README.md`
> 治理规则 3/5 与 `architecture.md` §0.1。

---

## 〇、最终目标树（全重名已消除 · src/ 平铺 · 包名 src）

```
astro-best/
├── SKILL.md                      # skill 入口（平台交付物，≤100 行，必读 README 链）
├── README.md                     # 入口 + 文件树 SSOT + 逐文件能力边界表 + 治理规则 + 平台部署前提
├── manifest.yaml                 # 加载地图 SSOT（always_load += README.md）
├── architecture.md               # 架构规范（12 治理面更新）
├── pipeline.yaml                 # 流水线声明（去 version，符号可 resolve）
├── Makefile                      # 工程入口（verify/lint 扩仓/eval 阻断）
├── pyproject.toml                # 仅 [tool.pytest.ini_options]/[tool.ruff]
├── .gitignore                    # += docs/ temp/ CHANGELOG.md .checkpoints/
├── .env.example                  # 凭据 SSOT（含 NADC_OAUTH_*）
├── environment.yaml              # 环境定义
├── src/                          # 实现层（原 src/astro_best/ 平铺；包名 = src）
│   ├── __init__.py               # 门面（去 __version__；导出 Best/BestClient/... ）
│   ├── __main__.py               # python -m src 入口（原 src/astro_best/cli.py）
│   ├── client.py / pybest.py / query.py / downloader.py / crossmatch.py / multiband_photometry.py
│   ├── csv_safety.py / protocol.py
│   ├── kb/                       # 文档加载器（原 astro_best/references/，标志文件查找根）
│   ├── models/                   # 数据模型（input/output/__init__）
│   ├── core/                     # __init__.py + pipeline.py（孤岛互通）
│   ├── scripts/                  # 包内功能模块 8 个（repair/rag 删）
│   └── auth/                     # 新增（Phase 6）：nadc_oauth.py + token_store.py
├── ops/                          # 运维入口层（原 scripts/ + bridge/ 合并）
│   ├── astro_best_cli.py              # doctor/rag 子命令（原 scripts/cli.py）
│   ├── verify_tree_integrity.py  # 文件树硬门禁（新增）
│   ├── register_skill.py         # 注册辅助（原 bridge/ 两份合并为一）
│   └── cloud_modelscope/         # run.py + remote_worker.py
├── agents/openai.yaml            # Persona（去 version）
├── weights/README.md             # 权重声明（原 models/）
├── contracts/                    # I/O 契约 SSOT
│   ├── envelope/error-codes/input/output/pipeline-stage/provenance.contract.yaml
│   ├── fields/ (data/sql/status/token)
│   ├── io-contract.md
│   └── oauth.contract.yaml       # 新增（Phase 6）
├── references/                   # 白盒文档内容层
│   ├── ALGORITHM-SPEC.md         # + OAuth 白盒节（Phase 6）
│   ├── best-database-guide.md / fallback-protocols.md / pybest-api-reference.md
│   └── skills-spec.local.yaml    # spec 快照（自 contracts/ 迁入）
├── rag/                          # 知识检索层（全树唯一 RAG）
│   ├── astro_rag.py
│   └── knowledge/                # best_practices/domain_rules/known_issues/lessons_learned
├── static/                       # 提示词静态规则（逐文件边界见 README）
│   ├── core/stance.md            # AI 立场与姿态规则（会话注入）
│   ├── core/workflow.md          # 五状态机工作流规则（会话注入）
│   ├── core/output-format.md     # 输出信封/报告格式规则（会话注入）
│   └── fragments/
│       ├── algo_mode/best_two_phase.yaml        # 协议步骤切片（端点/软404/门禁/env）
│       ├── algo_mode/two_stage_async_mode.yaml  # 算法模式契约（entry 符号/hyperparams/outputs/degrade）
│       ├── data_source/best_catalogs.md         # 星表数据源知识
│       ├── data_source/nadc_endpoints.md        # NADC 端点知识
│       ├── target_type/best_ttype.md            # BEST 目标类型判据
│       ├── target_type/photometry_region.md     # 测光区域语义
│       └── target_type/standard_star.md         # 标准星筛选语义
├── templates/                    # 模板层
│   ├── source/                   # config_template/report_template/best-config（键收 defaults）
│   └── generated/                # gen_* 历史产物
├── examples/                     # 人读示例
│   ├── example_skill_usage.py    # 库 API 用法演示
│   └── quickstart_pybest.py      # 端到端快速上手
├── test/                         # 能力回归层
│   ├── conftest.py               # 去 _DEFAULT_SPEC 降级链
│   ├── fixtures/
│   ├── unit/<能力域>/            # client/query/download/crossmatch/multiband_photometry/pipeline/protocol/contracts/scripts/config/meta
│   ├── integration/ / live/
│   └── upstream/                 # 去版本号 + topic 合并 + README
├── evals/                        # 质量评审层
│   ├── eval_runner.py / scoring-rubric.yaml / test-scenarios.yaml（唯一 canonical）
│   ├── cases/                    # 15 行为用例重写
│   └── audit/                    # 六审计器 + 反证夹具（含 docstring 覆盖率维度）
├── docs/            [local-only] # ISSUES.md, CODE-QUALITY-FIX-LIST.md, diagrams/, architecture/
├── best_data/       [gitignored] # 运行时数据
├── temp/            [gitignored] # 唯一临时区（.qdeep 留档）
└── .checkpoints/    [gitignored] # 运行时检查点状态
```

### 结构变更清单（Phase 0 执行）
| # | 原名 | 新名 | 理由 |
|---|------|------|------|
| 1 | `src/astro_best/` | `src/`（平铺） | 去 astro_best 层；包名 = src；82 处 import 全量改写；SKILL.md 兼容路径同步；S4 承诺变更为「函数能力不变、import 路径随重构演进」记 CHANGELOG |
| 2 | `scripts/` | `ops/` | 消除与 `src/scripts/` 撞名 |
| 3 | `scripts/cli.py` | `ops/astro_best_cli.py` | 消除与 `src/cli.py` 撞名 |
| 4 | `src/astro_best/cli.py` | `src/__main__.py` | `python -m src` 入口 |
| 5 | `models/` (顶层) | `weights/` | 消除与 `src/models/` 撞名 |
| 6 | `src/astro_best/references/` | `src/kb/` | 消除与 `references/` 撞名 |
| 7 | `bridge/` (2 文件) | `ops/register_skill.py` | 去重 + 并入运维层 |
| 8 | `contracts/skills-spec.local.yaml` | `references/skills-spec.local.yaml` | spec 快照归位参考层 |

src/ 平铺细则: `git mv src/astro_best/* src/` + 删空目录; 全部 `from astro_best.X` → `from src.X` (82 处, 含 src 内部 21 处互引); sys.path 锚点改仓库根 (ops/astro_best_cli.py, evals/eval_runner.py, rag/astro_rag.py, test/conftest.py, examples/); pyproject `pythonpath=["src"]` → `["."]`; kb/ 等 parents[N] 改「向上找标志文件 (manifest.yaml)」健壮查找 (Q-39); `python -m src` 验证入口。

---

## 一、对齐决策总览（11 轮 39 项）

| # | 决策 | # | 决策 |
|---|------|---|------|
| 1 | 作用域: 仅 astro-best | 21 | Q-* 先验证后分层纳入 |
| 2 | SKILL→README 三位一体 | 22 | 死代码分级处置 |
| 3 | 树防损坏硬门禁 (README=SSOT) | 23 | 实网受控取样进本轮 |
| 4 | README 树=自动生成文件级全树 | 24 | 学 Tashan 模式并创新 |
| 5 | temp/ 唯一临时区 | 25 | NADC OAuth 接入 |
| 6 | 结构变更 ask_user_question 请示 | 26 | OAuth 本地回环+手动兜底 |
| 7 | 权限矩阵 + 计划批量批准 | 27 | token 用户级缓存 0600 + env 凭据 |
| 8 | test=能力实现回归 | 28 | OAuth/form 双轨 |
| 9 | evals=全 skill 质量评审层 | 29 | auth/ 独立子包全套治理 |
| 10 | evals 靶目录 6 个全覆盖 | 30 | OAuth 暂不申请, mock 兜底 |
| 11 | evals 全面重建 | 31 | git 核对+基线提交 |
| 12 | test 能力域重组+合并去重 | 32 | 所有重名消除（8 项，见上表） |
| 13 | 删 2 死测试文件 | 33 | cli 两层都改 |
| 14 | conftest 去降级链 | 34 | bridge 合并为单一 Python 脚本 |
| 15 | 场景 __twh_2 基线合并 | 35 | src/ 平铺, 包名 = src, import 全量改写 |
| 16 | docs/ 去跟踪+清单标注 | 36 | examples/I-O 规范精细定义+契约守护 |
| 17 | 删 schemas/ | 37 | 注释全覆盖独立 Phase + evals docstring 审计维度 |
| 18 | 双层 scripts 边界声明 | 38 | README 逐文件能力边界（每文件夹一节+文件级表） |
| 19 | 全仓禁版本号, CHANGELOG 转 local | 39 | static 两个两阶段片段互补保留边界分列 |
| 20 | pyproject 剥离构建段 | | |

---

## 二、README 逐文件能力边界设计（Phase 0 产出物）

README.md 结构:
1. 顶部: 定位 + 必读链声明 (SKILL→README) + 治理铁律 (temp/唯一临时区/结构变更需批准/禁版本号)
2. 治理规则节: 权限矩阵 + 临时文件 + 版本禁止 + 平台部署前提 (topiclab publish/install, workspace 边界, zip 限制)
3. **逐文件能力边界**: 按 17 个文件夹分节, 每节 = 文件夹职责声明 + 文件级表格 (文件 | 能力边界 | 治理规则), 全树全覆盖
4. 文件树 SSOT: 自动生成的文件级全树代码块 (verify 校验对象, local-only 目录标注)

---

## 三、分阶段执行计划

### Phase 0 — 结构对齐与治理基石
`chore(astro-best): align tree boundaries and establish governance baseline`
1. git 核对: `git status/log` 全量审查 → WIP (CHANGELOG.md M, .qdeep.py ??, CODE-QUALITY-FIX-LIST.md ??, docs/architecture/ ??) 作为「审计存档」基线提交
2. 结构变更 8 项（见上表）: git mv + import 全量改写 (82 处) + 锚点同步（先 grep 复验每个锚点）
3. .gitignore += docs/ temp/ CHANGELOG.md .checkpoints/
4. `git rm -r --cached astro-best/docs` + `git rm --cached astro-best/CHANGELOG.md`
5. `temp/` + `temp/README.md` 留档 (.qdeep.py/.qdeep.out 移入)
6. `ops/verify_tree_integrity.py`: 扫描实际树（排除缓存），与 README 树清单 diff; `--write` 再生成; local-only 标注
7. README.md 重写: 逐文件能力边界表（17 节）+ 文件级全树 SSOT + 治理规则 + 平台部署前提节
8. SKILL.md: 必读 README 指令 + 治理铁律 + 去 version frontmatter + 兼容 API 路径改 src.*（≤100 行 G6）
9. manifest.yaml: always_load += README.md; 去 version; entry_points 改 ops/; on_demand 路径同步
10. Makefile: +verify 目标; 引用改 ops/; lint 扩 6 目录; eval 接入 check/all; clean 不删 best_data
11. architecture.md: 12 治理面更新（树 SSOT/临时文件/无版本号/OAuth 预留）
12. CHANGELOG.md (local): 记录 S4 import 承诺变更

出口: README 树 == 实际树; make lint == ruff check .; pytest 仍全绿（改写不破坏 import）; `python -m src --help` 可用

### Phase 1 — 去版本号与死资产清除
`chore(astro-best): purge version fields and dead assets`
1. 删全部 version 字段/marker; `src/__init__.py` 删 `__version__`; 删 `_version.py`
2. pyproject.toml 剥离构建段
3. 删 schemas/; 删死测试 (test_auth_store, test_server_api)
4. 删死代码连带测试: mcp_client+services/, processor(+5), repair, serialization(+1), _parse_csv_text/_count_url(+3), models/output.py 空模型; 验证后删 src/scripts/rag.py (BestRAGEngine)
5. evals 场景 5→1（__twh_2 基线 diff 合并, 去 version/BOM, 合并结果过目后删 4 变体）
6. BOM 清除; 陈旧路径修复; test/unit/__test_tmp__/ → temp/; CRLF 归一; CHANGELOG 全记录

出口: pytest ≥173 passed / 0 failed; README 树 regenerate 同步

### Phase 2 — test 能力域重组与测试有效性
`refactor(astro-best): reorganize test suite by capability domain`
1. test/unit/<能力域>/ 11 子目录; gen_algo_* 12 个按被测对象合并去重（全树 test 文件名唯一）; 每次合并 pytest
2. test/upstream_pybest_0_3_2_8/ → test/upstream/; tap_* 8 个合并 ~5 文件 + README
3. live 归位: integration/test_live_*.py 核对 gate 后 → live/
4. conftest: 删 _DEFAULT_SPEC 降级链; get_spec_data 收敛 13 份副本（utf-8-sig, 读 references/skills-spec.local.yaml）
5. Q-11/Q-12 假防护修复; Q-24 清 pycache 口径; Q-34 skip 预算文档化

出口: passed ≥173 断言只增不减; skip ≤40 全部可归类

### Phase 3 — 科学正确性 P0（数据语义）
`fix(astro-best): unify BEST data semantics on protocol layer`
1. 锚点复验（Q-01/02/03/04/05 对 HEAD 探针）
2. Q-01+Q-10 同批: cone_search 调 protocol.build_query_form; test_build_form_* 改写为协议键集断言
3. Q-02/Q-05: 统一 protocol.parse_csv_rows（has_header 动态判定）
4. Q-03 波段列名映射; Q-04 from_row catalog 透传
5. Q-06 全 emitter 接 csv_safety; Q-23 真实计数; Q-22 std 处理; Q-26 output.fmt 统一
6. 突变出口: M8/M10/M11/M12/M13 转红; 探针幻影源消失

出口: §13 门禁 4/5/6

### Phase 4 — 链路完整性与声明面收敛
`fix(astro-best): close wiring gaps and align declarations`
1. Q-54 下载强制 checksum; Q-55 kb/ 路径修复+接 CLI
2. Q-15/Q-56 core 孤岛互通+声明符号改正+「声明点必须可 resolve」契约测试
3. Q-14 门禁 fail-closed; Q-51 入参校验接线; Q-16 env SSOT; Q-52 truncate 副本语义
4. Q-17/Q-18/Q-21 并发/Session/凭据; Q-19 cli 退出码
5. Q-27/Q-28/Q-60 _write_rows+escape+utf-8-sig; Q-58/Q-59 记录并集+import 卫生
6. Q-29/Q-30/Q-31/Q-32/Q-37/Q-39/Q-57 声明对齐; templates source/ 键收 defaults; ops/register_skill.py 修 Q-32
7. 突变出口: M14 转红; import-graph 测试: protocol 公开符号 ≥1 生产引用

出口: §13 门禁 7/8/11/12; lint 全仓零告警

### Phase 5 — evals 质量评审层重建
`feat(astro-best): rebuild evals as whole-skill quality gate`
1. eval_runner.py 重建（无 fail-open/-O 安全/given 必喂/未知 id 报错/权重代码校验）
2. scoring-rubric.yaml 重建（行为 4 维 + 内容质量维度, targets 6 目录）
3. cases/ 15 用例重写; audit/ 六审计器（references/knowledge/templates/contracts/static/tests）
4. docstring 覆盖率维度: 公开函数无 docstring 即红（Phase 7 验收锚）
5. 反证夹具: 每审计器附 broken/ 坏样本; make eval 接入 check/all

出口: 双模式全绿; 反证夹具按预期失败; 破坏生产代码评分下降

### Phase 6 — NADC OAuth 接入
`feat(astro-best): add NADC passport OAuth2.0 identity layer`
1. `src/auth/`: nadc_oauth.py（authorize_url/exchange_code/get_profile/logout）+ token_store.py（~/.astro-best/nadc_token.json, 0600, expires_at 过期重取）
2. 本地回环回调 + 手动粘贴兜底
3. contracts/oauth.contract.yaml; references/ALGORITHM-SPEC.md §5 OAuth 白盒
4. test/unit/auth/ mock 全流程; evals oauth 契约审计
5. provenance envelope 实现（Q-08: data_hash + umtId 血缘）; QueryContext.record 接线（Q-52 载体）
6. .env.example 增补 NADC_OAUTH_CLIENT_ID/SECRET/REDIRECT_URI; 外部前提登记 blocked-on-approval

出口: OAuth 单测全绿; 凭据零字面量扫描通过

### Phase 7 — 注释全覆盖
`docs(astro-best): full docstring coverage across implementation`
1. src/ 全部公开函数 docstring 五要素: 职责/参数量纲/返回值/异常/门禁关系
2. 模块头 docstring: 职责 + 能力边界 + 白盒锚点 (references/ALGORITHM-SPEC.md §N)
3. 关键算法行内注释: 公式 + 量纲 + 设计理由
4. 沿用仓内中文 docstring 风格; 无凭据字样
5. evals docstring 审计维度转绿作为出口

出口: evals docstring 覆盖率维度 PASS; 抽样人工审阅通过

### Phase 8 — 实网受控取样与全链路验收
`test(astro-best): controlled live sampling and full-chain acceptance`
1. 实网取样（<100 样本点）: V-1 键行为/V-2 表头/V-3 分页; 回写 lessons_learned
2. V-6: oauth.china-vo.org 连通性探测（真实授权流 blocked-on-approval）
3. README 树终版 regenerate + verify 绿
4. §13 十二门禁 + docstring 审计 + make all 全绿; CHANGELOG 全记录

---

## 四、验收标准（量化）

1. pytest: 0 failed; passed ≥173; skip ≤40 可归类
2. evals: 行为+审计全绿（含 docstring 覆盖）; 反证夹具按预期失败; 破坏生产代码评分下降
3. verify_tree_integrity: README 树与实际零 diff
4. ruff 6 目录零告警; make lint == ruff check .
5. 突变 M8/M10/M11/M12/M13/M14 转红; 每 P0 配定向突变证据
6. 声明面全部可 importlib resolve（src.* 新路径）
7. OAuth mock 全绿; 凭据零字面量; token 0600
8. docstring: 公开函数 100% 覆盖（evals 维度证明）
9. `python -m src` 入口可用; make all 一键全绿

## 五、风险与回滚

| 风险 | 缓解 |
|------|------|
| 多 Agent 并发写入 | 每 Phase 前 git 核对; 每 Phase 一原子 commit; 锚点先验证 |
| import 全量改写漏改 | git mv 后先 `python -c "import src"` 冒烟 + pytest 全绿作证; grep astro_best 残留归零 |
| 死代码删除砍到在用模块 (Q-62) | 只用双口径结论; 删后全量测试绿作证明 |
| OAuth 审批未下 | mock 兜底 + blocked-on-approval 标注 |
| 实网触达率 | 受控预算 <100 样本点 |

## 六、Tashan 模式学习要点（已融入）

1. SKILL.md 即平台交付物（publish --content-file）→ ≤100 行 + 必读 README 链
2. workspace 边界（禁 ../ 逃逸）→ 安全面 9 对齐 + README 树 = workspace 地图
3. zip 蓝图导入（≤5MB/≤300 文件）→ 树 SSOT 兼作期望清单; temp/best_data/docs 排除分发
4. temp/ ↔ session uploads/ 概念同构
5. CLI-first → ops/astro_best_cli.py 保持运维入口地位
