# -*- coding: utf-8 -*-
"""回归: 并发写同一进度文件不得撞车 (AA7-A7-09)。

缺陷形态 (审计 A5 / G6, 本轮在 HEAD 631e72c 上实跑复现):
进度文件走 ``atomic_write_text`` 的 ``先写 <name>.tmp 再 os.replace``, 而这个临时名
**只由目标文件名派生** (``src.scripts.guards.atomic_write_text``), 不含 pid / 线程 /
随机量 —— 同一个 job_id 的两条写路径抢同一个 tmp: 一条刚 open 成 tmp, 另一条就把它
truncate 或 replace 掉, 于是前者要么写不进去 (PermissionError), 要么 replace 时 tmp
已经没了 (FileNotFoundError)。

    实跑 (temp/vfy/fix/fix_a709_repro.py, 16 线程 × 480 次写同一 job_id):
    修前 失败 114/480 = 23.8%  (PermissionError 85 + FileNotFoundError 29)
    修后 失败   0/480 =  0.0%

严重级为何是 P0: 该异常不在 ``DownloadManager._run`` 的 try 范围内, 顺着
``save -> _flush -> advance_pages`` 直达下载工作线程 —— 一次瞬时竞争就杀死任务,
而盘上留的是"看起来写成功了"的旧文件。

判据 (铁律 5): 并发落盘要么成功, 要么明确抛错; 不许"抛了异常但文件看起来没事"。
本文件守的是**进程内**并发这一面 (管理器线程 + GUI 轮询线程); 跨进程撞 tmp 名仍需
I/O 单点把 tmp 名加上 pid/线程/随机量, 见 ``src/download_progress._WRITE_LOCKS``
处的登记说明。
"""
from __future__ import annotations

# 标准库: 并发执行器 (真实多线程压测) / json 校验盘上文件始终是完整载荷 / pathlib
import json  # 读回进度文件: 断言"读者永远看到完整文件"
from concurrent.futures import ThreadPoolExecutor  # 真实并发: mock 造不出 tmp 名互撞
from pathlib import Path  # 进度目录与文件路径

# 本地: 进度存储与记录 (被测面)
from src.download_progress import ProgressRecord, ProgressStore

WRITES = 240  # 并发写次数: 足以稳定复现撞车 (修前同规模 ~24% 失败), 又能在秒级跑完
WORKERS = 16  # 与管理器默认并行度同量级


def _store(tmp_path: Path) -> ProgressStore:
    """进度目录锚在临时区的存储 (不碰工作区的 .progress)。"""
    return ProgressStore(tmp_path / ".progress")


def _rec(job_id: str, i: int) -> ProgressRecord:
    """造一条进度记录 (页数随 i 变, 便于验证最后一次写入确实落了盘)。"""
    return ProgressRecord(job_id=job_id, kind="region", total_pages=WRITES, done_pages=i)


class TestConcurrentWritesDoNotCollide:
    """同一 job_id 的并发落盘: 零异常, 且盘上文件始终是完整 JSON。"""

    def test_concurrent_writes_to_one_progress_file_all_succeed(self, tmp_path):
        """240 次并发写同一进度文件: 一次都不许抛 (修前 23.8% 抛 PermissionError/FileNotFoundError)。"""
        store = _store(tmp_path)
        errors: list[str] = []

        def one(i: int) -> None:
            """写一次同一 job_id 的进度 (异常记进 errors 而不是抛出, 为的是统计失败率)。"""
            try:
                store.save(_rec("job_shared", i))  # 同一 job_id: 撞车形态
            except Exception as exc:  # noqa: BLE001 - 统计的是并发失败率
                errors.append(type(exc).__name__)

        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            list(pool.map(one, range(WRITES)))

        assert errors == [], f"并发写同一进度文件不得失败: {len(errors)}/{WRITES} 抛异常, 类型分布 {set(errors)}"

    def test_progress_file_is_always_complete_json_for_readers(self, tmp_path):
        """读者 (GUI/CLI 轮询) 任何时刻读到的都必须是完整 JSON, 不能是半行。"""
        store = _store(tmp_path)
        bad: list[str] = []

        def one(i: int) -> None:
            """写一次后立刻以读者身份读回: 半写文件在这一步现形。"""
            store.save(_rec("job_shared", i))
            text = (tmp_path / ".progress" / "job_shared.json").read_text(encoding="utf-8-sig")
            try:
                json.loads(text)  # 半写文件在此现形: 原子写被撞破时读者会读到截断的 JSON
            except json.JSONDecodeError as exc:
                bad.append(str(exc))

        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            list(pool.map(one, range(WRITES)))

        assert bad == [], f"并发写期间读者读到了不完整文件: {bad[:3]}"

    def test_no_tmp_file_is_left_behind(self, tmp_path):
        """并发写结束后不得残留 .tmp: 残留即"某条写路径被另一条踩掉"的物证。"""
        store = _store(tmp_path)
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            list(pool.map(lambda i: store.save(_rec("job_shared", i)), range(WRITES)))
        leftovers = [p.name for p in (tmp_path / ".progress").iterdir() if p.suffix == ".tmp"]
        assert leftovers == [], f"不得残留临时文件: {leftovers}"

    def test_control_distinct_jobs_stay_independent(self, tmp_path):
        """对照: 不同 job_id 并发写互不干扰 (串行化按路径加锁, 不误伤并行度)。"""
        store = _store(tmp_path)
        jobs = [f"job_{i % 8}" for i in range(WRITES)]
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            list(pool.map(lambda pair: store.save(_rec(pair[1], pair[0])), enumerate(jobs)))
        names = sorted(p.name for p in (tmp_path / ".progress").iterdir())
        assert names == sorted(f"{j}.json" for j in set(jobs)), f"各作业各自成文件, 实得 {names}"
        for name in names:
            payload = json.loads((tmp_path / ".progress" / name).read_text(encoding="utf-8-sig"))
            assert payload["job_id"] == Path(name).stem, f"{name} 的 job_id 必须与文件名同源"
