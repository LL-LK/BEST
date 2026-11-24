# -*- coding: utf-8 -*-
"""门禁盲区回归: AST 结构扫描 + 跨入口行为断言。

守的三类盲区 (运行时问题清单 `temp/DEBUG-ISSUES-2026-09-28-runtime.md` 的
"为什么全绿不等于健康"一节):

1. **结构盲区** — 739 条契约形态测试与窄 ruff 规则集都看不见的问题:
   模块级同名重复定义 (同一模块里 61/72 双定义, 生效的是后一份)、
   公开符号生产零引用 (Q-09)。前者**阻断**, 后者仅 WARN (CODE-QUALITY-
   FIX-LIST §2.2 已论证 44% 公开函数零生产调用是设计使然的 A 类公开 API
   面, 一刀切阻断会误伤 — 用户 2026-09-28 裁定);
2. **行为盲区** — 跨入口的单点接线断言: 两条分页链都必须走协议层
   ``build_page_url`` 单点 (P0-1), 状态码显式失败必须落在两个客户端
   (P0-2)。逐条的行为回归在 ``test/unit/audit_round/test_audit_fixes.py``,
   这里守"接线本身不断"。
3. **版本库盲区** — 工作区不得存在"未跟踪且未被忽略"的文件 (``ops/audit/``
   11 个文件长期只在磁盘与 README 树清单里、不在 git index 里)。树门禁只比对
   README 树块 ↔ 文件系统, 看不见这一层; 详见 ``TestGitTrackingCoverage``。
4. **委派缝盲区** — 抽离件留下的薄壳按**位置参数**转发, 两侧形参表是两份独立
   文本。少转发一个形参、顺序错一位, **都不报 TypeError**, 也不违反任何既有
   断言, 只会静默少一项能力或查错天区 (R4-02; 详见 ``TestDelegationSeamIsGuarded``)。
   与第 3 条同源: 缺的不是"做对了", 而是"改坏了有人拦"。
"""

from __future__ import annotations

# 标准库: ast 做结构扫描 / warnings 发零引用告警 (不阻断) / pathlib 定位仓库根 /
# subprocess 调 git 核对跟踪状态
import ast  # ast 做结构扫描: 重复定义只能靠语法树看清
import subprocess  # subprocess 调 git 核对跟踪状态: 树门禁看不见这一层
import warnings  # warnings 发零引用告警: 那条是 WARN 级, 不阻断
from pathlib import Path  # 定位仓库根: 所有扫描目录都由它推出

# 第三方: 环境不满足时 skip (不在 git 仓库内 / git 不可用)
import pytest  # 不在 git 仓库内或 git 不可用时跳过

SKILL_ROOT = Path(__file__).resolve().parents[3]  # 仓库根: 本文件位于 test/unit/meta/, 上溯三级即 skill 根
SCAN_DIRS = ("src", "ops", "evals", "rag")        # 只扫生产代码目录: test/ 的重复定义由 pytest 收集期自然暴露


def _production_files() -> list[Path]:
    """收集生产目录下的全部 .py (排除 __pycache__ 与隐藏目录)。

    sorted 是为了让失败信息的次序可复现: rglob 的返回顺序随文件系统而变,
    同一处重复定义在不同机器上会报出不同的行号对照, 复核时无从对齐。
    """
    files: list[Path] = []                                                             # 收集生产文件: 只扫生产目录, test/ 的重复由收集期自然暴露
    for name in SCAN_DIRS:                                                                          # 逐个扫描目录
        base = SKILL_ROOT / name                                                                    # 目录由仓根与目录名拼出
        if not base.is_dir():                                                                      # 目录不存在就跳过: 裁剪克隆时子树可能缺失
            continue
        for path in sorted(base.rglob("*.py")):                                                     # 排序遍历: 失败信息的次序必须跨机可复现
            if "__pycache__" in path.parts:                                                  # 缓存目录不是源码: 里面的 .pyc 副本会造出假重复
                continue
            files.append(path)                                                                      # 收进清单
    return files  # 交给调用方按序扫描: 失败信息里先出现的那个才是最小复现点


def _module_level_definitions(tree: ast.Module) -> dict[str, int]:
    """模块级 class/function 定义名 -> 首次定义行号 (同名多次即重复定义)。"""
    seen: dict[str, int] = {}
    for node in tree.body:                                                                          # 只扫模块体: 嵌套定义不算模块级重复
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):                 # 类与两种函数形态都算定义
            seen.setdefault(node.name, node.lineno)  # 留首次出现: 重定义的后一份才是运行时生效的那份
    return seen


def _all_definition_lines(tree: ast.Module) -> dict[str, list[int]]:
    """模块级 class/function 定义名 -> 全部定义行号 (>1 即重复)。"""
    lines: dict[str, list[int]] = {}
    for node in tree.body:                                                                          # 只扫模块体
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):                 # 类与两种函数形态都算定义
            lines.setdefault(node.name, []).append(node.lineno)                                   # 同名就把行号追加进去, 长度大于 1 即重复
    return lines


class TestNoDuplicateModuleDefinitions:
    """结构门禁 (阻断): 模块级不允许同名 class/function 重复定义。

    复过的现 (运行时清单 P3-1): ``src/crossmatch.py`` 的
    ``_proximity_radec_text`` 定义两次, 运行时生效的是后一份 (重写 zip
    逻辑), 协议层薄别名成为死代码 — 而 ruff 的既有规则集与全部测试都没
    有报告它。AST 级扫描让"漏报重复定义"不再可能。
    """

    def test_no_duplicate_definitions_in_production_code(self):
        """生产目录任一模块都不得有模块级同名重复定义。

        这条专门堵 lint 的盲区: 重复定义既不是未用也不是未定义, 语法完全
        合法, 于是它能长期存活并让先写的那份悄悄变成死代码。
        """
        duplicates: list[str] = []                                                                  # 逐个文件扫, 攒齐再报
        for path in _production_files():                                                            # 按序扫生产文件
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))                                  # 解析失败不在这里判: 那是编译门禁的职责
            except (SyntaxError, UnicodeDecodeError):
                continue  # 解析不了的文件由编译门禁负责, 不在这里重复判
            for name, linenos in _all_definition_lines(tree).items():                               # 逐个定义名看它出现在几个行号上
                if len(linenos) > 1:  # 判据是"同名出现 >1 次", 不是"定义了两次"这类措辞
                    rel = path.relative_to(SKILL_ROOT).as_posix()                                   # 转成仓内相对路径: 报错信息要能直接定位
                    duplicates.append(f"{rel}:{name}@{linenos}")  # 连行号一起报: 改哪一份才有着落
        assert not duplicates, (
            "模块级重复定义 (后者覆盖前者, 前者成死代码): "
            + "; ".join(duplicates)
        )


class TestPublicSymbolReferences:
    """结构门禁 (WARN): 公开符号的生产引用清点 (Q-09 可视化, 不阻断)。

    判定口径与 CODE-QUALITY-FIX-LIST §2.2 一致: 公开 API 面 (A 类) 零
    生产调用是设计使然, 因此这里只发 WARN 把清单摆到明处; 真正的阻断
    留给重复定义门禁。清点方式: 全生产目录文本出现次数减去定义处的一次
    (含 docstring 提及 — 与既有审计同口径的上界, 宁多报不漏报)。
    """

    def test_zero_reference_public_symbols_are_reported(self):
        """零引用公开符号逐个 WARN (门禁价值在可见性, 不在红绿)。

        空扫描结果必须直接判红: 语料为空时"零引用符号"恒为空集, 而空集照样
        能通过所有断言 —— 这正是门禁空转比没有门禁更危险的那种形态。
        """
        files = _production_files()                                                                 # 先确认语料非空
        assert files, "生产目录扫描结果为空 — 门禁本身失效"
        # 全目录语料: {相对路径: 源码文本}
        corpus = {                                                                                  # 全目录语料: 引用计数要跨文件统计
            path.relative_to(SKILL_ROOT).as_posix():                                                # 键用仓内相对路径
                path.read_text(encoding="utf-8")                                                    # 值是该文件的源码全文
            for path in files
        }
        reported: list[str] = []
        for rel, text in corpus.items():                                                            # 逐个文件算引用数
            try:
                tree = ast.parse(text)                                                              # 解析失败不计入清点, 否则会误报成零引用
            except (SyntaxError, UnicodeDecodeError):
                continue  # 同上: 解析不了不计入清点, 否则误报成"零引用"
            for node in tree.body:                                                                  # 逐个模块级定义
                if not isinstance(node,
                                  (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                if node.name.startswith("_"):                                                       # 私有符号不参与公开面清点
                    continue  # 私有符号不参与公开面清点
                # 全语料出现总次数 - 本文件定义处的一次 = 引用数 (上界口径)
                total_hits = sum(other.count(node.name)                                             # 跨全语料数出现次数, 减去定义处那一次
                                 for other in corpus.values())
                if total_hits <= 1:  # 只有定义处那一次 = 生产代码零引用
                    reported.append(f"{rel}:{node.name}")                                           # 记下相对路径与符号名
        for item in reported:                                                                     # 逐条发告警: 门禁的价值在可见性, 不在红绿
            warnings.warn(                                                                          # 告警而不是断言: 这条按裁定不阻断
                f"公开符号生产零引用 (Q-09 清点, 不阻断): {item}", stacklevel=1)
        # 结构自洽: 清点必须跑过 (不强制非空 — A 类公开面允许零引用)
        assert isinstance(reported, list)  # 只验"清点确实执行过", 不把零引用本身判红


class TestCrossEntryWiring:
    """行为门禁 (阻断): 跨入口单点接线不能断 (P0-1/P0-2 的"接线"面)。

    逐条行为回归在 audit_round; 这里守更上层的实事: 分页链的源码
    都必须走 ``build_page_url`` 单点, 客户端与下载栈都必须显式查状态码 —
    只看单点自己的单测是不够的 (客户端真的走单点才算修好)。

    P1 合并注记: pybest 的第二条分页链 (best_export.fetch_pages) 随双副本
    删除一并移除, 本类断言相应收敛到唯一存留链 (client + best_export.download_file)。
    """

    def test_pagination_path_goes_through_the_single_point(self):
        """client 分页链必须调用 build_page_url (唯一分页链)。

        phase-2 取数引擎 (含分页 URL 构造的调用点) 按 budget §3.2 抽至
        ``src/client_paging.py``, client.py 留委派壳 —— 单点接线的**拓扑**是
        调用点迁户, 不变量不变: 分页 URL 仍只经 ``build_page_url`` 构造。
        故本门禁改查三件事:
          1. client_paging.py 里确有 ``build_page_url(`` 调用 (单点在场);
          2. client.py 的取数路径是委派壳 (转发到 client_paging, 不自建串);
          3. 全 src/ 内不得出现第二条 ``page=`` 自拼分页串 (双链回归)。
        """
        paging_src = (SKILL_ROOT / "src" / "client_paging.py").read_text(                      # 抽离件源码: 分页 URL 构造的调用点迁到了这里
            encoding="utf-8")
        assert "build_page_url(" in paging_src, (                                                   # 单点必须在场: 缺了它就退回自建查询串
            "src/client_paging.py 的分页 URL 构造又回到了自建查询串 — P0-1 单点接线断了"
        )
        client_src = (SKILL_ROOT / "src" / "client.py").read_text(                                  # 委派壳源码: 它该转发而不是自建串
            encoding="utf-8")
        assert "fetch_sqlid_data(" in client_src, (                                            # 委派调用必须在场: 抽离件接线断了的表现就是这一条
            "src/client.py 的取数路径不再委派 client_paging — 抽离件接线断了"
        )
        # 双链回归: src/ 内 f-string 自拼的分页串 (``page={...}``) 只允许出现在
        # stable_uri 溯源标识语境 (ai_tools 的 provenance 四键), 不得出现在
        # 任何抓取/请求路径 — 抓取一律经 build_page_url 单点。
        offenders = []                                                                              # 逐行扫全 src 找自拼分页串
        for path in sorted((SKILL_ROOT / "src").rglob("*.py")):                                     # 排序遍历: 双链回归要能稳定复现
            for index, line in enumerate(
                    path.read_text(encoding="utf-8").splitlines(), start=1):                        # 带行号读, 命中要报到行
                if "page={" in line and "stable_uri" not in line:                                # 溯源标识语境是唯一豁免: 抓取路径一律不许自拼
                    offenders.append(f"{path.name}:{index}")  # 报文件+行: 双链回归要能直接定位
        assert not offenders, (
            f"出现自拼分页串的文件 (应走 build_page_url): {offenders}")

    def test_client_and_download_stack_fail_closed_on_http_error_status(self):
        """BestClient._request 与 download_file 都不得缺少状态码显式失败。"""
        client_src = (SKILL_ROOT / "src" / "client.py").read_text(                                  # 客户端源码: 状态码显式失败必须在这一层
            encoding="utf-8")
        assert "raise_for_status()" in client_src, (                                       # 状态码校验必须在场: 缺了它 HTTP 错误会被当成空响应
            "src/client.py 的 _request 又没有了 raise_for_status — P0-2 回归"
        )
        export_src = (SKILL_ROOT / "src" / "best_export.py").read_text(                             # 下载栈源码: 状态码前置校验在落盘那一侧
            encoding="utf-8")
        assert "status_code != 200" in export_src, (                                        # 前置校验必须在场: 否则 404 响应体会被当成产物写盘
            "src/best_export.py 的 download_file 又没有了状态码前置校验 — P0-2 回归"
        )

    def test_download_url_allowlist_is_wired_into_the_download_stack(self):
        """下载栈唯一入口必须校验 URL 主机白名单 (P1-10)。

        守两处而不是只守入口: 常量在、入口不调, 与常量被删, 是两种完全
        不同的退化路径, 而后者正是当初 SSRF 能一路走到落盘的原因。
        """
        export_src = (SKILL_ROOT / "src" / "best_export.py").read_text(                           # 下载栈源码: 白名单校验的唯一调用点在这一层
            encoding="utf-8")
        assert "validate_external_url(" in export_src, (                                  # 校验调用必须在场: 常量在而入口不调, SSRF 照样能走通
            "src/best_export.py 的 download_file 又没有了 URL 白名单校验 — P1-10 回归"
        )
        guards_src = (SKILL_ROOT / "src" / "scripts" / "guards.py").read_text(                      # 白名单常量所在模块源码
            encoding="utf-8")
        assert "ALLOWED_DOWNLOAD_HOSTS" in guards_src, (                                         # 常量必须在场: 它被删与入口不调是两种退化路径
            "src/scripts/guards.py 的下载主机白名单常量缺失 — P1-10 单点被删"
        )

    def test_pagination_sort_covers_every_queryable_catalog(self):
        """12 张可查询星表都必须有确定性排序列 (P0-1 漏登记即红)。

        判据是集合差而不是逐张断言: 漏登记的那张表会在翻页时退回服务端默认
        排序, 同一查询两次跑出来的行序可能不同, 而这种不稳定性在结果里完全
        看不出来。
        """
        from src.protocol import CATALOG_PATHS, PAGINATION_SORT_COLUMNS  # 局部导入: 只有这条要用这两个常量

        missing = sorted(set(CATALOG_PATHS) - set(PAGINATION_SORT_COLUMNS))                       # 集合差: 漏登记的那张表会退回服务端默认排序
        assert not missing, f"星表缺少分页排序列登记: {missing}"  # 漏登记即红: 漏的那张会退回服务端默认排序


class TestGitTrackingCoverage:
    """工作区不得存在"未跟踪且未被忽略"的文件 (本机能跑、克隆机崩 的根形态)。

    守的缺口形态: ``ops/audit/`` 11 个文件被 6 份治理文档引用为"复测命令",
    在磁盘上真实存在、也已被 README 树清单登记, 却从未 ``git add``。新克隆的仓库
    缺这些文件, 按文档跑会"文件不存在"。

    为什么这一层容易漏: 树完整性门禁 (``ops/verify_tree_integrity.py``) 只比对
    「README 树块 ↔ 文件系统存在性」, **从不比对 git index** —— 只要文件在磁盘上、
    树块里也写了, 它就绿灯。既有 ``test_diagram_ssot.py`` 的同类断言又把范围限死在
    ``docs/diagrams``, 于是同一个坑换个目录就绕过去了。

    判据用 ``git ls-files --others --exclude-standard``: 它同时排除"已跟踪"与
    "被 .gitignore 忽略"两类, 剩下的就是必须入库却漏掉的。``temp/`` 等 local-only
    目录由 .gitignore 覆盖, 因此不会误报。

    这个判据按设计**排除被忽略的文件**, 于是它有一个对称的盲区: 把核心资产写进
    ``.gitignore`` 就能让它隐身而门禁全绿。``CHANGELOG.md`` 正是这样活了很久
    (本仓唯一变更记录载体, 却对新克隆者完全不存在)。故本类另有第二条门
    :meth:`test_core_governance_docs_are_not_gitignored` 专门守这一半: 核心资产
    既不得被忽略, 也必须确实 ``git add`` 过。两条合起来才是完整的入库义务。
    """

    def test_no_untracked_unignored_files(self) -> None:
        """工作区不得有"未跟踪且未被忽略"的文件 (docs/diagrams 渲染产物除外)。"""
        try:
            proc = subprocess.run(                                                              # 在仓根下问 git: 相对路径的基准就是 cwd
                ["git", "ls-files", "--others", "--exclude-standard"],                              # 这条命令同时排除已跟踪与被忽略两类
                cwd=SKILL_ROOT, capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=60)
        except (OSError, subprocess.TimeoutExpired):
            pytest.skip("git 不可用, 无法核对跟踪状态")                                                     # git 不可用时跳过: 环境问题不该算用例失败
        if proc.returncode != 0:                                                                  # 子进程非零即门禁未通过, 不看 stdout
            pytest.skip(f"不在 git 仓库内: {proc.stderr.strip()[:120]}")                           # 不在仓库内时跳过: skill 被整体拷走是合法场景
        untracked = [ln for ln in proc.stdout.splitlines() if ln.strip()]                           # 剩下的就是必须入库却漏掉的
        assert not untracked, (  # 空列表即合规; 非空时逐条点名, 不只报"有 N 个"
            "以下文件在磁盘上存在、未被 .gitignore 忽略, 但不在版本库里 — "
            "克隆机拿不到它们, 而本地一切正常:\n  " + "\n  ".join(untracked)
        )

    def test_core_governance_docs_are_not_gitignored(self) -> None:
        """核心治理资产不得被 .gitignore 豁免掉入库义务 (CHANGELOG 洞的通用形)。

        与上一条**恰好互补**, 这也是本门禁当初漏掉它的原因: 上一条用的
        ``git ls-files --others --exclude-standard`` 按设计就排除"被忽略"的文件,
        于是把某个核心文档写进 ``.gitignore`` 可以让它永久隐身, 而门禁全绿。
        ``CHANGELOG.md`` 正是这样活了很久: 它是本仓唯一的变更记录载体, 却因
        ``.gitignore`` 里一行 (原第 90 行) 而 (a) 新克隆者看不到任何变更理由,
        (b) ``evals/nl2tool/tasks.yaml`` / ``docs/eval-E1-nl2tool.md`` /
        ``docs/eval-E2-groundtruth.md`` 里"改动必须记 CHANGELOG.md"的义务对新
        克隆者不可履行, (c) 上一条门禁看不见它。

        判据是"两件事都要成立": 既**不被忽略** (否则回退到隐身态), 也**确实被
        git 跟踪** (否则只是把 ignore 删了却忘了 ``git add``, 换个方向同样隐身)。
        判据用 ``git check-ignore`` (退出码 0 即被忽略) 与 ``git ls-files
        --error-unmatch``, 逐个点名而不是只报计数。

        清单只收"仓内读者的事实源"这一类, 刻意**不收**运行期与大件产物
        (``temp/``、``.logs/``、``docs/diagrams/*.png``、``statcatalog/``):
        那些的 local-only 是有据的既定裁定, 混进来只会让本门禁被加豁免从而失效。
        """
        must_be_tracked = (
            "CHANGELOG.md",  # 唯一变更记录载体 (2026-10-05 由 local-only 改判为入库)
        )
        ignored: list[str] = []                                                                   # 攒齐再报: 逐条点名才定位得到
        untracked: list[str] = []                                                                  # 与上面分开: 两种退化的修法不同
        for rel in must_be_tracked:                                                               # 逐个核心资产问两个问题
            probe = subprocess.run(                                                                # check-ignore 退出码 0 = 被忽略
                ["git", "check-ignore", "-q", "--", rel],
                cwd=SKILL_ROOT, capture_output=True, timeout=60)
            if probe.returncode == 0:                                                              # 被忽略即隐身: 无论磁盘上有没有它都等于对克隆者不存在
                ignored.append(rel)
                continue
            listed = subprocess.run(                                                               # 不被忽略还不够, 必须真的进了 index
                ["git", "ls-files", "--error-unmatch", "--", rel],
                cwd=SKILL_ROOT, capture_output=True, timeout=60)
            if listed.returncode != 0:                                                             # 未跟踪: 上一条门禁此刻应该已红, 这里给出定向提示
                untracked.append(rel)
        assert not ignored, (
            "核心治理资产被 .gitignore 忽略, 对新克隆者等于不存在 (而上一条门禁按设计"
            "看不见被忽略的文件):\n  " + "\n  ".join(ignored)
        )
        assert not untracked, (
            "核心治理资产既未被忽略、也未 git 跟踪 — 删掉 ignore 行后忘了 git add:\n  "
            + "\n  ".join(untracked)
        )


# ── 委派缝 (delegation seam) 的发现与判据 ─────────────────────────────
# 抽离件的做法: 实现搬到 src/client_query.py 之类, 原处留一个同名同签名的薄壳,
# **按位置参数**转发 (`src/client.py:424-425` 自陈: 少传一个就错位到
# max_records/columns 且不会报错)。壳的形参表与实现的形参表是两份, 靠人记着
# 同步 —— 任一侧加参数而另一侧漏改, 既不报 TypeError, 也没人发现。
#
# 为什么按"发现"而不是按"表"来守: 手工登记表只能守住登记过的那几条, 而新增
# 委派缝的默认状态恰恰是"不在表里"。故判据自己从 AST 找出全部纯转发壳 (按发现
# 覆盖面, 这一句成立: 新缝一落盘就被纳入扫描), 不依赖任何人记得补一行。
#
# 但"被扫到"不等于"每种退化都被守住": 判据逐条列在 TestDelegationSeamIsGuarded
# 的 docstring 里, 关键字实参只查名与值对调 (不查值是否语义正确), 纯改名与
# 值是表达式的形态不查 —— 覆盖面以那份清单为准, 不以本段为准。

SEAM_SCAN_DIRS = ("src", "rag")  # 只扫可复用库层: evals/ 受铁律 6 禁止跨实验 import, ops/ 是路径调用层 (见 verify_import_graph 的分层判据)

_PROBE = object()  # bind 用的哑值: 只验 arity/传参形态, 不验类型, 故任何对象都行


def _import_table(tree: ast.Module) -> dict[str, str]:
    """from-import 局部名 -> ``模块.符号``。

    走 ``ast.walk`` 是刻意的: 壳内的**延迟导入** (client.py 每个壳都有一行
    ``from src.client_query import cone_search as _cone_search_impl``) 与模块级
    导入同形, 只认模块级会把绝大多数壳漏掉。
    """
    table: dict[str, str] = {}
    for node in ast.walk(tree):  # 全树: 壳内延迟导入与模块级导入同形
        if isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                table[alias.asname or alias.name] = f"{node.module}.{alias.name}"
    return table


def _iter_functions(tree: ast.Module):
    """产出 ``(函数节点, 是否类方法)``: 方法与非方法在接收者槽上的口径不同。"""
    for node in tree.body:  # 模块级函数先出
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield node, False
    for cls in ast.walk(tree):  # 再收类内方法
        if isinstance(cls, ast.ClassDef):
            for item in cls.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    yield item, True


def _forwarded_call(fn):
    """壳体若只剩单条 ``return 目标(位置实参)``, 返回 (目标局部名, 位置实参名, 关键字名, 关键字值的裸名)。

    关键字的**值**只取"裸形参名"这一种 (``None`` 表示该值是表达式如
    ``to_float(radius)``, 本判据不看): 值对调只可能发生在两个关键字互传对方
    名字的形态上, 而那种形态两侧必然都是裸名。

    判据收得紧是刻意的: 只有**纯转发**才是位置错位的高危形态 —— 壳里一旦掺了
    自己的逻辑, 漏改参数通常先撞上别的判据, 而纯转发是"改错了一路绿灯到底"。
    """
    body = [  # 剥掉 docstring 与壳内局部导入后剩下的才是可执行体
        stmt for stmt in fn.body
        # docstring 剥掉: 它是 Expr[Constant], 不算可执行体
        if not (isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant))
        # 壳内局部导入剥掉: 起个别名而已, 不是转发逻辑本身
        and not isinstance(stmt, (ast.Import, ast.ImportFrom))
    ]
    if len(body) != 1:  # 不是"单条 return"就不是纯转发壳
        return None
    ret = body[0]  # 唯一那条语句
    if not isinstance(ret, ast.Return) or not isinstance(ret.value, ast.Call):  # 不是 return 就不是纯转发壳
        return None
    call = ret.value  # 转发调用本体
    if not isinstance(call.func, ast.Name):  # 目标须是裸名 (壳内别名), self.method() 不算
        return None
    if not all(isinstance(arg, ast.Name) for arg in call.args):  # 位置实参须是裸形参名
        return None
    if any(kw.arg is None for kw in call.keywords):  # ``**kwargs`` 展开不受本判据管
        return None
    values = [kw.value.id if isinstance(kw.value, ast.Name) else None for kw in call.keywords]
    return call.func.id, [a.id for a in call.args], [kw.arg for kw in call.keywords], values


def _seam_problems(path: Path) -> list[str]:
    """扫一个文件里的全部委派缝, 返回问题清单 (空 = 全对齐)。

    逐条返回而不是只报计数: 失败信息里要能直接看出"哪条缝的哪一位置错了"。
    """
    import importlib  # 局部导入: 解析目标要真导入实现件, 失败只记问题不炸本文件
    import inspect

    rel = path.relative_to(SKILL_ROOT).as_posix() if path.is_relative_to(SKILL_ROOT) else path.name  # 仓内相对路径: tmp 副本只取文件名
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return []  # 解析不了的文件由编译门禁负责, 不在这里重复判
    imports = _import_table(tree)  # 局部名 -> 模块.符号
    problems: list[str] = []
    for fn, is_method in _iter_functions(tree):  # 方法与非方法的接收者槽口径不同
        if fn.name.startswith("__") and fn.name.endswith("__"):  # dunder 不是委派缝
            continue
        found = _forwarded_call(fn)
        if not found:
            continue
        local, pos, kwargs, kw_values = found
        full = imports.get(local)
        if not full or full.split(".")[0] not in SEAM_SCAN_DIRS:
            continue  # 标准库/三方调用: 参数名不对齐是常态, 不是本仓的错位风险
        try:
            target = getattr(importlib.import_module(full.rpartition(".")[0]), full.rpartition(".")[2])
        except (ImportError, AttributeError):
            continue  # 目标导不进由 import 图门禁负责; 这里不重复判, 免得两处口径打架
        if inspect.isclass(target):
            continue  # 构造器调用 (ColumnConstraint(...)) 不是委派缝
        try:
            signature = inspect.signature(target)
        except (TypeError, ValueError):
            continue  # 取不到签名 (C 扩展等) 不在本判据覆盖面内
        target_params = list(signature.parameters)
        shell_params = [a.arg for a in fn.args.args]
        receiver = shell_params[0] if (is_method and shell_params) else None
        found_problems: list[str] = []
        for index, arg in enumerate(pos):
            if index == 0 and receiver and arg == receiver:
                continue  # 接收者槽: self↔client/matcher 改名是约定 (壳绑实例, 实现接实例), 不是错位
            want = target_params[index] if index < len(target_params) else "<无此参>"
            if want != arg:
                found_problems.append(f"位置 {index} 转发 {arg!r}, 目标该位是 {want!r}")
        filled = set(target_params[: len(pos)])
        for name in kwargs:
            if name not in target_params:
                found_problems.append(f"关键字 {name!r}: 目标无此形参")
            elif name in filled:
                found_problems.append(f"关键字 {name!r}: 已被位置 {target_params.index(name)} 占用")
        forwarded = set(pos) | set(kwargs)
        missing = [p for p in shell_params if p != receiver and p not in forwarded]
        if missing:
            found_problems.append(f"未转发的形参 (静默少一项能力, 不报 TypeError): {missing}")
        # 关键字实参的**值**: 只判"两个关键字互传对方名字"这一种形态
        # (``ra=dec, dec=ra``)。它不报 TypeError、``bind`` 也过、每个名字在目标
        # 签名里都存在, 故上面三条判据全都看不见 —— 正是本类 docstring 点名的
        # "静默查错天区"。判据刻意窄: 纯改名 (``radius_arcsec=radius``) 与
        # 值是表达式 (``radius=to_float(radius)``) 都判不出意图, 不报 ——
        # 宁可漏报, 也不报出无法整改的红 (改名在本仓 28 条缝里实测 0 例)。
        value_of = dict(zip(kwargs, kw_values))
        swapped: set[frozenset[str]] = set()
        for name, value in value_of.items():
            # value 是另一个关键字的名字, 且那个关键字的值又正是 name → 互传
            if value is not None and value != name and value_of.get(value) == name:
                swapped.add(frozenset((name, value)))
        for pair in sorted(swapped, key=sorted):
            low, high = sorted(pair)
            found_problems.append(f"关键字实参的值对调: {low!r} 与 {high!r} 互传对方的名字 (静默查错天区, 不报 TypeError)")
        try:  # 绑一次: 位置段对齐但目标是 keyword-only 时, 真正调用会 TypeError —— 静态提前点名
            signature.bind(*[_PROBE] * len(pos), **{k: _PROBE for k in kwargs})
        except TypeError as exc:
            found_problems.append(f"实参无法绑定到目标签名: {exc}")
        problems.extend(f"{rel}::{fn.name}: {p}" for p in found_problems)
    return problems


def _seam_inventory() -> list[str]:
    """全扫描面的委派缝清单 (``相对路径::函数``), 供语料非空断言用。"""
    import importlib

    found: list[str] = []
    for name in SEAM_SCAN_DIRS:  # 逐个扫描面走一遍
        base = SKILL_ROOT / name
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except (OSError, SyntaxError, UnicodeDecodeError):
                continue
            imports = _import_table(tree)
            rel = path.relative_to(SKILL_ROOT).as_posix()
            for fn, _is_method in _iter_functions(tree):
                hit = _forwarded_call(fn)
                if not hit:
                    continue
                full = imports.get(hit[0])
                if not full or full.split(".")[0] not in SEAM_SCAN_DIRS:
                    continue
                try:
                    target = getattr(importlib.import_module(full.rpartition(".")[0]), full.rpartition(".")[2])
                except (ImportError, AttributeError):
                    continue
                if not isinstance(target, type):
                    found.append(f"{rel}::{fn.name}")
    return found


class TestDelegationSeamIsGuarded:
    """委派缝: 壳与实现的形参表必须逐位对齐, 且**不许静默错位** (R4-02)。

    **N8 于 2026-10-07 重测: 本类在当前 HEAD 上仍有效, 不是待办。**
    N8 记的是「宽网翻出存活体 F2 (删 ``client.py`` 委派壳的 ``max_pages`` 转发) →
    全落在本类」, 并把成因归给审计工具 G8 只扫 7 个子目录、**没覆盖
    ``test/unit/meta/``**, 定性为「基线漂移, 不是判断力问题」。
    重跑一遍负对照 (删 ``max_pages=max_pages`` 转发 → 跑本类) 的结果:
    **4 条转红**, 与 N8 当时的记录一致, 且源文件已还原干净。
    也就是说 N8 描述的**仓内缺口不存在** —— 守门在仓里, 失效的是那次审计的
    扫描清单。那份清单是审计会话的临时产物 (temp/vfy/), 不在本仓, 无从修也不必修。
    登记在此, 是为了下一轮别把它当成"仓里还缺一道闸"重新提一遍。

    守的缺口形态 (Q7 §5(a) 判为 P1 门禁盲区): ``src/client.py`` 的 18 个薄壳
    按**位置参数**转发到抽离件 (``client_query`` / ``client_phase1`` /
    ``client_paging`` / ``client_resolve`` / ``best_export``), 每个 2~13 个形参。
    两侧形参表是两份独立文本, 靠人记着同步 —— 任一侧加参数而另一侧漏改:

    - 少转发一个 → **不报 TypeError** (后面形参都有缺省值), 只是静默少一项能力;
    - 顺序错一位 → **不报 TypeError**, 只表现为查错天区 / 筛不出结果。

    既有守门只覆盖 2 条缝 (``test_client_pagination_sort.py`` 钉了
    ``_fetch_sqlid_data`` 与 ``_count``), 其余 16 条无守门。Q7 实测当前**全部
    对齐**, 所以这不是"现在有 bug", 而是"改了没人知道"。

    **覆盖面以本段为准** (判据逐条列全, 免得"全部纳入覆盖"被读成"每种退化都守住"):

    守得住的退化:
    - 少转发一个形参 → 名单点名 (静默少一项能力, 不报 TypeError);
    - 位置实参错位一位 → 逐位比对 (``swap_pair`` 突变覆盖);
    - 关键字**名**不存在于目标签名 / 与已占位置相撞 → 逐名比对;
    - 整组实参绑不上目标签名 (目标是 keyword-only 之类) → 绑一次;
    - 两个关键字**互传对方的名字** (``ra=dec, dec=ra``) → 互传对调判定
      (``swap_kw`` 突变覆盖)。

    守不住的形态 (判据刻意不猜意图, 宁可漏报也不报无法整改的红):
    - 关键字的值是**表达式** (``radius=to_float(radius)``) → 不查;
    - 纯改名 (``radius_arcsec=radius``) → 不查 (本仓 28 条缝实测 0 例);
    - 关键字的值指向一个**不属于本调用键集**的形参 (单侧改名/串错) → 不查;
      即"只查互传对调", 不查"值是否对应正确参数"。

    **本判据按发现而非按表**: 手工登记表只保得住登记过的那几条, 而新增委派缝
    的默认状态就是不在表里。故判据从 AST 找出全部纯转发壳 —— 现有 28 条
    (src 28 + rag 0) 全部纳入扫描, 新增缝落盘即被扫到。扫到 ≠ 全守住, 守住
    哪几种退化以上面两份清单为准。
    """

    def test_seam_inventory_is_not_empty(self):
        """语料非空: 扫不到任何委派缝时, 上面所有断言都恒真, 证据等于零。

        这条是本类的防空转闸 —— 与 ``test_zero_reference_public_symbols_are_
        reported`` 里"空扫描结果必须判红"同一纪律: 门禁扫到 0 条与门禁坏了
        长得一模一样。
        """
        seams = _seam_inventory()  # 先确认语料非空, 再谈判据
        assert seams, "委派缝扫描结果为空 —— 判据本身失效 (不是'仓里没有委派缝')"
        # 钉住具体几条: 只断数量的话, 扫描范围悄悄改小也能凑够条数
        for expected in ("src/client.py::cone_search", "src/client.py::_fetch_sqlid_data",
                         "src/client.py::_build_form", "src/downloader.py::_merge_region_files"):
            assert expected in seams, f"预期委派缝未被发现: {expected} (实得 {len(seams)} 条)"

    def test_all_delegation_seams_are_parameter_aligned(self):
        """真仓全部委派缝必须逐位对齐 (任一侧加参而另一侧漏改即红)。"""
        problems: list[str] = []
        for name in SEAM_SCAN_DIRS:  # 逐个扫描面走一遍
            base = SKILL_ROOT / name
            if not base.is_dir():
                continue
            for path in sorted(base.rglob("*.py")):
                if "__pycache__" in path.parts:
                    continue
                problems.extend(_seam_problems(path))
        assert not problems, (
            "委派缝与实现签名漂移 (位置错位/漏转发都不报 TypeError, 只会静默出坏结果):\n  "
            + "\n  ".join(problems)
        )

    @pytest.mark.parametrize("mutation", ["drop_tail", "swap_pair", "swap_kw"])
    def test_injected_misaligned_seam_is_caught(self, tmp_path, mutation):
        """注入一条错位缝 -> 同一个判据必须点名它 (**非空转**: 注入 → 红)。

        三种突变各自对应一种真实退化, 且**都不报 TypeError**:
          - ``drop_tail``: 少转发尾部形参 (后面形参都有缺省值) —— 静默少一项能力;
          - ``swap_pair``: 两个同为 float 的位置形参对调 —— 静默查错天区;
          - ``swap_kw``: 位置实参一个不动, 只让两个**关键字**互传对方的值
            (``ra=dec, dec=ra``) —— 每个名字都在目标签名里、``bind`` 也过,
            位置比对一次都不执行, 只有值对调判据能看见它 (这一形态此前无突变覆盖)。

        真仓不被触碰: 突变只发生在 ``tmp_path`` 里的副本上, 而实现件仍从真仓
        导入 —— 于是副本的壳与**真**签名比对, 注入的缺陷必现。
        """
        source = (SKILL_ROOT / "src" / "client.py").read_text(encoding="utf-8")
        # 每个锚点都带尾注释, 保证全文唯一 (client.py 里有 8 处形似行); 第三项是被点名的缝
        anchors = {  # 形态 -> (待替换原文, 替换后原文, 预期被点名的函数名)
            "drop_tail": ("sort, order, nearest_only,  # 排序三件套齐传: 少传即少能力, 站点对缺项不报错",
                          "sort, order,  # 突变: 少转发 nearest_only",
                          "cone_search"),
            "swap_pair": ("self, ra, dec, radius_arcsec, catalog, band,  # 前六项顺序固定: 错位只表现为查错天区",
                          "self, dec, ra, radius_arcsec, catalog, band,  # 突变: ra/dec 对调",
                          "cone_search"),
            "swap_kw": ("self, catalog, constraints, max_rows, ra=ra, dec=dec,  # 位置参数直传: 与实现签名逐位对齐, 少一个就错位到排序项",
                        "self, catalog, constraints, max_rows, ra=dec, dec=ra,  # 突变: 关键字的值对调",
                        "_build_form"),
        }
        old, new, target = anchors[mutation]  # 取本例要注入的那一对
        assert source.count(old) == 1, f"突变锚点必须唯一, 实得 {source.count(old)} 处: {old!r}"
        broken = source.replace(old, new)  # 只改副本: 真仓不受影响
        fake = tmp_path / "client_mutated.py"  # 副本放在 tmp: 真仓不受影响
        fake.write_text(broken, encoding="utf-8")

        problems = _seam_problems(fake)  # 同一个判据读注入后的副本
        assert problems, (
            f"注入 {mutation} 后判据必须点名 src/client.py::{target} —— 实得空清单, "
            "说明这条门禁对这种错位是空转的"
        )
        assert any(target in p for p in problems), f"点名要落到被注入的那条缝: {problems}"
        # 对照在同一用例内: 同一判据对**未突变**的副本必须零问题
        clean = tmp_path / "client_clean.py"
        clean.write_text(source, encoding="utf-8")
        assert not _seam_problems(clean), f"未突变的真源码不得被误报: {_seam_problems(clean)}"
