import sys,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from studio.queue import heartbeat

class HeartbeatTests(unittest.TestCase):
 def test_elapsed_quiet_and_stage(self):
  with patch('studio.queue.time.monotonic',return_value=185):
   message=heartbeat('animate.py',0,180,'synthesis')
  self.assertRegex(message,r'^\[\d{2}:\d{2}:\d{2} .+\]')
  self.assertIn('animate.py / synthesis',message)
  self.assertIn('process started 3m 05s ago',message)
  self.assertIn('last worker message 5s ago',message)
