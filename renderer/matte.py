import cv2 as cv
import numpy as np

def silhouette(rgb):
 blank=np.uint8(np.min(rgb,2)>248);_,labels=cv.connectedComponents(blank,8);border=np.unique(np.r_[labels[0],labels[-1],labels[:,0],labels[:,-1]]);mask=np.uint8(~np.isin(labels,border[border!=0]))
 n,parts,stats,_=cv.connectedComponentsWithStats(mask,8)
 if n>1:
  minimum=max(3,int(stats[1:,cv.CC_STAT_AREA].max()*.000015))
  for k in range(1,n):
   if stats[k,cv.CC_STAT_AREA]<minimum:mask[parts==k]=0
 return mask.astype(np.float32)
def cutout_rgba(rgb,coverage=None):
 alpha=silhouette(rgb) if coverage is None else np.clip(coverage.copy(),0,1);result=rgb.copy();distance=cv.distanceTransform(np.uint8(alpha>.99),cv.DIST_L2,3);edge=(alpha>0)&(distance<2.1)&(np.min(rgb,2)>145);core=np.uint8((alpha>.99)&~edge)
 if np.any(core) and np.any(edge):
  _,nearest=cv.distanceTransformWithLabels(1-core,cv.DIST_L2,5,labelType=cv.DIST_LABEL_PIXEL);colors=rgb[core>0].astype(float);fore=colors[np.clip(nearest[edge]-1,0,len(colors)-1)];obs=rgb[edge].astype(float);delta=255-fore;den=np.sum(delta*delta,1);inferred=np.sum((255-obs)*delta,1)/np.maximum(den,1);valid=(den>600)&(inferred>.03)&(inferred<.99);a=alpha[edge].copy();a[valid]=np.minimum(a[valid],inferred[valid]);alpha[edge]=a;obs[valid]=np.clip((obs[valid]-255*(1-a[valid,None]))/a[valid,None],0,255);result[edge]=np.uint8(np.rint(obs))
 result[alpha<=0]=0;return np.dstack([result,np.uint8(np.rint(alpha*255))])
