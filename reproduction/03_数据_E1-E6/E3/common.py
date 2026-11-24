"""E3 本轮实验公共载体：路径、配置、脱敏、原子写入与指纹。"""
from __future__ import annotations

# 标准库：只读解析环境文件，避免执行配置中的命令。
import hashlib
import json
import os
import re
import shlex
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SECRETS: list[str] = []
PILOT = ("E3-A01", "E3-A02", "E3-A03", "E3-D01", "E3-D02", "E3-G01", "E3-G02")
GROUPS = ("S-A", "S-B")
REDLINES = ("fatal_number", "static_as_lc_conclusion", "sentinel_calculation",
            "identity_misattribution", "absence_as_nonexistence", "unmarked_as_constant")


def now() -> str:
    """返回上海时区时间，用于实验批次和记录。"""
    return datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")


def encode(value) -> str:
    """生成可重算指纹的规范化 JSON，拒绝非有限浮点。"""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def fingerprint(value) -> str:
    """为字符串或 JSON 数据生成 SHA-256 指纹。"""
    text = value if isinstance(value, str) else encode(value)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def redact(value):
    """递归脱敏已配置密钥，防止服务商把密钥回显到错误响应。"""
    if isinstance(value, str):
        for secret in SECRETS:
            value = value.replace(secret, "[REDACTED]")
        return value
    if isinstance(value, dict):
        return {redact(k): redact(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(v) for v in value]
    return value


def write_json(path: Path, value) -> None:
    """原子写入 JSON；目录和文件仅当前用户可访问。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(redact(value), ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    temp.chmod(0o600)
    temp.replace(path)


def read_json(path: Path):
    """从实验产物读取 JSON。"""
    return json.loads(path.read_text(encoding="utf-8"))


def parse_env(path: Path) -> dict:
    """解析简单 KEY=value，不做变量替换或命令执行。"""
    result = {}
    if not path.exists():
        return result
    for index, line in enumerate(path.read_text().splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = re.fullmatch(r"(E3_[A-Z_]+)\s*=\s*(.*)", line)
        if not match:
            raise ValueError(f"环境文件第 {index} 行格式错误")
        key, text = match.groups()
        tokens = shlex.split(text, comments=True)
        if len(tokens) > 1 or key in result:
            raise ValueError(f"环境文件第 {index} 行有重复键或未引用空格")
        result[key] = tokens[0] if tokens else ""
    return result


def config(path: Path = HERE / ".env") -> tuple[dict, list[str]]:
    """读取配置；只返回缺项名称，不返回密钥内容。"""
    values = parse_env(path)
    for key in ("E3_API_BASE_URL", "E3_API_STYLE", "E3_API_KEY", "E3_TEST_MODEL",
                "E3_JUDGE_MODEL", "E3_TEST_REASONING_EFFORT", "E3_JUDGE_REASONING_EFFORT",
                "E3_TEMPERATURE", "E3_JUDGE_MODE", "E3_MAX_OUTPUT_TOKENS"):
        if key in os.environ:
            values[key] = os.environ[key]
    values.setdefault("E3_JUDGE_MODE", "assistant")
    values.setdefault("E3_MAX_OUTPUT_TOKENS", "32768")
    if values["E3_JUDGE_MODE"] != "api":
        values.pop("E3_JUDGE_MODEL", None)
        values.pop("E3_JUDGE_REASONING_EFFORT", None)
    secret = values.get("E3_API_KEY", "")
    if secret and secret not in SECRETS:
        SECRETS.append(secret)
    missing = []
    url = urlsplit(values.get("E3_API_BASE_URL", ""))
    if (url.scheme not in ("https", "http") or not url.hostname or "YOUR-" in url.hostname.upper()
            or url.username or url.password or url.query or url.fragment):
        missing.append("E3_API_BASE_URL（需要实际基础地址，不含凭据、查询串）")
    if url.scheme == "http" and url.hostname not in ("localhost", "127.0.0.1", "::1"):
        missing.append("远程 API 必须使用 HTTPS")
    if values.get("E3_API_STYLE") not in ("responses", "chat_completions"):
        missing.append("E3_API_STYLE（responses / chat_completions）")
    for key in (("E3_API_KEY", "E3_TEST_MODEL", "E3_JUDGE_MODEL") if values["E3_JUDGE_MODE"] == "api" else ("E3_API_KEY", "E3_TEST_MODEL")):
        if not values.get(key):
            missing.append(key)
    for key in ("E3_TEST_MODEL", "E3_JUDGE_MODEL"):
        if "latest" in values.get(key, "").lower():
            missing.append(f"{key}（禁止 latest 别名）")
    if values["E3_JUDGE_MODE"] not in ("assistant", "api"):
        missing.append("E3_JUDGE_MODE（assistant / api）")
    try:
        budget = int(values["E3_MAX_OUTPUT_TOKENS"])
        if not 1024 <= budget <= 65536:
            raise ValueError
    except ValueError:
        missing.append("E3_MAX_OUTPUT_TOKENS（1024–65536整数；本轮验证32768）")
    temperature = values.get("E3_TEMPERATURE", "")
    if temperature:
        try:
            n = float(temperature)
            if not 0 <= n <= 2:
                raise ValueError
        except ValueError:
            missing.append("E3_TEMPERATURE（留空或 0–2 的有限数值）")
    return values, missing


def public_config(values: dict) -> dict:
    """提取会影响实验的配置，排除凭据本体。"""
    return {k: v for k, v in values.items() if k != "E3_API_KEY"}


def anonymous(text: str) -> str:
    """隐藏系统与仓内路径线索；匿名改写只用于评分副本。"""
    text = redact(text)
    text = re.sub(r"astro[-_ ]best|BEST\s+skill", "[SYSTEM]", text, flags=re.I)
    text = re.sub(r"(?:src|rag|ops|references|static|agents|evals)/[\w./-]+", "[MODULE]", text)
    return text


def record_key(group: str, item: str, repeat: int) -> str:
    """组合有限的组别、题号与重复序号，生成本轮记录名。"""
    if group not in GROUPS or not re.fullmatch(r"E3-[A-G]\d{2}", item) or repeat not in (1, 2, 3):
        raise ValueError("记录编号非法")
    return f"{group}_{item}_r{repeat}"


def current_batch() -> Path:
    """取得当前批次，防止指针逃逸至实验目录外。"""
    path = (HERE / read_json(HERE / "current.json")["path"]).resolve()
    if not path.is_relative_to(HERE / "batches"):
        raise ValueError("批次路径越界")
    return path
