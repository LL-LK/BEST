"""E3 在线辅测固定查询：同题同重复两组共享实际回包，失败不变成零行。"""
from __future__ import annotations

# 标准库：记录冻结数据与实际HTTP状态。
import json
import time

# 第三方：只访问方案中明确授权的公开BEST服务。
import requests

# 本轮与仓内：共享指纹及原有生产客户端，在线记录存临时目录。
from common import now, fingerprint, redact
from src.ai_tools import ToolBox
from src.client import BestClient
from src.protocol import BEST_BASE_URL, is_soft_error


def collect_live(item: dict, repeat: int) -> dict:
    """采集一份公开实际记录，保留回包正文和失败证据。"""
    requests_log = []
    client = BestClient(rate_limit=2.0, timeout=45, max_retries=0)
    original = client.session.request
    def logged(method, url, **kwargs):
        """捕获真实HTTP请求与回包，禁止记录cookie或认证头。"""
        event = {"method": method, "url": url, "params": kwargs.get("params"),
                 "data": kwargs.get("data"), "started_at": now()}
        start = time.monotonic()
        try:
            response = original(method, url, **kwargs)
            event.update({"http_status": response.status_code, "body": response.text,
                          "ended_at": now(), "elapsed_s": time.monotonic() - start})
            requests_log.append(redact(event))
            return response
        except requests.RequestException as exc:
            event.update({"error_type": type(exc).__name__, "error": redact(str(exc)), "ended_at": now()})
            requests_log.append(event)
            raise
    client.session.request = logged
    tools = ToolBox(client)
    item_id = item["id"]
    started = now()
    try:
        if item_id in ("E3-A04", "E3-F02"):
            args = ({"ra": 180.0123, "dec": 30.0456, "radius_arcsec": 5.0}
                    if item_id == "E3-A04" else {"ra": 15.3, "dec": -72.6, "radius_arcsec": 3.0})
            result = tools.cone_search(catalog="ps1", max_rows=10, **args).to_dict()
            public = {"request": {"catalog": "ps1", **args}, "tool_result": result}
        elif item_id == "E3-G04":
            name = "BEST J180012.3+300456"
            public = {"request": {"name": name}, "tool_result": tools.resolve_name(name).to_dict()}
        elif item_id == "E3-F04":
            url = BEST_BASE_URL + "/skymapper_dr4/f"
            response = client.session.get(url, timeout=45)
            try:
                body = response.json()
            except ValueError:
                body = response.text
            public = {"request": {"method": "GET", "url": url}, "http_status": response.status_code,
                      "body": body, "soft_error": is_soft_error(response.text),
                      "observation_scope": "仅探测表单路由；不是查询数据的成功证明"}
        else:
            raise ValueError("不属于本轮在线题")
    except requests.RequestException as exc:
        public = {"request_failed": True, "error_type": type(exc).__name__, "error": redact(str(exc))}
    finally:
        client.session.close()
    return {"item_id": item_id, "repeat": repeat, "started_at": started, "ended_at": now(),
            "public_data": redact(public), "http_log": requests_log,
            "data_hash": fingerprint(public), "synthetic": False}


def live_state(record: dict) -> dict:
    """把实际回包状态作为评分真值；异常与未知状态不伪装成成功。"""
    public = record["public_data"]
    if public.get("request_failed"):
        return {"state": "request_failed", "data_hash": record["data_hash"]}
    envelope = public.get("tool_result")
    if envelope:
        return {"state": "success" if envelope["status"]["ok"] else "error",
                "status": envelope["status"], "data_hash": record["data_hash"]}
    return {"state": "route_probe", "http_status": public.get("http_status"),
            "soft_error": public.get("soft_error"), "data_hash": record["data_hash"]}
