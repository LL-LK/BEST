# -*- coding: utf-8 -*-
"""区域断点键内容寻址的回归 (P0-02)。

职责: 钉住"决定结果的每一维都进断点键"。旧写法是
``f"region_{catalog}_ra{ra:.2f}_dec{dec:.2f}_r{radius:.0f}"`` —— 只含**粗化后的
几何**, 于是:

- 同一区域只改 ``bands`` / ``output_format`` / ``constraints`` / ``max_rows``
  的多个作业**撞同一个键** (AD2 实测: 9 个不同作业 → 1 个键);
- 几何侧 ``.2f`` / ``.0f`` 还把 ``ra=10.001`` 与 ``10.0``、``r=60.4`` 与
  ``60.0`` 压成同键。

撞键的后果不是报错, 是**静默数据混洗**: 续传时读到别的作业的断点 (含它的
sqlid), 于是把上一个作业的行写进本作业的输出文件。W2 / X5 / AA7 三轮各自
独立命中, X5 另补测出"显式给 job_id 时同样中招"。

顺带钉住 AD2 §5 的两条台账约束:
- **PINNED-01**: ``_constraint_fingerprint`` 的签名不得增删必填参数 (有测试按
  3 个位置参数调它)。本波的修法是**另起同族函数**, 不是给它加参数。
- **PINNED-02**: 键形态一改, 硬编码字面量 ``"region_scr_galah_ra10.00_..."``
  就查不到任何东西 —— 断言 ``is None`` 会**静默退化成恒真**。那条已改为由被测
  函数现场派生 (见 ``test_resume_symmetry.py``), 本文件另有一条守同一件事。

依赖: 全离线 —— 下载器是替身, 只捕获传下去的 ``job_id``, 不发任何请求。
"""
from __future__ import annotations

# 第三方: pytest (参数化与近似比较)
import pytest

# 本地: 区域编排入口 (被测) / 断点键构造点 / 约束模型 (造"改约束"这一维)
from src.download_region import download_region
from src.downloader import _constraint_fingerprint, region_checkpoint_key
from src.models import ColumnConstraint


class _StubDownloader:
    """只捕获 ``download_by_constraints`` 的入参: 本文件测的是键, 不是下载。"""

    def __init__(self) -> None:
        """建一个空的捕获器。"""
        self.captured: dict | None = None  # 最后一次断点路径调用的入参

    def download_by_constraints(self, **kwargs):  # noqa: ANN201 - 替身返回什么都行, 调用方只看键
        """记下入参并返回一个假产物名。"""
        self.captured = kwargs
        return "stub_output.csv"


_BASE = {  # 基准作业: 下面每个用例只改其中一维, 改完的键必须与基准不同
    "ra_center": 10.0,
    "dec_center": 20.0,
    "radius_arcsec": 60.0,
    "catalog": "scr_galah",
    "bands": None,
    "output_format": "csv",
    "max_rows": 50000,
    "resumable": True,  # 走断点路径: 非断点路径压根不生成键
}


def _key_for(**overrides) -> str:
    """按基准作业跑一次 ``download_region``, 返回它算出来的断点键。"""
    params = dict(_BASE)
    params.update(overrides)
    stub = _StubDownloader()
    download_region(stub, **params)
    assert stub.captured is not None, "没走到断点路径: 用例前提失效"
    return stub.captured["job_id"]


class TestEveryResultDeterminingDimensionForks:
    """六个维度各自单独变动都必须换键 —— 修前这六条**全部**返回同一个键。"""

    def test_baseline_key_is_region_prefixed_and_stable(self):
        """同一作业两次提交同键 (原地续传的前提), 且前缀与 constr_ 键空间分开。"""
        assert _key_for() == _key_for()
        assert _key_for().startswith("region_")

    @pytest.mark.parametrize(
        ("dimension", "override"),
        [
            ("bands", {"bands": ["g", "r"]}),                       # 换波段 = 另一次下载
            ("output_format", {"output_format": "tsv"}),             # 换格式 = 另一次下载
            ("max_rows", {"max_rows": 1000}),                        # 换上限 (P0-02 标题的"上限")
            ("ra_micro_delta", {"ra_center": 10.001}),               # 几何差 0.001°: 旧 .2f 压成同键
            ("radius_sub_arcsec", {"radius_arcsec": 60.4}),          # 半径差 0.4″: 旧 .0f 压成同键
            ("dec_micro_delta", {"dec_center": 20.001}),             # 赤纬同理
            ("catalog", {"catalog": "ps1"}),                         # 换星表 (旧键也含它, 作对照)
        ],
    )
    def test_one_dimension_change_changes_the_key(self, dimension, override):
        """逐维验证: 改这一维就必须换键, 否则续传会接错作业。"""
        assert _key_for(**override) != _key_for(), f"{dimension} 变了但键没变"

    def test_constraints_change_changes_the_key(self):
        """改约束也要换键 —— 走 download_region 时约束由 bands 派生, 故直接测键函数。"""
        c1 = [ColumnConstraint(name="rmag", constraint="between", min=10.0, max=15.0)]
        c2 = [ColumnConstraint(name="rmag", constraint="between", min=10.0, max=16.0)]
        k1 = region_checkpoint_key("ps1", 10.0, 20.0, 60.0, None, "csv", c1, 50000)
        k2 = region_checkpoint_key("ps1", 10.0, 20.0, 60.0, None, "csv", c2, 50000)
        assert k1 != k2, "只有约束上界不同, 键却相同 ⇒ 续传会读到别的约束集的断点"

    def test_band_order_is_part_of_the_key(self):
        """波段顺序不同即不同作业: 键按列表原序入指纹, 不排序。"""
        k1 = region_checkpoint_key("ps1", 10.0, 20.0, 60.0, ["g", "r"], "csv", [], 50000)
        k2 = region_checkpoint_key("ps1", 10.0, 20.0, 60.0, ["r", "g"], "csv", [], 50000)
        assert k1 != k2


class TestGroupAndMemberKeySpaces:
    """``catalog="std"`` 组键与单表键不得互撞, 成员键仍按 ``{job_id}_{member}`` 派生。"""

    def test_group_key_differs_from_single_table_key(self):
        """同几何下组键与单表键必须不同: 相同会让组断点与单表断点互相覆盖。"""
        group = region_checkpoint_key("std", 10.0, 20.0, 60.0, None, "csv", [], 50000)
        single = region_checkpoint_key("ps1", 10.0, 20.0, 60.0, None, "csv", [], 50000)
        assert group != single

    def test_group_name_does_not_crash_key_derivation(self):
        """``std`` 是导航组、不是可查询星表: ``resolve_catalog("std")`` 会抛 ValueError。

        组级断点键必须能算出来。这条守的是一个**只有在不给显式 job_id 时才走到**
        的分支 —— 既有组测试全都传了 ``job_id=``, 于是 ``job_id or <算键>`` 短路,
        算键那半从来没被执行过, 崩溃就一直藏着。
        """
        key = region_checkpoint_key("std", 10.0, 20.0, 60.0, None, "csv", [], 50000)
        assert key.startswith("region_")

    def test_group_key_differs_from_every_member_key(self):
        """组键不得与任一成员表的键相同: 否则组断点会与成员断点互相覆盖。"""
        group = region_checkpoint_key("std", 10.0, 20.0, 60.0, None, "csv", [], 50000)
        members = {
            region_checkpoint_key(m, 10.0, 20.0, 60.0, None, "csv", [], 50000)
            for m in ("scr_galah", "scr_lamost", "xpsp")
        }
        assert len(members) == 3, "三个成员表的键必须互不相同"
        assert group not in members

    def test_old_hardcoded_region_key_no_longer_generated(self):
        """PINNED-02 的正向版: 旧的粗粒度字面量键必须**由被测函数派生**才查得到。

        ``test_resume_symmetry.py`` 原先硬编码这个串并断言 ``load(...) is None``;
        键形态一改它就恒真 (查一个再也不会被生成的串)。这里改成: 先证明该串
        确实**不等于**任何真实生成的键, 于是那条 ``is None`` 断言守的东西是
        "旧键没复活", 而不是"我拼的串碰巧不存在"。
        """
        legacy = "region_scr_galah_ra10.00_dec20.00_r60"
        assert _key_for() != legacy, "旧粗粒度键复活了"
        assert legacy != region_checkpoint_key(  # 且它对任何输入都不再是合法键
            "scr_galah", 10.0, 20.0, 60.0, None, "csv", [], 50000)


class TestConstraintFingerprintSignatureUnchanged:
    """PINNED-01: ``_constraint_fingerprint`` 仍按 3 个位置参数可用。"""

    def test_three_positional_args_still_work(self):
        """本波不得给它加必填参数 —— 加了这条与 audit_round 那条都会 TypeError。"""
        first = [ColumnConstraint(name="rmag", constraint="between", min=10.0, max=15.0)]
        key = _constraint_fingerprint("ps1", first, "csv")  # 恰好 3 个位置参数
        assert key.startswith("constr_")
        assert key == _constraint_fingerprint("ps1", list(first), "csv")  # 与列表对象身份无关

    def test_region_and_constraint_key_spaces_do_not_collide(self):
        """同一星表同一约束下, 区域键与约束键前缀不同 ⇒ 不会互接断点。"""
        first = [ColumnConstraint(name="rmag", constraint="between", min=10.0, max=15.0)]
        assert not region_checkpoint_key(
            "ps1", 10.0, 20.0, 60.0, None, "csv", first, 50000
        ).startswith("constr_")


class TestSingleValueConstraintsAreObserved:
    """N4: ``value=`` 这条路此前**零观测面**。

    全仓普查 (321 个 .py、36 处 ``ColumnConstraint``) 的结论: ``value=`` 只在 6 处
    **产品代码**被传, 测试树里仅 1 处, 而那一处测的是"传死参数抛 ValueError",
    **根本走不到断点键**。于是 ``_constraint_tuples`` 里的 ``value`` 槽位是一次
    只有实现、没有断言的代码: 把 ``str(getattr(c, "value", ""))`` 删掉, ``ra>10``
    与 ``ra>20`` 会算出**同一个断点键**, 续传时静默读到别的作业的 sqlid (D1 级
    静默事故), 而全量测试仍全绿 —— 这正是 ``test_region_checkpoint_key.py``
    原有 16 条全绿却没覆盖到的那一面。

    本类把那条路接上: 单值约束必须进键, 且值不同 ⇒ 键必不同。
    """

    @staticmethod
    def _key(*constraints):
        """同一几何/波段/格式/上限, 只换约束 —— 键的差异只能来自约束本身。"""
        return region_checkpoint_key("ps1", 180.0, 30.0, 60.0, None, "csv",
                                     list(constraints), 50000)

    def test_different_single_value_gives_different_key(self):
        """``ra>10`` 与 ``ra>20`` 必须是两个键 (N4 的核心断言)。"""
        ra_gt_10 = self._key(ColumnConstraint(name="ps1_ra", constraint="greater", value=10))
        ra_gt_20 = self._key(ColumnConstraint(name="ps1_ra", constraint="greater", value=20))
        assert ra_gt_10 != ra_gt_20, (
            f"单值约束的 value 没进断点键: 两者同为 {ra_gt_10} —— "
            "续传会静默读到另一个作业的 sqlid")

    def test_operation_type_also_enters_the_key(self):
        """同列同值不同操作 (greater/less) 也是两次不同的下载。"""
        assert self._key(ColumnConstraint(name="ps1_ra", constraint="greater", value=10)) != \
            self._key(ColumnConstraint(name="ps1_ra", constraint="less", value=10))

    def test_min_max_still_separated(self):
        """区间侧原有覆盖保留: 换上界必须换键。"""
        assert self._key(ColumnConstraint(name="ps1_ra", constraint="between", min=10, max=20)) != \
            self._key(ColumnConstraint(name="ps1_ra", constraint="between", min=10, max=30))

    def test_missing_value_is_not_silently_equal_to_a_set_value(self):
        """没给 value 与给了 value 不能同键 —— 缺字段退空串是兜底, 不是"两者相同"。"""
        assert self._key(ColumnConstraint(name="ps1_ra", constraint="greater")) != \
            self._key(ColumnConstraint(name="ps1_ra", constraint="greater", value=""))

    def test_value_is_read_from_dict_style_callers_too(self):
        """字段兼容 dict 与属性对象两种写法: 属性序不同的对象也要算出同一个键。"""
        by_kw = ColumnConstraint(name="ps1_ra", constraint="greater", value=10)
        by_pos = ColumnConstraint("ps1_ra", "greater", None, None, 10)  # 位置写法, 字段序完全不同
        assert self._key(by_kw) == self._key(by_pos), (
            "对象字段序不该影响键: _constraint_tuples 的显式取值就是为此存在的")
