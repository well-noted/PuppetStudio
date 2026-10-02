import io,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from setup_progress import SetupProgress
class ProgressTests(unittest.TestCase):
 def test_reports_elapsed_without_fake_percent(self):
  now=[0];out=io.StringIO();p=SetupProgress(stream=out,clock=lambda:now[0]);p.stage(2,'Installing packages');now[0]=65;p.status();text=out.getvalue();self.assertIn('Step 2/3',text);self.assertIn('elapsed 65s',text);self.assertIn('last output 65s ago',text);self.assertNotIn('%',text)
 def test_preserves_output_and_marks_completed_after_success(self):
  out=io.StringIO();p=SetupProgress(stream=out);p.stage(2,'Install');p.run([sys.executable,'-u','-c',"print('Installing collected packages: example');print('Successfully installed example')"],'Install');p.finish();text=out.getvalue();self.assertIn('Successfully installed example',text);self.assertIn('Setup complete',text)
 def test_failure_is_not_completion(self):
  import subprocess
  out=io.StringIO();p=SetupProgress(stream=out)
  with self.assertRaises(subprocess.CalledProcessError):p.run([sys.executable,'-c',"import sys;print('specific failure');sys.exit(7)"],'Install')
  self.assertIn('specific failure',out.getvalue());self.assertNotIn('Setup complete',out.getvalue())

 def test_quiet_subprocess_updates_tty_activity(self):
  out=io.StringIO();p=SetupProgress(stream=out);p.tty=True;p.stage(2,'Install');p.run([sys.executable,'-c',"import time;time.sleep(1.2)"],'Quiet install');self.assertGreaterEqual(p.tick,3);self.assertIn('output',out.getvalue())
