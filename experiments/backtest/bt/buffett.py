"""버핏 1차 필터(숫자, 코드 판단) — docs/strategies/buffett-moat.md §3, 시점 기준(point-in-time).

해자 판단(LLM)은 과거 시점으로 재현할 수 없어(모델이 이후 결과를 앎) 이 실험에서 뺀다.
이 실험의 근사·생략(README에도 기록):
- 명세의 'TTM 영업이익'·'현재 ROE' 조건은 생략하고 연간(10-K) 값만 쓴다
- 부채비율 = 총부채 ÷ 자기자본 (총부채 태그가 없으면 부채와자본총계 − 자기자본)
- 업종 중앙값 = 같은 유니버스의 GICS 섹터 중앙값 (현재 섹터 분류를 과거에도 그대로 적용)
- 1달러 테스트 = 5년 시가총액 증가 ≥ 최근 5개 회계연도 (순이익 − 배당) 합, 배당 태그가 없으면 0
- 오너 이익 근사 = 영업현금흐름 − 설비투자 (명세 제안)
- 시가총액 ≥ $10억 조건은 S&P 500 구성종목이라 생략
- 판정: 충족(True) / 미충족(False) / 미확인(None). 6개가 모두 충족일 때만 통과
"""
from __future__ import annotations

from bisect import bisect_right

import numpy as np
import pandas as pd

from .sec import annual_rows, latest_shares, pit

CRITERIA = {
    "b1": "영업이익 최근 7개 회계연도 모두 흑자",
    "b2": "ROE 최근 3개 회계연도 각각 > 15%",
    "b3": "부채비율(총부채÷자기자본) < 섹터 중앙값",
    "b4": "영업이익률·순이익률 > 섹터 중앙값",
    "b5": "1달러 테스트(5년 시가총액 증가 ≥ 5년 유보이익)",
    "b6": "FCF(영업현금흐름 − 설비투자) > 0",
}
ROE_MIN = 0.15
STALE_MONTHS = 15
YEAR_DAYS = 365.25


def _span_ok(ends: list, n: int) -> bool:
    """최근 n개 회계연도 말이 끊김 없이 이어지는가(간격 합 ≤ n − 0.5년)."""
    return len(ends) >= n and (ends[-1] - ends[-n]).days <= (n - 0.5) * YEAR_DAYS


def snapshot_metrics(ann: pd.DataFrame, asof: pd.Timestamp) -> dict:
    """asof 시점에 공개된 연간 값으로 계산한 지표(섹터 비교·시가총액 제외)."""
    ni = pit(ann, "net_income", asof)
    if ni.empty:
        return {"latest_end": None}
    ends = list(ni.index.sort_values())
    e = ends[-1]
    op, rev = pit(ann, "op_income", asof), pit(ann, "revenue", asof)
    eq, liab, le = pit(ann, "equity", asof), pit(ann, "liabilities", asof), pit(ann, "liab_and_equity", asof)
    ocf, capex, div = pit(ann, "ocf", asof), pit(ann, "capex", asof), pit(ann, "dividends", asof)
    m = {"latest_end": e}

    # b1 영업이익 7년 흑자
    if _span_ok(ends, 7) and all(x in op.index for x in ends[-7:]):
        m["b1"] = bool((op.loc[ends[-7:]] > 0).all())
    else:
        m["b1"] = None

    # b2 ROE 3년 (평균 자기자본, 직전 연도말 자본이 없으면 기말 자본)
    roes = []
    if _span_ok(ends, 3):
        for i in range(len(ends) - 3, len(ends)):
            end_eq = eq.get(ends[i])
            prev_eq = eq.get(ends[i - 1]) if i > 0 else None
            if end_eq is None or np.isnan(end_eq):
                roes = None
                break
            if end_eq <= 0:
                roes.append(-np.inf)  # 자본 음수 → ROE 의미 없음 → 미충족
                continue
            denom = (end_eq + prev_eq) / 2 if prev_eq is not None and prev_eq > 0 else end_eq
            roes.append(ni[ends[i]] / denom)
    else:
        roes = None
    m["roe3"] = roes
    m["b2"] = None if roes is None else bool(min(roes) > ROE_MIN)

    # b3·b4 재료 (섹터 중앙값은 체크포인트에서)
    equity = eq.get(e)
    total_liab = liab.get(e)
    if total_liab is None and le.get(e) is not None and equity is not None:
        total_liab = le.get(e) - equity
    m["neg_equity"] = equity is not None and equity <= 0
    m["de"] = total_liab / equity if total_liab is not None and equity is not None and equity > 0 else None
    revenue = rev.get(e)
    m["om"] = op.get(e) / revenue if revenue and revenue > 0 and op.get(e) is not None else None
    m["nm"] = ni[e] / revenue if revenue and revenue > 0 else None

    # b5 재료: 최근 5개 회계연도 (순이익 − 배당) 합
    m["retained5"] = float(sum(ni[x] - div.get(x, 0.0) for x in ends[-5:])) if _span_ok(ends, 5) else None

    # b6 FCF
    m["fcf"] = ocf.get(e) - capex.get(e) if ocf.get(e) is not None and capex.get(e) is not None else None
    m["b6"] = None if m["fcf"] is None else bool(m["fcf"] > 0)
    return m


def build_snapshots(rows: pd.DataFrame) -> tuple[list, list]:
    """10-K 계열 제출일마다 지표를 미리 계산 → (제출일 목록, 지표 목록)."""
    ann = annual_rows(rows)
    dates = sorted(pd.DatetimeIndex(ann["filed"].unique()))
    return dates, [snapshot_metrics(ann, d) for d in dates]


def cum_split_factor(splits: pd.Series) -> pd.Series:
    """날짜별 누적 분할 배수(그날까지 일어난 분할의 곱). splits: 분할일의 배수(그 외 0 또는 결측)."""
    s = splits.fillna(0.0)
    s = s.where(s > 0, 1.0)
    return s.cumprod()


def market_cap(rows: pd.DataFrame, close_adj: pd.Series, cum: pd.Series, d: pd.Timestamp):
    """d 시점 시가총액 = 그때 공개된 주식수 × 그날 종가(분할 기준을 맞춤). 없으면 None."""
    shares, ref = latest_shares(rows, d)
    if shares is None:
        return None
    i = close_adj.index.searchsorted(d, side="right") - 1
    if i < 0 or (d - close_adj.index[i]).days > 7:
        return None
    cum_end = float(cum.iloc[-1]) if len(cum) else 1.0
    j = cum.index.searchsorted(ref, side="right") - 1
    cum_ref = float(cum.iloc[j]) if j >= 0 else 1.0
    return shares * float(close_adj.iloc[i]) * cum_end / cum_ref


def evaluate(snapshots: dict, rows_by_tkr: dict, sectors: pd.Series, closes: pd.DataFrame,
             splits: pd.DataFrame, checkpoints: pd.DatetimeIndex) -> tuple[pd.DataFrame, pd.DataFrame]:
    """체크포인트별 통과 여부(표: 체크포인트 × 종목)와 조건별 판정 기록(긴 표)."""
    cums = {t: cum_split_factor(splits[t].dropna()) if t in splits else pd.Series(dtype=float) for t in snapshots}
    cls = {t: closes[t].dropna() for t in snapshots if t in closes}
    share_rows = {t: r[r["concept"].isin(["shares_out", "shares_diluted"])] for t, r in rows_by_tkr.items()}
    qual = {}
    records = []
    for c in checkpoints:
        cur = {}
        for t, (dates, metrics) in snapshots.items():
            i = bisect_right(dates, c)
            m = metrics[i - 1] if i else {"latest_end": None}
            if m.get("latest_end") is None or m["latest_end"] < c - pd.DateOffset(months=STALE_MONTHS):
                m = {"latest_end": None}
            cur[t] = m
        frame = pd.DataFrame({t: {k: m.get(k) for k in ("de", "om", "nm")} for t, m in cur.items()}).T
        frame = frame.apply(pd.to_numeric, errors="coerce")
        frame["sector"] = sectors.reindex(frame.index)
        med = frame.groupby("sector")[["de", "om", "nm"]].median()

        def median(sec, col):
            v = med.at[sec, col] if sec in med.index else np.nan
            return None if np.isnan(v) else float(v)

        row = {}
        for t, m in cur.items():
            st = {k: None for k in CRITERIA}
            if m["latest_end"] is not None:
                sec = sectors.get(t)
                st["b1"], st["b2"], st["b6"] = m.get("b1"), m.get("b2"), m.get("b6")
                if m.get("neg_equity"):
                    st["b3"] = False
                elif m.get("de") is not None and median(sec, "de") is not None:
                    st["b3"] = bool(m["de"] < median(sec, "de"))
                if None not in (m.get("om"), m.get("nm"), median(sec, "om"), median(sec, "nm")):
                    st["b4"] = bool(m["om"] > median(sec, "om") and m["nm"] > median(sec, "nm"))
                if m.get("retained5") is not None and t in cls:
                    now = market_cap(share_rows[t], cls[t], cums[t], c)
                    past = market_cap(share_rows[t], cls[t], cums[t], c - pd.DateOffset(years=5))
                    if now is not None and past is not None:
                        st["b5"] = bool(now - past >= m["retained5"])
            ok = all(v is True for v in st.values())
            row[t] = ok
            records.append({"checkpoint": c, "ticker": t, **st, "qualified": ok})
        qual[c] = row
    return pd.DataFrame(qual).T.sort_index(), pd.DataFrame(records)


def daily_mask(qual: pd.DataFrame, days: pd.DatetimeIndex) -> pd.DataFrame:
    """거래일 t의 통과 여부 = t보다 앞선 마지막 체크포인트의 판정 (당일 정보 누설 방지)."""
    shifted = qual.copy()
    shifted.index = shifted.index + pd.Timedelta(days=1)
    return shifted.reindex(days, method="ffill").fillna(False).astype(bool)
