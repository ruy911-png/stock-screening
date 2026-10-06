import unittest
import pandas as pd

from per_ticker_models import attach_pooled_scores, ticker_partitions


class TickerIsolationTests(unittest.TestCase):
    def test_model_inputs_are_ticker_isolated_and_time_purged(self):
        def frame(date, end):
            return pd.DataFrame({'ticker':['A','B','A','B'],
                                 'date':pd.to_datetime([date]*4),
                                 'target_date':pd.to_datetime([end]*4)})
        train=frame('2021-12-20','2021-12-28')
        valid=frame('2022-01-03','2022-01-10')
        test=frame('2024-01-02','2024-01-09')
        parts=list(ticker_partitions(train,valid,test))
        self.assertEqual([x[0] for x in parts],['A','B'])
        for name,*frames in parts:
            self.assertTrue(all(set(f.ticker)=={name} for f in frames))
        train['target_date']=pd.Timestamp('2022-01-03')
        with self.assertRaises(AssertionError):list(ticker_partitions(train,valid,test))

    def test_pooled_comparison_joins_by_date_ticker_not_row_order(self):
        test=pd.DataFrame({'ticker':['A','B'], 'date':pd.to_datetime(['2024-01-02']*2),
                           'target':[0.,1.], 'ret5_close_future':[.01,.15]})
        prior=test.copy();prior['score']=[.1,.8]
        joined=attach_pooled_scores(test,prior.iloc[::-1])
        self.assertEqual(joined.pooled_score.tolist(),[.1,.8])
        prior.loc[0,'target']=1.
        with self.assertRaises(ValueError):attach_pooled_scores(test,prior)


if __name__=='__main__':unittest.main()
