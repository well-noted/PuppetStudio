"""Render the stage exported by studio.html; no neural inference is performed."""
import base64,io,json,math,subprocess,tempfile,time
from pathlib import Path
import cv2 as cv
import numpy as np
from PIL import Image,ImageDraw,ImageFont,ImageFilter,ImageOps
from studio_puppet import StudioPuppet
from cache import Actor
from text_layout import find_font,wrap_lines
from motion import SpeechGate,PauseMouthCorrection,breathe,gestures as schedule
from scene import validate
from lighting import shade,cast_shadow
ROOT=Path(__file__).resolve().parent

def rgba(image,p=None,box=None):
 from matte import cutout_rgba
 alpha=getattr(p,'current_alpha',None) if p else None
 if alpha is not None and box:alpha=alpha[box[1]:box[3],box[0]:box[2]]
 return Image.fromarray(cutout_rgba(image,alpha))
def background(scene):
 cfg=scene['background'];result=Image.new('RGBA',(1280,720),cfg['color'])
 if cfg.get('image_data'):
  im=Image.open(io.BytesIO(base64.b64decode(cfg['image_data'].split(',',1)[1]))).convert('RGBA');result.alpha_composite(ImageOps.fit(im,(1280,720),method=Image.Resampling.LANCZOS))
 return result


def compose(scene,puppets,bounds,t,face=None,speaker=None,cues=None,gesture_schedule=None,gate=None,offset=0):
 canvas=background(scene)
 sprites={}
 for a in scene['actors']:
  if not a['visible']:continue
  p=puppets[a['id']];base=p.closed.copy()
  if face and speaker==a['id']:
   base=face.frame(t)
   if gate:base=gate.rest.apply(base,gate.value(t),t)
  # Listener puppets breathe but never perform the active speaker's hand gesture.
  active=gesture_schedule if (speaker==a['id']) else ([] if speaker else actor_schedule(a,[],9,scene['motion']['gesture_interval'],demo=True))
  im=p.frame(t,active,base);im=breathe(im,p,t+offset,a['breathing'],a['height']);x0,y0,x1,y1=bounds[a['id']];im=im[y0:y1,x0:x1]
  height=round(a['height']);width=round(im.shape[1]*height/im.shape[0]);sprite=rgba(im,p,(x0,y0,x1,y1)).resize((width,height),Image.Resampling.LANCZOS)
  if a['mirror']:sprite=ImageOps.mirror(sprite)
  sprites[a['id']]=(sprite,width,height)
 for a in scene['actors']:
  if a['visible']:cast_shadow(canvas,a,sprites[a['id']][0],scene['lighting'])
 for a in scene['actors']:
  if a['visible']:
   sprite,width,height=sprites[a['id']];canvas.alpha_composite(shade(sprite,a,scene['lighting']),(round(a['x']-width/2),round(a['y']-height)))
 draw=ImageDraw.Draw(canvas);font=find_font()
 for a in scene['actors']:
  l=a['label']
  if not a['visible'] or not l['visible']:continue
  nf=ImageFont.truetype(font,round(l['name_size']));tf=ImageFont.truetype(font,round(l['title_size']));draw.text((l['x'],l['y']),a['name'],font=nf,fill=l['color'],anchor='lt');y=l['y']+l['name_size']*1.4
  for line in wrap_lines(a['title'],tf,l['width']):draw.text((l['x'],y),line,font=tf,fill=l['title_color'],anchor='lt');y+=l['title_size']*1.38
 text=next((c['text'] for c in cues or [] if c['start']<=t<c['end']),'') if speaker else 'Subtitle preview — text appears here during speech.'
 s=scene['subtitles'];sf=ImageFont.truetype(font,round(s['size']));lines=wrap_lines(text,sf,s['width'])
 if len(lines)>2:raise ValueError('Caption exceeds two lines in this scene: '+text)
 if text:
  if s['panel']:
   panel=Image.new('RGBA',(1280,720));ImageDraw.Draw(panel).rectangle((s['x']-s['width']/2-15,s['y']-10,s['x']+s['width']/2+15,s['y']+len(lines)*s['size']*1.3+10),fill=(255,255,255,240));canvas.alpha_composite(panel);draw=ImageDraw.Draw(canvas)
  for i,line in enumerate(lines):draw.text((s['x'],s['y']+i*s['size']*1.3),line,font=sf,fill=(next(a['label']['subtitle_color'] for a in scene['actors'] if a['id']==speaker) if s['speaker_colors'] and speaker else s['color']),anchor='mt')
 return canvas.convert('RGB')

def actor_schedule(actor,cues,duration,interval,demo=False):
 from gesture_planner import plan
 available=[p['id'] for p in actor.get('asset',{}).get('poses',[])]
 if demo and actor['gestures']['mode'] not in ['off','manual'] and available:return [{'start':1,'end':4,'pose':available[0],'strength':1}]
 return plan(actor,cues,duration,interval,available)

def render(output,scene,seconds=9,speaker=None,cache=None,cues=None,intro=None,gesture_schedule=None,offset=0):
 scene=validate(scene)
 if not math.isfinite(seconds) or seconds<=0:raise ValueError('Positive duration required')
 output=Path(output).resolve();output.parent.mkdir(parents=True,exist_ok=True);face=None;gate=None;puppets={a['id']:StudioPuppet(a) for a in scene['actors']};bounds={}
 for key,p in puppets.items():
  bounds[key]=p.content_bounds()
 try:
  if cache:
   if speaker not in puppets:raise ValueError('Select the cache speaker')
   face=Actor(cache);face.bind_master(puppets[speaker].neutral());seconds=min(seconds,face.duration)
   if scene['motion']['pause_rest']:
    gate=SpeechGate(face.audio,cues or None);gate.rest=PauseMouthCorrection(puppets[speaker].closed,face.profile)
  cues=cues or [];gesture_schedule=gesture_schedule if gesture_schedule is not None else (actor_schedule(next(a for a in scene['actors'] if a['id']==speaker),cues,seconds,scene['motion']['gesture_interval']) if speaker else [])
  # Preflight subtitles before encoding a potentially long part.
  sf=ImageFont.truetype(find_font(),round(scene['subtitles']['size']))
  if any(len(wrap_lines(c['text'],sf,scene['subtitles']['width']))>2 for c in cues):raise ValueError('Scene subtitle width is too small for supplied captions')
  fps=25;card=scene['intro'];lead=round(card['duration']*fps) if intro else 0;frames=round(seconds*fps)+lead;lock=output.with_suffix('.lock')
  try:lock.open('x').close()
  except FileExistsError:raise ValueError('Render output is already locked: '+str(lock))
  try:
   with tempfile.TemporaryDirectory(prefix='studio-',dir=output.parent) as temp:
    temp=Path(temp);target=temp/'render.mp4';command=['ffmpeg','-v','error','-y','-f','rawvideo','-pix_fmt','rgb24','-s','1280x720','-r',fps,'-i','pipe:0']
    if face:command+=['-i',face.audio,'-map','0:v','-map','1:a','-c:a','aac','-b:a','192k','-af',f'adelay={lead*1000//fps}:all=1,apad']
    else:command+=['-an']
    command+=['-t',frames/fps,'-c:v','libx264','-preset','medium','-crf',18,'-pix_fmt','yuv420p','-vf','scale=in_range=full:out_range=limited:out_color_matrix=bt709','-colorspace','bt709','-color_primaries','bt709','-color_trc','bt709','-movflags','+faststart',target]
    with (temp/'ffmpeg.log').open('w') as log:
     encoder=subprocess.Popen([str(x) for x in command],stdin=subprocess.PIPE,stderr=log)
     try:
      for i in range(frames):
       t=max(0,(i-lead)/fps)
       if i<lead:
        im=Image.new('RGB',(1280,720),card['background']);draw=ImageDraw.Draw(im);f=ImageFont.truetype(find_font(),round(card['size']));lines=[line for paragraph in intro.split('\n') for line in (wrap_lines(paragraph,f,card['width']) or [''])]
        if len(lines)>7 or card['y']-(len(lines)-1)/2*card['size']*1.35<0 or card['y']+(len(lines)-1)/2*card['size']*1.35+card['size']>720:raise ValueError('Context card is too long or extends outside the stage')
        for j,line in enumerate(lines):draw.text((card['x'],card['y']+(j-(len(lines)-1)/2)*card['size']*1.35),line,font=f,fill=card['color'],anchor='mt')
       else:
        # Global clock keeps breathing phase continuous across reassembled parts.
        im=compose(scene,puppets,bounds,t,face,speaker,cues,gesture_schedule,gate,offset)
       encoder.stdin.write(np.ascontiguousarray(im).tobytes())
       if i%125==0:print(f'Rendering {t:.0f}/{seconds:.0f}s',flush=True)
      encoder.stdin.close()
      if encoder.wait():raise RuntimeError((temp/'ffmpeg.log').read_text())
     finally:
      if encoder.poll() is None:encoder.terminate();encoder.wait()
    target.replace(output)
  finally:lock.unlink(missing_ok=True)
 finally:
  if face:face.close()
 print('COMPLETE:',output,flush=True)
