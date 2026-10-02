import sys,unittest
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'renderer'))
from cache import Actor,decode,lower_face_alpha

class UpperFaceTests(unittest.TestCase):
 def test_full_face_cache_protects_upper_art_and_retains_mouth(self):
  profile={'nose_y_body':45.,'mouth_box_body':[40.,70.,20.,10.]};box=[20,20,60,60]
  alpha=lower_face_alpha(np.ones((60,60,1),np.float32),profile,box)
  self.assertEqual(alpha[:26].max(),0);self.assertTrue(np.all(alpha[50:]==1))
  self.assertTrue(np.all(np.diff(alpha[:,0,0])>=0));self.assertTrue(np.any((alpha>0)&(alpha<1)))
  actor=Actor.__new__(Actor);actor.profile=profile;actor.box=box;actor.alpha=alpha
  actor.body=np.full((100,100,3),120,np.uint8);actor.master=actor.body.copy();actor.reference=actor.body[20:80,20:80].copy();actor.linear=decode(actor.reference)
  actor.matrix=np.array([[1,0,0],[0,1,0]],np.float32);actor.bias=np.zeros(3);actor.fps=25;actor.count=25;actor.duration=1
  neural=np.full((60,60,3),[200,80,50],np.uint8);actor.sample=lambda _:neural
  result=actor.frame(0,calm=False)
  self.assertTrue(np.array_equal(result[:46],actor.master[:46]));self.assertTrue(np.array_equal(result[70,50],neural[50,30]))
 def test_existing_lower_mask_is_never_expanded(self):
  profile={'nose_y_body':25.,'mouth_box_body':[30.,40.,20.,10.]};alpha=np.zeros((60,60,1),np.float32);alpha[40:50,20:40]=.6
  guarded=lower_face_alpha(alpha,profile,[0,0,60,60]);self.assertTrue(np.all(guarded<=alpha));self.assertTrue(np.array_equal(guarded[40:50],alpha[40:50]))
