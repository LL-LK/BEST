from pathlib import Path
import subprocess,sys
P=Path(__file__).resolve().parent
for script,args in [('drawio/refine_drawio.py',[]),('drawio/render_drawio.py',['--dpi','200']),('charts/make_charts.py',[]),('charts/render.py',[])]:
    subprocess.run([sys.executable,str(P/script),*args],cwd=P/script.split('/')[0],check=True)
print('Figures 1-6 exported to LaTeX/figures')
