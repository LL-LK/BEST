# -*- coding: utf-8 -*-
"""判据级守护: 成员 sidecar 计数不可知时, 合并产物**不得**自称完整 (铁律 5)。

缺陷形态 (Q7 结构检测 P0, 本轮实跑复现于 ``temp/r4_p0_repro.py``):
``src/download_artifacts._member_counts`` 原先在 sidecar 读不到时只 warn 并
``return n_rows, False`` —— 把"截断与否无从回答"硬编码成**"未截断"**。于是
成员真值 ``total_count=99, truncated=True``, sidecar 一丢就被读成 ``(2, False)``,
台账记 ``status=ok``、合并产物 ``truncated=false``: 一个缺了几百行的文件自称完整。
更糟的形态是**全部**成员 sidecar 丢失 —— 那时合并产物整体 ``truncated=false``,
即"声称完整"。该函数自己的 docstring 写着"不能悄悄当成未截断", 实现与之矛盾。

同仓还有一处会主动制造 sidecar 缺失: ``write_provenance`` 是 best-effort
(复核产物不得阻断下载), 写失败只 warn 返回 None, 于是下载照常报成功而合并阶段
无 sidecar 可读。所以这不是假设分支, 是真实可达路径。

判据: 计数不可知必须**显式可观测且向保守方向倒** ——
``counts_known=False`` 逐成员登记, 成员与整体的 ``truncated`` 一律置 True。

**非空转 (取证纪律)**: 每条注入用例都配一道对照 —— sidecar 完好时
``counts_known=True``, 且"确实没被截断"的成员必须仍然是 ``truncated=False``。
少了对照, "永远置 truncated=True" 与"永远记录 counts_known=False" 同样能满足
上面所有断言, 而那正是把数据事故藏起来的另一种形态。
"""
from __future__ import annotations

# 标准库: json 读 sidecar / logging 验告警留痕 / pathlib 路径
import json  # 读回 sidecar: 断言的是复核人真能拿到的字段
import logging  # caplog: "记可观测"必须真的留下了痕, 不能只是代码里写了 warning
from pathlib import Path  # 产物/sidecar 路径构造

# 本地: 客户端 (rate_limit=0, 不发请求) / 下载器 (真实落盘与合并出口) /
# 数据模型 (替身) / 协议层导航组清单 (不自己抄一份成员名单)
from src.client import BestClient
from src.downloader import BestDownloader
from src.models import BestQueryResult, BestSource
from src.protocol import CATALOG_GROUPS

MEMBERS = CATALOG_GROUPS["std"]  # 权威组清单: 组扩成员时本文件自动跟着走


def _band_of(member: str) -> str:
    """取一个各不相同的波段标签 (scr_galah→g / xpsp→x), 使每成员独占一列。"""
    return member.rsplit("_", 1)[-1][0]


def _result(member: str, n_rows: int, total: int) -> BestQueryResult:
    """造成员查询结果: ``n_rows`` 实得行、``total`` 服务端自报总数 (两者不等即被截断)。"""
    band = _band_of(member)  # 独有波段 → 独有列
    sources = [BestSource(source_id=f"{member.upper()}{i}", ra=180.0 + i, dec=30.0 + i, snr=40.0 + i,  # 每成员独占一列: 0 行成员退表头时才看得出差别
                          magnitudes={band: 20.0 + i}) for i in range(n_rows)]
    return BestQueryResult(success=True, total_count=total, returned_count=n_rows,
                           truncated=total > n_rows, sources=sources, query_params={"catalog": member})


def _downloader(tmp_path: Path) -> BestDownloader:
    """输出目录锚在临时区的下载器 (不碰工作区, 不发请求)。"""
    return BestDownloader(BestClient(rate_limit=0), output_dir=str(tmp_path),
                          checkpoint_dir=str(tmp_path / ".ck"))


def _save(dl: BestDownloader, member: str, n_rows: int, total: int) -> Path:
    """真实落一份成员临时文件 (含其 sidecar) —— 合并链读的是文件, 不是 mock。"""
    name = f"best_{member}_ra180.0_dec30.0_r30arcsec_r.csv"
    return Path(dl._save_result(_result(member, n_rows, total), name, "csv"))


def _merge(dl: BestDownloader, parts: list[Path]) -> dict:
    """跑一次真实合并, 读回产物 sidecar 的 data 块 (复核人看的就是这一块)。"""
    merged = Path(dl._merge_region_files([str(p) for p in parts], "std", 180.0, 30.0, 30.0, ["r"], "csv", None))
    return json.loads(Path(str(merged) + ".provenance.json").read_text(encoding="utf-8"))["data"]


def _sidecar_of(part: Path) -> Path:
    """成员 sidecar 路径 (与合并器内部同一条推导)。"""
    return Path(str(part) + ".provenance.json")


# 四种能真正触发那条 except 的输入形态。逐个都注入过, 缺一个就等于该形态无人守:
#   missing   —— 文件不在 (write_provenance 写失败的直接后果)
#   bad_json  —— 内容不是 JSON
#   wrong_shape—— 合法 JSON 但 data 不是对象 (此前会抛 AttributeError, 不在窄 except 内)
#   bad_field —— 形态对但 total_count 不可强转
CORRUPTIONS = ("missing", "bad_json", "wrong_shape", "bad_field")  # 逐个都注入过: 缺一个即该形态无人守


def _corrupt(sidecar: Path, how: str) -> None:
    """把成员 sidecar 破坏成指定形态 (只动 sidecar, 数据文件保持可读)。"""
    if how == "missing":
        sidecar.unlink()
    elif how == "bad_json":
        sidecar.write_text("{not json at all", encoding="utf-8")
    elif how == "wrong_shape":
        sidecar.write_text('{"data": [1, 2, 3]}', encoding="utf-8")
    else:
        sidecar.write_text('{"data": {"total_count": "not-a-number", "truncated": false}}', encoding="utf-8")


class TestCountsUnknownIsNotSilentlyComplete:
    """注入 sidecar 失效 -> 断言合并产物**不是**静默通过。"""

    def test_all_sidecars_lost_product_does_not_claim_complete(self, tmp_path):
        """全部成员 sidecar 丢失: 整体 truncated 必须为 True (此前为 False, 即谎称完整)。

        这是本条最重的形态: 单个成员丢失时其余成员仍能撑住整体 truncated=True,
        掩盖了缺陷; **全部**丢失时旧实现让合并产物整体 ``truncated=false``。
        """
        dl = _downloader(tmp_path)  # 每种形态独立目录: 合并会删成员文件, 复用会互相污染
        parts = [_save(dl, m, 2, 99) for m in MEMBERS]  # 每成员真值 99 行、实得 2 行 (被截断)
        for part in parts:  # 全部丢失
            _sidecar_of(part).unlink()  # 全部丢失
        data = _merge(dl, parts)  # 合并产物 sidecar 的 data 块
        assert data["truncated"] is True, (
            f"计数全部不可知时合并产物不得自称完整: truncated={data['truncated']}, "
            f"total_count={data['total_count']} (真值 {99 * len(MEMBERS)})"
        )

    def test_each_corruption_form_is_marked_not_known(self, tmp_path, caplog):
        """四种失效形态逐一注入: 逐成员 counts_known=False + truncated=True, 且留告警痕。"""
        for how in CORRUPTIONS:  # 四种失效形态逐一注入
            root = tmp_path / how  # 每种形态独立目录: 合并会删成员文件, 复用会互相污染
            dl = _downloader(root)
            parts = [_save(dl, m, 2, 99) for m in MEMBERS]
            victim = parts[0]
            _corrupt(_sidecar_of(victim), how)
            with caplog.at_level(logging.WARNING, logger="src.download_artifacts"):
                data = _merge(dl, parts)
            ledger = data["query_params"]["members"]
            hit = [e for e in ledger if e["part"] == victim.name]
            assert len(hit) == 1, f"{how}: 台账里找不到受害成员 {victim.name}: {ledger}"
            entry = hit[0]
            assert entry["counts_known"] is False, f"{how}: 失效成员必须显式记 counts_known=False: {entry}"
            assert entry["truncated"] is True, f"{how}: 计数不可知时成员不得自称未截断: {entry}"
            assert data["truncated"] is True, f"{how}: 成员计数不可知必须把整体拉成截断: {data}"
            assert any("sidecar" in r.getMessage() for r in caplog.records), (
                f"{how}: 计数判为不可知必须留下可观测的告警痕, 不能只改返回值"
            )
            caplog.clear()

    def test_control_intact_sidecar_keeps_counts_known(self, tmp_path):
        """对照: sidecar 完好时 counts_known=True, 且真值照旧被继承。"""
        dl = _downloader(tmp_path)  # 输出目录锚在临时区
        cut, whole = MEMBERS[0], MEMBERS[1]  # 只让 cut 被截断, 其余完整
        parts = [_save(dl, m, 1 if m == cut else 2, 99 if m == cut else 2) for m in MEMBERS]  # 只让 cut 被截断
        data = _merge(dl, parts)  # sidecar 完好时的台账
        ledger = data["query_params"]["members"]
        assert all(e["counts_known"] is True for e in ledger), f"sidecar 完好即全部可信: {ledger}"

    def test_reverse_untruncated_member_stays_false(self, tmp_path):
        """反向守门: 确实没被截断的成员**仍须**是 truncated=False。

        这条是对照的另一半, 也是防"一律置 True"的关键: 保守不等于无脑拉满,
        否则门禁自己就成了噪声源, 迟早被整体关掉 (那才是真正的 fail-open)。
        """
        dl = _downloader(tmp_path)  # 输出目录锚在临时区
        parts = [_save(dl, m, 2, 2) for m in MEMBERS]  # 实得 2 = 自报 2: 无截断
        data = _merge(dl, parts)  # 无截断基线: 反向守门要判它仍是 False
        ledger = data["query_params"]["members"]
        assert all(e["truncated"] is False for e in ledger), f"无截断成员不得被误标: {ledger}"
        assert all(e["counts_known"] is True for e in ledger), ledger
        assert data["truncated"] is False, f"全员无截断时整体不得被误标: {data}"
        assert data["total_count"] == 2 * len(MEMBERS), data

    def test_no_member_can_be_unknown_and_claim_untruncated(self, tmp_path):
        """不变式: 不存在 ``counts_known=False`` 却 ``truncated=False`` 的台账项。

        直接钉住 P0 的形态本身 (而不是逐个触发条件): 无论将来用哪种方式造出
        计数不可知, 都不许同时自称未截断 —— 这正是旧实现返回 ``(n_rows, False)``
        做的事。
        """
        dl = _downloader(tmp_path)  # 输出目录锚在临时区
        parts = [_save(dl, m, 2, 99) for m in MEMBERS]  # 真值 99 / 实得 2: 三个成员全被截断
        _sidecar_of(parts[0]).write_text('{"data": {"total_count": 99, "truncated": true}}', encoding="utf-8")
        _sidecar_of(parts[1]).unlink()  # 一好一坏: 混态才验得出不变式不是恒真
        data = _merge(dl, parts)  # 一好一坏的混态产物
        for entry in data["query_params"]["members"]:
            assert not (entry["counts_known"] is False and entry["truncated"] is False), (
                f"计数不可知却自称未截断 —— 这就是 P0 的形态: {entry}"
            )
