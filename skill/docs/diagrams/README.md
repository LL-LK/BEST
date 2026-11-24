# astro-best 架构图示资源全景索引 (Architecture Diagrams Index)

本目录归档保存 `astro-best`（国家天文台 NADC 中国虚拟天文台 BEST 基准定标星表接入中枢）的全套生产级架构图示资产、矢量源文件、分层切片与几何审计工具链。

公开图表见 [实验图表](../../../reproduction/02_图表/README.md)。本目录保留本地生成和审查脚本。

## 脚本（生成 / 审计 / 渲染 / 落盘，7 个）

| 脚本 | 职责 | 用法 |
|---|---|---|
| **`gen_best_macro_flowchart.py`** | 宏观全景流程图构建器：生成 `.drawio` → 前置几何审计 → 无损渲染 SVG/PNG/PDF（一条龙，审计不过不渲染） | `python gen_best_macro_flowchart.py` |
| **`gen_astro_best_architecture.py`** | 四页架构图构建器：只生成 `.drawio`（渲染刻意分离，见下） | `python gen_astro_best_architecture.py` |
| **`drawio_io.py`** | 共用落盘出口：`save_clean()` 落盘后剥离构建库写死的 `host/agent/version` 工具元数据并把行尾归一为 LF（与 `.gitattributes` 的 `eol=lf` 对齐） | 被两个生成器 import，不单独运行 |
| **`layout_data.py`** | 两张图共用的纯数据常量表（字体/色板/坐标/卡片 HTML/连线），无任何逻辑；改图先改这里 | 被两个生成器 import，不单独运行 |
| **`check_macro_collisions.py`** | 宏观流程图几何审计：双重 AABB 碰撞 + 泳道包含性 + 零 Emoji | `python check_macro_collisions.py` |
| **`audit_local.py`** | 架构图本地体检：Emoji / 路径泄漏 / 页数 / 越界 / 重叠 | `python audit_local.py [drawio 路径]` |
| **`export_diagram.py`** | 本地 Draw.io CLI 渲染封装：逐页导出 PNG/SVG + 整册 PDF | `python export_diagram.py` |

## 重建依赖与环境变量

- **构建库**：两个生成器依赖 `drawio-diagram-author` skill 的 `drawio_builder.py`（装在用户目录，**不属于本仓库**）。目录可用环境变量 `ASTRO_BEST_DRAWIO_BUILDER_DIR` 覆盖，未设时回落到本机安装路径。
- **渲染器**：`export_diagram.py` 与流程图的渲染步骤调用本机 draw.io 桌面端 CLI，路径可用 `ASTRO_BEST_DRAWIO_EXE` 覆盖。
- **输出目录**：六个脚本统一读 `ASTRO_BEST_DIAGRAM_DIR`，未设时回落本目录；从任意 cwd 调用都落到同一处（架构图 SSOT 只有一份）。
- **只重生成不渲染**：`python` 进程内 `import` 两个生成器并调用 `build()` / `build_macro_flowchart()` + `drawio_io.save_clean()`，即可只更新 `.drawio` 而不碰 28MB 位图产物。
