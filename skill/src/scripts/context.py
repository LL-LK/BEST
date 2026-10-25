"""src.scripts.context — Context management for token/attention budgeting.

能力边界: QueryContext: token 预算与查询审计载体。边界: record 由 BestSkillClient 喂服(Q-52 接线); truncate 返回摊薄副本不改写源记录 (Q-52 修复); summary 始终报真实计数。
白盒锚点: contracts/provenance.contract.yaml (血缘载体)。
"""

from __future__ import annotations

# 标准库: 类型标注
from typing import Any


class QueryContext:
    """查询上下文跟踪器 (token 预算 + provenance 血缘载体)。

    record 由 BestSkillClient 每次查询喂服 (Q-52 接线); truncate 只返展示
    副本, summary 始终报真实计数。
    """

    def __init__(self, max_sources: int = 1000) -> None:
        """构造查询上下文, 设定向调用方展示的源数量上限。

        Args:
            max_sources: 单次查询最多向调用方展示/回传的源数 (防止把 20 亿星表
                的量级塞进上下文); 超限时 ``truncate()`` 摊薄, 但 ``summary()``
                仍报真实计数。

        Note:
            这是"展示预算"而非"数据预算" — 截断只影响呈现, 不改变已发生的查询。
        """
        self.max_sources = max_sources  # 展示预算, 不是数据预算: 不改变已发生的查询
        self.history: list[dict[str, Any]] = []  # 血缘真源: summary 的真实计数只认它

    def record(self, operation: str, params: dict, n_results: int) -> None:
        """记录一次查询操作 (审计血缘的最小单元)。

        params 以副本入库: 调用方常复用同一个 dict 并在之后改写它, 存引用
        会让已记录的历史被事后覆写, 血缘链从此不可信。

        Args:
            operation: 操作名 (如 ``cone_search``)。
            params: 查询参数 (入库时拷贝)。
            n_results: 本次真实结果数 (供 summary 报真实总数)。
        """
        self.history.append({  # 追加一条血缘: 摘要里的真实计数只认这个列表
            "operation": operation,  # 操作名入库: 事后能按动作分组统计
            # 必须存副本: 调用方常复用同一个参数 dict 并在之后改写它, 存引用
            # 会让已记录的历史被事后覆写, 血缘链从此不可信
            # 必须存副本: 调用方常复用同一个参数 dict 并在之后改写它, 存引用
            # 会让已记录的历史被事后覆写, 血缘链从此不可信
            "params": dict(params or {}),  # 必须存副本: 调用方复用并改写同一字典会让历史被覆写
            "n_results": n_results,  # 本次真实结果数, 与 truncate 的摊薄值无关
        })

    def truncate(self, max_records: int = 100) -> list[dict]:
        """Truncate results to fit context budget (返回裁剪副本, 不改源记录)。

        Q-52 不变量: 摊薄只影响返回视图, history 里的 ``n_results`` 一个都
        不改; summary()["total_results"] 必须报真实结果总数, 一旦被摊薄值
        覆写就是数据完整性缺陷。

        P3-8: ``max_sources`` 在此真正生效 — 展示预算取
        ``min(max_records, max_sources)``; 配置了不执行等于没有配置, 调用方
        传多大的 max_records 都放行, 所以钳制必须落在这里。
        """
        # 展示预算取"调用方请求值"与"上下文自身上限"的较小者: max_sources<=0
        # 视作不设限, 否则配置成 0 的调用方会被裁成 0 行而不知情
        budget = int(max_records)  # 起点取调用方请求值: 展示预算默认跟着请求走
        if self.max_sources and self.max_sources > 0:  # 非正视为不设限: 否则配成 0 的调用方会被裁成 0 行而不知情
            budget = min(budget, int(self.max_sources))  # 与自身上限取小: 上下文配的预算必须真正生效
        # total 取历史真实计数而非上次返回视图的计数: 截断是幂等可重复的,
        # 拿摊薄值当基数会让连续两次 truncate 的比例越来越偏
        total = sum(h["n_results"] for h in self.history)  # 基数取历史真实计数: 拿摊薄值当基数会让连续两次截断越来越偏
        if total <= budget:  # 未超预算就原样返回浅拷贝: 不必走摊薄分支
            return list(self.history)  # 浅拷贝: 返回视图也不该让调用方改到源记录
        # 按比例摊薄的展示副本 (源记录一个字段都不动)
        scale = budget / total if total else 0.0  # total>0 已由上一分支保证, 兜底仅为除零
        view: list[dict[str, Any]] = []  # 另建视图容器: 源记录一个字段都不动
        for h in self.history:  # 逐条摊薄: 比例一致才不会让某些源凭空消失
            shown = h.copy()  # 逐条浅拷贝: 改展示值不影响血缘真源
            # 逐条取整会让各条之和偏离 budget, 偏差随历史条数放大
            shown["n_results"] = int(h["n_results"] * scale)  # 一次性按比例取整: 逐条取整会让各条之和偏离预算
            view.append(shown)
        return view

    def summary(self) -> dict[str, Any]:
        """生成上下文摘要 (真实计数, 不受 truncate 摊薄影响)。

        Returns:
            ``{"total_operations": int, "total_results": int, "max_sources": int}``;
            total_results 是历史真实结果总数, 不是摊薄后的展示值。
        """
        return {
            "total_operations": len(self.history),  # 报真实操作条数: 与展示了多少条无关
            "total_results": sum(h["n_results"] for h in self.history),  # 报真实总数, 不受摊薄影响
            "max_sources": self.max_sources,  # 回报配置原值, 让调用方知道自己被钳到多少
        }

