"""Arctic Shift(레딧 아카이브) 재시험 — 첫 시험이 HTTP 422 "Timeout. Maybe slow down a bit"이었음.

작은 요청 몇 개로 실제로 과거 WSB 글을 받을 수 있는지, 하루 글 수·속도·제한 헤더를 본다.
API 안내(github.com/ArthurHeitmann/arctic_shift/api): 초당 몇 회 이하 권장, 대량은 월별 덤프.
결과: results/arctic_probe.md
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path

import pandas as pd
import requests

from probe_sources import fetch

BASE = "https://arctic-shift.photon-reddit.com/api"
CASES = [
    ("하루 6시간 게시물(제목만)", "/posts/search?subreddit=wallstreetbets&after=2024-01-02T14:00:00&before=2024-01-02T20:00:00"
                            "&limit=100&fields=created_utc,title,score"),
    ("하루 전체 게시물 자동 한도", "/posts/search?subreddit=wallstreetbets&after=2024-01-02&before=2024-01-03"
                           "&limit=auto&fields=created_utc,title,score"),
    ("2021-01-27 하루(밈 주식 급등기)", "/posts/search?subreddit=wallstreetbets&after=2021-01-27&before=2021-01-28"
                                 "&limit=auto&fields=created_utc,title,score"),
    ("2019-06-03 하루", "/posts/search?subreddit=wallstreetbets&after=2019-06-03&before=2019-06-04"
                       "&limit=auto&fields=created_utc,title,score"),
    ("2024년 1월 일별 게시물 수(집계)", "/posts/search/aggregate?subreddit=wallstreetbets&aggregate=created_utc"
                                  "&frequency=day&after=2024-01-01&before=2024-02-01"),
    ("최근(2026-10-01) 하루", "/posts/search?subreddit=wallstreetbets&after=2026-10-01&before=2026-10-02"
                            "&limit=auto&fields=created_utc,title,score"),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="results")
    out = Path(ap.parse_args().out)
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    for name, path in CASES:
        t = time.time()
        try:
            r = fetch(BASE + path)
            dt = time.time() - t
            hdr = {k: v for k, v in r.headers.items() if k.lower().startswith("x-ratelimit")}
            try:
                j = r.json()
            except ValueError:
                j = {}
            data = j.get("data") if isinstance(j, dict) else None
            n = len(data) if isinstance(data, list) else 0
            sample = ""
            if isinstance(data, list) and data:
                first = data[0]
                sample = str(first.get("title", first))[:50].replace("|", "/")
            rows.append(f"| {name} | {r.status_code} | {n} | {dt:.1f}s | {hdr or '-'} | {j.get('error') if isinstance(j, dict) else ''} | {sample} |")
        except requests.RequestException as e:
            rows.append(f"| {name} | {type(e).__name__} | 0 | {time.time() - t:.1f}s | - | - | |")
        time.sleep(2.0)
    lines = [f"# Arctic Shift 재시험 — {pd.Timestamp.now(tz='UTC'):%Y-%m-%d %H:%M} UTC (GitHub Actions)", "",
             "| 요청 | HTTP | 받은 건수 | 걸린 시간 | 제한 헤더 | 오류 | 첫 글(제목 50자) |",
             "|---|---|---:|---:|---|---|---|", *rows]
    (out / "arctic_probe.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
