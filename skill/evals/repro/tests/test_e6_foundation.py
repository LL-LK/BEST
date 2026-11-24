# -*- coding: utf-8 -*-
"""evals/repro/tests/test_e6_foundation.py — E6 输入面与统计守门 (拆分件 1/2)。

覆盖对照 (docs/eval-E6-reproducibility.md):
  §3   八项固定清单: 缺任一项 fail-closed / 齐备组装成功 / 同输入指纹一致 (确定性);
  §4   trace: 写入读回一致 / 脱敏红线 / 完整性校验 (seq 断号/头字段缺失/不配对/缺
        final_answer/凭据复扫) / 事件链 payload_fp 稳定;
  §2.1 回放路由: POST→phase1 html / getcount→总数 / page→CSV 原文 / 缺页→空表;
  §5.2 参数与结论卡归一 (正: 异写归一为同; 反: 列名全限定/kind/数值/实体);
  §5.5 Wilson 区间 / McNemar 精确检验 / Krippendorff α。

拆分缘由 (budget R2): 原单文件 743 净行超 400 预算 — 按"输入面/统计"与
"指标面"切两件, 共享夹具构造落 support_e6.py (无共享漂移)。
纪律: 只测不补; canary 值盲指纹与 payload_fp 写而不验两处真缺陷的修法,
各自钉在对应 test 的 docstring 里。

职责: 守住 E6 的**输入面与统计面** —— 固定清单八项的 fail-closed、trace 的
  脱敏与完整性、回放路由的保真、归一的口径边界, 以及三个统计量在已知
  样本上的取值。
所属实验: E6 可复现与效率 (32 任务 + R0 路实跑); 判据真值是
  docs/eval-E6-reproducibility.md §3 / §4 / §2.1 / §5.2 / §5.5, 本文件
  只断言代码与那几节一致, 不重新定义指标。
对外接口: 无 (pytest 收集面)。TestManifest / TestTrace / TestTransport /
  TestNormalize / TestStats 五个类, 分别对应上列五节。
依赖与数据流: 输入 = evals/repro/tests/support_e6.py 里共享的夹具构造
  (_valid_manifest / _write_trace / _mutated / _BASE_CARD 等) 与临时目录
  tmp_path; 产物 = pytest 断言结果, 不落盘、不联网。
关键契约与不变量: 全程离线 — 没有任何一条用例会发起真实请求, 回放全部
  走 evals/repro/transport.py; 零跨实验 import (只引 evals.repro.* 与
  临时构造的 requests 异常类型); 同一份代码重复跑必须得到同一结论, 所以
  这里不断言时间戳与墙钟的绝对值。跨实验等价性由 evals/equivalence/ 的
  断言守护, 本文件不重复造那份断言。
陷阱与边界: 三条 xfail 转正的用例 (canary 值盲 / payload_fp 写而不验 /
  结构外事件) 是本文件价值最高的部分 —— 它们对应三处真实漏检, 修复前
  靠 xfail 钉住, 修好后必须转正, 一旦有人为了让红变绿把它们改回 xfail,
  漏洞就会重新静默打开。test_module_matches_trace_schema_json 是防"代码
  与 schema 各改各的"的那道锁: 代码侧改了必填字段而 schema 没跟上, 报告
  里的机读校验就完全失效。
"""
from __future__ import annotations

# 标准库: 深拷贝 (清单变体) / JSON (报告与 schema) / 子进程编码 / 路径
import copy
import json
import subprocess
import sys
from pathlib import Path

# 第三方: pytest / requests (FakeResponse 抛 HTTPError 与真实 requests 同语义)
import pytest
import requests

# 本地: 被测模块 (输入面 §3/§4/§2.1/§5.2 与统计 §5.5)
from evals.repro.manifest import (  # noqa: E402
    REQUIRED_ITEMS,
    build_manifest,
    canary_fingerprint,
    load_manifest,
    save_manifest,
    sha256_file,
    sha256_text,
    validate_manifest,
)
from evals.repro.normalize import (  # noqa: E402
    cards_equal,
    norm_angle_deg,
    norm_args,
    norm_card,
    norm_radius_arcsec,
    strip_session_id,
)

# 本地: 编排入口 (清单与跑批的绑定面; 被测件)
from evals.repro.run_e6 import bind_manifest  # noqa: E402
from evals.repro.stats import (  # noqa: E402
    bootstrap_mean_ci,
    krippendorff_alpha_nominal,
    mcnemar_exact,
    mode,
    wilson_interval,
)
from evals.repro.tests.support_e6 import (  # noqa: E402
    _BASE_CARD,
    _BASE_HASH,
    _MODE_CARD,
    FIXTURES_DIR,
    REPRO_DIR,
    TOOLS_SCHEMA,
    _break_seq,
    _drop_final,
    _drop_header,
    _drop_result,
    _mutated,
    _valid_manifest,
    _write_manifest_file,
    _write_trace,
)
from evals.repro.trace import (  # noqa: E402
    EVENT_TYPES,
    FORBIDDEN_TOKENS,
    PAYLOAD_REQUIRED,
    TraceWriter,
    payload_fingerprint,
    read_trace,
    redact,
    validate_trace,
)
from evals.repro.transport import (  # noqa: E402
    FakeResponse,
    ReplayTransport,
)

# ── 1. manifest: 八项固定清单 ─────────────────────────────────────────────

class TestManifest:
    """八项指纹: 缺任一项 fail-closed / 齐备组装成功 / 同输入指纹相同 (确定性)。"""

    def test_valid_manifest_assembles_eight_items(self):
        """正: 八项齐备 → 组装成功且校验无阻断项 (可落盘)。

        作用: manifest 的基线正例。关键参数: 无 (夹具由 _valid_manifest
        构造)。Returns: None。抛什么: 断言失败即 pytest 失败, 不吞异常。
        """
        manifest = _valid_manifest()                                                # 夹具现构造: 八项齐备是本文件所有负例的基线, 共享实例会被删键用例污染
        # 用子集判定而非等值: environment 是第九块但不在 REQUIRED_ITEMS 里,
        # 等值比较会在合法地加块时误红
        assert set(REQUIRED_ITEMS) <= set(manifest)                         # 子集判定: environment 是第九块但不在必项表里, 等值比较会在合法加块时误红
        assert validate_manifest(manifest) == []      # 齐备时阻断项必须为空, 不是"少报也算过"

    @pytest.mark.parametrize("item", REQUIRED_ITEMS)
    def test_missing_any_item_is_blocked(self, item, tmp_path):
        """反: 删掉任一必项 → 报 manifest_missing 且拒绝落盘 (fail-closed)。

        逐项参数化而不是只测一项: 八项的键名以后可能增删, 参数化让新增的
        一项自动获得同等的 fail-closed 覆盖, 不会因为没人补用例而漏网。
        """
        manifest = copy.deepcopy(_valid_manifest())  # 深拷贝: 删键不能污染共享夹具
        del manifest[item]                                                                 # 删的是深拷贝里的键: 共享夹具被污染会让后面的用例莫名全红
        assert f"manifest_missing:{item}" in validate_manifest(manifest)  # 挡住"只判键存在"
        # 断落盘也拒: 校验与写入是两道独立的关, 只测校验会放过
        # "有人为了跑通而在 save 里跳过校验"的改法
        with pytest.raises(ValueError):                                      # 连落盘一起断: 校验与写入是两道独立的关, 只测校验会放过「在 save 里跳过校验」
            save_manifest(manifest, tmp_path / "m.json")

    def test_empty_item_value_is_blocked(self):
        """反: 项在但值为空 dict → 同样判缺失 (空壳不算齐备)。

        这条守的是 `item not in manifest or not manifest[item]` 的后半段:
        只判键存在的话, 八个空壳照样能通过, 等于"有清单但没内容"。
        """
        assert "manifest_missing:sampling" in validate_manifest(_mutated(sampling={}))

    def test_same_input_same_fingerprints(self):
        """确定性: 同输入两次组装的指纹逐项相同 (时间戳字段除外); skill 指纹带算法前缀。

        可复现指标的锚点必须自己可复现: 指纹如果会飘, 后面所有"同一次运行
        的两次 trace" 比对都失去意义。execution 因含时间戳被刻意排除。
        """
        first, second = _valid_manifest(), _valid_manifest()  # 同输入两次组装, 指纹会飘则跨 run 比对全无意义
        for key in ("best_data", "skill", "model", "system_prompt", "tool_schema",
                    "eval_data", "sampling"):
            assert first[key] == second[key], key  # 逐键断且带 key: 定位不到是哪一项在飘
        # 断长度 71 = "sha256:"(7) + 64 位 hex; 断前缀是为了将来换算法时
        # 能立刻看出这不是 sha256 算的
        assert first["skill"]["fingerprint"].startswith("sha256:")
        assert len(first["skill"]["fingerprint"]) == 71  # 71 = "sha256:"(7) + 64 位 hex, 锁死编码格式

    def test_design_assets_present(self):
        """三件套迁移落位 (manifest.example / trace.schema / rubric — 人读与机读权威都在)。"""
        # 断存在性而不是内容: 权威文件的正文改动是正常演进, 这条只守
        # "三件套不许被删" —— 删掉 schema 就等于让机读校验失去依据
        assert (REPRO_DIR / "manifest.example.yaml").is_file()  # 只守"不许被删": 正文演进是正常的
        assert (REPRO_DIR / "trace.schema.json").is_file()
        assert (REPRO_DIR / "rubric.yaml").is_file()

    def test_canary_requires_five_probes(self):
        """反: canary 探针不足 5 个即抛 (不静默出数据版本指纹)。

        少一个探针等于少一种星表的交叉验证, "数据没变"会退化成"这一种表
        没查到差异", 那是被伪装成证据的没测 (铁律 5 禁 fail-open)。
        """
        with pytest.raises(ValueError):                                          # 探针数不足即抛: 少一种星表的交叉验证, 「数据没变」就退化成「这一种没差异」
            canary_fingerprint([[{"a": 1}]] * 4)  # 探针不足 5 个: 少一种星表的交叉验证

    def test_canary_deterministic_and_key_sensitive(self):
        """正: 同探针 → 同指纹; 反: 行结构 (键集合) 变 → 指纹变。

        两侧都要断: 只断"同输入同输出"的话, 一个恒返回常量的实现也能通过;
        只断"变了会变"的话, 用随机数也能通过。
        """
        probes = [[{"ra": 1.0}], [{"ra": 2.0}], [{"ra": 3.0}], [{"ra": 4.0}], [{"ra": 5.0}]]
        assert canary_fingerprint(probes) == canary_fingerprint(probes)  # 恒返回常量的实现要挡在这条
        assert canary_fingerprint(probes) != canary_fingerprint(probes[:4] + [[{"ra": 6.0, "extra": 1}]])

    def test_canary_sensitive_to_value_drift(self):
        """反: 只改行内数值 (列名不变) → 指纹也必须变 (数据版本门禁的核心用途)。

        canary_fingerprint 必须指纹**整行规范化**而不只是列名: 只指纹列名
        时, 行内数值漂移全部漏检, 数据版本门禁就瞎了。
        """
        # 只动第一个探针的数值, 列名与结构完全不动: 这正是只指纹列名时
        # 漏掉的那种漂移 (数据值变了但字段没变)
        probes = [[{"ra": 1.0}], [{"ra": 2.0}], [{"ra": 3.0}], [{"ra": 4.0}], [{"ra": 5.0}]]
        drifted = [[{"ra": 999.0}], [{"ra": 2.0}], [{"ra": 3.0}], [{"ra": 4.0}], [{"ra": 5.0}]]
        assert canary_fingerprint(probes) != canary_fingerprint(drifted)  # 值漂移也必须被抓: 数据版本门禁的核心用途

    @pytest.mark.parametrize(("changes", "expected"), [
        ({"model.model_id": "gpt-latest"}, "model_alias_forbidden"),
        ({"sampling.temperature": None}, "temperature_not_fixed"),
        ({"best_data.drift_state": "WEIRD"}, "drift_state_invalid"),
        ({"eval_data.relative_time_tasks": ["REPRO-99"]}, "relative_time_tasks_present"),
        ({"execution.lane": "R9"}, "lane_invalid"),
    ])
    def test_validate_blocks_bad_values(self, changes, expected):
        """反: latest 别名/温度未固定/DRIFTED 未声明/相对时间任务/非法 lane → 阻断。

        五种坏值各占一行, 共同点是"单看都像能跑, 合起来就是一次无法复现
        的运行" —— 所以任何一处放过都会污染后面所有跨 run 比对。
        """
        assert any(p.startswith(expected) for p in validate_manifest(_mutated(**changes)))  # 按前缀匹配即可: 阻断项带分类名, 逐条等值会让文案一改就红

    def test_save_and_load_roundtrip(self, tmp_path):
        """正: 落盘再读回一致 (先校验后写); sha256_file 与 sha256_text 同口径。

        两个断言合在一起看: 往返一致保证"manifest 落盘后还能当证据用",
        指纹同口径保证"同一内容无论走文件还是走字符串都算出同一个值"。
        """
        manifest = _valid_manifest()                                                    # 先造合法清单: 往返用例要先有可落盘的对象, 否则测的是异常路径
        path = tmp_path / "run_manifest.json"
        save_manifest(manifest, path)                                                    # 落盘走正式入口: 自己拼 JSON 会绕过「先校验后写」这道关
        # 断等值而非逐键: 落盘过程少写一个键也要能被发现
        assert load_manifest(path) == manifest   # 等值: 落盘少写一个键也要能被发现
        target = tmp_path / "x.txt"
        target.write_text("astro-best", encoding="utf-8")
        # 同口径是硬要求: 两套算法会让报告里"文件指纹"与"文本指纹"两列
        # 看起来可比而其实不可比
        assert sha256_file(target) == sha256_text("astro-best")  # 同口径: 两套算法会让两列指纹看似可比



# ── 2. trace: 读写/脱敏/完整性 ───────────────────────────────────────────

class TestTrace:
    """trace: 写入读回一致 / 脱敏红线 / 完整性校验 / 事件链 hash 稳定。"""

    def test_write_read_roundtrip(self, tmp_path):
        """正: 写入的事件与读回的事件逐一相等 (seq 从 0 连续, 头五件套自动补)。

        断整体相等: 少写一个头字段、seq 不连续, 都会在这条上直接暴露。
        """
        path = tmp_path / "trace.jsonl"
        written = _write_trace(path)  # 写入端返回的就是落盘内容, 读回可比
        assert [e["seq"] for e in written] == [0, 1, 2, 3, 4]   # seq 从 0 连续: 断号是完整性红线
        # 整体相等而非逐字段: JSONL 往返还会暴露 ensure_ascii/编码层面的
        # 问题, 逐字段比会漏掉顺序与类型的偏差
        assert read_trace(path) == written                                          # 整体相等: JSONL 往返还会暴露编码与顺序层面的问题, 逐字段比会漏
        assert [e["type"] for e in written] == ["run_start", "tool_call", "tool_result",
                                                "final_answer", "run_end"]

    def test_validate_clean_trace(self, tmp_path):
        """正: 合法 trace → 无阻断项 (连续/配对/final_answer/凭据复扫全过)。"""
        # 这条是正例基线: 没有它, 下面四条反例的阻断项可能是"无论对错都
        # 报"的噪声, 测试就失去了鉴别力
        assert validate_trace(_write_trace(tmp_path / "ok.jsonl")) == []  # 正例基线, 没有它下面四条反例失去鉴别力

    def test_payload_fingerprint_stable_and_sensitive(self):
        """正: 事件链 hash 稳定 (键序不敏感); 反: 内容变则指纹变。

        两侧合起来才是"指纹可用": 键序不敏感保证同一份数据由不同构造路径
        写出时可比, 内容敏感保证篡改一定被抓。
        """
        assert payload_fingerprint({"x": 1, "y": [1, 2]}) == payload_fingerprint({"y": [1, 2], "x": 1})
        assert payload_fingerprint({"x": 1}) != payload_fingerprint({"x": 2})  # 内容敏感: 否则指纹形同虚设

    def test_redact_masks_url_token_params(self):
        """正: URL token 类查询参数值 → *** (token/api_key 同口径)。"""
        # 断逐字相等: 保留参数名、只抹值, 少了参数名的替换会让读者看不出
        # "这里原本有过一个凭据"
        assert redact("http://x/q?token=abc&page=2") == "http://x/q?token=***&page=2"  # 留参数名只抹值
        # 递归进 dict: 脱敏只扫顶层的话, 藏在嵌套参数里的 token 会漏
        assert redact({"u": "http://x?api_key=zzz"}) == {"u": "http://x?api_key=***"}

    @pytest.mark.parametrize("token", FORBIDDEN_TOKENS)
    def test_redact_blocks_credential_literals(self, token):
        """反: 凭据原文出现即抛 (脱敏红线 — 无静默放过)。

        按 token 逐个参数化: 红线词表以后会增补, 参数化让新词自动获得
        覆盖, 不会出现"加了词但忘了加用例"。
        """
        with pytest.raises(ValueError, match="脱敏红线"):
            redact(f"prefix {token} suffix")

    def test_writer_rejects_credential_payload(self, tmp_path):
        """反: 凭据进 payload → emit 即抛 (写坏一半好过静默落盘)。

        断在 emit 抛而不是"落盘后再扫": 后者意味着凭据已经进过文件系统,
        那一下就够了 —— 脱敏必须发生在序列化之前。
        """
        with TraceWriter(tmp_path / "t.jsonl", run_id="r", task_id="REPRO-04") as writer:
            with pytest.raises(ValueError, match="脱敏红线"):
                writer.emit("run_start", {"manifest": {"note": "BEST_API_TOKEN=abc"}})  # emit 就抛: 落盘后扫已太晚

    @pytest.mark.parametrize(("mutate", "expected"), [
        (_break_seq, "seq_gap"),
        (_drop_header, "header_missing"),
        (_drop_result, "tool_pairing"),
        (_drop_final, "final_answer_missing"),
    ])
    def test_tampered_trace_is_caught(self, tmp_path, mutate, expected):
        """反: seq 断号/头字段缺失/调用不配对/缺 final_answer → 各报对应阻断项 (§8.2 #6)。

        四种篡改共用一条用例体: 差异只在 mutate 函数与期望的阻断项前缀,
        写成一条参数化比四份复制粘贴更不容易在修校验时只改到其中一份。
        """
        events = _write_trace(tmp_path / "tamper.jsonl")
        mutate(events)  # 四种篡改共用一条体: 修校验时不会只改到其中一份
        assert any(expected in p for p in validate_trace(events))  # 断具体阻断项, 不是"有错就行"

    def test_empty_trace_is_caught(self):
        """反: 空 trace → trace_empty (不静默放过)。

        断等值而非"包含": 空轨迹只有一种合法判法, 多报或少报都说明
        校验层的空分支被改坏了。
        """
        assert validate_trace([]) == ["trace_empty"]   # 等值: 多报少报都说明空分支被改坏

    def test_credential_leak_in_trace_is_caught(self, tmp_path):
        """反: 事件体出现凭据原文 → credential_leak 阻断 (写后复扫, 文档 §8.2 #7)。"""
        events = _write_trace(tmp_path / "leak.jsonl")
        # 手工改事件体绕过写入侧: 这正是第二道复扫存在的理由, 有人能改
        # 文件不代表没人会改
        events[1]["payload"]["args"]["note"] = "Bearer access_token=sekrit"  # 手工改体绕过写入侧, 复扫才拦得住
        assert any(p.startswith("credential_leak") for p in validate_trace(events))  # 挡住"只扫写入前"

    @pytest.mark.parametrize(("event_type", "payload", "match"), [
        ("not_a_type", {}, "未知事件类型"),
        ("tool_call", {"tool": "cone_search"}, "缺必填字段"),
    ])
    def test_writer_rejects_invalid_events(self, tmp_path, event_type, payload, match):
        """反: 未知事件类型 / payload 缺必填字段 → emit 即抛 (schema 之外的进不了 trace)。

        事件类型白名单与 payload 必填是 schema 的两道门: 少一道, trace
        里就会混进校验器不认识的事件, 后续解析只能靠猜。
        """
        with TraceWriter(tmp_path / "bad.jsonl", run_id="r", task_id="REPRO-04") as writer:
            with pytest.raises(ValueError, match=match):                        # match 断异常文案: 类型白名单与必填是两道门, 断文案才分得清是哪一道拦的
                writer.emit(event_type, payload)   # 类型白名单与必填是两道门, 少一道后续只能靠猜

    def test_writer_outside_context_raises(self, tmp_path):
        """反: 未进上下文就 emit → RuntimeError (不往未打开的文件里写)。

        断 RuntimeError 而非通用异常: 误用与内部故障要能区分开, 否则
        调用方无从判断该不该重试。
        """
        writer = TraceWriter(tmp_path / "x.jsonl", run_id="r", task_id="REPRO-04")
        with pytest.raises(RuntimeError):                                        # 未进上下文即抛: 误用要报 RuntimeError, 让调用方知道该不该重试
            writer.emit("run_start", {"manifest": {}})  # 断 RuntimeError: 让调用方知道该不该重试

    def test_module_matches_trace_schema_json(self):
        """正: trace.py 的头字段/事件类型/payload 必填/脱敏红线必须与 schema 权威一致。

        这条是代码与 schema 之间的防漂移锁: 两侧各改各的会让机读校验完全
        失效, 而现象是"报告里一切正常, 实际漏检了一整类事件"。
        """
        schema = json.loads((REPRO_DIR / "trace.schema.json").read_text(encoding="utf-8"))
        # 头字段用等值比较: 多一个字段同样会让报告的解析器读不懂
        assert set(schema["event_header"]["required"]) == {   # 头字段等值: 多一个字段报告解析器就读不懂
            "seq", "ts_utc", "ts_mono", "run_id", "task_id", "attempt", "parent_seq",
            "layer", "type", "payload", "payload_fp"}
        assert set(schema["event_header"]["properties"]["type"]["enum"]) == set(EVENT_TYPES)
        # payload 必填用子集: schema 可以比代码多要求, 反过来不行
        for etype, required in PAYLOAD_REQUIRED.items():                                 # 逐类型比对必填: schema 可以比代码多要求, 反过来不行
            assert set(required) <= set(schema["payload_by_type"][etype]["required"]), etype
        # 脱敏红线用等值: 代码少认一个词就等于那道防线漏了一格
        assert set(schema["redaction"]["forbidden"]) == set(FORBIDDEN_TOKENS)  # 红线等值锁

    def test_payload_content_tamper_is_caught(self, tmp_path):
        """反: 只改 payload 内容不改结构 → 也应被 payload_fp 复核抓住。

        validate_trace 必须重算 payload_fp 并以 payload_fp_mismatch 拦下:
        不复核就只剩字段级校验, 改嵌套值一律逃过。
        """
        events = _write_trace(tmp_path / "tamper.jsonl")
        # 改一个已经存在的嵌套键, 结构与必填项全都不变: 字段级校验全都
        # 通过, 只有复算指纹能发现
        events[2]["payload"]["status"]["ok"] = False  # 只改嵌套值不动结构: 字段级校验全过
        assert any("payload" in p for p in validate_trace(events))  # 只有复算 payload_fp 抓得住



# ── 3. transport: 回放路由与调用计数 ─────────────────────────────────────

class TestTransport:
    """回放路由: POST→phase1 / getcount→总数 / page→CSV 原文 / 缺页→空表; 计数。"""

    def _snapshot(self, base: Path, *, count=True, page=True, root=False) -> Path:
        """造一个最小快照目录 (可控缺 count.json / page / root.html)。

        作用: 给路由用例造可裁剪的快照源。关键参数 base 是临时父目录,
        count/page/root 三个开关分别控制对应文件是否存在。
        Returns: 快照目录路径。抛什么: 不抛; 缺文件时由路由侧降级。
        """
        # 三个开关而不是三套固定夹具: 降级路径必须能单独触发, 否则
        # "缺 count.json" 只能靠删文件来构造, 用例之间会互相干扰
        snap = base / "snap"
        (snap / "pages").mkdir(parents=True)
        # 塞一个 sqlid 串: 两阶段协议的第二步要能从 phase1 里取到它,
        # 少了它整条链路会在解析处就断掉, 测不到路由本身
        (snap / "phase1.html").write_text('<html>url:"/data/best/sqlid/s9001"</html>', encoding="utf-8")  # sqlid 载体
        if count:                                                      # count 开关独立: 缺 count.json 的降级路径要能单独构造, 删文件会让用例互相干扰
            (snap / "count.json").write_text('{"total": 5}', encoding="utf-8")
        if page:                                                                       # page 开关独立: 同样的理由, 分页降级不能靠删别的用例的文件
            (snap / "pages" / "page_0001.csv").write_text("ps1_ra,ps1_dec\n180.0,30.0\n", encoding="utf-8")
        if root:                                                                       # root 开关独立: 根路径分支是探测性请求, 缺它也要能单独触发
            (snap / "root.html").write_text("<html>root</html>", encoding="utf-8")
        return snap

    def test_post_routes_to_phase1_html(self, tmp_path):
        """正: POST /{catalog}/q → phase1.html (sqlid 链接载体)。"""
        transport = ReplayTransport(self._snapshot(tmp_path))                        # 每个用例自建快照: 夹具写在自己的 tmp 下, 跨用例共享会互相覆盖
        response = transport.post("http://replay.local/data/best/ps1/q")
        # 断状态码与内容两项: 只断 200 的话, 任何一份 HTML 都会被当成正确
        # 回包, 路由到错的文件也发现不了
        assert response.status_code == 200 and "sqlid" in response.text  # 断码与内容: 只断 200 任何 HTML 都算对

    def test_getcount_routes_to_count_json(self, tmp_path):
        """正: 含 /getcount 的 GET → count.json 原文 (服务端真实总数)。"""
        transport = ReplayTransport(self._snapshot(tmp_path))                                 # 同上: 回放口不跨用例复用, 否则调用计数会互相污染
        # 断逐字相等: 少一个字段或改了 total 都会让分页终止条件算错
        assert transport.get("http://x/getcount?count=9001").text == '{"total": 5}'

    def test_getcount_missing_file_defaults_zero(self, tmp_path):
        """反: 快照无 count.json → {"total": 0} (不猜真实总数)。

        返 200 + 0 而非 404: 服务端首次查询可能真的还没索引完, 替身必须
        复现这个降级, 否则被测链路会走进它在线上永远不会走的错误分支。
        """
        transport = ReplayTransport(self._snapshot(tmp_path, count=False))  # 显式关掉 count: 这条要测的正是「缺 count.json 时给 total=0」这条降级路
        assert json.loads(transport.get("http://x/getcount").text) == {"total": 0}

    def test_page_routes_to_csv_original(self, tmp_path):
        """正: page=N → pages/page_NNNN.csv 原文 (保真读取, 不转码)。"""
        transport = ReplayTransport(self._snapshot(tmp_path))                       # 默认全开: 正例路径三个文件都要在, 少一个测到的就是降级而不是正常回放
        # 断逐字相等: 这条守的是 utf-8-sig 的 BOM 兼容 —— 换错编码参数
        # 会让第一列名带上不可见字符, 行键集合整体偏一列
        assert transport.get("http://x/sqlid/s9001?page=1").text == "ps1_ra,ps1_dec\n180.0,30.0\n"  # 守 utf-8-sig 兼容

    def test_missing_page_returns_empty_table(self, tmp_path):
        """反: 缺页 (末页之后) → 空表 + 200 (0 行即末页, 不是错误)。

        断两个条件: 少了 200 会让分页循环走进错误分支, 少了空串则会把
        "末页"当成"服务端异常", 两种都会让 R0 的回放看起来不可复现。
        """
        response = ReplayTransport(self._snapshot(tmp_path)).get("http://x/sqlid/s9001?page=9")
        assert response.status_code == 200 and response.text == ""  # 200+空串: 少任一个分页循环都会走错分支

    def test_root_route_with_and_without_root_html(self, tmp_path):
        """正/反: 其余 GET → root.html; 无该文件 → 404 替身 (不静默 200)。"""
        # 两个快照分开放不同的父目录: 共用同一个 tmp_path 会让第二个
        # ReplayTransport 看到第一个造出来的 root.html, 降级路径就测不到了
        with_root = ReplayTransport(self._snapshot(tmp_path / "a", root=True))
        assert with_root.get("http://x/").text == "<html>root</html>"
        without = ReplayTransport(self._snapshot(tmp_path / "b"))
        # 断 404 明确: 静默返 200 的空页会让"落地页缺失"看起来像正常
        assert without.get("http://x/").status_code == 404

    def test_call_count_counts_every_request(self, tmp_path):
        """正: 每次 get/post 都计数 (效率指标的实测口径, 非估算)。"""
        transport = ReplayTransport(self._snapshot(tmp_path))                          # 真实夹具而非人造: 人造夹具只能验证回放器自己, 验不了与磁盘同源
        # 一次 POST + 两次 GET 覆盖三条不同路由: 只测一种路由的话,
        # 另两条漏计也不会被发现, EF1 的分母就偏了
        transport.post("http://x/q")
        transport.get("http://x/getcount")
        transport.get("http://x/sqlid/s9001?page=1")
        assert transport.call_count == 3     # 计数是 EF1 的实测口径, 漏计一条分母就偏

    def test_missing_snapshot_dir_raises(self, tmp_path):
        """反: 快照目录不存在即抛 (回放目标必须真实 — fail-closed)。

        断抛而不建空目录: 静默建空目录会让每次查询都走 404 降级, 整轮
        R0 跑完看起来只是"全部失败", 而真因是快照压根没采到。
        """
        with pytest.raises(FileNotFoundError):                                       # 缺目录即抛: 静默建空目录会让整轮看起来只是「全部失败」, 真因被掩盖
            ReplayTransport(tmp_path / "nope")   # 不建空目录: 静默建会让整轮 R0 看起来只是"全部失败"

    def test_real_fixture_pages_match_disk(self):
        """正: 真实夹具回包与磁盘原文逐字一致 (ps1_5rows 表头+5 行 / ps1_singlepage 表头+3 行)。"""
        one = ReplayTransport(FIXTURES_DIR / "ps1_5rows")  # 真实夹具: 守磁盘与回包同源
        body = one.get("http://x/sqlid/s9001?page=1").text
        # 拿磁盘原文当基准而不是硬编码字符串: 快照更新后这条会立刻红,
        # 提醒同时更新期望, 而不是让陈旧的行数断言一直绿着
        assert body == (FIXTURES_DIR / "ps1_5rows" / "pages" / "page_0001.csv").read_text(
            encoding="utf-8-sig")                       # utf-8-sig 兼容, 不能改成普通 utf-8
        # 行数断 6 = 表头 + 5 行数据; 断行数才能发现"内容对但少了几行"
        assert len(body.strip().splitlines()) == 6                               # 断行数: 断 6 = 表头加 5 行数据, 断行数才能发现「内容对但少了几行」
        # 末页边界: ps1_singlepage 是真实单页快照 (total=3), 第 2 页在真实站点
        # 本就返 0 行 —— 替身必须复现这个语义, 而不是凭空造出第 2 页
        single = ReplayTransport(FIXTURES_DIR / "ps1_singlepage")
        assert len(single.get("http://x/sqlid/s4900?page=1").text.strip().splitlines()) == 4
        assert single.get("http://x/sqlid/s4900?page=2").text == ""               # 末页之后: 空表, 非 404

    def test_fake_response_semantics(self):
        """正/反: 非 2xx 抛 HTTPError (与真实 requests 同语义); 200 放行/分块/close。"""
        # 抛的必须是 requests 自己的异常类型: 被测链路的 except 分支通常
        # 按 requests.HTTPError 写, 替身抛别的类型就走不进那条路
        with pytest.raises(requests.HTTPError):    # 必须是 requests 自己的异常类型: 被测链路的 except 按 requests.HTTPError 写, 换类型就进不去那条路
            FakeResponse(404, "x").raise_for_status()
        ok = FakeResponse(200, "abcd")
        ok.raise_for_status()                                                      # 2xx 不抛: 放行本身也是语义的一部分, 只断抛错会漏掉「永远抛」的实现
        # 分块断逐块相等: 真分块才能让"读到一半中断"的异常分支在回放下
        # 也走得到, 一次给全量会让那条路径永远测不到
        assert list(ok.iter_content(2)) == [b"ab", b"cd"]  # 真分块: 一次给全量则"读到一半中断"永远测不到
        ok.close()                                                        # close 后再断言: 标志位是替身对 with/finally 的契约, 不验就等于没实现
        assert ok.closed is True                                                   # 断标志位而非句柄: 快照没有真实连接可关, 被测代码能观察到的只有这个标志



# ── 4. normalize: 参数与结论卡归一 ───────────────────────────────────────

class TestNormalize:
    """参数归一 (目录/列/坐标/半径) 与结论卡归一 (四子项, 容差外置)。"""

    @pytest.mark.parametrize(("raw", "expected"), [
        ("12h30m00s", 187.5), ("12 30 00", 187.5), ("180:30:00", 180.5),
        ("-20:24:00", -20.4), ("+20°00′00″", 20.0), ("187.5", 187.5), (187.5, 187.5),
    ])
    def test_angle_forms_to_deg(self, raw, expected):
        """正: 时角/冒号分秒/度分秒/裸数字 → 度 (容差来自 tolerances.fields.ra_deg)。

        两种时角写法 (12h30m00s 与 12 30 00) 给出同一期望值, 断的正是不
        语法序的消歧次序: 顺序写反会让裸三元组抢走带 h 的形态。
        """
        assert norm_angle_deg(raw) == pytest.approx(expected)  # 两种时角写法给同一期望: 断的是消歧次序

    @pytest.mark.parametrize("raw", ["abc", "", None, True])
    def test_angle_unparseable_returns_none(self, raw):
        """反: 不可解析 → None (由调用方判不一致, 不猜)。

        True 也在列: bool 是 int 的子类, 不单独挡掉的话会被当成 1.0 度,
        一次布尔误传就伪装成了合法角度。
        """
        assert norm_angle_deg(raw) is None   # 断 None 不猜: True 在列是因为 bool 是 int 子类

    @pytest.mark.parametrize(("raw", "expected"), [
        ("5″", 5.0), ("5''", 5.0), ("5′", 300.0), ("5'", 300.0), ("5角分", 300.0),
        ("0.5 deg", 1800.0), ("5 arcsec", 5.0), ("5", 5.0), (5, 5.0),
    ])
    def test_radius_units_to_arcsec(self, raw, expected):
        """正: 角秒/角分/度/带单位字符串 → 角秒 (文档 §5.2)。

        角分 60 倍、度 3600 倍是单位换算的物理常数, 断这两档是为了锁住
        换算表: 把它写反会让所有半径差 60/3600 倍, 而绝对值仍"看着合理"。
        """
        assert norm_radius_arcsec(raw) == pytest.approx(expected)  # 60/3600 是物理常数, 写反了绝对值仍"看着合理"

    def test_radius_unparseable_returns_none(self):
        """反: 单位错/不可解析 → None (不当成 0 或默认半径)。

        断 None 而不是 0: 默认半径会让"参数没给"与"给了个合法半径"在
        PAC 上同形, 而前者其实是链路失败。
        """
        assert norm_radius_arcsec("abc") is None
        assert norm_radius_arcsec(None) is None   # 断 None 不记 0: 默认半径会让"没给"与"合法值"同形

    def test_norm_args_positive(self):
        """正: 异写参数 (时角+角分+大小写表名+乱序列) 归一同形。

        四种异写同时出现, 归一后必须与规范形态逐键相等 —— 少归一任何一种
        都会让同一个语义的参数被判成漂移, PAC 虚低。
        """
        assert norm_args({"ra": "12h30m", "dec": "-20.4", "radius_arcsec": "5'",
                          "catalog": " PS1 ", "columns": ["b", "a"], "max_records": 10}) == {
            "ra": 187.5, "dec": -20.4, "radius_arcsec": 300.0,
            "catalog": "ps1", "columns": ["a", "b"], "max_records": 10}

    def test_norm_args_negative_column_qualification(self):
        """反: 列名必须全限定 — 裸名与带前缀名归一后仍不同 (投影稳定性正是 PAC 要抓的)。

        这条与 E1 的去前缀归一口径**相反**且刻意: 宽比对会把投影抖动洗掉,
        而 E6 要抓的恰恰是抖动。
        """
        bare = norm_args({"columns": ["rztf"]})["columns"]
        qualified = norm_args({"columns": ["scr_galah_rztf"]})["columns"]
        assert bare != qualified   # 与 E1 口径相反且刻意: 宽比对会把投影抖动洗掉

    def test_norm_args_catalog_not_alias_normalized(self):
        """正/反: catalog 只做大小写与空格归一, 不做别名归一 (表选错正是 PAC 要抓的)。

        两个断言分别守住边界两侧: PS1 与 " PS1 " 是同一个表, 而 gaia 与
        gaia_dr3_18 是两张表, 别名归一会把后者一起洗掉。
        """
        assert norm_args({"catalog": "PS1 "})["catalog"] == "ps1"
        assert norm_args({"catalog": "gaia_dr3_18"})["catalog"] != norm_args({"catalog": "gaia"})["catalog"]

    def test_norm_card_four_subitems(self):
        """正: kind 缺省 none / 数值转 float / 实体与 caveats 集合化 / sqlid 剥离。

        四个子项各断一次: 少做任何一项, FCC 都可能把"同一个结论的不同写法"
        判成漂移, 或者把真正的漂移洗掉。
        """
        card = norm_card({"key_numbers": [{"field": "n", "value": "12"}],
                          "key_entities": ["scr_galah", "best://x/sqlid/s9001"],
                          "caveats": ["合成测光非实测"]})
        # kind 缺省成 "none" 而不是空串: 空串会让"没写 kind"与"写了空 kind"
        # 在比对时同形
        assert card["kind"] == "none"
        # 字符串数值必须转 float 才能进 1e-6 容差比对
        assert card["key_numbers"] == [{"field": "n", "value": 12.0}]   # 不转则容差比对必红
        # sqlid 段被换掉: 每次运行都不同, 不剥就等于给 FCC 埋一颗地雷
        assert card["key_entities"] == {"scr_galah", "best://x/sqlid/<SESSION>"}
        assert card["caveats"] == {"合成测光非实测"}   # 集合化: 顺序不该影响结论一致性

    @pytest.mark.parametrize(("field", "value"), [
        ("kind", "refusal"), ("key_numbers", [{"field": "row_count", "value": 13}]),
        ("key_entities", ["xpsp"]), ("caveats", ["另一条限定"]),
    ])
    def test_cards_equal_rejects_subitem_drift(self, field, value):
        """反: 四子项任一项漂移 → 不一致 (kind 精确/数值容差/实体集合/限定集合)。

        按子项参数化: 四种漂移共用一条用例体, 改比对逻辑时不会只改到
        其中一个子项而让另外三个悄悄退化。
        """
        assert not cards_equal(_MODE_CARD, norm_card(dict(_BASE_CARD, **{field: value})))  # 四子项任一漂移都要被抓

    def test_cards_equal_accepts_tolerance_and_sqlid(self):
        """正: 1e-6 内容差 + sqlid 易失 → 仍判一致 (容差外置 + 地雷剥离)。

        这条是正例边界: 归一过松会让 FCC 恒为 1.0, 于是"完全可复现"这个
        最强的结论变成一句没有信息量的套话。
        """
        close = dict(_BASE_CARD, key_numbers=[{"field": "row_count", "value": 12.0000001}],
                     key_entities=["scr_galah", "best://scr_galah/sqlid/sOTHER"])
        assert cards_equal(_MODE_CARD, norm_card(close))   # 正例边界: 归一过松会让 FCC 恒为 1.0

    def test_strip_session_id_variants(self):
        """正: session_id=/sqlid=//sqlid/ 三种形态都剥离; 无关 URI 原样。

        末尾带 query 的那条要断: 值截到 & 或 / 为止, 否则同一个 sqlid 在
        两个不同页面下会归一成两个不同字符串, 漂移是假的。
        """
        assert strip_session_id("best://x/sqlid/s9001?fmt=csv") == "best://x/sqlid/<SESSION>"  # 值截到 & 或 / 为止
        assert strip_session_id("best://x?session_id=abc&y=1") == "best://x?session_id=<SESSION>"
        # 无关 URI 原样: 过度剥离会把两种不同的资源归一成同一个串
        assert strip_session_id("best://x/cone") == "best://x/cone"   # 过度剥离会把不同资源归成同一串


# ── 9. stats: Wilson / McNemar / α ───────────────────────────────────────

class TestStats:
    """Wilson 区间 / McNemar 精确检验 / Krippendorff α / 众数 (N=5 必须给区间)。"""

    def test_wilson_ten_of_ten(self):
        """n=10 k=10 → 区间含 1.0 且下界 > 0.69 (已知样本校验)。"""
        low, high = wilson_interval(10, 10)   # 全成功极端样本: 最容易用错公式却"看起来对"
        assert high == pytest.approx(1.0)                                        # 极端样本最易用错公式: 全成功时很多错误实现也「看起来对」, 只有上界区分得开
        # 断下界落在 0.69~0.75: 全成功的极端样本最容易让实现用错公式
        # 却仍然"看起来对", 只有下界才区分得出
        assert 0.69 < low < 0.75                                                        # 断下界区间: 只有下界才区分得出公式对错, 上界几乎恒为 1.0

    def test_wilson_five_of_five_is_wide(self):
        """N=5 全一致区间仍宽 (诚实声明 §5.5: 约 [0.57, 1.0]) — 不做强达标断言。

        这条是本文件里唯一"刻意不追求高分"的断言: N=5 全一致看起来像满分,
        区间下界只有 0.57, 把它当达标证据就是文档 §5.5 明令禁止的失真。
        """
        low, high = wilson_interval(5, 5)                                       # 先取区间再断言: N=5 全一致下界只有 0.55 上下, 这是诚实声明而非缺陷
        assert 0.55 < low < 0.58 and high == pytest.approx(1.0)   # 刻意不追高分: N=5 当达标证据被 §5.5 禁止

    def test_wilson_edges(self):
        """total=0 → (0,1) 不猜; 1/2 区间跨 0.5 (小样本不对称)。"""
        # 无观测时给 (0,1) 而不是抛错或给 (0,0): 空区间会被读成"一次都没成功"
        assert wilson_interval(0, 0) == (0.0, 1.0)   # 无观测给 (0,1) 而非 (0,0): 空区间会被读成"一次都没成功"
        low, high = wilson_interval(1, 2)                                                # 1/2 是小样本不对称的最短反例: 对称实现算出来的宽度是错的
        # 断跨 0.5: 小样本下区间必须是不对称的, 对称实现算出来的宽度是错的
        assert low < 0.5 < high                                                        # 断跨 0.5 而非断端点: 端点值随实现变, 跨越关系才是稳定判据

    @pytest.mark.parametrize(("b", "c", "expected"), [
        (0, 0, 1.0), (4, 4, 1.0), (3, 3, 1.0), (8, 0, 0.0078125), (5, 0, 0.0625),  # 期望值全是手算闭式: 2*(1/2)^n, 防实现把双侧乘 2 漏掉或写成单侧
    ])
    def test_mcnemar_exact(self, b, c, expected):
        """McNemar 精确检验: 无分歧/均衡 → p=1; 一边倒 8:0 → p<0.05; 5:0 → 边缘。

        五个期望值都是手算的闭式结果: 8:0 给出 2*(1/2)^8=0.0078, 5:0 给出
        2*(1/2)^5=0.0625 —— 5:0 那条正是"看起来该显著却没显著"的边界,
        断它是为了防止实现把双侧乘 2 漏掉或写成单侧。
        """
        assert mcnemar_exact(b, c) == pytest.approx(expected)  # 期望全是手算闭式 2*(1/2)^n, 防双侧漏乘 2

    def test_alpha_perfect_and_disagreement(self):
        """α: 全一致 = 1.0; 完全分歧 < 0 (比偶然一致还差)。

        两侧都要断: 期望分歧为 0 时必须走 1.0 分支而不是除零, 而完全
        分歧时 α 必须为负 —— 报 0.0 会让人误以为"只是没信息"。
        """
        assert krippendorff_alpha_nominal([[("a",), ("a",), ("a",)],
                                           [("a",), ("a",), ("a",)]]) == 1.0  # 期望分歧为 0 走 1.0 分支而非除零
        assert krippendorff_alpha_nominal([[("a",), ("b",)], [("a",), ("b",)]]) < 0.0

    def test_mode_tie_takes_first(self):
        """众数并列取先出现者 (确定性 — 报告需披露并列); 空表 → None。

        众数是 TSC/PAC/RDC/FCC 四个指标的共同参照: 换一个取法就等于让
        参照随输入顺序漂移, 一致率会在不同机器上给出不同结论。
        """
        assert mode(["a", "b", "a", "b"]) == "a"   # 并列取先出现者: 参照漂移会让一致率跨机器不一致
        assert mode([]) is None                                                    # 空表返 None 而非抛: 调用方据此判「无参照」, 返默认值会造出假一致

    # ── bootstrap 区间 (跨任务均值的诚实区间; Wilson 不适用于比值均值) ──────

    def test_bootstrap_is_deterministic(self):
        """同输入必须逐位复现 (固定种子): 可复现实验不允许区间随调用次数漂。"""
        values = [1.0, 0.8, 0.9, 0.95, 0.7, 1.0, 0.85, 0.9]
        assert bootstrap_mean_ci(values) == bootstrap_mean_ci(values)   # 两次调用必须同值, 否则跑批不可复现

    def test_bootstrap_interval_brackets_the_mean(self):
        """区间必须把点估计夹在中间, 且不是零宽 (有离散度才有宽度)。"""
        values = [1.0, 0.8, 0.9, 0.95, 0.7, 1.0, 0.85, 0.6, 0.75, 0.92]
        low, high = bootstrap_mean_ci(values)
        mean = sum(values) / len(values)
        assert low <= mean <= high          # 区间不含点估计就是实现错了
        assert low < high                    # 这些取值离散度明显, 零宽区间说明实现把方差吞了

    def test_bootstrap_width_tracks_sample_size(self):
        """样本量越小区间越宽 —— 这正是 Wilson 固定 100 样本丢掉的东西。

        旧口径把跨任务均值乘 100 再除以 100, 于是 5 个单元与 50 个单元算出
        同一个区间; 这里断言单元数与区间宽度真的挂钩。
        """
        few = [0.9, 1.0, 0.8, 0.95, 0.85]
        many = few * 10                        # 同分布、单元数 ×10 → 区间应显著收窄
        assert (bootstrap_mean_ci(many)[1] - bootstrap_mean_ci(many)[0]) < \
               (bootstrap_mean_ci(few)[1] - bootstrap_mean_ci(few)[0])   # 宽度随样本量收窄

    def test_bootstrap_single_unit_is_not_a_point_interval(self):
        """只有一个单元时返 (0,1) 而不是零宽区间 (无离散度可估, 不得给假确定)。"""
        assert bootstrap_mean_ci([1.0]) == (0.0, 1.0)      # 单单元: 任何重抽都是同一个值
        assert bootstrap_mean_ci([]) == (0.0, 1.0)         # 空输入同上

    def test_bootstrap_zero_variance_group_is_flagged_by_caller(self):
        """全同取值时区间退化为零宽 —— 纯函数照给, 由计分层标记并披露。

        零宽区间在数学上正确, 但报告里必须说明那是"任务间零离散度"而不是
        "可复现性被证明为 1.0"; 这条守住 bootstrap_mean_ci 不擅自加宽/收窄。
        """
        low, high = bootstrap_mean_ci([1.0] * 18)
        assert (low, high) == (1.0, 1.0)      # 刻意退化: 披露责任在调用方, 不在统计件里粉饰

    # ── CLI 层: 区间样本量与清单绑定状态必须自报 (报告口径不能靠人记) ──────

    def _run_cli(self, report_path: Path, *extra: str) -> dict:
        """跑一次 R0 实跑并读回报告 JSON (CLI 契约面: 走子进程, 与单测同一条入口)。

        刻意用子进程而不是直接调 main(): `--json` 落盘与退出码都是 CLI 契约的
        一部分, 直接调函数会把这半边契约漏在断言之外。
        """
        proc = subprocess.run([sys.executable, str(REPRO_DIR / "run_e6.py"), "--lane", "R0",
                               "--repeat", "2", "--json", str(report_path), *extra],
                              capture_output=True, text=True, encoding="utf-8", errors="replace",
                              timeout=900)                                     # 离线回放, 无外网; 超时只可能来自死锁
        assert proc.returncode == 0, proc.stdout[-2000:]                       # 设施自证批本身应跑通, 失败即代码坏了
        return json.loads(report_path.read_text(encoding="utf-8"))             # 报告是数字真值: 与 Markdown 同源

    def test_ci_sample_sizes_are_real_not_hundred(self, tmp_path):
        """区间样本量必须是真实任务数与总 run 数, 不是写死的 100。

        这条是旧口径 (`wilson_interval(round(v*100), 100)`) 的直接反证: 那个
        写法把跨任务均值乘 100 当成"成功次数", 于是样本量恒为 100, 与重复
        次数和覆盖任务数都脱钩。
        """
        report = self._run_cli(tmp_path / "e6.json")
        assert report["n_tasks_scored"] == 18                    # R0 预写序列实况 (18 条), 写死 100 时这里是 100
        assert report["n_runs_total"] == 36                      # 18 任务 × 2 次: 区间样本量随 --repeat 变
        assert "cluster-bootstrap" in report["ci_method"]         # 口径自报: 按任务重抽, 不再冒充 100 次 Bernoulli

    def test_unbound_batch_declares_itself_unbound(self, tmp_path):
        """不带 --manifest 的批次必须自称"未绑定", 不能被读成复现成功。

        退出码仍为 0: 设施自证批的结论是"R0 地板线仍成立", 与"这批有没有绑清单"
        是两个问题 —— 后者靠报告披露, 不靠把整批判死 (判死的是 `--require-full-coverage`)。
        """
        report = self._run_cli(tmp_path / "e6.json")
        assert report["manifest_binding"]["bound"] is False      # 绑定状态显式为假
        assert "未绑定" in report["manifest_note"]               # 且报告正文自己说出来, 不靠人记得加 --manifest

# ── 冻结清单与跑批的绑定 (清单不接执行 = 清单锁不住任何东西) ────────────────

class TestManifestBinding:
    """--freeze-manifest 落盘的清单必须被 R0 执行认领, 而不是各跑各的。

    历史缺陷: 冻结分支落盘即 return, 后续执行既不读清单也不接受它的路径 ——
    于是"落盘即冻结"这句话是空的: 换一组参数重跑, 报告照样出得来, 而两次
    跑批的清单可以完全不同。这里把清单接进执行路径并逐项核对。
    """

    def test_matching_manifest_binds_without_problems(self, tmp_path):
        """参数与清单一致 → 绑定成功, 无阻断项 (正向自证: 闸门不是永远拦)。"""
        manifest = _valid_manifest()                                       # 合法清单 (缓存件, 只读不改)
        path = _write_manifest_file(manifest, tmp_path)                    # 走 save_manifest 落盘, 与真实冻结同一条路
        _bound, problems = bind_manifest(str(path), repeat=int(manifest["execution"]["repeat"]))  # 参数照清单
        assert problems == []                                    # 合规绑定必须放行, 否则这批永远不敢用

    def test_repeat_mismatch_blocks(self, tmp_path):
        """实跑重复次数与清单不符 → 阻断 (一致率的分母变了就不是同一批)。"""
        manifest = _valid_manifest()                                       # 合法清单做底
        path = _write_manifest_file(manifest, tmp_path)                    # 落盘后不可变: 复跑比的就是这一份
        _bound, problems = bind_manifest(str(path), repeat=int(manifest["execution"]["repeat"]) + 1)  # 多跑一次
        assert any(p.startswith("manifest_repeat_mismatch") for p in problems)   # 断码不断全文: 报告要能按码聚合

    def test_lane_mismatch_blocks(self, tmp_path):
        """拿 R1/R2/R3 的清单跑 R0 → 阻断 (张冠李戴)。"""
        manifest = _mutated(**{"execution.lane": "R1"})                    # 只改 lane 一项, 其余仍合法
        path = _write_manifest_file(manifest, tmp_path)                    # 篡改后的清单也走落盘, 免绕过校验
        _bound, problems = bind_manifest(str(path), repeat=int(manifest["execution"]["repeat"]))
        assert any(p.startswith("manifest_lane_mismatch") for p in problems)   # 码要带原值, 复核者一眼看出张冠李戴

    def test_tool_schema_drift_blocks(self, tmp_path):
        """清单记的工具面指纹与现版本不符 → 阻断 (中途改过被测面)。"""
        manifest = _mutated(**{"tool_schema.code_side": "sha256:" + "0" * 64})   # 指纹换成假的
        path = _write_manifest_file(manifest, tmp_path)                    # 落盘
        _bound, problems = bind_manifest(str(path), repeat=int(manifest["execution"]["repeat"]))
        # 断到具体 side 名: 只断前缀的话, 两侧同时漂移会与"只漂了一侧"同形
        assert any(p.startswith("manifest_tool_schema_drift:code_side") for p in problems)

    def test_missing_manifest_file_raises(self):
        """清单文件不存在即抛 (不得退回"当裸跑"): 拿不到清单就不能出正式结论。"""
        with pytest.raises(FileNotFoundError):                             # 抛错而非返回空表
            bind_manifest(str(FIXTURES_DIR / "__no_such_manifest__.json"), repeat=5)   # 路径不存在
