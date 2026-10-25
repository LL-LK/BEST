# -*- coding: utf-8 -*-
"""ops/live_fetch.py 的**控制台编码稳健性**回归 (H5-05)。

守的缺口形态: 铁律 7 把"默认 dry-run, 先看计划再决定要不要跑"定为纪律, 于是
``python ops/live_fetch.py --set X`` 是用户按文档第一次试的命令。它在 Windows
默认控制台 (GBK) 上**开箱即崩** —— H5-05 实测:

    File "ops/live_fetch.py", line 433, in main
      print(f"    ! {cat}: {note}")
    UnicodeEncodeError: 'gbk' codec can't encode character '\\xb2'

肇因是 ``COVERAGE_NOTES`` 里 landolt 那条含 ``²`` (U+00B2), GBK 编不出。
注意崩的不是 ``--execute`` 的真抓路径, 而是**一个请求都不发的预览路径** ——
恰恰是纪律要求用户先走的那一步。

为什么测 stdout 而不用子进程: 这里要断的是"``main()`` 落到 GBK 流上不抛",
把流换掉直接调 ``main()`` 才是同一判据; 起子进程反而会把
``PYTHONIOENCODING`` 之类的环境因素掺进来, 测的就不是这一件事了。

用**真的** ``TextIOWrapper(encoding="gbk", errors="strict")`` 而不是假对象:
只有真编码器才会复现 UnicodeEncodeError。假对象永远不抛, 那样的测试恒绿。

本件放在 ``test/unit/meta/`` 是因为它是仓库级工具的回归, 且 ``test/unit/ops/``
尚不存在 (新建目录要动 README 树清单, 超出本轮范围)。
"""
from __future__ import annotations

# 标准库: importlib 按路径装载 ops/ 件 (ops/ 不是包) / io 造 GBK 真流 /
#         sys 路径锚定与流替换 / pathlib
import importlib.util
import io
import sys
from pathlib import Path
from typing import Any

SKILL_ROOT = Path(__file__).resolve().parents[3]  # 仓根: 本件在 test/unit/meta/ 下三级
if str(SKILL_ROOT) not in sys.path:  # 幂等: 与 test/conftest.py 同一纪律, 不重复插
    sys.path.insert(0, str(SKILL_ROOT))

# 被测文本里那个 GBK 编不出的字符 —— 断言"它被降级替换了", 而不是"它没被打印"。
UNENCODABLE = "²"  # SUPERSCRIPT TWO, U+00B2


def _load_live_fetch() -> Any:
    """按路径装载 ops/live_fetch.py (ops/ 不是包, 只能这样加载; 与 CLI 同口径)。"""
    spec = importlib.util.spec_from_file_location(                       # 路径装载 spec
        "live_fetch_under_test", SKILL_ROOT / "ops" / "live_fetch.py")   # 被测件路径
    module = importlib.util.module_from_spec(spec)                        # 先建模块对象
    spec.loader.exec_module(module)                                      # 再执行模块体
    return module                                                         # 交回调用方


def _gbk_stdout() -> tuple[io.TextIOWrapper, io.BytesIO]:
    """造一条真的 GBK 标准输出流 (errors=strict, 与崩溃时的环境同形)。

    为什么要 strict: 被测函数正是要把它改成 replace。若一开始就宽松, 这条
    测试恒绿 —— 测的就不是"有没有兜底", 而是"本来就编得过"。
    """
    buf = io.BytesIO()                                    # 字节底: TextIOWrapper 写进来的是 GBK 字节
    return io.TextIOWrapper(buf, encoding="gbk", errors="strict"), buf   # 严格 GBK = 复现现场


class TestDryRunSurvivesGbkConsole:
    """默认 dry-run 路径在 GBK 控制台上必须跑完, 不得抛 UnicodeEncodeError。"""

    def test_dry_run_does_not_crash_on_gbk_stdout(self, tmp_path, monkeypatch):
        """G2 实测的那条命令, 换一条真 GBK 流, 必须返回 0 且不抛。

        不设 ``PYTHONIOENCODING``: 崩溃的成因正是控制台编码, 用环境变量把它
        绕过去就等于把被测的那件事删掉了。
        """
        lf = _load_live_fetch()          # 每次现载: 模块级状态 (sys.path 注入) 不跨用例污染
        stream, buf = _gbk_stdout()      # 真 GBK 严格流
        monkeypatch.setattr(sys, "stdout", stream)  # print() 动态查 sys.stdout, 换掉即生效
        monkeypatch.setattr(sys, "stderr", stream)  # usage/报错同理, 一起换干净

        rc = lf.main(["--set", "sentinel", "--out", str(tmp_path)])  # 不带 --execute = 默认 dry-run

        stream.flush()
        out = buf.getvalue().decode("gbk", "replace")
        assert rc == 0, f"dry-run 必须正常返回 0, 实得 {rc}"
        assert "DRY-RUN" in out, f"dry-run 计划必须真的打印出来, 实际输出: {out[-300:]}"
        assert "landolt" in out, f"崩溃点正是 landolt 那条 note, 它必须被打印: {out[-300:]}"

    def test_unencodable_char_is_degraded_not_dropped(self, tmp_path, monkeypatch):
        """编不出的字符必须**降级替换**, 不能整条 note 消失。

        只断"不崩"不够: 悄悄把那条 note 跳过也是"不崩", 而它恰恰是解释
        "为什么 landolt 不在本批计划内"的那条。所以断替换字符真的落到输出里。
        """
        lf = _load_live_fetch()           # 现载: 模块级状态不跨用例污染
        stream, buf = _gbk_stdout()       # 真 GBK 严格流 = 复现现场
        monkeypatch.setattr(sys, "stdout", stream)  # print() 动态查 sys.stdout
        monkeypatch.setattr(sys, "stderr", stream)  # usage/报错同理, 一起换干净

        lf.main(["--set", "sentinel", "--out", str(tmp_path)])

        stream.flush()
        out = buf.getvalue().decode("gbk", "replace")
        # GBK 用 "?" 替换编不出的字符 (errors="replace" 的默认替换符)
        assert "deg?" in out, f"U+00B2 应被降级成 '?', 实际输出尾部: {out[-300:]}"
        # 对照: 前后文必须完好 —— 是"这个字降级了", 不是"这段被砍了"
        assert "45712" in out, "note 的其余内容必须完整保留"


class TestMakeConsoleSafeIsSelfContained:
    """``make_console_safe`` 本身的边界 —— 拿不到能力时不得抛。"""

    def test_stream_without_reconfigure_is_returned_unchanged(self):
        """``io.StringIO`` 没有 reconfigure: 原样返回, 不得抛 AttributeError。

        这条是"不主动抛"契约的落点: 拿不到 reconfigure 能力是常态 (测试替身、
        被 detach 的流), 那是环境事实, 不是缺陷。
        """
        lf = _load_live_fetch()
        sio = io.StringIO()                 # 没有 reconfigure 的流
        assert lf.make_console_safe(sio) is sio, "不支持 reconfigure 的流必须原样返回"

    def test_encoding_is_not_rewritten(self):
        """只改 errors, **不碰 encoding** —— 编码是环境事实, 不该由工具改写。"""
        lf = _load_live_fetch()
        stream, _buf = _gbk_stdout()        # 工具要改的就是这条流
        try:
            lf.make_console_safe(stream)
            assert stream.errors == "replace", f"errors 必须被改成 replace, 实得 {stream.errors!r}"
            assert stream.encoding.lower().replace("-", "") == "gbk", (
                f"encoding 必须保持环境原值 gbk, 实得 {stream.encoding!r} —— "
                "工具擅自改编码会把用户终端显示搞乱"
            )
        finally:
            stream.detach()  # 不 detach 会让 BytesIO 在 GC 时报 unclosed


class TestCoverageNoteStillCarriesTheRealReason:
    """兜底不能变成"把难看的字删掉" —— note 的事实内容必须仍在源码里。"""

    def test_landolt_note_keeps_its_degree_squared_marker(self):
        """那条 note 里必须有编不出的字符, 否则这条回归测试会自我消解。

        反向锁: 哪天有人"顺手"把 ``²`` 改成 ``deg^2`` 让 GBK 编得过, 崩溃是
        没了, 但上面两条用例也就失去了被测对象 —— 那等于把回归门禁自己废掉。
        """
        lf = _load_live_fetch()           # 现载: 与上面两条同口径
        assert UNENCODABLE in lf.COVERAGE_NOTES["landolt"], (
            "landolt note 里的 U+00B2 被改掉了 —— 那条 note 的 GBK 崩溃回归就"
            "不再有被测对象, 请连同本文件一起重估 (别只是把字符改好看)"
        )
