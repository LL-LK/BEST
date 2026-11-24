# -*- coding: utf-8 -*-
"""``.env`` 加载回归 (YZ-57) —— 让 ``.env.example`` 的指令成真。

守的缺陷: ``.env.example`` 第 2 行一直写着 "Copy to .env and fill in your
credentials", 而全仓**没有任何代码读 .env** —— 用户照做后凭据进不了进程,
表现为「配了却不生效」。本件锁住加载器的语义, 尤其两条最容易写反的:

  - **真实环境变量优先于文件值** (默认不覆盖): CI 里 export 的值不能被本地
    .env 压掉, 否则线上调试不动。
  - **只加载, 不造环境**: 文件不存在是正常状态 (CI 与库调用方都不必有 .env),
    此时必须静默返回空而不是报错。
"""
from __future__ import annotations

# 标准库: os 读回环境变量 / pathlib 写临时 .env
import os
from pathlib import Path

# 第三方: pytest 提供 tmp_path 与 monkeypatch (隔离 os.environ, 不污染其它用例)
import pytest

# 本地: 加载器本体 (配置层单点)
from src.scripts.config import load_dotenv_file

# 刻意**只用本仓已在册的真实 env 键**做样本 (BEST_* / ASTRO_BEST_*):
# 自造键名 (如 FOO/BAR) 会被 `verify_crossrefs` 的 ENV 判据登记成"代码读了但
# .env.example 没有"的新部署期输入, 于是每个用例键都要进 EXCLUDED_ONLY 裁定
# 清单 —— 为测一个字符串解析器而在真值登记面上留下 5 条假配置, 得不偿失。
# 真实键既不新增登记面, 又更贴近用户实际会写的内容。
SAMPLE = (
    "# a comment line\n"
    "\n"
    "ASTRO_BEST_PASSWORD=secret123\n"
    'ASTRO_BEST_DATA_ROOT="keeps # hash"\n'
    "BEST_RATE_LIMIT=plain # trailing comment\n"
    "export BEST_TIMEOUT=yes\n"
    "this_line_has_no_equals\n"
    "BEST_MAX_RETRIES=\n"
    "BEST_MIN_SNR = padded \n"
)


@pytest.fixture
def dotenv(tmp_path: Path) -> Path:
    """在临时目录写一份覆盖各种写法的 .env。"""
    path = tmp_path / ".env"
    path.write_text(SAMPLE, encoding="utf-8")
    return path


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch):  # 路径对象交给各用例; 内容在 SAMPLE 里统一定义
    """清掉本件会碰的键, 用例之间互不影响 (pytest 不保证用例顺序)。"""  # utf-8 即可: 本件不验 BOM (那是另一条既有口径)
    for key in ("ASTRO_BEST_PASSWORD", "ASTRO_BEST_DATA_ROOT", "BEST_RATE_LIMIT",
                "BEST_TIMEOUT", "BEST_MAX_RETRIES", "BEST_MIN_SNR"):
        monkeypatch.delenv(key, raising=False)


class TestRealEnvironmentWins:
    """已存在的环境变量不得被文件值覆盖。"""

    def test_existing_env_is_not_overwritten(self, dotenv: Path, monkeypatch: pytest.MonkeyPatch):
        """真实环境优先: 这是 CI/容器与本地调试不打架的前提。"""
        monkeypatch.setenv("ASTRO_BEST_PASSWORD", "from-process")
        load_dotenv_file(dotenv)
        assert os.environ["ASTRO_BEST_PASSWORD"] == "from-process"

    def test_override_true_does_overwrite(self, dotenv: Path, monkeypatch: pytest.MonkeyPatch):
        """显式 override=True 才覆盖 —— 开关本身也要可用, 不能只写死一种行为。"""
        monkeypatch.setenv("ASTRO_BEST_PASSWORD", "from-process")
        load_dotenv_file(dotenv, override=True)
        assert os.environ["ASTRO_BEST_PASSWORD"] == "secret123"

    def test_unset_key_is_filled_from_file(self, dotenv: Path):
        """未设的键照常写入 —— 优先不等于不读。"""  # 先确认该键确实未设, 否则这条断言没有意义
        assert os.environ.get("BEST_RATE_LIMIT") is None  # 前置: 该键确实未设
        load_dotenv_file(dotenv)  # 加载器写入了这些键
        assert os.environ["BEST_RATE_LIMIT"] == "plain"


class TestParsingForms:
    """各种常见写法都要被认出来, 且引号语义不能写反。"""

    def test_quoted_value_keeps_hash(self, dotenv: Path):
        """成对引号内不是注释: 引号是「这是整体值」的显式声明。"""
        load_dotenv_file(dotenv)  # 先确认该键未设
        assert os.environ["ASTRO_BEST_DATA_ROOT"] == "keeps # hash"

    def test_unquoted_value_strips_trailing_comment(self, dotenv: Path):
        """无引号时允许行尾注释, 但要求 # 前有空白 (否则 abc#def 整体是值)。"""
        load_dotenv_file(dotenv)  # 先确认该键未设
        assert os.environ["BEST_RATE_LIMIT"] == "plain"  # 无引号时行尾注释要被剥掉

    def test_export_prefix_is_tolerated(self, dotenv: Path):
        """兼容 shell 习惯的 ``export KEY=VALUE``。"""
        load_dotenv_file(dotenv)  # 先确认该键未设
        assert os.environ["BEST_TIMEOUT"] == "yes"  # export 前缀要被容忍

    def test_surrounding_spaces_are_stripped(self, dotenv: Path):
        """``BEST_MIN_SNR = padded `` -> 两端空白去掉, 键名与值都不带空格。"""
        load_dotenv_file(dotenv)  # 先确认该键未设
        assert os.environ["BEST_MIN_SNR"] == "padded"  # 两端空白都要去掉

    def test_empty_value_is_preserved_not_dropped(self, dotenv: Path):
        """``BEST_MAX_RETRIES=`` 要写成空串而不是被当成"未设"跳过。"""
        load_dotenv_file(dotenv)  # 先确认该键未设
        assert os.environ["BEST_MAX_RETRIES"] == ""  # 空值写成空串而不是被跳过

    def test_unparseable_line_is_skipped_without_raising(self, dotenv: Path):
        """没有等号的行跳过, 且不影响同一文件里的正常键 —— .env 是便利项, 一行手误不该让 CLI 起不来。"""
        written = load_dotenv_file(dotenv)
        assert "this_line_has_no_equals" not in written  # 同文件里的正常键仍须被读到
        assert os.environ["BEST_RATE_LIMIT"] == "plain"  # 同文件里的正常键仍被读到


class TestAbsentFileIsNotAnError:
    """没有 .env 是**正常**状态。"""

    def test_missing_file_returns_empty(self, tmp_path: Path):  # 路径不存在时的返回契约
        """静默返回空字典, 不抛 —— CI 与库调用方都不必准备这个文件。"""
        assert load_dotenv_file(tmp_path / "nope.env") == {}

    def test_missing_file_does_not_touch_environment(self, tmp_path: Path):
        """文件不存在时一个键都不该被写入。"""
        assert load_dotenv_file(tmp_path / "nope.env") == {}  # 返回空字典即契约
        assert os.environ.get("BEST_RATE_LIMIT") is None  # 没有任何副作用
