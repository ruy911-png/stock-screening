"""과매도 매수 진입 변형 백테스트 (버핏 필터 유무) — 사용자 요청(2026-10-05): "과매도에 사야 되는 거 아냐? 테스트임".

결과는 스크리닝 결과(통계용)이며 매수·매도 권유가 아니다. 신호 정의는 bt/oscillators.py의 oversold_signals.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from bt import backtest as btk  # noqa: E402
from bt.indicators import sma  # noqa: E402
from bt.oscillators import OVERSOLD, oversold_signals  # noqa: E402
from bt.pipeline import buffett_mask, load_market  # noqa: E402
from run_oscillators import pct, table  # noqa: E402


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
    market_up = (mk.spy > sma(mk.spy, 200)).fillna(False)
    mask, _, buffett_off, _ = buffett_mask(mk, cache, start)

    order = list(OVERSOLD) + ([f"버핏+{k}" for k in OVERSOLD] if mask is not None else [])
    evs = []
    for s in mk.symbols:
        df = mk.prices[s]
        sig = oversold_signals(df, market_up)
        for k in OVERSOLD:
            evs.append(btk.events(s, df["Close"], sig[k], mk.spy_fwd, k, start, last_entry))
            if mask is not None:
                evs.append(btk.events(s, df["Close"], sig[k] & mask[s].reindex(df.index, fill_value=False),
                                      mk.spy_fwd, f"버핏+{k}", start, last_entry))
    ev = pd.concat([e for e in evs if len(e)], ignore_index=True)
    ev.to_csv(out / "oversold_events.csv", index=False)
    stats = btk.stats_table(ev, order)

    up_mask = pd.DataFrame({s: market_up for s in mk.symbols}, index=mk.closes.index)
    bases = [("기준선: 유니버스 아무 날", None), ("기준선: 유니버스 시장 상승일", up_mask)]
    if mask is not None:
        bases += [("기준선: 버핏 통과 종목 아무 날", mask), ("기준선: 버핏 통과 종목 시장 상승일", mask & up_mask)]
    base_rows = []
    for name, m in bases:
        allday = btk.all_day_returns(mk.closes, m, mk.spy_fwd, start, last_entry)
        base_rows += [{"strategy": name, "h": h, **btk.summarize(allday[h]["ret"], allday[h]["ex"])}
                      for h in btk.HORIZONS]
    win = (mk.spy_fwd.index >= start) & (mk.spy_fwd.index <= last_entry)
    base_rows += [{"strategy": "기준선: SPY 아무 날", "h": h,
                   **btk.summarize(mk.spy_fwd[h][win], mk.spy_fwd[h][win] * float("nan"))} for h in btk.HORIZONS]
    stats = pd.concat([stats, pd.DataFrame(base_rows)], ignore_index=True)
    stats.to_csv(out / "oversold_stats.csv", index=False)

    prefix = "버핏+" if mask is not None else ""
    ranked = stats[(stats["h"] == 20) & stats["strategy"].isin([f"{prefix}{k}" for k in OVERSOLD]) & (stats["n"] > 0)]
    ranked = ranked.sort_values("mean", ascending=False)
    ym, yn = btk.yearly_table(ev, [f"{prefix}{k}" for k in OVERSOLD])
    up_share = float(market_up[(market_up.index >= start) & (market_up.index <= last_entry)].mean())

    lines = [
        "# 과매도 매수 진입 변형 백테스트 (버핏 필터 유무) — 스크리닝 결과(통계용)",
        "",
        f"- 신호 기간: {start:%Y-%m-%d} ~ {last_entry:%Y-%m-%d} (마지막 일봉 {mk.closes.index[-1]:%Y-%m-%d}) · "
        f"유니버스: S&P 500 현재 구성종목 중 금융 제외 {len(mk.symbols)}종목",
        (f"- **버핏 필터 미실행** — {buffett_off}" if buffett_off else
         "- 버핏 필터: 명세 §3 숫자 조건(해자 LLM 판단 제외), 그 시점 제출 10-K 값만, 월말 판정 → 다음 날부터 적용"),
        "- 신호(임시값): RSI(14)<30 첫날 · RSI 30 재돌파(전날 <30, 오늘 ≥30) · 스토캐스틱(14,3,3) %K가 20 아래에서 %D 상향 돌파 · "
        "윌리엄스 %R(14) −80 재돌파 · 과매도 3개 동시(첫날)",
        f"- 시장 상승 = 그날 SPY 종가 > SPY 200일선 (기간 중 {up_share:.0%}의 날). 기준선에도 같은 조건을 건 줄을 둔다",
        "- 수익률: 신호일 종가 → 5·10·20거래일 뒤 종가(분할 보정, 배당 미포함), 같은 종목·전략 20거래일 쿨다운. 매수·매도 권유가 아니다",
        "",
        "## 20거래일 수익률", *table(stats, 20), "",
        "## 10거래일 수익률", *table(stats, 10), "",
        "## 5거래일 수익률", *table(stats, 5), "",
        f"## {prefix}과매도 진입 20거래일 평균 순위",
        *[f"{i + 1}. {r['strategy']}: 평균 {pct(r['mean'])}, 중앙값 {pct(r['median'])}, 상승 비율 {pct(r['win'], 1, False)}, "
          f"건수 {int(r['n'])}, 표준오차 {pct(r['se'], 2, False)}" for i, (_, r) in enumerate(ranked.iterrows())],
        "",
        f"## 연도별 20거래일 평균 수익률 — {prefix}과매도 진입 (괄호: 건수)",
    ]
    if len(ym):
        cols = list(ym.columns)
        lines += ["| 연도 | " + " | ".join(cols) + " |", "|---|" + "---:|" * len(cols)]
        for y in ym.index:
            cells = [f"{pct(ym.at[y, c], 1)} ({int(yn.at[y, c]) if not pd.isna(yn.at[y, c]) else 0})" for c in cols]
            lines.append(f"| {y} | " + " | ".join(cells) + " |")
    lines += ["", f"- 실행 시간 {time.time() - t0:.0f}초"]
    (out / "oversold.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
