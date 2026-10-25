"""Align Figure 2 to Figure 1's architecture-diagram visual grammar."""
def align(c):
    c.items=[e for e in c.items if not (
        (e.kind=='ellipse' and ((e.w<5 and e.y<220) or e.w==42 or e.opacity<100)) or
        (e.kind=='rect' and e.w==1370) or
        (e.kind=='line' and e.p1==(140,973)))]
    for e in c.items:
        e.shadow=False
        if e.kind=='label':
            e.color='#17232C'
            if e.text=='BEST-Skill 数据准备与评价设计':e.size=36
            if e.text in ['一、数据准备','二、评价与统计']:e.size=28
            if e.text in ['1','2','3','4']:e.color='#245581';e.size=24
            if e.text=='Σ':e.color='#317452';e.size=36
            if e.text.startswith('固定研究条件'):e.color='#255B40';e.size=24
        elif e.kind=='line':
            if e.border not in ['white','#FFFFFF']:e.border='#245581'
        else:
            # Match Figure 1: blue outlines, restrained corner radii and pale fills.
            if e.fill=='#EDF8FF':e.fill='#FFFFFF'
            elif e.fill not in ['none','white','#FFFFFF']:e.fill='#245581'
            if e.border not in ['none','white','#FFFFFF']:e.border='#4699D9'
            e.bw=min(e.bw,1.4);e.gradient=None
            if e.kind=='rect':
                e.radius=min(e.radius,10)
                if e.w>1300 and e.y<100:
                    e.fill='#DEEFFD';e.gradient='#E3F4FE';e.border='#46AFF5'
                elif e.w>650 and e.h>700:
                    e.fill='#EAF7FF' if e.x<700 else '#FFF4E7'
                    e.gradient='#F8FCFF' if e.x<700 else '#FFFBF4'
                    e.border='#2687DC' if e.x<700 else '#EAA43F';e.dotted=True
                elif e.w>600 and e.h==62:
                    e.fill='#E5F3FD' if e.x<700 else '#FFF0DC'
                    e.gradient='#F6FBFF' if e.x<700 else '#FFF9EF';e.border='#91C5EA' if e.x<700 else '#EBC18B'
                elif e.w>600 and 150<e.h<180:
                    e.fill='#FFFFFF';e.gradient='#F4FAFF' if e.x<700 else '#FFFAF1'
                    e.border='#58AAF0' if e.x<700 else '#E4B779'
                elif e.w in [83,106]:
                    e.fill='#EFF7FC';e.gradient='#F6FBFF';e.border='none'
                elif e.w==84 and e.h==52:
                    e.fill='#EAF6FF';e.gradient='#F9FCFF';e.border='#58AAF0'
                elif e.y>950:
                    e.fill='#EFF8F0';e.gradient='#FAFDFA';e.border='#73B58B'
            if e.kind=='ellipse' and e.w==54:
                e.fill='#FFFFFF';e.border='#58AAF0';e.bw=1.4
    # The page frame must remain behind all panels, not become a dark rectangle.
    c.items[0].fill='#FFFFFF';c.items[0].gradient=None;c.items[0].border='#C8DFEE'
