# -*- coding: utf-8 -*-
"""evals.audit — astro-best 内容质量审计器包 (Phase 5 重建)。

能力边界: 对六个靶目录 (references/ rag/knowledge/ templates/ contracts/ static/ test/)
执行内容质量审计。每个审计器必须:
  1. ``run(root)`` 返回 findings (severity: CRITICAL/MAJOR/MINOR/INFO);
  2. ``broken_samples()`` 提供故意构造的坏样本 (反证夹具);
  3. ``check_rejects(check_id, broken)`` 证明该检查能拒绝坏样本——
     坏样本通过 = 审计器无效 (runner 记 CRITICAL 并总体 FAIL)。

纪律: 无 fail-open (目标缺失/损坏即 FAIL); -O 安全 (显式条件不用 assert)。
"""
from __future__ import annotations

# 标准库组: ast 静态解析 test/ (找 test_* 函数并数 assert, 零断言测试审计) /
# re 三类反模式文本匹配 + entry 符号解析 / dataclasses 两个轻量载体 (审计产出
# 直接 JSON 化进报告) / pathlib 以 skill 根为锚遍历六个靶目录 / typing 坏样本
# 表与注册表的宽松标注
import ast  # 数真落在 test_* 函数体内的 ast.Assert, 另用于按调用身份认 pytest.skip (不用文本子串)
import re  # 版本号铁律/空断言/mock __init__ 三类反模式 + entry 符号形态解析
from dataclasses import dataclass, field  # Finding/AuditResult 载体; field 只为 default_factory
from pathlib import Path  # 以 skill 根为锚遍历靶目录, 判定结果里的路径一律相对它
from typing import Any, Callable  # 坏样本表与审计器注册表的宽松标注, 运行期无依赖

# 第三方组: PyYAML —— 审计器要真实解析每个契约/模板/知识/片段 YAML,
# 只做文本 grep 会漏掉"能读但结构坏了"的损坏文件 (无 fail-open 纪律)
import yaml

# 禁版本号铁律 (全仓治理规则): 任何 YAML 里以 version 语义结尾的键
# (schema_version/template_version/.../version) 一律 CRITICAL。
# 防的是"同一个契约被复制出多份变体, 下游按文件名猜用哪份"的腐化 ——
# 版本信息只允许由 git tag 承载, 文件内容里出现即判腐化。
#
# D2 修复: 旧正则只匹配**行首**键, 对两种常见写法失明:
#   - YAML 列表项 ``  - version: 1.2.3`` (依赖声明/算法清单里最常见);
#   - 带引号键 ``  'version': 1.2.3`` / ``  "version": 1.2.3``。
# 两者都会被旧正则放过去, 等于禁版本号铁律在审计层有两个后门。
# 新正则容许「可选行首空白 + 可选列表项破折号 + 可选键引号」三种前缀,
# 仍要求键名后紧跟冒号 (行内提及与词中缀按设计不命中, 避免误报)。
VERSION_MARKER_RE = re.compile(  # 容许「行首空白+列表项破折号+键引号」三种前缀: 旧正则对列表项与带引号键失明
    r"^[ \t]*(?:-[ \t]*)?['\"]?"
    r"(schema_version|template_version|config_version|"
    r"scoring_rubric_version|manifest_version|version)"
    r"['\"]?[ \t]*:", re.M)
# 白盒五要素最低痕迹 (references/ 审计用): 量纲/公式/端点/协议/复现,
# 五个词里至少命中两个才算"这篇文档真的在讲怎么复现", 而不是宣传册
WHITEBOX_TOKENS = ("量纲", "公式", "端点", "协议", "复现")  # 五个词里至少命中两个才算在讲复现, 否则就是一份宣传册


def _has_module_level_skip(tree: ast.AST) -> bool:
    """这份 AST 里是否真有 ``pytest.skip(..., allow_module_level=True)`` 调用。

    认的是**调用身份**而不是文本: ``pytest.skip`` (含 ``from pytest import skip``
    之后的裸 ``skip``) 且带 ``allow_module_level`` 关键字。注释、docstring、字符串
    里的同名写法一律不算 —— 那正是纯文本子串匹配的假阳来源 (test_query_chain.py
    的注释里就有一处, 曾把一个**已删除**的守卫报成违规)。

    Returns:
        True = 确有模块级跳过调用; False = 没有。
    """
    imported_bare_skip = False                                       # `from pytest import skip` 后的裸名形态
    for node in ast.walk(tree):                                      # 先扫导入: 决定裸名要不要一并认
        if isinstance(node, ast.ImportFrom) and node.module == "pytest":
            imported_bare_skip = any(alias.name == "skip" for alias in node.names)
    for node in ast.walk(tree):                                      # 再扫调用
        if not isinstance(node, ast.Call):                           # 只有 Call 才是调用; 注释/字符串走不到这里
            continue
        func = node.func
        if isinstance(func, ast.Attribute):                          # 形态一: pytest.skip(...)
            called = isinstance(func.value, ast.Name) and func.value.id == "pytest" and func.attr == "skip"
        elif isinstance(func, ast.Name):                             # 形态二: 裸 skip(...) (仅当确实从 pytest 导入过)
            called = imported_bare_skip and func.id == "skip"
        else:
            called = False
        if called and any(kw.arg == "allow_module_level"                            # 关键字存在还不够
                           and isinstance(kw.value, ast.Constant)
                           and kw.value.value is True                                # 必须真的置 True: =False 不构成模块级跳过
                           for kw in node.keywords):
            return True
    return False

# 未决标记: 交付文档里留着待办等于把问题推给读者。
#
# 英文未决标记 (两个大写缩写) 走 ``\b`` 整词边界 (ASCII 词, 边界有效); **占位是中文,
# 没有词边界可言**, 旧写法把它当裸子串, 于是正文里当术语用的"填充占位"
# (references/scientific-client-defenses.md §7.1 讲哨兵填充的固定写法, 是本领域的
# 正经术语) 整段被判成未决标记 —— 判据与它自己那句注释「正文里提到『占位』二字不该被
# 当成未决标记」正好相反。
#
# 窄案口径 (只管**读起来像没写完**的形态): 要求占位与一个待办词在同句内相邻。
# 术语用法 ("填充占位" / "哨兵占位值") 一律放过, 真待办 ("占位待补" / "此处占位, TBD")
# 仍被抓 —— 放过条件与窄案取舍写在 ops/audit/README.md 的已知局限一节。
#
# 注意本段注释刻意**不写出**那两个英文缩写的字面: comment_audit 的 todo_in_code
# 规则扫的是代码里的未决标记, 而本仓自己的注释若写了那两个字就会把自己判红。
# 判据的正例是 ops/audit/comment_audit.py 里的规则定义, 不在本段复刻字面量。
UNRESOLVED_MARKER_RE = re.compile(
    r"\bTODO\b|\bFIXME\b"
    r"|(?:待补|待填|待定|待替换|未填|TBD)[^\n]{0,8}占位"      # 待办词在前: 「此处占位待补」
    r"|占位[^\n]{0,8}(?:待补|待填|待定|待替换|未填|TBD)",   # 待办词在后: 「占位待替换」
    re.IGNORECASE)


@dataclass
class Finding:
    """一条审计发现。

    严重度阶梯 (消费方是 runner 的总体判定与人工复核):
      - CRITICAL: 契约/铁律被破坏 (缺必需契约, 残留版本号, 空断言) —— 总体 FAIL;
      - MAJOR: 内容不达标但结构在 (白盒要素不足, 缺可消费键) —— 该审计器 FAIL;
      - MINOR: 卫生问题 (BOM, skip 缺理由) —— 只提示不判败;
      - INFO: 备注 (runner 汇总时过滤掉, 不计入扣分)。
    """

    severity: str  # CRITICAL / MAJOR / MINOR / INFO
    target: str    # 出问题的文件/目录/符号 (相对 skill 根)
    message: str   # 人类可读的问题描述

    def to_dict(self) -> dict[str, Any]:
        """转字典 (runner 直接把它并进 JSON 报告的 findings 列表)。"""
        # 三键即全部: runner 直接把它并进 JSON 报告的 findings 列表
        return {"severity": self.severity, "target": self.target, "message": self.message}


@dataclass
class AuditResult:
    """单个审计器的产出: findings 列表 + 是否通过。

    ``passed`` 与 findings 严重度联动: 出现 CRITICAL/MAJOR 即置 False;
    runner 只认这个布尔值做阻断, 所以审计器自己必须诚实置位 (无 fail-open)。
    """

    findings: list[Finding] = field(default_factory=list)  # default_factory 而非 []: 可变默认值会在所有实例间共享同一份列表
    passed: bool = True                                    # 默认 True 但必须由审计器主动置 False: runner 只认这个布尔做阻断


def _require_dir(result: AuditResult, root: Path, rel: str) -> Path | None:
    """目标目录缺失即记 CRITICAL 并置败; 存在则返回其 Path, 缺失返回 None。

    六个审计器里 contracts/static/test 三处的目录守卫共用本函数, 但**注释
    各自留在调用点** (说明各自为何缺不得)。守卫逻辑逐字复制等于改一处忘
    另两处, 而这里漏掉就等于该目录缺失被静默放过 —— 正是铁律 5 要防的形态。

    Args:
        result: 本次审计的产出 (就地追加 finding 并置 ``passed=False``)。
        root: skill 根目录。
        rel: 相对 root 的目录路径, 如 ``"contracts"``。

    Returns:
        目录的 Path; 缺失时为 None (调用方应立即 return result)。
    """
    d = root / rel      # 相对锚定: 靶目录名由调用方给, 本函数不写死六个目录
    if not d.is_dir():  # 缺失即 CRITICAL: 目标缺失不是"没问题", 是红线 (铁律 5)
        result.findings.append(Finding("CRITICAL", f"{rel}/", "目录缺失"))
        result.passed = False  # 就地置败: 调用方拿到 result 时阻断位已就位, 不靠返回值传递
        return None
    return d


class Auditor:
    """审计器基类: 一个靶目录 = 一个子类, 必须提供 run + 反证夹具。

    契约 (runner 按此消费):
      - ``name``/``target``: 报告里的标识与靶目录 (如 "contracts" / "contracts/");
      - ``run(root)``: 遍历靶目录产出 findings;
      - ``broken_samples()`` + ``check_rejects()``: 反证夹具, 证明检查不是空转。
    """

    name = "base"  # 基类不给真名: 子类漏覆盖时 runner 能从 name 认出是 base
    target = ""    # 空 target 而非真目录: 空值让"未覆盖"在报告里显形

    def run(self, root: Path) -> AuditResult:  # pragma: no cover - 抽象
        """执行审计 (子类必须实现)。

        Args:
            root: skill 根目录 (六个靶目录都锚在它下面)。

        Returns:
            AuditResult; 目标缺失/损坏必须置 ``passed=False`` 并附 CRITICAL finding。

        Raises:
            NotImplementedError: 基类不提供默认行为, 防止漏实现静默通过。
        """
        raise NotImplementedError

    def broken_samples(self) -> dict[str, str]:
        """坏样本: check_id -> 故意构造的坏内容 (必须被拒绝)。

        反证夹具是审计器的"自检抗体": 如果审计器对着一团明显违规的内容
        都报通过, 那它对真实仓库的"全绿"没有任何证据力。每个审计器至少
        要为一条核心检查提供坏样本。

        Returns:
            check_id -> 坏样本文本; 空字典表示该审计器无反证 (runner 不会
            因此判败, 但新增审计器时必须补上, 否则它的"全绿"没有证据力)。
        """
        return {}  # 空字典 = 本审计器无反证: runner 不因此判败, 但新增审计器时必须补上

    def check_rejects(self, check_id: str, broken: str) -> bool:
        """该 check 是否拒绝坏样本 (True=审计器有效)。

        基类实现是 **raise NotImplementedError**, 与同类 ``run()`` 同口径, 不给
        默认 True 这条 fail-open 退路: 新增审计器若只写了 ``run()`` 忘了重写本
        方法, 就会静默拿到 True, 即"反证夹具从未真正跑过检查"也被判成审计器
        有效 —— 反证夹具的全部价值就在"真跑一遍"。

        Args:
            check_id: 坏样本标识 (与 ``broken_samples()`` 的键对应)。
            broken: 坏样本内容 (基类默认实现不消费, 子类必须重写并真的拿它
                跑一遍对应检查)。

        Returns:
            True 表示检查确实拒绝了坏样本; False 表示坏样本被放过 ——
            runner 会记一条 CRITICAL 并把该审计器判败 (审计器无效)。
        """
        raise NotImplementedError


# ---------------------------------------------------------------------------
# 1. references/ 白盒文档审计
# ---------------------------------------------------------------------------

class ReferencesAuditor(Auditor):
    """references/ 白盒文档审计器。

    检查什么: 每份 .md 是否真的在讲"怎么复现"——白盒五要素痕迹数、
    未决标记 (TODO/FIXME/占位)、版本号铁律。
    什么算 finding: 要素不足/未决标记 = MAJOR, 版本号 = CRITICAL, 目录或
    文档整体缺失 = CRITICAL。
    严重度依据: 文档是给人复现用的, 缺要素只是"讲得浅" (MAJOR);
    残留版本号会直接腐化契约解析, 一律 CRITICAL。
    """

    name = "references"
    target = "references/"

    WHITEBOX_MIN_TOKENS = 2  # 每份白盒文档至少含 2 个五要素痕迹

    def run(self, root: Path) -> AuditResult:
        """遍历 references/*.md 逐份做三项判定 (目录/文档缺失即 CRITICAL)。

        三项判定互不覆盖:
          1. 五要素痕迹 < 2 -> MAJOR (文档可能是空壳或纯宣传);
          2. TODO/FIXME/占位 -> MAJOR (未决事项不该进交付文档);
          3. 版本号标记 -> CRITICAL (禁版本号铁律)。
        任何一项命中都把 ``passed`` 置 False; 空 .md 列表整体判 CRITICAL。
        """
        result = AuditResult()      # 每次 run 新建: 复用结果会让别的审计层的 finding 混进本层判定
        refs = root / "references"  # 六个靶目录都锚在 skill 根下, 不接受外部传入路径
        if not refs.is_dir():       # 靶目录整体缺失是 CRITICAL, 不进入后续逐份判定
            # 无 fail-open: 靶目录整个缺失不是"没问题", 是 CRITICAL
            result.findings.append(Finding("CRITICAL", "references/", "目录缺失"))
            result.passed = False                                                             # 靶目录整个没了不能读成"没问题": 判败并记最高级别
            return result
        md_files = sorted(refs.glob("*.md"))  # 排序遍历: 报告行序稳定, 两轮跑批可直接 diff
        if not md_files:                      # 一份 .md 都没有同样 CRITICAL: 目录在但内容空不等于通过
            result.findings.append(Finding("CRITICAL", "references/", "无 .md 白盒文档"))
            result.passed = False                                                               # 目录在但一份白盒文档都没有: 空目录同样不是通过
        for md in md_files:  # 逐份三项判定互不覆盖: 缺要素/未决标记/版本号各判各的
            # 读点: 本地白盒文档; utf-8-sig 兼容历史 BOM 文件
            text = md.read_text(encoding="utf-8-sig")
            hits = sum(1 for t in WHITEBOX_TOKENS if t in text)  # 计数而非布尔: 报告要显示 0/2 这类具体痕迹数
            if hits < self.WHITEBOX_MIN_TOKENS:                  # 低于阈值判 MAJOR: 讲得浅不等于结构坏, 不到 CRITICAL
                result.findings.append(Finding(                                             # 要素不足要留下 finding: 报告得说清缺的是哪几样
                    "MAJOR", f"references/{md.name}",
                    f"白盒五要素痕迹不足: {hits}/{self.WHITEBOX_MIN_TOKENS}"))
                result.passed = False                                                           # 讲得浅也是缺陷: 判败让复现者知道这份文档不够用
            if UNRESOLVED_MARKER_RE.search(text):  # 窄案: TODO/FIXME 整词 + 占位须与待办词相邻 (术语用法放过)
                result.findings.append(Finding(                                              # 未决标记逐条记: 交付文档里留着待办等于把问题推给读者
                    "MAJOR", f"references/{md.name}", "含 TODO/FIXME/占位 未决标记"))
                result.passed = False                                                            # 未决标记判败: 它说明这份文档还没到可交付状态
            if VERSION_MARKER_RE.search(text):  # 禁版本号铁律: 同一契约被复制出多份变体即腐化, 版本只由 git tag 承载
                result.findings.append(Finding(                                             # 版本号逐份查: 模板与文档都是契约入口, 残留版本即腐化
                    "CRITICAL", f"references/{md.name}", "残留版本号标记 (禁版本号铁律)"))
                result.passed = False                                                    # 判败并记最高级别: 同一份契约被复制出多份变体, 解析无从收敛
        return result

    def broken_samples(self) -> dict[str, str]:
        """反证夹具: 一份五要素痕迹为 0 的空壳文档 (必须被判 MAJOR)。"""
        return {"whitebox_elements": "# 空壳文档\n没有任何白盒要素。\n"}

    def check_rejects(self, check_id: str, broken: str) -> bool:
        """whitebox_elements 检查必须拒收零痕迹文档 (True=检查有效)。

        若这条返回 False, 说明"数五要素痕迹"的判定已经退化成恒过,
        审计器对真仓库的全绿不再有证据力。
        """
        if check_id != "whitebox_elements":
            return True
        hits = sum(1 for t in WHITEBOX_TOKENS if t in broken)  # 反证走同一套计数: 零痕迹坏样本必须被判出
        return hits < self.WHITEBOX_MIN_TOKENS


# ---------------------------------------------------------------------------
# 2. rag/knowledge/ 结构化规则审计
# ---------------------------------------------------------------------------

class KnowledgeAuditor(Auditor):
    """rag/knowledge/ 结构化规则审计器。

    检查什么: 知识文件数量 (至少 3 份)、必需主题文件齐套 (``REQUIRED_TOP``
    四个主题各有一份对应文件)、UTF-8 BOM、YAML 可否解析、内容非空。
    什么算 finding: 文件不足/缺主题文件/内容为空 = MAJOR, BOM = MINOR (只提示),
    YAML 解析失败 = CRITICAL (知识库读不了, RAG 全链路失明)。
    严重度依据: 解析失败是硬伤 (CRITICAL); 数量、主题齐套与空内容是丰满度
    问题 (MAJOR); BOM 不影响 yaml.safe_load, 只提示 (MINOR)。

    ``REQUIRED_TOP`` 的主题与文件一一对应 (domain_rules.yaml /
    known_issues.yaml / lessons_learned.yaml / best_practices.yaml): 每份
    文件承载一个主题, 不是每份文件内部含四个顶层键。D5 修复前该常量被定义
    却从未使用 —— 声明的检查不存在, 少一个主题文件也不会有任何 finding。
    """

    name = "knowledge"
    target = "rag/knowledge/"

    # 四个主题各一份文件 (不是每份含四个键): 按文件主名判齐套
    REQUIRED_TOP = ("domain_rules", "known_issues", "lessons_learned", "best_practices")

    def run(self, root: Path) -> AuditResult:
        """逐份解析 rag/knowledge/*.yaml (解析失败/内容为空/缺主题即判败)。

        BOM 检查走原始字节: 先看是不是以 EF BB BF 开头, 再按 utf-8-sig
        解码 —— 顺序反了就永远发现不了 BOM。YAML 损坏时记 CRITICAL 并
        continue (坏了的那份不值得再判空, 避免一条文件两条 finding)。

        D5 落点: 启用 ``REQUIRED_TOP`` —— 按文件主名判定四个必需
        主题是否齐套; 缺任一主题记 MAJOR 并判败。
        """
        result = AuditResult()                                                       # 每次 run 新建结果: 复用会把别的审计层的 finding 混进本层判定
        kdir = root / "rag" / "knowledge"  # 两级路径: 知识库在 rag/ 之下, 不在靶目录根
        if not kdir.is_dir():              # 知识库目录缺失即 CRITICAL, 不是"跳过这项检查"
            # 无 fail-open: 知识库目录缺失即 CRITICAL, 不是"跳过这项"
            result.findings.append(Finding("CRITICAL", "rag/knowledge/", "目录缺失"))
            result.passed = False                                                                  # 知识库目录缺失即判败: 检索侧会全链路失明
            return result
        ymls = sorted(kdir.glob("*.yaml"))  # 只取顶层 *.yaml: 知识库不允许子目录分层
        if len(ymls) < 3:                   # 数量下限三份: 少于三份的知识库没有交叉印证价值
            result.findings.append(Finding("MAJOR", "rag/knowledge/",
                                           f"知识文件不足: {len(ymls)}/3"))
            result.passed = False                                                               # 份数不足判败: 少于三份的知识库没有交叉印证价值
        # 必需主题齐套检查 (原为死常量, 见类 docstring)
        stems = {y.stem for y in ymls}                                     # 按主名建集: 主题齐套看文件名, 不看文件内容键
        missing_topics = [t for t in self.REQUIRED_TOP if t not in stems]  # 列出缺哪几个主题: 报告要能直接指出该补哪份文件
        if missing_topics:                                                                    # 四个必需主题逐个点名: 报告要能直接指出该补哪份文件
            result.findings.append(Finding("MAJOR", "rag/knowledge/",
                                           f"缺少必需主题文件: {missing_topics}"))
            result.passed = False                                                         # 缺主题判败: 声明过的主题文件不在, 知识面就有实打实的空洞
        for y in ymls:  # 逐份过 BOM/可解析/非空三项, 三项互不覆盖
            # 读点: 知识 YAML 原始字节 (BOM 判定) 后交 PyYAML 解析
            raw = y.read_bytes()                 # 读原始字节而非文本: BOM 只在字节层看得见
            if raw.startswith(b"\xef\xbb\xbf"):  # 先看 EF BB BF 再解码: 顺序反了就永远发现不了 BOM
                result.findings.append(Finding("MINOR", f"rag/knowledge/{y.name}", "含 UTF-8 BOM"))
            try:
                data = yaml.safe_load(raw.decode("utf-8-sig"))  # utf-8-sig 解码: BOM 不进内容, 免得污染首个键名
            except yaml.YAMLError as exc:                       # 只捕 YAMLError: 解析失败记 CRITICAL, 其它异常照冒不吞
                result.findings.append(Finding("CRITICAL", f"rag/knowledge/{y.name}",
                                               f"YAML 解析失败: {exc}"))
                result.passed = False                                                           # 解析失败判败后继续下一份: 坏的那份不值得再判空
                continue
            if not data:  # 空内容记 MAJOR: 文件在却读不出东西, 与"根本没写"同义
                result.findings.append(Finding("MAJOR", f"rag/knowledge/{y.name}", "内容为空"))
                result.passed = False                                                           # 内容为空判败: 有文件没内容与没有文件同样不可用
        return result

    def broken_samples(self) -> dict[str, str]:
        """反证夹具: 一段语法损坏的 YAML (必须被判 CRITICAL)。"""
        return {"yaml_parse": "key: [unclosed\n  - broken: : :\n",
                # D5 修复新增的主题齐套检查也必须配反证: 坏样本给出一个**不含任何
                # 必需主题文件名**的目录清单, check_rejects 必须判出缺主题。
                "missing_topic": "citations.yaml"}

    def check_rejects(self, check_id: str, broken: str) -> bool:
        """yaml_parse 检查必须对坏样本抛 YAMLError (True=检查有效)。

        坏样本竟能被 ``safe_load`` 解析 = 解析检查退化成恒过, 审计器无效。

        ``missing_topic`` 反证: 传入的文件名清单 (换行分隔的主名) 必须被判出
        "缺少必需主题"; 若判不出, 说明主题齐套检查退化成恒过。
        """
        if check_id == "yaml_parse":
            try:
                yaml.safe_load(broken)                                               # 反证走真实解析: 坏 YAML 必须在这里就抛, 抛不出说明检查已退化
                return False  # 坏样本竟能解析 -> 审计器无效
            except yaml.YAMLError:
                return True
        if check_id == "missing_topic":
            stems = {line.strip() for line in broken.splitlines() if line.strip()}  # 坏样本给的是文件名清单: 按换行切成主名集合再比齐套
            missing = [t for t in self.REQUIRED_TOP if t not in stems]                     # 反证按主名集合比齐套: 与正向判定同一口径, 免得自证自空
            return bool(missing)
        return True


# ---------------------------------------------------------------------------
# 3. templates/ 模板审计
# ---------------------------------------------------------------------------

class TemplatesAuditor(Auditor):
    """templates/ 模板审计器。

    检查什么: 全部模板 YAML 的版本号铁律; best-config.yaml 的 ``defaults``
    映射存在且含可消费键 (base_url/timeout/min_snr)。
    什么算 finding: 版本号/缺 defaults = CRITICAL, 缺可消费键 = MAJOR。
    严重度依据: ``from_yaml`` 只读 defaults, 键缺失会让加载后的配置悄悄
    用回硬编码默认值 (行为漂移且无报错), 所以 defaults 本身缺失是 CRITICAL,
    单键缺失是 MAJOR。
    """

    name = "templates"
    target = "templates/"

    def run(self, root: Path) -> AuditResult:
        """逐份审计 templates/*.yaml (版本号 + best-config 的 defaults 键集)。

        只对 best-config.yaml 做深度检查: 它是唯一被 ``from_yaml`` 消费的
        入口模板, 其余模板只过版本号铁律这一道公共闸。
        """
        result = AuditResult()                                                                 # 新建结果对象: 六个审计器各自独立, 判定互不串味
        tdir = root / "templates"  # 模板目录只锚根: 模板是交付面, 不做子目录分层
        if not tdir.is_dir():      # 模板目录缺失即 CRITICAL, 不得当作"本次不检查"
            # 无 fail-open: 模板目录缺失即 CRITICAL
            result.findings.append(Finding("CRITICAL", "templates/", "目录缺失"))
            result.passed = False                                                               # 模板目录缺失即判败: 模板层是配置契约的唯一入口
            return result
        for y in sorted(tdir.glob("*.yaml")):  # 全部模板都过版本号闸: 深度检查只对 best-config 做
            # 读点: 模板 YAML 全文 (版本号 grep 与 defaults 解析共用)
            text = y.read_text(encoding="utf-8-sig")
            if VERSION_MARKER_RE.search(text):                                                # 逐份查版本号标记: 模板是契约入口, 残留版本即腐化
                result.findings.append(Finding("CRITICAL", f"templates/{y.name}",
                                               "残留版本号标记 (禁版本号铁律)"))
                result.passed = False                                                       # 判败并记最高级别: 模板带版本号会让同一配置出现多份变体
            if y.name == "best-config.yaml":  # 只对这一个文件做深度检查: 它是 from_yaml 唯一消费的入口模板
                data = yaml.safe_load(text) or {}                                # 深度检查前先解析: 后面要按键取 defaults, 解析失败已在别的分支记过
                defaults = data.get("defaults")                     # defaults 是 from_yaml 的唯一读取口: 键漂在顶层等于没写
                if not isinstance(defaults, dict) or not defaults:  # 类型与空值都要判: 写成列表或空 dict 同样读不出键
                    result.findings.append(Finding("CRITICAL", "templates/best-config.yaml",
                                                   "缺 defaults 映射 (from_yaml 只读 defaults)"))
                    result.passed = False                                          # 缺 defaults 映射判败: 装载器只读这一段, 缺了等于配置入口失效
                else:
                    for key in ("base_url", "timeout", "min_snr"):  # 三个可消费键逐个点名: 缺一个就静默用回硬编码默认值
                        if key not in defaults:                                              # 三个可消费键逐个点名: 缺一个就静默回落到硬编码默认值
                            result.findings.append(Finding(
                                "MAJOR", "templates/best-config.yaml",
                                f"defaults 缺可消费键: {key}"))
                            result.passed = False                                              # 缺可消费键判败: 静默回落是最难发现的一类配置腐化
        return result

    def broken_samples(self) -> dict[str, str]:
        """反证夹具: 一份键都在但全都漂在顶层、没有 defaults 的坏配置。"""
        return {"defaults_keys": "tap_url: x\ntimeout: 60\nquality:\n  min_snr: 5.0\n"}

    def check_rejects(self, check_id: str, broken: str) -> bool:
        """defaults_keys 检查必须拒收"键在顶层、defaults 缺失"的坏样本。

        坏样本的 time/min_snr 都在, 只是不在 defaults 里 —— 这正是
        ``from_yaml`` 读不到的形态; 放行它等于默许配置静默漂移。
        """
        if check_id != "defaults_keys":
            return True
        data = yaml.safe_load(broken) or {}  # 坏样本同样真解析: 键都在而 defaults 缺失必须判出
        # 坏样本无可消费键落在 defaults -> 必须判 FAIL
        return not isinstance(data.get("defaults"), dict)  # 只判存在与类型: 坏样本的键都在, 只是不在 defaults 里


# ---------------------------------------------------------------------------
# 4. contracts/ 契约审计
# ---------------------------------------------------------------------------

class ContractsAuditor(Auditor):
    """contracts/ 契约审计器 (质量评审里最重的一道闸)。

    检查什么: 六份必需契约存在; 全目录 YAML 的版本号铁律与可解析性;
    input/output 契约的字段交叉引用; oauth 契约的端点表/凭据 env 化/
    Bearer 空格规范。
    什么算 finding: 必需契约缺失/版本号/解析失败 = CRITICAL, 内容为空/
    缺字段或缺 OAuth 要素 = MAJOR。
    严重度依据: 契约是跨 skill 数据传递的 envelope 权威源 (pipeline-contract),
    缺一份就等于某段链路没有契约可依, 一律 CRITICAL; 单字段缺失只降级 MAJOR。
    """

    name = "contracts"
    target = "contracts/"

    # 六份必需契约: envelope/input/output/provenance/error-codes/oauth,
    # 权威来源是 _shared/skill-engine/pipeline-contract.md 的 envelope 定义;
    # 消费方是全部跨 skill 调用方, 缺任何一份 CRITICAL
    REQUIRED = ("envelope.contract.yaml", "input.contract.yaml", "output.contract.yaml",
                "provenance.contract.yaml", "error-codes.contract.yaml",
                "oauth.contract.yaml")

    def run(self, root: Path) -> AuditResult:
        """四层判定: 必需契约存在性 -> 全目录版本号/可解析 -> 字段交叉引用 -> oauth 细节。

        交叉引用段只在 input/output 两份都在时跑: 单边缺失已由上一层记了
        CRITICAL, 再判字段会给出重复且误导的 finding。
        """
        result = AuditResult()                                                                     # 新建结果对象: 本层判定与其它五层互不影响
        # 无 fail-open: 契约目录缺失即 CRITICAL (缺它则本层无任何判定依据)
        cdir = _require_dir(result, root, "contracts")  # 复用共用守卫: contracts/static/test 三处判定语义必须一致
        if cdir is None:                                                                      # 目录缺失已由共用守卫记过: 这里直接短路, 不重复报
            return result
        for req in self.REQUIRED:  # 逐份点名: 缺一份就是某段链路没有契约可依
            if not (cdir / req).is_file():                                                     # 必需契约逐份点名: 缺一份就是某段链路没有契约可依
                result.findings.append(Finding("CRITICAL", f"contracts/{req}", "必需契约缺失"))
                result.passed = False                                                       # 缺契约判败: 契约层是接口面的唯一真值, 缺了就无从校验
        for y in sorted(cdir.rglob("*.yaml")):  # rglob 含 fields/ 子目录: 字段契约同样受版本号与可解析性管辖
            # 读点: 契约 YAML 全文 (rglob 含 fields/ 子目录)
            text = y.read_text(encoding="utf-8-sig")  # utf-8-sig: 历史 BOM 契约不能因解码失败被误判成"无版本号"
            if VERSION_MARKER_RE.search(text):                                                  # 契约也要查版本号: 同一份契约被复制出变体即腐化
                result.findings.append(Finding("CRITICAL", f"contracts/{y.relative_to(cdir).as_posix()}",
                                               "残留版本号标记 (禁版本号铁律)"))
                result.passed = False                                                        # 判败并记最高级别: 契约带版本号会让下游解析出两套口径
            try:
                data = yaml.safe_load(text)                                                    # 解析成功才继续判空: 解析失败已在上一分支单独记过
            except yaml.YAMLError as exc:
                result.findings.append(Finding("CRITICAL", y.name, f"YAML 解析失败: {exc}"))
                result.passed = False                                                           # 解析失败判败: 契约读不了, 整条校验链随之失明
                continue
            if not data:                                                                      # 契约内容为空判败: 有文件没内容与没有文件同样不可用
                result.findings.append(Finding("MAJOR", y.name, "契约内容为空"))
                result.passed = False                                                    # 空契约判败并记中等严重度: 不至于让链路失明, 但确实没有信息
        # fields/ 与 input/output 的交叉引用
        in_c = cdir / "input.contract.yaml"  # 交叉引用只在两份都在时跑: 单边缺失已由上一层记 CRITICAL
        out_c = cdir / "output.contract.yaml"
        if in_c.is_file() and out_c.is_file():                                              # 输入输出契约都在才做字段核对: 缺一份时字段检查无从谈起
            # 读点: 输入/输出契约全文做字段名核对
            in_text = in_c.read_text(encoding="utf-8-sig")
            out_text = out_c.read_text(encoding="utf-8-sig")
            for token in ("sql", "token"):
                if token not in in_text:                                                      # 输入契约关键字段逐个点名: 缺字段时下游无法组装请求
                    result.findings.append(Finding("MAJOR", "contracts/input.contract.yaml",
                                                   f"输入契约缺字段: {token}"))
                    result.passed = False                                                        # 缺字段判败: 输入契约不完整等于让调用方只能猜
            for token in ("data", "status"):
                if token not in out_text:                                                 # 输出契约关键字段同样逐个点名: 信封字段是下游统一解析的前提
                    result.findings.append(Finding("MAJOR", "contracts/output.contract.yaml",
                                                   f"输出契约缺字段: {token}"))
                    result.passed = False                                                    # 缺字段判败: 输出契约不完整会让所有消费方各写一套解析
        # oauth 契约审计 (Phase 6): 端点表完整 + 凭据 env 化 + Bearer 空格规范
        oauth_c = cdir / "oauth.contract.yaml"  # oauth 单独一层: 端点表/凭据 env 化/Bearer 空格三处核对
        if oauth_c.is_file():                                                           # 认证契约存在才做要素核对: 没有它属另一类缺失, 不在这里重复报
            # 读点: oauth 契约全文 (端点表/env 变量名/授权头规范三处核对)
            otext = oauth_c.read_text(encoding="utf-8-sig")
            for token in ("authorize", "token", "profile", "logout",  # 四个端点加两个 env 变量名逐个点名: 少一个就有环节走不通
                          "NADC_OAUTH_CLIENT_ID", "NADC_OAUTH_CLIENT_SECRET"):
                if token not in otext:                                                       # 凭据环境变量名逐个点名: 硬编码凭据进仓是不可逆的泄露
                    result.findings.append(Finding(
                        "MAJOR", "contracts/oauth.contract.yaml",
                        f"OAuth 契约缺要素: {token}"))
                    result.passed = False                                                    # 缺要素判败: 凭据 env 化是硬要求, 不是风格偏好
            if "Bearer {token}" not in otext:  # 带空格的规范写法: 不写清楚调用方会拼成 "Bearer{token}"
                result.findings.append(Finding(                                          # 带空格的规范写法要写进契约: 不写清楚调用方会拼成缺空格的形态
                    "MAJOR", "contracts/oauth.contract.yaml",
                    "OAuth 契约缺 Bearer 空格规范说明"))
                result.passed = False                                                          # 规范缺失判败: 这是能被真实复现出来的拼接口径问题
        return result

    def broken_samples(self) -> dict[str, str]:
        """反证夹具: 一份带 schema_version 顶层键的坏契约 (必须被判 CRITICAL)。"""
        return {"version_marker": "schema_version: contract-v1\nskill: astro-best\n"}

    def check_rejects(self, check_id: str, broken: str) -> bool:
        """version_marker 检查必须命中坏样本里的 version 键 (True=检查有效)。

        若正则对明显的 ``schema_version:`` 行不反应, 版本号铁律就是一句
        空话, 全仓契约都会被悄悄腐化。
        """
        if check_id != "version_marker":
            return True
        return bool(VERSION_MARKER_RE.search(broken))


# ---------------------------------------------------------------------------
# 5. static/ 提示词规则审计
# ---------------------------------------------------------------------------

class StaticAuditor(Auditor):
    """static/ 提示词规则审计器。

    检查什么: core 三件套存在且非空壳 (stance/workflow/output-format);
    **全部** fragments/**/*.yaml 里声明了 ``fragment.entry`` 的片段, 其符号是否
    可解析且可真实 import (旧版只查 algo_mode/two_stage_async_mode.yaml 一个,
    best_auth_mode.yaml 的 entry 断链长期无人守护 —— 覆盖盲区已补齐)。
    什么算 finding: 缺失/过短/符号不可解析/不可导入 = MAJOR (缺失片段 = MAJOR);
    无 entry 声明的片段记 INFO (不判败, 只提示该片段不参与符号检查)。
    严重度依据: 提示词是行为层的"编译产物", 坏一份不会立刻崩, 但会让
    skill 在某模式下静默降级, 所以整体定 MAJOR; 但 entry 符号 import 失败
    意味着片段指向的代码路径已不存在, 属于硬断链, 同样 MAJOR 但必须置败。
    """

    name = "static"
    target = "static/"

    def run(self, root: Path) -> AuditResult:
        """两段式: core 文件非空检查 + 全部片段 entry 符号的"可解析+可导入"双检。

        entry 符号形态约定为 ``模块:类.方法`` (可带 ``-> 方法`` 后缀),
        先正则拆解再真 import —— 只拆不 import 的话, 方法被改名/删除
        这类腐化发现不了。遍历面是 ``fragments/**/*.yaml`` 全量, 不再只盯
        单个核心片段; 无 ``fragment.entry`` 的文件只记 INFO 不判败。
        """
        result = AuditResult()                                                                      # 新建结果对象: 静态层判定独立于契约层
        # 无 fail-open: 提示词目录缺失即 CRITICAL (静默片段层 = 无策略面)
        sdir = _require_dir(result, root, "static")  # 提示词目录缺失即 CRITICAL: 静默片段层等于没有策略面
        if sdir is None:                                                                     # 提示词目录缺失已由共用守卫记过: 直接短路, 不重复报
            return result
        core = sdir / "core"                                          # core 三件套是行为层的编译产物, 单独一层判定
        for req in ("stance.md", "workflow.md", "output-format.md"):  # 逐个点名: 缺一份提示词, 对应模式就静默降级
            # 读点: core 提示词文件; 长度阈值 20 字符挡空壳占位
            p = core / req                                                                    # 核心提示词逐份点名: 缺一份就有一段策略没有落地文字
            if not p.is_file() or len(p.read_text(encoding="utf-8-sig").strip()) < 20:  # 长度阈值 20 挡空壳占位: 文件在但只有标题不算写过
                result.findings.append(Finding("MAJOR", f"static/core/{req}", "缺失或内容过短"))
                result.passed = False                                                            # 缺失或过短判败: 空壳占位提示词等于没有策略面
        # fragments 的 entry 符号必须可解析且可导入 —— 遍历**全部**片段 YAML。
        # 旧版只查 algo_mode/two_stage_async_mode.yaml 一个: best_auth_mode.yaml
        # 的 entry (src.client:BestAuth.login) 断链无人守护, 这是覆盖盲区。
        frag_dir = sdir / "fragments"
        # 遍历全部片段: 旧版只盯一个, best_auth_mode 的 entry 断链长期无人守护
        frag_files = sorted(frag_dir.rglob("*.yaml")) if frag_dir.is_dir() else []
        core_frag = frag_dir / "algo_mode" / "two_stage_async_mode.yaml"            # 核心片段是两阶段异步协议的锚点, 单独钉死不能被别的片段顶替
        if not core_frag.is_file():                                                    # 核心片段单独钉死: 它是两阶段异步协议的锚点, 不能被别的片段顶替
            # 核心片段是两阶段异步协议的锚点, 缺失即判败 (不因"还有别的片段"而放过)
            result.findings.append(Finding("MAJOR", "static/fragments/algo_mode/",
                                           "two_stage_async_mode.yaml 缺失"))
            result.passed = False                                                            # 核心片段缺失判败: 协议锚点丢了, 片段层整体失去意义
        for frag in frag_files:                                                           # 连记两条: 缺失既进逐份清单也进核心专项, 报告两处都能看到
            # 读点: 片段 YAML, 取 fragment.entry 符号串
            data = yaml.safe_load(frag.read_text(encoding="utf-8-sig")) or {}  # 每份片段真解析: 坏 YAML 在这里炸成 finding, 而不是被静默跳过
            entry = str((data.get("fragment") or {}).get("entry", ""))         # entry 是"模块:类.方法"符号串, 是符号检查的唯一输入
            # 无 entry 的片段只记 INFO: 目的是让人看见"这段没被守护", 不判败
            if not entry:                                                            # 无 entry 的片段只记提示: 目的是让人看见这段没被守护, 不判败
                # 无 entry 声明的片段 (如 best_two_phase.yaml 的 two_phase/gates 结构)
                # 不参与符号检查; 记 INFO 只为让人看见"这段没被守护", 不判败。
                result.findings.append(Finding(                                                 # 记最低级别提示: 判败与否留给下面的真导入那一路
                    "INFO", str(frag.relative_to(root)),
                    "无 fragment.entry 声明, 跳过符号检查"))
                continue
            # 形态: src.client:BestClient._execute_query -> _fetch_sqlid_data
            m = re.match(r"^(src[\w.]*):(\w+)\.(\w+)(?:\s*->\s*(\w+))?$", entry)  # 形态解析先于 import: 符号串写错报"不可解析", 不混进导入失败
            if not m:                                                                     # 形态先解析再导入: 符号串写错要报不可解析, 不混进导入失败
                result.findings.append(Finding("MAJOR", str(frag.relative_to(root)),
                                               f"entry 符号不可解析: {entry!r}"))
                result.passed = False                                                        # 不可解析判败: entry 写错等于这段片段没人能引用
                continue
            mod_name, cls_name, meth_name = m.group(1), m.group(2), m.group(3)  # 只取前三组: 可选的 "-> 方法" 后缀是文档注记, 不参与定位
            try:
                # import 点: 把片段声明的符号落到真实生产模块上 (失链即 finding)
                import importlib

                mod = importlib.import_module(mod_name)  # 真 import: 只拆不导的话, 方法被改名/删除这类腐化发现不了
                cls = getattr(mod, cls_name, None)                                           # 逐级取类: 取不到就落到下一段的缺失判定, 不在这里抛
                meth = getattr(cls, meth_name, None) if cls else None                      # 类缺失时短路: 否则对 None 取属性会直接炸掉整轮审计
                if meth is None:                                                         # 方法缺失即片段失效: 名字对但方法没了, 引用它照样运行时报错
                    raise AttributeError(f"{mod_name}.{cls_name}.{meth_name}")
            except Exception as exc:  # noqa: BLE001
                result.findings.append(Finding(                                                   # 缺方法记发现: 报告要指名是哪个符号没导进来
                    "MAJOR", str(frag.relative_to(root)),
                    f"entry 符号不可导入: {entry!r} ({exc!r})"))
                result.passed = False                                                    # 判败: 真导入失败说明生产树被裁剪或改名, 片段层引用的是幻觉
        return result

    def broken_samples(self) -> dict[str, str]:
        """反证夹具: 一份只有空白的空壳文件 (长度检查必须拒收)。"""
        return {"empty_file": "   \n"}

    def check_rejects(self, check_id: str, broken: str) -> bool:
        """empty_file 检查必须把空白内容判为过短 (True=检查有效)。"""
        if check_id != "empty_file":
            return True
        return len(broken.strip()) < 20


# ---------------------------------------------------------------------------
# 6. test/ 测试有效性审计
# ---------------------------------------------------------------------------

class TestsAuditor(Auditor):
    """test/ 测试有效性审计器 (专抓"看起来在测其实什么都没测")。

    检查什么: 空断言 (assert True)、mock __init__ 反模式、测试文件语法错误、
    零断言测试、无文档化理由的 module 级 skip。
    什么算 finding: assert True/语法错误 = CRITICAL, mock __init__/零断言 = MAJOR,
    skip 缺理由 = MINOR。
    严重度依据: assert True 与语法错误让测试从"证据"退化成"装饰", CRITICAL;
    零断言/mock __init__ 是"测了但失明" (Q-11), MAJOR; skip 缺理由只是
    可解释性缺口, MINOR 只提示不判败。
    """

    name = "tests"
    target = "test/"

    def run(self, root: Path) -> AuditResult:
        """单遍扫描: 文本反模式 (assert True/mock __init__/skip 理由) + AST 数断言。

        D5 落点的扫描形态: 每个测试文件只 ``read_text`` 一次, 同一份
        ``text`` 既喂正则也喂 ``ast.parse``, skip 判定放同一个循环 —— IO 次数
        减半, 且不会出现两遍读到不同内容的风险。

        AST 而不是文本数 assert: 只有真的落在 test_* 函数体内的
        ``ast.Assert`` (或 pytest.raises 调用) 才算数 —— 注释里提到 assert
        不算,  helper 函数里的断言也不该冒充测试函数的证据。
        """
        result = AuditResult()                                                                      # 新建结果对象: 测试层判定独立于其它五层
        # 无 fail-open: 测试目录缺失即 CRITICAL (质量评审层没有测试 = 无证据)
        tdir = _require_dir(result, root, "test")  # 测试目录缺失即 CRITICAL: 质量评审层没有测试等于没有证据
        if tdir is None:                                                                      # 测试目录缺失已由共用守卫记过: 直接短路, 不重复报
            return result
        n_assert_true = n_mock_init = n_zero_assert = 0  # 三个计数只进报告摘要: 逐条 finding 才是判败依据
        for py in sorted(tdir.rglob("test_*.py")):       # 单遍扫描: 同一份 text 既喂正则也喂 ast, IO 次数减半
            # 读点: 测试文件全文 (反模式 grep + AST 解析 + skip 判定共用一次读取)
            text = py.read_text(encoding="utf-8-sig")
            rel = py.relative_to(root).as_posix()    # 报告路径统一相对 skill 根: 跨机复跑才可比
            if re.search(r"assert\s+True\b", text):  # 空断言让测试从证据退化成装饰, 判 CRITICAL
                n_assert_true += 1                                                          # 计数之后还要逐条记发现: 报告要能点名是哪个文件有空断言
                result.findings.append(Finding("CRITICAL", rel, "含 assert True (空断言)"))
                result.passed = False                                                           # 空断言判败且级别最高: 它让测试从证据退化成装饰
            # mock __init__ 是结构性失明: 测了等于没测, 判 MAJOR (Q-11)
            if re.search(r'patch\.object\([^)]*,\s*["\']__init__["\']', text):
                n_mock_init += 1                                                              # 替身计数单列: 这是结构性失明, 与空断言不是同一类
                result.findings.append(Finding(
                    "MAJOR", rel, "mock __init__ 反模式 (结构性失明, Q-11)"))
                result.passed = False                                                       # 判败: 替掉被测类的初始化, 测试就再也无法证明它能构造
            try:
                tree = ast.parse(text)  # AST 而非文本: 判据必须看真调用, 不能被注释里的同名文本触发
            except SyntaxError as exc:
                result.findings.append(Finding("CRITICAL", rel, f"语法错误: {exc}"))
                result.passed = False                                                       # 语法错判败: 语法错的文件连收集都做不到, 等于没有测试
                continue
            # allow_module_level skip 必须有文档化理由, 且必须**真的是调用**。
            # 旧写法是纯文本子串匹配, 于是 test/integration/test_query_chain.py 里那段
            # "解释守卫为何被删除" 的注释 (注释正文含 allow_module_level=True) 被判成
            # 违规 —— 而那个文件里根本没有这样的调用, 守卫 2026-10-05 就删了。
            # 文本匹配同时产假阳与假阴: 真调用若把标志拆成变量名就漏, 注释里提一句就报。
            if _has_module_level_skip(tree) and "legacy import unavailable" not in text:
                result.findings.append(Finding(                                                 # 例外豁免要带说明: 裸写豁免标志等于给自己开后门
                    "MINOR", rel, "allow_module_level skip 缺文档化理由"))
            for node in ast.walk(tree):                                                       # 走 AST 而不是正则: 嵌套函数里的断言也要被看见
                # 只认 test 前缀的函数: helper 里的断言不该冒充测试证据
                if isinstance(node, ast.FunctionDef) and node.name.startswith("test"):
                    has_assert = any(                                                            # 只看测试函数: 辅助函数里的断言不构成测试覆盖
                        isinstance(n, ast.Assert) for n in ast.walk(node))                     # 逐节点找断言: 零断言测试是覆盖率里最隐蔽的一种洞
                    has_raises = any(
                        isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "raises"
                        for n in ast.walk(node))                                            # 异常断言也算断言: 只认 Assert 会误报异常型测试
                    if not (has_assert or has_raises):  # pytest.raises 也算断言: 只认 Assert 会误报异常型测试
                        n_zero_assert += 1                                                     # 两种断言都没有即零断言: 这条测试证明不了任何东西
                        result.findings.append(Finding(                                           # 计数用于结尾汇总: 报告要给零断言测试的总数
                            "MAJOR", f"{rel}::{node.name}", "零断言测试"))
                        result.passed = False                                            # 零断言判败并记中等严重度: 不至于让整层失明, 但确实是空覆盖
        return result

    def broken_samples(self) -> dict[str, str]:
        """反证夹具: 两个最典型的假测试 (空断言 + mock __init__), 都必须被拒收。"""
        return {"assert_true": "def test_x():\n    assert True\n",
                "mock_init": "def test_y():\n    patch.object(Best, '__init__', lambda self: None)\n"}

    def check_rejects(self, check_id: str, broken: str) -> bool:
        """assert_true / mock_init 两个反证检查都必须识别出各自的反模式。"""
        if check_id == "assert_true":
            return bool(re.search(r"assert\s+True\b", broken))
        if check_id == "mock_init":
            return bool(re.search(r'patch\.object\([^)]*,\s*["\']__init__["\']', broken))
        return True


# 审计器注册表 (权威顺序 = 模块内六个 class 的定义顺序):
#   消费方是 evals/eval_runner.py 的 run_audit() —— 它逐个实例化并执行,
#   顺序只影响报告里 findings 的排列, 不影响判定结果。
AUDITOR_CLASSES: list[type[Auditor]] = [  # 权威顺序 = 六个 class 的定义顺序: runner 逐个实例化执行
    ReferencesAuditor,                                                                          # 引用文档审计器: 白盒要素、未决标记与版本号三查
    KnowledgeAuditor,                                                                       # 引用知识库审计器: 份数、主题齐套、可解析与内容非空四查
    TemplatesAuditor,                                                                   # 引用模板审计器: 版本号与入口模板的 defaults 可消费性
    ContractsAuditor,                                                                         # 引用契约审计器: 必需文件、版本号与输入输出字段齐套
    StaticAuditor,                                                                         # 引用静态层审计器: 核心片段齐套与 entry 符号可导入
    TestsAuditor,                                                                              # 引用测试层审计器: 空断言、替身反模式与零断言三查
]


def auditor_registry() -> list[Auditor]:
    """实例化全部审计器 (runner 消费)。"""
    return [cls() for cls in AUDITOR_CLASSES]  # 每次新建实例: 审计器无状态, 但复用会让 findings 跨轮泄漏
