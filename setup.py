"""Isolated Studio dependencies; existing CUDA environments are never modified."""
import argparse,os,subprocess,sys
from pathlib import Path
from setup_progress import SetupProgress

def main():
 p=argparse.ArgumentParser();p.add_argument('--transcription',action='store_true');p.add_argument('--anatomy',action='store_true');a=p.parse_args();root=Path(__file__).parent
 if sys.version_info<(3,10):raise SystemExit('Studio needs Python 3.10 or newer. SadTalker can use a separate older Python.')
 progress=SetupProgress();env=root/'.venv';python=env/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
 progress.stage(1,'Prepare isolated Python environment')
 if not python.exists():progress.run([sys.executable,'-m','venv',str(env)],'Creating Studio environment')
 else:progress.output('Using existing Studio environment.')
 packages=['numpy>=1.26,<3','Pillow>=10,<13','opencv-python-headless>=4.8,<5'];modules=['numpy','PIL','cv2']
 if a.transcription:packages.extend(['faster-whisper>=1.1,<2','av>=11,<19']);modules.extend(['faster_whisper','av'])
 if a.anatomy:packages.append('mediapipe>=0.10,<0.11');modules.append('mediapipe')
 progress.stage(2,'Resolve, download and install packages')
 pip_env={**os.environ,'PYTHONIOENCODING':'utf-8','PYTHONUTF8':'1','PYTHONUNBUFFERED':'1','PIP_PROGRESS_BAR':'on'}
 progress.run([str(python),'-u','-m','pip','install',*packages],'Installing Studio dependencies',pip_env)
 progress.stage(3,'Verify package imports')
 code='import importlib; '+ '; '.join("importlib.import_module("+repr(m)+"); print("+repr('OK: '+m)+",flush=True)" for m in modules)
 progress.run([str(python),'-u','-c',code],'Verifying installed packages',pip_env)
 progress.finish();print('Run launch.cmd, or .venv/bin/python studio.py on Linux/macOS.')
if __name__=='__main__':
 try:main()
 except KeyboardInterrupt:print('\nSetup interrupted. Retry setup.cmd when ready.');sys.exit(130)
 except subprocess.CalledProcessError as e:print('\nERROR: Setup step failed (exit '+str(e.returncode)+'). See the output above; retry setup.cmd after fixing it.');sys.exit(e.returncode if e.returncode>0 else 1)
