---
title: YZ-* 缺陷编号登记册（代码注释里的编号出处）
scope:
  - src/
  - test/
白盒锚点: 本文的每一行都能在 src/ 或 test/ 里检索到同号注释
---

# YZ-* 登记册 —— 让代码注释里的编号可解析

## 为什么有这份文件

`src/` 与 `test/` 的注释里散落着 **30 个 `YZ-NN` 编号**（2026-10-06 实测；
新增编号时这个数会变，改完请连同下方条目一起更新）。
在本文之前，这些编号**只存在于注释与审计报告里，没有任何地方定义它们**
（审计轮次 AH5 §3.4 的结论：`YZ-* 归源`）。结果是：读代码的人看到
`# YZ-15: …` 只能靠猜，`grep YZ-15` 也搜不到「15 到底是什么」。

本文把每个编号的**一句话内容 + 代码落点 + 回归测试**对齐，使注释里的引用
从死引用变成可解析引用。

## 引用纪律

1. **注释里写编号时必须在本表有条目**；新增编号时同批改本表。
2. 编号是**缺陷身份**，不是严重度排序，也不表示修复顺序。
3. 编号只表示「这里防住的是哪一类缺陷」，**不表示该行代码的全部语义** ——
   读代码仍以代码与 docstring 为准，本表只解决「指的是哪一类问题」。
4. 审计报告里的裸 `P0-NN` / `Q-NN` 等其它命名空间**不在**本表范围
   （多套命名空间并存本身是审计轮次 AH5 指出的记录缺陷，见该轮 §3）。

## 工具面 / 信封（`src/ai_tools.py`、`src/ai_tools_envelope.py`）

| ID | 缺陷 | 代码落点 | 回归 |
|---|---|---|---|
| `YZ-03` | `fetch_page` 的 `max_rows` 无上限 → 单次调用可驱动无界翻页 | `src/ai_tools.py` fetch_page 参数校验 | `test/unit/ai_tools/test_yz_boundaries.py::TestFetchPageMaxRowsCap` |
| `YZ-04` | `max_rows<=0` 与非整数被静默接受（修前 0 行与「真的没有行」不可区分） | 同上 | `…::TestFetchPageMaxRowsPositive` |
| `YZ-14` | `count` 的 `total=None` 与「服务端确认 0 行」压成同一信封 | `src/ai_tools.py::count` / `src/ai_tools_envelope.py::build_envelope`（`extra_status` 位） | `…::TestCountDegradedTotal` |
| `YZ-15` | `stable_uri` 拼接段不做形态校验 → 脏段拼出歧义句柄；且守卫曾判 `stripped` 而调用方拼**原值** | `src/ai_tools_envelope.py::is_safe_uri_segment` | `…::TestStableUriGuardJudgesTheEmbeddedText` |
| `YZ-16` | `fetch_page` 公开缝绕过 `protocol.normalize_sqlid` 白名单，脏 sqlid 原样进 URL | `src/ai_tools.py::fetch_page`（`normalize_sqlid`） | `…::TestFetchPageSqlidValidation` |
| `YZ-18` | `page`/`page_size` 必须是严格 int：非整数被 `int()` 静默取整、bool 被当 int | 同上 | `…::TestFetchPagePageTypeStrictness` |
| `YZ-44` | `truncated` 只有布尔位，成因清单不上浮（agent 无法知道「为什么没取全」） | `src/ai_tools_envelope.py::truncation_reasons` + `data.truncated_reason` | `…::TestTruncatedReasonSurfaces` |

## 输入面守卫（`src/scripts/guards.py`、`src/models/input.py`、`src/client_query.py`）

| ID | 缺陷 | 代码落点 | 回归 |
|---|---|---|---|
| `YZ-07` | 半径/坐标守卫是**纯比较式**：任何与 NaN 的比较都判 False，`nan` 天然放行 | `src/scripts/guards.py`（`math.isfinite` 前置） | `test/unit/scripts/` 覆盖层 |
| `YZ-08` | 三个输入类是公开构造面，敌意值（nan/str/None/list/bool）曾静默落库 | `src/models/input.py::_check_finite_number` | `test/unit/models/` |
| `YZ-09` | `crossmatch_batch` 公开缝零校验：敌意坐标/半径直接拼进 proximity 坐标块 | `src/client_query.py::crossmatch_batch` | `test/unit/crossmatch/` |
| `YZ-58` | 与 `YZ-07` 同族的非有限值防线（坐标/半径两条守卫共用口径） | `src/scripts/guards.py` | 同上 |

## 序列化 / 导出（`src/serialization.py`、`src/tap/formats.py`）

| ID | 缺陷 | 代码落点 | 回归 |
|---|---|---|---|
| `YZ-05` | astropy `Table(rows=…)` 对含 None 的列给 object dtype，FITS 写不了 → 软错误收敛成零响应 | `src/tap/formats.py::_table` | `test/unit/tap/test_formats.py` |
| `YZ-24` | FITS 列集取首行键序 → 首行缺的列整列静默丢失 | `src/serialization.py::write_fits` | `test/unit/serialization/` |
| `YZ-25` | `{width}A` 的单位是**字节**不是字符，按字符数算会让非 ASCII 列整份 `UnicodeEncodeError` | 同上 | 同上 |
| `YZ-45` | 列数超过 FITS 标准 BinTable 硬顶 999 列，写出来也是非法文件 | 同上 | 同上 |
| `YZ-48` | 0 行结果在 VOTable 出一个列头、在 CSV 出另一个 → 同一份空结果两套表结构 | `src/serialization.py::votable_document` | `test/unit/serialization/` |
| `YZ-49` | VOTable 出口误用 CSV 的公式消毒：`-2+3` 被永久改写成 `'-2+3`（数据损坏） | 同上 | 同上 |
| `YZ-50` | 标识符被 `float()` 静默改写（前导零 / 超 2^53 整数不可逆丢失） | `src/serialization.py::must_stay_text`（单点） + 两个消费方 | `test/unit/models/test_magnitude_mapping.py` · `test/unit/tap/test_formats.py` |
| `YZ-51` | 截断时同时发 `QUERY_STATUS=OK` 与 `OVERFLOW`，且 OK 在前 → 客户端取首个 INFO 会把截断当完整 | `src/tap/formats.py::serialize_result` | `test/unit/tap/test_formats.py` |
| `YZ-52` | VOTable `RESOURCE` 缺 `type="results"`，与 TAP 出口不一致 | `src/serialization.py::votable_document` | 同上 |

## 断点 / 作业 / 编排（`src/downloader.py`、`src/crossmatch_jobs.py`、`src/core/`）

| ID | 缺陷 | 代码落点 | 回归 |
|---|---|---|---|
| `YZ-10` | 约束作业的断点键不含锥几何 → 同约束集换 `radec` 续到**别的天区**的断点上，跨查询数据静默混洗 | `src/downloader.py::constraint_checkpoint_key` | `test/unit/download/test_region_checkpoint_key.py` |
| `YZ-29` | `submit_upload_job` 的 `output_dir` 相对路径随 CWD 漂移 | `src/crossmatch_jobs.py`（经 `guards.anchor_output_dir`） | `test/unit/crossmatch/test_crossmatch.py` |
| `YZ-47` | FITS 半成品（`.tmp`）无清理：`write_fits` 写一半抛错就把半截文件留在输出目录 | `src/downloader.py`（`try/finally` + `unlink`） | `test/unit/download/` |
| `YZ-27` | `batch_crossmatch` 的失败原因与「查无此项」混成无类型 `list[str]` | `src/scripts/best_crossmatch_pipeline.py` | `test/unit/scripts/test_best_crossmatch_pipeline.py` |
| `YZ-28` | 质量门控是**纯比较式**：NaN/Inf 指标恒判合格（fail-open） | `src/core/__init__.py::QualityGate` | `test/unit/core/` |
| `YZ-68` | 检索行为配置被硬编码：`catalog` 恒 `ps1`、`quality_filter` 恒 `True` | `src/core/pipeline.py` | `test/unit/core/` |

## 知识槽 / 配置（`src/kb/`、`src/knowledge_slots.py`、`src/scripts/config.py`、`src/__main__.py`）

| ID | 缺陷 | 代码落点 | 回归 |
|---|---|---|---|
| `YZ-17` | `kb.load_reference` 曾实测读出仓根 `README` 全文（`../../README` 型输入） | `src/kb/__init__.py::load_reference` | `test/unit/knowledge/test_knowledge_slots.py::TestLoadReferenceTraversal` |
| `YZ-53` | 读失败（权限/解码）与「无槽位」被归成同一结果 → 静默 `None` | `src/knowledge_slots.py::_read_slot`（WARN 留痕） | `…::TestUnreadableSlotLogsWarning` |
| `YZ-30` | env 端点零校验、数值零校验：`nan` 静默通过（比较式守卫对 NaN fail-open），端点可带内嵌凭据 | `src/scripts/config.py`（`_validated_base_url` / `_finite_float` / `_strict_int`） | `test/unit/scripts/` |
| `YZ-57` | `.env.example` 教用户建 `.env`，而全仓**零代码读它** → 照做后凭据进不了进程 | `src/scripts/config.py::load_dotenv_file` + `src/__main__.py`（CLI 入口调用） | `test/unit/scripts/test_dotenv_loading.py` |

## 维护方式

- 本表由人工维护，**不是自动生成**：每行都是「一句话缺陷 + 落点 + 回归」，
  自动抽取只能得到编号与文件，得不出语义。
- 新增编号时：先在代码注释里写下**为什么**（缺陷是什么），再同批在本表补一行，
  两者缺一就是又造了一个死引用。
- 若某编号对应的缺陷已不复存在（代码已删/语义已变），把该行标 `~~删除线~~` 并
  在末列注明去向，**不要静默删行** —— 删掉会让历史注释里的引用重新变成死引用。