import io,json,os,sys,tempfile,unittest,zipfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'engine/backend'))
from studio.machine_setup import download,unzip,inventory,discover,install
from studio.core import new,store,load
class Response(io.BytesIO):
 def __init__(self,data):super().__init__(data);self.headers={'Content-Length':str(len(data))}
class MachineTests(unittest.TestCase):
 def test_download_receipt_reuses_only_identical_bytes(self):
  with tempfile.TemporaryDirectory() as d:
   dest=Path(d)/'tool.zip'
   with patch('studio.machine_setup.urllib.request.urlopen',side_effect=lambda *a,**k:Response(b'contents')) as get:
    download('https://example.test/tool',dest,lambda _:None);download('https://example.test/tool',dest,lambda _:None);self.assertEqual(get.call_count,1)
    dest.write_bytes(b'changed');download('https://example.test/tool',dest,lambda _:None);self.assertEqual(get.call_count,2)
 def test_archive_rejects_traversal(self):
  with tempfile.TemporaryDirectory() as d:
   archive=Path(d)/'a.zip'
   with zipfile.ZipFile(archive,'w') as z:z.writestr('../escape','bad')
   with self.assertRaisesRegex(ValueError,'Unsafe'):unzip(archive,Path(d)/'out')
   self.assertFalse((Path(d)/'escape').exists())
 def test_inventory_without_gpu_offers_composition(self):
  with patch('studio.machine_setup.shutil.which',return_value=None):
   report=inventory();self.assertEqual(report['suggested_preset'],'composition');self.assertEqual(report['gpus'],[])
 def test_discovery_saves_only_verified_paths(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);repo=root/'SadTalker';repo.mkdir();(repo/'inference.py').touch();python=root/'python.exe';python.touch();p=new();p['settings'].update(sadtalker_repo=str(repo),sadtalker_python=str(python));store(root,p)
   good={'checks':[{'name':'CUDA import test','status':'ok'},{'name':'SadTalker startup','status':'ok'}]}
   with patch('discover_sadtalker.candidates',return_value=([],[])),patch('studio.diagnostics.check',return_value=good):
    self.assertTrue(discover(root,lambda _:None)['found'])
   self.assertEqual(load(root)['settings']['sadtalker_repo'],str(repo))
 def test_install_rejects_unsupported_platform_before_mutation(self):
  if os.name!='nt':
   with self.assertRaisesRegex(ValueError,'Windows x64'):install('/tmp/unused')
