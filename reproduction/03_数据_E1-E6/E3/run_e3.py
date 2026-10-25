"""E3 本轮统一入口：准备、检查、试运行、全量采集评分、专家复核和报告。"""
from __future__ import annotations

# 标准库：统一命令入口，错误不输出包含密钥的堆栈。
import argparse
import sys
from pathlib import Path

# 本轮公共载体：先挂载仓根，再加载实验模块。
from common import HERE, ROOT, config, current_batch, redact
sys.path.insert(0, str(ROOT))

# 本轮设施：不改生产源码，输出统一位于temp/e3-formal。
from prepare import prepare
from pipeline import batch_lock, collect, connection_check, grade, prescreen_all
from reporting import report
from review import export_review, import_expert


def main(argv=None) -> int:
    """执行选定阶段；配置缺项返回2，真实调用或评分失败返回1。"""
    parser = argparse.ArgumentParser(description="E3 修订协议正式实验工作流")
    parser.add_argument("command", choices=("prepare", "check", "pilot", "collect", "prescreen", "grade", "export", "import-expert", "assistant-export", "assistant-import", "report", "run"))
    parser.add_argument("--expert-scores", type=Path)
    parser.add_argument("--assistant-scores", type=Path)
    args = parser.parse_args(argv)
    batch = None
    try:
        config()
        batch = prepare() if args.command in ("prepare", "run") else current_batch()
        print("批次："+str(batch), flush=True)
        with batch_lock(batch):
            if args.command == "prepare":
                export_review(batch)
                report(batch)
                print("准备材料已保存；尚未进行模型或BEST网络调用。")
            elif args.command == "check":
                connection_check(batch)
            elif args.command == "pilot":
                connection_check(batch)
                collect(batch, pilot=True)
                prescreen_all(batch)
                grade(batch, pilot=True)
            elif args.command == "collect":
                collect(batch)
            elif args.command == "prescreen":
                prescreen_all(batch)
            elif args.command == "grade":
                grade(batch)
            elif args.command == "export":
                print(export_review(batch))
            elif args.command == "assistant-export":
                from assistant_review import export_assistant
                print(export_assistant(batch))
            elif args.command == "assistant-import":
                from assistant_review import import_assistant
                if args.assistant_scores is None:
                    raise ValueError("需要 --assistant-scores 指定当前助手逐份评分JSON")
                print(import_assistant(batch, args.assistant_scores))
            elif args.command == "import-expert":
                if args.expert_scores is None:
                    raise ValueError("需要 --expert-scores 指定专家独立评分JSON")
                import_expert(batch, args.expert_scores)
            elif args.command == "run":
                connection_check(batch)
                collect(batch, pilot=True)
                prescreen_all(batch)
                grade(batch, pilot=True)
                collect(batch)
                prescreen_all(batch)
                grade(batch)
                export_review(batch)
            summary = report(batch)
            print(f"采集 {summary['collection']['actual']}/216，评分 {summary['rating']['actual']}/216，专家 {summary['expert']['status']}")
        return 0
    except KeyboardInterrupt:
        if batch:
            from common import write_json, now
            write_json(batch / "interruption.json", {"at": now(), "status": "interrupted", "in_flight_usage": None})
        print("执行已中断，成功产物保留；未收到的在途回包与usage不可推测。", file=sys.stderr)
        return 130
    except (ValueError, OSError, RuntimeError) as exc:
        print("未完成："+redact(str(exc)), file=sys.stderr, flush=True)
        if batch:
            try:
                report(batch)
            except (ValueError, OSError, RuntimeError):
                print("现有资产校验失败，保留旧报告，禁止输出新的科学结论。", file=sys.stderr)
        _, missing = config()
        return 2 if missing else 1


if __name__ == "__main__":
    raise SystemExit(main())
