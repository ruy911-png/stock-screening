"""Twenty separate ticker models, evaluated against frozen pooled-model results."""
from pathlib import Path
import hashlib
import json
import os
import time

import numpy as np
import pandas as pd

from smoke import FEATURES, select_daily, split_data, summarize

SOURCE_RUN = 37440503107
DATASET_SHA256 = '05ab8db0fcff474420238df08a24a9b87f35deaba48491ebb725d04f02affc2a'
PARAMETERS = dict(n_estimators=400, learning_rate=0.04, num_leaves=15,
                  max_depth=-1, min_child_samples=100, reg_lambda=2,
                  n_jobs=2, random_state=42, verbosity=-1,
                  deterministic=True, force_col_wise=True)


def ticker_partitions(train, valid, test):
    names = set(train.ticker)
    if names != set(valid.ticker) or names != set(test.ticker):
        raise ValueError('Train, validation, test must contain the same frozen ticker sample')
    for ticker in sorted(names):
        a, b, c = [f[f.ticker == ticker].copy() for f in (train, valid, test)]
        assert a.target_date.max() < b.date.min()
        assert b.target_date.max() < c.date.min()
        yield ticker, a, b, c


def attach_pooled_scores(test, pooled):
    keys = ['date', 'ticker']
    wanted = keys+['score', 'target', 'ret5_close_future']
    merged = test.merge(pooled[wanted], on=keys, how='left', validate='one_to_one',
                        suffixes=('', '_source'))
    if len(merged) != len(pooled) or merged.score.isna().any():
        raise ValueError('Frozen pooled predictions and ticker-model test keys differ')
    if not np.array_equal(merged.target.to_numpy(), merged.target_source.to_numpy()):
        raise ValueError('Frozen source labels differ')
    if not np.allclose(merged.ret5_close_future, merged.ret5_close_future_source, atol=1e-12, rtol=0):
        raise ValueError('Frozen source forward returns differ')
    return merged.drop(columns=['target_source', 'ret5_close_future_source']).rename(columns={'score':'pooled_score'})


def main():
    import lightgbm as lgb
    from sklearn.metrics import roc_auc_score, brier_score_loss

    started = time.perf_counter()
    source = Path(os.environ.get('FROZEN_SMALLCAP_INPUT', 'experiments/ml_feasibility/frozen_smallcap'))
    out = Path('experiments/ml_feasibility/results_per_ticker')
    (out/'models').mkdir(parents=True, exist_ok=True)
    dataset_bytes = (source/'dataset.csv').read_bytes()
    digest = hashlib.sha256(dataset_bytes).hexdigest()
    if digest != DATASET_SHA256:
        raise RuntimeError('Frozen dataset hash mismatch; refusing to change the input sample')
    data = pd.read_csv(source/'dataset.csv', parse_dates=['date', 'target_date'])
    previous = pd.read_csv(source/'predictions.csv', parse_dates=['date'])
    manifest = json.loads((source/'selection_manifest.json').read_text())
    train, valid, test = split_data(data)
    if set(test.ticker) != set(manifest['selected']) or test.ticker.nunique() != 20:
        raise RuntimeError('Expected exactly the original 20 selected tickers')
    test = attach_pooled_scores(test, previous)
    test['ticker_score'] = np.nan
    test['training_base_rate'] = np.nan
    model_rows = []
    print(f'STAGE frozen_data_verified train={len(train)} validation={len(valid)} test={len(test)}', flush=True)
    for ticker, a, b, c in ticker_partitions(train, valid, test):
        if a.target.nunique() != 2 or b.target.nunique() != 2:
            raise RuntimeError(f'{ticker}: cannot fit a two-class ticker model; no pooled fallback')
        print(f'STAGE train_ticker ticker={ticker} train={len(a)} train_hits={int(a.target.sum())} validation_hits={int(b.target.sum())}', flush=True)
        model = lgb.LGBMClassifier(**PARAMETERS)
        before = time.perf_counter()
        model.fit(a[FEATURES], a.target.astype(int),
                  eval_set=[(b[FEATURES], b.target.astype(int))], eval_metric='binary_logloss',
                  callbacks=[lgb.early_stopping(30, verbose=False)])
        score = model.predict_proba(c[FEATURES])[:, 1]
        assert np.isfinite(score).all() and ((score >= 0) & (score <= 1)).all()
        test.loc[c.index, 'ticker_score'] = score
        test.loc[c.index, 'training_base_rate'] = float(a.target.mean())
        model.booster_.save_model(str(out/'models'/f'{ticker}.txt'))
        pd.DataFrame({'feature':FEATURES, 'gain':model.booster_.feature_importance(importance_type='gain'),
                      'split_count':model.feature_importances_}).to_csv(out/'models'/f'{ticker}_importance.csv', index=False)
        model_rows.append({'ticker':ticker, 'train_n':len(a), 'train_hits':int(a.target.sum()),
                           'validation_n':len(b), 'validation_hits':int(b.target.sum()), 'test_n':len(c),
                           'train_last_target':str(a.target_date.max().date()),
                           'validation_first_entry':str(b.date.min().date()),
                           'validation_last_target':str(b.target_date.max().date()),
                           'test_first_entry':str(c.date.min().date()),
                           'best_iteration':int(model.best_iteration_),
                           'num_trees':int(model.booster_.num_trees()),
                           'score_std':float(np.std(score)), 'mean_score':float(np.mean(score)),
                           'test_auc':float(roc_auc_score(c.target,score)) if c.target.nunique()==2 else None,
                           'test_brier':float(brier_score_loss(c.target, score)),
                           'training_and_prediction_seconds':time.perf_counter()-before})
    assert test.ticker_score.notna().all() and len(model_rows) == 20
    comparisons = {'baseline_all_days':test,
                   'per_ticker_daily_top2':select_daily(test, 'ticker_score'),
                   'pooled_daily_top2':select_daily(test, 'pooled_score'),
                   'vol60_daily_top2':select_daily(test, 'vol60'),
                   'vol20_daily_top2':select_daily(test, 'vol20'),
                   'historical_ticker_rate_top2':select_daily(test, 'training_base_rate')}
    stats = {name:summarize(frame) for name,frame in comparisons.items()}
    assert stats['pooled_daily_top2']['hits'] == 496 and stats['vol60_daily_top2']['hits'] == 502
    by_ticker = []
    for row in model_rows:
        ticker = row['ticker']
        detail = dict(row)
        for name, frame in comparisons.items():
            detail.update({name+'_'+k:v for k,v in summarize(frame[frame.ticker==ticker]).items()})
        by_ticker.append(detail)
    pd.DataFrame(by_ticker).to_csv(out/'per_ticker_comparison.csv', index=False)
    pd.DataFrame(model_rows).to_csv(out/'training_details.csv', index=False)
    test.to_csv(out/'predictions.csv', index=False)
    comparisons['per_ticker_daily_top2'].to_csv(out/'selected_predictions.csv', index=False)
    by_year = {}
    for name, frame in comparisons.items():
        by_year[name] = {str(year):summarize(g) for year,g in frame.groupby(frame.date.dt.year)}
    result = {'source_run':SOURCE_RUN, 'dataset_sha256':digest,
              'method':'One independent LightGBM per ticker; identical features, hyperparameters and time splits to pooled run',
              'target':'Any high on t+1 through t+5 reaches +10% relative to close on t',
              'lightgbm':lgb.__version__, 'tickers':manifest['selected'], 'models_trained':len(model_rows),
              'parameters':PARAMETERS, 'features':FEATURES,
              'train_rows':len(train), 'validation_rows':len(valid), 'test_rows':len(test),
              'test_first_entry':str(test.date.min().date()), 'test_last_entry':str(test.date.max().date()),
              'test_dates':int(test.date.nunique()), 'total_seconds':time.perf_counter()-started,
              'comparisons':stats, 'by_year':by_year,
              'limitations':['Exploratory repeat on an already inspected test period, not fresh confirmation',
                             'Current surviving small-cap sample with pre-2022 price history; only 20 tickers',
                             'Separate model scores have not been calibrated for cross-ticker comparisons',
                             'Few positive validation examples for some tickers; outcomes overlap across five-day windows',
                             'Daily top-two screening counts repeated dates; no portfolio or executable fill model',
                             'Close-return statistics are separate from intraday target touch, with no costs or dividends']}
    (out/'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
    report = '# Independent ticker model comparison\n\n```json\n'+json.dumps(result, ensure_ascii=False, indent=2)+'\n```\n'
    (out/'result.md').write_text(report)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'],'a') as f:f.write(report)
    print('STAGE complete', flush=True)
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()
