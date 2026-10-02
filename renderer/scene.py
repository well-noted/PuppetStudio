"""Scene schema 2: portable assets, independent colors, mirroring and gesture cues."""
import base64,io,json,math,re,copy
from pathlib import Path
from PIL import Image

def upgrade(s):
 s=copy.deepcopy(s);s.setdefault('audio',{'mode':'off'});s.setdefault('intro',{'enabled':False,'text':'','duration':4,'background':'#ffffff','color':'#222222','x':640,'y':280,'width':1100,'size':40});s['schema']=2;s['lighting']={'intensity':.25,'color':'#ffe7bf',**s['lighting']};s['subtitles']={'speaker_colors':False,**s['subtitles']}
 for a in s['actors']:
  a.setdefault('mirror',False);a['label'].setdefault('title_color','#64584d');a['label'].setdefault('subtitle_color',s['subtitles']['color']);a.setdefault('gestures',{'mode':'auto','cues':[]});a.setdefault('gesture_region',[.1,.27,.92,.66]);g=a['gestures'];g.setdefault('seed',42);g.setdefault('probability',.75);g.setdefault('duration_min',2);g.setdefault('duration_max',4);g.setdefault('phrases',['important','fundamental','principle','so i think','in other words','question','for example']);g.setdefault('interval_min',20);g.setdefault('interval_max',45)
  if g['mode']=='auto':g['mode']='hybrid'
 return s

def default_scene():
 old=json.loads((Path(__file__).resolve().parents[1]/'scene_default.json').read_text(encoding='utf-8'));return upgrade(old)

def image_bytes(value):
 if not isinstance(value,str) or len(value)>7100000 or not re.match(r'^data:image/(png|jpeg|webp);base64,',value):raise ValueError('Invalid embedded image')
 raw=base64.b64decode(value.split(',',1)[1],validate=True)
 with Image.open(io.BytesIO(raw)) as im:
  if im.width*im.height>16000000:raise ValueError('Image dimensions are too large')
  if im.format not in ['PNG','JPEG','WEBP']:raise ValueError('Unsupported image format')
  im.verify()
 return raw

def validate(s):
 if s.get('schema') not in [1,2] or s.get('canvas')!={'width':1280,'height':720}:raise ValueError('Expected a 1280 x 720 scene')
 s=upgrade(s);actors=s['actors']
 if s['audio']['mode'] not in ['off','cleanup']:raise ValueError('Unknown audio mode')
 if not 1<=len(actors)<=12 or len({a['id'] for a in actors})!=len(actors):raise ValueError('Use 1-12 speakers with unique IDs')
 def num(v,lo,hi,field="Setting"):
  if isinstance(v,bool) or not isinstance(v,(float,int)) or not math.isfinite(v) or not lo<=v<=hi:raise ValueError(f'{field}: entered {v!r}; allowed range {lo}–{hi}')
 def color(v):
  if not isinstance(v,str) or not re.fullmatch('#[0-9a-fA-F]{6}',v):raise ValueError('Invalid color')
 for a in actors:
  if not re.fullmatch('[a-zA-Z0-9_-]{1,60}',a['id']):raise ValueError('Invalid speaker ID')
  num(a['x'],0,1280,"Figure center X");num(a['y'],0,720,"Figure feet Y");num(a['height'],100,720,"Figure height");num(a['breathing'],0,5,"Breathing amplitude")
  if not isinstance(a['name'],str) or len(a['name'])>120 or not isinstance(a['title'],str) or len(a['title'])>240:raise ValueError('Invalid speaker label')
  l=a['label'];num(l['x'],0,1280,"Name/title X");num(l['y'],0,720,"Name/title Y");num(l['width'],100,1200,"Name/title width");num(l['name_size'],12,72,"Name font size");num(l['title_size'],10,48,"Title font size")
  for k in ['color','title_color','subtitle_color']:color(l[k])
  asset=a.get('asset')
  if asset:
   neutral=image_bytes(asset['neutral_data'])
   with Image.open(io.BytesIO(neutral)) as im:size=im.size
   if asset.get('closed_data'):
    with Image.open(io.BytesIO(image_bytes(asset['closed_data']))) as im:
     if im.size!=size:raise ValueError('Closed-mouth rest canvas must match neutral artwork')
   ids=[]
   for p in asset.get('poses',[]):
    if not re.fullmatch('[a-zA-Z0-9_-]{1,60}',p['id']) or p['id'] in ids:raise ValueError('Invalid or duplicate gesture pose ID')
    ids.append(p['id']);data=image_bytes(p['image_data'])
    with Image.open(io.BytesIO(data)) as im:
     if im.size!=size:raise ValueError('Gesture pose canvas must match the neutral image')
  else:raise ValueError('Speaker needs its own neutral asset')
  g=a['gestures']
  num(g['interval_min'],5,180,"g interval min");num(g['interval_max'],5,180,"g interval max")
  if g['interval_max']<g['interval_min'] or not isinstance(g['phrases'],list) or any(not isinstance(p,str) or len(p)>120 for p in g['phrases']) or len(g['phrases'])>80:raise ValueError('Invalid gesture phrases or interval range')
  num(g['seed'],0,2147483647,"g seed");num(g['probability'],0,1,"g probability");num(g['duration_min'],.8,8,"g duration min");num(g['duration_max'],.8,8,"g duration max")
  if int(g['seed'])!=g['seed'] or g['duration_max']<g['duration_min']:raise ValueError('Invalid gesture variation settings')
  if g['mode'] not in ['off','manual','auto','phrases','timed','hybrid']:raise ValueError('Unknown gesture mode')
  available=([p['id'] for p in asset.get('poses',[])] if asset else []);scopes={}
  for c in g['cues']:
   num(c['start'],0,86400,"c start");num(c['end'],0,86400,"c end")
   scope=c.get('clip')
   if scope is not None and (not isinstance(scope,str) or not re.fullmatch('[a-zA-Z0-9_-]{1,60}',scope)):raise ValueError('Invalid gesture cue clip ID')
   if c['end']<=c['start'] or c['pose'] not in available:raise ValueError('Gesture cues need Start < End and an available pose')
   scopes.setdefault(scope,[]).append(c)
  for scope in scopes:
   combined=scopes[scope]+(scopes.get(None,[]) if scope is not None else [])
   previous=-1
   for c in sorted(combined,key=lambda c:c['start']):
    if c['start']<previous:raise ValueError('Gesture cues must not overlap within a clip (including cues applied to every clip)')
    previous=c['end']
  gate=a['gesture_region']
  if len(gate)!=4:raise ValueError('Invalid gesture region')
  for value in gate:num(value,0,1,"value")
  if not gate[0]<gate[2] or not gate[1]<gate[3]:raise ValueError('Invalid gesture region')
 i=s['intro'];num(i['duration'],1,20,"i duration");num(i['x'],0,1280,"i x");num(i['y'],0,720,"i y");num(i['width'],200,1200,"i width");num(i['size'],16,72,"i size");color(i['background']);color(i['color'])
 if not isinstance(i['text'],str) or len(i['text'])>1600:raise ValueError('Intro text is too long')
 l=s['lighting'];num(l['x'],0,1280,"Name/title X");num(l['y'],0,720,"Name/title Y");num(l['shadow_opacity'],0,.6,"l shadow opacity");num(l['shadow_blur'],0,60,"l shadow blur");num(l['shadow_length'],0,240,"l shadow length");num(l['intensity'],0,1,"l intensity");color(l['color'])
 t=s['subtitles'];num(t['x'],0,1280,"Subtitle center X");num(t['y'],0,700,"Subtitle Y");num(t['width'],200,1200,"Subtitle width");num(t['size'],14,48,"Subtitle font size");num(s['motion']['gesture_interval'],15,120,"s motion gesture interval");color(t['color']);color(s['background']['color'])
 if s['background'].get('image_data'):image_bytes(s['background']['image_data'])
 return s

def load(path=None):return validate(json.loads(Path(path).read_text(encoding='utf-8-sig')) if path else default_scene())
