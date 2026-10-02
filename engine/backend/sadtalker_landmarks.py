#!/usr/bin/env python3
"""Find measured FAN landmarks on an illustration, constrained by its source profile.
Runs in the existing SadTalker environment. No landmark templates or clicked points.
"""
import argparse,json,sys
from pathlib import Path

def score_landmarks(points,hints,size):
    import numpy as np
    p=np.asarray(points,dtype=float);w,h=size
    if p.shape!=(68,2) or not np.isfinite(p).all():return None
    if (p[:,0]<0).any() or (p[:,0]>=w).any() or (p[:,1]<0).any() or (p[:,1]>=h).any():return None
    mx,my,mw,mh=hints['mouth_box'];target=np.array([mx+mw/2,my+mh/2])
    mouth=p[48:60].mean(0);left=p[36:42].mean(0);right=p[42:48].mean(0);eyes=(left+right)/2
    distance=float(np.linalg.norm(mouth-target));limit=max(8.,mw*.45)
    if distance>limit:return None
    mouth_width=float(np.linalg.norm(p[54]-p[48]));eye_gap=float(np.linalg.norm(right-left))
    if not mw*.35<mouth_width<mw*1.8 or not eye_gap>mw*.35:return None
    # Reject flipped, misplaced, or collapsed landmark fits. Nose/jaw anchors are calibrated.
    if not left[0]<right[0] or not eyes[1]+5<p[30,1]<mouth[1] or not mouth[1]+5<p[8,1]:return None
    if abs(p[30,1]-hints['nose_y'])>max(18.,mh*1.4):return None
    if abs(p[8,1]-hints['jaw_y'])>max(40.,mw):return None
    return distance+abs(mouth_width-mw)*.1+abs(p[30,1]-hints['nose_y'])*.15

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--repo',required=True);p.add_argument('--image',required=True)
    p.add_argument('--hints',required=True);p.add_argument('--output',required=True);a=p.parse_args()
    import cv2 as cv
    import numpy as np
    import torch
    from PIL import Image,ImageDraw
    repo=Path(a.repo).resolve();sys.path.insert(0,str(repo))
    from src.utils.croper import Preprocesser
    from facexlib.alignment import landmark_98_to_68
    image=cv.cvtColor(cv.imread(a.image),cv.COLOR_BGR2RGB);h,w=image.shape[:2]
    hints=json.loads(Path(a.hints).read_text());model=Preprocesser('cuda');candidates=[];failures=[];rejected=[]
    def fit(box,method,confidence=0):
        x0,y0,x1,y1=[int(v) for v in box];x0=max(0,x0);y0=max(0,y0);x1=min(w,x1);y1=min(h,y1)
        if x1-x0<32 or y1-y0<40:return
        try:
            with torch.no_grad():points=np.asarray(landmark_98_to_68(model.predictor.detector.get_landmarks(image[y0:y1,x0:x1])),dtype=float)
            points+=np.array([x0,y0]);value=score_landmarks(points,hints,(w,h))
            if value is not None:candidates.append({'score':value,'method':method,'box':[x0,y0,x1,y1],'confidence':confidence,'points':points})
            else:
                failures.append(method+': landmark geometry did not pass')
                if points.shape==(68,2) and np.isfinite(points).all():
                    mx,my,mw,mh=hints['mouth_box'];distance=float(np.linalg.norm(points[48:60].mean(0)-[mx+mw/2,my+mh/2]))
                    rejected.append({'method':method,'mouth_distance_px':distance,'points':points.tolist()})
        except Exception as e:failures.append(method+': '+str(e))
    # Lower thresholds only propose rectangles; calibrated anatomy validates the landmarks.
    for scale in (1.,2.):
        scaled=cv.resize(image,(round(w*scale),round(h*scale)))
        for threshold in (.97,.75,.5,.3):
            with torch.no_grad():detections=model.predictor.det_net.detect_faces(scaled,threshold)
            for i,det in enumerate(detections[:3]):fit(np.array(det[:4])/scale,f'retinaface scale={scale} threshold={threshold} candidate={i}',float(det[4]))
    # Detector-independent bounded crops still use the real FAN landmark model.
    mx,my,mw,mh=hints['mouth_box'];cx=mx+mw/2;face_width=hints['jaw_width']*1.2
    top=hints['nose_y']-(hints['jaw_y']-hints['nose_y'])*1.1;bottom=min(h,hints['jaw_y']+h*.025)
    center=np.array([cx-face_width*.075,(top+bottom)/2]);span=np.array([face_width,bottom-top])
    for zoom in (.85,1.,1.15):
        for dx in (-.08,0,.08):
            c=center+[face_width*dx,0];fit([*(c-span*zoom/2),*(c+span*zoom/2)],f'bounded FAN zoom={zoom} shift={dx}')
    out=Path(a.output);out.parent.mkdir(parents=True,exist_ok=True)
    if not candidates:
        out.with_suffix('.rejected.json').write_text(json.dumps({'failures':failures,'hints':hints,'candidates':rejected},indent=2)+'\n')
        if rejected:
            canvas=Image.fromarray(image);draw=ImageDraw.Draw(canvas);mx,my,mw,mh=hints['mouth_box']
            draw.rectangle((mx,my,mx+mw,my+mh),outline='orange',width=2)
            for x,y in min(rejected,key=lambda r:r['mouth_distance_px'])['points']:draw.ellipse((x-1,y-1,x+1,y+1),fill='red')
            canvas.resize((w*3,h*3)).save(out.with_suffix('.rejected.preview.png'))
        raise RuntimeError('No anatomically valid FAN landmark candidate; see '+str(out.with_suffix('.rejected.json')))
    best=min(candidates,key=lambda c:c['score']);points=best.pop('points')
    import hashlib
    result={'version':1,'size':[w,h],'image_sha256':hashlib.sha256(Path(a.image).read_bytes()).hexdigest(),
        'points':points.tolist(),'selected':best,'accepted_candidates':len(candidates),'hints':hints}
    out.write_text(json.dumps(result,indent=2)+'\n');canvas=Image.fromarray(image);draw=ImageDraw.Draw(canvas)
    x,y,bw,bh=hints['mouth_box'];draw.rectangle((x,y,x+bw,y+bh),outline='orange',width=2)
    for i,(x,y) in enumerate(points):
        color='red' if 48<=i<68 else 'blue';draw.ellipse((x-1.2,y-1.2,x+1.2,y+1.2),fill=color)
    canvas.resize((w*3,h*3)).save(out.with_suffix('.preview.png'))
    print('Validated FAN landmarks:',best['method'],'score=',best['score'],flush=True)

if __name__=='__main__':main()
