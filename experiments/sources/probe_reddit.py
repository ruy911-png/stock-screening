"""레딧 반응 데이터 출처 시험 — 사용자 요청(2026-10-05): "레딧 반응 긍정인 건에 대한 백테스팅".

백테스트하려면 '과거 날짜별' 레딧 반응(언급·긍정/부정)이 있어야 한다. 출처마다 과거가 어디까지 되는지 본다.
원칙은 probe_sources.py와 같다(robots.txt 존중, 출처당 요청 최소, 정직한 User-Agent).
결과: results/reddit_probe.md
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path

import pandas as pd
import requests

from probe_sources import Result, fetch, robots_check

TRADESTIE = "https://tradestie.com/api/v1/apps/reddit?date={d}"
TRY_DATES = ["2021-03-01", "2021-06-01", "2022-01-03", "2022-06-01", "2023-01-03", "2024-01-02",
             "2025-01-02", "2026-09-01", "2026-10-02"]


def tradestie() -> tuple[Result, list[str]]:
    res = Result("레딧", "Tradestie WSB 감성(날짜별 상위 50)", "과거 날짜별 긍정/부정",
                 TRADESTIE.format(d="YYYY-MM-DD"), note="제3자 계산 감성(계산 방식 미공개)")
    res.robots = robots_check(TRADESTIE.format(d="2024-01-02"))
    if res.robots.startswith("막힘"):
        res.verdict = "안 됨 — robots.txt가 막음(요청 안 함)"
        return res, []
    lines, ok_dates = [], []
    for d in TRY_DATES:
        try:
            r = fetch(TRADESTIE.format(d=d))
            rows = r.json() if r.status_code == 200 else []
            n = len(rows) if isinstance(rows, list) else 0
            if n:
                ok_dates.append(d)
                s = rows[0]
                keys = ", ".join(sorted(s.keys()))
                bull = sum(1 for x in rows if str(x.get("sentiment", "")).lower() == "bullish")
                lines.append(f"  - {d}: HTTP {r.status_code}, {n}종목(긍정 {bull}) · 항목 [{keys}] · 1위 {s.get('ticker')}")
            else:
                lines.append(f"  - {d}: HTTP {r.status_code}, 데이터 없음")
        except (requests.RequestException, ValueError) as e:
            lines.append(f"  - {d}: {type(e).__name__}")
        time.sleep(1.0)
    res.status = "200" if ok_dates else "-"
    res.data = f"데이터 있는 날 {len(ok_dates)}/{len(TRY_DATES)} (가장 이른 {ok_dates[0] if ok_dates else '-'})"
    res.verdict = "됨" if ok_dates else "안 됨"
    return res, lines


def json_probe(res: Result, count_key=None) -> Result:
    res.robots = robots_check(res.url)
    if res.robots.startswith("막힘"):
        res.verdict = "안 됨 — robots.txt가 막음(요청 안 함)"
        return res
    try:
        r = fetch(res.url)
        res.status = str(r.status_code)
        if r.status_code != 200:
            res.data = " ".join(r.text.split())[:80]
            res.verdict = f"안 됨 — HTTP {r.status_code}"
            return res
        j = r.json()
        items = j.get(count_key) if count_key and isinstance(j, dict) else j
        n = len(items) if isinstance(items, (list, dict)) else 0
        res.data = f"항목 {n}개" + (f" · 첫 항목 키 {sorted(items[0].keys())[:8]}" if isinstance(items, list) and items else "")
        res.verdict = "됨" if n else "부분 — 빈 응답"
    except (requests.RequestException, ValueError) as e:
        res.status, res.verdict = type(e).__name__, "안 됨"
    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="results")
    out = Path(ap.parse_args().out)
    out.mkdir(parents=True, exist_ok=True)
    t_res, t_lines = tradestie()
    results = [
        t_res,
        json_probe(Result("레딧", "ApeWisdom (WSB 언급 순위)", "언급 수·순위(현재)",
                          "https://apewisdom.io/api/v1.0/filter/wallstreetbets/page/1"), "results"),
        json_probe(Result("레딧", "Arctic Shift 아카이브 (WSB 게시물)", "과거 원문(감성은 직접 계산)",
                          "https://arctic-shift.photon-reddit.com/api/posts/search"
                          "?subreddit=wallstreetbets&after=2024-01-02&before=2024-01-03&limit=5",
                          note="제3자 아카이브 — 레딧 약관과의 관계 확인 필요"), "data"),
        json_probe(Result("레딧", "Reddit 공식 JSON (로그인 없이)", "현재 게시물",
                          "https://www.reddit.com/r/wallstreetbets/top.json?t=day&limit=5",
                          note="공식 API는 OAuth 앱 등록 필요, 과거 검색 깊이 제한"), "data"),
    ]
    lines = [
        f"# 레딧 반응 데이터 출처 시험 — {pd.Timestamp.now(tz='UTC'):%Y-%m-%d %H:%M} UTC (GitHub Actions)",
        "",
        "목적: '레딧 반응 긍정' 백테스트에 쓸 과거 날짜별 데이터를 받을 수 있는지.",
        "",
        "| 출처 | 용도 | robots.txt | HTTP | 받은 데이터 | 판정 | 메모 |",
        "|---|---|---|---|---|---|---|",
        *[f"| {r.source} | {r.purpose} | {r.robots} | {r.status} | {r.data} | {r.verdict} | {r.note} |" for r in results],
        "",
        "## Tradestie 날짜별 확인",
        *t_lines,
    ]
    (out / "reddit_probe.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
