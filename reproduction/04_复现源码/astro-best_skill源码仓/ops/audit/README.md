# ops/audit/ — 治理测量工具（2026-10-01 自 temp/ 提升入库）

> **为什么入库**：这些工具被 6+ 份治理文档（README.md、
> docs/architecture/file-size-budget.md、coverage-matrix.md、
> governance-debt-plan.md、FIX-PLAN、ISSUES-2026-09-28-source-audit.md）
> 引用为"复测命令"，但一直躺在 gitignored 的 temp/ 里——新克隆的读者
> 按文档命令跑会"文件不存在"。提升后文档命令可复现；工具产物仍落
> temp/（gitignored，属一次性测量输出，不随仓库分发）。
>
> **复核修正**：提升只做了一半——文件落到了磁盘与 README 树清单，
> 却从未 `git add`。已入库，并新增常驻门禁
> `test/unit/meta/test_gate_blindspots.py::TestGitTrackingCoverage`
> 守"未跟踪且未被忽略的文件"。

## 工具清单

| 工具 | 度量对象 | 文档引用 | 门禁角色 |
|---|---|---|---|
| `count_code_lines.py` | 净代码行预算（R1: ≤400/文件；R2: 超限须登记） | budget/FIX-PLAN/source-audit/README/coverage-matrix/governance-debt | **硬门禁** |
| `comment_audit.py` | 注释规范全项（docstring/中文注/未决标记） | 同上 6 份 | **硬门禁** |
| `code_fingerprint.py` | 结构指纹（清单外文件 = 未登记变更） | README/budget | **硬门禁**（`check` 子命令） |
| `verify_import_graph.py` | 导入图（环/断名/分层违规） | source-audit | **硬门禁** |
| `verify_crossrefs.py` | 文档交叉引用（坏链/坏码/坏名/坏 module 路径） | source-audit | **硬门禁** |
| `verify_doc_consistency.py` | 注释与结构一致性（STRUCT 分节漂移 / DEADPARAM 假声明） | source-audit | **硬门禁** |
| `verify_no_version_keys.py` | 铁律 1 禁版本号（全仓 YAML 键名扫描） | README/budget | **硬门禁** |
| `verify_evidence_anchors.py` | E3 题集 `evidence` 锚点（文件/行号/符号落点） | README/budget | **硬门禁** |
| `verify_counting_claims.py` | 计数型断言（`<某 .py> … <N> 净行`）vs `count_code_lines` 实测 | budget | **硬门禁**（V2-01，2026-10-05 新增） |
| `scan_roots.py` | **扫描面唯一真源**（哪些 `.py` 进门禁；被上列四道门禁与 `code_fingerprint` 导入） | budget | 共享层（自身不产报告、不给退出码） |
| `verify_no_code_loss.py` | git HEAD vs 工作区的代码 token 零丢失 | README/budget | 报告型 |
| `scan_code_smells.py` | 代码异味（重复定义/裸 except/FIXME/可变默认参数） | source-audit | 报告型 |
| `version_scan.py` / `version_scan2.py` | 版本号铁律（A 类违规 / B 类裁定保留） | budget/governance-debt | 报告型（已被 `verify_no_version_keys` 取代，见下） |
| `check_line_endings.py` | 行尾体检（CRLF/LF；MK-03） | budget | 报告型 |

**硬门禁 vs 报告型**：硬门禁接在 `make audit`（并因此进入 `make check` / `make all`），
非零退出即阻断；报告型刻意不接线——它们的输出需要人判读，强行阻断会误伤正常重构
（例：合法清理一处重复定义会被 `verify_no_code_loss.py` 报成"token 减少"）。

---

## 怎么用这套门禁，什么时候别信它

这一节写的是**判据面**的用法与失效边界（2026-10-05 判据审计 D5 / E1 / E2 的归位）。
每条断言都配了实跑证据（复跑命令见 `temp/FIX-K4-gate-readme.md`），可逐条复核。
上面那张工具清单说明**每道门量什么**；这一节说明**它们量不到什么**，以及全绿时该信几分。

### 判据的强度阶梯：全绿 ≠ 门禁在工作

判据从强到弱有四档，**读退出码时必须区分**，否则会把最弱的一档当成最强的证据：

| 档 | 形态 | 全绿时能推出什么 | 本仓实例 |
|---|---|---|---|
| 1 | **恒红型**（照设计就红） | 什么都没证明，只能证明"现在还没坏到要修" | `code_fingerprint check`（有未提交真改动就红） |
| 2 | **判据级红测试覆盖** | 判据退化成 `return 0` / 恒不命中时，`pytest` 会抓到 | 判据审计 D5 的 8 道门禁里 7 道有（缺的那道已于 2026-10-05 补齐，见下） |
| 3 | **恒绿型判据** | 只证明**当前这批输入**没有触发违规，不证明覆盖了 | 其余八道硬门禁 |
| 4 | **零覆盖 ≠ 全绿** | — | 覆盖面缺口（见下节）落在这一档，**这一档最容易被误读** |

> **"零欠账"不等于"守卫到位"**：2026-10-05 扫描面收窄后，受跟踪的 `.py`
> **恰好全部**落在旧白名单内（K4 实测复核：316 个，旧白名单之外 **0** 个），新冒出的
> 违规是 **0 条**。这个 0 是**巧合**（目录布局正好对），不是任何一道门禁证明的。判据
> 审计 D5-01 实测把文件放进 `agents/` 立刻复现：同一批 `.py`，换个落位目录就免检。
> **结论：新口径下"违规 0 条"只能读作"这批落位里没抓到"，不能读作"守卫已覆盖全仓"。**
> 真要证明覆盖，看的是 `test_gate_scan_coverage.py` 那组断言绿，不是看违规计数为 0。

### ★ 白名单的缺口只能靠不断补，黑名单的排除项是有限且稳定的

这是本轮最贵的一课，且**同一反模式犯了两次**：

1. **第一次（已修）**：四道门禁各抄一份 `SCAN_DIRS` 白名单，缺口在同一处，
   `agents/` 下 900 净行的文件四道全部 exit 0 —— 铁律 2 被违反 900 行而门禁全绿。
2. **第二次（已修）**：`verify_crossrefs` §7 的 env 消费方当时用 `CONSUMER_FILES`
   写死 3 个文件（补丁前位置 `:237`，**该常量已删除，现名 `ENV_MAP_FILES` 在 `:326`**），
   于是 `src/tap/client.py` 读 `BEST_TAP_URL` 这样的真实读取点被误报成"代码未读取"。
   **同一个坑，第二次踩时上一轮的教训还没落地。**

两条都改成了**黑名单 / 形状判据**（`scan_roots.iter_py_files()` 走遍全仓，
`verify_crossrefs.py:339` 也改从 `scan_roots` 取扫描面）。**写新判据时的落笔顺序因此是
固定的**：先问"这份清单外的输入会怎样"，白名单答案永远是"免检"，黑名单答案才是
"进门禁"。守卫见 `test/unit/meta/test_gate_scan_coverage.py::TestScanScopeIsSingleSource`
与 `::TestExclusionsAreNarrow`（后者防的是黑名单自带的后门形态：往排除项里塞一个名字
就能给整片源码免检，而门禁仍然全绿）。

> **顺带纠一处历史误诊**：D5 早期记录把 `verify_crossrefs` 的 env 缺口写成
> "白名单只认 3 个文件，漏 1 个真实读取点"。**这个缺口早已不存在**——当前 HEAD 的
> **覆盖面**已是全仓黑名单，3 文件名单现在叫 `ENV_MAP_FILES`（`:326`）且**只管形态 (c)**，
> 不再管覆盖面。读这一段时别把两个面混为一谈，两者的分工理由见下节。

### ★ 判据"认几种形态"直接决定它能看见什么

`verify_crossrefs` §7 的 env 对账是本仓形态判据最完整的一处，也是"认不全就误报"的活样本。
**判据认的形态是封闭的**：不在清单里的写法，键就被当成"没人读"。K4 实跑（假仓，
同一键名 `PROBE_KEY`，唯一变量是**写法**）：

| 代码里的写法 | 门禁判 `PROBE_KEY` 为"有而代码未读取"？ | 判据认的是哪一维 |
|---|---|---|
| `os.environ.get("PROBE_KEY")` | 否 ✅ 认出 | 调用接收者名（`environ`/`getenv`） |
| `_env_int("PROBE_KEY", 1)` | 否 ✅ 认出 | **被调函数名前缀 `_env_`** |
| `_read_int("PROBE_KEY", 1)` | **是 ❌ 漏** | 前缀不匹配即认不出 |
| `ENV_PROBE = "PROBE_KEY"` | 否 ✅ 认出 | **左值形状** `RE_ENV_NAMED`（`ENV_`/`_ENV`） |
| `PROBE = "PROBE_KEY"` | **是 ❌ 漏** | 左值无 env 形状 |
| `{"PROBE_KEY": …}` 在配置面文件内 | 否 ✅ 认出 | **文件身份**（`ENV_MAP_FILES`） |
| `{"PROBE_KEY": …}` 在别的 `.py` 里 | **是 ❌ 漏** | 字典键无形状特征，只能靠文件身份 |

> `_env_int` 这条是 W1 补的**第四种形态**（原注释写"三种"是漏的，补之前 9 个键被误报）。
> `ENV_MAP_FILES` 那条**不是**覆盖面缺口：扫描面仍是全仓 `scan_roots`，收窄的只是
> "哪种字面量算配置映射表的证据"——`{"A3": …}` 这种普通数据字典与 env_map 在语法上
> 完全同形，**唯一能区分它们的是"这个字面量是不是配置映射表"，只能由人裁定**。
> 理由与逐项取舍写在 `verify_crossrefs.py:317-325`；**噪声面一大，判据迟早被整体关掉**，
> 那才是真正的 fail-open。

### ★ 门禁会假红，而假红比假绿更危险

判据的红**只说明"某条判据被触发了"，不说明"代码有问题"**。这轮实测到两类假红来源，
处理方式完全不同：

- **环境类**（红得毫无道理，容易被整体忽略）：`comment_audit` 曾因 `temp/` 缺失直接
  `FileNotFoundError` 崩溃 —— 红的理由是目录不存在，不是注释有问题。已修
  （`comment_audit.py:619` 补 `makedirs`）。**碰见 `Traceback` 而没有违规清单，先看
  环境，别当代码问题修。**
- **形态类**（红得对，但结论要打折）：`verify_doc_consistency` 的 DEADPARAM 只认
  Google 风格 `name: 说明`（`verify_doc_consistency.py:68`），**reST 风格
  `:param name:` 零覆盖** —— K4 实跑同一处假声明，Google 风格 exit 1、reST 风格 exit 0。
  反向还有 Q9 `referenced_path_missing` 的三处刻意放过（见「已知局限」第 5 条）。

> **读红绿的正确姿势**：退出码只回答"判据触发没有"，不回答"结论对不对"。形态覆盖不全
> 的判据红了要核形态，绿了也别当成"这一类问题不存在"。

### ★ 假红清单：哪些红与被测对象无关（2026-10-05 门禁失败方向审计 N2 实测）

上一节讲的是假红的**分类**，这一节是**逐条实测过的清单**：每条都写清触发条件、实测
输出与"该怎么处置"。**处置一律分两类**——能在门禁侧降低误报的已修（列在末尾），
需要改门禁代码的**登记在案**（本轮只读审计，不越权改 `ops/audit/*.py`）。
**判据的方向是对的**（真问题会红，这七轮实测都很扎实），失守的是反方向。

| # | 门禁 | 触发条件（与被测对象无关） | 实测形态 | 处置 |
|---|---|---|---|---|
| 1 | `verify_no_version_keys` | 本机有 `.venv/` / `build/` / `htmlcov/`（装了依赖、跑过 build、跑过 `--cov-report=html`） | 第三方包自带的 `*.yaml` 里的 `version:` 被报成违反铁律 1 | **登记待修**：它的 `SKIP_DIRS`（`:59`）漏了 `.venv/build/dist/htmlcov/site-packages/eggs/output/statalog`，而姊妹门禁的 `scan_roots.is_excluded_dir` 这十项**全部**返回 `True`。同仓两份扫描面口径 |
| 2 | `count_code_lines` / `comment_audit` / `verify_doc_consistency` / `verify_import_graph` | `.py` 带 **UTF-8 BOM**（Windows 记事本、某些 IDE 默认、跨工具粘贴） | 四门**同时**报 `[PARSE] ... invalid non-printable character U+FEFF` | **登记待修**：`ast.parse(bytes)` 直吃 BOM 没问题（实测 OK），炸的是"先 decode 成 str 再 parse"。同目录的 `verify_no_version_keys.py:98` 已用 `encoding="utf-8-sig"`——同一目录两种口径 |
| 3 | `comment_audit` | `.py` 以 **GBK** 落盘 | 汉字被 `errors="replace"` 变成 U+FFFD → 报 `module_header_not_chinese`「模块头无中文说明」 | **登记待修**。这一条**最误导整改方向**：报的是铁律 2（中文 docstring）的违反，而文件里百分之百是中文，按指引去"把注释改成中文"改多少遍都不绿。干净对照实测：同内容 UTF-8 落盘只报 `module_header_thin`，GBK 版多报 `docstring_not_chinese` |
| 4 | `verify_doc_consistency` | docstring 里有**散文编号**（"典型用法分三步：1. … 2. … 3. …"）而代码只有两个 `# ── N.` 分节 | `[STRUCT] docstring 列 3 项, 代码实际有 2 个分节 (以代码为准回正 docstring)` | **登记待修**：报错措辞会把人引向"改 docstring"，而正确处置恰恰是**别改**（那句散文是好的）。判据只比最大序号，不区分语义；其陷阱清单（`:38-41`）只提醒"别在 docstring 里写编号清单"，即**明知会误伤却仍留着** |
| 5 | `verify_doc_consistency` | 抽象方法的标准写法（docstring 诚实登记形参 + `raise NotImplementedError`） | `[DEADPARAM] read(... encoding ...): docstring 称「文本编码。」但函数体内零引用` | **登记待修**：`DISCLAIMER`（`:70-74`）含 `占位/替身/桩不/签名对齐/unused`，**不含** `NotImplementedError`/`由子类实现`。处置动作是"为了过门禁而改注释措辞"，属公开承认降级。注：同一判据对 reST 风格 `:param name:` **零覆盖**（K4 实测，Google 版 exit 1 / reST 版 exit 0），两者要一起看 |
| 6 | 四道 AST 门 | 并行工作区里另一个 agent 正在保存文件，门禁读到**半成品** | 在三引号内部截断实测：`count_code_lines` 0→1、`verify_doc_consistency` 0→1、`comment_audit` 与 `verify_evidence_anchors` 连带红 | **固有**（任何读盘门禁都有），重跑一次即转绿。**判读要点**：报 `[PARSE]` 而文件"看起来是好的"时先想到时序竞争，别急着自证"我改坏了" |
| 7 | `code_fingerprint` | 在**无 `.git`** 的目录上跑（裁剪克隆、zip 分发、拷进别的仓） | `compared=0 code-changed=0 new-untracked=18` 且 **exit 0** —— 每个文件都走"新增未跟踪"分支 | **已被现有守卫覆盖一半**：`compared == 0` 应判红（无基线可比 = 判据未生效，铁律 5），但真仓上有 `test_compared_is_positive_and_covers_all_tracked_files` 钉着，真仓不会空转。假仓场景由 `test_gate_scan_coverage.py` 覆盖 |

> **第 1 条是本清单里唯一"装个依赖就红"的**，也是最容易被误诊成"我加了版本号"的
> （`file:line` 带着 `.venv/...` 路径，人肉一眼能看出是误报，但**第一次遇到的人
> 不会立刻想到这是环境问题**）。修法是让 `iter_yaml_files` 复用
> `scan_roots.is_excluded_dir`——与 D5-01 收口覆盖面是同一个动作，本轮只读未做。

#### 假仓构造会污染"干净对照组"（已修，2026-10-05 N2）

判据级红测试用**假仓**（门禁都用 `parents[2]` 定位仓根、没有 root 参数，只能靠复制
脚本换扫描面）。原先三处构造都是 `for script in AUDIT_DIR.glob("*.py")` 复制**整个**
`ops/audit/`，于是假仓里躺着全部门禁脚本的副本，而**每个副本都进门禁扫描面**——
「干净对照组」实际扫描的是 `ops/audit/*.py` 的副本。两个通道都实测复现过：

- **通道 1**：只在**被复制的** `check_line_endensions.py` 末尾注入一个声明了
  `beta_unused` 而函数体零引用的函数，假仓 `src/ok.py` 保持干净 →
  `verify_doc_consistency` exit 1，且只报那个副本；
- **通道 2**：把被复制的 `scan_code_smells.py` 换成 450 净行内容。假仓没有
  `docs/architecture/file-size-budget.md`（登记簿缺失），于是**任何**超限文件都算
  「未登记超限」→ `count_code_lines` 的对照组同样被带红。

这类红与被测命题（`agents/` 落位覆盖面、Q7 口径、版本键、错误码契约）**毫无关系**，
正是"狼来了"的起点。**引爆点很近**：`comment_audit.py` 实测 **331 净行，距 400 只剩
69 行**，按本仓注释密度规范一个判据增补即可吃掉，届时所有相关对照组同时变红，而报错
指向 `ops/audit/comment_audit.py`——与"落位是否影响覆盖面"毫无关系。

**已修**（`test_gate_criterion_red.py` / `test_gate_scan_coverage.py` /
`test_env_ssot_covers_all_code_reads.py` 三处）：改为只复制**被测门禁 + 它按真实
`import` 递归算出的同目录依赖闭包**。闭包实测：`count_code_lines → {自身, scan_roots}`、
`comment_audit → {自身, line_scope, scan_roots}`、`verify_crossrefs → {自身, env_scope,
scan_roots}`。**按真实 import 递归算而不是手抄名单**：手抄会在门禁新增依赖时过期，
而过期的闭包会 `ModuleNotFoundError`——那会**伪装成"门禁判红了"**（D5-05 点名的脆弱性）。
反证：`temp/_n2_negctl_fakerepo.py` 第 [4] 项证明剪断依赖确实会崩，故闭包不能省。

#### 报告型工具"恒不阻断"这条不变量，此前只守住了 1/5（已补齐）

`check_line_endings` 有 `TestLineEndingsIsNotVacuous::test_report_type_tool_never_blocks`
用脏文件断言 `returncode == 0`；**另外四个在 `test/` 下零命中**。明天有人把
`verify_no_code_loss` 改出 `exit 1`、或直接接进 `make audit`，测试不会响，而文档早就
写着口径——两者会"自洽"地一起骗过读者。**已补**
`test_audit_gate_contracts.py::TestReportTypeToolsStayUnwired`：逐个点名五个报告型
工具不得出现在 `Makefile` 的 `audit:` 配方块里，并钉住清单条数不被静默删减。
它与既有的 `TestMakefileWiring`（断"硬门禁**必须**在"）互补——只钉后者的话，
往 `audit:` 里加一行报告型工具不会让任何测试变红。反证：
`temp/_n2_negctl_report_wiring.py` 注入三个接线点全部被抓（3/3），`Makefile` 已复原。

> **`README.md` 根文件的两处过时**（不在 `ops/audit/` 内，本轮未改）：`README.md:30`
> 把 `verify_no_code_loss.py` 写成「**（退出码 0）**」当作复测验收条件，而它是**报告型、
> 结论只看 stdout**，照字面执行得到的判定口径与 CLAUDE.md 相反；`README.md:35` 仍写
> 「`make audit` 里是**六项**硬门禁」并只列 6 个名字，而 `Makefile` 现有 **9 条**。
> 该行是"哪些会阻断"的唯一 SSOT，照它理解会以为铁律 1、E3 锚点、计数型断言无人拦。
> **无任何门禁覆盖"文档里的门禁清单 vs `Makefile`"的一致性**——
> `verify_crossrefs.py` 的治理文档检查只管反引号路径存在性，不管清单条数。

### ★ 判据级红测试自己也可能恒绿，而它的职责正是"防门禁恒绿"

"给每条门禁配一道注入缺陷的红测试"这套做法本身有一个**恒绿形态**：
写成 `for line in ...: if 命中: pytest.fail(...)` 时，**条件不成立时循环体一次都不执行，
整条测试零断言通过** —— 而它要防的恰恰就是"门禁恒绿"。

K4 实跑对照（2×2，同一探针两种写法 × 两组输入，唯一变量是门禁里有没有 `SCAN_DIRS`）：

| 写法 | 门禁含 `SCAN_DIRS`（缺陷在） | 门禁不含（缺陷已修） |
|---|---|---|
| `for`/`if` + `fail` | exit 1 ✅ 抓到 | exit 0，**断言执行数 = 0** ❌ 恒绿 |
| `assert not offenders` + `assert len(lines) > 10` | exit 1 ✅ 抓到 | exit 0，**断言执行数 = 2** ✅ 真断言后通过 |

两行 `exit 0` 单看**完全无法区分**，唯一区别在断言执行数。所以**正确写法是断"没有"
（`assert not offenders`）而不是"逐行 fail"，并补一条防空读断言**（读到空文件
不能算通过）。本仓这条已落地在
`test/unit/meta/test_gate_scan_coverage.py:227`（`TestScanScopeIsSingleSource`）。

> 判据审计 D5 统计的是**7/8**（其审计范围内的八道门禁里，唯一缺判据级红测试的是
> `verify_tree_integrity`），**已于 2026-10-05 补齐**在
> `test/unit/meta/test_tree_integrity_criterion_red.py`（K4 已核：文件在盘，四条用例
> 分别覆盖「基线绿 / 清单外新增红 / 登记过被删红 / 树块整段缺失红」，且每条红都配对照）。
> 注意 D5 的"8 道"不含后来新增的 `verify_counting_claims` 与 `code_fingerprint`，
> 引用这个比率时**别当成全量覆盖率**。覆盖齐了也不等于每条都带对照——
> **每条"必须判红"都要配一道干净对照**（`exit 0`），否则"门禁恒红"和"门禁恒绿"
> 同样能满足 `!= 0`，证据等于零。

### ★ 刻意留白的覆盖面：判据级红测试补齐之后，哪几块仍是盲区

- **`verify_tree_integrity` 对 `docs/` 结构性失明**：`docs` 被列进 `OPAQUE_DIRS`
  （`ops/verify_tree_integrity.py:55`），K4 实跑：删/增 `docs/` 下的文件树门禁都
  exit 0，而删 `src/` 下的文件 exit 1。而 `docs/eval-E1..E6-*.md` 按 CLAUDE.md 是
  **方案真值**、且有 34 份受跟踪文件。**树门禁是本仓宣称的文件树 SSOT 守门人，却看不见
  `docs/` 的增删改名** —— 这是本节最该记住的一条"别信它"。判据级红测试
  `test_tree_integrity_criterion_red.py` 的 docstring 已明写这条盲区**刻意不钉成契约**。
- **`verify_import_graph` 对 `ops/` 零覆盖**：`IMPORTABLE_BASES = ("src","rag","evals")`
  （`verify_import_graph.py:25`），对 `ops/` 做真 import 会执行 `runpy` 转发 shim
  （`skill_cli.py` 等会 `SystemExit`），这个取舍**成立**；代价是 `ops/` 下受跟踪的
  27 个 `.py`（K4 实测 `git ls-files` 计数）的断链导入**没有任何门禁在看**，
  只在运行时才炸。K4 实跑：断链放 `ops/` → exit 0，放 `src/` → exit 1。
  "判据选得对、覆盖面选得错"的一类。
- **判据"收窄了就绕过"**：`verify_doc_consistency` 的 STRUCT 分节判据要求 docstring
  用**编号清单**才判（`verify_doc_consistency.py:109` 的 `if len(items) < 2: return`）；
  把编号清单改成**散文**描述，整条判据直接消失。这条判据的存在理由本就是"docstring
  说四类、代码实现九节"那次事故，而修法是"要求写编号清单" —— **用格式强制代替内容
  核对**，改个文体就绕过整条判据。

### 汇报门禁状态时必须做的两个动作

1. **把"恒红型"和"恒绿型"分开说**。`code_fingerprint check` 在有未提交真代码改动时
   必然 exit 1，那是它在正确工作；把它混进"九条全绿/九条有红"里报，等于要么虚惊
   一场、要么把真改动藏起来。
2. **说清"判的是哪一面"**。同一个 `verify_crossrefs`，§7 的覆盖面（全仓黑名单）与
   归类面（配置面文件名单）是**两个真源**，报结论时说"env 侧对账通过"就够，不必
   也不会连带承诺"env 读取形态已全认"。

> **扫描面 = 判据覆盖面（2026-10-05 改口径，判据审计 D5-01）**：`count_code_lines` /
> `comment_audit` / `verify_doc_consistency` / `code_fingerprint` 四道门禁此前**各抄一份**
> 目录白名单 `SCAN_DIRS`，实测在 `agents/` 下放一个 900 净行的文件时四道全部 exit 0 ——
> 白名单之外的 `.py` 完全免检，一处缺口同时废掉四条判据。现在覆盖面统一取
> `scan_roots.iter_py_files()`：**走遍全仓 `.py`**，只排除三类非源码目录（工具/版本库
> 状态、第三方依赖与构建产物、gitignored 的数据与临时区，逐项理由见该模块头的表格）。
> 差别在**默认方向**：新建目录里的 `.py` 现在自动进门禁，而白名单口径下它自动免检。
> 四道门禁不再自带清单 —— 单测 `test/unit/meta/test_gate_scan_coverage.py` 钉住这一点
> （谁自带清单、谁没导入共享真源、排他项里是否藏着受跟踪 `.py`，三条各一组断言）。

> **九条硬门禁里 `code_fingerprint` 的性质与其他八条不同（2026-10-03 澄清）**：
> 它的职责就是「工作区与 HEAD 的**代码**指纹有差异即红」（其模块 docstring 明写
> 「退出码 0 = 无代码改动；1 = 有代码改动或被跟踪文件被删除」）。因此**只要工作区
> 有一处未提交的真实代码改动，它就必然 exit 1** —— 这不是缺陷，是它在正确工作。
> 其余八条（`count_code_lines` / `comment_audit` / `verify_import_graph` /
> `verify_crossrefs` / `verify_doc_consistency` / `verify_no_version_keys` /
> `verify_evidence_anchors` / `verify_counting_claims`）是**恒绿型**判据，与提交状态无关。
> 换言之：**纯注释改动**（本仓绝大多数改动）不触发它；**含代码改动的轮次**在提交前
> 会红，提交后转绿。汇报门禁状态时必须把这两类分开说，不要笼统称「九条全绿」。

### `verify_crossrefs.py`：覆盖面与归类面是两个真源，别混

§7 的 env 三方对账是本仓"覆盖面 vs 归类面"分离得最干净的一处，也是判据审计踩过两次
的地方，**改这一段前先读完再改**：

- **覆盖面**（哪些 `.py` 要扫）走 `scan_roots` 的全仓黑名单（`verify_crossrefs.py:339`），
  **不再有文件名单**。补丁前这里是 `CONSUMER_FILES` 写死 3 个文件的白名单，与
  `count_code_lines` 等四处的 `SCAN_DIRS` 属**同一种反模式**、同一个教训第二次犯错；
  代价是 `src/tap/client.py` 读 `BEST_TAP_URL` 这类真实读取点被误报成"代码未读取"。
- **归类面**（哪些读取点算"部署期配置输入"）走 `env_scope` 的在册裁定，与覆盖面正交：
  已被逐条裁定为非部署期输入的键不要求登记进 `.env.example`，照它配不改变行为。
  未裁定的同类键照样判红（漏裁定会红，不是静默放过）。
- 现在的 3 文件名单叫 `ENV_MAP_FILES`（`verify_crossrefs.py:326`），**只管形态 (c)**
  （哪些字典字面量算配置映射表），不再管覆盖面——两种"清单"含义不同，别当同一面看。

判据认四种 env 读取形态（`verify_crossrefs.py:302`），其中 `_env_int("KEY", 1)` 这种
**本地包装器**是 W1 补上的第四种（原注释写"三种"是漏的，补之前 9 个键被误报）。
各形态的实测对照与"认不全就误报"的后果见上文「判据'认几种形态'直接决定它能看见什么」。

### `verify_counting_claims.py`：为什么判据宁可漏，也不要变成噪声源

E3 注释腐烂审计（§3 C 类 / §4.1）审出最刺眼的一类腐烂是**同一个提交内部就自相矛盾**：
提交 `88792e1` 的标题就是「client.py 463 → 380 净行」，而它**新建**的
`src/client_phase1.py` 模块 docstring 却写「client.py 实测 463 净行仍超 400 预算」。
这不是"忘了改"，是"把旧数字抄进了新文件"，且抄的那一行恰好就在被改动的对象上。
code review 与 ruff 都看不见它：那行注释是**新增**的，没有任何工具会比对"新写的
数字"与"被改对象的当前状态"。

本门禁把那一类变成可判红：扫 `.py` 里的注释/docstring，凡形如
`<某个 .py> … <N> 净行` 的断言，就用 `count_code_lines.measure` 重算该文件净行，
不一致即红。**重算口径与门禁本体完全同一份**（复用 `measure` 而非另写统计），
覆盖面也取自 `scan_roots.iter_py_files` —— 两样都不另立真源，否则门禁就开始用自己的
口径判全仓，噪声随之而来（D5-01 同形）。

**刻意不收的四类**（每条都有实测理由，逐条可复核）：

| 不收 | 理由 |
|---|---|
| `物理行` | 口径不统一：`src/protocol_catalog_tables.py` docstring 写「730 物理行」，`splitlines()` 实测 729、"末尾换行算一行"则是 730——两种算法都对，判谁错都是噪声 |
| 裸计数（`26 条`/`共 96 列`） | 绝大多数指向**外部站点事实**（BEST 有多少列、多少用例），重算输入不在仓内，收进来必然长期红 |
| 历史/转场语境（「拆分前 463」「由 971 增至 990」） | 这类断言**说的就是过去**，拿当前磁盘比它必然不符——那不是腐烂，是它的原用途。CHANGELOG 与 budget 文档整篇是这一形态 |
| 归属不可判定（仓内同名 `.py` / 窗口内出现第二个 `.py`） | 数字到底指哪个文件无法机械判定，**宁可放过不猜** |

**为什么不会变成噪声源**：判据定稿前先跑原型**量精度**，而不是推理。规则收窄前是
3 红 1 误报（误报形态：`test_gate_criterion_red.py` 里"改成 `return 0` 并提交:
1020 净行的文件"，那个 1020 说的是被注入的假文件，不是前面点名的门禁文件），
加上"数字不紧跟『的』"一条后误报归零——`净行` 后面跟 `的` 说明该数字在**修饰一个
名词短语**（在定义某个东西），不是断言被点名文件的度量。定稿后在 HEAD 上实测
**受检 3 条、误报 0 条、真问题 2 条**（`ops/cli_download.py` 与
`src/crossmatch_jobs.py` 的陈旧净行，均已在同一轮订正）。

判据级红测试见 `test/unit/meta/test_counting_claims_gate.py`，三类各一组：
**判红**（注入错数字必红 + 干净假仓必绿的对照）、**防噪声**（历史语境/歧义/
修饰用法逐条钉住不得误报）、**契约**（覆盖面来自 `scan_roots`、口径复用 `measure`）。
第二类与第一类同等重要：门禁的失败模式不是"漏抓"，而是"老红着被人整体关掉"。

### `verify_evidence_anchors.py`：为什么判据钉在符号上而不是行号上

E3 的 `evidence` 字段是「这道题的断言在仓里哪条代码处成立」的指针。它此前既无门禁
也无任何消费者（全仓 `*.py` 搜 `evidence`/`must_state` 零命中），实测 7 题锚点指向
与断言无关的代码——指针失准意味着那道题的事实基座根本不存在。

判据分三档：**文件存在** / **行号在范围内** / **符号落在锚点附近（±8 行）**。第三档
才是真正抓住「288 vs 380」那一类误指的判据。之所以不用「精确命中」，是因为行号会随
`src/` 上方任何一次注释增删整体平移（本轮实测 `src/models/__init__.py` 在任务进行中
从 524 行长到 526 行、哨兵常量从 378 漂到 380），而符号跟着代码走。锚点语法因此取
本仓覆盖矩阵已在用的 `path:N-M::symbol` 形态（见 `test_coverage_matrix.py`），两处
共用同一套锚点约定。容差 8 行的依据：实测全部失准锚点与真身相距 37~92 行，8 行挡不住
任何一处真实失准，却能吸收注释级的行数抖动——门禁一旦成为噪声源，迟早被整体关掉，
那才是真正的 fail-open。

**已知局限（不掩盖）**：本门禁只证明「指针没指错地方」，不证明「这段代码支持这句
断言」——后者需要人或模型判读，它刻意不猜。散文形态锚点（`references/xxx.md 概述段`）
只能校验到文件存在这一层，会以 WARN 形式列出待改写清单。

## 本轮门禁变更登记（2026-10-03，提交前必读）

这一轮整改**含 5 处真实的代码改动**，不只是注释。它们尚未提交，因此
`code_fingerprint check` 现在是 exit 1（见上文「九条硬门禁里它的性质与其他八条
不同」）。登记在此而非只写在 CHANGELOG —— 后者**当时**因走 `.gitignore` 而仓内读者看不到，
仓外不可见的变更史等于无史，这是当初把知识复制进已跟踪文件的原因；该复制做法保留
（多处读者确实只读仓内文件）。`CHANGELOG.md` 已于 2026-10-05 改判为入版本控制，
两处现在都在仓内，本登记仍不撤——**复制是缓解手段，不是替代品**：仓内读者未必
去翻 CHANGELOG。

| 文件 | 改的是什么代码 | 为什么该改 |
|---|---|---|
| `comment_audit.py` | 新增 Q9 / Q10 两类判据 + `continuation_rows`/`field_decl_rows`/`assert_rows`/`fixture_rows`/`bracket_only_rows` 五个分母排除层 | 补上「注释说的是不是真的」与「一行对一行」两个此前完全没有的维度；净行 284 → 约 420，已按 `docs/architecture/file-size-budget.md` §3.13 登记超限并写明拆分预案 |
| `count_code_lines.py` | 语法错文件原返回 −1 净行（恒不满足 `> BUDGET`），改为显式收集并判红 | 旧行为是 fail-open：坏文件在本门禁与 `comment_audit` 的**双重沉默**里消失（两边都指望对方兜底） |
| `evals/repro/run_e6.py` | 删 `TASKS_DIR` / `PASS_SCORE` / `WARN_SCORE` 三个全仓零引用死常量 | 留着会让人以为改那里能调 R0 放行线，而 R0 根本不做加权评分 |
| `evals/ablation/report.py` | 报告表头字符串「九系统主表」→「主表 (T1: 11 装配 × 11 列)」 | 把过时数字从**报告产物正文**里去掉（这是普通字符串不是 docstring，故 AST 有差异） |
| `test_audit_gate_contracts.py` | 新增 Q9 / Q10 / 自一致三组反例守卫（共 11 条断言） | 判据类缺陷必须可被断言，否则门禁写反了无人能发现（Q7 首版就栽在这） |

另有第 6 处 AST 差异：`src/scripts/__init__.py` 原首行只是 `#` 注释（无 `__doc__`），
按 Q1「模块头必须有 docstring」改成了真 docstring —— 这是**语义变更**
（`__doc__` 由 `None` 变成字符串），一并登记，不藏。

**判据修复过程中自己也踩了四次「度量错了对象」**（详见 CHANGELOG「逐行对照轮」）：
隐式拼接字符串漏判、度量脚本自行重写 docstring 行号、排除函数签名会吃掉整个函数体、
样板行的扣减写在 `continue` 之后。四次都由守卫测试兜住，无一漏网。

## 第三轮门禁变更登记（2026-10-03，「按注释完善代码」）

这一轮的口径与前两轮**相反**：不是给代码加注释，而是查「注释声明的契约代码有没有兑现」。
四路只读审计（`src/` / `evals/` / `test/` / `ops/`）共报 18 条，逐条复核后确认 **7 处真代码缺陷**
（不是注释过时）。它们尚未提交，因此 `code_fingerprint check` 仍是 exit 1（同上文）。

| 文件 | 改的是什么代码 | 为什么该改（注释是规格，代码没兑现） |
|---|---|---|
| `evals/equivalence/sentinel.py` | 新增 `_numeric_literal()`，补 `UnaryOp(USub)` 分支 | **死守卫**：模块 docstring 声称扫 `<= -999` 这类形态，可 Python 把 `-999.0` 解析成 `UnaryOp(USub, Constant(999.0))`，而原判据只认 `isinstance(operand, ast.Constant)` —— 于是它对**任何**负哨兵恒不命中，报出来永远是一份空清单。这类「检查存在但恒不触发」的守卫比没有守卫更危险。已补 `temp/sentinel_negctl.py` 正反控制 10/10（含端到端：往 `evals/` 放真硬编码哨兵，守卫必须报出来） |
| `evals/robustness/runner.py` | 哨兵阈值改读 `load_null_sentinel()["threshold"]` | 行尾注释写「阈值取 `_data/null_sentinel.yaml`」，代码却是内联字面量 `-999.0` —— 正是上一个守卫该抓的硬编码形态。取阈值放在 `try` 之外：字典缺失必须炸，落进 `except` 就成了「读不到阈值 = 没有哨兵」的静默放行 |
| `evals/groundtruth/metrics/m3_units.py` | 新增 `_is_padded_precision()`，补零形态分流进 `precision_warnings` | docstring 与行内注释都写「整数补 .000000 的假精度**不判错但记 warn**」，而 `precision_warnings` 全函数**一次都没被 append 过** —— 注释承诺的 warn 通道不存在，且补零值实际落进 `precision_errors` 判错，与注释写的方向相反。`temp/m3_negctl.py` 7/7，含关键反例：真降精度（`18.2`）必须仍判错并 `pass=False` |
| `evals/groundtruth/run_e2.py` | `metascore` 并入 `pass` 的合取项（由四条变五条） | `metascore()` 的 docstring 写「metascore < 1.0 → E2 FAIL（判定器自身失效）」，而 `pass` 不含它、退出码只看 `pass` —— 判定器漏抓注入故障时整轮照样绿，报告正文却照印「必须 1.00」。fail-open 就藏在注释与实现之间。实测 metascore=1.0，E2 仍 17/17 exit 0，即补洞不改变现有结论 |
| `ops/audit/verify_crossrefs.py` | 新增 `require_source()`，五处必读源接入 | 铁律 5 禁 fail-open。`load_yaml` 只在「读不到/解析失败」时记 `[YAML]`；文件存在但内容为空时 `yaml.safe_load` 返回 None 且**一声不吭**，于是五节 `if spec:` 之类守卫整节跳过 —— 门禁 exit 0 而该节覆盖是零。空与坏是两类问题，故分记 `[EMPTY]` 而不是混成一类。同文件第 7 节早有 `else: issues.append(...)` 的正确写法，这五节只是没照做。`temp/crossrefs_negctl.py` 4/4（含「五个守卫点都接上了」的静态断言） |
| `src/client.py` | `Retry(...)` 补 `backoff_max=MAX_BACKOFF_S`，并 import 该常量 | `src/protocol.py` 把 `MAX_BACKOFF_S = 60.0` 注释为「指数退避的封顶值，消费方同上」，全 `src/` grep 该常量**零生产引用**，E4 的 rubric 还拿它当已生效的判据。接上即修掉「公开符号零生产引用」。注：`total=3` + `backoff_factor=2.0` 的退避序列只有 2/4/8 秒，**本条当前不改变任何运行时行为**，它防的是日后调大 total/backoff_factor 时指数项失控；`Retry-After` 不受此封顶约束（那是服务端意图） |
| `evals/repro/run_e6.py` | canary 探针的异常处理由「吞成空行集」改为记账 + 显式抛错 | 该处原注释已如实登记了这个 fail-open 并写明修法（「必须先改成显式阻断，记 failed 而非空行集」）——本轮按该规格落地。旧实现里探针抛错 → `rows = []`，而 `canary_after` 直接复用 `before`，于是「探针全挂」与「跑批稳定」在指纹上**同形**：一条恒真的稳定性证据比没有证据更糟。实测探针全部成功，E6 仍 `OK: 80` / exit 0，即本条只在探针真失败时才阻断 |

**这一轮同时修掉的注释错说**（零行为风险，未计入上表）：`verify_doc_consistency.py` 的死参数判据
三处注释方向与代码**完全相反**（注释说「docstring 声明了签名里没有的参数」，代码查的是
「签名里有、docstring 声明了、函数体却零引用」）；`comment_audit.py` 模块 docstring 只列
Q1–Q8 却自称「回答八个问题」（实为十个检查组，Q9/Q10 缺席）；`ai_tools.py` 把「毫秒精度」
写成「毫秒」（值单位是秒）；`multiband_photometry.py` 的三段式残留（实为两段）；
`examples/` 里写死的 `K = 28`（注册表实为 30 列）；`test_audit_fixes.py` 指向不存在的
`TestStdGroupExpansion`；`test_fixes.py` 引用已删模块 `src.pybest.Best._request`；
`ablation/runner.py` 把阻断项归属说反（`_blockers()` 只实现 1/4/7，2/6 在上游抛）。

**「与代码无关」的噪音怎么判**：用户口径是「右注可保留不删，要删的是和代码无关的噪音」。
据此否掉了按「复述即噪音」批量删注水的做法 —— `# 限流归0`、`# 打桩在数据面`、`# 上限`
这类极简右注短但在讲这行代码，全部保留；带理由的「同上, 独立于行为维度」同样保留。
真正清掉的是三类：光秃秃的「同上」（把「去上面找」的成本甩给读者）、讲「这次怎么改的」
而不是「这段代码怎么工作」的元注（如「原注释标的第 230/234 行已错位」）、以及同一语句
上下重复说同一句话。

**判据本身也被这轮改动逮到一次**：`test_audit_gate_contracts.py::TestSelfConsistency`
在补 Q9 说明时红了 —— 我写了「Q1–Q8 全是结构性检查」，而该守卫规定凡出现 `Q1–Qn`
就必须同句消歧为「N 个**检查组**」。改成「此前那八项全是结构性检查」即通过。同理，
新写的测试自己也先被 `comment_audit` 逮了两轮（缺 docstring、行内 import 缺中文说明）。
两处都不是我复查出来的，是门禁自己报的 —— 这就是它们存在的理由。

## 运行约定

```powershell
python ops/audit/<tool>.py          # 单工具直跑 (无参数依赖)
```

- **每个工具的 ROOT 统一为 `Path(__file__).resolve().parents[2]`**（`ops/audit/x.py`
  上溯三级 = 仓根），换机/换克隆目录可跑。
  > 修正记录：此前本文件声称"已统一"，实测 **6/9 不成立** —— 3 个用
  > `parents[1]`（指向 `ops/`，全部错位），3 个硬编码 `<MONOREPO_ROOT>` 绝对路径。
  > 错位的 `verify_crossrefs.py` 因此直接 `FileNotFoundError` 崩溃。
  > 2026-10-02 补修：11 个工具中**最后一个**硬编码残留 `code_fingerprint.py`
  > 已改相对定位；现 11/11 合规，硬编码绝对路径在本目录已清零。
- **git 相关工具必须在 `astro-best/.git` 这个仓里跑**。本 skill 是独立 git root，
  父目录 `G:/tw/twskills` 是另一个仓库且已不再跟踪本目录；`verify_no_code_loss.py`
  曾把 ROOT 指向父仓，拿**父仓陈旧 HEAD** 当基线比子仓工作区，把"早已提交的重写"
  误报成"代码丢失"。`code_fingerprint.py` 曾犯同类错（详见下表该行）。
- 产物（`temp/*.json`）属临时测量输出，不随仓库分发；
- 工具的 lint 口径见 pyproject.toml 的 `ops/audit/*` per-file-ignores
  （一次性测量脚本：本地 git 只读子进程 + 既有风格债，与 `evals/*/tests/*`
  同款登记制）；
- 工具自身的注释规范由 comment_audit.py 同口径守护（当前全项 0）。

## 注释密度标准（2026-10-03 起，`comment_audit.py` Q5/Q6 强制）

需求原文：「每个文件开头都有整个文件的详细注释，并且每一行代码都有对应的注释」。
落成两条**可判定**的硬检查（`comment_audit.py` 的 Q5/Q6，前六项为原有 Q1–Q4）：

| 检查 | 判据 | 阈值来源（全仓 254 个 .py 实测分位） |
|---|---|---|
| `module_header_missing` / `module_header_thin` / `module_header_not_chinese` | 模块级 docstring 必须存在、必须含中文、字符数 ≥ 160 | 头长度 p10 = 156，取 160 留余量；命中 27 个文件 |
| `inline_comment_density_low` | 注释行 / 净代码行 ≥ 0.10（净代码行 < 15 的小文件与已登记豁免项不判） | 密度 p25 = 0.083，取 0.10；命中 74 个文件 |
| `trailing_comment_ratio_low` | **行尾**注释行 / 净代码行 ≥ 0.10 —— 落实「代码在左边、注释在右边」 | 行尾占比 p25 = 0.093，取 0.10；命中 71 个文件 |
| `trailing_comment_spacing` | 行尾注释与代码之间至少留 **2 个空格**（PEP 8），同一块内建议对齐成列 | PEP 8 |
| `referenced_path_missing` | 注释与 docstring 引用的**仓内路径必须真实存在**（从仓根/本文件目录/其父目录三处都解析不到即判缺失） | Q1–Q8 全是结构性检查，没有一条管「注释说的是不是真的」，见下节 |
| `line_alignment_low` | **非平凡语句**里有行尾注释的比例 ≥ 0.70（样板行与数据行不进分母，见下节） | 诉求「尽量一行对一行，左右对照，而不是上下代码注释」的可判定形式；整改期起步 0.45，2026-10-03 全仓达标后上提到 0.70 |

### 「一行对一行」的正确口径：Q7 与 Q10 的分工

Q7 算的是「行尾注释行 / 净代码行」，口径偏粗 —— 它的**分母含样板行与数据行**，
于是「给列名逐行写右注」也能把指标刷上去，那是**注水不是对照**。Q10 换掉分母：

| 行类别 | 是否进 Q10 分母 | 理由 |
|---|---|---|
| 非平凡语句（赋值 / 调用 / `if` / `return` 之外的逻辑行） | ✅ 进，且需右注 | 这才是「一行对一行」要覆盖的对象 |
| 样板行（`import` / `return` / 收尾括号 / `def` / `class` / 分隔线） | ❌ 不进 | 写右注只是复述语法本身（`# 导入 os` 是废话） |
| 数据行（元素数 > 6 的 List/Dict/Set/Tuple 内部） | ❌ 不进 | 给 `"ps1_ra",` 写「RA 列」等于复述内容；由**块首那一行**的右注说明「这一块是什么」 |
| 声明式字符串行（跨行语句里的字符串字面量，含隐式拼接） | ❌ 不进 | 多行正则片段逐行写注释就是把正则复述一遍 |
| docstring 行 | ❌ 不进 | 已由 Q1/Q2/Q5 管 |
| import 续行名单行（`from x import (` 内） | ❌ 不进 | 给 `attribute_lane,` 写「导入 attribute_lane」是注水 |
| 多行函数签名的参数行（`def f(` 到函数体之前） | ❌ 不进 | 参数名与类型注解已写在行上，再补一句就是复述签名 |
| 跨行语句的**非首行**（含多行调用的参数行） | ❌ 不进 | 一条 `x = foo() if c else bar()` 展开成三行只承载**一个**判断，续行是该判断的延续 |
| 声明式字段行（`truncated: bool = False` / `X = Y` 别名） | ❌ 不进 | 右注只能把字段名/右值读一遍 |
| 单独占一行的 `(` / `[` / `{` 开启行 | ❌ 不进 | 与下面那串元素是同一个结构，常是数据表首行 |
| 以 `\` 结尾的**续行符首行** | ❌ 不进 | 追加注释会让 `\` 后面不再是换行、直接语法错；其说明本来就写在**续行第二行** |
| `assert` 语句 | ❌ 不进 | 本仓测试规范要求「挡什么回归」写在断言**上方**；右注会与之重复 |
| 测试夹具/打桩构造（`Mock()` 赋值、裸表达式调用） | ❌ 不进 | 「造一个假响应」没有可解释的 why |

> **这十一类排完之后，分母里不再有任何「物理上无法覆盖」的行。**
> 判据完备即：**每一行要么进分母（须有右注），要么被排除（且有明确理由）**。
> 可用 `python temp/verify_completeness.py` 复核当前是否仍有「进分母却无右注」的行 ——
> 它同样**只调用门禁本体的排除层**，不在脚本里另写一套。

> **为什么把这么多类移出分母**：这十类行的右注只能复述代码本身。`# 导入 os`、
> `# 返回结果`、`# 遍历列表`、`# 一个列表` 都不是注释，是噪音。**判据一旦被
> 注水行喂饱，指标就失去意义** —— 那正是 Q7 首版判据栽过的坑（把「上方缩进注释」
> 当行尾注释，154/226 个文件真实行尾注释为 0 而门禁报全绿）。
>
> **实现陷阱（实测踩过三次）**：
> ① 相邻字面量 `r"a"  r"b"` 在 AST 里是**一个** Constant（`lineno=80 / end_lineno=81`）。
> 只判「单行字符串」会把多行正则片段整片漏判成可注释代码，逼人给正则写复述型右注。
> `string_const_rows()` 因此取**完整行范围**。
> ② 排除函数签名时**不能**按 `FunctionDef.lineno..end_lineno` 整段排 —— 那会把整个
> 函数体一起吃掉、分母归零、门禁形同虚设。只排到 `node.body[0].lineno - 1`。
> ③ 样板行的排除必须放在 `net += 1` **之前**。放之后的话，「有行尾注释的样板行」
> 会先被 `if aligned: continue` 跳走、扣减永远执行不到 —— 样板行只要写了注释就
> **既进分母又算对照**，而没写注释的才被扣掉。实测让分母混进约三成样板行。

**连续行 `\`（续行符行）无法加行尾注释** —— 追加后 `\` 后面不再是换行，直接语法错。
这类行的注释写在续行的第二行。这是第四个「与工具链打架的例外」。

### 注释说的是不是真的：Q9 的判据与它的放过面

Q1–Q8 管的都是「注释写没写、写在哪、写多少」，**没有一条管「注释说的是不是真的」**。
后果实测（2026-10-03 全量对照）：`docs/eval-E1-nl-to-tool.md`（真名 `eval-E1-nl2tool.md`）、
`evals/nl2tool/test-scenarios.yaml`（真名 `tasks.yaml`）这类悬空引用能在两门禁全绿时长期存活；
更坑的是 `evals/test-scenarios.yaml` **真实存在**却是 25 条行为场景表——按注释找会落到一个
存在却完全无关的文件上。Q9 就是补这一维。

判据（`comment_audit.py` 的 `analyse_referenced_paths`）：

1. 只扫**仓内真实顶级目录**：`src evals ops test docs rag templates contracts examples references`。
   `pybest/ _shared/ bridge/ scripts/ astro-best/` 是**历史或外部**引用（旧包名、母仓 skill、
   运行时产物），刻意不查——查了必然全红，塞进白名单只会掩盖新问题。
2. 路径从**仓根 / 本文件所在目录 / 其父目录**三处都解析不到 → 判 `referenced_path_missing`。
3. **docstring 的豁免按整段判，行内注释按行判**：失效标注常写在相邻行或段首
   （「该文件与 docs/plans/ 目录在本仓均不存在」与路径本身分行），按行判会把如实登记的注释误报。

### 三处刻意放过（放过的是「正确的注释」）

| 形态 | 例子 | 为什么放过 |
|---|---|---|
| 已如实标注失效 | 「原锚点 `git 6f00efeb^`〔本仓历史已无此对象〕」 | 逼人把实话从注释里删掉，是门禁的反作用 |
| 历史/外部前缀 | `pybest/tap/adql.py`、`_shared/skill-engine/*.md` | 旧包名与母仓 skill 路径，仓内本就不该存在 |
| 举例写法 | `ops/audit/x.py`、`a/b/c.json`、`*.py` | 是格式示例，不是引用 |

**代价（有意取舍）**：放过条件可被「加个词就绕过」。相比之下收紧的代价更大——
Q9 上线首跑就报 12 条，其中 3 条是门禁自己注释里的举例、6 条是我自己写的新注释，
若不放过它们，正确的做法会变成把失效登记删掉。因此**宁可漏，不可逼人说假话**。
该取舍也写进了下方「已知局限」。

净代码行口径与 `count_code_lines.py` 对齐（剔空行 / 纯注释行 / docstring 行），
因此**加注释不会顶到 400 行净代码预算**，两个门禁互不打架；豁免必须写进
`comment_audit.py` 的 `DENSITY_EXEMPT` 并附理由，无理由不得豁免（铁律 5 禁 fail-open）。

> `noqa` / `type: ignore` / 分隔线一类的指令注释**不计入** Q6/Q7 占比
> （与 Q4 剔 DIRECTIVE 同一条理由）：否则一堆 `# noqa: E402` 就能把两个指标
> 刷上去，指标随即失去意义。

### 注释写在哪：代码在左，注释在右

**语句级注释一律写在代码同一行的行尾**，只有**文件头、成组说明、分节横幅**
留在代码上方。判据很简单：**这条注释解释的是一行代码，还是一组代码？**

| 场景 | 位置 | 例 |
|---|---|---|
| 单个语句的解释（赋值 / 调用 / 配置项 / 字段 / 装饰器 / 类定义） | **行尾** | `count = 0  # 类属性：实例共享，改一处全体可见` |
| 文件整体说明 | 上方 docstring | 模块头六项（见下） |
| 成组逻辑、跨行表达式、分支块的理由 | 上方独立注释行 | 为什么要走 filter→sort 而不是反过来 |
| 多行参数列表的逐项说明 | 上方（不能挤进行尾） | `super()` 的两种形态对比 |

行尾注释的写法要求：

- 与代码之间**至少两个空格**（Q8 强制），**同一块内对齐到同一列**，让整段代码
  右侧形成一条可扫读的注释列；
- **不复述代码**：`x = 1  # 赋值` 这类零信息量注释是负资产，删掉；
- 过长时**改用上方注释块**：行尾注释超过约 40 个中文字（显示宽 80 列）就拆到
  上方，一行行尾里塞三句话等于没写；
- 行尾注释可以比代码行短，**不要求对齐到固定列宽**（ruff 的 `E501` 已忽略，
  但本标准仍按可读宽度自律，避免右边界参差）。

### 三个与工具链打架的例外（2026-10-03 实测踩坑）

1. **`import` 行的行尾注释必须恰好 2 个空格**，不能是 3 个。ruff 的 isort 规则
   （`I001`）会要求 import 块的行尾注释用两空格分隔，多一个空格就报整块
   「un-sorted or un-formatted」。Q8 只管「至少 2 个」，import 行取交集
   即恰好 2 个。
2. **多行 `from … import ( … )` 块内不要逐项写行尾注释**。括号里的行尾注释
   会让 isort 无法格式化整个块，直接触发 `I001`（实测 `src/auth/__init__.py`
   一次报了 16 行）。逐项说明请写在该 import 块的**上方注释块**里——这与
   「跨行参数列表的逐项说明归上方」是同一条规则，只是这里还多一层工具链约束。
3. **函数内的 `import` 加行尾注释会被 isort 折成括号块**，同样触发 `I001`。
   这类 import 保留上方注释即可（它本来就在函数体里，上方注释同样是"紧邻"）。

自检：改完 import 附近务必跑 `python -m ruff check <文件>`，`I001` 是本标准
最容易踩出来的回归。

> 另注：**下移注释时别把覆盖 import 块的中文说明一起挪走**。Q2
> （`import_group_no_chinese_note`）只认 import 块**相邻**的注释，挪走会立刻红。

Q6（有没有注释）与 Q7（注释写在哪）是**互补**两个指标：Q6 管覆盖率，Q7 管
位置正确性。只低一个通常说明注释摆错了位置——把一堆解释都堆在代码上方
而语句本身裸着，是最常见的错法。

### 文件头 docstring 必写的六项

1. **职责**：本文件解决什么问题，一句话讲清边界（不写"处理 X 数据"这种同义反复）；
2. **所属子系统**：`src/` / `evals/<exp>/` / `ops/` / `test/` 哪一层，上游是谁、下游是谁；
3. **对外接口**：导出的类/函数名 + 各自一句话，标注哪些是 seam（可被外部依赖的缝）；
4. **依赖与数据流**：输入从哪来、输出到哪去，跨进程还是内存内；
5. **关键契约与不变量**：不能被改坏的东西（错误语义、幂等性、离线回放约束、方言兼容）；
6. **陷阱与边界**：曾经踩过、或下一个人一定会踩的坑（写清"为什么"，不是"注意"）。

### 行内注释写什么（不写什么）

**写**：为什么这么写而不是显而易见的另一种；分支/边界的判定依据；魔数与其来源；
不变量的守恒点；失败语义（为什么这里抛而不是降级）；性能/离线的取舍；
调用顺序的隐含前提；正则/键名方言的来历。

**不写**：复述代码（`# 加一`、`# 返回结果`、`# 导入 json`）；`import` / `return` /
收尾括号 / 纯 `__all__` 列表这类样板；与函数名同义的废话（`fluff_docstring` 会拦）。

「每一行都有注释」按**非平凡语句**执行：任何有判断、取舍、转换、状态变更的语句都要有
对应说明，且优先写成**行尾注释**；样板行不写。理由是样板注释会稀释信号——真正的读者
要在一片 `# 导入 json` 里捞那条解释分支口径的注释。密度门禁正是按这个口径判的。

### 明确的豁免（这些不是漏，是有意的）

- **单条断言的测试方法**：`"""反: 空运行集 → tsc=0.0 (不虚报一致)。"""` 这种一行
  说明已经说清了断言意图，硬套「参数/返回/抛什么」三段式纯属注水，Q1 只要求
  「存在 + 含中文」即合规。库函数（非测试）的 docstring 不适用本豁免。
- **Q6 豁免小文件**：净代码行 < 15 的文件（多为空的 `__init__.py`）不判密度。
  但它们**仍然要有合格的模块头 docstring**（Q5 对小文件照判）。

### 写完必须自查

```powershell
python ops/audit/comment_audit.py    # 十一类计数必须全 0
python ops/audit/count_code_lines.py  # 净代码行不得因加注释而变化
```

注意 `duplicated_comment`（同一文件内 ≥12 字的注释重复 ≥3 次即违规）与
`verify_doc_consistency.py` 的 STRUCT 判据（docstring 里的**编号清单**条数必须与
文件内 `# ── N.` 顶层分节横幅的最大序号一致——所以文件头请用**字段名**而不是编号
清单，除非确实有对应分节横幅）。


## 已知局限（报告型工具）

1. `verify_no_code_loss.py` 按**代码 token 多重集**比对（对"多行折成一行"这类
   纯排版改动免疫，旧的行集口径会误报）。但仍有两类**语义误报**：
   - **删除重复定义**：HEAD 里同一常量定义两次、现行只留一份，token 会减少；
   - **docstring 位置变化**：字符串在 HEAD 不是 docstring、现行是，剔除规则不同。
   实测样本：`evals/ablation/harness/adapters.py`（HEAD 第 65/71 行 `DATA_TOOLS`
   重复定义 + 一行重复注释，现行已清理）报"丢失 token=21"，逐 token 复核**无真实
   丢失**。故该工具只作方向性参考，不入硬门禁。
2. `scan_code_smells.py` 的 `[MARKER]` 项会把**正则字面量里的** `TODO|FIXME`
   （如 `re.compile(r"\bTODO\b|\bFIXME\b")`）算成未决标记，属检出层过宽。
3. `version_scan.py` 会扫到自身 docstring 里的 `pybest-0.3.2.8`（B 类历史锚点），
   属自引用噪声。
4. `check_line_endings.py` 报出的 CRLF 若来自 `core.autocrlf=true` 的 checkout
   产物，应先用 `.gitattributes` 的 `eol` 钉死再归一；数据类资产必须写
   `-text -eol`（只写 `-text` 不会清 `eol`，快照仍会被归一成 LF —— 本轮踩过）。
5. **`comment_audit.py` Q9（`referenced_path_missing`）的三处放过面**（有意取舍，
   非缺陷）：注释里含「不存在/已删除/已随/已移除/已下线/示例/例如/形如」即整段（或整行）
   放过；`pybest/ _shared/ bridge/ scripts/ astro-best/` 等历史/外部前缀不扫；
   `x.py` / `a/b/c.json` / `*.py` 等举例形态不扫。
   代价是**可被「加个词就绕过」**。收紧的代价更大：Q9 上线首跑 12 条里，
   6 条是「如实登记失效锚点」的正确注释、3 条是门禁自身的举例——若不放行，
   唯一能变绿的做法就是把失效登记删掉，那与「禁 fail-open」背道而驰。
   守卫见 `test/unit/meta/test_audit_gate_contracts.py::TestReferencedPathCriterion`
   （四组断言分别钉住「真悬空必抓 / 已标注失效必放过 / 历史与举例必放过 / 真实存在必放过」，
   走 `analyse_referenced_paths` 真实实现而非复制判据）。
6. **`comment_audit.py` Q10（`line_alignment_low`）量不到的两类**：
   - **续行符行**（以 `\` 结尾）物理上无法加行尾注释，恒计入「缺」；
     全仓仅 `comment_audit.py` 自身两处，因该文件同时是本条判据的实现者。
   - **阈值是下限不是上限**：`ALIGN_FLOOR` 现为 **0.70**（整改期起步 0.45，
     本轮收尾全仓 0.9642、六个目录最低 0.933，已于达标当日上提）。它只保证「不倒退」——
     要继续提高就先补注释；盲调阈值只会让门禁变红，并不会让注释变好。
   守卫见 `TestLineAlignmentCriterion`（五组断言：全右注必达标 / 全无右注必判红 /
   样板行不进分母 / 数据行不进分母 / 阈值真的生效）。
7. **不要用自动化脚本判定「注水」**（实测失败）：按「行尾注释挂在纯字符串行上」抓注水，
   误报率极高 —— `broken/__init__.py` 的反证夹具、`test_equivalence.py` 的白名单样例、
   `report.py` 的表头串，挂的注释都解释了「为什么」而非复述内容。
   **注水与否是语义判断，只能人做**；脚本只适合抓「行尾注释与代码完全无关」这类极端。

## 历史已知状态复核

| 条目 | 入库时记载 | 复核实测 |
|---|---|---|
| `verify_crossrefs.py` | "README 一处树清单子串误报，非真缺陷" | **误诊**。真问题是 ROOT 错位导致 `open()` 崩溃（exit=1，整份体检跑不完）。已修；另修出 4 个潜伏缺陷：`_src_file` 未定义（NameError 从未触发）、spec 顶层结构假设过时、`<Class>.module` 键漏检（静默空转）、`check_symbol` 把模块路径误判为属性链 |
| `code_fingerprint.py` / `verify_no_code_loss.py` | "基线停留在 P0 重命名前，属基线过时" | **两个都是误诊，2026-10-02 复测定论**。`verify_no_code_loss` 的真因是 **ROOT 指向父仓**（已修）。`code_fingerprint` 的"新增未跟踪文件"既不是"ops/audit/ 未入库"（那 11 个文件现已全部受跟踪，`git ls-files ops/audit/` 返回 11 条），也不是基线过时 —— 真因是 `REPO` 硬编码父仓 + `git show HEAD:astro-best/<rel>` 拼路径，父仓已 `git rm --cached` 故恒 exit 128，251 个 `.py` 全落进"新增未跟踪"分支、`compared` 恒为 0、门禁空转且恒返回 0。已改为 `parents[2]` 相对定位；实测 `compared=251 code-changed=0` |
| `verify_import_graph.py` | 未记载 | 导入 `ops/` 层会**执行**路径调用入口（`skill_cli.py` / `cloud_modelscope/run.py` 是 runpy 转发 shim），实测打印 CLI 用法后 `SystemExit(0)`，后续检查全部不再执行。已按 README「ops/ 路径调用，零 import」的定义把扫描范围限定为 `src/rag/evals`，并新增"可导入层不得反向 import ops 层"判据 |
