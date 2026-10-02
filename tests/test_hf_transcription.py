import sys,tempfile,unittest,json,io,os
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from studio.hf_transcription import timed_segments,transcribe,endpoint
from studio.core import new,validate
class HFTests(unittest.TestCase):
 def test_offsets_real_times(self):
  data={'chunks':[{'text':'test','timestamp':[1,2]}]}
  self.assertEqual(timed_segments(data,60,10),[{'start':61,'end':62,'text':'test'}])
 def test_no_invented_timestamps(self):
  for data in [{'error':'provider failure'},{'text':'untimed'},{'chunks':[{'text':'x','timestamp':[0,None]}]}]:
   with self.assertRaises(ValueError):timed_segments(data,0,10)
 def test_silent_response(self):
  self.assertEqual(timed_segments({'text':''},0,10),[])
 def test_old_projects_get_defaults_and_reject_secret(self):
  p=new();validate(p);self.assertEqual(p['settings']['hf_key_env'],'HF_TOKEN')
  p['settings']['token']='secret'
  with self.assertRaises(ValueError):validate(p)
 def test_provider_cache_reuse(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);audio=root/'audio.wav';audio.write_bytes(b'audio');cfg={'hf_key_env':'HF_TEST_TOKEN','hf_model':'openai/whisper-large-v3'};payload={'chunks':[{'text':'test','timestamp':[0,5]}]}
   with patch.dict(os.environ,HF_TEST_TOKEN='test-secret'),patch('studio.hf_transcription.subprocess.run'),patch('studio.hf_transcription.urllib.request.urlopen',side_effect=lambda *a,**k:io.BytesIO(json.dumps(payload).encode())) as request:
    # Mock FFmpeg extraction creates the expected request bytes.
    folder=root/'work/hf_transcription'
    def extract(args,**kw):Path(args[-1]).write_bytes(b'wav')
    with patch('studio.hf_transcription.subprocess.run',side_effect=extract):
     a=transcribe(root,audio,5,cfg,lambda _:None);b=transcribe(root,audio,5,cfg,lambda _:None)
    self.assertEqual(a,b);self.assertEqual(request.call_count,1)
    self.assertNotIn('test-secret',''.join(f.read_text() for f in folder.rglob('*.json')))
