# -*- coding: utf-8 -*-
r"""ops.audit.verify_archive_privacy — 归档压缩包的**独立**隐私复验门禁 (N11)。

**它守的失效形态 (2026-10-08 实测)**: 打包器 ``pack_bulk2.py`` 自带隐私处理与
"入库后复验", 实测**两个判据都报「残留 0」而包里真有 92 处本机路径**:

  * 抹除规则 ``SANITIZE`` 是**白名单**形态 —— 只认 ``Users`` 与
    ``dev|tmp|home|opt|srv|var``, 于是本仓**父目录** (``<ABSPATH>`` 形态) 三条全不命中;
  * 复验规则 ``PRIVACY_PATTERNS`` 的「绝对盘符」只认 ``(Users|dev|home)`` ——
    **尺子比要抹的东西窄**, 于是拿自己的盲区给自己作证。README 那句
    「入库后逐批复验: 本机路径残留均为 0」是真话, 但它量不到自己看不见的那一类。

这是同一个坑的第三次 (前两次: 用户目录的转义形态、本仓父目录), 而打包器
自己的注释早就写下过: **「扫一遍没命中」不等于「没泄露」，脱敏规则本身也可能比判据窄**。

> 本段刻意用占位符而非真路径。举真例说明隐私问题本身就是隐私事故 —— 上一轮
> README 就因为"举真例"把真实邮箱与本机路径抄了进去，落地前扫描判红;
> 本门禁自己也得守同一条, 否则它守别人而自己漏。

**本门禁为什么必须独立**: 它**不从 ``pack_bulk2.py`` import 任何符号**。
规则写两遍不是重复, 而是**互为对照** —— 打包器与它的尺子同源时, 尺子坏了没人知道;
拆开之后, 打包器再坏这里仍会响。两条判据刻意分列:

  * 抹除规则可以窄 (漏抹只是多留内容);
  * **复验规则必须宽** (漏验等于放行) —— 故这里对**任意盘符**的绝对路径判红,
    包括打包器根本没提的形态。

**扫描面**: ``docs/archive/**/*.zip``（默认）。零 zip 即**判红** ——
零输入的绿灯只蕴含「没有触发任何条件」。

对外接口: :func:`scan_archives` (root) -> [(zip, 类别, 命中数)]; :func:`main` -> 退出码。
"""
from __future__ import annotations

# 标准库: 命令行参数解析 / 操作系统环境 / 正则表达式匹配 / 系统控制与输出 / 压缩归档处理 / 路径定位
import argparse  # 命令行参数解析
import os  # 操作系统环境与变量读取
import re  # 正则表达式字节匹配
import sys  # 系统输出与退出码控制
import zipfile  # zip 归档包流式解压读取
from pathlib import Path  # 跨平台路径计算与定位

# 控制台编码防御: Windows cp936 / GBK 终端下防止 Unicode 符号抛 UnicodeEncodeError
if hasattr(sys.stdout, "reconfigure"):  # 检查标准输出是否支持重配编码
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # 统一标准输出为 UTF-8 编码
if hasattr(sys.stderr, "reconfigure"):  # 检查标准错误是否支持重配编码
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # 统一标准错误为 UTF-8 编码


# 复验规则 (刻意**不复用**打包器的 PRIVACY_PATTERNS —— 见模块头「为什么必须独立」)。
# 全部按**字节**匹配: 归档里混着 CSV/parquet/日志/HTML, 按文本解会引入编码噪声。
#
# ``(?<![A-Za-z0-9])`` 是盘符与 URL 协议的分界: ``https://`` 里的 ``p:`` 前面是字母,
# 不算盘符。漏掉这条, 每个 https 链接都会被报成命中 —— 那样的门禁第一次就会被关掉,
# 实测过: 这条判据反过来被 https 淹没时, 真命中反而没人看了。
def _username_pattern() -> re.Pattern[bytes]:
    """本机用户名的独立出现形态; 取不到用户名时返回**永不命中**的 pattern。"""
    name = os.environ.get("USERNAME", "").strip().encode("ascii", "ignore")  # 取系统用户名
    if not name:  # 非 Windows 或变量为空: 不猜, 直接让这条失效而不是恒真
        return re.compile(rb"(?!)")  # 空用户名返回永不命中正则
    return re.compile(rb"(?<!\w)" + re.escape(name) + rb"(?!\w)")  # 单词边界锚定真实用户名


_PATTERNS: dict[str, re.Pattern[bytes]] = {
    "绝对盘符": re.compile(rb"(?<![A-Za-z0-9])[A-Za-z]:(?:\\+|/)[A-Za-z0-9_.]"),  # 盘符路径匹配
    "本机用户名": _username_pattern(),  # 本机用户名特征正则
    "口令赋值": re.compile(rb"(?:password|passwd|secret|api_?key|token)\s*[:=]\s*[\"'][^\"'\s]{6,}[\"']",
                          re.IGNORECASE),  # 口令密钥赋值匹配
    "PEM 私钥": re.compile(rb"-----BEGIN [A-Z ]*PRIVATE KEY-----"),  # PEM 私钥头匹配
    "邮箱": re.compile(rb"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),  # 邮箱地址正则匹配
}

# 明确豁免: 按 (类别, 子串) 配对。只按类别豁免会变成「口令那一类永远绿」, 那道门就没意义了。
# **本表刻意为空**: 用户 2026-10-08 的口径是「本机绝对路径一律不出仓」, 不设例外。
_ALLOWLIST: dict[str, tuple[bytes, ...]] = {}  # 显式空豁免表，严禁放行未脱敏项


def looks_binary(chunk: bytes) -> bool:
    """前 8 KB 里有 NUL 即判二进制 —— 纯二进制里的随机字节不该产生隐私命中。"""
    return b"\x00" in chunk[:8192]  # 前 8KB 包含空字节即判为二进制文件


def _exempt(category: str, matched: bytes) -> bool:
    """该命中是否在已核实的豁免表里。"""
    return any(matched in allowed for allowed in _ALLOWLIST.get(category, ()))  # 核对白名单匹配


def scan_zip(path: Path) -> dict[str, int]:
    """扫一个 zip, 返回 ``{类别: 命中数}`` (只含非零项)。

    Args:
        path: zip 路径。

    Returns:
        类别到命中数的映射; 干净则为空字典。
    """
    hits: dict[str, int] = {}  # 命中分类计数器字典初始化
    with zipfile.ZipFile(path) as archive:  # 安全打开 zip 归档包
        for info in archive.infolist():  # 遍历压缩包内所有条目
            if info.is_dir():  # 跳过目录节点
                continue  # 仅处理文件内容
            try:  # 保护读取异常
                with archive.open(info) as member:  # 打开压缩成员字节流
                    head = member.read(8192)  # 读取头部 8KB 用于探测二进制
                    if looks_binary(head):  # 二进制探测命中
                        continue  # 二进制不参与: 随机字节的命中是噪声
                    data = head + member.read()  # 拼装头部与剩余数据全量字节
            except (zipfile.BadZipFile, RuntimeError, OSError):  # 捕获损坏包异常
                continue  # 残包/坏条目: 跳过, 不让单条坏掉整批判定
            for category, pattern in _PATTERNS.items():  # 逐个匹配模式进行审计
                for found in pattern.findall(data):  # 找出当前模式所有命中
                    if _exempt(category, found):  # 核查是否属合法豁免
                        continue  # 豁免项跳过计数
                    hits[category] = hits.get(category, 0) + 1  # 命中计数自增累加
    return hits  # 返回分类汇总计数字典

SKIP_DIRS = frozenset({"temp-bulk", "temp", ".tmp"})  # 显式跳过临时大文件分卷打包区

# 清单文件名形态: ``<包名>.MANIFEST.md`` 与 ``MANIFEST.md`` (replay-backup 那份)。
_MANIFEST_NAMES = ("*.MANIFEST.md", "MANIFEST.md")


def scan_manifest(path: Path) -> dict[str, int]:
    """扫一份归档清单 (纯文本), 返回 ``{类别: 命中数}``。

    与 :func:`scan_zip` 共用同一套 :data:`_PATTERNS` —— 判据只有一份, 载体有两种。
    """
    try:
        data = path.read_bytes()  # 清单是纯文本, 不走二进制探测
    except OSError:  # 读不到即跳过
        return {}
    hits: dict[str, int] = {}
    for category, pattern in _PATTERNS.items():  # 与 zip 路径同款逐类匹配
        for found in pattern.findall(data):  # 找出该类全部命中
            if _exempt(category, found):  # 核查豁免表
                continue  # 豁免不计
            hits[category] = hits.get(category, 0) + 1  # 累加计数
    return hits


def scan_manifests(root: Path) -> list[tuple[str, dict[str, int]]]:
    """扫仓内全部**归档清单** (实体 zip 已退役, 清单是留在版本库里的隐私载体)。"""
    out: list[tuple[str, dict[str, int]]] = []  # 命中结果容器
    archive_root = root / "docs" / "archive"  # 归档根目录
    if not archive_root.is_dir():  # 目录都不存在
        return out
    seen: set[Path] = set()  # 防两个 glob 命中同一个文件 (``MANIFEST.md`` 会被 ``*.md`` 之类捞两次)
    for pattern in _MANIFEST_NAMES:  # 逐个文件名形态
        for manifest in sorted(archive_root.rglob(pattern)):  # 递归查找
            if manifest in seen:  # 已处理过
                continue  # 跳过重复
            seen.add(manifest)  # 登记已处理
            hits = scan_manifest(manifest)  # 执行单份扫描
            if hits:  # 有命中
                out.append((manifest.relative_to(root).as_posix(), hits))  # 记录
    return out  # 返回清单


def scan_archives(root: Path) -> list[tuple[str, dict[str, int]]]:
    """扫仓内全部归档 zip。

    Args:
        root: 仓根。

    Returns:
        ``[(zip 相对路径, {类别: 命中数})]``, **只列有命中的**。
    """
    out: list[tuple[str, dict[str, int]]] = []  # 命中结果列表容器
    for zip_path in sorted((root / "docs" / "archive").rglob("*.zip")):  # 递归查找所有 zip
        if SKIP_DIRS.intersection(zip_path.parts):  # 命中跳过目录
            continue  # 忽略临时大文件包
        hits = scan_zip(zip_path)  # 执行单包扫描
        if hits:  # 存在隐私命中
            out.append((zip_path.relative_to(root).as_posix(), hits))  # 记录相对路径与命中字典
    return out  # 返回违规结果清单


def main(argv: list[str] | None = None) -> int:
    """门禁入口: 任何归档包里有隐私命中即判红。"""
    parser = argparse.ArgumentParser(description="归档压缩包隐私独立复验门禁 (N11)")  # 构造解析器
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[2]),  # 仓根参数
                        help="仓根 (默认按本文件位置上溯两级)")  # 参数帮助说明
    args = parser.parse_args(argv)  # 解析命令行参数
    root = Path(args.root)  # 转换为 Path 对象

    archive_root = root / "docs" / "archive"  # 归档主目录定位
    all_zips = sorted(archive_root.rglob("*.zip")) if archive_root.is_dir() else []  # 收集 zip
    zips = [p for p in all_zips if not SKIP_DIRS.intersection(p.parts)]  # 过滤掉排除目录
    manifests = scan_manifests(root)  # 清单 (实体 zip 退役后, 它们才是仓内的隐私载体)

    # 负对照: 零扫描面必须判红。**扫描面 = zip + 清单**。
    #
    # 为什么把清单算进来 (2026-10-08): 用户裁定归档实体 zip 不入库, 删掉之后
    # ``docs/archive/`` 下确实一个 zip 都不剩 —— 那是**政策达成的状态**, 却撞上了
    # 「零扫描面即判红」, 于是门禁要么长期红、要么被人把负对照删掉来"修绿"。
    # 两条都是坏结局。
    #
    # 正确的修法不是放宽, 而是**扩大扫描面**: 实体退役后清单就是留在版本库里的
    # 隐私载体, 它必须被扫。于是本门禁比原来更严 —— 扫的载体从一种变两种。
    if not zips and not manifests and not _has_any_manifest_file(root):
        print("[verify_archive_privacy] 扫描面为空: docs/archive/ 下既无 .zip 也无归档清单 —— 判红。\n"  # 输出告警
              "  零输入的绿灯只蕴含「没有触发任何条件」。", file=sys.stderr)  # 输出到 stderr
        return 1  # 零扫描面返回退出码 1

    findings = [(f"{name} (归档包)", hits) for name, hits in scan_archives(root)]  # zip 侧
    findings += [(f"{name} (清单)", hits) for name, hits in manifests]  # 清单侧
    total = sum(sum(hits.values()) for _name, hits in findings)  # 统计总命中数
    if findings:  # 发现命中违规
        print(f"[verify_archive_privacy] {len(findings)} 个归档资产检出隐私命中 "  # 汇总输出
              f"(共 {total} 处) —— 判红 (N11):", file=sys.stderr)  # 判红输出
        for name, hits in findings:  # 遍历违规清单
            detail = ", ".join(f"{cat}={n}" for cat, n in sorted(hits.items()))  # 拼接命中明细
            print(f"  - {name}: {detail}", file=sys.stderr)  # 逐条输出明细
        print("  门禁只报不改: 擦掉现场等于毁掉证据。\n"  # 修复指引第一步
              "  处理顺序: 先补脱敏规则 → 重抽清单 → 重跑本门禁。",  # 修复指引第二步
              file=sys.stderr)  # 输出指引
        return 1  # 返回退出码 1 阻断

    print(f"[verify_archive_privacy] {len(zips)} 个归档包 + {len(_count_manifests(root))} 份清单 "
          f"全部零命中 —— 通过 (N11)。")  # 正常放行
    print(f"  已检类别: {', '.join(sorted(_PATTERNS))}")  # 打印已检模式清单
    return 0  # 退出码 0 表示绿灯


def _has_any_manifest_file(root: Path) -> bool:
    """仓内是否存在归档清单文件 (哪怕一份都没命中隐私)。"""
    archive_root = root / "docs" / "archive"  # 归档根
    if not archive_root.is_dir():  # 目录不存在
        return False  # 视为没有
    return any(any(archive_root.rglob(p)) for p in _MANIFEST_NAMES)  # 任一形态命中即真


def _count_manifests(root: Path) -> list[Path]:
    """列出全部归档清单路径 (供报告用)。"""
    archive_root = root / "docs" / "archive"  # 归档根
    if not archive_root.is_dir():  # 目录不存在
        return []  # 空表
    seen: set[Path] = set()  # 去重集合
    for pattern in _MANIFEST_NAMES:  # 逐形态收集
        seen.update(archive_root.rglob(pattern))  # 并入集合
    return sorted(seen)  # 排序返回


if __name__ == "__main__":
    raise SystemExit(main())  # 执行 main 并抛出系统退出
