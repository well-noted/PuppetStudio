import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from studio.core import new
from studio.diagnostics import check

class DiagnosticTests(unittest.TestCase):
    def test_missing_tools_are_actionable_and_key_value_is_never_recorded(self):
        with tempfile.TemporaryDirectory() as folder, patch('studio.diagnostics.shutil.which',return_value=None), patch.dict('os.environ',{'STUDIO_API_KEY':'secret_example'}):
            report=check(folder,new())
            serialized=json.dumps(report)
            self.assertNotIn('secret_example',serialized)
            self.assertIn('PATH',serialized)
            self.assertGreater(report['errors'],0)
            self.assertTrue((Path(folder)/'work/setup_report.json').exists())
    def test_selected_environment_failure_preserves_specific_reason(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);repo=root/'SadTalker';repo.mkdir();(repo/'inference.py').touch()
            p=new();p['settings'].update(sadtalker_repo=str(repo),sadtalker_python=sys.executable)
            from subprocess import CompletedProcess
            outcomes=[CompletedProcess([],0,'STUDIO_PROBE='+json.dumps({'cuda':True,'device':'test GPU'})+'\n',''),CompletedProcess([],1,'','AttributeError: numpy VisibleDeprecationWarning')]
            with patch('studio.diagnostics.subprocess.run',side_effect=outcomes) as run:
                report=check(root,p,True)
            self.assertEqual(run.call_args_list[0].args[0][0],sys.executable)
            self.assertIn('VisibleDeprecationWarning',json.dumps(report))
            self.assertGreater(report['errors'],0)
    def test_still_mode_does_not_probe_model_or_change_environment(self):
        with tempfile.TemporaryDirectory() as folder, patch('studio.diagnostics.subprocess.run') as run:
            p=new();p['settings']['backend']='still';check(folder,p,True);run.assert_not_called()
    def test_startup_timeout_keeps_partial_stack_and_identifies_phase(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);repo=root/'SadTalker';repo.mkdir();(repo/'inference.py').touch()
            p=new();p['settings'].update(sadtalker_repo=str(repo),sadtalker_python=sys.executable)
            from subprocess import CompletedProcess,TimeoutExpired
            outcomes=[CompletedProcess([],0,'STUDIO_PROBE={"cuda":true}\n',''),TimeoutExpired([],180,output=b'Starting imports',stderr=b'Current thread:\n  importing face_alignment')]
            progress=[]
            with patch('studio.diagnostics.subprocess.run',side_effect=outcomes) as run:
                report=check(root,p,True,log=progress.append)
            self.assertIn('importing face_alignment',json.dumps(report))
            self.assertIn('Timed out after 180',json.dumps(report))
            self.assertIn('importing face_alignment',(root/'work/startup_probe.log').read_text())
            self.assertEqual(run.call_args_list[1].kwargs['env']['PYTHONIOENCODING'],'utf-8')
            self.assertTrue(any('Checking SadTalker startup' in line for line in progress))
    def test_cuda_timeout_does_not_start_second_probe(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);repo=root/'SadTalker';repo.mkdir();(repo/'inference.py').touch()
            p=new();p['settings'].update(sadtalker_repo=str(repo),sadtalker_python=sys.executable)
            from subprocess import TimeoutExpired
            with patch('studio.diagnostics.subprocess.run',side_effect=TimeoutExpired([],60,stderr=b'Torch import stalled')) as run:
                report=check(root,p,True)
            self.assertEqual(run.call_count,1)
            self.assertIn('Torch import stalled',json.dumps(report))

if __name__=='__main__':unittest.main()
