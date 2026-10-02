"""Hugging Face hosted ASR with real chunk timestamps and recoverable responses."""
import base64,json,os,re,subprocess,urllib.request,urllib.error
from pathlib import Path
from .core import digest,sig,save,read

def endpoint(cfg):
 model=cfg['hf_model']
 if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',model):raise ValueError('Hugging Face model must be owner/model')
 return 'https://router.huggingface.co/hf-inference/models/'+model

def timed_segments(data,offset,duration):
 chunks=data.get('chunks') or []
 if not chunks and isinstance(data.get('text'),str) and not data['text'].strip():return []
 if not chunks:raise ValueError('Hugging Face returned text without timestamps. Use a timestamp-capable ASR model, local Whisper, or import timed JSON/SRT. The provider response was retained.')
 result=[]
 for i,c in enumerate(chunks):
  stamp=c.get('timestamp')
  if not isinstance(stamp,(list,tuple)) or len(stamp)!=2 or any(v is None for v in stamp):raise ValueError('Hugging Face returned incomplete chunk timestamps; response retained for inspection. Use local Whisper or a model returning complete timestamps.')
  start,end=stamp
  if not isinstance(start,(int,float)) or not isinstance(end,(int,float)) or not 0<=start<end<=duration+.1:raise ValueError('Invalid Hugging Face chunk timestamps; response retained.')
  result.append({'start':offset+start,'end':offset+min(end,duration),'text':c.get('text','')})
 return result

def transcribe(root,audio,duration,cfg,log=print):
 token=os.environ.get(cfg['hf_key_env'])
 if not token:raise ValueError('Set a Hugging Face token in Advanced → Hugging Face credentials, or '+cfg['hf_key_env']+' before launch. Hosted ASR needs Inference Providers permission.')
 url=endpoint(cfg);signature=sig({'audio':digest(audio),'model':cfg['hf_model'],'adapter':1});folder=Path(root)/'work/hf_transcription'/signature;folder.mkdir(parents=True,exist_ok=True);segments=[]
 for n,start in enumerate(range(0,int(duration)+1,60)):
  length=min(60,duration-start)
  if length<=0:break
  raw=folder/f'chunk_{n:04}.json'
  if raw.is_file():data=read(raw);log(f'Reusing hosted transcript chunk at {start}s')
  else:
   chunk=folder/f'chunk_{n:04}.wav';subprocess.run(['ffmpeg','-v','error','-y','-ss',str(start),'-i',str(audio),'-t',str(length),'-ac','1','-ar','16000',str(chunk)],check=True)
   payload=json.dumps({'inputs':base64.b64encode(chunk.read_bytes()).decode(),'parameters':{'return_timestamps':True}}).encode()
   req=urllib.request.Request(url,data=payload,headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'})
   log(f'Sending audio {start:.0f}–{start+length:.0f}s to Hugging Face; charges may apply.')
   try:
    with urllib.request.urlopen(req,timeout=300) as response:data=json.load(response)
   except urllib.error.HTTPError as e:
    raise ValueError(f'Hugging Face ASR HTTP {e.code}. Check token permissions, model availability and account credits. Completed chunks retained.') from None
   if not isinstance(data,dict):raise ValueError('Unexpected Hugging Face ASR response')
   save(raw,data)
  segments+=timed_segments(data,start,length)
 return {'segments':segments,'provider':'huggingface','model':cfg['hf_model']}
