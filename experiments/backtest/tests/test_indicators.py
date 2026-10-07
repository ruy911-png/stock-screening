import numpy as np
import pandas as pd
import pytest

from bt.indicators import bollinger, mfi, rolling_high, rolling_low, rs_rating, sma


def test_sma_needs_full_window():
    s = pd.Series([1.0, 2, 3, 4, 5])
    out = sma(s, 3)
    assert out.iloc[:2].isna().all()
    assert out.iloc[2:].tolist() == [2.0, 3.0, 4.0]


def test_bollinger_matches_manual_population_sd():
    rng = np.random.default_rng(0)
    close = pd.Series(100 + rng.normal(0, 1, 60).cumsum())
    bb = bollinger(close)
    window = close.iloc[-20:].to_numpy()
    mb = window.mean()
    sd = np.sqrt(((window - mb) ** 2).mean())  # 모집단(N으로 나눔)
    assert bb["mb"].iloc[-1] == pytest.approx(mb)
    assert bb["ub"].iloc[-1] == pytest.approx(mb + 2 * sd)
    assert bb["lb"].iloc[-1] == pytest.approx(mb - 2 * sd)
    assert bb["pctb"].iloc[-1] == pytest.approx((close.iloc[-1] - (mb - 2 * sd)) / (4 * sd))
    assert bb["bw"].iloc[-1] == pytest.approx(4 * sd / mb)


def test_bollinger_flat_series_pctb_missing():
    bb = bollinger(pd.Series([10.0] * 25))
    assert bb["pctb"].iloc[-1] != bb["pctb"].iloc[-1]  # NaN: UB = LB


def test_mfi_all_up_is_100_and_all_down_is_0():
    up = pd.Series(np.arange(1, 31, dtype=float))
    vol = pd.Series(1000.0, index=up.index)
    assert mfi(up, up, up, vol, 10).iloc[-1] == pytest.approx(100.0)
    down = up[::-1].reset_index(drop=True)
    assert mfi(down, down, down, vol, 10).iloc[-1] == pytest.approx(0.0)


def test_mfi_hand_calculation():
    # 전형가격 = 종가(고·저·종 동일). 마지막 2일: +1 상승(흐름 11×100), -1 하락(흐름 10×300)
    close = pd.Series([10.0, 11.0, 10.0])
    vol = pd.Series([100.0, 100.0, 300.0])
    out = mfi(close, close, close, vol, 2)
    pos, neg = 11 * 100, 10 * 300
    assert out.iloc[-1] == pytest.approx(100 - 100 / (1 + pos / neg))
    assert np.isnan(out.iloc[1])  # 첫 행은 비교 불가 → 2일 창이 안 참


def test_52w_high_low_use_closes():
    s = pd.Series(np.arange(300, dtype=float))
    assert rolling_high(s).iloc[-1] == 299
    assert rolling_low(s).iloc[-1] == 299 - 251


def test_rs_rating_is_cross_sectional_percentile():
    scores = pd.DataFrame({"A": [0.1], "B": [0.2], "C": [0.3], "D": [0.4]})
    r = rs_rating(scores).iloc[0]
    assert r.tolist() == [25.0, 50.0, 75.0, 100.0]
