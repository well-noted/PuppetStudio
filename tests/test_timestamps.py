from pathlib import Path
import sys
import unittest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from studio.timestamps import normalize

class TimestampTests(unittest.TestCase):
    def test_instantaneous_words_keep_text_without_extending_speech(self):
        t=normalize({'segments':[{'start':0,'end':1,'text':'Hello there friend.'}],'words':[
            {'start':0,'end':0,'word':'Hello'},
            {'start':0,'end':.5,'word':'there'},
            {'start':.5,'end':1,'word':'friend.'}]},2)
        self.assertEqual(' '.join(w['word'] for w in t['words']),'Hello there friend.')
        self.assertEqual(t['words'][0]['start'],0);self.assertEqual(t['words'][-1]['end'],1)
        self.assertTrue(all(w['start']<w['end'] for w in t['words']))
    def test_untimed_words_fall_back_to_original_segment_text(self):
        t=normalize({'segments':[{'start':1,'end':2,'text':'Actual sentence.'}],'words':[{'start':1,'end':1,'word':'Actual sentence.'}]},3)
        self.assertEqual(t['words'],[]);self.assertEqual(t['segments'][0]['text'],'Actual sentence.');self.assertTrue(t['warnings'])
    def test_zero_segment_text_is_preserved_at_adjacent_source_time(self):
        t=normalize({'segments':[{'start':0,'end':0,'text':'Hello'},{'start':0,'end':1,'text':'there.'}]},2)
        self.assertEqual(t['segments'],[{'start':0,'end':1,'text':'Hello there.'}])
        self.assertTrue(t['warnings'])
    def test_small_end_rounding_is_clamped(self):
        t=normalize({'segments':[{'start':4,'end':5.02,'text':'End.'}]},5)
        self.assertEqual(t['segments'][0]['end'],5);self.assertTrue(t['warnings'])
    def test_large_overrun_identifies_interval_and_media_duration(self):
        with self.assertRaisesRegex(ValueError,r'segments\[0\].*end=10.0.*duration=5.000'):
            normalize({'segments':[{'start':2,'end':10,'text':'Invalid.'}]},5)
    def test_nonfinite_and_reversed_timing_are_rejected(self):
        for start,end in [(float('nan'),2),(3,2)]:
            with self.assertRaises(ValueError):normalize({'segments':[{'start':start,'end':end,'text':'Invalid.'}]},5)
    def test_source_order_is_not_silently_sorted(self):
        with self.assertRaisesRegex(ValueError,r'segments\[1\]'):
            normalize({'segments':[{'start':3,'end':4,'text':'First.'},{'start':1,'end':2,'text':'Second.'}]},5)

if __name__=='__main__':unittest.main()
