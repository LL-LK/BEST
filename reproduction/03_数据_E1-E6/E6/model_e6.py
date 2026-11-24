"""真实 Responses 工具调用客户端：完整上下文、原始回包、实际 usage。"""
# 标准库和第三方：网络调用与耗时记录。
import time
import requests
# 临时公共设施：安全脱敏与指纹。
from common_e6 import fp, utc, redact

class ModelAPI:
    """只使用被授权生成端点，禁止隐式改模型或删除参数。"""
    def __init__(self, values):
        """保存请求配置与独立 HTTP 会话。"""
        self.values = values
        self.session = requests.Session()
        self.endpoint = values["E3_API_BASE_URL"].rstrip("/") + "/responses"

    def parameters(self):
        """生成冻结请求参数；空温度明确不发送。"""
        params = {"model": self.values["E3_TEST_MODEL"], "store": False,
                  "max_output_tokens": int(self.values["E3_MAX_OUTPUT_TOKENS"])}
        if self.values.get("E3_TEST_REASONING_EFFORT"):
            params["reasoning"] = {"effort": self.values["E3_TEST_REASONING_EFFORT"]}
        if self.values.get("E3_TEMPERATURE"):
            params["temperature"] = float(self.values["E3_TEMPERATURE"])
        return params

    def call(self, context, tools, emit):
        """保存每次实际请求和回包；瞬时失败最多重试两次。"""
        payload = {**self.parameters(), "input": context, "tools": tools, "tool_choice": "auto"}
        for attempt in range(1, 4):
            req = emit("model_request", {"request": payload, "endpoint": self.endpoint,
                       "model_id": payload["model"], "temperature": payload.get("temperature"),
                       "seed": None, "prompt_fp": fp(context[0]), "messages_fp": fp(context),
                       "schema_fp": fp(tools)}, layer="model", attempt=attempt)
            start = time.monotonic()
            try:
                # 真实模型请求；认证头不保存到 trace。
                response = self.session.post(self.endpoint, json=payload,
                    headers={"Authorization": "Bearer " + self.values["E3_API_KEY"]}, timeout=(15, 180))
                try:
                    body = response.json()
                except ValueError:
                    body = {"non_json_body": response.text}
                body = redact(body)
                emit("model_response", {"raw": body, "raw_fp": fp(body), "http_status": response.status_code,
                     "latency_s": time.monotonic() - start, "finish_reason": body.get("status"),
                     "usage": body.get("usage"), "returned_model": body.get("model")},
                     layer="model", attempt=attempt, parent_seq=req["seq"])
                if response.status_code in (408, 429, 500, 502, 503, 504) and attempt < 3:
                    emit("retry", {"retry_of_seq": req["seq"], "reason": "transient_model_http",
                         "strategy_changed": False}, layer="model", attempt=attempt)
                    time.sleep(min(30, max(0, float(response.headers.get("Retry-After", 2 ** attempt)))))
                    continue
                if response.status_code >= 400:
                    raise RuntimeError(f"模型 HTTP {response.status_code}")
                if body.get("status") != "completed" or body.get("error") or not body.get("model"):
                    raise RuntimeError("模型响应未完成、有错误或缺实际模型标识")
                if not body.get("output"):
                    raise RuntimeError("模型没有输出")
                return body
            except (requests.ConnectionError, requests.Timeout) as exc:
                emit("error", {"layer": "model", "error_code": type(exc).__name__, "is_retryable": True,
                     "detail": str(exc), "latency_s": time.monotonic() - start}, layer="model", parent_seq=req["seq"])
                if attempt == 3:
                    raise RuntimeError("模型网络失败，保留全部失败尝试") from None
                emit("retry", {"retry_of_seq": req["seq"], "reason": "model_network",
                     "strategy_changed": False}, layer="model", attempt=attempt)
                time.sleep(2 ** attempt)
        raise RuntimeError("模型调用未完成")

def final_text(body):
    """仅提取模型真实最终消息，不将推理或工具参数当答案。"""
    return "\n".join(c["text"] for item in body.get("output", []) if item.get("type") == "message"
                     for c in item.get("content", []) if c.get("type") == "output_text").strip()

def function_schemas(mcp_tools):
    """按 Responses 格式投影项目真实工具 schema。"""
    return [{"type": "function", "name": t["name"], "description": t["description"],
             "parameters": t["inputSchema"]} for t in mcp_tools]
