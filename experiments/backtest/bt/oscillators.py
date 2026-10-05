"""과매수·과매도 지표 — RSI(Wilder), 스토캐스틱(slow), 윌리엄스 %R. 일봉, 코드만 계산.

경계값은 흔히 쓰는 관행값을 임시로 쓴다(사용자 요청 2026-10-05, 출처: 각 지표의 통상 기준):
RSI(14) 30/70 · 스토캐스틱(14,3,3) %K 20/80 · 윌리엄스 %R(14) −80/−20.
윌리엄스 %R(n) = 빠른 스토캐스틱 %K(n) − 100 이므로 스토캐스틱과 결과가 비슷할 수 있다.
참고 신호 (b)안은 PRD §9.1 제안(종가 > 200일선, 6개월 수익률 > 0, RSI(2) < 10).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .bollinger_methods import _fresh
from .indicators import roc, sma

RSI_LOW, RSI_HIGH = 30.0, 70.0
STOCH_LOW, STOCH_HIGH = 20.0, 80.0
WR_LOW, WR_HIGH = -80.0, -20.0


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    """Wilder RSI: 첫 평균은 n개 변화의 단순평균, 이후 (이전×(n−1) + 오늘) ÷ n."""
    c = close.to_numpy(float)
    out = np.full(len(c), np.nan)
    if len(c) <= n:
        return pd.Series(out, index=close.index)
    d = np.diff(c)
    gain, loss = np.where(d > 0, d, 0.0), np.where(d < 0, -d, 0.0)
    ag, al = gain[:n].mean(), loss[:n].mean()

    def value(g, lo):
        if lo == 0:
            return 50.0 if g == 0 else 100.0
        return 100.0 - 100.0 / (1.0 + g / lo)

    out[n] = value(ag, al)
    for i in range(n + 1, len(c)):
        ag = (ag * (n - 1) + gain[i - 1]) / n
        al = (al * (n - 1) + loss[i - 1]) / n
        out[i] = value(ag, al)
    return pd.Series(out, index=close.index)


def stochastic(high: pd.Series, low: pd.Series, close: pd.Series, k: int = 14, smooth: int = 3,
               d: int = 3) -> pd.DataFrame:
    """느린 스토캐스틱: 빠른 %K = (종가 − n일 최저) ÷ (n일 최고 − n일 최저) × 100, %K = 그 3일 평균, %D = %K 3일 평균."""
    ll = low.rolling(k, min_periods=k).min()
    hh = high.rolling(k, min_periods=k).max()
    rng = hh - ll
    fast = 100.0 * (close - ll) / rng.where(rng > 0)
    slow_k = fast.rolling(smooth, min_periods=smooth).mean()
    return pd.DataFrame({"fast_k": fast, "k": slow_k, "d": slow_k.rolling(d, min_periods=d).mean()})


def williams_r(high: pd.Series, low: pd.Series, close: pd.Series, n: int = 14) -> pd.Series:
    """윌리엄스 %R = (n일 최고 − 종가) ÷ (n일 최고 − n일 최저) × −100 (0 ~ −100)."""
    ll = low.rolling(n, min_periods=n).min()
    hh = high.rolling(n, min_periods=n).max()
    rng = hh - ll
    return -100.0 * (hh - close) / rng.where(rng > 0)


SIGNALS = ["RSI<30", "스토캐스틱<20", "윌리엄스%R<−80", "과매도 3개 동시",
           "RSI>70", "스토캐스틱>80", "윌리엄스%R>−20", "(b)안 200일선·6개월↑·RSI(2)<10"]


def signals(df: pd.DataFrame) -> pd.DataFrame:
    """df: High·Low·Close. 각 조건이 처음 성립한 날만 True."""
    h, lo, c = df["High"], df["Low"], df["Close"]
    r14, r2 = rsi(c, 14), rsi(c, 2)
    st = stochastic(h, lo, c)["k"]
    wr = williams_r(h, lo, c)
    conds = {
        "RSI<30": r14 < RSI_LOW,
        "스토캐스틱<20": st < STOCH_LOW,
        "윌리엄스%R<−80": wr < WR_LOW,
        "과매도 3개 동시": (r14 < RSI_LOW) & (st < STOCH_LOW) & (wr < WR_LOW),
        "RSI>70": r14 > RSI_HIGH,
        "스토캐스틱>80": st > STOCH_HIGH,
        "윌리엄스%R>−20": wr > WR_HIGH,
        "(b)안 200일선·6개월↑·RSI(2)<10": (c > sma(c, 200)) & (roc(c, 126) > 0) & (r2 < 10),
    }
    return pd.DataFrame({k: _fresh(v) for k, v in conds.items()}, index=df.index)
