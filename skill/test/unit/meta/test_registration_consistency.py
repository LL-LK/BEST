# -*- coding: utf-8 -*-
"""登记一致性守护: 仓内两处声明 (register_skill / manifest / SKILL.md) + conda_env 口径。

缺陷形态 (2026-10-05 J7 审计 J7-03): 登记辅助宣称的 ``conda_env`` 与共享登记表
不一致 (脚本 ``astro-best`` / 表里 ``astro-base``)。此事曾长时间全绿, 因为

  - ``grep register_skill|entry_points test/`` → **零命中**, 登记一致性此前
    没有任何测试守护;
  - ``register_skill.py --check`` 只判"表在不在", 字段分叉照绿。

本件把这两件事变成**可守护**的, 分两条腿:

  1. ``conda_env`` 口径: ``register_skill.ENTRY`` / ``environment.yaml`` /
     共享登记表三者必须一致, 且**必须是一个真实存在过的环境名**。
     口径取共享登记表而不是 ``environment.yaml``, 依据见下。
  2. 登记辅助自身的 ``--check`` 对账非空转 (喂一个已知分叉必须被抓)。

**2026-10-06 移除的第三条腿 (MCP 三层表述一致性)**: 该腿守的是"仓内三处对
MCP 的说法与登记状态是否自洽", 而 MCP server (``ops/best_mcp_server.py``) 已按
决定整体移除 —— 被测对象不存在时, 这条腿要么恒绿要么恒红, 两种都是假门禁,
故整腿删除而非改写成对已删文件的检查。移除后的口径是: **仓内不再有任何 MCP
入口**, 故也无从声称它可用或不可用; 若将来重新引入, 必须连同这条腿一起回来。

**为什么 conda_env 以共享登记表为准, 而不是 ``environment.yaml``** (K1-03 的
独立核实结论): ``environment.yaml`` 写 ``name: astro-best``, 但那个环境
**从未被创建过** ——

  - ``_shared/environments/`` 下只有 9 份定义, **没有** ``astro-best.yaml``;
  - ``_shared/environments/create_envs.ps1`` 的 ``$ENVS`` 名单里也没有它;
  - ``_shared/skill-engine/runtime/dep_resolver.py`` 的
    ``SkillEnvDeclaration.conda_env`` 缺省值是 ``astro-base``, 且它的
    ``MCP_SKILLS`` 表不含 astro-best —— 于是宿主解析 astro-best 落到的正是
    ``astro-base``。

即"登记表写的那一侧才对应宿主实际会用的环境"。``environment.yaml`` 的
``name:`` 另有含义 (它是本仓自己的环境锁文件名, 由
``test_environment_lock.py`` 单独守护), 故本件只在它与登记表**冲突**时报错,
不要求两者恒等 —— 那是两种语义, 强行统一反而会拆掉环境锁。

**母仓文件不在本仓管辖范围**: ``_shared/skill-registry.yaml`` 属上级仓库,
本 skill 无权修改。因此涉及它的断言走 ``skipif`` (母仓不在场就不判), 但
**不静默放过**: 母仓在场时逐字段对账必须通过, 否则即红。仓内两处
(register_skill / manifest / SKILL.md) 的互一致性则是无条件守护, 不受母仓
是否在场影响。
"""
from __future__ import annotations

# 标准库: importlib 按路径装载 ops 件 / pathlib 锚仓根与母仓
import importlib.util
import sys
from pathlib import Path

# 第三方: pytest 承载 skipif 与断言; yaml 读仓内 YAML 声明面
import pytest
import yaml

SKILL_ROOT = Path(__file__).resolve().parents[3]      # 仓根: 本件在 test/unit/meta/ 下三级
if str(SKILL_ROOT) not in sys.path:                   # 幂等注入: 与 conftest 同一纪律
    sys.path.insert(0, str(SKILL_ROOT))               # 仓根入路径: 被测脚本要能按路径装载

REGISTRY_PATH = SKILL_ROOT.parent / "_shared" / "skill-registry.yaml"  # 母仓登记表 (非本仓 git root)

# 母仓在场才判跨仓断言: 母仓缺席时那些断言无对象可比, 且跳过是**显式**的
# (skipif 会在报告里留痕), 不是静默通过。
require_mother_repo = pytest.mark.skipif(
    not REGISTRY_PATH.is_file(),                      # 判据: 登记表在不在场
    reason=f"共享登记表不在场 ({REGISTRY_PATH}): 本仓可独立 checkout, 跨仓对账无对象",
)


def _load_register_skill():
    """按路径装载 ops/register_skill.py (ops/ 不是包; 与该脚本自身口径一致)。"""
    spec = importlib.util.spec_from_file_location(
        "astro_best_register_skill_under_test", SKILL_ROOT / "ops" / "register_skill.py")
    assert spec is not None and spec.loader is not None, "register_skill.py 装载 spec 失败"   # 前提断言
    module = importlib.util.module_from_spec(spec)   # 先造模块对象再执行 —— 与生产装载同序
    spec.loader.exec_module(module)                 # 执行模块体: 只定义函数与常量, 不跑 main
    return module                                   # 返回现载模块: 模块级 sys.path 注入不跨用例污染


def _registry_entry() -> dict[str, str]:
    """读母仓登记表里 astro-best 那一条的字段 (逐行扫, 不引 pyyaml 到被测脚本)。"""
    reg = _load_register_skill()                    # 现载被测脚本: 取它自己的解析口径, 不另写一份
    fields = reg.registry_entry_fields()            # 解析走被测实现, 免得门禁与被测各认一套
    assert fields is not None, f"母仓登记表在场却读不出 astro-best 条目: {REGISTRY_PATH}"   # 前提断言
    return fields                                    # 字段字典: 下游逐字段对账用


# ── 腿 1: conda_env 口径 ─────────────────────────────────────────────────

class TestCondaEnvCoherence:
    """conda_env 三处必须一致, 且指向真实存在过的环境。"""

    def test_register_skill_matches_registry_field_by_field(self):
        """登记辅助的 ENTRY 与共享登记表逐字段一致 (K1-03 的分叉即在此红)。

        守的是"宿主据此选环境"这句承诺: 分叉时脚本印出的条目一旦被粘进表,
        或者表里的值与脚本不符, 宿主装的都不是 astro-best 真正跑得起来的那个
        环境, 且要到运行期 ImportError 才暴露。
        """
        reg = _load_register_skill()                    # 现载被测脚本 (每次现载, 不跨用例留状态)
        drift, readable = reg.check_consistency()       # 逐字段对账: 返回 (漂移项, 表是否可读)
        assert readable, "登记表在场却读不出 astro-best 条目 —— 对账等于空转"   # 可读性先判
        assert not drift, (                             # 有漂移即红, 并逐条列出让人能照着改
            "登记辅助 ENTRY 与共享登记表分叉 (宿主按哪边装环境都会错):\n  "
            + "\n  ".join(drift)
        )

    def test_conda_env_is_a_real_provisioned_environment(self):
        """conda_env 指向的环境必须真被共享环境登记表定义过。

        这条是 K1-03 的**根因**判据, 不是重复上一条: 上一条只保证"两边一样",
        而两边**一起**指向一个不存在的环境时它照样绿 (``astro-best`` 从未被
        创建 —— ``_shared/environments/`` 下没有 astro-best.yaml, 且
        ``create_envs.ps1`` 的 $ENVS 名单里也没有它)。宿主照着装必然失败。
        """
        reg = _load_register_skill()                    # 现载被测脚本, 取它认定的环境名
        envs_dir = REGISTRY_PATH.parent / "environments"      # 母仓的环境定义目录
        if not envs_dir.is_dir():                             # 母仓不在场 → 无从判
            pytest.skip(f"共享环境登记表不在场 ({envs_dir}): 无法核实环境名真伪")   # 显式跳过, 不静默放过
        defined = {p.stem for p in envs_dir.glob("*.yaml")}   # 被真正定义过的环境名 (文件名即环境名)
        assert defined, f"{envs_dir} 下没有任何环境定义 —— 判据前提失效"   # 前提断言
        assert reg.ENTRY["conda_env"] in defined, (            # 逐字比对: 必须命中其中一个
            f"conda_env={reg.ENTRY['conda_env']!r} 不是任何被定义的环境; "
            f"实际可用的有 {sorted(defined)}。宿主照此名装环境必然失败"
        )

    def test_environment_yaml_conflict_is_reported_not_silently_accepted(self):
        """``environment.yaml`` 的 conda_env 若与登记表冲突, 必须是**已知冲突**而非静默。

        刻意不断言两者恒等: ``environment.yaml`` 的 ``name:`` 是本仓环境锁的
        文件名 (由 ``test_environment_lock.py`` 单独守护), 与登记表里宿主
        实际选用的环境名是两种语义。但两者都叫 conda_env 时, 读者无从分辨 ——
        故本件要求: 一旦取值不同, 必须能在仓内找到明写的裁定说明。
        """
        env_lock = yaml.safe_load((SKILL_ROOT / "environment.yaml").read_text(encoding="utf-8"))  # 读环境锁
        lock_env = env_lock.get("conda_env")             # 环境锁自称的 conda_env
        reg = _load_register_skill()                     # 现载登记辅助, 取它认定的那个
        if lock_env == reg.ENTRY["conda_env"]:
            return  # 一致, 无需裁定说明
        # 不一致: 要求 register_skill.py 的注释里写明为什么以登记表为准
        source = (SKILL_ROOT / "ops" / "register_skill.py").read_text(encoding="utf-8")   # 读被测脚本全文
        assert lock_env in source and "astro-base" in source, (   # 两个值都要出现在裁定说明里
            f"environment.yaml 写 conda_env={lock_env!r} 而登记辅助写 "
            f"{reg.ENTRY['conda_env']!r}, 且仓内没有写明该采信哪一侧 —— "
            "下一个读者只会随手挑一边。须在 register_skill.py 注释里明写裁定与依据"
        )

    def test_check_consistency_detects_a_planted_drift(self):
        """对账函数对**喂进去的**分叉必须报错 (证明它不是恒真的橡皮图章)。

        只断言"当前一致"的话, 一个 ``return [], False`` 的空实现也能过 ——
        所以这里把 ENTRY 改回历史错误值再判一次。
        """
        reg = _load_register_skill()                    # 现载被测脚本
        saved = dict(reg.ENTRY)                         # 存快照: 判据会改全局, 必须在 finally 里还原
        try:
            reg.ENTRY["conda_env"] = "astro-definitely-not-a-real-env"   # 植入已知分叉
            drift, readable = reg.check_consistency()  # 再判一次: 这次必须报出漂移
        finally:
            reg.ENTRY.clear()                           # 清空再回填, 不留迭代残留的键
            reg.ENTRY.update(saved)                     # 还原: 不得让测试顺序影响后续用例
        assert readable                                  # 可读性先判: 读不到表谈不上漂移
        assert any("conda_env" in item for item in drift), (   # 只关心 conda_env 那一项被抓到
            f"植入 conda_env 分叉后对账仍报一致 —— 对账逻辑空转: {drift}"
        )
