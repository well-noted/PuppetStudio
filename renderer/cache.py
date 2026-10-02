"""Read registered source-face caches without changing or rerunning the engine."""
import json,math
from pathlib import Path
import cv2 as cv
import numpy as np
from PIL import Image

def read(path):return json.loads(Path(path).read_text(encoding='utf-8-sig'))
def clean_art(body):
    ink=np.uint8(np.min(body,axis=2)<245)*255
    contours,_=cv.findContours(ink,cv.RETR_EXTERNAL,cv.CHAIN_APPROX_SIMPLE)
    if not contours:raise ValueError('Character sheet is blank')
    keep=np.zeros_like(ink);cv.drawContours(keep,[max(contours,key=cv.contourArea)],-1,255,-1)
    result=body.copy();result[(keep==0)&(ink>0)]=255
    return result
def decode(v):
    v=v.astype(np.float32)/255
    return np.where(v<=.04045,v/12.92,((v+.055)/1.055)**2.4)
def encode(v):
    v=np.clip(v,0,1)
    return np.uint8(np.rint(np.clip(np.where(v<=.0031308,v*12.92,1.055*v**(1/2.4)-.055),0,1)*255))

def lower_face_alpha(alpha,profile,box):
    """Protect source eyes/glasses even when an older cache has a full-face mask."""
    _,y,_,h=box
    nose=float(profile['nose_y_body'])-y
    mouth=float(profile['mouth_box_body'][1])-y
    feather=max(1.,min(8.,(mouth-nose)*.5))
    rows=np.arange(h,dtype=np.float32)[:,None,None]
    weight=np.clip((rows-nose)/feather,0,1)
    weight=weight*weight*(3-2*weight)
    return alpha*weight

class Actor:
    def __init__(self,out):
        self.out=Path(out).resolve()
        if (self.out/'RUNNING.lock').exists():
            raise ValueError('Face cache is currently being written: '+str(self.out)+'. Wait for that animation job to finish.')
        if not (self.out/'result.json').is_file():
            raise ValueError('Face animation is not complete yet: '+str(self.out)+'. Finish the existing animation run first.')
        reg=read(self.out/'registration/registration.json');self.profile=read(self.out/'profile.json')
        if not reg['quality']['quality_passed']:raise ValueError('Registration quality failed')
        self.body=np.asarray(Image.open(self.out/'assets/body.png').convert('RGB')).copy()
        for x,y,w,h in self.profile.get('background_cleanup_boxes',[]):self.body[y:y+h,x:x+w]=255
        self.body=clean_art(self.body)
        meta=read(self.out/'assets/assets.json');self.box=meta['bust_box_body'];x,y,w,h=self.box
        px,py,_,_=meta['bust_content_box'];mask=np.asarray(Image.open(self.out/'mask.png').convert('L'))
        self.alpha=lower_face_alpha(mask[py:py+h,px:px+w,None].astype(np.float32)/255,self.profile,self.box)
        self.matrix=np.asarray(reg['matrix_video_to_body'],np.float32).copy();self.matrix[:,2]-=[x,y]
        video=Path(reg['video'])
        if not video.is_file():
            # Moving a project is fine; substituting a differently stabilized
            # video for the registered source would invalidate its transform.
            video=self.out/video.name
        self.cap=cv.VideoCapture(str(video));self.fps=self.cap.get(cv.CAP_PROP_FPS);self.count=int(self.cap.get(cv.CAP_PROP_FRAME_COUNT))
        if self.fps<=0 or self.count<=0:raise ValueError('Registered face video is missing or unreadable')
        self.duration=self.count/self.fps;self.audio=self.out/'animation.mp4'
        if not self.audio.is_file():raise ValueError('Engine animation with speech audio is missing')
        self.reference=self.body[y:y+h,x:x+w].copy();self.linear=decode(self.reference)
        self.buffer={};self.next_index=0
        # Use one fixed color bias for the complete source cache.
        gray=cv.cvtColor(self.reference,cv.COLOR_RGB2GRAY)
        gradient=cv.magnitude(cv.Sobel(gray,cv.CV_32F,1,0),cv.Sobel(gray,cv.CV_32F,0,1))
        anchors=(gray>150)&(gradient<24)&(self.alpha[:,:,0]>.05);values=[]
        for i in [0,self.count//2,self.count-1]:
            fr=self.sample(i);aligned=cv.warpAffine(fr,self.matrix,(w,h),borderValue=(255,255,255))
            valid=anchors&(np.min(aligned,2)>100)
            if valid.sum()>50:values.append(np.median(self.reference[valid].astype(float)-aligned[valid].astype(float),axis=0))
        self.bias=np.clip(np.median(values,axis=0),-16,16) if values else np.zeros(3)
        upper=(np.arange(h)[:,None]<self.profile['nose_y_body']-y-3)&(self.alpha[:,:,0]>.1)
        inv=cv.invertAffineTransform(self.matrix)
        self.upper=cv.warpAffine(np.uint8(upper)*255,inv,(int(self.cap.get(cv.CAP_PROP_FRAME_WIDTH)),int(self.cap.get(cv.CAP_PROP_FRAME_HEIGHT))),flags=cv.INTER_NEAREST)>0

    def bind_master(self,master):
        # Extraction and cache reading clean disconnected specks. Compare both
        # drawings with exactly the same normalization, never a loose tolerance.
        normalized=master.copy()
        for x,y,w,h in self.profile.get('background_cleanup_boxes',[]):normalized[y:y+h,x:x+w]=255
        if master.shape!=self.body.shape or not np.array_equal(clean_art(normalized),self.body):
            raise ValueError('Face cache truly uses different art after identical background cleanup')
        self.master=master.copy()

    def sample(self,index):
        index=max(0,min(self.count-1,index))
        if index in self.buffer:return self.buffer[index]
        if index!=self.next_index:self.cap.set(cv.CAP_PROP_POS_FRAMES,index)
        ok,bgr=self.cap.read()
        if not ok:raise ValueError('Source face video ended unexpectedly')
        frame=cv.cvtColor(bgr,cv.COLOR_BGR2RGB);self.next_index=index+1;self.buffer[index]=frame
        if len(self.buffer)>8:
            for key in list(self.buffer):
                if abs(key-index)>3:self.buffer.pop(key)
        return frame

    def frame(self,time,calm=True):
        if not math.isfinite(time) or time<0 or time>self.duration+.05:raise ValueError('Speech interval exceeds its face cache')
        index=min(self.count-1,round(time*self.fps));current=self.sample(index)
        if calm:
            prev=self.sample(index-1);nxt=self.sample(index+1)
            a=prev.astype(float);b=current.astype(float);c=nxt.astype(float)
            selected=(np.max(np.abs(a-c),2)<28)&(np.max(np.abs(a-b),2)>20)&(np.max(np.abs(c-b),2)>20)&self.upper
            current=current.copy();median=np.median(np.stack([prev,current,nxt]),axis=0).astype(np.uint8);current[selected]=median[selected]
        x,y,w,h=self.box;fr=np.uint8(np.clip(current.astype(float)+self.bias,0,255))
        aligned=cv.warpAffine(fr,self.matrix,(w,h),borderValue=(255,255,255))
        valid=cv.warpAffine(np.ones(fr.shape[:2],np.float32),self.matrix,(w,h),borderValue=0)[:,:,None]
        alpha=self.alpha*valid;result=getattr(self,"master",self.body).copy()
        result[y:y+h,x:x+w]=encode(self.linear*(1-alpha)+decode(aligned)*alpha)
        return result

    def close(self):self.cap.release()
