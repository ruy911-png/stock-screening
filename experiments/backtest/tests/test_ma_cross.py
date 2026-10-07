import numpy as np
import pandas as pd

from bt.ma_cross import golden_cross, signals, volume_surge


def test_golden_cross_fires_on_the_crossing_day_only():
    close = pd.Series([10.0] * 6 + [9.0] * 3 + [12.0, 13.0, 14.0])
    gc = golden_cross(close, 2, 5)
    s2, s5 = close.rolling(2).mean(), close.rolling(5).mean()
    expect = (s2.shift(1) <= s5.shift(1)) & (s2 > s5)
    assert gc.tolist() == expect.fillna(False).tolist()
    assert gc.sum() == 1


def test_volume_surge_uses_prior_window_only():
    vol = pd.Series([100.0] * 20 + [150.0, 153.0])
    v = volume_surge(vol, window=20, mult=1.5)
    assert v.iloc[20]              # 150 ≥ 1.5 × 100 (직전 20일 평균, 그날 제외)
    assert not v.iloc[21]          # 직전 20일에 150이 들어가 평균 102.5 → 153 < 153.75
    assert not v.iloc[:20].any()   # 창이 덜 찬 구간은 거짓


def test_signals_combine_cross_and_volume(ohlcv):
    closes = [100.0 - 0.5 * i for i in range(60)] + [70.0 + 2 * i for i in range(20)]
    df = ohlcv(closes)
    df.loc[df.index[66:], "Volume"] = 5_000_000.0
    s = signals(df)
    gc = s["골든크로스 5/20"]
    assert gc.any()
    assert (s["골든크로스 5/20 + 거래량"] <= gc).all()
    t = int(np.argmax(gc.to_numpy()))
    assert s["골든크로스 5/20 + 거래량"].iloc[t] == (df["Volume"].iloc[t] >= 1.5 * df["Volume"].iloc[t - 20:t].mean())
