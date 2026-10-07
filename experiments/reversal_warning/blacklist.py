"""Point-in-time descriptive upper-wick blacklist; no order placement.

Consumes archived daily XML. Never uses the previous experiment's signal-eligible
sample: a stock characteristic must not depend on a warning model's lookback.
"""
import argparse
import csv
import json
from pathlib import Path
from daily import UNIVERSE, parse, valid, label

BASE = Path(__file__).parent
POLICY = {'window_observed_sessions': 120, 'minimum_valid_bars_per_window': 100,
          'frequent_fraction': .15, 'severe_high_to_close': -.03,
          'persistence': 'both latest and preceding disjoint 120-session windows must pass',
          'meaning': 'descriptive exclusion candidate, not a forecast or a permanent stock characteristic'}


def window_stats(rows):
    usable = [r for r in rows if valid(r)]
    shapes = [r for r in usable if label(r, r['open'])['upper_wick_event']]
    severe = [r for r in shapes if r['close'] / r['high'] - 1 <= POLICY['severe_high_to_close']]
    return {'observed': len(rows), 'valid': len(usable), 'invalid': len(rows)-len(usable),
            'count': len(shapes), 'rate': len(shapes)/len(usable) if usable else None,
            'severe_count': len(severe), 'first': rows[0]['date'] if rows else None,
            'last': rows[-1]['date'] if rows else None}


def classify(recent, previous):
    if min(recent['valid'], previous['valid']) < POLICY['minimum_valid_bars_per_window']:
        return 'insufficient_data'
    if recent['rate'] >= POLICY['frequent_fraction']:
        return 'blacklist' if previous['rate'] >= POLICY['frequent_fraction'] else 'watch'
    return 'not_flagged'


def build(data_dir, asof):
    records, evidence = [], []
    for code, name in UNIVERSE.items():
        path = data_dir / f'{code}.xml'
        if not path.exists():
            records.append({'code': code, 'name': name, 'status': 'missing_source'})
            continue
        rows = [r for r in parse(path.read_bytes()) if r['date'] <= asof]
        recent = window_stats(rows[-120:])
        previous = window_stats(rows[-240:-120])
        historical = window_stats([r for r in rows if '2024-01-01' <= r['date'] < '2026-01-01'])
        records.append({'code': code, 'name': name, 'status': classify(recent, previous),
                        'recent': recent, 'previous': previous, 'historical_2024_2025': historical})
        for r in rows[-120:]:
            if valid(r) and label(r, r['open'])['upper_wick_event']:
                evidence.append({'code': code, 'name': name, **r,
                                 'upper_wick_fraction': (r['high']-max(r['open'],r['close']))/(r['high']-r['low']),
                                 'high_to_close': r['close']/r['high']-1})
    records.sort(key=lambda r: r.get('recent', {}).get('rate') or 0, reverse=True)
    return {'asof': asof, 'policy': POLICY, 'universe_count': len(UNIVERSE),
            'scope': '12-stock pilot, not an all-Korean-stock blacklist',
            'records': records,
            'limitations': ['A shape is not necessarily a large crash.',
                            'Frequency does not prove the next day or next rise will reverse.',
                            'Observed source sessions are not audited against an exchange calendar.',
                            'The historical archive has no vintage price revision audit.',
                            'Thresholds are provisional and not efficacy-validated.']}, evidence


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--data-dir', type=Path, default=BASE/'results')
    parser.add_argument('--asof', default=None)
    args = parser.parse_args()
    completed_cutoff = json.loads((args.data_dir/'summary.json').read_text())['cutoff']
    asof = args.asof or completed_cutoff
    if asof > completed_cutoff:
        raise ValueError('Requested date exceeds archived completed-session cutoff')
    report, evidence = build(args.data_dir, asof)
    out = args.data_dir / 'blacklist'
    out.mkdir(exist_ok=True)
    (out/'blacklist.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    flattened = []
    for r in report['records']:
        row = {k:r[k] for k in ['code','name','status']}
        for period in ['recent','previous','historical_2024_2025']:
            row.update({period+'_'+k:v for k,v in r.get(period,{}).items()})
        flattened.append(row)
    for name, rows in [('all_stocks.csv',flattened),('blacklist.csv',[r for r in flattened if r['status']=='blacklist']),('shape_dates.csv',evidence)]:
        fields = sorted(set().union(*(r.keys() for r in (rows or flattened))))
        with (out/name).open('w',newline='',encoding='utf-8-sig') as f:
            writer=csv.DictWriter(f,fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()
