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
    "test/",   # 测试自身开关 (PYBEST_RUN_LIVE): 配它不改变 skill 的部署行为
    "evals/",  # 评测复现元数据 (HTTP_PROXY/BEST_API_TOKEN): 只如实记录, 非部署期输入
    "docs/",   # 本机 draw.io 渲染路径 (ASTRO_BEST_DRAWIO_EXE 等): 制图工具链, 非 skill 运行时
)

# 只在排除面被读取、而 runtime 面无读取点的 env 键 —— **逐个给理由的在册清单**。
# 与 EXCLUDED_SCOPE 正交: 前者按目录划界, 本清单按键值在册, 两者由单测比对集合相等。
# 新增一项必须写清"为什么它不是部署期配置", 否则那条单测判红。
EXCLUDED_ONLY: dict[str, str] = {
    "PYBEST_RUN_LIVE": "test/live 的实网开关: 只切测试自身的联网与否, 不进部署配置面",
    "HTTP_PROXY": "操作系统级代理变量 (evals/repro 只如实记录它是否存在): 非本 skill 契约",
    "HTTPS_PROXY": "同上: 标准库/系统环境变量, 照 .env.example 配它对用户无指导意义",
    "ASTRO_BEST_DIAGRAM_DIR": "本机 draw.io 出图目录 (docs/diagrams 制图工具链), 非 skill 运行时",
    "ASTRO_BEST_DRAWIO_EXE": "本机 draw.io 可执行文件路径: 同上",
    "ASTRO_BEST_DRAWIO_BUILDER_DIR": "本机 draw.io builder 目录: 同上",
}
# 注: BEST_API_TOKEN **不在**本清单里 —— 它虽被 evals/repro/manifest.py 读取,
# 但 runtime 侧的 src/scripts/config.py 也真读它 (env_map), 故属"在册但死路",
# 由 test_dead_channel_claims.py 的退役通道判据守, 不归排除面裁定。
