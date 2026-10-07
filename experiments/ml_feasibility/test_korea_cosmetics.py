"""Boundary checks for Korean daily candles, halted sessions and live labels."""
import unittest
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from korea_cosmetics import build_frame, clean_prices, completed_date, live_partitions, mature_rows, parse_naver_chart


def prices(n=350):
    index = pd.bdate_range('2024-01-01', periods=n)
    close = pd.Series(100 + np.arange(n)*.05 + np.sin(np.arange(n)/4), index=index)
    return pd.DataFrame({'Open':close*.999, 'High':close*1.02,
                         'Low':close*.98, 'Close':close, 'Volume':100000}, index=index)


class KoreanBoundaryTests(unittest.TestCase):
    def test_naver_parser_preserves_missing_date_and_ohlcv_order(self):
        xml = '<protocol><chartdata><item data="20261002|100|111|99|105|12345"/><item data="20261006|105|112|104|110|23456"/></chartdata></protocol>'
        f = parse_naver_chart(xml)
        self.assertEqual(len(f), 2)
        self.assertNotIn(pd.Timestamp('2026-10-05'), f.index)
        self.assertEqual(f.loc['2026-10-06', 'Close'], 110)
        self.assertEqual(f.loc['2026-10-06', 'Volume'], 23456)
        self.assertEqual(f.loc['2026-10-02', 'High'], 111)

    def test_naver_duplicate_dates_fail_instead_of_silent_overwrite(self):
        xml = '<protocol><item data="20261006|100|111|99|105|12345"/><item data="20261006|105|112|104|110|23456"/></protocol>'
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            parse_naver_chart(xml)

    def test_completed_date_uses_korean_close_buffer(self):
        self.assertEqual(str(completed_date(datetime(2026, 10, 7, 0, 30, tzinfo=timezone.utc))), '2026-10-06')
        self.assertEqual(str(completed_date(datetime(2026, 10, 7, 7, 0, tzinfo=timezone.utc))), '2026-10-07')

    def test_latest_feature_row_remains_without_future_label(self):
        d = prices()
        f = build_frame(d, d.Close, 'TEST.KQ')
        self.assertEqual(f.date.max(), d.index.max())
        self.assertTrue(pd.isna(f.iloc[-1].target))
        m = mature_rows(f, d.index[-1])
        self.assertEqual(m.date.max(), d.index[-6])
        self.assertEqual(m.target_date.max(), d.index[-1])

    def test_halted_session_is_a_gap_not_removed_calendar_day(self):
        d = prices()
        d.loc[d.index[330], 'Volume'] = 0
        clean, invalid = clean_prices(d, d.index)
        self.assertTrue(invalid.iloc[330])
        self.assertEqual(len(clean), len(d))
        self.assertTrue(pd.isna(clean.iloc[330].High))
        f = build_frame(clean, d.Close, 'TEST.KQ').set_index('date')
        for index in range(325, 330):
            self.assertTrue(pd.isna(f.loc[d.index[index], 'target']))
        self.assertTrue(pd.notna(f.loc[d.index[324], 'target']))

    def test_live_validation_boundary_purges_overlapping_training_labels(self):
        d = prices(900)
        f = build_frame(d, d.Close, 'TEST.KQ')
        m = mature_rows(f, d.index[-1])
        train, valid = live_partitions(m)
        self.assertEqual(len(valid), 126)
        self.assertGreater(len(train), 252)
        self.assertLess(train.target_date.max(), valid.date.min())
        self.assertEqual(valid.target_date.max(), d.index[-1])


if __name__ == '__main__':
    unittest.main()
