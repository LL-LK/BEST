# -*- coding: utf-8 -*-
"""列约束操作符白名单的 fail-closed 回归 (P1-04 / G1-04)。

职责: 钉住 ``src.protocol.ALLOWED_OPERATIONS`` 这道闸的两个方向 ——
  1. **未知操作符必须抛 ValueError** (而不是原样下发)。2026-10-05 实站证据:
     拼错的 ``greatr`` (ps1 rpsf, max=16) 被站点**收下并返回空表**, 不是被忽略
     —— 静默产出 0 行会被读成"这片天区没有源", 而调用方以为自己筛过 (铁律 5)。
  2. **实测可用的操作符一个都不能被误杀**。这是本文件的主要防线: 白名单是
     按实站行数逐项取证后手工枚举的, 收紧它 (漏一个) 的后果是把合法查询打死,
     而这类回归没有任何功能测试会发现。

覆盖: 协议层 ``build_query_form`` 的操作符校验支 + 构建器 ``BestQuery.where``
的对外表现 (两者同一权威层, 这里从两端各钉一次, 防止哪一端绕过白名单)。
依赖: 纯内存调用, 不发任何网络请求, 桩数据只来自实测记录的行数表。
历史沿革: 本仓此前**根本没有**白名单 (where() 的 docstring 指向一个不存在的
东西), 复现脚本 temp/h3/probe_operation2.py + confirm_operation.py。
"""
from __future__ import annotations

# 第三方: pytest (raises / parametrize 是本文件的主要工具)
import pytest

# 本地: 协议层权威表单渲染 + 操作符白名单常量; 流畅构建器 (对外调用面)
from src.protocol import ALLOWED_OPERATIONS, build_query_form
from src.query_builder import BestQuery

# 实测可用的操作符 → 2026-10-05 实站 (ps1 @180,30 300", 同锥无约束 total=5109)
# 的服务端行数证据。这张表是白名单的**唯一**依据: 只登记"有行数作证"的取值。
# between 用 15..16 (得 4 行), 其余单值形态各自一行; grater 与 greater 只差
# 拼写却是 0 行 (表头 CSV 426 B), 故**不在**表内。
LIVE_PROVEN_OPERATIONS = {
    "between": 4,          # min=15, max=16 → 4 行: 区间型成立
    "greaterequal": 1559,  # min=15 → 1559 行: 方向型成立
    "less": 3554,          # max=16 → 3554 行
    "lessequal": 3554,     # max=16 → 3554 行 (与 less 同: 站上没有可区分的严格小于)
    "equal": 0,            # value=15.5 → 0 行: 站上**没有**恰好 15.5 的 PSF 值 (登记为"可提交", 不作为有效性证据)
    "in": None,            # textarea 形态, 本轮未取行数证据 (提交即被站点接受, 见下)
    "contains": None,      # 同上
    "notequal": None,      # 同上 (站点方言: 值写字符串 "null" 表空值, 见 download_region)
}
# 实测**不**成立的操作符: 站点收下后返空表。留着当回归钉子, 防止有人凭旧文档
# 把它们"补回"白名单。
LIVE_DISPROVEN_OPERATIONS = ("grater", "greater", "greatr", "lesss", "gt", "neq")


def _form(operation: str, **kwargs) -> dict:
    """按给定的操作符渲染一张 ps1 表单 (走协议层唯一入口)。"""
    constraint = {"name": "ps1_rpsf", "constraint": operation, **kwargs}
    return build_query_form("ps1", [constraint])


class TestUnknownOperationsAreRejected:
    """未知操作符必须显式抛错 (P1-04 的主命题)。"""

    @pytest.mark.parametrize("operation", LIVE_DISPROVEN_OPERATIONS)
    def test_typo_operation_raises_instead_of_being_forwarded(self, operation: str):
        """拼错/方言不成立的操作符一律 ValueError, 绝不原样进表单。"""
        with pytest.raises(ValueError) as excinfo:
            _form(operation, max=16)  # 值槽给全, 确保是"操作符"这一项触发拒绝而不是缺值
        message = str(excinfo.value)
        assert operation in message, message  # 报错要指名道姓: 只说"不支持"等于让人自己猜

    def test_greater_is_not_silently_rewritten_into_grater(self):
        """``greater`` 不再被映射成 ``grater`` —— 那条映射把可读操作变成静默空结果。

        旧实现: ``greater`` → ``grater`` (据旧文档"站点拼写错误"), 实测 ``grater``
        恒返 0 行, 于是这条"便利映射"实际是一条静默丢结果的路径。
        """
        with pytest.raises(ValueError, match="grater"):
            _form("greater", min=15)  # 方向型给 min: 旧实现会把它改写成 grater 后照发

    def test_rejection_happens_before_any_io_shaped_side_effect(self):
        """拒绝发生在**列名解析之前**, 因此错误信息里带的是调用方原样的列名。"""
        with pytest.raises(ValueError) as excinfo:
            build_query_form("ps1", [{"name": "rpsf", "constraint": "greatr", "value": "16"}])
        assert "'rpsf'" in str(excinfo.value)  # 裸列名原样回显: 复核者能对上自己写了什么


class TestProvenOperationsStillPass:
    """实测可用的操作符一个都不能被误杀 (反向自证: 收紧白名单必红)。"""

    @pytest.mark.parametrize("operation", sorted(LIVE_PROVEN_OPERATIONS))
    def test_every_proven_operation_is_still_allowed(self, operation: str):
        """白名单必须**恰好**覆盖全部实测可用操作符。

        这是"反向自证"那一半: 任何从 :data:`ALLOWED_OPERATIONS` 里删掉一项的改动
        (哪怕只删一个方言) 都会让本用例红, 而功能测试察觉不到这种收紧。
        """
        assert operation in ALLOWED_OPERATIONS, (
            f"{operation!r} 有实站行数证据 ({LIVE_PROVEN_OPERATIONS[operation]} 行), "
            f"不得从白名单里删掉; 当前白名单={sorted(ALLOWED_OPERATIONS)}"
        )

    @pytest.mark.parametrize("operation", sorted(LIVE_PROVEN_OPERATIONS))
    def test_proven_operation_renders_a_form(self, operation: str):
        """白名单内操作符都能真正渲染出 ``.operation`` 键 (值原样, 不被改写)。"""
        kwargs = {"min": 15, "max": 16} if operation == "between" else {"value": "15.5"}
        form = _form(operation, **kwargs)
        assert form["ps1.rpsf.operation"] == operation  # 原样下发: 白名单不夹带任何"友好改写"

    def test_whitelist_has_no_unproven_member(self):
        """白名单不得比实测证据更宽: 多出来的每一项都是"没人验证过它在站点上有效"。"""
        assert set(ALLOWED_OPERATIONS) == set(LIVE_PROVEN_OPERATIONS), (
            f"白名单与实站证据不一致: 多出={sorted(set(ALLOWED_OPERATIONS) - set(LIVE_PROVEN_OPERATIONS))}, "
            f"缺少={sorted(set(LIVE_PROVEN_OPERATIONS) - set(ALLOWED_OPERATIONS))}"
        )

    def test_between_still_needs_both_ends(self):
        """新增的校验不得吞掉区间型原有的两端必填校验 (少一端仍要抛)。"""
        with pytest.raises(ValueError, match="needs min and max"):
            _form("between", min=15)


class TestBuilderSurfaceUsesTheSameWhitelist:
    """``BestQuery.where`` 的 docstring 曾指向一个不存在的白名单; 现在两端同一权威层。"""

    def test_builder_rejects_typo_through_to_form(self):
        """构建器侧同样在 ``to_form()`` 抛错 —— 不是在 ``where()`` 提前抛。"""
        query = BestQuery().catalog("ps1").where("rpsf", "greatr", min=15, max=16)  # 构造期不校验 (与列名/波段同一口径)
        with pytest.raises(ValueError, match="unknown column operation"):
            query.to_form()

    def test_builder_docstring_points_at_a_real_symbol(self):
        """docstring 点名的 ``ALLOWED_OPERATIONS`` 必须真实存在 (G1-04 的原病灶)。"""
        doc = BestQuery.where.__doc__ or ""
        assert "ALLOWED_OPERATIONS" in doc, doc
        assert "grater" in doc, "方言那条反直觉的实测结论必须留在 docstring 里, 否则下一个人会照旧文档改回去"
        assert ALLOWED_OPERATIONS  # 符号真实存在且非空: 不是又一个指向不存在东西的名字
