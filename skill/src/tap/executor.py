"""src.tap.executor — 通过 BEST 客户端执行安全的 TAP 查询计划。

能力边界: 把 TapQueryPlan 分支翻译为 Best/BestClient 的 query 调用 (锥形走
pos.* 原生键), 合并去重 + 稳定排序 (空值恒排末尾) + 列投影; MAXREC 溢出探测
(execute_with_overflow 多取一行判断是否截断)。
边界: 不直连网络, 不解析 CSV; 后端异常统一收敛为 TapExecutionError。
白盒锚点: references/ALGORITHM-SPEC.md §6 (TAP 适配层锚点)。

历史来源: pybest 打包产物 (git 6f00efeb^〔本仓历史已无此对象〕〔本仓历史已无此对象〕) ``pybest/tap/executor.py`` (git 6f00efeb^〔本仓历史已无此对象〕), 迁入
src/tap/ 并改引 src.tap.adql。DALI MAXREC/OVERFLOW 语义: ivo://ivoa.net/std/TAP
(规范引用, 无 DOI)。

通过既有 BEST 客户端执行安全 TAP 查询计划。
"""
from __future__ import annotations

import json  # 标准库: 行去重键的 JSON 回退序列化
import math  # 标准库: NaN 判定 (缺失排序值识别)
from typing import Any  # 标准库: 行记录/查询参数的任意类型标注

# 本地导入: 查询计划与分支类型 — 执行层只消费解析层的产物 (跨解析→执行边界)
from src.tap.adql import QueryBranch, TapQueryPlan


class TapExecutionError(RuntimeError):
    """翻译后的 BEST 查询执行失败时抛出; service 层捕获后转 400/错误文档。"""


class TapExecutor:
    """把 :class:`TapQueryPlan` 翻译为 BEST 客户端调用并做合并/去重/排序。"""

    def __init__(self, best_client: Any) -> None:
        """持有 BEST 客户端实例 (``BestClient`` 或其替身; ``src`` 下只有 ``BestClient``,
            没有 ``Best``); 执行层不自行建网络连接。"""
        self.best = best_client  # 只存引用: 执行层不建连接, 会话与限流都由注入方持有

    def execute(self, plan: TapQueryPlan, *, max_rows: int = 1000) -> list[dict[str, Any]]:
        """执行 ``plan`` 并返回至多 ``max_rows`` 行。

        兼容入口, 有意不做溢出探测: 只需要数据、不需要 DALI OVERFLOW 指示的
        调用方用它; TAP HTTP handler 需要截断指示时改走
        :meth:`execute_with_overflow`。

        Args:
            plan: 解析层产出的查询计划。
            max_rows: 行数上限 (同时是每个分支的拉取上限)。

        Returns:
            list[dict[str, Any]]: 合并去重排序后的行记录。
        """
        return self._execute_limited(plan, max_rows=max_rows)

    def execute_with_overflow(
        self,
        plan: TapQueryPlan,
        *,
        max_rows: int = 1000,
    ) -> tuple[list[dict[str, Any]], bool]:
        """执行 TAP 计划并报告 MAXREC 是否发生了截断 (DALI OVERFLOW 语义)。

        只有当 ADQL ``TOP`` 没有施加相等或更小的限制时, 才多取一行用于判断
        是否被截断 — 省掉这一次额外探测可少一次上游往返。``MAXREC=0`` 是
        DALI 规定的"仅元数据"请求, 因此完全不触达后端, 直接返回空结果并标记
        溢出 (空结果即未知是否更多)。

        Args:
            plan: 查询计划。
            max_rows: MAXREC 值 (0 表示仅元数据)。

        Raises:
            ValueError: ``max_rows`` 为负数。

        Returns:
            tuple[list[dict[str, Any]], bool]: (至多 max_rows 行, 是否截断)。
        """
        limit = int(max_rows)  # 先转 int: 上游可能传来 float 或字符串形态的 MAXREC
        # 负数上限必须拒: 负 limit 会让后端按"倒数第 N 行"解释或直接返回空,
        # 两种结果都无法与"查询确实为空"区分
        if limit < 0:                                                                        # 负数 limit 直接拒: 那是上游传错, 不是业务值
            raise ValueError("max_rows must be non-negative")
        if limit == 0:  # MAXREC=0 按 DALI 是"仅元数据": 不触达后端, 但仍标 overflow
            # MAXREC=0 是 DALI 规定的"仅元数据"请求: 不触达后端 (省一次
            # 往返), 但按规范仍标记 overflow=True —— 空结果无法区分
            # "确实无数据" 与 "有数据但本次不取"
            return [], True

        # 只有当 ADQL TOP 没有施加相等或更小的限制时才多取一行: 若 TOP 已经
        # 把结果卡死在 limit, 探测行恒不存在, 多取只是白跑一次上游往返
        can_overflow = plan.limit is None or plan.limit > limit                                # 可能截断的两种情形: 计划里没限, 或限得比请求大
        probe_limit = limit + 1 if can_overflow else limit  # 探测上限只在真可能溢出时才 +1
        rows = self._execute_limited(plan, max_rows=probe_limit)  # 按探测上限执行: 多取的那一行只为判溢出, 不进结果
        # 两个条件缺一不可: 探测行数 > limit, 且确有溢出可能
        overflow = can_overflow and len(rows) > limit                                           # 两条件同时成立才算真截断, 少一个都只是"可能"
        # 切回 limit 行: 探测用的那第 limit+1 行只用于判溢出, 不进结果
        return rows[:limit], overflow  # 返回的是截断视图, rows 本身不动

    def _execute_limited(
        self,
        plan: TapQueryPlan,
        *,
        max_rows: int,
    ) -> list[dict[str, Any]]:
        """逐分支查询、合并去重、稳定排序、截断与列投影 (执行层核心)。

        语义契约:
        1. 分支合并: ``plan.branches`` 的每个 OR 分支各发一次 BEST 表单查询,
           按分支顺序拼接; 分支间是"或"关系, 同一行可能被多个分支命中。
        2. 去重: 以 ``_row_key`` 为键保持首次出现顺序, 重复行只留第一条 —
           上游对 OR 分支各查各的, 不去重会让同一颗星在结果里出现多次。
        3. 排序: 按 ORDER BY 术语逆序施加稳定排序 (从末位键到首位键), 每个键
           都是"数值优先、文本其次"的混合比较 (``_sort_key``); 该键缺失的行
           恒排在该键的末尾, 与方向无关 — 空值不该因 DESC 被顶到最前。
        4. 截断与投影: 合并排序后按上限截断, 最后才做列投影, 保证投影列
           不参与去重/排序判断之外的任何逻辑。
        """
        # 上限取 min(plan.limit, max_rows): 两个上限都要生效, 且至少为 1 ——
        # 取 0 会让分支查询直接返回空, 把"上限为 0"变成"无数据"的假象
        requested = plan.limit if plan.limit is not None else max_rows  # TOP 优先: ADQL 侧的上限比调用方的 MAXREC 更具体
        limit = min(max(1, int(requested)), max(1, int(max_rows)))  # 两个上限取小, 且各自至少为 1
        merged: list[dict[str, Any]] = []  # 跨分支累加的唯一容器: 顺序即 plan.branches 顺序
        seen: set[str] = set()  # 去重键集合: 与 merged 同步增长, 长度永远相等

        for branch in plan.branches:  # 逐分支查询: 或关系的每个分支各发一次表单
            try:
                rows = self.best.query(**self._query_kwargs(plan, branch, limit))  # 参数由翻译层组装: 本层不认 ADQL 文本, 只认翻译结果
            except Exception as exc:
                # 后端任何异常都收敛为 TapExecutionError: 上游错误信息不可信,
                # 但原文仍拼进消息便于排查 (service 层再统一转错误文档)
                raise TapExecutionError(f"BEST backend query failed: {exc}") from exc
            for row in rows or ():  # or () 兜住 None: 后端无结果时可能返回 None 而非空表
                key = self._row_key(row)  # 去重键优先用源标识列: 投影差异不该把同一目标算成两行
                # 首次出现即定案: 保留的是**第一条**命中, 后续同键行直接丢,
                # 使 OR 分支的拼接顺序 (即 plan.branches 顺序) 决定结果
                if key not in seen:
                    seen.add(key)  # 与合并容器同步记账: 两个容器长度必须始终相等
                    merged.append(dict(row))  # dict() 拷贝: 不让后端复用同一 dict 对象污染累加器

        # 逆序施加稳定排序: 从次要键排到主要键, 每一趟都是稳定排序,
        # 因此最终主要键优先, 次要键在主要键相等时决定次序
        for term in reversed(plan.order_by):                                                     # 排序键倒序遍历: 多级排序里后面的键优先级更低
            # 缺失值与有效值分开收集: 缺失恒排末尾且**与方向无关** ——
            # DESC 时若混在一起排, 空值会被顶到最前, 正是要避免的语义
            present = [row for row in merged if not self._missing_sort_value(row.get(term.column))]  # 有效值组
            missing = [row for row in merged if self._missing_sort_value(row.get(term.column))]  # 缺失值组, 恒接在末尾

            def row_sort_key(
                row: dict[str, Any],  # 排序键闭包的行入参: 已剔除缺失值分组
                column: str = term.column,  # 默认值锁住当前术语: 闭包晚于循环执行, 不锁会取到最后一轮的列名
            ) -> tuple[int, float | str]:
                """单个 ORDER BY 术语的排序键 (数值优先, 其次文本)。"""
                return self._sort_key(row.get(column))

            present.sort(  # 只排有效值组: 缺失组单独接在末尾, 不参与方向
                key=row_sort_key,  # 排序键闭包: 数值通道优先, 其次文本通道
                # reverse 直接取自 ADQL 的 DESC: 空值分组已在上面摘走,
                # 方向不会波及"缺失恒末尾"这条不变量
                reverse=term.descending,
            )
            # 就地替换切片内容 ([:] =) 而非重新绑定 merged: 保持 list 身份,
            # 避免下一趟 ORDER BY 术语作用到旧引用上
            merged[:] = present + missing
        # 排序**之后**才截断: 先截断会按分支拼接顺序取前 N 行, 与 ORDER BY
        # 无关, 结果不符合 ADQL 语义
        merged = merged[:limit]  # 到这里 merged 已是新 list, 重新绑定不会拆掉引用

        if plan.columns is not None:  # 有投影才裁列: 不给投影时原样返回全列行
            # 列投影放最后: 投影列不参与去重/排序之外的任何逻辑, 反过来做
            # 会让被投影掉的列在去重键里消失, 同一目标被误判成多行
            return [  # 投影是最外层: 截断已在它之前完成, 行数不会被投影改变
                {column: row.get(column) for column in plan.columns}  # 缺列补空值: 投影后的行不再暴露计划外的列
                for row in merged  # 在已截断的结果上投影: 行数不因投影而变
            ]
        return merged

    @staticmethod
    def _query_kwargs(plan: TapQueryPlan, branch: QueryBranch, limit: int) -> dict[str, Any]:
        """把一个 OR 分支翻译成 BEST 表单 query 调用的关键字参数。

        标量约束逐条转 ``{name, op, value|min/max}``; 锥形分支改走上游
        ``pos.*`` 原生键 (ra/dec 原样, 半径由度换算为角秒 — 上游锥形接口以
        角秒为单位); 两者都带上 ``max_rows=limit`` 让每个分支都不超过总上限。
        """
        constraints: list[dict[str, Any]] = []  # 一个分支一份约束表, 不跨分支复用
        for item in branch.constraints:  # 逐约束翻译: 一个分支的约束表不跨分支复用
            translated: dict[str, Any] = {  # 显式建 dict 而非复制: 只带该算子真正用到的键
                "name": item.column,  # 列名原样带过: 方言归一是上游协议层的活
                "op": item.operation,  # 算子原样带过: 白名单外的拼写交由上游拒绝
            }
            # between 走 min/max 双端契约, 其余算子走单值 value: 上游 BEST
            # 表单接口的两种形状不通用, 混用会被静默忽略一端
            if item.operation == "between":  # 双端算子走双槽: 混用单值会被上游静默忽略一端
                translated["min"] = item.minimum  # 下界入下限槽: 与上限成对才构成区间
                translated["max"] = item.maximum  # 上界入上限槽: 槽位约定与双端算子一一对应
            else:
                translated["value"] = item.value  # 单值算子走单槽: 不再重复填双端
            constraints.append(translated)  # 原样带过 value/min/max: 单位换算只发生在锥形键上

        kwargs: dict[str, Any] = {  # ra/dec/radius 先置 None 占位, 有锥形再 update 覆盖
            "catalog": plan.catalog,  # 星表来自计划: 执行层不猜目标表
            "constraints": constraints,  # 整份约束表: 上游按顺序逐条施加
            # ra/dec/radius 三个键必须**显式置 None**: 直传会缺键, 而上游
            # 对"无锥形约束"的判定是取不到值, 不是判 None
            "ra": None,  # 显式置空: 上游判无锥形靠取不到值, 缺键会走错分支
            "dec": None,  # 同上: 三个几何键必须成组出现
            "radius_arcsec": None,  # 同上: 少一个就退化成无空间约束的查询
            # 每个分支都带上限: 若等 OR 分支拼成一串再截断, 单个分支
            # 就可能先把内存吃光 (一个分支就能返回全表)
            "max_rows": limit,  # 每分支都带上限: 否则单个分支就能把内存吃光
            # P1 合并: 后端统一为 BestClient.query — 它**只返回裸行投影**
            # (归一化行追加的 magnitudes 字典会被 str() 成 "{'g': 19.4}"
            # 当字符列写进 VOTable, 污染科学消费端的列类型 — 见
            # file-size-budget §5.3), 调用点不再需要传 normalize 开关。
        }
        if branch.cone is not None:  # 有锥形才覆盖三键: 非锥形分支保持空值
            kwargs.update({  # 整块覆盖三键: 显式 None 的占位在这里被真值替换
                "ra": branch.cone.ra,  # 赤经原样带过: 上游吃度数, 换算只发生在半径上
                "dec": branch.cone.dec,  # 赤纬原样带过: 与赤经保持同一单位制
                # 度 -> 角秒: 上游锥形接口以角秒为单位, 漏乘 3600 会让
                # 1 度半径变成 1 角秒, 结果为空且不报错
                "radius_arcsec": branch.cone.radius_deg * 3600.0,  # 全文件唯一一处度->角秒换算
            })
        return kwargs

    @staticmethod
    def _row_key(row: dict[str, Any]) -> str:
        """行去重键: 优先用 ``*source_id*`` 列, 否则整行 JSON。

        优先 source_id 的理由: OR 分支命中的同一颗星, 其投影列可能因分支不同
        而有差异 (如某分支限制了更少列), 用整行 JSON 会把同一目标误判成两行;
        source_id 为空 (None/"") 时跳过该列, 全部为空才退回整行 JSON 兜底。
        """
        source_keys = sorted(key for key in row if key.lower().endswith("source_id"))  # 排序取首个非空: 同一目标多个 id 列时口径稳定
        for key in source_keys:  # 排序后的标识列依次尝试: 多个标识列时口径稳定
            value = row.get(key)  # 取该列取值: 空值与空串都算未命中
            if value not in (None, ""):  # 空值就换下一列: 全部为空才退回整行去重
                return f"{key}:{value}"  # 带列名前缀: 免得不同列的同号值撞成一个去重键
        return json.dumps(row, sort_keys=True, default=str, ensure_ascii=False)  # default=str 兜住不可序列化对象

    @staticmethod
    def _missing_sort_value(value: Any) -> bool:
        """判断排序值是否"缺失": None/空串, 或可转 float 后为 NaN。

        BEST 用约 -1000 的哨兵表示"无测量", 序列化层已把哨兵转成 NaN, 因此
        这里把 NaN 与空值一并视为缺失, 使它们在 ORDER BY 中恒排末尾。
        """
        if value is None or value == "":  # 空串与 None 一并当缺失: 星表里两者都表示"没这一列的值"
            return True
        try:
            # 哨兵 (≈-1000) 在序列化层已转成 NaN; NaN 参与任何比较都返回
            # False, 混排会让这些行静默留在原位而非排到末尾
            return math.isnan(float(value))  # 转 float 而非 isinstance: 字符串形态的 "nan" 也要算缺失
        except (TypeError, ValueError):
            # 转不动的是**文本**而非缺失: 文本排序键另有通道, 不能算缺失
            return False

    @staticmethod
    def _sort_key(value: Any) -> tuple[int, float | str]:
        """混合类型排序键: 可转 float 的走数值通道, 其余走文本通道。

        返回 ``(0, float)`` 或 ``(1, casefold 文本)``: 数字恒排在同一列的文
        本之前 (ADQL 侧星表列多为字符串形态, 不做此区分会出现 "10" < "9" 的
        字典序错位); 同通道内再按自然序比较。
        """
        try:
            return (0, float(value))  # 通道 0 = 数值: 通道号参与比较, 使数字恒排在本列文本之前
        except (TypeError, ValueError):
            # 通道 1 = 文本, casefold 让 "Gaia DR3" 与 "gaia dr3" 同序,
            # 避免仅大小写差异造成无意义的行序抖动
            return (1, str(value).casefold())
