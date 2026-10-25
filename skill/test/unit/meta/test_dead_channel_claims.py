# -*- coding: utf-8 -*-
"""守护: 死通道宣称 —— 文档面/工具面不得把**代码里没有的通道或门禁**说成可用 (H9)。

缺陷形态 (2026-10-05 H9 审计, 与 H2-01 同源但落在别的所有权面): 某条通道
"文档/诊断输出说它能用, 代码里压根没有这个消费方"。用户照着配环境变量, 什么
也不会发生 —— 比"没写"更坏, 因为它看起来像一份可执行的部署说明。

本轮实测到的四处 (逐条独立核实过代码, 见 temp/FIX-H9-dead-channels.md):

  1. ``ops/astro_best_cli.py`` 的 ``config`` 子命令把 ``BEST_API_TOKEN`` 报成
     ``token_env`` 凭据来源。**这一条最重**: 它是用户可见的诊断输出, 不是散文。
  2. ``manifest.yaml`` 的 ``best_query`` 注释写 ``BestQuery(sql, token∈env
     BEST_API_TOKEN)`` —— 两处假: ``BestQuery.__init__(self)`` 根本不收参数
     (更没有 ``sql``), token 也不走这里。
  3. ``references/ALGORITHM-SPEC.md`` §2 认证行写 "token 走 env BEST_API_TOKEN",
     与同文件 §4 已经写对的"真实凭据面"自相矛盾。
  4. ``static/fragments/algo_mode/best_two_phase.yaml`` 的 ``env:`` 映射里列
     ``api_token_override: BEST_API_TOKEN`` —— 读起来就是"用它覆盖凭据",
     而该文件自己上面两行的注释已经说了它不是凭据来源。

门禁宣称侧另有一处 (``rag/knowledge/domain_rules.yaml::checksum-gate`` 说
"流式下载完成后逐段校验; 不一致重试/告警"): 实测代码是**落盘后整文件**一次
比对 (写前意图摘要 vs 读后读回摘要), 不一致**既不重试也不告警**, 且外部基准
``expected_sha256`` 生产零传入。**注意方向**: 本轮 G5 已把 ``checksum_match``
从恒写 ``"unknown"`` 改成真布尔, 所以门禁 ``checksum_match==True`` 当前**可达**
—— 照旧审计报告去"三态化"会做反方向, ``TestGateClaimStillMatchesCode`` 的
反向用例就是钉这一点的。

与 H2 的分工 (两件守护刻意不重叠): ``test_rag_knowledge_vs_code.py`` 守
``rag/knowledge/**`` 的凭据通道宣称; 本件守 **manifest / references / static /
ops 工具输出 / evals 题面** 这一层, 外加门禁语义与代码的一致性。

**2026-10-05 (J1) 补齐的四处宣称** —— 原先它们被本模块 docstring 记为"已知越界
缺陷, 故意不覆盖" (理由: 把未修文件纳入守护 = 用假覆盖率换一个真红)。本轮已修,
故一并纳入守护面, 理由栏见 ``EVAL_SURFACES``:

  5. ``references/fallback-protocols.md`` FB-2 曾写 "TAP Bearer 通道另用
     ``BEST_API_TOKEN``" —— 真实校验方是**注入的** ``token_validator`` 回调
     (``src/tap/service.py``; 未注入则任何 token 一律 401), ``src/tap/`` 零读 env
     凭据。已改写并纳入 ``DOC_SURFACES``。
  6. ``evals/nl2tool/tasks.yaml`` 与 ``evals/ablation/items.yaml`` 的 NL2T-26
     ``suggest`` 曾教 agent "凭据走 BEST_API_TOKEN" —— 这是**在教一条死通道**,
     且它的 ``verify_cmd`` 恰好在核验死通道存在, 于是门禁全绿。两侧文本已换成真实
     凭据面 (数据面 ``--auth-user`` + ``ASTRO_BEST_PASSWORD``; 身份层 ``NADC_OAUTH_*``),
     ``verify_cmd`` 改为核验真实凭据键确已登记, 金标准轨迹由 ``gen_golden.py``
     重新合成 (只此一个文件变化)。

**仍未纳入守护的面 (刻意, 记在此处以免它变成隐形盲区)**: ``.env.example`` ——
它点名 ``BEST_API_TOKEN`` 时的"死路"措辞写在键的**上一行**而非同行, 句级判据
按行切会判它红。改法只需把免责话挪到键那一行的行尾注释, 但那超出本轮所有权
(那是 J1 任务一的文件, 由 ``TestEnvSsotCoversRealCredentialSurface`` 守其**键覆盖**,
不守其措辞)。人读该文件不会被误导 (措辞就在紧邻的上一行), 故留作已知缺口而非
默默不管。

判据纪律: **事实一律从代码现场取** (``inspect.signature`` / ``src.__main__``
常量 / AST 扫调用点), 文档侧只被检查"有没有说错"。所以代码改名/改签名而文档
没跟上时本件变红, 反过来文档回退到旧宣称时也变红 —— 两个方向都在判。
"""
from __future__ import annotations

# 标准库: ast 静态扫调用点 (不 import 被扫模块, 免副作用进测试进程) /
#         argparse 造 cmd_config 的入参 / importlib 按路径装载 ops 件 /
#         inspect 取真实签名 / io+json 收 CLI 真实输出 / os 注入口令做泄漏用例 /
#         pathlib 锚仓根 / re 切句
import argparse
import ast
import importlib.util
import inspect
import io
import json
import os
import re
import sys
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any

SKILL_ROOT = Path(__file__).resolve().parents[3]   # 仓根: 本件在 test/unit/meta/ 下三级
if str(SKILL_ROOT) not in sys.path:                # 幂等: 与 test/conftest.py 同一纪律
    sys.path.insert(0, str(SKILL_ROOT))

SRC_DIR = SKILL_ROOT / "src"                        # 代码面: 唯一权威

# 已退役的凭据通道: env 键名清单。三个都在本仓出现过, 但客户端**零消费方**
# (TestChannelIsStillDead 会用真实签名现场证明这一点)。
RETIRED_CHANNELS = ("BEST_API_TOKEN", "BEST_API_USER", "BEST_API_PASS")

# 判定"这句已经把它标成死路"的措辞锚: 只认明说退役/无消费方的那几类说法, 不认
# 泛泛的"安全""隔离" —— 放得太宽就成了永远绿的橡皮图章。
RETIRED_MARKERS = ("死路", "无消费方", "无此通道", "非凭据来源", "存而不用", "已退役", "死参数")

# 真实凭据面的两个构成: 用户名走 argv 参数、口令只走 env (刻意无 --auth-pass 明文参数)。
# 键名不写死, 运行时从 src.__main__.AUTH_PASSWORD_ENV 取 —— 代码改名即红。
USERNAME_ARG = "--auth-user"
FALLBACK_FLAG = "--allow-anonymous-fallback"

# 文档面守护覆盖的文件 (真值以**文本**形式存在, 逐行/逐文件判据都适用)。
# 刻意不含 rag/knowledge/ (H2 守护已覆盖); 2026-10-05 (J1) 起含
# references/fallback-protocols.md —— 原先它有同款死通道宣称而不在本轮所有权,
# 已修毕故纳入 (全文点名 --auth-user 与口令 env, 文件级判据成立)。
DOC_SURFACES: tuple[tuple[str, Path], ...] = (
    ("manifest.yaml", SKILL_ROOT / "manifest.yaml"),
    ("references/ALGORITHM-SPEC.md", SKILL_ROOT / "references" / "ALGORITHM-SPEC.md"),
    (
        "static/fragments/algo_mode/best_two_phase.yaml",
        SKILL_ROOT / "static" / "fragments" / "algo_mode" / "best_two_phase.yaml",
    ),
    ("references/fallback-protocols.md", SKILL_ROOT / "references" / "fallback-protocols.md"),
)

# 题面/轨迹面 (2026-10-05 J1 纳入): 只吃**句级**"同句标死路"判据, 不进
# DOC_SURFACES 的文件级判据 —— 理由是评测标注的文本是**被评分的期望答案**, 不是
# 给人指路的散文: 要求它携带 CLI argv 开关没有意义; 而它的措辞恰恰会被 agent
# 当成事实学走 (原缺陷: NL2T-26 建议教 agent 走 BEST_API_TOKEN 死通道)。
# 三份各自独立判: 铁律 6 (零跨实验 import / 各实验自包含) 下, E1 的 tasks.yaml
# 与 E5 的 items.yaml 是两份自有副本, 判据不得假定它们同源或互相兜底。
EVAL_SURFACES: tuple[tuple[str, Path], ...] = (
    ("evals/nl2tool/tasks.yaml", SKILL_ROOT / "evals" / "nl2tool" / "tasks.yaml"),
    ("evals/ablation/items.yaml", SKILL_ROOT / "evals" / "ablation" / "items.yaml"),
    (
        "evals/nl2tool/traces/golden/NL2T-26.json",
        SKILL_ROOT / "evals" / "nl2tool" / "traces" / "golden" / "NL2T-26.json",
    ),
)

# 工具面: CLI 源码。它的真实凭据面在**运行期输出**里, 不在源码文本里 ——
# 口令 env 键名是从 src.__main__ 导入的符号, 源码里本就不该出现字面量 (出现
# 才是第二份真源)。故它只吃"同句标死路"判据; 真实面由
# TestConfigCliNeverAdvertisesADeadChannel **真跑** payload 核。
# 实测记录: 第一版把 CLI 也纳入文件级"必须出现真实 env 键名"判据, 立刻红在
# "全文找不到 ASTRO_BEST_PASSWORD" —— 那不是缺陷, 恰恰是设计对了, 于是收窄。
CLI_SOURCE: tuple[str, Path] = ("ops/astro_best_cli.py", SKILL_ROOT / "ops" / "astro_best_cli.py")

# 吃"同句标死路"判据的全部面 (文档面 + 工具面 + 题面): 该判据只需要退役通道名与
# 措辞锚, 两者在源码里都是字面量, 所以 CLI 与题面也在内。
MARKER_SURFACES: tuple[tuple[str, Path], ...] = DOC_SURFACES + (CLI_SOURCE,) + EVAL_SURFACES

# ── env SSOT 的**凭据面**双向对账 (2026-10-05 J1) ─────────────────────────
# .env.example 第 3 行自称"环境变量 SSOT: 每个键都必须能被代码真实读取"。本组
# 判据兑现这句话的**凭据那一半**: 代码真的在读的口令/OAuth 变量, 必须逐个登记在
# 示例文件里。P0 由来: ASTRO_BEST_PASSWORD (E10 后口令的唯一非交互注入点) 从未
# 登记, 而**照示例文件配置的用户配不出一个能用的登录** —— 它看起来像一份可执行
# 的部署说明, 于是比"没写"更坏。
#
# 为什么这道判据不是"再抄一份键名清单": 键名全部从代码现场扫出 (AST 静态解析,
# 不 import, 免副作用进测试进程), 代码改名即红, 清单与代码漂移无从发生。
ENV_EXAMPLE = SKILL_ROOT / ".env.example"           # 声称是 SSOT 的那份文件

# 凭据面的**定义持有者**: 只有持 env 键名定义的模块能被静态扫出字面量。
# 逐个写明凭什么在名单里 (判据窄一格正是本轮 P0 的成因, 故不留"随手列"的余地):
#   src/__main__.py        E10 之后口令的唯一非交互注入点 (_resolve_password 读它)
#   src/auth/nadc_oauth.py NADC 身份层三个 env (ENV_CLIENT_ID/SECRET/REDIRECT_URI)
# 刻意不含 src/scripts/config.py: 它的 env_map 是**调参面** (端点/限流/超时/质量门),
# 不是凭据; 那一层的双向对齐由 test_phase4_wiring.py::TestEnvSSOT 的探针表守。
# 也不含 ops/astro_best_cli.py: 它确实读 password_configured, 但走的是**导入的
# 符号** (os.environ.get(AUTH_PASSWORD_ENV)), 按构造扫不出字面量 —— 它读什么由
# TestConfigCliNeverAdvertisesADeadChannel 真跑 payload 核。
CREDENTIAL_ENV_DEFS: tuple[Path, ...] = (
    SKILL_ROOT / "src" / "__main__.py",
    SKILL_ROOT / "src" / "auth" / "nadc_oauth.py",
)

# 第二条腿: 凭据"形状"的键名, 扫**整个 src/**, 与上面那份名单正交。
# 存在的理由: 名单制的老毛病就是"下回写到第四个文件里就又逃逸了" —— 形状扫描
# 不管它落在哪个模块, 新增一个 *_PASSWORD / *_SECRET / *_TOKEN / *_API_KEY 都被
# 捞出来要求登记。两条腿取并集, 缺哪条都在 docstring 里写明代价。
CREDENTIAL_NAME_SHAPE = re.compile(r"(PASSWORD|SECRET|TOKEN|API_KEY|CREDENTIAL)", re.IGNORECASE)


def _env_keys_in_module(path: Path) -> set[str]:
    """AST 扫一个模块读到的 env 键名: 常量引用与字面量直取两种形态都认。

    静态解析而非 import: import 被扫模块等于执行它 (``ops/astro_best_cli.py`` 在
    导入时就会改 ``sys.path``), 判据不该给测试进程留副作用。

    Args:
        path: 待扫的 ``.py`` 文件路径。

    Returns:
        该模块里出现的 env 键名集合; 扫不到即空集 (由调用方判是否为空转)。
    """
    keys: set[str] = set()
    tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))   # 只解析, 不执行
    for node in tree.body:                                                       # 只看模块顶层: 函数体内的局部名不是 env 键来源
        if isinstance(node, ast.Assign):                                         # X = "ENV_KEY" 形态
            targets, value = list(node.targets), node.value
        elif isinstance(node, ast.AnnAssign):                                    # X: str = "ENV_KEY" 形态
            targets, value = [node.target], node.value
        else:
            continue
        if not (isinstance(value, ast.Constant) and isinstance(value.value, str)):
            continue                                                             # 非字符串字面量不是 env 键名
        if not re.fullmatch(r"[A-Z][A-Z0-9_]+", value.value):
            continue                                                             # 只认全大写带下划线: 免得把 URL/普通文案算成键
        if any(isinstance(t, ast.Name) and "ENV" in t.id for t in targets):       # 常量名带 ENV 才认: AUTH_PASSWORD_ENV / ENV_CLIENT_ID / DATA_ROOT_ENV
            keys.add(value.value)
    for node in ast.walk(tree):                                                  # 再扫字面量直取形态
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue                                                             # 只认方法调用
        func = node.func
        is_env_read = (func.attr == "getenv" and isinstance(func.value, ast.Name) and func.value.id == "os")
        is_environ_get = (func.attr == "get" and isinstance(func.value, ast.Attribute)
                          and func.value.attr == "environ")                      # os.environ.get("KEY")
        if not (is_env_read or is_environ_get):
            continue
        for arg in node.args[:1]:                                                # 只看第一个实参 (键名位)
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str) and re.fullmatch(r"[A-Z][A-Z0-9_]+", arg.value):
                keys.add(arg.value)                                              # os.environ["KEY"] 形态
    return keys


def _credential_env_keys() -> set[str]:
    """代码现场扫出的**真实凭据** env 变量名 (两条腿取并集)。"""
    keys: set[str] = set()
    for path in CREDENTIAL_ENV_DEFS:                                              # 第一条腿: 定义持有者全量收
        assert path.exists(), f"凭据面定义持有者 {path.name} 不存在: 路径漂移会让下面的对账空转"   # 前提断言
        keys |= _env_keys_in_module(path)
    for path in sorted(SRC_DIR.rglob("*.py")):                                    # 第二条腿: 全 src/ 按名字形状扫
        if path in CREDENTIAL_ENV_DEFS:
            continue                                                              # 已扫过, 不重复
        keys |= {k for k in _env_keys_in_module(path) if CREDENTIAL_NAME_SHAPE.search(k)}
    return keys


def _declared_env_keys(env_example_text: str) -> set[str]:
    """从示例文件文本解析**已登记**的键 (只认赋值行, 注释行不算键)。"""
    keys: set[str] = set()
    for line in env_example_text.splitlines():
        m = re.match(r"^([A-Z][A-Z0-9_]*)=", line.strip())                      # 与 ops/audit/verify_crossrefs.py §7 同口径
        if m:
            keys.add(m.group(1))
    return keys


def _missing_env_declarations(env_example_text: str) -> list[str]:
    """代码真实读取、而示例文件未登记的凭据变量 (空列表 = 全覆盖 = 绿)。

    抽成纯函数是为了让下面的突变用例能就地喂一份"少登记一个键"的文本, 无需
    改磁盘上的真文件 —— 真文件由本函数在主判据里喂。
    """
    return sorted(_credential_env_keys() - _declared_env_keys(env_example_text))


def _sentences(text: str) -> list[str]:
    """把一段文本切成句子 (句号/分号/换行皆为句界)。

    与 H2 守护同口径且同理由: 本仓文档大量用分号分点陈述, 把分号当句界才能
    让"同句"判据真的落在半句话上; 不切分的话, 一段里任何位置的免责话都能替
    所有话背书 —— 而引用与转述时人只会摘走那半句。
    """
    return [s for s in re.split(r"[。；;\n]", text) if s.strip()]


def _doc_units() -> list[tuple[str, int, str]]:
    """逐行产出文档面单元 (文件名, 行号, 该行文本)。

    逐行而非整篇: 一篇里任何位置的免责话都不能替别处的话背书。行号进标签是
    为了让判据红了能直接跳过去看。
    """
    units: list[tuple[str, int, str]] = []
    for name, path in MARKER_SURFACES:                             # 全部吃句级判据的面, 含 CLI 源码
        assert path.exists(), f"守护面 {name} 不存在: 路径漂移会让下面所有判据空转"  # 前提断言
        for lineno, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
            units.append((name, lineno, line))
    return units


def _doc_files() -> dict[str, str]:
    """按文件聚合文档面全文 (文件名 -> 全文)。

    供"这个文件能不能回答该用什么"这类**文件级**判据使用: 单看某一行会把
    "死路登记行 + 上一行写真实面"这种正常排版判成违规。
    """
    files: dict[str, str] = {}
    for name, path in DOC_SURFACES:                                   # 只遍历文档面: CLI 源码不适用文件级判据 (真值在运行期输出里)
        assert path.exists(), f"守护面 {name} 不存在: 路径漂移会让下面所有判据空转"  # 前提断言
        files[name] = path.read_text(encoding="utf-8-sig")             # utf-8-sig: 与仓内其他读取口径一致 (容忍 BOM)
    return files


def _load_cli() -> Any:
    """按路径装载 ops/astro_best_cli.py (ops/ 不是包, 只能这样加载; 与 CLI 同口径)。"""
    spec = importlib.util.spec_from_file_location("astro_best_cli_under_test", SKILL_ROOT / "ops" / "astro_best_cli.py")
    assert spec is not None and spec.loader is not None, "ops/astro_best_cli.py 装载 spec 失败"  # 前提断言
    module = importlib.util.module_from_spec(spec)                     # 先建模块对象, 再执行 —— 与生产装载同序
    spec.loader.exec_module(module)                                   # 执行模块体: 只定义函数与常量, 不跑 main
    return module


def _config_payload() -> dict[str, Any]:
    """**真跑** ``cmd_config``, 解析它给用户看的那份 JSON。

    为什么必须真跑而不 grep 源码: 要守的正是"用户能看到的输出"。源码里留着
    死字段但输出时被过滤掉, 或输出层临时拼一个, grep 都看不出来; 而这是本次
    最重的一处 (用户在照着它配环境变量)。
    """
    cli = _load_cli()                                                # 每次现载: 模块级 sys.path 注入不跨用例污染
    buf = io.StringIO()                                              # 收 stdout: 不起子进程, 免掺入环境因素
    with redirect_stdout(buf):                                        # 换流而非起子进程: 判据就是这份 stdout 本身
        rc = cli.cmd_config(argparse.Namespace(json=True))           # --json 出口 = 机器可读那份
    assert rc == 0, f"config 诊断必须恒返回 0 (Q-19), 实得 {rc}"
    return json.loads(buf.getvalue())                                # 真解析: 输出若不是合法 JSON, 这里就红


def _expected_sha256_production_callers() -> list[str]:
    """AST 扫 ``_save_result`` 的生产调用点, 返回真正传了 ``expected_sha256`` 的那些。

    判据的事实侧: 外部基准形参有没有人传。不 import 被扫模块 —— 那等于执行
    下载器, 一次真实 IO 就可能把测试变成活体测试。
    """
    sites: list[str] = []
    for path in sorted(SRC_DIR.rglob("*.py")):                       # 只扫 src/: 测试与 evals 的调用不算生产传入
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))   # 只解析, 不执行
        for node in ast.walk(tree):                                  # 递归找全部调用点, 不靠行号猜
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
                continue                                             # 只认方法调用, 不认同名属性
            if node.func.attr != "_save_result":                    # 只认落盘统一出口
                continue
            passed_expected = len(node.args) > 3                    # 形参顺序: result, file, fmt, expected_sha256
            passed_expected = passed_expected or any(                # 关键字传法也要算: 位置参数漏了不代表没传
                kw.arg == "expected_sha256" for kw in node.keywords
            )
            if passed_expected:
                sites.append(f"{path.relative_to(SKILL_ROOT).as_posix()}:{node.lineno}")   # 行号进清单: 红了能直接跳过去看
    return sites


def _checksum_gate_rule() -> str:
    """取 ``domain_rules.yaml::checksum-gate`` 那条的全文 (缺失即抛)。"""
    rules = yaml_rules()                                             # 解析结果带 id, 便于按标识取单条
    assert "checksum-gate" in rules, "domain_rules.yaml 缺 checksum-gate: 门禁知识被删必须让守护变红"
    return rules["checksum-gate"]


def yaml_rules() -> dict[str, str]:
    """解析 domain_rules.yaml, 返回 {规则 id: 该规则全文}。

    全文 = 标题 + 正文 + tags 全拼: 只看一个键会漏判 —— 一条知识完全可以把
    真实机制写在 title、把错的话留在 description。
    """
    import yaml  # 延迟导入: 只这一处用到

    data = yaml.safe_load((SKILL_ROOT / "rag" / "knowledge" / "domain_rules.yaml").read_text(encoding="utf-8-sig"))
    out: dict[str, str] = {}
    for rule in data.get("rules", []):
        if isinstance(rule, dict) and rule.get("id"):
            out[str(rule["id"])] = "\n".join(
                str(v) for v in rule.values() if isinstance(v, (str, list))
            )
    return out


class TestChannelIsStillDead:
    """反向前提: 先证明这些通道**当下真的没有消费方**, 下面几条判据才成立。"""

    def test_best_skill_client_takes_no_api_token(self):
        """``BestSkillClient.__init__`` 不得重新长出 ``api_token`` 形参。

        反向判据: 哪天真给客户端接上了 token 通道, 本件会红, 那时正确动作是
        重新评估下面几条文档判据 (而不是把本测试改成放行) —— 因为"这条通道是
        死路"这个前提本身变了。
        """
        from src.core import BestSkillClient  # 真导入: 签名必须是代码的真实签名

        params = list(inspect.signature(BestSkillClient.__init__).parameters)
        assert "api_token" not in params, (
            f"BestSkillClient 又收 api_token 了 (现签名 {params}); 若已接线, "
            "请重写本守护的文档判据, 别只把它改绿"
        )

    def test_password_env_name_is_still_a_plain_constant(self):
        """口令 env 键名必须仍从 CLI 本体导出 (取不到即说明 CLI 口径变了)。"""
        from src.__main__ import AUTH_PASSWORD_ENV  # 真导入: 键名的唯一权威来源

        assert AUTH_PASSWORD_ENV, "CLI 必须仍声明口令 env 键名 (取不到说明凭据面变了, 文档判据需重写)"


class TestNoDeadChannelAdvertised:
    """文档面不得把已退役通道说成可用通道。"""

    def test_dead_path_marker_shares_the_sentence(self):
        """提到退役通道时, **同一句**必须同时把它标成死路。

        判据落在句级而不是行级/条目级: 死路登记写在相邻句里, 对引用无效 ——
        人与 agent 命中的是整条, 但转述时只摘走那半句, 于是"token 走 env
        BEST_API_TOKEN"又被当成可用通道传下去。
        """
        offenders: list[str] = []
        for name, lineno, line in _doc_units():                      # 逐行逐面扫: 一篇里任何位置的免责话都不能替别处背书
            for channel in RETIRED_CHANNELS:                         # 逐通道判: 一个标了死路不代表另一个也标了
                if channel not in line:
                    continue                                          # 没提就是没提, 不算问题
                marked = any(                                       # 同句 (按句号/分号/换行切) 同时有通道名与措辞锚才算标过
                    channel in s and any(m in s for m in RETIRED_MARKERS)
                    for s in _sentences(line)
                )
                if not marked:
                    offenders.append(f"{name}:{lineno} 的 '{channel}' 同句没标死路")
        assert not offenders, offenders                              # 文档宣称死路可用 = 文档在骗部署方

    def test_surfaces_naming_a_dead_channel_point_at_the_real_face(self):
        """只要某个文件点了退役通道的名, 该文件就必须能回答"那该用什么"。

        为什么这一条比上面那条宽一格 (文件级而非句级): "标死路"是会被单独
        摘走的断言, 必须同句; 而"真实面在哪"是路标 —— 读者与 agent 是连着
        上下文读的, 死路登记与真实面分两行写才是人写得出来的排版, 强行要求
        同句/同行只会把文档逼到读不懂。两级松紧是有意的分工, 不是判据不一致。

        (实测记录: 第一版按**行**判, 立刻把三处正当的"死路登记行 + 上一行
        写真实面"判成违规 —— 行级过严, 收窄到文件级后既不再误伤, 仍能抓住
        "整篇只字未提真实凭据面"这种真缺口。)
        """
        password_env = _password_env_name()                          # 现场取键名: 写死就会与代码漂移
        offenders: list[str] = []
        for name, text in _doc_files().items():                      # 文件级聚合: 死路登记与真实面分两行写是正常排版
            if not any(c in text for c in RETIRED_CHANNELS):
                continue                                              # 没点死通道名的文件不归这条判据管
            if password_env not in text or USERNAME_ARG not in text:  # 两个构成缺一即答不出"那该用什么"
                offenders.append(f"{name} 点了退役通道名, 全文却没指向 {USERNAME_ARG} + {password_env}")
        assert not offenders, offenders


def _password_env_name() -> str:
    """口令 env 键名: 现场从 CLI 本体取, 不写死 (代码改名即红)。"""
    from src.__main__ import AUTH_PASSWORD_ENV  # 真导入: 键名的唯一权威来源

    return AUTH_PASSWORD_ENV                                         # 交回调用方: 判据只拿它做比对, 不复制一份


class TestConfigCliNeverAdvertisesADeadChannel:
    """``config`` 子命令的用户可见输出不得把退役通道报成凭据来源 (本次最重的一处)。"""

    def test_payload_does_not_expose_the_dead_fields(self):
        """payload 里不得再有把死通道当凭据来源的字段。

        旧版字段是 ``token_env`` + ``token_configured``: 前者直接告诉用户
        "凭据来源是这个 env 键", 后者让它以为配了就能用。两者都必须消失。
        """
        payload = _config_payload()                                  # 真跑一次拿用户实际看到的那份
        leaked = [k for k in ("token_env", "token_configured") if k in payload]   # 逐个点名, 不抽样
        assert not leaked, f"config 输出仍把退役通道报成凭据来源: {leaked}"

    def test_payload_names_the_real_credential_face(self):
        """payload 必须点名真实凭据面: 口令 env 键名 (现场取) + 用户名参数 + 降级开关。"""
        payload = _config_payload()                                  # 真跑一次: 输出层临时拼的字段只有真跑才看得见
        credential = payload.get("credential")                       # 真实面独立成段: 与"退 env 键"区分开, 读的人不会混
        assert isinstance(credential, dict), f"config 输出缺 credential 段 (实得 {sorted(payload)})"
        password_env = _password_env_name()                          # 期望值取自代码, 不是本守护写死的字面量
        assert credential.get("password_env") == password_env, (
            f"口令 env 键名与 CLI 本体不符: 输出 {credential.get('password_env')!r} vs 代码 {password_env!r}"
        )
        assert credential.get("username_arg") == USERNAME_ARG, "真实凭据面必须点名用户名参数"
        assert credential.get("fallback_flag") == FALLBACK_FLAG, "凭据被拒的降级开关必须一起报出来"
        assert credential.get("anonymous_ok") is True, "公开数据面匿名可查, 报告必须说明"

    def test_dead_key_is_labelled_in_the_payload(self):
        """退役键名若仍出现在输出里 (为对照旧部署而保留), 同一句必须标死路。

        不要求删掉键名本身: 直接删会让看过旧输出的人以为是自己看错了, 保留
        键名 + 同句写死"客户端无此通道"才是把设计意图和事实都留住。
        """
        payload = _config_payload()                                  # 真跑一次: 登记段在输出层, 不在源码常量里
        retired = payload.get("retired_env_keys")                    # 死路登记段: 存在性本身就是被守的一部分
        assert isinstance(retired, dict) and retired, "退役键登记段不见了: 旧部署无法对照, 且无人再声明它是死路"
        for key, note in retired.items():                            # 逐键判: 登记段可能被追加新键
            assert key in RETIRED_CHANNELS, f"retired_env_keys 里出现未登记的键 {key!r}: 判据与清单脱节"
            assert any(m in note for m in RETIRED_MARKERS), f"退役键 {key!r} 的说明没标死路: {note!r}"

    def test_password_value_never_reaches_stdout(self):
        """口令**值**绝不进 stdout: 诊断输出会被日志收走。

        保留旧版那条纪律 (只回布尔不回显值), 只是把布尔挂到真实 env 键上 ——
        纪律是对的, 挂错的键才是缺陷。
        """
        cli = _load_cli()                                            # 现载: 不依赖别的用例留下的模块状态
        sentinel = "h9-sentinel-password-value"                      # 哨兵值: 唯一能证明"没泄漏"的东西
        old = os.environ.get(_password_env_name())                   # 先存原值: 测完必须还原, 否则污染同进程后续用例
        os.environ[_password_env_name()] = sentinel                  # 注入后跑: 没注入就证不了"真配了会不会漏"
        try:
            buf = io.StringIO()
            with redirect_stdout(buf):                               # 收输出: 泄漏就是漏在这里
                cli.cmd_config(argparse.Namespace(json=True))
            out = buf.getvalue()
        finally:
            if old is None:
                os.environ.pop(_password_env_name(), None)           # 原本没配 → 还原成没配
            else:
                os.environ[_password_env_name()] = old               # 原本配了 → 还原成原值
        assert sentinel not in out, "口令值泄漏进 config 输出: 凭据本体绝不能进 stdout"
        payload = json.loads(out)                                    # 顺带确认真是合法 JSON (没被字符串拼接破坏)
        assert payload["credential"]["password_configured"] is True, "配了口令时该布尔应为 true (只回布尔不回值)"


class TestManifestMatchesQueryBuilderSignature:
    """``manifest.yaml`` 的 ``best_query`` 注释必须与 ``BestQuery`` 真实签名一致。"""

    def test_best_query_takes_no_constructor_args(self):
        """前提: ``BestQuery()`` 是无参构造 —— 所以注释里写不出 ``BestQuery(sql``。"""
        from src.query_builder import BestQuery  # 真导入: 签名必须是代码的真实签名

        params = [p for p in inspect.signature(BestQuery.__init__).parameters if p != "self"]   # 去掉 self 才是真形参
        assert not params, (
            f"BestQuery 又收构造参数了 (现签名 {params}); 若确实新增, 注释需同步更新判据"
        )

    def test_manifest_comment_does_not_invent_constructor_args(self):
        """manifest 不得写 ``BestQuery(sql`` 这类代码里不存在的构造签名。"""
        offenders: list[str] = []
        for name, lineno, line in _doc_units():                      # 复用同一批文档单元, 免得两处各维护一份面
            if name != "manifest.yaml":
                continue                                              # 只管 manifest: 这条判据针对它的 inputs 注释
            if re.search(r"BestQuery\s*\(\s*\w", line):              # BestQuery( 后紧跟标识符 = 在宣称有构造参数
                offenders.append(f"{name}:{lineno} 宣称 BestQuery 有构造参数: {line.strip()}")
        assert not offenders, offenders


class TestGateClaimStillMatchesCode:
    """门禁宣称 (``checksum-gate``) 必须与落盘校验的真实实现一致。"""

    def test_expected_sha256_has_no_production_caller(self):
        """前提: 外部基准形参生产零传入 —— 所以本门禁不能与发布方基准比。"""
        sites = _expected_sha256_production_callers()                 # AST 事实侧: 有没有生产调用点真传了外部基准
        assert not sites, (
            f"生产已有人传 expected_sha256 ({sites}); 门禁可与外部基准比, "
            "domain_rules.yaml 里'不可比'的说法已过期, 需同步改判据"
        )

    def test_rule_states_the_self_consistency_basis(self):
        """规则必须说清比对基准是**整文件**写前/写后摘要自洽, 并点出外部基准不可比。"""
        text = _checksum_gate_rule()                                  # 取单条全文: 标题+正文+tags 全算
        assert "整" in text, "checksum-gate 没说清是整文件比对 (真实实现: 落盘后整文件算一次 SHA-256)"
        assert "expected_sha256" in text, "checksum-gate 必须点名外部基准形参 expected_sha256"
        assert ("不可比" in text) or ("零传入" in text), (
            "checksum-gate 必须说明外部基准生产零传入, 故与发布方基准不可比"
        )

    def test_rule_does_not_claim_per_segment_or_retry(self):
        """规则不得宣称逐段流式校验, 也不得宣称不一致会重试/告警 (代码两样都不做)。"""
        text = _checksum_gate_rule()                                  # 取单条全文
        for phrase in ("逐段校验", "不一致重试/告警"):                   # 两条旧版假宣称, 逐个点名
            assert phrase not in text, (
                f"checksum-gate 仍宣称 {phrase!r}; 真实实现是整文件一次比对, "
                "不一致既不重试也不告警"
            )

    def test_rule_does_not_repeat_the_retired_unknown_claim(self):
        """反向: 门禁当前**可达**, 规则不得再说它恒为 unknown / 永不满足。

        方向性提醒: 旧审计报告称"``checksum_match`` 生产永远产不出 true,
        sidecar 恒为 ``'unknown'``"。本轮 G5 已改成真布尔, 照那份报告去
        "三态化"会做反方向。本用例就是钉住这个方向: 代码已是布尔时, 文档
        再宣称不可达即红 (而代码真退回恒写 unknown 时, 本用例自动放行, 由人
        重新判断该写成什么)。
        """
        text = _checksum_gate_rule()                                  # 取单条全文
        is_bool_in_code = not re.search(                               # 扫全 src/: 代码里还写不写死字符串形态
            r"checksum_match\s*=\s*[\"']unknown[\"']",                # 代码里恒写字符串 = 已退回旧形态
            "\n".join(p.read_text(encoding="utf-8-sig") for p in sorted(SRC_DIR.rglob("*.py"))),
        )
        if is_bool_in_code:                                           # 只有代码确实是布尔时, "不可达"才成了一句假话
            for phrase in ("恒为 unknown", "恒写 unknown", "永不满足", "永不可满足"):   # 旧报告那几种措辞
                assert phrase not in text, (
                    f"checksum-gate 仍宣称 {phrase!r}, 但代码里 checksum_match 已是真布尔 (G5 已改)"
                )


class TestEnvSsotCoversRealCredentialSurface:
    """``.env.example`` 自称 env SSOT, 就不得漏掉代码真实读取的**凭据**变量。

    这道判据的方向与本件其余各条**相反**, 值得说清: 其余各条守"文档宣称了代码
    没有的通道", 本条守"代码用了而文档没登记的通道"。后者更隐蔽 —— 少登记一个
    键不会让任何现有断言变红, 只会让照示例文件配置的用户配不出可用登录。

    键名**不写死**: 全部从代码现场 AST 扫出 (见 ``_credential_env_keys``), 所以
    代码改了键名而示例文件没跟上, 本条立刻红; 反向 (示例多登记一个没人读的键)
    由 ``ops/audit/verify_crossrefs.py`` §7 的双向对账守, 两件各管一头。
    """

    def test_env_example_declares_every_credential_var_the_code_reads(self):
        """主判据: 代码真实读取的凭据变量必须逐个登记在 ``.env.example``。"""
        text = ENV_EXAMPLE.read_text(encoding="utf-8-sig")              # 真文件, 不造副本自证自洽
        missing = _missing_env_declarations(text)                       # 纯函数: 少登记即列出键名
        assert not missing, (
            f".env.example 漏登记代码真实读取的凭据变量: {missing} —— "
            "照本文件配置的用户配不出可用凭据 (ASTRO_BEST_PASSWORD 曾长期漏登记, "
            "而当时 verify_crossrefs 的消费方名单窄了一格, 全门禁照样绿)"
        )

    def test_discovery_is_not_vacuous(self):
        """扫描器自身不得空转: 空转与全绿在退出码上完全同形。"""
        keys = _credential_env_keys()                                   # 现场扫一遍
        assert keys, "从代码扫不出任何凭据变量: 判据已空转, 必须修扫描器而不是删判据"
        assert _password_env_name() in keys, (
            f"口令 env 键 {_password_env_name()!r} 不在扫出的凭据面里: "
            "要么常量名不再带 ENV, 要么模块被挪走 —— 判据需按新事实重写"
        )
        oauth = {k for k in keys if k.startswith("NADC_OAUTH_")}         # 身份层三键应一并捞出
        assert len(oauth) == 3, f"只捞出 {sorted(oauth)}: 身份层 env 定义没被扫到, 第二条腿可能已失效"

    def test_dropping_any_single_declaration_turns_the_check_red(self):
        """突变证据: **任意**一个键从示例文件里消失, 对账必须立刻报出它。

        逐键做而不是抽一个样例: 判据的非空转性是"漏一个就红", 抽样只能证明
        "抽到的那一个会红"。这里对扫出的每一个键都做一次原地突变, 喂纯函数,
        不碰磁盘上的真文件。
        """
        text = ENV_EXAMPLE.read_text(encoding="utf-8-sig")              # 真文件全文当底本
        keys = sorted(_credential_env_keys())                           # 扫出的全部键
        assert keys, "扫不出键就无从做突变实验: 先修扫描器"
        for key in keys:                                                # 逐键突变
            mutated = "\n".join(                                        # 删掉该键的赋值行, 其余原样
                ln for ln in text.splitlines() if not re.match(rf"^{key}=", ln.strip())
            )
            assert key in _missing_env_declarations(mutated), (
                f"从 .env.example 删掉 {key} 后对账仍判绿: 判据对该键失效 (空转)"
            )

    def test_the_password_env_is_declared_as_an_assignment(self):
        """点名本轮 P0: 口令 env 必须以 ``KEY=`` 赋值行登记, 而不是只在注释里被提到。

        单独钉这一条, 因为"注释里提过"曾经是它唯一的出现方式 —— 而用户照抄的是
        赋值行, 注释对配置毫无作用。
        """
        text = ENV_EXAMPLE.read_text(encoding="utf-8-sig")
        assert _password_env_name() in _declared_env_keys(text), (
            f".env.example 没有 {_password_env_name()}= 赋值行: 它是口令唯一的非交互注入点, "
            "漏登记即等于没有这个通道"
        )
