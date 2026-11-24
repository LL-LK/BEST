# astro-best Client API Reference

> **用途**: `BestClient` / `BestQuery` / `BestMultiBandPhotometry` / `BestDownloader` /
> `BestCrossMatch` 五个公开入口的签名、参数单位与方法清单 (外加构造 `BestClient` 所需的
> `BestAuth`, 见 §BestAuth —— 它的 `timeout` 与客户端的是两个独立旋钮)。写调用代码前
> 先查本文; 单位陷阱 (deg vs arcsec) 集中在 §量纲与 `BestQuery.cone` 两处, 是最高频的出错点。
>
> **P1 合并注记 (2026-09-28)**: pybest 单类门面 (`Best`) 双副本已删除 — 唯一生产
> 客户端是 `BestClient`; 原 `Best.query` 的脚本式裸行消费由 `BestClient.query`
> (裸投影) 承接, `Best.download_file` 由 `BestClient.download_file` (薄壳委托
> `best_export.download_file`) 承接。上游 pylamost 快照与 `~/pybest.ini`
> 自动鉴权兼容层随门面一并退场。

## 白盒要素 (G7)

- **端点**: 全部调用经两阶段协议 — Phase 1 `POST https://nadc.china-vo.org/data/best/{catalog}/q`
  (表单取 `sqlid`); Phase 2 `GET /sqlid/{sqlid}?output.fmt=csv&rows=N&page=P` 分页。
  BEST 无 TAP/ADQL 端点 (`validate_adql_query` 仅语法校验)。
- **量纲**: `ra`/`dec` 单位 deg (ICRS); `radius_arcsec` 单位 arcsec; `radius_deg`
  为兼容口径 (两者勿混); `rate_limit` 单位 s/request; `timeout` 单位 s;
  `max_retries` 单位 count; 星等单位 mag (各波段)。
- **公式**: 交叉匹配分离角用 haversine 大圆距离 (精确球面公式, 不做平面天球近似),
  见 `src/crossmatch._angular_separation_arcsec`。
- **复现**: 全部示例离线可复现 — `python -m pytest test/ -q`;
  端到端样例见 `examples/example_quickstart_client.py`。
- **权威协议层**: 表单键集/表头判定/计数解析以 `src/protocol.py` 为唯一出处。

## 核心类

### BestAuth

`BestClient(auth=...)` 吃的就是这个对象 —— Django session + CSRF 双重校验。定义在
`src/auth/session.py`，`src.client` 再导出一次以保住 `from src.client import
BestAuth` 这条旧导入路径（实测 `src.client.BestAuth is src.auth.session.BestAuth`
为 `True`）。**匿名查询不需要它**：不传 `auth` 即走匿名路径。

```python
BestAuth(
    timeout: int = 120,      # REQUEST_TIMEOUT, 登录两个请求点的单次请求超时 (s; 实为 int, 非 float)
)
```

| 成员 | 说明 |
|------|------|
| `login(username, password)` | Django session 登录（GET 登录页取 CSRF → POST 凭据）；**成功与失败都只返回布尔、不抛异常**，且站点拒登必留 ERROR 日志（静默 `False` 与"从未尝试登录"同形，会导致无声降级） |
| `authenticated` | 当前 session 是否已登录（property） |
| `request_timeout` | 本认证器**实际生效**的单请求超时（property）：登录两个出网请求点的唯一取值口，与 `BestClient.request_timeout` 同名同形（刻意） |
| `export_session()` | 交给 `BestClient` 的会话材料四键：`authenticated` / `cookies` / `csrf_token` / `headers`；后两者是**活引用**，调用方只读，透过去改会污染认证会话 |
| `close()` / `__enter__` / `__exit__` | 释放自持 `requests.Session` 的连接池（幂等；长生命进程反复构造认证对象时防 socket 泄漏） |

⚠ **`timeout` 与 `BestClient(timeout=...)` 是两个独立旋钮**：缺省都取协议层
`REQUEST_TIMEOUT`，所以没有显式配置的调用方（含全部评测回放）两侧行为逐字节一致；
一旦显式收窄，**只**影响登录路径（登录页 GET + 登录 POST 这两个请求点），
不会波及查询侧。**构造顺序不可逆**是根因 —— `BestClient.__init__` 拿到的是
**已登录**的 `BestAuth`（只经 `export_session()` 收 cookie + CSRF 头），
客户端无从回写认证侧的超时。所以要调快认证只能**从构造点各给各的**：

```python
auth = BestAuth(timeout=7)          # 认证侧: 登录页 GET + 登录 POST
auth.login(user, password)          # 认证判定只看最终 URL 是否仍停在 login 页
client = BestClient(auth=auth, timeout=7)   # 查询侧: 阶段 1 POST / 分页 GET / getcount / 名称解算
```

实测签名：`inspect.signature(BestAuth.__init__)` → `(self, timeout: int = 120)`；
`REQUEST_TIMEOUT` 实为 `int` 120（不是 float）。

### BestClient

```python
BestClient(
    base_url: str = "https://nadc.china-vo.org/data/best",
    auth: Optional[BestAuth] = None,
    rate_limit: float = 2.0,
    max_retries: int = 3,
    timeout: int = 120,      # REQUEST_TIMEOUT, 单次请求超时 (s; 实为 int, 非 float)
)
```

**方法**:

| 方法 | 说明 |
|------|------|
| `cone_search(ra, dec, radius_arcsec=180.0, catalog="ps1", band=None, max_records=1000, page_size=1000, columns=None, sort=None, order="asc", nearest_only=False)` | Cone 搜索（半径单位**角秒**；`catalog="std"` 展开三成员合并） |
| `query(catalog="ps1", constraints=None, ra=None, dec=None, radius_arcsec=None, max_rows=50000, columns=None, sort=None, order="asc", nearest_only=False)` | 通用列约束查询 → **裸行投影**（P1 合并入口, TAP 后端消费; constraints 为 `{name, op, value/min/max}` dict 列表） |
| `query_standard_stars(constraints, output_format, max_rows, table)` | 标准星；`table` 取 `scr_galah`/`scr_lamost`/`xpsp`（默认 `scr_lamost`） |
| `query_panstarrs(constraints, output_format, max_rows)` | 查询 Pan-STARRS |
| `query_calibrated(survey, constraints, output_format, max_rows)` | 查询精测星表（`survey` 接受任意可查 id，含旧名 `gaia_dr3`） |
| `crossmatch_batch(ra_list, dec_list, catalog="ps1", radius_arcsec=3.0, ...)` | 服务端 proximity 批量匹配（一次 POST 全部坐标） |
| `download_file(url, savedir, overwrite=True, filename=None, ...)` | 字节级流式下载（薄壳委托 `best_export.download_file`; HTTP Range 断点续传 + 取消） |
| `count(sqlid)` / `fetch_page(sqlid, page, page_size, ...)` | 服务端计数 / 单页取数（agent 工具面同款缝） |
| `check_connection()` | 检查连接状态（布尔, 不吞异常成信封）；**超时硬编码 30s，不跟随实例 `timeout`** —— 明文约定见下方 |
| `describe_columns(catalog)` | 列名内省（静态清单, 零请求） |

`catalog` 取值为线上 12 个可查 id：`ps1`、`stripe82`、`gaia_dr3_18`、`jplus_dr3`、
`smss_dr4`、`landolt`、`uss_dr1`、`splus_dr4`、`scr_galah`、`scr_lamost`、`xpsp`、
`dr3xpcorr`。`output_format` 仅 `csv`/`txt`/`json`/`votable` 为服务端支持格式。

> ⚠ **约定：`check_connection()` 的 30s 超时是一条独立的明文约定，不是"等对齐"的遗留值。**
>
> 值本身早已登记在 `references/ALGORITHM-SPEC.md` 超参表（`check_connection_timeout |
> 30 s | 仅连通性自检专用的硬编码超时`）；这里补的是**为什么**与**改它的代价**。
>
> - **现状（2026-10-05 核实）**：`src/client.py` 那一行是
>   `session.get(f"{base_url}/", timeout=30)` —— 字面量 `30`，**不读**
>   `self.request_timeout`，**没有**任何构造参数能改它。判据是「状态码 200 **且**
>   非软错误体」两件套（站点对失效路由回 200 + `{"error":"Not Found"}`）。
> - **为什么不跟随查询超时**：`120s` 是给大表查询的耐心值（阶段 1 POST、分页 GET、
>   `getcount`、名称解算共用它）。而连通性探测只 GET **站点根路径**这一个静态资源，
>   全部产出就是**一个布尔值**。把它也按 120s 等，等于让「站点不可达」这条诊断结论
>   在断网 / 链路劣化时**晚 4 倍时间**才出得来 —— 而受这条口径直接约束的正是
>   `python -m src doctor` 与 `python -m src info`（两者各探测一次、探测一次即复用，
>   同一诊断里不发第二次相同请求）。**诊断命令的可用性就是它出结论的速度。**
>   ⚠ 别认错门：`python ops/astro_best_cli.py doctor` 是**纯离线**的组件自检
>   （导入真包 + 组件在位），**不走** `check_connection`、不受本约定约束。
> - **为什么不取更小的值**：收得太紧会把"慢但活着"的站点误报成不可达，把一个真结论
>   换成假结论。30 是「比查询耐心小一个量级、但仍远宽于一次正常往返」的分界值。
>   仓内 `30` 秒的出网超时只有两处（`check_connection` /
>   `src/auth/nadc_oauth.py` 的令牌交换），**全是短交互面**，彼此一致；唯一另一处 `src/tap/jobs.py` 的 `timeout=30` 是 sqlite3
>   锁等待，与网络无关。
> - **改动代价（重要）**：仓里**没有任何可执行断言**钉这个 `30`。
>   `test/unit/client/test_client_transport_discipline.py` 的 docstring 提到了
>   「`check_connection` 用 30s 而不是跟随实例超时」这条口径，但该测试只断言
>   `BestClient` 侧缺省未变（`client.request_timeout == REQUEST_TIMEOUT`），
>   **没有**断言 `check_connection` 真的发了 30。**即改它不会让任何门禁变红** ——
>   所以要改就得**显式推翻本段约定**并给出替代口径（附带断网/劣化下
>   `doctor` 的实测耗时），而**不能**当作"顺手与 `REQUEST_TIMEOUT` 对齐"。

### BestQuery

```python
BestQuery()
    .catalog(name)           # 设置目标星表
    .cone(ra, dec, radius_deg)   # Cone 搜索空间约束; 半径单位是"度", 内部 ×3600 转角秒
    .box(ra_min, ra_max, dec_min, dec_max)  # 矩形区域
    .mag_range(mag_min, mag_max, band)     # 星等范围
    .mag_brighter_than(mag_limit, band)    # 亮于限制
    .min_snr(value)          # 最小 SNR
    .max_fwhm(value)         # 最大 FWHM
    .class_star_min(value)   # 最小 class_star
    .where(column, constraint, min, max, value)  # 自定义约束
    .limit(n)                # 限制返回数
    .output_format(fmt)      # 设置格式
    .build()                 # 构建参数字典
```

### BestMultiBandPhotometry

```python
BestMultiBandPhotometry(source_id, points=None, band=None)
BestMultiBandPhotometry.from_position(client, ra, dec, band=None, radius_arcsec=3.0, catalog="ps1")  # 按坐标检索
BestMultiBandPhotometry.from_client(client, source_id, band=None, catalog="ps1")  # 仅接受 POS_<ra>_<dec> 合成 ID
```

> `from_position` 的第 5 位是 **`radius_arcsec`**（默认 3.0，单位**角秒**），不是
> `catalog`。按缺参数的旧签名写 `from_position(client, ra, dec, band, "ps1")` 会把
> 字符串灌进半径，实测报 `TypeError: '<=' not supported between instances of 'str' and 'int'`。
> 实测签名: `inspect.signature(BestMultiBandPhotometry.from_position)`。

注意: BEST 是均一定标星表 (无时序), 本容器是**多波段静态测光**容器;
`n_points` 是 points (源) 个数, 不是观测历元数。需要时序请改用
ZTF/ATLAS/ASAS-SN 等测光巡天源。

**方法**:
| 方法 | 说明 |
|------|------|
| `to_csv(filepath)` | 导出 CSV |
| `to_json(filepath)` | 导出 JSON |
| `summary()` | 统计概要 |
| `n_points` / `magnitudes` / `bands` | 属性视图 |

> `from_client` 只支持 `POS_<ra>_<dec>` 合成 ID（解析出坐标后转 `from_position`）；
> 其他 ID 形态显式抛 `ValueError`（P2-12：BEST 没有按 ID 检索的公开端点，
> 不伪造数据）。`catalog` 参数默认 `ps1`。

### BestDownloader

```python
BestDownloader(client, output_dir)
```

**方法**:
| 方法 | 说明 |
|------|------|
| `download_region(ra_center, dec_center, radius_arcsec=600.0, catalog="ps1", bands=None, output_format="csv", max_rows=50000, page_size=1000, resumable=False, ...)` | 区域下载（半径单位**角秒**；`resumable=True` 时走断点续传） |
| `download_by_constraints(...)` | 约束下载（精准下载，in 约束） |
| `download_sqlid(sqlid, catalog, ...)` | 按已有 sqlid 分页下载 |
| `export_results(data, filename="best_results.json")` | 导出结果（CSV 或 JSON） |

### BestCrossMatch

```python
BestCrossMatch(client)
```

**方法**:
| 方法 | 说明 |
|------|------|
| `crossmatch_coords(ra_list, dec_list, catalog, radius_arcsec)` | 坐标匹配 |
| `crossmatch_source_list(sources, catalog, radius_arcsec)` | 源列表匹配 |
| `submit_upload_job(file_content, catalog, radius_arcsec)` | 本地批量匹配任务（落盘队列执行）。服务端侧另有条目：`pos.type=proximity` + `pos.radecTextarea`/`pos.posfile` 可在 BEST 站内批量匹配（响应含 `inputobjs_*`）；`/data/best/jobs` 自建星表区需 NADC 登录 |
