# 可用工具面（7 个原子工具）

> 本件是**工具导航表**：只讲“有哪些工具、各要什么参数”。
> 完整定义（含返回信封、错误码、量纲说明）在 `skill/references/tools.schema.json`。
> **哪句话该用哪个工具、传什么值 —— 本件不提示，那是本次要评的东西。**

> 生成依据：`references/tools.schema.json` @ `20cb4e4cf61ea2be`

## 一览

| 工具 | 一句话职责 |
|------|-----------|
| `resolve_name` | 天体名解算 |
| `list_catalogs` | 列出可查询星表 |
| `describe_catalog` | 星表列元数据 |
| `cone_search` | 天区锥形检索 |
| `crossmatch_batch` | 批量坐标交叉匹配 |
| `count` | 查询命中总数 |
| `fetch_page` | 分页续取 |

### `resolve_name`

- 说明：把天体名（M31、NGC 532…）解析为 ICRS 坐标。后端代理 CDS Sesame。失败时站点返回哨兵 ra=-1000, dec=-1000（HTTP 200），此时本工具返回 E_NAME_UNRESOLVED 而不是静默给错坐标。这是智能体「按名字查星」的唯一入口，无需本地装 Sesame。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `name` | string | 是 | 天体名，如 M31 / NGC 532 / Betelgeuse |

### `list_catalogs`

- 说明：列出 12 张可查询星表 id 与显示名。注意 std / calib / other 是导航组不是表，直接查询会得到软错误（组名自身返回 Internal Server Error，带组前缀的路径返回 Not Found）；std 展开为 scr_galah / scr_lamost / xpsp 三张成员表。

无参数。

### `describe_catalog`

- 说明：返回某星表的列清单、量纲与波段映射。智能体在构造约束前应先调此工具，不要猜列名（列名带表前缀，如 ps1_ra / gaia_dr3_18_phot_g_mean_mag）。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `catalog` | string | 是 | — |

### `cone_search`

- 说明：以 RA/Dec 为中心、给定半径（角秒）检索 BEST 星表。走服务端原生 pos.type=cone，不是客户端 box-between 近似。返回统一信封，含 getcount 真实总数与 truncated 标记。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `ra` | number | 是 | RA，度（ICRS） |
| `dec` | number | 是 | Dec，度（ICRS） |
| `radius_arcsec` | number | 否 | 搜索半径，**单位是角秒**（传度会得到 0 行或 360 倍半径；上限 18000 角秒=5 度，BestClient 入口强制执行 validate_search_radius） |
| `catalog` | string | 否 | 缺省 `ps1` |
| `columns` | array | 否 | 列投影（showcol）。留空=全列，大星表建议裁剪以省带宽 |
| `sort` | string | 否 | 服务端排序列，如 ps1.rpsf 或裸名 rpsf |
| `order` | string | 否 | 缺省 `asc` |
| `nearest_only` | boolean | 否 | cone_nearestonly：每个锥心只保留最近邻；缺省 `False` |
| `max_rows` | integer | 否 | 上限。超出时 truncated=true，用 fetch_page 续取；缺省 `1000` |

### `crossmatch_batch`

- 说明：把一批坐标一次性提交给服务端做交叉匹配。走 pos.type=proximity（pos.radecTextarea），服务端直接算角距，响应自带 inputobjs_dist_arcsec / input_line / input_ra / input_dec 列。等价于过去 N 次独立锥形检索——1000 个坐标从约 2000 次 HTTP 降为 1 次 POST + 分页 GET。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `coords` | array | 是 | 待匹配坐标列表 |
| `catalog` | string | 否 | 缺省 `ps1` |
| `radius_arcsec` | number | 否 | 匹配半径（角秒）, 即 pos.defaultRadius；缺省 `3.0` |
| `nearest_only` | boolean | 否 | proximity_nearestonly：每个输入只返回最近邻；缺省 `True` |
| `columns` | array | 否 | 列投影（showcol） |
| `max_rows` | integer | 否 | 缺省 `50000` |

### `count`

- 说明：返回某查询会话的真实命中总数（服务端 getcount）。用于判断结果是否被截断、以及预算拉取成本。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `sqlid` | string | 是 | 服务端会话 id，如 s3898 或 3898 |

### `fetch_page`

- 说明：按页继续取回某会话的结果。当 cone_search / crossmatch_batch 返回 truncated=true 时使用。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `sqlid` | string | 是 | — |
| `page` | integer | 否 | 页码 (1 起); 工具边界校验 page>=1, 越界 E_INVALID_INPUT；缺省 `1` |
| `page_size` | integer | 否 | rows 参数; 工具边界校验 1<=page_size<=10000 (MAX_FETCH_PAGE_SIZE), 越界 E_INVALID_INPUT；缺省 `1000` |
| `catalog` | string | 否 | 用于列名前缀映射（响应列名带星表前缀） |
| `max_rows` | integer | 否 | 本工具调用的行数上限，默认=page_size; 上限与 page_size 的 MAX_FETCH_PAGE_SIZE (=10000) 对齐, 越界 E_INVALID_INPUT (YZ-03/YZ-04) |

> 参数以外的 schema 细节（返回信封、错误码、量纲）见 `skill/references/tools.schema.json`。
