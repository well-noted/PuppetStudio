import argparse,subprocess,sys
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--project',type=Path,default=Path(__file__).parent/'projects/my_project');p.add_argument('--production',action='append',default=[]);p.add_argument('--preview',action='store_true');a=p.parse_args();cmd=[sys.executable,str(Path(__file__).parent/'studio.py'),'--project',str(a.project),'render']
for key in a.production:cmd+=['--production',key]
if a.preview:cmd.append('--preview')
sys.exit(subprocess.call(cmd))
