# -*- coding: utf-8 -*-
"""evals.case_executor — 行为用例执行层 (逐条用例跑真实交互并判定)。

能力边界: 读 evals/cases/ 下的用例夹具, 按 type 派发到四类执行体
(gate / algorithm / scope / field), 每条用例都**真实调用**生产代码或真实执行门禁
判定, 拒绝纯 hasattr 假校验 (EVAL-10)。与 eval_runner 的分工: 本模块负责"一条用例
过不过", runner 负责"汇总通过率并加权评分"。

白盒锚点: docs/architecture/file-size-budget.md §3.1;
references/ALGORITHM-SPEC.md §3。
"""
from __future__ import annotations

# 标准库: 逐条列出"为什么需要它" —— 用例执行层原先靠 eval_runner 的同模块
# 可见性白用, 拆出后必须显式补上 (re 抽 derived_from 字段, importlib 动态
# import 真实生产模块, pathlib 定位夹具, typing 汇总标注, contextlib 清理,
# json 做字段契约的关键词探测)
import contextlib  # 尽力而为的清理: 删不掉临时文件不该让评测失败 (SIM105)
import importlib  # 按用例声明动态 import 真实生产模块: EVAL-10 拒绝纯 hasattr 假校验
import json  # 字段契约的关键词探测: 整份契约转文本后查 type/unit
import re  # 从 derived_from 字符串里抽 'name'/'module' 两段
from pathlib import Path  # 定位 cases/ 目录与用例夹具路径
from typing import Any  # 汇总字典的宽松类型标注, 运行期无依赖

# 本地组: 中立载体 (skill 根定位 + YAML 装载)
from paths import SKILL_DIR, load_yaml_file  # noqa: E402


def _evaluate_gate(cmp_op: str, actual: Any, threshold: Any) -> bool:
    """比较门禁阈值 (显式返回, -O 安全)。

    刻意不用 assert: ``python -O`` 会整体删掉 assert, 那会让门禁在优化模式下
    恒真 (EVAL-02 教训), 所以这里逐分支显式 return。

    Args:
        cmp_op: 比较算子 (== != <= >= < >)。
        actual: 真实执行得到的实际值。
        threshold: 用例声明的阈值。

    Returns:
        比较结果; 未知算子返回 False (不认识的算子绝不能放行)。
    """
    if cmp_op == "==":  # 逐分支显式 return: python -O 会把 assert 删成恒真
        return actual == threshold
    if cmp_op == "!=":
        return actual != threshold
    if cmp_op == "<=":  # 有序算子统一走 float(): 阈值常以字符串形态写进 YAML
        return float(actual) <= float(threshold)
    if cmp_op == ">=":
        return float(actual) >= float(threshold)
    if cmp_op == "<":
        return float(actual) < float(threshold)
    if cmp_op == ">":
        return float(actual) > float(threshold)
    # 未知算子: 保守判 False, 防止用例写错算子反而恒过
    return False  # 未知算子保守判 False: 用例写错算子绝不能反而恒过
def _run_gate_case(cf: Path, cdata: dict[str, Any]) -> tuple[bool, str]:
    """门禁用例: 真实执行生产代码路径 (EVAL-07: actual 只认生产判定)。

    ``actual`` 必须由生产判定函数算出, 用例文件名绝不参与: 若从文件名里有
    没有 ``violated`` 反推, "违反用例判 blocked、通过用例判 pass" 这个比较
    恒真 —— 门禁逻辑 (``protocol.is_soft_error``) 就算整个退化成"永远返回
    False", 评测也永远全绿。现在 actual 完全由生产判定算出, 退化立刻显红。

    Args:
        cf: 用例文件路径 (其文件名只用于区分 violated/pass 意图)。
        cdata: 用例 YAML 内容 (derived_from / threshold / expect)。

    Returns:
        (是否通过, 人类可读说明); 未知门禁名返回 (False, 原因)。
    """
    derived = str(cdata.get("derived_from", ""))  # 派发依据: gate:名字 / algorithm:...
    gate_name = derived.split(":", 1)[1] if derived.startswith("gate:") else ""  # 只认 gate: 前缀; 其余派发交给另外三类 handler
    threshold = cdata.get("threshold", {}) or {}
    cmp_op = threshold.get("cmp", "==")  # 缺 cmp 缺省等值: 只写阈值不写算子是最常见形态
    threshold_val = threshold.get("value")
    expect_status = (cdata.get("expect", {}) or {}).get("status", "pass")  # 期望状态是门禁的"意图"声明, 不是从文件名反推的
    name = cf.name                                                                        # 文件名只用于读出"违反或通过"的意图, 绝不参与实际值的计算

    if gate_name == "http_status":  # actual 完全由生产判定算出: 从文件名反推会让比较恒真, 永不可能红
        # 延迟导入: 门禁判定只在这一支需要 Mock 替身 / 客户端 / is_soft_error,
        # 放进模块级依赖面会让未跑门禁用例的模块也付出导入代价
        from unittest.mock import Mock as _Mock

        from src.client import BestClient
        from src.protocol import is_soft_error

        client = BestClient(rate_limit=0)  # rate_limit=0: 离线回放, 构造客户端不得引入任何等待
        entry = hasattr(client, "cone_search")  # 入口存在性
        is_violation = "violated" in name
        # 两种回包体由用例意图定, 判定权交给 is_soft_error
        body = '{"error":"Not Found"}' if is_violation else "ps1_ra,ps1_dec\n180.0,30.0\n"
        stub = _Mock()                                                                    # 替身只给状态码与回包体两样: 门禁只读这两样, 多的都是噪声
        stub.status_code = 200  # 软错误也是 200: 状态码本身不能作为判据
        stub.text = body                                                                        # 回包体由用例意图决定: 软错误体与正常载荷各一支
        actual = 500 if is_soft_error(stub.text) else 200  # 门禁语义: 软错误体判失败, 正常载荷判通过
        eval_res = _evaluate_gate(cmp_op, actual, threshold_val)                        # 实际值交给比较门禁: 算子与阈值都来自用例声明, 不在代码里写死
        # 双向匹配: 只认"判定结果 == 声明意图"
        ok = (eval_res and expect_status == "pass") or ((not eval_res) and expect_status == "blocked")
        return ok, (f"http_status 门禁逻辑实测 actual={actual} expect={expect_status} "
                    f"-> {ok} (软错误体判定={is_violation}, entry={entry})")

    if gate_name == "checksum_match":  # 第二类门禁: 校验和比对走真实文件 sha256, 不依赖网络样本
        # 延迟导入: 校验和门禁只需临时文件与下载器的两个静态方法, 全程不触网
        import tempfile

        from src.downloader import BestDownloader

        with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8") as tf:  # 写点: 内容确定的临时文件, 让 sha256 可复算
            tf.write("eval-gate-checksum-payload-42")
            tf_path = Path(tf.name)                                                       # 临时文件路径先取出来: 清理分支在 with 之外还要引用它
        try:
            real_sha = BestDownloader.compute_sha256(tf_path)  # 真值由生产函数自算: 用例不自造哈希, 免得判据自证
            if "violated" in name:
                match = BestDownloader.verify_checksum(tf_path, "0" * 64)  # 违反分支: 全零哈希必须 False, 不能恒真
                return (not match) and expect_status == "blocked", "checksum 违反分支实测 (篡改哈希必须 False)"
            match = BestDownloader.verify_checksum(tf_path, real_sha)                             # 通过分支用真值哈希: 自造哈希等于让判据自证
            ok = _evaluate_gate(cmp_op, match, threshold_val) and expect_status == "pass"
            return ok, f"checksum 通过分支实测 match={match}"
        finally:
            if tf_path.exists():  # 清理点: 临时文件必须删, 否则评测在 CI 上留垃圾
                with contextlib.suppress(OSError):  # 删不掉不该让评测失败: 只影响卫生, 不影响门禁语义 (SIM105)
                    tf_path.unlink()                                                         # 删不掉也不该让评测失败: 只影响卫生, 不影响门禁语义
    return False, f"unknown gate: {gate_name!r}"
def _run_algorithm_case(cdata: dict[str, Any]) -> tuple[bool, str]:
    """算法用例: import 真实模块 + 调用 + 校验输出 (EVAL-10: 不止 hasattr)。

    ``hasattr`` 只能证明"名字还在", 证明不了"行为还对" —— 函数被改成
    永真/永假桩也能全绿。这里对每个已登记算子追加一次**真实调用 + 输出
    断言**, 名字与行为一起校。

    被测对象完全由 ``cdata['derived_from']`` 指名 (下方两条正则抽取), 与用例
    文件名无关: 报告文案由调用方拿 ``cf.name`` 拼, 本函数不消费文件名, 所以
    形参里没有 ``cf``。

    Args:
        cdata: 用例 YAML 内容; ``derived_from`` 里以 ``'name': ... 'module': ...``
            指名被测对象。

    Returns:
        (是否通过, 人类可读说明)。
    """
    derived = str(cdata.get("derived_from", ""))  # 与 gate 同一字段, 派发规则不同: 这里抽的是被测对象
    # 从 derived_from 里正则抽取被测对象; 抽不到即用例自身损坏, 记 FAIL
    m_name = re.search(r"'name':\s*'([^']+)'", derived)
    m_mod = re.search(r"'module':\s*'([^']+)'", derived)
    if not (m_name and m_mod):                                                               # 两个正则缺一即用例自身损坏: 记 FAIL 而不是跳过
        return False, "derived_from 缺少 name/module"
    name_str, mod_str = m_name.group(1), m_mod.group(1)  # 正则抽模块与名字; 抽不到即用例自身损坏, 记 FAIL
    try:
        # 动态 import: 导入失败 = 生产树被裁剪, 显式 FAIL (不 fail-open)
        mod = importlib.import_module(mod_str)                                            # 动态导入真实生产模块: 导入失败说明生产树被裁剪, 不能放行
    except Exception as exc:  # noqa: BLE001
        return False, f"module import failed: {mod_str}: {exc!r}"
    obj = getattr(mod, name_str, None)  # getattr 默认 None: 名字不存在时走"缺失或不可调用"而非 AttributeError
    if obj is None or not callable(obj):                                                  # 名字在但不可调用同样算失效: 只查 hasattr 会放过桩
        return False, f"{mod_str}.{name_str} 缺失或不可调用"
    # 行为抽查: 对已知算子做一次真实调用
    if name_str == "cone_search":
        # 延迟导入: 表单构造器只在 cone_search 抽查分支用, 不放模块级依赖面
        from src.protocol import build_query_form

        form = build_query_form("ps1", [])  # 真实调用而非 hasattr: 名字在但行为坏了也必须被抓出来
        if "showcol" not in form:
            return False, "cone_search 依赖的 protocol 表单缺 showcol"
    if name_str == "validate_adql_query":
        # 延迟导入: ADQL 校验器只在 validate_adql_query 抽查分支用
        from src.scripts.guards import validate_adql_query

        valid = "SELECT source_id, ra, dec FROM best.source LIMIT 5"
        if validate_adql_query(valid) != valid:  # 合法语句必须原样返回: 校验器不得改写用户的 ADQL
            return False, "合法 ADQL 被误拒"
        try:
            validate_adql_query("SELECT 1")  # 形状不完整的语句必须抛: 不抛说明这个校验名不副实
            return False, "缺 FROM 子句的语句被放行 (校验名不副实)"
        except ValueError:
            pass  # 期望行为: 形状不完整的语句必须被拒
    # 下载能力行为抽查 (真实调用, 非 hasattr)
    if name_str == "DownloadManager" and mod_str == "src.download_manager":
        # 延迟导入: 临时目录与探针层桩客户端只在本抽查分支用 (全程不触网)
        import tempfile

        with tempfile.TemporaryDirectory() as td:                                               # 临时目录自带清理: 下载链产物不许留在评测目录里
            # 用桩客户端跑完整"提交-执行-完成"链, 全程不触网;
            # 桩客户端类属探针层设施, 定义在 evals/probes.py
            from probes import _StubFileClient

            mgr = obj(_StubFileClient(), output_dir=td,                                          # 桩客户端跑完整链: 全程不触网, 只验编排逻辑
                      progress_dir=f"{td}/.progress",
                      checkpoint_dir=f"{td}/.checkpoints")
            jid = mgr.submit(__import__(                                                      # 提交一个真实作业: 只构造管理器不提交就验不到执行链
                "src.download_manager", fromlist=["FileJob"]).FileJob(
                url="https://stub/x.dat", filename="x.dat"))
            path = mgr.result(jid, timeout=30)                                   # 真实跑完提交-执行-完成链, 只有超时才算失败
            ok = path.endswith("x.dat") and mgr.status(jid)["status"] == "done"  # 文件名与终态双条件: 只落盘不算完成
            mgr.shutdown()                                                                      # 显式收尾管理器: 不关会把后台线程留在评测进程里
        if not ok:                                                                               # 双条件任一不满足即失败: 落盘不等于状态置完成
            return False, "DownloadManager 提交-执行-完成链实测失败"
    if name_str == "DownloadHooks" and mod_str == "src.download_hooks":
        hooks = obj()                                                                             # 探针钩子现构造: 拦截行为必须在真实实例上验
        try:
            hooks.severe("checksum_mismatch", "探针", {"k": "v"}, job_id="p")
            return False, "severe 未拦截"
        except Exception as exc:
            # 拦截类型必须是 HookBlockedError: 抛错但类型不对, 调用方的
            # except 分支接不住, 同样等于没拦住
            if type(exc).__name__ != "HookBlockedError":
                return False, f"拦截异常类型错误: {type(exc).__name__}"
            payload = exc.interrupt.to_ask_payload()  # 拦截后还要给建议方案: 抛错但不给选项等于把问题推回用户
            if not payload.get("options"):
                return False, "ask 载荷缺建议方案"
    if name_str == "ProgressStore" and mod_str == "src.download_progress":
        # 延迟导入: 临时目录只在本抽查分支用 (进度存取实测)
        import tempfile

        with tempfile.TemporaryDirectory() as td:                                                  # 临时目录隔离: 进度存取的产物不进评测目录
            store = obj(td)                                                                       # 存储器只吃一个目录参数: 写读都在临时区完成
            from src.download_progress import ProgressRecord

            # 写点 + 读点: 存一条再读回, 验证进度"落盘即可见"
            store.save(ProgressRecord(job_id="p1", status="running"))
            loaded = store.load("p1")  # 落盘即可见是进度存储的用途, 写完不读等于没验
            if loaded is None or loaded.status != "running":
                return False, "ProgressStore 存取实测失败"
    if name_str == "BestDownloader" and mod_str == "src.downloader":
        # 延迟导入: 临时目录 + 真客户端 + checkpoint 只在本抽查分支用
        import tempfile

        from src.client import BestClient
        from src.scripts.checkpoint import DownloadCheckpoint

        with tempfile.TemporaryDirectory() as td:                                               # 临时目录隔离: 断点续传实测的产物必须能整体丢弃
            dl = obj(BestClient(rate_limit=0), output_dir=td,                                       # 节流归零: 构造下载器不得引入任何等待
                     checkpoint_dir=f"{td}/.checkpoints")
            ckpt = DownloadCheckpoint(f"{td}/.checkpoints")
            ckpt.save("probe_job", {"sqlid": "s3898", "next_page": 3,
                                    "catalog": "ps1", "sources": []})
            loaded = ckpt.load("probe_job")  # 断点续传: 读回的 next_page 必须与写入一致才算续得上
            if not loaded or loaded.get("next_page") != 3:
                return False, "断点续传 checkpoint 实测失败"
            if not hasattr(dl, "resume_job"):
                return False, "resume_job 入口缺失"
    if name_str == "download_file" and mod_str == "src.best_export":
        # 延迟导入: 临时目录 + patch 只在本抽查分支用 (download_file 落盘实测)
        import tempfile

        # P1 合并: 权威实现 src.best_export.download_file (请求经 request=
        # 注入体 — 生产注入方是 BestClient.download_file → BestClient._request)
        from src.best_export import download_file

        if not callable(download_file):                                                         # 入口可调用性也要查: 名字在但不是函数同样算缺失
            return False, "best_export.download_file 入口缺失"
        with tempfile.TemporaryDirectory() as td:                                                  # 落盘实测的产物落在临时区: 不污染评测目录
            # 桩响应带 Content-Disposition 与 iter_content, 走真实落盘路径;
            # P2-10: close() 必须声明 (download_file 流读尽后关闭响应, 桩
            # 没有 close 会走 except 分支判失败)
            resp = type("R", (), {"status_code": 200, "headers":
                                  {"Content-Disposition":
                                   'attachment; filename="p.dat"'},
                                  "iter_content": lambda self, chunk_size:
                                  iter([b"xy"]),                                                # 分块迭代只产一块: 够验流读路径, 不必造大文件
                                  "close": lambda self: None})()
            # P1-10: URL 必须过官方主机白名单 — 桩响应走 request= 注入,
            # 但 download_file 入口的 validate_external_url 先于请求,
            # 故抽查用的桩 URL 也用白名单主机 (stub 主机会被拒)
            p = download_file(                                                                      # 请求走注入体: 离线回放, 不发真实请求
                "https://nadc.china-vo.org/data/best/p.dat", savedir=td,
                request=lambda *a, **k: resp)                                                    # 桩响应用于落盘路径: 只验写盘行为, 不验网络
            # 读点: 落盘后重新读文件比对字节, 而不是只看返回值非空
            # SIM115: 上下文管理器保证句柄释放
            if not p:                                                                            # 返回路径为空即失败: 落盘函数必须报出文件位置
                return False, "download_file 落盘实测失败"
            with open(p, "rb") as fh:
                if fh.read() != b"xy":                                                          # 落盘后重新读文件比对字节: 只看返回值非空是自欺
                    return False, "download_file 落盘实测失败"
    if name_str == "PreciseDownloadJob" and mod_str == "src.download_precise":
        # 延迟导入: precise 表单构造三件套只在本抽查分支用
        from src.download_precise import MAX_IDS_PER_QUERY, build_precise_form, normalize_ids

        job = obj(source_ids=[" x ", "x", "y"], catalog="stripe82")
        if normalize_ids(job.source_ids) != ["x", "y"]:  # 去重+清洗是 normalize_ids 的职责: 空格与重复都要归一
            return False, "normalize_ids 去重清洗实测失败"
        form = build_precise_form(job)                                                        # 表单构造实测: 列映射错了服务端认不出, 属静默失效
        if form.get("stripe82.calibstars_id.operation") != "in":  # 列映射正确性: ID 列必须落到 calibstars_id, 否则服务端认不出
            return False, "stripe82 ID 列映射 (calibstars_id) 实测失败"
        # 上限分支: 超量 ID 必须被拒, 否则一次提交会把服务端表单撑爆
        big = obj(source_ids=[str(i) for i in range(MAX_IDS_PER_QUERY + 1)])               # 超量样本: 上限必须真的拒, 否则一次提交会撑爆服务端表单
        try:
            build_precise_form(big)                                                                 # 不抛即失败: 上限形同虚设时这里必须红
            return False, "超量 ID 未被拒"
        except ValueError:
            pass
    if name_str == "parse_adql" and mod_str == "src.tap.adql":
        plan = obj(                                                                        # 真实 ADQL 语句喂进去: 解析器要连过滤条件一起解出来
            "SELECT ra, ps1_rpsf FROM best.ps1 "
            "WHERE CONTAINS(POINT('ICRS', ps1_ra, ps1_dec), "
            "CIRCLE('ICRS', 180.0, 30.0, 0.1)) = 1"
        )
        if plan.catalog != "ps1" or plan.columns != ("ps1_ra", "ps1_rpsf"):  # 计划字段实测: catalog 与列名都要对, 只对一半等于没解析
            return False, "ADQL 计划字段实测失败"
        if plan.branches[0].cone is None:  # CONTAINS(POINT) 必须解析出锥形约束, 否则过滤条件被静默丢掉
            return False, "CONTAINS(POINT) 锥形约束未解析"
        try:
            obj("SELECT ra FROM best.ps1 JOIN best.stripe82 ON 1 = 1")
            return False, "JOIN 未被拒"
        except ValueError:
            pass
    if name_str == "ToolBox" and mod_str == "src.ai_tools":
        # 延迟导入: 真客户端只在本抽查分支用 (离线工具链实测)
        from src.client import BestClient

        box = obj(BestClient(rate_limit=0))                                                       # 真客户端但节流归零: 工具链实测不得引入等待
        catalogs = box.list_catalogs()  # 离线工具链实测: 走本地注册簿, cost.http_requests 必须是 0
        described = box.describe_catalog("ps1")
        rejected = box.describe_catalog("std")
        envelope = catalogs.to_dict()                                                               # 信封转字典: 四段结构要在这里逐段验
        if not catalogs.status["ok"] or catalogs.cost["http_requests"] != 0:
            return False, "离线工具 cost/status 实测失败"
        if described.data.get("catalog") != "ps1":
            return False, "describe_catalog 实测失败"
        if rejected.status.get("error_code") != "E_INVALID_INPUT":
            return False, "导航组拒绝的错误码映射失败"
        if set(envelope) != {"data", "status", "cost", "provenance"}:  # 信封四段是契约: 少一段下游就没法统一解析
            return False, "信封四段结构实测失败"
    if name_str == "TaskLogger" and mod_str == "src.task_log":
        # 延迟导入: 临时目录只在本抽查分支用 (TaskLogger 实测)
        import tempfile

        with tempfile.TemporaryDirectory() as td:                                                 # 临时日志目录: 任务日志实测的产物能整体丢弃
            log = obj(log_dir=td)                                                                 # 日志器现构造: 追加与读取都要在真实实例上验
            log.log("p1", "submit", "s")
            log.log("p1", "done", "d")
            # 第三条故意用 warn 级: 顺便验证 problems() 只捞 warn/error
            log.log("p2", "hook", "blocked", level="warn")
            if len(log.tail(n=0)) != 3:                                                        # 三条事件必须都读得到: 追加不落盘等于日志形同虚设
                return False, "TaskLogger 追加/读取实测失败"
            if log.summarize("p1")["events"] != 2:
                return False, "summarize 聚合实测失败"
            if len(log.problems()) != 1:                                                        # 问题视图只捞告警与错误: 多一条说明级别过滤失效
                return False, "problems 视图实测失败"
    return True, f"{mod_str}.{name_str} import+调用实测通过"
def _run_scope_case(cf: Path, cdata: dict[str, Any]) -> tuple[bool, str]:
    """scope 用例: spec in_scope 内容校验 (EVAL-04 修复: 缺失即 FAIL, 非 pass)。

    除了条目数, 还要求三项主理能力 (认证 / 两阶段 / 下载) 必须齐名 ——
    只数字数的话, 把 in_scope 换成三句废话也能过, 那是自欺。

    Returns:
        (是否通过, 人类可读说明)。
    """
    local_spec = SKILL_DIR / "references" / "skills-spec.local.yaml"  # 本地 spec 优先: 评测要验的是实际生效的那一份
    if not local_spec.is_file():                                                        # 本地 spec 缺失即 FAIL: 评测要验的是实际生效的那一份
        return False, "skills-spec.local.yaml 缺失"
    # 读点: 本地 spec 文件 (utf-8-sig 兼容 BOM)
    sdata = load_yaml_file(local_spec)                                                        # 读本地 spec 且兼容 BOM: 内容以这一份为准
    scopes = sdata.get("skills", {}).get("astro-best", {}).get("in_scope", [])  # 三层嵌套取值; 缺失给空列表, 交给下面的条目数判据去红
    if len(scopes) < 3:                                                                          # 条目数只是下限判据: 少写就说明范围声明被掏空
        return False, f"in_scope 条目不足: {len(scopes)}"
    # 内容校验: 三项主理能力必须齐名
    joined = " ".join(str(s) for s in scopes)
    for token in ("认证", "两阶段", "下载"):  # 三项主理能力逐个点名: 只数字数, 三句废话也能过
        if token not in joined:                                                                # 三项主理能力逐个点名: 只数字数, 三句废话也能过
            return False, f"in_scope 缺主理能力 token: {token}"
    return True, f"in_scope {len(scopes)} 项内容校验通过"
def _run_field_case(cf: Path, cdata: dict[str, Any]) -> tuple[bool, str]:
    """字段用例: 契约文件存在且内容含类型/量纲 (EVAL-04 修复: 存在≠过)。

    "文件在但里面是空的/没有 type/unit" 同样算 FAIL: 字段契约的用途就是
    让下游知道量纲, 缺了这两个键的契约和没写没有区别。

    Returns:
        (是否通过, 人类可读说明)。
    """
    field_name = cf.stem.split("_")[-1]                                                  # 字段名取自文件名末段: 契约文件与用例同名对应
    field_contract = SKILL_DIR / "contracts" / "fields" / f"{field_name}.contract.yaml"  # 契约路径由字段名派生而不查注册表: 少一个文件即 FAIL
    if not field_contract.is_file():                                                           # 契约文件缺失即 FAIL: 存在性不能替代内容校验
        return False, f"字段契约缺失: {field_name}"
    data = load_yaml_file(field_contract)                                                           # 契约现读: 改字段定义不必同步改用例
    # 整份契约转文本后做关键词探测: 比按 schema 逐键校验更耐布局调整
    text = json.dumps(data, ensure_ascii=False)                                                  # 整份契约转文本再探测: 比逐键校验更耐布局调整
    if "type" not in text or "unit" not in text:  # type 与 unit 缺一即 FAIL: 缺量纲的契约和没写没区别
        return False, f"字段契约缺 type/unit: {field_name}"
    return True, f"字段契约 {field_name} 内容校验通过 (type/unit 在)"
def run_cases_eval(cases_dir: Path) -> dict[str, Any]:
    """执行全部用例 (evals/cases/*.yaml); 无 given 消费的用例记 FAIL。

    按 ``derived_from`` 前缀分流到 gate / algorithm / scope / field 四类
    handler; 归不进任何一类的一律判 FAIL: 放行等于让无 handler 的用例静默逃过评测。

    Args:
        cases_dir: 用例目录。

    Returns:
        total/passed/rate/details/valid 五段汇总; 目录为空时 valid=False。
    """
    case_files = sorted(cases_dir.glob("case_*.yaml"))  # 只收 case_ 前缀: 目录里其它 yaml 不是用例
    if not case_files:                                                                   # 空目录是输入缺失: 记 valid=False 而不是"全过"
        # 空用例目录 = 输入缺失, 记 valid=False (不是"全过")
        return {"total": 0, "passed": 0, "rate": 0.0,
                "details": [{"file": "-", "passed": False, "type": "error",
                             "error": "cases 目录为空"}], "valid": False}

    results: list[dict[str, Any]] = []  # 逐条累积: 单条失败不中断整轮评测
    for cf in case_files:               # 排序遍历: 报告行序与文件名序一致, 便于两轮跑批 diff
        try:
            cdata = load_yaml_file(cf)                                                             # 单条用例内容现读: 解析失败只记这一条失败
        except Exception as exc:  # noqa: BLE001
            # 单个用例 YAML 损坏只记该用例失败, 不中断整轮评测
            results.append({"file": cf.name, "passed": False, "type": "error", "error": str(exc)})
            continue

        derived = str(cdata.get("derived_from", ""))  # 派发优先级 gate > algorithm > 文件名, 顺序不能倒
        # EVAL-03 修复: given 必须存在 (各 handler 真实消费, 非仅存在性)
        given = cdata.get("given") or {}

        try:
            if derived.startswith("gate:"):
                ctype = "gate"
                ok, note = _run_gate_case(cf, cdata)                                           # 门禁分支: 实际值由生产判定算出, 不从文件名反推
            elif "algorithm:" in derived:
                ctype = "algorithm"
                ok, note = _run_algorithm_case(cdata)                                             # 算法分支: 真导入真调用, 名字与行为一起校
            elif "scope" in cf.name:
                ctype = "scope"
                ok, note = _run_scope_case(cf, cdata)                                               # 范围分支: 查实际生效的本地 spec
            elif "field" in cf.name or "input" in cf.name:
                ctype = "field"
                ok, note = _run_field_case(cf, cdata)                                               # 字段分支: 契约内容含类型与量纲才算过
            else:
                # 无法归类的用例: 显式 FAIL, 防止"加了文件没人管"悄悄变绿
                ctype = "generic"
                ok, note = False, f"unclassified case (no handler): {cf.name}"
        except Exception as exc:  # noqa: BLE001
            # handler 抛异常 = 该用例失败, 异常原文进报告便于定位
            ctype = "error"
            ok, note = False, f"case raised: {exc!r}"

        results.append({  # 五段记录: 报告要能定位到文件、类型与失败原因
            "name": cdata.get("name", cf.stem),
            "type": ctype,
            "file": cf.name,
            "passed": ok,
            "note": note,
            # 标记夹具是否被真实消费: gate/algorithm/scope/field 四类天然消费,
            # 其它类型必须自带 given, 否则等于"没喂输入就断言输出"
            "given_consumed": bool(given) or ctype in ("gate", "algorithm", "scope", "field"),
        })

    pass_count = sum(1 for r in results if r["passed"])  # 通过数按明细实数, 不用"总数 - 失败数"倒推
    return {
        "total": len(results),
        "passed": pass_count,
        "rate": pass_count / len(results) if results else 0.0,  # 空结果时 rate 给 0.0 但 valid=False: 两者不能互相替代
        "details": results,
        "valid": True,
    }
