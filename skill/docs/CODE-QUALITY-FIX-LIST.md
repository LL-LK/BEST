# astro-best 代码质量审查 · 文件修复清单（v3 · 全量版）

## ⚠ 基线已过期声明（必读）

**本文的基线是分支 `best` @ `301f134b` 的 monorepo 时代快照**：范围写的是
`src/astro_best/` 33 个模块的包布局，而**现行 `src/` 已平铺**、`pybest` 单类已删除、
`evals/` 已从 27 个文件长到 96 个（E1–E6 六套实验）、`ops/audit/` 护栏已入库。
因此本文的**模块可达性（§2.1）、函数接线计数（§2.2）、契约点 resolve（§2.3）
三张表全部需要在当前树重跑**，不能直接引用。

**引用本文时请先做两件事**：
1. 把任何"某模块不可达 / 某符号零调用"的结论当作**待复核线索**而非事实；
2. 用当前工具复测：`python ops/audit/verify_import_graph.py`（导入图 + 分层违规）、
   `python ops/audit/scan_code_smells.py`（重复定义/裸 except）、
   `python ops/audit/verify_crossrefs.py`（文档↔实现交叉引用）。

**已知在本轮之前已被修复、但本文未回正的样本**：§2.1 列的"死模块"
（`core/source_postprocess.py`、`serialization.py`、`csv_safety.py`、
`references/__init__.py`、`_version.py` 等）多数已随平铺重构删除或接线，
需按当前树重判。

---

> 基线：分支 `best` @ `301f134b`　范围：`astro-best/` 全部 177 个受控文件（Python 97，其中 `src/astro_best/` 33 个模块**本轮已 100% 逐文件覆盖**）
> 方法：CodeReview 子代理全仓扫描 → 逐条读码复验 → 离线探针复现 → 字节级突变矩阵 → **接线/契约/死代码三类静态解析**
> 版本沿革：v1 突变表失真已作废（§0.3）；v2 补齐探针与突变矩阵；**v3 新增体系结构全景（§2）与 13 条新缺陷（Q-50 ~ Q-62）**。条目编号跨版本保持稳定，便于追溯。

## 0. 方法与可信度声明

### 0.1 证据等级
| 标记 | 含义 |
|---|---|
| ✅ | 亲自复验：读到位码 **且** 有命令/探针/运行时/突变输出佐证 |
| ◐ | 位码锚点已读到，但未运行验证（多为静态一致性问题） |
| ⚠ | 有怀疑但证据不足，已移入 §12 待验清单，**不作为修复依据** |

### 0.2 取证手段（v3 全集）
1. **离线探针**（8 组）：桩化 `session.get` 喂固定 CSV，驱动生产解析函数，读真实对象与落盘字节。
2. **字节级突变矩阵**（14 个突变位 × pytest/eval 双门禁 ≈ 28 次全量执行，每轮 `git checkout` 还原并复测基线）。
3. **接线分析**：AST 构建模块 import 图，从发布入口做 BFS，并与运行时 `sys.modules` 交叉验证（双口径一致）。
4. **契约解析校验**：把 `manifest.yaml` / `SKILL.md` / `pipeline.yaml` 声明的每个点号路径、每条 `always_load`/`on_demand` 路径、每个依赖 skill 名，逐个 resolve 并判存在性。
5. **函数级死代码审计**：133 个公开函数/方法的生产调用点计数（文本级，含 docstring 与模块内自调用，故为**上界**；关键项已用精确 grep 二次核对）。
6. **跨 skill 克隆检测**：去 docstring/注释/专有名词后哈希比对同名模板文件。

### 0.3 v1 作废内容（保留存档）
v1 的突变脚本用文本模式（`read_text/write_text`）改写源文件，把整文件行尾 CRLF→LF 归一化，导致部分突变未进入被执行代码，**把"被捕获"误报为"存活"**。v2 字节级重测结果：

| v1 结论 | v2/v3 实测 | 变化 |
|---|---|---|
| M3 消毒函数空转 → 0 检出 | 2 条用例捕获 | v1 错 |
| M4 门禁恒通过 → 0 检出 | 2 条用例捕获 | v1 错 → Q-14 已重写 |
| M5 去重失效 → 0 检出 | 3 条用例捕获 | v1 错 |
| M6 RA 归零 → 0 检出 | 3 条用例捕获 | v1 错 |
| M8 "正确修复被 4 条测试阻塞" | 等价突变存活 | 方向反转 → Q-05 |

### 0.4 本轮（v3）净新增
- 新增 **§2 体系结构全景**：32/23/9 模块可达性、59/133 零调用公开函数、契约点 resolve 结果、跨 skill 五件套哈希矩阵。
- 新增缺陷 **Q-50 ~ Q-62**（13 条），其中 4 条属"声明与实现断裂"的新证据链：版本双源字面量、入参零校验、checksum 不在下载链路、编排 tool 名不可解析。
- 新增**健康项清单**（§2.4）——本轮首次同时记录"核验通过"的部分，避免文档被误读为"全是坏的"。
- 修正 `.qdeep.py` 探针的可达性误判（Q-62），防止后续据此误删 6 个在用模块。

---

## 1. 基线实测数字

| 项 | 命令 / 手段 | 结果 |
|---|---|---|
| 测试 | `python -m pytest test/ -q` | **175 passed, 42 skipped**（3.3–4.1s，10+ 轮稳定） |
| 收集 | `pytest test/ --collect-only -q` | **197 collected**（运行期 217，差 20，见 Q-24） |
| 评测 | `python evals/eval_runner.py` | 场景 5/5、用例 16/16，**综合评分恒 1.0000** |
| Lint 门禁 | `make lint` → `ruff check src/ test/` | All checks passed |
| Lint 全仓 | `ruff check .` | **8 errors**，全部落在门禁外 |
| 规则集 | 放开 `BLE001,SIM,ANN` | BLE001 ×15、ANN001 ×11、SIM105 ×11 |
| 宽异常 | `src/` | 19 处 `except Exception`/裸 except |
| `zip()` | 缺 `strict=` | 4 处 |
| 行尾 | 字节扫描 | 32 个 `.py` 含 CR、71 纯 LF；子仓无 `.gitattributes` |
| 版本面 | 全仓 grep | **16 处 / 7 个不同值**，测试只盖 6 处 |
| 模块接线 | AST BFS + `sys.modules` | 32 模块，**23 可达 / 9 不可达**（两口径一致） |
| 函数接线 | 生产调用点统计 | 133 公开函数中 **59 个（44%）生产零调用** |
| 契约点 resolve | `importlib` 逐项解析 | `__all__` 13/13 ✓；**pipeline.yaml 2/3 步 ✗**；SKILL.md 1 项 ✗ |
| 加载地图路径 | `always_load` + `on_demand` | **15/15 全部存在** ✓ |
| 依赖 skill | 双根探测 | `astro-common` **两处都不存在** |

---

## 2. 体系结构全景（v3 新增）

### 2.1 模块可达性：32 模块 / 23 可达 / 9 孤儿

从发布入口（`astro_best` 包门面 + `astro_best.cli`，即 `pyproject` 声明的 `astro-best` / `pybest` 两个 console script）出发：

```
静态 BFS 可达 23 == 运行时 sys.modules 实际加载 23   （两口径一致，结论稳）
```

**9 个不可达模块**（生产零引用，按体量排序）：

| 模块 | 行数 | 生产引用 | 测试引用 | 定性 |
|---|---|---|---|---|
| `services/mcp_client.py` | 330 | 0 | **0** | 最大死重，且零验证（Q-61） |
| `core/__init__.py` | 130 | 1（仅 `core.pipeline`） | 5 | 孤岛自引用（Q-14） |
| `core/source_postprocess.py` | 94 | 0 | 1 | 死类（Q-20） |
| `serialization.py` | 79 | 0 | 1 | 死模块（Q-44 族） |
| `csv_safety.py` | 70 | 0 | 1 | 修好的实现未接线（Q-06） |
| `references/__init__.py` | 27 | 0 | **0** | 且路径解析错误，恒返回空（Q-55） |
| `core/pipeline.py` | 35 | 0 | 2 | 与 `core` 互引成孤岛（Q-15） |
| `_version.py` | 2 | 0 | 1 | 与 `__init__.py` 平行硬编码（Q-50） |
| `services/__init__.py` | 2 | 0 | 2 | 随 mcp_client 悬空 |

合计 **769 行（占包内 5444 行的 14%）处于任何发布入口都到不了的位置**。其中 `core` + `core.pipeline` 互为引用形成孤岛：**SKILL.md 对外承诺的 `QualityGate / BestSkillClient / AstroBestPipeline` 三件套，从包的任何入口都导入不到**（`astro_best.core.AstroBestPipeline` 更是直接 AttributeError，见 Q-56）。

> **方法学警示（Q-62）**：工作区内另一会话留下的 `.qdeep.py` 报"15 个孤儿"，其中 6 个是误判——它的 BFS 没有把"导入 `a.b.c` 会执行父包 `a.b/__init__.py`"计入，于是把 `scripts.{config, context, io, repair, tool, best_multiband_export}` 全判成孤儿。**这 6 个模块实际由 `scripts/__init__.py` 正常拉起，是活的**。若据其结论删除，会砍掉在用代码。

### 2.2 函数级接线：133 公开函数中 59 个生产零调用（44%）

必须先做三分，否则会把"库的公开 API"误判成死代码：

| 类别 | 判读 | 本轮实例 |
|---|---|---|
| **A 公开 API 面**（给用户/agent 调，内部无调用者是设计使然） | 真正要问的是"是否被测、是否真能用" | `Best.*`、`BestQuery.cone/box/build`、`BestMultiBandPhotometry.*`、`BestCrossMatch.submit_upload_job`、`BestDownloader.resume_job` |
| **B 内部能力**（本应被管线调用，却无人调用） | **设计-实现断裂** | 见下表 |
| **C 契约声明的入口**（外部按声明路径调） | 不可解析即断链 | 见 §2.3 |

**B 类零调用的内部能力（已用精确 grep 复核，不含统计噪声）**：

| 能力 | 所在 | 生产调用点 | 测试引用 | 后果 |
|---|---|---|---|---|
| `validate_coordinate` / `validate_search_radius` | `scripts/guards.py` | **0** | **0** | 公开入口 `astro_best.cone_search()` 不做任何入参校验（Q-51） |
| `QueryContext.record` | `scripts/context.py` | **0** | 0 | 审计/provenance 无载体（Q-52） |
| `auto_fix_query` / `diagnose_connection_error` | `scripts/repair.py` | **0** | **0** | 整个"自愈层"空挂，且作用在本 skill 根本不发的 ADQL 上（Q-53） |
| `load_reference` / `list_references` | `references/` | **0** | **0** | 且路径恒错，返回空（Q-55） |
| `verify_checksum` / `compute_sha256` | `downloader.py` | **0**（仅测试与 eval） | 2 | **下载完成从不校验和**（Q-54） |
| `build_query_form` / `parse_sqlid` / `catalog_from_path` | `protocol.py` | **0** | 3 | 权威协议层未接线（Q-01/Q-09） |
| `sanitize_rows` / `sanitize_row` / `sanitize_cell` | `csv_safety.py` | **0**（`sanitize_cell` 的 1 处是模块内自调用） | 1 | 修好的消毒器无人用（Q-06） |
| `degrees_to_hms` / `degrees_to_dms` | `scripts/tool.py` | **0** | **0** | 坐标格式化空挂 |
| `to_dataframe` / `load_json` | `scripts/guards.py` | **0** | **0** | 出口层空挂（`to_csv`/`to_json` 有 1 处引用） |
| `CatalogType.display_name` | `models/` | **0** | **0** | 显示名映射（星表中文名）空挂 |
| `DownloadCheckpoint.list_jobs` | `scripts/checkpoint.py` | **0** | **0** | 断点续传只写不列 |
| `batch_export_multiband_photometry` | `scripts/best_multiband_export.py` | **0** | **0** | 批量光变导出无入口 |
| `BestRAGEngine.best_practices` | `scripts/rag.py` | **0** | **0** | RAG 分类检索空挂 |
| `BestQuery.where` / `mag_range` / `mag_brighter_than` / `class_star_min` | `query.py` | **0** | **0** | 构造器一半没接线（Q-30） |

> 统计口径注意：调用点为文本级匹配，包含 docstring 里的示例（如 `mcp_client.py` 文档串中的 `McpClient(...)`），故原始数字是**上界**；上表逐项经精确 grep 复核。

### 2.3 契约面 resolve 结果

把三份声明文件里的点号路径逐个真解析：

| 声明处 | 声明的路径 | resolve |
|---|---|---|
| `astro_best/__init__.py` `__all__`（13 项） | `Best` `BestClient` `BestAuth` `BestQuery` `BestMultiBandPhotometry` `BestCrossMatch` `BestDownloader` `CatalogType` `ColumnConstraint` `BestSource` `BestQueryResult` `cone_search` `crossmatch_coords` | **13/13 ✓** |
| `SKILL.md` L43-44 | `scripts.guards.validate_adql_query`、`scripts.best_crossmatch_pipeline.{crossmatch_with_gaia, batch_crossmatch}`、`scripts.best_multiband_export.{export_multiband_photometry, batch_export_multiband_photometry}` | **5/5 ✓**（存在，但多数零调用，见 §2.2） |
| `SKILL.md` L45 | `astro_best.core.{QualityGate, BestSkillClient, AstroBestPipeline}` | 2/3；**`AstroBestPipeline` 抛 AttributeError ✗** |
| `pipeline.yaml` L31-35 workflow steps 的 `tool:` | `astro_best.best_cone_search`、`astro_best.quality_gate`、`astro_best.crossmatch` | 1/3；**前两个 AttributeError ✗**（正确应为 `astro_best.scripts.best_cone_search.cone_search` 与 `astro_best.core.QualityGate`） |
| `manifest.yaml` axes `best_query` | 注释声明 `BestQuery(sql, token∈env BEST_API_TOKEN)` | **`BestQuery.__init__(self) -> None`，无 sql/token ✗**（Q-30 升级为 ✅） |
| `manifest.yaml` sinks | `result_json`（BestResultSet 信封）、`lightcurve_ecsv`（ECSV）、`query_audit`（查询审计） | src 内 `data_hash` 0 命中、`ecsv/ECSV` 0 命中、`audit/provenance/envelope` 的 3 处命中**全是注释用词** → **三个 sink 均无实现 ✗**（Q-08/Q-52） |
| `pipeline.yaml` dependencies / sub_skills | `astro-common`、`astro-catalog-query` | `astro-common` 在 `<SKILLS_ROOT>\` 与 `~\.agents\skills\` **两处都不存在 ✗**；`astro-catalog-query` 只在 `~\.agents\skills\`（跨根，未在仓库声明）◐ |
| `SKILL.md`/`manifest.yaml` redirects | `astro-catalog`、`astro-clean` | **目录均存在 ✓** |
| `manifest.yaml` `always_load`(8) + `on_demand`(7) | 15 个文件路径 | **15/15 存在 ✓** |

**读法**：文件级契约（路径、门面导出）是健康的；断裂集中在**符号级**（tool 名、类名、签名）与**语义级**（声明的 sink/门禁没有实现）。这决定了修复方式是"补实现或降级声明"，而非重写加载地图。

### 2.4 健康项（核验通过，勿"顺手改坏"）

| 项 | 结论 |
|---|---|
| `astro_best.__all__` 13 个导出 | 全部可解析，门面承诺诚实 |
| `manifest.yaml` 的 15 条加载路径 | 全部存在 |
| `SKILL.md`/`manifest` 重定向目标 `astro-catalog` / `astro-clean` | 存在 |
| `_version.py` / `__init__.py` / `pyproject.toml` / `SKILL.md` / `manifest.yaml` / `pipeline.yaml` 六处版本 | 当前一致（0.3.2.6） |
| `io.to_csv` / `io.load_json` 编码 | 用 `utf-8-sig`，符合项目 BOM 约定（反而是 `pybest`/`downloader` 不一致，见 Q-60） |
| `services/mcp_client.py` 实现质量 | 超时、`not_configured` 诚实上报、上下文管理、stderr 后台泵——包内写得最好的一份（缺陷只是没接线） |
| `csv_safety.sanitize_cell` | 正确放行纯数字（含负数），只对真公式向量加引号 |
| `processor.deduplicate` 数学 | 球面小角近似 + RA 环绕 + cos(dec) 投影正确，有 3 条真测试守护（M5 被捕获） |
| 请求超时 | `src/` 内未见裸 `requests` 调用缺 timeout，未见 `verify=False` |
| 路径穿越防护 | `pybest._save_result` L493、`downloader` L260-267 有 `resolve()` + `is_relative_to` 校验 |

---

## 3. P0 — 阻断级

| ID | 文件 / 锚点 | 状态 | 问题 | 证据 | 修复动作 | 验证方式 |
|---|---|---|---|---|---|---|
| Q-01 | `client.py` `_build_form` L536-550、`cone_search` L507-519 ↔ `protocol.py` L453 | ✅ | 生产查询表单与协议层键集**完全不相交**，锥形检索结构性失效 | 探针实出：生产 `['max_rows','outputformat','ra.constraint','ra.max','ra.min']` vs 协议 `['output.fmt','pos.deccenter','pos.racenter','pos.radius','pos.type','pos_group','showcol']`，交集 = 空 | 删 `ColumnConstraint` 通路，`cone_search` 改调 `protocol.build_query_form` | 断言表单键集 ⊇ 协议键集且不含 `.constraint`；M1 类突变必须变红 |
| Q-02 | `client.py` `_fetch_sqlid_data` L310-323 | ✅ | CSV 表头未剔除 → `ra=0.0 dec=0.0 source_id=''` 幻影源并计入计数 | 探针：表头+2 真行 → `len(sources)=3 total_count=3`，`[0] ra=0.0 dec=0.0 sid=''`；同输入 `protocol.parse_csv_rows` 正确出 2 行 | 改用 `protocol.parse_csv_rows`（L565 有 `has_header` 动态判定） | 任一 CSV 夹具结果中不存在 `ra==0.0 and source_id==''` |
| Q-03 | `client.py` L324-337 | ✅ | 星等按列序塞进 r/g/i，不看列名 → 波段错位 | 探针：`ps1_gmag,ps1_rmag,ps1_flag` → `{'r':18.5,'g':18.2,'i':1.0}`（g↔r 互换、flag 变 1.0 等星等） | 由表头列名经 `CATALOG_COLUMNS`/`qualify_column` 建映射；无映射只填 `raw_data` | M10 现存活 → 修复后必须被捕获 |
| Q-04 | `client.py` L341-343、`downloader.py` L446 ↔ `models/__init__.py` L87/L108-112 | ✅ | `from_row()` 未传 catalog（解析后才赋值）→ 前缀不剥离；**唯一针对性的测试用了生产不调用的签名** | `test_protocol.py` L90-106 显式传 `catalog="ps1"` 且 3 项断言全绿 | 两处补 `from_row(row_dict, catalog=cat)`；删 L108-112 单字母启发式 | 用生产真实调用形态跑前缀夹具必须变红 |
| Q-05 | `client.py` L281/L310 ↔ `pybest.py` L292 ↔ `protocol.py` L564-566 | ✅ | 同一 `/sqlid` CSV 在包内有**三种互斥表头假设**，唯一自洽实现无生产调用者 | 三方位码对照；M8 盲删首行**存活** → 表头语义零钉住 | 统一到 `protocol.parse_csv_rows`，两客户端共用 | 表头/无表头两类夹具各跑一次，行数与列名都必须正确 |
| Q-06 | `pybest.py` `_save_result` L520-527 ↔ `csv_safety.py` | ✅ | **在线数据损坏**：内联消毒把负数当公式，`dec=-5.0` 落盘成 `'-5.0`；模块 docstring 已自认此缺陷"已修"但零调用 | 探针 6 落盘字节 `X,10.0,'-5.0`；探针 4 对照；M9（关闭内联消毒）**存活** | 全部 emitter 统一 `sanitize_cell`，删 L523 内联副本 | `dec=-5.0` 与 `=cmd` 夹具走所有 emitter；M9 类突变必须变红 |
| Q-07 | `evals/eval_runner.py` L149-161 | ✅ | `http_status` 门禁实测值由**用例文件名**决定，从不执行被测代码；评测层对生产链完全免疫 | 14/14 个突变场景 eval **恒 1.0000**（对照未突变亦 1.0000） | `actual` 必须来自真实执行；`checksum_match` 分支确调生产代码（L166-185）予以保留 | 任一 P0 突变下评分必须下降 |
| Q-08 | `contracts/envelope/provenance/error-codes` + `models/output.py` L82-111 | ✅ | 封套/data_hash/provenance/错误码/`BestResultSet` 只有 YAML 与空模型，代码零实现零构造；门禁默认即"通过" | `src` 内 `data_hash` 0 命中；`audit/provenance/envelope` 的 3 处命中全为注释用词；`BestResultSet(` 零构造 | 实现注入点或降级为 `docs/ROADMAP.md`；默认值一律 fail-closed | 导出文件必带 envelope + data_hash；错误码常量须被实际引用 |

---

## 4. P1 — 高

| ID | 文件 / 锚点 | 状态 | 问题 | 证据 | 修复动作 | 验证方式 |
|---|---|---|---|---|---|---|
| Q-09 | `protocol.py` 6 个公开符号 | ✅ | 协议层正确实现全是死代码，且**有测试守护**——守护的是没有生产调用者的实现 | §2.1/§2.2 计数；M2 改坏 `pos.type` → `test_catalog_registry_live` 2 条红 | 按 Q-01/Q-03/Q-05 接线；未接线前文件头标注"未生效" | import-graph 测试：protocol 公开符号须 ≥1 生产引用 |
| Q-10 | `test/integration/test_integration.py` L57-88（`test_build_form_*` ×4） | ✅ | **测试把错误契约钉成真相**：Q-01 一修就红，门禁阻塞修复 | M1：恰好这 4 条红 | 与 Q-01 同批改写为"表单键集 == 协议键集" | 改后全绿；退回旧实现必须红 |
| Q-11 | `test/unit/test_fixes.py` L143-174 | ✅ | **结构性假防护**：`patch.object(Best,"__init__", lambda self: None)` 使 `HTTPAdapter(Retry(...))` 从未安装，而该测试 docstring 声称防的正是双层重试 | M14：`Retry(total=3→99)` **存活** | 保留单层重试；测试不得 mock `__init__`，改计总请求数 | M14 类突变必须变红 |
| Q-12 | `test/unit/test_fixes.py` L163 | ✅ | 夹具手工 `b._rate_lock = threading.Lock()`，而 `_rate_lock` 在 `src/` **零出现** → 测试替生产补上了缺失的并发保护 | `git grep _rate_lock` 仅 1 处且在 test | 生产实现限速锁（Q-17），删伪造注入 | 删伪造后该测试应红，直到生产有锁 |
| Q-13 | 版本面 16 处 / 7 个值 | ✅ | `test_release_regressions.py` L142-154 只比对 6 处；已安装发行版元数据 `0.3.2.8` 与源码 `0.3.2.6` 并存（版本回退未被发现） | `pip show astro-best` → 0.3.2.8（Editable 指向本仓）；`importlib.metadata.version` → 0.3.2.8；六处断言仍全绿 | `_version.py` 为唯一源，pyproject dynamic，其余生成器写入 | 16/16 一致；改 `_version.py` 后未同步处必须红 |
| Q-14 | `core/__init__.py` `validate_source` L33-65 | ✅ | 门禁本身有 2 条用例守护（修正 v1）；真缺陷是**指标缺失即 fail-open**，而 Q-04 使 snr/fwhm/class_star 恒 None | 探针 3：幻影源 `passed=True checks=[]`；真实源仅 `has_magnitude` | 无指标 → fail-closed 或 `unknown`；补真实列映射 | 不手工注入指标把生产解析源喂门禁，不得 `passed=True` |
| Q-15 | `core/pipeline.py` L9-24 / L30-32 | ✅ | 配置装饰化：`AstroBestConfig` 9 字段只取 2 个，其余 7 个（含 base_url/rate_limit/timeout/api_token）静默丢弃；且整个 core 层不可达（§2.1） | 位码 + §2.1 孤岛结论 | pipeline 全量透传，或从契约删除不支持字段并 warning | 设 `BEST_BASE_URL` 走 pipeline，断言实际请求域名变化 |
| Q-16 | `scripts/config.py` L39-44 + `.env.example` | ✅ | 9 个环境变量**只有 1 个真生效**；4 个连字段都不存在；反向 3 个 env_map 键未写进 `.env.example` | 探针 7 逐行输出 | 以 `.env.example` 为 SSOT 双向补齐；加载失败改 warning | 一致性测试：三方集合相等 |
| Q-17 | `pybest.py` `crossmatch` L640-666 | ◐ | 4 线程共享 `_last_request_time` 无锁（Q-12 已证无 `_rate_lock`）；`zip` 无 `strict`；`except Exception: pass` 吞失败——而 manifest 把 `batch_crossmatch` 描述为"单点失败隔离" | 位码 + `zip` 缺 strict 4 处 | 加锁/令牌桶；`strict=True`；失败进 `result.errors` + `logger.exception` | 不等长入参断言 ValueError；QPS 上限断言 |
| Q-18 | `client.py` / `pybest.py` / `scripts/best_cone_search.py` L29-30 | ✅ | `requests.Session` 永不关闭；且**公开函数 `cone_search()` 在 `client is None` 时每次新建 `BestClient()`** → 普通用户路径必泄漏 session；cookie 仅构造时拷贝一次 | §2.2 调用点 + 位码 | 三个客户端加 `close()`/上下文协议；登录后回写 cookie；公共函数默认复用一个模块级或注入 client | `-W error::ResourceWarning` 跑 100 次不告警 |
| Q-19 | `scripts/cli.py` L122 + L149 | ✅ | **成功的** `config` 子命令返回退出码 200 → `make`/CI 判失败（v1 曾把方向写反） | 实测 `EXITCODE=200`（`doctor`=0）；M7 改 0 存活 → 修复无门禁障碍 | 成功 0 / 失败非 0；HTTP 语义只进 payload | `$LASTEXITCODE == 0` |
| Q-20 | `core/source_postprocess.py` 全类 | ✅ | `BestProcessor` 零生产调用者（§2.1），`bright_sources` 依赖的 `best_mag` 无生产者 | 探针 8：生产 `to_dict()` 无 `best_mag` → `bright_sources(...)` 返回 `[]` | 接入或整体删除（连带 5 条测试） | 若删除，删除后全量测试仍绿即证明无人依赖 |
| Q-21 | `src/astro_best/cli.py` L37 / L96-98 | ◐ | 明文口令进命令行；`auth.login()` 返回值未检查即继续 | 位码 | 改 `getpass`/env/文件；失败返回非 0 | 登录失败退出码非 0 |
| Q-22 | `client.py` L516-517；`protocol.py` L284-286 | ✅ | `catalog="std"` 被静默改写为 `scr_lamost` 单表，用户以为是 Standard Stars 全集 | 位码；protocol 注释自述"BEST 无单一 std 表" | 展开为分组列表或抛 `ValueError` | 断言报错或多表合并 |
| Q-23 | `client.py` L360-363 | ✅ | `total_count`/`returned_count` 都取 `len(all_sources)`，非服务端计数 → 幻影行虚增结果 | 探针 2：2 真行 → 3；M13 **存活** | 用 `protocol.parse_count` 真实计数或改名 `parsed_count` | 计数类突变必须被捕获 |
| Q-24 | 测试口径 | ✅ | `--collect-only` 197 vs 运行期 217，差 20 = 20 条模块级 skip；skip 明细中 5 个文件报 `test\_archive\...` 而该目录**磁盘与 git 都不存在** → 陈旧 `__pycache__` 携带迁移前 `co_filename` | 命令输出对照 | 清 `__pycache__` 复测；把 collect 口径写进验收 | 干净 checkout 下两口径应一致 |
| Q-25 | `pybest.py` L483-490 + L560 | ✅ | 未支持 `fmt` 无前置校验：静默套 `.json` 扩展名后不写任何分支 → `os.replace` 抛 `FileNotFoundError` | 探针 5 实际异常 | 入口校验 `fmt in SUPPORTED_OUTPUT_FORMATS` 否则 `ValueError` | 断言 ValueError 而非 FileNotFoundError |
| **Q-50** | `src/astro_best/__init__.py` L9 ↔ `_version.py` L2 | ✅ | **版本双源**：两处是各自独立的字符串字面量（`__init__.py` 并未 `from ._version import __version__`），§2.1 亦证 `_version.py` 生产零引用；回归测试同时比对两者故"一致"是被两处同步手改维持的假象 | 位码 + §2.1 引用计数 0 | `__init__.py` 改为 `from astro_best._version import __version__`，`_version.py` 作唯一源 | 只改 `_version.py`，断言 `astro_best.__version__` 随之变化 |
| **Q-51** | `scripts/guards.py` `validate_coordinate`/`validate_search_radius` ↔ `scripts/best_cone_search.py` L29-31 | ✅ | 入参校验器齐备但**公开入口一个都不调**：负 RA、0/负半径、超 5° 半径全部直传服务端；校验函数连测试都零引用 | §2.2 双 0 | `cone_search()` 入口调用两个校验（radius 校验已有常量上限 18000″） | 非法坐标/半径夹具断言 `ValueError`；MUT 关掉校验必须变红 |
| **Q-54** | `downloader.py` L50-66 ↔ `manifest.yaml` `quality_gates.checksum_match` | ✅ | **声明的 checksum 门禁不在下载链路上**：`verify_checksum` 在生产代码里零调用，只有测试与 eval 调；eval 校验的还是它自己刚写的临时文件 → 下载产物从不验证 | §2.2 + `git grep verify_checksum` 全部命中点枚举 | 下载完成后强制 `verify_checksum`（有期望值时），失败即 `raise`；无期望值显式记 `checksum_match=unknown`（呼应 Q-08 fail-closed） | 篡改下载文件后断言流程报错 |
| **Q-56** | `pipeline.yaml` L31-33、`SKILL.md` L45 | ✅ | 编排与兼容 API 声明的符号**不可解析**：`astro_best.best_cone_search`、`astro_best.quality_gate`、`astro_best.core.AstroBestPipeline` 均 AttributeError（真实为 `astro_best.scripts.best_cone_search.cone_search`、`astro_best.core.QualityGate`、`astro_best.core.pipeline.AstroBestPipeline`）；且没有任何代码读 pipeline.yaml 去校验这些 tool | §2.3 importlib 实测 | 改正声明路径；加一条"pipeline.yaml 的每个 `tool:` 必须可 import"的契约测试 | 遍历 pipeline.yaml/SKILL.md 声明点逐个 resolve，缺失即红 |
| **Q-52** | `scripts/context.py` L29-42 | ✅ | `QueryContext.truncate()` **原地改写** `history[i]["n_results"]` 为按预算摊薄的值，`summary().total_results` 随后报告**被篡改后的计数**而非真实结果数；对声明为 "token budgeting and provenance" 的对象是数据完整性缺陷。且 `record()` 生产零调用（§2.2）→ 载体本身也没人喂 | 位码 + §2.2 | 摊薄只影响返回视图，不改写源记录（返回裁剪后的副本）；把真实计数与展示计数分成两个字段 | 断言 `truncate()` 后 `summary()["total_results"]` 仍等于真实总数 |
| **Q-61** | `services/mcp_client.py`（330 行，零引用零测试） | ◐ | 实现质量最高却整体悬空。细节缺陷：①`_next_id += 1` 与共享 `_lines` 队列**无锁**，并发请求会串号；②`_drain_stderr()` 刚启动泵线程就立刻取 `_stderr_tail` → 诊断信息**几乎恒为空**；③`Popen(env=self.env)` 是替换而非合并，传部分 env 会丢 PATH；④`close()` 只关 stdin，stdout/stderr 句柄未关 | 位码 + §2.1（330 行最大死重） | 先定去留：接入某个入口（`scripts/cli.py` 加 `mcp` 子命令）并补测试，或整体移出包 | 若保留：并发 `tools/list` 压测不得串号；启动失败时 stderr tail 非空；fd 数不随调用增长 |

---

## 5. P2 — 中

| ID | 文件 / 锚点 | 状态 | 问题 | 修复动作 |
|---|---|---|---|---|
| Q-26 | `client.py` L298 与 L537 | ✅ | 同产品内 `output.fmt`（取数 URL）与 `outputformat`（提交表单）两种拼写并存 | 统一到 `output.fmt` |
| Q-27 | `downloader.py` L302-329 / L342-363、L374、L393 | ◐ | 22 行整块复制；HTML 未转义（注入面）；写盘 `utf-8` 而非 `utf-8-sig`；downloader 全部 emitter 无消毒 | 抽 `_write_rows()`；`html.escape`/`xml.sax.saxutils.escape`；接 `csv_safety`；编码统一 |
| Q-28 | `pybest.py` L528-559 | ◐ | VOTable 值未 XML 转义即拼进 `<TD>`；`FIELD datatype` 靠 `col.endswith("mag")` 猜 | 写值前 escape；类型来自列映射 |
| Q-29 | `multiband_photometry.py` `from_client` L112-121 | ◐ | 只识别 `POS_` 前缀列，其余静默返回 0 点光变（"看起来成功"的空结果） | 未识别列 → warning + `success=False` |
| Q-30 | `query.py` `__init__` L31-35 ↔ `contracts/input.contract.yaml`、`manifest.yaml` axes | ✅ | **升级为 ✅**：运行时 `BestQuery.__init__(self) -> None`，manifest 注释声明 `BestQuery(sql, token∈env BEST_API_TOKEN)`；`cone()` 走 box-between（同 Q-01）；`where/mag_range/mag_brighter_than/class_star_min` 四个构造器零调用 | 契约与实现对齐；删 snr/fwhm 约束；`test_gen_contracts` 改断言 `inspect.signature` |
| Q-31 | `templates/*.yaml` L24-26 | ◐ | 顶层键落在 `defaults:` 之外，`from_yaml` 只读 `defaults` → 模板键全丢；模板注释引用的 `astro_best.config`/`astro_best.pipeline` 模块不存在 | 键收进 `defaults:`；路径改 `astro_best.core.pipeline`/`astro_best.scripts.config`；两模板合并 |
| Q-32 | `bridge/register-astro-best.{ps1,sh}` | ◐ | 上级路径多跳两级（应为 `..\_shared`）；登记版本 0.2.0；conda 环境名不一致 | 相对脚本自身一级上跳；同步版本与环境名；共用 Python 入口 |
| Q-33 | `test_gen_algo_*.py`（12）+ spec 加载副本（13） | ✅ | 断言只有 `assert fn is not None` + `assert callable(fn)`；L59-60 导入失败静默 skip；12 文件各内联一份 `get_spec_path/get_spec_data`（与 conftest 重复 13 份），且用 `utf-8` 而非 `utf-8-sig` 读 YAML | 升行为断言；合并参数化；spec 加载收敛到 conftest 并改 `utf-8-sig` |
| Q-34 | 42 个 skip 构成 | ✅ | 20 条（48%）`legacy import unavailable`（引用不存在的 `pybest` 包）＝永久失效资产；13 条 live 网络门控；本仓自身单测 0 skip | 上游参考测试移出主树或补真跑；live 补录制回放；`-rs` 明细入报告 |
| Q-35 | `test/conftest.py` L20-51 | ✅ | conftest **无** live 自动跳过（v1 转述错误）；`test_catalog_registry_live.py` 带 `live` 标记却离线真跑；`get_spec_data()` 读上级 spec 失败时 `except Exception: pass` 静默降级 | 明确 `live` 语义；降级路径加 warning |
| Q-36 | `docs/ISSUES.md` L121/L306/L461/L501 | ✅ | 台账与现状脱节（"25 行全 CRLF" vs 实测 32 文件含 CR；"ruff 191/474" vs 现 8） | 台账脚本化生成，每条带可重跑取证命令 |
| Q-37 | `SKILL.md` L8 vs `manifest.yaml` L8 vs README vs io-contract | ◐ | `standalone: false` vs `true`；"BEST 无 TAP/ADQL" 与 `validate_adql_query`（实测存在，L51）表述冲突；crossmatch 越权禁令与自有算子并存；"三件套"实为 4 项 | 以 `manifest.yaml` 为 SSOT；表述统一为"无标准 TAP，仅保留语法校验"；加文档一致性测试 |
| Q-38 | `client.py` L135、`pybest.py` L143 | ✅ | UA 两套硬编码且都过期（`astro-best/0.3.2`、`pybest/0.3.0`） | 统一 `f"astro-best/{__version__}"`（随 Q-50 走单一源） |
| Q-39 | `rag/`、`scripts/` | ◐ | `parents[3]` 硬编码推仓库根（`references/__init__.py` 已因同类错误失效，见 Q-55）；`rag/knowledge/` 双份副本 | 向上找标志文件或读环境变量；知识单源 + 生成副本 |
| Q-40 | 门禁外 8 条 lint | ✅ | `eval_runner.py` 5 条（含 2 个 unused import）、`examples/example_skill_usage.py` E402+I001、~~`scripts/cloud_modelscope/run.py:39` F841~~ **坐标订正（R2, 2026-10-05）**：原文两处皆错 —— 目录应为 `ops/cloud_modelscope/run.py`（非 `scripts/`），且行号 **39 越界**（该文件仅 14 行）。该文件现为 `[deprecated shim]`，只 `runpy` 转发到同目录 `dispatch.py`、不含实现，原 F841 已随之失效 | `ruff check . --fix` + 手工处理，并入 Q-41 门禁 |
| Q-41 | `Makefile` `lint` / `clean` L51 | ✅ | lint 范围漏 3 个目录（8 错恰在门外）；`clean` 递归删 `data/`、`best_data/`、`logs/`（不可逆删科研数据）；`ruff` 未声明依赖 | `ruff check .` + `extend-exclude`；数据目录另设 `distclean` 带确认；ruff 入 dev 依赖 |
| Q-42 | `pyproject.toml` L19-25 + `environment.yaml` | ✅ | `astropy`/`numpy` 为硬依赖但 `src/` 零 import（`numpy` 全仓 0 命中）；真实第三方仅 `requests`、`yaml`、`pandas`（`pandas` 只被 `scripts/guards.py` L9 用） | 依赖收敛；AST 抽取 import 集与依赖表自动比对 |
| Q-53 | `scripts/repair.py` L57-74（整模块 §2.2 双 0） | ✅ | `auto_fix_query` 对查询串做盲 `str.replace`（`LIMIT0`→`LIMIT 1`、`ORDER_BY`→`ORDER BY`），可破坏合法标识符/字面量；而本 skill 明确**没有 ADQL/TAP 端点**，等于给永不发送的语言写"修复器"；`diagnose_connection_error` 用 `"500" in error` 这类子串判状态码，`"1500ms"` 会误判为服务器错误 | 删除或降级为"仅诊断建议、不改写查询"；状态码改正则 `\bHTTP\s*(\d{3})\b` 提取 |
| Q-55 | `references/__init__.py` L11/L21 | ✅ | **路径差一层**：`Path(__file__).parent.parent.parent / "references"` 解析到 `src\references`（不存在），真实目录在 `parents[3]`；运行时实证 `list_references() == []`、`load_reference('best-database-guide') is None`（真实目录含 4 个文件）→ "白盒知识入口"恒空 | 改 `Path(__file__).parents[3] / "references"` 或向上找标志文件；读文本改 `utf-8-sig`；并接进某个 CLI 子命令 |
| Q-57 | `pipeline.yaml` L10-14 | ✅ | `dependencies: astro-common` 在 `<SKILLS_ROOT>\` 与 `~\.agents\skills\` **两处都不存在**；`sub_skills: astro-catalog-query` 只存在于 `~\.agents\skills\`（跨根引用，仓库内无声明） | 删除或改指向真实存在的 skill；把跨根引用写进 README 的部署前提 |
| Q-58 | `scripts/guards.py` L98-100 | ◐ | `DictWriter(fieldnames=records[0].keys())` 未设 `extrasaction`，异构记录（BEST 分页场景的真实形态）会抛 `ValueError`；`records` 为空时写出 0 字节文件（连表头都没有） | fieldnames 取所有记录键的并集（保序）；空集时明确写表头或抛错，别静默出空文件 |
| Q-59 | `io.py` L96/L103/L132 | ◐ | 函数内 `import io` 遮蔽与本模块同名标识符；`import os` 在两个函数里重复出现 | 顶部统一 import；模块内避免与 stdlib 同名 |
| Q-60 | CSV 落盘编码三处不一致 | ✅ | `io.to_csv=utf-8-sig`（合约定）、`pybest.*=utf-8`、`downloader.*=utf-8` | 统一 `utf-8-sig` 并写成一条跨 emitter 的契约测试 |

---

## 6. P3 — 低

| ID | 文件 | 状态 | 问题 | 修复动作 |
|---|---|---|---|---|
| Q-43 | 32 个 `.py` | ✅ | CRLF/LF 混用，子仓无 `.gitattributes` | `*.py text eol=lf` 一次性归一 |
| Q-44 | `client.py` L374-400 | ✅ | `_parse_csv_text`/`_count_url` 生产零调用，却被 3 条测试覆盖 → 测的是死代码 | 删除，连带其测试；统一走 protocol 解析 |
| Q-45 | `schemas/message.proto` | ◐ | 11 行占位（无 message/字段）却被契约引用 | 补定义或标注 reserved |
| Q-46 | `README.md` L24 | ✅ | 记录基线"88 passed, 91 skipped" vs 实测 175/42 | 数字脚本生成 |
| Q-47 | `src/` 19 处宽异常 | ✅ | BLE001 被规则集屏蔽（15 处） | 收窄异常；补 `BLE001` 到 select |
| Q-48 | `models/__init__.py` L96/L118 | ✅ | `obj.ra = nv or 0.0`、`if not val` 把解析失败/空/合法的 0 三者混同 | 字段改 Optional，显式 `is None` |
| Q-49 | `core/__init__.py` L123/L128 | ✅ | 同一源体内调用 `validate_source` 两次 | 调一次复用 |
| Q-62 | 工作区 `.qdeep.py`（他人探针） | ✅ | 可达性 BFS 缺父包传播，把 6 个在用模块判成孤儿（15 vs 真实 9）；按其结论删代码会砍掉活模块 | 修 `ancestors()` 传播（本清单 §2.1 已给正确实现），或改用运行时 `sys.modules` 口径 |

---

## 7. 突变矩阵（v2 可信版，v3 未变动）

| # | 突变 | pytest | 被捕获用例 | eval | 判定 |
|---|---|---|---|---|---|
| M1 | `_build_form` 字段值改坏 | 4 failed | `test_build_form_basic/_empty/_txt/_votable` | 1.0000 | 被捕获，**但捕获者钉死错误契约**（Q-10） |
| M2 | `protocol` `pos.type="coneX"` | 2 failed | `test_cone_form_uses_native_position_fields_and_showcol` 等 | 1.0000 | 被捕获（守的是死代码，Q-09） |
| M3 | `csv_safety.sanitize_cell` 空转 | 2 failed | `test_formula_cell_escaped`、`test_at_prefixed_non_numeric_escaped` | 1.0000 | 被捕获——只测模块自身，测不到"没人调用" |
| M4 | `validate_source` 恒通过 | 2 failed | `test_core`、`test_quality_gate` 的 low_snr | 1.0000 | 被捕获（v1 记录作废） |
| M5 | `deduplicate` 退化恒等 | 3 failed | 3 条 dedup 用例 | 1.0000 | 被捕获（模块本身零生产调用，Q-20） |
| M6 | `from_row` RA 全归零 | 3 failed | `test_csv_text_parsing`、`test_fetch_sqlid_with_csv_data`、`test_best_source_understands_prefixed_result_columns` | 1.0000 | 被捕获 |
| M7 | `cli.py config` 退出码 200→0 | 175 passed | — | 1.0000 | **存活**（好事：修复无门禁障碍，Q-19） |
| M8 | 盲删每页首行 | 175 passed | — | 1.0000 | **存活** → 表头语义零钉住（Q-05） |
| M9 | 关掉 pybest 内联消毒 | 175 passed | — | 1.0000 | **存活** → 生产 CSV 输出无防护（Q-06） |
| M10 | 波段映射塌陷为单列 | 175 passed | — | 1.0000 | **存活** → Q-03 零守护 |
| M11 | 分页"只取第一页" | 175 passed | — | 1.0000 | **存活** → 分页正确性零守护 |
| M12 | `total_fetched += 0` | 175 passed | — | 1.0000 | **存活** → `max_rows` 语义零守护 |
| M13 | `total_count = 0` | 175 passed | — | 1.0000 | **存活** → 计数零守护（Q-23） |
| M14 | urllib3 `Retry(total=3→99)` | 175 passed | — | 1.0000 | **存活** → 双层重试零守护（Q-11） |

14 个突变位：pytest 捕获 6、存活 8；**eval 在 14/14 全部输出 1.0000**。存活项集中在同一层——`_fetch_sqlid_data` 的数据语义（表头、波段、分页、计数）与生产输出消毒，即"结果对不对"这一层没有任何自动化防线。

---

## 8. 离线探针实录（原始输出）

```text
1) 表单键集
   生产 _build_form : ['max_rows','outputformat','ra.constraint','ra.max','ra.min']
   协议 build_query_form: ['output.fmt','pos.deccenter','pos.racenter','pos.radius','pos.type','pos_group','showcol']
   交集 : 空

2) 表头 + 2 行真数据（ps1_gmag, ps1_rmag, ps1_flag）经生产解析
   len(sources)=3  total_count=3  returned_count=3
     [0] ra=0.0 dec=0.0 sid='' mags={} catalog='ps1'
     [1] ra=187.7059 dec=12.3692 sid='' mags={'r': 18.5, 'g': 18.2, 'i': 1.0} catalog='ps1'
     [2] ra=30.0 dec=40.0 sid='' mags={'r': 19.1, 'g': 18.9} catalog='ps1'
2b) 同一 CSV 走 protocol.parse_csv_rows(catalog='ps1') → 行数 2，列名保留 ps1_gmag/ps1_rmag/ps1_flag

3) QualityGate 判定生产形态源体
   幻影源: passed=True checks=[]                       snr/fwhm/class_star = None
   真实源: passed=True checks=[{'has_magnitude': True}]  snr/fwhm/class_star = None

4) 消毒对照   '-5.0' → pybest "'-5.0'" / csv_safety '-5.0'   '+1.25e-3' → "'+1.25e-3'" / '+1.25e-3'
5) _save_result(fmt="fits") -> FileNotFoundError [WinError 2] '...r1arcsec.json.tmp' -> '...json'
6) fmt=csv 实际落盘: source_id,ra,dec | X,10.0,'-5.0
7) BEST_MIN_SNR=99→cfg.min_snr=5.0 / MAX_FWHM=99→5.0 / TIMEOUT=99→120 / DOWNLOAD_DIR→best_data
   LOG_LEVEL、QUALITY_FILTER、API_USER、API_PASS → <无此字段>；.env.example 9 个变量仅 1 个生效
8) to_dict() 键无 best_mag；bright_sources([生产 dict],16.0) -> []

9) 接线（AST BFS + sys.modules 双口径一致）
   32 模块 | 23 可达 | 9 不可达（mcp_client 330 / core 130 / processor 94 / serialization 79
            / csv_safety 70 / pipeline 35 / references 27 / _version 2 / services 2）
10) 函数级：133 公开函数中 59 个生产零调用；validate_coordinate / validate_search_radius /
   QueryContext.record / auto_fix_query / diagnose_connection_error / load_reference /
   list_references / verify_checksum / degrees_to_hms / to_dataframe / load_json
   → 生产 0 且测试 0
11) 契约 resolve：__all__ 13/13 ✓ | always_load+on_demand 15/15 ✓
   ✗ astro_best.best_cone_search | ✗ astro_best.quality_gate | ✗ astro_best.core.AstroBestPipeline
   BestQuery.__init__(self) -> None   （manifest 声明 sql/token）
   src 内 ecsv/ECSV 0 命中、data_hash 0 命中、audit/provenance/envelope 命中全为注释用词
12) references 路径：解析到 src\references（存在? False）；真实 references\ 存在、4 个文件；
   运行时 list_references() == [] 、load_reference(...) is None
13) 版本：pip show / importlib.metadata = 0.3.2.8  vs  源码六处 = 0.3.2.6
```

---

## 9. 假覆盖图鉴（7 类结构性教训）

1. **钉死错误契约**（Q-10）：断言服务端不认的字段名，修复反而变红。
2. **测的是无人调用的正确实现**（Q-09 / M2）：绿灯与线上行为无关。
3. **夹具替生产补实现**（Q-12）：测试手工塞 `_rate_lock`，生产从没这属性。
4. **`patch` 掉构造器 → 结构上测不到**（Q-11 / M14）：docstring 声称防的正是它测不到的东西。
5. **测了无辜的那一个**（Q-06）：负赤纬回归用例打在"根本没有消毒逻辑"的 downloader 上，出事的 pybest 分支无人测。
6. **用生产从不调用的签名做断言**（Q-04）：前缀剥离测试显式传 `catalog=`，生产不传。
7. **自证式评测**（Q-07 / Q-54）：eval 校验 checksum 时读的是它自己刚写的临时文件；门禁值取自用例文件名。

外加两条口径教训：
8. **skip ≠ "暂时没跑"**（Q-34）：48% 的 skip 指向不存在的包名，属永久失效资产。
9. **命名与执行错位**（Q-35）：带 `live` 标记的测试其实离线在跑，且无机制跳过它。

---

## 10. 重复资产：删除 / 合并

| 资产 | 处置 | 依据 |
|---|---|---|
| `pybest.py`(668) 与 `client.py`(559) | 合并为单一客户端，`_save_result`/`crossmatch` 入 `services/` | 两套表单构造同为错实现双副本；UA/重试/Session 各一套 |
| 五件套模板层（跨 5 skill 各 1 份） | 抽公共库或代码生成 | `config/context/io/rag/repair/tool/checkpoint` 在 5 个 skill 下**哈希全不相同**（行数 43↔475），即同一模板已各自漂移，一个 bug 要修 5 遍 |
| `downloader.py` L302-329 / L342-363 | 删后者，抽 `_write_rows()` | 22 行逐行相同 |
| `csv_safety.py` vs `pybest.py` L523 | **保留模块、删内联副本并接线** | 模块才是修好的那份（Q-06） |
| `models/output.py` 4 个 Output 模型 | 接入真实构造链，否则整体删除 | 零构造、默认即通过（Q-08） |
| `models/__init__.py` L197 `BestMultiBandPhotometryPoint = BestSource` | 删别名 | 类型语义污染 |
| `contracts/` 无实现的 envelope/data_hash/provenance/error-codes | 降级 `docs/ROADMAP.md` 或删 | Q-08 |
| `evals/test-scenarios*.yaml`（5 变体） | 1 个 SSOT + 生成脚本 | 实测版本值 5 个各不同（0.2.0/0.3.2.6/0.3.2.8/0.1.0/0.1.0）；内容等价性 ◐ |
| `test_gen_algo_*.py`（12） | 合并参数化 + 收敛 13 份 spec 加载副本 | 存在性自证（Q-33） |
| `test/upstream_pybest_0_3_2_8/` + `test/_archive` 幽灵 | 移出主树或补真跑；清 `__pycache__` | 20 条永久 skip（Q-34）、陈旧 pyc（Q-24） |
| `client.py` L374-400 `_parse_csv_text`/`_count_url` | 删除（连带 3 条测试） | 零调用死代码（Q-44） |
| `core/source_postprocess.py` 整类 | 接入或删（含 5 条测试） | 零生产调用（Q-20） |
| `scripts/repair.py` 整模块 | 删或降级为纯建议输出 | 双 0 调用 + 盲替换查询串（Q-53） |
| `services/mcp_client.py` | **先定去留**：接入 CLI 入口 + 补测试，或移出包 | 330 行最大死重且零验证（Q-61） |
| `rag/knowledge/` 双份、`templates/` 双模板、`bridge/` 双脚本 | 各归一 | Q-39/Q-31/Q-32 |

---

## 11. 实施批次与出口判据

```
批次 A —— 先解门禁与"别删错东西"
  Q-62 修正血缘口径（以 §2.1 双口径为准），冻结任何据 .qdeep 结论做的删除
  Q-10 改写 test_build_form_*            Q-06 前置：给 pybest 分支补消毒测试
  Q-07 eval 去文件名自证                 Q-41 lint 扩全仓 + Q-40 清 8 条
  Q-19 cli 退出码归 0（M7 已证明无阻力）  Q-24 清 __pycache__ 重取基线口径
  ▶ 出口：M1/M9 都变红；make lint 与 ruff check . 报错数一致

批次 B —— 科学正确性主修复（最高风险，需实网配合）
  Q-01 → Q-09 → Q-05 → Q-02 → Q-03 → Q-04 → Q-23 → Q-22 → Q-26
  ▶ 出口：M8/M10/M11/M12/M13 五条存活转红；探针 2 的幻影源与波段错位消失

批次 C —— 安全、并发、资源与链路完整性
  Q-06 全 emitter 接线 csv_safety（含 Q-60 编码统一、Q-58 异构记录）
  Q-54 下载链路补 checksum          Q-27/Q-28 转义          Q-21 凭据
  Q-11/Q-12 重试与限速锁（先补测试）  Q-17 并发              Q-18 Session 生命周期
  Q-16 环境变量 SSOT                Q-51 入参校验接线
  Q-14/Q-15 门禁 fail-closed 与配置透传

批次 D —— 声明面收敛（契约↔代码对齐）
  Q-56 pipeline/SKILL 符号改正 + 加"声明点必须可 resolve"契约测试
  Q-57 astro-common 依赖处理        Q-30 BestQuery 签名对齐
  Q-08 fail-closed 或降级 ROADMAP   Q-52 QueryContext 计数不篡改
  Q-50 版本单一源（__init__ 导入 _version）  Q-13 16 面一致   Q-38 UA
  Q-20/Q-44/Q-53/Q-61 死重定去留    Q-29/Q-31/Q-32/Q-37/Q-39/Q-55 资产与文档

批次 E —— 可并行卫生项
  Q-33/Q-34/Q-35 测试有效性   Q-43/Q-45/Q-46/Q-47/Q-48/Q-49
```

**统一出口条件**：每条修复必须自带"改坏就变红"的定向突变证据；无突变证据不计入完成。

---

## 12. 残留待实网确认

| # | 问题 | 已定论部分 | 仍需实测 |
|---|---|---|---|
| V-1 | `.constraint` 被服务端忽略还是降级 | ✅ 键集与协议不相交（探针 1） | 服务端对未知键的实际行为、是否触发全表扫描 |
| V-2 | CSV 到底带不带表头 | ✅ 包内三套互斥假设本身即缺陷（Q-05），M8 存活说明无人钉住 | 哪些星表/ sqlid 带表头，需 `ps1`/`std`/`gaia` 各取样本 |
| V-3 | 分页提前终止 | — | `rows=10` 小分页 + 带表头响应组合实测（可与 V-2 同趟） |
| V-4 | monorepo 外资产是否在交付边界内 | ✅ conftest 回退读上级 spec 且异常静默（Q-35）；`astro-common` 两处都不存在（Q-57） | 发布产物打包清单是否只含 `astro-best/` |
| V-5 | token 是否明文落盘 | ✅ 未见 `verify=False`；`pybest` 仅读 `~/pybest.ini` | 运行时日志与缓存文件的写入审计 |

---

## 13. 修完后的验收门禁（量化，缺一不可）

1. **突变存活率归零**：§7 中 7 条存活缺陷突变（M8–M14）全部转为被捕获；每个 P0 修复各配一条定向突变。
2. **eval 有效性**：生产代码被破坏时评分必须下降；恒定 1.0000 视为假门禁。
3. **Lint 口径一致**：`make lint` 报错数 == `ruff check .`；放开 BLE001/SIM 后另行清零。
4. **表单契约测试**：`set(生产表单键) ⊇ {pos.type, pos.racenter, pos.deccenter, pos.radius, output.fmt, showcol}` 且不含 `.constraint`。
5. **解析纯净性**：表头/无表头两类夹具下结果集不含 `ra==0.0 and source_id==""`，且波段值与列名一致。
6. **输出无损**：`dec=-5.0` 经所有 emitter 落盘仍为 `-5.0`；公式向量加 `'`；VOTable/HTML 可被解析器读回；编码一律 `utf-8-sig`。
7. **声明面可解析**：`pipeline.yaml` 每个 `tool:` 与 `SKILL.md` 每个 `astro_best.X.Y` 都能 importlib resolve；`manifest.yaml` 的 axes/sinks 每项要么有实现要么从声明删除。
8. **链路完整性**：下载流程实际调用 `verify_checksum`；公开入口实际调用 `validate_coordinate`/`validate_search_radius`。
9. **版本单一源**：`_version.py` 为唯一字面量源，`__init__.py` 改为 import，pyproject dynamic，metadata/UA/全部 YAML 由生成器写入并被测试枚举（16/16）。
10. **死重量化**：§2.1 的 9 个不可达模块与 §2.2 的 B 类零调用内部能力，每一项都要有"接线"或"删除"的处置记录；孤儿数从 9 降到 0（或书面豁免）。
11. **skip 预算**：`-rs` 明细全部可归类，`legacy import unavailable` 类为 0；`--collect-only` 与运行期结果数一致。
12. **依赖真实性**：AST 抽取的第三方 import 集合 ⊆ `pyproject.dependencies`，且无零 import 的硬依赖。

---

## 附录 A · 复现命令清单（全部只读，可重跑）

```powershell
# 基线
python -m pytest test/ -q --tb=no                       # 175 passed, 42 skipped
python -m pytest test/ --collect-only -q                # 197 collected
python -m pytest test/ -q -rs --tb=no                   # skip 明细（注意 -q 会折行）
python evals/eval_runner.py                             # 综合评分恒 1.0000
python -m ruff check . --statistics                     # 8 errors
python -m ruff check src/ --select BLE001,SIM,ANN --statistics

# 接线（正确实现见 §2.1；关键是 BFS 里要补 ancestors() 父包传播）
python -c "import sys; sys.path.insert(0,'src'); import astro_best, astro_best.cli; \
print(sorted(m for m in sys.modules if m.startswith('astro_best')))"   # 运行时口径 23

# 契约 resolve
python -c "import sys; sys.path.insert(0,'src'); import importlib; \
[print(p, end=' ') or importlib.import_module(p) for p in ['astro_best.core']]"  # 逐个 try

# references 路径缺陷
python -c "import sys; sys.path.insert(0,'src'); from astro_best.references import list_references; \
print(list_references())"                               # []

# 版本面
pip show astro-best | Select-String Version
python -c "import importlib.metadata as m; print(m.version('astro-best'))"   # 0.3.2.8

# 突变矩阵要点（务必字节级 + 保行尾 + 每轮还原复测基线）
#   raw = Path(f).read_bytes(); nl = b'\r\n' in raw
#   anchor = anchor.replace('\n','\r\n') if nl else anchor   # 否则整文件行尾被归一，测量失真
# PowerShell 重定向一律 | Out-File -Encoding utf8（默认 > 产 UTF-16LE，Python 读不回）
```
