"""src.scripts.config — Configuration loader (env -> YAML -> defaults).

能力边界: AstroBestConfig: 分层配置 (env → YAML → defaults)。边界: env_map 覆盖 .env.example 全部可映射键 (Q-16 SSOT); from_yaml 只读 defaults 且按白名单过滤 + WARN (Q-31); 禁版本字段 (全仓禁版本号)。
白盒锚点: .env.example (SSOT); templates/best-config.yaml。
"""
from __future__ import annotations

# 标准库: 日志/环境变量读取
import logging
import os

# 标准库: dataclass 定义与字段自省 (白名单过滤用 fields)
from dataclasses import dataclass, fields

# 标准库: 配置文件存在性判断
from pathlib import Path

# 标准库: 可选类型标注
from typing import Optional

logger = logging.getLogger(__name__)  # 配置层的问题一律归到本 logger, 不污染 root


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
    log_level: str = "INFO"  # 日志级别: 声明式, 由调用方配置 handler 时消费
    quality_filter: bool = True  # 质量门控开关: 默认开, 显式关掉才是有意的选择

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
            "BEST_LOG_LEVEL": "log_level",
            "BEST_QUALITY_FILTER": "quality_filter",
        }
        # env_map 与 .env.example 是 SSOT 关系: .env.example 是环境变量名的
        # 唯一权威声明处, 本表逐个映射到 dataclass 字段 (Q-16; 原 9 个声明
        # 变量只有 1 个真正生效, 其余声明了却没人读)。
        for env_key, attr in env_map.items():                          # env 无条件压过 YAML: 优先级是 Q-16 定的, 加载顺序不得动摇
            val = os.environ.get(env_key)                              # 未设即 continue: 绝不让空串覆盖已有值
            if val is None:  # 未设即跳过: 绝不让空串覆盖已有值
                continue
            current = getattr(self, attr)                              # 取默认值只为拿 Python 类型, dataclass 没有字段注解表可查
            # 按字段默认值类型做转换: bool 认 1/true/yes/on, float/int 显式转型
            if isinstance(current, bool):                              # bool 必须先判: isinstance(True, int) 为真会串类型
                setattr(self, attr, val.strip().lower() in ("1", "true", "yes", "on"))  # 真值集合窄: 只认四种常见写法, 免得把随意拼写当真
            elif isinstance(current, float):                           # 显式转型而非赋串: 字段类型本身就是下游消费契约
                setattr(self, attr, float(val))  # 显式转型而非赋串: 字段类型本身就是下游消费契约
            elif isinstance(current, int):
                setattr(self, attr, int(val))  # 整数同理转型: 字符串会一路带到请求层才炸
            else:
                setattr(self, attr, val)                              # 兜底字符串字段: 原样赋值不 strip, 免得改写 token
        # env 覆盖后 tap_url 别名同步 (保持两字段一致语义)
        self.tap_url = self.base_url                                   # 归一后强制两字段一致: 调用方读哪个都拿到同一值

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
