"""完整请求语义快照：真实记录、固定响应、未知分支失败关闭。"""
# 标准库与第三方：二进制保存、URL规范化、响应载体。
import base64
import json
import re
import time
from urllib.parse import urlsplit, parse_qsl, urlencode, urlunsplit
import requests
# 项目权威解析器和临时安全设施。
from src.protocol import parse_sqlid
from common_e6 import fp, redact, read, write

def request_key(method, url, kwargs, aliases):
    """保留表单、名称、分页、投影及排序；sqlid 映射到建会话查询。"""
    parts = urlsplit(url)
    path = re.sub(r"(/sqlid/)(s?\d+)", lambda m: m[1] + aliases.get(m[2].lstrip("s"), "unbound:" + m[2]), parts.path)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query.update(kwargs.get("params") or {})
    data = kwargs.get("data") or {}
    if not isinstance(data, dict):
        raise ValueError("快照请求仅支持项目实际字典表单")
    data = {k: str(v) for k, v in data.items()}
    for k in ("pos.racenter", "pos.deccenter", "pos.radius", "pos.defaultRadius"):
        if k in data:
            try:
                data[k] = format(float(data[k]), ".15g")
            except ValueError:
                pass
    semantic = {"method": method.upper(), "url": urlunsplit((parts.scheme, parts.netloc, path, urlencode(sorted(query.items())), "")),
                "data": data, "json": kwargs.get("json")}
    return fp(semantic), redact(semantic)

def pack_response(response):
    """保留真实响应正文、状态和非凭据头；重定向也逐条保留。"""
    allowed = {k: v for k, v in response.headers.items() if k.lower() in
               ("content-type", "content-length", "date", "etag", "last-modified", "location", "retry-after")}
    text = redact(response.text)
    original_safe = text == response.text
    content = response.content if original_safe else text.encode(response.encoding or "utf-8")
    retry = getattr(getattr(response, "raw", None), "retries", None)
    history = [{"method": h.method, "url": h.url, "status": h.status, "error": str(h.error) if h.error else None,
                "redirect_location": h.redirect_location} for h in getattr(retry, "history", ())]
    return redact({"status": response.status_code, "url": response.url, "headers": allowed,
                   "encoding": response.encoding, "content_base64": base64.b64encode(content).decode(),
                   "text": text, "retries": history, "redirects": [pack_response(r) for r in response.history]})

def unpack_response(record):
    """恢复 requests.Response，无任何站点网络请求。"""
    response = requests.Response()
    response.status_code = record["status"]
    response.url = record["url"]
    response.headers.update(record["headers"])
    response.encoding = record["encoding"]
    response._content = base64.b64decode(record["content_base64"])
    response.history = [unpack_response(r) for r in record.get("redirects", [])]
    return response

class Transport:
    """在 Session.request 层接线，保证工具自身成本计数仍有效。"""
    def __init__(self, client, emit, bank=None):
        """在线保持生产重试和限速；离线完全禁用网络。"""
        self.client, self.emit, self.bank = client, emit, bank
        self.aliases, self.records, self.misses = {}, [], []
        self.session_requests = 0
        self.wait_s = 0.0
        self.original = client.session.request
        self.original_wait = client._rate_limit_wait
        client.session.request = self.request
        client._rate_limit_wait = self.wait

    def wait(self):
        """实测限速等待，不用请求数乘固定秒数估算。"""
        start = time.monotonic()
        self.original_wait()
        self.wait_s += time.monotonic() - start

    def request(self, method, url, **kwargs):
        """记录每个请求最终响应及重试历史；缺快照不回伪造空表。"""
        key, semantic = request_key(method, url, kwargs, self.aliases)
        self.session_requests += 1
        start = time.monotonic()
        record = {"request_key": key, "request": semantic, "original_url": url,
                  "mode": "live" if self.bank is None else "replay"}
        try:
            if self.bank is None:
                # 调用真实项目 Session；不覆盖生产 adapter 的重试策略。
                response = self.original(method, url, **kwargs)
                record["response"] = pack_response(response)
            else:
                source = self.bank.get(key)
                if source is None:
                    self.misses.append(key)
                    raise requests.ConnectionError("E_SNAPSHOT_MISS：请求语义未冻结 " + key)
                record["source_fp"] = fp(source)
                if source.get("error"):
                    error_class = getattr(requests, source.get("error_type", "ConnectionError"), requests.ConnectionError)
                    raise error_class(source["error"])
                response = unpack_response(source["response"])
                record["response"] = source["response"]
            if method.upper() == "POST":
                sqlid = parse_sqlid(response.text)
                if sqlid:
                    self.aliases[sqlid.lstrip("s")] = key
            return response
        except requests.RequestException as exc:
            record.update({"error": str(exc), "error_type": type(exc).__name__})
            raise
        finally:
            record["elapsed_s"] = time.monotonic() - start
            self.records.append(redact(record))
            self.emit("network_exchange", record, layer="network")

def freeze_bank(paths, out):
    """按输入顺序选首个实测响应，不合成结果；保留所有来源指针。"""
    bank, sources, excluded = {}, {}, []
    for path in paths:
        try:
            events = [json.loads(line) for line in path.read_text().splitlines()]
        except ValueError:
            excluded.append({'trace':str(path),'reason':'incomplete_jsonl_original_retained'})
            continue
        if not events or events[-1]['type'] != 'run_end':
            excluded.append({'trace':str(path),'reason':'unterminated_original_retained'})
            continue
        for event in events:
            if event["type"] != "network_exchange":
                continue
            record = event["payload"]
            if record.get("mode") != "live":
                continue
            key = record["request_key"]
            sources.setdefault(key, []).append({"trace": str(path), "seq": event["seq"], "fp": fp(record)})
            if key not in bank:
                bank[key] = record
    write(out, {"bank": bank, "sources": sources, "excluded_sources":excluded, "fingerprint": fp(bank),
                "selection": "first_observed_per_exact_request_semantics", "network_allowed": False,
                "limitation": "urllib3 内部重试保存 status/error 历史；中间重试正文不暴露，未声称完整 wire 抓包"})
    return bank
