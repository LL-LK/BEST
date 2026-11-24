# -*- coding: utf-8 -*-
"""evals.groundtruth.transport — 快照回放传输层 (哑回放 + 查询语义模拟)。

能力边界: 造一个"假网卡" — 不去访问网站, 从快照目录把冻结的回包递给被测
代码。两种模式:
  - ``SnapshotTransport`` (哑回放): POST → phase1.html; getcount → count.json;
    page=N → pages/page_NNNN.csv 原文。快照即"某次查询的冻结答案";
  - ``QueryAwareTransport`` (查询语义模拟): 解析 POST 表单 (锥/矩形/proximity/
    约束/排序), 对 rows_full.csv **独立执行**后现场算答案 — 用于场景查询与
    快照冻结查询不一致的对账 (E2 §5: 每用例自带查询参数)。

模拟边界 (文档化, 不模拟的部分):
  - showcol 投影**不模拟** — 响应列集 = 快照列集 (投影正确性是 E1 的
    columns 参数与 E2 missing_column 场景的职责);
  - proximity 走"冻结答案直通" (rows_full 即服务端 proximity 应答, 含
    inputobjs_* 回连列);
  - 分页/计数/排序/约束/锥距为协议语义, 按表单键逐项落实 (haversine 为
    本模块独立实现, 与 GT oracle 同公式不同代码 — 假服务器与金标准互相
    独立, 一方写错会被 M1 对账抓出)。

白盒锚点: docs/eval-E2-groundtruth.md §3.3 (回放方式) / §5 (每用例查询
参数); src/protocol.py build_query_form (表单键集的权威形态)。
"""
from __future__ import annotations

# 标准库: 路径锚定 / JSON 回包读取 / 调用计数 / 数学 (haversine) / CSV 读取
import csv
import hashlib
import json
import math
from pathlib import Path
from typing import Any


class FakeResponse:
    """requests.Response 最小替身 (快照原文的载体)。

    只实现被测链路消费的成员: ``status_code`` / ``text`` / ``headers`` /
    ``raise_for_status()`` / ``close()``。``text`` 一律快照原文 (保留 BOM、
    无表头形态、哨兵值 — 真实脏形态是 E2 的保真要求)。
    """

    def __init__(self, status_code: int, text: str, headers: dict | None = None):
        """记录状态码/回包原文/响应头 (快照三件套)。"""
        self.status_code = status_code
        self.text = text
        self.headers = headers or {}
        self.closed = False

    def raise_for_status(self) -> None:
        """非 2xx 抛 requests.HTTPError (与真实 requests 同语义)。"""
        import requests

        if self.status_code >= 400:
            raise requests.HTTPError(
                f"{self.status_code} snapshot replay error", response=self)

    def close(self) -> None:
        """标记关闭 (被测链路流读尽后会调; 快照无真实句柄)。"""
        self.closed = True

    def iter_content(self, chunk_size: int = 1):
        """字节流迭代 (下载类探针消费; 快照按整文本一次性产出)。"""
        data = self.text.encode("utf-8")
        for start in range(0, len(data), chunk_size):
            yield data[start:start + chunk_size]


class SnapshotTransport:
    """快照回放传输层: 按 URL 路由到快照目录的冻结回包。

    路由规则 (E2 §3.3):
      - POST ``/{catalog}/q`` → ``phase1.html`` (内含 sqlid 链接);
      - GET 含 ``/getcount`` → ``count.json`` 原文;
      - GET 含 ``/sqlid/{id}`` 且带 ``page=N`` → ``pages/page_NNNN.csv`` 原文;
      - 其余 GET (根路径等) → ``root.html`` (存在则回, 否则 404 替身)。

    用法 (与被测代码接线)::

        client = BestClient(base_url="http://snapshot.local", rate_limit=0.0)
        client.session.get = transport.get
        client.session.post = transport.post
    """

    def __init__(self, snap_dir: str | Path) -> None:
        """记住快照目录 (不存在即抛 — 回放目标必须真实存在)。"""
        self.snap_dir = Path(snap_dir)
        if not self.snap_dir.is_dir():
            raise FileNotFoundError(f"快照目录缺失: {snap_dir}")
        self.call_count = 0
        self.calls: list[tuple[str, str]] = []
        self.events: list[dict] = []

    def _read(self, path: Path) -> str:
        """读快照文件原文 (utf-8-sig 兼容 BOM — 保真读取, 不转码)。"""
        return path.read_text(encoding="utf-8-sig")

    def _record(self, method: str, url: str, route: str, response: FakeResponse,
                form: dict | None = None) -> FakeResponse:
        """记录离线请求路由与原始响应指纹；不把大响应体重复写入trace。"""
        self.events.append({"method": method, "url": url, "route": route,
                            "status": response.status_code,
                            "response_bytes_sha256": hashlib.sha256(
                                response.text.encode("utf-8")).hexdigest(),
                            "response_bytes": len(response.text.encode("utf-8")),
                            "form": form})
        return response

    def get(self, url: str, **kwargs: Any) -> FakeResponse:
        """顶替 ``session.get``: 按 URL 路由到 getcount / 分页 CSV / 根回包。"""
        self.call_count += 1
        self.calls.append(("GET", url))
        if "/getcount" in url:
            path = self.snap_dir / "count.json"
            if path.is_file():
                return self._record("GET", url, "count.json", FakeResponse(200, self._read(path)))
            return self._record("GET", url, "synthetic-empty-count", FakeResponse(200, json.dumps({"total": 0})))
        if "/sqlid/" in url:
            page = _query_param(url, "page") or "1"
            path = self.snap_dir / "pages" / f"page_{int(page):04d}.csv"
            if path.is_file():
                return self._record("GET", url, path.relative_to(self.snap_dir).as_posix(),
                                    FakeResponse(200, self._read(path)))
            # 末页之后: 空表 (0 行即末页 — 与站点行为一致)
            return self._record("GET", url, "empty-terminal-page", FakeResponse(200, ""))
        root = self.snap_dir / "root.html"
        if root.is_file():
            return self._record("GET", url, "root.html", FakeResponse(200, self._read(root)))
        return self._record("GET", url, "missing-root", FakeResponse(404, "<html>404</html>"))

    def post(self, url: str, **kwargs: Any) -> FakeResponse:
        """顶替 ``session.post``: 回 phase-1 HTML (sqlid 链接的载体)。"""
        self.call_count += 1
        self.calls.append(("POST", url))
        path = self.snap_dir / "phase1.html"
        if path.is_file():
            return self._record("POST", url, "phase1.html", FakeResponse(200, self._read(path)), kwargs.get("data"))
        return self._record("POST", url, "missing-phase1", FakeResponse(200, "<html>no sqlid</html"), kwargs.get("data"))


def _query_param(url: str, name: str) -> str | None:
    """从 URL 查询串取参数值 (无查询串/无该参数 → None)。"""
    if "?" not in url:
        return None
    query = url.split("?", 1)[1]
    for pair in query.split("&"):
        if "=" in pair:
            key, value = pair.split("=", 1)
            if key == name:
                return value
    return None


# ── 查询语义模拟回放 (场景查询 ≠ 快照冻结查询时的对账底座) ────────────────

def _haversine_arcsec(ra1: float, dec1: float, ra2: float, dec2: float) -> float:
    """大圆角距 (角秒) — 假服务器侧独立实现 (与 GT oracle 同公式不同代码)。

    公式: a = sin²(Δdec/2) + cos(dec1)·cos(dec2)·sin²(Δra/2);
    分离角 = 2·asin(√a)。sin² 以 360° 为周期 → RA 跨 0–360 天然 wrap-safe。
    """
    r1, d1, r2, d2 = map(math.radians, (ra1, dec1, ra2, dec2))
    a = (math.sin((d2 - d1) / 2.0) ** 2
         + math.cos(d1) * math.cos(d2) * math.sin((r2 - r1) / 2.0) ** 2)
    return math.degrees(2.0 * math.asin(min(1.0, math.sqrt(a)))) * 3600.0


def _to_float(value: Any) -> float | None:
    """安全转 float (空/不可解析 → None)。"""
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class QueryAwareTransport(SnapshotTransport):
    """查询语义模拟回放: 解析 POST 表单, 对 rows_full 独立执行后现场算答案。

    与哑回放的分工: 哑回放用于"快照即该查询的答案" (L 类直通); 本类用于
    场景自带查询参数、需要按协议语义现场过滤的对账 (E2 §5 全部用例)。

    表单键 (权威形态见 src/protocol.py build_query_form):
      - 空间: ``pos.type`` = cone (pos.racenter/pos.deccenter/pos.radius) /
        rect (pos.ramin/ramax/decmin/decmax) / proximity (pos.radecTextarea,
        直通不重算) / none;
      - 排序: ``sort`` (``{table}.{column}`` 限定形) + ``order``;
      - 约束: ``{table}.{column}.operation`` + ``.min``/``.max`` (between)
        或 ``.constraint`` (单值) 或 ``.textarea`` (contains/in);
      - 分页: URL 的 ``rows`` (page_size) 与 ``page``。
    """

    def __init__(self, snap_dir: str | Path) -> None:
        """记住快照目录并初始化查询状态 (表单在 POST 时解析)。"""
        super().__init__(snap_dir)
        self._form: dict[str, str] = {}
        self._rows_cache: list[dict] | None = None
        self.page_rows: list[list[dict]] = []

    # ── rows_full 装载 (UTF-8-sig 保真读取) ──
    def _load_rows(self) -> list[dict]:
        """读 rows_full.csv (懒加载 + 缓存; 缺失即空 — 错误态快照无真值行)。"""
        if self._rows_cache is None:
            path = self.snap_dir / "rows_full.csv"
            if not path.is_file():
                self._rows_cache = []
            else:
                with path.open("r", encoding="utf-8-sig", newline="") as handle:
                    self._rows_cache = [dict(r) for r in csv.DictReader(handle)]
        return self._rows_cache

    # ── POST: 解析表单 (data 是 requests 的 form 编码字典) ──
    def post(self, url: str, **kwargs: Any) -> FakeResponse:
        """顶替 ``session.post``: 记录表单查询语义, 回 phase-1 HTML。"""
        data = kwargs.get("data") or {}
        self._form = {str(k): str(v) for k, v in data.items()}
        return super().post(url, **kwargs)

    # ── 查询执行 (空间 → 约束 → 排序) ──
    def _row_coord(self, row: dict) -> tuple[float | None, float | None]:
        """取行的 (ra, dec) — 兼容裸列名与带星表前缀两种形态。"""
        ra = dec = None
        ra_keys = ["ra", "ps1_ra"] + sorted(k for k in row if k.endswith("_ra") and not k.startswith("inputobjs_") and k not in ("ra", "ps1_ra"))
        dec_keys = ["dec", "ps1_dec"] + sorted(k for k in row if k.endswith("_dec") and not k.startswith("inputobjs_") and k not in ("dec", "ps1_dec"))
        for key in ra_keys:
            if row.get(key) not in (None, ""):
                ra = _to_float(row[key])
                break
        for key in dec_keys:
            if row.get(key) not in (None, ""):
                dec = _to_float(row[key])
                break
        return ra, dec

    def _spatial_filter(self, rows: list[dict]) -> list[dict]:
        """按表单空间键过滤: cone / rect / proximity (冻结答案+nearestonly) / none。"""
        pos_type = self._form.get("pos.type", "none")
        if pos_type == "proximity":
            return self._proximity_filter(rows)
        if pos_type == "cone":
            return self._cone_filter(rows)
        if pos_type == "rect":
            return self._rect_filter(rows)
        return rows  # none: 无空间约束 (全表扫描式提交)

    def _cone_filter(self, rows: list[dict]) -> list[dict]:
        """锥形过滤 (pos.racenter/pos.deccenter/pos.radius; d ≤ radius 含等号)。"""
        ra_c = _to_float(self._form.get("pos.racenter"))
        dec_c = _to_float(self._form.get("pos.deccenter"))
        radius = _to_float(self._form.get("pos.radius"))
        if ra_c is None or dec_c is None or radius is None:
            return rows
        kept = []
        for row in rows:
            ra, dec = self._row_coord(row)
            if ra is None or dec is None:
                continue
            if _haversine_arcsec(ra_c, dec_c, ra, dec) <= radius:
                kept.append(row)
        return kept

    def _rect_filter(self, rows: list[dict]) -> list[dict]:
        """矩形过滤 (pos.ramin/ramax/decmin/decmax; 闭区间)。"""
        ra_min = _to_float(self._form.get("pos.ramin"))
        ra_max = _to_float(self._form.get("pos.ramax"))
        dec_min = _to_float(self._form.get("pos.decmin"))
        dec_max = _to_float(self._form.get("pos.decmax"))
        if None in (ra_min, ra_max, dec_min, dec_max):
            return rows
        kept = []
        for row in rows:
            ra, dec = self._row_coord(row)
            if ra is None or dec is None:
                continue
            if ra_min <= ra <= ra_max and dec_min <= dec <= dec_max:
                kept.append(row)
        return kept

    def _proximity_filter(self, rows: list[dict]) -> list[dict]:
        """proximity: 冻结答案直通 + nearestonly 时每输入行只留最小角距行。

        快照的 rows_full 即服务端 proximity 应答 (含 inputobjs_* 回连列);
        ``proximity_nearestonly`` 在表单里时, 服务端按每个输入位置只回最近
        邻 — 假服务器按 inputobjs_input_line 分组、取 inputobjs_dist_arcsec
        最小行复刻该语义 (与 GT 的最近邻判定互为独立实现)。
        """
        if "proximity_nearestonly" not in self._form:
            return rows
        best: dict[str, dict] = {}
        for row in rows:
            line = str(row.get("inputobjs_input_line", ""))
            dist = _to_float(row.get("inputobjs_dist_arcsec"))
            current = best.get(line)
            if current is None:
                best[line] = row
                continue
            current_dist = _to_float(current.get("inputobjs_dist_arcsec"))
            if dist is not None and (current_dist is None or dist < current_dist):
                best[line] = row
        return [best[line] for line in sorted(best)]

    def _constraint_filter(self, rows: list[dict]) -> list[dict]:
        """按表单约束键过滤 (``{col}.operation`` + min/max/constraint/textarea)。

        列名解析: 表单用限定形 (``ps1.source_id``), 快照行用裸形
        (``source_id``) 或前缀形 (``ps1_source_id``) — ``_resolve_cell``
        三种形态依次尝试 (站点 showcol 与响应列同源不同形, E1 §6.2 的
        column 归一化同口径)。
        """
        ops: dict[str, dict] = {}
        for key, value in self._form.items():
            if key.endswith(".operation"):
                ops.setdefault(key[: -len(".operation")], {})["op"] = value
            elif key.endswith(".min"):
                ops.setdefault(key[: -len(".min")], {})["min"] = value
            elif key.endswith(".max"):
                ops.setdefault(key[: -len(".max")], {})["max"] = value
            elif key.endswith(".constraint"):
                ops.setdefault(key[: -len(".constraint")], {})["value"] = value
            elif key.endswith(".textarea"):
                ops.setdefault(key[: -len(".textarea")], {})["value"] = value
        if not ops:
            return rows
        kept = []
        for row in rows:
            ok = True
            for column, spec in ops.items():
                cell = self._resolve_cell(row, column)
                if cell in (None, ""):
                    ok = False
                    break
                op = spec.get("op", "equal")
                try:
                    if op == "between":
                        lo, hi = _to_float(spec.get("min")), _to_float(spec.get("max"))
                        num = _to_float(cell)
                        ok = ok and lo is not None and hi is not None and num is not None and lo <= num <= hi
                    elif op in ("equal",):
                        ok = ok and str(cell).strip() == str(spec.get("value", "")).strip()
                    elif op in ("less",):
                        ok = ok and _to_float(cell) is not None and _to_float(cell) < _to_float(spec.get("value"))
                    elif op in ("grater", "greater"):
                        ok = ok and _to_float(cell) is not None and _to_float(cell) > _to_float(spec.get("value"))
                    elif op in ("greaterequal",):
                        ok = ok and _to_float(cell) is not None and _to_float(cell) >= _to_float(spec.get("value"))
                    elif op in ("lessequal",):
                        ok = ok and _to_float(cell) is not None and _to_float(cell) <= _to_float(spec.get("value"))
                    elif op in ("notequal",):
                        ok = ok and str(cell).strip() != str(spec.get("value", "")).strip()
                    elif op in ("contains", "in"):
                        ok = ok and str(spec.get("value", "")) in str(cell)
                    else:
                        ok = False  # 未知操作不猜 (fail-closed)
                except (TypeError, ValueError):
                    ok = False
                if not ok:
                    break
            if ok:
                kept.append(row)
        return kept

    @staticmethod
    def _resolve_cell(row: dict, column: str) -> Any:
        """限定列名 → 行内取值: ``ps1.source_id`` → ``ps1_source_id`` → ``source_id``。"""
        if column in row:
            return row[column]
        if "." in column:
            prefixed = column.replace(".", "_")
            if prefixed in row:
                return row[prefixed]
            bare = column.split(".", 1)[1]
            if bare in row:
                return row[bare]
        return None

    def _sort_rows(self, rows: list[dict]) -> list[dict]:
        """按表单 sort/order 排序 (限定列名 ``{table}.{column}`` → 行内取列)。"""
        sort_key = self._form.get("sort")
        if not sort_key:
            return rows

        def key_func(row):
            value = self._resolve_cell(row, sort_key)
            if value in (None, ""):
                return (1, 0.0, "")
            try:
                return (0, float(value), "")
            except (TypeError, ValueError):
                return (0, 0.0, str(value))

        order = (self._form.get("order") or "asc").lower()
        return sorted(rows, key=key_func, reverse=(order == "desc"))

    def _apply(self, rows: list[dict]) -> list[dict]:
        """空间 → 约束 → 排序 (协议语义的假服务器侧落实)。"""
        return self._sort_rows(self._constraint_filter(self._spatial_filter(rows)))

    # ── GET: getcount/page 按查询语义现场算 ──
    def get(self, url: str, **kwargs: Any) -> FakeResponse:
        """顶替 ``session.get``: getcount 回查询后总数; page 回查询后当页 CSV。

        错误态快照 (无 rows_full — 快照即"服务端错误应答"的冻结) 走**哑回放**
        直通: 查询语义无从算起 (没有真值行), 冻结的错误页就是答案本身。
        """
        self.call_count += 1
        self.calls.append(("GET", url))
        if not (self.snap_dir / "rows_full.csv").is_file():
            return super().get(url, **kwargs)
        if "/getcount" in url:
            total = len(self._apply(self._load_rows()))
            return self._record("GET", url, "query-aware-count", FakeResponse(200, json.dumps({"total": total})))
        if "/sqlid/" in url:
            page = int(_query_param(url, "page") or "1")
            page_size = int(_query_param(url, "rows") or "1000")
            rows = self._apply(self._load_rows())
            chunk = rows[(page - 1) * page_size: page * page_size]
            if chunk:
                self.page_rows.append([dict(row) for row in chunk])
            route = f"query-aware-page:{page}" if chunk else f"query-aware-empty-page:{page}"
            return self._record("GET", url, route,
                                FakeResponse(200, self._to_csv(chunk)))
        return super().get(url, **kwargs)

    @staticmethod
    def _to_csv(rows: list[dict]) -> str:
        """行字典列表 → CSV 文本 (列序取首行键序; 空结果给空文本 — 末页形态)。"""
        if not rows:
            return ""
        import io

        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
        return buffer.getvalue()
