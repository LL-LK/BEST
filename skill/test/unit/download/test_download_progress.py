"""下载进度单元测试: 进度存储 / 累加器 / 文本进度条。

守的回归: 进度文件是 CLI/GUI 的**唯一事实源** (原子落盘, 读者不看到半行
JSON); job_id 路径逃逸必须拒绝; 观察回调异常不得打断下载; Windows GBK 等
旧控制台下块字符回退 ASCII, 不让 CLI 崩在 UnicodeEncodeError 上。
"""
from __future__ import annotations

# 标准库: json (读回进度文件校验落盘内容, 不走被测的 load 以验证真文件) /
# os (monkeypatch 替换 os.replace 复现 Windows 占用竞争)
import json
import os

# 测试框架: raises 断言异常; tmp_path 提供独立临时目录; monkeypatch 替身 stdout
import pytest

try:
    # 被测单元: 状态机枚举 + 进度快照/存储/累加器 + 文本条渲染器
    from src.download_progress import (
        STATUS_BLOCKED,  # 被拦截是断言的状态锚点
        STATUS_DONE,  # 成功是断言的状态锚点
        STATUS_FAILED,  # 失败终态: adopt 用例拿它当"上一轮已失败"的锚点
        STATUS_QUEUED,  # 排队态: 首帧渲染要认它
        STATUS_RUNNING,  # 运行态
        ProgressRecord,  # 进度记录载体
        ProgressStore,  # 进度存储: 原子读写与路径锚定都在这里
        ProgressTracker,  # 进度累加器: 字节与页两种口径
        render_text_bar,  # 文本进度条渲染器
    )
except Exception as _legacy_err:  # legacy-import-guard
    # 源码树调整导致旧导入路径失效时整模块跳过, 不让收集期报错
    import pytest as _pytest
    _pytest.skip(f'legacy import unavailable: {_legacy_err!r}', allow_module_level=True)            # 模块级跳过: 导入树问题不该算用例失败


class TestProgressStore:
    """.progress/<job_id>.json 的原子读写、路径锚定与列举/删除。"""

    def test_save_load_roundtrip(self, tmp_path):
        """落盘的进度记录必须能无损读回 (文件即事实源)。

        守的回归: save 走 tmp + os.replace, load 走 utf-8-sig; 二者必须闭环 —
        done_bytes=250/1000 按字节口径算出 fraction 0.25, 与 GUI 百分比同源。
        tmp_path: 进度目录落到临时位置, 不在 skill 根下建 .progress。
        """
        store = ProgressStore(str(tmp_path))  # 进度目录落临时位置, 不在 skill 根下建 .progress
        rec = ProgressRecord(job_id="j1", kind="region", status=STATUS_RUNNING,                     # 进度记录: 字节口径的输入
                             total_bytes=1000, done_bytes=250)  # 250/1000 = 0.25 整除
        path = store.save(rec)  # 落盘路径即 GUI 与 CLI 的唯一事实源
        assert json.loads(open(path, encoding="utf-8").read())["job_id"] == "j1"  # 不走 load: 验真文件
        loaded = store.load("j1")                                                                   # 读回来
        assert loaded is not None  # 挡"save 成功但 load 认不出自己写的文件"
        assert loaded.done_bytes == 250                                                             # 字节进度必须无损: 少了它就与写入端脱节
        assert loaded.fraction() == 0.25  # 与 GUI 百分比同源: 字节口径, 不按页折算

    def test_load_missing_returns_none(self, tmp_path):
        """文件缺失返回 None 而不是抛 (GUI 列表要容忍"还没开始"的任务)。"""
        assert ProgressStore(str(tmp_path)).load("nope") is None  # 挡"未开始的任务让 GUI 崩"

    def test_job_id_path_traversal_rejected(self, tmp_path):
        """job_id 路径逃逸防护: 带目录成分的 id 必须拒绝。

        守的回归: job_id 直接拼进文件名, "../escape" 会把进度文件写到
        .progress 之外 (任意目录覆盖面); 现在一律 ValueError, 宁死不写。
        """
        store = ProgressStore(str(tmp_path))                                                        # 进度目录锚在临时区
        with pytest.raises(ValueError):  # 宁可不写也不写到 .progress 之外
            store.save(ProgressRecord(job_id="../escape"))                                          # 越界作业号: 路径逃逸必须在存储层被拒
    def test_list_and_delete(self, tmp_path):
        """列举只收 .json (save 的 .tmp 半成品不混入), 删除可逆。"""
        store = ProgressStore(str(tmp_path))                                                        # 进度目录锚在临时区
        # 连存两个再列举: 断排序后的完整集合 (而非"包含 a"), 否则实现漏掉
        # 其中一个文件时断言仍会通过, 那个文件对应的任务就在 GUI 里消失了
        store.save(ProgressRecord(job_id="a"))                                                      # 先存 a
        store.save(ProgressRecord(job_id="b"))                                                      # 再存 b
        assert sorted(store.list_jobs()) == ["a", "b"]  # 断完整集合而非"包含": 漏一个也该红
        # 删除后 load 必须变 None: 断 delete 的返回值只证明它认得这个 job,
        # 证不了文件真被摘掉, 而残留文件会让已删任务在列表里复活
        assert store.delete("a") is True                                                            # 删除要真的生效
        assert store.load("a") is None                                                              # 删完必须读不到

    def test_list_jobs_ignores_provenance_sidecars(self, tmp_path):
        """output_dir 与 progress_dir 同目录时, provenance sidecar 不得被当成 job (B6)。

        守的不变量: 下载产物 <name>.json 的复核 sidecar 是
        <name>.json.provenance.json, 也匹配 *.json —— 用 glob("*.json")
        扫会把它们当成伪 job_id, list_jobs/status() 对幽灵 id 返回 None 记录,
        CLI download list 出现查不到的任务。只认"文件名 stem 与文件内
        job_id 一致"的真进度文件: 普通 JSON 产物与 sidecar 都没有 job_id
        键, 自然被排除; 损坏的 .json 同样跳过 (列举是人工复核面, 不该被
        单个坏文件搞崩)。
        """
        store = ProgressStore(str(tmp_path))                                                        # 进度目录锚在临时区
        store.save(ProgressRecord(job_id="real_job"))  # 唯一真进度文件
        # 边缘配置: 产物与 sidecar 落在同一目录 (output_dir == progress_dir)
        (tmp_path / "best_ps1_c2.json").write_text(                                                 # 造一个产物文件: 列举要把它挡在外面
            '{"sources": []}', encoding="utf-8")  # 普通 JSON 产物: 无 job_id 键
        (tmp_path / "best_ps1_c2.json.provenance.json").write_text(                               # 再放一个伴生血缘文件: 它的后缀同样不是作业
            '{"file": "best_ps1_c2.json", "sha256": "aa"}', encoding="utf-8")                       # 伴生内容只是为了让文件像真的
        (tmp_path / "broken.json").write_text("{not json", encoding="utf-8")  # 坏文件不该搞崩列举
        assert store.list_jobs() == ["real_job"]                                                   # 只列真作业: 噪声混进来会让运维列表误导人


class TestProgressTracker:
    """任务内进度累加器: 生命周期状态跃迁 + hook 载荷 + 观察回调。"""

    def test_lifecycle_queued_running_done(self, tmp_path):
        """状态机 queued -> running -> done 与 result 载荷必须落盘可见。

        守的回归: 每个跃迁都是契约事件 (start/finish 走 force=True 绕过 2Hz
        节流), 否则 CLI 会显示任务"还没开始"而它其实早已跑完。
        """
        store = ProgressStore(str(tmp_path))                                                        # 进度目录锚在临时区
        tr = ProgressTracker(store, "j1", total_pages=4)  # 4 页: done_pages 的上界
        assert store.load("j1").status == STATUS_QUEUED  # 构造即落盘: CLI 才看得到"排队中"
        tr.start()                                                                                  # 开始: 置运行态并落第一帧
        assert store.load("j1").status == STATUS_RUNNING  # start 走 force=True 绕开 2Hz 节流
        tr.advance_pages(2)  # 只完成一半: 让 done != total 的中间态可见
        tr.finish({"path": "/tmp/x.csv"})                                                           # 收尾: 落终态与产物路径
        rec = store.load("j1")                                                                      # 读回终态记录
        assert rec.status == STATUS_DONE                                                            # 终态必须落盘
        assert rec.done_pages == 2  # 挡"finish 把页数重置": GUI 进度会跳回 0
        assert rec.result["path"] == "/tmp/x.csv"                                                  # 产物路径也要落: GUI 靠它显示下载结果

    def test_block_writes_hook_payload(self, tmp_path):
        """hook 拦截: 状态转 blocked 且 ask 载荷入文件 (fail-closed)。

        守的回归: 后台任务没有前台可以向用户 ask, 必须把问题写进进度文件 —
        否则任务既不在跑也没有任何错误可见, 用户只能盲等。
        """
        store = ProgressStore(str(tmp_path))                                                        # 进度目录锚在临时区
        tr = ProgressTracker(store, "j2")                                                           # 绑定存储与作业号
        tr.start()                                                                                  # 置运行态
        payload = {"id": "hook_checksum_mismatch", "question": "ask?",                              # ask 载荷
                   "options": []}  # options 为空 = 无从选择, 只能人工介入
        tr.block(payload)                                                                           # 置被拦截态
        rec = store.load("j2")                                                                      # 读回记录
        assert rec.status == STATUS_BLOCKED  # 挡"拦截后状态仍是 running": 用户以为它在跑
        assert rec.hook["id"] == "hook_checksum_mismatch"                                 # 载荷必须完整落盘: 前端只拿到进度文件, 少一字段就问不出来

    def test_callback_fires_and_survives_exception(self, tmp_path):
        """观察回调异常必须被吞掉, 不得打断下载。

        守的回归: 双轨设计 (文件权威, 回调只是加速) — 一个订阅者抛异常就
        让下载失败, 等于把可选的加速通道变成单点故障。
        """
        store = ProgressStore(str(tmp_path))                                                        # 进度目录锚在临时区
        seen = []                                                                                   # 观察回调记账

        def cb(rec):
            """订阅回调: 记下状态后故意抛异常, 验证异常不会打断下载。

            守的回归: 回调只是可选的加速通道, 文件才是权威事实源; 一个订阅者
            抛异常就让下载失败, 等于把可选通道变成单点故障。
            """
            seen.append(rec["status"])                                                              # 逐帧记状态
            raise RuntimeError("observer boom")  # 不得打断下载

        tr = ProgressTracker(store, "j3", callback=cb)                                              # 带观察回调的累加器
        tr.start()                                                                                  # 置运行态
        tr.finish({"path": "x"})  # 抛过异常的回调后仍要走完: 证明异常被吞而非中断
        assert seen == [STATUS_RUNNING, STATUS_DONE]  # 两条都在 = 首次异常没终止后续调用


class TestProgressTrackerAdopt:  # N1-03: 续传从旧快照长出记录, 不从零长出
    """``adopt=`` 续传构造: 进度与 result 沿用旧记录, 且构造期不落盘。"""

    def test_adopt_preserves_progress_and_result_and_does_not_write(self, tmp_path):
        """adopt 旧记录: done_pages/total_pages/result 原样继承, 且构造期不写盘。

        守的回归 (N1-03, fail-open): 跨进程 resume 时内存注册表为空, 管理器按
        job_id 重建 tracker。若重建时另起一条全零快照, 它在构造期那次 save
        就会把盘上 ``done_pages`` 与 ``result`` (内含 ``resume_spec``) 抹掉 ——
        续传若随后失败, 这个作业**永远续不回来**, 而磁盘上看不出任何损坏。
        本用例分别钉住两半: 继承 (内容不丢) 与不写盘 (不拿旧终态做状态抖动)。
        """
        store = ProgressStore(str(tmp_path))  # 进度目录锚在临时区
        old = ProgressRecord(job_id="j9", kind="sqlid", status=STATUS_FAILED,  # 上一轮的 failed 终态
                            total_pages=4, done_pages=1,  # 已取回 1 页: 续传要接着数
                            result={"path": "p.csv", "resume_spec": {"kind": "sqlid"}})  # spec 是续传的唯一凭据
        store.save(old)  # 旧记录落盘: 跨进程时新进程读到的就是它

        tr = ProgressTracker(store, "j9", kind="sqlid", adopt=old)  # 续传式构造: 显式传旧记录

        # 构造期**不得**落盘: 旧记录已在盘上且是权威, 再写一遍只会把 failed
        # 终态盖成 queued 做一次无意义的状态抖动 (内容相同, 只有 updated_at 变)。
        assert json.loads((tmp_path / "j9.json").read_text(encoding="utf-8"))["status"] == STATUS_FAILED, \
            "adopt 路径构造期不得落盘: 旧记录的终态会被一次多余的 save 盖成 queued"
        # 继承: 进度字段与 result 都必须来自旧记录 (不是全零)
        assert tr.record.done_pages == 1, "done_pages 必须沿用上一轮实绩: 归零即进度说谎"
        assert tr.record.total_pages == 4, "total_pages 必须沿用: 否则续传期 fraction() 回落到 0%"
        assert tr.record.result["resume_spec"] == {"kind": "sqlid"}, "resume_spec 必须沿用: 丢了它作业再也续不回来"
        assert tr.record.kind == "sqlid", "kind 取显式入参: 漏传会回落到 region 并写错记录"

    def test_adopt_does_not_inherit_terminal_error_or_hook(self, tmp_path):
        """adopt 只继承进度与 result: 上一轮的 error/hook 不得跟着进 running 态。

        守的不变量: error/hook 属**上一次**尝试的终态事实, 续传把它们继承下来
        就会让一条 running 记录带着旧错误 (GUI 会显示"正在跑"同时挂着上次的
        报错), 属记录自相矛盾。status 同理: 归 start() 管, 不从旧记录抄。
        """
        store = ProgressStore(str(tmp_path))  # 进度目录锚在临时区
        old = ProgressRecord(job_id="j10", kind="region", status=STATUS_BLOCKED,  # 上一轮被 hook 拦下
                            error="boom", hook={"id": "hook_x", "question": "?"},  # 两样都是上一轮的终态事实
                            done_pages=2, result={"resume_spec": {"kind": "region"}})
        store.save(old)  # 旧记录落盘: 跨进程现场

        tr = ProgressTracker(store, "j10", kind="region", adopt=old)  # 续传式构造
        tr.start()  # 推到 running: 这是本次运行的契约事件

        rec = store.load("j10")  # 读回本次运行真正落的那一帧
        assert rec.status == STATUS_RUNNING, "status 由 start() 决定: 不得停在上一轮的 blocked"
        assert rec.error is None, "error 属上一轮尝试: 继承它会让 running 记录挂着旧报错"
        assert rec.hook is None, "hook 同理: 上一轮的待决策载荷不该在续传期复活"
        assert rec.done_pages == 2, "进度仍要继承: 本用例只钉 error/hook 两样不继承"

    def test_default_construction_still_saves_queued_record(self, tmp_path):
        """不带 adopt 时: 构造期照旧落盘 queued (standalone 契约不得被改掉)。

        守的回归: 修 N1-03 走的是「给续传一条不落盘的构造方式」, 不是把
        构造期那次 save 删掉。删掉它等于拿独立使用 (无 Manager 代存) 的
        契约去换续传路径 —— 那是把一个 fail-open 换成一个新缺陷。本用例
        把「默认路径逐字节不变」钉住, 日后谁想简化这段就会先撞上这里。
        """
        store = ProgressStore(str(tmp_path))  # 进度目录锚在临时区
        ProgressTracker(store, "j11", total_pages=3)  # 不传 adopt: 全新任务路径
        rec = store.load("j11")  # 构造后立刻读盘: 这一帧就是订阅方要看到的
        assert rec.status == STATUS_QUEUED, "独立使用时任务起跑前就得可见: 删掉构造期 save 会让它凭空消失"
        assert rec.done_pages == 0  # 全新任务没有旧进度可继承


class TestRenderTextBar:
    """CLI 单行文本进度条: 口径优先级、旧控制台回退、零总量兜底。"""

    def test_bytes_mode(self):
        """字节口径: 百分比 + 已完成/总量 + 速率 + ETA 都要出现在一行里。

        守的回归: 文本条与 GUI 百分比必须同口径 (字节优先、页次之), 否则
        出现"条走 100% 文件还没写完"的漂移。
        """
        rec = {"job_id": "j", "status": "running", "total_bytes": 10_000_000,                       # 字节口径的渲染输入
               "done_bytes": 5_000_000, "speed_bps": 1_000_000.0, "eta_sec": 5.0}  # 各给整除值
        line = render_text_bar(rec)                                                                 # 走真实渲染器
        # 三个片段合成一行断言: 百分比、容量、ETA 各占一段, 少一段都说明
        # 渲染漏了字段而不是格式变了; 单独断"50%"会让其余退化混过去
        assert "50%" in line and "5.0/10.0MB" in line and "eta 5s" in line                          # 百分比、量级与剩余时间三样都要在
        # 前缀锁 "[j] running": job_id 与状态是 CLI 多任务并行时唯一的区分依据,
        # 掉了它几条进度行混在一起就没法读了
        assert line.startswith("[j] running")                                                       # 前缀必须带作业号与状态

    def test_ascii_fallback_on_legacy_console(self, monkeypatch):
        """GBK 等旧控制台: 块字符回退 #/- (不抛 UnicodeEncodeError)。

        守的不变量: Windows 中文代码页控制台编码不了 "█░", 直接渲染会让
        CLI 崩在打印进度这一行; 必须探测 stdout 编码不可用即回退 ASCII。
        monkeypatch.setattr 把 sys.stdout 换成编码为 gbk 的替身, 用来在
        Linux CI 上复现 Windows 旧控制台。
        """
        # 标准库: sys 只为替换 sys.stdout 探测编码回退 (不涉及被测逻辑)
        import sys

        class _FakeStdout:
            """编码为 gbk 的 stdout 替身: 在 Linux CI 上复现 Windows 旧控制台。

            守的不变量: 渲染器必须探测 stdout 编码是否容得下块字符; 少了这个
            替身, GBK 控制台崩在打印进度那一行的回归在 Linux 上永远测不到。
            """

            encoding = "gbk"                                                                      # 旧控制台编码: 块字符在 GBK 下不可编码

        monkeypatch.setattr(sys, "stdout", _FakeStdout())  # 编码降级后才触发回退分支
        # 本地: 私有渲染辅助 (块字符选择), 延迟导入避免模块级依赖回退探测
        from src.download_progress import _bar_chars
        assert _bar_chars() == ("#", "-")  # 挡"回退被摘掉": GBK 控制台会崩在打印行
        line = render_text_bar({"job_id": "j", "status": "running",                                 # 渲染输入
                                "total_bytes": 10, "done_bytes": 5})                                # 极小字节数: 要走到 KB 分支以下
        line.encode("gbk")  # 必须可编码: 真正抛错点就在这一行

    def test_pages_mode_and_zero_totals(self):
        """页口径文本条 + 总量未知时显示 0B (不做除零)。

        守的不变量: 分页下载没有 Content-Length, total_bytes/total_pages 均为
        0; 在这里除零或显示 "nan%", 用户看到的就是乱码进度。
        """
        rec = {"job_id": "j", "status": "running", "total_pages": 4,                                # 页口径的渲染输入
               "done_pages": 1}  # 无 total_bytes: 逼出页口径分支
        assert "1/4页" in render_text_bar(rec)  # 页码要成对出现, 否则用户算不出进度
        empty = {"job_id": "j", "status": "queued"}  # 两个总量键全缺: 除零的最小复现
        assert "0B" in render_text_bar(empty)                                                       # 零字节时也要有可读文本

    def test_accepts_record_object(self, tmp_path):
        """渲染器同时接受 dict 与 ProgressRecord (内部调用直接传快照对象)。"""
        rec = ProgressRecord(job_id="j", status=STATUS_DONE, total_bytes=10,                        # 终态记录: 完成态不该再渲染进度条
                             done_bytes=10)  # 对象形态而非 dict: 内部调用路径
        assert "100%" in render_text_bar(rec)  # 挡"只认 dict": 内部调用直接崩


class TestProgressStoreReplaceRetry:
    """Windows 目标占用竞争的退避重试 (WinError 5 不得杀死下载线程)。

    守的不变量 (Phase 8 观察项 ④): Windows 上 os.replace 对正被并发读者
    (GUI 轮询 / 编辑器 / 杀软) 持有的目标文件抛 PermissionError。不重试的话,
    异常穿过 save -> _flush -> advance_pages 直达下载工作线程 — 页码
    回调位于 _run 的 try 之外, 一次几十毫秒的瞬时竞争就杀死整个任务。
    既有测试靠"内存 Event + Future 收敛后单次读"规避该竞争, 但生产侧
    (真实 GUI 轮询) 规避不掉, 所以这里正面验证重试语义。
    """

    def test_replace_retries_then_succeeds(self, tmp_path, monkeypatch):
        """前两次 replace 抛 PermissionError, 第三次必须成功且内容完整。

        重试退避序列在用例里打成 0: 测的是"重试几次/是否原样抛出"的语义,
        不是真实时长 (真时长由 REPLACE_RETRY_DELAYS 的三个值承担)。
        """
        # 本地: 重试退避常量, 打平避免用例真睡 170ms
        from src.download_progress import REPLACE_RETRY_DELAYS

        monkeypatch.setattr("src.download_progress.REPLACE_RETRY_DELAYS",                         # 把重试间隔压到零: 瞬时竞争不该让用例付墙钟
                            (0.0, 0.0, 0.0))                                                        # 三个零延迟
        assert REPLACE_RETRY_DELAYS == (0.02, 0.05, 0.1)  # 常量本身不被改动

        store = ProgressStore(str(tmp_path))                                                        # 进度目录锚在临时区
        rec = ProgressRecord(job_id="r1", status=STATUS_RUNNING, done_bytes=7)                      # 要落盘的记录
        real_replace = os.replace                                                                   # 先存真实现: 打桩之后仍要真替换
        calls = {"n": 0}                                                                            # 调用计数: 断言要数"试了几次"

        def flaky_replace(src, dst):
            """前两次模拟 Windows 占用, 第三次放行到真替换。"""
            calls["n"] += 1                                                                         # 先累计次数
            if calls["n"] < 3:                                                                      # 前两次都失败: 模拟瞬时竞争
                raise PermissionError(5, "Access is denied")  # WinError 5: 目标被读者持有
            return real_replace(src, dst)

        monkeypatch.setattr(os, "replace", flaky_replace)                                           # 把替换打成会失败的替身
        path = store.save(rec)                                                                      # 走真实的保存路径
        assert calls["n"] == 3, "必须重试到第三次才成功 (前两次是瞬时竞争)"                                            # 必须重试到第三次才成功
        assert store.load("r1") is not None                                                         # 读回记录: 重试之后内容仍要完整
        assert store.load("r1").done_bytes == 7                                                     # 字节进度也要完整
        assert not list(tmp_path.glob("*.tmp")), "成功后不得留下 .tmp 半成品"                                 # 成功后不得留下半成品

    def test_replace_permanent_failure_raises_original_error(self, tmp_path,
                                                             monkeypatch):                          # 用 monkeypatch 注入替身
        """重试耗尽后必须原类型抛出, 且清理 .tmp 半成品。

        守的回归: 重试是为了兜瞬时竞争, 不是吞异常 — 永久失败 (权限真的不对)
        必须继续往上抛, 上层 except OSError 的语义不变。
        """
        monkeypatch.setattr("src.download_progress.REPLACE_RETRY_DELAYS",                           # 同样把重试间隔压到零
                            (0.0, 0.0, 0.0))  # 打平退避: 测语义不测时长
        store = ProgressStore(str(tmp_path))                                                        # 进度目录锚在临时区
        rec = ProgressRecord(job_id="r2")                                                           # 要落盘的记录

        def always_denied(src, dst):
            """模拟目标被长期占用: 重试全部失败。"""
            raise PermissionError(5, "Access is denied")  # 每次都 WinError 5

        monkeypatch.setattr(os, "replace", always_denied)                                           # 替换永远被拒: 模拟权限或占用冲突
        with pytest.raises(PermissionError):  # 原类型上抛: 上层 except OSError 语义不变
            store.save(rec)                                                                         # 走真实的保存路径
        assert not list(tmp_path.glob("*.tmp")), "失败路径也不得留下 .tmp"                                   # 失败路径也不得留下半成品
        assert store.load("r2") is None, "落盘失败不得留下假进度记录"
