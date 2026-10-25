# -*- coding: utf-8 -*-
"""evals.ablation.metrics.assertions — critical 断言的匹配层 (表述层的表示归一)。

**为什么需要单独一层 (2026-10-10)**: ``gate_E`` 原先对 ``critical`` 断言做**裸子串
命中** (``c not in answer``)。这个判据的前提是"答案是渲染层按模板产出的原文" —— 它对
``ScriptedLLM`` 替身臂成立, 对 live 臂 (子代理自由行文) **不成立**。实测同一批采集表
(B3, 3 attempt × 30 题): 三次的 route 分布与工具调用数几乎逐字相同 (answer 230/230/229,
tool_calls 0.69/0.69/0.68), 而 E 门通过率是 **0.533 / 0.233 / 0.233** —— 差异不来自
决策, 全部来自**措辞**。平均答案长度 122.0 → 91.8 → 86.6 字符, 决策没变而正文变短。

失败短语经逐条归类, 分两类:

  * **表示类 (本模块负责归一)**: 同一个事实的不同写法。例: 答案写「共 3 个源」而断言要
    ``"3 行"``; 答案写「未截断」而断言要 ``"truncated=false"``; 答案写「不等于『非变星』」
    而断言要 ``"不等于非变星"`` (只是插入了引号); 答案写「只剩位置列」而断言要 ``"只有位置列"``。
  * **实质类 (本模块**不**负责, 必须继续判失败)**: 答案压根没说那个事实。例: 未给
    ``best://ps1/cone`` 稳定引用、未给 ``BEST_SIM_0001``、未提 18.20 / 17.55 / 12 次。
    归一化**不得**把这类洗成通过 —— 那是把判据变摆设。

因此本层只做三件**保事实**的机械归一 (仅表示, 不补事实):
  1. 字符层: NFKC (全角→半角) + 小写 + 去引号/强调符 + 空白折叠;
  2. 数值层: 数字尾零归一 (``18.20`` ≡ ``18.2``);
  3. 计数单位层: ``N 行 / N 个源 / N 条 / N 个`` → 同一概念 ``count:rows=N``;
     ``N 页`` → ``count:pages=N``; ``N 次`` → ``count:epochs=N``。**不同量纲不合并**
     (行 ≠ 页 ≠ 次), 否则会造出假通过。

语义型近义 (如 ``不支持`` ≡ ``做不了``) **不在这里猜** —— 那类由断言自己显式声明可接受
变体 (``{any_of: [...]}``), 逐条可复核, 不给模糊匹配留空间。

对外接口: :func:`match_critical` (返回归一/严格两套缺失清单) / :func:`canonicalize` /
:func:`concepts`。

依赖: 只用标准库。不 import 被测产品代码。
"""
from __future__ import annotations

# 标准库: 正则 / 字符归一
import re  # 概念抽取与归一都靠它
import unicodedata  # NFKC: 全角→半角的唯一来源

# 需要剥掉的引号与强调符 (中英各一套): 它们只影响排版, 不影响事实
_QUOTE_CHARS = "『』「」“”‘’\"'`*_【】〔〕《》"                  # 纯排版字符集: 归一时整批删掉

# 计数概念: (正则, 概念模板)。模板里的 {n} 用捕获组 1 填。
# **量纲严格分开**: rows / pages / epochs 三者不互认, 否则 "2 页" 会被 "2 行" 顶替。
_COUNT_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    # 行 / 源 / 条 都指"结果行数": 实测答案在这三种写法间自由切换
    (re.compile(r"(\d+)\s*(?:行|个源|条记录|条|个天体|个)"), "count:rows={n}"),   # 中文行数写法
    (re.compile(r"(\d+)\s*(?:records?|rows?)", re.IGNORECASE), "count:rows={n}"),   # 英文行数写法
    (re.compile(r"(\d+)\s*(?:页|pages?)", re.IGNORECASE), "count:pages={n}"),   # 页数: 与行数**不同量纲**
    (re.compile(r"(\d+)\s*(?:次|历元|epochs?)", re.IGNORECASE), "count:epochs={n}"),   # 观测次数: 同上不合并
)

# 截断布尔: 两种记法 (字面量 / 中文短语) 归一到同一概念
_TRUNC_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"truncated\s*[:=]\s*false|未截断|没有截断|未被截断|不截断|未触发截断",
                re.IGNORECASE), "flag:truncated=false"),   # 否: 字面量与中文短语等价
    (re.compile(r"truncated\s*[:=]\s*true|已截断|发生截断|触发了截断|被截断",
                re.IGNORECASE), "flag:truncated=true"),   # 是: 同上
)

# 数值字面量: 18.20 → 18.2 (尾零不承载信息); 整数保持整数形态
_NUM_RE = re.compile(r"(?<![\w.])(\d+\.\d+)(?![\w])")   # 前后界防止切进 id/版本号内部


def _strip_quotes(text: str) -> str:
    """去掉引号与强调符 (只影响排版, 不影响事实)。"""
    return "".join(ch for ch in text if ch not in _QUOTE_CHARS)   # 逐字符过滤: 比 replace 链更省事


def _norm_number(match: re.Match[str]) -> str:
    """数值尾零归一: ``18.20`` → ``18.2``; ``1.0`` → ``1``。"""
    value = float(match.group(1))                                 # 先取数值
    return str(int(value)) if value == int(value) else repr(value)   # 整数去掉小数点, 否则保留最短表示


def canonicalize(text: str) -> str:
    """字符层 + 数值层的归一 (不做概念替换, 保留可读性, 供子串命中用)。

    Args:
        text: 原始文本 (断言短语或答案正文)。

    Returns:
        归一后的文本: NFKC → 小写 → 去引号 → 数值尾零归一 → 空白折叠。
    """
    out = unicodedata.normalize("NFKC", str(text))     # 全角→半角: ３/＂/（） 都要能被断言命中
    out = out.lower()                                   # 大小写不承载事实: TRUNCATED 与 truncated 同义
    out = _strip_quotes(out)                            # 引号/强调符只影响排版
    out = _NUM_RE.sub(_norm_number, out)                # 数值尾零: 18.20 ≡ 18.2
    return re.sub(r"\s+", " ", out).strip()             # 空白折叠: 换行与多空格都归成一个空格


def concepts(text: str) -> set[str]:
    """抽出文本里的**概念集合** (计数 / 截断布尔), 供概念级命中。

    与 :func:`canonicalize` 是两条互补的路: 后者管"字面还得在", 前者管"换个写法也算说到了"。
    """
    canon = canonicalize(text)                          # 概念抽取在归一后的文本上做, 两边同口径
    found: set[str] = set()                             # 命中集合: 同一概念重复出现只记一次
    for pattern, template in _COUNT_PATTERNS:           # 逐条计数模式扫
        for m in pattern.finditer(canon):               # 一条文本可有多个计数
            found.add(template.format(n=int(m.group(1))))   # 捕获组即数字: 归一成 int 免掉 "03" 之类的写法差异
    for pattern, template in _TRUNC_PATTERNS:           # 截断布尔两条模式
        if pattern.search(canon):                       # 命中即记概念
            found.add(template)                         # 一条文本最多各记一次
    return found                                        # 概念集合交给 _hit 判包含


def _variants(entry) -> list[str]:
    """把一条断言展开成"可接受写法"清单。

    形态:
      * ``"3 行"`` → ``["3 行"]`` (旧形态, 完全向后兼容);
      * ``{"any_of": ["不支持", "做不了"]}`` → 逐条列出 (语义近义只能显式声明, 不许模糊猜);
      * ``{"text": "3 行"}`` → 与裸字符串等价 (便于将来加字段)。
    """
    if isinstance(entry, str):                          # 旧形态: 裸字符串
        return [entry]                                  # 单写法原样返回
    if isinstance(entry, dict):                         # 新形态: 映射
        if entry.get("any_of"):                         # 显式变体清单优先
            return [str(v) for v in entry["any_of"]]    # 逐条转字符串: YAML 可能给数字
        if entry.get("text"):                           # 单写法但仍写成映射
            return [str(entry["text"])]                 # 与裸字符串等价
    raise ValueError(f"critical 断言形态非法: {entry!r} (允许 str / {{any_of: [...]}} / {{text: ...}})")   # fail-closed: 非法形态当场抛


def _hit(answer_canon: str, answer_concepts: set[str], phrase: str) -> bool:
    """一条写法是否被答案说到了 (先概念级, 再降级到归一后的子串)。"""
    want_concepts = concepts(phrase)                       # 断言侧也过同一套概念抽取: 两边同口径才能对齐
    if want_concepts and want_concepts <= answer_concepts:  # 概念全中即算说到 (「3 个源」顶「3 行」)
        return True                                        # 概念级命中直接返回
    return canonicalize(phrase) in answer_canon             # 否则退回字面子串 (归一后): 保住"原文必须出现"那一半


def match_critical(answer: str, critical: list) -> dict:
    """按 critical 断言逐条判"说到了没有", 同时给出归一与严格两套读数。

    **两套读数都要进报告** (不能只报归一那套): 严格读数是被测方"逐字复述模板"的比率,
    归一读数是"事实说到了"的比率。两者之差就是**表述层脆性**的量化 —— 只报一套会把
    这个差藏起来, 而它正是 add-back 超限的成因之一。

    Args:
        answer: 答案正文。
        critical: 断言清单 (str 或 {any_of: [...]} / {text: ...})。

    Returns:
        ``{"missing": [...], "missing_strict": [...], "entries": [...]}``:
        ``missing`` 是归一后仍缺的 (驱动判定); ``missing_strict`` 是裸子串就缺的 (披露面);
        ``entries`` 记每条断言用了哪条写法命中, 便于复核。
    """
    answer_canon = canonicalize(answer)                    # 答案只归一一次: 循环里反复算会拖慢判定
    answer_concepts = concepts(answer)                     # 答案概念集同理只抽一次
    missing: list[str] = []                                # 归一口径缺失: 驱动判定
    missing_strict: list[str] = []                          # 严格口径缺失: 只披露
    entries: list[dict] = []                               # 逐条留痕: 复核时能看到命中的是哪条写法
    for entry in critical or []:                           # 逐条断言
        variants = _variants(entry)                        # 展开可接受写法
        hit_variant = next((v for v in variants if _hit(answer_canon, answer_concepts, v)), None)   # 取首条命中的写法
        # 严格侧: 只认第一条写法的裸子串 (与旧实现逐字等价, 保留可比性)
        strict_hit = canonicalize(variants[0]) in answer_canon    # 归一后的字面子串
        if hit_variant is None:                            # 归一后仍没说到 → 算真缺
            missing.append(str(entry) if isinstance(entry, str) else variants[0])   # 报可读的那条写法
        if not strict_hit:                                 # 严格侧独立记账
            missing_strict.append(str(entry) if isinstance(entry, str) else variants[0])   # 同上
        entries.append({"assertion": entry, "matched_variant": hit_variant,
                        "strict": strict_hit})             # 逐条留痕
    return {"missing": missing, "missing_strict": missing_strict, "entries": entries}   # 三件一起交给调用方
