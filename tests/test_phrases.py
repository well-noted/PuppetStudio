import sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from studio.core import new,store,load,action,actor
from scene import default_scene
class PhraseTests(unittest.TestCase):
 def test_custom_and_empty_phrases_survive_project_save(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);store(root,new());action(root,'add-speaker',{'name':'Person'})
   p=load(root);scene=default_scene();scene['actors']=[actor(p['speakers'][0])];p['productions']=[{'id':'solo','name':'Solo','clips':[],'output':'separate','intro_mode':'none','scene':scene}]
   for phrases in [['A new point','For this reason'],[]]:
    p['productions'][0]['scene']['actors'][0]['gestures']['phrases']=phrases;store(root,p);p=load(root)
    self.assertEqual(p['productions'][0]['scene']['actors'][0]['gestures']['phrases'],phrases)
