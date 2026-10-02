"""Optional output-only cleanup; timing and model input audio remain untouched."""
import json,subprocess,os,re
from pathlib import Path
FILTER='highpass=f=65,afftdn=nr=6:nf=-45:tn=0:gs=6,loudnorm=I=-16:TP=-1.5:LRA=11'
def enhance_video(path,mode='off'):
 if mode=='off':return
 path=Path(path);receipt=path.with_suffix('.audio.json')
 # The caller runs this only after creating a fresh presentation.
 probe=subprocess.run(['ffmpeg','-hide_banner','-i',str(path),'-vn','-af','volumedetect','-f','null','-'],capture_output=True,text=True,check=True);match=re.search(r'max_volume: ([^ ]+) dB',probe.stderr)
 if match and (match.group(1)=='-inf' or float(match.group(1))<-75):
  receipt.write_text(json.dumps({'mode':mode,'note':'Silent track retained without normalization'}));return
 temp=path.with_name(path.stem+'.audio.tmp.mp4')
 try:
  subprocess.run(['ffmpeg','-v','error','-y','-i',str(path),'-map','0:v:0','-map','0:a:0','-c:v','copy','-af',FILTER,'-ar','48000','-c:a','aac','-b:a','192k','-movflags','+faststart',str(temp)],check=True)
  os.replace(temp,path);receipt.write_text(json.dumps({'mode':mode,'filter':FILTER,'model_audio_unchanged':True},indent=2))
 finally:
  if temp.exists():temp.unlink()
