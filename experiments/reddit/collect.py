"""Arctic Shift(레딧 아카이브)에서 r/wallstreetbets 게시물 제목을 하루씩 받아 종목·날짜별로 집계.

- 원문(제목)은 저장하지 않고 숫자만 남긴다: 날짜·종목·글 수·감성 합·긍정/부정 글 수·추천수 합.
- 요청 간격 ≥ PAUSE초, 422/429/5xx면 X-RateLimit-Reset만큼 기다렸다 재시도, 그래도 실패하면 그날은 '실패'로 기록.
- API 안내: 초당 몇 회 이하 권장(github.com/ArthurHeitmann/arctic_shift/api).
사용: python collect.py --year 2024 --out data/
"""
from __future__ import annotations

import argparse
import io
import time
from collections import defaultdict
from pathlib import Path

import pandas as pd
import requests

from wsb import extract_tickers, sentiment

API = "https://arctic-shift.photon-reddit.com/api/posts/search"
UA = "stock-screening-reddit-backtest/0.1 (+https://github.com/ruy911-png/stock-screening)"
CONSTITUENTS_URL = "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/constituents.csv"
PAUSE = 2.0
POS, NEG = 0.05, -0.05  # VADER 관례 경계


def universe() -> set[str]:
    r = requests.get(CONSTITUENTS_URL, timeout=60)
    r.raise_for_status()
    syms = pd.read_csv(io.StringIO(r.text))["Symbol"].astype(str)
    return {s.replace(".", "-") for s in syms}


RETRY_WAITS = (5.0, 15.0, 30.0)  # 실패 시 기다리는 초(제한 헤더가 더 짧으면 그만큼만)
MAX_FAIL_STREAK = 20             # 연속 실패 날이 이만큼이면 그 해 수집을 멈춘다(출처가 안 되는 기간)


def _get(sess: requests.Session, params: dict):
    for wait in (*RETRY_WAITS, None):
        try:
            r = sess.get(API, params=params, headers={"User-Agent": UA}, timeout=60)
        except requests.RequestException:
            r = None
        time.sleep(PAUSE)
        if r is not None and r.status_code == 200:
            return r.json().get("data") or []
        if r is not None and r.status_code not in (422, 429, 500, 502, 503, 504):
            return None
        if wait is None:
            return None
        reset = (r.headers.get("X-RateLimit-Reset", "") if r is not None else "").strip()
        time.sleep(min(wait, float(reset)) if reset.replace(".", "", 1).isdigit() else wait)
    return None


def fetch_day(sess: requests.Session, day: pd.Timestamp) -> tuple[list[dict] | None, bool]:
    """하루(UTC) 게시물과 완전 여부. 한 번에 다 안 오면 마지막 글 시각부터 이어 받는다."""
    start, end = day, day + pd.Timedelta(days=1)
    after, seen, posts = start, set(), []
    for _ in range(15):
        data = _get(sess, {"subreddit": "wallstreetbets", "after": f"{after:%Y-%m-%dT%H:%M:%S}",
                           "before": f"{end:%Y-%m-%dT%H:%M:%S}", "limit": "auto", "sort": "asc",
                           "fields": "id,created_utc,title,score"})
        if data is None:
            return (posts or None), False
        new = [p for p in data if p.get("id") not in seen]
        if not new:
            break
        for p in new:
            seen.add(p.get("id"))
        posts += new
        last = pd.Timestamp(max(int(p["created_utc"]) for p in new), unit="s")
        if last >= end - pd.Timedelta(hours=1) or len(data) < 100:
            break
        after = last
    return posts, True


def collect(year: int, out: Path, last_day: pd.Timestamp | None = None) -> None:
    uni = universe()
    sess = requests.Session()
    agg = defaultdict(lambda: [0, 0.0, 0, 0, 0])  # 글 수, 감성 합, 긍정 수, 부정 수, 추천수 합
    cover = []
    last_day = last_day or (pd.Timestamp.now(tz="UTC").tz_localize(None).normalize() - pd.Timedelta(days=1))
    streak = 0
    for day in pd.date_range(f"{year}-01-01", f"{year}-12-31", freq="D"):
        if day > last_day:
            break
        if streak >= MAX_FAIL_STREAK:
            cover.append({"date": day.date(), "status": "실패", "posts": 0, "posts_with_ticker": 0})
            continue
        posts, complete = fetch_day(sess, day)
        if posts is None:
            streak += 1
            cover.append({"date": day.date(), "status": "실패", "posts": 0, "posts_with_ticker": 0})
            continue
        streak = 0
        with_ticker = 0
        for p in posts:
            tickers = extract_tickers(p.get("title", ""), uni)
            if not tickers:
                continue
            with_ticker += 1
            s = sentiment(p.get("title", ""))
            for t in tickers:
                a = agg[(day.date(), t)]
                a[0] += 1
                a[1] += s
                a[2] += s >= POS
                a[3] += s <= NEG
                a[4] += int(p.get("score") or 0)
        cover.append({"date": day.date(), "status": "성공" if complete else "일부", "posts": len(posts),
                      "posts_with_ticker": with_ticker})
    out.mkdir(parents=True, exist_ok=True)
    rows = [{"date": d, "ticker": t, "n": v[0], "sent_sum": round(v[1], 4), "n_pos": v[2], "n_neg": v[3],
             "score_sum": v[4]} for (d, t), v in agg.items()]
    pd.DataFrame(rows, columns=["date", "ticker", "n", "sent_sum", "n_pos", "n_neg", "score_sum"]).to_csv(
        out / f"wsb_ticker_day_{year}.csv", index=False)
    pd.DataFrame(cover).to_csv(out / f"wsb_coverage_{year}.csv", index=False)
    ok = sum(c["status"] == "성공" for c in cover)
    print(f"{year}: 성공 {ok}/{len(cover)}일, 게시물 {sum(c['posts'] for c in cover)}, 종목 언급 행 {len(rows)}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--out", default="data")
    ap.add_argument("--last-day", default=None, help="시험용 마지막 날짜(YYYY-MM-DD)")
    a = ap.parse_args()
    collect(a.year, Path(a.out), pd.Timestamp(a.last_day) if a.last_day else None)
