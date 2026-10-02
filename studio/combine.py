"""Join ordered presentations with compatible video/audio formats and safe quoting."""
import json,subprocess,tempfile,hashlib,os
from pathlib import Path

def combine(files,output):
 output=Path(output);signature=hashlib.sha256(json.dumps([(str(p.resolve()),p.stat().st_size,p.stat().st_mtime_ns) for p in files]).encode()).hexdigest();receipt=output.with_suffix('.combined.json')
 if output.exists() and receipt.exists() and json.loads(receipt.read_text()).get('signature')==signature:return
 if not files:raise ValueError('No clips to combine')
 with tempfile.TemporaryDirectory(prefix='combine-',dir=output.parent) as folder:
  folder=Path(folder);parts=[]
  for n,p in enumerate(files):
   probe=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(p)]));video=next(s for s in probe['streams'] if s['codec_type']=='video');duration=float(video.get('duration',probe['format']['duration']));audio=any(s['codec_type']=='audio' for s in probe['streams']);target=folder/f'{n:03}.mp4';cmd=['ffmpeg','-v','error','-y','-i',str(p)]
   if not audio:cmd+=['-f','lavfi','-i','anullsrc=r=48000:cl=stereo']
   cmd+=['-map','0:v:0','-map','0:a:0' if audio else '1:a:0','-vf','scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2,fps=25,setsar=1','-af','aresample=48000,apad','-ac','2','-t',str(duration),'-c:v','libx264','-preset','fast','-crf','18','-pix_fmt','yuv420p','-c:a','aac','-b:a','192k',str(target)]
   subprocess.run(cmd,check=True);parts.append(target)
  # Generated relative filenames contain no user-controlled paths or quotes.
  listing=folder/'list.txt';listing.write_text(''.join("file '"+p.name+"'\n" for p in parts));temp=folder/'combined.mp4';subprocess.run(['ffmpeg','-v','error','-y','-f','concat','-safe','1','-i',str(listing),'-c','copy','-movflags','+faststart',str(temp)],check=True);os.replace(temp,output)
 receipt.write_text(json.dumps({'signature':signature,'clips':[str(p) for p in files]},indent=2))
