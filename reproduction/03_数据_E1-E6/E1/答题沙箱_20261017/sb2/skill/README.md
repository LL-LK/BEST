# astro-best — NADC BEST 数据源主理 Skill

> **必读链**: `SKILL.md`（入口与治理铁律）→ **`README.md`（本文件：逐文件能力边界 + 文件树 SSOT + 治理规则）** → `manifest.yaml`（加载地图）→ `architecture.md`（架构规范）。
> 任何 AI Agent 处理本 skill 任务前，必须完整阅读本文件以建立文件树地图；禁止在未读本文件的情况下猜测目录用途或改动结构。
>
> **定位**: 全 ecosystem 只有本 skill 能访问 `nadc.china-vo.org/data/best`（该站点无 TAP/ADQL/REST-JSON 端点，只有 Django form 两阶段协议）。astro-catalog 主理 SIMBAD/VizieR/Gaia 等通用检索，**不具备 BEST 访问能力**——BEST 数据任务必须路由到本 skill。

## 快速上手

```bash
python ops/astro_best_cli.py doctor                    # 离线自检（导入/版本门禁/配置诊断）
python ops/astro_best_cli.py rag "气团 计算" --top-k 3  # 本地知识混合检索
python -m src --help                              # 包级 CLI（python -m src 入口）
python -m src.tap.service --db temp/tap.db --out temp  # IVOA TAP 网关（可选，async 需 db+out）
make check                                        # test + lint + verify + audit
make audit                                        # 治理护栏 12 项硬门禁（见 ops/audit/README.md）
make eval                                         # [已净化] 质量评审
make verify                                       # 文件树完整性硬门禁
```

## 治理规则（对人与 AI 同等约束）

1. **权限矩阵**：既有文件的**内容编辑**（修 bug/补断言/补注释/改文档）自由；**结构变更**（被跟踪文件/目录的新增、删除、移动、重命名；`.gitignore` 规则增删；本文件树清单变更）必须经用户明确批准（会话内结构化提问），批准后以 `python ops/verify_tree_integrity.py --write` 重新生成树清单。
2. **临时文件**：只允许进入 `temp/`（gitignored）。其他任何位置出现临时文件即违规，`make verify` 与 [已净化] 审计可检出。
3. **禁止版本号**：全仓不得出现发布版本号（含 schema_version/template_version 等标记）。变更历史只记录在 `CHANGELOG.md`（已入版本控制）。
4. **文件树 SSOT**：本文件末尾的树清单块是唯一 canonical 快照，由 `ops/verify_tree_integrity.py` 生成与校验；实际树与清单不一致即非零退出（阻断）。**注意树门禁只比对「树块 ↔ 文件系统存在性」，不比对 git index** —— "文件在磁盘上、树块里也写了、但从未 `git add`"这一状态它看不见（`ops/audit/` 11 个文件曾长期如此），该缺口由规则 11 单独守。
5. **local-only 目录**：`temp/`（临时区）、`best_data/`（运行时数据）、`.checkpoints/`（运行时状态）不随 git 分发；树清单只登记其存在性。`CHANGELOG.md` 原在此名单内（走 `.gitignore`），2026-10-05 改判为**入版本控制**——它是删改记录的唯一载体，留在仓外等于无记录、新克隆者无从追溯，故现在不在本名单内。**`docs/` 自 2026-09-28 起整体入版本控制**（经用户批准：六份 `eval-E*` 实验方案与 `docs/architecture/` 计划需随专用远程仓库分发；更早的「docs/ 整体 local-only」决策已作废——本条曾长期停留在旧决定上，而 git 里实际跟踪 28 个 `docs/` 文件，`governance-debt-plan.md` §12.2 遗留观察项 4 记的就是这个矛盾）。`docs/diagrams/` 下的 PNG/SVG/PDF 渲染产物（约 27.9 MB）仍不跟踪、本地保留，理由与再渲染方式见 `docs/diagrams/README.md` §1/§5。
6. **数据边界（禁外泄/禁打包）**：本 skill 的代码、文档、知识库与任何运行产物（含下载数据、日志、进度文件）**仅限本机工作区使用**；未经用户明确授权，不得发布、上传、打包或拷贝到任何外部平台/仓库/分享渠道，不得接入第三方分发链路。凡涉及对外暴露的改动（新平台接入、CI 外发、包构建），先 ask 再动工。
7. **规模预算与中文注释**：单个 `.py` 的**净代码行**（剔除空行/`#` 注释/docstring）非必要不超过 400 行；超限文件必须在 `docs/architecture/file-size-budget.md` §3 登记必要性论证与拆分预案。所有注释与 docstring 一律中文，**每个 class/function/method 必须有中文 docstring**，每个 import 组至少一条中文说明，每次外部 API/IO 调用一条中文行内注释。**每个文件开头必须有覆盖整个文件的详细模块头 docstring**（含中文、≥160 字符，写清职责/子系统/对外接口/数据流/不变量/陷阱六项），**注释密度（注释行 ÷ 净代码行）≥ 0.10**（净代码行 < 15 的小文件不判）。**注释位置：代码在左、注释在右** —— 语句级注释一律写在代码同一行的行尾（与代码至少隔 2 个空格，同一块内对齐成列），只有文件头 docstring、成组说明与分节横幅留在代码上方；行尾注释占比（行尾注释行 ÷ 净代码行）同样 ≥ 0.10。`noqa`/`type: ignore`/分隔线不计入占比。"每一行都有注释"按**非平凡语句**执行：样板行（import/return/收尾括号）不写，注释只解释「为什么」不复述代码。白名单（可留英文）：shebang、`# noqa`、`# pragma: no cover`、`# legacy-import-guard`、`# type: ignore`、`# ---` 纯分隔线。规范全文与四道防回归护栏见 `docs/architecture/file-size-budget.md` §4，注释密度与位置标准全文见 `ops/audit/README.md`「注释密度标准」。复测：`python ops/audit/count_code_lines.py`；只改注释的护栏：`python ops/audit/code_fingerprint.py check`（必须 `code-changed=0`）+ `python ops/audit/verify_no_code_loss.py`（退出码 0）+ `python ops/audit/comment_audit.py`（**十五类**计数全 0，含 `referenced_path_missing`：注释与 docstring 引用的**仓内路径必须真实存在**；`line_alignment_low`：**非平凡语句**的行尾注释占比 ≥ 0.70，样板行（import/return/收尾括号）、数据行（星表列名表、指标定义表）、import 续行名单行、多行函数签名参数行均不进分母——「注释只解释为什么，不复述代码」，给列名逐行写右注属注水；且**注释里不写会腐化的裸数量**，要写就紧邻被数的定义）。
8. **覆盖矩阵 SSOT**：`docs/architecture/coverage-matrix.md` 一行 = 一条关键路径能力，五列证据锚点（anchor/unit/integration/eval/status）必须全部真实。新增能力必须同步登记，否则 `test/unit/meta/test_coverage_matrix.py` 失败；`status: gap` 必须在矩阵 §3 登记（已知未修可长期存在，无声缺口不允许）。复测：`python -m pytest test/unit/meta/test_coverage_matrix.py -q`。
9. **契约路径必须为真**：`references/skills-spec.local.yaml` 的 `algorithms[].module`、`contracts/io-contract.md` 算子表、`contracts/**.yaml` 的 `module:` 值，每一个都必须**可导入且同名符号存在**，死路径由 `test/unit/meta/test_module_paths.py`  fail-closed。扩 spec 时同步扩矩阵（规则 8）。
10. **单模式评测不得宣布通过**：`[已净化]` 引入 `measured` 语义——`--mode audit` 不跑行为探针、`--mode behavior` 不跑审计/docstring 维度时，相应维度记 0.0 并报 `NOT_MEASURED`，同时加入 `behavior_not_measured`/`docstring_not_measured`/`audit_not_measured` 三条阻断。只有 `--mode all` 能给出合格判定。防的是"零证据也能拿高综合分"的 fail-open。
11. **文件必须入库 + 权威版本库是 `astro-best/.git`**：磁盘上存在、且未被 `.gitignore` 忽略的文件必须受 git 跟踪（门禁 `test/unit/meta/test_gate_blindspots.py::TestGitTrackingCoverage`，判据是 `git ls-files --others --exclude-standard` 必须为空）。**本 skill 是独立 git root**；父目录 `G:/tw/twskills` 是另一个仓库、已不再跟踪本目录，所有 git 操作（commit/diff/ls-files/log）都在本目录内执行——从父目录操作会让 HEAD 基线分叉，`ops/audit/` 里按 HEAD 比对的工具会读错仓库。
12. **治理护栏分两档**：`make audit` 里是 **12 项硬门禁**（`count_code_lines` 超限未登记即红、语法坏文件即红 / `comment_audit` 十五类计数须全 0 / `code_fingerprint check` / `verify_import_graph` / `verify_crossrefs` / `verify_doc_consistency` / `verify_no_version_keys` / `verify_evidence_anchors` / `verify_counting_claims` / `verify_eval_report_assets` / `verify_measurement_registry` / `verify_archive_privacy`，均须 exit 0），已接入 `make check` 与 `make all`；`verify_no_code_loss` / `scan_code_smells` / `version_scan*` / `check_line_endings` 为**报告型**，刻意不阻断（需人判读，强行阻断会误伤正常重构）。**扫描面型**的那几道另带负对照闸：扫描面为空时显式判红（`verify_crossrefs` / `verify_evidence_anchors` 本来就是 fail-closed 的，是其余的范本）。工具清单、注释密度与位置标准、已知局限与 ROOT 约定见 `ops/audit/README.md`。
13. **注释里的缺陷编号必须可解析**：`src/` 与 `test/` 的注释引用了 30 个 `YZ-NN` 编号，每个都必须在 `docs/architecture/yz-registry.md` 有条目（一句话缺陷 + 代码落点 + 回归测试）。审计轮次 AH5 的结论是这些编号「只存在于注释与报告、无定义文档」，读者只能靠猜、`grep YZ-15` 搜不到「15 是什么」；登记册补齐后两侧集合须**逐个相等**（既无「代码用了而表里没有」，也无「表里有而代码没用」）。新增编号须同批补表，两者缺一就是又造一个死引用。

## 逐文件能力边界（全树全覆盖）

### 根目录文件

| 文件 | 能力边界 | 治理规则 |
|------|----------|----------|
| `SKILL.md` | skill 入口：定位/主理委派边界契约/API 快查/质量门禁/场景路由/组件地图/完成自检 | ≤100 行（G6）；首步必读 README；禁版本号 |
| `README.md` | 本文件：必读链/治理规则/逐文件边界/树 SSOT | 树块仅 verify --write 可改 |
| `manifest.yaml` | 声明式加载地图 SSOT：axes/always_load/on_demand/entry_points/redirects/quality_gates | 路径变更需批准；always_load 含 README.md |
| `architecture.md` | 架构规范：五状态机（INTAKE→VALIDATE→EXECUTE→GATE→EMIT）+ 12 横切治理面 + 门禁表 | 与 contracts 联动不同步 |
| `pipeline.yaml` | 流水线声明：stage/dependencies/sub_skills/outputs/workflows（tool 符号须可 importlib resolve） | 声明面 Phase 4 收敛 |
| `pyproject.toml` | 仅工具配置：`[tool.pytest.ini_options]`/`[tool.ruff]` | 无构建段、无版本号 |
| `Makefile` | 工程入口：test/test-unit/test-integration/lint/format/doctor/eval/verify/check/clean/all | verify 目标接入 |
| `.gitignore` | 分发边界：Python/IDE/缓存/data/local-only 四目录 | 规则增删需批准 |
| `.env.example` | 凭据与配置环境变量 SSOT 示例（BEST_* + NADC_OAUTH_*） | 与 src/scripts/config.py 双向一致（Q-16） |
| `environment.yaml` | conda 运行环境锁（硬依赖/互操作/可选/本地工具） | 依赖真实性 AST 校验（Q-42，`test/unit/meta/test_environment_lock.py` 双向守护：多声明/漏声明即红） |
| `CHANGELOG.md` | 变更历史（删改记录唯一载体） | 已入版本控制（2026-10-05 由 local-only 改判） |

### `agents/` — Persona 提示词层

| 文件 | 能力边界 | 治理规则 |
|------|----------|----------|
| `openai.yaml` | Persona：AI 角色定义与决策 Prompt 契约（逐状态对应 architecture.md） | 内容编辑自由 |

### `contracts/` — I/O 契约 SSOT（被 [已净化] 审计）

| 文件 | 能力边界 | 治理规则 |
|------|----------|----------|
| `envelope.contract.yaml` | 跨节点双态信封 schema（data/decision，astro-envelope 线协议） | Phase 6 实现构造链 |
| `input.contract.yaml` | 输入契约（sql/token 字段，legacy 委派面） | 与 `src/models/input.py` 的一致性**未**被 test 守护（已标注 legacy，勿当现输入面） |
| `output.contract.yaml` | 输出契约（data/status 字段） | 信封事实标准是 `src/provenance.build_envelope`；本契约为 schema 索引 |
| `pipeline-stage.contract.yaml` | 流水线阶段契约（stage 枚举/迁移条件） | — |
| `provenance.contract.yaml` | 血缘契约（session_id/data_hash/lineage/completeness_gate） | Phase 6 接 OAuth umtId |
| `error-codes.contract.yaml` | 错误码枚举（不静默吞异常）; BEST_1006=E_SOFT_404 软错误显式失败 | 常量须被代码引用 |
| `io-contract.md` | 契约层人类可读面孔：主理/委派/门禁/白盒算子索引/信封约定 | 与 SKILL/manifest 表述对齐（Q-37） |
| `fields/data.contract.yaml` | 字段级 schema：data（object/mixed） | 被 test_gen_fields 守护 |
| `fields/sql.contract.yaml` | 字段级 schema：sql（string/dimensionless） | 同上 |
| `fields/status.contract.yaml` | 字段级 schema：status（string/dimensionless） | 同上 |
| `fields/token.contract.yaml` | 字段级 schema：token（string/credential） | 同上 |

### `[已净化]` — 质量评审层（行为评测 + 内容质量审计 + docstring 维度）

> [已剥离] 评测层组件清单整段移除 —— 它逐行登记判分脚本与[已净化]（含维度名、权重和、[已净化]），属判分逻辑，不应出现在模型可见面。

### `examples/` — 人读示例（lint 覆盖，并由 `test/examples/` 离线执行防腐烂）

| 文件 | 能力边界 | 治理规则 |
|------|----------|----------|
| `example_skill_usage.py` | 库 API 用法演示：BestSkillClient/BestCrossMatch/BestClient 典型调用形态 | 随 API 演进而更新；由 `test/examples/` 离线桩执行守护 |
| `example_quickstart_client.py` | 端到端快速上手：查询→下载最小闭环 | 随 API 演进而更新；由 `test/examples/` 离线桩执行守护 |

### `ops/` — 运维入口层（路径调用，零 import）

| 文件 | 能力边界 | 治理规则 |
|------|----------|----------|
| `astro_best_cli.py` | 运维 CLI：doctor（离线自检）/rag（知识检索）/log（任务日志 problems/summary）/领域演示子命令；含 `_safe_path` 数据根锚定 | 成功退出码必须 0（Q-19） |
| `verify_tree_integrity.py` | 文件树硬门禁：扫描实际树 vs README 清单 diff；`--write` 再生成；`--diff` 明细 | 更新需用户批准 |
| `register_skill.py` | 技能登记辅助：向 `_shared/skill-registry.yaml` 输出登记条目（只打印不写） | 零网络零凭据 |

### `rag/` — 知识检索层（全树唯一 RAG）

| 文件 | 能力边界 | 治理规则 |
|------|----------|----------|
| `astro_rag.py` | 唯一 RAG 执行器：BM25+词桶+RRF 混合检索，加载 `rag/knowledge/` | 双 RAG 已归一（BestRAGEngine 已删） |
| `knowledge/best_practices.yaml` | 结构化最佳实践规则 | [已净化] knowledge 审计 |
| `knowledge/citations.yaml` | 论文引文全集（9 verified / 2 unverified，DOI 经 Crossref 实核；引文唯一权威源） | verified 才可静默引用；unverified 必须带标注 |
| `knowledge/domain_rules.yaml` | 领域规则（VALIDATE/GATE 态咨询） | 检索失败不阻断主链 |
| `knowledge/known_issues.yaml` | 已知问题库（degradation 路径加载） | 降级须 WARN 注记 |
| `knowledge/lessons_learned.yaml` | 经验教训库（每次任务回写） | CLAUDE.md 铁律 |

### `references/` — 白盒文档内容层（被 [已净化] 审计）

| 文件 | 能力边界 | 治理规则 |
|------|----------|----------|
| `ALGORITHM-SPEC.md` | 算法白盒 G7 五要素：端点表/两阶段协议/真源码锚点/超参/DOI 核验；§4 OAuth 白盒、§5 proximity 批量匹配、§6 TAP 适配层、§7 工具面 | 唯一白盒出处 |
| `auth-and-oauth.md` | 双轨鉴权与上鉴权准备（智能体使用向）：数据轨 BestAuth Django 会话/身份轨 NADC OAuth2.0/三闸门//jobs 第一跳/上鉴权七步清单（第 2/5/6 项已接线，1/3/4 阻塞待站点账号与 OAuth 审批）/失败语义 | 凭据只走 env，代码零字面量；契约权威 contracts/oauth.contract.yaml |
| `best-database-guide.md` | BEST 数据库领域指南（端点清单/表单字段/输出格式/约束） | — |
| `data-formats.md` | BEST 数据格式全景与解析能力边界：`output.fmt` 全集处置/两阶段分岔/单位陷阱/FITS 纯本地转换地位 | 线上 vs 本地格式集合差异的唯一依据（protocol 与 serialization 双向一致） |
| `fallback-protocols.md` | 降级协议（检索失败/端点不可达） | — |
| `photometric-systems.md` | 官方文档镜像：19 测光系统全表 / SCR 精度口径 / 8 个 Well-Calibrated 表精度规模 / User-Defined FITS 协议 / 文档-现实偏差实证 | 论文引文下沉 rag/knowledge/citations.yaml |
| `site-endpoints-and-interactions.md` | 站点端点与交互全图（智能体使用向 SSOT）：路由全表/表单字段/结果页导出与 SAMP/dbgrid live 状态/登录态边界/复现步骤/§6bis 协议细节实测/§8 TAP 迁回忆审/§9 2026-09-29 端点列全覆盖审计 | 实机浏览器深潜，证据 temp/site_dive/ 与 temp/audit_* |
| `download-playbook.md` | 下载能力使用向 playbook：后台模型/进度同源/并行/两级续传/hook ask 纪律/精准下载/常见需求与坑解法 | 下载相关能力的唯一使用向 SSOT |
| `tools.schema.json` | 7 个原子工具的 JSON Schema 契约（function-calling 直接消费）；信封字段与错误码对齐 contracts | 与 src/ai_tools.py 双向一致 |
| `llms.txt` | 智能体发现向索引：工具清单 + 协议要点 + 文档导航 | 内容随 references 演进 |
| `client-api-reference.md` | 客户端 API 参考（BestClient/BestQuery/BestMultiBandPhotometry/BestDownloader/BestCrossMatch 签名与单位） | 单位陷阱 (deg vs arcsec) 高频出错点 |
| `skills-spec.local.yaml` | 本地 spec 快照（Fallback SSOT，脱离大仓独立分发时供测试消费） | 模块路径与 src 同步 |

### `src/` — 实现层（包名 = src，`python -m src` 入口）

| 文件 | 能力边界 | 治理规则 |
|------|----------|----------|
| `__init__.py` | 包门面：`__all__` 13 项导出（BestClient/BestAuth/BestQuery/BestMultiBandPhotometry/BestCrossMatch/BestDownloader/CatalogType/ColumnConstraint/BestSource/BestQueryResult/ResolvedName/cone_search/crossmatch_coords） | 导出须可解析 |
| `__main__.py` | 包级 CLI：cone/download/crossmatch/catalogs/info/doctor 子命令（rag 检索入口在 ops/astro_best_cli.py） | 凭据走 env/getpass |
| `client.py` | `BestAuth`（Django session+CSRF）/`BestClient`（两阶段异步 REST：POST 表单→sqlid→分页 GET；getcount 真实总数+truncated；resolve_name 名称解算；columns/sort/order/nearest_only 参数；软 404 显式失败） | 表单键集以 protocol 为权威（Q-01） |
| `best_export.py` | 字节级流式下载实现（HTTP Range 断点续传 + 取消 + 主机白名单）：格式相关写出委托 serialization；请求可调用体由 `BestClient.download_file` 注入（节流/重试/软错误仍归客户端） | P1 合并后唯一存留关注点（原 save_result/fetch_pages 双副本随 pybest 删除） |
| `query_builder.py` | `BestQuery` 列约束查询构造器（cone/box/mag_range/where；空间约束以原生区域记录并经 to_form() 委托 protocol，P1-10） | 契约↔签名对齐（Q-30） |
| `downloader.py` | `BestDownloader`：流式下载 + checksum 校验 + 断点续传 | 下载完成强制 verify_checksum（Q-54） |
| `crossmatch.py` | `BestCrossMatch`：坐标交叉匹配（Gaia/PS1）；crossmatch_batch 服务端 proximity 一次提交替代 N 次锥搜（P0-1），逐点路径保留为回归基线与 fallback | manifest 声明单点失败隔离（Q-17） |
| `multiband_photometry.py` | `BestMultiBandPhotometry`：多波段静态测光容器（BEST 无时序，非光变曲线） | 未识别列须显式失败（Q-29） |
| `protocol.py` | 权威协议层：表单键集/CSV 解析（has_header 动态判定）/计数解析/sqlid 规范化/列名限定/软 404 检测（is_soft_error/Soft404Error）/名称解算解析（/nss/solve 哨兵）/重试策略常量（RETRY_STATUS_CODES/MAX_RETRIES/RETRY_BACKOFF_S/MAX_BACKOFF_S） | 公开符号须 ≥1 生产引用（Q-09） |
| `protocol_catalog_tables.py` | 星表路由/列/波段/质量列权威数据表（纯数据无函数：查询路径/导航分组/别名/显示名/showcol/响应列/星等列映射）；protocol 以 re-export 保留全部公开名 | 数据表不占 400 行净代码逻辑额度 |
| `csv_safety.py` | CSV 公式注入消毒器（`sanitize_cell` 正确放行负数） | 全 emitter 接线（Q-06） |
| `serialization.py` | BEST 原生输出格式单一事实源：CSV/TSV/JSON/VOTable/FITS 本地导出（downloader 下载路径的落盘层, P1 合并后唯一存留路径） | 禁第二套写出逻辑；线上格式集以 protocol 为权威 |
| `models/__init__.py` | 行模型：BestSource/BestQueryResult（含 truncated）/CatalogType/ColumnConstraint/ResolvedName + 输入输出模型再导出 | from_row 透传 catalog（Q-04）；哨兵与 proximity 元数据列不当测光 |
| `models/input.py` | 输入模型（ConeSearchInput/DownloadInput/SourceQueryInput） | 与 input.contract 对齐 |
| `models/output.py` | 输出模型（BestResultSet/QueryOutput/DownloadOutput/QualityReport，契约匹配的实质模型） | Phase 6 接入真实构造链（Q-08 接线路线） |
| `core/__init__.py` | `BestSkillClient`/`QualityGate`（min_snr/max_fwhm 门控，fail-closed） | 无指标不得放行（Q-14） |
| `core/pipeline.py` | `AstroBestPipeline` 编排（配置全量透传） | 孤岛互通（Q-15/56） |
| `core/source_postprocess.py` | `BestProcessor` 领域后处理：球面去重/亮度筛选/波段统计（纯函数静态方法，haversine 与 crossmatch 同口径） | 不发请求、不落盘；禁第二套球面距离实现 |
| `scripts/best_cone_search.py` | 锥形检索入口（入参校验接线） | validate_coordinate 必调（Q-51） |
| `scripts/best_crossmatch_pipeline.py` | 批量交叉匹配管线（crossmatch_with_gaia/with_ps1/batch） | 单点失败隔离 |
| `scripts/best_multiband_export.py` | 多波段测光导出（export/batch_export） | 批量导出入口 |
| `scripts/checkpoint.py` | `DownloadCheckpoint` 断点续传状态 | 只写不列问题（§2.2） |
| `scripts/config.py` | `AstroBestConfig` 配置加载（env→YAML→defaults） | env 三方集合一致（Q-16） |
| `scripts/context.py` | `QueryContext` token 预算与上下文管理 | truncate 不得篡改源计数（Q-52） |
| `scripts/guards.py` | I/O 协议：入参校验 + 输出格式化（to_csv/to_json/validate_adql_query）+ 原子写（atomic_write_text）、目录锚定（resolve_within）、数据根锚定（resolve_data_path）、下载 URL 主机白名单（validate_external_url）四个全包单点 | 编码 utf-8-sig；异构记录并集（Q-58）；禁版本号 |
| `kb/__init__.py` | `references/` 文档加载器（标志文件定位 skill 根） | 接 CLI 子命令（Q-55） |
| `download_manager.py` | 后台/并行下载管理器：submit 即返回（线程池默认 2 并发）、Region/Sqlid/File/Precise 四类任务、cancel/resume、hook 接线、并行唯一文件名 | 前台不阻塞；进度文件为权威 |
| `download_progress.py` | 进度存储：ProgressStore（.progress/ JSON 原子写）+ ProgressTracker（页/字节累加、速度/ETA、blocked/finish/fail/cancel）+ render_text_bar（CLI 文本条，GBK 回退 ASCII） | CLI/GUI 同源事实源 |
| `download_hooks.py` | 分级 hook：network 类指数退避重试≤3、severe 类立即拦截；HookInterrupt ask 载荷（原因+证据+≥2 方案） | 拦截必须 ask，严禁静默 |
| `download_precise.py` | 精准下载：PreciseDownloadJob（source_id 列表 in 约束）、星表 ID 列映射（stripe82=calibstars_id）、0 行/超量 hook ask、行数回核 | ps1_source_id 线上为空（live 实证），ps1 精准下载走 hook ask |
| `download_region.py` | 区域下载编排：std 组展开/断点路由/一次性锥搜落盘（查询/分页/checkpoint/落盘委托 BestDownloader） | 不拼表单、不发网络请求 |
| `download_sqlid.py` | 按 sqlid 的分页下载与断点续传（区域/约束之外的第三条取数路径）：页级 checkpoint 落盘/恢复/删除 | 不建 sqlid、不做格式写出 |
| `download_artifacts.py` | 下载产物落盘辅助：输出路径解析与防逃逸/行记录构建/导航组成员文件合并/provenance sidecar/原始数据列表导出 | 不发请求、不做查询；atomic_write_text 单点 |
| `task_log.py` | 任务日志管理器：JSONL 事件流（.logs/task_log.jsonl）+ tail/problems/tasks/summary 查询 | 与 .progress 分工：日志答“发生了什么”，进度答“到哪了” |
| `ai_tools.py` | 智能体工具面：ToolBox 7 原子工具（resolve_name/list_catalogs/describe_catalog/cone_search/crossmatch_batch/count/fetch_page）+ 统一信封（data/status/cost/provenance）+ best:// 稳定 URI；站点数据标注 untrusted（S-2） | 唯一对外工具面（P1-9 收敛）；schema 权威在 references/tools.schema.json |
| `tap/`（9 个文件） | IVOA TAP 1.1 适配层：adql（有界子集解析）/executor（计划→两阶段协议）/formats（VOTable/CSV/FITS+OVERFLOW）/jobs（UWS sqlite 作业）/client（pyvo 消费端，可选依赖）/response（TapResponse 网关载体与 XML 响应构造）/service（stdlib http.server 路由：sync/async/VOSI/TAP_SCHEMA，Bearer 失败 401 不降级）/uws_service（UWS 作业生命周期与 /results Range 读取，属主不符 403/未完成 409/结果缺失 410） | 不引 FastAPI/pyvo 硬依赖；上游不执行 SQL，查询经白名单计划翻译 |
| `auth/__init__.py` | NADC 通行证 OAuth2.0 身份层门面（Authorization Code only；再导出 ensure_access_token/TokenExpiredError 过期恢复面） | 凭据只读 env；token 缓存静态保护（Windows DPAPI / POSIX 0600） |
| `auth/session.py` | BEST 站点 Django 会话：登录/CSRF 双重校验/会话材料显式移交（与 NADC OAuth 双轨制，数据查询只认 Django 会话） | 凭据只从参数/env 流入，零字面量 |
| `auth/nadc_oauth.py` | OAuth 协议实现：authorize URL/state、code 交换、profile 解析、登出、TokenStore（v2 信封 + DPAPI/0600 静态保护 + 过期重取）、ensure_access_token 过期恢复单点、本地回环流（127.0.0.1 收 code）+ 手动粘贴兜底 | 零凭据字面量；Bearer 与 token 间必须有空格；NADC 无 refresh_token，过期只能重走授权流 |
| `provenance.py` | astro-envelope-v1 双态信封构造（data_hash SHA-256 + session_id + NADC 身份 + lineage 引用） | Q-08 接线；身份缺失不阻断主链 |
| `py.typed` | PEP 561 类型标记 | — |

### `static/` — 提示词静态规则（会话注入 / 按需路由）

> 括号内的 `always_load` / `on_demand` 标注与 `manifest.yaml` 同源：
> `always_load` 9 项、**`static/fragments/` 下 8 份片段全部 8/8 挂 `on_demand`**（2026-10-05
> 三方核对：manifest ↔ README ↔ 磁盘文件集，差集为空）。

| 文件 | 能力边界 | 治理规则 |
|------|----------|----------|
| `core/stance.md` | AI 立场与姿态规则（always_load） | 内容编辑自由 |
| `core/workflow.md` | 五状态机工作流规则（always_load） | 与 architecture.md 联动 |
| `core/output-format.md` | 输出信封/报告格式规则（always_load） | 与 contracts 联动 |
| `fragments/algo_mode/best_auth_mode.yaml` | 认证算法模式片段（on_demand） | 与 client.BestAuth 联动 |
| `fragments/algo_mode/best_two_phase.yaml` | 协议步骤切片：端点/软 404/门禁/env（on_demand） | 与 protocol.py 联动 |
| `fragments/algo_mode/two_stage_async_mode.yaml` | 算法模式契约：entry 符号/hyperparams/outputs/degrade（on_demand） | entry 须可 resolve |
| `fragments/data_source/best_catalogs.md` | 星表数据源知识（on_demand，含 ps1 双记录类型分型） | — |
| `fragments/data_source/nadc_endpoints.md` | NADC 端点知识（on_demand） | — |
| `fragments/target_type/best_ttype.md` | BEST 目标类型判据（on_demand） | — |
| `fragments/target_type/photometry_region.md` | 测光区域语义（on_demand） | — |
| `fragments/target_type/standard_star.md` | 标准星筛选语义（on_demand） | — |

### `templates/` — 模板层（被 [已净化] 审计；每个模板文件头声明唯一消费者）

| 文件 | 能力边界 | 治理规则 |
|------|----------|----------|
| `best-config.yaml` | BEST 专用配置模板（人读配置） | 键收 defaults（Q-31）；去 BOM；文件头声明消费者 |
| `gen_config_template.yaml` | 生成物：通用配置模板（无代码消费者；module 值已对齐真实实现位置） | 文件头声明消费者 |
| `report_template.yaml` | 生成物：报告渲染模板（无代码消费者） | 文件头声明消费者 |
| `gen_case_prep_sql.yaml` | 生成产物：SQL 用例准备 | 历史生成物，生成器已不在树；无代码消费者，文件头已声明 |
| `gen_case_prep_token.yaml` | 生成产物：Token 用例准备 | 同上 |
| `gen_report_appendix.yaml` | 生成产物：报告附录 | 同上 |
| `gen_result_field_data.yaml` | 生成产物：data 字段结果 | 同上 |
| `gen_result_field_status.yaml` | 生成产物：status 字段结果 | 同上 |
| `gen_result_summary.yaml` | 生成产物：汇总结果 | 同上 |

### `test/` — 能力回归层（能力实现测试，unit/ 按能力域分目录）

| 文件 | 能力边界 | 治理规则 |
|------|----------|----------|
| `conftest.py` | pytest 配置 + spec 解析（fail-closed：契约缺失即红）+ 共享 fixture | 降级显式 WARN（Q-35），无静默 pass |
| `unit/client/`（3 个） | BestAuth/BestClient 单测（分页定序/传输层重试纪律/生成式契约回归） | 真构造计数，禁 mock `__init__`（Q-11/12 已修） |
| `unit/download/`（10 个） | BestDownloader + 断点续传 + 下载管理器/进度/hook/精准下载/任务日志 + 取消语义/续传对称单测 | Phase 3 接线 checksum（Q-54） |
| `unit/crossmatch/`（1 个） | BestCrossMatch + Gaia/PS1 匹配 + proximity 批量单测 | 单点失败隔离（Q-17） |
| `unit/multiband_photometry/`（1 个） | BestMultiBandPhotometry 单测 | 未识别列显式失败（Q-29） |
| `unit/pipeline/`（3 个） | BestSkillClient/QualityGate/AstroBestPipeline 单测 | 无指标 fail-closed（Q-14） |
| `unit/protocol/`（2 个） | 协议层回归（表单键集/CSV/计数/sqlid/软 404/名称解算/重试策略） | 公开符号须有生产引用（Q-09） |
| `unit/serialization/`（2 个） | 输出序列化回归：VOTable 列类型推断/标识符列保持字符串/未知格式显式抛错/TSV 分隔符判别 + 星等列判据（误差列不得被当星等、真实列名 psf/pstotal 须被认出） | 输出格式 SSOT（src/serialization）防腐烂 |
| `unit/contracts/`（4 个） | 契约/字段/门禁/委派生成式测试 | spec 驱动 |
| `unit/scripts/`（4 个） | cone_search/validate_adql_query 入口 + crossmatch/光变导出管线 + io 空导出 + OAuth 落盘保护测试（0600 + Windows DPAPI） | 入参校验接线（Q-51） |
| `unit/meta/`（12 个） | 冒烟/台账/修复回归（haversine/消毒/限速）/星表登记门禁/wiring 图/覆盖矩阵/图表 SSOT/环境锁/模块路径/评审器维度/门禁盲点/RAG 领域增强 | 台账偏差须白名单记录 |
| `unit/models/`（4 个） | 行模型默认值/星等映射/测光字段/calibstars_id 与哨兵值解析回归 | from_row 数据语义 |
| `unit/tap/`（4 个） | TAP 层回归：ADQL 子集/执行器/序列化/网关路由（VOSI、sync/async、配额、Bearer、属主、Range） | 还原自 pybest 打包产物 (git 6f00efeb^ 可取回) 的测试面并扩写 |
| `unit/ai_tools/`（3 个） | 工具面信封/cost/错误码 + YZ 边界校验回归（YZ-03/04/14/15/16/18/44）+ agent 面 fail-open | 离线运行（禁打真实站点） |
| `unit/auth/`（3 个） | NADC OAuth + provenance + Django session 导出单测 | 零凭据字面量 |
| `integration/`（7 个 chain 文件） | 分链集成回归：test_crossmatch_chain/test_data_semantics_chain/test_multiband_photometry_chain/test_name_resolution_chain/test_query_chain/test_server_count_chain/test_soft404_chain（原 test_integration.py 按 file-size-budget §3.7 拆分） | 与 Q-01 同批改写 |
| `integration/test_download_feature_integration.py` | 下载栈与 pipeline/query 融合回归 | 新能力不破坏旧能力 |
| `integration/test_pipeline.py` | AstroBestPipeline 集成 | 孤岛互通后生效 |
| `integration/test_release_regressions.py` | 发布回归（CLI/计数/禁版本号守卫） | 禁版本号守卫测试 |
| `live/test_live_best_api.py` | 真实网络冒烟（BEST_LIVE=1） | 受控预算 |
| `live/test_live_best.py` / `test_live_download.py` | live 门控集成（PYBEST_RUN_LIVE=1） | Phase 2 已归位 |
| `unit/audit_round/`（3 个） | 深度审计轮回归：波段权威映射/取消传播/checkpoint 指纹与逃逸/公式注入/确定性排序/typed error_code/CSV 线规/旁路信封/审计可读出口 | 每个修复配“改坏就红”的定向断言 |
| `test/examples/test_examples_run_offline.py` | examples/ 两个示例的离线执行防腐烂（`Session.request` 全量桩 + `HTTPAdapter.send` 真网卫兵 + docstring 预期输出断言） | 示例腐烂即红；零真实网络请求 |

### `weights/` — 权重声明

| 文件 | 能力边界 | 治理规则 |
|------|----------|----------|
| `README.md` | 无二进制权重声明（纯规则/协议 skill） | 保持声明式 |

### local-only / gitignored 目录（树清单只登记存在性）

| 目录 | 能力边界 | 治理规则 |
|------|----------|----------|
| `docs/` | 历史计划/审计/图表（ISSUES、CODE-QUALITY-FIX-LIST、architecture 计划、diagrams、file-size-budget 规模预算） | local-only；**唯一例外 `docs/diagrams/` 的 `.drawio` 源与 7 个生成/审计脚本受跟踪**（渲染产物 PNG/SVG/PDF 不跟踪）；零运行时引用 |
| `temp/` | 唯一临时文件区（探针/草稿/中间产物，含 .qdeep 留档） | gitignored；可随时清理 |
| `best_data/` | 运行时数据落盘（下载产物） | gitignored；AI 只读写 |
| `.checkpoints/` | 断点续传运行时状态 | gitignored |
| `.progress/` | 下载任务进度文件（`astro_best_cli download status/progress` 的跨进程读取面） | gitignored |
| `.logs/` | 任务事件日志（`astro_best_cli log problems/tail` 的事实源） | gitignored |

---

> [已剥离] 仓库级文件树清单整段移除 —— 它是仓库导航件，不是 skill 的工具文档，且内含评测目录与题号指针。
