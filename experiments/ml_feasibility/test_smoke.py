import unittest
import numpy as np
import pandas as pd
from smoke import FEATURES, H, features, split_data


class FeatureTests(unittest.TestCase):
    def test_features_labels_and_time_split(self):
        rng = np.random.default_rng(1)
        idx = pd.bdate_range('2014-01-01', '2026-10-02')
        c = pd.Series(100*np.exp(np.cumsum(rng.normal(.0003,.012,len(idx)))),index=idx)
        df = pd.DataFrame({'Close':c,'Open':c*.999,'High':c*1.01,'Low':c*.99,
                           'Volume':rng.integers(10000,50000,len(idx))},index=idx)
        f = features(df,c)
        pd.testing.assert_frame_equal(f[FEATURES].iloc[:1200],
                                      features(df.iloc[:1200],c.iloc[:1200])[FEATURES])
        self.assertEqual(H, 5)
        self.assertTrue(f.target.tail(H).isna().all())
        self.assertAlmostEqual(f.ret5_close_future.iloc[500],c.iloc[505]/c.iloc[500]-1)
        self.assertAlmostEqual(f.max_upside_5d.iloc[500], df.High.iloc[501:506].max()/c.iloc[500]-1)
        self.assertEqual(f.target_date.iloc[500], idx[505])
        f['date'] = f.index
        d = f.dropna(subset=FEATURES+['target','target_date'])
        # Two synthetic symbols only for validation of sample-count guards.
        two = pd.concat([d.assign(ticker='TEST_A'), d.assign(ticker='TEST_B')])
        train, valid, test = split_data(two)
        self.assertLess(train.target_date.max(), valid.date.min())
        self.assertLess(valid.target_date.max(), test.date.min())

    def test_touch_window_boundary_and_missing_prices(self):
        idx = pd.bdate_range('2024-01-01', periods=20)
        base = pd.DataFrame({'Close':100., 'Open':100., 'High':101., 'Low':99.,
                             'Volume':10000.}, index=idx)
        for offset, expected in [(0,0), (1,1), (5,1), (6,0)]:
            with self.subTest(offset=offset):
                df = base.copy()
                df.loc[idx[offset], 'High'] = 110.
                f = features(df, df.Close)
                self.assertEqual(f.target.iloc[0], expected)
                self.assertEqual(f.ret5_close_future.iloc[0], 0)
        df = base.copy()
        df.loc[idx[3], 'High'] = np.nan
        self.assertTrue(np.isnan(features(df, df.Close).target.iloc[0]))
        df = base.copy()
        df.loc[idx[5], 'High'] = 109.999
        self.assertEqual(features(df, df.Close).target.iloc[0], 0)


if __name__ == '__main__':
    unittest.main()
