"""阻断性门禁 ``checksum_match == true`` 真的可满足 (A3-05)。

守的不变量: sidecar 的 ``checksum_match`` 必须是**真实算出来的布尔**, 任何
格式 (含 FITS) 都一样。此前它是字符串且恒为 ``"unknown"``: ``_save_result``
的四个调用点全部省略 ``expected_sha256``, FITS 分支与合并分支更是硬编码
``"unknown"``。而 ``agents/openai.yaml`` 与 ``manifest.yaml`` 都把
``checksum_match`` 列为 **blocking** 门禁 —— 一个恒假的阻断条件等于没有门禁。

判定口径: ``checksum_match = (写前按落盘编码算的意图摘要 == 写后从盘上读回
的摘要)``。两个来源必须独立: 拿同一个函数算两遍必然相同, 证明不了任何事。

离线: 只走落盘出口, 客户端为 ``rate_limit=0`` 的真客户端但一次请求都不发。
"""
from __future__ import annotations

# 标准库: json 读 sidecar / pathlib 产物与临时区定位
import json  # 断言的是复核人真能从盘上读到的字段
from pathlib import Path  # 产物/伴生文件定位, 以及半截文件模拟

# 测试框架: parametrize 跑格式矩阵; monkeypatch 模拟"写了一半"的半截文件
import pytest  # 格式矩阵与"门禁能转红"两半断言都靠它

# 本地: 客户端 (不发请求) / 下载器 (四条落盘路径的最终出口)
from src.client import BestClient  # 只取真客户端, rate_limit=0: 一个请求都不发
from src.download_artifacts import merge_region_files  # 合并出口: 曾硬编码 unknown
from src.downloader import BestDownloader  # 四条落盘路径的最终出口 _save_result 在此

# 本地: 数据模型 (查询结果载体)
from src.models import BestQueryResult, BestSource  # 造带行信封, 过非空闸

# 格式矩阵: (output_format, 文件名) —— 线上白名单 (csv/txt/json/votable) + 落盘层本地 FITS
FORMATS = [("csv", "out.csv"), ("txt", "out.tsv"), ("json", "out.json"),
           ("votable", "out.xml"), ("fits", "out.fits")]  # 五条分支各来一遍: FITS 曾被硬编码 unknown


def _dl(tmp_path) -> BestDownloader:
    """造一个锚定临时区的下载器 (输出目录与断点目录都不许落 CWD 相对默认)。"""
    return BestDownloader(BestClient(rate_limit=0), output_dir=str(tmp_path / "data"),
                          checkpoint_dir=str(tmp_path / "ckpt"))  # 临时区隔离: 不污染 CWD 的 .checkpoints


def _result() -> BestQueryResult:
    """造一份单行成功信封 (非空闸要过, 否则测的是空结果而非校验和)。"""
    return BestQueryResult(
        success=True, total_count=1, returned_count=1,  # 一行一行: 非空闸与完整性都判 1
        sources=[BestSource(source_id="S1", ra=180.0, dec=30.0, magnitudes={"r": 15.2})],  # 带星等列
        query_params={"catalog": "ps1/q", "sqlid": "s4242"},  # 溯源参数: sidecar 契约的一环
    )


def _sidecar(saved: str) -> dict:
    """读回落盘产物的 provenance sidecar (复核契约的载体)。"""
    sidecar = Path(saved).with_suffix(Path(saved).suffix + ".provenance.json")  # 与写出一侧同一命名约定
    return json.loads(sidecar.read_text(encoding="utf-8"))  # 读盘上那份才谈得上可复核


@pytest.mark.parametrize("fmt,filename", FORMATS)
def test_checksum_match_is_a_real_boolean_for_every_format(tmp_path, fmt, filename):
    """任意格式落盘后 ``checksum_match`` 都是真实计算结果, 绝不是 "unknown"。"""
    downloader = _dl(tmp_path)  # 锚在临时区的下载器
    saved = downloader._save_result(_result(), filename, fmt)  # 走真实的落盘出口

    value = _sidecar(saved)["data"]["checksum_match"]  # 门禁要比的就是这个键
    assert isinstance(value, bool), f"{fmt}: 门禁要比的是布尔, 拿到 {value!r} ({type(value).__name__})"
    assert value is True, f"{fmt}: 写前意图摘要与写后读回摘要必须一致"
    assert _sidecar(saved)["data"]["sha256"] == downloader.compute_sha256(saved), "sidecar 的 sha256 仍须读回落盘文件重算"


def test_merge_sidecar_also_carries_a_boolean(tmp_path):
    """合并产物的 sidecar 曾硬编码 "unknown": 主路径产物同样不许有假门禁。"""
    downloader = _dl(tmp_path)  # 只为拿同一个输出目录锚点
    merged = merge_region_files([], "ps1", 180.0, 30.0, 600.0, None, "csv", "merged.csv",
                               output_dir=Path(str(tmp_path / "data")))  # 零成员: 走真实的合并与补 sidecar 链

    value = _sidecar(merged)["data"]["checksum_match"]  # 门禁键
    assert isinstance(value, bool) and value is True, f"合并产物拿到 {value!r}, 必须是真实判定出的 True"


def test_checksum_match_can_actually_go_false(tmp_path, monkeypatch):
    """假门禁的特征是恒真/恒假: 这里造一次半截落盘, 门禁必须真的转红。"""
    from src.scripts import guards  # 局部导入: 只为拿原实现再包一层

    real_write = guards.atomic_write_text  # 原实现: 包一层而不是替换语义

    def _truncating_write(path, content, encoding="utf-8", retry_delays=()):
        """照常原子写, 但写完把文件截断一半 —— 模拟"写了却没真落全"。"""
        real_write(path, content, encoding=encoding, retry_delays=retry_delays)  # 先按生产口径落盘
        data = Path(path).read_bytes()  # 再把落盘结果读回来
        Path(path).write_bytes(data[: len(data) // 2])  # 砍掉一半: 意图与事实就此分家

    monkeypatch.setattr("src.downloader.atomic_write_text", _truncating_write)  # 只截落盘出口: sidecar 那侧仍走原实现
    downloader = _dl(tmp_path)  # 锚在临时区的下载器
    saved = downloader._save_result(_result(), "half.csv", "csv")  # 半截落盘也要走完整出口

    assert _sidecar(saved)["data"]["checksum_match"] is False, "产物与意图不符时必须记 False, 恒 True 同样是假门禁"
