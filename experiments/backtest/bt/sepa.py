"""SEPA Trend Template (코드 부분만) — docs/strategies/minervini-sepa.md §3.2.

종가 기준(장중 가격 미사용). 미정 수치(PRD Q20)는 PRD 참고값을 임시로 쓴다:
- 200일선 상승 = 오늘 MA200 > 22거래일(약 1개월) 전 MA200
- 52주 저점 대비 +30% 이상
- RS = IBD식 가중 수익률의 유니버스 내 백분위 ≥ 70
VCP·피벗·손절·R/R(LLM 판정 단계)은 이 테스트 범위 밖이다.
"""
from __future__ import annotations

import pandas as pd

from .indicators import rolling_high, rolling_low, rs_rating, rs_score, sma

MA200_RISING_DAYS = 22
LOW52_MIN_GAIN = 0.30
HIGH52_MAX_DROP = 0.25
RS_MIN = 70.0
YEAR = 252

CONDITIONS = {
    "c1": "종가 > MA50·MA150·MA200",
    "c2": "MA50 > MA150 > MA200",
    "c3": f"MA200 상승({MA200_RISING_DAYS}거래일 전 대비)",
    "c4": f"종가 ≥ 52주 저점 × {1 + LOW52_MIN_GAIN:.2f}",
    "c5": f"종가 ≥ 52주 고점 × {1 - HIGH52_MAX_DROP:.2f}",
    "c6": f"RS 백분위 ≥ {RS_MIN:.0f}",
}


def template_values(close: pd.Series) -> pd.DataFrame:
    """한 종목의 날짜별 Trend Template 수치(c1~c5). c6은 단면 비교라 따로 붙인다."""
    v = pd.DataFrame({"close": close})
    v["ma50"] = sma(close, 50)
    v["ma150"] = sma(close, 150)
    v["ma200"] = sma(close, 200)
    v["ma200_prev"] = v["ma200"].shift(MA200_RISING_DAYS)
    v["low52"] = rolling_low(close, YEAR)
    v["high52"] = rolling_high(close, YEAR)
    v["rs_score"] = rs_score(close)
    return v


def evaluate(v: pd.DataFrame) -> pd.DataFrame:
    """수치 → 조건 충족 여부. 수치가 결측이면 그 조건은 미충족(False)으로 둔다."""
    c = v["close"]
    out = pd.DataFrame(index=v.index)
    out["c1"] = (c > v["ma50"]) & (c > v["ma150"]) & (c > v["ma200"])
    out["c2"] = (v["ma50"] > v["ma150"]) & (v["ma150"] > v["ma200"])
    out["c3"] = v["ma200"] > v["ma200_prev"]
    out["c4"] = c >= v["low52"] * (1 + LOW52_MIN_GAIN)
    out["c5"] = c >= v["high52"] * (1 - HIGH52_MAX_DROP)
    out["c6"] = v["rs"] >= RS_MIN
    out["all"] = out[list(CONDITIONS)].all(axis=1)
    return out


def screen_asof(closes: pd.DataFrame, asof: pd.Timestamp) -> pd.DataFrame:
    """closes: index = 날짜, columns = 종목(분할 보정 종가). asof 기준 종목별 수치·충족 여부.

    asof에 종가가 없는 종목(마지막 일봉 ≠ 기준일)은 data_ok = False (명세 §7 검증 3).
    """
    rows = {}
    scores = {}
    for tkr in closes.columns:
        s = closes[tkr].dropna()
        s = s[s.index <= asof]
        if s.empty:
            continue
        v = template_values(s)
        scores[tkr] = v["rs_score"]
        rows[tkr] = v.iloc[-1].copy()
        rows[tkr]["last_date"] = s.index[-1]
    if not rows:
        return pd.DataFrame()
    table = pd.DataFrame(rows).T
    score_df = pd.DataFrame(scores)
    score_today = score_df.loc[[asof]] if asof in score_df.index else score_df.iloc[[0]] * float("nan")
    table["rs"] = rs_rating(score_today).iloc[0].reindex(table.index)
    table["data_ok"] = (table["last_date"] == asof) & table[["ma200_prev", "low52", "rs_score"]].notna().all(axis=1)
    for col in ["close", "ma50", "ma150", "ma200", "ma200_prev", "low52", "high52", "rs_score", "rs"]:
        table[col] = pd.to_numeric(table[col], errors="coerce")
    ev = evaluate(table)
    ev["all"] = ev["all"] & table["data_ok"]
    return table.join(ev)
