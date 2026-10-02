#!/usr/bin/env python3
"""One command, resumable talking-illustration workflow. See README.md."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parent

def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()

def save(path,data):
    temporary=Path(str(path)+'.tmp')
    temporary.write_text(json.dumps(data,indent=2)+'\n',encoding='utf-8')
    temporary.replace(path)

def read(path):return json.loads(Path(path).read_text(encoding='utf-8'))

def probe(path):
    return json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams',
        '-show_format','-of','json',str(path)],text=True))

def unique(folder,stem,extensions,required=True):
    found=[p for p in folder.iterdir() if p.is_file() and p.stem.lower()==stem and p.suffix.lower() in extensions]
    if len(found)>1 or (required and len(found)!=1):
        raise ValueError(f'Provide exactly one {stem} file in {folder}; found {len(found)}')
    return found[0].resolve() if found else None

def auto_profile(image,cache):
    """Detect anatomy on one clean character; never use guessed default boxes."""
    import cv2 as cv
    try:
        import mediapipe as mp
    except ImportError:
        raise ValueError('Install optional anatomy dependencies with setup.cmd --anatomy, or import profile.json') from None
    import numpy as np
    import urllib.request
    model=cache/'face_landmarker.task'
    if not model.exists():
        cache.mkdir(parents=True,exist_ok=True)
        url='https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task'
        temp=model.with_suffix('.download')
        print('Downloading the face detector once...',flush=True)
        urllib.request.urlretrieve(url,temp);temp.replace(model)
    im=cv.imread(str(image));h,w=im.shape[:2]
    opts=mp.tasks.vision.FaceLandmarkerOptions(base_options=mp.tasks.BaseOptions(
        model_asset_path=str(model),delegate=mp.tasks.BaseOptions.Delegate.CPU),num_faces=2)
    # Full-body drawings make the face too small for a single detector pass.
    # Scan overlapping, image-derived tiles and deduplicate the same face.
    boxes=[(0,0,w,h)]
    for fraction in [.5,.75]:
        size=max(128,int(min(w,h)*fraction));step=max(1,size//2)
        xs=sorted(set([*range(0,max(1,w-size+1),step),max(0,w-size)]))
        ys=sorted(set([*range(0,max(1,h-size+1),step),max(0,h-size)]))
        boxes.extend((x,y,min(size,w-x),min(size,h-y)) for y in ys for x in xs)
    candidates=[]
    with mp.tasks.vision.FaceLandmarker.create_from_options(opts) as detector:
        for x,y,tw,th in boxes:
            tile=im[y:y+th,x:x+tw]
            result=detector.detect(mp.Image(image_format=mp.ImageFormat.SRGB,data=cv.cvtColor(tile,cv.COLOR_BGR2RGB)))
            for face in result.face_landmarks:
                points=np.array([[q.x*tw+x,q.y*th+y] for q in face])
                lo,hi=points.min(axis=0),points.max(axis=0)
                if (lo<[x+2,y+2]).any() or (hi>[x+tw-2,y+th-2]).any():continue
                candidates.append(points)
    distinct=[]
    for points in sorted(candidates,key=lambda p:float(np.prod(np.ptp(p,axis=0))),reverse=True):
        center=points.mean(axis=0);span=np.linalg.norm(np.ptp(points,axis=0))
        if not any(np.linalg.norm(center-q.mean(axis=0))<.4*min(span,np.linalg.norm(np.ptp(q,axis=0))) for q in distinct):
            distinct.append(points)
    if len(distinct)!=1:
        raise ValueError('Could not reliably detect ONE face. Supply a calibrated profile.json; no guessed mouth placement will be used.')
    p=distinct[0]
    mouth=p[[61,291,0,17,13,14]];lo=mouth.min(axis=0);hi=mouth.max(axis=0)
    nose=float(p[2,1]);jaw=float(p[152,1]);mw=float(hi[0]-lo[0])
    if mw<8 or not nose<lo[1]<hi[1]<jaw or not np.isfinite(p).all():
        raise ValueError('Detected anatomy is implausible. Supply a calibrated profile.json.')
    face_lo=p.min(axis=0);face_hi=p.max(axis=0);fw,fh=face_hi-face_lo
    x=max(0,int(face_lo[0]-.35*fw));y=max(0,int(face_lo[1]-.6*fh))
    x1=min(w,int(face_hi[0]+.35*fw));y1=min(h,int(face_hi[1]+.2*fh))
    return {'name':'automatic-face','bust':[x,y,x1-x,y1-y],
        'mouth_box_body':[float(lo[0]),float(lo[1]),mw,float(hi[1]-lo[1])],
        'nose_y_body':nose,'jaw_y_body':jaw,'jaw_width':float(np.linalg.norm(p[234]-p[454]))*.8,
        'animation_polygon_body':cv.convexHull(p.astype('float32')).reshape(-1,2).tolist(),
        'detector_model_sha256':digest(model)}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--assets',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--tools',type=Path,default=ROOT/'tools.json')
    parser.add_argument('--profile',type=Path)
    parser.add_argument('--check',action='store_true',help='Check inputs/setup without neural inference')
    args=parser.parse_args()
    folder=args.assets.resolve();out=args.out.resolve()
    if not folder.is_dir():raise ValueError('Asset folder does not exist')
    if out==folder or folder in out.parents:raise ValueError('Output must be separate from the asset folder')
    for tool in ['ffmpeg','ffprobe']:
        if not shutil.which(tool):raise ValueError(f'Install {tool} and put it on PATH')
    try:
        import cv2
        import numpy
        from PIL import Image,ImageOps
    except ImportError as e:raise ValueError('Install requirements.txt in this Python environment') from e
    image=unique(folder,'character',{'.png','.jpg','.jpeg','.webp'})
    audio=unique(folder,'speech',{'.wav','.mp3','.m4a','.flac'})
    face=unique(folder,'face',{'.mp4','.mkv'},required=False)
    if not any(s['codec_type']=='audio' for s in probe(audio)['streams']):raise ValueError('Speech has no audio stream')
    if face:
        fp=probe(face);video=next((s for s in fp['streams'] if s['codec_type']=='video'),None)
        if not video:raise ValueError('face.mp4 has no video stream')
        if abs(float(video.get('duration',fp['format']['duration']))-float(probe(audio)['format']['duration']))>.5:
            raise ValueError('Cached face video and speech differ in duration by more than 0.5s')
    settings=read(args.tools) if args.tools.exists() else {}
    for key in ['sadtalker_repo','sadtalker_python']:
        if settings.get(key):
            value=settings[key].strip()
            if len(value)>=2 and value[0]==value[-1] and value[0] in [chr(34),chr(39)]:value=value[1:-1].strip()
            settings[key]=value
    repo=python=None
    if face is None:
        if not settings.get('sadtalker_repo') or not settings.get('sadtalker_python'):
            sys.path.insert(0,str(ROOT/'backend'))
            from discover_sadtalker import discover
            print('Locating existing SadTalker and CUDA Python...',flush=True)
            settings={**discover(ROOT),**settings}
            save(args.tools,settings)
            print('SadTalker:',settings['sadtalker_repo'],flush=True)
            print('CUDA Python:',settings['sadtalker_python'],flush=True)
        repo=Path(settings['sadtalker_repo']).expanduser().resolve();python=Path(settings['sadtalker_python']).expanduser().resolve()
        if not (repo/'inference.py').is_file():raise ValueError('SadTalker inference.py not found at '+str(repo/'inference.py')+'; check the checkout path under Advanced.')
        if not python.is_file():raise ValueError('CUDA Python executable not found at '+str(python)+'; check the Python path under Advanced.')
        if not (repo/'checkpoints').is_dir() or not any((repo/'checkpoints').iterdir()):raise ValueError('SadTalker checkpoints are missing')
        verify=subprocess.run([str(python),'-c','import torch; print(torch.cuda.is_available())'],capture_output=True,text=True)
        if verify.returncode or 'True' not in verify.stdout:raise ValueError('SadTalker Python cannot use CUDA. Fix that environment before an overnight run.')
    explicit=args.profile or (folder/'profile.json' if (folder/'profile.json').exists() else None)
    profile=read(explicit) if explicit else next((read(p) for p in (ROOT/'profiles').glob('*.json')
        if read(p).get('source_sha256')==digest(image)),None)
    if explicit and profile.get('source_sha256') and profile['source_sha256']!=digest(image):
        raise ValueError('This anatomy profile belongs to a different image; use automatic detection or a matching profile.')
    if args.check:
        print('Setup passed.','Cached face video will be reused.' if face else 'SadTalker CUDA environment is available.')
        if not profile:print('Face anatomy will be detected automatically at run time; illustration detection may fail.')
        return
    out.mkdir(parents=True,exist_ok=True)
    lock=out/'RUNNING.lock'
    try:
        fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY);os.write(fd,str(os.getpid()).encode());os.close(fd)
    except FileExistsError:raise ValueError(f'Another run may be active. If it crashed, remove {lock} before resuming.')
    state_path=out/'state.json'
    inputs={'character':digest(image),'audio':digest(audio),'cached_face':digest(face) if face else None,
        'profile':digest(explicit) if explicit else profile,'settings':settings,
        'package':{str(p.relative_to(ROOT)):digest(p) for p in [Path(__file__),*(ROOT/'backend').glob('*.py')]}}
    fingerprint=hashlib.sha256(json.dumps(inputs,sort_keys=True).encode()).hexdigest()
    state=read(state_path) if state_path.exists() else {'fingerprint':fingerprint,'stages':{}}
    dirty=False;completed=[]
    def stage(name,action,outputs):
        nonlocal dirty
        existing=state['stages'].get(name)
        if not dirty and existing and all(p.is_file() and digest(p)==existing.get(str(p)) for p in outputs):
            print('RESUME:',name,flush=True);completed.append(name);return
        dirty=True
        state['stages']={k:v for k,v in state['stages'].items() if k in completed};save(state_path,state)
        print('RUN:',name,flush=True);start=time.time();action()
        if not all(p.is_file() for p in outputs):raise RuntimeError('Stage did not produce expected files: '+name)
        state['stages'][name]={str(p):digest(p) for p in outputs};save(state_path,state)
        completed.append(name)
        print(f'DONE: {name} ({time.time()-start:.1f}s)',flush=True)
    def command(name,cmd):
        with (out/(name+'.log')).open('wb') as log:
            r=subprocess.run([str(x) for x in cmd],stdout=log,stderr=subprocess.STDOUT)
        if r.returncode:
            print((out/(name+'.log')).read_text(encoding='utf-8',errors='replace')[-14000:],flush=True)
            raise RuntimeError(f'{name} failed. See {out/(name+".log") }')
    backend=[sys.executable,ROOT/'backend/pipeline.py']
    try:
        if state['fingerprint']!=fingerprint:raise ValueError('Inputs, settings or scripts changed. Use a NEW output folder to avoid stale intermediates.')
        profile_path=out/'profile.json'
        stage('anatomy',lambda:save(profile_path,profile or auto_profile(image,ROOT/'models')),[profile_path])
        profile=read(profile_path)
        with Image.open(image) as im:w,h=ImageOps.exif_transpose(im).size
        assets=out/'assets';metadata=assets/'assets.json'
        def extract():
            command('extract',backend+['extract','--sheet',image,'--body',0,0,w,h,
                '--bust',*profile['bust'],'--square-pad','--out',assets])
            reference=settings.get('source_bust_reference')
            if reference:
                with Image.open(reference) as ref, Image.open(assets/'bust.png') as expected:
                    if ref.size!=expected.size:raise ValueError('Inference bust must match the extracted padded canvas')
                    if digest(reference)!=settings.get('source_bust_reference_sha256'):raise ValueError('Inference bust changed after configuration')
                    ref.convert('RGB').save(assets/'bust.png')
            # Known detached palette swatches in the supplied drawing, outside the figure.
            boxes=profile.get('background_cleanup_boxes',[])
            if boxes:
                from PIL import ImageDraw
                with Image.open(assets/'body.png') as im:
                    clean=im.convert('RGB');draw=ImageDraw.Draw(clean)
                    for x,y,cw,ch in boxes:draw.rectangle((x,y,x+cw-1,y+ch-1),fill='white')
                    clean.save(assets/'body.png')
        stage('extract',extract,[metadata,assets/'body.png',assets/'bust.png'])
        neural=out/'face.mp4'
        def synthesize():
            if face:shutil.copyfile(face,neural);return
            previous=set((out/'neural').glob('*/run.json'))
            extraction=read(metadata);px,py,_,_=extraction['bust_content_box'];bx,by,_,_=profile['bust']
            mx,my,mw,mh=profile['mouth_box_body'];hints=out/'source_landmark_hints.json'
            save(hints,{'mouth_box':[mx-bx+px,my-by+py,mw,mh],
                'nose_y':profile['nose_y_body']-by+py,'jaw_y':profile['jaw_y_body']-by+py,
                'jaw_width':profile['jaw_width']})
            command('synthesis',[sys.executable,ROOT/'backend/run_sadtalker.py','--repo',repo,'--python',python,
                '--image',assets/'bust.png','--audio',audio,'--out',out/'neural','--size',256,
                '--enhancer',settings.get('enhancer','none'),'--expression-scale',settings.get('expression_scale',1.0),
                '--landmark-hints',hints])
            reports=list((out/'neural').glob('*/run.json'))
            successful=[p for p in reports if p not in previous and Path(read(p)['output']).is_file()]
            if len(successful)!=1:raise ValueError('Ambiguous successful neural runs; inspect neural folder')
            shutil.copyfile(read(successful[0])['output'],neural)
        stage('synthesis',synthesize,[neural])
        stable=out/'face_stable.mp4'
        # The glasses/nose anchor is derived from calibrated or detected anatomy.
        bx,by,_,_=profile['bust'];mx,my,mw,mh=profile['mouth_box_body']
        meta=read(metadata);bw,bh=meta['bust_size'];px,py,cw,ch=meta['bust_content_box']
        cx=mx+mw/2-bx+px;ny=profile['nose_y_body']-by+py
        rx=max(0.,(cx-profile['jaw_width']*.5)/bw);ry=max(0.,(ny-bh*.23)/bh)
        roi=[rx,ry,min(profile['jaw_width']/bw,1-rx),min(bh*.21/bh,1-ry)]
        def stabilize():
            if settings.get('stabilize_face',True):
                command('stabilize',[sys.executable,ROOT/'backend/stabilize_face.py','--input',neural,'--output',stable,
                    '--roi',*roi,'--strength',settings.get('stabilization_strength',.85),
                    '--texture',settings.get('upper_face_smoothing',.3)])
            else:shutil.copyfile(neural,stable)
        stage('stabilize',stabilize,[stable])
        cfg=out/'registration_config.json'
        cfg_data={'search_width_px':[int(bw*.8),int(bw*1.15)],'scale_steps':20,
            'search_angles_degrees':[-2,0,2],
            'stable_polygons':[[[px/(bw-1),py/(bh-1)],[(px+cw-1)/(bw-1),py/(bh-1)],
                [(px+cw-1)/(bw-1),.57],[px/(bw-1),.57]]],
            'max_chamfer_px':2.,'min_edge_coverage':.55,'min_valid_fraction':.75,
            'min_sample_pass_fraction':.8,'max_rotation_degrees':5}
        save(cfg,cfg_data)
        registration=out/'registration/registration.json'
        stage('register',lambda:command('register',backend+['register','--assets',metadata,'--video',stable,
            '--config',cfg,'--out',registration.parent]),[registration])
        mask=out/'mask.png'
        def matte():
            sys.path.insert(0,str(ROOT/'backend'))
            import masking
            import numpy as np
            import cv2 as cv
            bx,by,_,_=meta['bust_box_body'];x,y,mw,mh=profile['mouth_box_body']
            gate=masking.gate_from_box([x-bx+px,y-by+py,mw,mh],(bh,bw),
                profile['nose_y_body']-by+py,profile['jaw_y_body']-by+py,profile['jaw_width'])
            save(out/'gate.json',gate)
            polygon=np.array(profile.get('animation_polygon_body',[]),float)
            if len(polygon):polygon=polygon-[bx-px,by-py]
            else:polygon=np.array(gate['jaw_polygon'])*[bw-1,bh-1]
            binary=np.zeros((bh,bw),np.uint8);cv.fillPoly(binary,[np.rint(polygon).astype('int32')],255)
            # Feather INSIDE the facial contour only. No global difference mask.
            distance=cv.distanceTransform(binary,cv.DIST_L2,5)
            alpha=np.clip(distance/2.,0,1)*255
            content=np.zeros_like(binary);content[py:py+ch,px:px+cw]=1
            cv.imwrite(str(mask),(alpha*content).astype('uint8'))
        stage('matte',matte,[mask,out/'gate.json'])
        final=out/'animation.mp4'
        def render():
            temp=out/'animation.partial.mp4'
            command('render',backend+['render','--registration',registration,'--mask',mask,'--audio',audio,
                '--output',temp,'--overwrite','--preview-dir',out/'frames','--encoder','x264'])
            data=probe(temp);v=next(s for s in data['streams'] if s['codec_type']=='video')
            duration=float(v['duration']);ad=float(probe(audio)['format']['duration'])
            if abs(duration-ad)>.5:raise ValueError('Audio/video durations differ by more than 0.5s; check cached face.mp4')
            temp.replace(final)
        stage('render',render,[final])
        preview=out/'preview.mp4'
        stage('preview',lambda:command('preview',['ffmpeg','-v','error','-y','-i',final,'-t',12,
            '-c','copy','-movflags','+faststart',preview]),[preview])
        save(out/'result.json',{'status':'completed','output':str(final),'preview':str(preview),
            'registration_quality':read(registration)['quality'],
            'motion_scope':'audio-driven face; original arms, torso and legs retained',
            'inputs':inputs,'output_probe':probe(final)})
        print('COMPLETE:',final,flush=True)
    finally:lock.unlink(missing_ok=True)

if __name__=='__main__':
    try:main()
    except KeyboardInterrupt:print('Interrupted; completed stages can be resumed.',file=sys.stderr);sys.exit(130)
    except Exception as e:print('ERROR:',e,file=sys.stderr);sys.exit(1)
