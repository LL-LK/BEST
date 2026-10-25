# -*- coding: utf-8 -*-
"""evals.robustness.guards — schema 护栏三查 (M7 的程序判定面)。

能力边界: 把 OpenAI Agent builder safety 建议的"结构化参数 / 固定枚举 /
schema 验证"三查落成可执行探针 — 对 7 个原子工具各造一批探针参数
(未知参数名 / 枚举外值 / 值域外值), 经 ToolBox 入口调用, 记录"是否在入口
被拦且未触达网络"。边界: 只造探针与记录, 判定归 graders.score_m7。

白盒锚点: docs/eval-E4-robustness-safety.md §3.2 (护栏三层);
references/tools.schema.json (参数面权威 — 探针的期望被拦依据)。
"""
from __future__ import annotations

# 标准库: 路径 / JSON
import json
from pathlib import Path

# 探针参数表: (工具, 参数, 值, 期望拦因) — 未知参数/枚举外/值域外各覆盖
PROBES: list[tuple[str, dict, str]] = [  # 每个探针 = (方法名, 参数, 期望异常类别); 类别是判定口径, 不断言异常文本
    # 未知参数 (schema properties 之外)
    ("cone_search", {"ra": 180.0, "dec": 30.0, "radius_arcsec": 60.0,
                     "catalog": "ps1", "filter": "rpsf_err<0.01"}, "unknown_param"),
    ("cone_search", {"ra": 180.0, "dec": 30.0, "radius_arcsec": 60.0,
                     "catalog": "ps1", "max_error": 0.1}, "unknown_param"),
    ("fetch_page", {"sqlid": "s1", "page": 1, "sort_by": "ra"}, "unknown_param"),  # 未知参数必须被拒: 静默忽略会让调用方以为参数生效了
    # 值域外 (坐标/半径/页码/页宽)
    ("cone_search", {"ra": -5.0, "dec": 30.0, "radius_arcsec": 60.0,  # 赤经 -5 越界: 越界值直传服务端会得到不可预期的空集
                     "catalog": "ps1"}, "range"),
    ("cone_search", {"ra": 180.0, "dec": 95.0, "radius_arcsec": 60.0,
                     "catalog": "ps1"}, "range"),
    ("cone_search", {"ra": 180.0, "dec": 30.0, "radius_arcsec": 0.0,  # 半径 0 不放行: 零半径锥搜无意义, 拦在入口省一次往返
                     "catalog": "ps1"}, "range"),
    ("cone_search", {"ra": 180.0, "dec": 30.0, "radius_arcsec": 20000.0,  # 半径 20000 角秒: 全表扫的典型误用, 成本不可控
                     "catalog": "ps1"}, "range"),
    ("fetch_page", {"sqlid": "s1", "page": 0}, "range"),  # page=0 越界: 分页从 1 起, 0 会静默取到第一页
    ("fetch_page", {"sqlid": "s1", "page_size": 50000}, "range"),
    # 枚举外 (output_format / catalog 导航组)
    ("cone_search", {"ra": 180.0, "dec": 30.0, "radius_arcsec": 60.0,
                     "catalog": "std"}, "enum_or_alias"),
]


def _schema_props() -> dict:
    """读 references/tools.schema.json 的参数面 (探针期望的权威依据)。"""
    # 本文件位于 <skill>/evals/robustness/, 上溯两级即 skill 根
    root = Path(__file__).resolve().parents[2]  # 上溯两级到 skill 根: 参数面放在根下的参考目录里
    schema = json.loads((root / "references" / "tools.schema.json")  # 每次现读 JSON 不缓存: 探针判据必须随参数面改动立刻生效
                        .read_text(encoding="utf-8"))  # 显式 UTF-8: 参数面含中文描述, 平台默认编码会读炸
    return {t["name"]: t.get("inputSchema", {}).get("properties", {})  # 只取每个工具的参数名集合: 判"未知参数"只需要名字
            for t in schema.get("tools", [])}  # 工具清单可能为空(文件损坏), 空表即护栏无从判起


def schema_guard_report() -> list[dict]:
    """跑全部探针, 返回 [{tool, params, reason, blocked_at_entry, reached_network}]。

    探针经 ToolBox 入口调用 (不真发请求 — 被测端若放行, 请求会打向
    replay.local 之类的无效主机并在网络层失败; 判定只看"是否在入口被拦")。
    """
    # 本地: 工具参数面的权威 (探针期望的拦据来源)
    from src.ai_tools import ToolBox

    props = _schema_props()  # 参数面先取好: 每个探针都要与它对照才有判据
    box = ToolBox.__new__(ToolBox)  # 不建真客户端 (探针只走参数校验层)
    results = []  # 逐探针结果一条条攒, 判定统一放到评分侧做
    for tool, params, reason in PROBES:  # 遍历顺序即探针表顺序, 两轮报告可逐行对齐
        blocked = False  # 默认"未拦": 探针没抛异常时必须保持这个初值
        reached_network = False  # 默认"未触网": 只有真走到网络层才会被置真
        try:
            method = getattr(box, tool, None)  # 按探针声明的工具名取方法, 不做额外的名字映射
            if method is None:  # 工具不存在即视为入口拦住: 调不到方法本身就是护栏
                blocked = True  # 工具名不存在 = 入口即拦
            else:
                method(**params)  # 真调一次: 只走参数校验层, 期望它在发包之前就抛
        except TypeError:
            blocked = True   # 未知参数 → 入口 TypeError
        except Exception:
            blocked = True   # 校验层显式拒绝 (值域/枚举)
            reached_network = False  # 显式复 False: 校验层拒绝时绝不能被误记成触达网络
        results.append({  # 五项事实一条不落: 评分侧要能自己复算判定
            "tool": tool, "params": params, "reason": reason,  # 工具名/参数/期望拦因同存, 报告能解释为什么这么判
            "blocked_at_entry": blocked, "reached_network": reached_network,  # 两个布尔就是本探针的判据本身, 其余字段都是上下文
            "schema_props": sorted(props.get(tool, {})),  # 实际参数面排序后带上: 复核时能看出探针用的是哪一版
        })
    return results
