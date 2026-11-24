# -*- coding: utf-8 -*-
"""``contracts/envelope.contract.yaml`` ↔ ``src/provenance.py`` 的**双向对齐**门禁。

为什么要有这个门禁 (H5-01 / H5-03): 契约与代码各写一份, 就会漂移, 而且漂移
的方向恒为"契约越说越漂亮, 代码一动不动"。H5-01 实测的那一处:

  - 契约声明 ``astro-data-envelope-v2``, 唯一实现 ``src/provenance.py:195``
    固定发 ``astro-envelope-v1``;
  - v2 独有的 9 个字段 (pipeline_id / stage / artifacts / metrics / workflow_id /
    data_envelope_ref / llm_scientific_assessment / checkpoint / human_review)
    在 ``src/`` 内**零实现**;
  - 契约原引的 ``_shared/skill-engine/pipeline-contract.md`` 与脚注里的
    ``scripts/refactor/materialize_contracts.py`` 在本仓**都不存在** —— v2 是
    从一份不在仓内的外部计划物化来的, 从未接线;
  - 而 input/output/provenance 三份契约 + io-contract.md + architecture.md +
    implementation-plan.md 共 8 处都写 v1。

危害是"下游按契约选解析器会直接不匹配": 照契约写的消费方取不到字段。这不是
措辞问题, 是契约在骗读者。

所以本门禁断言的不是"契约写了什么", 而是**契约字段集 == 代码实跑输出**。
判据直接取 ``build_envelope`` 的返回值, 不抄一份字面量 —— 抄字面量的话,
代码改了字面量也跟着改, 又变成各写一份。

对照纪律: 每条"必须相等"都配一条"不该被误伤"的反向用例, 否则把契约清空
也能满足 ``相等``。
"""
from __future__ import annotations

# 标准库: sys 路径锚定 / pathlib
import sys
from pathlib import Path
from typing import Any

# 第三方: pytest (parametrize) / PyYAML 解析契约
import pytest
import yaml

SKILL_ROOT = Path(__file__).resolve().parents[3]  # 仓根: 本件在 test/unit/meta/ 下三级
if str(SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILL_ROOT))

from src.provenance import build_envelope  # noqa: E402  (路径锚定之后才能导入)

CONTRACTS = SKILL_ROOT / "contracts"  # 契约目录

# v2 独有、本仓零实现的字段名。列出来是为了**反向钉死**: 哪天有人把它们
# 塞回契约的 data_envelope, 下面那条用例立刻红 —— 那等于又开始吹一个不存在的
# 版本, 正是 H5-01 的病因。
V2_ONLY_FIELDS = (
    "pipeline_id", "stage", "artifacts", "metrics", "workflow_id",
    "data_envelope_ref", "llm_scientific_assessment", "checkpoint", "human_review",
)


def _load(name: str) -> dict[str, Any]:
    """读一份契约 YAML (utf-8, 容忍 Windows BOM)。"""
    return yaml.safe_load((CONTRACTS / name).read_text(encoding="utf-8-sig"))  # utf-8-sig: 容忍 Windows BOM


def _real_envelope() -> dict[str, Any]:
    """造一条**离线确定**的真实信封当判据基准。

    显式给 ``identity`` 是必须的: 缺省会回落 TokenStore 读 ``~/.astro-best/``,
    缓存里若有有效令牌还会真发一次 profile 网络请求 —— 门禁测试绝不能联网,
    也不能让结果依赖开发机上有没有登录过。
    """
    return build_envelope(
        {"rows": [{"ra": 180.0, "dec": 30.0}]},
        status="ready",
        session_id="sess-alignment",                        # 固定值: 判据要比字段集, 不是随机 id
        identity={"umtId": "U1", "ldap_id": "L1", "name": "N"},   # 非空才挂 identity 块: 契约要登记它
    )


class TestDataEnvelopeMatchesImplementation:
    """契约声明的 data_envelope 必须与 ``build_envelope`` 的实跑输出逐字段相等。"""

    def test_top_level_field_set_is_equal(self):
        """顶层键集合相等 —— 少一个消费方取不到, 多一个就是契约在吹。"""
        declared = set(_load("envelope.contract.yaml")["data_envelope"])  # 契约声明的键集
        # data_hash_preimage 是**算法说明**而非信封字段, 契约需要它人才算得清
        # 哈希口径, 代码里当然没有对应键 —— 显式剔掉再比, 免得"说明漏了"与
        # "字段漂了"两件事混在一条断言里。
        declared.discard("data_hash_preimage")  # 剔掉算法说明, 只比信封字段
        assert declared == set(_real_envelope()), (
            "契约 data_envelope 的字段集与 build_envelope 实跑输出不等 —— "
            f"契约多: {sorted(declared - set(_real_envelope()))}; "
            f"代码多: {sorted(set(_real_envelope()) - declared)}"
        )

    def test_schema_name_is_the_one_the_code_emits(self):
        """schema 名逐字相等, 且必须是 v1 —— 换名等于让跨 skill 传递全断。"""
        real = _real_envelope()["schema"]                  # 代码实发值
        declared = _load("envelope.contract.yaml")["data_envelope"]["schema"]  # 契约声明值
        assert declared == real == "astro-envelope-v1", (
            f"契约声明 {declared!r}, 代码实发 {real!r}; 现行线协议名是 astro-envelope-v1"
        )

    def test_v2_only_fields_are_absent_from_the_normative_block(self):
        """v2 独有字段不得回到 data_envelope —— 那是 H5-01 病因的复发。"""
        declared = _load("envelope.contract.yaml")["data_envelope"]  # 只看规范块
        leaked = [f for f in V2_ONLY_FIELDS if f in declared]
        assert not leaked, (
            f"data_envelope 又声明了本仓零实现的 v2 字段 {leaked} —— "
            "要么接线实现, 要么别在规范块里声明 (决策信封请放 decision_envelope)"
        )

    def test_provenance_block_matches(self):
        """provenance 子块的键集相等 (含仅授权时出现的 identity)。"""
        real = set(_real_envelope()["provenance"])          # 代码侧键集
        declared = set(_load("envelope.contract.yaml")["data_envelope"]["provenance"])  # 契约侧键集
        assert declared == real, (
            f"provenance 字段集不等 —— 契约多: {sorted(declared - real)}; "
            f"代码多: {sorted(real - declared)}"
        )

    def test_lineage_block_matches(self):
        """lineage 子块的键集相等 —— 血缘链漏一个键就断一环回溯。"""
        real = set(_real_envelope()["lineage"])             # 代码侧键集
        declared = set(_load("envelope.contract.yaml")["data_envelope"]["lineage"])  # 契约侧键集
        assert declared == real, (
            f"lineage 字段集不等 —— 契约多: {sorted(declared - real)}; 代码多: {sorted(real - declared)}"
        )


class TestSiblingContractsAgreeOnEnvelopeName:
    """四份契约对信封名的说法必须一致 —— 契约之间自相矛盾等于没有契约。"""

    @pytest.mark.parametrize(
        "name", ["input.contract.yaml", "output.contract.yaml", "provenance.contract.yaml"]
    )
    def test_sibling_declares_v1(self, name: str):
        """input/output/provenance 三份都声明 ``envelope: astro-envelope-v1``。"""
        assert _load(name)["envelope"] == "astro-envelope-v1", (
            f"{name} 的 envelope 名与代码实发值不一致"
        )


class TestDecisionEnvelopeIsDeclaredUnemitted:
    """决策信封必须**明说不产出** —— 不得让消费方等一个永不到来的信封。"""

    def test_emitted_flag_is_false(self):
        """``emitted: false`` 是本仓的实况 (L1 确定性数据流, 0% LLM)。"""
        assert _load("envelope.contract.yaml")["decision_envelope"]["emitted"] is False, (
            "本 skill 不产决策信封 (pipeline-stage.contract.yaml 声明 "
            "emit_decision_envelope: false); 契约不得改口说会产出"
        )

    def test_pipeline_stage_contract_agrees(self):
        """两份契约必须对同一件事给同一个答案 (单一事实源)。"""
        stage = _load("pipeline-stage.contract.yaml")      # 另一份契约的说法
        assert stage["degradation"]["emit_decision_envelope"] is False, (
            "pipeline-stage.contract.yaml 与 envelope.contract.yaml 对决策信封的说法冲突"
        )


class TestInputValidationCodeIsLive:
    """``input.contract.yaml`` 的 error_code 必须指向一个**真在发**的码 (H5-02)。

    原值 ``E101_INVALID_INPUT`` 是 2026-09-28 重命名前的旧名, 早已退役: 全仓
    唯一残留就是那一行与 error-codes 契约里的改名说明注释, 代码侧零引用。
    照它实现校验会去找一个永不出现的码。
    """

    def test_error_code_matches_error_codes_contract(self):
        """输入契约引用的码必须是错误码真源 (BEST_1001.code) 里的那个。"""
        declared = _load("input.contract.yaml")["validation"]["error_code"]  # 引用方
        truth = _load("error-codes.contract.yaml")["codes"]["BEST_1001"]["code"]  # 真源
        assert declared == truth, (
            f"input.contract.yaml 引用的 {declared!r} 与错误码真源 {truth!r} 不一致"
        )

    def test_error_code_is_actually_emitted_by_code(self):
        """反向钉死: 该码必须真在 ``src/`` 里被定义, 不能是另一个空头引用。"""
        declared = _load("input.contract.yaml")["validation"]["error_code"]
        sources = (SKILL_ROOT / "src" / "ai_tools.py").read_text(encoding="utf-8")
        protocols = (SKILL_ROOT / "src" / "protocol.py").read_text(encoding="utf-8")
        assert f'{declared} = "{declared}"' in sources or f'{declared} = "{declared}"' in protocols, (
            f"{declared} 在 src/ai_tools.py 与 src/protocol.py 里都没有定义 —— "
            "契约引用了一个代码侧不存在的错误码"
        )
