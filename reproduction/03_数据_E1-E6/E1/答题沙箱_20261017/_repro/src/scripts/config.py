"""src.scripts.config — Configuration loader (env -> YAML -> defaults).

能力边界: AstroBestConfig: 分层配置 (env → YAML → defaults)。边界: env_map 覆盖 .env.example 全部可映射键 (Q-16 SSOT); from_yaml 只读 defaults 且按白名单过滤 + WARN (Q-31); 禁版本字段 (全仓禁版本号)。
白盒锚点: .env.example (SSOT); templates/best-config.yaml。
"""
from __future__ import annotations

# 标准库: 日志/环境变量读取
import logging
import math
import os

# 标准库: dataclass 定义与字段自省 (白名单过滤用 fields)
from dataclasses import dataclass, fields

# 标准库: 配置文件存在性判断
from pathlib import Path

# 标准库: 可选类型标注; URL 组件拆分 (urlparse 拆 scheme/netloc, 端点结构校验用)
from typing import Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)  # 配置层的问题一律归到本 logger, 不污染 root

# 端点主机**不钉白名单**, 这是有意的 (YZ-30 的设计裁定, 不是漏做):
# - 主机白名单的真值源是 src/scripts/guards.py 的 ALLOWED_DOWNLOAD_HOSTS,
#   它的职责域是**下载栈** (validate_external_url, 文件下载的唯一入口);
# - base_url 是操作者自配的端点, 离线回放 (SnapshotTransport) 与镜像部署
#   都要把它指向官方主机之外, 钉死会把这两条正规用法一起关掉;
# - test/unit/meta/test_phase4_wiring.py 的 env→字段探针以
#   `https://probe.example/best` 断言 BEST_BASE_URL 确实生效, 那是 env 通道
#   的 SSOT 契约, 不能靠改测试来迁就校验。
# 故本模块只校验**结构** (scheme/主机/凭据/空白), 主机归属交由下载栈那一道。
_ALLOWED_URL_SCHEMES = ("https",)  # 元组而非 set: 只此一项, 元组保序且不可被消费方改写


def _validated_base_url(raw: str, source: str) -> str:
    """校验端点结构并归一 (YZ-30): 只认 https + 必须有主机 + 禁内嵌凭据。

    校验**结构**而非主机归属, 理由见模块级 ``_ALLOWED_URL_SCHEMES`` 上方
    的裁定。凭据那条是真问题: URL 里的口令会随异常消息与日志外泄, 而
    ``base_url`` 是被拼进每次请求的字符串。

    Args:
        raw: 端点原文 (来自 env 或 YAML)。
        source: 出处标签 (env 键名或 "YAML"), 报错时指明是哪条通道给的。

    Returns:
        去掉尾斜杠的端点串 (拼接路径时只需保证一处斜杠)。

    Raises:
        ValueError: 非 https / 无主机 / 含内嵌凭据 / 含空白或控制字符。
    """
    value = str(raw).strip()  # 去首尾空白: 前后空格会让主机名比对失配
    if not value:  # 空端点即拒: 否则每次请求都打到无主机的相对路径上
        raise ValueError(f"{source}: endpoint must not be empty")
    if value != str(raw):  # 首尾空白即拒: 与 urlparse 的容错相反, 这里不替调用方猜
        raise ValueError(f"{source}: endpoint must not carry surrounding whitespace: {raw!r}")
    parsed = urlparse(value)  # 拆组件而非正则: 各字段都有标准解析, 自写正则必漏边界
    if parsed.scheme not in _ALLOWED_URL_SCHEMES:  # 非 https 全拒: 明文会把响应内容暴露在链路上
        raise ValueError(
            f"{source}: endpoint must use https (got {parsed.scheme or 'no scheme'!r}): {raw!r}"
        )
    if not parsed.hostname:  # 无主机即无可解析的端点: 必须在消费前挡掉
        raise ValueError(f"{source}: endpoint has no host: {raw!r}")
    if parsed.username or parsed.password:  # 禁内嵌凭据: 口令会随日志与异常一起外泄
        raise ValueError(f"{source}: endpoint must not embed credentials: {raw!r}")
    return value.rstrip("/")  # 去尾斜杠: 后续拼路径靠它保证只有一处斜杠


def _finite_float(raw: str, source: str) -> float:
    """把 env/YAML 文本转成**有限** float (YZ-30), NaN/Inf 一律显式拒。

    拒的理由是 fail-open 而不是洁癖: 任何与 NaN 的比较都判 False, 于是
    ``min_snr=nan`` 会让质量门控的每一项比较恒判"合格" —— 配置写错反而
    把门控整个关掉, 且不报任何错。Inf 同理 (上限比较恒真)。

    Args:
        raw: 数值原文。
        source: 出处标签, 报错时指明是哪条通道给的。

    Returns:
        解析后的有限浮点数。

    Raises:
        ValueError: 非数值, 或数值是 NaN/Inf。
    """
    try:
        number = float(raw)  # 先转再判: 非数值在这里就炸, 不留到下游
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{source}: must be a number (got {raw!r})") from exc
    if not math.isfinite(number):  # 显式拒非有限值: 比较式门控对它们天然 fail-open
        raise ValueError(
            f"{source}: must be finite (got {raw!r}); NaN/Inf makes every "
            "threshold comparison silently pass"
        )
    return number


def _strict_int(raw: str, source: str) -> int:
    """把 env/YAML 文本转成严格 int, 报错点明是哪个键 (YZ-30)。

    ``int("3.5")`` / ``int("nan")`` 都抛, 故不存在静默取整; 这里只是把
    Python 默认的 ``invalid literal for int()`` 换成带键名的消息 —— 崩的
    位置一样 (fail-closed), 但用户知道该改哪个环境变量。

    Args:
        raw: 整数原文。
        source: 出处标签, 报错时指明是哪条通道给的。

    Returns:
        解析后的整数。

    Raises:
        ValueError: 非整数, 或是 bool 型文本这类非预期形态。
    """
    try:
        return int(str(raw).strip())  # 去空白再转: " 3 " 是常见的复制粘贴产物
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{source}: must be an integer (got {raw!r})") from exc


def load_dotenv_file(path: Optional[Path] = None, *, override: bool = False) -> dict[str, str]:
    """把 ``.env`` 文件读进 :data:`os.environ` —— 零第三方依赖 (YZ-57)。

    **为什么需要它**: ``.env.example`` 第 2 行一直写着 "Copy to .env and fill in
    your credentials", 而全仓此前**没有任何代码读 .env** —— 用户照做后凭据进不了
    进程, 表现为「配了却不生效」。这是一句骗人的指令, 不是缺一个便利功能。
    此前之所以没装 ``python-dotenv``, 是因为整个需求只要 ~30 行 stdlib 代码:
    为此引入一个新依赖不值当 (依赖零新增是本仓铁律之一)。

    语义 (刻意与所有主流 dotenv 实现一致, 不自创一套):

    - **真实环境变量优先**: 默认 ``override=False``, 已存在的键不被文件值覆盖。
      CI 里显式 export 的值必须压过本地 .env, 否则调试时改不动。
    - 只认 ``KEY=VALUE``; 支持可选的 ``export `` 前缀、行尾注释 (``#`` 前须有
      空白, 否则 ``abc#def`` 整体是值)、以及单/双引号包裹的值 (引号内不剥注释)。
    - 解析不了的行**跳过而不抛**: .env 是配置便利项, 一行手误不该让 CLI 起不来。
    - **查找顺序是仓根 → CWD, 且仓根优先** (2026-10-07 安全修复, AO2-CWD):
      此前缺省锚 ``Path.cwd()``, 于是在攻击者控制的目录下跑 ``python -m src``,
      那个目录的 ``.env`` 会被读进来并注入 ``ASTRO_BEST_PASSWORD`` 与
      ``BEST_BASE_URL``。.env 是**安装者的凭据文件**, 它的位置不该由"谁调用了
      这个进程"决定 —— 那等于把凭据交给 CWD 的主人。仓根由本模块位置静态推出,
      不受 cwd 影响。

    Args:
        path: ``.env`` 路径; ``None`` 时按「仓根 → CWD」的顺序取第一个存在的。
        override: True 时文件值覆盖已有环境变量 (默认不覆盖, 见上)。

    Returns:
        实际写入 ``os.environ`` 的 ``{键: 值}``; 一个都没找到时返回空字典。
    """
    # 仓根锚: 由本文件位置静态上溯 (本模块在 src/scripts/config.py, 上溯两级即仓根)。
    # 刻意不用 Path.cwd(): 那正是 AO2-CWD 的成因 —— 换目录就换掉了凭据来源。
    repo_env = Path(__file__).resolve().parents[2] / ".env"
    cwd_env = Path.cwd() / ".env"  # CWD 退居第二顺位: 仓根没有 .env 时才看它 (如把 skill 复制到别处用)
    # 候选顺序即优先级; 第一个**存在**的胜出, 而不是"都读一遍后者覆盖前者" ——
    # 后者会让 CWD 的 .env 反过来压过仓根, 等于没修。
    target = Path(path) if path is not None else next(
        (p for p in (repo_env, cwd_env) if p.is_file()), repo_env
    )
    if not target.is_file():  # 没有 .env 是**正常**状态 (CI 与库调用方都不必有)
        return {}
    written: dict[str, str] = {}
    for raw_line in target.read_text(encoding="utf-8-sig").splitlines():  # utf-8-sig: 容忍 Windows 编辑器写的 BOM
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue  # 空行与注释行: 无事可做
        if line.startswith("export "):  # 兼容 shell 习惯的写法: export KEY=VALUE
            line = line[len("export "):].lstrip()
        key, sep, value = line.partition("=")  # 只按第一个等号切: 值里可以再含等号
        key = key.strip()
        if not sep or not key:  # 无等号或键名为空 = 不是赋值行
            continue
        value = value.strip()
        if value[:1] in ("'", '"') and value[-1:] == value[:1] and len(value) >= 2:  # 成对引号才剥
            value = value[1:-1]  # 引号内不剥注释: 引号是"这是整体值"的显式声明
        else:
            value = value.split(" #", 1)[0].rstrip()  # 无引号才允许行尾注释, 且要求 # 前有空白
        if not override and key in os.environ:  # 真实环境优先: 已设的不动
            continue
        os.environ[key] = value
        written[key] = value
    if written:
        logger.debug("loaded %d key(s) from %s", len(written), target)  # 只记条数与路径, 绝不记值 (可能是凭据)
    return written


@dataclass
class AstroBestConfig:
    """BEST 客户端配置 (分层加载)。

    分层解析顺序: 环境变量 -> YAML 配置文件 -> dataclass 默认值
    (env 永远压过 YAML, YAML 压过默认值; 重实例化时 __post_init__ 会再跑
    一遍 env 覆盖, 保证该优先级不被加载顺序破坏)。
    """

    base_url: str = "https://nadc.china-vo.org/data/best"   # 官方 NADC 端点; env 与 YAML 均可覆盖
    api_token: Optional[str] = None  # 令牌字段: 客户端无此通道, 保留给 doctor 报告用
    rate_limit: float = 2.0  # 限流秒数: 线程池共享同一把时钟, 不能按请求各算
    max_retries: int = 3  # 重试次数: 只作用于适配器那一层, 不在其上手写循环
    timeout: int = 120  # 超时秒数: 各方法实际取协议层常量, 这里只是可配形态
    output_dir: str = "best_data"  # 默认输出目录: 相对当前工作目录, 落盘前另有路径消毒
    # 历史兼容字段 (astro-best 0.x 调用面): tap_url 为 base_url 别名;
    # min_snr/max_fwhm 供旧管线 fixture 注入质量门控阈值 (默认与 QualityGate 一致)。
    tap_url: Optional[str] = None  # 端点别名字段: 旧调用面按这个名字取端点, 与主字段同值
    min_snr: float = 5.0  # 信噪比门限: 缺省与质量门控一致, 两侧漂移会让门控形同虚设
    max_fwhm: float = 5.0  # 半高宽门限(像素): 同上, 与质量门控共用一套缺省
    # Q-16: .env.example 为 SSOT 双向补齐 — 原 9 个声明变量只有 1 个生效。
    # AH3-08: 曾经同在此处的 log_level 字段与 BEST_LOG_LEVEL 映射**零消费方**, 已
    # 连同 .env.example 的登记与 templates/best-config.yaml 的 defaults 键一并
    # 退役 (AH3-08 实测: 全仓 0 读取点, 含 getattr/下标/字符串键三种动态形态)。
    # 退役而非接线的理由: 本仓**没有任何一处装 logging handler** (全仓零
    # basicConfig/setLevel; 各模块一律 getLogger(__name__) 并把 handler 交给调用
    # 方), 接上它就得先发明一个日志配置面, 那是新增行为而不是补一个洞。quality_filter
    # **不**在退役名单里: 它有真消费方 (src/core/pipeline.py 经 _config_field
    # 读它并透传给 BestSkillClient.cone_search, 登记为 YZ-68)。
    quality_filter: bool = True  # 质量门控开关: 经 pipeline 透传到 QualityGate, 默认开, 显式关掉才是有意的选择

    def __post_init__(self) -> None:
        """Override with environment variables if set (并做旧字段别名归一)."""
        # 旧调用面: tap_url 显式给出时视为 base_url 定义 (base_url 缺省/一致时)。
        if self.tap_url and (                                         # 别名归一只在 base_url 仍缺省或两者相同时生效, 否则显式 base_url 优先
            self.base_url == "https://nadc.china-vo.org/data/best" or self.tap_url == self.base_url  # 显式端点优先: 只有主字段仍是缺省或两者相同时别名才生效
        ):
            self.base_url = str(self.tap_url).rstrip("/")             # 去尾斜杠: 后续拼路径靠它保证只有一处斜杠
        env_map = {                                                    # env 变量名 -> dataclass 字段名的 SSOT 映射表
            "BEST_BASE_URL": "base_url",
            "BEST_API_TOKEN": "api_token",
            "BEST_RATE_LIMIT": "rate_limit",
            "BEST_MAX_RETRIES": "max_retries",
            "BEST_TIMEOUT": "timeout",
            "BEST_DOWNLOAD_DIR": "output_dir",
            "BEST_MIN_SNR": "min_snr",
            "BEST_MAX_FWHM": "max_fwhm",
            "BEST_QUALITY_FILTER": "quality_filter",  # 消费方在 src/core/pipeline.py, 不在本文件
        }
        # env_map 与 .env.example 是 SSOT 关系: .env.example 是环境变量名的
        # 唯一权威声明处, 本表逐个映射到 dataclass 字段 (Q-16; 原 9 个声明
        # 变量只有 1 个真正生效, 其余声明了却没人读)。
        for env_key, attr in env_map.items():                          # env 无条件压过 YAML: 优先级是 Q-16 定的, 加载顺序不得动摇
            val = os.environ.get(env_key)                              # 未设即 continue: 空串/纯空白与未设同等对待
            if val is None or not val.strip():  # 空串与纯空白**都**视同未设: 容器与 CI 常注入无值变量, 让它覆盖掉默认值比不设更坏
                continue
            current = getattr(self, attr)                              # 取默认值只为拿 Python 类型, dataclass 没有字段注解表可查
            # 按字段默认值类型做转换: bool 认 1/true/yes/on, float/int 显式转型
            if isinstance(current, bool):                              # bool 必须先判: isinstance(True, int) 为真会串类型
                setattr(self, attr, val.strip().lower() in ("1", "true", "yes", "on"))  # 真值集合窄: 只认四种常见写法, 免得把随意拼写当真
            elif isinstance(current, float):                           # 显式转型而非赋串: 字段类型本身就是下游消费契约
                setattr(self, attr, _finite_float(val, env_key))  # NaN/Inf 显式拒: 比较式门控对它们天然 fail-open
            elif isinstance(current, int):
                setattr(self, attr, _strict_int(val, env_key))  # 整数同理: 崩在这里比崩在请求层可归因
            else:
                setattr(self, attr, val)                              # 兜底字符串字段: 原样赋值不 strip, 免得改写 token
        # 端点结构校验放在 env 覆盖**之后** (YZ-30): YAML 与 env 是两条入口,
        # 只校验 env 会漏掉 YAML 写坏的端点; 而校验放在最后只需一次, 两路
        # 产出的是同一个字段。tap_url 别名此时已同步, 故一并过校验。
        self.base_url = _validated_base_url(self.base_url, "base_url")  # 结构不合格即拒: 不静默回落缺省
        self.tap_url = self.base_url  # 归一后强制两字段一致: 调用方读哪个都拿到同一值
        # 有限性兜底扫全字段 (YZ-30): 上面 _finite_float 只覆盖 env 一条入口,
        # YAML 直接给的 float 绕过了它。这里按 dataclass 的**最终值**扫一遍,
        # 于是"NaN 进不了配置对象"是字段级不变量, 而不是某条通道的巧合。
        for spec in fields(self):  # 逐字段扫最终值: 非有限值只可能装在 float 里, 故不必再按注解类型筛
            value = getattr(self, spec.name, None)
            if isinstance(value, float) and not math.isfinite(value):  # 非有限即拒: 崩在配置层比静默放行好归因
                raise ValueError(
                    f"{spec.name} must be finite (got {value!r}); NaN/Inf makes "
                    "every threshold comparison silently pass"
                )

    @classmethod
    def from_yaml(cls, path: str) -> "AstroBestConfig":
        """从 YAML 文件读配置 (只读 ``defaults`` 段)。

        ``defaults`` 映射里的未知键按白名单剔除并 WARN (白名单 = dataclass
        字段集), 这样模板文件多带的键 (如 max_records/bands) 能干净加载,
        而不是直接抛 TypeError。

        Args:
            path: YAML 配置文件路径。

        Returns:
            AstroBestConfig; 文件缺失或环境无 yaml 时回退全默认实例。
        """
        try:
            # 延迟导入 yaml: 只有真读 YAML 配置才拉第三方依赖; ImportError
            # 与 FileNotFoundError 一样按 "无配置" 静默回退默认值。
            import yaml
            # IO 点: utf-8-sig 读 YAML, 兼容 Windows 编辑器写的 BOM 头
            with open(path, "r", encoding="utf-8-sig") as f:  # 用带 BOM 兼容的编码: Windows 编辑器写的配置也能读
                data = yaml.safe_load(f) or {}  # 空文件归一成空字典: 缺配置与空配置都落到无覆盖分支
            raw = dict(data.get("defaults", {}) or {})  # 只取 defaults 段: 其余段属别的用途, 混进来会污染字段
            # 白名单 = dataclass 字段集; 模板多出来的键只 WARN 不炸
            known = {f.name for f in fields(cls)}                     # 白名单取自字段本身: 加字段自动放行, 无需再维护一份清单
            unknown = sorted(k for k in raw if k not in known)  # 排序后告警: 未知键的输出顺序稳定, 便于逐条清点
            if unknown:  # 有未知键才告警: 干净的模板不该每次加载都刷一条
                logger.warning(  # 告警而非抛错: 模板多带键是常态, 不该让 CLI 起不来
                    "AstroBestConfig.from_yaml: ignoring unknown keys %s in %s",  # 消息里带键名: 只说忽略了什么键, 用户无从清点
                    unknown, path,  # 同时带文件名: 同一份模板在多处使用时能定位来源
                )
            filtered = {k: v for k, v in raw.items() if k in known}  # 白名单过滤后再构造: 未知键不进构造器, 免得类型错误
            return cls(**filtered)                                    # 传 filtered 而非 raw: 未知键不进构造器, 免得 TypeError
        except (FileNotFoundError, ImportError):
            return cls()                                              # 静默回退: 缺文件/缺 pyyaml 都属"没给配置", 不该让 CLI 崩

    @classmethod
    def load(cls, path: Optional[str] = None) -> "AstroBestConfig":
        """分层加载配置: env -> YAML -> default。

        重实例化 (``cls(**config.__dict__)``) 是故意的, 不是疏漏: 它让
        ``__post_init__`` 的 env 覆盖与 tap_url 别名归一对"最终字段集"再执行一遍, 从构造上保证 env 优先于 YAML — 不论 config 由
        哪条加载路径产出 (env+默认 / YAML+env), 最终实例的字段都最后一次
        经过 env 覆盖。env 覆盖幂等, 执行两遍结果一致, 无副作用 (A5: 登记
        结论"无需修", 此处仅注明意图)。

        Args:
            path: 可选 YAML 配置文件路径; 给空或文件不存在时只用 env+默认。

        Returns:
            AstroBestConfig (env 覆盖已生效)。
        """
        config = cls()                                                 # 起点永远是纯默认实例: __post_init__ 里的 env 覆盖已经生效
        if path and Path(path).exists():                              # 显式判存在: 路径缺失按"无配置"处理而不是报错
            config = cls.from_yaml(path)  # 有路径才换: 没给配置时保留已含 env 覆盖的默认实例
        # 以公开字段重建实例: 剔除私有属性, 并让 __post_init__ 的 env 覆盖
        # 与 tap_url 别名归一再跑一遍 — 保证 env 始终压过 YAML 的最终语义。
        return cls(**{k: v for k, v in config.__dict__.items()
                      if not k.startswith("_")})  # 只留公开字段: 剔掉下划线开头的私有属性, 别名归一才能重跑


# 兼容别名: 保留旧类名 BestConfig, 让历史 import 路径继续可用 (能力不变)
BestConfig = AstroBestConfig  # 用别名而非子类: 否则 isinstance 会按两个类名分裂
