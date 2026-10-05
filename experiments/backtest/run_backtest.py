"""버핏 숫자 필터 × 볼린저 Method I·II·III 백테스트 (미장, S&P 500 현재 구성종목 중 금융 제외).

결과는 스크리닝 결과(통계용)이며 매수·매도 권유가 아니다. 임시값·한계는 README.md.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from bt import backtest as btk  # noqa: E402
from bt.bollinger_methods import METHODS, add_indicators, signals  # noqa: E402
from bt.buffett import CRITERIA, build_snapshots, daily_mask, evaluate  # noqa: E402
from bt.data import download_prices, load_universe  # noqa: E402
from bt.sec import DEFAULT_UA, fetch_companyfacts  # noqa: E402

BENCH = "SPY"


def pct(x, digits=2, sign=True):
    if x is None or pd.isna(x):
        return "—"
    return f"{x * 100:+.{digits}f}%" if sign else f"{x * 100:.{digits}f}%"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="results")
    ap.add_argument("--cache", default=".cache")
    ap.add_argument("--price-start", default="2010-01-01")
    ap.add_argument("--start", default="2016-01-01", help="신호 집계 시작일")
    ap.add_argument("--limit", type=int, default=0, help="시험용: 앞 N종목만")
    args = ap.parse_args()
    out, cache = Path(args.out), Path(args.cache)
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    uni = load_universe(cache)
    uni = uni[uni["sector"] != "Financials"]
    if args.limit:
        uni = uni.iloc[:args.limit]
    symbols = list(uni.index)

    prices, failed = download_prices(symbols + [BENCH], args.price_start, cache)
    if BENCH not in prices:
        raise SystemExit("SPY 일봉을 받지 못함 — 중단")
    spy = prices.pop(BENCH)["Close"]
    symbols = [s for s in symbols if s in prices]
    closes = pd.DataFrame({s: prices[s]["Close"] for s in symbols}).sort_index()
    splits = pd.DataFrame({s: prices[s]["Stock Splits"] for s in symbols}).reindex(closes.index)
    spy = spy.reindex(closes.index)
    spy_fwd = pd.DataFrame({h: btk.forward_returns(spy, h) for h in btk.HORIZONS})

    # 기간: 신호는 [start, 마지막 거래일 − 20거래일]
    start = pd.Timestamp(args.start)
    last_entry = closes.index[-1 - max(btk.HORIZONS)]

    # 버핏: SEC 재무 → 제출일별 지표 → 월말 체크포인트 판정 → 거래일 마스크
    ua = os.environ.get("SEC_USER_AGENT") or DEFAULT_UA
    rows, sec_missing = {}, []
    for s in symbols:
        try:
            r = fetch_companyfacts(int(uni.at[s, "cik"]), cache, ua)
        except RuntimeError as e:
            print(e)
            r = None
        if r is None or r.empty:
            sec_missing.append(s)
        else:
            rows[s] = r
    if len(sec_missing) > len(symbols) / 2:
        raise SystemExit(f"SEC 재무를 절반 넘게 못 받음({len(sec_missing)}/{len(symbols)}) — User-Agent 차단 가능성. 중단")
    snaps = {s: build_snapshots(r) for s, r in rows.items()}
    ckpts = pd.date_range(start - pd.offsets.MonthEnd(1), closes.index[-1], freq="ME")
    qual, records = evaluate(snaps, rows, uni["sector"], closes, splits, ckpts)
    mask = daily_mask(qual, closes.index).reindex(columns=symbols, fill_value=False)

    # 볼린저 신호 → 이벤트
    order = [f"BB-{m}" for m in METHODS] + [f"버핏+BB-{m}" for m in METHODS]
    evs = []
    for s in symbols:
        ind = add_indicators(prices[s][["Open", "High", "Low", "Close", "Volume"]])
        sig = signals(ind)
        for m in METHODS:
            evs.append(btk.events(s, ind["Close"], sig[m], spy_fwd, f"BB-{m}", start, last_entry))
            evs.append(btk.events(s, ind["Close"], sig[m] & mask[s].reindex(ind.index, fill_value=False),
                                  spy_fwd, f"버핏+BB-{m}", start, last_entry))
    ev = pd.concat([e for e in evs if len(e)], ignore_index=True)
    ev.to_csv(out / "backtest_events.csv", index=False)
    stats = btk.stats_table(ev, order)

    # 기준선: 아무 날이나 (유니버스 전체 / 버핏 통과 종목 / SPY)
    base_rows = []
    for name, m in [("기준선: 유니버스 아무 날", None), ("기준선: 버핏 통과 종목 아무 날", mask)]:
        allday = btk.all_day_returns(closes, m, spy_fwd, start, last_entry)
        for h in btk.HORIZONS:
            base_rows.append({"strategy": name, "h": h, **btk.summarize(allday[h]["ret"], allday[h]["ex"])})
    win = (spy_fwd.index >= start) & (spy_fwd.index <= last_entry)
    for h in btk.HORIZONS:
        r = spy_fwd[h][win]
        base_rows.append({"strategy": "기준선: SPY 아무 날", "h": h, **btk.summarize(r, r * float("nan"))})
    stats = pd.concat([stats, pd.DataFrame(base_rows)], ignore_index=True)
    stats.to_csv(out / "backtest_stats.csv", index=False)
    yearly_mean, yearly_n = btk.yearly_table(ev, order)

    # 버핏 필터 진단: 연도별 평균 통과 종목 수, 조건별 미확인 비율
    rec = records.copy()
    rec["year"] = pd.to_datetime(rec["checkpoint"]).dt.year
    qual_by_year = rec.groupby("year")["qualified"].sum() / rec.groupby("year")["checkpoint"].nunique()
    unknown = {k: float(rec[k].isna().mean()) for k in CRITERIA}
    passed_share = {k: float((rec[k] == True).mean()) for k in CRITERIA}  # noqa: E712
    rec.to_csv(out / "buffett_checkpoints.csv", index=False)

    h_main = 20
    main_rows = stats[stats["h"] == h_main]
    best = main_rows[main_rows["strategy"].isin([f"버핏+BB-{m}" for m in ("I", "II", "III")])]
    best = best[best["n"] > 0].sort_values("mean", ascending=False)

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
        "# 버핏 × 볼린저 Method I·II·III 백테스트 — 스크리닝 결과(통계용)",
        "",
        f"- 신호 기간: {start:%Y-%m-%d} ~ {last_entry:%Y-%m-%d} (마지막 일봉 {closes.index[-1]:%Y-%m-%d})",
        f"- 유니버스: S&P 500 현재 구성종목 중 금융 제외 {len(symbols)}종목 (일봉 못 받음 {len(failed)}: {', '.join(failed) or '없음'})",
        f"- SEC 재무 없음 {len(sec_missing)}종목: {', '.join(sec_missing) or '없음'} → 버핏 필터 미통과로 처리",
        "- 수익률: 신호일 종가 → 5·10·20거래일 뒤 종가 (분할 보정, 배당 미포함). 같은 종목·전략은 신호 뒤 20거래일 동안 새 신호 안 셈",
        "- 버핏 필터: 명세 §3의 숫자 조건(해자 LLM 판단 제외), 그 시점에 제출된 10-K 값만 사용, 월말 판정 → 다음 날부터 적용",
        "- 볼린저: I 변동성 돌파 · II 추세 추종(%b>0.8·MFI(10)>80) · III 반전(W-bottom 단순화) · I+II(Q41 기본안, 참고)",
        "- 매수·매도 권유가 아니다. 임시값·한계는 README.md",
        "",
        f"## {h_main}거래일 수익률",
        *table(h_main),
        "",
        "## 10거래일 수익률",
        *table(10),
        "",
        "## 5거래일 수익률",
        *table(5),
        "",
        f"## 버핏+볼린저 {h_main}거래일 평균 순위 (I·II·III)",
        *[f"{i + 1}. {r['strategy']}: 평균 {pct(r['mean'])}, 중앙값 {pct(r['median'])}, 건수 {int(r['n'])}, "
          f"SPY 대비 {pct(r['ex_mean'])}" for i, (_, r) in enumerate(best.iterrows())],
        "",
        f"## 연도별 {h_main}거래일 평균 수익률 (괄호: 건수)",
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
        "## 버핏 필터 진단",
        "| 연도 | 월말 평균 통과 종목 수 |",
        "|---|---:|",
        *[f"| {y} | {v:.1f} |" for y, v in qual_by_year.items()],
        "",
        "| 조건 | 충족 비율 | 미확인 비율 |",
        "|---|---:|---:|",
        *[f"| {k} {label} | {passed_share[k]:.1%} | {unknown[k]:.1%} |" for k, label in CRITERIA.items()],
        "",
        f"- 실행 시간 {time.time() - t0:.0f}초",
    ]
    (out / "backtest.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
