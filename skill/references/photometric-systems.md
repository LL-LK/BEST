# photometric-systems.md — BEST 测光系统与精测定标口径（官方文档层）

> 本文内容取自官网文档页 `https://nadc.china-vo.org/data/best/doc/system-en/catalog`
> 与 `.../doc/system-en/help`（采集，原文存 `temp/catalog_doc.txt`）。
> 官网口径以本文件为本地镜像；与线上不一致时以线上为准并回写本文件。
> **论文引文不在此文** —— 全部移入 `rag/knowledge/citations.yaml`（DOI 均
> Crossref 实核）；本文只存使用向的测光系统/精度/规模口径。

## 1. 标准星总口径（Standard Stars Based on the Gaia DR3 XP spectra）

- **SCR 方法单星精度**：u/v 类波段约 **0.01–0.02 mag**；grizy 类波段约 **0.001–0.005 mag**。
- **恒星参数表**（Stellar Parameters）：
  - LAMOST DR11 — 2.18G 星；GALAH DR4 — 281.5M 星。
  - 官方筛选口径（原文）：仅 **4500–6500 K 的矮星（dwarf）**、**消光 Av < 0.1 mag**，
    并对光谱信噪比设下限以保证导出参数可靠；更多星与补充光谱数据留给后续版本。
- 对查询的含义：SCR 标准星不是"全量 Gaia"，选表时若需 Teff/log g 参数
  应预期上述矮星/低消光子集，富巨星与高消光天区不在覆盖内。

## 2. 测光系统全表（19 个系统，官网 catalog 页逐行镜像）

星数为该系统的标准星星数（G = 10 亿）。作者列为主联系人。

| 测光系统 | 波段（passbands） | 标准星数 | 作者 |
|----------|------------------|---------|------|
| APASS | B, V, g, r, i, z | 30G | Kai Xiao |
| BASS | g, r | 9.9G | Kai Xiao |
| CSST | u, g, r, i, z, y | 30G | Kai Xiao |
| DES | g, r, i, z, Y | 30G | Kai Xiao |
| Gaia DR3 | G, GBP, GRP | 15G | Bowen Huang |
| Hipparcos-Tycho | Hp, B, V | 15G | Kai Xiao |
| JKC | U, B, V, R, I | 25G | Bowen Huang |
| J-PAS | u, uJava, gSDSS, rSDSS, iSDSS + 55 个 J0xxx 窄波段 J0378–J1007 | 296G | Kai Xiao |
| J-PLUS | uJAVA, gSDSS, rSDSS, iSDSS, zSDSS, J0378, J0395, J0410, J0430, J0515, J0660, J0861 | 60G | Kai Xiao |
| Kepler | Kepler | 5G | Kai Xiao |
| LSST | u, g, r, i, z, y | 30G | Kai Xiao |
| Mephisto | u, v, g, r, i, z | 30G | Kai Xiao |
| Pan-STARRS | g, r, i, z, y | 25G | Kai Xiao |
| SDSS | u, g, r, i, z | 25G | Kai Xiao |
| S-PLUS | uJAVA, gSDSS, rSDSS, iSDSS, zSDSS, J0378, J0395, J0410, J0430, J0515, J0660, J0861 | 60G | Kai Xiao |
| SiTian | g, r, i | 15G | Kai Xiao |
| SkyMapper | u, v, g, r, i, z | 30G | Kai Xiao |
| TESS | TESS | 5G | Kai Xiao |
| ZTF | g, r, i | 15G | Kai Xiao |

J-PAS 窄波段全集（官网逐行，55 个）：J0378, J0390, J0400, J0410, J0420, J0430,
J0440, J0450, J0460, J0470, J0480, J0490, J0500, J0510, J0520, J0530, J0540,
J0550, J0560, J0570, J0580, J0590, J0600, J0610, J0620, J0630, J0640, J0650,
J0660, J0670, J0680, J0690, J0700, J0710, J0720, J0730, J0740, J0750, J0760,
J0770, J0780, J0790, J0800, J0810, J0820, J0830, J0840, J0850, J0860, J0870,
J0880, J0890, J0900, J0910, J1007（共 55 个；2026-09-29 与
`CATALOG_FORM_TABLES['xpsp']` 的 55 个 `jpas_j*` 表逐一相符，含 J0900）。

**波段命名陷阱**（实测列名前缀规则，见 best-database-guide.md §表单字段）：
- SDSS 系系统用 `gSDSS/rSDSS/...` 与本地 `g/r` 区分；J-PLUS/S-PLUS 兼有
  `uJAVA` 与 `J0xxx` 两套窄波段列，`showcol` 投影时须用线上表单页给出的
  `{table}.{col}` 全名，不能凭缩写猜测。

## 3. Well-Calibrated 星表：精度 / 规模（论文引用见 rag/knowledge/citations.yaml）

| 星表 | 官方精度口径 | 规模 | 文献（short id） |
|------|-------------|------|----------------------|
| Pan-STARRS All-sky | 1–2 mmag @ 14′ 天区 | 1.4T | `C-xiao-yuan-2022-ps1`；`C-xiao-2023-ps1-lamost` |
| Gaia Photometry | ~1 mmag | 1.8T | `C-yang-2021-gaia` |
| Landolt Standard Stars | <10 mmag @ U；1–2 @ BVRI | 9.8M | `C-huang-2025-landolt`（**unverified**，to be submitted） |
| SDSS Stripe 82 | 2–5 mmag（约 5 倍提升） | 236.4M | `C-huang-yuan-2022-stripe82` |
| J-PLUS DR3 | 零点 1–5 mmag（2–5 倍提升） | 9.2G | `C-xiao-2023-jplus`；`C-lopezsanjuan-2024-jplus` |
| S-PLUS DR4 | 零点 1–6 mmag（2–5 倍提升） | 18G | `C-xiao-2024-splus` |
| S-PLUS USS DR1 | 零点 1–6 mmag（2–5 倍提升） | 643M | `C-li-2025-uss` |
| SkyMapper DR4 | 零点 1–5 mmag | 34G | 官网未列文献 |

> **引文纪律**：上表 short id 对应 `rag/knowledge/citations.yaml`（每条 DOI 均
> Crossref 实核）。本文件只存使用向内容；需要题名/作者/BibTeX 时
> 检索 citations.yaml。官网对 Stripe 82 一条漏写期刊名（Crossref 补全为 ApJS
> 259, 26）；Gaia 一条官网写 "908, 24"，Crossref 为 908, L24（同页）。

## 4. 官方引用口径（help 页 Citation 段）

- 官网要求引文两则：**Xiao et al. (2025, Scientific Data, submitted)**（无 DOI，
  unverified）与 **Huang et al. (2024, ApJS, 271, 13)**。
- 两条的完整元数据（题名/作者/BibTeX/DOI/arXiv）在
  `rag/knowledge/citations.yaml`（`C-xiao-2025-scidata` / `C-huang-2024-xpspec`），
  DOI 已经 Crossref 实核；本文件不重复引文内容。

## 5. User-Defined Catalog（自建标准星，需登录）上传协议

官网 help 页原文口径（采集）：

- 输入 **仅 FITS**，必须含两列：`wavelength`（单位 Å，**范围 3360–10200**）与
  `function`（归一化响应曲线）；另填 `Photometric system`（如 SDSS）与 `Band`（如 r）。
- 点 Run 后作业进入 Jobs 表；**Phase 保持 pending 超过 1 分钟应重新上传提交**。
- 空闲服务器上典型作业**每波段数分钟内可生成 2 亿+ 标准星**。
- 查询区批量上传口径：CSV **只含 ra/dec 两个列头**，单文件建议 <1000 万个源；
  更大数据集走 Catalog 区整表下载。

本 skill 的 OAuth 身份层（`src/auth/`）即为此区登录服务；未获 NADC 应用审批前
真实作业流标记 blocked-on-approval（client_id/secret 需 NADC 管理员发放）。

## 6. 文档 ↔ 现实偏差记录（实证）

- **SkyMapper DR4 在 catalog 文档页的 Well-Calibrated 表内（34G），但线上不可查询**：
  `GET /data/best/skymapper_dr4/f` 返回 `{"error":"Not Found"}`（软 404），
  `/data/best/calib` 分组页仅列 7 张表（stripe82, gaia_dr3_18, jplus_dr3, smss_dr4,
  landolt, uss_dr1, splus_dr4），无 skymapper。教训：**文档存在 ≠ 可查询**，
  以 `/f` 路由实测为准。
- 同理， catalog 文档页的 19 个测光系统是标准星侧覆盖，不逐一对应可查询表。

## 7. 网站元信息

- News：2025/05/20 首发（Initial release）；发布公告见官网 news 栏目。
- 联系：科学问题 Kai Xiao (xiaokai@ucas.ac.cn) / Yang Huang (huangyang@ucas.ac.cn) /
  Haibo Yuan (yuanhb@bnu.edu.cn)；网站技术 Dongwei Fan (fandongwei@nao.cas.cn)；
  修正 XP 光谱 Bowen Huang (student@example.edu.cn)（2026-09-29 对 help 页
  镜像复核：早前转写为 2022 开头，官网原文为 2021 开头）。
- 官方承诺响应时限 15 个工作日；平台声明"功能可能频繁更新"。

## 8. 复现方法（本文件内容的取证步骤）

1. `GET https://nadc.china-vo.org/data/best/doc/system-en/catalog` → 保存 HTML，
   去标签后按表格行镜像 §1–§3（星数/精度/文献列以官网原文为准）。
2. `GET .../doc/system-en/help` → 镜像 §4 引用块与 §5 上传协议；`.../doc/system-en/news`
   → 镜像 §7 版本信息。
3. §6 偏差实证：`GET /data/best/skymapper_dr4/f` 记录响应体前 22 字节；抓
   `/data/best/calib` 分组页枚举 `href`，确认 7 张可查询表。
4. DOI 核验：对 §3/§4 每条文献以 Crossref REST
   (`https://api.crossref.org/works?query.bibliographic=…`) 取题名/期刊/卷/页/年份
   逐字段比对；不一致以 Crossref 为准并在表内注明。全部脚本与原始响应留在 `temp/`。
