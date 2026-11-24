"""ops/knowledge_capture.py — 知识沉底管道的"传送带": 运行时事件 → 候选知识条目。

能力边界: 只做**归集与去重**, 不做判断 (不自动批准、不自动改写既有知识)。
产出落在 ``.knowledge/inbox/``, 必须过审才能升格进 ``rag/knowledge/``。

为什么要有 inbox 这道闸:
    ``rag/knowledge/`` 是 A 路 (槽位) 与 B 路 (RAG) 的**唯一真源**, 且受
    "只增不减硬锁"保护 — 一旦脏数据进去就很难清掉, 而且会同时污染两条取用
    路。所以自动化的边界止于"提出候选", 入库这一步留给人。

用法:
    python ops/knowledge_capture.py                      # 扫全量日志
    python ops/knowledge_capture.py --since 7d --limit 50
    python ops/knowledge_capture.py --dry-run            # 只看会产出什么, 不落盘
"""
from __future__ import annotations

# 标准库: argparse CLI / hashlib 去重指纹 / json 解析日志行 / 时间窗口 /
# 路径与原子落盘 / 类型标注
import argparse
import hashlib
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

try:
    # 第三方: PyYAML 写候选条目 (硬依赖, 缺失即显式失败)
    import yaml
except ImportError as _exc:  # pragma: no cover - 环境相关
    raise SystemExit("knowledge_capture 需要 PyYAML: pip install pyyaml") from _exc

# ── 路径锚点 ──────────────────────────────────────────────────────────
# 本文件位于 ops/ 下, 上跳一级即 skill 根。
SKILL_ROOT = Path(__file__).resolve().parents[1]     # 解析后取父级: 换机换克隆位置照样成立
DEFAULT_LOG = SKILL_ROOT / ".logs" / "task_log.jsonl"  # 默认事件源: 运行时写的那份 JSONL
DEFAULT_INBOX = SKILL_ROOT / ".knowledge" / "inbox"  # 候选落点: 审批前一律不进 rag/knowledge/

# ── 归集策略 (G7: 超参必须显式可复核) ─────────────────────────────────
# 只归集"有信息量"的事件: 成功路径 (submit/start/page/done) 不产知识,
# 只有失败/拦截/决策才承载经验。
CAPTURE_EVENTS: tuple[str, ...] = ("failed", "blocked", "hook", "ask")  # 白名单外的成功事件一律不收

# 事件 → 建议归入的知识文件 (归类是建议, 不是判定, 由审批者改)
EVENT_TO_TYPE: dict[str, str] = {                    # 值只是建议归类, 审批者可改
    "failed": "known_issues",    # 跑挂了 → 已知问题
    "blocked": "known_issues",   # 被拦下了 → 已知问题
    "hook": "lessons_learned",   # hook 拦截 → 经验教训
    "ask": "lessons_learned",    # 需要人决策 → 经验教训
}

# 指纹窗口: 取 message 前 N 字符参与去重。异常信息尾部常带具体数值/时间戳,
# 取前段才能把"同一类问题"归并, 而尾部全量比对会把每次都算成新问题。
FINGERPRINT_CHARS = 120                             # 前段即可代表问题类别, 尾部是每次都变的现场

# 数字归一化: 指纹计算前把所有数字串换成 '#', 让"同模板不同数值"的错误
# 并成一类。真实场景里 ``/sqlid/12345?page=3`` 与 ``/sqlid/99999?page=1``
# 是同一个问题, 不做归一化的话重试/分页会刷出一堆几乎一样的候选条目,
# 把 inbox 淹掉 — 这正是"自动化沉淀"最容易失控的地方。
_DIGITS_RE = re.compile(r"\d+")                      # 只替数字: URL 骨架仍参与同类判定

# 已知噪声模式: 命中则丢弃, 不进 inbox (避免把测试造的假错误当真知识)
NOISE_PATTERNS: tuple[str, ...] = (                 # 正则而非子串: evil.com 要挡 example.com 的近邻
    r"evil\.com",            # 安全校验的负向用例 (单测构造)
    r"localhost",
    r"example\.(com|org)",
)


def _parse_since(raw: Optional[str]) -> Optional[float]:
    """把 ``--since`` 参数解析为起始 Unix 时间戳。

    支持两种写法: ``7d`` (天数) 或 ISO 日期 ``2026-09-01``。
    为 None 时返回 None (表示不限时间窗, 扫全量)。
    """
    if not raw:                                                                  # 空文件直接返回 None: 免得 _parse_since 在空串上做浮点转换
        return None
    text = raw.strip().lower()                       # 统一小写: 容忍 "7D" 这种写法
    if text.endswith("d") and text[:-1].replace(".", "", 1).isdigit():
        days = float(text[:-1])                                                               # "7d" 这类相对写法: 去掉单位后按天换算成时间戳
        return time.time() - days * 86400.0          # 相对当下滚动: 每跑一次窗口都更新
    try:
        # ISO 日期按 UTC 解析, 与 task_log 的 ts (Unix 秒) 同基准
        dt = datetime.strptime(text[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except ValueError:
        # 解析不了就显式失败: 静默忽略 --since 会让人以为窗口筛过了
        raise SystemExit(f"无法解析 --since: {raw!r} (支持 '7d' 或 '2026-09-01')") from None


def _iter_records(log_path: Path) -> Iterable[dict[str, Any]]:
    """逐行读取 JSONL 日志, 产出事件字典 (坏行跳过而非中断)。

    日志可能含半写残卷 (进程被杀) 或非 JSON 行; 一条坏行不应让整次归集失败,
    故跳过并计数, 由调用方决定是否告警。
    """
    if not log_path.is_file():                                                               # 日志不存在即抛: 沉底没有输入就不该报"扫了 0 条"
        return                                       # 缺文件给空产出, 报不报由 main 决定
    with log_path.open("r", encoding="utf-8") as handle:  # 逐行读: JSONL 日志可能很大
        for line in handle:                                                                         # 逐行读
            line = line.strip()                                                                     # 去空白
            if not line:                                                                            # 空行跳过
                continue
            try:
                rec = json.loads(line)                                                              # 逐行 JSON 解码
            except json.JSONDecodeError:
                continue                             # 半写残卷只丢这一行, 不中断整轮归集
            if isinstance(rec, dict):                                                               # 只收字典形态的记录
                yield rec                           # 非 dict 事件 (裸列表/标量) 不归集


def _fingerprint(rec: dict[str, Any]) -> str:
    """计算事件指纹 (同类问题归并用)。

    指纹 = event + 归一化后的 message 前 FINGERPRINT_CHARS 字符, 取 SHA-256 前 12 位。
    两道归并: (1) 数字串 → '#', 让同模板不同数值的错误并成一类;
    (2) 只取前段, 让尾部时间戳/路径差异不影响同类判定。
    否则重试 3 次就会产出 3 条几乎一样的候选, 稀释 inbox 的信噪比。
    """
    event = str(rec.get("event", ""))
    normalized = _DIGITS_RE.sub("#", str(rec.get("message", "")))  # 先换数字: 同模板不同数值算同一类
    message = normalized[:FINGERPRINT_CHARS]       # 再截前段: 尾部时间戳与路径差异不该影响归并
    raw = f"{event}|{message}"                      # event 入指纹: 同一句话挂在不同事件下不算重复
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]  # 取前 12 位防撞, 也不至于让条目名过长


def _is_noise(message: str) -> bool:
    """判断是否测试噪声 (单测构造的假错误不该沉成知识)。"""
    return any(re.search(p, message) for p in NOISE_PATTERNS)  # 任一命中即算噪声: 宁可漏收也不污染 inbox


def _slot_hint_actionable(key: str) -> bool:
    """这个建议槽位当前**真能命中**吗? 命不中就不给建议 (A8-03)。

    旧实现对 6 个星表名一律返回 ``catalog/<name>``、对网络/校验和类错误返回
    ``error_kind/*``, 而 ``static/fragments/`` 下只有 algo_mode / data_source /
    target_type 三个目录 —— 没有 catalog/, 也没有 error_kind/。实测
    ``resolve_slots({"catalog": "ps1"})`` 与 ``resolve_slots({"error_kind":
    "network_exhausted"})`` 都返回 ``[]``: 管道持续产出指向空槽位的建议, 审批者
    会以为"挂上钩就能取到知识", 实际永远取不到。

    为什么不等升格器: 仓内**没有**把候选升格成 fragment 的环节 ——
    ``write_inbox`` 只写 ``.knowledge/inbox/``, 而人工审的那一端是
    ``rag/knowledge/`` (B 路), 不是槽位目录。所以这个洞不会自愈, 只会持续误导,
    处置取 (b): 停止产出无效建议, 而不是凭空补一个没人调用的升格器。

    但这不是永久删除这两个维度: 判据是"**当前**能否命中", 哪天有人真建了
    ``static/fragments/catalog/ps1.yaml``, 同一份代码立即把建议放回来 —— 判据跟着
    盘面走, 不跟着注释走。
    """
    if str(SKILL_ROOT) not in sys.path:                   # 仓根先入路径: 本件既可被 CLI 按路径装载, 也可直跑
        sys.path.insert(0, str(SKILL_ROOT))
    try:
        from src.knowledge_slots import resolve_slots  # 延迟导入: 与 astro_best_cli 的 slots 子命令同口径
    except ImportError:                                   # 槽位层不可用 → 不给建议 (建议是可选字段, 缺它不该让整轮归集失败)
        return False
    dimension, _, value = key.partition("/")             # 槽位键形态 维度/值
    if not dimension or not value:                       # 形态不对就不猜: 交给下游安全校验也没有意义
        return False
    return bool(resolve_slots({dimension: value}))       # 交给 A 路自己判命中: 别在这里另写一套查表逻辑


def _guess_slot_hint(rec: dict[str, Any]) -> str:
    """从事件内容猜一个建议槽位 (A 路用), 猜不出或命中不了返回空串。

    只做保守的字面匹配: 消息里出现已知星表名/错误类别才给建议,
    绝不硬猜。给建议前还要过一道**可命中**校验 (见 _slot_hint_actionable):
    指向当前不存在的槽位, 与不给建议相比只有坏处 —— 它会让审批者以为这条经验已经
    挂上钩可以取用。
    """
    message = str(rec.get("message", "")).lower()  # 全小写匹配: 日志里的星表名大小写并不统一
    data = rec.get("data") or {}                    # data 可能是 None/缺失, 归一成 dict 再用
    catalog = str(data.get("catalog", "")).lower() if isinstance(data, dict) else ""  # 结构不对就不猜
    candidates: list[str] = []
    for name in ("ps1", "stripe82", "gaia_dr3_18", "jplus_dr3", "smss_dr4", "landolt"):
        if name in message or name == catalog:      # 消息命中或 data.catalog 显式声明都算
            candidates.append(f"catalog/{name}")
    if "network" in message or "5xx" in message or "timeout" in message:
        candidates.append("error_kind/network_exhausted")   # 网络类只归一种, 不按站点细分
    if "checksum" in message or "sha" in message:
        candidates.append("error_kind/checksum_mismatch")   # 校验和类同理
    for key in candidates:                          # 取第一个当前真能命中的建议
        if _slot_hint_actionable(key):
            return key
    return ""                                       # 猜不出 (或猜出的槽位不存在) 就空着: 硬猜会把脏槽位带进 A 路


def build_candidates(
    log_path: Path,                                                                                 # 入参: 日志路径是唯一必需项
    since: Optional[float] = None,                                                                  # 时间窗可空: 不给就是全量
    limit: int = 50,                                                                                # 产出上限: 防止一次灌出几千条候选
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """扫描日志, 产出候选条目 (去重、过滤噪声后)。

    Args:
        log_path: JSONL 事件日志路径
        since: 起始时间戳 (None = 不限)
        limit: 最多产出多少条候选

    Returns:
        (候选条目列表, 统计字典)。统计含 scanned/captured/duplicated/noise,
        便于运维判断"这条管道有没有真的在工作"。
    """
    stats = {"scanned": 0, "captured": 0, "duplicated": 0, "noise": 0}
    seen: set[str] = set()                         # 内存态去重集合, 只在本次运行内有效
    candidates: list[dict[str, Any]] = []          # 顺序即日志顺序, 便于人工按时间线审阅

    for rec in _iter_records(log_path):             # 单趟扫描: 不把整份日志预先读进内存
        stats["scanned"] += 1                       # 先计总数: 远大于产出量说明白名单收得太狠
        event = str(rec.get("event", ""))
        if event not in CAPTURE_EVENTS:                                                             # 不在采集事件白名单内的直接跳过
            continue                                # 白名单外不产知识: 成功路径没有沉淀价值
        ts = float(rec.get("ts", 0) or 0)           # ts 缺失记 0: 早于任何起点, 等于被时间窗排除
        if since is not None and ts < since:                                                        # 早于时间窗的跳过
            continue                                # since 为 None 时不限窗, 扫全量
        message = str(rec.get("message", "")).strip()
        if not message:                                                                             # 空消息没有知识价值
            continue
        if _is_noise(message):                                                                      # 噪声行提前滤掉
            stats["noise"] += 1                     # 噪声单独计数: 数量异常说明日志源变了
            continue
        fp = _fingerprint(rec)                                                                      # 算指纹
        if fp in seen:                                                                             # 已见过就跳过: 同一条知识反复出现只收一次
            stats["duplicated"] += 1                # 重复单独计数: 重试风暴会在这里显形
            continue
        seen.add(fp)                                                                                # 指纹入库

        # 时间戳转 ISO: 机器时间 (Unix 秒) 落成人类可读, 便于审批者判断时效
        iso = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        candidates.append({                                                                         # 收成候选
            "id": f"C-{fp}",
            "candidate_type": EVENT_TO_TYPE.get(event, "lessons_learned"),  # 默认归类, 审批者可改
            "title": message[:80],
            "body": message,
            "evidence": {
                "log_file": str(log_path.relative_to(SKILL_ROOT)) if _rel(log_path) else str(log_path),
                "task_id": rec.get("task_id", ""),
                "event": event,
                "ts_utc": iso,
            },
            "tags": [event, "auto-captured"],
            "slot_hint": _guess_slot_hint(rec),
            "status": "pending",                    # 固定 pending: 升格必须由人改成 approved
        })
        stats["captured"] += 1
        if len(candidates) >= limit:                                                                # 达到上限就停: 后面的日志再扫也是超量
            break                                    # 到上限就停: 一次跑批不该灌爆 inbox

    return candidates, stats


def _rel(path: Path) -> bool:
    """路径是否在 skill 根内 (决定能否显示相对路径)。"""
    try:
        return path.resolve().is_relative_to(SKILL_ROOT.resolve())  # 先 resolve: 混用相对/绝对会判不出包含关系
    except OSError:
        return False                                # 断链/无权限一律当作"不在根内", 退回绝对路径


def write_inbox(candidates: list[dict[str, Any]], inbox_dir: Path) -> list[Path]:
    """把候选条目原子写入 inbox (一条一文件, 便于逐条审批与 git diff)。

    原子落盘: 先写 .tmp 再 os.replace, 杜绝半写残卷被后续流程读到。
    文件名含指纹, 重复归集同一事件会覆盖同名文件 (幂等)。
    """
    inbox_dir.mkdir(parents=True, exist_ok=True)   # exist_ok: 重复运行不报错, 幂等的前提之一
    written: list[Path] = []                                                                        # 写入结果列表
    for item in candidates:                                                                         # 逐条写
        target = inbox_dir / f"{item['id']}.yaml"  # 文件名带指纹: 同一事件重复归集会覆盖同名文件
        tmp = target.with_suffix(target.suffix + ".tmp")  # 先写 .tmp: 杜绝半写残卷被审批流程读到
        payload = {"candidates": [item]}            # 一条一文件, 便于逐条审批与 git diff
        tmp.write_text(                                                                             # 先写临时文件
            yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),  # 保留插入顺序, 审批时按字段读
            encoding="utf-8",
        )
        import os

        os.replace(tmp, target)                     # 原子替换: 读者要么看到旧的, 要么看到新的
        written.append(target)                                                                      # 入表
    return written


def main(argv: Optional[list[str]] = None) -> int:
    """CLI 入口。"""
    parser = argparse.ArgumentParser(                                                               # 命令行解析器
        prog="knowledge_capture",
        description="运行时事件 → 候选知识条目 (知识沉底管道第一棒)",
    )
    parser.add_argument("--log", default=str(DEFAULT_LOG), help="事件日志路径 (JSONL)")  # 覆盖默认锚点, 便于试跑不碰真日志
    parser.add_argument("--inbox", default=str(DEFAULT_INBOX), help="候选条目输出目录")
    parser.add_argument("--since", default=None, help="只扫最近多久: '7d' 或 '2026-09-01'")
    parser.add_argument("--limit", type=int, default=50, help="最多产出多少条候选")
    parser.add_argument("--dry-run", action="store_true", help="只打印, 不落盘")
    args = parser.parse_args(argv)                                                                  # 取实参

    log_path = Path(args.log)                                                                       # 日志路径
    if not log_path.is_file():                                                                      # 不存在即非零
        print(f"[capture] 日志文件不存在: {log_path}", file=sys.stderr)
        return 1                                    # 缺源直接非零: 空跑批会把"管道坏了"说成"没抓到"

    since = _parse_since(args.since)                # 时间窗解析失败在此抛 SystemExit, 不进归集
    candidates, stats = build_candidates(log_path, since, args.limit)                               # 扫一遍出候选与统计

    print(f"[capture] 扫描 {stats['scanned']} 条事件 → "
          f"候选 {stats['captured']} 条 (去重 {stats['duplicated']}, 噪声 {stats['noise']})")
    for item in candidates:                                                                         # 逐条打印候选
        hint = item["slot_hint"] or "-"
        print(f"  [{item['id']}] {item['candidate_type']:15s} slot={hint:28s} {item['title'][:50]}")

    if args.dry_run:                                                                                # dry-run 在写盘前短路
        print("[capture] dry-run: 未落盘")
        return 0                                    # 必须在写盘之前返回, 这是 dry-run 的唯一保证

    written = write_inbox(candidates, Path(args.inbox))                                             # 真写盘
    print(f"[capture] 已写入 {len(written)} 个候选文件 → {args.inbox}")
    print("[capture] 下一步: 人工审阅后改 status=approved, 再升格进 rag/knowledge/")
    return 0                                        # 落盘成功即 0, 审批失败是人的流程不是脚本的


if __name__ == "__main__":
    raise SystemExit(main())                        # 退出码透传: main 的 1 会让调用方立刻停
