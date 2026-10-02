"""Locate existing SadTalker environments; report each actual failure separately."""
import json,os,shutil,subprocess,sys
from pathlib import Path

CUDA_PROBE = '''import json
result={}
try:
 import torch
 result.update(torch_version=torch.__version__,torch_cuda_build=torch.version.cuda,cuda_available=torch.cuda.is_available())
 if result['cuda_available']: result['device']=torch.cuda.get_device_name(0)
except Exception as e: result['torch_error']=type(e).__name__+': '+str(e)
print('SADTALKER_PROBE='+json.dumps(result))
'''

def locate_repo(root):
    repos=[]
    for base in (root,root.parent,Path.cwd()):
        for relative in ('SadTalker','LivePortrait/SadTalker','../SadTalker','../LivePortrait/SadTalker'):
            candidate=(base/relative).resolve()
            if (candidate/'inference.py').is_file() and candidate not in repos:repos.append(candidate)
    if len(repos)!=1:raise ValueError('Could not identify one SadTalker checkout. Use configure.py --sadtalker PATH --python PATH_TO_ITS_PYTHON')
    return repos[0]

def candidates(repo,root):
    found=[];notes=[]
    def add(p):
        p=Path(p).expanduser().resolve()
        if p.is_file() and p not in found:found.append(p)
    def environment(base):
        for relative in ('python.exe','bin/python'):add(Path(base)/relative)
    explicit=os.environ.get('SADTALKER_PYTHON')
    if explicit:
        add(explicit)
        if not found:raise ValueError('SADTALKER_PYTHON points to a missing file: '+explicit)
        return found,notes
    for variable in ('CONDA_PREFIX','VIRTUAL_ENV'):
        if os.environ.get(variable):environment(os.environ[variable])
    for base in (repo,repo.parent,root,root.parent,root.parent/'lineart_pipeline'):
        for name in ('.venv','venv','env','sadtalker_env','.venv-sadtalker'):environment(base/name)
    # Conda environments remain discoverable when conda is absent from PATH.
    homes=[Path.home()]
    if os.environ.get('LOCALAPPDATA'):homes.append(Path(os.environ['LOCALAPPDATA']))
    if os.environ.get('PROGRAMDATA'):homes.append(Path(os.environ['PROGRAMDATA']))
    installations=[]
    for home in homes:
        for name in ('miniconda3','anaconda3','miniforge3','mambaforge'):
            install=home/name
            if install.is_dir():installations.append(install);environment(install)
            if (install/'envs').is_dir():
                for env in sorted((install/'envs').iterdir()):
                    if env.is_dir():environment(env)
    registry=Path.home()/'.conda/environments.txt'
    if registry.is_file():
        for line in registry.read_text(encoding='utf-8',errors='replace').splitlines():
            if line.strip():environment(line.strip())
    commands=[]
    for command in (os.environ.get('CONDA_EXE'),shutil.which('conda')):
        if command and command not in commands:commands.append(command)
    for install in installations:
        for relative in ('Scripts/conda.exe','bin/conda'):
            if (install/relative).is_file() and str(install/relative) not in commands:commands.append(str(install/relative))
    for command in commands:
        try:
            result=subprocess.run([command,'env','list','--json'],capture_output=True,text=True,timeout=20)
            if result.returncode:notes.append('conda environment listing failed: '+result.stderr.strip()[-500:]);continue
            for env in json.loads(result.stdout).get('envs',[]):environment(env)
        except (OSError,ValueError,subprocess.TimeoutExpired) as e:notes.append('conda listing: '+str(e))
    add(sys.executable)
    if shutil.which('python'):add(shutil.which('python'))
    return found,notes

def check_python(python,repo):
    record={'python':str(python),'usable':False}
    try:
        result=subprocess.run([str(python),'-c',CUDA_PROBE],capture_output=True,text=True,timeout=45)
        lines=[line for line in result.stdout.splitlines() if line.startswith('SADTALKER_PROBE=')]
        if not lines:
            record['reason']='Python/PyTorch check failed';record['details']=(result.stderr or result.stdout).strip()[-2000:];return record
        details=json.loads(lines[-1].split('=',1)[1]);record.update(details)
        if details.get('torch_error'):
            record['reason']=details['torch_error'];return record
        if not details.get('cuda_available'):
            record['reason']='PyTorch is installed but CUDA is unavailable'
            if not details.get('torch_cuda_build'):record['reason']='PyTorch is a CPU build (no CUDA support)'
            return record
        help_result=subprocess.run([str(python),'inference.py','--help'],cwd=repo,capture_output=True,text=True,timeout=90)
        if help_result.returncode:
            record['reason']='CUDA works, but SadTalker failed to import/start';record['details']=(help_result.stderr or help_result.stdout).strip()[-4000:];return record
        if '--driven_audio' not in help_result.stdout:
            record['reason']='CUDA works, but this inference CLI has no --driven_audio option';return record
        record.update(usable=True,reason='CUDA and SadTalker CLI passed')
    except (OSError,ValueError,subprocess.TimeoutExpired) as e:record['reason']=str(e)
    return record

def inspect(root):
    root=Path(root).resolve();repo=locate_repo(root);pythons,notes=candidates(repo,root)
    records=[]
    for python in pythons:
        print('Checking:',python,flush=True);record=check_python(python,repo);records.append(record)
        print('  '+record['reason'],flush=True)
        if record.get('torch_version'):print('  Torch:',record['torch_version'],'CUDA build:',record.get('torch_cuda_build'),'Device:',record.get('device','unavailable'),flush=True)
        if record.get('details'):print(record['details'],flush=True)
    return {'repo':str(repo),'environments':records,'discovery_notes':notes}

def discover(root):
    root=Path(root).resolve();repo=locate_repo(root);pythons,notes=candidates(repo,root);records=[]
    for python in pythons:
        print('Checking SadTalker Python:',python,flush=True)
        record=check_python(python,repo);records.append(record);print('  '+record['reason'],flush=True)
        if record.get('torch_version'):print('  Torch:',record['torch_version'],'CUDA build:',record.get('torch_cuda_build'),'Device:',record.get('device','unavailable'),flush=True)
        if record['usable']:
            return {'sadtalker_repo':str(repo),'sadtalker_python':str(python),'enhancer':'none','expression_scale':1.0}
        if record.get('details'):print(record['details'],flush=True)
    report=Path(root)/'sadtalker_environment_report.json'
    report.write_text(json.dumps({'repo':str(repo),'environments':records,'discovery_notes':notes},indent=2)+'\n',encoding='utf-8')
    raise ValueError('No working SadTalker environment found. Actual failures are listed above and saved to '+str(report)+'. Run python diagnose_sadtalker.py --configure to inspect all candidates and save a working environment.')
