"""Read-only setup checks. Never install packages or alter model environments."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

def check(root, project, model=False, log=None):
    results=[]
    def add(name,status,message):
        results.append({'name':name,'status':status,'message':message})
        if log:log(status.upper()+': '+name+' - '+message)
    add('Studio Python','ok',sys.version.split()[0]+' — '+sys.executable)
    for tool in ('ffmpeg','ffprobe'):
        found=shutil.which(tool)
        add(tool,'ok' if found else 'error',found or 'Install FFmpeg and add its bin folder to PATH, then reopen the terminal.')
    for module,label in [('numpy','NumPy'),('PIL','Pillow'),('cv2','OpenCV')]:
        found=importlib.util.find_spec(module)
        add(label,'ok' if found else 'error','Available in Studio environment.' if found else 'Run python setup.py in the package folder.')
    for module,label,flag in [('faster_whisper','Local transcription','--transcription'),('mediapipe','Anatomy detection','--anatomy')]:
        found=importlib.util.find_spec(module)
        add(label,'ok' if found else 'optional','Available.' if found else 'Optional: run python setup.py '+flag+' or import reviewed files.')
    cfg=project['settings']
    add('API credentials','ok' if os.environ.get(cfg['key_env']) else 'optional',
        cfg['key_env']+' is set (value hidden).' if os.environ.get(cfg['key_env']) else cfg['key_env']+' is not set; local workflows do not need it.')
    if cfg['backend']=='still':
        add('Face backend','optional','Still-face mode checks composition and gestures, without lip sync.')
    else:
        repo=Path(cfg['sadtalker_repo'].strip().strip('"')).expanduser() if cfg['sadtalker_repo'] else None
        python=Path(cfg['sadtalker_python'].strip().strip('"')).expanduser() if cfg['sadtalker_python'] else None
        good_repo=bool(repo and (repo/'inference.py').is_file())
        good_python=bool(python and python.is_file())
        add('SadTalker checkout','ok' if good_repo else 'error',str(repo) if good_repo else 'Set a checkout containing inference.py under Advanced → Animation environment.')
        add('CUDA Python','ok' if good_python else 'error',str(python) if good_python else 'Set the existing SadTalker environment python.exe under Advanced → Animation environment.')
        if model and good_repo and good_python:
            # Use the exact chosen environment, preserving the same import paths.
            env={**os.environ,'PYTHONIOENCODING':'utf-8','PYTHONUTF8':'1'}
            def probe(args,seconds,label):
                if log:log('Checking '+label+' (limit '+str(seconds)+' seconds)...')
                try:
                    result=subprocess.run(args,cwd=repo,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=seconds,env=env)
                    output=(result.stdout or '')+'\n'+(result.stderr or '')
                except subprocess.TimeoutExpired as e:
                    def decode(v):return v.decode('utf-8','replace') if isinstance(v,bytes) else (v or '')
                    output=decode(e.stdout)+'\n'+decode(e.stderr)
                    result=None
                except OSError as e:
                    add(label,'error',str(e));return None
                folder=Path(root)/'work';folder.mkdir(parents=True,exist_ok=True)
                filename='startup_probe.log' if label=='SadTalker startup' else 'cuda_probe.log'
                (folder/filename).write_text(output,encoding='utf-8')
                if result is None:
                    add(label,'error','Timed out after '+str(seconds)+' seconds. Last output / stack trace:\n'+(output.strip()[-6000:] or '(No output captured.)')+'\nFull log: work/'+filename+'. No packages were changed.')
                return result
            code="import json,torch,numpy;print('STUDIO_PROBE='+json.dumps({'torch':torch.__version__,'cuda':torch.cuda.is_available(),'device':torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,'numpy':numpy.__version__,'numpy_path':numpy.__file__}),flush=True)"
            proc=probe([str(python),'-u','-c',code],60,'CUDA import test')
            if proc is not None:
                marker=next((line[13:] for line in proc.stdout.splitlines() if line.startswith('STUDIO_PROBE=')),None)
                try:data=json.loads(marker) if marker else None
                except ValueError:data=None
                if proc.returncode or not data:
                    add('CUDA import test','error',((proc.stderr or '')+'\n'+(proc.stdout or '')).strip()[-3500:] or 'Environment probe failed.')
                else:
                    add('CUDA import test','ok' if data['cuda'] else 'error',json.dumps(data,ensure_ascii=False))
                    if data['cuda']:
                        startup_code="import faulthandler,runpy,sys;faulthandler.enable();faulthandler.dump_traceback_later(60,repeat=True);print('Starting SadTalker imports...',flush=True);sys.argv=['inference.py','--help'];runpy.run_path('inference.py',run_name='__main__')"
                        startup=probe([str(python),'-u','-c',startup_code],180,'SadTalker startup')
                        if startup is not None:
                            add('SadTalker startup','ok' if startup.returncode==0 else 'error','Imports and CLI startup passed. Weights and rendering still require a speaking preview.' if startup.returncode==0 else ((startup.stderr or '')+'\n'+(startup.stdout or '')).strip()[-6000:])
        elif not model:
            add('Model startup test','optional','Use Check model environment to test CUDA and SadTalker imports without rendering.')
    report={'checks':results,'errors':sum(x['status']=='error' for x in results),'model_test_requested':model}
    from .core import save
    save(Path(root)/'work/setup_report.json',report)
    return report
