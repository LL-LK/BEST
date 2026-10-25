"""输出模型的 blocking 门禁不得恒真 (H6-02)。

守的不变量: ``BestResultSet`` 的两条 blocking 门禁
(``http_status == 200`` / ``checksum_match == True``, 声明于
``manifest.yaml`` / ``agents/openai.yaml`` / ``contracts/output.contract.yaml``)
在**缺省构造**下必须判**不通过**。

缺陷形状: 此前 ``http_status`` 缺省 200、``checksum_match`` 缺省 True, 而
代码里没有任何一处真正求值这两条门禁 —— 缺省即通过的字段配上无人求值的
声明, 合起来是一条**恒真的假门禁**。失败方向还恰恰是最危险的一侧: 软 404
(HTTP 200 + 错误体) 会被读成成功。

与 ``test_gen_gates.py`` 的分工: 那份守的是**声明** (恰为 2 条、比较符与阈值
不漂移); 本份守的是**求值** (缺省不得判过、真实回填后能判过)。两份都过而
门禁恒真, 正是"声明齐备 = 门禁有效"的典型盲区。

离线: 纯模型层, 零 IO 零网络 (handoff 的 manifest 派生读仓内 manifest.yaml)。
"""
from __future__ import annotations

# 标准库: importlib 直接按路径加载模型模块 (该模块刻意不从 src.models 顶层导入,
# 以免为一个默认值测试把整条模型链拉进来)
import importlib.util  # 按文件路径加载单个模块, 不触发包级导入
from pathlib import Path  # 定位仓根以拼出模块文件路径

# 测试框架: raises 断言 fail-closed 冒泡
import pytest  # 门禁若被改成"缺省即抛"也要能断言异常类型


def _load_output_module():
    """按文件路径加载 ``src/models/output.py``。

    刻意不走 ``from src.models import BestResultSet``: 那会连带导入整个模型包,
    而本文件只验一个类的门禁默认值。直接加载被测文件本身, 依赖面最小。
    """
    module_path = Path(__file__).resolve().parents[3] / "src" / "models" / "output.py"  # test/unit/models -> 仓根
    spec = importlib.util.spec_from_file_location("h6_models_output", module_path)  # 独立模块名: 不与真实包同名, 避免写 sys.modules 时撞车
    assert spec is not None and spec.loader is not None, "被测模块必须可加载"  # 前置条件显式化: 加载不了就是环境坏了, 不该静默 skip
    module = importlib.util.module_from_spec(spec)  # 先建壳再执行: dataclass/注解求值需要模块已在册
    spec.loader.exec_module(module)  # 真实执行模块体: 拿到的就是生产类本身
    return module


_output = _load_output_module()  # 模块级加载一次: 构造模型要走真实 __init__


class TestGatesAreNotConstantlyTrue:
    """缺省构造不得通过 blocking 门禁。"""

    def test_default_http_status_is_not_200(self):
        """缺省 http_status 必须是"未知", 不是 200。"""
        result = _output.BestResultSet()  # 无参构造: 走的正是缺省分支

        assert result.http_status is None, (
            "缺省 http_status 不得是 200: 未回填真实响应时, 200 会把软 404 "
            "(HTTP 200 + 错误体) 读成成功 (P0-3)"
        )
        assert result.http_status != 200, "更直接的判据: 缺省值与 200 不可相等"

    def test_default_checksum_match_is_false(self):
        """缺省 checksum_match 必须是 False (未校验即不宣称匹配)。"""
        result = _output.BestResultSet()  # 无参构造

        assert result.checksum_match is False, "没做校验就宣称匹配, 等于用缺省值伪造门禁通过"

    def test_default_construction_fails_the_gates(self):
        """核心判据: 缺省构造求值两条 blocking 门禁, 结果必须是"不通过"。"""
        result = _output.BestResultSet()  # 无参构造: 模拟"没有任何真实回填"的实例

        assert result.gates_passed() is False, (
            "恒真的门禁等于没有门禁: 缺省实例必须判不通过 (fail-closed)"
        )

    def test_to_dict_gates_segment_is_not_a_passing_verdict(self):
        """序列化出口同样不得吐出"通过"形态的缺省值。"""
        gates = _output.BestResultSet().to_dict()["gates"]  # 只取 gates 段: 那才是门禁判定的依据

        assert gates["http_status"] != 200, "序列化出口的 http_status 缺省不得是 200"
        assert gates["checksum_match"] is False, "序列化出口的 checksum_match 缺省不得是 True"


class TestGatesCanActuallyGoBothWays:
    """门禁必须**能真能假** —— 恒假与恒真都不算数。"""

    def test_real_backfill_passes(self):
        """真实回填 (200 + 校验通过) 时门禁判过: 证明求值不是恒假。"""
        result = _output.BestResultSet(http_status=200, checksum_match=True)  # 真实回填形态

        assert result.gates_passed() is True, "真实回填后门禁必须能判过, 否则它不是门禁而是一道永远拦人的墙"

    @pytest.mark.parametrize(
        ("http_status", "checksum_match"),
        [
            (500, True),   # 服务端错 + 校验过: 状态码不过即整体不过
            (200, False),  # 状态码过 + 校验不过: 任一不过即整体不过
            (None, True),  # 状态码未回填 + 校验过: 未知即不通过
            (404, False),  # 两门皆不过
        ],
    )
    def test_each_gate_can_independently_block(self, http_status, checksum_match):
        """两条门禁各自都能拦住: 任一不满足即整体不通过。"""
        result = _output.BestResultSet(http_status=http_status, checksum_match=checksum_match)  # 逐组合构造

        assert result.gates_passed() is False, f"({http_status}, {checksum_match}) 应当判不通过"

    def test_non_200_success_status_still_blocks(self):
        """3xx/2xx 家族的非 200 值不得被当成"成功" —— 判据是恰为 200。"""
        for status in (201, 204, 301, 199):  # 这些都"看起来像成功", 但契约写死 200
            result = _output.BestResultSet(http_status=status, checksum_match=True)  # 逐个构造
            assert result.gates_passed() is False, f"http_status={status} 不该通过 == 200 的门禁"
