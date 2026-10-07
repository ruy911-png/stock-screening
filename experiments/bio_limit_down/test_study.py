import unittest
from study import estimated_lower,is_candidate,events_for,summarize


class StudyTests(unittest.TestCase):
    def test_peptron_tick_limit(self):
        self.assertEqual(estimated_lower(130600,'2026-10-07'),91500)

    def test_touch_and_recovery_is_not_closing_candidate(self):
        prev=dict(open=100,high=100,low=100,close=100,volume=1)
        row=dict(open=100,high=100,low=70,close=90,volume=1)
        self.assertFalse(is_candidate(prev,row))

    def test_next_session_halt_is_not_skipped(self):
        rows=[dict(date='2026-10-01',open=100,high=100,low=100,close=100,volume=1),
              dict(date='2026-10-02',open=80,high=80,low=70,close=70,volume=1),
              dict(date='2026-10-06',open=0,high=0,low=0,close=70,volume=0),
              dict(date='2026-10-07',open=75,high=90,low=75,close=90,volume=10)]
        e=events_for('087010',rows,{'2026-10-02':'2026-10-06'})
        self.assertEqual(len(e),1)
        self.assertFalse(e[0]['outcome_known'])
        self.assertIsNone(summarize(e)['next_close_up_fraction'])


if __name__=='__main__':unittest.main()
