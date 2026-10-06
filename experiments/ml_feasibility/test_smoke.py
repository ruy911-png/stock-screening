import unittest
import numpy as np
import pandas as pd
from smoke import FEATURES, features, split_data


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
        self.assertTrue(f.target.tail(20).isna().all())
        self.assertAlmostEqual(f.ret20_future.iloc[500],c.iloc[520]/c.iloc[500]-1)
        f['date'] = f.index
        d = f.dropna(subset=FEATURES+['target','target_date'])
        # Two synthetic symbols only for validation of sample-count guards.
        two = pd.concat([d.assign(ticker='TEST_A'), d.assign(ticker='TEST_B')])
        train, valid, test = split_data(two)
        self.assertLess(train.target_date.max(), valid.date.min())
        self.assertLess(valid.target_date.max(), test.date.min())


if __name__ == '__main__':
    unittest.main()
