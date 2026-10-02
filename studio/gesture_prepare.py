"""Pixel-preserving gesture compositing. No resizing, warping or AI calls."""
import math,uuid
from pathlib import Path
import numpy as np
from PIL import Image
from .core import path,digest,read
DEFAULT_REGION=(.08,.25,.95,.66)

def region_mask(size,region=DEFAULT_REGION,feather=8):
 w,h=size
 if not isinstance(region,(list,tuple)) or len(region)!=4 or any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in region):raise ValueError('Gesture region needs four finite normalized coordinates')
 x0,y0,x1,y1=region
 if not DEFAULT_REGION[0]<=x0<x1<=DEFAULT_REGION[2] or not DEFAULT_REGION[1]<=y0<y1<=DEFAULT_REGION[3]:raise ValueError('Gesture region must stay inside X 0.08–0.95 and Y 0.25–0.66 to protect head and lower body')
 if isinstance(feather,bool) or not isinstance(feather,(int,float)) or not math.isfinite(feather) or not 0<=feather<=64:raise ValueError('Feather must be 0–64 pixels')
 left,top,right,bottom=round(x0*w),round(y0*h),round(x1*w),round(y1*h)
 yy,xx=np.mgrid[:h,:w];inside=(xx>=left)&(xx<right)&(yy>=top)&(yy<bottom)
 if not feather:return inside.astype(float)
 distance=np.minimum.reduce([xx-left+1,right-xx,yy-top+1,bottom-yy])
 return np.where(inside,np.clip(distance/feather,0,1),0.)

def composite(master,gesture,region=DEFAULT_REGION,feather=8,mask=None):
 if master.size!=gesture.size:raise ValueError(f'Gesture canvas {gesture.size[0]} × {gesture.size[1]} must match neutral {master.size[0]} × {master.size[1]}; no automatic resizing')
 gate=region_mask(master.size,region,feather)
 if mask is not None:
  if mask.size!=master.size:raise ValueError('Gesture mask must match the neutral canvas')
  gate*=np.asarray(mask.convert('L'),float)/255
 a=np.asarray(master.convert('RGBA'));b=np.asarray(gesture.convert('RGBA'));af=a.astype(float)/255;bf=b.astype(float)/255;v=gate[:,:,None]
 alpha=af[:,:,3:4]*(1-v)+bf[:,:,3:4]*v
 premul=af[:,:,:3]*af[:,:,3:4]*(1-v)+bf[:,:,:3]*bf[:,:,3:4]*v
 rgb=np.divide(premul,alpha,out=np.zeros_like(premul),where=alpha>0)
 out=np.uint8(np.rint(np.clip(np.concatenate([rgb,alpha],2),0,1)*255));protected=gate==0;out[protected]=a[protected]
 report={'canvas':list(master.size),'region':list(region),'feather_pixels':feather,'protected_pixels':int(protected.sum()),'protected_changed_pixels':int(np.any(out[protected]!=a[protected],axis=1).sum()),'edited_pixels':int(np.count_nonzero(gate)),'method':'premultiplied alpha blend; exact master copy wherever mask is zero'}
 return Image.fromarray(out),report

def prepare(root,s,a):
 if not s.get('asset'):raise ValueError('Import a neutral figure first')
 import re
 pose=a.get('pose','')
 if not re.fullmatch('[A-Za-z0-9_-]{1,60}',pose):raise ValueError('Enter a gesture ID first')
 source=path(root,s['asset']);src=Path(a['path']);src=src if src.is_absolute() else path(root,str(src))
 master=Image.open(source).convert('RGBA');gesture=Image.open(src).convert('RGBA');mask=None
 if a.get('mask'):
  masksrc=Path(a['mask']);masksrc=masksrc if masksrc.is_absolute() else path(root,str(masksrc));mask=Image.open(masksrc)
 output,report=composite(master,gesture,a.get('region',DEFAULT_REGION),a.get('feather',8),mask)
 # Canonical Studio art is RGB on white; use the exact master outside the gate.
 # PNG alpha is preserved by composite() for standalone RGBA workflows.
 out=Image.new('RGBA',output.size,'white');out.alpha_composite(output);dest=path(root,'assets/'+s['id']+'/draft_pose_'+uuid.uuid4().hex[:10]+'.png');out.convert('RGB').save(dest)
 return {'kind':'pose','path':str(dest.relative_to(root)),'source_sha256':digest(source),'profile_sha256':None,'pose':pose,'description':'Locally prepared gesture; inspect arm boundaries before import.','preparation':report}
