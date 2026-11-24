# -*- coding: utf-8 -*-
"""Phase 4 链路完整性与声明面钉桩 (Q-14/15/16/51/52/54 + import-graph + M14)。

每条修复自带「改坏就红」的定向防线; import-graph 测试守护 protocol 公开符号
必须有生产引用 (Q-09); M14 (Retry total=3->99) 由 test_fixes.py 的单层重试
测试捕获 (Q-11 修复后已真实安装重试层)。
"""
from __future__ import annotations

# 标准库: ast/importlib 自省公开符号 + inspect 判定函数/类 + skill 根锚定
import ast
import importlib
import inspect
import sys
from pathlib import Path

# 第三方: pytest.raises / monkeypatch 承载负路径与环境注入
import pytest

SKILL_DIR = Path(__file__).resolve().parents[3]  # test/unit/meta -> skill 根


class TestQualityGateFailClosed:
    """Q-14: 无指标 fail-closed。

    两条用例成对: 一条钉"缺指标必须拒", 一条钉"有指标必须放" —— 只守前
    一条的话, 一条恒拒绝的门也能全绿, 而那时它挡住的不是坏数据而是一切。
    """

    def test_no_metrics_is_rejected(self):
        """只有坐标、没有任何测光/形态指标的源必须被质量门拒收。

        fail-closed 语义: 缺数据时不允许「默认放行」, 否则下游会把未标定
        源当好源用。
        """
        # 本地: 质量门 (Q-14 fail-closed 守门对象) 与源行模型 (只给坐标不给指标)
        from src.core import QualityGate
        from src.models import BestSource

        qg = QualityGate()                                                                          # 默认质量门
        src = BestSource(source_id="BEST001", ra=180.0, dec=30.0)                                   # 只有坐标的源: 一个指标都不给
        report = qg.validate_source(src)                                                            # 走真实的校验入口
        assert report["passed"] is False  # 必须判 False: 缺指标时默认放行, 下游会把未标定源当好源
        assert any(c["check"] == "no_metrics" for c in report["checks"])               # 必须点名 no_metrics 这条: 无差别拒一切也能过上面那条

    def test_real_metrics_still_pass(self):
        """带真实星等与 class_star 的源必须照常通过 (门不能把好数据也误杀)。"""
        # 本地: 同一对门/模型, 但这次喂真实星等与 class_star (反向守门)
        from src.core import QualityGate
        from src.models import BestSource

        qg = QualityGate()                                                                          # 默认质量门
        src = BestSource.from_row(                                                                  # 从裸行构造带指标的源
            {"ps1_source_id": "B1", "ps1_ra": "180.0", "ps1_dec": "30.0",                           # 标识列与坐标
             "ps1_gmag": "18.2", "ps1_class_star": "0.99"},                                         # 星等与恒星分类概率
            catalog="ps1",                                                                          # 星表名
        )
        report = qg.validate_source(src)                                                            # 走真实的校验入口
        assert report["passed"] is True, report  # 带真指标必须放行, 挡住把门写成恒拒绝的实现


class TestConfigPassthrough:
    """Q-15/56: AstroBestPipeline 配置全量透传。

    透传必须一路验到 requests 的 session adapter: 停在 pipeline 属性上的
    断言只能证明"值被存起来了", 证明不了它最终被用在了发请求的那一层。
    """

    def test_pipeline_passes_full_config(self):
        """pipeline 构造时传入的每一项配置都必须原样到达底层 client。

        断到 adapter 的 ``max_retries.total`` 是为了证明重试策略真的被装进
        session, 而不是只存进了某个属性 (后者 mock __init__ 即可造假)。
        """
        # 本地: 被测 pipeline + 配置对象 (Q-15/56 配置全量透传的接线)
        from src.core.pipeline import AstroBestPipeline
        from src.scripts.config import AstroBestConfig

        cfg = AstroBestConfig(                                                                      # 配置对象: 五个键都要能透传
            base_url="https://mock.example.com/best",                                               # 基址: 端点配置漂移会让所有请求打到别处
            rate_limit=1.5, timeout=99, max_retries=7, api_token="tok",                             # 限流间隔
        )
        pipeline = AstroBestPipeline(cfg)  # 配置只经这一处注入, 后面逐项断的是透传链而非构造参数
        client = pipeline.client.client  # 下钻两层到真 client: 停在 pipeline 属性上只能证明值被存了
        assert client.base_url == "https://mock.example.com/best"                                   # 基址必须原样透传
        assert client.rate_limit == 1.5                                                             # 限流必须原样透传
        assert client.timeout == 99                                                                 # 超时必须原样透传
        assert client.session.get_adapter("https://x").max_retries.total == 7  # 断到 adapter: 证明重试真被装进 session 而非只存在属性上

    def test_pipeline_defaults_when_config_absent(self):
        """不传配置时必须落到权威默认端点 (nadc.china-vo.org), 不是空串/占位。"""
        # src.core.pipeline: 五状态机管线 (INTAKE→…→EMIT)
        # 本地: 不传配置的 pipeline, 验默认端点不是空串/占位
        from src.core.pipeline import AstroBestPipeline

        pipeline = AstroBestPipeline()                                                              # 默认管线
        assert pipeline.client.client.base_url.startswith("https://nadc.china-vo.org")         # 默认基址必须指向真实站点: 漂了就是拿假端点跑全仓


class TestEnvSSOT:
    """Q-16: .env.example 声明的每个键都必须被配置层消费。

    双向对齐是这个门禁的全部意义: 示例里有而代码不读, 是文档在教用户设一个
    完全不起作用的环境变量; 代码读而示例里没有, 则用户根本不知道有这扇门。
    """

    def test_env_example_keys_are_consumable(self, monkeypatch):
        """``.env.example`` 与配置层必须双向对齐 (SSOT)。

        示例文件里出现一个没人读的键 = 文档撒谎; probes 表逐个把环境变量
        注入并断言它真的生效到 AstroBestConfig 对应属性。
        """
        # 本地: 配置层 — env 键的消费端 (Q-16 .env.example SSOT 对齐)
        from src.scripts.config import AstroBestConfig

        env_example = (SKILL_DIR / ".env.example").read_text(encoding="utf-8")  # 读仓库内示例文件本身, 不另造一份键表来自证自洽
        keys = {  # 从示例文件现场解析键表: 文档改了就红, 不靠硬编码副本
            ln.split("=")[0].strip()  # 集合推导逐行取等号左侧, 注释行与空行先被滤掉
            for ln in env_example.splitlines()                                                      # 逐行扫环境样例文件
            if ln.strip() and not ln.startswith("#") and "=" in ln                                  # 只看有效赋值行: 注释与空行不参与
        }
        probes = {  # 探针表把每个键映射到目标属性与探针值, 逐个注入后现造配置
            "BEST_BASE_URL": ("base_url", "https://probe.example/best"),
            "BEST_RATE_LIMIT": ("rate_limit", 4.0),
            "BEST_MAX_RETRIES": ("max_retries", 9),
            "BEST_TIMEOUT": ("timeout", 33),
            "BEST_DOWNLOAD_DIR": ("output_dir", "probe_dir"),
            "BEST_MIN_SNR": ("min_snr", 7.5),
            "BEST_MAX_FWHM": ("max_fwhm", 2.5),
            "BEST_QUALITY_FILTER": ("quality_filter", False),
            # Phase 6: NADC OAuth 身份层 env (src.auth 消费)
            "NADC_OAUTH_CLIENT_ID": ("__oauth_client_id__", "cid-probe"),
            "NADC_OAUTH_CLIENT_SECRET": ("__oauth_client_secret__", "sec-probe"),
            "NADC_OAUTH_REDIRECT_URI": ("__oauth_redirect__", "http://127.0.0.1:9999/cb"),
        }
        # 无探针的键分三类, 三类都**不是**"没人消费", 故按类列开而不是笼统豁免:
        #   (a) BEST_API_USER / BEST_API_PASS: 已退役, 全仓零消费方 (登记见
        #       test_dead_channel_claims.py::RETIRED_CHANNELS);
        #   (b) BEST_API_TOKEN / ASTRO_BEST_PASSWORD: 仍在被代码读取, 只是本用例探的
        #       是 AstroBestConfig 的 dataclass 属性, 而这两个键都不落该 dataclass ——
        #       前者只覆盖 api_token 这一个非凭据字段, 后者由 CLI 的
        #       src.__main__._resolve_password 消费 (CLI 层, 刻意不进配置对象)。
        #       ASTRO_BEST_PASSWORD 的"必须登记在 .env.example"由
        #       test_dead_channel_claims.py::TestEnvSsotCoversRealCredentialSurface
        #       从代码现场扫出来对账 (该件才是凭据面的双向门禁)。
        #   (c) 2026-10-05 (V1 修 E5 P1-01) 补入的 14 个键: 此前 .env.example 漏登记,
        #       现已登记, 但它们的消费方**不在** AstroBestConfig 这个 dataclass 上 ——
        #       TAP 端点 (src/tap/client.py)、TAP 网关配额 (src/tap/service.py, 经
        #       _env_int 形参流入)、数据根 (src/scripts/guards.py) 各自独立读 env。
        #       本用例的探针只覆盖配置层, 覆盖不到那三层; 那三层的"必须登记"双向门禁是
        #       test_env_ssot_covers_all_code_reads.py (全仓 AST 扫描面)。
        #       (原第 4 层「魔塔云调度」已于 2026-10-06 连同组件整体移除, 三键同步
        #        从 .env.example 与本表删除 — 留着就成了"样例里有而代码没有"的空挂。)
        #   (d) 2026-10-06 (P0-18) 新增 ASTRO_BEST_STALE_RUNNING_SEC: 崩溃遗留作业的
        #       接管阀值, 消费方是 src/download_manager.py::_stale_running_sec(),
        #       不在 AstroBestConfig 上 —— 与 (c) 同类, 故同列本表而非探针表。
        non_config_keys = (
            "BEST_API_USER", "BEST_API_PASS", "BEST_API_TOKEN", "ASTRO_BEST_PASSWORD",
            "ASTRO_BEST_DATA_ROOT", "ASTRO_BEST_STALE_RUNNING_SEC",
            "BEST_TAP_URL", "BEST_LOCAL_TAP_URL",
            "BEST_TAP_ANON_MAXREC", "BEST_TAP_AUTH_MAXREC",
            "BEST_TAP_MAX_QUERY_CHARS", "BEST_TAP_MAX_BODY_BYTES",
            "BEST_TAP_ANON_CONCURRENCY", "BEST_TAP_AUTH_CONCURRENCY",
            "BEST_TAP_ANON_PENDING", "BEST_TAP_AUTH_PENDING",
        )
        missing = [k for k in keys if k not in probes and k not in non_config_keys]  # 未覆盖的键: 样例里写了而代码没有, 就是文档在骗人
        assert not missing, f".env.example 有未被配置层消费的键: {missing}"  # 示例里有而配置层不读的键即撒谎, 报错要带上具体键名
        # OAuth env 必须被 src.auth 识别 (常量名稳定)
        # 本地: Phase 6 身份层的 env 常量名 (改名即断 OAuth 接线)
        from src.auth import ENV_CLIENT_ID, ENV_CLIENT_SECRET, ENV_REDIRECT_URI

        assert (ENV_CLIENT_ID, ENV_CLIENT_SECRET, ENV_REDIRECT_URI) == (  # 常量名是 OAuth 接线的锚: 改一个名就断掉整条身份链
            "NADC_OAUTH_CLIENT_ID", "NADC_OAUTH_CLIENT_SECRET", "NADC_OAUTH_REDIRECT_URI")          # 三个 OAuth 环境变量名
        for env_key, (attr, value) in probes.items():  # 逐键注入再实例化, 单键生效证明不了多键共存不互相覆盖
            if attr.startswith("__"):                                                             # 双下划线开头的属性跳过: 内部状态不对外承诺
                # __oauth_*__ 是哨兵属性: 由下面 src.auth 常量断言单独覆盖
                continue
            # monkeypatch: 已存在的变量必须能被还原 —— ``del os.environ[key]``
            # 会永久删掉它, 把删除泄漏给后续测试
            monkeypatch.setenv(env_key, str(value))  # 逐键还原, 保证注入的探针值不串到下一个键上
            cfg = AstroBestConfig()  # 每次现造配置对象, 复用同一个实例会让覆盖写假象
            assert getattr(cfg, attr) == value, f"{env_key} 未生效到 {attr}"  # 属性必须等于探针值, 只断非空会让恒默认值蒙混过关

    def test_retired_log_level_stays_retired(self):
        """AH3-08: BEST_LOG_LEVEL 已退役 —— 三个声明面都不得再出现它。

        为什么钉退役而不钉"生效": 实测该键**零消费方** (全仓 0 读取点, 且本仓
        零 basicConfig/setLevel, 无处装 handler)。留着它就是 ``.env.example``
        在教用户设一个不起作用的开关。

        三面同断的原因: 只摘 ``.env.example`` 会让 ``verify_crossrefs`` §7 的
        双向对账判红 (代码 env_map 仍读它而样例里没有); 只摘 dataclass 字段会
        让 ``TestTemplateDefaults`` 判红 (模板 defaults 出现白名单外的键)。
        三者必须同时退役 —— 这也正是本条用例存在的意义。
        """
        # 本地: 配置层权威定义 (dataclass 字段集)
        from dataclasses import fields

        from src.scripts.config import AstroBestConfig

        env_example = (SKILL_DIR / ".env.example").read_text(encoding="utf-8")  # 读真文件: 判据不靠硬编码副本
        declared = {ln.split("=")[0].strip() for ln in env_example.splitlines()  # 现场解析键表
                    if ln.strip() and not ln.startswith("#") and "=" in ln}
        assert "BEST_LOG_LEVEL" not in declared, "BEST_LOG_LEVEL 已退役, 不得重新登记进 .env.example"

        field_names = {f.name for f in fields(AstroBestConfig)}  # 反射真实字段集: 写死副本会随字段漂移
        assert "log_level" not in field_names, "log_level 字段已退役 (无消费方), 不得重新加回"

        # 退役键不许从另一扇门回来: dataclass 字段被拿掉后, env_map 里若还留着该
        # 键, setattr 会凭空造出同名属性, 于是"退役"只做了一半
        probe = AstroBestConfig()  # 零参数构造: 只想看它有没有被 env_map 塞出属性
        assert not hasattr(probe, "log_level"), "env_map 里仍残留 BEST_LOG_LEVEL -> log_level 的映射"
        # 对照组: quality_filter **不**在退役名单里 (消费方在 src/core/pipeline.py),
        # 上面这条退役判据不得把它一起带走
        assert "quality_filter" in field_names, "quality_filter 有真消费方 (pipeline -> cone_search), 不得随 log_level 一起退役"

        # 模板 defaults 同属声明面: 键留在那里只会被 from_yaml 白名单 WARN 丢弃
        import yaml

        tpl = yaml.safe_load((SKILL_DIR / "templates" / "best-config.yaml").read_text(encoding="utf-8"))
        assert "log_level" not in tpl.get("defaults", {}), "best-config.yaml 的 defaults 里 log_level 已退役"


class TestInputValidation:
    """Q-51: 入口入参校验接线。

    校验必须落在入口而不是交给服务端: 非法坐标发出去要么换一个语义完全
    不同的天区, 要么让整次查询白跑一趟, 两种都不会在结果里留下痕迹。
    """

    def test_cone_search_rejects_bad_coordinates(self):
        """ra=-10° 越界必须在入口被拒, 不得带着非法坐标发请求。

        载荷取 -10 而不是 370: 后者虽然在数学上等价, 但它暴露的是另一类
        问题 (角度归一化), 混进来会让"越界被拒"这条判据失去指向性。
        """
        # 本地: 客户端入口 (Q-51 入参校验的落点)
        from src.client import BestClient

        client = BestClient(rate_limit=0)  # rate_limit 归零避免礼貌限流拖慢用例, 离线桩不需要节流
        with pytest.raises(ValueError):  # 入口拒绝而非服务端报错: 非法坐标发出去会白跑一趟查询
            client.cone_search(ra=-10.0, dec=30.0, radius_arcsec=60.0)                              # 负赤经必须被拒: 落到别的天区去查

    def test_cone_search_rejects_zero_radius(self):
        """radius=0 会被服务端当成无限查询, 入口必须 fail-closed。

        0 与负数要分开守: 负数一眼就是非法值, 而 0 在很多 API 里是合法语义
        (不限范围), 恰恰因此会一路放行并拖回整张表。
        """
        # 本地: 同一客户端入口, 这次钉 radius=0 的 fail-closed
        from src.client import BestClient

        client = BestClient(rate_limit=0)  # 零半径在很多 API 里是合法语义, 恰恰因此会一路放行
        with pytest.raises(ValueError):                                                             # 零半径必须被拒
            client.cone_search(ra=180.0, dec=30.0, radius_arcsec=0.0)                               # 半径为零的锥形查询没有意义

    def test_public_cone_search_validates(self):
        """公开脚本入口 (best_cone_search.cone_search) 必须共享同一套校验。"""
        # 本地: 公开脚本入口 (不得自带一套宽松校验)
        from src.scripts.best_cone_search import cone_search

        with pytest.raises(ValueError):  # 公开入口必须共享同一套校验, 不得自带一套宽松实现
            cone_search(ra=-10.0, dec=30.0, radius_arcsec=60.0)                                     # 越界经度必须被拒

    def test_public_cone_search_shares_client(self):
        """Q-18: 公开入口默认复用模块级 client (不每次新建泄漏 session)。"""
        # 本地: 摸模块级 _shared_client 单例, 验复用而非每次新建
        from src.scripts import best_cone_search as mod

        c1 = mod._shared_client()  # 两次取同一单例, 新建即每次泄漏一个 session
        c2 = mod._shared_client()                                                               # 共享客户端必须复用: 新建就意味着限流时钟被重置
        assert c1 is c2                                                                             # 两次取到同一个对象


class TestTruncateDoesNotTamper:
    """Q-52: truncate 不得改写源记录。

    截断是为了控制 token 预算, 一旦顺手把源历史也削掉, 这次省下的代价就是
    后面再也拿不回全量, 而用户并不会知道自己已经永久丢了数据。
    """

    def test_truncate_returns_view_and_keeps_truth(self):
        """truncate 只返回受控视图, 源历史与 summary 的真实总数必须保持。"""
        # 本地: 查询上下文 (Q-52 truncate 不得改写源记录)
        from src.scripts.context import QueryContext

        ctx = QueryContext()                                                                        # 查询上下文
        ctx.record("cone", {"ra": 180.0}, 80)  # 第一条记 80 条, 与下一条相加得 140 才好判覆盖写
        ctx.record("download", {"ra": 181.0}, 60)  # 第二条记 60 条, 两条不同值才能抓住后写覆盖前写
        view = ctx.truncate(max_records=10)                                                         # 按展示预算取视图
        assert sum(h["n_results"] for h in view) <= 10  # 视图内计数不得超过阈值, 超过说明裁剪没生效或改写了源
        # 源记录与 summary 保持真实总数
        assert ctx.summary()["total_results"] == 140  # summary 仍报真实总数 140, 被就地削成 10 即为半修
        assert ctx.history[0]["n_results"] == 80  # 首条历史原样保留, 源记录被改时这条与 summary 同时红


class TestChecksumWiring:
    """Q-54: 下载链路校验和接线。

    校验和的两种失效都不体面: 不校验会静默写坏文件, 而校验写成恒失败则让
    整条下载链路不可用 —— 所以负路径与正路径必须成对存在。
    """

    def test_checksum_mismatch_raises(self, tmp_path):
        """期望 sha256 不符时必须抛 ValueError, 不允许静默写坏文件。

        期望值取 64 个 0: 长度合法、形态合法, 只在内容上必然对不上, 这样
        抛错才来自比对本身而不是来自参数格式检查。
        """
        # 标准库: hashlib 仅用于构造"错误"的期望 sha256 (Q-54 负路径)
        import hashlib

        # 本地: 客户端 (仅构造, 不发请求) + 落盘器 (被测) + 查询结果/源模型
        from src.client import BestClient
        from src.downloader import BestDownloader
        from src.models import BestQueryResult, BestSource

        dl = BestDownloader(client=BestClient(rate_limit=0), output_dir=str(tmp_path))  # 落盘器只被构造不发网络请求, 期望值错配由它自己抛
        result = BestQueryResult(                                                                   # 成功标志
            success=True, total_count=1, returned_count=1,                                          # 总数与返回数
            sources=[BestSource.from_row({"ps1_source_id": "B1", "ps1_ra": "180.0"}, catalog="ps1")],  # 单源
        )
        wrong = "0" * 64  # 64 个 0 长度合法形态合法, 抛错只能来自比对而非格式检查
        with pytest.raises(ValueError, match="checksum mismatch"):  # 匹配错误文案而非异常类型, 便于排障时一眼认出是校验失败
            dl._save_result(result, "out.json", "json", expected_sha256=wrong)                # 错误校验和必须被拒: 静默忽略等于完整性防线形同虚设

    def test_checksum_match_accepts(self, tmp_path):
        """带正确期望值的落盘必须成功 (接线不能把好文件也拒掉)。

        期望值由同一次落盘的产物现算, 而不写死一个字面量: 只有这样才是
        "与实际内容一致"的真阳性, 写死的哈希一旦落盘格式微调就会变成另一
        条假阴性的负路径, 把问题引向错误的方向。
        """
        # 标准库: 先落盘算真实 sha256, 再带正确期望值重写 (正向守门)
        import hashlib

        # 本地: 与负路径同一组依赖, 验证正确期望值不被误拒
        from src.client import BestClient
        from src.downloader import BestDownloader
        from src.models import BestQueryResult, BestSource

        dl = BestDownloader(client=BestClient(rate_limit=0), output_dir=str(tmp_path))  # 正负两条共用同一组依赖, 差别只在期望值对不对
        result = BestQueryResult(                                                                   # 成功标志
            success=True, total_count=1, returned_count=1,                                          # 总数与返回数
            sources=[BestSource.from_row({"ps1_source_id": "B1", "ps1_ra": "180.0"}, catalog="ps1")],  # 单源
        )
        # 先写一次算真实 sha256, 再带正确期望值重写
        path = dl._save_result(result, "out.json", "json")                                          # 先落一次拿到真校验和
        expected = hashlib.sha256(Path(path).read_bytes()).hexdigest()                              # 自己算一遍校验和: 不能只信工具给的
        path2 = dl._save_result(result, "out.json", "json", expected_sha256=expected)               # 拿真校验和再落一次
        assert Path(path2).is_file()                                                                # 产物必须在: 校验通过不等于没落盘


class TestImportGraph:
    """Q-09: protocol 公开符号必须有生产引用 (死代码守护)。

    协议层是所有数据入口的收口, 它的公开面一旦被弃用而不删, 后来者就会
    照着死符号接线, 于是错误被固化在新的调用点上。
    """

    def test_protocol_public_symbols_have_production_reference(self):
        """protocol 的公开函数/类必须在 src/ + ops/ 里有真实生产引用。

        文本级 (非 AST 级) 扫描是有意的宽松口径: 只抓「彻底没人提过」的死
        符号; 解析器类 (parse_csv_rows/build_query_form) 是 Phase 3/4 接线
        的权威入口, 单独钉死, 防止回归成死代码。
        """
        proto = importlib.import_module("src.protocol")  # import 真实协议模块, 反射出的公开面才是被守护的那一份
        src_texts = []                                                                            # 源文本收集: 公开符号的生产引用只能从这里数
        for py in (SKILL_DIR / "src").rglob("*.py"):                                                # 递归扫源目录
            if py.name == "protocol.py":                                                          # 协议层自身要排除: 自己引用自己不算生产引用
                continue
            src_texts.append(py.read_text(encoding="utf-8"))                                        # 收进语料
        ops_texts = []                                                                             # 运维侧也要算: 门禁脚本同样会引用协议符号
        for py in (SKILL_DIR / "ops").rglob("*.py"):                                                # 递归扫运维目录
            ops_texts.append(py.read_text(encoding="utf-8"))                                        # 收进语料
        all_text = "\n".join(src_texts + ops_texts)                                                 # 两份语料拼成一整段: 只扫一侧会误报

        public = [                                                                                  # 公开符号候选
            name for name, obj in vars(proto).items()                                               # 遍历协议层命名空间
            if not name.startswith("_") and (inspect.isfunction(obj) or inspect.isclass(obj))       # 只收函数与类
            and getattr(obj, "__module__", "") == "src.protocol"
        ]
        unreferenced = [n for n in public if n not in all_text]                             # 清点零引用公开符号: 有生产零引用就说明导出面与实现脱节
        # parse_csv_rows/parse_count 等权威解析器必须被接线 (Phase 3/4 已接)
        assert "parse_csv_rows" not in unreferenced  # 权威解析器必须被接线: 它是 Phase 3/4 数据入口的收口
        assert "build_query_form" not in unreferenced  # 表单构造同理, 死了就意味着约束查询走不通
        # 其余未引用符号列出来供人工裁决 (不强制为 0, 防误删公开 API 面)
        if unreferenced:                                                                            # 有零引用即报, 空集是正常结果
            print(f"[import-graph] 未在生产代码引用的 protocol 公开符号: {unreferenced}")


class TestRetryConfiguration:
    """M14 防线: urllib3 Retry 配置必须真实安装且可钉 (mock __init__ 的写法会让缺陷存活)。"""

    def test_adapter_retry_total_is_three(self):
        """默认重试总次数与 status_forcelist 必须如实装在 session adapter 上。

        断言打在真实 adapter 对象上而非构造参数 —— mock 掉 ``__init__``
        会让「配置了但没装上」的缺陷存活。
        """
        # 本地: 客户端 (M14 防线 — 重试配置必须真装在 adapter 对象上)
        from src.client import BestClient

        client = BestClient(rate_limit=0)                                                 # 建客户端只为拿到字段面, 零限速免得测试被 sleep 拖住
        adapter = client.session.get_adapter("https://nadc.china-vo.org/data/best")  # 按真实 URL 取 adapter, 避免落到别的挂载点而假通过
        retry = adapter.max_retries  # 重试配置挂在 adapter 上, 直接取它避免经 client 属性中转
        assert retry.total == 3, retry.total  # 总次数必须是 3, 只配了不装上的缺陷在这里现形
        assert 429 in retry.status_forcelist  # 429 与 503 都得重试, 少一个就让限流直接透给调用方
        assert 503 in retry.status_forcelist

    def test_max_retries_param_honored(self):
        """调用方显式传入的 max_retries 必须覆盖默认值 (不硬编码 3)。

        载荷 7 与默认值 3 差得足够远: 取一个恰好等于或接近默认值的数, 一条
        "读都没读参数、直接用默认值"的实现也能混过去。
        """
        # 本地: 客户端 (显式 max_retries=7 必须覆盖默认 3)
        from src.client import BestClient

        client = BestClient(rate_limit=0, max_retries=7)  # 显式 7 覆盖默认 3: 两者差得够远才抓得住读都没读的实现
        adapter = client.session.get_adapter("https://nadc.china-vo.org/data/best")
        assert adapter.max_retries.total == 7  # 断的是覆盖生效, 参数被忽略时这里仍是默认 3


class TestTemplateDefaults:
    """Q-31: best-config 可消费键必须落在 defaults 映射内, 且取值对齐代码缺省。"""

    def test_consumable_keys_inside_defaults(self):
        """模板 defaults 里的键必须是 AstroBestConfig 真实字段的子集。

        防止模板声明一个配置层根本不认识的键 (用户照着改却毫无效果),
        同时钉住模板取值与 dataclass 缺省逐项一致 (H2-04)。
        """
        # 标准库: 反射 AstroBestConfig 的字段名, 供模板键做子集比对
        from dataclasses import fields

        # 第三方: 解析 best-config.yaml 模板的 defaults 映射
        import yaml

        # 本地: 配置层权威字段集 (Q-31 模板键必须是它的子集)
        from src.scripts.config import AstroBestConfig

        tpl = yaml.safe_load((SKILL_DIR / "templates" / "best-config.yaml").read_text(encoding="utf-8"))
        defaults = tpl.get("defaults", {})
        known = {f.name for f in fields(AstroBestConfig)}                                           # 配置类的真实字段集
        consumable = set(defaults) & known                                                          # 能落到默认值的字段才算可消费
        assert "base_url" in consumable, defaults
        assert "timeout" in consumable, defaults
        assert "min_snr" in consumable, defaults
        # H2-04: 集外键会被 from_yaml 静默 WARN 丢弃, 用户改了不起作用, 必须保持为空
        assert not (set(defaults) - known), f"defaults 有非白名单键 (from_yaml 只 WARN 丢弃): {sorted(set(defaults) - known)}"  # 键漂回去即红
        cfg = AstroBestConfig.from_yaml(str(SKILL_DIR / "templates" / "best-config.yaml"))         # 走真实加载路径: 模板值真的落到配置对象上
        code_cfg = AstroBestConfig()                                                                # 零参数构造 = dataclass 缺省 (env 覆盖两侧同时生效, 不干扰相等判定)
        drift = {f.name: (getattr(cfg, f.name), getattr(code_cfg, f.name))                         # 逐字段对账: 模板给了什么 vs 代码缺省是什么
                 for f in fields(AstroBestConfig) if getattr(cfg, f.name) != getattr(code_cfg, f.name)}
        assert not drift, f"模板 defaults 与 dataclass 缺省漂移 (旧版 timeout 60/rate_limit 1.0/output_dir './best_data'): {drift}"  # 漂移即红: 限流减半与超时砍半都从这里来
        # 类型也要对: env 路径会按字段缺省类型转型, YAML 路径不会, 写成 "120" 字符串能过相等判定却会在下游炸
        assert type(cfg.timeout) is int and type(cfg.rate_limit) is float, (cfg.timeout, cfg.rate_limit)  # int/float 各归其位
