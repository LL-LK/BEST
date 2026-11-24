# -*- coding: utf-8 -*-
r"""ops.audit.env_scope — 「哪些 env 读取算**部署期配置输入**」的唯一真源 (归类面)。

覆盖面与归类面是两个不同的问题, 混在一起就会出现两条门禁对同一个键各说各话:

- **覆盖面** (哪些 ``.py`` 要被扫): 真源是 :mod:`scan_roots`, 黑名单口径, 全仓。
- **归类面** (扫到的读取点里哪些该登记进 ``.env.example``): 真源是**本模块**。

2026-10-05 W1 实测的分歧: ``verify_crossrefs.py`` §7 按"全仓扫到的读取点都必须
登记"判红 ``PYBEST_RUN_LIVE`` / ``HTTP_PROXY`` / ``ASTRO_BEST_DRAWIO_EXE`` 等 6 个键,
而 ``test/unit/meta/test_env_ssot_covers_all_code_reads.py`` 已把同一批键逐条裁定为
**非部署期输入**并断言它们**不许**登记进 ``.env.example``。同一批键, 一条要登记、
一条不许登记 —— 两道判据不可能同时对。本模块就是把这个裁定抽成唯一真源: 门禁 §7 读
:data:`EXCLUDED_ONLY` 扣账, 单测用它反查集合相等, 两边不再各持一份。

============================  ====================================================
导出                          口径 (改任何一项前先读这一列)
============================  ====================================================
:data:`EXCLUDED_SCOPE`        按路径前缀划出的"非部署期读取面"。消费方据此**推导**
                              哪些键属排除面; 推导结果必须与 :data:`EXCLUDED_ONLY`
                              **集合相等**, 由单测监督
:data:`EXCLUDED_ONLY`         已被逐条裁定为非部署期输入的 env 键 → 裁定理由。
                              门禁 §7 据此扣账, **但只扣已裁定的那几个** ——
                              新出现的同类键仍然判红 (漏裁定会红, 不是静默放过)
============================  ====================================================

**为什么键必须在排除面被读到、又在 runtime 面读不到时登记**: 只按目录划界会漏掉
"排除面读、runtime 面没人读"的事实, 那正是这 6 个键的形态 (测试开关 / 系统代理 /
本机渲染路径)。它们登记进 ``.env.example`` 是**误导** (照它配不改变 skill 行为),
不登记又必须有人在册说明为什么 —— 所以是"目录 + 在册键清单"两层, 而不是一层。

依赖: 纯数据 (只用标准库 ``from __future__``), 不读文件、不 import 被判定的代码,
因此门禁脚本与单测都能同口径导入它, 且不产生导入副作用。
"""
from __future__ import annotations

# 不构成"部署期配置输入面"的目录前缀 (逐条理由)。按路径前缀判: 目录内的一切 .py
# 一律不算部署期读取点。**这是归类, 不是覆盖面** —— 这些目录下的 .py 仍进门禁的
# 其余判据 (净行预算 / 注释规范 / 交叉引用), 覆盖面真源另有 scan_roots。
EXCLUDED_SCOPE: tuple[str, ...] = (
    "test/",        # 测试自身开关 (PYBEST_RUN_LIVE): 配它不改变 skill 的部署行为
    "evals/",       # 评测复现元数据 (HTTP_PROXY/BEST_API_TOKEN): 只如实记录, 非部署期输入
    "docs/",        # 本机 draw.io 渲染路径 (ASTRO_BEST_DRAWIO_EXE 等): 制图工具链, 非 skill 运行时
    # 2026-10-07 新增。**刻意只圈 ops/audit/, 不圈整个 ops/**: ops/ 下同时住着治理
    # 工具链与一个真运行时入口 (ops/astro_best_cli.py, 它真读 ASTRO_BEST_PASSWORD /
    # NADC_OAUTH_* —— 那是货真价实的部署期配置), 圈大一点就会把这些键一并豁免。
    # ops/audit/ 则是纯治理代码 (九道硬门禁 + 共享真源), 它读的 env 只服务门禁自身,
    # 配了不改变 skill 的任何行为。
    "ops/audit/",
)

# 只在排除面被读取、而 runtime 面无读取点的 env 键 —— **逐个给理由的在册清单**。
# 与 EXCLUDED_SCOPE 正交: 前者按目录划界, 本清单按键值在册, 两者由单测比对集合相等。
# 新增一项必须写清"为什么它不是部署期配置", 否则那条单测判红。
EXCLUDED_ONLY: dict[str, str] = {
    "PYBEST_RUN_LIVE": "test/live 的实网开关: 只切测试自身的联网与否, 不进部署配置面",
    "ASTRO_BEST_LIVE_ARTIFACTS": (
        "E2 实跑产物落盘目录 (evals/groundtruth/live_policy.py): 只改评测批次把产物写哪, "
        "缺省已是 gitignored 的 temp/live_runs —— 照 .env.example 配它不改变 skill 行为, "
        "配错反而把产物写到被跟踪区, 那是铁律 3 违规"
    ),
    "HTTP_PROXY": "操作系统级代理变量 (evals/repro 只如实记录它是否存在): 非本 skill 契约",
    "HTTPS_PROXY": "同上: 标准库/系统环境变量, 照 .env.example 配它对用户无指导意义",
    "ASTRO_BEST_DIAGRAM_DIR": "本机 draw.io 出图目录 (docs/diagrams 制图工具链), 非 skill 运行时",
    "ASTRO_BEST_DRAWIO_EXE": "本机 draw.io 可执行文件路径: 同上",
    "ASTRO_BEST_DRAWIO_BUILDER_DIR": "本机 draw.io builder 目录: 同上",
    # 2026-10-07 新增: 门禁负对照闸的下限覆盖通道 (ops/audit/scan_roots.py)。
    # 键在 ops/audit/ 而不在 test/, 但性质与上面六键同类 —— 它是**门禁自身**的测试
    # 开关: 只有判据级测试造"故意很小的假仓"时才会设它, 照 .env.example 配它
    # 不改变 skill 的任何部署行为, 登记反而会教用户去设一个只对门禁有意义的变量。
    "ASTRO_BEST_MIN_SCAN_FILES": "门禁负对照闸的下限覆盖 (scan_roots): 门禁自身的测试开关, 非部署期输入",
    # 2026-10-08 新增: 归档压缩包隐私复验门禁 (ops/audit/verify_archive_privacy.py)
    # 动态抓取 Windows 操作系统提供的本机用户名做脱敏残留检验，非部署期配置。
    "USERNAME": "Windows 操作系统当前用户名 (ops/audit/verify_archive_privacy.py 隐私复验): 纯治理门禁读取, 非部署期输入",
    # 2026-10-11 新增: E5 隔离批的两条路径覆盖通道 (evals/ablation/iso/paths.py)。
    # 二者只在**隔离采集**时被读: E5_SCRATCH_ROOT 把批次根从 %TEMP%\e5_scratch 换到别的
    # 位置 (单测用它指向 tmp_path), E5_ISO_PROMPTS 换逐格提示词的源目录。照
    # .env.example 配它们既不改变 skill 行为, 也**不该**被部署方去设 —— scratch 的默认
    # 落点"必须在仓库之外"是 D-17 的结构性判据, 给一个可配置项去挪它反而给开了后门。
    "E5_SCRATCH_ROOT": (
        "E5 隔离批 scratch 根的覆盖通道 (evals/ablation/iso/paths.py): 单测与跨机复跑用, "
        "缺省 %TEMP%/e5_scratch; 登记进 .env.example 会教人去挪一个必须为仓外的目录"
    ),
    "E5_ISO_PROMPTS": (
        "E5 逐格提示词源目录的覆盖通道 (evals/ablation/iso/paths.py): 只换隔离投放从哪读, "
        "非部署期配置, 缺省 temp/decision_iso"
    ),
}
# 注: BEST_API_TOKEN **不在**本清单里 —— 它虽被 evals/repro/manifest.py 读取,
# 但 runtime 侧的 src/scripts/config.py 也真读它 (env_map), 故属"在册但死路",
# 由 test_dead_channel_claims.py 的退役通道判据守, 不归排除面裁定。
