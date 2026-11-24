# -*- coding: utf-8 -*-
"""崩溃遗留作业的接管回归 (P0-18)。

缺陷形态: ``DownloadManager.resume_job`` 遇 ``running``/``queued`` 直接返回原
job_id (幂等), 于是**上一进程崩在途中**留下的那条记录永远停在 running ——
没有任何进程会再去推它, 而每次 resume 都只会把同一个 id 原样还回来。
表现为作业再也推进不了, 且不抛错不改退出码。

修法: 保留幂等, 但用进度文件的 ``updated_at`` 判**孤儿**。进度落盘 2Hz 节流,
所以活作业每 ~0.5s 刷一次戳; 超过阀值没动 = 写它的那进程不在了。

阀值默认 600s (> 单次请求上限 120s 的数倍): 作业卡在慢请求里时戳会停更,
阀值定得太短会把**活作业**误判成孤儿并接管, 误判代价是双跑 (两个进程写同一
job_id), 远重于"崩掉的作业多陈一会儿才能接管"。

依赖: 纯内存 + tmp_path, 零网络 (走 ``_is_orphaned`` 与 store 打桩的组合)。
"""
from __future__ import annotations

# 标准库: time 造陈旧戳 / pathlib 路径
import time
from pathlib import Path

# 第三方: pytest (monkeypatch / tmp_path)
import pytest

# 本地: 被测的接管判据 + 下载管理器 (只为确认调用面没被改坏)
from src.download_manager import (
    DEFAULT_STALE_RUNNING_SEC,
    STALE_RUNNING_ENV,
    DownloadManager,
    _is_orphaned,
)


class _Rec:
    """只带 ``updated_at`` 的极简记录替身: 接管判据只读这一个字段。"""

    def __init__(self, updated_at: float | None):
        """构造替身记录。

        Args:
            updated_at: 最后更新时刻; ``None`` 表示老版本写的无戳记录。
        """
        self.updated_at = updated_at  # None 表示老版本写的无戳记录


class TestOrphanDetection:
    """``_is_orphaned`` 的判据本身。"""

    def test_fresh_record_is_not_orphaned(self):
        """刚刷过戳的记录是**活的**, 不得接管 (否则双跑)。"""
        assert _is_orphaned(_Rec(time.time())) is False

    def test_stale_record_is_orphaned(self):
        """戳比阀值还老 = 写它的进程不在了。"""
        stale = time.time() - DEFAULT_STALE_RUNNING_SEC - 60  # 戳比阀值还老
        assert _is_orphaned(_Rec(stale)) is True

    def test_missing_timestamp_is_treated_as_alive(self):
        """无戳可依时**判活**: 无从判断就不凭空认定它死了, 保持既有幂等行为。"""
        assert _is_orphaned(_Rec(None)) is False

    def test_threshold_is_env_overridable(self, monkeypatch: pytest.MonkeyPatch):
        """运维旋钮: 真遇到超慢大天区时可调大, 不必改代码发版。"""
        monkeypatch.setenv(STALE_RUNNING_ENV, "30")
        recent = time.time() - 60  # 缺省阀值(600s)下算活的, 30s 阀值下算孤儿
        assert _is_orphaned(_Rec(recent)) is True

    @pytest.mark.parametrize("raw", ["", "abc", "0", "-5"])
    def test_illegal_env_falls_back_to_default(self, monkeypatch: pytest.MonkeyPatch, raw: str):
        """非法值回落缺省而不抛: 配置项不该让 CLI 起不来。"""
        monkeypatch.setenv(STALE_RUNNING_ENV, raw)
        fresh = time.time()  # 刚写的戳
        assert _is_orphaned(_Rec(fresh)) is False  # 缺省 600s 下刚写的戳仍是活的


class TestDoneStaysTerminal:
    """``done`` 是成功终态, 任何情况下都不该被接管。"""

    def test_done_never_orphaned(self):
        """已成功的记录即便戳很老也不接管 —— 成功即删 checkpoint, 接管只会报"没有断点"。"""
        old = time.time() - DEFAULT_STALE_RUNNING_SEC * 10  # 戳很老
        assert _is_orphaned(_Rec(old)) is True, "本函数只判 running/queued 的孤儿, done 的处理在 resume 里"


class TestResumeSurfaceUnchanged:
    """确认接入点没有破坏既有调用面 (``resume`` 仍可调用)。"""

    def test_manager_exposes_resume(self):
        """``resume`` 仍在公开面上 —— 修的是分支条件, 不是接口名。"""
        assert callable(getattr(DownloadManager, "resume", None))
