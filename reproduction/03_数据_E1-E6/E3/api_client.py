"""E3 模型接口：独立上下文调用、供应商响应解析、实测用量与错误脱敏。"""
from __future__ import annotations

# 标准库：真实调用计时、有限重试和输出JSON解析。
import json
import time

# 第三方：复用最小环境已有HTTP客户端。
import requests

# 本轮载体：保存脱敏的请求与真实响应。
from common import now, redact


class APIError(RuntimeError):
    """携带真实尝试记录的调用失败，不产生替代科学回答。"""
    def __init__(self, message: str, attempts: list[dict]):
        """保存脱敏失败信息供续跑和人工排查。"""
        super().__init__(redact(message))
        self.attempts = redact(attempts)


def extract_text(body: dict, style: str) -> str:
    """按接口结构提取最终文本，拒绝截断与未完成响应。"""
    if style == "responses":
        if body.get("status") not in (None, "completed") or body.get("error"):
            raise ValueError("响应未完成或有错误，不计作有效回答")
        output = body.get("output", [])
        parts = [c["text"] for item in output if item.get("type") == "message"
                 for c in item.get("content", []) if c.get("type") == "output_text"]
        text = "\n".join(parts) or body.get("output_text", "")
    else:
        choices = body.get("choices", [])
        if not choices or choices[0].get("finish_reason") != "stop":
            raise ValueError("Chat Completions 未正常结束，不计作有效回答")
        text = choices[0].get("message", {}).get("content", "")
    if not isinstance(text, str) or not text.strip():
        raise ValueError("没有最终文本")
    return text.strip()


class ModelAPI:
    """仅调用配置指定的接口，不读取Codex登录凭据或隐式改模型。"""
    def __init__(self, values: dict, session=None):
        """接受已验证配置；会话可注入离线测试替身。"""
        self.values = values
        self.style = values["E3_API_STYLE"]
        self.session = session or requests.Session()

    def payload(self, role: str, system: str, user: str) -> dict:
        """固定角色参数；温度留空时不发送并在请求记录中体现。"""
        prefix = "E3_TEST" if role == "test" else "E3_JUDGE"
        payload = {"model": self.values[prefix + "_MODEL"]}
        effort = self.values.get(prefix + "_REASONING_EFFORT", "")
        if self.style == "responses":
            payload.update({"input": [{"role": "system", "content": system},
                                      {"role": "user", "content": user}],
                            "store": False, "max_output_tokens": int(self.values.get("E3_MAX_OUTPUT_TOKENS", "16384"))})
            if effort:
                payload["reasoning"] = {"effort": effort}
        else:
            payload.update({"messages": [{"role": "system", "content": system},
                                         {"role": "user", "content": user}],
                            "max_completion_tokens": int(self.values.get("E3_MAX_OUTPUT_TOKENS", "16384"))})
            if effort:
                payload["reasoning_effort"] = effort
        temperature = self.values.get("E3_TEMPERATURE", "")
        if temperature:
            payload["temperature"] = float(temperature)
        return payload

    def call(self, role: str, system: str, user: str) -> dict:
        """进行一次独立模型任务；仅为限流或瞬时网络错误有限重试。"""
        if role == "judge" and self.values.get("E3_JUDGE_MODE", "api") == "assistant":
            raise ValueError("当前协议禁止评分 API 调用；主评由当前助手完成")
        payload = self.payload(role, system, user)
        suffix = "/responses" if self.style == "responses" else "/chat/completions"
        endpoint = self.values["E3_API_BASE_URL"].rstrip("/") + suffix
        attempts = []
        for attempt in range(3):
            start = time.monotonic()
            stamp = now()
            try:
                response = self.session.post(endpoint, json=payload, timeout=(15, 180),
                    headers={"Authorization": "Bearer " + self.values["E3_API_KEY"],
                             "Content-Type": "application/json"})
                status = response.status_code
                try:
                    raw = response.json()
                except ValueError:
                    raw = {"non_json_body": response.text}
                attempts.append({"started_at": stamp, "ended_at": now(), "http_status": status,
                                 "elapsed_s": time.monotonic() - start, "response": redact(raw),
                                 "request": payload if attempt == 0 else None, "endpoint": endpoint})
                if status in (408, 429, 500, 502, 503, 504) and attempt < 2:
                    try:
                        delay = float(response.headers.get("Retry-After", 2 ** (attempt + 1)))
                    except ValueError:
                        delay = 2 ** (attempt + 1)
                    time.sleep(min(30, max(0, delay)))
                    continue
                if status >= 400:
                    raise APIError(f"API HTTP {status}；查看本批次失败记录，禁止自动删参或改模型", attempts)
                if not isinstance(raw, dict):
                    raise ValueError("API响应不是对象")
                text = extract_text(raw, self.style)
                if not raw.get("model"):
                    raise ValueError("供应商未返回实际模型标识，无法冻结模型来源")
                return redact({"request": payload, "endpoint": endpoint,
                               "requested_model": payload["model"], "returned_model": raw["model"],
                               "answer": text, "usage": raw.get("usage"), "response_id": raw.get("id"),
                               "attempts": attempts, "started_at": stamp, "ended_at": now()})
            except (requests.Timeout, requests.ConnectionError) as exc:
                attempts.append({"started_at": stamp, "ended_at": now(),
                                 "error_type": type(exc).__name__, "error": redact(str(exc)),
                                 "request": payload if attempt == 0 else None, "endpoint": endpoint})
                if attempt < 2:
                    time.sleep(2 ** (attempt + 1))
                    continue
                raise APIError("API网络连接失败", attempts) from None
            except APIError:
                raise
            except (ValueError, KeyError, TypeError) as exc:
                raise APIError(str(exc), attempts) from None
        raise APIError("调用未完成", attempts)


def parse_score(text: str) -> dict:
    """仅接受完整JSON对象；允许整个输出被一个Markdown代码块包围。"""
    text = text.strip()
    if text.startswith("```json\n") and text.endswith("\n```"):
        text = text[8:-4]
    elif text.startswith("```\n") and text.endswith("\n```"):
        text = text[4:-4]
    def unique(pairs):
        """拒绝重复JSON键，避免隐式覆盖评分。"""
        data = {}
        for key, value in pairs:
            if key in data:
                raise ValueError("评分JSON含重复键")
            data[key] = value
        return data
    value = json.loads(text, object_pairs_hook=unique)
    if not isinstance(value, dict):
        raise ValueError("评分JSON必须是对象")
    return value
