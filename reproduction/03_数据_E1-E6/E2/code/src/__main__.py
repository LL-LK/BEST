"""src.__main__ — astro-best 的命令行界面 (对接真实 BEST 两阶段 API; 仓内没有
    独立的 CLI 模块, 本文件即 ``python -m src`` 的入口)。

能力边界: 包级 CLI 入口 (python -m src): cone/download/crossmatch/catalogs/info/doctor。边界: 只做参数解析与分派; 业务逻辑在 client/best_export/downloader; 凭据走 env/getpass, 零字面量。
白盒锚点: references/ALGORITHM-SPEC.md §3 (超参: rate_limit/max_retries/timeout)。

E10 (运维面): 口令**不再接受** ``--auth-pass`` 明文命令行参数 —— 命令行参数会
原样进入 shell history 与 ``ps`` 输出, 同机任何用户都能回看。口令只从环境变量
``ASTRO_BEST_PASSWORD`` 读入, 交互终端缺失时才用 getpass 隐形读取。
"""
from __future__ import annotations

# 标准库: argparse 做子命令解析, json 做 catalogs/info 等机器可读输出,
# sys 取 Python 版本/平台 (doctor 诊断) 并携带退出码, pathlib 做输出目录锚定;
# getpass 隐形读口令 (E10: 口令不走明文命令行参数), os 只读环境变量
# (凭据/数据根, 代码内零凭据字面量)。
import argparse  # 子命令骨架: 六个子命令的解析树由此生成
import getpass  # 隐形读口令 (E10: 口令不走明文命令行参数)
import json  # catalogs/info 的机器可读输出
import os  # 只读环境变量: 口令与数据根, 代码内零凭据字面量
import sys  # 版本/平台诊断 (doctor) + 承载进程退出码
from pathlib import Path  # 输出目录与 RAG 知识库目录的锚定

# 本地: 认证与两阶段 REST 客户端 — 所有子命令最终都经 BestClient 发起请求;
# BestAuth 仅在调用方显式提供凭据时才构造 (匿名可查星表不因未登录而失败)。
from src.client import BestAuth, BestClient  # 全子命令共用一个客户端: 复用连接与限流器

# 本地: 星表枚举 — catalogs 子命令枚举全部星表 id 与展示名 (数据源即权威)。
from src.models import CatalogType  # 枚举即权威: 新增星表只改 models, CLI 自动跟随

# 本地: .env 加载单点 — 只在 CLI 入口调一次, 不在模块导入期产生副作用。
from src.scripts.config import load_dotenv_file  # 零依赖 dotenv: 让 .env.example 的指令成真 (YZ-57)

# 口令环境变量名: 与 ops/astro_best_cli.py 的 ASTRO_BEST_DATA_ROOT 同一命名空间;
# E10 后它是口令的唯一非交互注入点 (本 CLI 不提供明文 --auth-pass 参数)。
# S105 误报: 值是环境变量**名字**不是口令字面量 (凭据零字面量铁律)
AUTH_PASSWORD_ENV = "ASTRO_BEST_PASSWORD"  # noqa: S105


def _resolve_password(auth_user: str) -> str:
    """解析登录口令: 只认 env, 交互终端才回落 getpass (E10)。

    明文口令走命令行参数会进 shell history 与 ``ps`` 输出, 同机任何用户都能
    回看, 因此本函数刻意不提供任何 argv 通道: 调用方只能经环境变量注入
    (CI/脚本可用 ``read -s`` 后再 export), 交互终端在线时才用 getpass 隐形
    读取。非交互且未给 env 时返回空串 —— 按匿名查询继续, 不让 CLI 在无人
    值守的管道里卡在口令提示上。

    Args:
        auth_user: 已给出的用户名 (为空表示本次不打算登录)。

    Returns:
        口令字符串; 用户名为空、或非交互且未给 env 时返回空串。
    """
    if not auth_user:  # 没给用户名就不提示口令: 匿名可查星表不该整体不可用
        # 没给用户名就不该提示口令: 匿名可查星表不因缺凭据而整体不可用
        return ""
    password = os.environ.get(AUTH_PASSWORD_ENV, "")  # E10: 口令唯一非交互注入点 (本函数刻意不提供明文 argv 通道)
    if password:  # env 优先: CI/脚本 read -s 后 export 即可, 无需交互
        return password
    if sys.stdin.isatty():  # 管道/CI 里 isatty 为假: 绝不能卡在口令提示上
        # 交互终端才提示: getpass 不回显, 口令同样不进 history
        return getpass.getpass(f"BEST password for {auth_user}: ")
    return ""  # 非交互且无 env: 按匿名继续, 不在无人值守的管道里挂起


def build_parser() -> argparse.ArgumentParser:
    """构建 CLI 参数解析器 (cone/download/crossmatch/catalogs/info/doctor 子命令)。

    Returns:
        配置好全局选项与六个子命令的 ArgumentParser; 全局 ``--catalog`` /
        ``--format`` 挂在共享父解析器上, 子命令写在主选项前后均可被接受
        (回归防线见 test_cli_accepts_catalog_and_format_after_subcommand)。
    """
    # 父解析器: 让 --catalog/--format 可出现在子命令前后 (argparse 默认
    # 只接受子命令之后的选项; 共享 parents 是唯一不改动调用姿势的修法)
    common = argparse.ArgumentParser(add_help=False)  # 共享父解析器: 让 --catalog/--format 可出现在子命令前后
    common.add_argument(                                                                          # 公共参数组: 子命令共享的那批选项先在此登记
        "--catalog", default="ps1",
        help=(                                                                                     # 帮助文案按行拼接: 单行太长会挤坏终端排版
            "Catalog id: ps1, stripe82, gaia_dr3_18, jplus_dr3, smss_dr4, landolt, "
            "uss_dr1, splus_dr4, scr_galah, scr_lamost, xpsp, dr3xpcorr "
            "(std/calib/other are navigation groups; gaia_dr3 stays accepted as a legacy alias)"
        ),
    )
    common.add_argument(                                                                           # 再加一个公共选项: 同一组里补齐缺的那一项
        "--format", default="csv",
        choices=["csv", "txt", "json", "votable"],
        help="Output format (default: csv)",
    )

    parser = argparse.ArgumentParser(  # prog 固定: 否则 --help 会打出 __main__.py 这种路径
        prog="astro-best",
        description="BEST database Python query & download tool",
        parents=[common],                                                                          # 挂到父解析器: 子命令因此不必各自重复声明
    )
    # 认证凭据: 只从命令行/env 注入, 源码内零字面量; 缺省匿名查询
    # (BEST 公开星表不需要登录, 见 P1-7)。
    # E10: 只保留 --auth-user; 口令不再有 --auth-pass 明文参数 — 命令行参数
    # 会进 shell history / ps 输出, 口令改走 env (ASTRO_BEST_PASSWORD) 或
    # getpass 隐形读取 (见 _resolve_password)。
    parser.add_argument(                                                                       # 子命令自己的选项: 与公共组分开声明, 便于分文件
        "--auth-user",
        help=(
            "BEST username for authenticated queries; the password is read from "
            f"env {AUTH_PASSWORD_ENV} or prompted invisibly via getpass — a "
            "plaintext --auth-pass command-line argument is deliberately not "
            "accepted (it would leak into shell history and ps output)"
        ),
    )
    # A4-01 (fail-closed): 显式给了凭据却登不进去, 默认**不**降级匿名 ——
    # 静默降级会让这次运行与一次纯匿名运行完全不可区分 (退出码 0、数据照常返回)。
    # 要降级必须由调用方显式打开本开关, 降级时打 stderr 说明。
    parser.add_argument(                                                                       # 与 --auth-user 同挂主解析器: 认证语义一起给
        "--allow-anonymous-fallback",
        action="store_true",                                                                    # store_true: 默认 False 即"不许降级"
        help=(
            "Downgrade to anonymous queries when --auth-user credentials are "
            "rejected by BEST (default: fail with a non-zero exit code). Without "
            "this switch, a rejected login is an error, not a silent fallback."
        ),
    )

    subparsers = parser.add_subparsers(dest="command", help="Commands")  # dest 固定: 整个分派只靠 args.command

    # cone search: 锥形检索 (pos.* 原生字段, 非 RA/Dec box-between; Q-01)
    cone = subparsers.add_parser("cone", help="Cone search around a position", parents=[common])
    cone.add_argument("--ra", type=float, required=True)  # 锥心必填: 没有中心的锥检索无意义
    cone.add_argument("--dec", type=float, required=True)
    cone.add_argument("--radius", type=float, default=180.0, help="Radius in arcsec")  # 180" 远大于 30" 级 PSF 匹配半径, 够覆盖一个点源
    cone.add_argument("--band", help="Filter by band (e.g. g, r, i, z, y)")
    cone.add_argument("--max", type=int, default=1000, help="Max records")  # 默认截断: 交互式查询不该一次拉十万行刷屏
    cone.add_argument("--output", help="Save results to file (auto-format from extension)")

    # download region: 区域下载 (两阶段协议 + 分页 + 四种格式落盘)
    dl = subparsers.add_parser("download", help="Download region data to file", parents=[common])
    dl.add_argument("--ra", type=float, required=True)
    dl.add_argument("--dec", type=float, required=True)
    dl.add_argument("--radius", type=float, default=600.0, help="Radius in arcsec")  # 比 cone 宽: 下载取的是整片区域做持久化, 不是看一眼
    dl.add_argument("--bands", help="Comma-separated bands (e.g. g,r,i)")
    dl.add_argument("--output", help="Output file path")
    dl.add_argument("--max", type=int, default=50000, help="Max records")  # 5 万行: 落盘场景的合理体量, 由分页取数兜住

    # crossmatch: 单坐标或 CSV 批量交叉匹配 (逐点异常隔离, Q-17)
    xm = subparsers.add_parser("crossmatch", help="Cross-match coordinates", parents=[common])
    xm.add_argument("--ra", type=float, help="Single RA to match")
    xm.add_argument("--dec", type=float, help="Single Dec to match")
    xm.add_argument(                                                                              # 交叉匹配子命令的选项: 半径与星表在此定缺省
        "--input", help="CSV file with ra,dec columns for batch matching"
    )
    xm.add_argument("--radius", type=float, default=3.0, help="Match radius in arcsec")  # 3" 够吸收星表间位置差, 再大就引入错配
    xm.add_argument("--output", help="Save results to file")

    # list catalogs: 列出全部星表 (导航组 std/calib/other 不在可查询集内)
    subparsers.add_parser("catalogs", help="List available catalogs")  # 不挂 common: 它不查数据, 无所谓 --catalog/--format

    # info: 连接自检 + 服务信息 (base_url 与 check_connection 探测结果)
    subparsers.add_parser("info", help="Check connection and show service info")

    # doctor: 环境体检 (Python/平台/服务端可达性/星表数/本地 RAG 知识库目录)
    subparsers.add_parser("doctor", help="Run health check and environment diagnostics")

    return parser  # 解析器是纯数据: build 阶段不发任何请求, 便于测试直接喂 argv


def main() -> int:
    """CLI 入口: 解析参数并分派子命令; 成功返回 0, 失败非零。

    职责边界: 只做"参数 → 子命令"的路由与退出码编排, 具体子命令
    的实现在各自模块; 本函数不含任何星表协议逻辑。

    Args:
        无 (参数全部来自 ``sys.argv``)。

    Returns:
        0 表示子命令成功; 1 表示未给子命令 (打印帮助) 或子命令
        报告失败; 具体非零码一律由子命令自己决定并向上传递。

    凭据缺失不在此判失败: 匿名可查的子命令照常执行, 只有真正需要
    认证的命令才因拿不到凭据而报错 (见下方 auth 分支)。反过来, **显式
    给了凭据却被站点拒绝**是失败 (返回 1), 不静默降级匿名 ——
    降级只由 ``--allow-anonymous-fallback`` 显式打开 (A4-01 fail-closed)。
    """
    # .env 先行加载 (YZ-57): `.env.example` 教用户 "Copy to .env and fill in
    # your credentials", 而此前全仓没有任何代码读它 —— 照做的人凭据进不了
    # 进程, 表现为「配了却不生效」。放在 main() 开头而不是模块导入期:
    # 库调用方 import src.* 不该被进程的环境状态改动, 只有真正跑 CLI 时才加载。
    # 已存在的真实环境变量优先, 故 CI 里 export 的值不会被本地 .env 压掉。
    load_dotenv_file()  # 文件不存在即静默返回空: .env 是便利项, 不是前置条件

    parser = build_parser()  # 建树与解析分开: 测试可绕过 argv 直接构解析器
    args = parser.parse_args()  # argparse 自己处理 -h 并 SystemExit, 这里不必兜

    # 未给子命令: 打印帮助并以 1 退出 (与"成功执行"区分, 便于脚本判定)
    if args.command is None:  # dest="command" 收不到值即代表没给子命令
        parser.print_help()                                                                       # 打印帮助即返回: 没给子命令时不该继续往下走
        return 1  # 非零: 脚本据此区分"没干活"与"干成了"

    # 凭据仅在用户名与口令都到位时才构造 BestAuth: 登录失败不抛异常 (只置
    # authenticated=False), 匿名可查星表不因缺凭据而整体不可用;
    # E10: 口令只从 env (ASTRO_BEST_PASSWORD) 或 getpass 读入, 不走 argv。
    auth = None  # 默认匿名: 缺凭据不该让匿名可查的子命令整体失败
    if args.auth_user:  # 只有显式给了用户名才尝试登录
        password = _resolve_password(args.auth_user)  # 口令唯一入口: env 或 getpass, 无 argv 通道
        if password:  # 用户名与口令都到位才登录: 半截凭据去登必然失败
            auth = BestAuth()  # 登录失败不抛, 只把 authenticated 置 False 并返回 False
            if not auth.login(args.auth_user, password):  # 返回值必须接: 丢弃它等于把"被拒"读成匿名可用
                # A4-01 (fail-closed): 显式给了凭据却登不进去 = 用户要的东西没拿到,
                # 默认不得静默降级 —— 否则这次运行与一次纯匿名运行不可区分。
                if not args.allow_anonymous_fallback:  # 默认不降级: 降级必须由显式开关打开
                    print(f"Error: login failed for {args.auth_user!r} — BEST rejected "
                          f"the credentials (no retry is attempted); re-run with "
                          f"--allow-anonymous-fallback to query anonymously, or fix "
                          f"the password in {AUTH_PASSWORD_ENV}",
                          file=sys.stderr)  # 走 stderr: stdout 仍是机器可读结果
                    return 1  # 非零: 显式凭据失败不能报成功, 否则脚本无从分辨
                print(f"Warning: credentials rejected for {args.auth_user!r}; "
                      f"--allow-anonymous-fallback was given, continuing anonymously",
                      file=sys.stderr)  # 显式开关才降级, 且必须留痕: 降级不是无声的
                auth = None  # 降级即真匿名: 被拒的会话不留 cookie 尾巴进客户端
        else:
            # 给了用户名却拿不到口令: 明说按匿名继续, 不静默降级
            print(f"Warning: no password for {args.auth_user!r} "
                  f"(set {AUTH_PASSWORD_ENV} or run interactively); "
                  f"continuing anonymously", file=sys.stderr)  # 走 stderr: stdout 仍是机器可读结果

    client = BestClient(auth=auth)  # 全子命令共用一个客户端: 连接与限流口径一致

    # 输出格式: catalogs 子命令没有 --format (未挂 common), 用 getattr 兜底 csv
    output_format = getattr(args, "format", "csv")  # getattr 而非直接取: 未挂 common 的子命令没有这个键

    if args.command == "cone":
        # 锥检索: 约束进 phase-1 表单 (pos.*), sqlid 回包后分页取数 (P0-2:
        # 先 getcount 拿服务端总数, total_count 以服务端口径为准)
        result = client.cone_search(  # 单一入口: 限流、重试与两阶段协议都在 client 内
            ra=args.ra, dec=args.dec,                                                             # 几何参数按名传: 位置传参易把中心与半径对调
            radius_arcsec=args.radius,                                                             # 半径独立一行: 与赤经赤纬同口径但不同单位
            catalog=args.catalog,                                                                   # 星表随行传: 与上面几项同为请求面参数
            band=args.band if hasattr(args, "band") and args.band else None,
            max_records=args.max,                                                                  # 取回上限: 工具层显式封顶, 超出即标截断
        )
        _print_or_save(result, output_format, getattr(args, "output", None))  # 出口二选一: 落盘或打摘要

    elif args.command == "download":
        # 延迟导入: downloader 反向依赖 client, 顶层导入会成环;
        # 只有 download 子命令真正需要它 (CLI 冷启动路径更短)
        from src.downloader import BestDownloader  # 延迟导入: downloader 反向依赖 client, 顶层导入会成环

        dl = BestDownloader(client)  # 复用同一客户端: 限流与连接口径与 cone 一致
        # --bands 是逗号分隔字符串, 拆成列表后交给下载器按波段过滤/投影
        bands = getattr(args, "bands", None)  # 只有 download 有 --bands, 故走 getattr
        bands_list = bands.split(",") if bands else None  # None 而非 []: 空列表会被下游当成"筛出零行"

        # 区域下载: 内部走完整两阶段协议 (POST 取 sqlid → GET 分页),
        # output_format 决定落盘格式, 未给 --output 时由下载器按星表+坐标命名
        filepath = dl.download_region(  # 两阶段与分页都在下载器内, CLI 只负责传参
            ra_center=args.ra,                                                                      # 天区中心赤经: 区域下载的定位依据
            dec_center=args.dec,                                                                    # 天区中心赤纬: 与赤经共同界定天区
            radius_arcsec=args.radius,                                                              # 区域半径: 角秒, 与单点检索不同量级
            catalog=args.catalog,                                                                   # 星表: 组名会在下游展开成成员
            bands=bands_list,                                                                       # 波段列表: 缺省不限波段
            output_format=output_format,                                                            # 输出格式: 声明式格式只进溯源
            output_file=getattr(args, "output", None),
            max_rows=getattr(args, "max", 50000),
        )
        print(f"Downloaded to: {filepath}")  # 报下载器返回的实际路径: 目录名可能被它规范化过

    elif args.command == "crossmatch":
        # 延迟导入: crossmatch 同样反向依赖 client, 避免顶层导入环
        from src.crossmatch import BestCrossMatch

        xm = BestCrossMatch(client)                                                             # 交叉匹配对象: 复用同一客户端会话, 节流才生效

        if args.input:  # CSV 批量优先于单点: 显式给了文件就不猜坐标
            # Batch from CSV file: 逐点锥检索, 单点失败进 errors 不中断整批 (Q-17)
            result = xm.crossmatch_from_csv(  # 批量路径: 逐点隔离异常, 坏行不拖垮整批
                args.input, catalog=args.catalog, radius_arcsec=args.radius,                        # 输入文件与星表: 半径同样按名传
            )
        elif args.ra is not None and args.dec is not None:  # 两坐标齐全才走单点: 缺一个就是输入不完整
            # Single coordinate: 单点也要包成列表走同一条批量路径 (语义一致)
            result = xm.crossmatch_coords(  # 单点也包成列表: 不为它单开第二条代码路径
                [args.ra], [args.dec],                                                          # 单点也走批量入口: 数组形态与列表入口同一条路径
                catalog=args.catalog, radius_arcsec=args.radius,                                    # 星表与半径随行传: 与上面同一口径
            )
        else:
            # 输入不完整: 明确报错并非零退出 (batch 与 single 二义时不猜)
            print("Error: specify --ra/--dec or --input")
            return 1  # 非零: 脚本据此知道交叉匹配没做成, 而非"跑完了没结果"

        # 交叉匹配结果固定以 json 呈现/落盘 (匹配关系是结构化数据)
        _print_or_save(result, "json", getattr(args, "output", None))  # 固定 json: 匹配关系是结构化数据, 不用 csv 展平

    elif args.command == "catalogs":
        # 星表清单: 从权威枚举生成 {id: 展示名}, 不硬编码列表
        # (新增星表只改 src.models, CLI 自动跟随)
        cats = {c.value: c.display_name for c in CatalogType}  # 从枚举生成: 硬编码列表迟早漏星表
        print(json.dumps(cats, indent=2, ensure_ascii=False))  # 不转义非 ASCII: 星表展示名含中文, 转义了不好读

    elif args.command == "info":
        # 连接自检: base_url 是协议锚点; check_connection 发一次真实探测请求,
        # 失败语义是返回 False 而非抛异常 (诊断命令不该自己崩)
        info = {  # base_url 是协议锚点, 与 CLIENT 配置同源
            "base_url": client.base_url,
            "connected": client.check_connection(),  # 失败返回 False 而非抛异常: 诊断命令不该自己崩
        }
        print(json.dumps(info, indent=2, ensure_ascii=False))  # 机器可读: 上层脚本能直接 json.loads

    elif args.command == "doctor":
        # 环境体检: 先打本地事实 (Python/平台), 再探测服务端可达性,
        # 最后核对本地 RAG 知识库目录是否存在 (离线也能给出可读结论)
        print("astro-best Environment Diagnostics:")
        print(f"  Python Version: {sys.version.split()[0]}")
        print(f"  Platform: {sys.platform}")
        conn = client.check_connection()  # 探测一次即复用: 避免同一诊断里发两次相同请求
        print(f"  NADC REST API Reachable: {conn}")
        # 延迟导入: protocol 是纯常量/键集模块, 只有 doctor 需要权威星表路由表
        from src.protocol import CATALOG_PATHS
        print(f"  Supported Catalogs ({len(CATALOG_PATHS)}): {', '.join(sorted(CATALOG_PATHS.keys()))}")
        # 定位仓库根下的 rag/knowledge: 以本文件为锚上溯一级 (本文件在 src/ 下, parents[1] 即仓根)
        rag_knowledge = Path(__file__).resolve().parents[1] / "rag" / "knowledge"  # 以本文件为锚上溯一级: 换机/换工作目录都能定位
        print(f"  Local RAG Knowledge Dir: {rag_knowledge.is_dir()}")  # 只报存在与否: doctor 求快, 不递归扫目录
        print("Doctor check completed.")
        return 0  # 显式 0: 诊断跑完即成功, 可达性 false 也不算失败

    return 0  # 成功: 子命令执行完且未报错


def _print_or_save(result, output_format="json", output_path=None):
    """Print or save query result.

    ``output_path`` 为空时向 stdout 打摘要 JSON (成功标志/总数/前 5 条源);
    非空时落盘为完整文件。两种形态都不吞 ``result.error``。
    """
    if output_path:  # 给了路径就落完整文件, 否则只打摘要: 两种形态都不吞 result.error

        # 延迟导入: 复用下载器的落盘逻辑 (csv/txt/json/votable 四种 emitter),
        # 避免在此重复实现格式细节; 数据根锚定单点 (P1-6)
        from src.downloader import BestDownloader  # 复用四种 emitter, 不在此重写格式细节
        from src.scripts.guards import resolve_data_path  # 数据根锚定单点 (P1-6)

        # P1-6: 对完整输出路径锚定到数据根 (起点校验) — 把
        # ``Path(output_path).parent`` 直接当 output_dir 传给 _save_result 的话,
        # 防逃逸单点的基准就成了用户给定的值 (校验可被参数化绕过);
        # env ASTRO_BEST_DATA_ROOT 可改数据根。
        anchored = resolve_data_path(output_path)  # 锚到数据根: 否则防逃逸基准成了用户自己给的值
        client = BestClient(rate_limit=0)  # rate_limit=0: 纯本地导出, 这个客户端绝不发真实请求
        try:
            dl = BestDownloader(client, output_dir=str(anchored.parent))  # 必须是锚定后的父目录, 不能用原始输入
            # 只借道 _save_result 的序列化能力: rate_limit=0 的客户端不会被
            # 用来发请求, 纯本地导出
            actual_path = dl._save_result(  # 只借序列化能力, 不借它的取数逻辑 (离线纪律)
                result, anchored.name, output_format)                                            # 结果与锚名成对出函: 落盘路径由下游按锚名解析
            print(f"Saved {len(result.sources)} results to {actual_path}")  # 报实际落盘名: 下载器可能再加后缀
        finally:
            # P1-6 附带: 这个客户端自持 requests.Session, 构造后不 close 会
            # 泄漏 socket (CLI 进程退出前释放)
            client.close()  # 放在 finally: 上面的写入抛异常也必须释放 socket
    else:
        # 摘要视图: total/returned/n_sources 分离, 让调用方直接看出
        # 服务端总数与本地实取数的差 (P0-2 截断可见性)
        output = {  # 三个计数分开: 服务端总数与本地实取数的差要肉眼可见
            "success": result.success,
            "total": result.total_count,
            "returned": result.returned_count,
            "n_sources": len(result.sources),
        }
        if result.error:  # 摘要同样带失败原因: 落盘与打印两种形态都不吞 error
            output["error"] = result.error
        if result.sources:  # 空结果时省略 sources 键, 而不是给一个空列表
            # 只预览前 5 条, 超出以 "... and N more" 提示, 避免刷屏
            output["sources"] = [s.to_dict() for s in result.sources[:5]]  # 截前 5 条: 摘要要短, 全文去落盘看
            if len(result.sources) > 5:  # 超出部分只报数量, 不展开: 展开就刷屏了
                output["sources"] += [f"... and {len(result.sources) - 5} more"]
        print(json.dumps(output, indent=2, ensure_ascii=False))  # 摘要也是合法 JSON: 脚本能直接解析


if __name__ == "__main__":
    # python -m src 入口: main() 的返回值即进程退出码
    sys.exit(main())  # python -m src 入口: main 的返回值即进程退出码
