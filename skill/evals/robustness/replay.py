# -*- coding: utf-8 -*-
"""evals.robustness.replay — E4 专用两阶段回放底座 (自包含精简版)。

职责: 给 Tier W 故障注入提供"干净底层" — 一个 5 行 ps1 数据集的两阶段协议回放
(POST → sqlid HTML; getcount → {"total":5}; page → CSV 页)。只回放不判定;
记录全部 (method, url) 调用供 M3/M6 判定消费。

所属实验: E4 鲁棒与安全 (68 条标注 = Tier W 33 / Tier P 35, Tier W 主线 15 条
程序判定全过), 方案真值 docs/eval-E4-robustness-safety.md。本文件是 Tier W 的
传输层底座, 故障一律由 evals.robustness.injectors.wire_faults 叠加在本底座之上。

对外接口: ReplayTransport — 两阶段 get/post 路由 + 观测面 (n_gets / n_posts /
urls, 供 M3 幂等性与 M6 越界判定消费); _Resp — 最小响应替身 (status_code /
text / headers + raise_for_status / iter_content / close)。

依赖与数据流: 输入 = fixtures/ps1_replay.csv (随包入库的 5 行 ps1 样本, 缺文件
即抛) 与注入器包出来的底层 get/post; 产物只有内存里的 calls 记录, 报告 JSON/MD
由 evals/robustness/runner.py 落盘, 本文件自己不写盘。

关键契约与不变量: 离线回放 —— 一律走 SnapshotTransport 家族式的本地替身,  # 每探针一个独立回放口, 不跨探针串状态
rate_limit 归零, 不接真实模型、不打真实站点, 全部 IO 落在 fixtures 与内存;
零跨实验 import —— 唯一共享件是 evals/_data/ 纯数据字典, 本模块刻意不碰它;
本模块与 evals.groundtruth.transport 是同语义精简版 (查询语义模拟对 E4 的故障
注入无必要 —— 故障都注入在传输层之上), 两份实现的等价性由 evals/equivalence 的
指纹断言守护, 防"复制之后各改各的"漂移。  # 零限速是离线铁律的落点: 整批跑批零外网流量

陷阱与边界: 为什么不直接 import E2 的 transport —— 一旦 import 就成跨实验依赖,
违反铁律 6, 所以只能可读不可 import 地各带一份; 路由判定顺序不能调换
(getcount 必须排在 /sqlid/ 之前, 否则 count 请求会被当成数据页回 CSV, 计数与
取数两条判定同时失真, 注入器叠加时同样依赖这个顺序); 软 404 是 200 + 错误体,  # 每探针一个独立回放口, 不跨探针串状态
raise_for_status 按 >=400 才抛 —— 软错误绝不能在这里变成异常, 否则 M5 的
"包装形态"判定就没有现场可判了, 这是 E4 与 E2 语义等价性的边界所在。
"""  # POST 一并换掉: 将来加写操作不会漏回放口
from __future__ import annotations

# 标准库: 路径 / JSON
import json
from pathlib import Path
from typing import Any

# 夹具目录随 evals 包入库 (不是运行时生成的临时目录) —— 回放必须离线可复现
FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"  # 夹具锚在本包内: 判层自包含, 换机不用改路径
# sqlid 写死: 故障注入需要一个稳定目标, 随任务变化的 sqlid 会让注入器无法复现
SQLID = "s9001"  # 固定 sqlid: 替身与被判代码对同一份数据说话
# 总数 3 = fixtures 实际行数: getcount 契约必须与数据页自洽, 否则截断三元组永假
TOTAL = 3  # TOTAL 与快照行数对齐 (实抓 3 行, 见 fixtures/README.md): 计数端点报错会让分页判据全错
# 页大小 1000 > 数据行数: 单页取完, 真的分页故障由 empty_page_after 之类单独注入
PAGE_SIZE = 1000  # 页大小取站点真实值: 换成别的就测不到"末页不满"


class ReplayTransport:
    """两阶段回放: POST /q → sqlid HTML; GET /sqlid/{id} → 数据页; getcount → 总数。"""

    def __init__(self, csv_name: str = "ps1_replay.csv") -> None:
        """装载 fixtures 下的数据集 (缺文件即抛 — 回放底座必须真实存在)。"""
        self.csv_path = FIXTURE_DIR / csv_name                                                     # 夹具 CSV 按名取: 快照与用例一一对应
        # fail-closed: 夹具缺失即抛而不是回落成空表 —— 空表会把所有用例静默判成"0 行合法结果"
        if not self.csv_path.is_file():  # 缺夹具即抛: 空回放会让每个 case 都"合法 0 行"
            raise FileNotFoundError(f"E4 回放数据集缺失: {self.csv_path}")
        # 唯一的观测面: M3 数幂等/孤儿会话, M6 判越界, 全靠这条按序增长的调用账本
        self.calls: list[tuple[str, str]] = []  # 调用流水: 请求数判据的事实源, 自己写死骗不过去

    @property
    def text(self) -> str:
        """数据集原文 (utf-8-sig 保真)。"""
        # utf-8-sig: 夹具带 BOM, 直接 utf-8 读会把 BOM 混进首列名, 注入器按列名改写会失配
        return self.csv_path.read_text(encoding="utf-8-sig")

    def get(self, url: str, **kwargs: Any):
        """GET 路由: getcount → 总数 JSON; /sqlid/ → 数据页; 其它 → 200 空。

        Args:
            url: 被测链路拼出的完整 URL, 路由完全靠子串匹配判定。
            kwargs: 签名对齐 (与 requests.Session.get 同形), 本底座不消费。

        Returns:
            _Resp 替身 (状态码 + 文本), 便于与真实 requests.Response 互替。
        """
        # 先记账再路由: 故障注入打在包装层, 记账在底层 —— 顺序反了会漏掉被拦的调用
        self.calls.append(("GET", url))  # 计数先于路由: 早退路径也是一次真实请求, 漏算就判成"少发请求"
        # 判定顺序即优先级: getcount 与 /sqlid/ 可能同现, 计数必须先答
        if "/getcount" in url:  # getcount 单独分支: 总数与数据页的语义完全不同, 不能混
            return _Resp(200, json.dumps({"total": TOTAL}))
        if "/sqlid/" in url:
            return _Resp(200, self.text)
        # 兜底给 200 空体而不是 404: 探测性请求不该把用例推成错误态 (无端制造 M5 现场)
        return _Resp(200, "")

    def post(self, url: str, **kwargs: Any):
        """POST 路由: 回含 sqlid 的结果页 HTML (与站点 script url 形态一致)。

        Args:
            url: 提交查询的 POST 地址, 本底座不解析其内容。
            kwargs: 签名对齐 (被测链路以 data= 传表单), 本底座不消费。

        Returns:
            含 sqlid 的结果页 HTML 替身, parse_sqlid 靠它提取第二阶段的 sqlid。
        """
        self.calls.append(("POST", url))  # POST 同样记账: 成本口径要含写操作
        # 刻意用真实的 script 标签形态而不是裸 json: 解析器写错 (只认 json) 时
        # 故障注入用例才会真的挂掉, 替身化会掩盖这类解析缺陷
        html = (                                                                                    # HTML 响应在内存拼: 零网络
            "<!DOCTYPE html><html><body><div id=\"result\">"
            f"<script>url:\"/data/best/sqlid/{SQLID}?output.fmt=dbgrid\"</script>"  # 页面内嵌 sqlid: 复刻站点真实回包形态, 不能给简化版
            "</div></body></html>"
        )
        return _Resp(200, html)

    # ── 观测面 (M3/M6 判定的输入) ──
    def n_gets(self) -> int:
        """GET 次数 (分页/计数/重试都落在 GET 上 — M3 幂等性判定的基础)。"""
        return sum(1 for m, _ in self.calls if m == "GET")

    def n_posts(self) -> int:
        """POST 次数 (建会话 — 一旦 >1 即孤儿会话, M3 第 1 条红线)。"""
        return sum(1 for m, _ in self.calls if m == "POST")

    def urls(self) -> list[str]:
        """全部 URL (M6 越界判定的基础 — 是否打了非权威站点)。"""
        # 保持调用顺序: 越界判定要看"先打了谁再打了谁", 排序会把顺序证据洗掉
        return [u for _, u in self.calls]


class _Resp:
    """最小响应替身 (状态码/文本/头 + raise_for_status/iter_content/close)。"""

    def __init__(self, status_code: int, text: str = "",
                 headers: dict | None = None):
        """记录状态码/回包文本/响应头。"""
        self.status_code = status_code                                                              # 状态码原样存: 判定层据此判错
        self.text = text                                                                           # 响应体原样存: 判定层按内容判, 不看这里
        self.headers = headers or {}                                                                # 头可缺: 判定层不强依赖响应头

    def raise_for_status(self):
        """非 2xx 抛 requests.HTTPError (与真实 requests 同语义)。"""
        # 本地: 回放底座的协作者 (数据装载与查询语义)
        import requests

        # 阈值 400 而非 3xx: 3xx 在两阶段协议里是重定向而非失败, 抛了会把正常流程打断
        if self.status_code >= 400:  # 4xx 起才抛: 与 requests 的 raise_for_status 同口径, 3xx 交重定向
            raise requests.HTTPError(
                f"{self.status_code} replay response", response=self)

    def iter_content(self, chunk_size: int = 1):
        """字节流迭代 (下载类路径按块消费; 单次产出等价于整包)。"""
        data = self.text.encode("utf-8")  # 按块切分: 下载路径按 chunk 消费, 一次性返回会绕过块边界逻辑
        for start in range(0, len(data), chunk_size):                                        # 按块切分: 与 E6 的 transport 同一口径
            yield data[start:start + chunk_size]

    def close(self):
        """无真实句柄 — 空实现满足接口。"""
