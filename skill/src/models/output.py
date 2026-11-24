"""src.models.output — BEST 查询结果的输出模型。

能力边界: 输出模型 (BestResultSet/QueryOutput/DownloadOutput/QualityReport): 契约匹配的实质模型 (Phase 3 偏差记录: 保留非删)。**四个类在 src/ 与 test/ 内均无生产构造点** (H6-02 实测: QueryOutput/DownloadOutput/QualityReport 各 0 处, BestResultSet 仅 6 处且全在 test/unit/models/test_model_defaults.py) —— 判定为「按契约声明保留、尚未接线」, 不是死代码: contracts/output.contract.yaml 以 BestResultSet 为输出 schema, manifest.yaml 的 result_json sink 声明其信封, 跨 skill 消费方按此名取件。此前本 docstring 自称"由 provenance.envelope_for_result 提供真实构造注入点 (Q-08 接线)" —— 该说法与代码事实不符 (envelope_for_result 只调 result.to_dict(), 从不构造本类), 已订正。门禁字段的缺省值一律 fail-closed (见 BestResultSet.gates_passed)。
白盒锚点: contracts/output.contract.yaml; contracts/envelope.contract.yaml。
"""

from __future__ import annotations

# 标准库: 任意负载与可选字段的类型标注 (sources/handoff 等为自由结构 dict) /
# manifest 路径定位与可注入锚点 (G3: 跨 skill 路由从 manifest 读取而非硬编码)
from pathlib import Path
from typing import Any, Optional

# 第三方: PyYAML 解析 manifest.yaml 的 redirects 表 (environment.yaml 已声明
# 的硬依赖; 读取失败按明确降级语义处理, 见 _next_skills_from_manifest)
import yaml

# 本地: skill 根解析的唯一实现 (R4-03: 本处原有第二份副本已收敛)。原先的
# 兜底写死 parents[2] —— 与本件所在层数耦合, 副本分叉时静默解析到错根。
from src._paths import skill_root

# G3: manifest 路径的可注入锚点。None = 运行时按 skill 根解析; 测试用
# monkeypatch 注入临时 manifest, 证明 next_skills 真的随 manifest 变化。
# 下游名单只从 manifest 读, 不得写死在模型默认值里: 硬编码名单在 envelope
# 契约变更时会静默漂移。
_MANIFEST_PATH: Optional[Path] = None  # 缺省 None = 运行时按 skill 根解析; 显式赋值即测试注入点

# 读不到 manifest (文件缺失/不可读/语法坏/无 redirects) 时的降级语义:
# 空清单 = "未声明任何下游交接", 由调用方按无交接处理。绝不回退到写死的
# skill 名单 — 那正是 G3 要消除的静默漂移源。
_NEXT_SKILLS_FALLBACK: tuple[str, ...] = ()  # 故意留空元组: 降级成写死名单正是要消除的静默漂移源


def _next_skills_from_manifest(manifest_path: Optional[Path] = None) -> list[str]:
    """从 manifest.yaml 的 redirects 表派生跨 skill 交接清单 (G3)。

    权威出处是 manifest 的 ``redirects``: 每条 ``{from, to, reason}`` 声明
    一次本 skill 向外移交的能力, ``to`` 即下游 skill 名。自指声明 (``to``
    等于 manifest 的 ``name``) 不是跨 skill 交接, 跳过; 结果保序去重。

    降级语义 (读不到时): 返回空 list — "没有声明下游"比"猜一个下游"诚实,
    调用方拿到空清单应按无交接处理, 而不是当成本 skill 自己消化。

    Args:
        manifest_path: 显式 manifest 路径; None 时用模块级 ``_MANIFEST_PATH``
            注入点, 再缺省按 skill 根解析 (测试注入点)。

    Returns:
        下游 skill 名列表 (保序去重); 读不到 manifest 时为空列表。
    """
    path = manifest_path or _MANIFEST_PATH or (skill_root(__file__) / "manifest.yaml")  # 三级优先: 显式参数 > 测试锚点 > skill 根解析, 顺序不可调换
    try:
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))  # safe_load 而非 load: manifest 是外部输入, 不给它构造任意对象的权限
    except (OSError, yaml.YAMLError):
        # 文件缺失/不可读/语法坏都按"无声明"处理: 模型层不因 manifest 缺失
        # 而炸掉构造, 但也不 invent 路由
        return list(_NEXT_SKILLS_FALLBACK)  # 降级而非抛: 缺 manifest 不该让输出模型无法构造
    if not isinstance(data, dict):  # 顶层不是映射 (手滑写成列表) 同样按"无声明"处理, 不抛
        return list(_NEXT_SKILLS_FALLBACK)
    own = str(data.get("name") or "")  # 自指判定的基准: 取 manifest 自己的 name 字段
    skills: list[str] = []                                                                          # 保序去重的结果容器: 顺序即清单声明顺序
    for entry in data.get("redirects") or []:  # or [] 兜住 redirects 缺失与显式 null 两种 YAML 写法
        if not isinstance(entry, dict):                                                          # 非映射条目跳过: 清单是外部输入, 形态不保证
            continue
        target = str(entry.get("to") or "").strip()
        # 自指声明 (to == 本 skill 名) 不是跨 skill 交接; 顺带去重保序
        if target and target != own and target not in skills:  # 三条件缺一不可: 空串/自指/已声明过 都不是跨 skill 交接
            skills.append(target)                                                             # 追加而非入集合: 同一 skill 重复声明只留首次
    return skills or list(_NEXT_SKILLS_FALLBACK)  # 空清单是合法结果不是失败: 调用方按"无交接"处理即可


class QueryOutput:
    """标准化的查询输出 (给上游 skill 的查询结果摘要)。

    与 BestQueryResult 的分工: 那个承载完整源列表, 这个只承载计数与错误摘要,
    字段直接对应 contracts/output.contract.yaml 的查询输出段。
    """

    def __init__(
        self,                                                                                       # 实例: 字段逐项落到属性上
        success: bool,                                                                            # 成功是必填: 软错误与输入非法同样走假值分支
        total_count: int = 0,                                                                       # 总数缺省零: 摘要里不允许出现空值计数
        returned_count: int = 0,
        sources: Optional[list[dict]] = None,                                                       # 源列表可空: 摘要层允许只报计数不报体
        error: Optional[str] = None,                                                              # 错误文本可空: 只给人读, 分支判断必须看码
    ) -> None:
        """构造查询输出摘要 (``success`` 为必填, 其余可缺省)。"""
        # 查询是否成功 (软 404/无 sqlid/输入非法均为 False, 并带 error_code 语义)。
        self.success = success                                    # 软 404 也走这里: success 才是分支依据, error 文本只给人读
        # 服务端报告的总行数 (getcount) 与本次实际返回的行数; 两者不等即截断。
        self.total_count = total_count                                                              # 与取回数分别记录: 两者不等即结果被截断
        self.returned_count = returned_count                      # 与 total_count 的差就是被截断掉的部分, 两个字段不能合并
        # 源列表 (dict 形式, 通常来自 BestSource.to_dict()); 缺省为空列表。
        self.sources = sources or []                              # or [] 兜成 list: 下游可直接迭代, 不必先判 None
        # 人类可读的错误描述; 分支判断应改用契约错误码而不是匹配这段文本。
        self.error = error                                        # 只给人读: 分支判断必须改用契约错误码, 别匹配这段文本

    def to_dict(self) -> dict[str, Any]:
        """QueryOutput -> dict (success/counts/n_sources/error)。

        ``total_count``/``returned_count`` 分别记服务端报告总量与实际取回量,
        两者不等即结果被截断; 调用方应读这两个数而不是 ``len(sources)``。
        """
        return {
            "success": self.success,
            "total_count": self.total_count,
            "returned_count": self.returned_count,
            "n_sources": len(self.sources),  # 报数不报体: 摘要里带上整份 sources 会把输出撑大
            "error": self.error,
        }


class DownloadOutput:
    """批量下载的输出摘要 (一次下载任务的完成情况)。"""

    def __init__(
        self,                                                                                       # 实例: 作业标识是续传的锚
        job_id: str,                                                                               # 作业标识必填: 落盘名与断点文件都由它派生
        total_downloaded: int = 0,                                                                # 落盘与跳过的合计: 调用方据此判断是否已完成
        output_path: Optional[str] = None,                                                          # 尚未产出时为空: 调用方据此决定等不等
        errors: Optional[list[str]] = None,                                                     # 逐源错误可空: 全量留在对象里, 序列化时才截断
    ) -> None:
        """构造下载摘要 (``job_id`` 为必填, 其余可缺省)。"""
        # 下载作业标识; total_downloaded 为实际落盘/跳过的行数合计。
        self.job_id = job_id  # 作业标识是续传的锚: 落盘名与 checkpoint 都由它派生
        self.total_downloaded = total_downloaded                                                 # 与错误条数分开记: 两个数语义不同, 不可合并
        # 输出文件路径 (单文件合并输出时) 或输出目录;  None 表示尚未产出。
        self.output_path = output_path                                                              # 原样落属性: 路径消毒在落盘那一侧统一做
        # 逐源错误列表; to_dict 只吐前 5 条, 避免错误文本淹没摘要。
        self.errors = errors or []                                                                  # 兜成列表: 下游直接遍历, 不必先判空

    def to_dict(self) -> dict[str, Any]:
        """DownloadOutput -> dict (job_id/output_path/errors 摘要)。"""
        return {
            "job_id": self.job_id,
            "total_downloaded": self.total_downloaded,
            "output_path": self.output_path,
            "n_errors": len(self.errors),
            "errors": self.errors[:5],
        }


class QualityReport:
    """质量验证报告 (对一次查询/下载结果的门控结论)。"""

    def __init__(
        self,                                                                                       # 实例: 汇总结论与逐项明细相互独立
        passed: bool,
        checks: Optional[list[dict]] = None,                                                      # 逐项明细可空: 只读汇总结论会丢掉为什么被拒
        score: float = 1.0,                                                                       # 质量分缺省满值: 缺省不该凭空造一个低分结论
    ) -> None:
        """构造质量报告 (``passed`` 为必填; ``score`` 与 ``passed`` 相互独立)。"""
        # 是否通过质量门控 (任一硬性检查失败即 False)。
        self.passed = passed  # 汇总结论不做加权: 任一硬性检查失败即 False
        # 逐项检查明细 (每项含名称/通过态/说明), 供人工复核追溯。
        self.checks = checks or []                                                                  # 兜成列表: 消费方直接遍历, 不必判空
        # 综合质量分 (1.0 = 全部通过); 分数与 passed 相互独立, 分数低但硬性
        # 检查全过时仍可为 passed=True。
        self.score = score  # 与 passed 相互独立: 分数低但硬性检查全过仍可 passed=True

    def to_dict(self) -> dict[str, Any]:
        """QualityReport -> dict (passed/score/checks)。

        ``checks`` 是逐项判定明细 (哪一条没过), ``passed`` 是汇总结论 —
        只读 ``passed`` 会丢失"为什么被拒", 人工复核需要明细。
        """
        return {
            "passed": self.passed,
            "score": self.score,
            "n_checks": len(self.checks),
            "checks": self.checks,
        }


class BestResultSet:
    """符合契约的输出模型, 对应 contracts/output.contract.yaml 的 schema: BestResultSet。"""

    def __init__(
        self,                                                                                       # 实例: 契约输出模型的容器
        data: Optional[dict[str, Any]] = None,                                                  # 负载可空: 缺省给空字典, 契约要求该段恒为映射
        status: str = "ready",
        handoff: Optional[dict[str, Any]] = None,                                         # 交接信息可空: 缺省从清单派生, 跨 skill 路由不写死
        http_status: Optional[int] = None,                                                        # 缺省 None = 未知, **不是 200**: 门禁 fail-closed
        checksum_match: bool = False,                                                           # 缺省 False = 未校验即不通过, 不假装匹配
    ) -> None:
        """构造契约输出模型 (data/status 可缺省, 门控字段默认值一律 fail-closed)。

        门控字段 (``http_status`` / ``checksum_match``) 的缺省值刻意取
        **不通过**那一侧: 缺省即"还没人回填真实判定", 而不是"判定通过"。
        早期版本把 ``http_status`` 缺省成 200、``checksum_match`` 缺省成 True,
        于是任何未回填的实例都能通过 ``manifest.yaml`` / ``agents/openai.yaml``
        声明的两条 **blocking** 门禁 —— 恒真的门禁等于没有门禁, 且失败方向
        恰恰是最危险的一侧 (把失败读成成功)。
        """
        # 实际负载 (源列表/计数/查询参数等), 缺省为空 dict。
        self.data = data or {}  # 缺省空 dict 而非 None: 契约要求 data 恒为映射
        # 结果状态 (``ready`` / ``truncated`` / ``failed`` ...), 供下游分流。
        self.status = status                                                                        # 状态原样落属性: 下游分流的第一依据
        # 交接信息: 显式给出下一步应接的 skill 列表; 缺省从 manifest.yaml 的
        # redirects 表派生 (G3: 不再写死 ["astro-catalog", "astro-clean"] —
        # 跨 skill 路由随 manifest/契约变更而变, 读不到时降级为空清单, 见
        # _next_skills_from_manifest 的降级语义)。
        self.handoff = handoff or {  # 显式 handoff 优先: 只有没给才从 manifest 派生
            "status": status,
            "next_skills": _next_skills_from_manifest(),
        }
        # 门控字段: 上游 HTTP 状态码与校验和匹配态。缺省一律取"不通过"侧,
        # 必须由真实响应回填 —— 未回填时门禁判否 (fail-closed), 而不是恒真。
        self.http_status = http_status                             # None = 未知, 不可与 200 相等: 门禁自然判否, 不必另设分支
        self.checksum_match = checksum_match                       # False = 未校验, 不宣称匹配 (假门禁的另一半)

    def gates_passed(self) -> bool:
        """两条 blocking 门禁的**求值** (与 manifest/agents 声明同口径)。

        存在的理由: 门禁此前只以 ``{"http_status": 200, "checksum_match":
        True}`` 的字面声明存在, 代码里没有任何一处真正求值它。缺省即通过
        的字段配上无人求值的声明, 合起来是一条恒真的假门禁。这里给出唯一
        一处求值实现, 且判定**与缺省方向相反** —— 未知即不通过。

        Returns:
            True 仅当 ``http_status`` 恰为 200 **且** ``checksum_match`` 为
            True; 任一不满足 (含 ``http_status`` 仍为 None 的未回填态) 即 False。
        """
        return self.http_status == 200 and self.checksum_match is True  # 两条件并判: 声明是两条 blocking 门禁

    def to_dict(self) -> dict[str, Any]:
        """BestResultSet -> dict (data/status/handoff/gates 四段)。"""
        return {
            "data": self.data,
            "status": self.status,
            "handoff": self.handoff,
            "gates": {
                "http_status": self.http_status,  # 门控字段单列 gates 段: 消费方能一眼区分"结论"与"判定依据"
                "checksum_match": self.checksum_match,
            },
        }
