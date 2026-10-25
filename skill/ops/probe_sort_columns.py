# -*- coding: utf-8 -*-
"""ops.probe_sort_columns — 逐表实测 ``PAGINATION_SORT_COLUMNS`` 的注入列 (N10 数据侧)。

## 它补的是什么缺口

``contracts/measurements/sort-columns.yaml`` 是排序列的实测登记册, 但建立时只有 2 张表
有观测, 其余 10 张排列表"尚无实测依据"。本件把那张表补齐: 对每张可查表发**一次**
真锥搜, 量两件事 —

* ``present_in_payload``: 注入列名是否出现在**回包表头**里 (false = 登记名写错, 服务端不认);
* ``non_empty_rows``: 该列在**数据行**里非空的行数 (空串与字面 ``nan`` 都算空)。

产物是 ``ops/gen_measurement_registry.py --from-measurements`` 吃的那份 JSON。

## 铁律 7 的四条硬约束 (本件逐条遵守)

1. **串行**, 不并发;
2. **强制间隔 >= 1.5s** (默认 1.6s, 与 ``live_policy.RATE_LIMIT_SECONDS`` 同源),
   且额外 sleep 一次 —— 限流只节流 ``session`` 上的请求, 而 phase-1 的 POST 是直接
   走 ``client.session.post``, 同样受节流; 多 sleep 一次是给站点留余量;
3. **POST 不重试** (重试会造孤儿会话、泄漏服务端配额)。单表失败只记账, 不回头重打;
4. 产物落 ``temp/`` (``--out`` 可改), 不写仓内任何位置。

## 两个必须说清的口径

**表头行不进数据**: 站点的分页 CSV **每页都重复一遍表头** (references §6)。单页探测
只遇到一次, 但仍统一走 ``protocol.parse_csv_rows`` —— 它把表头行剔在数据之外。直接
``csv.DictReader`` 的话, 表头那格里的列名字面量会被数成"非空值", 实测能凭空造出
3 个"非空 ``ps1_source_id``"。

**0 行不等于列空**: ``landolt`` (全天约 1 行 / 3.7 deg²) 与 ``jplus_dr3`` (站点侧
疑似覆盖空洞) 在任何合理半径下都回 0 行。**0 行只能说明"这个天区没数据"**, 不能说明
"这一列是空的" —— 拿它去证伪排序列是误判。本件因此把 ``sample_rows`` 一并记下,
让门禁能区分"没数据"与"列空"。

用法::

    python ops/probe_sort_columns.py --execute --out temp/sort_col_obs.json
    python ops/gen_measurement_registry.py --from-measurements temp/sort_col_obs.json
"""
from __future__ import annotations

# 标准库: 参数解析 / JSON / 正则 / 时间 / 路径 / sys
import argparse
import json
import re
import sys
import time
from datetime import date
from pathlib import Path

# 本地: 仓根锚定
ROOT = Path(__file__).resolve().parents[1]  # 仓根: 本件在 ops/ 下, 上溯一级
if str(ROOT) not in sys.path:  # 幂等: 支持从任意 cwd 直跑
    sys.path.insert(0, str(ROOT))

from src.client import BestClient  # noqa: E402  — 本仓实现, 不另造会话
from src.protocol import (  # noqa: E402  — 全部取协议层真源, 不复刻 URL 形态
    BEST_BASE_URL,
    CATALOG_PATHS,
    PAGINATION_SORT_COLUMNS,
    build_page_url,
    build_query_form,
    parse_csv_rows,
)

# 铁律 7 (b): 强制间隔。本仓限速真源是 1.5s, 这里取 1.6s 留一点余量。
DELAY_SECONDS = 1.6

# 每张表一个探测天区。**刻意不共用一个**: 排序列能不能用是**位置相关**的
# (ps1_source_id 在 (180,30) 整列为空, 在 (286.1,15.7) 有 128/300 非空 ——
# 见 contracts/measurements/sort-columns.yaml)。拿一个天区代表全表, 恰恰是本仓
# 反复吃过的那个坑。
#
# 半径按各表**实测密度**选, 不统一: scr_galah/scr_lamost 在 300″ 下恒 0
# (references §11: 1800″ 下分别 1 / 137 行), 300″ 只能测出"没数据"。
PROBE_REGIONS: dict[str, tuple[float, float, float]] = {
    "ps1": (180.0, 30.0, 60.0),            # 实测 174 行
    "gaia_dr3_18": (286.1, 15.7, 300.0),    # 实测有数据
    "xpsp": (10.68, 41.27, 300.0),          # 实测有数据
    "dr3xpcorr": (180.0, 30.0, 300.0),      # 实测 1 行 (极稀疏, 诚实记 1)
    "stripe82": (286.1, 15.7, 300.0),       # 实测有数据
    "smss_dr4": (120.3, -20.4, 1800.0),    # survey 天区, 半径放大到 1800″
    "splus_dr4": (120.3, -20.4, 1800.0),    # 同上
    "scr_galah": (120.0, -20.4, 1800.0),    # references §11: 1800″ 下 1 行
    "scr_lamost": (120.3, -20.4, 1800.0),   # references §11: 1800″ 下 137 行
    "uss_dr1": (120.3, -20.4, 300.0),       # 实测 1000 行
    # 下面两张按实测恒 0, 本件仍要**实跑一次**把"表头在不在"记下来 ——
    # 0 行但表头有该列, 是一个有信息量的观测 (比"没测到"强)。
    "landolt": (10.68, 41.27, 300.0),       # 全天极稀疏, 期望命中 0.018 行
    "jplus_dr3": (10.0, -60.0, 300.0),      # 站点侧疑似覆盖空洞 (references §10.8)
}

_SQLID_RE = re.compile(r"sqlid/(s?\d+)")


def probe_one(client: BestClient, catalog: str, column: str,
              ra: float, dec: float, radius: float) -> dict:
    """测一张表的一个排序列, 返回一条观测字典。

    单表失败不抛: 返回带 ``error`` 的观测, 让上层如实记账 —— 一个探点失败不该
    毁掉整批实测 (铁律 7: POST 不重试, 也就没有"再打一次"的选项)。
    """
    observed = {
        "catalog": catalog, "column": column,
        "ra": ra, "dec": dec, "radius_arcsec": radius,
        "sample_rows": 0, "non_empty_rows": 0,
        "present_in_payload": False,
        "evidence": "LIVE", "observed_on": date.today().isoformat(),
        "note": "",
    }
    try:
        form = build_query_form(catalog, [], output_format="html",
                                ra=ra, dec=dec, radius_arcsec=radius)
        # CATALOG_PATHS 的值**已经是**站点路径片段 (如 "ps1/q"), 不要再拼 "/q"。
        resp = client.session.post(f"{BEST_BASE_URL}/{CATALOG_PATHS[catalog]}", data=form)
        match = _SQLID_RE.search(resp.text)
        if not match:
            observed["error"] = "phase-1 未给出 sqlid"
            observed["note"] = "该天区可能无覆盖; 表头无从取得, present_in_payload 记 false"
            return observed
        url = build_page_url(BEST_BASE_URL, match.group(1), 1, page_size=200,
                             catalog=catalog, sort=column, order="asc")
        text = client.session.get(url).text
        # 表头判定用**原始首行**, 数据行用 parse_csv_rows (它把表头剔在数据之外)。
        # 两者分开: 前者回答"服务端认不认这一列名", 后者回答"这一列有值吗"。
        header = text.lstrip("﻿").splitlines()[:1]
        observed["present_in_payload"] = bool(header) and column in header[0]
        rows = parse_csv_rows(text, catalog=catalog)
        observed["sample_rows"] = len(rows)
        observed["non_empty_rows"] = sum(
            1 for row in rows if str(row.get(column, "")).strip() not in ("", "nan", "None")
        )
        if not rows:
            observed["note"] = ("该天区 0 数据行 —— 只说明这里没数据, **不能**据此说列空; "
                                "present_in_payload 来自表头, 仍有效")
    except Exception as exc:  # noqa: BLE001 — 探针要跑完所有表, 单表失败只记账
        observed["error"] = f"{type(exc).__name__}: {str(exc)[:120]}"
    return observed


def main(argv: list[str] | None = None) -> int:
    """入口: 默认 dry-run 预览, ``--execute`` 才真发请求。"""
    parser = argparse.ArgumentParser(description="逐表实测排序列注入列 (N10 数据侧)")
    parser.add_argument("--execute", action="store_true",
                        help="真发请求 (不带就是 dry-run, 一个请求都不发)")
    parser.add_argument("--out", default="temp/sort_col_obs.json", help="观测 JSON 落点")
    parser.add_argument("--only", default="", help="只测这几张表 (逗号分隔, 缺省全部)")
    parser.add_argument("--radius-mult", type=float, default=1.0,
                        help="探测半径倍率 (缺省 1.0; 0 行时放大再试一次, 换取真数据而非 '无覆盖')")
    parser.add_argument("--suffix", default="", help="观测 note 里追加的后缀 (区分不同半径的批次)")
    parser.add_argument("--region", default="",
                        help="覆盖探测天区: 表=ra,dec,radius, 多组用**分号**分隔 "
                             "(逗号已被 --only 占用, 且 ra/dec/radius 自己就要用逗号)。"
                             "只在探测**已知选错天区**时用 —— stripe82 沿赤道窄带、"
                             "splus_dr4 是南天巡天, 拿别的表的天区去测只会测出 "
                             "'这里没覆盖', 那与列本身有没有值无关")
    args = parser.parse_args(argv)

    overrides: dict[str, tuple[float, float, float]] = {}
    for item in (s.strip() for s in args.region.split(";") if s.strip()):
        name, _, coords = item.partition("=")
        parts = coords.split(",")
        if len(parts) != 3:
            raise SystemExit(f"--region 每组须为 表=ra,dec,radius, 实得 {item!r}")
        ra, dec, radius = parts
        overrides[name.strip()] = (float(ra), float(dec), float(radius))

    targets = sorted(PAGINATION_SORT_COLUMNS)
    if args.only:
        wanted = {c.strip() for c in args.only.split(",") if c.strip()}
        targets = [c for c in targets if c in wanted]

    # 别名项 (不在 CATALOG_PATHS 里) 不是可查表, 测了也只会得到"路由不存在"。
    # 它们的排序列随主表走, 观测记在主表名下 —— 见文件末尾的缺口说明。
    unqueryable = [c for c in targets if c not in CATALOG_PATHS]

    print(f"待测 {len(targets)} 项, 其中 {len(unqueryable)} 项不是可查表(别名): {unqueryable}")
    for catalog in targets:
        column = PAGINATION_SORT_COLUMNS[catalog]
        region = PROBE_REGIONS.get(catalog)
        if region is None:
            print(f"  跳过 {catalog}: 未登记探测天区")
            continue
        print(f"  {catalog:<12} -> {column:<42} @ {region}")
    if not args.execute:
        print("\n(dry-run) 不带 --execute 一个请求都不发。")
        return 0

    client = BestClient(rate_limit=1.5)   # 限速在客户端侧, 本件再额外 sleep
    observations: list[dict] = []
    for index, catalog in enumerate(targets):
        if catalog not in CATALOG_PATHS:
            print(f"[{index + 1}/{len(targets)}] {catalog}: 别名项, 随主表观测, 跳过", flush=True)
            time.sleep(DELAY_SECONDS)
            continue
        column = PAGINATION_SORT_COLUMNS[catalog]
        ra, dec, radius = PROBE_REGIONS[catalog]
        if catalog in overrides:
            ra, dec, radius = overrides[catalog]
        radius = radius * args.radius_mult
        observed = probe_one(client, catalog, column, ra, dec, radius)
        if args.suffix:
            observed["note"] = (observed["note"] + " " if observed["note"] else "") + args.suffix
        observations.append(observed)
        flag = "  <-- 有问题" if observed.get("error") else ""
        if observed.get("present_in_payload") and observed["sample_rows"] == 0:
            flag = "  <-- 表头有该列但 0 数据行 (无覆盖, 非列空)"
        print(f"[{index + 1}/{len(targets)}] {catalog:<12} 列={column:<38} "
              f"在表头={observed['present_in_payload']!s:<5} 行={observed['sample_rows']:<5} "
              f"非空={observed['non_empty_rows']}{flag}", flush=True)
        time.sleep(DELAY_SECONDS)   # 铁律 7 (b)

    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"observations": observations}, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    print(f"\n落盘 {out.relative_to(ROOT).as_posix()} ({len(observations)} 条观测)")
    print(f"下一步: python ops/gen_measurement_registry.py --from-measurements {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
