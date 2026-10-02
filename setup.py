"""Isolated Studio dependencies; existing CUDA environments are never modified."""
import argparse,os,subprocess,sys
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--transcription',action='store_true');p.add_argument('--anatomy',action='store_true');a=p.parse_args();root=Path(__file__).parent
if sys.version_info<(3,10):raise SystemExit('Studio needs Python 3.10 or newer. SadTalker can use a separate older Python.')
env=root/'.venv';python=env/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
if not python.exists():subprocess.run([sys.executable,'-m','venv',str(env)],check=True)
packages=['numpy>=1.26,<3','Pillow>=10,<13','opencv-python-headless>=4.8,<5']
if a.transcription:packages.extend(['faster-whisper>=1.1,<2','av>=11,<19'])
if a.anatomy:packages.append('mediapipe>=0.10,<0.11')
subprocess.run([str(python),'-m','pip','install',*packages],check=True)
print('Setup complete. Run launch.cmd, or .venv/bin/python studio.py on Linux/macOS.')
