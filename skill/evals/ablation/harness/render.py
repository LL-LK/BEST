# -*- coding: utf-8 -*-
"""evals.ablation.harness.render — ScriptedLLM 的答案文本渲染 (按组件开关拼段)。

职责: 把一次运行的结构化结果 (行集/截断三元组/来源句柄) 渲染成回答文本。
**段落的存在与否由系统装配的组件开关决定** — 这正是消融效应在 scripted 模式的
体现方式 (可解释、可复现):

  - ``data_path``      关 → 没有取数句 (B0/B1 结构性不可完成);
  - ``field_semantics``关 → 只有裸列名清单, 没有波段→列映射与全限定列名 (A2);
  - ``provenance``     关 → 没有来源句与注入防线句 (A4: 站点注入失去 untrusted 标记);
  - ``post_verify``    关 → 没有哨兵剔除/截断三元组对账句 (A5);
  - ``refusal_rules``  关 → 拒绝/澄清句被路由降级取代 (A3, 降级在 adapters.plan)。

**表述门 (E) 的断言载体**: items.yaml 的 ``assertions.critical`` 短语全部从这些
句子里取 — 因此"关键断言全中"等价于"该有的段落都在", 机器可判且无歧义。

所属实验: E5 基线与消融 (30 任务 × 10 系统 + sham, ScriptedLLM 离线跑;
成功率 = ScriptedLLM 跑通率而非模型能力), 方案真值 docs/eval-E5-baseline-ablation.md
§3.1 (装配表) / §6.1 (E 门定义) / §7 (反证夹具 V-2/V-3/V-6 的坏答案形态)。本模块
是消融效应的**唯一表达面**: 开关一关, 对应短语就从答案里消失, 表述门随即判缺。

对外接口: render(item, outcome, components, system) -> 答案文本; data_sentence /
scope_sentence / provenance_sentence / postcheck_sentence / reject_sentence /
clarify_sentence / science_sentence / injection_sentence / no_data_sentence
(各段落, 供 render 拼装); first_call / catalog_of / cell / key_value_phrases
(查询语义小工具)。

依赖与数据流: 输入 = items.yaml 的单条 item + adapters 产出的 RunOutcome + 系统装配
的组件开关; 产物 = 答案文本字符串, 由 composite.gate_E 拿去做禁答/关键断言/数值
溯源判定, 本身不落盘。  # 渲染层只负责排版, 判定一律不在此做

关键契约与不变量: 离线回放 —— 答案完全由回放数据与开关拼出, rate_limit 归零,
不接真实模型、不打真实站点; 零跨实验 import —— 本模块不 import evals/ 下其它实验
的代码, 只按路径读数据文件 (哨兵字典 / E3 fixtures / E2 gold); 星表前缀从
metrics.composite 单点取, 不在本文件另抄一份 (见 table_prefixes 的 docstring);
确定性 —— 同样的 (item, outcome, components) 必须渲染出逐字节相同的文本。

陷阱与边界: 为什么 sham 在这里换文本而不是换开关 —— 安慰剂要控制"长度不变、
信息量被置换", 所以段落照常出现、只把内容换成等长无关天文通识; 反过来, 若让
sham 关掉 field_semantics, 它就和 A2 完全同构, 掉分幅度无从归因。另一个坑:  # 渲染层只排版不改判定: 判定在 composite
injection_sentence 随 provenance 一起被 A4 拆掉, 于是 S 类安全题在 A4 上会因
缺 critical 断言而判 FAIL — 这是 A4 的真实效应, 不是渲染 bug, 不要靠"给 A4 补回
一句"来让用例变绿。**零跨实验 import**: 本模块不 import evals/ 下其它实验的代码。

白盒锚点: docs/eval-E5-baseline-ablation.md §3.1 (装配表) / §6.1 (E 门定义) /
§7 (反证夹具 V-2/V-3/V-6 的坏答案形态)。  # 列宽按最长单元格算: 固定宽度会让长站名折行
"""
from __future__ import annotations  # 渲染层只排版不改判定: 判定在 composite

# 标准库: 类型标注 (RunOutcome 只作形态提示, 用 Any 避免与 adapters 成环)
from typing import Any

# 本地: E5 metrics 层的星表前缀单一出处 (本文件不得另持一份硬编码前缀表 ——
# 两份副本各改各的, 粒度必然漂移; 登记口径见 table_prefixes 的 docstring)
from evals.ablation.metrics.composite import table_prefixes

# 表前缀集合 (A2 退化时剥离; 与 src.protocol 的星表名前缀同源)
_TABLE_PREFIXES = table_prefixes()  # NA 与 0 严格区分: 不适用 ≠ 得了零分


def render(item: dict, outcome: Any, components: dict, system: dict | None = None) -> str:  # 渲染入口只做排版: 判定在 composite, 这里改文案不能改变结论
    """按路由与组件开关拼装答案 (段落缺失即该组件的消融效应)。

    Args:
        item: items.yaml 的单条任务 (断言短语与 gold 关键字段的来源)。
        outcome: adapters 产出的 RunOutcome (行集/报告态/路由)。
        components: 系统装配的组件开关 (决定哪些段落存在)。
        system: 系统装配全量; 只有 sham 安慰剂会读它的 sham_detail。

    Returns:  # NA 与 0 严格区分: 该指标不适用 ≠ 得了零分
        拼好的答案文本 (句间用中文句号连接, 末尾补一个句号)。
    """  # 小数位固定 4: 跑批之间的报告要能直接 diff
    parts: list[str] = []                                                                 # 段落按拼装顺序攒: 顺序即答案语序, 消融效应体现在缺哪一段
    # 路由优先于组件: 拒答/澄清轮本来就不该带数据段落, 先分流再谈开关
    if outcome.route == "reject":  # reject 路线先出拒绝句: 拒绝是结论, 澄清/科学说明都排在它后面
        parts.append(reject_sentence(item, components))  # 列宽按内容算: 固定宽度会让长站名折行
    elif outcome.route == "clarify":
        parts.append(clarify_sentence(item))  # 列宽按内容算: 固定宽度会让长站名折行
    elif item.get("category") == "safety":
        # S 类走科学陈述 + 注入防线: 这里没有取数段落, 因为答案是通识与安全口径
        parts.append(science_sentence(item))                                                        # S 类答案主体是科学陈述, 不带取数段落
        if components.get("provenance"):  # 只有真的判到溯源缺失才提它: 无条件提会变成套话
            # 防线句挂 provenance: A4 拆掉来源标注就同时失去"行数据不可信"的声明
            parts.append(injection_sentence())                                                 # 防线句随来源段一起被拆: 这正是 A4 的效应所在
    else:
        # D/C 类的正常取数分支: 下面四段各自独立受一个开关控制
        if components.get("data_path"):  # 数据路径缺失也要点名: 否则用户不知道该去查哪张表
            parts.append(data_sentence(item, outcome))  # 排序按分数降序: 报告要先看最差的系统
        if components.get("field_semantics"):
            parts.append(scope_sentence(item, outcome, components))  # 报告抬头: 跑批口径摘要, 缺失项显式写 N/A
        elif (system or {}).get("sham_detail"):
            # sham 安慰剂: 不注入 BEST 专属字段语义, 注入**等长无关天文通识** —
            # 段落仍在 (长度受控), 但信息量被置换成无关内容 (§4 可靠性检验 1)
            parts.append(str(system["sham_detail"].get("replacement_block")))  # 指标表抬头: 列数随系统数变, 故现算而非写死
        if components.get("provenance"):
            parts.append(provenance_sentence(item, outcome))  # 各系统的通过率逐行给出: 报告要先看最差的系统
        if components.get("post_verify"):
            parts.append(postcheck_sentence(item, outcome))                                    # 后验证段独立受开关控制, 关掉它就是 A5 的消融
        if not parts:  # 一句话都拼不出来是合法结局, 单独给"无数据"句而不是留空
            # 兜底: 无数据通路的系统 (B0/B1) 必须显式说"没有数据通路",
            # 留空答案会被表述门判成"什么都没说", 那测不出结构性不可完成
            parts.append(no_data_sentence(item))                                              # 无数据通路要显式说出来, 留空会被判成"什么都没说"
    # 过滤空串再连接: 某个开关关掉后段落是空, 不滤会留下悬空的句号
    return "。".join(p for p in parts if p) + "。"  # 反证段: 判定器自证, 与成绩表分开


# ── 查询语义的小工具 ────────────────────────────────────────────────────────

def first_call(item: dict) -> dict:
    """首个非 optional 期望调用 (取 catalog/坐标/列等查询语义)。"""  # 按分数升序: 报告要先看最差的系统
    # 优先取非 optional 的那一步: optional 多是排序/翻页这类锦上添花的调用,
    # 拿它当"本题问的是什么"会把口径带偏
    for step in item.get("expect_tools") or []:
        if not step.get("optional"):  # 只取第一个非可选工具: 可选项不构成"必须先调"的判据
            return step
    # 全是 optional 时退回第一步, 宁可口径不完美也不让调用方炸掉
    return (item.get("expect_tools") or [{}])[0]


def catalog_of(item: dict) -> str:  # 按分数升序: 报告要先看最差的系统
    """本题目标星表 (从期望调用参数取; 缺省 ps1)。"""
    # 缺省 ps1: E5 的 D 类题几乎都落在 ps1, 兜底值只是防御性默认值
    return str((first_call(item).get("args") or {}).get("catalog") or "ps1")


def bare_column_args(args: dict) -> dict:  # 成本段: 跑批口径里的实测请求数, 不做估算
    """A2 退化: 列名去表前缀 (只留裸列名清单 — 波段→列映射被拆掉)。"""
    out: dict = {}                                                                         # A2 退化时另起一份参数: 不改原字典, 免得污染同题复用
    for key, value in args.items():                                                            # 逐参数判形态: 字符串与列表两种列名参数要分别处理
        # 字符串形态的 columns/sort: 可能是逗号分隔的多列, 整串剥前缀即可
        if key in ("columns", "sort") and isinstance(value, str):  # columns/sort 走裸列名: 带星表前缀的形态由执行层再补回去
            out[key] = _bare(value)                                                                 # 逗号分隔的多列整串剥前缀即可, 不必拆词
        # 列表形态: 逐项剥, 漏掉这一支会让 A2 在列表列上"看起来没退化"
        elif key == "columns" and isinstance(value, list):
            out[key] = [_bare(v) for v in value]                                           # 列表形态逐项剥: 漏掉这支, A2 在列表列上就看不出退化
        else:
            # 其余参数原样透传: 坐标/半径不属于字段语义, 动了就变成另一个消融
            out[key] = value                                                                      # 坐标与半径原样透传: 动它们就变成另一个消融
    return out


def _bare(name: str) -> str:
    """去掉星表前缀 (``ps1_rpsf`` → ``rpsf``; 无前缀原样返回)。"""
    # 顺序匹配前缀集 (已按长度降序): gaia_ 与 gaia_dr3_18_ 共存时必须长前缀先命中,
    # 否则规范列名会被剥成 dr3_18_rpsf 这种半截名
    for prefix in _TABLE_PREFIXES:                                                             # 前缀集已按长度降序, 长前缀先命中才不会剥成半截名
        if name.startswith(prefix):                                                               # 只剥首个命中的前缀: 再剥一次会把列名剥没了
            return name[len(prefix):]
    return name


def _num(value: Any) -> str:
    """数值的紧凑渲染 (300.0 → "300"; 整数形态便于断言短语命中)。"""
    try:  # 反证表尾: 元分低于 1.00 即判 E5 FAIL
        number = float(value)                                                                     # 先转数值再判整数形态: 转不了就原样字符串化
    except (TypeError, ValueError):
        # 不可转数值就原样字符串化: 断言短语里写的是原文形态, 转了反而对不上
        return str(value)
    # 整数值去掉小数尾巴: items.yaml 的 critical 短语写的是 "3 行" 而不是 "3.0 行"
    return str(int(number)) if number.is_integer() else str(number)


def _column_name(item: dict, column: str, components: dict) -> str:
    """断言短语里的列名 (A2 拆掉字段语义后用裸列名)。"""
    # item 形参是签名对齐 (列名解析只依赖 components, 不读题面), 函数体不消费
    return column if components.get("field_semantics") else _bare(column)


# ── 各段落 ──────────────────────────────────────────────────────────────────

def data_sentence(item: dict, outcome: Any) -> str:
    """取数句: 行数 + 服务端总数 + 实返 + 截断标记 + 检索口径 (E 门断言载体)。"""
    rep = outcome.reported                                                                    # 报告态是取数句的唯一事实源: 行数与三元组都从这里取
    state = rep.get("state", "rows")                                                   # 缺省按有行处理: 正常路径下 reported 一定带 state
    if state == "error":                                                                          # 错误态先分流: 它与空结果、截断三种说法互斥
        # 错误态必须显式点名入参问题: 降级成空结果或静默改参都算 M5 四态错判
        radius = (first_call(item).get("args") or {}).get("radius_arcsec")                   # 错误多半出在半径: 取出来只为把原因说清, 不为猜原因
        tail = (f"半径 {_num(radius)} 角秒非法" if radius is not None else "入参非法")                   # 有半径就点名半径, 没有就只说入参非法, 不编原因
        return (f"查询显式失败: {rep.get('error_code')} ({tail} → 显式拒绝; "                     # 显式拒绝要同时声明"没降级、没改参", 这是 M5 判据要的证据
                f"未降级为空结果, 也未静默改参)")
    if state == "empty":
        # 0 行是合法结果: 必须与"位置不存在天体"区分开说, 否则语义上是错的
        return (f"在 {catalog_of(item)} 表检索到 0 行 — 库内无记录是合法结果 "
                f"(success=true, total_count=0, truncated=false), "
                f"不等于该位置不存在天体")
    args = first_call(item).get("args") or {}                                                  # 期望调用参数是口径的事实源: 中心与半径都从这里取
    scope = ""                                                                                      # 默认无口径句: 后面只有锥形检索才会填
    # 只有锥形检索才有口径可言: 其它形态没有中心与半径, 硬凑会写出假参数
    if args.get("ra") is not None:                                                              # 有中心才谈得上口径: 非锥形调用硬凑会写出假参数
        scope = (f"; 检索口径: 中心 ({_num(args.get('ra'))}, {_num(args.get('dec'))}), "           # 口径句写全中心与半径: 这是"查了哪块天区"的唯一证据
                 f"半径 {_num(args.get('radius_arcsec'))} 角秒")
    # 关键字段短语来自 gold 的 first_* 键: 与 gold 对齐才能做字段一致率判定
    keys = ", ".join(key_value_phrases(item, outcome)) or "见上行"                   # 关键字段短语取自 gold 的首行字段, 与 gold 对齐才能算字段一致率
    # 截断三元组写全: truncated 与 total/returned 必须同时出现才能被对账判据读到
    return (f"在 {catalog_of(item)} 表检索到 {rep.get('returned_count', 0)} 行 "                       # 截断三元组写全: 少写一项, 对账判据就读不到
            f"(服务端总数 {rep.get('total_count', 0)}, 本次返回 "
            f"{rep.get('returned_count', 0)}, "
            f"truncated={str(rep.get('truncated', False)).lower()}){scope}; "
            f"关键字段: {keys}")


def key_value_phrases(item: dict, outcome: Any) -> list[str]:
    """把 gold 的 first_* 关键字段值渲染成 "列=值" 短语 (E 门断言载体)。"""
    gold = (item.get("gold_result") or {}).get("key_values") or {}                    # 期望字段来自 gold: 短语要对得上断言, 只能以 gold 为准
    rows = outcome.reported.get("rows") or []                                                     # 观测行来自本次回放: 有行才有"列=值"可比
    phrases: list[str] = []                                                                # 逐字段攒短语, 顺序沿 gold 的键序, 报告可逐行对照
    for name, expected in gold.items():                                                      # 逐个 gold 字段判: 缺一个就会在表述门少一条断言
        # 只取 first_ 前缀的键: 非 first_ 键是本地过滤约束, 由 _filter_phrases 负责,
        # 混进来会让"列=值"短语里出现过滤区间, 断言短语对不上
        if not name.startswith("first_") or not rows:                                          # 只取首行前缀且必须有观测行, 两者缺一都给不出短语
            continue
        column = name[len("first_"):]                                                               # 去掉前缀就是断言短语里的列名写法
        actual = cell(rows[0], column)                                                     # 只看首行: gold 的首行字段语义就是"第一行的这个列"
        if expected is None:
            # gold 期望缺失: 答案里必须出现"缺失"字样, 填 0 或填哨兵都判错
            phrases.append(f"{column}=缺失(空值/哨兵)")                                           # 期望缺失时必须出现"缺失"字样: 填 0 或填哨兵都判错
        elif actual is None:
            # gold 有值但观测取不到: 如实报缺失, 报不出就是掩盖了取数缺陷
            phrases.append(f"{column}=缺失")                                                  # 期望有值却取不到: 如实报缺失, 报不出就是掩盖取数缺陷
        else:
            phrases.append(f"{column}={actual}")                                                # 正常形态直接写"列=值", 断言短语按这形态匹配
    return phrases


def cell(row: dict, column: str) -> Any:
    """行内取列 (全限定名 / 裸名 / 波段字典三种形态依次尝试)。"""
    # 先直取: 站点回包多数就是全限定列名
    for key in (column, _bare(column)):                                                         # 全限定名与裸名依次试: 站点回包两种形态都出现过
        if key in row and row[key] not in (None, ""):                                         # 空值不算取到: 当成有值会让短语写成"列=None"
            return row[key]
    # 再翻波段字典: 光变类结果把测光值塞在嵌套 dict 里, 平铺取列会全落空
    for bucket in ("magnitudes", "magnitude_errors"):                                            # 再翻波段字典: 光变类结果把测光塞在嵌套字典里
        values = row.get(bucket) or {}
        if _bare(column) in values:                                                                 # 字典键也是裸列名, 所以这里同样要剥前缀
            return values[_bare(column)]
    return None


def scope_sentence(item: dict, outcome: Any, components: dict) -> str:
    """字段语义句: 全限定列名 + 波段→列映射 + 本地过滤/批量入口口径 (A2 拆掉即消失)。"""
    step = first_call(item)                                                                         # 取首个非可选调用: 它才代表本题的问法
    args = step.get("args") or {}
    bits: list[str] = []                                                                     # 字段语义句由若干片段拼成, 缺一项就在表述门少一条断言
    columns = args.get("columns") or []                                                       # 关键列原样列出: 全限定名正是 A2 被拆掉的那部分
    sort = args.get("sort")
    if columns:                                                                                   # 题目点了列才写列清单, 没点则走下面的兜底句
        bits.append("关键列: " + ", ".join(str(c) for c in columns))                                # 列名清单不剥前缀: 退化与否在这一句上直接可见
    if sort:                                                                                        # 有排序键才排序: 报告列序由调用方决定
        # 排序列要说成"经波段→列映射核实", 这句正是 A2 拆掉后消失的字段语义证据
        bits.append(f"排序列 {sort} (r 波段的权威列, 经波段→列映射核实)")
    if not bits:                                                                          # 兜底分支: 没点名也要说清列名是核实来的, 否则这段等于没写
        # 兜底: 题目没点名列时也要说清列名是核实来的, 否则这段等于没写
        bits.append(f"列名与波段映射经 describe_catalog 核实 "
                    f"(全限定形, 如 {catalog_of(item)}_rpsf)")
    if _has_local_filter(item):                                                                 # 本地过滤才需要交代: 没有区间约束时提了就是废话
        # 明说"服务端不过滤、已在本地过滤": 工具面没有服务端过滤参数,
        # 不交代就会被当成"少过滤了"
        bits.append("服务端不过滤, 已在本地过滤: " + ", ".join(_filter_phrases(item)))
    if str(step.get("tool")) == "crossmatch_batch":
        # 批量入口的判别式: 坐标内联一次提交, 不建 job, 答案里要能看出这一点
        n_inputs = len(args.get("coords") or [])
        unmatched = ((item.get("gold_result") or {}).get("key_values") or {}).get(
            "unmatched_inputs")
        tail = f", {unmatched} 个输入无匹配" if unmatched is not None else ""
        bits.append(f"批量入口 crossmatch_batch (coords 内联一次提交, 无需上传建 job); "
                    f"共 {n_inputs} 个输入坐标{tail}")
    return "; ".join(bits)


def _has_local_filter(item: dict) -> bool:
    """本题是否需要本地过滤 (gold 声明了区间约束 — 工具面无服务端过滤参数)。"""
    keys = (item.get("gold_result") or {}).get("key_values") or {}
    # 判据是键名后缀: gold 用 xxx_between 记区间约束, 这是数据侧的既有写法
    return any(str(k).endswith("between") for k in keys)


def _filter_phrases(item: dict) -> list[str]:
    """把 gold 的非 first_* 键值渲染成 "约束=值" 短语 (本地过滤的依据)。"""
    keys = (item.get("gold_result") or {}).get("key_values") or {}
    return [f"{k}={v}" for k, v in keys.items() if not str(k).startswith("first_")]


def provenance_sentence(item: dict, outcome: Any) -> str:
    """来源句: stable_uri + 数据快照 + 内容信任标注 (A4 拆掉后整段消失)。"""
    rep = outcome.reported                                                                       # 来源句同样只认报告态里的事实字段, 不另找出处
    # 缺句柄时给显式占位而不是省略: "来源: (未记录)" 本身就是可判的缺陷信号
    uri = rep.get("stable_uri") or "best://(未记录)"
    snap = rep.get("snapshot_id") or "(未声明)"
    return (f"来源: {uri}; 数据快照 {snap}; "
            f"站点行数据一律 content_trust=untrusted (S-2 提示注入面)")


def postcheck_sentence(item: dict, outcome: Any) -> str:
    """后验证句: 哨兵剔除 + 缺列显式 null + 截断三元组对账 + 分页数 (A5 拆掉即消失)。"""
    rep = outcome.reported                                                                # 后验证句的四态互斥全靠 reported 判定, 不另设状态
    bits: list[str] = []                                                                       # 逐项攒后验证证据: 哨兵、缺列、四态、分页各占一条
    if rep.get("sentinels_removed"):
        # 哨兵阈值 -999 是 evals/_data 的字典口径, 答案里要连同豁免列一起交代
        bits.append("已按哨兵字典把缺失/空测光值剔除 (阈值 -999, 含 -1004 形态)")
    missing = (item.get("gold_result") or {}).get("missing_columns") or []
    if missing:                                                                          # 缺列必须显式记 null: 填 0 或从别的列推导都是阻断形态
        # 缺列必须显式记 null: 填 0 或从别的列推导都是 §11 阻断的形态
        bits.append(f"缺列 {', '.join(str(c) for c in missing)} 已显式记为缺失 (null), "
                    f"未填 0、未从其他列推导")
    # 四态互斥: error / truncated / empty / 正常 只能说一条, 多说就等于自相矛盾
    if rep.get("state") == "error":
        bits.append("显式拒绝路径已核对: 未降级为空结果、未擅自改参")
    elif rep.get("truncated"):
        bits.append(f"结果被截断: 服务端总数 {rep.get('total_count')} > 本次返回 "
                    f"{rep.get('returned_count')}, 不得当作全量")
    elif rep.get("state") == "empty":
        bits.append("0 行是合法结果 (success=true, total_count=0, truncated=false)")
    else:
        bits.append(f"截断三元组一致 (truncated=false, total={rep.get('total_count')}, "
                    f"returned={rep.get('returned_count')})")
    if rep.get("pages"):
        # 分页数写进答案: 翻页重试属于 M3 判据面, 答案层看不到就无从对账
        bits.append(f"分页 {rep['pages']} 页无重无漏")
    if rep.get("extra_page_empty"):
        bits.append("续取下一页得空页 (末页已满, 空页是正常终止信号, 不是错误)")
    return "; ".join(bits)


def clarify_sentence(item: dict) -> str:
    """澄清句: 缺哪个维度 + 候选口径 (C 类 E 门断言载体)。"""
    clarify = item.get("clarify") or {}
    # 缺什么与可选口径都取自题面: 澄清轮的可比性靠写死的第二回合文本 (E5 §9)
    missing = "、".join(str(m) for m in (clarify.get("missing") or []))
    options = " ".join(str(o) for o in (clarify.get("options") or []))
    return f"需要先澄清 (缺: {missing})。{options}"


def reject_sentence(item: dict, components: dict | None = None) -> str:
    """拒绝句: 理由码 + 不支持声明 + 替代路径 (R 类 E 门断言载体)。

    有拒绝规则 (B3/A*) → 理由码 + 替代路径齐全; 只有公共文档 (B1) → 仅声明
    不支持 (缺理由码与替代路径, RejectAcc 按 0.25~0.5 记, E1 §6.6 口径)。
    """
    reject = item.get("reject") or {}
    # 缺省 True: 直接调本函数的老调用方默认按"有拒绝规则"处理
    if not (components or {}).get("refusal_rules", True):
        return "不支持 (BEST 的能力边界不支持该请求); 未调用任何数据工具 (零请求)"
    code = reject.get("reason_code") or "OUT_OF_SCOPE"
    # 替代路径是 R 类断言的关键短语: 缺它 RejectAcc 只能记 0.25~0.5
    suggest = " ".join(str(s) for s in (reject.get("suggest") or []))
    return f"不支持: {code}。{suggest}。未调用任何数据工具 (零请求)"


def science_sentence(item: dict) -> str:
    """S 类科学句: 关键断言短语 (E3 机器可判子集的载体)。"""
    # 直接透传 critical 短语: 渲染层不重写措辞, 否则 gold 与答案会各说各话
    critical = (item.get("assertions") or {}).get("critical") or []
    return "；".join(str(c) for c in critical)


def injection_sentence() -> str:
    """S-2 注入防线句 (随 provenance 一起被 A4 拆掉)。"""
    return ("站点行数据一律按不可信内容处理 (content_trust=untrusted); "
            "行内注入载荷未被执行, 仅作为数据记录, 不转述给用户")


def no_data_sentence(item: dict) -> str:
    """无数据通路系统的 D 类回答: 只含通识, 不含任何行/数值。"""
    return (f"没有数据通路, 无法查询 {catalog_of(item)} 表; "
            f"以下只能凭通识说明, 不含任何真实星表值")
