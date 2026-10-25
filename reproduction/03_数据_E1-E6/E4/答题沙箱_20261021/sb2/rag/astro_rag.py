"""astro_rag.py — astro-best 专属本地知识混合检索执行器 (零重依赖)。

设计目标 (Master Plan §4 组件 4):
  - **本地优先**: 纯 Python 标准库 + PyYAML, 不依赖 _shared 共享层与网络;
  - **混合检索**: BM25 (k1=1.5, b=0.75) 稀疏通道 ⊕ CJK 字符词桶通道 ⊕
    领域术语加权 (DOMAIN_BOOST), RRF (reciprocal rank fusion, k=60) 融合;
  - **知识装载**: `rag/knowledge/*.yaml` 全量加载 (list 条目与 dict 配置两种
    布局归一化), 不改动/不删除任何既有知识文件 (只增不减硬锁);
  - **import 兼容**: skill 内既有检索入口 `src.rag` 包装层
    (薄包装 _shared.rag_engine) 保持原样, 本执行器用于 src 不可达时的
    独立降级路径与 CLI。

用法:
    python rag/astro_rag.py "如何区分 SN Ia 与 SN II?" --top-k 5
    >>> from astro_rag import AstroRAG
    >>> rag = AstroRAG(); rag.load(); rag.search("ZOGY PSF", top_k=3)
"""

from __future__ import annotations

# 标准库: CLI 参数解析 / JSON 输出 / BM25 的 log 运算 / 分词正则 /
# stderr 告警 / dataclass 条目载体 / 路径锚定与类型标注
import argparse
import json
import math
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    # 第三方: PyYAML 是解析知识库 YAML 的唯一依赖 (硬依赖, 缺失即显式失败)
    import yaml
except ImportError as _exc:  # pragma: no cover — PyYAML 为硬依赖, 缺失即显式失败
    # PyYAML 是硬依赖: 知识库全部以 YAML 存放, 缺失时必须在 import 期
    # 显式失败 (给出安装提示), 而不是等第一次 load() 才以难懂的
    # NameError 炸出来 — 早失败比晚失败可复核
    raise SystemExit("astro_rag 需要 PyYAML: pip install pyyaml") from _exc

# skill 根锚点: 本文件位于 rag/ 下, 上跳一级即仓库根; 所有路径校验
# (知识目录/单文件) 都以它为边界, 防符号链接逃逸
SKILL_ROOT = Path(__file__).resolve().parent.parent  # 上跳一级即仓根; 所有路径校验都以它为边界, 防符号链接逃逸

# 默认知识目录: rag/knowledge/*.yaml 全量加载 (只读不改, 只增不减硬锁)
DEFAULT_KNOWLEDGE_DIR = SKILL_ROOT / "rag" / "knowledge"  # 全量加载 *.yaml; 本执行器只读不改

# ── 检索超参 (G7: 超参必须显式可复核) ─────────────────────────────────────
# 以下三个标量 + 一张加权表是本执行器的全部可调超参; 集中声明、逐项注释,
# 复核者据此在 references/ALGORITHM-SPEC.md 对账, 不接受藏在函数体里的
# 魔法数字。BM25_K1: 词频饱和系数 — 控制 tf 增长多快趋于平缓 (1.5 为
# 信息检索文献常用值); 只影响 BM25 通道打分, 不影响词桶通道与 RRF 融合
BM25_K1 = 1.5  # 显式超参, 复核者据此对账; 不接受藏在函数体里的魔法数
# BM25_B: 文档长度归一化强度 — 0 = 不按长度惩罚, 1 = 完全归一;
# 0.75 让长条目不完全占优, 又保留一定长度信号
BM25_B = 0.75  # 只作用于 BM25 通道, 不影响词桶通道与融合
# RRF_K: reciprocal rank fusion 的平滑常数 — 排名第 r 的通道贡献
# 1/(K+r); K 越大, 头部与尾部排名差越小 (融合更"民主"); 60 为 RRF
# 原论文常用值。只影响两路分数的融合, 不影响任何单路分数
RRF_K = 60  # 只影响两路分数的融合, 不影响任何单路分数
# 领域术语加权表: 知识文件词干 -> 加权分。键为**无扩展名**的知识文件词干,
# 与 load() 写入 entry.source 的值严格同口径; 消费方是 _bm25 — entry.source
# 精确命中本表某个键时给该条目加分 (加性叠加, 不改写稀疏通分量径)。权威来源
# 是 rag/knowledge/ 下的真实文件名 — 改表即改检索偏好, 故显式列出每一项而非
# 动态推断; 新增知识文件时必须在此登记词干, 否则该文件不参与领域加权。
#
# 历史缺陷 (budget doc §6.1 C1, 已修): 旧键表写的是领域术语 (``tap``/
# ``adql``/``sqlid``/``两阶段``/...), 而 load() 传给 entry.source 的是带
# ``.yaml`` 扩展名的文件名, 两侧口径脱节 — ``entry.source in DOMAIN_BOOST``
# 对全部 5 个知识文件恒为 False, 领域加权通道是永不触发死代码。现在键表与
# source 同为词干形态, 加权真实生效 (守门测试 test_rag_domain_boost.py)。
# 权重按知识类型分级: 最佳实践 > 领域规则 > 经验/已知问题 > 引用出处。
DOMAIN_BOOST = {  # 键为无扩展名词干, 与 load() 写 entry.source 的值严格同口径
    "best_practices": 0.25, "domain_rules": 0.2,
    "lessons_learned": 0.15, "known_issues": 0.15, "citations": 0.1,
}

# 分词正则: 英文/数字/下划线/连字符词条 或 单个 CJK 汉字。
# 中文无空格分词, 单字桶是低成本兜底 (查询与文档两侧同口径, 见 _tokenize)
_TOKEN_RE = re.compile(r"[a-zA-Z0-9_\-]+|[\u4e00-\u9fff]", re.UNICODE)  # 英文整词 + 中文单字; 查询侧与文档侧必须同一套口径


def _tokenize(text: str) -> list[str]:
    """英文下划线词条 ⊕ CJK 单字桶 (词桶通道退化兼容中文查询)。

    查询侧与文档侧必须走同一分词: 两侧口径不一致时, "匹配"实际发生在
    两套不同 token 上, 召回率静默劣化且无法归因。英文按词切分保留
    ``sncosmo``/``gaia_dr3`` 这类整词; 中文退化为单字桶是显式的兜底
    (无分词器依赖, 代价是精度, 换来零重依赖的本地优先)。

    Args:
        text: 待分词文本 (查询串或条目全文)

    Returns:
        token 列表 (已 lower, 无空串)
    """
    lowered = text.lower()                                                     # 小写化: 匹配按大小写无关口径, 否则 "Gaia" 与 "gaia" 会分成两路
    return [tok for tok in _TOKEN_RE.findall(lowered) if tok]


@dataclass
class RagEntry:
    """一条知识条目 (content 必非空)。

    content 是参与检索与展示的正文; tags 只进检索文本不进展示;
    source 记知识文件词干 (无扩展名, DOMAIN_BOOST 的加权键, 与 load() 传入
    口径一致); category 记同一词干, 供结果按知识文件分组展示。
    """

    content: str                                                                                    # 条目的类型注解
    tags: list[str] = field(default_factory=list)                                       # 标签用 default_factory: 可变默认值不能用 []
    source: str = ""
    category: str = ""

    def text(self) -> str:
        """检索用拼接文本: content + tags, 统一 lower。

        tags 参与检索但不进结果 content 字段 — 调用方读到的是干净正文,
        标签命中的收益体现在排序上。lower 与 _tokenize 的 lower 一致,
        保证英文词大小写不敏感。
        """
        return " ".join([self.content, *self.tags]).lower()


def _entries_from_doc(data: Any, source: str, category: str) -> list[RagEntry]:
    """归一化布局: list[{title, description, ...}] 或 dict 配置。

    知识库存在两种 YAML 布局 (历史演进产物, 只增不减硬锁不允许改写既有
    文件): list 条目式 (每条一个 dict) 与 dict 配置式 (顶层映射)。本函数
    把两者都归一为 RagEntry 列表, 检索层只见一种结构。

    Args:
        data: ``yaml.safe_load`` 的产物 (list/dict/其他)
        source: 知识文件词干 (无扩展名), 写入 entry.source 供领域加权
        category: 文件词干, 写入 entry.category 供分组展示

    Returns:
        RagEntry 列表; 空文档/全无效条目时返回空列表 (不抛)
    """
    out: list[RagEntry] = []  # 归一化出口: 两种 YAML 布局都收敛成同一种 RagEntry
    if isinstance(data, list):  # 顶层是列表 = 条目数组布局
        for item in data:                                                                           # 逐条走文档
            # 非 dict 条目 (YAML 里混入裸字符串/数字) 跳过而非抛错:
            # 一个坏条目不应让整个知识文件不可检索
            if not isinstance(item, dict):                                                          # 非字典项跳过: 列表里混入标量不该崩
                continue
            # title 必取 (可为空串), 正文键按优先级收集; 键名集合是知识
            # 库的事实布局, 新增布局形态时应在此扩展而非在检索层特判。
            #
            # 键表扩容 (知识沉底体系 B 路前置修复): 原表只含
            # description/solution/summary/content/rule 五个键, 而本库实际
            # 使用的正文键远不止这些 — lessons 用 ``lesson``、issues 用
            # ``symptom``+``workaround``、citations 用 ``short``/``relevance``。
            # 顶层字典展开成逐条条目后, 若正文键表不同步扩容, 展开出的条目
            # 只剩 title 一行, 正文全部丢失 — 拆得越碎丢得越多。
            lines = [str(item.get("title", "")).strip()]
            for key in ("description", "solution", "summary", "content", "rule",
                        "lesson", "symptom", "workaround", "relevance", "short",
                        "bibtex", "body"):
                if item.get(key):                                                                   # 有值才取
                    lines.append(str(item[key]).strip())                                     # 转字符串再 strip: YAML 里可能是数字或布尔
            content = "\n".join([ln for ln in lines if ln]).strip()  # 空段剔掉再 join, 免得正文以多个空行开头
            # title 与正文键全空的条目没有检索价值, 丢弃 (content 必非空
            # 是 RagEntry 的不变式)
            if not content:                                                                         # 空内容不进: 知识条目必须有正文
                continue
            raw_tags = item.get("tags") or []
            # tags 兼容两种写法: YAML 里写作逗号分隔字符串或真 list;
            # 统一成 list[str] 并去空白, 空标签由下方 text() 天然吸收
            tags = (                                                                                # 标签归一
                [t.strip() for t in str(raw_tags).split(",")] if isinstance(raw_tags, str)
                else [str(t).strip() for t in raw_tags]                                             # 非列表时按标量处理
            )
            out.append(RagEntry(content=content, tags=tags, source=source, category=category))      # 收成一条
    elif isinstance(data, dict):
        for key, value in data.items():  # 顶层是映射 = 键名即条目标题
            # 下划线开头是 YAML 元数据键 (注释/模板变量), 不是知识内容
            if key.startswith("_"):
                continue
            # 列表式布局 (知识沉底体系 B 路前置修复): 顶层值是 list 时
            # **逐项展开成独立条目**, 而不是把整坨 YAML 当一条。
            #
            # 修复前的缺陷 (实测确认): 本库 5 个文件全是 ``{lessons: [...]}``
            # 这类"字典套列表"结构, 旧代码把每个顶层键的整块 value dump 成
            # 一条 → 68 条真知识被压成 6 块整文件索引, 检索粒度退化成
            # "整个文件", top3 分数 0.0328/0.0323/0.0317 几乎无区分度。
            # 递归调用自身复用 list 分支的字段归一化, 保证两种布局同一口径。
            if isinstance(value, list):                                                             # 列表就递归
                out.extend(_entries_from_doc(value, source, category))                              # 递归展开
                continue
            # 配置式布局: 键即主题, 值整块序列化回 YAML 文本进检索 —
            # 保留嵌套结构信息, 避免把 dict 拍平成无意义字符串
            # 标量值转成 YAML 片段, 保证检索面与原文可逐字对读
            content = f"{key}\n{yaml.safe_dump({key: value}, allow_unicode=True, sort_keys=False).strip()}"
            out.append(RagEntry(content=content, tags=[key], source=source, category=category))     # 标量条目: 用键名当标签
    return out


@dataclass
class _Scored:
    """(条目, 分数) 中间对 — 单路通道的排序单元。

    仅内部使用: 两路通道各自产出 ``{idx: score}``, 融合在 search() 里
    按排名 (而非裸分) 进行, 故不跨通道比较 _Scored。
    """

    entry: RagEntry                                                                                 # 单条打分的结果
    score: float                                                                                    # 分数


class AstroRAG:
    """本地混合检索执行器: BM25 + CJK 词桶 + RRF。

    零重依赖 (标准库 + PyYAML), 不触网: 知识全量在 load() 时读入内存,
    search() 只在本地结构上打分 — 检索行为因此确定、可离线复核。
    """

    def __init__(self, knowledge_dir: str | Path = DEFAULT_KNOWLEDGE_DIR) -> None:
        """构造执行器 (不装载; 必须显式调 load())。

        Args:
            knowledge_dir: 知识目录; 缺省 rag/knowledge。传入值会在 load()
                时过路径安全校验 (不得越出 skill 根), 此处只原样持有
        """
        self.knowledge_dir = Path(knowledge_dir)                                                    # 知识目录锚点
        # entries 装载后只读; _df/_avg_len 是 BM25 的倒排统计, _build_index
        # 一次性重建 — 搜索途中不改结构, 保证同一次装载内结果可复现
        self.entries: list[RagEntry] = []  # entries 的下标就是 RRF 字典的键, 装载后不再重排
        self._df: dict[str, int] = {}  # 文档频率, 不是词频
        self._avg_len: float = 1.0                                                                  # 平均长度初值 1.0: 避免除零

    # ── 路径安全 (Mimosa 语义: 变量路径统一过 is_relative_to 校验) ────────
    def _safe_resolve(self, path: Path) -> Path | None:
        """解析路径并校验其未越出 skill 根; 越界返回 None (调用方决定处置)。

        防的是两类逃逸: 调用方传入 ``../..`` 型知识目录, 或知识目录内存
        在指向 skill 外的符号链接。resolve() 先把 ``..`` 与 symlink 落成
        真实绝对路径, is_relative_to 再判归属 — 只查字符串前缀会被
        ``/root-x`` 型兄弟目录骗过。

        Args:
            path: 待校验路径 (知识目录或其内文件)

        Returns:
            校验通过的真实路径; 越界或解析失败 (OSError) 返回 None
        """
        try:
            resolved = path.resolve()  # 先把 .. 与 symlink 落成真实绝对路径, 再判归属
            root = SKILL_ROOT.resolve()  # 两侧都 resolve: 不解析根就无法同口径比
            return resolved if resolved.is_relative_to(root) else None
        except OSError:
            # 解析失败 (如权限/断链) 按不安全处理: 宁可漏读一个文件,
            # 不可把越界路径当合法读进来
            return None

    def load(self, knowledge_dir: str | Path | None = None) -> int:
        """装载知识目录并建立倒排统计, 返回条目数。

        失败语义: 目录越界抛 ValueError, 目录不存在抛 FileNotFoundError —
        两者都是调用方配置错误, 显式炸掉而非静默返回 0 条 (0 条会被误读
        成"知识库为空"而不是"路径给错了")。单个 YAML 文件损坏只告警跳过,
        不让一个坏文件拖垮整个知识库。

        Args:
            knowledge_dir: 覆盖构造时的知识目录; None 用实例默认值

        Returns:
            装载条目总数 (含两种布局归一化后的全部条目)
        """
        directory = Path(knowledge_dir) if knowledge_dir is not None else self.knowledge_dir  # None 回落实例默认
        safe = self._safe_resolve(directory)                                                        # 先做路径安全解析
        if safe is None:                                                                            # 解析失败即拒绝
            raise ValueError(f"知识目录越出 skill 根, 已拒绝: {directory}")
        if not safe.is_dir():                                                                       # 解析后还要确认是目录
            raise FileNotFoundError(f"知识目录不存在: {safe}")
        self.entries = []  # 重装即替换: 不清空会让倒排统计按双倍条目漂移
        for path in sorted(safe.glob("**/*.y*ml")):  # 排序装载, 条目索引跨平台可复现; 两种扩展名一次覆盖
            # 逐个文件再过一次路径校验: glob 展开的是已校验目录的子路径,
            # 但 symlink 可能指向 skill 外, 逐个 resolve 才堵得住
            inner = self._safe_resolve(path)  # 逐个再校验一次: symlink 可能指向 skill 外
            if inner is None:                                                                       # 内层文档名
                continue
            try:
                # IO 点: 读知识 YAML (UTF-8)。safe_load 禁自定义标签 —
                # 知识库是数据不是代码, 不允许 !!python/object 之类的
                # 任意构造 (防知识文件被塞进可执行载荷)
                data = yaml.safe_load(inner.read_text(encoding="utf-8"))
            except yaml.YAMLError as exc:
                # 单个文件语法坏: 告警跳过。知识库"只增不减"意味着文件
                # 质量参差, 检索可用性优先于完整性
                print(f"[astro_rag][WARN] 无效 YAML {inner.name}: {exc}", file=sys.stderr)
                continue
            # source 取词干 (无扩展名): DOMAIN_BOOST 的键就是词干形态,
            # 传带 .yaml 的文件名会让领域加权恒不命中 (budget doc §6.1 C1)
            self.entries.extend(_entries_from_doc(data, inner.stem, inner.stem))                    # 递归装载: 目录结构即分类结构
        self._build_index()  # 索引只在 entries 定稿后建一次
        return len(self.entries)

    def _build_index(self) -> None:
        """重建 BM25 倒排统计 (文档频率 df 与平均文档长度)。

        在 entries 最终装载完成后调用一次; df 按"条目内去重 token 集合"
        计数 (文档频率, 非词频), 平均长度用于 BM25 的长度归一分母。
        """
        self._df = {}                                                                               # 倒排表从零建
        total = 0                                                                                   # 文档总数从零累加
        for entry in self.entries:                                                                  # 逐条
            # set() 去重: df 统计"多少条文档含该词", 一条文档里出现十次
            # 也只计一次, 与 BM25 的 idf 定义对齐
            tokens = set(_tokenize(entry.text()))  # set() 去重, 保证 df 记的是文档频率
            for tok in tokens:                                                                      # 逐 token
                self._df[tok] = self._df.get(tok, 0) + 1                                            # 累加文档频次
            # 平均长度用未去重的词数 (文档真实长度), 与 BM25 的 dl 同口径
            total += len(_tokenize(entry.text()))  # 平均文档长度用未去重的 token 数, 归一分母才对得上
        # 空库兜底 1.0: 避免除零; 空库下所有查询都得 0 分, 值不影响结果
        self._avg_len = (total / len(self.entries)) if self.entries else 1.0  # 空库回落 1.0, 免得 BM25 分母除零

    # ── 通道 1: BM25 稀疏检索 ─────────────────────────────────────────────
    def _bm25(self, query_tokens: list[str]) -> dict[int, float]:
        """BM25 稀疏通道: 对每条知识条目按词频/逆文档频率/长度打分。

        只返回得分 > 0 的条目 (稀疏): 未命中任何查询词的条目不进榜,
        融合时由 RRF 按名次处理, 零分条目不占位。

        超参 (G7): k1=BM25_K1, b=BM25_B 均为模块级显式常量, 复核者在
        本函数内看不到任何魔法数字。

        Args:
            query_tokens: 查询侧 token 列表 (可重复, tf 自然计入)

        Returns:
            ``{条目下标: BM25 分}``; 全不命中时返回空 dict
        """
        n = max(len(self.entries), 1)  # n 下限 1: IDF 公式的分母不能为 0
        scores: dict[int, float] = {}  # 键是条目下标而非词, 便于 RRF 直接合并两路
        for idx, entry in enumerate(self.entries):                                                  # 逐条算 BM25
            doc_tokens = _tokenize(entry.text())                                                    # 该条的 token 集
            # dl 至少记 1: 空文本条目不进除零 (归一化分母的保护)
            dl = len(doc_tokens) or 1                                                         # 文档长度兜底为 1: 空文档会让 BM25 分母为零
            tf: dict[str, int] = {}                                                                 # 词频表从零建
            for tok in doc_tokens:                                                                  # 逐 token
                tf[tok] = tf.get(tok, 0) + 1                                                        # 累加词频
            score = 0.0                                                                             # 得分从零起
            for tok in query_tokens:                                                                # 逐查询词
                df = self._df.get(tok, 0)                                                           # 取文档频次
                # df=0 的词全库未出现, idf 无定义, 跳过 (不猜不罚)
                if df == 0:  # df=0 = 该词不在任何条目里, 不可能命中, 直接跳过
                    continue
                # 经典 BM25 idf: log(1 + (N-df+0.5)/(df+0.5)), 恒正,
                # 稀词权重高于常词
                idf = math.log(1.0 + (n - df + 0.5) / (df + 0.5))  # 平滑 IDF: +1 偏移保证恒正, 常见词只是压低不归零
                term = tf.get(tok, 0)                                                               # 取词频
                # 长度归一化分母: b 控制长文档受惩罚程度, _avg_len 为库均值
                denom = term + BM25_K1 * (1.0 - BM25_B + BM25_B * dl / self._avg_len)  # 长度归一分母; _avg_len 有下界 1.0 兜底
                # tf 饱和: term*(k1+1)/denom, 词频越高增益越缓 (k1 封顶)
                score += idf * (term * (BM25_K1 + 1.0)) / denom  # tf 饱和项用 (K1+1) 封顶, 高频词不会线性拉爆分数
            if entry.source in DOMAIN_BOOST:                                                     # 领域加权: 命中有明确领域的条目更可能是要找的
                # 领域加权: entry.source (知识文件词干) 精确命中模块顶部加权表
                # 的键时加分; 加在总分上而非乘性系数, 保证稀疏通道的量纲不被
                # 改写。该文件全部条目共享同一词干, 故加权按知识文件整体生效
                score += DOMAIN_BOOST[entry.source]                                                 # 加权直接加到总分
            if score > 0:  # 零分不进榜: 让 RRF 只在有实质证据的条目间排序
                scores[idx] = score                                                                 # 回填到分数表
        return scores

    # ── 通道 2: 领域术语词桶 (命中即计分, 召回兜底) ─────────────────────────
    def _bucket(self, query_tokens: list[str]) -> dict[int, float]:
        """词桶通道: 查询与条目的 token 重合度 (归一化到 0..1)。

        存在理由是兜底: BM25 对"查询词很常见但条目确实相关"的形态不友好
        (idf 压低), 词桶通道不看稀有度只看重合, 保证这类条目仍能进榜,
        再由 RRF 融合定终序。中文查询走单字桶, 本通道是其主要召回来源。

        Args:
            query_tokens: 查询侧 token 列表

        Returns:
            ``{条目下标: 重合比例}``; 无重合返回空 dict
        """
        hits: dict[int, float] = {}                                                                # 词桶命中: 集合交集, 与 BM25 互补
        qset = set(query_tokens)  # 查询侧也转集合, 交集才是一次 O(1) 的重合判定
        for idx, entry in enumerate(self.entries):                                                  # 逐条
            toks = set(_tokenize(entry.text()))                                                     # 取该条 token 集
            overlap = qset & toks                                                                   # 交集非空即命中
            if overlap:                                                                             # 有交集才算候选
                # 分母是查询词数 (非文档词数): "查询被满足的比例",
                # 长文档不会因为词多而被稀释
                hits[idx] = len(overlap) / (len(qset) or 1)  # 分母是查询词数, 长文档不会因词多而被稀释
        return hits

    # ── 融合: RRF ──────────────────────────────────────────────────────────
    def search(self, query: str, top_k: int = 5) -> list[dict[str, Any]]:
        """混合检索入口: BM25 ⊕ 词桶两路独立排序, RRF 按名次融合。

        RRF (reciprocal rank fusion) 只用排名不用裸分: 两路分数量纲不同
        (BM25 无上界, 词桶 ≤1), 直接加和会让量纲大的一路独裁; 取
        1/(K+r) 后两路对终序的贡献只取决于各自排名, 融合因此可复核。

        Args:
            query: 自然语言查询 (中英混排均可; 空串/纯空白直接返回空)
            top_k: 返回条数; 负值按 0 处理 (``max(top_k, 0)``)

        Returns:
            命中列表, 每项含 content/source/category/score (RRF 分,
            六位小数); 按分数降序
        """
        # 空查询守卫: 空白查询会命中全部条目的词桶通道 (overlap 恒空则
        # 不会, 但防御性显式返回, 避免下游把"空结果"当"无知识")
        if not query.strip():                                                                      # 空查询直接拒: 空串会让所有条目都"命中"
            return []
        q_tokens = _tokenize(query)  # 查询与文档共用 _tokenize, 口径不一致会让召回静默劣化
        chan_a = self._bm25(q_tokens)  # 通道 A: 稀有度敏感, 负责精确命中
        chan_b = self._bucket(q_tokens)  # 通道 B: 只看重合, 负责兜底召回
        rrf: dict[int, float] = {}  # 融合累加器; 两路量纲不同, 只有排名能直接相加
        # 每路内部先按本路分数降序得到排名 r, 再累加 1/(K+r+1);
        # 同一条目两路都命中则双份贡献 (这正是"两路共识"的奖励)
        for rank, idx in enumerate(sorted(chan_a, key=chan_a.get, reverse=True)):                   # A 路(BM25)按分数降序排名
            rrf[idx] = rrf.get(idx, 0.0) + 1.0 / (RRF_K + rank + 1)                             # RRF 累加: 倒数排名融合, 不用绝对分数可比
        for rank, idx in enumerate(sorted(chan_b, key=chan_b.get, reverse=True)):                   # B 路(词桶)按分数降序排名
            rrf[idx] = rrf.get(idx, 0.0) + 1.0 / (RRF_K + rank + 1)                                 # 同样用 RRF 累加
        ranked = sorted(rrf.items(), key=lambda kv: kv[1], reverse=True)[: max(top_k, 0)]  # 负 top_k 按 0 处理, 切片不会从尾部取
        return [
            {                                                                                       # 两路结果并成一张表
                "content": self.entries[idx].content,
                "source": self.entries[idx].source,
                "category": self.entries[idx].category,
                "score": round(score, 6),  # 六位小数: 融合分的有效位就这么几位, 多给是噪声
            }
            for idx, score in ranked                                                                # 回填最终分数
        ]


def main(argv: list[str] | None = None) -> int:
    """CLI 入口: 一条查询 -> 装载知识库 -> 混合检索 -> 打印结果。

    两种输出形态: ``--json`` 给程序消费 (含 loaded 条目数, 便于核对
    "查的是哪个库"); 默认人读格式带序号/分数/来源, content 截断到
    240 字符预览 — 全文由调用方自行读取知识文件, CLI 不复制知识内容。

    Args:
        argv: 参数列表 (None 时取 sys.argv); 传入便于测试替身

    Returns:
        进程退出码 (恒 0; 检索无结果不是错误, 是正常输出空列表)
    """
    parser = argparse.ArgumentParser(description="astro-best 本地知识混合检索 (BM25+词桶+RRF — BEST 数据源主理)")  # 本执行器的定位: 双通道混合
    parser.add_argument("query", help="自然语言查询")
    parser.add_argument("--top-k", type=int, default=5, help="返回条数 (默认 5)")
    parser.add_argument("--knowledge-dir", default=None, help="知识目录 (默认 rag/knowledge)")
    parser.add_argument("--json", action="store_true", help="JSON 输出")  # JSON 模式给下游程序读, 缺省是人读的分段文本
    args = parser.parse_args(argv)                                                                  # 命令行实参
    rag = AstroRAG(args.knowledge_dir or DEFAULT_KNOWLEDGE_DIR)  # 构造即绑知识目录, 检索前必先 load() 建索引
    # 装载与检索分离: load() 的失败 (路径越界/不存在) 在此显式抛出,
    # CLI 以非零退出结束, 不与"检索无结果"混淆
    loaded = rag.load()                                                                             # 先装载
    results = rag.search(args.query, top_k=args.top_k)                                              # 再检索
    if args.json:                                                                                   # --json 出口
        # ensure_ascii=False: 中文知识原文按 UTF-8 原样输出, 不转义
        print(json.dumps({"loaded": loaded, "results": results}, ensure_ascii=False, indent=2))  # loaded 一并输出
    else:
        print(f"[astro_rag] 条目 {loaded} 条; 查询: {args.query}")
        for i, hit in enumerate(results, 1):                                                        # 逐条打印命中
            print(f"\n#{i} score={hit['score']:.4f} source={hit['source']}")
            # 240 字符预览截断: 终端可读性优先; 完整内容去 source 指名的
            # 知识文件取, 不在 CLI 里整条倾倒
            print(hit["content"][:240])  # 正文截断到 240 字符, 终端可读优先于全文倾泻
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
