# -*- coding: utf-8 -*-
"""evals.ablation.harness.run_batch — E5 跑批编排 (30 任务 × N 系统 × repeat)。

能力边界 (docs/eval-E5-baseline-ablation.md §10 执行流程):
装配 (systems/*.yaml) → 绑定 (items + snapshot/fixture) → 跑批 (repeat 次)
→ L0 三门判定 (metrics/composite.py) → 反证自测 (broken/) → 报告 (report.py)。

**回放 (自包含, 纪律注记)**: D 类按 ``data_anchor.ref`` 挂
:class:`ReplayTransport` — 两阶段协议的最小回放 + 查询语义模拟 (解析 POST 表单,
对 rows_full.csv 独立执行后现场算答案)。它当初是
evals/groundtruth/transport.py (已删除) 的同语义精简版: 按本仓"零跨实验 import"
纪律自带一份实现 (可读不可 import)。那份权威件已于 2026-10-07 删除, 故本副本
现已无对照物, 传输层的等价性无从比对; ``evals/equivalence`` 现守的是**判定口径**
等价 (行主键/哨兵), 不含传输实现 —— 本文件的 ``row_key`` 属 E5 自用的简化件
(坐标缺测塌成 0.000000000), 刻意不进那道对账。回放一律 ``rate_limit=0.0``
(E5 §13: 默认 2.0 节流会让回放 100 页真睡 200 秒, 延迟指标全废)。

**确定性 (E6 R0 同款)**: 同一 (items, 系统) 重复跑 N 次, ``fingerprint``
必须一致 — 轨迹指纹排除 elapsed_s (wall-clock 天生抖动), 其余逐字节纳入哈希。

**成本口径 (E5 §6.7)**: ``http_requests`` 由回放/客户端实测计数 (非估算);
``tokens_in``/``tokens_out`` 一律记 ``null`` — API usage 缺失即缺失,
**禁止估算填数**。

所属实验: E5 基线与消融 (30 任务 × 10 系统 + sham 共 11 装配, ScriptedLLM 离线跑;
成功率 = ScriptedLLM 跑通率而非模型能力), 方案真值 docs/eval-E5-baseline-ablation.md
§10 (执行流程) / §6.7 (成本口径) / §13 (已知坑位)。本文件是 E5 的**编排层**:
它只负责装配、绑定与逐 run 记录, 一条 run 的判定交给 metrics/composite。

对外接口: run_matrix(system_names, items, repeat, category, seed) -> 跑批报告
(逐 run 记录 + 确定性声明); run_once(system, item, attempt) -> 单条 run 记录;
load_items / load_systems / select_items (装载与筛选); row_key (行主键口径);
write_traces (逐 run 轨迹落盘); ReplayTransport / FakeResponse (自包含回放);
main (CLI 入口)。

依赖与数据流: 输入 = systems/*.yaml 装配表 + items.yaml 任务集 + E2 快照目录
(按 data_anchor.ref 绑定) + adapters/llm 层; 产物 = 内存里的跑批报告, 以及
write_traces 落下的 runs/<system>/<item>__aN.json 轨迹 (只增不改)。

关键契约与不变量: 离线回放 —— 全部 IO 落在本地快照与内存, rate_limit 归零,
不接真实模型、不打真实站点; 零跨实验 import —— 唯一共享件是 evals/_data/ 纯数据
字典, 本文件按路径读它而不 import 它; **与 E2 transport 的等价性无断言覆盖**
(见上文与 equivalence/import_isolation.py:15);
确定性 —— 顺序随机化只由显式 seed 驱动 (绝不读系统随机源), 否则重复跑的指纹
不可能一致; 缺文件/空任务集一律抛 (fail-closed, 不静默跳过)。

陷阱与边界: 为什么自带一份 ReplayTransport 而不复用 E2 的 —— import 即跨实验
依赖, 违反铁律 6, 代价是两份实现要靠等价性断言兜住漂移; rate_limit 必须由调用方
显式置 0.0, 这里不替调用方决定, 因为 E2 的跑批要 2.0 的真实节流语义; 任务序
随机化只对"系统与评阅人各自随机化"的场景有意义 (E5 §9), 给了 seed 才生效,
没给 seed 就保持 items.yaml 的原序以便逐条比对; 轨迹里的 elapsed_s 进了报告但
**不得**进指纹, 否则 wall-clock 抖动会让确定性自证永远失败。

白盒锚点: docs/eval-E5-baseline-ablation.md §10 (执行流程) / §6.7 (成本口径) /
§13 (已知坑位); src/protocol.py (两阶段 URL 形态 — 路由判定依据)。
"""
from __future__ import annotations

# 标准库: CSV 行集 / JSON / 路径 / 随机 (顺序随机化) / 计时 / 类型标注
import csv
import json

# 标准库: 进程号 (临时文件名) 与原子提交/排他打开 (轨迹写的并发保护执行者)
import os
import random
import time
from pathlib import Path
from typing import Any, Optional

import yaml

from evals.ablation.harness.adapters import (
    RunOutcome,  # 运行结果类型: 编排层只认这个结构, 不直接碰适配器内部状态
    make_adapter,  # 装配入口: 工具面差异全在这一层的参数里
    make_llm,  # scripted 模型入口: 它决定路由与工具选择, 不接真实模型
    trace_fingerprint,  # 指纹函数在此导入: 确定性自证必须用同一份实现, 不另写一份
)

# 本地: 共享纯函数层 (哨兵/数值/行集/参数预检的对账单点)
from evals.ablation.harness.support import (
    column_of,  # 行内取列: 排序列解析与渲染层共用这一套口径
    coord_of,  # 坐标兜底: 锥形过滤算角距的前提
    haversine_arcsec,  # 角距公式取自共享件: 不在本文件另抄一份, 免得两边漂移
    to_float,  # 安全转数值: 哨兵与非数值列都靠它统一处理
)

ABLATION_DIR = Path(__file__).resolve().parents[1]  # 锚点只算一次: run 记录不存绝对路径, 跨机复跑不被路径绑死
EVALS_DIR = Path(__file__).resolve().parents[2]  # eval 包根: 供 SNAPSHOTS_DIR 逐层上溯
SYSTEMS_DIR = ABLATION_DIR / "systems"                                                          # 装配表目录: 缺任一文件即抛, 不静默少一个系统
ITEMS_PATH = ABLATION_DIR / "items.yaml"                                                            # 任务集路径: 三十条固定, 空集即抛
RUNS_DIR = ABLATION_DIR / "runs"                                                                 # 轨迹落盘根目录: 只增不改, 便于两轮跑批对照
# 只按路径读 E2 快照: 零跨实验 import 下"可读不可 import"的落点
SNAPSHOTS_DIR = EVALS_DIR / "groundtruth" / "snapshots"                                     # 快照按路径读而不 import: 这是零跨实验依赖的落点

# 跑批顺序 (主表序; 任务序由 --seed 随机化 — E5 §9 顺序/学习效应控制)
SYSTEM_ORDER: tuple[str, ...] = ("B0", "B1", "B2a", "B2b", "B3",
                                 "A1", "A2", "A3", "A4", "A5", "A6", "sham_placeholder")

# 系统 id → systems/ 下的文件名 (装配表的权威拼写)
SYSTEM_FILES: dict[str, str] = {  # 显式映射而非拼字符串: 文件名带层级 (b2a/b2b) 且有下划线, 拼串会错
    "B0": "b0_bare", "B1": "b1_docs", "B2a": "b2a_raw_api", "B2b": "b2b_raw_tools",
    "B3": "b3_full", "A1": "a1_no_validation", "A2": "a2_no_semantics",
    "A3": "a3_no_refusal", "A4": "a4_no_provenance", "A5": "a5_no_postcheck",
    "A6": "a6_no_envelope",  # 2026-10-10 采集前补登记: 统一信封此前无单件对照 (方案 §11 缺陷 10)
    "sham_placeholder": "sham_placeholder",
}


# ── 自包含回放传输层 (evals/groundtruth/transport.py 已删除前的同语义精简版) ─

class FakeResponse:
    """requests.Response 最小替身 (快照原文载体; 保留 BOM/无表头/哨兵)。"""

    def __init__(self, status_code: int, text: str) -> None:
        """记录状态码与回包原文 (保真读取, 不转码)。"""
        self.status_code = status_code                                                   # 状态码原样存: 软 404 判据全靠它区分 200 与 4xx
        self.text = text  # 不做任何归一: 替身一美化, BOM/无表头/哨兵这些脏形态就测不出了
        self.headers: dict = {}  # 留空 dict 而非 None: 注入器/断言可能直接索引, None 会炸
        self.closed = False  # 记 closed 而非空做: 有调用方拿它判断"是否走了 close 路径"

    def raise_for_status(self) -> None:
        """非 2xx 抛 requests.HTTPError (与真实 requests 同语义)。"""
        # 第三方: 异常类型判定 (回放路径的失败分支)
        import requests

        if self.status_code >= 400:  # 软 404 是 200 + 错误体: 在此抛就等于替被测链路做了包装检测
            raise requests.HTTPError(f"{self.status_code} replay error", response=self)

    def close(self) -> None:
        """标记关闭 (流读尽后被测链路会调; 快照无真实句柄)。"""
        self.closed = True                                                                 # 只记标志不真关: 快照没有真实句柄, 调用方却会查这个字段

    def iter_content(self, chunk_size: int = 1):
        """字节流迭代 (下载类消费; 按整文本一次性产出)。"""
        data = self.text.encode("utf-8")  # 刻意保留分块循环: 一次性 yield 整包会绕过块边界逻辑
        for start in range(0, len(data), chunk_size):                                         # 按块切分产出: 一次性产出会绕过被测链路的块边界逻辑
            yield data[start:start + chunk_size]


def _query_param(url: str, name: str) -> Optional[str]:
    """从 URL 查询串取参数 (无查询串/无该参数 → None)。"""
    if "?" not in url:
        return None  # 没有 "?" 就直接退: 第二阶段 URL 未必都带查询串
    for pair in url.split("?", 1)[1].split("&"):
        # 按第一个 "=" 切: 值里可能自带 "=" (如 base64), 无上限切会截断
        if "=" in pair:
            key, value = pair.split("=", 1)
            if key == name:                                                              # 逐对扫描而不是建字典: 查询串参数很少, 线性扫更贴近真实解析
                return value
    return None


class ReplayTransport:
    """E5 精简回放 (哑回放 + 查询语义模拟; SnapshotTransport 的私有同语义件)。

    路由规则: POST ``/{catalog}/q`` → phase1.html (记录表单查询语义);
    GET 含 ``/getcount`` → 查询后总数; GET 含 ``/sqlid/`` 且 ``page=N`` →
    查询后当页 CSV; 其余 GET → 404 替身。用法::

        client = BestClient(base_url="http://snapshot.local", rate_limit=0.0)
        client.session.get = transport.get
        client.session.post = transport.post
    """

    def __init__(self, snap_dir: str | Path) -> None:
        """记住快照目录 (不存在即抛 — 回放目标必须真实存在)。"""
        self.snap_dir = Path(snap_dir)                                                        # 快照目录先归一成路径对象: 后面多处拼接不再各自转换
        # fail-closed: 不回退空快照 —— 那会把所有题判成"合法 0 行", 整批跑绿却无信息量
        if not self.snap_dir.is_dir():                                                   # 缺快照即抛: 回落空快照会把所有题判成合法 0 行, 整批假绿
            raise FileNotFoundError(f"回放快照缺失: {snap_dir}")
        self.call_count = 0  # http_requests 的事实源: 成本口径要求实测而非估算 (§6.7)
        self._form: dict[str, str] = {}  # 表单语义缓存: POST 记一次, 后续 GET 据此现场执行查询再分页
        self._rows_cache: Optional[list[dict]] = None  # None = 未装载; 空列表 = 装载过且确实为空

    def _read(self, rel_path: str) -> str:
        """读快照内文件原文 (utf-8-sig 兼容 BOM — 保真不转码)。"""
        return (self.snap_dir / rel_path).read_text(encoding="utf-8-sig")  # 转码会把 BOM 混进首列名, 列对齐随之全错

    def _load_rows(self) -> list[dict]:
        """读 rows_full.csv (懒加载 + 缓存; 缺失即空 — 错误态快照无真值行)。"""
        if self._rows_cache is None:  # 懒加载: 不是每条 case 都翻页, 无条件读盘会多出几百次无谓 IO
            path = self.snap_dir / "rows_full.csv"
            if not path.is_file():  # 缺真值文件 = 错误态/空态快照: 返空列表让"0 行"成为真实结论
                self._rows_cache = []                                                    # 缺真值文件按空集缓存: 错误态快照的 0 行是真实结论而非缺陷
            else:
                with path.open("r", encoding="utf-8-sig", newline="") as handle:  # newline="": 否则字段里的 \n 会被改写
                    self._rows_cache = [dict(r) for r in csv.DictReader(handle)]         # 每行转成普通字典: 后续按列名取值不必依赖 reader 状态
        return self._rows_cache

    def get(self, url: str, **kwargs: Any) -> FakeResponse:
        """顶替 session.get: getcount 回查询后总数; page 回查询后当页 CSV。

        Args:
            url: 两阶段协议的第二阶段 URL (含 page/rows 参数)。
            kwargs: 签名对齐 (与 requests.Session.get 同形), 本层不消费。

        Returns:
            FakeResponse: getcount 给 JSON 总数, 数据页给当页 CSV, 其余 404。
        """
        self.call_count += 1  # 计数在路由之前: 被短路返回的故障回包也是一次真实请求, 成本口径要算它
        if "/getcount" in url:
            return FakeResponse(200, json.dumps({"total": len(self._apply())}))
        if "/sqlid/" in url:
            page = int(_query_param(url, "page") or "1")  # page/rows 缺省成 1/1000: 站点不带参数即第一页满页
            page_size = int(_query_param(url, "rows") or "1000")
            chunk = self._apply()[(page - 1) * page_size: page * page_size]  # 切片分页: 末页自然变短, 再往后取就是空页
            return FakeResponse(200, self._to_csv(chunk))
        return FakeResponse(404, "<html>404</html>")

    def post(self, url: str, **kwargs: Any) -> FakeResponse:
        """顶替 session.post: 记录表单查询语义, 回 phase-1 HTML。

        Args:
            url: 提交查询的 POST 地址 (仅用于记账, 不解析路径)。
            kwargs: 与 requests 同形, 这里只消费 data (表单体)。

        Returns:
            FakeResponse: 有 phase1.html 就回原文, 否则回"无 sqlid"的等价回包。
        """
        self.call_count += 1                                                          # POST 也是一次真实请求: 成本口径要算它, 否则孤儿会话判据会漏
        data = kwargs.get("data") or {}  # 只取 data: 站点走表单提交, 查询语义全在表单里
        self._form = {str(k): str(v) for k, v in data.items()}  # 全转字符串: 表单值上 URL 也是字符串, 归一后下游不必各写一次
        if (self.snap_dir / "phase1.html").is_file():
            return FakeResponse(200, self._read("phase1.html"))
        return FakeResponse(200, "<html>no sqlid</html>")  # 仍回 200 但不带 sqlid: 让"解析失败"成为可判现场

    # -- 查询语义 (空间 → 最近邻 → 排序) ──

    def _apply(self) -> list[dict]:
        """按已记录表单执行查询 (协议语义的假服务器侧落实)。"""
        rows = self._load_rows()                                                              # 先取全量行: 过滤与排序都在这一份上做, 不多次读盘
        pos_type = self._form.get("pos.type", "none")  # 缺省 none: 表示本次查询没有位置约束
        if pos_type == "cone":
            rows = self._cone(rows)                                                              # 锥形过滤按位置类型分流, 缺位置约束就原样放行
        elif pos_type == "proximity":
            rows = self._proximity(rows)                                                           # 就近模式与锥形互斥, 一次查询只走其中一支
        return self._sort(rows)  # 排序恒在最后: 顺序反了会把未过滤的行混进结果

    def _cone(self, rows: list[dict]) -> list[dict]:
        """锥形过滤 (pos.racenter/pos.deccenter/pos.radius; d ≤ radius 含等号)。"""
        ra_c = to_float(self._form.get("pos.racenter"))
        dec_c = to_float(self._form.get("pos.deccenter"))
        radius = to_float(self._form.get("pos.radius"))
        if ra_c is None or dec_c is None or radius is None:  # 缺一就不滤: 拿 0 当中心去滤会得出"空结果"的假结论
            return rows
        return [r for r in rows if haversine_arcsec(ra_c, dec_c, *coord_of(r)) <= radius]

    def _proximity(self, rows: list[dict]) -> list[dict]:
        """proximity: 冻结答案直通 + nearestonly 时每输入行只留最小角距行。"""
        if "proximity_nearestonly" not in self._form:
            return rows  # 没带 nearestonly 就原样放行: 该模式冻结答案, 不该由本层重算
        best: dict[str, dict] = {}  # 按 input_line 分组: 一个输入坐标对应一行, 行号即分组键
        for row in rows:                                                                         # 逐行归到它的输入行: 一个输入坐标对应一行结果
            line = str(row.get("inputobjs_input_line", ""))
            dist = to_float(row.get("inputobjs_dist_arcsec"))
            current = best.get(line)                                                              # 取出该输入行当前的最近候选, 后面与它比角距
            if current is None:  # 该输入行的首个候选直接占位, 后面才有可比对象
                best[line] = row                                                                 # 首个候选直接占位: 还没有可比对象, 先记下来
                continue
            current_dist = to_float(current.get("inputobjs_dist_arcsec"))
            if dist is not None and (current_dist is None or dist < current_dist):  # 距离缺失时让位: 角距不可比的行不能当"最近邻"
                best[line] = row                                                            # 角距更小才替换: 距离缺失时让位, 不可比的行不当最近邻
        return [best[line] for line in sorted(best)]  # 按行号排序输出: 站点按输入顺序返回, 顺序变了行集就不一致

    def _sort(self, rows: list[dict]) -> list[dict]:
        """按 sort/order 排序 (限定列名 → 行内取列; 无排序列则保持文件序)。"""
        key = self._form.get("sort")
        if not key:                                                                          # 无排序列就保持文件序: 自行排序会破坏金标准的行序假设
            return rows  # 没有排序列就保持快照文件序: 自行排序会破坏金标准的行序假设
        return sorted(rows, key=lambda r: to_float(column_of(r, key)) or 0.0,  # or 0.0: 不可解析值按 0 排, sorted 不炸
                      reverse=(self._form.get("order") or "asc") == "desc")

    @staticmethod
    def _to_csv(rows: list[dict]) -> str:
        """行字典列表 → CSV 文本 (列序取首行键序; 空结果给空文本 — 末页形态)。"""
        if not rows:                                                                     # 空结果单独分支: 末页就是空体, 不该再吐一个带表头的 CSV
            return ""  # 空串而非带表头的 CSV: 站点末页就是空体, 对齐才测得出"续取一页得空页"
        # 标准库: CSV 文本的内存读写 (查询语义模拟的页序列化)
        import io

        buffer = io.StringIO()                                                               # 内存里拼 CSV: 不落盘, 页文本只在响应里短暂存在
        writer = csv.DictWriter(buffer, fieldnames=list(rows[0].keys()))  # 列序取首行键序: DictWriter 靠 fieldnames 定位每格
        writer.writeheader()                                                                  # 表头必写: 缺列与哨兵这些脏形态正是靠表头才看得出来
        writer.writerows(rows)                                                                      # 一次写完当页所有行, 列序沿首行键序
        return buffer.getvalue()


# ── 装载 ────────────────────────────────────────────────────────────────────

def load_items(path: Optional[Path] = None) -> list[dict]:
    """读 items.yaml 的 30 条任务 (禁 version 键; 缺字段由调用方判 FAIL)。

    Args:
        path: 可选的 items.yaml 路径 (默认用包内那份)。

    Returns:
        任务列表; 空任务集抛 ValueError。

    抛什么: 任务集为空时 ValueError (空跑批没有信息量, 静默返空会假绿)。
    """
    data = yaml.safe_load((path or ITEMS_PATH).read_text(encoding="utf-8")) or {}
    items = data.get("items") or []
    # fail-closed: 空任务集必须显式炸, 否则 30×11 的矩阵会跑成 0×11 却"全过"
    if not items:                                                                            # 空任务集必须炸: 否则矩阵跑成 0×11 却报"全过"
        raise ValueError(f"任务集为空: {path or ITEMS_PATH}")
    return items


def load_systems(names: Optional[list[str]] = None) -> dict[str, dict]:
    """读 systems/*.yaml 装配表 (缺文件即抛 — fail-closed, 不静默跳过)。

    Args:
        names: 要装载的系统 id 列表 (None = SYSTEM_ORDER 全体)。

    Returns:
        {系统 id: 装配 dict}。

    抛什么: 缺任一装配文件即 FileNotFoundError —— 少一个系统会让主表少一行,
    而报告仍能渲染出"看起来完整"的表, 那是最危险的一类假绿。
    """
    wanted = list(names) if names else list(SYSTEM_ORDER)                                           # 未指定即主表全体: 报告列序要跟着主表走
    systems: dict[str, dict] = {}                                                            # id 映射到装配体: 后面按 id 取, 不按文件名取
    for name in wanted:                                                                        # 逐个装载: 缺一个就抛, 不给"少一行还绿"的机会
        path = SYSTEMS_DIR / f"{SYSTEM_FILES.get(name, name)}.yaml"  # 查表拿文件名, 查不到就拿 id 当名: 自定义系统可临时加 yaml 不改代码
        if not path.is_file():                                                             # 缺装配文件即抛: 少一个系统会让主表少行而报告仍渲染得出来
            raise FileNotFoundError(f"系统装配缺失: {path}")
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        systems[str((data.get("system") or {}).get("id") or name)] = data["system"]  # 以 yaml 里的 id 为准: 文件名可能改过
    return systems


def select_items(items: list[dict], category: Optional[str] = None,
                 seed: Optional[int] = None) -> list[dict]:                                # 种子显式传入: 随机化只能由调用方决定, 绝不读系统随机源
    """按层筛选 + 顺序随机化 (E5 §9: 任务顺序按系统与评阅人各自随机化)。"""
    chosen = [i for i in items if category in (None, "", "all")  # None/空/"all" 都算全选: CLI 默认档位就是 "all"
              or str(i.get("id", "")).startswith(f"E5-{category}")]
    ordered = list(chosen)                                                                   # 复制一份再洗牌: 调用方传进来的列表顺序不能被就地改掉
    if seed is not None:  # 只在给了 seed 时才洗牌: 不给就保持原序, 便于逐条 diff 两轮跑批
        random.Random(seed).shuffle(ordered)  # noqa: S311  # 任务序洗牌, 非密码用途; 显式 seed 保证确定性
    return ordered


# ── 跑批 ────────────────────────────────────────────────────────────────────

def run_once(system: dict, item: dict, attempt: int = 1, capture: Optional[dict] = None) -> dict:
    """跑一次 (系统 × 任务); 返回含轨迹与指纹的 run 记录 (只增不改)。"""
    anchor = item.get("data_anchor") or {}
    # 只有锚到 E2 快照的题才有回放底座: fixture 与 none 类题不走传输层
    transport = None                                                                     # 默认无回放底座: fixture 与 none 类题不走传输层
    if anchor.get("kind") == "snapshot" and anchor.get("ref"):
        transport = ReplayTransport(SNAPSHOTS_DIR / str(anchor["ref"]))
    adapter = make_adapter(system, transport)  # transport 传 None 也是合法装配: 非快照题走 fixture 路径
    # 模型层: capture 非空即 live 臂 (CapturedLLM), 否则 ScriptedLLM 替身。两种实现
    # 的 plan/render 签名不同 (替身无 attempt), 所以按签名能力分流而不是改两边接口 ——
    # 替身保持零参数, 不为 live 臂改形状。
    llm = make_llm(system, capture)
    # plan 先于 execute: 路由与工具选择是"调什么", 执行才是"调出什么"
    plan_kwargs = {"attempt": attempt} if hasattr(llm, "coverage") else {}
    route, calls = llm.plan(item, **plan_kwargs)                                         # 先规划再执行: "调什么"与"调出什么"分开才看得清消融效应
    outcome: RunOutcome = adapter.execute(item, calls, route)                              # 执行产出观测事实: 行集与报告态都从这里来, 不由渲染层编
    if plan_kwargs:  # live 臂: 答案文本同样按 attempt 回放, 不由判据层重渲染
        outcome.answer_text = llm.render(item, outcome, **plan_kwargs)
    else:
        outcome.answer_text = llm.render(item, outcome)  # 渲染在执行之后: 答案要看到真实观测到的行集与报告态
    outcome.turns = 2 if item.get("route") == "clarify" else 1  # scripted 口径: 澄清题天然两轮 (问 + 答)
    return {
        "system": system.get("id"),
        "item": item.get("id"),
        "attempt": attempt,  # attempt 参与轨迹文件名: repeat>1 时同名会互相覆盖
        "route": outcome.route,
        "turns": outcome.turns,
        "tool_calls": outcome.tool_calls,
        "envelopes": outcome.envelopes,
        "row_keys": [row_key(r) for r in outcome.rows],  # 行主键用 E2 口径: 位置不敏感, 才能与金标准逐条对齐
        "row_count": len(outcome.rows),
        "first_row": (outcome.reported.get("rows") or [{}])[0],  # 取"系统声称"的首行: 取数门字段对账基准
        # 摘掉 rows: 全量行集已进 first_row/row_keys, 留着体积翻十几倍
        "reported": {k: v for k, v in outcome.reported.items() if k != "rows"},
        "answer_text": outcome.answer_text,
        # token 两列恒 None: API 不返 usage, 估算填数污染成本结论 (§6.7)
        "cost": {"http_requests": outcome.http_requests,
                 "tokens_in": None, "tokens_out": None,
                 "elapsed_s": round(outcome.elapsed_s, 6)},  # 保留 6 位看延迟量级, 但它不进指纹
        "tool_face": adapter.face,  # 记工具面: 无工具面系统的工具类指标是 N/A 而非 0
        "notes": outcome.notes,
        "fingerprint": trace_fingerprint(outcome),  # 确定性自证的唯一依据, 必须在所有字段齐了之后再算
    }


def row_key(row: dict) -> str:
    """行主键 (proximity 复合键 in<line>:<id>; 否则 source_id, 再退 (ra,dec)@9 键)。

    与 E2 gold 的 row_keys 口径一致: batch_proximity 的金标准用
    ``in<input_line>:<source_id>`` 复合键 (回连列由 input_index 承担)。
    """
    line = row.get("inputobjs_input_line")
    sid = row.get("ps1_source_id") or row.get("source_id")
    if line not in (None, "") and sid not in (None, ""):  # 优先复合键: 同一批输入里 source_id 可能重复, 只用它会误判少返行
        return f"in{int(float(line))}:{sid}"
    if sid not in (None, ""):
        return str(sid)
    # 兜底坐标键: 限定名与裸名两种形态都试, 都没有才按 0 拼 (与 E2 同样口径)
    ra = row.get("ps1_ra") if row.get("ps1_ra") not in (None, "") else row.get("ra")
    dec = row.get("ps1_dec") if row.get("ps1_dec") not in (None, "") else row.get("dec")
    return f"{to_float(ra) or 0.0:.9f},{to_float(dec) or 0.0:.9f}"  # 9 位 = 毫角秒: 再粗会合并邻近源, 再细会因浮点尾数对不上


def run_matrix(system_names: Optional[list[str]] = None,
               items: Optional[list[dict]] = None,                                                # 任务集可注入: 跑子集与复现都不必改包内那份
               repeat: int = 3, category: Optional[str] = None,                               # 重复次数默认三次: 确定性自证要多次重复才谈得上一致
               seed: Optional[int] = None,
               capture: Optional[dict] = None) -> dict:                                              # 种子缺省即不随机化: 保持原序便于两轮逐条对照
    """跑批矩阵 (任务 × 系统 × repeat); 返回逐 run 记录 + 确定性声明。

    Args:
        system_names: 要跑的系统 id (None = 全体)。
        items: 任务集 (None = 从 items.yaml 装载)。
        repeat: 每 (系统, 任务) 的重复次数 (至少 1)。
        category: 只跑某一门 (D/C/R/S 或 all)。
        seed: 顺序随机化的种子 (None = 不随机化)。
        capture: 真模型采集表 (None = 替身批; 见 captured_llm 模块头)。

    Returns:
        含 n_items/n_systems/repeat/systems/runs/determinism 的跑批报告。
    """
    items = items if items is not None else load_items()  # 用 is None 判而非真值判: 传空列表是明确意图, 不该被换成默认任务集
    systems = load_systems(system_names)                                                            # 装配先装载: 缺文件即抛, 不进矩阵循环
    chosen = select_items(items, category, seed)                                                   # 筛选与随机化都在这一步定: 后面循环只管跑
    runs: list[dict] = []                                                                    # 逐 run 记录全攒在内存: 报告与轨迹落盘共用这一份
    for item in chosen:  # 任务序在外: 同一道题的所有系统连着跑, 减少跨题状态串扰
        for system_id in systems:                                                           # 内层遍历系统: 同一道题的所有系统连着跑, 减少跨题串扰
            for attempt in range(1, max(1, repeat) + 1):  # max(1, repeat) 兜底: repeat=0 不该产出零次重复的空矩阵
                # capture 逐层透传: live 臂缺 (系统, 任务, attempt) 组合时由
                # CapturedLLM 现抛 CaptureMissingError, 不在此处静默换回替身
                runs.append(run_once(systems[system_id], item, attempt, capture))              # 一次跑批收一条记录: 重复次数体现在 attempt 上
    return {"n_items": len(chosen), "n_systems": len(systems),
            "repeat": max(1, repeat), "systems": sorted(systems), "runs": runs,
            "mode": "live" if capture is not None else "scripted",   # 模式进报告: 不靠调用方记得自己传了什么
            "determinism": _determinism_report(runs)}


def _determinism_report(runs: list[dict]) -> dict:
    """同 (系统, 任务) 多次重复的指纹一致性 (E6 R0 同款确定性声明)。"""
    groups: dict[tuple[str, str], set[str]] = {}  # 按 (系统, 任务) 聚组, 每组收指纹集合: 集合大小即"是否分叉"
    for run in runs:                                                                    # 逐 run 归组: 同一 (系统, 任务) 的多次重复要能比指纹
        groups.setdefault((run["system"], run["item"]), set()).add(run["fingerprint"])
    unstable = [f"{s}/{i}" for (s, i), prints in sorted(groups.items()) if len(prints) > 1]  # 列出具体组: 光给布尔没法排查
    return {"n_groups": len(groups), "unstable": unstable, "deterministic": not unstable}


TRACE_LOCK = ".write_lock"                                                                   # 目录级互斥锁名: 目录创建是原子的, 抢到即独占
TRACE_SUFFIX = ".json"                                                                      # 轨迹后缀: 只认它, 临时文件不带此后缀故不会被下游误吃


def _acquire_trace_lock(target: Path, *, break_lock: bool = False) -> Path:
    """占住轨迹目录的写锁 (并发保护的执行者, fail-closed)。

    **为什么需要**: 旧实现两个进程可同时写同一目录, 同名轨迹互相覆盖 (last-writer-wins) ——
    与 D-18 完全同形, 只是发生在轨迹层而不是采集层。

    Args:
        target: 轨迹落盘根。
        break_lock: 强制清掉已存在的锁 (仅用于上一轮崩掉留下的死锁)。

    Returns:
        锁目录路径 (调用方须在 finally 里 ``_release_trace_lock``)。

    Raises:
        RuntimeError: 抢不到锁且不要求强制清理 —— 说明已有写者在跑。
    """
    lock = target / TRACE_LOCK                                                              # 锁即目录: mkdir 只有一个赢家, 无 TOCTOU 窗口
    if break_lock and lock.is_dir():                                                        # 强制清锁: 只在上轮崩掉时人工使用
        lock.rmdir()
    try:
        lock.mkdir(exist_ok=False)                                                          # 原子抢占: 已存在即 FileExistsError
    except FileExistsError as exc:
        raise RuntimeError(f"轨迹目录正被另一个写者占用: {lock} (若要清上一轮崩掉留下的锁, "
                           f"显式给 break_lock=True)") from exc
    return lock


def _release_trace_lock(target: Path) -> None:
    """释放轨迹目录的写锁 (幂等: 锁已不在就什么也不做)。"""
    lock = target / TRACE_LOCK                                                              # 与抢占同一路径口径: 不另拼
    if lock.is_dir():                                                                       # 幂等: 重复释放不该抛
        lock.rmdir()                                                                        # 空目录: 锁里不放任何内容


def write_traces(report: dict, out_dir: Optional[Path] = None, *,
                 overwrite: bool = False, break_lock: bool = False) -> list[Path]:
    """落盘逐 run 轨迹 (只增不改; runs/<system>/<item>__aN.json)。

    **为什么改成原子提交 + 拒覆盖 (2026-10-11 实测)**: 旧实现 ``path.write_text(...)``
    直写固定文件名, 三个洞: ① 两个进程撞车时后写者静默覆盖先写者, 那一轮是两份数据的
    混合; ② 写到一半崩掉留下**半截 JSON**, 而下游按 ``*.json`` 扫, 半截文件会被当成
    正常轨迹吃掉; ③ 重复跑批直接覆盖旧轮次 —— "只增不改"只是句注释, **没有执行者**。
    现在: 目录级互斥锁 + 临时文件 + ``os.replace`` 原子提交 + 同名拒写 (须显式
    ``overwrite=True``), 同一报告内重复的 (system, item, attempt) 直接判错。

    Args:
        report: 跑批报告 (取 ``runs``)。
        out_dir: 落盘根; 缺省 ``RUNS_DIR``。
        overwrite: 允许覆盖已存在的同名轨迹。**默认关闭**: 只增不改是被执行的约定。
        break_lock: 强制清掉上一轮崩掉留下的写锁。

    Returns:
        已落盘的轨迹路径清单。

    Raises:
        RuntimeError: 目录锁被别的写者占着。
        ValueError: 同一报告内出现重复的 (system, item, attempt)。
        FileExistsError: 同名轨迹已存在而 ``overwrite`` 为假。
    """
    target = Path(out_dir) if out_dir else RUNS_DIR                                           # 落盘根可注入: 离线验证常写到临时目录, 不污染包内
    target.mkdir(parents=True, exist_ok=True)                                               # 根目录自建: 锁要落在它里面
    _acquire_trace_lock(target, break_lock=break_lock)                                      # 先抢锁: 抢不到就不写任何一个字节
    written: list[Path] = []                                                                    # 回写已落盘清单: 调用方要能核对到底写了哪些轨迹
    seen: set[tuple[str, str, Any]] = set()                                                 # 去重哨兵: 同一报告内撞键即数据本身有问题
    try:
        for run in report.get("runs") or []:
            directory = target / str(run["system"])  # 按系统分子目录: 11×30×N 平铺在一个目录里没法看
            directory.mkdir(parents=True, exist_ok=True)                                   # 按系统分子目录: 三十乘十一乘 N 平铺在一个目录里没法看
            key = (str(run["system"]), str(run["item"]), run["attempt"])                   # 三元组: 与文件名的构成口径一致
            if key in seen:                                                                 # 撞键即抛: 静默覆盖会让"少一轮"永远看不出来
                raise ValueError(f"同一报告内出现重复的 (system, item, attempt): {key}")
            seen.add(key)
            path = directory / f"{run['item']}__a{run['attempt']}{TRACE_SUFFIX}"            # 带 attempt 后缀: repeat>1 时同名才不会互撞
            if path.exists() and not overwrite:                                             # 拒覆盖: 只增不改从此有执行者
                raise FileExistsError(f"轨迹已存在: {path} (要覆盖请显式 overw"
                                      "rite=True —— 旧轮次是数据, 不是缓存)")
            tmp = directory / f".{path.name}.{os.getpid()}.tmp"                             # 临时文件不带 .json: 崩了也不会被下游扫到
            tmp.write_text(json.dumps(run, ensure_ascii=False, indent=2), encoding="utf-8")  # 不转义: 中文答案要人能直接读
            os.replace(tmp, path)                                                           # 原子提交: 要么整份在, 要么不在, 没有半截
            written.append(path)                                                               # 记路径便于对账: 只增不改这个约定要靠这份清单验证
    finally:
        _release_trace_lock(target)                                                         # 无论成败都放锁: 异常也不能把目录锁死
    return written


def main(argv: Optional[list[str]] = None) -> int:
    """CLI: --systems/--category/--repeat/--seed/--out; 退出码 0 全过 / 1 有 fail。"""
    # 标准库: CLI 参数解析 (跑批矩阵的入口面)
    import argparse

    parser = argparse.ArgumentParser(description="E5 ablation batch runner")
    parser.add_argument("--systems", default="all")
    parser.add_argument("--category", default="all", choices=["all", "D", "C", "R", "S"])
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--out", default="")
    parser.add_argument("--overwrite-traces", action="store_true",                         # 显式开关: 覆盖旧轨迹是数据销毁, 不许默认发生
                        help="允许覆盖已存在的同名轨迹 (默认拒写: 只增不改)")
    args = parser.parse_args(argv)                                                          # argv 缺省走命令行: 这样单测可以直调 main()
    names = None if args.systems in ("all", "") else [  # "all"/"" 都解析成 None (全体); 手输常带空格要 strip
        s.strip() for s in args.systems.split(",") if s.strip()]
    started = time.monotonic()  # monotonic 而非 time(): 挂钟会被系统调时打断, 差值可能为负
    report = run_matrix(names, repeat=args.repeat, category=args.category, seed=args.seed)  # 矩阵参数原样下传: 口径集中在 run_matrix 一处, 入口不做二次加工
    report["wall_s"] = round(time.monotonic() - started, 3)  # 只作跑批规模参考, 不进指纹也不进任何指标
    if args.out:                                                                                    # 未给输出路径就不落盘: 默认跑批只打摘要
        write_traces(report, Path(args.out), overwrite=args.overwrite_traces)             # 轨迹按 run 逐条落: 报告里要能回指到具体那份 JSON
    print(json.dumps({k: v for k, v in report.items() if k != "runs"},  # stdout 只打摘要: 990 条会把终端刷爆
                     ensure_ascii=False, indent=2))                                    # 摘要不含逐 run 明细: 三百多条会把终端刷爆, 明细走轨迹文件
    det = report.get("determinism", {})  # 确定性评估结果
    has_unstable = bool(det.get("unstable"))  # 存在分叉组视为不确定
    has_failures = any(run.get("status") in ("failed", "error") for run in report.get("runs", []))  # 检查显式失败
    return 1 if (has_unstable or has_failures) else 0  # 退出码 0 全过 / 1 有 fail


if __name__ == "__main__":
    raise SystemExit(main())
