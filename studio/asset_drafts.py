"""Conservative local proposals and bounded image-edit drafts; always reviewed."""
import base64,io,uuid
import numpy as np
from PIL import Image
from .core import path,read,digest,multipart,provider

def breath_proposal(size,profile):
 w,h=size;mx,my,mw,mh=profile['mouth_box_body'];jaw=profile['jaw_y_body']
 # Narrow central chest only. This is a proposal, not chair/body segmentation.
 cx=mx+mw/2;top=jaw+mh*.65;bottom=min(h*.59,top+mw*3.0)
 if bottom<=top:raise ValueError('Anatomy leaves no safe chest proposal; supply a reviewed mask.')
 rx=min(w*.12,mw*1.15);ry=(bottom-top)/2;yy,xx=np.mgrid[:h,:w]
 r=((xx-cx)/max(rx,1))**2+((yy-(top+bottom)/2)/max(ry,1))**2
 return Image.fromarray(np.uint8(np.rint(np.clip(1-r,0,1)**2*180)))

def generate(root,s,cfg,a):
 kind=a['kind']
 if kind not in ['breath','closed','inference-bust','pose']:raise ValueError('Unknown draft kind')
 if not s.get('asset'):raise ValueError('Import a neutral figure first')
 master=path(root,s['asset']);source_hash=digest(master);image=Image.open(master).convert('RGB');profile=read(path(root,s['profile'])) if s.get('profile') else None
 if kind!='pose' and (not profile or not s.get('approved')):raise ValueError('Detect and approve anatomy before generating this draft')
 pose=a.get('pose','');description=a.get('description','').strip()
 if kind=='pose':
  import re
  if not re.fullmatch('[A-Za-z0-9_-]{1,60}',pose):raise ValueError('Enter a gesture ID first')
  if not description:raise ValueError('Describe the gesture to generate')
 dest=path(root,'assets/'+s['id']+'/draft_'+kind.replace('-','_')+'_'+uuid.uuid4().hex[:10]+'.png')
 input_image=image
 if kind=='inference-bust':
  x,y,w,h=map(round,profile['bust']);size=max(w,h);input_image=Image.new('RGB',(size,size),'white');input_image.paste(image.crop((x,y,x+w,y+h)),((size-w)//2,(size-h)//2))
 if kind=='breath':output=breath_proposal(image.size,profile)
 elif kind=='closed' and a.get('method','local')=='local':
  from motion import mouth_rest
  output=Image.fromarray(mouth_rest(np.asarray(image),np.asarray(image),profile,0))
 elif kind=='inference-bust' and a.get('method')=='local':output=input_image
 else:
  instructions={'pose':'Change ONLY arms and hands to this gesture: '+description+'. Preserve the entire head, chair, legs, feet, clothing colors, scale and placement exactly.', 'closed':'Change ONLY the lips to a relaxed closed-mouth rest. Preserve face shape, skin color, jaw, hair and every other pixel.', 'inference-bust':'Change ONLY lips to a gently parted neutral speaking mouth with a small visible opening. Preserve face geometry, colors, hair and all other details.'}
  prompt='Edit this exact puppet image in its existing flat illustrated style. '+instructions[kind]+' Use the same framing and canvas. White background. No text or extra figures.'
  # Store the exact request input for later review; never alter the master.
  request=dest.with_name(dest.stem+'_input.png');input_image.save(request)
  body,ctype=multipart([('model',cfg['image_model']),('prompt',prompt),('size','1024x1536' if kind=='pose' else '1024x1024')],request,'image')
  data=provider(cfg,'images/edits',body,ctype);raw=base64.b64decode(data['data'][0].get('b64_json',''),validate=True)
  if not raw or len(raw)>20*1024*1024:raise ValueError('Image provider must return a base64 image under 20 MiB')
  with Image.open(io.BytesIO(raw)) as edited:
   if edited.width*edited.height>16000000:raise ValueError('Draft exceeds 16 megapixels')
   edited=edited.convert('RGBA');background=Image.new('RGBA',edited.size,'white');background.alpha_composite(edited);output=background.convert('RGB').resize(input_image.size,Image.Resampling.LANCZOS)
  if kind in ['closed','inference-bust']:
   # Retain the master outside a compact lip rectangle. Review alignment inside it.
   mx,my,mw,mh=profile['mouth_box_body'];x0=max(0,round(mx-mw*.1));y0=max(0,round(my-mh*.1));x1=min(image.width,round(mx+mw*1.1));y1=min(image.height,round(my+mh*.65))
   if kind=='inference-bust':
    bx,by,bw,bh=map(round,profile['bust']);px=(input_image.width-bw)//2;py=(input_image.height-bh)//2;x0+=px-bx;x1+=px-bx;y0+=py-by;y1+=py-by
   bounded=input_image.copy();bounded.paste(output.crop((x0,y0,x1,y1)),(x0,y0));output=bounded
 output.save(dest)
 return {'kind':kind,'path':str(dest.relative_to(root)),'source_sha256':source_hash,'profile_sha256':digest(path(root,s['profile'])) if profile else None,'pose':pose,'description':description}
