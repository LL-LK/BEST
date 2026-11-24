"""解压后执行：仅用标准库核验快照来源，不需密钥或原机器路径。"""
import hashlib
import json
from pathlib import Path


def fp(value):
    data=value if isinstance(value,str) else json.dumps(value,ensure_ascii=False,sort_keys=True,allow_nan=False,default=str)
    return 'sha256:'+hashlib.sha256(data.encode()).hexdigest()


def main():
    root=Path(__file__).resolve().parent
    snapshot=json.loads((root/'snapshot_manifest.json').read_text())
    mapping=json.loads((root/'SNAPSHOT-SOURCE-PATH-MAP.json').read_text())
    cache={}
    for source,entry in mapping.items():
        relative=Path(entry['archive_path'])
        local=root.joinpath(*relative.parts[1:]).resolve()
        if not local.is_relative_to(root.resolve()):
            raise ValueError('来源路径越界')
        raw=local.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=entry['sha256']:
            raise ValueError('来源文件指纹不匹配')
        cache[source]=[json.loads(line) for line in raw.decode().splitlines()]
    if fp(snapshot['bank'])!=snapshot['fingerprint']:
        raise ValueError('快照库指纹不匹配')
    checked=0
    for key,record in snapshot['bank'].items():
        if key!=fp(record['request']) or record.get('mode')!='live':
            raise ValueError('请求语义或回包来源不合法')
        pointers=snapshot['sources'].get(key,[])
        if not pointers:
            raise ValueError('快照缺少来源')
        for i,pointer in enumerate(pointers):
            event=cache[pointer['trace']][pointer['seq']]
            payload=event['payload']
            if (event['type']!='network_exchange' or event['seq']!=pointer['seq'] or
                fp(payload)!=pointer['fp'] or payload.get('request_key')!=key or
                payload.get('mode')!='live' or (i==0 and payload!=record)):
                raise ValueError('来源指针不匹配')
            checked+=1
    print(json.dumps({'snapshot_entries':len(snapshot['bank']),'source_traces':len(mapping),
                      'source_pointers_checked':checked,'passed':True}))


if __name__=='__main__':
    main()
