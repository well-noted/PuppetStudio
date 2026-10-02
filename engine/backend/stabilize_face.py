#!/usr/bin/env python3
"""Remove rapid face drift; lightly filter small upper-face texture fluctuations.
Expressions and mouth pixels are not temporally blended. No frame duplication.
"""
import argparse,json,subprocess
from pathlib import Path
import cv2 as cv
import numpy as np

def smooth(values,radius):
    k=np.arange(-radius,radius+1); weights=np.exp(-.5*(k/max(1,radius/2))**2);weights/=weights.sum()
    return np.stack([np.convolve(np.pad(values[:,i],(radius,radius),mode='edge'),weights,'valid') for i in range(2)],1)

def estimate(reference,image,mask):
    warp=np.eye(2,3,dtype=np.float32)
    try:
        score,warp=cv.findTransformECC(reference,image,warp,cv.MOTION_TRANSLATION,
            (cv.TERM_CRITERIA_EPS|cv.TERM_CRITERIA_COUNT,35,.0001),mask,3)
        return warp[:,2].copy(),float(score)
    except cv.error:return np.zeros(2),0.

def process(source,output,roi,strength=.85,texture=.3):
    cap=cv.VideoCapture(str(source));fps=cap.get(cv.CAP_PROP_FPS);ok,first=cap.read()
    if not ok or fps<=0:raise ValueError('Cannot read face video')
    h,w=first.shape[:2];scale=min(1.,256/w);sw,sh=round(w*scale),round(h*scale)
    x,y,rw,rh=roi
    if not (0<=x<1 and 0<=y<1 and rw>0 and rh>0 and x+rw<=1 and y+rh<=1):raise ValueError('Invalid normalized stable ROI')
    mask=np.zeros((sh,sw),np.uint8);mask[round(y*sh):round((y+rh)*sh),round(x*sw):round((x+rw)*sw)]=255
    def gray(im):return cv.cvtColor(cv.resize(im,(sw,sh)),cv.COLOR_BGR2GRAY).astype(np.float32)/255
    ref=gray(first);shifts=[];scores=[];im=first
    while True:
        shift,score=estimate(ref,gray(im),mask)
        if score<.7 or np.max(np.abs(shift))>8*scale:shift=shifts[-1] if shifts else np.zeros(2)
        shifts.append(shift);scores.append(score)
        ok,im=cap.read()
        if not ok:break
    cap.release();shifts=np.array(shifts)/scale
    # Preserve gradual head/expression movement; only remove the rapid residual.
    correction=(shifts-smooth(shifts,max(2,round(fps*.18))))*strength
    upper=cv.resize(mask,(w,h)).astype(np.float32)/255
    upper=(cv.GaussianBlur(upper,(0,0),max(1,w*.014))*upper)[:,:,None]
    output=Path(output);output.parent.mkdir(parents=True,exist_ok=True)
    cmd=['ffmpeg','-v','error','-y','-f','rawvideo','-pix_fmt','bgr24','-s',f'{w}x{h}','-r',str(fps),'-i','pipe:0',
         '-an','-c:v','libx264','-crf','16','-preset','medium','-pix_fmt','yuv420p',str(output)]
    log=output.with_suffix('.ffmpeg.log').open('wb');enc=subprocess.Popen(cmd,stdin=subprocess.PIPE,stderr=log)
    cap=cv.VideoCapture(str(source));previous=None;current=None
    def read(index):
        ok,im=cap.read()
        if not ok:return None
        matrix=np.eye(2,3,dtype=np.float32);matrix[:,2]=-correction[index]
        return cv.warpAffine(im,matrix,(w,h),flags=cv.INTER_LINEAR,borderMode=cv.BORDER_REPLICATE)
    try:
        current=read(0)
        for i in range(len(shifts)):
            following=read(i+1) if i+1<len(shifts) else current
            if current is None or following is None:raise ValueError('Video changed during stabilization')
            prev=previous if previous is not None else current
            # Motion compensation before filtering avoids doubled glasses/edges.
            neighbors=[]
            for neighbor in (prev,following):
                shift,score=estimate(gray(current),gray(neighbor),mask)
                if score>.7 and np.max(np.abs(shift))<8*scale:
                    matrix=np.eye(2,3,dtype=np.float32);matrix[:,2]=-shift/scale
                    neighbor=cv.warpAffine(neighbor,matrix,(w,h),flags=cv.INTER_LINEAR,borderMode=cv.BORDER_REPLICATE)
                else:neighbor=current
                neighbors.append(neighbor.astype(np.float32))
            cur=current.astype(np.float32);average=(neighbors[0]+neighbors[1])/2
            difference=np.maximum(np.max(np.abs(neighbors[0]-cur),2),np.max(np.abs(neighbors[1]-cur),2))
            # Larger changes (e.g. blink/expression) pass through unchanged.
            weight=upper*texture*np.clip(1-difference[:,:,None]/22,0,1)**2
            filtered=np.clip(cur+(average-cur)*weight,0,255).astype(np.uint8)
            enc.stdin.write(filtered.tobytes());previous=current;current=following
        enc.stdin.close()
        if enc.wait():raise RuntimeError('FFmpeg stabilization failed; see '+str(output.with_suffix('.ffmpeg.log')))
    finally:
        cap.release();log.close()
        if enc.poll() is None:enc.terminate();enc.wait()
    report={'frames':len(shifts),'fps':fps,'roi':roi,'drift_strength':strength,'texture_strength':texture,
            'measured_rapid_shift_rms_px':float(np.sqrt(np.mean((shifts-smooth(shifts,max(2,round(fps*.18))))**2))),
            'max_correction_px':float(np.max(np.abs(correction))),'low_confidence_frames':sum(s<.7 for s in scores),
            'scope':'rapid translation and small upper-face fluctuations; mouth unchanged by temporal filtering'}
    output.with_suffix('.stabilization.json').write_text(json.dumps(report,indent=2)+'\n')
    return report

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--input',required=True);p.add_argument('--output',required=True)
    p.add_argument('--roi',nargs=4,type=float,default=[.2,.28,.6,.27]);p.add_argument('--strength',type=float,default=.85)
    p.add_argument('--texture',type=float,default=.3);a=p.parse_args()
    if not 0<=a.strength<=1 or not 0<=a.texture<=1:p.error('Strengths must be 0..1')
    print(json.dumps(process(a.input,a.output,a.roi,a.strength,a.texture),indent=2))
