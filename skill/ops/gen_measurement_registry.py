# -*- coding: utf-8 -*-
"""ops.gen_measurement_registry — 实测登记表的生成器 / 校验器 (N10 的数据侧)。

登记表 ``contracts/measurements/sort-columns.yaml`` 是**实测事实**的单点。手工维护
它迟早会和现实漂开, 所以本件提供两条命令:

* ``--check``: 只校验当前登记表与排序列真源是否自洽、是否冲突 (不写盘)。
  退出码非零即"该重算了"。**门禁跑的是判据不是这个件**, 但本件给出人能读的解释。
* ``--from-measurements <json>``: 从一份实测量 JSON 重算并覆写登记表。该 JSON 是
  ``ops/live_fetch.py`` 抓取后的**逐列统计产物** (格式见 :func:`observation_schema`)。

**刻意不做的事**: 本件**不发任何请求**。补观测要真打站点, 那是
``ops/live_fetch.py`` 的事 (铁律 7: 串行、间隔 >=1.5s、POST 不重试、产物落 temp/)。
把网络塞进生成器会让 ``make audit`` 变成一条要联网的线, 反而不可用。

**没有实测量时明说, 不写空表**: 零观测的登记表会让门禁判红 (零输入的绿灯只蕴含
「没有触发任何条件」), 所以本件在缺输入时直接失败, 不产出"看起来干净"的空文件。

用法::

    python ops/gen_measurement_registry.py --check
    python ops/gen_measurement_registry.py --from-measurements temp/sort_obs.json
"""
from __future__ import annotations

# 标准库: 参数解析 / JSON / 路径 / sys
import argparse
import json
import sys
from pathlib import Path

# 本地: 仓根锚定与排序列真源
ROOT = Path(__file__).resolve().parents[1]  # 仓根: 本件在 ops/ 下, 上溯一级
if str(ROOT) not in sys.path:  # 幂等: 支持从任意 cwd 直跑本件
    sys.path.insert(0, str(ROOT))

from ops.audit.verify_measurement_registry import (  # noqa: E402  — 判据方是门禁, 本件只取它的读表与校验
    REGISTRY_REL,
    load_registry,
    scan,
)

# 观测条目的必填键 (与登记表 schema 一致; 缺一个即拒收, 不做"尽力而为"的填充)
REQUIRED_KEYS = ("catalog", "column", "ra", "dec", "radius_arcsec",
                 "sample_rows", "non_empty_rows", "present_in_payload",
                 "evidence", "observed_on")


def observation_schema() -> dict:
    """给出 ``--from-measurements`` 期望的 JSON 结构 (供采集端照着产出)。

    Returns:
        一个"空模板"字典; 字段说明见本模块 docstring。
    """
    return {"observations": [dict.fromkeys(REQUIRED_KEYS, "<必填>")]}


def build_registry(observations: list[dict]) -> str:
    """把观测列表渲染成登记表 YAML 文本。

    刻意**不手写 YAML**: 用 ``yaml.safe_dump`` 保证语法正确, 但表头注释
    (口径与维护说明) 从现有登记表的头部原样保留 —— 那段是人读的契约, 不能因为
    重算就丢。

    Args:
        observations: 观测字典列表。

    Returns:
        完整 YAML 文本 (含保留的头部注释)。

    Raises:
        ValueError: 某条观测缺必填键。
    """
    import yaml  # 局部导入: 只有真的要渲染或校验时才需要

    existing = (ROOT / REGISTRY_REL).read_text(encoding="utf-8")
    header = "\n".join(ln for ln in existing.splitlines() if ln.startswith("#"))
    body = yaml.safe_dump({"observations": observations}, allow_unicode=True, sort_keys=False)
    return header.rstrip() + "\n\n" + body


def main(argv: list[str] | None = None) -> int:
    """入口: ``--check`` 校验, 或 ``--from-measurements`` 重算并覆写。

    Args:
        argv: 命令行参数 (None = 取 sys.argv)。

    Returns:
        0 = 校验通过 / 覆写成功; 1 = 有问题, 或缺输入。
    """
    parser = argparse.ArgumentParser(description="实测登记表生成器 / 校验器 (N10)")
    group = parser.add_mutually_exclusive_group(required=True)  # 二选一且必选: 不给动作就无从判断意图
    group.add_argument("--check", action="store_true", help="只校验当前登记表 (不写盘)")
    group.add_argument("--from-measurements", metavar="JSON", help="从实测量 JSON 重算并覆写")
    args = parser.parse_args(argv)  # argv 显式传入: 单测可绕开子进程调同一份解析器

    if args.check:  # 校验分支: 只读, 绝不写盘
        problems = scan(ROOT)
        if problems:
            print("[gen_measurement_registry] 登记表有问题 —— 判红:", file=sys.stderr)
            for item in problems:
                print(f"  - {item}", file=sys.stderr)
            return 1
        count = len(load_registry(ROOT))  # 读一次只为报个条数: 让人知道校的是多大一份表
        print(f"[gen_measurement_registry] 登记表自洽 ({count} 条观测), 且不与排序列真源冲突。")
        print("  要补观测: python ops/live_fetch.py --execute (产物落 temp/), "
              "再统计成 JSON 交给 --from-measurements。")
        return 0

    source = Path(args.from_measurements)  # 实测量 JSON: 采集端按 observation_schema 产出
    if not source.is_file():  # 输入不存在即失败: 静默跳过等于"没重算也当重算了"
        print(f"[gen_measurement_registry] 实测量文件不存在: {source}", file=sys.stderr)
        return 1
    payload = json.loads(source.read_text(encoding="utf-8"))
    observations = payload.get("observations") if isinstance(payload, dict) else None
    if not isinstance(observations, list) or not observations:  # 零观测不覆写 (见上方说明)
        print("[gen_measurement_registry] 实测量里没有 observations, 拒绝覆写。", file=sys.stderr)
        print("  结构模板:", json.dumps(observation_schema(), ensure_ascii=False), file=sys.stderr)
        return 1
    for index, entry in enumerate(observations):  # 逐条验必填键, 缺一个就指到序号
        missing = [key for key in REQUIRED_KEYS if key not in entry]  # 不做默认值填充: 那等于替你编观测
        if missing:
            print(f"[gen_measurement_registry] observations[{index}] 缺键: {missing}", file=sys.stderr)
            return 1

    (ROOT / REGISTRY_REL).write_text(build_registry(observations), encoding="utf-8")
    print(f"[gen_measurement_registry] 已覆写 {REGISTRY_REL} ({len(observations)} 条观测)。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
