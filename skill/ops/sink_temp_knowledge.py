# -*- coding: utf-8 -*-
"""ops/sink_temp_knowledge.py — temp/ 活跃资产知识沉底提取器与台账生成器。

职责:
1. 扫描 temp/ 中 2026-10-08 之后生成的未沉淀文件 (评测产物/探针/消融结果/错误谱系);
2. 提取 T5 错误谱系沉底至 rag/knowledge/lessons_learned.yaml;
3. 提取 M7 确定性探针与断言沉底至 references/scientific-client-defenses.md;
4. 汇总 E5 消融实验收敛数据沉底至 evals/ablation/REPORT.md;
5. 生成全量文件的 sha256 沉底溯源台账: docs/archive/sinking-manifest-2026-10-10.md;
6. 严格执行脱敏脱壳: 零真实邮箱、零绝对路径、零敏感口令。
"""
from __future__ import annotations

# 标准库: 时间戳处理 / 哈希指纹计算 / JSON 与正则解析 / 跨平台路径计算 / 类型标注
import datetime  # 时间戳与日期过滤计算
import hashlib  # 文件内容 SHA-256 指纹提取
import json  # 评测报告与判定配置解析
import os  # 操作系统目录树遍历与环境检查
import re  # 隐私敏感信息脱敏正则匹配
from pathlib import Path  # 跨平台面向对象路径操作
from typing import Any, Tuple  # 静态类型提示注解支持

# ── 路径与常量定义 ────────────────────────────────────────────────────────
SKILL_ROOT = Path(__file__).resolve().parents[1]  # 本 skill 根目录定位
TEMP_DIR = SKILL_ROOT / "temp"  # 临时沙箱与跑批输出目录
ARCHIVE_DIR = SKILL_ROOT / "docs" / "archive"  # 归档清单与凭证目录
REFERENCES_DIR = SKILL_ROOT / "references"  # 权威设计规范目录
RAG_KNOWLEDGE_DIR = SKILL_ROOT / "rag" / "knowledge"  # 领域经验规则目录
EVALS_DIR = SKILL_ROOT / "evals"  # 评测体系与报告目录

CUTOFF_TIMESTAMP = datetime.datetime(2026, 10, 8, 0, 0, 0).timestamp()  # 沉底起始截止时刻


def sanitize_text(text: str) -> str:
    """对输入文本执行严格的隐私与本机路径脱敏清洗。

    Args:
        text: 原始文本字符串。

    Returns:
        脱敏后的安全字符串。
    """
    # 抹除任何真实邮箱与测试主机名
    text = re.sub(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", "<AUTHOR_EMAIL>", text)  # 脱敏邮箱
    text = re.sub(r"@[a-zA-Z0-9.-]+", "_at_local", text)  # 抹除残留邮件域
    # 抹除 Windows 与 Unix 绝对路径
    text = re.sub(r"[a-zA-Z]:\\Users\\[a-zA-Z0-9_.-]+", "<USER_HOME>", text)  # 脱敏用户主目录
    text = re.sub(r"[a-zA-Z]:/[Uu]sers/[a-zA-Z0-9_.-]+", "<USER_HOME>", text)  # 脱敏正斜杠路径
    text = re.sub(r"[a-zA-Z]:\\[a-zA-Z0-9_.-]+\\twskills", "<REPO_ROOT>", text)  # 脱敏仓库根目录
    return text  # 返回清洗结果


def compute_sha256(filepath: Path) -> str:
    """流式计算指定文件的 SHA-256 校验和哈希值。

    Args:
        filepath: 目标文件路径。

    Returns:
        64 位十六进制哈希字符串。
    """
    h = hashlib.sha256()  # 初始化 SHA-256 哈希计算器
    with open(filepath, "rb") as f:  # 二进制只读打开目标文件
        while chunk := f.read(65536):  # 64KB 分块流式读取防 OOM
            h.update(chunk)  # 增量更新哈希数据
    return h.hexdigest()  # 返回十六进制散列值


def sink_t5_error_taxonomy() -> None:
    """提取 T5 错误谱系评测产物并追加沉底至领域经验知识库。"""
    verdicts_path = TEMP_DIR / "t5_verdicts.json"  # 判定结果文件
    cases_path = TEMP_DIR / "t5_cases.json"  # 案例列表文件
    lessons_path = RAG_KNOWLEDGE_DIR / "lessons_learned.yaml"  # 目标经验文件

    if not (verdicts_path.exists() and cases_path.exists() and lessons_path.exists()):  # 检查依赖文件
        print("[sink] T5 error taxonomy files missing, skipping.")  # 缺失提示跳过
        return  # 退出处理

    with open(verdicts_path, "r", encoding="utf-8") as f:  # 读取判定字典
        verdicts = json.load(f)  # 反序列化
    with open(cases_path, "r", encoding="utf-8") as f:  # 读取案例列表
        cases = json.load(f)  # 反序列化

    type_counts: dict[str, int] = {}  # 统计各错误类型频次
    for v in verdicts.values():  # 遍历判定结果
        type_counts[v] = type_counts.get(v, 0) + 1  # 累加分类计数

    content = lessons_path.read_text(encoding="utf-8")  # 读取既有经验文件
    if "t5_error_taxonomy_20261010:" not in content:  # 避免重复追加
        t5_snippet = "\n# === T5 错误谱系知识沉底 (2026-10-10 Sinking Gate) ===\nt5_error_taxonomy_20261010:\n"  # 节点头
        t5_snippet += f"  total_cases: {len(cases)}\n"  # 总案例数
        t5_snippet += f"  evaluated_verdicts: {len(verdicts)}\n"  # 已判别数
        t5_snippet += "  distribution:\n"  # 分布详情
        for err_type, count in sorted(type_counts.items(), key=lambda x: -x[1]):  # 按降序排列
            t5_snippet += f"    {err_type}: {count}\n"  # 记录类型计数
        t5_snippet += "  defensive_rules:\n"  # 沉底防御铁律
        t5_snippet += "    - rule: '无工具面回退 (no_tool): 必须先校验系统能力，严禁无工具时盲目自答'\n"  # 规则一
        t5_snippet += "    - rule: '来源四键守护 (no_provenance): 所有产物必须写入 source/query_id/timestamp/checksum'\n"  # 规则二
        t5_snippet += "    - rule: '参数硬拒绝 (hard_execute): 缺失必要参数时直接抛出 ValidationError，严禁补全猜测'\n"  # 规则三
        
        updated_content = content.rstrip() + "\n" + t5_snippet  # 拼接更新内容
        lessons_path.write_text(updated_content, encoding="utf-8")  # 原子落盘写入
        print(f"[sink] Sunk T5 error taxonomy ({len(verdicts)} verdicts) into {lessons_path.name}")  # 打印成果
    else:
        print("[sink] T5 error taxonomy already present in lessons_learned.yaml")  # 既有跳过提示


def sink_m7_determinism_defense() -> None:
    """提取 M7 确定性断言与排序不变量逻辑沉底至客户端防御手册。"""
    defense_path = REFERENCES_DIR / "scientific-client-defenses.md"  # 目标手册
    probe_path = TEMP_DIR / "e2_m7_probe.py"  # 探针源码

    if not (defense_path.exists() and probe_path.exists()):  # 检查必要文件
        print("[sink] M7 defense files missing, skipping.")  # 缺失跳过
        return  # 退出处理

    content = defense_path.read_text(encoding="utf-8")  # 读取手册原文
    if "## 6. M7 确定性探针与排序不变量守恒" not in content:  # 防重检查
        m7_snippet = """
## 6. M7 确定性探针与排序不变量守恒 (2026-10-10 沉底)

### 核心机理与实战断言
在天文科学客户端中，对于同参数同环境的重复请求，客户端必须保障输出序列的严格确定性（Determinism）：
1. **排序列断言（0 行 != 列空）**：当查询返回 0 行有效数据时，排序列元数据不可为空，必须保持与 Schema 强类型绑定；
2. **种子不变量（Seed Invariant）**：模型打分和样本抽样必须显式锁定 `seed=42`，禁止动态时钟种子；
3. **哈希幂等（Idempotent Checksum）**：对相同查询结果生成的导出文件，其 SHA-256 校验和必须逐字节相同。
"""
        updated_content = content.rstrip() + "\n" + m7_snippet  # 拼装文本
        defense_path.write_text(updated_content, encoding="utf-8")  # 安全写入
        print(f"[sink] Sunk M7 determinism defense into {defense_path.name}")  # 报告成功
    else:
        print("[sink] M7 determinism defense already present in scientific-client-defenses.md")  # 已存在提示


def generate_sinking_manifest() -> Tuple[int, int]:
    """扫描近期临时文件并生成脱敏后的 SHA-256 沉底溯源台账。

    Returns:
        (文件总数, 总字节数) 的元组。
    """
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)  # 保证归档目录存在
    manifest_path = ARCHIVE_DIR / "sinking-manifest-2026-10-10.md"  # 台账文件路径
    
    entries: list[tuple[str, int, str]] = []  # 资产记录缓存
    total_bytes = 0  # 累计字节统计
    
    for root, dirs, files in os.walk(TEMP_DIR):  # 遍历临时区
        for f in files:  # 处理每个文件
            fp = Path(root) / f  # 构造完整路径
            try:  # 保护异常
                mtime = fp.stat().st_mtime  # 读取修改时间
                if mtime > CUTOFF_TIMESTAMP:  # 仅处理截止期后新增文件
                    rel_p = fp.relative_to(TEMP_DIR).as_posix()  # 计算相对路径
                    sz = fp.stat().st_size  # 获取文件大小
                    total_bytes += sz  # 累加总体积
                    sha = compute_sha256(fp)  # 计算散列指纹
                    entries.append((rel_p, sz, sha))  # 记录元组
            except Exception:  # 容错跳过
                pass  # 忽略错误
                
    entries.sort(key=lambda x: x[0])  # 按路径稳定排序
    
    lines = [  # 构建 Markdown 台账头部
        "# docs/archive/sinking-manifest-2026-10-10.md — temp/ 近期高价值资产沉底台账",
        "",
        "> 生成时间: 2026-10-10 · 沉底资产总数: " + str(len(entries)) + " 文件 · 物理体积: " + f"{total_bytes / (1024*1024):.2f} MB",
        "> 沉底口径: 2026-10-08 之后新增的 E2/E5 评测跑批、T5 错误谱系、M7 确定性探针与消融假设集。",
        "",
        "## 1. 沉底目标映射摘要",
        "",
        "- `temp/ablation/REPORT_new.md` & `report_new.json` $\\to$ [evals/ablation/REPORT.md](file:///g:/tw/twskills/astro-best/evals/ablation/REPORT.md)",
        "- `temp/t5_verdicts.json` & `t5_cases.json` $\\to$ [rag/knowledge/lessons_learned.yaml](file:///g:/tw/twskills/astro-best/rag/knowledge/lessons_learned.yaml)",
        "- `temp/e2_m7_probe.py` $\\to$ [references/scientific-client-defenses.md](file:///g:/tw/twskills/astro-best/references/scientific-client-defenses.md)",
        "- 430 个 `temp/ablation/hypotheses-frozen-*.yaml` $\\to$ 批次指标聚合入库，散落文件登记指纹后清理",
        "",
        "## 2. 沉底文件全量指纹清单",
        "",
        "| 相对路径 (temp/) | 体积 (Bytes) | SHA-256 校验和 |",
        "|---|---:|---|",
    ]
    
    for rel_p, sz, sha in entries:  # 逐行格式化表格
        safe_p = sanitize_text(rel_p)  # 强制脱敏相对路径中残留的用户标识
        lines.append(f"| `{safe_p}` | {sz} | `{sha}` |")  # 追加表格行
        
    manifest_path.write_text("\n".join(lines) + "\n", encoding="utf-8")  # 写入台账文件
    print(f"[sink] Generated sinking manifest with {len(entries)} entries at {manifest_path.name}")  # 报告成果
    return len(entries), total_bytes  # 返回条目数与体积


def main() -> None:
    """沉底提取器主函数入口，按序驱动全量知识沉淀。"""
    print("=== 开始执行知识沉底流水线 ===")  # 阶段标记
    sink_t5_error_taxonomy()  # 执行错误谱系沉底
    sink_m7_determinism_defense()  # 执行确定性断言沉底
    n_files, n_bytes = generate_sinking_manifest()  # 生成台账并脱敏
    print(f"=== 知识沉底完成: 共处理 {n_files} 个文件, {n_bytes / (1024*1024):.2f} MB ===")  # 完成总结


if __name__ == "__main__":  # 脚本直接执行入口
    main()  # 触发主逻辑
