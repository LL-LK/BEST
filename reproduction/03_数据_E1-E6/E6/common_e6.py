"""E6 临时设施：安全配置、脱敏、不可覆盖产物和内容指纹。"""
# 标准库：安全解析、原子落盘、时区与指纹。
import hashlib
import importlib.util
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
SECRETS = []
PILOT = [f"REPRO-{i:02d}" for i in (1, 3, 4, 7, 11, 15, 27, 28, 30, 32)]

def now():
    """返回上海实际执行时间。"""
    return datetime.now(ZoneInfo("Asia/Shanghai")).isoformat()

def utc():
    """返回 UTC 时间，保留微秒供时序校验。"""
    return datetime.now(timezone.utc).isoformat()

def encode(value):
    """规范化 JSON，拒绝非有限值。"""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False, default=str)

def fp(value):
    """返回内容指纹。"""
    data = value.encode() if isinstance(value, str) else encode(value).encode()
    return "sha256:" + hashlib.sha256(data).hexdigest()

def redact(value):
    """删除凭据原文和敏感请求头；保留谈论凭据的普通文本。"""
    if isinstance(value, str):
        for secret in SECRETS:
            if secret:
                value = value.replace(secret, "[REDACTED]")
        return re.sub(r"([?&](?:token|api_key|apikey|access_token|auth)=)[^&\s]*", r"\1[REDACTED]", value, flags=re.I)
    if isinstance(value, dict):
        return {str(k): ("[REDACTED]" if str(k).lower() in
                ("authorization", "cookie", "set-cookie", "x-api-key", "api_key", "access_token", "refresh_token")
                else redact(v)) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [redact(v) for v in value]
    return value

def write(path, value, exclusive=True):
    """写入产物；默认拒绝覆盖历史文件。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    payload = json.dumps(redact(value), ensure_ascii=False, indent=2, allow_nan=False, default=str) + "\n"
    # 完整写入私有临时文件后再原子提交，崩溃不能留下半个成功JSON。
    with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=path.parent, prefix=path.name+'.pending-', delete=False) as out:
        pending = Path(out.name)
        out.write(payload)
        out.flush()
        os.fsync(out.fileno())
    try:
        if exclusive:
            os.link(pending, path)
        else:
            os.replace(pending, path)
        path.chmod(0o600)
    finally:
        pending.unlink(missing_ok=True)

def read(path):
    """读取 JSON，不执行配置代码。"""
    return json.loads(Path(path).read_text())

def config():
    """复用已验收 dotenv 解析器，仅取被测模型所需字段。"""
    spec = importlib.util.spec_from_file_location("e3_safe_common", ROOT / "temp/e3-formal/common.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    values, missing = module.config(ROOT / "temp/e3-formal/.env")
    if missing:
        raise ValueError("必要配置缺项：" + ", ".join(missing))
    values = {k: v for k, v in values.items() if k.startswith("E3_TEST_") or k in
              ("E3_API_BASE_URL", "E3_API_STYLE", "E3_API_KEY", "E3_MAX_OUTPUT_TOKENS", "E3_TEMPERATURE")}
    if values["E3_API_STYLE"] != "responses":
        raise ValueError("本轮真实 agent 设施需要已确认的 Responses 接口")
    SECRETS.extend([values["E3_API_KEY"], os.environ.get("BEST_API_TOKEN", "")])
    return values

def public_config(values):
    """返回安全的请求配置，不含密钥。"""
    return {k: v for k, v in values.items() if k != "E3_API_KEY"}
