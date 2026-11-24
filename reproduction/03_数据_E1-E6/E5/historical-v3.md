# E5 最佳可行确认性重跑方案 v3（能力边界核验版，2026-10-11）

## 决策摘要

本版综合并裁决 E5 整体重构路线图、实站采集/E5 执行方案、v2 最佳可行方案、实时闭环草案、隔离与答案键专项审计、历史批次证据，以及当前仓库的题库、12 臂配置、评分器、worker 和账本实现。**本版替代 v2，作为唯一前瞻执行协议；本轮只完善方案，不启动确认性单元。当前 E5 仍为 0/2,016，NO-GO。**

最优可行方案不是让 Harness 自带 shell 在“工作区沙箱”里执行，也不是把单独通过的 WSL worker 当成集成证据，而是：**专用 Harness profile + 持久 Cordis Host 插件限制模型工具目录 + 受限工具网关 + 独立 OS 身份运行 Harness + 无网 WSL/bubblewrap worker + 与 agent/插件/worker 物理隔离的 scorer/gold 身份 + 真实同 session tool loop。** 只有完整探针闭环、协议资产冻结、账本及评分门全部通过，才能执行固定的 56×12×3=2,016 个确认性逻辑单元。无法满足这些边界时停止并报告不可执行，不降级冒充 E2E。

| 项目 | v3 选择 |
|---|---|
| 研究问题 | 固定题集上 B3 相对 B2b 的任务级 E2E 成功差；A1–A6 删除组件比较；A2 对等长 sham 的长度控制 |
| 总预算 | 56 题 × 12 臂 × 3 次独立重复 = 2,016 格；不增加 pilot/add-back 单元 |
| 模型调用 | Harness 内置 OpenCode `opencode-go/deepseek-v4.1-flash`；既有真实文本路由 canary 使用旧版本 `0.2.0-rc.2`，本机当前 CLI 为 `0.2.1-alpha.1`，正式执行前需在隔离 profile 重验；revision/fingerprint/usage 不可得则记 null |
| agent 工具 | 仅冻结、臂专属的有限 E5 schema；拒绝任意 shell、命令、路径、URL、HTTP 与通用文件工具 |
| 安全执行 | 独立 Harness OS 账户、Host 插件限权、固定网关 argv、WSL/bwrap worker 无网、空输出挂载 |
| gold | scorer 与金标准置于 Harness OS 账户无权读取的独立 OS 身份/ACL；运行后才由 scorer 读取封存 trace |
| 题目类别 | 两位盲审+仲裁决定真实 `decision_class`；D14/C6/R24/S12 是历史目标，不是强制配额 |
| 统计 | 题目是配对/聚类单位，保留 3 次重复；预算不足以支撑的结论降级，不临时扩样 |
| 当前状态 | route 有限验证；工具隔离、OS 身份隔离、gold 隔离、协议冻结及 E2E 均未放行 |

## 1. 能力边界：已确认、文档支持、未验证

| 事项 | 证据与边界 | 对方案的影响 |
|---|---|---|
| 模型 route | 真实 Harness canary 证明 `opencode-go/deepseek-v4.1-flash` 可返回文本且 turn 完成；只证明路由，不证明 tool call 或实验表现 | 可复用作 0 单元 route gate；不当作样本 |
| Harness 版本 | 本轮读取的已安装 CLI 报告 `0.2.1-alpha.1`；本机安装包内含 Cordis Host 插件开发文档和 `@deepseek-ai/dsh-tools` 类型/说明 | 执行前重读 Harness 版本与插件 API；历史 canary 的 `0.2.0-rc.2` 只代表当时环境，不可冒充本轮版本 |
| 持久 Host 插件 | 内置指南描述 `plugin_manager` 的 `install_bundle` 路径、Host plugin `apply(ctx, config)`、tools 注入及 `agent/created` 生命周期；这是版本文档证据 | 候选实现机制；须先经 Harness 自身 `cordis_inspect_list/query` 核实服务/事件/签名，再装入隔离 profile |
| 工具限权 API | 内置 tools 文档描述 `agent.ctx.tools.restrict({allow:[...]})`、scoped context、工具 schema 查询和单调 `guard`；restriction 对全局继承工具生效，scope 内新注册工具仍可见 | 不可仅凭文档宣布安全通过；agent 创建时限权、生命周期 disposer、schema 与 guard 均须真实 session 验收 |
| 保留工具/PCT | 文档指出 PTC `run_code` 属保留执行通道，可能不受普通 `restrict` 名称 allowlist 控制 | 必须检查当前真实工具目录并证明 PTC/`run_code` 不暴露；无法禁用/证明则 NO-GO |
| 原生 shell 边界 | 既有 Harness `pwsh` 负探针观察到读取 cell 上级 canary；源 session 原始 trace 丢失，证据不可逐字节复核，但属于必须按失败处理的风险观察 | 原生 pwsh/bash/fs/web/MCP/workflow/subagent 均从 E5 agent 目录移除，不能靠 workspace-write 或配置文本声称隔离 |
| 动态插件沙箱 | 安装包 README 明确 Cordis 动态 VM 不是安全边界 | 使用持久 Host plugin bundle；插件本身按宿主代码审计并最小化权限 |
| WSL/bwrap worker | 独立 worker 测试已通过，但尚未接 Harness 工具回环；单测不能证明 Harness 到 worker 的链路 | 只作为 OS 隔离组件，必须由真实 Harness tool call 触发并留下绑定证据 |
| OS 文件权限 | Cordis restrict 约束的是工具可见性/调用，不会改变 Host 插件所属进程的 Windows 令牌或本地文件 ACL | Harness、Host plugin、agent 运行在专用低权限账户；gold/scorer/repo 放在该账户无权读取的位置，并用真实进程负探针验证 |

OpenCode 路由可用、Cordis 文档存在、单独 worker 测试通过，三者相加仍不等于 E2E 放行。Harness 专用插件尚未安装验收；当前没有通过工具目录或金标准访问负测的证据。

### Harness 内置 OpenCode / DeepSeek-V4.1-Flash 可行性裁定

**结论：可以把 Harness 内置 OpenCode provider 的 `opencode-go / deepseek-v4.1-flash` 作为 E5 的模型决策层，但当前证据只到真实文本 route smoke。** 已安装 Harness 0.2.0-rc.2 的显式 provider overlay canary 返回文本并以 completed turn 结束；它证明的是 Harness→OpenCode provider→模型别名路由，不证明真实工具调用、E5 tool loop、精确模型 revision 或任何实验效果。不要绕过 Harness 直接请求 OpenCode API，也不要使用默认 `deepseek-official` 凭据失败来推断内置 OpenCode 不可用。

执行时每格用一个全新 Harness session，使用独立 `e5-live` profile 与显式冻结的 provider/model overlay；记录 Harness 版本、profile/patch/plugin hash、provider/model alias、session id、原始事件和可得的 usage/revision。credential 只留在 Harness 环境，日志与 worker 不记录密钥。缺少 revision、token、cost 时写 null；不做别名之外的 checkpoint 声明。确认性矩阵中 provider/model route 变更或 session metadata 与冻结 profile 不匹配时立即停批，不自动回退另一个 provider。

阶段 B 必须再用独立非题库 fixture 做一次真实 function/tool-call canary：模型产生带 ID 的原始 tool_call，已核验的 E5 工具在同一 session 返回 tool_result，随后同一 session 给出 final；保存完整 Harness event trace。当前只有文本 route smoke，`G4.2` tool-call 能力仍未验证，不能把该 canary 计为 E5 单元。

### 本轮门禁代码修复与证据

| 缺陷 | 修复 | 当前验证 |
|---|---|---|
| `E5_SCRATCH_ROOT` override 未被根目录函数自动检查，调用方可能漏掉断言 | `scratch_root()` 对默认/覆盖根统一 resolve+assert；batch ID 禁绝路径分隔符 | 隔离门定向回归通过 |
| 同名 `--force` 会递归删除旧批次；stage 失败可能留下半批 | 旧批次禁止覆盖，源文件/ID/泄漏词在建批前预检，复制失败回滚；批次须用新 ID | 定向回归覆盖旧批保留、非法ID和泄漏输入 |
| 收尾快照只记录 mtime，mtime 可回拨；`end_write` 能重设基线/闭合后重开 | 输出快照改内容 SHA-256+长度；close 需存在匹配 owner token 的写会话；快照仅创建一次，封存批次不可重开 | 定向回归证明恢复 mtime 后改内容仍被识别 |
| audit 对畸形 cells/非 object JSON、链接容易异常退出或漏检 | 结构化校验、符号链接/非 JSON 文件拒绝、畸形证据变成明确审计问题；单写者 mtime 降为异常线索而非身份证明 | 定向回归覆盖畸形清单/JSON 与内容改写 |
| RunJournal 建仓前才检查路径、seal 与 record 无互斥、最终目录留矛盾 incomplete 状态；Windows junction/reparse point 未覆盖；进程间写入锁需实测 | 路径先验证再创建；拒绝 symlink/junction/reparse tree；跨进程文件锁串行 record/seal；封存后禁止追加；崩溃留下不可复用的 INCOMPLETE；验证路径、数量、嵌入键和每个 hash | 2026-10-12 targeted ledger/isolation：32 writer 各写唯一格 32/32 成功并封存核验；32 writer 同格争抢 1 成功、31 显式拒绝；进程崩溃留 INCOMPLETE；目录 junction 与 sealed-run alias 拒绝。全套非 live 测试结果见过程包；Harness receipt 集成仍待门禁 |
| worker 以未挂载 `/sys/class/net` 的空列表当无网、只对 TEST-NET 超时 | 改验 net namespace inode、默认路由、`/proc/net/dev` 外部接口，并以隔离前可达的 WSL loopback sentinel 做正/负对照 | 独立 WSL/bwrap gate 11 项通过；未证明 Harness→worker 链 |

上述通过只覆盖代码级与独立 OS worker 门；不放行 Harness catalog/PTC、专用 Windows 账户 ACL、Gold ACL 或真实同 session 集成。

## 2. 研究矩阵、臂定义、估计量

### 固定矩阵

- 12 臂：B0、B1、B2a、B2b、B3、A1–A6、sham。
- 56 个冻结任务；每个 task×arm 三个互相独立的新 Harness session；共 2,016 个逻辑格。每逻辑格只允许一个首次实验 attempt；重试按 append-only attempt 另列。
- 以冻结随机种子按盲审后的真实类别分层，在任务内平衡并交错 arm/replicate；先串行。只有隔离、唯一性/恢复及受控并发门全过才允许有界并行。
- Gate fixture 与题库完全分离且不计格；不加 24 格 pilot。旧 hypotheses 中 add-back/+150 方案不属于本协议。

### 处理一致性

每臂固定 provider/model 路由、公开数据快照、后端版本、OS 边界、超时、token 上限及可观察到的解码参数。机器可读差异清单要证明每臂只改变预设组件。B2a 可用受限原始协议 schema；B2b/B3/A1–A6 使用冻结七个原子领域工具；臂间 schema 可因处理定义不同，但所有工具必须进入同一个 gateway/worker 与同一快照。任何臂都不得取得通用 shell、任意路径、任意 URL/HTTP、任意程序执行或答案键权限。

所有臂固定保留硬工具 allowlist、OS worker、安全拒绝、gold 隔离、独立 scorer、trace 和账本。A1 只能删除软参数验证；A3 只能删除模型可见拒绝/路由指导；A4 只能删除模型可见 provenance 指导；A5 只能删除模型自检提示；A6 只能改变模型可见输出 envelope。上述处理不得改变硬安全边界、后台测量、快照或评分。报告明确这些组件不可作为消融变量。

### 预注册估计量

- 主要估计量：56 个任务等权的 B3−B2b 任务级 E2E 成功率差。
- A1–A6 对 B3 构成一个预先声明的 Holm 校正家族；A2 对 sham 是单独的长度控制比较；B0/B1/B2a 为描述性基线。
- 同一任务 3 次重复先求 arm 内成功比例，再形成 task 内配对差。报告等权平均、按任务聚类 bootstrap 95% CI 和逐任务结果；混合效应模型为预设敏感性分析。不得把 2,016 格当独立样本。
- 开跑前以固定 56 任务、3 重复、多组任务内相关参数完成功效/MDE 模拟；模拟不能更改预算或门槛。若功效不足，结论限定为区间估计/不确定性，不追加样本仍称原确认性试验。
- E2E 成功按冻结 rubric 逐门判定：意图/路由、工具必要性、参数、真实 tool_result 与 session 绑定、字段/数据、最终事实/来源/安全。工具错误、超时、拒答、格式错按冻结规则进入终态，不能通过成功重试覆盖。澄清/拒绝题按预设 rubric，不强迫工具调用。
- 主报告同时给 task 等权总体和按真实类别的分层结果。若分类支持度或评审一致性不足，不做四类宏平均强推断，不按 ID 前缀补配额。

## 3. 题库、类别、gold 和盲审冻结

当前 `items.yaml` 类别统计与旧计划 D14/C6/R24/S12 不一致；ID 前缀不能替代语义类别。冻结前必须：

1. 只用公开题面与冻结公开快照，独立重建 `decision_class`、工具必要性、可判定 gold 与来源；禁止从 SUT 源码/期望答案倒推 gold。
2. 两名不知条件的审核者独立标注类别、拒绝/澄清边界、工具调用要求、答案/rubric 和来源；第三人按冻结规则仲裁。保存双份原始标注、理由、仲裁和 κ/α。目标 ≥0.80；低于目标则修订 rubric 后重盲标，不以仲裁替代一致性。
3. D14/C6/R24/S12 作为历史目标核对，不是硬配额。对 R26/R32 snapshot/sort/source contract 及全部安全项逐条审阅；题证不支持转类则保留真实类别，调整宏平均与主张，不改 ID 或强行挪类。
4. 将模型可读 public tasks 与 scorer-only gold/rubric 分开。模型、Harness 主进程、Host plugin 和 worker 均无 scorer/gold ACL。公开提示不含类别、expected tools、gold ref 或内部路径。静态扫描仅为辅助，必须由 ACL/独立账户加真实 Harness 负探针证明。
5. 冻结 public task、prompt、类别映射、arm/system、工具 schema、数据快照、scorer/gold、随机化、分析计划及执行代码 hashes。任意修改必须生成新 protocol 版本，不能在同一 run 中悄然替换。

## 4. 最佳可行执行架构

每逻辑格用新 session、随机 opaque cell ID。受限调度器独占真实 task/arm/replicate 到 opaque ID 的映射。目标链为：

`public opaque prompt → 当前 Harness agent 的真实模型 tool_call → 单一专用 Host E5 gateway → 固定 WSL/bwrap worker → tool_result 返回同一 Harness session → final`。

receipt 必须绑定 protocol/run/cell/session/arm/replicate/attempt、prompt/schema/snapshot hash 和 tool-call ID。链路缺项时不得宣称有效 E2E；根据已冻结缺失规则计终态失败或整批基础设施中断。

### Harness Profile 与 Cordis Host 插件

- 创建独立 `e5-live` profile，并通过内置 `plugin_manager` 安装本地持久 bundle；禁止手改 profile 的 `package.json`/`cordis.patch.yml`、禁止动态插件 VM 作为安全边界、禁止触碰默认 profile。
- 安装前用 Harness 自身 `cordis_inspect_list` 和针对性 `cordis_inspect_query` 核实 `agent/created`、`ctx.tools.restrict`、`ctx.tools.guard`、schema 查询、`plugin_manager` 的确切版本/API。按该版本签名实现，不复制 OpenCode 上游假设。
- 在 `{agent}` 创建事件中对 `agent.ctx` 施加 allowlist 和同步单调 guard；逐 agent 保存并清理 scope disposer；对全局工具只允许预注册 E5 名称。拒绝未知工具、缺字段参数、超范围参数、取消信号、重复/过期 receipt。工具 scope 内新增注册也需逐项检查。
- 真实 catalog/schema 必须精确等于该臂允许的有限 E5 schema。确认 pwsh/bash/fs/fs_search/web/MCP/jobs/workflow/subagent/fork 与未登记工具不显示、不调用且无副作用。特别确认保留 PTC `run_code`/其它代码执行入口不可用；普通 allowlist 若无法覆盖保留通道，就禁用该通道或 NO-GO。
- 单独 profile 的工具补丁/插件安装可能影响该 profile 全部会话；任何变更后重新采集 catalog/schema hash 并重跑 G2 探针。provider credential 仅留在 Harness 进程环境，不传入 agent-visible 配置、插件日志或 worker。

### OS 身份、Gateway 与 worker

- Harness 与 Host plugin 以专用低权限 Windows 账户运行。该账户只可读专用 profile、公开 task、必要快照与 E5 gateway；无权读 `items.yaml` 内 gold、scorer、分析代码、仓库私有目录、历史 trace 或其他用户数据。用真实 Harness 进程 token/身份做 read-denied 正负探针；管理员/当前交互用户下通过不能替代此门。
- 持久 Host plugin 是受信任宿主代码而非沙箱。审查源代码/依赖/SBOM，禁止任意文件 API、子进程 shell 字符串、任意网络、日志 prompt/gold/credential。它只验证有限 schema 并将规范化 JSON 请求写入唯一 gateway stdin/IPC；固定绝对 binary 和 argv 数组，不从模型输入构造可执行路径或参数。Gateway 自身不得能访问 scorer/gold。
- Worker 只挂载该 cell 的公开输入、冻结只读快照和经过审查的只读工具实现；仅一个预先建空目录可写。使用 `bwrap --unshare-all`/WSL 网络命名空间，无外部接口/路由；`--clearenv`，不挂载 repo<SANDBOX_HOME>/credentials/gold/scorer/history；限制 CPU、内存、时间、输出大小和并发。
- 只允许有限的领域查询 API/固定 operation enum；请求大小、字段、排序、分页均有界。网络不得由 worker 访问。provider 网络请求由 Harness 主进程执行，与 worker 能力边界分离。
- worker 无网检查不得依赖连接 TEST-NET 超时这一弱信号；验证隔离 net namespace、路由/接口状态，并在 gate fixture 外设置受控可达端点做正反控制。允许隔离 namespace 内 loopback 存在，但须证明其无法到达宿主/外网；以可复现的 OS 事实和负向连接记录放行。

### 答案键与评分隔离

scorer/gold 使用与 Harness 专用账户不同的 Windows 身份与 ACL；不能仅依赖模型 tool catalog。先运行 Harness/provider 与工具链后，用实际 Harness/Host 插件/worker 进程读金标准、scorer、repo、sibling 和父目录 canary，逐项必须拒绝并保留 OS 错误/审计；公开快照必须读成功。所有 agent session 终结、事件导出并原子封存后，独立 scorer 才读取 traces 与 gold。评分结果和臂映射继续封存至人工盲评锁定。

## 5. 账本、故障恢复、评分和统计

- `run_id` 与每逻辑格唯一键一次创建；DB 唯一约束或 exclusive create，禁止 upsert/覆盖。attempt 只追加，含 `retry_of`、失败类别、调用是否被 Harness 接受及 session 是否启动。
- 模型拒答、provider/session 接收后的超时/错误、工具失败、格式错是该 attempt 的终态，不以成功重试覆盖。只有 prompt 未被 Harness 接收且 session 未启动的基础设施前置失败可按冻结规则重试；全部 attempt 永久保留。
- 同格双写、重复 receipt、worker 崩溃/超时、Harness 崩溃/中断、日志部分写入、进程恢复、封存损坏均须用非题库 fixture 演练。若共享基础设施故障可能影响多个格则停整批并封存 INCOMPLETE；修复后新 `run_id` 完整重跑，不拼接批次或挑成功格。
- 先串行跑。32 writer 压测、锁竞争、崩溃恢复与无共享状态证据通过后，可限定并发数；每 writer 独立 session/cell/output，不共享工作目录或临时可写文件。
- 独立 scorer 对 100% 单元逐门评分并记录数值、fail code 和证据事件。trace 全部 seal 后方可读 scorer-only gold。人工盲评预先按类别/状态抽样不少于 20%，另纳入全部安全红线、边界项和机器不确定项；至少两位评审不知道臂。报告初始 κ/α、分层一致性、仲裁前后和理由。κ/α<0.80 则按冻结规则降级结论，不得观察差异后改 rubric。
- 运行前完成统计代码 dry-run、功效/MDE 模拟、缺失/失败处理和多重比较核验；分析脚本不得访问未封存的中间臂标签。结果按预注册估计量完整报告，包括所有 56 题和 12 臂。

## 6. 分阶段重跑、放行门与当前状态

### 阶段 A：协议冻结（0 实验格）
盲审 56 题、gold、类别、评分 rubric；修订 arm 差异与七个工具 schema；核验快照来源/完整性；拆 public/scorer-only；锁定随机化、统计、功效、人工抽评、失败重试与证据导出方案。完成 hash 和受限访问审查。

### 阶段 B：Harness 集成/安全门（0 实验格）
用独立非题库 fixture 验证 route、真实模型 tool-call canary、Host plugin 安装、真实 agent 工具目录、同 session tool loop、工具拒绝、保留执行入口不可用、专用 OS 账户 ACL、gold 负测、worker network/file/process 隔离、账本/恢复/并发。每项保留成功与失败原始证据。此阶段不调用题库，不产生 E5 样本。

### 阶段 C：确认性重跑（2,016 逻辑格）
只有所有门 PASS、protocol sealed、目录和二进制 hash 冻结后才开始。默认串行或门限允许的有界并行；全矩阵可对账和复算后原子 seal。

| 门 | 通过条件 | 当前判定 |
|---|---|---|
| G4.1 provider route | Harness 内置 `opencode-go/deepseek-v4.1-flash` 的真实 route canary；能力范围仅限文本路由 | 有限 PASS；不是工具闭环 |
| G4.2 model tool call | 非题库 fixture 中产生真实 tool_call→同 session tool_result→final，保留原始 session trace | 未验证，阻断 |
| G2.1 工具目录/同 session | 实际 E5 agent schema 精确匹配 allowlist，原生危险工具/PTC 不可见；正向 tool loop 和负向调用均有同 session 事件 | FAIL/未集成，阻断 |
| G2.2 public 输入扫描 | public prompt、日志、挂载和工具 schema 不含类别/gold/内部路径 | 待执行 |
| G2.3 OS/gold ACL | 专用 Harness 身份；Harness 主进程/插件/worker 对 gold/scorer/repo/sibling/父路径拒绝 | 未验证，阻断 |
| G2.4 Worker OS 沙箱 | 无网 namespace、无默认路由、只读输入、仅 cell 输出可写；经 Harness gateway 集成 | 独立 WSL/bwrap 11 项 PASS；Harness E2E 未验证 |
| G3 ledger/seal | unique/create-once、append-only、故障恢复、32 writer/锁测试与真实 session receipt 集成通过 | 2026-10-12 targeted isolation+sealed-run：41 passed, 1 skipped；32 writer 两种矩阵、crash→INCOMPLETE、junction/reparse 拒绝均有测试证据。1 项报告文件 symlink 测试因主机权限跳过。真实 Harness receipt 与完整系统故障注入仍未过 |
| G5 题目/协议 | 56 项双盲类别/gold/rubric、快照、arm/tool hashes 与 prereg 冻结 | 未冻结 |
| G6 评分/统计 | scorer 盲评流程、一致性、功效/MDE、分析脚本与失败规则通过审查 | 未放行 |
| G8 覆盖/封存 | 矩阵 2,016 格、attempt、trace、hash 对账且无覆盖/静默丢失 | 未启动 |
| G9 可复算/污染 | 独立复算、盲评、ACL 与污染审计、归档清单通过 | 未放行 |

任一阻断门失败为 NO-GO。工具逃逸、Gold 可读、prompt/条件泄漏、tool-call 链断、重复覆盖、静默丢行或协议 hash 漂移，立即停止并封存 `INCOMPLETE`/`INVALID`。修复后升级 protocol 并以新 `run_id` 重跑完整矩阵；不在已污染批次续跑。

### 明确重跑总量

- Gate 探针、route smoke、tool-call canary、工具目录核验、OS 负探针、worker 集成、账本/恢复演练：**0 个 E5 实验单元**，但都必须真实执行并交付日志。
- 确认性 E5：全部 56×12×3，即 **2,016 个逻辑格**。旧 scripted、hybrid、expression-only、replay、历史污染或来源不明数据不进入该分母。
- 若任务 rubric 或臂定义发生冻结后实质更改，版本升级并重新完整跑 2,016 格；不得只补失败任务/臂。

## 7. 全部过程产物与复现包

每格交付：唯一 manifest/receipt、opaque ID、run/cell/session/arm/replicate/attempt、时间与状态；原始 Harness event JSONL 和源 session hash；assistant 内容、模型原始 tool_call、工具返回、错误/重试/turn end；路由/provider/model 与 Harness/OpenCode/plugin 版本；不可得的 revision/token/cost 明确为 null；schema/catalog hash；固定 gateway binary/argv hash；worker 输入/输出 hash、stdout/stderr/exit code、mount/network 审计；cell output tree hash；逐门评分及失败理由。secret 不进 trace；内部原始日志只读保存，外发版本明确记录脱敏策略与 hash。

轨迹封存不能只把这些路径写进 README 或报告。RunJournal v2 的 `artifacts/` 使用 `record_artifact(relative_path, bytes)` create-once 写入，`SEALED.json` 对全部附件路径/字节写 SHA-256，verify 检查附件路径、全集与哈希；v1 sealed run 仍可读。具体目录、字段、event/call/result 配对规则、失败 attempt 保存和第三方复算步骤以 `docs/E5-NEW-WINDOW-EXECUTION-PLAN-2026-10-12.md` 的“Harness 调用轨迹与复现性契约”为准。该接口目前仅提供受 hash 保护的附件存储；Harness exporter、cell trace 的 `artifact_paths` 引用一致性、调用配对和 2,016 格跨文件 verifier 仍是 G4.2/G8 阻断工作，完成并验收前不得启动矩阵。

事件保存边界：留 Harness 导出的实际事件顺序、可见 prompt/assistant 文本、tool_call 参数与 tool_result/error、event/session/turn/call ID、provider request ID、模型有效配置和版本；不保存 credential、Authorization/API key、hidden chain-of-thought 或与任务无关的私有工作区文本。模型 revision/seed 若 provider 不披露必须标 null；因此目标是审计和复算证据链，不承诺非确定模型逐字节复答。

每 run 交付：sealed protocol/prereg、题目/arm/schema/snapshot/gold/scorer/分析脚本 hashes；盲审原始双标、仲裁、κ/α；完整 2,016 coverage 和 append-only attempts；所有正向/负向 gate 记录；Harness 插件源代码/依赖清单/SBOM/安装收据；OS 账户 ACL/令牌证据；worker 隔离参数与正反网络控制；账本故障/恢复/并发日志；统计模拟源/日志；评分与盲评原始表；分析代码/环境/完整日志、CSV/JSON/图表源和报告；ZIP 文件清单、每文件 SHA-256、归档总体 SHA-256 与校验日志。包中保留成功、失败、阻断、未启动及恢复事件，不仅打包最终报告。

## 8. 历史口径、冲突处理与范围限制

历史 `all-systems-rebuild` 990 条由 ScriptedLLM 规划器决策；约 2,010 个 indep3 是表达阶段会话；旧 scripted、hybrid、capture/replay、expression-only、疑似多写者批次分层登记为各自证据，不填充新 E2E 分母。旧 `capture_live` 缺失不补造。此前 pwsh escape 风险保留为失败证据，后续 ACL 初始化失败只标 `not_started/indeterminate`，不能写成拒绝通过。

v3 取代此前实时闭环草案和 v2 中“API 未证实”的旧描述：当前安装包文档确实描述 Cordis 的持久 Host plugin、agent-scoped tools restriction 与 guard；但**实装、PTC 隐藏、隔离和实际拒绝依然待验收**。任何报告不得把内置文档支持写成实测通过，也不得把 worker 独立测试写成 Harness 集成通过。本文只定义可执行条件和证据，不宣称 gate 已完成或 E5 已有新结果。

## 9. 核查范围

本版对照了计划目录中的 E5 总路线、执行方案、v2、Harness 实时闭环草案、门禁检查表、源码专项复核、投稿待办与过程审计；仓库中 E5 live/revised/prereg/isolation/maintext/defect 文档、题库、hypotheses、12 臂配置、评分器、账本、隔离 worker、隔离/账本定向测试，以及 Harness 0.2.0-rc.2 安装包内 Cordis 插件/工具文档。2026-10-12 最终完整非 live `evals/ablation/tests` 为 139 passed、1 skipped（249.41s，exit 0）；附件封存定向测试 14 passed、1 skipped（exit 0）。测试通过仅说明被测模块，不表示 Harness 系统级或真实 E2E 证据已通过。

## 2026-10-12 可行性复核与执行状态

- 用户要求暂不运行 E5。E5 确认性矩阵保持 0/2,016；以下只是本地门禁代码测试、静态/文档复核和过程审计，不会创建 E5 cell、调用模型或把测试 fixture 计入实验。
- E5 最优可行路线维持：Harness 内置 `opencode-go/deepseek-v4.1-flash` 仅作为候选决策模型；Host 插件 + 最小工具 catalog + 专用 OS 身份/ACL + 固定参数 gateway + 无网 WSL/bwrap worker + 独立 scorer/gold 身份 + 同 session tool loop 缺一不可。OpenCode 文本 route canary 不能替代工具闭环。
- 目前没有可供本 Codex 会话调用的 Harness `plugin_manager` 工具；Harness 插件开发指南要求通过 `plugin_manager install_bundle` 管理安装。因此只允许在仓内起草/离线校验插件与权限策略，不能用 shell/CLI 直接改 Harness profile。G2.1/G2.3/G2.4 E2E/G4.2 继续阻断，直到真实 Harness manager 安装收据、当前工具 catalog、危险工具/PTC 拒绝、ACL 读拒绝和正向同 session worker 闭环全部封存。
- 账本实现现已对 Windows reparse point/junction 做 fail-closed 检查：检测发生在 resolve 前，并覆盖根目录自身及祖先；同时用跨进程锁保护 append/seal。32-process unique/duplicate 矩阵及 abrupt crash 负测通过。此结果验证的是账本模块，不是 Harness 收据的端到端生成、断电恢复或并行模型调用稳定性。
- Harness 会话审计覆盖主项目与两个 E5 canary 路径下 1,961 份磁盘可见 v4 事件日志；其中 1,913 份提到 E2/E5，30 个会话包含 E5 决策文件写调用（395 次）。缓存 2,054 条中 1,961 条与项目 cwd 对齐；未导出原始 prompt/response。缓存不含归档标志，所以不能证明已删除或不可见的历史归档也在扫描中。审计 JSON 保留 session ID、模型/沙箱元数据、事件配对计数和压缩文件 hash，敏感正文不导出。
- 在全套非 live 测试结论落盘后，须再按 GATE-STATUS 与检查表逐项核对状态、证据路径和版本；仍有任一阻断即维持 NO-GO，不启动任何确认性单元。

### 实验可行性与验证门（零实验单元）

| 阶段 | 输入与验证 | 当前结论 | 放行后可做什么 |
|---|---|---|---|
| F0 代码/协议静态核验 | 配置、题集、臂、Gold/Scorer 边界、导入图、hash 与版本一致性；不访问模型 | 部分代码门已通过；类别/盲审、G7 统计预登记仍未冻结 | 修订题目裁决与统计协议，不执行模型任务 |
| F1 隔离账本压力 | 单元/进程唯一写入、重复键拒绝、crash→INCOMPLETE、根/祖先 junction/reparse 拒绝、原始 artifact 附件 create-once/hash/tamper/partial-crash seal 负测 | 最终附件封存定向测试 14 passed/1 skipped；全套非 live suite 139 passed/1 skipped（249.41s，exit 0）；32 进程唯一/重复竞争通过 | 只允许评估运行器稳定性，不推断模型表现或 Harness 端到端可用 |
| F2 Harness 工具边界 | 通过 Harness `plugin_manager` 安装隔离 profile；导出当前 agent catalog/schema；证明危险工具、PTC `run_code`、shell/fs/web/MCP/subagent 不可见/不可调用且无副作用 | 当前 NO-GO：本 Codex 会话没有 `plugin_manager` 管理能力，未产生安装收据；禁止 CLI/shell 改 profile | 取得真实 Harness 管理通道后再验证，不绕过 Harness 管理约束 |
| F3 主机身份与 Gold ACL | 专用低权限 Windows 身份运行实际 Harness/Host plugin；公开输入成功读取，Gold/Scorer/repo/sibling/父级 canary 明确拒绝 | 未验证，阻断 | 只证明进程令牌和 ACL 边界，不开始 E5 题目 |
| F4 worker 集成闭环 | 独立非题库 fixture 经真实同 session tool_call→固定 gateway→WSL/bwrap worker→tool_result→final；记录 OS 网络/挂载与完整事件证据 | WSL/bwrap 独立 11 项通过，但 Harness E2E 未验证，阻断 | 只跑零计分集成 canary；绝不从 56 题中抽取或新增 pilot cell |
| F5 统计/评分预登记 | 显式 decision_class、盲审 rubric/Gold、双盲/仲裁、一致性方案、以固定 2,016 预算模拟任务聚类效应与区间宽度；报告可识别的最小效应范围 | 未完成，阻断；不得把 2,016 格当 2,016 个独立样本 | 只能冻结方案与分析代码，不能看分组结果后改口径 |
| F6 确认性执行 | F0–F5 全部通过、协议及代码/题集/工具 schema hash 冻结后，56×12×3 每格一个新 session | 用户要求暂不运行；现为 0/2,016，NO-GO | 只有用户后续要求执行且放行证据齐全后，按固定矩阵启动；不扩增单元 |

**可行性结论：技术路线有条件可行，但当前整体不可执行。** 已证明的只是文本 route 历史 canary、独立 worker 与账本模块的局部能力；最关键的 Harness 管理安装、工具目录与保留 PTC 约束、OS 身份/Gold ACL、真实同 session worker 链、任务类别/双盲统计仍缺证。不得把单项 PASS 合并成端到端 PASS。模型调用下限是 2,016 次新 session；重试按同一逻辑格的 append-only attempt 记账，不增加逻辑单元，但运行预算/总时长需在零单元 canary 和统计冻结后另行估算。初次确认性运行建议串行，只有运行器与 Harness 故障矩阵额外证明无共享状态后才可考虑限并发；32 进程账本测试不证明 32 路模型调用安全。

### 2026-10-12 最终路径门与 worker 证据补充

- 最新独立交接执行文件：`docs/E5-NEW-WINDOW-EXECUTION-PLAN-2026-10-12.md`，提供阶段 0–8 的步骤、PowerShell 操作、输入/输出、通过/停止标准与当前阻断；新窗口从阶段 0 开始。本协议是研究设计 SSOT，交接文件是执行入口。
- 本轮额外修复 resolve 前路径检查：stage prompt source 根/祖先、protocol freeze/verify 路径、OS sandbox `--out-dir`、sealed-run 根路径及祖先均拒绝 reparse/junction；OS sandbox 审计命令直接运行 import 路径和 Windows stderr 解码问题也已修复。
- 最新 WSL/bwrap fresh evidence `os-sandbox-v4-20261012-02` 11/11 PASS、exit 0；父子 network namespace 不同，worker 仅 loopback、无默认路由，host sentinel 正控隔离前可达而隔离后不可达。此处仍只标为独立 worker 组件证据；Harness gateway→worker 同 session 集成、Windows Gold ACL 未验。
- 唯一 skipped 测试是 Windows 权限令牌无法创建文件 symlink（WinError 1314）；目录 junction/reparse 正反用例通过。跳过不解释为 symlink 测试 PASS，保持该特定平台门为限制。
- 完整分阶段命令、过程路径及下一步 API/OS 身份缺口见上述交接文件与过程证据包；E5 保持 0/2,016 NO-GO，未调用模型或创建实验单元。
