"""发布回归测试: 钉住 CLI 参数解析、四种格式导出、sqlid 路由与禁版本号铁律。

每条用例都对应一次"改坏就红"的历史教训: --catalog/--format 写在子命令后必须
仍被接受; txt 导出必须是制表符分隔而非 JSON; csv/votable 导出不得丢原始星表
字段; download_sqlid 必须把旧拼写 gaia_dr3 路由到服务端真实路径 gaia_dr3_18/q
(直送 gaia_dr3/q 会被服务端以 {"error":"Not Found"} 拒绝)。全部离线。
"""
from __future__ import annotations

# 标准库: csv 读回落盘结果做字段级断言; math 备于数值比较; re 扫禁版本号字段;
# pathlib 做临时目录/仓库根路径锚定; unittest.mock.patch 替身 HTTP 与内部方法。
import csv  # 读回落盘 CSV 做字段级断言: 列名即契约
import math
import re  # 扫禁版本号铁律: 只认顶层 version 键
from pathlib import Path
from unittest.mock import patch  # 桩掉第二阶段 GET, 好抓真实 catalog_path

# 第三方: pytest 提供断言/夹具/依赖缺失跳过机制
import pytest  # importorskip/approx/夹具都靠它

# 导入失败即整文件跳过, 不让环境问题伪装成用例失败
try:
    # src 包: 被测生产代码树
    import src
except Exception as _legacy_err:  # legacy-import-guard
    # 回退导入 pytest 只为发出模块级 skip; 原因必须可读, 不能红一片
    import pytest as _pytest  # 回退导入只为了发 skip
    _pytest.skip(f'legacy import unavailable: {_legacy_err!r}', allow_module_level=True)  # 模块级 skip
# 本地: CLI 解析器与结果呈现/落盘函数 — 被测对象 (权威实现在 src.__main__)
from src.__main__ import _print_or_save, _resolve_password, build_parser  # 被测三件套: 解析/落盘/口令解析

# 本地: 两阶段 REST 客户端 — rate_limit=0 构造仅为离线导出/解析, 不发请求
from src.client import BestClient  # 构造不发请求, 只借它的会话与路由表

# 本地: 下载器 — csv/txt/json/votable 四种 emitter 的权威实现
from src.downloader import BestDownloader  # 四种 emitter 的权威实现, 导出全走它

# 本地: 领域模型 — BestQueryResult 结果信封 + BestSource 单源 (含 raw_data 全字段)
from src.models import BestQueryResult, BestSource  # 导出链路的输入模型


def _raw_source() -> BestSource:
    """构造一颗带全字段原始行的 ps1 源 (导出回归的基准数据)。

    刻意选用 ebv/ruwe/rflags/rpsf_corr 四个易丢字段: 导出链路
     任何"只挑已知列"的投影都会在此丢字段变红。
    """
    return BestSource.from_row(  # 基准行: 那四个易丢字段决定这条用例的证明力
        {
            "ps1_source_id": "123456789",  # 溯源主键
            "ps1_ra": "180.25",  # 坐标: 导出必须原样保真
            "ps1_dec": "30.5",
            "ps1_ebv": "0.031",  # 易丢字段 1/4: 质量指标
            "ps1_ruwe": "1.04",  # 易丢字段 2/4: 质量指标
            "ps1_rflags": "GOOD",  # 易丢字段 3/4: 字符串型标志
            "ps1_rpsf_corr": "15.102",  # 易丢字段 4/4: 校正后星等
        },
        catalog="ps1",  # 星表 id 决定前缀剥离规则
    )


def test_cli_accepts_catalog_and_format_after_subcommand():
    """--catalog/--format 写在子命令之后也必须被解析 (共享父解析器契约)。

     argparse 默认只接受子命令之后的选项; 修复前 cone --catalog gaia_dr3
     会直接报 unrecognized arguments。守的是 CLI 调用姿势不被回归破坏。
    """
    args = build_parser().parse_args(  # 选项写在子命令之后
        [
            "cone",
            "--ra",
            "180",
            "--dec",
            "30",
            "--catalog",
            "gaia_dr3",  # 旧拼写, 解析层不做路由
            "--format",
            "txt",  # 输出格式与 --catalog 同样须被接受
        ]
    )
    assert args.catalog == "gaia_dr3"  # 共享父解析器契约
    assert args.format == "txt"


def test_cli_txt_export_is_tab_delimited_not_json(tmp_path, monkeypatch):
    """txt 格式必须落盘为制表符分隔表, 而不是 JSON 文本。

    守导出格式回归: format=txt 若误走 JSON emitter, 文件会以 "{" 开头且无
    制表符 — 下游 Excel/TOPCAT 按列解析即烂。另注意实际落盘后缀是 .tsv
    (txt 形态的真实容器), 断言读的是 result.tsv。P1-6: --output 锚定数据根,
    测试经 ASTRO_BEST_DATA_ROOT 把数据根指到 tmp_path。
    """
    monkeypatch.setenv("ASTRO_BEST_DATA_ROOT", str(tmp_path))  # 数据根锚到临时目录
    result = BestQueryResult(success=True, sources=[_raw_source()], total_count=1)  # 单源信封
    target = tmp_path / "result.txt"  # 调用方要的路径
    actual = tmp_path / "result.tsv"  # txt 形态的真实容器是 .tsv

    _print_or_save(result, "txt", str(target))  # 走 CLI 落盘分支

    # 读回落盘文件 (本地 IO): 验证字节级格式而非内存对象
    content = actual.read_text(encoding="utf-8")  # 读真实文件, 不看内存对象
    assert "\t" in content  # 制表符分隔才可被按列解析
    assert not content.lstrip().startswith("{")  # 误走 JSON emitter 就会挂这条
    assert "ps1_ebv" in content  # 易丢字段也必须在


def test_csv_export_preserves_all_raw_catalog_fields(tmp_path):
    """csv 导出必须保留星表全部原始字段 (含 ebv/ruwe/rflags 等非投影列)。

    守"导出不挑列"回归: _save_result 若按已知列白名单写盘, 站点新增列会
    静默消失; 这里用全字段基准行钉死透传语义。
    """
    result = BestQueryResult(success=True, sources=[_raw_source()], total_count=1)  # 单源信封
    path = BestDownloader(BestClient(rate_limit=0), str(tmp_path))._save_result(  # 直接调内部落盘函数
        result, "full.csv", "csv"  # 导出格式与目标文件名
    )  # rate_limit=0: 构造不发请求, 纯离线

    # 以 DictReader 读回 (本地 IO): 列名即契约, 缺列会 KeyError 变红
    with open(path, newline="", encoding="utf-8") as handle:  # newline="" 是 csv 模块硬要求
        row = next(csv.DictReader(handle))  # 只取第一行
    assert row["ps1_ebv"] == "0.031"  # 易丢字段 1/4
    assert row["ps1_ruwe"] == "1.04"  # 易丢字段 2/4
    assert row["ps1_rflags"] == "GOOD"  # 字符串型标志不许被转成数值
    assert row["ps1_rpsf_corr"] == "15.102"  # 易丢字段 4/4


def test_votable_export_preserves_raw_fields_and_types(tmp_path):
    """votable 导出必须保留原始字段且数值列保持数值类型 (非全字符串)。

    守 VOTable 类型回归: astropy 解析后 ps1_ebv 须可转 float、rflags 保持
    字符串; 类型塌缩成 str 会让下游科学工具按文本处理数值。
    """
    # astropy 缺失时跳过 (votable 断言依赖它; 不因可选依赖拖垮整文件)
    astropy = pytest.importorskip("astropy")  # 可选依赖缺失就跳, 不拖垮整文件
    # 第三方: astropy.io.votable.parse_single_table — 读回落盘 VOTable 做列类型断言
    from astropy.io.votable import parse_single_table  # 延迟导入: 可选依赖缺失才跳过

    result = BestQueryResult(success=True, sources=[_raw_source()], total_count=1)  # 单源信封
    path = BestDownloader(BestClient(rate_limit=0), str(tmp_path))._save_result(  # 走同一落盘函数
        result, "full.xml", "votable"  # VOTable emitter + xml 后缀
    )  # 离线: 客户端不发请求
    # 读回并解析 VOTable (本地 IO): 类型信息只在落盘文件里可验证
    table = parse_single_table(path).to_table()  # 转成 astropy Table 才能看列类型

    assert float(table["ps1_ebv"][0]) == pytest.approx(0.031)  # 数值列必须可转 float
    assert table["ps1_rflags"][0] == "GOOD"  # 字符串列不许塌缩
    assert table["ps1_source_id"][0] == "123456789"  # 溯源主键原样


def test_download_sqlid_uses_selected_catalog(tmp_path):  # 旧别名归位的路由回归
    """download_sqlid 必须按所选星表走真实服务端路由 (旧别名 gaia_dr3 归位)。

    守路由回归: gaia_dr3 是旧拼写, 权威路由表里它必须映射到 gaia_dr3_18/q;
    若直送 gaia_dr3/q, 服务端以 {"error":"Not Found"} 拒绝 (软 404)。
    """
    client = BestClient(rate_limit=0)  # 离线: 构造不发请求
    downloader = BestDownloader(client, str(tmp_path))  # 落盘目录锚到临时路径
    result = BestQueryResult(                                                                       # 手工造结果信封: 覆盖各类失败形态
        success=True,  # 桩子返回的固定结果
        sources=[
            BestSource.from_row(
                {
                    "gaia_dr3_source_id": "42",  # 带旧星表前缀的列
                    "gaia_dr3_ra": "10.5",  # 坐标
                    "gaia_dr3_dec": "-2.0",  # 坐标
                },
                catalog="gaia_dr3",  # 旧拼写: 路由表负责归位
            )
        ],
        total_count=1,  # 计数与行数一致
    )

    # 替身: 桩掉第二阶段 GET (sqlid 数据拉取), 固定返回内存结果,
    # 从而在不联网的前提下捕获 download_sqlid 真实使用的 catalog_path
    with patch.object(client, "_fetch_sqlid_data", return_value=result) as fetch:  # 桩掉第二阶段 GET
        path = downloader.download_sqlid(  # 真走路由表
            "s2623", catalog="gaia_dr3", output_format="csv"  # 旧拼写星表 id
        )  # 输出走 csv emitter

    assert Path(path).exists()  # 落盘成功才算这条路由跑通
    # 旧拼写 gaia_dr3 必须到达真实路由 gaia_dr3_18/q; 直送 gaia_dr3/q 会被
    # 服务端以 {"error":"Not Found"} 拒绝。
    assert fetch.call_args.kwargs["catalog_path"] == "gaia_dr3_18/q"  # 归位到真实路径才算过


def test_release_has_no_version_fields():  # 禁版本号铁律的发布面守门
    """禁版本号铁律 (Phase 0 首覆盖 SKILL.md/manifest.yaml; Phase 1 扩展至 pyproject/pipeline/agents/_version)。"""
    root = Path(__file__).parents[2]  # 上溯两级到仓根
    for name in ("SKILL.md", "manifest.yaml"):  # 铁律覆盖的两个文件
        text = (root / name).read_text(encoding="utf-8")  # 读原文
        assert re.search(r'^version: "', text, re.MULTILINE) is None, f"{name} 残留 version 字段"  # 顶层 version 键


def test_cli_rejects_plaintext_auth_password_argument():
    """E10: --auth-pass 明文口令参数必须被解析器拒绝 (不再有这条 argv 通道)。

    守运维面回归: 口令走命令行参数会原样进 shell history 与 ``ps`` 输出,
    同机任何用户都能回看。重新引入该参数 = 凭据泄漏面回归, 必须在此断红。
    注意认证选项只挂主解析器, 必须写在子命令**之前** (旧 --auth-pass 的合法
    位置就在那里) —— 写在子命令后即便参数存在也会因作用域报错, 证明力不足。
    """
    with pytest.raises(SystemExit):  # argparse 对未知参数直接退出
        build_parser().parse_args(
            ["--auth-user", "someone", "--auth-pass", "not-so-secret",
             "cone", "--ra", "180", "--dec", "30"]  # 明文口令位必须已不存在
        )


def test_cli_auth_user_still_accepted_without_password_argument():
    """E10: --auth-user 必须保留 (口令改走 env/getpass, 不是连用户名一起删)。"""
    args = build_parser().parse_args(  # 用户名位须在子命令之前: 认证选项只挂主解析器
        ["--auth-user", "someone", "cone", "--ra", "180", "--dec", "30"])  # 用户名位仍在
    assert args.auth_user == "someone"  # 用户名保留
    assert not hasattr(args, "auth_pass"), "auth_pass 属性不应再存在于解析结果里"  # 口令位已删


def test_cli_password_resolution_reads_env_not_argv(monkeypatch):
    """E10: 口令解析只认 env; 未给用户名时不读 env 也不提示 (匿名可用)。"""
    monkeypatch.setenv("ASTRO_BEST_PASSWORD", "env-only-secret")  # 只给 env 通道
    assert _resolve_password("someone") == "env-only-secret"  # 有用户名才读 env
    # 用户名为空 = 不登录: 即使 env 有值也不取用, 更不提示
    assert _resolve_password("") == ""  # 匿名路径不碰 env


def test_cli_password_falls_back_to_getpass_on_interactive_tty(monkeypatch):
    """E10: env 缺口令但交互终端在线时, 回落 getpass 隐形读取 (不回显)。"""
    monkeypatch.delenv("ASTRO_BEST_PASSWORD", raising=False)  # 制造 env 缺口令

    class _FakeStdin:
        """替身 stdin: isatty 恒真, 用来模拟交互终端。"""

        @staticmethod
        def isatty():
            """恒为真: 迫使口令解析走 getpass 分支。"""
            return True  # 走 getpass 分支的唯一开关

    monkeypatch.setattr("src.__main__.sys.stdin", _FakeStdin())  # 假装有终端
    monkeypatch.setattr("src.__main__.getpass.getpass",
                        lambda prompt: "typed-secret")  # 隐形输入的替身
    assert _resolve_password("someone") == "typed-secret"  # 回落到 getpass 结果


def test_cli_password_stays_empty_on_non_interactive_no_env(monkeypatch):
    """E10: 非交互且无 env 时必须返回空串 (不卡在口令提示上, 按匿名继续)。"""
    monkeypatch.delenv("ASTRO_BEST_PASSWORD", raising=False)  # 同样制造 env 缺口令

    class _FakeStdin:
        """替身 stdin: isatty 恒假, 用来模拟管道/CI 无人值守场景。"""

        @staticmethod
        def isatty():
            """恒为假: 非交互场景下不得调用 getpass。"""
            return False  # 非交互: 一旦走去 getpass 就是错的

    monkeypatch.setattr("src.__main__.sys.stdin", _FakeStdin())  # 假装在管道里
    monkeypatch.setattr("src.__main__.getpass.getpass",
                        lambda prompt: (_ for _ in ()).throw(  # 一旦被调用即失败
                            AssertionError("非交互场景不得提示口令")))
    assert _resolve_password("someone") == ""  # 空串 = 按匿名继续, 不卡住
