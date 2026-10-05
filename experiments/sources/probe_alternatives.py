"""대체 출처 시험 — 사용자 질문(2026-10-05): "야후파이낸스나 구글파이낸스로 안 돼? 네이버증권".

SEC 재무가 막혔을 때 버핏 필터(7년 영업이익·3년 ROE 등)에 쓸 수 있는지 본다.
원칙은 probe_sources.py와 같다(robots.txt 존중, 출처당 1~3회, 정직한 User-Agent).
결과: results/alternatives_probe.md
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

import pandas as pd

from probe_sources import Result, fetch, robots_check, title_of

NEEDED = {  # 버핏 필터에 필요한 항목(야후 행 이름)
    "Operating Income": "영업이익",
    "Net Income": "순이익",
    "Total Revenue": "매출",
    "Stockholders Equity": "자기자본",
    "Total Liabilities Net Minority Interest": "총부채",
    "Operating Cash Flow": "영업현금흐름",
    "Capital Expenditure": "설비투자",
}


def yahoo_fundamentals(symbol: str, market: str) -> Result:
    res = Result(market, f"야후 재무 ({symbol})", "버핏 필터 재무", "yfinance Ticker.income_stmt 등")
    try:
        import yfinance as yf

        t = yf.Ticker(symbol)
        frames = {"손익": t.income_stmt, "재무상태": t.balance_sheet, "현금흐름": t.cashflow}
        q = t.quarterly_income_stmt
        years = sorted({c.year for f in frames.values() if f is not None and not f.empty for c in f.columns})
        rows = set().union(*[set(map(str, f.index)) for f in frames.values() if f is not None and not f.empty])
        have = [k for k in NEEDED if k in rows]
        miss = [NEEDED[k] for k in NEEDED if k not in rows]
        res.status = "200"
        res.data = (f"연간 {len(years)}개 연도({years[0] if years else '-'}~{years[-1] if years else '-'}) · "
                    f"분기 {0 if q is None else q.shape[1]}개 · 항목 {len(have)}/{len(NEEDED)}"
                    + (f" (없음: {', '.join(miss)})" if miss else ""))
        if len(years) >= 7 and not miss:
            res.verdict = "됨"
        else:
            res.verdict = f"부분 — 연간 {len(years)}년뿐(필요 7년), 제출일이 없어 과거 시점 재현 불가"
    except Exception as e:  # noqa: BLE001
        res.status, res.verdict = type(e).__name__, f"안 됨 — {str(e)[:60]}"
    return res


def web_check(res: Result, keywords: list[str]) -> Result:
    res.robots = robots_check(res.url)
    if res.robots.startswith("막힘"):
        res.verdict = "안 됨 — robots.txt가 막음(요청 안 함)"
        return res
    try:
        r = fetch(res.url)
    except Exception as e:  # noqa: BLE001
        res.status, res.verdict = type(e).__name__, "안 됨 — 접속 실패"
        return res
    res.status = str(r.status_code)
    text = r.content.decode(r.apparent_encoding or "utf-8", errors="replace")
    found = [k for k in keywords if re.search(k, text)]
    res.data = f"제목: {title_of(text)} · 찾은 단어: {', '.join(found) or '없음'}"
    if r.status_code != 200:
        res.verdict = f"안 됨 — HTTP {r.status_code}"
    elif found:
        res.verdict = "접속됨 — 화면(HTML)에서 읽어야 함, 공식 API 아님"
    else:
        res.verdict = "부분 — 접속은 되나 숫자 표 못 찾음(자바스크립트로 그리는 화면 추정)"
    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="results")
    out = Path(ap.parse_args().out)
    out.mkdir(parents=True, exist_ok=True)
    results = [yahoo_fundamentals(s, m) for s, m in
               [("ANET", "미장"), ("APH", "미장"), ("TSM", "미장"), ("005930.KS", "국장")]]
    results += [
        web_check(Result("미장", "구글 파이낸스 (ANET)", "시세·재무", "https://www.google.com/finance/quote/ANET:NYSE",
                         note="공식 API 없음(인수인계 문서: 쓰지 않기로 결정)"), ["Revenue", "Net income", "ANET"]),
        web_check(Result("국장", "네이버증권 종목 (삼성전자)", "시세·재무 요약",
                         "https://finance.naver.com/item/main.naver?code=005930"), ["매출액", "영업이익", "ROE"]),
        web_check(Result("국장", "네이버증권 기업분석(와이즈리포트)", "재무 상세",
                         "https://navercomp.wisereport.co.kr/v2/company/c1030001.aspx?cmp_cd=005930"),
                  ["매출액", "영업이익", "자본총계"]),
        web_check(Result("미장", "네이버증권 해외 (ANET)", "해외 종목 재무",
                         "https://m.stock.naver.com/worldstock/stock/ANET.K/finance",
                         note="종목 코드 형식(ANET.K)은 추정"), ["매출", "영업이익", "Revenue"]),
    ]
    lines = [
        f"# 대체 출처 시험 — {pd.Timestamp.now(tz='UTC'):%Y-%m-%d %H:%M} UTC (GitHub Actions)",
        "",
        "목적: SEC가 막혔을 때 버핏 필터(영업이익 7년·ROE 3년·부채비율·이익률·FCF)에 쓸 재무를 받을 수 있는지.",
        "",
        "| 시장 | 출처 | 용도 | robots.txt | HTTP | 받은 데이터 | 판정 | 메모 |",
        "|---|---|---|---|---|---|---|---|",
        *[f"| {r.market} | {r.source} | {r.purpose} | {r.robots} | {r.status} | {r.data} | {r.verdict} | {r.note} |"
          for r in results],
    ]
    (out / "alternatives_probe.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
