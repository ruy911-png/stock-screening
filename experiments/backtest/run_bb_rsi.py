"""버핏 숫자 필터 × 볼린저+RSI 조합 백테스트 — 사용자 요청(2026-10-05): "둘 다 해봐 버핏 붙여서".

조합: 하단 밴드 이탈 + RSI(14)<30, 볼린저 Method I 돌파 + RSI(14)>50. 비교용으로 볼린저 단독 줄도 둔다.
결과는 스크리닝 결과(통계용)이며 매수·매도 권유가 아니다.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from bt import backtest as btk  # noqa: E402
from bt.oscillators import BB_RSI as SIGNALS, bb_rsi_signals as signals  # noqa: E402
from run_oscillators import pct, table  # noqa: E402
from bt.pipeline import buffett_mask, load_market  # noqa: E402


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
    ev.to_csv(out / "bb_rsi_events.csv", index=False)
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
    stats.to_csv(out / "bb_rsi_stats.csv", index=False)

    prefix = "버핏+" if mask is not None else ""
    ranked = stats[(stats["h"] == 20) & stats["strategy"].isin([f"{prefix}{k}" for k in SIGNALS]) & (stats["n"] > 0)]
    ranked = ranked.sort_values("mean", ascending=False)
    ym, yn = btk.yearly_table(ev, [f"{prefix}{k}" for k in SIGNALS])

    lines = [
        "# 버핏 × 볼린저+RSI 조합 백테스트 — 스크리닝 결과(통계용)",
        "",
        f"- 신호 기간: {start:%Y-%m-%d} ~ {last_entry:%Y-%m-%d} (마지막 일봉 {mk.closes.index[-1]:%Y-%m-%d})",
        f"- 유니버스: S&P 500 현재 구성종목 중 금융 제외 {len(mk.symbols)}종목 (일봉 못 받음 {len(mk.failed)})",
        (f"- **버핏 필터 미실행** — {buffett_off}. 아래는 지표 단독 결과만" if buffett_off else
         f"- 버핏 필터: 명세 §3 숫자 조건(해자 LLM 판단 제외), 그 시점 제출 10-K 값만, 월말 판정 → 다음 날부터 적용 · SEC 재무 없음 {len(sec_missing)}종목"),
        "- 볼린저(20, ±2σ): 하단 이탈 = 종가 < 하단 밴드(%b < 0)가 처음 된 날 · I 돌파 = 직전 20거래일 안 Squeeze(BandWidth 125거래일 최저) 뒤 종가가 처음 상단 밴드 위",
        "- RSI(14) Wilder: 하단 이탈과 함께 < 30(과매도 재확인), I 돌파일에 > 50(상승 힘 확인) — 임시 경계값",
        "- 수익률: 신호일 종가 → 5·10·20거래일 뒤 종가(분할 보정, 배당 미포함), 같은 종목·전략 20거래일 쿨다운. 매수·매도 권유가 아니다",
        "",
        "## 20거래일 수익률", *table(stats, 20), "",
        "## 10거래일 수익률", *table(stats, 10), "",
        "## 5거래일 수익률", *table(stats, 5), "",
        f"## {'버핏+' if mask is not None else ''}볼린저+RSI 20거래일 평균 순위",
        *[f"{i + 1}. {r['strategy']}: 평균 {pct(r['mean'])}, 중앙값 {pct(r['median'])}, 건수 {int(r['n'])}, "
          f"SPY 대비 {pct(r['ex_mean'])}, 표준오차 {pct(r['se'], 2, False)}" for i, (_, r) in enumerate(ranked.iterrows())],
        "",
        f"## 연도별 20거래일 평균 수익률 — {'버핏+' if mask is not None else ''}볼린저+RSI (괄호: 건수)",
    ]
    if len(ym):
        cols = list(ym.columns)
        lines += ["| 연도 | " + " | ".join(cols) + " |", "|---|" + "---:|" * len(cols)]
        for y in ym.index:
            cells = [f"{pct(ym.at[y, c], 1)} ({int(yn.at[y, c]) if not pd.isna(yn.at[y, c]) else 0})" for c in cols]
            lines.append(f"| {y} | " + " | ".join(cells) + " |")
    lines += ["", f"- 실행 시간 {time.time() - t0:.0f}초"]
    (out / "bb_rsi.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
