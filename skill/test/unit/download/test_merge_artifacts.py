"""std 导航组合并落盘路径的单元测试 (格式名实相符 + sidecar 溯源)。

守的不变量 (A3-02):
  A3-02① 合并产物的**内容格式必须与文件后缀一致**。合并层曾按 ``.csv``
    后缀分派格式, 而自动名用 ``output_format`` 拼后缀 (``.txt`` / ``.votable``),
    于是这两种名下的产物全落进 JSON 分支 —— 实测 txt 产物首字符是 ``{``,
    按 TSV 读回 ``DictReader.fieldnames == ['{']`` (整表塌成一列), votable
    更是连成员文件都读不回来 (拿 XML 喂 ``json.loads`` 直接抛)。分派只看
    声明格式 + 过白名单, 与文件名是否相配也要显式校验 (fail-closed)。
  A3-02② 合并产物必须伴随 provenance sidecar: 它是主路径产物, 此前只走
    ``export_results`` 直写, 于是既无 sha256 也无 query_params/completeness,
    人工复核与 provenance 契约在这条路径上完全失效。哈希必须**读回落盘文件
    重算** (防"空气写")。

离线: 成员临时文件由 ``_save_result`` 真实写出 (与 ``download_region`` 的
成员路径同口径), 但全程不碰网络 —— 客户端仅取 ``BestClient(rate_limit=0)``,
不发任何请求。
"""
from __future__ import annotations

# 标准库: csv 按分隔符读回 (验"产物能被自己声称的格式解析") / 哈希重算 (验 sidecar
# 里的 sha256 真对应磁盘字节) / json 读 sidecar / ElementTree 解析 VOTable (验
# XML 结构而不是只看后缀) / 路径
import csv  # 按声称的分隔符读回: 塌成一列 (fieldnames==['{']) 即是格式欺骗的特征
import hashlib  # 重算 sha256: 用内存值当基准就验不出"写了但没真落"
import json  # 读 sidecar: 断言的是复核人真能拿到的字段
import xml.etree.ElementTree as ET  # 解析 VOTable: 只看后缀挡不住"XML 名的 JSON"
from pathlib import Path  # 产物/伴生文件路径断言

# 测试框架: parametrize 跑三格式矩阵; raises 断言 fail-closed
import pytest

# 本地: 客户端 (rate_limit=0, 不发请求) / 下载器 (合并链的权威入口) /
# 数据模型 (成员查询结果替身) / 被测落盘出口
from src.client import BestClient
from src.download_artifacts import (
    export_results,  # 行级落盘出口: 合并产物与直写导出都经它
    merge_region_files,  # 合并器: 读回成员 + 写合并产物 + 补 sidecar
    resolve_export_format,  # 格式白名单与名实相符的门
)
from src.downloader import BestDownloader  # 合并链的权威入口 (成员落盘 + 组合并薄壳)
from src.models import BestQueryResult, BestSource
from src.protocol import CATALOG_GROUPS  # 导航组成员清单的权威来源
from src.serialization import VOTABLE_XMLNS

MEMBERS = CATALOG_GROUPS["std"]  # 直接取协议层的导航组清单: 组扩了成员, 这条用例自动跟着走


def _member_result(member: str, n_rows: int = 2, total: int | None = None) -> BestQueryResult:
    """造一个成员星表的查询结果 (列集随表变化, 逼合并层走列并集)。

    Args:
        member: 成员星表名 (只进 query_params 与 source_id 前缀)。
        n_rows: 实际取回行数。
        total: 服务端自报总行数; 缺省与 ``n_rows`` 同值 (即未截断)。

    Returns:
        可直接喂 ``_save_result`` 的查询结果。
    """
    sources = [
        BestSource(source_id=f"{member.upper()}{i}", ra=180.0 + i, dec=30.0 + i, snr=40.0 + i)
        for i in range(n_rows)
    ]
    return BestQueryResult(
        success=True,
        total_count=n_rows if total is None else total,  # 与 n_rows 不同即模拟被 max_rows 截断
        returned_count=n_rows,
        truncated=(n_rows if total is None else total) > n_rows,  # 截断标记由计数差推出, 不另开一个入参造"假截断"
        sources=sources,
        query_params={"catalog": member, "ra": 180.0, "dec": 30.0, "radius_arcsec": 30.0},
    )


def _downloader(tmp_path: Path) -> BestDownloader:
    """构造输出目录锚在临时区的下载器 (不碰工作区, 不发请求)。"""
    return BestDownloader(BestClient(rate_limit=0), output_dir=str(tmp_path),
                          checkpoint_dir=str(tmp_path / ".ck"))


def _merge(dl: BestDownloader, fmt: str, members: tuple[str, ...] = MEMBERS,
           result_of: object = None) -> Path:
    """跑一遍真实的成员落盘 + 合并链, 返回合并产物路径。

    Args:
        dl: 下载器。
        fmt: 输出格式。
        members: 成员星表名。
        result_of: 成员结果工厂 (缺省 ``_member_result``); 截断场景用来传替身。

    Returns:
        合并产物的 :class:`Path`。
    """
    factory = result_of or (lambda m: _member_result(m))
    parts = [
        dl._save_result(factory(m), f"best_{m}_ra180.0_dec30.0_r30arcsec_r.{fmt}", fmt)
        for m in members
    ]
    return Path(dl._merge_region_files(parts, "std", 180.0, 30.0, 30.0, ["r"], fmt, None))


class TestMergedArtifactFormat:
    """A3-02①: 合并产物的后缀与内容必须是同一个格式 (不是 JSON 冒充 TSV)。"""

    @pytest.mark.parametrize(
        ("fmt", "suffix", "delimiter"),
        [("csv", ".csv", ","), ("txt", ".tsv", "\t")],  # txt 的规范容器是 .tsv
    )
    def test_delimited_artifact_reads_back_as_its_own_format(self, tmp_path, fmt, suffix, delimiter):
        """表格类合并产物: 后缀是规范扩展名, 且能按该分隔符读回全部列。"""
        merged = _merge(_downloader(tmp_path), fmt)
        assert merged.suffix == suffix, f"{fmt} 的产物后缀必须是 {suffix}, 不得用 output_format 直拼"
        text = merged.read_text(encoding="utf-8-sig")  # utf-8-sig: 表格类带 BOM, 与落盘口径一致
        assert not text.lstrip().startswith("{"), "产物不得是 JSON 冒充分隔符文本"
        with merged.open("r", encoding="utf-8-sig", newline="") as handle:  # newline="" 是 csv 的硬要求
            reader = csv.DictReader(handle, delimiter=delimiter)
            rows = list(reader)
        assert len(reader.fieldnames or []) >= 5, "表头塌成一列即说明读错了分隔符/格式"
        assert "source_id" in (reader.fieldnames or []), "行投影的必存列必须在表头里"
        assert len(rows) == 6, "三成员各 2 行必须并成 6 行 (行级并集)"

    def test_votable_artifact_is_real_xml(self, tmp_path):
        """votable 合并产物: XML 文档 + nrows/行数自洽 (此前该格式直接抛 JSONDecodeError)。"""
        merged = _merge(_downloader(tmp_path), "votable")
        assert merged.suffix == ".xml", "votable 的规范扩展名是 .xml"
        root = ET.fromstring(merged.read_text(encoding="utf-8"))  # 解析而非只看后缀: XML 名的 JSON 在此现形
        assert root.tag == f"{{{VOTABLE_XMLNS}}}VOTABLE", "根元素必须是 VOTABLE (ns 取自序列化层同一常量)"
        table = root.find(f".//{{{VOTABLE_XMLNS}}}TABLE")
        assert table is not None and table.get("nrows") == "6", "nrows 须等于实际并入行数"
        assert len(root.findall(f".//{{{VOTABLE_XMLNS}}}TR")) == 6, "TR 数须等于实际并入行数"

    def test_json_artifact_round_trips(self, tmp_path):
        """json 合并产物: 读回仍是 6 行的 sources 列表 (回归护栏, 免得改坏另一支)。"""
        merged = _merge(_downloader(tmp_path), "json")
        assert merged.suffix == ".json"
        payload = json.loads(merged.read_text(encoding="utf-8"))
        assert len(payload["sources"]) == 6

    def test_unsupported_format_fails_before_any_write(self, tmp_path):
        """白名单外格式必须在任何落盘之前显式报错 (fail-closed, 不静默出 JSON)。"""
        dl = _downloader(tmp_path)
        with pytest.raises(ValueError, match="unsupported output format"):
            dl._merge_region_files([], "std", 180.0, 30.0, 30.0, ["r"], "xlsx", None)
        assert not list(tmp_path.glob("*.xlsx")), "门禁失败时不得留下任何产物"

    def test_fits_group_merge_is_rejected_explicitly(self, tmp_path):
        """FITS 是二进制, 成员文件读不回: 必须明说不支持, 不能抛 JSONDecodeError。"""
        dl = _downloader(tmp_path)
        part = dl._save_result(_member_result("ps1"), "best_ps1.fits", "fits")  # 二进制成员先落出来
        with pytest.raises(ValueError, match="无法按行读回"):
            dl._merge_region_files([part], "std", 180.0, 30.0, 30.0, ["r"], "fits", None)


class TestExportFormatGate:
    """A3-02① 的门本体: 声明格式 + 扩展名双口径校验 (contracts 的 fmt_in_whitelist)。"""

    def test_name_format_mismatch_is_rejected(self, tmp_path):
        """名实不符即拒: .csv 名 + txt 声明 (TSV 内容落进 .csv) 只有下游才会发现。"""
        with pytest.raises(ValueError, match="不相配"):
            export_results([{"a": 1}], "out.csv", tmp_path, "txt")

    def test_unknown_extension_is_rejected_when_format_not_given(self, tmp_path):
        """未声明格式时按扩展名反查; 反查不到就报错 (此前一律静默写 JSON)。"""
        with pytest.raises(ValueError, match="无法反查输出格式"):
            export_results([{"a": 1}], "out.bin", tmp_path)

    def test_fits_through_text_export_is_rejected(self, tmp_path):
        """FITS 在白名单内但本出口写文本: 显式报错, 不给"名为 fits 实为 JSON"的文件。"""
        with pytest.raises(ValueError, match="FITS"):
            export_results([{"a": 1}], "out.fits", tmp_path, "fits")

    def test_case_insensitive_alias_is_accepted(self, tmp_path):
        """大小写与别名 (.txt/.votable) 是既有调用姿势: 放行但内容要对得上。"""
        assert resolve_export_format("OUT.CSV", "CSV") == "csv"
        assert resolve_export_format("out.txt", "txt") == "txt"
        # 两列才看得出分隔符: 单列表里根本没有分隔符可写
        out = Path(export_results([{"a": 1, "b": 2}], "out.txt", tmp_path, "txt"))
        assert out.read_text(encoding="utf-8-sig").splitlines()[0] == "a\tb", "txt 名的内容必须是 TSV"


class TestMergedProvenance:
    """A3-02②: 合并产物必须带可复核的 sidecar (sha256/query_params/completeness)。"""

    def test_sidecar_carries_reviewable_fields(self, tmp_path):
        """sidecar 在场且字段齐: 复核人靠它回答"这份文件来自哪次查询、内容是否完整"。"""
        merged = _merge(_downloader(tmp_path), "csv")
        sidecar = merged.with_suffix(merged.suffix + ".provenance.json")
        assert sidecar.exists(), "合并产物必须伴随 provenance sidecar (主路径产物也要可复核)"
        env = json.loads(sidecar.read_text(encoding="utf-8"))
        data = env["data"]
        assert data["sha256"] == hashlib.sha256(merged.read_bytes()).hexdigest(), (  # 从磁盘重算
            "sha256 必须对应落盘文件的真实字节 (防'写了但没真落'的空气写)")
        assert data["query_params"]["catalog"] == "std"
        assert data["query_params"]["merged"] is True, "溯源须标明这是导航组合并而非单表查询"
        assert data["query_params"]["radius_arcsec"] == 30.0
        assert data["query_params"]["bands"] == ["r"]
        assert data["total_count"] == 6 and data["returned_count"] == 6
        assert data["row_status"] == "ok"
        assert env["lineage"]["completeness_gate"] == {"required": True, "value": 1.0}

    def test_truncated_member_propagates(self, tmp_path):
        """成员被 max_rows 截断时, 合并产物必须继承截断标记与服务端总数。"""
        merged = _merge(_downloader(tmp_path), "csv",
                        result_of=lambda m: _member_result(m, n_rows=2, total=50))
        data = json.loads(
            merged.with_suffix(merged.suffix + ".provenance.json").read_text(encoding="utf-8"))["data"]
        assert data["truncated"] is True, "被截断的成员不能被并成一份'看起来完整'的文件"
        assert data["total_count"] == 150, "total_count 取各成员服务端自报总数之和"
        assert data["returned_count"] == 6, "returned_count 是实际并入的行数"

    def test_member_artifacts_and_their_sidecars_are_cleaned(self, tmp_path):
        """成员临时文件与其 sidecar 读毕即删: 只剩合并产物 + 它的 sidecar。"""
        merged = _merge(_downloader(tmp_path), "csv")
        leftovers = sorted(p.name for p in tmp_path.iterdir() if p.is_file())
        assert leftovers == sorted([merged.name, merged.name + ".provenance.json"]), (
            f"合并后不该留中间产物, 实得 {leftovers}")
