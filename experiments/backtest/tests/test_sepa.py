import numpy as np
import pandas as pd

from bt.sepa import screen_asof


def _closes():
    idx = pd.bdate_range("2023-01-02", periods=400)
    t = np.arange(400)
    return pd.DataFrame({
        "STRONG": 50 * 1.002 ** t,
        "WEAK": 50 * 1.0003 ** t,
        "FLAT": 50 + np.sin(t / 5),
        "DOWN": 50 * 0.998 ** t,
    }, index=idx)


def test_strong_uptrend_passes_and_downtrend_fails():
    closes = _closes()
    res = screen_asof(closes, closes.index[-1])
    assert bool(res.loc["STRONG", "all"])
    assert not bool(res.loc["DOWN", "all"])
    assert res.loc["STRONG", "rs"] == 100.0
    # 약한 상승: 52주 저점 대비 +30% 미달
    assert not bool(res.loc["WEAK", "c4"])


def test_stale_last_bar_is_excluded():
    closes = _closes()
    closes.loc[closes.index[-1], "STRONG"] = np.nan  # 기준일 종가 없음
    res = screen_asof(closes, closes.index[-1])
    assert not bool(res.loc["STRONG", "data_ok"])
    assert not bool(res.loc["STRONG", "all"])


def test_values_match_plain_recompute():
    closes = _closes()
    res = screen_asof(closes, closes.index[-1])
    s = closes["STRONG"].to_numpy()
    assert abs(res.loc["STRONG", "ma50"] - s[-50:].mean()) < 1e-9
    assert abs(res.loc["STRONG", "ma200_prev"] - s[-222:-22].mean()) < 1e-9
    assert res.loc["STRONG", "low52"] == s[-252:].min()
