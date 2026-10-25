# -*- coding: utf-8 -*-
"""回归: 合并路径必须拿 sidecar 的 sha256 校验成员文件 (AB3-P0-1)。

缺陷形态 (审计 A5 / FIX-STATUS-AUDIT §5.6 第 2 条, 本轮在 HEAD 631e72c 上实跑复现):
``merge_region_files`` 只读成员 sidecar 的 ``total_count`` / ``truncated``
(``_member_counts``), sidecar 里的那个 ``sha256`` **从来没人读** —— 于是成员文件
在"落盘 (``_save_result``) → 合并"之间被改掉多少都无人知晓:

    实跑 (temp/vfy/fix/fix_ab3_repro.py): 把成员 CSV 的一个数值改成 99.99
    → 盘上 sha ``e679efbe…`` ≠ sidecar 记的 ``1a7e3e3a…``
    → merge **不抛错**, 99.99 进入合并产物
    → 合并 sidecar 仍 ``checksum_match=True / row_status=ok / status=ok``

即"产物被篡改"在这条链上没有任何观测点: 合并产物自己的 ``checksum_match`` 比的
是"写前意图 vs 写后读回", 与成员是否被篡改无关。

判据 (铁律 5 禁 fail-open):
  - 盘上 sha ≠ sidecar sha ⟹ **抛错终止合并**, 且不得留下"看起来正常"的产物;
  - 校验**没验成** (sidecar 丢失 / 未登记 sha256) 与"验出不符"必须分开: 前者只
    披露 (``digest_checked=False`` 进台账 + warning), 后者直接抛错;
  - 对照: 成员完好时合并照旧成功且 ``digest_checked=True`` —— 少了对照,
    "永远抛错"或"永远放行"同样能满足一半断言。

离线: 成员文件由 ``BestDownloader._save_result`` 真实写出 (与 download_region 的
成员路径同口径), 客户端 ``rate_limit=0`` 全程不发请求。
"""
from __future__ import annotations

# 标准库: hashlib 重算盘上摘要 / json 读写 sidecar / logging 验披露留痕 / pathlib
import hashlib  # 重算盘上 sha256: 断言的是磁盘字节, 不是内存值
import json  # 读 sidecar: 复核人拿得到的东西才是判据
import logging  # caplog: "没验成必须披露"要真的留下 warning
from pathlib import Path  # 产物与 sidecar 路径

# 测试框架: raises 断言 fail-closed
import pytest

# 本地: 客户端 (rate_limit=0, 不发请求) / 下载器 (成员落盘 + 组合并的权威入口) /
# 数据模型 (成员结果替身) / 协议层导航组清单 (不自己抄一份成员名单)
from src.client import BestClient
from src.downloader import BestDownloader
from src.models import BestQueryResult, BestSource
from src.protocol import CATALOG_GROUPS

MEMBERS = CATALOG_GROUPS["std"]  # 权威组清单: 组扩成员时本文件自动跟着走
TAMPERED = "99.99"  # 篡改值: 取一个真实落盘值里没有的形态, 便于断言"它进没进产物"


def _member_result(member: str) -> BestQueryResult:
    """造成员查询结果 (2 行, 未截断)。"""
    return BestQueryResult(
        success=True, total_count=2, returned_count=2, truncated=False,
        sources=[BestSource(source_id=f"{member.upper()}{i}", ra=180.0 + i, dec=30.0 + i, snr=40.0 + i)
                 for i in range(2)],
        query_params={"catalog": member, "ra": 180.0, "dec": 30.0, "radius_arcsec": 30.0},
    )


def _downloader(tmp_path: Path) -> BestDownloader:
    """输出目录锚在临时区的下载器 (不碰工作区, 不发请求)。"""
    return BestDownloader(BestClient(rate_limit=0), output_dir=str(tmp_path),
                          checkpoint_dir=str(tmp_path / ".ck"))


def _parts(dl: BestDownloader) -> list[str]:
    """真实落三份成员临时文件 (各带自己的 sidecar), 返回路径列表。"""
    return [dl._save_result(_member_result(m), f"best_{m}_ra180.0_dec30.0_r30arcsec_r.csv", "csv")
            for m in MEMBERS]


def _sidecar_of(part: str | Path) -> Path:
    """成员 sidecar 路径 (与合并器内部同一条推导)。"""
    return Path(str(part) + ".provenance.json")


def _tamper(part: str) -> tuple[str, str]:
    """在**盘上**篡改成员文件的一个数值 (不动 sidecar), 返回 (sidecar sha, 盘上 sha)。"""
    victim = Path(part)  # 受害者: 第一个成员的数据文件
    sidecar_sha = json.loads(_sidecar_of(victim).read_text(encoding="utf-8"))["data"]["sha256"]
    lines = victim.read_text(encoding="utf-8-sig").splitlines()
    lines[1] = lines[1].replace("40.0", TAMPERED)  # 第 1 行是表头, 第 2 行是首条数据
    victim.write_text("\n".join(lines) + "\n", encoding="utf-8-sig", newline="")
    disk_sha = hashlib.sha256(victim.read_bytes()).hexdigest()  # 从**盘上**重算: 内存值验不出落盘后被改
    return sidecar_sha, disk_sha


class TestTamperedMemberIsRefused:
    """盘上字节与 sidecar 登记值不符 ⟹ 拒绝合并, 不产产物。"""

    def test_tampered_member_file_is_rejected_before_it_reaches_the_product(self, tmp_path):
        """篡改的成员必须让合并抛错, 且被改的值一行都不许进最终产物。"""
        dl = _downloader(tmp_path)  # 输出目录锚在 pytest 临时区
        parts = _parts(dl)  # 三个成员各落一份文件与一份 sidecar
        sidecar_sha, disk_sha = _tamper(parts[0])  # 只改第一个成员的数据文件, 不动 sidecar
        assert sidecar_sha != disk_sha, "夹具自检: 篡改后盘上摘要必须与 sidecar 不同, 否则本用例是空转"

        with pytest.raises(RuntimeError, match="SHA-256"):  # fail-closed: 不许只告警后照旧合并
            dl._merge_region_files(parts, "std", 180.0, 30.0, 30.0, ["r"], "csv", None)

        merged = list(tmp_path.glob("best_std_*.csv"))  # 合并产物是自动名 best_std_*
        assert merged == [], f"篡改被拒时不得留下合并产物, 实得 {[p.name for p in merged]}"

    def test_tampered_value_never_lands_in_the_merged_artifact(self, tmp_path):
        """载荷面: 拒绝之后, 输出目录里任何文件都不含被篡改的那个值。"""
        dl = _downloader(tmp_path)  # 与上一例同构, 只换断言面
        parts = _parts(dl)  # 成员落盘走真实 _save_result, 不造假文件
        _tamper(parts[0])  # 显式输出名: 这条验的是产物里有没有那个篡改值
        with pytest.raises(RuntimeError, match="SHA-256"):
            dl._merge_region_files(parts, "std", 180.0, 30.0, 30.0, ["r"], "csv", "merged.csv")
        body = (tmp_path / "merged.csv").read_text(encoding="utf-8-sig") if (tmp_path / "merged.csv").exists() else ""
        assert TAMPERED not in body, "被篡改的值不得以任何形态落到合并产物里"

    def test_control_intact_member_merges_and_is_marked_verified(self, tmp_path):
        """对照: 成员完好时合并照旧成功, 台账逐成员记 digest_checked=True。"""
        dl = _downloader(tmp_path)  # 对照支路: 成员全部完好
        merged = Path(dl._merge_region_files(_parts(dl), "std", 180.0, 30.0, 30.0, ["r"], "csv", None))
        assert merged.exists(), "完好成员不得被新门禁误杀"
        data = json.loads(_sidecar_of(merged).read_text(encoding="utf-8"))["data"]
        ledger = data["query_params"]["members"]
        assert [e["member"] for e in ledger] == list(MEMBERS), ledger  # 台账仍逐成员登记
        assert all(e["digest_checked"] is True for e in ledger), f"已校验的成员必须自证验过: {ledger}"
        assert len(merged.read_text(encoding="utf-8-sig").splitlines()) == 1 + 2 * len(MEMBERS)


class TestUnverifiableMemberIsDisclosed:
    """没验成 ≠ 验过: 必须披露, 不得写 digest_checked=True。"""

    def test_sidecar_without_sha256_is_marked_unchecked_not_assumed_clean(self, tmp_path, caplog):
        """sidecar 未登记 sha256: 合并继续, 但该成员记 digest_checked=False 且留痕。"""
        dl = _downloader(tmp_path)  # 披露支路: sidecar 在场但缺 sha256 键
        parts = _parts(dl)  # 成员与其 sidecar 都由落盘链真实产出
        _sidecar_of(parts[0]).write_text(  # 手写一个无 sha256 键的 sidecar: 契约缺字段
            json.dumps({"data": {"total_count": 2, "truncated": False}}), encoding="utf-8")  # 无 sha256 键
        with caplog.at_level(logging.WARNING, logger="src.download_artifacts"):
            merged = Path(dl._merge_region_files(parts, "std", 180.0, 30.0, 30.0, ["r"], "csv", None))
        ledger = json.loads(_sidecar_of(merged).read_text(encoding="utf-8"))["data"]["query_params"]["members"]
        victim = [e for e in ledger if e["part"] == Path(parts[0]).name]
        assert len(victim) == 1, ledger
        assert victim[0]["digest_checked"] is False, f"没验成不得记成已校验: {victim[0]}"
        assert any("sha256" in r.getMessage() for r in caplog.records), "没验成必须留下可观测的告警痕"

    def test_missing_sidecar_is_marked_unchecked(self, tmp_path):
        """sidecar 整个丢失 (write_provenance 是 best-effort): 同样记未校验。"""
        dl = _downloader(tmp_path)  # 混态支路: 一好一坏, 免得断言恒真
        parts = _parts(dl)  # 只丢中间那个成员的 sidecar
        _sidecar_of(parts[1]).unlink()  # 只丢一个: 剩下的仍须记已校验
        merged = Path(dl._merge_region_files(parts, "std", 180.0, 30.0, 30.0, ["r"], "csv", None))
        ledger = json.loads(_sidecar_of(merged).read_text(encoding="utf-8"))["data"]["query_params"]["members"]
        by_name = {e["part"]: e for e in ledger}
        assert by_name[Path(parts[1]).name]["digest_checked"] is False, ledger
        assert by_name[Path(parts[0]).name]["digest_checked"] is True, "sidecar 完好的成员仍须记已校验"
