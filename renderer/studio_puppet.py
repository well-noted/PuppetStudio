import io
import numpy as np
from PIL import Image
from scene import image_bytes
from matte import cutout_rgba

def rgb(data):
 a=np.asarray(Image.open(io.BytesIO(image_bytes(data))).convert('RGBA'),float)/255
 return np.uint8(np.rint((a[:,:,:3]*a[:,:,3:4]+1-a[:,:,3:4])*255))
def smooth(t):
 t=np.clip(t,0,1);return t*t*t*(t*(t*6-15)+10)
class StudioPuppet:
 def __init__(self,actor):
  self.actor=actor;a=actor['asset'];self.rest=rgb(a['neutral_data']);self.closed=self.rest.copy();h,w=self.rest.shape[:2];self.size=(w,h);self.alpha=cutout_rgba(self.rest)[:,:,3]/255.;self.current_alpha=self.alpha.copy();self.poses={};self.masks={};self.pose_alpha={};self.breath_mask=None
  if a.get('alpha_data'):self.alpha=np.asarray(Image.open(io.BytesIO(image_bytes(a['alpha_data']))).convert('L'),float)/255
  if a.get('closed_data'):self.closed=rgb(a['closed_data'])
  self.current_alpha=self.alpha.copy();gate=np.zeros((h,w),float);x0,y0,x1,y1=[round(v*n) for v,n in zip(actor['gesture_region'],[w,h,w,h])];gate[y0:y1,x0:x1]=1
  for p in a['poses']:
   image=rgb(p['image_data'])
   if image.shape!=self.rest.shape:raise ValueError('Gesture canvas differs from neutral')
   self.poses[p['id']]=image;self.masks[p['id']]=gate;self.pose_alpha[p['id']]=cutout_rgba(image)[:,:,3]/255.
  if a.get('breath_data'):self.breath_mask=np.asarray(Image.open(io.BytesIO(image_bytes(a['breath_data']))).convert('L'),float)/255
 def neutral(self):return self.rest.copy()
 def frame(self,t=0,gestures=None,animated_body=None):
  base=self.rest if animated_body is None else animated_body;self.current_alpha=self.alpha.copy();chosen=None;strength=0
  for c in gestures or []:
   speed=min(.35,(c['end']-c['start'])/2);value=smooth((t-c['start'])/speed)*smooth((c['end']-t)/speed)
   if value>strength:strength=value;chosen=c['pose']
  if chosen is None:return base.copy()
  a=self.masks[chosen]*strength;self.current_alpha=self.alpha*(1-a)+self.pose_alpha[chosen]*a;return np.uint8(np.rint(base*(1-a[:,:,None])+self.poses[chosen]*a[:,:,None]))
 def content_bounds(self):
  """Fixed bounds across every pose, so extended hands remain in frame."""
  mask=np.min(self.rest,2)<245
  for key,image in self.poses.items():mask|=(np.min(image,2)<245)&(self.masks[key]>0)
  yy,xx=np.nonzero(mask)
  if not len(xx):raise ValueError('Figure is blank')
  return (max(0,int(xx.min())-8),max(0,int(yy.min())-8),min(self.size[0],int(xx.max())+9),min(self.size[1],int(yy.max())+9))
