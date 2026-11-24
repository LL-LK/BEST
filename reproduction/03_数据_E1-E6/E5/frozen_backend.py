"""有限公开查询回放传输；由真实模型决定调用，不读任务标签或答案键。"""
import csv
import hashlib
import io
import json
from pathlib import Path
import re
from urllib.parse import parse_qs, urlsplit
import requests

class FrozenSession(requests.Session):
    """严格查询绑定、会话内句柄及有限分页；绝不兜底成别的天区。"""
    def __init__(self,bundle,state,session_id):
        super().__init__()
        self.trust_env=False
        self.bundle=bundle
        self.state=state
        self.session_id=session_id
        self.log=[]
    def response(self,url,payload,status=200):
        response=requests.Response()
        response.url=url
        response.status_code=status
        response.encoding='utf-8'
        response._content=payload if isinstance(payload,bytes) else payload.encode('utf-8')
        self.log.append({'method':self.method,'url':url,'status':status,'response_sha256':hashlib.sha256(response.content).hexdigest(),'bytes':len(response.content)})
        return response
    def denied(self,url,reason):
        return self.response(url,json.dumps({'error':reason}),422)
    def request(self,method,url,**kwargs):
        self.method=method.upper()
        parsed=urlsplit(url)
        if parsed.scheme!='https' or parsed.hostname!='nadc.china-vo.org' or not parsed.path.startswith('/data/best/'):
            raise requests.RequestException('E5_OUTBOUND_DENIED')
        path=parsed.path.removeprefix('/data/best/')
        params=parse_qs(parsed.query)
        if method.upper()=='GET' and path=='nss/solve':
            name=params.get('obj',[''])[0]
            record=self.bundle['names'].get(name)
            if record is None:return self.denied(url,'E_SNAPSHOT_NAME_UNAVAILABLE')
            return self.response(url,json.dumps(record['response'],ensure_ascii=False))
        if method.upper()=='POST' and re.fullmatch(r'[A-Za-z0-9_]+/q',path):
            catalog=path.split('/')[0]
            form=kwargs.get('data') or {}
            self.log.append({'method':'POST','url':url,'form':{k:v for k,v in form.items() if 'token' not in k.lower()}})
            try:
                if form.get('pos.type')=='cone':
                    query={'kind':'cone','catalog':catalog,'ra':float(form['pos.racenter']),
                           'dec':float(form['pos.deccenter']),'radius':float(form['pos.radius'])}
                    if not (0<=query['ra']<360 and -90<=query['dec']<=90 and 0<query['radius']<=18000):
                        return self.denied(url,'E_INVALID_INPUT')
                elif form.get('pos.type')=='proximity':
                    points=[[float(n) for n in line.replace(',',' ').split()[:2]] for line in str(form['pos.radecTextarea']).strip().splitlines()]
                    query={'kind':'proximity','catalog':catalog,'points':points,'radius':float(form['pos.defaultRadius'])}
                else:return self.denied(url,'E_SNAPSHOT_QUERY_UNAVAILABLE')
            except (ValueError,KeyError,TypeError):return self.denied(url,'E_INVALID_INPUT')
            match=next((q for q in self.bundle['queries'] if all(q['query'].get(k)==v for k,v in query.items())),None)
            if match is None:return self.denied(url,'E_SNAPSHOT_QUERY_UNAVAILABLE')
            # Additional column constraints are not silently discarded.
            if any('.constraint' in key or key.endswith('.min') or key.endswith('.max') for key in form):
                return self.denied(url,'E_SNAPSHOT_CONSTRAINT_UNAVAILABLE')
            columns=form.get('showcol') or match['columns']
            if isinstance(columns,str):columns=[c.strip() for c in columns.split(',') if c.strip()]
            def column_name(value):
                normalized=value.replace('.','_')
                return normalized if normalized in match['columns'] else catalog+'_'+normalized
            columns=[column_name(c) for c in columns]
            if any(c not in match['columns'] for c in columns):return self.denied(url,'E_SNAPSHOT_COLUMN_UNAVAILABLE')
            sort=form.get('sort') or match['query'].get('sort')
            if sort:sort=column_name(sort)
            order=form.get('order','asc')
            if not match['complete'] and (sort!=match['query'].get('sort') or order!=match['query'].get('order')):
                return self.denied(url,'E_SNAPSHOT_SORT_UNAVAILABLE')
            counter=int(self.state.get('next_query',1))
            sqlid=str(int(hashlib.sha256(self.session_id.encode()).hexdigest()[:10],16)*1000+counter)
            self.state['next_query']=counter+1
            self.state.setdefault('queries',{})[sqlid]={'query_id':match['query_id'],'columns':columns,
                                                       'sort':sort,'order':order,
                                                       'nearest_only':bool(form.get('cone_nearestonly') or form.get('proximity_nearestonly'))}
            return self.response(url,f'<html><a href="/data/best/sqlid/s{sqlid}">query</a></html>')
        if method.upper()=='GET':
            match=re.fullmatch(r'sqlid/s?(\d+)(/getcount)?',path)
            if not match:return self.denied(url,'E5_ROUTE_DENIED')
            handle=self.state.get('queries',{}).get(match.group(1))
            if handle is None:return self.denied(url,'E5_CROSS_SESSION_HANDLE_DENIED')
            dataset=next(q for q in self.bundle['queries'] if q['query_id']==handle['query_id'])
            data=list(dataset['rows'])
            if handle['nearest_only'] and dataset['query']['kind']=='cone' and data:
                data=[min(data,key=lambda row:float(row['inputobjs_dist_arcsec']))]
            total=1 if handle['nearest_only'] and dataset['query']['kind']=='cone' and data else dataset['total_count']
            if match.group(2):return self.response(url,json.dumps({'total':total}))
            sort=params.get('sort',[handle.get('sort')])[0]
            if sort:
                sort=sort.replace('.','_')
                if sort not in dataset['columns']:sort=dataset['query']['catalog']+'_'+sort
            order=params.get('order',[handle.get('order','asc')])[0]
            if not dataset['complete'] and (sort!=dataset['query'].get('sort') or order!=dataset['query'].get('order')):
                return self.denied(url,'E_SNAPSHOT_SORT_UNAVAILABLE')
            if sort and dataset['complete']:
                if sort not in dataset['columns']:return self.denied(url,'E_SNAPSHOT_SORT_UNAVAILABLE')
                def key(row):
                    try:return (0,float(row.get(sort,'')))
                    except ValueError:return (1,str(row.get(sort,'')))
                data.sort(key=key,reverse=order=='desc')
            try:
                page=int(params.get('page',['1'])[0]);size=int(params.get('rows',['1000'])[0])
                if page<1 or size<1 or size>10000:raise ValueError()
            except ValueError:return self.denied(url,'E_INVALID_INPUT')
            start=(page-1)*size
            if start>=len(data) and len(data)<total:return self.denied(url,'E_SNAPSHOT_COVERAGE_LIMIT')
            selected=data[start:start+size]
            columns=[c for c in dataset['columns'] if c.startswith('inputobjs_') or c in handle['columns']]
            stream=io.StringIO(newline='')
            writer=csv.DictWriter(stream,fieldnames=columns,extrasaction='ignore',lineterminator='\n')
            writer.writeheader();writer.writerows(selected)
            return self.response(url,stream.getvalue())
        return self.denied(url,'E5_METHOD_DENIED')

def invoke(bundle,state,session_id,tool,args):
    """生产 ToolBox/BestClient 为唯一 SUT；传输层只替换网络响应。"""
    from src.client import BestClient
    from src.ai_tools import ToolBox
    from src.protocol import resolve_catalog
    if tool in {'count','fetch_page','best_get_count','best_get_page'}:
        sqlid=args.get('sqlid')
        if not isinstance(sqlid,str) or not re.fullmatch(r's?\d+',sqlid) or sqlid.removeprefix('s') not in state.get('queries',{}):
            raise PermissionError('E5_SESSION_HANDLE_DENIED')
    client=BestClient(rate_limit=0,max_retries=0,timeout=10)
    client.session.close()
    transport=FrozenSession(bundle,state,session_id)
    client.session=transport
    toolbox=ToolBox(client=client)
    atomic={'resolve_name','list_catalogs','describe_catalog','cone_search','crossmatch_batch','count','fetch_page'}
    if tool in atomic:
        result=getattr(toolbox,tool)(**args).to_dict()
    elif tool=='best_submit':
        catalog=resolve_catalog(args.get('catalog','ps1'))
        form=client._build_form(catalog,[],1,ra=args.get('ra'),dec=args.get('dec'),radius_arcsec=args.get('radius_arcsec'),
                                radec_text=args.get('radec_text'),default_radius_arcsec=args.get('default_radius_arcsec'),
                                columns=args.get('columns'),sort=args.get('sort'),order=args.get('order','asc'),nearest_only=args.get('nearest_only',False))
        sqlid,error=client._submit_query_for_sqlid(catalog+'/q',form)
        result={'sqlid':sqlid,'error':error}
    elif tool=='best_get_count':result={'sqlid':args['sqlid'],'total':client.count(args['sqlid'])}
    elif tool=='best_get_page':
        from src.protocol import build_page_url,normalize_sqlid
        url=build_page_url(client.base_url,normalize_sqlid(args['sqlid']),args.get('page',1),args.get('rows',1000),
                           catalog=args.get('catalog','ps1'),sort=args.get('sort'),order=args.get('order','asc'))
        response=transport.get(url);response.raise_for_status()
        result={'sqlid':args['sqlid'],'csv':response.text,'page':args.get('page',1)}
    elif tool=='best_metadata':result=toolbox.describe_catalog(args['catalog']).data
    elif tool=='best_resolve':result=client.resolve_name(args['name']).to_dict()
    elif tool=='e5_fixture_square':
        if args!={'value':7}:raise ValueError('finite fixture schema')
        result={'value':args['value']**2}
    else:raise ValueError('E5_TOOL_DENIED')
    client.close()
    return result,state,transport.log
