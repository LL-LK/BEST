# -*- coding: utf-8 -*-
"""E5 三项隔离门禁 (答案键隔离 / 批次唯一 / 并发写保护) 的回归用例。

**为什么这批用例必须存在**: 三项门禁原先只有实现、没有测试, 且实现只活在 gitignored 的
``temp/`` 里 —— 于是"改坏了不会有人知道", 这正是 D-17/D-18 的共同形状 (我以为禁住了)。
本文件把三条门禁**钉在判据上**: 每条都先造出失效形态, 再断言被挡回。少了任一条,
相应的门禁就退回成"口头纪律"。

**覆盖**:
  * 答案键隔离 —— scratch 落点在仓外 (够不着答案键) + 投放内容含禁词即撤销;
  * 批次唯一 —— 复用批次名被挡 (含并发抢占的原子性);
  * 并发写保护 —— 写锁互斥 + 轨迹同名拒写 + 原子提交不留半截 + 报告内撞键判错;
  * 后验审计 —— 单写者判据能抓出双写者批 (用造出来的双簇 mtime 反证)。
"""
from __future__ import annotations

# 标准库: 把时钟搬到过去 (造双写者时间簇)
import os

# 标准库: pytest 夹具
import pytest

from evals.ablation.harness.run_batch import (  # 被测: 轨迹落盘的三条并发判据
    _acquire_trace_lock,  # 目录锁: 抢不到即拒
    _release_trace_lock,  # 释放锁: 幂等
    write_traces,  # 轨迹落盘: 原子提交与拒覆盖
)
from evals.ablation.iso import audit, paths, stage  # 被测: 隔离投放与后验审计

PROMPT_TEXT = "你是天文数据检索装配体。给定请求, 决定路由与工具调用。\n"  # 夹具提示词: 干净, 不含任何禁词


@pytest.fixture
def scratch(tmp_path, monkeypatch):
    """把 scratch 根指到 tmp_path, 并把提示词源也换成夹具目录。"""
    root = tmp_path / "e5_scratch"  # 隔离根: 单测不碰真实的 %TEMP%\e5_scratch
    monkeypatch.setenv(paths.ENV_SCRATCH, str(root))  # 换根: 走 SSOT 的覆盖通道, 不打全局状态
    prompts = tmp_path / "decision_iso" / "B3"  # 提示词夹具: 两个格子, 够造批也够造命中
    prompts.mkdir(parents=True)
    (prompts / "E5-D01.txt").write_text(PROMPT_TEXT, encoding="utf-8")
    (prompts / "E5-D02.txt").write_text(PROMPT_TEXT, encoding="utf-8")
    monkeypatch.setenv(paths.ENV_PROMPTS, str(prompts.parent))  # 提示词源: 同样走覆盖通道
    return root


def test_scratch_root_default_is_outside_repo():
    """默认 scratch 根必须在仓库之外 —— D-17 的结构性判据, 不是禁令。"""
    root = paths.scratch_root()  # 默认落点: 系统临时目录下
    paths.assert_outside_repo(root)  # 不抛即通过: 向上逐层都够不到仓根与答案键


def test_scratch_inside_repo_is_refused(monkeypatch):
    """把 scratch 硬指到仓内必须被拒 —— 断言本身就是门禁, 不是提示。"""
    inside = paths.ABLATION_DIR / "scratch"  # 造一个"向上两级就是答案键"的位置 (D-17 的原形状)
    monkeypatch.setenv(paths.ENV_SCRATCH, str(inside))
    with pytest.raises(ValueError):  # fail-closed: 位置不对就不许投放
        paths.assert_outside_repo(paths.scratch_root())


def test_batch_reuse_is_refused(scratch):
    """复用批次名必须被挡 —— D-18 的直接防护 (批次唯一)。"""
    stage.stage_batch("b_x", ["B3"])  # 第一次投放: 成功
    with pytest.raises(stage.BatchBusy):  # 同名再来一次: 必须挡回, 不许静默覆盖
        stage.stage_batch("b_x", ["B3"])


def test_force_overwrites_and_rewrites_owner(scratch):
    """--force 允许覆盖一个**没有开着会话**的批次, 且必须留下**新**的写者标记。"""
    stage.stage_batch("b_y", ["B3"])  # 首投: 建立写者标记
    first_token = stage.read_owner("b_y")["token"]  # 记住首投令牌
    stage.stage_batch("b_y", ["B3"], force=True)  # 强制覆盖: 没有开着的会话, 允许
    owner = stage.read_owner("b_y")  # 读回标记: 必须还在, 否则后验审计会判"无主"
    assert owner is not None and owner["batch"] == "b_y"  # 有主: 覆盖后仍可归属
    assert owner["token"] != first_token  # 新令牌: 换过主人这件事本身要有证据


def test_answer_key_in_prompt_revokes_staging(scratch):
    """投放内容里出现答案键物料 → 整批撤销 (fail-closed, 不留半截给代理读)。"""
    leaky = paths.prompt_root() / "B3" / "E5-D02.txt"  # 污染一格: 注入禁词 expect_tools
    leaky.write_text(PROMPT_TEXT + "expect_tools: [cone_search]\n", encoding="utf-8")
    with pytest.raises(stage.AnswerKeyLeak):  # 命中即抛: 不许"大致干净就往下跑"
        stage.stage_batch("b_leak", ["B3"])
    assert not paths.batch_dir("b_leak").exists()  # 已撤销: 目录不该留下


def test_only_limits_cells_in_manifest(scratch):
    """--only 只投放指定格 —— 目录里看不到别的题, 族标签无从推断。"""
    dst = stage.stage_batch("b_only", ["B3"], only=["E5-D01"])  # 只投一格
    manifest = (dst / stage.MANIFEST_FILE).read_text(encoding="utf-8")
    assert "E5-D01" in manifest and "E5-D02" not in manifest  # 清单里没有别的题号
    assert len(list((dst / "prompts" / "B3").glob("*.txt"))) == 1  # 目录里也只有那一格


def test_trace_lock_is_exclusive(tmp_path):
    """两个写者抢同一个轨迹目录: 第二个必须被挡 (并发写保护)。"""
    target = tmp_path / "runs"  # 轨迹根: 单测目录, 不污染包内
    target.mkdir()
    _acquire_trace_lock(target)  # 第一个写者占住
    with pytest.raises(RuntimeError):  # 第二个: 抢不到即拒, 不排队也不覆盖
        _acquire_trace_lock(target)
    _release_trace_lock(target)  # 释放: 幂等
    _acquire_trace_lock(target)  # 再抢: 锁已放回, 应当成功
    _release_trace_lock(target)


def test_write_traces_refuses_overwrite(tmp_path):
    """同名轨迹默认拒写 —— "只增不改"从此有执行者, 不再是句注释。"""
    report = {"runs": [{"system": "B3", "item": "E5-D01", "attempt": 1, "route": "answer"}]}
    first = write_traces(report, tmp_path)  # 首写: 成功
    assert len(first) == 1 and first[0].is_file()
    with pytest.raises(FileExistsError):  # 再写同名: 必须挡回, 旧轮次是数据不是缓存
        write_traces(report, tmp_path)
    again = write_traces(report, tmp_path, overwrite=True)  # 显式允许: 才覆盖
    assert again == first  # 路径一致: 覆盖写的是同一个文件


def test_write_traces_rejects_duplicate_key(tmp_path):
    """同一报告内撞 (system, item, attempt) 即判错 —— 静默覆盖会让少一轮永远看不出来。"""
    report = {"runs": [{"system": "B3", "item": "E5-D01", "attempt": 1, "route": "answer"},
                       {"system": "B3", "item": "E5-D01", "attempt": 1, "route": "reject"}]}
    with pytest.raises(ValueError):  # 撞键即抛: 不靠调用方自查
        write_traces(report, tmp_path)
    assert len(list((tmp_path / "B3").glob("*.json"))) == 1  # 只落了第一条: 撞键处即停, 不假装跑完


def test_write_traces_leaves_no_partial_file(tmp_path):
    """原子提交: 目录里只留 .json 成品, 临时文件不得以 .json 后缀出现 (半截防吃)。"""
    report = {"runs": [{"system": "B3", "item": "E5-D01", "attempt": 1, "route": "answer"}]}
    write_traces(report, tmp_path)  # 正常落盘
    names = {p.name for p in (tmp_path / "B3").iterdir()}  # 目录快照: 只看文件名
    assert "E5-D01__a1.json" in names  # 成品在
    assert not any(n.endswith(".tmp") for n in names)  # 临时文件已提交或不存在: 不带 .json 后缀故不会被误吃


def test_single_writer_flags_two_wave_batch(scratch):
    """单写者判据必须抓出"两波写" —— 用造出来的双簇 mtime 反证 (D-18 的形状)。"""
    dst = stage.stage_batch("b_two", ["B3"])  # 投放两格
    out = dst / "out" / "B3"
    for name in ("E5-D01.json", "E5-D02.json"):  # 第一波: 时间往前搬, 与第二波拉开空档
        path = out / name
        path.write_text('{"route": "answer", "tool_calls": []}', encoding="utf-8")
        stamp = os.path.getmtime(path) - 600  # 往前搬十分钟: 造出 D-18 那样的双簇
        os.utime(path, (stamp, stamp))
    for name in ("E5-D03.json", "E5-D04.json"):  # 第二波: 保持当前时刻
        (out / name).write_text('{"route": "answer", "tool_calls": []}', encoding="utf-8")
    writer = audit.check_single_writer("b_two")  # 判单写者: 应抓到 600s 空档
    assert writer["suspect"] is True  # 判红: 空档远超 60s 阈值
    assert writer["max_gap_s"] > audit.DEFAULT_MAX_GAP_S  # 空档具体值回传: 便于排查


def test_audit_passes_clean_batch(scratch):
    """走完 begin→写→end 的干净批必须判过 —— 门禁不许变成"一律判红"。"""
    dst = stage.stage_batch("b_ok", ["B3"])  # 投两格
    stage.begin_write("b_ok")  # 开写会话: 单写者从此可证
    out = dst / "out" / "B3"
    for name in ("E5-D01.json", "E5-D02.json"):  # 同一秒内写完: 单波
        (out / name).write_text('{"route": "answer", "tool_calls": []}', encoding="utf-8")
    stage.end_write("b_ok")  # 收尾: 拍下指纹, 关会话
    result = audit.audit_batch("b_ok", expect=2)  # 判据全跑
    assert result["ok"] is True, result["problems"]  # 干净批不许被误判
    assert result["owner"] is not None  # 有主: 写者标记在


def test_audit_reds_when_owner_missing(scratch):
    """无写者标记即判红 —— 铁律 5: 扫不到就当干净是 fail-open。"""
    dst = stage.stage_batch("b_noowner", ["B3"])  # 投放后删掉标记, 模拟绕过投放器
    (dst / stage.OWNER_FILE).unlink()
    result = audit.audit_batch("b_noowner")  # 审计: 应判无主
    assert result["ok"] is False  # 判红
    assert any("无写者标记" in p for p in result["problems"])  # 指明具体项: 不只给个 False


def test_pid_alive_is_fail_closed_on_unknown():
    """判不出 pid 死活时按**活着**处理 —— 否则"以为死了就覆盖"会重演 D-18。"""
    assert stage.pid_alive(0) is True  # 非法 pid: 不冒险判死
    assert stage.pid_alive(-1) is True  # 同上
    assert stage.pid_alive(os.getpid()) is True  # 自己当然活着


def test_begin_write_blocks_second_writer(scratch):
    """D-18 的真实形态: 批次已投放后再派第二个代理 —— 第二个 begin_write 必须被挡。"""
    stage.stage_batch("b_w1", ["B3"])  # 投放: 批次名唯一
    stage.begin_write("b_w1")  # 第一个写者开会话
    with pytest.raises(stage.WriteSessionBusy):  # 第二个: 同批再开即拒 (这正是 D-18 的形状)
        stage.begin_write("b_w1")
    stage.end_write("b_w1")  # 关会话: 收尾指纹落盘
    stage.begin_write("b_w1")  # 会话关掉后可以再开 (合法的重跑/续跑)
    stage.end_write("b_w1")


def test_begin_write_refuses_foreign_token(scratch):
    """令牌不匹配即拒 —— pid 会被操作系统复用, 只有 token 能证明"你是这批的主人"。"""
    stage.stage_batch("b_tok", ["B3"])  # 投放: 生成一次性令牌
    with pytest.raises(stage.BatchBusy):  # 拿错令牌: 不许开写
        stage.begin_write("b_tok", token="不是我的令牌")


def test_begin_write_refuses_unstaged_batch(scratch):
    """未经投放的批次不许开写 —— 无主的写入无法归属。"""
    with pytest.raises(stage.BatchBusy):  # 没投过: 直接拒
        stage.begin_write("b_never")


def test_force_refuses_batch_with_open_session(scratch):
    """采集进行中 (写会话未关) 不得被 --force 覆盖 —— 那是一次主动的并发破坏。"""
    stage.stage_batch("b_live", ["B3"])  # 投放
    stage.begin_write("b_live")  # 开会话 = 有代理正在写
    with pytest.raises(stage.BatchBusy):  # force 也不许: 会话开着即不可覆盖
        stage.stage_batch("b_live", ["B3"], force=True)
    stage.end_write("b_live")  # 关会话后覆盖才合法
    stage.stage_batch("b_live", ["B3"], force=True)  # 此时可以


def test_force_begin_records_the_override(scratch):
    """强制清掉一个未关闭的会话必须**留痕** —— 不靠猜它死没死, 也不许静默清场。"""
    stage.stage_batch("b_fb", ["B3"])  # 投放
    stage.begin_write("b_fb")  # 第一个会话 (故意不关)
    with pytest.raises(stage.WriteSessionBusy):  # 默认: 第二个被挡
        stage.begin_write("b_fb")
    marker = stage.begin_write("b_fb", force=True)  # 显式授权: 才清掉旧的
    assert marker["forced"] is True  # 留痕: 这次是强制开的
    assert "started_at" in (marker["forced_from"] or {})  # 被清掉的那个会话也在记录里


def test_audit_reds_open_write_session(scratch):
    """写会话没关 = 采集未正常收尾 (或第二个写者还在写) —— 审计必须判红。"""
    stage.stage_batch("b_open", ["B3"])  # 投放
    stage.begin_write("b_open")  # 开会话但**不关**: 模拟采集中断
    result = audit.audit_batch("b_open")  # 审计
    assert result["ok"] is False  # 判红
    assert any("写会话未关闭" in p for p in result["problems"])  # 指明具体项
    stage.end_write("b_open")  # 收尾: 交回干净状态


def test_audit_reds_out_of_band_write(scratch):
    """写了**未分配**的格 = 越界写入 —— 分配清单就是为抓这条而落的。"""
    dst = stage.stage_batch("b_stray", ["B3"], only=["E5-D01"])  # 只分配 D01
    (dst / "out" / "B3" / "E5-D02.json").write_text(  # 却写了 D02
        '{"route": "answer", "tool_calls": []}', encoding="utf-8")
    result = audit.audit_batch("b_stray")  # 审计
    assert any("写了未分配的格" in p for p in result["problems"])  # 越界被抓到


def test_audit_reds_post_close_append(scratch):
    """收尾后又被追加写 —— 第二波写者最典型的痕迹, 必须判红。"""
    dst = stage.stage_batch("b_append", ["B3"])  # 投放
    (dst / "out" / "B3" / "E5-D01.json").write_text(  # 先写一个
        '{"route": "answer", "tool_calls": []}', encoding="utf-8")
    stage.begin_write("b_append")  # 开会话
    stage.end_write("b_append")  # 收尾: 拍下指纹
    (dst / "out" / "B3" / "E5-D02.json").write_text(  # 收尾之后又写了一个
        '{"route": "answer", "tool_calls": []}', encoding="utf-8")
    result = audit.audit_batch("b_append")  # 审计
    assert any("收尾后又新增" in p for p in result["problems"])  # 追加写被抓到


def test_audit_reds_without_finish_snapshot(scratch):
    """有输出却没收尾快照 = 没走 begin/end 流程, 单写者不可证 —— 判红。"""
    dst = stage.stage_batch("b_nosnap", ["B3"])  # 投放后直接写 (绕过会话)
    (dst / "out" / "B3" / "E5-D01.json").write_text(
        '{"route": "answer", "tool_calls": []}', encoding="utf-8")
    result = audit.audit_batch("b_nosnap")  # 审计
    assert any("无收尾快照" in p for p in result["problems"])  # 未按流程收尾即判红


def test_full_session_passes_clean_batch(scratch):
    """走完 begin→写→end 的干净批必须判过 —— 门禁不许变成"一律判红"。"""
    dst = stage.stage_batch("b_clean", ["B3"])  # 投放
    stage.begin_write("b_clean")  # 开会话
    for name in ("E5-D01.json", "E5-D02.json"):  # 写满分配的格
        (dst / "out" / "B3" / name).write_text(
            '{"route": "answer", "tool_calls": []}', encoding="utf-8")
    stage.end_write("b_clean")  # 收尾
    result = audit.audit_batch("b_clean")  # 审计
    assert result["ok"] is True, result["problems"]  # 全流程合规 -> 必须放行


def test_audit_root_matches_stage_root(scratch):
    """投放与审计必须解析到同一个根 —— 2026-10-11 的路径单边漂移事故不许重演。"""
    dst = stage.stage_batch("b_same", ["B3"])  # 投放器建出来的目录
    assert paths.batch_dir("b_same") == dst  # 审计器解析出来的必须是同一个
    assert paths.batch_dir("b_same").exists()  # 且它真的存在: 否则"没有该批次"又会空转


def test_audit_reports_missing_batch(scratch):
    """批次不存在必须判红, 不许因"没审到"就算过 (旧 audit 就是这么空转的)。"""
    result = audit.audit_batch("nope")  # 不存在的批次
    assert result["ok"] is False  # 判红: 缺数据不是干净数据
    assert any("没有该批次" in p for p in result["problems"])  # 指明原因: 与"审过但有问题"区分开
