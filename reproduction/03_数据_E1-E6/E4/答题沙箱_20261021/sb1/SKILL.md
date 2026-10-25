---
name: astro-best
description: |
  BEST 数据库数据源主理 skill —— 访问 nadc.china-vo.org/data/best 真实 REST API。
role: data-source
strength: S2
standalone: true
pipeline_stage: collection
in_scope:
  - NADC BEST REST 两阶段异步查询 (POST 表单 → sqlid → 分页 GET)
  - 12 张可查星表的锥形检索 / 批量交叉匹配 / 标准星 / 多波段测光
  - 流式下载 + 校验和 + 断点续传 (后台下载栈)
  - IVOA TAP 1.1 适配面 (src/tap/, stdlib 零依赖传输)
  - NADC OAuth2.0 身份层 (公开数据面免登录, 仅 /jobs 需要)
out_scope:
  - 通用星表检索/交叉匹配主理 → astro-catalog (球面 KD-Tree 锥搜; BEST 自身数据仍归本 skill)
  - 原始数据清洗 (2D 校准/剔除) → astro-clean
author: LL-LK
license: MIT
gates:
  http_status: {cmp: "==", value: 200, unit: "count"}
  checksum_match: {cmp: "==", value: True, unit: "bool"}
manifest: manifest.yaml
architecture: architecture.md
redirect_policy: table
# 生命周期字段 (registry 侧同值, 以 registry 为 SSOT; 禁版本号铁律下不写 version)
maturity: alpha
---

# astro-best — BEST 数据源主理 Skill

> **定位: BEST 数据库的唯一数据源主理方。** 全 ecosystem 只有本 skill 能访问
> `nadc.china-vo.org/data/best` (Django form 两阶段协议, 站点无 TAP/ADQL/REST-JSON 端点); astro-catalog **不具备 BEST 访问能力**。

## 主理/委派边界契约

**主理 In-Scope (本 skill 100% 负责, 不委派)**: NADC BEST REST 认证 (Django session + CSRF, `src.auth.session`/`src.client`)、两阶段异步查询 (POST 表单→sqlid→分页 GET) 与 12 张可查星表锥形检索/列约束 (`src.client`/`src.protocol`/`src.query_builder`/`src.protocol_catalog_tables`)、BEST 自身数据批量交叉匹配 (`src.crossmatch.BestCrossMatch.crossmatch_batch` 服务端 proximity 一次提交)、流式下载+校验和+断点续传 (`src.downloader` + `src.download_manager` 下载栈)、输出落盘 csv/txt/json/votable/fits (`src.serialization`)、标准星/多波段静态测光容器 (`src.multiband_photometry`/`src.models`)、IVOA TAP 1.1/UWS 适配 (`src.tap`)、NADC OAuth2.0 身份层 (`src.auth.nadc_oauth`)。
**委派 Out-of-Scope (越界即转承接方)**: 通用星表检索与坐标交叉匹配 (SIMBAD/VizieR/Gaia/TNS, 球面 KD-Tree 锥搜) → `astro-catalog`; 原始数据清洗 (2D 校准/剔除) → `astro-clean`; NADC BEST 表单/两阶段异步客户端为外部数据源驱动, 不委派 (BEST 无 TAP/ADQL 端点, 仍归本 skill)。

## 第一步（强制）

**阅读 `README.md`** —— 逐文件能力边界表 + 文件树 SSOT + 治理规则; 未读 README 不得猜测目录用途或改动文件树结构。

## 治理铁律（人与 AI 同等约束）

1. **禁版本号**: 全仓不得出现发布版本号; 变更历史只记 `CHANGELOG.md` (已入版本控制)。
2. **临时文件只进 `temp/`** (gitignored); 其他位置出现临时文件即违规。
3. **结构变更需批准, 内容编辑自由**: 被跟踪文件/目录的新增/删除/移动/重命名、`.gitignore` 增删、README 树清单变更必须经用户明确同意 (批准后 `python ops/verify_tree_integrity.py --write` 重新生成树清单); 既有文件修 bug/补断言/补注释/改文档不需请示。
4. **注释必须中文**: 每个 class/function/method 都要有中文 docstring; import 组要有中文说明; `#` 注释行中文为主 (白名单: shebang / `# noqa` / `# pragma: no cover` / `# legacy-import-guard` / 分隔线)。规范见 `docs/architecture/file-size-budget.md` §4。
5. **400 行预算**: 单个 `.py` 的净代码行 (总行 − 空行 − `#` 注释 − docstring) 非必要不超过 400 行; 超限文件必须在 `docs/architecture/file-size-budget.md` §3 登记必要性论证与拆分预案。度量: `python ops/audit/count_code_lines.py`。

## API 快查 (模块 → 关键符号; 完整逐文件边界见 README `src/` 表)

- **客户端/查询/下载/编排**: `src.client`(BestAuth/BestClient) · `src.query_builder`(BestQuery) · `src.models`(BestQueryResult) · `src.downloader`(BestDownloader) · `src.crossmatch`(BestCrossMatch) · `src.multiband_photometry`(BestMultiBandPhotometry) · `src.core.source_postprocess`(BestProcessor) · `src.core`(QualityGate/BestSkillClient) · `src.core.pipeline`(AstroBestPipeline)
- **脚本入口**: `src.scripts.best_cone_search`(cone_search) · `src.scripts.guards`(validate_adql_query) · `src.scripts.best_crossmatch_pipeline`(crossmatch_with_gaia/batch_crossmatch)
- **适配面/工具栈**: `src.tap`(IVOA TAP 1.1, stdlib 零依赖; 站点本身无 TAP 端点) · `src.ai_tools`(ToolBox 7 原子工具 + 统一信封) · `src.auth.nadc_oauth` · 下载栈 (download_manager/hooks/progress/precise/task_log)

## 质量门禁 (阻断性, 不足即 needs_review)

| 门禁 | 判定 | 阈值 | 单位 |
|------|------|------|------|
| http_status | == | 200 | count |
| checksum_match | == | True | bool |

> **接线状态 (未接线, 见 Q-08)**: 上述两条 blocking 门禁**当前在生产链路没有填充点** —— 唯一求值实现 `src/models/output.py` 的
> `BestResultSet.gates_passed()` 本身正确且 fail-closed (缺省即判否), 但 `BestResultSet` 在 `src/` 内**零生产构造点** (H6-02 与 V1 复扫
> 一致: 13 处构造全在 `test/unit/models/`), 缺的只是构造链。故**不要凭空声称这两条已判过**: 无门可判时按 `agents/openai.yaml` 的
> `honesty_stance` 显式记 `not_computable` 并转 needs_review。

## 场景路由

| 场景 | 入口 |
|------|------|
| 星表查询 / 锥搜 / 交叉匹配 / 标准星 / 多波段测光 | `src/` (模块→类映射见 API 快查与 README `src/` 表) |
| 本地冒烟/自检 | `python ops/astro_best_cli.py doctor` |
| 知识检索 (BM25+词桶+RRF 本地混合) | `python ops/astro_best_cli.py rag "..."` |
| 知识片段定向获取 (A· 编号) | `python ops/astro_best_cli.py slots "..."` |
| 实时记录 → 可选知识库主题 (离线可用) | `python ops/astro_best_cli.py capture "..."` |
| 配置查看/参考条目 | `python ops/astro_best_cli.py config [--json]` / `refs` |
| OAuth 授权 (仅 /jobs 需要) | `python ops/astro_best_cli.py oauth` |
| 下载管理 (后台/进度/取消/续传) | `python ops/astro_best_cli.py download ...` |
| 任务日志 | `python ops/astro_best_cli.py log problems\|tail` |
| 云端规格 | `python ops/cloud_modelscope/dispatch.py --plan` |
| 工程命令 (test/test-cov/lint/lint-fix/install/distclean 等) | `make help` (目标清单见 Makefile) |
| 文件树校验 | `python ops/verify_tree_integrity.py` |

## 组件地图 (十三位一体)

- **加载地图** `manifest.yaml` (data-source 主理声明) · **架构规范** `architecture.md` (五状态机 + 12 横切治理面 + 4 附加结构治理面) · **入口文档** `README.md` (逐文件能力边界 + 文件树 SSOT + 治理规则)
- **领域 RAG** `rag/astro_rag.py` + `rag/knowledge/` 五件套 (best_practices/citations/domain_rules/known_issues/lessons_learned) · **白盒** `references/ALGORITHM-SPEC.md` (G7 五要素, DOI 逐条核验) · **静态规则** `static/core/` 三件 + `static/fragments/`
- **角色** `agents/openai.yaml` (Persona) · **权重** `weights/README.md` (无二进制权重声明) · **工具与云端** `ops/astro_best_cli.py` + `ops/cloud_modelscope/run.py` (env 驱动/零凭据) · **树门禁** `ops/verify_tree_integrity.py` (README 树清单 SSOT 校验) · **实现与测试** `src/` + `test/`
- **MCP 通道 (未接线)**: `ops/best_mcp_server.py` 实现确在仓内且离线自检 13/13 通过, 但登记 `mcp_service: null`、母仓 `.mcp.json` 未登记、本仓 `entry_points` 也不列它 —— 宿主走 `direct` 路径, **不要当可用 MCP 服务去连**。

## 完成自检

- [ ] BEST 数据查询路由到本 skill, 未误转到 astro-catalog (后者无 BEST 端点)
- [ ] **歧义未澄清即执行 = 交付不合格** (R1 2026-10-22): 缺关键参数 (半径单位 / 目标星表该取哪张 / 批量匹配批次策略) 时给 `needs_clarification` 或显式声明所取默认值, 不得静默取默认值
- [ ] 旧调用路径全部保留, `python -m pytest test -q` 0 failed
- [ ] SKILL.md ≤100 行 (G6), 长知识下沉 references/ 与 rag/
- [ ] 注释全中文 (零违规, `python ops/audit/comment_audit.py`) + 超 400 净行已在 `docs/architecture/file-size-budget.md` §3 登记
- [ ] 凭据只在 env, 路径锚定数据根 (`resolve_within`) 无 ../ 逃逸; 临时文件只在 `temp/`; 无版本号字段; 文件树与 README 清单一致 (verify 绿)
