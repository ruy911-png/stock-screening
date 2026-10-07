"""Exploratory daily upper-wick warning experiment, using previous-session features.

No intraday lead-time or 60-minute crash claim can be made from these data.
Thresholds are declared before fetching/evaluating the test observations.
"""
import argparse
import csv
import hashlib
import json
import math
import re
import statistics
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

OUT = Path(__file__).parent / 'results'
UNIVERSE = {'298040': '효성중공업', '267260': 'HD현대일렉트릭', '010120': 'LS ELECTRIC',
            '005930': '삼성전자', '000660': 'SK하이닉스', '042700': '한미반도체',
            '012450': '한화에어로스페이스', '064350': '현대로템', '011200': 'HMM',
            '035420': 'NAVER', '005380': '현대차', '086520': '에코프로'}
PARAMETERS = {'high_vs_prev_close': .03, 'close_vs_high': -.05,
              'upper_wick_range_fraction': .50, 'body_range_fraction_max': .35, 'close_range_location': .40,
              'test_start': '2024-01-01', 'momentum_return_5d': .10,
              'volume_ratio': 1.5, 'ma20_extension': .10}


def parse(payload):
    if isinstance(payload, bytes):
        declaration = re.search(br'encoding=[\"\x27]([^\"\x27]+)', payload[:200])
        encoding = declaration.group(1).decode('ascii') if declaration else 'utf-8'
        payload = payload.decode(encoding)
    rows = []
    for item in ET.fromstring(payload).iter('item'):
        v = item.attrib['data'].split('|')
        if len(v) != 6 or len(v[0]) != 8:
            raise ValueError('Expected dated daily OHLCV observations')
        row = dict(zip(['open', 'high', 'low', 'close', 'volume'], map(float, v[1:])))
        row['date'] = datetime.strptime(v[0], '%Y%m%d').date().isoformat()
        rows.append(row)
    rows.sort(key=lambda x: x['date'])
    if not rows or len({x['date'] for x in rows}) != len(rows):
        raise ValueError('Empty or duplicate daily observations')
    return rows


def valid(row):
    o, h, l, c, v = [row[k] for k in ['open', 'high', 'low', 'close', 'volume']]
    return all(math.isfinite(x) and x > 0 for x in [o, h, l, c, v]) and l <= min(o, c) <= max(o, c) <= h


def label(row, previous_close):
    width = row['high'] - row['low']
    upper = row['high'] - max(row['open'], row['close'])
    gain = row['high'] / previous_close - 1
    reversal = row['close'] / row['high'] - 1
    fraction = upper / width if width else 0
    location = (row['close'] - row['low']) / width if width else 1
    broad = gain >= PARAMETERS['high_vs_prev_close'] and reversal <= PARAMETERS['close_vs_high']
    body = abs(row['close'] - row['open']) / width if width else 1
    wick = fraction >= PARAMETERS['upper_wick_range_fraction'] and body <= PARAMETERS['body_range_fraction_max'] and location <= PARAMETERS['close_range_location']
    return {'broad_reversal': broad, 'upper_wick_event': wick, 'body_fraction': body, 'high_return': gain,
            'high_to_close': reversal, 'upper_wick_fraction': fraction, 'close_location': location}


def signals(history):
    """Input ends at the previous completed session; never sees the event-day bar."""
    if len(history) < 21 or not all(valid(x) for x in history[-21:]):
        return None
    c = history[-1]['close']
    r5 = c / history[-6]['close'] - 1
    ma20 = statistics.mean(x['close'] for x in history[-20:])
    volume_base = statistics.mean(x['volume'] for x in history[-21:-1])
    volume_ratio = history[-1]['volume'] / volume_base
    momentum = r5 >= PARAMETERS['momentum_return_5d']
    return {'always': True, 'momentum': momentum,
            'momentum_volume': momentum and volume_ratio >= PARAMETERS['volume_ratio'],
            'extended_volume': c / ma20 - 1 >= PARAMETERS['ma20_extension'] and volume_ratio >= PARAMETERS['volume_ratio'],
            'return_5d': r5, 'volume_ratio': volume_ratio, 'ma20_extension': c / ma20 - 1}


def fetch(code, cutoff):
    url = f'https://fchart.stock.naver.com/sise.nhn?symbol={code}&timeframe=day&count=6000&requestType=0'
    meta = {'code': code, 'name': UNIVERSE[code], 'url': url, 'retrieved_at': datetime.now(ZoneInfo('UTC')).isoformat()}
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0', 'Referer': 'https://finance.naver.com/'})
        with urllib.request.urlopen(req, timeout=15) as response:
            raw = response.read(4_000_000)
            meta['http_status'] = response.status
        (OUT / f'{code}.xml').write_bytes(raw)
        rows = [r for r in parse(raw) if r['date'] <= cutoff]
        if not rows:
            raise ValueError('No completed daily rows')
        meta.update(status='ok', sha256=hashlib.sha256(raw).hexdigest(), rows=len(rows),
                    first=rows[0]['date'], last=rows[-1]['date'], invalid_rows=sum(not valid(r) for r in rows))
        return code, rows, meta
    except Exception as exc:
        meta.update(status='failed', error=f'{type(exc).__name__}: {exc}'[:400])
        return code, [], meta


def cached(code, cutoff):
    raw = (OUT / f'{code}.xml').read_bytes()
    rows = [r for r in parse(raw) if r['date'] <= cutoff]
    old = json.loads((OUT / 'manifest.json').read_text())
    meta = next(x.copy() for x in old if x['code'] == code)
    meta.pop('error', None)
    meta.update(status='ok', sha256=hashlib.sha256(raw).hexdigest(), rows=len(rows),
                first=rows[0]['date'], last=rows[-1]['date'], invalid_rows=sum(not valid(r) for r in rows))
    return code, rows, meta


def ratio(a, b):
    return a / b if b else None


def evaluate(observations, target):
    result = []
    for rule in ['always', 'momentum', 'momentum_volume', 'extended_volume']:
        alerts = [r for r in observations if r[rule]]
        tp = sum(r[target] for r in alerts)
        positives = sum(r[target] for r in observations)
        fp = len(alerts) - tp
        result.append({'target': target, 'rule': rule, 'observations': len(observations), 'events': positives,
                       'alerts': len(alerts), 'true_positives': tp, 'false_positives': fp,
                       'recall': ratio(tp, positives), 'precision': ratio(tp, len(alerts)),
                       'false_alert_fraction': ratio(fp, len(alerts)),
                       'false_positive_rate': ratio(fp, len(observations) - positives),
                       'alert_fraction': ratio(len(alerts), len(observations)),
                       'base_rate': ratio(positives, len(observations))})
    return result


def write_csv(path, rows):
    if rows:
        with path.open('w', newline='', encoding='utf-8-sig') as file:
            writer = csv.DictWriter(file, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--from-cache', action='store_true', help='Replay the archived XML with its retrieval manifest')
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    now = datetime.now(ZoneInfo('Asia/Seoul'))
    cutoff = (now.date() if (now.hour, now.minute) >= (16, 0) else (now - timedelta(days=1)).date()).isoformat()
    if args.from_cache:
        cutoff = json.loads((OUT / 'summary.json').read_text())['cutoff']
    print('PREDECLARED ' + json.dumps({'parameters': PARAMETERS, 'universe': UNIVERSE, 'completed_cutoff': cutoff}, ensure_ascii=False), flush=True)
    datasets, manifests = {}, []
    with ThreadPoolExecutor(max_workers=3) as pool:
        for future in as_completed([pool.submit(cached if args.from_cache else fetch, code, cutoff) for code in UNIVERSE]):
            code, rows, meta = future.result()
            datasets[code] = rows
            manifests.append(meta)
            print('SOURCE ' + json.dumps(meta, ensure_ascii=False), flush=True)
    observations, hyosung_events, excluded = [], [], []
    for code, rows in datasets.items():
        for i in range(21, len(rows)):
            row, previous = rows[i], rows[i-1]
            sig = signals(rows[:i])
            if sig is None or not valid(row):
                excluded.append({'code': code, 'date': row['date'], 'reason': 'invalid_or_zero_OHLCV_in_lookback_or_target'})
                continue
            # Exclude gross price discontinuities; corporate-action-adjusted archives are still a limitation.
            if not .70 <= row['open'] / previous['close'] <= 1.30:
                excluded.append({'code': code, 'date': row['date'], 'reason': 'opening_price_discontinuity'})
                continue
            record = {'code': code, 'name': UNIVERSE[code], **row, 'signal_asof': previous['date'],
                      'previous_close': previous['close'], **label(row, previous['close']), **sig}
            if code == '298040' and (record['upper_wick_event'] or record['broad_reversal']):
                hyosung_events.append(record)
            if row['date'] >= PARAMETERS['test_start']:
                observations.append(record)
    metrics = evaluate(observations, 'upper_wick_event') + evaluate(observations, 'broad_reversal')
    hyosung = datasets.get('298040', [])
    summary = {'study': 'exploratory fixed daily rules, not intraday prediction', 'cutoff': cutoff,
               'parameters': PARAMETERS, 'universe_selection': 'fixed convenience sample; power equipment, large-cap and volatile stocks; survivor/selection bias',
               'actual_first': min((r['date'] for r in observations), default=None),
               'actual_last': max((r['date'] for r in observations), default=None),
               'sources_ok': sum(x['status'] == 'ok' for x in manifests), 'metrics': metrics,
               'hyosung_recent_candidates': hyosung_events[-15:], 'hyosung_recent_daily': hyosung[-70:],
               'screenshot_exact_high_matches': [r for r in hyosung if r['high'] == 2907000],
               'excluded_rows': len(excluded),
               'limitations': ['Daily labels are available only after the close; signals use prior sessions only.',
                               'No intraday warning time, 60-minute horizon, tick data or LLM performance measured.',
                               'Archived prices have no historical receipt timestamps; adjusted-price revisions and missing sessions not independently audited.',
                               'Fixed selected survivors, one public source, no tuned model and no out-of-sample efficacy claim.',
                               'Screenshot price during a live session need not equal that session closing price.']}
    (OUT / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    (OUT / 'manifest.json').write_text(json.dumps(manifests, ensure_ascii=False, indent=2))
    write_csv(OUT / 'observations.csv', observations)
    write_csv(OUT / 'events.csv', [r for r in observations if r['upper_wick_event'] or r['broad_reversal']])
    write_csv(OUT / 'excluded.csv', excluded)
    print('RESULT ' + json.dumps(summary, ensure_ascii=False), flush=True)
    if not observations:
        raise SystemExit('No actual eligible observations: no performance claim possible')


if __name__ == '__main__':
    main()
