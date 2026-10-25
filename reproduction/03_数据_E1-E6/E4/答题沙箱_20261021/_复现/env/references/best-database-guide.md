# BEST Database Guide

## 概述

BEST（官方站名 **BEst STar database**，国家天文科学数据中心 NADC 的均一定标标准星数据库）
是经过精测定标的高精度测光数据库。其数据经过严格的气消光校正、零点标定和仪器效应修正，
精度优于许多官方 survey 发布的数据库，可以作为多种天文数据分析的 baseline。

- 官网口径（首页）：**up to 2 billion stars**（约 20 亿星）、200+ 波段、mmag 级精度；
  标准星组（/std doc 页）口径为 over 200 million stars（2 亿+）、~10 mmag —— 两个
  数字范围不同（全集 vs 标准星子集），引用时勿混。
- SCR 方法单星精度（官网 doc 页口径）：u/v 类波段 0.01–0.02 mag、grizy 类 0.001–0.005 mag。
- 引用（从官网 help 页 Citation 段采集）：Xiao et al. (2025,
  Scientific Data, submitted) 与 Huang et al. (2024, ApJS, 271, 13)。
  **完整元数据/BibTeX/DOI 在 `rag/knowledge/citations.yaml`**（9 条 verified +
  2 条 unverified，Crossref 实核）；本文件不重复引文。
- 各 Well-Calibrated 星表的精度/规模、19 个测光系统全表、User-Defined
  上传协议：见 [`photometric-systems.md`](photometric-systems.md)（官方文档镜像）。
- **站点端点与交互全图**（`/nss/solve` 名称解算、dbgrid 网格口、SAMP 推送、
  导出协议、live 状态快照）：见
  [`site-endpoints-and-interactions.md`](site-endpoints-and-interactions.md)。

## 数据访问方式

`https://nadc.china-vo.org` 上的 BEST 子站是 **Django 表单应用**，不是 TAP/ADQL 服务，
也不是 JSON REST 服务。查询走"提交表单 → 服务端建 SQL 会话 → 按页取结果"两阶段。

**关键判据：该站对未知路由返回 HTTP 200 + 请求体 `{"error":"Not Found"}`（软 404）。**
因此"状态码 200"不能证明端点存在，必须看请求体。本文所有条目均按下文《核查方法》实测得到。

### 端点清单

| 端点 | 方法 | 作用 | 备注 |
|------|------|------|------|
| `/data/best` | GET | 首页/导航 | 301 → `/data/best/` |
| `/data/best/std`、`/calib`、`/other` | GET | 三个分组的目录页 | 分组页本身**不可查询** |
| `/data/best/jobs` | GET | User-Defined Catalog（自建星表上传/交叉匹配） | 需登录；未登录 308→`/jobs/` 再 302→`/user/login?next=…`，**第一跳是站点表单登录页（Django 会话），OAuth 是第二跳**（2026-09-27 实测） |
| `/data/best/doc/system-en/{catalog,help,news}` | GET | 官方文档 | `catalog` 页含测光系统全表 |
| `/data/best/{catalog}/f` | GET | 查询表单页 | 裸 id 全组通用；带分组前缀的 `/calib/{catalog}/f` **仅对 calib 组成员有效**（ps1/stripe82/gaia_dr3_18/jplus_dr3/smss_dr4/landolt/uss_dr1/splus_dr4），std/other 组成员带前缀均软 404（2026-09-29 复测） |
| `/data/best/{catalog}/q` | POST | 建立查询会话 | **只接受裸星表 id**，`/calib/{catalog}/q` 是软 404 |
| `/data/best/sqlid/{sqlid}` | GET | 结果分页/导出 | 参数 `output.fmt`、`rows`、`page`、`sort`、`order`（分页务必带 `sort`+`order`：无 ORDER BY 时服务端行序不稳定；`filterRules` 是 EasyUI 插件名、非服务端参数，本站 datagrid URL 亦无此参，已 live 证冗余） |
| `/data/best/sqlid/{numeric}/getcount` | GET | 结果总行数 | 返回 `{"total": N}`；**id 必须去掉 `s` 前缀** |
| `/data/best/t/{table_id}` | GET | 单表列元数据页 | 站点用它构造 `showcol`，可作列名校源 |
| `/data/best/user/login?next=…` | GET | 登录入口 | 实际跳转到 `oauth.china-vo.org`，回调 `/data/best/user/oauth2/callback/nadc` |

`{sqlid}` 形如 `s3873`；同一会话在 `sqlid` 路由用带 `s` 的 id，在 `getcount` 路由用纯数字。

### 两阶段协议与 `output.fmt` 的分岔

`POST /q` 的 `output.fmt` 决定返回形态，这一点极易踩错：

| 提交的 `output.fmt` | `/q` 的响应 | 后果 |
|---|---|---|
| `html` | 结果页 HTML，内含 `sqlid=sNNNN` | ✅ 唯一能拿到会话 id 的写法 |
| `csv` / `json` / `votable` / `txt` | **直接内联数据**，无 sqlid | 两阶段分页协议丢失，无法翻页/取总数 |

### 可用星表（12 张可查询表）

| id（`/q` 用） | 分组 | 说明 | 位置表 / 列规模 |
|---|---|---|---|
| `ps1` | calib | Pan-STARRS 全天（站点亦作 `calib/ps1`，同表 t/346） | 位置表 `ps1` |
| `stripe82` | calib | Stripe82 精测天区 | `stripe82`（t/329，页题 `#329 bestphot_calib.stripe82`，2026-09-29 复证） |
| `gaia_dr3_18` | calib | Gaia DR3 精测定标 | `gaia_dr3_18`，155 列（t/349，页题 `#349 bestphot_calib.gaia_dr3_18`，2026-09-29 复证） |
| `jplus_dr3` | calib | J-PLUS DR3 精测定标 | `jplus_dr3` |
| `smss_dr4` | calib | SMSS DR4 精测定标 | `smss_dr4` |
| `landolt` | calib | Landolt 标准星 | `landolt` |
| `uss_dr1` | calib | USS DR1 精测定标 | `uss_dr1` |
| `splus_dr4` | calib | S-PLUS DR4 精测定标 | `splus_dr4` |
| `scr_galah` | std | 标准星 × GALAH 交叉表 | `scr_galah`，137 列 |
| `scr_lamost` | std | 标准星 × LAMOST 交叉表 | `scr_lamost`，137 列 |
| `xpsp` | std | Gaia DR3 XP&SP 光谱-测光 | 139 张表单表（含 1 张共享位置表 `gaiaxp_photinfo_replenish` + 138 张分波段表），287 个可选列 |
| `dr3xpcorr` | other | 修正后的 Gaia DR3 XP 光谱 | `gaiaxp_photinfo_replenish` + `correctedxpspecv1`，共 17 列 |

两个易错点：

- **没有 `gaia_dr3` 这张表**：线上 id 带 `_18` 后缀，`gaia_dr3/f`、`gaia_dr3/q` 均为软 404。
  列前缀同样是 `gaia_dr3_18.`，不是 `gaia_dr3.`。
- **`std` 不是表**：`/std/f` 与 `/std/q` 返回 `{"error":"Internal Server Error"}`，
  它只是 Standard Stars 分组页，成员是上面三张表。
- **文档页列了 SkyMapper DR4（34G）但线上不可查询**：`/skymapper_dr4/f` 是软 404，
  `/calib` 分组页只列 7 张表（无 skymapper）。凡文档页出现的星表，均以 `/f` 路由
  实测为准，文档存在 ≠ 可查询。
- 测光系统侧共 19 个（APASS…ZTF，含 296G 的 J-PAS），与"可查询表"是两个维度，
  详见 [`photometric-systems.md`](photometric-systems.md) §2。

**可查询 ≠ 在任意天区都查得到**（2026-10-04 逐表实抓，33 个快照目录 / 31 份
`rows_full.csv` 已入库；计数见 [`site-endpoints-and-interactions.md`](site-endpoints-and-interactions.md) §10）：

- `stripe82` 只覆盖赤道精测天区，`smss_dr4`/`splus_dr4` 各自只覆盖南天 survey 天区，
  锥区落在天区外就是 0 行 —— 这是**正常**结果。
- `landolt` 全表 45712 行摊到全天约 1 行 / 3.7 deg²，**任何 0.5° 锥都大概率 0 行**。
  要用它必须先有已知标准星坐标（锥搜按位置找，按名字找不到）。
- **`jplus_dr3` 探测 24 处全 0 行**（含其公认天区与最大半径）—— **疑似站点侧覆盖
  异常，待站方确认**。留档快照显示 `getcount` 与分页**自洽**（`{"total":0}` +
  HTTP 200 的 12 列表头 CSV、0 数据行，无软 404 形态），即站点此刻的表现与
  "该锥内无源"无法区分。这一条与上一条的 `landolt` **必须分开看**：两者都表现为
  0 行，但一个能由密度估算解释、另一个不能。
- 逐表实测行数、坐标列形态与判读依据见
  [`site-endpoints-and-interactions.md`](site-endpoints-and-interactions.md) §10.3。

### 表单字段（实测字段名）

| 字段 | 取值 | 说明 |
|---|---|---|
| `csrf_token` | 表单页内嵌 | 缺失即被拒 |
| `output.fmt` | `html`/`csv`/`json`/`votable`/`txt` | 见上文分岔 |
| `pos_group` | `ra,dec` | 位置入口选择 |
| `pos.type` | `none`、`cone`、`rect`、`proximity` | 四种空间选择 |
| `pos.racenter`/`pos.deccenter`/`pos.radius` | 度 / 度 / **角秒** | `cone` 用。**单位陷阱：表单页原文 `radius <input name="pos.radius"> arcsec`，radius 是角秒不是度**（表单页实证；传度会得到 0 行或 360 倍半径） |
| `pos.ramin`/`pos.ramax`/`pos.decmin`/`pos.decmax` | 度 | `rect` 用 |
| `pos.radecTextarea` / `pos.posfile` | 文本 / 上传文件 | `proximity` 用：**服务端批量坐标交叉匹配**；文本区格式为 `ra,dec[,radius_in_arcsec]`（官网示例 `236.2150926,6.29186431,2`，即半径 2 角秒） |
| `pos.defaultRadius`、`cone_nearestonly`、`proximity_nearestonly` | — | 半径缺省与"仅最近邻" |
| `showcol` | 可重复，`{table}.{col}` | 投影列；不提交则只回 `inputobjs_*` |
| `{table}.{col}.operation` | `equal`/`notequal`/`less`/`lessequal`/`greaterequal`/`between`/`contains`/`in` | 上列 8 个是本仓 `src.protocol.ALLOWED_OPERATIONS` 白名单（fail-closed，白名单外显式 `ValueError`）。⚠ **旧文档「站点把 greater 拼成 `grater`」已被实测推翻**：2026-10-05 ps1 @180,30 300″ 同锥逐项实跑，`greaterequal` min15 出 **1559** 行，而 `grater` min15 出 **0** 行（回包 426 B，仅表头）—— 白名单外的值站点**既不报错也不忽略**，而是收下后返回空表。⚠ 但「`grater` 在站点表单下拉里到底有没有这一项」**当前未取证**（表单页三次尝试均未取到取值表：候选 URL 返回的是结果页壳，站点两个 JS 里也没有取值表）—— 故本仓白名单的依据是**行数行为**而非表单取值表，**站点的严格大于拼写尚未取证**，本仓**不做** `greater→grater` 映射 |
| `{table}.{col}.min`/`.max`/`.constraint`/`.textarea`/`.file` | — | `between` 用 min/max；`contains`/`in` 用 textarea |
| `sort` | 列名 `{table}.{col}` | 排序列（`sort` 与 `order` 是**同一个 if 分支**：只发 `order` 不发 `sort` 时站点不报错，排序静默不生效、分页退回无序） |
| `order` | `asc`/`desc` | 排序方向；**取值是方向不是列名**，且只在 `sort` 存在时携带 |

`{table}` 多数等于星表 id；`xpsp`/`dr3xpcorr` 的位置与光谱列分别落在
`gaiaxp_photinfo_replenish` 与 `correctedxpspecv1`，XP 分波段 flux 列另在各波段子表里。

### 输出格式与响应列命名

实测支持 `csv`、`txt`、`json`、`votable`，以及站点网格自用的 `dbgrid`
（`{"rows":[…], "total": 999999999999}`，超限以哨兵值表示）。
**`fits` 不受支持**：请求它返回的是结果页 HTML 而非 FITS，导出需本地转换。

- CSV 请求体带 UTF-8 BOM（`\ufeff`），解析须用 `utf-8-sig` 或先剥 BOM。
- `/q` 内联响应给**裸列名**（`ra`、`gpsf`）；`/sqlid/{sqlid}` 分页响应**多数**给
  **带前缀列名**（`ps1_ra`、`ps1_gpsf`）。两个例外（2026-09-29 复测）：
  **uss_dr1 的 CSV 响应恒为裸名**（`ra_u`/`u_pstotal`，站点 datagrid 才用
  `uss_dr1_` 前缀）；**xpsp/dr3xpcorr 的共享表列前缀是表单表名**
  （`gaiaxp_photinfo_replenish_ra` 而非 `xpsp_ra`）。带空间约束时额外前置
  `inputobjs_*`（`inputobjs_input_ra`、`inputobjs_dist_arcsec` 等），即服务端
  匹配的行号与角距。

### 使用约束

- 查询务必带天区/星等约束。无约束的"Save all"等价于全量拉表：内联 CSV 可达
  **数百 MB 量级**（历史记录称 uss_dr1 上约 637 MB，但无留档证据、且该表
  2026-09-29 已按波段重构，作量级口径勿引作精确值）。
- `getcount` 在无约束会话上会超时（>60 s），先收敛天区再取计数。
- 官网 help 页口径：批量上传 CSV **只含 ra/dec 两个列头**，单文件 <1000 万源；
  更大数据集走 Catalog 区整表下载（需登录）。

### User-Defined Catalog（`/jobs`，需登录）

自建标准星作业区：上传 **FITS 滤光片响应曲线**（列 `wavelength`，单位 Å，
范围 3360–10200；列 `function`，归一化响应）+ 测光系统与波段名 → Run → Jobs 表
跟踪；Phase pending 超 1 分钟应重新上传；空闲服务器上每波段数分钟可生成 2 亿+ 标准星。
本 skill 的 `src/auth/` NADC OAuth 身份层即为此区登录服务；真实作业流在获得
NADC 应用审批（client_id/secret）前标记 blocked-on-approval。

## 核查方法

上述结论用以下方式得到，可按同样步骤复现：

1. 抓首页/分组页，从 `href` 枚举出 `/std`、`/calib`、`/other`、`/jobs` 及其下所有 `/f` 表单页。
2. 对候选路由取响应体大小与前 60 字节；以 `{"error":"Not Found"}`（22 B）与
   `{"error":"Internal Server Error"}`（34 B）区分真实端点与软 404。
3. 从表单页正则抽 `value="{table}.{col}"` 得 `showcol` 全集与列前缀。
4. 用 `output.fmt=html` 与四种数据格式分别 POST `/q`，比对是否返回 sqlid。
5. 用同一会话分别请求 `sqlid/{sN}` 与 `sqlid/{N}/getcount` 校验两种 id 形态。

补充采集（官方文档层，证据 `temp/catalog_doc.txt`、`temp/probe_text.txt`）：

6. 抓 `/doc/system-en/{catalog,help,news}` 三页，镜像测光系统全表、SCR 精度口径、
   Well-Calibrated 文献与官方引用块；对页面所列文献逐条 Crossref REST 核验 DOI
   （`temp/crossref_verify*.py` → `temp/crossref_verify*.json`，9 条全部 verified）。
7. 对 catalog 文档页出现但分组页缺失的星表（skymapper_dr4）单独探测 `/f` 路由，
   确认文档-现实偏差并记录（见上文与 photometric-systems.md §6）。

全链路联通测试（证据 `temp/live_connectivity_results.json`）：
表单页(csrf+30 列) → POST `/ps1/q`(cone 180″) → sqlid=s3898 → CSV 首页 10 行
（表头 `inputobjs_*` + `ps1_ra,ps1_dec,ps1_gpsf,ps1_ipsf,ps1_rpsf`）→
getcount total=1870 → `/t/346` 30 列 → skymapper 软 404 复验 → `calib/gaia_dr3_18/f`
分组前缀路由 200。同轮 `PYBEST_RUN_LIVE=1 pytest test/live` **7 passed / 15 skipped**，
并修复两个 live 才暴露的实现缺陷（pybest `_save_result`：fits 无写入分支抛
FileNotFoundError；votable 列类型按名猜漏判 `ps1_ra` 前缀列——改为按取值推断）。

> 说明: 早期版本此处有一节「与 pylamost 对比」。该内容描述的是上游姊妹包
> （光谱巡天）而非本 skill 的能力边界，已删除以免误导选型; 需要对照时查
> 上游包自身文档。
