"""Exploratory Korean cosmetics stock models; signals, not an execution simulator."""
from pathlib import Path
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import argparse
import ast
from concurrent.futures import ThreadPoolExecutor, as_completed
import xml.etree.ElementTree as ET
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



def parse_naver_chart(payload):
    """Parse the publisher's OHLCV observations, with no missing-date imputation."""
    root = ET.fromstring(payload)
    rows = []
    for item in root.iter('item'):
        values = item.attrib.get('data', '').split('|')
        if len(values) < 6:
            raise ValueError('Malformed Naver chart observation')
        rows.append([values[0], *[float(x) for x in values[1:6]]])
    if not rows:
        raise ValueError('Naver chart contained no price observations')
    frame = pd.DataFrame(rows, columns=['date', *PRICE_FIELDS])
    frame['date'] = pd.to_datetime(frame.date, format='%Y%m%d')
    if frame.date.duplicated().any():
        raise ValueError('Duplicate dates in Naver chart')
    return frame.set_index('date').sort_index()


def fetch_naver(ticker, limit, out):
    import requests
    code = ticker.split('.')[0]
    headers = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://finance.naver.com/'}
    urls = [f'https://fchart.stock.naver.com/sise.nhn?symbol={code}&timeframe=day&count=6000&requestType=0',
            f'https://api.finance.naver.com/siseJson.naver?symbol={code}&requestType=1&startTime=20140101&endTime={limit:%Y%m%d}&timeframe=day']
    errors = []
    for kind, url in enumerate(urls):
        try:
            response = requests.get(url, headers=headers, timeout=20)
            response.raise_for_status()
            payload = response.text
            (out/'source_payloads'/f'{ticker}_naver_{kind}.txt').write_text(payload)
            if kind == 0:
                frame = parse_naver_chart(payload)
            else:
                values = ast.literal_eval(payload.strip())
                rows = [row[:6] for row in values[1:] if len(row) >= 6]
                frame = pd.DataFrame(rows, columns=['date', *PRICE_FIELDS])
                frame['date'] = pd.to_datetime(frame.date.astype(str).str.strip(), format='%Y%m%d')
                for name in PRICE_FIELDS:
                    frame[name] = pd.to_numeric(frame[name], errors='raise')
                if frame.date.duplicated().any():
                    raise ValueError('Duplicate dates in Naver JSON')
                frame = frame.set_index('date').sort_index()
            frame = frame.loc[(frame.index >= '2014-01-01') & (frame.index <= pd.Timestamp(limit))]
            if frame.empty:
                raise ValueError('No observations in the requested date range')
            return frame, {'ticker': ticker, 'source': 'Naver Finance', 'url': url,
                           'first_date': str(frame.index.min().date()), 'last_date': str(frame.index.max().date()),
                           'rows': len(frame), 'earlier_endpoint_errors': errors}
        except Exception as error:
            errors.append(f'{url}: {type(error).__name__}: {str(error)[:240]}')
    raise RuntimeError(' | '.join(errors))


def download_primary_naver(tickers, limit, out):
    (out/'source_payloads').mkdir(parents=True, exist_ok=True)
    prices, sources, errors = {}, [], {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(fetch_naver, ticker, limit, out): ticker for ticker in tickers}
        for future in as_completed(futures):
            ticker = futures[future]
            try:
                frame, record = future.result()
                prices[ticker] = frame
                sources.append(record)
                print(f'STAGE naver_download {ticker} rows={len(frame)} latest={record["last_date"]}', flush=True)
            except Exception as error:
                errors[ticker] = str(error)
                print(f'STAGE naver_unavailable {ticker} {str(error)[:180]}', flush=True)
    metadata = {'primary_source': 'Naver Finance complete per-ticker OHLCV history; Yahoo audit only',
                'sources': sources, 'errors': errors,
                'policy': 'Never impute missing prices or splice Yahoo observations into Naver histories'}
    (out/'price_source_manifest.json').write_text(json.dumps(metadata, ensure_ascii=False, indent=2))
    if BENCHMARK not in prices:
        raise RuntimeError('Primary Naver Korean benchmark unavailable; refusing Yahoo or synthetic fallback')
    return pd.concat(prices, axis=1).sort_index(), metadata


def audit_sources(primary, yahoo, out):
    audit, missing = [], []
    for ticker in primary.columns.get_level_values(0).unique():
        n = primary[ticker].dropna(subset=['Close'])
        y = (yahoo[ticker].dropna(subset=['Close']) if yahoo is not None and not yahoo.empty
             and ticker in yahoo.columns.get_level_values(0) else pd.DataFrame(columns=PRICE_FIELDS))
        common = n.index.intersection(y.index)
        absent = n.index.difference(y.index)
        for date in absent:
            missing.append({'ticker': ticker, 'date': str(date.date()), 'source_with_observation': 'Naver', 'missing_source': 'Yahoo'})
        latest = n.index.max()
        yclose = float(y.loc[latest, 'Close']) if latest in y.index else None
        differences = ((n.loc[common, 'Close'] / y.loc[common, 'Close']) - 1).abs() if len(common) else pd.Series(dtype=float)
        audit.append({'ticker': ticker, 'naver_rows': len(n), 'yahoo_rows': len(y),
                      'common_rows': len(common), 'naver_dates_missing_in_yahoo': len(absent),
                      'latest_date': str(latest.date()), 'latest_naver_close': float(n.loc[latest, 'Close']),
                      'latest_yahoo_close': yclose,
                      'latest_close_relative_difference': (float(n.loc[latest, 'Close']) / yclose - 1) if yclose else None,
                      'common_close_difference_over_0_5pct_rows': int((differences > .005).sum()),
                      'maximum_common_close_relative_difference': float(differences.max()) if len(differences) else None})
    pd.DataFrame(audit).to_csv(out/'cross_source_audit.csv', index=False)
    pd.DataFrame(missing).to_csv(out/'naver_dates_missing_from_yahoo.csv', index=False)
    return audit


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
    yahoo = None
    try:
        yahoo = yf.download(tickers+[BENCHMARK], start='2014-01-01', end=str(limit+timedelta(days=1)),
                            auto_adjust=False, actions=True, group_by='ticker', threads=4, progress=False, timeout=20)
        if yahoo is not None and not yahoo.empty:
            yahoo.index = pd.DatetimeIndex(yahoo.index).tz_localize(None).normalize()
            yahoo = yahoo.loc[yahoo.index <= pd.Timestamp(limit)]
            yahoo.to_csv(out/'ohlcv_yahoo_audit_only.csv')
    except Exception as error:
        (out/'yahoo_audit_download_error.txt').write_text(str(error))
        print(f'STAGE yahoo_audit_unavailable {error}', flush=True)
    raw, price_sources = download_primary_naver(tickers+[BENCHMARK], limit, out)
    source_audit = audit_sources(raw, yahoo, out)
    raw.to_csv(out/'ohlcv_naver_primary.csv')
    raw.to_csv(out/'ohlcv.csv')
    benchmark_frame = raw[BENCHMARK]
    calendar = benchmark_frame.loc[(benchmark_frame.Close > 0) & (benchmark_frame.Volume > 0)].index
    traded = pd.DataFrame({ticker: (raw[ticker].Close > 0) & (raw[ticker].Volume > 0)
                           for ticker in tickers if ticker in raw.columns.get_level_values(0)})
    market_activity = traded.sum(axis=1)
    missing_benchmark = market_activity[(market_activity >= max(3, len(traded.columns)//2)) & ~market_activity.index.isin(calendar)]
    pd.DataFrame({'date': missing_benchmark.index, 'stocks_with_trades': missing_benchmark.to_numpy()}).to_csv(out/'benchmark_calendar_gaps.csv', index=False)
    if len(missing_benchmark):
        raise RuntimeError('Primary benchmark is missing sessions traded by many stocks; see benchmark_calendar_gaps.csv')
    inspected_dates = []
    for inspected in ['2024-01-15', '2025-09-19']:
        date = pd.Timestamp(inspected)
        inspected_dates.append({'date': inspected, 'benchmark_has_session': bool(date in calendar),
                                'primary_stocks_with_trades': int(market_activity.get(date, 0)),
                                'note': 'Prior Yahoo download anomalies; publisher observations retained, never imputed'})
    (out/'previous_anomaly_dates_check.json').write_text(json.dumps(inspected_dates, indent=2))
    if len(calendar) < 400:
        raise RuntimeError('Insufficient Korean benchmark sessions')
    asof = calendar.max()
    benchmark = benchmark_frame.Close.reindex(calendar)
    frames, data_excluded, flags, quality = {}, {}, [], []
    for ticker in tickers:
        if ticker not in raw.columns.get_level_values(0) or raw[ticker].Close.notna().sum() == 0:
            data_excluded[ticker] = 'Primary Naver source provided no prices; see source manifest errors'
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
              'price_source_manifest': price_sources, 'cross_source_audit': source_audit,
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
                             'Naver publisher price history; Yahoo is audit-only. No missing-price imputation or cross-source splicing. Dividends, costs, news and corporate actions not exhaustively verified',
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
