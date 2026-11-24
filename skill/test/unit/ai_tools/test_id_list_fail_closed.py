# -*- coding: utf-8 -*-
"""crossmatch_batch 的 id_list 兜底必须 fail-closed (G1-07 同形缺陷, H4-3)。

守的回归: 旧的 ``str(item.get("id", index))`` 只在**键缺失**时回落, 值为
``None`` 时原样返回, ``str(None)`` 于是把 Python 关键字 None 变成字面串
``"None"`` 混进 ``source_id`` 前缀 (``"None -> ps1_123"``)。真实 id 被吞,
且这个前缀与合法 id 无法区分 —— 比缺前缀更难发现的错挂。空串/纯空白同理:
拼出来的是 ``" -> ps1_123"`` 这种无主前缀。

本文件离线运行: 只桩掉 crossmatch 执行器, 零 HTTP。
"""
from __future__ import annotations

# 标准库: SimpleNamespace 作轻量结果替身 (字段以 ToolBox 实际读取的为准 ——
# P0-07 之后它还要读 success/error/error_code, 替身少一个就 AttributeError)
from types import SimpleNamespace

# 本地: 被测工具面 (id_list 的收集点) + 生产客户端 (rate_limit=0 关掉限流噪声)
from src.ai_tools import ToolBox
from src.client import BestClient


def _box_with_stub_crossmatch() -> tuple[ToolBox, list[dict]]:
    """装一个只桩掉 crossmatch 的 ToolBox; 返回 (工具面, 实收 kwargs 列表)。

    桩掉整个 ``crossmatch_batch`` 而不是逐层 HTTP: 本用例要断的只是
    **id_list 收集逻辑**, 走真实网络只会让断言依赖站点回包。
    """
    box = ToolBox(BestClient(rate_limit=0))  # 限流归零: 本用例零请求, 免得白等 2s 间隔
    seen: list[dict] = []  # 收集执行器实收的关键字参数: 断言直接读它

    def _fake_batch(ra_list, dec_list, **kwargs):
        """记录 kwargs 并回一个空结果信封 (够 _envelope 消费即可)。"""
        seen.append({"ra": list(ra_list), "dec": list(dec_list), **kwargs})
        return SimpleNamespace(
            # success 必须给: P0-07 之后 crossmatch_batch 会先判这一位, 缺它替身
            # 就 AttributeError。生产里成功的批量匹配恒为 True (BestQueryResult 的
            # 缺省是 False, 那是"未填即失败"的 fail-closed 缺省, 不是成功态)。
            success=True, error=None, error_code=None,
            sources=[], total_count=0, returned_count=0, truncated=False,
            query_params={"mode": "proximity"},
        )

    box.crossmatch = SimpleNamespace(crossmatch_batch=_fake_batch)  # 替身只实现被调的那一个入口
    return box, seen


class TestIdListFailClosed:
    """id_list 收集: 任何不可用 id 都不得变成 "None"/空标签混进查询。"""

    def test_none_id_does_not_become_the_string_none(self):
        """id 键存在但值为 None: 不得产出 "None" 字面串 (核心回归)。"""
        box, seen = _box_with_stub_crossmatch()
        box.crossmatch_batch([{"ra": 10.0, "dec": 20.0, "id": None}])  # id 显式给 None: 最常见的脏输入
        id_list = seen[0]["id_list"]
        assert id_list == ["0"], f"None 必须回退到输入下标, 实得 {id_list!r}"
        assert "None" not in id_list, f'"None" 字面串混进了 id_list: {id_list!r}'  # 钉死具体形态: 不用下标兜底也会让这条红

    def test_none_id_falls_back_to_source_id_before_the_index(self):
        """id=None 时次选 source_id: 真实标识不能被下标顶掉。"""
        box, seen = _box_with_stub_crossmatch()
        box.crossmatch_batch([{"ra": 10.0, "dec": 20.0, "id": None, "source_id": "ps1_123"}])  # id 脏但 source_id 可用
        assert seen[0]["id_list"] == ["ps1_123"], "真实 source_id 被 None 顶掉了"  # 优先级与 crossmatch 侧三级兜底同序

    def test_empty_and_blank_id_fall_back_to_the_index(self):
        """id 为空串/纯空白: 一律视作缺失, 不得产出无主标签。"""
        box, seen = _box_with_stub_crossmatch()
        box.crossmatch_batch([
            {"ra": 10.0, "dec": 20.0, "id": ""},      # 空串
            {"ra": 11.0, "dec": 21.0, "id": "   "},   # 纯空白
        ])
        id_list = seen[0]["id_list"]
        assert id_list == ["0", "1"], f"空/空白 id 未回退到下标: {id_list!r}"
        assert not any(v.strip() == "" for v in id_list), f"空标签混进了 id_list: {id_list!r}"  # 空标签会拼出 " -> src" 无主前缀

    def test_usable_ids_are_untouched(self):
        """正常 id (含数字) 原样透传: 兜底逻辑不得反过来吃掉合法标识。"""
        box, seen = _box_with_stub_crossmatch()
        box.crossmatch_batch([
            {"ra": 13.0, "dec": 23.0, "id": "S4"},   # 字符串 id
            {"ra": 14.0, "dec": 24.0, "id": 7},      # 数字 id: 统一转字符串与下标兜底同形态
            {"ra": 15.0, "dec": 25.0},                # 无 id 键: 下标兜底
        ])
        assert seen[0]["id_list"] == ["S4", "7", "2"], f"合法 id 被改写: {seen[0]['id_list']!r}"

    def test_dirty_ids_are_warned_not_silently_swapped(self, caplog):
        """脏 id 必须留痕: 换名不是无声动作 (铁律 5 不静默跳过)。"""
        box, _seen = _box_with_stub_crossmatch()
        with caplog.at_level("WARNING", logger="src.ai_tools"):
            box.crossmatch_batch([{"ra": 10.0, "dec": 20.0, "id": None}, {"ra": 11.0, "dec": 21.0}])  # 两行都脏
        assert any("no usable id" in rec.message for rec in caplog.records), "脏 id 未告警: 事后无法知道有多少行换了名"  # 可观测性锚点
