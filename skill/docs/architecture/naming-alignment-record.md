# 命名不符实锤清单与回改记录 (P0/P1 结构整改)

> 立项依据: 2026-09-28 苏格拉底对齐第 6 轮问答 (Q27/Q28/Q29/Q30 用户裁决:
> A+B 全量整改、pybest 本轮合并删除、硬切换 + 旧名短路 Shim)。
> 本文件是整改台账 — 每条记录「原名 → 新名 → 更名理由 → 波及面 → 兼容期安排」。
> 历史叙事 (审计记录/还原注记/commit 台账) 中的旧名**保持原貌**: 它们描述
> 过去发生的事, 改写即伪造历史。

## 一、模块更名 (P0, 各带 deprecated shim, 登记二期删除)

| # | 旧路径 | 新路径 | 名不符实证据 | 兼容期 |
|---|--------|--------|--------------|--------|
| ① | `src/lightcurve.py` (类 `BestLightCurve`) | `src/multiband_photometry.py` (类 `BestMultiBandPhotometry`) | docstring 自认 "BEST 提供单历元星表数据 (而非时间序列)" — 名字却叫 lightcurve; E1 NL2T-22/E3 语义轴 A 的头号 S1 陷阱; `n_points` 旧 docstring 宣称"观测历元数" (实为源个数) | `src/lightcurve.py` 3 行 shim 转发 + 旧类名别名 |
| ② | `src/query.py` | `src/query_builder.py` | 类 docstring 自认 "只构造约束描述, 不直接发请求" — 与真发请求的 `src/client.py` 混淆; 类名 `BestQuery` 保留 (契约层 input schema 身份, `contracts/fields/*.contract.yaml` 与 12 份 cases 夹具的 `BestQuery:` 键依赖) | `src/query.py` shim 转发 |
| ③ | `src/core/processor.py` | `src/core/source_postprocess.py` | "processor" 空泛; 实际职责是源记录领域级后处理 (球面去重/亮度筛选/波段统计) | shim 转发 |
| ④ | `src/scripts/io.py` | `src/scripts/guards.py` | "io" 空泛; 实际是入参校验 + 输出格式化 + 路径锚定 + URL 白名单四族守卫 (全包单点) | shim 转发 9 符号 |
| ⑤ | `evals/case_runner.py` | `evals/case_executor.py` | 与 `eval_runner.py` 近义混淆 (一个判单条用例过不过, 一个汇总加权评分) | shim (兄弟裸导入转发) |
| ⑥a | `ops/skill_cli.py` | `ops/astro_best_cli.py` | docstring 自称 "cli.py" 的历史错名; "skill_cli" 通用名未说明归属 | runpy 转发 shim (`python ops/skill_cli.py doctor` 实测可用) |
| ⑥b | `ops/cloud_modelscope/run.py` | `ops/cloud_modelscope/dispatch.py` | docstring 自称 "run.py"; "run" 未说明跑什么 (实际是云端算力作业规格合成与分发调度) | runpy 转发 shim |
| ⑦ | `docs/architecture/implementation-plan-v2.md` | `docs/architecture/implementation-plan-phase0-8.md` | 文件名含 v2 版本号, 违反禁版本号铁律精神; 新名以内容范围命名 (计划自身声明 "Phase 0→8 推进") | git mv 100% 相似度 (内容零改动) |

连带符号更名 (① 的家族): `src/scripts/best_lightcurve_export.py` →
`best_multiband_export.py`; `export_lightcurve` → `export_multiband_photometry`;
`batch_export_lightcurves` → `batch_export_multiband_photometry`;
`QualityGate.validate_lightcurve` → `validate_multiband_photometry`;
`BestLightCurvePoint` → `BestMultiBandPhotometryPoint`;
evals 探针/场景 id `lightcurve` → `multiband_photometry`;
落盘文件名前缀 `lc_` → `mbp_`; 默认输出目录 `lightcurves` → `multiband_photometry`;
manifest sinks 轴 `lightcurve_csv` → `multiband_photometry_csv`;
pipeline outputs 类型 `best_lightcurve` → `multiband_photometry` (两处均无外部消费方, grep 实证)。

## 二、双副本合并删除 (P1)

| 项 | 内容 |
|---|---|
| 删除 | `src/pybest.py` (801 行单类门面 `Best`, pylamost 范式) — 与 `src/client.py` 是 docstring 自认的双副本 |
| 入口 | `Best` 从 `src.__all__` 移除 (14→13 项); `from src import Best` 全部失效 |
| 能力路由 | `BestClient._request` (节流+超时+raise_for_status+软错误四职责, 流式下载注入缝); `BestClient.download_file` (薄壳委托 `best_export`); `BestClient.query` (承接 TAP 后端裸行消费; dict constraints → ColumnConstraint; 软 404 抛 Soft404Error; 失败不降级空结果) |
| 死副本清除 | `best_export.save_result` / `best_export.fetch_pages` — 唯一调用方是 pybest, 与 `downloader._save_result` / `client._fetch_sqlid_data` 重复, 随双副本一并删除 |
| 兼容层退场 | `~/pybest.ini` 令牌自动探测 (上游 pylamost 惯例, 从来不是 BEST 站点要求); `_normalize_row` / `_fetch(normalize=)` 开关 (归一化职责由 `BestSource.from_row` 领域模型路径承担) |
| 测试保全 | 传输层纪律 4 例迁入 `test/unit/client/test_client_transport_discipline.py`; 分页定序 1 例迁入 `test_client_pagination_sort.py`; download_file 5 例折叠进 `test_download_file_resume.py` (改 `request=` 注入); 修复原 `test_failed_download_keeps_part_for_resume` 名不副实 (桩每次回 206, 意图路径从未被执行); 集成链/live/ examples 改道 BestClient; TAP 执行器契约改裸行投影 (去掉 normalize 开关) |

## 三、文档锚点回改清单 (随各 Phase 执行)

- P0: SKILL.md / README.md (文件表+导出清单+树清单) / references/ALGORITHM-SPEC.md /
  contracts/io-contract.md / references/skills-spec.local.yaml / templates×2 /
  static/fragments/data_source/best_catalogs.md / evals/cases/case_015 derived_from /
  docs/architecture/coverage-matrix.md / file-size-budget.md / governance-debt-plan.md /
  layer-architecture-diagrams-plan.md / ISSUES-2026-09-28-source-audit.md /
  docs/eval-E1/E2/E3/E4 锚点 / docs/diagrams (layout_data + 重生成) / manifest.yaml /
  pipeline.yaml / references/download-playbook.md
- P1: architecture.md / README.md (src 表) / static/core/workflow.md /
  rag/knowledge/best_practices.yaml + known_issues.yaml / references/
  (pybest-api-reference.md → client-api-reference.md, data-formats.md,
  download-playbook.md, site-endpoints-and-interactions.md) /
  docs/diagrams (node_a2/a3/b1 重写 + 重生成) / evals/cases/case_020 derived_from
- 编号回改 (P2): eval-E1 §0 / eval-E2 §1.2+§2 / eval-E3 §0 / eval-E4 §0 —
  四处旧预留指代改为 E6 附录 B 终版台账 (漂移→E7, TAP→E8), 只改措辞不动计划内容。

## 四、验证证据

- 全量 `python -m pytest test/ -q`: 基线 842 passed → P0 后 842 passed → P1 后 817 passed
  (差额 = pybest 专有 25 例随文件删除/折叠, 关键纪律用例已迁入, 无覆盖净损失)。
- `python evals/eval_runner.py`: 1.0000 SUCCESS (各 Phase 后复跑)。
- `ruff check src/ test/ evals/ rag/ ops/ examples/`: All checks passed。
- `python ops/verify_tree_integrity.py`: OK (286 条目, 每 Phase `--write` 重生成)。
- 图示漂移门禁 `test/unit/meta/test_diagram_ssot.py`: 8 passed (layout_data 改后重生成)。
- Shim 可达性: `python ops/skill_cli.py doctor` / `python ops/cloud_modelscope/run.py
  --check-only` / `from src.lightcurve import BestLightCurve` 等旧路径实测可用。
