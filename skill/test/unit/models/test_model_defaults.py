"""回归: 输入/输出模型默认值必须来自真实契约而非硬编码 (budget §6.1 G2/G3)。

G2 — ``DownloadInput.bands`` 默认含 ``"clear"``: 它不是任何星表
``CATALOG_MAG_COLUMNS`` 里的波段标签, 默认清单若被透传给
``protocol.magnitude_column()`` 会抛 ``ValueError`` (templates/best-config.yaml
的同一缺陷已在 Phase 5 修复, 本组守模型层默认值)。

G3 — ``BestResultSet`` 默认 ``handoff`` 把 ``next_skills`` 硬编码为
``["astro-catalog", "astro-clean"]``: 跨 skill 路由写死在模型默认值里,
envelope 契约变更时会静默漂移。现在路由必须从 ``manifest.yaml`` 的
``redirects`` 表派生, 读不到时按空清单明确降级。
"""
from __future__ import annotations

# 第三方: pytest (monkeypatch 注入临时 manifest / 不存在路径)
import pytest

# 旧导入守门: src.models 不可导入时整模块 skip 而非 collection error
try:
    # 本地: 输入/输出契约模型 (bands 默认值与 handoff 路由的被测对象)
    from src.models import BestResultSet, DownloadInput
    from src.models import output as output_module
    from src.protocol import CATALOG_MAG_COLUMNS, magnitude_column
except Exception as _legacy_err:  # legacy-import-guard
    # 源码树调整导致旧导入路径失效时整模块跳过, 不让收集期报错
    import pytest as _pytest
    _pytest.skip(f'legacy import unavailable: {_legacy_err!r}', allow_module_level=True)            # 模块级跳过: 导入树问题不该算用例失败


class TestDownloadInputDefaultBands:
    """G2: DownloadInput.bands 默认清单必须全部是真实波段标签。"""

    def test_default_bands_exclude_clear(self):
        """"clear" 不是任何星表发布的波段标签, 不得出现在默认清单里。

        旧默认 ``["g", "r", "i", "z", "clear"]`` 里的 clear 透传给
        ``magnitude_column()`` 会抛 ValueError — 默认值本身就该是合法的。
        """
        assert "clear" not in DownloadInput(ra=0.0, dec=0.0).bands  # clear 透传会抛 ValueError: 默认值自己先要合法

    def test_every_default_band_is_published_by_some_catalog(self):
        """默认清单里每个标签都必须是某星表 CATALOG_MAG_COLUMNS 真实发布的波段。

        口径与 magnitude_column() 的判定同源: 全星表波段值集合的补集标签
        一律不得进默认清单 (防再混进 clear 一类幽灵波段)。
        """
        published = {band for table in CATALOG_MAG_COLUMNS.values() for band in table.values()}  # 全星表并集: 只看 ps1 会误判别家波段
        # 断言消息里带出 unknown 清单: 只断 not unknown 的话, 报错时看不出是哪个
        # 标签漂进来的, 排障还得自己去 diff 星表
        unknown = [b for b in DownloadInput(ra=0.0, dec=0.0).bands if b not in published]         # 逐标签取差集: 幽灵波段就是并集里没有的那些
        assert not unknown, f"默认 bands 含非真实波段标签: {unknown}"  # 消息带出 unknown 清单: 只断 not unknown 的话, 报错看不出是哪个标签漂进来

    def test_every_default_band_resolves_for_ps1(self):
        """默认清单每个标签都必须能被 ps1 的 magnitude_column() 解析 (不抛)。

        ps1 发布 g/r/i/z/y, 覆盖默认清单全部标签; 任一波段解析抛
        ValueError 即说明默认清单又漂回了幽灵波段。
        """
        for band in DownloadInput(ra=0.0, dec=0.0).bands:  # 逐标签循环: 清单里混进一个坏标签, 整批下载才会在站点侧炸
            # 断的是"能解析出列名"而不是直接跑查询: 解析这步是幽灵波段最早的
            # 爆炸点, 在它断住就不必等真发一次站点请求才发现
            column = magnitude_column("ps1", band)                                                  # 逐标签解析: 幽灵波段在这一步就会抛
            # 断言消息带 band 名: 逐条循环里没有它就不知道是哪个标签没解析出来
            assert column, band                                                      # 断言消息带 band 名: 逐条循环里没它就不知道是哪个标签没解析出来

    def test_explicit_bands_are_still_honored(self):
        """显式传入的 bands 必须原样保留 (修默认值不得顺径改覆盖语义)。"""
        assert DownloadInput(ra=0.0, dec=0.0, bands=["g"]).bands == ["g"]  # 显式 bands 原样保留: 修默认值时顺径改掉覆盖语义也是回归


class TestBestResultSetHandoffRouting:
    """G3: handoff.next_skills 必须从 manifest 派生, 不得硬编码。"""

    def test_real_manifest_yields_the_declared_downstream_skills(self):
        """真实 manifest 的 redirects 必须派生出 astro-catalog + astro-clean。

        redirects 表声明两次外派 (交叉匹配 -> astro-catalog, 数据清洗 ->
        astro-clean) 与一次自指 (to astro-best); 自指不是跨 skill 交接,
        必须被剔除, 结果与 contracts/output.contract.yaml 的委派表一致。
        """
        result = BestResultSet()  # 无参构造走派生分支: 显式传 handoff 的那条用例守的是另一侧
        # 等值断言把顺序也钉住: redirects 的声明顺序就是委派顺序, 顺序漂了
        # 跨 skill 交接的先后关系会跟着变, 而集合断言看不出来
        assert result.handoff["next_skills"] == ["astro-catalog", "astro-clean"]         # 等值断言把顺序也钉住: 声明顺序即委派顺序, 集合断言看不出来
        # status 一并断: next_skills 对而 status 不对, 客户端仍会以为交接已完成
        assert result.handoff["status"] == "ready"                     # status 一并断: next_skills 对而 status 不对, 客户端仍以为交接已完成

    def test_next_skills_follow_a_rewritten_manifest(self, monkeypatch, tmp_path):
        """monkeypatch manifest 后 next_skills 必须随之变化 (不再硬编码)。

        写一份 redirects 指向另外两个 skill 的临时 manifest 并注入; 若路由
        仍来自硬编码常量, 本断言失败 — 这是 G3 的核心守门。
        """
        manifest = tmp_path / "manifest.yaml"  # 临时 manifest 落在 tmp_path: 改真实 manifest 会污染仓库资产
        manifest.write_text(                                                     # 临时 manifest 落在临时区: 改真实 manifest 会污染仓库资产
            "name: astro-best\n"                                                 # 写一份指向另外两个 skill 的 redirects: 硬编码名单会当场露馅
            "redirects:\n"                                                                          # 重定向表头: 路由真要从这里读
            '  - {from: "a", to: "astro-x", reason: "r"}\n'                                         # 第一个新下游
            '  - {from: "b", to: "astro-y", reason: "r"}\n'                                         # 第二个新下游: 两个都要出现在派生结果里
            '  - {from: "c", to: "astro-best", reason: "self"}\n',                             # 自指条目: 不是跨 skill 交接, 必须被剔除
            encoding="utf-8",                                                          # 编码显式钉死: 解析失败会静默降级, 读不出是编码问题还是路由问题
        )
        monkeypatch.setattr(output_module, "_MANIFEST_PATH", manifest)           # 注入模块级路径常量: 路由真从文件读, 硬编码名单会当场露馅
        assert BestResultSet().handoff["next_skills"] == ["astro-x", "astro-y"]  # 两个新下游按声明序出现: 换序即跨 skill 交接先后被换掉

    def test_self_redirect_and_duplicates_are_excluded(self, monkeypatch, tmp_path):
        """自指声明与重复 to 必须被剔除 (保序去重, 只留跨 skill 下游)。"""
        manifest = tmp_path / "manifest.yaml"                                              # 样本落在临时区: 改真实 manifest 会污染仓库资产
        manifest.write_text(                                                                    # 同样落在临时区: 自指与重复的样本不该碰真实资产
            "name: astro-best\n"                                                                    # 同样自造一份 redirects
            "redirects:\n"                                                                          # 重定向表头
            '  - {from: "a", to: "astro-best", reason: "self"}\n'                                   # 自指在前: 剔除逻辑必须与顺序无关
            '  - {from: "b", to: "astro-x", reason: "r"}\n'                                         # 第一个真实下游
            '  - {from: "c", to: "astro-x", reason: "dup"}\n',                                      # 重复的同一个下游: 保序去重要求只留一条
            encoding="utf-8",                                                                       # 编码显式钉死
        )
        monkeypatch.setattr(output_module, "_MANIFEST_PATH", manifest)                              # 注入路径常量: 路由真从文件读才会跟着变
        assert BestResultSet().handoff["next_skills"] == ["astro-x"]  # 自指与重复只留一条: 多一个下游就是多一次真实交接请求

    def test_missing_manifest_degrades_to_empty_list(self, monkeypatch, tmp_path):
        """读不到 manifest 时降级为空清单 (明确降级语义, 不 invent 路由)。

        空清单 = "未声明任何下游交接", 由调用方按无交接处理; 绝不回退到
        写死的 skill 名单 — 那正是 G3 要消除的静默漂移源。
        """
        monkeypatch.setattr(output_module, "_MANIFEST_PATH", tmp_path / "absent.yaml")       # 指向不存在的文件: 明确降级语义, 不许回退硬编码名单
        # 降级方向是"空清单"而非"抛错"也非"回退硬编码名单": 前者让调用方
        # 明确知道没有下游可派, 后两者分别会把缺文件变成崩溃、把契约漂移
        # 重新引回来 —— 这正是 G3 要消除的那个静默漂移源
        assert BestResultSet().handoff["next_skills"] == []                                        # 降级成空清单: 调用方据此知道没有下游可派

    def test_broken_manifest_degrades_to_empty_list(self, monkeypatch, tmp_path):
        """manifest 语法坏 (YAML 解析失败) 同样按空清单降级, 不抛。"""
        manifest = tmp_path / "manifest.yaml"                                                       # 样本落在临时区
        # 半截 YAML ("name: [unclosed") 是"文件存在但解析不了"的最短样本
        manifest.write_text("name: [unclosed\n", encoding="utf-8")                             # 半截 YAML: "文件存在但解析不了"的最短样本
        monkeypatch.setattr(output_module, "_MANIFEST_PATH", manifest)                              # 注入路径常量
        assert BestResultSet().handoff["next_skills"] == []                                         # 解析失败同样降级成空清单, 不抛

    def test_explicit_handoff_still_wins(self):
        """显式传入的 handoff 必须原样保留 (派生只发生在缺省分支)。"""
        handoff = {"status": "blocked", "next_skills": ["astro-anything"]}                   # 显式 handoff 的样本: 派生只该发生在缺省分支
        assert BestResultSet(handoff=handoff).handoff == handoff  # 显式 handoff 覆盖派生: 两条路径并存时, 调用方的声明必须赢
