import numpy as np

from bt.bollinger_methods import add_indicators, method1, method12, method2, method3, squeeze_days


def _volatile(n, seed=1, start=100.0, sd=1.0):
    rng = np.random.default_rng(seed)
    return list(start + rng.normal(0, sd, n).cumsum() * 0.3 + rng.normal(0, sd, n))


def _flat(n, base=100.0):
    return [base + (i % 2) * 0.1 for i in range(n)]


def test_method1_squeeze_then_breakout(ohlcv):
    closes = _volatile(180) + _flat(30) + [106.0]
    ind = add_indicators(ohlcv(closes))
    assert squeeze_days(ind["bw"]).iloc[190:210].any()
    sig = method1(ind)
    assert sig.iloc[210]
    assert not sig.iloc[180:210].any()


def test_method1_no_recent_squeeze_no_signal(ohlcv):
    closes = _volatile(180) + _flat(30) + _volatile(40, seed=7, start=100.0, sd=1.0) + [130.0]
    ind = add_indicators(ohlcv(closes))
    t = len(closes) - 1
    assert ind["Close"].iloc[t] > ind["ub"].iloc[t]  # 돌파는 있음
    assert not squeeze_days(ind["bw"]).iloc[t - 20:t].any()  # 최근 20일 Squeeze 없음
    assert not method1(ind).iloc[t]


def test_method2_fires_once_on_first_joint_day(ohlcv):
    closes = [100.0 + (i % 2) for i in range(40)] + [102.0 + i for i in range(15)]
    ind = add_indicators(ohlcv(closes))
    sig = method2(ind)
    joint = (ind["pctb"] > 0.8) & (ind["mfi10"] > 80)
    first = int(np.argmax(joint.to_numpy()))
    assert first >= 40
    assert sig.sum() == 1 and sig.iloc[first]


def test_method12_needs_squeeze_breakout_and_momentum(ohlcv):
    closes = _volatile(180) + _flat(30) + [101.0 + i for i in range(12)]
    ind = add_indicators(ohlcv(closes))
    sig = method12(ind)
    assert sig.sum() == 1
    t = int(np.argmax(sig.to_numpy()))
    assert ind["pctb"].iloc[t] > 0.8 and ind["mfi10"].iloc[t] > 80

    # Squeeze 없이 같은 모양의 상승만 있으면 신호 없음
    base = [100.0 + (0.5 + 4.5 * i / 239) * (-1) ** i for i in range(240)]  # 진폭이 계속 커짐 → 최근 Squeeze 없음
    ind2 = add_indicators(ohlcv(base + [106.0 + 2 * i for i in range(12)]))
    assert not squeeze_days(ind2["bw"]).iloc[-32:].any()  # 전제: 최근 창에 Squeeze 없음
    assert ((ind2["pctb"] > 0.8) & (ind2["mfi10"] > 80)).iloc[-12:].any()  # 전제: 모멘텀 조건은 성립
    assert not method12(ind2).iloc[-12:].any()


W_SHAPE = (
    [100.0 + (i % 2) for i in range(60)]          # 0-59 기준 구간
    + [99, 97, 95, 93, 91]                          # 60-64 첫 저점(하단 밖)
    + [93, 95, 97, 99, 100, 101, 101, 100]          # 65-72 중간 밴드 위로 반등, H = 101
    + [98, 96, 94, 92.5, 92]                        # 73-77 둘째 저점(첫 저점 +3% 이내, 밴드 안)
    + [94, 96, 98, 100, 101.5, 102]                 # 78-83 H 돌파 → 82일에 신호
)


def test_method3_w_bottom(ohlcv):
    ind = add_indicators(ohlcv(W_SHAPE))
    assert ind["pctb"].iloc[64] < 0          # 첫 저점은 하단 밖
    assert ind["pctb"].iloc[77] > 0          # 둘째 저점은 밴드 안
    sig = method3(ind)
    assert sig.sum() == 1 and sig.iloc[82]


def test_method3_v_shape_without_second_low_no_signal(ohlcv):
    closes = [100.0 + (i % 2) for i in range(60)] + [99, 97, 95, 93, 91] + [93, 95, 97, 99, 101, 103, 105, 107]
    assert not method3(add_indicators(ohlcv(closes))).any()


def test_method3_second_low_outside_band_resets(ohlcv):
    closes = list(W_SHAPE[:73]) + [96, 92, 88, 84, 80] + [84, 88, 92, 96, 100, 101.5, 102]
    ind = add_indicators(ohlcv(closes))
    assert (ind["pctb"].iloc[73:78] < 0).any()
    assert not method3(ind).any()
