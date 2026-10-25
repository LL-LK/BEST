# astro-best 能力-证据覆盖矩阵 (Coverage Matrix SSOT)

> 状态: **Phase 3 首版**。本文档是「evals/test 无全覆盖」这一问题的
> 可判定形态: 一行 = 一条关键路径能力, 五列证据锚点全部指向真实文件与符号。
> 由 `test/unit/meta/test_coverage_matrix.py` 强制校验 (见文末「门禁规则」)。
>
> **为什么需要它**: 修复 §6/§6.1 的 34 条债务时发现, 大部分缺陷「现有测试
> 测不出」——不是测试写得差, 而是根本没有一行证据指向那条能力。没有矩阵,
> 「覆盖率」就只是一句主观判断。

## 0. 基线数字 (每次变更后须刷新)

| 指标 | 值 | 取得方式 |
|---|---|---|
| pytest | 622 passed / 22 skipped | `python -m pytest -q` |
| src 行覆盖 | 4590 语句 / 772 未覆盖 / **83%** | `python -m pytest -q -o addopts="" --cov=src --cov-report=term-missing` |
| evals 场景 | 24/24 | `python evals/eval_runner.py --mode all` |
| evals 用例 | 25/25 | 同上 |
| 审计器 | 6 个 / 0 failed / 1 INFO finding | 同上 |
| docstring 覆盖 | 100.00% (260/260) | 同上 |
| 综合评分 | 1.0000 SUCCESS | 同上 |

> 行覆盖基线 **83%** 是下限: 后续任何一轮不得低于该值 (Phase 3e 补 P0 缺口后
> 只应上升)。`--mode audit` 单独跑不再产生可信总分 (D1 修复后行为三维记
> NOT_MEASURED 并阻断), 因此本矩阵的 `eval` 列自 D1 修复起才具备证据资格。

## 1. 覆盖行来源 (四类并集, 缺一即矩阵不完整)

1. **spec 算法面** — `references/skills-spec.local.yaml` 的 `algorithms` 列表
   (下游 skill 按此装配 envelope, 是跨 skill 契约面)。
2. **包公开面** — `src/__init__.py` 的 `__all__` (删改任何一项即公开面变更)。
3. **输出格式面** — `src/serialization.py` 的 `LOCAL_EXPORT_FORMATS`
   (服务端 `output.fmt` 白名单 + 本地 `fits` 转换)。
4. **站点交互链** — 对 `nadc.china-vo.org/data/best` 的真实调用链
   (认证 → 两阶段查询 → 分页 → 落盘 → 校验和 → 续传 → 取消 → TAP/UWS →
   名称解析 → 交叉匹配), 权威清单见测试模块内的 `CHAIN_CAPABILITIES`。

## 2. 矩阵

列含义: `anchor` = 权威源码定义处; `unit` / `integration` / `eval` = 三类证据
锚点 (`—` 表示无); `status` = `covered` (有行为证据) / `gap` (无行为证据,
必须带理由) / `by-design` (有意不测, 带理由)。

### 2.1 认证与身份

| capability | anchor | unit | integration | eval | status |
|---|---|---|---|---|---|
| `BestAuth` Django session + CSRF 登录 | `src/auth/session.py` | `test/unit/audit_round/test_restored_surface.py::TestClientLifecycle::test_bestauth_close_and_context_manager` | — | `case_005_scope_01_nadc-best-rest-api-认证` | covered |
| `export_session` 会话导出 (cookies/csrf/headers) | `src/auth/session.py` | `test/unit/auth/test_session_export.py` (6 例: 四键契约/活引用/纯读取/客户端只应用 cookie+CSRF) | — | — | covered |
| `TokenStore` OAuth 令牌 v2 信封存取 (Windows DPAPI / POSIX 0600 静态保护) | `src/auth/nadc_oauth.py` | `test/unit/auth/test_nadc_oauth.py::TestTokenStore::test_save_load_expire_clear` + `test/unit/scripts/test_nadc_oauth_permissions.py` (9 例: 0600 收敛/落盘非明文/v2 信封/round-trip/v1 兼容/DPAPI 不可用回退/损坏信封/Windows 实机 DPAPI) | — | — | covered |
| `ensure_access_token` token 过期恢复单点 (reauth 注入自动续期 / 无通道抛错带恢复命令) | `src/auth/nadc_oauth.py` | `test/unit/auth/test_nadc_oauth.py::TestEnsureAccessToken` (6 例) + `test/unit/auth/test_provenance.py::TestOAuthCli::test_token_subcommand_expired_errors_with_command` | — | — | covered |
| `TokenExpiredError` 过期且无恢复手段的显式失败 (NadcOAuthError 子类) | `src/auth/nadc_oauth.py` | `test/unit/auth/test_nadc_oauth.py::TestEnsureAccessToken::test_expired_token_without_reauth_raises_with_command` | — | — | covered |

### 2.2 两阶段查询主链

| capability | anchor | unit | integration | eval | status |
|---|---|---|---|---|---|
| `BestClient` 两阶段协议 (POST 表单 → sqlid) | `src/client.py` | `test/unit/audit_round/test_restored_surface.py::TestClientLifecycle::test_bestclient_close_and_context_manager` | `test/integration/test_query_chain.py::TestBestClientIntegration::test_cone_search_builds_correct_constraints` | `case_006_scope_02_两阶段异步查询` | covered |
| 表单拼装 (原生 position 字段, 无逆向 filterRules) | `src/protocol.py` | `test/unit/protocol/test_protocol.py` | `test/integration/test_query_chain.py::TestBestClientIntegration::test_phase_two_url_carries_no_reverse_engineered_filterrules` | — | covered |
| 软 404 判定 (HTTP 200 + error 体) | `src/protocol.py` | `test/unit/protocol/test_protocol.py` | `test/integration/test_soft404_chain.py::TestSoft404Detection::test_phase_two_soft_error_is_reported_not_swallowed` | — | covered |
| `getcount` 服务端总数 + 截断判定 | `src/client.py` | — | `test/integration/test_server_count_chain.py::TestServerTotalCount::test_total_count_reports_the_server_total_and_flags_truncated` | — | covered |
| `resolve_name` Sesame 名称解析 (ra=dec=-1000 哨兵) | `src/client.py` | — | `test/integration/test_name_resolution_chain.py::TestNameResolution::test_resolve_name_returns_coordinates` | `case_024_algo_tap_adql` (name_resolve 场景) | covered |
| 分页 GET + `max_rows` 上限 | `src/client.py` | `test/unit/meta/test_fixes.py::TestRetry::test_single_layer_retry_on_503` | `test/integration/test_server_count_chain.py::TestServerTotalCount::test_max_rows_cap_without_server_count_marks_truncated` | — | covered |
| 重试与退避 (503 / 429 Retry-After) | `src/client.py` | `test/unit/client/test_client_transport_discipline.py::test_request_retries_429_and_honours_retry_after` (P1 合并后自 test_single_class.py 迁入) | — | — | covered |
| TSV 解析 (站点 `output.fmt=txt`) | `src/protocol.py::parse_csv_rows` | `test/unit/protocol/test_protocol.py` | — | — | covered |

### 2.3 查询构造与星表注册

| capability | anchor | unit | integration | eval | status |
|---|---|---|---|---|---|
| `cone_search` 锥形检索 (投影/排序/nearest) | `src/scripts/best_cone_search.py` | `test/unit/meta/test_phase4_wiring.py::TestInputValidation::test_cone_search_rejects_bad_coordinates` | `test/integration/test_query_chain.py::TestBestClientIntegration::test_cone_search_builds_correct_constraints` | `cone_search` 场景 | covered |
| `cone_search` 软错误上抛 (不返空列表冒充成功) | `src/scripts/best_cone_search.py` | `test/unit/ai_tools/test_ai_tools.py::TestNetworkTools::test_cone_search_soft_404_maps_to_error_code` | `test/integration/test_soft404_chain.py::TestSoft404Detection::test_best_cone_search_propagates_soft_error_instead_of_empty_list` | — | covered |
| `BestQuery` 列约束 DSL | `src/query_builder.py` | `test/unit/protocol/test_protocol.py` | `test/integration/test_download_feature_integration.py::TestPipelineQueryFusion::test_protocol_form_from_query_constraints` | `case_007_scope_03_流式下载` | covered |
| `ColumnConstraint` 协议约束编码 | `src/models/__init__.py` | `test/unit/protocol/test_protocol.py` | — | — | covered |
| `CatalogType` 12 星表 + 导航组 | `src/models/__init__.py` | `test/unit/protocol/test_protocol.py` | — | `case_014_algo_namemodule` | covered |
| 星表列清单单一事实源 | `src/protocol_catalog_tables.py` | `test/unit/protocol/test_protocol.py` | — | — | covered |
| `magnitude_column` 波段 → 真实星等列映射 | `src/protocol.py` | `test/unit/models/test_magnitude_mapping.py::TestExplicitMagnitudeMaps::test_ps1_corrected_column_does_not_clobber_the_raw_psf_magnitude` | — | — | covered |
| `validate_adql_query` ADQL 语法校验 | `src/scripts/guards.py` | `test/unit/protocol/test_protocol_safety.py` | — | `case_024_algo_tap_adql` | covered |

### 2.4 交叉匹配

| capability | anchor | unit | integration | eval | status |
|---|---|---|---|---|---|
| `BestCrossMatch.crossmatch_batch` 服务端 proximity 一次提交 | `src/crossmatch.py` | `test/unit/crossmatch/test_crossmatch.py::TestProximityBatch::test_crossmatch_batch_uses_one_proximity_submission` | — | `case_018_algo_download_hooks` (proximity_batch 场景) | covered |
| `crossmatch_coords` 脚本入口 | `src/scripts/best_crossmatch_pipeline.py` | — | `test/integration/test_download_feature_integration.py::TestCrossmatchFusion` (类内 2 例) | — | covered |
| `crossmatch_with_gaia` Gaia 定标星匹配 | `src/scripts/best_crossmatch_pipeline.py` | `test/unit/pipeline/test_core.py::TestScripts::test_crossmatch_function_exists` (仅存在性) | — | — | **gap** (`crossmatch_with_gaia`) — 只有 import+callable 断言, 无行为证据; 对应 §6.1 A1 (每次调用新建 BestClient 泄漏 session) |
| 坐标列表长度不一致/空列表的拒绝 | `src/crossmatch.py` | — | `test/integration/test_crossmatch_chain.py::TestBestCrossMatch::test_crossmatch_empty_coords` / `test_crossmatch_mismatched_lists` | — | covered |
| 匹配结果保序返回 | `src/crossmatch.py` | `test/unit/audit_round/test_audit_fixes.py::TestCrossMatchOrdering::test_matches_come_back_in_input_order` | — | — | covered |

### 2.5 下载链路

| capability | anchor | unit | integration | eval | status |
|---|---|---|---|---|---|
| `BestDownloader` 流式下载 + 校验和 | `src/downloader.py` | `test/unit/download/test_downloader.py::TestBestDownloader::test_save_result_csv` 等 14 例 | `test/integration/test_download_feature_integration.py` | `case_019_algo_download_progress` | covered |
| `DownloadManager` 后台作业栈 | `src/download_manager.py` | `test/unit/download/test_download_manager.py` | — | `case_017_algo_download_manager` | covered |
| `PreciseDownloadJob` 按 source_id 精准下载 | `src/download_precise.py` | `test/unit/download/test_download_precise.py` (14 例) | — | `case_022_algo_precise_download` | covered |
| `FileJob` 单文件下载流 | `src/download_manager.py` | `test/unit/download/test_download_manager.py::TestManagerSqlidAndFileJobs::test_file_job_flow_with_progress` | — | `case_020_algo_download_file_resume` | covered |
| `resume_job` 断点原地续传 | `src/download_sqlid.py` | `test/unit/download/test_downloader_resumable.py::TestResumableDownloader::test_resume_job_method` | — | `case_021_algo_download_resume_job` | covered |
| `DownloadCheckpoint` 页级断点 (job_id 穿越拒绝) | `src/scripts/checkpoint.py` | `test/unit/audit_round/test_audit_fixes.py::TestDownloaderSafety::test_checkpoint_rejects_escaping_job_ids` | — | — | covered |
| `ProgressStore` 进度持久化与列举 | `src/download_progress.py` | `test/unit/download/test_download_progress.py` (7 例) | — | — | covered |
| 下载 hook (ask/blocked 中断语义) | `src/download_hooks.py` | `test/unit/download/test_download_hooks.py` | — | `case_018_algo_download_hooks` | covered |
| **取消语义: region/sqlid 每页查取消标志** | `src/download_region.py` / `src/download_sqlid.py` | `test/unit/download/test_download_manager.py` (cancel 相关) | — | — | covered |
| `precise_cancel` 取消语义 (precise 任务可取消) | `src/download_precise.py` | — | — | — | **gap** (`precise_cancel`) — §6.1 B1: 页回调不查取消标志, 终态错记 `done` 而非 `cancelled`; 无测试能发现 |
| `file_cancel` 取消语义 (file 任务取消终态) | `src/best_export.py` | — | — | — | **gap** (`file_cancel`) — §6.1 B2: 取消返 None 被 `_run_file` 一律当失败, 与网络失败不可区分 |
| `TaskLog` JSONL 任务日志 | `src/task_log.py` | `test/unit/download/test_task_log.py` (8 例) | — | `case_023_algo_task_log` | covered |

### 2.6 输出格式 (服务端 fmt + 本地转换)

| capability | anchor | unit | integration | eval | status |
|---|---|---|---|---|---|
| `csv` 落盘 (CRLF + 公式注入防护) | `src/serialization.py` | `test/unit/serialization/test_output_formats.py` + `test/unit/meta/test_fixes.py::TestCSVSafety::test_formula_cell_escaped` | `test/integration/test_release_regressions.py::test_csv_export_preserves_all_raw_catalog_fields` | — | covered |
| `txt` 落盘 (TSV) | `src/serialization.py` | `test/unit/serialization/test_output_formats.py` | — | — | covered |
| `json` 落盘 | `src/serialization.py` | `test/unit/serialization/test_output_formats.py` | — | — | covered |
| `votable` 落盘 (double/char 类型 + unit) | `src/serialization.py` | `test/unit/serialization/test_output_formats.py::TestVotableDocument::test_numeric_columns_get_double_datatype` | `test/integration/test_release_regressions.py::test_votable_export_preserves_raw_fields_and_types` | — | covered |
| `fits` 本地转换 (astropy 可选) | `src/serialization.py` | `test/unit/serialization/test_output_formats.py` (白名单 + fits 非线上格式 + 写出回归) | — | — | covered |
| 未知格式显式报错 (不静默回落 JSON) | `src/serialization.py::normalize_output_format` | `test/unit/serialization/test_output_formats.py::TestFormatWhitelist::test_unknown_formats_raise_instead_of_silent_fallback` | — | — | covered |
| 标识符列保持 char (不丢前导零/精度) | `src/serialization.py::is_identifier_column` | `test/unit/serialization/test_output_formats.py::TestVotableDocument::test_identifier_column_stays_char` | — | — | covered |

### 2.7 领域模型

| capability | anchor | unit | integration | eval | status |
|---|---|---|---|---|---|
| `BestSource.from_row` 前缀剥离与星等归类 | `src/models/__init__.py` | `test/unit/models/test_magnitude_mapping.py` (10 例) | `test/integration/test_data_semantics_chain.py::TestDataSemantics::test_from_row_strips_catalog_prefix_in_production_path` | — | covered |
| `BestSource_six_fields` 六字段 (ra_err/dec_err/parallax/parallax_err/fwhm/quality_flag) 填充 | `src/models/__init__.py` | — | — | — | **gap** (`BestSource_six_fields`) — §6.1 G1: `from_row` 从不填充这六个字段, 真实值只在 `raw_data`; 无测试断言字段非 None |
| `BestQueryResult` 成功/总数/截断/错误信封 | `src/models/__init__.py` | `test/unit/models/test_calibstars_id.py` | — | `case_008_field_data` / `case_009_field_status` | covered |
| `ResolvedName` 名称解析结果 + 外部内容标记 | `src/models/__init__.py` | `test/unit/protocol/test_protocol.py` | — | — | covered |

### 2.8 质量门控与编排

| capability | anchor | unit | integration | eval | status |
|---|---|---|---|---|---|
| `QualityGate` 单源门控 (min_snr/max_fwhm) | `src/core/__init__.py` | `test/unit/pipeline/test_quality_gate.py` (5 例) | `test/integration/test_download_feature_integration.py::TestPipelineQueryFusion::test_quality_gate_unchanged` | — | covered |
| `BestSkillClient` 门控 + 查询审计 | `src/core/__init__.py` | `test/unit/pipeline/test_core.py` | — | — | covered |
| `AstroBestPipeline` 配置全量透传 | `src/core/pipeline.py` | `test/unit/meta/test_phase4_wiring.py::TestConfigPassthrough::test_pipeline_passes_full_config` | — | — | covered |
| `AstroBestConfig` YAML + env 覆盖 | `src/scripts/config.py` | `test/unit/meta/test_phase4_wiring.py::TestTemplateDefaults::test_consumable_keys_inside_defaults` | — | — | covered |
| `QueryContext` token 预算与血缘 | `src/scripts/context.py` | `test/unit/audit_round/test_review_surface.py` | — | — | covered |
| `provenance` 血缘信封 (data_hash 可复核) | `src/provenance.py` | `test/unit/auth/test_provenance.py` | `test/integration/test_download_feature_integration.py::TestProvenanceFusion` | — | covered |
| `write_provenance` provenance sidecar 落盘 (best-effort, 不阻断下载) | `src/download_artifacts.py` | `test/unit/audit_round/test_review_surface.py` (sidecar 存在性 + 失败不阻断) | `test/integration/test_download_feature_integration.py::TestProvenanceFusion::test_provenance_envelope_buildable` | — | covered |
| `BestMultiBandPhotometry` 多波段静态测光 + CSV/JSON 导出 | `src/multiband_photometry.py` | `test/unit/multiband_photometry/test_multiband_photometry.py` (4 例) | `test/integration/test_download_feature_integration.py::TestMultiBandPhotometryFusion::test_multiband_photometry_export_after_manager_download` | — | covered |
| `export_multiband_photometry` 脚本入口 | `src/scripts/best_multiband_export.py` | `test/unit/scripts/test_best_multiband_export.py` (4 例: 白名单拒绝 + csv/json 扩展名与内容一致) | — | — | covered (§6.1 A2 已修: `output_format` 白名单化, 非白名单显式抛 ValueError) |
### 2.9 TAP / UWS 适配面

| capability | anchor | unit | integration | eval | status |
|---|---|---|---|---|---|
| `TapExecutor` ADQL → BEST 查询后端 | `src/tap/executor.py` | `test/unit/tap/test_executor.py` | — | — | covered |
| `TapGateway` VOSI/同步查询/ bearers 认证 | `src/tap/service.py` | `test/unit/tap/test_service.py` (5 类) | — | `tap_service` 场景 | covered |
| `TapUWSMixin` 异步作业生命周期 | `src/tap/uws_service.py` | `test/unit/tap/test_service.py::TestAsyncUws` | — | — | covered |
| `convert_table_rows` 按列类型转 VOTable | `src/tap/formats.py` | `test/unit/tap/test_formats.py` | — | — | covered |
| `TapJobStore` 作业持久化 | `src/tap/jobs.py` | `test/unit/tap/test_adql.py` 同级覆盖 | — | — | covered |
| `TapHTTPServer` stdlib HTTP 服务面 | `src/tap/service.py` | `test/unit/tap/test_service.py::TestBearerAuth` | — | — | covered |

### 2.10 AI 工具面与 CLI

| capability | anchor | unit | integration | eval | status |
|---|---|---|---|---|---|
| `ToolBox` 工具编排 + 客户端类型契约 | `src/ai_tools.py` | `test/unit/ai_tools/test_ai_tools.py::TestToolBoxClientContract` | — | `case_025_algo_agent_tools` | covered |
| 工具面信封与边界 (降级位/引用句柄/页大小与 sqlid 白名单) | `src/ai_tools_envelope.py` | `test/unit/ai_tools/test_yz_boundaries.py` | — | `agent_tools` 场景 | covered |
| ~~MCP server 工具面~~ | — | — | — | — | **removed 2026-10-06**（传输层连同 `mcp_server` 评测场景整体下线；能力由上一行 `ToolBox` 行承接） |
| CLI 子命令 (cone/download/crossmatch/catalogs/info/doctor) | `src/__main__.py` | `test/integration/test_release_regressions.py::test_cli_accepts_catalog_and_format_after_subcommand` | — | — | covered |
| `sanitize_cell` CSV 公式注入防护 | `src/csv_safety.py` | `test/unit/meta/test_fixes.py::TestCSVSafety::test_formula_cell_escaped` | — | — | covered |
| `to_csv` 空记录集导出语义 | `src/scripts/guards.py` | `test/unit/audit_round/test_audit_fixes.py::TestSharedIoHelpers::test_to_csv_uses_the_union_of_record_keys` | — | — | covered |
| `resolve_within` 路径穿越防护 | `src/scripts/guards.py` | `test/unit/audit_round/test_audit_fixes.py` | — | — | covered |
| `validate_coordinate` / `validate_search_radius` | `src/scripts/guards.py` | `test/unit/meta/test_phase4_wiring.py::TestInputValidation::test_cone_search_rejects_bad_coordinates` | — | — | covered |

### 2.11 门禁与元测试 (测测试的门禁)

| capability | anchor | unit | integration | eval | status |
|---|---|---|---|---|---|
| G1 资产守恒 (ASSET-TRUTH-LEDGER) | `ops/` + `test/unit/meta/test_gen_ledger.py` | 同名 | — | — | covered |
| 环境锁 (第三方包白名单) | `test/unit/meta/test_environment_lock.py` | 同名 | — | — | covered |
| 契约文件齐套与 gates 相等 | `test/unit/contracts/test_gen_contracts.py` | 同名 | — | — | covered |
| 400 行净代码预算 | `ops/audit/count_code_lines.py` + `docs/architecture/file-size-budget.md` §3 | 人工门禁 | — | — | by-design — 结构性预算, 由人工度量而非 pytest 强制; 超限文件在 §3 登记论证 |
| 注释规范 (中文/docstring/import 组) | `ops/audit/comment_audit.py` 等 | 人工门禁 | — | — | by-design — 脚本在 temp/ 由人工跑; 每条规则的可判定化是独立工程, 见 budget doc §4 |
| `eval_runner` 评测执行器自身 (五维加权/阻断/反证夹具) | `evals/eval_runner.py` | `test/unit/meta/test_eval_runner_dimensions.py` (10 例: measured 三态/阻断键齐套/run_audit 文档范围/REQUIRED_TOP 启用与反证/单遍读取) | — | — | covered |

### 2.12 站点交互链逐环覆盖 (第四类来源)

对 `nadc.china-vo.org/data/best` 的一次完整调用会依次经过以下环节; 每一环都
必须有独立证据, 否则「端到端能用」会掩盖某一环的退化。键名与测试模块内的
`CHAIN_CAPABILITIES` 逐字对应。

| capability | anchor | unit | integration | eval | status |
|---|---|---|---|---|---|
| `认证` Django session + CSRF 登录与保持 | `src/auth/session.py` | `test/unit/audit_round/test_restored_surface.py::TestClientLifecycle::test_bestauth_close_and_context_manager` | — | `case_005_scope_01_nadc-best-rest-api-认证` | covered |
| `两阶段` POST 表单 → sqlid → GET 取数 | `src/client.py` | `test/unit/audit_round/test_restored_surface.py::TestClientLifecycle::test_bestclient_close_and_context_manager` | `test/integration/test_query_chain.py::TestBestClientIntegration::test_fetch_sqlid_with_csv_data` | `case_006_scope_02_两阶段异步查询` | covered |
| `分页` GET 分页 + max_rows 上限 | `src/client.py` | `test/unit/meta/test_fixes.py::TestRetry::test_single_layer_retry_on_503` | `test/integration/test_query_chain.py::TestBestClientIntegration::test_fetch_sqlid_empty_page` | — | covered |
| `软 404` HTTP 200 + error 体判定 (两阶段各自) | `src/protocol.py` | `test/unit/protocol/test_protocol.py` | `test/integration/test_soft404_chain.py::TestSoft404Detection::test_phase_two_soft_error_fails_instead_of_empty_success` | — | covered |
| `getcount` 服务端总数 + 截断标记 | `src/client.py` | — | `test/integration/test_server_count_chain.py::TestServerTotalCount::test_getcount_failure_falls_back_to_the_local_count` | — | covered |
| `resolve_name` Sesame 代理 (ra=dec=-1000 哨兵) | `src/client.py` | — | `test/integration/test_name_resolution_chain.py::TestNameResolution::test_resolve_name_failure_sentinel_raises` | `name_resolve` 场景 | covered |
| `流式下载` 分块读取 + sha256 校验和 | `src/downloader.py` | `test/unit/download/test_downloader.py::TestBestDownloader::test_save_result_csv` 同级 | — | `case_019_algo_download_progress` | covered |
| `断点` 页级 checkpoint 存取与清理 | `src/scripts/checkpoint.py` | `test/unit/download/test_downloader_resumable.py::TestResumableDownloader::test_checkpoint_atomic_write_and_cleanup` | — | — | covered |
| `取消` 用户取消后作业到达 cancelled 终态 | `src/download_manager.py` | `test/unit/download/test_download_manager.py` | — | — | **gap** (`cancel_terminal_state`) — §6.1 B1/B2: precise 与 file 两条支路的取消终态都不正确 (见 §2.5 两行) |
| `provenance` 血缘 sidecar 落盘 (data_hash 可复核) | `src/provenance.py` | `test/unit/auth/test_provenance.py` | `test/integration/test_download_feature_integration.py::TestProvenanceFusion::test_provenance_envelope_buildable` | — | covered |
| `TAP` TAP 1.1 / UWS 1.0 适配面 | `src/tap/service.py` | `test/unit/tap/test_service.py` | — | `tap_service` / `tap_adql` 场景 | covered |
| `交叉匹配` 服务端 proximity 一次提交 + 保序 | `src/crossmatch.py` | `test/unit/crossmatch/test_crossmatch.py::TestProximityBatch::test_crossmatch_batch_uses_one_proximity_submission` | — | `proximity_batch` 场景 | covered |
| `CSV 注入` 公式注入前缀转义 (不误伤负数) | `src/csv_safety.py` | `test/unit/meta/test_fixes.py::TestCSVSafety::test_negative_numeric_string_preserved` | — | — | covered |
| `路径穿越` 输出路径约束在 output_dir 内 | `src/scripts/guards.py` | `test/unit/audit_round/test_audit_fixes.py` | — | — | covered |

### 2.13 Phase 4 spec 扩片后新增的契约面

Phase 4 把 spec `algorithms` 从 12 条扩到 31 条 (每条 module 指向权威实现位置,
由 `test/unit/meta/test_module_paths.py` 强制校验可导入 + 同名符号存在),
并新增 4 条 `executable_gates` 与 9 个字段。下表登记扩片带来的新覆盖行。

| capability | anchor | unit | integration | eval | status |
|---|---|---|---|---|---|
| `TaskLogger` JSONL 任务日志 (append/tail/tasks/summarize) | `src/task_log.py` | `test/unit/download/test_task_log.py::TestTaskLogger` (8 例) | — | `case_023_algo_task_log` | covered |
| `build_envelope` 双态信封构造 (data_hash/session_id/lineage) | `src/provenance.py` | `test/unit/auth/test_provenance.py::TestEnvelope` (6 例) | `test/integration/test_download_feature_integration.py::TestProvenanceFusion` | — | covered |
| `column_is_numeric` 列类型推断 (数值/文本/稀疏) | `src/serialization.py` | `test/unit/serialization/test_output_formats.py::TestColumnTypeInference` (7 例) | — | — | covered |
| `is_identifier_column` 标识符列判定 (永不当数值列) | `src/serialization.py` | `test/unit/serialization/test_output_formats.py::TestColumnTypeInference::test_identifier_columns_are_never_numeric` | — | — | covered |
| `normalize_output_format` 格式白名单归一 (未知格式显式报错) | `src/serialization.py` | `test/unit/serialization/test_output_formats.py::TestFormatWhitelist` (4 例) | — | — | covered |
| `votable_document` VOTable 序列化 (double/char + unit + 转义) | `src/serialization.py` | `test/unit/serialization/test_output_formats.py::TestVotableDocument` (7 例) | `test/integration/test_release_regressions.py::test_votable_export_preserves_raw_fields_and_types` | — | covered |
| `executable_gates` 四条可执行门禁的结构完备性 | `references/skills-spec.local.yaml` | `test/unit/meta/test_module_paths.py` | — | — | covered |
| spec `module:` 路径真实性 (可导入 + 同名符号) | `references/skills-spec.local.yaml` | `test/unit/meta/test_module_paths.py` | — | — | covered |

## 3. 当前 gap 清单 (9 条, 全部需配套回归)

| # | capability | 归属 | 状态 | 说明 |
|---|---|---|---|---|
| G-cov-1 | `export_session` | 新增 | **已修** | 补 `test/unit/auth/test_session_export.py` 6 例 (四键契约/活引用语义/纯读取无副作用/客户端只应用 cookie+CSRF 头) |
| G-cov-2 | `crossmatch_with_gaia` | §6.1 A1 | 未修 | 仅存在性断言; 每次调用新建 BestClient 泄漏 session 测不出 |
| G-cov-3 | `export_multiband_photometry` | §6.1 A2 | **已修** | 补 `test/unit/scripts/test_best_multiband_export.py` 4 例: `output_format="txt"` 显式抛 ValueError (白名单) + csv/json 扩展名与内容严格一致 |
| G-cov-4 | `precise_cancel` | §6.1 B1 | 未修 | precise 取消语义: 页回调不查取消标志, 终态错记 `done` |
| G-cov-5 | `file_cancel` | §6.1 B2 | 未修 | file 取消语义: 取消返 None 被当失败, 与网络失败不可区分 |
| G-cov-6 | `BestSource_six_fields` | §6.1 G1 | 未修 | `BestSource.from_row` 从不填充六字段, 无测试断言字段非 None |
| G-cov-7 | `write_provenance` | 首版误报 | **已注销** | 首版把 capability 写成 `ProvenanceStore`, 该类在 `src/` 不存在; 真实 API `write_provenance` 已有 sidecar 存在性与失败不阻断两组覆盖 |
| G-cov-8 | `eval_runner` | 新增 | **已修** | 补 `test/unit/meta/test_eval_runner_dimensions.py` 10 例 (measured 语义三态/阻断键齐套/run_audit 文档范围/REQUIRED_TOP 启用与反证/单遍读取) |
| G-cov-9 | `cancel_terminal_state` | §6.1 B1/B2 | 未修 | 站点交互链「取消」环: precise 与 file 两条支路取消后终态不正确 |

> **对账规则** (由 `test_gap_section_has_no_stale_entries` 与
> `test_gaps_are_registered` 双向强制):
> - `未修` 行的 capability 键必须在矩阵对应行的 `status: gap (...)` 里逐字出现;
> - `已修` / `已注销` 的行**不得**再以 gap 形态出现在矩阵里 (修好了没注销 = 清单说谎);
> - 反过来, 矩阵里任何 gap 行都必须在本表有 `未修` 登记 (不许无声缺口)。
>
> 允许「已知未修」长期存在 (34 条债务不可能一轮清完), 不允许「没人知道」。

## 4. 门禁规则 (由 `test/unit/meta/test_coverage_matrix.py` 强制执行)

1. **锚点真实性** — 每行 `anchor` 指向的文件必须存在, 且符号 (类/函数) 必须
   能在该文件中用 AST 找到; `unit`/`integration` 锚点同理 (文件存在 + 节点存在)。
2. **来源完备性** — 矩阵的 capability 集合必须覆盖四类来源的全集:
   spec `algorithms`、`src.__all__`、`LOCAL_EXPORT_FORMATS`、
   `CHAIN_CAPABILITIES`。漏一行即失败, 逼使新增能力时同步登记。
3. **证据真实性** — `status: covered` 的行, 其 `unit`/`integration`/`eval`
   锚点必须真实存在且可收集 (eval 锚点 = `evals/cases/<file>.yaml` 存在)。
4. **不许无声缺口** — `status: gap` 的行必须在本文件 §3 中出现 (带编号);
   未登记的 gap 即失败。`by-design` 必须带 `—` 理由。

> 规则 4 的设计意图: 允许「已知但未修」的缺口长期存在 (34 条债务不可能一轮
> 清完), 但不允许**没人知道**的缺口。登记本身就是把盲区变成可见资产。