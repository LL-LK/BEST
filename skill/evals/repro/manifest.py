# -*- coding: utf-8 -*-
"""evals.repro.manifest — E6 固定清单 (frozen manifest) 八项指纹组装与校验。

能力边界: 开跑前把"用的是哪份数据/哪份代码/哪个模型/哪段提示语/什么温度"
全部算成 sha256 指纹落盘; **任一项缺失 → 本 run 无效 (阻断项)**。
边界: 只算指纹与校验, 不跑查询 (canary 探针的原始数据由调用方注入,
本模块只负责把规范化结果算成指纹 — 联网与否是 lane 的事)。

白盒锚点: docs/eval-E6-reproducibility.md §3 (八项固定清单);
ops/verify_tree_integrity.py (skill 指纹的排除口径 — 复用不另立)。

职责: E6 的"这次跑的是什么"的答案 —— 把数据/代码/模型/提示语/工具 schema/
  评测数据/采样/执行环境八项全部算成 sha256 指纹组装成 frozen manifest,
  缺一项就判这次运行无效。
所属实验: E6 可复现与效率 (32 任务 + R0 路实跑); 八项的定义与阻断口径
  真值是 docs/eval-E6-reproducibility.md §3 与 §8.2, skill 指纹的排除目录
  直接复用 ops/verify_tree_integrity.py 的同一套, 不另立一份。
对外接口: build_manifest(...) 组装八项 + environment; validate_manifest
  返回阻断项列表 (空 = 有效); save_manifest 先校验后落盘, load_manifest
  读回; 四个指纹件 sha256_text / sha256_file / skill_fingerprint /
  canary_fingerprint / task_set_fingerprint 可单独调用与单测。
依赖与数据流: 输入 = 调用方注入的 canary 探针行 (联网路取真实回包、回放
  路取快照行) 与环境实参; 产物 = manifest 字典与落盘的 JSON, 供
  evals/repro/r0_lane.py 与 run_e6.py 消费。本模块自身不跑查询 ——
  联网与否是 lane 的事, 这里只负责把结果算成指纹。
关键契约与不变量: 纯离线 (只读本地文件算哈希, 不发任何请求); 同一份
  输入重复组装必须得到逐字段相同的八项指纹 —— 指纹是"可复现"的锚点,
  它自己飘了就什么都没锁住; 零跨实验 import, 只经 paths 兄弟导入拿
  skill 根, 与其它实验的等价性由 evals/equivalence/ 的断言守护。
陷阱与边界: 本仓无 .git 且禁版本号, 所以 skill 只能用内容指纹而不是  # 清单是 E6 的可复现基线: 任务/夹具/阈值三者一起冻结
  commit 号 (文档 §3 #2 坑位 1), 代价是任何一次代码改动都会让历史
  manifest 全部失效 —— 这是刻意的, "同代码"必须真的同代码。模型名出现
  latest 之类别名即阻断: 别名等于没钉版本, 今天的 latest 和下个月的
  latest 不是同一个模型, 而报告里看不出来。canary 探针不足 5 个直接抛  # 清单一节的抬头: 说清这份清单冻结了什么
  (fail-closed), 少一个探针会让"数据没变"变成"没查到"这种无法证伪的话。
"""  # 任务集路径与命名约定绑在一起: 改名即换基线
from __future__ import annotations

# 标准库: 哈希 / JSON / 路径 / 时间 / 环境变量
import hashlib  # 禁浮动 tag: 复跑拿到不同模型就不叫复现
import json
import os  # 只收存在的任务: 写了不存在的任务, 跑批成功只是假象
import sys
from datetime import datetime, timezone  # 只收已存在的任务: 清单里写不存在的任务等于把"跑批成功"变成假象
from pathlib import Path

# 本地: 中立载体 (skill 根; paths 是 evals/ 下的兄弟裸导入模块 — 挂 evals/)

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # evals/ (paths 兄弟导入)
# 本地: 兄弟裸导入的 skill 根 (指纹计算的树入口)
from paths import SKILL_DIR  # noqa: E402

REPRO_DIR = Path(__file__).resolve().parent  # 本实验根: 任务/夹具/清单都挂在它下面
TASKS_DIR = REPRO_DIR / "tasks"  # 任务集路径: 与 tasks/*.yaml 的命名约定绑在一起

# 八项固定项的键 (缺一即阻断; 顺序即文档 §3 的序号)
REQUIRED_ITEMS = (  # 每条任务必须带齐这几段: 少一段就没法判它跑没跑对
    "best_data", "skill", "model", "system_prompt",  # canary 取自回放快照: 离线跑批也要有跨轮一致的指纹面
    "tool_schema", "eval_data", "sampling", "execution",
)  # 只收存在的任务: 写了不存在的任务, 跑批成功只是假象

# 禁用模型别名 (命中即阻断项 — 别名等于没钉版本)
_FORBIDDEN_MODEL_TOKENS = ("latest", "-latest", ":latest")  # "latest" 之类浮动 tag 一律禁: 复跑拿到不同模型就不叫复现

# skill 指纹扫描根与排除 (文档 §3 #2; 排除口径复用 verify_tree_integrity)
SKILL_SCAN_ROOTS = (  # drift_state 由 lane 填: R0 无模型, 恒为 STABLE
    "src", "ops", "evals", "contracts", "references", "static", "agents",
    "SKILL.md", "README.md", "architecture.md", "manifest.yaml",  # drift_state 由 lane 填: R0 无模型, 恒为 STABLE
)
SKILL_EXCLUDE_DIRS = {"temp", "__pycache__", ".workbuddy-ai", ".pytest_cache",  # 排除目录: 缓存与运行时数据一变指纹就变, 那是噪声不是漂移
                      ".ruff_cache", ".git", "best_data", ".checkpoints",
                      ".progress", ".logs", "runs"}  # 清单内容寻址: 任一字段变了指纹就变, 复跑对不上立刻暴露
SKILL_EXCLUDE_SUFFIX = (".pyc", ".pyo")  # 排除字节码产物: 同上


def sha256_text(text: str) -> str:  # 清单内容寻址: 任一字段变了指纹就变, 复跑对不上立刻暴露
    """文本指纹 (sha256, 带算法前缀 — 与 trace/manifest 口径一致)。

    作用: 短文本的指纹。关键参数 text 是待算文本。Returns: "sha256:" 前缀
    的十六进制串。抛什么: 不抛。
    """
    # 带算法前缀是刻意与不带前缀的裸 hex 区分: 将来换算法时, 报告里一眼
    # 能看出哪批指纹不是 sha256 算的, 不会出现两批数被直接对比
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    """文件内容指纹 (sha256, 分块读防大文件爆内存)。  # 空清单即抛: 空跑批跑绿是最危险的假象

    作用: 文件的指纹。关键参数 path 是文件路径。Returns: "sha256:" 前缀  # 空清单即抛: 空跑批跑绿是最危险的假象
    的十六进制串。抛什么: 文件不存在时由 open 抛 FileNotFoundError。
    """  # 固定时间戳: 清单里的时间若用真实时钟, 每次跑都不一样
    digest = hashlib.sha256()  # 分块读: 大文件一次读入会把内存吃满
    # 二进制分块读: 文本模式会做换行转换, Windows 上 CRLF 会被读成 LF,
    # 同一份文件在两个平台上会算出两个指纹, 那等于没锁
    with path.open("rb") as handle:  # 清单逐条写盘: 落在 temp/, 不污染工作区
        for chunk in iter(lambda: handle.read(65536), b""):                           # 分块读不整读: 大文件一次读入会把内存吃满, 指纹是每次跑批都要算的
            digest.update(chunk)                                                             # 逐块喂摘要: 换块大小不改变最终摘要, 只影响内存峰值
    return "sha256:" + digest.hexdigest()


def skill_fingerprint(root: Path = SKILL_DIR) -> str:  # 时间戳固定: 用真实时钟会让每次跑的清单都不同
    """Skill 内容指纹: sha256(排序后的 "相对路径|大小|内容sha256" 拼接)。

    无 .git + 禁版本号 → 只能用内容指纹 (文档 §3 #2 的坑位 1)。

    作用: 锁住"跑的是哪份代码"。关键参数 root 是扫描根 (默认仓根)。
    Returns: 指纹串。抛什么: 根下什么都没有时也会返回空 entries 的指纹 ——  # 指纹算在写盘之前: 落盘后重算就自证循环了
    空指纹同样是有效信号 (代码被清空), 由 validate 层按缺项处理。
    """
    entries: list[str] = []                                                       # 先攒条目再统一排序: rglob 的遍历顺序依赖文件系统, 直接拼会不可复现
    for rel in SKILL_SCAN_ROOTS:  # 指纹算在写盘之前: 落盘后重算就成了自证循环
        path = root / rel                                                                   # 相对路径定位: 指纹要锁的是仓内内容, 绝对路径随机器变
        # SKILL_SCAN_ROOTS 里混了目录与单文件 (SKILL.md/README.md), 分开
        # 处理才不会在单文件上跑出空 rglob
        if path.is_file():                                                    # 单文件与目录分开处理: 扫描根里混了目录与单文件, 在单文件上跑 rglob 会得空
            entries.append(f"{rel}|{path.stat().st_size}|{sha256_file(path)}")  # 单文件也算一份: 清单允许直接列文件
            continue
        if not path.is_dir():                                                           # 不是目录也不是文件即跳过: 扫描根登记错时静默忽略会把缺口藏起来
            continue
        for child in sorted(path.rglob("*")):  # 目录递归要排序: 遍历顺序不是契约, 排序后才可复现
            if child.is_dir():                                                     # 子目录本身不算条目: 只有文件进指纹, 目录条目会让同一份代码算出不同结果
                continue
            # 排除目录按"除文件名外的任一段"判: 只判首段会漏掉 src/x/__pycache__,
            # 缓存文件一被扫进去指纹就随运行时刻变化, manifest 立刻失效
            rel_parts = child.relative_to(root).parts                               # 取相对路径分段: 排除规则要按路径段判, 只看首段会漏掉嵌套里的缓存目录
            if any(part in SKILL_EXCLUDE_DIRS for part in rel_parts[:-1]):  # 排除目录按路径段判: 只看目录名会漏掉嵌套里的缓存
                continue
            if child.suffix in SKILL_EXCLUDE_SUFFIX:                                      # 按后缀排除: 缓存与临时文件一进指纹, 清单就随运行时刻变化
                continue
            # 相对路径用 posix 统一分隔符: 路径本身进了指纹, Windows 的
            # 反斜杠会让同一份代码在不同平台上算出不同指纹
            rel_str = child.relative_to(root).as_posix()                 # 统一用 posix 分隔符: 路径本身进了指纹, Windows 的反斜杠会让两平台算出两个值
            entries.append(f"{rel_str}|{child.stat().st_size}|{sha256_file(child)}")  # 每份都带大小+内容哈希: 只比大小会把等长不同内容放过
    # 排序后再拼: rglob 的遍历顺序依赖文件系统, 不排序则同一份代码会因
    # 目录创建顺序不同而算出不同指纹
    return sha256_text("\n".join(sorted(entries)))


def canary_fingerprint(probe_rows: list[list[dict]]) -> str:
    """BEST 数据版本 canary 指纹: 5 探针规范化结果的 sha256。

    Args:
        probe_rows: 5 个探针 (ps1/gaia_dr3_18/scr_galah/stripe82/xpsp 各一条
            定参锥搜 + count) 的行列表 (调用方注入 — 联网路取真实回包,
            回放路取快照行)。

    Returns:
        ``bestfp:sha256:<64hex>``; 输入不足 5 个探针即抛 (fail-closed)。
    """
    # 探针数必须正好 5: 少一个探针等于少一种星表的交叉验证, "数据没变"就
    # 退化成"这一种表没查到差异"; 多一个则说明调用方拼错了顺序
    if len(probe_rows) != 5:  # 探针数必须是 5: 数量变了说明回放面被改, 不是同一套基线
        raise ValueError(f"canary 必须 5 个探针, 实得 {len(probe_rows)}")
    # 整行 (键+值) 规范化: 只指纹列名会把"同列名不同数值"的数据漂移放掉 —
    # canary 的职责就是抓 BEST 数据版本变化 (E6 §3 #1 / §8.2 #4)。
    # sort_keys 保证行内字段序不影响指纹, default=str 兜住 Decimal/日期
    canonical = json.dumps(  # 规范化后再算指纹: 键序与分隔符都会影响字节流
        probe_rows, sort_keys=True, ensure_ascii=False, default=str,     # 键排序后序列化: 行内字段序不影响指纹, default=str 兜住 Decimal 与日期
    )
    # 前缀 bestfp: 而非 sha256: —— canary 指纹与 skill 指纹走的是不同的
    # 探针与语义, 混用同一个前缀会让报告里两列看起来可比而其实不可比
    return "bestfp:sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def task_set_fingerprint(tasks_dir: Path = TASKS_DIR) -> str:
    """任务集指纹: 32 个 REPRO yaml 排序拼接的 sha256 (改一字即不可比)。

    作用: 锁住"跑的是哪批题"。关键参数 tasks_dir 是任务目录。
    Returns: 指纹串。抛什么: 目录里一个 REPRO-*.yaml 都没有时抛
    FileNotFoundError —— 空任务集算出的指纹和"题目被清空"无法区分。
    """
    entries = []                                                                            # 条目先攒后排序: 目录遍历顺序不是契约, 排序后才可复现
    # 排序 + 固定通配: 只收 REPRO-*.yaml, 让无关文件 (README、缓存) 不进
    # 指纹, 否则加一行说明文档就会让整批历史 run 不可比
    for path in sorted(tasks_dir.glob("REPRO-*.yaml")):  # 只取 REPRO-*.yaml: 混进别的文件会让指纹随目录杂物漂移
        entries.append(f"{path.name}|{sha256_file(path)}")
    if not entries:  # 空任务集即抛: 空跑批"跑绿"是最危险的假象
        raise FileNotFoundError(f"任务集缺失: {tasks_dir}")
    return sha256_text("\n".join(entries))


def build_manifest(
    *,                                                                                  # 强制关键字传参: 清单有二十多项, 位置传参必然错位且错位不可见
    lane: str,                                                                            # 四路对照的标识: 进清单后四路结果才分得开, 混算就无从归因
    repeat: int = 5,                                                             # 重复次数是一致率的分母: 缺省 5 与口径文档一致, 少一次会让区间宽到没结论
    canary_before: str,                                                                 # run 前的数据版本指纹: 与 after 成对才谈得上有无漂移
    canary_after: str,
    drift_state: str = "STABLE",
    model_id: str = "opaque",
    provider: str = "opaque",
    endpoint: str = "",
    prompt_text: str = "",
    prompt_template_id: str = "",
    tools_schema_fp: str,                                                         # 工具面指纹: 与 exposed 分开锁, 两者不一致说明暴露层改过工具定义
    exposed_schema_fp: str,                                                                # 对外暴露面: 与内部工具面分开, 改一侧要能看出是哪侧变了
    snapshot_id=None,
    snapshot_manifest_fp=None,                                                              # 快照自身的清单指纹: 快照被动过时它会变, 是回放路的锚
    temperature: float = 0.0,                                                     # 0.0 是 E6 的前提: 有温度就有采样随机性, 一致率类指标随之失去意义
    top_p: float = 1.0,
    max_tokens=None,
    seed_requested=None,
    seed_honored: bool = False,                                                      # 默认 False: 没有证据说服务端兑现了种子, 不得默认成 True
    run_date=None,                                                                        # 显式传入而非取当天: 清单要可复算, 真实时钟写进去就不可比
    rate_limit_seconds: float = 2.0,                                                         # 节流秒数进清单: 不含节流的耗时分位只有配上它才可解释
) -> dict:
    """组装八项固定清单 (+ 运行环境变量) — 键名即文档 §3 的八项。

    Args:
        lane: R0|R1|R2|R3 (四路对照, §2.1)。
        canary_before/after: run 前后各算一次的数据版本指纹。
        drift_state: STABLE | DRIFTED (DRIFTED 必须声明, 不判 E6 失分)。
        model_id: 必须钉具体版本串; latest 别名在 validate 层阻断。

    Returns:
        八项 + environment 的 manifest dict (可 JSON 落盘)。
    """
    now = datetime.now(timezone.utc)                                                      # 只取一次时钟: 同一份清单里多处现取时间会算出两个不同时间戳
    # 提示语为空就留空指纹而不是空串的哈希: 显式空串哈希与"没传提示语"
    # 在报告里长得几乎一样, 留空能让 validate 层一眼看出缺项
    prompt_fp = sha256_text(prompt_text) if prompt_text else ""
    # 键名与顺序即文档 §3 的八项, 不可改名也不可调序: 报告与跨 run 的
    # manifest 比对都是按这两个维度做的
    return {
        "best_data": {
            "method": "canary_fingerprint",
            "canary_queries": 5,
            # 前后两个指纹都要留: 只存一个就无法区分"数据在跑之前就变了"
            # 与"数据在跑的过程中变了", 而这两者的处置完全不同
            "fingerprint_before": canary_before,
            "fingerprint_after": canary_after,
            # DRIFTED 必须显式声明而不判失分: 报告期数据更新是外部事实,
            # 藏起来才是造假 (文档 §3)
            "drift_state": drift_state,
            "canary_rerun_on_mismatch": True,
        },
        "skill": {
            "fingerprint": skill_fingerprint(),
            "method": "sha256(排序后的 '相对路径|大小|内容sha256' 拼接)",
            "scan_roots": list(SKILL_SCAN_ROOTS),
            "exclude": ["temp", "__pycache__", "*.pyc", ".workbuddy-ai"],
        },
        "model": {
            "scope": "external",
            "model_id": model_id,
            "provider": provider,
            "endpoint": endpoint,
            # opaque 是诚实声明而非占位: 本仓拿不到权重发布日期, 写一个
            # 猜出来的日期比写 opaque 危险得多
            "weights_snapshot_date": "opaque",
            "reasoning_mode": False,
        },
        "system_prompt": {
            "fingerprint": prompt_fp,
            # 字节数与指纹并列: 指纹看不出提示语有多长, 报告要能一眼判断
            # "换了个提示语" 是改了几十字还是整段重写
            "bytes": len(prompt_text.encode("utf-8")) if prompt_text else 0,
            "template_id": prompt_template_id,
        },
        # 代码侧与暴露侧分列: 被测链路看到的 schema 可能与仓库里的不一致
        # (裁剪/重命名/裁字段), 合成一个指纹就把这种差异洗掉了
        "tool_schema": {"code_side": tools_schema_fp, "exposed_side": exposed_schema_fp},
        "eval_data": {
            "task_set": "REPRO-01..32",
            "task_set_fp": task_set_fingerprint(),
            "snapshot_id": snapshot_id,
            "snapshot_manifest_fp": snapshot_manifest_fp,
            # 恒空列表: 任务里出现相对时间表述 (今天/最近/本月) 会让同一
            # 个任务在不同日期指向不同数据, 校验层据此阻断
            "relative_time_tasks": [],
        },
        "sampling": {
            "temperature": temperature,
            "top_p": top_p,
            "max_tokens": max_tokens,
            # requested 与 honored 分列: 请求了 seed 不等于服务端认了,
            # 合成一个字段就看不出来了
            "seed": {"requested": seed_requested, "honored": seed_honored},
        },
        "execution": {
            "run_date": run_date or now.date().isoformat(),
            "run_started_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "timezone": "Asia/Shanghai",
            "crossed_utc_midnight": False,
            "lane": lane,
            # repeat=5 是默认: N=5 下 Wilson 区间已经很宽 (§5.5), 再少就
            # 连"大致可复现"都说不出来, 报告必须同时给区间
            "repeat": repeat,
        },
        "environment": {
            "rate_limit_seconds": rate_limit_seconds,
            # 缓存与并发恒定写死: 这两项一变, 墙钟与请求数就没法跨 run 比,
            # 所以即便实际开着也要如实记 False/1 由调用方保证
            "http_cache_enabled": False,
            "concurrency": 1,
            "python_version": sys.version.split()[0],
            "requests_version": _requests_version(),
            # 代理与令牌只记"有没有", 不记值: manifest 是要落盘留痕的
            "proxy_enabled": bool(os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY")),
            "best_api_token_present": bool(os.environ.get("BEST_API_TOKEN")),
        },
    }


def _requests_version() -> str:
    """requests 版本 (装了什么报什么; 缺失报 absent — 不猜)。

    作用: 记录回放底座所依赖的库版本。关键参数: 无。Returns: 版本串,
    装不上时返回 "absent"。抛什么: 不抛, 任何异常都归到 absent。
    """
    try:
        # 第三方: 异常类型判定 (skill 指纹扫描的容错面)
        import requests

        return requests.__version__
    except Exception:  # pragma: no cover - 环境缺 requests 时
        # 报 absent 而不是空串: 空串在报告里看不出是"没装"还是"忘了填"
        return "absent"


def validate_manifest(manifest: dict) -> list[str]:
    """校验固定清单; 返回阻断项列表 (空 = 有效)。

    阻断项 (文档 §8.2): 八项任缺 / 模型 latest 别名 / temperature 未固定 /
    DRIFTED 未声明 / 任务集含相对时间表述。
    """
    problems: list[str] = []                                                           # 阻断项先攒后判: 一次校验要给出全部问题, 早返回会让人只修第一处
    # 逐项查八项: 缺项与空值都算缺 —— 空 dict/空串同样是"没写",
    # 只判 key 存在会让空壳 manifest 通过校验
    for item in REQUIRED_ITEMS:                                                           # 逐项查八项: 缺项与空值都算缺, 只判键存在会让空壳清单通过
        if item not in manifest or not manifest[item]:                                 # 非空也要求: 空 dict 与空串同样是「没写」, 不该与真值同权
            problems.append(f"manifest_missing:{item}")
    # 缺项时不再往下判: 八项不齐的 manifest 里取子键只会抛 KeyError,
    # 把一条清晰的阻断项变成一次崩溃 (铁律 5 禁 fail-open)
    if not problems:                                                           # 八项不齐就不再往下判: 取子键只会抛 KeyError, 把清晰阻断项变成一次崩溃
        model_id = str(manifest["model"].get("model_id", ""))
        # 转小写再匹配: 别名可能写作 Latest / LATEST, 大小写不同但同样
        # 意味着"没钉版本"
        if any(token in model_id.lower() for token in _FORBIDDEN_MODEL_TOKENS):  # 先转小写再匹配: 别名可能写作 Latest 或 LATEST, 大小写不同但同样没钉版本
            problems.append(f"model_alias_forbidden:{model_id}")
        # 只认 None 为未固定: temperature=0.0 是完全合法的确定性设置,
        # 用 `if not temperature` 判会把它误报成没固定
        if manifest["sampling"].get("temperature") is None:
            problems.append("temperature_not_fixed")
        best = manifest["best_data"]
        # 白名单而非黑名单: 新增一个 drift_state 拼写 (DRIFT) 会被这里
        # 拦住, 而不是被当成合法值静默通过
        if best.get("drift_state") not in ("STABLE", "DRIFTED"):
            problems.append(f"drift_state_invalid:{best.get('drift_state')}")
        if manifest["eval_data"].get("relative_time_tasks"):
            problems.append("relative_time_tasks_present")
        if manifest["execution"].get("lane") not in ("R0", "R1", "R2", "R3"):
            problems.append(f"lane_invalid:{manifest['execution'].get('lane')}")
    return problems


def save_manifest(manifest: dict, path: Path) -> None:
    """落盘 (JSON, ensure_ascii=False); 先校验后写 (无效清单不落盘)。

    作用: 持久化一次运行的固定清单。关键参数 manifest/path 是清单与目标
    路径。Returns: None。抛什么: 校验不过时抛 ValueError, 目录不可写时
    由 mkdir/write_text 自抛。
    """
    # 先校验后写: 无效清单落盘等于制造一份"看起来跑过"的证据, 之后
    # 谁读到它都会以为这次 run 是合规的
    problems = validate_manifest(manifest)                                                 # 先校验后写: 无效清单落盘等于制造一份「看起来跑过」的证据
    if problems:                                                                            # 校验不过即抛: 拒绝落盘, 不让无效清单有机会被后续读到
        raise ValueError(f"固定清单无效, 拒绝落盘: {problems}")
    path.parent.mkdir(parents=True, exist_ok=True)                                # 递归建目录: 落点由 lane/task 决定, 目录布局不该推给每个调用点
    # 缩进 2 + 不转义中文: 清单是给人读留痕的, \uXXXX 形态没法复核
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def load_manifest(path: Path) -> dict:
    """读固定清单; 缺失/损坏即抛 (回放侧不猜默认值)。

    作用: 读回一次运行的固定清单。关键参数 path 是清单路径。
    Returns: 清单字典。抛什么: 文件不存在抛 FileNotFoundError, 内容不是
    合法 JSON 抛 JSONDecodeError — 两者都不静默退回空清单。
    """
    if not path.is_file():                                                     # 缺失即抛而不返回空: 回放侧拿到空清单会把这次 run 当成裸跑, 指标照样出得来
        # 显式报错而不是返回 {}: 回放侧拿到空清单会以为"没有固定项",
        # 于是把这次 run 当成没跑过 manifest 的裸跑, 指标照样出得来
        raise FileNotFoundError(f"固定清单缺失: {path}")
    return json.loads(path.read_text(encoding="utf-8"))
