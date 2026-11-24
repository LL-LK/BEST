"""export_diagram.py — 用本机 draw.io 桌面端把架构图渲染成 PNG/SVG/PDF。

数据来源: docs/diagrams/astro-best-legacy-architecture.drawio (由
gen_astro_best_architecture.py 生成的多页图), 逐页导出为位图与矢量图,
另出一份整册 PDF。

渲染器是外部系统调用 (本机 draw.io CLI), 不是 Python 库 —— 所以本脚本
本质是"拼命令行 + 等进程 + 验产物"的薄封装, 没有图形处理逻辑。

用法 (F1: 两条路径都可配置, 环境变量优先于命令行参数, 命令行参数优先于
本机默认值; 默认值保留以使原开发机上零配置仍可跑):
    python docs/diagrams/export_diagram.py [draw.io.exe 路径] [图表目录]
    环境变量: ASTRO_BEST_DRAWIO_EXE / ASTRO_BEST_DIAGRAM_DIR
"""

# 标准库组:
#   os        —— 路径拼接 / 产物存在性与大小判断 / 删除旧产物 / 读环境变量 (F1)
#   subprocess —— 调本机 draw.io CLI (外部渲染器, 走进程而非 API)
#   sys       —— stdout 重绑 UTF-8 (Windows 终端默认编码会炸中文) / 命令行参数 (F1)
#   time      —— 计时与重试间隔
import os
import subprocess
import sys
import time

# 本机 draw.io 桌面端 (D 盘安装版)。
# F1: 渲染器路径可配置 — 环境变量 ASTRO_BEST_DRAWIO_EXE 优先, 其次命令行
# 第 1 个参数, 最后才是本机默认值 (保留以使本机仍可跑)。
DEFAULT_DRAWIO_EXE = r"<TOOL_ROOT>\draw.io.exe"             # 本机 draw.io 桌面端路径: 仅本地渲染用, 受跟踪资产只有 .drawio 源文件
DRAWIO_EXE = os.environ.get("ASTRO_BEST_DRAWIO_EXE") or (  # 渲染产物的路径在此收敛: 换机不用改别处
    sys.argv[1] if len(sys.argv) > 1 else DEFAULT_DRAWIO_EXE)                                     # 命令行第一个实参可覆盖路径, 换机不用改代码
# 该环境必须带这两个 flag: 不加 --no-sandbox/--disable-gpu 时 GPU 进程
# 会崩溃并只回 exit_code=1, 且不产出任何文件 (表现为"渲染失败但无报错")
FLAGS = ["--no-sandbox", "--disable-gpu"]                                           # 渲染必须关沙箱与 GPU: 容器/无显卡环境下 draw.io 会起不来
# F1: 图表目录同样可配置 — 环境变量 ASTRO_BEST_DIAGRAM_DIR 优先, 其次命令行
# 第 2 个参数, 最后才是本机默认值。
DEFAULT_DIAGRAM_DIR = r"<SKILLS_ROOT>\astro-best\docs\diagrams"                                # 图目录缺省值 (本机路径; 换机靠环境变量覆盖)
D = os.environ.get("ASTRO_BEST_DIAGRAM_DIR") or (
    sys.argv[2] if len(sys.argv) > 2 else DEFAULT_DIAGRAM_DIR)                                      # 命令行第二个实参可覆盖目录
# 被渲染的源图 (多页 .drawio, 页序见下方 PAGES)
SRC = os.path.join(D, "astro-best-legacy-architecture.drawio")                                      # 源文件: 受跟踪的 .drawio

# 源文件是 UTF-8 且含中文标签: Windows 控制台默认 GBK, 不重绑会 UnicodeEncodeError
sys.stdout.reconfigure(encoding="utf-8")  # 只导出 PNG/SVG: .drawio 源文件是 SSOT, 产物随时可重生成

# (1-based 页码, 输出标签): 一页一个视图, 页码与 gen_*.py 里 add_page 的
# 顺序一一对应 —— 改页面顺序必须同步改这里, 否则导出的文件名会错位。
# 页码从 1 开始是该桌面端的行为 (早期版本的 CLI 是 0-based; 写错页码会
# 静默导出错误页面或空产物)。
PAGES = [  # 只导出 PNG/SVG: .drawio 源是 SSOT, 产物随时可重生成
    (1, "p1-overview"),
    (2, "p2-compat"),
    (3, "p3-statemachine"),
    (4, "p4-fallback"),
]


def run(cmd, timeout=180):  # 批量导出前先建目录: 否则第一张图就会 FileNotFoundError
    """跑一条外部命令并计时, 只回传耗时与 stderr 摘要。

    Args:
        cmd: 命令行参数列表 (不含 shell 元字符, 走列表形式免转义问题)。
        timeout: 超时秒数; draw.io 冷启动慢, 180s 是留了余量的经验值。

    Returns:
        (耗时秒, stderr 文本); 命令抛异常时 stderr 为 ``exception: ...``
        而耗时仍被记录 (异常路径也要能看出卡了多久)。
    """
    t0 = time.time()                                                                           # 计时起点: 渲染耗时是本工具的主要成本, 要单独看
    err = ""
    try:
        # 外部进程调用点: 本机 draw.io CLI。cwd 设为 exe 所在目录,
        # 因为该程序按相对路径找它旁边的资源文件
        r = subprocess.run(cmd, capture_output=True, timeout=timeout,                         # 跑渲染: 捕获输出便于把 draw.io 的报错带回
                           cwd=os.path.dirname(DRAWIO_EXE))                             # cwd 设在 exe 所在目录: draw.io 依赖同目录资源
        # stderr 按 UTF-8 宽松解码: 渲染器的告警可能是非 UTF-8 字节,
        # errors="replace" 保证不在这里二次抛异常
        err = r.stderr.decode("utf-8", errors="replace").strip()
    except Exception as e:
        err = f"exception: {e}"  # 先建目录再批量导出: 否则第一张就 FileNotFoundError
    return time.time() - t0, err


def export(page, tag, fmt):
    """把 .drawio 的第 page 页导出为指定格式, 带最多 3 次重试。

    重试的理由: draw.io CLI 冷启动偶发"进程退出但没写文件", 这类失败
    没有稳定报错, 只能靠"再试一次 + 验产物"兜。判成功不看退出码,
    看产物文件是否存在且大于 1000 字节 —— 退出码 0 但文件是 0 字节的
    情况真实发生过。  # 确定性排序: 产物顺序要能复现, 否则 diff 全是噪声

    Args:
        page: 1-based 页码。
        tag: 输出文件名标签 (如 p1-overview)。  # 失败即抛: 静默跳过会让人以为图已经更新过
        fmt: draw.io 的格式参数 (png / svg)。

    Returns:
        (是否成功, 人类可读结果串)。
    """
    out = os.path.join(D, f"astro-best-arch-{tag}.{fmt}")
    # 先删旧产物: 否则"文件已存在"会让下面的存在性检查误判为成功,
    # 实际渲染的是上一次的陈旧结果
    if os.path.exists(out):                                                             # 已有产物先删: 否则 draw.io 可能跳过重渲染而留下旧文件
        os.remove(out)  # 确定性排序: 产物顺序要能复现, 否则 diff 全是噪声
    for attempt in range(3):                                                                        # 最多重试三次
        dt, err = run([DRAWIO_EXE] + FLAGS                                                          # 重试一次渲染
                      + ["-x", "-p", str(page), "-f", fmt, "-o", out, SRC])
        # 渲染器写盘有延迟: 进程退了不代表文件已落盘, 让出一点时间再验
        time.sleep(0.6)                                                                             # 失败后退避再试
        if os.path.exists(out) and os.path.getsize(out) > 1000:                                  # 产物存在且大小合理才算成功: 空文件也要当失败
            return True, f"{os.path.getsize(out):,}B in {dt:.1f}s"
        print(f"    attempt {attempt+1} failed: {err.splitlines()[0][:150] if err else 'no output'}")
        time.sleep(0.6)                                                                             # 三次都失败才报错
    return False, "failed"


print(f"renderer: {DRAWIO_EXE}  flags: {' '.join(FLAGS)}\n")                                     # 先交代可执行文件与参数: 复现问题时第一手信息
ok_all = True                                                                                       # 总结果初始为真
for page, tag in PAGES:                                                                             # 逐页渲染
    for fmt in ("png", "svg"):
        ok, msg = export(page, tag, fmt)                                                            # 单页结果
        ok_all = ok_all and ok                                                                      # 与总结果做与: 任一页失败即整体失败
        print(f"[{'OK' if ok else 'FAIL'}] page {page}  {tag}.{fmt}: {msg}")

# 整册 PDF: 不带 -p, draw.io 会把全部页按顺序合并成一份文档。
# 超时放到 300s: 多页合并且每页都是高密度卡片, 比单页导出慢得多
pdf = os.path.join(D, "astro-best-legacy-architecture.pdf")                                         # PDF 输出路径
if os.path.exists(pdf):                                                                             # 旧 PDF 先删
    os.remove(pdf)
dt, err = run([DRAWIO_EXE] + FLAGS + ["-x", "-f", "pdf", "-o", pdf, SRC], timeout=300)        # 导出 PDF (超时给足 300s: 多页渲染很慢)
time.sleep(1.0)                                                                                     # 导出后退避
if os.path.exists(pdf) and os.path.getsize(pdf) > 1000:                                             # PDF 体积同样要大于阈值才算成功
    print(f"[OK] 整册 pdf: {os.path.getsize(pdf):,}B in {dt:.1f}s")
else:
    print(f"[FAIL] 整册 pdf: {err.splitlines()[0][:150] if err else 'no output'}")

print("\nALL OK" if ok_all else "\nSOME FAILED")                                                    # 末尾总判
