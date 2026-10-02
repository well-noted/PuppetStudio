import sys,tempfile,unittest
from pathlib import Path
import numpy as np
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from studio.gesture_prepare import composite,region_mask,prepare
from studio.core import new,store,action,read,digest
class GestureTests(unittest.TestCase):
 def test_preserves_protected_rgba_exactly(self):
  a=np.zeros((100,100,4),dtype=np.uint8);a[10:90,30:60]=[80,140,60,255];b=a.copy();b[:]=[200,100,50,255]
  out,report=composite(Image.fromarray(a),Image.fromarray(b),feather=4)
  result=np.asarray(out);gate=region_mask((100,100),feather=4)
  self.assertTrue(np.array_equal(result[gate==0],a[gate==0]));self.assertEqual(report['protected_changed_pixels'],0)
  self.assertEqual(result[0,0,3],0);self.assertEqual(result[45,45,3],255)
 def test_bad_geometry_rejected(self):
  a=Image.new('RGBA',(100,100));b=Image.new('RGBA',(99,100))
  with self.assertRaisesRegex(ValueError,'no automatic resizing'):composite(a,b)
  for region in [[0,.25,.95,.66],[.08,.2,.95,.66],[.5,.25,.4,.66],[.08,float('nan'),.95,.66]]:
   with self.assertRaises(ValueError):region_mask((100,100),region)
 def test_mask_protects_torso_and_no_dark_alpha_fringe(self):
  a=Image.new('RGBA',(100,100),(0,0,0,0));b=Image.new('RGBA',(100,100),(240,140,70,255));mask=Image.new('L',(100,100),0)
  mask.putpixel((50,50),128);out,report=composite(a,b,feather=0,mask=mask);self.assertEqual(out.getpixel((50,50)),(240,140,70,128));self.assertEqual(out.getpixel((49,50)),(0,0,0,0))
 def test_prepared_draft_imports_and_master_hash_guard(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);store(root,new());action(root,'add-speaker',{'name':'Test'})
   neutral=root/'neutral.png';pose=root/'pose.png';Image.new('RGB',(200,300),(80,130,60)).save(neutral);Image.new('RGB',(200,300),(180,80,40)).save(pose)
   action(root,'import-asset',{'speaker':'test','kind':'neutral','path':str(neutral)});p=read(root/'project.json');before=digest(root/p['speakers'][0]['asset'])
   action(root,'prepare-gesture',{'speaker':'test','pose':'palm','path':str(pose)});p=read(root/'project.json');draft=p['speakers'][0]['asset_drafts'][0]
   self.assertEqual(draft['preparation']['protected_changed_pixels'],0)
   action(root,'import-asset-draft',{'speaker':'test','path':draft['path']});self.assertEqual(before,digest(root/p['speakers'][0]['asset']))
   Image.new('RGB',(200,300),'blue').save(root/p['speakers'][0]['asset'])
   with self.assertRaisesRegex(ValueError,'older artwork'):action(root,'import-asset-draft',{'speaker':'test','path':draft['path']})
 def test_extended_hand_in_fixed_render_bounds(self):
  from studio.core import actor,uri
  from studio_puppet import StudioPuppet
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);neutral=root/'n.png';pose=root/'p.png';a=np.full((300,200,3),255,dtype=np.uint8);a[20:280,80:120]=[40,80,120];b=a.copy();b[100:140,120:185]=[40,80,120];Image.fromarray(a).save(neutral);Image.fromarray(b).save(pose)
   stage=actor({'id':'p','name':'Test','title':''});stage['asset']={'neutral_data':uri(neutral),'poses':[{'id':'palm','image_data':uri(pose)}]};puppet=StudioPuppet(stage)
   self.assertGreaterEqual(puppet.content_bounds()[2],185);before=puppet.content_bounds();puppet.frame(1,[{'start':0,'end':2,'pose':'palm'}]);self.assertEqual(puppet.content_bounds(),before)
