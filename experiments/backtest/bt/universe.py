"""S&P 500 밖 유니버스(러셀 1000에서 S&P 500·금융 제외) 준비 — 사용자 요청(2026-10-05):
"나스닥은?" → "중복종목 빼고 러셀 1000" → "시총 100으로 해라".

목록 출처: 사용자가 iShares IWB(러셀 1000 ETF) 보유종목 파일을 브라우저로 직접 내려받은 것.
그 파일의 저작권 고지(개인·비상업적 용도, 복사·배포·게시 금지)에 따라 목록은 공개 저장소에 두지 않는다.
make_universe_secret.py가 파일 → 한 줄 문자열("티커:섹터코드,…", IWB 비중 큰 순)로 바꾸고,
사용자가 그 문자열을 GitHub Secret(R1000X_UNIVERSE)에 넣으면 워크플로가 환경변수로 받는다.
"""
from __future__ import annotations

import csv
import io
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pandas as pd

ENV_NAME = "R1000X_UNIVERSE"
TOP_N = 100  # "시총 100": 제외 후 IWB 비중(유동주식 시가총액) 상위 N
# GICS 섹터 ↔ 짧은 코드. iShares 표기 'Communication'은 S&P 목록과 같게 'Communication Services'로 맞춘다
SECTOR_CODES = {
    "IT": "Information Technology", "IN": "Industrials", "HC": "Health Care", "CD": "Consumer Discretionary",
    "CM": "Communication Services", "EN": "Energy", "MT": "Materials", "RE": "Real Estate",
    "CS": "Consumer Staples", "UT": "Utilities", "FN": "Financials",
}
ISHARES_SECTORS = {**{v: k for k, v in SECTOR_CODES.items()}, "Communication": "CM"}
_SS = "{urn:schemas-microsoft-com:office:spreadsheet}"


def norm_ticker(t: str) -> str:
    """'BRK B'·'BRK.B'·'brk-b' → 'BRK-B' (야후·SEC 표기)."""
    return re.sub(r"[ ./]+", "-", str(t).strip().upper())


def parse_spec(spec: str) -> pd.DataFrame:
    """'NVDA:IT,AAPL:IT,…' → 표(index=티커, sector, rank). 순서 = IWB 비중 큰 순."""
    rows = []
    for i, item in enumerate(x for x in (spec or "").replace("\n", ",").split(",") if x.strip()):
        tkr, _, code = item.strip().partition(":")
        code = code.strip().upper()
        if not tkr.strip() or code not in SECTOR_CODES:
            raise ValueError(f"유니버스 항목 형식 오류 ({i + 1}번째)")  # 비밀값이라 내용은 찍지 않는다
        rows.append((norm_ticker(tkr), SECTOR_CODES[code], i + 1))
    if not rows:
        raise ValueError("유니버스 문자열이 비어 있음")
    return pd.DataFrame(rows, columns=["symbol", "sector", "rank"]).drop_duplicates("symbol").set_index("symbol")


def ticker_cik_map(company_tickers: dict) -> dict[str, int]:
    """SEC company_tickers.json → {티커: CIK}."""
    out: dict[str, int] = {}
    for row in company_tickers.values():
        t = norm_ticker(row.get("ticker", ""))
        if t and t not in out:
            out[t] = int(row["cik_str"])
    return out


def build(spec: pd.DataFrame, ticker_ciks: dict[str, int], sp500: pd.DataFrame,
          exclude_sectors: tuple[str, ...] = ("Financials",)) -> tuple[pd.DataFrame, dict]:
    """S&P 500과 같은 회사(티커·클래스·CIK)와 제외 섹터를 빼고, 한 회사의 여러 클래스는 비중 큰 것 하나만 남긴다.

    반환: (load_universe와 같은 열 + rank(제외 후 순위) 표, 단계별 개수)
    """
    counts = {"목록": len(spec)}
    sp_t = {norm_ticker(s) for s in sp500.index}
    sp_base = {t.split("-")[0] for t in sp_t}
    same = [t in sp_t or t.split("-")[0] in sp_base for t in spec.index]
    df = spec[[not x for x in same]].copy()
    counts["S&P 500과 같은 티커·클래스"] = int(sum(same))
    fin = df["sector"].isin(exclude_sectors)
    counts["금융"] = int(fin.sum())
    df = df[~fin]
    df["cik"] = [ticker_ciks.get(t, ticker_ciks.get(t.replace("-", ""))) for t in df.index]
    sp_ciks = set(pd.to_numeric(sp500["cik"], errors="coerce").dropna().astype(int))
    in_sp = df["cik"].isin(sp_ciks)
    counts["S&P 500과 같은 회사(CIK)"] = int(in_sp.sum())
    df = df[~in_sp]
    dup = df["cik"].notna() & df["cik"].duplicated(keep="first")
    counts["같은 회사 다른 클래스"] = int(dup.sum())
    df = df[~dup]
    counts["CIK 못 찾음(재무 미확인)"] = int(df["cik"].isna().sum())
    df = df.assign(yahoo=df.index, name=df.index, sub_industry=None, rank=range(1, len(df) + 1))
    counts["최종"] = len(df)
    return df[["yahoo", "name", "sector", "sub_industry", "cik", "rank"]], counts


# ── 사용자가 내려받은 iShares 보유종목 파일 읽기 (make_universe_secret.py가 쓴다) ──

def _spreadsheet_rows(text: str, sheet: str = "Holdings") -> list[list[str]]:
    """Excel 2003 XML(SpreadsheetML) 한 시트 → 행 목록. iShares 파일은 링크의 '&'가 이스케이프 안 돼 있어 고친다."""
    text = re.sub(r"&(?!(?:amp|lt|gt|quot|apos|#\d+|#x[0-9a-fA-F]+);)", "&amp;", text)
    root = ET.fromstring(text)
    for ws in root.iter(f"{_SS}Worksheet"):
        if ws.get(f"{_SS}Name") != sheet:
            continue
        rows = []
        for r in ws.iter(f"{_SS}Row"):
            cells: list[str] = []
            for c in r.iter(f"{_SS}Cell"):
                idx = c.get(f"{_SS}Index")
                if idx:  # 빈 칸을 건너뛴 셀
                    cells += [""] * (int(idx) - 1 - len(cells))
                d = c.find(f"{_SS}Data")
                cells.append("".join(d.itertext()).strip() if d is not None else "")
            rows.append(cells)
        return rows
    raise ValueError(f"'{sheet}' 시트가 없음")


def read_ishares_holdings(path: Path) -> pd.DataFrame:
    """iShares 보유종목 파일(.xls = SpreadsheetML, 또는 .csv) → 'Ticker' 머리행 아래 표."""
    text = Path(path).read_text(encoding="utf-8-sig")
    rows = _spreadsheet_rows(text) if text.lstrip().startswith("<?xml") else list(csv.reader(io.StringIO(text)))
    head = next((i for i, r in enumerate(rows) if r and r[0].strip() == "Ticker"), None)
    if head is None:
        raise ValueError("'Ticker' 머리행을 못 찾음")
    cols = [c.strip() for c in rows[head]]
    body = [r + [""] * (len(cols) - len(r)) for r in rows[head + 1:] if len(r) >= 4]
    return pd.DataFrame([r[:len(cols)] for r in body], columns=cols)


def holdings_to_spec(h: pd.DataFrame) -> tuple[str, dict]:
    """보유종목 표 → Secret 문자열("티커:섹터코드,…", 비중 큰 순)과 단계별 개수.

    주식만, 권리·발행 전 거래(티커 뒤 두 글자 이상 꼬리: 'WI'·'RTWI')와 비상장(거래소 'NO MARKET'·'--')은 뺀다.
    """
    counts = {"보유 행": len(h)}
    eq = h[h["Asset Class"].str.strip() == "Equity"].copy()
    counts["주식"] = len(eq)
    tail = eq["Ticker"].str.strip().str.split().str[1:]
    odd = tail.map(lambda p: bool(p) and len(p[-1]) > 1)
    unlisted = eq["Exchange"].str.strip().str.upper().str.startswith("NO MARKET") | (eq["Exchange"].str.strip() == "--")
    counts["권리·발행 전·비상장 제외"] = int((odd | unlisted).sum())
    eq = eq[~(odd | unlisted)]
    eq["code"] = eq["Sector"].str.strip().map(ISHARES_SECTORS)
    counts["섹터 모름 제외"] = int(eq["code"].isna().sum())
    eq = eq[eq["code"].notna()]
    eq["w"] = pd.to_numeric(eq["Weight (%)"].str.replace(",", ""), errors="coerce").fillna(0.0)
    eq = eq.sort_values("w", ascending=False, kind="stable")
    counts["Secret에 넣을 종목"] = len(eq)
    return ",".join(f"{norm_ticker(t)}:{c}" for t, c in zip(eq["Ticker"], eq["code"])), counts
