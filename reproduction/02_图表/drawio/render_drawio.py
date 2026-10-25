"""Render the actual native mxGraph files to vector PDF and high-resolution PNG.
Supports the editable primitive shapes used by the supplied diagram source.
No raster background, network access or proprietary renderer is required.
"""
from pathlib import Path
import xml.etree.ElementTree as ET
import html,re,math,json,argparse
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import colors,font_manager
from matplotlib.patches import FancyBboxPatch,Ellipse,Polygon,Rectangle
P=Path(__file__).resolve().parent
ap=argparse.ArgumentParser();ap.add_argument('--out',type=Path,default=P.parents[1]/'LaTeX/figures');ap.add_argument('--dpi',type=int,default=300);args=ap.parse_args();args.out.mkdir(parents=True,exist_ok=True)
fonts={x.name for x in font_manager.fontManager.ttflist};font=next((x for x in ['Microsoft YaHei','Noto Sans CJK SC','SimHei'] if x in fonts),None)
if not font:raise RuntimeError('A Chinese font is required: Microsoft YaHei / Noto Sans CJK SC / SimHei')
plt.rcParams.update({'font.family':font,'svg.fonttype':'none','pdf.fonttype':42,'axes.unicode_minus':False,'svg.hashsalt':'BEST-native-drawio'})
checks=[]
for stem in ['fig1_architecture','fig2_data_model']:
 tree=ET.parse(P/(stem+'.drawio'));model=tree.find('.//mxGraphModel');w=int(model.get('pageWidth'));h=int(model.get('pageHeight'))
 fig=plt.figure(figsize=(w/96,h/96),facecolor='white');ax=fig.add_axes([0,0,1,1]);ax.set(xlim=(0,w),ylim=(h,0));ax.axis('off');texts=[];count=0
 for idx,cell in enumerate(model.findall('.//mxCell')):
  style=cell.get('style','');st=dict(x.split('=',1) for x in style.split(';') if '=' in x);geo=cell.find('mxGeometry')
  if geo is None:continue
  assert 'image=' not in style and 'shape=image' not in style
  z=idx*3
  if cell.get('edge')=='1':
   pts={x.get('as'):(float(x.get('x')),float(x.get('y'))) for x in geo.findall('mxPoint')};a=pts['sourcePoint'];b=pts['targetPoint'];lw=float(st.get('strokeWidth',1))*72/96
   ax.plot([a[0],b[0]],[a[1],b[1]],color=st.get('strokeColor','#333'),lw=lw,ls=(0,(4,4)) if st.get('dashed')=='1' else '-',solid_capstyle='round',zorder=z)
   if st.get('endArrow')=='block':
    ang=math.atan2(b[1]-a[1],b[0]-a[0]);L=11+float(st.get('strokeWidth',1));ww=5+float(st.get('strokeWidth',1));x,y=b
    ax.add_patch(Polygon([(x,y),(x-L*math.cos(ang)+ww*math.sin(ang),y-L*math.sin(ang)-ww*math.cos(ang)),(x-L*math.cos(ang)-ww*math.sin(ang),y-L*math.sin(ang)+ww*math.cos(ang))],fc=st.get('strokeColor','#333'),ec='none',zorder=z+1))
   continue
  x,y,bw,bh=[float(geo.get(k,0)) for k in ['x','y','width','height']]
  if style.startswith('text;'):
   t=html.unescape(re.sub('<[^>]+>','',cell.get('value','').replace('<br>','\n')));size=float(st.get('fontSize',18));lh=size*1.35;lines=t.split('\n');start=y+(bh-len(lines)*lh)/2+size if st.get('verticalAlign')=='middle' else y+size
   align=st.get('align','center');tx=x+bw/2 if align=='center' else x+bw if align=='right' else x
   for j,line in enumerate(lines):
    obj=ax.text(tx,start+j*lh,line,fontsize=size*.75,color=st.get('fontColor','#222'),weight='bold' if st.get('fontStyle')=='1' else 'normal',ha=align,va='baseline',zorder=z);texts.append((obj,line,(x,y,bw,bh)))
   continue
  fill=st.get('fillColor','none');edge=st.get('strokeColor','none');shape=st.get('shape','rectangle');radius=float(st.get('arcSize',0))/100*min(bw,bh)/2
  def patch(fc,ec,dx=0,dy=0):
   if shape=='ellipse':return Ellipse((x+bw/2+dx,y+bh/2+dy),bw,bh,fc=fc,ec=ec)
   if shape=='rhombus':return Polygon([(x+bw/2+dx,y+dy),(x+bw+dx,y+bh/2+dy),(x+bw/2+dx,y+bh+dy),(x+dx,y+bh/2+dy)],fc=fc,ec=ec)
   return FancyBboxPatch((x+dx,y+dy),bw,bh,boxstyle=f'round,pad=0,rounding_size={radius}',fc=fc,ec=ec)
  if st.get('shadow')=='1':q=patch('#D6E3EF','none',2,4);q.set_zorder(z-1);ax.add_patch(q)
  q=patch(fill,edge);q.set_alpha(float(st.get('opacity',100))/100);q.set_lw(float(st.get('strokeWidth',1))*.75);q.set_zorder(z);ax.add_patch(q)
  if st.get('dashed')=='1':q.set_linestyle((0,(4,4)))
  if 'gradientColor' in st:
   q.set_facecolor('none');a=np.array(colors.to_rgb(fill));b=np.array(colors.to_rgb(st['gradientColor']))
   for k in range(80):
    c=a+(b-a)*(k+.5)/80;r=Rectangle((x,y+k*bh/80),bw,bh/80+.02,fc=c,ec='none',zorder=z-.1);r.set_clip_path(q);r.set_alpha(float(st.get('opacity',100))/100);ax.add_patch(r)
  count+=1
 fig.canvas.draw();renderer=fig.canvas.get_renderer();bad=[]
 for t,line,box in texts:
  bb=t.get_window_extent(renderer)
  if bb.x0<fig.bbox.x0-1 or bb.y0<fig.bbox.y0-1 or bb.x1>fig.bbox.x1+1 or bb.y1>fig.bbox.y1+1:bad.append(line)
 if bad:raise RuntimeError(f'{stem}: text outside canvas: {bad}')
 fig.savefig(args.out/(stem+'.png'),dpi=args.dpi)
 fig.savefig(args.out/(stem+'.pdf'),metadata={'CreationDate':None,'ModDate':None,'Creator':'Native draw.io source renderer'})
 # This renderer also provides a vector export of the actual parsed draw.io geometry.
 fig.savefig(args.out/(stem+'.svg'),metadata={'Date':None,'Creator':'Native draw.io source renderer'})
 plt.close(fig);checks.append({'figure':stem,'native_shapes':count,'editable_text_lines':len(texts),'canvas': [w,h],'font':font,'out_of_canvas_text':bad})
(P/'render_validation.json').write_text(json.dumps(checks,ensure_ascii=False,indent=2),encoding='utf-8')
print('Rendered native draw.io files:',checks)
