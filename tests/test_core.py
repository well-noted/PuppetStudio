import copy,io,json,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'renderer')]
from unittest.mock import patch
from studio.core import new,validate,path,normalize,captions,actor,read
from studio.queue import cuts,profile_check
from gesture_planner import plan
from matte import cutout_rgba
import numpy as np
class CoreTests(unittest.TestCase):
 def test_model_paths_accept_matching_quotes_and_keep_internal_spaces(self):
  for quote in ['"',"'"]:
   p=new();repo=r'C:\Users\Person\Global Futures Panel\SadTalker';python=r'C:\Users\Person\Python Env\python.exe'
   p['settings']['sadtalker_repo']=' '+quote+repo+quote+' '
   p['settings']['sadtalker_python']=quote+python+quote
   result=validate(p)
   self.assertEqual(result['settings']['sadtalker_repo'],repo)
   self.assertEqual(result['settings']['sadtalker_python'],python)
 def test_paths_cannot_escape(self):
  for value in ['../secret','/tmp/secret']:
   with self.assertRaises(ValueError):path('/tmp/project',value)
 def test_keys_are_not_saved(self):
  p=new();p['settings']['api_key']='secret'
  with self.assertRaisesRegex(ValueError,'credentials'):validate(p)
 def test_timestamp_rejects_out_of_source(self):
  with self.assertRaises(ValueError):normalize({'segments':[{'start':2,'end':10,'text':'bad'}]},5)
 def test_range_errors_include_value_and_range(self):
  p=new();p['settings']['expression_scale']=3
  with self.assertRaisesRegex(ValueError,'entered 3; supported range 0.5–2'):validate(p)
 def test_scene_ranges_checked_on_save(self):
  p=new();s={'id':'person','name':'Person','title':'Role','poses':[]};p['speakers']=[s];scene=read(ROOT/'scene_default.json');a=actor(s);a['height']=999;scene['actors']=[a];p['productions']=[{'id':'solo','name':'Solo','clips':[],'scene':scene,'intro_mode':'none','output':'both'}]
  with self.assertRaisesRegex(ValueError,'999.*100–720'):validate(p)
 def test_captions_preserve_source_words(self):
  t=normalize({'words':[{'start':0,'end':.5,'word':'Hello'},{'start':.6,'end':1,'word':'world.'}]},2);c=captions(t,0,2);self.assertEqual(c[0]['text'],'Hello world.')
 def test_chunks_are_contiguous_and_end_exactly(self):
  c=cuts(10,223,[],75);self.assertEqual(c,[10,85,160,223]);self.assertTrue(all(b>a for a,b in zip(c,c[1:])))
 def test_gestures_repeatable_inside_speech(self):
  a={'id':'test','gestures':{'mode':'timed','seed':42,'probability':1,'interval_min':8,'interval_max':12,'duration_min':1,'duration_max':2,'phrases':[],'cues':[]}};cues=[{'start':20,'end':50,'text':'speech'}];x=plan(a,cues,60,5,['palm','point']);self.assertTrue(x);self.assertEqual(x,plan(a,cues,60,5,['palm','point']));self.assertTrue(all(20<=g['start']<g['end']<=50 for g in x))
 def test_white_clothing_preserved_and_edge_unmatted(self):
  a=np.full((60,60,3),255,np.uint8);a[10:50,10:50]=[30,40,50];a[20:40,20:40]=255;a[10:50,9]=220;a[2,2]=100;rgba=cutout_rgba(a);self.assertEqual(rgba[30,30,3],255);self.assertEqual(rgba[2,2,3],0);self.assertLess(rgba[30,9,3],255);self.assertLess(int(rgba[30,9,:3].max()),100)
 def test_no_breath_mask_does_not_move_chair(self):
  from motion import breathe
  a=np.zeros((30,20,3),np.uint8);p=type('P',(),{'breath_mask':None})();self.assertTrue(np.array_equal(breathe(a,p,1,2,300),a))
if __name__=='__main__':unittest.main()
