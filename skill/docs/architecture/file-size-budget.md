# 代码规模预算与人工复核面（astro-best）

> 本文是 `README.md` 治理规则第 7 条的展开说明。`docs/` 为 local-only 目录（不随 git 分发），
> 故此处放**详细论证**，README 只保留规则本体与指针。

---

## 1. 规则本体

| # | 规则 | 口径 |
|---|---|---|
| R1 | 单个 `.py` 文件的**净代码行**非必要不超过 **400 行** | 净代码行 = 总行数 − 空行 − `#` 注释行 − docstring 物理行 |
| R2 | 超出 400 行的文件必须在本文档登记必要性论证与拆分预案 | 未登记即视为违规 |
| R3 | 所有注释与 docstring 一律中文 | 技术标识符/HTTP 路径/列名/异常名保持英文原样 |
| R4 | 注释密度：每个函数一段中文 docstring；每个外部 API/IO 调用点一条中文行内注释；每个 import 组一条中文说明 | 目的是让不懂英文的复核者独立读懂 |

**为什么按"净代码行"而不是总行数**：本仓刻意用长 docstring 承载回归锚点与失败语义
（`src/protocol.py` 总 933 行 / 净 307 行）。按总行数卡 400 会逼着删注释，恰好与
"增加人工复核空间"的目标相反。净口径约束的是**必须读的逻辑量**。

---

## 2. 度量口径与复测命令

定义（与规则 R1 一致）：

- 不计空行与纯空白行；
- 不计 `#` 开头的注释行；
- 不计 docstring —— 即模块/类/函数体中作为首个语句的字符串字面量所占的物理行
  （用 `tokenize` 判定：该 STRING token 是其所在逻辑行的第一个 token）。

复测（在 `astro-best/` 下执行）：

```powershell
python ops/audit/count_code_lines.py          # 全仓扫描, 结果写 temp/line_counts.json
python ops/audit/count_code_lines.py | Select-String "OVER"
```

覆盖范围（2026-10-05 改口径，判据审计 D5-01）：**仓内全部 `.py`**，排除项只有
`ops/audit/scan_roots.py` 里那三类非源码目录（工具/版本库状态、第三方依赖与构建产物、
gitignored 的数据与临时区），逐项理由见该模块头的表格。改口径的原因：此前是目录
**白名单**（`src/ ops/ evals/ test/ examples/ rag/ docs/diagrams/`），而白名单的缺口
只能靠不断补——实测在 `agents/` 下放一个 900 净行的文件，四道门禁全部 exit 0
（铁律 2 被违反 900 行而门禁全绿）。黑名单口径下新建目录里的 `.py` **自动进门禁**。
四个消费方（`count_code_lines` / `comment_audit` / `verify_doc_consistency` /
`code_fingerprint`）都从该模块取覆盖面，不再各自抄一份。

> 注意：补注释**不会**推高净代码行（注释与 docstring 都不计），因此"补中文注释"与
> "400 行预算"两条规则不冲突。

---

## 3. 当前超限登记簿

> **复测修正（重要）**：本节此前的数字（eval_runner 513 / client 502 /
> pybest 469 / downloader 401）是**用粗糙口径测出来的，严重低估**。同一口径实测
> （`python ops/audit/count_code_lines.py`，净代码行 = 物理行 − 空行 − 注释 − docstring，
> 组内去重避免 docstring 与空行双重计数）得到的是下表。偏差根因：早先脚本把
> 多行表达式的续行也当"非代码行"扣掉了，`evals/eval_runner.py` 一项就少了 458 行。
> 已按实测重登记，并把遗漏的 5 个超限文件补入。
>
> **拆分进展**：`src/protocol.py`(658→381) 与 `src/downloader.py`(508→381)
> 已通过"抽数据表/抽落盘辅助到新模块 + 原地留薄壳"降到 400 以内，见 §3.9。
> 剩余 7 个文件的拆分方案见 §3.1~§3.8。

| 文件 | 净代码行 | 物理行 | 超限 | 状态 |
|---|---|---|---|---|
| `src/protocol_catalog_tables.py` | 662 | 817 | +262 | 已登记，见 §3.11（2026-09-29 线上列全覆盖重写所致） |
| `src/client.py` | 380 | 795 | — | **已入预算，登记豁免撤销**（2026-10-05 阶段 3~6，见 §3.2） |
| `src/protocol.py` | 483 | 1058 | +83 | 已登记，见 §3.10（P0-1 分页定序单点 + 协议层修复；2026-09-30 错误码单点上收 +2） |

> `ops/audit/comment_audit.py` 曾以 411 净行（+11）登记，2026-10-03 已按 §3.13
> 拆出 `ops/audit/line_scope.py`（135 净行），本体降至 326 净行，该条登记移除。

> **2026-09-30 完善轮拆分（R2 执行）**：
> - `evals/repro/tests/test_e6.py`（743）→ 拆三件：`support_e6.py`（共享夹具）+
>   `test_e6_foundation.py`（输入面/统计）+ `test_e6_metrics.py`（指标面 389）+
>   `test_e6_runner.py`（CLI 冒烟）；拆分后 174 用例与原文件**逐一对齐无丢失**；
> - `ops/astro_best_cli.py`（454）→ download 子系统（子解析器接线 + 实现）
>   整体抽至 `ops/cli_download.py`，主文件降至 **332**；`_safe_path` 薄委派
>   的唯一调用点随迁并直走 `resolve_data_path` 单点（不留零调用函数，P1-7 反模式）；
> - 登记簿清理：`src/pybest.py` 条目随 P1 删除移除；
>   `test/unit/audit_round/test_audit_fixes.py`（398）回落预算内。
>
> **当前超限 3 个全部已登记**（§3.2 已论证例外 / §3.10 / §3.11 数据表），
> 未登记超限 = 0。复测命令：`python ops/audit/count_code_lines.py | Select-String "OVER"`。

> **拆分进展**：`docs/diagrams/` 两个图生成器 (793/584) 已按 §3.5 拆分预案把坐标
> 常量抽到 `layout_data.py`，双双回到预算内 (§3.5 已改为"已完成")；
> `evals/eval_runner.py`(990→381)、`test/integration/test_integration.py`
> (577→7 个文件最大 171)、`src/tap/service.py`(499→入预算内)、
> `src/downloader.py`(508→381)、`src/protocol.py`(658→381→464)、
> `src/pybest.py`(566→389→406) 的拆分/回涨记录见 §3.1/§3.7/§3.9/§3.10。

次接近上限（暂不构成违规，列出以便预警）：`evals/probes.py` 387、
`src/downloader.py` 382、`src/ai_tools.py` 378、`src/download_manager.py` 337、
`ops/astro_best_cli.py` 331、`src/tap/service.py` 319、`evals/audit/__init__.py` 353、
`evals/eval_runner.py` 316、`src/tap/adql.py` 313、`evals/case_executor.py` 295。

> **这张榜刻意不进阻断门禁**（V2 定稿结论）：它是**每次改代码都要手工刷新**的预警
> 榜，而全仓有 311 个 .py，任何一次提交都会让榜上若干条目过期 —— 拿它当判据等于
> "改任何文件都红"，正是本轮要避开的噪声源。复算入口只有一个：
> `python ops/audit/count_code_lines.py` 的「250~400 接近文件」段（口径与本榜一致）。
> 2026-10-05 V2 实测刷新：原榜 11 条里 **9 条已过期**（如 `src/crossmatch.py` 标
> 361 实为 285、`src/downloader.py` 标 368 实为 382）。

> **复核注记**：`evals/eval_runner.py` 由 971 增至 990 净行 —— 增量来自
> Phase 3 的 D1/D4/D5 修复（measured 语义、阻断项、反证夹具）。该文件既是**被测
> 对象**又是**评测执行器**，其自身回归 (`test/unit/meta/test_eval_runner_dimensions.py`,
> 255 净行) 已单独成文件，故 §3.1 的探针层拆分仍是正解，且拆分会更安全。

> **拆分进展（第二次）**：`src/tap/service.py`(499→入预算内)、
> `src/pybest.py`(566→389) 也已入预算内，见 §3.9。超限文件从 9 个降到 **5 个**。

### 3.1 `evals/eval_runner.py`（971）

**必要性**：这是行为评测 + 内容质量审计的**单一运行器**，三类异质职责被刻意放在一个
可独立执行的入口里：

1. 探针层（`probe_*`）——每个探针是一次**真实协议交互**（两阶段查询 / 名称解析 /
   proximity 批量 / TAP / 工具面 / MCP），必须共用同一套会话与限流配置，拆开后
   "探针之间是否互相污染"变得不可判；
2. 门禁层 ——`http_status`/`correctness`/`connection_info` 三个门禁的判定逻辑依赖探针
   产出的同一份结果结构；
3. 报告层 ——评分公式、反证夹具（每个审计器的 `broken_samples` 必须被拒绝）、
   docstring 维度汇总。

**为什么不拆**：拆成 `probes.py` + `gates.py` + `report.py` 会让"探针 → 门禁 → 报告"
的数据流穿过三个模块的私有结构，而评测运行器的核心价值恰是**这条流可被一次读完整**。
拆分的认知成本高于 400 行红线省下的成本。

**拆分预案**（触发条件：任一探针数量再增加 ≥3 个，或门禁规则 ≥5 条）：
按职责切 `evals/probes/`（每个探针一文件，统一 `run(ctx) -> dict` 契约）+
`evals/gates.py` + `evals/report.py`，运行器只做装配。属结构变更，需用户批准。

### 3.2 `src/client.py`（553）

**必要性**：`BestClient` 是唯一生产入口，两阶段协议（POST 表单 → sqlid → 分页 GET）的
六个公开 seam（`submit_phase1`/`submit_query`/`fetch_page`/`count`/`crossmatch_batch`/
`resolve_name`）必须与私有实现同文件，才能保证"改私有实现不影响公开契约"可被一次读全。
`BestAuth` 已迁到 `src/auth/session.py`（589 → 553）。

**为什么剩下的 153 行不能再按"抽模块"降**——主控按"裁定由我定、完成所有任务"
重新逐条核过，原文三条论证有**一条实测不成立**，已改为如实表述：

1. ~~其余方法几乎全被测试钉死在实例上，薄壳只省"实现体"不省"签名+docstring"~~
   ——**实测不成立，原判断作废**。`patch.object(client, "_fetch_sqlid_data")` 一类补丁在
   "搬走实现 + 留同名同签名委派壳"之后**依然有效**（补丁替换的是实例上的绑定方法，
   壳仍是同名方法）；且薄壳省的是"实现体"这一大块——`_fetch_sqlid_data` 141 物理行
   的壳只需约 12 行，净省约 129 行，"额度大幅缩水"是把薄壳成本高估了。
   被钉住的方法实测：`_fetch_sqlid_data`×6、`cone_search`×8、`_execute_query`×3、
   `_submit_query_for_sqlid`×2、`_count`/`fetch_page`/`query_panstarrs` 各 1-2 处，
   全部可由委派壳承接。
2. **两阶段引擎是主链本身，拆它损害可读性**（原第 1 条，理由从"不许拆"改为如实表述）：
   `_fetch_sqlid_data`(141) / `_submit_query_for_sqlid`(55) / `_execute_query`(50)
   合计约 246 物理行是"一次查询经历什么"的主链，搬走等于把主链拆到两个文件。
3. **技术上可行但余量过薄，且属未批准的结构变更**：把 phase-2 取数关注点
   （`_fetch_sqlid_data` + `_count` + `count`，合计约 179 物理行）抽到
   `src/client_paging.py`、留委派壳，实测可到约 **394** 净行——能过 400 线，但
   ① 余量仅 6 行，任何后续新增都会再次超限；② 该拆分**不在用户已批准的新模块清单内**
   （批准清单见 README 治理规则 3 与 governance-debt-plan.md 的 Phase 0-7），
   按"结构变更需显式批准"铁律不予执行；③ 拆主链的收益（6 行余量）远低于
   可读性代价。

**结论（裁定）**：`src/client.py` 维持 553 行，登记为**已论证的例外**而非"待修"。
正解仍是 README 已排期的 **P1-9 双入口合并**——`BestClient` 成为唯一客户端后，
`src/pybest.py` 的 368 行门面消失，届时可重新评估是否值得为余量拆主链。

**拆分预案**（触发条件：接入第二套认证机制，或公开方法再增 ≥3 个）：
正解是执行 README 已排期的 **P1-9 双入口合并**——`BestClient` 成为唯一客户端，
`src/pybest.py::Best` 退化为它的薄适配层。届时 `BestClient` 仍是 550 行量级，
但 `src/pybest.py` 会消失，**全仓客户端代码总量**下降约 40%。属结构变更，需用户批准。

> 备选（不推荐）：把 `BestClient` 整体改成"一层委派薄壳 + 私有实现模块"。薄壳约
> 120 净行、实现模块约 430 净行 —— 只是把超限从一个文件搬到另一个文件，且让
> "改私有实现不影响公开契约"这条可读性承诺失效。
>
> 补充实测：若只抽 phase-2 取数关注点（`_fetch_sqlid_data` + `_count` +
> `count`）到 `src/client_paging.py` 并留委派壳，可到约 394 净行——这是唯一能过
> 400 线的抽法，但余量仅 6 行且需拆主链，按上文裁定不予执行；如将来公开方法再增
> 而触发拆分预案，这是首选抽法。

> **2026-09-30 执行更新（完善轮 2）**：上文裁定的前置条件（P1-9 双入口合并，
> pybest 删除、BestClient 成为唯一客户端）**已达成**，且文件已从 553 涨到
> **725** 净行（E2 `query_result` 信封缝 + F-E4-01 半行跳过接线等增量）——
> "已论证的例外"的数字基础失效，按 R2 执行上文备案的首选抽法：
> - **阶段 1（已执行）**：`_fetch_sqlid_data`(198 物理/136 净) + `_count`
>   (32/15) 抽至 `src/client_paging.py`（模块函数 `fetch_sqlid_data(client,...)` /
>   `count_sqlid_rows(client,sqlid)`），原方法留同名同签名委派壳；
>   client.py **725 → 581** 净行。错误码单点上收 protocol（破除
>   client→client_paging Import 环）；`_control_flow_errors` 随迁。
>   实测：全量 1174 passed 零回归；`test_gate_blindspots` 分页单点门禁
>   同步扩展为三断言（client_paging 在场 / client 委派壳在场 / src/ 无
>   stable_uri 外的自拼分页串）。
> - **阶段 2（已执行，2026-09-30 当晚）**：query 表面（`query_result`/`query`/
>   `_query_result` 三缝 + 共享 `_build_form`）抽至 `src/client_query.py`
>   （模块函数 + 委派壳；`_build_form` 留壳使其余五个查询方法调用点零改动）。
>   client.py **581 → 536** 净行。实测：全量 1175 passed 零回归；
>   期间抓到并修复一个真 bug（`_query_result` 内 `client._build_form` 双跳
>   改为直调模块 `build_form` — 抽离缝的 ImportError 由集成测试先抓出）。
> - **余量实测与阶段 3 评估（不再深拆，理由如上文论证且 measurably 成立）**：
>   剩余 536 净行的方法块分布（实测）：`cone_search` 70 / `__init__` 35 /
>   `submit_query` 34 / `_execute_query` 29 / `_submit_query_for_sqlid` 28 /
>   `crossmatch_batch` 26 / `resolve_name` 22 / `fetch_page` 21 / 三个查询
>   族方法各 ~19 / 五个委派壳共 94（每个 ~18，docstring 承载缝契约）。
>   要入预算内须再移 ~136 净行 = `cone_search`(70) + phase-1 执行组
>   (`_submit_query_for_sqlid`+`_execute_query`+`submit_query`+`submit_phase1`
>   ≈108) — 即 §3.2 备选方案明确否掉的"整体委派薄壳 + 私有实现模块"（实现
>   模块自身会超 400，且"改私有实现不影响公开契约"的可读性承诺失效）。
>   **结论：执行至阶段 2 为止，剩余 136 净行维持登记例外**；触发条件改为
>   "cone_search 或 phase-1 执行组发生结构性修改时顺势再抽"。

> **2026-10-05 执行更新（阶段 3~6，触发条件已成立，登记豁免撤销）**
>
> 触发条件「cone_search 或 phase-1 执行组发生结构性修改」在 F-E4-01 半行
> 跳过接线与 E2 信封缝那几轮里已经成立，用户批准本轮工单后按上文备案的抽法
> 全部执行完。**净行 536 → 380，落入预算内**，故据 R2 撤销本节登记条目。
>
> | 阶段 | 切分面 | 去向 | client.py 净行 |
> |---|---|---|---|
> | 3 | `resolve_name`（`/nss/solve` 名称解析，与两阶段协议正交） | `src/client_resolve.py`（新） | 557 → 533 |
> | 4 | `cone_search` + `crossmatch_batch`（锥形 / proximity 查询面） | `src/client_query.py`（**补齐其模块头早已声明却未持有的边界**） | 533 → 469 |
> | 5 | `query_standard_stars` / `query_panstarrs` / `query_calibrated` | `src/client_query.py` | 469 → 463 |
> | 6 | `_submit_query_for_sqlid` + `_execute_query` + `submit_phase1` + `submit_query` + `_error_code_from_message` | `src/client_phase1.py`（新） | 463 → **380** |
> | 6 | `fetch_page`（phase-2 单页续取公开缝） | `src/client_paging.py` | 同上 |
>
> 两处与上文论证的偏差，如实记录：
>
> 1. 上文第 3 条把「抽主链」列为代价，本轮仍抽了 —— 因为 §3.9 原则 1 的
>    例外恰好是「与主链正交的关注点」，而 phase-1 组与 phase-2 组之间的交接
>    点**只有一个** `client._fetch_sqlid_data` 委派调用；抽完后
>    「一次查询经历什么」仍可沿 client → client_phase1 → client_paging
>    一次读完，没有出现「数据流穿过多个模块私有结构」的坏形。
> 2. 上文估「薄壳只省实现体」是对的，但**低估了壳的签名成本**：本仓每个
>    参数都带中文右注，签名行逐行计净行，于是 11 行签名的方法抽出去只净省
>    6 行（阶段 5 实测）。这也是为什么最终余量（20 行）来自「五个模块各自
>    达标」而不是任何一刀的大幅下降。
>
> 余量现状：client.py 380，余量 20 行。五个 `client_*` 模块全部在预算内
> （client 380 / client_query 289 / client_paging 225 / client_phase1 146 /
> client_resolve 35）。后续再增公开方法时，优先考虑挂到既有模块的单点上，
> 而不是继续往 client.py 加。

### 3.3 `src/pybest.py`（405，P2-6/7/8 双副本对齐后刚过线）

**必要性**：这是 **pylamost 范式的单类接口**，"单类"是它的设计契约而非偶然——
`Best` 一个对象同时承担查询/下载/光变/匹配，与 `src/client.py` 的双副本关系记录在
README 的 `src/pybest.py` 行（"与 client 双副本合并排二期"）。按行数拆类会直接违背
该设计声明。本轮 P2-6（std 组展开对齐）/P2-7（query 默认形态统一、crossmatch_batch
补 page_size）/P2-8（resolve_name 异常收敛、getcount 软 404 口径）把 389 推到 405。

**为什么不拆**：拆成 `BestQuery`/`BestDownload` 会让 pylamost 兼容面断裂
（`Best().cone_search(...)` 是老调用方的唯一入口）。

**拆分预案**：不拆。正解仍是执行 README 已排期的 **P1-9 双入口合并**——`Best` 退化为
`BestClient` 的薄适配层（保留方法名，内部全部委部），届时本文件自然降到 200 行以下。
属结构变更，需用户批准。余量仅 5 行，后续新增优先考虑能否落入 client/protocol 单点。

### 3.4 `src/downloader.py`（519）

**必要性**：职责（区域下载 / sqlid 下载 / 断点续传 / std 组展开 / 区域合并 /
provenance sidecar / 多格式落盘）彼此通过 `self.checkpoint` 与 `self.client`
强耦合；且 `BestDownloader` 同时被 `src/pybest.py` 与 `src/download_manager.py`
两个上层复用，拆分会把"下载产物长什么样"这件事分散到三个文件。

**拆分预案**（触发条件：净代码行再增 ≥20 行）：把 `_merge_region_files` 与
`_write_provenance` 两个自洽辅助函数提到 `src/download_artifacts.py`。属结构变更，
需用户批准。

### 3.5 `docs/diagrams/gen_best_macro_flowchart.py`（794）与 `gen_astro_best_architecture.py`（578）→ **已完成拆分**

**必要性（原登记理由，仍有效）**：这两个是 **drawio 图生成器**，代码主体是
"坐标常量 + 卡片模板 + 连接线"的声明式数据，不是控制流。把 2000×3000 像素的
画布按区域切开（每区一个函数）会让"这张图的布局"无法在一个屏幕里看完——而图
生成器的全部价值就在于**布局可一次读全**。它们位于 `docs/diagrams/`，本来就在
ruff `extend-exclude` 中，不参与发布路径。

**已完成（按原拆分预案执行）**：坐标常量表已抽到 `docs/diagrams/layout_data.py`
（纯数据，无逻辑），两个生成器只留渲染代码，实测均已回到 400 净行以内
（提交 `755fbe78`）。§3 登记簿中相应条目已移除。

### 3.11 `src/protocol_catalog_tables.py`（405 → 662，2026-09-29 线上列全覆盖重写所致）

**必要性**：这是全仓**唯一的星表侧数据注册簿**（路径/分组/别名/显示名/showcol
表单表/响应列清单/星等列/星等误差列/质量列九张表），**不含任何函数**（模块
docstring 即此声明）。它正是 §3.9 从 `src/protocol.py` 抽出来的那个"数据表模块"——
抽取的理由（§3.9 原则 4）就是"数据表类内容占预算额度但不构成必须读的逻辑量"。
2026-09-29 线上端点审计（`temp/audit_column_drift.py`）发现静态列清单与站点漂移：
smss_dr4/uss_dr1 已按波段重构（旧登记列全成幻影列，服务端静默丢弃），
gaia_dr3_18/scr_galah/scr_lamost/xpsp 只登记了线上可选列的 4%~24%。按线上
全量重写后净行 405 → 662，换来的是 12 张星表的列覆盖从"部分"到"逐一相等"
（守门测试 `test_static_columns_match_the_live_showcol_counts`）。

**为什么不拆**：本文件的超限全部是**列名字符串常量**（线上列清单的忠实镜像），
不是逻辑量；拆成多个数据文件会让"哪个星表有哪些列"重新散落——这正是 §3.6
反对的形态，也会让 `qualify_column` 的白名单判定要跨文件拼装。列清单的单一
出处比文件行数更重要。

**拆分预案**（触发条件：净代码行再增 ≥200 行，或线上星表结构再次大改）：
把逐星表响应列清单（`CATALOG_COLUMNS` 的大列表）迁到 `data/` 下的
YAML/JSON（纯数据文件，import 时加载），Python 侧只留小表与注释；列清单仍保持
单一出处。属结构变更，需用户批准。届时同步更新
`test/unit/meta/test_catalog_registry_live.py` 的列数门禁数据来源。

### 3.12 `test/unit/audit_round/test_audit_fixes.py`（406，Phase 6 修复回归集）

**必要性**：Phase 6"文档回正与门禁增强"轮的修复回归集（宽 ruff/AST 扫描/行为
盲区三类门禁的守门测试），按修复批次集中在一个文件，+6 行刚过线。

**拆分预案**（触发条件：净代码行再增 ≥30 行）：按三类门禁拆成
`test_gate_ast.py` / `test_gate_ruff.py` / `test_gate_behavior.py`。属结构变更，
需用户批准。

### 3.6 `src/protocol.py`（649）

**必要性**：协议层是**唯一的端点常量与表单拼装事实源**。两阶段协议的全部端点路径、
12 张星表的列名映射、软 404 判定、名称解析哨兵、getcount 键控规则必须集中一处，
否则 `src/client.py` 与 `src/pybest.py` 两个客户端会各自漂移出一套端点认知
（历史上正是这个漂移导致两个客户端解析行为不一致，见 §5.3）。

**为什么不拆**：按星表拆映射表会让"哪个星表有哪些列"散落多个文件；按端点类型拆
会让"软 404 判定"与"端点路径"分离，而这两者在排障时必须一起看。

> **2026-10-02 复评：抽 `build_query_form` 到 `src/protocol_form.py` 的提案已否决。**
> 该提案按"功能种类"拆（表单拼装独立成模块），乍看不落在上面两条否决理由内，
> 但仍与本节必要性冲突：`build_query_form` 是**表单拼装事实源**本身，与端点常量
> 同属"唯一权威协议层"；`references/ALGORITHM-SPEC.md:37` 的 §2 锚点表正是把
> `build_query_form / parse_csv_rows / parse_count / is_soft_error / parse_name_resolve`
> 五个符号一并锚定到 `src/protocol.py`。抽出后锚点表要改指另一文件、"权威协议层"
> 的边界从文档降级为约定，且新模块要反向 import 本模块的 `resolve_catalog` /
> `qualify_column` / `_constraint_value` / `CATALOG_PATHS`，形成循环依赖（需在
> 本模块文件末尾做延迟 re-export 破环）。代价与收益不成比例。当前 483 净行，
> §3.10 的拆分触发线是 496，**未触发**，本文件维持登记豁免。

**拆分预案**（触发条件：可查星表数再增 ≥4 张，或新增第二套协议）：
把 `CATALOG_FORM_TABLES`/`CATALOG_COLUMNS` 等大映射表移到
`src/protocol_catalog_tables.py`（纯数据），判定函数留在 `src/protocol.py`。
属结构变更，需用户批准。

### 3.7 `test/integration/test_integration.py`（560 → **已拆分**）

> **已按链路拆完**（原 577 净行 / 991 物理行 → 7 个文件，最大 171 净行）。
> 拆分方案即原预案，未新增夹具层级：**`test/conftest.py` 零改动**。

**拆分结果**（按被测的能力链切，测试函数体逐字节未改，类名与方法名不变）：

| 新文件 | 净行 | 承接的原内容 |
|---|---|---|
| `test/integration/test_query_chain.py` | 171 | `make_query_html` + `TestBestClientIntegration` + `TestQueryParameterPlumbing` |
| `test/integration/test_data_semantics_chain.py` | 142 | CSV 基准数据 + `_mock_csv_response` + `TestDataSemantics` |
| `test/integration/test_server_count_chain.py` | 97 | `TestServerTotalCount` |
| `test/integration/test_soft404_chain.py` | 88 | `TestSoft404Detection` |
| `test/integration/test_name_resolution_chain.py` | 78 | `TestNameResolution` |
| `test/integration/test_crossmatch_chain.py` | 34 | `TestBestCrossMatch` |
| `test/integration/test_multiband_photometry_chain.py` | 12 | `TestBestMultiBandPhotometry` |

**为什么不把共享夹具上移 conftest**（原预案说上移，实测后改为不上移）：拆分前逐個
grep 核实过，原文件每个模块级 helper **都只有 1 个消费类** ——
`make_query_html` 仅 `TestBestClientIntegration` 调、`_mock_csv_response` 9 处调用全在
`TestDataSemantics` 内、`CSV_WITH_HEADER`/`CSV_HEADERLESS` 仅 `TestDataSemantics` 消费。
上移即制造**跨文件死 fixture**（正是 E5 债务刚清掉的那类问题），故 `test/conftest.py`
一字未改。原预案担心的"同一份 mock HTML/CSV 夹具要在多个文件间复制"没有发生 ——
因为每条链路各自只用自己那份夹具。

**顺带删除一处死代码**：`make_sqlid_json_page` 在原文件即为零消费者（全仓 grep 仅定义处），
按 E5 同律未搬迁、就地删除。

**拆分前后不变量**：集成测试收集数 68 → 68（分文件明细：原 11+44+2+11 → 新
4+10+11+2+6+2+11+11+5+6），AST 对 HEAD 版原文件与 7 个新文件并集做 (类名, 方法名)
集合比对：45 对，丢失 0 / 新增 0 / 改名 0。

**联动收口**：`docs/architecture/coverage-matrix.md` 有 15 条 integration 列锚点指向已删除
的 `test_integration.py`，已按「只改路径段、类名与方法名不动」机械替换到 7 个新文件
（矩阵门禁 `test_coverage_matrix.py` 7 条断言复跑通过）。

### 3.8 `src/tap/service.py`（499）

**必要性**：IVOA TAP 1.1 网关的请求分发（sync/async/VOSI/UWS）与 stdlib
`http.server` 的处理器必须同文件——`TapRequestHandler` 的 `do_GET`/`do_POST`/
`do_DELETE` 直接调 `TapGateway.handle(...)`，这个对应关系是零依赖传输层的全部骨架。

**为什么不拆**：拆开后"哪个 HTTP 动词路由到哪个 TAP 能力"要从两个文件拼出来，
而这是排障时第一个要确认的事。

**拆分预案**（触发条件：TAP 端点数再增 ≥3 个）：把 UWS 作业生命周期
（create/phase/run/delete）抽到 `src/tap/uws_service.py`，`service.py` 只留
HTTP 动词到网关的映射。属结构变更，需用户批准。

### 3.9 已完成拆分（用户批准"优化到 400 以内"）

两个文件通过"**抽到新模块 + 原地留委派薄壳**"降到预算内。薄壳保留原方法名与
签名，既有 import 路径与调用点全部不受影响；被抽出的模块用 AST 精确定位边界
（含上方注释块），搬完立即跑 ruff + pytest 验证。

| 文件 | 前 | 后 | 抽出了什么 | 新模块 |
|---|---|---|---|---|
| `src/protocol.py` | 658 | 381 | 9 张星表侧数据表（路径/分组/别名/显示名/showcol 表单表/响应列/星等列/星等误差列/质量列，约 400 行纯数据） | `src/protocol_catalog_tables.py` |
| `src/downloader.py` | 508 | 381 | ① 落盘辅助（路径解析/校验和/组合并/provenance sidecar/原始导出）② 区域编排（std 组展开/断点路由/一次性锥搜）③ sqlid 分页下载与断点续传 | `src/download_artifacts.py` / `src/download_region.py` / `src/download_sqlid.py` |

同轮还抽出一个**跨路径共用**的序列化层 `src/serialization.py`
（csv/tsv/json/votable/fits 写出 + 格式白名单 + 列类型推断），它同时修掉了三个
已存在的缺陷，见 §9.4。

**拆分原则（后续照此办理）**：
1. 只抽"与主链正交的关注点"，主链本身不拆——拆主链会让数据流穿过多个模块的
   私有结构；
2. 抽出的模块第一个参数显式接收原对象（`downloader`），不反向 import，避免循环依赖；
3. 原地留的薄壳必须保留原名/签名/返回类型，只改实现为一行委派；
4. 数据表类内容（无逻辑）优先抽——它占预算额度但不构成"必须读的逻辑量"。

### 3.10 `src/protocol.py`（381 → 466，P0-1 分页定序单点 + P1 协议层修复所致）

**必要性**：两轮修复的新增逻辑全部落在协议层这一"唯一权威协议层"里，且都属于
**不许出现第二份**的内容：

1. P0-1 分页定序单点：`PAGINATION_SORT_COLUMNS`（12 星表 → 排序列数据表）+
   `pagination_sort_key()` + `build_page_url()`（两个客户端分页 URL 的唯一构造点）。
   分页 URL 的构造规则离开协议层，两个客户端就会再次各写一份——这正是 P0-1 的
   根因形态；
2. P1-1/P2-2 CSV 解析判据：表头权威判定 + 列名形态识别 + overflow 降级，
   必须与 `CATALOG_COLUMNS`（同文件的权威列清单）同文件才能一次读全；
3. P1-2/P1-3 列名 fail-closed：`_catalog_table_columns()` 由 `CATALOG_COLUMNS`
   反推每张表单表的已知列集合，与 `catalog_tables()`/`qualify_column()` 强耦合。

**为什么不现在拆**：超出 +63 行；按 §3.9 原则 4 拆"数据表 + 判定助手"在技术上
是标准的薄壳抽取（先例即 §3.9 的 protocol_catalog_tables.py），但**新增受跟踪的
src 模块属结构变更**，按 README 治理规则 1/3 需用户显式批准；本轮修复方案已批准
的新增文件仅限门禁用途（`test/unit/meta/test_gate_blindspots.py`）。

**拆分预案**（触发条件：净代码行再增 ≥30 行，或 Phase 6 门禁轮次一并申请）：
把 `PAGINATION_SORT_COLUMNS`（纯数据）+ `pagination_sort_key` 抽到
`src/protocol_pagination.py`，`build_page_url` 留在协议层（它是逻辑不是数据，
且与 `SQLID_PATH` 强耦合）；`_catalog_table_columns` 视 qualify_column 的
演化决定去留。原地留 re-export 保既有 import 路径。属结构变更，需用户批准。

---

## 4. 中文注释规范（权威规则）

> 本节是全仓注释规范的**唯一权威文本**。`temp/COMMENT_SPEC.md` 是任务派发用的临时
> 留档，不是规范源；两者冲突时以本节为准。

### 4.1 硬性规则

| # | 规则 | 说明 |
|---|---|---|
| C1 | **语言**：所有 `#` 注释与 docstring 一律中文 | 技术标识符、HTTP 路径、列名、异常类名、DOI/arXiv 号、IVOA 协议标准名（TAP 1.1 / ADQL 2.1）保持英文原样 |
| C2 | **覆盖**：每个 `class` / `function` / `method` 必须有 docstring | 含 `__init__`、`__str__`、`__enter__`、`__exit__`、`log_message`、`do_GET` 等协议方法；缺一个即违规 |
| C3 | **import 组**：每个 import 组至少一条中文说明 | 组 = 连续的 import/注释/空行区间（续行归属同组）；一条组注释覆盖整组，不要求逐条 |
| C4 | **只改注释不改代码** | 不改标识符、逻辑、语句顺序、参数、默认值、字符串字面量（错误信息是运行时契约） |
| C5 | **注释禁版本号** | 与全仓铁律一致；注释里出现发布版本号即违规 |
| C6 | **行尾白名单**：以下可保留英文 | `#!/usr/bin/env python3`、`# noqa: <code>`、`# pragma: no cover`、`# legacy-import-guard`、`# type: ignore[...]`、`# ---` 类分隔线。**指令后的解释文字仍须中文**（如 `# noqa: BLE001 - 记入 failures, 不静默吞`） |

### 4.2 白名单判定口径（避免误报）

一条注释算"中文注释"的条件：**该注释块内任一行含 CJK 字符**
（`[\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]`，含中文标点）。

理由：中文注释的续行常是纯标识符（如 `# build_query_form()`、`# ``{catalog}.{col}```），
逐行判定会把它们误报成英文注释。**必须按块判定**。

同理，import 组覆盖也必须按组判定——早先的逐条口径把已覆盖的组虚报成欠覆盖
（217 条虚报 → 实测 0 条）。

### 4.3 docstring 三段式质量标准

测试函数的 docstring **不许写"测试某某功能"这类空话**，必须写清三件事：

1. **验证什么行为** —— 调用什么、传什么、断言什么；
2. **为什么重要** —— 这个行为坏了会造成什么后果，尤其要点明**静默错误**
   （数据错了但不报错，比显式失败危险得多）；
3. **回归背景** —— 有 bug 编号/历史缺陷时点明（如 Q-20、P1-6、P0-3）。

生产代码的 docstring 保留 `Args:` / `Returns:` / `Raises:` / `Note:` 小节标题
（英文段标题属 C1 白名单），小节内文字中文化；`Note:` 用来写"为什么不那么做"。

### 4.4 外部 API / IO 调用点

每一次外部 API / IO 调用点一条中文行内注释，写清：**调的是什么 + 协议阶段 +
失败语义 + 降级策略**。示例：

```python
# HTTP 调用点 (协议阶段一+二): download_region 内部 POST /q 取 sqlid
# 再分页拉取; 包一层 hooks.run_network — 网络类失败指数退避重试,
# 耗尽才升级为 HookInterrupt (blocked)
```

### 4.5 防回归护栏（四道，必须全绿）

| 护栏 | 命令 | 守住什么 |
|---|---|---|
| AST 指纹 | `python ops/audit/code_fingerprint.py check` | 剥离 docstring 后的 AST 与 git HEAD 一致 → 证明只改了注释 |
| 代码零丢失 | `python ops/audit/verify_no_code_loss.py` | 逐文件比对 def/class 数、assert 数、净代码行集合 → 证明没删代码 |
| 注释体检 | `python ops/audit/comment_audit.py` | 缺失 docstring / 非中文 docstring / import 组欠覆盖 / 重复注释 / TODO 全为 0 |
| 行尾一致性 | `python ops/audit/check_line_endings.py` | 无 CRLF 混入（本仓约定 LF） |

辅助：`python temp/show_english.py`（列英文注释）、`python temp/show_import_gaps.py`
（列 import 缺口）、`python temp/dump_docstring_gaps.py`（列缺失 docstring 及上下文）。

```powershell
python ops/audit/code_fingerprint.py check     # code-changed 必须只含有意改动
python ops/audit/verify_no_code_loss.py        # 退出码 0 = 无可疑文件
python ops/audit/comment_audit.py              # 六类计数全 0 (import 组 1 条已知误报除外)
python ops/audit/check_line_endings.py         # CRLF 文件数 = 0
```

> **已知误报 1 条**：`src/pybest.py` 模块 docstring 的"用法"示例里含
> `from src import Best`，被 import 组扫描当成真 import。那是文档示例不是代码，
> 不得按此给它加注释（加了会破坏 docstring）。

> **踩坑记录（护栏自身错过三次）**：
> ① 把 docstring 替换成 `Pass` 节点 → "给原本没有 docstring 的函数补 docstring"被误判
> 为代码变更；② `[Pass]` 与 `[]`（函数体只有 docstring 时剥离后）不同形 → 同样误判。
> 修正为"整条删除 + 空体归一化"后才可信。
>
> **完整的踩坑登记册见 `docs/architecture/pitfalls.md`**（2026-10-03 新建）：门禁本体、
> 拆分迁移、数据正确性、资源并发、协议量纲、配置六类。上面这两条只是该册的 §A-2。
> ③ 自动补 import 注释的脚本把 `src/pybest.py` **模块 docstring 内部**的示例 import
> 也插了一条 `#` 注释，破坏了 docstring。教训：**任何自动插注释的脚本都必须先排除
> docstring 区间**（用 AST 取 docstring 的 lineno..end_lineno 再插）。

### 4.6 落地结果（终测）

| 指标 | 结果 |
|---|---|
| 缺失 docstring 的 class/function/method | **0**（此前 135） |
| 非中文 docstring | **0** |
| 无中文说明的 import 组 | **0**（此前 217，含 1 条 §4.5 已知误报） |
| 非中文 `#` 注释（白名单外） | **0**（此前 142） |
| 重复粘贴的注释 | **0**（此前 16） |
| TODO/FIXME 遗留 | **0** |
| AST 指纹 `code-changed` | **0**（103 个文件全比过） |
| 代码零丢失 | **0 / 59** 可疑文件 |
| CRLF 混入 | **0**（修复 11 个） |
| pytest | 569 passed / 22 skipped |
> 另有一次子代理并发写入造成的**真实**损坏 —— `ops/astro_best_cli.py` 一整块分派代码被重复
> 粘贴成 `return 1` 之后的死代码、`docs/diagrams/check_macro_collisions.py` 三个 f-string
> 的 `f` 前缀被删 —— 都是这条护栏抓出来的。它的价值正在于能发现"只改注释"承诺被破坏的
> 那一刻。

**中文注释落地的度量**（`temp/docstring_lang.py` + `temp/comment_coverage.py`）：

- 1360 个模块/类/函数 docstring，**完全不含中文的 = 0**（用 `ast.get_docstring` 精确判定，
  不把 `__all__`/`_EXPORTS` 这类集合里的字符串字面量算成 docstring —— 早先的粗糙口径
  正是因此误报）；
- `#` 注释行 2349/2665 含中文（88%），其余为英文技术标识符行与 `# noqa` 之类标记；
- import 语句 660/853 带中文说明（一个 import 组算一条，覆盖全部 import 组）。

---

## 5. 附录：pybest 打包产物高价值内容还原决策记录

打包产物树（git `6f00efeb^` 可取回，best 分支"Phase 8 扁平化"时整体
删除）与现行 `src/` 做过**函数级清点比对**（脚本 `temp/diff_inventory.py`，历史树取回
脚本 `temp/extract_hist.py`，取回产物在 `temp/pybest0328/`）。逐项判定如下。

### 5.1 已按能力边界加回

| 能力 | 归属 | 理由 |
|---|---|---|
| `Best.close()` / `__enter__` / `__exit__` | `src/pybest.py` | `Best` 自持挂了 HTTPAdapter 的 `requests.Session`，原先**无任何释放路径**；MCP server 与批处理脚本反复构造客户端会泄漏 socket。 |
| `BestClient.close()` / `__enter__` / `__exit__` | `src/client.py` | 同上；只关自己的 session，不波及其他客户端共享的 `BestAuth`。 |
| `BestAuth.close()` / `__enter__` / `__exit__` | `src/client.py` | 同上，认证会话自持连接池。 |
| `_normalize_row` + `_fetch(normalize=...)` | `src/pybest.py` | **修复诚实性缺陷**：`Best.cone_search` 的 docstring 一直承诺 "List of dicts with ra, dec, magnitudes"，实际返回 `ps1_ra` 等原始行，按文档取 `row["ra"]` 直接 KeyError。 |
| `Best.describe_columns()` / `BestClient.describe_columns()` | `src/pybest.py` / `src/client.py` | 查询前的列内省（IVOA TAP_SCHEMA 语义）。旧 docstring 声称"从表单页抓取"而实现只读静态表 —— 已改为诚实表述。 |
| `BestProcessor`（`deduplicate` / `bright_sources` / `band_summary`） | `src/core/source_postprocess.py`（新文件） | 现行 `src/` 无任何等价实现。`deduplicate` 用真球面 haversine 距离，并保留上游两个关键修正：坐标缺失/越界的行**必须保留**（不当成 (0,0) 静默丢弃）；容差必须有限非负。 |
| `DownloadCheckpoint.list_jobs()` | `src/scripts/checkpoint.py` | 人工复核面：批任务中断后一眼看到"有哪些任务可以接着跑"，不必翻 `.checkpoints/` 目录。只读文件名不解析内容，写坏的文件不让复核面整体失效。 |

配套回归：`test/unit/pipeline/test_processor.py`（24 项）+
`test/unit/audit_round/test_restored_surface.py`（25 项）。

### 5.2 判定为「不需加回」

| 旧能力 | 判定理由 |
|---|---|
| `BestSource.to_flat_dict` | 现行 `to_dict()` = 原始行 + 解析字段 + 质量元数据，语义已覆盖且更全。 |
| `serialization._is_missing` / `_is_string_column` / `sanitize_csv_value` / `sanitize_csv_text` | 已由 `src/tap/formats.py::convert_table_rows` 与 `src/csv_safety.py::sanitize_cell` 承接；后者还多处理 TAB/CR 前缀，是超集。 |
| `BestConfig`（`__post_init__`/`from_yaml`/`load`） | 现行 `src/scripts/config.py::AstroBestConfig` 已实现且保留 `BestConfig` 别名；清点脚本按类名比对产生假缺失。 |
| `BestRAGEngine` | 现行 `rag/astro_rag.py` 已承接，同样为改名导致的假缺失。 |
| `NADCOAuthClient` 等 15 个符号 | 现行 `src/auth/nadc_oauth.py` 是其演进版（多出 TokenStore 0600 缓存、登出、手动粘贴兜底），按名比对为假缺失。 |
| `client._build_filter_rules` | filterRules 第二约束源已按 P1-4 删除（live 实证冗余，且会把 `greaterequal` 合并成 `greater`）。 |
| `client._parse_csv_text` / `_detect_catalog` / `_count_url` / `_catalog_field_at` / `_get_csrf` | 已分别由 `protocol.parse_csv_rows` / `resolve_catalog` / `count_sqlid` / `qualify_column` 承接或按死代码删除。 |
| `_parse_retry_after` | 重试已收敛为**唯一一层**（session 的 `HTTPAdapter`，`respect_retry_after_header=True`）；再留一个手工解析器就是第二层。 |
| `Best.search(adql)` / `Best._get_tap_client` | TAP 直通属 README 已排期的 P1-9 双入口合并事项；现在加回去会扩大双副本分歧。 |
| `Best.login` / `begin_login` | 登录面现行落在 `BestAuth.login`（Django 会话）与 `src/auth/nadc_oauth.py`（OAuth）；`Best` 单类经 `token` 参数接入，不重复造第三个入口。 |
| `Best.tap_query` | 用正则把 ADQL 猜成表单查询的"假 TAP"，与现行 `src/tap/` 真网关路线冲突，且其自身 docstring 已承认 "NOT a real TAP endpoint"。 |
| `Best.sql` | 上一轮已按用户批准删除（无实现的占位）。 |
| `scripts/repair.py`（`diagnose_connection_error` / `auto_fix_query`） | 纯字符串启发式；`auto_fix_query` 的 `SELECT*→SELECT *` 一类替换会篡改用户查询文本，属有害"便利"。 |
| `scripts/tool.py`（`retry` / `degrees_to_hms` / `degrees_to_dms` / `mag_to_flux` / `flux_to_mag`） | 上一轮已按用户批准删除：`retry` 零生产调用且与"唯一重试层"架构结论矛盾；坐标格式化零引用；Pogson 换算只被自家测试消费。 |
| `scripts/guards.py::load_json` / `to_dataframe` | 随 pandas 依赖移除一并删除（零依赖传输层）。 |
| `services/server.py`（38 符号：FastAPI 路由、请求校验器、暴力破解防护、限流器） | 多用户 Web 服务面，超出本 skill 能力边界（本地单用户 CLI + MCP stdio；README 明确 no deploy）。其输入校验职责已由 `src/scripts/guards.py` 的 `validate_coordinate`/`validate_search_radius` 与 `protocol.normalize_sqlid`/`resolve_catalog` 承接。 |
| `services/async_best.py`（16 符号：`AsyncBestClient`） | 引入 asyncio 会形成第二套并发模型；现行并发已由 `ThreadPoolExecutor`（crossmatch）与 download_manager 承担，且传输层遵守零依赖。 |
| `services/download_service.py`（43 符号：作业注册/ETA/错误分类/批量监控） | 已由 `src/download_manager.py` + `src/downloader.py` + `src/download_progress.py` + `src/task_log.py` 承接；ETA 在 `ProgressRecord.eta_sec`，错误分类由 `BestQueryResult.error_code` 类型化承担。 |
| `services/auth_store.py`（23 符号：SQLite 用户/API Key 存储、bcrypt） | 多用户服务端存储，超出本地单用户边界；令牌缓存职责由 `src/auth/nadc_oauth.py::TokenStore`（0600）承接。 |
| `cli.py` 的 `register` / `whoami` / `key` / `serve` 子命令及 `_api_json` / `_server_url` / `_add_catalog_option` / `_add_format_option` / `CliError` | 均为服务端多用户面的附属；现行 `python -m src` 的 cone/download/crossmatch/catalogs/info/doctor 已覆盖本地用例。 |

### 5.3 与上游的有意分歧（已记录在代码注释中）

`Best.query(normalize=False)` 的默认值与上游的 `True` **相反**：现行 `query` 是 TAP 执行器
的后端（`src/tap/executor.py` 调 `self.best.query(...)`），其结果进入
`tap/formats.convert_table_rows` 的按列类型推断；归一化追加的 `magnitudes` 字典会被
`str()` 成 `"{'g': 19.4}"` 当字符列写进 VOTable，污染科学消费端的类型。人工调用方需要
通用键时显式传 `normalize=True`。

---

## 6. 附：本轮注释复核发现的问题（已核实）

> **清偿状态：§6.1 的 34 条（A1-A5 / B1-B6 / C1-C2 / D2 / E2-E10 / F1-F3 /
> G1-G3）已全部修复，每条配回归测试；D1/D4/D5 与 H1-H7 在更早轮次已修。**
> 下文保留原始问题描述作为「当时发现了什么」的记录，逐条处置见 §6.4 清偿台账。

以下问题由注释补充过程逐行读码时发现并核实。本轮只做注释、不改代码，故登记待办而不
顺手修——每一条都需要配套回归测试，属独立变更。

### 6.2 本轮已修（用户批准"修复裁定"）

| # | 问题 | 修法 |
|---|---|---|
| H1 | `ToolBox.__init__` 传入 `src.pybest.Best` 时，在 `cone_search` 之后访问 `result.success` 炸出 `AttributeError: 'list' object has no attribute 'success'` —— 错误信息完全指不到"传错了客户端"这个根因 | 构造期加 duck-typing 判别（查 ToolBox 真正依赖、而 `Best` 不具备的 `fetch_page`/`resolve_name`），传错即 `TypeError` 并指名两种客户端的返回类型差异。回归 `test/unit/ai_tools/test_ai_tools.py::TestToolBoxClientContract` |
| H2 | 两个重试回归补 `urllib3.connectionpool.HTTPConnectionPool.ResponseCls`，而 urllib3 2.x 已删除该属性（响应构造下沉到 `HTTPConnection.getresponse`），`mock.patch.object` 直接 `AttributeError` —— 两个用例在 urllib3 2.x 环境**恒红** | 改为不再依赖该属性（`_make_request` 直接返回真实响应即可计数），并在 docstring 记录 urllib3 1.x/2.x 的差异 |
| H3 | `BestDownloader._save_result` 的 VOTable 把全部列写成 `datatype="char"`，无 unit | 见 §9.4 |
| H4 | 未知输出格式静默回落 JSON 并改扩展名 | 见 §9.4 |
| H5 | 星等列单位只判 `endswith("mag")`，漏 `ps1_rpsf`/`u_pstotal` 一类 | 见 §9.4 |
| H6 | 标识符列（`*_id`）被按取值推断成数值列 | 见 §9.4 |
| H7 | TSV（站点 `output.fmt=txt` / 人工另存）无法解析 | `protocol.parse_csv_rows` 增加表头行分隔符判别，见 §9.4 |

### 6.3 temp/ 问题文档的未决项（汇总，来源见各文档）

`temp/boundaries_2_4_5_deep_dive_2026-09-27.md` 的"仍待办"三条，逐条核对现状：

| # | 待办 | 现状 |
|---|---|---|
| T1 | 双副本合并（`Best` vs `BestClient`）：README 排二期 | **仍未做**。同文档实测：两套 API 共有方法仅 5 个，其中 `cone_search`/`crossmatch_batch` 的签名与返回类型都不同（`Best` → `list[dict]`，`BestClient` → `BestQueryResult`）。H1 的类型防线是把这条边界的**症状**挡住，根除仍靠合并 |
| T2 | fits 分支修复待复验（本机无 astropy） | **已复验**：`serialization.write_fits` 与 `test/unit/client/test_single_class.py::test_download_fits_mocked` 都在 astropy 可用时走真实 FITS 写出；astropy 缺失时抛带安装提示的 `RuntimeError`。两条下载路径（`Best.download` 与 `BestDownloader._save_result`）现已都支持 fits |
| T3 | `ToolBox` 类型收口 | **已修**，见 H1 |

`temp/ai_ready_baseline/ISSUE-LIST.md`（37 项）的状态已大面积过时：P0-1/P0-2/P0-3、
V-2/V-3/V-4、P1-4（filterRules 移除）、P1-5（分页排序非确定）在该轮次
已修并记录于 `references/site-endpoints-and-interactions.md` §6bis。**该文档原样
提升为 references 会把已过时状态变成正式文档区的错误信息源** —— 处置见 §9.2。


| # | 位置 | 问题 | 建议 |
|---|---|---|---|
| A1 | `src/scripts/best_crossmatch_pipeline.py` 的 `crossmatch_coords` / `crossmatch_with_gaia` / `crossmatch_with_ps1`，以及 `src/scripts/best_multiband_export.py` 的 `export_multiband_photometry` | 每次调用都 `BestClient()` 新建会话，未走 `best_cone_search.py` 的 Q-18 模块级共享实例（`_SHARED_CLIENT`）。Q-18 的修复理由是"公开函数每次新建 BestClient 会泄漏 session"，此处与已修结论不一致 | 复用同一惰性共享 client（或显式注入），与 Q-18 对齐；`batch_crossmatch` 已是"一批一个 client"的正确形态，可作参照 |
| A2 | `src/scripts/best_multiband_export.py::export_multiband_photometry` | `fn = f"mbp_{source_id}_{band or 'all'}.{output_format}"`：`output_format="txt"` 时扩展名是 `.txt`，内容却走 `to_json`（只有 `"csv"` 走 `to_csv`，其余一律 JSON）——扩展名与内容类型不符 | 白名单化 `output_format`（只接受 `csv`/`json`），非白名单值显式报错而非静默按 json 写 |
| A3 | `src/auth/nadc_oauth.py::TokenStore.save` | `os.open(..., O_CREAT, 0o600)` 只对**新建**文件设权限；文件已存在时不会修正既有权限位，旧文件可能仍是 0644 | 保存后显式 `os.chmod(path, 0o600)`，或先 unlink 再建 |
| A4 | `src/scripts/guards.py::to_csv` | `records` 为空列表时写出 0 字节文件（无表头）——"空导出"与"写出失败"在下游不可区分 | 空列表仍写表头（或用 `records[0]` 的键集推头），并在文档中定义空导出语义 |
| A5 | `src/scripts/config.py::AstroBestConfig.load` | `cls(**config.__dict__)` 重实例化会重跑 `__post_init__`，env 覆盖执行两遍（幂等，非 bug；`tap_url` 别名归一也跑两遍） | 无需修；如需澄清可在 docstring 注明"重实例化是故意的，用以保证 env 优先于 YAML" |

> 备注：A1/A2/A3/A4 均为本轮之前就存在的行为，不是注释补充引入的。

### 6.1 本轮新发现（并行注释执行者逐行读码上报，主控已复核关键项）

同样不在本轮动手 —— 每一条都需要配套回归，属独立变更。

**下载链路（`src/download_*.py` / `src/download_manager.py`）**

| # | 问题 | 影响 |
|---|---|---|
| B1 | `PreciseDownloadJob` 无法取消：`_run_precise → run_precise_download` 的页回调不调用 `_check_cancelled`，且函数签名没有取消回调参数 | `cancel()` 置位后 precise 任务仍跑到自然结束，终态记 `done` 而非 `cancelled`（region/sqlid 每页都查取消标志） |
| B2 | `FileJob` 取消后报 `failed` 而非 `cancelled`：`pybest.download_file` 取消时 `return None`（不抛 `JobCancelledError`），`_run_file` 对 None 一律 `raise RuntimeError` | 网络失败与用户取消返回的 None 无法区分，调用方看到同一条错误 |
| B3 | `precise_output_file` 唯一性只到（星表, ID 数）粒度：同星表同 ID 数的两个并行任务生成同名输出，经 `_save_result` 原子写互相 `os.replace` 覆盖 | 原 docstring"防并行覆盖"名不副实 |
| B4 | `DownloadManager.resume` 不对称：region/sqlid 委派 `resume_job` 原地续传（返回原 job_id），file/precise 走 `self.submit(job)` 生成新 job_id | 旧进度记录停留在非终结状态，调用方跟踪旧 id 永远等不到终态；重复 resume 无幂等保护 |
| B5 | `download_region` 对 `catalog="std"` 走组展开分支时**不透传 job_id**，成员 checkpoint 用自动生成的键 | `resume(job_id)` 抛 `FileNotFoundError`（断点实际存在于成员自动键下）；同参数 std 并行下载还会撞同一成员断点键 |
| B6 | `ProgressStore.list_jobs` 用 `glob("*.json")`：若 `output_dir` 与 `progress_dir` 同目录，provenance sidecar（`<name>.json.provenance.json`）会被扫成伪 job_id | 默认配置不触发，属边缘配置 |

**RAG（`rag/astro_rag.py`）**

| # | 问题 | 影响 |
|---|---|---|
| C1 | `DOMAIN_BOOST` 键表与实配值脱节：`load()` 传给 `entry.source` 的是 `inner.name`（带 `.yaml` 扩展名），而 `DOMAIN_BOOST` 的键是无扩展名领域词，且 5 个现有文件名词干与键表无一匹配 | `_bm25` 的领域加权通道对当前知识库**实际永不触发**（死代码风险）。修键表或改传 `stem` 皆可 |
| C2 | 模块 docstring 含 "Master Plan v8.0" 版本样式字符串（指计划文档版本，非包版本） | 与禁版本号铁律字面冲突 |

**评测与门禁（`evals/`）**

| # | 问题 | 影响 |
|---|---|---|
| D1 | `--mode audit` 时 `main()` 把 scenarios/cases 汇总预置为 `rate=1.0`，`evaluate_rubric` 于是把 correctness/determinism/gate_compliance 全按 1.0 计 | 纯审计模式可报满分而零行为评测证据，blocking 也不触发（fail-open 气味） |
| D2 | `VERSION_MARKER_RE` 只匹配行首（可选空白后）的 version 键 | YAML 列表项 `- version: x` 与带引号 `'version':` 漏杀，禁版本号铁律有两个模式盲区 |
| D3 | `Auditor` 基类默认 `broken_samples()` 返回 `{}`、`check_rejects()` 返回 `True` | 未来新增审计器忘配反证夹具会零反证静默通过，注册表无强制校验（现有六个都已配齐） |
| D4 | `run_audit()` docstring 写"运行六审计器 + docstring 维度"，实际 docstring 维度由 `main()` 调 `run_docstring_dimension()` 跑 | 纯文档范围超出实际 |
| D5 | `KnowledgeAuditor.REQUIRED_TOP` 定义了但 `run()` 从未使用；`TestsAuditor.run` 对每个测试文件读两遍（两个 rglob 循环） | 死常量 + 重复 IO |

**测试层（`test/`）**

| # | 问题 | 影响 |
|---|---|---|
| E1 | 6 个 `test_gen_*` 文件头部声明"托管命名空间，请勿手改；重新物化由生成器统一管理"（产物是 `scripts/refactor/materialize_tests.py`） | 本轮加的中文注释会在下次重新物化时被整体覆盖。**建议把注释模板固化进生成器**，否则注释寿命只有一次物化周期 |
| E2 | `test/unit/meta/test_environment_lock.py` 的 `STDLIB` 白名单缺 `tomllib`/`zoneinfo`/`graphlib`/`__main__`/`_thread`/`asyncio` | `src/` 将来 import 其中任一个会被判"imported but undeclared"而 fail-closed（误报） |
| E3 | 同上，`_declared_packages` 正则 `^\s*-\s*([a-z0-9_\-]+)` 抓 `environment.yaml` | 若 dependencies 段出现 `- pip>=23` 这类带比较符写法，抓到的名字会失真（当前仅靠 tooling 白名单兜住 pip/python） |
| E4 | `test/unit/meta/test_gen_ledger.py` 在 `ASSET-TRUTH-LEDGER.json` 不存在时只断言目录存在，不校验任何计数 | G1 资产守恒在独立交付模式下是空门禁（已知的平滑降级设计，复核者应知晓盲区） |
| E5 | `test/conftest.py` 的 `spec_section` / `mock_skill_config` 两个 fixture 无任何测试消费；`contracts/` 与 `meta/` 下 6 个文件各自定义了本地同名 fixture | 死代码 + 重复定义 |
| E6 | `test/integration/test_integration.py::test_no_sqlid_detects_no_results` 只断言 `"No results" in html`，未真正走 `_execute_query` 的 HTML 检查路径 | 防御力弱于用例名暗示 |
| E7 | `test/integration/test_download_feature_integration.py::test_parallel_download_multiple_catalogs` 的替身 `_fake` 是死代码（patch 实际用 `_fake2`），且引用不存在的 `_catalog` 参数 | 死代码 + 误导 |
| E8 | `test/live/test_live_download.py::test_download_by_constraints_from_std` 用例名与 docstring 说 "std"，代码实际请求 `catalog="ps1"` | 疑似复制粘贴遗留，名字误导（std 是导航组，/q 不接受） |
| E9 | `test/unit/ai_tools/test_mcp_server.py` 用 `Path(__file__).resolve().parents[3]` 硬编码目录深度，且在 import 期改写 `sys.path` | 文件移动即失效；sys.path 改写会泄漏到整个 pytest 会话 |
| E10 | `src/__main__.py` 的 `--auth-pass` 走明文命令行参数 | 会进 shell history / `ps` 输出；源码零字面量纪律满足，但与文件头"凭据走 env/getpass"声明有运维层面差距 |

**文档生成脚本（`docs/diagrams/`）**

| # | 问题 | 影响 |
|---|---|---|
| F1 | 五个脚本硬编码绝对路径：`<USER_HOME>\...`（builder）、`<TOOL_ROOT>\draw.io.exe`（渲染器）、`<SKILLS_ROOT>\...`（输出目录） | 换机器必然失效，未参数化 |
| F2 | 预存在 ruff 违规（`docs/` 在 `extend-exclude` 中故 `ruff check .` 不报）：`check_macro_collisions.py` 4×F541、`audit_local.py` E402、`gen_best_macro_flowchart.py` 2×F401 / E402+I001 / 2×F841 | 应作为独立的一次代码清理提交处理 |
| F3 | `ops/astro_best_cli.py` 与 `ops/cloud_modelscope/dispatch.py` 头部示例仍写 `python scripts/...`，实际文件在 `ops/` 下 | 过期路径，误导调用方 |

**数据模型（`src/models/__init__.py`）**

| # | 问题 | 影响 |
|---|---|---|
| G1 | `BestSource.from_row` 从不填充 `ra_err`/`dec_err`/`parallax`/`parallax_err`/`fwhm`/`quality_flag` 六个字段 | CSV 有 `ps1_parallax` 等列时字段仍停留在默认值，真实值只在 `raw_data`；下游直接读 `obj.parallax` 会静默拿到 None |
| G2 | `DownloadInput.bands` 默认含 `"clear"`，不是任何星表 `CATALOG_MAG_COLUMNS` 里的波段标签 | 该默认清单若被透传给 `protocol.magnitude_column()` 会抛 `ValueError` |
| G3 | `BestResultSet` 默认 `handoff` 把 `next_skills` 硬编码为 `["astro-catalog", "astro-clean"]` | 跨 skill 路由写死在模型默认值里，envelope 契约变更时会静默漂移 |

### 6.4 清偿台账（逐条修法 + 回归位置）

| # | 修法 | 回归测试 | 提交 |
|---|---|---|---|
| A1 | 模块级惰性共享 client（Q-18 同形态）+ 三入口尾参 `client=None` 注入 | `test/unit/scripts/test_best_crossmatch_pipeline.py` 4 例 | `3bf61494` |
| A2 | `_OUTPUT_FORMATS` 白名单，非白名单函数首行 fail-fast 抛 ValueError | `test/unit/scripts/test_best_multiband_export.py` 3 例 | `3bf61494` |
| A3 | 保存后显式 `os.chmod(path, 0o600)`（docstring 说明为何优于 unlink） | `test/unit/scripts/test_nadc_oauth_permissions.py` 2 例 | `3bf61494` |
| A4 | `to_csv` 新增 `fieldnames` 形参；空导出 = 只写表头，无 fieldnames 显式抛错 | `test/unit/scripts/test_io_empty_export.py` 2 例 | `3bf61494` |
| A5 | **无需修**（重实例化是保证 env>YAML 优先级的构造手段，幂等无害），仅补 docstring | — | `3bf61494` |
| B1 | `run_precise_download` 增 `cancel_check` 参数，页回调首行查取消 | `test_download_cancel_semantics.py::TestPreciseCancel` | `37de2c27` |
| B2 | `_run_file` 对 None 先查取消标志再分流（取消 → `JobCancelledError`） | `test_download_cancel_semantics.py::TestFileCancel` 2 例 | `37de2c27` |
| B3 | 自动名加 `job_id or uuid4` 唯一后缀，docstring 与行为对齐 | `test_download_precise.py` 3 例 | `37de2c27` |
| B4 | `_spawn` 共用接线 + resume_spec 提交即落盘 + file/precise 同 id 原地重跑 + 幂等 | `test_resume_symmetry.py::TestFilePreciseResumeSymmetry` 6 例 | `37de2c27` |
| B5 | 组展开透传 job_id + 组级 checkpoint + `resume_job` 组分支 | `test_resume_symmetry.py::TestStdGroupResume` 3 例 | `37de2c27` |
| B6 | `list_jobs` 内容校验（stem 与文件内 job_id 一致） | `test_download_progress.py::test_list_jobs_ignores_provenance_sidecars` | `37de2c27` |
| C1 | 键表换 5 个真实文件词干 + `load()` 改传 `inner.stem`（死代码本体删除） | `test/unit/meta/test_rag_domain_boost.py` 6 例 | `3aa520e4` |
| C2 | **核实已是清净状态**（grep 0 匹配 + git 史证），无需修改 | — | `3aa520e4` |
| D2 | 正则容许「可选空白 + 可选列表项破折号 + 可选键引号」前缀 | `test_eval_runner_dimensions.py::TestVersionMarkerCoverage` 7 例 | `b43c9102` |
| E2 | STDLIB 白名单补 6 项 + `_is_interpreter_provided()` 交叉核实 | `test_environment_lock.py::TestStdlibWhitelist` 2 例 | `b43c9102` |
| E3 | `_declared_packages` 正则改裸包名抽取 | `TestDeclaredPackageNameExtraction` 5 例 | `b43c9102` |
| E4 | 降级路径显式登记 `DEGRADE_LOG` 并断言（未改成硬失败） | `test_gen_ledger.py::TestLedgerDegradedPath` 2 例 | `b43c9102` |
| E5 | 删 conftest 2 个死 fixture + 5 个零消费者本地副本（保留有消费者的那份） | grep 无消费者证据 | `b43c9102` |
| E6 | 真走 `_execute_query` + 换措辞页面复跑（不依赖 "No results" 字样） | 同名用例重写 + 有牙齿反向验证 | `b43c9102` |
| E7 | 删死 `_fake` 与 `kw["_catalog"]` 死引用，`_fake2` 更名 | 既有 11 passed | `b43c9102` |
| E8 | 改名 `_from_ps1` 并说明 std 为何不可用（导航组，`/q` 不接受） | live skip 纪律不变 | `b43c9102` |
| E9 | `_locate_skill_root()` 锚点定根 + `_ops_on_sys_path()` 可还原注入 | `TestSkillRootLocation` 3 例 | `b43c9102` |
| E10 | 口令改 env(`ASTRO_BEST_PASSWORD`)/getpass，删 `--auth-pass` | `test_release_regressions.py` 5 例 | `b43c9102` |
| F1 | 五脚本统一 env > argv > 原默认值（本机零配置仍可跑） | 五脚本本机实跑 | `b43c9102` |
| F2 | 4×F541 / E402 / F401+I001 / 2×F841 全真修（不靠 noqa） | 显式路径 ruff 清零 | `b43c9102` |
| F3 | 头部示例路径改 `python ops/...` | grep 无残留 | `b43c9102` |
| G1 | `_ASTROMETRIC_COLUMNS` 真实列名映射（锚定 `CATALOG_COLUMNS`） | `test_astrometric_fields.py` 10 例 | `3aa520e4` |
| G2 | 默认 bands 去 `"clear"`，与 templates/best-config.yaml 同口径 | `test_model_defaults.py` 4 例 | `3aa520e4` |
| G3 | `next_skills` 从 manifest `redirects` 派生，读不到降级空清单（不回退写死） | `test_model_defaults.py` 6 例 | `3aa520e4` |

**执行期发现并已处置的三处计划外问题**：

1. **evals `download_resume` 探针与 B4 冲突**：探针原断言 `new_id != job_id`，依据是
   "resume 必须是新任务否则断点历史被覆盖"。B4 修复后该依据不成立——旧行为下旧进度
   记录反而停留在非终结态，断点历史审计由进度记录本身承担（它被推到终态而不是被
   遗弃），不需靠"换 id"保留。已按新语义改写为「原地续传 + 幂等」并在 docstring 记录
   裁定理由。这是 B4 修复后 evals 从 25/25 掉到 24/25 的唯一原因。
2. **`src/client.py` 的不可拆论证有一条实测不成立**：原文称"薄壳只省实现体不省签名+
   docstring，额度大幅缩水"。实测 `_fetch_sqlid_data`(141 物理行) 的委派壳仅需约 12 行，
   净省约 129 行，且 `patch.object(client, "_fetch_sqlid_data")` 在留壳后依然有效。
   已改为如实表述并登记为「已论证的例外」而非「待修」，见 §3.2。
3. **G1 台账不需要 relock**：四类计数全部 ≥ locked 基线（tests 983/956、
   templates 411/411、evals 904/904、contracts 1003/1003），钩子通过；动治理工件
   收益有限，登记为观察项。

---

## 7. 版本号清理记录（禁版本号铁律）

按 README 治理规则 3「全仓不得出现发布版本号」做了一次全仓扫描
（脚本 `ops/audit/version_scan.py`，`checked=181` 个文件）。扫描器分两类报告：

**A 类 —— 明确违规，已清除（71 处）**

| 模式 | 处置 | 处数 |
|---|---|---|
| `Master Plan v8.0` | → `Master Plan`（计划书版本号，明确违规） | 47 |
| `pybest-0.3.2.8`（独立提及） | → `pybest 打包产物 (git 6f00efeb^ 可取回)`（去掉版本号但保住 git 追溯锚点） | 22 |
| 外部站点首发版本 `v1.0.0` | → 去掉字面量、保留事实（"2025/05/20 首发"） | 2 |

**B 类 —— 经裁定保留（不是本 skill 的发布版本）**

| 模式 | 保留理由 |
|---|---|
| IVOA 规范的 XML 命名空间版本：`VOTable v1.3` / `UWS v1.0` / `VOSI v1.0` / `VODataService v1.1` | 协议常量。`version` 与 `xmlns` 必须同代，删了会直接破坏 VOTable/UWS 的 XML 序列化与路由 |
| `references/site-endpoints-and-interactions.md` 里的真实路径 `04-collection/best/.artifacts/package-stage-0.3.2.8/pybest-0.3.2.8/` | 文件系统路径需逐字符准确才能取回历史树；这是检索指引不是版本声明 |
| `src/pybest.py` 注释里"旧实现 `version=\"1.4\"` 配 v1.3 namespace" | 描述历史缺陷的必要上下文（版本不匹配正是当时的 bug） |
| `CHANGELOG.md` | 规则 3 明确豁免的变更历史载体 |

**仍需跟进（不在 astro-best 边界内）**：生成器
`<SKILLS_ROOT>\scripts\refactor/common.py:273` 与
`scripts/refactor/materialize_tests.py:34` 仍在产出 `Master Plan v8.0` 字样，
下次重新物化会把该字符串带回 `contracts/`、`templates/`、`evals/cases/` 与
`test/unit/{contracts,meta}/test_gen_*`。这两个文件在 monorepo 根、不属于本 skill，
需单独报批后修改。

**补扫发现并修复**：`references/site-endpoints-and-interactions.md:183` 的 git
路径里残留两处 `0.3.2.8`（`package-stage-0.3.2.8/pybest-0.3.2.8/`）——这是上一轮清理的
漏网。已改为中性表述「pybest 打包产物树（git `6f00efeb^` 可取回）」，追溯锚点保留。
同时修掉 `ALGORITHM-SPEC.md:112` 与 `known_issues.yaml:53` 的「打包产物 pybest 打包产物」
重复语病。

---

## 8. S4 Legacy 定位清除记录（用户已批准）

### 8.1 为什么要清

原定位是「S4 Legacy —— 只做兼容，不作为新任务 PRIMARY」，大仓
`docs/routing/MASTER-ROUTING.md` 据此把「BEST 数据」场景 redirect 到 `astro-catalog`。
但 **astro-catalog 主理 SIMBAD/VizieR/Gaia/TNS 通用检索，完全不具备 BEST 访问能力**
（BEST 站点无 TAP/ADQL/REST-JSON 端点，只有 Django form 两阶段协议）。
这条 redirect 是**路由缺陷**：会把唯一能查 BEST 的任务导向一个查不到 BEST 的 skill。

事实基线（本轮之前已达成）：569 项单测通过、evals 25/25 场景、6 审计器 0 findings、
MCP selftest 13/13、真实 REST 全链路联通实证。这不是"只读历史能力"的状态。

### 8.2 用户裁定

「全去 Legacy 化，改为主理定位」；`strength: S4` 与 `role: Legacy` 两个机器字段
**暂留原值**，避免与大仓 `SKILL-STRENGTH-MODEL.md` / `MASTER-ROUTING.md` 的 S4 定义
冲突（改字段属跨仓治理变更，需单独报批）。

### 8.3 已改文件（叙事层，不动机器字段）

| 文件 | 改动 |
|---|---|
| `SKILL.md` | frontmatter description/role/out_scope 重写为「BEST 数据源主理」；标题、引言、重定向表→委派表、兼容 API 快照→API 快查、组件地图、完成自检全部更新；治理铁律新增第 5 条（注释必须中文）与第 6 条（400 行预算） |
| `manifest.yaml` | 头部说明去掉 Legacy/S4 措辞；`compat_mode` 注释改为 data-source 主理声明 |
| `architecture.md` | §0「兼容模式声明 (S4 Legacy)」整节重写为「主理定位声明」 |
| `README.md` | 标题与 `docs/` 能力行去掉 S4 Legacy 措辞 |
| `agents/openai.yaml` | statement 去掉「只做兼容，不作为新任务 PRIMARY」 |
| `static/core/stance.md` | 首行角色描述去掉 Legacy/S4 |
| `contracts/io-contract.md` | strength 行补「主理数据源」说明 |
| `contracts/oauth.contract.yaml` | 「S4 兼容」注释改为主流定位说明 |
| `references/skills-spec.local.yaml` | delegates 注释口径对齐 |
| `templates/report_template.yaml` | strength 注释中性化 |
| `weights/README.md` | 「现状声明 (S4 Legacy 兼容层)」重写 |
| `src/auth/nadc_oauth.py` | 模块 docstring 的「S4 兼容」措辞改为主流定位 |

### 8.4 越界未改（只报告）

| 文件 | 内容 |
|---|---|
| `G:/tw/twskills/docs/routing/MASTER-ROUTING.md:20` | 「BEST 数据 → `astro-catalog`（redirect: astro-best → S4）」——**建议改为 PRIMARY `astro-best`** |
| `G:/tw/twskills/docs/routing/MASTER-ROUTING.md:19` | 「星表查询」支持 skill 列仍标 `astro-best (legacy_deprecated)` |
| `G:/tw/twskills/docs/system_architecture/SKILL-STRENGTH-MODEL.md:14` | S4 = Legacy 定义表 |
| `G:/tw/twskills/docs/system_architecture/build.md:330` | S4 行列举 astro-best |
| `G:/tw/twskills/SKILL.md:56` | 强度矩阵 S4 行 |

---

## 9. 上游引进文件规则检测结果

本轮从 pybest 打包产物加回的内容（§5.1 七项 + 三个新文件）逐条过了本仓规则：

| 检查项 | 结果 |
|---|---|
| 禁版本号 | 通过。加回代码不含任何发布版本号；`src/core/source_postprocess.py` 的 `_best_magnitude` 哨兵 −900 是数值阈值不是版本 |
| 文件树 SSOT | 通过。`python ops/verify_tree_integrity.py --write` 已重生成（243 条目） |
| G1 资产守恒 | 通过。新增 2 个测试文件使 `tests` 计数上升，未触及任何 locked_counts 下限 |
| 注释全中文 | 通过。`src/core/source_postprocess.py` 与两个测试文件全部函数有中文 docstring，import 组有中文说明 |
| 400 行预算 | 通过。`src/core/source_postprocess.py` 净代码行远低于上限 |
| 无散落临时文件 | 通过。历史树取回产物只在 `temp/pybest0328/` |
| 依赖零新增 | 通过。`BestProcessor` 只用标准库 `math` |

### 9.1 references/ 与 rag/knowledge/ 合规体检（15 份逐份读 + 代码核验）

**R1 版本号**：唯一违例已修（§7 末段）。IVOA 协议标准名（TAP 1.1 / ADQL 2.1 /
OAuth2.0 / JSON-RPC 2.0）、星表数据发行代号（DR3/DR4/DR11）、DOI/arXiv/卷期页
均裁定保留——删了会破坏协议序列化或文献可追溯性。

**R4 事实错误（8 处，全部已修）**：

| 文件:行 | 原文 | 实际行为 | 修法 |
|---|---|---|---|
| `ALGORITHM-SPEC.md` 超参表 | `REQUEST_TIMEOUT \| 30 s` | `REQUEST_TIMEOUT = 120`（`src/protocol.py`），30 s 只硬编码在 `check_connection` | 拆成 `timeout 120 s` + `check_connection_timeout 30 s` |
| `ALGORITHM-SPEC.md` 超参表 | `page_size \| 50000` | `page_size` 默认 1000；50000 是 `max_rows` | 拆成 `max_rows 50000` + `page_size 1000` |
| `fallback-protocols.md` FB-2 | `BEST_USERNAME`/`BEST_PASSWORD` | 全仓无此二变量；实际是 `BEST_API_USER`/`BEST_API_PASS` + `BEST_API_TOKEN` | 改 env 名（原样配置环境变量永远不生效，FB-2 降级路径不可达） |
| `best-database-guide.md` 端点表 | 回调 `/user/oauth2/login/nadc` | 回调是 `/user/oauth2/callback/nadc`；`/login/nadc` 是发起路由 | 改路由 |
| `best_practices.yaml` 星表选择 | 「九类目录」含 std、gaia_dr3 | 现为 12 张可查表；std 是导航组；gaia_dr3 仅旧别名；缺 4 张 | 更新为 12 id 清单并标注 |
| `pybest-api-reference.md` cone | `.cone(ra, dec, radius)` | 实为 `radius_deg`（度，内部 ×3600 转角秒） | 补参数名与单位——该文档通篇警告角秒/度陷阱却唯此处漏注 |
| `pybest-api-reference.md` BestClient | 签名缺 timeout | 实际有 `timeout=REQUEST_TIMEOUT` | 补上 |
| `skills-spec.local.yaml` algorithms | `module: "astro_best"` | 无此模块；`BestQueryResult` 在 `src/models` | 改 `src.models` |
| `fallback-protocols.md` FB-3 | 「等待 = rate_limit·2^k」 | 基数是独立常量 `RETRY_BACKOFF_S=2.0` 且 urllib3 尊重 `Retry-After` | 改措辞，注明两个常量数值巧合相同 |

**R5 上游残留（已处置）**：

| 位置 | 处置 |
|---|---|
| `references/site-endpoints-and-interactions.md:183` 版本化上游路径 | 中性化为「pybest 打包产物树（git `6f00efeb^` 可取回）」；顺带删「FastAPI 路由」等上游内部描述（R2 2026-10-05 补路径前缀：原文写 `site-endpoints-and-interactions.md:183` 少了 `references/` 段 —— 该文件**确实存在**且 183 行可打开，是「filterRules 冗余」那一行；Q4 检测报告把它判成"从未存在"有误） |
| `ALGORITHM-SPEC.md:112` / `known_issues.yaml:53` 「打包产物 pybest 打包产物」重复语病 | 改为「pybest 打包产物树」 |
| `best-database-guide.md` 「与 pylamost 对比」整节 | **删除**（描述上游姊妹包而非本 skill 能力边界，会误导选型）；留一行说明指向何处可查 |
| `best_practices.yaml` `~/pybest.ini` | 补注「上游 pylamost 惯例的兼容层，不是 BEST 站点要求」；同时修正「下载大文件需 token」与「公开数据面免登录」的口径冲突 |
| `lessons_learned.yaml` BestSkillClient 清华 TAP 门面 | 保留为历史注记（已在 ALGORITHM-SPEC 证为无 A 记录死域名），不呈现为可用能力 |
| `skills-spec.local.yaml` `sql` required 输入字段 | 登记为待办（master-plan 遗留，BEST 上游不执行 SQL）；改契约字段属结构变更，需报批 |

**结构问题（已修）**：`download-playbook.md` §8/§9 编号重复（重排为 8/9/10/11）；
`known_issues.yaml` 死路径 `scripts/cloud_modelscope/dispatch.py` → `ops/cloud_modelscope/dispatch.py`；
`skills-spec.local.yaml` 死引用 `scripts/refactor/spec/skills-spec.yaml`（该文件只在 monorepo 根，本包不可达）改为说明性表述；
`ALGORITHM-SPEC.md` DOI 核验状态节标题残缺（`###` 嵌进正文）重写；
`llms.txt` 尾注「degradation 路径加载」碎片句补完整，并补下载手册入口。

### 9.2 temp/ 文档筛选结果（14 份逐份读）

**结论：无一份可原文照搬进 `references/`**——全部需先去重、去版本号、去绝对路径、
去会话痕迹。按价值分三档：

**值得提炼进 references/（合并而非照搬）**

| temp 文档 | 目标 | 提炼内容 |
|---|---|---|
| `temp/ai_ready_baseline/ANALYSIS.md` | 合并入 `references/ALGORITHM-SPEC.md` | 其两阶段协议白盒与 showcol 双态/total_count/软 404 三大踩坑已被 09-30 版 §1/§5 吸收，**无可增量**；P0-1/P0-2/P0-3/P1-8 已修复，须改述为「已修复」并指向现行行号，否则会成为错误信息源 |
| `temp/boundaries_2_4_5_deep_dive_2026-09-27.md` | 提炼进 `references/ALGORITHM-SPEC.md` 回归锚点 | 三条真 bug 根因有长期价值：① votable 下载静默改名 `.xml` 致 FileNotFoundError；② 光变探针按实例方法调 classmethod 致恒绿零信息量；③ ToolBox 传 Best 在 `result.success` 抛 AttributeError。须去掉验证矩阵数字与「本轮改动清单」会话痕迹 |

**留 temp（有价值但现状不符 references 准入线）**

| 文档 | 理由 |
|---|---|
| `temp/ai_ready_baseline/ISSUE-LIST.md` | 37 项归属分派是最完整病灶索引，但状态已过时（V-2/V-3/V-4 已解除、P0 三项已修、P1-4 filterRules 已移除）。**刷新状态后可提炼为 `references/known-issues.md`**，但需先删「23 个提交未推送」等会话态信息 |
| `temp/ai_ready_baseline/REFERENCES.md` | A/B/C 采信分档 + 文献→结论映射是方法论资产，但与 `rag/knowledge/citations.yaml` 双轨会漂移；建议把分档纪律并入 citations.yaml 注释 |
| `temp/ai_ready_baseline/BASELINE.md` | 三层架构设计草案，含 D-1 待决策与多处待验证 + 易失实测数据 |
| `temp/ai_ready_baseline/OSS-COMPARISON.md` | 中期建议（VO 适配器）已于 09-30 落地为 ALGORITHM-SPEC §6，主体过时 |
| `temp/oauth_deep_dive_2026-09-27.md` | 含绝对路径 `<USER_HOME>\.astro-best\nadc_token.json` 与本机实跑输出，违反 references 准入线；3 条新发现可单独提炼进 `site-endpoints-and-interactions.md` §5 |
| `temp/selfbuilt_python_audit_2026-09-27.md` | 模块清单与 README 文件树重复；含 3 处版本号违规 + 绝对路径 |
| `temp/probe_text.txt` / `temp/catalog_doc.txt` | 官网原文转储，已被 `photometric-systems.md` §2/§3 与 `best-database-guide.md` 逐行镜像吸收；且夹带上游版本号 `Version 1.0.0` |
| `temp/COMMENT_SPEC.md` | 硬性规则已被 README 治理规则与本文 §4 覆盖，无独立长期价值 |
| `temp/diff_inventory.txt` | 机器生成的一次性符号盘点，纯英文标识符，典型易失探针输出 |

**建议删除**：`temp/search_text.txt`（3 行原始站点文本，零信息增量）、
`temp/ai_ready_baseline/llms.txt`（与 `references/llms.txt` 完全重复且为旧草案——
缺「名称解算哨兵」要点、缺「下载与续传」节）。

### 9.3 非违规但易误报（扫描器须知，避免"修坏"）

`catalog_doc.txt` 的 DR3/DR4/DR11/DR1、`photometric-systems.md` 与
`best-database-guide.md` 各表的 DR 系列、`gaia_dr3_18` 等 id —— 均为**星表数据发行
编号/线上 id**，删了就无法指表。`oauth_deep_dive.md` 的 `OAuth2.0`、
`selfbuilt audit` 的 `TAP 1.1`/`JSON-RPC 2.0` —— 协议名，非发布版本。
`citations.yaml` 的 DOI/arXiv/卷期页 —— 文献常量。

### 9.4 格式层重构：`src/serialization.py`

把 BEST 原生输出格式的写出逻辑从 `src/pybest.py` 与 `src/downloader.py`
两条下载路径里抽成单一事实源，顺带修掉三个**已存在的静默缺陷**：

| # | 缺陷 | 后果 | 修法 |
|---|---|---|---|
| 1 | `BestDownloader._save_result` 的 VOTable 把**全部列**写成 `datatype="char"`，无 unit | 数值列被 astropy 读成字符串，科学消费端类型链条整段断裂；`src/pybest.py` 早就修了同一处，`downloader` 漏修 —— 双副本各自的写出逻辑漂移 | 共用 `serialization.votable_document`，按实际取值推断 double/char，ra/dec 补 `unit="deg"`，星等列补 `unit="mag"` |
| 2 | `BestDownloader._save_result` 对 `fits` 等未知格式**静默回落 JSON** 并把扩展名改成 `.json` | 调用方请求 FITS 拿到一个 JSON 文件且无任何提示；下游按 FITS 解析以难懂的格式错误失败，按扩展名判断的调用方以为拿到的是 JSON | `serialization.normalize_output_format` 白名单外一律 `ValueError` 并列出可选值；`fits` 接线到 `serialization.write_fits` |
| 3 | 星等列单位只判 `endswith("mag")` | `ps1_rpsf`/`splus_dr4_u_pstotal` 这类实测列名拿不到 `unit="mag"`，TOPCAT 侧无法做星等换算，且不抛异常 | 后缀集合由 `CATALOG_MAG_COLUMNS` **现场推导**（`serialization.MAGNITUDE_SUFFIXES`），不再有第二份会漂移的清单 |
| 4 | 按取值推断列类型时把**标识符列**也当成数值列 | `ps1_source_id="123456789"` 写成 `double` 后：前导零丢失、超过 2^53 的 id 丢精度、下游按 ID 比较时 `"123"` 与 `123.0` 不再相等 | `serialization.is_identifier_column`（`id`/`_id`/`_ids` 结尾）强制保持字符串 |

另补两项能力：
- **TSV 解析**：`protocol.parse_csv_rows` 增加分隔符判别，**只看表头行**
  （数据行里的逗号会错拆列且不抛异常）。站点的 `output.fmt=txt` 与人工另存的
  TSV 现在都能读。
- **格式全景文档**：`references/data-formats.md`（站点 6 个 `output.fmt` 的处置、
  两阶段分岔、单位陷阱、列类型规则、常见天文格式支持面、编码约定）。

回归：`test/unit/serialization/test_output_formats.py` 43 项
（白名单/类型推断/标识符列/VOTable 类型单位转义/分隔符判别/JSON total 语义）。

> 复测方式：`python temp/format_probe.py` 逐格式走一遍落盘并回读，
> 输出"请求 → 实际落盘 → 能否被标准解析器读回"三段结论。

### 3.13 `ops/audit/comment_audit.py`（已拆分，见下）

**成因**：2026-10-03 两轮各补一类此前完全没有的判据 ——
Q9 `referenced_path_missing`（注释引用的仓内路径必须真实存在）与
Q10 `line_alignment_low`（非平凡语句的逐行对照率）。两类都不是新检查项数量的
线性增长，而是**各带一组独立的判据辅助层**。

**为什么当时不立即拆**：它是 `make audit` 的注释护栏本体，被
`test/unit/meta/test_audit_gate_contracts.py` 以 `sys.path` 注入后**直接 import
其函数**（`analyse_trailing_style` / `analyse_referenced_paths` /
`analyse_line_alignment`）来做反例守卫。拆成多文件要同步改：注入路径、
测试类的 import、以及 `verify_tree_integrity` 的 README 树清单。

**已执行（2026-10-03，经批准）**：按上面的预案把「行范围判定」层抽出 ——
落点 `ops/audit/line_scope.py`（**净 135 行**），`comment_audit.py` 降至
**净 326 行**，两侧都在预算内，本条从登记簿移除。

搬走的比预案多：预案点的是 7 个函数，实际搬走 **14 个**（十一类排除口径的
全部行分类函数 + `multiline_stmt_rows`/`string_const_rows`/`_continuation_flags`
三个被它们调用的助手 + `TRIVIAL_STMT_PREFIX`/`DATA_LITERAL_MIN`/`BRACKET_ONLY`
三个常量）。预案按"七个彼此无依赖的函数"估的行数偏少，因为十一类口径里真正
独立的是少数，多数是互相调用的。

**两处与预案不同，都是踩出来的**：
1. **导入用同目录裸名 `from line_scope import …`，不用 `ops.audit.line_scope`。**
   预案写的是后者，实测在本仓跑不通：本文件既可能被
   `python ops/audit/comment_audit.py` 直跑（此时 `sys.path[0]` 是 `ops/audit/`，
   仓根不在 path 上，`import ops` 直接 ModuleNotFoundError），也可能被单测注入
   `AUDIT_DIR` 后 `import comment_audit` 拉起。两种情况同目录都在 path 上，裸名
   才都成立。
2. **多收敛出一个 `nontrivial_stmt_rows(tree, lines)`。** 原实现把十一类在一个
   表达式里 and 起来，而清单在函数 docstring 与调用点注释里**各写一遍** ——
   已经漂过一次（本处原写"七类"、末尾另有一条"三类不算"，实际是十一类）。
   现在清单只由 `line_scope` 的模块头维护，Q10 分母只此一个来源。

**拆分自身踩的坑（记下来，因为这类错误不会自己暴露）**：迁移脚本按 AST 取
`end_lineno` 后多删了一行"块后空行"，实际那两行是**真代码** ——
`analyse_trailing_style` 与 `analyse_comments` 的 `return findings` 被吃掉，
运行期表现为 `'NoneType' object is not iterable`。发现方式不是肉眼 diff，而是
(a) `ruff` 的 `RET503`（缺显式 return）与 `F821`（未定义名）；
(b) 一条"标注返回非 None 却没有 return 值"的 AST 自查。**搬判据本体时，
先备好这两道机械检查再动手。**

