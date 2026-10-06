import unittest

import numpy as np
import pandas as pd

from smallcap import assess_candidate, candidate_order, normalize_download, parse_holdings


class SmallcapTests(unittest.TestCase):
    def test_csv_header_filters_and_ticker_normalization(self):
        text = '\ufeffFund Name\nFund Holdings as of,"Oct 02, 2026"\nExtra metadata,foo\n' + (
            'Ticker,Name,Sector,Asset Class,Location\n'
            'MOG A,Moog,Industrials,Equity,United States\n'
            'ABC,Abc,Health Care,Equity,United States\n'
            'BANK,Bank,Financials,Equity,United States\n'
            'CAN,Canada,Industrials,Equity,Canada\n'
            'USD,Cash,Cash and/or Derivatives,Cash,United States\n'
            'ABC,Duplicate,Health Care,Equity,United States\n'
            'Legal footer\n')
        universe, date = parse_holdings(text)
        self.assertEqual(date, 'Oct 02, 2026')
        self.assertEqual(universe.ticker.tolist(), ['ABC', 'MOG-A'])
        self.assertEqual(universe.original_ticker.tolist(), ['ABC', 'MOG A'])

    def test_seed_reproducible_and_input_order_independent(self):
        u = pd.DataFrame({'ticker': [f'NAME{i}' for i in range(40)]})
        a = candidate_order(u)
        self.assertEqual(a, candidate_order(u.iloc[::-1]))
        self.assertEqual(a, candidate_order(u))
        self.assertEqual(set(a), set(u.ticker))
        self.assertNotEqual(a, candidate_order(u, seed=1))

    def test_selection_ignores_future_gaps_and_extreme_returns(self):
        idx = pd.bdate_range('2014-01-01', '2026-10-02')
        x = np.arange(len(idx))
        c = pd.Series(100*np.exp(.0002*x+.01*np.sin(x/11)), index=idx)
        d = pd.DataFrame({'Open': c*.999, 'High': c*1.01, 'Low': c*.99,
                          'Close': c, 'Volume': 10000.}, index=idx)
        original = assess_candidate(d, c)
        changed = d.copy()
        changed.loc['2024-01-02':'2024-02-01'] = np.nan
        changed.loc['2025-01-02', ['Open', 'High', 'Low', 'Close']] *= 4
        modified = assess_candidate(changed, c)
        self.assertTrue(original['eligible'])
        self.assertEqual(original['eligible'], modified['eligible'])
        self.assertEqual(original['coverage']['train'], modified['coverage']['train'])
        self.assertGreater(modified['coverage']['test']['missing_rows'], 0)
        self.assertGreater(len(modified['large_daily_changes']), 0)
        short = d.copy()
        short.loc[:'2021-12-01'] = np.nan
        self.assertFalse(assess_candidate(short, c)['eligible'])

    def test_download_preserves_ticker_multiindex(self):
        dates = pd.bdate_range('2020-01-01', periods=3)
        raw = pd.DataFrame({('Close', 'ABC'): [1., 2., 3.],
                            ('Open', 'ABC'): [1., 2., 3.]}, index=dates)
        normalized = normalize_download(raw, ['ABC'])
        self.assertEqual(normalized['ABC']['Close'].tolist(), [1., 2., 3.])


if __name__ == '__main__':
    unittest.main()
