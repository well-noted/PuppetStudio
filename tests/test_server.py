import json,os,re,subprocess,sys,tempfile,time,unittest,urllib.request,urllib.error
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from studio.core import new,store
class ServerTests(unittest.TestCase):
 def test_local_server_auth_save_export_and_path_guard(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);store(root,new());proc=subprocess.Popen([sys.executable,str(ROOT/'studio.py'),'--project',str(root),'studio','--no-browser','--port','40589'],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,env={**os.environ,'LC_ALL':'C','PYTHONCOERCECLOCALE':'0','PYTHONUTF8':'0','PYTHONIOENCODING':'utf-8'})
   try:
    first=proc.stdout.readline().strip();match=re.search(r'http://127.0.0.1:40589/\?token=(\S+)',first);self.assertIsNotNone(match,first);token=match[1];base='http://127.0.0.1:40589'
    def request(route,data=None,origin=None,authorized=True):
     headers={'X-Studio-Token':token if authorized else 'wrong','Content-Type':'application/json'}
     if origin:headers['Origin']=origin
     req=urllib.request.Request(base+route,data=json.dumps(data).encode() if data is not None else None,headers=headers)
     with urllib.request.urlopen(req,timeout=10) as r:return json.loads(r.read())
    req=urllib.request.Request(base+'/',headers={'X-Studio-Token':token})
    with urllib.request.urlopen(req,timeout=10) as response:
     html=response.read().decode('utf-8');self.assertIn(' · ',html);self.assertNotIn('Â·',html)
    self.assertEqual(request('/api/state')['project']['schema'],'puppet-studio-1')
    self.assertIsNone(request('/api/job')['job']);self.assertIn('tools_home',request('/api/machine'))
    original=(root/'project.json').read_text();(root/'project.json').write_text('broken')
    self.assertIsNone(request('/api/job')['job'])
    (root/'project.json').write_text(original)
    for origin,auth in [('http://evil.test',True),(None,False)]:
     with self.assertRaises(urllib.error.HTTPError) as error:request('/api/state',origin=origin,authorized=auth)
     self.assertEqual(error.exception.code,403)
    p=new();p['name']='HTTP saved';request('/api/save',{'project':p});self.assertEqual(json.loads((root/'project.json').read_text())['name'],'HTTP saved');request('/api/action',{'action':'export','args':{}});self.assertTrue((root/'exports/project.json').exists())
    self.assertTrue(request('/api/credential',{'name':'HF_TOKEN','value':'session-test-secret'})['configured'])
    self.assertNotIn('session-test-secret',json.dumps(request('/api/state')))
    request('/api/action',{'action':'export','args':{}})
    self.assertNotIn('session-test-secret',(root/'exports/project.json').read_text())
    with self.assertRaises(urllib.error.HTTPError):request('/api/credential',{'name':'PATH','value':'wrong'})
    self.assertFalse(request('/api/credential',{'name':'HF_TOKEN','value':''})['configured'])
    video=root/'renders/solo/clips/test.mp4';video.parent.mkdir(parents=True);video.write_bytes(b'0123456789')
    self.assertEqual(request('/api/renders')['renders'][0]['path'],'renders/solo/clips/test.mp4')
    req=urllib.request.Request(base+'/files/renders/solo/clips/test.mp4?download=1',headers={'X-Studio-Token':token,'Range':'bytes=2-5'})
    with urllib.request.urlopen(req,timeout=10) as response:
     self.assertEqual(response.status,206);self.assertEqual(response.read(),b'2345');self.assertIn('attachment',response.headers['Content-Disposition'])
    with self.assertRaises(urllib.error.HTTPError):request('/files/%2e%2e/secret')
   finally:proc.terminate();proc.wait(timeout=10);proc.stdout.close()
if __name__=='__main__':unittest.main()
