"""当前助手制定的结论语义抽取：按任务核心事实比较，保留模型声明卡作对照。"""
# 标准库：字段语义词表、URI与数值验证。
import re
from urllib.parse import urlsplit, parse_qsl, urlencode, urlunsplit
# 项目表名及临时会话归一。
from src.protocol import CATALOG_PATHS
from metrics_e6 import aliases_for, stable_payload

def capability_labels(answer):
    """肯定的显式能力标签；排除否定及明确的未来/缺参时假设。"""
    excluded = r'(?:不属于|不是|非)[^。；;\n]{0,40}$|(?:无|没有)\s*$|(?:若|如果|假如)[^。；;\n]{0,50}$|(?:缺失|未配置|不足)时[^。；;\n]{0,25}$'
    return [m.group().lower() for m in re.finditer(r'not_computable|not_configured',answer,re.I)
            if not re.search(excluded,answer[max(0,m.start()-80):m.start()])
            and not re.match(r'\s*(?:无关|不适用|未(?:发生|触发))',answer[m.end():])]

def numeric_field(task_id, field):
    """将同一关键事实的中英文标签归一，不把效率数值混入科学结论。"""
    lower = field.lower().replace(" ", "").replace("_", "")
    if task_id=='REPRO-28' and any(t in lower for t in ('sourcecount','sourcescount')):
        return 'total_count'
    if task_id=='REPRO-28' and ((any(t in lower for t in ('page1','firstpage')) and any(t in lower for t in ('returned','rows','rowcount'))) or
                               (any(t in field for t in ('第一页','首页')) and any(t in field for t in ('返回','行数')))):
        return 'returned_count'
    if any(t in lower for t in ('page','http','request','elapsed','toolstep')) or any(t in field for t in ('页数','请求','耗时')):
        return None
    if task_id == 'REPRO-11' and lower == 'stdstarswithin5arcsec':
        return 'total_count'
    if task_id == 'REPRO-11' and re.search(r'(?<!\d)5\s*(?:″|角秒|arcsec)',field,re.I) and ('标准星' in field or 'std' in lower) and ('数' in field or 'count' in lower):
        return 'total_count'
    if task_id in ('REPRO-10','REPRO-12') and ('radiusarcsec' in lower or ('半径' in field and '角秒' in field)):
        if lower.startswith(('max','min','limit')) or '上限' in field or '下限' in field:
            return None
        return 'radius_arcsec'
    if task_id in ("REPRO-03", "REPRO-29", "REPRO-14", "REPRO-21"):
        if task_id == 'REPRO-21' and any(t in lower for t in ('center','query','cone')):
            return None
        if (lower.startswith("ra") and not lower.startswith("radius")) or 'centerra' in lower or "赤经" in field:
            return "ra_deg"
        if lower.startswith("dec") or 'centerdec' in lower or "赤纬" in field:
            return "dec_deg"
        if task_id != 'REPRO-21':
            return None
    if task_id in ("REPRO-01", "REPRO-02", "REPRO-20", "REPRO-32"):
        if (('列' in field and any(t in field for t in ('测光','星等','质量','坐标','位置','标志'))) or
            ('column' in lower and any(t in lower for t in ('photometric','photometry','magnitude','psf','flag','coordinate')))):
            return None
        if "catalogcount" in lower or lower=='ncatalogs' or ("星表" in field and any(t in field for t in ("总", "可查", "可查询"))):
            return "catalog_count"
        if "columncount" in lower or lower in ('ncolumns','ncols','ps1columns') or ("列" in field and any(t in field for t in ("数", "总"))):
            return "column_count"
        return None
    if task_id in ("REPRO-15", "REPRO-16", "REPRO-21") and (any(x in lower for x in ('mag','rpsf','rpstotal')) or "星等" in field):
        if any(t in lower for t in ('err','uncertainty','rows','count','runnerup','second')) or any(t in field for t in ('误差','不确定','行数','次亮')):
            return None
        if task_id == 'REPRO-21':
            return 'magnitude'
        if any(x in lower for x in ('min','brightest')) or any(x in field for x in ('最亮','最小')):
            return 'min_magnitude'
        if any(x in lower for x in ('max','faintest')) or any(x in field for x in ('最暗','最大')):
            return 'max_magnitude'
        if 'mean' in lower or '平均' in field:
            return 'mean_magnitude'
        return 'magnitude'
    if task_id == 'REPRO-21':
        return None
    if any(t in lower for t in ("total", "matched", "nhits", "nmatched")) or any(t in field for t in ("总", "命中", "匹配数")):
        return "total_count"
    if any(t in lower for t in ("return", "rowcount", "nrows", "fetched", "retrieved")) or any(t in field for t in ("返回", "实取", "拉取", "行数")):
        return "returned_count"
    return None

def canonical_uri(uri, aliases):
    """查询URI统一数值写法，剥离易失会话；保留查询语义。"""
    uri = stable_payload(uri, aliases)
    parts = urlsplit(uri)
    query = []
    for k, v in parse_qsl(parts.query, keep_blank_values=True):
        if k in ("ra", "dec", "sr", "r", "rows", "page", "n"):
            try:
                v = format(float(v), ".12g")
            except ValueError:
                pass
        query.append((k, v))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(sorted(query)), ""))

def semantic_card(run):
    """抽取答案中的事实；模型声明值必须确实出现在答案中才可作为候选。"""
    answer, declared, task = run["answer_text"], run["card"], run["task_id"]
    kind = declared["kind"]
    # 原题要求的主结论类型固定；同一行集被模型称为value不构成事实变化。
    if kind in ('value', 'rowset'):
        if task in ('REPRO-01','REPRO-02','REPRO-04','REPRO-11','REPRO-25','REPRO-27','REPRO-28','REPRO-32'):
            kind = 'rowset'
        elif task in ('REPRO-03','REPRO-15','REPRO-16','REPRO-21','REPRO-29'):
            kind = 'value'
    numbers, diagnostics = {}, []
    if kind in ("value", "rowset") or (kind == 'clarification' and task in ('REPRO-10','REPRO-12','REPRO-14')):
        for item in declared.get("key_numbers", []):
            field = numeric_field(task, str(item.get("field", "")))
            if not field:
                continue
            if task == 'REPRO-11' and field == 'returned_count':
                field = 'total_count'
            try:
                value = float(item["value"])
            except (KeyError, ValueError, TypeError):
                diagnostics.append("card_non_numeric:" + str(item))
                continue
            # 仅在答案含该数值时采纳；任务核心事实缺失如实保留，禁止拿工具数值补答案。
            parsed = [float(x) for x in re.findall(r"(?<![A-Za-z0-9_.])[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?(?![A-Za-z0-9_.])", answer)]
            if not any(abs(x - value) <= 1e-6 * max(abs(x), abs(value), 1e-30) for x in parsed):
                diagnostics.append(f"declared_number_not_in_answer:{field}:{value}")
                continue
            numbers.setdefault(field, set()).add(value)
        # 直接从答案提取明确标记的主事实，避免声明卡漏字段被误判为事实漂移。
        explicit = {}
        if task in ('REPRO-10','REPRO-12'):
            explicit = {'radius_arcsec':r'(?:=|即|等于|折合|转换为)\s*(\d+(?:\.\d+)?)\s*(?:角秒|″|arcsec)'}
        if task in ('REPRO-04','REPRO-25','REPRO-27','REPRO-28'):
            explicit = {'total_count':r'(?:total_count\s*[:=]\s*|命中(?:总数)?\s*[:：=]?\s*\**\s*)(\d+)',
                        'returned_count':r'(?:returned_count\s*[:=]\s*|(?:返回|取回)\s*(?:全量|全部)?\s*)(\d+)'}
        if task=='REPRO-28' and not re.search(explicit['returned_count'],answer,re.I):
            explicit['returned_count']=r'(\d+)\s*行[^。；;\n]{0,35}(?:全部返回|全量返回|全部取回)|第一页[^。；;\n]{0,25}(?:共|返回|取回)\s*(\d+)\s*行'
        if task=='REPRO-28':
            page=re.search(r'第一页.{0,85}?(?:\brows\s*[:=]\s*|(?:返回|取回|共)\s*(?:全量|全部)?\s*)(\d+)',answer,re.I|re.S)
            if page:
                numbers['returned_count']={float(page[1])}
            if 'returned_count' in numbers:
                explicit.pop('returned_count',None)
        if task in ('REPRO-03','REPRO-29','REPRO-14'):
            explicit = {'ra_deg':r'\bRA\s*[=:]\s*([-+]?\d+(?:\.\d+)?)',
                        'dec_deg':r'\bDec\s*[=:]\s*([-+]?\d+(?:\.\d+)?)'}
        plain_answer = re.sub(r'[`*]','',answer)
        if task in ('REPRO-01','REPRO-32'):
            explicit['catalog_count'] = r'可(?:查询|查)(?:的)?星表[^\d\n]{0,25}(\d+)\s*张'
        if task in ('REPRO-02','REPRO-32'):
            explicit['column_count'] = r'(?:共|计)\s*(\d+)\s*列|列[^\d\n]{0,15}(\d+)\s*个'
        for field, pattern in explicit.items():
            match = re.search(pattern, plain_answer, re.I)
            if match:
                numbers.setdefault(field,set()).add(float(next(v for v in match.groups() if v is not None)))
        if task == 'REPRO-15':
            # G逐源点值是主请求；不能只比较最大/最小而漏掉中间值。
            points = re.findall(r'(?<![A-Za-z])G\s*[=＝]\s*(\d+(?:\.\d+)?)\s*mag',plain_answer,re.I)
            g_column = None
            for line in plain_answer.replace('\\n','\n').splitlines():
                if not line.strip().startswith('|'):
                    g_column = None
                    continue
                cells = [c.strip() for c in line.strip().strip('|').split('|')]
                header = next((i for i,c in enumerate(cells) if re.match(r'^G(?:\s|\(|$)|^phot_g_mean_mag$',c,re.I)),None)
                if header is not None:
                    g_column = header
                elif g_column is not None and g_column < len(cells) and re.fullmatch(r'\d+(?:\.\d+)?',cells[g_column]):
                    points.append(cells[g_column])
            if points:
                numbers['magnitude'] = {float(v) for v in points}
            if 'returned_count' in numbers and re.search(r'truncated\s*[:=]\s*false|未截断',answer,re.I):
                numbers.setdefault('total_count',set()).update(numbers.pop('returned_count'))
        if task == 'REPRO-16':
            # 原题为S-PLUS的60″锥；PS1对照及大半径覆盖点不是主行数。
            match = re.search(r'total_count\s*[:=]\s*(\d+)|(?:命中|返回)\s*(\d+)\s*行',plain_answer,re.I)
            numbers = {k:v for k,v in numbers.items() if 'magnitude' in k}
            if match:
                numbers['total_count'] = {float(next(v for v in match.groups() if v is not None))}
        if task == 'REPRO-21':
            # “哪颗”的主身份取自最亮源段落，不能把查询中心当目标坐标。
            marker = re.search(r'最亮(?:的)?源',plain_answer)
            scope = plain_answer[marker.end():marker.end()+800] if marker else ''
            for field,label in (('ra_deg','RA'),('dec_deg','Dec')):
                match = re.search(r'\b'+label+r'\s*[=＝:：]\s*([-+]?\d+(?:\.\d+)?)',scope,re.I)
                if match:
                    numbers[field] = {float(match[1])}
        if task == 'REPRO-28':
            # 原题要看首页；先前cone曾取全量也不能覆盖后来展示20/50行的首页事实。
            preview = re.search(r'第[一1]页[\s\S]{0,180}?(?:returned_count\s*[:=]\s*|(?:返回|页大小)\s*(?:全量|全部)?\s*)(\d+)', answer, re.I)
            if preview:
                numbers['returned_count'] = {float(preview[1])}
    entities = set()
    if kind in ("value", "rowset"):
        if task in ('REPRO-01','REPRO-32'):
            relevant_catalogs = set(CATALOG_PATHS)
        elif task in ('REPRO-03','REPRO-29'):
            relevant_catalogs = set()
        else:
            relevant_catalogs = {c['args'].get('catalog','ps1') for c in run['tool_calls'] if c['tool'] in ('cone_search','crossmatch_batch','describe_catalog')}
        if task == 'REPRO-16':
            relevant_catalogs = {'splus_dr4'}
        for catalog in CATALOG_PATHS:
            if catalog in relevant_catalogs and re.search(r"(?<![A-Za-z0-9_])" + re.escape(catalog) + r"(?![A-Za-z0-9_])", answer, re.I):
                entities.add(catalog)
        if task in ("REPRO-03", "REPRO-29") and "M31" in answer:
            entities.add("M31")
        # 稳定引用属结论实体；外部引用的易失值不进入比较。
        for uri in re.findall(r"best://[^\s\"'`<>（）。，；、*()\[\]{}]+", answer):
            # count/page是同一查询的补充证据引用，不是新增科学结论实体。
            if '/sqlid/' in uri:
                continue
            if task == 'REPRO-01' and not uri.startswith('best://catalogs'):
                continue
            if task == 'REPRO-02' and not uri.startswith('best://ps1/describe'):
                continue
            if task in ('REPRO-04','REPRO-11','REPRO-15','REPRO-16','REPRO-21','REPRO-25','REPRO-27','REPRO-28') and not re.search(r'/(?:cone|proximity)\?',uri):
                continue
            if task in ('REPRO-03','REPRO-29') and not uri.startswith('best://nss/solve'):
                continue
            if task == 'REPRO-11':
                # 5角秒三表零行是原题；额外60角秒诊断及count引用属于补充证据。
                parts = urlsplit(uri)
                query = dict(parse_qsl(parts.query))
                if '/cone' not in parts.path or query.get('sr') not in ('5','5.0'):
                    continue
            if task == 'REPRO-16':
                parts = urlsplit(uri)
                query = dict(parse_qsl(parts.query))
                if parts.netloc != 'splus_dr4' or query.get('sr') not in ('60','60.0'):
                    continue
            entities.add(canonical_uri(uri.rstrip(";,.):]"), aliases_for(run)))
    if kind == "refusal":
        entities.update(re.findall(r"\bE_[A-Z_]+\b", answer))
    caveats = set()
    # 科学/能力限定按语义标签；用量、出处重复措辞及提示性示例不当科学事实。
    rules = {"no_time_series": r"无时序|不(?:提供|支持|包含|具备).{0,15}(?:光变|时序|逐历元)|not_computable.{0,30}(?:光变|时序)",
             "synthetic_photometry": r"合成测光|合成星等|synthetic",
             "not_measured_lightcurve": r"非实测|不是.{0,10}实测|不能.{0,12}光变",
             "incomplete_result": r"truncated\s*[:=]\s*true|未取全|仍有.{0,6}(?:剩余|下一页)",
             "empty_is_not_nonexistence": r"不(?:代表|意味着|等于).{0,12}不存在|不能.{0,12}不存在",
             "not_computable": r"not_computable|无法计算",
             "not_configured": r"not_configured|未配置"}
    for label, pattern in rules.items():
        if re.search(pattern, answer, re.I | re.S):
            caveats.add(label)
    for label in ('not_computable','not_configured'):
        if label in answer.lower() and label not in capability_labels(answer):
            caveats.discard(label)
    # 答案解释“只有truncated=true才续取”不能覆盖其当前truncated=false结论。
    if re.search(r'truncated\s*[:=]\s*false|未(?:发生)?截断|无截断', answer, re.I):
        if 'incomplete_result' in caveats:
            diagnostics.append('hypothetical_truncation_excluded_by_explicit_complete_claim')
            caveats.discard('incomplete_result')
    if task in ('REPRO-03','REPRO-29') and kind == 'value':
        caveats = {'frame_ICRS'} if 'ICRS' in answer else ({'frame_J2000'} if 'J2000' in answer else set())
    if task == 'REPRO-11' and kind == 'rowset':
        caveats = set()
    if task == 'REPRO-04' and re.search(r'class_star.{0,20}空|无法.{0,20}(?:恒星筛选|区分恒星)|不代表.{0,10}(?:全部|均|都).{0,8}恒星|未做.{0,15}只取恒星',answer,re.I|re.S):
        caveats.add('stellar_classification_unavailable')
    if task == 'REPRO-15' and kind == 'value':
        # 原题求G测光，静态时序提醒不是该测光值的限定；子集口径才是。
        caveats.discard('no_time_series')
        if re.search(r'Well.Calibrated|标定子集|精定标', answer, re.I):
            caveats.add('well_calibrated_subset')
    if task == 'REPRO-16':
        for label,pattern in {'footprint_inference':r'覆盖.{0,15}(?:推断|判断)|(?:推断|提示).{0,50}覆盖',
                'footprint_undetermined':r'覆盖.{0,40}不可区分|空因未判定',
                'footprint_point_probes':r'覆盖边界.{0,20}点测|边界未细测',
                'pstotal_petrosian_claim':r'Petrosian'}.items():
            if re.search(pattern,answer+' '+str(declared.get('caveats',[])),re.I):
                caveats.add(label)
    if task == 'REPRO-28' and 'returned_count' in numbers and 'total_count' in numbers:
        caveats.discard('incomplete_result')
        if max(numbers['returned_count']) < max(numbers['total_count']):
            caveats.add('dataset_has_later_pages')
    if kind == "clarification":
        keep = {'radius_arcsec'} if task in ('REPRO-10','REPRO-12') else ({'ra_deg','dec_deg'} if task == 'REPRO-14' else set())
        numbers = {k:v for k,v in numbers.items() if k in keep}
        entities = set()
        caveats = {"requires_user_input"}
    if kind == "none":
        diagnostics.append("no_conclusion")
    card = {"kind": kind, "key_numbers": [{"field": field, "value": value} for field in sorted(numbers) for value in sorted(numbers[field])],
            "key_entities": sorted(entities), "caveats": sorted(caveats)}
    return card, diagnostics
