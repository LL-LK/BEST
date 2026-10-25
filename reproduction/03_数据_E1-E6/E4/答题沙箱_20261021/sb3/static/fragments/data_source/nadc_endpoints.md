# data_source/nadc_endpoints — NADC 端点与协议切片

基地址 `https://nadc.china-vo.org/data/best`（Django 表单应用，非 TAP/REST-JSON）。
逐路由实测；**未知路由返回 HTTP 200 + `{"error":"Not Found"}`**，
所以只看状态码会把死端点读成活的。
**端点/交互全图 (智能体使用向 SSOT): `references/site-endpoints-and-interactions.md`**
(实机浏览器深潜; 本节只留高频切片)。

- 查询：`POST /{catalog}/q` — `output.fmt=html` 才返回含 `sqlid` 的结果页；
  `csv/json/votable/txt` 会**内联返回数据**、不给 sqlid。
- 取数：`GET /sqlid/{sqlid}?output.fmt=…&rows=N&page=P[&sort=&order=]`。
  **不要反推 EasyUI `filterRules` 二次传一遍**：约束随 phase-1 表单进入 sqlid 会话，
  该参数已 live 证冗余（`src/client_paging.py` 明记，见 SSOT §7）。
- **分页是绝对偏移，页号与页大小绑成同一个量**：`page=N & rows=M` 表示跳过前
  `(N-1)*M` 行再取 M 行（2026-10-04 实测：`page=2&rows=100` 的 100 行与
  `page=1&rows=1000` 的 `[100:200]` 逐行完全相同）。**改了 `rows`，同一个 `page`
  就是另一个数据集**；断点续传必须把 `(sqlid, page, rows, sort, order)` 成对存取，
  漏存 `rows` 会静默丢行。
- **取页的 sqlid 要带 `s` 前缀，`getcount` 的要裸数字，写反都是 22 B 软 404**
  （2026-10-04 实测：同一 `s4958`，`/sqlid/s4958?…` → 24997 B 真实 CSV，
  `/sqlid/4958?…` → 22 B `{"error":"Not Found"}`；`/sqlid/4958/getcount` →
  15 B `{"total":5109}`，`/sqlid/s4958/getcount` → 22 B）。
- **探针陷阱：22 字节 `{"error":"Not Found"}` 先怀疑自己拼的 URL**，别急着报站点。
  手搓裸 `requests` 探针用 `re.search(r"sqlid/s?(\d+)", …)` 取号时 `s?` 落在捕获组
  **外**，拿到的裸数字拼出的取页 URL 一律 22 B —— 连 `total=215774` 的 ps1 也一样。
  一分钟判据：**同会话的 `getcount` 还通不通？通 → 会话是活的，问题在地址。**
  实测排除了 cookie / `X-CSRFToken` / `User-Agent` / `Accept` 四个候选（同一会话
  四种组合一律 22 B，`BestClient` 同条件立刻拿到 24997 B）。客户端免疫是因为
  `src.protocol.parse_sqlid` 保留前缀、只有 `count_sqlid` 才剥。
- 计数：`GET /sqlid/{numeric}/getcount` → `{"total": N}`（id 去掉 `s` 前缀，
  带 `s` 的是软 404）；无约束会话上该请求会超时。
- 名称解算：`GET /nss/solve?obj={name}` → `{ra,dec,obj,remark}`（CDS Sesame 代理；
  失败 `ra=dec=-1000`；GET only）。表单页 solve 按钮即此端点。
- 表单/元数据：`GET /{catalog}/f`（**裸 id 全组通用**）、`GET /t/{table_id}`。
  `calib/` 前缀**仅对 calib 组成员有效**（ps1/stripe82/gaia_dr3_18/jplus_dr3/
  smss_dr4/landolt/uss_dr1/splus_dr4）；std 组成员（scr_galah/scr_lamost/xpsp）与
  other 组成员（dr3xpcorr）带 `calib/` 前缀**均软 404**（2026-09-29 复测，
  旧记「两种前缀均接受」过宽）。
- 分组描述页：`GET /{group}/doc/{timestamp}`（一句话口径，时间戳 id）。
- 结果页网格数据口：`POST /sqlid/{sqlid}?output.fmt=dbgrid`（body
  `page&rows&sort&order`）——**2026-09-29 复测为 123ms 快速软错误**（旧记「匿名会话
  挂起」已改写，结论方向不变），取数走 GET 分页。
- 空间选择 `pos.type`：`none` / `cone`(racenter,deccenter,**radius 单位角秒** —
  表单页原文 `radius <input name="pos.radius"> arcsec`; 传度得 0 行) /
  `rect`(ramin,ramax,decmin,decmax, 单位度) / `proximity`(radecTextarea 或 posfile，
  格式 `ra,dec[,radius_in_arcsec]`, **服务端批量坐标匹配**，响应前置 `inputobjs_*` 列 ——
  但**那组列不是 proximity 独有**，锥搜回包同样带，见下节)。
- 列投影 `showcol={table}.{col}`，可重复；约束键 `{table}.{col}.operation` 与
  `.min/.max/.constraint/.textarea/.file`。**operation 只认这 8 个**：
  `equal/notequal/less/lessequal/greaterequal/between/contains/in`。
  **白名单外的值站点不报错也不忽略，而是收下后返回空表**（2026-10-05 实测：
  `grater` min15 与拼错的 `greatr` max16 在 ps1 300″ 锥里都 total=0，而同锥
  `greaterequal` min15 出 1559 行）—— 拼错的后果是"看起来天上没源"，不是
  "不过滤"。**旧版本文档说的「strict-greater 拼写是 `grater`」是错的**，
  勿照抄；站点的严格大于拼写尚未取证。
- 输出 MIME：csv=text/csv、votable=application/x-votable+xml、json=application/json；
  `fits` **不支持**（返回 HTML）。CSV 请求体带 UTF-8 BOM，须按 `utf-8-sig` 读。
- 登录：`GET /user/login?next=…` 的**页面内**再跳 `oauth.china-vo.org`（表单登录页
  是第一跳，见 `references/site-endpoints-and-interactions.md` §5）。**发起**路由是
  `GET /user/oauth2/login/nadc`（→302），**回调**路由是
  `/user/oauth2/callback/nadc` —— 两者不同，**早期文档曾混用**，写 redirect_uri
  必须用 callback 那条（否则登录直接失败）。`/data/best/jobs` 为自建星表区（需登录）。
  POST 查询仍需表单页内嵌的 `csrf_token`；站点 AJAX 惯例加 `X-CSRFToken` 头。
- `/jobs` (User-Defined Catalog, 需登录): 上传 FITS 响应曲线 (`wavelength` Å,
  3360–10200; `function` 归一化) + 系统/波段 → Run → Jobs 表; Phase pending
  >1min 应重传; 空闲服务器每波段数分钟可生成 2 亿+ 标准星 (官网 help 页口径)。
- 文档页三件: `/doc/system-en/{catalog,help,news}` — catalog 含 19 测光系统全表 +
  8 个 Well-Calibrated 表精度/规模; help 含官方引用与上传协议; news 仅有首发公告 (2025/05/20)。
  本地镜像: `references/photometric-systems.md` (采集);
  论文引文: `rag/knowledge/citations.yaml`。
- 凭据: 只读 env; 无 token 的云作业登记为离线 pending (绝不伪造 job_id)。

## 名称解算失败是失败信号，不是坐标：-1000 不得回灌查询

- `GET /nss/solve?obj={name}` 失败时回 **`ra=dec=-1000`**。这是**失败信号，不是
  坐标**：它表示"名称解析服务库里没有这个名字"，**不表示该天体不存在**。
- **处置**（三件都必须做）：① **显式报错**，不要把 -1000 当作成功结果返回；
  ② **绝不把 -1000 当坐标继续查询** —— 它会进锥搜算出一个看似合法却无意义的
  结果集（`-1000` 度不是有效天区坐标）；③ 提示改用**坐标**（RA/Dec）或其他标识
  （如 Gaia `source_id`）重试。
- 用户问"报 E_NAME_UNRESOLVED 是不是说明这个天体不存在"时，正确答法是区分
  **「解析失败」与「不存在」**，并给出换标识的可行路径。

## 回包表头不是星表列清单：多出的 4 列与列序

`CATALOG_COLUMNS` 登记的是**星表列**；回包表头里还挂着别的东西。**先摘再比**。

- **`inputobjs_*` 四列（`dist_arcsec`/`input_line`/`input_ra`/`input_dec`）描述的是
  这次查询，不是源** —— 回的是"你提交了什么坐标 / 命中输入第几行 / 角距多少"。
  **锥搜（`pos.type=cone`）同样带**，proximity 不是它的专利；带就固定排在表头最前。
  【临时实跑 + 入库快照】12 表逐表实跑与 31 份 `rows_full.csv` 重数一致
  （唯一例外 `uss_dr1` 回 0 个）。
  - **判列数必须先摘掉这 4 列再比**，否则每表假报 **+4** 漂移；
  - **连"这 4 列总在"都不能当不变量** —— 判"有没有"要按**回包表头里有没有**来判，
    不能按"哪张星表"来判；
  - **不许按"补登记进 `CATALOG_COLUMNS`"把这个差消掉**：那是把查询元数据当源数据，
    导出的每个 CSV 多 4 列重复值；且 `inputobjs_*` 以波段字母 `i` 开头，
    按波段首字母推断测光列的逻辑会把角距/行号**吞成 i 波段星等**。
- **列序在回包与登记之间不保证一致 → 一律按列名取值**：实测 `dr3xpcorr` 的 17 列
  **集合与登记完全相同、顺序不同**；`uss_dr1` 回包用**裸列名**（`ra_u` vs 登记
  `uss_dr1_ra_u`）。【临时实跑 + 入库快照】
  任何按位置取值（`zip` 下标 / `iloc` / `[i]`）的解析在这两张表上**静默错列** ——
  不报错，取到的是同一行**另一列**的值。仓内 `parse_csv_rows` 按列名成 dict，
  **不受影响**；要核的是**自己读 `rows_full.csv` 的脚本**（E5 消融、导出层、临时分析）。
  逐表差异与复算口径见 `references/site-endpoints-and-interactions.md` §11.4/§11.5。

## 「站点可达」怎么判：200 不算，根路径活不等于端点活

- **判据是两件套，不是一件事**：HTTP 200 **且** 响应体不是软错误体
  （`src/client.py::check_connection`）。站点对失效路由/失效会话一律回 200 +
  `{"error":"Not Found"}` —— 只看状态码会把**故障读成健康**。超时/连接错误一律返回
  `False` 且**不向外抛异常**（诊断命令要的是一个布尔值，不是一堆栈）。
- **它只 GET 站点根路径**：`connected=True` 只证明**根路径**活着，**不证明你要用的
  那个端点、那张星表路由活着**。判某个路由活不活，要看**它自己那个请求的回包**
  （22 B 判据见上）。反向才成立：根路径 `False` 才是"站点整体不可达"的结论。
- **别认错门**：`python -m src doctor` / `info` 各发一次真实探测（探测一次即复用）；
  而 `python ops/astro_best_cli.py doctor` 是**纯离线**的组件自检（导入真包 +
  组件在位），**不发网络请求** —— 它绿**不等于**站点可达，两者是不同的门。
  30s 独立超时的取舍与改它的代价见 `references/client-api-reference.md`。

