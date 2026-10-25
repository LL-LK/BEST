# -*- coding: utf-8 -*-
"""evals.repro.transport — E6 自包含精简回放 (R0/R3 路的假网卡)。

能力边界: 两阶段协议的最小回放 — POST 表单 → phase1.html (含 sqlid);
getcount → count.json; page=N → pages/page_NNNN.csv 原文; 每次调用计数。
边界: 只读快照目录, 零网络; FakeResponse 实现 requests.Response 最小子集。

**纪律注记 (零跨实验 import)**: 本文件是 E6 的自包含精简回放, 按 E6 独立性要求
**自带一份实现** (可读不可 import)。2026-10-07「全盘删回放改实跑」裁定已把
evals/groundtruth/transport.py 删除 (该文件现已不存在), 因此**本文件与任何一份
transport 之间的逐字节等价性已无从比对**; 现在由 ``evals/equivalence`` 守的是
**判定口径**等价 (行主键 / 哨兵, 见 ``evals.equivalence.criteria``) —— 传输实现
随回放层一并退役, 判定实现仍在, 漂移风险改由那一层承接。

白盒锚点: docs/eval-E6-reproducibility.md §2.1 (R0/R3 走快照回放);
src/protocol.py (两阶段 URL 形态 — 路由判定依据)。

职责: 给 E6 提供一个零网络的假网卡, 把两阶段查询协议 (POST 表单 →
  phase1.html → getcount → 分页 CSV) 全部按快照目录回放, 让 R0/R3 路
  能离线复现被测链路的全部往返。
所属实验: E6 可复现与效率 (32 任务 + R0 路实跑); 路由形态真值是
  docs/eval-E6-reproducibility.md §2.1 与 src/protocol.py 的两阶段 URL。
对外接口: FakeResponse (requests.Response 最小替身) 与 ReplayTransport
  (提供 .get / .post 与 call_count); 内部 _query_param 只服务分页路由。
依赖与数据流: 输入 = 一个快照目录 (phase1.html / count.json / pages/*.csv /
  root.html) 与被测链路发来的 URL; 产物 = 快照原文构成的 FakeResponse,
  call_count 供 evals/repro/attribution.py 统计请求数, 自身不落盘。
关键契约与不变量: 零网络 — 任何 URL 都只从磁盘读, 读不到就返回替身 404
  或空表, 绝不向外发包; 同一快照目录重复回放必须得到逐字节相同的响应,
  否则 E6 的所有一致性指标都失去意义; 零跨实验 import — 本文件**刻意**
  不 import evals.groundtruth 的 SnapshotTransport, 自带一份精简实现,
  两者的等价性由 evals/equivalence/ 的 P7 断言守护。
陷阱与边界: 缺页返回空 CSV 而非 404 是刻意的 — 服务端的末页之后本就返回
  0 行, 替身必须复现这个语义, 否则被测链路会走错分页终止分支, 把回放
  缺陷误报成不可复现。read_text 用 utf-8-sig 是为了保真: 快照可能带 BOM,
  强行按 utf-8 读会在第一列留下不可见字符, 键集合就整体偏了一列。
"""
from __future__ import annotations

# 标准库: 路径 / JSON (count 回包) / 调用计数 / 类型标注
import json
from pathlib import Path
from typing import Any, Optional


class FakeResponse:
    """requests.Response 最小替身 (快照原文载体; E6 精简版)。"""

    def __init__(self, status_code: int, text: str) -> None:
        """记录状态码与回包原文 (保留 BOM/无表头/哨兵 — 保真读取)。

        作用: 把快照原文原样挂到替身上。关键参数 status_code/text 是状态码
        与回包全文。Returns: None。抛什么: 不抛, 一切错误都延迟到被测链路
        自己读回包时才暴露。
        """
        self.status_code = status_code               # 原样保留: 被测链路靠它分流成功/失败路径
        # text 存字符串而非字节: 快照统一按 utf-8-sig 读过一道, 再存字节
        # 就等于给同一次回放开两条编码路径, 换个入口会读出不同内容
        self.text = text                                                                            # 响应体先原样存着: 判定层要按字节比
        # headers 恒为空字典: 被测链路可能读 content-type 决定解析方式,
        # 给个空壳比让 AttributeError 直接崩掉更接近真实回包的形状
        self.headers: dict = {}
        # closed 是被测链路的退出信号, 快照没有真实句柄可关, 只能打标记
        self.closed = False  # 起始为未关闭: 退出之后被测链路仍会读 text

    def raise_for_status(self) -> None:
        """非 2xx 抛 requests.HTTPError (与真实 requests 同语义)。

        作用: 让被测链路的错误分支在回放下也能走到。关键参数: 无。
        Returns: 2xx 时返回 None。抛什么: 状态码 >= 400 时抛
        requests.HTTPError。
        """
        # 延迟 import: 只有真要抛错时才需要 requests, 纯回放路径不必装载它
        import requests

        if self.status_code >= 400:                                                       # 4xx/5xx 即失败: 判定层只看状态码与 body 组合
            raise requests.HTTPError(f"{self.status_code} replay error", response=self)  # 3xx 不抛, 与 requests 同语义

    def close(self) -> None:
        """标记关闭 (流读尽后被测链路会调; 快照无真实句柄)。

        作用: 满足被测链路的资源释放约定。关键参数: 无。Returns: None。
        抛什么: 不抛。
        """
        self.closed = True                                                                       # 显式标记已关: 重复 close 要能被测出来

    def iter_content(self, chunk_size: int = 1):
        """字节流迭代 (下载类消费; 按整文本一次性产出)。

        作用: 让走流式读取的代码路径在回放下也能跑通。关键参数 chunk_size
        是切块粒度。Returns: 字节块的生成器。抛什么: 不抛。
        """
        data = self.text.encode("utf-8")  # 快照按 utf-8-sig 读过, 这里统一补回 utf-8 字节
        # 真分块而不是整块一次给: 被测链路可能按块累计行数, 一次给全量
        # 会让"读到一半中断"的异常分支在回放下永远走不到
        for start in range(0, len(data), chunk_size):                                               # 按块切分: 大响应不能一次性读进内存
            yield data[start:start + chunk_size]


def _query_param(url: str, name: str) -> Optional[str]:
    """从 URL 查询串取参数 (无查询串/无该参数 → None)。

    作用: 分页路由要读 page=N 才能定位快照文件。关键参数 url/name 是待查
    URL 与参数名。Returns: 参数值字符串, 缺失返回 None。抛什么: 不抛。
    """
    if "?" not in url:  # 无查询串即无参数: 短路, 不必 split
        return None
    # 手写解析而不是 urllib.parse: 被测链路构造的 URL 形态固定且简单,
    # 少一个依赖就少一处跨版本行为差异 (本仓零重型依赖纪律)
    for pair in url.split("?", 1)[1].split("&"):
        if "=" in pair:
            # 只切第一个 "=": 值里可能含 = (如 base64 片段), 全切会截断
            key, value = pair.split("=", 1)  # 不做百分号解码: 回放 URL 形态固定
            if key == name:
                return value
    return None


class ReplayTransport:
    """E6 精简回放传输层 (SnapshotTransport 的 E6 私有精简同语义件)。

    路由规则: POST ``/{catalog}/q`` → phase1.html; GET 含 ``/getcount`` →
    count.json; GET 含 ``/sqlid/`` 且 ``page=N`` → pages/page_NNNN.csv;
    其余 GET → root.html (无则 404 替身)。用法::

        client = BestClient(base_url="http://replay.local", rate_limit=0.0)
        client.session.get = transport.get
        client.session.post = transport.post
    """

    def __init__(self, snap_dir: str | Path) -> None:
        """记住快照目录 (不存在即抛 — 回放目标必须真实)。

        作用: 绑定回放源。关键参数 snap_dir 是快照目录路径。
        Returns: None。抛什么: 目录不存在时抛 FileNotFoundError ——
        目录缺失等于回放无源, 静默建空目录会让所有查询返回 404 而被误读
        成"服务不可用"。
        """
        self.snap_dir = Path(snap_dir)  # 只记路径, 不在这里校验内容: 缺文件由各路由自己降级
        if not self.snap_dir.is_dir():                                                            # 快照目录缺失即无法回放, 早失败好过返回空页
            raise FileNotFoundError(f"回放快照缺失: {snap_dir}")
        # call_count 统计每一次往返 (get + post), 是 EF/EO 效率指标的分母侧
        self.call_count = 0  # 起点为 0: 效率表的"请求数"直接读它

    def _read(self, rel_path: str) -> str:
        """读快照内文件原文 (utf-8-sig 兼容 BOM — 保真不转码)。

        作用: 唯一的读盘入口。关键参数 rel_path 是相对快照目录的路径。
        Returns: 文件全文字符串。抛什么: 文件不存在时抛
        FileNotFoundError, 由调用方先判存在性兜住。
        """
        # utf-8-sig 在有无 BOM 时行为一致: 带 BOM 会剥掉, 不带则原样读,
        # 正因如此才不需要为两种快照各写一条分支
        return (self.snap_dir / rel_path).read_text(encoding="utf-8-sig")

    def get(self, url: str, **kwargs: Any) -> FakeResponse:
        """顶替 session.get: getcount / 分页 CSV / 根回包 三路由。

        作用: 按 URL 形态分派到三条快照分支。关键参数 url 是被测链路
        构造的完整 URL; kwargs 是 requests 的其余关键字参数, 本实现
        全部忽略 (timeout/headers 在回放下无意义)。Returns: FakeResponse。
        抛什么: 不抛, 读不到的一律降级为替身 404 或空表。
        """
        self.call_count += 1                                                           # 计数在**取数**时加: 判定"请求了几次"靠它, 与是否成功无关
        # 路由顺序不能换: "/sqlid/" 分页 URL 里也可能带 getcount 字样吗?
        # 不能, 但 "/getcount" 先判能让常见路径少一次 in 扫描, 顺序即优先级
        if "/getcount" in url:
            if (self.snap_dir / "count.json").is_file():
                return FakeResponse(200, self._read("count.json"))
            # 缺 count.json 仍返 200 且 total=0: 服务端首次查询本来就可能
            # 还没有索引完成, 报 404 会让被测链路走进错误分支
            return FakeResponse(200, json.dumps({"total": 0}))
        if "/sqlid/" in url:
            page = _query_param(url, "page") or "1"  # 缺 page 按第 1 页: 首个分页请求不带页码
            # 补零到四位: 快照文件名由采集端按 4 位定宽命名, 少补零会
            # 找不到文件, 整条回放退化成空表
            rel = f"pages/page_{int(page):04d}.csv"
            if (self.snap_dir / rel).is_file():
                return FakeResponse(200, self._read(rel))
            return FakeResponse(200, "")  # 末页之后: 空表 (0 行即末页)
        # 兜底给根回包: 两阶段协议里 phase1 之后的落地页走这条, 缺根页时
        # 返 404 替身让被测链路走它本该走的错误分支
        if (self.snap_dir / "root.html").is_file():
            return FakeResponse(200, self._read("root.html"))
        return FakeResponse(404, "<html>404</html>")  # 只有缺根页才 404, 让被测链路走该走的错误分支

    def post(self, url: str, **kwargs: Any) -> FakeResponse:
        """顶替 session.post: 回 phase1.html (sqlid 链接载体)。

        作用: 复现两阶段协议的第一步。关键参数 url 是表单提交地址;
        kwargs (data/params) 全部忽略 —— 快照不区分不同查询词, 这是
        精简版的已知边界, 真实差异由 E2 的权威件覆盖。Returns:
        FakeResponse。抛什么: 不抛。
        """
        self.call_count += 1                                                                        # 同 163, 但记在另一个通道上
        if (self.snap_dir / "phase1.html").is_file():
            return FakeResponse(200, self._read("phase1.html"))  # sqlid 链接就藏在这页里
        # 无 phase1.html 时仍回 200: 让被测链路的"取不到 sqlid"分支自己
        # 走完, 比在这里抛错更贴近服务端降级行为
        return FakeResponse(200, "<html>no sqlid</html>")
