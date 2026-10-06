"""Real-price LightGBM feasibility check, not a validated trading strategy."""
from pathlib import Path
import json
import math
import os
import platform
import resource
import time

import numpy as np
import pandas as pd

TICKERS = 'AAPL MSFT AMZN GOOGL NVDA META JNJ PFE XOM CVX KO PEP WMT COST HD CAT UNP IBM PG MCD'.split()
H = 20
FEATURES = ['ret1', 'ret5', 'ret20', 'ret60', 'vol20', 'vol60', 'volume_ratio',
            'ma20_gap', 'ma60_gap', 'ma200_gap', 'rsi14', 'bb_position',
            'body', 'upper_wick', 'lower_wick', 'range', 'spy20', 'spy60']


def features(df, spy):
    c, o, hi, lo, v = (df[x].astype(float) for x in ['Close', 'Open', 'High', 'Low', 'Volume'])
    f = pd.DataFrame(index=c.index)
    for n in [1, 5, 20, 60]:
        f[f'ret{n}'] = c.pct_change(n, fill_method=None)
    for n in [20, 60]:
        f[f'vol{n}'] = f.ret1.rolling(n).std()
    f['volume_ratio'] = v / v.shift(1).rolling(20).mean()
    for n in [20, 60, 200]:
        f[f'ma{n}_gap'] = c / c.rolling(n).mean() - 1
    d = c.diff()
    gain = d.clip(lower=0).ewm(alpha=1/14, adjust=False, min_periods=14).mean()
    loss = (-d.clip(upper=0)).ewm(alpha=1/14, adjust=False, min_periods=14).mean()
    f['rsi14'] = 100 - 100 / (1 + gain / loss)
    f.loc[(gain > 0) & (loss == 0), 'rsi14'] = 100
    f.loc[(gain == 0) & (loss == 0), 'rsi14'] = 50
    f['bb_position'] = (c - c.rolling(20).mean()) / (2*c.rolling(20).std(ddof=0))
    f['body'] = (c-o)/c
    f['upper_wick'] = (hi-pd.concat([o,c],axis=1).max(axis=1))/c
    f['lower_wick'] = (pd.concat([o,c],axis=1).min(axis=1)-lo)/c
    f['range'] = (hi-lo)/c
    f['spy20'] = spy.pct_change(20, fill_method=None).reindex(c.index)
    f['spy60'] = spy.pct_change(60, fill_method=None).reindex(c.index)
    # Labels are deliberately separate from the explicit feature allowlist.
    f['ret20_future'] = c.shift(-H)/c-1
    f['target_date'] = pd.Series(c.index, index=c.index).shift(-H)
    f['target'] = (f.ret20_future >= 0.05).astype(float).where(f.ret20_future.notna())
    return f.replace([np.inf, -np.inf], np.nan)


def split_data(data):
    date = pd.to_datetime(data['date'])
    end = pd.to_datetime(data['target_date'])
    train = data[(date >= '2016-01-01') & (date < '2022-01-01') & (end < '2022-01-01')].copy()
    valid = data[(date >= '2022-01-01') & (date < '2024-01-01') & (end < '2024-01-01')].copy()
    test = data[date >= '2024-01-01'].copy()
    assert len(train) > 1000 and len(valid) > 500 and len(test) > 500
    assert train.target_date.max() < valid.date.min()
    assert valid.target_date.max() < test.date.min()
    assert set(FEATURES).isdisjoint({'target', 'target_date', 'ret20_future', 'ticker', 'date'})
    return train, valid, test


def summarize(frame):
    return {'n': len(frame), 'target_rate': float(frame.target.mean()),
            'mean_return': float(frame.ret20_future.mean()),
            'median_return': float(frame.ret20_future.median()),
            'positive_rate': float((frame.ret20_future > 0).mean())}


def main():
    import lightgbm as lgb
    import sklearn
    from sklearn.metrics import roc_auc_score, brier_score_loss
    import yfinance as yf

    started = time.perf_counter()
    out = Path('experiments/ml_feasibility/results')
    out.mkdir(parents=True, exist_ok=True)
    print('STAGE data_download', flush=True)
    raw = yf.download(TICKERS+['SPY'], start='2014-01-01', end='2026-10-03',
                      auto_adjust=False, actions=True, group_by='ticker', threads=4,
                      progress=False, timeout=20)
    if raw is None or raw.empty:
        raise RuntimeError('No real market data received; synthetic fallback is prohibited')
    raw.to_csv(out/'ohlcv.csv')
    prices = {}
    for ticker in TICKERS+['SPY']:
        if ticker not in raw.columns.get_level_values(0):
            continue
        d = raw[ticker].copy()
        d.index = pd.DatetimeIndex(d.index).tz_localize(None).normalize()
        if d.Close.notna().sum() >= 1000:
            prices[ticker] = d
    if 'SPY' not in prices:
        raise RuntimeError('SPY missing')
    calendar = prices['SPY'].Close.dropna().index
    spy = prices['SPY'].Close.reindex(calendar)
    frames, excluded = [], {}
    for ticker in TICKERS:
        if ticker not in prices:
            excluded[ticker] = 'missing or insufficient prices'
            continue
        d = prices[ticker].reindex(calendar)
        ratios = d.Close.pct_change(fill_method=None)
        # Diagnostic quarantine, not proof all remaining corporate actions are clean.
        if ((ratios > 1) | (ratios < -0.6)).any():
            excluded[ticker] = 'large daily discontinuity needs corporate-action review'
            continue
        f = features(d, spy)
        f['ticker'] = ticker
        f['date'] = f.index
        frames.append(f.dropna(subset=FEATURES+['target','target_date','ret20_future']))
    data = pd.concat(frames, ignore_index=True).sort_values(['date','ticker'])
    if data.ticker.nunique() < 15:
        raise RuntimeError(f'Only {data.ticker.nunique()} usable symbols; need 15')
    data.to_csv(out/'dataset.csv', index=False)
    train, valid, test = split_data(data)
    print(f'STAGE data_ready symbols={data.ticker.nunique()} rows={len(data)} train={len(train)} validation={len(valid)} test={len(test)}', flush=True)
    model = lgb.LGBMClassifier(n_estimators=400, learning_rate=0.04, num_leaves=15,
                              max_depth=-1, min_child_samples=100, reg_lambda=2,
                              n_jobs=2, random_state=42, verbosity=-1,
                              deterministic=True, force_col_wise=True)
    begin = time.perf_counter()
    model.fit(train[FEATURES], train.target.astype(int),
              eval_set=[(valid[FEATURES],valid.target.astype(int))], eval_metric='binary_logloss',
              callbacks=[lgb.early_stopping(30, verbose=False)])
    training_seconds = time.perf_counter()-begin
    begin = time.perf_counter()
    test['score'] = model.predict_proba(test[FEATURES])[:,1]
    inference_seconds = time.perf_counter()-begin
    assert np.isfinite(test.score).all() and test.score.between(0,1).all()
    # Select within each day. No portfolio, cooldown or statistical significance claim.
    selected_idx = []
    for _, group in test.groupby('date',sort=True):
        selected_idx.extend(group.nlargest(max(1,math.ceil(len(group)*0.1)), 'score').index.tolist())
    selected = test.loc[selected_idx]
    baseline_p = float(train.target.mean())
    result = {
        'purpose':'real-price LightGBM smoke test; not calibrated probabilities or proven alpha',
        'python':platform.python_version(), 'lightgbm':lgb.__version__, 'sklearn':sklearn.__version__,
        'symbols':int(data.ticker.nunique()), 'excluded':excluded, 'features':FEATURES,
        'rows':len(data), 'train_rows':len(train), 'validation_rows':len(valid), 'test_rows':len(test),
        'train_last_target':str(train.target_date.max().date()),
        'validation_first_entry':str(valid.date.min().date()),
        'validation_last_target':str(valid.target_date.max().date()),
        'test_first_entry':str(test.date.min().date()), 'test_last_entry':str(test.date.max().date()),
        'best_iteration':model.best_iteration_, 'training_seconds':training_seconds,
        'inference_seconds':inference_seconds, 'total_seconds':time.perf_counter()-started,
        'peak_rss_mb':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,
        'auc':float(roc_auc_score(test.target,test.score)),
        'brier':float(brier_score_loss(test.target,test.score)),
        'constant_train_rate_brier':float(brier_score_loss(test.target,np.full(len(test),baseline_p))),
        'baseline_all_days':summarize(test), 'model_daily_top10pct':summarize(selected),
        'rsi_below30_state':summarize(test[test.rsi14<30]),
        'limitations':['Hand-picked current large-cap survivors; not all S&P500',
                       'Overlapping 20-day outcomes; no inferential significance claim',
                       'Uncalibrated scores; corporate actions not exhaustively verified',
                       'No cooldown; RSI comparison is state, not previous first-day strategy',
                       'Split-adjusted price returns exclude dividends and costs']}
    (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    test.to_csv(out/'predictions.csv', index=False)
    model.booster_.save_model(str(out/'model.txt'))
    pd.Series(model.feature_importances_,index=FEATURES).sort_values(ascending=False).to_csv(out/'feature_importance.csv')
    report = '# LightGBM feasibility smoke test\n\n```json\n'+json.dumps(result,ensure_ascii=False,indent=2)+'\n```\n'
    (out/'result.md').write_text(report)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'],'a') as f: f.write(report)
    print('STAGE complete', flush=True)
    print(json.dumps(result,ensure_ascii=False,indent=2),flush=True)


if __name__ == '__main__':
    main()
