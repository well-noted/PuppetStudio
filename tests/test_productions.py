from pathlib import Path
import sys
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from studio.core import new,store,load,action,save,read

class ProductionTests(unittest.TestCase):
    def test_new_production_retains_complete_ui_settings(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);store(root,new())
            action(root,'add-speaker',{'name':'Speaker','title':'Role'})
            action(root,'add-production',{'name':'Solo'})
            p=read(root/'project.json');scene=p['productions'][0]['scene']
            self.assertEqual(scene['audio']['mode'],'off')
            self.assertEqual(scene['actors'][0]['gestures']['mode'],'hybrid')
    def test_existing_production_is_upgraded_without_losing_clip_or_layout(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);store(root,new())
            action(root,'add-speaker',{'name':'Speaker','title':'Role'})
            action(root,'add-production',{'name':'Solo'})
            p=read(root/'project.json');prod=p['productions'][0];prod['scene'].pop('audio')
            prod['scene']['actors'][0]['x']=456
            p['clips']=[{'id':'speech','title':'Speech','start':1,'end':3,'speaker':'speaker','intro':'Context','group':'','reviewed':True}]
            prod['clips']=['speech'];save(root/'project.json',p)
            loaded=load(root)
            self.assertEqual(loaded['productions'][0]['scene']['audio']['mode'],'off')
            self.assertEqual(loaded['productions'][0]['scene']['actors'][0]['x'],456)
            self.assertEqual(loaded['productions'][0]['clips'],['speech'])
            self.assertTrue(loaded['clips'][0]['reviewed'])
            store(root,loaded);self.assertIn('audio',read(root/'project.json')['productions'][0]['scene'])

if __name__=='__main__':unittest.main()
