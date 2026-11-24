# ALGORITHM-SPEC.md — astro-best 算法白盒规范 (G7 五要素)

> 立档依据: Phase 3-D 白盒化整理; 增量修订按 CHANGELOG.md 逐轮登记 (禁版本号铁律)。

## 1. NADC BEST REST 端点表 + 两阶段异步查询 (主理能力 ①)

量纲: 坐标 ra/dec (deg), 搜索半径 (arcsec), 时间窗 (MJD, day), 速率 (req/s),
HTTP 状态 (count, 门禁 ==200), 校验和 (bool, 门禁)。
协议: 端点 $\texttt{https://nadc.china-vo.org/data/best}$ 为 Django 表单应用
（两阶段：POST 表单取 sqlid，GET sqlid 分页）。**BEST 未提供 TAP/ADQL 端点**，
历史声明的 $\texttt{https://best.astro.tsinghua.edu.cn/tap}$ 门面经复核实为
无 A 记录的域名，仅作兼容别名保留、不得对外宣称为可用能力。
两阶段: ① POST 检索表单 (`output.fmt=html`) → 服务端建 SQL, 返回含 `sqlid` 的 HTML;
② GET `/sqlid/{sqlid}` 分页拉取 JSON/CSV — 由 `BestClient` 独立实现
(requests.Session + urllib3 Retry 429/5xx, 退避 2.0)。
软 404: 未知路由返回 HTTP 200 + `{"error":"Not Found"}`，故 `http_status==200` 门禁
不足以证明端点存在，须并查请求体。检测实现 `src/protocol.py: is_soft_error/
Soft404Error` (P0-3): 两个客户端在唯一收口处 body 检测, 失败显式
抛 `E_SOFT_404` 而非静默空结果。
真实计数: phase-2 前先调 `getcount` (`src/client.py: BestClient._count`, P0-2),
`total_count` 取服务端值并置 `truncated`; 约束会话实测稳定 (V-4, temp/live_getcount_results.json)。
端点/交互全图 (实机浏览器深潜补全): `/nss/solve` 天体名解算
(CDS Sesame 代理, GET only, 失败哨兵 ra=dec=-1000)、`/t/{table_id}` 列元数据、
`/{group}/doc/{ts}` 分组描述页、结果页 dbgrid 数据口 (POST, 匿名不可用 —
2026-09-29 复测为 123ms 快速软错误, 旧记"挂起"已改写, 结论方向不变)、
SAMP `table.load.votable` 推送、隐藏表单 POST 导出 (`csrf_token+output.fmt+sqlid|id`)。
逐条见 `site-endpoints-and-interactions.md` (智能体使用向 SSOT, live 快照以该篇 §6 为准)。
站点能力接线 (P1-8): `/nss/solve` 名称解算 (`BestClient.resolve_name`,
哨兵显式判 `E_NAME_UNRESOLVED`)、`showcol` 列投影
(`columns` 参数, 三种拼写经 `qualify_column` 白名单)、服务端 `sort`/`order`、
`cone_nearestonly`/`proximity_nearestonly` 最近邻。

## 2. 两阶段异步查询真源码锚点
| 用途 | 精确函数/类 | 位置 |
|------|----------|------|
| 协议客户端 | `BestClient.cone_search / _build_form / _fetch_sqlid_data / _count` | `src/client.py` |
| 权威协议层 | `build_query_form / parse_csv_rows / parse_count / is_soft_error / parse_name_resolve` | `src/protocol.py` |
| 认证 | `BestAuth` (Django session+CSRF); 凭据面 = CLI `--auth-user` + env `ASTRO_BEST_PASSWORD` (交互终端回落 getpass, 刻意无 `--auth-pass`) | 定义在 `src/auth/session.py`, `src/client.py` 再导出 (兼容 `from src.client import BestAuth`); env `BEST_API_TOKEN` 只覆盖 `AstroBestConfig.api_token`, **客户端无此通道** (`src/core/__init__.py` 记 "全链是死路, 已删") |
| 查询信封 | `BestQuery` (`src/query_builder.py`) / `BestQueryResult` (`src/models`) / `validate_adql_query` (`src/scripts/guards.py`) | `src/query_builder.py`, `src/models`, `src/scripts/guards.py` |
| 流式下载 | `BestDownloader` (校验和 + 断点续传) | `src/downloader.py` |
| 批量匹配 (逐点) | `BestCrossMatch.crossmatch_coords` | `src/crossmatch.py` |
| 批量匹配 (服务端 proximity) | `BestCrossMatch.crossmatch_batch` (经公开缝 `BestClient.crossmatch_batch`) | `src/crossmatch.py`, `src/client.py` |
| 后台/并行下载栈 | `DownloadManager / ProgressStore / DownloadHooks / PreciseDownloadJob / TaskLogger` | `src/download_*.py`, `src/task_log.py` |
| 编排 | `AstroBestPipeline / BestSkillClient / QualityGate(min_snr=5, max_fwhm=5)` | `src/core/{pipeline,__init__}.py` |
| CSV 安全 | `sanitize_cell` (公式注入消毒入口; 同模块 `sanitize_row`/`sanitize_rows`) | `src/csv_safety.py` |

## 3. 超参
| 超参 | 默认 | 含义 |
|------|------|------|
| rate_limit | 2.0 s/request | 礼貌限速 (`BestClient` 唯一现役客户端; pybest 单类门面 `Best` 已删除, 见 §5) |
| max_retries | 3 | urllib3 重试 (429/500~504, backoff 2) |
| timeout | 120 s | 所有 session.get/post 的通用请求超时 (`REQUEST_TIMEOUT`) |
| check_connection_timeout | 30 s | 仅连通性自检专用的硬编码超时 |
| min_snr / max_fwhm | 5.0 / 5.0 | 质量门控 (QualityGate) |
| max_rows | 50000 | 单次查询拉取的行上限 |
| page_size | 1000 | 分页拉取时每页的行数 |

## 4. NADC 通行证 OAuth2.0 身份层 (主理能力 ②, Phase 6)

量纲: access_token 有效期 expires_in (s, 典型 3600); state 熵 (bit, ≥128);
HTTP 状态 (count); profile 字段 (string/bool, 无量纲)。
协议: NADC 用户通行证 (https://oauth.china-vo.org) **仅 Authorization Code 模式**:
① GET `/oauth/authorize?response_type=code&client_id&redirect_uri&scope=profile&state`
  — 用户登录授权, 回调 `redirect_uri?code&state`;
② POST `/oauth/token` (grant_type=authorization_code&code&redirect_uri&client_id&
  client_secret&scope=profile) → `{"access_token","expires_in"}` (官方无 refresh_token);
③ GET `/api/profile` (`Authorization: Bearer <token>`, **Bearer 与 token 间必须有空格**)
  → `{"code":200,"data":{"user":{umtId, ldap_id, name, email, ...}}}`;
④ GET `/oauth/logout?WebServerURL=` 登出。
真源码锚点: `src/auth/nadc_oauth.py` (build_authorize_url/exchange_code/get_profile/
build_logout_url/run_local_callback_flow/run_manual_paste_flow/ensure_access_token),
`src/auth/__init__.py` 门面; token 缓存 `TokenStore` (~/.astro-best/nadc_token.json,
v2 信封: Windows DPAPI 密文 / POSIX 0600, expires_at 过期重取; v1 裸 JSON 兼容读取)。
过期恢复 (2026-09-30): 官方无 refresh_token → `ensure_access_token` 是唯一恢复单点
(有交互通道注入 reauth 自动重走授权; 无通道抛 `TokenExpiredError` 带恢复命令,
绝不返回过期令牌); CLI 面对应 `oauth token` / `oauth status` 三态。
交互: 本地回环 (127.0.0.1 临时端口收 code, state 防 CSRF) + 手动粘贴兜底。
边界: **双轨制** — 本层只做 NADC 身份 (profile/provenance 血缘); BEST 数据查询 form
登录不变 (真实凭据面: CLI `--auth-user` + env `ASTRO_BEST_PASSWORD`; 历史 env
BEST_API_USER/PASS 无消费方已退役); BEST REST 是否接受 Bearer NADC token 列 V-6 实网验证。
契约: contracts/oauth.contract.yaml (端点表/参数/错误码/凭据纪律)。

## 5. proximity 批量交叉匹配 (P0-1, live 验证)

量纲: 输入坐标 (deg), 匹配半径 (arcsec), 响应角距 `inputobjs_dist_arcsec` (arcsec),
输入行号 `inputobjs_input_line` (1-based count)。
协议: `pos.type=proximity` + `pos.radecTextarea` (`ra,dec,radius` 多行, 逗号分隔)
+ `pos.defaultRadius` + `proximity_nearestonly`; 响应元数据列前缀取决于是否提交
`showcol` (V-1: 提交才带 `inputobjs_` 前缀且返回星表列; 不提交只回 4 个无前缀
元数据列, 一个星表列都没有 — 列投影是必填项)。
真源码锚点: `src/crossmatch.py: BestCrossMatch.crossmatch_batch` (经公开缝
`BestClient.crossmatch_batch` 提交, 其内部委托协议层 `_build_form(radec_text=...)`
— 历史教训: 批量表单曾直连 `_build_form` 私有方法破坏封装, 现统一走公开接口;
P1 合并: pybest 单类门面删除, 提交入口唯一化为 `BestClient.crossmatch_batch`);
逐点路径 `crossmatch_coords` 保留为回归基线与自动 fallback。
实绩: 8 坐标 16 请求/25.9s → 2 请求/7.0s; N=100/500/1000 全部成功 (745 命中/约 3s,
temp/live_proximity_p1_8_results.json); 12 张星表默认投影全部可用 (V-2)。
数据卫生: `BestSource.from_row` 跳过 `inputobjs_*`/无前缀元数据列 (不当星等),
ps1 ≈-1000 空值哨兵不当测光 (`NULL_MAGNITUDE_SENTINEL`)。⚠ **该哨兵是「带」不是「点」**:
`-1004.*` 一族散布在 `-1004.0788`~`-1004.0726` (3062 个互不相同的浮点),
浮点精确相等只命中 1/174 —— **禁止等值匹配**, 按阈值 `value <= -999.0` 判缺失。

## 6. IVOA TAP 1.1 适配层 (恢复)

量纲: MAXREC (count), 半径 (deg, ADQL CIRCLE), QUERY 长度 (chars, ≤100000),
响应介质 (votable/csv/fits)。
协议: BEST 上游不执行 SQL; 适配层把**有界 ADQL 子集**解析为类型化查询计划, 再翻译为
两阶段表单协议, 从不转发任意 SQL。支持 SELECT/TOP/WHERE(AND-OR ≤16 分支)/
ORDER BY/CONTAINS(POINT) 锥形; JOIN/GROUP/HAVING/UNION/子查询/聚合/函数投影拒绝;
列名按 `src.protocol.CATALOG_COLUMNS` 白名单校验 (ra/dec 特例补前缀)。
端点 (stdlib `http.server`, 零新依赖): `GET|POST /tap/sync` (doQuery),
`POST /tap/async` (UWS 建单, 303+Location), `GET|DELETE /tap/async/{id}`,
`GET|POST /tap/async/{id}/phase` (RUN/ABORT), `GET /tap/async/{id}/results[/result]`
(结果清单/文件, Range 206/416, X-Checksum-SHA256), VOSI `/tap/availability` ·
`/tap/capabilities` (ivo://ivoa.net/std/TAP#1.1), TAP_SCHEMA `/tap/tables`。
配额: 匿名 MAXREC 1000 / 认证 50000; **Bearer 校验失败一律 401, 严禁降级匿名**;
UWS 相位机 PENDING→QUEUED→EXECUTING→COMPLETED/ERROR/ABORTED (sqlite, CAS 迁移),
每 principal 并发/pending 配额, 网关重启把在跑作业收敛为 ERROR。
真源码锚点: `src/tap/adql.py` (parse_adql), `src/tap/executor.py`
(TapExecutor.execute_with_overflow — MAXREC=0 元数据态不触网), `src/tap/formats.py`
(VOTable/CSV/FITS + OVERFLOW 标记), `src/tap/jobs.py` (TapJobStore), `src/tap/service.py`
(TapGateway/TapHTTPServer), `src/tap/client.py` (BestTapClient, pyvo 可选)。
历史来源: pybest 打包产物树 (git `6f00efeb^` 可取回) 的 `pybest/tap/` (TAP+OAuth
实现; 该树在 best 分支被 Phase 8 重组删除, 迁回忆审详见
site-endpoints-and-interactions.md §8)。

## 7. 智能体工具面

量维: cost.http_requests (count), cost.elapsed_s (s), rows_returned (count),
data_hash (sha256 string), stable_uri (best:// URI)。
协议: 7 个按 agent 意图切的原子工具 (resolve_name/list_catalogs/describe_catalog/
cone_search/crossmatch_batch/count/fetch_page), 统一信封 data/status/cost/provenance;
站点数据一律标注 `content_trust: untrusted` (S-2 提示注入面); sqlid 易失, 可复现
引用用 content-addressed `best://` URI (A-5)。错误码: E_INVALID_INPUT/E_SOFT_404/
E_NAME_UNRESOLVED/E_NO_SQLID (对齐 contracts/error-codes.contract.yaml) +
E_BACKEND (定义于 `src/ai_tools.py`, 登记于 `references/tools.schema.json` 的
error_code enum, 不在上述契约内)。
真源码锚点: `src/ai_tools.py: ToolBox` (Session.request 计数收口) + `src/ai_tools_envelope.py`
(信封构造单点), schema 权威 `references/tools.schema.json`。工具面无独立传输层入口
(MCP server 已于 2026-10-06 整体移除)。
- NADC BEST 数据库服务 — unverified-source (服务规范/在线文档, 无注册 DOI):
  https://nadc.china-vo.org/data/best (task 声明的 NADC BEST 表单/两阶段端点；
  同处的 TAP 声明不成立，见 §1)
- ADQL 语义 — IVOA ADQL 2.1 REC — unverified-source (规范 URL
  https://ivoa.net/documents/ADQL/20250213/index.html)
- 门禁校验和 — SHA-256 (NIST FIPS 180-4) — unverified-source (无 DOI 的规范)

### 文献引用存放
论文引文全集移入 `rag/knowledge/citations.yaml` (RAG 可检索): 9 条
Crossref-verified (Huang et al. 2024 ApJS 271 13 = 10.3847/1538-4365/ad18b1 等)
+ 2 条 unverified (Xiao et al. 2025 Scientific Data submitted; Landolt 2025 to be
submitted)。证据 `temp/crossref_verify*.json`; 本 spec 的 DOI 核验状态以该文件为权威。

### 基线债务
- 两阶段查询的实网断言 (HTTP 200/checksum) 依赖外部服务可用性, 本地单测以
  mock HTML/CSV 夹具替代 → 真网回归 baseline_debt 登记不展开。

### DOI 核验状态 (Phase 3-D 专项; 每条 DOI 以 Crossref REST 逐一实核;
官网文献采集后复审, 9 条 DOI 全部 verified; 权威表在
`rag/knowledge/citations.yaml`, 本 spec 不重复)

| 范围 | 状态 | 说明 |
|-----|------|------|
| citations.yaml 全部条目 | 9 verified / 2 unverified | 外部服务型 skill 的文献引用自此有可验 DOI; unverified 两条为 submitted 态 |
|
