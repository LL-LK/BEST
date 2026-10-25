# -*- coding: utf-8 -*-
"""sidecar 复核契约的两个字段的回归: ``schema`` (H3-04) 与逐成员台账 (H3-05)。

职责: 把"人能凭 sidecar 复核产物"这条要求在这两个缺口上钉死 ——
  H3-04 **schema**: 0 行产物的表头只含兜底固定列, 有行产物是完整列投影, 同一张
    星表因此有**两套表头**。``row_status`` 虽能让人猜出来, 但它讲的是"有没有
    行", 不讲"该按哪套列读"; 下游靠表头建表结构就会建错。sidecar 因此显式记
    ``schema`` ∈ {full, minimal}, 且与 ``row_status`` 同源不另立判据。
  H3-05 **members**: 合并产物里, 0 行成员的**全部声明列**不进表头 (0 行则无行
    可并集), 缺失成员的文件直接被跳过 —— 而 sidecar 此前只记 ``total_count``
    汇总, 复核人无从知道少了什么、少在哪张表上。

覆盖: ``write_provenance`` 的 data 块字段 + ``merge_region_files`` 的台账组装。
依赖: 全离线 —— 成员临时文件由 ``_save_result`` 真实写出, 客户端取
``BestClient(rate_limit=0)`` 但不发任何请求。
历史沿革: 两条都是 G6 真实站点跑批 (场景 3/4/5) 撞出来的, 离线复现脚本见
temp/g6/s3_merge.py 与 s5_s6_check.py。
"""
from __future__ import annotations

# 标准库: csv 读表头 (验"表头宽度真的随有无数据而变") / json 读 sidecar / 路径
import csv  # 只读表头就够: 本文件验的是列集合, 不是行内容
import json  # 读 sidecar: 断言的是复核人真能拿到的字段
from pathlib import Path  # 产物/sidecar 路径构造与断言

# 本地: 客户端 (rate_limit=0, 不发请求) / 落盘辅助 (schema 常量与状态字面量) /
# 下载器 (落盘与合并的权威入口) / 数据模型 (查询结果替身) / 协议层导航组清单
from src.client import BestClient
from src.download_artifacts import SCHEMA_FULL, SCHEMA_MINIMAL, STATUS_EMPTY, STATUS_OK
from src.downloader import BestDownloader
from src.models import BestQueryResult, BestSource
from src.protocol import CATALOG_GROUPS

MEMBERS = CATALOG_GROUPS["std"]  # 权威组清单: 测试不自己抄一份成员名单 (组扩成员时本文件自动跟着走)


def _band_of(member: str) -> str:
    """从成员表名里取一个**各不相同**的波段标签 (scr_galah→g / xpsp→x)。"""
    return member.rsplit("_", 1)[-1][0]  # 只求互不相同, 不求语义正确


def _result(member: str, n_rows: int, total: int | None = None) -> BestQueryResult:
    """造一个成员查询结果: ``n_rows``=0 即 0 行成员 (0 行且 total=0 是真空区形态)。

    每个成员的**列集必须不同**, 否则"某成员 0 行 → 它的列退出表头"这件事在夹具
    里根本看不出来 (别的成员会把同样的列补回来)。做法是给每个成员一个独有波段
    的星等: 落盘投影把 ``magnitudes`` 展平成 ``{band}mag``, 于是每个成员独占一列。
    """
    band = _band_of(member)  # 独有波段 → 独有列
    sources = [BestSource(source_id=f"{member.upper()}{i}", ra=180.0 + i, dec=30.0 + i, snr=40.0 + i,
                          magnitudes={band: 20.0 + i}) for i in range(n_rows)]  # 0 行即空列表
    return BestQueryResult(  # total_count 与 n_rows 不同即模拟被 max_rows 截断
        success=True,
        total_count=n_rows if total is None else total,
        returned_count=n_rows,
        truncated=(n_rows if total is None else total) > n_rows,
        sources=sources,
        query_params={"catalog": member, "ra": 180.0, "dec": 30.0, "radius_arcsec": 30.0},
    )


def _downloader(tmp_path: Path) -> BestDownloader:
    """输出目录锚在临时区的下载器 (不碰工作区, 不发请求)。"""
    return BestDownloader(BestClient(rate_limit=0), output_dir=str(tmp_path),  # 限流归零: 替身不发请求
                          checkpoint_dir=str(tmp_path / ".ck"))  # 断点也锚在临时区, 不污染工作区


def _save(dl: BestDownloader, member: str, n_rows: int, fmt: str = "csv", total: int | None = None) -> str:
    """落一份成员临时文件 (文件名沿用生产侧自动名形态, 合并器据此可读)。"""
    name = f"best_{member}_ra180.0_dec30.0_r30arcsec_r.{fmt}"  # 与 download_region 的成员命名同形
    return dl._save_result(_result(member, n_rows, total), name, fmt)  # 真实落盘: 合并链读的是文件


def _merge(dl: BestDownloader, rows_per_member: dict[str, int], fmt: str = "csv") -> Path:
    """按 ``{成员: 行数}`` 造成员文件并跑一次真实合并, 返回合并产物路径。"""
    parts = [_save(dl, member, n_rows, fmt) for member, n_rows in rows_per_member.items()]  # 与组清单同序
    return Path(dl._merge_region_files(parts, "std", 180.0, 30.0, 30.0, ["r"], fmt, None))  # 几何随行


def _sidecar(artifact: Path) -> dict:
    """读回产物的 sidecar data 块 (复核人看的就是这一块)。"""
    path = Path(str(artifact) + ".provenance.json")  # sidecar 与数据文件同名加后缀
    return json.loads(path.read_text(encoding="utf-8"))["data"]  # 载荷在 data 键下 (envelope 形态)


def _header(artifact: Path) -> list[str]:
    """读回落盘表头 (按 utf-8-sig: 表格类带 BOM)。"""
    with Path(artifact).open("r", encoding="utf-8-sig", newline="") as handle:  # newline="" 是 csv 硬要求
        return next(csv.reader(handle))  # 只取首行: 本文件验列集合


class TestSchemaField:
    """H3-04: 同一张表两种列结构, sidecar 必须说出来。"""

    def test_empty_product_declares_minimal_schema(self, tmp_path):
        """0 行产物: row_status=empty 且 schema=minimal (表头只有兜底固定列)。"""
        saved = Path(_save(_downloader(tmp_path), "ps1", 0))  # 0 行: 真空区形态
        data = _sidecar(saved)  # 复核人拿到的就是这块
        assert data["row_status"] == STATUS_EMPTY  # 既有字段: 0 行显式登记
        assert data["schema"] == SCHEMA_MINIMAL  # 新字段: 按哪套列读
        assert _header(saved) == ["source_id", "ra", "dec", "snr", "class_star", "quality_flag"]  # 兜底固定列

    def test_nonempty_product_declares_full_schema(self, tmp_path):
        """有行产物: schema=full, 表头是行投影的完整列集。"""
        saved = Path(_save(_downloader(tmp_path), "ps1", 2))  # 2 行: 有数据形态
        data = _sidecar(saved)
        assert data["row_status"] == STATUS_OK
        assert data["schema"] == SCHEMA_FULL
        assert len(_header(saved)) > 6, "有行时表头是完整投影, 不是兜底固定列"  # 实测含展平列

    def test_schema_tracks_row_status_in_both_directions(self, tmp_path):
        """``schema`` 与 ``row_status`` 必须同源, 不允许出现第二套判定语义。

        判据: 有行 ⇔ full、0 行 ⇔ minimal, 两侧都验 —— 只验一侧的话, 有人把
        schema 改成"按列数猜"这类独立判据, 另一侧仍会绿。
        """
        dl = _downloader(tmp_path)  # 同一目录两次落盘: 两种形态各一
        pairs = [(_result("ps1", 3), STATUS_OK, SCHEMA_FULL),  # 有行
                 (_result("ps1", 0), STATUS_EMPTY, SCHEMA_MINIMAL)]  # 0 行
        for index, (result, want_status, want_schema) in enumerate(pairs):
            saved = Path(dl._save_result(result, f"best_ps1_{index}.csv", "csv"))  # 文件名区分两次
            data = _sidecar(saved)
            assert (data["row_status"], data["schema"]) == (want_status, want_schema), data  # 成对断言

    def test_merged_zero_row_product_also_declares_minimal(self, tmp_path):
        """合并路径的 0 行产物同样登记 minimal (它退到 EMPTY_EXPORT_COLUMNS, 更窄)。"""
        merged = _merge(_downloader(tmp_path), {member: 0 for member in MEMBERS})  # 全员 0 行
        data = _sidecar(merged)  # 合并产物同样要能自述形态
        assert data["row_status"] == STATUS_EMPTY
        assert data["schema"] == SCHEMA_MINIMAL


class TestMemberLedger:
    """H3-05: 每个成员的实际行数与状态都必须能从 sidecar 看出来。"""

    def test_ledger_records_every_member_with_its_row_count(self, tmp_path):
        """全有行的合并: 台账逐成员记 member/rows/status, 顺序与组清单同序。"""
        merged = _merge(_downloader(tmp_path), {member: 2 for member in MEMBERS})  # 每成员 2 行
        ledger = _sidecar(merged)["query_params"]["members"]  # 复核人唯一能看"谁贡献了什么"的地方
        assert [entry["member"] for entry in ledger] == list(MEMBERS), ledger  # 顺序与组清单一致
        assert [entry["rows"] for entry in ledger] == [2] * len(MEMBERS), ledger  # 行数逐成员对得上
        assert {entry["status"] for entry in ledger} == {STATUS_OK}, ledger  # 全有行即全 ok

    def test_zero_row_member_is_named_as_the_reason_columns_are_missing(self, tmp_path):
        """0 行成员: 台账指名它, 而不是让复核人靠"表头少了几百列"去猜。

        这是本条的核心: 合并表头的列集合 = 各成员**有行**成员的列并集, 因此
        0 行成员的列一个都不出现。台账是唯一的归因出口。
        """
        galah = "scr_galah"  # std 组里被 G6 实测为 0 命中的那个成员 (场景 3: 137 个声明列整体消失)
        full = {member: 2 for member in MEMBERS}  # 全有行的基线
        assert galah in full, "组清单变了, 本用例的前提需重取"  # 防夹具与注册表脱节
        with_rows = _merge(_downloader(tmp_path / "a"), full)  # 同一片天区, 全员有行
        without_rows = _merge(_downloader(tmp_path / "b"), {**full, galah: 0})  # 只让 galah 归零

        header_with = _header(with_rows)  # 有行时的表头
        header_without = _header(without_rows)  # galah 归零后的表头
        assert len(header_without) < len(header_with), "0 行成员的列确实整体退出了表头"  # 缺列是事实
        empty_entries = [e for e in _sidecar(without_rows)["query_params"]["members"] if e["status"] == STATUS_EMPTY]
        assert [e["member"] for e in empty_entries] == [galah], empty_entries  # 台账指名它
        assert empty_entries[0]["rows"] == 0, empty_entries  # 且行数是 0

    def test_missing_member_file_is_recorded_not_silently_dropped(self, tmp_path):
        """成员文件缺失 (落盘后被清掉/没写成): 台账记 status=missing, 行数 0。

        形态取"三个路径都在列表里、其中一个文件不在盘上" —— 这是位置配对仍然
        可信的真实场景; 少传文件是另一种形态, 由 ``members_expected`` 暴露。
        """
        dl = _downloader(tmp_path)
        parts = [_save(dl, member, 2) for member in MEMBERS]  # 三个成员都先落出来
        gone = MEMBERS[0]  # 取第一个成员当受害者
        Path(parts[0]).unlink()  # 模拟"该成员文件不在盘上"
        merged = Path(dl._merge_region_files(parts, "std", 180.0, 30.0, 30.0, ["r"], "csv", None))  # 照常合并
        ledger = _sidecar(merged)["query_params"]["members"]  # 台账里必须看得见
        missing = [entry for entry in ledger if entry["status"] == "missing"]  # 只挑缺失项
        assert [entry["member"] for entry in missing] == [gone], ledger  # 指名道姓
        assert missing[0]["rows"] == 0 and missing[0]["total_count"] == 0, missing  # 行数与自报总数都是 0

    def test_short_member_list_is_exposed_not_guessed(self, tmp_path):
        """调用方少传一个成员文件: 台账按文件名登记, 且数量差异显式可读。

        位置配对在这种形态下**不可信** (第 2 个文件已经不代表第 2 个成员), 因此
        合并器不许把某个成员名安到它头上 —— 交给复核人拿组清单去 diff。
        """
        dl = _downloader(tmp_path)
        parts = [_save(dl, member, 2) for member in MEMBERS[1:]]  # 只交两个文件
        merged = Path(dl._merge_region_files(parts, "std", 180.0, 30.0, 30.0, ["r"], "csv", None))
        params = _sidecar(merged)["query_params"]  # 数量差异要显式可读
        assert params["members_expected"] == len(MEMBERS), params  # 组应有三个
        assert params["members_seen"] == len(parts), params  # 实际只交了俩
        assert all("best_" in entry["member"] for entry in params["members"]), params["members"]  # 退回文件名

    def test_ledger_keeps_member_level_truncation_visible(self, tmp_path):
        """成员级截断必须在台账里可读: 合并产物整体 truncated 时要能定位到谁。"""
        cut_member = MEMBERS[1]  # 取第二个成员当被截断的那个
        dl = _downloader(tmp_path)
        parts = [_save(dl, m, 1 if m == cut_member else 2, total=99 if m == cut_member else None)  # 只有它被截断
                 for m in MEMBERS]
        merged = Path(dl._merge_region_files(parts, "std", 180.0, 30.0, 30.0, ["r"], "csv", None))
        data = _sidecar(merged)  # 整体态与成员态要同时可读
        assert data["truncated"] is True, "被截断的成员必须让合并产物整体置截断 (既有语义)"  # 既有不变量
        cut = [e for e in data["query_params"]["members"] if e["truncated"]]  # 只挑被截断的成员
        assert [e["member"] for e in cut] == [cut_member], data["query_params"]["members"]  # 定位到它
        assert cut[0]["total_count"] == 99 and cut[0]["rows"] == 1, cut  # 自报 99 实得 1
