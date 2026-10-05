"""버핏 숫자 필터 × 과매수·과매도 지표(RSI·스토캐스틱·윌리엄스 %R) 백테스트 — 사용자 요청(2026-10-05).

결과는 스크리닝 결과(통계용)이며 매수·매도 권유가 아니다. 지표 경계값·한계는 bt/oscillators.py·README.md.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from bt import backtest as btk  # noqa: E402
from bt.oscillators import SIGNALS, signals  # noqa: E402
from bt.pipeline import buffett_mask, load_market  # noqa: E402


def pct(x, digits=2, sign=True):
    if x is None or pd.isna(x):
        return "—"
    return f"{x * 100:+.{digits}f}%" if sign else f"{x * 100:.{digits}f}%"


def table(stats: pd.DataFrame, h: int) -> list[str]:
    sub = stats[stats["h"] == h]
    lines = ["| 전략 | 건수 | 신호일 수 | 평균 | 중앙값 | 상승 비율 | SPY 대비 평균 | SPY보다 나은 비율 | 표준오차 |",
             "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for _, r in sub.iterrows():
        if not r["n"]:
            lines.append(f"| {r['strategy']} | 0 | — | — | — | — | — | — | — |")
            continue
        nd = "—" if pd.isna(r.get("n_dates")) else int(r["n_dates"])
        lines.append(f"| {r['strategy']} | {int(r['n'])} | {nd} | {pct(r.get('mean'))} | {pct(r.get('median'))} | "
                     f"{pct(r.get('win'), 1, False)} | {pct(r.get('ex_mean'))} | {pct(r.get('ex_win'), 1, False)} | "
                     f"{pct(r.get('se'), 2, False)} |")
    return lines


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

    mk = load_market(cache, args.price_start, args.limit)
    start = pd.Timestamp(args.start)
    last_entry = mk.closes.index[-1 - max(btk.HORIZONS)]
    mask, _, buffett_off, sec_missing = buffett_mask(mk, cache, start)

    order = list(SIGNALS) + ([f"버핏+{k}" for k in SIGNALS] if mask is not None else [])
    evs = []
    for s in mk.symbols:
        df = mk.prices[s]
        sig = signals(df)
        for k in SIGNALS:
            evs.append(btk.events(s, df["Close"], sig[k], mk.spy_fwd, k, start, last_entry))
            if mask is not None:
                evs.append(btk.events(s, df["Close"], sig[k] & mask[s].reindex(df.index, fill_value=False),
                                      mk.spy_fwd, f"버핏+{k}", start, last_entry))
    ev = pd.concat([e for e in evs if len(e)], ignore_index=True)
    ev.to_csv(out / "oscillators_events.csv", index=False)
    stats = btk.stats_table(ev, order)

    bases = [("기준선: 유니버스 아무 날", None)] + ([("기준선: 버핏 통과 종목 아무 날", mask)] if mask is not None else [])
    base_rows = []
    for name, m in bases:
        allday = btk.all_day_returns(mk.closes, m, mk.spy_fwd, start, last_entry)
        base_rows += [{"strategy": name, "h": h, **btk.summarize(allday[h]["ret"], allday[h]["ex"])}
                      for h in btk.HORIZONS]
    win = (mk.spy_fwd.index >= start) & (mk.spy_fwd.index <= last_entry)
    base_rows += [{"strategy": "기준선: SPY 아무 날", "h": h,
                   **btk.summarize(mk.spy_fwd[h][win], mk.spy_fwd[h][win] * float("nan"))} for h in btk.HORIZONS]
    stats = pd.concat([stats, pd.DataFrame(base_rows)], ignore_index=True)
    stats.to_csv(out / "oscillators_stats.csv", index=False)

    prefix = "버핏+" if mask is not None else ""
    ranked = stats[(stats["h"] == 20) & stats["strategy"].isin([f"{prefix}{k}" for k in SIGNALS]) & (stats["n"] > 0)]
    ranked = ranked.sort_values("mean", ascending=False)
    ym, yn = btk.yearly_table(ev, [f"{prefix}{k}" for k in SIGNALS])

    lines = [
        "# 버핏 × 과매수·과매도(RSI·스토캐스틱·윌리엄스 %R) 백테스트 — 스크리닝 결과(통계용)",
        "",
        f"- 신호 기간: {start:%Y-%m-%d} ~ {last_entry:%Y-%m-%d} (마지막 일봉 {mk.closes.index[-1]:%Y-%m-%d})",
        f"- 유니버스: S&P 500 현재 구성종목 중 금융 제외 {len(mk.symbols)}종목 (일봉 못 받음 {len(mk.failed)})",
        (f"- **버핏 필터 미실행** — {buffett_off}. 아래는 지표 단독 결과만" if buffett_off else
         f"- 버핏 필터: 명세 §3 숫자 조건(해자 LLM 판단 제외), 그 시점 제출 10-K 값만, 월말 판정 → 다음 날부터 적용 · SEC 재무 없음 {len(sec_missing)}종목"),
        "- 지표(임시 경계값): RSI(14) 30/70 · 스토캐스틱(14,3,3) %K 20/80 · 윌리엄스 %R(14) −80/−20. 조건이 처음 성립한 날이 신호",
        "- 윌리엄스 %R(14) = 빠른 스토캐스틱 %K − 100 이라 스토캐스틱(느린 %K)과 결과가 비슷할 수 있다",
        "- (b)안 = PRD §9.1 제안(종가 > 200일선, 6개월 수익률 > 0, RSI(2) < 10) — 참고",
        "- 수익률: 신호일 종가 → 5·10·20거래일 뒤 종가(분할 보정, 배당 미포함), 같은 종목·전략 20거래일 쿨다운. 매수·매도 권유가 아니다",
        "",
        "## 20거래일 수익률", *table(stats, 20), "",
        "## 10거래일 수익률", *table(stats, 10), "",
        "## 5거래일 수익률", *table(stats, 5), "",
        f"## {'버핏+' if mask is not None else ''}지표 20거래일 평균 순위",
        *[f"{i + 1}. {r['strategy']}: 평균 {pct(r['mean'])}, 중앙값 {pct(r['median'])}, 건수 {int(r['n'])}, "
          f"SPY 대비 {pct(r['ex_mean'])}, 표준오차 {pct(r['se'], 2, False)}" for i, (_, r) in enumerate(ranked.iterrows())],
        "",
        f"## 연도별 20거래일 평균 수익률 — {'버핏+' if mask is not None else ''}지표 (괄호: 건수)",
    ]
    if len(ym):
        cols = list(ym.columns)
        lines += ["| 연도 | " + " | ".join(cols) + " |", "|---|" + "---:|" * len(cols)]
        for y in ym.index:
            cells = [f"{pct(ym.at[y, c], 1)} ({int(yn.at[y, c]) if not pd.isna(yn.at[y, c]) else 0})" for c in cols]
            lines.append(f"| {y} | " + " | ".join(cells) + " |")
    lines += ["", f"- 실행 시간 {time.time() - t0:.0f}초"]
    (out / "oscillators.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
