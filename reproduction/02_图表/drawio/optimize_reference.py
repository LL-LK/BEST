"""Reference-aligned refinements; all additions are editable mxGraph primitives."""
def install(g):
    C=g.Canvas
    def database(c,x,y,s=1,color='#285B89'):
        for yy in [22,11,0]:
            c.rect(x,y+(yy+6)*s,39*s,11*s,color,'none',0)
            c.items.append(g.Element('ellipse',x,y+(yy+10)*s,39*s,13*s,color,'#FFFFFF',1.2*s,shape='ellipse'))
            c.items.append(g.Element('ellipse',x,y+yy*s,39*s,13*s,color,'#FFFFFF',1.2*s,shape='ellipse'))
    def document(c,x,y,s=1,color='#26557F'):
        c.rect(x,y,32*s,39*s,'#FFFFFF',color,3*s,4*s)
        c.line(x+7*s,y+10*s,x+25*s,y+10*s,color,3*s)
        for i,w in enumerate([18,13,18]):
            c.line(x+7*s,y+(19+7*i)*s,x+(7+w)*s,y+(19+7*i)*s,color,2.5*s)
        if abs(x-75)<1 and abs(y-417)<1:
            c.circle(x+27*s,y+29*s,8*s,'white',color,2.5*s)
            c.line(x+33*s,y+35*s,x+41*s,y+43*s,color,3*s)
        if abs(x-76)<1 and abs(y-514)<1:
            c.rect(x+9*s,y-3*s,15*s,6*s,'white',color,2*s,2*s)
    old=C.docicon
    def doc_or_search(c,x,y,s=1,color='#26557F'):
        if abs(x-411)<1 and abs(y-369)<1:
            c.circle(x+12*s,y+13*s,13*s,'none',color,3*s)
            c.line(x+22*s,y+23*s,x+36*s,y+38*s,color,3.5*s)
        else:document(c,x,y,s,color)
    C.dbicon=database;C.docicon=doc_or_search
    original=C.mini_charticon
    def chart(c,x,y,s=1,color='#9567DA'):
        c.line(x,y+2*s,x,y+43*s,color,3*s)
        c.line(x,y+43*s,x+43*s,y+43*s,color,3*s)
        original(c,x,y,s,color)
    C.mini_charticon=chart

def refine(c1,c2,g):
    # Figure 1: lighter typography and tighter heading groups, like the reference.
    for e in c1.items:
        if e.kind=='label':
            if e.text=='五状态执行控制':e.text='五状态执行控制  (Five-State Execution Control)';e.x=300;e.w=936;e.size=26
            if e.text=='(Five-State Execution Control)':e.x=744;e.w=530;e.size=25
            if e.text=='执行与协议适配':e.text='执行与协议适配  (Execution and Protocol Adaptation)';e.x=365;e.w=858;e.size=22
            if e.text=='(Execution and Protocol Adaptation)':e.x=718;e.w=485;e.size=21
            if e.bold and e.size==22:e.size=20
            if e.text=='七项原子工具':e.size=23
            if e.text=='(7 Atomic Tools)':e.size=19
            if e.text=='身份与访问控制  (Identity and Access Control)':e.size=21
        if e.kind=='rect' and e.shadow:e.shadow=False
    c1.items=[e for e in c1.items if not(e.kind=='label' and e.text in ['(Five-State Execution Control)','(Execution and Protocol Adaptation)'])]
    # Header strips retain the original blue / orange / green architecture lanes.
    for x,w,col in [(26,309,'#DDF2FE'),(351,884,'#FFF1DC'),(1251,260,'#E6F4E9')]:
        band=g.Element('rect',x+1,176,w-2,75,col,'none',0,12,gradient='#FFFFFF')
        index=next(i for i,e in enumerate(c1.items) if e.kind=='rect' and e.x==x and e.y==175)
        c1.items.insert(index+1,band)
    # Figure 2: number medallions sit above distinct icon tiles, as in the reference.
    for e in c2.items:
        if e.kind=='rect':
            if e.w in [83,106] and 230<=e.y<=800:
                e.y+=47;e.h-=47
            if e.w==95 and e.h==52:
                e.w=84;e.fill='#AA8CF0';e.gradient='#7651DB';e.radius=10;e.shadow=True
            if e.w==1370 and e.h==36:
                e.h=24;e.fill='#6DBAFF';e.gradient='#3689DF'
            if e.w in [652,649] and e.h>=160:
                e.shadow=False;e.gradient='#EDF8FF' if e.x<700 else '#F7F2FF'
        if e.kind=='ellipse' and e.w in [42,54]:
            e.gradient='#096CCD' if e.x<700 else '#7436CA'
        if e.kind=='label':
            if e.text in ['映射 E1','契约 E2','语义 E3','边界 E4','运行 E6']:
                e.w=80;e.size=15.5
            if e.text.startswith('E1：26题'):
                e.text='E1、E2、E3、E4、E6 分组组织评价任务';e.size=18;e.h=32
            if e.text=='BEST-Skill 数据准备与评价设计':e.size=43
    # Subtle curved highlights are native translucent ellipses, never bitmaps.
    for x,y,w,h in [(12,21,1381,103),(34,150,653,62),(724,150,650,62)]:
        index=next(i for i,e in enumerate(c2.items) if e.kind=='rect' and e.x==x and e.y==y)
        shine=g.Element('ellipse',x+18,y+4,w*.43,h*.40,'#FFFFFF','none',0,shape='ellipse',opacity=10)
        c2.items.insert(index+1,shine)
    # Close the whole page with the fine frame and footer divider in the reference.
    c2.items.insert(0,g.Element('rect',12,20,1382,1047,'#FFFFFF','#B5E3FE',1.3,20))
    c2.line(140,973,140,1041,'#F2BD30',1.5)
