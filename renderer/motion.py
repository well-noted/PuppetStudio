"""Sparse emphasis gestures, bounded breathing and conservative pause correction."""
import math,subprocess
import numpy as np
import cv2 as cv

def gestures(cues,duration,interval=40):
 result=[];last=-interval
 for c in cues:
  a,b=c['start'],c['end'];text=c['text'].lower()
  if a<3 or a>=duration or a-last<interval or b-a<1:continue
  if not any(w in text for w in ['important','fundamental','principle','so i think','in other words','question','for example']):continue
  result.append({'start':a,'end':min(duration,a+3),'strength':1});last=a
 return result

class SpeechGate:
 def __init__(self,audio,cues=None):
  raw=subprocess.check_output(['ffmpeg','-v','error','-i',str(audio),'-vn','-ac','1','-ar','8000','-f','f32le','pipe:1']);signal=np.frombuffer(raw,np.float32)
  hop=160;n=len(signal)//hop
  if n==0:raise ValueError('Speech track is empty')
  rms=np.sqrt(np.mean(signal[:n*hop].reshape(n,hop)**2,axis=1));noise=float(np.percentile(rms,10));voice=float(np.percentile(rms,85));self.threshold=max(.0015,min(voice*.5,max(noise*1.7,voice*.12)))
  active=(rms>self.threshold).astype(np.float32)
  # Preserve consonant onset/offset by expanding activity 80 ms either way.
  active=np.maximum.reduce([np.pad(active,(i,8-i),mode='edge')[4:4+n] for i in range(9)])
  self.values=np.convolve(np.pad(active,(2,2),mode='edge'),np.ones(5)/5,mode='valid');self.hop_seconds=.02;self.cues=cues
 def value(self,t):
  energy=float(np.interp(t/self.hop_seconds,np.arange(len(self.values)),self.values))
  if self.cues is None:return energy
  caption=max((min(1,max(0,(t-c['start']+.12)/.12))*min(1,max(0,(c['end']+.12-t)/.12)) for c in self.cues),default=0)
  return min(energy,caption)

def mouth_rest(animated,neutral,profile,voice,shift=(0.,0.)):
 """Close the current mouth geometrically; never insert different artwork.

 `neutral` remains an API argument for compatibility but is not sampled.
 The compact inverse warp squeezes the lip opening vertically and eases back
 to the original frame at its boundary. No horizontal motion is introduced.
 """
 voice=float(np.clip(voice,0,1))
 if voice>=.999:return animated
 h,w=animated.shape[:2];mx,my,mw,mh=profile['mouth_box_body']
 dx,dy=shift;cx=mx+mw/2+dx;cy=my+mh*.23+dy
 rx=max(2.,mw*.55);ry=max(2.,mh*.40)
 x0=max(0,int(math.floor(cx-rx-1)));x1=min(w,int(math.ceil(cx+rx+2)))
 y0=max(0,int(math.floor(cy-ry-1)));y1=min(h,int(math.ceil(cy+ry+2)))
 if x0>=x1 or y0>=y1:return animated
 yy,xx=np.mgrid[y0:y1,x0:x1].astype(np.float32)
 # Elliptical support is bounded: the beard outline is never touched.
 nx=np.abs((xx-cx)/rx);half=ry*np.sqrt(np.clip(1-nx*nx,0,1))
 band=half*.48;scale=.18+.82*voice;target=band*scale
 distance=np.abs(yy-cy);inside=(distance<half)&(nx<1)
 source_distance=np.where(distance<=target,distance/scale,
   band+(distance-target)*(half-band)/np.maximum(half-target,1e-6))
 source_y=cy+np.sign(yy-cy)*source_distance
 source_y=np.where(inside,source_y,yy).astype(np.float32)
 warped=cv.remap(animated,xx,source_y,cv.INTER_LINEAR,borderMode=cv.BORDER_REPLICATE)
 result=animated.copy();patch=result[y0:y1,x0:x1]
 patch[inside]=warped[inside]
 return result

class PauseMouthCorrection:
 """Track the current mouth and close it without swapping art or texture."""
 def __init__(self,neutral,profile):
  self.neutral=neutral;self.profile=profile;self.shift=np.zeros(2,np.float32)
  self.last_time=None;self.voice=1.
  mx,my,mw,mh=profile['mouth_box_body'];h,w=neutral.shape[:2]
  self.limit=min(10.,mw*.25)
  # Register stable facial detail above the lips. Lip movement never drives
  # the alignment and the body/chair are excluded from registration.
  x0=max(0,int(mx-mw));x1=min(w,int(mx+2*mw))
  y0=max(0,int(profile['nose_y_body']-mw*1.5));y1=min(h,int(my-2))
  self.box=(x0,y0,x1,y1)
  self.reference=cv.cvtColor(neutral[y0:y1,x0:x1],cv.COLOR_RGB2GRAY).astype(np.float32)/255
  self.reference=cv.GaussianBlur(self.reference,(3,3),0)
  self.mask=np.uint8(self.reference<.97)*255
 def apply(self,animated,voice,t):
  dt=.04 if self.last_time is None else max(0.,min(.2,t-self.last_time))
  reset=self.last_time is None or t<self.last_time or t-self.last_time>.5
  self.last_time=t
  target=np.clip(voice,0,1)
  if reset:self.voice=float(target);self.shift[:]=0
  else:
   # Ease closing over ~quarter second. Reopen quickly for consonant onset.
   tau=.18 if target<self.voice else .035
   self.voice+=float(target-self.voice)*(1-math.exp(-dt/tau))
  x0,y0,x1,y1=self.box
  current=cv.cvtColor(animated[y0:y1,x0:x1],cv.COLOR_RGB2GRAY).astype(np.float32)/255
  current=cv.GaussianBlur(current,(3,3),0)
  warp=np.array([[1,0,self.shift[0]],[0,1,self.shift[1]]],np.float32)
  try:
   score,warp=cv.findTransformECC(self.reference,current,warp,cv.MOTION_TRANSLATION,(cv.TERM_CRITERIA_COUNT|cv.TERM_CRITERIA_EPS,20,1e-4),self.mask,3)
   candidate=warp[:,2]
   if score>.65 and np.all(np.abs(candidate)<=self.limit):
    self.shift+=(candidate-self.shift)*(1-math.exp(-dt/.12))
  except cv.error:pass # Keep previous validated alignment, never snap to zero.
  return mouth_rest(animated,self.neutral,self.profile,self.voice,self.shift)

def breathe(image,p,t,pixels,figure_height):
 if pixels<=0:return image
 if getattr(p,'breath_mask',None) is None:return image
 h,w=image.shape[:2];dy=-pixels*h/figure_height*math.sin(t*math.tau/4.6)
 yy,xx=np.mgrid[:h,:w].astype(np.float32);mask=p.breath_mask
 shifted=cv.remap(image,xx,yy-mask*dy,cv.INTER_LINEAR,borderMode=cv.BORDER_CONSTANT,borderValue=(255,255,255))
 # Strict mask support: all chair/head/feet pixels remain byte-identical.
 return np.uint8(np.rint(image*(1-mask[:,:,None])+shifted*mask[:,:,None]))
