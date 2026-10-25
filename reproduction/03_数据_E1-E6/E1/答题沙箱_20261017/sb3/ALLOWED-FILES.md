# 白名单：模型能看到的全部文件

> 白名单制：不在本清单里的东西，沙箱里**物理上不存在**。
> 本次构建：复制 **120** 个文件，行级净化 **67** 行。

## 一、可以看

### `(根目录文件)`

- `README.md`
- `SKILL.md`
- `architecture.md`
- `manifest.yaml`

### `agents`

- `agents/openai.yaml`

### `contracts`

- `contracts/envelope.contract.yaml`
- `contracts/error-codes.contract.yaml`
- `contracts/fields/data.contract.yaml`
- `contracts/fields/sql.contract.yaml`
- `contracts/fields/status.contract.yaml`
- `contracts/fields/token.contract.yaml`
- `contracts/input.contract.yaml`
- `contracts/io-contract.md`
- `contracts/measurements/sort-columns.yaml`
- `contracts/oauth.contract.yaml`
- `contracts/output.contract.yaml`
- `contracts/pipeline-stage.contract.yaml`
- `contracts/provenance.contract.yaml`

### `rag`

- `rag/astro_rag.py`
- `rag/knowledge/best_practices.yaml`
- `rag/knowledge/citations.yaml`
- `rag/knowledge/domain_rules.yaml`
- `rag/knowledge/known_issues.yaml`
- `rag/knowledge/lessons_learned.yaml`

### `references`

- `references/ALGORITHM-SPEC.md`
- `references/auth-and-oauth.md`
- `references/best-database-guide.md`
- `references/client-api-reference.md`
- `references/data-formats.md`
- `references/download-playbook.md`
- `references/fallback-protocols.md`
- `references/llms.txt`
- `references/photometric-systems.md`
- `references/scientific-client-defenses.md`
- `references/site-endpoints-and-interactions.md`
- `references/skills-spec.local.yaml`
- `references/tools.schema.json`

### `src`

- `src/__init__.py`
- `src/__main__.py`
- `src/_paths.py`
- `src/ai_tools.py`
- `src/ai_tools_envelope.py`
- `src/auth/__init__.py`
- `src/auth/nadc_oauth.py`
- `src/auth/session.py`
- `src/best_export.py`
- `src/client.py`
- `src/client_paging.py`
- `src/client_phase1.py`
- `src/client_query.py`
- `src/client_resolve.py`
- `src/core/__init__.py`
- `src/core/pipeline.py`
- `src/core/processor.py`
- `src/core/source_postprocess.py`
- `src/crossmatch.py`
- `src/crossmatch_jobs.py`
- `src/csv_safety.py`
- `src/download_artifacts.py`
- `src/download_hooks.py`
- `src/download_manager.py`
- `src/download_precise.py`
- `src/download_progress.py`
- `src/download_region.py`
- `src/download_sqlid.py`
- `src/downloader.py`
- `src/http_session.py`
- `src/kb/__init__.py`
- `src/knowledge_slots.py`
- `src/lightcurve.py`
- `src/models/__init__.py`
- `src/models/input.py`
- `src/models/output.py`
- `src/multiband_photometry.py`
- `src/protocol.py`
- `src/protocol_catalog_tables.py`
- `src/provenance.py`
- `src/py.typed`
- `src/query.py`
- `src/query_builder.py`
- `src/scripts/__init__.py`
- `src/scripts/best_cone_search.py`
- `src/scripts/best_crossmatch_pipeline.py`
- `src/scripts/best_multiband_export.py`
- `src/scripts/checkpoint.py`
- `src/scripts/config.py`
- `src/scripts/context.py`
- `src/scripts/guards.py`
- `src/scripts/io.py`
- `src/serialization.py`
- `src/tap/__init__.py`
- `src/tap/adql.py`
- `src/tap/client.py`
- `src/tap/executor.py`
- `src/tap/formats.py`
- `src/tap/jobs.py`
- `src/tap/response.py`
- `src/tap/service.py`
- `src/tap/uws_service.py`
- `src/task_log.py`

### `static`

- `static/core/output-format.md`
- `static/core/stance.md`
- `static/core/workflow.md`
- `static/fragments/algo_mode/best_auth_mode.yaml`
- `static/fragments/algo_mode/best_two_phase.yaml`
- `static/fragments/algo_mode/two_stage_async_mode.yaml`
- `static/fragments/data_source/best_catalogs.md`
- `static/fragments/data_source/nadc_endpoints.md`
- `static/fragments/target_type/best_ttype.md`
- `static/fragments/target_type/photometry_region.md`
- `static/fragments/target_type/standard_star.md`

### `templates`

- `templates/best-config.yaml`
- `templates/gen_case_prep_sql.yaml`
- `templates/gen_case_prep_token.yaml`
- `templates/gen_config_template.yaml`
- `templates/gen_report_appendix.yaml`
- `templates/gen_result_field_data.yaml`
- `templates/gen_result_field_status.yaml`
- `templates/gen_result_summary.yaml`
- `templates/report_template.yaml`

### `题卷/`（工具面与 system prompt）

- `题卷/TOOLFACE.md` —— 7 个原子工具的工具面
- `题卷/system_prompt.txt` —— 本次 system prompt

> `题卷/per_task/`（28 条题面）与 `题卷/context/`（4 条续接上下文）**已对模型关闭**：
> 一次读全 28 题就是串题。题面从下一节的题包里取。

### `_exec/题包/`（自包含题包 · 按题投喂）

- `_exec/题包/<题号>.md` —— system prompt + 工具面 + 上下文 + 题面，四合一

> **一次只取一份，且目录本身对模型拒绝读取。** 题包由执行会话逐题取出后
> 以文本形式交给模型 —— 模型拿到的是一份内容，不是一条路径。
> `_exec/` 的其余部分（28 题一册的索引件）一律不给 —— 一次看全就是串题。

### `answers/`（唯一可写）

- `answers/NL2T-<题号>.md` —— 你的作答
- `answers/_答题模板.md` —— 两段式模板
- `answers/RUN-INFO.md` —— 批次台账

## 二、看不见（物理不存在）

| 类别 | 说明 |
|------|------|
| 标注 | 期望工具序列 / 错法清单 / 澄清探测词 / 拒绝理由码 |
| 金标准轨迹 | 按标注合成的满分轨迹 |
| 历史跑批 | 上一批模型的真实回答与判定 |
| 判分逻辑 | 判据、权重、通过线、红线 |
| 仓库其他目录 | 评测目录 / 文档 / 示例 / 运维 / 测试 |

## 三、净化口径（两级）

1. **区块级**：仓库级文件树清单整段剥离（它是导航件，不是工具文档）；
2. **行级**：其余命中行整行替换为占位符。被剥离的三类：
   - 题号（答案定位器）
   - 评测目录指针
   - 标注字段名

> 占位符按文件后缀选取（`.yaml`/`.py` 用 `#`，`.md` 用 `>`），
> 以保证结构化文件净化后**仍能解析** —— 这条已纳入构建期断言。
