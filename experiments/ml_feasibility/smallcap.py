"""Fixed-seed sample of current IWM holdings for a small real-data ML check."""
from __future__ import annotations

import csv
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import random
import re

import numpy as np
import pandas as pd

import smoke

HOLDINGS_URL = 'https://www.ishares.com/us/products/239710/ishares-russell-2000-etf/latest-holdings.csv'
SEED = 20261006
MAX_CANDIDATES = 100
SAMPLE_SIZE = 20
MIN_TRAIN_ROWS = 252


def parse_holdings(text):
    """Find the actual CSV header, preserving fund metadata and raw ticker text."""
    lines = text.lstrip('\ufeff').splitlines()
    parsed = list(csv.reader(lines))
    header_index = next((i for i, row in enumerate(parsed)
                         if {'Ticker', 'Sector', 'Asset Class', 'Location'}.issubset(row)), None)
    if header_index is None:
        raise ValueError('IWM CSV header missing: expected Ticker/Sector/Asset Class/Location')
    as_of = next((row[1].strip() for row in parsed[:header_index]
                  if len(row) > 1 and row[0].strip() == 'Fund Holdings as of'), None)
    if not as_of:
        raise ValueError('IWM CSV holdings date missing')
    header = parsed[header_index]
    records = []
    for values in parsed[header_index+1:]:
        row = dict(zip(header, values))
        if (row.get('Asset Class') != 'Equity' or row.get('Location') != 'United States'
                or row.get('Sector') == 'Financials'):
            continue
        original = row.get('Ticker', '').strip()
        ticker = re.sub(r'[. /]+', '-', original.upper())
        if not re.fullmatch(r'[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)?', ticker):
            continue
        records.append({'ticker': ticker, 'original_ticker': original,
                        'name': row.get('Name', ''), 'sector': row.get('Sector', '')})
    if not records:
        raise ValueError('IWM CSV contains no eligible US nonfinancial equities')
    universe = pd.DataFrame(records).drop_duplicates('ticker').sort_values('ticker').reset_index(drop=True)
    return universe, as_of


def candidate_order(universe, seed=SEED):
    """Shuffle a canonical ticker order, independent of CSV holding weights/order."""
    tickers = sorted(set(universe['ticker']))
    random.Random(seed).shuffle(tickers)
    return tickers


def normalize_download(raw, tickers):
    if raw is None or raw.empty:
        return pd.DataFrame()
    raw = raw.copy()
    if not isinstance(raw.columns, pd.MultiIndex):
        if len(tickers) != 1:
            raise ValueError('Multiple-symbol download unexpectedly has flat columns')
        raw = pd.concat({tickers[0]: raw}, axis=1)
    elif not any(t in raw.columns.get_level_values(0) for t in tickers):
        if any(t in raw.columns.get_level_values(1) for t in tickers):
            raw = raw.swaplevel(0, 1, axis=1)
        else:
            raise ValueError('Download MultiIndex has no requested ticker level')
    raw.index = pd.DatetimeIndex(raw.index).tz_localize(None).normalize()
    if raw.index.has_duplicates:
        raise ValueError('Download has duplicate daily timestamps')
    return raw.sort_index()


def assess_candidate(prices, spy):
    """Training completeness alone controls eligibility; future diagnostics do not."""
    prices = prices.reindex(spy.index)
    f = smoke.features(prices, spy)
    complete = f[smoke.FEATURES+['target', 'target_date', 'ret5_close_future']].notna().all(axis=1)
    end = f['target_date']
    date = pd.Series(f.index, index=f.index)
    masks = {
        'train': (date >= '2016-01-01') & (date < '2022-01-01') & (end < '2022-01-01'),
        'validation': (date >= '2022-01-01') & (date < '2024-01-01') & (end < '2024-01-01'),
        'test': (date >= '2024-01-01') & end.notna(),
    }
    coverage = {}
    for name, mask in masks.items():
        expected = int(mask.sum())
        observed = int((mask & complete).sum())
        coverage[name] = {'expected_rows': expected, 'complete_rows': observed,
                          'missing_rows': expected-observed,
                          'complete_fraction': observed/expected if expected else None}
    ohlc = prices[['Open', 'High', 'Low', 'Close']]
    finite = pd.Series(np.isfinite(ohlc.to_numpy(dtype=float)).all(axis=1), index=prices.index)
    invalid = finite & ((ohlc <= 0).any(axis=1)
                        | (prices.High < prices[['Open', 'Close']].max(axis=1))
                        | (prices.Low > prices[['Open', 'Close']].min(axis=1))
                        | (prices.High < prices.Low))
    ratios = prices.Close.pct_change(fill_method=None)
    extreme = ratios[(ratios > 1) | (ratios < -0.6)]
    report = {
        'eligible': coverage['train']['complete_rows'] >= MIN_TRAIN_ROWS,
        'coverage': coverage,
        'invalid_ohlc_rows': int(invalid.sum()),
        'invalid_ohlc_dates': [str(x.date()) for x in prices.index[invalid]],
        'missing_or_nonfinite_ohlc_rows': int((~finite).sum()),
        'negative_volume_rows': int((prices.Volume < 0).sum()),
        'large_daily_changes': [{'date': str(i.date()), 'return': float(v)} for i, v in extreme.items()],
        'diagnostics_affect_selection': False,
    }
    if not report['eligible']:
        report['reason'] = f'training_complete_rows_below_{MIN_TRAIN_ROWS}'
    return report


def main():
    import requests
    import yfinance as yf

    out = Path('experiments/ml_feasibility/results_smallcap')
    out.mkdir(parents=True, exist_ok=True)
    print('STAGE smallcap_holdings_download', flush=True)
    response = requests.get(HOLDINGS_URL, headers={'User-Agent': 'Mozilla/5.0'}, timeout=30)
    response.raise_for_status()
    text = response.content.decode('utf-8-sig')
    (out/'holdings_raw.csv').write_bytes(response.content)
    universe, as_of = parse_holdings(text)
    order = candidate_order(universe)
    ordered = universe.set_index('ticker').loc[order].reset_index()
    ordered.insert(0, 'draw_rank', range(1, len(ordered)+1))
    ordered.to_csv(out/'candidate_order.csv', index=False)
    manifest = {
        'source_url': HOLDINGS_URL, 'holdings_as_of': as_of,
        'downloaded_at_utc': datetime.now(timezone.utc).isoformat(),
        'universe_proxy': 'Current IWM holdings; US Equity excluding Financials',
        'universe_count': len(universe), 'seed': SEED,
        'sample_size': SAMPLE_SIZE, 'max_candidates': MAX_CANDIDATES,
        'price_start': '2014-01-01', 'price_end_exclusive': '2026-10-03',
        'eligibility': 'At least 252 complete training rows from 2016 through 2021, with target_date before 2022',
        'selection_uses_validation_test_coverage_or_return_values': False,
        'selection_order': order, 'selected': [], 'attempts': [],
        'limitations': [
            'Current IWM holdings proxy has survivorship bias and is not historical Russell 2000 membership',
            'Requires historical training data; recent IPOs are underrepresented',
            'Fund Market Value is a position value, not company market capitalization',
            'Future coverage and price diagnostics are reported but do not replace selected symbols',
            'Only 20 sampled symbols; results do not establish performance across small-cap stocks',
        ],
    }

    def save_manifest():
        (out/'selection_manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2))

    save_manifest()

    def download(tickers):
        raw = yf.download(tickers, start='2014-01-01', end='2026-10-03',
                          auto_adjust=False, actions=True, group_by='ticker',
                          threads=4, progress=False, timeout=20)
        return normalize_download(raw, tickers)

    print('STAGE smallcap_spy_calendar', flush=True)
    spy_raw = download(['SPY'])
    if spy_raw.empty or 'SPY' not in spy_raw.columns.get_level_values(0):
        raise RuntimeError('SPY calendar download failed')
    spy = spy_raw['SPY']['Close'].dropna()
    if len(spy) < 1000:
        raise RuntimeError('SPY calendar has insufficient history')
    manifest['calendar_first_date'] = str(spy.index.min().date())
    manifest['calendar_last_date'] = str(spy.index.max().date())
    selected_raw = {'SPY': spy_raw['SPY'].reindex(spy.index)}
    for start in range(0, min(MAX_CANDIDATES, len(order)), 20):
        batch = order[start:min(start+20, MAX_CANDIDATES)]
        print(f'STAGE smallcap_candidate_batch first_rank={start+1} count={len(batch)} selected={len(manifest["selected"])}', flush=True)
        raw = download(batch)
        raw.to_csv(out/f'candidate_prices_{start+1:03d}.csv')
        for offset, ticker in enumerate(batch):
            attempt = {'ticker': ticker, 'draw_rank': start+offset+1}
            if raw.empty or ticker not in raw.columns.get_level_values(0):
                attempt.update(eligible=False, reason='download_missing')
            else:
                d = raw[ticker].reindex(spy.index)
                required = {'Open', 'High', 'Low', 'Close', 'Volume'}
                if not required.issubset(d.columns):
                    attempt.update(eligible=False, reason='required_price_columns_missing')
                else:
                    attempt.update(assess_candidate(d, spy))
                    if attempt['eligible']:
                        manifest['selected'].append(ticker)
                        selected_raw[ticker] = d
                        attempt['selected'] = True
            manifest['attempts'].append(attempt)
            save_manifest()
            if len(manifest['selected']) == SAMPLE_SIZE:
                break
        if len(manifest['selected']) == SAMPLE_SIZE:
            break
    if len(manifest['selected']) != SAMPLE_SIZE:
        manifest['status'] = 'failed_insufficient_training_eligible_symbols'
        save_manifest()
        raise RuntimeError(f'Only {len(manifest["selected"])} eligible symbols among {len(manifest["attempts"])} candidates; need exactly {SAMPLE_SIZE}; no resampling')
    manifest['status'] = 'selection_complete_frozen_before_model_evaluation'
    save_manifest()
    combined = pd.concat(selected_raw, axis=1)
    print(f'STAGE smallcap_sample_frozen symbols={",".join(manifest["selected"])}', flush=True)
    smoke.main(tickers=manifest['selected'], raw=combined, outdir=out,
               metadata=manifest, quarantine=False)


if __name__ == '__main__':
    main()
