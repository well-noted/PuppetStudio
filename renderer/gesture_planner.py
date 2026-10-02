"""Repeatable phrase/time scheduling, restricted to captioned speaking intervals."""
import hashlib,random,re
DEFAULT_PHRASES=['important','fundamental','principle','so i think','in other words','question','for example']
def plan(actor,cues,duration,interval,available):
 g=actor['gestures'];mode=g['mode']
 if mode=='off' or not available:return []
 if mode=='manual':return [{**c,'strength':1} for c in g['cues'] if c['start']<duration]
 rng=random.Random(int(g['seed'])+int(hashlib.sha256((actor['id']+str(cues)).encode()).hexdigest()[:8],16));windows=[]
 for c in cues:
  start=max(0,float(c['start']));end=min(duration,float(c['end']))
  if end-start<.8:continue
  if windows and start-windows[-1][1]<=.25:windows[-1][1]=max(end,windows[-1][1])
  else:windows.append([start,end])
 candidates=[]
 if mode in ['phrases','hybrid','auto']:
  phrases=[p.strip().lower() for p in g['phrases'] if p.strip()]
  for c in cues:
   if c['start']>=3 and c['end']-c['start']>=.8 and any(p in c['text'].lower() for p in phrases):candidates.append((c['start'],0))
 if mode in ['timed','hybrid']:
  t=rng.uniform(g['interval_min'],g['interval_max'])
  while t<duration:
   window=next(([a,b] for a,b in windows if b>=t+.8),None)
   if window is None:break
   t=max(t,window[0]);candidates.append((t,1));t+=rng.uniform(g['interval_min'],g['interval_max'])
 result=[];last=-interval;last_pose=None
 for t,kind in sorted(candidates):
  if t-last<interval or rng.random()>g['probability']:continue
  window=next(([a,b] for a,b in windows if a<=t<b-.5),None)
  if not window:continue
  hold=min(rng.uniform(g['duration_min'],g['duration_max']),window[1]-t,duration-t)
  if hold<.8:continue
  choices=[p for p in available if p!=last_pose] or available;pose=rng.choice(choices);last_pose=pose;last=t
  result.append({'start':t,'end':t+hold,'pose':pose,'strength':1,'reason':'phrase' if kind==0 else 'timed'})
 return result
