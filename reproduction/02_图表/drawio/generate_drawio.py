#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Reproduce BEST-Skill figures 1 and 2 from the current BEST v50 PDF as native editable diagrams.net mxGraph shapes.
The PDF-faithful pair preserves the embedded figure labels; the v50-aligned pair corrects labels/data to the current body and Table 1.

Usage: python generate_drawio.py
Every colored rectangle, label, connector and symbolic icon is an editable mxCell.
The output SVGs are independent fidelity previews generated from the same geometry.
"""
from __future__ import annotations
from dataclasses import dataclass
from html import escape
from pathlib import Path
import xml.etree.ElementTree as ET
import copy
import math
from hashlib import sha1

OUT = Path(__file__).resolve().parent
NS = 'http://www.w3.org/2000/svg'
ET.register_namespace('', NS)
FONT = 'Microsoft YaHei'

@dataclass
class Element:
    kind: str
    x: float = 0; y: float = 0; w: float = 0; h: float = 0
    fill: str = 'none'; border: str = 'none'; bw: float = 1
    radius: float = 0; dotted: bool = False; gradient: str | None = None
    text: str = ''; size: float = 18; color: str = '#24334C'
    bold: bool = False; align: str = 'center'; valign: str = 'middle'
    p1: tuple[float,float] | None = None; p2: tuple[float,float] | None = None
    opacity: float = 100
    arrow: bool = False; dash: bool = False; shape: str = 'rect'; shadow: bool = False

class Canvas:
    def __init__(self,title:str,width:int,height:int):
        self.title=title; self.width=width; self.height=height; self.items=[]; self.counter=0
    def rect(self,x,y,w,h,fill='none',stroke='none',sw=1,r=0,dashed=False,gradient=None,shadow=False):
        self.items.append(Element('rect',x,y,w,h,fill,stroke,sw,r,dashed,gradient,shadow=shadow))
    def label(self,txt,x,y,w,h,size=18,color='#183F64',bold=False,align='center',valign='middle'):
        self.items.append(Element('label',x,y,w,h,text=txt,size=size,color=color,bold=bold,align=align,valign=valign))
    def bullet(self,cx,cy,color='#4C9FF0',r=6):
        self.circle(cx,cy,r,color,'#FFFFFF',0.8)
    def line(self,x1,y1,x2,y2,color='#1D5E9D',w=3,arrow=False,dash=False):
        self.items.append(Element('line',p1=(x1,y1),p2=(x2,y2),border=color,bw=w,arrow=arrow,dash=dash))
    def circle(self,cx,cy,r,fill,stroke='none',sw=1):
        self.items.append(Element('ellipse',cx-r,cy-r,2*r,2*r,fill,stroke,sw,shape='ellipse'))
    def pill(self,text,x,y,w,h,fill,stroke='none',size=17,color='#21354B',bold=False):
        self.rect(x,y,w,h,fill,stroke,1,9)
        self.label(text,x+2,y+1,w-4,h-2,size,color,bold)
    def docicon(self,x,y,s=1,color='#26557F'):
        self.rect(x,y,32*s,39*s,'#FFFFFF',color,3*s,4*s)
        self.line(x+18*s,y+2*s,x+30*s,y+14*s,color,2*s)
        for i in range(3):
            self.line(x+7*s,y+(17+7*i)*s,x+24*s,y+(17+7*i)*s,color,2*s)
    def lockicon(self,x,y,s=1,color='#245581'):
        self.rect(x+7*s,y+17*s,28*s,25*s,color,color,1,5*s)
        self.rect(x+14*s,y+4*s,14*s,22*s,'none',color,4*s,7*s)
        self.circle(x+21*s,y+27*s,3*s,'white')
    def personicon(self,x,y,s=1,color='#245581'):
        self.circle(x+20*s,y+11*s,11*s,color)
        self.rect(x+1*s,y+23*s,38*s,17*s,color,color,1,14*s)
    def dbicon(self,x,y,s=1,color='#285B89'):
        self.rect(x,y+8*s,39*s,29*s,color,'none',1,0)
        self.items.append(Element('ellipse',x,y,39*s,15*s,color,'#FFFFFF',1.2*s,shape='ellipse'))
        for yy in [y+17*s,y+30*s]:self.line(x+2*s,yy,x+37*s,yy,'#FFFFFF',1.5*s)
    def nodesicon(self,x,y,s=1,color='#27557F'):
        pts=[(3,21),(22,4),(36,20),(23,38)]
        for a,b in [(0,1),(1,2),(1,3)]:
            self.line(x+pts[a][0]*s,y+pts[a][1]*s,x+pts[b][0]*s,y+pts[b][1]*s,color,2*s)
        for px,py in pts:
            self.circle(x+px*s,y+py*s,5*s,'#FFFFFF',color,3*s)
    def levelsicon(self,x,y,s=1,color='#966BD2'):
        for i in range(3):
            self.rect(x+5*s,y+(7+11*i)*s,35*s,9*s,color,'none',0,3*s)
    def barsicon(self,x,y,s=1,color='#9675D8'):
        for i,h in enumerate([13,24,37]):
            self.rect(x+(6+12*i)*s,y+(41-h)*s,8*s,h*s,color,'none',0,2*s)
    def mini_charticon(self,x,y,s=1,color='#9675D8'):
        pts=[(5,35),(16,24),(26,29),(38,8)]
        for a,b in zip(pts,pts[1:]):self.line(x+a[0]*s,y+a[1]*s,x+b[0]*s,y+b[1]*s,color,2.5*s)
        for a,b in pts:self.circle(x+a*s,y+b*s,3.5*s,color)
    def diamond(self,cx,cy,hw,hh,fill='#A06AE8',stroke='none',sw=1):
        self.items.append(Element('diamond',cx-hw,cy-hh,hw*2,hh*2,fill,stroke,sw,shape='rhombus'))
    def shieldicon(self,x,y,s=1,color='#277ED1'):
        # Shield outline as editable vector segments
        pts=[(20,0),(40,10),(38,31),(31,43),(20,49),(9,43),(2,31),(0,10),(20,0)]
        for a,b in zip(pts,pts[1:]):self.line(x+a[0]*s,y+a[1]*s,x+b[0]*s,y+b[1]*s,color,3*s)
        self.lockicon(x+5*s,y+7*s,0.62*s,color)
    def clock_docicon(self,x,y,s=1,color='#277ED1'):
        self.docicon(x,y,s,color)
        self.circle(x+30*s,y+32*s,13*s,'#EDF8FF',color,3*s)
        self.line(x+30*s,y+32*s,x+30*s,y+23*s,color,2*s)
        self.line(x+30*s,y+32*s,x+37*s,y+35*s,color,2*s)
    def checked_dbicon(self,x,y,s=1,color='#277ED1'):
        self.dbicon(x,y,s,color)
        self.circle(x+34*s,y+35*s,13*s,'#EDF8FF',color,2*s)
        self.line(x+27*s,y+34*s,x+32*s,y+39*s,color,3*s)
        self.line(x+32*s,y+39*s,x+42*s,y+27*s,color,3*s)
    def grid_decor(self,x,y,cols,rows,dx,dy,color='#FFFFFF'):
        for i in range(cols):
            for j in range(rows):self.circle(x+i*dx,y+j*dy,2.1,color)

    def graphmodel(self):
        model=ET.Element('mxGraphModel',{
            'dx':str(self.width),'dy':str(self.height),'grid':'0','gridSize':'10','guides':'1',
            'tooltips':'1','connect':'1','arrows':'1','fold':'1','page':'1','pageScale':'1',
            'pageWidth':str(self.width),'pageHeight':str(self.height),'math':'0','shadow':'0'})
        root=ET.SubElement(model,'root')
        ET.SubElement(root,'mxCell',{'id':'0'})
        ET.SubElement(root,'mxCell',{'id':'1','parent':'0'})
        for i,e in enumerate(self.items):
            idx=f'n{i+2:05}'
            if e.kind=='line':
                style='edgeStyle=none;html=1;rounded=0;'
                style+=f'strokeColor={e.border};strokeWidth={e.bw};'
                if e.arrow: style+='endArrow=block;endFill=1;endSize=10;'
                else: style+='endArrow=none;'
                if e.dash:style+='dashed=1;dashPattern=4 4;'
                cell=ET.SubElement(root,'mxCell',{'id':idx,'style':style,'parent':'1','edge':'1'})
                ge=ET.SubElement(cell,'mxGeometry',{'relative':'1','as':'geometry'})
                ET.SubElement(ge,'mxPoint',{'x':str(e.p1[0]),'y':str(e.p1[1]),'as':'sourcePoint'})
                ET.SubElement(ge,'mxPoint',{'x':str(e.p2[0]),'y':str(e.p2[1]),'as':'targetPoint'})
            else:
                if e.kind=='label':
                    style=(f'text;html=1;whiteSpace=wrap;strokeColor=none;fillColor=none;'
                           f'fontSize={e.size};fontColor={e.color};fontFamily={FONT};'
                           f'fontStyle={1 if e.bold else 0};align={e.align};verticalAlign={e.valign};'
                           'overflow=hidden;spacing=0;spacingLeft=0;spacingRight=0;spacingTop=0;spacingBottom=0;')
                    # literal line break markup; labels are editable text
                    val='<div>'+('<br>'.join(escape(x) for x in e.text.split('\n')))+'</div>'
                else:
                    rflag='1' if e.radius else '0'
                    style=(f'shape={"ellipse" if e.kind=="ellipse" else ("rhombus" if e.kind=="diamond" else "rectangle")};rounded={rflag};'
                           f'arcSize={int(min(50,e.radius*2/max(1,min(e.w,e.h))*100)) if e.radius else 0};'
                           f'html=1;whiteSpace=wrap;strokeColor={e.border};fillColor={e.fill};strokeWidth={e.bw};')
                    style+=f'opacity={e.opacity};'
                    if e.gradient:style+=f'gradientColor={e.gradient};gradientDirection=south;'
                    if e.dotted:style+='dashed=1;dashPattern=4 4;'
                    if e.shadow:style+='shadow=1;'
                    val=''
                cell=ET.SubElement(root,'mxCell',{'id':idx,'value':val,'style':style,'parent':'1','vertex':'1'})
                ET.SubElement(cell,'mxGeometry',{'x':str(e.x),'y':str(e.y),'width':str(e.w),'height':str(e.h),'as':'geometry'})
        return model

    def save_drawio(self,path:Path):
        mxfile=ET.Element('mxfile',{'host':'app.diagrams.net','agent':'BEST-Skill native draw.io generator','version':'24.7.17','type':'device'})
        diag=ET.SubElement(mxfile,'diagram',{'name':self.title,'id':sha1(self.title.encode('utf-8')).hexdigest()[:12]})
        diag.append(self.graphmodel())
        ET.indent(mxfile,space='  ')
        path.write_bytes(ET.tostring(mxfile,encoding='utf-8',xml_declaration=True))

    def save_svg(self,path:Path):
        svg=ET.Element('svg',{'xmlns':NS,'viewBox':f'0 0 {self.width} {self.height}', 'width':str(self.width),'height':str(self.height)})
        defs=ET.SubElement(svg,'defs')
        # gradients made for all kinds of fills
        for i,e in enumerate(self.items):
            if e.gradient:
                g=ET.SubElement(defs,'linearGradient',{'id':f'grad{i}','x1':'0','y1':'0','x2':'0','y2':'1'})
                ET.SubElement(g,'stop',{'offset':'0%','stop-color':e.fill})
                ET.SubElement(g,'stop',{'offset':'100%','stop-color':e.gradient})
        bg=ET.SubElement(svg,'rect',{'x':'0','y':'0','width':str(self.width),'height':str(self.height),'fill':'#FFFFFF'})
        for i,e in enumerate(self.items):
            if e.kind=='rect':
                if e.shadow:
                    ET.SubElement(svg,'rect',{'x':str(e.x+2),'y':str(e.y+4),'width':str(e.w),'height':str(e.h),'rx':str(e.radius),'ry':str(e.radius),'fill':'#94AFC8','opacity':'0.15'})
                attr={'x':str(e.x),'y':str(e.y),'width':str(e.w),'height':str(e.h),
                      'rx':str(e.radius),'ry':str(e.radius),
                      'fill':f'url(#grad{i})' if e.gradient else e.fill,
                      'stroke':e.border,'stroke-width':str(e.bw)}
                if e.dotted:attr['stroke-dasharray']='5 4'
                ET.SubElement(svg,'rect',attr)
            elif e.kind=='diamond':
                ET.SubElement(svg,'polygon',{'points':f'{e.x+e.w/2},{e.y} {e.x+e.w},{e.y+e.h/2} {e.x+e.w/2},{e.y+e.h} {e.x},{e.y+e.h/2}', 'fill':e.fill,'stroke':e.border,'stroke-width':str(e.bw)})
            elif e.kind=='ellipse':
                ET.SubElement(svg,'ellipse',{'cx':str(e.x+e.w/2),'cy':str(e.y+e.h/2),'rx':str(e.w/2),'ry':str(e.h/2),'opacity':str(e.opacity/100),'fill':f'url(#grad{i})' if e.gradient else e.fill,'stroke':e.border,'stroke-width':str(e.bw)})
            elif e.kind=='label':
                lines=e.text.split('\n'); lh=e.size*1.35
                total=len(lines)*lh
                start=e.y+(e.h-total)/2+e.size*1.0 if e.valign=='middle' else e.y+e.size
                for j,ln in enumerate(lines):
                    tx= e.x+e.w/2 if e.align=='center' else (e.x+e.w if e.align=='right' else e.x)
                    ET.SubElement(svg,'text',{'x':str(tx),'y':str(start+j*lh),'font-family':FONT+', sans-serif','font-size':str(e.size),'font-weight':'700' if e.bold else '400','fill':e.color,'text-anchor': 'middle' if e.align=='center' else ('end' if e.align=='right' else 'start')}).text=ln
            elif e.kind=='line':
                x1,y1=e.p1;x2,y2=e.p2
                attr={'x1':str(x1),'y1':str(y1),'x2':str(x2),'y2':str(y2),'stroke':e.border,'stroke-width':str(e.bw),'stroke-linecap':'round'}
                if e.dash:attr['stroke-dasharray']='5 4'
                ET.SubElement(svg,'line',attr)
                if e.arrow:
                    a=math.atan2(y2-y1,x2-x1)
                    L=11+e.bw; ww=5+e.bw
                    poly=[]
                    for xx,yy in [(x2,y2),(x2-L*math.cos(a)+ww*math.sin(a),y2-L*math.sin(a)-ww*math.cos(a)),
                                   (x2-L*math.cos(a)-ww*math.sin(a),y2-L*math.sin(a)+ww*math.cos(a))]:
                        poly.append(f'{xx:.2f},{yy:.2f}')
                    ET.SubElement(svg,'polygon',{'points':' '.join(poly),'fill':e.border})
        ET.indent(svg,space='  ')
        path.write_bytes(ET.tostring(svg,encoding='utf-8',xml_declaration=True))

BLUE='#2F86CF'; NAVY='#245581'; PURPLE='#A27CDE'; ORANGE='#E89E32'; GREEN='#319963'

def fig1():
    c=Canvas('图1｜五状态执行控制与总体架构',1536,920)
    # top main control zone
    c.rect(25,10,1486,152,'#DEEFFD','#46AFF5',1.5,9,gradient='#E3F4FE')
    c.label('五状态执行控制',475,18,240,44,31,'#131920',True)
    c.label('(Five-State Execution Control)',717,18,380,44,27,'#16191C',True)
    c.rect(287,64,962,92,'#FFFFFF','#9ACBF5',1,12,shadow=True)
    stages=[('接收','INTAKE'),('校验','VALIDATE'),('执行','EXECUTE'),('门禁','GATE'),('输出','EMIT')]
    start=315
    for i,(cn,en) in enumerate(stages):
        x=start+i*191
        c.rect(x,77,149,69,'#EAF6FF','#2180D4',1.5,9,gradient='#DEEFFA',shadow=True)
        c.label(cn,x+6,81,137,31,24,'#131920',True)
        c.label(en,x+6,111,137,29,18,'#121720')
        if i<4:c.line(x+157,111,x+193,111,'#265D9B',3,True)
    # three sections
    c.rect(26,175,309,766,'#EAF7FF','#2687DC',1.3,13,True,gradient='#F5FBFF')
    c.rect(351,175,884,766,'#FFF2DF','#F19D30',1.3,14,True,gradient='#FFF9F0')
    c.rect(1251,175,260,766,'#EDF9EF','#38985A',1.3,14,True,gradient='#F6FCF6')
    c.label('输入契约',61,187,237,30,28,'#171C26',True)
    c.label('(Input Contract)',56,217,244,28,24,'#171C26',True)
    c.label('执行与协议适配',467,183,291,42,28,'#191B1D',True)
    c.label('(Execution and Protocol Adaptation)',739,183,405,39,23,'#191B1D')
    c.label('结果信封',1273,187,217,32,28,'#151A19',True)
    c.label('(Result Envelope)',1258,218,248,29,23,'#161C19',True)
    # left lane
    c.personicon(157,263,1.05)
    c.label('自然语言请求',66,315,240,31,22,'#1B1C25',True)
    c.label('(Natural Language Request)',38,347,287,30,19,'#1E2227')
    for yy in [398,495,592,692,796]: pass
    leftcards=[(399,'参数解析','(Parameter Parsing)'),(494,'参数校验','(Parameter Validation)'),(592,'语义校验','(Semantic Validation)'),(693,'任务规划','(Task Planning)'),(796,'执行准备','(Execution Preparation)')]
    for i,(y,t,en) in enumerate(leftcards):
        c.rect(54,y,261,74,'#F6FBFF','#287AC3',1.3,11,gradient='#FFFFFF')
        c.label(t,120,y+9,186,29,23,'#171C22',True)
        c.label(en,119,y+39,189,28,18,'#1A1B22')
        if i < len(leftcards)-1:c.line(180,y+74,180,leftcards[i+1][0]-4,'#245888',2.1,True)
    c.line(180,372,180,394,NAVY,2.1,True)
    c.docicon(75,417,0.8)
    c.docicon(76,514,0.8)
    c.nodesicon(73,607,0.8)
    c.docicon(77,709,0.82)
    # gear approximation: editable circle+spokes
    c.circle(90,833,15,'none',NAVY,5)
    for a in range(0,360,45):
        r1,r2=16,23
        c.line(90+math.cos(math.radians(a))*r1,833+math.sin(math.radians(a))*r1,90+math.cos(math.radians(a))*r2,833+math.sin(math.radians(a))*r2,NAVY,5)
    c.line(322,536,356,536,'#2D689E',5,True)
    # Tools panel
    c.rect(365,236,518,333,'#E8F6FF','#2D9BFA',1.2,9,gradient='#DFF2FF')
    c.label('七个原子工具',419,239,249,35,26,'#14264A',True)
    c.label('(7 Atomic Tools)',655,241,189,35,21,'#1A2744')
    tools=[('目录发现','(catalog_discovery)',382,279,'db'),('计数查询','(row_count)',637,279,'bars'),
           ('名称解析','(name_resolver)',382,351,'doc'),('分页读取','(paged_query)',637,351,'doc'),
           ('坐标锥搜','(cone_search)',382,423,'target'),('元数据查询','(metadata_query)',637,423,'doc'),
           ('批量交叉匹配','(batch_crossmatch)',382,495,'nodes')]
    for cn,en,x,y,icon in tools:
        c.rect(x,y,243,65,'#FFFFFF','#58AAF0',1.3,10,gradient='#F4FAFF',shadow=True)
        c.label(cn,x+77,y+7,156,25,22,'#16191D',True)
        c.label(en,x+68,y+34,166,25,17,'#23232A')
        if icon=='db':c.dbicon(x+27,y+20,0.65)
        elif icon=='doc':c.docicon(x+29,y+18,0.64)
        elif icon=='nodes':c.nodesicon(x+28,y+14,0.73)
        elif icon=='bars':
            for j,h in enumerate([18,28,39]):c.rect(x+29+j*9,y+51-h,6,h,NAVY,'none',0,2)
        else:
            c.circle(x+44,y+32,13,'none',NAVY,3)
            c.line(x+25,y+32,x+63,y+32,NAVY,2)
            c.line(x+44,y+14,x+44,y+50,NAVY,2)
    # protocol
    c.rect(896,236,327,331,'#E9F6FF','#58ABF4',1.2,9,gradient='#E2F2FF')
    c.label('协议适配网关',919,240,284,32,24,'#111822',True)
    c.label('(Protocol Gateway)',918,268,288,30,20,'#171F25')
    c.rect(906,305,307,234,'#FFFFFF','#9976DE',1.4,11,gradient='#F5F0FF')
    c.rect(907,305,304,66,'#DCD2F8','none',0,9,gradient='#EBE6FC')
    c.label('TAP/ADQL 适配',922,315,281,27,22,'#15151A',True)
    c.label('(TAP/ADQL Adapter)',921,341,281,27,19,'#141923')
    c.label('◆  同步查询（Sync Query）',928,388,266,34,18,'#151825',align='left')
    c.label('◆  异步查询（Async Query）',928,425,270,32,18,'#151825',align='left')
    c.label('◆  受支持查询子集',929,459,270,29,18,'#151825',align='left')
    c.label('(Supported Subset)',955,486,240,29,18,'#151825',align='left')
    c.line(877,409,902,409,'#2E6797',2.5,True)
    c.line(902,413,876,413,'#2E6797',2.5,True)
    # identity section
    c.rect(365,583,858,210,'#FFF2E2','#EAA43F',1.1,9,gradient='#FFF6EC')
    c.label('身份与访问控制  (Identity and Access Control)',520,578,612,40,23,'#161924',True)
    identity=[(373,620,271,'BEST 会话与 CSRF 令牌','(BEST Session & CSRF)', '#FCE3C6','#ED9E47',0),
              (650,620,281,'网关 Bearer 令牌与配额','(Gateway Bearer Token)', '#DDEFFF','#4FA4E8',1),
              (937,620,277,'NADC OAuth 2.0','(NADC OAuth 2.0)', '#FBE1CC','#F09C48',2)]
    for x,y,w,t,en,fill,stroke,i in identity:
        c.rect(x,y,w,167,fill,stroke,1.1,10,gradient='#FFF9F2' if i != 1 else '#EFF8FF')
        if i==0:c.lockicon(x+10,y+10,0.77)
        elif i==1:
            c.circle(x+36,y+33,13,'none',NAVY,7); c.line(x+23,y+45,x+10,y+59,NAVY,7)
        else:c.personicon(x+12,y+11,0.82)
        c.label(t,x+47,y+6,w-58,28,18,'#171A22',True)
        c.label(en,x+49,y+34,w-59,27,17,'#1C1D25')
    c.label('◆  会话管理',391,686,246,29,17,'#1C1B1D',align='left')
    c.label('(Session Management)',425,709,213,24,16,'#1C1B1D',align='left')
    c.label('◆  CSRF 防护',391,739,245,26,17,'#1C1B1D',align='left')
    c.label('(CSRF Protection)',425,760,213,25,16,'#1C1B1D',align='left')
    c.label('◆  访问授权',668,687,248,27,17,'#1C1B1D',align='left')
    c.label('(Access Control)',697,709,205,25,16,'#1C1B1D',align='left')
    c.label('◆  请求配额',668,737,245,27,17,'#1C1B1D',align='left')
    c.label('(Request Quota)',697,760,205,24,16,'#1C1B1D',align='left')
    c.label('◆  独立身份路径',953,687,245,27,17,'#1C1B1D',align='left')
    c.label('(Independent Identity)',983,709,205,25,16,'#1C1B1D',align='left')
    c.label('◆  来源记录与溯源',953,737,245,27,17,'#1C1B1D',align='left')
    c.label('(Source Record & Provenance)',978,760,226,25,14,'#1C1B1D',align='left')
    # best two-stage query
    c.rect(365,805,859,109,'#E8F5FF','#2793DF',1.3,9,gradient='#F7FCFF')
    c.dbicon(390,832,1.15)
    c.label('BEST 两阶段查询',490,808,249,31,23,'#161923',True)
    c.label('(Two-Stage Query on BEST)',749,808,407,31,21,'#161923')
    for j,yy in enumerate([852,886]):
        c.circle(485,yy,15,'#3E81CC')
        c.label(str(j+1),470,yy-14,30,28,18,'#FFFFFF',True)
    c.label('提交查询条件，获取 sqlid',526,838,345,32,19,'#171C25',align='left')
    c.label('(Submit query and obtain sqlid)',866,839,336,30,17,'#171C25',align='left')
    c.label('基于 sqlid 获取计数和分页结果',526,876,401,31,18,'#171C25',align='left')
    c.label('(Get count and paged results)',930,878,285,28,16,'#171C25',align='left')
    # Output panel
    c.rect(1267,266,229,134,'#FFFFFF','#B7D8C5',1,12,gradient='#F9FFFA')
    c.label('astro-envelope',1272,274,220,39,24,'#141B18',True)
    c.docicon(1356,328,1.3)
    outputs=[('schema','（结构定义）'),('status','（状态信息）'),('data','（数据载荷）'),
             ('data_hash','（内容哈希）'),('provenance','（来源记录）'),('lineage','（上下游关联）')]
    for i,(en,cn) in enumerate(outputs):
        y=412+i*80
        c.rect(1286,y,196,64,'#FFFFFF','#73B58B',1.2,10,gradient='#F2FAF3')
        c.label(en,1291,y+3,187,30,19,'#1C2224',True)
        c.label(cn,1290,y+33,188,24,19,'#23272A')
    c.line(1229,536,1258,536,'#2D689E',5,True)
    return c


def fig2():
    c=Canvas('图2｜数据准备与评测建模',1432,1098)
    c.rect(12,21,1381,103,'#3AA5FF','#1E7BCF',2,17,gradient='#0756B3',shadow=True)
    c.rect(17,25,1370,36,'#77C7FF','none',0,16,gradient='#2071D1')
    c.label('BEST-Skill 数据准备与评测建模',246,32,952,72,46,'#FFFFFF',True)
    for sx in [43,1303]: c.grid_decor(sx,56,6,4,10,9,'#82C4FC')
    # header zones (round card boxes and gradient ribbons)
    c.rect(24,139,671,805,'#E9F7FE','#7DC4FF',2,21,gradient='#F8FDFF')
    c.rect(713,139,674,805,'#F5E9FF','#BA84F3',2,21,gradient='#FDFCFF')
    c.rect(34,150,653,62,'#7FCFFF','none',0,13,gradient='#2B7CDF')
    c.rect(724,150,650,62,'#C797FD','none',0,13,gradient='#8237D7')
    c.label('一、数据准备',211,161,293,45,31,'#FFFFFF',True)
    c.label('二、评测建模',921,161,290,45,31,'#FFFFFF',True)
    c.grid_decor(598,178,7,3,10,9,'#B5E6FF')
    c.grid_decor(1295,178,7,3,10,9,'#DEBBFF')
    # blue left four cards
    left=[(33,227,652,163),(33,405,652,167),(33,588,652,168),(33,770,652,170)]
    right=[(725,226,649,164),(725,405,649,169),(725,588,649,168),(725,770,649,168)]
    for i,(x,y,w,h) in enumerate(left):
        c.rect(x,y,w,h,'#FFFFFF','#7EC8FA',2,14,gradient='#DFF2FE',shadow=True)
        c.rect(x+12,y+15,83,h-30,'#E7F7FF','none',0,13,gradient='#DEF1FC')
        c.circle(x+36,y+36,27,'#1689E5','#D8F0FF',2.5)
        c.circle(x+36,y+36,21,'#2699EF','#AFDDFF',1.3)
        c.label(str(i+1),x+16,y+16,40,41,27,'#FFFFFF',True)
    for i,(x,y,w,h) in enumerate(right):
        c.rect(x,y,w,h,'#FFFFFF','#B987EC',2,14,gradient='#F2E5FF',shadow=True)
        c.rect(x+15,y+15,106,h-30,'#F1E8FF','none',0,14,gradient='#FBF8FE')
        c.circle(x+40,y+39,27,'#9254D9','#F0DEFF',2.5)
        c.circle(x+40,y+39,21,'#A26AED','#D6B0FF',1.3)
        c.label(str(i+1),x+20,y+21,40,39,27,'#FFFFFF',True)
    titles=['题集、答案键与夹具冻结','答案键权限隔离','执行留痕与状态归档','结构化解析与字段核验']
    l1=[
       ['E1–E6 各组独立建集，每组 21–56 题','题面、标准答案、评分规则与检验夹具在正式运行前冻结'],
       ['答案键与模型、执行器分离保存','置于模型与执行器不可读的独立权限域'],
       ['实站查询、冻结回包与压力样本按批次执行','逐次保留请求、返回、最终回答、工具轨迹与状态'],
       ['评分前解析工具名、调用参数、数值字段、结果行集与运行状态','失败记录保留在相应分母中，不因补测而消失']]
    for i,(x,y,w,h) in enumerate(left):
        c.label(titles[i],x+120,y+19,w-141,46,25,'#122A58',True,'left')
        c.bullet(x+116,y+94,'#43A0FA',6)
        c.bullet(x+116,y+131,'#43A0FA',6)
        c.label(l1[i][0],x+136,y+77,w-157,32,16.7 if i==3 else 18.5,'#23334A',align='left')
        c.label(l1[i][1],x+136,y+115,w-157,32,18,'#23334A',align='left')
        # icon at left: each native element
        if i==0:c.docicon(x+43,y+83,0.84,'#2282D5')
        elif i==1:c.shieldicon(x+35,y+80,1.0,'#2282D5')
        elif i==2:c.clock_docicon(x+35,y+79,1.0,'#2282D5')
        else:c.checked_dbicon(x+39,y+92,0.95,'#2282D5')
    rtitles=['五层证据框架','判分分工','独立判据与分母','统计推断与重复一致性']
    for i,(x,y,w,h) in enumerate(right):
        c.label(rtitles[i],x+135,y+18,w-152,42,25,'#432B74',True,'left')
        if i==0:
            for k in range(3):
                c.diamond(x+73,y+87+13*k,24,10,'#9863E3')
            chip_labels=['格式 E1','契约 E2','语义 E3','边界 E4','运行 E6']
            start=x+132
            for n,t in enumerate(chip_labels):
                xx=start+n*98
                c.pill(t,xx,y+78,95,52,'#916ADD','#9679DC',16,'#FFFFFF',True)
                if n<4:c.label('›',xx+94,y+81,12,47,20,'#6B3EAF',True)
        elif i==1:
            c.docicon(x+49,y+87,1.0,'#986CE0')
            c.circle(x+86,y+126,13,'#A06CE9')
            c.line(x+80,y+127,x+85,y+132,'#FFFFFF',3)
            c.line(x+85,y+132,x+93,y+119,'#FFFFFF',3)
            c.bullet(x+143,y+95,'#AE67EC',6)
            c.bullet(x+143,y+133,'#AE67EC',6)
            c.label('结构化字段由程序逐项核验；科学断言按公开量规主评',x+162,y+78,w-175,35,17.2,'#29334D',align='left')
            c.label('工具选择、参数、轨迹与最终文本分别计分',x+162,y+116,w-175,35,18,'#29334D',align='left')
        elif i==2:
            c.barsicon(x+47,y+84,0.99,'#9366DB')
            c.bullet(x+143,y+96,'#AE67EC',6)
            c.bullet(x+143,y+132,'#AE67EC',6)
            c.label('各组使用独立判据、评分器与分母',x+162,y+78,w-175,34,19,'#29334D',align='left')
            c.label('不合并为单一总体能力分数',x+162,y+116,w-175,32,19,'#29334D',align='left')
        else:
            c.mini_charticon(x+48,y+88,0.99,'#9567DA')
            c.bullet(x+143,y+96,'#AE67EC',6)
            c.bullet(x+143,y+132,'#AE67EC',6)
            c.label('配对题号 Bootstrap 95% CI；二元结果精确 McNemar',x+162,y+77,w-175,38,16.6,'#29334D',align='left')
            c.label('重复一致性按题计算 TSC / PAC / RDC / FCC，再取宏平均',x+162,y+115,w-175,38,16.8,'#29334D',align='left')
    # bottom gold summary
    c.rect(22,957,1362,98,'#FFF5CE','#E5A600',2,15,gradient='#FFFCED',shadow=True)
    c.rect(43,974,74,74,'#FFD759','#F5B129',1.5,12,gradient='#F0A90B')
    c.label('Σ',48,977,63,70,43,'#FFFFFF',True)
    c.label('正式运行前冻结题集、夹具与答案键；各组按独立判据与分母分别报告，不合并为总体能力分数。',162,972,1190,73,24,'#8B5316',True,'left')
    return c


def all_file(canvases, path):
    mxfile=ET.Element('mxfile',{'host':'app.diagrams.net','agent':'BEST-Skill v50 reproducible native draw.io generator','version':'24.7.17','type':'device'})
    for i,c in enumerate(canvases):
        diag=ET.SubElement(mxfile,'diagram',{'name':c.title,'id':f'BEST-v50-Figure-{i+1}'})
        diag.append(c.graphmodel())
    ET.indent(mxfile,space='  ')
    path.write_bytes(ET.tostring(mxfile,encoding='utf-8',xml_declaration=True))


def fig1_v50_body_aligned(base=None):
    """Keep native layout; align tool names to the current v50 Section 2.2.1."""
    c=copy.deepcopy(base if base is not None else fig1())
    c.title='图1｜v50正文接口名称对齐版'
    replacements={
        '目录发现':'星表枚举',
        '(catalog_discovery)':'(list_catalogs)',
        '计数查询':'计数',
        '(row_count)':'(count)',
        '名称解析':'名称解析',
        '(name_resolver)':'(resolve_name)',
        '分页读取':'分页获取',
        '(paged_query)':'(fetch_page)',
        '坐标锥搜':'坐标锥搜',
        '元数据查询':'星表描述',
        '(metadata_query)':'(describe_catalog)',
        '(batch_crossmatch)':'(crossmatch_batch)',
    }
    for e in c.items:
        if e.kind=='label' and e.text in replacements:
            e.text=replacements[e.text]
        if e.kind=='label' and e.text in ('(crossmatch_batch)','(describe_catalog)','(list_catalogs)'):
            e.size=15.5
        if e.kind=='label' and e.text=='(fetch_page)':
            e.size=16
    return c


def fig2_v50_data_aligned(base=None):
    """Keep native layout; replace stale group-size generalization with v50 Table 1 counts."""
    c=copy.deepcopy(base if base is not None else fig2())
    c.title='图2｜v50评价数据对齐版'
    for e in c.items:
        if e.kind!='label':
            continue
        if e.text=='E1–E6 各组独立建集，每组 21–56 题':
            e.text='E1 26题×3次；E2 17场景；E3 32题号×2配置×3次\nE4 35话术+15协议故障；E6 32任务×5次'
            e.size=13.4
            e.y -= 3
            e.h = 42
        elif e.text=='题面、标准答案、评分规则与检验夹具在正式运行前冻结':
            e.y += 3
            e.h = 32
        elif e.text=='重复一致性按题计算 TSC / PAC / RDC / FCC，再取宏平均':
            e.text='重复一致性按题计算 TSC / PAC_call / RDC / FCC，再取宏平均'
            e.size=15.0
    return c


def save_canvas(c, stem):
    c.save_drawio(OUT/(stem+'.drawio'))
    c.save_svg(OUT/(stem+'.svg'))


