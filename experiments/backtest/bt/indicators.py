"""공통 지표 — 일봉 기준, 코드만 계산.

정의 출처: docs/strategies/bollinger.md §2.1, docs/strategies/minervini-sepa.md §3.2.
결측은 NaN으로 두고 대체값을 넣지 않는다.
"""
from __future__ import annotations

import pandas as pd


def sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n, min_periods=n).mean()


def bollinger(close: pd.Series, n: int = 20, k: float = 2.0) -> pd.DataFrame:
    """MB = n일 단순평균, UB/LB = MB ± k·σ (σ = 모집단 표준편차, 명세 제안)."""
    mb = sma(close, n)
    sd = close.rolling(n, min_periods=n).std(ddof=0)
    ub = mb + k * sd
    lb = mb - k * sd
    width = ub - lb
    pctb = (close - lb) / width.where(width > 0)  # UB = LB면 결측
    bw = width / mb
    return pd.DataFrame({"mb": mb, "ub": ub, "lb": lb, "pctb": pctb, "bw": bw})


def mfi(high: pd.Series, low: pd.Series, close: pd.Series, volume: pd.Series, n: int = 10) -> pd.Series:
    """Money Flow Index. 전형가격이 전일보다 오른 날 = 양, 내린 날 = 음, 같으면 제외.

    음 합 = 0이면 100 (명세 제안). 첫 행은 전일 비교가 없어 결측.
    """
    tp = (high + low + close) / 3.0
    flow = tp * volume
    d = tp.diff()
    pos = flow.where(d > 0, 0.0).where(d.notna())
    neg = flow.where(d < 0, 0.0).where(d.notna())
    pos_sum = pos.rolling(n, min_periods=n).sum()
    neg_sum = neg.rolling(n, min_periods=n).sum()
    out = 100.0 - 100.0 / (1.0 + pos_sum / neg_sum.where(neg_sum != 0))
    out = out.where(neg_sum != 0, 100.0)
    return out.where(pos_sum.notna() & neg_sum.notna())


def roc(close: pd.Series, n: int) -> pd.Series:
    return close / close.shift(n) - 1.0


def rolling_high(close: pd.Series, n: int = 252) -> pd.Series:
    return close.rolling(n, min_periods=n).max()


def rolling_low(close: pd.Series, n: int = 252) -> pd.Series:
    return close.rolling(n, min_periods=n).min()


def rs_score(close: pd.Series) -> pd.Series:
    """IBD식 상대강도 근사 (임시값 — PRD Q20 미정): 0.4·3개월 + 0.2·6개월 + 0.2·9개월 + 0.2·12개월 수익률."""
    return 0.4 * roc(close, 63) + 0.2 * roc(close, 126) + 0.2 * roc(close, 189) + 0.2 * roc(close, 252)


def rs_rating(scores: pd.DataFrame) -> pd.DataFrame:
    """날짜별 단면 백분위 (0~100]. scores: index = 날짜, columns = 종목."""
    return scores.rank(axis=1, pct=True) * 100.0
