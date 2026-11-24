# -*- coding: utf-8 -*-
"""evals.ablation.iso.stage — 逐格提示词的**隔离投放** (答案键隔离 + 批次唯一 + 写者标记)。

本模块是 G1/G2/G3 三项门禁的**执行者**, 取代原先只活在 ``temp/`` (gitignored) 里的
``stage_scratch.py``。三件事分别对应三条判据:

  ① **答案键隔离**: scratch 落点由 ``paths.scratch_root()`` 给出 (默认在仓库之外),
     投放后**逐文件扫禁词**, 命中即 ``rmtree`` 撤销投放 —— 不许"大致干净就往下跑"。
  ② **批次唯一**: 建批用 ``mkdir(exist_ok=False)`` —— **目录创建是原子的**, 第二个
     并发投放必然抢不到, 不存在"先检查再创建"的 TOCTOU 窗口。
  ③ **写者标记**: 建批成功即原子写 ``.owner.json`` (``O_EXCL``), 记录 pid/时间/投放格数;
     后验审计据此判"这批有没有主人", 而"两个代理写同一批"会表现为写者标记与
     输出时间戳对不上 (由 ``audit.check_single_writer`` 抓)。

**为什么 --force 也要留痕**: 它会 ``rmtree`` 掉整个批次目录。若此时还有代理在里面跑,
这就是一次主动的并发破坏 —— 所以强制覆盖必须显式给出, 且被写进新一批的写者标记里。

对外接口: ``stage_batch()`` / ``acquire_batch_dir()`` / ``read_owner()`` / ``main()``。
"""
from __future__ import annotations

# 标准库: 写者标记的序列化 (固定字段, 不引第三方)
import json

# 标准库: 进程号 (写者标记) 与时间戳
import os

# 标准库: 原子创建与排他打开 (O_EXCL 是并发保护的执行者)
import pathlib

# 标准库: 递归删除 (fail-closed 撤销投放 / --force 覆盖)
import shutil

# 标准库: CLI 入口的 argv
import sys

# 标准库: 时间源 (写者标记的落笔时刻)
import time

# 标准库: 一次性写者令牌 (pid 会被操作系统复用, uuid 不会)
import uuid

from evals.ablation.iso.paths import (  # 根目录 SSOT: 与审计器共用同一份解析, 不另拼路径
    assert_outside_repo,  # 结构性判据: 够得着仓就拒绝投放
    batch_dir,  # 批次目录解析: 投放与审计同一口径
    prompt_root,  # 逐格提示词源: 默认 temp/decision_iso, 可环境变量覆盖
)

# 答案键物料的指纹: scratch 里出现任一即判红 (与审计器共用, 见 FORBIDDEN 的注释)
FORBIDDEN: tuple[str, ...] = (
    "expect_tools", "should_call_best", "reason_code", "must_not_call",
    "anti_patterns", "gold_result", "data_anchor", "assertions",
    "items.yaml", "hypotheses.yaml", "evals/ablation",
)

OWNER_FILE = ".owner.json"                                                # 写者标记: 原子创建, 后验审计据此判主人
PROMPTS_DIR = "prompts"                                                   # 提示词子目录: 只读输入
OUT_DIR = "out"                                                           # 输出子目录: 代理唯一可写处
MANIFEST_FILE = "MANIFEST.txt"                                            # 批次清单: 代理据此知道自己负责哪些格
CELLS_FILE = ".cells.json"                                                # 分配格清单: 写了清单外的格即越界 (审计判据)
WRITING_FILE = ".writing"                                                 # 写会话标记: 会话开着 = 有人正在写, 不许再开一个
FINISHED_FILE = ".finished.json"                                          # 收尾快照: 会话关闭时的输出指纹, 事后比对用

_QUERY_LIMITED_INFORMATION = 0x1000                                       # Windows 进程查询权限位: 判 pid 活不活要它


class BatchBusy(RuntimeError):
    """批次已被占用 (同名已存在或有活跃写者) —— 复用批次名是 D-18 的直接成因。"""


class AnswerKeyLeak(RuntimeError):
    """投放内容里出现答案键物料 —— fail-closed, 该批作废。"""


class WriteSessionBusy(RuntimeError):
    """该批次已有一个打开的写会话 —— D-18 的真实形态 (同批派第二个代理) 在此被挡。"""


def pid_alive(pid: int) -> bool:
    """判一个进程号是否还活着 (跨平台; 失败一律按**活着**处理, 铁律 5 禁 fail-open)。

    Args:
        pid: 进程号。

    Returns:
        True 表示活着**或判不出来** —— 判不出来时按活的处理, 这样"不敢覆盖"而非"误以为死了"。
    """
    if pid <= 0:                                                          # 非法的进程号: 直接当活, 不冒险覆盖
        return True
    if os.name == "nt":                                                   # Windows: 标准库没有 POSIX 的 kill(pid, 0)
        try:
            import ctypes  # 只此一处需要: 顶层挂它会拖慢纯 Linux 环境

            handle = ctypes.windll.kernel32.OpenProcess(_QUERY_LIMITED_INFORMATION, False, pid)
            if handle:                                                    # 拿到句柄 = 进程还在
                ctypes.windll.kernel32.CloseHandle(handle)
                return True
            return False                                                  # 拿不到 = 已退出
        except Exception:                                                 # 判不出来: 按活的处理, 不做"死了就覆盖"的假设
            return True
    try:
        os.kill(pid, 0)                                                   # POSIX: 信号 0 只做存在性探测
    except ProcessLookupError:                                            # 明确"不存在"才敢判死
        return False
    except PermissionError:                                               # 存在但无权: 它活着
        return True
    except OSError:                                                       # 其余一律按活处理
        return True
    return True


def _write_owner(dst: pathlib.Path, batch: str, n_cells: int, token: str) -> pathlib.Path:
    """原子写写者标记 (``O_EXCL``: 抢不到说明这批已经有主人)。

    **为什么要有 token**: pid 会**被复用** —— 上一批的 pid 死后, 操作系统可能把同一个号
    给一个新进程。只比 pid 会把"旧批的主人"误认成"当前还活着"。token 是一次性随机串,
    只有真正持有它的那个会话才能开写。

    Args:
        dst: 批次目录 (已由 ``acquire_batch_dir`` 原子创建)。
        batch: 批次名。
        n_cells: 本批投放的格数 (后验审计要核对"投了多少、写了多少")。
        token: 本次投放的一次性写者令牌。

    Returns:
        写者标记的路径。
    """
    payload = json.dumps({"batch": batch, "pid": os.getpid(), "token": token,
                          "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                          "n_cells": n_cells}, ensure_ascii=False, indent=2)
    path = dst / OWNER_FILE
    fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)         # O_EXCL: 已存在即抛, 无覆盖窗口
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(payload)                                             # 一次性写完: 不留半截文件给下游读
    return path


def _write_json(path: pathlib.Path, payload: dict, *, exclusive: bool) -> None:
    """原子写一个 JSON 小文件 (要么整份在、要么不在)。

    Args:
        path: 目标路径。
        payload: 待写内容。
        exclusive: True 时用 ``O_EXCL`` —— 已存在即抛, 用于一切"标记"类文件的抢占。
    """
    flags = os.O_CREAT | os.O_WRONLY | (os.O_EXCL if exclusive else os.O_TRUNC)  # O_TRUNC 只在非抢占时用
    fd = os.open(str(path), flags)                                        # 打开即决定成败: 抢占失败在这里抛
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, indent=2))    # 一次写完: 不留半截给下游解析


def read_owner(batch: str) -> dict | None:
    """读某批次的写者标记。

    Args:
        batch: 批次名。

    Returns:
        写者标记 dict; 批次不存在或无标记时返回 ``None`` (后验审计据此判"无主")。
    """
    path = batch_dir(batch) / OWNER_FILE                                  # 路径解析走 SSOT: 不在此处另拼
    if not path.is_file():
        return None                                                       # 无主 = 后验审计要判红的一条 (见 audit)
    return dict(json.loads(path.read_text(encoding="utf-8")))             # 字段固定: 不做缺省填充, 缺即如实缺


def acquire_batch_dir(batch: str, *, force: bool = False) -> pathlib.Path:
    """原子地占住一个批次目录 (批次唯一 + 并发保护的执行者)。

    Args:
        batch: 批次名。**不得复用** —— 复用即 D-18 (两个代理并发写同一批)。
        force: 显式允许覆盖同名旧批次 (会 ``rmtree``, 属主动破坏, 须人下决定)。

    Returns:
        已占住的批次目录路径。

    Raises:
        BatchBusy: 同名批次已存在而 ``force`` 为假; 或并发投放抢不到目录。
        ValueError: 落点在仓库内或祖先层有答案键 (D-17 的结构性判据)。
    """
    dst = batch_dir(batch)                                                # 单一路径解析: 与审计器同源
    assert_outside_repo(dst)                                              # 结构性判据先行: 位置不对就不谈别的
    if force and dst.exists():                                            # 强制覆盖: 先看有没有人正在写
        if (dst / WRITING_FILE).exists():                                 # 会话开着 = 有代理在里面写, rmtree 就是 D-18
            raise BatchBusy(f"批次 {batch} 有一个打开的写会话 —— 不得在采集进行中覆盖它 "
                            "(先 --end-write, 或等采集结束)")
        shutil.rmtree(dst)
    try:
        dst.mkdir(parents=True, exist_ok=False)                           # 原子建批: 目录创建只有一个赢家
    except FileExistsError as exc:                                        # 抢不到 = 同名已存在 (D-18 的直接防护)
        raise BatchBusy(f"批次 {batch} 已存在: {dst} —— 批次名不得复用 (D-18: "
                        "并发写会互相覆盖); 请换新批次名, 或显式 force=True 覆盖") from exc
    return dst


def stage_batch(batch: str, systems: list[str], *, only: list[str] | None = None,
                force: bool = False, source: pathlib.Path | None = None) -> pathlib.Path:
    """投放一个批次: 只装该批自己要跑的格, 并做 fail-closed 禁词自检。

    Args:
        batch: 批次名 (不得复用)。
        systems: 装配标签列表 (如 ``["B3"]``)。
        only: 只投放这些题号 —— **这是结构隔离的关键**: 若目录里放着全部 56 格,
            被分配 5 格的代理会**列目录**看到其余题号并推断出族标签; 那是口头禁令挡不住的。
        force: 允许覆盖同名旧批次。
        source: 提示词源目录; 缺省走 ``paths.prompt_root()``。

    Returns:
        投放完成的批次目录路径。

    Raises:
        BatchBusy: 批次名被占用。
        AnswerKeyLeak: 投放内容含答案键物料 (已撤销投放)。
        FileNotFoundError: 该装配没有现导好的提示词。
    """
    dst = acquire_batch_dir(batch, force=force)                           # 先占位: 隔离未成立就不拷贝任何内容
    src_root = source if source is not None else prompt_root()            # 源目录可注入: 单测用夹具, 不碰真实产物
    n_cells = 0
    for tag in systems:                                                   # 逐装配拷贝: 一次投放可含多个装配
        src = src_root / tag
        if not src.is_dir():                                              # 缺源即抛: 静默少拷会让"跑了却没题"看不出来
            raise FileNotFoundError(f"没有该装配的提示词: {src}")
        (dst / PROMPTS_DIR / tag).mkdir(parents=True, exist_ok=True)      # 提示词目录: 只读输入
        (dst / OUT_DIR / tag).mkdir(parents=True, exist_ok=True)          # 输出目录: 代理唯一可写处
        for item_file in sorted(src.glob("*.txt")):                       # 逐格拷贝: 排序保证清单可复现
            if only is not None and item_file.stem not in only:           # 只装分配的格: 目录里看不到别的题
                continue
            shutil.copy2(item_file, dst / PROMPTS_DIR / tag / item_file.name)
            n_cells += 1
    cells = sorted(p.stem for p in (dst / PROMPTS_DIR / systems[0]).glob("*.txt"))
    (dst / MANIFEST_FILE).write_text(                                     # 清单: 代理据此知道自己的工作边界
        f"批次: {batch}\n装配: {', '.join(systems)}\n格数/装配: {len(cells)}\n"
        f"题号: {', '.join(cells)}\n\n"
        f"你的工作目录就是本目录。提示词在 {PROMPTS_DIR}/<装配>/<题号>.txt;\n"
        f"输出写到 {OUT_DIR}/<装配>/<题号>.json。本目录之外的文件与本任务无关。\n",
        encoding="utf-8")
    token = uuid.uuid4().hex                                              # 一次性写者令牌: pid 会被复用, token 不会
    assigned: list[str] = []                                              # 分配格清单: 审计据此判"有没有写清单外的格"
    for tag in systems:                                                   # 逐装配登记: 多装配批次也要逐格可核对
        for item_file in sorted((dst / PROMPTS_DIR / tag).glob("*.txt")):  # 以实际拷贝为准, 不用入参回放
            assigned.append(f"{tag}/{item_file.stem}")
    _write_json(dst / CELLS_FILE, {"cells": assigned}, exclusive=True)     # 抢占写: 目录是新建的, 不该已存在
    _write_owner(dst, batch, n_cells, token)                              # 写者标记: 后验审计据此判主人
    hits: list[str] = []                                                  # 禁词命中: 非空即撤销整批
    for path in dst.rglob("*"):                                           # 全量扫: prompts 与 MANIFEST 都在扫描面内
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")          # 容错读: 扫的是有没有物料, 不是编码合规
        for key in FORBIDDEN:
            if key in text:
                hits.append(f"{path.relative_to(dst)} 含禁词 {key!r}")
    if hits:                                                              # fail-closed: 隔离没做到就不许往下跑
        shutil.rmtree(dst)                                                # 撤销投放: 不留半截批次给代理去读
        raise AnswerKeyLeak(f"scratch 含答案键物料: {len(hits)} 处 (如 {hits[0]}) —— 已撤销投放")
    return dst


def _snapshot_outputs(batch: str) -> dict:
    """给批次的输出拍一张指纹 (文件名 → mtime), 供收尾后比对"有没有被追加写"。

    Args:
        batch: 批次名。

    Returns:
        ``{"n": 文件数, "files": {相对路径: mtime}}``。
    """
    root = batch_dir(batch) / OUT_DIR                                     # 只拍输出: 提示词是投放时的一次性产物
    files = {str(p.relative_to(root)): round(p.stat().st_mtime, 3)         # 相对路径: 换机复跑也能对上
             for p in sorted(root.rglob("*.json"))}
    return {"n": len(files), "files": files}


def begin_write(batch: str, *, token: str | None = None, force: bool = False) -> dict:
    """开一个写会话 —— **D-18 真实形态的拦截点**。

    D-18 不是"两个投放器抢同名批次", 而是"批次**已投放**之后, 我又往**同一个** scratch
    派了第二个代理"。批次名自始至终唯一, 所以批次唯一性挡不住它 —— 能挡的是:
    **同一时刻只允许一个打开的写会话**, 且只有显式 `end_write` 才能把它关掉。

    **为什么不按 pid 存活判断 (实测否决, 2026-10-11)**: 开会话的进程常常**立刻退出**
    (CLI 调完就结束), 而真正的写者是那个被派出去的代理, 它不在本进程树里。实测就是这个
    形状 —— 第一次 `begin_write` 的进程退出后 pid 被判死, 第二次 `begin_write` **照样成功**,
    门禁形同虚设。所以判据只能是"标记在不在": 在, 就是有人没关会话; 要清必须由人显式
    给 `force=True`, 并把被清掉的旧会话**记进新标记**留痕 —— 不靠猜。

    Args:
        batch: 批次名。
        token: 写者令牌; 给了就与写者标记比对 (不给则信任本机同一会话)。
        force: 显式清掉一个**未关闭**的旧会话 (人为决定, 会留痕)。

    Returns:
        写会话标记内容 (含 pid / token / started_at / forced / forced_from)。

    Raises:
        BatchBusy: 无写者标记, 或令牌不匹配。
        WriteSessionBusy: 已有一个未关闭的写会话 —— 第二个写者在此被挡。
    """
    owner = read_owner(batch)                                             # 无主即拒: 未投放的批次不许开写
    if owner is None:
        raise BatchBusy(f"批次 {batch} 没有写者标记 —— 未经投放的批次不许开写")
    if token is not None and token != owner.get("token"):                 # 令牌不匹配: 不是这批的主人
        raise BatchBusy("写者令牌不匹配: 该批属于另一个投放会话")
    dst = batch_dir(batch)                                                # 路径走 SSOT: 与投放/审计同一口径
    marker = dst / WRITING_FILE                                           # 会话标记: 存在即"有人正在写"
    forced_from: dict | None = None                                       # 被强制清掉的旧会话: 必须留痕
    if marker.exists():                                                   # 已存在: 默认一律挡回, 不猜它死没死
        if not force:                                                     # 未显式授权 -> 第二个写者在此被挡
            try:
                previous = json.loads(marker.read_text(encoding="utf-8"))  # 取旧会话只为把报错说具体
            except (json.JSONDecodeError, OSError):
                previous = {}                                             # 半截也照样挡: 判不出来不许放行
            alive = pid_alive(int(previous.get("pid", 0)))                # 仅作**诊断**, 不作放行依据
            raise WriteSessionBusy(f"批次 {batch} 已有一个未关闭的写会话 (pid={previous.get('pid')}, "
                                   f"该 pid 当前{'仍活着' if alive else '已退出'}) —— 同一时刻只许一个写者, "
                                   "这正是 D-18 的形状; 确认旧会话确已结束再显式 force=True")
        try:
            forced_from = json.loads(marker.read_text(encoding="utf-8"))  # 留痕: 被清掉的是哪一个会话
        except (json.JSONDecodeError, OSError):
            forced_from = {"unparsable": True}                            # 解析不出也要记一笔, 不许静默
        marker.unlink()                                                   # 显式授权后才清: 不靠存活猜测
    payload = {"batch": batch, "pid": os.getpid(), "token": owner.get("token"),
               "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
               "forced": bool(forced_from), "forced_from": forced_from}    # 强制清场要留痕: 事后可追责
    try:
        _write_json(marker, payload, exclusive=True)                      # O_EXCL: 并发抢会话也只有一个赢家
    except FileExistsError as exc:                                        # 抢不到 = 有别人刚开了会话
        raise WriteSessionBusy(f"批次 {batch} 的写会话被另一个进程抢先打开") from exc
    return payload


def end_write(batch: str) -> dict:
    """关掉写会话并**拍下收尾指纹** (事后被追加写就能查出来)。

    Args:
        batch: 批次名。

    Returns:
        收尾快照 ``{"n", "files", "closed_at"}``。
    """
    snapshot = _snapshot_outputs(batch)                                   # 先拍快照: 收尾后再写的文件会与之对不上
    snapshot["closed_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")          # 收尾时刻: 与 started_at 配对看时长
    _write_json(batch_dir(batch) / FINISHED_FILE, snapshot, exclusive=False)  # 覆盖写: 允许重复收尾
    marker = batch_dir(batch) / WRITING_FILE                              # 会话标记: 关会话即删
    if marker.exists():                                                   # 幂等: 重复收尾不该抛
        marker.unlink()
    return snapshot


def main(argv: list[str]) -> int:
    """CLI: 投放 / 开写会话 / 关写会话 三条子命令。

    用法::

        stage.py <批次名> <装配> [装配...] [--only D01,D02] [--force]   # 投放
        stage.py --begin-write <批次名>                                 # 开写会话 (已有会话即拒)
        stage.py --end-write <批次名>                                   # 关写会话 + 拍收尾指纹

    Returns:
        0 成功; 2 用法错; 3 批次被占用/无主/令牌不符 (D-18 门禁);
        4 禁词命中 (已撤销投放); 5 写会话已被占用 (同批第二个写者)。
    """
    if "--begin-write" in argv:                                           # 开写会话: 派代理前必须调一次
        batch = argv[argv.index("--begin-write") + 1]
        try:
            marker = begin_write(batch, force="--force-begin" in argv)     # 抢不到即抛: 第二个写者在此被挡
        except (BatchBusy, WriteSessionBusy) as exc:
            print(f"✗ {exc}")
            return 3 if isinstance(exc, BatchBusy) else 5
        print(f"✓ 写会话已开: {marker}")
        return 0
    if "--end-write" in argv:                                             # 关写会话: 采完必须调, 否则审计判红
        batch = argv[argv.index("--end-write") + 1]
        snapshot = end_write(batch)                                       # 拍快照: 事后追加写就能查出来
        print(f"✓ 写会话已关: 输出 {snapshot['n']} 个, 指纹已落")
        return 0
    if len(argv) < 3:                                                     # 用法: 至少一个批次名与一个装配
        print("用法: python -m evals.ablation.iso.stage <批次名> <装配> [装配...] "
              "[--only D01,D02] [--force]")
        return 2
    args = argv[1:]
    force = "--force" in args                                             # 强制覆盖: 显式给出才生效
    args = [a for a in args if a != "--force"]
    only: list[str] | None = None
    if "--only" in args:                                                  # 只投指定题号: 结构隔离的关键开关
        index = args.index("--only")
        only = [x.strip() for x in args[index + 1].split(",") if x.strip()]
        args = args[:index]
    batch, systems = args[0], args[1:]
    try:
        dst = stage_batch(batch, systems, only=only, force=force)         # 投放: 三项门禁都在这条调用里
    except BatchBusy as exc:                                              # 批次唯一门禁: 复用名一律挡回
        print(f"✗ {exc}")
        return 3
    except AnswerKeyLeak as exc:                                          # 答案键隔离门禁: 命中即作废
        print(f"✗ {exc}")
        return 4
    print(f"✓ 投放批次 {batch}: {len(systems)} 装配 -> {dst}")
    print(f"  ✓ 写者标记已落: {read_owner(batch)}")
    print(f"  ✓ fail-closed 自检通过: {len(FORBIDDEN)} 个禁词一个未出现")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))                                      # 直接跑: 交回退出码给调用方判门禁
