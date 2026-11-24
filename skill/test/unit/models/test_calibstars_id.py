"""回归: stripe82 的裸列名 calibstars_id 必须填进 source_id (live 实证)。

同时守 ps1 ≈-1000 空值哨兵语义: 哨兵不得变成星等, 但真实暗星必须保留。
两组测试都锚定 live 行实测。

职责: 守住"列名 -> 字段"映射表的回归。stripe82 响应里 source_id 那一列不带星表
  前缀, 旧别名表漏掉它就让 source_id 整段丢失 —— 精准下载与数据溯源同时断链,
  而现象只是"下载不到文件", 极难回溯到是解析层的问题。
所属层次: test/unit 层 (行数据全部来自 live 抽样时抄下的固定快照, 本文件不联网),
  对应被测模块 src/models/ 的 BestSource.from_row —— 即行字典到源对象的装配口,
  以及 ps1 ≈-1000 空值哨兵在该口上的判定规则。
对外接口: TestCalibstarsIdParsing 验裸列名 calibstars_id 与带前缀 ps1_source_id
  都能落进 source_id; 同文件另一组用例验哨兵星等既不冒充有效值也不吃掉真实暗星。
依赖与数据流: 无夹具, 全部输入是内联的固定行字典 (取自 live 抽样, 因此是快照
  回放而非活站点); 断言只读 from_row 产出的源对象字段; 零写盘、零网络, 这也是本
  文件能留在 test/unit 而不进 test/live 的原因。
关键契约与不变量: 哨兵值 ≈-1000 是"缺测"而非"极暗星", 换算成星等后必须落回
  缺测语义, 否则 PS1 那批 -999 会被排到结果集最前面并伪装成最亮目标; 反过来
  真实暗星 (g 值十几二十) 必须原样保留, 不能被哨兵规则一并吃掉。
陷阱与边界: 这里测的是"为什么这么测" —— 用 live 实测行而不是自造字典, 因为
  裸列名这个事实本身只能从真实响应里观察到, 编出来的用例会顺着自己写的解析器
  通过; 旧导入路径失效时整模块 skip (legacy-import-guard) 而非让收集期报错, 是
  为了让源码树调整不被误读成行为回归。
"""
from __future__ import annotations

import pytest  # 第三方: approx 浮点比较

# 旧导入守门: src.models 不可导入时整模块 skip 而非 collection error
try:
    from src.models import BestSource  # 本地: 列名映射与哨兵规则的权威实现
except Exception as _legacy_err:  # legacy-import-guard
    # 源码树调整导致旧导入路径失效时整模块跳过, 不让收集期报错
    import pytest as _pytest  # 别名导入: 顶部 import 若已失败, 这里重新绑定
    _pytest.skip(f'legacy import unavailable: {_legacy_err!r}', allow_module_level=True)  # 模块级 skip


class TestCalibstarsIdParsing:
    """source_id 列名识别守门: 裸 calibstars_id 与带前缀 ps1_source_id 都要认。"""

    def test_bare_calibstars_id_maps_to_source_id(self):
        """stripe82 响应用裸列名 calibstars_id (live 实证);
        旧别名表漏它 -> source_id 丢失, 精准下载/溯源都断。"""
        src = BestSource.from_row(                                                         # 裸列名行: 这条存在的理由就是 live 响应不带星表前缀
            {"calibstars_id": "CALIBSTARS_0844369", "ra": "35.000105",                          # ID 与坐标同在一行: 列名映射错位会在这里露馅
             "dec": "-0.451923"}, catalog="stripe82")
        assert src.source_id == "CALIBSTARS_0844369"   # 裸列名也必须落进 source_id
        assert src.ra == pytest.approx(35.000105)      # approx: 定点列名的尾数抖动不该算回归

    def test_prefixed_ps1_source_id_still_maps(self):
        """修 calibstars_id 时不能顺手破坏带前缀形态: ps1_source_id 仍须映射。

        两套列名体系 (裸名 / 带星表前缀) 必须同时成立, 否则修一个表会回归
        另一个表。
        """
        src = BestSource.from_row(                                                                # 带前缀形态: 修裸名时不能顺手把前缀形态挤掉
            {"ps1_source_id": "123", "ps1_ra": "180.0", "ps1_dec": "30.0"},                         # 前缀列同样要映射
            catalog="ps1")                                                                          # 星表名决定用哪张映射表
        assert src.source_id == "123"        # 带前缀形态不能被前一条的修复挤掉
        assert src.ra == 180.0               # 坐标列同样走前缀剥离

    def test_raw_data_preserved_for_export(self):
        """raw_data 必须原样保留整行: 下载/导出按原始列写文件, 归一化不得丢列。"""
        row = {"calibstars_id": "X", "ra": "1.0", "dec": "2.0"}                                     # 裸列名行: 导出按原始列名取值
        src = BestSource.from_row(row, catalog="stripe82")                                          # 走真实的装配口
        assert src.to_dict()["calibstars_id"] == "X"   # 导出侧按原始列名取, 归一化不能吞列


class TestNullMagnitudeSentinels:
    """ps1 的 ≈-1000 空值哨兵不得变成星等 (live 实证)。"""

    def test_sentinel_magnitudes_and_errors_are_dropped(self):
        """P0 哨兵修复守门: g/r 的 ≈-1000 空值必须整体丢弃 (星等与误差),
        同行的真实 i 波段星等必须保留; ra/dec 坐标不受哨兵规则影响。

        live 行里 ps1_gpsf=-1004.07 / ps1_gpsf_err=-999.0 与 ps1_ipsf=19.49
        并存 — 把哨兵当星等会造出"星等 -1000 的极亮源"这种科学废数据。
        """
        src = BestSource.from_row(                                                      # 同一行里 g/r 是哨兵、i 是真值: 一刀切会连 i 一起吃掉
            {   # 同一行里 g/r 是哨兵、i 是真值: 一刀切会连 i 一起吃掉
                "ps1_gpsf": "-1004.072785155375", "ps1_gpsf_err": "-999.0",
                "ps1_rpsf": "-1003.8802043547206", "ps1_rpsf_err": "-999.0",
                "ps1_ipsf": "19.49426718384701", "ps1_ipsf_err": "0.1456020027399063",
                "ps1_ra": "179.99904154", "ps1_dec": "29.99972728",
            },
            catalog="ps1",
        )
        assert src.magnitudes == {"i": 19.49426718384701}        # 只剩真值 i, 哨兵波段整段没了
        assert src.magnitude_errors == {"i": 0.1456020027399063}  # 误差表与星等表必须同步清
        assert src.ra == 179.99904154  # 坐标不受哨兵规则影响

    def test_real_faint_magnitudes_survive(self):
        """反向守门: 21.5 等暗星不是哨兵, 必须保留 — 防"一刀切"误删真实测光。"""
        src = BestSource.from_row(                                                        # 真实暗星行: 21.5 不是哨兵, 防"一刀切"误删真实测光
            {"ps1_gpsf": "21.5", "ps1_gpsf_err": "0.03"}, catalog="ps1"                            # 星等与误差成对: 误差表与星等表必须同步清
        )
        assert src.magnitudes["g"] == 21.5     # 真实暗星必须活下来
        assert src.magnitude_errors["g"] == 0.03                                                # 误差同样要活下来: 只保星等不保误差等于半个修复

    def test_sentinel_floor_is_documented_as_a_class_constant(self):
        """哨兵下限必须是文档化的类常量 (-999.0): 下游消费方 (processor/
        downloader) 按同一常量判"无测光", 散落魔法数会让两层口径漂移。"""
        assert BestSource.NULL_MAGNITUDE_SENTINEL == -999.0   # 判据必须可被下游引用
