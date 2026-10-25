# astro-best 架构图示资源全景索引 (Architecture Diagrams Index)

本目录归档保存 `astro-best`（国家天文台 NADC 中国虚拟天文台 BEST 基准定标星表接入中枢）的全套生产级架构图示资产、矢量源文件、分层切片与几何审计工具链。

---

## 1. 核心产物清单

分发口径：**`.drawio` 源文件与生成/审计脚本受 git 跟踪**（合计约 270 KB），**PNG / SVG / PDF 渲染产物不随 git 分发**（`docs/` 整体在 `.gitignore` 内，本地保留供查看与再渲染）。

| 文件名称 | 格式与规格 | 文件大小 | 架构层级 / 适用场景 | git |
|---|---|---|---|---|
| **`astro-best-macro-flowchart.drawio`** | `.drawio` (4400×3200px XML) | 75.1 KB | 原生架构源文件，支持本地 Draw.io 桌面端自由编辑 | 跟踪 |
| **`astro-best-legacy-architecture.drawio`** | `.drawio` (2400 宽 4 页 XML) | 72.8 KB | astro-best 四页架构图: 总览 / 主理能力域 / 五状态机 / 降级·错误码·证据 | 跟踪 |
| **`astro-best-macro-flowchart.svg`** | 矢量 SVG | 11.35 MB | 任意倍率无损缩放，大屏展示与高清投屏首选 | 本地 |
| **`astro-best-macro-flowchart.png`** | 2x 超高清位图 | 4.53 MB | 演示文稿、报告与文档直接嵌入 | 本地 |
| **`astro-best-macro-flowchart.pdf`** | 单页矢量 PDF | 580 KB | 汇报级单页打印、白皮书附件与独立审阅 | 本地 |
| **`astro-best-legacy-architecture.pdf`** | 单册矢量 PDF (4 页合并) | 261.8 KB | 四页架构合并单册审阅文档 | 本地 |
| **`astro-best-arch-p1-overview.*`** | PNG & SVG | ~3 MB | 架构图 Page 1: 架构总览 · 三域拓扑切片 | 本地 |
| **`astro-best-arch-p2-compat.*`** | PNG & SVG | ~3 MB | 架构图 Page 2: 域① 主理能力域与委派路由切片 | 本地 |
| **`astro-best-arch-p3-statemachine.*`**| PNG & SVG | ~3.2 MB | 架构图 Page 3: 域② 五状态机执行链切片 | 本地 |
| **`astro-best-arch-p4-fallback.*`** | PNG & SVG | ~3.2 MB | 架构图 Page 4: 域③ 降级·错误码·证据切片 | 本地 |

---

## 2. 宏观全景流程图架构设计（5 大能力泳道 + 1 条闭环走廊）

画布自上而下：顶部总标题条 → **数据口径表**（量纲/单位/门限数值的一级展示）→ 5 条能力泳道 → **闭环反馈走廊**（第 6 条横向带，横切五条泳道的回退通道，外环紫色虚线即其返回走线）。

1. **第一泳道：多端接入与交互层 (Multi-Surface Intake)**
   - 涵盖 CLI 命令行 (`python -m src` / `ops/astro_best_cli.py`)、OOP 套件 (`BestClient`, `BestAuth`, `BestQuery`, `BestDownloader`)、agent 工具面 (`ToolBox` 7 原子工具)、轻量独立脚本与本地领域 RAG 检索；
2. **第二泳道：调度编排与五状态机治理层 (Orchestration & 5-State Machine)**
   - 贯穿 `INTAKE`（接收）$\to$ `VALIDATE`（校验）$\to$ `EXECUTE`（执行）$\to$ `GATE`（门禁）$\to$ `EMIT`（发布），并在底部横向锚定 12 维横切治理面；
3. **第三泳道：两阶段异步 REST 通信引擎 (Two-Phase REST Protocol Engine)**
   - 详细解构 Phase 1 POST 表单构造、SQLID 正则安全提取清洗、Phase 2 分页拉取 (`rows=1000`) 与连接池指数退避重试；
4. **第四泳道：12 张可查定标星表全景体系 (12 Queryable Calibration Catalogs)**
   - 涵盖 `std` 导航组 (`scr_galah`/`scr_lamost`/`xpsp`)、`ps1`、`stripe82`、`gaia_dr3`、`jplus_dr3`、`smss_dr4`、`landolt`、`uss_dr1`、`splus_dr4`、`dr3xpcorr` 及外部台站服务；
5. **第五泳道：安全防御、产物交付、委派路由与闭环回退 (Security & Closed-Loop)**
   - 包含 CSV 公式注入清洗（天文学负数放行）、路径穿越拦截、`write_text + os.replace` 原子防污染落盘、委派路由与反馈总线重观测回路。
6. **闭环反馈走廊 (Closed-Loop Corridor，非能力层)**
   - 四站推进：① 异常触发（门禁持续失败/数据质量不足/网络熔断）→ ② 决策信封（`needs_review` + ask 载荷转人工复核）→ ③ 重观测请求（11-closed-loop 驱动望远镜调整曝光/滤光片/指向）→ ④ 知识飞轮（沉淀 `known_issues.yaml` 反哺领域 RAG）。
   - 该走廊是生成器第一版就声明、但旧实现只落成一条绕画布边缘的连线（`e_e6_a1`）的结构；现已提为可见容器，读者能直接读出闭环经过哪几站。

---

## 3. 脚本清单（生成 / 审计 / 渲染 / 落盘，7 个）

| 脚本 | 职责 | 用法 |
|---|---|---|
| **`gen_best_macro_flowchart.py`** | 宏观全景流程图构建器：生成 `.drawio` → 前置几何审计 → 无损渲染 SVG/PNG/PDF（一条龙，审计不过不渲染） | `python gen_best_macro_flowchart.py` |
| **`gen_astro_best_architecture.py`** | 四页架构图构建器：只生成 `.drawio`（渲染刻意分离，见下） | `python gen_astro_best_architecture.py` |
| **`drawio_io.py`** | 共用落盘出口：`save_clean()` 落盘后剥离构建库写死的 `host/agent/version` 工具元数据并把行尾归一为 LF（与 `.gitattributes` 的 `eol=lf` 对齐） | 被两个生成器 import，不单独运行 |
| **`layout_data.py`** | 两张图共用的纯数据常量表（字体/色板/坐标/卡片 HTML/连线），无任何逻辑；改图先改这里 | 被两个生成器 import，不单独运行 |
| **`check_macro_collisions.py`** | 宏观流程图几何审计：双重 AABB 碰撞 + 泳道包含性 + 零 Emoji | `python check_macro_collisions.py` |
| **`audit_local.py`** | 架构图本地体检：Emoji / 路径泄漏 / 页数 / 越界 / 重叠 | `python audit_local.py [drawio 路径]` |
| **`export_diagram.py`** | 本地 Draw.io CLI 渲染封装：逐页导出 PNG/SVG + 整册 PDF | `python export_diagram.py` |

## 4. 重建前提（依赖与环境变量）

- **构建库**：两个生成器依赖 `drawio-diagram-author` skill 的 `drawio_builder.py`（装在用户目录，**不属于本仓库**）。目录可用环境变量 `ASTRO_BEST_DRAWIO_BUILDER_DIR` 覆盖，未设时回落到本机安装路径。
- **渲染器**：`export_diagram.py` 与流程图的渲染步骤调用本机 draw.io 桌面端 CLI，路径可用 `ASTRO_BEST_DRAWIO_EXE` 覆盖。
- **输出目录**：六个脚本统一读 `ASTRO_BEST_DIAGRAM_DIR`，未设时回落本目录；从任意 cwd 调用都落到同一处（架构图 SSOT 只有一份）。
- **只重生成不渲染**：`python` 进程内 `import` 两个生成器并调用 `build()` / `build_macro_flowchart()` + `drawio_io.save_clean()`，即可只更新 `.drawio` 而不碰 28MB 位图产物。

## 5. 产物修订状态（重要）

- `.drawio` 是唯一可编辑源文件；**PNG / SVG / PDF 是它的渲染快照**，重新生成 `.drawio` 后不会自动刷新。
- 当前本地渲染产物与 `.drawio` 源**同步**（随口径表 + 闭环走廊一起重渲）。往后若只改 `.drawio` 忘了重渲，用第 3 节的一条龙（流程图）或 `export_diagram.py`（架构图四页 + 整册 PDF）补齐；渲染失败时该脚本会先删旧产物再重试，所以**不要在渲染中途打断它**。
- 文件命名的 `legacy` 字样是历史沿用（该图原为 legacy 兼容层归档图，现为四页主架构图），未随定位迁移改名，以免破坏外部引用。
- 漂移防护：`test/unit/meta/test_diagram_ssot.py` 会重生成并与受跟踪 `.drawio` 逐字节比对——改了 `layout_data.py` 忘记重生成，或用裸 `doc.save()` 绕过 `drawio_io.save_clean()`，这道测试都会红；同一条测试还跑构建库的 `verify_drawio_security`（8 类安全/结构检查）并核对每个源文件都在 git 跟踪内。
