"""SEPA Trend Template — 지금 시세로 숫자 필터가 제대로 도는지 확인.

유니버스: S&P 500 현재 구성종목 전체 (미장 SEPA 유니버스 기준 PRD Q19 미정 → 임시).
결과는 스크리닝 결과(통계용)이며 매수·매도 권유가 아니다.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from bt.data import download_prices, load_universe, quality_flags  # noqa: E402
from bt.sepa import CONDITIONS, HIGH52_MAX_DROP, LOW52_MIN_GAIN, MA200_RISING_DAYS, screen_asof  # noqa: E402


def recompute_check(closes: pd.DataFrame, res: pd.DataFrame, asof: pd.Timestamp) -> list[str]:
    """통과 종목을 pandas 없이 다시 계산해 대조한다(자체 검산). RS는 단면 비교라 제외."""
    problems = []
    for t in res.index[res["all"].astype(bool)]:
        s = closes[t].dropna()
        s = [float(x) for x in s[s.index <= asof].to_numpy()]
        last = s[-1]
        ma = {n: sum(s[-n:]) / n for n in (50, 150, 200)}
        ma200_prev = sum(s[-200 - MA200_RISING_DAYS:-MA200_RISING_DAYS]) / 200
        lo, hi = min(s[-252:]), max(s[-252:])
        expect = {"ma50": ma[50], "ma150": ma[150], "ma200": ma[200], "ma200_prev": ma200_prev,
                  "low52": lo, "high52": hi, "close": last}
        for k, v in expect.items():
            if abs(v - float(res.at[t, k])) > 1e-6 * max(1.0, abs(v)):
                problems.append(f"{t}: {k} 불일치 (재계산 {v:.6f} / 표 {float(res.at[t, k]):.6f})")
        ok = (last > ma[50] and last > ma[150] and last > ma[200] and ma[50] > ma[150] > ma[200]
              and ma[200] > ma200_prev and last >= lo * (1 + LOW52_MIN_GAIN) and last >= hi * (1 - HIGH52_MAX_DROP))
        if not ok:
            problems.append(f"{t}: 재계산으로는 c1~c5 미충족")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="results")
    ap.add_argument("--cache", default=".cache")
    ap.add_argument("--limit", type=int, default=0, help="시험용: 앞 N종목만")
    args = ap.parse_args()
    out, cache = Path(args.out), Path(args.cache)
    out.mkdir(parents=True, exist_ok=True)

    uni = load_universe(cache)
    if args.limit:
        uni = uni.iloc[:args.limit]
    start = f"{pd.Timestamp.today().year - 2}-01-01"
    prices, failed = download_prices(list(uni.index), start, cache)
    closes = pd.DataFrame({s: df["Close"] for s, df in prices.items()}).sort_index()
    last_dates = pd.Series({s: df.index[-1] for s, df in prices.items()})
    asof = last_dates.mode().iloc[0]

    res = screen_asof(closes, asof)
    res = res.join(uni[["name", "sector"]])
    flags = {s: quality_flags(df[df.index >= asof - pd.DateOffset(years=1)]) for s, df in prices.items()}
    problems = recompute_check(closes, res, asof)

    ok = res["data_ok"].astype(bool)
    funnel = [("대상 종목(S&P 500)", len(uni)), ("일봉 받음", len(prices)), ("기준일 데이터 정상", int(ok.sum()))]
    cum = ok.copy()
    for k, label in CONDITIONS.items():
        cum = cum & res[k].astype(bool)
        funnel.append((f"+ {k} {label}", int(cum.sum())))
    single = [(f"{k} {label}", int((ok & res[k].astype(bool)).sum())) for k, label in CONDITIONS.items()]

    passed = res[res["all"].astype(bool)].copy()
    passed["vs_low52"] = passed["close"] / passed["low52"] - 1
    passed["vs_high52"] = passed["close"] / passed["high52"] - 1
    passed = passed.sort_values("rs", ascending=False)
    res.to_csv(out / "sepa_screen_all.csv")

    lines = [
        "# SEPA Trend Template 실행 확인 — 스크리닝 결과(통계용)",
        "",
        f"- 기준일(종가): **{asof:%Y-%m-%d}** · 유니버스: S&P 500 현재 구성종목 {len(uni)}개(임시, PRD Q19 미정)",
        f"- 데이터: 야후(yfinance) 분할 보정 종가 · 받지 못한 종목 {len(failed)}개{(': ' + ', '.join(failed)) if failed else ''}",
        "- 범위: 코드가 계산하는 Trend Template(명세 §3.2)만. VCP·피벗·손절·R/R(LLM 판정)과 펀더멘털은 제외",
        f"- 임시 수치(PRD Q20 미정): 200일선 상승 = {MA200_RISING_DAYS}거래일 전 대비, 52주 저점 +{LOW52_MIN_GAIN:.0%} 이상, "
        "RS = 0.4·3개월+0.2·6개월+0.2·9개월+0.2·12개월 수익률의 S&P 500 내 백분위 ≥ 70",
        "- 매수·매도 권유가 아니다.",
        "",
        "## 단계별 통과 수 (누적)",
        "| 단계 | 종목 수 |",
        "|---|---:|",
        *[f"| {a} | {b} |" for a, b in funnel],
        "",
        "## 조건별 단독 통과 수 (기준일 데이터 정상 종목 중)",
        "| 조건 | 종목 수 |",
        "|---|---:|",
        *[f"| {a} | {b} |" for a, b in single],
        "",
        f"## 모든 조건 통과 — {len(passed)}종목 (RS 순)",
        "| 종목 | 회사 | 섹터 | 종가 | 52주 저점 대비 | 52주 고점 대비 | RS |",
        "|---|---|---|---:|---:|---:|---:|",
        *[f"| {t} | {r['name']} | {r['sector']} | {r['close']:.2f} | {r['vs_low52']:+.1%} | {r['vs_high52']:+.1%} | {r['rs']:.0f} |"
          for t, r in passed.iterrows()],
        "",
        "## 자체 검산 (통과 종목을 pandas 없이 다시 계산해 대조)",
        f"- 결과: {'불일치 없음' if not problems else f'불일치 {len(problems)}건'}",
        *[f"  - {p}" for p in problems[:30]],
        "",
        "## 데이터 점검",
        f"- 기준일 데이터 없음(마지막 일봉 ≠ 기준일 또는 기간 부족): {int((~ok).sum())}종목"
        + (f" — {', '.join(res.index[~ok][:20])}" if (~ok).any() else ""),
        f"- 최근 1년 이상치 표시 종목: {sum(1 for v in flags.values() if v)}개",
        *[f"  - {s}: {'; '.join(v)}" for s, v in flags.items() if v][:20],
    ]
    (out / "sepa_screen.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
