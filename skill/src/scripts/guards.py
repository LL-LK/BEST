"""src.scripts.guards — 入参校验 + 输出格式化 + 路径锚定 + 安全落盘 (全包守卫单点)。

能力边界: I/O 协议: 入参校验 (validate_coordinate/validate_search_radius) + 输出格式化(to_csv/to_json) + ADQL 语法校验 (validate_adql_query, BEST 无 TAP 端点仅语法) + 原子落盘 (atomic_write_text)、目录锚定 (resolve_within)、数据根锚定 (resolve_data_path 封闭 / anchor_output_dir 开环, P1-5/6/7 起点校验) 与下载 URL 主机白名单 (validate_external_url, P1-10) 四个全仓单点实现。边界: 编码 utf-8-sig (Q-60); 异构记录 fieldnames 取并集 (Q-58); 无 stdlib 同名遮蔽 (Q-59)。
白盒锚点: references/ALGORITHM-SPEC.md §1 (BEST 无 TAP/ADQL 声明)。
"""

from __future__ import annotations

# 标准库: CSV 写出/内存缓冲/JSON 序列化/日志/路径与 os.replace 原子替换/
# time 供 os.replace 退避重试 (Windows 并发读者会让 replace 抛 WinError 5);
# ipaddress 判 IP 字面量 (P1-10) / urlparse 拆 URL 组件 (P1-10);
# math.isfinite 显式拒 NaN/Inf (YZ-07/YZ-58: 任何与 NaN 的比较都判 False,
# 比较式守卫对它天然 fail-open); 可选类型标注 (to_csv 的 fieldnames 形参)
import csv
import io
import ipaddress
import json
import logging
import math
import os
import time
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

# 本地: CSV 公式注入消毒 (Q-06) — 每个值落盘前统一过闸
from src.csv_safety import sanitize_row

logger = logging.getLogger(__name__)  # 模块级 logger: handler 交调用方配置, 本模块不装

# 数据根覆盖开关 (P1-5/P1-6/P1-7 路径锚定单点): 用户相对路径一律相对它解析。
# 权威定义就在本模块: 消费方一律从这里取, 不许在别处再写一个同名环境变量
# (P1: CLI 侧另有一份定义会造成双份漂移, 改环境变量只对其中一处生效)。
DATA_ROOT_ENV = "ASTRO_BEST_DATA_ROOT"  # env 键名是跨模块契约: 消费方一律从这里取, 不得另立同名常量

# 下载 URL 主机白名单 (P1-10): BEST 官方数据面唯一主机。权威来源:
# BEST_BASE_URL (src/protocol.py) 的宿主部分; 消费方: validate_external_url
# (best_export.download_file 的唯一入口校验)。
ALLOWED_DOWNLOAD_HOSTS = frozenset({  # frozenset 而非 set: 白名单一旦构建就不该被任何调用方改写
    "nadc.china-vo.org",  # 主站主机名: 权威来源是协议层站点常量所指的宿主
    "www.nadc.china-vo.org",  # 带 www 的等价写法: 不加它会把合法链接判成外部主机
})


def validate_coordinate(ra: float, dec: float) -> tuple[float, float]:
    """校验天球坐标范围 (入口防线, 非法值不发请求)。

    安全理由: 负 RA / 越界 Dec 直传服务端只会得到晦涩的服务端报错或空
    结果, 浪费配额且难排查; 在入口显式失败, 调用方立刻看到是哪颗星坏。

    Args:
        ra: 赤经 (度)。
        dec: 赤纬 (度)。

    Returns:
        校验通过的 (ra, dec) 元组 (原值返回, 不做归一化)。

    Raises:
        ValueError: ra 不在 [0, 360)、dec 不在 [-90, 90], 或任一坐标为
            NaN/Inf 或 bool (YZ-07/YZ-58: 任何与 NaN 的比较都判 False,
            纯比较式守卫对它天然 fail-open; bool 是 int 子类, 不先判会被
            静默当作 0.0/1.0 度坐标放行)。
    """
    if isinstance(ra, bool) or isinstance(dec, bool):  # bool 是 int 子类: True/False 会被比较守卫静默当作 1.0/0.0 度, 必须先判
        raise ValueError(f"coordinates must be real numbers, not bool: ra={ra!r}, dec={dec!r}")
    if not (math.isfinite(ra) and math.isfinite(dec)):  # 先拒 NaN/Inf: 任何与 NaN 的比较都判 False, 比较守卫对它天然放行
        raise ValueError(f"coordinates must be finite, got ra={ra!r}, dec={dec!r}")
    if not 0 <= ra < 360:  # 左闭右开: 360 与 0 指同一方向, 归一到 0
        raise ValueError(f"RA must be in [0, 360), got {ra}")
    if not -90 <= dec <= 90:  # 两端都闭: ±90 是合法天极, 不可照抄 RA 的开区间
        raise ValueError(f"Dec must be in [-90, 90], got {dec}")
    return (ra, dec)


def validate_search_radius(radius_arcsec: float) -> float:
    """校验检索半径 (必须为正, 且不超过 5 度上限)。

    安全理由: 0/负半径是无意义查询, 超限半径会把锥检索退化成半张星表,
    既拖慢服务端又可能触发限流; 上限 18000 角秒 (5 度) 是 BEST 公开接口
    的容忍边界。

    Args:
        radius_arcsec: 检索半径 (角秒)。

    Returns:
        校验通过的半径 (原值返回)。

    Raises:
        ValueError: 半径非正、超过 18000 角秒, 或为 NaN/Inf 或 bool
            (YZ-07: ``nan <= 0`` 与 ``nan > 18000`` 均判 False, 纯比较式
            守卫对 NaN 天然放行, 必须像坐标守卫一样显式拒)。
    """
    if isinstance(radius_arcsec, bool):  # bool 是 int 子类: True 会被静默当作 1 角秒半径, 必须先判
        raise ValueError(f"Search radius must be a real number, not bool: {radius_arcsec!r}")
    if not math.isfinite(radius_arcsec):  # 先拒 NaN/Inf: 任何与 NaN 的比较都判 False, 下面两条比较守卫对它天然放行 (YZ-07)
        raise ValueError(f"Search radius must be finite, got {radius_arcsec!r}")
    if radius_arcsec <= 0:  # 非正即拒: 0/负半径是无意义查询, 服务端只会回空或报错
        raise ValueError(f"Search radius must be positive, got {radius_arcsec}")
    if radius_arcsec > 18000:  # 上限 5 度 (服务端约束式锥搜的最大半径)
        raise ValueError(f"Search radius too large: {radius_arcsec} arcsec")  # 超限即拒: 大半径把锥检索退化成半张星表并触发限流
    return radius_arcsec


def validate_adql_query(query: str) -> str:
    """ADQL 查询字符串的形状校验 (仅语法层, 不解析)。

    BEST 不发布任何 TAP/ADQL 端点, 所以这只是形状检查: 拒绝空串和缺
    ``SELECT``/``FROM`` 子句的串。**不得**把它称作 "syntax validation" 或等价说法:
    这里只做 strip 后的形状检查, 那种叫法会让这道门声称超出实际检查能力的含义,
    调用方误以为已过语法关。

    Args:
        query: 待校验的 ADQL 查询字符串。

    Returns:
        strip 后的查询字符串。

    Raises:
        ValueError: 查询为空, 或首词不是 SELECT, 或缺 FROM 子句。
    """
    text = query.strip()  # 先去空白: 全空白串也要落进空串分支被拒
    if not text:  # 空串无首词可判: 提前拒, 免得下面取下标越界
        raise ValueError("Empty ADQL query")
    words = text.split()  # 按空白切词: 只为判首词与子句存在, 不做真解析
    if words[0].upper() != "SELECT":  # 大小写不敏感: 关键字不区分大小写, 但必须以 SELECT 起头
        raise ValueError("ADQL query must start with SELECT")
    if " FROM " not in f" {text.upper()} ":  # 两端补空格: 否则首词或尾词的 FROM 会被漏判
        raise ValueError("ADQL query must contain a FROM clause")
    return text


def atomic_write_text(
    path: str | Path,
    content: str,
    encoding: str = "utf-8",
    retry_delays: tuple[float, ...] = (),
) -> Path:
    """原子写文本: 先写 ``<name>.tmp`` 再 ``os.replace``, 异常也清理临时文件。

    全仓唯一实现 — downloader / progress store / checkpoint / 光变导出一律调本
    函数, 不得各带一份副本: 副本一旦漂移, 读者就会看到半写文件。写失败时临时
    文件也会被删掉, 不留垃圾。

    ``newline=""`` 是刻意为之: 文本模式会把 ``csv.writer`` 产出的
    ``\r\n`` 再翻译成 ``\r\r\n``, 在 Windows 上每条 CSV 记录后多出一个空行
    (实测复现)。内容逐字落盘, 行尾由调用方自己控制。

    Args:
        path: 目标路径 (父目录不存在会顺手创建)。
        content: 逐字落盘的内容。
        encoding: 文本编码 (默认纯 utf-8; Excel 兼容用 utf-8-sig, 见 Q-60)。
        retry_delays: ``os.replace`` 失败时的退避重试间隔序列; 缺省 (空序列)
            = 单次尝试不重试。**Windows 专项**: 目标文件被并发读者 (GUI/CLI)
            持有时 ``os.replace`` 会抛 ``PermissionError`` (WinError 5), 而
            该异常会顺着调用栈直达工作线程, 一次瞬时竞争就杀死任务。给一段
            退避序列即可吸收它; 重试耗尽后按原类型抛出, 上层
            ``except OSError`` 的既有行为不变。

            这一段逻辑原先只存在于 ``src.download_progress`` 的私有副本里 ——
            那正是"副本一旦漂移"的实例: 主实现缺了副本长出来的能力。此处把它
            收进全包单点, 两个模块共用同一份退避语义。
    """
    target = Path(path)  # 规整成路径对象: 后面要取名、取父目录、拼临时名
    target.parent.mkdir(parents=True, exist_ok=True)  # 父目录顺手建: 目标目录不存在时直接开写会失败
    tmp_path = target.parent / f"{target.name}.tmp"  # 临时名与目标同目录: 跨文件系统会让 os.replace 退化成复制, 失去原子性
    try:
        # IO 点: newline="" 防止 Windows 下行尾二次翻译 (\r\n -> \r\r\n)
        with open(tmp_path, "w", encoding=encoding, newline="") as handle:  # newline="" 是关键: 文本模式会二次翻译, Windows 上多出空行
            handle.write(content)  # 写进临时文件: 此时目标文件还没被动过, 读者不受影响
        # IO 点: os.replace 同目录原子替换, 读者只会看到完整旧文件或完整新文件。
        # 退避序列缺省为 (None,): 单次尝试且不睡; 给了序列则按序重试,
        # 每次失败后都退避 (含最后一次), 与 progress store 的原语义逐位一致。
        last_error: OSError | None = None  # 循环外声明: 区分"重试耗尽"与"首次即成"
        for delay in (retry_delays or (None,)):
            try:
                os.replace(tmp_path, target)  # 同目录 rename 才原子: 换目录就退化成"复制后删除"
                last_error = None  # 成功即清空: 不让循环后的判断误报失败
                break
            except OSError as exc:
                last_error = exc  # 记住最后一次异常, 耗尽后按原类型重抛
                if delay is not None:
                    time.sleep(delay)  # 退避递增: 给并发读者退出临界区的窗口
        if last_error is not None:
            raise last_error  # 原类型重抛: 上层 except OSError 的既有行为不变
    finally:
        if tmp_path.exists():  # 替换成功后临时文件已消失, 这里只兜失败路径
            try:
                # IO 点: 清理临时文件 (替换成功后 tmp 已不存在, 这里是失败兜底)
                tmp_path.unlink()
            except OSError:
                # pragma: no cover - 尽力而为的清理, 失败也不该冒泡出去
                logger.debug("temp cleanup failed for %s", tmp_path)  # debug 而非 warning: 清理失败不该把一次好写入报成问题
    return target  # 返回最终路径而非 tmp: 调用方拿到的必须是落盘产物所在处


def resolve_within(base: str | Path, name: str) -> Path:
    """把 ``name`` 解析到 ``base`` 目录内, 拒绝一切逃逸企图。

    拒绝绝对路径、盘符、目录分隔符与 ``..`` 成分 — 调用方给的文件名
    (``--out`` / ``job_id`` / ``output_file``) 因此永远写不出目标目录。
    Windows 上绝对路径 ``C:/x`` 会整体替换路径根, 单查 ``".." not in parts``
    的旧防线对它完全失效; 这里多路并查。

    Args:
        base: 基准目录。
        name: 待锚定的文件名 (必须是裸文件名)。

    Returns:
        解析后的绝对路径 (保证位于 base 之内)。

    Raises:
        ValueError: name 为空、带首尾空白、含目录成分, 或解析结果逃逸。
    """
    raw = str(name)  # 先字符串化: 非字符串名也走同一套锚定检查
    if not raw or raw != raw.strip():  # 空串与带首尾空白都拒: 空白名是调用方拼接失误, 不该静默修
        raise ValueError(f"invalid state file name: {name!r}")
    if raw != Path(raw).name or set(raw) <= {"."}:  # 两路并查: Windows 的 C:/x 能整体替换路径根, 单查 ".." 拦不住
        # 必须是裸文件名, 且不能是 ``.``/``..``/``...`` 这类点号串 (它们虽通过
        # Path(raw).name 检查, 但指向目录或造成歧义)
        raise ValueError(f"path must be a bare file name: {name!r}")
    if os.path.pardir in Path(raw).parts:  # 显式查 parts 而非子串: 名里含 ".." 的合法文件不该被误杀
        raise ValueError(f"path traversal denied: {name!r}")
    root = Path(base).resolve()  # 先 resolve 才谈得上"在 base 之内": 不解析链接时判定可被链接绕过
    resolved = (root / raw).resolve()  # 再次 resolve: 逐段展开 .. 与链接后才比得出真实归属
    if root != resolved and root not in resolved.parents:  # root != resolved 是"恰好等于根"的放行口
        raise ValueError(f"path escapes the base directory: {name!r}")
    return resolved  # 返回绝对路径: 免得调用方再基于 CWD 二次解析


def data_root() -> Path:
    """数据根: env ``ASTRO_BEST_DATA_ROOT`` 优先, 缺省 skill 根本身。

    Returns:
        解析后的绝对路径。环境变量优先, 使用户可把数据目录指到 skill 之外
        (测试用 tmp_path、部署用独立数据盘都走这条 env, 不需要改代码)。
    """
    # 读环境变量 (外部配置输入点): 用户显式指定数据根时才生效
    env = os.environ.get(DATA_ROOT_ENV)  # 外部配置输入点: 只有用户显式设置才改变数据根
    if env:  # 真值判断: 空串视同未设, 免得解析出一个指向 CWD 的"数据根"
        return Path(env).expanduser().resolve()  # expanduser: 用户习惯写 "~/data", 不展开就落错地方
    # 缺省: src/scripts/guards.py 上溯两级即 skill 根 (src/scripts -> src -> root)
    return Path(__file__).resolve().parents[2]  # 硬编码两级: 改目录层级必须同步改这里, 宁可显式也不要猜


def anchor_output_dir(candidate: str | Path) -> Path:
    """把**相对**输出目录锚到数据根, 调用方显式给定的绝对目录原样尊重。

    与 :func:`resolve_data_path` 是两种政策, 别混用:

    - ``resolve_data_path`` 是**封闭**政策: 越出数据根即 ``ValueError``。用
      在"落盘文件名由调用方给"的场合 (``--output`` 指向的完整路径), 因为
      那时越界就等于写到不该写的地方。
    - 本函数是**开环**政策: 绝对目录一律放行。理由是**公开 API 契约** ——
      ``BestCrossMatch.submit_upload_job(output_dir=...)`` 的 output_dir 是
      公开形参 (``references/client-api-reference.md`` 列了该入口), 用户
      明确指定任务队列写到哪个目录是它的正常用法 (临时目录、独立数据盘),
      拿封闭政策套上去等于用一次加固换掉一条公开能力。
      该路径上没有用户给的文件名 (``job_id`` 由时间戳+随机段内部生成),
      所以也不存在 ``..`` 上溯写到别处的逃逸面。

    真正要消掉的不一致是**相对**路径随 CWD 漂移: 同一条命令在两个目录下
    执行, 相对 output_dir 会落到两个不同位置, 而数据根是配置里唯一的
    落盘基准。相对路径一律锚到它。

    Args:
        candidate: 调用方给出的输出目录 (相对或绝对)。

    Returns:
        绝对路径。相对入参锚到数据根, 绝对入参 expanduser 后原样返回。
    """
    path = Path(candidate).expanduser()  # expanduser: 用户习惯写 "~/data", 不展开会落错地方
    if path.is_absolute():  # 绝对路径是调用方的显式选择, 不做越界判定
        return path
    return data_root() / path  # 相对路径锚到数据根: 不再随 CWD 漂移


def resolve_data_path(candidate: str | Path) -> Path:
    """把用户给的路径限定在数据根内 (起点校验, 越界即 ValueError)。

    与 :func:`resolve_within` 的分工: 后者把"裸文件名"锚进某个基准目录
    (终点校验); 本函数校验"目录本身"是否越出数据根 (起点校验)。P1-5/P1-6
    复过的现: ``Best.download`` 的 ``output_dir`` 与 ``python -m src --output``
    的父目录由调用方直接指定, 终点校验 (``resolve_output_path`` 等) 的基准
    随之成了用户给定的值, 防逃逸被参数化绕过。

    Args:
        candidate: 用户传入的相对或绝对路径 (目录或文件均可)。

    Returns:
        解析后的绝对路径, 保证位于数据根之内 (或就是数据根本身)。

    Raises:
        ValueError: 解析结果越出数据根 (含 ``..`` 上溯与符号链接逃逸)。
    """
    root = data_root()  # 每次现取: 环境变量可能在进程运行期被改, 不缓存
    p = Path(candidate).expanduser()  # 展开后再判绝对/相对: "~/x" 不是绝对路径, 不展开会锚错根
    # 相对路径锚定到数据根; 绝对路径原样解析后再校验, 两路都必须过
    # is_relative_to 判定 (root != resolved 是"恰好等于根"的放行)
    resolved = (p if p.is_absolute() else root / p).resolve()  # 相对路径锚到数据根, 绝对路径原样解析: 两路都得过越界判定
    if root != resolved and root not in resolved.parents:  # 恰好等于根是放行口: 数据根本身当然合法
        raise ValueError(
            f"路径越出数据根 ({root}), 已拒绝: {resolved}; "  # 报错带真实根与解析结果: 用户据此能看出是哪一段越界
            f"如需其它目录请设置 {DATA_ROOT_ENV}"  # 报错给出合法出路: 比只说拒绝有用得多
        )
    return resolved


def validate_external_url(url: str) -> str:
    """校验下载 URL: 仅 https + 仅官方主机 + 无内嵌凭据 + 非 IP 字面量。

    P1-10 复过的现: ``FileJob.url`` 全程直连 — 无 scheme 白名单、无主机
    白名单、未禁重定向、无内网/链路本地地址拦截, 响应体被完整写盘并作为
    "下载成功"产物返回, 构成 SSRF 原族 (如 ``https://169.254.169.254/``
    云元数据口、``https://10.0.0.1/`` 内网服务)。对照 ``src/tap/client.py``
    的 ``_validated_tap_url`` (只校 scheme/netloc/凭据, 不含主机白名单) —
    团队知道该做, 只是没在下载栈做; 这里是下载栈的单一入口校验。

    Args:
        url: 待下载文件的 URL。

    Returns:
        strip 后的原 URL (校验通过才返回)。

    Raises:
        ValueError: scheme 非 https、含内嵌凭据、无主机、主机是 IP 字面量,
            或主机不在 :data:`ALLOWED_DOWNLOAD_HOSTS` 白名单内。
    """
    raw = str(url).strip()  # 去空白再解析: 前后空格会让主机名比对失配
    parsed = urlparse(raw)  # 拆组件而非正则: 各字段都有标准解析, 自己写正则必漏边界
    if parsed.scheme != "https":  # https 之外全拒: 明文下载会把响应内容暴露在链路上
        raise ValueError(f"only https download URLs are allowed: {url!r}")
    if parsed.username or parsed.password:  # 禁内嵌凭据: URL 里的口令会随日志与异常一起外泄
        raise ValueError(f"download URL must not embed credentials: {url!r}")
    host = (parsed.hostname or "").lower()  # 转小写: 主机名大小写不敏感, 不归一会误拒
    if not host:  # 无主机即无可比对: 必须在进白名单比对之前先挡掉
        raise ValueError(f"download URL has no host: {url!r}")
    try:
        ipaddress.ip_address(host)  # 试判 IP 字面量: 成功即说明是内网或元数据口形态, 一律拒
    except ValueError:
        pass  # 不是 IP 字面量, 继续走主机名白名单
    else:
        # IP 字面量一律拒绝: 白名单只放官方域名, IP 形态连白名单比对都不必
        raise ValueError(f"IP literal hosts are not allowed: {host!r}")
    if host not in ALLOWED_DOWNLOAD_HOSTS:  # 白名单是唯一放行口: 主机名对不上就没有第二条例外
        raise ValueError(
            f"download host {host!r} is not the BEST data host "  # 报错点明实际主机: 拼错域名与 SSRF 尝试要能一眼分开
            f"(allowed: {sorted(ALLOWED_DOWNLOAD_HOSTS)})"  # 顺带列出允许值: 修正拼写不必去翻源码
        )
    return raw  # 返回原串而非重组串: 白名单只把关, 不改写调用方给的 URL


def to_csv(records: list[dict], filepath: str, fieldnames: Optional[list[str]] = None) -> str:
    """把记录列表导出为 CSV (原子写 + BOM + 公式消毒 + 并集表头)。

    Q-58: 表头取所有记录键的并集, 异构行 (某源缺一个波段) 保住自己的列,
    而不是静默丢列或抛 ``ValueError``。
    Q-06: 每个值先过 CSV 消毒器才落盘 (公式注入防护)。

    A4 空导出语义 (取代旧的 0 字节文件行为): 空 ``records`` 时不再产出 0
    字节文件 — 那让"空导出"与"写出失败"在下游不可区分。空导出 = 只写
    表头, 表头来源为调用方显式传入的 ``fieldnames`` (空列表没有
    ``records[0]`` 可推头); 未提供 ``fieldnames`` 时显式抛 ``ValueError``,
    拒绝产出含义不明的空文件。

    Args:
        records: 记录列表; 为空时必须提供 ``fieldnames``。
        filepath: 目标文件路径。
        fieldnames: 可选, 显式声明的表头列; 非空 ``records`` 时作为表头
            前缀, 记录中新出现的键仍按并集追加 (Q-58 不丢列)。

    Returns:
        落盘文件路径 (字符串)。

    Raises:
        ValueError: ``records`` 为空且未提供 ``fieldnames``。
    """
    path = Path(filepath)  # 规整成路径对象: 原子写吃路径或字符串都行, 统一在此转一次
    # A4: 表头来源 = fieldnames (显式声明) + records 键并集 (Q-58)
    columns: list[str] = list(fieldnames) if fieldnames else []  # 表头起点: 显式列名在前, 记录里冒出的键按并集追加
    if not records and not columns:  # 两条同时空才抛: 有 fieldnames 的空导出是合法形态 (只写表头)
        # A4: 空列表且无 fieldnames 推不出表头 — 写 0 字节文件会让"空导出"
        # 与"写出失败"不可区分, 显式失败并要求调用方点名列
        raise ValueError(
            "to_csv: 空记录列表必须显式提供 fieldnames 定义表头 "  # 报错说清空导出的确切含义: 只写表头, 不是 0 字节文件
            "(空导出 = 只写表头, 表头来源为 fieldnames)"  # 同一条消息的后半: 顺带告诉调用方该怎么改调用
        )
    for record in records:  # 逐记录并键: 异构行的独有列正是要保住的, 不能只取首条
        for key in record:  # 只看键不看值: 表头并集与记录内容无关
            if key not in columns:  # 追加前查重: 否则同一列会在表头里重复出现
                columns.append(key)  # 按出现次序追加: 显式列名在前, 新键附在后面
    buffer = io.StringIO()  # 先在内存里拼: 落盘只做一次原子写, 中途失败不留半份文件
    if columns:  # 无表头就不建 writer: 构造时缺列名会直接抛
        writer = csv.DictWriter(buffer, fieldnames=columns, extrasaction="ignore")  # extrasaction="ignore": 表头说了算, 记录里多出的键不炸
        writer.writeheader()  # 表头先写: 即使记录为空, 下游也能凭表头认出列语义
        for record in records:  # 逐记录写出: 每行都过一遍消毒器
            # Q-06: 逐值消毒 (=/+/-/@ 开头的公式串转义), 防 CSV 公式注入
            writer.writerow(sanitize_row(record))
    # IO 点: utf-8-sig (Excel 直接打开中文不乱码, Q-60) + 原子落盘
    return str(atomic_write_text(path, buffer.getvalue(), encoding="utf-8-sig"))  # utf-8-sig: Excel 开中文不乱码 (Q-60), 与 to_json 的 utf-8 有意不同


def to_json(records: list[dict], filepath: str, pretty: bool = True) -> str:
    """把记录列表导出为 JSON (原子写, ensure_ascii=False 保留中文)。

    Args:
        records: 记录列表 (可 JSON 序列化的 dict)。
        filepath: 目标文件路径。
        pretty: True 时缩进 2 空格, False 时紧凑单行。

    Returns:
        落盘文件路径 (字符串)。
    """
    path = Path(filepath)  # 规整成路径对象: 与 CSV 出口保持同一形态
    indent = 2 if pretty else None  # 缩进可关: 紧凑单行更小, 缩进两格更便于人工核查
    content = json.dumps(records, indent=indent, ensure_ascii=False)  # ensure_ascii=False: 中文直接落盘, 不转 \uXXXX
    # IO 点: 原子落盘 (utf-8; JSON 的消费方含 envelope, 不加 BOM)
    return str(atomic_write_text(path, content, encoding="utf-8"))
