"""러셀 1000에서 S&P 500·금융을 뺀 유니버스로, 지금까지 시험한 방법 전체를 한 번에 백테스트 — 사용자 요청(2026-10-05):
"나스닥은?" → "중복종목 빼고 러셀 1000" → "시총 100으로 해라". 전체와 시총 상위 100을 함께 낸다.

결과는 스크리닝 결과(통계용)이며 매수·매도 권유가 아니다. 유니버스 목록은 Secret(R1000X_UNIVERSE)로만 받고
(bt/universe.py), 종목별 이벤트는 목록이 드러나므로 파일로 남기지 않는다 — 집계만 저장한다.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from bt import backtest as btk  # noqa: E402
from bt.bollinger_methods import add_indicators  # noqa: E402
from bt.bollinger_methods import signals as bb_signals  # noqa: E402
from bt.data import load_universe  # noqa: E402
from bt.indicators import sma  # noqa: E402
from bt.ma_cross import signals as ma_signals  # noqa: E402
from bt.oscillators import bb_rsi_signals, oversold_signals  # noqa: E402
from bt.oscillators import signals as osc_signals  # noqa: E402
from bt.pipeline import buffett_mask, load_market  # noqa: E402
from bt.runner import pct, table  # noqa: E402
from bt.sec import DEFAULT_UA, fetch_company_tickers  # noqa: E402
from bt.universe import ENV_NAME, TOP_N, build, parse_spec, ticker_cik_map  # noqa: E402

# 앞 시험에서 이름만 다르고 정의가 같은 신호 → 오른쪽 이름으로 한 번만 센다
SAME_AS = {"RSI<30 첫날": "RSI<30", "BB I 돌파": "BB-I"}
SP500_FILES = ["backtest", "oscillators", "oversold", "bb_rsi", "ma_cross"]
ALL, TOP = "전체", f"시총 상위 {TOP_N}"
MIN_N = {ALL: 100, TOP: 30}  # 순위표에 올리는 최소 건수(시총 상위 묶음은 종목이 적어 낮춤)


def all_signals(df: pd.DataFrame, market_up: pd.Series) -> pd.DataFrame:
    """앞 시험 다섯 묶음(볼린저 I·II·III, 과매수·과매도, 과매도 진입, 볼린저+RSI, 골든크로스)의 신호를 한 표로."""
    ind = add_indicators(df[["Open", "High", "Low", "Close", "Volume"]])
    parts = [bb_signals(ind).rename(columns=lambda m: f"BB-{m}"), osc_signals(df), oversold_signals(df, market_up),
             bb_rsi_signals(df), ma_signals(df)]
    out = pd.concat(parts, axis=1)
    out = out.loc[:, ~out.columns.duplicated()]  # '과매도 3개 동시'는 두 묶음에 같은 정의로 있다
    return out.drop(columns=[c for c in SAME_AS if c in out.columns])


def baseline_of(strategy: str) -> str:
    """비교할 기준선: 버핏이 붙으면 버핏 통과 종목, 시장 상승 조건이 붙으면 시장 상승일끼리."""
    who = "버핏 통과 종목" if strategy.startswith("버핏+") else "유니버스"
    return f"기준선: {who} {'시장 상승일' if '시장 상승' in strategy else '아무 날'}"


def subset_stats(mk, symbols: list[str], mask, market_up: pd.Series, ev: pd.DataFrame, order: list[str],
                 start: pd.Timestamp, last_entry: pd.Timestamp) -> pd.DataFrame:
    """종목 묶음 하나의 전략별 통계 + 기준선(유니버스·버핏 × 아무 날·시장 상승일, SPY)."""
    stats = btk.stats_table(ev[ev["ticker"].isin(symbols)], order)
    closes = mk.closes[symbols]
    up = pd.DataFrame({s: market_up for s in symbols}, index=closes.index)
    bases = [("기준선: 유니버스 아무 날", None), ("기준선: 유니버스 시장 상승일", up)]
    if mask is not None:
        bm = mask[symbols]
        bases += [("기준선: 버핏 통과 종목 아무 날", bm), ("기준선: 버핏 통과 종목 시장 상승일", bm & up)]
    rows = []
    for name, m in bases:
        allday = btk.all_day_returns(closes, m, mk.spy_fwd, start, last_entry)
        rows += [{"strategy": name, "h": h, **btk.summarize(allday[h]["ret"], allday[h]["ex"])} for h in btk.HORIZONS]
    win = (mk.spy_fwd.index >= start) & (mk.spy_fwd.index <= last_entry)
    rows += [{"strategy": "기준선: SPY 아무 날", "h": h,
              **btk.summarize(mk.spy_fwd[h][win], mk.spy_fwd[h][win] * float("nan"))} for h in btk.HORIZONS]
    return pd.concat([stats, pd.DataFrame(rows)], ignore_index=True)


def ranking(stats: pd.DataFrame, min_n: int, h: int = 20) -> pd.DataFrame:
    """h거래일 평균 순위(건수 min_n 이상) + 맞는 기준선 대비 차이와 표준오차 배수(z)."""
    sub = stats[stats["h"] == h]
    base = sub.set_index("strategy")["mean"]
    r = sub[~sub["strategy"].str.startswith("기준선") & (sub["n"] >= min_n)].copy()
    r["base"] = r["strategy"].map(lambda k: base.get(baseline_of(k)))
    r["z"] = (r["mean"] - r["base"]) / r["se"]
    return r.sort_values("mean", ascending=False)


def sp500_reference(results_dir: Path) -> pd.DataFrame:
    """앞 S&P 500 시험의 통계(이름을 이 실행과 같게 맞춤). 파일이 없으면 빈 표."""
    frames = [pd.read_csv(p) for p in (results_dir / f"{n}_stats.csv" for n in SP500_FILES) if p.exists()]
    if not frames:
        return pd.DataFrame(columns=["strategy", "h", "n", "mean", "median", "win", "ex_mean", "ex_win", "se"])
    df = pd.concat(frames, ignore_index=True)
    df["strategy"] = df["strategy"].replace({**SAME_AS, **{f"버핏+{a}": f"버핏+{b}" for a, b in SAME_AS.items()}})
    return df.drop_duplicates(["strategy", "h"])


def cell(stats: pd.DataFrame, strategy: str, h: int = 20) -> str:
    row = stats[(stats["strategy"] == strategy) & (stats["h"] == h)]
    if row.empty or not row["n"].iloc[0] or pd.isna(row["mean"].iloc[0]):
        return "—"
    return f"{pct(row['mean'].iloc[0])} ({int(row['n'].iloc[0])}건)"


def rank_table(r: pd.DataFrame, sp20: pd.Series) -> list[str]:
    lines = ["| 순위 | 방법 | 평균 | 중앙값 | 상승 비율 | 건수 | SPY 대비 평균 | 기준선 대비 | S&P 500 같은 방법 |",
             "|---:|---|---:|---:|---:|---:|---:|---:|---:|"]
    for _, x in r.iterrows():
        z = "—" if pd.isna(x["z"]) else f"{(x['mean'] - x['base']) * 100:+.2f}%p ({x['z']:+.1f} SE)"
        lines.append(f"| {x['_rank']} | {x['strategy']} | {pct(x['mean'])} | {pct(x['median'])} | "
                     f"{pct(x['win'], 1, False)} | {int(x['n'])} | {pct(x['ex_mean'])} | {z} | {pct(sp20.get(x['strategy']))} |")
    return lines


def ranked_section(stats: pd.DataFrame, min_n: int, sp20: pd.Series, top: int = 10, bottom: int = 3) -> list[str]:
    r = ranking(stats, min_n)
    r["_rank"] = range(1, len(r) + 1)
    shown = pd.concat([r.head(top), r.tail(bottom)]) if len(r) > top + bottom else r
    shown = shown[~shown.index.duplicated()]
    lines = rank_table(shown, sp20)
    if len(r) > top + bottom:
        lines.insert(2 + top, f"| … | (중간 {len(r) - top - bottom}개 생략, 전체는 아래 표) | | | | | | | |")
    return lines


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="results/r1000x")
    ap.add_argument("--cache", default=".cache")
    ap.add_argument("--price-start", default="2010-01-01")
    ap.add_argument("--start", default="2016-01-01", help="신호 집계 시작일")
    ap.add_argument("--limit", type=int, default=0, help="시험용: 앞 N종목만")
    args = ap.parse_args()
    out, cache = Path(args.out), Path(args.cache)
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    spec = parse_spec(os.environ.get(ENV_NAME, ""))
    sp = load_universe(cache)
    ua = os.environ.get("SEC_USER_AGENT") or DEFAULT_UA
    cik_note = None
    try:
        tickers = ticker_cik_map(fetch_company_tickers(cache, ua))
    except Exception as e:  # noqa: BLE001 — 표를 못 받으면 S&P 500 중복은 티커로만 거르고 버핏 필터는 못 쓴다
        tickers, cik_note = {}, f"SEC 티커→CIK 표를 못 받음({type(e).__name__}) — S&P 500 같은 회사는 티커로만 거름"
    uni, counts = build(spec, tickers, sp)
    if args.limit:
        uni = uni.iloc[:args.limit]
    mk = load_market(cache, args.price_start, uni=uni, name="r1000x")
    start = pd.Timestamp(args.start)
    last_entry = mk.closes.index[-1 - max(btk.HORIZONS)]
    market_up = (mk.spy > sma(mk.spy, 200)).fillna(False)
    mask, _, buffett_off, sec_missing = buffett_mask(mk, cache, start)

    names: list[str] = []
    evs = []
    for s in mk.symbols:
        df = mk.prices[s]
        sig = all_signals(df, market_up)
        names = names or list(sig.columns)
        bm = mask[s].reindex(df.index, fill_value=False) if mask is not None else None
        for k in names:
            evs.append(btk.events(s, df["Close"], sig[k], mk.spy_fwd, k, start, last_entry))
            if bm is not None:
                evs.append(btk.events(s, df["Close"], sig[k] & bm, mk.spy_fwd, f"버핏+{k}", start, last_entry))
    evs = [e for e in evs if len(e)]
    if not evs:
        raise SystemExit("신호가 하나도 없음 — 중단")
    ev = pd.concat(evs, ignore_index=True)
    order = names + ([f"버핏+{k}" for k in names] if mask is not None else [])

    top = [s for s in mk.symbols if mk.uni.at[s, "rank"] <= TOP_N]
    sets = {ALL: mk.symbols, TOP: top}
    stats = {k: subset_stats(mk, syms, mask, market_up, ev, order, start, last_entry) for k, syms in sets.items()}
    stats[ALL].to_csv(out / "stats_all.csv", index=False)
    stats[TOP].to_csv(out / f"stats_top{TOP_N}.csv", index=False)

    sp_ref = sp500_reference(HERE / "results")
    sp20 = sp_ref[sp_ref["h"] == 20].set_index("strategy")["mean"]
    sp_top = ranking(sp_ref, MIN_N[ALL]).head(5)["strategy"].tolist() if len(sp_ref) else []
    top5 = ranking(stats[ALL], MIN_N[ALL]).head(5)["strategy"].tolist()
    ym, yn = btk.yearly_table(ev, top5)

    no_cik = counts.pop("CIK 못 찾음(재무 미확인)")
    steps = " → ".join(f"{k} {v}" if k in ("목록", "최종") else f"{k} −{v}" for k, v in counts.items())
    steps += f" (그중 CIK 못 찾음 {no_cik} — 재무 미확인)"
    lines = [
        "# 러셀 1000(S&P 500·금융 제외) 백테스트 — 스크리닝 결과(통계용)",
        "",
        f"- 유니버스: 사용자가 내려받은 iShares IWB(러셀 1000 ETF) 보유종목에서 {steps}. "
        f"일봉 받음 {len(mk.symbols)}종목(못 받음 {len(mk.failed)})",
        f"- {TOP} = 위 목록에서 IWB 비중(유동주식 시가총액) 큰 순 {TOP_N}개 중 일봉 받은 {len(top)}종목",
        "- 종목 목록은 파일의 저작권 고지(개인·비상업적 용도, 게시 금지)에 따라 저장소에 두지 않는다. 종목별 결과도 남기지 않고 집계만 둔다",
        (f"- **버핏 필터 미실행** — {buffett_off}" if buffett_off else
         f"- 버핏 필터: 앞 시험과 같은 숫자 조건(해자 LLM 판단 제외), 그 시점 제출 10-K 값만, 월말 판정 → 다음 날부터. "
         f"업종 중앙값은 이 유니버스 안에서 계산(S&P 500 시험과 비교 집단이 다름). SEC 재무 없음 {len(sec_missing)}종목"),
        *([f"- {cik_note}"] if cik_note else []),
        "- 신호: 앞 시험과 같은 정의(볼린저 I·II·III·I+II, RSI·스토캐스틱·윌리엄스 %R 과매수·과매도, (b)안, 과매도 진입 변형, "
        "볼린저+RSI, 골든크로스 ± 거래량). 이름만 다른 같은 신호(RSI<30 첫날 = RSI<30, BB I 돌파 = BB-I)는 한 번만 센다",
        f"- 신호 기간: {start:%Y-%m-%d} ~ {last_entry:%Y-%m-%d} (마지막 일봉 {mk.closes.index[-1]:%Y-%m-%d}). "
        "수익률: 신호일 종가 → 5·10·20거래일 뒤 종가(분할 보정, 배당 미포함), 같은 종목·전략 20거래일 쿨다운. 매수·매도 권유가 아니다",
        "- 한계: 현재 구성종목만(생존편향, 새로 상장한 종목은 이력이 짧음) · 같은 날 신호가 몰려 표준오차가 작게 나옴 · "
        "여러 방법을 비교해 우연히 좋아 보이는 결과가 섞일 수 있음 · 거래비용·세금 미반영",
        "",
        "## S&P 500 상위 5개 방법은 여기서 어땠나 (20거래일 평균, 괄호: 건수)",
        f"| S&P 500 순위 | 방법 | S&P 500 | 러셀(S&P 제외) {ALL} | {TOP} |",
        "|---:|---|---:|---:|---:|",
        *[f"| {i + 1} | {k} | {cell(sp_ref, k)} | {cell(stats[ALL], k)} | {cell(stats[TOP], k)} |"
          for i, k in enumerate(sp_top)],
        "",
        f"## {ALL} {len(mk.symbols)}종목 — 20거래일 평균 순위 (건수 {MIN_N[ALL]} 이상, 위 10 · 아래 3)",
        *ranked_section(stats[ALL], MIN_N[ALL], sp20),
        "",
        f"## {TOP} — 20거래일 평균 순위 (건수 {MIN_N[TOP]} 이상, 위 10 · 아래 3)",
        *ranked_section(stats[TOP], MIN_N[TOP], sp20),
        "",
        "- 기준선 대비 = 맞는 기준선(버핏 유무 × 아무 날/시장 상승일)과의 평균 차이, 괄호는 그 차이 ÷ 표준오차",
        "",
        f"## 연도별 20거래일 평균 — {ALL} 상위 5개 (괄호: 건수)",
    ]
    if len(ym):
        cols = list(ym.columns)
        lines += ["| 연도 | " + " | ".join(cols) + " |", "|---|" + "---:|" * len(cols)]
        for y in ym.index:
            cells = [f"{pct(ym.at[y, c], 1)} ({int(yn.at[y, c]) if not pd.isna(yn.at[y, c]) else 0})" for c in cols]
            lines.append(f"| {y} | " + " | ".join(cells) + " |")
    lines += ["", f"## {ALL} — 20거래일 전체 표", *table(stats[ALL], 20), "",
              f"## {TOP} — 20거래일 전체 표", *table(stats[TOP], 20), "",
              "- 5·10거래일 결과는 stats_all.csv · stats_top100.csv", "", f"- 실행 시간 {time.time() - t0:.0f}초"]
    (out / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
