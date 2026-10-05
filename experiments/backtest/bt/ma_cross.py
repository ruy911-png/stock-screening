"""이동평균선 골든크로스(+ 거래량) 신호 — 사용자 요청(2026-10-05): "버핏과 이평선 골드크로스는? 거래량까지 고려".

골든크로스 = 짧은 이동평균이 긴 이동평균을 아래에서 위로 넘은 날(전날 짧은 ≤ 긴, 오늘 짧은 > 긴).
거래량 확인 = 그날 거래량 ≥ 직전 20거래일 평균 거래량 × VOL_MULT (임시값).
"""
from __future__ import annotations

import pandas as pd

from .indicators import sma

PAIRS = [(5, 20), (20, 60), (50, 200)]  # 단기 · 국내에서 흔한 조합 · 미국식 골든크로스
VOL_WINDOW, VOL_MULT = 20, 1.5
MA_CROSS = [name for a, b in PAIRS for name in (f"골든크로스 {a}/{b}", f"골든크로스 {a}/{b} + 거래량")]


def volume_surge(volume: pd.Series, window: int = VOL_WINDOW, mult: float = VOL_MULT) -> pd.Series:
    prior = volume.shift(1).rolling(window, min_periods=window).mean()
    return (volume >= mult * prior).fillna(False)


def golden_cross(close: pd.Series, short: int, long: int) -> pd.Series:
    s, lo = sma(close, short), sma(close, long)
    return ((s.shift(1) <= lo.shift(1)) & (s > lo)).fillna(False)


def signals(df: pd.DataFrame) -> pd.DataFrame:
    """df: Close·Volume. 이름별 신호(bool)."""
    vol = volume_surge(df["Volume"])
    out = {}
    for a, b in PAIRS:
        gc = golden_cross(df["Close"], a, b)
        out[f"골든크로스 {a}/{b}"] = gc
        out[f"골든크로스 {a}/{b} + 거래량"] = gc & vol
    return pd.DataFrame(out, index=df.index).astype(bool)
