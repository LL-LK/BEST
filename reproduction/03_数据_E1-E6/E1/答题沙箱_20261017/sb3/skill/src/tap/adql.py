"""src.tap.adql — 有界 ADQL 子集解析器。

能力边界: 把 ADQL 查询解析为类型化查询计划 (TapQueryPlan), 由 src.tap.executor
翻译为 BEST 两阶段表单协议; 绝不转发任意 SQL 文本到上游 (BEST 不执行 SQL)。
边界: 仅支持 SELECT/TOP/WHERE(AND-OR 16 分支上限)/ORDER BY/CONTAINS(POINT) 锥形;
JOIN/GROUP/HAVING/UNION/子查询/聚合/函数投影一律拒绝; 列名按
src.protocol.CATALOG_COLUMNS 白名单校验。
白盒锚点: references/ALGORITHM-SPEC.md §6 (TAP 适配层锚点)。

历史来源: 打包产物 pybest 打包产物 (git 6f00efeb^〔本仓历史已无此对象〕〔本仓历史已无此对象〕) 的 ``pybest/tap/adql.py`` (TAP+OAuth 设计稿实现, git 6f00efeb^〔本仓历史已无此对象〕〔本仓历史已无此对象〕),
按本 skill 能力边界迁入 src/tap/
并改引 src.protocol。IVOA TAP 标准: ivo://ivoa.net/std/TAP (规范引用, 无 DOI)。

BEST 公共服务不执行 SQL: 因此本解析器只产出一个小而类型化的查询计划,
可在不向上游转发任意 SQL 文本的前提下, 翻译为已验证的 form/sqlid 两阶段协议。
"""
from __future__ import annotations

import re  # 标准库: ADQL 词法正则
from dataclasses import dataclass  # 标准库: 不可变查询计划与约束记录
from typing import Any  # 标准库: 约束值/字面量的任意类型标注

# 本地导入: 权威列名白名单与星表路径表 — 表名/列名只认 src.protocol 的集合 (跨协议层能力边界)
from src.protocol import CATALOG_ALIASES, CATALOG_COLUMNS, CATALOG_PATHS


class ADQLError(ValueError):
    """ADQL 非法或超出支持子集时抛出; service 层捕获后转 400 VOTable 错误文档。"""


@dataclass(frozen=True)
class TapConstraint:
    """单条标量约束: 列名 + 操作符 + 取值 (或区间端点)。

    operation 取 equal/notequal/less/lessequal/greater/greaterequal/between,
    由 executor 原样搬进 BEST 表单 constraints 项; between 走 minimum/maximum,
    其余操作符走 value。
    """

    column: str                        # 已过白名单的权威拼写 (归一化在 _normalize_column)
    operation: str                     # between 走 minimum/maximum, 其余走 value
    value: Any = None                  # 单值操作的操作数; between 时恒为 None
    minimum: Any = None                # 区间下界: ADQL BETWEEN 的第一个端点
    maximum: Any = None                # 区间上界: 两端点顺序不可交换


@dataclass(frozen=True)
class ConeConstraint:
    """锥形约束: POINT(ra,dec) 圆心与半径 (度), 由 executor 转上游 pos.* 原生键。"""

    ra_column: str                     # 须为 {catalog}_ra: 走 pos.* 原生键, 列名错不会报错
    dec_column: str                    # 须为 {catalog}_dec, 且与 ra 的顺序固定
    ra: float                          # 圆心赤经 (度), 校验区间 [0, 360)
    dec: float                         # 圆心赤纬 (度), 校验区间 [-90, 90]
    radius_deg: float                  # 半径 (度), 上界 180: 再大等同全表扫


@dataclass(frozen=True)
class QueryBranch:
    """一个 OR 分支: 该分支内的全部 AND 标量约束 + 至多一个锥形约束。"""

    constraints: tuple[TapConstraint, ...] = ()  # 按书写顺序拼接; 顺序影响上游表单的缓存键
    cone: ConeConstraint | None = None           # 至多一个: 两个并存时显式拒绝而非静默丢弃


@dataclass(frozen=True)
class OrderTerm:
    """ORDER BY 一项: 列名 + 是否降序 (executor 排序时缺失值恒排末尾)。"""

    column: str                        # 排序列同样过列白名单, 不开后门
    descending: bool = False           # ASC 可省略, DESC 必须显式写出


@dataclass(frozen=True)
class TapQueryPlan:
    """查询计划: 星表/投影列/TOP 限制/OR 分支/排序项, 即 BEST 表单协议的输入。"""

    catalog: str                       # 规范星表 id: 已剥限定名并过 CATALOG_PATHS
    columns: tuple[str, ...] | None    # None = SELECT *: 序列化阶段按星表全列补列名
    limit: int | None                  # TOP n 展开的正整数; None = 不限行
    branches: tuple[QueryBranch, ...]  # OR 展开后的并行分支: executor 一支一个上游请求
    order_by: tuple[OrderTerm, ...] = ()  # 空元组 = 不排序; 缺失值恒排末尾


@dataclass(frozen=True)
class _Token:
    """词法单元: kind 为 number/string/op/punct/ident, value 保留原文。"""

    kind: str                          # 五类之一, 由正则的命名组直接决定
    value: str                         # 保留原文: 关键字比对走大写, 原文只进错误信息


# 词法正则: 数字(含科学计数法与正负号)/单引号字符串('' 为 SQL 转义)/比较符/
# 标点/限定标识符(允许 . 与 $); 候选顺序即优先级 — 数字先于标识符, 保证
# "1e3" 整体成 number 而不被切成 ident。消费方: _tokenize 与 _Parser。
_TOKEN = re.compile(  # 候选顺序即优先级: number 先于 ident, "1e3" 才不会被切成两段
    r"(?P<number>[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)"
    r"|(?P<string>'(?:''|[^'])*')"
    r"|(?P<op><=|>=|<>|!=|=|<|>)"  # 长符号在前: "<=" 必须先于 "<" 命中
    r"|(?P<punct>[(),*])"
    r"|(?P<ident>[A-Za-z_][A-Za-z0-9_$.]*)"
)

# 子句关键字表: 出现在 FROM 之后的裸标识符若属于这些词, 说明"别名已结束";
# 同时是解析收尾时对残留 token 的分类依据 (JOIN/GROUP 等据此给出针对性拒绝)。
_CLAUSE_WORDS = {  # 兼作两用: 裸别名识别的终止集 + 残留 token 的拒绝分类依据
    "WHERE", "ORDER", "JOIN", "LEFT", "RIGHT", "INNER", "OUTER",
    "FULL", "CROSS", "GROUP", "HAVING", "UNION", "LIMIT", "OFFSET",
}


def _tokenize(query: str) -> list[_Token]:
    """把 ADQL 文本切成有序 token 流。

    边界与拒绝语义: 出现语句分隔符 ``;`` 或注释起止 (``--``/``/*``/``*/``)
    立即拒绝 — 多语句堆叠与注释注入不在白名单内; 任何无法被 ``_TOKEN`` 匹配
    的字符同样拒绝 (静默跳过不可见字符会让解析位置与原文脱节)。返回按出现顺序排列的
    token 列表, 供 ``_Parser`` 递归下降消费。
    """
    # 语句分隔符与注释一律拒绝: BEST 不执行 SQL, 但放开 ";" 意味着一次
    # 请求里可以堆叠多条查询, 绕过分支上限并让错误信息与实际执行者不符
    if ";" in query or "--" in query or "/*" in query or "*/" in query:
        raise ADQLError("Unsupported token in ADQL")  # 不细分是 ; 还是注释: 三者同为白名单外构造
    tokens: list[_Token] = []                 # 预建列表: 解析期只追加, 不重排
    pos = 0                                    # 扫描游标: 单趟前移, 不回溯
    while pos < len(query):                                                                         # 扫描式解析: 查询串变长, 只能边走边取
        if query[pos].isspace():
            pos += 1
            continue                           # 空白只做分隔, 不进 token 流
        # 严格逐字符推进: 任何无法匹配的字符都报错而非跳过, 否则一个不可见
        # 字符就能把 ``ra=1 AND dec=2`` 静默切成两段语义不同的查询
        match = _TOKEN.match(query, pos)      # 用 match 而非 search: 位置敏感, 漏匹配即报错
        if not match:
            # 只回显 20 字符: 整段回显会把用户的完整查询写进日志与错误文档
            raise ADQLError(f"Unsupported token near {query[pos:pos + 20]!r}")
        kind = match.lastgroup or ""          # lastgroup 即命中的命名组: 正则分支与 kind 一一对应
        tokens.append(_Token(kind, match.group(kind)))  # 只取命中组原文, 不含前导空白
        pos = match.end()                     # 直接跳到匹配末尾: 词法层不做回溯匹配
    return tokens                              # 顺序即出现顺序, 递归下降按序消费


class _Parser:
    """递归下降解析器: SELECT → FROM/别名 → WHERE(OR→AND→因子→谓词) → ORDER BY。

    ``max_branches`` 限制 AND/OR 展开后的分支总数 (公开入口默认 16): 形如
    ``a=1 OR a=2 OR ...`` 的查询会把分支组合放大成上游表单请求风暴, 上限
    必须在前端就掐断, 不能指望上游限流。
    """

    def __init__(self, query: str, max_branches: int) -> None:
        """保存 token 流并初始化解析游标; ``max_branches`` 下限钳到 1。"""
        self.tokens = _tokenize(query)      # 词法先于语法: 不可见字符在这一步就被拒
        self.index = 0                      # 单游标递归下降: 各层子解析共享同一位置
        # max(1, ...): 传 0 或负数时钳到 1 而不是放行无限分支, 否则等于
        # 关掉了唯一防表单请求风暴的闸门
        self.max_branches = max(1, int(max_branches))  # 下限 1: 负上限等于没上限
        self.catalog = ""                   # 由 parse 从 FROM 填; 列名归一化依赖它
        self.alias = ""                     # 可选: FROM t AS a 的 a, 供 alias.col 校验

    def parse(self) -> TapQueryPlan:
        """解析完整 token 流为 :class:`TapQueryPlan`。

        支持子集: ``SELECT [TOP n] cols|* FROM table [AS alias] [WHERE ...]
        [ORDER BY col [ASC|DESC], ...]``; 任何白名单外结构 (JOIN/GROUP/
        HAVING/UNION/子查询/函数投影) 一律抛 :class:`ADQLError`, 绝不静默
        忽略 — 放行一个上游不认识的构造只会把错误推到 500。
        """
        self._expect_word("SELECT")                # 唯一支持的语句头: 其它动词都从这里就拒
        limit = None                                # 无 TOP 时不限行, 与 DALI MAXREC 缺省行为一致
        if self._accept_word("TOP"):                # TOP 可选: 它是本子集里唯一的行数限制
            raw_limit = self._expect("number").value  # 先取原文再转 float: 需要 is_integer 判正整数
            value = float(raw_limit)                # 经浮点中转: "1e2" 这类写法也能被统一判掉
            # TOP 只接受正整数: 对应 DALI MAXREC 的 ADQL 侧写法, 小数/负数/零无意义
            if value <= 0 or not value.is_integer():
                raise ADQLError("TOP must be a positive integer")  # 零/负/小数一律拒: MAXREC 语义是正整数
            limit = int(value)                      # 确认正整数后才截断, 免得把 1.5 悄悄取整

        raw_columns: list[str] | None
        if self._accept_value("*"):                # SELECT * 走 None 投影, 不在此展开成列清单
            # SELECT * 保留 None 投影: 序列化阶段按星表全列补列名
            raw_columns = None                      # None 与空列表语义不同: 前者是"全部列"
        else:
            raw_columns = []                        # 显式投影: 保持书写顺序, 序列化时按序发给上游
            while True:
                token = self._expect("ident")       # 列名必须是标识符或限定名, 拆分留给归一化
                if self._peek_value() == "(":
                    # 投影里的 "(" 即函数/聚合 (COUNT/AVG/...) — 白名单外, 拒绝
                    raise ADQLError("aggregate and function projections are not supported")
                raw_columns.append(token.value)     # 先存原文: 白名单比对统一放到归一化阶段
                if not self._accept_value(","):     # 逗号是投影列表的唯一续接符
                    break

        self._expect_word("FROM")                  # 投影后必须紧跟 FROM: 中间任何结构都不支持
        if self._peek_value() == "(":
            # FROM ( 即子查询/派生表 — 两阶段表单协议没有对应物, 拒绝
            raise ADQLError("Subqueries are not supported")
        table = self._expect("ident").value         # 表名允许限定写法 (best.gaia_dr3)
        # 表名取限定名最后一段并小写: ADQL 写 ``best.gaia_dr3`` 而白名单只按
        # 规范 id 登记, 不剥前缀就永远匹配不上
        self.catalog = table.split(".")[-1].lower()  # 取最后一段并小写: 白名单登记的只有规范 id
        if self.catalog not in CATALOG_PATHS:       # 表名白名单同样取自 protocol 层, 不本地维护
            # 未知表直接拒绝: 放行会在构造上游请求时才失败, 错误信息与
            # 用户实际写的东西对不上
            raise ADQLError(f"Unknown BEST table: {table}")  # 早失败: 错误信息与用户写的东西对得上

        if self._accept_word("AS"):                 # 显式别名
            self.alias = self._expect("ident").value  # 原样保存, 校验时按小写比对
        elif self._peek_kind() == "ident" and self._peek_upper() not in _CLAUSE_WORDS:  # 省略 AS 的裸别名
            # 省略 AS 的裸别名 (pyvo/TOPCAT 常见写法): 非子句关键字的 ident 按别名消费
            self.alias = self._next().value         # 非子句关键字才当别名: 否则 WHERE 会被吃掉

        columns = (                                                                          # 列名按 select 列表的顺序固定, 不随站点返回变
            tuple(self._normalize_column(column) for column in raw_columns)  # 逐列过白名单, 未知列在此就抛
            if raw_columns is not None
            else None                                # SELECT * 分支跳过归一, 保持 None
        )

        branches = [QueryBranch()]                  # 兜底空分支: 无 WHERE 时 executor 也走同一条循环
        if self._accept_word("WHERE"):              # WHERE 可选; 省略即整锥或全表查询
            # 无 WHERE 时给一个空分支: 让 executor 的"逐分支查询"循环不必
            # 特判空分支列表, 整锥查询与纯标量查询共用同一条执行路径
            branches = self._parse_or()

        order_by: list[OrderTerm] = []             # 排序项: 空列表表示不排序
        if self._accept_word("ORDER"):              # ORDER BY 可选, 且本子集不接受 OFFSET
            self._expect_word("BY")                 # ORDER 必须成对跟 BY, 单独 ORDER 算残留 token
            while True:
                # 排序列同样过白名单; ASC 可省略, DESC 必须显式
                column = self._normalize_column(self._expect("ident").value)  # 不过白名单就会排一个不存在的列
                descending = self._accept_word("DESC")  # 先试 DESC: 缺省是升序, DESC 才是显式写法
                if not descending:
                    self._accept_word("ASC")         # 显式 ASC 消费掉即可, 不进 order_by 语义
                order_by.append(OrderTerm(column, descending))  # 多项排序按书写顺序进元组
                if not self._accept_value(","):     # 逗号续接下一个排序项
                    break

        if self.index != len(self.tokens):         # 必须恰好消费完: 残留即白名单外结构
            # 收尾时仍有残留 token: 按关键字分类给出针对性拒绝, 其余报意外 token
            word = self._peek_upper() or self._peek_value()  # 关键字先看大写形式, 否则看原文
            if word in {"JOIN", "LEFT", "RIGHT", "INNER", "OUTER", "CROSS"}:  # 六种 JOIN 归一类
                raise ADQLError("JOIN is not supported")  # 明确拒绝而非忽略: 表单协议没有 JOIN
            if word in {"GROUP", "HAVING", "UNION"}:  # 聚合与集合运算同理
                raise ADQLError(f"{word} is not supported")  # 报出具体关键字, 用户才知道怎么改写
            raise ADQLError(f"Unexpected token {self._peek_value()!r}")  # 其余残留报原文, 便于定位

        return TapQueryPlan(                        # frozen 计划: executor 侧不再改动, 可跨线程传
            catalog=self.catalog,
            columns=columns,
            limit=limit,
            branches=tuple(branches),               # 列表转元组: 计划对象不可变
            order_by=tuple(order_by),
        )

    def _parse_or(self) -> list[QueryBranch]:
        """按 OR 收集若干 AND 组, 展开成并行分支列表 (顺序即分支顺序)。"""
        branches = self._parse_and()              # OR 的第一组, 后面每组都追加在它之后
        while self._accept_word("OR"):            # 平铺 OR; 嵌套括号由 _parse_factor 处理
            branches.extend(self._parse_and())    # 顺序即书写顺序: 分支序号进上游请求与缓存键
            # 每吃进一个 OR 组立即校验分支上限, 超限早失败以免继续解析放大开销
            self._check_branch_count(branches)    # 每组都数一次, 不等全部解析完
        return branches                           # 交给 _parse_and 做笛卡尔积合并

    def _parse_and(self) -> list[QueryBranch]:
        """按 AND 做分支笛卡尔积合并, 并强制"每分支至多一个锥形约束"。

        不变量: ``CONTAINS(...) AND CONTAINS(...)`` 不可并存 — 上游表单只接受
        单锥形, 后一个锥形被静默丢弃会造成结果偏差, 所以此处显式拒绝。
        """
        branches = self._parse_factor()           # 左侧首个因子: 可能是锥形也可能是标量谓词
        while self._accept_word("AND"):            # 逐个吸收右因子, 每轮都做一次笛卡尔积
            right = self._parse_factor()           # 右侧同样展开成分支列表
            combined: list[QueryBranch] = []       # 组合结果另起表: 避免边迭代边改写
            # 笛卡尔积: 左右两组分支的每一种组合都是一个独立的上游请求,
            # 这正是分支数会爆炸的地方
            for left_branch in branches:           # 双层循环即笛卡尔积: 分支数在此放大
                for right_branch in right:         # 每一种 (左, 右) 组合都成一个独立上游请求
                    if left_branch.cone is not None and right_branch.cone is not None:  # 上游表单只收单锥形
                        raise ADQLError("Only one cone constraint is allowed per branch")  # 显式拒绝: 静默丢弃会让结果有偏
                    combined.append(              # 每种组合落成一条新分支
                        QueryBranch(
                            # 约束按左后右拼接, 保持书写顺序: 上游表单按序求交,
                            # 顺序变了可能命中不同的缓存键
                            constraints=left_branch.constraints + right_branch.constraints,  # 左后右: 保持书写顺序
                            cone=left_branch.cone or right_branch.cone,  # 两侧至多一个锥形, 直接取非空者
                        )
                    )
            # 每次合并完立即计数: 组合是逐步放大的, 只在末尾查一次已经太晚
            self._check_branch_count(combined)     # 合并完立即计数: 组合是逐步放大的
            branches = combined                    # 换成本次结果, 继续与它做下一次笛卡尔积
        return branches                            # 全部 AND 吸收完毕

    def _parse_factor(self) -> list[QueryBranch]:
        """因子: 左括号起头的分组递归按 OR 解析, 否则是单个谓词分支。"""
        if self._accept_value("("):               # 左括号 = 显式分组, 内部按 OR 解析
            branches = self._parse_or()            # 递归复用同一套 OR/AND 规则, 不另写一套
            self._expect_value(")")                # 括号必须闭合: 不做自动补全
            return branches                        # 分组结果直接上抛, 参与外层 AND 的笛卡尔积
        return [self._parse_predicate()]          # 单谓词包成单元素列表: 统一成"分支列表"语义

    def _parse_predicate(self) -> QueryBranch:
        """谓词: CONTAINS(POINT) 锥形、BETWEEN 区间, 或"列 比较符 字面量"。

        兼容 pyvo/ADQL 常见的 ``1=CONTAINS(POINT(...),CIRCLE(...))`` 写法:
        先用保存的索引试探, 不成立即回退, 不影响普通比较谓词的解析。
        """
        if self._peek_upper() == "CONTAINS":      # 锥形谓词: 只能以 CONTAINS 开头
            cone = self._parse_contains()         # 坐标系/区间/坐标列名校验都在里面完成
            if self._accept_value("="):           # 允许 CONTAINS(...) = 1 的镜像写法
                # 允许 CONTAINS(...) = 1 后缀 (1=CONTAINS(...) 的镜像写法)
                self._expect_one()                # 右值必须是 1: ADQL 布尔比较的固定惯例
            return QueryBranch(cone=cone)         # 锥形独占一个分支, 不与标量约束混装

        if self._peek_kind() == "number" and float(self._peek_value()) == 1.0:  # 试探 1=CONTAINS 写法
            # 试探 "1=CONTAINS(...)": 先存索引, 非锥形则回退, 避免误判普通数字比较
            saved = self.index                    # 存游标: 试探失败必须能原样回退
            self._next()                          # 吃掉那个 1
            if self._accept_value("=") and self._peek_upper() == "CONTAINS":  # 两段都对上才认是锥形
                return QueryBranch(cone=self._parse_contains())  # 确认是镜像写法, 按标准锥形解析
            self.index = saved                     # 回退: 否则 1=2 这类比较会被吞掉一个 token

        column = self._normalize_column(self._expect("ident").value)  # 左值必须过列白名单
        if self._accept_word("BETWEEN"):          # 区间: 上游表单原生支持, 不拆成两条比较
            # BETWEEN a AND b → between 操作符 (min/max), 上游表单原生支持区间
            minimum = self._parse_literal()       # 第一个端点作下界
            self._expect_word("AND")              # 这个 AND 是语法的一部分, 不参与分支展开
            maximum = self._parse_literal()       # 第二个端点作上界; 大小关系交上游裁剪
            return QueryBranch(                   # 区间整体成一条约束, 不拆
                constraints=(TapConstraint(column, "between", minimum=minimum, maximum=maximum),)  # 元组包一层: 分支内可有多条
            )

        operator = self._expect("op").value       # 比较符: 词法层已保证落在六种之内
        value = self._parse_literal()             # 右值只收字面量: 本子集不支持列间比较
        # ADQL 比较符 → executor 表单 op 名; <> 与 != 同为 notequal
        operations = {                            # 映射表把 ADQL 符号翻成 BEST 表单的 op 名
            "=": "equal",                         # 显式列举: 漏配会 KeyError, 比静默错配好
            "!=": "notequal",
            "<>": "notequal",                     # 与 != 同义, 归到同一个表单操作
            "<": "less",
            "<=": "lessequal",
            ">": "greater",
            ">=": "greaterequal",
        }
        return QueryBranch(constraints=(TapConstraint(column, operations[operator], value=value),))  # 单约束分支

    def _parse_contains(self) -> ConeConstraint:
        """解析 ``CONTAINS(POINT('ICRS',ra,dec),CIRCLE('ICRS',ra,dec,radius))`` 锥形。

        边界: 坐标框架只接受 ICRS (可省略); RA∈[0,360)、Dec∈[-90,90]、半径
        ∈(0,180] 度; POINT 的两个坐标列必须恰为 ``{catalog}_ra``/``{catalog}_dec``
        且顺序固定 — 锥形查询由上游 pos.* 原生键执行, 不落在通用表单约束上,
        因此坐标列名写错会被明确拒绝而不是悄悄按错误列检索。
        """
        self._expect_word("CONTAINS")
        self._expect_value("(")
        self._expect_word("POINT")
        self._expect_value("(")
        self._parse_frame()
        self._expect_value(",")
        ra_column = self._normalize_column(self._expect("ident").value)
        self._expect_value(",")
        dec_column = self._normalize_column(self._expect("ident").value)
        self._expect_value(")")
        self._expect_value(",")
        self._expect_word("CIRCLE")
        self._expect_value("(")
        self._parse_frame()
        self._expect_value(",")
        ra = float(self._expect("number").value)
        self._expect_value(",")
        dec = float(self._expect("number").value)
        self._expect_value(",")
        radius = float(self._expect("number").value)
        self._expect_value(")")
        self._expect_value(")")
        if not 0.0 <= ra < 360.0:                                                           # RA 必须落在 [0,360): 越界值会被站点静默取模
            raise ADQLError("Cone RA must be in [0, 360)")
        if not -90.0 <= dec <= 90.0:                                                             # Dec 必须落在 [-90,90], 越界同理
            raise ADQLError("Cone Dec must be in [-90, 90]")
        # 半径上界 180 度 = 整个天球: 再大与"全表扫"等价, 会让锥形约束
        # 名存实亡 (用户以为缩小了范围, 实际一条不少全查回来)
        if radius <= 0.0 or radius > 180.0:                                                    # 半径 0 或超半球都无意义, 早失败好过让站点回空
            raise ADQLError("Cone radius must be in (0, 180]")
        expected_ra = f"{self.catalog}_ra"
        expected_dec = f"{self.catalog}_dec"
        # 坐标列必须恰为 {catalog}_ra/{catalog}_dec 且顺序固定: 锥形走的是
        # 上游 pos.* 原生键而非通用表单约束, 列名写错不会报错, 只会按错误列
        # 检索并返回一批看似合理实则无关的行
        if ra_column != expected_ra or dec_column != expected_dec:                          # 列名必须与请求里的约定一致: 不匹配说明查询与元数据脱节
            raise ADQLError(
                "POINT coordinate columns must be "
                f"{expected_ra}, {expected_dec} in that order"
            )
        return ConeConstraint(ra_column, dec_column, ra, dec, radius)

    def _parse_frame(self) -> None:
        """坐标框架字符串: 仅接受 ICRS (大小写不敏感, 空串按省略处理)。"""
        token = self._expect("string")
        # '' 解义后再大写: 先大写会把 SQL 转义引号原样带进判定
        frame = token.value[1:-1].replace("''", "'").upper()
        if frame not in {"", "ICRS"}:
            # 只支持 ICRS: BEST 存的坐标就是 ICRS, 放行 FK5 会让用户以为做了
            # 框架转换, 实际拿到的是未经转换的 ICRS 值
            raise ADQLError("Only the ICRS coordinate frame is supported")

    def _parse_literal(self) -> Any:
        """字面量: 数字 (整数值收敛为 int)、单引号字符串 (``''`` 解义为 ``'``)、NULL → ``"null"``。"""
        token = self._next()                                                                     # 一次只前进一个 token: 出错位置才好回溯
        if token.kind == "number":
            value = float(token.value)
            # 整数值收敛为 int: 上游表单按类型分派, 1.0 与 1 在不同星表上
            # 会命中不同的表单字段
            return int(value) if value.is_integer() else value
        if token.kind == "string":
            return token.value[1:-1].replace("''", "'")
        if token.kind == "ident" and token.value.upper() == "NULL":
            # NULL 归一成字符串 "null": 与上游表单的空值约定一致, 避免
            # Python None 在 JSON 序列化后变成 null 字面量字符串再被二次解析
            return "null"
        raise ADQLError(f"Expected a literal, got {token.value!r}")

    def _normalize_column(self, raw: str) -> str:
        """列名规范化: 去限定前缀 (校验别名/表名)、裸 ra/dec 补星表前缀、白名单比对。

        白名单取自 ``src.protocol.CATALOG_COLUMNS``; 大小写不敏感匹配, 返回
        权威拼写 — 上游各星表列名大小写不统一, 统一由协议层键集裁定。
        """
        parts = raw.split(".")                    # 按点拆限定名: 段数不限, 只看最后两段
        column = parts[-1]                       # 最后一段是列名, 前面各段只作限定符
        if len(parts) > 1 and self.alias:         # 有限定名才校验, 且须已解析出别名/表名
            # alias.col 形式: 限定名必须匹配当前别名或星表名, 否则是 JOIN 的残留写法
            qualifier = parts[-2]                 # 只看紧邻的一段: 更前面的段不参与判定
            if qualifier.lower() not in {self.alias.lower(), self.catalog.lower()}:  # 别名或星表名二选一
                raise ADQLError(f"Unknown table alias: {qualifier}")  # 不匹配即拒: 多表限定的残留写法
        if column.lower() in {"ra", "dec"}:      # 裸坐标列按当前星表补前缀
            # 裸 ra/dec 按当前星表补前缀 (best.ps1 → ps1_ra), 与 TAP_SCHEMA 暴露列一致
            column = f"{self.catalog}_{column.lower()}"  # 补成 ps1_ra: 与 TAP_SCHEMA 暴露的列名一致
        # 别名归一: CATALOG_ALIASES 只登记**包外旧调用方**的旧拼写
        # (gaia_dr3 -> gaia_dr3_18), 而 L201 的表名白名单只认规范 id, 旧拼写在
        # FROM 阶段就已被拒 (E4 要求枚举外表名 100% 拒绝), 故本行归一对 ADQL
        # 入口**不可达**: set(CATALOG_PATHS) 与 set(CATALOG_ALIASES) 交集为空,
        # 恒取默认值。保留是防御 —— 万一日后白名单纳入别名键, 这里不必再改。
        # **不要**为了"让用户可写旧拼写表名"去放宽 L201。
        known = CATALOG_COLUMNS.get(             # 列白名单与别名表都取自 protocol 层, 本地不维护
            CATALOG_ALIASES.get(self.catalog, self.catalog), ())  # 防御性归一: 当前为恒等映射
        match = next((item for item in known if item.lower() == column.lower()), None)  # 大小写不敏感, 返回权威拼写
        if match is None:                        # 未命中即未知列: 不透传给上游
            # 未知列直接拒绝: 透传给上游只会被 500 收场, 且错误信息与用户写的东西对不上
            raise ADQLError(f"Unknown column {raw!r} for best.{self.catalog}")  # 带原文与星表, 用户能直接定位
        return match                             # 返回白名单里的拼写, 下游不必再做大写处理

    def _check_branch_count(self, branches: list[QueryBranch]) -> None:
        """分支数超上限即拒绝: OR/AND 展开可能组合爆炸, 上限由构造参数控制。"""
        # 在展开过程中就掐断: 等解析完再数, 一次精心构造的查询就能先把
        # 内存与 CPU 打满, 闸门就失去意义
        if len(branches) > self.max_branches:    # 展开中就掐断: 解析完再数已经太晚
            raise ADQLError(                     # 消息带上实际上限, 用户才知道该拆查询还是调参数
                f"ADQL expands to too many OR branches (maximum {self.max_branches})"
            )

    def _expect_one(self) -> None:
        """``CONTAINS(...) = 1`` 的右值必须是数字 1 (ADQL 布尔比较惯例)。"""
        token = self._expect("number")           # 右值必须是数字 token, 其它 kind 直接拒
        if float(token.value) != 1.0:            # 布尔比较惯例固定为 1, 其它值无意义
            raise ADQLError("CONTAINS must be compared with 1")  # 明确报错好过当成普通数字比较

    def _peek_kind(self) -> str:
        """查看当前 token 的 kind; 越界返回空串 (调用方据此收尾)。"""
        return self.tokens[self.index].kind if self.index < len(self.tokens) else ""  # 越界返空串: 调用方按"没匹配上"收尾

    def _peek_value(self) -> str:
        """查看当前 token 原文; 越界返回空串。"""
        return self.tokens[self.index].value if self.index < len(self.tokens) else ""  # 同上, 看原文而非 kind

    def _peek_upper(self) -> str:
        """当前 token 原文的大写形式 (ADQL 关键字大小写不敏感)。"""
        return self._peek_value().upper()        # 关键字比对统一走大写: ADQL 大小写不敏感

    def _next(self) -> _Token:
        """消费并返回当前 token; 流已耗尽则抛 :class:`ADQLError`。"""
        if self.index >= len(self.tokens):       # 流耗尽即语法错误, 不返回哨兵 token
            raise ADQLError("Unexpected end of ADQL")  # 报"到头了", 区别于"类型不符"
        token = self.tokens[self.index]          # 先取值再推进游标, 顺序反了会跳过当前 token
        self.index += 1                          # 单游标即递归下降的状态: 各子解析共享
        return token

    def _expect(self, kind: str) -> _Token:
        """消费一个指定 kind 的 token, 不匹配即拒绝 (错误信息带原文便于定位)。"""
        token = self._next()                     # 先消费再判类型: 错误信息里带的是刚读到的
        if token.kind != kind:                   # kind 不符即拒: 不做隐式类型转换
            raise ADQLError(f"Expected {kind}, got {token.value!r}")  # 报期望类型与实际原文
        return token                             # 返回已消费的 token, 调用方直接取 value

    def _accept_value(self, value: str) -> bool:
        """当前 token 原文等于 ``value`` 则消费并返回 True (标点/符号匹配)。"""
        if self._peek_value() == value:          # 只看原文: 标点无大小写问题
            self.index += 1                      # 命中才推进; 标点不存在既是前缀又是整 token
            return True
        return False                             # 不命中: 调用方据此区分"可选"与"必需"

    def _expect_value(self, value: str) -> None:
        """必须出现指定标点/符号, 否则拒绝。"""
        if not self._accept_value(value):        # 复用 accept 的游标推进, 不另写一套
            raise ADQLError(f"Expected {value!r}, got {self._peek_value()!r}")  # 报期望符号与实际原文

    def _accept_word(self, word: str) -> bool:
        """当前 ident 大写后等于 ``word`` 则消费 (关键字匹配, 大小写不敏感)。"""
        if self._peek_kind() == "ident" and self._peek_upper() == word:  # 必须先是 ident: 免得把字符串 "WHERE" 当关键字
            self.index += 1                      # 命中才推进: 未命中时游标留给调用方
            return True
        return False

    def _expect_word(self, word: str) -> None:
        """必须出现指定关键字, 否则拒绝。"""
        if not self._accept_word(word):          # 关键字同样复用 accept 的推进逻辑
            raise ADQLError(f"Expected {word}, got {self._peek_value()!r}")  # 用大写关键字名报出, 便于对照


def parse_adql(query: str, *, max_branches: int = 16) -> TapQueryPlan:
    """把受支持的 ADQL 子集解析为安全查询计划 (本模块公开入口)。

    Args:
        query: ADQL 文本; 非字符串或空白字符串直接拒绝。
        max_branches: OR/AND 展开后的分支上限, 超过即 :class:`ADQLError`。

    Returns:
        TapQueryPlan: 可直接交给 ``src.tap.executor`` 翻译为 BEST 表单调用。

    Raises:
        ADQLError: 查询为空, 或超出支持子集 (JOIN/GROUP/子查询/聚合/未知列/
            坐标越界/分支超限等)。
    """
    if not isinstance(query, str) or not query.strip():  # isinstance 在前: None/bytes 不能进词法器
        # 非 str 也要拒: isinstance 判在前, 否则一个 None/bytes 会走到
        # _tokenize 里抛 AttributeError, 网关侧看到的是 500 而非 400
        raise ADQLError("ADQL query cannot be empty")  # 明确失败: 网关侧转 400 而不是 500
    return _Parser(query, max_branches=max_branches).parse()  # 解析器不跨查询复用: 游标状态是单次语义
