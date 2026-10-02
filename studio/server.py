"""Local Studio server with streamed imports, same-origin authentication and background jobs."""
import json,mimetypes,os,secrets,subprocess,sys,threading,time,urllib.parse,webbrowser
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from .core import ROOT,load,store,save,path,read,action

def serve(root,port=0,browser=True):
 from .machine_setup import activate
 activate()
 root=Path(root).resolve();token=secrets.token_urlsafe(32);state={'job':None,'process':None};guard=threading.Lock()
 def busy():return (state['process'] is not None and state['process'].poll() is None) or (state['job'] and state['job']['status']=='running')
 def start(name,args):
  with guard:
   if busy():raise ValueError('A job is already running')
   key=secrets.token_hex(8);job={'id':key,'action':name,'status':'running','started':time.time(),'lines':[]};state['job']=job;request=root/'work'/('request_'+key+'.json');save(request,{'action':name,'args':args})
  def worker():
   try:
    proc=subprocess.Popen([sys.executable,str(ROOT/'studio.py'),'--project',str(root),'task',str(request)],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8',errors='replace',env={**os.environ,'PYTHONIOENCODING':'utf-8','PYTHONUTF8':'1'},start_new_session=os.name!='nt',creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name=='nt' else 0);state['process']=proc
    with (root/'work'/('job_'+key+'.log')).open('w',encoding='utf-8') as f:
     for line in proc.stdout:f.write(line);f.flush();job['lines']=(job['lines']+[line.rstrip()])[-150:]
    code=proc.wait();proc.stdout.close()
    if job['status']!='cancelled':job['status']='completed' if code==0 else 'failed'
   except Exception as e:job['status']='failed';job['lines'].append(str(e))
   finally:state['process']=None;job['finished']=time.time();save(root/'work'/('job_'+key+'.json'),job)
  threading.Thread(target=worker,daemon=True).start();return job
 class Handler(BaseHTTPRequestHandler):
  def log_message(self,*a):pass
  def authorized(self):
   host=f'127.0.0.1:{self.server.server_port}';q=urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
   return self.headers.get('Host')==host and self.headers.get('Origin','http://'+host)=='http://'+host and (self.headers.get('X-Studio-Token')==token or q.get('token',[None])[0]==token)
  def reply(self,data,status=200):
   body=json.dumps(data).encode();self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
  def do_GET(self):
   if not self.authorized():self.reply({'error':'Authorization failed'},403);return
   route=urllib.parse.urlsplit(self.path).path
   try:
    if route=='/':
     body=(ROOT/'web/index.html').read_text(encoding='utf-8').replace('__TOKEN__',token).encode();self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8');self.send_header('Content-Length',str(len(body)));self.send_header('Referrer-Policy','no-referrer');self.end_headers();self.wfile.write(body);return
    if route=='/api/machine':
     from .machine_setup import inventory
     self.reply(inventory());return
    if route=='/api/renders':
     from .gallery import catalog
     q=urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
     self.reply({'renders':catalog(root,q.get('history',['0'])[0]=='1')});return
    if route=='/api/job':
     self.reply({'job':state['job']});return
    if route=='/api/state':
     p=load(root);meta={}
     from PIL import Image
     import numpy as np
     for s in p['speakers']:
      if s['asset']:
       rgb=np.asarray(Image.open(path(root,s['asset'])).convert('RGB'));yy,xx=np.nonzero(np.min(rgb,2)<245)
       if not len(xx):raise ValueError('Artwork for '+s['name']+' is blank; import a visible figure.')
       from studio_puppet import StudioPuppet
      from .core import actor,uri
      staged=actor(s);staged['asset']={'neutral_data':uri(path(root,s['asset'])),'poses':[{'id':pose['id'],'image_data':uri(path(root,pose['path']))} for pose in s['poses']]}
      meta[s['id']]={'bounds':list(StudioPuppet(staged).content_bounds()),'profile':read(path(root,s['profile'])) if s['profile'] else None}
     self.reply({'project':p,'meta':meta,'job':state['job']});return
    if route.startswith('/files/'):
     target=path(root,urllib.parse.unquote(route[7:]));parts=target.relative_to(root).parts
     if parts[0] not in ['assets','media','transcript','exports','handoff','renders'] and parts!=('work','snapshot.png'):raise ValueError('File unavailable')
     size=target.stat().st_size;lo=0;hi=size-1;status=200
     if self.headers.get('Range'):
      import re
      match=re.fullmatch(r'bytes=(\d+)-(\d*)',self.headers['Range'])
      if not match:raise ValueError('Unsupported range')
      lo=int(match[1]);hi=min(hi,int(match[2]) if match[2] else hi);status=206
      if lo>hi:raise ValueError('Invalid range')
     self.send_response(status);self.send_header('Content-Type',mimetypes.guess_type(target)[0] or 'application/octet-stream');self.send_header('Content-Length',str(hi-lo+1));self.send_header('Accept-Ranges','bytes');self.send_header('Cache-Control','no-store')
     q=urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
     if q.get('download')==['1']:self.send_header('Content-Disposition',"attachment; filename*=UTF-8''"+urllib.parse.quote(target.name,safe=''))
     if status==206:self.send_header('Content-Range',f'bytes {lo}-{hi}/{size}')
     self.end_headers()
     with target.open('rb') as f:
      f.seek(lo);remaining=hi-lo+1
      while remaining:
       block=f.read(min(1024*1024,remaining))
       if not block:break
       self.wfile.write(block);remaining-=len(block)
     return
    self.reply({'error':'Not found'},404)
   except (BrokenPipeError,ConnectionResetError):pass
   except Exception as e:self.reply({'error':str(e)},400)
  def do_POST(self):
   if not self.authorized():self.reply({'error':'Authorization failed'},403);return
   try:
    route=urllib.parse.urlsplit(self.path).path;length=int(self.headers.get('Content-Length','0'))
    if route=='/api/upload':
     if busy():raise ValueError('Wait for current job before uploading')
     if not 0<length<=5*1024**3:raise ValueError('Upload supported range: 1 byte–5 GiB; use local paths for larger media')
     name=Path(urllib.parse.unquote(self.headers.get('X-Filename','upload'))).name;suffix=Path(name).suffix.lower()
     if suffix not in ['.png','.jpg','.jpeg','.webp','.mp4','.mkv','.mov','.webm','.wav','.mp3','.m4a','.flac','.ogg','.json','.srt']:raise ValueError('Unsupported file type')
     target=root/'imports'/(secrets.token_hex(8)+suffix);target.parent.mkdir(exist_ok=True)
     with target.open('xb') as f:
      while length:
       block=self.rfile.read(min(1024*1024,length))
       if not block:raise ValueError('Upload interrupted')
       f.write(block);length-=len(block)
     self.reply({'path':str(target)});return
    if length>30*1024*1024:raise ValueError('Request exceeds 30 MiB')
    data=json.loads(self.rfile.read(length) or '{}')
    if route=='/api/cancel':
     if not busy() or state['process'] is None:raise ValueError('No running job')
     state['job']['status']='cancelled';proc=state['process']
     if os.name=='nt':subprocess.run(['taskkill','/PID',str(proc.pid),'/T','/F'],capture_output=True)
     else:
      import signal;os.killpg(proc.pid,signal.SIGTERM)
     self.reply({'ok':True});return
    if busy():raise ValueError('Wait for current job before saving or starting another')
    if route=='/api/credential':
     p=load(root);allowed={'HF_TOKEN',p['settings']['hf_key_env'],p['settings']['key_env']};name=data.get('name');value=data.get('value','')
     if name not in allowed or not isinstance(value,str) or len(value)>4096 or any(c in value for c in ['\n','\r','\0']):raise ValueError('Invalid credential input')
     if value:os.environ[name]=value
     else:os.environ.pop(name,None)
     self.reply({'ok':True,'configured':bool(value)});return
    if route=='/api/save':store(root,data['project']);self.reply({'saved':time.time()});return
    if route=='/api/action':
     name=data['action'];args=data.get('args',{})
     if name in ['transcribe','propose','calibrate','generate-art','generate-asset','snapshot','render','diagnose','discover-tools','install-tools']:self.reply({'job':start(name,args)});return
     action(root,name,args);self.reply({'ok':True});return
    self.reply({'error':'Unknown endpoint'},404)
   except Exception as e:self.reply({'error':str(e)},400)
 server=ThreadingHTTPServer(('127.0.0.1',port),Handler);url=f'http://127.0.0.1:{server.server_port}/?token={token}';print('Studio:',url,flush=True)
 if browser:webbrowser.open(url)
 try:server.serve_forever()
 except KeyboardInterrupt:print('Studio closed. Use the queue log before restarting an interrupted render.')
 finally:server.server_close()
