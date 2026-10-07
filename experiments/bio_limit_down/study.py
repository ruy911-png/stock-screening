"""Exploratory near-limit-down close / next-session rebound study.

Fixed convenience sample, not the entire pharma/biotech industry. Daily close
candidates are inferred from adjusted OHLCV, not exchange limit-status flags.
"""
from concurrent.futures import ThreadPoolExecutor,as_completed
from datetime import datetime,timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
import csv,hashlib,json,math,statistics,sys,urllib.request
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'reversal_warning'))
from daily import parse,valid

OUT=Path(__file__).parent/'results'
STOCKS={'087010':'펩트론','028300':'HLB','196170':'알테오젠','141080':'리가켐바이오',
 '298380':'에이비엘바이오','068760':'셀트리온제약','086900':'메디톡스','084990':'헬릭스미스',
 '215600':'신라젠','086450':'동국제약','145020':'휴젤','064550':'바이오니아',
 '065660':'안트로젠','115450':'HLB테라퓨틱스','067630':'HLB생명과학','032300':'한국파마',
 '950160':'코오롱티슈진','237690':'에스티팜','214450':'파마리서치','140410':'메지온',
 '174900':'앱클론','200670':'휴메딕스','220100':'퓨쳐켐','226950':'올릭스',
 '298060':'에스씨엠생명과학','214370':'케어젠','323990':'박셀바이오','217730':'강스템바이오텍',
 '007390':'네이처셀','299660':'셀리드','307750':'국전약품','378800':'샤페론',
 '347850':'디앤디파마텍','291650':'압타머사이언스','293780':'압타바이오'}
START='2016-01-01'


def download(code,cutoff):
    url=f'https://fchart.stock.naver.com/sise.nhn?symbol={code}&timeframe=day&count=6000&requestType=0'
    info={'code':code,'url':url,'retrieved_at':datetime.now(ZoneInfo('UTC')).isoformat()}
    try:
        request=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0','Referer':'https://finance.naver.com/'})
        with urllib.request.urlopen(request,timeout=15) as response: raw=response.read(4_000_000)
        (OUT/f'{code}.xml').write_bytes(raw)
        rows=[r for r in parse(raw) if r['date']<=cutoff]
        info.update(status='ok',rows=len(rows),first=rows[0]['date'],last=rows[-1]['date'],sha256=hashlib.sha256(raw).hexdigest())
        return code,rows,info
    except Exception as exc:
        info.update(status='failed',error=f'{type(exc).__name__}: {exc}'[:300])
        return code,[],info


def tick(price,day):
    if day<'2023-01-25':
        for limit,unit in [(1000,1),(5000,5),(10000,10),(50000,50),(float('inf'),100)]:
            if price<limit:return unit
    for limit,unit in [(2000,1),(5000,5),(20000,10),(50000,50),(200000,100),(500000,500),(float('inf'),1000)]:
        if price<limit:return unit


def estimated_lower(previous,day):
    unit=tick(previous,day)
    change=math.floor(round(previous*.30/unit,10))*unit
    raw=previous-change
    newunit=tick(raw,day)
    return math.ceil(round(raw/newunit,10))*newunit


def is_candidate(prev,row):
    if not valid(prev) or not valid(row):return False
    ret=row['close']/prev['close']-1
    return -.301<=ret<=-.295 and abs(row['close']-row['low'])<1e-8


def events_for(code,rows,next_day):
    output=[]
    bydate={r['date']:r for r in rows}
    for i in range(1,len(rows)):
        prev,row=rows[i-1],rows[i]
        if row['date']<START or not is_candidate(prev,row):continue
        expected=next_day.get(row['date']); nxt=bydate.get(expected)
        known=nxt is not None and valid(nxt)
        if known and not .65<=nxt['open']/row['close']<=1.35:known=False
        first=not (i>1 and is_candidate(rows[i-2],prev))
        lower=estimated_lower(prev['close'],row['date'])
        event={'code':code,'name':STOCKS[code],'date':row['date'],'previous_close':prev['close'],
            'close':row['close'],'daily_return':row['close']/prev['close']-1,
            'first_in_chain':first,'estimated_lower':lower,'formula_exact_match':row['close']==lower,
            'next_session':expected,'outcome_known':known,
            'next_open_return':nxt['open']/row['close']-1 if known else None,
            'next_high_return':nxt['high']/row['close']-1 if known else None,
            'next_close_return':nxt['close']/row['close']-1 if known else None,
            'next_open_to_close_return':nxt['close']/nxt['open']-1 if known else None,
            'next_close_near_limit_down':is_candidate(row,nxt) if known else None}
        output.append(event)
    return output


def wilson(k,n):
    if not n:return None
    p=k/n;z=1.96;d=1+z*z/n
    a=(p+z*z/(2*n))/d;b=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/d
    return [a-b,a+b]


def summarize(events):
    known=[e for e in events if e['outcome_known']];n=len(known)
    up=sum(e['next_close_return']>0 for e in known)
    return {'events':len(events),'known_next_sessions':n,'unresolved':len(events)-n,
      'next_close_up':up,'next_close_down':sum(e['next_close_return']<0 for e in known),
      'next_close_flat':sum(e['next_close_return']==0 for e in known),
      'next_close_up_fraction':up/n if n else None,'wilson95_unclustered':wilson(up,n),
      'next_open_up':sum(e['next_open_return']>0 for e in known),
      'next_high_above_limit_close':sum(e['next_high_return']>0 for e in known),
      'next_close_up_from_next_open':sum(e['next_open_to_close_return']>0 for e in known),
      'next_limit_close_again':sum(e['next_close_near_limit_down'] for e in known),
      'mean_next_close_return':statistics.mean(e['next_close_return'] for e in known) if n else None,
      'median_next_close_return':statistics.median(e['next_close_return'] for e in known) if n else None}


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    now=datetime.now(ZoneInfo('Asia/Seoul'))
    # Conservative completed KRX-date cutoff. No NXT aftermarket inference.
    cutoff=(now.date() if (now.hour,now.minute)>=(16,0) else (now-timedelta(days=1)).date()).isoformat()
    print('PREDECLARED '+json.dumps({'stocks':STOCKS,'start':START,'cutoff':cutoff,'candidate':'close=low and daily return -30.1% to -29.5%; inferred, not official limit flags'},ensure_ascii=False),flush=True)
    datasets={};manifests=[]
    with ThreadPoolExecutor(max_workers=4) as pool:
        for f in as_completed([pool.submit(download,c,cutoff) for c in [*STOCKS,'069500']]):
            code,rows,meta=f.result();datasets[code]=rows;manifests.append(meta)
            print('SOURCE '+json.dumps(meta,ensure_ascii=False),flush=True)
    calendar=[r['date'] for r in datasets['069500'] if valid(r)]
    if not calendar:raise RuntimeError('Benchmark trading-session calendar unavailable')
    next_day=dict(zip(calendar,calendar[1:]))
    events=[]
    for code in STOCKS:events+=events_for(code,datasets.get(code,[]),next_day)
    events.sort(key=lambda e:(e['date'],e['code']))
    groups={'all_near_limit_closes':events,'first_day_only':[e for e in events if e['first_in_chain']],
       'formula_exact_subset':[e for e in events if e['formula_exact_match']],
       'since_2023':[e for e in events if e['date']>='2023-01-01'],
       'peptron':[e for e in events if e['code']=='087010']}
    result={'cutoff':cutoff,'start':START,'requested_stocks':len(STOCKS),
       'successful_stocks':sum(m['status']=='ok' and m['code']!='069500' for m in manifests),
       'statistics':{key:summarize(value) for key,value in groups.items()},
       'events':events,'peptron_latest':datasets.get('087010',[])[-3:],
       'limitations':['Convenience sample of currently accessible stocks, not full historical sector; survivor and selection bias.',
         'Sector membership is not point-in-time verified. Some historical businesses differ.',
         'Inferred near-limit closes, not official exchange limit-status records. Adjusted prices/corporate actions may affect detection.',
         'Includes successive limit-down days; first-day-only shown separately to avoid hindsight selection of the final day.',
         'Wilson interval assumes independent observations; chains and common-news shocks violate that assumption.',
         'Regular daily observations cannot estimate NXT aftermarket-limit-down next-day odds.',
         'Next-session close up is not an executable investment profit probability.']}
    (OUT/'summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    (OUT/'manifest.json').write_text(json.dumps(manifests,ensure_ascii=False,indent=2))
    if events:
        with (OUT/'events.csv').open('w',newline='',encoding='utf-8-sig') as file:
            writer=csv.DictWriter(file,fieldnames=list(events[0]));writer.writeheader();writer.writerows(events)
    print('RESULT '+json.dumps(result,ensure_ascii=False),flush=True)
    if not events:raise SystemExit('No verified usable event sample')


if __name__=='__main__':main()
