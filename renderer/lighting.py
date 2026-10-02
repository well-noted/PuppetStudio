"""Directional illustration shading and projected alpha-silhouette floor shadows."""
import math
import numpy as np
import cv2 as cv
from PIL import Image,ImageFilter

def shade(sprite,actor,light):
 intensity=light['intensity']
 if not intensity:return sprite
 pixels=np.array(sprite);h,w=pixels.shape[:2];dx=light['x']-actor['x'];dy=light['y']-(actor['y']-actor['height']/2);n=math.hypot(dx,dy) or 1;dx/=n;dy/=n
 ax,ay=w/2+dx*w*.8,h/2+dy*h*.8;vx,vy=-dx*w*1.6,-dy*h*1.6;yy,xx=np.mgrid[:h,:w];u=np.clip(((xx-ax)*vx+(yy-ay)*vy)/max(1,vx*vx+vy*vy),0,1)
 front=intensity*.25*(1-u);back=intensity*.4*u;color=np.array([int(light['color'][i:i+2],16) for i in [1,3,5]])
 pixels[:,:,:3]=np.uint8(np.rint(np.clip(pixels[:,:,:3]*(1-front[:,:,None]-back[:,:,None])+color*front[:,:,None],0,255)))
 return Image.fromarray(pixels)

def cast_shadow(canvas,actor,sprite,light):
 width,height=sprite.size;dx=actor['x']-light['x'];dy=actor['y']-light['y'];n=math.hypot(dx,dy) or 1;dx/=n;dy/=n;vx=dx*light['shadow_length'];vy=20+dy*light['shadow_length']*.35
 # The source top projects away from the light; source feet remain at the floor.
 matrix=np.float32([[.7, -vx/height,actor['x']-.35*width+vx],[0,-vy/height,actor['y']+vy]])
 mask=cv.warpAffine(np.array(sprite.getchannel('A')),matrix,(1280,720),flags=cv.INTER_LINEAR,borderValue=0);alpha=Image.fromarray(np.uint8(np.rint(mask*light['shadow_opacity']))).filter(ImageFilter.GaussianBlur(light['shadow_blur']));layer=Image.new('RGBA',(1280,720));layer.putalpha(alpha);canvas.alpha_composite(layer)
