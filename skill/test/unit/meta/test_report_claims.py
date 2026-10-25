# -*- coding: utf-8 -*-
"""REPORT.md 声称数字 vs 题集实数 —— "报告与事实脱节"的现成向量 (A6-05)。

起因 (2026-10-04 突变实验 A6-05): 全仓 ``test/**/*.py`` 搜 ``REPORT.md``
**零命中**, 而 ``ops/audit/verify_doc_consistency.py`` 只扫 ``.py``。于是
``evals/*/REPORT.md`` 里"题数 36 / 判定 PASS / 68 条用例"这类**归档结论**
没有任何一处与题集事实对账的机制: 题集改了、跑批口径变了、报告没跟上, 或者
更糟 —— 报告说 SUCCESS 而代码实际不是, **全绿与说谎在 CI 输出里长得一模一样**。
这与 A6-04 的"退出码写死成常量"是同一族病: 报告与门禁都是对事实的**声明**,
而声明本身无人核。

本文件的对账口径刻意分两层, 边界必须说清:

  - **可复算的** (本文件断言): 规模类数字 —— 题数、用例数、任务数、系统数、
    分层条数。它们能从题集/场景/任务文件**当场重算**, 因此报告一改或题集一
    改就会红。六个实验 (E1~E6) 全部纳入。
  - **不可廉价复算的** (E3/E4/E6 仍然不断言): 分数、通过率、metascore、
    区间宽度 —— 重算它们要真跑批, 塞进 ``make test`` 会让门禁慢到被绕过。
    这条边界是本文件的已知局限, 不是"已覆盖": **E3/E4/E6 的分数漂移目前仍无
    自动发现机制**, 要靠人复跑对账。本文件只对 E1 的"判定 vs 加权总分"做
    **报告内部**一致性核对 (不需要跑批), 跨档位比较一律不做 —— E3/E6 的
    口径与 E1/E5 不同, 强行归一会造出假红。

  - **E5 的指标值 (2026-10-05 K1 补齐, 唯一一处例外)**: 上面那条"不跑批"
    的纪律曾留下一条真实缺口 —— 2026-10-05 实测发现 commit ``1893cfd`` 改了
    影响 HR 口径的代码却没重生成 ``evals/ablation/REPORT.md``, 7 行 HR 指标
  与代码脱节 (B3/A1/A2/A5/sham 的 HR_any 0.833→0.800, A3 的 0.967→0.933),
    而门禁全绿: 因为规模类数字 (30 任务 / 11 系统) 一个都没变。
    补法不是"全量跑批进 make test" (实测 46s, 太慢), 而是**只重算基准装配
    B3**: 跑批矩阵按 (装配 × 任务 × 重复) 独立, 单装配重算与全量重算的
    该装配指标**逐字相同** (B3 行正是那 7 行漂移行之一), 实测 6.2s。
    这条只锁 B3 一行, 不覆盖其余 10 个装配 —— 是有意的成本换取舍, 不冒充
    "全部指标已守护"; 其余装配的漂移仍靠 ``make eval-e5`` 后人工对账。

门禁位置说明: 本文件是 **pytest 门禁** (随 ``make test`` / ``make check`` 走),
不是 ``ops/audit/`` 里的独立脚本。理由是它的判据天然是"逐条声明 vs 逐条实算",
与仓内既有的 SSOT 守护 (``test_coverage_matrix.py`` 守矩阵、``test_module_paths.py``
守契约路径) 同族, 放进 pytest 就能复用同一套 fail-closed 惯例; 而
``ops/audit/`` 那一层留给"整仓扫描型"的治理护栏。
"""
from __future__ import annotations

# 标准库: re 从报告正文抽声称的数 / sys 解释器 / pathlib 仓根与路径
import re  # 抽"报告声称的数", 与从题集重算的值对撞
import sys  # 把仓根塞进 sys.path: 重算 E5 系统数要 import 实验侧装配表
from pathlib import Path  # 路径拼装: 仓根由本文件位置推出, 不写死盘符

# 第三方: yaml 读题集 (题集是纯数据, 安全加载足够)
import yaml  # 题集/场景/任务清单都是 YAML 事实源

SKILL_ROOT = Path(__file__).resolve().parents[3]  # 仓根上溯三级: 本文件在 test/unit/meta/
REPORTS = SKILL_ROOT / "evals"                     # 六个实验的 REPORT.md 都在这一层之下

# 实验编号 -> 目录名。目录名是历史沿革 (E1 的目录叫 nl2tool 而非 e1), 与文档里
# 的 "E1..E6" 编号对不上; 映射集中在这里, 免得每处对账各写一遍对照。
EXP_DIRS = {
    "E1": "nl2tool",
    "E2": "groundtruth",
    "E3": "semantics",
    "E4": "robustness",
    "E5": "ablation",
    "E6": "repro",
}


def report_text(exp: str) -> str:
    """读某个实验的 REPORT.md 全文; 文件缺失即红 (不静默跳过, 铁律 5)。"""
    path = REPORTS / EXP_DIRS[exp] / "REPORT.md"  # 编号经映射落到真实目录名
    assert path.is_file(), f"报告缺失: {path}"     # 缺报告即红: 静默跳过等于让漂移合法化
    return path.read_text(encoding="utf-8")       # 全utf-8 读: 报告是中文正文


def claimed_int(text: str, pattern: str, exp: str) -> int:
    """从报告里抽出一个声称的**整数**; 抽不到即红 (报告改了口径必须同步改本门禁)。"""
    m = re.search(pattern, text)                    # 只认带中文标签的形态
    assert m, f"{exp}: 报告里找不到声称 `{pattern}` —— 报告口径变了, 本门禁必须同步更新"
    return int(m.group(1))                          # 捕获组第一条即目标数字


def _items(rel: str) -> list[dict]:
    """读一份题集 YAML 的 items 列表 (E1/E3/E4/E5 共用同一形态)。"""
    text = (SKILL_ROOT / rel).read_text(encoding="utf-8")  # 路径相对仓根: 换机不用改
    return yaml.safe_load(text)["items"]            # 题集顶层必有 items, 缺了就是结构坏了


def _e1_task_count() -> int:
    """E1 任务数: tasks.yaml 的条目数。"""
    text = (SKILL_ROOT / "evals/nl2tool/tasks.yaml").read_text(encoding="utf-8")
    return len(yaml.safe_load(text)["tasks"])       # E1 顶层键是 tasks 而非 items


def _e3_item_count() -> int:
    """E3 题数: items.yaml 的条目数 (live 题计入题数, 只是不计入主指标)。"""
    return len(_items("evals/semantics/items.yaml"))


def _e3_tier_count(tier: str) -> int:
    """E3 某一 tier 的题数: fixture 与 live 的分账。"""
    return sum(1 for i in _items("evals/semantics/items.yaml") if i.get("tier") == tier)


def _e4_total() -> int:
    """E4 用例集总数: items.yaml 全部条目 (主用例 + 复合变体)。"""
    return len(_items("evals/robustness/items.yaml"))


def _e4_is_composite(item: dict) -> bool:
    """E4 复合变体判定: RB-C 前缀 (它们单独出报告, 不计入主指标)。"""
    return str(item["id"]).startswith("RB-C")


def _e4_main_count() -> int:
    """E4 主用例数: 非 RB-C 前缀的条目。"""
    return sum(1 for i in _items("evals/robustness/items.yaml") if not _e4_is_composite(i))


def _e4_main_tier_count(tier: str) -> int:
    """E4 主用例里指定 tier 的条数 (报告写 '35 P + 15 W')。"""
    return sum(1 for i in _items("evals/robustness/items.yaml")
               if not _e4_is_composite(i) and i.get("tier") == tier)


def _e4_composite_count() -> int:
    """E4 复合变体数: RB-C 前缀条目数。"""
    return sum(1 for i in _items("evals/robustness/items.yaml") if _e4_is_composite(i))


def _e5_item_count() -> int:
    """E5 任务数: items.yaml 条目数。"""
    return len(_items("evals/ablation/items.yaml"))


def _e5_system_count() -> int:
    """E5 系统数: 装配表 SYSTEM_ORDER 的长度 (从实验侧 import, 不在本门禁复刻一份)。

    刻意 import 真实装配表而不是数 YAML 行: 装配表是实验的 SSOT, 门禁自备副本
    等于自己给自己发考卷 (两份副本漂移时门禁会跟着一起错)。
    """
    if str(SKILL_ROOT) not in sys.path:
        sys.path.insert(0, str(SKILL_ROOT))       # 仓根入路径: evals 包要能 import
    from evals.ablation.harness.run_batch import SYSTEM_ORDER  # noqa: PLC0415 局部导入: 只这一处依赖实验侧
    return len(SYSTEM_ORDER)


def _e6_task_count() -> int:
    """E6 任务数: tasks/ 下 REPRO-*.yaml 的个数 (与 manifest.task_set_fingerprint 同口径)。"""
    return len(list((SKILL_ROOT / "evals/repro/tasks").glob("REPRO-*.yaml")))


def _e2_gold_count() -> int:
    """E2 金标准份数: gold/ 下 17 份 <case_id>.json (签字单联与指纹台账已于 2026-10-04 删除)。"""
    files = (SKILL_ROOT / "evals/groundtruth/gold").glob("*.json")  # 只收 json
    return sum(1 for f in files if f.name != "manifest.json")


def _e2_scenario_count() -> int:
    """E2 场景数: scenarios/*.yaml 的个数。"""
    return len(list((SKILL_ROOT / "evals/groundtruth/scenarios").glob("*.yaml")))


def _e5_report_row(system: str) -> list[str]:
    """从 E5 报告的主表里取出某个装配那一行的全部单元格 (逐字, 未解析)。"""
    text = report_text("E5")                                   # 报告全文: 三张表都在同一份里
    for line in text.splitlines():                             # 逐行找目标装配那一行
        cells = [c.strip() for c in line.strip().strip("|").split("|")]  # 去掉首尾竖线再切, 免得空单元格错位
        if cells and cells[0] == system:                       # 首格即系统 id
            return cells                                       # 命中即返回: 逐字文本, 不在这里解析成浮点
    raise AssertionError(f"E5 报告主表里找不到装配 {system} 那一行")   # 抽不到即红: 静默跳过等于让漂移合法化


def _e5_recompute_baseline() -> dict[str, float]:
    """**真跑** E5 的基准装配 B3, 返回它的指标卡 (实测 6.2s, 全离线)。

    为什么只跑 B3 一个装配: 跑批矩阵按 (装配 × 任务 × 重复) 三重独立, 某个
    装配的成绩单只由它自己的那些 run 决定 —— 少跑另外 10 个装配不会改变它
    的任何一个指标 (已实测: 单装配与全量跑批的 B3 指标逐字相同)。全量跑批
    实测 46s, 塞进 ``make test`` 会让门禁慢到被绕过; 单装配是那个折中点。

    锁 B3 的另一个理由: 2026-10-05 实测的指标漂移 (commit 1893cfd 改了 HR
    口径却没重生成报告) 恰好就落在 B3 那一行上, 即这条门禁对那次真实缺陷
    是**非空转**的。
    """
    if str(SKILL_ROOT) not in sys.path:                  # 幂等判据: 已注入就不重复塞
        sys.path.insert(0, str(SKILL_ROOT))              # 仓根入路径: evals 包要能 import
    from evals.ablation.harness.run_batch import load_items  # noqa: PLC0415 题集由实验侧装载
    from evals.ablation.metrics.composite import aggregate  # noqa: PLC0415 成绩单聚合在实验侧
    from evals.ablation.runner import run  # noqa: PLC0415 局部导入: 只这一处依赖实验侧
    report = run(system_names=["B3"], repeat=3)   # 只跑基准装配; 默认走 ScriptedLLM 替身批, 零网络
    return aggregate(report["runs"], load_items())["B3"]   # 聚合成成绩单后只取 B3 那一行


# E5 主表 (表 1) 的列序: 键名必须与 evals/ablation/report.py::T1_COLUMNS 逐字对齐,
# 顺序即那一行的单元格顺序。刻意从实验侧 import 而不在本文件复刻一份 —— 复刻
# 等于自己给自己发考卷 (两份副本漂移时门禁会跟着一起错, 与 _e5_system_count 同理)。
# 表 1 在 T1_COLUMNS 之外**额外追加**一列 http_requests (成本列走整数形态,
# 见 report.py 的渲染处), 故本门禁把它显式补在末尾而不是写死偏移量 —— 偏移量
# 会在有人调整列序时静默错位。
E5_EXTRA_T1_COLUMNS: tuple[str, ...] = ("http_requests",)   # T1_COLUMNS 之外的追加列


def _e5_t1_columns() -> tuple[str, ...]:
    """取 E5 主表的指标列键名 (从实验侧 import, 不在本门禁复刻)。"""
    if str(SKILL_ROOT) not in sys.path:
        sys.path.insert(0, str(SKILL_ROOT))                  # 主表列名取自 evals.ablation.report
    from evals.ablation.report import T1_COLUMNS  # noqa: PLC0415 局部导入: 只这一处依赖实验侧
    return tuple(key for key, _ in T1_COLUMNS) + E5_EXTRA_T1_COLUMNS   # 元组保序: 顺序即报告里的列序


# E5 表 4 (幻觉三通道) 的列序: 键名取自实验侧 HR_COLUMNS, 同样不本地复刻。
def _e5_hr_columns() -> tuple[str, ...]:
    """取 E5 表 4 的 HR 通道列键名 (从实验侧 import)。"""
    if str(SKILL_ROOT) not in sys.path:
        sys.path.insert(0, str(SKILL_ROOT))                  # 表 4 列名取自同一模块
    from evals.ablation.report import HR_COLUMNS  # noqa: PLC0415 局部导入: 只这一处依赖实验侧
    return HR_COLUMNS                                        # 已是保序元组: 三通道 + 复合 + 致命


def _e5_hr_report_row(system: str) -> list[str]:
    """从 E5 报告的表 4 (幻觉三通道表) 里取出某个装配那一行的单元格。"""
    text = report_text("E5")                                 # 报告全文: 表 4 与主表同在一份
    header = next((line for line in text.splitlines()         # 认表头: 用它定列数, 免得拿错别的表
                   if line.strip().startswith("|") and "HR_param" in line), None)
    assert header, "E5: 报告里找不到表 4 (幻觉三通道表) 的表头 —— 报告结构变了, 本门禁须同步"
    columns = [c.strip() for c in header.strip().strip("|").split("|")]   # 列数由表头定, 不由数据行猜
    for line in text.splitlines():                           # 逐行找目标装配那一行
        cells = [c.strip() for c in line.strip().strip("|").split("|")]  # 切列同上
        if len(cells) == len(columns) and cells and cells[0] == system:   # 列数相符才认, 防撞上别的表
            return cells                                     # 命中即返回: 逐字文本, 不解析成浮点
    raise AssertionError(f"E5 表 4 里找不到装配 {system} 那一行")   # 抽不到即红, 不静默跳过


def test_e5_baseline_metrics_match_a_live_rerun() -> None:
    """E5 基准装配 B3 的**指标值**必须与真跑重算一致 (不再只对账规模类数字)。

    这是本文件对"不可廉价复算的分数"那条纪律的**唯一一处例外**, 理由与边界:

      - **为什么必须**: 2026-10-05 实测到 ``evals/ablation/REPORT.md`` 相对
        HEAD 过期 7 行 HR 指标 (commit ``1893cfd`` 改了 HR 口径却没重生成报告),
        而当时的门禁全绿 —— 因为 ``CLAIMS`` 只对账题数/系统数, 那些数一个都没变。
        指标漂移就是这么一路无人发现的。
      - **为什么只锁 B3**: 全量跑批实测 46s (990 个 run + 20s 聚合), 塞进
        ``make test`` 会让门禁慢到被绕过。单装配重算实测 6.2s, 且跑批矩阵按
        (装配 × 任务 × 重复) 独立, B3 的指标与另外 10 个装配无关。
      - **覆盖边界 (不冒充)**: 其余 10 个装配的指标值**仍无自动守护**, 漂移
        靠 ``make eval-e5`` 重生成后人工对账。B3 行恰好是那次真实漂移涉及的行
        之一, 故这条对已知缺陷非空转。

    断言逐个指标比字符串形态 (报告里就是三位小数的文本): 比浮点值会在
    "0.800 vs 0.8" 上假红, 而报告的呈现形态本身就是被断言的对象。
    """
    card = _e5_recompute_baseline()                      # 真跑一次拿基准值: 替身批, 全离线
    row = _e5_report_row("B3")                           # 报告里 B3 那一行
    keys = _e5_t1_columns()                              # 主表列序 (自实验侧 import)
    assert len(row) == len(keys) + 1, (                  # +1 是首格的系统 id
        f"E5 主表 B3 行有 {len(row)} 个单元格, 而 T1_COLUMNS 只有 {len(keys)} 个指标列 "
        f"({keys}) —— 报告结构变了, 本门禁须同步"
    )
    drift = [f"{key}: 报告 {row[i + 1]!r} vs 重算 {_reported(key, card.get(key))!r}"   # 逐指标列名报出差异
             for i, key in enumerate(keys)               # 索引 +1: 首格是系统 id, 不参与比对
             if row[i + 1] != _reported(key, card.get(key))]  # 比呈现文本而非浮点: 避免 0.800 vs 0.8 假红
    assert not drift, (                                  # 攒齐再报: 一次看全比首错即抛利于整改
        "E5 REPORT.md 的 B3 指标值与真跑重算不符 (报告相对代码过期):\n  "
        + "\n  ".join(drift)
        + "\n  重生成: make eval-e5"
    )


def _fmt_like(value: object, digits: int = 3) -> str:
    """按 E5 报告的呈现口径格式化指标值 (与 report.py::_fmt 同款)。

    Args:
        value: 成绩单里的原始指标值。
        digits: 小数位数; 成本侧的请求数等小计数走整数形态 (三位小数没有信息量)。

    Returns:
        报告里应当出现的那个字符串; ``None`` 显式渲染成 ``N/A``, 绝不记成 0。
    """
    if value is None:
        return "N/A"                                      # 缺失显式写 N/A, 绝不记成 0
    if isinstance(value, bool):
        return str(value)                                 # 布尔不走浮点格式化 (True → "1.000" 是错的)
    return f"{float(value):.{digits}f}"                   # 按传入位数格式化: 与报告呈现逐字对齐


# 主表里走整数形态的那一列 (请求数是小计数); 表 4 全是比率, 不在此列。
E5_INTEGER_COLUMNS: frozenset[str] = frozenset(E5_EXTRA_T1_COLUMNS)   # 整数列名集合


def _reported(key: str, value: object) -> str:
    """按该列在报告里的呈现口径格式化一个重算值。"""
    return _fmt_like(value, digits=0 if key in E5_INTEGER_COLUMNS else 3)   # 整数列零位小数


def test_e5_baseline_hr_channels_match_a_live_rerun() -> None:
    """E5 基准装配 B3 的**幻觉三通道**指标 (表 4) 必须与真跑重算一致。

    与上一条分列而非并进一条: 表 4 才是 2026-10-05 那次漂移真正发生的表
    (7 行全在 HR 通道上), 而表 1 的那几列当时没动。两条分开红, 红了能一眼
    看出漂的是哪张表。
    """
    card = _e5_recompute_baseline()                      # 同上: 复算基准值
    row = _e5_hr_report_row("B3")                        # 表 4 里 B3 那一行
    keys = _e5_hr_columns()                              # HR 通道列序 (自实验侧 import)
    assert len(row) == len(keys) + 1, (                  # +1 是首格的系统 id
        f"E5 表 4 的 B3 行有 {len(row)} 个单元格, 而 HR_COLUMNS 有 {len(keys)} 列 "
        f"({keys}) —— 报告结构变了, 本门禁须同步"
    )
    drift = [f"{key}: 报告 {row[i + 1]!r} vs 重算 {_fmt_like(card.get(key))!r}"   # 逐通道列名报出差异
             for i, key in enumerate(keys)               # 索引 +1: 首格是系统 id
             if row[i + 1] != _fmt_like(card.get(key))]  # 比呈现文本而非浮点
    assert not drift, (                                  # 攒齐再报, 便于一次整改
        "E5 REPORT.md 表 4 的 B3 幻觉通道指标与真跑重算不符 (报告相对代码过期):\n  "
        + "\n  ".join(drift)
        + "\n  重生成: make eval-e5"
    )


def test_e5_metric_guard_is_not_vacuous() -> None:
    """这道指标门禁必须**对已知缺陷非空转**: 喂一份改过的报告数字就得红。

    为什么要有这条自检: 上面两条若因某种原因恒真 (抽错行、格式化写错、
    判据写成永远为真的空断言), 它们会像 J7 描述的那样"看起来在核对"实则
    对错对象。这里把报告里的一个 HR 数字换成别的值再判一次, 确保判据真的
    在比 —— 用临时副本换, 不动磁盘上的真报告。
    """
    card = _e5_recompute_baseline()                      # 真跑一次拿基准值 (全离线)
    row = _e5_hr_report_row("B3")                        # 表 4 里 B3 那一行
    keys = _e5_hr_columns()                              # HR 通道列序
    idx = keys.index("HR_any") + 1                       # +1: 跳过首格的系统 id
    tampered = list(row)                                 # 复制一份再改: 不动磁盘上的真报告
    tampered[idx] = "0.123"                              # 换成任何别的值都该被抓
    drift = [key for i, key in enumerate(keys)           # 复算同一套判据, 只是喂改过的行
             if tampered[i + 1] != _fmt_like(card.get(key))]
    assert "HR_any" in drift, (                          # 判据在动真格地比, 不是恒真
        "篡改 HR_any 后判据仍报一致 —— 指标门禁空转, 它抓不到任何漂移"
    )


# 逐条对账表: (实验, 该数的含义, 重算函数, 报告里该数的正则)。
# 正则刻意锚在**中文标签 + 数字**上而不是裸数字 —— 裸数字在报告里到处都是, 抽错
# 一行就会造出"看起来在核对"实则对错对象的假门禁。
CLAIMS: tuple[tuple[str, str, object, str], ...] = (
    ("E1", "任务数", _e1_task_count, r"任务数:\s*(\d+)/\d+"),
    ("E3", "题数", _e3_item_count, r"题数:\s*(\d+)"),
    ("E3", "fixture 题数", lambda: _e3_tier_count("fixture"), r"题数:\s*\d+\s*\(fixture\s*(\d+)"),
    ("E3", "live 题数", lambda: _e3_tier_count("live"), r"fixture\s*\d+\s*/\s*live\s*(\d+)"),
    ("E4", "用例集总数", _e4_total, r"用例集:\s*(\d+)\s*条"),
    ("E4", "主用例数 (RB-01..RB-NN)", _e4_main_count, r"RB-01\.\.RB-(\d+)\s*主用例"),
    ("E4", "主用例 Tier P", lambda: _e4_main_tier_count("P"), r"主用例\s*(\d+)\s*P"),
    ("E4", "主用例 Tier W", lambda: _e4_main_tier_count("W"), r"主用例\s*\d+\s*P\s*\+\s*(\d+)\s*W"),
    ("E4", "复合变体数", _e4_composite_count, r"RB-C01\.\.RB-C(\d+)\s*复合变体"),
    ("E5", "任务数", _e5_item_count, r"规模:\s*(\d+)\s*任务"),
    ("E5", "系统数", _e5_system_count, r"任务\s*×\s*(\d+)\s*系统"),
    ("E6", "任务数", _e6_task_count, r"任务集:\s*(\d+)\s*条"),
    ("E2", "金标准份数", _e2_gold_count, r"(\d+)\s*份金标准"),
    ("E2", "场景数", _e2_scenario_count, r"(\d+)\s*个场景"),
)


def test_every_report_claim_matches_the_data() -> None:
    """六个实验 REPORT.md 的规模类数字必须与题集实数一致 (逐条对账)。"""
    bad: list[str] = []                          # 攒齐再报: 一次看全比首错即抛利于整改
    for exp, label, recompute, pattern in CLAIMS:  # 逐条对账项过一遍
        want = claimed_int(report_text(exp), pattern, exp)  # 报告声称的数 (抽不到即红)
        got = recompute()                        # 从题集当场重算的数
        if want != got:                          # 对不上就是报告漂移
            bad.append(f"{exp} {label}: 报告称 {want}, 题集实为 {got} (正则 {pattern!r})")
    assert not bad, "REPORT.md 与题集事实脱节 (报告漂移):\n  " + "\n  ".join(bad)


def test_all_six_experiments_have_a_checked_claim() -> None:
    """有 REPORT.md 的实验目录必须都在对账表里 —— 防止覆盖面静默缩小。

    挡的是"门禁覆盖面悄悄缩了": 将来加了 E7 却在 CLAIMS 里忘了登记, E7 的报告
    漂移就没人管, 而 E7 的存在本身不会发出任何信号提醒谁去补这条。
    """
    covered = {EXP_DIRS[exp] for exp, *_ in CLAIMS}          # 对账表覆盖到的目录名
    on_disk = {p.parent.name for p in REPORTS.glob("*/REPORT.md")}  # 盘上真有报告的目录名
    missing = on_disk - covered
    assert not missing, (
        f"这些实验有 REPORT.md 却没有对账项, 报告漂移将无人发现: {sorted(missing)}"
    )


def test_e1_task_count_is_self_consistent() -> None:
    """E1 声称的 "26/26" 两处数字必须相等 (分子分母不一致即报告自相矛盾)。"""
    text = report_text("E1")
    done = claimed_int(text, r"任务数:\s*(\d+)\s*/", "E1")  # 分子
    total = claimed_int(text, r"任务数:\s*\d+\s*/\s*(\d+)", "E1")  # 分母
    assert done == total, (
        f"E1 报告自相矛盾: 任务数写作 {done}/{total} —— 有缺轨迹时分子应小于分母, "
        "且报告必须写清缺的是哪几条"
    )


def test_e1_verdict_agrees_with_its_own_score() -> None:
    """E1 声称的"判定"必须与它自己写的加权总分同向, 否则报告自身打架。

    只做**报告内部**核对 (不需要跑批), 因此可以在 make test 里常驻。跨档位的
    分数比较一律不做 —— 各实验口径不同, 归一后会造出假红。
    """
    text = report_text("E1")
    m_score = re.search(r"加权总分:\s*([\d.]+)", text)      # 分数是浮点, 走独立正则不走整数通道
    m_verdict = re.search(r"判定:\s*([A-Za-z]+)", text)     # 判定是文字, 同样独立抽
    assert m_score, "E1: 报告里找不到 '加权总分' 声明"
    assert m_verdict, "E1: 报告里找不到 '判定' 声明"
    total = float(m_score.group(1))                         # 解析成数值再比大小
    verdict = m_verdict.group(1).upper()                    # 归一大小写: 报告两种写法都出现过
    if verdict == "PASS":
        assert total >= 0.90, f"E1 报告判定 PASS 但加权总分只有 {total} (通过线 0.90) —— 自相矛盾"
    elif verdict == "FAIL":
        assert total < 0.90, f"E1 报告判定 FAIL 但加权总分 {total} 已过通过线 0.90 —— 自相矛盾"


def test_e2_gold_and_scenario_counts_agree() -> None:
    """E2 的金标准份数与场景数必须相等 (一个场景一份金标准, 多一份即孤儿)。"""
    gold, scen = _e2_gold_count(), _e2_scenario_count()
    assert gold == scen, (
        f"E2 存在孤儿资产: gold/*.json (去掉 manifest.json) {gold} 份, "
        f"scenarios/*.yaml {scen} 份 —— 两者必须一一对应, 否则多出来的那份无人核对"
    )


def test_e5_system_count_agrees_across_the_report() -> None:
    """E5 的系统数在两处出现 (规模行与表 1 标题), 且必须与装配表实数一致。

    E5 没有独立的重复次数事实源 (它由跑批命令行决定, 不落在题集里), 所以那条
    只能做报告**内部**一致性对账。这是刻意降级的口径, 已在模块 docstring 的
    "不可廉价复算" 一节登记, 不冒充跨源对账。
    """
    text = report_text("E5")
    t1 = re.search(r"表 1 · 主表 \(T1:\s*(\d+)\s*装配", text)  # 表 1 标题里的装配数
    assert t1, "E5: 找不到 '表 1 · 主表 (T1: N 装配 …)' 标题"
    real = _e5_system_count()                                   # 装配表实数
    assert int(t1.group(1)) == real, (
        f"E5 表 1 标题称 {t1.group(1)} 个装配, 装配表实为 {real} 个 —— 报告自相矛盾"
    )
    repeat = re.search(r"系统\s*×\s*(\d+)\s*次重复", text)  # 重复次数: "11 系统 × 3 次重复"
    assert repeat and int(repeat.group(1)) >= 1, f"E5 重复次数声明非法或缺失: {repeat}"


def test_e4_tier_w_denominator_matches_tier_sizes() -> None:
    """E4 报告称 'Tier W 15/15 PASS', 分母必须等于主用例 Tier W 的实数条数。

    只校验分母 —— 分子是跑批结果, 复算它要真跑一遍, 不塞进 make test。分子漂移
    靠人复跑对账, 这条不冒充已覆盖。
    """
    text = report_text("E4")
    m = re.search(r"Tier W \(程序判定\):\s*\**(\d+)/(\d+)", text)  # 分子/分母两条捕获
    assert m, "E4: 报告里找不到 'Tier W (程序判定): n/m' 声明"
    denom = int(m.group(2))                                      # 取分母
    real = _e4_main_tier_count("W")                              # 主用例 Tier W 实数
    assert denom == real, (
        f"E4 报告称 Tier W 主线 {denom} 条, 题集实为 {real} 条 —— 分母对不上"
    )
