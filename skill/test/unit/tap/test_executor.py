# -*- coding: utf-8 -*-
"""TAP 执行器测试: plan 到协议参数的翻译、OR 分支合并去重、排序语义、溢出探测。

职责: 守住 TAP 执行器三个阶段的语义回归。翻译阶段: ADQL plan 必须翻成 BEST
  原生协议参数, 且角度单位从度换算成角秒 (弄错就是永远空锥区)。合并阶段: OR 的
  多分支结果要合并并按 source_id 去重, 排序阶段: 缺测值排最后而不是当 0 混进
  队首。最后是 MAXREC 溢出探测 —— 靠"多取一行"探针一次请求同时拿数据与溢出位。
所属层次: test/unit 层, 对应被测模块 src/tap/executor.py 的 TapExecutor 及其
  失败出口 TapExecutionError, 输入侧是被测的 ADQL 子集解析器 src/tap/adql.py 的
  parse_adql; 后端为 _FakeBest 替身, 整条链路不触网。
对外接口: _cone_plan 造锥形 plan (top=None 时去掉 TOP 子句, 供溢出探测用例);
  _FakeBest 录下每次 query 收到的协议 kwargs 并按脚本吐页; 四个测试类分别覆盖
  plan 翻译 (TestPlanTranslation)、合并去重与排序投影 (TestMergeAndOrder)、
  溢出探测 (TestOverflow) 以及后端故障的错误包装。
依赖与数据流: 数据全部来自内联的替身页脚本与 ADQL 字符串, 无夹具、无临时目录、
  无落盘; 断言一律从 best.calls 回查"执行器到底给协议层发了什么", 而不是断言
  返回值 —— 后者只能证明有结果, 证不了参数翻译对不对。
关键契约与不变量: 离线回放, 后端必须永远是替身; 单位换算是硬契约 (ADQL 的
  CIRCLE 半径单位是度, 协议字段要的是角秒); 底层后端抛的原始异常必须包成
  TapExecutionError 且原消息不丢, 因为网关层只认这一种, 裸 RuntimeError 会
  逃逸成 500 而不是带 QUERY_STATUS=ERROR 的 VOTable; MAXREC=0 是合法的
  "只要元数据" 请求, 后端一次都不许被调用。
陷阱与边界: 断言放在 calls 上是因为执行器最贵的 bug 正是"发对了请求、发错了
  参数" —— 结果照样能回来, 只有回查实参才看得见; 探针行用 max_rows+1 而不是
  再发一次 count 请求, 后者会把站点负载翻倍, 在限流站点上直接换来 429; 缺测
  星等用空串而非 None 来表达, 这是替身刻意贴合真实响应里字段存在但为空的形态。
"""
from __future__ import annotations

# 第三方: pytest 承载断言与负路径 raises (全用替身后端, 不打真实站点)
import pytest

# 本地: ADQL 子集解析器 —— 执行器的输入就是 parse_adql 产出的结构化 plan
from src.tap.adql import parse_adql

# 本地: TAP 执行器及其失败出口 (底层异常统一包装成 TapExecutionError)
from src.tap.executor import TapExecutionError, TapExecutor


class _FakeBest:
    """替身后端: 记录每次 query() 收到的协议 kwargs, 并按顺序吐出脚本化分页。"""

    def __init__(self, pages: list[list[dict]]) -> None:
        """装入分页脚本 pages; calls 列表留空, 由 query() 逐次追加协议 kwargs。"""
        self.pages = pages  # 每次调用消费一页; 耗尽后回空列表 (模拟分页结束)
        self.calls: list[dict] = []  # 断言翻译结果用: 执行器到底发了什么参数

    def query(self, **kwargs):
        """录下本次协议 kwargs, 再按脚本顺序返回一页; 页耗尽即回空列表。"""
        self.calls.append(kwargs)  # 先记账, 后吐数据, 顺序反了断不到参数
        return self.pages.pop(0) if self.pages else []  # 一次调用一页, 不做自动续页


def _cone_plan(top: int | None = None):
    """构造一个锥形查询 plan; top=None 时去掉 TOP 子句 (用于溢出探测用例)。"""
    query = (                                                                        # 子句单独一条: 后面按 top 决定要不要删掉 TOP, 其余几何不动
        "SELECT TOP 5 ra, ps1_rpsf FROM best.ps1 "
        "WHERE CONTAINS(POINT('ICRS', ps1_ra, ps1_dec), CIRCLE('ICRS', 180.0, 30.0, 0.1)) = 1"
    )
    if top is None:                                                                   # top 为空即代表"不带 TOP", 溢出探测用例靠它撤掉服务端限流
        query = query.replace("TOP 5 ", "")  # 删子句而非删词, 免得 "SELECTra" 这种坏串
    return parse_adql(query)  # 造 plan 的唯一入口, 各用例共用同一条几何


class TestPlanTranslation:
    """执行器把 plan 翻译成 BEST 原生协议参数 (catalog/ra/dec/radius_arcsec/constraints)。"""

    def test_cone_becomes_native_position_kwargs(self):
        """锥形条件要翻成原生位置参数, 半径从度换算成角秒 (0.1 deg = 360 arcsec)。

        回归锚点: 半径必须从度换算成角秒 — 单位混用会让 0.1 度被当成 0.1 角秒
        下发, 结果永远是空锥区。
        """
        best = _FakeBest([[{"ps1_ra": "180.0", "ps1_rpsf": "15.0"}]])  # 单页单行, 只验翻译不看分页
        executor = TapExecutor(best)  # 执行器只认协议层 kwargs, 不认 plan 里的度
        rows = executor.execute(_cone_plan())  # 喂带 TOP 的锥形 plan
        kwargs = best.calls[0]  # 回查实参, 比断言返回值更能证翻译对不对
        assert kwargs["catalog"] == "ps1"  # best.ps1 -> catalog
        assert kwargs["ra"] == 180.0  # 中心经度原样下发
        assert kwargs["dec"] == 30.0  # 中心纬度原样下发
        assert kwargs["radius_arcsec"] == pytest.approx(360.0)  # 度 -> 角秒换算
        assert rows == [{"ps1_ra": "180.0", "ps1_rpsf": "15.0"}]  # 行原样透传, 不做归一化

    def test_constraints_translate_to_protocol_dicts(self):
        """BETWEEN 要翻成 {"name","op","min","max"} 协议字典 (协议层的约束契约)。"""
        best = _FakeBest([[]])  # 空页: 只验翻译, 不给数据
        executor = TapExecutor(best)                                                      # 约束用例也要装执行器: 翻译发生在取数之前, 空页不参与断言
        executor.execute(parse_adql("SELECT ra FROM best.ps1 WHERE ps1_rpsf BETWEEN 15 AND 16"))
        assert best.calls[0]["constraints"] == [  # 协议层约束契约: name/op/min/max 四键
            {"name": "ps1_rpsf", "op": "between", "min": 15, "max": 16}
        ]

    def test_backend_failure_raises_tap_execution_error(self):
        """底层后端抛的原始异常必须包成 TapExecutionError, 且原消息不丢。

        回归锚点: 网关层只认 TapExecutionError; 裸 RuntimeError 会逃逸成 500 而非
         带 QUERY_STATUS=ERROR 的 VOTable。
        """

        # 替身后端: 模拟站点级故障 (每次 query 都抛)
        class _Boom:
            """本地负路径替身: 不接任何协议层, 只负责把故障原样抛给执行器。"""

            def query(self, **_kwargs):
                """无条件抛 RuntimeError, 用来验证底层异常被包成 TapExecutionError。"""
                raise RuntimeError("site down")  # 裸异常: 网关层不认, 必须被执行器包一层

        with pytest.raises(TapExecutionError, match="site down"):  # match 证原消息没丢
            TapExecutor(_Boom()).execute(_cone_plan())  # 故障发生在取数阶段


class TestMergeAndOrder:
    """多分支合并、去重、排序与列投影的执行期语义。"""

    def test_or_branches_merge_and_dedupe(self):
        """OR 的两个分支分别取数后合并, 同一 source_id 只保留一条。

        回归锚点: 不去重会让跨分支重复源在结果里出现两次, 统计口径随即翻倍。
        """
        best = _FakeBest([                                                                # 两页分别喂两个 OR 分支: 合并去重的输入就是这两页的并集
            [{"ps1_source_id": "A", "ps1_ra": "1"}],  # 第 1 分支只有 A
            [{"ps1_source_id": "A", "ps1_ra": "1"}, {"ps1_source_id": "B", "ps1_ra": "2"}],
        ])  # 第 2 分支 A 重复 + 新增 B
        plan = parse_adql("SELECT ra, ps1_source_id FROM best.ps1 WHERE ps1_rpsf < 16 OR ps1_rpsf > 18")
        rows = TapExecutor(best).execute(plan)  # 两页分别喂给两个分支
        assert [r["ps1_source_id"] for r in rows] == ["A", "B"]  # 重复的 A 只留一条

    def test_order_by_puts_missing_values_last(self):
        """星等为空串 (缺测) 的行在升序里排最后, 不当成 0 混进队首。"""
        best = _FakeBest([[                                                              # 三行里掺一条空串缺测: 排序断言要能区分"缺测"与"星等最小"
            {"ps1_source_id": "A", "ps1_rpsf": "16.0"},
            {"ps1_source_id": "B", "ps1_rpsf": ""},
            {"ps1_source_id": "C", "ps1_rpsf": "15.0"},
        ]])
        plan = parse_adql("SELECT ps1_source_id, ps1_rpsf FROM best.ps1 ORDER BY ps1_rpsf ASC")
        rows = TapExecutor(best).execute(plan)  # 升序: 空串缺测必须沉底
        assert [r["ps1_source_id"] for r in rows] == ["C", "A", "B"]  # 缺测排最后, 不混进队首

    def test_order_by_descending(self):
        """DESC 排序要真正反转, 而非沿用升序键名。"""
        best = _FakeBest([[                                                               # 两行同页即可: DESC 用例只验方向, 不掺分页与缺测变量
            {"ps1_source_id": "A", "ps1_rpsf": "16.0"},
            {"ps1_source_id": "C", "ps1_rpsf": "15.0"},
        ]])
        plan = parse_adql("SELECT ps1_source_id, ps1_rpsf FROM best.ps1 ORDER BY ps1_rpsf DESC")
        rows = TapExecutor(best).execute(plan)  # 降序: 键名相同, 只有方向该变
        assert [r["ps1_source_id"] for r in rows] == ["A", "C"]  # 真反转, 不是沿用升序

    def test_column_projection(self):
        """投影只保留 SELECT 列出的列, 不透传协议层的全列结果。"""
        best = _FakeBest([[{"ps1_ra": "1", "ps1_rpsf": "2", "ps1_dec": "3"}]])  # 后端回全列
        plan = parse_adql("SELECT ra FROM best.ps1")  # 投影只点了一个列
        rows = TapExecutor(best).execute(plan)  # 投影在执行器这侧做
        assert rows == [{"ps1_ra": "1"}]  # 协议层的其余列不许透传上来


class TestOverflow:
    """MAXREC 溢出探测: 多取一行做探针、TOP 已限流时不探测、0/负值语义。"""

    def test_overflow_probes_one_extra_row(self):
        """溢出判断靠"多取一行"探针: max_rows=3 时给后端下发 4, 回 4 行即判溢出。

        回归锚点: 用 count 再取一次会双倍请求; 探针行方案一次请求同时拿数据与溢出位。
        """
        best = _FakeBest([[{"ps1_source_id": str(i)} for i in range(4)]])  # 故意给满 4 行
        plan = parse_adql("SELECT ra FROM best.ps1")  # 无 TOP, 限流权在 max_rows
        rows, overflow = TapExecutor(best).execute_with_overflow(plan, max_rows=3)   # max_rows=3 配四行回包: 探针行必须真的多要一行才判得出溢出
        assert overflow is True  # 回满探针数 = 还有第 4 行
        assert len(rows) == 3  # 多取的那行只当探针, 不进结果
        assert best.calls[0]["max_rows"] == 4  # limit + 1 探针行

    def test_no_overflow_when_top_already_limits(self):
        """TOP 已经限流时不再加探针行, 直接把 TOP 值当 max_rows 下发。"""
        best = _FakeBest([[{"ps1_source_id": str(i)} for i in range(2)]])  # 只回 2 行
        plan = parse_adql("SELECT TOP 2 ra FROM best.ps1")  # TOP 已经把结果卡死在 2
        rows, overflow = TapExecutor(best).execute_with_overflow(plan, max_rows=5)   # TOP 已经限流时 max_rows 更大也不加探针: 多要的行会白跑
        assert overflow is False  # 站点侧本来也回不出第 3 行
        assert len(rows) == 2  # 结果条数由 TOP 决定
        assert best.calls[0]["max_rows"] == 2  # 无需探针

    def test_maxrec_zero_is_metadata_only(self):
        """MAXREC=0 是合法的"只要元数据"请求: 后端一次都不许被调用。"""
        best = _FakeBest([[]])  # 脚本备着, 用来证明它压根不会被消费
        plan = parse_adql("SELECT ra FROM best.ps1")
        rows, overflow = TapExecutor(best).execute_with_overflow(plan, max_rows=0)             # 0 是合法的元数据请求, 溢出位仍要给但数据可为空
        assert rows == [] and overflow is True  # 无行可取, 溢出位仍要给
        assert best.calls == []  # 后端从未被调用

    def test_negative_maxrec_rejected(self):
        """负的 max_rows 是调用方 bug, 必须本地抛 ValueError 而不是发给服务端。"""
        with pytest.raises(ValueError):  # 本地失败: 发出去等于让站点替我们报错
            TapExecutor(_FakeBest([])).execute_with_overflow(_cone_plan(), max_rows=-1)  # 负值属调用方 bug: 本地抛错好过让服务端回一个含义模糊的错
