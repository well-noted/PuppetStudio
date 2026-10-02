"""Sequential resumable face inference, short clips and joined productions."""
import copy,json,os,shutil,subprocess,sys,threading,time
from datetime import datetime
from pathlib import Path
from .core import ROOT,load,read,save,path,digest,sig,compile_scene,captions,probe,slug

def heartbeat(label,started,last_output,stage=None):
 now=time.monotonic()
 elapsed=int(now-started);minutes,seconds=divmod(elapsed,60)
 return f"[{datetime.now().astimezone().strftime('%H:%M:%S %Z')}] Process running: {label}"+(f" / {stage}" if stage else '')+f" | process started {minutes}m {seconds:02}s ago | last worker message {int(now-last_output)}s ago"

def command(args,logfile,log):
 logfile.parent.mkdir(parents=True,exist_ok=True)
 with logfile.open('a',encoding='utf-8') as f:
  proc=subprocess.Popen([str(x) for x in args],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8',errors='replace')
  started=time.monotonic();status={'last_output':started,'stage':None}
  def reader():
   for line in proc.stdout:
    status['last_output']=time.monotonic()
    if line.startswith('RUN:'):status['stage']=line[4:].strip()
    f.write(line);f.flush();log(line.rstrip())
  t=threading.Thread(target=reader,daemon=True);t.start()
  try:
   while True:
    try:code=proc.wait(timeout=15);break
    except subprocess.TimeoutExpired:log(heartbeat(Path(str(args[1] if len(args)>1 else args[0])).name,started,status['last_output'],status['stage']))
   t.join();proc.stdout.close()
  except BaseException:proc.terminate();proc.wait();t.join(timeout=2);raise
  if code:raise ValueError('Step failed; see '+str(logfile))
def reusable(p,key):
 done=p.with_suffix('.done.json');return p.is_file() and done.is_file() and read(done).get('signature')==key and read(done).get('sha256')==digest(p)
def finish(p,key):save(p.with_suffix('.done.json'),{'signature':key,'sha256':digest(p)})
def cuts(lo,hi,words,limit):
 result=[lo]
 while hi-result[-1]>limit:
  desired=result[-1]+limit;options=[w['end'] for w,n in zip(words,words[1:]) if n['start']-w['end']>.18 and desired-6<=w['end']<=desired+3];v=min(options,key=lambda x:abs(x-desired)) if options else desired;v=round(v*25)/25
  if v<=result[-1]:raise ValueError('Invalid chunk boundary')
  result.append(v)
 return result+[hi]
def profile_check(root,s):
 from PIL import Image
 import math
 if not s.get('profile') or not s.get('approved'):raise ValueError('Detect/import and approve anatomy for '+s['name'])
 p=read(path(root,s['profile']))
 with Image.open(path(root,s['asset'])) as image:w,h=image.size
 for key in ['bust','mouth_box_body']:
  x,y,bw,bh=p[key]
  if not all(math.isfinite(v) for v in [x,y,bw,bh]) or not 0<=x<x+bw<=w or not 0<=y<y+bh<=h:raise ValueError('Invalid '+key+' for '+s['name'])
 x,y,bw,bh=p['bust'];mx,my,mw,mh=p['mouth_box_body']
 if not x<=mx<mx+mw<=x+bw or not y<=my<my+mh<=y+bh or not y<p['nose_y_body']<my+mh<p['jaw_y_body']<y+bh:raise ValueError('Implausible mouth/nose/jaw coordinates')
 if p.get('source_sha256') and p['source_sha256']!=digest(path(root,s['asset'])):raise ValueError('Profile belongs to different artwork')
def preflight(root,p,productions):
 if not p['media'] or not p['transcript']:raise ValueError('Import recording and transcript first')
 roster={s['id']:s for s in p['speakers']};clips={c['id']:c for c in p['clips']}
 if p['settings']['backend']=='sadtalker':
  cfg=p['settings']
  if not cfg['sadtalker_repo'] or not (Path(cfg['sadtalker_repo']).expanduser()/'inference.py').is_file():raise ValueError('SadTalker checkout missing inference.py: '+repr(cfg['sadtalker_repo'])+'; check Advanced → Animation environment.')
  if not cfg['sadtalker_python'] or not Path(cfg['sadtalker_python']).expanduser().is_file():raise ValueError('CUDA Python executable does not exist: '+repr(cfg['sadtalker_python'])+'; check Advanced → Animation environment.')
 for prod in productions:
  if not prod['clips']:raise ValueError('Production '+prod['name']+' has no clips')
  compile_scene(root,p,prod)
  for key in prod['clips']:
   c=clips[key]
   if not c['reviewed']:raise ValueError('Review clip '+key+' first')
   if c['end']>p['media']['duration']+.05:raise ValueError('Clip goes past source recording')
   if not c['speaker']:raise ValueError('Assign speaker to '+key)
   if not any(a['id']==c['speaker'] and a['visible'] for a in prod['scene']['actors']):raise ValueError('Clip speaker is hidden in scene')
   if p['settings']['backend']=='sadtalker':profile_check(root,roster[c['speaker']])
 return roster,clips

def render_queue(root,selected=None,preview=False,log=print):
 from render_stage import render,actor_schedule
 from audio import enhance_video
 from .combine import combine
 from .gallery import record
 root=Path(root).resolve();p=load(root);productions=[x for x in p['productions'] if not selected or x['id'] in selected]
 if not productions:raise ValueError('Select a production')
 roster,clips=preflight(root,p,productions);cfg=p['settings'];media=path(root,p['media']['path']);mediahash=digest(media);transcript=read(path(root,p['transcript']));code=sig({str(f.relative_to(ROOT)):digest(f) for sub in ['renderer','engine','studio'] for f in (ROOT/sub).rglob('*.py')});out=root/'renders';out.mkdir(exist_ok=True);lock=root/'work/QUEUE_RUNNING.lock';lock.parent.mkdir(exist_ok=True)
 try:
  with lock.open('x') as f:f.write(str(os.getpid()))
 except FileExistsError:raise ValueError('Queue already running, or an interrupted lock remains: '+str(lock))
 report={'outputs':[],'failed':[],'preview':preview}
 try:
  for prod in productions:
   scene=compile_scene(root,p,prod);published=[];groups={}
   for key in prod['clips']:
    c=clips[key];lo=c['start'];hi=min(c['end'],lo+12) if preview else c['end'];s=roster[c['speaker']];card=c['intro'] if prod['intro_mode']=='clip' else (scene['intro']['text'] if prod['intro_mode']=='production' else '');keyhash=sig({'scene':scene,'clip':c,'hi':hi,'media':mediahash,'settings':{k:cfg[k] for k in ['backend','expression_scale','sadtalker_repo','sadtalker_python','chunk_seconds']},'code':code});folder=out/prod['id']/(key+'_'+keyhash);folder.mkdir(parents=True,exist_ok=True);target=folder/'clip.mp4'
    try:
     log('PRODUCTION '+prod['name']+' / CLIP '+c['title'])
     if not reusable(target,keyhash):
      whole=folder/'speech.wav';command(['ffmpeg','-v','error','-y','-ss',lo,'-i',media,'-t',hi-lo,'-vn','-ac','1','-ar','48000',whole],folder/'audio.log',log);boundaries=cuts(lo,hi,transcript['words'],cfg['chunk_seconds']);schedule=actor_schedule(next(a for a in scene['actors'] if a['id']==s['id']),captions(transcript,lo,hi),hi-lo,scene['motion']['gesture_interval']);parts=[]
      for n,(a,b) in enumerate(zip(boundaries,boundaries[1:])):
       log(f'PART {n+1}/{len(boundaries)-1} ({b-a:.1f}s)');audio=folder/f'part_{n:03}.wav';part=folder/f'part_{n:03}.mp4';command(['ffmpeg','-v','error','-y','-ss',a,'-i',media,'-t',b-a,'-vn','-ac','1','-ar','48000',audio],folder/'audio.log',log);cache=None
       if cfg['backend']=='sadtalker':
        if not cfg['sadtalker_repo'] or not cfg['sadtalker_python']:raise ValueError('Set existing SadTalker checkout and CUDA Python under Advanced')
        settings={k:cfg[k] for k in ['sadtalker_repo','sadtalker_python','expression_scale']};settings.update(enhancer='none',stabilize_face=True,stabilization_strength=.9,upper_face_smoothing=.3)
        if s.get('inference_bust'):settings.update(source_bust_reference=str(path(root,s['inference_bust'])),source_bust_reference_sha256=digest(path(root,s['inference_bust'])))
        facekey=sig({'art':digest(path(root,s['asset'])),'profile':digest(path(root,s['profile'])),'audio':digest(audio),'settings':settings,'engine':{str(f.relative_to(ROOT/'engine')):digest(f) for f in (ROOT/'engine').rglob('*.py')}});base=root/'work/face_cache'/s['id']/facekey;inputs=base/'input';inputs.mkdir(parents=True,exist_ok=True)
        for source,name in [(path(root,s['asset']),'character.png'),(path(root,s['profile']),'profile.json'),(audio,'speech.wav')]:
         dest=inputs/name
         if not dest.exists() or digest(source)!=digest(dest):shutil.copy2(source,dest)
        save(base/'tools.json',settings);cache=base/'engine';command([sys.executable,ROOT/'engine/animate.py','--assets',inputs,'--tools',base/'tools.json','--out',cache],base/'worker.log',log)
       elif cfg['backend']!='still':raise ValueError('Unknown animation backend')
       partkey=sig({'clip':keyhash,'a':a,'b':b,'cache':digest(cache/'result.json') if cache else None})
       if not reusable(part,partkey):
        offset=a-lo;gestures=[{**g,'start':g['start']-offset,'end':g['end']-offset} for g in schedule if g['end']>offset and g['start']<b-lo];render(part,scene,seconds=b-a,speaker=s['id'],cache=cache,cues=captions(transcript,a,b),intro=card if n==0 else None,gesture_schedule=gestures,offset=offset);finish(part,partkey)
       parts.append(part)
      listing=folder/'concat.txt';listing.write_text(''.join("file '"+part.name+"'\n" for part in parts));temp=folder/'joined.tmp.mp4';lead=scene['intro']['duration'] if card else 0
      command(['ffmpeg','-v','error','-y','-f','concat','-safe','1','-i',listing,'-i',whole,'-map','0:v:0','-map','1:a:0','-c:v','copy','-af',f'adelay={round(lead*1000)}:all=1,apad','-c:a','aac','-b:a','192k','-t',hi-lo+lead,'-movflags','+faststart',temp],folder/'join.log',log)
      if abs(float(probe(temp)['format']['duration'])-(hi-lo+lead))>.12:raise ValueError('Joined duration mismatch')
      temp.replace(target);enhance_video(target,scene['audio']['mode']);finish(target,keyhash)
     final=out/prod['id']/'clips'/(key+('_preview' if preview else '')+'.mp4');final.parent.mkdir(exist_ok=True);temp_publish=final.with_suffix('.publishing');shutil.copy2(target,temp_publish);temp_publish.replace(final);record(final,clip_id=key,title=c['title'],preview=preview,duration=hi-lo+(scene['intro']['duration'] if card else 0));record(target,clip_id=key,title=c['title'],preview=preview,duration=hi-lo+(scene['intro']['duration'] if card else 0));published.append(final);groups.setdefault(c['group'],[]).append(final);report['outputs'].append({'production':prod['id'],'clip':key,'path':str(final)});log('COMPLETE '+str(final))
    except Exception as e:report['failed'].append({'production':prod['id'],'clip':key,'error':str(e)});log('FAILED '+key+': '+str(e))
    save(out/'queue_report.json',report)
   if published and prod['output'] in ['together','both']:
    try:
     if len(published)!=len(prod['clips']):raise ValueError('Cannot combine incomplete production; completed clips retained')
     suffix='_preview' if preview else '';combined=out/prod['id']/('combined'+suffix+'.mp4');combine(published,combined);record(combined,preview=preview,duration=float(probe(combined)['format']['duration']))
     for group,files in groups.items():
      if group and len(files)>1:
       joined=out/prod['id']/('group_'+slug(group)+suffix+'.mp4');combine(files,joined);record(joined,preview=preview,duration=float(probe(joined)['format']['duration']))
    except Exception as e:report['failed'].append({'production':prod['id'],'error':str(e)});log('FAILED combined: '+str(e))
   save(out/'queue_report.json',report)
 finally:lock.unlink(missing_ok=True)
 if report['failed']:raise ValueError('Some jobs failed; see renders/queue_report.json. Completed outputs retained.')
 return report
