import numpy as np
import pandas as pd
import pytest

from bt.backtest import all_day_returns, apply_cooldown, events, stats_table


def test_cooldown_keeps_first_signal_per_window():
    sig = pd.Series([1, 1, 0, 1, 0, 0, 1, 1], dtype=bool)
    assert apply_cooldown(sig, cooldown=3).tolist() == [1, 0, 0, 1, 0, 0, 1, 0]


def test_events_forward_and_excess_returns():
    days = pd.bdate_range("2020-01-01", periods=40)
    close = pd.Series(np.arange(100.0, 140.0), index=days)
    spy = pd.Series(100.0, index=days)  # SPY 수익률 0
    spy_fwd = pd.DataFrame({h: spy.shift(-h) / spy - 1 for h in (5, 10, 20)})
    sig = pd.Series(False, index=days)
    sig.iloc[[2, 5, 25]] = True  # 5는 쿨다운(20일)으로 빠짐, 25는 20일 뒤 데이터 부족 구간
    ev = events("X", close, sig, spy_fwd, "S", days[0], days[-21])
    assert ev["date"].tolist() == [days[2]]
    assert ev["entry"].iloc[0] == 102.0
    assert ev["ret_5"].iloc[0] == pytest.approx(107 / 102 - 1)
    assert ev["ret_20"].iloc[0] == pytest.approx(122 / 102 - 1)
    assert ev["ex_20"].iloc[0] == pytest.approx(122 / 102 - 1)


def test_all_day_baseline_respects_mask():
    days = pd.bdate_range("2020-01-01", periods=30)
    closes = pd.DataFrame({"A": np.linspace(100, 129, 30), "B": np.linspace(100, 71, 30)}, index=days)
    spy_fwd = pd.DataFrame({h: pd.Series(0.0, index=days) for h in (5, 10, 20)})
    mask = pd.DataFrame({"A": True, "B": False}, index=days)
    out = all_day_returns(closes, mask, spy_fwd, days[0], days[-21])
    assert (out[5]["ret"] > 0).all()  # B(하락)는 빠짐
    assert len(out[20]) == 10        # A만, 20일 뒤 종가가 있는 10일


def test_stats_table_counts():
    ev = pd.DataFrame({"strategy": ["S", "S"], "ticker": ["A", "B"],
                       "date": pd.to_datetime(["2020-01-02", "2020-01-02"]),
                       **{f"ret_{h}": [0.1, -0.05] for h in (5, 10, 20)},
                       **{f"ex_{h}": [0.05, -0.1] for h in (5, 10, 20)}})
    t = stats_table(ev, ["S"])
    r = t[t.h == 20].iloc[0]
    assert r["n"] == 2 and r["n_dates"] == 1
    assert r["mean"] == pytest.approx(0.025) and r["win"] == 0.5 and r["ex_win"] == 0.5


def test_drop_unfinished_session_only_before_close():
    from bt.data import drop_unfinished_session
    days = pd.bdate_range("2026-10-01", "2026-10-05")
    df = pd.DataFrame({"Close": [1.0, 2.0, 3.0]}, index=days)
    ny = "America/New_York"
    assert len(drop_unfinished_session(df, pd.Timestamp("2026-10-05 11:00", tz=ny))) == 2  # 장중 → 오늘 행 제외
    assert len(drop_unfinished_session(df, pd.Timestamp("2026-10-05 18:00", tz=ny))) == 3  # 마감 후 → 유지
    assert len(drop_unfinished_session(df, pd.Timestamp("2026-10-06 09:00", tz=ny))) == 3  # 다음 날
