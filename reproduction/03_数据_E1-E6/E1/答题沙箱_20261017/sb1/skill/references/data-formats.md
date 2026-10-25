# data-formats.md — BEST 数据格式全景与解析能力边界

> **用途**: 回答"BEST 有哪些格式、我们能不能全解析、常见天文格式覆盖到哪"。
> 写取数/导出代码前先查本文; 换格式踩坑集中在 §2 的两阶段分岔与 §4 的单位陷阱。

## 1. 站点 `output.fmt` 全集与我们的处置

BEST 的 `output.fmt` 站点侧共接受 6 个取值（`html`/`csv`/`txt`/`json`/`votable`/
`dbgrid`），另有一个 **`fits` 站点并不支持**（请求它拿到的是结果页 HTML）。
**只有 `html` 与 `csv` 会出现在我们的网络请求里**，其余都是"站点支持但本 skill
不向站点请求"——数据恒以 CSV 取回，其余格式在本地转换。这样做的理由见 §3。

| `output.fmt` | 站点行为 | 本 skill 处置 | 解析/生成实现 |
|---|---|---|---|
| `html` | 阶段一唯一会交回 `sqlid` 的提交形态 | **必需**: 每次查询的阶段一都用它 | `protocol.parse_sqlid` (正则) |
| `csv` | 直接内联数据, 丢会话 | **唯一线上取数格式**: 阶段二分页固定 `output.fmt=csv` | `protocol.parse_csv_rows` |
| `txt` | 制表符分隔 (TSV) | 不向站点请求; 本地导出落 `.tsv` | `serialization.delimited_text(rows, "\t")` |
| `json` | 直接内联 JSON | 不向站点请求; 本地导出构造 JSON | `serialization.json_document` |
| `votable` | 直接内联 VOTable | 不向站点请求; 本地导出构造 VOTable | `serialization.votable_document` |
| `dbgrid` | 网格数据口 (EasyUI datagrid) | **刻意不用**: 匿名请求不可用 (2026-09-29 复测为 123ms 快速返回 `{"error":"Internal Server Error"}`; 旧快照记 ">75s 挂起", 站点行为已变而结论不变, 见 `site-endpoints-and-interactions.md` §6) | 无 |
| `fits` | **站点不支持** — 请求 fits 拿到的是结果页 HTML | 纯本地转换 | `serialization.write_fits` (astropy 可选) |

> 注意 `fits` 的特殊地位: 它**不在** `protocol.SUPPORTED_OUTPUT_FORMATS`
> (那是"线上能力"集合) 里, 而在 `serialization.LOCAL_EXPORT_FORMATS` 里。
> 两个集合分开声明, 免得有人以为能给服务端传 `output.fmt=fits`。

## 2. 两阶段协议与 `output.fmt` 的分岔 (最高频踩坑)

`POST /{catalog}/q` 的 `output.fmt` 决定响应形态, 这一点极易踩错:

| 提交的 `output.fmt` | `/q` 的响应 | 后果 |
|---|---|---|
| `html` | 含 `sqlid` 的 HTML 页面 | 正确: 拿到会话 id, 再去 `/sqlid/{id}` 分页取数 |
| `csv` / `txt` / `json` / `votable` | 直接内联数据 | **丢会话**: 没有 `sqlid`, 无法分页、无法 `getcount`、无法续传 |

因此本 skill 的阶段一**恒用 `html`** (`protocol.PHASE1_HANDOFF_FORMAT`),
数据面恒用 `csv`; 想要别的格式就在本地转。

## 3. 为什么"线上只取 CSV, 其余本地转"

1. **单一 wire 格式 = 单一解析路径**。四种格式各写一个线上解析器, 就要维护四套
   表头/编码/转义假设, 而站点对这四种的实现细节并未全部公开文档化。
2. **分页与续传只对 CSV 验证过**。`rows`/`page` 参数、`getcount` 计数、
   页级 checkpoint 都以 CSV 响应为基准做过 live 实证。
3. **本地转换可复现且可单测**。导出逻辑不依赖站点, 全部能用固定夹具覆盖。

代价: 本地转换多一次内存驻留 (行记录已在内存里)。对 `max_rows=50000` 的默认上限
可接受; 更大结果集应走 `DownloadManager` 的分页路径, 不要一次拉全表。

## 4. 单位陷阱 (deg vs arcsec, 本仓最高频错误)

| 位置 | 单位 | 说明 |
|---|---|---|
| `BestQuery.cone(ra, dec, radius_deg)` | ra/dec **度**, radius **度** | 内部 ×3600 填 `pos.radius` |
| `BestClient.cone_search(ra, dec, radius_arcsec, ...)` | ra/dec **度**, radius **角秒** | 直接进表单 |
| 表单 `pos.radius` | **角秒** | 站点契约; 传度会得 0 行或 360 倍半径 |
| VOTable `ra`/`dec` 列 | **度** (`unit="deg"`) | 由 `serialization` 自动补 |
| VOTable 星等列 | **星等** (`unit="mag"`) | 后缀集由 `CATALOG_MAG_COLUMNS` 推导 |

`BestQuery.cone` 的半径单位是**度**（内部 ×3600 填 `pos.radius`），
`BestClient.cone_search` 的半径单位是**角秒** ——
⚠ 早期版本在这里论证「`Best` 与 `BestClient` 的单位分歧」，那是**已不存在的对照**：
pybest 单类门面 `Best`（`src/pybest.py`）随 P1 双副本合并**已删除**，
`BestClient` 是唯一现役客户端，`from src import Best` 一律失效。
现存两处易混点：① `BestQuery.cone(radius_deg=度)` 与
`BestClient.cone_search(radius_arcsec=角秒)` 形参名不同、单位不同；
② `BestQuery.cone` 返回 `BestQueryResult`（不是 `list[dict]`，那是已删门面的旧返回形态）。
调用前务必看签名 (见 `client-api-reference.md`)。

## 5. 列类型推断规则 (VOTable / FITS 落盘)

按**实际取值**推断, 不按列名猜——实测列名带表前缀 (`ps1_ra` / `gaia_dr3_18_ra`),
名称规则覆盖率不了:

| 列类型 | 判定 | VOTable | FITS |
|---|---|---|---|
| 数值列 | 全部非空取值可解析为 float | `datatype="double"` | `format="D"` (float64) |
| 标识符列 | 列名以 `id`/`_id`/`_ids` 结尾 | `datatype="char"` + `arraysize="*"` | 定长字符串 |
| 字符列 | 其余 | `datatype="char"` + `arraysize="*"` | 定长字符串 (宽度取列内最长值) |
| 坐标列 | 列名是 `ra`/`dec` 或以 `_ra`/`_dec` 结尾 | 额外 `unit="deg"` | 无单位字段 (FITS 头可另加) |
| 星等列 | 列名后缀命中 `CATALOG_MAG_COLUMNS` 的任一键 | 额外 `unit="mag"` | 无单位字段 |

> **坐标列那条规则有个已知例外，别把它当完备判据**：12 张可查表里只有 9 张
> 符合"`_ra`/`_dec` 结尾"；`xpsp`/`dr3xpcorr` 的坐标落在共享位置表
> `gaiaxp_photinfo_replenish_ra/dec`（前缀是表单表名），`uss_dr1` 则**根本没有**
> 规范化坐标列（分波段 `ra_u` / `ra_j0378`）。按名推断坐标列的代码在这些表上会
> 静默漏判 —— 逐表实测形态见
> [`site-endpoints-and-interactions.md`](site-endpoints-and-interactions.md) §10.1。
> 另外 12 张表都带 `inputobjs_input_ra/dec`，那是**查询输入坐标**，
> 不该给源行补 `unit="deg"`。

**标识符列必须保持字符串**, 即使每个取值都像数字。**真例子取 `ps1_source_id`
的对象记录子集**（2026-10-05 实测值如 `4512916854546732416`，恒 **19 位**，
去重后无重复）: 写成 `double` 后会 ① 丢前导零 (`"007"` → `7`); ② 超过 2^53 的
id 丢精度（19 位整数全部越界）; ③ 下游按 ID 做相等比较时 `"123"` 与 `123.0`
不再相等。这条是复测发现的真 bug, 回归钉在
`test/unit/serialization/test_output_formats.py::TestColumnTypeInference`。

> ⚠ **`ps1_source_id` 是有条件的好例子**：它只在**对象记录**子集里有值，
> **点源记录子集整列为空串**。拿它当范例前**必须先判记录类型**（判据见 §5c）——
> 写 `double` 的害处是真的，但"这一列全程有值"是假的。
> 想要一个无条件成立的正例可用 `gaia_dr3_18_source_id`（19 位整数，实测 1000 行
> 全非空且无重复）。**判据是"这一列在你要处理的那部分数据里真有值"，
> 不是"这一列叫 id"。**

## 6. 分隔符判别 (CSV / TSV)

`protocol.parse_csv_rows` 的分隔符判别**只看表头行**:

- 表头只含制表符 → 按 TSV 读; 否则按逗号读。
- **绝不能据数据行判别**: 数据值里的逗号 (如 `obj_name` = `"M31, NGC 532"`) 会让
  逗号判据选中逗号, 把 TSV 的一列错拆成三列, 整表列序静默偏移且不抛异常。
- 表头行是列名, 不会含分隔符本身, 是唯一安全的判别位置。

## 7. 常见天文格式支持面

| 格式 | 支持 | 实现 / 说明 |
|---|---|---|
| CSV | ✅ 全链路 | 线上取数 + 本地导出 + 回读 |
| TSV (ASCII tab) | ✅ | 本地导出; 解析侧靠 §6 的表头判别 |
| JSON | ✅ | 本地导出 (`sources` + 可选 `total`) |
| VOTable | ✅ | 本地导出 (TABLEDATA 形态); astropy 可读回 |
| FITS (binary table) | ✅ | 本地转换, astropy 可选; 缺失时抛带安装提示的 `RuntimeError` |
| IPAC / CDS table | ❌ | 未实现; 天文学界交换格式, 如需请提需求 |
| HDF5 | ❌ | 未实现 |
| Parquet | ❌ | 未实现 |
| DS9 regions | ❌ | 未实现 (本 skill 不出图像) |
| ASCII 定宽 (mag 分隔) | ❌ | 未实现 |

**已知不支持项一律显式报错**: `serialization.normalize_output_format` 对白名单外的
格式抛 `ValueError` 并列出可选值。旧实现在 `else` 分支把未知格式静默写成 JSON 并把
扩展名改成 `.json`——调用方请求 FITS 拿到一个 JSON 文件且无任何提示, 下游按 FITS
解析以难懂的格式错误失败, 而按扩展名判断的调用方以为拿到的是 JSON。

## 5b. 合成夹具里的幽灵列 `ps1_snr`（别照着它写代码）

仓内几份**曾经**是**合成**夹具的素材（E2 的 `syn_missing`、E4 的 `fixtures/ps1_replay.csv`、
E6 的 `ps1_5rows`/`ps1_2pages`）都带一列 `ps1_snr`。**站点不发布这一列**：
2026-10-04 逐列实测，`CATALOG_COLUMNS['ps1']` 登记的 30 列与真实回包**零差异**
（双向都没有），其中没有 `snr`；ps1 的逐波段不确定度列是 `*_err`（如 `ps1_rpsf_err`），
`*_corr` 四列则是**整列全空**。

**这四份已全部换成实抓数据并把这列去掉**（2026-10-04 完成）：

| 夹具 | 现状 | 换法 |
|------|------|------|
| E4 `fixtures/ps1_replay.csv` | 实抓 3 行（r60 快照第 31/69/159 行） | `[已净化]robustness/fixtures/README.md` |
| E6 `ps1_5rows` | 实抓 5 行（服务端约束查询回包） | `[已净化]repro/fixtures/README.md` |
| E6 `ps1_2pages` → **`ps1_singlepage`** | 实抓 3 行单页 | 同上（原名描述的分页形态站点并不产生） |
| E6 `scr_galah_3rows` → **`scr_galah_0rows`** | 实抓 0 行 + 141 列表头 | 同上 |
| E2 `syn_missing` | **有意保留合成** | 站点不产生「列不存在」的回包（不存在的列被服务端忽略，回包永远是完整列集），这条形态无法真实抓出 |

> 现在读这三份 E6 夹具时**不该**再看到 `ps1_snr` —— 若读到了，说明拿到的是旧副本。
> 本节一度写着「E6 的三份**尚未换**」，那是在换夹具**之前**写的、换完没回头更新的
> 过期陈述；本仓有先例（commit `95a7bc7`「更正三处与 git 事实矛盾的陈述」）。

> 教训比这一列本身重要：**照着合成夹具的列名写代码，会写出一个站点不发布的列**。
> 列名以 `CATALOG_COLUMNS` 与真实回包为准，夹具只用来造形态。
> —— 而本节自己就踩过一次反过来的坑：**照着"夹具里有什么列"去描述夹具现状**，
> 夹具换了、描述没换，于是 reference 说了假话。写现状的文档要与被描述的对象同批更新。

## 5c. `ps1` 回包是**两种记录混排**：对象记录 vs 点源记录（2026-10-05 实测）

**先说结论**：`ps1_source_id` **不是**"线上逐行为空"那一列。`ps1` 的回包把**两类
结构不同的行首尾相接**返回 —— 有对象信息但测光列写 `nan` 的**对象记录**，与有点源
测光但对象列全空的**点源记录**。**对象级列与点源级列互斥**，覆盖比例**随天区变**。

**判型方法（一行判据）**：`ps1_source_id` 非空 ⇔ 对象记录；为空 ⇔ 点源记录。

| 列族 | 对象记录（A 组） | 点源记录（B 组） |
|---|---|---|
| `ps1_source_id` / `class_star` / `ruwe` / `parallax` | **有值** | **整列空串** |
| `ps1_gpsf` / `rpsf` / `zpsf` / `ipsf` / `ypsf` | 有值，但**混着 `nan`** | 有值，含 `-100x` 哨兵 |

### 5c.1 覆盖是位置相关的（`temp/G8-LIVE-ps1-recordtype.py`，r=600″ / 300 行实跑）

| 天区 | `total` | A 组（对象记录） | B 组（点源记录） |
|---|---|---|---|
| (286.1, 15.7) | 56892 | **128**（索引 0–127，连续） | 172（索引 128–299） |
| (180.0, 30.0) | 20628 | **0** | 300（全 B） |
| (10.68, 41.27) | 156554 | **0** | 300（全 B） |

→ **同一个查询语句，换天区就换回一种记录。** 任何"ps1 的某列有没有值"的结论，
不加天区限定都不成立。仓内已入库快照也印证这一点（`temp/G8_probe_srcid.py`）：

| 快照 | 行数 | `ps1_source_id` 非空 | 去重后 |
|---|---|---|---|
| `live_ps1_ra180.0_dec30.0_r5.0as` / `_r60.0as` / `_r120.0as` | 3 / 174 / 770 | **0** | 0 |
| `live_ps1_ra0.0_dec90.0_r60.0as` | 163 | **0** | 0 |
| `live_ps1_ra29.967632_dec0.024272_r5.0as` | 4 | **0** | 0 |
| `live_ps1_ra180.0_dec30.0_r240/300/480/900.0as` | 各 1000 | **0** | 0 |
| `live_ps1_ra180.0_dec30.0_r300.0as_max4000` | 4003 | 3（**不是 id**：分页续抓时重复落进数据的表头行，取值恰为字符串 `ps1_source_id`） | — |
| `live_ps1_ra359.5_dec0.0_r1800.0as` | 1000 | **431**（A 组连续占据索引 0–430） | 569 |
| `live_ps1_proximity_n3_5d2580ec` | 3 | **该列根本不在投影里**（只有 `inputobjs_*` + `ps1_ra/dec/ipsf/rpsf`） | — |

### 5c.2 用 `ps1_source_id` 当主键的**两个**失效条件

1. **B 组整列为空** —— 拿整列建主键会让 B 组全部塌成一个值，逐格比对变成自己比自己。
   仓内绝大多数 ps1 快照（上面 8 份）**整个结果集都是 B 组**，此时该列零可用。
2. **A 组内部也不保证唯一** —— `live_ps1_ra359.5_dec0.0_r1800.0as` 的 431 个非空 id
   去重后只有 **430** 个（`2449920474593168128` 出现 2 次）。有值 ≠ 唯一。

**正确口径**：主键可用性由**结果集**判定，且**必须先分记录类型**。
`[已净化]groundtruth/canonical.py::id_keys_unique()` 取集合内最小判据，出现重复即整批
改用 `(ra, dec)` 量化键（保留 9 位）—— E2 的 `cone_5as` 等 8 份 case 走的是这条兜底。
注意这条兜底目前**不感知记录类型**，它只是发现重复后降级，对"A 组为主 + B 组少量"
的结果集仍会给出 `source_id` 口径 —— 这是已登记的待改进项（见下）。

### 5c.3 「无值」有**五种**具体编码（两种字符串 + 三种数值哨兵），按"等于哨兵"判空会漏判

| 编码 | 出现位置 | 样例 |
|---|---|---|
| **空串 `""`** | B 组的全部对象级列 | `ps1_source_id = ""` |
| **`nan`（字面字符串）** | **A 组的点源级列** | `ps1_gpsf = "nan"` |
| **数值哨兵 `-100x`（带）** | B 组的点源级列 | `ps1_gpsf = -1004.0688964246228` |
| **数值哨兵 `-999`（点）** | `*_err` 列 | `ps1_gpsf_err = -999.0` |
| **数值哨兵 `-32768`（点）** | **`uss_dr1` 的 12 个 `*_flag` 列**（`u_flag`/`j0378_flag`/…/`z_flag`；入库快照 `live_uss_dr1_ra120.3_dec-20.4_r300.0as` 实测 **9046** 个单元格，恰为 int16 下界；**值域是「点」不是「带」** —— 逐列去重后每列只有这一个取值，写死相等即可判） | `u_flag = -32768` |

2026-10-05 实测 (286.1, 15.7) 的 128 行 A 组里，`ps1_gpsf` 有 **98/128 是 `nan`**、
`rpsf` 56/128、`zpsf` 37/128、`ypsf` 37/128（`ipsf` 0）。**即 A 组并非"测光列全无"，
而是"测光列有 `nan` 也有真值"** —— 只认 `-100x` 哨兵的过滤器会把 `nan` 当成有效星等。
`nan` 此前**未被任何仓内文档登记**（`[已净化]_data/null_sentinel.yaml` 与本文 §5c 都只
记了 `-999.0` / `-1004.07`）。

⚠ `nan` 是**字符串**不是浮点 NaN —— 走 `float()` 解析时会被读成"能转换的数"
（`float("nan")` 合法），随后任何 `==` / `<` 比较都恒假。**判空必须显式列全五种编码。**

> ⚠ 哨兵**逐表不同**，判空不能跨表套用。上表五种里**只有三个数值哨兵**参与阈值判定：
> `[已净化]_data/null_sentinel.yaml` 的约定是 **`value <= threshold`（不是 `==` 某一个
> 具体值）**，`threshold: -999.0`，故 `-999.0` / `-1004.*` / `-32768` 三者**全部落在
> 阈值内**（`-32768` 是 int16 下界，远低于阈值）—— **判定逻辑一行未改，本节只是把
> `-32768` 这条实测形态补登记进 `per_catalog` 的已知实例清单**。另两种（空串 `""` 与
> 字面 `nan`）是**字符串**，压根不参与 `<=` 比较，必须按字面单列判。
> 另注：`-1004.*` 那一族是**带**不是点，2 位小数上就分裂 —— 已实测到 `-1004.07` /
> `-1004.08`（ps1 @180,30 60″）与 `-1004.09`（ps1 @286.1,15.7 r=600″），**同一列至少
> 三个不同取值**，浮点精确相等一个都命中不了。

> 上一版本文写的是"`ps1_source_id` 线上逐行为空" —— 那是**在 (180.0, 30.0) 单点
> 测得的局部结论被当成了全局属性**。同仓另一条教训是同一句话在
> `docs/EVAL-LIVE-FETCH-WAIVER.md` §5.1（该文件不在本文归属内，待统一处理）。
> 推广前先问"这个结论是在几个采样点上测的"。

## 5d. 本节实测的复现口径

```powershell
python temp/G8-LIVE-ps1-recordtype.py   # 实站: 三天区分型 + nan/带哨兵逐列计数 (联网)
python temp/G8_probe_dualrecord.py      # 离线: 已入库快照的 A/B 组分型与编码清点
python temp/G8_probe_srcid.py           # 离线: 逐快照 *_source_id 非空/去重计数
python temp/G8_probe_sheet.py           # 离线: 快照目录数 / 文件数 / 签字单联抽样规则
```

`temp/` 是 gitignored 的临时产物目录（铁律 3）：脚本只作本轮取证，结论已写进正文，
脚本本身不入库。离线部分要复算请直接读
`[已净化]groundtruth/snapshots/live-2026-10-04/*/rows_full.csv`。

## 8. 编码约定

| 格式 | 编码 | 理由 |
|---|---|---|
| CSV / TSV | `utf-8-sig` | Excel 双击打开不乱码 (站点 CSV 也带 BOM, 读侧用 `utf-8-sig`) |
| JSON | `utf-8` | BOM 会破坏标准 JSON 解析器 |
| VOTable | `utf-8` | XML 声明自述编码, BOM 会让严格解析器拒收 |
| FITS | 二进制 | astropy 负责 |

## 9. 复现命令

```powershell
python temp/format_probe.py                        # 逐格式实测落盘结果
python -m pytest test/unit/serialization -q        # 50 项格式层回归
python -m pytest test/integration/test_release_regressions.py -q   # 透传/类型/路由回归
```
