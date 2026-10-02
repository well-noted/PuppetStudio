"""Portable project actions and optional providers; no names or conference content built in."""
import base64,copy,hashlib,importlib.util,io,json,math,os,re,shutil,subprocess,sys,urllib.request,urllib.error,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'renderer'))
def read(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def save(p,d):
 p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);t=p.with_suffix(p.suffix+'.tmp');t.write_text(json.dumps(d,indent=2,ensure_ascii=False)+'\n',encoding='utf-8');t.replace(p)
def digest(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
 return h.hexdigest()
def sig(d):return hashlib.sha256(json.dumps(d,sort_keys=True).encode()).hexdigest()[:20]
def path(root,value):
 p=Path(value)
 if p.is_absolute() or '..' in p.parts:raise ValueError('Use a project-relative file path')
 out=(Path(root)/p).resolve()
 if not out.is_relative_to(Path(root).resolve()):raise ValueError('Path escapes project')
 return out
def slug(s):return re.sub('[^a-z0-9]+','_',s.lower()).strip('_')[:50] or 'item'
def newid(items,name):
 key=slug(name);n=2
 while any(x['id']==key for x in items):key=slug(name)+'_'+str(n);n+=1
 return key
def uri(p):return 'data:image/png;base64,'+base64.b64encode(Path(p).read_bytes()).decode()
def new():return {'schema':'puppet-studio-1','name':'My project','media':None,'transcript':None,'speakers':[],'clips':[],'productions':[],'settings':{'transcription':'local','hf_model':'openai/whisper-large-v3','hf_key_env':'HF_TOKEN','whisper_model':'small','language':'','planning':'rules','target_seconds':60,'max_seconds':150,'backend':'sadtalker','sadtalker_repo':'','sadtalker_python':'','expression_scale':1.0,'chunk_seconds':75,'api_base':'https://api.openai.com/v1','key_env':'STUDIO_API_KEY','chat_model':'gpt-4.1-mini','image_model':'gpt-image-1','transcription_model':'whisper-1','style':'Editorial line art, flat muted colors, natural proportions, minimal shading.'}}
def actor(s,i=0):return {'id':s['id'],'name':s['name'],'title':s['title'],'visible':True,'mirror':False,'x':900 if i==0 else 340,'y':615,'height':535,'breathing':1.2,'gesture_region':[.08,.25,.95,.66],'label':{'visible':True,'x':55 if i==0 else 680,'y':60,'width':535,'name_size':36,'title_size':22,'color':'#233047','title_color':'#69758a','subtitle_color':'#222222'},'gestures':{'mode':'hybrid','cues':[],'seed':42,'probability':.75,'duration_min':2,'duration_max':4,'phrases':['important','for example','in other words'],'interval_min':25,'interval_max':50}}
def validate(p):
 if p.get('schema')!='puppet-studio-1':raise ValueError('Not a Puppet Studio project')
 def num(v,lo,hi,name):
  if isinstance(v,bool) or not isinstance(v,(float,int)) or not math.isfinite(v) or not lo<=v<=hi:raise ValueError(f'{name}: entered {v!r}; supported range {lo}–{hi}')
 for category,limit in [('speakers',12),('clips',1000),('productions',50)]:
  if not isinstance(p[category],list) or len(p[category])>limit:raise ValueError('Too many '+category)
  ids=[x['id'] for x in p[category]]
  if len(set(ids))!=len(ids) or any(not re.fullmatch('[a-zA-Z0-9_-]{1,60}',x) for x in ids):raise ValueError('Invalid/duplicate '+category+' IDs')
 roster={s['id']:s for s in p['speakers']};clips={c['id'] for c in p['clips']}
 for s in p['speakers']:
  if len(s['name'])>120 or len(s['title'])>240:raise ValueError('Speaker label too long')
  for k in ['asset','alpha','profile','reference','draft','breath','closed','inference_bust']:
   if s.get(k):path('/tmp/project',s[k])
  for d in s.get('asset_drafts',[]):path('/tmp/project',d['path'])
  for x in s['poses']:path('/tmp/project',x['path'])
 for c in p['clips']:
  num(c['start'],0,864000,'Clip start');num(c['end'],0,864000,'Clip end')
  if c['end']<=c['start'] or (c['speaker'] and c['speaker'] not in roster):raise ValueError('Invalid clip interval or speaker')
  if len(c['intro'])>1600:raise ValueError('Clip intro exceeds 1600 characters')
 for prod in p['productions']:
  if len(set(prod['clips']))!=len(prod['clips']) or any(x not in clips for x in prod['clips']):raise ValueError('Production contains duplicate/missing clips')
  if prod['output'] not in ['separate','together','both'] or prod['intro_mode'] not in ['clip','production','none']:raise ValueError('Invalid production output/intro mode')
  # Validate geometry on Save even while neutral artwork is pending.
  from PIL import Image
  from scene import validate as scene_validate
  b=io.BytesIO();Image.new('RGB',(2,2),'white').save(b,format='PNG');image='data:image/png;base64,'+base64.b64encode(b.getvalue()).decode();scene=copy.deepcopy(prod['scene'])
  for a in scene['actors']:
   if a['id'] not in roster:raise ValueError('Scene speaker is missing')
   a['asset']={'neutral_data':image,'poses':[{'id':x['id'],'image_data':image} for x in roster[a['id']]['poses']]}
  scene_validate(scene)
  # Keep validated defaults in project state, not only the renderer copy.
  from scene import upgrade as upgrade_scene
  prod['scene']=upgrade_scene(prod['scene'])
 cfg=p['settings']
 for key in ['sadtalker_repo','sadtalker_python']:
  value=cfg[key].strip()
  if len(value)>=2 and value[0]==value[-1] and value[0] in [chr(34),chr(39)]:value=value[1:-1].strip()
  cfg[key]=value
 cfg.setdefault('hf_model','openai/whisper-large-v3');cfg.setdefault('hf_key_env','HF_TOKEN')
 if not re.fullmatch('[A-Z_][A-Z0-9_]{0,79}',cfg['hf_key_env']):raise ValueError('Hugging Face key field must be an environment-variable NAME')
 if cfg['transcription'] not in ['local','api','huggingface']:raise ValueError('Unknown transcription provider')
 num(cfg['expression_scale'],.5,2,'Expression scale');num(cfg['chunk_seconds'],15,120,'Chunk seconds');num(cfg['target_seconds'],10,600,'Target clip seconds');num(cfg['max_seconds'],20,1800,'Maximum clip seconds')
 if cfg['max_seconds']<cfg['target_seconds']:raise ValueError('Maximum clip seconds must be at least target')
 if not re.fullmatch('[A-Z_][A-Z0-9_]{0,79}',cfg['key_env']):raise ValueError('API key field must be an environment-variable NAME')
 if not cfg['api_base'].startswith(('https://','http://localhost:','http://127.0.0.1:')):raise ValueError('API base must use HTTPS or local HTTP')
 def secrets(v):
  if isinstance(v,dict):
   for k,x in v.items():
    if k.lower() in ['api_key','apikey','password','authorization','token']:raise ValueError('Do not save credentials; use environment variables')
    secrets(x)
  elif isinstance(v,list):
   for x in v:secrets(x)
 secrets(p);return p
def load(root):return validate(read(Path(root)/'project.json'))
def store(root,p):save(Path(root)/'project.json',validate(p))
def probe(p):return json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(p)]))
from .timestamps import normalize
def captions(t,lo,hi):
 words=[{'start':max(lo,w['start'])-lo,'end':min(hi,w['end'])-lo,'text':w['word']} for w in t['words'] if w['end']>lo and w['start']<hi]
 result=[];buf=[]
 for w in words:
  if buf and (len(' '.join(x['text'] for x in buf))+len(w['text'])>68 or w['start']-buf[-1]['end']>.45 or w['end']-buf[0]['start']>4.5):result.append({'start':buf[0]['start'],'end':buf[-1]['end'],'text':' '.join(x['text'] for x in buf)});buf=[]
  buf.append(w)
 if buf:result.append({'start':buf[0]['start'],'end':buf[-1]['end'],'text':' '.join(x['text'] for x in buf)})
 if not words:
  for s in t['segments']:
   if s['end']<=lo or s['start']>=hi:continue
   chunks=[];text=''
   for w in s['text'].split():
    if len(text+' '+w)>68 and text:chunks.append(text);text=''
    text=(text+' '+w).strip()
   if text:chunks.append(text)
   a=max(lo,s['start'])-lo;b=min(hi,s['end'])-lo
   result.extend({'start':a+i*(b-a)/len(chunks),'end':a+(i+1)*(b-a)/len(chunks),'text':text} for i,text in enumerate(chunks))
 return result

def multipart(fields,file,field='file'):
 boundary='studio_'+uuid.uuid4().hex;parts=[]
 for k,v in fields:parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
 parts.extend([f'--{boundary}\r\nContent-Disposition: form-data; name="{field}"; filename="input{Path(file).suffix}"\r\nContent-Type: application/octet-stream\r\n\r\n'.encode(),Path(file).read_bytes(),f'\r\n--{boundary}--\r\n'.encode()]);return b''.join(parts),'multipart/form-data; boundary='+boundary
def provider(cfg,route,body,kind='application/json'):
 key=os.environ.get(cfg['key_env'])
 if not key:raise ValueError('Set '+cfg['key_env']+' in the launch terminal; never put the key in project JSON')
 req=urllib.request.Request(cfg['api_base'].rstrip('/')+'/'+route,data=body,headers={'Authorization':'Bearer '+key,'Content-Type':kind})
 try:
  with urllib.request.urlopen(req,timeout=600) as r:return json.loads(r.read())
 except urllib.error.HTTPError as e:raise ValueError('Provider HTTP '+str(e.code)+'; check compatible endpoint/model/permissions') from None
 except urllib.error.URLError:raise ValueError('Provider connection failed') from None

def compile_scene(root,p,prod):
 from scene import validate as scene_validate
 scene=copy.deepcopy(prod['scene']);roster={s['id']:s for s in p['speakers']}
 for a in scene['actors']:
  s=roster[a['id']]
  if not s['asset']:raise ValueError('Import artwork for '+s['name'])
  a['asset']={'neutral_data':uri(path(root,s['asset'])),'poses':[{'id':x['id'],'image_data':uri(path(root,x['path']))} for x in s['poses']]}
  if s.get('alpha'):a['asset']['alpha_data']=uri(path(root,s['alpha']))
  if s.get('breath'):a['asset']['breath_data']=uri(path(root,s['breath']))
  if s.get('closed'):a['asset']['closed_data']=uri(path(root,s['closed']))
 return scene_validate(scene)

def art_prompt(s,cfg):return f'One complete seated editorial illustration of {s["name"]}, recognizable from the reference. {cfg["style"]} Natural head/body proportions. Entire figure, chair and shoes in frame. No text, swatches, atlas or extra figures. White or transparent background. Neutral pose, hands resting naturally on thighs. Face clear, mouth gently parted, not a tight smile. Gesture variants must preserve exact head, chair, legs, scale and canvas; change only arms. This is a draft requiring review.'
def handoff(root,p):
 folder=Path(root)/'handoff';folder.mkdir(exist_ok=True)
 (folder/'ASSISTANT_PROMPT.md').write_text(f'''Help prepare a local Puppet Studio project. Prompt the user to provide the transcript located at {Path(root)/'transcript/transcript.json'}. You cannot read that path without local file access; ask them to attach it. Ask for the speaker roster and identities before assigning speakers. Suggest meaningful self-contained excerpts using only source text and actual segment timestamps. Do not invent quotes, speakers or context. Return JSON {{"clips":[{{"id":"clip_001","title":"...","start":0,"end":20,"speaker":null,"intro":"...","group":"...","reviewed":false}}]}}. Group related parts of one speech. The user must review cuts and assignments. Ask for photos/video frames and preferred art style. Generate one figure per PNG; additional gestures must match the neutral canvas and keep head, chair and legs fixed. Gently parted lips improve talking-face inference. Generated art needs anatomy calibration and a short speaking preview before overnight use. Never request API keys or include credentials in JSON.\n''',encoding='utf-8')
 if p['transcript']:shutil.copy2(path(root,p['transcript']),folder/'transcript.json')
 save(folder/'speaker_roster.json',[{'id':s['id'],'name':s['name'],'title':s['title']} for s in p['speakers']]);save(folder/'art_prompts.json',[{'speaker':s['id'],'prompt':art_prompt(s,p['settings'])} for s in p['speakers']]);return str(folder)

def action(root,name,a,log=print):
 if name in ['discover-tools','install-tools']:
  from .machine_setup import discover,install
  return discover(root,log) if name=='discover-tools' else install(root,a.get('animation',True),log)
 if name=='diagnose':
  from .diagnostics import check
  report=check(root,load(root),a.get('model',False),log=log)
  log('Setup report saved in work/setup_report.json')
  return report
 from PIL import Image,ImageOps
 import numpy as np
 from cache import clean_art
 from matte import cutout_rgba
 root=Path(root).resolve();p=load(root);cfg=p['settings'];get=lambda:next(s for s in p['speakers'] if s['id']==a['speaker'])
 if name=='import-media':
  source=Path(a['path'].strip().strip('"').strip("'")).expanduser().resolve();data=probe(source)
  if not any(s['codec_type']=='audio' for s in data['streams']):raise ValueError('Recording has no audio')
  dest=root/'media'/('source'+source.suffix.lower());dest.parent.mkdir(exist_ok=True)
  if source!=dest:shutil.copy2(source,dest)
  p['media']={'path':str(dest.relative_to(root)),'duration':float(data['format']['duration']),'video':any(s['codec_type']=='video' for s in data['streams'])};p['clips']=[];p['transcript']=None
  for prod in p['productions']:prod['clips']=[]
 elif name=='add-speaker':
  if not a['name'].strip():raise ValueError('Enter a speaker name')
  p['speakers'].append({'id':newid(p['speakers'],a['name']),'name':a['name'],'title':a.get('title',''),'asset':None,'profile':None,'approved':False,'poses':[],'reference':None})
 elif name=='import-asset':
  s=get();folder=root/'assets'/s['id'];folder.mkdir(parents=True,exist_ok=True);src=Path(a['path'].strip().strip('"'));src=src if src.is_absolute() else path(root,str(src));kind=a.get('kind','neutral')
  if kind=='profile':save(folder/'profile.json',read(src));s['profile']=str((folder/'profile.json').relative_to(root));s['approved']=False
  else:
   im=ImageOps.exif_transpose(Image.open(src)).convert('RGBA')
   if im.width*im.height>16000000:raise ValueError('Image limit is 16 megapixels')
   if kind=='reference':im.save(folder/'reference.png');s['reference']=str((folder/'reference.png').relative_to(root))
   elif kind=='inference-bust':
    if not s.get('profile'):raise ValueError('Detect/import anatomy first, so the exact bust canvas is known')
    profile=read(path(root,s['profile']));size=max(round(profile['bust'][2]),round(profile['bust'][3]))
    if im.size!=(size,size):raise ValueError(f'Inference bust must use the exact padded {size} x {size} canvas')
    im.convert('RGB').save(folder/'inference_bust.png');s['inference_bust']=str((folder/'inference_bust.png').relative_to(root))
   elif kind=='closed':
    if im.size!=Image.open(path(root,s['asset'])).size:raise ValueError('Closed rest must match neutral canvas')
    rgba=np.asarray(im,float)/255;Image.fromarray(np.uint8(np.rint((rgba[:,:,:3]*rgba[:,:,3:4]+1-rgba[:,:,3:4])*255))).save(folder/'closed.png');s['closed']=str((folder/'closed.png').relative_to(root))
   elif kind=='breath':
    if im.size!=Image.open(path(root,s['asset'])).size:raise ValueError('Breathing mask must match neutral canvas')
    im.convert('L').save(folder/'breath.png');s['breath']=str((folder/'breath.png').relative_to(root))
   else:
    rgba=np.asarray(im,float)/255;rgb=np.uint8(np.rint((rgba[:,:,:3]*rgba[:,:,3:4]+1-rgba[:,:,3:4])*255))
    if kind=='neutral':
     if not np.any(np.min(rgb,2)<245):raise ValueError('Neutral artwork is blank; import one visible figure.')
     rgb=clean_art(rgb)
     dest=folder/'character.png'
     # Retain source byte identity when the PNG already is the canonical RGB
     # image. Re-encoding unchanged pixels can vary across Pillow/zlib builds.
     with Image.open(src) as original:
      preserve=original.format=='PNG' and original.mode=='RGB' and original.size==(rgb.shape[1],rgb.shape[0]) and np.array_equal(np.asarray(original),rgb)
     if preserve:
      if src.resolve()!=dest.resolve():shutil.copy2(src,dest)
     else:Image.fromarray(rgb).save(dest)
     clean=cutout_rgba(rgb,rgba[:,:,3] if np.any(rgba[:,:,3]<.99) else None);Image.fromarray(clean).save(folder/'display.png');Image.fromarray(clean[:,:,3]).save(folder/'alpha.png');s.pop('closed',None);s.pop('inference_bust',None);s.pop('breath',None);s.pop('asset_drafts',None);s.update(asset=str((folder/'character.png').relative_to(root)),display=str((folder/'display.png').relative_to(root)),alpha=str((folder/'alpha.png').relative_to(root)),profile=None,approved=False,poses=[])
    elif kind=='pose':
     key=a['pose']
     if not re.fullmatch('[A-Za-z0-9_-]{1,60}',key):raise ValueError('Gesture ID must use letters/numbers/underscore/hyphen')
     neutral=np.asarray(Image.open(path(root,s['asset'])).convert('RGB'))
     if rgb.shape!=neutral.shape:raise ValueError('Gesture must use exact neutral canvas')
     h,w=rgb.shape[:2];outside=np.ones((h,w),bool);outside[round(h*.25):round(h*.66),round(w*.08):round(w*.95)]=False
     if np.mean(np.max(np.abs(rgb.astype(float)-neutral),2)[outside]>12)>.005:raise ValueError('Gesture changes head/chair/legs outside arm envelope; register or correct the art first')
     rgb[outside]=neutral[outside];dest=folder/(key+'.png');Image.fromarray(rgb).save(dest);s['poses']=[x for x in s['poses'] if x['id']!=key]+[{'id':key,'path':str(dest.relative_to(root))}]
    else:raise ValueError('Unknown asset kind')
 elif name=='reference-frame':
  if not p.get('media') or not p['media'].get('video'):raise ValueError('Import video before capturing a reference')
  seconds=a.get('seconds',0)
  if not isinstance(seconds,(int,float)) or not math.isfinite(seconds) or not 0<=seconds<p['media']['duration']:raise ValueError('Reference time must be inside the recording')
  if a.get('clip'):
   clip=next((c for c in p['clips'] if c['id']==a['clip'] and c['speaker']==a['speaker']),None)
   if not clip or not clip['start']<=seconds<=clip['end']:raise ValueError('Capture must be inside a clip assigned to this speaker')
  s=get();dest=root/'assets'/s['id']/'reference.png';dest.parent.mkdir(parents=True,exist_ok=True);subprocess.run(['ffmpeg','-v','error','-y','-ss',str(a.get('seconds',0)),'-i',str(path(root,p['media']['path'])),'-frames:v','1',str(dest)],check=True);s['reference']=str(dest.relative_to(root))
 elif name=='calibrate':
  s=get();spec=importlib.util.spec_from_file_location('anatomy',ROOT/'engine/animate.py');mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod);profile=mod.auto_profile(path(root,s['asset']),root/'models/anatomy');profile['source_sha256']=digest(path(root,s['asset']));dest=root/'assets'/s['id']/'profile.json';save(dest,profile);s['profile']=str(dest.relative_to(root));s['approved']=False
 elif name=='approve':
  s=get()
  if not s['profile']:raise ValueError('Detect or import anatomy first')
  s['approved']=True
  from .queue import profile_check
  profile_check(root,s)
 elif name in ['transcribe','import-transcript']:
  if not p['media']:raise ValueError('Import recording first')
  if name=='import-transcript':
   src=Path(a['path']);text=src.read_text(encoding='utf-8-sig')
   if src.suffix.lower()=='.srt':
    def stamp(x):
     h,m,s=x.replace(',','.').split(':');return int(h)*3600+int(m)*60+float(s)
    segments=[]
    for block in re.split(r'\n\s*\n',text.replace('\r','').strip()):
     lines=block.splitlines();i=next((i for i,x in enumerate(lines) if '-->' in x),None)
     if i is not None:lo,hi=lines[i].split('-->');segments.append({'start':stamp(lo.strip()),'end':stamp(hi.strip().split()[0]),'text':' '.join(lines[i+1:])})
    data={'segments':segments}
   else:data=json.loads(text)
  else:
   raw=root/'work/transcription_raw.json';receipt=root/'work/transcription_raw.done.json'
   recognition_key=sig({'media':digest(path(root,p['media']['path'])),'settings':{k:cfg[k] for k in ['transcription','whisper_model','language','api_base','transcription_model','hf_model']}})
   if raw.exists() and receipt.exists() and read(receipt).get('signature')==recognition_key and read(receipt).get('sha256')==digest(raw):
    log('Reusing complete raw transcript; recognition does not need to run again.');data=read(raw)
   else:
    audio=root/'work/transcription.wav';audio.parent.mkdir(exist_ok=True);subprocess.run(['ffmpeg','-v','error','-y','-i',str(path(root,p['media']['path'])),'-vn','-ac','1','-ar','16000',str(audio)],check=True)
    if cfg['transcription']=='huggingface':
     from .hf_transcription import transcribe
     data=transcribe(root,audio,p['media']['duration'],cfg,log)
    elif cfg['transcription']=='api':
     if audio.stat().st_size>24*1024*1024:raise ValueError('API audio adapter limit 24 MiB; use local transcription for conferences')
     body,kind=multipart([('model',cfg['transcription_model']),('response_format','verbose_json'),('timestamp_granularities[]','word'),('timestamp_granularities[]','segment')],audio);data=provider(cfg,'audio/transcriptions',body,kind)
    else:
     try:from faster_whisper import WhisperModel
     except ImportError:raise ValueError('Run setup.cmd --transcription or import JSON/SRT') from None
     log('Local Whisper on CPU. First use downloads model.');model=WhisperModel(cfg['whisper_model'],device='cpu',compute_type='int8',download_root=str(root/'models/whisper'));it,info=model.transcribe(str(audio),word_timestamps=True,vad_filter=True,language=cfg['language'] or None);segments=[]
     for x in it:segments.append({'start':x.start,'end':x.end,'text':x.text,'words':[{'start':w.start,'end':w.end,'word':w.word} for w in x.words or []]});log(f'Transcribed through {x.end:.0f}s')
     data={'segments':segments,'language':info.language}
    save(raw,data);save(receipt,{'signature':recognition_key,'sha256':digest(raw)})
  try:normalized=normalize(data,p['media']['duration'])
  except ValueError as e:
   save(root/'work/transcription_validation_error.json',{'error':str(e),'media_duration':p['media']['duration'],'raw_transcript':'work/transcription_raw.json' if name=='transcribe' else a['path']})
   raise
  save(root/'transcript/transcript.json',normalized);p['transcript']='transcript/transcript.json'
  for warning in normalized.get('warnings',[])[:10]:log('TIMING NOTE: '+warning)
  if len(normalized.get('warnings',[]))>10:log('Further timing notes are retained in transcript/transcript.json.')
 elif name in ['propose','import-clips']:
  if name=='import-clips':clips=read(a['path'])['clips']
  else:
   t=read(path(root,p['transcript']));clips=[]
   if cfg['planning']=='api':
    if len(json.dumps(t))>180000:raise ValueError('Transcript too large for this chat adapter; use local proposals or external assistant')
    prompt='Suggest self-contained topical clips using ONLY these transcript segments. Return JSON {"clips":[{"start":number,"end":number,"title":string,"intro":string}]}. Use actual segment start/end boundaries and maximum '+str(cfg['max_seconds'])+' seconds. Never infer speaker identity. Context must be supported; leave intro blank if unclear. '+json.dumps(t['segments']);data=provider(cfg,'chat/completions',json.dumps({'model':cfg['chat_model'],'messages':[{'role':'user','content':prompt}],'temperature':.2}).encode());text=data['choices'][0]['message']['content'].strip();text='\n'.join(text.splitlines()[1:-1]) if text.startswith('```') else text;draft=json.loads(text)['clips']
    for c in draft:
     if not any(abs(c['start']-s['start'])<.05 for s in t['segments']) or not any(abs(c['end']-s['end'])<.05 for s in t['segments']) or not 0<c['end']-c['start']<=cfg['max_seconds']:raise ValueError('Planner returned unsupported timestamp boundaries')
     clips.append(c)
   else:
    lo=None;parts=[]
    for i,s in enumerate(t['segments']):
     if lo is None:lo=s['start'];parts=[]
     parts.append(s['text']);end=s['end'];gap=t['segments'][i+1]['start']-end if i+1<len(t['segments']) else 0
     if (end-lo>=cfg['target_seconds'] and (re.search('[.!?]$',s['text']) or gap>.7)) or end-lo>=cfg['max_seconds'] or i==len(t['segments'])-1:
      cursor=lo
      while cursor<end:hi=min(end,cursor+cfg['max_seconds']);clips.append({'start':cursor,'end':hi,'title':' '.join(' '.join(parts).split()[:9]),'intro':''});cursor=hi
      lo=None
  p['clips']=[{'id':c.get('id',f'clip_{i+1:03}'),'start':c['start'],'end':c['end'],'title':c['title'],'speaker':c.get('speaker'),'intro':c.get('intro',''),'group':c.get('group',''),'reviewed':False} for i,c in enumerate(clips)]
  for prod in p['productions']:prod['clips']=[]
 elif name=='add-production':
  if not p['speakers']:raise ValueError('Add a speaker first')
  from scene import default_scene
  scene=default_scene();scene['actors']=[actor(s,i) for i,s in enumerate(p['speakers'])];p['productions'].append({'id':newid(p['productions'],a['name']),'name':a['name'],'clips':[],'output':'both','intro_mode':'clip','scene':scene})
 elif name=='prepare-gesture':
  from .gesture_prepare import prepare
  s=get();draft=prepare(root,s,a);s.setdefault('asset_drafts',[]).append(draft);log('Prepared gesture draft: '+draft['path']+'. Protected pixels changed: '+str(draft['preparation']['protected_changed_pixels'])+'. Review before importing.')
 elif name=='generate-asset':
  from .asset_drafts import generate
  s=get();draft=generate(root,s,cfg,a);s.setdefault('asset_drafts',[]).append(draft);log('Draft saved: '+draft['path']+'. Review before importing; the master figure was not changed.')
 elif name=='import-asset-draft':
  s=get();draft=next(d for d in s.get('asset_drafts',[]) if d['path']==a['path'])
  if digest(path(root,s['asset']))!=draft['source_sha256']:raise ValueError('Draft belongs to older artwork; generate it again')
  if draft.get('profile_sha256') and digest(path(root,s['profile']))!=draft['profile_sha256']:raise ValueError('Anatomy changed since draft generation; generate it again')
  return action(root,'import-asset',{'speaker':s['id'],'kind':draft['kind'],'path':draft['path'],'pose':draft.get('pose','')},log)
 elif name=='generate-art':
  s=get()
  if not s.get('reference'):raise ValueError('Import reference photo or extract a video frame first')
  body,kind=multipart([('model',cfg['image_model']),('prompt',art_prompt(s,cfg)),('size','1024x1536')],path(root,s['reference']),'image');data=provider(cfg,'images/edits',body,kind);item=data['data'][0]
  if not item.get('b64_json'):raise ValueError('Image adapter requires a base64 image response')
  raw=base64.b64decode(item['b64_json'],validate=True)
  if len(raw)>20*1024*1024:raise ValueError('Image response exceeds 20 MiB')
  dest=root/'assets'/s['id']/'draft.png';Image.open(io.BytesIO(raw)).convert('RGBA').save(dest);s['draft']=str(dest.relative_to(root));log('Draft ready for review. Import it as neutral art only after checking likeness/proportions.')
 elif name=='handoff':log(handoff(root,p))
 elif name=='export':
  save(root/'exports/project.json',p)
  for prod in p['productions']:save(root/'exports'/('scene_'+prod['id']+'.json'),prod)
 elif name=='snapshot':
  from render_stage import compose
  from studio_puppet import StudioPuppet
  prod=next(x for x in p['productions'] if x['id']==a['production']);scene=compile_scene(root,p,prod);puppets={a['id']:StudioPuppet(a) for a in scene['actors']};bounds={}
  for key,puppet in puppets.items():
   bounds[key]=puppet.content_bounds()
  dest=root/'work/snapshot.png';dest.parent.mkdir(exist_ok=True);compose(scene,puppets,bounds,0).save(dest)
 elif name=='render':
  from .queue import render_queue
  return render_queue(root,a.get('productions'),a.get('preview',False),log)
 else:raise ValueError('Unknown action '+name)
 store(root,p);return {'ok':True}
