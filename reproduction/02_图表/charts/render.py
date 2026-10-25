"""Offline SVG rendering, completing the render module referenced by the source ZIP.
Uses Python Playwright and Chromium to preserve SVG gradients, bevels and fonts.
"""
from pathlib import Path
import argparse,json,re,shutil
from playwright.sync_api import sync_playwright
HERE=Path(__file__).resolve().parent
MAP={'fig_c1_E1_batches':'fig3_e1','fig_c2_E3_semantics':'fig4_e3','fig_c3_E4_disposition':'fig5_e4','fig_c4_E6_repeatability':'fig6_e6'}
def render(svg,dst,cw,ch,scale=1):
    svg=Path(svg).resolve();dst=Path(dst).resolve()
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True, channel='msedge')
        page=browser.new_page(viewport={'width':int(cw),'height':int(ch)},device_scale_factor=scale)
        page.set_content('<html><head><style>html,body{margin:0;padding:0;background:white}svg{display:block}</style></head><body>'+svg.read_text(encoding='utf-8')+'</body></html>')
        page.evaluate('document.fonts.ready');page.screenshot(path=str(dst),full_page=True)
        browser.close()
    return True
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--out',type=Path,default=HERE.parents[1]/'LaTeX/figures');ap.add_argument('--width',type=int,default=1640);args=ap.parse_args();args.out.mkdir(parents=True,exist_ok=True)
    qa=[]
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True, channel='msedge')
        for src,dest in MAP.items():
            f=HERE/(src+'.svg');text=f.read_text(encoding='utf-8');cw,ch=map(float,re.search(r'viewBox="0 0 ([\d.]+) ([\d.]+)"',text).groups())
            page=browser.new_page(viewport={'width':int(cw),'height':int(ch)},device_scale_factor=args.width/cw)
            page.set_content('<html><head><style>html,body{margin:0;padding:0;background:white}svg{display:block}@page{margin:0}</style></head><body>'+text+'</body></html>')
            page.evaluate('document.fonts.ready')
            outside=page.evaluate('''() => { const svg=document.querySelector('svg'),r=svg.getBoundingClientRect(); return [...svg.querySelectorAll('text')].map(t=>({text:t.textContent,r:t.getBoundingClientRect()})).filter(x=>x.r.left < r.left-1 || x.r.right > r.right+1 || x.r.top < r.top-1 || x.r.bottom > r.bottom+1).map(x=>x.text); }''')
            if outside:raise RuntimeError(f'{src}: clipped text {outside}')
            page.screenshot(path=str(args.out/(dest+'.png')),full_page=True)
            page.pdf(path=str(args.out/(dest+'.pdf')),width=f'{cw}px',height=f'{ch}px',print_background=True,margin={k:'0' for k in ['top','bottom','left','right']},prefer_css_page_size=False)
            shutil.copy2(f,args.out/(dest+'.svg'))
            qa.append({'figure':dest,'canvas':[cw,ch],'text_nodes':page.locator('svg text').count(),'clipped_text':outside})
            page.close()
        browser.close()
    (HERE/'render_validation.json').write_text(json.dumps(qa,ensure_ascii=False,indent=2),encoding='utf-8');print(qa)
if __name__=='__main__':main()

