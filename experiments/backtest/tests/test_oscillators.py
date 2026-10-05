import numpy as np
import pandas as pd
import pytest

from bt.oscillators import rsi, signals, stochastic, williams_r


def test_rsi_matches_wilder_hand_calculation():
    close = pd.Series([10.0, 11, 12, 11, 12, 13])
    out = rsi(close, 3)
    # 변화: +1 +1 −1 +1 +1 → 첫 평균(3개): 이득 2/3, 손실 1/3
    ag, al = 2 / 3, 1 / 3
    assert out.iloc[3] == pytest.approx(100 - 100 / (1 + ag / al))
    ag, al = (ag * 2 + 1) / 3, (al * 2 + 0) / 3   # 4번째 변화 +1
    assert out.iloc[4] == pytest.approx(100 - 100 / (1 + ag / al))
    assert out.iloc[:3].isna().all()


def test_rsi_extremes():
    up = pd.Series(np.arange(1.0, 31.0))
    assert rsi(up, 14).iloc[-1] == 100.0
    assert rsi(up[::-1].reset_index(drop=True), 14).iloc[-1] == pytest.approx(0.0)
    assert rsi(pd.Series([5.0] * 20), 14).iloc[-1] == 50.0


def test_stochastic_and_williams_relationship():
    rng = np.random.default_rng(3)
    c = pd.Series(100 + rng.normal(0, 1, 80).cumsum())
    h, lo = c + 1, c - 1
    st = stochastic(h, lo, c)
    wr = williams_r(h, lo, c)
    # 윌리엄스 %R = 빠른 %K − 100
    both = pd.concat([st["fast_k"] - 100, wr], axis=1).dropna()
    assert np.allclose(both.iloc[:, 0], both.iloc[:, 1])
    # 느린 %K = 빠른 %K 3일 평균
    assert st["k"].iloc[-1] == pytest.approx(st["fast_k"].iloc[-3:].mean())
    assert ((wr.dropna() <= 0) & (wr.dropna() >= -100)).all()


def test_oversold_signal_fires_once_on_first_day(ohlcv):
    closes = [100.0 + (i % 2) for i in range(40)] + [99 - 2 * i for i in range(10)]
    df = ohlcv(closes)
    sig = signals(df)
    r = rsi(df["Close"], 14)
    first = int(np.argmax((r < 30).to_numpy()))
    assert sig["RSI<30"].sum() == 1 and sig["RSI<30"].iloc[first]
    assert not sig["RSI>70"].iloc[40:].any()
