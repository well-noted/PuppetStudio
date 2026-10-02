import sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from studio.core import save,digest,new,store,load,action
from studio.asset_drafts import generate,breath_proposal
class DraftTests(unittest.TestCase):
 def test_local_proposals_never_call_provider_or_change_master(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);folder=root/'assets/person';folder.mkdir(parents=True)
   im=Image.new('RGB',(200,400),(230,210,190));im.save(folder/'character.png')
   profile={'bust':[40,0,110,140],'mouth_box_body':[80,70,30,20],'jaw_y_body':110}
   save(folder/'profile.json',profile);speaker={'id':'person','asset':'assets/person/character.png','profile':'assets/person/profile.json','approved':True};before=digest(folder/'character.png')
   with patch('studio.asset_drafts.provider',side_effect=AssertionError('Unexpected API call')):
    outputs=[generate(root,speaker,{}, {'kind':k,'method':'local'}) for k in ['breath','closed','inference-bust']]
   self.assertEqual(digest(folder/'character.png'),before)
   with Image.open(root/outputs[2]['path']) as bust:self.assertEqual(bust.size,(140,140))
   mask=np.array(Image.open(root/outputs[0]['path']));self.assertEqual(mask[:120].max(),0);self.assertEqual(mask[240:].max(),0);self.assertGreater(mask.max(),0)
   closed=np.array(Image.open(root/outputs[1]['path']));self.assertTrue(np.array_equal(closed[:50],np.array(im)[:50]))
   self.assertEqual(outputs[0]['source_sha256'],before)
 def test_gesture_requires_description(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);Image.new('RGB',(100,100)).save(root/'master.png')
   with self.assertRaisesRegex(ValueError,'Describe'):
    generate(root,{'id':'p','asset':'master.png'},{},{'kind':'pose','pose':'palm'})

 def test_breath_draft_import_and_missing_draft_error(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);store(root,new());action(root,'add-speaker',{'name':'Person'})
   neutral=root/'neutral.png';Image.new('RGB',(200,400),(80,130,70)).save(neutral)
   action(root,'import-asset',{'speaker':'person','kind':'neutral','path':str(neutral)})
   p=load(root);speaker=p['speakers'][0];folder=root/'assets/person'
   save(folder/'profile.json',{'bust':[40,0,110,140],'mouth_box_body':[80,70,30,20],'jaw_y_body':110})
   speaker.update(profile='assets/person/profile.json',approved=True);store(root,p)
   action(root,'generate-asset',{'speaker':'person','kind':'breath','method':'local'},lambda _:None)
   p=load(root);draft=p['speakers'][0]['asset_drafts'][0];expected=np.array(Image.open(root/draft['path']))
   # Accept separators in either form, but resolve the stored canonical path.
   action(root,'import-asset-draft',{'speaker':'person','path':draft['path'].replace('/','\\')})
   p=load(root);mask=Image.open(root/p['speakers'][0]['breath']);self.assertEqual(mask.mode,'L');self.assertTrue(np.array_equal(expected,np.array(mask)))
   with self.assertRaisesRegex(ValueError,'Draft not found'):
    action(root,'import-asset-draft',{'speaker':'person','path':'missing.png'})
 def test_reserved_gesture_cannot_overwrite_neutral(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);store(root,new());action(root,'add-speaker',{'name':'Person'})
   neutral=root/'neutral.png';Image.new('RGB',(200,400),(80,130,70)).save(neutral)
   action(root,'import-asset',{'speaker':'person','kind':'neutral','path':str(neutral)});master=root/load(root)['speakers'][0]['asset'];before=digest(master)
   with self.assertRaisesRegex(ValueError,'reserved'):
    action(root,'import-asset',{'speaker':'person','kind':'pose','pose':'character','path':str(neutral)})
   self.assertEqual(digest(master),before)

 def test_render_reports_missing_input_separately(self):
  from studio.queue import preflight
  p=new()
  with self.assertRaisesRegex(ValueError,'no recording reference'):preflight(Path('.'),p,[])
  p['media']={'path':'media/source.m4a','duration':30,'video':False}
  with self.assertRaisesRegex(ValueError,'no transcript reference'):preflight(Path('.'),p,[])
