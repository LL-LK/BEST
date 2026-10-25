# -*- coding: utf-8 -*-
"""Phase 6 provenance 信封与 QueryContext 载体测试 (Q-08/Q-52 接线验证)。

职责: 守住三条身份/血缘契约的回归 —— 数据哈希必须键序无关且确定 (信封去重与
  跨会话比对全靠它); 信封骨架字段与血缘引用不得被下游改写; 未授权/过期身份必须
  整体缺席而不是塞个空壳进血缘。
所属层次: test/unit 层, 对应被测模块 src/provenance.py (build_envelope /
  compute_data_hash / envelope_for_result)、src/core/ (BestSkillClient 自带的
  QueryContext 记账) 与 src/auth/ (OAuthProfile / TokenStore); 末节另起子进程
  端到端验 ops/astro_best_cli.py 的 oauth 子命令。
对外接口: TestDataHash 两条用例守哈希的确定性与 64 位宽度; TestEnvelope 覆盖信封
  形状、身份段挂载/缺失、血缘引用原样保留; TestQueryContextWiring 验操作次数与
  结果数累加、truncate 只裁视图; TestOAuthCli 以子进程验 status/token/url 三态。
依赖与数据流: 夹具只有 pytest 的 tmp_path, 令牌缓存与 CLI 隔离 HOME 都落在它下面;
  身份段靠 patch("src.provenance.TokenStore") 注入替身来制造"有/无/过期"三种态;
  断言读的是信封字典与子进程 stdout 的 JSON; 全程零网络, 唯一的写操作就是往
  tmp_path 里落令牌文件, 不碰真实 ~/.astro-best。
关键契约与不变量: 离线回放 —— 子进程只跑 oauth 子命令, 不发任何请求; 身份段缺失
  不得阻断主链 (未登录也要能查公开星表); missing 与 expired 是两个 state, 排障
  动作不同; oauth token 在无头且过期时必须 rc=1, 绝不能把过期凭据交出去。
陷阱与边界: 这组断言挡的是"把身份缺失降级成空 dict"与"令牌过期照发"两类回归 ——
  前者让血缘段出现 identity={} 的假身份, 后者让 401 晚一个任务周期才暴露;
  expires_in=-10 是显式造过期, 比 sleep 等待确定得多也不拖慢测试。
"""
from __future__ import annotations

# 标准库: JSON 回读 CLI 输出、路径解析 (SKILL_ROOT 锚定) 与 mock 补丁
import json
from pathlib import Path
from unittest.mock import patch

# 第三方: pytest — tmp_path 夹具注入 (令牌落盘/CLI 隔离 HOME 的临时目录) 与测试发现
import pytest

# 本地: 身份载体 OAuthProfile/TokenStore (provenance 身份段的两个来源)
from src.auth import OAuthProfile, TokenStore

# 本地: provenance 信封三件套 —— 信封构造、数据哈希、结果信封适配
from src.provenance import build_envelope, compute_data_hash, envelope_for_result


class TestDataHash:
    """数据哈希契约: 键序无关、确定性强、长度固定为 SHA-256 十六进制。"""

    def test_deterministic_and_order_insensitive(self):
        """同内容不同键序必须同哈希 (信封去重与比对依赖此性质), 内容变则哈希必须变。"""
        a = {"x": 1, "y": [1, 2]}  # 同内容换键序仍同哈希: 去重与跨会话比对全靠这条性质
        b = {"y": [1, 2], "x": 1}  # 两份字典字面不同序, 归一化失效应让下面第一条直接分叉
        assert compute_data_hash(a) == compute_data_hash(b)  # 键序无关: 挡住\按插入序拼串\的实现, 那会让等价信封对不上
        assert compute_data_hash(a) != compute_data_hash({"x": 2})  # 内容变则哈希必须变: 挡住恒返回常量的桩, 那会让去重形同虚设

    def test_sha256_length(self):
        """哈希串长 64 字符 (SHA-256 十六进制), 与血缘引用字段宽度一致。"""
        assert len(compute_data_hash({"k": "v"})) == 64  # 宽度即契约: 血缘引用字段按 64 位 SHA-256 十六进制对齐


class TestEnvelope:
    """astro-envelope-v1 信封: 结构字段、身份段挂载/缺失、血缘引用保留。"""

    def test_envelope_shape(self):
        """信封骨架字段 (schema/status/data_hash/provenance/lineage) 必须齐备。

        回归锚点: 跨 skill 传递统一走 envelope; schema 名或 completeness_gate 缺失会
        让下游 skill 的解包端直接拒绝。
        """
        env = build_envelope({"rows": [1, 2]}, status="ready", session_id="sess-1")  # 信封骨架一次成型, 下面逐字段断的都是它的不可变形状
        assert env["schema"] == "astro-envelope-v1"  # schema 名被下游解包端硬编码, 改它等于让跨 skill 传递全断
        assert env["status"] == "ready"                                                           # 骨架状态必须固定: 下游按它判断信封能不能用
        assert len(env["data_hash"]) == 64                                                     # 数据哈希宽度必须对: 血缘引用字段按 64 位对齐
        assert env["provenance"]["skill"] == "astro-best"                                        # 归属 skill 名要落: 跨会话比对靠它分桶
        assert env["provenance"]["session_id"] == "sess-1"                                          # 会话号要落: 这是信封唯一的分组键
        assert env["lineage"]["completeness_gate"]["required"] is True  # 默认即必检: 门禁缺席会让下游 skill 无法判断数据是否完整
        assert env["lineage"]["inputs_ref"] == []  # 无上游输入时空列表是合法初值, 不是缺省异常的信号

    def test_envelope_with_oauth_identity(self):
        """显式传入 OAuthProfile 时, 身份段按 NADC 原始字段名 (umtId/ldap_id) 落座。"""
        profile = OAuthProfile(umt_id="UMT-1", ldap_id="astro", name="N", email="e@x")  # NADC 原始字段名直接落座, 不做下划线改写的猜测
        env = build_envelope({"rows": []}, profile=profile, session_id="s")  # 显式传 profile 的旁路: 不读 TokenStore 也能挂身份段
        assert env["provenance"]["identity"]["umtId"] == "UMT-1"                                    # 身份段里的用户标识必须原样带出
        assert env["provenance"]["identity"]["ldap_id"] == "astro"  # 同名不同拼写(umtId/ldap_id)混用会让下游身份比对恒不相等

    def test_identity_from_token_store_unauthorized(self, tmp_path):
        """无授权缓存时身份段整体缺失, 且不阻断主链 (未登录也能查公开星表)。"""
        store = TokenStore(path=tmp_path / "none.json")  # 空路径下 TokenStore 读不到任何缓存, 身份段因此缺席
        env = build_envelope({"r": 1})  # 不传 profile 时信封自行回落到 TokenStore 探测
        # 无授权缓存 -> 身份段缺失 (不阻断主链)
        assert "identity" not in env["provenance"]                                                 # 身份缺失必须整段缺席: 塞空壳会造出假身份

    def test_identity_from_token_store_expired(self, tmp_path):
        """令牌过期等价于未授权: 身份段同样缺失, 避免把过期身份写进血缘。"""
        store = TokenStore(path=tmp_path / "tok.json")                                              # 令牌存储锚在临时区
        store.save({"access_token": "t", "expires_in": 1})  # expires_in=1 造的是刚有效, 过期的对例在下一条单独造
        # 补丁 src.provenance.TokenStore: 让信封构造读到这个"已过期"的存储
        with patch("src.provenance.TokenStore", return_value=store):                               # 注入令牌存储: 身份段的两个来源都由它决定
            env = build_envelope({"r": 1})                                                          # 构造信封
        assert "identity" not in env["provenance"]                                                # 过期身份同样整段缺席: 假身份比没有身份更坏

    def test_envelope_for_result(self):
        """envelope_for_result 把查询结果对象 to_dict 后塞进 data 段, 并带上 session_id。"""

        # 替身结果对象: 只需 to_dict 契约, 模拟 BestQueryResult 的序列化出口
        class _R:
            """替身查询结果: 只实现 ``to_dict`` 契约 (不依赖真实 BestQueryResult)。

            这样用例聚焦在"信封怎么包装结果"而不是"结果对象怎么构造" —
            真实对象还要星表/约束等一堆前置状态, 会把这处契约测试淹没掉。
            """

            def to_dict(self):
                """返回最小可用的结果字典 (``success`` + 空 ``sources``)。"""
                return {"success": True, "sources": []}

        env = envelope_for_result(_R(), session_id="s2")  # 结果对象只经 to_dict 出口被消费, 信封不碰它的内部字段
        assert env["provenance"]["session_id"] == "s2"  # session_id 走透传: 换会话后血缘若串号, 跨会话比对即失效
        assert env["data"]["success"] is True  # data 段原样收下 to_dict 的出口, 不做字段筛选或重命名

    def test_lineage_refs_preserved(self):
        """inputs_ref/outputs_ref 由调用方给定并原样保留, 信封不得改写血缘引用。"""
        env = build_envelope({}, inputs_ref=["h1"], outputs_ref=["h2"])                             # 显式传血缘引用
        assert env["lineage"]["inputs_ref"] == ["h1"]  # 调用方给什么就存什么: 挡住信封擅自归一化或重算血缘
        assert env["lineage"]["outputs_ref"] == ["h2"]                                              # 输出引用必须原样保留: 下游不得改写它


class TestQueryContextWiring:
    """Q-52: BestSkillClient 自带 QueryContext, 记录操作次数/结果数/截断视图。"""

    def test_record_carrier_in_client(self):
        """context 记账要累加总数, 且 truncate 只裁视图不改源数据。

        回归锚点: truncate 只裁视图, 就地改写 records 会让同一客户端第二次 summary 数字对不上。
        """
        # src.core: 管线级客户端与质量门禁
        from src.core import BestSkillClient

        client = BestSkillClient()  # 真客户端而非 mock: Q-52 要验的是自带记账载体确实接线
        assert hasattr(client, "context")  # context 存在即合格: 缺属性说明门控层被换成了别的实现
        # 记录真实计数 (Q-52)
        client.context.record("cone_search", {"ra": 180.0}, 7)  # 两次不同操作各记一笔, 用来证明累加而不是覆盖
        client.context.record("download", {"ra": 181.0}, 3)                                         # 再记一次: 两次调用合起来才看得出累加
        assert client.context.summary()["total_results"] == 10  # 7+3 累计成 10: 挡住\后写覆盖前写\的记账实现
        # truncate 不改写源
        view = client.context.truncate(max_records=4)  # truncate 只裁视图, 下一条再断源计数未被动过
        assert sum(h["n_results"] for h in view) <= 4                                               # 摊薄后总数不得超过展示预算
        assert client.context.summary()["total_results"] == 10                                      # 真实计数不得被裁剪改写

    def test_cone_search_records_context(self):
        """cone_search 走客户端门面后必须落一条 context 记录 (空结果也记)。"""
        # unittest.mock: 打桩替身 (离线化唯一手段); src.core: 管线级客户端与质量门禁
        from unittest.mock import MagicMock

        from src.core import BestSkillClient

        client = BestSkillClient()  # 替身只实现序列化出口, 让本例聚焦信封如何包装结果
        # 替身查询结果: sources 为空, 验证"零结果"同样计入 total_operations
        mock_result = MagicMock()  # sources 置空: 验证零结果也照样留下一条操作记录
        mock_result.sources = []                                                                   # 空源列表: 这条要看的是记账而不是匹配结果
        with patch.object(client.client, "cone_search", return_value=mock_result):                  # 打桩锥搜
            client.cone_search(180.0, 30.0, 60.0)                                                   # 走公开入口
        summary = client.context.summary()  # summary 是记账的唯一读出口, 下面两条都从它取值
        assert summary["total_operations"] == 1  # 一次调用即一条: 操作数记错会让配额与审计全部偏移
        assert summary["total_results"] == 0  # 零结果仍记 0 而不记 None: 累加型字段混进 None 会让 summary 崩


class TestOAuthCli:
    """ops/astro_best_cli.py 的 oauth 子命令端到端 (子进程 + 隔离 HOME)。"""

    # 类级常量: 仓库根 = 本文件上溯三级 (test/unit/auth -> 仓库根), 子进程 cwd 用它
    SKILL_ROOT = Path(__file__).resolve().parents[3]  # 上溯三级出 test/unit/auth 到仓库根, 子进程 cwd 靠它找 ops/

    def test_status_unauthenticated(self, tmp_path):
        """HOME 指向空目录时 oauth status 必须报 unauthorized 且退出码为 0。

        回归锚点: 未授权是正常状态而非故障; 退出码非 0 会让运维脚本误判为崩溃。
        """
        # os: 重定向 HOME/USERPROFILE 隔离真实凭据缓存; subprocess: 起 CLI 子进程; sys: 解释器路径
        import os
        import subprocess
        import sys

        # 起子进程跑 CLI; HOME/USERPROFILE 重定向到 tmp_path 以隔离真实凭据缓存
        proc = subprocess.run(                                                       # 子进程拉起: CLI 各自的仓根定位与 HOME 解析只能在真进程里验
            [sys.executable, "ops/astro_best_cli.py", "oauth", "status"],                           # 只跑 oauth 子命令: 不发任何请求
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,         # 解码与超时都要钉死
            env={**os.environ,                                                                  # 刻意不注入 PYTHONIOENCODING: 本条断的是 oauth status 不靠调用方环境也能输出中文 (A6)
                 "HOME": str(tmp_path), "USERPROFILE": str(tmp_path)},                          # 隔离 HOME: 绝不碰真实用户目录下的令牌缓存
            cwd=str(self.SKILL_ROOT),                                                               # 工作目录必须是仓根
        )
        # HOME 重定向后无缓存 -> unauthorized (退出码 0)
        payload = json.loads(proc.stdout)                                                           # 回读 JSON 输出
        assert payload["authorized"] is False                                                       # 未授权状态
        # 三态可判 — 从没有缓存是 missing (不是 expired), 且载荷
        # 必须带恢复命令 hint (无 refresh_token, 排障时不用翻文档)
        assert payload["state"] == "missing"                                                   # 缺令牌与过期令牌是两个 state: 排障动作不同
        assert "oauth login" in payload["hint"]                                                     # 必须给出可复制的恢复命令

    def test_status_expired_state(self, tmp_path):
        """过期缓存: status 必须报 state=expired (授权过又过期 ≠ 从没授权)。

        回归锚点: auth §5.5 — NADC 无 refresh_token, 过期与缺失的恢复动作
        相同 (重走授权), 但排障是两件事; 退出码仍为 0 (未授权不是故障)。
        """
        import os
        import subprocess
        import sys

        # 经 TokenStore 落一枚已过期 token (v2 信封, 与本机平台保护一致)
        cache = tmp_path / ".astro-best" / "nadc_token.json"                                        # 令牌缓存落在隔离 HOME 下
        TokenStore(path=cache).save({"access_token": "stale", "expires_in": -10})                 # 负寿命造过期: 比 sleep 等待确定得多
        proc = subprocess.run(                                                                      # 子进程拉起
            [sys.executable, "ops/astro_best_cli.py", "oauth", "status"],                           # 只跑状态子命令
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,         # 解码与超时
            env={**os.environ,                                                                  # 同上刻意不注入: token 子命令的 JSON 出口也必须自己钉 UTF-8 (A6)
                 "HOME": str(tmp_path), "USERPROFILE": str(tmp_path)},                              # 同样隔离 HOME
            cwd=str(self.SKILL_ROOT),                                                               # 工作目录必须是仓根
        )
        payload = json.loads(proc.stdout)                                                           # 回读 JSON 输出
        assert payload["authorized"] is False                                                       # 过期即未授权
        assert payload["state"] == "expired"                                               # state 必须是 expired 而不是 missing
        assert "oauth login" in payload["hint"]                                                     # 同样要给恢复命令

    def test_token_subcommand_prints_valid_token(self, tmp_path):
        """oauth token: 有有效缓存时打印 token 本身 (无头管道消费面)。"""
        # 本地: 被测 OAuth 身份层 (令牌存储/恢复路径/CLI 三态的守门对象)
        import os
        import subprocess
        import sys

        cache = tmp_path / ".astro-best" / "nadc_token.json"                                        # 有效令牌: 走的是"授权且未过期"那条
        TokenStore(path=cache).save({"access_token": "headless-token",                              # 令牌与寿命
                                     "expires_in": 3600})
        proc = subprocess.run(                                                                      # 子进程拉起
            [sys.executable, "ops/astro_best_cli.py", "oauth", "token"],                            # 只跑取令牌子命令
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,         # 解码与超时
            env={**os.environ,                                                                  # 同上: 过期令牌的错误消息含中文, 靠注入就等于没测 CLI 自己的出口 (A6)
                 "HOME": str(tmp_path), "USERPROFILE": str(tmp_path)},                              # 同样隔离 HOME
            cwd=str(self.SKILL_ROOT),                                                               # 工作目录必须是仓根
        )
        assert proc.returncode == 0                                                                 # 成功退出: 无头场景就靠这一个退出码
        assert proc.stdout.strip() == "headless-token"                                     # 必须只吐令牌本身: 多一行提示就会让 shell 注入出错

    def test_token_subcommand_expired_errors_with_command(self, tmp_path):
        """oauth token: 过期且无交互通道时 rc=1 且 stderr 带恢复命令。

        回归锚点: 无头脚本绝不能把过期令牌当有效凭据拿到手 (那会让 401 晚一个
        任务周期才暴露); 命令必须可复制执行, 运维不用翻文档。
        """
        # 本地: 被测 OAuth 身份层 (令牌存储/恢复路径/CLI 三态的守门对象)
        import os
        import subprocess
        import sys

        cache = tmp_path / ".astro-best" / "nadc_token.json"                                        # 过期令牌: 用来证明过期令牌不会被交出去
        TokenStore(path=cache).save({"access_token": "stale", "expires_in": -10})                   # 负寿命造过期
        proc = subprocess.run(                                                                      # 子进程拉起
            [sys.executable, "ops/astro_best_cli.py", "oauth", "token"],                            # 只跑取令牌子命令
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,         # 解码与超时
            env={**os.environ,                                                                  # 同上: 非零退出的错误路径同样不许靠环境变量兜 (A6)
                 "HOME": str(tmp_path), "USERPROFILE": str(tmp_path)},                              # 同样隔离 HOME
            cwd=str(self.SKILL_ROOT),                                                               # 工作目录必须是仓根
        )
        assert proc.returncode == 1                                                                 # 必须非零退出: 绝不能把过期凭据交出去
        assert "oauth login" in proc.stderr                                                         # 恢复命令要落在标准错误上

    def test_url_prints_authorize_url(self, tmp_path):
        """oauth url 子命令打印的授权 URL 要指向官方端点并带上注入的 client_id。"""
        # os: 注入测试用 client_id 环境变量 (不触碰真实凭据); subprocess: 起 CLI 子进程; sys: 解释器路径
        import os
        import subprocess
        import sys

        # 通过环境变量注入测试用 client_id, 不触碰真实凭据
        proc = subprocess.run(                                                                      # 子进程拉起
            [sys.executable, "ops/astro_best_cli.py", "oauth", "url"],                              # 只跑授权 URL 子命令
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,         # 解码与超时
            env={**os.environ,                                                                  # 同上: 授权 URL 含中文参数, 这条专测 CLI 的 URL 出口编码 (A6)
                 "NADC_OAUTH_CLIENT_ID": "test-cid",                                        # 显式给 client id: 不给就没有可断言的 URL
                 "HOME": str(tmp_path), "USERPROFILE": str(tmp_path)},                              # 同样隔离 HOME
            cwd=str(self.SKILL_ROOT),                                                               # 工作目录必须是仓根
        )
        payload = json.loads(proc.stdout)                                                           # 回读 JSON 输出
        assert payload["authorize_url"].startswith("https://oauth.china-vo.org/oauth/authorize")    # 端点必须对: 跳去别的域用户只看到白屏
        assert "client_id=test-cid" in payload["authorize_url"]                             # client id 必须进 URL: 前端直接拼这个链接
