"""astro-best scripts.best_multiband_export 输出格式白名单回归 (A2)。

钉住两件事: output_format 白名单化 ("txt" 等非白名单值显式抛 ValueError
并指名合法值, 不再静默按 json 写); 合法值 csv/json 落盘时扩展名与内容
类型一致。全部离线: BestClient 在测试内被替身换掉, 且选用的 source_id
不触发 POS_ 坐标检索路径, 不发任何网络请求。
"""
from __future__ import annotations

import json  # 标准库: 校验 json 导出的内容可被解析
from pathlib import Path  # 标准库: 读回落盘文件

import pytest  # 第三方: raises 断言负路径; monkeypatch 换模块级依赖

from src.scripts import best_multiband_export as export_mod  # 本地: 被测导出模块


class _StubClient:
    """BestClient 替身: 导出路径只需要一个能传给 from_client 的对象 (零网络)。"""


class _StubMultiBandPhotometry:
    """BestMultiBandPhotometry 替身: from_client 回一个**带 1 个测光点**的容器。

    隔离理由: 本组用例守的是 output_format 白名单与扩展名/内容一致性 (A2),
    不是 source_id 解析 — P2-12 起未识别 ID 在 from_client 显式抛错, 拿
    "TESTSRC" 走真实路径会撞 ValueError, 把格式断言变成 ID 断言。

    必须带点而不能回 0 点容器 (G1-03): 0 点容器缺省拒绝落盘 (仅表头文件与
    写坏的空文件不可区分), 那是 ``_guard_nonempty`` 的职责, 不该由这组
    格式用例顺带覆盖。
    """

    @classmethod
    def from_client(cls, client, source_id, band=None, catalog="ps1"):
        """回一个单点容器 (to_csv/to_json 照常工作, 零网络)。"""
        from src.models import BestSource  # 真实数据模型: 落盘走生产码, 行结构不造
        from src.multiband_photometry import BestMultiBandPhotometry  # 真实光变对象, 落盘逻辑仍走生产码

        point = BestSource(source_id=source_id, ra=10.0, dec=20.0,      # 一个最小测光点: 让容器非空, 导出才是合法路径
                           catalog=catalog, magnitudes={"r": 15.0})     # 单波段即可: 本组只断扩展名与内容类型, 不断波段数
        return BestMultiBandPhotometry(source_id=source_id, points=[point], band=band)  # 不接 client, 故零网络


class TestOutputFormatWhitelist:
    """A2 回归: output_format 白名单 — 扩展名与内容类型必须一致。"""

    def test_unknown_format_raises_value_error(self, tmp_path, monkeypatch):
        """output_format="txt" 必须显式抛 ValueError 且消息指名合法值。

        验证的行为: 传 "txt" 抛 ValueError, 消息同时含 csv/json, 输出目录
        不落任何文件 (fail-fast: 校验先于建 client/建目录/落盘)。
        为什么重要: 只对 "csv" 走 to_csv, 其余值一律按 json 写却把该值当扩展名 — "txt" 会落一个 .txt 里装 JSON 的文件, 下游按扩展名分派
        解析器时静默解析失败 (数据坏了但不报错, 比显式失败危险)。
        回归背景: docs/architecture/file-size-budget.md §6 A2。
        """
        monkeypatch.setattr(export_mod, "BestClient", _StubClient)  # 换掉会发网络的真实 client
        monkeypatch.setattr(export_mod, "BestMultiBandPhotometry", _StubMultiBandPhotometry)  # 换掉会解 ID 的真实类
        with pytest.raises(ValueError, match="csv") as excinfo:  # match 钉住"白名单含 csv"这半句
            export_mod.export_multiband_photometry(  # "txt" 不在白名单, 必须在落盘前就失败
                "TESTSRC", output_format="txt", output_dir=str(tmp_path)
            )
        assert "json" in str(excinfo.value)  # 消息须同时指名另一个合法值, 便于调用方自查
        assert list(tmp_path.iterdir()) == []  # fail-fast: 校验先于建目录与落盘

    def test_csv_export_extension_matches_content(self, tmp_path, monkeypatch):
        """合法值 csv: 落 .csv 且内容是可解析的 CSV (首行是多波段测光导出表头)。

        验证的行为: 返回路径以 mbp_TESTSRC_all.csv 结尾, 文件首行是 CSV 表头
        (source_id 开头) 而不是 JSON。为什么重要: 白名单放行值必须端到端落
        对内容, 否则"允许 csv"只是名义上的。
        """
        monkeypatch.setattr(export_mod, "BestClient", _StubClient)  # 零网络前提: client 换成空壳
        monkeypatch.setattr(export_mod, "BestMultiBandPhotometry", _StubMultiBandPhotometry)  # 光变对象也走替身
        out = export_mod.export_multiband_photometry(  # 合法值 csv: 白名单放行, 走 to_csv 分支
            "TESTSRC", output_format="csv", output_dir=str(tmp_path)
        )
        assert out.endswith("mbp_TESTSRC_all.csv")  # 扩展名必须与 output_format 严格一致
        text = Path(out).read_text(encoding="utf-8-sig")  # utf-8-sig: 让 Excel 直开也不乱码
        assert text.splitlines()[0].startswith("source_id")  # 首行是 CSV 表头, 不是 JSON 体

    def test_json_export_extension_matches_content(self, tmp_path, monkeypatch):
        """合法值 json: 落 .json 且内容是可解析的 JSON 对象。

        验证的行为: 返回路径以 mbp_TESTSRC_all.json 结尾, json.loads 读回
        dict 且含 source_id 键。为什么重要: 与 csv 用例合起来证明白名单内
        每个值的扩展名与内容类型严格一致。
        """
        monkeypatch.setattr(export_mod, "BestClient", _StubClient)  # 与 csv 用例同替身, 变量只有格式
        monkeypatch.setattr(export_mod, "BestMultiBandPhotometry", _StubMultiBandPhotometry)  # 保持 ID 不被解析
        out = export_mod.export_multiband_photometry(  # 合法值 json: 白名单的另一条放行分支
            "TESTSRC", output_format="json", output_dir=str(tmp_path)
        )
        assert out.endswith("mbp_TESTSRC_all.json")  # 扩展名跟着 format 变, 不再按 json 硬写
        payload = json.loads(Path(out).read_text(encoding="utf-8"))  # 读回必须是合法 JSON 对象
        assert payload["source_id"] == "TESTSRC"  # 键名与值一起钉住, 防退化成裸数组
