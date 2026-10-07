"""신호일 이후 수익률 집계 (이벤트 방식).

- 기준가 = 신호일 종가. 수익률 = h거래일 뒤 종가 ÷ 기준가 − 1 (분할 보정, 배당 미포함 — PRD Q14 미정)
- 같은 종목·같은 전략은 신호 뒤 COOLDOWN 거래일 동안 새 신호를 세지 않는다 (겹침 방지)
- 초과수익 = 같은 기간 SPY 수익률을 뺀 값
"""
from __future__ import annotations

import numpy as np
import pandas as pd

HORIZONS = (5, 10, 20)
COOLDOWN = 20


def forward_returns(close: pd.Series, h: int) -> pd.Series:
    return close.shift(-h) / close - 1.0


def apply_cooldown(sig: pd.Series, cooldown: int = COOLDOWN) -> pd.Series:
    arr = sig.fillna(False).to_numpy(bool)
    out = np.zeros(len(arr), dtype=bool)
    nxt = 0
    for i in np.flatnonzero(arr):
        if i >= nxt:
            out[i] = True
            nxt = i + cooldown
    return pd.Series(out, index=sig.index)


def events(ticker: str, close: pd.Series, sig: pd.Series, spy_fwd: pd.DataFrame, strategy: str,
           start: pd.Timestamp, last_entry: pd.Timestamp) -> pd.DataFrame:
    """신호(쿨다운 적용 전) → 이벤트 행. 기간 [start, last_entry] 밖 신호는 버린다."""
    sig = sig.reindex(close.index, fill_value=False)
    sig = sig & (close.index >= start) & (close.index <= last_entry)
    sig = apply_cooldown(sig)
    if not sig.any():
        return pd.DataFrame()
    days = close.index[sig.to_numpy()]
    out = pd.DataFrame({"strategy": strategy, "ticker": ticker, "date": days, "entry": close.loc[days].to_numpy()})
    for h in HORIZONS:
        r = forward_returns(close, h).loc[days].to_numpy()
        out[f"ret_{h}"] = r
        out[f"ex_{h}"] = r - spy_fwd[h].reindex(days).to_numpy()
    return out


def all_day_returns(closes: pd.DataFrame, mask: pd.DataFrame | None, spy_fwd: pd.DataFrame,
                    start: pd.Timestamp, last_entry: pd.Timestamp) -> dict[int, pd.DataFrame]:
    """기준선: 조건을 만족한 '모든 종목-날'의 h일 수익률·초과수익 (평균·중앙값·승률용)."""
    out = {}
    window = (closes.index >= start) & (closes.index <= last_entry)
    for h in HORIZONS:
        fwd = (closes.shift(-h) / closes - 1.0).loc[window]
        if mask is not None:
            fwd = fwd.where(mask.reindex(index=fwd.index, columns=fwd.columns, fill_value=False))
        ex = fwd.sub(spy_fwd[h].reindex(fwd.index), axis=0)
        out[h] = pd.DataFrame({"ret": fwd.stack(), "ex": ex.stack()}).dropna()
    return out


def summarize(ret: pd.Series, ex: pd.Series, dates: pd.Series | None = None) -> dict:
    ret, ex = ret.dropna(), ex.dropna()
    n = len(ret)
    if n == 0:
        return {"n": 0}
    return {
        "n": n,
        "n_dates": int(dates.nunique()) if dates is not None else None,
        "mean": float(ret.mean()),
        "median": float(ret.median()),
        "win": float((ret > 0).mean()),
        "ex_mean": float(ex.mean()),
        "ex_win": float((ex > 0).mean()),
        "se": float(ret.std(ddof=1) / np.sqrt(n)) if n > 1 else None,
    }


def stats_table(ev: pd.DataFrame, order: list[str]) -> pd.DataFrame:
    rows = []
    for strat in order:
        sub = ev[ev["strategy"] == strat]
        for h in HORIZONS:
            s = summarize(sub[f"ret_{h}"], sub[f"ex_{h}"], sub["date"]) if len(sub) else {"n": 0}
            rows.append({"strategy": strat, "h": h, **s})
    return pd.DataFrame(rows)


def yearly_table(ev: pd.DataFrame, order: list[str], h: int = 20) -> tuple[pd.DataFrame, pd.DataFrame]:
    """연도별 평균 수익률 표와 건수 표."""
    if ev.empty:
        return pd.DataFrame(), pd.DataFrame()
    ev = ev.assign(year=ev["date"].dt.year)
    mean = ev.pivot_table(index="year", columns="strategy", values=f"ret_{h}", aggfunc="mean")
    cnt = ev.pivot_table(index="year", columns="strategy", values=f"ret_{h}", aggfunc="count")
    cols = [c for c in order if c in mean.columns]
    return mean[cols], cnt[cols]
