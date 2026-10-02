from studio.machine_setup import activate
activate()
import argparse,os,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent

def main():
 from studio.core import new,store,read,action
 p=argparse.ArgumentParser(description='Local Puppet Studio');p.add_argument('--project',type=Path,default=ROOT/'projects/my_project');sub=p.add_subparsers(dest='command');s=sub.add_parser('studio');s.add_argument('--no-browser',action='store_true');s.add_argument('--port',type=int,default=0);sub.add_parser('init');sub.add_parser('handoff');s=sub.add_parser('render');s.add_argument('--production',action='append');s.add_argument('--preview',action='store_true');s=sub.add_parser('task');s.add_argument('request',type=Path);s=sub.add_parser('action');s.add_argument('name');s.add_argument('--args',default='{}');a=p.parse_args();root=a.project.expanduser().resolve()
 if not (root/'project.json').exists():root.mkdir(parents=True,exist_ok=True);store(root,new())
 log=lambda x:print(x,flush=True)
 if a.command in [None,'studio']:
  from studio.server import serve;serve(root,getattr(a,'port',0),not getattr(a,'no_browser',False));return
 if a.command=='init':return
 if a.command=='render':action(root,'render',{'productions':a.production,'preview':a.preview},log)
 elif a.command=='handoff':action(root,'handoff',{},log)
 elif a.command=='task':d=read(a.request);action(root,d['action'],d['args'],log)
 elif a.command=='action':
  import json;action(root,a.name,json.loads(a.args),log)
 if os.name=='nt':
  try:
   import winsound;winsound.Beep(1100,600)
  except Exception:pass
if __name__=='__main__':
 try:main()
 except KeyboardInterrupt:print('Interrupted. Outputs retained.');sys.exit(130)
 except Exception as e:
  print('ERROR:',e,flush=True)
  if os.name=='nt':
   try:
    import winsound;winsound.Beep(330,600)
   except Exception:pass
  sys.exit(1)
