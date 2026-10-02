import json,os,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from studio.core import provider,multipart
class Response:
 def __enter__(self):return self
 def __exit__(self,*a):pass
 def read(self):return b'{"ok":true}'
class ProviderTests(unittest.TestCase):
 def test_key_only_in_auth_header(self):
  cfg={'key_env':'STUDIO_TEST_KEY','api_base':'https://provider.example/v1'}
  with patch.dict(os.environ,{'STUDIO_TEST_KEY':'secret'}),patch('urllib.request.urlopen',return_value=Response()) as mock:
   self.assertTrue(provider(cfg,'chat/completions',b'{"model":"test"}')['ok']);req=mock.call_args[0][0];self.assertEqual(req.get_header('Authorization'),'Bearer secret');self.assertNotIn(b'secret',req.data);self.assertNotIn('secret',req.full_url)
 def test_missing_key_blocks_request(self):
  with patch.dict(os.environ,{},clear=True),patch('urllib.request.urlopen') as mock:
   with self.assertRaises(ValueError):provider({'key_env':'MISSING','api_base':'https://example.test'},'images/edits',b'{}')
   mock.assert_not_called()
 def test_multipart_includes_actual_file_and_fields(self):
  with tempfile.TemporaryDirectory() as d:
   f=Path(d)/'test.png';f.write_bytes(b'PNGDATA');body,kind=multipart([('model','test')],f,'image');self.assertIn(b'PNGDATA',body);self.assertIn(b'name="image"',body);self.assertTrue(kind.startswith('multipart/form-data'))
if __name__=='__main__':unittest.main()
