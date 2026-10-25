# -*- coding: utf-8 -*-
"""ops/live_fetch.py — 从真实 BEST 站点抓取快照 (铁律 7 的有条件豁免入口)。

能力边界: 把一次**真实**查询的线路回包逐字节录成快照目录, 供 evals 的回放传输层
消费。抓完之后评测仍跑回放 (确定性不变), 本工具只负责把"素材从哪来"这件事变得
可审计、可复现。**它不参与任何判分**。

为什么需要它: E2 的 17 份金标准里, 审计坐实 11 份 ``syn_*`` 合成、3 份合成却挂在
名为 ``ps1_*`` 的 "L 类真实快照" 下 (其 snapshot.yaml 自认"素材反推构造, 零联网",
行 ``source_id`` 字面为 ``BEST_SIM_0001/0002``), 另有 1 份在真实天区掺了人造星。
后果: E2 证明的是"被测代码与独立 oracle 在同一批**人造**素材上对得上", 不是
"对真实天文数据取数正确"。本工具是那批素材的重建入口。

默认 dry-run (铁律 5 禁 fail-open 的同源要求): 不带 ``--execute`` 只打印计划、
一个请求都不发。发了什么、拿到什么, 全部落进快照目录的 ``capture_log.json``。

能力边界之外 (刻意不做):
  - **不重试 POST**: 会话建立非幂等, 重试造孤儿会话并泄漏服务端配额。GET 的
    重试与退避由客户端自己的 HTTPAdapter 负责 (allowed_methods 只含 GET), 本工具
    不绕过也不加码。
  - **不并发**: 串行 + 可配间隔, 对站点友好优先于吞吐。
  - **不替人签字**: 抓到真实数据不等于金标准通过人工复核, 签字是 E2 独立门禁。

白盒锚点: CLAUDE.md 铁律 7 (离线纪律, live 抽样须显式声明) · CLAUDE.md 铁律 1
(禁版本号; ``data_version`` 属数据血缘, 允许) · docs/eval-E2-groundtruth.md
§4.6.6 (素材真实性 P1 改造项) · evals/groundtruth/transport.py (快照目录布局的
消费方, 布局以该文件为准)。
"""
from __future__ import annotations

# 标准库: 参数解析 / JSON / 路径 / 哈希 / 时间
import argparse
import contextlib
import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# 第三方: requests (只为了继承 Session; 业务请求全部由客户端发出)
import requests

# 目录锚点: 本文件在 ops/, parents[1] 即 skill 根
ROOT = Path(__file__).resolve().parents[1]                                                  # 仓根: 本文件在 ops/, 上溯一层
if str(ROOT) not in sys.path:  # 直接 `python ops/live_fetch.py` 时 sys.path[0] 是 ops/, 补根才能 import src
    sys.path.insert(0, str(ROOT))

from src.client import BestClient  # noqa: E402
from src.protocol import BEST_BASE_URL  # noqa: E402

# 快照根: 与 E2 回放消费方同层, 便于对照; 目录名带抓取日期, 不覆盖既有素材
SNAPSHOT_ROOT = ROOT / "evals" / "groundtruth" / "snapshots"                             # 与 E2 回放消费方同层, 便于逐份对照


# ── 录制式 session: 客户端实际发了什么就录什么, 不重实现协议 ──────────────

class RecordingSession(requests.Session):
    """requests.Session 的录制子类: 透传全部行为, 顺带把回包原文留档。

    只重写 :meth:`request` —— ``Session.get`` / ``Session.post`` 内部都走它,
    所以这一处覆盖就够, 不必分别重写两个动词。重试发生在 urllib3 adapter 层,
    本类看到的是**重试后**的有效回包, 那正是快照该留的东西 (回放不该重试)。
    """

    def __init__(self) -> None:
        """建空录制表 (记录项在每次 request 时追加)。"""
        super().__init__()
        self.log: list[dict[str, Any]] = []          # 请求日志: 复核"发了什么"靠它
        self.bodies: list[tuple[str, str]] = []      # (角色, 原文): 角色决定落到哪个文件

    def request(self, method: str, url: str, **kwargs: Any) -> Any:  # noqa: ANN401 — 与父类同签名
        """发一次请求并录下回包; 返回**未经改写**的原始 Response。"""
        resp = super().request(method, url, **kwargs)                                        # 先发再录: 录的是重试后的有效回包
        text = resp.text                                                                    # 原文, 不 strip 不换行归一: 脏形态本身就是被测对象
        self.log.append({"method": method, "url": url, "status": resp.status_code,
                         "bytes": len(resp.content or b""), "at": datetime.now(timezone.utc).isoformat()})
        if method.upper() == "POST":
            self.bodies.append(("phase1", text))                      # 阶段 1 的 HTML: sqlid 就住在这里
        elif "/getcount" in url:
            self.bodies.append(("count", text))                       # getcount: total_count 的唯一真值源
        elif "/sqlid/" in url and "page=" in url:
            page = 1
            for pair in url.split("?", 1)[-1].split("&"):              # 页码从查询串里取: 与回放侧同一口径
                if pair.startswith("page="):
                    page = int(pair.split("=", 1)[1])
            self.bodies.append((f"page:{page}", text))                # 分页 CSV: 逐页留档, 缺页即真实缺页
        return resp


# ── 抓取任务表: 每个实验要什么, 在这里声明 ────────────────────────────────

def cone(catalog: str, ra: float, dec: float, radius: float, **kw: Any) -> dict:
    """声明一次锥搜抓取任务 (radius 单位是角秒, 站点 pos.radius 的原生单位)。

    可选键: ``max_records`` (取回上限, 缺省 1000 不触发截断)、``page_size``、
    ``constraints`` (列约束列表)、``sort`` / ``order``。带 ``constraints`` 时走
    协议层的 ``_build_form`` 直传, 不经 ``cone_search`` 的单约束入口。
    """
    return {"kind": "cone", "catalog": catalog, "ra": ra, "dec": dec, "radius": radius, **kw}  # 可选项透传


def col(name: str, constraint: str, value: Any, **kw: Any) -> dict:
    """声明一条列约束 (站点原生的 name/constraint/value 三元组)。"""
    return {"name": name, "constraint": constraint, "value": value, **kw}


def proximity(catalog: str, points: list[tuple[float, float]], **kw: Any) -> dict:
    """声明一次 proximity 批量抓取 (points 每项是 (ra, dec); 匹配半径走 kw 的 radius)。

    三个点必须**互不相同**: 服务端会把同中心的输入并成一组回连, 冻结答案里就没有
    分开的组, 与 oracle 逐输入独立匹配的口径对不上 (踩过一次)。
    """
    return {"kind": "proximity", "catalog": catalog, "points": points, **kw}


def raw(catalog: str, ra: float, dec: float, radius: float, note: str) -> dict:
    """声明一次**绕开入口校验**的原始 POST (取证用, 见 ``_run_raw`` 的免责说明)。

    存在的理由只有两个, 都是"客户端太称职反而看不见服务器行为":
    ``radius=0`` 被 :func:`validate_search_radius` 当无意义查询拒在发包之前;
    未知表名被 :func:`resolve_catalog` 拒在发包之前。两者都会让 E2 的边界场景
    与软 404 场景**永远抓不到**。这是取证通道, 不是正常调用路径。
    """
    return {"kind": "raw", "catalog": catalog, "ra": ra, "dec": dec, "radius": radius, "note": note}


def _catalog_probe_set() -> list[dict]:
    """12 张可查表各一次代表性锥搜 (坐标经 2026-10-04 实测标定, 非猜测)。"""
    return [cone(catalog, ra, dec, 300.0) for catalog, ra, dec in REAL_COVERAGE]


# 各表实测代表坐标 (2026-10-04 探测标定)。**这不是按表名猜的天区, 是实测出来的**:
# 首轮用赤道附近统一坐标时, stripe82 / splus_dr4 / smss_dr4 / scr_lamost / scr_galah
# 全部返回 0 行 —— 各表天区互不重叠这件事, 只有真数据能告诉你。
# (ra, dec, 实测 total@1800as); None = 探测多处仍无数据, 见 COVERAGE_NOTES。
REAL_COVERAGE: list[tuple[str, float, float]] = [
    ("ps1", 180.0, 30.0),            # 174 行 @60as; 全天覆盖
    ("gaia_dr3_18", 286.1, 15.7),    # 7193 @300as
    ("uss_dr1", 120.3, -20.4),       # 1039801 @300as —— 全库最大的表之一
    ("xpsp", 10.68, 41.27),          # 2268 @300as
    ("dr3xpcorr", 180.0, 30.0),      # 1 @300as
    ("stripe82", 30.0, 0.0),         # 1606 @1800as —— Stripe82 精测天区在赤道
    ("splus_dr4", 10.0, -70.0),      # 7775 @1800as —— S-PLUS 在南天
    ("smss_dr4", 0.0, -30.0),        # 3995 @1800as —— SMSS 在南天银道面
    ("scr_lamost", 180.0, 30.0),     # 137 @1800as
    ("scr_galah", 120.0, -20.4),     # 1 @1800as —— 极稀疏
]

# 两张表实测取不到数据, 如实登记而不假装有 (2026-10-04 探测):
COVERAGE_NOTES = {
    "jplus_dr3": "探测 24 处 (含其公认天区 Dec -79..-45, 最大半径 5°) 全部 0 行, **疑似站点侧覆盖异常, "
                 "待站方确认**。**入库快照的实测形态 (以 "
                 "live_jplus_dr3_ra10.0_dec-60.0_r300.0as 为证 — 探点在其公认天区内, 区外那份 ra120.3 探的是 uss_dr1 的天区, 已作废)**: getcount 与分页**自洽** —— "
                 "getcount 回 {\"total\":0}, 分页回 HTTP 200 + 带 BOM 的 12 列表头 CSV + **0 数据行**; "
                 "is_soft_error() 判 False, parse_csv_rows() 判 0 行。即站点此刻的表现与「该锥内无源」"
                 "**无法区分**, 客户端行为也是正确的 (分页请求确实发出, 见 capture_log.json 三条请求)。"
                 "此前本文件记过「分页回软 404 而客户端报 success/0 (total=0 时跳过分页取)」——"
                 "**该说法与留档证据矛盾, 已撤回**: 客户端分页循环条件是 total_fetched < max_rows, "
                 "不看 getcount; 且该快照内不存在软 404 形态。若站方确认坏表, 需要的是站侧日志。",
    "landolt": "探测 45 处全 0。全表 45712 行摊到全天约 1 行/3.7 deg², 0.5° 锥期望命中 "
               "0.018 行 —— 0 命中在统计上属**正常稀疏**, 不是故障。要用它必须先有已知 "
               "标准星坐标 (锥搜按位置找, 按名字找不到)。",
}


TASK_SETS: dict[str, list[dict]] = {
    "catalogs": _catalog_probe_set(),          # 12 张表各一次: E3 fixture 与 E5 data_anchor 的素材底座
    "empty": [cone("ps1", 10.0, -45.0, 60.0)],  # 南天低密度天区: 验证"0 命中是合法结果"
    # 软 404 必须走 raw: 未知表名会被 resolve_catalog 拦在**发包之前**, 走客户端就永远观测不到
    "soft404": [raw("no_such_catalog", 180.0, 30.0, 60.0, "未知表名的真实软 404 形态 (HTTP 200 + {\"error\":\"Not Found\"})")],
    "sentinel": [cone("ps1", 180.0, 30.0, 60.0)],            # 哨兵高发天区 (实测 148/174 行带 -1004)
    "tiny": [cone("ps1", 180.0, 30.0, 5.0)],                # 极小半径: 边界/截断用例
    "sort": [cone("ps1", 180.0, 30.0, 60.0, sort="ps1_rpsf", order="asc")],  # 服务端排序路径
    # ── E2 场景重指素材: 补齐 8 类, 让 16/17 场景能用真实回包 (2026-10-04) ──
    "e2_rows": [cone("ps1", 180.0, 30.0, 300.0, max_records=4000, page_size=1000)],  # >页容量 的多页截断样本 (total 5109)
    "e2_mag_snr": [cone("ps1", 180.0, 30.0, 60.0, constraints=[        # 星等区间 + 信噪上限: 两个约束同时生效
        col("ps1_gpsf", "between", None, min=18.0, max=20.0),          # between 用 min/max 两键, 不用 value
        col("ps1_gpsf_err", "less", "5.0")])],                              # 信噪误差越小越好, 取上限 (value 按契约是字符串)
    # 三个中心各**贴着一颗不同的源** (取自 5" 快照的实测行位置), 半径 10":
    #   - 半径不能太小 —— (180,30) 最近的源也在 3.587" 外, r=2" 时三点全 0 命中;
    #   - 中心不能同址 —— 同中心的服务端并成一组回连, 冻结答案里没有分开的组。
    # 三个中心各距约 4", 配上 10" 半径, 每点的最近邻必是各自那颗源。
    "e2_proximity_v2": [proximity("ps1", [
        (180.0, 30.0), (180.0011, 29.9995), (180.0004, 29.9990)],
        radius=10.0, columns=["ps1_ra", "ps1_dec", "ps1_rpsf", "ps1_ipsf"])],
    "e2_pole": [cone("ps1", 0.0, 90.0, 60.0)],                              # 北天极: dec=90 合法 (校验是闭区间)
    "e2_wrap": [cone("ps1", 359.5, 0.0, 1800.0)],                            # 赤经回绕: 锥区跨 0/360 分界
    "e2_zero_radius": [raw("ps1", 180.0, 30.0, 0.0, "radius=0: 被 validate_search_radius 拒在发包前, 只能绕行取证")],
    # E3-A05 需要"同一颗星在 ps1 与 stripe82 都有": 在 stripe82 那颗星的位置补抓
    # 一份 ps1, 才能做同星跨星表比较 (跨表比不同星没有意义)。
    "e2_xcatalog_ps1": [cone("ps1", 29.967632, 0.024272, 5.0)],
    # 找 total 恰为整页的半径 (60″ 已在库且 total=174 非整页, 不重抓)
    "e2_page_exact": [cone("ps1", 180.0, 30.0, r, max_records=1000, page_size=1000)
                      for r in (120.0, 240.0, 480.0, 900.0)],
    # ── E3-F06 的 jplus 侧必须探在**它自己的天区内** (2026-10-05 补) ──
    # 此前入库的 live_jplus_dr3_ra120.3_dec-20.4_r300.0as 探的是 (120.3, -20.4),
    # 那是 **uss_dr1** 的天区, 不在 jplus 的公认天区 (Dec -79..-45) 内。后果是:
    # 在天区外探到 0, 恰好是"该表没覆盖这里"能解释的结果, 于是"疑似站点侧异常"
    # 这个结论与题面给的回包**互相拆台** —— 读得懂知识面的被测模型会指出这一点,
    # 而那个更正确的回答会被判错 (一道惩罚正确答案的题比没有这道题更糟)。
    # 这里用片段已订正的公认天区代表坐标 (10.0, -60.0): **区内仍 0** 才是可疑的证据。
    "jplus_inregion": [cone("jplus_dr3", 10.0, -60.0, 300.0)],
}


# ── 控制台编码兜底: dry-run 是给人看的计划, 崩了就失去意义 ──────────────

def make_console_safe(stream: Any) -> Any:
    """把输出流调成"编不出来的字符降级替换", 而不是抛 UnicodeEncodeError。

    为什么必须有 (2026-10-05 H5-05 实测): Windows 默认控制台是 GBK, 而本
    文件的 ``COVERAGE_NOTES`` 里有 GBK 编不出的字符 (landolt 那条含 ``²``
    = U+00B2)。默认 dry-run 会走到 ``main`` 里的 COVERAGE_NOTES 打印分支,
    于是 **不带 ``--execute`` 的默认路径在 GBK 控制台直接崩**:

        File "ops/live_fetch.py", line 433, in main
          print(f"    ! {cat}: {note}")
        UnicodeEncodeError: 'gbk' codec can't encode character '\\xb2'

    铁律 7 把"默认 dry-run, 先看计划再决定要不要跑"定为纪律, 用户按文档第一次
    试就撞墙 —— 一个开箱即崩的默认路径, 比没有预览功能更糟。

    为什么选 ``errors="replace"`` 而不是把源码里的 ``²`` 改掉: 换字符只是把
    这一次侥幸躲过去, 下一条 note、下一个任务描述再带个生僻字符就又崩。降级
    策略得落在**输出这一层**, 与具体字符无关。

    Args:
        stream: 待加固的输出流 (通常是 ``sys.stdout`` / ``sys.stderr``)。

    Returns:
        同一个流对象, 便于链式调用。

    失败语义: 流不支持 reconfigure (如测试里的 ``io.StringIO``) 或已被
    detach 时**静默放过** —— 那是"拿不到这个能力", 不是"发现问题": 此时该流
    本来就没有编码器, 也就不会有编码错误。真正要判的失败是单字符编不出来,
    那由 ``errors="replace"`` 兜住。
    """
    reconfigure = getattr(stream, "reconfigure", None)  # TextIOWrapper 才有; StringIO 没有
    if reconfigure is None:
        return stream
    # 只改错误处理策略, 不碰 encoding: 编码是环境事实, 不该由本工具改写。
    # 已 detach / 已关闭的流会抛, 那是"拿不到这个能力"而不是"发现问题", 放过。
    with contextlib.suppress(ValueError, OSError):
        reconfigure(errors="replace")
    return stream


# ── 落盘: 布局严格对齐 evals/groundtruth/transport.py 的消费方 ─────────────

def _write(path: Path, text: str) -> None:
    """写文本, **逐字节保真**: 一律按纯 utf-8 写, BOM 由回包文本自带。

    ``RecordingSession`` 存的是 ``resp.text`` —— 站点 CSV 的 BOM 已经以 ``\\ufeff``
    留在文本里, 而 JSON/HTML 回包本来没有 BOM。曾经无条件写 ``utf-8-sig``, 于是
    两个方向都错了: CSV 落成**双** BOM (``\\xef\\xbb\\xbf`` ×2), 而 count.json /
    phase1.html 被**凭空加上**一层 BOM。两种都违背每份 ``snapshot.yaml`` 里
    "回包逐字节来自站点, 未做任何改写"的声明, 而且 manifest 记的是
    ``sha256(text.encode("utf-8"))`` —— 加了 BOM 就与 manifest 对不上。

    正确做法: 不碰编码标记, ``text`` 有什么就写什么。manifest 的哈希口径与落盘
    字节由此天然一致 (两者都是 ``text.encode("utf-8")``)。
    """
    path.parent.mkdir(parents=True, exist_ok=True)              # 父目录自建: pages/ 是二级目录
    path.write_text(text, encoding="utf-8", newline="")        # 纯 utf-8: 不加也不去 BOM


def dump_snapshot(out_dir: Path, task: dict, session: RecordingSession, meta: dict) -> dict:
    """把一次抓取的回包落成快照目录 + 清单 + 溯源。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    written: dict[str, str] = {}
    page_rows: list[str] = []
    for role, text in session.bodies:                                                        # 逐个回包落位: 角色决定落到哪个文件
        if role == "phase1":
            _write(out_dir / "phase1.html", text)
            written["phase1.html"] = text                     # 阶段 1: sqlid 的载体
        elif role == "count":
            _write(out_dir / "count.json", text)
            written["count.json"] = text                      # 计数: total_count 的唯一真值源
        elif role.startswith("page:"):
            n = int(role.split(":", 1)[1])                       # 页码从角色名取
            _write(out_dir / "pages" / f"page_{n:04d}.csv", text)
            written[f"pages/page_{n:04d}.csv"] = text            # 逐页入清单: 哈希要覆盖每一页
            page_rows.append(text)                           # 逐页留档: 缺页就是真实的缺页
        elif role == "raw_response":                         # 绕行取证的裸回包 (无角色, 形态事前未知)
            _write(out_dir / "raw_response.txt", text)       # 原样落盘: 软 404 这类形态没有预设解析器
            written["raw_response.txt"] = text               # 入清单: 哈希覆盖它, 事后可核未改写
    if page_rows:                       # rows_full.csv 供 QueryAwareTransport 按查询语义现场重算
        merged = "\n".join(r.rstrip("\n") for r in page_rows) + "\n"   # 换行归一一次: 页间不产生空行
        _write(out_dir / "rows_full.csv", merged)             # 落全量行集: 独立重算的数据源
        written["rows_full.csv"] = merged                     # 同样入清单, 哈希可核
    if not written:                     # 一个回包都没有 = 抓取失败, 不是"零行快照"
        raise RuntimeError(f"本次抓取没有任何回包可落盘: {task} (软错误/网络失败?)")
    manifest = {"snapshot_id": out_dir.name,                 # 快照 id = 目录名
                "files": {k: "sha256:" + hashlib.sha256(v.encode("utf-8")).hexdigest()
                          for k, v in sorted(written.items())}}
    (out_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                                            encoding="utf-8")
    (out_dir / "capture_log.json").write_text(json.dumps(
        {"task": task, "request_log": session.log, "observed": meta}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    _write_snapshot_yaml(out_dir, task, meta)
    return meta


def _write_snapshot_yaml(out_dir: Path, task: dict, meta: dict) -> None:
    """写 snapshot.yaml 溯源块。``data_version`` 是数据血缘标识 (铁律 1 允许)。"""
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    lines = [
        f"snapshot_id: {out_dir.name}",
        "kind: LIVE",                                        # 与既有 kind: L 的"反推构造"明确区分
        "material_class: live-pure",                        # 真实抓取, 非合成
        f"catalog: {task.get('catalog', '-')}",             # 表 id: 数据血缘必填
        f"row_count: {meta.get('returned_count', 0)}",      # 实取行数 (截断时与服务端 total 不等, 两者都要看)
        f"data_version: {task.get('catalog', '-')}@{stamp}-live",   # 数据血缘标识, 非发布版本号
        f"page_size: {meta.get('page_size', 1000)}",         # 单页条数: 复现时要原样带上
        f"fetched_at: {stamp}",                              # 抓取日期: 站点数据会漂, 它是判断快照是否过期的唯一依据
        "endpoint:",
        f"  submit: {BEST_BASE_URL}/{task.get('catalog', '-')}/q",   # 阶段 1 提交端点
        f"  count: {BEST_BASE_URL}/sqlid/{{count}}/getcount",        # 计数端点: total_count 真值源
        "note: |",
        "  **真实抓取** (ops/live_fetch.py --execute, 铁律 7 有条件豁免)。回包逐字节来自站点,",
        "  未做任何改写或补行; request_log 见 capture_log.json, 文件哈希见 manifest.json。",
        "  抓到数据不等于金标准通过人工复核 —— E2 的签字门禁是独立环节。",
    ]
    (out_dir / "snapshot.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


# ── 执行 ─────────────────────────────────────────────────────────────────

def slug(task: dict) -> str:
    """任务 → 目录名 (可读且可复现: 同参数必得同名, **不同参数必不同名**)。

    后半句是硬要求: ``max_records`` / ``constraints`` / ``page_size`` 都会改变
    落盘行数, 与既有快照同名就会静默覆盖已经入库的素材。
    """
    k = task.get("kind")
    if k == "cone":
        base = f"live_{task['catalog']}_ra{task['ra']}_dec{task['dec']}_r{task['radius']}as"
        if task.get("sort"):
            base += f"_sorted_{task['sort']}_{task.get('order', 'asc')}"    # 排序路径单独命名
        cap = int(task.get("max_records", 1000))                              # 上限进名字: 同锥不同上限是两份素材
        if cap != 1000:
            base += f"_max{cap}"
        if task.get("constraints"):
            base += "_f" + "-".join(f"{c['name']}{c['constraint']}" for c in task["constraints"])  # 约束进名字
        return base
    if k == "proximity":
        # 点集必须进目录名: 只带点数的话, 换一组坐标重抓会**静默覆盖**已入库的
        # 旧快照 (踩过一次: 三个同中心点换成三个不同中心点, 同名同目录, 174 行被 0 行盖掉)
        digest = hashlib.sha256(
            ";".join(f"{p[0]},{p[1]}" for p in task["points"]).encode("utf-8")
        ).hexdigest()[:8]
        return f"live_{task['catalog']}_proximity_n{len(task['points'])}_{digest}"
    if k == "raw":
        return f"live_raw_{task['catalog']}_r{task['radius']}as"           # 绕行取证: 目录名必须带 raw 以免与正常路径混淆
    return f"live_{k}_{task.get('catalog', 'na')}"                         # 兜底: 非锥搜任务只按 kind+表名


def _run_cone(client: BestClient, task: dict) -> dict:
    """跑一次锥搜。带 constraints 时绕 cone_search 的单约束入口, 直传协议层表单。"""
    max_records = int(task.get("max_records", 1000))                        # 缺省 1000: 单页装得下, 不触发截断
    page_size = int(task.get("page_size", 1000))
    if not task.get("constraints"):
        res = client.cone_search(ra=task["ra"], dec=task["dec"],            # 无额外约束: 走公开入口, 校验照常生效
                                 radius_arcsec=task["radius"], catalog=task["catalog"],
                                 max_records=max_records, page_size=page_size,
                                 sort=task.get("sort"), order=task.get("order", "asc"))
    else:
        from src.models import ColumnConstraint  # 延迟导入: 约束值对象在模型层
        from src.protocol import CATALOG_PATHS, resolve_catalog  # 路径表与表名归一在协议层
        resolved = resolve_catalog(task["catalog"])                          # 表名归一: 导航组名在这里就会被拒
        constraints = [ColumnConstraint(name=c["name"], constraint=c["constraint"],
                                        value=c.get("value"), min=c.get("min"), max=c.get("max"))
                       for c in task["constraints"]]                          # 任务里的裸 dict → 协议层约束对象
        form = client._build_form(resolved, constraints, max_records,         # 表单键集权威在协议层, 本函数不自拼
                                  ra=task["ra"], dec=task["dec"], radius_arcsec=task["radius"],
                                  sort=task.get("sort"), order=task.get("order", "asc"))
        res = client._execute_query(CATALOG_PATHS[resolved], form,           # 走同一条两阶段执行路径
                                    max_rows=max_records, page_size=page_size)
    return {"success": res.success, "total_count": res.total_count,          # total 与 returned 分开记: 截断时两者不等
            "returned_count": res.returned_count, "truncated": res.truncated,
            "error_code": res.error_code}


def _run_proximity(client: BestClient, task: dict) -> dict:
    """跑一次 proximity 批量交叉 (一次 POST 提交多点, 服务端逐点匹配)。

    走**公开接口** ``crossmatch_batch`` 而不是自拼表单: E2 的回放侧也走这条
    路径, 两侧同源才谈得上"快照就是这个查询的答案"。三个输入点共用一个匹配半径
    (公开接口的签名如此), 且必须**互不相同** —— 同中心的服务端会并成一组回连,
    冻结答案里就没有分开的组, 与 oracle 逐输入独立匹配的口径对不上。
    """
    points = task["points"]
    # 注意: 不能写成 task.get("radius", points[0][2]) —— 默认参数是**急切求值**的,
    # 即使 radius 给了也会先算 points[0][2], 而 points 现在是 (ra, dec) 二元组
    radius = float(task["radius"]) if task.get("radius") is not None else float(points[0][2])
    res = client.crossmatch_batch(
        ra_list=[p[0] for p in points],                        # RA 逐位取: 与 dec_list 按位配对
        dec_list=[p[1] for p in points],                       # Dec 同上
        catalog=task["catalog"],
        radius_arcsec=radius,                                  # 共用半径: 接口只收一个
        columns=task.get("columns"),
        nearest_only=bool(task.get("nearest_only", True)),     # 默认只要最近邻: 与 crossmatch 的常规诉求一致
        max_rows=1000, page_size=1000,                         # 单页装得下: 输入点只有几个
    )
    return {"success": res.success, "total_count": res.total_count, "returned_count": res.returned_count,
            "truncated": res.truncated, "error_code": res.error_code, "n_points": len(points)}


def _run_raw(session: RecordingSession, task: dict) -> dict:
    """绕开入口校验的原始 POST —— **取证专用**, 正常调用不该走这里。

    免责: 本函数不复用客户端的表单构造, 因为需要它绕开的两道校验正是"客户端称职"
    的表现 (零半径与未知表名)。它仍然发**同样那 7 个键**, 不发明私有协议。
    风险控制: 单次 POST、不重试; 回包逐字节录进快照目录供事后判读。
    """
    form = {                                                                       # 与 build_query_form 同键集
        "csrfmiddlewaretoken": session.cookies.get("csrftoken", ""),               # 缺 csrf 会被站点拒, 如实留回包
        "output.fmt": "html", "pos_group": "ra,dec", "pos.type": "cone",           # html 才能拿到 sqlid
        "pos.racenter": str(task["ra"]), "pos.deccenter": str(task["dec"]),
        "pos.radius": str(task["radius"]), "showcol": "",
    }
    url = f"{BEST_BASE_URL}/{task['catalog']}/q"                                    # 未知名照样拼 URL: 软 404 就在这里
    resp = session.post(url, data=form, timeout=60)                                # 走录制 session: 回包自动留档
    body = resp.text
    soft = body.strip().startswith("{") and "Not Found" in body                    # 软 404 判据: 200 + 错误体
    session.bodies.append(("raw_response", body))                                  # 额外留一份无角色回包
    return {"success": not soft, "raw_status": resp.status_code, "raw_is_soft_404": soft,
            "total_count": 0, "returned_count": 0, "truncated": False,
            "error_code": "E_SOFT_404" if soft else None, "raw_note": task.get("note", "")}


def run_task(task: dict, out_root: Path, delay: float, dry: bool) -> dict:
    """执行/预览一次抓取。dry 为真时只算计划, 不建连接。"""
    name = slug(task)                                                                          # 目录名先定: dry 与真跑同一条命名路径
    if dry:                                                                                   # dry 分支: 只报计划, 不建连接
        return {"snapshot": name, "planned": True, "requests_estimate": 3}                    # 3 = POST + getcount + 首页 GET
    session = RecordingSession()                                                               # 录制会话: 客户端此后每个回包都留档
    client = BestClient(rate_limit=delay)     # rate_limit 复用为请求间隔: 对站点友好优先
    client.session = session                  # 换掉会话: 客户端此后所有请求都被录下
    meta: dict[str, Any] = {"returned_count": 0, "page_size": 1000}                          # 观测面: 与落盘字段同名, 便于对账
    try:
        if task["kind"] == "cone":                                                             # 锥搜: 两种入口 (有无额外约束)
            meta.update(_run_cone(client, task))
        elif task["kind"] == "proximity":                                                      # 批量交叉匹配
            meta.update(_run_proximity(client, task))
        elif task["kind"] == "raw":                                                            # 绕行取证 (见 _run_raw 免责)
            meta.update(_run_raw(session, task))
        else:                                  # 未知 kind 不猜: 早失败好过默默抓错东西
            raise ValueError(f"未知抓取任务 kind: {task['kind']}")
    finally:
        client.close()                                                                        # 关会话: finally 保证异常路径也释放
    out_dir = out_root / name                                                                 # 快照目录
    dump_snapshot(out_dir, task, session, meta)                                              # 落盘 + 清单 + 溯源
    return {"snapshot": name, "planned": False, **meta,                                       # 观测面回给调用方
            "files": len(session.bodies), "requests": len(session.log)}                       # 文件数与请求数: 抓取成本可核


def main(argv: list[str] | None = None) -> int:
    """CLI: ``--plan`` (默认) 只预览; ``--execute`` 真抓。"""
    ap = argparse.ArgumentParser(description="BEST live 快照抓取 (铁律 7 有条件豁免入口)")
    make_console_safe(sys.stdout)  # 先加固再说话: argparse 的报错也要能落到 GBK 控制台
    make_console_safe(sys.stderr)  # usage/错误同样走 stderr, 一起兜住
    ap.add_argument("--set", dest="sets", default="catalogs", help="逗号分隔任务集: " + ",".join(TASK_SETS))
    ap.add_argument("--out", default="", help="快照输出根 (默认 snapshots/live-<日期>)")
    ap.add_argument("--delay", type=float, default=1.5, help="请求间隔秒 (对站点友好)")
    ap.add_argument("--execute", action="store_true", help="真发请求; 不带就是 dry-run 预览")
    args = ap.parse_args(argv)                                                                # argv 显式传入: 单测可绕开子进程调同一份解析器
    unknown = [s for s in args.sets.split(",") if s and s not in TASK_SETS]                    # 未知集名早失败: 静默跳过会让人以为跑全了
    if unknown:                                                                               # 非法集名当场退出, 不进抓取
        ap.error(f"未知任务集: {unknown} (合法: {list(TASK_SETS)})")
    tasks = [t for s in args.sets.split(",") if s for t in TASK_SETS[s]]                      # 展平多集: 一次调用可跨集
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")                                   # 目录名带日期: 不同批次不互相覆盖
    out_root = Path(args.out) if args.out else SNAPSHOT_ROOT / f"live-{stamp}"                # 输出根: 显式路径优先
    if not args.execute:                                                                      # dry-run 分支: 一个请求都不发
        print(f"[DRY-RUN] 任务 {len(tasks)} 个, 一个请求都不会发。计划:")
        for t in tasks:
            print(f"  - {slug(t):52} kind={t['kind']} catalog={t.get('catalog')}")
        missing = [c for c in COVERAGE_NOTES if c not in {t.get('catalog') for t in tasks}]     # 该登记却没排进本批的表
        if missing:                                                                           # 有则显式说明, 不让"没排"看起来像"没问题"
            print("\n  以下表不在本批计划内 (实测取不到数据, 如实登记):")
            for cat, note in COVERAGE_NOTES.items():                                          # 逐表把原因写清
                if cat in missing:
                    print(f"    ! {cat}: {note}")
        print(f"  输出根: {out_root}")                                                         # 输出根也要在预览里给
        print("  加 --execute 才真抓。")
        return 0
    out_root.mkdir(parents=True, exist_ok=True)                                               # 目录自建: 输出根可指向任意新层级
    results: list[dict] = []                                                                  # 逐任务结果: 失败项也留档
    for i, t in enumerate(tasks, 1):                                                          # 串行: 对站点友好优先于吞吐
        print(f"[{i}/{len(tasks)}] {slug(t)} ...", flush=True)                                # 进度可见, 便于中途判断要不要停
        try:
            results.append(run_task(t, out_root, args.delay, dry=False))                     # 单任务一次抓完
        except Exception as exc:            # noqa: BLE001 — 单个任务失败不许中断整批
            # 记失败而不是中止: 某张表 0 命中/软 404/网络抖动都是**真实观测**的一部分,
            # 正是本工具要留档的东西; 中止反而会丢掉后面还没探的表。
            results.append({"snapshot": slug(t), "ok": False,                               # ok=False 与"抓到了 0 行"必须分开
                            "error": f"{type(exc).__name__}: {exc}"[:300]})                  # 错误截断: 异常文本可能很长
            print(f"    ! {type(exc).__name__}: {str(exc)[:120]}", flush=True)                # 失败当场可见, 不滚到末尾才发现
        time.sleep(args.delay)               # 任务之间也留间隔: 单任务内部已有 rate_limit
    ok = sum(1 for r in results if r.get("ok") is not False)                                  # 成功数: ok 键缺省也算成功
    print(json.dumps(results, ensure_ascii=False, indent=2))                                 # 全量结果落终端, 便于复制进报告
    print(f"\n完成 {ok}/{len(results)} 个; 失败项已如实记录, 不重试。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
