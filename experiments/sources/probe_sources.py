"""출처별 실제 접속 시험 — 사용자 요청(2026-10-05): "실제로 테스트 돌려보고 안 되는 것 알려줘".

앱처럼 프로그램으로 요청해 데이터를 받을 수 있는지 본다. 원칙:
- robots.txt가 막은 경로는 요청하지 않고 '막힘'으로 기록한다.
- 출처당 요청 1~3회, 정직한 User-Agent(브라우저로 위장하지 않음).
- 인증키가 필요한 API는 키 없이 불러 '키 필요' 응답만 확인한다(키가 환경변수에 있으면 실제 조회).
결과: results/source_probe.md, results/source_probe.json
"""
from __future__ import annotations

import argparse
import json
import os
import re
import time
from dataclasses import asdict, dataclass
from io import StringIO
from pathlib import Path
from urllib import robotparser
from urllib.parse import urlparse

import pandas as pd
import requests

UA = "stock-screening-source-probe/0.1 (+https://github.com/ruy911-png/stock-screening)"
SEC_UA = "stock-screening backtest research github.com/ruy911-png/stock-screening"
TIMEOUT = 25


@dataclass
class Result:
    market: str
    source: str
    purpose: str
    url: str
    robots: str = "-"
    status: str = "-"
    data: str = "-"
    verdict: str = "-"
    note: str = ""


_robots: dict[str, tuple] = {}


def robots_check(url: str) -> str:
    """robots.txt 기준 허용 여부. 401/403이면 전체 금지로 본다(표준 해석)."""
    p = urlparse(url)
    base = f"{p.scheme}://{p.netloc}"
    if base not in _robots:
        try:
            r = requests.get(base + "/robots.txt", headers={"User-Agent": UA}, timeout=TIMEOUT)
            if r.status_code in (401, 403) or r.status_code >= 500:  # 5xx도 보수적으로 금지
                _robots[base] = ("deny", r.status_code)
            elif r.status_code >= 400:
                _robots[base] = ("allow", r.status_code)
            else:
                rp = robotparser.RobotFileParser()
                rp.parse(r.text.splitlines())
                _robots[base] = (rp, r.status_code)
        except requests.RequestException as e:
            _robots[base] = ("error", type(e).__name__)
    rp, code = _robots[base]
    if rp == "deny":
        return f"막힘(robots.txt {code})"
    if rp == "allow":
        return f"허용(robots.txt 없음 {code})"
    if rp == "error":
        return f"확인 불가({code})"
    return "허용" if rp.can_fetch(UA, url) else "막힘"


def fetch(url: str, headers: dict | None = None, **kw) -> requests.Response:
    h = {"User-Agent": UA}
    h.update(headers or {})
    return requests.get(url, headers=h, timeout=TIMEOUT, **kw)


def title_of(html: str) -> str:
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.S | re.I)
    return re.sub(r"\s+", " ", m.group(1)).strip()[:60] if m else "(제목 없음)"


def web_probe(res: Result, parse=None):
    """robots 확인 → 1회 요청 → (선택) 파싱. 반환: (Result, 파싱 결과)."""
    res.robots = robots_check(res.url)
    if res.robots.startswith("막힘"):
        res.verdict = "안 됨 — robots.txt가 막음(요청 안 함)"
        return res, None
    try:
        r = fetch(res.url)
    except requests.RequestException as e:
        res.status, res.verdict = type(e).__name__, "안 됨 — 접속 실패"
        return res, None
    res.status = str(r.status_code)
    if r.status_code != 200:
        res.data = title_of(r.text) if "html" in r.headers.get("content-type", "") else "-"
        res.verdict = f"안 됨 — HTTP {r.status_code}"
        return res, None
    if parse is None:
        res.data = f"페이지 제목: {title_of(r.text)}"
        res.verdict = "접속됨"
        return res, None
    try:
        return parse(res, r)
    except Exception as e:  # noqa: BLE001 — 파싱 실패도 결과로 기록
        res.data = f"파싱 실패: {type(e).__name__}: {str(e)[:60]}"
        res.verdict = "부분 — 접속은 되나 데이터 추출 실패"
        return res, None


def _close_table(html: str) -> pd.DataFrame:
    for t in pd.read_html(StringIO(html)):
        cols = [str(c) for c in t.columns]
        close = next((c for c in cols if re.search(r"^close|종가|price", c, re.I)), None)
        date = next((c for c in cols if re.search(r"date|날짜|일자", c, re.I)), None)
        if close and date:
            t.columns = cols
            out = pd.DataFrame({"date": pd.to_datetime(t[date], errors="coerce"),
                                "close": pd.to_numeric(t[close].astype(str).str.replace(",", ""), errors="coerce")})
            return out.dropna()
    raise ValueError("종가 표를 찾지 못함(자바스크립트로 그리는 페이지일 수 있음)")


def parse_price_table(res: Result, r: requests.Response):
    t = _close_table(r.text)
    res.data = f"종가 표 {len(t)}행, 최근 {t['date'].max():%Y-%m-%d}"
    res.verdict = "기술적으로 됨"
    return res, t.set_index("date")["close"].sort_index()


def parse_ir(res: Result, r: requests.Response):
    html = r.text
    pdfs = len(re.findall(r"\.pdf", html, re.I))
    hits = len(re.findall(r"quarter|results|실적", html, re.I))
    res.data = f"제목: {title_of(html)} · PDF 링크 {pdfs}개 · '실적' 단어 {hits}회"
    res.verdict = "접속됨 — 숫자는 보도자료(HTML/PDF), 회사마다 형식 다름"
    return res, None


# ── 개별 출처 ───────────────────────────────────────────────

def sec_ticker_ciks() -> tuple[Result, dict]:
    url = "https://www.sec.gov/files/company_tickers.json"
    res = Result("미장", "SEC 티커→CIK 표", "CIK 조회", url, note=f"User-Agent: {SEC_UA}")
    try:
        r = fetch(url, headers={"User-Agent": SEC_UA})
    except requests.RequestException as e:
        res.status, res.verdict = type(e).__name__, "안 됨 — 접속 실패"
        return res, {}
    res.status = str(r.status_code)
    if r.status_code != 200:
        res.data = re.sub(r"<[^>]+>|\s+", " ", r.text)[:100]
        res.verdict = f"안 됨 — HTTP {r.status_code}"
        return res, {}
    res.data, res.verdict = f"{len(r.json())}개 티커", "됨"
    return res, {v["ticker"]: int(v["cik_str"]) for v in r.json().values()}


def sec_probe(ticker: str, ciks: dict) -> Result:
    cik = ciks.get(ticker)
    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik or 0:010d}.json"
    res = Result("미장", f"SEC EDGAR ({ticker})", "공시 재무(분기·연간)", url)
    if not cik:
        res.verdict = "안 됨 — 티커→CIK 못 찾음"
        return res
    try:
        r = fetch(url, headers={"User-Agent": SEC_UA})
    except requests.RequestException as e:
        res.status, res.verdict = type(e).__name__, "안 됨 — 접속 실패"
        return res
    res.status = str(r.status_code)
    if r.status_code != 200:
        res.data = re.sub(r"<[^>]+>|\s+", " ", r.text)[:100]
        res.verdict = f"안 됨 — HTTP {r.status_code}"
        return res
    body = r.json()
    res.source += f" — {body.get('entityName', '')}"
    facts = body.get("facts", {})
    taxos = {k: len(v) for k, v in facts.items()}
    forms, quarterly_rev, last_q = set(), 0, None
    for taxo in facts.values():
        for tag, node in taxo.items():
            for unit_rows in node.get("units", {}).values():
                for f in unit_rows:
                    forms.add(f.get("form"))
                    if re.search(r"^Revenue", tag) and f.get("start"):
                        days = (pd.Timestamp(f["end"]) - pd.Timestamp(f["start"])).days
                        if 80 <= days <= 100:
                            quarterly_rev += 1
                            last_q = max(last_q or f["end"], f["end"])
    res.data = (f"분류체계 {taxos} · 제출 양식 {sorted(x for x in forms if x)[:6]} · "
                f"분기 매출 값 {quarterly_rev}개(최근 분기말 {last_q or '없음'})")
    res.verdict = "됨" if quarterly_rev else "부분 — 연간만 있고 분기 매출 값 없음"
    return res


def yahoo_probe(symbol: str, market: str) -> tuple[Result, pd.Series | None]:
    res = Result(market, f"야후 yfinance ({symbol}) — 참고", "일봉(현재 시험 코드 원천)", "query1/2.finance.yahoo.com")
    try:
        import yfinance as yf

        df = yf.Ticker(symbol).history(period="2mo", auto_adjust=False)
        if df.empty:
            res.verdict = "안 됨 — 빈 응답"
            return res, None
        s = df["Close"]
        s.index = pd.DatetimeIndex(s.index).tz_localize(None).normalize()
        res.status, res.data, res.verdict = "200", f"{len(s)}일, 최근 {s.index[-1]:%Y-%m-%d}", "됨"
        return res, s
    except Exception as e:  # noqa: BLE001
        res.status, res.verdict = type(e).__name__, f"안 됨 — {str(e)[:60]}"
        return res, None


def naver_kr_probe(code: str) -> tuple[Result, pd.Series | None]:
    url = f"https://m.stock.naver.com/api/stock/{code}/price?pageSize=30&page=1"
    res = Result("국장", f"네이버 모바일 ({code}) — 참고(주식킹 방식)", "일봉 종가", url, note="비공식 API")
    res.robots = robots_check(url)
    if res.robots.startswith("막힘"):
        res.verdict = "안 됨 — robots.txt가 막음(요청 안 함)"
        return res, None
    try:
        r = fetch(url)
        res.status = str(r.status_code)
        rows = r.json()
        s = pd.Series({pd.Timestamp(x["localTradedAt"][:10]): float(str(x["closePrice"]).replace(",", ""))
                       for x in rows}).sort_index()
        res.data, res.verdict = f"{len(s)}일, 최근 {s.index[-1]:%Y-%m-%d}", "기술적으로 됨"
        return res, s
    except Exception as e:  # noqa: BLE001
        res.verdict = f"안 됨 — {type(e).__name__}"
        return res, None


def pykrx_probe(code: str) -> tuple[Result, pd.Series | None]:
    res = Result("국장", f"KRX 정보데이터시스템 via pykrx ({code})", "일봉 OHLCV", "data.krx.co.kr",
                 note="pykrx README: 일부 기능 KRX 로그인 필요")
    try:
        from pykrx import stock

        end = pd.Timestamp.today().strftime("%Y%m%d")
        start = (pd.Timestamp.today() - pd.Timedelta(days=45)).strftime("%Y%m%d")
        df = stock.get_market_ohlcv(start, end, code)
        if df is None or df.empty:
            res.verdict = "안 됨 — 빈 응답(로그인 필요 가능성)"
            return res, None
        close = next(c for c in df.columns if "종가" in str(c) or str(c).lower() == "close")
        s = df[close].astype(float)
        s.index = pd.DatetimeIndex(s.index)
        res.status, res.data, res.verdict = "200", f"{len(s)}일, 최근 {s.index[-1]:%Y-%m-%d}", "됨"
        return res, s
    except Exception as e:  # noqa: BLE001
        res.status, res.verdict = type(e).__name__, f"안 됨 — {str(e)[:60]}"
        return res, None


def dart_probe() -> Result:
    key = os.environ.get("DART_API_KEY", "")
    url = "https://opendart.fss.or.kr/api/company.json?corp_code=00126380&crtfc_key="
    res = Result("국장", "DART OpenAPI", "공시 재무·기업정보", url + ("(키)" if key else "(키 없음)"))
    try:
        r = fetch(url + (key or "0" * 40))
        res.status = str(r.status_code)
        j = r.json()
        res.data = f"status {j.get('status')} · {j.get('message', '')[:30]}"
        if j.get("status") == "000":
            res.verdict = "됨"
        elif j.get("status") in ("010", "011", "012", "901"):
            res.verdict = "키 필요 — 인증키 발급 후 사용"
        else:
            res.verdict = "안 됨"
    except Exception as e:  # noqa: BLE001
        res.status, res.verdict = type(e).__name__, "안 됨 — 접속 실패"
    return res


def krx_openapi_probe() -> Result:
    key = os.environ.get("KRX_AUTH_KEY", "")
    day = (pd.Timestamp.today() - pd.offsets.BDay(1)).strftime("%Y%m%d")
    url = f"https://data-dbg.krx.co.kr/svc/apis/sto/stk_bydd_trd?basDd={day}"
    res = Result("국장", "KRX Open API", "유가증권 일별매매정보", url, note="키 승인 약 1영업일(검색 결과)")
    try:
        r = fetch(url, headers={"AUTH_KEY": key} if key else None)
        res.status = str(r.status_code)
        body = r.text[:120].replace("\n", " ")
        res.data = body
        if r.status_code == 200 and "OutBlock" in r.text:
            res.verdict = "됨"
        elif r.status_code in (401, 403) or "auth" in body.lower() or "인증" in body:
            res.verdict = "키 필요 — 인증키 발급·서비스 신청 후 사용"
        else:
            res.verdict = f"안 됨 — HTTP {r.status_code}"
    except Exception as e:  # noqa: BLE001
        res.status, res.verdict = type(e).__name__, "안 됨 — 접속 실패"
    return res


def compare(name: str, a: pd.Series | None, b: pd.Series | None, la: str, lb: str) -> str:
    if a is None or b is None:
        return f"- {name}: 비교 못 함({la if a is None else lb} 데이터 없음)"
    both = pd.concat([a.rename("a"), b.rename("b")], axis=1).dropna()
    if both.empty:
        return f"- {name}: 겹치는 날짜 없음"
    diff = (both["a"] / both["b"] - 1).abs()
    return (f"- {name}: 겹치는 {len(both)}일, 종가 최대 차이 {diff.max():.4%} "
            f"(최근 {both.index[-1]:%Y-%m-%d}: {la} {both['a'].iloc[-1]:,.2f} / {lb} {both['b'].iloc[-1]:,.2f})")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="results")
    out = Path(ap.parse_args().out)
    out.mkdir(parents=True, exist_ok=True)
    results: list[Result] = []

    # 미장
    sa, sa_close = web_probe(Result("미장", "StockAnalysis.com (ANET)", "일봉 OHLC·거래량",
                                    "https://stockanalysis.com/stocks/anet/history/",
                                    note="약관: 자동 수집·대량 다운로드 금지(robots.txt 따르는 크롤러 예외) — 검색 요약"),
                             parse_price_table)
    results.append(sa)
    results.append(web_probe(Result("미장", "TrendScreeners.com", "Trend Template·RS 계산값",
                                    "https://trendscreeners.com/"))[0])
    for name, url in [("Arista IR", "https://investors.arista.com/"),
                      ("Amphenol IR", "https://investors.amphenol.com/"),
                      ("TSMC IR", "https://investor.tsmc.com/english/quarterly-results")]:
        results.append(web_probe(Result("미장", name, "실적·가이던스", url), parse_ir)[0])
    map_res, ciks = sec_ticker_ciks()
    results.append(map_res)
    # 표를 못 받아도 회사 재무 API는 따로 시험: ANET·APH는 S&P 500 구성종목 CSV의 CIK, TSM은 추정 CIK(응답의 회사명으로 확인)
    ciks = {"ANET": 1596532, "APH": 820313, "TSM": 1046179, **ciks}
    for t in ("ANET", "APH", "TSM"):
        results.append(sec_probe(t, ciks))
        time.sleep(0.2)
    y_res, y_close = yahoo_probe("ANET", "미장")
    results.append(y_res)

    # 국장
    for host in ("www", "kr"):
        results.append(web_probe(Result("국장", f"Investing.com ({host}, 삼성전자)", "일봉",
                                        f"https://{host}.investing.com/equities/samsung-electronics-co-ltd-historical-data"),
                                 parse_price_table)[0])
    results.append(web_probe(Result("국장", "한국경제 Markets", "시세", "https://markets.hankyung.com/"))[0])
    results.append(web_probe(Result("국장", "한국경제 Markets 종목 페이지", "일봉",
                                    "https://markets.hankyung.com/stock/005930/total",
                                    note="종목 페이지 주소는 추정"))[0])
    results.append(dart_probe())
    results.append(krx_openapi_probe())
    k_res, k_close = pykrx_probe("005930")
    results.append(k_res)
    results.append(web_probe(Result("국장", "KIND", "시장경보 공시", "https://kind.krx.co.kr/"))[0])
    results.append(web_probe(Result("국장", "KRX 시장감시위원회", "시장경보 조회", "https://surveillance.krx.co.kr/"))[0])
    results.append(web_probe(Result("국장", "연합뉴스", "보조 실적·뉴스", "https://www.yna.co.kr/",
                                    note="앱은 직접 수집 대신 팩트체크 검색으로 사용 예정"))[0])
    n_res, n_close = naver_kr_probe("005930")
    results.append(n_res)

    checks = [compare("ANET 야후 vs StockAnalysis", y_close, sa_close, "야후", "StockAnalysis"),
              compare("삼성전자 KRX(pykrx) vs 네이버", k_close, n_close, "KRX", "네이버")]

    def group(v: str) -> str:
        if v.startswith(("됨", "접속됨", "기술적으로 됨")):
            return "ok"
        if v.startswith("키 필요"):
            return "key"
        return "partial" if v.startswith("부분") else "bad"

    groups = {g: [r for r in results if group(r.verdict) == g] for g in ("bad", "key", "partial")}
    item = lambda r: f"- **{r.market} {r.source}** ({r.purpose}): {r.verdict}" + (f" — {r.note}" if r.note else "")  # noqa: E731
    lines = [
        f"# 출처 접속 시험 — {pd.Timestamp.now(tz='UTC'):%Y-%m-%d %H:%M} UTC (GitHub Actions)",
        "",
        "원칙: robots.txt가 막은 경로는 요청 안 함 · 출처당 1~3회 · 정직한 User-Agent · 키 필요한 API는 키 없이 응답만 확인.",
        "",
        f"## 안 되는 것 ({len(groups['bad'])})",
        *[item(r) for r in groups["bad"]],
        "",
        f"## 키를 발급받아야 되는 것 ({len(groups['key'])})",
        *[item(r) for r in groups["key"]],
        "",
        f"## 일부만 되는 것 ({len(groups['partial'])})",
        *[item(r) for r in groups["partial"]],
        "",
        "## 전체 결과",
        "| 시장 | 출처 | 용도 | robots.txt | HTTP | 받은 데이터 | 판정 | 메모 |",
        "|---|---|---|---|---|---|---|---|",
        *[f"| {r.market} | {r.source} | {r.purpose} | {r.robots} | {r.status} | {r.data} | {r.verdict} | {r.note} |"
          for r in results],
        "",
        "## 원천끼리 종가 대조",
        *checks,
    ]
    (out / "source_probe.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (out / "source_probe.json").write_text(json.dumps([asdict(r) for r in results], ensure_ascii=False, indent=1),
                                           encoding="utf-8")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
