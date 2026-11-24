# astro-best 源码级逐文件核实 — 问题清单

- 日期: 2026-09-28
- 范围: 全仓被跟踪文件（src 50 py / ops 5 / rag 1+5 / evals 5+27 / contracts 12 / templates 9 / test 69 / references 11 / static 11 + 治理文档）
- 方法: 树完整性门禁 + 全量编译 + 739 项 pytest + AST import 图(181 组 from-import 符号解析) + 重复定义/异味 AST 扫描 + 文档声明↔实现逐项比对 + 人工通读核心文件(client/protocol/pybest/crossmatch/models/core/auth/scripts 等 16 个全文, 其余结构性抽核)
- 结论: **无 P0 阻断项**。树完整性 PASS, 739 passed / 24 skipped, 全量编译通过。问题集中在**文档层失真**与**少数契约/代码漂移**。

---

## P1 — 重要(治理根基失真)

### P1-1 README 逐文件能力边界表大面积失实(自称"全树全覆盖")
README.md:34 声明"逐文件能力边界(全树全覆盖)", 实际:

| 类别 | 具体失实 | 证据 |
|------|----------|------|
| 引用不存在文件 | `fixtures/mock_data.py` / `fixtures/mock_responses.py` 两行, 磁盘无 test/fixtures/ 目录 | README:206-207 |
| 引用已删除文件 | `integration/test_integration.py`(已按 file-size-budget §3.7 拆为 7 个 chain 文件); 7 个新文件(test_crossmatch_chain 等)未登记 | README:223 vs test/integration/ 实树 |
| 目录无行 | `unit/serialization/`(1 文件)整目录未列 | README test 表 |
| 计数错误(表N个 vs 实树) | client 2→1; crossmatch 2→1; lightcurve 2→1; download 9→10; meta 5→12; models 1→4; scripts 1→4; auth 2→3; audit_round 2→3 | README:208-230 vs 树清单 |
| 空目录声称有测试 | `unit/config/`(1个)、`unit/query/`(1个)实际为空(仅 __pycache__); `test/upstream/` 空目录未提及 | README:217,506 |
| src 表遗漏 | serialization.py / best_export.py / download_artifacts.py / download_region.py / download_sqlid.py / auth/session.py / core/source_postprocess.py / protocol_catalog_tables.py / tap/response.py / tap/uws_service.py; `tap/(7 个模块)` 实为 9 文件 | README:132-169 vs 树清单 |
| references 遗漏 | data-formats.md 在树无表行 | README:117-130 |
| evals 遗漏 | case_runner.py / paths.py / probe_support.py / probes.py 无行 | README:74-87 |

### P1-2 错误码契约 ↔ 实现双漂移 ✅ 已修

> **已修**（见 `contracts/error-codes.contract.yaml` 头部修复记录）：
> `BEST_1001.code` 已改为代码实际发出的 `E_INVALID_INPUT`；补入 `BEST_1007`
> （`E_NO_SQLID`）与 `BEST_1008`（`E_NAME_UNRESOLVED`）两条代码在用而契约缺失的
> 条目；`BEST_1004/1005` 编号规则统一为 `E1004_*`/`E1005_*`；`BEST_1002/1003/
> 1004/1005/1099` 的未接线状态从"隐式"改为**显式 declared 并注明原因**。
> 本节原文保留作取证历史。

contracts/error-codes.contract.yaml 与代码双向不一致:

- 契约 `BEST_1001.code = E101_INVALID_INPUT`, 代码实际发 **`E_INVALID_INPUT`**(`src/protocol.py::E_INVALID_INPUT` 定义; 实发点 `src/ai_tools.py::_error_envelope` 与 `src/client_paging.py::fetch_sqlid_data`); `E_NO_SQLID`(`src/protocol.py::E_NO_SQLID`, 实发于 `src/client_phase1.py::_submit_query_for_sqlid`)、`E_NAME_UNRESOLVED`(`src/protocol.py::NameResolveError`) 代码在用的码**无契约条目**。
  > **坐标订正（R2, 2026-10-05）**：本条原文写 `src/client.py:95` / `client.py:96`。逐行打开确认，
  > 那两行是星表枚举的 docstring 列表项（`- CatalogType.CALIB_STRIPE82: ...`），
  > 且 `src/client.py` 内 `E_INVALID_INPUT` / `E_NO_SQLID` 均为 **0 处** —— `client_resolve` /
  > `client_phase1` 抽取后实发点已整体迁出该文件（`src/protocol.py:679` 同样不是
  > `E_NAME_UNRESOLVED`，那是 `NameResolveError` 上方）。故改为符号锚点。
  > **上方 P1-2 的 ✅已修 结论不变**（契约确已改为 `E_INVALID_INPUT`），失效的只是取证坐标。
- `BEST_1002/1003/1004/1005/1099` 五个码在 src/ops/evals/test **零引用** — 违反 README:67 治理列"常量须被代码引用"。test_phase4_wiring 以白名单默认此缺口而非修复。
- `BEST_1004.code = E101004_*` / `BEST_1005.code = E101005_*` 编号规则不一致(1004→101004), 疑似生成缺陷。

---

## P2 — 次要(代码/契约真实缺陷)

| # | 位置 | 问题 |
|---|------|------|
| P2-1 | SKILL.md(全文 137 行) | ✅ **已修**（R2 订正, 2026-10-05）：超自身 G6 门禁 ≤100 行。原文记的 `SKILL.md:133` 自检项与 `README:40` 均已漂 —— 自检项实际在「完成自检」段的 `SKILL.md ≤100 行 (G6)` 那一条, 门禁条款在 `README.md` 的逐文件边界表 `SKILL.md` 行。**更关键: `SKILL.md` 现仅 98 行, 已达标**（`CHANGELOG.md` 有「SKILL.md 137→98 行 (G6 ≤100 达标)」的修复记录），故"违反 G6"这条结论**已不成立**, 不应再当待办项 |
| P2-2 | src/crossmatch.py:61,72 | `_proximity_radec_text` **重复定义**; 第二份不复用协议层而重写 zip 逻辑, 打破"线格式归属协议层"单一事实源(docstring 自认"历史遗留, 不做删改") |
| P2-3 | src/core/__init__.py:132,146 | `BestSkillClient.api_token` 死参数: docstring 称"透传 BestClient", 实际 BestClient 无 token 通道, 值存而不用; BEST_API_TOKEN env → AstroBestConfig.api_token → 此处全链死 |
| P2-4 | .env.example:5,10-12 | 声明"每个键都必须能被 AstroBestConfig 或 BestAuth 消费(Q-16)", 但 **BEST_API_USER / BEST_API_PASS 无任何代码消费方**; CLI 实际凭据面是 `--auth-user` + `ASTRO_BEST_PASSWORD`(src/__main__.py:32), 与 .env.example 声明变量不一致 |
| P2-5 | src/protocol.py:108-111 vs :327 | 模块注释声明 `SUPPORTED_OUTPUT_FORMATS` 的消费方含 "build_query_form 的 output_format 校验", 但 `build_query_form` 对 output_format **零校验**, 非法值(如 fits)可直入 phase-1 表单; 声明的责任未兑现 |
| P2-6 | ~~src/pybest.py:268 vs src/client.py:345~~ | ✅ **已修**（R2 订正, 2026-10-05）：`src/pybest.py` 已由提交 `456149e`「pybest 双副本合并删除, 统一 BestClient/ToolBox」**整体删除** —— "双客户端 4xx 失败语义不一致" 的前提（两个实现并存）已不成立。原文两处坐标均已失效：`src/pybest.py` 文件不存在，`src/client.py:345` 亦非该判据落点 |
| P2-7 | ~~src/pybest.py:651,684 vs src/client.py:950~~ | ✅ **已修**（R2 订正, 2026-10-05）：同上，`src/pybest.py` 随 `456149e` 删除，"两公开面行为分叉" 随副本合并消解。另 `src/client.py:950` **越界**（该文件 795 行，指针超出 155 行），双重失效 |
| P2-8 | README:103 vs ops/best_mcp_server.py:235+ | "--selftest 离线 13 项" 与实际 **7 项** checks 不符(历史 docstring 曾记 26 项, 文档未随实现收敛) |
| P2-9 | references/site-endpoints-and-interactions.md | 引用不存在的 `src/pybest/oauth.py`(真实位置 src/auth/nadc_oauth.py) |

---

## P3 — 轻微(文档/打磨)

| # | 位置 | 问题 |
|---|------|------|
| P3-1 | README:230 | ~~`examples/test_examples_run_offline.py` 路径错, 实为 `test/examples/`~~ **已修**: README 表格行改为 `test/examples/test_examples_run_offline.py`（由 `ops/audit/verify_crossrefs.py` 的 `[DOCPATH]` 判据复现并定位） |
| P3-2 | ~~SKILL.md:120~~ | ✅ **已修**（R2 订正, 2026-10-05）："rag/knowledge/ 三件套" 口径已改为**五件套**并在同处列出五个文件名（`best_practices`/`citations`/`domain_rules`/`known_issues`/`lessons_learned`），现于 `SKILL.md` 的「组件地图」段。原坐标 `SKILL.md:120` **越界**（该文件 98 行） |
| P3-3 | README:46 | Makefile 行未列 test-cov / distclean / lint-fix / install / help 目标 |
| P3-4 | src/client.py:716-733 | `cone_search` 的 std 组展开对 merged 结果不做 max_records 总量封顶(成员各取 max_records, 合并可 3 倍超限), 与单表路径语义不一致 |
| P3-5 | src/protocol.py:271 | `proximity_radec_text` zip 静默截断(docstring 已自认), 建议对齐 crossmatch_batch 的显式拒绝 |
| P3-6 | src/auth/nadc_oauth.py:278 | `TokenStore.valid_token` 经 is_expired 重复 load 两次(性能微疵) |
| P3-7 | evals/eval_runner.py:33,40,41 | evals 用兄弟裸导入(`import case_runner/paths/probes`), 模块无法从仓根 import; "必须脚本方式调用"的隐含契约无文档声明(测试已绕路加载) |
| P3-8 | test/unit/config/ test/unit/query/ test/upstream/ | 空目录残留(仅 __pycache__), git 不跟踪空目录, 疑似删文件遗留 |
| P3-9 | contracts/error-codes.contract.yaml:20,24 | E101004_/E101005_ 编号与 BEST_1xxx 规则不一致(见 P1-2) |

---

## 已核实无误的关键声明(抽核通过)

- 树完整性: `verify_tree_integrity` PASS(278 项); 全量 py 编译通过; pytest **739 passed, 24 skipped**(live 门控跳过)
- import 图: 181 组 `from src/ops/... import` 全部符号解析成功(AST 级)
- src/__init__.py `__all__` 14 项全部可解析; 12 张可查询星表 = CATALOG_PATHS(12) = CatalogType 可查询成员, 三方一致
- io-contract.md 算子表 33 项符号全部存在于声明模块; skills-spec.local.yaml 31 项 algorithms.module 由 test_module_paths fail-closed 守护
- 下载栈: manager 默认 2 并发/四类任务、hooks network≤3 退避+severe 立即拦截+ask 载荷、precise stripe82=calibstars_id 映射、progress/store/tracker/bar、task_log、Range 续传(CHUNK_SIZE=8192)均与文档一致
- ai_tools: ToolBox 7 原子工具 + 统一信封 + best:// URI; mcp selftest 7 项全过
- auth: OAuth state/0600/回环+手动双流、Bearer 空格纪律、Django CSRF 双步登录均兑现
- 治理: 中文注释审计 0 违规; 无发布版本号(仅协议常量 VOTABLE 1.3 / MCP 协议日期, 均白名单); client.py 553 行已登记 §3.2 为例外; 引文 9 verified / 2 unverified 与 README 一致; ops/register_skill 目标 `_shared/skill-registry.yaml` 存在
- eval_runner: 权重和=1.0 启动校验、pass_score>WARN 线、NOT_MEASURED 三阻断均真实实现

## 复测命令

```bash
python ops/verify_tree_integrity.py          # 树门禁
python -m pytest test -q                     # 739 项
python ops/audit/count_code_lines.py              # 行预算
python ops/audit/comment_audit.py                 # 中文注释
python ops/audit/verify_import_graph.py           # import 图(AST)
python ops/audit/verify_crossrefs.py              # 文档路径/符号交叉引用
python ops/audit/scan_code_smells.py              # 重复定义/异味扫描
```
