# -*- coding: utf-8 -*-
"""
layout_data.py
--------------
astro-best 两张 drawio 架构图生成器的纯数据常量表: 字体 / 配色 / 画布尺寸 /
坐标 / 卡片 HTML 文案 / 连线定义。本模块不含任何逻辑 (无函数, 无控制流) ——
渲染代码留在两个生成器脚本里, 数据全部集中到此处。

来源: docs/architecture/file-size-budget.md §3.5 已登记的拆分预案 ——
"把坐标常量表抽到 docs/diagrams/layout_data.py (纯数据, 无逻辑), 生成器只留
渲染代码"; 硬性验收是生成产物 (.drawio) 逐字节不变。

分组约定 (前缀即归属图):
  FF                两张图共用的字体回退栈 (保证视觉语言一致)
  FLOWCHART_*       gen_best_macro_flowchart.py   (4400x3200 宏观全景流程图)
  ARCHITECTURE_*    gen_astro_best_architecture.py (2400 宽 4 页架构图)

读表须知 (改任何数值前先读):
  - 每张卡的 HTML 都是 SKILL.md / architecture.md / 契约文件的逐字转写,
    "图与文档不一致即视为缺陷", 不做二次概括;
  - 坐标分两套体系: 泳道容器用画布绝对坐标, 容器内卡片用相对父容器的局部
    坐标 (drawio_builder 约定);
  - 各行顺序即图上添加顺序, 直接决定 .drawio XML 里 <mxCell> 的排列 ——
    调整行序会改变产物字节, 属于视觉变更, 需重新过碰撞审计;
  - 连线锚点后缀 (exitX/exitY/entryX/entryY) 与 waypoints 是走线铁律
    "纯正交 Manhattan + 显式锚点"的落地形式, 见生成器 edge_style() 注释;
  - 架构图原脚本里按循环生成的卡片/连线 (能力组件卡、委派路由表、五状态机、
    阶段数据流、降级协议、不可变证据、状态/数据流传递边) 已在此物化为显式
    行, 行内 x/y 就是原循环算术的结果, 改行序等于改图。
"""

# =====================================================================
# 字体组: 三平台回退栈 (Windows Segoe UI / 中文 Microsoft YaHei /
# macOS PingFang SC), 两张图共用, 消费方是生成器的 st()/container_style()
# /edge_style()/TITLE_STYLE。改这里会同时改两张图的全部文字字体
# =====================================================================
FF = "Segoe UI,Microsoft YaHei,PingFang SC,sans-serif"  # 三平台回退栈; 改这里两张图的文字字体同时变

# =====================================================================
# 配色组: (填充色, 字体色, 描边色, 描边宽度), 每键是一类图面语义。
# 两份色板数值不同 (架构图 red/purple/cyan/indigo 线宽 1.6、banner 底色
# 偏蓝; 流程图统一 1.8、banner 近中性), 故按图分列不合并 —— 合并会让
# 其中一张图的视觉规格被另一张悄悄改掉
# =====================================================================
FLOWCHART_PALETTE = {  # 流程图色板: 线宽统一 1.8, banner 近中性
    "title": ("#0F172A", "#FFFFFF", "#1E293B", 2.0),
    "banner": ("#F8FAFC", "#0F172A", "#CBD5E1", 1.5),
    "blue": ("#F0F7FF", "#1E3A8A", "#2563EB", 1.8),
    "green": ("#ECFDF5", "#064E3B", "#059669", 1.8),
    "cyan": ("#ECFEFF", "#155E75", "#0891B2", 1.8),
    "indigo": ("#EEF2FF", "#3730A3", "#4F46E5", 1.8),
    "amber": ("#FFF7ED", "#9A3412", "#EA580C", 1.8),
    "red": ("#FEF2F2", "#991B1B", "#DC2626", 1.8),
    "purple": ("#FAF5FF", "#581C87", "#9333EA", 1.8),
    "neutral": ("#F8FAFC", "#1E293B", "#64748B", 1.5),
    "muted": ("#F1F5F9", "#64748B", "#CBD5E1", 1.2),
}

ARCHITECTURE_PALETTE = {  # 架构图色板: 线宽 1.6, banner 底色偏蓝 (与流程图分列)
    "title": ("#0F172A", "#FFFFFF", "#1E293B", 2.0),
    "banner": ("#F0F7FF", "#1E3A8A", "#2563EB", 1.8),
    "label": ("#F0F7FF", "#1E3A8A", "#2563EB", 1.8),
    "blue": ("#F0F7FF", "#1E3A8A", "#2563EB", 1.8),
    "neutral": ("#F8FAFC", "#1E293B", "#94A3B8", 1.4),
    "green": ("#ECFDF5", "#064E3B", "#059669", 1.8),
    "amber": ("#FFF7ED", "#9A3412", "#EA580C", 1.8),
    "red": ("#FEF2F2", "#991B1B", "#DC2626", 1.6),
    "purple": ("#FAF5FF", "#581C87", "#9333EA", 1.6),
    "cyan": ("#ECFEFF", "#155E75", "#0891B2", 1.6),
    "indigo": ("#EEF2FF", "#3730A3", "#4F46E5", 1.6),
    "muted": ("#F1F5F9", "#64748B", "#CBD5E1", 1.2),
}

# =====================================================================
# FLOWCHART 组: 4400x3200 宏观全景流程图 (5 泳道 + 外环闭环走廊)
# =====================================================================
# 画布尺寸 (px)。页名/页 id/DrawioFile 文件名是标识符不是坐标, 留在生成器
FLOWCHART_CANVAS = (4400, 3200)  # (宽, 高) px; 页名/页 id/文件名是标识符不是坐标, 留在生成器

# 顶部宏观总标题条 (画布级节点, 不属于任何泳道): (x, y, w, h, HTML)
FLOWCHART_BANNER = (  # 画布级节点: (x, y, w, h, HTML), 不属于任何泳道
    200, 30, 4000, 75,                                                                              # 横幅矩形: x, y, 宽, 高
    "<b>astro-best: BAO 反馈系外行星与恒星瞬变源 (BEST) 数据库基准星表接入中枢 · 全景架构图</b><br/><span style='font-size:12.5px;color:#94A3B8;'>定位: BEST 数据源主理 &nbsp;|&nbsp; 核心通信: NADC 两阶段异步 REST 协议 (Phase 1 POST /q + Phase 2 GET /sqlid) &nbsp;|&nbsp; 治理范式: 五状态机流转 (INTAKE-VALIDATE-EXECUTE-GATE-EMIT) &nbsp;|&nbsp; 覆盖基准: 12 大定标星表全景 &nbsp;|&nbsp; 闭环中枢: 11-closed-loop 科学重观测反馈回路</span>",
)

# 数据口径表 (画布级节点, 不属于任何泳道): (x, y, w, h, HTML)
# 为什么要独立成条: 量纲与单位是科学数据出错的第一来源, 旧版把单位塞在
# "12 大横切治理面"横幅的 ② Units 一行里, 读者要读完 12 条治理面才看见单位。
# 参考数模国赛 A 题全景架构图的口径表做法 (温度 °C / 浓度 kg/kg / 几何 η),
# 把口径提为图面一级元素; 表中每个数值都能在源码里对上号 (见 html 注释)。
FLOWCHART_UNITS_STRIP = (  # 量纲独立成条: 旧版藏在 12 条治理面里, 读者要读完才看见单位
    200, 2962, 4000, 62,                                                                            # 单位条矩形
    # 数值出处: ra/dec 范围见 src.protocol 校验; radius_arcsec<=18000 见 VALIDATE 卡;
    # rate_limit=3.0s 见 node_c6; rows=1000/max_rows=50000 见 node_c4;
    # SHA-256 见 node_e3 与双门槛; min_snr/fwhm/class_star 见 node_b4
    "<b>【数据口径表 · 全链路唯一】</b>坐标 deg (ICRS, J2000) &nbsp;|&nbsp; 角距 arcsec (上限 18000) &nbsp;|&nbsp; 测光 mag &nbsp;|&nbsp; 时间 UTC ISO8601 &nbsp;|&nbsp; 请求速率 req/s (礼貌限流 3.0s) &nbsp;|&nbsp; 分页 rows=1000 · max_rows=50000 &nbsp;|&nbsp; 完整性 SHA-256 &nbsp;|&nbsp; 质量门限 min_snr≥5.0 · fwhm≤5.0 · class_star≥0.8",
)

# 五大能力泳道容器 (自上而下): (容器 id, 标题, x, y, w, h)
# 第 6 条是闭环反馈走廊 (不是能力层, 是横切五条泳道的回退通道), 单独列在
# FLOWCHART_LOOP_CONTAINER — 它与五条泳道同级的容器身份, 但不参与"第几层"编号
FLOWCHART_CONTAINERS = [  # 五大能力泳道: (容器 id, 标题, x, y, w, h), 自上而下排列
    ("s1_access", "1. 多端接入与交互层 (Multi-Modal Access & Client Interfaces)", 200, 160, 4000, 370),  # 泳道高 370: 六张 570x280 卡片单排
    ("s2_state", "2. 调度编排与五状态机治理层 (Orchestration, 5-State Machine & 12 Governance Facets)", 200, 650, 4000, 500),  # 泳道高 500: 六张卡 + 底部治理面横条
    ("s3_protocol", "3. 两阶段异步 REST 通信引擎 (Two-Phase Asynchronous REST Protocol & Transport Robustness)", 200, 1270, 4000, 440),  # 泳道高 440: 六张 570x340 卡片单排
    ("s4_catalogs", "4. 12 张可查定标星表全景体系与外部数据源 (12 Queryable Calibration Catalogs & External Services)", 200, 1830, 4000, 520),  # 泳道高 520: 首排五张 + 次排七张两行
    ("s5_security", "5. 安全防御、产物交付、委派路由与闭环回退 (Security Defenses, Sinks, Delegation Routing & Closed-Loop Feedback)", 200, 2470, 4000, 480),  # 泳道高 480: 六张 570x370 卡片单排
]

# 闭环反馈走廊容器: 第 6 条横向带, 画布级 (不属于五条能力泳道中的任何一条)。
# 生成器 docstring 承诺"外环专用闭环反馈走廊", 布局层就不能只把它落成
# 一条绕画布的边 (e_e6_a1) —— 那样读者看不到闭环经过哪几站。本容器把走廊提为
# 可见结构, 与数模国赛 A 题架构图"外框轨道 + 环内循环节点"同一范式。
FLOWCHART_LOOP_CONTAINER = (  # 第 6 条横向走廊容器: (id, 标题, x, y, w, h)
    "loop_corridor",
    "闭环反馈走廊 (Closed-Loop Corridor · 横切五大泳道的重观测回退通道; 外环紫色虚线即返回走线)",
    200, 3036, 4000, 140,                                                                           # 图例矩形
)

# 容器内卡片: (父容器 id, 节点 id, x, y, w, h, 色键, HTML)。
# x/y 是相对父容器左上角的局部坐标; w/h 为卡片尺寸
FLOWCHART_NODES = [  # 卡片行: (父容器 id, 节点 id, x, y, w, h, 色键, HTML); x/y 为父容器内局部坐标
    ("s1_access", "node_a1", 55, 55, 570, 280, "blue", "<b>科研人员 / 智能体决策调度中心</b> &nbsp;<span style='color:#2563EB;'>[DECISION_CORE]</span><br/><span style='font-size:10.5px;color:#64748B;'>Human Astronomer &amp; LLM Agent Orchestrator</span><br/><hr style='border:0.5px solid #CBD5E1;'/>• <b>任务意图识别</b>: 天区锥搜、测光校准、多波段交叉匹配<br/>• <b>星表选择决策</b>: std / ps1 / stripe82 / gaia_dr3 / jplus<br/>• <b>上下文与配额控制</b>: 控制单次查询规模 (rows&le;50000)<br/>• <b>科学目标</b>: 超新星、变星、系外行星定标基准获取<br/>• <b>闭环交互中枢</b>: 接收质量门禁反馈并驱动重新观测决策"),
    ("s1_access", "node_a2", 719, 55, 570, 280, "blue", "<b>CLI 命令行工具链 (astro-best)</b> &nbsp;<span style='color:#059669;'>[VERIFIED_ALGO]</span><br/><span style='font-size:10.5px;color:#64748B;'>python -m src · ops/astro_best_cli.py</span><br/><hr style='border:0.5px solid #CBD5E1;'/>• <b>cone</b>: 天区锥搜 (<code>--ra --dec --radius --catalog --band</code>)<br/>• <b>download</b>: 区域抓取 (<code>--bands --max 50000 --output</code>)<br/>• <b>crossmatch</b>: 坐标交叉比对 (<code>--input coords.csv --radius</code>)<br/>• <b>catalogs</b>: 打印 12 张可查星表枚举字典与端点映射<br/>• <b>info</b>: 探测 NADC 服务连通性 (<code>check_connection</code>)<br/>• <b>doctor</b>: 全离线导入与契约自检 (执行耗时 &lt;1.0s)<br/>• <b>config</b>: 查看 REST/TAP 端点及 min_snr=5.0 门限制"),
    ("s1_access", "node_a3", 1383, 55, 570, 280, "blue", "<b>Agent 工具面 (ToolBox)</b> &nbsp;<span style='color:#059669;'>[VERIFIED_ALGO]</span><br/><span style='font-size:10.5px;color:#64748B;'>src/ai_tools.py · src/ai_tools_envelope.py</span><br/><hr style='border:0.5px solid #CBD5E1;'/>• <b>7 个原子工具</b>: resolve_name/list_catalogs/describe_catalog/cone_search/crossmatch_batch/count/fetch_page<br/>&nbsp;&nbsp;- 统一信封 (data/status/cost/provenance), 站点行数据一律 <code>untrusted</code><br/>&nbsp;&nbsp;- <code>cost.http_requests</code> 在 <code>Session.request</code> 唯一出口实测计数<br/>&nbsp;&nbsp;- <code>best://</code> 稳定句柄替代易失 sqlid 作引用键<br/>• <b>无独立传输层</b>: 直接以 Python 调用或经 function-calling 消费<br/>&nbsp;&nbsp;- (MCP 通道已于 2026-10-06 整体移除)<br/>• <b>错误码契约</b>: E_INVALID_INPUT/E_SOFT_404/E_NAME_UNRESOLVED/E_NO_SQLID/E_BACKEND<br/>• <b>P1 合并</b>: pybest 单类门面已删除, 工具面客户端唯一化为 BestClient"),
    ("s1_access", "node_a4", 2047, 55, 570, 280, "blue", "<b>经典面向对象组件库 (OOP Client Suite)</b> &nbsp;<span style='color:#059669;'>[VERIFIED_ALGO]</span><br/><span style='font-size:10.5px;color:#64748B;'>BestClient / BestAuth / BestQuery / BestDownloader</span><br/><hr style='border:0.5px solid #CBD5E1;'/>• <b>BestClient</b>: 两阶段查询调度引擎，维持 CSRF 会话状态<br/>• <b>BestAuth</b>: NADC 登录管理器，提取 <code>X-CSRFToken</code> 安全凭据<br/>• <b>BestQuery</b>: Fluent 链式构造器:<br/>&nbsp;&nbsp;<code>.catalog().cone().mag_range().min_snr().where().build()</code><br/>• <b>BestCrossMatch</b>: Haversine 大圆角距高精度空间邻近匹配<br/>• <b>BestMultiBandPhotometry</b>: 多波段静态测光导出容器（BEST 无时序，非光变曲线）<br/>• <b>BestDownloader</b>: 支持断点续传与 SHA-256 完整性核验"),
    ("s1_access", "node_a5", 2711, 55, 570, 280, "blue", "<b>零依赖轻量独立脚本集</b> &nbsp;<span style='color:#059669;'>[VERIFIED_ALGO]</span><br/><span style='font-size:10.5px;color:#64748B;'>Pure Python stdlib / PowerShell / Bash</span><br/><hr style='border:0.5px solid #CBD5E1;'/>• <b>适用场景</b>: 离线服务器、受限容器、运维终端快速诊断<br/>• <b>best_standalone.py</b>:<br/>&nbsp;&nbsp;- 仅依赖 Python 标准库 + 基础 requests<br/>&nbsp;&nbsp;- 内联两阶段 POST+GET，免安装完整 skill 包即可执行<br/>• <b>best_query.ps1</b>: Windows PowerShell 运维原生脚本<br/>• <b>best_query.sh</b>: Linux/macOS Shell 自动化流水线调用<br/>• <b>输出落盘</b>: 自动写入 <code>best_data/</code> 规范目录"),
    ("s1_access", "node_a6", 3375, 55, 570, 280, "blue", "<b>本地领域 RAG 检索 (无云端分发)</b> &nbsp;<span style='color:#4F46E5;'>[HYBRID]</span><br/><span style='font-size:10.5px;color:#64748B;'>rag/astro_rag.py</span><br/><hr style='border:0.5px solid #CBD5E1;'/>• <b>本地领域 RAG 检索器 (astro_rag.py)</b>:<br/>&nbsp;&nbsp;- 纯离线 BM25 (k1=1.5, b=0.75) ⊕ CJK 字符词桶通道<br/>&nbsp;&nbsp;- 领域术语提权字典 (DOMAIN_BOOST) ⊕ RRF 融合排序<br/>&nbsp;&nbsp;- 检索 4 大规则库: domain_rules, known_issues, lessons<br/>• <b>算力边界 (G8)</b>: 本地 &lt;100 样本点、&lt;1s 单测<br/>&nbsp;&nbsp;- 重负载由调用方在仓外自行调度<br/>&nbsp;&nbsp;- (ModelScope 云端分发组件已于 2026-10-06 移除)"),
    ("s2_state", "node_b1", 55, 55, 570, 210, "green", "<b>① INTAKE 接收态</b> &nbsp;<span style='color:#059669;'>[VERIFIED_ALGO]</span><br/><span style='font-size:10.5px;color:#64748B;'>Entry: 上游信封到达 | Exit: 凭据与Hash齐备</span><br/><hr style='border:0.5px solid #CBD5E1;'/>• <b>输入契约验证</b>: 校验 <code>astro-envelope-v1</code> 结构<br/>• <b>溯源凭证提取</b>: 提取 <code>session_id</code> 与 <code>data_hash</code><br/>• <b>鉴权状态探测</b>: 核验 <code>BEST_API_TOKEN</code> (env) 或 BestAuth 显式登录<br/>• <b>Fail-Closed 拒收</b>: 信封为空直接抛 <code>E_INTAKE_EMPTY</code>"),
    ("s2_state", "node_b2", 719, 55, 570, 210, "green", "<b>② VALIDATE 校验态</b> &nbsp;<span style='color:#059669;'>[VERIFIED_ALGO]</span><br/><span style='font-size:10.5px;color:#64748B;'>Schema: input.contract.yaml | Fail: E101</span><br/><hr style='border:0.5px solid #CBD5E1;'/>• <b>空间坐标范围检验</b>: 0.0 &le; ra &lt; 360.0, -90.0 &le; dec &le; 90.0<br/>• <b>搜索半径物理约束</b>: 0.0 &lt; radius_arcsec &le; 18000.0 (5度上限)<br/>• <b>星表标识符白名单</b>: 严格属于 12 张可查星表代码<br/>• <b>错误拦截</b>: 违规输出 <code>needs_review</code> 决策信封"),
    ("s2_state", "node_b3", 1383, 55, 570, 210, "green", "<b>③ EXECUTE 执行态</b> &nbsp;<span style='color:#059669;'>[VERIFIED_ALGO]</span><br/><span style='font-size:10.5px;color:#64748B;'>Engine: 场景路由分发与单点隔离执行</span><br/><hr style='border:0.5px solid #CBD5E1;'/>• <b>Mode A (两阶段查询)</b>: POST 表单提交 &rarr; GET 分页流式抓取<br/>• <b>Mode B (约束下载)</b>: BestDownloader 断点续传切片下载<br/>• <b>Mode C (批量比对)</b>: 逐点 try/except 隔离，单点失败置 failed<br/>• <b>委派路由</b>: 越界匹配/清洗委派 canonical 主理 skill"),
    ("s2_state", "node_b4", 2047, 55, 570, 210, "amber", "<b>④ GATE 门禁判定态</b> &nbsp;<span style='color:#EA580C;'>[GATE_CHECK]</span><br/><span style='font-size:10.5px;color:#64748B;'>阻断门禁: http_status==200 &amp;&amp; checksum==true</span><br/><hr style='border:0.5px solid #CBD5E1;'/>• <b>传输状态门限</b>: 网络 HTTP 状态码强制核查，非 200 硬阻断<br/>• <b>文件指纹校验</b>: SHA-256 哈希比对，不符立即销毁临时文件<br/>• <b>天体测光质量检验</b>: min_snr &ge; 5.0, max_fwhm &le; 5.0<br/>• <b>恒星形态判据</b>: ps1_class_star &ge; 0.8 (严格滤除伪点源)"),
    ("s2_state", "node_b5", 2711, 55, 570, 210, "purple", "<b>⑤ EMIT 交付发布态</b> &nbsp;<span style='color:#9333EA;'>[VERIFIED_ALGO]</span><br/><span style='font-size:10.5px;color:#64748B;'>Sinks: 原子写落盘与不可变数据信封组装</span><br/><hr style='border:0.5px solid #CBD5E1;'/>• <b>原子落盘保障</b>: <code>write_text + os.replace</code> 杜绝半写残卷<br/>• <b>双态信封封包</b>: 交付 <code>data_envelope</code> (结构化结果集)<br/>• <b>多格式物理产物</b>: 规范 CSV / TSV / VOTable / JSON / ECSV<br/>• <b>审计元数据注记</b>: 附带执行时间戳、耗时、总记录数与血缘"),
    ("s2_state", "node_b6", 3375, 55, 570, 210, "red", "<b>阻断分流与审查决策态 (needs_review)</b> &nbsp;<span style='color:#DC2626;'>[FALLBACK]</span><br/><span style='font-size:10.5px;color:#64748B;'>contracts/error-codes.contract.yaml | E101 / E102</span><br/><hr style='border:0.5px solid #CBD5E1;'/>• <b>E101_INVALID_INPUT (BEST_1001)</b>: 坐标超限或星表不存在拦截<br/>• <b>E102_GATE_FAILED (BEST_1002)</b>: HTTP 失败或 SHA-256 校验和失配<br/>• <b>E103_DELEGATE_STREAM (BEST_1003)</b>: 委派链路异常或远端超时<br/>• <b>决策信封封装</b>: 产出 <code>decision_envelope</code> (handoff.status=blocked)<br/>• <b>下游保护</b>: 严密阻断脏数据注入下游超新星与变星探测管线"),
    ("s2_state", "node_b_gov", 55, 340, 3890, 125, "indigo", "<b>【12 大横切治理面全生命周期锚定矩阵 (12 Cross-Cutting Governance Facets Architecture)】</b><br/><span style='font-size:11px;color:#3730A3;'>① <b>Provenance 溯源</b>: 强制绑定 session_id 与 data_hash &nbsp;|&nbsp; ② <b>Units 量纲</b>: 坐标 deg、角距 arcsec、测光 mag、流速 req/s &nbsp;|&nbsp; ③ <b>Determinism 确定论</b>: 固定 seed=42 杜绝非受控时钟 &nbsp;|&nbsp; ④ <b>Logging 日志</b>: 降级统一输出 WARN 级审计标记<br/>⑤ <b>Error Codes 错误码</b>: 严格规范 BEST_1001~1099 &nbsp;|&nbsp; ⑥ <b>Contracts 双态信封</b>: 区分 data 数据信封与 decision 决策信封 &nbsp;|&nbsp; ⑦ <b>Quality Gates 门禁</b>: 双阻断条件前置硬拦截 &nbsp;|&nbsp; ⑧ <b>Delegation 委派</b>: 坚守主理边界，越界能力主动委派<br/>⑨ <b>Security 安全</b>: 凭据隔离只读、CSV 公式清洗、路径锚定 &nbsp;|&nbsp; ⑩ <b>Reproducibility 可复现</b>: 算法 100% 白盒有据 &nbsp;|&nbsp; ⑪ <b>Compute Budget 预算</b>: 本地单测 &lt;1.0s，重算上云 &nbsp;|&nbsp; ⑫ <b>Observability 遥测</b>: 全链路结构化事件可回放</span>"),
    ("s3_protocol", "node_c1", 55, 55, 570, 340, "cyan", "<b>Phase 1: POST 表单构造器</b> &nbsp;<span style='color:#059669;'>[VERIFIED_ALGO]</span><br/><span style='font-size:10.5px;color:#64748B;'>protocol.build_query_form (protocol.py:250)</span><br/><hr style='border:0.5px solid #CBD5E1;'/>• <b>天区锥搜参数映射</b>:<br/>&nbsp;&nbsp;<code>pos.racenter = ra, pos.deccenter = dec</code><br/>&nbsp;&nbsp;<code>pos.radius = radius_arcsec, pos.type = 'cone'</code><br/>• <b>列约束名称白名单</b>:<br/>&nbsp;&nbsp;<code>qualify_column</code> 校验正则: <code>^[A-Za-z_][A-Za-z0-9_]*$</code><br/>• <b>操作符纠错与范围映射</b>:<br/>&nbsp;&nbsp;将 <code>greater</code> 自动修正为服务端历史拼写 <code>grater</code><br/>&nbsp;&nbsp;<code>between</code> 自动拆解为 <code>{col}.min</code> 与 <code>{col}.max</code><br/>• <b>列投影与格式</b>: 注入 <code>showcol</code> 与 <code>output.fmt</code>"),
    ("s3_protocol", "node_c2", 719, 55, 570, 340, "cyan", "<b>Phase 1: 异步查询提交端点</b> &nbsp;<span style='color:#2563EB;'>[EXTERNAL_DRIVER]</span><br/><span style='font-size:10.5px;color:#64748B;'>POST https://nadc.china-vo.org/data/best/{cat}/q</span><br/><hr style='border:0.5px solid #CBD5E1;'/>• <b>请求类型</b>: <code>application/x-www-form-urlencoded</code><br/>• <b>Session 凭据挂载</b>: 携带会话 Cookie 与 <code>X-CSRFToken</code><br/>• <b>服务端行为</b>: Django 后端启动异步工作流，生成临时查询 Session<br/>• <b>响应内容</b>: HTTP 200 HTML 页面，内嵌带唯一查询标记的链接<br/>• <b>网络防护</b>: 遭遇 HTTP 429 / 5xx 触发指数退避重试<br/>• <b>耗时预算</b>: 典型响应时间 0.8s ~ 2.5s"),
    ("s3_protocol", "node_c3", 1383, 55, 570, 340, "amber", "<b>SQLID 正则提取与安全清洗</b> &nbsp;<span style='color:#EA580C;'>[SECURITY_GATE]</span><br/><span style='font-size:10.5px;color:#64748B;'>protocol.normalize_sqlid</span><br/><hr style='border:0.5px solid #CBD5E1;'/>• <b>正则捕获模式</b>: <code>re.compile(r'sqlid/(s?\\d+)')</code><br/>• <b>白名单正则强校验</b>:<br/>&nbsp;&nbsp;<code>_SAFE_SQLID_RE = re.compile(r's?\\d+\\Z')</code><br/>• <b>防穿透字符清洗</b>: <code>re.sub(r'[^a-zA-Z0-9_-]', '', sqlid)</code><br/>• <b>拦截恶意输入</b>:<br/>&nbsp;&nbsp;拒收 <code>../../etc/passwd</code> (路径穿越)<br/>&nbsp;&nbsp;拒收 <code>1; DROP TABLE best</code> (SQL/日志注入)<br/>• <b>校验失败出口</b>: 抛出 <code>ValueError('Invalid BEST sqlid')</code>"),
    ("s3_protocol", "node_c4", 2047, 55, 570, 340, "cyan", "<b>Phase 2: 数据分块获取与分页引擎</b> &nbsp;<span style='color:#059669;'>[VERIFIED_ALGO]</span><br/><span style='font-size:10.5px;color:#64748B;'>GET https://nadc.china-vo.org/data/best/sqlid/{sqlid}</span><br/><hr style='border:0.5px solid #CBD5E1;'/>• <b>分页参数</b>: <code>page=P, rows=1000, output.fmt=csv/tsv/json</code><br/>• <b>最大记录控制</b>: 单次任务上限 <code>max_rows=50000</code> 行<br/>• <b>数据流汇聚</b>: 递增页码迭代拉取，直至返回行数 &lt; 1000<br/>• <b>容错 CSV 解析引擎</b>:<br/>&nbsp;&nbsp;- 智能检测并剥除 <code>UTF-8-SIG (BOM)</code> 前缀<br/>&nbsp;&nbsp;- 针对历史无表头 CSV，自动对齐首两列为 <code>(ra, dec)</code><br/>• <b>数据结构转换</b>: 组装为 <code>BestQueryResult / BestSource</code> 实体"),
    ("s3_protocol", "node_c5", 2711, 55, 570, 340, "cyan", "<b>Phase 2: 总条数查询与计数器</b> &nbsp;<span style='color:#059669;'>[VERIFIED_ALGO]</span><br/><span style='font-size:10.5px;color:#64748B;'>GET /data/best/sqlid/{sqlid}/getcount</span><br/><hr style='border:0.5px solid #CBD5E1;'/>• <b>SQLID 前缀剥离</b>:<br/>&nbsp;&nbsp;调用 <code>protocol.count_sqlid</code> 执行 <code>removeprefix('s')</code><br/>&nbsp;&nbsp;将 <code>s2623</code> 精确转换为后端纯数字 <code>2623</code><br/>• <b>响应格式解析</b>: 支持 <code>{'total': 4820}</code> JSON 与纯文本整数<br/>• <b>调度用途</b>: 精确预估分页拉取轮数与流式下载进度条<br/>• <b>平滑降级</b>: 接口偶发异常时返回 None，不阻断主分页拉取"),
    ("s3_protocol", "node_c6", 3375, 55, 570, 340, "indigo", "<b>传输安全与鲁棒性控制中枢</b> &nbsp;<span style='color:#4F46E5;'>[NET_ROBUST]</span><br/><span style='font-size:10.5px;color:#64748B;'>Session Pool / Retry / Throttle Engine</span><br/><hr style='border:0.5px solid #CBD5E1;'/>• <b>连接池维持</b>: <code>requests.Session</code> 复用 TCP 连接与 SSL 握手<br/>• <b>指数退避重试</b>:<br/>&nbsp;&nbsp;<code>HTTPAdapter(max_retries=Retry(3, backoff_factor=2.0))</code><br/>&nbsp;&nbsp;拦截状态码: 429 (限流), 500, 502, 503, 504<br/>• <b>OpenAlex 范式动态退避</b>: 智能解析响应头 <code>Retry-After</code><br/>• <b>礼貌请求限速</b>: <code>rate_limit=3.0s</code> (符合 arXiv 抓取规范)<br/>• <b>连续失败熔断</b>: 超过 3 次触发降级协议 (FB-1 网络降级)"),
    ("s4_catalogs", "node_d1", 55, 55, 710, 175, "indigo", "<b>① std: Standard Stars 标准星</b> &nbsp;<span style='color:#2563EB;'>[DRIVER]</span><br/><span style='font-size:10.5px;color:#64748B;'>std/q | UBVRI 测光标准基准</span><br/><hr style='border:0.5px solid #CBD5E1;'/>• <b>主键与坐标</b>: <code>std_id, std_name, std_ra, std_dec</code><br/>• <b>关键测光列</b>: <code>std_mag, std_mag_err</code><br/>• <b>科学定位</b>: 绝对流量与仪器零点标定参考标准星"),
    ("s4_catalogs", "node_d2", 850, 55, 710, 175, "indigo", "<b>② ps1: Pan-STARRS All-Sky 全天星表</b> &nbsp;<span style='color:#2563EB;'>[DRIVER]</span><br/><span style='font-size:10.5px;color:#64748B;'>ps1/q | 20 亿+ 天体光学全天基准</span><br/><hr style='border:0.5px solid #CBD5E1;'/>• <b>5 波段 PSF 星等</b>: <code>gpsf, rpsf, ipsf, zpsf, ypsf</code><br/>• <b>星点与天体测量</b>: <code>ps1_class_star, ps1_ruwe</code><br/>• <b>科学定位</b>: 超新星、光学瞬变源巡天高精度参考基准"),
    ("s4_catalogs", "node_d3", 1645, 55, 710, 175, "indigo", "<b>③ stripe82: Well-Calibrated Stripe82</b> &nbsp;<span style='color:#2563EB;'>[DRIVER]</span><br/><span style='font-size:10.5px;color:#64748B;'>stripe82/q | SDSS 赤道深场精测天区</span><br/><hr style='border:0.5px solid #CBD5E1;'/>• <b>5 波段多次测量</b>: <code>u_h22, g_h22, r_h22, i_h22, z_h22</code><br/>• <b>精测离散度指标</b>: <code>rms, chi2, n_epochs</code><br/>• <b>科学定位</b>: 80+ 次重复曝光，极微弱光变与零点标定验证"),
    ("s4_catalogs", "node_d4", 2440, 55, 710, 175, "indigo", "<b>④ gaia_dr3: Gaia DR3 精测定标星表体系</b> &nbsp;<span style='color:#2563EB;'>[DRIVER]</span><br/><span style='font-size:10.5px;color:#64748B;'>gaia_dr3/q | 空间天体测量绝对基准 (含 4 张子表体系)</span><br/><hr style='border:0.5px solid #CBD5E1;'/>• <b>绝对测光三带</b>: <code>phot_g/bp/rp_mean_mag, bp_rp, pmra, pmdec</code><br/>• <b>4 张可查定标星表</b>: <code>gaia_dr3</code>, <code>gaia_dr3_18</code>, <code>xpsp</code>, <code>dr3xpcorr</code><br/>• <b>科学定位</b>: 微角秒级空间坐标、XP 连续谱与全天绝对星等统一定标"),
    ("s4_catalogs", "node_d5", 3235, 55, 710, 175, "indigo", "<b>⑤ jplus_dr3: J-PLUS DR3 中窄带星表</b> &nbsp;<span style='color:#2563EB;'>[DRIVER]</span><br/><span style='font-size:10.5px;color:#64748B;'>jplus_dr3/q | 12 色中窄带测光系统</span><br/><hr style='border:0.5px solid #CBD5E1;'/>• <b>孔径校正测光</b>: <code>jplus_dr3_mag_aper_6_0_final</code><br/>• <b>仪器定标零点</b>: <code>aper_corr, zp1, zp2</code><br/>• <b>科学定位</b>: 北天 12 色测光，用于恒星物理参数精确反演"),
    ("s4_catalogs", "node_d6", 55, 295, 570, 180, "indigo", "<b>⑥ smss_dr4: SMSS DR4 定标星表</b> &nbsp;<span style='color:#2563EB;'>[DRIVER]</span><br/><span style='font-size:10.5px;color:#64748B;'>smss_dr4/q | SkyMapper 南天巡天基准</span><br/><hr style='border:0.5px solid #CBD5E1;'/>• <b>核心测光</b>: <code>smss_dr4_psf_mag, source_id</code><br/>• <b>科学定位</b>: 覆盖南半球天区的主力光学测光定标星表"),
    ("s4_catalogs", "node_d7", 719, 295, 570, 180, "indigo", "<b>⑦ landolt: Landolt 经典标准星场</b> &nbsp;<span style='color:#2563EB;'>[DRIVER]</span><br/><span style='font-size:10.5px;color:#64748B;'>landolt/q | 约翰逊-考辛斯系统基准</span><br/><hr style='border:0.5px solid #CBD5E1;'/>• <b>标准星等</b>: <code>umag, bmag, vmag, rmag, imag</code><br/>• <b>科学定位</b>: 全球地基大型望远镜标准星定标金标准"),
    ("s4_catalogs", "node_d8", 1383, 295, 570, 180, "indigo", "<b>⑧ uss_dr1: USS DR1 超深精测星表</b> &nbsp;<span style='color:#2563EB;'>[DRIVER]</span><br/><span style='font-size:10.5px;color:#64748B;'>uss_dr1/q | 超深巡天系统精测基准</span><br/><hr style='border:0.5px solid #CBD5E1;'/>• <b>微弱源测光</b>: <code>uss_dr1_psf_mag, source_id</code><br/>• <b>科学定位</b>: 针对暗弱深场天体的高精度测光交叉检验"),
    ("s4_catalogs", "node_d9", 2047, 295, 570, 180, "indigo", "<b>⑨ splus_dr4 & 光谱星表体系</b> &nbsp;<span style='color:#2563EB;'>[DRIVER]</span><br/><span style='font-size:10.5px;color:#64748B;'>splus_dr4/q | 南天 12 色 + SCR 交叉精测表</span><br/><hr style='border:0.5px solid #CBD5E1;'/>• <b>splus_dr4</b>: <code>j0378, j0395, j0410, j0515, j0660, j0861</code><br/>• <b>附加光谱精测表</b>: 包含 <code>scr_galah</code> (137列), <code>scr_lamost</code> (62列)<br/>• <b>科学定位</b>: 12 张可查定标星表全景完整闭环"),
    ("s4_catalogs", "node_d10", 2711, 295, 570, 180, "neutral", "<b>NADC 中国虚拟天文台官方台站服务</b> &nbsp;<span style='color:#0F172A;'>[REMOTE]</span><br/><span style='font-size:10.5px;color:#64748B;'>https://nadc.china-vo.org/data/best/</span><br/><hr style='border:0.5px solid #CBD5E1;'/>• <b>服务架构</b>: 国家天文科学数据中心托管，Django 后端<br/>• <b>数据库规模</b>: 汇聚全天 20 亿+ 精测星表底层数据<br/>• <b>核心能力</b>: 承载两阶段 Form 提交、Session 建立与异步分发"),
    ("s4_catalogs", "node_d11", 3375, 295, 570, 180, "neutral", "<b>清华大学学术 TAP 门面兼容器件</b> &nbsp;<span style='color:#0F172A;'>[REMOTE]</span><br/><span style='font-size:10.5px;color:#64748B;'>https://best.astro.tsinghua.edu.cn/tap</span><br/><hr style='border:0.5px solid #CBD5E1;'/>• <b>历史兼容</b>: 支持 TAP/IVOA 协议门面接口标准调用<br/>• <b>兼容入口</b>: <code>DEFAULT_TAP_URL</code> 维持存量学术系统调用协议<br/>• <b>降级协议</b>: TAP 异常时平滑重定向至 NADC REST 主通道"),
    ("s5_security", "node_e1", 55, 55, 570, 370, "red", "<b>CSV 公式注入与路径穿越防御</b> &nbsp;<span style='color:#DC2626;'>[SECURITY_GATE]</span><br/><span style='font-size:10.5px;color:#64748B;'>csv_safety.sanitize_cell &amp; is_relative_to</span><br/><hr style='border:0.5px solid #CBD5E1;'/>• <b>CSV 注入清洗 (CWE-1236)</b>:<br/>&nbsp;&nbsp;- 单元格以 <code>=, +, @</code> 开头强制前缀单引号 <code>'</code> 转义<br/>&nbsp;&nbsp;- <b>天文学负数放行</b>: <code>_looks_numeric</code> 智能识别 <code>-5.0</code> (南半球 Dec) 与 <code>-1.5e-3</code>，严防破坏科学数据<br/>• <b>路径穿越防御</b>:<br/>&nbsp;&nbsp;- <code>_resolve_output_path</code> 强制校验 <code>is_relative_to(output_dir)</code><br/>&nbsp;&nbsp;- 拦截一切 <code>../</code> 上溯逃逸至系统目录的攻击尝试"),
    ("s5_security", "node_e2", 719, 55, 570, 370, "amber", "<b>批处理逐条失败隔离引擎</b> &nbsp;<span style='color:#EA580C;'>[RESILIENCE]</span><br/><span style='font-size:10.5px;color:#64748B;'>batch_crossmatch &amp; crossmatch.py:334</span><br/><hr style='border:0.5px solid #CBD5E1;'/>• <b>多点批处理机制</b>: 循环处理成百上千组用户目标坐标<br/>• <b>单点局部隔离</b>:<br/>&nbsp;&nbsp;- 逐坐标点位调用独立 <code>try/except</code> 保护<br/>&nbsp;&nbsp;- 单点发生格式越界、网络超时或星表无源时，记录 <code>status='failed'</code><br/>• <b>批次不中断</b>: 绝不抛出顶层未捕获异常中断整体批次<br/>• <b>汇总记录</b>: 成功写入 <code>matches</code>，失败归档至 <code>misses/errors</code>"),
    ("s5_security", "node_e3", 1383, 55, 570, 370, "purple", "<b>不可变产物与科学存证交付</b> &nbsp;<span style='color:#9333EA;'>[IMMUTABLE_SINKS]</span><br/><span style='font-size:10.5px;color:#64748B;'>BestResultSet &amp; ECSV / CSV / JSON Sinks</span><br/><hr style='border:0.5px solid #CBD5E1;'/>• <b>结构化数据集</b>: <code>BestResultSet</code> (astro-envelope-v1 JSON)<br/>• <b>测光星表</b>: <code>best_sources.csv</code> (清洗防注入标准表格)<br/>• <b>多波段测光档案</b>: <code>BestMultiBandPhotometry</code> (静态测光容器导出，非时序)<br/>• <b>不可变证据存证</b>:<br/>&nbsp;&nbsp;- 绑定 <code>session_id</code>, <code>data_hash</code>, <code>SHA-256</code> 签名<br/>&nbsp;&nbsp;- 完整记录查询参数、执行耗时与数据血缘头<br/>• <b>原子落盘</b>: 临时文件写入完毕执行 <code>os.replace</code>，零半写残卷"),
    ("s5_security", "node_e4", 2047, 55, 570, 370, "indigo", "<b>BEST 数据源主理 · 委派路由</b> &nbsp;<span style='color:#4F46E5;'>[DELEGATION]</span><br/><span style='font-size:10.5px;color:#64748B;'>SKILL.md 委派表 &amp; Master Plan §4</span><br/><hr style='border:0.5px solid #CBD5E1;'/>• <b>主理立场</b>: 严守 In-Scope 边界，杜绝越权旁路重造轮子<br/>• <b>委派策略</b>:<br/>&nbsp;&nbsp;1. <b>通用星表检索与全天锥搜</b> &rarr; 委派至 <b>astro-catalog</b><br/>&nbsp;&nbsp;2. <b>原始图像与测光数据清洗</b> &rarr; 委派至 <b>astro-clean</b><br/>&nbsp;&nbsp;3. <b>NADC BEST REST 底层通信驱动</b> &rarr; 核心保留在 <b>astro-best</b>（唯一能访问 BEST 端点，绝不外派）<br/>• <b>错误路由标引</b>: 携带 <code>E103_DELEGATE_STREAM</code> 追踪标记"),
    ("s5_security", "node_e5", 2711, 55, 570, 370, "amber", "<b>科学质检决策与人机协同审核</b> &nbsp;<span style='color:#EA580C;'>[HUMAN_IN_THE_LOOP]</span><br/><span style='font-size:10.5px;color:#64748B;'>contracts/envelope.contract.yaml (decision_envelope)</span><br/><hr style='border:0.5px solid #CBD5E1;'/>• <b>决策状态三态</b>:<br/>&nbsp;&nbsp;- <code>ACCEPTED</code>: 门禁完全通过，放行至科学管线<br/>&nbsp;&nbsp;- <code>PASSED_PENDING_HUMAN</code>: 临界数据需专家人工复核<br/>&nbsp;&nbsp;- <code>REJECTED</code>: 质检严重不符，阻断数据分发<br/>• <b>现场证据保全</b>: 冻结当前全部输入参数、报文头与错误调用栈<br/>• <b>人机协同接口</b>: 导出可视化审查信封，供天文学家或审核智能体研判"),
    ("s5_security", "node_e6", 3375, 55, 570, 370, "red", "<b>全局科学闭环与重观测反馈回路</b> &nbsp;<span style='color:#DC2626;'>[CLOSED_LOOP_BUS]</span><br/><span style='font-size:10.5px;color:#64748B;'>11-closed-loop (World Model WM19 架构总线)</span><br/><hr style='border:0.5px solid #CBD5E1;'/>• <b>反馈闭环联动</b>: 与全局反馈学习与重观测调度系统实时互通<br/>• <b>异常触发机制</b>: 门禁持续失败、数据质量不足或网络熔断<br/>• <b>望远镜重观测决策</b>: 反向驱动望远镜调度器调整曝光、切换滤光片或重新指向<br/>• <b>知识飞轮沉淀</b>: 经验与故障自动写入 <code>known_issues.yaml</code><br/>• <b>决策闭环收敛</b>: 反馈信标直达顶部决策调度层，完成人机系统闭环"),
    # 闭环走廊四站 (父容器 loop_corridor, 局部坐标; 容器标题栏占 34px, 故从 y=48 起)
    # 四站内容全部转写自 node_e6 与 SKILL.md 的闭环描述, 不发明新事实
    ("loop_corridor", "loop_c1", 55, 48, 940, 80, "red", "<b>① 异常触发</b> &nbsp;<span style='color:#DC2626;'>[TRIGGER]</span><br/>• 门禁持续失败 · 数据质量不足 · 网络熔断<br/>• GATE 态 blocked 即进入本走廊"),
    ("loop_corridor", "loop_c2", 1048, 48, 940, 80, "amber", "<b>② 决策信封</b> &nbsp;<span style='color:#EA580C;'>[DECISION]</span><br/>• needs_review + ask 载荷，转人工复核<br/>• 复核结论: 放行 / 驳回 / 调整参数"),
    ("loop_corridor", "loop_c3", 2041, 48, 940, 80, "purple", "<b>③ 重观测请求</b> &nbsp;<span style='color:#9333EA;'>[RE-OBSERVE]</span><br/>• 11-closed-loop 驱动望远镜调度器<br/>• 调整曝光 · 切换滤光片 · 重新指向"),
    ("loop_corridor", "loop_c4", 3034, 48, 940, 80, "indigo", "<b>④ 知识飞轮</b> &nbsp;<span style='color:#4F46E5;'>[KNOWLEDGE]</span><br/>• 经验与故障沉淀 <code>known_issues.yaml</code><br/>• 反哺领域 RAG 检索与下一轮判定"),
]

# 连线: (连线 id, 源 id, 目标 id, 标签, 色, 虚线, 线宽, 字色, 锚点后缀,
# waypoints 锚点列表或 None)。虚线专用于异常/回退/闭环反馈这类非主路径
FLOWCHART_EDGES = [                                                                                 # 边清单起点: 所有连线的起终点都在这里定
    ("e_a1_a2", "node_a1", "node_a2", "CLI 任务派发", "#2563EB", False, 1.8, "#1E3A8A", "exitX=1;exitY=0.5;entryX=0;entryY=0.5;", None),
    ("e_a1_a3", "node_a1", "node_a3", "SDK 代码调用", "#2563EB", False, 1.8, "#1E3A8A", "exitX=0.5;exitY=1;entryX=0.3;entryY=1;", [(540.0, 560.0), (1550.0, 560.0)]),
    ("e_a1_a4", "node_a1", "node_a4", "OOP 复杂查询", "#2563EB", False, 1.8, "#1E3A8A", "exitX=0.6;exitY=1;entryX=0.3;entryY=1;", [(600.0, 580.0), (2210.0, 580.0)]),
    ("e_a1_a5", "node_a1", "node_a5", "轻量脚本运维", "#2563EB", False, 1.8, "#1E3A8A", "exitX=0.7;exitY=1;entryX=0.3;entryY=1;", [(660.0, 600.0), (2880.0, 600.0)]),
    ("e_a1_a6", "node_a1", "node_a6", "云端规格/RAG", "#2563EB", False, 1.8, "#1E3A8A", "exitX=0.8;exitY=1;entryX=0.3;entryY=1;", [(720.0, 620.0), (3540.0, 620.0)]),
    ("e_a2_b1", "node_a2", "node_b1", "组装输入信封", "#059669", False, 1.8, "#1E3A8A", "exitX=0.5;exitY=1;entryX=0.7;entryY=0;", [(1204.0, 560.0), (650.0, 560.0)]),
    ("e_a3_b1", "node_a3", "node_b1", "凭据与任务入队", "#059669", False, 1.8, "#1E3A8A", "exitX=0.5;exitY=1;entryX=0.5;entryY=0;", [(1868.0, 580.0), (540.0, 580.0)]),
    ("e_a4_b1", "node_a4", "node_b1", "BestQuery 序列化", "#059669", False, 1.8, "#1E3A8A", "exitX=0.5;exitY=1;entryX=0.3;entryY=0;", [(2532.0, 600.0), (430.0, 600.0)]),
    ("e_b1_b2", "node_b1", "node_b2", "信封非空/Hash齐备", "#059669", False, 1.8, "#1E3A8A", "exitX=1;exitY=0.5;entryX=0;entryY=0.5;", None),
    ("e_b2_b3", "node_b2", "node_b3", "Schema 验证通过", "#059669", False, 1.8, "#1E3A8A", "exitX=1;exitY=0.5;entryX=0;entryY=0.5;", None),
    ("e_b2_b6", "node_b2", "node_b6", "Schema 失败 (E101)", "#DC2626", True, 1.8, "#1E3A8A", "exitX=0.5;exitY=1;entryX=0.3;entryY=1;", [(1204.0, 950.0), (3740.0, 950.0)]),
    ("e_b3_b4", "node_b3", "node_b4", "执行完毕提交门禁", "#059669", False, 1.8, "#1E3A8A", "exitX=1;exitY=0.5;entryX=0;entryY=0.5;", None),
    ("e_b4_b5", "node_b4", "node_b5", "双门禁通过 (HTTP 200 + SHA-256)", "#059669", False, 1.8, "#1E3A8A", "exitX=1;exitY=0.5;entryX=0;entryY=0.5;", None),
    ("e_b4_b6", "node_b4", "node_b6", "门禁未过 (E102)", "#DC2626", True, 1.8, "#1E3A8A", "exitX=0.5;exitY=1;entryX=0.6;entryY=1;", [(2532.0, 970.0), (3910.0, 970.0)]),
    ("e_b3_c1", "node_b3", "node_c1", "路由分发 Phase 1 POST", "#0891B2", False, 1.8, "#1E3A8A", "exitX=0.5;exitY=1;entryX=0.5;entryY=0;", [(1868.0, 1210.0), (540.0, 1210.0)]),
    ("e_c1_c2", "node_c1", "node_c2", "表单载荷提交", "#0891B2", False, 1.8, "#1E3A8A", "exitX=1;exitY=0.4;entryX=0;entryY=0.4;", None),
    ("e_c2_c3", "node_c2", "node_c3", "HTML 正则抽取 sqlid", "#EA580C", False, 1.8, "#1E3A8A", "exitX=1;exitY=0.4;entryX=0;entryY=0.4;", None),
    ("e_c3_c4", "node_c3", "node_c4", "安全 sqlid 分页拉取", "#0891B2", False, 1.8, "#1E3A8A", "exitX=1;exitY=0.4;entryX=0;entryY=0.4;", None),
    ("e_c3_c5", "node_c3", "node_c5", "纯数字 sqlid 查总数", "#0891B2", False, 1.8, "#1E3A8A", "exitX=0.5;exitY=1;entryX=0.5;entryY=1;", [(1868.0, 1680.0), (3196.0, 1680.0)]),
    ("e_c6_c2", "node_c6", "node_c2", "连接池/1req/3s 限速", "#4F46E5", False, 1.8, "#1E3A8A", "exitX=0.3;exitY=1;entryX=0.3;entryY=1;", [(3740.0, 1660.0), (1080.0, 1660.0)]),
    ("e_c6_c4", "node_c6", "node_c4", "指数退避重试 (backoff=2.0)", "#4F46E5", False, 1.8, "#1E3A8A", "exitX=0.5;exitY=1;entryX=0.5;entryY=1;", [(3860.0, 1690.0), (2532.0, 1690.0)]),
    ("e_c2_d10", "node_c2", "node_d10", "POST 创建查询 Session", "#0F172A", False, 1.8, "#1E3A8A", "exitX=0.5;exitY=1;entryX=0.3;entryY=0;", [(1204.0, 1750.0), (3080.0, 1750.0)]),
    ("e_c4_d10", "node_c4", "node_d10", "GET 分页拉取星表流", "#0F172A", False, 1.8, "#1E3A8A", "exitX=0.5;exitY=1;entryX=0.6;entryY=0;", [(2532.0, 1780.0), (3250.0, 1780.0)]),
    ("e_c4_d11", "node_c4", "node_d11", "TAP 历史兼容通道", "#64748B", True, 1.8, "#1E3A8A", "exitX=0.7;exitY=1;entryX=0.5;entryY=0;", [(2650.0, 1800.0), (3860.0, 1800.0)]),
    ("e_d10_d1", "node_d10", "node_d1", "std 标准星", "#4F46E5", False, 1.8, "#1E3A8A", "exitX=0.2;exitY=0;entryX=0.5;entryY=1;", [(3020.0, 2100.0), (610.0, 2100.0)]),
    ("e_d10_d2", "node_d10", "node_d2", "ps1 全天", "#4F46E5", False, 1.8, "#1E3A8A", "exitX=0.3;exitY=0;entryX=0.5;entryY=1;", [(3080.0, 2115.0), (1405.0, 2115.0)]),
    ("e_d10_d3", "node_d10", "node_d3", "stripe82 深场", "#4F46E5", False, 1.8, "#1E3A8A", "exitX=0.4;exitY=0;entryX=0.5;entryY=1;", [(3140.0, 2130.0), (2200.0, 2130.0)]),
    ("e_d10_d4", "node_d10", "node_d4", "gaia_dr3 基准", "#4F46E5", False, 1.8, "#1E3A8A", "exitX=0.5;exitY=0;entryX=0.5;entryY=1;", [(3200.0, 2145.0), (2995.0, 2145.0)]),
    ("e_d10_d5", "node_d10", "node_d5", "jplus 12色", "#4F46E5", False, 1.8, "#1E3A8A", "exitX=0.7;exitY=0;entryX=0.5;entryY=1;", [(3320.0, 2130.0), (3790.0, 2130.0)]),
    ("e_d10_d6", "node_d10", "node_d6", "smss 南天", "#4F46E5", False, 1.8, "#1E3A8A", "exitX=0;exitY=0.5;entryX=1;entryY=0.5;", [(2911.0, 2215.0), (825.0, 2215.0)]),
    ("e_d10_d7", "node_d10", "node_d7", "landolt 标准", "#4F46E5", False, 1.8, "#1E3A8A", "exitX=0;exitY=0.4;entryX=1;entryY=0.4;", None),
    ("e_d10_d8", "node_d10", "node_d8", "uss 超深", "#4F46E5", False, 1.8, "#1E3A8A", "exitX=0;exitY=0.6;entryX=1;entryY=0.6;", None),
    ("e_d10_d9", "node_d10", "node_d9", "splus 12色", "#4F46E5", False, 1.8, "#1E3A8A", "exitX=0;exitY=0.8;entryX=1;entryY=0.8;", None),
    ("e_c4_e1", "node_c4", "node_e1", "数据流清洗注入 (保留负数Dec)", "#DC2626", False, 1.8, "#1E3A8A", "exitX=0.2;exitY=1;entryX=0.5;entryY=0;", [(2360.0, 2400.0), (540.0, 2400.0)]),
    ("e_b3_e2", "node_b3", "node_e2", "多坐标批处理逐点隔离", "#EA580C", False, 1.8, "#1E3A8A", "exitX=0.2;exitY=1;entryX=0.5;entryY=0;", [(1698.0, 2420.0), (1204.0, 2420.0)]),
    ("e_e1_e3", "node_e1", "node_e3", "清洗后数据原子落盘 (os.replace)", "#9333EA", False, 1.8, "#1E3A8A", "exitX=1;exitY=0.4;entryX=0;entryY=0.4;", None),
    ("e_e2_e3", "node_e2", "node_e3", "汇聚匹配结果与不可变证据", "#9333EA", False, 1.8, "#1E3A8A", "exitX=1;exitY=0.6;entryX=0;entryY=0.6;", None),
    ("e_b3_e4", "node_b3", "node_e4", "超出 In-Scope 主动委派", "#4F46E5", False, 1.8, "#1E3A8A", "exitX=0.8;exitY=1;entryX=0.5;entryY=0;", [(2038.0, 2440.0), (2532.0, 2440.0)]),
    ("e_b6_e5", "node_b6", "node_e5", "异常现场存证打包 (decision_envelope)", "#EA580C", True, 1.8, "#1E3A8A", "exitX=0.5;exitY=1;entryX=0.5;entryY=0;", [(3860.0, 2430.0), (3196.0, 2430.0)]),
    ("e_e5_e6", "node_e5", "node_e6", "质检阻断触发闭环反馈", "#DC2626", True, 1.8, "#1E3A8A", "exitX=1;exitY=0.5;entryX=0;entryY=0.5;", None),
    ("e_e6_a1", "node_e6", "node_a1", "【闭环反馈回路】重观测决策与策略参数动态调整回写 (11-closed-loop)", "#9333EA", True, 2.4, "#581C87", "exitX=1;exitY=0.5;entryX=0;entryY=0.3;", [(4145.0, 2710.0), (4300.0, 2710.0), (4300.0, 105.0), (100.0, 105.0), (100.0, 300.0), (255.0, 300.0)]),
    # 闭环走廊内部推进 (虚线: 回退路径不是主数据流); 走廊的"返回"段不另画边 —
    # 外环 e_e6_a1 就是返回走线, 容器标题里已写明, 再画一条会与它视觉打架
    ("e_loop_1", "loop_c1", "loop_c2", "", "#DC2626", True, 1.8, "#1E3A8A", "exitX=1;exitY=0.5;entryX=0;entryY=0.5;", None),
    ("e_loop_2", "loop_c2", "loop_c3", "", "#EA580C", True, 1.8, "#1E3A8A", "exitX=1;exitY=0.5;entryX=0;entryY=0.5;", None),
    ("e_loop_3", "loop_c3", "loop_c4", "", "#9333EA", True, 1.8, "#1E3A8A", "exitX=1;exitY=0.5;entryX=0;entryY=0.5;", None),
]

# =====================================================================
# ARCHITECTURE 组: 2400 宽 4 页架构图 (每页一个 ARCHITECTURE_Pn 有序表)
# =====================================================================
# 三域导航标签 (Page 2/3/4 顶部导航条按序渲染, active 索引高亮)。
# 顺序即架构总览里三个泳道的左右顺序
ARCHITECTURE_DOMAINS = [  # 三域导航标签, Page 2/3/4 顶部导航条按序渲染
    "① 主理能力域",  # 对应 Page 2: 立场/能力组件/委派路由
    "② 五状态机执行链",  # 对应 Page 3: 五态卡 + 阶段数据流 + 双门槛
    "③ 降级 · 错误码 · 证据",  # 对应 Page 4: 降级协议/错误码/证据存证
]

# 页级元素有序表: 一个页面的全部导航条/容器/节点/连线按原生成代码的添加
# 顺序排列 (原循环已物化为显式行)。行首标签: V=三域导航条, C=容器,
# N=节点, E=连线, 四种行的字段依次为 ——
#   V: (标签, active 域索引 0/1/2)   —— 导航条纵坐标 y=115 三页一致, 在生成器
#   C: (标签, 容器 id, 标题, x, y, w, h)
#   N: (标签, 节点 id, x, y, w, h, 样式规格, HTML)
#      样式规格 = (色键, align, valign, bold); 色键 "title"/"rhombus" 是
#      哨兵, 分别映射生成器的 TITLE_STYLE / rhombus_style(), 其余色键走 st()
#   E: (标签, 连线 id, 源 id, 目标 id, 标签, 色, 字色, 锚点后缀)
# Page 1 架构总览: 总标题+使命横幅 -> 输入/交付 -> 三域容器 -> 域间连线 -> 图例与约束
ARCHITECTURE_P1 = [  # Page 1 架构总览: 行序即 .drawio 里 <mxCell> 的添加顺序, 调序即改图
    ("N", "p1_title", 300, 30, 1800, 75, ('title', '', '', False), "<b>【astro-best 架构总览】BEST 数据源主理 · NADC BEST 查询/下载/匹配</b><br/><span style='font-size:12px;color:#94A3B8;'>架构编号: astro.best-collection &nbsp;|&nbsp; 管线阶段: collection &nbsp;|&nbsp; 定位: data-source 主理 &nbsp;|&nbsp; 强度等级见 skill registry &nbsp;|&nbsp; 变更史见 CHANGELOG</span>"),
    ("N", "p1_mission", 300, 120, 1800, 85, ('banner', 'left', 'top', False), "<b>【核心使命】</b> 作为 BEST 数据库的唯一数据源主理方（全 ecosystem 仅本 skill 能访问 nadc.china-vo.org/data/best），在 NADC BEST REST 端点上完成 <b>两阶段异步查询 → 流式下载 → 校验和门禁</b>，交付可追溯的采集结果。<br/><b>【委派边界】</b> 通用星表检索/交叉匹配主理转 astro-catalog，数据清洗转 astro-clean；<b>BEST 自身数据的查询与批量匹配不委派</b>（他 skill 无 BEST 端点）；公开函数行为变更必须连带回归测试，不允许行为漂移。"),
    ("N", "p1_in", 1000, 245, 400, 70, ('cyan', 'center', 'middle', True), "<b>输入入口</b><br/><span style='font-size:11px;'>BestQuery 信封 (sql, token)</span>"),
    ("N", "p1_out", 1000, 990, 400, 70, ('purple', 'center', 'middle', True), "<b>交付产物</b><br/><span style='font-size:11px;'>结果集 + 查询审计 + 血缘头</span>"),
    ("C", "p1_domA", "① 主理能力域", 100, 360, 680, 580),  # 三域容器统一 680x580, 左右各留 80 间隙
    ("C", "p1_domB", "② 五状态机执行链", 860, 360, 680, 580),  # 容器 x 由左域宽 680 + 间隙 80 推出
    ("C", "p1_domC", "③ 降级 · 错误码 · 证据", 1620, 360, 680, 580),  # 第三域贴右边界: 1620+680=2300
    ("N", "p1_A1", 125, 412, 630, 95, ('blue', 'left', 'top', False), "<b>【主理立场】</b><br/><span style='font-size:11.5px;'>HTTP 200 + 校验和一致才叫“下载完成”；凭据缺失即 not_configured；mock 与真网区别显式声明。</span>"),
    ("N", "p1_A2", 125, 522, 630, 150, ('blue', 'left', 'top', False), "<b>【能力清单 · 5 项】</b><br/><span style='font-size:11.5px;'>1. 两阶段异步查询客户端（认证 + 建 SQL + 分页拉取）<br/>2. 查询构造与流式下载（校验和 + 断点续传）<br/>3. 匹配与光变（BEST 自身数据保留，通用源委派）<br/>4. 编排与质量门控 &nbsp;·&nbsp; 5. 采集脚本与 CSV 公式注入防御</span>"),
    ("N", "p1_A3", 125, 687, 630, 115, ('indigo', 'left', 'top', False), "<b>【委派路由 · 3 条】</b><br/><span style='font-size:11.5px;'>交叉匹配 → 检索 / 交叉匹配主理 &nbsp;·&nbsp; 数据清洗 → 校准 / 剔除主理<br/>自身 REST 异步客户端 <b>不委派</b>（外部数据源驱动，本 skill 是唯一主理）</span>"),
    ("N", "p1_A4", 125, 817, 630, 75, ('neutral', 'left', 'top', False), "<b>【主理声明】</b> <span style='font-size:11.5px;'>BEST 自身数据查询/匹配归本 skill；通用检索与清洗委派。</span>"),
    ("N", "p1_B1", 885, 412, 630, 95, ('green', 'left', 'top', False), "<b>【五状态机】</b><br/><span style='font-size:11.5px;'>INTAKE → VALIDATE → EXECUTE → GATE → EMIT<br/>每态含进入条件 / 离开条件 / 失败出口</span>"),
    ("N", "p1_B2", 885, 522, 630, 140, ('neutral', 'left', 'top', False), "<b>【阶段数据流 · 4 段】</b><br/><span style='font-size:11.5px;'>① 查询信封 → 语法与速率校验<br/>② 两阶段异步（建 SQL → 取查询标识 → 分页拉取）<br/>③ 流式下载（校验和 + 断点续传）<br/>④ 原子落盘 + 查询审计</span>"),
    ("N", "p1_B3", 885, 677, 630, 110, ('amber', 'left', 'top', False), "<b>【阻断性门禁 · 双门槛】</b><br/><span style='font-size:11.5px;'>① http_status == 200 &nbsp;·&nbsp; ② checksum_match == True<br/>任一失败 → handoff.status = blocked；门禁不因降级放松</span>"),
    ("N", "p1_B4", 885, 802, 630, 115, ('cyan', 'left', 'top', False), "<b>【双态信封】</b><br/><span style='font-size:11.5px;'>data 信封（产物 / 指标 / 数据指纹 / 血缘）<br/>decision 信封（科学评估 / 检查点 / 人工复核）<br/>L1 确定性数据流：0% LLM</span>"),
    ("N", "p1_C1", 1645, 412, 630, 135, ('red', 'left', 'top', False), "<b>【优雅降级 · 6 条协议】</b><br/><span style='font-size:11.5px;'>网络不可达 / 认证失败 / 限流与 5xx /<br/>内容漂移 / 完整性失败 / 下游委派回退<br/>降级必须留痕（WARN 注记 + status 字段）</span>"),
    ("N", "p1_C2", 1645, 562, 630, 115, ('red', 'left', 'top', False), "<b>【错误码 · Fail-Closed】</b><br/><span style='font-size:11.5px;'>输入非法 → 直接阻断，不进入执行<br/>门禁未达 → blocked &nbsp;·&nbsp; 委派失败 → 优雅降级并标注<br/>未分类异常 → 收敛并保留完整回溯</span>"),
    ("N", "p1_C3", 1645, 692, 630, 130, ('purple', 'left', 'top', False), "<b>【不可变证据 · 4 项】</b><br/><span style='font-size:11.5px;'>结果集（data / status） &nbsp;·&nbsp; 查询审计<br/>血缘头（完整度门禁 = 1.0） &nbsp;·&nbsp; 光变产品<br/>量纲随字段走；时间一律 UTC ISO8601</span>"),
    ("N", "p1_C4", 1645, 837, 630, 75, ('neutral', 'left', 'top', False), "<b>【支撑面】</b> <span style='font-size:11.5px;'>溯源 RAG + 算法白盒 + 质量门禁 + 治理强度元数据</span>"),
    ("E", "p1_e_AB", "p1_domA", "p1_domB", "存量能力被编排", "#4F46E5", "#3730A3", "exitX=1;exitY=0.28;entryX=0;entryY=0.28;"),  # 域 A→B: 显式锚点锁 y=0.28
    ("E", "p1_e_BA", "p1_domB", "p1_domA", "审计 · 证据回写", "#0891B2", "#155E75", "exitX=0;exitY=0.62;entryX=1;entryY=0.62;"),  # 反向箭头 = 审计回写
    ("E", "p1_e_BC", "p1_domB", "p1_domC", "门禁 · 异常事件", "#EA580C", "#9A3412", "exitX=1;exitY=0.28;entryX=0;entryY=0.28;"),  # 门禁不过才流向降级域
    ("E", "p1_e_CB", "p1_domC", "p1_domB", "降级 · 恢复路径", "#DC2626", "#991B1B", "exitX=0;exitY=0.62;entryX=1;entryY=0.62;"),  # 降级后回到执行域继续
    ("E", "p1_e_in", "p1_in", "p1_domB", "", "#0891B2", "#155E75", "exitX=0.5;exitY=1;entryX=0.5;entryY=0;"),  # 输入入口自上而下入 B 域
    ("E", "p1_e_out", "p1_domB", "p1_out", "", "#9333EA", "#581C87", "exitX=0.5;exitY=1;entryX=0.5;entryY=0;"),  # 交付产物自 B 域向下出
    ("N", "p1_legend", 100, 1110, 1080, 190, ('neutral', 'left', 'top', False), "<b>【图例 · 语义色】</b><br/><span style='font-size:11.5px;'><b>蓝</b> = 兼容能力 / 立场 &nbsp;·&nbsp; <b>靛</b> = 委派路由 &nbsp;·&nbsp; <b>绿</b> = 状态与执行 &nbsp;·&nbsp; <b>橙</b> = 阻断门禁<br/><b>红</b> = 降级与错误码 &nbsp;·&nbsp; <b>紫</b> = 证据产物 &nbsp;·&nbsp; <b>青</b> = 信封与入口 &nbsp;·&nbsp; <b>灰</b> = 中性说明<br/>连线: 实线 = 数据 / 能力流向 &nbsp;·&nbsp; 反向箭头 = 审计回写与降级恢复</span>"),
    ("N", "p1_constraints", 1220, 1110, 1080, 190, ('amber', 'left', 'top', False), "<b>【三条不可让步的约束】</b><br/><span style='font-size:11.5px;'>1. <b>双门槛不放水</b> — http_status == 200 且 checksum_match == True，半成品绝不进入下游。<br/>2. <b>越权即拒</b> — 执行态禁止旁路重实现 canonical 能力；越界能力的元决策与执行一律委派 canonical skill。<br/>3. <b>降级必留痕</b> — 任何降级都要产生 WARN 注记与 status 字段，不静默吞异常、不伪造成功。</span>"),
]

# Page 2 域①: 立场横幅 -> 左右两栏容器 -> 能力组件卡 5 张 (y 步进 158) -> 委派路由表 3 行 (y 步进 164) -> 定位声明 -> 边界约束
ARCHITECTURE_P2 = [  # Page 2 域①: 立场横幅 -> 左右两栏 -> 能力卡 5 张 -> 委派表 3 行
    ("N", "p2_title", 250, 30, 1900, 70, ('title', '', '', False), "<b>【域 ①】主理能力域与委派路由</b><br/><span style='font-size:12px;color:#94A3B8;'>astro-best 是 BEST 数据源主理 &nbsp;|&nbsp; 唯一能访问 BEST 端点 &nbsp;|&nbsp; 交付物 / 边界判定 / 委派路由</span>"),
    ("V", 0),  # 三域导航条: active=0 高亮"① 主理能力域"
    ("N", "p2_stance", 100, 180, 2200, 105, ('banner', 'left', 'top', False), "<b>【主理立场】</b> 本域是 skill 的对外能力面：主理 BEST 自身数据的查询与批量匹配，把不该由本 skill 承担的职责显式委派出去。<br/><b>信条:</b> HTTP 200 + 校验和一致才叫“下载完成”；凭据没有就 not_configured。&nbsp;<b>诚实:</b> mock 夹具与真网区别显式声明，不伪造提交成功。&nbsp;<b>门禁:</b> 双门槛判定，降级不放松。"),
    ("C", "p2_box_l", "【能力组件 · 职责与边界】", 100, 305, 1080, 915),  # 左栏 1080 宽: 组件卡 y 步进 158
    ("C", "p2_box_r", "【委派路由 · 主理定位声明】", 1220, 305, 1080, 915),  # 右栏 x=1220: 与左栏留 40 间隙
    ("N", "p2_lbl_c", 125, 357, 1030, 36, ('label', 'center', 'middle', False), "<b>5 个能力组件（提供什么 / 边界在哪）</b>"),
    ("N", "p2_c0", 125, 411, 1030, 144, ('blue', 'left', 'top', False), "<b>◆ 两阶段异步查询客户端</b><br/><span style='font-size:11.5px;'><b>提供:</b> 认证（会话 + CSRF）与两阶段异步查询：POST 检索表单 → 服务端建 SQL → 返回查询标识 → 分页 GET。</span><br/><span style='font-size:11px;color:#64748B;'><b>边界:</b> 凭据只读环境变量；代码零凭据字面量；不缓存用户凭据。</span><br/><span style='font-size:11px;color:#1D4ED8;'><b>关键点:</b> 两阶段设计避免长查询阻塞连接；分页拉取可中断续做。</span>"),
    ("N", "p2_c1", 125, 569, 1030, 144, ('blue', 'left', 'top', False), "<b>◆ 查询构造与流式下载</b><br/><span style='font-size:11.5px;'><b>提供:</b> 查询信封（BestQuery / BestQueryResult）与流式下载：SHA-256 校验和 + 断点续传。</span><br/><span style='font-size:11px;color:#64748B;'><b>边界:</b> 约束构造集中收敛；字段白名单统一维护，应对上游表单演进。</span><br/><span style='font-size:11px;color:#1D4ED8;'><b>关键点:</b> 校验和逐块比对；断点续传应对大区域下载与网络抖动。</span>"),
    ("N", "p2_c2", 125, 727, 1030, 144, ('blue', 'left', 'top', False), "<b>◆ 匹配与光变（BEST 自身数据）</b><br/><span style='font-size:11.5px;'><b>提供:</b> 坐标匹配与光变提取，BEST 自身数据的批量匹配保留在本地。</span><br/><span style='font-size:11px;color:#64748B;'><b>边界:</b> 通用源交叉匹配一律委派 astro-catalog，不在本地拼凑匹配结果。</span><br/><span style='font-size:11px;color:#1D4ED8;'><b>关键点:</b> 球面角距匹配；模糊命中必须标记为待判，而非强制合并。</span>"),
    ("N", "p2_c3", 125, 885, 1030, 144, ('blue', 'left', 'top', False), "<b>◆ 编排与质量门控</b><br/><span style='font-size:11.5px;'><b>提供:</b> 工作流编排与质量门控（SNR / FWHM / class_star），并提供对外门面客户端。</span><br/><span style='font-size:11px;color:#64748B;'><b>边界:</b> REST 默认端点与 TAP 门面显式区分，杜绝“同一客户端两个端点”的隐式漂移。</span><br/><span style='font-size:11px;color:#1D4ED8;'><b>关键点:</b> 门控默认阈值：信噪比 5.0、半高宽 5.0、分类星概率 0.8。</span>"),
    ("N", "p2_c4", 125, 1043, 1030, 144, ('blue', 'left', 'top', False), "<b>◆ 采集脚本与 CSV 安全</b><br/><span style='font-size:11.5px;'><b>提供:</b> 锥形检索、检索语句语法校验、批量交叉匹配（单点失败隔离，不中断批次）。</span><br/><span style='font-size:11px;color:#64748B;'><b>边界:</b> CSV 公式注入防御：以 = + - @ 开头的单元格转义为文本。</span><br/><span style='font-size:11px;color:#1D4ED8;'><b>关键点:</b> 批量逐点隔离：单点异常只影响该点，不拖垮整批作业。</span>"),
    ("N", "p2_lbl_r", 1245, 357, 1030, 36, ('label', 'center', 'middle', False), "<b>委派路由表（越界能力 → 承接方 → 理由）</b>"),
    ("N", "p2_r0", 1245, 411, 1030, 150, ('indigo', 'left', 'top', False), "<b>◆ 越界能力: 通用星表检索与坐标交叉匹配</b><br/><span style='font-size:11.5px;'>→ 承接方: <code>astro-catalog</code></span><br/><span style='font-size:11px;color:#4338CA;'><b>理由:</b> 检索 / 交叉匹配主理（球面 KD-Tree 锥搜）</span><br/><span style='font-size:11px;color:#4338CA;'><b>说明:</b> SIMBAD/VizieR/Gaia/TNS 等通用源转投；BEST 自身数据的批量匹配仍归本 skill。</span>"),
    ("N", "p2_r1", 1245, 575, 1030, 150, ('indigo', 'left', 'top', False), "<b>◆ 越界能力: 原始数据清洗</b><br/><span style='font-size:11.5px;'>→ 承接方: <code>astro-clean</code></span><br/><span style='font-size:11px;color:#4338CA;'><b>理由:</b> 2D 校准 / 剔除主理</span><br/><span style='font-size:11px;color:#4338CA;'><b>说明:</b> CCD/图像归约转投。</span>"),
    ("N", "p2_r2", 1245, 739, 1030, 150, ('indigo', 'left', 'top', False), "<b>◆ 越界能力: NADC BEST 两阶段异步客户端</b><br/><span style='font-size:11.5px;'>→ 承接方: <code>astro-best（不委派）</code></span><br/><span style='font-size:11px;color:#4338CA;'><b>理由:</b> 外部数据源驱动，本 skill 是唯一主理</span><br/><span style='font-size:11px;color:#4338CA;'><b>说明:</b> 声明行：全 ecosystem 仅本 skill 能访问 BEST 端点，绝不外派。</span>"),
    ("N", "p2_lbl_d", 1245, 911, 1030, 36, ('label', 'center', 'middle', False), "<b>主理定位声明（BEST 数据源）</b>"),
    ("N", "p2_decl", 1245, 965, 1030, 225, ('neutral', 'left', 'top', False), "<b>【主理定位声明】</b><br/><span style='font-size:11.5px;'>• 本域约束“BEST 自身数据能力保持可用 + 委派路由正确”。<br/>• BEST 数据查询与批量匹配是本 skill 的 PRIMARY 场景；通用检索与数据清洗委派 canonical skill。<br/>• 执行态禁止旁路重实现 canonical 能力。<br/>• 公开函数行为变更必须连带回归测试，不允许行为漂移。<br/>• 存量承诺：既有测试全绿，导入路径不增不减。</span>"),
    ("N", "p2_bound", 100, 1250, 2200, 110, ('red', 'left', 'top', False), "<b>【边界约束 · 越权即拒】</b><br/><span style='font-size:11.5px;'>• 在执行态旁路重实现 canonical 能力 → 直接拒绝。&nbsp;• 不在未声明情况下扩大搜索半径，不把兼容性猜测写成事实。&nbsp;• 凭据只在环境变量，路径锚定校验，无上溯逃逸。</span>"),
]

# Page 3 域②: 五状态机横排 5 卡 (x 步进 450) + Pass 链 4 边 -> 阶段数据流 4 段 (y 步进 88) + 传递边 3 条 -> 双菱形门禁 -> 双态信封 -> 失败隔离说明
ARCHITECTURE_P3 = [  # Page 3 域②: 五态横排 (x 步进 450) -> 数据流 4 段 -> 双菱形门禁
    ("N", "p3_title", 250, 30, 1900, 70, ('title', '', '', False), "<b>【域 ②】五状态机执行链 · 双态信封 · 阻断门禁</b><br/><span style='font-size:12px;color:#94A3B8;'>astro-best 是 BEST 数据源主理 &nbsp;|&nbsp; INTAKE → VALIDATE → EXECUTE → GATE → EMIT &nbsp;|&nbsp; 状态迁移 / 数据流 / 门禁</span>"),
    ("V", 1),  # 三域导航条: active=1 高亮"② 五状态机执行链"
    ("N", "p3_lbl_sm", 100, 180, 2200, 36, ('label', 'center', 'middle', False), "<b>运行态五状态机（每态含职责 / 进入 / 离开 / 失败出口）</b>"),
    ("N", "p3_s0", 100, 236, 400, 140, ('green', 'left', 'top', False), "<b>① INTAKE 接收</b><br/><span style='font-size:11px;color:#334155;'><b>职责:</b> 接收输入契约信封<br/><b>进入:</b> 上游产物到达<br/><b>离开:</b> 数据指纹齐备</span><br/><span style='font-size:10.5px;color:#B91C1C;'><b>失败出口:</b> 拒收（信封为空）</span>"),
    ("N", "p3_s1", 550, 236, 400, 140, ('green', 'left', 'top', False), "<b>② VALIDATE 校验</b><br/><span style='font-size:11px;color:#334155;'><b>职责:</b> 输入契约 Schema 校验<br/><b>进入:</b> INTAKE 通过<br/><b>离开:</b> Schema 零错误</span><br/><span style='font-size:10.5px;color:#B91C1C;'><b>失败出口:</b> 转 needs_review + 错误码</span>"),
    ("N", "p3_s2", 1000, 236, 400, 140, ('green', 'left', 'top', False), "<b>③ EXECUTE 执行</b><br/><span style='font-size:11px;color:#334155;'><b>职责:</b> 按场景路由执行（惰性加载）<br/><b>进入:</b> VALIDATE 通过<br/><b>离开:</b> 全部条目完成 / 隔离</span><br/><span style='font-size:10.5px;color:#B91C1C;'><b>失败出口:</b> 逐条隔离，不中断批次</span>"),
    ("N", "p3_s3", 1450, 236, 400, 140, ('green', 'left', 'top', False), "<b>④ GATE 门禁</b><br/><span style='font-size:11px;color:#334155;'><b>职责:</b> 阻断性质量门禁判定<br/><b>进入:</b> EXECUTE 完成<br/><b>离开:</b> accepted / rejected 落定</span><br/><span style='font-size:10.5px;color:#B91C1C;'><b>失败出口:</b> 门禁不足 → needs_review</span>"),
    ("N", "p3_s4", 1900, 236, 400, 140, ('green', 'left', 'top', False), "<b>⑤ EMIT 落盘</b><br/><span style='font-size:11px;color:#334155;'><b>职责:</b> 原子写输出契约产物<br/><b>进入:</b> GATE 完成<br/><b>离开:</b> 成功落盘</span><br/><span style='font-size:10.5px;color:#B91C1C;'><b>失败出口:</b> 抛出，绝无半写</span>"),
    ("E", "p3_e_s0", "p3_s0", "p3_s1", "Pass", "#059669", "#047857", "exitX=1;exitY=0.5;entryX=0;entryY=0.5;"),  # Pass 链: 五态横排的唯一走线
    ("E", "p3_e_s1", "p3_s1", "p3_s2", "Pass", "#059669", "#047857", "exitX=1;exitY=0.5;entryX=0;entryY=0.5;"),  # 同一 y 锚点, 保证走线纯正交
    ("E", "p3_e_s2", "p3_s2", "p3_s3", "Pass", "#059669", "#047857", "exitX=1;exitY=0.5;entryX=0;entryY=0.5;"),  # VALIDATE→EXECUTE 同样锁 0.5
    ("E", "p3_e_s3", "p3_s3", "p3_s4", "Pass", "#059669", "#047857", "exitX=1;exitY=0.5;entryX=0;entryY=0.5;"),  # GATE→EMIT 是最后一条 Pass
    ("N", "p3_lbl_flow", 100, 404, 2200, 36, ('label', 'center', 'middle', False), "<b>阶段数据流 · 交互负载与超参</b>"),
    ("N", "p3_f0", 100, 462, 2200, 80, ('neutral', 'left', 'top', False), "<b>【阶段数据流】</b> ① 查询信封 → 语法与速率校验<br/><span style='font-size:11.5px;color:#2563EB;'><b>Payload:</b> 载荷: 检索语句、坐标与范围、字段需求；速率窗口与限速约束。</span><br/><span style='font-size:11px;color:#64748B;'>门禁: 语法零错误 + 速率窗口未超限。</span>"),
    ("N", "p3_f1", 100, 550, 2200, 80, ('neutral', 'left', 'top', False), "<b>【阶段数据流】</b> ② 两阶段异步（第一阶段：建 SQL）<br/><span style='font-size:11.5px;color:#2563EB;'><b>Payload:</b> 载荷: POST 检索表单 → 服务端建立查询 → 返回含查询标识的响应。</span><br/><span style='font-size:11px;color:#64748B;'>超参: 重试 3 次 / 请求超时 120s / 退避 2.0（429 与 5xx）。</span>"),
    ("N", "p3_f2", 100, 638, 2200, 80, ('neutral', 'left', 'top', False), "<b>【阶段数据流】</b> ③ 两阶段异步（第二阶段：分页拉取 + 流式下载）<br/><span style='font-size:11.5px;color:#2563EB;'><b>Payload:</b> 载荷: 分页 JSON/CSV + SHA-256 校验和 + 断点续传。</span><br/><span style='font-size:11px;color:#64748B;'>超参: 单页拉取上限 50000 行 / 校验和逐块比对。</span>"),
    ("N", "p3_f3", 100, 726, 2200, 80, ('neutral', 'left', 'top', False), "<b>【阶段数据流】</b> ④ 门禁判定 → 原子落盘<br/><span style='font-size:11.5px;color:#2563EB;'><b>Payload:</b> 载荷: 结果集（data / status）+ 查询审计（HTTP 状态 / 校验和 / 查询标识）。</span><br/><span style='font-size:11px;color:#64748B;'>落盘: 原子写（临时文件 + 原子替换），绝无半写。</span>"),
    ("E", "p3_e_f0", "p3_f0", "p3_f1", "", "#334155", "#0F172A", ""),
    ("E", "p3_e_f1", "p3_f1", "p3_f2", "", "#334155", "#0F172A", ""),
    ("E", "p3_e_f2", "p3_f2", "p3_f3", "", "#334155", "#0F172A", ""),
    ("N", "p3_lbl_gate", 100, 834, 2200, 36, ('label', 'center', 'middle', False), "<b>阻断性质量门禁（双门槛 · 任一失败 → handoff.status = blocked）</b>"),
    ("N", "p3_g0", 340, 890, 600, 200, ('rhombus', '', '', False), "<b>门禁 ①</b><br/>http_status == 200<br/><span style='font-size:10.5px;'>量纲: count</span>"),
    ("N", "p3_g1", 1460, 890, 600, 200, ('rhombus', '', '', False), "<b>门禁 ②</b><br/>checksum_match == True<br/><span style='font-size:10.5px;'>量纲: bool</span>"),
    ("N", "p3_gate_note", 100, 1110, 2200, 85, ('amber', 'left', 'top', False), "<b>【门禁语义】</b> 任一失败 → <code>handoff.status = blocked</code>，记录失败门禁项；降级必须产生 WARN 级注记并落到经验教训锚点。<br/><span style='font-size:11.5px;'><b>关键约束:</b> 门禁不因降级放松；半成品绝不进入下游；门禁表与对外声明保持一致。</span>"),
    ("N", "p3_lbl_env", 100, 1223, 2200, 36, ('label', 'center', 'middle', False), "<b>跨节点双态信封（data / decision）</b>"),
    ("N", "p3_env_data", 100, 1279, 1080, 120, ('cyan', 'left', 'top', False), "<b>◆ data 信封</b><br/><span style='font-size:11.5px;'>管线标识 / 阶段 = collection / UTC 时间戳 &nbsp;·&nbsp; 产物清单 + 指标（data, status）<br/><b>数据指纹:</b> 由管线标识 + 阶段 + 产物 + 指标计算，输入路径可复核<br/><b>血缘:</b> 会话标识 + 端点 + 查询标识</span>"),
    ("N", "p3_env_dec", 1220, 1279, 1080, 120, ('cyan', 'left', 'top', False), "<b>◆ decision 信封</b><br/><span style='font-size:11.5px;'>工作流标识 + 检查点门禁名 &nbsp;·&nbsp; <b>检查点状态:</b> 待人工确认 / 失败 / 豁免<br/><b>人工复核:</b> 复核人 / 决定（批准 · 驳回 · 调整参数 · 待定）/ 备注 / UTC 时间戳<br/><span style='color:#0F766E;'><b>注:</b> L1 确定性数据流 0% LLM → 不产出 decision 信封</span></span>"),
    ("E", "p3_e_env", "p3_env_data", "p3_env_dec", "门控 / 审计", "#0891B2", "#155E75", "exitX=1;exitY=0.5;entryX=0;entryY=0.5;"),
    ("N", "p3_lbl_tr", 100, 1427, 2200, 36, ('label', 'center', 'middle', False), "<b>失败隔离与降级留痕</b>"),
    ("N", "p3_tr", 100, 1483, 2200, 110, ('neutral', 'left', 'top', False), "<span style='font-size:11.5px;'><b>失败隔离:</b> 对每条目（帧 / 条目 / 查询）独立捕获异常 — 单点异常进入该条目的错误列表并置为 failed，不中断整批；全批失败则整体转 needs_review 并携带错误清单。<br/><b>降级留痕:</b> 任何降级都必须产生 WARN 级注记并落到经验教训锚点，供后续复盘。<br/><b>迁移一致性:</b> 五状态迁移条件与架构规范逐条对应，状态迁移与门禁判定全程可回放。</span>"),
]

# Page 4 域③: 左右两栏容器 -> 降级协议 3 卡 (y 步进 124) -> 错误码契约 -> 不可让步原则 -> 不可变证据 4 项 (y 步进 96) -> 支撑面 -> 完成自检
ARCHITECTURE_P4 = [  # Page 4 域③: 降级 3 卡 (y 步进 124) -> 错误码 -> 证据 4 项 (y 步进 96)
    ("N", "p4_title", 250, 30, 1900, 70, ('title', '', '', False), "<b>【域 ③】优雅降级 · 错误码 · 证据存证与自检</b><br/><span style='font-size:12px;color:#94A3B8;'>astro-best 是 BEST 数据源主理 &nbsp;|&nbsp; 断点续传 / Fail-Closed / 门禁证据 / 血缘</span>"),
    ("V", 2),  # 三域导航条: active=2 高亮"③ 降级 · 错误码 · 证据"
    ("C", "p4_box_l", "【优雅降级协议与错误码】", 100, 180, 1080, 968),  # 左栏装降级/错误码/原则
    ("C", "p4_box_r", "【证据存证 · 支撑面 · 完成自检】", 1220, 180, 1080, 968),  # 右栏装证据/支撑面/自检
    ("N", "p4_lbl_fb", 125, 232, 1030, 36, ('label', 'center', 'middle', False), "<b>优雅降级协议（降级必须留痕）</b>"),
    ("N", "p4_fb0", 125, 286, 1030, 110, ('red', 'left', 'top', False), "<b>网络不可达 &nbsp;·&nbsp; 认证失败</b><br/><span style='font-size:11px;color:#991B1B;'><b>触发:</b> 连接失败 / DNS 失败；环境凭据缺失；登录被重定向回登录页。</span><br/><span style='font-size:11px;color:#065F46;'><b>处置:</b> 不伪造结果集，空数据与失败严格区分；重试 ≤1 次，再失败终止会话并提示人工核对凭据。</span><br/><span style='font-size:11px;color:#7F1D1D;'><b>标记: not_configured / auth_failed</b></span>"),
    ("N", "p4_fb1", 125, 410, 1030, 110, ('red', 'left', 'top', False), "<b>限流与 5xx &nbsp;·&nbsp; 内容漂移</b><br/><span style='font-size:11px;color:#991B1B;'><b>触发:</b> 超出限流 → 标记为限流；响应类型与预期不符 → 解析失败。</span><br/><span style='font-size:11px;color:#065F46;'><b>处置:</b> 指数退避至多 3 次；保留原始文本进错误列表，不解析不产出；批量作业改约窗口。</span><br/><span style='font-size:11px;color:#7F1D1D;'><b>标记: rate_limited / parse_failed</b></span>"),
    ("N", "p4_fb2", 125, 534, 1030, 110, ('red', 'left', 'top', False), "<b>完整性失败 &nbsp;·&nbsp; 下游委派回退</b><br/><span style='font-size:11px;color:#991B1B;'><b>触发:</b> 校验和重读不一致；上游返回缺失星表导致匹配无法完成。</span><br/><span style='font-size:11px;color:#065F46;'><b>处置:</b> 删除半成品并重试 1 次，再失败标记校验和不匹配；不在本地拼凑匹配，改为建议下游主理。</span><br/><span style='font-size:11px;color:#7F1D1D;'><b>标记: checksum_mismatch / delegate_fallback</b></span>"),
    ("N", "p4_lbl_err", 125, 672, 1030, 36, ('label', 'center', 'middle', False), "<b>错误码契约（Fail-Closed 原则）</b>"),
    ("N", "p4_err", 125, 726, 1030, 200, ('red', 'left', 'top', False), "<span style='font-size:11.5px;'><b>输入非法</b> — 输入未通过契约校验 → 直接阻断，不进入执行阶段<br/><b>门禁失败</b> — 阻断性门禁未达阈值 → 交接状态置为 blocked<br/><b>委派流异常</b> — 下游信封缺失或状态为 blocked → 抛出并上报闭环<br/><b>交叉匹配委派失败</b> — 下游主理失败 → 优雅降级并在信封标注<br/><b>清洗委派失败</b> — 下游主理失败 → 优雅降级并在信封标注<br/><b>未分类内部异常</b> — 收敛为统一内部错误码，保留完整回溯于血缘头<br/><span style='color:#7F1D1D;'><b>原则:</b> 不静默吞异常；失败必留证据，成功不虚报。</span></span>"),
    ("N", "p4_lbl_pr", 125, 954, 1030, 36, ('label', 'center', 'middle', False), "<b>降级与门禁的关系（不可让步）</b>"),
    ("N", "p4_principle", 125, 1008, 1030, 110, ('amber', 'left', 'top', False), "<b>【不可让步】</b><br/><span style='font-size:11.5px;'>• 降级不等于放宽门禁：门禁判定始终是双门槛。<br/>• 降级不等于伪造结果：宁可交付 needs_review，也不交付假的成功。<br/>• 降级不等于静默：每一次降级都必须留下可复核的痕迹。</span>"),
    ("N", "p4_lbl_evi", 1245, 232, 1030, 36, ('label', 'center', 'middle', False), "<b>不可变证据产物（可复核 / 可回放）</b>"),
    ("N", "p4_e0", 1245, 286, 1030, 86, ('purple', 'left', 'top', False), "<b>证据产物: 结果集（data / status）</b><br/><span style='font-size:11.5px;color:#581C87;'><b>证明效力:</b> 采集结果与失败严格区分，不伪造空数据；状态字段显式可判。</span>"),
    ("N", "p4_e1", 1245, 382, 1030, 86, ('purple', 'left', 'top', False), "<b>证据产物: 查询审计</b><br/><span style='font-size:11.5px;color:#581C87;'><b>证明效力:</b> 每次请求可关联 HTTP 状态 / 校验和 / 查询标识，逐次可追溯。</span>"),
    ("N", "p4_e2", 1245, 478, 1030, 86, ('purple', 'left', 'top', False), "<b>证据产物: 血缘头</b><br/><span style='font-size:11.5px;color:#581C87;'><b>证明效力:</b> 记录 skill / 版本 / UTC 时间戳 / 会话标识 + 输入输出引用；完整度门禁 = 1.0。</span>"),
    ("N", "p4_e3", 1245, 574, 1030, 86, ('purple', 'left', 'top', False), "<b>证据产物: 光变产品</b><br/><span style='font-size:11.5px;color:#581C87;'><b>证明效力:</b> 量纲随字段走（每个数值附单位）；时间一律 UTC ISO8601。</span>"),
    ("N", "p4_lbl_rag", 1245, 688, 1030, 36, ('label', 'center', 'middle', False), "<b>支撑面（RAG · 白盒 · 算力 · 治理面）</b>"),
    ("N", "p4_rag", 1245, 742, 1030, 165, ('neutral', 'left', 'top', False), "<span style='font-size:11.5px;'><b>领域 RAG:</b> 本地检索执行器（BM25 + 词桶 + 倒数排名融合）+ 领域知识四件套（领域规则 / 已知问题 / 经验教训 / 最佳实践）；检索失败不阻断主链。<br/><b>算法白盒:</b> 五要素白盒规范，DOI 逐条核验 — 本 skill 为外部服务型，无已验证 DOI，全部标注为未验证来源。<br/><b>算力预算:</b> 本地样本点 &lt; 100、单测 &lt; 1s；重负载改走云端规格（环境驱动 / 零凭据）。<br/><b>12 横切治理面:</b> 溯源 / 量纲 / 确定论 / 日志 / 错误码 / 契约 / 质量门禁 / 委派 / 安全 / 可复现 / 算力 / 遥测。<br/><b>可复现:</b> 白盒规范为唯一出处（五要素）。</span>"),
    ("N", "p4_lbl_chk", 1245, 935, 1030, 36, ('label', 'center', 'middle', False), "<b>完成自检（BEST 数据源主理）</b>"),
    ("N", "p4_chk", 1245, 989, 1030, 129, ('green', 'left', 'top', False), "<span style='font-size:11.5px;'>• BEST 自身数据查询/批量匹配列为本 skill PRIMARY 场景（委派表只承接越界能力）<br/>• 存量调用路径全部保留，回归测试全绿<br/>• 主文档精简（≤ 100 行），长知识下沉到参考与知识库<br/>• 凭据只在环境变量，路径锚定校验，无上溯逃逸<br/>• 架构规范的五状态机 + 12 治理面 + 主理定位声明齐备<br/>• 门禁表与对外声明一致（双门槛）</span>"),
]

