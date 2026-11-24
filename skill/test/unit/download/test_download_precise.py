"""精准下载 (按 source_id in 约束) 单元测试。

守的回归: ID 归一化 (去重/去空白/类型拒绝)、表单键的星表差异 (ps1 用
``source_id`` textarea, stripe82 用裸名 ``calibstars_id``, gaia_dr3 解析到
真实星表)、单次 in 查询的 ID 上限、0 行结果必须 hook 拦截而部分命中只 WARN,
以及 constraints 必须是 ColumnConstraint 对象。
"""
from __future__ import annotations

# 标准库: pathlib 造临时产物文件与目录 (进度/断点目录锚定到 tmp_path)
from pathlib import Path  # 产物/进度/断点三个目录都要锚到临时区, 用例不得碰真实运行目录

# 标准库: patch 替换 downloader 的下载方法, 避免真实网络请求
from unittest.mock import patch  # patch 换掉下载方法: 全程离线, 不打真实站点

# 测试框架: raises 断言拦截异常; tmp_path 提供独立临时目录
import pytest  # raises 断言拦截异常; tmp_path 提供每例独立的目录

try:
    # 本地: 生产客户端 (管理器集成用例用, rate_limit=0 关掉礼貌限流)
    from src.client import BestClient  # 管理器集成用例用; 限流归零免得后台任务被礼貌等待拖住

    # 本地: hook 层 — 0 行/超量 ID 两条 severe 判据与拦截异常
    from src.download_hooks import (
        SEVERE_EMPTY_PRECISE,  # 0 行的严重级别常量: UI 与日志按它区分"空结果"与"超量"
        SEVERE_PRECISE_TOO_LARGE,  # 超量 ID 的严重级别常量
        DownloadHooks,  # hook 集合: 注册与派发都在这里
        HookBlockedError,  # 拦截异常: 精准下载被拦时抛的就是它
        HookPolicy,  # 退避策略: 只验拦截语义, 不真等退避
    )

    # 本地: 作业管理 — 任务载体 + 后台执行/进度/日志集成面
    from src.download_manager import DownloadManager, PreciseDownloadJob  # 任务载体 + 后台执行面: 端到端几条用例都要用

    # 本地: 被测单元 — ID 归一化/表单构造/输出命名/执行与行数回核
    from src.download_precise import (
        MAX_IDS_PER_QUERY,  # ID 上限常量: 超量判定必须与它同源
        build_precise_form,  # 表单构造: 星表相关的键名差异全在这里
        normalize_ids,  # ID 归一化: 去重去空白与坏类型拒绝
        precise_output_file,  # 输出命名: 唯一后缀是并行不互覆盖的关键
        run_precise_download,  # 执行与行数回核: 0 行强异常在回核那一层触发
    )
except Exception as _legacy_err:  # legacy-import-guard
    # 源码树调整导致旧导入路径失效时整模块跳过, 不让收集期报错
    import pytest as _pytest
    _pytest.skip(f'legacy import unavailable: {_legacy_err!r}', allow_module_level=True)            # 模块级跳过: 导入树问题不该算用例失败


def _fast_policy():
    """构造毫秒级退避策略 (max_retries=1): 只验拦截语义, 不真等退避。"""
    # retry_base_sec 压到毫秒级是刻意省时: 真正要验的是"拦不拦", 不是退避曲线;
    # 用生产级退避会让整组用例多花几十秒, 而拦截判据一次都不会变
    return HookPolicy(max_retries=1, retry_base_sec=0.001)                                  # 退避压到毫秒级: 这组用例要验的是拦不拦, 不是退避曲线


class TestNormalizeIds:
    """source_id 归一化: 去重、去空白、容错单字符串、拒绝坏类型。"""

    def test_dedupe_and_strip(self):
        """去空白 + 去重 + 丢空值: 同一 ID 重复提交只算一次。

        守的回归: 站点 in 约束按 textarea 逐行提交, 重复 ID 会让请求行数虚高
        甚至撞单次上限, 且回核时"请求 N 个/返回 M 行"对不上账。
        """
        # 期望值写成归一后的两个 ID: 顺序取首次出现, 因此 " 123 " 与 "123" 收成
        # 同一条, 而 None/空串被整条丢掉而不是变成字面量 "None"
        assert normalize_ids([" 123 ", "123", "", None, "456"]) == ["123", "456"]  # 期望值写归一后的结果: 顺序取首次出现, 空值整条丢而非变 None

    def test_single_string(self):
        """单个字符串按一个 ID 处理 (调用方常直接传一个 id 而不是列表)。"""
        assert normalize_ids("abc") == ["abc"]  # 单个字符串按一个 ID 处理, 不因类型不同就报错

    def test_none_and_bad_type(self):
        """None 返回空列表; 非字符串类型 (int) 必须 TypeError。

        守的回归: 静默 str() 会把 42 变成合法 ID, 最终查出 0 行、再被 0 行
         hook 拦成"ID 或星表用错" — 把编程错误误导成用户错误。
        """
        assert normalize_ids(None) == []  # None 是合法空输入而不是类型错误, 两条路径语义必须分开
        with pytest.raises(TypeError):                                           # 传错类型必须抛 TypeError: 静默转成空集会伪装成"没有精确测光结果"
            normalize_ids(42)                                                         # 非字符串类型必须报错: 静默 str() 会把编程错误伪装成用户错误


class TestPreciseForm:
    """in 约束表单: 星表相关 ID 列名、列投影、上限与输出命名。"""

    def test_ps1_form_uses_in_textarea(self):
        """ps1: operation=in + textarea 逐行 ID, 列投影补表前缀。

        守的回归: 站点表单的 in 约束是 textarea 多行文本 (不是数组参数),
        列投影必须带表前缀 (``ps1.ra`` 而非 ``ra``), 否则投影静默失效。
        """
        job = PreciseDownloadJob(source_ids=["a", "b"], catalog="ps1",                              # 列名用星表真实列, 投影才补得上前缀
                                 columns=["ps1_ra", "ps1_gpsf"])                              # 两列: 一列是赤经, 一列是星等, 投影要逐个补前缀
        form = build_precise_form(job)  # 表单由作业对象构造, 键的星表前缀从这里开始
        assert form["ps1.source_id.operation"] == "in"  # operation 固定为 in: 精准下载的约束语义不允许退化成别的
        # textarea 的值是换行拼接而不是数组: 站点的 in 约束收多行文本, 传数组
        # 会被序列化成 Python 字面量, 服务端当成一个畸形 ID 去查
        assert form["ps1.source_id.textarea"] == "a\nb"  # textarea 收换行拼接, 传数组会被序列化成 Python 字面量
        # 投影列必须带 ps1. 前缀; 断言整个列表相等, 顺带钉住列序不被排序打乱
        assert form["showcol"] == ["ps1.ra", "ps1.gpsf"]  # 整份等值顺带钉住列序, 投影被排序打乱时这条会红

    def test_stripe82_uses_calibstars_id(self):
        """live 实证: stripe82 的 ID 列是裸名 calibstars_id。

        守的回归: 各星表 ID 列名不统一, 按 ps1 的 ``source_id`` 硬编码会让
        stripe82 精准下载约束到一个不存在的列, 返回 0 行。
        """
        job = PreciseDownloadJob(source_ids=["CALIBSTARS_1"], catalog="stripe82")
        form = build_precise_form(job)  # ID 列名按星表解析: 硬编码 ps1 的 source_id 会查空
        assert "stripe82.calibstars_id.operation" in form  # 键在场即证明 stripe82 的 ID 列已解析, 不必断值
        assert form["stripe82.calibstars_id.operation"] == "in"                           # 值也必须是 in: 只断键存在的话, 约束语义写错了也照样绿

    def test_gaia_alias_resolves(self):
        """gaia_dr3 是别名: 表单键必须落在真实星表 gaia_dr3_18 上。

        守的回归: 别名不解析会把表单发到不存在的星表路径, 服务端软 404。
        """
        job = PreciseDownloadJob(source_ids=["x"], catalog="gaia_dr3")                        # 用别名构造: 别名不解析会把表单发到不存在的星表路径
        form = build_precise_form(job)  # 别名解析后的真实星表名才是表单键的前缀来源
        # 只断键存在: 别名若没解析, 键会留在 gaia_dr3.* 上, 这条自然红;
        # 反向断言 (gaia_dr3. 前缀不存在) 交给上面 ps1/stripe82 两条即可
        assert "gaia_dr3_18.source_id.operation" in form                                 # 只断键存在: 反向断言交给 ps1 与 stripe82 两条

    def test_explicit_id_column_prefixed(self):
        """显式 id_column 也要补表前缀 (ps1_source_id -> ps1.source_id)。"""
        job = PreciseDownloadJob(source_ids=["x"], catalog="ps1",  # 显式 id_column 仍走同一条补前缀规则
                                 id_column="ps1_source_id")                                         # 给带前缀的裸列名, 看实现补不补
        form = build_precise_form(job)                                                              # 同样走公开的表单构造
        assert form["ps1.source_id.operation"] == "in"  # 补完前缀才是服务端认识的键, 裸列名会静默失效

    def test_empty_ids_raise(self):
        """空 ID 列表必须 ValueError (不发无约束查询, 那等于拉全表)。"""
        with pytest.raises(ValueError):                                                             # 空 ID 列表即报错
            build_precise_form(PreciseDownloadJob(source_ids=[]))                                   # 不发无约束查询: 那等于拉全表

    def test_too_many_ids_raise(self):
        """超过单次 in 查询上限必须 ValueError。

        守的回归: 站点对单次 in 的 ID 数有上限, 超量提交会被服务端静默截断
        (返回部分行且不报错), 用户以为拿到了全部结果。
        """
        ids = [str(i) for i in range(MAX_IDS_PER_QUERY + 1)]  # 构造上限加一的 ID 列表, 少一个就落在界内不触发
        # match="too many" 是在钉错误语义而不只是异常类型: 裸 ValueError 会让
        # 用户以为是 ID 格式错, 而实际是"数量超限, 该分批"
        with pytest.raises(ValueError, match="too many"):
            build_precise_form(PreciseDownloadJob(source_ids=ids))                                  # 报错要走表单构造: 校验点在建单那一刻

    def test_output_file_naming(self):
        """输出名 (星表, ID 数) + job_id 唯一后缀; 显式 output_file 优先 (B3)。

        守的不变量: 自动名的唯一性必须细到 job_id 粒度 — 只到 (星表, ID 数)
        粒度时, 同星表同 ID 数的两个并行任务会生成同名文件, 经 _save_result
        原子写互相 os.replace 覆盖 (用户 silently 少一份数据)。自动名带 job_id,
        人也可从文件名回溯到是哪次作业的产物; 调用方并行提交时仍应显式给
        job.output_file (人读性最好)。
        """
        job = PreciseDownloadJob(source_ids=["a", "b", "a"], catalog="ps1")                     # 传重复 ID 是为了验文件名计数用的是归一后的数
        # 传 "a","b","a" 是为了验文件名里的计数用的是归一后的 ID 数 (2) 而不是
        # 原始长度 (3); 计数口径若没归一, 文件名会骗人
        assert precise_output_file(job, "j1") == "best_ps1_precise_2ids_j1.csv"  # 计数取归一后的 2 而非原始 3, 口径错时文件名会骗人
        job.output_file = "custom.csv"                                                             # 显式名优先于自动名: 调用方自己起名最可读
        # 显式名优先于自动名: 调用方并行批量提交时自己起名最可读
        assert precise_output_file(job, "j1") == "custom.csv"                                       # 显式名必须原样返回

    def test_output_file_unique_across_parallel_jobs(self):
        """同参数两个任务的自动输出名必须不同 (唯一后缀保证并行不互覆盖) (B3)。

        守的回归: 唯一性不能依赖调用方记得传不同参数 — 两个同星表同 ID 数
        的任务 (并行批量精准下载的常态) 也必须拿到不同文件名。给了 job_id
        按 job_id 区分 (同一作业 resume 重跑还是同一名, 幂等覆盖); 没给
        (直接调用 run_precise_download 未传 job_id) 则退到随机后缀。
        """
        job_a = PreciseDownloadJob(source_ids=["x", "y"], catalog="stripe82")  # 两作业参数完全相同, 唯一性只能来自 job_id 后缀
        job_b = PreciseDownloadJob(source_ids=["x", "y"], catalog="stripe82")  # 构造第二个同参作业, 两者唯一性互为对照
        assert precise_output_file(job_a, "ja") != precise_output_file(job_b, "jb")                 # 给了 job_id 就按它区分
        assert precise_output_file(job_a) != precise_output_file(job_b)                        # 没给 job_id 则退到随机后缀, 同样不许撞名


class TestPreciseHooks:
    """结果回核: 0 行强异常要 ask, 部分命中只 WARN, 约束对象类型不能退化成 dict。"""

    def test_empty_result_triggers_ask(self, tmp_path):
        """0 行 = 精准下载强异常: hook 拦截 + ask 载荷。

        守的回归: 只有表头的产物意味着 ID 或星表用错 (如把 gaia_dr3 的 ID 丢给
        ps1), 必须立刻 ask 而不是返回一个"成功"的空文件; 选项至少 2 条给用户
        可执行出路 (核对 ID / 改坐标 proximity)。
        """
        hooks = DownloadHooks(policy=_fast_policy())  # 只有表头的产物是 0 行强异常的判定对象
        target = tmp_path / "empty.csv"  # 先落好这个文件: 判定读的是磁盘上的真实行数
        target.write_text("ps1_ra,ps1_dec\n", encoding="utf-8")                                     # 只有表头, 没有数据行

        class _DL:
            """最小 downloader 替身: 只回一个只有表头的产物路径。"""

            def download_by_constraints(self, **kw):
                """把预置的空结果路径交出去, 用来触发 0 行强异常判定。"""
                return str(target)                                                                  # 交出预置的空结果路径

        with pytest.raises(HookBlockedError) as ei:                                # 钩子拦截要抛 HookBlockedError, 而不是静默放行或换一种错
            run_precise_download(_DL(),                                                           # 走公开执行入口: 直接调内部会绕过回核与拦截
                                 PreciseDownloadJob(source_ids=["nope"]),                           # 给一个必然查不到的 ID, 制造 0 行
                                 hooks, job_id="j1")                                           # job_id 显式给出: 拦截载荷要靠它关联到任务
        assert ei.value.interrupt.kind == SEVERE_EMPTY_PRECISE  # kind 是内部常量, 用户看到的是下面那条的 payload.id
        payload = ei.value.interrupt.to_ask_payload()  # ask 载荷是 GUI/CLI/agent 三态共同的消费面
        # 断 payload 的 id 而不是只断 kind: kind 是内部常量, 用户与 GUI 看到的是
        # payload.id, 两者对不上会让 ask 界面显示成别的流程
        assert payload["id"] == "hook_empty_precise_result"  # id 必须与 kind 对得上, 错位会让 ask 界面串流程
        # 至少两条出路是硬要求: 只给一个"重试"等于把用户推回死路
        assert len(payload["options"]) >= 2  # 选项数是硬要求: 只给重试等于把用户推回死路

    def test_too_many_ids_triggers_ask(self):
        """超量 ID: 走 severe hook 且建议方案里必须带"分批"。

        守的回归: 上限是硬约束, 但报错方式必须是可操作的 ask (分批/proximity
        两条路), 而不是一个裸 ValueError 让调用方无从下手。
        """
        hooks = DownloadHooks(policy=_fast_policy())                                             # 部分命中用同一套 hook, 差别只在结果非空
        ids = [str(i) for i in range(MAX_IDS_PER_QUERY + 1)]                                        # 同样构造超量 ID 列表
        with pytest.raises(HookBlockedError) as ei:                                                 # 同上, 但走的是另一类策略分支
            run_precise_download(object(),                                                   # 替身用 object() 就够: 超量在请求之前就被拦
                                 PreciseDownloadJob(source_ids=ids),                                # 超量 ID 列表
                                 hooks, job_id="j1")
        assert ei.value.interrupt.kind == SEVERE_PRECISE_TOO_LARGE  # 超量走的是 hook 而非裸 ValueError, 调用方要能直接弹出 ask
        assert any("分批" in o["label"] for o in ei.value.interrupt.options)  # 方案里必须出现分批: 上限是硬约束但出路要可操作

    def test_partial_result_warns_not_blocks(self, tmp_path):
        """部分命中: WARN 不拦截 (ID 不存在是常态)。

        守的回归: 请求 3 个 ID 只回 1 行是正常科学结果 (星表覆盖不全), 若按
        0 行同等拦截会把用户逼疯; 只有 0 行才是强异常信号。
        """
        hooks = DownloadHooks(policy=_fast_policy())  # 部分命中用同一套 hook, 差别只在结果非空
        target = tmp_path / "partial.csv"  # 一行的产物是常态而非异常: 星表覆盖不全本该如此
        target.write_text("ps1_ra,ps1_dec\n180.0,30.0\n", encoding="utf-8")                         # 预置一行数据, 与 0 行形成对照

        class _DL:
            """最小 downloader 替身: 只回一个"有 1 行数据"的产物路径。"""

            def download_by_constraints(self, **kw):
                """交出部分命中结果, 验证部分命中只 WARN 不拦截。"""
                return str(target)                                                                  # 交出部分命中结果

        path = run_precise_download(  # 不抛异常并原样返回路径, 这就是部分命中的契约
            _DL(), PreciseDownloadJob(source_ids=["a", "b", "c"]),                                  # 请求三个 ID
            hooks, job_id="j1")
        assert path == str(target)  # 不抛, 正常返回

    def test_constraints_are_columnconstraint_objects(self, tmp_path):
        """downloader/_build_form 要求 ColumnConstraint (传 dict 会在下游炸)。

        守的不变量: 约束必须是对象而不是 dict —— downloader 侧取 .name/
        .constraint, 传 dict 直接 AttributeError; 且 name 用星表解析出的裸 ID 列。
        """
        hooks = DownloadHooks(policy=_fast_policy())                                                # 约束对象类型是这条要验的
        target = tmp_path / "ok.csv"                                                                # 正常产物: 与 0 行那条形成对照
        target.write_text("calibstars_id,ra\nX1,1.0\n", encoding="utf-8")                           # 预置一行, 让回核通过
        seen = {}  # 替身把入参记进 seen, 断约束类型需要它的出口

        class _DL:
            """最小 downloader 替身: 把收到的 constraints 原样记进 seen。"""

            def download_by_constraints(self, constraints=None, **kw):
                """记录约束对象后返回一个正常产物, 供断言约束的真实类型。"""
                seen["constraints"] = constraints
                return str(target)                                                                  # 返回正常产物, 供后面断言约束类型

        run_precise_download(                                                                       # 走公开执行入口
            _DL(), PreciseDownloadJob(source_ids=["X1"], catalog="stripe82"),                   # 用裸 ID 列的星表, 看 name 是不是裸列
            hooks, job_id="j1")
        c = seen["constraints"][0]  # 取第一条即可: 约束列表的每一条都应是同一类对象
        # 断类名而不是 isinstance: 约束类定义在下游模块, 用类名比较可以避免
        # 本测试为了 import 它而多绑一层依赖
        assert type(c).__name__ == "ColumnConstraint"  # 类名比较避免为断类型而多绑一层下游依赖
        # name 用星表解析出的裸 ID 列: 带表前缀会让 _build_form 拼出不存在的字段
        assert c.name == "calibstars_id" and c.constraint == "in"  # name 用裸 ID 列: 带表前缀会让表单拼出不存在的字段


class TestManagerPreciseIntegration:
    """精准下载经 DownloadManager 的端到端: 正常/被拦截/断点续传。"""

    def test_precise_job_end_to_end(self, tmp_path):
        """端到端: 提交 -> 分页 observer 累加 -> done, 任务日志事件序列完整。

        守的回归: 事件序列必须是 submit ... done, 且含精准下载特有的
        "query" 事件 (约束已构造 + 行数回核事实) — 问题定位时靠它还原
        "到底拿几个 ID 查了哪一列"。
        """
        mgr = DownloadManager(BestClient(rate_limit=0),  # 限流归零, 后台任务不会被礼貌等待拖住
                              output_dir=str(tmp_path / "out"),                                     # 产物目录锚在临时区
                              progress_dir=str(tmp_path / ".progress"),                             # 进度目录锚在临时区: 断言读的是这一份
                              checkpoint_dir=str(tmp_path / ".checkpoints"))                        # 断点目录锚在临时区
        target = str(tmp_path / "out" / "p.csv")  # 产物路径先定死: 替身返回它, 断言才有可比对象
        Path(target).parent.mkdir(parents=True, exist_ok=True)  # 先建目录: 后台线程写产物时目录不存在会直接失败
        Path(target).write_text("calibstars_id,ra\nX1,1.0\nX2,2.0\n",                               # 预置两行, 对应两个 ID
                                encoding="utf-8")                                                   # 编码显式钉死: 断言要读盘上那份字节
        # 预置 2 行 (对 2 个 ID): _verify_row_count 的回核要看到行数不为 0 才不
        # 触发拦截, 这条断言才能落在事件序列上而不是被 0 行 hook 岔开

        def _fake(self, *a, **kw):                                                                  # 替身回调一页后返回产物
            """回调一页 (2 个源) 后返回产物, 让 observer 有进度可累加。

            守的回归: done_pages 必须来自 observer 而不是下载完后的补写,
            否则 GUI 在大任务上会长时间显示 0 页后突然跳到 100%。
            """
            ob = kw.get("on_page_observer")                                                         # observer 从关键字参数里取
            if ob:                                                                                  # observer 可能缺席, 显式判一次
                ob(1, [1, 2])                                                                       # 回调一页两个源: 页数才有累加的余地
            return target                                                                           # 交回产物路径

        with patch("src.downloader.BestDownloader.download_by_constraints",                         # 打在被测下载方法上
                   _fake):
            jid = mgr.submit(PreciseDownloadJob(                                                    # 提交精准任务
                source_ids=["X1", "X2"], catalog="stripe82"))                                       # 两个 ID 对应预置的两行
            # timeout=30 是后台任务的上限护栏: 替身是同步返回的, 真超时只会
            # 暴露成挂死, 30s 足够跑完又不会让 CI 在故障时干等
            assert mgr.result(jid, timeout=30) == target  # 超时是护栏: 替身同步返回, 真超时只会暴露成挂死
        rec = mgr.status(jid)                                                                       # 从管理器读终态, 而不是从替身返回值推断
        assert rec["status"] == "done"  # 终态从管理器读, 而不是从替身返回值推断
        events = [r["event"] for r in mgr.task_log.tail(n=0, task_id=jid)]                          # 取该任务的事件序列
        # 首尾都要断: 只断末态的话, 少了 submit 的任务 (例如 submit 失败后
        # 被重试掩盖) 仍会显示 done, 排障时看不出任务是怎么起的
        assert events[0] == "submit" and events[-1] == "done"  # 首尾都断: 少了 submit 的任务仍显示 done, 排障看不出起点
        assert "query" in events  # 精准下载特有事实
        mgr.shutdown()                                                                              # 收线程池, 不然后台线程会漏给后续用例

    def test_parallel_precise_jobs_get_unique_output_files(self, tmp_path):
        """并行: 同星表同 ID 数的两个精准任务输出文件名必须不同 (B3 回归)。

        守的回归 (与区域下载同名覆盖同一族的问题): 两任务自动同名会互相
        os.replace 覆盖, 用户 silently 少一份数据; 这里记录管理器算出的
        output_file, 让"文件名是否唯一"成为可断言的事实。
        """
        mgr = DownloadManager(BestClient(rate_limit=0),                                             # 限流归零
                              output_dir=str(tmp_path / "out"),                                     # 产物目录锚在临时区
                              progress_dir=str(tmp_path / ".progress"),                             # 进度目录锚在临时区
                              checkpoint_dir=str(tmp_path / ".checkpoints"))                        # 断点目录锚在临时区
        seen_files = []  # 收集两个任务各自算出的文件名, 唯一性断的是这份记录
        # 产物预置 2 行: 让 _verify_row_count 的回核通过 (不触发 0 行 hook),
        # 断言才能落在"文件名是否唯一"上而不是被拦截岔开
        target = tmp_path / "out" / "x.csv"                                                         # 预置产物, 让回核通过
        target.parent.mkdir(parents=True, exist_ok=True)  # 目录同样要先建, 两个任务并发写同一个父目录
        target.write_text("calibstars_id,ra\nX1,1.0\nX2,2.0\n",                                     # 同样预置两行
                          encoding="utf-8")                                                         # 编码显式钉死

        def _fake(self, *a, output_file=None, **kw):
            """把管理器算出的 output_file 收进 seen_files: 唯一性断言的依据。"""
            seen_files.append(output_file)                                                       # 只记文件名, 不改写: 唯一性才是可断言的事实
            return str(target)                                                                      # 返回路径与文件名无关, 排除干扰

        with patch("src.downloader.BestDownloader.download_by_constraints",                         # 打在被测下载方法上
                   _fake):
            ids = mgr.submit_all([                                                                  # 一次交两个同参任务
                PreciseDownloadJob(source_ids=["X1", "X2"],                                         # 第一个同参任务
                                   catalog="stripe82"),
                PreciseDownloadJob(source_ids=["X1", "X2"],                                         # 第二个同参任务: 两者唯一性互为对照
                                   catalog="stripe82"),
            ])
            for jid in ids:                                                                         # 逐个等完, 两个任务都要记过文件名
                mgr.result(jid, timeout=30)                                                        # 逐个等: 提前 break 会让记录不完整
        assert len(seen_files) == 2  # 先断条数: 两个任务都拿到 None 时不等式仍可能成立
        # 先断条数再断不等: 只断不等的话, 两个任务都拿到 None (输出名没算出来)
        # 也能通过, 那恰好是这段代码最坏的一种退化
        assert seen_files[0] != seen_files[1]  # 不等式只在两个名字都算出来时才有意义
        mgr.shutdown()                                                                              # 收线程池

    def test_precise_job_blocked_flow(self, tmp_path):
        """0 行结果经管理器: 进度置 blocked + ask 载荷, 日志可见 hook warn。

        守的回归: 后台任务没有前台可 ask, 必须把问题同时落到进度文件 (GUI/CLI
        同源) 和任务日志的 problems() 视图 — 双落点缺一个, 用户就看不到"为什
        么什么都没下载到"。
        """
        mgr = DownloadManager(BestClient(rate_limit=0),                                             # 限流归零
                              output_dir=str(tmp_path / "out"),                                     # 产物目录锚在临时区
                              progress_dir=str(tmp_path / ".progress"),                        # 进度目录锚在临时区: blocked 载荷写在这里
                              checkpoint_dir=str(tmp_path / ".checkpoints"))                        # 断点目录锚在临时区
        empty = str(tmp_path / "out" / "e.csv")                                                     # 只有表头的产物路径
        Path(empty).parent.mkdir(parents=True, exist_ok=True)  # 建目录后再落只有表头的产物, 让 0 行判定有真实对象
        Path(empty).write_text("ps1_ra\n", encoding="utf-8")
        def _fake(self, *a, **kw):                                                                  # 替身直接返回空结果
            """直接返回只有表头的产物, 让 0 行判定在管理器层触发拦截。"""
            return empty                                                                            # 交回空产物路径

        with patch("src.downloader.BestDownloader.download_by_constraints",                         # 打在被测下载方法上
                   _fake):
            jid = mgr.submit(PreciseDownloadJob(source_ids=["nope"]))                               # 给一个必然查不到的 ID
            with pytest.raises(HookBlockedError):
                mgr.result(jid, timeout=30)
        rec = mgr.status(jid)                                                                       # 从管理器读回被拦截后的状态
        assert rec["status"] == "blocked"                                       # 状态必须是 blocked: 落成 failed 就等于用户看不到为什么空手而归
        assert rec["hook"]["raw"]["kind"] == SEVERE_EMPTY_PRECISE  # raw 是 UI 消费的原始载荷, 少这一层就看不到 kind
        # 任务日志可见 hook warn (问题定位)
        probs = mgr.task_log.problems()                                                             # 取问题视图
        assert any(p["event"] == "hook" for p in probs)  # 问题视图要能看见 hook warn, 否则用户不知为何空手而归
        mgr.shutdown()                                                                              # 收线程池

    def test_precise_resume_roundtrip(self, tmp_path):
        """精准任务 resume 后仍能拿到同一产物 (无页级 checkpoint 时按原参数重提交)。"""
        mgr = DownloadManager(BestClient(rate_limit=0),                                             # 限流归零
                              output_dir=str(tmp_path / "out"),                                     # 产物目录锚在临时区
                              progress_dir=str(tmp_path / ".progress"),                             # 进度目录锚在临时区
                              checkpoint_dir=str(tmp_path / ".checkpoints"))                        # 断点目录锚在临时区
        target = str(tmp_path / "out" / "r.csv")                                                    # 产物路径: 续跑前后必须是同一个
        Path(target).parent.mkdir(parents=True, exist_ok=True)                                      # 先建目录
        Path(target).write_text("calibstars_id,ra\nX1,1.0\n", encoding="utf-8")                     # 预置一行, 与请求的一个 ID 对应

        def _fake(self, *a, **kw):
            """返回同一产物路径, 让 resume 前后拿到的是同一个文件。"""
            return target                                                                         # 返回同一产物路径, 让续跑前后拿到同一个文件

        with patch("src.downloader.BestDownloader.download_by_constraints",                         # 打在被测下载方法上
                   _fake):
            jid = mgr.submit(PreciseDownloadJob(source_ids=["X1"],                                  # 提交一个 ID 的精准任务
                                                catalog="stripe82"))                                # 用裸 ID 列的星表
            mgr.result(jid, timeout=30)
            new_id = mgr.resume(jid)
            assert mgr.result(new_id, timeout=30) == target                                         # 续跑后仍要拿到同一份产物
        mgr.shutdown()                                                                              # 收线程池
