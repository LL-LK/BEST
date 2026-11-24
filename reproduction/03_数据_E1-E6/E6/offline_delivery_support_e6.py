"""离线收尾不需要认证；准确披露已知密钥扫描不可用。"""
import base64
import json
import re
import common_e6

TOKEN_PATTERN = re.compile(rb'sk-[A-Za-z0-9_-]{20,}')
FIELDS = {'authorization','cookie','set-cookie','x-api-key','api_key',
          'access_token','refresh_token','e3_api_key'}


def credentials_for_offline_only():
    try:
        common_e6.config()
        return {'exact_known_api_key_scan_available': True}
    except ValueError as exc:
        if str(exc) != '必要配置缺项：E3_API_KEY':
            raise
        return {'exact_known_api_key_scan_available': False,
                'reason': '收尾时本机配置已无 API 密钥；仅离线统计，不恢复或使用认证。'}


def generic_scan(paths):
    """仅返回命中文件，不输出秘密；覆盖结构字段和解码后的回包。"""
    hits=[]
    def check(value):
        if isinstance(value,dict):
            for key,item in value.items():
                if (key.lower() in FIELDS and isinstance(item,str) and item
                        and '[REDACTED]' not in item):
                    return True
                if key=='content_base64' and isinstance(item,str):
                    try:
                        if TOKEN_PATTERN.search(base64.b64decode(item,validate=True)):
                            return True
                    except (ValueError,TypeError):
                        pass
                if check(item):
                    return True
        elif isinstance(value,list):
            return any(check(item) for item in value)
        return False
    for path in paths:
        raw=path.read_bytes()
        hit=bool(TOKEN_PATTERN.search(raw))
        if path.suffix in ('.json','.jsonl'):
            try:
                records=[json.loads(s) for s in raw.decode().splitlines()] if path.suffix=='.jsonl' else [json.loads(raw)]
                hit=hit or any(check(r) for r in records)
            except (ValueError,UnicodeError):
                # 数据有效性另由轨迹审计处理；不能假装结构解析已通过。
                hit=True
        if hit:
            hits.append(str(path))
    return hits
