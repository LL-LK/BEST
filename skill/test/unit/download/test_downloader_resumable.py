"""BestDownloader 断点续传单元测试 (checkpoint 驱动的页级恢复)。

守的回归: 每页成功后必须落 checkpoint (崩溃后能从断点页继续而不是从第 1 页
重下); 续传要把 checkpoint 里的 initial_sources 注入首轮结果, 最终文件是两
次的并集; 成功后 checkpoint 必须删除 (不泄漏); 无 checkpoint 时 resume_job
抛 FileNotFoundError 而不是静默重下。
"""
from __future__ import annotations

# 标准库: json (读回 JSON 产物校验结构) / pathlib 落盘路径断言
import json
from pathlib import Path

# 标准库: patch 替换 BestClient 的取数方法, 模拟协议阶段与失败点
from unittest.mock import Mock, patch

# 测试框架: raises 断言异常; tmp_path 提供每次用例独立的临时目录
import pytest

# 本地: 生产客户端 (downloader 的 HTTP 依赖, rate_limit=0 关掉礼貌限流)
from src.client import BestClient
from src.download_sqlid import SqlidExpiredError

# 本地: 被测单元 — 下载器 (resumable 分页 + checkpoint 读写的权威实现) / 过期异常
from src.downloader import BestDownloader

# 本地: 数据模型 — 查询结果载体 / 单个源 / 约束对象
from src.models import BestQueryResult, BestSource, ColumnConstraint

# 本地: 断点检查点管理器 (原子写 + 路径锚定, job 级状态持久化)
from src.scripts.checkpoint import DownloadCheckpoint


class TestResumableDownloader:
    """基于 checkpoint 的断点续传测试套件。"""

    def test_checkpoint_atomic_write_and_cleanup(self, tmp_path):
        """Rule 12 防线二: checkpoint 原子替换, .tmp 不得残留。

        守的回归: 直接写目标文件会让崩溃现场留下半个 JSON, 下次 load 拿到
        损坏状态; tmp + os.replace 保证读者只看到旧完整版或新完整版。
        """
        ckpt_dir = tmp_path / "checkpoints"                                                         # 断点目录锚在临时区
        ckpt = DownloadCheckpoint(str(ckpt_dir))                                                    # 构造断点存储

        job_id = "test_job_atomic_01"                                                               # 显式作业号: 原子写这条与业务无关
        saved_file = ckpt.save(job_id, {"page": 1, "sources": [{"source_id": "S1"}]})               # 带页号与源列表: 续传要靠这两样恢复现场
        assert Path(saved_file).is_file()  # 真文件落盘, 不看返回值语义

        # 原子写的 .tmp 半成品不得残留在磁盘上 (否则 glob/list 会把它当产物)
        tmp_file = Path(saved_file).parent / f"{Path(saved_file).name}.tmp"                        # 按约定拼出临时文件名: 残留就说明清理没做
        assert not tmp_file.exists()  # 挡"tmp+replace 被简化成直写目标文件"

        loaded = ckpt.load(job_id)                                                                  # 读回来
        assert loaded is not None  # 挡"写得进去读不回来": 续传入口直接失效
        assert loaded["page"] == 1  # 断点页号是续传起点, 错位即重头再下一遍
        assert loaded["sources"][0]["source_id"] == "S1"  # 源列表也必须完整落盘

        # 删除后必须读不到 (删除是续传生命周期的收尾, 不能只返回 True)
        assert ckpt.delete(job_id) is True                                                          # 删除必须真的生效
        assert ckpt.load(job_id) is None  # 挡"只返回 True 不真删": 下次 resume 拿到旧断点

    def test_download_sqlid_resumable_saves_checkpoint_per_page(self, tmp_path):
        """第 2 页断流: checkpoint 必须已含第 1 页的数据 (next_page=2)。

        守的不变量: 只在全部下完才写检查点的话, 大任务中途崩掉等于全丢;
        必须每页成功后落盘, 断点就是"下一页"。side_effect 模拟协议阶段: 第 1 页
        正常回调 on_page_fetched, 随后抛 RuntimeError 模拟网络掉线。
        """
        client = BestClient(rate_limit=0)  # 关礼貌限流: 用例只验 checkpoint, 不想等 sleep
        out_dir = tmp_path / "data"                                                                 # 产物目录锚在临时区
        ckpt_dir = tmp_path / "checkpoints"                                                         # 断点目录锚在临时区
        dl = BestDownloader(client, output_dir=str(out_dir), checkpoint_dir=str(ckpt_dir))        # 两个目录都显式给: 默认值是 CWD 相对的

        job_id = "job_partial_sqlid"                                                                # 作业号显式给: 断点键由它派生

        # 替身: 第 1 页正常回调 on_page_fetched, 第 2 页抛错模拟网络掉线
        def mock_fetch(sqlid, **kwargs):
            """第 1 页回调后抛 RuntimeError, 制造"下一页断流"的崩溃现场。

            守的回归: checkpoint 必须在每页成功后立刻落盘; 若只在全部下完才
            写, 这个替身一炸就什么都留不下, "断点就是下一页"这条契约无从验证。
            """
            on_page = kwargs.get("on_page_fetched")                                                 # 取出页回调: 断点就是靠它落盘
            if on_page:                                                                             # 回调可能缺席, 显式判一次
                src1 = BestSource(source_id="S101", ra=180.0, dec=30.0, magnitudes={"r": 15.0})     # 第一页的源: 断流前唯一落盘的页
                on_page(1, [src1])  # 回调即"第 1 页已成功": 此时必须已落盘
            raise RuntimeError("Simulated network drop on page 2")

        with patch.object(client, "_fetch_sqlid_data", side_effect=mock_fetch):                     # 打桩在取数层
            with pytest.raises(RuntimeError, match="Simulated network drop"):                       # 断流必须冒泡: 被吞掉就构造不出中断
                dl.download_sqlid("s1001", job_id=job_id, resumable=True)                           # 带作业号与可续标记: 断点键才有得派生

        # 断流后 checkpoint 必须还在磁盘上, 且已含第 1 页的进度
        state = dl.checkpoint.load(job_id)                                                          # 读回断点: 续传的唯一事实源
        assert state is not None  # 崩了就全丢 = 续传名存实亡
        assert state["sqlid"] == "s1001"  # 断点要认得出自己属于哪个 sqlid 会话
        assert state["next_page"] == 2  # 断点就是"下一页": 写成 1 会重下已完成的页
        assert len(state["sources"]) == 1                                                     # 断点里恰好一条: 第 2 页没落盘就该只有第 1 页
        assert state["sources"][0]["source_id"] == "S101"  # 源数据随断点一起落盘

    def test_download_sqlid_resumes_from_checkpoint_and_cleans_up(self, tmp_path):
        """预置 checkpoint 在第 2 页: 续传从 start_page=2 起, 两页源并集落盘。

        守的回归: initial_sources 必须从 checkpoint 注入 (否则最终文件只剩第
        2 页, 第 1 页数据静默丢失); 成功后 checkpoint 必须删除, 否则下次
        resume 又拿到同一份断点, 磁盘上永久留垃圾。
        """
        client = BestClient(rate_limit=0)                                                           # 限流置 0
        out_dir = tmp_path / "data"                                                                 # 产物目录锚在临时区
        ckpt_dir = tmp_path / "checkpoints"                                                         # 断点目录锚在临时区
        dl = BestDownloader(client, output_dir=str(out_dir), checkpoint_dir=str(ckpt_dir))          # 两个目录都显式给

        job_id = "job_resumed_sqlid"                                                                # 作业号显式给
        # 预置 checkpoint, 伪装成"第 1 页已经下完"的续传现场
        dl.checkpoint.save(job_id, {                                                                # 预置一个断点: 续跑要接着它往下取
            "job_id": job_id,
            "sqlid": "s2002",
            "catalog": "ps1",
            "next_page": 2,
            "sources": [{"source_id": "S101", "ra": 180.0, "dec": 30.0, "magnitudes": {"r": 15.0}}],
            "output_format": "csv",
            "output_file": "final_output.csv",
            # 步长/上限必存 (A3-01): phase-2 是偏移翻页, next_page 脱离 page_size
            # 就没有意义 —— 这里刻意给 250 而非缺省 1000, 让下面的断言能分辨
            # "从断点复原" 与 "回落缺省" 两种实现
            "page_size": 250,
            "max_rows": 50000,
        })

        # 替身: 记录 start_page 与 initial_sources, 验证续传真的从第 2 页起
        recorded_kwargs = {}                                                                     # 逐次记账: 断言要看的是"续跑时带了什么参数"

        def mock_fetch(sqlid, **kwargs):
            """把续传入口收到的参数原样记下, 并拼出"已抓源 + 本页新源"的结果。

            守的回归: start_page 必须是 2 且 initial_sources 必须带上检查点
            里的第 1 页 — 少了后者, 最终文件只剩第 2 页, 第 1 页数据静默丢失
            且全程无报错。
            """
            # 记录续传入口实际收到的参数: 起点页与已抓源列表
            recorded_kwargs.update(kwargs)                                                          # 把实参收下来供断言
            initial = kwargs.get("initial_sources", [])                                             # 首轮已取到的源: 续跑结果必须是两轮并集
            # 协议阶段: 第二阶段从 start_page 开始返回"本页"新源
            src2 = BestSource(source_id="S202", ra=180.5, dec=30.5, magnitudes={"r": 16.0})         # 第二轮的源
            all_srcs = list(initial) + [src2]  # 并集: 检查点旧源 + 本页新源
            return BestQueryResult(success=True, sources=all_srcs, total_count=len(all_srcs))

        with patch.object(client, "_fetch_sqlid_data", side_effect=mock_fetch):                     # 打桩在取数层
            saved_path = dl.download_sqlid("s2002", output_file="final_output.csv", job_id=job_id, resumable=True)  # 显式给输出名: 续跑必须落回同一个文件

        assert Path(saved_path).is_file()  # 产物真落盘, 不只看返回值
        assert recorded_kwargs["start_page"] == 2  # 挡"仍从第 1 页重下": 白跑一遍
        assert recorded_kwargs["page_size"] == 250  # 步长必须取自断点: 偏移翻页下用缺省 1000 会跳过整段行 (A3-01)
        assert len(recorded_kwargs["initial_sources"]) == 1  # 第 1 页源必须注入进来

        # 最终产物必须同时含 S101 (来自 checkpoint) 与 S202 (来自第 2 页)
        content = Path(saved_path).read_text(encoding="utf-8")                                      # 回读落盘字节: 两次的并集只能从盘上验
        assert "S101" in content  # 少了它: 第 1 页数据静默丢失且不报错
        assert "S202" in content  # 少了它: 本页结果没落盘

        # 成功后 checkpoint 必须删除 (不删会泄漏, 且下次 resume 拿到同一断点)
        assert dl.checkpoint.load(job_id) is None  # 挡"成功后忘删": 永久留垃圾断点

    def test_resume_job_method(self, tmp_path):
        """resume_job 编排: 无 checkpoint 抛 FileNotFoundError, 有则按状态恢复。

        守的不变量: 找不到检查点时若静默从第 1 页重下, 用户以为在续传,
        实际白下了半小时; 必须显式失败, 调用方改走重新提交。
        """
        client = BestClient(rate_limit=0)  # 关礼貌限流: 只验编排, 不真的分页取数
        dl = BestDownloader(client, output_dir=str(tmp_path / "data"), checkpoint_dir=str(tmp_path / "ckpts"))  # 两个目录都显式给: 默认值是 CWD 相对的

        # 无 checkpoint 时必须显式 FileNotFoundError, 不许静默从第 1 页重下
        with pytest.raises(FileNotFoundError, match="No resumable checkpoint found"):               # 无断点时必须抛错, 而不是静默从头重下
            dl.resume_job("non_existent_id")  # 静默重下 = 用户以为在续传, 实际白跑

        # 有 checkpoint 时就按状态恢复, 不再重新建查询
        dl.checkpoint.save("job_resume_api", {                                                      # 预置断点: 公共续传入口要靠它恢复参数
            "sqlid": "s3003",  # 已有会话号: 恢复路径不得再走 phase-1
            "catalog": "scr_lamost",                                                               # 星表参数要落进断点: 续跑才知道去取哪张表
            "output_format": "json",                                                                # 输出格式同样要落
            "output_file": "resumed_api.json",                                                      # 输出名同样要落: 否则续跑会另起一个文件
        })

        mock_res = BestQueryResult(                                                                 # 先造一个成功结果
            success=True,                                                                           # 成功标志
            sources=[BestSource(source_id="STD_01", ra=120.0, dec=20.0)],                           # 单源: 续跑结果的最小输入
            total_count=1,                                                                          # 总数与返回数
        )
        with patch.object(client, "_fetch_sqlid_data", return_value=mock_res):                      # 打桩在取数层
            # 协议阶段: 第二阶段直接按 sqlid 分页取数 (不再重新 POST 建查询)
            out = dl.resume_job("job_resume_api")                                                  # 走公共续传入口: 断点里的参数就是它的输入
            assert Path(out).is_file()  # 产物真落盘: 恢复路径也要走完整写出
            data = json.loads(Path(out).read_text(encoding="utf-8"))                                # 回读 JSON 产物
            assert data["sources"][0]["source_id"] == "STD_01"  # 断点里的星表与格式都生效

    def test_download_region_resumable_integration(self, tmp_path):
        """区域查询也能断点续传: 两阶段协议 + 成功后 checkpoint 清空。

        守的不变量: 只有 sqlid 路径支持 resumable 的话, 区域查询 (最常用的
        入口) 中途崩掉必须整轮重来。side_effect/return_value 模拟协议阶段:
        第一阶段 _submit_query_for_sqlid 返回新 sqlid, 第二阶段 _fetch_sqlid_data
        分页取数。
        """
        client = BestClient(rate_limit=0)  # 关礼貌限流: 两阶段都被桩掉, 不会真发请求
        dl = BestDownloader(client, output_dir=str(tmp_path / "data"), checkpoint_dir=str(tmp_path / "ckpts"))  # 两个目录都显式给

        # 替身: 第一阶段 _submit_query_for_sqlid 返回新 sqlid, 第二阶段取数
        with patch.object(client, "_submit_query_for_sqlid", return_value=("s4004", None)), \
             patch.object(client, "_fetch_sqlid_data") as mock_fetch:                               # 打桩取数层
            # 协议阶段: 第二阶段取数成功 (单源结果, 一页即完)
            mock_fetch.return_value = BestQueryResult(                                              # 先造一个成功结果
                success=True,                                                                       # 成功标志
                sources=[BestSource(source_id="REG_01", ra=150.0, dec=10.0)],                       # 单源
                total_count=1,                                                                      # 总数与返回数
            )
            saved = dl.download_region(                                                             # 走真实的区域下载入口
                ra_center=150.0,                                                                    # 天区
                dec_center=10.0,                                                                    # 天区
                radius_arcsec=60.0,                                                                 # 半径
                catalog="ps1",                                                                      # 星表
                resumable=True,                                                                     # 可续标记: 断点键才派生得出来
                job_id="test_region_run",                                                          # 显式作业号: 不给就退回自动键而复现旧行为
            )
            assert Path(saved).is_file()  # 区域入口也要走完写出, 不能只建断点
            assert dl.checkpoint.load("test_region_run") is None  # 成功后断点即收尾

    def test_download_sqlid_expired_session_raises_sqlid_expired_error(self, tmp_path):
        """sqlid 会话软 404 (过期/死亡): 必须抛出 SqlidExpiredError 并附带自愈指引。

        守的不变量: 服务端会话过期后偏移翻页无法继续; 必须明确抛出可识别的
        SqlidExpiredError (它同时是 RuntimeError 的子类, 兼容已有捕获), 并在错误
        信息中指导调用方清理断点重提 Phase 1 查询, 防止盲目重试陷入死循环。
        """
        client = BestClient(rate_limit=0)
        out_dir = tmp_path / "data"
        ckpt_dir = tmp_path / "checkpoints"
        dl = BestDownloader(client, output_dir=str(out_dir), checkpoint_dir=str(ckpt_dir))

        job_id = "job_expired_session"
        dl.checkpoint.save(job_id, {
            "job_id": job_id,
            "sqlid": "s9999",
            "catalog": "ps1",
            "next_page": 2,
            "sources": [{"source_id": "S101", "ra": 180.0, "dec": 30.0}],
            "output_format": "csv",
            "output_file": "expired_output.csv",
            "page_size": 1000,
            "max_rows": 50000,
        })

        expired_result = BestQueryResult(
            success=False,
            error="E_SOFT_404: sqlid session s9999 answered page 2 with a soft error body; session is dead or expired",
            error_code="E_SOFT_404",
        )

        with patch.object(client, "_fetch_sqlid_data", return_value=expired_result):
            with pytest.raises(SqlidExpiredError) as exc_info:
                dl.resume_job(job_id)

            err_text = str(exc_info.value)
            assert "E_SOFT_404" in err_text
            assert "expired or dead" in err_text
            assert f"delete checkpoint '{job_id}'" in err_text
            # 兼容性断言: SqlidExpiredError 必须也是 RuntimeError 的实例
            assert isinstance(exc_info.value, RuntimeError)

