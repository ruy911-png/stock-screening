"""주봉 스토캐스틱 슬로우(15,5,5) + 윌리엄스 %R 동시 과매도 진입 — 재현 시험.

사용자 참고 자료(2026-10-05, 영상 요약): "스토캐스틱 슬로우와 윌리엄스 %R이 동시에 극단적 과매도일 때만 분할 매수,
주봉에서, 지수·초대형주에서. 2010~2022 S&P 500 기준 13년간 8번 진입 7승 1패, 손실 시 최대 −0.31%".
요약에 없는 값(%R 기간, 과매도 기준값, 승패 판정 기간)은 여러 값으로 함께 돌린다(임시값).
결과는 스크리닝 결과(통계용)이며 매수·매도 권유가 아니다.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backtest"))

from bt.oscillators import stochastic, williams_r  # noqa: E402

TICKERS = {
    "^GSPC": "S&P 500 지수", "^KS200": "KOSPI 200 지수", "005930.KS": "삼성전자", "000660.KS": "SK하이닉스",
    "AAPL": "Apple", "MSFT": "Microsoft", "NVDA": "NVIDIA", "AMZN": "Amazon", "GOOGL": "Alphabet",
    "META": "Meta", "AVGO": "Broadcom", "TSLA": "Tesla", "BRK-B": "Berkshire", "JPM": "JPMorgan",
}
WR_PERIODS = (14, 21, 28)
LEVELS = ((20.0, -80.0), (10.0, -90.0))   # (스토캐스틱 %K 미만, 윌리엄스 %R 미만)
HORIZONS = (4, 8, 13, 26)                 # 주
COOLDOWN = 13                             # 같은 종목은 13주 안에 다시 세지 않음
PERIODS = {"2010~2022(영상 기간)": ("2010-01-01", "2022-12-31"), "2023~(이후)": ("2023-01-01", "2100-01-01")}


def to_weekly(df: pd.DataFrame) -> pd.DataFrame:
    """일봉 → 금요일 마감 주봉. 마지막 주가 아직 안 끝났으면 뺀다."""
    w = df.resample("W-FRI").agg({"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"})
    w = w.dropna(subset=["Close"])
    if len(df) and w.index[-1] > df.index[-1].normalize() and df.index[-1].dayofweek < 4:
        w = w.iloc[:-1]
    return w


def entries(w: pd.DataFrame, wr_n: int, k_th: float, wr_th: float) -> pd.DatetimeIndex:
    k = stochastic(w["High"], w["Low"], w["Close"], k=15, smooth=5, d=5)["k"]
    wr = williams_r(w["High"], w["Low"], w["Close"], n=wr_n)
    cond = ((k < k_th) & (wr < wr_th)).fillna(False).to_numpy()
    out, nxt = [], 0
    for i in range(len(cond)):
        if cond[i] and (i == 0 or not cond[i - 1]) and i >= nxt:
            out.append(w.index[i])
            nxt = i + COOLDOWN
    return pd.DatetimeIndex(out)


def fwd(w: pd.DataFrame, h: int) -> pd.Series:
    return w["Close"].shift(-h) / w["Close"] - 1.0


def load(cache: Path) -> dict[str, pd.DataFrame]:
    import yfinance as yf

    f = cache / f"weekly_src_{pd.Timestamp.today():%Y%m%d}.pkl"
    if f.exists():
        return pd.read_pickle(f)
    got = {}
    for t in TICKERS:
        df = yf.Ticker(t).history(start="2005-01-01", auto_adjust=False)
        if df is not None and not df.empty:
            df.index = pd.DatetimeIndex(df.index).tz_localize(None).normalize()
            got[t] = df[["Open", "High", "Low", "Close", "Volume"]].astype(float)
        time.sleep(1.0)
    cache.mkdir(parents=True, exist_ok=True)
    pd.to_pickle(got, f)
    return got


def pct(x):
    return "—" if x is None or pd.isna(x) else f"{x * 100:+.1f}%"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="results")
    ap.add_argument("--cache", default=".cache")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    data = load(Path(a.cache))
    rows, dates = [], {}
    for t, df in data.items():
        w = to_weekly(df)
        f = {h: fwd(w, h) for h in HORIZONS}
        for pname, (p0, p1) in PERIODS.items():
            in_p = (w.index >= p0) & (w.index <= p1)
            base = f[13][in_p].dropna()
            rows.append({"ticker": t, "period": pname, "variant": "기준선: 아무 주", "n": len(base),
                         **{f"win{h}": float((f[h][in_p].dropna() > 0).mean()) for h in HORIZONS},
                         "mean13": float(base.mean()), "worst13": float(base.min())})
            for wr_n in WR_PERIODS:
                for k_th, wr_th in LEVELS:
                    e = entries(w, wr_n, k_th, wr_th)
                    e = e[(e >= p0) & (e <= p1)]
                    var = f"%R({wr_n}) · %K<{k_th:.0f} & %R<{wr_th:.0f}"
                    r13 = f[13].reindex(e).dropna()
                    rows.append({"ticker": t, "period": pname, "variant": var, "n": len(e),
                                 **{f"win{h}": float((f[h].reindex(e).dropna() > 0).mean()) if len(e) else None
                                    for h in HORIZONS},
                                 "mean13": float(r13.mean()) if len(r13) else None,
                                 "worst13": float(r13.min()) if len(r13) else None})
                    if t == "^GSPC":
                        dates[(pname, var)] = [(d, f[13].get(d)) for d in e]
    res = pd.DataFrame(rows)
    res.to_csv(out / "weekly_osc.csv", index=False)

    def tab(sub):
        lines = ["| 조건 | 진입 수 | 4주 승률 | 8주 승률 | 13주 승률 | 26주 승률 | 13주 평균 | 13주 최악 |",
                 "|---|---:|---:|---:|---:|---:|---:|---:|"]
        for _, r in sub.iterrows():
            lines.append(f"| {r['variant']} | {r['n']} | " + " | ".join(
                "—" if r[f"win{h}"] is None or pd.isna(r[f"win{h}"]) else f"{r[f'win{h}']:.0%}" for h in HORIZONS)
                + f" | {pct(r['mean13'])} | {pct(r['worst13'])} |")
        return lines

    lines = ["# 주봉 스토캐스틱(15,5,5) + 윌리엄스 %R 동시 과매도 — 재현 시험 (스크리닝 결과, 통계용)", "",
             "- 영상 요약의 주장: 2010~2022 S&P 500, 13년간 8번 진입 7승 1패(87.5%), 손실 시 최대 −0.31%",
             "- 요약에 없는 값은 여러 값으로 함께 돌림: 윌리엄스 %R 기간 14·21·28주, 과매도 기준 (%K<20 & %R<−80) / (%K<10 & %R<−90)",
             f"- 진입 = 두 조건이 동시에 처음 성립한 주의 종가(금요일), 같은 종목 {COOLDOWN}주 안 재진입 안 셈. 승 = n주 뒤 종가가 진입가보다 높음",
             "- 분할 매수·손절은 모형에 없음. 수익률은 가격만(배당 미포함). 매수·매도 권유가 아니다", ""]
    for pname in PERIODS:
        lines += [f"## S&P 500 지수 — {pname}", *tab(res[(res.ticker == "^GSPC") & (res.period == pname)]), ""]
    lines += ["## S&P 500 지수 진입 주(13주 뒤 수익률)"]
    for (pname, var), ds in dates.items():
        if ds:
            lines.append(f"- {pname} · {var}: " + ", ".join(f"{d:%Y-%m-%d}({pct(r)})" for d, r in ds))
    lines += ["", "## 전체 종목 — 기준선 대비 13주 승률 (조건: %R(14) · %K<20 & %R<−80 / %R(28) · %K<10 & %R<−90)",
              "| 종목 | 기간 | 아무 주 13주 승률 | 조건① 진입·13주 승률 | 조건② 진입·13주 승률 |", "|---|---|---:|---:|---:|"]
    v1, v2 = "%R(14) · %K<20 & %R<-80", "%R(28) · %K<10 & %R<-90"
    for t, name in TICKERS.items():
        for pname in PERIODS:
            sub = res[(res.ticker == t) & (res.period == pname)].set_index("variant")
            if sub.empty:
                continue
            b = sub.loc["기준선: 아무 주"]
            c1 = sub.loc[v1] if v1 in sub.index else None
            c2 = sub.loc[v2] if v2 in sub.index else None
            fmt = lambda c: "—" if c is None or not c["n"] else f"{int(c['n'])}번 · {c['win13']:.0%}"  # noqa: E731
            lines.append(f"| {name}({t}) | {pname} | {b['win13']:.0%} | {fmt(c1)} | {fmt(c2)} |")
    lines += ["", f"- 받은 종목 {len(data)}/{len(TICKERS)}: 없음 → {', '.join(t for t in TICKERS if t not in data) or '없음'}"]
    (out / "weekly_osc.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
