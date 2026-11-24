# I/O Contract — astro-best

- strength: `S2` (SKILL-INDEX; 强度收敛后与 registry/强度矩阵一致 — 见 docs/architecture/file-size-budget.md §8)
- pipeline_stage: `collection` (pipeline-manifest.yaml)
- plan_row_sec2: §2 第 2 行 (Master Plan)
- 定位: **BEST 数据库唯一数据源主理方** (外部数据源驱动, 不委派)

## 主理能力 In-Scope (100% 负责)

- NADC BEST REST API 认证
- 两阶段异步查询
- 流式下载

## 委派下游 Out-of-Scope (严禁越权)

- crossmatch -> `astro-catalog`
- data_clean -> `astro-clean`

## 输入契约 (Input Schema)

| field | type | unit | 依据 |
| :--- | :--- | :--- | :--- |
| sql | string | dimensionless | master-plan |
| token | string | credential | master-plan |
| ra | float | deg | io-contract |
| dec | float | deg | io-contract |
| radius_arcsec | float | arcsec | io-contract |
| source_ids | array | dimensionless | io-contract |

## 输出契约 (Output Schema)

| field | type | unit | 依据 |
| :--- | :--- | :--- | :--- |
| data | object | mixed | master-plan |
| status | string | dimensionless | master-plan |
| fmt | string | dimensionless | io-contract |
| rows | integer | count | io-contract |
| job_id | string | dimensionless | io-contract |
| checksum | string | dimensionless | io-contract |
| progress | object | dimensionless | io-contract |

## 阻断性门禁 (Quality Gate)

| gate | 判定 | 阈值 | 量纲 |
| :--- | :--- | :--- | :--- |
| http_status | == | 200 | count |
| checksum_match | == | true | bool |

## 可执行门禁 (Executable Gates)

与上方阻断性门禁分开声明: 以下是本 skill 可判定的运行时门禁, 权威声明在
`references/skills-spec.local.yaml` 的 `executable_gates` (结构由
`test/unit/meta/test_module_paths.py` 校验)。

| gate | 判定 | 阈值 | 量纲 | 判定说明 |
| :--- | :--- | :--- | :--- | :--- |
| fmt_in_whitelist | in | LOCAL_EXPORT_FORMATS | dimensionless | output.fmt 必须落在 `src/serialization.py` 的 `LOCAL_EXPORT_FORMATS` 白名单内, 未知格式显式报错而非静默回落 JSON |
| rows_nonneg | >= | 0 | count | 返回行数不得为负; 负行数只可能来自截断判定或解析 bug |
| sqlid_resolved | != | "" | dimensionless | 两阶段查询第二阶段必须拿到非空 sqlid (`sqlid != ""`), 空 sqlid 即查询会话从未真正建立 |
| path_within_output_dir | within | output_dir | path | 落盘路径归一化后必须位于 output_dir 内, 拒绝 `../` 穿越与绝对路径逃逸 |

## 核心白盒算子 (grep 自真源码)

下表 `module` 一律写**权威实现位置** (能力真正落地的文件), 不是历史再导出处:

- `cone_search` (src.scripts.best_cone_search)
- `validate_adql_query` (src.scripts.guards)
- `crossmatch_with_gaia` (src.scripts.best_crossmatch_pipeline)
- `BestAuth` (src.auth.session)
- `BestClient` (src.client)
- `BestCrossMatch` (src.crossmatch)
- `BestMultiBandPhotometry` (src.multiband_photometry)
- `BestDownloader` (src.downloader)
- `BestQuery` (src.query_builder)
- `BestQueryResult` (src.models)
- `AstroBestConfig` (src.scripts.config)
- `AstroBestPipeline` (src.core.pipeline)
- `QueryContext` (src.scripts.context)
- `QualityGate` (src.core)
- `BestSkillClient` (src.core)
- `TapGateway` (src.tap.service)
- `TapHTTPServer` (src.tap.service)
- `TapExecutor` (src.tap.executor)
- `TapUWSMixin` (src.tap.uws_service)
- `DownloadManager` (src.download_manager)
- `PreciseDownloadJob` (src.download_precise)
- `ProgressStore` (src.download_progress)
- `DownloadCheckpoint` (src.scripts.checkpoint)
- `TaskLogger` (src.task_log)
- `build_envelope` (src.provenance)
- `TokenStore` (src.auth.nadc_oauth)
- `ensure_access_token` (src.auth.nadc_oauth)
- `ToolBox` (src.ai_tools)
- `column_is_numeric` (src.serialization)
- `is_identifier_column` (src.serialization)
- `normalize_output_format` (src.serialization)
- `votable_document` (src.serialization)
- `write_provenance` (src.download_artifacts)
- `download_file` (src.best_export)

> 薄壳再导出说明: 部分算子因历史拆分保留了旧导入路径 — `src.client` 仍可
> `from src.client import BestAuth` (认证态拆至 `src.auth.session` 后的显式移交),
> `BestDownloader` 的落盘辅助也已拆到 `src.download_artifacts` 与 `src.best_export`。
> 这些再导出路径**仍然可用**, 但权威实现以上表为准; 跨 skill 契约面以
> `references/skills-spec.local.yaml` 的 `algorithms` 为唯一事实源。
> 本表每条 `(符号, module)` 都由 `test/unit/meta/test_module_paths.py` 校验
> 「模块可导入 + 同名符号存在」, 写不存在的路径会直接红灯 (历史缺陷: 本节曾把
> `BestQueryResult` 标成不存在的 `astro_best` 模块)。

信封约定: 所有跨节点传递必须包裹 `_shared/skill-engine/pipeline-contract.md`
定义的 data/decision 双态信封 (`astro-envelope-v1`)。
