import base64,io,sys,unittest
from pathlib import Path
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from studio.core import actor
from scene import default_scene,validate
from render_stage import actor_schedule
class ManualCueTests(unittest.TestCase):
 def scene(self):
  b=io.BytesIO();Image.new('RGB',(20,30),(80,120,90)).save(b,format='PNG');png='data:image/png;base64,'+base64.b64encode(b.getvalue()).decode()
  a=actor({'id':'person','name':'Person','title':''});a['asset']={'neutral_data':png,'poses':[{'id':'explain','image_data':png}]};a['gestures']['mode']='manual';s=default_scene();s['actors']=[a];return s,a
 def test_clip_scoping_and_legacy_global_cues(self):
  s,a=self.scene();a['gestures']['cues']=[{'start':3,'end':6,'pose':'explain','clip':'one'},{'start':3,'end':5,'pose':'explain','clip':'two'},{'start':12,'end':14,'pose':'explain'}];validate(s)
  for clip,end in [('one',6),('two',5)]:
   scheduled=actor_schedule(a,[],20,40,clip_id=clip);self.assertEqual(len(scheduled),2);self.assertEqual(scheduled[0]['end'],end);self.assertNotIn('clip',scheduled[1])
  self.assertEqual(len(actor_schedule(a,[],20,40)),1);self.assertEqual(len(a['gestures']['cues']),3)
 def test_same_clip_and_global_overlaps_rejected(self):
  for scope in ['one',None]:
   s,a=self.scene();a['gestures']['cues']=[{'start':3,'end':6,'pose':'explain','clip':'one'},{'start':4,'end':7,'pose':'explain',**({'clip':scope} if scope else {})}]
   with self.assertRaisesRegex(ValueError,'overlap'):validate(s)
 def test_invalid_clip_id_rejected(self):
  s,a=self.scene();a['gestures']['cues']=[{'start':1,'end':2,'pose':'explain','clip':'../bad'}]
  with self.assertRaisesRegex(ValueError,'clip ID'):validate(s)
