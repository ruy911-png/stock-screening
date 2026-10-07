import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from run_weekly_osc import entries, to_weekly  # noqa: E402


def _daily(n=200, seed=0):
    days = pd.bdate_range("2020-01-06", periods=n)
    c = 100 + np.random.default_rng(seed).normal(0, 1, n).cumsum()
    return pd.DataFrame({"Open": c, "High": c + 1, "Low": c - 1, "Close": c, "Volume": 1000.0}, index=days)


def test_to_weekly_aggregates_friday_weeks_and_drops_unfinished():
    d = _daily(12)  # 2020-01-06(월) ~ 2020-01-21(화)
    w = to_weekly(d)
    assert list(w.index) == [pd.Timestamp("2020-01-10"), pd.Timestamp("2020-01-17")]  # 마지막 주(화요일까지)는 뺌
    first = d.loc["2020-01-06":"2020-01-10"]
    assert w["Open"].iloc[0] == first["Open"].iloc[0] and w["Close"].iloc[0] == first["Close"].iloc[-1]
    assert w["High"].iloc[0] == first["High"].max() and w["Volume"].iloc[0] == 5000.0


def test_entries_need_both_oversold_and_respect_cooldown():
    c = list(np.linspace(100, 140, 40)) + list(np.linspace(140, 90, 12)) + list(np.linspace(90, 130, 30))
    idx = pd.date_range("2015-01-02", periods=len(c), freq="W-FRI")
    w = pd.DataFrame({"Open": c, "High": np.array(c) + 1, "Low": np.array(c) - 1, "Close": c, "Volume": 1.0}, index=idx)
    e = entries(w, 14, 20.0, -80.0)
    assert len(e) == 1 and idx[40] < e[0] <= idx[52]   # 하락 구간에서 한 번
    assert len(entries(w, 14, 0.0, -80.0)) == 0        # %K 기준을 못 넘으면 진입 없음
