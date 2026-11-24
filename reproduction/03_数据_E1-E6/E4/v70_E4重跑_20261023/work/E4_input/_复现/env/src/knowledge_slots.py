"""src.knowledge_slots — 知识沉底体系 A 路：不依赖 RAG 的确定性槽位取用。

能力边界: 只做"按固定挂钩取知识"这一件事, 不做模糊检索 (模糊检索是 B 路
``rag/astro_rag.py`` 的职责)。本模块不触网、不加载模型、无第三方依赖。

设计类比 (给非算法读者):
    工具箱。每样知识挂在一个**固定挂钩**上, 挂钩名字是 ``维度/值``, 例如
    ``catalog/ps1``。要 ps1 的知识就直接去 ``catalog/ps1`` 这个挂钩拿, 不用
    翻箱倒柜地搜索。好处是快且可预测 (同样的输入永远同样的输出), 代价是
    "没挂上钩的知识"取不到 — 那部分交给 B 路召回。

槽位物理布局 (复用既有 ``static/fragments/`` 目录, 不新建体系):
    static/fragments/<维度>/<值>.{yaml,md}

    维度       目录                    取值来源            盘上现状
    algo_mode  static/fragments/algo_mode/    文件名 stem       3 份
    data_source static/fragments/data_source/  文件名 stem       2 份
    target_type static/fragments/target_type/  文件名 stem       3 份
    catalog    static/fragments/catalog/      文件名 stem       **目录不存在**
    error_kind static/fragments/error_kind/    文件名 stem       **目录不存在**

catalog / error_kind 留在白名单里是因为**登记的是"有哪些挂钩"这个契约**, 而不是
"盘上现在有什么": 仓内并没有把候选升格成 fragment 的环节 (``ops/knowledge_capture.py``
只写 ``.knowledge/inbox/``, 人工审的那一端是 ``rag/knowledge/`` 而不是槽位目录),
所以这两个维度不会自愈。为了不让"声明了却取不到"变成常态, 沉底管道已改为
**只给当前真能命中的槽位建议** (``ops/knowledge_capture.py::_slot_hint_actionable``):
谁把 ``static/fragments/catalog/ps1.yaml`` 建出来, 建议当天就自动回来, 不必改代码。

用法:
    >>> from src.knowledge_slots import resolve_slots
    >>> slots = resolve_slots({"algo_mode": "two_phase", "target_type": "ttype"})
    >>> [s.key for s in slots]
    ['algo_mode/best_two_phase', 'target_type/best_ttype']

键里带的是**解析后的文件 stem** (短名经 ``SLOT_ALIASES`` 落到实际文件名), 因此
``list_slots()`` 列出的台账键与这里返回的键是同一套命名, 两者可直接互相回查。
"""
from __future__ import annotations

# 标准库: dataclass 做返回值载体 / pathlib 跨平台路径与越界校验 / 类型标注
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional

# 本地: skill 根解析的唯一实现 (R4-03: 收敛掉本件原有的第三份副本)
from src._paths import skill_root

# ── 路径锚点 ──────────────────────────────────────────────────────────
# 本文件位于 src/ 下, 上跳一级即 skill 根; 用标志文件探测而非写死层数,
# 防止目录层级调整后锚点漂移 (Q-39)。解析实现收敛在 src/_paths.py (R4-03):
# 本处原有第三份副本, 兜底写死 parents[1] —— 与另两份的 parents[2] 不同,
# 正说明"逐调用点写死层数"会随文件深度漂移, 故改为按目录名定位。


SKILL_ROOT = skill_root(__file__)                   # 全模块唯一的根锚点, 越界校验都拿它当基准
FRAGMENTS_DIR = SKILL_ROOT / "static" / "fragments"  # 槽位物理根, 复用既有片段目录不另立体系

# 允许的槽位维度 (白盒清单): 新增维度必须在此登记, 否则 resolve_slots 忽略。
# 登记在这里而不是动态扫目录, 是为了让"有哪些挂钩"成为可复核的事实,
# 而不是随目录内容漂移的隐式契约。
SLOT_DIMENSIONS: tuple[str, ...] = (  # 元组顺序即 resolve_slots 的遍历序, 改序会改结果顺序
    "algo_mode",
    "data_source",
    "target_type",
    "catalog",
    "error_kind",
)

# 槽位文件后缀优先级: yaml 先于 md (结构化优先, 便于程序消费)
_SUFFIXES: tuple[str, ...] = (".yaml", ".yml", ".md", ".txt")  # 同名多后缀并存时取先命中者

# 取值别名: 调用方习惯说的短名 → 实际文件名 stem。
# 存在的理由 (实测踩到): 目录里真实文件叫 ``best_two_phase.yaml``, 而调用方
# 自然会说 ``two_phase`` — 没有别名表时这类调用全部静默落空, A 路会变成
# "看起来能用、实际永远不命中"的摆设。别名是显式清单而非前缀模糊匹配,
# 以保证确定性 (一个值只可能映射到一个文件)。
SLOT_ALIASES: dict[tuple[str, str], str] = {  # 显式清单而非前缀模糊匹配, 保证一个值只映射一个文件
    ("algo_mode", "two_phase"): "best_two_phase",
    ("algo_mode", "auth"): "best_auth_mode",
    ("algo_mode", "async"): "two_stage_async_mode",
    ("data_source", "catalogs"): "best_catalogs",
    ("data_source", "endpoints"): "nadc_endpoints",
    ("target_type", "ttype"): "best_ttype",
}

# 单个槽位文本上限 (字符): 防日志/异常原文把上下文撑爆。
# 超出部分截断并加显式标记 — 静默截断会让使用者误以为看到了全貌。
MAX_SLOT_CHARS = 4000  # 截断事实随 Slot.truncated 外带, 不靠文本猜


@dataclass(frozen=True)  # 不可变: 槽位可安全缓存与按值比较
class Slot:
    """一个被命中的知识槽位 (不可变, 便于缓存与相等比较)。

    Attributes:
        key: 槽位键 ``维度/值`` (如 ``catalog/ps1``)
        path: 槽位文件绝对路径 (便于溯源与审计)
        text: 槽位正文 (已按 MAX_SLOT_CHARS 截断)
        truncated: 是否发生过截断
    """

    key: str                                                                                    # 槽位键: 维度与值拼成, 调用方无需回查目录结构
    path: str                                                                                    # 文件绝对路径: 便于溯源与审计, 不给相对形态
    text: str                                                                                      # 正文: 已按上限截断, 截断事实另带布尔位
    truncated: bool                                                                              # 截断标志: 必须外带, 否则摘要会被当全文消费

    def as_dict(self) -> dict[str, Any]:
        """转为可 JSON 序列化的字典 (供日志/契约消费)。

        Returns:
            四字段浅字典 (key/path/text/truncated), 键名与本 dataclass
            字段同名。``truncated`` 必须外带: 文本被裁过时下游要能
            区分"原文如此短"与"被截断", 否则会把摘要当全文消费。
        """
        return {
            "key": self.key,
            "path": self.path,
            "text": self.text,
            "truncated": self.truncated,
        }


def _safe_resolve(path: Path) -> Optional[Path]:
    """解析路径并校验未越出 skill 根; 越界返回 None。

    防两类逃逸: 调用方传入 ``../..`` 型路径, 或目录内存在指向 skill 外的
    符号链接。resolve() 先把 ``..`` 与 symlink 落成真实绝对路径,
    is_relative_to 再判归属 — 只比对字符串前缀会被 ``/root-x`` 型兄弟目录骗过。
    """
    try:
        resolved = path.resolve()  # 先把 ``..`` 与 symlink 落成真实绝对路径
    except OSError:  # 路径不可解析 (权限/不存在) 时按未命中处理, 不抛
        return None
    # 归属判定放最后: 越界返回 None — 只比字符串前缀会被 ``/root-x`` 型兄弟目录骗过
    return resolved if resolved.is_relative_to(SKILL_ROOT.resolve()) else None


def _normalize_value(value: Any) -> Optional[str]:
    """把槽位取值归一为安全的文件名片段; 不安全/空值返回 None。

    只接受 ``[A-Za-z0-9_-]``, 其余字符 (含路径分隔符与 ``..``) 一律拒绝 —
    这是纵深防御的第二道: 即便调用方拼出了恶意 key, 也到不了文件系统层。
    """
    text = str(value or "").strip().lower()  # 小写 + 去空白: 槽位键大小写不敏感
    if not text:                                                                                    # 空值即拒: 槽位键不接受空串
        return None
    allowed = set("abcdefghijklmnopqrstuvwxyz0123456789_-")
    return text if all(ch in allowed for ch in text) else None  # 白名单外(含 ``..``)一律拒


def _read_slot(dimension: str, value: str) -> Optional[Slot]:
    """按 (维度, 值) 读取一个槽位; 不存在或越界返回 None。

    确定性契约: **不猜、不模糊匹配**。``ps1`` 就只找 ``ps1.yaml``,
    绝不会退而求其次返回 ``ps1_old`` 或"最像的那个"。
    """
    dim_dir = _safe_resolve(FRAGMENTS_DIR / dimension)                                           # 维度目录先过越界校验: 外部串不当目录名直接用
    if dim_dir is None or not dim_dir.is_dir():                                                    # 目录不存在即未命中: 视为无槽位, 不报错
        return None
    for suffix in _SUFFIXES:                                                                    # 按后缀优先级逐个试: 同名多后缀并存时取先命中者
        candidate = _safe_resolve(dim_dir / f"{value}{suffix}")                               # 候选路径再过一次越界校验: 目录内也可能藏有越界链接
        if candidate is None or not candidate.is_file():                                        # 非文件或已越界都跳过: 符号链接与目录都不算槽位
            continue
        try:
            # 读取: UTF-8 解码, 读失败 (权限/二进制) 按未命中处理
            raw = candidate.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None
        truncated = len(raw) > MAX_SLOT_CHARS                                                    # 按字符数判截断: 截断的是文本, 不是落盘字节
        text = raw[:MAX_SLOT_CHARS] + ("\n...[已截断]" if truncated else "")  # 截断留痕, 防止被当全文
        return Slot(
            key=f"{dimension}/{value}",  # 键即"维度/值", 调用方无需回查目录结构
            path=str(candidate),                                                                  # 路径记绝对形态: 越界校验与溯源都以此为基准
            text=text,                                                                            # 正文带显式截断标记: 静默截断会被当全文消费
            truncated=truncated,                                                                    # 截断标志随对象走: 下游不必从文本反推
        )
    return None


def resolve_slots(context: dict[str, Any]) -> list[Slot]:
    """按上下文字典批量解析槽位 (A 路唯一取用入口)。

    Args:
        context: 形如 ``{"catalog": "ps1", "algo_mode": "two_phase"}`` 的字典。
            键必须是 SLOT_DIMENSIONS 成员, 否则忽略; 值会被归一化校验。

    Returns:
        命中槽位列表 (按维度声明顺序, 未命中维度不出现在结果里)。
        永远不抛异常: 坏输入 = 该维度不命中, 不影响其他维度。
    """
    slots: list[Slot] = []                                                                          # 结果容器: 只收命中的槽位
    for dimension in SLOT_DIMENSIONS:  # 按白名单顺序遍历, 结果顺序因此可预期
        raw_value = context.get(dimension)                                                          # 取值可缺: 缺该维度既不算命中也不算失败
        if raw_value is None:                                                                       # 没给就跳过: 坏输入不拖垮其它维度
            continue  # 该维度没给: 跳过, 既不算命中也不算失败
        value = _normalize_value(raw_value)                                                        # 先归一再查文件: 大小写与空白在这一步收口
        if value is None:                                                                        # 不安全即跳过: 含路径分隔符的值到不了文件系统
            continue  # 值不安全 (空/含路径分隔符): 静默忽略, 坏输入不拖垮整批
        # 别名解析: 短名优先落到实际文件 stem; 无别名时按原值查 (同名文件)
        slot = _read_slot(dimension, SLOT_ALIASES.get((dimension, value), value))              # 别名先查表: 短名落实际文件主干, 无别名按原值查
        if slot is not None:                                                                        # 命中才收集: 未命中维度不出现在结果里
            slots.append(slot)
    return slots


def list_slots(dimension: Optional[str] = None) -> list[str]:
    """列出已有槽位键 (运维/体检用)。

    Args:
        dimension: 限定维度; 为 None 时列出全部维度。

    Returns:
        ``维度/值`` 键列表 (排序稳定, 便于 diff 与审计)。
    """
    dims: Iterable[str] = (dimension,) if dimension else SLOT_DIMENSIONS  # None 时覆盖全部维度
    keys: list[str] = []                                                                            # 键容器: 体检输出用, 排序在返回前做
    for dim in dims:                                                                              # 逐维度遍历: 限定维度时只有一个, 否则全量
        if dim not in SLOT_DIMENSIONS:                                                             # 非白名单维度跳过: 外部串不当目录名直接用
            continue  # 只认白名单维度: 外部串不当目录名直接用
        dim_dir = _safe_resolve(FRAGMENTS_DIR / dim)                                                # 目录先过越界校验: 与读取路径同一纪律
        if dim_dir is None or not dim_dir.is_dir():                                                 # 目录缺失即跳过: 视为无槽位, 不报错
            continue  # 维度目录不存在: 视为无槽位, 不报错
        for path in dim_dir.iterdir():                                                              # 遍历目录项: 仅收录已知后缀的文件
            # 只收已知后缀, 忽略 README/临时文件等非槽位文件
            if path.is_file() and path.suffix in _SUFFIXES:                                         # 只收已知后缀: 忽略说明文件与临时文件
                keys.append(f"{dim}/{path.stem}")
    return sorted(keys)  # 排序稳定, 两次体检的输出可直接 diff
