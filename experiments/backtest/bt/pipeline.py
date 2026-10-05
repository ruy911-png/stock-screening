"""백테스트 실행 스크립트들이 같이 쓰는 준비 단계: 유니버스·일봉·SPY, 버핏 필터 마스크."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from . import backtest as btk
from .buffett import build_snapshots, daily_mask, evaluate
from .data import download_prices, load_universe
from .sec import DEFAULT_UA, SecBlocked, fetch_companyfacts

BENCH = "SPY"


@dataclass
class Market:
    uni: pd.DataFrame
    symbols: list[str]
    prices: dict[str, pd.DataFrame]
    failed: list[str]
    closes: pd.DataFrame
    splits: pd.DataFrame
    spy_fwd: pd.DataFrame


def load_market(cache: Path, price_start: str, limit: int = 0) -> Market:
    """S&P 500 현재 구성종목 중 금융 제외 + SPY 일봉."""
    uni = load_universe(cache)
    uni = uni[uni["sector"] != "Financials"]
    if limit:
        uni = uni.iloc[:limit]
    symbols = list(uni.index)
    prices, failed = download_prices(symbols + [BENCH], price_start, cache)
    if BENCH not in prices:
        raise SystemExit("SPY 일봉을 받지 못함 — 중단")
    spy = prices.pop(BENCH)["Close"]
    symbols = [s for s in symbols if s in prices]
    closes = pd.DataFrame({s: prices[s]["Close"] for s in symbols}).sort_index()
    splits = pd.DataFrame({s: prices[s]["Stock Splits"] for s in symbols}).reindex(closes.index)
    spy = spy.reindex(closes.index)
    spy_fwd = pd.DataFrame({h: btk.forward_returns(spy, h) for h in btk.HORIZONS})
    return Market(uni, symbols, prices, failed, closes, splits, spy_fwd)


def buffett_mask(m: Market, cache: Path, start: pd.Timestamp):
    """SEC 재무 → 월말 판정 → 거래일 마스크. 반환: (마스크 또는 None, 판정 기록, 미실행 사유 또는 None, 재무 없는 종목)."""
    ua = os.environ.get("SEC_USER_AGENT") or DEFAULT_UA
    rows, sec_missing, off = {}, [], None
    for s in m.symbols:
        try:
            r = fetch_companyfacts(int(m.uni.at[s, "cik"]), cache, ua)
        except SecBlocked as e:  # 정책 차단: 남은 종목도 같으므로 바로 멈춘다
            print(e)
            off = f"SEC가 접근을 막음 — {e}"
            break
        except RuntimeError as e:
            print(e)
            r = None
        if r is None or r.empty:
            sec_missing.append(s)
        else:
            rows[s] = r
    if off is None and len(sec_missing) > len(m.symbols) / 2:
        off = f"SEC 재무를 절반 넘게 못 받음({len(sec_missing)}/{len(m.symbols)})"
    if off is not None:
        return None, pd.DataFrame(), off, sec_missing
    snaps = {s: build_snapshots(r) for s, r in rows.items()}
    ckpts = pd.date_range(start - pd.offsets.MonthEnd(1), m.closes.index[-1], freq="ME")
    qual, records = evaluate(snaps, rows, m.uni["sector"], m.closes, m.splits, ckpts)
    mask = daily_mask(qual, m.closes.index).reindex(columns=m.symbols, fill_value=False)
    return mask, records, None, sec_missing
