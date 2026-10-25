# -*- coding: utf-8 -*-
"""evals.semantics.runner — E3 入口 (items → prescreen L0 → 报告)。

能力边界: 编排件 — 读 items.yaml (37 题 7 轴), 对每条 fixture 题跑 L0
机器预筛, 汇总输出 JSON/Markdown。边界: **不调大模型、不联网** (Tier F
的 L2 判定需真模型跑批产出回答 (2026-10-03 起 LLM-only, 无人工评阅),
  机器侧只到 L0 预筛 + 数据完备); 跑批产物 (回答) 由实验
主持人另行采集, runner 接受 `--answers` 注入已采集的回答 JSON。

白盒锚点: docs/eval-E3-semantics.md §13 (执行流程与产物) / §7.3 (预筛)。
"""
from __future__ import annotations

# 标准库: 参数解析 / JSON / 路径 / 时间戳 / 类型标注
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# 本地: 中立载体 (skill 根 + YAML 装载; evals/ 兄弟裸导入约定)。
# 脚本直跑时 sys.path[0] 只含本目录 — 同时挂 skill 根 (evals.* 命名空间包)
# 与 evals/ (paths 兄弟裸导入)。
_HERE = Path(__file__).resolve()  # 先 resolve: 经软链调用时上溯层级会算错, 路径锚必须先归一
sys.path.insert(0, str(_HERE.parents[1]))   # evals/
sys.path.insert(0, str(_HERE.parents[2]))   # skill 根
# 本地: 兄弟裸导入的 YAML 装载件 (evals/ 在路径上)
from paths import load_yaml_file  # noqa: E402

# 本地: 反证自证/预筛/报告三件 (L0 机器预筛入口)
from evals.semantics.broken import run_broken_selftest  # noqa: E402
from evals.semantics.prescreen import prescreen  # noqa: E402
from evals.semantics.report import render_report  # noqa: E402

SEMANTICS_DIR = _HERE.parent                      # 本实验根
ITEMS_PATH = SEMANTICS_DIR / "items.yaml"        # 37 题 7 轴题集, 判定的事实源


def load_items(items_path: Path = ITEMS_PATH) -> dict:
    """读题集 (items.yaml); 缺失/空 → fail-closed 抛错。"""
    if not items_path.is_file():  # 题集缺失即抛: 静默出空报告会伪装成"全批零违规"
        raise FileNotFoundError(f"E3 题集缺失: {items_path}")
    data = load_yaml_file(items_path)  # 走中立载体的 YAML 装载件: 同一套方言, 不各写各的
    if not data.get("items"):   # 空题集即抛: 静默出空报告会伪装成"全批零违规"
        raise ValueError(f"E3 题集为空: {items_path}")
    return data


def load_answers(path: Optional[str]) -> dict[str, str]:
    """读已采集的回答 (JSON: ``{item_id: answer_text}``); 缺省返回空。"""
    if not path:                 # 未给 --answers 时返回空: 离线只跑题集完备性
        return {}
    return json.loads(Path(path).read_text(encoding="utf-8"))   # 一次读全: 回答是事先采好的, 不流式


def load_rubric_prescreen() -> dict:
    """读 rubric.yaml 的 ``prescreen`` 节 (预筛口径的文档权威)。

    存在的理由 (2026-10-04): prescreen.py 的模块头要求"改窗口宽度/否定词表/
    安全语境表都必须同步回改 rubric §3, 否则预筛口径会与文档脱钩" —— 但此前
    rubric 的 prescreen 节只有正则, 窗口与词表只活在代码里, 那条要求无处校验。
    把它做成可装载的口径块后, test_e3.py 就能断言"代码里的窗口/词表 == rubric
    里写的", 脱钩由测试发现而不是靠人记得。

    Returns:
        ``rubric["prescreen"]`` 字典; 缺节即抛 (口径块缺了就无法校验, 静默兜空
        会让脱钩永远绿灯)。
    """
    rubric = load_yaml_file(SEMANTICS_DIR / "rubric.yaml")  # 走同一套 YAML 方言, 不另引解析器
    spec = rubric.get("prescreen")
    if not spec:   # fail-closed: 缺节就不能校验口径, 兜空字典会让脱钩检测恒绿
        raise ValueError("E3 rubric.yaml 缺 prescreen 节 — 预筛口径无文档权威")
    return spec


def aggregate(results: list[dict]) -> dict:
    """把逐题预筛结果聚合成系统级摘要 (九个数中 L0 可算的部分)。"""
    agg = {   # 披露数里只有这六个 L0 机器可算; L2 判定相关的见下方占位键
        "n_items": len(results),
        "static_as_lc_triggered": sum(
            1 for r in results if r["summary"]["static_as_lc_triggered"]),
        "sentinel_misuse_count": sum(
            r["summary"]["sentinel_misuse_count"] for r in results),
        "unsourced_number_count": sum(
            r["summary"]["unsourced_number_count"] for r in results),
        "fatal_candidate_count": sum(
            r["summary"]["fatal_candidate_count"] for r in results),
        "unsupported_claim_count": sum(
            r["summary"]["unsupported_claim_count"] for r in results),
        "qualifier_missing_count": sum(
            len(r["summary"]["qualifier_missing"]) for r in results),
    }
    # L0 可算的预筛版指标 (L2 判定的 SFA/UCR/SLR/RQC 以 L2 为准, 此处显式标占位)
    total_numbers = sum(   # UNGR 的分母: 全批出现过的数值总数, 不是题数
        r["hits"]["unsourced_numbers"]["total_numbers"] for r in results)
    agg["ungr"] = (agg["unsourced_number_count"] / total_numbers) if total_numbers else 0.0  # 分母为零时给 0.0: 没有数值就不该产比值, 但也不该抛
    # 下面几个键先占位: L2 判定前报告 schema 就得定死, 否则前后两版报告无法对账
    agg["sfa"] = "待 L2 判定"  # 语义保真率占位: L2 判定前给不出分, 写 0 会被读成"跑了得零分"
    agg["mcnemar"] = "待 L2 判定"  # McNemar 检验要等 L2 判定出结果才填
    agg["ucr"] = "待 L2 判定"  # 不可回答率占位, 口径以 L2 判定为准
    agg["slr"] = "待 L2 判定"  # 自限率占位, 不由机器预筛代算
    agg["rqc"] = "待 L2 判定"  # 限定语质量属 L2 判定维度, 预筛阶段不猜
    # 2026-10-07 删去 agg["agreement"] 与 agg["arbitration"]: 两个键原本只是为
    # 「一致性统计 + 人工仲裁」保留的 schema 占位, 而那条能力已于 2026-10-03 整链取消
    # (LLM-only, 见 docs/eval-E3-semantics.md §10)。连同实现它的同目录模块一并删除 ——
    # 那份模块全仓零消费者 (19.9 KB, 算 κ/α/AC1/ICC, 而 κ 只在**两个真正独立的人**
    # 手上有定义)。留一个恒为占位的键, 等于让读者以为"一致性"这件事还在算。
    # (注释里不写那个文件名: 仓内路径必须真实存在, 而它已随本次删除消失。)
    return agg


def run(items_path: Path = ITEMS_PATH, answers: dict | None = None,
        system: str = "S-A") -> dict:
    """跑 L0 预筛: 逐题 prescreen + 反证自证 + 汇总。"""
    data = load_items(items_path)         # 题集必到: 缺失即抛, 不出半份报告
    fixtures = data.get("fixtures") or {}   # 哨兵阈值/溯源池的宿主, 缺则两路判据无基准
    items = data["items"]  # 题集一次取出: 主循环与 live 计数共用同一份, 不重复解析
    answers = answers or {}                 # None 与 {} 同义: CLI 不给 --answers 也走这条
    results = []                            # 只收有回答的题: 未采集的题不进分母
    for item in items:  # 按题集顺序遍历, 保证报告行序逐次可复现
        answer = answers.get(item["id"], "")   # 按 id 直取: 回答 JSON 的键即 item id
        if not answer:  # 空回答即视为未采集: 空串与缺键同义, 都不进分母
            continue  # 未采集回答的题不进预筛 (主持人另采)
        results.append(prescreen(answer, item, fixtures))   # 逐题独立, 顺序不影响结论
    selftest = run_broken_selftest(fixtures)   # 与预筛共用同一 fixtures, 免出两套哨兵阈值
    n_live = sum(1 for i in items if i.get("tier") == "live")   # live 题要人工采集, 离线跑批里多半是 fixture 题
    return {  # 汇总块按系统名收一层: 多系统并列时渲染层结构不用改
        "system": system,
        "generated_at": datetime.now(timezone.utc).isoformat(),   # UTC 带时区: 跨机比不带会错位
        "n_items": len(items),
        "n_fixture": len(items) - n_live,
        "n_live": n_live,
        "n_answered": len(results),
        "prescreen": {system: aggregate(results)} if results else {},   # 按系统名收一层, 便于多系统并列
        "results": results,
        "metascore": selftest["metascore"],
        "selftest": selftest,
    }


def main(argv: Optional[list] = None) -> int:
    """CLI: ``--items/--answers/--system/--json/--md``; 退出码 0/1 (metascore)。"""
    parser = argparse.ArgumentParser(description="E3 semantics runner (L0 prescreen)")  # 命令行只暴露五个参数, 指标口径不进帮助文本
    parser.add_argument("--items", default=str(ITEMS_PATH))  # 题集可注入: 离线验证预筛时常换题集重跑
    parser.add_argument("--answers", default="", help="已采集回答 JSON {item_id: text}")  # 回答走外部注入: 由主持人另采, 跑批自己不联网取
    parser.add_argument("--system", default="S-A")  # 系统名只作报告标签: 换标签不改变任何判据
    parser.add_argument("--json", default="", help="JSON 输出路径")  # json 留空即不落盘: 默认只打标准输出, 跑批无副作用
    parser.add_argument("--md", action="store_true", help="打印 Markdown 报告")  # md 是开关: 默认给机器可读摘要, 人工复核按需再看
    parser.add_argument("--md-out", default="", help="Markdown 报告落盘路径 (docs §13 要求的 REPORT.md 永久资产)")  # 报告要入库, 打印到终端不算数
    parser.add_argument("--require-coverage", action="store_true",
                        help="实验门禁: 未采集回答的题记 answers_missing 阻断 (铁律 5 禁 fail-open)")  # 与 E2 的 --require-human-review 同款
    args = parser.parse_args(argv)  # argv 缺省走命令行: 这样单测可以直调 main()

    summary = run(Path(args.items), load_answers(args.answers), args.system)  # 一次跑批拿到全部结果, 渲染与落盘共用同一份数据
    # 覆盖度门禁: metascore 只证明"预筛器抓得住坏样本", 不证明"任何题被评测过"。
    # 零回答时两者都是绿的, 于是 exit 0 会被读成"E3 通过" —— 铁律 5 意义上的 fail-open。
    # 开启 --require-coverage 后, 未采集的题逐条记 answers_missing 并阻断。
    missing = [i["id"] for i in load_items(Path(args.items))["items"]
               if not (load_answers(args.answers) or {}).get(i["id"])]
    summary["answers_missing"] = missing           # 报告正面披露: 缺哪几题一目了然
    summary["coverage_ok"] = not missing           # 覆盖度是否成立
    summary["coverage_required"] = bool(args.require_coverage)  # 闸门开没开也要记, 免得 PASS 被读成"评过了"
    if args.json:  # 给了 json 路径才写盘, 避免跑批顺手污染工作区
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)  # 目录自建: Makefile 写 temp/<exp>/report.json 时父目录可能还不存在
        out.write_text(  # 显式 UTF-8 且不转义: 中文说明在文件里要能直接读
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.md_out:  # 落盘版: 与 --json 同形, 路径由调用方 (Makefile) 指定, 不猜默认落点
        md_path = Path(args.md_out)
        md_path.parent.mkdir(parents=True, exist_ok=True)  # 目录自建: 首次生成 REPORT.md 时父目录可能还不存在
        md_path.write_text(render_report(summary) + "\n", encoding="utf-8", newline="\n")  # newline="\n": 跨平台不写成 CRLF
    if args.md:   # --md 给人读; 否则只打去掉逐题明细的机器摘要
        print(render_report(summary))
    else:
        print(json.dumps({k: v for k, v in summary.items()  # 默认摘要剔掉逐题明细: 终端保持可读, 明细走 json
                          if k not in ("results", "selftest")},
                         ensure_ascii=False, indent=2))
    # 两条阻断, 任一命中即 exit 1 (E3 FAIL 语义):
    #   1) metascore < 1.0 → 预筛规则失效, 判定器不灵, 本轮分数不作数;
    #   2) 开了覆盖度闸门但有题没回答 → 实验根本没跑, 不许判通过。
    if summary["metascore"] < 1.0:
        return 1
    return 1 if (args.require_coverage and not summary["coverage_ok"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
