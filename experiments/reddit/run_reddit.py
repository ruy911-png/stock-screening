"""레딧(WSB) 반응 긍정 신호 백테스트 — 스크리닝 결과(통계용), 매수·매도 권유 아님.

입력: collect.py가 만든 연도별 종목·날짜 집계(data/wsb_ticker_day_*.csv)와 수집 기록(data/wsb_coverage_*.csv).
신호(임시값): 하루(UTC) 같은 종목 언급 글 MIN_POSTS개 이상이고
- 긍정: 평균 감성 ≥ +0.05 그리고 긍정 글 수 > 부정 글 수
- 부정: 평균 감성 ≤ −0.05 그리고 부정 글 수 > 긍정 글 수
- 언급 전체: 감성 무관
- 긍정+급증: 긍정이면서 언급 수 ≥ 직전 30일 평균의 SPIKE배
기준가 = 그 UTC 날짜 다음 거래일 종가(장 마감 뒤 글을 미리 보는 일 방지), 5·10·20거래일 뒤 종가까지 수익률.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "backtest"))

from bt import backtest as btk  # noqa: E402
from bt.data import download_prices, load_universe  # noqa: E402

MIN_POSTS = 3
SPIKE = 3.0
BENCH = "SPY"
# 종목 인식 오류로 확인된 티커(2026-10-05): DTE = Days To Expiration, PSA = 공지. 이미 모은 집계에서 통째로 뺀다
EXCLUDE_TICKERS = {"DTE", "PSA"}


def pct(x, digits=2, sign=True):
    if x is None or pd.isna(x):
        return "—"
    return f"{x * 100:+.{digits}f}%" if sign else f"{x * 100:.{digits}f}%"


def load(data_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    td = pd.concat([pd.read_csv(f) for f in sorted(data_dir.glob("wsb_ticker_day_*.csv"))], ignore_index=True)
    cov = pd.concat([pd.read_csv(f) for f in sorted(data_dir.glob("wsb_coverage_*.csv"))], ignore_index=True)
    td["date"] = pd.to_datetime(td["date"])
    cov["date"] = pd.to_datetime(cov["date"])
    return td, cov


def make_signals(td: pd.DataFrame) -> pd.DataFrame:
    """종목·날짜 집계 → 신호 표(날짜, 종목, 전략)."""
    td = td.sort_values(["ticker", "date"]).copy()
    td["mean"] = td["sent_sum"] / td["n"]
    # 직전 30일(달력일) 평균 언급 수 — 언급 없는 날은 0
    spikes = []
    for t, g in td.groupby("ticker"):
        s = g.set_index("date")["n"].asfreq("D", fill_value=0)
        prior = s.shift(1).rolling(30, min_periods=30).mean()
        spikes.append(pd.DataFrame({"ticker": t, "date": s.index, "prior30": prior.to_numpy()}))
    td = td.merge(pd.concat(spikes, ignore_index=True), on=["ticker", "date"], how="left")
    busy = td["n"] >= MIN_POSTS
    pos = busy & (td["mean"] >= 0.05) & (td["n_pos"] > td["n_neg"])
    neg = busy & (td["mean"] <= -0.05) & (td["n_neg"] > td["n_pos"])
    spike = pos & (td["n"] >= SPIKE * td["prior30"].clip(lower=1 / SPIKE))
    out = []
    for name, m in [("레딧 긍정", pos), ("레딧 긍정+급증", spike), ("레딧 부정", neg), ("레딧 언급 전체", busy)]:
        out.append(td.loc[m, ["date", "ticker"]].assign(strategy=name))
    return pd.concat(out, ignore_index=True)


def entry_mask(days: pd.DatetimeIndex, signal_dates: pd.Series) -> pd.Series:
    """UTC 날짜 D의 신호 → D 다음 첫 거래일에 True."""
    idx = days.searchsorted(pd.DatetimeIndex(signal_dates), side="right")
    idx = idx[idx < len(days)]
    mask = pd.Series(False, index=days)
    mask.iloc[idx] = True
    return mask


def baseline_days(days: pd.DatetimeIndex, cov: pd.DataFrame) -> pd.Series:
    """기준선에 넣을 거래일: 수집한(실패 아닌) UTC 날짜의 다음 거래일 — 신호가 나올 수 있는 날과 같은 범위(제외 연도는 빠진다)."""
    return entry_mask(days, cov.loc[cov["status"] != "실패", "date"])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data")
    ap.add_argument("--out", default="results")
    ap.add_argument("--cache", default=".cache")
    args = ap.parse_args()
    out, cache = Path(args.out), Path(args.cache)
    out.mkdir(parents=True, exist_ok=True)

    td, cov = load(Path(args.data))
    td = td[~td["ticker"].isin(EXCLUDE_TICKERS)]
    sig = make_signals(td)
    uni = load_universe(cache)
    tickers = sorted({s.replace(".", "-") for s in uni.index})
    prices, failed = download_prices(tickers + [BENCH], "2018-06-01", cache)
    if BENCH not in prices:
        raise SystemExit("SPY 일봉을 받지 못함 — 중단")
    spy = prices.pop(BENCH)["Close"]
    closes = pd.DataFrame({t: df["Close"] for t, df in prices.items()}).sort_index()
    spy = spy.reindex(closes.index)
    spy_fwd = pd.DataFrame({h: btk.forward_returns(spy, h) for h in btk.HORIZONS})
    days = closes.index
    start = max(pd.Timestamp("2019-01-01"), td["date"].min())
    last_entry = days[-1 - max(btk.HORIZONS)]

    order = ["레딧 긍정", "레딧 긍정+급증", "레딧 부정", "레딧 언급 전체"]
    evs = []
    for (strat, t), g in sig.groupby(["strategy", "ticker"]):
        if t not in closes:
            continue
        close = closes[t].dropna()
        mask = entry_mask(close.index, g["date"])
        evs.append(btk.events(t, close, mask, spy_fwd, strat, start, last_entry))
    ev = pd.concat([e for e in evs if len(e)], ignore_index=True)
    ev.to_csv(out / "reddit_events.csv", index=False)
    stats = btk.stats_table(ev, order)
    # 기준선도 신호와 같은 날짜 범위만(2026-10-05 수정: 전에는 수집에서 뺀 2021년이 기준선에 들어 있었다)
    ok_days = baseline_days(days, cov)
    day_mask = pd.DataFrame({t: ok_days for t in closes.columns}, index=days)
    allday = btk.all_day_returns(closes, day_mask, spy_fwd, start, last_entry)
    base = [{"strategy": "기준선: S&P 500 아무 날", "h": h, **btk.summarize(allday[h]["ret"], allday[h]["ex"])}
            for h in btk.HORIZONS]
    win = (spy_fwd.index >= start) & (spy_fwd.index <= last_entry) & ok_days.to_numpy()
    base += [{"strategy": "기준선: SPY 아무 날", "h": h,
              **btk.summarize(spy_fwd[h][win], spy_fwd[h][win] * float("nan"))} for h in btk.HORIZONS]
    stats = pd.concat([stats, pd.DataFrame(base)], ignore_index=True)
    stats.to_csv(out / "reddit_stats.csv", index=False)
    yearly_mean, yearly_n = btk.yearly_table(ev, order)

    cov["year"] = cov["date"].dt.year
    skipped = sorted(set(range(start.year, last_entry.year + 1)) - set(cov["year"]))
    cov_tab = cov.groupby("year").agg(days=("date", "count"), ok=("status", lambda s: (s == "성공").sum()),
                                      part=("status", lambda s: (s == "일부").sum()),
                                      fail=("status", lambda s: (s == "실패").sum()),
                                      posts=("posts", "sum"), with_ticker=("posts_with_ticker", "sum"))
    top = td.groupby("ticker")["n"].sum().sort_values(ascending=False).head(15)
    td.to_csv(out / "wsb_ticker_day.csv.gz", index=False)

    def table(h):
        sub = stats[stats["h"] == h]
        lines = ["| 전략 | 건수 | 신호일 수 | 평균 | 중앙값 | 상승 비율 | SPY 대비 평균 | SPY보다 나은 비율 | 표준오차 |",
                 "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
        for _, r in sub.iterrows():
            nd = "—" if pd.isna(r.get("n_dates")) else int(r["n_dates"])
            lines.append(f"| {r['strategy']} | {int(r['n'])} | {nd} | {pct(r.get('mean'))} | {pct(r.get('median'))} | "
                         f"{pct(r.get('win'), 1, False)} | {pct(r.get('ex_mean'))} | {pct(r.get('ex_win'), 1, False)} | "
                         f"{pct(r.get('se'), 2, False)} |")
        return lines

    lines = [
        "# 레딧(WSB) 반응 긍정 백테스트 — 스크리닝 결과(통계용)",
        "",
        f"- 레딧 데이터: Arctic Shift 아카이브의 r/wallstreetbets 게시물 제목, {cov['date'].min():%Y-%m-%d} ~ {cov['date'].max():%Y-%m-%d}",
        f"- 종목: S&P 500 현재 구성종목(캐시태그 또는 대문자 티커). 인식 오류로 뺀 티커: {', '.join(sorted(EXCLUDE_TICKERS))}. 일봉 못 받음 {len(failed)}",
        f"- 신호: 하루 언급 글 {MIN_POSTS}개 이상 + VADER(WSB 은어 추가) 평균 감성으로 긍정/부정, 긍정+급증 = 직전 30일 평균의 {SPIKE:.0f}배 이상",
        "- 기준가: 신호 날짜(UTC) 다음 거래일 종가 → 5·10·20거래일 뒤 종가(분할 보정, 배당 미포함). 같은 종목·전략 20거래일 쿨다운",
        f"- 집계 기간: {start:%Y-%m-%d} ~ {last_entry:%Y-%m-%d}. 매수·매도 권유가 아니다. 임시값·한계는 README.md",
        f"- 기준선: 수집한 날짜(실패한 날·수집 안 한 연도 {', '.join(map(str, skipped)) or '없음'} 제외)의 다음 거래일만 — 신호와 같은 날짜 범위"
        " (2026-10-05 수정: 전에는 기준선에 2021년이 들어 있었음)",
        "",
        "## 20거래일 수익률", *table(20), "",
        "## 10거래일 수익률", *table(10), "",
        "## 5거래일 수익률", *table(5), "",
        "## 연도별 20거래일 평균 수익률 (괄호: 건수)",
    ]
    if len(yearly_mean):
        cols = list(yearly_mean.columns)
        lines += ["| 연도 | " + " | ".join(cols) + " |", "|---|" + "---:|" * len(cols)]
        for y in yearly_mean.index:
            cells = [f"{pct(yearly_mean.at[y, c], 1)} ({int(yearly_n.at[y, c]) if not pd.isna(yearly_n.at[y, c]) else 0})"
                     for c in cols]
            lines.append(f"| {y} | " + " | ".join(cells) + " |")
    lines += [
        "",
        "## 레딧 수집 현황 (UTC 날짜 기준)",
        "| 연도 | 날짜 수 | 성공 | 일부 | 실패 | 게시물 | S&P 500 종목 언급 글 |",
        "|---|---:|---:|---:|---:|---:|---:|",
        *[f"| {y} | {r['days']} | {r['ok']} | {r['part']} | {r['fail']} | {r['posts']:,} | {r['with_ticker']:,} |"
          for y, r in cov_tab.iterrows()],
        "",
        "## 언급 글 수 상위 15종목 (전체 기간)",
        ", ".join(f"{t} {n:,}" for t, n in top.items()),
    ]
    (out / "reddit_backtest.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
