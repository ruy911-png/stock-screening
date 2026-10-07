"""Exploratory Korean cosmetics stock models; signals, not an execution simulator."""
from pathlib import Path
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import argparse
import json
import os
import time

import numpy as np
import pandas as pd

from smoke import FEATURES, features, summarize

BENCHMARK = '069500.KS'  # KODEX 200: market-calendar and market-return features.
PARAMETERS = dict(n_estimators=400, learning_rate=0.04, num_leaves=15,
                  max_depth=-1, min_child_samples=100, reg_lambda=2,
                  n_jobs=2, random_state=42, verbosity=-1,
                  deterministic=True, force_col_wise=True)
MIN_TURNOVER = 1_000_000_000  # KRW 10억원, average of latest 20 sessions.
PRICE_FIELDS = ['Open', 'High', 'Low', 'Close', 'Volume']


def completed_date(now=None):
    now = datetime.now(ZoneInfo('Asia/Seoul')) if now is None else now.astimezone(ZoneInfo('Asia/Seoul'))
    # After the close allow 30 minutes for Yahoo to finalize the daily candle.
    return now.date() if (now.hour, now.minute) >= (16, 0) else (now-timedelta(days=1)).date()


def clean_prices(frame, calendar):
    d = frame.reindex(calendar).copy()
    q = d[PRICE_FIELDS]
    invalid = q.isna().any(axis=1) | (q <= 0).any(axis=1)
    invalid |= (d.High < d[['Open', 'Close']].max(axis=1)) | (d.Low > d[['Open', 'Close']].min(axis=1)) | (d.High < d.Low)
    d.loc[invalid, PRICE_FIELDS] = np.nan
    return d, invalid


def build_frame(prices, benchmark, ticker):
    # smoke's spy20/spy60 names are retained, but their input here is KODEX 200.
    f = features(prices, benchmark)
    f['date'] = f.index
    f['ticker'] = ticker
    f['close'] = prices.Close
    f['volume'] = prices.Volume
    f['turnover_20d_krw'] = (prices.Close*prices.Volume).rolling(20).mean()
    # Keep the latest feature row even when its forward label is unknown.
    return f.dropna(subset=FEATURES).reset_index(drop=True)


def mature_rows(frame, asof):
    return frame.dropna(subset=['target', 'target_date', 'ret5_close_future']).loc[
        lambda x: (x.date >= '2016-01-01') & (x.target_date <= pd.Timestamp(asof))].copy()


def live_partitions(mature, validation_rows=126):
    b = mature.sort_values('date').tail(validation_rows).copy()
    if len(b) < validation_rows:
        return mature.iloc[:0].copy(), b
    a = mature[(mature.date < b.date.min()) & (mature.target_date < b.date.min())].copy()
    return a, b


def eligibility(a, b):
    if len(a) < 252:
        return f'training history below 252 usable sessions ({len(a)})'
    if len(b) < 126:
        return f'validation history below 126 usable sessions ({len(b)})'
    if a.target.nunique() != 2:
        return 'training data lacks one target class'
    if b.target.nunique() != 2:
        return 'validation data lacks one target class'
    return None


def daily_top(frame, column, n=3):
    # Deterministic ticker tie-break, identical ranking convention for every method.
    return frame.sort_values(['date', column, 'ticker'], ascending=[True, False, True]).groupby('date', sort=True).head(n).copy()


def fit_model(train, valid):
    import lightgbm as lgb
    model = lgb.LGBMClassifier(**PARAMETERS)
    model.fit(train[FEATURES], train.target.astype(int),
              eval_set=[(valid[FEATURES], valid.target.astype(int))], eval_metric='binary_logloss',
              callbacks=[lgb.early_stopping(30, verbose=False)])
    return model


def safe_json(value):
    if isinstance(value, dict):
        return {str(k): safe_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [safe_json(v) for v in value]
    if isinstance(value, (float, np.floating)) and not np.isfinite(value):
        return None
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    return value


def save_model(model, out, stem):
    model.booster_.save_model(str(out/'models'/f'{stem}.txt'))
    pd.DataFrame({'feature': FEATURES, 'gain': model.booster_.feature_importance(importance_type='gain')}).sort_values('gain', ascending=False).to_csv(out/'models'/f'{stem}_importance.csv', index=False)


def historical_test(frames, asof, out):
    chunks, exclusions, training = [], {}, []
    for ticker, frame in frames.items():
        m = mature_rows(frame, asof)
        a = m[(m.date < '2022-01-01') & (m.target_date < '2022-01-01')].copy()
        b = m[(m.date >= '2022-01-01') & (m.date < '2024-01-01') & (m.target_date < '2024-01-01')].copy()
        c = m[m.date >= '2024-01-01'].copy()
        reason = eligibility(a, b)
        if reason or c.empty:
            exclusions[ticker] = reason or 'no 2024+ labeled test data'
            continue
        assert a.target_date.max() < b.date.min() and b.target_date.max() < c.date.min()
        print(f'STAGE history_model {ticker} train={len(a)} valid={len(b)} test={len(c)}', flush=True)
        model = fit_model(a, b)
        c['ticker_score'] = model.predict_proba(c[FEATURES])[:, 1]
        c['training_base_rate'] = a.target.mean()
        save_model(model, out, f'history_{ticker}')
        chunks.append((a, b, c))
        training.append({'ticker': ticker, 'train_n': len(a), 'train_hits': int(a.target.sum()),
                         'validation_n': len(b), 'validation_hits': int(b.target.sum()),
                         'best_iteration': int(model.best_iteration_), 'test_n': len(c),
                         'train_last_target': str(a.target_date.max().date()),
                         'validation_first_entry': str(b.date.min().date()),
                         'validation_last_target': str(b.target_date.max().date())})
    if not chunks:
        return {'excluded': exclusions, 'symbols': 0, 'comparisons': {}}, pd.DataFrame()
    train, valid, test = [pd.concat([x[i] for x in chunks], ignore_index=True) for i in range(3)]
    pooled = fit_model(train, valid)
    test['pooled_score'] = pooled.predict_proba(test[FEATURES])[:, 1]
    save_model(pooled, out, 'history_pooled')
    comparisons = {'baseline_all_days': test,
                   'per_ticker_daily_top3': daily_top(test, 'ticker_score'),
                   'pooled_daily_top3': daily_top(test, 'pooled_score'),
                   'vol60_daily_top3': daily_top(test, 'vol60'),
                   'vol20_daily_top3': daily_top(test, 'vol20'),
                   'training_base_rate_daily_top3': daily_top(test, 'training_base_rate')}
    stats = {name: summarize(f) for name, f in comparisons.items()}
    details = []
    for record in training:
        row = dict(record)
        for name, f in comparisons.items():
            row.update({name+'_'+key: val for key, val in summarize(f[f.ticker == row['ticker']]).items()})
        details.append(row)
    detail_frame = pd.DataFrame(details)
    detail_frame.to_csv(out/'historical_per_ticker.csv', index=False)
    test.to_csv(out/'historical_predictions.csv', index=False)
    comparisons['per_ticker_daily_top3'].to_csv(out/'historical_selected.csv', index=False)
    pd.DataFrame(training).to_csv(out/'historical_training.csv', index=False)
    return {'excluded': exclusions, 'symbols': int(test.ticker.nunique()),
            'test_first_entry': str(test.date.min().date()), 'test_last_entry': str(test.date.max().date()),
            'test_dates': int(test.date.nunique()), 'test_symbols_per_day_min': int(test.groupby('date').ticker.nunique().min()),
            'test_symbols_per_day_max': int(test.groupby('date').ticker.nunique().max()),
            'comparisons': stats}, detail_frame


def latest_predictions(frames, stocks, asof, out):
    import lightgbm as lgb
    rows, exclusions, validation_frames = [], {}, []
    lookup = {s['ticker']: s for s in stocks}
    for ticker, frame in frames.items():
        current = frame[frame.date == pd.Timestamp(asof)]
        if len(current) != 1:
            exclusions[ticker] = 'no valid feature row on the latest completed benchmark session'
            continue
        m = mature_rows(frame, asof)
        a, b = live_partitions(m)
        reason = eligibility(a, b)
        if reason:
            exclusions[ticker] = reason
            continue
        assert a.target_date.max() < b.date.min()
        assert m.target_date.max() <= pd.Timestamp(asof)
        print(f'STAGE live_model {ticker} train={len(a)} valid={len(b)} mature={len(m)}', flush=True)
        provisional = fit_model(a, b)
        vscore = provisional.predict_proba(b[FEATURES])[:, 1]
        vb = b.copy()
        vb['validation_score'] = vscore
        validation_frames.append(vb)
        cutoff = float(np.quantile(vscore, .9))
        high = vb[vb.validation_score >= cutoff]
        parameters = dict(PARAMETERS, n_estimators=max(1, int(provisional.best_iteration_)))
        final = lgb.LGBMClassifier(**parameters)
        final.fit(m[FEATURES], m.target.astype(int))
        score = float(final.predict_proba(current[FEATURES])[0, 1])
        save_model(final, out, f'live_{ticker}')
        item = current.iloc[0]
        record = lookup[ticker]
        tradable = bool(item.volume > 0 and np.isfinite(item.turnover_20d_krw) and item.turnover_20d_krw >= MIN_TURNOVER)
        rows.append({'ticker': ticker, 'code': str(record['code']).zfill(6), 'name': record['name'],
                     'category': record.get('category', ''), 'asof': str(pd.Timestamp(asof).date()),
                     'score': score, 'eligible': tradable,
                     'eligibility_reason': 'pass' if tradable else 'latest 20-session mean turnover below KRW 1 billion or unavailable',
                     'close_krw': float(item.close), 'target_10pct_krw': float(item.close*1.1),
                     'ret5': float(item.ret5), 'ret20': float(item.ret20), 'vol60': float(item.vol60),
                     'volume_ratio': float(item.volume_ratio), 'rsi14': float(item.rsi14),
                     'turnover_20d_krw': float(item.turnover_20d_krw),
                     'mature_train_n': len(m), 'mature_train_hits': int(m.target.sum()),
                     'own_historical_base_rate': float(m.target.mean()),
                     'earlystop_train_n': len(a), 'earlystop_train_hits': int(a.target.sum()),
                     'validation_n': len(b), 'validation_hits': int(b.target.sum()),
                     'validation_base_rate': float(b.target.mean()),
                     'validation_top_decile_n': len(high), 'validation_top_decile_hits': int(high.target.sum()),
                     'validation_top_decile_hit_rate': float(high.target.mean()),
                     'validation_top_decile_score_threshold': cutoff,
                     'validation_first_entry': str(b.date.min().date()),
                     'validation_last_entry': str(b.date.max().date()),
                     'last_mature_target_date': str(m.target_date.max().date()),
                     'best_iteration': int(provisional.best_iteration_),
                     'score_note': 'Uncalibrated model score; not a verified probability. Validation top decile is descriptive and from the pre-refit model.'})
    live = pd.DataFrame(rows)
    if not live.empty:
        live = live.sort_values(['score', 'ticker'], ascending=[False, True])
        live.to_csv(out/'live_predictions.csv', index=False)
        chosen = live[live.eligible].head(3).copy()
        chosen.to_csv(out/'shortlist_top3.csv', index=False)
    else:
        chosen = pd.DataFrame()
    if validation_frames:
        pd.concat(validation_frames, ignore_index=True).to_csv(out/'live_validation_predictions.csv', index=False)
    return {'excluded': exclusions, 'scored_symbols': len(live),
            'eligible_symbols': int(live.eligible.sum()) if not live.empty else 0,
            'shortlist': chosen.to_dict(orient='records')}, live


def main():
    import yfinance as yf
    import lightgbm as lgb
    parser = argparse.ArgumentParser()
    parser.add_argument('--universe', type=Path, default=Path(__file__).with_name('kr_cosmetics_universe.json'))
    parser.add_argument('--outdir', type=Path, default=Path(__file__).with_name('results_korea'))
    parser.add_argument('--asof', default=None)
    args = parser.parse_args()
    started = time.perf_counter()
    limit = completed_date()
    if args.asof:
        requested = pd.Timestamp(args.asof).date()
        if requested > limit:
            raise ValueError('Requested date is not a completed Korean session yet')
        limit = requested
    source = json.loads(args.universe.read_text())
    stocks = source['stocks'] if isinstance(source, dict) else source
    for stock in stocks:
        stock['ticker'] = stock.get('ticker', stock.get('yahoo_ticker', stock.get('symbol')))
    tickers = [s['ticker'] for s in stocks]
    if len(set(tickers)) != len(tickers) or any(t is None for t in tickers):
        raise ValueError('Universe tickers must be present and unique')
    out = args.outdir
    (out/'models').mkdir(parents=True, exist_ok=True)
    (out/'universe.json').write_text(json.dumps(source, ensure_ascii=False, indent=2))
    print(f'STAGE download requested_symbols={len(tickers)} latest_allowed_date={limit}', flush=True)
    raw = yf.download(tickers+[BENCHMARK], start='2014-01-01', end=str(limit+timedelta(days=1)),
                      auto_adjust=False, actions=True, group_by='ticker', threads=4, progress=False, timeout=20)
    if raw is None or raw.empty or BENCHMARK not in raw.columns.get_level_values(0):
        raise RuntimeError('Real market data or Korean benchmark missing; no synthetic fallback')
    raw.index = pd.DatetimeIndex(raw.index).tz_localize(None).normalize()
    raw = raw.loc[raw.index <= pd.Timestamp(limit)]
    raw.to_csv(out/'ohlcv.csv')
    benchmark_frame = raw[BENCHMARK]
    calendar = benchmark_frame.loc[(benchmark_frame.Close > 0) & (benchmark_frame.Volume > 0)].index
    if len(calendar) < 400:
        raise RuntimeError('Insufficient Korean benchmark sessions')
    asof = calendar.max()
    benchmark = benchmark_frame.Close.reindex(calendar)
    frames, data_excluded, flags, quality = {}, {}, [], []
    for ticker in tickers:
        if ticker not in raw.columns.get_level_values(0) or raw[ticker].Close.notna().sum() == 0:
            data_excluded[ticker] = 'Yahoo provided no prices'
            continue
        d, invalid = clean_prices(raw[ticker], calendar)
        moves = d.Close.pct_change(fill_method=None)
        extreme = moves[(moves > .305) | (moves < -.305)]
        for date, value in extreme.items():
            flags.append({'ticker': ticker, 'date': str(date.date()), 'daily_close_return': float(value),
                          'note': 'Review IPO, suspension resumption, and corporate actions; flag alone does not exclude ticker'})
        f = build_frame(d, benchmark, ticker)
        if f.empty:
            data_excluded[ticker] = 'fewer than 200 continuous sessions or incomplete OHLCV/features'
            continue
        frames[ticker] = f
        quality.append({'ticker': ticker, 'valid_price_sessions': int(d.Close.notna().sum()),
                        'missing_or_invalid_sessions': int(invalid.sum()),
                        'last_valid_price': str(d.Close.dropna().index.max().date()),
                        'last_valid_features': str(f.date.max().date()), 'extreme_price_flags': len(extreme)})
    if not frames:
        raise RuntimeError('No usable sector data; no synthetic fallback')
    pd.concat(list(frames.values()), ignore_index=True).to_csv(out/'dataset_including_unlabeled_latest.csv', index=False)
    pd.DataFrame(quality).to_csv(out/'data_quality.csv', index=False)
    print(f'STAGE data_ready usable_symbols={len(frames)} benchmark_asof={asof.date()}', flush=True)
    historical, details = historical_test(frames, asof, out)
    latest, live = latest_predictions(frames, stocks, asof, out)
    result = {'purpose': 'Exploratory Korean cosmetics individual-stock models and latest screening candidates',
              'asof': str(asof.date()), 'requested_latest_allowed_date': str(limit),
              'target': 'Any intraday high on the NEXT 5 Korean exchange sessions reaches 110% of signal-day close; signal-day high excluded',
              'benchmark': BENCHMARK, 'market_feature_names': 'spy20/spy60 are KODEX 200 returns here, not SPY',
              'lightgbm_version': lgb.__version__, 'features': FEATURES, 'parameters': PARAMETERS,
              'universe_count': len(stocks), 'download_usable_count': len(frames),
              'data_excluded': data_excluded, 'extreme_price_flags': flags,
              'minimum_latest_turnover_20d_krw': MIN_TURNOVER,
              'historical': historical, 'latest': latest, 'elapsed_seconds': time.perf_counter()-started,
              'limitations': ['Current manually declared sector membership; survivorship and sector-selection bias',
                             'Historical split: 2016-2021 train, 2022-2023 validation, 2024 onward known-outcome test',
                             'Latest models are separately refit on all labels mature by asof; latest predictions have no realized outcome yet',
                             'Overlapping five-session windows and repeated ticker selections; no significance or independent-event claim',
                             'A high touch does not guarantee a fill or a realized ten-percent return; signal-close reference is not an executable entry',
                             'Scores from separate models are uncalibrated and not directly verified success probabilities',
                             'Latest validation top-decile rates have small samples and are descriptive; validation also chose model iteration',
                             'Suspended/invalid sessions remain calendar gaps; windows touching such gaps have unknown labels',
                             'Yahoo split-adjusted price data; dividends, costs, news and corporate actions not exhaustively verified',
                             'Historical rankings use same available eligible universe each date and do not apply the latest-only liquidity gate',
                             'Latest shortlist is mechanically top three eligible scores, not a demonstrated edge over volatility or per-ticker base rates']}
    result = safe_json(result)
    (out/'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    report = '# Korean cosmetics exploratory model results\n\n```json\n'+json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)+'\n```\n'
    (out/'result.md').write_text(report)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as stream:
            stream.write(report)
    print('STAGE complete', flush=True)
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), flush=True)


if __name__ == '__main__':
    main()
