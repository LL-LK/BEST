#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""astro_best_cli.py — astro-best 本地 CLI (Phase 3-D 十三组件, 组件 12B)。

子命令 (与 SKILL.md 场景路由 / manifest.yaml entry_points 对齐):
  doctor   导入真包 + 版本/门禁自检 (全离线)
  领域演示子命令 (见 --help)
  rag      本地知识混合检索 (rag/astro_rag.py)

安全约定 (Mimosa 门禁):
  - 凭据/令牌一律读环境变量, 代码内零凭据字面量;
  - 用户路径经 `src.scripts.guards.resolve_data_path()` 校验 (全仓权威单点, 本文件
    不得再持第二份实现), 相对路径锚定数据根 (env `ASTRO_BEST_DATA_ROOT`,
    默认 = skill 根), 结果必须 is_relative_to(数据根), 拒绝 .. 上溯逃逸;
  - 路径操作一律 pathlib; 原子落盘用 write_text + os.replace。

示例 (本文件真实路径在 ops/ 下, 不是 scripts/):
  python ops/astro_best_cli.py doctor
  python ops/astro_best_cli.py 领域演示子命令 (见  --help
  python ops/astro_best_cli.py rag "气团 计算" --top-k 3
"""

from __future__ import annotations

# 标准库组:
#   argparse   —— 子命令解析与接线 (doctor/rag/config/refs/oauth/log/download)
#   importlib  —— 延迟导入真包 src, 避免 CLI 启动即拖垮重依赖
#   json       —— 机器可读报告序列化 (ensure_ascii=False 保中文)
#   os         —— 只读环境变量 (凭据/数据根, 代码内零凭据字面量)
#   sys        —— sys.path 注入, 使 `import src` 在任意 cwd 下可达
#   pathlib    —— 全程路径锚定与原子落盘 (替代 os.path 字符串拼接)
import argparse
import importlib
import json
import os
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent                      # 锚点: 本文件在 ops/ 下, 上溯一级即 skill 根 —— 换机/换 cwd 都能定位
PKG_ROOT = SKILL_ROOT  # src/ 平铺后, 包 src 的父目录即 skill 根
# 把 skill 根注入 sys.path: 否则从仓库任意目录调用本 CLI 时 `import src` 必失败
if str(PKG_ROOT) not in sys.path:      # 先查后插: 重复注入会让同一模块出现两份类对象
    sys.path.insert(0, str(PKG_ROOT))  # 插首位: 本仓 src 优先于环境里的同名包
RAG_DIR = SKILL_ROOT / "rag"  # 路径常量; rag/ 不再注入 sys.path (防跨套件 astro_rag 互踩)

# 真包名 (src/ 平铺后的包根); 导入即校验, 失败由上层转非零退出
PKG = "src"                                                             # 真包名: src/ 已平铺, 下面 import_module(PKG) 成功与否就是包结构体检
# 数据根覆盖开关 (ASTRO_BEST_DATA_ROOT) 的权威定义与解析已收敛到全仓单点
# src.scripts.guards.data_root/resolve_data_path — CLI 不再持第二份实现
# (P1-7: 本文件不得再定义第二份数据根解析, 与单点漂移即路径安全双轨)。


def cmd_doctor(_args: argparse.Namespace) -> int:
    """导入真包 + 组件自检 (全离线, <1s, G8 本地算力铁律)。

    Returns:
        全部组件在位返回 0; 任一缺失返回 1 (供 make doctor / CI 消费)。
    """
    # 延迟导入: 导入动作本身就是最强校验 (包结构破坏会在这里抛异常)
    importlib.import_module(PKG)  # 导入即最强校验: 包结构破坏在这里就抛, 不必另写检查
    report = {"skill": "astro-best", "import_ok": True}                     # import_ok 先置真: 真正的校验在上一行的 import, 抛异常就不会走到这行
    checks = {  # 存在性探针表: 缺项即交付树被裁剪, 与内容对错无关
        # 以下均为"文件/目录存在性"探针: 缺一项即说明交付树被裁剪或漏打包
        "rag/astro_rag.py": (RAG_DIR / "astro_rag.py").is_file(),                               # RAG 执行体: 缺它 rag 子命令直接不可用
        "rag/knowledge": (RAG_DIR / "knowledge").is_dir(),                          # 知识目录: RAG 的唯一真源, 缺则检索恒空 (会被误读成"没查到")
        "references/ALGORITHM-SPEC.md": (SKILL_ROOT / "references" / "ALGORITHM-SPEC.md").is_file(),  # 算法规范: 引用层权威, 缺它则对外描述无出处
        "manifest.yaml": (SKILL_ROOT / "manifest.yaml").is_file(),                             # 清单: 能力声明的入口, 缺它等于没登记自己有什么
        "architecture.md": (SKILL_ROOT / "architecture.md").is_file(),              # 架构说明: 人读的组件地图, 与 references 里的算法规范分工
    }
    # E1–E6 实验设施探针 (入口文件缺失 = 实验树被裁)
    evals_dir = SKILL_ROOT / "evals"                                                    # 实验树锚点: E1–E6 探针都在它下面, 缺失即实验设施被裁剪
    checks["evals/_data/null_sentinel.yaml"] = (evals_dir / "_data" / "null_sentinel.yaml").is_file()  # 哨兵字典: 跨实验唯一共享数据件, 缺它 E2/E3/E4/E5 判定全部失准
    checks["evals/_data/tolerances.yaml"] = (evals_dir / "_data" / "tolerances.yaml").is_file()  # 容差表: 同上; 与哨兵字典分两个文件是按「值 / 误差」两类语义拆的
    checks["evals/nl2tool/runner.py"] = (evals_dir / "nl2tool" / "runner.py").is_file()       # E1 跑批入口: 缺它则 NL→工具决策实验无法执行
    checks["evals/groundtruth/run_e2.py"] = (evals_dir / "groundtruth" / "run_e2.py").is_file()   # E2 跑批入口: 缺它则金标准一致性无法执行
    checks["evals/semantics/runner.py"] = (evals_dir / "semantics" / "runner.py").is_file()      # E3 跑批入口: 缺它则语义与幻觉维度无法执行
    checks["evals/robustness/runner.py"] = (evals_dir / "robustness" / "runner.py").is_file()    # E4 跑批入口: 缺它则鲁棒与安全维度无法执行
    checks["evals/repro/run_e6.py"] = (evals_dir / "repro" / "run_e6.py").is_file()               # E6 跑批入口: 缺它则可复现性维度无法执行
    checks["evals/ablation/runner.py"] = (evals_dir / "ablation" / "runner.py").is_file()          # E5 跑批入口: 缺它则基线与消融无法执行
    checks["evals/equivalence/tests"] = (evals_dir / "equivalence" / "tests").is_dir()  # 等价性测试: 守护"同源功能多份实现"不漂移, 缺它则该防线无人守
    report["components"] = checks  # 布尔表进 payload: 谁缺席一眼可见, 不必翻 stdout 文本
    # 输出点:  stdout JSON (机器可读); 退出码承载门禁语义, 不进 payload
    print(json.dumps(report, ensure_ascii=False, indent=2))                    # 机器可读输出: make doctor / CI 只看退出码, 人看这份 JSON
    return 0 if all(checks.values()) else 1  # 全 True 才 0: 缺一项即非零, 门禁不许部分通过


def cmd_rag(args: argparse.Namespace) -> int:
    """本地 BM25+词桶+RRF 混合检索 (零网络)。

    Returns:
        正常检索返回 0; 知识目录缺失/损坏由被调方抛异常冒泡。
    """
    # 唯一模块名装载本地执行器, 杜绝多 skill 同进程运行时的 astro_rag 同名互踩
    _repo_root = SKILL_ROOT.parent  # 共享层在 skill 根之外, 故要上溯一级
    # 注入仓库根: 优先走共享层 _shared.rag_local_executor (统一多 skill RAG 装载语义)
    if str(_repo_root) not in sys.path:                                                          # 先查后插: 重复注入会让同一模块出现两份类对象
        sys.path.insert(0, str(_repo_root))                                                      # 插首位: 共享层要优先于环境里可能存在的同名包
    try:
        # 首选共享装载器: 以唯一模块名加载本 skill 的 rag/astro_rag.py
        from _shared.rag_local_executor import load_local_rag
        rag_mod = load_local_rag("best", RAG_DIR / "astro_rag.py")                 # 唯一模块名装载: 多 skill 同进程时 astro_rag 同名会互踩
    except (ImportError, ModuleNotFoundError):
        # 降级路径: 共享层不可达 (单 skill 独立分发) 时按文件路径直接装载
        import importlib.util
        spec = importlib.util.spec_from_file_location("astro_rag_best", RAG_DIR / "astro_rag.py")  # 降级路径的 spec: 共享层不可达时按文件路径直接装载
        if spec is None or spec.loader is None:                                            # spec 为空即文件不可定位: 抛错而不是降级成空检索结果
            raise RuntimeError(f"Cannot load RAG module from {RAG_DIR / 'astro_rag.py'}") from None
        rag_mod = importlib.util.module_from_spec(spec)                                  # 先建模块对象: exec_module 需要它作为命名空间容器
        sys.modules[spec.name] = rag_mod  # 登记进 sys.modules: 不登记则同一文件被执行成两份类
        # 执行模块: 这是本函数唯一的外部代码装载点 (读本地 .py 文件, 无网络)
        spec.loader.exec_module(rag_mod)                                                     # 唯一的外部代码装载点: 读本地 .py 文件, 零网络
    # 知识目录读点: 只读 rag/knowledge 下的 YAML, 不写不删
    rag = rag_mod.AstroRAG(RAG_DIR / "knowledge")  # 知识根固定在 rag/knowledge: 那是 A/B 两路的唯一真源
    loaded = rag.load()                                                                   # 装载即校验: 知识 YAML 损坏在这里就抛, 不拖到查询时
    hits = rag.search(args.query, top_k=args.top_k)  # RRF 混合打分在 rag 侧: CLI 不重排, 免两处口径打架
    if args.json:                                                                             # JSON 出口: 供脚本消费, 与下面的文本出口互斥
        print(json.dumps({"loaded": loaded, "hits": hits}, ensure_ascii=False, indent=2))  # ensure_ascii=False: 中文命中内容要可读, 转义后没法人工复核
    else:
        print(f"[rag] 条目 {loaded} 条 — 查询: {args.query}")                                # 人读出口: 查询串原样回显, 便于确认 BM25 收到的是哪句话
        for i, h in enumerate(hits, 1):  # 从 1 起编号: 与 CLI 其它列表输出的人读习惯一致
            print(f"  #{i} score={h['score']:.4f} [{h['source']}] {h['content'][:120]}")    # 分数与来源同列: 命中可追溯到知识条目, 不只是一段文本
    return 0



def cmd_config(args: argparse.Namespace) -> int:
    """端点/门禁/真实凭据面诊断 (全离线, 零凭据字面量)。

    Returns:
        恒 0 (Q-19): 诊断成功即 200 语义, 端点是否可达不进退出码。
    """
    # 延迟导入客户端常量与配置对象: 避免 CLI 启动即加载 requests 会话栈
    # 口令 env 键名现场取自 CLI 本体: 代码改名时本报告自动跟上, 不在两处各写一份
    from src.__main__ import AUTH_PASSWORD_ENV
    from src.client import BEST_BASE_URL
    from src.scripts.config import AstroBestConfig

    cfg = AstroBestConfig()                                                         # 零参数构造: 诊断要报"默认配置长什么样", 不该受调用方 env 干扰
    payload = {"rest_base_url": BEST_BASE_URL, "tap_url": cfg.tap_url,             # 两个端点并列: 走 REST 与走 TAP 是两条不同的取数路径, 都要报
               "quality": {"min_snr": cfg.min_snr, "max_fwhm": cfg.max_fwhm},      # 质量门阈值进 payload: 部署方据此核对线上的门限与本仓默认是否一致
               # 真实凭据面 (H9): 只报 env 键名与"是否已配置"的布尔, 口令值绝不进 payload
               "credential": {"username_arg": "--auth-user", "password_env": AUTH_PASSWORD_ENV,
                              "password_configured": bool(os.environ.get(AUTH_PASSWORD_ENV)),
                              "anonymous_ok": True,  # 公开数据面匿名可查: 没配凭据不代表不能用
                              "fallback_flag": "--allow-anonymous-fallback"},     # 凭据被拒默认非零退出, 降级匿名必须显式打开这个开关
               # 死路登记: 保留键名供旧部署对照, 但同一条就把"无此通道"写死, 免得半句被摘走又变回凭据来源
               "retired_env_keys": {"BEST_API_TOKEN": "客户端无此通道, 非凭据来源 (只覆盖 AstroBestConfig.api_token)"}}
    if args.json:                                                                           # JSON 出口: 供脚本断言字段存在, 不必解析人读文本
        print(json.dumps(payload, ensure_ascii=False, indent=2))                            # config --json 出口: 端点与门限供脚本断言
    else:
        print(payload)                                                                    # 文本出口: Python repr 便于人工扫一眼端点与门限
    # Q-19: 成功必须返回 0 (HTTP 200 语义只进 payload, 不当退出码)
    return 0


def cmd_slots(args: argparse.Namespace) -> int:
    """知识沉底体系 A 路: 按上下文确定性取用知识槽位 (不依赖 RAG)。

    与 B 路 (rag 子命令的 BM25 模糊召回) 的区别: 本命令只做精确挂钩查找,
    命中即返回整片知识, 不命中就返回空 — 不猜、不模糊、不做相似度打分。

    Returns:
        恒 0 (Q-19 语义: 未命中是正常结果, 不是失败)。
    """
    # 延迟导入槽位层: 只有 slots 子命令才拉 src.knowledge_slots
    from src.knowledge_slots import list_slots, resolve_slots

    if args.list:                                                                               # --list 与精确查找互斥: 列表不产知识内容
        keys = list_slots(args.dimension)  # dimension 缺省即全维度: 传 None 时列出已注册的全部
        if args.json:                                                                               # slots --list --json
            print(json.dumps({"slots": keys}, ensure_ascii=False, indent=2))                   # 列表也走 JSON: 槽位注册表要能被脚本核对数量
        else:
            print(f"[slots] {len(keys)} 个已注册槽位:")                                           # 先报总数: 槽位数量本身是体检信号(骤减说明注册表被裁)
            for key in keys:                                                              # 逐条列 key: key 是挂钩标识, 人工要能照着拼上下文
                print(f"  - {key}")                                                           # 缩进两格: 与上面的总数行区分层级, 别读成同级条目
        return 0

    # 只把显式给出的维度放进上下文: 未给出的维度不参与查找
    context = {  # 只收显式给出的维度: 未给的不参与查找, 免得误命中
        "algo_mode": args.algo_mode,                                                                # 算法模式维度: 决定走哪条算法分支的挂钩
        "data_source": args.data_source,                                                            # 数据源维度: 星表/模型等数据来源的挂钩
        "target_type": args.target_type,                                                        # 目标类型维度: 点源/图像/时序等目标形态的挂钩
        "catalog": args.catalog,                                                                    # 星表维度: 具体查哪张表的挂钩
        "error_kind": args.error_kind,                                                           # 错误类型维度: 按失败形态取对应处置经验的挂钩
    }
    slots = resolve_slots(context)  # 精确挂钩: 命中即整片返回, 不做相似度打分 (A 路语义)
    if args.json:                                                                                   # JSON 出口: 槽位内容供下游程序消费
        print(json.dumps([s.as_dict() for s in slots], ensure_ascii=False, indent=2))            # slots --json: 槽位内容供下游消费
    else:
        print(f"[slots] 命中 {len(slots)} 个槽位:")  # 零命中是合法结果: 因此不进退出码 (Q-19 语义)
        for slot in slots:                                                                         # 逐槽位展开: 一条一行, 便于人工逐条审批
            flag = " (已截断)" if slot.truncated else ""  # 截断标记打在标题行: 正文可能很长, 标记要一眼可见
            print(f"  [{slot.key}]{flag}")                                                        # 标题行: key 加截断标记, 正文按需再打
            if args.text:                                                                      # --text 才打正文: 默认只要清单, 免得刷屏
                print(slot.text)                                                                    # --text 才打正文
    return 0


def cmd_capture(args: argparse.Namespace) -> int:
    """知识沉底体系第一棒: 运行时事件 → 候选知识条目 (.knowledge/inbox/)。

    只归集不判定: 产出是 pending 状态候选, 必须人工审批后才可升格进
    rag/knowledge/ (那是 A/B 两路的唯一真源, 受只增不减硬锁保护)。

    Returns:
        0 有候选产出 (或 dry-run); 1 日志文件不存在。
    """
    # 按文件路径装载同目录模块 (ops/ 不是包, 与 rag 子命令同口径)
    import importlib.util

    spec = importlib.util.spec_from_file_location(                                           # 按路径装载同目录的 knowledge_capture
        "knowledge_capture_best", Path(__file__).resolve().parent / "knowledge_capture.py"  # 同目录装载: ops/ 不是包, 只能按路径加载 (与 rag 子命令同口径)
    )
    if spec is None or spec.loader is None:  # 不可装载即非零: 静默跳过会让沉底管道看起来一直在跑
        print("knowledge_capture.py 不可装载", file=sys.stderr)                         # 不可装载即报 stderr 并退出: 静默跳过会让沉底管道看起来一直在跑
        return 1
    cap = importlib.util.module_from_spec(spec)                                           # 先建模块对象: exec_module 需要它当命名空间容器
    sys.modules[spec.name] = cap                                                  # 登记进 sys.modules: 不登记则同一 .py 会被执行成两份类对象
    spec.loader.exec_module(cap)                                                                  # 唯一的外部代码装载点: 读本地文件, 零网络

    log_path = Path(args.log)  # 日志路径由参数给: 缺省值在 argparse 里锚到 skill 根
    if not log_path.is_file():                                                              # 日志不存在即非零: 沉底没有输入就不该报"扫了 0 条"
        print(f"[capture] 日志文件不存在: {log_path}", file=sys.stderr)                           # 路径回显: 让用户知道 CLI 找的是哪个文件, 而不是猜
        return 1
    since = cap._parse_since(args.since)                                   # 时间窗在装载层解析: '7d' 与绝对日期两种写法同源
    candidates, stats = cap.build_candidates(log_path, since, args.limit)  # 候选与统计一起返回: 扫描量与产出量要能对账
    print(f"[capture] 扫描 {stats['scanned']} 条事件 → 候选 {stats['captured']} 条 "
          f"(去重 {stats['duplicated']}, 噪声 {stats['noise']})")
    for item in candidates:  # 逐条打 pending 候选: 人工审批前它们还不是知识
        print(f"  [{item['id']}] {item['candidate_type']:15s} "
              f"slot={item['slot_hint'] or '-':26s} {item['title'][:50]}")
    if args.dry_run:  # dry-run 在写盘前短路: 审批流程先看后落
        print("[capture] dry-run: 未落盘")
        return 0
    written = cap.write_inbox(candidates, Path(args.inbox))  # 写点: 落 inbox 目录, 升格进真源要人工审批
    print(f"[capture] 已写入 {len(written)} 个候选 → {args.inbox}")
    return 0


def cmd_refs(args: argparse.Namespace) -> int:
    """references/ 白盒文档检索 (Q-55: kb 加载器接 CLI 入口)。

    Returns:
        命中/列清单返回 0; 指定文档不存在返回 1。
    """
    # 延迟导入 kb 加载器 (白盒文档清单 + 按名读取), 保持 doctor 子命令零重依赖
    from src.kb import list_references, load_reference

    refs = list_references()  # 清单来自 kb 加载器: CLI 不自己扫目录, 免两处口径
    if args.name:                                                                                   # 按名取白盒文档
        text = load_reference(args.name)                                             # 按名读取: 返回 None 表示文档不存在, 与"存在但为空"语义不同
        if text is None:  # None 与空串要分开: 前者是文档不存在, 后者是文档为空
            print(f"reference not found: {args.name}", file=sys.stderr)           # 不存在走 stderr: 调用方按流分流, 不把错误混进 stdout 结果
            return 1
        # --full 打印全文, 缺省截断到前 2000 字符 (防终端刷屏)
        print(text if args.full else text[:2000])                                                 # --full 才打全文: 缺省截断防终端刷屏
        return 0
    if args.json:                                                                                   # refs --json 出口
        print(json.dumps({"references": refs}, ensure_ascii=False, indent=2))                     # JSON 出口: 文档清单要能被脚本核对份数
    else:
        print(f"[refs] {len(refs)} 份白盒文档:")                                                       # 先报份数: 白盒文档数量骤减是仓库被裁的信号
        for name in refs:                                                                         # 逐条列名: 后续按名取用, 名字要能直接复制
            print(f"  - {name}")
    return 0


def cmd_oauth(args: argparse.Namespace) -> int:
    """NADC 通行证 OAuth2.0 身份入口 (Phase 6; 本地回环 + 手动粘贴)。

    六个子命令: status / url / paste / login / token / logout。全部凭据只读
    环境变量, 错误信息走 stderr, 成功载荷走 stdout (调用方按流分流)。

    Returns:
        0 表示该子命令语义成功; 1 表示失败/未知子命令。
    """
    # 延迟导入身份层: 只有 oauth 子命令才拉 TokenStore / 授权流等依赖
    from src.auth import (
        ENV_CLIENT_ID,  # 客户端 id 的 env 键名
        ENV_CLIENT_SECRET,  # 客户端密钥的 env 键名
        ENV_REDIRECT_URI,  # 回调地址的 env 键名
        NadcOAuthError,  # 授权失败基类
        TokenStore,  # 令牌持久化后端
        build_authorize_url,  # 拼授权 URL
        build_logout_url,  # 拼登出 URL
        ensure_access_token,  # 过期恢复单点
        get_profile,  # 取用户 profile
        run_local_callback_flow,  # 本地回调交互流
        run_manual_paste_flow,  # 手工粘贴交互流
    )

    # 凭据输入点: 一律环境变量, 代码内零凭据字面量 (Mimosa 安全约定)
    client_id = os.environ.get(ENV_CLIENT_ID, "")                                     # 凭据只从环境变量进: 代码内零凭据字面量 (Mimosa 安全约定)
    client_secret = os.environ.get(ENV_CLIENT_SECRET, "")
    redirect_uri = os.environ.get(ENV_REDIRECT_URI, "http://127.0.0.1:8765/callback")  # 回环地址须与授权端登记一致, 不一致换 token 会失败

    if args.oauth_cmd == "status":
        store = TokenStore()                                                                        # 令牌存储: 默认落在 skill 根下
        token = store.valid_token()                                                                 # 取有效令牌 (过期即视为无效)
        if not token:                                                                             # 无有效令牌即非零: 静默继续会让人以为已登录
            # 未授权三态可判: missing (从没有缓存) vs expired (授权过但过期,
            # NADC 无 refresh_token) — 恢复动作相同 (重走授权流), 但排障时
            # 是两件事; hint 直接把恢复命令写进载荷, 运维不用翻文档
            state = "expired" if store.load() else "missing"  # 两态靠缓存文件区分: 恢复动作相同, 排障时是两件事
            print(json.dumps({"authorized": False, "state": state,
                              "token_cache": str(store.path),
                              "hint": "token 缺失或已过期; 恢复: "
                                      "python ops/astro_best_cli.py oauth login"},
                             ensure_ascii=False))                                                   # token 子命令的 JSON 出口
            return 0
        try:
            # 外部网络调用点: 拉取 NADC 通行证 profile (需有效 token, 失败即非零)
            profile = get_profile(token)                                                            # 取 profile 需真发请求
        except NadcOAuthError as exc:
            # token 存在但已失效/被拒: 授权态保留, profile 错误单独进 payload
            print(json.dumps({"authorized": True, "state": "rejected",
                              "profile_error": str(exc)},
                             ensure_ascii=False))                                                   # profile 子命令输出
            return 1
        print(json.dumps({"authorized": True, "state": "valid",
                          "profile": profile.to_dict()},
                         ensure_ascii=False))                                                       # status 子命令输出
        return 0

    if args.oauth_cmd == "token":
        # 无头消费面: 打印可用 access_token 供管道使用
        # (TOKEN=$(python ops/astro_best_cli.py oauth token)); 过期且无交互通道时
        # ensure_access_token 抛 TokenExpiredError (消息带恢复命令), rc=1 —
        # 调用脚本不会把过期令牌当有效凭据继续用下去
        try:
            print(ensure_access_token())                                                            # paste 子命令: 打印新令牌
        except NadcOAuthError as exc:
            print(f"[ERROR] {exc}", file=sys.stderr)
            return 1
        return 0

    if args.oauth_cmd == "url":
        try:
            # 仅本地拼 URL, 不发请求: 供用户自行在浏览器完成授权 (无头环境友好)
            url, state = build_authorize_url(client_id, redirect_uri)  # state 一并返回: CSRF 校验要靠它, 不能只发 URL
        except NadcOAuthError as exc:
            print(f"[ERROR] {exc}", file=sys.stderr)
            return 1
        print(json.dumps({"authorize_url": url, "state": state}, ensure_ascii=False))  # 不自动开浏览器: 无头环境下由调用方自己决定
        return 0

    if args.oauth_cmd == "paste":
        try:
            # 手动粘贴流: 用户从浏览器拷回回调 URL/code, 由本进程代换 token (会发请求)
            profile = run_manual_paste_flow(client_id, client_secret, redirect_uri,                # login 走手工粘贴流 (无浏览器环境)
                                            args.callback)                                          # 回调端口可显式指定
        except NadcOAuthError as exc:
            print(f"[ERROR] {exc}", file=sys.stderr)
            return 1
        print(json.dumps({"authorized": True, "profile": profile.to_dict()},
                         ensure_ascii=False))                                                       # login 的 JSON 出口
        return 0

    if args.oauth_cmd == "login":
        try:
            # 本地回环流: 起 127.0.0.1 回调服务 + 自动开浏览器 (重网络交互)
            profile = run_local_callback_flow(client_id, client_secret, redirect_uri)  # 回环流会起本地服务并开浏览器: 唯一重网络交互的分支
        except NadcOAuthError as exc:
            # 回环被占/被拒时给出手动粘贴的退路提示, 不静默失败
            print(f"[ERROR] {exc} (可改用手动粘贴: oauth paste <回调URL或code>)",
                  file=sys.stderr)                                                                  # 出错走 stderr
            return 1
        print(json.dumps({"authorized": True, "profile": profile.to_dict()},
                         ensure_ascii=False))                                                       # login 的文本出口
        return 0

    if args.oauth_cmd == "logout":
        # 先取登出 URL (纯本地拼接), 再清本地 token 缓存文件
        print(build_logout_url(web_server_url=args.web_server_url or ""))
        TokenStore().clear()  # 只清本地缓存: 服务端会话由登出 URL 去收
        print("[oauth] 本地 token 缓存已清除", file=sys.stderr)
        return 0

    print(f"unknown oauth subcommand: {args.oauth_cmd}", file=sys.stderr)
    return 1


def cmd_log(args: argparse.Namespace) -> int:
    """任务日志查询: tail/problems/tasks/summary (快速定位问题)。

    Returns:
        查询成功返回 0; problems 发现 warn/error 事件时返回 1 (非零=有待看问题)。
    """
    # 延迟导入任务日志器: 只读本地 .logs 目录, 不触网
    from src.task_log import TaskLogger, fmt_records

    log = TaskLogger()                                                                              # 任务日志读取器
    if args.log_cmd == "tasks":
        for tid in log.tasks():                                                                     # 列出全部任务 id
            print(tid)                                                                              # 逐个打印
        return 0
    if args.log_cmd == "summary":
        print(json.dumps(log.summarize(args.job_id), ensure_ascii=False,                            # 汇总的 JSON 形态
                         indent=2))                                                                 # 缩进便于人工扫
        return 0
    if args.log_cmd == "problems":
        rows = log.problems(n=args.n)  # 只取 warn/error: info 级混进来会淹没真问题
        print(fmt_records(rows) if rows else "[log] 无 warn/error 事件")
        return 1 if rows else 0  # 非零=有问题待看
    # tail (缺省)
    rows = log.tail(n=args.n, task_id=args.job_id, event=args.event,                          # tail 的三个过滤维度 (条数/任务/事件/级别)
                    level=args.level)                                                # level 过滤与 event 过滤相互独立, 都不给就是纯 tail
    print(fmt_records(rows) if rows else "[log] 无匹配事件")  # 空结果也要有话: 静默无输出会被误读成命令没跑到
    return 0
    return 1


def cmd_doctor_extend(parser: argparse.ArgumentParser, sub) -> None:
    """注册 config/refs/oauth/download/log 子解析器 (各 skill 同形状的扩展点)。

    Args:
        parser: 顶层 ArgumentParser (保留签名兼容, 供未来顶层级选项使用)。
        sub: 子命令容器, 所有扩展子命令都挂到它下面。
    """
    # 延迟导入: download 子系统接线 (抽离件, budget R2; 函数内导入避免
    # 脚本直跑时 ops/ 非包的 ImportError, 与本文件其它延迟导入同纪律)
    from ops.cli_download import register_download
    p = sub.add_parser("config", help="BEST 端点/门禁/真实凭据面诊断 (离线)")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_config)                                                                 # config 子命令接线
    p_refs = sub.add_parser("refs", help="references/ 白盒文档清单/读取 (kb 加载器)")
    p_refs.add_argument("name", nargs="?", help="文档名 (缺省列清单)")
    p_refs.add_argument("--full", action="store_true", help="打印全文 (缺省前 2000 字符)")
    p_refs.add_argument("--json", action="store_true")
    p_refs.set_defaults(func=cmd_refs)                                                              # refs 子命令接线
    # NADC OAuth 身份层 (Phase 6)
    p_oauth = sub.add_parser("oauth", help="NADC 通行证 OAuth2.0 身份 (login/url/paste/status/token/logout)")
    oauth_sub = p_oauth.add_subparsers(dest="oauth_cmd")
    # login = 本地回环自动授权; url = 只出链接供手动浏览器授权 (两种授权通道)
    oauth_sub.add_parser("login", help="本地回环授权流 (自动打开浏览器)").set_defaults()
    oauth_sub.add_parser("url", help="仅打印授权 URL (手动浏览器授权)").set_defaults()
    p_paste = oauth_sub.add_parser("paste", help="手动粘贴回调 URL 或裸 code 完成授权")
    p_paste.add_argument("callback", help="回调 URL (含 code=) 或裸 authorization code")
    oauth_sub.add_parser("status", help="查看当前授权状态与 profile").set_defaults()
    # token = 无头消费面: 打印可用 token (过期即报错并给恢复命令, 见
    # cmd_oauth 的 ensure_access_token 分支 — 不把过期令牌当有效凭据输出)
    oauth_sub.add_parser("token", help="打印可用 access_token (过期即报错)").set_defaults()
    p_logout = oauth_sub.add_parser("logout", help="登出并清除本地 token 缓存")
    p_logout.add_argument("--web-server-url", default="", help="登出后重定向地址")
    p_oauth.set_defaults(func=cmd_oauth)                                                            # oauth 子命令接线
    # 下载管理子系统 (接线 + 实现已抽离至 ops/cli_download.py, budget R2)
    register_download(sub)  # 接线在抽离件里: 本文件只留扩展点, 控制净行预算

    # 任务日志 (快速定位问题)
    p_log = sub.add_parser("log", help="任务日志 (tail/problems/tasks/summary)")
    log_sub = p_log.add_subparsers(dest="log_cmd")
    # tail 为缺省子命令: 裸 `log` 与 `log tail` 等价 (在 set_defaults 里回落)
    p_tail = log_sub.add_parser("tail", help="最近 n 条事件 (缺省)")
    p_tail.add_argument("--n", type=int, default=20)
    p_tail.add_argument("--job-id", default=None, help="按任务过滤")
    p_tail.add_argument("--event", default=None, help="按事件类型过滤")
    p_tail.add_argument("--level", default=None, help="按级别过滤")
    p_tail.set_defaults(func=cmd_log)                                                               # log tail 接线
    p_prob = log_sub.add_parser("problems", help="全部 warn/error 事件")
    p_prob.add_argument("--n", type=int, default=20)
    p_prob.set_defaults(func=cmd_log)                                                       # log probe 接线 (与 tail 共用处理函数)
    p_tasks = log_sub.add_parser("tasks", help="列出全部任务 id")
    p_tasks.set_defaults(func=cmd_log)                                                              # log tasks 接线
    p_sum = log_sub.add_parser("summary", help="单任务聚合摘要")
    p_sum.add_argument("job_id")
    p_sum.set_defaults(func=cmd_log)                                                                # log summary 接线
    p_log.set_defaults(func=cmd_log, log_cmd="tail", n=20, job_id=None,
                       event=None, level=None)                                                      # 共享签名: 四个子命令靠参数有无区分行为



def main(argv: list[str] | None = None) -> int:
    """CLI 入口: 组装子命令树, 分发到各 cmd_* 并归一化退出码。

    Args:
        argv: 可选参数向量 (测试可注入; 缺省读 sys.argv)。

    Returns:
        0 成功; 非零为门禁失败 (各子命令语义见其 docstring)。
    """
    repo = argparse.ArgumentParser(prog="astro-best", description="astro-best 本地 CLI")  # prog 固定: 帮助里显示的名字与实际调用一致
    sub = repo.add_subparsers(dest="cmd")
    sub.add_parser("doctor", help="导入真包 + 组件自检 (离线)").set_defaults(func=cmd_doctor)  # doctor 挂最前: 它是门禁入口, 出问题先跑它
    p_rag = sub.add_parser("rag", help="本地知识混合检索")
    p_rag.add_argument("query")
    p_rag.add_argument("--top-k", type=int, default=5)
    p_rag.add_argument("--json", action="store_true")
    p_rag.set_defaults(func=cmd_rag)                                                                # rag 子命令接线
    # 知识沉底体系 A 路: 确定性槽位取用 (不依赖 RAG, 精确挂钩查找)
    p_slots = sub.add_parser("slots", help="知识槽位确定性取用 (A路, 不依赖 RAG)")
    p_slots.add_argument("--catalog", default=None, help="星表槽位值 (如 ps1)")
    p_slots.add_argument("--algo-mode", dest="algo_mode", default=None, help="算法模式槽位值")
    p_slots.add_argument("--data-source", dest="data_source", default=None, help="数据源槽位值")
    p_slots.add_argument("--target-type", dest="target_type", default=None, help="目标类型槽位值")
    p_slots.add_argument("--error-kind", dest="error_kind", default=None, help="错误类别槽位值")
    p_slots.add_argument("--list", action="store_true", help="只列出已注册槽位")
    p_slots.add_argument("--dimension", default=None, help="--list 时限定维度")
    p_slots.add_argument("--text", action="store_true", help="打印槽位正文")
    p_slots.add_argument("--json", action="store_true", help="机器可读输出")
    p_slots.set_defaults(func=cmd_slots)                                                            # slots 子命令接线
    # 知识沉底体系第一棒: 运行时事件 → 候选条目 (两套取用路共用)
    p_cap = sub.add_parser("capture", help="运行时事件 → 候选知识条目 (沉底管道)")
    p_cap.add_argument("--log", default=str(SKILL_ROOT / ".logs" / "task_log.jsonl"),
                       help="事件日志 (JSONL)")
    p_cap.add_argument("--inbox", default=str(SKILL_ROOT / ".knowledge" / "inbox"),
                       help="候选条目输出目录")
    p_cap.add_argument("--since", default=None, help="只扫最近多久: '7d' 或 '2026-09-01'")
    p_cap.add_argument("--limit", type=int, default=50, help="最多产出多少条候选")
    p_cap.add_argument("--dry-run", action="store_true", help="只打印不落盘")
    p_cap.set_defaults(func=cmd_capture)                                                            # capture 子命令接线
    # 领域演示子命令接线 (各 skill 的 cmd_doctor_extend 同形状)
    cmd_doctor_extend(repo, sub)  # 扩展点单独一个函数: 各 skill 同形状, 便于对齐新增子命令

    args = repo.parse_args(argv)         # argv 缺省读 sys.argv: 测试可注入而不改进程状态
    if not getattr(args, "func", None):  # getattr 而非下标: 没匹配子命令时 argparse 不设 func
        # 无子命令: 打帮助并返回 0 (不是错误, 只是用法提示)
        repo.print_help()                                                                    # 无子命令时打帮助: 不静默退出, 让人知道有哪些子命令
        return 0
    rc = args.func(args)                      # 唯一派发点: 各 cmd_* 的返回值就是退出码
    return 0 if rc in (0, None) else int(rc)  # None 视作 0: 允许子命令只 print 不显式 return


if __name__ == "__main__":
    raise SystemExit(main())
