"""开跑前验证服务商模型、参数、工具选择与工具结果续接。"""
# 标准库：真实调用记录、时间与 JSON。
import json
import time
# 项目和临时设施：实际工具实现及被授权模型接口。
from common_e6 import HERE, config, write, now, redact
from model_e6 import ModelAPI, function_schemas, final_text
from ops.best_mcp_server import McpServer
from src.ai_tools import ToolBox

def main():
    """实际完成一个零站点请求工具闭环并保存原始证据。"""
    values = config()
    api = ModelAPI(values)
    box = ToolBox()
    mcp = McpServer(box).handle_message({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    records = []
    def emit(kind, payload, **kwargs):
        """收集脱敏事件，探针不混入正式样本。"""
        event = {"seq": len(records), "type": kind, "payload": redact(payload), **kwargs}
        records.append(event)
        return event
    context = [{"role": "system", "content": "你是工具调用兼容性探针。请使用 list_catalogs 工具，读取回包后用中文简要报告星表数量，不猜测。"},
               {"role": "user", "content": "请通过工具确认 BEST 可查询多少张星表。"}]
    path = HERE / "preflight" / ("probe-" + str(time.time_ns()) + ".json")
    result = {"started_at": now(), "request_parameters": api.parameters(), "mcp_tools_list": mcp}
    try:
        for turn in range(4):
            body = api.call(context, function_schemas(mcp["result"]["tools"]), emit)
            context.extend(body["output"])
            calls = [i for i in body["output"] if i.get("type") == "function_call"]
            if not calls:
                result.update({"answer": final_text(body), "returned_model": body["model"],
                               "passed": bool(final_text(body)) and any(e["type"] == "tool_result" for e in records)})
                break
            for call in calls:
                args = json.loads(call["arguments"])
                if call["name"] != "list_catalogs":
                    raise RuntimeError("兼容性探针意外请求其它工具")
                emit("tool_call", call)
                envelope = box.list_catalogs(**args).to_dict()
                emit("tool_result", envelope)
                context.append({"type": "function_call_output", "call_id": call["call_id"],
                                "output": json.dumps(envelope, ensure_ascii=False)})
        else:
            raise RuntimeError("探针超过模型回合上限")
    except Exception as exc:
        result.update({"passed": False, "error": str(exc)})
    result.update({"ended_at": now(), "records": records})
    write(path, result)
    print(json.dumps({"path": str(path), "passed": result.get("passed"), "error": result.get("error"),
                      "requested_model": api.parameters()["model"], "returned_model": result.get("returned_model")}))
    return 0 if result.get("passed") else 1

if __name__ == "__main__":
    raise SystemExit(main())
