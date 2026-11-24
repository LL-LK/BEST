"""空结果落盘闸的回归 (A3-03)。

守的不变量: "0 行" 只有两种合法形态, 且两者都必须**在字节层与 sidecar 里**
与"产物损坏"可区分 ——
  (1) 真空区 (0 行且 ``total_count == 0``): 产物照落, 但必须带表头 (不是只含
      BOM 的 3 字节空壳), 且 sidecar 显式记 ``row_status="empty"``;
  (2) 异常 (0 行但 ``total_count > 0``): 显式抛错, 且**一个字节都不落** ——
      服务端说有行却一行没拿到, 落个空文件只会让人读成"这片天区没源"。

修复前四条落盘路径 (region / sqlid / 约束 / 精准) 只判 ``result.success``:
``delimited_text`` 对空 rows 返回空串 → CSV 路径落出 3 字节文件, sidecar 只有
``completeness=0.0``, 全程无异常、终态 done。本文件用桩客户端走真实入口,
不碰网络。
"""
from __future__ import annotations

# 标准库: json 读 sidecar / pathlib 产物路径断言
import json
from pathlib import Path

# 标准库: patch 替换客户端查询面, 离线造出"成功但 0 行"的结果信封
from unittest.mock import patch  # 换掉网络面: 两条用例都在桩上完成

# 测试框架: raises 断言异常冒泡 (0 行 + 有总数必须抛, 不许静默落盘)
import pytest  # fail-closed 是本文件的一半断言

# 本地: 生产客户端 (rate_limit=0 关掉礼貌限流; 本文件不打桩的分支一个也不走)
from src.client import BestClient

# 本地: 被测单元 — 下载器 (四条落盘路径的最终出口 _save_result 在此)
from src.downloader import BestDownloader

# 本地: 数据模型 — 查询结果载体 (success/total_count/sources 三元组是闸的输入)
from src.models import BestQueryResult, BestSource


def _dl(tmp_path) -> BestDownloader:
    """造一个锚定临时区的下载器 (输出目录与断点目录都不许落 CWD 相对默认)。"""
    return BestDownloader(  # 限流归零: 桩在查询面, 但仍不该让用例等礼貌 sleep
        BestClient(rate_limit=0),
        output_dir=str(tmp_path / "data"),
        checkpoint_dir=str(tmp_path / "ckpt"),
    )


def _sidecar_of(saved: str) -> dict:
    """读回落盘产物的 provenance sidecar (复核契约的载体)。"""
    sidecar = Path(saved).with_suffix(Path(saved).suffix + ".provenance.json")  # 与写出一侧的命名约定一致
    assert sidecar.is_file(), "空结果也必须有 sidecar: 否则调用方无从区分真空区与损坏文件"
    return json.loads(sidecar.read_text(encoding="utf-8"))


def test_empty_region_result_is_flagged_with_header(tmp_path):
    """真空区 (0 行 + total_count=0): 落表头 + sidecar 记 row_status=empty, 不抛错。

    守的回归: 修复前这里落出 ``b'\\xef\\xbb\\xbf'`` (只含 BOM 的 3 字节文件),
    sidecar 只有 ``completeness=0.0``, 调用方既没法区分"没源"与"写坏了", 也没
    办法让下游按表头建表。真空区本身不是失败, 所以这里断言的是"照落但显式
    记状态", 而不是抛错。
    """
    dl = _dl(tmp_path)
    empty = BestQueryResult(success=True, sources=[], total_count=0)  # 成功但零源: 真空区的构造
    with patch.object(dl.client, "cone_search", return_value=empty):  # 打桩查询面: region 非断点路径的出口
        saved = dl.download_region(ra_center=10.0, dec_center=20.0, radius_arcsec=60.0, catalog="ps1")

    raw = Path(saved).read_bytes()  # 按字节看: 3 字节空壳正是修复前的形态
    assert len(raw) > 3, "空结果不能只落 BOM: 字节层必须能与'写坏的空文件'区分"
    first_line = raw.decode("utf-8-sig").splitlines()[0]  # 首行必须是表头 (utf-8-sig 吃掉 BOM)
    assert "source_id" in first_line, "0 行也要落表头: 列名取行投影的固定列 (serialization.BASE_COLUMNS)"

    data = _sidecar_of(saved)["data"]  # 复核契约: 0 行必须在这里显形
    assert data["row_status"] == "empty", "真空区必须显式记 row_status=empty, 不能只靠 completeness 暗示"
    assert data["total_count"] == 0 and data["returned_count"] == 0  # 计数照实报: 不拿 0 冒充"未报告"


def test_zero_rows_with_nonzero_total_raises_and_writes_nothing(tmp_path):
    """0 行但 total_count=750: 必须抛错, 且输出目录一个字节都不落。

    守的回归 (铁律 5 禁 fail-open): 这是丢数据的形态, 不是"这片天区没源"。
    修复前四条路径只判 ``success``, 于是把 3 字节空壳当成功交付、终态 done ——
    调用方既看不到异常, 事后也无从对账究竟少了几行。
    """
    dl = _dl(tmp_path)
    lost = BestQueryResult(success=True, sources=[], total_count=750)  # 服务端说有 750 行, 实际 0 行
    with patch.object(dl.client, "cone_search", return_value=lost):  # 打桩查询面: 造出"成功但丢行"的信封
        with pytest.raises(RuntimeError, match="total_count=750"):  # 错误文案要带服务端总数, 便于对账
            dl.download_region(ra_center=10.0, dec_center=20.0, radius_arcsec=60.0, catalog="ps1")

    produced = list((tmp_path / "data").iterdir())  # 输出目录必须干净: 空壳也是证据, 落了会被人当产物
    assert produced == [], "异常 0 行不得留下任何产物/半成品: 抛错即代表没拿到数据"


def test_sqlid_path_shares_the_same_gate(tmp_path):
    """sqlid 路径同样受闸约束: 证明闸装在共用出口, 而不是只补了某一条路径。

    守的回归: 闸若只挂在 region 分支上, sqlid/约束/精准三条路径仍会把空壳当
    成功交付 (修复前正是如此: 只有精准下载自带回核, 另外三条零校验)。
    """
    dl = _dl(tmp_path)
    lost = BestQueryResult(success=True, sources=[], total_count=42)  # 同一种丢行形态, 换一条路径复现
    with patch.object(dl.client, "_fetch_sqlid_data", return_value=lost):  # 打桩 phase-2 取数引擎
        with pytest.raises(RuntimeError, match="total_count=42"):  # 同一条闸, 同样的显式失败
            dl.download_sqlid("s5151", output_file="sqlid_empty.csv")


def test_export_results_empty_csv_still_writes_header(tmp_path):
    """合并产物出口: 空数据也写表头 (合并路径此前刻意不建 writer, 落 3 字节壳)。

    守的回归: ``export_results`` 是导航组合并的落盘点, 空数据时"不建 writer"
    看着合理, 但产物在字节层与写坏的文件不可区分。下游 glob 到合并产物后无法
    判断该重跑还是该直接用。
    """
    dl = _dl(tmp_path)
    saved = dl.export_results([], "empty_merge.csv")  # 空数据: 没有任何行可并列
    raw = Path(saved).read_bytes()  # 按字节看: 只含 BOM 即为未修复形态
    assert len(raw) > 3, "空合并产物不能只落 BOM"
    assert "source_id" in raw.decode("utf-8-sig"), "空数据也要落可识别表头"


def test_nonempty_result_still_records_ok_status(tmp_path):
    """有行时 row_status=ok: 闸不能把正常产物也标成 empty (反向误报同样是错)。

    守的回归: 闸是分流不是拦截 —— 一旦判定条件写反 (例如拿 total_count 当
    行数), 所有正常下载的 sidecar 都会记成 empty, 复核人反而拿不到真相。
    """
    dl = _dl(tmp_path)
    one = BestSource(source_id="SRC_OK_1", ra=180.0, dec=30.0, magnitudes={"r": 18.2})  # 单源: 最小的正常结果
    ok = BestQueryResult(success=True, sources=[one], total_count=1)  # 有行且总数一致
    with patch.object(dl.client, "cone_search", return_value=ok):  # 打桩查询面
        saved = dl.download_region(ra_center=10.0, dec_center=20.0, radius_arcsec=60.0, catalog="ps1")

    data = _sidecar_of(saved)["data"]  # 复核契约: 正常产物必须记 ok
    assert data["row_status"] == "ok", "有行时必须记 ok, 不能被闸误标成 empty"
    assert "SRC_OK_1" in Path(saved).read_text(encoding="utf-8-sig")  # 数据行确实落了盘
