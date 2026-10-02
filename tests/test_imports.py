from pathlib import Path
import sys
import tempfile
import unittest
from PIL import Image
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from studio.core import new,store,load,action,save

class ImportTests(unittest.TestCase):
    def test_unchanged_rgb_png_keeps_original_bytes_and_profile_identity(self):
        import hashlib
        from PIL.PngImagePlugin import PngInfo
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);store(root,new());action(root,'add-speaker',{'name':'Person','title':'Role'})
            src=root/'original.png';meta=PngInfo();meta.add_text('Source','Approved master')
            Image.new('RGB',(200,300),'black').save(src,pnginfo=meta,compress_level=1)
            original=src.read_bytes()
            profile=root/'original_profile.json';save(profile,{'source_sha256':hashlib.sha256(original).hexdigest(),'bust':[20,20,100,100],'mouth_box_body':[50,70,20,10],'nose_y_body':60,'jaw_y_body':100})
            action(root,'import-asset',{'speaker':'person','kind':'neutral','path':str(src)})
            self.assertEqual((root/'assets/person/character.png').read_bytes(),original)
            action(root,'import-asset',{'speaker':'person','kind':'profile','path':str(profile)})
            action(root,'approve',{'speaker':'person'});self.assertTrue(load(root)['speakers'][0]['approved'])
    def test_blank_replacement_keeps_existing_art_and_review(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);p=new();p['speakers']=[{'id':'person','name':'Person','title':'Role','asset':'assets/person/character.png','profile':None,'approved':True,'poses':[],'reference':None}];store(root,p)
            old=root/'assets/person/character.png';old.parent.mkdir(parents=True);Image.new('RGB',(20,20),'black').save(old);original=old.read_bytes()
            blank=root/'blank.png';Image.new('RGB',(20,20),'white').save(blank)
            with self.assertRaisesRegex(ValueError,'blank'):action(root,'import-asset',{'speaker':'person','kind':'neutral','path':str(blank)})
            self.assertEqual(old.read_bytes(),original);self.assertTrue(load(root)['speakers'][0]['approved'])
    def test_impossible_anatomy_cannot_be_approved(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);p=new();p['speakers']=[{'id':'person','name':'Person','title':'Role','asset':'assets/person/character.png','profile':'assets/person/profile.json','approved':False,'poses':[],'reference':None}];store(root,p)
            art=root/'assets/person/character.png';art.parent.mkdir(parents=True);Image.new('RGB',(200,300),'black').save(art)
            save(root/'assets/person/profile.json',{'bust':[20,20,100,100],'mouth_box_body':[150,150,20,20],'nose_y_body':40,'jaw_y_body':110})
            with self.assertRaisesRegex(ValueError,'Implausible'):action(root,'approve',{'speaker':'person'})
            self.assertFalse(load(root)['speakers'][0]['approved'])

if __name__=='__main__':unittest.main()
