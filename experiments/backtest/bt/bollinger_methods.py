"""볼린저 Method I~III 신호 (상승 방향만).

신호일 t는 t일 종가까지의 정보만 쓰고, 수익률 기준가는 t일 종가다.
명세: docs/strategies/bollinger.md §1.1·§2 (수치는 명세의 제안값).
Method III의 정량 규칙(W_TOL·W_MAX_DAYS·반등 기준)은 원전에 정량 정의가 없어 이 실험에서 정한 임시값이다.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .indicators import bollinger, mfi, sma

SQUEEZE_LOOKBACK = 125  # BandWidth 최저 비교 기간(약 6개월, 명세 제안)
WINDOW = 20             # 판정 창(명세 제안)
PCTB_MIN = 0.8          # Method II (2차 출처)
MFI_MIN = 80.0          # Method II (2차 출처)
W_REBOUND_PCTB = 0.5    # III: 첫 저점 뒤 반등이 중간 밴드(%b 0.5)까지 와야 함 (임시)
W_TOL = 0.03            # III: 둘째 저점 종가 ≤ 첫 저점 종가 × 1.03 (임시)
W_MAX_DAYS = 60         # III: 첫 저점부터 확인까지 최대 거래일 (임시)

METHODS = ("I", "II", "III", "I+II")


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """df: Open·High·Low·Close·Volume (분할 보정 일봉)."""
    out = df.join(bollinger(df["Close"]))
    out["mfi10"] = mfi(df["High"], df["Low"], df["Close"], df["Volume"], 10)
    out["sma200"] = sma(df["Close"], 200)
    return out


def _fresh(cond: pd.Series) -> pd.Series:
    """조건이 처음 참이 된 날만 (전일은 거짓)."""
    cond = cond.fillna(False).astype(bool)
    return cond & ~cond.shift(1, fill_value=False)


def squeeze_days(bw: pd.Series, lookback: int = SQUEEZE_LOOKBACK) -> pd.Series:
    """BandWidth가 그날까지 lookback 거래일 중 최저인 날."""
    rmin = bw.rolling(lookback, min_periods=lookback).min()
    return (bw <= rmin) & rmin.notna()


def method1(ind: pd.DataFrame) -> pd.Series:
    """I. 변동성 돌파: 직전 20거래일 안에 Squeeze일이 있고, 종가가 처음 UB 위로 마감한 날."""
    breakout = _fresh(ind["Close"] > ind["ub"])
    sq = squeeze_days(ind["bw"]).astype(float)
    recent_sq = sq.shift(1).rolling(WINDOW, min_periods=1).max() >= 1.0
    return breakout & recent_sq


def method2(ind: pd.DataFrame) -> pd.Series:
    """II. 추세 추종: %b > 0.8 그리고 MFI(10) > 80이 처음 함께 성립한 날."""
    return _fresh((ind["pctb"] > PCTB_MIN) & (ind["mfi10"] > MFI_MIN))


def _squeeze_then_breakout(sq: np.ndarray, above: np.ndarray, window: int) -> np.ndarray:
    """t 포함 최근 window 거래일 안에 Squeeze일 s와 그 뒤(s < u ≤ t) UB 위 종가 u가 있는가."""
    n = len(sq)
    out = np.zeros(n, dtype=bool)
    for t in range(n):
        seen_sq = False
        for u in range(max(0, t - window + 1), t + 1):
            if seen_sq and above[u]:
                out[t] = True
                break
            if sq[u]:
                seen_sq = True
    return out


def method12(ind: pd.DataFrame) -> pd.Series:
    """I+II (Q41 기본안): 창 안 Squeeze → 그 뒤 UB 위 종가 1번 이상 → 기준일 %b > 0.8·MFI(10) > 80. 처음 성립한 날."""
    sq = squeeze_days(ind["bw"]).to_numpy()
    above = (ind["Close"] > ind["ub"]).to_numpy()
    sb = pd.Series(_squeeze_then_breakout(sq, above, WINDOW), index=ind.index)
    return _fresh(sb & (ind["pctb"] > PCTB_MIN) & (ind["mfi10"] > MFI_MIN))


def method3(ind: pd.DataFrame, tol: float = W_TOL, max_days: int = W_MAX_DAYS,
            rebound_pctb: float = W_REBOUND_PCTB) -> pd.Series:
    """III. 반전(W-bottom) 단순화: 하단 밖 종가(첫 저점) → 중간 밴드까지 반등 →
    첫 저점 부근(≤ +tol)까지 되밀리되 밴드 안(둘째 저점) → 그 사이 최고 종가 H를 넘는 종가가 나온 날.

    거래량 지표(Intraday Intensity 등) 확인은 생략.
    """
    close = ind["Close"].to_numpy(float)
    pctb = ind["pctb"].to_numpy(float)
    sig = np.zeros(len(close), dtype=bool)
    phase, a, a_close, high, b_close = 0, -1, np.nan, np.nan, np.nan
    for t in range(len(close)):
        c, p = close[t], pctb[t]
        if np.isnan(c) or np.isnan(p):
            phase = 0
            continue
        if phase and t - a > max_days:
            phase = 0
        if phase == 0:
            if p < 0:
                phase, a, a_close = 1, t, c
        elif phase == 1:  # 첫 저점 뒤 반등 대기
            if p < 0:
                if c < a_close:
                    a, a_close = t, c
            elif p >= rebound_pctb:
                phase, high = 2, float(np.max(close[a:t + 1]))
        elif phase == 2:  # 반등 고점 추적 · 둘째 저점 대기
            if p < 0:
                phase, a, a_close = 1, t, c
            elif c > high:
                high = c
            elif c <= a_close * (1 + tol):
                phase, b_close = 3, c
        elif phase == 3:  # 둘째 저점 뒤 H 돌파 대기
            if p < 0:
                phase, a, a_close = 1, t, c
            elif c > high:
                sig[t] = True
                phase = 0
            elif c < b_close:
                b_close = c
    return pd.Series(sig, index=ind.index)


def signals(ind: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame({
        "I": method1(ind),
        "II": method2(ind),
        "III": method3(ind),
        "I+II": method12(ind),
    }, index=ind.index)
