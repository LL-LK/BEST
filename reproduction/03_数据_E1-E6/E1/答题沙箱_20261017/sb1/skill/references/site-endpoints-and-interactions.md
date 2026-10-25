# site-endpoints-and-interactions.md — BEST 站点端点与交互全图（智能体使用向）

> 本文回答一个问题：**智能体要怎么用这个站点**。所有条目来自实机浏览器深潜（Playwright/Chromium，`temp/site_dive/`）+ 逐路由实测，
> 含站点自有 JS（`script.js` / `search-result.js`）证言的交互协议。
> 论文引用不在此文 —— 见 `rag/knowledge/citations.yaml`。
> 领域背景与官方口径见 `best-database-guide.md` / `photometric-systems.md`。

## 0. 一分钟速用（智能体最小路径）

```
GET  /data/best/{catalog}/f                     取 csrf_token + showcol 列名
POST /data/best/{catalog}/q  (output.fmt=html)  → 响应文本正则 sqlid/(s?\d+)
GET  /data/best/sqlid/{sqlid}?output.fmt=csv&rows=N&page=P
GET  /data/best/sqlid/{numeric}/getcount        numeric = 去掉 s 前缀
```
四个请求拿完数据；不要用 `output.fmt=csv` 直接 POST `/q`（内联数据、丢 sqlid、
无法分页/计数）；不要用站点结果页的 dbgrid 数据口（当前对匿名会话挂起，见 §6）。

## 1. 路由全表（实测存在性）

基地址 `https://nadc.china-vo.org/data/best`。软 404 惯例：未知路由返回
HTTP 200 + `{"error":"Not Found"}`（22 B）；表单页对不存在星表返回
`{"error":"Internal Server Error"}`（34 B）。

| 路由 | 方法 | 鉴权 | 作用 | 实证备注 |
|------|------|------|------|----------|
| `/` | GET | 否 | 首页/导航 | 200 |
| `/{group}`（std/calib/other/ps1） | GET | 否 | 分组目录页 | ps1 是顶层页；其余三组各列成员 `/f` 链接 |
| `/{group}/doc/{timestamp}` | GET | 否 | 分组描述页 | 实测 `/calib/doc/20250721143914`、`/std/doc/20250721144330`、`/other/doc/20250721144831`；内容为一句话口径 |
| `/{catalog}/f`、`/calib/{catalog}/f` | GET | 否 | 查询表单页 | 裸 id 全组通用; `calib/` 前缀**仅对 calib 组成员有效** (ps1/stripe82/gaia_dr3_18/jplus_dr3/smss_dr4/landolt/uss_dr1/splus_dr4) — std 组成员 (scr_galah/scr_lamost/xpsp) 与 other 组成员 (dr3xpcorr) 带 `calib/` 前缀均软 404 (2026-09-29 复测, 旧文档"两种前缀均接受"过宽); 表单内嵌 `csrf_token`; `showcol` 选项值是列名权威源 |
| `/{catalog}/q` | POST | 否 | 建查询会话 | **只接受裸星表 id**；`/calib/{catalog}/q` 软 404。**GET `/{catalog}/q` 渲染默认/空查询的结果页**（复查实测，Save/Broadcast 菜单俱在）——不要用 GET 当查询入口，一律 POST 带约束 |
| `/sqlid/{sqlid}` | GET | 否 | 结果页 HTML 外壳 | 内含 datagrid 配置与列定义 |
| `/sqlid/{sqlid}?output.fmt=dbgrid` | POST | 否 | 网格数据口 | body `page&rows&sort&order`；**当前匿名挂起，见 §6** |
| `/sqlid/{sqlid}?output.fmt={fmt}&rows&page&sort&order` | GET | 否 | 分页/导出 | fmt ∈ csv/txt/json/votable；不带 rows/page 即全量。**`{sqlid}` 必须带 `s` 前缀**（`s4943`），写成裸数字回 22 B 软 404；`page`/`rows` 是**绝对偏移**且互相绑定（§6bis） |
| `/sqlid/{numeric}/getcount` | GET | 否 | 结果总行数 | `{"total": N}`；id 去掉 `s`；无约束会话会超时 |
| `/t/{table_id}` | GET | 否 | 单表列元数据页 | ps1=t/346（页题 `#346 bestphot_calib.ps1`，暴露内部库表名） |
| `/nss/solve?obj={name}` | GET | 否 | 天体名解算 | JSON `{ra,dec,obj,remark}`；后端代理 CDS Sesame；**GET only** |
| `/jobs` | GET | **是** | User-Defined Catalog | 未登录 308→`/jobs/` 再 302→表单登录页（`/user/login?next=…`）；**第一跳是 Django 站点登录页不是 OAuth 页**，OAuth 是登录页内第二跳，见 §5 |
| `/user/login?next=…` | GET | 否 | 登录入口 | meta-refresh + JS 双跳 `oauth.china-vo.org/user/login?appid=TfiNrZZBgQRVjxDd59FV9L4B&redirect_uri=…/user/oauth2/login/nadc` |
| `/user/oauth2/login/nadc` | GET | 否 | OAuth 发起路由 | 未登录 302 到 `oauth.china-vo.org/oauth/authorize`（client_id/redirect_uri/scope/state 全参数实证，见 §5）；真正接收 code 的回调路由是 `/user/oauth2/callback/nadc` |
| `/doc/system-en/{catalog,help,news}` | GET | 否 | 官方文档三页 | 镜像见 photometric-systems.md |
| `/user/email-exists?email=` | GET | 否 | 账号系统 | **2026-09-29 复测: 软 404 (端点疑已下线)**; `script.js` 仍证言该调用 (注册校验用), 非数据面 |
| `/search` | GET | 否 | 站点搜索页 | 复查实测：返回 HTML（"Input some words." 搜索框，无表单字段名，疑似 query 参数驱动）；非数据面 |
| `/user/logout` | GET | 否 | 登出入口 | 返回 meta-refresh 重定向页 |

分组页只列**可查询**星表：calib=7 张（stripe82, gaia_dr3_18, jplus_dr3,
smss_dr4, landolt, uss_dr1, splus_dr4）、std=3 张（scr_galah, scr_lamost, xpsp）、
other=1 张（dr3xpcorr）、ps1 顶层。**文档页出现 ≠ 可查询**（SkyMapper DR4 反例，
见 best-database-guide.md §可用星表）。

## 2. 查询表单交互（ps1/f 全字段实测，30 列星表）

### 2.1 空间选择（互斥 radio `pos.type`）

| 模式 | 字段 | 单位 | 备注 |
|------|------|------|------|
| `none` | — | — | 无空间约束（严禁：等于全表） |
| `cone` | `pos.racenter`/`pos.deccenter`/`pos.radius` | 度/度/**角秒** | 表单原文 `radius … arcsec`；`cone_nearestonly` 复选框 |
| `rect` | `pos.ramin`/`pos.ramax`/`pos.decmin`/`pos.decmax` | 度 | 盒式 |
| `proximity` | `pos.radecTextarea` 或 `pos.posfile` | 度,度,角秒 | **服务端批量坐标交叉匹配**；文本区示例 `236.2150926,6.29186431,2`；文件 accept `.txt,.csv`；`proximity_nearestonly` 复选框；`pos.defaultRadius` 缺省半径 |

公共字段：`pos_group=ra,dec`；响应因此前置 `inputobjs_*` 列
（`inputobjs_dist_arcsec/input_line/input_ra/input_dec`，即匹配行号与角距）。

### 2.2 天体名解算（solve）

表单 `#pos_objname` 输入名称 → `#solvename` 按钮 → `GET /nss/solve?obj=M31`
→ 回填 `pos.racenter`/`pos.deccenter`。实证：`M31 → ra=10.68470833,
dec=41.26875`；`NGC 532 → ra=21.32229359, dec=9.26424215`；失败返回
`ra=-1000, dec=-1000` 且 `remark` 内含 CDS Sesame URL（后端是
`cds.unistra.fr/cgi-bin/nph-sesame/A?…` 代理）。**智能体用法**：本地不装
Sesame 也能解算坐标；失败哨兵值是 -1000，不是报错空值。

### 2.3 列投影与约束

- `showcol={table}.{col}` 复选框（可重复）；`showcolcheckall` 按 `data={table_id}`
  全选/全不选某表全部列。不提交 showcol 时服务端只回 `inputobjs_*` 列
  （xpsp 这种多表星表会按表分组，实测 139 张表 287 个可选列）。
- 每列五个子字段：`{table}.{col}.operation`（select）、`.constraint`、
  `.min`、`.max`、`.textarea`、`.file`。operation 取值（**站点表单的
  `select` 取值表本轮未抓到**，见 §6bis 的登记行；下面这一列是**站点行为**取证，
  不是表单下拉的抄录）：
  `equal/notequal/less/lessequal/grater/greaterequal/between/contains/in`
  —— ⚠ **其中 `grater` 已被实测推翻，不可当方言用**：同锥 `greaterequal min15`
  回 **1559** 行而 `grater min15` 回 **0** 行（回包 426 B，仅表头 CSV），两者只差
  一个字母，行为天壤之别。**站点的 strict-greater 拼写尚未取证**，本仓不做
  `greater→grater` 映射（详见 §6bis「未知 `.operation` 返空表」行）。
  JS 按 operation 切换输入组：
  `between`→min/max；`in`/`contains`→textarea；其余→单值输入。
  每列另有 `.file` 上传口（accept `.txt,.csv`，默认 disabled）。
- `sort={table}.{col}` + `order=desc` 复选框：提交时即定序。
- `output.fmt` select：`csv/txt/json/votable/html`（**html 是默认且是唯一
  能拿回 sqlid 的取值**）。

### 2.4 CSRF 与 AJAX 约定（站点 JS 证言）

- 表单页内嵌隐藏 `csrf_token`；`script.js` 的 `$.ajaxSetup` 对所有非
  GET/HEAD/OPTIONS/TRACE 同源 AJAX 加 **`X-CSRFToken` 头**。
- `ajaxError` 统一 toast：优先读 JSON 的 `message` 字段，否则
  "Server error, please try again later."。
- `is_authenticated` 为真时每 30 s 轮询通知角标端点（登录后才出现）。

## 3. 结果页交互（sqlid 页）

结果页是 easyui datagrid 外壳 + 一组导出/推送动作（`search-result.js` 证言）：

| 交互 | 机制 | 协议细节 |
|------|------|----------|
| 网格取数 | `POST {sqlid_url}?output.fmt=dbgrid` | body `page=1&rows=100&sort=ps1_source_id&order=asc`；pageList [20,50,100,300]；rownumbers；多选 checkbox；**服务端分页排序**（clientPaging:false） |
| Save page / Save all | `open_link(get_saveas_url(fmt, save_page))` | GET `{sqlid_url}?output.fmt={fmt}`；save_page=true 时附带 `rows&page&sort&order`；fmt ∈ votable/csv/json |
| SAMP 推送 | `samp_notify(save_page)` | `samp.Connector("China-VO Data")` 发 `table.load.votable`，URL = `{sqlid_url}?output.fmt=votable[&page params]`；桌面端 TOPCAT 等可接 |
| 选中行下载 | `download_selected(url, fmt)` | 隐藏表单 POST `{csrf_token, output.fmt, id[]}`（id 为选中行 `id_column_name` 值，ps1 为 `ps1_` 前缀） |
| 整会话下载 | `download_sqlid(url, fmt, sqlid)` | 隐藏表单 POST `{csrf_token, output.fmt, sqlid}`；target=_blank |

智能体等价实现：Save all = 不带 rows/page 的 GET；dbgrid 不必复刻（§6）。

## 4. 两阶段协议要点（智能体最容易踩的五件事）

1. **`output.fmt=html` 才回 sqlid**；csv/json/votable/txt 直接内联数据。
2. **`pos.radius` 是角秒**（传度 → 0 行或 360 倍半径）。
3. **列名前缀分岔**：`/q` 内联响应给裸名（`ra`/`gpsf`），`/sqlid/` 分页响应给
   带前缀名（`ps1_ra`）；带空间约束时再前置 `inputobjs_*`。
4. **CSV 响应体带 UTF-8 BOM**，按 `utf-8-sig` 读；`fits` 不受支持（返回 HTML），
   要 FITS 走本地转换（`src/serialization.py::write_fits` 已是先例）。
5. **分页是绝对偏移**：`page=N & rows=M` 表示「跳过前 `(N-1)*M` 行再取 M 行」，
   **页号与页大小是绑定的同一个量**。所以 `rows` 一改，同一个 `page` 指向的
   是**完全不同的数据集**；断点只存 `next_page` 而不存 `page_size`，
   续传会从错误的偏移起算并**静默丢行**（实测见 §6bis，判据与数值见
   `docs/architecture/pitfalls.md` E-5）。`build_page_url` 收 `page` 与
   `page_size` 两个形参正是这个语义的直接后果——它不是"两个可独立调的旋钮"。

> **智能体用法**：要续传就把 `(sqlid, page, page_size, sort, order)` 当成一个
> **不可拆的元组**一起存取。`sort` 同理——无 `ORDER BY` 时服务端行序不保证稳定，
> 中途换排序列等于换了数据集（§6bis「分页排序非确定」）。

## 5. 登录态边界（无管理员权限下的真实边界）

- 公开数据面（查询/分页/计数/列元数据/名称解算/文档）**无需登录**。
- `/jobs`（User-Defined：上传 FITS 响应曲线生成标准星）必须登录；
  未登录访问 308→`/jobs/` 再 302→`/user/login?next=…`。**第一跳是站点表单
  登录页（Django session），不是 OAuth 页**（2026-09-27 实测）——即开 `/jobs`
  先要有 BEST 站点账号（凭据面：CLI `--auth-user` + env `ASTRO_BEST_PASSWORD`，
  `BestAuth` 可覆盖；历史 env `BEST_API_USER/PASS` 已退役无消费方），NADC 通行证
  OAuth 是站点登录页里的第二跳。双轨制与上线清单见 `references/auth-and-oauth.md`。
- **OAuth 授权链实证**（复查：未登录 `GET /user/oauth2/login/nadc`
  → 302）：
  `oauth.china-vo.org/oauth/authorize?response_type=code&client_id=TfiNrZZBgQRVjxDd59FV9L4B&redirect_uri=https://nadc.china-vo.org/data/best/user/oauth2/callback/nadc&scope=profile&state=<32hex>`
  —— 站点自身 OAuth 应用 **client_id=`TfiNrZZBgQRVjxDd59FV9L4B`**；授权后回调路由是
  **`/user/oauth2/callback/nadc`**（`/login/nadc` 是发起路由，两者不同，早期文档曾混用）。
- 真实作业流还需 NADC 应用审批的 client_id/secret —— **blocked-on-approval**；
  本 skill 的 `src/auth/` OAuth 层按 Authorization Code 实现（凭据走 env），契约见
  `contracts/oauth.contract.yaml` 与 `ALGORITHM-SPEC.md` §4。

## 6. Live 状态快照（复测前以此为准）

> **2026-09-29 全量复核**（`temp/audit_endpoints_live.py` /
> `temp/audit_dbgrid_recheck.py`）：路由表逐条重采，两阶段协议
> （POST /ps1/q → sqlid=s4351 → CSV + getcount total=174）、`/nss/solve`
> （M31 解算 2.8s）、12 张星表表单页（csrf + showcol 俱在）全部正常；
> 软 404 惯例不变。下表为**当前有效快照**，旧快照中已被复测改写的行以
> 2026-09-29 列为准。

| 项 | 状态 | 证据 |
|----|------|------|
| 两阶段 GET 协议 | ✅ 正常 | sqlid=s4351 链，CSV 664 B，getcount total=174 |
| `/nss/solve` | ✅ 正常 | M31 → ra=10.68470833, dec=41.26875；失败返回 ±1000 哨兵 |
| 表单页/列元数据/分组页/文档页 | ✅ 正常 | 12/12 表单页 200 且有预期内容 |
| **dbgrid 数据口** | ❌ **匿名会话不可用（现象已变）** | 2026-09-29 复测：浏览器风格 POST 123ms 快速返回 `{"error":"Internal Server Error"}`（旧快照记 ">75s 挂起"，站点行为已变，结论方向不变）；GET csv 等价路径正常 |
| `/jobs` 作业流 | ⛔ blocked-on-approval | 需站点账号登录（第一跳是表单登录页）+ NADC OAuth 审批 |
| SkyMapper DR4 | ❌ 不可查询 | 文档页列出但 `/skymapper_dr4/f` 软 404 |
| `/user/email-exists` | ❌ 疑已下线 | 2026-09-29 复测软 404（script.js 仍证言，端点本身已不可用） |

**对智能体的含义**：站点自身的网格数据通道不可用作数据源；以
GET `/sqlid/{id}?output.fmt=csv` 为权威取数路径（本 skill 的 `BestClient`
即此设计）。dbgrid 缺陷的两种历史表现（挂起/软错误）都记录在
`rag/knowledge/lessons_learned.yaml: L-dbgrid-endpoint-hangs` 与
`L-site-behavior-drift-recheck`。

## 6bis. 补充实测（协议细节定稿）

| 项 | 结论 | 证据 |
|----|------|------|
| **filterRules 冗余** | phase-1 约束键已作用于 sqlid 会话本身： razor-thin 约束（ps1_rpsf between 15.0–15.001）带/不带 filterRules **均 0 行**；站点自身 datagrid URL 亦无此参。skill 侧反推的 EasyUI filterRules 二次约束已移除（P1-4） | `temp/live_filterrules_decisive_results.json` |
| **分页排序非确定** | 同一 sqlid 连续两次 GET（不带 sort/order）行数相同但**行序不同**（集合重叠仅 1/50）——无 ORDER BY 时服务端不保证稳定序；需要稳定分页必须显式 `sort`+`order`（P1-8 已接线索件） | `temp/live_filterrules_ab_results.json` |
| **注入的排序列可能整列为空（保证的边界）** | `build_page_url` 默认按星表注入排序列，但**注入只在服务端认这一列时才是定序保证**：ps1 注入 `ps1_source_id`，而该列在 2026-10-05 实测里 174/174 行为空（`output.fmt=dbgrid` 回包同批复核：全 `null`）—— 对 ps1，注入的排序列是**空操作**，行序实际由**未声明的服务端行为**决定。本轮观测**没有**出问题（跨两个独立会话、跨中断边界，产物逐字节相同，sha256 `68202e0a…`），但那是观测不是保证：站方改默认行序即可能静默重复/丢行。**「注入确定性排序列」是尽力而为，不对列为空的表生效**。⚠ 排序列是否为空**取决于天区与记录类型**：ps1 混对象记录（`source_id` 非空）与点源记录（整列空串），见下一行 —— 同一个注入在不同天区可能有效也可能无效。**2026-10-05 逐表实跑订正**：本行「其它星表未逐表验」已作废 —— 12 张表逐张建档（85 请求零失败）实测，登记的排序列里**只有 `ps1` 是空列**，其余 9 张有数据的表排序列全部非空且 asc/desc 双向单调（`landolt`/`jplus_dr3` 覆盖恒 0，**未取证**）。逐表清单与 `uss_dr1` 的 `desc` 陷阱见 **§11** | `temp/h3/live_probe.py`（ps1 60″ 整页，`ps1_source_id` 非空 0/174）+ `temp/h3/dbgrid.json`；跨会话字节一致性见 `temp/VERIFY-G6-live-download.md` 场景 1；全表订正见 `temp/VERIFY-J3-catalog-coverage.md` 与 `temp/FIX-K3-knowledge.md` |
| **getcount（约束会话）** | 稳定可用：r=120″ → 770（独立复取一致）；r=600″ → 156676（正确置 truncated）。V-4 解除 | `temp/live_getcount_results.json` |
| **proximity 批量** | `pos.type=proximity` 多行文本可用至 **N=1000**（745 命中/约 3s，无文本区长度限制）；12 张星表默认投影全部返回星表列（V-2/V-3 解除）；响应元数据列带 `inputobjs_` 前缀且 `input_line` 为 1-based | `temp/live_proximity_p1_8_results.json` |
| **ps1 空值哨兵是「带」不是「定点」** | ps1 无测光列回 **≈-1000 哨兵带**，**不是某一个浮点值**。2026-10-05 实测（ps1 @180,30 60″，整页 174 行）：`ps1_gpsf` 148/174 行哨兵，在 2 位小数上就分裂成 `-1004.07`(103) + `-1004.08`(45)，完整浮点散布 `-1004.0787842744421` ~ `-1004.0726439746845` —— **浮点精确相等只命中 1/174**。每个波段的带心还各不相同：g≈-1004.07 / r≈-1003.88 / i≈-1003.54 / z≈-1002.88 / y≈-1001.94；`*_err` 列则是精确的 `-999.0`（149/109/136/142/134 行）。**2026-10-05 K1 逐格复算**（把这行升为【入库快照】级，且**结论变强**）：① 上面 174 行那组数字在 `live_ps1_ra180.0_dec30.0_r60.0as` 上**逐项复现**（`gpsf` 带内 148、`gpsf_err` -999.0 149、`rpsf` 135、`zpsf` 133）；② 换 1000 行样本（`live_ps1_ra180.0_dec30.0_r300.0as`）量**规模**——5 个 psf 列落在带内共 **3861 格，且每一格都是互不相同的浮点**（`gpsf` 878 / `ipsf` 742 / `rpsf` 625 / `ypsf` 817 / `zpsf` 799，去重数 = 计数），2 位小数上的取值个数**逐列不同**：`gpsf` 2 个（-1004.07 / -1004.08）、**`ipsf` 3 个**（-1003.53 / -1003.54 / -1003.57）、`rpsf` 3 个、`ypsf` 1 个（-1001.94）、`zpsf` 4 个 —— 即**连 2 位小数枚举都覆盖不全**，带内"写死相等"的命中率是 **0**；同批 5 个 `*_err` 列是精确 `-999.0` 共 3867 格。故**枚举两三个点覆盖不了**，只能按带：全带上沿 `-1001.9397837161488`，带外最近合法值 `16.20364086044799`（同帧 `ipsf=19.49` 为真值），阈值取其间即可 —— `BestSource.NULL_MAGNITUDE_SENTINEL = -999.0` 与 `src.tap.formats` 共用该阈值，守门测试 `test/unit/models/test_sentinel_band.py` 把**带内每个实测端点**都钉成缺测。⚠ **带外比较同样被污染**：`less 16` 在 300″ 锥里回 3554 行 = 真实值 + 约 3545 行哨兵（哨兵比 16 小得多），因此服务端按 PSF 列做上限筛选时会把「没测光」的源算成「暗于极限」—— 本地带判定救不回服务端计数 | `temp/h3/live_probe.py` + `temp/h3/live_report.json`（2026-10-05 实站）；前轮 `temp/diag_proximity_row.py` |
| **未知 `.operation` 返空表（不是忽略）** | 白名单外的操作符站点**既不报错也不忽略**，而是收下后返回**空表**。2026-10-05 逐项实测（ps1 @180,30 300″，同锥无约束 total=5109，每项一个独立 sqlid）：`between 15..16`→**4**、`greaterequal min15`→**1559**、`less/lessequal max16`→**3554**、`equal 15.5`→0，而**拼错的 `greatr` max16 与「方言」`grater` min15 都 total=0**（回包是 426 B 的表头 CSV，`confirm_operation.py` 逐行看过）。**推翻了旧登记的「strict-greater 站点拼写为 `grater`」**：`grater` 与 `greaterequal` 只差这一个字母，行为天壤之别。旧文档那句是本仓 `greater→grater` 映射的唯一依据，而那条映射实际是一条「把可读操作变成静默空结果」的路径，已删除。现状：`src.protocol.ALLOWED_OPERATIONS` = equal/notequal/less/lessequal/greaterequal/between/contains/in，白名单外显式 `ValueError`（fail-closed，铁律 5）；站点的严格大于拼写**尚未取证**，本仓不做映射 | `temp/h3/probe_operation2.py` + `temp/h3/confirm_operation.py` + `temp/h3/operation_probe2.json`（2026-10-05 实站） |
| **`ps1_source_id` 值分布随天区变** | 该列在回包中恒存在，但**只在「对象记录」子集里有值**，「点源记录」子集整列为空串。判型判据 = 该列是否非空。r=600″/300 行三天区实跑观测：非空行数 (286.1,15.7)=**128**、(180.0,30.0)=**0**、(10.68,41.27)=**0** → **"ps1 没有可用 id"是错的局部结论**。precise（`in` 约束）下载对 ps1 恒 0 行故改走 proximity 坐标上传 —— 那是**下载路径**的结论，不是这一列的属性。完整分型与五种"无值"编码见 `references/data-formats.md` §5c | ⚠ **分两层说证据等级**：(1)「两型互斥、分段连续、覆盖位置相关」这个**结构**现在是【入库快照】级 —— `live_ps1_ra359.5_dec0.0_r1800.0as` 1000 行里 A 组 431 行占索引 0–430（**前段连续**）、B 组 569 行占 431–999，对象级列 `class_star`/`ruwe`/`parallax` 在 A 组 431/431 非空、在 B 组 0/569（**严格互斥、零例外**），完整分型见 **§11.6**；(2) `(286.1, 15.7)` 的 **128/172 那个数**仍只是【临时实跑】—— 来自 `temp/G8-LIVE-ps1-recordtype.py` 的 2026-10-05 实站运行，该脚本在 gitignored 的 `temp/`（`git ls-files temp` = 0 行）、**换机拿不到**，此数**不能用入库素材复算**。⚠ 旧稿「仓内**没有任何** ps1 快照覆盖 (286.1, 15.7)」**不准确**：确有一份 `ps1_ra286.1_dec15.7_r5as`，但它是 **L 类反推构造**（`snapshot.yaml` 自述「零联网」，列是落盘投影而非回包原样），5 行的 `source_id` **5/5 全空**，**仍不能用来判型**。要长期可复核 (286.1, 15.7)，得把该天区的**回包原文**落成快照。 |
| **分页是绝对偏移** | `page=N & rows=M` 是**绝对偏移**，不是会话内游标：`page=2&rows=100` 的 100 行与 `page=1&rows=1000` 的 `[100:200]` **逐行完全相同**（`offset_semantics=true`）；同参数二次取回完全一致（`repeatable=true`）。判据取「逐行相同」而非「零重叠」——`page1 ∩ page2` 实测交集 1 行，服务端无 `ORDER BY` 时行序本就不稳定（见上一行）。**页号与页大小绑成同一个量，续传必须成对存取** | `temp/LIVE-PAGING-results.json`（sqlid=s4943，ps1 锥搜 180/30 r=300as，脚本 `temp/LIVE-PAGING.py`） |
| **sqlid 前缀有两套形态** | 取页要 **`s` 前缀**，`getcount` 要**裸数字**，写反任一个都是 22 B 软 404：同一 `s4958` 同一页，`/sqlid/s4958?…&rows=100&page=1` → **24997 B 真实 CSV**，`/sqlid/4958?…` → 22 B `{"error":"Not Found"}`；`/sqlid/4958/getcount` → 15 B `{"total":5109}`，`/sqlid/s4958/getcount` → 22 B。`src.protocol.parse_sqlid` 保留前缀交给 `src.protocol.build_page_url`，只有 `src.protocol.count_sqlid` 才 `removeprefix("s")` | `temp/LIVE-SQLID-PREFIX-results.json`（脚本 `temp/probe_f8_sqlid_prefix.py`） |
| **每页 CSV 都重复一遍表头；第 2 页起 BOM 落在单元格里** | 分页响应的**每一页都自带一行表头**，不是只有第 1 页有。把多页原文直接拼接（`ops/live_fetch.py:290` 就是 `"\n".join(...)`，**不去头**）时，**每翻一页就多出一行"表头行"**；且该行首格带 `\ufeff` —— **BOM 落在行内单元格里**，`utf-8-sig` 只吃文件开头那一个，**吃不掉它**。后果两条：① 「非空 `source_id` 计数」被灌水（伪数据行该单元格里是字面量 `ps1_source_id`）；② 对该格 `float()` 抛 `ValueError`。实测：`live_ps1_ra180.0_dec30.0_r300.0as_max4000/rows_full.csv` 共 4003 行 = **4000 数据行 + 3 行表头**（索引 1000 / 2001 / 3002，首格 `\ufeffinputobjs_dist_arcsec`）—— 同一次 4000 行拉取里 `ps1_source_id` 的「3 个非空」**全是这 3 行伪数据，对象记录实为 0 行**。按列名取值（`protocol.parse_csv_rows`）不受影响；**按位置取值、或直接数非空格的代码要显式剔掉表头行** | **证据等级【入库快照】**（逐字节可复算）`[已净化]groundtruth/snapshots/live-2026-10-04/live_ps1_ra180.0_dec30.0_r300.0as_max4000/rows_full.csv` + `ops/live_fetch.py:289-292` |
| **断点续传跨会话、跨任务都不串味** | ① 单表中断→续传：产物与**另一个独立会话**的一次性下载**逐字节相同**（ps1 @180,30 300″、`page_size=200`、5109 行 / 26 页，sha256 `68202e0a…`；续传 **0 个 POST**、复用同一 sqlid，起点 = 断点 `next_page`，成功后断点已删）。② 双任务并发跑：两断点 sqlid 独立、已落盘行集**不相交**（\|A\|=199、\|B\|=160、交集 **0**），续传后各自行集与「**同会话整读**」对照组**逐行同序相等**（300/300、160/160，缺 0 多 0）。判据取「同会话整读」而不是「另起一次全新下载」——跨会话行序站点没承诺（ps1 注入的排序列是空操作，§11.1），那样比会把行序漂移混进结论。⚠ **「无重复整行」不是站点保证**：ps1 300 行里有 **1 整行重复 3 次**，同会话对照组**同样**如此 → 重复来自回包内容本身，不是续传造出来的。选行身份键别用「整行唯一」：该批 ps1 的 `source_id` 300/300 全空、坐标里也有 2 对重复，**坐标同样不是可靠行键** | **证据等级【临时实跑】** `temp/VERIFY-G6-live-download.md` 场景 1（110 请求全 200）+ `temp/VERIFY-J6-concurrency.md` §3（其断言表 2 项 FAIL 均非正确性缺陷：一条是判据本身错 —— "无重复整行"那条，见上；一条是本表下一行的间隔欠量） |
| **并发没有击穿限流；但 429 处理仍未取证** | 产品缺省 `max_workers=2` 的真实并发（两条 worker 线程的请求在时间轴上交织）下，四轮实测**最小请求间隔 1.9856 s vs 配置 2.0 s，最大欠量 0.72%（≤14.4 ms）**——限流**没有被静默减半**。根因：限流只钉住「节流释放时刻」之间的间隔，而**上线时刻 = 释放时刻 + 该请求的准备耗时**（DNS/TCP/TLS/连接池/调度），相邻两次准备耗时之差就是那 ≤14.4 ms（离线探针实测打点本身只造成 1–55 µs，时钟分辨率也已排除）。68 次请求**零 429 / 零 `Retry-After` / 零重试 / 零超时**。⚠ **因此不能说「429 处理正确」**：真实 429 下的 `Retry-After` 兑现、退避序列、以及「被重试的 GET 会不会重新过限流时钟」（重试发生在 `session.get` 内部，即限流已返回之后）本轮**零证据**，属**未取证** —— 既不是「已验证没问题」，也不是「已确认有缺陷」 | **证据等级【临时实跑】** `temp/VERIFY-J6-concurrency.md` §1–§2（四轮请求时间线 + 离线 delta 探针） |

## 7. 复现方法（本文取证步骤）

1. Playwright（Chromium）打开 `/ps1/f`，`page.on("request")` 记录全部
   xhr/fetch/document 请求与 post body（`temp/site_dive/network.json`）。
2. 填 cone 字段 `f.submit()` → 结果页；等 6 s+ 抓 dbgrid 请求/响应
   （`run3_requests.json` / `run4.py`：确认无响应事件）。
3. 点 `#solvename`（填 M31）→ 抓 `/nss/solve` 请求与 JSON 响应。
4. 抓 `static/js/script.js`、`static/js/search-result.js` 全文，提取
   csrf/ajaxError/nss/saveas/samp/download 逻辑。
5. 对候选路由逐一 GET，记录状态码 + 响应体前 60 B 区分软 404
   （复查新增 18 个候选路由：`/search` 站点搜索页、`/user/logout`
   重定向存根、`GET /{catalog}/q` 结果页行为、OAuth 302 全参数；
   证据 `temp/endpoint_sweep.json` / `temp/endpoint_details.json`）。
6. 表单字段清单：正则 `<input|select|textarea` 的 name/id（204 个字段名，
   30 列 × 5 约束子字段）。

## 8. IVOA TAP + OAuth 历史资产迁回忆审

「以前做过的 IVOA 标准接口与鉴权」位置与现状，供后续轮次查考：

| 资产 | 历史位置 | 现状 |
|------|----------|------|
| TAP 网关（ADQL 子集/执行器/VOTable/UWS/http.server 路由） | pybest 打包产物树（git `6f00efeb^` 可取回；该树在 **best 分支**被 `6f00efeb`「Phase 8 扁平化」整体删除，master 分支亦无） | **已迁回** `src/tap/`（adql/executor/formats/jobs/client/service，传输层按零依赖原则用 stdlib `http.server` 重写）；设计稿同树可取回 |
| NADC OAuth2.0 客户端 | 同树 `oauth.py` + `services/{server,auth_store}.py`（已随 `6f00efeb` 扁平化删除，git `6f00efeb^` 可取回） | **现行版即其演进**：`src/auth/nadc_oauth.py`（多出 TokenStore 0600 缓存、登出、手动粘贴兜底）+ `contracts/oauth.contract.yaml` + `test/unit/auth/`；无需回迁 |
| 上游兼容回归测试 | 同树 `tests/test_tap_*.py`、`test_oauth.py` | **已删除**（经用户批准）：18 个文件 import 不存在的 `pybest.*` 包，模块级 skip 恒不执行；其高价值断言（Range 206/416、OAuth state 校验、字节级续传）在 `test/unit/tap/`、`test/unit/auth/`、`test/unit/download/` 已有等价覆盖；git 历史可取回 |

**教训**：这套资产当年随打包目录被扁平化重组误删（非刻意下线），且删除后只剩
skip 守卫、无任何可见线索——结构清理时必须先确认被删树的能力是否已被新位置覆盖，
并在 references 留迁移锚点（本节即补做）。

## 9. 2026-09-29 端点/列全覆盖审计（教师专项：一键接入 skill 的问题清查）

本轮对"站点全部功能与端点 ↔ skill 覆盖"做了一次全量对账
（`temp/audit_endpoints_live.py` / `temp/audit_column_drift.py` /
`temp/audit_acceptance_full_coverage.py`，证据 JSON 同名在 temp/）。

### 9.1 端点覆盖矩阵（结论：数据面全覆盖，非数据面有意不实现）

| 站点端点/功能 | skill 覆盖 | 说明 |
|---|---|---|
| `POST /{catalog}/q`（建会话） | ✅ | `src.client.BestClient.submit_phase1` / `src.protocol.build_query_form` |
| `GET /sqlid/{id}?output.fmt=`（分页/导出） | ✅ | `build_page_url` 单点；csv/txt/json/votable 四格式 |
| `GET /sqlid/{numeric}/getcount` | ✅ | `BestClient.count` / `_count` |
| `GET /nss/solve`（名称解算） | ✅ | `resolve_name` + 哨兵判定 |
| proximity 批量坐标匹配 | ✅ | `crossmatch_batch`（服务端一次提交，实测 N=1000 可用） |
| 表单页 `/{catalog}/f`（列元数据） | ⚠️ 静态镜像 | `CATALOG_COLUMNS` 逐星表登记线上列清单（见 9.2），不实时抓取；列数由 wire-fact 门禁钉住 |
| `/t/{table_id}`（内部表元数据页） | ➖ 有意不实现 | 仅暴露内部库表名，无智能体消费价值 |
| dbgrid 数据口 | ➖ 有意不实现 | 站点侧缺陷（§6），GET csv 是等价且权威的路径 |
| SAMP 推送（`table.load.votable`） | ➖ 有意不实现 | 浏览器→桌面端（TOPCAT）桥；智能体直接 GET votable 即可，无头环境无 SAMP |
| 选中行下载 / 整会话下载（隐藏表单 POST） | ⚠️ 等价实现 | 站点 UI 的 POST 表单动作；skill 用不带 rows/page 的 GET（Save all 语义）覆盖，约束由 phase-1 会话表达 |
| `/search` 站点搜索 | ➖ 有意不实现 | 无字段名/query 参数未证，非数据面 |
| `/user/email-exists` | ➖ 端点已下线 | 2026-09-29 复测软 404 |
| 通知角标（`is_authenticated` 时轮询） | ➖ 有意不实现 | 纯 UI 面 |
| `/jobs`（User-Defined 星表） | ⛔ blocked | 需站点账号 + NADC OAuth 审批，见 §5 与 `auth-and-oauth.md` |

### 9.2 本轮发现并已修复的问题（按严重度）

1. **静态列白名单与线上漂移（数据面静默事故，已修 + 门禁）**：
   smss_dr4/uss_dr1 已被站点按波段重构——旧登记列
   （smss: `source_id`/`ra`/`dec`/`psf_mag`；uss: `source_id`/`ra`/`dec`/`psf_mag`）
   全部下线成**幻影列**，服务端静默丢弃未知 showcol 键：smss 默认投影只剩
   ra/dec（星等整列消失），uss 响应退回无表头全表（解析出 92 个
   `metadata_*` 幻影列）。同时 gaia_dr3_18（27/155）、scr_galah、
   scr_lamost（各 33/137）、xpsp（11/287）只登记了线上可选列的一小部分，
   qualify_column fail-closed 让其余列不可请求。已按线上全量重写
   `CATALOG_COLUMNS`/`CATALOG_FORM_TABLES`/星等映射，验收 12/12 星表
   默认投影**零静默丢列**。
2. **xpsp/dr3xpcorr 响应前缀是表单表名不是星表名（已修）**：其位置/Gaia
   测光列在共享表 `gaiaxp_photinfo_replenish`，响应列名是
   `gaiaxp_photinfo_replenish_ra` 而非 `xpsp_ra`；`from_row` 只剥星表
   前缀，导致这两张星表的 BestSource 位置/星等整列静默丢失（锥搜"成功"
   但是空壳）。已改为剥离"星表名 ∪ 全部表单表名"（长前缀优先）。
3. **幻影排序列被静默忽略（已修）**：P0-1 注入的 `sort=smss_dr4_source_id` /
   `uss_dr1_source_id` 随星表重构失效，服务端不报错不排序（asc/desc 行序
   相同即判定），分页定序对这两张星表退回无序。已改指线上真实列
   （`smss_dr4_ra` / `uss_dr1_ra_u`，asc/desc 反转实测生效）。
4. **文档漂移（已修）**：`/user/email-exists` 已下线（软 404）；
   `calib/` 前缀只对 calib 组成员有效；dbgrid 从"挂起"变为"快速软错误"。

### 9.3 残留已知限制（站点侧，非 skill 缺陷）

- `ps1_source_id` 的**值分布随天区变**（2026-10-05 更正，原记"线上为空"）：
  该列只在对象记录子集里有值，点源记录子集整列为空；`sort=ps1_source_id`
  在**全点源记录**的结果集上空转。2026-09-29 复测服务端自然序当前稳定
  （同页 3 次一致、3 页零重复），保留站点 datagrid 同款 sort 值作防御。
  分型判据与实测见 `references/data-formats.md` §5c。
- uss_dr1 无规范化 ra/dec（按波段各自测量）：BestSource.ra/dec 为 None，
  原值在 `raw_data`；星等 12 波段正常。
- landolt 在三个标准探测锥区无源，sort 未能在本轮复验（列覆盖已验证）。

### 9.4 复跑方式（站点再漂移时）

```bash
python temp/audit_endpoints_live.py        # 路由全表复采
python temp/audit_column_drift.py          # 列清单双向 diff (线上 vs 静态)
python temp/audit_acceptance_full_coverage.py  # 12 星表默认投影零丢列 + sort 生效验收
python -m pytest test/unit/meta/test_catalog_registry_live.py -q  # wire-fact 门禁
```

## 10. 2026-10-04 真实回包全表普查（快照持续补跑入库，`live-2026-10-04/` 下 33 个目录）

§6bis 的证据来自 2026-09-29 的**表单页解析 + 单行探测**；本节来自一次系统普查：
12 张可查表逐张实抓，回包**逐字节落盘**并记 `manifest.json`（sha256），
素材在 `[已净化]groundtruth/snapshots/live-2026-10-04/`（该子树下 **33 个快照目录 / 230 个文件**，
**已入版本库**；其中 31 份带 `rows_full.csv`，另 2 个 `live_raw_*` 目录是
软 404 / 原始响应的取证件、不含表），抓取工具是 `ops/live_fetch.py`（默认
dry-run，纪律见 §10.6），条件豁免全文见 `docs/EVAL-LIVE-FETCH-WAIVER.md`。

> ⚠ **"份数"一律要带作用域**（K1 复核，2026-10-05 逐个数过）：`33 / 230 / 31` 指的是
> **`live-2026-10-04/` 这一个子树**；整个 `[已净化]groundtruth/snapshots/` 是
> **10 个顶层目录 / 290 个文件 / 39 份 `rows_full.csv`**，多出来的是 3 份顶层
> ps1 快照 + `std_scr_galah_live` + 8 个 `syn_*` 合成集（合成集不是站点回包，
> **不参与任何站点事实的取证**）。§11 各处引用的"31 份"同此口径。

本节只写**回包本身证明**的结论。凡是"应该如此"而非"实测如此"的，一律留在 §6bis。

### 10.1 坐标列形态：12 张表实测 5 种，**不能硬编码**

| 星表 | 坐标列形态 | 实测依据 |
|------|-----------|---------|
| `ps1` / `stripe82` / `gaia_dr3_18` / `smss_dr4` / `splus_dr4` / `landolt` / `jplus_dr3` / `scr_galah` / `scr_lamost` | `{表名}_ra` / `{表名}_dec` | 9 张表一致 |
| `xpsp` / `dr3xpcorr` | `gaiaxp_photinfo_replenish_ra/dec` —— **前缀是共享位置表名，不是星表 id** | 291 / 21 列回包 |
| `uss_dr1` | **没有任何一列以 `_ra`/`_dec` 结尾**：分波段 `ra_u` / `ra_j0378` / … | 96 列回包逐列核过 |
| 全部 12 张 | 都额外带 `inputobjs_input_ra` / `inputobjs_input_dec` | 那是**查询输入坐标**，不是源行位置 |

**这条不是理论洁癖，是一个已经踩过的真缺陷**：E2 的回放 transport
（原 [已净化]groundtruth/transport.py，已于 2026-10-07 随回放层退役删除，备份见
`docs/archive/replay-backup/`）原先把坐标列硬编码成裸 `ra`/`dec`，导致 20 个字段的保真验收
只有 13/20 通过。现改为三级回退 —— ① 裸形 `ra`/`dec` → ② 本表前缀 → ③ 任意同前缀配对
（表名从 POST URL 反解）—— 保真升到 **19/20**，双向自证钉在
`[已净化]groundtruth/tests/test_e2.py::TestQueryAwareCoordResolution`；
坐标解析的现行口径真值以本表 §10.1 与 `[已净化]groundtruth/canonical.py` 为准。

> **派生规则**：`inputobjs_*` 永远不能当源行位置；解析不出坐标时**记
> `coord_unavailable` 计数**，不许挑一个波段/一列凑答案（假坐标比 0 行更坏）。

### 10.2 表单权威键集：**7 个几何/交接键** + 可选 `sort`/`order`；手搓表单会**静默**退化成全表查询

`src/protocol.py::build_query_form` 生成的表单核心是 **7 个几何/交接键**（锥搜形态）：
`output.fmt`、`pos_group`、`pos.type`、`pos.racenter`、`pos.deccenter`、
`pos.radius`、`showcol`。

**「恰有 7 个键」只在不带排序参数时成立**，实测（`temp/G8_probe_formkeys.py`，
本轮实跑）：

| 调用 | 键数 | 键集 |
|---|---|---|
| 锥搜（不带 `sort`） | **7** | 上述 7 键 |
| 锥搜 + `sort`/`order` | **9** | 7 键 + `sort` + `order` |
| 矩形（`box=`） | **8** | `pos_group` / `pos.type` / `pos.ramin` / `pos.ramax` / `pos.decmin` / `pos.decmax` / `output.fmt` / `showcol`（`pos.radius` 换成 4 个边界键） |
| proximity（`radec_text=` + `nearest_only`） | **7** | `pos_group` / `pos.type` / `pos.radecTextarea` / `pos.defaultRadius` / `proximity_nearestonly` / `output.fmt` / `showcol`（半径键换名，且最近邻键**不叫** `cone_nearestonly`） |

> 键数随空间形态与排序参数变，唯一稳定的结构是：**`output.fmt` + `pos_group` +
> `pos.type` + 一组空间键 + 可选 `*_nearestonly` + 可选 `sort`/`order` + `showcol`**。
> 写死"7 键"的文档会在带排序的调用上直接对不上 —— 排序键是**显式传 `sort` 才注入**，
> `order` 只在 `sort` 存在时携带（`build_query_form` 里是同一个 `if` 分支，
> 单独发 `order` 会被站点忽略，见 §6bis「分页排序非确定」）。

**危险不在于少一个键会报错**——站点不报错。少提交 `pos.*` 三键时，站点按
**无约束全表查询**执行并正常返回分页结果：内联 CSV 可达数百 MB 量级
（历史记录称 uss_dr1 上约 637 MB，见 `best-database-guide.md`《使用约束》）。
调用方拿到的是一个"成功"的全表，于是把一次锥搜悄悄变成一次拉表。

> **规则**：构造查询表单一律走 `build_query_form`，不要手搓字典。手搓的唯一
> 合法用途是复现站点的**降级形态**做负例，且必须在代码注释里写明这是负例。

### 10.3 表覆盖实测：异常与正常稀疏必须**分开**报告

| 星表 | 探测天区（半径） | 实测行数 | 判读 |
|------|-----------------|---------|------|
| `ps1` | (180, 30) 5″/60″/300″ | 3 / 174 / 1000 | 正常，全天覆盖 |
| `ps1` | (10, −45) 60″ | 0 | 正常：南天低密度，验证"0 命中是合法结果" |
| `gaia_dr3_18` | (286.1, 15.7) 300″ | 1000 | 正常（撞 `rows` 上限，真实值 7193） |
| `uss_dr1` | (120.3, −20.4) 300″ | 1000 | ⚠ **不正常：锥形被丢弃** —— `total=1039801` 是全表行数（5″ 与 300″ 同值），1000 行**全部锥外**（角距中位数 ≈116.9°）。详见 §11.7 |
| `xpsp` | (10.68, 41.27) 300″ | 1000 | 正常（真实值 2268） |
| `smss_dr4` | (0, −30) 300″ | 106 | 正常（南天银道面） |
| `splus_dr4` | (10, −70) 300″ | 206 | 正常（南天） |
| `stripe82` | (30, 0) 300″ | 27 | 正常：Stripe 82 精测天区在赤道 |
| `stripe82` | (286.1, 15.7) 300″ | 0 | 正常：锥区落在 Stripe 82 之外 |
| `dr3xpcorr` | (180, 30) 300″ | 1 | 正常：极稀疏 |
| `smss_dr4` / `splus_dr4` | 北天非本 survey 天区 | 0 | 正常：survey 天区之外 |
| `scr_galah` / `scr_lamost` | 两个天区 300″ | 0 | 正常：300″ 太窄（1800″ 下分别 1 / 137 行） |
| **`landolt`** | (10.68, 41.27) 300″，共探测 45 处 | **全 0** | **正常稀疏，不是故障**：全表 45712 行摊到全天约 1 行 / 3.7 deg²，0.5° 锥期望命中 0.018 行。用它必须先有已知标准星坐标 |
| **`jplus_dr3`** | (10.0, −60.0) 300″，共探测 24 处（**探点在其公认天区 Dec −79..−45 之内**、最大半径 5°） | **全 0** | **疑似站点侧覆盖异常，待站方确认**（2026-10-04 复测：表单页 200 + 34672 B，**路由未死**；数据侧仍恒 0 —— 见 §10.8）。⚠️ 旧表把代表坐标记成 (120.3, −20.4)，那是 `uss_dr1` 的天区 —— 区外探到的 0 恰恰是「该表没覆盖这里」能解释的结果，据此说"疑似站点侧异常"等于把覆盖空洞讲成了站点故障（2026-10-05 订正） |

`jplus_dr3` 这条要把**已证**与**未证**分开说，否则会把一个站点问题误报成客户端缺陷：

- **已证（留档可核，`live_jplus_dr3_ra10.0_dec-60.0_r300.0as`，**探点在公认天区内**）**：`getcount` 与分页
  **自洽** —— 前者回 `{"total":0}`，后者回 HTTP 200 + 带 BOM 的 12 列表头 CSV +
  **0 数据行**。`protocol.is_soft_error()` 判 False、`protocol.parse_csv_rows()` 判
  0 行，两处判定都与回包相符；`capture_log.json` 三条请求证明**分页请求确实发出**。
  也就是说：站点此刻的表现与「该锥内真的没有源」**无法区分**。
- **未证**：此前仓内曾记「分页回软 404 而客户端报 success/0（`total=0` 时跳过分页取）」。
  **该说法与留档证据矛盾，已撤回** —— 客户端分页循环条件是
  `total_fetched < max_rows`（`src/client_paging.py`），不看 `getcount`；且该快照内
  不存在软 404 形态。要坐实"坏表"需要的是站方日志，不是客户端改代码。

> **为什么必须分开写**：`landolt` 与 `jplus_dr3` 都表现为"0 行"，但一个可由
> 密度估算解释、另一个不能。把两者合并成"两张表没数据"，会让站方接到一条
> 无法定位的报障，也会让我们自己误判素材可用性。两条原文登记在
> `ops/live_fetch.py::COVERAGE_NOTES`。

### 10.4 `uss_dr1` 的分波段坐标：不可用优于猜一个

`uss_dr1` 1000 行 × 96 列里没有规范化坐标列，位置按波段各自测量
（`ra_u` / `ra_j0378` / …），与 §9.3 记的"BestSource.ra/dec 为 None、原值在
`raw_data`"一致。E2 的字段保真验收对这份快照记 **`coord_unavailable = 1000`**：
如实计数全部不可用，而**不是**挑一个波段（比如 `u`）当作全表坐标。

### 10.5 要留档真实软 404，必须绕开高层客户端

未知表名（如 `no_such_catalog`）在**发包之前**就被客户端的表名校验拦下，
抛 `ValueError: Unknown BEST catalog` —— 于是永远观测不到站点真实的软 404
形态。`ops/live_fetch.py` 为此保留了一条绕过校验层的原始 HTTP 路径专门用于
留档；**这是取证手段，不是可走的正常调用路径**（正常调用就该在本地拦下）。

### 10.6 抓取纪律（对站方友好优先于吞吐）

`ops/live_fetch.py` 的四条硬约束，缺一条就不该发包：

1. **默认 dry-run** —— 不带 `--execute` 一个请求都不发；
2. **不重试 POST** —— 重试会造孤儿会话、泄漏服务端配额；GET 的重试退避交给
   客户端 `HTTPAdapter`（`allowed_methods` 只含 GET）；
3. **串行 + 强制间隔**（≥1.5 s；`ops/live_fetch.py` 的 `--delay` 默认 1.5 s，
   与铁律 7(b) 同口径 —— 不得下调到 1.2 s 那类下界）；
4. **抓到数据 ≠ 金标准被独立核过** —— E2 的签字门禁已于 2026-10-04 整链取消
   并删除（工具链/签字单联/台账/报告字段均不存在），豁免只覆盖
   "素材从哪来"，不放宽任何判分口径。

### 10.7 proximity 回连列的三个坑（写解析器前必读）

实测依据：`live_ps1_proximity_n3_5d2580ec`（三个输入点，快照已入库）。

| 坑 | 实测 | 后果 |
|---|---|---|
| **`input_line` 是 1-based** | 三个输入点回显 `1` / `2` / `3` | 按 0-based 解读会**整体错位一格**：第 0 个输入的匹配被当成第 1 个。行集对不上却看不出是基准问题 |
| **`ps1_source_id` 在对象记录子集内也会重复** | `live_ps1_ra359.5_dec0.0_r1800.0as`（1000 行，其中 431 行为对象记录）里 431 个非空 id 去重后 **430** | 把 id 当唯一主键会让两行塌成一格，逐格比对随之变成"拿 A 行比 B 行" |
| **`ps1_source_id` 在点源记录子集整列为空** | 该快照另 569 行（点源记录）全为空串；另四份 ps1 快照**整个结果集**都是点源记录 | 同上 —— "有这一列"不等于"这一列能当主键" |

三条推论：

- **主键的可用性由结果集判定，不由列的存在判定**。`[已净化]groundtruth/canonical.py`
  的 `id_keys_unique()` 取集合内最小判据：出现重复即整批改用 `(ra, dec)` 量化键；
  两侧（被测侧与独立 oracle）各有一份同判据的实现，是 M1 可比的前提。
  **注意**：该判据只识别"重复"，**不识别记录类型** —— 对「以对象记录为主 + 少量
  点源记录」的结果集它仍会给 `source_id` 口径。已登记为待改进项
  （`[已净化]groundtruth/REPORT.md`「已知登记」第 8 条）。
- **proximity 的距离列只在提交了 `showcol` 时才带 `inputobjs_` 前缀**；不提交投影时
  服务端只回四列元数据且用**裸拼写**（`input_line` / `dist_arcsec` / `input_ra` /
  `input_dec`），一个星表列都不给。两种拼写都要认，否则会把"没有距离列"误读成
  "距离为零"。

> 这三条都不是从文档读来的，是 2026-10-04 那次逐表实抓撞出来的。**同中心的多个输入
> 点会被服务端并成一组回连**（冻结答案里没有分开的组）—— 要测"逐输入独立匹配"就必须
> 给互不相同的中心，且半径要够大（(180,30) 最近的源也在 3.587″ 外，`r=2″` 时三点全 0 命中）。

### 10.8 `jplus_dr3` / `landolt` 的最新实测：路由是活的，数据侧恒 0

§10.3 记的是"探测若干天区全 0"。本节补上 2026-10-04 的**两路对照**——同一批
天区分别走**权威客户端**与**裸 `requests`**——并据此把旧叙事改准。

**两路对照（`r=1800as`）**：

| 星表 | 天区 | 权威客户端 `cone_search` | 表单页 | 裸 requests `getcount` |
|---|---|---|---|---|
| `ps1`（对照） | (180.0, 30.0) | `success=True` / returned 100 / **total 215774** / truncated | 200，77490 B | `{"total":215774}` |
| `landolt` | (120.0, −20.4) | `success=True` / returned **0** / total 0 | **200，120062 B** | `{"total":0}` |
| `jplus_dr3` | (10.0, −60.0) 公认天区 | `success=True` / returned **0** / total 0 | **200，34672 B** | `{"total":0}` |
| `scr_galah`（对照） | (120.0, −20.4) | `success=True` / returned 1 / total 1 | 200 | `{"total":1}` |

证据：`temp/LIVE-COVERAGE-client-results.json`（脚本 `temp/LIVE-COVERAGE-CLIENT.py`）、
`temp/LIVE-COVERAGE-results.json`、`temp/LIVE-PROBE-results.json`（表单页字节数）。

**据此必须改准的三处说法**：

1. **不是路由 404。** `/jplus_dr3/f` 回 **HTTP 200 + 34672 B 真实表单**，
   `/landolt/f` 回 **200 + 120062 B**（csrf + showcol 俱在，见 §1 表单页行）。
   路由与表单都活着，**不能写成"表没了"**。
2. **数据侧确实恒 0。** `getcount` 对 jplus_dr3（两处天区）与 landolt（两处天区）
   稳定回 `{"total":0}`；客户端侧 `success=True / total=0 / pages_fetched=1`
   —— 失败语义与"真的没有源"**在回包上不可区分**，这一点 §10.3「未证」段已记，
   本节没有推翻它，只是把"路由活"这一半钉死了。**仍属可疑，待站方确认。**
3. **两者要分开报告。** `landolt` 的 0 命中是**统计可解释的稀疏**：全表 45712 行
   摊全天约 1 行 / 3.7 deg²，0.5° 锥的期望命中约 0.018 行——**这个 0 是正常的**，
   用它必须先有已知标准星坐标。`jplus_dr3` 是在**其公认天区**（Dec −79..−45）
   仍大面积为 0，**密度解释不了**。把两者合并成"两张表没数据"，会让站方接到一条
   无法定位的报障。

> **本节同时排除一个假象**：裸 `requests` 探针那六个天区的取页**一律**回 22 B
> `{"error":"Not Found"}`——**连 `total=215774` 的 ps1 也是**。那不是站点坏了，
> 是探针自己把 sqlid 的 `s` 前缀吃掉了（§6bis「sqlid 前缀有两套形态」）。
> **先怀疑自己拼的 URL，再怀疑站点**。

## 11. 2026-10-05 全 12 表实跑建档：逐表订正（J3 探测 + K3 复算）

本节是 §6bis 与 §10 的**逐表订正面**。证据分两跳，都在 gitignored 的 `temp/` 下：
J3 的原始回包与请求日志（`temp/j3/`，`requests.json` 73 条 + `recheck_requests*.json`
6+5+1 = 12 条 = **85 条请求，21 POST / 64 GET，状态码全 200，零重试**，19.9 MB），
以及 K3 的离线复算（`temp/FIX-K3-recompute.py` → `temp/FIX-K3-recompute.json`，
逐字节重读那 **17** 份 CSV，不发一个请求）。⚠ 这里的 **17 是 K3 那一轮的样本数**
（J3 原始回包的页级 CSV，`temp/j3/*_p1.csv`；该 JSON 的顶层键是 `per_csv`（17 项）
与 `best`（12 项）——**旧稿写的 `csvs` 键并不存在**），
**不是** §10 的入库快照集规模（`live-2026-10-04/` 下 33 个目录 / 31 份 `rows_full.csv`）——两处"份数"
各指各的，别混用。
**本节只写回包能证明的结论；"未取证"的地方一律照原样标"未取证"，不用推断填补。**

> **本节起逐条标证据等级**（全篇通用，四档 —— 混级是把"临时实跑"当精确事实的头号成因）：
>
> | 等级 | 含义 |
> |---|---|
> | **【入库快照】** | 能用 `[已净化]groundtruth/snapshots/` 下的字节**当场复算**（换台机器也复算得出） |
> | **【实跑】** | 有真实请求日志 + 字节级产物，但产物未入库（比入库快照弱一档） |
> | **【临时实跑】** | 只有 gitignored 的 `temp/` 观测，**换机拿不到**，不能复算 |
> | **【未取证】** | 探过但**没有结论** —— 不是"已确认不存在" |
>
> 典型降级案例：`ps1` 在 (286.1, 15.7) 的"128 行对象记录"是【临时实跑】，
> 同一现象的**结构**（两型互斥、分段连续）已由 (359.5, 0.0) 的入库快照独立支撑
> —— 见 §11.6。**数字要降级，方向可以留。**

### 11.1 注入排序列的保证有**明确范围**：只有 `ps1` 是空列

`PAGINATION_SORT_COLUMNS` 登记 13 个键（`gaia_dr3` 是 `gaia_dr3_18` 的旧拼写别名，
去重后对应 12 张表）。逐表实测**排序列本身**的空/非空（空 = 单元格空串或字面 `nan`）：

| 星表 | 登记排序列 | 回包表头里命中的列名 | 非空 / 数据行 | asc/desc 双向单调 | 判定 |
|---|---|---|---|---|---|
| `ps1` | `ps1_source_id` | 同名 | **0 / 1000** | 否（行序完全不变） | **整列为空 → 注入是空操作** |
| `stripe82` | `stripe82_calibstars_id` | 同名 | 27 / 27 | ✅ 字典序双向 | 真的在排 |
| `gaia_dr3_18` | `gaia_dr3_18_source_id` | 同名 | 1000 / 1000 | ✅ 数值双向 | 真的在排 |
| `smss_dr4` | `smss_dr4_ra` | 同名 | 106 / 106 | ✅ 数值双向 | 真的在排 |
| `splus_dr4` | `splus_dr4_id` | 同名 | 206 / 206 | ✅ 字典序双向 | 真的在排 |
| `xpsp` | `gaiaxp_photinfo_replenish_source_id` | 同名 | 1000 / 1000 | ✅ 数值双向 | 真的在排 |
| `dr3xpcorr` | `gaiaxp_photinfo_replenish_source_id` | 同名 | 120 / 120（1800″） | ✅ 数值双向 | 真的在排 |
| `scr_lamost` | `scr_lamost_source_id` | 同名 | 137 / 137（1800″） | ✅ 数值双向 | 真的在排 |
| `scr_galah` | `scr_galah_source_id` | 同名 | 1 / 1（1800″） | **未做对照**（样本仅 1 行，无从判序） | 列非空，方向性未取证 |
| `uss_dr1` | `uss_dr1_ra_u` | **裸名 `ra_u`**（剥前缀命中） | 1000 / 1000 | ⚠ asc 单调、**desc 不单调** | 列非空，但**方向有陷阱**，见 §11.2 |
| `landolt` | `landolt_source_id` | — | **0 数据行** | — | **未取证**（3 天区 × 2 半径全 0） |
| `jplus_dr3` | `jplus_dr3_ra` | — | **0 数据行** | — | **未取证**（2 天区 × 2 半径全 0） |

**因此"注入确定性排序列以防偏移翻页丢行"这个保证的范围是**：
在实测的 9 张有数据的表上**成立**（7 张数值双向单调 + 2 张字符串字典序双向单调），
**在 `ps1` 上无效**，在 `landolt`/`jplus_dr3` 上**未取证**（连一行都没有，无从发生丢行）。
§6bis 那句「注入的排序列可能整列为空」现在有了确切清单，不再是悬空的"可能"。

> **K1 用入库快照独立复算过这张表的"非空"半边**（2026-10-05，31 份
> `rows_full.csv` 逐份按登记列名落回包列名后数非空）：
> `stripe82` 27/27、`gaia_dr3_18` 1000/1000、`smss_dr4` 106/106、`splus_dr4` 206/206、
> `xpsp` 1000/1000、`uss_dr1` 1000/1000（裸名 `ra_u`）、`dr3xpcorr` 1/1（该快照只有 1 行）——
> **7 张是【入库快照】级**；`scr_lamost`（137/137）/`scr_galah`（1/1）因入库快照里这两个天区是
> 0 行，**仍只是【临时实跑】**。`ps1` 的"整列为空"同样在 11 份入库 ps1 快照上复算为
> 0/行（唯二例外：§11.6 那份混排快照 431 行非空，以及 max4000 那份的 3 行**伪数据表头**
> —— §6bis「每页重复表头」行；按该行口径，那 4000 行里的对象记录实为 0）。
> **升不上去的两格就写"临时实跑"，别跟着表格一起升格。**

⚠ **仍然只是尽力而为，不是契约**（结论未变，变的只是风险面比原先假设的小得多）：
服务端只按它认得的列排序；`ps1` 换天区会换成"对象记录"子集（`source_id` 非空），
那时注入又会生效 —— **同一张表的有效性随天区与记录类型变**。`landolt`/`jplus_dr3`
的空白要靠站方给出标准星坐标才能闭合。

### 11.2 `uss_dr1` 的 `order=desc` 会整页跨到 null 块 —— 显式 desc 是陷阱

排序列 `uss_dr1_ra_u` 是**按波段**的坐标列。同一 sqlid 会话（`s5051`）只改
`order=asc/desc`，各取两页 200 行实测：

| 页 | 行数 | `ra_u` 是 `nan` 的行数 | 该页不同位置数 | 与同方向另一页的交集 |
|---|---|---|---|---|
| `asc` p1 | 200 | **0** | 140 | — |
| `asc` p2 | 200 | **0** | — | **1 行**（见下方注） |
| `desc` p1 | 200 | **200（全页）** | 200 | **0 行** |
| `desc` p2 | 200 | **200（全页）** | — | **0 行**（重复取回**逐行相同**） |

`asc` p1 ∩ `desc` p1 = **0 行重叠** —— 两个方向给的是两批完全不同的行。
样例行 `ra_u`/`u_pstotal`/`ra_g`/`g_pstotal` 全 `nan`，而 `ra_z=358.1465`、
`z_pstotal=17.280886` 有值 —— 这些源**缺 u/g 波段测量、只有 z 波段有位置**。
末页（`total=1039801` → p5200）该页 1 行、`ra_u` 同样是 `nan`。
⚠ **该 `total` 不是锥内数**：见 §11.7「`uss_dr1` 静默丢弃锥形约束」——它与请求
半径无关（5″ 与 300″ 同值），是**全表行数**。用该表按位置取数时必须自行复核角距。
→ 服务端把 NULL 块在 `asc` 时压到末尾、在 `desc` 时顶到开头。

⚠ **"同一方向内行序稳定"只在 `desc` 侧有据**：`desc` p1 二次取回逐行相同、
p1 ∩ p2 = 0 行；**`asc` 侧 p1 ∩ p2 = 1 行**（200 行里 1 行）。
那一行是同源重复行还是边界抖动**未取证** —— 不要把"方向内完全稳定"当成
`asc` 侧也已证的事实。

**给智能体的硬结论**：

- **默认 `order="asc"` 的生产路径不受影响**（null 块在末尾，首页就是有值段）。
- **不要在 `uss_dr1` 上显式请求 `order="desc"`** —— 会拿到一整页没有 u 波段坐标的
  行，而坐标规范化取的正是 `ra_u`/`dec_u`，于是 `models` 层拿到整页空坐标（或被
  `malformed_coordinate_reason` 判成半行跳过，`src/client_paging.py`）。
- 登记的 `uss_dr1_ra_u` 在回包表头里**没有同名列**（回包是裸名 `ra_u`），
  定位靠剥前缀。这是**排序列问题**（`src/protocol.py` 的 `PAGINATION_SORT_COLUMNS`）
  与**回包表头问题**（`protocol_catalog_tables.py`）两套命名，不要混谈。

### 11.3 哨兵登记：`-32768` 是**第四种**编码，且已在阈值口径内被覆盖

`uss_dr1` 的 **12 个 `*_flag` 列**（`u_flag`/`j0378_flag`/…/`z_flag`）用
**`-32768`** 作"未测"填充值：1000 行里 **9046 个**单元格，**值域是"点"不是"带"**
（每列去重后只有这 1 个取值，写死相等即可判；`-32768` 恰是 int16 下界）。
仓内原有的三种是 `-1004.07`（**带**，ps1）、`-999.0`（点，`*_err` 列）、`nan`（token）。

**但这不是新增一条判定规则，而是一条新增"实测形态"登记** ——
`[已净化]_data/null_sentinel.yaml` 的判定约定明写是 **`value <= threshold`（不是
`==` 某一个具体值）**，`threshold: -999.0`。`-32768 < -999`，
所以**现有阈值已经覆盖它**，`BestSource.from_row` 端到端实测
（1000 行真实回包喂进行模型）**泄漏 0 个** `-32768` 值。
本节的改动是把 `-32768` 补进 `per_catalog` 的**已知实例**清单，
让"哪些星表有哪些形态"有据可查 —— **判定逻辑一行未改**。

⚠ **`nan` 的规模逐表差异极大，且与"空串"是两回事**：K1 在 J3 原始回包上逐格复算
（`temp/j3/raw/*_p1.csv`，1000 行样本）——`uss_dr1` 96,000 个单元格
里 **37,077 个是 `nan`（38.6%）**；`xpsp` 291,000 个（1000 行 × 291 列）里 8,162 个
（2.8%，其中 **8000 个集中在 8 个 `des_*` 测光列、整列全 `nan`**）；`smss_dr4` 848 个里 **338 个**（分布在 6 个 `*psf` 列，
`upsf` 94 / `vpsf` 77 / `gpsf` 51 / `zpsf` 54 / `rpsf` 36 / `ipsf` 26）；`scr_lamost` 18,769 个里 10 个；
而 `gaia_dr3_18` 的 155,000 个星表格子里 **50,555 个是空串、一个 `nan` 都没有**。
→ **"无值"编码逐表不同，判空必须逐表核对取值分布，
不能跨表套用**（`nan` 是字符串不是浮点 NaN，`float()` 能转成功，后续 `==`/`<` 恒假）。

> ⚠ **本行两处数字是 K1 复算订正的，别再照抄旧值**（2026-10-05，同一份原始回包
> `temp/j3/raw/smss_dr4_r300as_p1.csv` / `gaia_dr3_18_r300as_p1.csv` 上逐格重数）：
> 旧稿的 `smss_dr4 848 个里 171 个` 与 `gaia_dr3_18 的 49,420 个空单元格` **复算不出来**
> （正确值是 **338** 与 **50,555**）。**结论方向不变**（`nan` 与空串是两回事、逐表不同），
> 错的只是这两个绝对数。`uss_dr1` 37,077、`xpsp` 8,162、`-32768` 9,046 三处**复算一致**。

### 11.4 `inputobjs_*` **不是 proximity 专属**：锥搜回包同样带

`src/protocol.py::PROXIMITY_META_COLUMNS` 的注释原文把这 4 列
（`inputobjs_dist_arcsec` / `input_line` / `input_ra` / `input_dec`）写成
"proximity 响应"独有的形态。**实测不是**：`pos.type=cone` 的锥搜回包
**同样带这 4 列**，且固定排在**表头最前面**。K3 逐表核对 17 份 J3 原始回包
（`temp/j3/*_p1.csv`）里 **16 份带**，唯一例外是 **`uss_dr1`（0 个）** —— 该表
回包列名是裸名形态，站点没给它挂这组元数据列。
**入库快照口径重数（2026-10-05，31 份 `rows_full.csv`）：30 份带 4 列、1 份带
0 个，例外仍是 `uss_dr1`**（分布实测 `{4: 30, 0: 1}`）——**结论随样本规模不变**。

两个后果：

1. **列数对账会每表假报 +4**：拿回包表头宽度与 `CATALOG_COLUMNS` 长度比对时，
   必须先摘掉这 4 列（`width − registered` 的取值集合实测就是 `{0, 4}`，0 是 `uss_dr1`）。
2. **连"这 4 列总在"都不能当不变量** —— `uss_dr1` 反例在册。判列数要按
   "回包表头里有没有"来判，不能按"星表是谁"来判。
   （本仓的判空/导出逻辑按**列名前缀**剔这 4 列，形态无关，现状正确；
   受影响的只是**新增的按星表硬编码的判断**。）

> **但"每表多 4 列"不是登记缺口 —— 补登记才是错的**（代码级核查结论）：这 4 列描述的是
> **这次查询**（输入了哪一行坐标、角距多少），**不是源行的数据**，本就不该进数据投影。
> 仓内三处都刻意处理了它们：导出层**跳过**（`src/downloader.py:433`，理由是导出它会让每个
> CSV 多 4 列重复数据，而 `raw_data` 里已含）、行模型**跳过**（`src/models/__init__.py:292`，
> 理由更硬：`inputobjs_*` 以波段字母 `i` 开头，旧的首字母匹配会把**角距/行号吞成 i 波段星等**）、
> `src/crossmatch.py:383` **主动消费**它们做行归属。→ **「141 vs 137」这类数量差异，第一反应
> 不该是"补登记让数量对上"，而该是"问清那多出来的是什么"**。本仓在这件事上已经吃过两次亏：
> `ps1_source_id` 被当"整列为空"要换掉（实为位置相关，§11.6）、`grater` 被当"站点方言"保留
> （实为不存在，§6bis）。

### 11.5 回包表头 vs `CATALOG_COLUMNS`：数量全对（显式投影快照除外），三处形态差异

逐表核对 K3 那 17 份 J3 原始回包：**星表列数量全部与登记一致（无缺列无多列）**，
但有三处形态差异，任何按列名/列序比对表头的逻辑都要显式处理：

> **按入库快照重数（2026-10-05，31 份 `rows_full.csv`）的补充口径**：摘掉
> `inputobjs_*` 后 `wire − registered` 实测 **30 份为 0**，唯一非 0 的是
> `live_ps1_proximity_n3_5d2580ec` = **−26**（回包只给 4 个 ps1 列、登记 30 列）——
> 那是**显式 `showcol` 投影**所致，不是列漂移。故"数量全对"要带这条例外，
> 别把它当无例外定理。

1. **`uss_dr1` 用裸列名**（回包 `ra_u`/`dec_u`/`u_pstotal`，登记 `uss_dr1_ra_u` 等）。
   已在 `src/protocol_catalog_tables.py:313-318` 登记，不算新发现；此处只钉一条后果：
   **按列名比对表头会 96 列全部"不匹配"**（实测 `order_mismatch=96`），
   且排序列在回包里没有同名列。
2. **`dr3xpcorr` 的 17 列集合完全相同但顺序不同**（实测 `order_mismatch=6`，
   错位在 idx `[6,7,8,9,12,13]`，idx 10/11 恰好对上）。→ **列序在回包与登记之间
   不保证一致，解析必须按列名**（`CATALOG_COLUMNS` 名字映射）；
   **按列序（`zip` 位置 / `iloc` / `[i]`）解析的代码
   在这张表上会静默错列**。`protocol.parse_csv_rows` 走的是
   按列名成 dict，**不受影响**；E5 消融 / 导出层 / 任何自己读 `rows_full.csv`
   的脚本都值得核一遍。
3. **`inputobjs_*` 四列排在表头最前**（见 §11.4）。

### 11.6 `ps1` 本表的双记录类型（**已证**，入库快照级）＋ 别的表上「未取得」

#### 11.6.1 `ps1` 混排：判型、分段、以及**两种记录型的缺测编码不同**

`ps1` 的回包**不是同一种记录的集合**，而是两类结构不同的行。判型判据唯一且充分：
**`ps1_source_id` 是否非空**（非空 ⇔ 对象记录 A 组；空串 ⇔ 点源记录 B 组）。

**证据等级【入库快照】**（K1 在 `live_ps1_ra359.5_dec0.0_r1800.0as`（1000 行）
上逐行复算，2026-10-05）：

| 判据 | A 组（对象记录） | B 组（点源记录） |
|---|---|---|
| 行数 / 索引位置 | **431 行，占索引 0–430（前段连续）** | **569 行，占 431–999（后段连续）** |
| `ps1_source_id` | 431/431 非空（**去重 430 —— 组内有一个 id 重复**） | 0/569（全空串） |
| `ps1_class_star` / `ps1_ruwe` / `ps1_parallax` / `ps1_sigma` / `ps1_dust` / `ps1_ebv` | **431/431 非空** | **0/569**（整列空串） |
| `ps1_gpsf`/`ipsf`/`rpsf`/`ypsf`/`zpsf` | 有真值时是真值（如 `gpsf` 13.81–21.14），缺测写 **`nan`**（每列 1–5 格） | 有值即真值，缺测落在**哨兵带**内（`gpsf` 387/569、`ipsf` 420、`rpsf` 456、`ypsf` 504、`zpsf` 523） |
| **哨兵带格数** | **0 格** | **2290 格**（上列五个 psf 列合计） |
| `ps1_yflags` / `ps1_ypsf_err` | **整列空串 431/431**（y 波段在对象记录里完全没有） | 有值 |

三条可直接用的结论：

1. **对象级列与点源级列在这份样本里严格互斥、零例外**（431/431 vs 0/569）——
   "有 `class_star` 就必然没有点源测光"在这份样本上成立。
2. **哨兵带只在 B 组出现**（A 组 0 格）→ **看到 `-1004.*` 带的值即等价于"这行是点源记录"**，
   反之 A 组的缺测是 `nan`/`空串`。**两型不能用同一套判空写法**（这正是"按哨兵判空会漏判 A 组"的根因）。
3. **两型是"首尾相接"而不是"交错"**：A 组占前段连续 431 行。但**"永远前段连续"未取证** ——
   排序列 `ps1_source_id` 在 B 组整列为空，注入排序是空操作（§11.1），所以**行序由未声明的
   服务端行为决定**；上面那份 300″ 快照（A 组 0 行）与这份 1800″ 快照（A 组 431 行）之间
   已证明天区会换掉整个构成。**要判型就先判型，别假设块的顺序或位置。**

> ⚠ **覆盖是位置相关的，不是全局属性** —— 同半径换天区就换构成：
> `live-2026-10-04/` 下带 `ps1_source_id` 列的 **13 份** ps1 快照逐份复算，
> 其中 **11 份非空 0/行**（覆盖 (180,30)/(0,90)/(10,−45)/(29.97,0.02)，纯 B 组）、
> 1 份是上面那份 **431 + 569**、剩 1 份（`..._r300.0as_max4000`）的"3 个非空"
> 是**伪数据表头**（§6bis「每页重复表头」行）—— 即**该天区实际对象记录 0 行**。
> `(286.1, 15.7)` 的 128 + 172 比例是【临时实跑】，方向与上面一致但那个数不能用入库素材复算
> （§6bis 该行有完整说明）。

#### 11.6.2 「ps1 式混排在别的表上」：未取得 ——**不是「已否证」**

判据（严于探针一版）：两列的"有真值"掩码**互补**（不相交且并集 = 全部行）且
**两翼各 ≥5% 行**；`nan`/空串/哨兵带均算无真值。K3 用同一判据在 J3 的 11 份
有数据 CSV 上独立复算：

| 星表 | 数据行 | 真分层对数 |
|---|---|---|
| `ps1` @(180, 30) 300″ | 1000 | **0**（该天区是纯点源段，`source_id` 1000/1000 全空） |
| `gaia_dr3_18` / `xpsp` / `uss_dr1` | 1000 | 0 |
| `splus_dr4` / `scr_lamost` / `smss_dr4` / `dr3xpcorr` | 206 / 137 / 106 / 120 | 0 |
| `stripe82` / `scr_galah` | 27 / 1 | 0 |
| `landolt` / `jplus_dr3` | 0 | **未取证** |

> ⚠ **分寸必须原样保留**：这只等于**在各自代表天区、本轮样本量下没检出**，
> **不等于"别的表没有分层"** —— 天区相关性已被 `ps1` 实证过（(359.5, 0.0) 是混排段、
> (180.0, 30.0) 是纯点源段 —— 入库 11 份快照逐份复算为 0），所以"别的表在别的天区没有分层"是
> **未取证**，**不得当结论用**。

> **另记一个已踩的坑**（假阳性，判据要照抄别照改）：探针第一版曾在
> `gaia_dr3_18` 上报"404 对不相交列对"—— 那是把"某列 991 行有值 / 另一列 1 行
> 有值"也算成不相交，且把 19 位 `source_id` 当成了 `>=9999` 的极端哨兵。
> 要求互补 + 两翼 ≥5% + 排除 ID 列后归零。

### 11.7 ⚠ P0（2026-10-07 实跑坐实）：`uss_dr1` **静默丢弃锥形约束**

本节是 §11 各表登记的**订正面**，取代此前"uss_dr1 (120.3, −20.4) 300″ → 真实
1039801"的说法 —— 那个数是**全表行数**，不是锥内数。

**证据等级【临时实跑】**（`temp/` 下的观测，换机拿不到、不能复算；但结论由四条
互相独立的判据共同支撑，且其中两条是算术与结构层面的，不依赖那批字节）。

同坐标 (120.3, −20.4) 查两次，半径差 60 倍（串行、间隔 1.5s、单次 POST 不重试）：

| 请求半径 | `total` | 回包 1000 行落在请求锥内 | 角距中位数 | 角距范围 |
|---|---|---|---|---|
| 5″ | 1039801 | **0 / 1000**（11 波段逐段核） | 420708″ ≈ **116.9°** | 416401″–424957″ |
| 300″ | 1039801 | **0 / 1000** | 420708″ ≈ **116.9°** | 416401″–424957″ |

四条独立判据：

1. **`total` 与半径无关** —— 5″ 与 300″ 一个字没变。锥搜计数必须随半径变，
   不变即锥形约束没参与。
2. **算术上不可能** —— 300″ 锥面积 0.0218 deg²；若真装 1039801 行，全天需约
   **20 亿颗源**。
3. **两次回包逐行角距完全相同** —— 半径参数对该表**零影响**（不是"锥太窄"
   导致命中少，是同一个结果集被原样返回）。
4. **回包缺锥心元数据列** —— 其余 11 张表的锥搜回包都带 `inputobjs_input_ra/dec`，
   `uss_dr1` 的 96 列里一列都没有 ⇒ 站点侧也没把它当锥搜处理。

**并发行的登记订正**：§11.1 提到的 `uss_dr1_ra_u` 在 96 列回包里**不存在同名列**
（回包是裸名 `ra_u`）。本轮实跑再次确认表头只有 `ra_u`/`ra_g`/… 共 11 组波段坐标，
无带前缀写法。排序列按**裸名** `ra_u` 填（`src/protocol.py` 已如此登记）。

**给智能体的硬结论**：

- 要按位置取 `uss_dr1` 的行，**不要信锥搜结果**；回包后必须自己按 `ra_<band>` /
  `dec_<band>` 复核角距再入库。
- **这与 §11.2 的 `order="desc"` 陷阱是两回事**：那条讲排序方向让空坐标块顶到
  首页；这条讲位置约束整个没生效。不要合并叙述。
- 报告异常时报障请写"锥形约束未生效 + `total` 为全表行数"，而不是"数据不对"——
  站方要的是前者才能定位。

### 11.8 本节的复现命令

```powershell
# 离线复算 (不发请求): 逐表重读 J3 的原始回包
python temp/FIX-K3-recompute.py

# 原始实跑 (J3, 联网, 串行 + 强制间隔 1.5s, POST 不重试)
python temp/VERIFY-J3-probe.py
```
