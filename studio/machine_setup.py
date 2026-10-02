"""Per-user Windows dependency management. No changes to external environments."""
import hashlib,json,os,platform,re,shutil,subprocess,sys,time,urllib.request,zipfile
from pathlib import Path
from .core import ROOT,load,store,save,read,digest
UV_VERSION='0.8.22'
SADTALKER_COMMIT='cd4c0465ae0b54a6f85af57f5c65fec9fe23e7f8'
MODEL_BASE='https://github.com/OpenTalker/SadTalker/releases/download/v0.0.2-rc/'
MODELS=['mapping_00109-model.pth.tar','mapping_00229-model.pth.tar','SadTalker_V0.0.2_256.safetensors','SadTalker_V0.0.2_512.safetensors']
FACEX_BASE='https://github.com/xinntao/facexlib/releases/download/'

def home():return Path(os.environ.get('STUDIO_TOOLS_HOME',str(Path(os.environ.get('LOCALAPPDATA',Path.home()/'.local/share'))/'PuppetStudio'/'tools'))).expanduser().resolve()
def shared_paths():
 try:
  cfg=read(home()/'verified_animation.json');repo=Path(cfg['sadtalker_repo']);python=Path(cfg['sadtalker_python'])
  if (repo/'inference.py').is_file() and python.is_file():return {'sadtalker_repo':str(repo),'sadtalker_python':str(python)}
 except (OSError,ValueError,KeyError,TypeError):pass
 return {}

def inherit_tools(project):
 cfg=project['settings'];saved=shared_paths()
 if not cfg.get('sadtalker_repo') and not cfg.get('sadtalker_python'):cfg.update(saved)
 return project

def remember_verified(cfg,report):
 checks={x['name']:x['status'] for x in report.get('checks',[])}
 if checks.get('CUDA import test')!='ok' or checks.get('SadTalker startup')!='ok':return False
 repo=Path(cfg.get('sadtalker_repo',''));python=Path(cfg.get('sadtalker_python',''))
 if not (repo/'inference.py').is_file() or not python.is_file():return False
 save(home()/'verified_animation.json',{'sadtalker_repo':str(repo),'sadtalker_python':str(python),'verified_at':time.time()});return True

def activate():
 bin=home()/'ffmpeg/bin'
 if bin.is_dir():os.environ['PATH']=str(bin)+os.pathsep+os.environ.get('PATH','')
 os.environ.setdefault('PYTHONIOENCODING','utf-8');os.environ.setdefault('PYTHONUTF8','1')

def run(args,log=print,timeout=None):
 log('RUN: '+' '.join(map(str,args)))
 from .queue import command
 logfile=home()/'setup.log';command(args,logfile,log)

def download(url,dest,log=print):
 dest=Path(dest);dest.parent.mkdir(parents=True,exist_ok=True);receipt=dest.with_suffix(dest.suffix+'.download.json')
 if dest.is_file() and receipt.is_file():
  meta=read(receipt)
  if meta.get('url')==url and meta.get('sha256')==digest(dest):log('REUSE: '+dest.name);return dest
 part=dest.with_suffix(dest.suffix+'.partial');log('Downloading '+dest.name)
 request=urllib.request.Request(url,headers={'User-Agent':'PuppetStudio-Alpha'})
 try:
  with urllib.request.urlopen(request,timeout=60) as response,part.open('wb') as f:
   total=int(response.headers.get('Content-Length',0));count=0;last=time.monotonic();hasher=hashlib.sha256()
   while block:=response.read(1024*1024):
    f.write(block);hasher.update(block);count+=len(block)
    if time.monotonic()-last>5:log(f'{dest.name}: {count//1048576} MiB'+(f' / {total//1048576} MiB' if total else ''));last=time.monotonic()
  if not count or (total and count!=total):raise ValueError('Incomplete download: '+dest.name)
  part.replace(dest);save(receipt,{'url':url,'sha256':hasher.hexdigest(),'bytes':count})
 except BaseException:
  part.unlink(missing_ok=True);raise
 return dest

def unzip(archive,dest):
 dest=Path(dest).resolve();dest.mkdir(parents=True,exist_ok=True)
 with zipfile.ZipFile(archive) as z:
  for info in z.infolist():
   target=(dest/info.filename).resolve()
   if not target.is_relative_to(dest) or '\\' in info.filename or (info.external_attr>>16)&0o170000==0o120000:raise ValueError('Unsafe archive entry')
  z.extractall(dest)

def inventory():
 activate();gpus=[]
 tool=shutil.which('nvidia-smi')
 if tool:
  try:
   r=subprocess.run([tool,'--query-gpu=name,memory.total','--format=csv,noheader,nounits'],capture_output=True,text=True,timeout=10)
   for line in r.stdout.splitlines():
    name,mem=line.rsplit(',',1);gpus.append({'name':name.strip(),'vram_mib':int(mem.strip())})
  except (OSError,ValueError,subprocess.TimeoutExpired):pass
 mem=min((g['vram_mib'] for g in gpus),default=0)
 return {'platform':platform.system(),'architecture':platform.machine(),'python':sys.executable,'python_version':platform.python_version(),'tools_home':str(home()),'free_gib':round(shutil.disk_usage(home() if home().exists() else Path.home()).free/2**30,1),'gpus':gpus,'ffmpeg':shutil.which('ffmpeg'),'ffprobe':shutil.which('ffprobe'),'suggested_preset':'low-memory' if 0<mem<=6144 else 'standard' if mem else 'composition','saved_animation':bool(shared_paths()),'note':'NVIDIA device detection is not a CUDA model test. A speaking preview verifies actual inference.'}

def nearby_checkouts(base,max_depth=3,max_directories=600):
 # Bounded read-only directory search; skip environments, caches and symlinks.
 from collections import deque
 excluded={'appdata','node_modules','models','checkpoints','anaconda3','miniconda3','miniforge3','mambaforge','envs','site-packages','windows','program files','program files (x86)'}
 pending=deque([(Path(base),0)]);visited=0;found=[];deadline=time.monotonic()+10
 while pending and visited<max_directories and time.monotonic()<deadline:
  folder,depth=pending.popleft();visited+=1
  if folder.name.lower()=='sadtalker' and (folder/'inference.py').is_file():found.append(folder.resolve());continue
  if depth>=max_depth:continue
  try:
   children=[]
   with os.scandir(folder) as entries:
    for i,item in enumerate(entries):
     if i>=2000 or time.monotonic()>=deadline:break
     if not item.name.startswith('.') and item.name.lower() not in excluded and item.is_dir(follow_symlinks=False):children.append(Path(item.path))
   for child in sorted(children,key=lambda x:(x.name.lower() not in ['sadtalker','liveportrait'],x.name.lower())):pending.append((child,depth+1))
  except OSError:continue
 return found

def repos(root,cfg):
 result=[]
 for value in [cfg.get('sadtalker_repo'),shared_paths().get('sadtalker_repo'),os.environ.get('SADTALKER_REPO'),str(home()/'SadTalker')]:
  if value:
   p=Path(value.strip().strip('"')).expanduser()
   if (p/'inference.py').is_file() and p not in result:result.append(p)
 for base in [Path(root),Path(root).parent,ROOT,ROOT.parent]:
  for rel in ['SadTalker','LivePortrait/SadTalker','../LivePortrait/SadTalker']:
   p=(base/rel).resolve()
   if (p/'inference.py').is_file() and p not in result:result.append(p)
 for p in nearby_checkouts(Path.home()):
  if p not in result:result.append(p)
 return result

def discover(root,log=print):
 p=load(root);cfg=p['settings'];log('Searching configured, managed, adjacent and user-home folders for SadTalker (home search: 3 levels, up to 600 folders / 10 seconds).');found=repos(root,cfg)
 log('Found '+str(len(found))+' SadTalker checkout(s).')
 attempts=[];report=None
 sys.path.insert(0,str(ROOT/'engine/backend'))
 from discover_sadtalker import candidates
 from .diagnostics import check
 for repo in found:
  paths=[]
  if cfg.get('sadtalker_python'):paths.append(Path(cfg['sadtalker_python']))
  if shared_paths().get('sadtalker_python'):paths.append(Path(shared_paths()['sadtalker_python']))
  paths.append(home()/'sadtalker-env/Scripts/python.exe')
  try:candidates_found,notes=candidates(repo,ROOT)
  except (OSError,ValueError) as error:candidates_found=[];notes=[str(error)]
  paths+=candidates_found
  for note in notes:log('Discovery note: '+note)
  log('Checkout: '+str(repo))
  for executable in dict.fromkeys(paths):
   if not executable.is_file():continue
   log('Checking existing animation Python: '+str(executable))
   test=json.loads(json.dumps(p));test['settings'].update(sadtalker_repo=str(repo),sadtalker_python=str(executable),backend='sadtalker')
   report=check(root,test,True,log=log)
   attempts.append({'repo':str(repo),'python':str(executable),'report':report})
   checks={x['name']:x['status'] for x in report['checks']}
   if checks.get('CUDA import test')=='ok' and checks.get('SadTalker startup')=='ok':
    p['settings'].update(sadtalker_repo=str(repo),sadtalker_python=str(executable));store(root,p);remember_verified(p['settings'],report);save(Path(root)/'work/discovery_report.json',{'found':True,'checkouts':[str(x) for x in found],'attempts':attempts});log('Discovery report saved in work/discovery_report.json.');log('Verified paths saved for this project and future projects on this computer. No existing environment was changed.');return {'found':True,'repo':str(repo),'python':str(executable)}
 summary={'found':False,'checkouts':[str(x) for x in found],'attempts':attempts,'search':'Configured paths, shared verified tools, managed install, adjacent folders, and user home (depth 3, 600 folders, 10 seconds).'}
 save(Path(root)/'work/discovery_report.json',summary)
 if report is None:
  message='No SadTalker checkout found in the bounded search. Set its folder under Advanced → Animation environment, or use managed installation.' if not found else 'Found SadTalker checkout(s), but no existing Python executable to test. Set its CUDA python.exe under Advanced → Animation environment.'
  report={'checks':[{'name':'Animation discovery','status':'error','message':message}],'errors':1,'model_test_requested':True}
 report={**report,'discovery':summary};save(Path(root)/'work/setup_report.json',report)
 log('No verified existing CUDA environment found. Reports saved in work/discovery_report.json and work/setup_report.json.');return {'found':False}

def install(root,animation=True,log=print):
 if os.name!='nt' or platform.machine().lower() not in ['amd64','x86_64']:raise ValueError('Managed installation currently supports Windows x64. Other platforms can use existing installations.')
 tools=home();tools.mkdir(parents=True,exist_ok=True);lock=tools/'INSTALL_RUNNING.lock'
 try:
  with lock.open('x') as f:f.write(str(os.getpid()))
 except FileExistsError:raise ValueError('An installation is running, or its interrupted lock needs inspection: '+str(lock))
 try:
  if shutil.disk_usage(tools).free<15*2**30:raise ValueError('Managed animation setup needs at least 15 GiB free during installation.')
  uv=tools/'uv/uv.exe'
  if not uv.is_file():
   archive=download(f'https://github.com/astral-sh/uv/releases/download/{UV_VERSION}/uv-x86_64-pc-windows-msvc.zip',tools/'downloads/uv.zip',log);unzip(archive,tools/'uv')
  if not uv.is_file():raise ValueError('uv archive did not contain uv.exe')
  ff=tools/'ffmpeg/bin'
  if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
   archive=download('https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip',tools/'downloads/ffmpeg.zip',log);unzip(archive,tools/'ffmpeg-extract');ff.mkdir(parents=True,exist_ok=True)
   for name in ['ffmpeg.exe','ffprobe.exe']:
    candidates=list((tools/'ffmpeg-extract').rglob(name))
    if len(candidates)!=1:raise ValueError('Cannot identify '+name+' in archive')
    shutil.copy2(candidates[0],ff/name)
  activate()
  studio_python=ROOT/'.venv/Scripts/python.exe'
  if not studio_python.is_file():raise ValueError('Launch through launch.cmd to create the isolated Studio environment before managed installation.')
  run([studio_python,'-m','pip','install','faster-whisper>=1.1,<2','av>=11,<19','mediapipe>=0.10,<0.11'],log)
  p=load(root);requested_animation=animation
  if animation and discover(root,log).get('found'):
   p=load(root);p['settings']['backend']='sadtalker';animation=False;log('Reusing verified animation environment; no model download needed.')
  if animation:
   machine=inventory()
   if not machine['gpus']:raise ValueError('No NVIDIA GPU detected. Local transcription/composition were installed; CUDA animation needs supported hardware/drivers.')
   repo=tools/'SadTalker';source=tools/'sadtalker-source.json'
   if not (repo/'inference.py').is_file():
    archive=download(f'https://github.com/OpenTalker/SadTalker/archive/{SADTALKER_COMMIT}.zip',tools/'downloads/sadtalker.zip',log);unzip(archive,tools/'source-extract');matches=list((tools/'source-extract').glob('SadTalker-*'))
    if len(matches)!=1:raise ValueError('Unexpected SadTalker source archive')
    shutil.copytree(matches[0],repo);save(source,{'commit':SADTALKER_COMMIT})
   env=tools/'sadtalker-env';python=env/'Scripts/python.exe'
   if not python.is_file():run([uv,'venv','--python','3.10','--python-preference','only-managed',env],log)
   run([uv,'pip','install','--python',python,'torch==1.12.1+cu113','torchvision==0.13.1+cu113','torchaudio==0.12.1','--extra-index-url','https://download.pytorch.org/whl/cu113','--index-strategy','unsafe-best-match'],log)
   constraints=tools/'constraints.txt';constraints.write_text('numpy==1.23.4\nnumba==0.57.1\nllvmlite==0.40.1\nav>=11,<13\nopencv-python<4.9\n')
   run([uv,'pip','install','--python',python,'-r',repo/'requirements.txt','-c',constraints],log)
   for name in MODELS:download(MODEL_BASE+name,repo/'checkpoints'/name,log)
   for tag,name in [('v0.1.0','alignment_WFLW_4HG.pth'),('v0.1.0','detection_Resnet50_Final.pth'),('v0.2.2','parsing_parsenet.pth')]:download(FACEX_BASE+tag+'/'+name,repo/'gfpgan/weights'/name,log)
   download('https://github.com/TencentARC/GFPGAN/releases/download/v1.3.0/GFPGANv1.4.pth',repo/'gfpgan/weights/GFPGANv1.4.pth',log)
   from .diagnostics import check
   test=json.loads(json.dumps(p));test['settings'].update(backend='sadtalker',sadtalker_repo=str(repo),sadtalker_python=str(python));report=check(root,test,True,log=log)
   if report['errors']:raise ValueError('Managed setup verification failed. See work/setup_report.json; project paths were not switched.')
   p['settings'].update(backend='sadtalker',sadtalker_repo=str(repo),sadtalker_python=str(python))
   remember_verified(p['settings'],report)
  store(root,p);save(tools/'installed.json',{'recipe':1,'time':time.time(),'machine':inventory(),'animation':requested_animation});log('Setup verified and paths saved. Render a short speaking preview to verify weights and animation.')
 finally:lock.unlink(missing_ok=True)
