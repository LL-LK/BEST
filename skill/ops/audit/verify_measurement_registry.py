# -*- coding: utf-8 -*-
r"""ops.audit.verify_measurement_registry — 实测登记表的一致性门禁 (N10)。

**它守的失效形态 (2026-10-07)**: ``PAGINATION_SORT_COLUMNS`` 里每一列都是"实测过
才敢注入"的选择, 但那份实测结论当时只活在**注释与一个测试的字面量集合**里::

    known_empty = {"ps1_source_id", "uss_dr1_ra_u"}

2026-10-07 实跑把这两条**双双证伪**:

  * ``ps1_source_id`` 的空值率**位置相关** —— (180,30) 样本 0/174 非空, 而
    (286.1, 15.7) 实测 128/300 非空。"该列整列为空"是这个**天区**的性质, 不是
    列的固有属性。按旧断言的口径, 一张表只要碰上那个天区就会被冤枉。
  * ``uss_dr1_ra_u`` 在 96 列回包里**根本不存在同名列** (回包是裸名 ``ra_u``)
    —— 它不是"空列", 是**登记名写错**。把"不存在"混进"恒空"是两个不同的病,
    混在一张集合里就等于两种都治不了。

**本门禁的判据**: 实测事实移到 ``contracts/measurements/sort-columns.yaml`` 登记,
本门禁核三件事 ——

  1. **条目自洽**: ``non_empty_rows <= sample_rows``、证据等级在四档内、
     ``present_in_payload`` 是真布尔、catalog/column 非空;
  2. **登记的排序列不被证伪**: ``PAGINATION_SORT_COLUMNS`` 里的每个列, 只要它在
     登记表里**有观测**, 那观测就不得说它"表头里不存在"或"处处为空" ——
     这一条是对上面那两个证伪事实的机械落地;
  3. **覆盖缺口必须显式披露**: 没有任何观测的排序列**不判红** (登记表刚建立,
     12 张表里只有几张有观测是事实), 但**必须报出来** —— 缺口被打印出来而不是
     被静默当成"都验过了", 这正是零输入绿灯的同一种病。

**本门禁管不到的一类 (明说, 免得被当成全覆盖)**: "某列在**你这次查询的那个天区**
恰好为空"。`ps1_source_id` 就是活的反例 —— (180,30) 样本 0/174 非空, 而
(286.1,15.7) 128/300 非空。所以本门禁**不**禁止把 `ps1_source_id` 设成排序列
(那是合法的选择), 也**判不出**在某个特定天区会失效。要抓那一类需要"请求上下文",
属于分页实跑臂的职责, 不在本门禁射程内。**登记表只回答"这一列有没有可能可用",
不回答"你这次会不会正好落在空的那些区"。**

**刻意不做的事**: 不重打站点去补观测。补观测是 ``ops/live_fetch.py`` 与
``ops/gen_measurement_registry.py`` 的活; 门禁只核**已登记的**那份是否自洽且
不与代码冲突 —— 免得 ``make audit`` 变成一条要联网的线。

对外接口: :func:`load_registry` (root) -> 观测列表; :func:`scan` (root) -> 违规清单;
:func:`main` (argv) -> 退出码。``root`` 显式参数化: 判据级红测试要能在临时目录里
注入畸形登记表后实跑。
"""
from __future__ import annotations

# 标准库: argparse / os / sys / 路径
import argparse
import sys
from pathlib import Path

# 控制台编码防御: Windows cp936 / GBK 终端下防止 Unicode 符号抛 UnicodeEncodeError
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# 本地: 共享真源 —— 排序列映射从协议层取, 不在本门禁里复刻 (复刻即第二份真源)
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))          # 上溯两级即仓根: 让 src.* 可导入

from src.protocol import PAGINATION_SORT_COLUMNS  # noqa: E402  — 排序列真源

# 登记表相对路径 (SSOT 位置: 与 contracts/ 下其它契约同层)
REGISTRY_REL = "contracts/measurements/sort-columns.yaml"  # SSOT 位置: 与 contracts/ 下其它契约同层

# 四档证据等级 (与 references §11 的披露口径逐字一致; 不认的等级即判红,
# 否则"随手写个 UNKNOWN"就能让一条没验过的观测混过门禁)
VALID_EVIDENCE = frozenset({"LIVE", "SNAPSHOT", "TEMP", "UNTESTED"})  # 四档穷举, 不接受扩展

# 必填的数值/布尔字段: 缺一个即判红 —— "没测"要写成 UNTESTED 观测, 不能靠缺字段表达
REQUIRED_INT_FIELDS = ("sample_rows", "non_empty_rows")  # 两个都必须是真整数
REQUIRED_BOOL_FIELDS = ("present_in_payload",)  # 登记表里"表头有没有这一列"的事实位


def load_registry(root: Path) -> list[dict]:
    """读登记表并返回观测列表。

    Args:
        root: 仓根。

    Returns:
        观测字典列表; 表单不对时抛 ``ValueError`` (由调用方转成违规)。
    """
    import yaml  # 局部导入: 只有真的读到表才需要 yaml 依赖

    path = root / REGISTRY_REL  # 表单路径由 SSOT 常量决定, 不在函数里复刻字符串
    if not path.is_file():
        raise FileNotFoundError(f"实测登记表缺失: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("observations"), list):
        raise ValueError("登记表结构不对: 顶层须是含 observations 列表的映射")
    return data["observations"]


def _entry_problems(entry: dict, index: int) -> list[str]:
    """单条观测的自洽性判据。

    Args:
        entry: 一条观测。
        index: 序号 (写进问题描述, 便于按行定位)。

    Returns:
        问题描述列表; 空列表 = 该条自洽。
    """
    where = f"observations[{index}]"  # 按序号定位: 登记表很长, 报告要能指到具体条目
    problems: list[str] = []
    for key in ("catalog", "column"):
        if not str(entry.get(key, "")).strip():  # 空串与缺键同判: 两者都认不出是哪张表的哪一列
            problems.append(f"{where}: 缺必填字段 {key}")
    evidence = entry.get("evidence")
    if evidence not in VALID_EVIDENCE:  # 不认的等级即判红, 不做大小写折叠 (免得 UNKNOWN 混过)
        problems.append(f"{where}: evidence={evidence!r} 不在四档内 {sorted(VALID_EVIDENCE)}")
    for key in REQUIRED_INT_FIELDS:
        value = entry.get(key)
        # bool 是 int 的子类: isinstance(True, int) 为真, 必须显式排除
        if not isinstance(value, int) or isinstance(value, bool):  # True/False 填进行数字段即违规
            problems.append(f"{where}: {key}={value!r} 不是整数")
    for key in REQUIRED_BOOL_FIELDS:
        if not isinstance(entry.get(key), bool):  # 字符串 "true"/"false" 一律判红: YAML 里那不是事实
            problems.append(f"{where}: {key}={entry.get(key)!r} 不是布尔")
    if not problems:  # 类型全对才比大小, 否则下面的比较会抛
        sample, non_empty = entry["sample_rows"], entry["non_empty_rows"]  # 分母与非空数
        if non_empty < 0 or sample < 0:  # 负行数没有物理意义
            problems.append(f"{where}: 行数不得为负 (sample={sample}, non_empty={non_empty})")
        if non_empty > sample:  # 非空数超分母 = 抄错了, 这条观测自相矛盾
            problems.append(f"{where}: non_empty({non_empty}) > sample({sample})")
    return problems


def scan(root: Path) -> list[str]:
    """核登记表自洽, 且不与排序列真源冲突。

    Args:
        root: 仓根。

    Returns:
        违规描述列表; 空列表 = 全绿 (覆盖面缺口只打印, 不进这个列表)。
    """
    try:
        observations = load_registry(root)
    except (FileNotFoundError, ValueError) as exc:
        return [f"登记表不可用: {exc}"]

    if not observations:  # 零观测: 无从判断, 不等于"都验过了"
        # 零观测: 门禁无从判断 —— 与本仓其余门同一纪律, 判红而不是报"全绿"
        return ["登记表零观测: 零输入的绿灯只蕴含「没有触发任何条件」"]

    problems: list[str] = []
    for index, entry in enumerate(observations):  # 序号进问题描述: 登记表长, 要能指到条目
        problems.extend(_entry_problems(entry, index))

    # 反证核心: 登记的排序列不得被登记表证伪 (表头里不存在 / 处处为空)
    by_column: dict[tuple[str, str], list[dict]] = {}
    for entry in observations:  # 按 (catalog, column) 归组: 一列可能有多个天区的观测
        by_column.setdefault((entry.get("catalog"), entry.get("column")), []).append(entry)
    for catalog, column in sorted(PAGINATION_SORT_COLUMNS.items()):  # 排序让报告跨机可比
        hits = by_column.get((catalog, column))
        if not hits:  # 无观测 = 未知; 走覆盖面披露, 不在这里判红
            continue  # "没测到"不等于"空": 这一条正是旧断言栽的地方
        if all(entry.get("present_in_payload") is False for entry in hits):
            problems.append(
                f"排序列 {catalog} -> {column} 被登记表证伪: 所有观测都记 present_in_payload=false"
                " (该列名在回包表头里不存在, 注入它服务端不认)")
        # **只看有数据的观测** (2026-10-07 修正): ``non_empty_rows == 0`` 只有在
        # 真的取到数据行时才说明"这一列是空的"。``sample_rows == 0`` 说明**这个天区
        # 没覆盖**, 拿它证伪排序列是误判 —— 实测 landolt (全天约 1 行 / 3.7 deg²) 与
        # jplus_dr3 (站点侧疑似覆盖空洞) 都是"表头有该列 + 0 数据行", 而它们的排序列
        # 恰恰是**唯一合法的选择**。原实现把两者混为一谈, 是一条会误杀合法配置的门。
        with_data = [entry for entry in hits if entry.get("sample_rows", 0) > 0]
        if with_data and all(entry.get("non_empty_rows") == 0 for entry in with_data):
            problems.append(
                f"排序列 {catalog} -> {column} 被登记表证伪: 所有**有数据**的观测 "
                "non_empty_rows 都是 0 (该列处处为空, 注入等于白送)")
    return problems


def _coverage_gap(root: Path) -> str:
    """报出没有任何实测观测的排序列 (缺口披露, 不判红)。

    **别名项与真缺口分开报** (2026-10-07): ``PAGINATION_SORT_COLUMNS`` 里有
    ``gaia_dr3`` —— 它是 ``gaia_dr3_18`` 的**旧拼写别名**, 不在 ``CATALOG_PATHS`` 里,
    不是可查表 (实测 ``path=None``)。给一个不可查的表建观测**按构造不可能**, 把它
    列进"尚无实测依据"是**误导**: 读的人会去补测, 而补测只能得到"路由不存在"。
    故别名项单独报, 并指向它随谁走。

    Args:
        root: 仓根。

    Returns:
        披露文字 (可能多行); 登记表不可读时返回空串 (错误已由 :func:`scan` 报出)。
    """
    try:
        observations = load_registry(root)
    except (FileNotFoundError, ValueError):
        return ""
    from src.protocol import CATALOG_PATHS  # 局部导入: 只为判"可查表", 别处已有同一真源

    observed = {(e.get("catalog"), e.get("column")) for e in observations}  # 已建档的 (表, 列)
    # 分两类时**按 catalog 键本身**分, 不在格式化后的字符串上做前缀匹配 ——
    # 字符串前缀判据经不起 "gaia_dr3->..." 与 "gaia_dr3_18->..." 这种同前缀异名:
    # 试过, 它会把别名项漏进真缺口里 (实测就该漏)。
    aliases = sorted(f"{c}->{col} (随 {_alias_target(col)} 走)"  # 别名项: 不可查表, 单独披露
                     for c, col in PAGINATION_SORT_COLUMNS.items()
                     if c not in CATALOG_PATHS and (c, col) not in observed)
    real_missing = sorted(f"{c}->{col}" for c, col in PAGINATION_SORT_COLUMNS.items()  # 真缺口: 可查表却没观测
                          if c in CATALOG_PATHS and (c, col) not in observed)

    lines = []                                                                                        # 披露行容器: INFO 与 WARN 分行给
    if aliases:                                                                                       # 别名项不是缺口: 说清它随谁走即可
        lines.append(f"  [INFO] 别名项 {len(aliases)} 个 (非可查表, 按构造无法单独建观测): "
                     + ", ".join(aliases) + "\n")
    if not real_missing:                                                                               # 全覆盖是最好状态, 但它不是判红条件
        lines.append("  覆盖面: 全部**可查**排序列都有实测观测。\n")
    else:
        lines.append(f"  [WARN] 覆盖面缺口 (不判红, 但这些排序列**尚无实测依据**): "  # 缺口必须可见
                     f"{len(real_missing)} 个 —— " + ", ".join(real_missing) + "\n")
    return "".join(lines)


def _alias_target(column: str) -> str:
    """与给定排序列同值的**可查**表名 (别名项随它走); 没有则说「未找到」。

    判据刻意用「同排序列值」而不是硬编码别名表 —— 别名关系会随代码演进, 硬编码的
    映射表必然漂移; 而"这张表不可查, 那张可查的表用同一个排序列"是可直接算出来的事实。
    """
    from src.protocol import CATALOG_PATHS  # 局部导入: 同上

    for catalog, col in sorted(PAGINATION_SORT_COLUMNS.items()):  # 排序让报告跨机可比
        if col == column and catalog in CATALOG_PATHS:  # 同排序列值 + 可查 = 别名的落点
            return catalog
    return "未找到可查主表"


def main(argv: list[str] | None = None) -> int:
    """门禁入口: 登记表不自洽或与排序列真源冲突即判红。"""
    parser = argparse.ArgumentParser(description="实测登记表一致性门禁 (N10)")
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[2]),
                        help="仓根 (默认按本文件位置上溯两级)")
    args = parser.parse_args(argv)  # root 显式可传: 判据级红测试要在临时目录里实跑
    root = Path(args.root)  # 显式根: 判据级红测试靠它把仓指向临时目录
    findings = scan(root)  # 判据全在这一个函数里, main 不再重复判

    if findings:  # 非空即红; 空则走覆盖面披露后放行
        print(f"[verify_measurement_registry] {len(findings)} 个问题 —— 判红 (N10):", file=sys.stderr)
        for item in findings:
            print(f"  - {item}", file=sys.stderr)
        print("  实测事实请改 contracts/measurements/sort-columns.yaml, 或跑 "
              "ops/gen_measurement_registry.py 重算。", file=sys.stderr)
        return 1
    print("[verify_measurement_registry] 登记表自洽, 且不与排序列真源冲突 —— 通过 (N10)。")
    sys.stdout.write(_coverage_gap(root))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
