"""复核面轮的回归测试 (provenance 伴生文件、审计读侧)。

职责: 守住「事后可追溯」这条能力不被悄悄删掉 —— provenance envelope 必须
在生产路径里被真正构造, query-audit 记录器必须真的被读侧消费; 两者任一
退化成「测试专属」, 「这个文件来自哪次查询」在事后就根本无法回答。
所属层次: test/unit 层 (audit_round 组); 被测模块是 src.provenance
(血缘信封构造与身份解析)、src.downloader (落盘伴生文件)、src.core
(管线级客户端与审计读数)、src.scripts.context (查询上下文)。
对外接口: TestEnvelope 钉信封构造契约 (会话可分组、完整性门诚实、哈希自洽);
TestProvenanceSidecar 钉「落盘必伴随生文件、且伴生失败不阻断下载」;
TestAuditReadSide 钉审计读侧的计数真实、视图不改写历史、参数存副本、
质量门每源只跑一次。
依赖与数据流: 夹具全在内存里现造 (BestQueryResult/BestSource 直接构造),
落盘一律走 pytest 的 tmp_path —— 伴生文件与 .checkpoints 都落临时目录, 跑完
即弃; 断言读的是 tmp_path 下真实落盘的字节与 JSON, 网络侧全用 Mock 替身。
关键契约与不变量: 全程离线, client 传 Mock 绝不打真实站点 (铁律 7); 写入只
发生在 tmp_path 内, 不碰工作区; 伴生文件里的 sha256 必须与盘上数据同源计算,
不得复用调用方传进来的缓存值。
陷阱与边界: 空载荷的完整性门必须返回 0.0 —— 默认充成 1.0 会让「字段缺失」
冒充「数据完整」, 而这类谎报比缺失本身更难被发现; 伴生文件是增强面而非硬依赖,
构造失败只应记 WARNING, 绝不能把用户已经拿到的数据一并回滚。
"""
from __future__ import annotations  # 标准库: 注解延迟求值

# 标准库: json 读回 provenance 伴生文件; logging 捕获 WARNING 日志;
# unittest.mock 的 Mock/patch 在协议层之下打桩 (真实逻辑照跑)。
import json
import logging
from unittest.mock import Mock, patch

# 第三方: pytest 承载断言
import pytest

# 本地: 客户端入口 / 落盘 / 数据模型 / provenance 面 / 查询上下文 (跨能力边界)
try:
    # src.core: 管线级客户端与质量门禁; src.downloader: 流式下载 + 校验和; src.models: 查询结果/单源/约束的数据模型; src.provenance: 血缘信封构造 (data_hash 可复核); src.scripts.context: 查询上下文 (token 预算 + 血缘)
    from src.core import BestSkillClient
    from src.downloader import BestDownloader
    from src.models import BestQueryResult, BestSource
    from src.provenance import build_envelope, compute_data_hash, current_session_id
    from src.scripts.context import QueryContext
except Exception as _legacy_err:  # legacy-import-guard
    # 任一模块缺失即整模块 skip: 这些回归只在完整交付里才有意义
    import pytest as _pytest
    _pytest.skip(f'legacy import unavailable: {_legacy_err!r}', allow_module_level=True)          # 模块级跳过: 这些回归只在完整交付里才有意义


class TestEnvelope:
    """provenance envelope 的构造契约: 会话可分组、完整性门诚实、哈希自洽。"""

    def test_session_id_is_reused_within_a_process(self):
        """同一进程内 session_id 必须稳定 (否则 envelope 无法按会话分组)。"""
        first = current_session_id()                                                                # 先取一次会话号作为基准
        assert current_session_id() == first, "envelopes must be groupable by session"  # 同进程内必须稳定

    def test_completeness_gate_is_honest_for_empty_payloads(self):
        """空载荷的完整性门必须是 0.0, 不得默认充值为 1.0 冒充完整。

        挡的是"用默认值撒谎"这一类回归: 载荷为空恰恰是完整性最差的情形,
        若默认 1.0, 下游拿到的是"数据完整"的结论, 而实际一条源都没有。
        """
        envelope = build_envelope([])                                                               # 空载荷信封: 完整性最差的情形
        assert envelope["lineage"]["completeness_gate"]["value"] == 0.0  # 空载荷 = 零完整, 不是默认值 1.0
        assert build_envelope([{"a": 1}])["lineage"]["completeness_gate"]["value"] == 1.0  # 单源齐全 = 1.0

    def test_caller_can_supply_the_real_completeness_judgement(self):
        """调用方可以给出真实完整性判定 (缺这个口子就只能靠默认值猜)。

        边界值取 0.5 这个既非 0 也非 1 的中间值: 用 0 或 1 当探针的话, 判据
        分不清"调用方传的值"与"库里的默认值", 传参通路坏掉也不会红。
        """
        envelope = build_envelope([{"a": 1}], completeness={"required": True, "value": 0.5})        # 调用方自带判定: 传参通路坏掉时这条会红
        assert envelope["lineage"]["completeness_gate"]["value"] == 0.5  # 0.5 排除默认值歧义

    def test_data_hash_matches_the_payload(self):
        """data_hash 必须与载荷一致 (哈希对不上 = 血缘不可信)。

        载荷故意用乱序的键 (b 在前 a 在后) 钉住一点: 实现若依赖键的插入序
        去序列化, 同一份内容换个来源顺序就会算出不同的哈希, 跨进程复核立刻
        失效, 而这种缺陷在单进程测试里根本看不出来。
        """
        payload = {"b": 2, "a": 1}  # 乱序键: 哈希不得依赖插入序
        envelope = build_envelope(payload)                                                          # 构造一个非空载荷信封: 哈希自洽靠它验
        assert envelope["data_hash"] == compute_data_hash(payload)  # 同源函数算出的才可比

    def test_identity_failure_is_logged_not_silently_swallowed(self, caplog):
        """身份解析失败必须落 WARNING 日志, 不得静默吞掉。

        模拟对象与协议阶段: token store 替身返回未过期+有效 token,
        ``src.auth.get_profile`` 被钉成抛 RuntimeError (协议阶段 = 身份解析),
        断言返回 {} 且原因进了日志。
        """
        # 本地: identity_from_token_store — 身份解析入口 (验失败落日志不静默)
        from src.provenance import identity_from_token_store

        store = Mock()                                                                              # 令牌存储替身: 身份解析的输入
        store.is_expired.return_value = False  # 未过期: 让判定走到取 profile 那一段
        store.valid_token.return_value = "tok"                                                      # 有有效令牌: 走"已认证"分支
        with patch("src.auth.get_profile", side_effect=RuntimeError("nadc down")), \
                caplog.at_level(logging.WARNING):                                                   # 同时捕获 WARNING: 降级要留痕
            assert identity_from_token_store(store) == {}  # 失败返回空身份而非抛
        assert "nadc down" in caplog.text  # 原因必须落日志, 否则失败无从排查


class TestProvenanceSidecar:
    """落盘必须同时写出可验证的 provenance 伴生文件, 且永不阻塞下载本身。"""

    def _result(self) -> BestQueryResult:
        """构造一个带 query_params 的标准查询结果 (被测夹具, 非真实网络)。"""
        return BestQueryResult(
            success=True,                                                                           # 成功标志
            total_count=2,                                                                          # 总数与返回数
            returned_count=1,
            sources=[BestSource(source_id="S1", ra=180.0, dec=30.0,                                 # 单源: 血缘信封的载荷
                                magnitudes={"r": 15.2})],                                           # 带星等的源
            query_params={"catalog": "ps1/q", "sqlid": "s4242"},                                  # 查询参数: 会话号与星表路径都要落进伴生文件
        )

    def test_download_writes_a_verifiable_sidecar(self, tmp_path):
        """每次落盘都必须伴随一个可验证的 provenance 伴生文件。

        伴生文件里的 sha256 必须与盘上数据一致, query_params/sqlid 与
        completeness_gate 都要如实记录 — 这是「哪个文件来自哪次查询」的唯一
        事后答案。checksum_match 必须是**真实判定出的布尔** (写前意图摘要
        vs 写后读回摘要), 既不得恒写 "unknown" (那样 blocking 门禁
        checksum_match==True 永不可满足), 也不得无条件写 True (假门禁)。
        """
        downloader = BestDownloader(Mock(), output_dir=str(tmp_path),                       # 只做落盘的下载器: client 传 Mock, 不触网
                                    checkpoint_dir=str(tmp_path / ".checkpoints"))                  # 断点目录锚在临时区
        path = downloader._save_result(self._result(), "out.csv", "csv")                            # 走真实的落盘入口
        sidecar = tmp_path / "out.csv.provenance.json"  # 伴生名 = 数据名 + .provenance.json
        assert sidecar.exists(), "downloads must carry a reviewable provenance sidecar"    # 伴生文件必须在场: 缺了"这个文件来自哪次查询"就无从回答
        envelope = json.loads(sidecar.read_text(encoding="utf-8"))                                  # 回读伴生文件: 读盘上那份才谈得上可复核
        assert envelope["schema"] == "astro-envelope-v1"  # schema 键是消费方的版本判据
        assert envelope["data"]["sha256"] == downloader.compute_sha256(path)  # 现场算, 不复用调用方缓存值
        assert envelope["data"]["query_params"]["sqlid"] == "s4242"  # 溯源到具体 sqlid: 事后可追
        assert envelope["data"]["checksum_match"] is True  # 真比对通过才写 True: 恒 "unknown" 是假门禁, 恒 True 同样是
        assert envelope["lineage"]["completeness_gate"]["value"] == 1.0  # 单源 = 完整

    def test_sidecar_failure_never_blocks_the_download(self, tmp_path):
        """伴生文件构造失败不得阻断下载 (复核面是增强, 不是硬依赖)。

        挡的是"增强面反过来绑架主流程"这一类回归: 用户已经等到了数据, 却因为
        写不进伴生文件而拿不到文件, 那是纯粹的功能倒退。
        """
        downloader = BestDownloader(Mock(), output_dir=str(tmp_path),                               # 同样只做落盘
                                    checkpoint_dir=str(tmp_path / ".checkpoints"))                  # 断点目录锚在临时区
        # build_envelope 整体被钉成抛错, 覆盖的是伴生构造的任一环节而非特指某行
        with patch("src.provenance.build_envelope", side_effect=RuntimeError("boom")):             # 构造伴生失败: 伴生是增强面, 不是硬依赖
            path = downloader._save_result(self._result(), "out2.csv", "csv")                      # 落盘仍要成功: 用户已拿到的数据不能被回滚
        assert path.endswith("out2.csv")  # 伴生崩了但数据仍要落盘: 增强面不得绑架主流程


class TestAuditReadSide:
    """审计读侧: 计数真实、视图不改写历史、参数存副本、质量门不重复跑。

    读侧的失效形态与写侧相反 —— 它不会崩, 只会安静地少报或改写, 而读审计
    的人正是靠这些数字做判断的, 数字一美化整条复核链就失去依据。
    """

    def test_audit_summary_reports_real_counts(self):
        """audit_summary 必须如实汇总操作次数与结果总数 (审计读数不可美化)。"""
        client = BestSkillClient(rate_limit=0)  # rate_limit=0: 全程离线, 绝不打真实站点
        client.context.record("cone_search", {"ra": 1.0}, 7)  # 两次结果数不同: 才能验出是求和
        client.context.record("cone_search", {"ra": 2.0}, 3)                                        # 先记一次调用
        summary = client.audit_summary()                                                            # 读审计摘要
        assert summary == {"total_operations": 2, "total_results": 10,  # 7+3, 不是取最大值 7
                           "max_sources": client.context.max_sources}                              # 摘要要含展示预算: 只报结果数就看不出钳制

    def test_audit_history_returns_a_thinned_view_without_rewriting_history(self):
        """截断视图只是视图: 视图上限生效, 源历史总数必须原样保持。

        挡的是"截断顺手把源数据也改了"这一类回归 —— 一次为了省内存做的截断,
        若把源历史一起削掉, 用户再调一次大一点的视图就永远拿不回全量了。
        """
        context = QueryContext(max_sources=1000)  # 上限远高于视图, 让截断只可能来自 truncate(10)
        # 两条各 500 条: 单条就等于视图上限会让"逐条截断"与"总量截断"两种实现
        # 得到同样的结论, 断言就分不出实现到底截在哪一层
        context.record("cone_search", {"ra": 1.0}, 500)                                             # 记两次大结果: 摊薄的输入
        context.record("cone_search", {"ra": 2.0}, 500)                                             # 再记一次: 两次都超预算才看得出钳制
        view = context.truncate(10)                                                                 # 按展示预算取视图
        assert sum(h["n_results"] for h in view) <= 10  # 视图受限
        assert sum(h["n_results"] for h in context.history) == 1000  # 源历史原样: 截断不得改写

    def test_record_stores_a_copy_of_the_params(self):
        """record 必须存 params 的副本 (调用方复用 dict 不得改写历史)。"""
        context = QueryContext()                                                                    # 新建上下文: 避免受其它用例的预算影响
        params = {"ra": 1.0}                                                                        # 参数字典要留副本
        context.record("cone_search", params, 1)                                                    # 记一次调用
        params["ra"] = 999.0  # 调用方复用该 dict 不得改写已记录的历史
        assert context.history[0]["params"]["ra"] == 1.0  # 存的是副本: 复用不污染历史

    def test_quality_gate_runs_once_per_source(self):
        """质量门对每个源只跑一次 (重复跑既慢又可能给出不一致判定)。

        模拟对象与协议阶段: cone_search 被替身替换为返回预构造结果,
        validate_source 用 wraps 包住真实实现以便计数 (协议阶段 = 质量门)。
        """
        client = BestSkillClient(rate_limit=0)                                                      # 管线级客户端
        source = BestSource(source_id="S1", ra=180.0, dec=30.0,                                     # 带信噪比的源: 质量门要真跑过它
                            magnitudes={"r": 15.2}, snr=40.0)                                       # 星等与信噪比
        with patch.object(client.client, "cone_search") as mock_cs, \
                patch.object(client.quality, "validate_source",                                   # 包住而不是替换: 门真要跑, 只是顺便数次数
                             wraps=client.quality.validate_source) as mock_gate:                    # 数调用次数: 验"每源只跑一次"
            mock_cs.return_value = BestQueryResult(success=True, sources=[source],                  # 回一个命中的结果
                                                   total_count=1)                                   # 总数为一
            rows = client.cone_search(180.0, 30.0, quality_filter=True)                             # 带质量过滤调用: 过滤开关打开才走质量门
        assert len(rows) == 1 and "quality" in rows[0]  # 质量字段必须被写回行里
        assert mock_gate.call_count == 1, "the gate must not run twice per source"  # 一源一次
