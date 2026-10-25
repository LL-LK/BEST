"""Create a new prospective protocol; never overwrite historical v3 evidence."""
from pathlib import Path
import hashlib
import json
import re

PLAN = Path(r"<USER_HOME>\Desktop\论文\e2和e5重构计划")
REPO = Path(r"<REPO_ROOT>")
OUT = Path(__file__).parent
source = PLAN / "E5_最佳可行确认性重跑方案_v3_能力边界核验_2026-10-11.md"
raw = source.read_bytes()
text = raw.decode("utf-8-sig")
replacements = {
    "# E5 最佳可行确认性重跑方案 v3（能力边界核验版，2026-10-11）": "# E5 确认性执行协议 v4（Harness 0.2.0-rc.2 / Claude Science 模式，2026-10-12）",
    "**本版替代 v2，作为唯一前瞻执行协议；本轮只完善方案，不启动确认性单元。当前 E5 仍为 0/2,016，NO-GO。**": "**本版依用户2026-10-12的新指令替代v3，授权在全部技术门通过后执行固定确认性矩阵。开跑前人工双标、仲裁和一致性要求已移除，人工审核留到后续。当前是否可执行以本轮实际门禁证据为准。**",
    "Harness 内置 OpenCode `opencode-go/deepseek-v4.1-flash`；既有真实文本路由 canary 使用旧版本 `0.2.0-rc.2`，本机当前 CLI 为 `0.2.1-alpha.1`，正式执行前需在隔离 profile 重验；revision/fingerprint/usage 不可得则记 null": "固定调用安装目录内 Harness CLI `0.2.0-rc.2`，agent preset 为 `claude-science`；模型路由固定 `opencode-go/deepseek-v4.1-flash`。PATH 上全局 `0.2.1-alpha.1` 不参与本实验。revision/fingerprint/usage 不可得则记 null",
    "两位盲审+仲裁决定真实 `decision_class`；D14/C6/R24/S12 是历史目标，不是强制配额": "基于公开题面与公开快照逐项确定并冻结 `decision_class`；D14/C6/R24/S12 是历史目标，不是强制配额。人工审核留到后续",
    "题目类别是由双盲审查决定": "题目类别按公开题面和快照证据冻结",
    "以冻结随机种子按盲审后的真实类别分层": "以冻结随机种子按冻结的真实类别分层",
    "## 3. 题库、类别、gold 和盲审冻结": "## 3. 题库、类别、gold 与技术冻结",
    "2. 两名不知条件的审核者独立标注类别、拒绝/澄清边界、工具调用要求、答案/rubric 和来源；第三人按冻结规则仲裁。保存双份原始标注、理由、仲裁和 κ/α。目标 ≥0.80；低于目标则修订 rubric 后重盲标，不以仲裁替代一致性。": "2. 逐项保存类别、拒绝/澄清边界、工具调用要求、答案/rubric 与公开来源；无法从公开证据确定的项目必须明确记录并在技术冻结前解决。人工审核留到后续，不作为本次开跑的前置门。",
    "评分结果和臂映射继续封存至人工盲评锁定。": "评分结果和臂映射与封存trace一起留存，供后续人工审核。",
    "- 独立 scorer 对 100% 单元逐门评分并记录数值、fail code 和证据事件。trace 全部 seal 后方可读 scorer-only gold。人工盲评预先按类别/状态抽样不少于 20%，另纳入全部安全红线、边界项和机器不确定项；至少两位评审不知道臂。报告初始 κ/α、分层一致性、仲裁前后和理由。κ/α<0.80 则按冻结规则降级结论，不得观察差异后改 rubric。": "- 独立 scorer 对100%单元逐门评分并记录数值、fail code和证据事件；trace全部seal后方可读scorer-only gold。原始评分、失败、安全边界项和机器不确定项完整留存，供后续人工审核。审核尚未完成时明确标记pending；不得据此宣布论文结论已经过人工验收，也不得观察差异后改rubric。",
    "盲审 56 题、gold、类别、评分 rubric": "技术核验56题、gold、类别、评分rubric",
    "功效、人工抽评、失败重试": "功效、后续人工审核记录、失败重试",
    "56 项双盲类别/gold/rubric、快照、arm/tool hashes 与 prereg 冻结": "56项类别/gold/rubric、快照、arm/tool hashes与prereg技术冻结；后续人工审核不阻断开跑",
    "scorer 盲评流程、一致性、功效/MDE、分析脚本与失败规则通过审查": "scorer、功效/MDE、分析脚本与失败规则完成技术核验；人工审核后续进行",
    "独立复算、盲评、ACL 与污染审计、归档清单通过": "独立复算、ACL与污染审计、归档清单通过；人工审核状态单列",
    "盲审原始双标、仲裁、κ/α": "逐项类别/rubric/公开来源和后续人工审核状态",
    "评分与盲评原始表": "评分原始表与后续人工审核记录",
    "题目/协议": "题目/协议",
    "没有通过工具目录或金标准访问负测的证据。": "没有通过工具目录或金标准访问负测的证据；历史记录与本轮状态不得混用。",
    "本版替代 v2": "本版替代v3",
    "v3 取代此前实时闭环草案和 v2": "v4继承v3对实时闭环草案和v2",
    "用户要求暂不运行 E5。E5 确认性矩阵保持 0/2,016；以下只是本地门禁代码测试、静态/文档复核和过程审计，不会创建 E5 cell、调用模型或把测试 fixture 计入实验。": "本段为历史证据：此前用户要求暂不运行E5。该限制已被2026-10-12执行指令替代；历史零单元测试不得算作本轮确认性结果。",
    "当前 CLI 为 `0.2.1-alpha.1`": "PATH上全局CLI为`0.2.1-alpha.1`；本轮固定安装目录CLI`0.2.0-rc.2`",
    "本轮读取的已安装 CLI 报告 `0.2.1-alpha.1`": "历史读取的是PATH上全局CLI`0.2.1-alpha.1`；本轮安装目录CLI实测为`0.2.0-rc.2`",
    "当前 E5 仍为 0/2,016，NO-GO": "历史E5为0/2,016，NO-GO；新结果以本轮门禁和coverage为准",
    "任务类别/双盲统计仍缺证": "任务类别、评分与统计技术冻结仍缺证；人工审核后续进行",
    "类别/盲审、G7 统计预登记仍未冻结": "类别/评分、G7统计预登记仍未冻结",
    "盲审 rubric/Gold、双盲/仲裁、一致性方案": "rubric/Gold与逐项来源、后续人工审核状态",
    "用户要求暂不运行；现为 0/2,016，NO-GO": "用户已授权本轮执行；技术门未齐前仍为0/2,016，NO-GO",
    "类别映射、arm/system": "类别映射、arm/system",
    "只代表当时环境，不可冒充本轮版本": "只代表当时环境；本轮须重验安装目录CLI、profile与preset的实际版本",
    "本机当前 CLI 为 `0.2.1-alpha.1`": "本轮固定安装目录CLI`0.2.0-rc.2`",
    "docs/E5-NEW-WINDOW-EXECUTION-PLAN-2026-10-12.md": "docs/E5-EXECUTION-ENTRY-v4-2026-10-12.md",
}
for old, new in replacements.items():
    text = text.replace(old, new)
# Remove historical human-review preconditions wherever the old text restated them.
text = text.replace("双盲人工复核", "后续人工审核").replace("双盲统计", "统计技术冻结")
text = text.replace("盲审", "逐项技术核验").replace("双盲", "后续人工审核")
text = text.replace("κ/α", "人工审核状态").replace("仲裁", "后续人工审核")
text = text.replace("`0.2.1-alpha.1` 的正式执行", "`0.2.0-rc.2`的正式执行")
text = text.replace("使用旧版本 `0.2.0-rc.2`", "使用安装目录版本`0.2.0-rc.2`")
text += """

## v4 用户变更与统一运行时

- 2026-10-12用户明确要求执行E5，移除开跑前人工双标/审核相关门，人工审核后续进行。没有生成或伪造任何人工评审记录。
- 固定可执行入口：`<USER_HOME>\\AppData\\Local\\Programs\\DeepSeek Harness\\resources\\runtime\\cli\\bin\\dsh.cmd`；其调用安装目录`DeepSeek Harness.exe`和`app.asar`内Host，CLI/runtime版本0.2.0-rc.2。
- 科研工作模式为真实`claude-science` preset；冻结`@local/science-tools`包、preset定义与配置的SHA-256。模式与模型供应商不同：原方案的`opencode-go/deepseek-v4.1-flash`不因选science模式而自动切换。
- 普通headless 0.2.0-rc.2 runner直接创建Agent，不挂载preset，不能仅改persona或默认preset配置便宣称使用了Claude Science模式。必须用真实preset绑定的session入口或经管理器安装、实测的专用driver。
- Claude Science中的持久内核、通用文件/网络/MCP/子代理工具可以用于研究编排；进入每个确认性Agent时仍必须仅暴露该臂冻结E5工具，禁用science_kernel、science_mcp、host SDK等绕过边界的入口。共享内核与台账不得在实验Agent间形成状态污染。
- 不修改默认desktop profile，不调用PATH上的全局dsh，不绕过plugin_manager手写实验profile。未获得专用Windows身份/Gold ACL、真实工具闭环或技术冻结时停止，不退化为表达阶段/replay/scripted结果。
"""
if re.search(r"双盲|盲审|κ|≥0\.80|至少两位评审|两名不知条件", text):
    raise RuntimeError("human review precondition remains")
archive = OUT / "historical-v3.md"
with archive.open("xb") as f:
    f.write(raw)
targets = [
    PLAN / "E5_确认性执行协议_v4_Harness020rc2_ClaudeScience_2026-10-12.md",
    REPO / "docs/e5-execution-protocol-v4-2026-10-12.md",
]
for target in targets:
    with target.open("x", encoding="utf-8", newline="\n") as f:
        f.write(text)
record = {
    "schema": "e5-user-amendment-v4",
    "date": "2026-10-12",
    "original_protocol_sha256": hashlib.sha256(raw).hexdigest(),
    "v4_sha256": hashlib.sha256(text.encode()).hexdigest(),
    "authorization": "execute E5; move human review later; use installed Harness CLI 0.2.0-rc.2 and Claude Science mode",
    "human_review": "pending_post_run",
    "confirmatory_units": 0,
    "targets": [str(p) for p in targets],
}
with (OUT / "protocol-amendment.json").open("x", encoding="utf-8") as f:
    json.dump(record, f, ensure_ascii=False, indent=2)
print(json.dumps(record, ensure_ascii=False, indent=2))
