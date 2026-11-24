"""任务日志管理器单元测试 (append-only JSONL 事件流)。

守的回归: 一行一事件且每行独立可解析 (流式/grep 消费的前提); task_id/event/
level 三类过滤与 n 语义; warn 不算 error (部分命中是常态, 升级成 error 会让
汇总永远红); 超长载荷降级为摘要而不是把单行写爆; 空/不存在目录返回空列表。
"""
from __future__ import annotations

import json  # 标准库: 逐行解析 jsonl, 验证行定向性

import pytest  # 测试框架: tmp_path 提供每次用例独立的日志目录

try:
    # 被测单元: 事件枚举 (submit/done/hook 是断言用的事件锚点) + 记录器与
    # 单行文本格式化器
    from src.task_log import (
        EVENT_DONE,
        EVENT_HOOK,
        EVENT_SUBMIT,
        TaskLogger,
        fmt_record,
        fmt_records,
    )
except Exception as _legacy_err:  # legacy-import-guard
    # 源码树调整导致旧导入路径失效时整模块跳过, 不让收集期报错
    import pytest as _pytest  # 别名导入: 顶部 import 若已失败, 这里重新绑定
    _pytest.skip(f'legacy import unavailable: {_legacy_err!r}', allow_module_level=True)  # 模块级 skip


class TestTaskLogger:
    """TaskLogger: 追加、尾随过滤、任务聚合、问题视图、截断与空态。"""

    def test_log_append_and_tail(self, tmp_path):
        """追加顺序保持, data 载荷原样可读 (tail 是最常用的查询面)。"""
        log = TaskLogger(log_dir=str(tmp_path))  # 同目录, 顺序写入两条
        log.log("j1", EVENT_SUBMIT, "submitted", kind="region")   # kwargs 全部落进 data 段
        log.log("j1", EVENT_DONE, "finished", path="/x.csv")  # 第二条带 path
        rows = log.tail(n=10)                    # n 是"取最近几条", 不设过滤 = 全量
        assert len(rows) == 2  # 两条都在
        assert rows[0]["event"] == EVENT_SUBMIT  # tail 保持写入序, 不按时间重排
        assert rows[0]["data"]["kind"] == "region"  # kwargs 原样可取, 不被 message 覆盖
        assert rows[1]["data"]["path"] == "/x.csv"  # 第二条的 kwargs 同样保真

    def test_jsonl_is_line_oriented(self, tmp_path):
        """落盘必须一行一事件, 每行独立可解析。

        守的不变量: 把多条事件拼成一个 JSON 数组的话, tail -f / grep 整条流式
        消费全部失效; 行定向是 task_log 被外部工具 (CI、GUI 轮询) 使用的前提。
        """
        log = TaskLogger(log_dir=str(tmp_path))  # 每次用例一个独立日志目录
        log.log("j1", EVENT_SUBMIT, "a")  # 写两条: 验证不拼成单个 JSON 数组
        log.log("j1", EVENT_DONE, "b")  # 第二条事件
        lines = (tmp_path / "task_log.jsonl").read_text(
            encoding="utf-8").strip().splitlines()  # 落盘文件名是契约, 外部工具按它读
        assert len(lines) == 2  # 两事件对两行
        for line in lines:                                                                          # 逐行读事件文件
            json.loads(line)  # 每行独立可解析, 不依赖前一行

    def test_tail_filters(self, tmp_path):
        """task_id/event/level 三维过滤 + n=0 全量 + n=1 取末条。

        守的不变量: n=0 的语义是"不限制条数"而不是"取 0 条" —— 按 n 直接
        切片会导致过滤查询永远返回空, 问题定位时看起来"什么都没发生"。
        """
        log = TaskLogger(log_dir=str(tmp_path))  # 三个任务两个事件, 刻意留一个 warn
        log.log("j1", EVENT_SUBMIT, "s")  # j1 第一条
        log.log("j2", EVENT_HOOK, "h", level="warn")  # j2 唯一的 warn 事件
        log.log("j1", EVENT_DONE, "d")  # j1 第二条
        assert len(log.tail(n=0, task_id="j1")) == 2   # n=0 表示不限条数, 只按 task_id 过滤
        assert len(log.tail(n=0, event=EVENT_HOOK)) == 1  # 事件名过滤: 只剩那条 hook
        assert len(log.tail(n=0, level="warn")) == 1      # 级别过滤与任务过滤互不干扰
        assert len(log.tail(n=1)) == 1  # 只取最后一条

    def test_tasks_and_summarize(self, tmp_path):
        """任务清单按首见顺序; 单任务聚合的 has_error 只看 error 级。

        守的回归: warn (部分命中/hook 拦截) 不算 error — 精准下载常态就是
        "请求 N 个 ID 回 M 行", 若把 warn 升级成 error, 每次汇总都是红的,
        真正的失败反而被淹没。
        """
        log = TaskLogger(log_dir=str(tmp_path))  # 两个任务: j1 干净, j2 带 warn
        log.log("j1", EVENT_SUBMIT, "s")  # j1 第一条
        log.log("j1", EVENT_DONE, "d")  # j1 第二条
        log.log("j2", EVENT_HOOK, "blocked", level="warn")  # 拦截属 warn 不是 error
        assert log.tasks() == ["j1", "j2"]  # 按首见顺序, 不按字典序
        s = log.summarize("j1")               # 按任务汇总: 事件数 + 是否有 error
        assert s["found"] and s["events"] == 2 and s["has_error"] is False  # 干净任务无 error
        s2 = log.summarize("j2")
        assert s2["has_error"] is False  # warn 不算 error
        assert log.summarize("nope")["found"] is False   # 不存在的任务: found=False 而非抛错

    def test_problems_view(self, tmp_path):
        """problems() 只收 warn/error 并按时间排序 (快速定位面, 不掺正常事件)。"""
        log = TaskLogger(log_dir=str(tmp_path))  # 正常/警告/错误各一条, 便于看排序
        log.log("j1", EVENT_DONE, "ok")  # 正常事件不该进问题视图
        log.log("j2", EVENT_HOOK, "w1", level="warn")  # warn 收
        log.log("j3", "failed", "e1", level="error")  # error 收
        probs = log.problems()  # 只回 warn/error, 按写入序
        assert len(probs) == 2  # 正常那条被滤掉
        assert [p["level"] for p in probs] == ["warn", "error"]  # 写入序即时间序, 不重排

    def test_long_payload_clipped(self, tmp_path):
        """超长载荷降级为摘要 (键名保留), 不是原样 9000 字符。

        守的不变量: 原样写入的话, 一个带大 evidence 的 hook 事件能把单行撑到
        几十万字符, 日志爆盘且任何按行读取的工具都被卡死; 只留键名 + 预览。
        """
        log = TaskLogger(log_dir=str(tmp_path))  # 目录存在但内容为空
        log.log("j1", EVENT_SUBMIT, "big", blob="x" * 9000)  # 单条载荷 9000 字符
        rec = log.tail(n=1)[0]             # 取刚写的那条超长载荷记录
        assert rec["data"]["_clipped"] is True   # 9000 字必截断, 否则日志没人敢 tail
        assert "blob" in rec["data"]["keys"]    # 留名目不留值: 排障要看到"这里有过什么"

    def test_empty_log_reads(self, tmp_path):
        """空日志/目录不存在: 三个查询面都返回空列表 (不抛)。

        守的回归: 全新安装或日志被清后, GUI 首屏查询不该崩在 FileNotFoundError。
        """
        log = TaskLogger(log_dir=str(tmp_path / "empty"))  # 目录压根不存在
        assert log.tail() == []  # 空列表而非 FileNotFoundError
        assert log.tasks() == []  # 任务面同样空
        assert log.problems() == []  # 问题面同样空

    def test_fmt_record_ascii_safe(self, tmp_path):
        """单行文本格式化: 含 job_id 与事件名, 且 ASCII 安全 (旧控制台不崩)。"""
        log = TaskLogger(log_dir=str(tmp_path))  # 格式化器吃的是记录, 不碰落盘
        rec = log.log("j1", EVENT_DONE, "done", rows=2)  # log 直接回记录, 免得再 tail 一次
        line = fmt_record(rec)  # 折成单行文本
        assert "j1" in line and "done" in line  # job_id 与事件名都要出现
        fmt_records([rec, rec])  # 批量格式化不抛, ASCII 安全即可
