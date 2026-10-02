#!/usr/bin/env python3
"""Reuse validated source landmarks through SadTalker's exact crop/resize pipeline.
Runtime patch only; the user's checkout stays unchanged.
"""
import argparse,hashlib,json,runpy,sys
from pathlib import Path

def transform_landmarks(points,size,rsize,crop,quad,still,pic_size):
    import numpy as np
    p=np.asarray(points,float).copy();w,h=size
    p*=np.array(rsize)/np.array([w,h])
    clx,cly,crx,cry=map(int,crop);p-=[clx,cly];cw=crx-clx;ch=cry-cly
    if not still:
        lx,ly,rx,ry=map(int,quad);p-=[lx,ly]
        # Match NumPy slice clamping when the last pixel reaches the crop edge.
        cw=min(rx,cw)-lx;ch=min(ry,ch)-ly
    if min(cw,ch)<=0:raise ValueError('Invalid SadTalker crop transform')
    p*=np.array([pic_size/cw,pic_size/ch]);return p

def main():
    p=argparse.ArgumentParser();p.add_argument('--repo',required=True);p.add_argument('--landmarks',required=True)
    a,inference_args=p.parse_known_args();repo=Path(a.repo).resolve();sys.path.insert(0,str(repo))
    import numpy as np
    from PIL import Image
    data=json.loads(Path(a.landmarks).read_text());points=np.asarray(data['points'],float)
    if points.shape!=(68,2) or not np.isfinite(points).all():raise ValueError('Invalid validated source landmarks')
    from src.utils.preprocess import CropAndExtract
    original=CropAndExtract.generate
    def generate(self,input_path,save_dir,crop_or_resize='crop',source_image_flag=False,pic_size=256):
        source=Path(input_path)
        if not source_image_flag or hashlib.sha256(source.read_bytes()).hexdigest()!=data['image_sha256']:
            return original(self,input_path,save_dir,crop_or_resize,source_image_flag,pic_size)
        with Image.open(source) as image:
            size=image.size
            if list(size)!=data['size']:raise ValueError('Source dimensions differ from landmark calibration')
            if 'crop' in crop_or_resize.lower() or 'full' in crop_or_resize.lower():
                rsize,crop,quad=self.propress.align_face(image,points.copy(),output_size=512)
                lm=transform_landmarks(points,size,rsize,crop,quad,'ext' in crop_or_resize.lower(),pic_size)
            else:lm=points*np.array([pic_size/size[0],pic_size/size[1]])
        # The internal crop receives original-image points; coefficient alignment
        # receives points transformed into the resized crop, rather than detecting again.
        previous=self.propress.get_landmark
        self.propress.get_landmark=lambda img:points.copy()
        Path(save_dir).mkdir(parents=True,exist_ok=True)
        cache=Path(save_dir)/(source.stem+'_landmarks.txt');np.savetxt(cache,lm.reshape(-1))
        try:
            print('Using validated drawing landmarks for both crop and 3DMM alignment.',flush=True)
            return original(self,input_path,save_dir,crop_or_resize,source_image_flag,pic_size)
        finally:self.propress.get_landmark=previous
    CropAndExtract.generate=generate
    sys.argv=[str(repo/'inference.py'),*inference_args]
    runpy.run_path(str(repo/'inference.py'),run_name='__main__')

if __name__=='__main__':main()
