# download-playbook.md — 下载能力使用向 playbook（智能体怎么用）

> 本文是下载相关能力的**唯一使用向 SSOT**：后台下载、进度显示、并行下载、
> 断点续传、hook 拦截与 ask 纪律、常见需求与常见问题的解法。
> 端点/协议背景见 `site-endpoints-and-interactions.md`；论文引文不在此文
> （在 `rag/knowledge/citations.yaml`）。
> 实现锚点：`src/download_manager.py` / `src/download_progress.py` /
> `src/download_hooks.py` / `src/best_export.py::download_file`。

## 0. 三十秒上手

```python
from src.client import BestClient
from src.download_manager import DownloadManager, RegionJob

mgr = DownloadManager(BestClient())                 # 默认 2 并发, 进度落 .progress/
job_id = mgr.submit(RegionJob(ra=180.0, dec=30.0, radius_arcsec=180))
# ↑ 立即返回: 下载在后台线程跑, 前台可以继续对话
rec = mgr.status(job_id)                            # 或读 .progress/<job_id>.json
if rec["status"] == "blocked":
    ask(rec["hook"])                                # 必须 ask (见 §5)
path = mgr.result(job_id)                           # done 后取落盘路径
```

CLI 等价：`python ops/astro_best_cli.py download start --ra 180 --dec 30 --radius 180`。

## 1. 后台下载模型（前台不阻塞）

| 层 | 机制 | 适用 |
|----|------|------|
| **库内（agent）** | `DownloadManager.submit()` 提交即返回，ThreadPoolExecutor 后台执行 | agent 对话不中断，随时 `status()`/进度文件轮询 |
| **CLI 前台** | `download start` 阻塞并渲染实时进度条（Ctrl-C = cancel） | 人在终端前等待结果 |
| **CLI/GUI 真后台** | 宿主把 `astro_best_cli.py download start` 作为后台任务运行（harness background job / `start-process`） | 终端要干别的；任何进程都可 `download status/progress <job_id>` 读同一进度文件 |

纪律：**下载永不占前台对话**。库内调用一律 submit 后轮询；需要"即问即答"的
小查询（cone_search）才走同步路径。

## 2. 进度显示（CLI/GUI 同源）

- **唯一事实源**：`.progress/<job_id>.json`（原子写，崩溃可恢复）。字段：
  `job_id/kind/status/total_bytes/done_bytes/total_pages/done_pages/speed_bps/
  eta_sec/started_at/updated_at/error/hook/result`。
- **status 枚举**：`queued → running → done|failed|cancelled|blocked`；
  `blocked` = hook 拦截待用户决策（见 §5）。
- **CLI 渲染**：`download progress <job_id>` / `download list`（文本条，
  Windows GBK 控制台自动回退 ASCII `#/-`，不抛 UnicodeEncodeError）。
- **GUI 渲染**：读同一 JSON 自行绘制；`hook` 字段即 ask 卡片内容。
- **库内回调**：`ProgressTracker(callback=...)` 可选订阅（文件仍为权威）。

## 3. 并行下载

- 维度：**区域/星表级**（一次 `submit_all([...])` 多个 RegionJob/SqlidJob/FileJob）。
- 默认并发 **2**（尊重官网礼貌限速 2 s/req；`DownloadManager(max_workers=N)` 可调）。
- 每任务独立 checkpoint + 进度文件；**未指定 output_file 时按
  (星表,ra,dec,半径,格式) 生成确定性唯一名**——并行防覆盖（live 实证：
  同名任务曾互相 `os.replace` 覆盖，已修）。
- 不要页级并行：站点 dbgrid 数据口匿名不可用（2026-09-29 复测为快速软错误，
  见 site-endpoints §6），GET 分页才是取数路径，页级并行无收益。

## 4. 断点续传（两级）

| 级 | 机制 | 恢复单位 |
|----|------|----------|
| 页级（查询下载） | `.checkpoints/<job_id>.json` 存 `sqlid` + `next_page` + `page_size` + `max_rows` + 已取 `sources`（另带 `job_id`/`catalog`/`output_format`/`output_file`；键集见 `src/download_sqlid.py:166`） | 崩进程/断网后 `mgr.resume(job_id)` 或 `BestDownloader.resume_job(job_id)` 从断页继续。⚠ **`page_size` 必须入断点**：分页是绝对偏移且页码与页大小绑定同一量，漏存即从错误偏移起算**静默丢行**（`docs/architecture/pitfalls.md` E-5；`src/download_sqlid.py` 对缺 `page_size` 的旧断点直接抛错而非猜缺省）。⚠ **`sort`/`order` 当前不入断点** —— 它们由 `build_page_url` 按 `catalog` 逐请求注入，故续传时**由同一个 `catalog` 推出同一注入列**；但这是「靠 catalog 重算」而非「存住当时的 sort」，自定义 `sort` 传空串（明确不注入）时续传会退回默认列，跨页行序可能不一致 |
| 字节级（单文件） | `<name>.part` 半成品 + HTTP `Range: bytes=N-`；服务端 206 续传、200 忽略则整文件重下；续传中失败**保留 .part** | `download_file` 再次调用即自动续 |

纪律：续传中失败不删半成品；落盘后的 `checksum_match` 门禁**取写前意图摘要与写后
读回摘要的真布尔比对**（`digests_match`），无外部期望值也照样求值 → 该 blocking 门禁
**可达**；外部基准核对 `verify_checksum(expected_sha256)` 才只在传期望值时发生
（站点不提供摘要 → 生产链路零传入）。
字节级另有大小回核，不符即失败，不静默续写。

## 5. Hook 分级拦截与 ask 纪律（强制）

`DownloadHooks(policy=HookPolicy(...))`，两级：

| 级 | 问题 | 行为 |
|----|------|------|
| network | 连接失败/超读/429/5xx | 指数退避自动重试 ≤ `max_retries`（默认 3，基数 2s）；耗尽才拦截（`network_exhausted`） |
| severe | **已接线**：`empty_precise_result` / `precise_id_list_too_large`（精准下载两类）；**已定义未接线**：`checksum_mismatch` / `disk_write_failed` / `session_expired` / `pagination_inconsistent` / `path_traversal` | 立即拦截（重试无意义或有损坏风险）；未接线类当前不会触发，对应故障走任务 failed（见 §9 排障表） |

**ask 铁律**：拦截产生 `HookBlockedError`，其 `interrupt.to_ask_payload()`
（`id/question/options/raw`）必须交给用户做**一次** ask——说明原因 + 证据 +
至少 2 个建议方案；严禁静默跳过或自动选路。后台任务被拦截时：任务置
`blocked`、载荷写进度文件，前台下次 `status()`/`pending_asks()` 时 surfaces；
`mgr.result()` 对 blocked 任务抛 `HookBlockedError`（调用方捕获后 ask）。
非网络异常（编程错误）不被包装成 network ask，原样抛出。

## 6. 精准下载对应数据（source_id 列表）

```python
from src.download_manager import DownloadManager, PreciseDownloadJob

mgr = DownloadManager(client)
job_id = mgr.submit(PreciseDownloadJob(
    source_ids=["CALIBSTARS_0844369", "CALIBSTARS_0841102"],
    catalog="stripe82",
    columns=["stripe82_calibstars_id", "stripe82_ra", "stripe82_dec"]))
path = mgr.result(job_id)
```

- 机制：`{table}.{id_col}` 的 **`in` 约束**（站点表单 textarea 形态，换行分隔），
  只取这些行；`columns` 做列投影（响应列名，protocol 映射为 showcol 键）。
- **星表 ID 列映射**（live 实证）：`stripe82 → calibstars_id`（响应用
  裸列名！）；其余星表 `→ {catalog}_source_id`；可用 `id_column=` 显式覆盖。
- **ps1 陷阱（live 实证）**：`ps1_source_id` **不是**「线上逐行为空」那一列。ps1 回包把
  **对象记录**（该列有值）与**点源记录**（该列整列为空串）两类首尾相接返回，**占比随天区变**：
  同一条查询语句，(286.1,15.7) 实测 300 行里 **128** 行非空，(180.0,30.0) 则 **0/300**
  （r=600″ 实跑；入库快照 `live_ps1_ra359.5_dec0.0_r1800.0as` 1000 行里 **431** 行非空，
  同一结论的第二份独立佐证）。⚠ 旧记「`ps1_source_id` 线上逐行为空」是在 (180.0,30.0)
  单点测得的**局部**结论被当成了全局属性，**已撤回**；分型判据与五种「无值」编码见
  `references/data-formats.md` §5c。**正确口径是「用这一列当主键前必须先判记录类型」**，
  而不是「这一列不能当主键」：命中点源记录子集时该列确实零可用，换天区则可能整列可用。
  ps1 精准下载（`in` 约束）仍会 0 行，由 hook `empty_precise_result` 拦截并 ask
  （设计内行为，不是 bug）—— 但那是**下载路径**的结论，建议改走 proximity 坐标上传。
- 上限：单次 in 查询 ≤ `MAX_IDS_PER_QUERY`（1000）个 ID；超出走 hook
  `precise_id_list_too_large` ask（建议分批或改 proximity）。
- 结果回核：0 行 → hook ask（ID/星表用错）；部分命中（行数 < ID 数）→ WARN
  不阻断（ID 不存在是常态）。
- CLI：`download start --source-ids ID1,ID2 --catalog stripe82`。
- live 证据：stripe82 2 个真实 ID → 2 行精确返回
  （`temp/live_precise_results.json`）。

## 7. 任务日志管理器（快速定位问题）

- 位置：`.logs/task_log.jsonl`（append-only JSONL，原子行追加，单行截断防护）。
- 与 `.progress/` 分工：**日志答“发生了什么”，进度答“到哪了”**。
- 事件：`submit/start/page/done/blocked/failed/cancelled/hook/ask/query/resume/info`，
  级别 info/warn/error；hook 拦截自动记 warn，任务失败记 error。
  （`ask` 在 `task_log` 事件枚举里但当前无生产代码发出——拦截实际记的是
  `hook`/`blocked`，`ask` 保留给未来显式 ask 审计面。）
- 查询：CLI `log tail [--job-id --event --level --n]` / `log problems`（warn+error
  第一视图，非零退出）/ `log tasks` / `log summary <job_id>`（事件数/首末时间/
  是否异常）；库内 `TaskLogger.tail/summarize/problems/tasks`。
- 排障典型路径：`log problems` → 看到 hook/失败事件 → `log summary <job_id>` →
  该任务全事件链 → 对照 `.progress/<job_id>.json` 的 blocked 载荷 ask 用户。

## 8. 常见下载需求 → 做法

| 需求 | 做法 |
|------|------|
| 单天区下载 | `RegionJob(ra,dec,radius_arcsec,catalog)` 或 `download start --ra --dec --radius` |
| 多天区/多星表并行 | `submit_all([RegionJob(...), ...])`（唯一文件名自动生成） |
| 已有 sqlid 续取 | `SqlidJob(sqlid="s3898")` / `download start --sqlid s3898` |
| 换格式导出 | `output_format ∈ csv/txt/json/votable`；FITS 走本地转换（`BestDownloader.download_region(..., output_format="csv")` 取行后交 `src.serialization.write_fits`，服务端不支持） |
| 单文件下载（大文件） | `FileJob(url)` / `download start --file URL`；自动 Range 续传 |
| 崩进程后续传 | `mgr.resume(job_id)` / CLI `download resume <job_id>` |
| 取消 | `mgr.cancel(job_id)`（下一页边界停）/ CLI Ctrl-C 或 `download cancel` |
| 看进度 | `mgr.status()` / CLI `download progress|list` / GUI 读 `.progress/*.json` |
| 精准取行 | `PreciseDownloadJob(source_ids=[...])` / CLI `download start --source-ids`（注意 ps1 该列分**对象/点源记录**两态，非空与否随天区与记录类型变，见 §6 与 `references/data-formats.md` §5c） |
| 待决拦截 | `mgr.pending_asks()` / CLI `download asks`（非零退出=必须 ask） |
| 定位问题 | CLI `log problems` / `log summary <job_id>` / 库内 `TaskLogger` |

## 9. 常见下载问题 → 解法（全部实证过）

| 症状 | 根因 | 解法 |
|------|------|------|
| 内联 CSV 数百 MB 量级 | 提交了无空间约束的表单 | 查询必带天区/星等约束；先 cone 再放大（历史记录 ~637 MB 无留档证据，量级口径） |
| `getcount` 超时 | 无约束会话计数要全表扫描 | 先收敛天区再取计数 |
| 状态码 200 但无数据 | 软 404（`{"error":"Not Found"}`）或 `{"error":"Internal Server Error"}` | 看响应体前 60 B，不看状态码 |
| CSV 首列乱码/`\ufeff` | 响应体带 UTF-8 BOM | 按 `utf-8-sig` 读 |
| 请求 fits 得到 HTML | 服务端不支持 fits 导出 | 本地转换（`write_fits` BinTableHDU） |
| HTTP 429 / 5xx | 限流/服务端波动 | hook network 级自动退避重试；仍失败 ask |
| 下载中途断网 | 连接 drop | 页级：checkpoint 续传；字节级：`.part` + Range 续传 |
| checksum 不符 | 半成品损坏/传输错误 | 落盘门禁 `checksum_match` = 写前意图摘要 vs 写后读回摘要（真布尔、可为 False，恒写 unknown 的旧行为已修）→ 不符即任务 **failed**；外部基准 `verify_checksum` 需调用方传期望值（站点不给摘要 → 生产零传入）；字节级另有大小回核（`SEVERE_CHECKSUM` 模板已定义未接线） |
| 磁盘写失败 | 空间不足/权限 | OSError 冒泡 → 任务 **failed**（错误信息含异常类型；`SEVERE_DISK` 已定义未接线） |
| sqlid 失效 | 会话过期被服务端回收 | 软错误体判定 → `success=False(E_SOFT_404)` → 任务 **failed**，需重新 POST /q 建会话（`SEVERE_SESSION` 已定义未接线） |
| 分页行序漂移 | 无 ORDER BY 时服务端行序不稳定 | 已由 P0-1 确定性排序列注入缓解（分页必带 sort+order）；跨页行数核对当前没有（`SEVERE_PAGINATION` 已定义未接线） |
| 结果页网格转圈无数据 | dbgrid 数据口匿名不可用（站点缺陷） | 用 GET `/sqlid/{id}?output.fmt=csv` 分页（本 skill 默认路径） |
| 锥搜 0 行 | `pos.radius` 传了度（单位是角秒） | radius 用角秒（表单页原文实证） |
| 两并行任务互相覆盖 | 自动文件名相同 | 已修：按 (星表,天区,半径,格式) 唯一命名；自定义名仍需自行防重 |
| 落盘 votable 列全成字符串 | 列类型按名猜漏判前缀列 | 已修：按整列取值推断（`column_is_numeric`） |
| 精准下载 0 行 | ps1 **点源记录子集**的 `source_id` 为空（对象记录子集非空，换天区可能成功）；或 ID/星表用错 | hook `empty_precise_result` ask；ps1 改用 proximity 坐标上传 |
| 精准下载超 1000 ID | 单次 in 查询上限 | hook `precise_id_list_too_large` ask：分批或 proximity |
| stripe82 下载丢 ID | 响应用裸列名 `calibstars_id`，旧解析别名表漏它 | 已修：`from_row` 别名补 `calibstars_id`（live 实证回归） |
| 主键列认错（`*_id` 通配） | **`gaia_dr3_18_solution_id` 是解算批次 ID，不是主键** —— 1000 行里只有 2 个不同值，字典序又排在 `*_source_id` 前面 | 主键只认 `*_source_id` 与 stripe82 的 `*_calibstars_id`；**不要按裸 `id`/`objid` 后缀扫全列**（2026-10-04 实测踩过）。重复 id 会让两行塌成同一主键 |
| 出问题不知道从哪查 | 日志与进度不分 | `.logs/task_log.jsonl` 事件流 + `log problems` 第一视图 |

## 10. 与既有能力交融（已验证）

交叉匹配 / 光变导出 / pipeline / query / `BestClient` 与新下载栈并存，
回归见 `test/integration/test_download_feature_integration.py`（11 用例）：
- `BestCrossMatch.crossmatch_coords` 结果可直接喂 `RegionJob` 天区；
- `BestMultiBandPhotometry.to_csv/to_json` 与后台下载同一工作流共存；
- `BestQuery.build()` 参数字典与 `protocol.build_query_form` 表单化职责不变；
- `BestClient.cone_search` 与 `DownloadManager` 同进程共存；
- `provenance.build_envelope` 信封可包下载产物（data_hash 可复核）。

## 11. 复现与证据

- 单测：`pytest test/unit/download test/unit/models test/integration/test_download_feature_integration.py`
- live 冒烟：`temp/live_bg_smoke.py`（2 并行后台任务，前台轮询不阻塞；
  证据 `temp/live_bg_download_results.json`：done、唯一文件名、74 KB/任务）；
  `temp/live_precise2.py`（stripe82 真实 ID 精准下载，2ID→2行；
  证据 `temp/live_precise_results.json`）
- hook 反证：`pytest test/unit/download/test_download_hooks.py`（拦截必带 ask 载荷）
- 任务日志：`pytest test/unit/download/test_task_log.py`；CLI `python ops/astro_best_cli.py log problems`
