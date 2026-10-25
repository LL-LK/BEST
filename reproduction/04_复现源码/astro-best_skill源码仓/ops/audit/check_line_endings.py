"""check_line_endings.py — 检出工作区内混入 CRLF 的文件 (本仓约定 LF)。

背景: Windows 编辑器与部分工具写文件时会把 LF 悄悄变成 CRLF, git 随后警告
"CRLF will be replaced by LF" —— 本仓约定一律 LF, 因此需要一个能把落盘形态
照出来的体检工具。本脚本递归扫描**全仓文本类文件**, 列出含 CRLF 的文件与
CRLF 行数, 供一次性修正回 LF。

2026-10-05 修复轮 (H5-04, G2-15) 扩了扫描范围。此前本工具只匹配 ``.py``,
于是门禁 exit 0 的同时, 全仓有 68 个受跟踪文件是 CRLF —— REPORT.md /
capture_log.json / manifest.json 一个都看不见。G2 实测口径: 旧工具报 1 个,
真相是 68 个。给出虚假安心的门禁比没有门禁更糟, 所以范围按下面三条重写。

判定口径 (**与 .gitattributes 同源, 不另立标准**):
  1. 默认应为 LF —— 源码 / 文档 / 配置 / 构建脚本。除下面两条豁免外, 一律
     按"该是 LF"判。这条默认是刻意选的: 漏扫等于给假绿开门, 而把新出现的
     文件类型默认判成豁免, 等于让未知类型自动获得豁免权 (fail-loud 的方向)。
  2. 按字节保真 (豁免) —— ``.gitattributes`` 标 ``-text -eol`` 的数据资产:
     ``*.csv`` / ``best_data/**`` / ``evals/**/snapshots/**`` /
     ``evals/**/fixtures/**`` / ``temp/**``。这些含 \\r 是**站点回包的原样
     落盘**, 归一化就等于篡改被留档的证据 (``.gitattributes:29-31`` 记的正是
     上一次 renormalize 误改 27 个快照的事故)。
  3. 允许 CRLF —— ``.gitattributes`` 标 ``eol=crlf`` 的 ``*.ps1`` / ``*.bat``
     (Windows 脚本键就该是 CRLF, 判它红是误杀)。

职责: 只做行尾体检, **不修改任何文件**。度量对象是文件字节流里的 \\r 字节分布,
分 CRLF (Windows 换行) 与裸 CR (老 Mac 换行, 或二进制误写) 两类报出, 因为二者的
修正方式不同: 前者要归一换行, 后者往往是整文件编码写错, 值得单独看一眼。
所属子系统: 仓库治理层 ops/audit/ 的**报告型**工具 (不接 make audit 硬门禁):
零命中时直接 return, **非零也不改退出码**, 全靠 stdout 说话。上游无代码依赖,
下游是人工判读与一次性修正。
对外接口: main() -> None, 打印 ``应为 LF 却含 CRLF 的文件 = N`` 与逐行明细。
可外部依赖的 seam 只有这条 stdout 格式, 因为它没有任何返回值或产物文件 ——
因此它的判据级测试只能断言 stdout (见 test/unit/meta/
test_gate_criterion_red.py 的 TestLineEndingsIsNotVacuous), 不能断言退出码。
依赖与数据流: 输入是工作区磁盘上的字节 (不经 git, 检的是"落盘形态"而非"索引
形态"); 输出只到 stdout, 不落盘。
关键契约与不变量: (a) 扫描范围是**全仓递归**, 不得退回"只扫 .py"; (b) 报告
必须同时报出"该是 LF 的红"与"按字节保真的豁免"两个数 —— 只报一个就是 G2-15
那种口径缩小; (c) 判定必须读二进制, 文本模式读会把 \\r\\n 悄悄归一成 \\n,
那样就永远检不出 CRLF; (d) 退出码恒 0 (报告型工具不得变成阻断门禁)。
陷阱与边界: 裸 CR 计数用 "总 \\r 数 - CRLF 数" 得出, 若直接用 \\r\\n 计数会漏掉
纯 Mac 换行的文件; 二进制文件 (PNG/CSV) 靠"前 8 KiB 含 NUL 字节"识别并跳过,
否则 CSV 里的 \\r 会被当行尾误判。
"""
from __future__ import annotations

# 标准库: 文件遍历与字节读取 (行尾体检) / 仓根定位 (Path)
import io
import os
from pathlib import Path

# 仓根 = 本文件上溯两级 (ops/audit/x.py -> ops/audit -> ops -> 仓根)。
# 必须相对定位: 硬编码 monorepo 绝对路径, 换机/换克隆目录即失效。
ROOT = str(Path(__file__).resolve().parents[2])  # 仓根: parents[2] = 从 ops/audit/ 上跳两级

# 扫描范围 = 仓根**递归** (不再是 src/ops/evals/... 七个目录的并集; 范围参数化
# 在 scan(root) 上, 常量只有一个 ROOT)。旧口径漏掉了 contracts/ references/
# static/ agents/ weights/ templates/ 以及 README.md / Makefile / SKILL.md /
# .gitattributes 这些根级文件 —— 而 .gitattributes 恰恰是行尾约定的定义处,
# 漏掉它等于"用没被检查的文件定义检查标准"。

# 剪枝目录: 版本控制与工具缓存、运行时状态区。temp/ 与 best_data/ 同时也在
# 豁免名单里, 这里剪枝是为了不必逐个进去开文件。
SKIP_DIRS = frozenset({  # 用段名剪枝, 不做子串匹配 (否则 src/temporary_pkg/ 会被误伤)
    ".git", "__pycache__", ".ruff_cache", ".pytest_cache", ".mypy_cache",
    "node_modules", "best_data", "temp", ".checkpoints", ".progress", ".logs",
    ".venv", "venv",
})

# 判据 2 —— 按字节保真的数据资产 (.gitattributes 的 -text -eol 段)。
# 用**路径**而非扩展名表达: .gitattributes 就是这么钉的, 换机制不用改本工具。
BYTE_EXACT_EXTS = frozenset({".csv"})                     # 整类按扩展名豁免
BYTE_EXACT_DIRS = ("/snapshots/", "/fixtures/")           # 目录豁免: 带前导斜杠, 段边界才准

# 判据 3 —— 明确允许 CRLF (.gitattributes 的 eol=crlf 段)。
CRLF_ALLOWED_EXTS = frozenset({".ps1", ".bat"})           # Windows 脚本键

# 二进制嗅探窗口: 前 8 KiB 出现 NUL 即判二进制。CSV/PNG 不读进来, 既省时间
# 也避免把数据里的 \r 当行尾。
BINARY_SNIFF_BYTES = 8192  # 8 KiB 足够嗅出常见容器格式的头部


def is_binary(path: str) -> bool:
    """按"前 8 KiB 是否含 NUL 字节"判二进制 (行尾体检的适用性前提)。

    为什么需要它: 判据 1 默认"该是 LF", 若不先剔掉二进制, PNG/ICO 里的
    \\x0d\\x0a 字节会被报成"文件含 CRLF" —— 那不是行尾问题, 是数据。

    Args:
        path: 绝对路径。

    Returns:
        True = 判为二进制 (跳过); False = 当作文本类继续判行尾。

    失败语义: 读失败不自行吞掉, 由调用方按"扫描结果本身有问题"处理 ——
    静默跳过等于给假绿开门。
    """
    with io.open(path, "rb") as fh:
        return b"\x00" in fh.read(BINARY_SNIFF_BYTES)


def classify(rel: str) -> str:
    """把仓内相对路径归入三档判据之一。

    Args:
        rel: 正斜杠分隔的仓内相对路径 (如 ``contracts/io-contract.md``)。

    Returns:
        ``"byte_exact"`` (按字节保真, 豁免) / ``"crlf_allowed"`` (允许 CRLF) /
        ``"lf"`` (应为 LF, 判红)。**默认落在 ``"lf"``** —— 未知文件类型不得
        自动获得豁免权, 这是本工具 fail-loud 方向的落点。
    """
    low = rel.lower()  # 判据全小写: 扩展名大小写不该影响归档
    if os.path.splitext(low)[1] in BYTE_EXACT_EXTS:  # 先判扩展名豁免
        return "byte_exact"        # CSV: 科学数据, 含 \r 是数据本身
    if os.path.splitext(low)[1] in CRLF_ALLOWED_EXTS:  # 再判 CRLF 白名单
        return "crlf_allowed"      # Windows 脚本键: CRLF 是规定而非缺陷
    # 目录判据按 "/snapshots/" 这类**带前导斜杠**的子串比: 段边界才不会把
    # "src/mysnapshots_backup/" 之类的同名目录误判成豁免。
    padded = "/" + low  # 补前导斜杠, 让首段目录也能被 "/snapshots/" 命中
    if any(seg in padded for seg in BYTE_EXACT_DIRS):  # 目录豁免按段边界比
        return "byte_exact"        # 快照/夹具: 站点回包原样落盘
    return "lf"                    # 默认档: 未知类型不得自动获得豁免权


def scan(root: str = ROOT) -> tuple[list[tuple[str, int, int]], list[tuple[str, int, int]]]:
    """递归扫描全仓, 返回 (红, 豁免) 两份明细。

    Args:
        root: 仓根。**显式参数** —— 判据级测试要把缺陷注入临时假仓后实跑本
        函数, 写死 ROOT 会让"它能不能抓住自己该抓的"永远无法验证。

    Returns:
        ``(red, exempt)``, 每项是 ``(相对路径, CRLF 行数, 裸 CR 数)``; 两份都
        按路径排序, 让两次运行的输出可直接 diff。

    失败语义: 单个文件读失败会冒 OSError, 不静默跳过 —— "扫描结果本身有
    问题"与"文件干净"必须能区分开。
    """
    red: list[tuple[str, int, int]] = []      # 该是 LF 却含 CRLF 的明细
    exempt: list[tuple[str, int, int]] = []   # 按字节保真的明细 (显式报出, 不吞)
    for dirpath, dirnames, filenames in os.walk(root):  # 一次遍历
        # 必须原地改写 dirnames 才会剪枝, os.walk 读的就是这个列表对象
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fname in filenames:
            full = os.path.join(dirpath, fname)  # 拼绝对路径
            if is_binary(full):  # 二进制先行剔除: 其 \r 字节不是行尾
                continue
            with io.open(full, "rb") as fh:
                # 关键: 二进制读。文本模式的 universal newlines 会把 \r\n
                # 吃掉变 \n, 检出来的永远是 0 —— 这是本工具唯一的成败点
                raw = fh.read()  # 按字节读: 行尾判断必须在字节层做
            crlf = raw.count(b"\r\n")  # CRLF: 换行符写错, 归一即可
            lone_cr = raw.count(b"\r") - crlf  # 裸 CR 单列: 疑似整文件编码写错
            if not (crlf or lone_cr):
                continue  # 纯 LF: 本工具只管含 \r 的
            # relpath 已给出干净的相对路径, 不要再 lstrip("./") —— 那是按
            # **字符集**剥的, ".gitignore" 会被削成 "gitignore", 根级点文件
            # (而 .gitattributes 恰恰是行尾约定的定义处) 就会报成错名字。
            rel = os.path.relpath(full, root).replace(os.sep, "/")  # 正斜杠, 与门禁报告同写法
            if classify(rel) == "lf":
                red.append((rel, crlf, lone_cr))      # 判红: 该是 LF 却不是
            else:
                exempt.append((rel, crlf, lone_cr))   # 豁免也要列出来, 不能悄悄吞掉
    return sorted(red), sorted(exempt)  # 排序: 两次运行的输出可直接 diff


def main() -> None:
    """主入口: 扫描全仓文本类文件, 分"该是 LF 的红"与"按字节保真的豁免"报出。

    作用: 把两个计数与两份明细打到 stdout, 不返回业务值。关键输入只有模块级
    ROOT (相对仓根定位), 不需要调用方传入。
    返回: 无显式返回值 (None); **恒以退出码 0 结束** —— 本工具是报告型的,
    刻意不阻断 (CLAUDE.md: 报告型工具刻意不阻断, 需人判读)。
    抛什么: 不主动抛 —— 读单个文件失败会冒 OSError, 这是"扫描结果本身有
    问题"而非可降级项, 静默跳过等于给假绿开门。
    """
    red, exempt = scan(ROOT)  # 一次扫描, 两份明细
    # 口径先行打印: 旧工具只扫 .py 却只报一个数, 读者无从判断覆盖面。
    # 把范围与两条豁免规则写进输出, "只扫了 .py" 这种事就不可能再发生。
    print("行尾体检口径 (2026-10-05 H5-04 起为全仓递归, 不再只扫 .py):")
    print("  应为 LF    : 源码/文档/配置/构建脚本 (默认档; 未知类型也落这档)")
    print("  按字节保真  : *.csv / **/snapshots/ / **/fixtures/ (豁免, 不判红)")
    print("  允许 CRLF  : *.ps1 / *.bat (.gitattributes eol=crlf)")
    print("应为 LF 却含 CRLF 的文件 = %d" % len(red))  # 红档计数: 该修的那批
    for rel, crlf, lone_cr in red:  # 逐条打印 (已按路径排序)
        print("  %-58s CRLF=%d 裸CR=%d" % (rel, crlf, lone_cr))
    print("按 .gitattributes 豁免 (含 CRLF, 不判红) = %d" % len(exempt))  # 豁免也要有计数
    for rel, crlf, lone_cr in exempt:  # 逐条打印, 让豁免可被人复核
        print("  %-58s CRLF=%d 裸CR=%d" % (rel, crlf, lone_cr))
    print("\n本工具只体检不修改 (报告型, 恒 exit 0)。修正 = 把红档文件的 \\r\\n 换回 \\n:")
    print("  例: python -c \"import io,sys; p=sys.argv[1]; "
          "b=io.open(p,'rb').read(); io.open(p,'wb').write(b.replace(b'\\r\\n',b'\\n'))\" <路径>")


if __name__ == "__main__":
    main()  # 入口: 报告型工具, 恒 exit 0 (不阻断)
