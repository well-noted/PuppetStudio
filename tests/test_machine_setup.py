import io,json,os,sys,tempfile,unittest,zipfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'engine/backend'))
from studio.machine_setup import download,unzip,inventory,discover,install,shared_paths,inherit_tools,remember_verified,nearby_checkouts,repos
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
   with patch('studio.machine_setup.home',return_value=root/'tools'),patch('discover_sadtalker.candidates',return_value=([],[])),patch('studio.diagnostics.check',return_value=good):
    self.assertTrue(discover(root,lambda _:None)['found'])
   self.assertEqual(load(root)['settings']['sadtalker_repo'],str(repo))
 def test_install_rejects_unsupported_platform_before_mutation(self):
  if os.name!='nt':
   with self.assertRaisesRegex(ValueError,'Windows x64'):install('/tmp/unused')

 def test_home_nested_checkout_discovery_and_limits(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);repo=root/'Other project/LivePortrait/SadTalker';repo.mkdir(parents=True);(repo/'inference.py').touch()
   self.assertEqual(nearby_checkouts(root),[repo.resolve()]);self.assertEqual(nearby_checkouts(root,max_depth=2),[]);self.assertEqual(nearby_checkouts(root,max_directories=1),[])
   hidden=root/'AppData/SadTalker';hidden.mkdir(parents=True);(hidden/'inference.py').touch()
   with patch('studio.machine_setup.Path.home',return_value=root),patch('studio.machine_setup.home',return_value=root/'tools'):
    self.assertIn(repo.resolve(),repos(root/'studio/projects/demo',new()['settings']))
   self.assertNotIn(hidden.resolve(),nearby_checkouts(root))
 def test_empty_discovery_writes_current_failure_report(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);store(root,new());save=root/'work/setup_report.json';save.parent.mkdir();save.write_text('{"old":true}')
   with patch('studio.machine_setup.repos',return_value=[]):result=discover(root,lambda _:None)
   self.assertFalse(result['found']);report=json.loads(save.read_text());self.assertNotIn('old',report);self.assertEqual(report['checks'][0]['name'],'Animation discovery');self.assertEqual(report['discovery']['checkouts'],[])

 def test_windows_venv_python_candidates(self):
  from discover_sadtalker import candidates
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);repo=root/'SadTalker';repo.mkdir();python=repo/'.venv/Scripts/python.exe';python.parent.mkdir(parents=True);python.touch();alias=root/'Local/Microsoft/WindowsApps/python.exe';alias.parent.mkdir(parents=True);alias.touch()
   with patch.dict(os.environ,{'LOCALAPPDATA':str(root/'Local')},clear=True),patch('discover_sadtalker.Path.home',return_value=root),patch('discover_sadtalker.shutil.which',return_value=None):found,_=candidates(repo,root)
   self.assertIn(python.resolve(),found);self.assertIn(alias.resolve(),found)

class ReuseTests(unittest.TestCase):
 def test_verified_paths_inherited_without_installing(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);repo=root/'repo';repo.mkdir();(repo/'inference.py').touch();python=root/'python.exe';python.touch();cfg={'sadtalker_repo':str(repo),'sadtalker_python':str(python)};report={'checks':[{'name':'CUDA import test','status':'ok'},{'name':'SadTalker startup','status':'ok'}]}
   with patch('studio.machine_setup.home',return_value=root/'tools'):
    self.assertTrue(remember_verified(cfg,report));p=inherit_tools(new());self.assertEqual(p['settings']['sadtalker_python'],str(python))
    p['settings']['sadtalker_python']='custom.exe';inherit_tools(p);self.assertEqual(p['settings']['sadtalker_python'],'custom.exe')
    python.unlink();self.assertEqual(shared_paths(),{})
 def test_failed_probe_never_marks_tools_verified(self):
  with tempfile.TemporaryDirectory() as d,patch('studio.machine_setup.home',return_value=Path(d)/'tools'):
   self.assertFalse(remember_verified({}, {'checks':[{'name':'CUDA import test','status':'ok'},{'name':'SadTalker startup','status':'error'}]}));self.assertFalse((Path(d)/'tools/verified_animation.json').exists())
