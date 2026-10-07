import unittest
from daily import label, signals, parse


class DailyTest(unittest.TestCase):
    def test_euc_kr_xml(self):
        xml = '<?xml version="1.0" encoding="EUC-KR"?><root name="효성"><item data="20261006|100|105|99|100|5"/></root>'
        self.assertEqual(parse(xml.encode('euc-kr'))[0]['high'], 105)

    def test_shape_does_not_require_three_or_five_percent(self):
        x = label(dict(open=100, high=102, low=99.8, close=100.1), 100)
        self.assertTrue(x['upper_wick_event'])
        self.assertFalse(x['broad_reversal'])

    def test_open_at_high_red_body_is_not_upper_wick(self):
        x = label(dict(open=106, high=106, low=99, close=100), 100)
        self.assertTrue(x['broad_reversal'])
        self.assertFalse(x['upper_wick_event'])

    def test_no_range_is_not_a_wick(self):
        self.assertFalse(label(dict(open=100, high=100, low=100, close=100),100)['upper_wick_event'])

    def test_signal_does_not_see_target_bar(self):
        rows = [dict(open=100+i, high=101+i, low=99+i, close=100+i, volume=100+i) for i in range(23)]
        original = signals(rows[:22])
        rows[22] = dict(open=500, high=999, low=10, close=20, volume=999999)
        self.assertEqual(signals(rows[:22]), original)

    def test_bad_prior_volume_blocks_signal(self):
        rows = [dict(open=100, high=101, low=99, close=100, volume=100) for _ in range(21)]
        rows[-1]['volume'] = 0
        self.assertIsNone(signals(rows))

    def test_reject_minute_as_daily(self):
        with self.assertRaises(ValueError):
            parse('<root><item data="202610071001|100|101|99|100|5"/></root>')


if __name__ == '__main__':
    unittest.main()
