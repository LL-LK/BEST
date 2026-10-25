#!/usr/bin/env python3
"""ops/best_mcp_server.py — astro-best MCP server (stdio, 传输层零第三方依赖)。

能力边界: 把 src.ai_tools.ToolBox 的 7 个原子工具以 MCP (JSON-RPC 2.0 over
stdio) 暴露: initialize / ping / tools/list / tools/call。**传输层**零第三方
依赖 (stdlib json + sys.stdin 逐行读); 但工具实现经 src.ai_tools -> src.client
依赖 requests/urllib3 — 进程级不是零依赖, MCP host 需预装 requests
(无 requests 的环境 import 即失败, 与 tools.schema.json 的 _server.dependencies
表述对齐)。
边界: 本文件只做传输与参数编解码, 不含业务逻辑;
schema 权威在 references/tools.schema.json; 凭据只读 env, 本进程不落盘。
白盒锚点: references/ALGORITHM-SPEC.md §7 (工具面锚点);
references/download-playbook.md (下载类任务另走下载栈, 不走本 server)。

运行:
    python ops/best_mcp_server.py            # stdio MCP server
    python ops/best_mcp_server.py --selftest # 离线自检 (不发任何网络请求)
    python ops/best_mcp_server.py --live     # 对真实站点做一次最小连通性检查

工具实现走 src.ai_tools (权威层); 传输层按 MCP stdio 约定自写, 零第三方依赖。
"""
from __future__ import annotations

# 标准库组 (传输层零第三方依赖; 业务层 requests 依赖见模块 docstring):
#   json   —— JSON-RPC 2.0 帧的编解码 (stdio 一行一帧)
#   sys    —— 逐行读 stdin / 写 stdout, 以及把 skill 根注入 sys.path
#   pathlib—— 定位 references/tools.schema.json (schema 权威文件)
#   typing —— 帧/工具 schema 的宽松类型标注 (Any 容忍 JSON 动态结构)
import json
import sys
from pathlib import Path
from typing import Any

SKILL_ROOT = Path(__file__).resolve().parents[1]  # 上溯一级 = skill 根, src/ 平铺的 sys.path 注入基准
# 把 skill 根注入 sys.path: src/ 平铺后 `import src.*` 依赖它; 未注入则本 server 起不来
if str(SKILL_ROOT) not in sys.path:  # 幂等注入: 重复 import 不把同一路径塞两遍
    sys.path.insert(0, str(SKILL_ROOT))                                               # 注入 skill 根: 让 src.* 可导入 (脚本直跑自挂路径)

# 本地 src.* 导入 (跨能力边界: 传输层 -> 权威业务层):
#   ai_tools.TOOL_NAMES/ToolBox —— 7 个原子工具与工具名元组 (权威实现在 src/)
#   client.BEST_BASE_URL        —— REST 端点常量 (--live 探针用, 不硬编码 URL)
from src.ai_tools import TOOL_NAMES, ToolBox  # noqa: E402
from src.client import BEST_BASE_URL  # noqa: E402

SERVER_NAME = "astro-best"  # initialize 握手里报的 serverInfo.name, 与 skill 名同源
SCHEMA_PATH = SKILL_ROOT / "references" / "tools.schema.json"  # 工具面契约唯一出处, 运行时只读不改
PROTOCOL_VERSION = "2024-11-05"  # MCP 协议修订标识 (非本 skill 发布版本号)


# ---------------------------------------------------------------------------
# Tool schemas
# ---------------------------------------------------------------------------

def load_tool_schemas() -> list[dict[str, Any]]:
    """从 references/tools.schema.json 装载工具契约 (name/title/description/inputSchema)。

    只做字段投影与缺省兜底, 不在这里发明 schema —— schema 权威在 JSON 文件里,
    改动工具面必须同步改该文件, 否则 MCP host 与实现会漂移。

    Returns:
        按文件顺序排列的工具描述字典列表。

    Raises:
        FileNotFoundError / json.JSONDecodeError: schema 文件缺失或损坏 (显式失败, 不 fail-open)。
    """
    payload = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))  # 唯一外部输入; 缺失即显式失败, 不 fail-open
    return [
        {                                                                              # 工具描述表: 名字与说明成对, 数量要与 schemas 断言对齐
            "name": tool["name"],
            "title": tool.get("title", tool["name"]),  # title 缺省回落 name, 免得 host 拿到空标题
            "description": tool["description"],
            "inputSchema": tool["inputSchema"],
            "annotations": tool.get("annotations", {"readOnlyHint": True}),  # 缺省全只读: 声明宁可比实现少, 不多承诺
        }
        for tool in payload["tools"]
    ]


# ---------------------------------------------------------------------------
# JSON-RPC plumbing
# ---------------------------------------------------------------------------

def _result(message_id: Any, result: Any) -> dict[str, Any]:
    """构造 JSON-RPC 2.0 成功响应帧 (id 原样回显, 通知场景下可能为 None)。"""
    return {"jsonrpc": "2.0", "id": message_id, "result": result}  # id 原样回显; 通知场景由调用方给 None


def _error(message_id: Any, code: int, message: str) -> dict[str, Any]:
    """构造 JSON-RPC 2.0 错误响应帧 (code 用协议保留值: -32700/-32601/-32602)。"""
    return {"jsonrpc": "2.0", "id": message_id, "error": {"code": code, "message": message}}  # 只用协议保留码, 不自造业务码


class McpServer:
    """Line-delimited JSON-RPC 2.0 server over stdio (MCP transport)。

    职责边界: 只做传输与参数编解码 — 方法路由、参数校验、结果信封化;
    不含任何业务逻辑 (业务在 src.ai_tools.ToolBox)。**传输层**零第三方依赖:
    全部用 stdlib json + sys.stdin/stdout 逐行读写 (进程级仍经 src.client
    依赖 requests/urllib3, 见模块 docstring)。
    """

    def __init__(self, toolbox: ToolBox | None = None) -> None:
        """构造 JSON-RPC 服务外壳。

        Args:
            toolbox: 工具实现; 传 None 时自建真实 ``ToolBox`` (会去建 BEST 客户端)。
                selftest 与单测必须传入离线桩, 否则自检会真的发网络请求。

        Note:
            这里只做协议外壳 (读一行 JSON -> 派发 -> 写一行 JSON), 业务全在
            ``src.ai_tools.ToolBox``; 外壳保持传输层零第三方依赖。
        """
        self.toolbox = toolbox or ToolBox()  # 允许注入离线桩: 真 ToolBox 会建客户端发请求
        self.schemas = load_tool_schemas()  # 构造期就装载, tools/list 不碰盘, 免得每帧重读

    # -- dispatch -----------------------------------------------------------

    def handle_message(self, message: dict[str, Any]) -> dict[str, Any] | None:
        """路由一个 JSON-RPC 消息; 通知 (notification) 无 id, 返回 None 即不回帧。

        非 dict 帧 (合法 JSON 但不是 object: int/str/list/bool/null) 一律回
        -32600 而不抛异常 —— 首行 ``message.get`` 对它们会抛 AttributeError,
        冒泡出 serve() 循环即杀死整个 MCP 进程, 一次脏帧就让 7 工具面整体不可用。

        Args:
            message: 已解析的 JSON 值。类型标注是 dict 但**运行期不保证**:
                stdio 上的输入不可信, 判据由本函数自己把 (不是靠调用方先筛)。

        Returns:
            响应帧字典; 对 notifications/* 返回 None (协议要求通知不应答);
            对非 object 帧返回 -32600 (Invalid Request)。
        """
        if not isinstance(message, dict):  # 运行期类型闸: 标注是 dict 但输入不可信
            # id 无法从非 object 帧里取 (它本身就没有 .get), 故按 JSON-RPC 2.0
            # 规定传 null, 与 -32700 解析失败路径同口径
            return _error(None, -32600, f"Invalid Request: expected a JSON object, got {type(message).__name__}")
        method = message.get("method")  # 协议路由的唯一判据
        message_id = message.get("id")
        params = message.get("params") or {}

        if method == "initialize":
            # 握手: 声明协议修订 + 能力面 (tools.listChanged=False 表示工具集静态)
            return _result(message_id, {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": False}},  # 工具集静态: 不支持运行期增删
                "serverInfo": {"name": SERVER_NAME, "title": "astro-best BEST 数据工具面"},
            })
        if method == "notifications/initialized" or (method or "").startswith("notifications/"):
            # 通知一律静默: 回帧会违反 JSON-RPC 语义并可能卡死 host
            return None
        if method == "ping":
            return _result(message_id, {})
        if method == "tools/list":
            return _result(message_id, {"tools": self.schemas})  # 顺序即 schema 文件顺序, 与 TOOL_NAMES 逐字对齐
        if method == "tools/call":
            return self._call_tool(message_id, params)
        return _error(message_id, -32601, f"Method not found: {method!r}")

    def _call_tool(self, message_id: Any, params: dict[str, Any]) -> dict[str, Any]:
        """执行 tools/call: 按 name 分发到 ToolBox 同名方法, 并把结果信封化。

        Args:
            message_id: 请求 id, 原样回显。
            params: 含 name (工具名) 与 arguments (关键字参数) 的参数字典。

        Returns:
            成功时 content 为 JSON 文本且 isError 由业务 status.ok 决定;
            参数/工具名错误返回 JSON-RPC -32602; 业务异常转为 isError=True 的
            工具结果帧 (MCP 约定: 工具失败不是协议错误)。
        """
        name = str(params.get("name") or "")  # 强制转 str: 非字符串名直接落白名单外
        arguments = params.get("arguments") or {}
        if name not in TOOL_NAMES:  # 白名单先于 getattr, 防任意属性调用
            # 白名单校验: 只允许 schema 登记过的 7 个工具, 防任意属性调用
            return _error(message_id, -32602, f"Unknown tool: {name!r}")
        method = getattr(self.toolbox, name)  # 白名单已过, 取到的必然是 ToolBox 的同名工具
        try:
            result = method(**arguments)  # 关键字展开: 参数名或个数错会在这里抛 TypeError
        except TypeError as exc:
            # 参数名/个数不匹配 -> 协议级参数错误 (调用方改请求即可)
            return _error(message_id, -32602, f"Invalid arguments for {name}: {exc}")
        except Exception as exc:  # noqa: BLE001 - surfaced as a tool error
            # 业务异常不冒泡出 serve() 循环: 收敛为 isError 结果帧, 保连接存活
            return _result(message_id, {
                "content": [{"type": "text",
                             "text": json.dumps({"error": f"{type(exc).__name__}: {exc}"},
                                                ensure_ascii=False)}],                              # 工具清单的收尾
                "isError": True,
            })
        return _result(message_id, {
            "content": [{"type": "text",
                         "text": json.dumps(result.to_dict(), ensure_ascii=False)}],
            "isError": not result.status.get("ok", False),  # 业务成败映射到 isError, 协议层不报错
        })

    # -- stdio loop ----------------------------------------------------------

    def serve(self, stdin: Any = None, stdout: Any = None) -> int:
        """stdio 主循环: 逐行读帧 -> 解析 -> 路由 -> 写帧 (一行一响应)。

        Args:
            stdin: 可注入的输入流 (测试用); 缺省 sys.stdin。
            stdout: 可注入的输出流 (测试用); 缺省 sys.stdout。

        Returns:
            输入流正常结束时返回 0。**任何单帧都不回崩**: 解析失败回 -32700,
            合法 JSON 但非 object 回 -32600, 处理器内部异常回 -32603, 三种脏帧
            各自回一帧后继续读下一行。
        """
        stdin = stdin or sys.stdin  # 可注入, 供单测喂离线帧
        stdout = stdout or sys.stdout                                                          # 默认走标准输出, 便于测试时注入 StringIO
        for line in stdin:                                                                          # 逐行读: JSON-RPC 是一行一条
            line = line.strip()                                                                     # 去空白
            if not line:                                                                            # 空行跳过
                # 空行是 keep-alive/分隔噪声, 直接跳过 (不是错误)
                continue
            try:
                # 读点: 每行一个 JSON-RPC 帧 (MCP stdio 传输约定)
                message = json.loads(line)  # 解析失败走下一道, 不在这里吞
            except json.JSONDecodeError:
                # 坏帧只回一次 Parse error 并继续: 不能因一行脏数据杀死 server
                stdout.write(json.dumps(_error(None, -32700, "Parse error")) + "\n")  # id 传 null: 坏帧的 id 本身不可信
                stdout.flush()                                                            # 每条响应后立刻 flush: 不 flush 客户端会一直等
                continue
            # 兜底闸: 处理器再完整也有落空的分支 (新方法名、参数形态变化、
            # 第三方库行为)。stdio 上的一行脏数据不该终止整个 MCP 会话 ——
            # 冒泡出去 = 进程退出 = host 侧整个工具面失联。
            # 业务异常另有 _call_tool 的 isError 帧兜着, 走到这里的是协议层意外。
            try:
                response = self.handle_message(message)                                             # 交给消息处理器
            except Exception as exc:  # noqa: BLE001 - 单帧异常不得终止 stdio 会话
                response = _error(message.get("id") if isinstance(message, dict) else None,  # 非 dict 帧的 id 取不到, 按 null 回
                                  -32603, f"Internal error: {type(exc).__name__}: {exc}")            # -32603: 协议保留码, 不自造
            if response is not None:                                                               # 无响应也要 flush (错误路径已写过)
                # 写点: 响应必须立即 flush, 否则 host 会因管道缓冲假死
                stdout.write(json.dumps(response, ensure_ascii=False) + "\n")  # 写点: 必须立即 flush, 否则管道缓冲会让 host 假死
                stdout.flush()                                                                      # 响应写出后 flush
        return 0  # 输入流正常结束即成功; 单帧错误不回崩整个 server


# ---------------------------------------------------------------------------
# Self-test / live probe
# ---------------------------------------------------------------------------

def selftest() -> int:
    """离线自检: schema 计数、工具面顺序、信封形态 (全程零网络请求)。

    自检刻意只调用"答案来自本地已核实登记表"的工具 (list_catalogs /
    describe_catalog) 与一条已知坏输入, 从而在完全不触网的前提下证明
    工具面可用。任何一项 FAIL 都返回 1。

    Returns:
        全部通过返回 0; 任一失败返回 1。
    """
    checks: list[tuple[bool, str]] = []                                                      # 自检清单: (结果, 标签) 成对, 便于最后统一汇总

    schemas = load_tool_schemas()                                                                   # 从 schema 文件读工具声明
    checks.append((len(schemas) == len(TOOL_NAMES) == 7,                              # 工具数三方对齐 (schemas / TOOL_NAMES / 7)
                   f"schema/tool counts: {len(schemas)}/{len(TOOL_NAMES)}"))
    names = [tool["name"] for tool in schemas]
    checks.append((tuple(names) == TOOL_NAMES, f"tool order matches TOOL_NAMES: {names}"))
    for tool in schemas:                                                                            # 逐工具检查
        schema = tool["inputSchema"]
        checks.append((schema.get("type") == "object" and "properties" in schema,
                       f"{tool['name']} inputSchema is an object schema"))

    # 离线工具必须只从已核验的注册表应答, 一次 HTTP 都不发 (否则自检会依赖网络)
    server = McpServer(ToolBox())  # 传真 ToolBox: 下面几条断言要读真实登记结果
    catalogs = server.toolbox.list_catalogs()                                                       # 客户端要真能用: 列星表是一次真实往返
    checks.append((catalogs.status["ok"] and catalogs.cost["http_requests"] == 0,
                   "list_catalogs is offline and ok"))
    described = server.toolbox.describe_catalog("ps1")
    checks.append((described.status["ok"] and described.data["catalog"] == "ps1",
                   "describe_catalog('ps1') answers from the registry"))
    rejected = server.toolbox.describe_catalog("std")
    checks.append((not rejected.status["ok"] and rejected.status["error_code"] == "E_INVALID_INPUT",
                   "describe_catalog('std') rejects the navigation group"))

    # 错误路径上的信封形态 (同样不发网络请求: 用坏的工具名类型触发)
    bad = server.toolbox.cone_search("not-a-number", 30.0)
    checks.append((not bad.status["ok"] and "cost" in bad.to_dict()
                   and "provenance" in bad.to_dict(),
                   "error path still returns the full envelope"))

    failed = [label for ok, label in checks if not ok]                                              # 失败项汇总
    for ok, label in checks:                                                                        # 逐项打印
        print(f"[{'PASS' if ok else 'FAIL'}] {label}")
    print(f"selftest: {len(checks) - len(failed)}/{len(checks)} passed")
    return 1 if failed else 0


def live_probe() -> int:
    """对真实站点做一次最小连通性检查 (仅 1 个 GET, 显式 opt-in)。

    这是全文件唯一的网络调用点, 只在 --live 时触发; serve()/selftest 路径
    绝不触网, 保证 MCP host 拉起 server 时不会偷偷发请求。

    Returns:
        站点返回 200 返回 0; 其它状态码或任何网络异常返回 1。
    """
    # 惰性导入: requests 只在真正跑 live 探针时才需要 (离线 selftest 不依赖它)
    import requests

    try:
        # 外部 HTTP 调用点: GET BEST 站点根路径, timeout=30 防挂死
        resp = requests.get(f"{BEST_BASE_URL}/", timeout=30)
        ok = resp.status_code == 200                                                                # 以 HTTP 200 为成功判据
        print(f"[{'PASS' if ok else 'FAIL'}] GET {BEST_BASE_URL}/ -> {resp.status_code} ({len(resp.content)} bytes)")
        return 0 if ok else 1
    except Exception as exc:  # noqa: BLE001
        # 网络异常一律收敛为 FAIL 行 + 非零退出, 不抛栈污染 stdio 协议流
        print(f"[FAIL] live probe: {exc}")
        return 1


def main(argv: list[str] | None = None) -> int:
    """入口: --selftest 走离线自检, --live 走真实探针, 缺省起 stdio server。

    Args:
        argv: 可选参数向量 (测试可注入); 缺省读 sys.argv。

    Returns:
        子功能退出码 (见 selftest/live_probe/serve)。
    """
    argv = list(sys.argv[1:] if argv is None else argv)                                         # argv 缺省取命令行实参: 便于测试直接传列表
    if "--selftest" in argv:
        return selftest()
    if "--live" in argv:
        return live_probe()
    return McpServer().serve()


if __name__ == "__main__":
    raise SystemExit(main())
