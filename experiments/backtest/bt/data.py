"""유니버스(S&P 500 현재 구성종목)와 일봉(야후, yfinance) 불러오기 + 캐시.

- 구성종목: GitHub datasets/s-and-p-500-companies (GICS 섹터·CIK 포함). 현재 구성종목이라 생존편향이 있다.
- 일봉: 분할 보정 OHLCV(auto_adjust=False의 Close = 분할 보정·배당 미보정) + 분할 배수.
"""
from __future__ import annotations

import io
import time
from pathlib import Path

import pandas as pd

CONSTITUENTS_URL = "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/constituents.csv"
FIELDS = ["Open", "High", "Low", "Close", "Volume", "Stock Splits"]


def yahoo_symbol(symbol: str) -> str:
    return symbol.replace(".", "-")


def load_universe(cache_dir: Path) -> pd.DataFrame:
    cache = Path(cache_dir) / "constituents.csv"
    if cache.exists():
        text = cache.read_text()
    else:
        import requests

        resp = requests.get(CONSTITUENTS_URL, timeout=60)
        resp.raise_for_status()
        text = resp.text
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(text)
    df = pd.read_csv(io.StringIO(text))
    df = df.rename(columns={"Symbol": "symbol", "Security": "name", "GICS Sector": "sector",
                            "GICS Sub-Industry": "sub_industry", "CIK": "cik"})
    df["yahoo"] = df["symbol"].map(yahoo_symbol)
    return df[["symbol", "yahoo", "name", "sector", "sub_industry", "cik"]].set_index("symbol")


def _split_frame(raw: pd.DataFrame, ysym: str) -> pd.DataFrame | None:
    if isinstance(raw.columns, pd.MultiIndex):
        if ysym not in raw.columns.get_level_values(0):
            return None
        df = raw[ysym]
    else:
        df = raw
    if "Stock Splits" not in df:
        df = df.assign(**{"Stock Splits": 0.0})
    df = df[[c for c in FIELDS if c in df]].dropna(subset=["Close"])
    if df.empty:
        return None
    df.index = pd.DatetimeIndex(df.index).tz_localize(None).normalize()
    return df.astype(float)


def drop_unfinished_session(df: pd.DataFrame, now: pd.Timestamp | None = None) -> pd.DataFrame:
    """미국 장 마감(뉴욕 17시, 여유 포함) 전에 받은 '오늘' 행은 장중 가격이라 뺀다(종가 기준 원칙)."""
    now = now or pd.Timestamp.now(tz="America/New_York")
    if len(df) and df.index[-1].date() == now.date() and now.hour < 17:
        return df.iloc[:-1]
    return df


def download_prices(symbols: list[str], start: str, cache_dir: Path, chunk: int = 50,
                    pause: float = 2.0) -> tuple[dict[str, pd.DataFrame], list[str]]:
    """symbols(원 표기) → {symbol: 일봉}, 실패 목록. 캐시는 하루 단위로 새로 받는다.

    같은 날 다른 유니버스가 받아 둔 종목은 다시 쓰고, 없는 종목만 받아 캐시에 합친다.
    """
    import yfinance as yf

    cache = Path(cache_dir) / f"prices_{start}_{pd.Timestamp.today():%Y%m%d}.pkl"
    got: dict[str, pd.DataFrame] = pd.read_pickle(cache) if cache.exists() else {}
    todo = [s for s in symbols if s not in got]
    for i in range(0, len(todo), chunk):
        part = todo[i:i + chunk]
        ysyms = [yahoo_symbol(s) for s in part]
        raw = yf.download(ysyms, start=start, auto_adjust=False, actions=True, group_by="ticker",
                          threads=True, progress=False, multi_level_index=True)
        for s, y in zip(part, ysyms):
            df = _split_frame(raw, y) if raw is not None and not raw.empty else None
            if df is not None:
                got[s] = df
        time.sleep(pause)
    failed = [s for s in todo if s not in got]
    for s in list(failed):  # 하나씩 재시도
        try:
            raw = yf.Ticker(yahoo_symbol(s)).history(start=start, auto_adjust=False, actions=True)
            df = _split_frame(raw, yahoo_symbol(s))
            if df is not None:
                got[s] = df
                failed.remove(s)
        except Exception:  # noqa: BLE001 — 실패 종목은 목록으로 보고
            pass
        time.sleep(pause / 2)
    if todo:
        cache.parent.mkdir(parents=True, exist_ok=True)
        pd.to_pickle(got, cache)
    return {s: drop_unfinished_session(got[s]) for s in symbols if s in got}, failed


def quality_flags(df: pd.DataFrame) -> list[str]:
    """명백한 이상치 점검: 분할 없는 날의 종가 ±50% 초과 변동, 0 이하 가격."""
    flags = []
    ch = df["Close"].pct_change().abs()
    split_days = df["Stock Splits"].fillna(0) > 0
    big = ch[(ch > 0.5) & ~split_days]
    if len(big):
        flags.append(f"분할 없는 ±50% 변동 {len(big)}일 (첫날 {big.index[0]:%Y-%m-%d})")
    if (df[["Open", "High", "Low", "Close"]] <= 0).any().any():
        flags.append("0 이하 가격")
    return flags
