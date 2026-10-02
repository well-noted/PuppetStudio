from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import unittest
from unittest.mock import MagicMock,patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from studio.core import new,store,action,read

class TranscriptCacheTests(unittest.TestCase):
    def test_raw_result_survives_validation_failure_and_reuses_only_matching_media(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);media=root/'media/source.wav';media.parent.mkdir();media.write_bytes(b'fixture-a')
            p=new();p['media']={'path':'media/source.wav','duration':5,'video':False};store(root,p)
            model=MagicMock();model.transcribe.return_value=([SimpleNamespace(start=2,end=10,text='Test words.',words=[])],SimpleNamespace(language='en'))
            constructor=MagicMock(return_value=model)
            with patch.dict('sys.modules',{'faster_whisper':SimpleNamespace(WhisperModel=constructor)}),patch('studio.core.subprocess.run'):
                with self.assertRaisesRegex(ValueError,r'segments\[0\]'):action(root,'transcribe',{},log=lambda s:None)
                self.assertTrue((root/'work/transcription_raw.json').exists())
                self.assertTrue((root/'work/transcription_validation_error.json').exists())
                fixed={'segments':[{'start':2,'end':5,'text':'Test words.'}],'words':[],'language':'en'}
                with patch('studio.core.normalize',return_value=fixed):action(root,'transcribe',{},log=lambda s:None)
                self.assertEqual(constructor.call_count,1)
                self.assertEqual(read(root/'transcript/transcript.json'),fixed)
                media.write_bytes(b'fixture-b')
                with self.assertRaises(ValueError):action(root,'transcribe',{},log=lambda s:None)
                self.assertEqual(constructor.call_count,2)

if __name__=='__main__':unittest.main()
