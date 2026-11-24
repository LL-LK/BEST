# Changelog

> 本文件只记录修改内容（改了什么、为什么改），不声明也不引用代码版本。
> 每条以修改日期为节，按时间倒序排列。

## E5 三项隔离门禁：核出「一项未落地、一项检测面失效」，并修复（2026-10-11）

核的不是结论，是门禁本身。三项里只有「批次唯一性」真落地，另两项各有缺口。

- **`write_traces()` 没有任何并发保护**（`evals/ablation/harness/run_batch.py`）。
  旧实现 `path.write_text()` 直写固定文件名 `runs/<system>/<item>__aN.json`：
  两个进程撞车即 last-writer-wins（那一轮是两份数据的混合，与 D-18 同形）；
  写到一半崩掉留下**半截 JSON**，而下游按 `*.json` 扫，半截文件会被当正常轨迹吃掉；
  重复跑批静默覆盖旧轮次 —— 「只增不改」只是句注释，**没有执行者**。
  改为目录级互斥锁 + 临时文件 + `os.replace` 原子提交 + 同名拒写（须显式
  `--overwrite-traces`），报告内撞 (system,item,attempt) 即判错。
- **后验审计器对 240 格新数据全程空转**。`temp/audit_scratch.py` 写死
  `ROOT/temp/scratch/<batch>`，而投放器已把 scratch 迁到 `%TEMP%/e5_scratch`
  —— 两边各有一份根目录字面量，漂移无人拦。实测 `audit_scratch.py b3_s1 24`
  回「没有该批次」，10 个新批次从未被审过，而文档仍把「检测」记作已完成。
- **「并发写保护」从未被实现**，文档里的「拒绝复用批次名 ⇒ 防并发覆盖」是把
  「名字唯一」误当成「写者唯一」：D-18 的真实形态是批次**已投放**后往同一 scratch
  派第二个代理，批次名自始至终唯一，两个写者写的是同一批。
- 修法：实现搬进仓内 `evals/ablation/iso/`（原在 `.gitignore` 排除的 `temp/` 下，
  交付包里根本翻不到），根目录收成 SSOT `paths.batch_dir()`，建批改原子
  `mkdir(exist_ok=False)` + `O_EXCL` 写者标记，审计新增**单写者判据**
  （out 的 mtime 相邻空档 > 60s 即判红）。`temp/` 下两份旧脚本降级为转发入口。
- 复验：单写者判据对已知双写者批 `rep_b3_r2` 判红（空档 94.854s），对旧干净批
  `dcs_pilot` 不判红（46.0s）；10 个新批单写者全过但**全部无主**（早于写者标记，
  故其结论须写「观测到」而非「已归属」）。新增 15 条单测；E5 既有 89 条全绿。
- 两个新 env 键在 `ops/audit/env_scope.py` 逐条裁定为非部署期输入，`verify_crossrefs`
  转绿。仍未修：`temp/decision_iso` 与生成器未入库 ⇒ 投放不可自行复现。

### 同一天第二轮：G3 从「名字唯一」补到「会话唯一」

第一轮把"批次名不得复用"做实了，但**挡不住 D-18** —— D-18 是批次**已投放**后往同一
scratch 再派一个代理，批次名自始至终唯一。补三件事：

- **写会话**（真正的拦截点）：`begin_write` / `end_write`，同批同时只许一个未关闭的
  写会话，只有显式 `end_write` 能关；第二个 `begin_write` 撞 `.writing` 即拒 (exit=5)。
  **中间踩过一个坑**：第一版按"上一个会话的 pid 活不活"判，实测**形同虚设** ——
  开会话的 CLI 进程调完就退出，pid 被判死，第二次照样成功。改为"标记在不在"，
  要清必须由人显式 `force=True` 并把被清掉的旧会话记进新标记留痕。**不靠猜进程死没死**
  （与 D-17/D-18 同源：又是一次"我以为它结束了"；且开会话的进程 ≠ 真正的写者）。
- **写者令牌**：`.owner.json` 加一次性 `uuid4`。pid 会被操作系统复用，只比 pid 会把
  旧批的主人误认成当前会话。
- **审计加三条不依赖时间戳的判据**：写了未分配的格（`.cells.json` 比对）、**收尾后**
  新增/重写（`.finished.json` 指纹比对）、无收尾快照（未走 begin/end 流程）。
  实测追加一个文件时 mtime 空档只有 **1.77s**，远低于 60s 阈值 —— **时间戳判据
  完全看不出来**，这三条补的正是它的盲区。
- 复验：`test_e5_isolation_gates.py` 由 15 条增至 **26 passed**；`test_e5.py`
  **46 passed**；硬门禁仍为改前那 3 道 HEAD 既有红（`comment_audit` / `code_fingerprint`
  / `verify_eval_report_assets`），新增文件未上 `comment_audit` 榜单。

## 补两条登记册外的真缺陷：亮度筛选对真实列名整表空转 + 误差列被当星等（2026-10-06）

这两条同源于一处判据：星等列的识别方式。修的是根，不是症状。

- **`BestProcessor.bright_sources` 对绝大多数星表是空操作**
  （`src/core/source_postprocess.py::_best_magnitude`）。回退判据是
  `key.endswith("mag")`，而站点实际发布的列名是 `ps1_gpsf` / `ps1_rpsf` /
  `splus_dr4_u_pstotal` / `gaia_dr3_18_phot_g_mean_mag` —— **名字里没有
  `mag`**。实测一行真实 ps1 源（`ps1_gpsf=15.0`）走 `bright_sources(.., 16.0)`
  返回 `[]`：被当成「无测光」整行剔除。谓词头里的 `best_mag` / `best_magnitude`
  两个键同样不存在于任何星表的星等列集合（8/8 核账为 0），即回退路径也够不着。
  改用 `src.serialization.is_magnitude_column` —— 它由
  `protocol.CATALOG_MAG_COLUMNS` 现场推导后缀集，是星等列的单一真源。
- **误差列被判成星等列**（`src/serialization.py::is_magnitude_column`）。
  后缀匹配的固有漏洞：误差列名往往**以星等列名结尾**
  （`splus_dr4_e_u_pstotal` 以 `u_pstotal` 结尾、`ps1_gpsf_err` 以 `gpsf`
  结尾），纯 `endswith` 于是把误差列收进星等。两处后果：
  `votable_document` 给误差列挂 `unit="mag"`（TOPCAT 侧会把 0.003 角秒的
  不确定度当星等换算）；按列取代表星等时可能把 0.003 当成一颗 0.003 等的亮源，
  而亮度筛选正是拿它排序的。新增 `MAGNITUDE_ERROR_SUFFIXES`（由
  `CATALOG_MAG_ERROR_COLUMNS` 对称推导），误差列先判、星等列后判。
  回归 `test/unit/serialization/test_magnitude_column_predicate.py`（8 条，
  含"真值列仍被认出"的反向对照，防「一律判否」那种假修）。

顺带说明为什么这两条之前没人看见：它们都**不抛异常、不影响退出码**，亮度筛选
返回空列表看起来像"这片天区真的没有亮源"，而 `unit="mag"` 挂错列也不会让解析器
报错 —— 与铁律 5 关注的"门禁显示通过而事没做成"是同一类。

## 修四条「不在任何登记册里」的真缺陷 + 两处门禁自身 fail-open（2026-10-06）

审计记录里反复出现同一个结构性问题: 若干**真缺陷从未进入任何登记册**, 按册工作的
修复者永远看不到它们; 而其中两条恰好被本轮的结构变更**触发或暴露**。以下四条逐条
以实跑取证修掉, 不是照抄报告结论。

- **测光上侧缺测哨兵 99.0 未识别**（`src/models/__init__.py` +
  `src/tap/formats.py`）。先验后修: 报告称 `uss_dr1` 34 处 / `splus_dr4` 54 处, 但
  在 87 份真实快照 34,379 行里按星等列名逐列复算, `uss_dr1` 实得 **0 处**,
  `splus_dr4_*_pstotal` 实得 **284 处** —— 计数与归属都对不上, 说明不能照单全收。
  再看分布坐实性质: `splus_dr4_u_pstotal` 412 个取值里真值域 15.5649..27.9548
  (n=398), 99.0 恰为**最大值**且与真值域之间是干净空档; 同批 `*_err` 列的 99.0
  计数与值列**逐格相等**（14/14）—— 误差列不会有这种巧合。故新增
  `BestSource.NULL_MAGNITUDE_UPPER_SENTINEL = 99.0`, 在**测光分支**判缺测。
  **判据刻意不越界**: 视差等天体测量列的 99.0 是合法毫秒值, 无差别套用会抹掉真实
  视差, 回归 `test_sentinel_upper.py::TestUpperSentinelMustNotLeakToAstrometry`
  专门钉这条。两个消费方 (行模型 / TAP 导出) 同判, 不留口径分叉。

- **同一张表多个星等列时「过滤列 ≠ 取值列」**（`src/models/__init__.py::from_row`）。
  `scr_galah` 给每个波段标签发**三列**（u 带 = `ujkc` / `usdss` / `usplus`, 全表
  30 列塌成 10 个标签）。查询层 `protocol.magnitude_column` 取**首个**匹配列并据此
  下发约束, 行模型却是无条件 `dict[label] = v` 的**后写覆盖** —— 最后一列
  (`usplus`) 赢。后果是用户按 band="u" 下发的条件落在 `ujkc` 上, 返回的却是
  `usplus` 的值: 实测差 **0.16963370 mag** 的系统偏差, 按自己刚下的约束比对永远
  对不上。改成**首个有值的列胜出**, 两条路径取同一列。实跑复核 14 个可比行, 修后
  0 处不一致 (修前该行的 u 带模型值即 `usplus`)。

- **标识符被 `float()` 静默改写**（`src/tap/formats.py::convert_table_rows`）。
  实跑量化: 87 份快照 744,344 个非空格里有 **1,074 格不可逆损坏** ——
  `gaia_dr3_18_source_id` 的 `4512921183874236032` (>2^53) 落成
  `4.512921183874236e+18`, `ps1_source_id` 等四列同病, 且 VOTable 与 CSV 两个出口
  对同一份数据给出两个不同的标识符。护栏复用 `src/serialization.py::must_stay_text`
  (前导零 / 超 2^53 整数字面量), 按**值形态**判而不是按列名猜 —— 所以新星表新增
  标识符列不必改代码就自动受保护。修后同一口径复跑 **0 处**。

- **`.env` 从未被读取**（`src/scripts/config.py::load_dotenv_file` +
  `src/__main__.py`）。`.env.example` 第 2 行一直教用户 "Copy to .env and fill in
  your credentials", 而全仓此前**零代码读 .env** —— 那是一句骗人的指令, 用户照做后
  凭据进不了进程, 表现为「配了却不生效」。用 **~40 行 stdlib** 实现, 不引
  `python-dotenv` (依赖零新增是本仓铁律)。语义刻意与主流 dotenv 一致: 真实环境
  变量优先 (默认不覆盖)、支持 `export ` 前缀/成对引号/行尾注释、认不出的行跳过
  而不抛。只在 **CLI 入口**加载, 不在模块导入期 —— 库调用方 import `src.*` 不该被
  改动进程环境。

- **门禁自身两处 fail-open**（同期暴露, 顺手修掉）:
  - `ops/audit/code_fingerprint.py` 的 `removed` 计数**结构上恒为 0** ——
    覆盖面取自 `iter_py_files` (文件系统遍历), 被删的文件根本不会被产出, 紧随的
    `os.path.exists` 分支对真正的删除是死代码。实测删掉 4 个受跟踪 .py 时门禁照样
    报 `removed=0` 且退出码不含它 → **删文件不红**。改从 `git ls-tree HEAD` 取
    清单, 删除即刻计入并参与退出码; 同时补扫工作区保住 `new-untracked` (只改一
    半会让"新写了 .py 没提交"彻底看不见)。回归:
    `test/unit/meta/test_code_fingerprint_deletion.py`（4 条, 在临时 git 仓里造场景,
    不碰工作区; 关键是**装进门禁副本**而不是只改 cwd —— 它的 REPO 由文件位置算出）。
  - `ops/verify_tree_integrity.py::OPAQUE_DIRS` 漏登记 `.worktrees/`
    (`.gitignore:105` 已忽略)。漏登记的表现是树门禁把并行工作树里几十个文件当成
    「疑似未授权新增」, 而 `--write` 会把工作树副本写进 SSOT —— 等于把临时产物登记
    成架构资产。`ops/audit/scan_roots.py` 的 `EXCLUDED_DIRS` 同口径补上。

## 再修三条登记册 P0：同列多约束静默覆盖 / 序列化零哨兵转换 / 视差哨兵放行（2026-10-06）

三条都是**已复现**的静默错答，共同点与前几笔相同：不抛错、不改退出码、产物看着正常。

### P0-16 同列多约束静默覆盖（`src/protocol.py::build_query_form`）

表单键是 `{prefix}.operation` 这一**对**，同前缀写第二次即覆盖。实测：同一列先给
`greaterequal 15.0` 再给 `lessequal 18.0`，产出只剩后者（operation 键数 = 1），
于是「15 <= r <= 18 的区间」悄悄退化成「r <= 18」，返回集混进大量 r < 15 的源，
而调用方以为自己限了下界。处置：显式 `ValueError`，带列名/冲突双方/出路；**不自动
合并成 between**（两次 greaterequal、contains+lessequal 都无从合并，猜语义仍是静默
给错答案）。回归 6 条含三组反向对照。

### P0-14 序列化五格式零哨兵转换（`src/serialization.py`）

AH3 记「serialization 五格式零哨兵转换」，本轮按行为复验属实：`ps1_gpsf = -1004.07`
经本模块落盘后**仍是 -1004.07** —— 一个**缺测**被导出成一颗「-1004 等」的源，而同仓
TAP 出口早已转成 NaN。两个出口对同一份数据给出两个值，前者还把任何按该列做的统计彻底
带偏（均值被拉到 -1004 量级）。三出口（CSV/TSV、VOTable、FITS）统一经
`_sentinel_aware_cell`，判据取 `BestSource.NULL_MAGNITUDE_SENTINEL` 同一阈值（哨兵是
**带**不是点，ps1 各波段带心不同）。**只对星等列生效**是关键限制：无差别套用会把高自行
星的 `pmra ≈ -1500`（合法 mas/yr）抹成 NaN —— 那正是 P0-03b 记的「静默丢真实自行」。

顺带订正一条**样例值误选**的既有用例：`test_negative_numbers_are_not_quoted` 曾拿
`-1004.07` 当「合法负数」的例子，而该值正是 ps1 缺测哨兵（负到 -1004 的星等物理上不
存在，最亮恒星约 -30）。改用同样合法但不在哨兵带内的 `-5.0`（其 docstring 本就点名
这个值），意图不变，另加一条反向对照钉住哨兵那一半。

### AH3-04 哨兵豁免按整类天体测量列（`src/models/__init__.py`）

原实现写 `kl not in _ASTROMETRIC_COLUMNS`（天体测量列**整类**白免），而那一支自身
注释给出的理由只有一条：高自行星 pmra 可达 ±1e4 mas/yr —— 而 pmra/pmdec/
radial_velocity 本就在 `_SENTINEL_EXEMPT_COLUMNS` 窄名单里。整类豁免比理由所需宽得多，
顺带把**视差的缺测哨兵**放行了。

收窄依据（扫仓内全部快照 34,379 行逐列核量程）：`gaiaxp_photinfo_replenish_parallax`
有 **108 个 <= -999 的取值，且逐字相同都是 `-999.0`**（固定值签名，与 ps1 测光哨兵
同款写法），而真实视差量级只到 ±15 mas；其余天体测量列（parallax_err / parallax_error
/ decrms / rarms）最小值全为正、<= -999 出现 **0 次**。原注释引用的证据是「ps1 与
gaia_dr3_18 各 200 行里没有这类取值」—— 样本窄了一档，结论在全语料上不成立。

处置：天体测量类不再整类豁免，豁免改由 `_SENTINEL_EXEMPT_COLUMNS` 单点裁决；将来
若有列的量程真的到得了 -999，加进那一份窄名单并附实测证据即可，不必重新放宽整类。
两条既有用例按新口径改写：真正要守的「合法大负值不被抹成 None」用 pmra 守住，
视差那半改成钉哨兵，并写明原结论的样本局限。

## 三条裁定落地 + 再修三条登记册缺陷（2026-10-06）

### 一、E2 精度下限下修 + 放行判据对齐契约（用户裁定）

原下限 `ra_deg/dec_deg=9`、`magnitude=6` **不可达**：金标准对自己记录的取值
要求比它实际含有的位数更多 —— 实测 `batch_proximity.json` 里 ps1_dec 记录值
本身只有 8 位有效数字却要求 `min: 9`；`live_ps1_ra359.5_dec0.0_r1800.0as`
（赤经 0/360 wrap 边界）1000 行里 ps1_dec 有 1 行 3 位、ps1_ra 有 1 行 3 位
+ 3 行 4 位。而 SUT 与站点原始文本**逐字节一致**（1000/1000），不存在截位层。
下限改为坐标 3 / 星等 3（snr 无失分故不动），17 份 gold 全部重生成
（diff 只含 precision_map）。

**代价写在表旁**：3 位坐标 = 3.6 角秒，粗于常规视宁度（约 1″），故这条判据现在
只能拦住「把坐标截成个位数」这类**粗暴**降精度。更强口径是「逐格比 gold 自己
记录的位数」（下界恒可达且真能抓住 SUT 截位），但那要改 m3_units 的入参与判据，
属判据重构，本轮未做 —— 留作下一步。

放行判据由 `(weighted >= PASS_SCORE) and not blockers` 改为
`not any(metric.pass is False) and not blockers`，与 `run_e2.py:360` 自己的注释
（「全过才算 PASS, 不按加权分和算」）及 E2 文档 ③ 放行行（「7 项全过 + 零红线才
exit 0」）一致。修前实测 17 个 case 里 **12 个**是「某项不过但均分仍过」的
fail-open；修后实现与契约在 17 个 case 上**零差异**，E2 由 exit 1 转 exit 0。

### 二、签字内容整体删除（用户裁定：全部取消和清除）

删 `evals/groundtruth/review/` 整目录（`gen_review_sheet.py` /
`backfill_reviews.py` / `HUMAN_REVIEW_SHEET.csv` / `review_focus.yaml` /
`README.md`）、其测试、17 份 `*.review.yaml` 侧车、`gold/manifest.json`
（经核对其 `entries` 为空、规则全是「未签字…不许进判定」，确属签字台账；其
指纹完整性职责已由 `provenance_drift` 承担）、`docs/eval-E2-signing-guide.md`；
`run_e2.py` 去掉 `sidecar_signed` / `human_review_*` / `review_disclosure` /
`verify_case_ledger` 等字段与逻辑，`pass` 只剩 case 全过 / 无缺件 /
metascore=1.0 三条；`gen_gold.py` 去掉 `--review-out` 与 gold 内嵌 review 段；
`CLAUDE.md:61` 与 E2 文档相关段落改为「已取消并删除」。保留
`provenance_drift` 全套（生成器指纹过期 + 快照身份不符，与签字无关，删了会让
过期金标准悄悄出 PASS）。

### 三、三条登记册缺陷（子代理并发修，逐条带实测证据）

- **P0-20 半径守卫放行 NaN**：实测协议层有**两条**独立于
  `guards.validate_search_radius` 的纯比较式守卫（`src/protocol.py` 的
  `radius_arcsec` 与 `default_radius_arcsec`，后者登记册未单列），`nan <= 0.0`
  判 False → NaN 直达 `pos.radius` / `pos.defaultRadius`。改为复用 guards 单点，
  连带引入其 5° 上限（与 `models/input.py` 既有口径一致，无调用点受影响）——
  **这是收紧方向的行为变化**，已在门禁里显式记录。变异验证：新用例撤掉修复即红。
- **AF2-05 `owner_key` 只认 IP**：根因是 `_authenticate` 只回布尔，令牌身份在
  建键前已被丢弃。改为认证态用**已校验令牌的 SHA-256 摘要**、匿名态用地址、
  两者皆缺显式拒绝（不并桶、不猜 IP）。实测三条断言修前 200/403/200 → 修后
  403/200/403。风险：共享网关 API key 的部署下认证用户会并成同一属主（该部署
  本就没有用户级身份），已写进 docstring。
- **AH3-08 两个 env 键零消费方 —— 登记册半数过期**：自跑三形态 AST 复计数后发现
  `quality_filter` **有**真消费方（`src/core/pipeline.py` 的字符串键动态读，正是
  已登记的 YZ-68），登记为「零消费」是计数方法的盲区 → **保留不动**；`log_level`
  确实全仓零消费（模块一律 `getLogger(__name__)`，无任何 `basicConfig` /
  `setLevel`）→ 从 `.env.example` / dataclass / env_map / 模板四个声明面同步退役。

### 四、`boundary_wrap_ra` 的 `'nan'` 漏出（`evals/groundtruth/canonical.py`）

`_as_float` 已对 `'nan'` 返回 `None`，但 `normalize_value` 把「不可解析」与
「可解析但非有限」并成一种 `None` 后**落回 `return text`**，丢弃了自己的判定。
修在最早能正确归一的这一层（上游 transport 与行模型按契约保留原始回包形态，
`m3_units` 只判不治）。已验证哨兵 `-1003.868…` / `99.0` / 大整数
`4512921183874236032` 与文本列均**不受影响**。

### 五、P0-19 复核结论：不是活缺陷

`write_fits` 对空 cell 已正确处理（数值列写 NaN、整列为空时落 char 列），
登记册本身标的是「STATIC-降级 / 本轮无独立证据, 不主张」——按实测确认为
**已覆盖**，故不改代码，只在此留档。

## 移除 MCP 通道与魔塔云分发组件（2026-10-06 结构变更，本轮结束）

按用户决定**整体移除**两条腿，并把全部在用声明面同步到位（不留悬空引用）：

- **删除的文件**：`ops/best_mcp_server.py`（stdio JSON-RPC 2.0 工具面传输，
  7 工具 / 离线自检 13 项）、`ops/cloud_modelscope/`（`dispatch.py` +
  `run.py`，魔塔云重算力分发入口）、`test/unit/ai_tools/test_mcp_server.py`。
- **评测面**：`mcp_server` 场景连同 `evals/probes.py::_exec_mcp_server_probe`、
  `evals/eval_runner.py` 的注册与 `evals/test-scenarios.yaml` 的条目一并移除 ——
  该探针原本 `import best_mcp_server` 当被测系统，server 没了它必然红。**行为
  评测场景由 25 条降为 24 条**，`probes.py` 与 `README.md` 的口径同步改写。
  `evals/cases/case_025_algo_agent_tools.yaml` 测的是 ToolBox 本身（不依赖
  传输层），保留，仅改掉注释里的传输层描述。
- **门禁面**：`test_registration_consistency.py` 的第三条腿「MCP 三层表述
  一致性」整条删除 —— 被测对象不存在时它要么恒绿要么恒红，两种都是假门禁，
  改成对已删文件的检查只会更糟。留下的两条腿（`conda_env` 口径、`--check`
  非空转）不受影响。`mcp_service` 登记项**保留为显式 `null`** 而非删键：
  母仓 `_shared/skill-registry.yaml` 里这一条还在，删键会让对账把它读成
  「本仓漏填」而不是「如实为空」。
- **配置面**：`.env.example` 删去 `MODELSCOPE_API_TOKEN` / `MS_JOB_NAME` /
  `MS_INSTANCE_TYPE` 三键及其分节（留着就成了「样例里有而代码没有」的空挂），
  文件头的消费方计数由「七处」改为「六处」。
- **文档面**：`manifest.yaml`（`cli.cloud` 条目）、`SKILL.md`（云端规格命令
  行、组件地图由「十三位一体」改为「十二位一体」并加「无 MCP 通道」说明）、
  `README.md`（快速开始、文件表两行、场景数、树清单）、`references/` 四件
  （`tools.schema.json` 删掉整块 `_server`、`ALGORITHM-SPEC.md`、
  `client-api-reference.md`、`llms.txt`、`auth-and-oauth.md`）、
  `rag/knowledge/` 两处、四个 `ops/audit/*` 门禁脚本里的示例注释。
- **历史记录不动**：`CHANGELOG.md` 既有条目、`docs/ISSUES*.md`（已带
  `status: archived` 横幅）、`docs/CODE-QUALITY-FIX-LIST.md` 里的 MCP/魔塔
  记载一律保留 —— 改写它们等于伪造历史判断依据。本节即为该次移除的留痕。

**顺带修掉两处门禁自身的漂移**（与本决策无直接因果，但同期暴露）：

- `ops/verify_tree_integrity.py::OPAQUE_DIRS` 漏登记 `.worktrees/`
  （`.gitignore:105` 已忽略）。漏登记的表现是树门禁把并行工作树里几十个文件
  当成「疑似未授权新增」，而 `--write` 会把工作树副本写进 SSOT —— 等于把临时
  产物登记成架构资产。现按 local-only 单行登记。`ops/audit/scan_roots.py` 的
  `EXCLUDED_DIRS` 同口径补上。
- `test_agent_fail_open.py` 里一条恒真空断言 `assert code_hint or True`：它
  名义上以 `code_hint` 参数化覆盖两支错误码，实际只抛 `Soft404Error`，
  另几支从未被走过。改为按**异常类型**参数化四支（Soft404 /
  NameResolve / ValueError / 兜底），错误码变成被验的输出而不是输入。

## E3-F06 修正：`jplus_dr3` 探点移出它自己的天区（2026-10-05 续十四）

上一轮补的 `E3-F06` 有一处**会惩罚正确答案**的缺陷：题目测的是
「`landolt` 的 0 是统计可解释的稀疏、`jplus_dr3` 的 0 可疑」这个**不对称**，
而它的 fixture 把 `jplus_dr3` 探在 **(120.3, −20.4)** —— 那是 **`uss_dr1`** 的
天区，不在 jplus 的公认天区（Dec −79…−45）内。

- **后果**：区外探到的 0 恰恰是「该表没覆盖这里」**能解释**的结果，于是题面与
  `must_state` 自相矛盾。一个读了知识面的模型会指出"这个 0 用天区覆盖就能解释"，
  而那个**更正确**的回答会被判错 —— **一道惩罚正确答案的题比没有这道题更糟**。
  本轮独立复核确认了这个缺陷（未照抄上轮结论）：`evals/semantics/items.yaml`
  的 `fx_two_zero_catalogs.tool_returns[jplus_dr3]` 记的确实是 `cone_ra: 120.3 /
  cone_dec: -20.4`，而同一份 fixture 的 `must_state` 要求答"疑似站点侧覆盖异常"。
- **修正**：`jplus_dr3` 的探点改为 **(10.0, −60.0)**（知识面 2026-10-05 已订正的
  公认天区代表坐标）。区内仍 0，「疑似站点侧异常」才与回包自洽。
  `must_state` 第 3 条显式写明"探点落在其公认天区**之内**、所以不能用覆盖解释掉"，
  `must_not_state` 新增第 4 条**禁掉"探点不在覆盖天区内 / 换个天区就好了"**这个借口。
- **真抓入库新快照**（铁律 7 改判后默认实跑）：先查 `temp/j3/raw/` 能否复用 ——
  **不能**：J3 的捕获只有分页 CSV 与一份探测元数据 JSON，**没有 `phase1.html`、
  没有 `capture_log.json` 的逐请求记录、没有 `manifest.json` 哈希**，手工拼一份等于
  编造溯源件（本仓吃过 `class_star=0.02` 的亏）。故按"素材重建入口"的规定用
  `ops/live_fetch.py` 重抓：`--set jplus_inregion --execute`（先 dry-run 确认计划，
  串行、间隔 1.5s、POST 不重试）。结果 `total_count=0 / success=true / 3 请求`，
  sqlid `s5080`，落盘 `evals/groundtruth/snapshots/live-2026-10-04/
  live_jplus_dr3_ra10.0_dec-60.0_r300.0as/`（7 件齐全，`manifest.json` 四个哈希
  逐一复算通过）。**新增快照目录 = 结构变更，已获本工单批准**。
- **新增任务集 `jplus_inregion`**（`ops/live_fetch.py`）：此前 `REAL_COVERAGE` 只有
  10 张表，`jplus_dr3` 与 `landolt` 登记在 `COVERAGE_NOTES` 的"实测取不到数据"一栏，
  **没有任何任务集会抓 jplus** —— 这正是当初只能沿用区外坐标的根因。新增集把区内
  探点变成可复现的抓取任务。`COVERAGE_NOTES` 里引作形态证据的快照名同步改为区内那份
  （区外那份标注作废，但**保留在库**：`E3` 的"回包同形"断言拿它当对照）。
- **判别力的诚实结论（未新增机器判据）**：修坐标后题面与 `must_state` 自洽了，
  但**机器判别力仍是零增量** —— L0 五项预筛全是正则/关键词启发式且"只标记不裁定"，
  抓的是"合并"的**下游后果**（凭空断言无源、编锥内源数），**不是"合并"这个动作本身**。
  纯合并、"说要分开但没给结论"、方向颠倒（landolt=坏表 / jplus=确认坏）三种坏回答
  **都漏过 L0**；判定权在 L2 人工评阅（`must_state` / `must_not_state`）。
  **未新增"跨表结论一致性"预筛**：那要碰 `rubric.yaml` §3 并抬高**全部 37 题**的误报率，
  而正则/关键词版无法把"两表给了相同结论"与"两表都提到了但措辞不同"分开 ——
  详见 `temp/FIX-M1-e3-f06.md` §M1-03。
- **新增回归门**（`evals/semantics/tests/test_e3.py::TestTwoZeroProbeIsInsideJplusRegion`，
  4 条断言）：探点赤纬必须落在片段登记的 Dec −79..−45 之内（**这正是本轮修的那条**，
  读的是片段自己的区间而非内联常数，片段改口径它会跟着红）；题面坐标与 fixture 一致；
  `must_not_state` 禁掉了覆盖借口；区内那份与区外那份的 `rows_full.csv`
  **必须逐字节相同**（"回包同形、结论不同"这个判别点就架在它上面）。
  `E3` 单测 67 → **71 passed**。
- **连带订正**：`references/site-endpoints-and-interactions.md` §10.3 的
  `jplus_dr3` 代表坐标同样记着 (120.3, −20.4)（知识面 `best_catalogs.md` 已订正、
  这一份漏了）——留着它，被测模型读这份参考仍会得出"探点在区外"的结论。
  一并改为 (10.0, −60.0) 并写明区外那份作废。

## E3 补题：覆盖「两张恒 0 的表必须分开报告」（2026-10-05 续十三）

上一轮的知识面覆盖核查（如实报缺口，不是遗漏）指出
`static/fragments/data_source/best_catalogs.md` 的「两张恒 0 的表必须分开报告」
一节**无任何题目指到**：它有实质判别力（`landolt` 的 0 属统计可解释的稀疏、
`jplus_dr3` 的 0 疑似站点侧覆盖异常，**两者在回包形态上无法区分**），
但测它必须新增题目，而新增题目会动题数与 7 轴分布。本轮把该题补上。

- **新增 `E3-F06`**（F 轴，tier=fixture）：题面给两次**回包形态完全一致**的
  300″ 锥搜（`getcount {"total":0}` + 分页 HTTP 200 + 只有表头的 CSV + 0 数据行），
  问"能不能写成「两张表都没数据」"。`must_state` 要求**不对称**结论
  （`landolt` 0.5° 锥期望 0.018 行属正常稀疏；`jplus_dr3` 在其公认天区 24 处含
  5° 最大半径仍全 0、密度解释不了，**只能记"疑似待站方确认"**），
  `must_not_state` 同时禁"合并"与"断言 jplus 已坐实为坏表"两个方向。
- **新增 fixture `fx_two_zero_catalogs`**（第 11 组）：**未新抓**。回包形态逐项取自
  **已入库**快照 `live_landolt_ra10.68_dec41.27_r300.0as` 与
  `live_jplus_dr3_ra120.3_dec-20.4_r300.0as` 的 `capture_log.json` / `snapshot.yaml`；
  覆盖统计（45 处 / 45712 行 / 0.018 行 / 24 处 / 5° / 385 deg²）取自
  `ops/live_fetch.py::COVERAGE_NOTES` 记的同批 live 实跑。故**无新快照落盘**、
  **无树清单结构变更**。
  ⚠️ 旧探测件 `temp/LIVE-COVERAGE-results.json` 里那批 `page1_head` 是
  `{"error":"Not Found"}`，该说法**已在 CHANGELOG 撤回**（与入库快照矛盾）——
  本 fixture 只采信入库快照，note 里写明了这一取舍。
- **新增反证夹具 B-4**（`evals/semantics/broken/__init__.py`）：把两张恒 0 表合并
  成"都没数据"、断言"这个天区没有任何源"、并编一个锥内源数（60 颗）。
  `must_flag = [unsupported_claims, unsourced_numbers]`，metascore 仍 **1.00（4/4）**。
  连带把 `report.py` 里写死的"3 份反证夹具"改成**从 summary 现取** ——
  自己写死的报告数正是 `test_report_claims` 守的那族缺陷。
- **区分度实证**（`evals/semantics/tests/test_e3.py::TestTwoZeroCatalogsItemDiscriminates`）：
  正反成对——坏回答（合并）必须命中无支撑主张 + 无来源数值；好回答（分开报告）
  必须**零命中**且引用数值全部可溯源（否则这题只会虚高 UNGR）。
  另有一条断言把题面的**不对称**钉死（两侧结论 + 关键数字缺一即红），
  防的是"只写'必须分开'、不写各自结论"的废题形态。
- **题集变更的连带面**（36 → 37 题、F 轴 5 → 6、fixture 10 → 11、tier 32 → 33、
  反证夹具 3 → 4）逐项同步：`evals/semantics/tests/test_e3.py` 三处写死数字 +
  `"0/36"` 断言、`evals/semantics/{README.md,REPORT.md,rubric.yaml}`、
  `docs/eval-E3-semantics.md`（§2 覆盖表、§4 轴表、§5 fixture 表、§9 反证表、
  §10 门槛、目录清单）、`docs/EVAL-UNLOCK-CHECKLIST.md`。
  `REPORT.md` 是**重跑生成**的（`python -m evals.semantics.runner --md-out`），不是手改数字。
  `items.yaml` / `items_real.yaml` / `fixtures_real.yaml` 三份同内容同步（门禁 `ITEM_FILES`
  扫前两份，漏一份即给"改一份留一份"留后门）。
- **知识面门禁**：`E3-F06` 的 `evidence` 指到片段小节标题
  （`best_catalogs.md::"两张恒 0 的表必须分开报告"`），故它是**已覆盖**题，
  无需进 `UNCOVERED_BY_DESIGN`；带知识面锚点的题数 34 → 35，仍高于下界 30。
  （行号段在本轮收尾时被并发改动推到了 117-128，已同步；
  锚点的**权威是标题**不是行号 —— 标题被改名门禁才会判红。）
- **已知局限（如实登记，不掩盖）**：
  ① L0 预筛只标记不裁定，B-4 抓的是"合并"的**下游后果**（断言无源 / 编造数字），
  "必须分开报告"这条断言本身由 L2 依 `must_state` 判定，机器判不了；
  ② 正确表述里若出现"软 **404**"字样，数字抽取会把它当数值判成无来源
  （`404` 是软错误的**名字**不是测量值）—— L0 是上界，报告已披露，本轮**未**为它
  往 fixture 里塞数；
  ③ 片段里有**两个既有算式对不齐**（**本轮未改，只登记**）：
  「1 行 / 3.7 deg² ⇒ 0.5° 锥期望 0.018 行」（按其自身密度口径应为 0.21 行量级）、
  以及「最大半径 5°（≈385 deg²）」（5° 半径锥的立体角换算是 ≈78.5 deg²）。
  题目只把它们当作"属统计正常稀疏 / 大面积仍 0"的**定性**依据，不要求复算。
  牵动 `best_catalogs.md` / `references/site-endpoints-and-interactions.md` /
  `best-database-guide.md` / `docs/EVAL-LIVE-FETCH-WAIVER.md` /
  `ops/live_fetch.py::COVERAGE_NOTES` 五处同源副本，**建议下一轮单独立项**核。

## 循环 1：检测代码与注释质量 → 按清单修 → 规范 reference（2026-10-05 续十五）

> 本轮是**可重复的质量循环**的第一次：8 路只读检测产清单 → 按清单修 → 本地 git →
> 规范 reference。检测的立足点很特别 —— **八道门禁当时全绿、1746 测试全绿**，
> 所以目标不是"门禁能抓什么"，而是**门禁抓不到什么**。

### 检测为什么有价值：`comment_audit` 查格式，不查语义

它管模块头有没有、中文不中文、行尾注释比例、路径存不存在。
**它不管一条注释说的是不是真的。** 结果 8 路检测挖出 **14 条 P0**，而门禁一片绿。

| 检测域 | P0 | 代表性发现 |
|---|---|---|
| 注释解释力 | 3（全在 `src/tap/jobs.py`） | 读函数上写"写终态"；声称"落库"的执行计划**从未落库**；位置错位 + 引用不存在的时间窗配额 |
| 陈旧锚点 | 5 | 错误码锚点指向**相反的码**；被引符号**已从 `client.py` 移走**；**跨仓文档把已修好的缺陷仍写成未修根因** |
| 重复真源 | 3 | 哨兵豁免列**三处真源**，E5 与生产各持一份硬编码；阈值读取器 3 份，E5 的 2 份**跳过 SSOT 三键校验** |
| 测试可信度 | 2 | 恒绿测试；**子串判据可假绿**（是上一轮刚建的测试）；11 个用例从未进收集集 |
| 结构质量 | 1 | `_member_counts` 宽捕获；另 11 条委派缝零签名守门 |
| 注释语义 | 0 | 诚实计数：**47 条断言逐条核实、14 条不符、33 条为真**、未发现 P0 |

### 11 个从未执行的用例找回来了

`test/integration/test_query_chain.py` 整份文件被一个
`except Exception -> pytest.skip(allow_module_level=True)` 守卫静默吞掉 ——
11 个用例不在收集集里，门禁却全绿，其中 P1-7 的回归锚点一度无人看守。

修法是**改导入源**（`src.client` → `src.protocol`），**不是**在 `client.py`
再导出一份：那两个码的真源在 `protocol.py`，再导出等于制造第二份真源，
与本轮正在收敛的"哨兵/错误码单点"方向相反。
**收集面 1775 → 1807，该文件 11 passed。**

### 门禁自己也有假阳性，修的是门禁不是测试

`comment_audit` 按原始物理行扫，**分不清"这行是 import 语句"和"这行只是三引号字符串里
的一段文字"** —— 而本仓的判据级测试**必然**要把待检形态当样本抄进字符串（阳性对照）。
于是门禁去要求给字符串里的英文 import 配中文说明。
新增 `string_literal_lines()` 只排除字符串内部的行，**不放宽任何真实 import 的判据**
（自证：裸 import 无中文注仍报 2 条、字符串内不给新层仍报 2 条证明这层在起作用）。

### 一条"注释说谎"的 P0，按它改代码反而会制造 bug

`src/tap/jobs.py` 一个**读函数**上写着"写终态"。按注释实现它**会引入 bug**：
终态已由 `_transition` 写过，再写一次是双写，**会把已中止的作业复活成 COMPLETED** ——
而这正是 `_transition` docstring 存在的意义所要防的。
**注释说谎，但按它改代码更糟** —— 这类项只能改注释。三条 P0 全判"改注释"，
理由分别是"实现了就双写"、"表里根本没有这一列且协议不要求"、"加了会削弱配额"。

唯一的例外是 `nadc_oauth.py`：`HTTPServer(...)` 写在 `try` 外，端口被占抛
`PermissionError`，而 CLI 唯一的 `except NadcOAuthError`（其注释恰好点名这个 case）
接不住。**那是本该存在的行为，所以改代码而不是文档**，并实际占端口验证。

### reference 面的剔除与完善

- **剔除被实跑推翻的旧结论**：`grater`（实跑 `greaterequal` 1559 行 vs `grater` 0 行 +
  426 B 仅表头 CSV）从"站点行为"降级为**当前未取证**（不是"已确认不存在" ——
  两者的证据强度不同）；`ps1_source_id`「线上逐行为空」改为**位置相关**（(180,30)=0/300
  vs (286.1,15.7)=128/300），正确表述是"用这一列当主键前**必须先判记录类型**"；
  `data-formats.md` 补第四种无值编码 `-32768`（**代码无需改** —— 阈值规则本就是
  `value <= threshold`，`-32768 < -999` 已被覆盖，只补登记）。
- **`static/core/` 两条 P0**：`not_configured` 被当运行期真实状态（实为**仓内零产出方**）；
  `best_result` 的形状是**第三种、从不存在过的形态**。`static/` 是**智能体实际加载**的面，
  错了模型会照着做，故与 `references/` 同级看待。
- **SSOT 数字回写**：快照规模、CSV 份数、`checksum_match` 旧口径（已由 `"unknown"` 改真布尔）、
  `dr3xpcorr` 列序不同但解析按列名故无害。
- **`tools.schema.json` 的 `http_requests`**：schema 说"真实 wire 请求数"，实测
  **3 次 wire 只报 1**（计数器挂在 `Session.request` 层，看不见适配器层重试）。

### 验证

`pytest test/ evals/ -q` → **1778 passed, 29 skipped, 0 failed**（1746 → 1778）·
收集面 **1775 → 1807** · `ruff` 全仓绿 · 八道硬门禁全 exit 0（树清单 1123 entries）·
`eval_runner` 1.0000 SUCCESS · 未入库文件 0

---

## 跨进程续传曾静默抹掉进度与结果（2026-10-05 续十四）

> **补记**：这处 fail-open 修复的实现落在 `02ba642`（一次 15 文件的批量提交）里，
> 而那条提交信息只写了"文件预算还清 + 实跑事实沉淀 + 门禁假绿二次清除"，
> **完全没提它**。`git log -S resume_spec` 找不到它。补这一节，
> 是为了让"改了什么"和"为什么改"不依赖对提交信息的记忆。

### 现象
`BestDownloadManager.resume()` 的**跨进程分支**构造 `ProgressTracker(self.store, job_id)`
时，会把磁盘记录上的 `done_pages` 和 `result` 抹掉。后果：**作业永久不可续**。

### 根因不是 `save()`，是"另起一条全零记录"
初判是"`ProgressTracker.__init__` 里的 `store.save()` 抹数据"。
**实测否掉了这个判据**：

- 该 `save()` 服务的是 **standalone 契约** —— 不经 Manager 直接 new tracker 时，
  起跑前进度文件就该可见；且 `_spawn` 之后还会**再显式 save 一次**。
  所以**没有删它**。
- **而且删了也堵不住** —— 紧接的 `start()` 的 force flush 会照样写下那条
  `done_pages=0` / `result=None` 的全零快照。

真因是续传路径**另起了一条全零记录**，而不是"在既有记录上覆盖"。

### 三进程实跑证据（打桩 `session.get`，走真实分页/断点/续传参数复原，零真实网络）

| | 修复前 | 修复后 |
|---|---|---|
| 进程 1 盘上 | failed, `done_pages=1`, 有 spec | 同 |
| 进程 2（续传再失败） | failed, `done_pages=0`, **`result=None`** | failed, `done_pages=1`, 有 spec |
| 进程 3 再试 | **`FileNotFoundError: no resumable record`** → 永久不可续 | **done, `done_pages=4`** |

### 修法
加末位关键字 `adopt`（从旧快照播种进度与 result，续传时构造期不落盘）；
`status` / `error` / `hook` **一律留新** —— 继承下来会让 running 记录挂着旧报错。

**顺带修掉同一处重建的第二个数据损坏**：原调用漏传 `kind=kind`，
使 **sqlid 作业被落盘成 `region`**。

补 6 条测试（一条都没删）。承重验证：`git stash` 掉修复后重跑 →
**5 failed, 1 passed**，唯一通过的那条正是"默认路径契约不变"守卫。

### 另修：模块头路径引用回归
`src/crossmatch_jobs.py` 的模块头写 `src/models.py`（不存在）。核实：
`git log --all -- src/models.py` 与 `git ls-files` **都为空** → 该路径在本仓
git 历史里**从未存在过**。且 `CHANGELOG.md:1162` 记着 Q9 早前那轮已批量修过
`src/models.py` → `src/models/` —— **是 `f1cb082` 新建该文件时没跟上，属回归**。

---

## 实跑扩面：12 张表全验 + 文件预算还清 + 门禁假绿二次清除（2026-10-05 续十三）

> 本轮把实跑证据从 `ps1` **1 张表扩到 12 张**（85 次真实请求，全 200，零重试），
> 并还清了 `client.py` / `crossmatch.py` 的行数预算欠账。

### 4 条只有实跑才能拿到的结论

1. **排序键只有 `ps1` 是空列** —— 填上了 H3 临收尾留的问号（当时只能写
   "可能是空列"）。其余 9 张有数据的表排序键非空，且 asc/desc 双向探针
   证明服务端真的认这个排序。含义：「注入确定性排序列以防偏移翻页丢行」
   **对 9 张表成立，对 `ps1` 是空操作**（该列 174/174 为空）。
2. **`uss_dr1` 的 `order=desc` 返回完全不同的行集** —— 与 asc **零重叠**，
   desc 前 200 行**全部 `ra_u = nan`**（服务端把 NULL 排在 asc 末尾、desc 开头）。
   默认 asc 安全；**显式 desc 是个陷阱**，已写进知识面。
3. **第四种哨兵编码 `-32768`**（uss_dr1 的 `*_flag`，定点非带）。
   ⚠ **但代码不需要改** —— `evals/_data/null_sentinel.yaml` 的规则本就是
   `value <= threshold`（不是 `==` 某个值），`-32768 < -999` 已被现有阈值覆盖。
   只登记形态、判定逻辑一行未动（把"登记一个事实"变成"发明一条规则"是倒退）。
4. **`inputobjs_*` 不是 proximity 专属**（锥搜也返回），但**不是登记缺口** ——
   代码在 `downloader` / `models` / `crossmatch` 三处都刻意处理并写了理由。
   **补登记反而是错的**：那会把查询元数据当星表数据列，并重新引入
   `models/__init__.py` 注释里记载的 **i 波段污染**（`inputobjs_` 以 "i" 开头，
   旧的波段首字母匹配会把角距吞成 i 波段星等）。缺口只在文档。

### 一道"惩罚正确答案"的题已修

`E3-F06` 测「landolt 的 0 是统计可解释稀疏 / jplus 的 0 可疑」，但它的 fixture
探的 jplus 坐标 **(120.3, −20.4) 是 `uss_dr1` 的天区**，在 jplus 自己的
Dec −79…−45 之外 → **一个读了知识面的模型会正确指出"这个 0 用天区覆盖就能解释"，
而这个更正确的答案会被判错。** 已把探点移进 jplus 自身天区并补正式快照。

同题另抓到一个**编造值**：fixture 记 landolt 表头 57 列，归档 CSV 真实是 **53**。
这正是本仓付过代价的 `class_star=0.02` 同款失效模式。已改 4 处并加**溯源守护测试**
（重新注入 57 → 红，53 → 绿）——"逐字段溯源"从一句承诺变成每次跑批的断言。

### 文件预算还清（用户裁决项 1）

| 文件 | 起始 | 现在 |
|---|---|---|
| `src/client.py` | 557 | **380**（抽出 `client_resolve` / `client_phase1`） |
| `src/crossmatch.py` | 400/400 零余量 | **285**（抽出 `crossmatch_jobs`） |

纯结构重构，每步用 **AST 归一化比对**证明"只有位置变了、逻辑逐字未变"。

### 验证

`pytest test/ evals/ -q` → **1746 passed, 30 skipped, 0 failed** ·
`ruff` 全仓绿 · 八道硬门禁全 exit 0（树清单 1117 entries）·
`eval_runner` 1.0000 SUCCESS · 未入库文件 0

### 本轮遗留（下一轮）

1. **`landolt` / `jplus_dr3` 排序键仍未取证** —— 两表零数据行，闭不了。
   需要站点侧的标准星坐标（仓内无法自举）。
2. **本轮未观测到 429** —— 按纪律不得加压制造，故"429 处理正确"**未验证**。
   此前所有 429 证据都是注入的假响应。
3. **E5 指标值守护只覆盖 B3**（6.2s vs 全量 46s），其余 10 个组装仍需
   `make eval-e5` 后人工对账。
4. **父仓接线待其 owner** —— `_shared/skill-registry.yaml`（`mcp_service: null`）
   与 `.mcp.json` 不在本仓 git root 内，仓内只做到了"登记一致性可守护"，
   并加了**反向断言**：将来父仓真接线时门禁会红。
5. **`canonical.py:176` / `gold/gold_algorithms.py:119` / `tests/test_e2.py:202`
   三处「2 个不同值」应为 1** —— 实测 `gaia_dr3_18_solution_id` 1000 行只有
   1 个不同值。证据在 `temp/` 报告里，未改（归属 E2 线）。

### 一条给下轮的提醒

**「141 vs 137」这类数量差异，第一反应不该是"补登记让数量对上"，
而该是"问清楚多出来的那部分是什么"。**

本仓已经为同类直觉付过代价：`ps1_source_id` 被当"空列"要替换掉（实为位置相关）、
`grater` 被当"站点方言"保留（实跑证明根本不存在）。
每次看到数量对不上，先查清那部分是什么。

## 三条已裁决但**本轮刻意不做**的工单（2026-10-05 续十二）

> 下面三条是 2026-10-05 收口时**用户明确裁决"下一轮再做"**的，不是遗漏。
> 记在这里是为了让下一轮开局就能看到，不必重新考古。

### 1. 文件预算：`crossmatch.py` 400/400、`client.py` 557（下一轮抽函数压回）
- `src/crossmatch.py` 净行已 **400，上限 400，零余量** —— 下次改动**必须先抽函数**。
- `src/client.py` 541 → **557**（本轮 H6 修 phase-1 异常传递所增），预算文档
  `docs/architecture/file-size-budget.md` 写的触发条件「phase-1 执行组已修改」**事实上已成立**。
- 两者都仍在放宽簿**登记豁免**内，所以 `count_code_lines` 门禁当前是绿的
  —— **绿不等于合规**，是"已登记的例外"。
- 压回方向（未实施）：`protocol.py` 的 CSV 解析（`parse_csv_rows` + `_sniff_delimiter`，
  约 120 行）抽到 `src/protocol_csv.py` 并在协议层 re-export；`crossmatch.py` 归因逻辑抽离。

### 2. `.env.example` 漏 `ASTRO_BEST_PASSWORD` —— 用户照它配不出可用登录
- `.env.example:3` 自称是 env 的 SSOT，却**没有** `ASTRO_BEST_PASSWORD`。
- 那是**唯一的非交互式凭据注入点**（H9 实测：设了它 `password_configured` 才变 true，
  且密钥值从不出现在任何输出里）。**照现有 `.env.example` 配置的用户配不出一个能用的登录。**
- 同一轮扫出的 4 处仍宣称废弃 `BEST_API_TOKEN` 通道的地方：
  `references/fallback-protocols.md:24`、`evals/nl2tool/tasks.yaml:744`、
  `evals/nl2tool/tasks.yaml:734`（原文写 `evals/nl2tool/NL2T-26.json:5` —— 该 JSON 文件**从未存在**，`NL2T-26` 是 `tasks.yaml` 内的任务 id；R2 2026-10-05 订正）、`evals/ablation/items.yaml:867,875`。
- H9 **刻意没把它们纳入守护面**（理由：把未修文件纳入守护 = 用假覆盖率换一个真红），
  已登记在 `test/unit/meta/test_dead_channel_claims.py` 的 docstring 里。

### 3. `H8-02` 的门禁判据测试落在 `temp/`（gitignored，克隆机跑不到）
- `ops/audit/verify_crossrefs.py` 对错误码契约的覆盖面已从 **0 修到 10 条**
  （原来只扫 dict 的**值**、`BEST_NNNN` 是**键**，所以一条都收不到）。
- 但守它的判据级用例写在 `temp/`，**不随仓库分发**。
- 仓内 `test/unit/meta/test_gate_criterion_red.py` 对 `verify_crossrefs` 只有接线级断言。
- 下一轮补 `TestCrossrefsErrorCodeContractIsNotVacuous`。

### 附：本轮已完成的收口状态（父 Agent 独立复核，非引用子代理报告）
```
pytest test/ evals/ -q     → 1697 passed, 29 skipped, 0 failed
ruff check 全仓              → All checks passed!
八道硬门禁                   → 全部 exit 0（树清单 1102 entries 一致）
eval_runner                 → 1.0000 SUCCESS
doctor                      → exit 0
未入库文件                   → 空（铁律 8 满足）
code_fingerprint check      → exit 1 =「有未提交真代码改动」，提交后归零
```

## 知识面沉淀：8 路审计的实跑结论入库（2026-10-04 续十一）

本节只记**今天实跑得到的结论**与其落点，不复述审计过程。口径变更先行，因为它
决定了下面两条为什么值得单独沉淀。

**一、口径变更：取消逐次联网授权，改为默认实跑。** 原「只做静态分析、结论留待
实跑」已被用户判为不可接受（理由：本轮 6 条 P1 全是纸面看不出、实跑一验即穿的
问题），逐次授权规则删除。**但实跑与评测确定性是两件事**：评测仍全部跑回放
（SnapshotTransport 家族，rate_limit 归零），变的只是**素材从哪来** ——
`ops/live_fetch.py` 是素材重建入口，默认 dry-run 的设计保留（不带 `--execute`
一个请求都不发），但跑它不再需要额外授权。对站点的四条礼仪不变：POST 建会话
不重试、串行 + 强制间隔、产物只落 `temp/`、抓到数据 ≠ 金标准通过人工复核。
**禁止连真实模型/真实付费 API** 这一条不在本次改判范围内。

**二、分页语义钉死：偏移翻页（推翻"未验证"状态）。** `page=N & rows=M` 是**绝对
偏移**。实跑（ps1 锥搜 180/30 r=300as，sqlid=s4943）：`page=2&rows=100` 的 100 行
与 `page=1&rows=1000` 的 `[100:200]` **逐行完全相同**（`offset_semantics=true`），
同参数二次取回完全一致。判据取「逐行相同」而非「零重叠」——`page1 ∩ page2` 交集
实测为 1 行，无 `ORDER BY` 时行序本就不稳定。

这条的价值在于**关掉一个悬置的未证前提**：`temp/AUDIT-A3-download.md` 的 A3-01
（断点续传静默丢行）此前把严重度挂在"偏移 vs 会话内游标"上，并预留了「若为游标
则丢行降级为错序」的分支。实跑把 A3-01 从"可能只错序"钉成"**真丢行且无重复**"。
**认知根源**也在这：`references/site-endpoints-and-interactions.md` 原先只讲了
`build_page_url` 怎么拼参数，没讲「改 `rows` 会让同一个 `page` 指向另一个数据集」
这个语义后果 —— A3-01 因此能长期存在而不被察觉。
证据：`temp/LIVE-PAGING-results.json`（脚本 `temp/LIVE-PAGING.py`）。

**三、`jplus_dr3` / `landolt` 的旧叙事改准。** 旧说法「jplus_dr3 是坏表」不够准确，
今天的对照实跑把它拆成两半：

- **路由是活的**：`/jplus_dr3/f` 回 **HTTP 200 + 34672 B 真实表单**，
  `/landolt/f` 回 **200 + 120062 B**，csrf 与 showcol 俱在。**不能说"表没了"。**
- **数据侧确实恒 0**：`getcount` 对两表（多天区）稳定回 `{"total":0}`；权威客户端
  `cone_search` 侧 `success=True / total=0 / pages_fetched=1`。
- **两者必须分开报告**：landolt 的 0 是**统计可解释的稀疏**（45712 行摊全天约
  1 行 / 3.7 deg²，0.5° 锥期望命中 0.018 行）；jplus_dr3 是在**其公认天区**仍
  大面积为 0，密度解释不了，**仍属可疑、待站方确认**。
证据：`temp/LIVE-COVERAGE-client-results.json`、`temp/LIVE-COVERAGE-results.json`、
`temp/LIVE-PROBE-results.json`。

**四、探针陷阱（写进 pitfalls 的 E-6），且订正了最初误判的成因。** 裸 `requests`
探针取页**一律**回 22 B `{"error":"Not Found"}` —— 连 `total=215774` 的 ps1 也一样，
很容易被读成"站点坏了/表没了"。**最初把它归因为"漏 `csrfmiddlewaretoken`"，这个
判断是错的**，经三轮实跑逐项排除后定位到真因：**探针用 `re.search(r"sqlid/s?(\d+)")`
取号时 `s?` 落在捕获组外，吃掉了前缀**。决定性对照（同一 `s4958`、同一页）：
`/sqlid/s4958?…` → **24997 B 真实 CSV**，`/sqlid/4958?…` → 22 B 软 404；
`getcount` 恰好相反（裸数字 → 15 B `{"total":5109}`，带 `s` → 22 B）。
**被实测排除的四个候选**：cookie、`X-CSRFToken`、`User-Agent`、`Accept` ——
同一会话四种组合一律 22 B，`BestClient` 同条件立刻拿到 24997 B。
客户端免疫是因为 `src/protocol.py::parse_sqlid` 保留前缀交给 `build_page_url`，
只有 `count_sqlid` 才 `removeprefix("s")`。
证据：`temp/LIVE-SESSION-BINDING-results.json`、`temp/LIVE-HEADER-BINDING-results.json`、
`temp/LIVE-MATRIX-results.json`、`temp/LIVE-SQLID-PREFIX-results.json`。
**留档的教训**：「22 字节软 404 = 站点坏」这个推断链条上，第一步就错了；
真正起作用的判据是**换同会话的另一个端点验活**（`getcount` 通 → 地址错）。

**本节的落点（只改知识面，未动任何生产代码）**：

| 文件 | 落了什么 |
|---|---|
| `docs/architecture/pitfalls.md` | 新增 E-5（偏移翻页）、E-6（sqlid 前缀假软 404），并登记进 §0 索引 |
| `references/site-endpoints-and-interactions.md` | §4 补第 5 条「分页是绝对偏移」；§1 路由表标注 `s` 前缀要求；§6bis 补两行实测（分页语义 / 前缀两套形态）；新增 §10.8（jplus/landolt 两路对照）；§10.3 的 jplus 行加指向 §10.8 |
| `static/fragments/data_source/best_catalogs.md` | 补「表单页 200 ≠ 有数据」+ 四类覆盖分档（确认有覆盖 / 极稀疏 / 统计可解释稀疏 / 可疑恒 0）+ 代表坐标 |
| `static/fragments/data_source/nadc_endpoints.md` | 补分页偏移语义、sqlid 前缀两套形态、22 B 软 404 探针陷阱（含一分钟判据） |
| `CHANGELOG.md` | 本节 |

**未改动**：`src/**`、`evals/**`、`examples/**`、`test/**`、`CLAUDE.md`、
`docs/EVAL-LIVE-FETCH-WAIVER.md`、`references/ALGORITHM-SPEC.md` /
`client-api-reference.md` / `download-playbook.md`（F5 在改）。
**仍未闭环**：A3-01 的代码侧修复（断点补存 `page_size`/`max_rows`）不在本节范围，
归下载线；本节只把它的**严重度前提**钉死。

## 撑销 reference 里一处「换夹具前」写下的过期陈述（2026-10-04 续十）

`references/data-formats.md` §5b 写着「E6 的三份**尚未换**，读到那些夹具里的
`ps1_snr` 时要记得：那是构造样本的产物」—— 这是在 E6 换夹具**之前**写的，
换完没回头更新，于是 reference 说了假话。实测三份夹具的表头**均无 `snr`**，
`ps1_2pages` 也已不存在（改名为 `ps1_singlepage`）。

- §5b 改写为一张现状表：五份素材逐份列出「现状 + 换法 + 依据」，并写明
  `syn_missing` 是**有意保留合成**（站点不产生「列不存在」的回包）。
- 补一句自查：「若读到 `ps1_snr` 说明拿到的是旧副本」。
- **这次错误的教训值得单独记**：§5b 自己的教训是「照着合成夹具的列名写代码，会写出
  一个站点不发布的列」—— 而它自己踩了反过来的坑：**照着「夹具里有什么列」去描述
  夹具现状**，夹具换了、描述没换。写现状的文档必须与被描述的对象同批更新。

### `code_fingerprint check` exit 1 的准确定位（补 CLAUDE.md）

这条门以 **HEAD 为基线**，工作区任何**真代码**改动（纯注释/docstring 不算）都会让它
exit 1，含义是「有尚未提交的真代码改动，请确认」，**不是**「代码有问题」。
本轮题集切换带来的 `test_e3.py` `assert len(fixtures) == 7` → `== 10` 是正当逻辑改动，
提交前必然触发它，提交后归零。

**明确写下「绝不要为了让这条门绿而改判定逻辑或回退正当改动」** —— 那才是真把门禁
变成摆设。同时记下它**看不见「未跟踪」**：磁盘上存在且未被 `.gitignore` 忽略的新文件
必须 `git add`（铁律 8），那是 `TestGitTrackingCoverage` 的职责，两条门各管一头。

## E3 题集切换：items.yaml → 真实回包（2026-10-04 续九，铁律 4 已批准）

- `evals/semantics/items.yaml` 覆盖为 `items_real.yaml` 的内容：**36 题全部重推**、
  **fixture 由 7 组增至 10 组**（全部逐字段溯源到 `snapshots/live-2026-10-04/`）。
- 36 题的改动分三类：13 条**前提重建**（题目语义变了，旧编造值在真实数据里不成立）、
  12 条只换锚点/断言含数值、11 条不动。逐题对照见 `temp/E3-SWITCH-REVIEW.md`。
- **新增的三组是换真实回包才发现合成数据取不到的形态**：
  `fx_ps1_flags`（flags 确实不一致：yflags=114720 vs g/r/i/z 各不同）、
  `fx_xcatalog_ps1`（跨表同源锚点）、
  `fx_uss_classstar_low`（`u_class_star=0.0764` 真有接近 0 的值 —— ps1 在密集天区
  该列**整列为空**，合成数据里那个 0.02 是编的）。
- **`test_fixtures_present` 的 `== 7` 改 `== 10`**，并写明为何是 10 组。
- **`test_e3.py` 内联 `_FIXTURES` 的注释订正**：原文写「与 items.yaml fx_ps1_pair
  逐字一致」，切换后这句话不再成立（题集已是 `rpsf=19.090110214761232`）。改为
  说明**刻意保留合成值**的理由：预筛必须对**两种形态都成立**，真实浮点的溯源由
  另外两条内联真实值的反证覆盖（`test_traceable_against_17digit_real_float` /
  `test_still_catches_genuinely_fabricated_number`），两组构成对照。
- `docs/eval-E3-semantics.md` §5 的 fixture 表整表重写（旧表记的全是合成值：
  `class_star=0.02` / `rnobs=12` / `ruwe=1.42` / `flux=3.912e-15`，
  **站点从不返回这些值**），并在树注释处把「7 组 fixture」更正为 10 组。
  表里的 11 个引用值已逐个对 `items.yaml` 实际值核实过。
- **一处陷阱因换真实数据而更隐蔽**（已写进文档）：`phot_g_mean_mag_y21=17.45913697260331`
  与 `phot_g_mean_mag=17.460993` 极其接近，**正因为接近才更容易被当成"同一个量的两个
  版本"而不加分辨** —— 这是「敢不敢说不知道」那题的加强版。
- 验证：`pytest evals/semantics/` **59 passed**；`runner.py` **exit 0**
  （36 题 / `metascore=1.0` / `n_live=4`）。

## `scr_galah_3rows` → `scr_galah_0rows`（2026-10-04 续八）

- **夹具名与内容不符，按 `ps1_2pages → ps1_singlepage` 同款口径改名**。该夹具实为
  真实 **0 行**回包（保留 141 列表头，如实呈现「有列定义但无数据行」这条形态），
  名字里的 "3rows" 是旧合成数据的遗产。
- **为什么不能只靠 README 声明**：`docs/eval-E2-groundtruth.md` §4.6.4 刚判过
  「目录名声称真实、内容是造数」为**命名误导**并要求消解 —— 同一个仓里若一边
  按「名字必须与内容相符」处理 `ps1_2pages`，另一边留着 `scr_galah_3rows` 只在
  README 里写一句"不符"，就是**两套口径自相矛盾**，读者先看目录名仍会被误导。
  一条铁律只该有一种落法。
- 连带改动：`r0_lane.py` 的 `REPRO-11` 与 `run_e6.py` 的 canary 探针指向、
  `docs/eval-E6-reproducibility.md` 的树注释、`fixtures/README.md` 的三处
  （夹具表 / 幽灵列段 / 「真的就是 0 行」段），以及 `python ops/verify_tree_integrity.py --write`
  重生成 README 树块（1074 entries 不变）。
- 验证：`pytest evals/repro/` **190 passed**；`run_e6.py --lane R0 --repeat 3 --selftest`
  **exit 0**（改名后夹具仍可回放，一致率未退化）。

## E5 锚点复核 + 反证夹具与正式题集的「同名不同底座」登记（2026-10-04 续七）

- **逐条核对 `items.yaml` 的 30 题锚点**（按 `tests/test_e5.py` 的真实基目录
  `evals/groundtruth/snapshots/` 解析，**不是仓根** —— 首次核对时我按仓根解析，
  30 条全报 MISS，那是检查本身的错，不是数据缺件）：D 类 12 条里 **11 条指向
  `live-2026-10-04/` 实抓回包**、1 条 `syn_missing`（有据保留），锚点缺失 0 条、
  gold 文件缺失 0 条。C 类 6 条 `kind=none`（不适用取数门）、R 类 6 条同、
  S 类 6 条挂 E3 的 `fx_*` fixture —— 均为设计内形态。
- **发现一处极易误判的「同名不同底座」并钉死**：`evals/ablation/broken/__init__.py`
  里 `_ITEM_D04` / `_ITEM_D11` / `_ITEM_D06` 的 `data_anchor` **仍挂合成快照**
  （`ps1_ra180.0_dec30.0_r60as` / `syn_missing` / `syn_huge`，主键是
  `BEST_SIM_*` / `BEST_SYN_*`），而正式题集里同名 id 的 `E5-D02/D03/D11/D05`
  已全部改指实抓回包。**两者不冲突** —— 反证自证不读 `items.yaml`，反证夹具的
  职责是「判定器抓不抓得住坏答案」而非复现真实数据，合成底子反而让期望值一眼可辨。
  但同名极易让人以为该一致，故加 `test_broken_fixture_bases_stay_synthetic_on_purpose`
  钉死：反证夹具的快照锚点**无一条**指向 `live-2026-10-04`，且这些合成目录必须在
  盘上存在；有人「顺手改成真实快照」会立刻红，先想清楚反证夹具到底测什么。
- 附带记一笔：`ps1_ra180.0_dec30.0_r60as` 这个目录名**曾经**是「命名声称真实、
  内容是 `BEST_SIM_*` 造数」的反面教材（E2 文档 §4.6.4 点名过）；正式题集侧已由
  `live_ps1_ra180.0_dec30.0_r60.0as`（174 行实抓）取代，反证夹具侧保留合成副本。
- **一处需要注意的余量**：`evals/ablation/tests/test_e5.py` 净 369 行，距铁律 2 的
  400 行上限只剩 31 行。再往这个文件加用例会撞线，届时应先拆分而不是硬塞。

## 撑销一批已被推翻的过期结论（2026-10-04 续六）

**背景**：本轮把 E2 的 16/17 场景改指真实回包后，`docs/eval-E2-groundtruth.md`
§4.6 的审计结论**没有跟着更新**，仍在宣称「11 份 `syn_*` 合成 + 3 份合成伪装成
`ps1_*` + 1 份掺人造星 + 完全真实 **0** 份」「E2 最该测的真实脏数据处理几乎没被测」。
**过期结论比没有结论更坏** —— 读者会拿一个已经不成立的判断去理解当前结果。

- **逐场景重新核对**（脚本实测 17 个场景挂的快照目录）：**16 个挂
  `live-2026-10-04/` 实抓回包，1 个保留 `syn_missing`**（有据：站点不产生
  「列不存在」的回包，不存在的列会被服务端忽略，这条形态无法真实抓出）。
- §4.6.4 素材真实性全表改写为当前实况，原表折叠保留为「审计曾发现什么」的记录。
- §4.6.5 的「E2 不能证明取数正确」改写为**两条现行边界**：仍未覆盖的是
  **尚未抓取过的**天区/星表/参数组合（不是"不是真实数据"）；另加一句
  「金标准经人工复核」这一层已按 §4.3.0 取消为披露项、不参与 `pass`。
- §4.6.6 的改造项表从「要求」改为「当前状态」：P0×2 与 P1×2 已全部消解
  （命名误导由 174 行实抓取代、`cone_5as` 人造星已去掉、`live-dirty` 用例**已远超**
  3 份 —— 哨兵、整列全空 0/174、零行、17 位 id、重复 id 形态全在跑批路径上）；
  **P2（星团/M31 密集场多值并列）如实标 ⏳ 未做**，不假装已完成。
- §4.6.4 点名的「`ps1_ra180.0_dec30.0_r60as` 命名伪装成真实」问题：目录已被
  `live_ps1_ra180.0_dec30.0_r60.0as`（174 行实抓）取代。
- **六个实验 runner 端到端实跑复核**（此前只验过单测与门禁，**单测绿 ≠ 跑批
  结果对**，尤其这轮改了 E2 的 oracle 主键口径、E3 的预筛容差、E6 的夹具）：
  E1 26 题 `pass=true`/`weighted=1.0`；E2 17/17 + `metascore=1.0` +
  `provenance_drift` 归零；E3 36 题 + `metascore=1.0`；E4 Tier W 15/15 +
  Tier P 标注 35/35 完备；E5 PASS + `metascore=1.00`；E6 R0 四路一致率
  **TSC/PAC/RDC/FCC 全 1.0**、Wilson 95% 下界 0.963、覆盖 18/32 如实披露。
  **E6 尤其值得记**：换真实夹具后 `scr_galah` 是零行、`ps1_singlepage` 是 3 行单页，
  两种差异极大的形态下一致率仍满分。

## E6 夹具换真实回包 + E2 签字闸门取消（2026-10-04 续五）

### E3：预筛容差对真实浮点不成立（切题集前抓出来的缺陷）

- **切换干跑时抓到，不是切完才发现**：`_close_to_any` 的溯源容差是固定 `1e-6`
  （相对+绝对），这对合成 fixture 成立（2 位小数 `16.812`），但真实回包是
  **17 位浮点** —— `ps1_rpsf = 19.090110214761232`，题面引到 3 位小数（`19.090`）
  时绝对差 **1.1e-4**，是 1e-6 窗口的 **6 倍**，**正确的引用会被判成"无来源编造"**。
- **影响面量化**：128 个真实值里 **54 个（42%）** 在 3 位小数下失配。这足以让
  UNGR 系统性虚高，**把 E3 用自己的预筛判死**。
- **改法不是一刀切放宽容差**，而是换判据：人引用一个数时不会写 17 位小数，必然按
  某个精度舍入过，所以「回答的数 == fixture 值按该精度的舍入结果」才是可溯源的
  真正含义。窗口改为 **按回答数值的有效小数位数取半单位**（3 位 → `5e-4`），
  与原双端容差取并集。
- **不放水的反向自证**：半单位窗差一个单位以上仍判无来源，`19.091` / `19.5` /
  `21.090` / `18.999` 四条反例守住。`19.09` **不在**反例里 —— 它与 `19.090` 是
  同一个数（浮点解析后位数信息已失），判它可溯源是对的；要求实现区分两者的字面
  写法是不可能的，浮点里没有这个信息。
- **口径同步 rubric §3**（模块头硬要求）：新增 `tolerance_by_significant_digits` /
  `digits_rule` / `counter_check`，并加一条 `test_tolerance_syncs_with_rubric` 断言，
  与既有的 `test_window_syncs_with_rubric` 同款 —— 防止代码改了 rubric 没跟。
- 两条新用例**内联最小真实值 fixture**，**不依赖 `items_real.yaml` 是否已切换**：
  铁律 4 未批准前也守得住，将来若有人把判据改回固定容差会立刻红。
- **切换干跑结论**（不落盘、未切换）：36 题 / 轴分布 A6 B5 C4 D6 E5 F5 G5 /
  10 组 fixture / 零悬空引用 / `n_live=4` / `metascore=1.0` 全部通过，
  **只差 `test_e3.py` 里一个数字**（`test_fixtures_present` 断言 7 组，真实是 10 组）。

### E6：三份合成夹具 → 逐字节真实回包

- `evals/repro/fixtures/` 下三份夹具换成真实回包（脚本从
  `snapshots/live-2026-10-04/` 裁出，不重打任何数值）：
  `ps1_5rows`（5 行，来源服务端约束查询）、`scr_galah_0rows`（**真实 0 行**，保留
  141 列表头；原名 `scr_galah_3rows` 的 "3rows" 与内容不符，同批重命名）、
  `ps1_2pages` → 重命名 `ps1_singlepage`（3 行真实单页）。
- **三份各自带了一个站点从不发布的列**，与 E4 那份 `ps1_snr` 是同一种病换了两张表：
  `ps1_snr`（真实 ps1 回包 34 列里没有，只有 `*_err` 误差列）、
  `scr_galah_teff`（真实 scr_galah 回包 141 列里没有）。合成 id
  （`BEST_FIX_0001..0007` / `SCR_FIX_0001..0003`）与整齐假值全仓清零。
- **`ps1_2pages` 描述的分页场景站点并不产生**：31 份真实快照全是 `page_size=1000`
  单页，`total == returned_count`（3 / 27 / 174 / 770 / 1000 / 5109 / 12750 /
  50095 / 305172 …），没有一份是「第 1 页 5 行 + 第 2 页 2 行 + total=7」。
  故 REPRO-08/27/28 的 `stability_class` 从 `pagination_termination` 改为
  `past_last_page_boundary`：现在考**末页边界**（翻过末页服务端返 0 行，客户端
  不得读成"还有下一页"或失败）。`stability_class` 无代码消费，改动零风险。
- **一处只登记未修的结构不对称（产品代码是对的，错在 oracle 侧）**：stripe82 的 id 列
  是 `stripe82_calibstars_id`，不匹配 `*_source_id`。实测两侧行为：
  - **SUT 侧正确** —— `src/models/__init__.py:308` 的 `from_row` 别名支路已含
    `calibstars_id`（"旧别名表漏它导致 ID 丢失"是 live 实证后修的，见本文件
    精准下载轮的 Fixed 条目），实测从真实行取到 `CALIBSTARS_0813769`。
  - **oracle 侧取不到** —— 它按 `*_source_id` 在裸 CSV 里找主键，stripe82 上匹配
    为空，于是 `row_key` 退化到坐标对。
  即两侧对"哪一列是主键"确实不对称，但**不是产品缺陷**，修法在 oracle 的主键判据
  （应与 `from_row` 同口径地认 `calibstars_id`）。已让 `boundary_maxrows` 换回 ps1
  测本来的语义，stripe82 这条留作 E2 oracle 的待办。

- **stripe82 主键不对称已修** (产品代码是对的，错在 oracle 侧)。实测：
  `stripe82_calibstars_id` 27/27 非空且唯一，而 `src/models/__init__.py:308`
  的 `from_row` 别名支路**已含** `calibstars_id`（live 实证后补的），能取到
  `CALIBSTARS_0813769`；oracle 侧 (`canonical._source_id_of` 与
  `gold_algorithms.row_key`) 只认 `*_source_id`，对这 27 行返回 `None` → 全退到
  坐标键。**两侧不同尺**会让 M1 报出看着像"数据对不上"的假失配。
  两份 oracle 实现都已补 `calibstars_id`（它们本就刻意不复用代码，须同改）。
- **名单刻意不比照 `from_row` 的全部别名**（`id` / `objid` / `obj_id` 都不收）：
  `from_row` 是**逐键精确匹配**，oracle 是**按后缀扫全列**，风险面不同。实测加了
  裸 `id` 后缀会先命中 `gaia_dr3_18_solution_id` —— 那是**解算批次 ID**
  （1000 行里只有 2 个不同值），字典序又排在 `*_source_id` 前面，取了它等于拿
  **重复 id 当主键**，两行会塌成同一主键。照抄别名是修一个星表、坑另一个。
- 两条反向自证（`TestCanonical`）：stripe82 主键被认且两份 oracle 同判；
  `*_solution_id` 不得被当主键。
- `boundary_maxrows` 此前为躲这个不对称换回 ps1 —— 现在 oracle 侧已修，该换回
  stripe82 属可选项，**本轮未换**（换表要重算该用例 gold，且它测的是
  `max_rows` 上限语义，与主键口径无关）。

### E2：签字闸门取消，改为纯披露（拆法 A）

- `--require-human-review` **从 CLI 与 `run()` 签名删除**，签字一族（署名档 / 台账 /
  签字单联）全部**降级为披露，不再阻断**。
- **为什么它是摆设而非闸门**：仓内 17 份金标准全部由 `gen_gold.py` 自签
  （`review_provenance = {human: 0, self_signed: 17, unsigned: 0}`，
  `sidecar_signed = 0`），**历史上从未有任何一个 case 通过这道闸门** ——
  启用后 17 条全判 `gold_not_human_signed`，整批恒 FAIL，产出的是"没通过"而非证据。
- **披露一个都没删**，且新增逐 case 粒度：`review_provenance`（三态计数）/
  `sidecar_signed` / `human_review_complete`（恒 false）/
  **`review_disclosure`**（新：`case_id → {signer, ledger}`，点名
  `gold_not_human_signed` + `ledger_missing` 等）/ `provenance_drift`。
  `human_review_required` 保留为恒 `False`，让旧消费者读到确定值而非 `KeyError`。
- **边界不得越界读**：`pass` 的五条判据（case 全过 / 无缺件 / metascore=1.0）
  与签字完全无关，取消签字**没有放松任何一条数据判据**。Markdown 报告新增一行
  `签字闸门: **已取消** …`，与既有那行「本报告证明的是回放与判定管线自洽,
  不等于金标准经人工审核」一起构成这次改动的核心产出 —— **披露替代阻断，
  不是两者都免**。
- 14 个签字相关用例改写为「披露到位 / 不阻断」：自签披露逐 case 落地、
  台账无条目 / gold 签后被改 / 生成器漂移三条各自落在 `review_disclosure` 的
  正确列上，且真人工签字仍被如实记成 `human`（披露不是一刀切"未完成"）。
- 口径同步：`docs/eval-E2-groundtruth.md` §4.3.0（新增裁定记录）、`REPORT.md`、
  `eval-E2-signing-guide.md` 三态表、`EVAL-UNLOCK-CHECKLIST.md` 门禁表（E2 行划掉）、
  `EVAL-HUMAN-RUNBOOK.md` L1 判据、`review/README.md`、`gen_gold.py` 与
  `backfill_reviews.py` 的注释/提示（**注释必须与代码一致，否则文档说谎**）。
- **连带：17 份金标准重生成 + 汇总表重出**。改 `gen_gold.py` 的注释会让它的
  sha256 变化，17 份金标准内嵌的旧指纹随即与现况对不上 ——
  `test_repo_golds_are_regenerated_with_the_current_generator` 正是抓这个的，它红了。
  按纪律用当前生成器逐场景重生成 17 份（生成器出厂自签的现状保持不动，
  回填签字仍属人工那一步）；金标准一换，`HUMAN_REVIEW_SHEET.csv` 里锁死的答案
  指纹随之失效，15 条 `test_review_sheet` 报 `STALE`，重出表后转绿。
  **两道门都在正常工作**：一道抓"答案不是现版本脚本产的"，一道抓"审的不是这份答案"。

### E3：`items_real.yaml` 溯源复核抓到一处抄错（未切换）

- 10 个 fixture 逐字段对回真实快照：8 个有溯源的**零差异**，另 2 个核对通过
  （`fx_ps1_pair` 多行、`fx_zero_rows` 零行）。那 5 处"差异"只是 YAML `null` 与
  CSV 空串的表示差别，正是真实回包里 `ps1_source_id` 与四个 `*_corr` 列**整列为空**
  这件事。
- **一处真错已修**：`fx_gaia_mixed` 的 `source_id` 写作 `4512921183874235904`，
  真实值是 `4512921183874236032`（末四位抄错，该值在整份 gaia 快照里不存在）。
  三处同步修正（`fixtures_real.yaml` / `items_real.yaml` 的 fixture 段与题面）。
- **`items.yaml` → `items_real.yaml` 的切换仍未做**（铁律 4 结构变更，待批准）：
  36 题中 13 条前提重建、11 条只换锚点/断言含数值、11 条不动，diff 已逐条呈交。

## E4 回放底座换真实数据：Tier W 15/15，判据不再写死合成值（2026-10-04 续四）

- `evals/robustness/fixtures/ps1_replay.csv`：5 行编造数据 → **实抓快照的 3 行**
  （`live_ps1_ra180.0_dec30.0_r60.0as` 第 31/69/159 行，五波段星等与误差都是真值）。
  挑选判据是必需的：先试过 5″ 快照的 3 行，那三行 `ps1_rpsf` **全是哨兵**，F8 的
  类型漂移（RB-31）与列序打乱（RB-34）无值可恢复，Tier W 掉到 13/15 ——
  **是素材缺形态，不是判定器坏了**。`fixtures/README.md` 写明来源、挑选判据与连带
  约束，并如实声明这是**子集**（逐行逐字节来自站点，但不是整份响应）。
- **换掉的那份还有个更基础的问题**：它带了一个**站点根本不发布的列** `ps1_snr`
  （真实 ps1 只有 `*_err` 误差列；仓内 `CATALOG_COLUMNS['ps1']` 登记的 30 列与真实
  回包逐列比对是**零差异**，其中没有 snr）。也就是说 E4 的线路层回放里既没有哨兵值、
  也没有空列，"客户端不能把 -1004 当星等"这类判据在 E4 里**从未在线路形态上被考过**。
  同一批幽灵列也存在于 E6 的 `ps1_5rows`/`ps1_2pages` 与 E2 的 `syn_missing`。
- **`runner._normalization_ok` 原本把合成值写死**（`rpsf≈18.20` / `ra≈180.0001`）。
  夹具一换，判据仍在与常量比，于是 RB-31/RB-34 双双报"未纠正" —— 素材换了而期望
  没换。改为**从夹具首行现取期望值**：判据要问的是"漂移值有没有正确穿过解析层"，
  那个"正确"的参照只能是源值本身。写死常量等于把夹具锁死在合成数据上，下次换素材
  会再次静默失效。
- `replay.TOTAL` 5 → 3（getcount 与数据页必须自洽，否则截断三元组永假）。
- **等价性层同步为同一批真实行**（`ps1_equiv.csv` / `equiv_ps1`）：三家回放要在
  **带哨兵与空列的脏数据**上仍逐字节一致，比原先的干净合成行更难。其快照 `note`
  里"无哨兵, 无脏形态"的自述已随之改写 —— 那句话在换数据后就是假的。
- `test_getcount_and_page` 的断言从 `BEST_SIM_0001` 换成夹具首行的真坐标
  （任何合成夹具都能满足 `BEST_SIM_*`，换掉基线它不会红）。
- **E6 的 `soft404` 夹具无需改**：实抓的软 404 回包是 22 字节
  `{"error":"Not Found"}\n`，与手写夹具**逐字节相同** —— 反倒证实那份夹具写对了。
- E6 其余三个夹具（`ps1_5rows` / `ps1_2pages` / `scr_galah_3rows`）**本轮未动**：
  它们与 `TOTAL`、分页序列、测试里的行数断言绑死，换素材要连带重算，且
  `scr_galah` 真实就是 0 行（与夹具名 "3rows" 的结构角色冲突）。已登记，待决。

## E3 全部 36 题按真实数据重推（`items_real.yaml`，**尚未切换**）

- `evals/semantics/fixtures_real.yaml`（10 块）+ `evals/semantics/items_real.yaml`
  （36 题）。逐题处置分四类，每题在 `_change` 字段写明：**只换锚点 10 /
  断言含数值 2 / 前提重建 13 / 不动 11**。数值一律从 fixture 现取（不手抄），
  题面引用哪几块 fixture 由 `fixture_refs` 显式声明。
- **前提重建的 13 条是本轮主要工作** —— 这些题目的事实前提在真实数据里**不成立**，
  硬套数值会造出一道"数据与题干不符"的题：

  | 题 | 原前提（编造） | 真实前提 |
  |---|---|---|
  | A05 | 两表差 1.2 mag | 同一颗星两表**吻合到 0.006 mag**（接近不等于同源） |
  | B03 | `rmmed` 与 `r_h22` 差 0.019 | 真实**只差 0.003** —— 极接近却是不同产物 |
  | B04 | u 波段观测次数少得多 (4 vs 12) | 次数**并不少** (21 vs 20)，但 u 的 rms 大一个量级 → 判据换成"离散度" |
  | B05 | `rmchi2=1.83` 大于 1 | 真实 `rmchi2=0.422` **小于 1** → 改用 `umchi2=1.474` |
  | C03 | 该列是 flux (`3.912e-15`)，算不出星等 | 真实值 **18.0955（星等量级）**且列名未声明量纲 |
  | D01 | 哨兵是 `-999.0` | 真实 `-1002.879` → 判据改成 `≤ -999` |
  | D03 | `class_star=0.02` | ps1 的 class_star **整列为空** → 改用 uss_dr1 的 `u_class_star=0.0764` |
  | D04 | `rpsf` 与 `rpsf_corr` 两列值不同 | 真实 `*_corr` 四列**整列全空** (0/174) |
  | D05 | `ruwe=1.42`、`ipd=3` 提示异常 | 真实 `ruwe=1.015`、`ipd=0` **都不提示异常** → 限制改来自视差自身约 26% 的相对误差 |
  | D06 | `yflags=128` 而其余为 0 | 换成真实确实不一致的一行（`yflags=114720` vs `g=16416`） |
  | F01 | 零行天区 (180,30) r=3″ | 换成真实零行快照 ps1@(10,−45) r=60″ |
  | G04 | 标识符 `J180012.3+300456` | 换成真实 Gaia DR3 `source_id` |
  | C01 | 跨表比 flux 与星等 | 两块 fixture 显式声明（`fixture_refs`） |

- **为 E3-A05 补抓一份 ps1**：该题前提是"同一颗星在 ps1 与 stripe82 都有"，而两块
  fixture 原先取自不同位置，语义被破坏。在 stripe82 那颗星的位置
  (29.967632, 0.024272) 补抓 ps1，得 `rpsf=16.6079`（stripe82 侧 `rmmed=16.614`，
  位置差约 0.5″）。**真实数据里两表吻合到 0.006 mag** —— 题目从原来的"差 1.2 mag
  是不是在变"变成"几乎相同也不能当时间证据"，陷阱更隐蔽，语义（BEST 无时序）不变。
- **三道自查都跑通**：
  - 形态断言 **10/10**（每块 fixture 原本为某题设计的性质在真实数据里确实存在，
    不是只换了数值）；
  - 题面数值**阻断级 0 条** —— 每个数都能在其声明的 fixture 里查到。这一关抓到过
    **三处旧编造值残留**：D04 的 `16.204`/`16.041`、E05 的 `2.14`、C04 的 `766`，
    分别藏在 `answer_sketch` 与 `must_not_state` 里，只改 `prompt` 会漏掉；
  - **真实列缺口 0**（余下 7 条是表名/文件路径/工具参数）。
- **切换属结构变更，未擅自做**：`items.yaml` 保持原样，E3 仍按旧题集跑、门禁不受
  影响。切换 runner 的题集指向需一次批准，好处是这份 diff 可被完整评审
  —— 尤其那 13 条前提重建值得逐条过一眼。

### 抓取工具的保真缺陷（本轮补记）

- **BOM 加了又没加对**。`ops/live_fetch._write` 曾无条件按 `utf-8-sig` 落盘，而
  `RecordingSession` 存的是 `resp.text` —— 站点 CSV 的 BOM 已经以 `\ufeff` 留在文本里。
  于是两个方向都错：CSV 落成**双** BOM（`\xef\xbb\xbf` ×2，61 个文件），而
  `count.json` / `phase1.html` 被**凭空加**一层 BOM（62 个文件）。两种都违背每份
  `snapshot.yaml` 里「回包逐字节来自站点，未做任何改写」的声明；读侧还因此认不出
  首列（`\ufeffinputobjs_dist_arcsec`、`\ufeffra_u`），按名取列一律取不到。
  改为**一律按纯 utf-8 写**，BOM 由回包文本自带。既有 123 份文件已按
  「剥一层 BOM 后是否与 `manifest.json` 哈希相符」这一**自验证**规则归一，
  全部对上（manifest 记的正是 `sha256(text.encode("utf-8"))`）。
- **`proximity` 的 slug 只带点数** → 换一组坐标重抓会**静默覆盖**已入库的旧快照
  （踩过一次：174 行被 0 行盖掉）。点集摘要进目录名。
- **`_run_proximity` 绕开公开接口自拼表单**，产出的"proximity 答案"是坏的
  （174 行全标 `input_line=2`、没有 `inputobjs_dist_arcsec`）。改走
  `crossmatch_batch` 公开接口 —— E2 回放侧也走这条，两侧同源才谈得上"快照就是
  这个查询的答案"。三份抓坏的快照已删除。
- 一处 Python 陷阱：`task.get("radius", points[0][2])` 的**默认参数是急切求值**的，
  即使 `radius` 给了也会先算 `points[0][2]` 而 IndexError。

## E2 全绿：17/17 PASS 跑在真实天文数据上（2026-10-04 续三）

> 上一节把 16/17 场景改指到真实回包、E2 升到 12/17，余 5 例逐条定位。本节把那 5 例
> 全部收掉 —— **E2 = 17/17 PASS、`pass: true`、metascore 1.0，且 16/17 场景的素材
> 是逐字节来自站点的真实回包**。人工签字闸门仍按设计拦截（`--require-human-review`
> exit 1，17 条全判 `gold_not_human_signed`）。

### Fixed（本轮新增 2 个协议层事实 + 1 处抓取工具缺陷）

- **主键：id 必须"集合内唯一"才可用**。`live_ps1_ra359.5_dec0.0_r1800.0as`（1000 行）
  里有 **2 个重复的 `ps1_source_id`**。E2 §2 原写「有 source_id 用 source_id」——
  "有"不等于"唯一"：重复 id 让两行塌成同一主键，M2 拿 A 行的期望值去比 B 行的实际
  值，报出一串看着像"数据对不上"的假失配（`boundary_wrap_ra` 3 格失配全部来自这里）。
  新增 `canonical.id_keys_unique` / `gold_algorithms.id_keys_unique`：在**结果集层**
  判一次，重复即整批走坐标键。逐行的 `row_key` 看不到集合，所以判据不能塞在那里。
- **`inputobjs_input_line` 是 1-based**。真实抓取三个输入点回显 1/2/3，而场景 `inputs`
  是 0-based 序列、oracle 拼 `in<N>:` 用的也是 0-based —— 不归一就整体错位一格，
  M1 报"行集对不上"却看不出是基准问题。新增 `canonical.batch_line_offset`：
  取集合内最小行号，≥1 即认定 1-based（偏移 1），出现 0 即认定 0-based —— 两种素材
  都对，不把某一侧的真实约定写死成常量。
- **按整列为空的列排序等于没排**。`boundary_page_exact` 的 `ps1_source_id` 在 770 行
  里 0 个非空、`huge_3700rows` 的 4003 行里只有 3 个：服务端按空列排是空操作，而
  oracle 的主键次级 tiebreak 会重排并列行，M4 的 `sequence_match` 必然对不上。
  两条改按 `ps1_ra`（位置列，每行有值且真在变）。
- **`ops/live_fetch.py` 两处**：
  - `proximity` 任务的 `slug` 只带点数 → 换一组坐标重抓会**静默覆盖**已入库的旧快照
    （踩过一次：174 行被 0 行盖掉）。点集摘要进目录名。
  - `_run_proximity` 绕开公开接口自拼表单，产出的"proximity 答案"是坏的（174 行全标
    `input_line=2`、没有 `inputobjs_dist_arcsec`）。改走 `crossmatch_batch` 公开接口
    —— E2 回放侧也走这条，两侧同源才谈得上"快照就是这个查询的答案"。三份抓坏的
    快照已删除，保留的 v2 是 3 行 / `input_line` 1,2,3 / 三颗不同源的真答案。
  - 另修一处 Python 陷阱：`task.get("radius", points[0][2])` 的**默认参数是急切求值**
    的，即使 `radius` 给了也会先算 `points[0][2]` 而 IndexError。

### Changed

- `boundary_maxrows` 换回 ps1@60″（174 行真数据，`max_rows=page_size=174` → 总行数
  恰等于上限、`truncated` 必须为 False，本用例要测的语义不变）。换表的原因**登记在
  此而非掩盖**：stripe82 的 id 列是 `stripe82_calibstars_id`（不匹配 `*_source_id`）。
  **产品侧无缺陷** —— `BestSource.from_row` 的别名支路已含 `calibstars_id`，实测能取到
  `CALIBSTARS_0813769`；是 **oracle 侧**按 `*_source_id` 找主键取不到、退化到坐标对，
  两侧建行口径不对称。修法在 oracle 主键判据，与本用例无关。
- `evals/groundtruth/snapshots/live-2026-10-04/` 现有 31 份快照 / 216 个文件。

### 测试

- `test_key_set_dedup` 拆成三条：去重性质、`id 唯一时用 id 键`、`id 重复时整批降级`。
  原用例拿**重复 id** 演示去重，而重复 id 现在正是降级的触发条件 —— 前提被新规则
  推翻，拆开各自钉住。`batch_line_offset` 另配一条（1-based 与 0-based 各一例）。
- E2 测试 75 passed；review sheet 按新金标准重新出表。

## E2 改指真实快照：16/17 场景换真实素材 + 真实数据逼出 7 个缺陷（2026-10-04 续二）

> 起因: 上一节把 20 份真实回包入库了，但 17 份金标准仍挂在 `syn_*` 合成快照上
> （其中 3 份合成却挂在名为 `ps1_*` 的"L 类真实快照"下）。本节把场景改指到真实
> 回包，并用独立 oracle 重算全部金标准。**当前 E2 = 12/17 PASS**（改指前合成
> 素材上 17/17），余 5 例的根因已逐一定位，见下表。

### Added

- `ops/live_fetch.py` 扩出三类新任务形态：`constraints`（多列约束直传协议层表单，
  绕 `cone_search` 的单约束入口）、`proximity`（多点批量）、`raw`（绕开入口校验的
  原始 POST，专为取证 `radius=0` 与未知表名的软 404）。新增 7 个任务集
  （`e2_rows` / `e2_mag_snr` / `e2_proximity` / `e2_pole` / `e2_wrap` /
  `e2_zero_radius` / `e2_page_exact`），并把 `soft404` 集从"走客户端（必然被
  表名校验拦下）"改成走 `raw` 通道。`slug()` 补上 `max_records`/`constraints`
  段 —— 不同参数必须不同名，否则重抓会静默覆盖已入库素材。
- 补抓落地 11 份真实快照（4003 行多页样本、5 行双约束锥搜、3 点 proximity、
  北天极 163 行、赤经回绕 total=305172、radius=0 的无 sqlid 结果页、
  未知表名的真软 404）。`evals/groundtruth/snapshots/live-2026-10-04/` 现有
  **31 份快照 / 216 个文件**（全部已入库）。

### Fixed（真实数据逼出的 7 个缺陷，全部有留档证据）

| # | 位置 | 缺陷 | 真实数据怎么暴露的 |
|---|------|------|-------------------|
| 1 | `canonical.row_key` | 只认裸名 `ra`/`dec`，且 proximity 分支**缺 None 保护**直接 `round(None)` 抛 TypeError | 12 张表的真实回包**每一行**都构不出坐标键；`syn_*` 全过 → 是列名形态问题不是数据问题 |
| 2 | `canonical.row_key` | 主键列硬编码 `source_id`/`ps1_source_id` 两个名字 | `xpsp`/`dr3xpcorr` 的主键是 `gaiaxp_photinfo_replenish_source_id`，被恒判成"无主键" |
| 3 | `canonical.normalize_value` | `float('nan')` 转得"成功"，NaN 流进比对层 | 站点在大量幅值列回字面量 `nan`（uss_dr1 一份 37077 格）。`nan == nan` 恒假 → 每格成对假失配，且 M5 把缺测读成有值，**且不报错** |
| 4 | `gold_algorithms.row_key` | oracle 侧那份拷贝同样只认裸名与两个硬编码名 | 与 #1/#2 同源。两侧是**刻意不复用**的（"格式契约，非共享代码 — 铁律"），所以只能各自修到同一契约 |
| 5 | `metrics/m3_units._significant_digits` | 拿 `Decimal.exponent` 跟 0 比，NaN/Inf 的 exponent 是**字符串** → TypeError | 同 #3 的 `nan` |
| 6 | `canonical.row_key` 的批量判据 | 靠"行里有没有 `inputobjs_input_line`"判批量行 | **锥搜回包同样带这列**（单输入恒为 0）→ 每个锥搜结果集都被错判成批量行，主键凭空多个 `in0:` 前缀。判据改由查询传入（`row_key(row, batch=)` / `key_set(rows, batch=)`，M1/M2/M4 与 `run_e2` 同步） |
| 7 | `canonical.normalize_value` | 19 位整数主键转 float 丢精度 | `4512921183874236032` → `4.512921183874236e+18`，同一条记录两侧算出两个主键。`references/data-formats.md §5` 早已把这条列为标识符列的硬要求，归一层此前漏了 |

另修两处**生成器与自己文档矛盾**的缺陷：

- `gen_gold.py` 出厂写 `signed=false`，而 `run_e2.py:46` 明写「gen_gold.py 产出的
  金标准由脚本自己署 offline-selfcheck」、`test_repo_gold_is_all_self_signed_today`
  断言 17 份全为自签。两者矛盾，按文档与测试改生成器（署名取
  `SELF_SIGN_BYERS` 同口径，不抄第二份名单）。**不能改成 `signed=false`**：
  那会让默认离线自检模式也判 `gold_unsigned` 而全批阻断。
- `gen_gold.py` 落盘没钉行尾，按平台默认写成 CRLF，与 `.gitattributes` 的
  `*.json/*.yaml → LF` 冲突。补 `newline="\n"`。

### Changed

- 17 个场景改指：`snapshot_id` 16 个换成 `live-2026-10-04/...`，`missing_column`
  保留 `syn_missing`（站点**不产生**"列不存在"的回包；ps1 的 `ps1_gpsf` 等是
  "列在但全空"，那是 `missing_cell` 的语义，两案不可合并）。
- 连带订正换表后的残留假设：几何坐标、`columns`、`sort`、`max_rows`/`page_size`、
  `constraints`（oracle 读的是 `{column, op, value}`，`between` 的 value 必须是
  `{min, max}`）、proximity 的 `inputs` 真坐标。`boundary_page_exact` 用
  "770 行 / `page_size=385` = 2 个满页"让真实数据照样钉住整页边界。

### 两条前提被改指合法推翻的测试（改法都更严，不是放宽）

- `test_repo_generator_drift_is_disclosed_not_hidden` 原来断言"仓内此刻恰好漂移"，
  于是金标准一重算漂移归零，它就**静默失去测试能力**。拆成两条：用 monkeypatch
  注入漂移测**机制**（确定性、与仓内状态解耦），另加一条断言新事实
  （金标准与现版本生成器一致 → 无漂移）。**漂移为零不等于已人工签字**。
- `test_metascore_gates_the_overall_verdict` 原来以"真实夹具必须是绿的"为前置，
  等于把素材状态当成本测试的前提。改为直接验放行公式
  （`pass == (n_pass == n_cases 且 metascore == 1.0)`）——比"假设它是绿的"更强。
- `test_review_sheet.py` 的沙箱克隆只扫顶层快照目录，真实快照嵌在
  `live-<日期>/` 下一层 → 拷不到 `snapshot.yaml`。改 `rglob` 并保留相对路径。
  `HUMAN_REVIEW_SHEET.csv` 按新金标准重新出表（17 行全待人工填写）。

### 未过 5 例（根因已定位，未动手）

| 场景 | 症状 | 根因 |
|------|------|------|
| `batch_proximity` | gold 有 `in0:`/`in1:`，回放只有 `in2:` | 场景的两个输入点**同中心不同半径**，服务端把它们并成一组回连；冻结答案里就没有 in0/in1 那些行。需用三个**不同中心**重抓 |
| `boundary_maxrows` | gold 键是坐标、实际键是 `CALIBSTARS_*` | stripe82 的 id 列是 `stripe82_calibstars_id`（不匹配 `*_source_id`）。**产品侧 `BestSource.from_row` 别名支路已含它、能取到值**（live 实证后修过），是 oracle 侧按 `*_source_id` 取不到而退化到坐标对 —— 两侧建行口径不对称，修法在 oracle 主键判据 |
| `boundary_page_exact` | 只 M4 不过（0.9498） | 分页结构项待核 |
| `huge_3700rows` | 只 M4 不过（0.9499） | 分页结构项待核；注意快照落 4000 行而服务端 `total=5109`，回放按 `rows_full` 重算得 4000，与服务端计数不等（M6 只记警告） |
| `boundary_wrap_ra` | 只 M2 不过（0.9889） | 逐格值待核 |

## 找回丢失内容 + temp/ 资产转正 + reference 按真实回包完善（2026-10-04 续）

> 起因: 用户三条指令 —— ① 丢失的内容看远程仓库能否找回；② 把已有内容（含 temp/）
> 整理一下；③ 先再次完善 reference，再继续完善实验方案。

### Fixed（把「不可逆损失」结论作废）

- 上一节记的「4 个测试用例不可逆丢失」**结论错误，已撤回**。当时只查了 git
  对象库就下了判断；实际上**当初写下这些方法的 Edit 调用，其 `new_string` 原文
  完整保存在会话转录里**。已逐字取回 7 项（3 个辅助方法 + 4 个测试），
  `evals/groundtruth/tests/` 由 61（原 65）→ 67 → **71**，`test_e2.py` 37 → **41** 条全绿。
- 连带纠正一处**事故后临时补丁的降级**：`test_human_gate_lets_real_signer_through`
  事故后被改成打桩 `verify_case_ledger` 才转绿；原版是喂一份**合规台账**让真实校验
  跑通。恢复原版后这条反向自证不再靠屏蔽校验过关，下面三条反证（台账无条目 /
  签后 gold 被改 / 生成器漂移）也才真正测得到闸门。
- 教训已写进 CHANGELOG 事故记录：判「不可逆」之前，会话转录 / 编辑器本地历史 /
  `__pycache__` 三条路都要走过。**「对象库里没有」只等于「git 恢复不出来」。**

### Added（temp/ 资产转正，经用户批准）

- **跑批产出入库**（原先全躺在 gitignored 的 `temp/live/`，随时会丢）：
  - `docs/EVAL-LIVE-RUN-2026-10-04.md` —— 六实验真模型跑批完整报告（原 §9「东西都在
    会被删的目录里」整节重写，3 处 temp/ 路径引用同步订正）；
  - `evals/{nl2tool,groundtruth,semantics,robustness,ablation,repro}/live-2026-10-04.json`
    —— 六份计分结果。E2 那份 **1481 KB → 61.8 KB**：体积 92% 在
    `m3_units.precision_warnings` 这个**逐值**清单上（huge_* 两 case 合计约 587 KB），
    按每 case 20 条截断，并在 JSON 内登记 `_total` / `_truncated` / `_kept` / `_note`
    四个字段 —— **截断事实写在数据里，不靠文档声明**；真实失败项 `precision_errors`
    一条未删。
  - `evals/ablation/live-dual-arm-2026-10-04.json` —— E5 双臂结果**首次落盘**。
    原脚本只 `print` 不落盘，这组数字此前仅以报告正文形式存在，无法复算。
- **四份判分脚本转正进 `evals/`**（推翻原作者 docstring 里「一次性跑批脚本（不入库）」，
  经用户批准）：`evals/semantics/score_l2.py`、`evals/robustness/judge_tier_p.py`、
  `evals/ablation/score_live.py`、`evals/repro/score_r1.py`。统一 `--live-dir`
  （采集物目录）与 `--out`（落盘路径）两个入参，**逐字段复算与入库 JSON 完全一致**
  （E6 另补 `PAC_ci95` / `first_tool_correct_ci95` 两个区间字段）。

### Changed（reference 按真实回包完善）

- `references/site-endpoints-and-interactions.md` 新增 **§10 真实回包全表普查**
  （20 份入库快照为证）：§10.1 坐标列形态 12 表实测 5 种、**不能硬编码**；
  §10.2 `build_query_form` 权威 7 键，手搓少提交 `pos.*` 会**静默**退化成无约束
  全表查询；§10.3 逐表实测行数与判读；§10.4 `uss_dr1` 分波段坐标记不可用而非猜一个；
  §10.5 留档真实软 404 必须绕开高层客户端；§10.6 抓取纪律四条。
- `references/data-formats.md` §5 补一条警告：坐标列「`_ra`/`_dec` 结尾」这条
  规则**不是完备判据**（xpsp/dr3xpcorr 前缀是共享表名，uss_dr1 根本没有规范化坐标列），
  且 `inputobjs_input_ra/dec` 是查询输入坐标、不该给源行补 `unit="deg"`。
- `references/best-database-guide.md` 在 12 表清单下补「可查询 ≠ 任意天区查得到」。
- `references/llms.txt` 索引补三条高价值陷阱（坐标列不能硬编码 / 表单别手搓 / 0 行不等于坏表）。

### Fixed（一处被留档证据推翻的记录）

- `ops/live_fetch.py::COVERAGE_NOTES` 里 `jplus_dr3` 原记「分页回软 404 而客户端报
  success/0（`total=0` 时跳过分页取）」——**与留档证据矛盾，已撤回**。快照
  `live_jplus_dr3_ra120.3_dec-20.4_r300.0as` 显示 `getcount` 与分页**自洽**
  （`{"total":0}` + HTTP 200 的 12 列表头 CSV、0 数据行，无软 404），客户端三条请求
  证明分页确实发出；`client_paging.py` 的循环条件是 `total_fetched < max_rows`，
  不看 `getcount`。`jplus_dr3` 仍**疑似站点侧覆盖异常待站方确认**，但依据只剩
  「24 处探测全 0」这一条，要坐实需要站方日志。

### Removed

- `temp/baseline_{final,after,check}/` 三份重复图目录（63 MB 中约 47 MB 为逐字节
  重复：5 个文件里 4 个四份完全相同，只有 PDF 各不相同），已移入回收站；
  保留 `temp/baseline_before/` 作回归对照基准（图可由 `docs/diagrams/gen_*.py` 重生成）。

## live 素材重建：铁律 7 条件豁免 + 独立 oracle 的坐标列缺陷（2026-10-04）

> 起因: 用户要求「六个实验都必须按最真实的信息来，必要时可以对 BEST 的数据进行
> 下载」。站���实测可达（HTTP 200 / 0.61s），故开铁律 7 的**有条件豁免**：抓取只解决
> 「素材从哪来」，判分口径一律不动，评测仍跑回放。条款全文见
> `docs/EVAL-LIVE-FETCH-WAIVER.md`，CLAUDE.md 铁律 7 已同步。

### Added

- `ops/live_fetch.py`：真实快照抓取入口。**默认 dry-run**（不带 `--execute` 一个请求
  都不发）；`RecordingSession` 继承 `requests.Session` 只重写 `request`，客户端实际
  发了什么就录什么，**不重实现协议**；不重试 POST；串行 + 强制间隔；每个快照落
  `manifest.json`（逐文件 sha256）与 `capture_log.json`（逐请求日志）供审计。
- `evals/groundtruth/snapshots/live-2026-10-04/`：20 份真实快照（12 张可查表按**实测
  标定**的代表坐标 + 空区/极小半径/服务端排序三种边界）。

### Fixed（真实数据暴露的判定缺陷）

- `QueryAwareTransport._row_coord` 原只认 `ra`/`ps1_ra` 与 `dec`/`ps1_dec`，而 12 张
  可查表里**只有 ps1 有裸 `ra`/`dec` 列**。非 ps1 表（stripe82/splus_dr4/smss_dr4/
  scr_lamost/gaia_dr3_18 用 `{table}_ra`；xpsp 用 `gaiaxp_*_ra`）的行全被判「坐标不可用」
  而丢弃，独立重算**静默返回 0 行** —— 与「天区真的无源」读起来一模一样。
  合成素材的列名恰好都落在旧口径内，所以该缺陷在纯合成批次里永远绿灯。
  改为三级回退（裸形 → 本表前缀 → 任意同前缀配对，表名从 POST 的 URL 反解），
  并新增 `coord_unavailable` 计数器：**认不出坐标时记为不可用并可读数，不回退成
  「零行」**（铁律 5 禁 fail-open）。保真验收从 13/20 提到 **19/20**。
  剩下 1 条是 `uss_dr1`：它的坐标是**分波段**的（`ra_u`/`ra_j0378`…，前缀式），
  「这一行的位置」本身多值 —— 如实记为不可用，而**不挑一个波段凑答案**。
  教训一句话：**独立 oracle 只有在素材列名足够多样时才真的独立。**

### 真实数据揭示的站点侧事实（登记，未修复）

- **`jplus_dr3` 疑似坏表**：在其公认天区（Dec −79…−45）探测 24 处，含最大半径 5°，
  全部 `success=True / total=0 / error_code=None`；权威表单下 `getcount={"total":0}`
  而分页回软 404 `{"error":"Not Found"}`。客户端在 `total=0` 时不取分页页，软 404
  **从未被观测**，`is_soft_error` 无从触发 —— 「0 命中是合法结果」这条规则在此把一张
  坏表洗成了正常结果。**待站方确认。**
- **`landolt` 0 命中属统计正常**：全表 45712 行摊到全天约 1 行/3.7 deg²，0.5° 锥期望
  命中 0.018 行。**与 jplus 的异常必须分开报告，不能都写成「没数据」。**
- **软 404 走高层客户端抓不到**：被 `ValueError: Unknown BEST catalog` 拦在发包前
  （客户端先做表名校验）。要留档真实软错误形态必须走原始 HTTP 绕过校验层。

### 事故记录（操作失误；功能已恢复，丢失内容**已从会话转录找回**）

用 `git checkout HEAD -- evals/groundtruth/tests/test_e2.py` 清理自己写坏的文件时，
**一并覆盖了该文件前序会话尚未提交的改动**（该文件当时是 `MM` 状态：已暂存 + 未暂存）。
- 已恢复：文件回到 HEAD 版本后 1 条测试失败（`test_human_gate_lets_real_signer_through`
  缺 `verify_case_ledger` 的 monkeypatch 隔离，导致真实台账把假 signer 拦下），测试转绿。
- **曾判为不可逆，现已找回**：当时只查了 git 对象库（`git fsck --unreachable`）就下了
  「无法恢复」的结论。实际上**当初写下这 7 个方法的那次 Edit 调用，其 `new_string`
  原文完整保存在会话转录里** —— 恢复时逐字取回（见下表），`evals/groundtruth/tests/`
  由 61（原 65）→ 67 → **71**，`test_e2.py` 单文件 37 → **41** 条，全绿。

| 找回路径 | 结果 |
|---------|------|
| 远程 `origin/refactor/comment-declutter-and-audit-split` | ✗ 未提交过的改动不可能在远端；远端 ref 与本地 HEAD 同为 `c8574aa` |
| `git reflog` / `git stash` / `git fsck --unreachable` | ✗ 无 dangling blob（结论本身没错，错在把它当唯一路径） |
| `evals/groundtruth/tests/__pycache__/*.pyc` | ✗ 源码一改，pyc 头里的 `rec_size` 已被重写成事故后的大小（28473），事故前那份被原地覆盖 |
| `temp/head_snap/` `temp/snap/` 里的旧副本 | ✗ 均为 10-02 快照，早于 10-03 那次编辑，不含这批方法 |
| **会话转录 `~/.minimax/v2/sessions/2026/10/03/10-29-08-647-*/messages.jsonl`** | ✓ **命中**：工具调用参数里存着逐字原文 |

找回的内容（7 项，全部逐字恢复，无一处改写）：

| 类型 | 名称 |
|------|------|
| 辅助方法 ×3 | `_compliant_gold` / `_ledger` / `_gate_with` |
| 测试 ×4 | `test_human_gate_blocks_when_ledger_has_no_entry`、`test_human_gate_blocks_when_gold_changed_after_signing`、`test_human_gate_blocks_when_generator_drifted`、`test_repo_generator_drift_is_disclosed_not_hidden` |

连带纠正了一处**事故后临时补丁的降级**：`test_human_gate_lets_real_signer_through`
在事故后曾被改成打桩 `verify_case_ledger` 让它转绿；原版是喂一份**合规台账**让真实
校验跑通。恢复原版后，这条反向自证不再靠屏蔽校验过关，而下面三条反证
（台账无条目 / 签后 gold 被改 / 生成器漂移）也才真正测得到闸门。

- 教训一：清理自己写坏的文件**不得**用 `git checkout HEAD --`；那会连同别人的未提交
  改动一起丢掉。正确做法是先 `git diff > temp/backup.patch` 或先 `cp` 到 `temp/`。
- 教训二：**「对象库里没有」只等于「git 恢复不出来」，不等于「内容没了」**。
  agent 写下的每个字节都留在会话转录的工具参数里。判不可逆之前，先把
  转录 / 编辑器本地历史 / `__pycache__` 三条路都走一遍再下结论。

## 真模型跑批的判据修正：七处判定缺陷 + 四处标注冲突（2026-10-04）

> 起因：第一次用真模型（26 题 × 3 轮盲测）跑 E1–E6。跑批本身通过，但暴露
> **判定器把正确行为判错、标注预设了仓库里不存在的事实**两类问题。下列改动
> 全部以「golden 自证批仍 1.00 / metascore 仍 1.00 / W 层仍 15/15」为不变量，
> 逐条加了双向自证测试（既证该拦的拦住，也证不该拦的放行）。

### Fixed（判定器缺陷，7 处）

| ID | 位置 | 缺陷 | 改法 |
|----|------|------|------|
| G1 | `nl2tool/normalizers.py` | `norm_set` 用集合**全等**比 `columns`，多投影一列即判 param=0 —— 实测模型多要一个 `ruwe` 质量标志被判错 6 次 | 新增 `norm_set_covers`（标注列必须齐全，多投影不罚）；刻意**不**剥星表前缀，否则裸列名会通过，撞上 NL2T-15/16 的 S1 反模式 |
| G2 | `nl2tool/graders.py` | 标注点名的参数漏传即判错，不看 schema 有没有 `default` —— 实测 8 次 | 缺省时取 `properties[key].default` 当实测量再比一次；无 `default` 声明的键（`sort`/`radius_arcsec`）仍判错 |
| G3 | `nl2tool/graders.py` | reject 的 `has_alt` 要求逐字命中整句 `suggest`，实测 11/12 次给了实质替代路径全判 0.5 | 双通道：逐字命中是强证据，命中不了退到兜底词表（与 E4 `_ALT_WORDS` 同源，按铁律 6 独立复刻）；两通道结果都进 evidence |
| G4 | `robustness/graders.py` | M5/M6 是协议层红线，却在只带话术的 trace 上返回 **1.0** —— 什么都没查却算满分（假绿，比假红更危险） | 加重事实守卫：trace 不带协议层事实时记 N/A；`grade_case` 无适用指标时 `weighted=None` + `scored=False` + `weighted_note` |
| P4 | `semantics/prescreen.py` | `check_static_as_lc` 只看向后一侧的否定窗口，隐含「否定词总写在前面」；中文否定常**后置**，实测 5 条假阳 | 改双向窗口（28 字符）+ 补否定动词（做不到/给不出/不发布/看不出…）+ 新增「安全语境」档（`统计摘要` 属 §2 的 `single_or_coadded` 限定语）。同步回改 `rubric.yaml §3`，并加 `load_rubric_prescreen()` 让「代码↔文档脱钩」可被测试抓到 |
| R1 | `semantics/report.py` | UNGR 直接渲染 L0 值 0.4313，会被当结论引用 | 行标题标注「**L0 预筛版 = 上界**」+ 增披露段（L2 复核后 0.0070，差 62 倍） |
| R2 | `robustness/runner.py` | `weighted=None` 的「未判」条目不上人读面 | 报告增「加权判据记账: 已判 N/M 条; 未判(无适用指标, 非零分) …」 |

### Changed（冻结标注，4 处 —— 按 E1 §9 记 CHANGELOG）

| ID | 文件 | 改动 | 依据 |
|----|------|------|------|
| A1 | `nl2tool/tasks.yaml` | 7 条澄清题补 `clarify.probes`（中文探针）；clarify 维增加并联的探针通道 | 六词表漏判严重：21 次正确澄清里 17 次判 0.5 |
| A2 | `robustness/items.yaml` | 10 条 C 级用例补 `clarify.probes`；`score_m2` 的 `named` 改双通道（探针优先、枚举 id 兜底） | `clarify.missing` 存的是英文枚举 id（`radius_unit`），中文话术逐字命不中 → **10 条 C 级没有一条能判满分**，而不少回答是标准答案级 |
| A3 | `semantics/items.yaml` `E3-E04` | 重写 `must_state`/`must_not_state` | 原题面预设 `scr_lamost` 有 Teff/logg 并给出官方覆盖子集；实际该表 137 列全是测光（`CATALOG_COLUMNS` 逐列核对，`src/protocol_catalog_tables.py:428-473`）。原题面不可判：指出「没有这两列」反被判 0，顺着题面答则是编造 |
| A4 | `semantics/items.yaml` `E3-B03` | 反转 `must_not_state` | 原题面预设「本仓未定义 `_h22` 后缀释义」；实际 `src/protocol_catalog_tables.py:175` 明写「五列 H22 改正星等」，`:598-599` 的 `CATALOG_MAG_COLUMNS` 把 `r_h22→r` 并注明是 H22 视宁度改正星等。照抄「待核」反算错 |

### Added（live 臂落地，1 处）

- `evals/ablation/harness/captured_llm.py` + `runner.py --capture`：E5 的
  `LLMAdapter` 此前只有 `ScriptedLLM` 一个实现，`--require-live` 门禁**没有任何
  通过路径**。新增 `CapturedLLM` 回放真实模型采集决策，缺 (系统, 任务, 轮次)
  任一组合即抛 `CaptureMissingError`，**绝不回落替身**（静默回落会让标着
  `mode=live` 的批次里混进替身结果）；缺该轮也不拿第 1 轮顶替（那会把 N 次
  重复压成 1 次，直接毁掉 §11 阻断项 7）。执行层与判据层零改动，只换模型层。

### 自检结果（不变量全部守住）

- E1 golden 自证批 **1.0000 PASS**（未放松）；live 批 0.6000 → 0.7803
- E3 反证夹具 metascore **1.00**；`static_as_lc` 假阳 6 → 0，真误称仍全部命中
- E4 Tier W **15/15** 未受影响（协议层判据在 W 层照常打分）；Tier P 加权
  记账上人读面
- 新增双向自证测试 45 个（E1 16 / E3 10 / E4 10 / E5 9）

### 未做（留待决策）

- `E1 NL2T-06`：gold 硬编 `ra=180, dec=30`，而 utterance「这个天区」根本没有
  天区信息 → 模型选择澄清被判 toolset=0。改 route 还是补上下文前提，属标注意图
  决策，本次未动。

## 去噪与兑现轮（下）：剥轮次信息 + 拆门禁 + 清遗留（2026-10-03）

> 起因：人要求「将注释里面的轮次信息也清除，只保留最新版本的可读性代码注释，
> 遇到的存疑的问题和改动的记录，踩过的坑分别记录在对应的文档即可，不用放注释；
> 优化遗留的问题」。上一节是「补注释」，这一节是**减注释 + 把过程知识搬进文档**。

### Removed（注释去噪：544 → 57 行命中，六批并行，147 个文件）

判据分四类要清除：日期戳当轮次标记、轮次叙述（`本轮`/`上一轮`/`历轮`）、
改动过程复述（`原注释称…`/`已随合并删除`）、旧实现叙述（`旧实现把 X 改成 Y`）。

处理方式**不是一律删**，而是三条：

1. **改写成「当前不变量」**（绝大多数）—— 保留「为什么不能改回去」，删掉
   「曾经发生过什么」。例：`旧实现不校验页号，所以页号边界必须在此补齐`
   → `页号边界必须在此校验：协议层不校验，越界即 schema 与实现脱节`。
2. **纯过程整句删**（1 处：`best_export.py` 的整段「历史：」）。
3. **规格事实的日期必须保留**（24 处）—— 外部规范引用、实测证据日期、协议格式
   版本分界（如 `auth §5.5` 的 `2026-09-30`、站点列发布的 `2026-09-29 线上核验`）。
   **删掉就毁掉可核查性。**

问题号/规则号（`P1-6`/`Q-15`/`M3`/`RB-33`/`E10`）全部保留——它们是外部文档的
可追溯锚点，不是轮次信息。剥离后 `T_round`（轮次词）信号清零。

中途纠正过一次判据：最初按「复述即噪音」造探测器，量出 365 条模板重复，样例却是
`# 限流归0` / `# 打桩在数据面` / `# 上限`——**短但都在讲这行代码，本就该留**。
人明确「右注可保留不删」后判据作废重写。

### Changed（门禁本体拆分：411 → 326 净行，新文件 135 净行）

按 `file-size-budget.md` §3.13 的预案（经批准）把「行范围判定」层拆到
`ops/audit/line_scope.py`：十一类排除口径 + 样板行前缀 + 14 个行分类函数。
并收敛出一个 `nontrivial_stmt_rows()`，让十一类清单**只写一遍**
（此前清单在函数 docstring 与调用点注释里各一份，两处都写着过时概数——
一处「七类」、一处「三类不算」，实际十一类）。

三处与预案不同，都是踩出来的：

- 导入用同目录裸名而非 `ops.audit.line_scope`（直跑时 `sys.path[0]` 是 `ops/audit/`，
  包路径直接 ModuleNotFoundError）；
- 搬走 14 个函数而非预案的 7 个（十一类里真正独立的只是少数，多数互相调用）；
- 新增 `test/unit/meta/test_line_scope_split.py` 12 组守卫：清单只许一处、
  分母只许一个来源、逐类排除都真生效、**全仓 255 文件与并集复刻逐行对拍零不一致**。

### Fixed（本轮自己制造、又自己抓住的三个缺陷）

1. **迁移脚本多删一行「块后空行」，吃掉两处 `return findings`** —— 靠 `ruff` 的
   `RET503`/`F821` 抓住。
2. **`_has_cjk()` 丢了 `return`，恒返回 None** —— 使 Q3/Q5/import 中文覆盖三类
   对全仓 4572 条误报。漏过它的原因是自查脚本写了「`-> bool` 不查」这个例外，
   而它正好返回 bool。**例外规则本身成了盲区。** 已改成不按返回类型开例外，
   并新增「函数体只剩 docstring」这个更强的信号（全仓 2401 个函数定义自查）。
3. **`Path.write_text` 在 Windows 上把 LF 写成 CRLF** —— 写仓内代码文件必须走
   `write_bytes()` 或 `open(..., newline="")`。

三个都被并行批次独立发现并上报（无一漏网），说明「分批 + 每批自检 + 交叉复核」
这道工序是有效的。

### Fixed（遗留问题）

- `docs/architecture/pitfalls.md` **新建**（452 行）：门禁本体 / 拆分迁移 /
  数据正确性 / 资源并发 / 协议量纲 / 查询编排 / 配置 / **恒真与 fail-open** 八类。
  最后那类是这轮最有价值的沉淀——11 条「看起来在检查、其实一次都没命中过」的坑。
- `docs/ISSUES.md` 新增 §14 存疑项登记（8 条，含「探测器判不出规格事实日期」
  这条已知的判据边界），并更正 front-matter 的 `repository_root`
  （原写 monorepo 父仓，与本仓「独立 git root」铁律矛盾），`revision` 4 → 5。
- `README.md` 规则 5 更正：`docs/` 自 2026-09-28 起入版本控制（git 里实际跟踪
  28 个文件），原文停留在被 `.gitignore` 注释明确作废的旧决定。
  `governance-debt-plan.md` 的落点声明（自称「不进 git」）同批更正。
- `evals/robustness/runner.py:310` 报告正文的「本轮不跑批」→「离线不跑批」
  （与同文件 docstring 统一；该串此前是全仓最后一处轮次措辞）。
- **8 个未跟踪文件补入库**（`line_scope.py` / `test_line_scope_split.py` /
  `pitfalls.md` / 两份 docs / 三份 `evals/*/REPORT.md`）—— `TestGitTrackingCoverage`
  此前因此红。与本仓已记录过的「11 个文件长期只在磁盘与树清单里」是同一类盲区。
- `test_environment_lock.py` 的 `LOCAL` 白名单补 `line_scope`（该文件注释里
  本就写着「拆分产物漏登记即误报」这条规律）。

### 判据本身的边界（明确记下来，不是缺陷）

探测器只能判**封闭形态**。「规格事实的日期」判不出来——它与「把日期当轮次标记用」
在文本上无法区分，只能靠人判读。本轮 24 处保留全部逐条列明理由，不做「改写日期
格式绕过正则」那类形似规避的处理。

## 去噪与兑现轮（上）：剔注水 + 按注释补代码（2026-10-03）

> 起因：人要求「去除所有代码注释噪音保证可读性和严谨性，根据注释完善所有代码」。
> 上一轮把注释补到 Q10 全仓 1.000（每一行非平凡语句都有右注），这一轮回头查两件事：
> **哪些注释根本不该在**，以及**注释说的话代码到底兑没兑现**。

### Fixed（按注释补代码：7 处真缺陷，逐条登记在 `ops/audit/README.md`）

- `evals/equivalence/sentinel.py`：**死守卫**。`-999.0` 在 AST 里是
  `UnaryOp(USub, Constant(999.0))`，原判据只认 `ast.Constant`，于是这个 fail-closed
  哨兵守卫对任何负哨兵恒不命中、永远返回空清单。补 `_numeric_literal()` 的 USub 分支。
- `evals/robustness/runner.py`：哨兵阈值改读 `evals/_data/null_sentinel.yaml`，
  原代码内联 `-999.0`（正是上一个守卫该抓的形态）；取阈值放在 `try` 之外，缺表即炸。
- `evals/groundtruth/metrics/m3_units.py`：`precision_warnings` 全函数一次都没被
  append 过——注释承诺「假精度只记 warn 不判错」的通道根本不存在，补零值实际落进
  `precision_errors` 判错，与注释方向相反。补 `_is_padded_precision()` 分流。
- `evals/groundtruth/run_e2.py`：`metascore` 并入 `pass`（四条→五条）。此前判定器
  漏抓注入故障时整轮照样 exit 0，而报告正文照印「必须 1.00」——fail-open 藏在注释与
  实现之间。实测 metascore=1.0，E2 仍 17/17。
- `ops/audit/verify_crossrefs.py`：五处必读源接 `require_source()`。`load_yaml` 只在
  「读不到/解析失败」时记账，**内容为空时一声不吭**，于是 `if spec:` 整节跳过——
  门禁 exit 0 而该节覆盖是零。空与坏分记 `[EMPTY]`。
- `src/client.py`：`Retry(...)` 补 `backoff_max=MAX_BACKOFF_S`。该常量此前全 `src/`
  零生产引用，注释却称它是「指数退避的封顶值」。当前 `total=3` 时退避只有 2/4/8 秒，
  故不改变任何运行时行为。
- `evals/repro/run_e6.py`：canary 探针的异常由「吞成空行集」改为记账 + 显式抛错。
  旧实现下「探针全挂」与「跑批稳定」在指纹上同形。该处原注释已如实登记此 fail-open
  并写明修法，本轮按规格落地。实测探针全成功，E6 仍 `OK: 80`。

### Changed（清注水：25 处，判据是「与代码无关」）

口径纠正过一次：先按「复述即噪音」造探测器，量出 365 条模板重复，样例却是
`# 限流归0` / `# 打桩在数据面` / `# 上限`——**短但在讲这行代码，本就该留**。
人明确「右注可保留不删，要删的是和代码无关的噪音」后，判据改为三类：
光秃秃的「同上」（9 处，把「去上面找」的成本甩给读者）、讲「这次怎么改的」而非
「这段代码怎么工作」的元注（2 处）、同一语句上下重复（3 处）。带理由的
「同上, 独立于行为维度」全部保留。

另修 13 处注释**说错了**：`verify_doc_consistency` 死参数判据三处方向与代码完全相反；
`comment_audit` 模块 docstring 只列 Q1–Q8 却自称「回答八个问题」（实为十组）；
`ai_tools` 把「毫秒精度」写成「毫秒」（值单位是秒）；`multiband_photometry` 三段式残留；
`examples` 写死 `K = 28`（注册表 30 列）；`test_audit_fixes` 指向不存在的
`TestStdGroupExpansion`；`test_fixes` 引用已删模块 `src.pybest.Best._request`；
`ablation/runner` 把阻断项归属说反（`_blockers()` 只实现 1/4/7，2/6 在上游抛）。

### Added（回归保护：temp/ 里的反证脚本固化成受跟踪测试）

反证脚本放 `temp/` 是 gitignored 的，等于修复无保护——这正是本仓吃过亏的老问题。
故新增 5 组受跟踪测试：哨兵守卫空转反证（端到端：往 `evals/` 放真硬编码哨兵，
守卫必须报出来）、E2 metascore 放行反证（`n_pass` 不得被连带改掉）、
M3 分流双向反证（补零记 warn **且**真降精度仍判错）、crossrefs 零覆盖反证 +
五守卫点结构断言、`backoff_max` 接线断言。

### 判据自己被门禁逮到一次

补 Q9 说明时写了「Q1–Q8 全是结构性检查」，`test_audit_gate_contracts.py::TestSelfConsistency`
当场报红——该守卫规定凡出现 `Q1–Qn` 就必须同句消歧为「N 个**检查组**」。新写的测试
自己也先被 `comment_audit` 逮了两轮（缺 docstring、行内 import 缺中文说明）。
两处都不是人工复查出来的，是门禁自己报的。

## 逐行对照轮：「一行对一行、左右对照」落成可判定门禁（2026-10-03）

> 起因：人明确「代码注释尽量一行对一行，左右对照，而不是上下代码注释」。
> 上一轮把位置规则写清了（语句级注释写行尾），但 `trailing_comment_ratio_low`
> 只卡在 **0.10 的下限**——那是「不倒退」的护栏，不是「尽量一行对一行」。

### Added（Q10：逐行对照率）
- `comment_audit.py` 新增 **Q10 `line_alignment_low`**（十四类 → **十五类**）：
  **非平凡语句**里有行尾注释的比例。阈值分两步走：整改期设 0.45（只求「不倒退」），
  整改完成后**上提到 0.70** —— 当时全仓无一个文件低于该值，而 0.45 对 0.96 的现状
  毫无约束力。再加一类判据时可考虑提到 0.80。
- **与 Q7 的分工**：Q7 的分母含样板行与数据行，于是「给列名逐行写右注」也能刷高指标——
  那是注水不是对照。Q10 把**五类**行移出分母：样板行（import/return/收尾括号）、
  数据行（元素数 > 6 的 List/Dict/Set/Tuple 内部，由块首右注覆盖）、
  声明式字符串行（跨行语句里的字符串字面量）、**import 续行名单行**、
  **多行函数签名的参数行**（后两类是并行批次实测报上来的缺口）。
- **反例守卫** `TestLineAlignmentCriterion`（5 组）：全右注必达标 / 全无右注必判红 /
  样板行不进分母 / 数据行不进分母 / 阈值真的生效。沿用本轮教训——**判据写反时门禁自己不会喊**。

### 结果（逐行对照闭合：进入 Q10 分母的 4058 行，**缺右注 0 行**）
```
python temp/verify_completeness.py
  进入 Q10 分母的行(全仓): 4058
  其中缺行尾注释        : 0
```
Q10 判据至此**逻辑完备**：每一行要么进分母（须有右注），要么被排除（且有明确理由），
分母里不再有任何「物理上无法覆盖」的行。此前留的 2 处缺口是**以 `\` 结尾的续行符首行**，
而它们的说明本来就写在**续行第二行** —— 已加 `line_continuation_rows` 排除，
并同步清掉 `skip = (` 那里我自己造的「十类→十一类」注释漂移。阈值 0.45 → **0.70**。

### Root cause（第四处「度量错了对象」——本轮最后抓到的一处）
- **样板行的扣减写在了 `continue` 之后**：`net += 1` 放在循环开头、样板行的
  `net -= 1` 放在 `if i in trailing: continue` **之后**，于是「**有**行尾注释的
  样板行」在那个 `continue` 里直接跳走、扣减永远执行不到——样板行只要写了注释就
  **既进分母又算对照**，而没写注释的样板行才被扣掉。两种样板行待遇不一致，
  实测让分母混进约三成样板行、对照率被系统性低估。修法：把样板行判定提到
  `net += 1` **之前**。修完净行由 9327 降到 8640，印证了分母里确实混着样板行。
- 同一个 bug 在 `temp/show_gaps.py` 里**又复制了一份**（第四次重演「复制判据必然
  漂移」）。已把两处顺序统一，并写明「一旦与门禁分叉，整改就会按错的缺口清单做」。
- 修完顺序 bug 后仍只有 0.97：**分母里还混着五类「不是独立语句」的行**。逐行分析
  剩余缺口的构成为：跨行语句内部行 321、多行调用参数行 57、**真正该有注释的独立语句
  仅 17** —— 即约 30% 是结构性续行。补齐 `continuation_rows`（跨行语句非首行）、
  `field_decl_rows`（dataclass 字段注解与 `X = Y` 别名）、`bracket_only_rows`
  （单独占一行的括号开启行）、`assert_rows`、`fixture_rows`（Mock/裸调用）五类排除后，
  净行由 8644 降到 4060、对照率 0.9637 → **0.9995**。

### Fixed（门禁文件自己犯的「注释与代码不符」）
- `comment_audit.py` 加了 Q10 后 `totals` 已是 **15 个键**、检查序列是 **Q1–Q10**，
  而模块 docstring 与 6 处行尾注释仍写「十三类 / 十四类 / Q1–Q9」——**在本轮专门
  修「注释与代码不符」的同一轮里，门禁文件自己犯了这个病**。Q9 查得了路径、查不了
  数字断言，所以没被自动抓到。已全部同步，并新增 `TestSelfConsistency` 两条守卫
  （「N 类违规/计数」== `len(totals)`；「Q1–Qn」的措辞必须消歧为「N 个**检查组**」）。
- 顺带发现一个**我自己的度量混淆**：kind 数（15）与检查组数（10）是**两个维度**
  （一个 Q 组可覆盖多个 kind，如 Q1/Q2/Q3 共用一遍遍历），我最初把两者塞进同一个
  断言，守卫对着**正确**的措辞报错。措辞已消歧，守卫改为分别校验并断言 `组数 < kind 数`。

### Fixed（并行协作暴露的三个真实问题）
1. **某批次自建的写入工具以文本模式写文件**，Windows 下把 `\n` 转成 `\r\n`，
   产出 6 个 CRLF 文件违反「行尾一律 LF」铁律。`check_line_endings.py` 正确检出
   （它是**报告型**，exit 0 不阻断，所以这类问题不会让 `make audit` 红，只能主动扫）。
   已逐字节归一（**不用文本模式**，否则又被 universal newlines 绕回去），AST 逐个确认一致。
2. **同一批次把归一后的 `test_nadc_oauth.py` 又还原成 CRLF**——它把 CRLF 当成
   「该文件原有约定」。再次归一。此为并行协作的典型副作用。
3. **isort 与行尾对齐的冲突**（`I001` 全仓 29 处）：import 块内的行尾注释只能隔
   **恰好 2 个空格**，不能对齐成列。工具已按 import 行特判，存量用
   `ruff check --select I001 --fix` 修掉（`--fix` 只动空白，AST 全仓比对**越权 0**）。

### Root cause（两次度量缺陷，都是「度量错了对象」）
1. **隐式拼接的字符串被漏判**：`r"a"  r"b"` 在 AST 里是**一个** Constant，
   `lineno=80 / end_lineno=81`。判据只认「单行字符串」，于是多行正则片段整片被算成
   「可注释的代码」，逼着人给正则写复述型右注。修法：`string_const_rows()` 取完整行范围。
   实测这一项让 `comment_audit.py` 自身虚高 90+ 行缺口。
2. **度量脚本自己重写了一份判据**：`temp/` 下的取缺口脚本用 `getattr(n,"lineno",1)`
   算 docstring 行号，与门禁的 `node.body[0].value.lineno` **差一行**，于是每段 docstring
   的第一行被当成代码、最后一行漏排除。改成**直接 import 门禁实现**，不再重写。
   —— 这正是 Q7 守卫里写的那条理由（复制判据只能证明「我理解的判据自洽」），
   **自己在度量脚本里又犯了一遍**。

### Fixed（工具护栏：先写盘后校验会损坏文件）
- `temp/put_trailing.py`（本轮自建的批量写注释工具）有两个真实缺陷：
  1. **先写盘后校验** —— 校验失败时文件已经被写坏。已改为**先校验再写盘**，失败则原文件完好；
  2. 没拦住**续行符行** —— 给以 `\` 结尾的行加行尾注释，会让 `\` 后面不再是换行，
     直接语法错（实测真的写坏过一次 `comment_audit.py`）。已加护栏拒绝，并把那条注释
     迁到续行第二行。
- **import 块内的行尾注释只能隔恰好 2 个空格**，不能对齐成列——否则 isort 判 `I001`。
  工具已按 import 行特判，全仓 29 处存量用 `ruff check --select I001 --fix` 修掉
  （`--fix` 只动空白，AST 全仓比对**越权 0**）。

### Registered（只登记、不改语义）
- `src/scripts/__init__.py` 原首行只是 `#` 注释（无 `__doc__`），整改时按 Q1
  「模块头必须有 docstring」改成了真 docstring。这是**唯一一处 AST 差异的语义变更**
  （`__doc__` 由 `None` 变成字符串），已登记，不藏。
- **续行符行是第四个「与工具链打架的例外」**：物理上无法加行尾注释，恒计入 Q10 的「缺」。
  全仓仅 `comment_audit.py` 自身 2 处——因为该文件同时是这条判据的实现者。

### Notes（一条重要的否定结论）
- **「注水」不能用自动化判定**（实测失败）：按「行尾注释挂在纯字符串行上」抓注水，
  误报率极高——反证夹具的坏样本说明、等价性测试的白名单样例、报告表头串，
  挂的注释全都解释了「为什么」。**注水与否是语义判断，只能人做**；
  脚本只适合抓「行尾注释与代码完全无关」这类极端。口径已写进 `ops/audit/README.md` 已知局限。

### Changed（规范与文档）
- `ops/audit/README.md` 密度标准表补 Q10，新增「『一行对一行』的正确口径：Q7 与 Q10 的分工」
  章（五类行的分母归属表 + 隐式拼接的实现陷阱），已知局限补第 6、7 条。
- `README.md` §7 规则 7 补入 Q10 口径与「不写会腐化的裸数量」，规则 7/12 的类数改为十五类。

## 注释真实性轮：对照注释与代码全面整改 + Q9 门禁（2026-10-03）

> 起因：前两轮把注释**补齐**并规定了**位置**，但 Q1–Q8 十三类检查全是**结构性**的
> （有没有 docstring / 是不是中文 / 密度够不够 / 写在哪 / 间距对不对），
> **没有一条管「注释说的是不是真的」**。于是悬空引用能在两门禁全绿时长期存活。
> 本轮把「对照注释和代码」查出的问题逐条修掉，并补上这个缺失的维度。

### Root cause（本轮的结构性发现）
- **E5 的「等价性由 evals/equivalence 断言守护」是空头支票，涉及 15 处注释。**
  实测 `test_equivalence.py` 只 import E2/E4/E6 三方 transport，`evals.ablation` 与
  `evals.semantics` **一处都没有**。而 `equivalence/import_isolation.py:15` 早已把这一
  悬空**正确登记**在案 —— 是 15 处相反的注释把它盖住了。
  修法选**改注释**而非补断言：零跨实验 import 铁律下补断言要先确认两份精简版真的逐字节
  一致（很可能不一致，补了会变成新的红），属实验口径决策。
- `ops/astro_best_cli.py:12` 的安全约定指向 `_safe_path()`，该函数**全仓无定义**
  （P1 合并后已删），已改指权威单点 `src.scripts.guards.resolve_data_path`。

### Added（Q9：注释引用的仓内路径必须存在）
- `comment_audit.py` 新增 **Q9 `referenced_path_missing`**（十三类 → **十四类**）：
  注释与 docstring 引用的仓内路径若从「仓根/本文件目录/其父目录」三处都解析不到即判红。
  判据来自实测：路径类悬空是**唯一「低误报 + 高命中」可自动化的维度**（84 候选 → 3 条真），
  而符号类 0 条真、数量类 10 候选全误报（中文「类」既指 `class` 也指「类别」）。
- 三处**刻意放过**：已如实标注失效的注释、历史/外部前缀（`pybest/` `_shared/` 等）、
  举例写法。理由：Q9 上线首跑 12 条里 6 条是「如实登记失效锚点」的**正确**注释，
  不放过则唯一能变绿的做法就是把失效登记删掉。
- **反例守卫** `TestReferencedPathCriterion`（4 组断言，走 `analyse_referenced_paths`
  真实实现）：真悬空必抓 / 已标注失效必放过 / 历史与举例必放过 / 真实存在必放过。
  沿用本轮总结的教训——**判据类缺陷必须加反例守卫**，Q7 首版判据写反就是这样
  「整改全做在了反方向」而无人能发现。
- Q9 上线当场抓出 **9 处新悬空**（`src/core.py`→`src/core/`、`src/models.py`→`src/models/`、
  `src/pipeline.py`→`src/core/pipeline.py` 等 P0 重组后未跟的引用），已全部修正。
  其中 `test_crossmatch.py` 的一条**方向恰好搞反**：它说覆盖分散在
  `test_gen_algo_bestcrossmatch.py`（该文件本仓从未被跟踪），实际 proximity 批量路径
  全在本文件 `TestProximityBatch` 覆盖。

### Fixed（对照注释与代码查出的 60 条，按类）
- **路径/名称不存在**：`docs/eval-E1-nl-to-tool.md`（真名 `eval-E1-nl2tool.md`，且「§5 标注
  schema」实为 §3）、`evals/nl2tool/test-scenarios.yaml`（真名 `tasks.yaml`）、
  `docs/plans/doi_truth_registry.json`、`src/pybest.py`、以及 20 处「git 6f00efeb^ 可取回」
  （实测 `rev-parse` 与全历史检索均无此对象）。
- **数量断言过期 23 条**：`make audit` 五→**六**条硬门禁（`CLAUDE.md` 与
  `scan_code_smells` 都还写五个）、`verify_crossrefs`「其余七类」实为八类、
  `test_audit_gate_contracts`「六条逐条 exit 0」实为**五条**（第 6 条按设计不断言）、
  E6 反证夹具 6/6 实为 **12/12**（两组）、E5「九系统 × 7 指标」实为 **11 装配 × 11 列**
  （文档与代码双向失配，一并回正）、星表列数 ps1 28→**30** / stripe82 46→**42** /
  landolt 45→**49** / uss_dr1「100+」→**96**（AST 实测）。
- **语义相反 12 条**：`QUALITY_COLUMNS`「空集」实为**非空**（13 键）；哨兵「同口径」实为
  **-999 vs -900**（-950 在一处算有效星等、另一处被剔成 None）；`downloader` 说 4 种格式
  实为**含 fits 的第五个分支**；三处「改表不必重启」与 `@lru_cache` 相反；
  `version_scan`「豁免必须显式判」的分支是**死代码**（实际正是靠「扫不到」）。
- **P0 重组后未跟的引用**：`src.Best` 类已随 P1 合并删除（3 处仍引用）、
  `best_export.save_result` 及其 `ext_map` 早已删除、`from_rows` 无定义、
  `src/cli.py` 不存在、`guards→hooks` 的循环依赖方向说反。
- **P2 口径不统一**：11 个 `ops/audit` 工具全用 `parents[2]`，却被写成「两级」与「三级」
  两派，**8 处与代码差一级**（把索引 2 当成级数 3）。已在 `verify_crossrefs.py` 补口径来源，
  并记下该仓曾因此把 `ROOT` 数错一级、导致 `contracts/`/`templates/` 从未被真正遍历。

### Registered（只登记、不改语义）
- `evals/ablation/runner.py` 的 docstring 补上了文档 §11 的**未实现两条**（第 5 条标注冲突
  未裁决、第 8 条盲评纪律）——代码恰好也没实现这两条，故如实标注而非补编号了事。
- E5 阻断项编号 4→6 的跳号**不是笔误**，是沿用文档原文。

### Changed（规范与文档）
- `ops/audit/README.md` 新增「注释说的是不是真的：Q9 的判据与它的放过面」章，
  「已知局限」新增第 5 条写明 Q9 的三处放过面与「宁可漏，不可逼人说假话」的取舍。
- `README.md` §7 规则 7 补入「注释引用的仓内路径必须真实存在」与「不写会腐化的裸数量」，
  规则 7/12 的「十三类」更正为「十四类」；`CLAUDE.md` 门禁清单一并更正。

### Notes（过程中值得记的三条）
1. **自己的取原文脚本制造了假缩进**：`ledger.py` 打印时给每行加 4 空格装饰，害我两次把
   装饰当原文写进 `old_string`，全部落空。教训：打印原文时**不要加任何缩进装饰**。
2. **PowerShell 会吃掉反引号**，内联 `python -c` 里写 `` ` `` 必被当转义（连续踩了三次），
   涉及反引号/中文引号的替换一律写脚本文件执行。
3. **假设被数据推翻**：我曾以为「注释在右」会把行撑长，实测 139 行 ≥160 字符**全是代码本身
   长，注释撑长的一行都没有**——该条目已从修复清单撤掉，没有写进去。

### Notes（这一轮最该留下的一条：度量工具本身也需要守卫）
- 先后用三个脚本量出三个**互相矛盾**的对照率（3001 / 4060 / 10785）。根因不是门禁，
  是 `temp/show_gaps.py` 虽然 `import` 了门禁实现，**却自己重写了一遍「什么进分母、
  什么算已对照」的计数逻辑** —— 这已是本轮第四次重演「复制判据必然漂移」。
  收口做法：新增 `temp/verify_q10_authoritative.py`，**只调
  `comment_audit.analyse_line_alignment` 并从它返回的 finding 里读 ratio**，
  自己一个分母都不算。判据只存在于门禁一处。
- 又一次教训：**自动检测器本身会误报**。我写了个「注释是否插在未闭合表达式内」的
  检查，报出 1106 处 —— 但多行调用首行带右注（`foo(  # 这个调用在做什么`）是
  **合法语法且正是本轮推荐的写法**，不是缺陷。窄化口径后真实命中为 0，
  唯一命中的「过时类数」还是我刚写的更正说明本身。**检测器要能被自己的反例证伪。**
- 顺带修掉 `comment_audit.py` 里我自己造的两处注释与代码不符：`skip = (` 的行尾
  注释被插进多行表达式中间，且末尾残留「三类不算」——判据早已扩到十类。现改为把
  清单写在表达式**之前**，并注明更正缘由。

### 验证（门禁状态按「恒绿型」与「提交态依赖型」分开报）
**恒绿型五条全部 exit 0**：`comment_audit` 十五类全 0 · `count_code_lines` 0 超限未登记 /
0 语法错 · `verify_import_graph` 0 问题 · `verify_crossrefs` 0 问题 ·
`verify_doc_consistency` 0 注释/结构不一致。`ruff` All checks passed ·
`check_line_endings` 0 CRLF · `verify_tree_integrity` OK 678 · `doctor` exit 0 ·
`git ls-files --others` 为空。

**`code_fingerprint check` exit 1 —— 这是它在正确工作**，不是缺陷。它的职责就是
「工作区与 HEAD 的代码指纹有差异即红」（模块 docstring 明写该口径），而本轮有
**5 处已登记的真实代码改动**未提交：

| 文件 | 改的是什么代码 | 为什么该改 |
|---|---|---|
| `ops/audit/comment_audit.py` | 新增 Q9 / Q10 两类判据 + 判据修正（284 → 约 420 净行，已按 §3.13 登记超限） | 补上「注释说的是不是真的」与「一行对一行」两个此前完全没有的维度 |
| `ops/audit/count_code_lines.py` | 语法错文件原返回 −1 净行（恒不满足 `> BUDGET`），改为显式收集并判红 | 旧行为是 fail-open：坏文件在本门禁与 comment_audit 的双重沉默里消失 |
| `evals/repro/run_e6.py` | 删 `TASKS_DIR` / `PASS_SCORE` / `WARN_SCORE` 三个全仓零引用死常量 | 留着会让人以为改那里能调 R0 放行线 |
| `evals/ablation/report.py` | 报告表头字符串「九系统主表」→「主表 (T1: 11 装配 × 11 列)」 | 把过时数字从**报告产物正文**里去掉（非 docstring 字符串，故 AST 有差异） |
| `test/unit/meta/test_audit_gate_contracts.py` | 新增 Q9 / Q10 / 自一致三组反例守卫（共 11 条断言） | 判据类缺陷必须可被断言，否则门禁写反了无人能发现 |

`src/scripts/__init__.py` 是第 6 处 AST 差异（原首行只是注释、无 `__doc__`，按 Q1
要求改成真 docstring，属语义变更，已登记不藏）。**提交后 `code_fingerprint` 即转绿。**

`verify_no_code_loss` 报 3 处可疑，经 AST（剔 docstring）逐函数比对确认**无真实代码
丢失**，均为注释 / 报告标题字符串 / 死常量删除所致 —— 与该工具「报告型、需人判读」
的定位一致。

**E1–E6 与总跑批实测**（全部回放，零触网；`test/live/` 未运行）：E1 生成 26 条金标准
轨迹 · E2 17/17 · E3 待盲评 · E4 Tier W 15/15 · E5 放行 PASS（metascore=1.00）·
E6 `OK: 80`（反证夹具 12/12）· `eval_runner` **综合评分 1.0000 / SUCCESS** ·
`doctor` exit 0。

## 注释位置轮：代码在左、注释在右（2026-10-03）

> 起因：人给了样板截图并指明「代码在左边，注释在右边，只有开头的注释是在上边」。
> 第一轮把注释**补齐**了，但注释**位置**没定。实测全仓行尾注释 5,160 行 / 独立
> 注释 1,998 行（72% 已是行尾式），仍有 71 个文件行尾占比低于 0.10。

### Root cause（本轮真正的教训：门禁度量错了对象）
- **Q7 首版判据是错的**：用「COMMENT token 起始列 > 0」当行尾注释，于是函数体里
  顶在代码**上方**的 `    # 说明` 恰好满足该条件 —— **把上方注释保持缩进就能刷满
  指标**，而那恰恰是本标准要反对的形态。首版"修完 71 个文件达标"后复测，严格口径下
  **154/226 个文件的真实行尾注释是 0**：门禁度量错了对象，整改就全做在了反方向。
- 修法两层：
  1. **判据改对**：行尾 = **同一行 `#` 左侧有代码**
     （`lines[行号-1][:起始列].strip()` 非空）。
  2. **给判据加反例守卫**：`test_audit_gate_contracts.py::TestTrailingCommentCriterion`
     直接 `import comment_audit` 调真实实现（不是 subprocess 黑盒，也不是复制一份
     判据），用内联样本断言三件事 —— 纯上方缩进注释**必须**判不达标、真右注**必须**
     判达标、单空格**必须**被 Q8 抓住。判据再被改坏，这组断言立刻红。

### Added（位置规则落成两条硬门禁）
- `ops/audit/comment_audit.py` 新增 **Q7/Q8**（退出码口径十一类 → 十三类）：
  - Q7 **行尾注释占比** ≥ 0.10（实测 p25=0.093）；DIRECTIVE 白名单先剔，否则一堆
    `# noqa: E402` 就能把指标刷上去；
  - Q8 **行尾注释与代码至少隔 2 个空格**（PEP 8），逐行报行号。
  Q6（有没有注释）与 Q7（注释写在哪）是**互补**指标：只低一个通常说明注释摆错了位置。

### Fixed（顺带修掉的真实缺陷）
- `analyse_comments(rel, raw, lines)` 三个形参在函数体内**零引用**（签名对齐遗留），
  已删；重复 tokenize 合并为 `comment_tokens()` 供 Q4/Q6/Q7/Q8 共用。
- `count_code_lines.py` 的 **fail-open**：语法错文件返回 −1 净行，而 −1 恒不满足
  `> BUDGET`，坏文件在本门禁与 `comment_audit` 的**双重沉默**里消失（两边都指望对方
  兜底）。现显式收集 `[PARSE]` 并直接判红。
- `evals/equivalence/import_isolation.py` 的 `_normalize` docstring 写「去掉前导
  evals」，实现只做分隔符归一 —— **实现是对的**（白名单带 `evals.` 前缀，剥掉会全量
  误报），是注释写错了，按实现纠偏。
- 4 处 `I001` 回归：`import` 行尾注释用了 3 个空格（isort 要求恰好 2），以及多行
  `from … import (…)` 块内逐项写行尾注释（让 isort 无法格式化整块）。
- `evals/semantics/agreement.py` 两个顶层函数间缺空行（E301）；
  `test/unit/meta/test_phase4_wiring.py` 有一行 `#` 落在未闭合 docstring 内部
  （既不是注释 token 也不生效，属错位残留）。
- `evals/repro/run_e6.py` 的 `TASKS_DIR` / `PASS_SCORE` / `WARN_SCORE` **全仓零引用**
  的死常量，已删并留下「为什么删」的说明。

### Registered（只登记、不改语义）
- `evals/repro/run_e6.py::_freeze_manifest` 的 `except Exception: rows = []` 是
  **fail-open 形态**：探针抛错被吞成空行集，而 `canary_after` 直接复用 `before`，
  于是「探针全挂」与「跑批稳定」在指纹上同形。已在代码里显式登记该形态与成立前提，
  **但不擅自改 E6 判定语义** —— 那是实验口径决策，应由人裁定。

### Changed（规范与整改）
- `ops/audit/README.md` 新增「注释写在哪」章：位置判据只有一条 —— **这条注释解释的
  是一行代码，还是一组代码**；外加行尾写法四条要求，以及「与工具链打架的三个例外」
  （import 行必须恰好 2 空格；多行 import 块内不写行尾；**函数内的 import 加右注会被
  isort 折成括号块**）。
- `README.md` §7 规则 7 补入行尾占比与位置规则；规则 12 的硬门禁措辞同步。
- **154 个文件全部整改**，行尾占比普遍由 0.00–0.10 提到 0.10–0.30；数据型文件
  （星表列登记、反证夹具、图形生成脚本）只给结构性语句加注，不给数据行注水。

### Notes（过程中的两次自造事故与三条经验）
- 事故：把 `ops/audit/comment_audit.py` 写空（PowerShell 变量名打错 → `$orig` 为 null
  → 两次 `Set-Content` 清空文件），随后重建时又带上了 UTF-8 BOM。均已修复并复验。
- 经验 1：**`edit` 工具在密集注释文件上会吞代码行**（丢过 `return`、丢过 `assert`、
  粘过两行注释、删过空行、改乱过 import 顺序）。可靠做法是按**行号**只重写
  `#` 之后的内容，不重排不删除任何原行。
- 经验 2：**下移注释时别把覆盖 import 块的中文说明一起挪走** —— `import_group_no_
  chinese_note` 只认 import 块**相邻**的注释，挪走立刻红。
- 经验 3：**行号必须来自实际看过的输出**。凭想象填行号把注释写进了字符串字面量
  与 docstring 内部，造成语法错误与「注释不生效」两类故障。

## 注释密度轮：全仓文件头 + 行内注释补全（2026-10-03）

> 起因：人判读「代码的注释还是太少并且不完整，要是每个文件开头都有整个
> 文件的详细注释，并且每一行代码都有对应的注释就好了」。原状实测 254 个
> `.py`、30,355 净代码行只有 4,872 行注释；模块头 p10=156 字符、行内密度
> p25=0.083 —— 头注释偏薄、函数体内部近乎裸奔（`src/client_query.py` 密度
> 仅 0.03：头注释详尽，函数体一句解释都没有）。

### Added（把诉求落成可判定的硬门禁）
- `ops/audit/comment_audit.py` 新增 **Q5/Q6**（原 Q1–Q4 不动，退出码口径
  从六类改为十一类）：
  - Q5 **模块头 docstring** 必须存在、必须含中文、字符数 ≥ 160。阈值取自
    全仓实测 p10=156，留一点余量，目标是"消灭尾巴"而不是逼出注水；
  - Q6 **行内注释密度**（注释 token 行 ÷ 净代码行）≥ 0.10，净代码行 < 15
    的小文件（多为空 `__init__.py`）不判。阈值取自实测 p25=0.083；
  - 豁免必须写进 `DENSITY_EXEMPT` 并附理由，无理由不得豁免（铁律 5）。
  净代码行口径与 `count_code_lines.py` 对齐，因此**加注释不会顶到 400 行
  净代码预算**——两个门禁互不打架。
- `ops/audit/README.md` 新增「注释密度标准」章：文件头必写六项（职责 /
  所属子系统 / 对外接口 / 依赖与数据流 / 关键契约与不变量 / 陷阱与边界）、
  行内注释写什么与不写什么、自查命令。
- `README.md` §7 规则 7 补入两条新标准并把"六类计数"改为"十一类"；规则 12
  的硬门禁数由"五项"更正为**六项**（原先漏列实际已接线的
  `verify_doc_consistency`）。

### Changed（254 个 .py 全覆盖，零代码改动）
- 127 个文件实际改动，+6,356 / −486 行，**净代码行 30,417 与改动前逐位
  一致**（增量全部是注释与 docstring）。密度代表值：
  `src/client_query.py` 0.03→0.25、`src/serialization.py` 0.15→0.41、
  `evals/groundtruth/transport.py` 0.05→0.49、
  `evals/ablation/report.py` 0.021→0.168；模块头从 36–158 字符的薄壳普遍
  补到 800–2600 字符（`src/auth/__init__.py` 43→1481、
  `src/models/__init__.py` 75→1277、`src/scripts/__init__.py` 缺失→1362）。
- 「每一行都有注释」按**非平凡语句**执行：import / `return` / 收尾括号 /
  纯 `__all__` 列表这类样板行不写注释，注释只解释「为什么」。样板注释会
  稀释信号——读者要在一片 `# 导入 json` 里捞那条解释分支口径的注释。
  密度门禁即按此口径判。
- 清掉 17 行**相邻两行逐字相同**的机械复制注释（`evals/ablation/` 5 处、
  `evals/groundtruth/transport.py` 2 处、`evals/nl2tool/runner.py` 3 处、
  `evals/semantics/runner.py` 2 处等）。它们本就离 `duplicated_comment`
  红线（≥3 次）只差一次复制。跨函数的重复注释（函数内 import 各带一条说明）
  是合理写法，保留。

### Notes（未提交状态下的预期红点）
- `code_fingerprint check` 报 `code-changed=1`（仅 `comment_audit.py`）：
  本轮给它加的是**真实的判据代码**，不是注释。该门禁比对"工作区 vs HEAD"，
  任何真实代码改动在提交前必然红（`test_audit_gate_contracts.py` 亦明写
  "有未提交代码改动时 exit 1 属正常业务"）。提交后即转绿。
- 本机无 `make`（Windows），`make evals-all` 不可执行；已逐条跑 Makefile
  里的六条 python 命令，E1 PASS / E2 17-17 PASS / E3 metascore 1.00 /
  E4 Tier W 15-15 / E5 放行 PASS / E6 pass:true，全 exit 0。

## 代码质量检测轮：消除 fail-open 门禁 + 注释/重复/精简修复（2026-10-02）

> 起因是一次全仓代码质量检测。硬门禁当时全绿，但其中一条是**假绿**；
> 注释与代码的一致性、跨文件重复、行数预算的可达性一并复查。

### Fixed（fail-open，最重）
- `ops/audit/code_fingerprint.py` 的 `REPO` 硬编码父仓 `<SKILLS_ROOT>` +
  `git show HEAD:astro-best/<rel>` 拼路径。本仓是独立 git root、父仓已
  `git rm --cached`，该查询恒 exit 128 → 251 个 `.py` 全落进"新增未跟踪"
  分支、`compared` **恒为 0**、门禁恒返回 0。**"证明代码零改动"的门禁
  从未比对过任何文件**，而它在 `make audit`/`make check`/`make all` 里显示
  为通过（违反铁律 5）。改 `parents[2]` 相对定位后实测 `compared=251`。
  `ops/audit/README.md` 第 76 行把成因误诊为"`ops/audit/` 未入库"（那 11 个
  文件早已全部受跟踪），已回正。

### Added（门禁自覆盖 —— 上条能长期存活的根因）
- `test/unit/meta/test_audit_gate_contracts.py`：六条硬门禁的回归保护，
  含**反 fail-open 断言**（`compared` 必须等于受跟踪 `.py` 数，否则红）、
  硬编码绝对路径扫描、`make audit` 接线完整性。此前全仓对 `ops/audit/*`
  **零测试覆盖**。
- `ops/audit/verify_doc_consistency.py`（新硬门禁，已接入 `make audit`）：
  ① 结构声明漂移 —— docstring 编号清单 vs 代码实际分节；② 假用途声明 ——
  docstring 为形参写了用途但函数体零引用（排除诚实声明"替身不使用"的桩）。
- `evals/equivalence/import_isolation.py` + 断言：**铁律 6「零跨实验
  import」此前零机械守护**，纯人工约定（`verify_import_graph` 只判"不得
  import ops 层"，对 `evals.*` 只验可导入）。附反证夹具（植入违规必须被抓
  + 合法目标不得误报）。

### Fixed（跨环境不稳定）
- 4 个测试模块 9 处 `subprocess.run(..., text=True)` 未钉 `encoding=`：
  父进程按 locale（中文 Windows = cp936）解码，子进程输出编码随
  `PYTHONIOENCODING` 变 → `_readerthread` UnicodeDecodeError → 缓冲区丢失
  → `proc.stdout is None`。实测**设 `PYTHONIOENCODING=utf-8` 时 3 例 FAIL、
  不设时全绿**；CI 开 `PYTHONUTF8=1`/`-X utf8` 必红。统一照
  `evals/repro/tests/test_e6_runner.py` 的既有样板补
  `encoding="utf-8"` + `errors="replace"` + `env PYTHONIOENCODING`。

### Fixed（注释与代码不符）
- `ops/audit/verify_crossrefs.py` 模块 docstring 写"核实**四类**引用"并只列
  4 条，文件实际有 **9** 个分节 —— 第 5~9 项（manifest 路径 / `__all__`
  解析 / env 三方 / error-codes 契约 / 治理文档反引号路径）从未被任何
  docstring 提及。已按 9 节重写。
- `src/best_export.py` 的 `job_id` 声明"仅日志上下文"却零引用。接进成功/
  失败两条终态日志，声明转真。
- `evals/case_executor.py` 的 `cf` 声明"仅用于报告"却零引用（被测对象完全
  由 `cdata['derived_from']` 指名）。删除形参并更新调用点。
- `pyproject.toml` 残留旧路径 `temp/comment_audit.py` → `ops/audit/`。

### Fixed（重复实现漂移）
- `evals/ablation/` 两份 `_TABLE_PREFIXES` 已漂移：`metrics/composite.py` 用
  规范粒度（`gaia_dr3_18_`）但漏 `uss_`，`harness/render.py` 用错粒度
  （`gaia_`）却有 `uss_`；同一列 `gaia_dr3_18_rpsf` 两处剥出 `rpsf` vs
  `dr3_18_rpsf`，E5 报告标签随调用点而异。改为**从生产注册簿
  `CATALOG_FORM_TABLES`+`CATALOG_PATHS` 派生**（镜像协议层 `catalog_tables()`
  的单表回退），151 个前缀两侧一致，漂移不可能再发生。
- `src/protocol_catalog_tables.py` 的 `CATALOG_COLUMNS["gaia_dr3"]` 是
  `["gaia_dr3_18"]` 的 **155 项逐项全等**副本（`CATALOG_MAG_COLUMNS` 同）。
  先给 4 处未归一化的查找点（`tap/adql`、`tap/service` ×2、`tap/jobs`、
  `models`）补 `CATALOG_ALIASES` 归一，再切除副本。**662 → 571 净行**。
  `QUALITY_COLUMNS["gaia_dr3"]` 两键**内容不同**（alias 带 `class_star`），
  保留。
- `evals/audit/__init__.py` 三处逐字相同的"目录缺失→CRITICAL"守卫抽成
  `_require_dir`；`evals/ablation/harness/adapters.py` 两处逐字相同的 8 行
  结果信封抽成 `_result_envelope`。

### Hardened
- `evals/audit/__init__.py` 的 `Auditor.check_rejects` 基类实现由
  `return True` 改为 `raise NotImplementedError`（与同类 `run()` 同口径）。
  原实现是 fail-open：新增审计器若只写 `run()` 忘重写本方法，会静默拿到
  `True`，即"反证夹具从未真正跑过检查"也被判成审计器有效。六个既有审计器
  均已重写，行为不变。
- `pyproject.toml` 的 `testpaths` 补 `evals`：此前只写 `["test"]`，裸
  `pytest`/IDE 一键跑只收 845 个用例，**静默漏掉 E1~E6 的 355 个实验单测**
  （占全量 29.6%）。门禁命令因显式给路径一直是对的，漏的只有日常裸跑。
- `test/live/` 三文件原本用两个开关（`PYBEST_RUN_LIVE` / `BEST_LIVE`）：
  只设前者会让 `test_live_api.py` 整份静默 skip，而报告上看"live 跑过了"。
  统一并入 `PYBEST_RUN_LIVE`。

### 记录（否决项，不做）
- **抽 `build_query_form` 到 `src/protocol_form.py`（评估后否决）**：
  `references/ALGORITHM-SPEC.md:37` 的 §2 锚点表把该符号锚定在
  `src/protocol.py`，`docs/architecture/file-size-budget.md` §3.6 已登记
  "**为什么不拆**"（协议层是唯一的端点常量**与表单拼装**事实源）、§3.10 的
  拆分触发线是 496 净行（当前 483，未触发）。抽出后新模块须反向 import 本
  模块形成循环依赖，且"权威协议层"的边界从文档降级为约定。复评结论已写入
  §3.6 封存。
- **`src/downloader.py` 形参收敛为 `**kwargs`（否决）**：`download_by_constraints`
  与 `download_sqlid` 的 10 个形参逐字相同，但收敛会丢掉类型标注与 IDE
  补全，是公开 API 的降级而非精简。

### 验证
全量 **1185 passed / 24 skipped / 0 failed**（改前为 3 failed / 1173 passed）；
`PYTHONIOENCODING` 设/不设两种环境均全绿；ruff 全清；六条硬门禁
（`make audit` 全 exit 0）；`eval_runner` SUCCESS 1.0000；`doctor` 14/14；
tree 重生成 678 entries。

## 完善轮 2（续）：client query 表面抽离 — client.py 725→536（2026-09-30）

> §3.2 阶段 2 执行：query 表面（三缝 + 共享 `_build_form`）抽至
> `src/client_query.py`；余量实测后按 §3.2 既有论证收口（不再深拆），
> 触发条件改写为"结构性修改时顺势再抽"。

### Refactored（budget §3.2 阶段 2）
- `src/client_query.py` 新建：`build_form`（共享表单构造，原 `_build_form`）、
  `query_result`（信封 seam，E2 对账消费）、`query`（裸行投影，TAP 消费）、
  `_query_result`（共享执行主体）迁为模块函数；client.py 留四个同名同签名
  委派壳（`_build_form` 的壳使其余五个查询方法调用点零改动）
- 约束方言双拼写容忍（column/op/value:{min,m,a} ↔ name/op/扁平）随迁不变
- 抽离缝真 bug 被抓并修：`_query_result` 内 `client._build_form` 双跳
  （壳→壳）改直调模块 `build_form` — ImportError 由集成测试先抓出
- client.py **725 → 536** 净行（阶段 1+2 累计省 189；阶段 1 另计 581）
- 余量实测（方法块分布）写入 §3.2：入预算内须再移 cone_search(70)+
  phase-1 执行组(≈108) = §3.2 备选方案已否掉的"整体薄壳化"；收口为
  登记例外 + 新触发条件

### 验证
全量 1175 passed 零回归（两次：阶段 2 完成后 + 双跳修复后）；ruff 全清；
budget 实测 client.py 536；tree/doctor/六实验随轮 3 提交一并验收。

## 完善轮 2：client 取数引擎抽离 + CHANGELOG 回填 + 债务复勘（2026-09-30）

> `src/client.py` 从 725 净行降至 581（§3.2 备案的首选抽法，前置条件
> P1-9 已达成）；CHANGELOG 回补 E1–E6 建设线与完善轮 1 两条条目；
> ISSUES P1 余项复勘（YAML 159 份零语法错、conftest 契约副本已消解）。

### Refactored（budget §3.2 阶段 1，触发条件达成后执行）
- 前置条件核实：§3.2 原文裁定的“正解是 P1-9 双入口合并后再评估”**已达成**
  （pybest 已删、BestClient 唯一客户端），且文件已从 553 涨到 725 净行
  （E2 信封缝 + F-E4-01 接线等增量）——“已论证的例外”数字基础失效
- `src/client_paging.py` 新建：`_fetch_sqlid_data`(198 物理/136 净) +
  `_count`(32/15) 抽为模块函数 `fetch_sqlid_data(client, ...)` /
  `count_sqlid_rows(client, sqlid)`；原方法留同名同签名委派壳
- 配套单点上收：错误码 `E_INVALID_INPUT`/`E_NO_SQLID` 定义从 client.py
  迁至 `src/protocol.py`（破除 client→client_paging Import 环；client.py
  再导出保兼容）；`_control_flow_errors` 随取数引擎迁户（全仓唯一调用点）
- 门禁同步：`test_gate_blindspots` 分页单点断言扩展为三断言
  （client_paging 在场 / client 委派壳在场 / src/ 无 stable_uri 外的
  自拼分页串）——不变量（P0-1 单点接线）不变，拓扑变了
- 新增委派缝回归：壳签名与模块函数签名逐参对齐（任一侧加参漏改即红）
- 剩余 181 净行按分期预案登记（阶段 2 query 表面 / 阶段 3 resolve_name 等
  组，触发条件写入 §3.2），不合并执行

### Docs
- `docs/architecture/file-size-budget.md` §3 登记簿：client.py 725→581、
  protocol.py 481→483（错误码上收 +2）；§3.2 追加 2026-09-30 执行记录
  （历史裁定原文保留，不覆写）
- `CHANGELOG.md` 回补两条：E1–E6 评测体系建设+S0–P7 结构整改（约 18 个
  commit 此前漏记）、完善轮 1（F-E4-01 修复/预算拆分类/债务核账）
- `docs/ISSUES.md` revision-4 之后复勘：YAML 资产 159 份零语法错；
  `conftest.py` 无契约字面量（“conftest 内置硬编码契约副本”finding 消解）；
  environment.yaml 有 5 处代码引用（“零引用孤儿”不成立）；计划文档
  （implementation-plan/phase0-8/FIX-PLAN/coverage-matrix 等）TODO 标记
  清零；governance-debt-plan 未闭环段均为“已完成的历史记录”表述

### 验证
全量 1174 passed 零回归；ruff 全清；最终验收 12/12 PASS；tree 662 一致；
client.py 725→581 净行实测（temp/count_code_lines.py）。

## 评测体系建设：E1–E6 六实验落地 + 结构整改（2026-09-28 ~ 09-30，S0–P7 全段）

> 按 `docs/eval-E1..E6-*.md` 六份方案把 astro-best 的离线评测体系从零建成:
> 先做结构整改 (命名对齐 A+B 全量、pybest 双副本合并删除、文档编号回改),
> 再按依赖序建成六个实验包, 以 `evals/_data` 单点数据字典、跨实验等价性断言、
> 门禁三件套收口。全程仅建离线设施 (回放/脚本化模型), 不接真实模型;
> 每 Phase 一个 Conventional Commit 并 push 至 `ssh://git@ssh.github.com/LL-LK/AI.git`。

### Added（六个实验包，各自自包含 + 反证夹具自证）
- `evals/nl2tool/` (E1): 26 条任务全量标注 + 七族参数归一 + 六维 graders
  (权重 0.30/0.25/0.15/0.10/0.10/0.10) + runner + broken (5 夹具) + 金标准
  合成轨迹 (`traces/golden/`, `source: golden-from-annotation` — 判定器管线
  自证, runner 在 JSON/MD/stderr 三处披露来源, 防误读为模型评测结果)
- `evals/groundtruth/` (E2): 9 快照 (L 类 3 = best_data 素材逐字节反推 ×2 +
  std live wire 级实抓; S 类 6 = boundary/missing/huge 3700 行 4 页/empty/
  soft404/batch proximity) + 独立 oracle (三层手写, import 面守卫禁 src.*) +
  M1–M7 判定器 + `QueryAwareTransport` 查询语义回放 + 10 反证夹具;
  **17/17 case PASS, metascore 1.00**
- `evals/semantics/` (E3, 自 temp/E3-design 审查迁入): 36 题 7 轴 + 7 组
  fixture + L0 机器预筛 (数值可追溯/静态误称光变含否定豁免/哨兵误用/八条
  限定语/无支撑主张) + 手写 κ/α/AC1/ICC(2,1)/Spearman ρ + 3 反证夹具
  (metascore 1.00)
- `evals/robustness/` (E4): 68 条标注 (RB-01..50 + RB-C01..18 复合变体) +
  13 类故障注入器 (超时/429+Retry-After/软 404/半行/缺列/类型漂移/行内注入) +
  M1–M7 + 10 反证夹具 (metascore 1.00); Tier W 程序判定实跑
- `evals/ablation/` (E5): 30 任务 (D12/C6/R6/S6, D 类全绑 E2 快照+gold) +
  预登记 hypotheses (Δ1/Δ2/Δ2b/Δ3 + A1–A5 + sham + add-back) + 11 系统装配 +
  ScriptedLLM 三工具面适配器 + 三门合成 (ESR_data/know/full + 幻觉三通道) +
  V-1..V-7 反证 (metascore 1.00); scripted 下 B3 十二 D 任务三门全过
- `evals/repro/` (E6, 自 temp/E6-design 审查迁入): 32 任务 + frozen manifest
  八项指纹 (缺一即抛) + trace 脱敏/完整性 + 四一致率 (tsc/pac/rdc/fcc) +
  EF1..EF7/U1..U7/Wilson·McNemar·α + 12 反证夹具; R0 路实跑四率 1.0000
- `evals/_data/` 唯一共享件: `null_sentinel.yaml` (阈值 -999/豁免 pmra/pmdec/
  radial_velocity) + `tolerances.yaml` (ra/dec 1e-9, mag 1e-6, arcsec 1e-6)
- `evals/equivalence/`: 跨实验等价性断言 — transport 字节级一致 (groundtruth/
  robustness/repro 三副本同数据同答案) + 哨兵字典单点静态扫描 (禁 evals/ 硬编码)

### Fixed（结构整改 S0–P2）
- S0: astro-best 独立 git root (remote `ssh://git@ssh.github.com/LL-LK/AI.git`,
  github.com:22 被中间盒阻断, ssh.github.com:443 通); `.gitignore` 放行 docs/
  全部计划文档; pre-existing 树漂移 (.workbuddy-ai) 进 EXCLUDE_DIRS
- P0 命名对齐 A+B 全量: `src/lightcurve.py→multiband_photometry.py` (类
  BestMultiBandPhotometry)、`src/query.py→query_builder.py` (BestQuery 契约定
  义不变)、`src/core/processor.py→source_postprocess.py`、`src/scripts/io.py→
  guards.py`、`evals/case_runner.py→case_executor.py`、`ops/skill_cli.py→
  astro_best_cli.py`、`ops/cloud_modelscope/run.py→dispatch.py` — 全部留
  Shim (旧路径可跑), 锚点全量回改, README 树清单重生成
- P1: `src/pybest.py` 删除 (Best 单类与 BestClient 双副本合并) — `BestClient`
  获 `_request()` (节流+超时+raise_for_status+软错误) 注入缝、`download_file()`、
  `query()`; `best_export.save_result/fetch_pages` 死代码清理; 测试 842→817
  (pybest 专属 25 条随删, 计划内)
- P2: 六份实验文档编号回改 §0 为 E6 附录 B 最终台账 (drift→E7, TAP→E8);
  `docs/architecture/naming-alignment-record.md` 全量台账

### Added（门禁三件套）
- `Makefile`: `eval-e2..e6` + `evals-all` targets; `test:` 扩到 `test/ evals/`
- `ops/astro_best_cli.py doctor`: 组件探针扩到 E1–E6 实验设施 (含
  `evals/_data` 两份字典 + equivalence tests)
- `CLAUDE.md` 新建: 门禁命令 + 七条铁律 (禁版本号/中文 docstring/400 行净代码/
  temp 产物/树清单/fail-open/零跨实验 import) + 六实验状态表

### Docs
- 六份 `docs/eval-E*.md` 为方案真值 (内容零删除 — 铁律); `evals/*/REPORT.md`
  每实验实测报告 (覆盖边界显式披露: E3 盲评待评阅人/E6 R1-R3 待模型 API/
  E5 scripted 下 Δ1 与 sham 区分度不可分辨, 不冒充 100%)

### 验证
pytest 842→**1172 passed** (24 skipped, 零回归); ruff 宽规则集全清;
`evals/eval_runner.py` SUCCESS (综合 1.0000); `ops/verify_tree_integrity.py`
661 条目一致; doctor 全组件 OK; 最终验收 12/12 PASS (全门禁 + 六实验 +
equivalence)。

## 完善轮 1：SUT 缺陷修复 + 400 行预算整改 + 债务核账（2026-09-30）

> E4 实验抓到并修复真实 SUT 缺陷; 两个预算越界文件按 §3 预案拆分;
> ISSUES.md/MK-03 按实测核销。

### Fixed
- **E4 F-E4-01 半行入库** (实验首个真实产出): `BestSource.from_row` 接受
  "有 ra 无 dec" 的结构半行并原样入库 ( dec=None 进结果集, 下游按 None
  坐标匹配/去重静默出错) — 新增 `src/models.malformed_coordinate_reason`
  (坐标列存在但空值→理由串; 列不存在的星表如 uss_dr1 不受影响) +
  `_fetch_sqlid_data` 跳过并计入 `query_params.skipped_malformed_rows`,
  服务端计数大于实收时 `truncated=True` (不把"少收"说成"已取全");
  **E4 RB-29 翻转, W tier 15/15**; 两条回归钉死
- 重试测试环境依赖: `test_single_layer_retry_on_503` 原打
  `https://x.invalid` — 断网时死于 SSL connect, `_make_request` 桩达不着
  (attempts=0 假失败) → 改 `http://` + `_new_conn` 替身连接, 全程零真实
  socket (被判行为不变: 同一 Retry 配置), 用例 4.6s→0.12s

### Refactored（400 行预算, R2 执行）
- `evals/repro/tests/test_e6.py` (743 净行) → 拆四件: `support_e6.py`
  (共享夹具对账单点) + `test_e6_foundation.py` + `test_e6_metrics.py`
  (389) + `test_e6_runner.py`; 拆分后 174 用例与原文件逐一对齐无丢失
- `ops/astro_best_cli.py` (454) 的 download 子系统 (接线+实现) 整体抽至
  `ops/cli_download.py` (主文件 332); `_safe_path` 唯一调用点随迁直走
  `resolve_data_path` 单点 (不留零调用函数 — P1-7 反模式)
- `docs/architecture/file-size-budget.md` §3 登记簿刷新: 删 pybest 条目
  (已随 P1 删除), client.py 583→725 / protocol.py 464→481; **未登记超限 = 0**

### Fixed（债务核账, ISSUES.md revision-4）
- MK-03 平台绑定修掉: Makefile 归一纯 LF (原 86 行全 CRLF — GNU make 在
  Linux/CI 会把 `\r` 吃进 recipe 与 .PHONY) + 新建 `.gitattributes`
  (Makefile/\*.sh 钉 LF; snapshots/fixtures/csv/best_data 钉 `-text` 防
  科学数据被行尾转换污染)
- ISSUES.md revision-4 核账头 (历史内容零删除): MK-01/MK-02 已修; MK-03
  本轮已修; ENV-02 按设计消解 (无 install 路径, Makefile install 清单含
  pyyaml); SCH-01 message.proto 不适用 (契约面由 contracts/ 9 份承担);
  **§11 假评测已修** (突变实验: 副本删 contracts/ → FAILED 退出码 1,
  provenance 维 0.0; 25 cases 全含 given 且 runner 真实消费)

### 验证
全量 1174 passed 0 failed; ruff 全清; 最终验收 12/12 PASS; tree 661 一致。

## 鉴权待办清零：token 过期恢复路径 + Windows 静态保护（2026-09-30）

> `references/auth-and-oauth.md` §5「上鉴权准备清单」里仅剩两项仓内可行动条目
> (第 5 项长跑任务重新授权点、第 6 项 Windows token 权限)，本轮全部落地;
> 另修复 CHANGELOG 自身一处结构残损 (条目被 prepend 到 `# Changelog` 标题之上)。

### Added（auth §5.5 token 过期恢复单点）
- `src/auth/nadc_oauth.py::ensure_access_token(store, reauth)` + `TokenExpiredError`
  (NadcOAuthError 子类): NADC 官方不签发 refresh_token, token 典型 3600 s 过期,
  过期后唯一合法续期是重走 Authorization Code 流。恢复路径收敛成一个调用点 —
  有未过期 token 直通; 过期时调用方注入 `reauth` 回调 (典型是 `oauth login`/`paste`
  流的薄包装) 即自动重走授权并落缓存; 无交互通道 (批处理/CI/无头 MCP) 抛
  `TokenExpiredError`, 消息带 `python ops/skill_cli.py oauth login` 恢复命令。
  **任何路径都不把过期令牌当有效身份返回** (旧行为: 过期后身份块静默变空/请求 401,
  晚一个任务周期才暴露)
- `ops/skill_cli.py oauth token` (无头管道面: 打印可用 access_token, 过期 rc=1 带
  恢复命令) 与 `oauth status` 三态 (`valid`/`expired`/`missing` + hint; 缺省仍
  `missing`, rc 语义不变 — 未授权不是故障)
- `references/skills-spec.local.yaml` algorithms 增钉 `ensure_access_token`/
  `TokenExpiredError`; `contracts/io-contract.md` 算子表增 `ensure_access_token`
  (S1 门禁随之覆盖这两个新公开缝)

### Added（auth §5.6 Windows 静态保护: DPAPI）
- `TokenStore` 落盘格式版本化为 **v2 信封** `{"v":2,"protection":"dpapi"|"none",
  "data_b64":...}`: Windows 走 DPAPI (crypt32 `CryptProtectData`, CURRENT_USER 范围,
  禁弹窗) — 0600 权限位在 Windows 上不生效 (chmod 只兑现只读标志, st_mode 恒
  0o666), 保密责任改由 DPAPI 承担, 同机其他用户/换账号/整机外带都解不出;
  POSIX 维持 0600 (权限位真实生效, 不引入第二套机制)
- 兼容与回退: v1 裸 JSON 旧缓存照常可读、下次 save 自动升级 (不做迁移脚本);
  DPAPI 探测失败或加解密失败时告警回退明文信封 (可用性优先, 风险留痕 —
  "登不进去"比"文件宽松"更糟, 但不允许静默降级); 密文损坏/换账号读取按
  "无缓存"处理 (load 返回 None), 不抛异常
- 本机 (Windows) 实机验证: save→dpapi 密文 (base64 500B), 明文 token 不出现在
  文件文本, load 解回同一记录, 篡改一个字节拒解密, v1 兼容, 回退路径闭环

### Tests（+16 回归, 全离线零网络零凭据）
- `test/unit/auth/test_nadc_oauth.py::TestEnsureAccessToken` (6 例): 有效直通/
  reauth 恢复并落盘/无 reauth 抛错且消息带命令/裸字符串载荷/垃圾载荷拒绝
- `test/unit/scripts/test_nadc_oauth_permissions.py` 重写 (2→9 例): 保留 A3 的
  POSIX 0600 两例; 新增落盘非明文/v2 信封/round-trip/v1 兼容/DPAPI 不可用回退/
  损坏信封按无缓存; **Windows 实机 DPAPI 类** (真加密真解密真拒解密 + ctypes
  原语闭环) — 此前该文件在 Windows 上只有 1 例能跑 (另 1 例 skip), 等于
  "无保护也无门禁", 现在 Windows 是保护最强的一侧
- `test/unit/auth/test_provenance.py::TestOAuthCli` (+3 例): status 三态断言
  (missing/expired + hint)、`oauth token` 有效打印与过期报错

### Docs（声明与实现同步)
- `references/auth-and-oauth.md`: §3 已知边界 (0600→DPAPI, 补残余边界)、§5 清单
  第 5/6 项标记已接线并写明剩余空缺 (第 1/3/4 项仍阻塞: 需站点账号与 OAuth 审批)、
  §6 失败语义增 TokenExpiredError、§7 证据锚点测试数 37→46+9
- `references/ALGORITHM-SPEC.md` §4 锚点与 TokenStore 描述、`README.md` 三行
  (auth 门面/nadc_oauth/auth-and-oauth 条目)、`references/llms.txt` 无需改
  (原表述仍成立)
- CHANGELOG 结构修复: fe47788a 把 Phase 5 条目 prepend 到 `# Changelog` 标题之上
  且尾部段落残损 (乱码片段), 已按可核实事实重写并归位到时间倒序正确位置;
  文中"monorepo 生成器仍产旧名"的告诫经核实已过期 (生成器随后已对齐新名)

### 验证
pytest 842 passed / 24 skipped (零回归, +16); ruff 宽规则集净;
ops/verify_tree_integrity.py 277 项一致 (无新增文件); evals --mode all 25/25
(综合 1.0000 SUCCESS); MCP --selftest 13/13; doctor import_ok。净代码行:
nadc_oauth 250→341, skill_cli 352→367, 均在 400 预算内
(docs/architecture/file-size-budget.md §3 登记簿无需更新);
docs/architecture/coverage-matrix.md §2.1 同步三行 (新符号进矩阵, R2 门禁)。

## references 严谨性审计（2026-09-29，教师专项第二轮）

> 对 references/ 全部 12 份文件做"声明 ↔ 代码/契约/live 证据"逐条对账（4 路并行
> 只读审计 + 主控实证复核）。结论: 无 P0；3 条 P1、20 条 P2，全部已修；
> 另补 2 处代码侧失真声明修正与 1 处 schema 未执行校验的接线。

### Fixed（文档声称的行为/锚点与代码不符 — "声称的控制未接线"规律在文档侧再现）
- download-playbook §9 排障表 4 行 + fallback FB-5: `checksum_mismatch`/
  `disk_write_failed`/`session_expired`/`pagination_inconsistent` 四类 severe
  hook 与"sha256 重读重试"协议在 src/ **有定义无触发**（生产唯一调用方不传
  expected_sha256 → 校验和核对实际不发生；磁盘/会话/分页故障实际走任务 failed）。
  已按实况改写，并在 §5 表格区分"已接线/已定义未接线"两类 severe kind
- tools.schema.json + llms.txt + README + best_mcp_server docstring: "零第三方
  依赖"实为**传输层**零依赖 — 进程级经 src.client 依赖 requests/urllib3，
  无 requests 的环境 import 即失败。五处同步改口径
- tools.schema.json 信封 "对齐 contracts/envelope.contract.yaml" 不成立（那是
  流水线双态信封；工具信封字段在 contracts/ 零命中）；E_BACKEND 不在
  error-codes 契约内。已改为如实标注归属
- ALGORITHM-SPEC §2 锚点表: BestQueryResult 权威处是 src.models（非 query.py）、
  BestAuth 定义在 src.auth.session（client 仅再导出）、csv_safety 符号实为
  sanitize_cell；§1 dbgrid"匿名挂起"、§3 rate_limit 单值（Best 实为 3.0）、
  §5 proximity 直连 _build_form（已改公开缝）同步修正
- best-database-guide: 删除无来源的 "BAO Feedback Exoplanet and Stellar
  Transient" 全称（官网自名 BEst STar database）；calib/ 前缀精度；xpsp
  "139 张分波段表"→"139 张表单表（1 共享+138 分波段）"；filterRules 从路由
  参数移除；"637 MB" 无留档证据 → 降级为"数百 MB 量级"（4 处转载点同步）
- photometric-systems: J-PAS 窄带 56→55 且枚举补 J0900（官方镜像逐行复核 +
  CATALOG_FORM_TABLES 55 个 jpas_j* 表实证）；help 页联系人邮箱 2022→2021
  转写修正
- data-formats: "Best 与 BestClient 半径单位不同"为误（两者都收 radius_arcsec，
  分歧在返回形态）；dbgrid"挂起"→快速软错误；serialization 回归 43→50 项
- pybest-api-reference: 口径声明改为"本仓（扁平化 pybest）"并列出与上游快照
  （temp/pybest0328）的两处差异（timeout 参数、12 vs 9 星表）；haversine 去掉
  "小角近似"误述
- llms.txt / auth-and-oauth.md / site-endpoints §5: "/jobs 需要 OAuth" 解耦为
  "第一关是 BEST 站点账号（Django 会话），OAuth 是登录页第二跳"；auth 文档
  §0 损失项 3→2（/jobs 不卡在 OAuth 审批）；NADC_OAUTH_* 三键不在 Q-16
  env_map 的括注更正；退役 env 名 BEST_API_USER/PASS 换现行凭据面；
  "90 个 metadata_*"→92（证据精确计数）；smss 旧登记列 2→4

### Fixed（代码侧让文档变真）
- `src/ai_tools.py`: fetch_page 补 page/page_size 边界校验
  (page>=1, 1<=page_size<=10000=MAX_FETCH_PAGE_SIZE, 与 schema maximum 一致),
  越界 ValueError -> E_INVALID_INPUT — schema 此前声明 maximum 而全链无校验;
  docstring 的"协议层判定"声称同步改实
- `src/download_hooks.py`: SEVERE_PATH 建议方案补第 2 条 (原 1 条违反"每类
  severe 至少 2 个建议方案"的 ask 铁律, 文档与 HookInterrupt docstring 同承诺)
- `ops/best_mcp_server.py`: docstring 去掉进程级零依赖的失实宣称

### Added（守门）
- `test/unit/meta/test_module_paths.py` 新增 S4 源: ALGORITHM-SPEC.md 的模块
  引用必须可导入 + §2 锚点表 10 个关键符号钉住表逐条校验 (此前 spec 锚点不在
  任何门禁扫描范围)
- `test/unit/download/test_download_hooks.py`: severe kind 覆盖扩到全 7 类且
  阈值 >=1 提为 >=2 (ask 铁律变可判定)
- `test/unit/ai_tools/test_ai_tools.py`: fetch_page 越界参数 5 例 + 边界值放行
- `rag/knowledge/lessons_learned.yaml` 回写 2 条: 文档声称行为与代码脱钩的
  审计方法 (grep 触发点 + inspect 符号双口径)、live 快照与转载数字的证据要求

### 验收（全绿）
- `pytest test -q`: 826 passed / 24 skipped (本轮 +8)
- `ruff check src/ test/ evals/ ops/`: All checks passed
- `ops/verify_tree_integrity.py`: OK (277 entries)
- `evals --mode all`: 25/25 场景 + 25/25 用例, 综合 1.0000 SUCCESS
- `ops/best_mcp_server.py --selftest`: 13/13

## 端点/列全覆盖审计 + 静态列表漂移修复 + 鉴权准备（2026-09-29）

> 教师专项: 清查"一键接入网站的 skill"的问题, 确保网站全部功能与端点全覆盖,
> 完毕后准备上鉴权。取证脚本与证据 JSON 均在 `temp/audit_*.py` / `temp/audit_*_results.json`。

### Fixed（静态列白名单与线上漂移 — 两类静默事故）
- smss_dr4/uss_dr1 已被站点按波段重构, 旧登记列 (smss: source_id/ra/dec/psf_mag;
  uss: source_id/ra/dec/psf_mag) 全部下线成**幻影列** — 服务端静默丢弃未知
  showcol 键: smss 默认投影只剩 ra/dec (星等整列消失), uss 响应退回无表头
  全表 (parse 出 92 个 metadata_* 幻影列)。已按线上全量重写两张星表的
  CATALOG_COLUMNS + 星等/误差映射 (smss 6 波段 PSF; uss 12 波段 pstotal)
- gaia_dr3_18 (27→155), scr_galah/scr_lamost (各 33→137), xpsp (11→287,
  CATALOG_FORM_TABLES 1→139 张表) 只登记了线上可选列的一小部分,
  qualify_column fail-closed 让其余列不可请求 — 已按线上全量登记
- `src/models/__init__.py::from_row` 前缀剥离只认星表名 — xpsp/dr3xpcorr 的
  响应前缀是**表单表名** (gaiaxp_photinfo_replenish_), 导致这两张星表的
  BestSource 位置/星等/source_id 整列静默丢失 (锥搜"成功"但是空壳)。
  已改为剥离"星表名 ∪ 全部表单表名" (长前缀优先, 防 jpas_u/jpas_ujava 误剥)
- `PAGINATION_SORT_COLUMNS` 的 smss_dr4/uss_dr1 排序列随星表重构失效
  (服务端静默忽略未知 sort, asc/desc 行序相同即判定) — 分页定序对这两张
  星表退回无序。已改指线上真实列 (smss_dr4_ra / uss_dr1_ra_u, 反转实测生效)

### Added（守门与参考层）
- `test/unit/meta/test_catalog_registry_live.py` 新增
  `test_static_columns_match_the_live_showcol_counts` (wire-fact 门禁):
  12 星表列数与线上表单页逐一相等 + gaia_dr3 别名同步 — 站点再漂移先红
- `test/unit/models/test_magnitude_mapping.py` 新增 3 条回归: XP 星表表单表
  前缀剥离 / uss_dr1 裸名命中星等表 / smss_dr4 六波段 PSF
- `references/auth-and-oauth.md` (新受跟踪文件, 用户"凝练进 references"请求的
  落点): 双轨鉴权总表 / BestAuth Django 会话协议 / NADC OAuth 三闸门与坑 /
  /jobs 第一跳 / **上鉴权七步清单** / 失败语义; README 表 + 树清单同步 (277)
- `references/site-endpoints-and-interactions.md`: §1 修正 email-exists (已下线)
  与 calib/ 前缀精度; §5 补 /jobs 第一跳; §6 live 快照按 2026-09-29 复测改写
  (dbgrid 从"挂起"变"快速软错误"); 新增 §9 端点/列全覆盖审计 (覆盖矩阵 +
  问题清单 + 残留限制 + 复跑命令)
- `rag/knowledge/lessons_learned.yaml` 回写 5 条: 静态列表漂移 / 表单表前缀 /
  uss 裸名与 sort 双拼写 / 幻影排序列被静默忽略 / live 快照过期复测
- `docs/architecture/file-size-budget.md` §3.11 登记 protocol_catalog_tables.py
  (662 净行, 纯数据列清单, 单一出处论证), 登记簿按实测刷新并补 §3.12

### 验收（全绿）
- `pytest test -q`: 819 passed / 24 skipped（+4 新守门）
- `ruff check src/ test/ evals/ ops/`: All checks passed
- `ops/verify_tree_integrity.py`: OK（277 entries）
- 实网验收 `temp/audit_acceptance_full_coverage.py`: 12/12 星表默认投影
  **零静默丢列**, 10/12 sort asc/desc 反转生效 (ps1 因 source_id 线上为空
  空转属已知站点限制; landolt 探测锥区无源未验)

## 文档回正 + 门禁增强 + 方案补漏（2026-09-28，Phase 6/6）

> 依据 `docs/FIX-PLAN-2026-09-28.md`。本轮为六阶段修复的收尾: 源审计清单的
> 文档/契约失真回正、三类新门禁落地、以及方案编制时遗漏的三条运行时问题补修。

### Added（三类新门禁 — 运行时清单"全绿不等于健康"的直接对症）
- `test/unit/meta/test_gate_blindspots.py`（新受跟踪文件, 用户 Q9 批准）:
  ① AST 模块级重复定义扫描（**阻断** — crossmatch.py 双定义那类漏报的根治法）;
  ② 公开符号生产零引用清点（**仅 WARN** — Q12 裁定防误伤 A 类公开 API 面,
  现报 2 条: csv_safety.sanitize_rows / provenance.reset_session_id）;
  ③ 跨入口单点接线断言（两条分页链都走 build_page_url、两客户端都查状态码、
  下载栈校验 URL 白名单、12 星表排序列全覆盖 — 守"接线本身不断"）
- `pyproject.toml` ruff 宽规则集增量启用: `select += RET, SIM, S`
  （既有违规真修: RET501/504 全清、SIM105 改 contextlib.suppress、SIM108/117
  机械修复、生产目录 10 处 S 误报/已缓解项定点 noqa + 中文理由; TRY 集 185 条
  多为风格类, 留待下一轮, 不搞大爆炸式切换; 测试目录按既有惯例入
  per-file-ignores 并逐类裁定理由）

### Fixed（方案补漏 — 编制 Phase 划分时遗漏的三条, 诚实记账）
- P1-11: `Best.info()` 的裸 `except Exception: pass` 改为 WARN 日志
  (类型+消息) — DNS/TLS/代理/编程错误不再塌缩成无记录的 connected=False
- P2-10: `best_export.download_file` 补大小回核 (Content-Length 与实落字节
  不一致即失败并保留半成品, 不再静默报成功) + 非续传/取消路径关闭响应
- P2-12: `BestLightCurve.from_client` 对非 `POS_<ra>_<dec>` 形态 ID 显式
  ValueError — 旧实现静默返回 0 点容器, 导出落盘成仅表头文件还报"成功"
  (README 声称的 Q-29 就此兑现)

### Fixed（源审计清单回正 — SA-P1-1/P1-2/P2-1/3/4/8/9、SA-P3-1/2/3/6/8/9）
- README 逐文件能力边界表: 删 fixtures 两行与三个空目录行; integration 行改
  7 个 chain 文件; 计数更正 (client/crossmatch/lightcurve 2→1, download 9→10,
  meta 5→12, models 1→4, scripts 1→4, auth 2→3, audit_round 2→3); src 表补 10 个
  遗漏文件 (serialization/best_export/download_*/auth/session/core/processor/
  protocol_catalog_tables/tap response+uws_service); references 补 data-formats;
  evals 补 4 文件; protocol.py 行去掉已删的 parse_retry_after; SKILL.md 行同步
  压缩后的节结构
- 错误码契约双向对齐: BEST_1001.code 改为代码实发的 `E_INVALID_INPUT`; 补
  BEST_1007 (E_NO_SQLID) 与 BEST_1008 (E_NAME_UNRESOLVED); BEST_1004/1005
  编号规则统一 (E101004_*→E1004_*); 五个 declared 未接线码的缺口从隐式变显式
  (注释说明生态级委派/门禁码暂无消费点); 顺带修掉值内 ": " 未引用的 YAML
  解析错误 (evals 契约审计器 CRITICAL 实测抓到)
- SKILL.md 137→98 行 (G6 ≤100 达标): 主理表+委派表合并为边界契约两段, API
  快查 9 条分组为 4 行, 组件地图表格化紧凑; frontmatter/铁律/门禁/路由/自检
  全保留; 失效符号 sis_relative_to → resolve_within; rag 三件套→五件套;
  场景路由补 Makefile 工程命令行
- .env.example: 删无消费方的 BEST_API_USER/PASS (注释说明真实凭据面为
  --auth-user + ASTRO_BEST_PASSWORD); references/fallback-protocols.md 与
  ALGORITHM-SPEC.md、oauth.contract.yaml 的同类表述同步回正
- references/site-endpoints-and-interactions.md 的历史位置列去掉不存在的
  `src/pybest/oauth.py` 字面 (改为包内相对路径 + 6f00efeb 删除标注, 现状列
  仍权威指向 src/auth/nadc_oauth.py)
- SA-P2-3: `BestSkillClient.api_token` 死参数删除 (BestClient 无 token 通道,
  env BEST_API_TOKEN→config→此处的全链是死路; 配置层字段保留供 doctor 报告),
  pipeline 透传点同步; SA-P3-6: TokenStore.valid_token 双 load 改一次;
  SA-P3-7: evals 兄弟裸导入的"必须脚本方式调用"契约写入 eval_runner docstring;
  SA-P3-8: 三个空目录 (unit/config、unit/query、test/upstream) 清理;
  SA-P3-9: 错误码编号规则统一 (见上)
- src/tap/__init__.py docstring 重复串 "(git 6f00efeb^ 可取回)" 去重

### Tests（evals 联动修正 + 补漏回归, 808 → 815 passed）
- `evals/case_runner.py`: 抽查桩 URL 改白名单主机 (P1-10 联动) + 桩响应补
  close() (P2-10 联动) + SIM115/105 修复
- `evals/probes.py`: 锥搜/质量探针的幻影列 ps1_gmag → 真实列 ps1_rpsf/ps1_gpsf
  (P1-3 联动 — 旧探针用的就是会被 fail-closed 拒掉的幻影列)
- 补漏回归: info() WARN 不静默 / download_file 大小回核与响应关闭 /
  from_client 未识别 ID 显式失败 (含 POS_ 两段非数字分支)

### Docs
- `docs/architecture/file-size-budget.md`: protocol.py 466 / client.py 583 /
  pybest.py 405 三处登记数字同步 (§3.2/3.3/3.10)
- README 树清单经 `verify_tree_integrity.py --write` 两次重新生成
  (新门禁文件登记 279 → 空目录清理后 276)

## P2 双副本语义对齐 + 死代码清理（2026-09-28，Phase 5/6）

> 依据 `docs/FIX-PLAN-2026-09-28.md`。双入口物理合并仍排二期（README 原排期），
> 本轮把七维漂移里的六维错误语义对齐。

### Fixed（P2-1 pybest 侧分页与 client 侧结构漂移）
- `src/best_export.py fetch_pages` 补三个 seam: `start_page`/`initial_rows`/
  `on_page_fetched` (与 BestClient._fetch_sqlid_data 同名对齐, 断点续传与
  页边界取消可用) + `count_total` 服务端总数查询 (超过 max_rows 记 WARN —
  Best 返回裸 list 没有 truncated 标志可挂, 截断不再静默); HTTP 状态错误
  显式冒泡、瞬时网络错保留断点语义 (Phase 1 已接, 本轮补结构对齐)

### Fixed（P2-6 `Best.cone_search(catalog="std")` 与 client 两种语义）
- `src/pybest.py` cone_search 展开 `CATALOG_GROUPS["std"]` 成员表合并
  (复过的现: resolve_catalog("std") 抛 ValueError -> None -> [], "标准星"
  概念在两条客户端上两种语义); 单成员失败隔离 + 总量封顶, 与 client 侧
  Phase 4 的修复同构

### Fixed（P2-7 同一查询返回形态随入口变）
- `Best.query` 默认 `normalize=True` (与 cone_search/get_query_result/
  crossmatch_batch 统一形态); TAP 执行器改由调用点显式传 `normalize=False`
  (归一化行会把 magnitudes 字典 str() 成字符列污染 VOTable 类型 —
  file-size-budget §5.3 的分歧理由从"默认值隐藏"变为"调用点声明")
- `Best.crossmatch_batch` 补 `page_size` 形参 (BestClient 一直有, 签名分叉)

### Fixed（P2-8 `Best.resolve_name` 裸抛 requests 异常）
- `Best.resolve_name` 网络/HTTP 失败收敛为 `NameResolveError` (与
  BestClient "调用方只需捕一种异常"的契约一致);
  `Best.get_query_result_count` 软 404 按"计数未知"收敛 None (与 client._count
  口径一致, 旧实现让 Soft404Error 穿透)

### Fixed（P2-9 output_format 死参数 + SA-P2-5 build_query_form 零校验）
- `src/protocol.py` 新增 `validate_export_format()` 白名单校验器;
  `build_query_form` 的 output_format 过 `{html} ∪ SUPPORTED_OUTPUT_FORMATS`
  白名单 (fits 等站点不服务的值显式抛错 — 模块注释声明的责任兑现)
- client 三个便捷查询入口 (query_panstarrs/query_calibrated/
  query_standard_stars) 入口校验 + docstring 说真话: 阶段 2 始终 csv 拉取,
  该值进 query_params 溯源, 格式转换在落盘层

### Fixed（P3-1 `_proximity_radec_text` 重复定义）
- `src/crossmatch.py` 删除第二份 (重写 zip 逻辑) 定义, 只留委托协议层的
  薄别名 — 复过的现: 生效的是后一份, 线格式单一事实源被打破
- 顺带修 SA-P3-5: `protocol.proximity_radec_text` 改 `zip(strict=True)`,
  RA/Dec 长度不齐显式 ValueError (旧实现静默截断坐标列表)

### Fixed（P3-2 端点常量形同虚设 + 零引用重试助手）
- `SQLID_PATH` (经 build_page_url) 与 `GETCOUNT_PATH` (client._count 与
  Best.get_query_result_count 两处) 真正成为端点 URL 的单一事实源
- 删除生产零引用的 `is_retryable_status`/`parse_retry_after`/`backoff_delay`
  (一套 dormant 的"手写第二重试层"零件, 与"重试唯一层在 adapter"的架构结论
  矛盾); 测试锚点改为 RETRY_STATUS_CODES 常量本身; README 能力边界表述的
  修正列入 Phase 6

### Fixed（P3-3/P3-4 落盘: 不可达分支 + 显式名/格式不相配）
- `src/best_export.py save_result`: 删两处永不可达的"纠后缀"分支 (自动名
  早已由 ext_map 给对扩展名); 新增显式名/格式自洽校验 (fmt=txt 给 .csv 名
  显式抛错; .votable/.txt 别名容忍 — live 实证的调用姿势)
- `src/downloader.py _save_result` 同口径对齐: 同一套别名校验; votable 不再
  无条件 `with_suffix(".xml")` (显式 .votable 名被暗改导致调用方 stat 落空);
  txt 的 .txt→.tsv 归一保留 (live 实证行为); 自动名改规范扩展名 (txt→tsv /
  votable→xml, 与 best_export 的 ext_map 同口径)

### Fixed（P3-8 max_sources 配置了不执行）
- `src/scripts/context.py truncate` 展示预算取 `min(max_records, max_sources)`
  — 复过的现: max_sources 被构造、被 summary() 报告, 却无任何读取点钳制

### Tests（+18 项, 790 → 808 passed）
- `test/unit/protocol/test_protocol.py`: output_format 白名单 (phase-1 表单
  与 validate_export_format 双侧) / proximity 长度不齐拒绝
- `test/unit/audit_round/test_audit_fixes.py` 新增三个守门类: 双副本对齐
  (std 组展开 / query 默认形态 / TAP 显式 False / resolve_name 收敛 /
  getcount 软 404 / crossmatch_batch page_size / 便捷入口格式拒绝与归一);
  落盘格式契约 (显式名不相配拒绝 / .votable 别名保留 / .txt 归一);
  单一定义与预算钳制 (AST 级防重复定义 / max_sources 钳制 / getcount
  URL 走端点常量)

### Docs
- `docs/architecture/file-size-budget.md`: protocol.py 463→466 (§3.10)、
  client.py 578→583 (§3.2)、pybest.py 新增登记 405 (§3.3, 双副本对齐所致)

## P1 并发正确性与重试/错误语义（2026-09-28，Phase 4/6）

> 依据 `docs/FIX-PLAN-2026-09-28.md`。

### Fixed（P1-8 `DownloadManager._lock` 只声明、零使用）
- `src/download_manager.py` 锁真正接线: `_spawn` 的 `_trackers`/`_cancel_flags`/
  `_futures` 写入、`cancel()` 的标志/future/tracker 复合操作、`_check_cancelled`
  的取标志判位、`_downloader()` 的 check-then-act、`_results` 写入全部过
  `with self._lock:` — 复过的现: 这把锁制造了"已加锁"的错觉, 后续维护者会
  以为共享字段受保护 (IO 调用保持在锁外, 不长持)

### Fixed（P1-9 每任务新建 BestClient → 限流时钟不跨实例共享）
- `_run_region`/`_run_sqlid`/`_run_precise` 从 `_make_downloader(job)` 改走
  `_downloader()` 管理器级单例 — 复过的现: `Best` 单类无 `.client`/`._client`
  属性 (只有 session), 每任务新建 BestClient 让 `max_workers=2` 时的
  rate_limit=2.0 被静默降为 ~1.0, 正是该限流要防的上游封禁风险

### Fixed（P2-4 `NETWORK_ERRORS` 按类名字符串匹配漏常见故障）
- `src/download_hooks.py` 改类引用元组 (ConnectionError/Timeout/
  ChunkedEncodingError/SSLError/ProxyError/RetryError) + `isinstance` 判定 —
  复过的现: ConnectTimeout (同时继承 ConnectionError+Timeout, 类名不在元组)、
  SSLError/ProxyError/RetryError 全部漏判, 最常见的网络故障反而不重试
- 测试替身同步真实化: 内置 ConnectionError → requests 异常 (生产栈真实类型)

### Fixed（P2-5 `cone_search("std")` 合并无单点失败隔离）
- `src/client.py` std 分支: 成员循环 try/except (坏波段的 ValueError 记 error
  后继续, 不再炸掉整个组查询); `query_params` 带成员溯源 (旧恒 `{}`);
  成员失败透传 `error_code`; `max_records` 按成员分摊 + 合并后总量封顶并置
  `truncated` (顺带修 SA-P3-4 的 3 倍超限)

### Fixed（P2-11 `TapJobStore` 连接即弃）
- `src/tap/jobs.py` 新增 `_db()` 上下文助手: 拿锁 -> 开连 -> 用 -> 提交 ->
  关连单点化 (7 处接线) — 复过的现: `sqlite3.Connection.__exit__` 只提交事务、
  不关闭连接, 每作业 4~6 次建连即弃, 句柄累积, `database is locked` 概率上升
- `src/tap/service.py` `main()` 的 finally 接线 `store.close()` (旧实现
  `close()` 零调用点, 线程池随进程悬挂)

### Fixed（P3-5 表单 POST 重试造孤儿 sqlid 会话）
- `src/client.py` 与 `src/pybest.py` 的 `Retry(allowed_methods)` 收紧为
  `["GET"]` — phase-1 表单 POST 在 429/5xx 时重试 3 次会让服务端创建 3 个
  sqlid 会话, 前两个成孤儿会话 (泄漏查询配额); phase-2 分页 GET 才是幂等
  可重试的那一半

### Tests（+17 项, 779 → 796 passed）
- `test/unit/download/test_download_hooks.py`: 8 类常见网络故障参数化判定
  (含 ConnectTimeout/SSLError/ProxyError/RetryError) + 非网络类不误判
- `test/unit/download/test_download_manager.py`: 三类任务共享一个 downloader
  (单例只建一次) + 30 并发 submit 一个都不丢 (锁接线)
- `test/unit/client/test_single_class.py`: 两个客户端的 adapter 重试白名单
  只有 GET (P3-5)
- `test/unit/audit_round/test_audit_fixes.py`: std 组单点失败隔离/溯源/总量
  封顶三个守门
- `test/unit/tap/test_service.py`: `_db()` 退出即关连接 (关闭后用即抛) +
  写入跨连接存活 (提交语义)

### Docs
- `docs/architecture/file-size-budget.md` §3.2 数字更新: `src/client.py`
  553 → 578 净行 (P2-5 std 组合并隔离所致, 例外登记同步)

## P1 安全面：数据根锚定单点 + 下载 URL 主机白名单（2026-09-28，Phase 3/6）

> 依据 `docs/FIX-PLAN-2026-09-28.md`。规律二（防逃逸只防终点、不防起点）与
> P1-10（SSRF 原语）的系统修复。

### Added（两个全仓单点, 落在 src/scripts/io.py 入参校验层）
- `resolve_data_path(candidate)` + `data_root()`：**起点校验**单点 — env
  `ASTRO_BEST_DATA_ROOT` 优先、缺省 skill 根；相对路径锚定数据根、绝对路径
  过 is_relative_to 校验。与 `resolve_within`（终点校验）分工明确
- `validate_external_url(url)` + `ALLOWED_DOWNLOAD_HOSTS`：下载 URL 白名单
  单点 — 仅 https、仅官方主机（nadc.china-vo.org + www 别名）、拒 IP 字面量、
  拒内嵌凭据；对照 `src/tap/client.py::_validated_tap_url`（不含主机白名单）
  补上下载栈缺失的一层

### Fixed（P1-5 `Best.download` 的 output_dir 无目录锚定）
- `src/pybest.py` `Best.download` 的 `output_dir` 先过 `resolve_data_path`
  再 mkdir — 复过的现: 落盘侧 `resolve_output_path` 只校验"文件是否逃出
  output_dir", 基准本身由调用方给定, 防逃逸被参数化绕过

### Fixed（P1-6 `python -m src --output` 把锚点本身开放给调用方）
- `src/__main__.py` `_print_or_save` 对完整输出路径锚定（不再把
  `--output` 的父目录当作 output_dir）; 顺带补 `BestClient.close()`
  （该客户端自持 requests.Session, 构造后不释放会泄漏 socket）

### Fixed（P1-7 `_safe_path` 定义后零调用点, README 却声称它生效）
- `ops/skill_cli.py` `_safe_path` 改为委托 `resolve_data_path`（删本地重复
  实现与随之零引用的 `_data_root`/`DATA_ROOT_ENV`）; download start 的
  `--out` 真正过锚定 — 复过的现: argv 直达下载栈, 只做文件名分隔符消毒,
  路径安全铁律在 CLI 面整体失效

### Fixed（P1-10 `FileJob.url` 无主机白名单 → SSRF 原语）
- `src/best_export.py` `download_file` 入口校验 URL（先于任何 IO）; 初始与
  Range 续传两个请求点加 `allow_redirects=False`（跳转目标会绕过主机白名单）
- 复过的现: 无 scheme/主机白名单、未禁重定向、无内网拦截, 响应体被完整写盘
  并报"下载成功"; CLI 冒烟: `--file https://evil.com/x.csv` 被显式拒绝

### Fixed（P3-6 `ProgressStore._path` 自制校验绕过 resolve_within 单点）
- `src/download_progress.py` `_path` 委托 `resolve_within`（拒目录成分、
  绝对路径、盘符与 resolve 后逃逸; 旧实现只查 pardir/斜杠）; 校验与拼名
  分离, 保住 `.json` 后缀与相对/绝对两种 progress_dir 配置

### Tests（+15 项, 764 → 779 passed; 测试桩同步真实化）
- `test/unit/audit_round/test_audit_fixes.py` 新增三个守门类: 数据根锚定
  （相对锚定/根内绝对路径/逃逸拒绝/Best.download 公开入口逃逸拒绝）;
  URL 白名单（官方主机放行 + 7 类 SSRF 载荷参数化拒绝 + download_file
  请求前即拒）; ProgressStore 路径守卫（绝对路径/盘符/目录成分拒绝）
- 测试桩真实化: 下载假 URL 换白名单主机（`https://x/...`/`example.com` →
  `nadc.china-vo.org`）; `best.download`/CLI 导出测试经
  `ASTRO_BEST_DATA_ROOT` 把数据根指到 tmp_path

## P1 协议层与模型层数据正确性（2026-09-28，Phase 2/6）

> 依据 `docs/FIX-PLAN-2026-09-28.md`。每条修复配"改坏就红"定向断言。

### Fixed（P1-1 `parse_csv_rows` 的 width 取数据行最大宽 → 真实表头被丢弃、全表串列）
- 判据改为**表头权威**：`has_header and (known is None or len(first) >= len(known))`
  时首行原样采用；宽于表头的数据行其多余值落 `overflow_{i}` 键并 WARN（一次解析
  只记一条）。复过的现：30 列表头 + 一行因未转义逗号多出一列 → 旧实现据数据行
  最大宽判定，真实表头 h1..h29 被丢弃并换成 `CATALOG_COLUMNS` 补齐列，坐标/星等
  全部串列且不抛异常
- 旧式短表头路径（首行只含元数据列）保留，与 bug 场景的区分判据是"表头是否短于
  权威列数"而非"数据行是否更宽"

### Fixed（P2-2 `has_header` 只问"有无 ASCII 字母" → 无表头响应首行被吞）
- 判据加强为列名形态：`_COLUMN_NAME_RE`（标识符状）且非 `_VALUE_LIKE_RE`
  （纯数值/科学计数/null 哨兵）。复过的现：`'180.0,30.0,1.2e-05\n...'` → 旧实现
  把含字母 `e` 的 `1.2e-05` 当表头证据，首行数据被整行吞掉且列名变成数据值

### Fixed（P1-2 `qualify_column` 的 legacy_prefix 兜底对 xpsp/dr3xpcorr 产出错误表名）
- 删除无条件 `return f"{resolved}.{name}"` 兜底；新增 `_catalog_table_columns()`
  （由 `CATALOG_COLUMNS` 响应列名按 `catalog_tables` 长表优先反推每张表单表的
  已知列集合），裸列名必须唯一落在某张表的已知列集合内才拼键
- 复过的现：`qualify_column('xpsp','g_mag')` → `xpsp.g_mag`（服务端无 xpsp 表，
  波段过滤静默不生效）→ 现为 `gaiaxp_photinfo_replenish.g_mag`；
  `magnitude_column('xpsp','g')` 同链路受益

### Fixed（P1-3 `qualify_column` 对裸列名只过正则，不校验列是否真实存在）
- 裸列名路径与已限定路径都校验列存在于该星表已知列集合（已限定路径旧实现只校验
  表归属）。复过的现：`nonexistent_col` → `ps1.nonexistent_col` 不抛错 → 服务端
  忽略未知表单键，静默返回全表而非过滤结果。docstring 中"严格白名单校验"的声称
  就此兑现

### Fixed（P1-4 `from_row` 把空/哨兵 RA/Dec 填成 0.0）
- `obj.ra = nv` / `obj.dec = nv`（None 即 None），字段类型改 Optional。复过的现：
  空 ra/dec → (0,0) 真实天球位置 → 畸形行被 `core/processor.deduplicate` 当成
  同一位置互相去重（`src/crossmatch.py` 注释早已点名该反模式）

### Fixed（P2-3 `NULL_MAGNITUDE_SENTINEL=-999` 无差别作用于所有数值列）
- 哨兵改为按列限定：豁免 `_ASTROMETRIC_COLUMNS`（视差/坐标误差等）与
  `_SENTINEL_EXEMPT_COLUMNS`（pmra/pmdec/radial_velocity —— 高自行星 pmra 可达
  ±1e4 mas/yr，旧实现把合法值抹成 None）。live 证据（`temp/live_sentinel_evidence.py`）：
  ps1 与 gaia_dr3_18 各 200 行响应里这批列没有任何 ≤ -999 取值 —— 站点不用
  ≈-999 作天体测量列缺失哨兵；测光列哨兵（`gpsf=-999`）保持生效
- 既有测试 `test_sentinel_parallax_is_treated_as_missing` 的前提（"与星等哨兵同
  口径"）经 live 证据推翻，已改写为 `test_sentinel_does_not_apply_to_astrometric_columns`
  + `test_photometry_sentinel_still_applies`（边界守门）

### Tests（+6 项，757 → 764 passed）
- `test/unit/protocol/test_protocol.py`：宽行不吞表头（overflow 键）/ 无表头首行
  是数据 / 幻影列 fail-closed（裸名与已限定两种形态）/ xpsp·dr3xpcorr 波段列落
  真实表单表
- `test/unit/models/test_astrometric_fields.py`：空 ra/dec 为 None（正常坐标路径
  不受影响）/ 天体测量列哨兵豁免 + 测光哨兵仍生效

### Docs
- `docs/architecture/file-size-budget.md` §3.10 数字更新：`src/protocol.py`
  428 → 463 净行（必要性论证与拆分预案同步扩充为三条）

## P0 止血：分页强制确定性定序 + HTTP 4xx/5xx 显式失败（2026-09-28，Phase 1/6）

> 依据 `docs/FIX-PLAN-2026-09-28.md`（两份问题清单经苏格拉底提问收敛后的统一修复方案），
> 定级以运行时实测清单为基准（主窗口独立复核 10/10 复现，探针 `temp/socratic_verify_probe.py`）。

### Fixed（P0-1 分页从不传 sort/order，默认路径必然重复行 + 丢行）
- `src/protocol.py` 新增分页单一事实源：`PAGINATION_SORT_COLUMNS`（12 张可查询星表 →
  确定性排序列，ID 类列优先；jplus_dr3 无 ID 列退到坐标列）+ `pagination_sort_key()`
  （星表 id/路径/别名 → 排序列，未知星表返回 None）+ `build_page_url()`
  （阶段 2 分页 URL 的唯一构造点，默认注入 sort+order，调用方显式 sort 优先，
  空串为显式逃逸口）。根因：线上实测无 ORDER BY 时同一 sqlid 两次 GET 行序不同
  （集合重叠仅 1/50，`references/site-endpoints-and-interactions.md`），`page=N`
  偏移翻页静默重复/丢行且 `truncated` 不置位
- `src/client.py` `_fetch_sqlid_data` 与 `src/best_export.py` `fetch_pages` 两条
  分页主链全部改走 `build_page_url`（此前各自硬编码 `output.fmt=csv&rows&page`）
- live 验证（`temp/live_pagination_order.py`，BEST_LIVE=1 受控预算）：两条链分页 URL
  均携带 sort+order，同一查询连续两遍翻页行序完全一致（修复前仅 1/50 重叠）；
  sort 两种键形式（`ps1_source_id` / `ps1.source_id`）服务端均回 200，采用响应列名形式

### Fixed（P0-2 `Best._request` 缺 raise_for_status，4xx 静默降级为"无数据"）
- `src/pybest.py` `_request` 补 `resp.raise_for_status()`（置于软错误检查之前）：
  401/403/404 等非 2xx 一律显式抛 `requests.HTTPError`，不再直通到调用方。
  复过的现：401 token 过期被读成"天上没有源"
- `src/best_export.py` `download_file` 初始请求与 Range 续传请求两处增加状态码前置
  校验（非 200 / 非 200·206 即中止并 `resp.close()`）：复过的现——404 HTML 正文经
  `os.replace` 变成"下载成功"的正式产物，日志还打 "Downloaded"（三条下游中最危险的
  产物污染）
- `src/best_export.py` `fetch_pages` 区分瞬时网络错（ConnectionError/Timeout → break，
  保留断点续传语义）与 HTTP 状态错误（确定性失败 → 显式冒泡，不再静默截断）
- `src/pybest.py` `_execute` 捕 RequestException 时日志带 HTTP 状态码细节
  （"到底是 401 还是 404"不再塌缩成一句"没有 sqlid"）

### Tests（每条修复配"改坏就红"定向断言，共 +18 项，739 → 757 passed）
- `test/unit/protocol/test_protocol.py`：`build_page_url` 默认注入 sort+order /
  显式 sort 优先与逃逸口 / 12 张可查询星表排序列全覆盖（漏登记即红）/ 路径与别名解析
- `test/unit/client/test_single_class.py`：`_request(404)` 显式抛 HTTPError；
  `download_file(404)` 不落盘返回 None（tmp/part 均不残留）；BestClient 分页 URL
  端到端携带 sort+order（守"单点接线"不断）
- `test/unit/download/test_download_file_resume.py` 与 `test/unit/client/test_single_class.py`
  的下载桩同步真实化：首次请求回 200、带 Range 的续传请求回 206，Mock 桩补
  `status_code = 200`——不声明状态的成功响应与 404 错误页不可区分，正是 P0-2 的生存土壤

### Docs
- `docs/FIX-PLAN-2026-09-28.md`（local-only）：两份问题清单的苏格拉底收敛产物——
  统一台账（33 条运行时 + 源审计文档/契约条目）、6 Phase 执行计划、三类新门禁设计
- `docs/architecture/file-size-budget.md` §3.10：`src/protocol.py` 因分页定序单点
  新增至 428 净行（+28），登记必要性与拆分预案（抽 `PAGINATION_SORT_COLUMNS` 到
  `src/protocol_pagination.py`，属结构变更待批准）

## templates/ 与 examples/ 规范化（2026-09-27）

> 本条 2026-09-30 修两处遗留: ① 原条目被误插在 `# Changelog` 标题**之上**
> (fe47788a 的 prepend 越位), 且尾部段落残损 (不可重构的乱码片段已删);
> ② "monorepo 生成器仍按旧名产出" 的告诫已过期 — 该生成器随后已对齐新名。
> 内容按可核实事实重写, 位置按时间倒序归位。

### Fixed（templates/config_template.yaml 的 6 处死路径）
- 该生成物模板的 `params.<Symbol>.module` 有 6 处指向不存在的模块，读者按图索骥
  即落空：`BestSkillClient`（`src.__init__` → 真实 `src.core`）、
  `BestCrossMatchJob` / `BestCrossMatchResult` / `BestQueryResult`
  （`src.__init__` → 真实 `src.models`）、`AstroBestConfig`
  （`src.config` → 真实 `src.scripts.config`）、`AstroBestPipeline`
  （`src.pipeline` → 真实 `src.core.pipeline`）。已按 `src/` 实况逐条修正
- `templates/best-config.yaml` 的 `defaults.bands` 默认值含 `"clear"`，而 `clear`
  不是任何星表 `CATALOG_MAG_COLUMNS` 里的波段标签，透传给
  `protocol.magnitude_column()` 会抛 `ValueError`（budget doc §6.1 G2 登记缺陷）。
  已从默认清单移除并在注释里写明理由
### Added（examples/ 纳入测试执行，防腐烂）
- `test/examples/test_examples_run_offline.py`（新目录 + 新文件）：此前 README 明确
  examples「不被 test 执行」，示例只能随 API 演进而静默腐烂。现在两个示例的主路径
  由离线桩真实跑通——`requests.Session.request` 全量替换为确定性桩（两阶段协议 +
  计数端点 + 连通性探测四类回包），`HTTPAdapter.send` 换真网卫兵；示例 docstring 里
  声明的预期输出（打印文案、落盘文件、归一化键、info 信封禁版本号）逐条变成断言
- 每个模板文件头新增「本模板的消费者」声明：`gen_*.yaml` 与 `gen_config_template.yaml`、
  `report_template.yaml` 如实写明「无代码消费者；仅由 evals TemplatesAuditor 审计消费」；
  `best-config.yaml` 写明消费者是 `AstroBestConfig.from_yaml` + wiring 测试 + 审计器
### Changed（命名统一，结构变更）
- `examples/quickstart_pybest.py` → `examples/example_quickstart_pybest.py`
  （示例统一 `example_*` 前缀）；`references/pybest-api-reference.md:18` 的引用同步（R2 2026-10-05 补注：该 reference 已随提交 `456149e`「pybest 双副本合并删除」一并删除，此行坐标为当时快照）
- `templates/config_template.yaml` → `templates/gen_config_template.yaml`
  （生成物统一 `gen_*` 前缀，与人读配置 `best-config.yaml` 分前缀）；README 描述行
  同步。monorepo 根的生成器 `scripts/refactor/materialize_templates.py:150` 已对齐
  新名（本条早期版本曾告诫"仍按旧名产出、重新物化会把旧名带回来"，该告诫随后已修掉，
  此处按 2026-09-30 实况改写）；6 个 `test_gen_*` 是生成器产物，注释寿命只有一次
  物化周期

## 格式层单一事实源 + 400 行预算拆分落地 + 预存在测试缺陷修复

### Added（输出序列化层：跨两条下载路径共用一份实现）
- `src/serialization.py`（新文件）：BEST 原生输出格式的单一事实源 ——
  `column_is_numeric` / `is_identifier_column` / `is_magnitude_column` /
  `xml_escape` / `delimited_text` / `json_document` / `votable_document` /
  `write_fits` / `normalize_output_format`。`src/pybest.py` 与
  `src/downloader.py` 都改为委派它，原地保留兼容别名
  （`pybest._column_is_numeric` / `pybest._write_fits`）
- `references/data-formats.md`（新文件）：BEST 全格式解析能力边界 —— 站点 6 个
  `output.fmt` 的处置、两阶段分岔、单位陷阱表、列类型推断规则、常见天文格式
  支持面、编码约定、复现命令
- `test/unit/serialization/test_output_formats.py`（新文件，43 项）：白名单/
  列类型推断/标识符列/VOTable 类型与单位与转义/分隔符判别/JSON total 语义

### Fixed（三个已存在的静默缺陷，都由"双副本各自维护写出逻辑"造成）
- **`BestDownloader` 的 VOTable 把全部列写成 `datatype="char"`**：数值列被
  astropy 读成字符串，科学消费端类型链条整段断裂。`src/pybest.py` 早在
  2026-09-30 就修了同一处（按整列取值推断 double/char + ra/dec 补 unit），
  `downloader` 漏修 —— 现在两条路径共用 `serialization.votable_document`
- **未知格式静默回落 JSON**：`BestDownloader._save_result` 的 `else` 分支把
  `fits` 等任何未实现格式写成 JSON 并把扩展名改成 `.json`，调用方请求 FITS
  拿到 JSON 文件且无任何提示。现在 `normalize_output_format` 白名单外一律
  `ValueError` 并列可选值；`fits` 接线到 `write_fits`（astropy 可选，缺失时抛
  带安装提示的 RuntimeError）
- **星等列单位漏判**：旧规则只判 `endswith("mag")`，`ps1_rpsf` /
  `splus_dr4_u_pstotal` 这类实测列名拿不到 `unit="mag"`，TOPCAT 侧无法做星等
  换算且不抛异常。后缀集合改为由 `CATALOG_MAG_COLUMNS` 现场推导
- **标识符列被当成数值列**：`ps1_source_id="123456789"` 写成 `double` 后前导零
  丢失、超 2^53 丢精度、下游按 ID 比较时 `"123"` 与 `123.0` 不再相等。新增
  `is_identifier_column`（`id`/`_id`/`_ids` 结尾）强制保持字符串
- **预存在的 urllib3 2.x 测试断裂**：两个重试回归补
  `urllib3.connectionpool.HTTPConnectionPool.ResponseCls`，而 urllib3 2.x 已删除
  该属性（响应构造下沉到 `HTTPConnection.getresponse`），`mock.patch.object`
  直接 AttributeError。改为不再依赖该属性（`_make_request` 直接返回真实响应即
  可计数），两个用例恢复绿色

### Added（TSV 解析能力）
- `protocol.parse_csv_rows` 增加分隔符判别，**只看表头行**：站点
  `output.fmt=txt` 与人工另存的 TSV 现在都能读。判别绝不能据数据行 —— 数据值
  里的逗号（如 `obj_name` = `"M31, NGC 532"`）会让逗号判据选中逗号，把 TSV
  的一列错拆成三列，整表列序静默偏移且不抛异常

### Changed（400 行预算拆分，用户批准"优化到 400 以内"）
超限文件 **9 → 5**。四个文件通过"抽到新模块 + 原地留委派薄壳"入预算内：

| 文件 | 前 | 后 | 抽到什么 |
|---|---|---|---|
| `src/protocol.py` | 658 | 381 | 9 张星表侧数据表（约 400 行纯数据）→ `src/protocol_catalog_tables.py` |
| `src/downloader.py` | 508 | 381 | 落盘辅助 / 区域编排 / sqlid 分页续传 → `src/download_artifacts.py`、`src/download_region.py`、`src/download_sqlid.py` |
| `src/tap/service.py` | 499 | 入预算内 | UWS 作业生命周期 + 响应载体 → `src/tap/uws_service.py`、`src/tap/response.py` |
| `src/pybest.py` | 566 | 368 | `_save_result` / `download_file` / `_fetch` → `src/best_export.py` |
| `src/client.py` | 589 | 553 | `BestAuth`（7 方法逐字迁入）+ 新增 `export_session()` 显式移交 → `src/auth/session.py` |

`src/client.py` 仍超限 153 行的**不可行性论证**已登记（budget doc §3.2）：两阶段引擎
是主链不许拆；其余方法被测试 `patch.object(client, ...)` 与直接调用钉死在实例上；
理论上限约 420。正解是 P1-9 双入口合并。

### Fixed（顺带清掉的存量死代码）
- `src/pybest.py` 有 3 个 `_column_is_numeric` 定义与 2 个 `_write_fits` 定义
  （互相遮蔽，Python 只取最后一个；前两个是纯死代码，约 16 净行重复）。列类型推断
  与 FITS 写出的真实现已在 `src/serialization.py`，留着会让人以为"这里还有第二套"，
  已删除，只保留一组兼容别名

### Docs
- `docs/architecture/file-size-budget.md` §3 按实测重登记（此前数字严重低估，
  旧脚本把多行表达式续行也当非代码行扣掉，`eval_runner` 一项少算 458 行）；
  §3.2 补 client.py 的不可行性论证；§3.9 记录已完成拆分与五条拆分原则（含
  "共享载体再抽一层到中立模块"以打破循环依赖）；§6.2 记录本轮已修项；
  §6.3 汇总 temp/ 问题文档的未决项；§9.4 记录格式层重构与修掉的缺陷
- README 树清单 SSOT 重生成（243 → 255 条目）

### Verified
- ruff：All checks passed
- pytest：**622 passed / 22 skipped**
- evals：25/25 场景、25/25 用例、6 审计器 0 findings、docstring 100.00%、
  1.0000 SUCCESS
- 树 SSOT：OK，255 条目
- MCP selftest：13/13
- 400 行预算：**9 个超限文件降到 5 个**
- 注释体检：缺失 docstring 0 / 非中文 docstring 0 / import 组欠覆盖 0（均只剩 1 条
  docstring 内示例 import 的已知误报）/ 重复注释 0 / TODO 0
- CRLF：0

### 待用户裁定
- `docs/architecture/file-size-budget.md` §6/§6.1 的 38 条已核实未修问题
- 剩余 5 个超 400 行文件：`evals/eval_runner.py` 971（探针层可切
  `evals/probes/`）、`docs/diagrams/gen_best_macro_flowchart.py` 794 与
  `gen_astro_best_architecture.py` 580（坐标常量表可抽 `layout_data.py`）、
  `test/integration/test_integration.py` 560（可按链路拆 + 共享夹具上移
  `conftest.py`）、`src/client.py` 553（见 §3.2 论证）。方案已登记待批
- monorepo 根 `scripts/refactor/common.py:273` / `materialize_tests.py:34` 仍会
  重新产出 `Master Plan v8.0`；6 个 `test_gen_*` 是生成器产物，本轮注释寿命只有
  一次物化周期，建议把注释模板固化进生成器（E1）
- 大仓 `MASTER-ROUTING.md` 的 BEST 数据 redirect 指向（见 §8.4）

## S4 Legacy 定位清除 + 注释规范全量落地 + references/knowledge 合规修正 + 上游引进文件规则检测

### Changed（定位：S4 Legacy → BEST 数据源主理，用户已批准）
- 清除全仓 12 个文件的「S4 Legacy —— 只做兼容，不作为新任务 PRIMARY」叙事。
  根因是**路由缺陷**：大仓 `docs/routing/MASTER-ROUTING.md` 据此把「BEST 数据」redirect
  到 `astro-catalog`，而 astro-catalog 主理 SIMBAD/VizieR/Gaia 通用检索、**不具备 BEST
  访问能力**（BEST 站点无 TAP/ADQL/REST-JSON 端点，只有 Django form 两阶段协议）。
  事实基线：569 项单测通过、evals 25/25、6 审计器 0 findings、MCP selftest 13/13、
  真实 REST 全链路联通实证——不是"只读历史能力"的状态
- 涉及：`SKILL.md`（frontmatter/标题/引言/重定向表→委派表/API 快查/组件地图/完成自检）、
  `manifest.yaml`、`architecture.md` §0、`README.md` 标题与 docs 行、`agents/openai.yaml`、
  `static/core/stance.md`、`contracts/io-contract.md`、`contracts/oauth.contract.yaml`、
  `references/skills-spec.local.yaml`、`templates/report_template.yaml`、
  `weights/README.md`、`src/auth/nadc_oauth.py`
- `strength: S4` 与 `role: Legacy` 两个**机器字段暂留原值**（避免与大仓
  `SKILL-STRENGTH-MODEL.md` / `MASTER-ROUTING.md` 的 S4 定义冲突，改字段属跨仓治理
  变更需单独报批）；每个保留处都加了指向 `docs/architecture/file-size-budget.md` §8 的说明
- SKILL.md 治理铁律新增第 5 条（注释必须中文）与第 6 条（400 行预算）
- 越界未改（只报告）：`MASTER-ROUTING.md:19/20`、`SKILL-STRENGTH-MODEL.md:14`、
  `build.md:330`、大仓根 `SKILL.md:56`

### Added（注释规范：四道防回归护栏 + 权威规则文本）
- `docs/architecture/file-size-budget.md` §4 重写为**注释规范唯一权威文本**（C1~C6 硬性
  规则、块级中文判定口径、docstring 三段式质量标准、外部 API/IO 注释标准、四道护栏）；
  原 `temp/COMMENT_SPEC.md` 降级为任务派发留档，不再是规范源
- 新增 6 个审计脚本（`temp/`）：`comment_audit.py`（六类违规计数）、`show_english.py`
  （块级英文注释检出）、`show_import_gaps.py`（组级 import 覆盖检出）、
  `dump_docstring_gaps.py`、`verify_no_code_loss.py`（AST 零丢失比对）、
  `check_line_endings.py` / `fix_line_endings.py`（CRLF 检出与归一）
- 修正了两个审计口径 bug，它们此前造成大规模虚报：① 中文注释续行是纯标识符
  （`# build_query_form()`），逐行判定把中文注释误报成英文 → 改为**按注释块判定**；
  ② 多行 import 的续行把同一组拆成多个"组"，已覆盖的被虚报成欠覆盖 → 改为
  **括号深度感知的组判定**（217 条虚报 → 实测 0）

### Fixed（注释负债清零：135 个缺失 docstring + 142 条英文注释 + 217 个 import 组）
- **缺失 docstring 135 → 0**：覆盖 `src/` 18 个、`evals/` 7 个、`ops/` 2 个、
  `rag/`、`docs/diagrams/`，以及 100+ 个测试替身对象（`_Resp`/`fake_urlopen`/
  `side_effect`/`_FakeBest`/`_Weird`/`_Handler` 等）。测试函数 docstring 一律按
  「验证什么行为 + 坏了造成什么静默后果 + 回归背景」三段式写，不写"测试某某功能"空话
- **非中文注释 142 → 0**（白名单外）：含 `src/pybest.py` 19 条、`src/client.py` 7 条、
  `src/crossmatch.py` 6 条、`src/tap/service.py` 的 `noqa: N802 - stdlib handler
  contract` 等指令后缀，以及 `docs/diagrams/` 的编号步骤标题。
  白名单（可留英文）：shebang、`# noqa`、`# pragma: no cover`、`# legacy-import-guard`、
  `# type: ignore`、`# ---` 纯分隔线
- **import 组无中文说明 217 → 0**：模块职责映射表统一口径（`temp/fill_import_notes.py`），
  同一模块在不同文件用同一句描述
- **重复粘贴注释 16 → 0**：`src/scripts/best_crossmatch_pipeline.py` 的
  "每次调用新建 BestClient" 3 处改为带差异化说明；`evals/eval_runner.py` 的
  "tempfile 造隔离临时目录" 3 处同理
- 修复 11 个文件被并发写入成 CRLF 的行尾回退（`test_lightcurve.py` 等）；
  已用 `git diff` + AST 双重确认内容无损
- 修复 `test/unit/models/test_magnitude_mapping.py` 因插入 import 注释触发的 ruff I001

### Fixed（references/ 与 rag/knowledge/ 合规：1 处版本号 + 8 处事实错误 + 5 处上游残留）
- **版本号**：`references/site-endpoints-and-interactions.md:183` 的 git 路径残留两处
  `0.3.2.8`（上一轮清理漏网），改为「pybest 打包产物树（git `6f00efeb^` 可取回）」；
  顺带修掉 `ALGORITHM-SPEC.md:112` 与 `known_issues.yaml:53` 的「打包产物 pybest 打包产物」
  重复语病；`gen_best_macro_flowchart.py` 的 `Master Plan v8.0 §4` → `Master Plan §4`；
  架构图标题里的 `版本: v0.3.1` 一并去除
- **事实错误 8 处**：`ALGORITHM-SPEC.md` 超参表 `REQUEST_TIMEOUT 30s→120s`（30s 只硬编码在
  `check_connection`）、`page_size 50000` 拆为 `max_rows 50000` + `page_size 1000`；
  `fallback-protocols.md` FB-2 的 `BEST_USERNAME/BEST_PASSWORD`（全仓无此二变量，
  照原文配环境变量永远不生效）→ `BEST_API_USER/BEST_API_PASS` + `BEST_API_TOKEN`；
  FB-3 退避措辞改为基数 `RETRY_BACKOFF_S=2.0` 并注明与 `rate_limit` 数值巧合相同；
  `best-database-guide.md` OAuth 回调 `/user/oauth2/login/nadc` → `/callback/nadc`；
  `pybest-api-reference.md` 的 `.cone(ra, dec, radius)` → `radius_deg` 并注"单位度，
  内部换算角秒"（该文档通篇警告角秒/度陷阱却唯此处漏注），BestClient 签名补 `timeout`；
  `best_practices.yaml` 星表清单「九类」→ 12 张可查表（std 标为导航组、gaia_dr3 标旧别名）；
  `skills-spec.local.yaml` 的 `module: "astro_best"`（无此模块）→ `src.models`
- **上游残留 5 处**：删除 `best-database-guide.md`「与 pylamost 对比」整节（描述上游姊妹包
  而非本 skill 能力边界，会误导选型）；`best_practices.yaml` 的 `~/pybest.ini` 补注
  "上游 pylamost 惯例的兼容层，不是 BEST 站点要求"，并修正「下载大文件需 token」与
  「公开数据面免登录」的口径冲突；架构图与流程图的 S4 Legacy 措辞全部改为主理定位
- **结构问题**：`download-playbook.md` §8/§9 编号重复（重排 8/9/10/11）；
  `known_issues.yaml` 死路径 `scripts/cloud_modelscope/run.py` → `ops/`；
  `skills-spec.local.yaml` 死引用 `scripts/refactor/spec/skills-spec.yaml` 改为说明性表述；
  `ALGORITHM-SPEC.md` DOI 核验状态节残缺标题（`###` 嵌进正文）重写；
  `llms.txt` 尾注碎片句补完整并加下载手册入口

### Docs（规模预算登记簿按实测重登记）
- `docs/architecture/file-size-budget.md` §3：此前数字（eval_runner 513 / client 502 /
  pybest 469 / downloader 401）是**粗糙口径测出的，严重低估**——旧脚本把多行表达式续行
  也当"非代码行"扣掉，`eval_runner.py` 一项少算 458 行。实测为 971/794/649/622/589/578/
  560/519/499 共 **9 个**超限文件（此前只登记 4 个，漏了 `src/protocol.py`、
  `src/tap/service.py`、`test/integration/test_integration.py` 与两个图生成器），
  逐一补必要性论证与拆分预案
- 同文档新增 §8（S4 定位清除记录，含越界未改清单）、§9（上游引进文件规则检测结果 +
  references/knowledge 体检 + temp/ 文档筛选）

### Verified（本轮全部门禁）
- ruff：All checks passed
- pytest：569 passed / 22 skipped（与改动前一致，零回归）
- evals：25/25 场景、25/25 用例、6 审计器 0 findings、docstring 100.00%、1.0000 SUCCESS
- 树 SSOT：OK，243 条目
- MCP selftest：13/13
- `skill_cli doctor`：通过
- AST 指纹：`compared=103 code-changed=0`（除两个图生成器的**有意**内容改动）
- 代码零丢失：`0 / 59` 可疑文件（def/class 数、assert 数、净代码行集合逐文件比对）
- 注释体检：缺失 docstring 0 / 非中文 docstring 0 / import 组欠覆盖 0 / 重复注释 0 /
  TODO 0 / 非中文注释 0
- CRLF：0（修复 11 个）
- 版本号复扫：tracked 文件 A 类 0；剩余 12 处全在 local-only `docs/` 且均为
  **记录被清理违规的引文**，非违例

### 待用户裁定
- `docs/architecture/file-size-budget.md` §6/§6.1 的 38 条已核实未修问题（每条都需配套
  回归，属独立变更）
- monorepo 根 `scripts/refactor/common.py:273` / `materialize_tests.py:34` 仍会重新产出
  `Master Plan v8.0`；6 个 `test_gen_*` 是生成器产物，本轮注释寿命只有一次物化周期，
  建议把注释模板固化进生成器（E1）
- 大仓 `MASTER-ROUTING.md` 的 BEST 数据 redirect 指向（见 §8.4）

## pybest 高价值内容按能力边界加回 + 全仓中文注释 + 400 行规模预算

### Added（还原自 pybest 打包产物，git `6f00efeb^` 可取回）
- `src/core/processor.py`（新文件）：`BestProcessor` 三项后处理能力在现行 `src/`
  无任何等价实现 —— `deduplicate`（真球面 haversine 去重）、`bright_sources`
  （亮度筛选）、`band_summary`（波段统计）。保留上游两个关键修正：坐标缺失/越界的
  行**必须保留**（不当成 (0,0) 静默丢弃）；容差必须有限非负。回归：
  `test/unit/pipeline/test_processor.py` 24 项
- `Best.close()` / `BestClient.close()` / `BestAuth.close()` + 三者 `__enter__`/
  `__exit__`：这三个类各自持有挂了 HTTPAdapter 的 `requests.Session`，原先**无任何
  释放路径**，MCP server 与批处理脚本反复构造客户端会泄漏 socket。
  `BestClient.close()` 只关自己的 session，不波与其他客户端共享的 `BestAuth`
- `Best.describe_columns()` / `BestClient.describe_columns()`：查询前列内省（IVOA
  TAP_SCHEMA 语义）。旧 docstring 声称"从表单页抓取"而实现只读静态表，已改为诚实
  表述（数据源是 `protocol.CATALOG_COLUMNS` 静态清单）
- `DownloadCheckpoint.list_jobs()`：人工复核面——批任务中断后一眼看到"有哪些任务
  可以接着跑"。只读文件名不解析内容，写坏的文件不让复核面整体失效
- 回归 `test/unit/audit_round/test_restored_surface.py` 25 项（生命周期/列内省/
  归一化契约/list_jobs）

### Fixed（还原时顺带修掉的诚实性缺陷）
- `Best.cone_search` 的 docstring 一直承诺 "List of dicts with ra, dec, magnitudes"，
  实际返回 `parse_csv_rows` 的原始行（`ps1_ra`/`ps1_gpsf`…），按文档取 `row["ra"]`
  直接 KeyError。加回 `_normalize_row` 与 `_fetch(normalize=...)` 开关后契约与实现
  一致；原始站点投影仍原样保留
- `Best.query(normalize=False)` 默认值与上游 `True` **有意分歧**并已在 docstring 记录
  理由：现行 `query` 是 TAP 执行器后端（`src/tap/executor.py`），归一化追加的
  `magnitudes` 字典会被 `convert_table_rows` 的 `str()` 成 `"{'g': 19.4}"` 当字符列
  写进 VOTable，污染科学消费端类型。人工调用方可显式传 `normalize=True`

### Docs（新增治理规则与论证留档）
- `docs/architecture/file-size-budget.md`（新文件，local-only）：400 行净代码行预算的
  度量口径、超限文件的必要性论证与拆分预案、中文注释规范、以及 §5 附录完整记录
  pybest 打包产物逐项还原决策（加回 7 项 / 不加回 19 类及理由 / 有意分歧 1 项）
- README 治理规则新增第 7 条「规模预算与中文注释」，`docs/` 能力边界行补
  file-size-budget

### Changed（全仓中文注释补充，只改注释不改代码）
- 覆盖 `src/ ops/ evals/ rag/ examples/ docs/diagrams/ test/` 全部 Python 文件：
  每个函数/方法/类一段中文 docstring；每次外部 API/IO 调用点一条中文行内注释
  （协议阶段 + 失败语义 + 降级策略）；import 按「标准库/第三方/本地 src.*」分组加
  中文说明；既有英文 docstring 中文化，技术标识符与字符串字面量保持原样
- 防回归护栏 `temp/code_fingerprint.py`：剥离 docstring 后做 AST 规范化 dump 取哈希，
  `check` 必须 `code-changed=0`，以此证明注释补充未触碰任何代码逻辑

### 验证
- pytest 569 passed / 22 skipped；ruff 全绿；树 SSOT 243 条目（新增
  `src/core/processor.py` 与两个测试文件）；evals 25/25 + 25/25、6 审计器 0
  findings、docstring 100%、1.0000 SUCCESS；`best_mcp_server --selftest` 13/13；
  `skill_cli doctor` 通过

### 注释落地的度量（temp/ 脚本可复现）
- `temp/docstring_lang.py`：1360 个模块/类/函数 docstring，**完全不含中文 = 0**
- `temp/comment_coverage.py`：`#` 注释行 2349/2665 含中文（88%）；import 语句
  660/853 带中文说明（按 import 组计）
- `temp/code_fingerprint.py check`：`compared=100, code-changed=4` —— 其中 3 个是
  本轮 pybest 还原的有意改动，1 个是子代理补的 `from __future__ import annotations`；
  其余 96 个被注释触及的文件全部零代码改动

### 过程中抓到并修复的两处并发写入损坏（均由指纹护栏发现）
- `ops/skill_cli.py`：一整块 `dl_cmd` 分派代码被重复粘贴成 `return 1` 之后的死代码
  （40 行不可达代码）—— 已删除，删除后与 HEAD 代码完全一致
- `docs/diagrams/check_macro_collisions.py`：3 个 f-string 的 `f` 前缀被删、并被加了
  `docs/` 下本不需要的 `# noqa: F541`（`docs/` 在 ruff `extend-exclude` 中）—— 已按
  HEAD 原样还原

### 评测门禁一度转红并修回（诚实记录）
- 新增的 `test_restored_surface.py` 有 5 个测试只用了 `Mock.assert_called_once_with()`
  而没有 `assert` 语句，被 `evals/audit` 的 TestsAuditor 判为"零断言测试"（Q-11），
  correctness 0.50 → 综合 0.85 FAILED。已改为显式 `assert ... .call_count == N`，
  evals 恢复 1.0000 SUCCESS。**没有为了让自己的测试过关去改审计器**
- 另记录一条审计器的已知边界：它只认 `ast.Assert` 与 `pytest.raises`，不认
  `unittest.mock` 的 `assert_*()` 系列；本仓测试风格统一用显式 `assert`，故按现状收敛

### 版本号清理（用户要求"在我们的规则内做一次扫描，将版本号等违规内容去除"）
- 全仓扫描脚本 `temp/version_scan.py`（checked=181 文件），A 类明确违规清除 71 处：
  - `Master Plan v8.0` → `Master Plan`（47 处，波及 SKILL.md/manifest.yaml/
    architecture.md/weights/README.md/rag/astro_rag.py/contracts 12 个/
    templates 8 个/evals/cases 16 个/test_gen_* 6 个）
  - `pybest-0.3.2.8` → `pybest 打包产物 (git 6f00efeb^ 可取回)`（22 处，
    去掉版本号但保住 git 追溯锚点；涉及 src/tap 七件套、src/client、
    src/pybest、src/core/processor、src/scripts/checkpoint、README、
    references/ALGORITHM-SPEC、rag/knowledge/known_issues 与两个新测试）
  - 外部站点首发版本 `v1.0.0` → 去掉字面量保留事实（2 处：
    references/photometric-systems.md、static/fragments/data_source/nadc_endpoints.md）
  - `ops/register_skill.py` 注释里的旧登记版本 `0.2.0` → 去掉字面量（1 处）
- 经裁定**保留**（不是本 skill 的发布版本，删了会破坏功能）：
  - IVOA 规范 XML 命名空间版本（VOTable v1.3 / UWS v1.0 / VOSI v1.0 /
    VODataService v1.1）—— 协议常量，`version` 与 `xmlns` 必须同代
  - `references/site-endpoints-and-interactions.md` 里的真实路径
    `package-stage-0.3.2.8/pybest-0.3.2.8/` —— 取回历史树的检索指引
  - `src/pybest.py` 注释里"旧实现 version=1.4 配 v1.3 namespace" —— 历史缺陷上下文
- 清理后复扫：A 类仅剩上述 IVOA 命名空间与真实路径，B 类 0 处
- 清理后全门禁复跑：ruff 全绿、pytest 569/22、evals 25/25 + 25/25、
  6 审计器 0 findings、docstring 100%、1.0000 SUCCESS、MCP selftest 13/13
- **遗留（不在 astro-best 边界内，需单独报批）**：生成器
  `scripts/refactor/common.py:273` 与 `scripts/refactor/materialize_tests.py:34`
  （monorepo 根）仍在产出 `Master Plan v8.0`，下次重新物化会把它带回
  contracts/templates/evals/cases/test_gen_*

### 待用户裁定（详见 docs/architecture/file-size-budget.md §6 / §6.1）
- 结构变更报批：新增 `src/core/processor.py`、`test/unit/pipeline/test_processor.py`、
  `test/unit/audit_round/test_restored_surface.py` 三个被跟踪文件
- §6/§6.1 共登记 38 条已核实但未修的问题（下载取消失效/取消后状态误报、resume 不对称、
  std 组断点找不到、RAG DOMAIN_BOOST 死通道、评测 fail-open 气味、禁版本号正则盲区、
  测试生成器会覆盖注释、环境锁白名单缺项、diagrams 硬编码绝对路径等），每一条都需要
  配套回归，属独立变更

## 用户批准的三项清理 + 惰性导出解环

### Security（用户批准）
- `.gitignore` 补 `.env`（此前只忽略 `.env/` **目录**）：`.env.example` 指示用户
  "Copy to .env and fill in your credentials"（含 `BEST_API_PASS`、
  `NADC_OAUTH_CLIENT_SECRET`），凭据文件有误提交风险。`git check-ignore -v`
  实证文件与目录双双命中

### Removed（用户批准）
- `test/upstream/` 18 个文件（约 96KB）：import 不存在的 `pybest.*` 包，模块级
  skip 恒不执行（skip 数 40 → 22）。删除前已核实其高价值断言在现役 suite 有
  等价覆盖：Range 206/416（`test/unit/tap/test_service.py`）、OAuth state 校验
  （`test/unit/auth/test_nadc_oauth.py`）、字节级 Range 续传
  （`test/unit/download/test_download_file_resume.py`）；git 历史可取回
- `ops/cloud_modelscope/remote_worker.py`：零文档/零代码引用的死入口，且
  `MS_PAYLOAD` 直接 `Path(env)` 无校验即读写
- `src/scripts/tool.py`（删除前已核查用途）：`retry` 装饰器零生产调用方（重试已
  收敛到 protocol 的 urllib3 Retry 单层，再留一份装饰器就是第二套重试实现）；
  `degrees_to_hms/dms` 全仓零引用（含 tests/docs）；`mag_to_flux/flux_to_mag`
  唯一"用途"是自家测试——无生产消费。整文件删除，连同 `test_fixes.py` 的
  Pogson 往返用例与 `src/scripts/__init__.py` 的 `retry` 再导出

### Changed（架构：解掉一条自认的导入环）
- `src/scripts/__init__.py` 改 PEP 562 惰性导出（`__getattr__` + `__all__` +
  `__dir__`）。旧 eager import 链 `best_cone_search → src.client →
  src.scripts.io` 曾迫使 `src/client.py` 把入参校验写成函数内惰性导入并自承
  "防循环依赖"；现在 client 层在模块顶部直接 import `validate_coordinate` /
  `validate_search_radius`，环消失

### Docs
- README：删 `scripts/tool.py` 与 `cloud_modelscope/remote_worker.py` 两行、
  `upstream/*.py` 一行（改登记 `unit/audit_round/`）；`scripts/io.py` 行补
  原子写/目录锚定两个单点；`references/site-endpoints-and-interactions.md` 的
  上游测试条目改为"已删除 + 覆盖位置 + git 可取回"

### 验证
- pytest 520 passed / 22 skipped（18 个 upstream 模块级 skip 消失）；ruff 全绿；
  树 SSOT 239 条目；evals 25/25 + 25/25、6 审计器 0 findings、docstring 100%
  (225/225)、1.0000 SUCCESS；`best_mcp_server --selftest` 13/13；
  `skill_cli doctor` 通过；`skill_cli download list` rc=0

## 深度审计轮 2 · 声明面对齐、复核空间接线、CSV 线规修复

### Fixed（live 实证的产物级缺陷）
- **CSV 每条记录后多一个空行**: `csv.writer` 发 `\r\n`, 落盘走文本模式又被
  翻译成 `\r\r\n` (Windows), 主下载产物每行之间多一空行 — Excel/pandas 读到
  幻影空行。`atomic_write_text` 与 `pybest._save_result` 改为 `newline=""`
  原样落盘; 新增线规回归测试 (禁 `\r\r`, 记录数=行数-1)
- **proximity 元数据列污染导出**: `_rows_from_result` 把 `inputobjs_*` 四列当
  普通列写进每个 CSV (live 实证 52 列里 4 列是匹配元数据); 现只进 JSON 的
  raw_data, 不再进 CSV/VOTable 列头

### Added（人工复核空间, 从"只写不读"到真实产物）
- **下载产物旁路信封**: `_save_result` 落盘 `<name>.provenance.json`
  (schema/data_hash/sha256/查询参数/完整性判定), 让人能核对"这个文件确实来自
  这次查询"; 信封失败只 warn 不阻断下载; live 实证 sha256 与文件一致
- **查询审计可读出口**: `BestSkillClient.audit_summary()` / `audit_history()`
  (QueryContext 此前只被喂写, summary 无生产调用方, 事后无法回答"查过哪些天区")
- **completeness_gate 诚实化**: 删除硬编码 `{"required": True, "value": 1.0}`
  假门禁; 缺省按载荷空否给出 0/1, 调用方可传真实判定
- **session_id 真复用**: 进程级缓存 (docstring 承诺复用实则每次新 UUID4, 两个
  信封无法按 session 归组); 新增 `reset_session_id()` 供会话边界使用
- **identity 解析失败记日志**: 不再静默 `except: return {}` (空 identity 无法
  区分"未授权"与"授权服务不可达")
- **`test/unit/meta/test_environment_lock.py`**: README 宣称的"依赖真实性 AST
  校验 (Q-42)"此前不存在 — 现成为真门禁 (AST 扫描 src/ops/evals/examples,
  双向断言多声明/漏声明即红)

### Changed（声明面与代码对齐）
- `environment.yaml`: 删除零 import 的 numpy/pandas/tqdm/rich/hatchling, 补录
  惰性 import 的 pyvo (src/tap/client.py 远端 TAP 模式); astropy 标注为缺失即
  显式失败的可选依赖
- `README.md`: evals 计数 12 场景/16 用例 → 25/25, cases 表补 017~025;
  input/output 契约的"由 test 守护"改为事实描述 (信封事实标准是
  `provenance.build_envelope`); local-only 表补 `.progress/` `.logs/`
- `SKILL.md`: `src.core` → `src.core.pipeline` (实测 import 路径); 兼容 API 快查
  补 `src.tap` / `src.ai_tools` / 下载栈; 场景路由补 config/refs/oauth/download/log
  五个已存在子命令; 重定向表澄清"现行 proximity 批量匹配仍属本 skill";
  标题 Legio → Legacy 笔误; 12 → 16 横切治理面
- `manifest.yaml`: 删死 sink `lightcurve_ecsv` (全仓无 ECSV 产出), 改
  `lightcurve_csv`; slidid 笔误; `batch_crossmatch` 更名 `proximity_batch` 并
  在 on_demand 指向现行 `src/crossmatch.py`

### Removed（经用户批准的删除)
- `test/fixtures/mock_data.py` + `mock_responses.py` (零引用)
- 8 个 `test_gen_algo_merged_*` (同一批算子的第四重复制, 每文件仅 1-2 个算子却
  各带 50 行相同 boilerplate; `test_gen_smoke.py` 一处保留全量断言)

### Tests
- `test/unit/audit_round/test_review_surface.py` (11): 信封 session 复用/完整性
  诚实/data_hash 一致/identity 失败日志; 旁路信封内容与 sha256 核对; 旁路失败
  不阻断下载; 审计摘要真实计数; 摊薄副本不改源记录; params 拷贝; 门控单次运行
- `test/unit/audit_round/test_audit_fixes.py` 增 2 项线规/元数据列测试
- 门禁: pytest 521 passed / 40 skipped; ruff 全绿; 树 SSOT 259 条目;
  evals 25/25 + 25/25, 6 审计器 0 findings, docstring 100% (232/232), 1.0000 SUCCESS

## 深度审计轮（4 路并行只读审计 + 受控 live 验证）· 架构收敛与门禁去假

### Fixed（数据完整性 / 架构裂缝 / 门禁诚信）
- **测光波段归属 (P0)**: `BestSource.from_row` 改为消费
  `protocol.CATALOG_MAG_COLUMNS` / `CATALOG_MAG_ERROR_COLUMNS`; 旧"列名前缀猜
  波段"把 `ps1_gflags=16416`、`ps1_ruwe` 当 g/r 星等, 把 `stripe82_ummed/unobs`
  当 u 星等, 并整列丢弃 Gaia/Landolt/J-PLUS 测光 (2026-09-30 live 实证)
- **单层重试**: 删除 `Best._request` 手写重试循环 (与 adapter Retry 叠加, 一次
  瞬时失败最坏 ~16 次 wire 请求 + 双倍 backoff); 两个重试测试改到 urllib3 传输层
  打桩 (旧测试 mock `Session.request`, 位于重试层之上, 结构性失明)
- **eval 门禁去假**: connection_info 探针不再真实联网 (25 个探针经
  `Session.request` 守卫实测零外网); http_status 门禁不再由用例文件名派生 actual
  (恒真比较); correctness 删除"无 finding 即 1.0"死分支; ADQL 校验被真实测试
- **取消失效**: page observer 的控制流异常 (JobCancelledError) 重新抛出, 不再被
  `_fetch_sqlid_data` 吞掉 (Ctrl-C 曾被忽略, 下载照常完成并覆盖文件)
- **断点续传**: `DownloadManager.resume` 委托 `BestDownloader.resume_job` 原地续传
  (旧实现重提新 job_id → 从第 1 页重下 + 旧 checkpoint 永久泄漏); checkpoint 落到
  manager 的 `checkpoint_dir` (旧为 CWD 相对 `.checkpoints/`)
- **checkpoint 碰撞/逃逸**: job_id 改 constraints 指纹 hash (两次不同下载曾共用同一
  checkpoint, 互相写入对方 sqlid 的数据); job_id 经 `resolve_within` 校验 (拒绝对
  路径/盘符/斜杠/.., Windows 下 `C:/evil.json` 曾可击穿旧守卫); 损坏 checkpoint 返
  None 而非崩任务
- **公式注入补齐**: 下载主通道 CSV/TSV/VOTable、`io.to_csv`、`lightcurve.to_csv`
  全部接入 `csv_safety`; `to_csv` 表头改并集 (旧取首行键, 异构行丢列/ValueError)
- **健壮性**: 限流加锁 (线程池下曾可被绕过); `Best.crossmatch` 记录逐坐标失败
  (旧 `except: pass`); 交叉匹配按输入顺序返回 (旧由线程完成顺序决定); 缺 ra/dec 的
  源显式报错 (旧默认 (0,0) 真实天区)

### Changed（架构收敛, 不破坏分层）
- protocol 新增 `magnitude_column` / `quality_column` / `proximity_radec_text` /
  `BEST_BASE_URL` / `REQUEST_TIMEOUT` / `QUALITY_COLUMNS`; band/质量列名三份矛盾
  副本 (client 恒 `f"{band}psf"` / pybest·query `ps1?psf:mag`) 全部收敛
- `BestClient` 新增公共接缝 `submit_phase1` / `submit_query` / `fetch_page` /
  `count` / `crossmatch_batch`; downloader/crossmatch/ai_tools 不再越界访问私有方法
- sqlid 提取统一 `protocol.parse_sqlid` (两处内联正则副本删除); `CatalogType.
  display_name` 委托 `CATALOG_DISPLAY` (双份键集不一致的副本删除)
- `BestQueryResult.error_code` 类型化错误码 (替代 ai_tools 对错误消息的字符串嗅探)
- `src.scripts.io` 新增 `atomic_write_text` / `resolve_within` (8 份原子写副本 + 4 份
  强度不一的路径守卫收敛); `to_dataframe` / `load_json` / `list_jobs` 死代码删除
- 36 个文件清理重复 docstring 锚点与失效 `astro_best.*` 包路径; User-Agent 版本字面量
  移除 (禁版本号铁律); `verify_tree_integrity` 收录 `.progress/` `.logs/`;
  `skill_cli download` 6 个子命令不再因 `--workers` 缺失崩溃 (P0)

### Tests / Verification
- 新增 `test/unit/models/test_magnitude_mapping.py` (12) 与
  `test/unit/audit_round/test_audit_fixes.py` (13): 覆盖 12 星表波段往返、列序
  无关性、取消化、checkpoint 指纹与逃逸、公式注入、确定性排序、typed error_code
- 门禁: pytest 517 passed / 40 skipped; ruff 全绿; README 树 SSOT 268 条目;
  evals 25/25 场景 + 25/25 用例, 6 审计器 0 findings, docstring 100% (229/229),
  综合 1.0000 SUCCESS (且门禁本身已去假)
- live 受控验证 (temp/live_audit_round.py): ps1 锥搜 2339 命中 (服务端 total +
  truncated 诚实上报), 星等按 live 列正确归属且 flags/RUWE 不入测光, 2 坐标
  proximity 批量匹配一次 POST 成功并按输入行标注

### 已知遗留 (下一轮)
- README/SKILL/manifest/environment.yaml 与代码面的计数与能力描述对齐
- `test/upstream/` 18 个模块级 skip 死文件 (约 1500 行) 的迁移或删除
- 测试 CWD 污染 (默认 output_dir) 与 `os.environ` 直写改 monkeypatch
- `task_log` / `provenance` 信封"只写不读"接线 (下载产物带 data_hash/lineage)
- UWS 作业相位历史 (tap_job_phase_log) 落库

## 2026-09-30 · ISSUE-LIST 全修（P0/P1/P2/S 26 项）+ TAP/OAuth 恢复 + 工具面 + README 治理

### Fixed（ISSUE-LIST 本仓归属 26 项, 逐项落地+回归）
- **P0-3 软 404**: `src/protocol.py` 新增 `is_soft_error/Soft404Error`
  (两个 live 实证错误体 + 容错 JSON 回退); `BestClient` phase-1/phase-2 与
  `Best._request` (唯一收口) 全面接线; 错误码契约新增 `BEST_1006=E_SOFT_404`;
  软错误从"静默空结果"变为显式失败 (http_status 门禁恢复判别力)
- **P0-2 真实计数**: `BestClient._count` (getcount) 接入 `_fetch_sqlid_data`;
  `BestQueryResult.truncated` 新字段; `total_count` 取服务端值; V-4 live 实证
  (约束会话 getcount 稳定: 770 精确一致, 156676 行正确 truncated)
- **P0-1 批量匹配**: `BestCrossMatch.crossmatch_batch` / `Best.crossmatch_batch`
  走 `pos.type=proximity` 多行文本 (一次 POST 替代 N 次锥搜); 保留逐点路径做
  回归基线与自动 fallback (mode=per_coordinate_fallback); V-2/V-3 live 实证
  (N=1000 → 745 命中/约 3s; 12 星表默认投影全部可用)
- **P1-8 站点能力接线**: `resolve_name` (/nss/solve, 哨兵 ra=dec=-1000 显式判
  E_NAME_UNRESOLVED; live: M31 → 10.68470833/41.26875); `showcol` 列投影
  (裸名/前缀名/限定名三拼写经 qualify_column 白名单); 服务端 `sort`/`order`;
  `cone_nearestonly`/`proximity_nearestonly`; `pos.defaultRadius`
- **P1-4**: 移除反推的 EasyUI filterRules 二次约束源 (判定性 live 实验:
  razor-thin 约束带/不带均 0 行 → phase-1 键已约束会话; 站点自身 URL 亦无此参);
  同时消除 grater/greaterequal 语义合并与 contains 的 float() 崩溃
- **P1-6**: 重试策略收敛到 `src/protocol.py` 单一定处 (RETRY_STATUS_CODES/
  parse_retry_after/backoff_delay/is_retryable_status), 两个客户端同源配置,
  `respect_retry_after_header=True`
- **P1-7**: 公开数据面默认路径不再取 CSRF (单测钉死: cone_search 只触 /sqlid/ URL)
- **P1-10**: `BestQuery.cone/box` 改为记录原生区域 + `to_form()` 委托 protocol
  (与 BestClient 同一权威表单层; 旧 box-between 路径结构性失效)
- **P2-12/S-1**: `Best` 单类 VOTable 落盘 XML 转义 (`_xml_escape`; astropy 回读回归)
- **S-2/S-3**: 工具面信封 `content_trust: untrusted` 标注; ResolvedName.remark
  单独字段 + `remark_external` 外部来源标注
- **数据语义 (live 抓)**: `BestSource.from_row` 跳过 proximity 元数据列
  (inputobjs_* 以 i 开头曾被吞成 i 波段星等) + ≈-1000 哨兵不当测光
  (`NULL_MAGNITUDE_SENTINEL=-999`, TAP 序列化共用同阈值)

### Added（IVOA TAP 适配层恢复, src/tap/ 7 模块 + 77 测试）
- `src/tap/adql.py`: 有界 ADQL 子集解析 (JOIN/GROUP/子查询/聚合/越界 OR 拒绝)
- `src/tap/executor.py`: 计划→两阶段协议翻译 + 合并去重 + 稳定排序 (空值末位)
  + MAXREC 溢出探测 (MAXREC=0 元数据态不触网)
- `src/tap/formats.py`: VOTable/CSV/FITS 序列化 (OVERFLOW 标记, 哨兵→NaN)
- `src/tap/jobs.py`: UWS sqlite 作业存储 (PENDING→…→COMPLETED/ERROR/ABORTED
  CAS 相位迁移, per-principal 配额, 重启收敛在跑作业)
- `src/tap/client.py`: BestTapClient (pyvo 可选依赖, 惰性导入)
- `src/tap/service.py`: stdlib `http.server` TAP 路由 (sync/async/VOSI/
  TAP_SCHEMA, Range 206/416, Bearer 失败 401 严禁降级匿名)
- 历史来源: pybest 打包产物 (`git 6f00efeb^` 可取回, 曾被 Phase 8
  扁平化重组从 best 分支删除); 迁回忆审见
  `references/site-endpoints-and-interactions.md` §8; OAuth 现行版即其演进
  (`src/auth/`, 无需回迁)

### Added（智能体工具面 + MCP 传输）
- `src/ai_tools.py`: ToolBox 7 原子工具 + 统一信封 (data/status/cost/
  provenance) + `best://` 稳定 URI; `cost.http_requests` 为真实 wire 计数
- `ops/best_mcp_server.py`: MCP stdio JSON-RPC 2.0 (initialize/tools/list/
  tools/call), 零第三方依赖, `--selftest` 离线 13 项
- `references/tools.schema.json` + `references/llms.txt`: 工具契约与智能体索引

### Docs / 治理
- README: **删除 tashan/TopicLab 平台部署段**; 治理规则新增第 6 条
  **数据边界 (禁外泄/禁打包)**; 边界表更新 (src/tap、ai_tools、MCP、工具 schema);
  树 SSOT 重生 (242→264 条目)
- ALGORITHM-SPEC: 去"版本: v1.0"字样; §1 补软 404/getcount/站点能力接线;
  §2 锚点表纠错 (旧路径 astro_best/* 已不存在); 新增 §5 proximity/§6 TAP/§7 工具面
- site-endpoints-and-interactions: 新增 §6bis (filterRules 冗余判定/分页排序
  非确定/getcount 约束会话/proximity N=1000/ps1 哨兵) 与 §8 TAP 迁回忆审
- known_issues: 修正 _build_filter_rules 陈旧条目; 新增分页非确定 + 5 条已修复留档
- lessons_learned: +5 条 (P0 live 判定方法/哨兵污染/测试补丁生命周期/TAP 误删迁移)
- best_practices: +3 条 (proximity 批量/TAP 网关/工具面)

### Verified
- live 受控预算 (~60 请求): M31 解算逐位一致; bogus 名 E_NAME_UNRESOLVED;
  proximity 8 坐标 2 请求; N=100/500/1000 全通过; 12 星表 smoke;
  filterRules 判定性实验 (带/不带均 0 行); getcount 770/156676 两级
- pytest **+188** (TAP 77 / ai_tools+MCP 25 / 软404+getcount+名称解算+参数贯通
  集成 / protocol 安全 / query 委托 / VOTable 转义 / 哨兵 等; 305→493 passed,
  40 skipped); ruff 全绿; evals 场景 **25/25** (+6), 用例 **25/25** (+2),
  审计 6 过 0 findings, docstring 100% (223/223), 总分 1.0000 SUCCESS

## 2026-09-30 · 精准下载 + 任务日志管理器 + architecture.md 焕新

### Added（精准下载对应数据）
- `src/download_precise.py`: PreciseDownloadJob — source_id 列表经
  `{table}.{id_col}` **in 约束**（textarea 换行分隔）只取指定行; 列投影;
  星表 ID 列映射 (`stripe82=calibstars_id` 裸列名 / 其余 `{catalog}_source_id`);
  行数回核 (0 行 hook ask / 部分命中 WARN); ≤1000 ID 上限 (超出 hook ask)
- hook 新 severe 种类: `empty_precise_result` / `precise_id_list_too_large`
  (各带 ≥2 建议方案); DownloadManager 分发 PreciseDownloadJob (后台/进度/
  续传/hook 俱享); CLI `download start --source-ids ID1,ID2`

### Added（任务日志管理器）
- `src/task_log.py`: TaskLogger — `.logs/task_log.jsonl` append-only JSONL
  (原子行追加, 单行截断防护); 事件 submit/start/page/done/blocked/failed/
  cancelled/hook/query; tail/problems/tasks/summary 查询; 与 .progress 分工
  (日志答"发生了什么", 进度答"到哪了")
- DownloadManager/hooks 全链接线 (submit/start/done/blocked/failed/cancelled
  + hook 拦截 warn); CLI `log tail/problems/tasks/summary`

### Fixed（live 实证缺陷, 精准下载轮次）
- 精准下载约束曾以 dict 传入 downloader 路径 -> AttributeError (live 抓);
  改传 ColumnConstraint 对象 (单测钉死对象类型)
- `normalize_ids` 把 None 转成字符串 "None" -> 显式跳过 None
- `BestSource.from_row` ID 别名表漏 `calibstars_id` (stripe82 响应用裸列名,
  live 实证) -> ID 丢失; 已补 (回归测试 test_calibstars_id.py)
- `.gitignore` 补 `.progress/` 与 `.logs/` (运行时状态, 用户批准)

### Verified
- live: stripe82 真实 ID (`CALIBSTARS_0844369/0841102`) 精准下载 **2ID→2行**
  精确返回, 任务日志事件链 submit→start→query→page→query→done;
  证据 temp/live_precise_results.json; ps1_source_id 线上为空 (锥搜/矩形实证,
  temp/diag_cols.py) -> ps1 精准下载走 hook ask (设计内)
- pytest **+28** (task_log 8 / precise 17 / calibstars_id 3, 全绿; 总数
  277→305 passed, 40 skipped);
  evals 场景 **19/19** (+precise_download/task_log), 用例 **23/23** (+2),
  审计 6 过 0 findings, docstring 100% (173/173), 总分 1.0000 SUCCESS
- architecture.md 去版本号字样; oauth_identity 由"预留"改"已实现"; local-only
  目录补 .progress/.logs; 新增 §4 下载 hook 分级与 ask 纪律; §3 补下载能力栈
  与文档分层铁律

## 2026-09-30 · 下载能力全家桶（后台/进度/并行/续传/hook）+ 交融验证

### Added（src 三新模块 + CLI 子命令组 + 使用向 playbook）
- `src/download_manager.py`: DownloadManager — submit 即返回 (ThreadPoolExecutor
  默认 2 并发, 前台对话不阻塞), Region/Sqlid/File 三类任务, cancel (页边界
  终止)/resume (spec 重建), hook 接线, 并行唯一文件名 (星表+天区+半径+格式)
- `src/download_progress.py`: ProgressStore (.progress/<job>.json 原子写,
  CLI/GUI 同源事实源) + ProgressTracker (页/字节累加, 速度/ETA, blocked/
  finish/fail/cancel) + render_text_bar (文本条, Windows GBK 自动回退 ASCII)
- `src/download_hooks.py`: 分级 hook — network 类 (超时/429/5xx) 指数退避
  重试 ≤3 才拦截; severe 类 (checksum/disk/session/pagination/path) 立即拦截;
  HookInterrupt.to_ask_payload (原因+证据+≥2 方案) — **拦截必须 ask, 严禁静默**
- `src/pybest.py::download_file`: 字节级断点续传 — .part 半成品 + HTTP Range
  (206 续传/200 忽略则整重/失败保留 .part) + 进度/取消接线
- `ops/skill_cli.py`: `download` 子命令组 — start (前台+实时进度条, Ctrl-C
  取消)/status/progress/list/cancel/resume/asks (非零退出=必须 ask)
- `references/download-playbook.md`: 下载能力唯一使用向 SSOT (后台模型/进度
  同源/并行/两级续传/hook ask 纪律/常见需求表/13 类常见坑解法/交融验证)

### Changed
- `src/downloader.py`: download_region/download_by_constraints/download_sqlid
  增 on_page_observer 贯通 (管理器页进度依赖; checkpoint 逻辑不变)
- `rag/knowledge/best_practices.yaml`: +4 条 (后台下载/两级续传/hook ask/坑解)
- README: src 边界表 +3 模块, references 表 +playbook; 树 SSOT 217→231

### Fixed（live 实证缺陷）
- 并行任务自动同名 (best_ps1_c2.csv) 互相 os.replace 覆盖 → 管理器按
  (星表,天区,半径,格式) 生成唯一名 (live 复验: 两任务 74KB 各自落盘)
- run_network 把非网络异常误包装成 network ask → 仅网络类重试/拦截,
  其余原样抛出 (单测钉死)
- render_text_bar 块字符在 GBK 控制台崩 → 编码探测回退 ASCII

### Verified
- pytest **277 passed / 40 skipped** (+53: 63 下载单测 + 10 交融集成)
- live 冒烟 (temp/live_bg_smoke.py): 2 并行后台任务, 前台轮询不阻塞,
  ~3s 双 done, 唯一文件名, 100% 进度条; 证据 temp/live_bg_download_results.json
- evals: 场景 **17/17** (+5: background/parallel/resume/hook_ask/progress),
  用例 **21/21** (+5), 审计 6 过 0 findings, docstring 100% (161/161),
  总分 **1.0000 SUCCESS**
- 交融集成 (test/integration/test_download_feature_integration.py, 10 用例):
  crossmatch→后台下载→光变导出→pipeline→query→单类 Best→provenance 全链并存

### 教训回写 (4 条)
- L-download-parallel-filename-collision / L-download-hook-exception-taxonomy /
  L-progress-bar-gbk-fallback / L-live-hang-isolate-before-conclude

## 2026-09-30 · 网站源码深潜 + Reference 分层重组（references=使用向 / rag=论文引文）

### Added（实机浏览器深潜, Playwright/Chromium, 证据 temp/site_dive/）
- 新增 `references/site-endpoints-and-interactions.md`（智能体使用向 SSOT）:
  路由全表 16 条 (含新发现 `/nss/solve` 名称解算、`/t/{table_id}` 列元数据、
  `/{group}/doc/{ts}` 分组描述页、`/user/email-exists`); 查询表单全字段清单
  (204 字段名, 30 列 × 5 约束子字段, operation 十取值, solve 按钮 AJAX 协议);
  结果页交互 (dbgrid POST 协议/Save page vs Save all/SAMP table.load.votable 推送/
  download_selected/download_sqlid 隐藏表单 POST); CSRF/X-CSRFToken 约定;
  登录态边界 (公开数据面免登录, /jobs 需 OAuth); Live 状态快照; 复现步骤
- 新增 `rag/knowledge/citations.yaml`: 11 条论文引文 (9 verified + 2 unverified),
  含题名/作者/期刊/卷期页/DOI/arXiv/BibTeX/核验方式; RAG 引擎自动加载可检索

### Changed（知识分层: references 只留使用向, 引文下沉 rag）
- `references/photometric-systems.md`: §3/§4 论文引用表/BibTeX 块移出,
  改留 short-id 指针 (C-*) 指向 citations.yaml; 精度/规模/测光系统等使用向内容保留
- `references/best-database-guide.md`: 概述引用段改为 citations.yaml 指针,
  新增 site-endpoints-and-interactions.md 入口
- `references/ALGORITHM-SPEC.md`: §1 补深潜取证的新端点一句; §5 DOI 表改为
  citations.yaml 权威指针 (9 verified/2 unverified)
- `static/fragments/data_source/{best_catalogs,nadc_endpoints}.md`: 引用段改指针;
  endpoints 片段补 /nss/solve、分组 doc 页、dbgrid live 状态、X-CSRFToken 约定
- `README.md`: references/ 与 rag/knowledge/ 边界表补两个新文件; 树 SSOT 215→217

### Verified（Live 状态快照, 2026-09-30）
- 两阶段 GET 协议 / nss/solve / 表单页 / 列元数据 / 分组页 / 文档页全部正常
- **dbgrid 数据口对匿名会话挂起** (浏览器 >75s 无响应含强制 reload; requests 快速
  `{"error":"Internal Server Error"}`) — 站点自身网格数据通道当前不可用,
  GET 分页仍是权威取数路径 (本 skill 设计正确)
- 门禁: pytest 224 passed/40 skipped, ruff 绿, verify 树 217 条目 exit=0,
  eval 1.0000 SUCCESS

### 教训回写
- L-reference-layering-usage-vs-citations: 文档分层先问"谁消费"
- L-dbgrid-endpoint-hangs: 站点缺陷的两种表现 (挂起/报错) 都要记录

## 2026-09-30 · Reference 丰富（官方文档采集）+ 真实联通测试（f7f63a45 + c169c230）

### Added（references 四面 + 一新文件, 用户批准范围: 全部四个面）
- 新增 `references/photometric-systems.md`: 官网 doc/system-en 三页镜像 —
  19 个测光系统全表 (波段/星数/作者), SCR 单星精度口径 (u/v 类 0.01–0.02 mag、
  grizy 类 0.001–0.005 mag), 恒星参数筛选 (矮星 4500–6500 K, Av<0.1), 8 个
  Well-Calibrated 表精度/规模/文献, User-Defined FITS 上传协议 (3360–10200 Å),
  官方引用块 (BibTeX), 复现方法; README 边界表 + 树 SSOT 同步 (214→215, verify 过)

### Changed（引用状态: unverified-source → Crossref 实核 verified）
- 官网 help 页 Citation 段 + catalog 页文献逐条 Crossref REST 核验:
  **9/9 verified** — Huang et al. 2024 (ApJS 271 13, 10.3847/1538-4365/ad18b1,
  官方 BibTeX), Xiao&Yuan 2022 (AJ 163 185), Xiao+ 2023 (ApJS 268 53), Yang+
  2021 (ApJL 908 L24), Huang&Yuan 2022 (ApJS 259 26 — 期刊名官网缺失, Crossref
  补全), Xiao+ 2023 (ApJS 269 58), López-Sanjuan+ 2024 (A&A 683 A29), Xiao+
  2024 (ApJS 271 41), Li+ 2025 (ApJS 277 26); 主引用 Xiao 2025 (Scientific Data,
  submitted) 仍无 DOI 保持 unverified-source
- `references/best-database-guide.md`: 引用段升级; 新增 User-Defined/jobs 协议与
  批量上传口径 (<1000 万源/文件, CSV 只含 ra/dec 列头); 核查方法补 2026-09-30 采集
- `static/fragments/data_source/{best_catalogs,nadc_endpoints}.md`: 同步引用/精度/
  jobs 协议/文档页三件结构
- `rag/knowledge/known_issues.yaml`: citation 条目更新 (Huang 2024 可验);
  新增「文档页星表与可查询现实偏差」条目
- `references/ALGORITHM-SPEC.md` §5: 新增已核验 DOI 表 (9 条), DOI 核验状态表更新

### Fixed（文档错误 — 表单页实证）
- best-database-guide.md 字段表 `pos.radius` 单位「度」→**角秒** (表单页原文
  `radius <input name="pos.radius"> arcsec`; 传度得 0 行/360 倍半径);
  proximity 文本区补 `ra,dec[,radius_in_arcsec]` 格式说明

### Verified（真实联通测试, 无登录态, 预算内: 7 请求/轮 × 2 轮 + Crossref 12 次）
- 全链路 PASS (temp/live_connectivity_results.json): /ps1/f (csrf+30 列) →
  POST /ps1/q (cone 180″) → sqlid=s3898 → CSV 首页 10 行 (表头 inputobjs_* +
  ps1_ra/ps1_dec/ps1_gpsf/ps1_ipsf/ps1_rpsf) → getcount total=1870 → /t/346
  30 列 → skymapper_dr4/f 软 404 复验 → calib/gaia_dr3_18/f 分组前缀 200
- `PYBEST_RUN_LIVE=1 pytest test/live`: 首跑 2 failed 5 passed → 修复后 **7 passed**
- 四条教训回写 lessons_learned.yaml (pos.radius 单位/fits+votable 落盘缺陷/
  文档-现实偏差/Crossref 引用升级)

### Fixed（live 暴露的实现缺陷 — c169c230）
- `src/pybest.py::_save_result`: (1) fits 无写入分支 → tmppath 从未创建 →
  os.replace FileNotFoundError; 按 guide「导出需本地转换」口径补本地 FITS 转换
  (BinTableHDU, 数值列 float64, astropy 缺失清晰报错); (2) votable 列类型按名猜
  漏判带表前缀实测列名 (ps1_ra/ps1_dec 判 char → astropy 解析为字符串) → 改按
  整列取值推断 (_column_is_numeric)
- 两个修复各补离线回归测试 (mocked); pytest 224 passed/40 skipped, ruff 绿,
  eval 1.0000 SUCCESS, verify 树 215 条目 exit=0

### Deferred（外部前提, blocked-on-approval）
- NADC OAuth client_id/secret 审批 (support@china-vo.org) — 真实授权流与
  /jobs 作业流仍待审批后验证; 本轮按用户选择仅测公开端点, 不使用浏览器会话

## 2026-09-26 · Phase 2b gen_algo 合并参数化（deferred 项清零）

### Changed（Q-33 落实: 12 个公式化单测文件 -> 8 个能力域参数化文件）
- test/unit/{client,config,crossmatch,download,lightcurve,pipeline,query,scripts}/
  test_gen_algo_merged_<域>.py: 共享导语一份 + @pytest.mark.parametrize 覆盖
  全部 12 算子 (import + 属性 + 可调用三级断言, 依赖缺失显式 skip)
- 合并后测试数不变 (222 passed/40 skipped), 断言零丢失; 文件净减 4
- 合并文件唯一命名 (test_gen_algo_merged_<域>.py) — 首批同名触发 pytest
  撞名收集错误 (无 __init__.py 时的经典冲突), 加域后缀解决

### Deferred（有意记录, 非遗漏）
- upstream tap_* 8 文件 topic 合并: 均为永久 skip 的 legacy 资产 (pybest 包不存在),
  拼接有跨文件符号碰撞风险, 而收益仅是文件数; 保留现状 (目录已去版本号,
  skip 原因已文档化, G10 skip 预算全归类)。后续如需合并应先做符号冲突审计。

## 2026-09-26 · Phase 8 实网受控取样与全链路验收（重构完成）

### Verified（实网受控取样, compute_budget 内: BEST 3 请求 + OAuth 1 请求, 样本 <100）
- **V-0**: nadc.china-vo.org/data/best 可达 (HTTP 200)
- **V-1/V-2 (Q-01 修复的活服务器证据)**: protocol.build_query_form 的
  pos.type=cone + pos.racenter/deccenter/radius + showcol + output.fmt=html 表单
  被活服务器接受, 两阶段协议返回 sqlid=s3878, 3 源带 inputobjs_* 邻近列 —
  旧 box-between .constraint 键集不相交缺陷确认消除
- **V-2/V-3 (表头与分页实证)**: rows=2 分页 page1/page2 各 3 行 = 1 表头 + 2 数据行 —
  表头确实存在 (parse_csv_rows has_header 动态判定有实证), 分页参数语义正确
- **V-6**: oauth.china-vo.org 首次 ConnectionReset (瞬时), 重试 HTTP 200 —
  探测类失败一次重试再记 baseline_debt 的教训入册; 真实授权流 blocked-on-approval
- 结果存档 temp/live_sampling_results.json, 四条教训回写 rag/knowledge/lessons_learned.yaml

### Fixed（验收门禁抓出的 Phase 4 遗留）
- Q-56: pipeline.yaml 三个 tool 符号改正为可 importlib resolve 的真实路径
  (src.best_cone_search -> src.scripts.best_cone_search.cone_search;
  src.quality_gate -> src.core.QualityGate; src.crossmatch ->
  src.crossmatch.BestCrossMatch) + 「声明点必须可 resolve」由验收探针强制执行
- Q-57: pipeline.yaml dependencies 移除虚构的 astro-common (两处探测根均不存在);
  sub_skills 改指仓内真实存在的 astro-catalog
- pipeline.yaml 注释残留版本号清除 (禁版本号铁律)
- environment.yaml 显式声明 urllib3>=2.0 (src/ 直接 import Retry; 原仅 requests 传递)

### 验收（§13 门禁全链路, temp/probe_final_acceptance.py, 9/9 PASS）
- G1 突变矩阵: M13 复测 CAUGHT (M8/M10/M11/M12 由 Phase 3 矩阵 5/5, M14 由 Phase 4)
- G2 eval 有效性: 1.0000 SUCCESS (Phase 5 两种生产突变均被抓)
- G3 lint 口径: ruff check . 全绿 (与 make lint 范围一致)
- G4-6 测试: pytest 222 passed / 40 skipped / 0 failed
- G7 声明面: pipeline.yaml tool 符号全部可 resolve
- G9 禁版本号: 全仓 version 标记残留 = []
- G10 skip 预算: 31 条 skip 明细全部可归类 (legacy import/live 门控/依赖缺失)
- G11 依赖真实性: AST 第三方 import {pandas,requests,urllib3,yaml} 全部已声明
- G12 树 SSOT: verify 218 条目 exit=0
- make all 等价链 (本机无 make, 手动执行): lint -> test -> eval -> verify -> doctor 全绿

### 重构总账（Phase 0-8, 9 个 Conventional Commit）
- 84da4e7c 结构对齐与治理基石 / 5e08baff 去版本号与死资产 / 17f41ab7 test 重组 /
  60d1d127 科学正确性 P0 / b9534006 链路与声明面 / 2b616ac2 evals 重建 /
  1027452a NADC OAuth / 55f277bf 注释全覆盖 / 本轮 Phase 8 验收
- 测试 166 -> 222 passed; eval 从假门禁 (恒定 1.0) 到真门禁 (阻断性 + 反证夹具);
  突变矩阵 8/8 转红 (M8-M14); docstring 100%; 文件树 SSOT 门禁运行全程

## 2026-09-26 · Phase 7 注释全覆盖

### Changed（21 个模块头升级为三要素: 职责 + 能力边界 + 白盒锚点）
- src/ 全部模块 (client/pybest/protocol/crossmatch/downloader/query/lightcurve/
  csv_safety/core.pipeline/models.input/models.output/scripts 八件/kb/auth 已有)
  模块头追补能力边界 (做什么/不做什么/越权拒绝) 与白盒锚点 (ALGORITHM-SPEC §N /
  contracts 引用); kb 与 auth 与 provenance 本就富含三要素跳过
- 修正 enrichment 脚本两处事故: docstring 闭合引号外插入 (SyntaxError) 与
  单行 docstring 未拆分 — git 还原后以修正版重跑, pytest 全绿证明无损伤

### Added（关键算法行内注释: 公式 + 量纲 + 设计理由）
- crossmatch._angular_separation_arcsec: haversine 公式逐项注释 + cos(dec) 因子
  语义 (dec=30° 面上 1°RA 跨 3600·cos30″≈3117.8″) + asin 定义域防护 + M5 守护引用
- protocol.parse_csv_rows: 表头动态判定设计理由 (三套互斥假设的历史与 M8 突变
  存活教训, Q-02/Q-05 根因)
- client._fetch_sqlid_data: phase-2 分页参数语义 (output.fmt/rows/page/filterRules)
- csv_safety: 修正 enrichment 造成的前缀重复 (白盒锚点:)

### 基线
- docstring 覆盖率维持 100% (Phase 5/6 已达); 模块头三要素 21/21 (kb/auth/
  provenance 本就达标); pytest 222/40; ruff 全绿; eval 1.0000; verify 218 exit=0;
  doctor 正常

## 2026-09-26 · Phase 6 NADC OAuth 接入

### Added（src/auth/ 身份层, contracts/oauth.contract.yaml, 19+12 测试）
- `src/auth/nadc_oauth.py`: NADC 通行证 OAuth2.0 (仅 Authorization Code 模式) —
  build_authorize_url (state 防 CSRF, 缺省随机生成) / exchange_code (grant_type=
  authorization_code, HTTP 错误显式抛) / get_profile (Bearer 空格规范, 业务码校验) /
  build_logout_url / TokenStore (~/.astro-best/nadc_token.json, 0600, obtained_at/
  expires_at, is_expired 提前 60s 判过期) / run_local_callback_flow (127.0.0.1 临时
  端口收 code + state 校验 + 超时) / run_manual_paste_flow (回调 URL 或裸 code)
- `contracts/oauth.contract.yaml`: 端点表 (authorize/token/profile/logout) + 参数
  来源 (env) + profile 字段 (umtId/unionId/ldap_id/name/email/phone/confirmed/
  locked/avatar_url) + token 生命周期 (无 refresh, 过期重走) + 失败模式 (409/401/
  state_mismatch) + 双轨边界声明
- `references/ALGORITHM-SPEC.md` §4 OAuth 白盒: 端点/量纲/协议四步/真源码锚点/
  交互模式/双轨边界 (BEST form 登录不变; Bearer token 接受性列 V-6)
- `.env.example`: NADC_OAUTH_CLIENT_ID/SECRET/REDIRECT_URI (默认回环地址)
- `ops/skill_cli.py oauth` 子命令: login (本地回环)/url (仅打印授权 URL)/paste
  (手动粘贴)/status/logout
- 外部前提登记: client_id/secret 需 NADC 管理员审批 (support@china-vo.org),
  blocked-on-approval; 未获批期间全 mock 测试覆盖

### Added（provenance envelope 实现, Q-08 接线路线）
- `src/provenance.py`: build_envelope (astro-envelope-v1: data_hash SHA-256 确定性
  排序键 + session_id UUID4 + NADC 身份 umtId/ldap_id + lineage inputs/outputs_ref +
  completeness_gate) / compute_data_hash / identity_from_token_store (未授权返回
  空 dict 不阻断) / envelope_for_result
- Q-52 载体接线: BestSkillClient 持有 QueryContext, cone_search 后 record 真实计数
- models/output.py 四个输出模型保留为契约匹配实质模型 (Phase 3 偏差记录), 现由
  envelope_for_result 提供真实构造注入点

### Fixed（评测器与测试即时抓住的问题）
- oauth.contract.yaml 引号未闭合 (logout WebServerURL note) — contracts 审计 CRITICAL
  检出后修复; static entry 陈旧路径同类问题第二次被审计抓住, 证明审计层有效
- auth 模块 9 个公开函数 docstring 补齐 (覆盖率维持 100%)
- _Handler 方法 docstring 插入位置错误 (脚本事故) — pytest 收集错误检出后修复

### 验证（出口）
- pytest 222 passed / 40 skipped (auth 19 + provenance/CLI 12 全绿); ruff check . 全绿
- eval 1.0000 SUCCESS (docstring 100% 114/114); 凭据零字面量扫描通过 (唯一匹配为
  env 变量名常量); verify 树 218 条目 exit=0

## 2026-09-26 · Phase 5 evals 质量评审层重建

### Changed（eval_runner.py 全面重建, EVAL-01~10 教训全量落实）
- 无 fail-open: 未知场景 id 显式 FAIL (旧实现 reason="generic scenario verified" 放行);
  spec/契约/用例缺失即 FAIL; 分类不了的用例记 FAIL
- -O 安全: 校验逻辑全部显式返回/条件, 不用 assert (python -O 不得退化)
- 输入必喂: 12 个场景各注册真实探针 (BestQuery 流畅构造/protocol 表单键集/haversine
  已知值含 cos(dec) 因子/QualityGate 三态判定/约束 operation 编码/星表登记+别名/
  光变入口/负 RA 拒绝/ADQL 语法/校验和算子/info 信封无版本字段); 16 用例真实执行
  (http_status actual 不再取自文件名; checksum 走真实 compute/verify; 算法用例
  import+调用非 hasattr; scope 校内容 token; field 校 type/unit)
- 权重代码校验: 权重和 != 1.0 启动即败; pass_score (0.9) 必须高于 WARN 线 (0.85)
- 阻断性条件: 场景/用例/审计任一失败不论加权分高低一律 FAIL (旧实现恒定 1.0000
  假门禁的根因消除)
- scoring-rubric.yaml 重建: 五维 (correctness 0.3/gate_compliance 0.25/
  determinism 0.15/provenance 0.1/docstring_coverage 0.2, 和=1.0)
- --mode behavior|audit|all; --json; make eval 接入 check/all 阻断

### Added（evals/audit/ 六审计器 + 反证夹具）
- references 审计: 白盒五要素痕迹 (量纲/公式/端点/协议/复现) + TODO/占位 + 版本标记
- knowledge 审计: YAML 可解析 + 非空 + BOM 检出
- templates 审计: 禁版本标记 + best-config defaults 键位 (base_url/timeout/min_snr)
- contracts 审计: 必需五契约存在 + 可解析 + 非空 + input/output 字段 token 交叉引用
- static 审计: core 三件非空 + two_stage_async_mode entry 符号可导入
- tests 审计: assert True / mock __init__ (Q-11 模式) / 零断言测试 / 无理由模块级 skip
- 每审计器附 broken 坏样本, runner 验证坏样本必须被拒绝 (坏样本过=审计器无效=CRITICAL)

### Fixed（评测器重建后立即抓出的真问题）
- static/fragments/algo_mode/two_stage_async_mode.yaml entry 陈旧路径
  (src.client -> src.client, Phase 0 平铺遗留)
- references/pybest-api-reference.md 补白盒要素节 (端点/量纲/公式/复现/权威协议层)
- evals/cases 三个 algo 用例的陈旧模块路径 (src.* -> src.*)
- 探针期望值修正: dec=30° 面上 1°RA = 3600*cos(30°)″ (haversine 数学本就正确,
  原探针期望算错 — 复验纪律的又一实例)

### Added（docstring 维度 bootstrap, 20 个公开函数补齐五要素 docstring）
- src 公开函数 docstring 覆盖率 81.65% -> 100% (109/109); 覆盖 __main__/client/
  core.pipeline/lightcurve/models/protocol/scripts 的 to_dict/from_row/属性/装饰器
  (Phase 7 将继续做模块头与关键算法行内注释深化)

### 验证（出口）
- eval 全绿: 场景 12/12, 用例 16/16, 审计器 6/6 (findings 0), docstring 100%,
  综合 1.0000 SUCCESS; 反证夹具 7/7 按预期拒绝坏样本
- Q-07 回归 (破坏生产代码评分必须下降/阻断): 波段塌陷突变 -> 0.3656 CAUGHT;
  QualityGate fail-open 突变 -> 阻断 exit=1 CAUGHT; 还原后 1.0000
- pytest 191 passed/40 skipped; ruff check . 全绿; verify 树 210 条目 exit=0

## 2026-09-26 · Phase 4 链路完整性与声明面收敛

### Fixed（锚点先复验后修复; 探针 11 项中 9 项缺陷消失, Q-15/56 与 Q-18 为启发式误报实质已修）
- Q-14: QualityGate.validate_source 无任何质量指标可判时 fail-closed
  (旧实现 passed=True 放行幻影源; 同批改写钉缺陷的 test_validate_source_no_mags)
- Q-15/56: BestSkillClient 接收并透传 rate_limit/timeout/max_retries/api_token/
  base_url (BestClient 补 timeout 参数); AstroBestPipeline 配置全量透传
  (旧实现 9 字段只取 2 个)
- Q-16: env_map 补全至 10 键 (BEST_TIMEOUT/DOWNLOAD_DIR/MIN_SNR/MAX_FWHM/
  LOG_LEVEL/QUALITY_FILTER); AstroBestConfig 新增 log_level/quality_filter 字段;
  .env.example 重写为 SSOT (12 键全部可消费, BEST_API_USER/PASS/TOKEN 由 BestAuth/CLI 消费)
- Q-51: cone_search (client + scripts.best_cone_search 双入口) 接线
  validate_coordinate/validate_search_radius (负 RA/0 半径/超限半径入口即拒)
- Q-52: QueryContext.truncate 返回摊薄副本不再就地改写源记录;
  summary()["total_results"] 始终报告真实总数
- Q-54: downloader._save_result 落盘后强制校验和: 有期望值 verify_checksum
  (失败 raise), 无期望值显式记 checksum_match=unknown (fail-closed 语义)
- Q-55: kb 加载器接 CLI (ops/skill_cli.py 新增 refs 子命令: 清单/读取)
- Q-19: cmd_config 成功退出码 200.0 -> 0 (HTTP 语义只进 payload)
- Q-18: scripts.best_cone_search 模块级共享 client (惰性单例), 公开入口不再
  每次新建 BestClient 泄漏 session
- Q-27: downloader 行构建收敛为 _rows_from_result 单一实现 (csv/txt/votable
  三处 22 行逐行重复移除)
- Q-28: VOTable 值/字段名/资源名 HTML 转义 (防 XML 注入)
- Q-31: templates/best-config.yaml 可消费键收进 defaults (from_yaml 只读
  defaults; 分组视图保留为文档性); from_yaml 消费验证 timeout==60
- Q-37: SKILL.md standalone 对齐 manifest SSOT (false->true)
- Q-60: CSV/TSV 落盘 utf-8-sig (Excel 兼容); JSON/VOTable 保持纯 utf-8
  (BOM 破坏标准解析器, 首版过泛已回调)

### Added（Phase 4 钉桩测试, test/unit/meta/test_phase4_wiring.py, 16 例）
- fail-closed 门控/真实指标放行; 配置全量透传/缺省; env SSOT 10 键逐键生效;
  入参校验双入口/共享 client; truncate 不改源; checksum 不符 raise/相符接受;
  protocol import-graph (公开符号须有生产引用); 模板 defaults 消费
- M14 防线: adapter Retry.total==3 与 max_retries 参数透传直接钉桩

### 验证（出口）
- pytest 191 passed / 40 skipped; ruff check . 全绿; verify 树 208 条目 exit=0
- M14 突变 (Retry total=3->99) 字节级验证 CAUGHT, 还原后基线全绿
- Phase 3 突变矩阵 5/5 (M8/M10/M11/M12/M13) 依旧全红 (回归)

## 2026-09-26 · Phase 3 科学正确性 P0（数据语义统一到 protocol 层）

### Fixed（Q-01~Q-06 数据语义，锚点先复验后修复）
- **复验发现审计基线漂移**: Q-01/Q-03/Q-06 代码形态已被并发提交改变 (探针报签名错误);
  Q-02/Q-04/Q-05 锚点仍成立; Q-03 缺陷以更歪形态存在 (r 波段拿到 dec 值)。按"先验证不盲目相信"
  纪律重读现行实现后修复。
- Q-01: `client._build_form` / `pybest._form_from_constraints` 重接
  `protocol.build_query_form` (权威协议层); phase-1 固定 `output.fmt=html`
  (唯一取回 sqlid 的提交形态); 锥形检索改用服务端原生 `pos.type=cone` 字段
  (旧 RA/Dec box-between 键集与服务端不相交, 锥搜结构性失效)
- Q-02: `_fetch_sqlid_data`/`pybest._fetch` 解析统一委托 `protocol.parse_csv_rows`
  (表头动态判定), 表头行不再成为幻影源 (ra=0.0/source_id='')
- Q-03: 波段按列名映射 (ps1_gmag→g, ps1_rmag→r), 废弃位置分割+魔法值启发式
- Q-04: 生产解析路径透传 catalog (`catalog_from_path`→`from_row(row, catalog=cat)`),
  前缀正确剥离 (source_id 非空)
- Q-05: 全包单一表头假设 (client 位置解析与 pybest DictReader 假设均移除,
  protocol.parse_csv_rows 为唯一解析器)
- Q-06: pybest csv/txt emitter 接 `csv_safety.sanitize_cell` (旧内联副本把
  dec=-5.0 当公式向量加引号致在线数据损坏; 现负数原样, =cmd 仍中和)
- Q-22: cone_search 的 std 分支展开为全部成员表 (scr_galah/scr_lamost/xpsp) 合并,
  不再静默改写单一表 (protocol.resolve_catalog 对导航组报错的行为保留)
- Q-23: total_count 语义诚实化 (真实解析行数; 服务端总数留待 getcount 接线, V-1)
- Q-26: outputformat 拼写随协议层统一为 output.fmt
- `_build_filter_rules` 改解析协议层约束键 ({prefix}.operation/.min/.max/.constraint/
  .textarea; grater→greater 别名); downloader.download_by_constraints 同步新签名

### Added（钉桩测试, 每条修复自带"改坏就红"防线）
- test/integration TestDataSemantics: 表头幻影源/波段列名映射/前缀剥离/无表头投影/
  计数真实性/负赤纬落盘/公式向量中和/分页取完/max_rows 截断 共 9 例
- Q-10 同批改写: 4 个 test_build_form_* 从钉死错误契约改为断言协议层键集
  (output.fmt=html/pos.*/showcol/{table}.{col}.operation; 禁 outputformat/max_rows/
  非限定 .constraint)

### 验证（突变矩阵出口）
- temp/probe_mutations.py 字节级突变验证: M8(盲删首行)/M10(波段塌陷)/M11(只取首页)/
  M12(计数不推进)/M13(计数归零) **5/5 全部转红**, 还原后基线全绿
- temp/probe_phase3.py 锚点复跑: Q-01/02/03/05/06 缺陷消失; Q-04 生产接线修复
  (from_row 合约行为保留)
- 基线: pytest 175 passed/40 skipped (Phase 2 的 166+9 新钉桩), ruff 全绿,
  verify 207 条目 exit=0, doctor/eval 正常

## 2026-09-26 · Phase 2a/2b test 能力域重组与测试有效性

### Changed（结构重组，用户批准的计划批量执行）
- `test/unit/` 按能力域重组为 11 个子目录：client/query/download/crossmatch/lightcurve/pipeline/protocol/contracts/scripts/config/meta；31 个测试文件移动并修正 `__file__` 锚点深度（parents[N]+1）
- `test/upstream_pybest_0_3_2_8/` → `test/upstream/`（去版本号）
- `test/integration/test_live_{best,download}.py` → `test/live/`（live 门控测试归位）
- README.md test/ 边界节与树 SSOT 同步更新（207 条目）

### Fixed（测试有效性）
- Q-11：`test_single_layer_retry_on_503` 不再 mock `Best.__init__`（原 mock 使 HTTPAdapter(Retry) 从未安装，测试结构性失明），改真实构造 + 计数总请求数
- Q-12：删除对生产不存在属性 `_rate_lock` 的夹具伪造注入
- Q-35：conftest `get_spec_data()` 大仓 spec 解析失败不再静默 pass，显式 RuntimeWarning 后按 local 快照继续
- ledger 测试更新白名单机制：已批准并记录的基准偏差（evals -2，场景 4 变体合并）允许存在，未记录的计数下降依旧 Fail-Closed；顺带移除对已删 version 字段的断言

### 后续轮次（Phase 2b 内容合并去重，已记录未执行）
- gen_algo_* 12 个生成式测试按被测对象合并参数化（Q-33 升行为断言）
- upstream tap_* 8 个文件按 topic 合并为 ~5 个（均为 legacy skip 资产）

### 基线（出口绿灯）
- pytest 166 passed / 40 skipped（与 Phase 1 一致，重组零行为漂移）；ruff check . 全绿；verify 207 条目 exit=0；`python -m src doctor` 正常

## 2026-09-26 · Phase 1 去版本号与死资产清除

### Removed（版本号，全仓禁止铁律）
- 全部发布版本号与 schema/template 标记：SKILL.md/manifest.yaml frontmatter、pipeline.yaml、agents/openai.yaml、contracts 六件 + fields 四件的 schema_version 行、provenance 的 version 行、evals/scoring-rubric.yaml 的 scoring_rubric_version、templates 九件的 template_version/config_version、src/__init__.py 的 __version__
- 删除 `src/_version.py`；`__main__.py` info 子命令、`pybest.py` 连接信息、`ops/skill_cli.py` doctor 报告中的 version 字段一并移除
- pyproject.toml 剥离 [build-system]/[project]/[project.scripts]（skill 以源码树分发，无构建无版本）

### Removed（死资产，Q-61/Q-20/Q-53/Q-44 分级处置的删除类）
- `src/services/`（mcp_client.py 330 行零引用零测试 + 空 __init__）
- `src/core/processor.py`（BestProcessor 零生产调用）+ test/unit/test_processor.py（5 例）
- `src/scripts/repair.py`（自愈层双 0 调用 + 盲替换查询串）
- `src/serialization.py`（零生产调用）+ test_release_regressions 的 convert_table_rows 测试
- `src/client.py` `_parse_csv_text`/`_count_url`（零调用）+ test_integration 的 3 条附属测试
- `test/unit/test_auth_store.py`、`test/integration/test_server_api.py`（目标模块不存在，整文件从未执行）
- `schemas/`（message.proto 全库零引用）
- `src/scripts/rag.py`（BestRAGEngine）：`__main__.py` 的 rag 子命令本就是 ops/skill_cli.py 的重复入口，按双层边界移除；doctor 的 RAG 检查改路径直查；rag/astro_rag.py 为全树唯一 RAG 执行器

### Changed（evals 场景合并，用户过目批准）
- `evals/test-scenarios.yaml` 为唯一 canonical：__twh_2 基线（7）吸收 twh 独有 3 个 + canonical/swsk/v1 同构 5 个 = 12 场景；折叠 4 个（basic_cone_search→cone_search 首步、lightcurve_export_csv→lightcurve、custom_adql_query→custom_adql、coordinate_lookup 保留独立 id）；入口命令统一 `python -m src`；星表数 9→12 事实修正；custom_adql 标注 BEST 无 ADQL 端点；去 version/BOM
- 删除 4 变体：test-scenarios__{swsk,twh,twh_2,v1}.yaml

### Fixed
- templates/best-config.yaml 去 UTF-8 BOM（YAM-03）；weights/README.md 与 test/live 文档的陈旧路径（tests→test、scripts→ops）
- 删除连锁的未用导入（client.py csv/io/count_sqlid/parse_count、skill_cli mod）
- Q-43 CRLF：monorepo 级 .gitattributes 已覆盖 `*.py text eol=lf`，无需子仓动作

### 偏差记录（先验证后发现）
- models/output.py 四个输出模型实为契约匹配的实质模型（BestResultSet 对 output.contract.yaml），非"空壳"：保留，Q-08 改走 Phase 6 接入路线（原计划的删除类移出）

### 基线（出口绿灯）
- pytest 166 passed / 40 skipped（-9 passed/-2 skipped 与删除量精确吻合）；ruff check . 全绿；verify 树 196 条目 exit=0；ledger 按批准批 relock（tests 968→965、evals 898→894）

## 2026-09-26 · Phase 0 结构对齐与治理基石

### Changed（结构对齐，用户批准的 8 项）
- `src/astro_best/` 平铺为 `src/`（包名 = src；82 处 import 全量改写；S4 import 承诺变更为「函数能力不变、import 路径随重构演进」）
- 根 `scripts/` → `ops/`；`scripts/cli.py` → `ops/skill_cli.py`；包内 `cli.py` → `src/__main__.py`（`python -m src` 入口）
- 顶层 `models/` → `weights/`；包内 `references/` → `src/kb/`（标志文件定位 skill 根，Q-39/Q-55）
- `bridge/` 两脚本合并为 `ops/register_skill.py`（修 Q-32：路径一级上跳/去版本/环境名对齐 environment.yaml）
- `contracts/skills-spec.local.yaml` → `references/`（spec 快照归位）；大仓共享 spec 的 astro-best 段模块路径同步（用户批准的手术式更新，其余 29 段零改动）

### Added（治理机制）
- `ops/verify_tree_integrity.py` 文件树硬门禁：README 树清单 SSOT 生成（--write）/校验/漂移检出（exit 1）
- `README.md` 重写：必读链/治理规则（权限矩阵+temp+禁版本号）/平台部署前提/17 节逐文件能力边界表/树 SSOT 块（213 条目）
- `SKILL.md`：第一步强制读 README + 治理铁律 4 条；`manifest.yaml` always_load += README.md，entry_points 改 ops/，新增 tree_gate
- `Makefile`：+verify 目标；lint 扩 6 目录；eval 接入 check/all；clean 不再删 best_data（Q-41）；+distclean
- `.gitignore`：docs/ temp/ CHANGELOG.md .checkpoints/ 转 local-only（git rm --cached，文件留磁盘）
- `temp/` 唯一临时区；.qdeep.py/.qdeep.out 移入留档（含 Q-62 BFS 缺陷警示）

### Fixed
- upstream 三个死测试 legacy 守卫探测符号过弱（被平铺后的 src/pybest.py 误触发导致收集错误）：改探上游包专属子模块并绑定 Best
- `test_release_version_is_consistent` → `test_release_has_no_version_fields`（禁版本号铁律守卫；Phase 1 扩展覆盖面）
- lint 清零（Q-40）：eval_runner I001/F401 ×5、examples E402/I001、run.py F841、upstream I001 ×4
- SKILL.md/manifest.yaml version 字段移除（禁版本号第一批）；pytest pythonpath 改仓库根

### 基线（出口绿灯）
- pytest 175 passed / 42 skipped（与重构前完全一致）；ruff check . 全绿；verify exit=0；python -m src 可用；make doctor 正常

## 2026-09-26

### Added
- 星表注册表按 2026-09-26 实测补齐为 12 张可查表：新增 `scr_galah`、`scr_lamost`、
  `xpsp`、`dr3xpcorr`，并补 `CatalogType` 对应成员与真实列名（列名取自各 `/f` 表单页）
- `protocol.resolve_catalog()` / `catalog_tables()`：旧名 `gaia_dr3` 映射到线上
  `gaia_dr3_18`，`std`/`calib`/`other` 作为分组给出成员表而非静默空结果
- `protocol` 端点常量与格式白名单（`SQLID_PATH`、`GETCOUNT_PATH`、`TABLE_META_PATH`、
  `SUPPORTED_OUTPUT_FORMATS`、`PHASE1_HANDOFF_FORMAT`）
- `build_query_form` 支持 `pos.type=rect`（`box=`）与 `pos.type=proximity`
  （`radec_text=`，服务端批量坐标匹配）
- `test/unit/test_catalog_registry_live.py`：把上述线上事实钉成回归门禁（10 例）

### Changed
- `references/best-database-guide.md` 重写为端点/星表/表单字段权威清单，含软 404 判据
  与复现步骤；`static/fragments/data_source/*`、`ALGORITHM-SPEC.md`、
  `pybest-api-reference.md` 同口径更新
- `getcount` 改用数字 id 并按 `{"total": N}` 解析（带 `s` 前缀原为软 404，计数恒为 None）
- `query_calibrated` 去掉 `calib/{survey}` 兜底（该拼法只存在于 `/f`，`/q` 上是死路由）
- `query_standard_stars` 改路由到标准星成员表（默认 `scr_lamost`）
- `--catalog` 帮助与 CLI `catalogs` 列表同步；`sync/` 镜像同步以收敛 src↔sync 漂移

### Removed
- 声明面里的虚构端点：`best.astro.tsinghua.edu.cn/tap`（2026-09-26 两个解析器下均无 A
  记录）与 `/data/best/api`（软 404）；`DEFAULT_TAP_URL` 改为真实基地址别名而非死主机
- 输出格式声明中的 `fits`（服务端返回结果页 HTML，不是 FITS）

## 2026-07-18

### Added
- **独立执行脚本**: 无需安装 pybest，只需 Python 3 + requests 即可执行锥形搜索；
  Python 内联版、Windows PowerShell、Linux/Mac bash 三平台覆盖
- **Best 单类接口**: 完整的 pylamost 风格单类接口导出（`from astro_best import Best`）
- **crossmatch 便捷方法**: `Best.crossmatch()` 支持多坐标并发交叉匹配

### Changed
- **SKILL.md 修复**: 独立执行脚本代码块的围栏由单反引号改为三反引号
- **上游同步项**: VOTable 按 astropy 规范输出、FITS 处理补齐、`*.tmp` 纳入 gitignore
- **安全特性同步**: 原子写入、CSV header 解析、超时传播
- `__init__.py` 导出 `Best` 类

## 2026-07-17

### Changed
- **重大重构**: 从虚构 TAP API 切换到真实 nadc.china-vo.org Django form-based REST API
- `client.py`: 完整重写，POST form data 到 `/data/best/{catalog}/q`
- `models/`: 重写为子包，适配真实星表列结构（`CatalogType` 枚举 9 种星表）
- `core/__init__.py`: QualityGate 移除旧的 `best_mag` 引用，改用 magnitudes/SnR/FWHM/class_star
- 测试文件全部更新为新 API 架构
- 配置文件更新为真实 BEST 端点

### Added
- `BestAuth`: Django session + CSRF token 鉴权模块
- `ColumnConstraint`: 列约束查询构建器（min/max/constraint/value）
- `BestCrossMatch`: 坐标上传交叉匹配（核心功能，避免全量下载 2B+ 星表）
- CLI: `catalogs` 列出星表、`crossmatch` 交叉匹配、`cone` 搜索
- FROM_ROW 解析：从最佳真实列名自动映射

### Removed
- 虚构 TAP 端点 `best.astro.tsinghua.edu.cn/tap`
- ADQL 查询（BEST 真实网站无 ADQL/TAP 端点）
- `tap_query()` 方法

## 2026-07-16

### Added
- 初始实现（基于虚构 TAP API 的占位架构）
- 基本模型和客户端框架
- `pyproject.toml`、`Makefile` 等基础设施
