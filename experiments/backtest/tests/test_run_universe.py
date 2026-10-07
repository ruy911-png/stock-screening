import numpy as np
import pandas as pd

import run_universe as ru


def test_all_signals_counts_each_definition_once(ohlcv):
    rng = np.random.default_rng(7)
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.02, 400)))
    df = ohlcv(close)
    sig = ru.all_signals(df, pd.Series(True, index=df.index))
    cols = list(sig.columns)
    assert len(cols) == len(set(cols)) == 27
    assert "RSI<30 첫날" not in cols and "BB I 돌파" not in cols       # 같은 정의라 한 번만
    assert {"BB-I", "RSI<30", "과매도 3개 동시", "BB 하단 이탈 + RSI<30", "골든크로스 20/60"} <= set(cols)
    assert sig.dtypes.eq(bool).all()


def test_all_signals_short_history_is_quiet(ohlcv):
    df = ohlcv([10.0, 10.5, 9.8, 10.2, 10.1])  # 막 상장한 종목처럼 이력이 짧아도 오류 없이 신호 없음
    sig = ru.all_signals(df, pd.Series(True, index=df.index))
    assert not sig.any().any()


def test_baseline_of_matches_filter_and_market_condition():
    assert ru.baseline_of("RSI<30") == "기준선: 유니버스 아무 날"
    assert ru.baseline_of("버핏+골든크로스 20/60") == "기준선: 버핏 통과 종목 아무 날"
    assert ru.baseline_of("버핏+RSI 30 재돌파 + 시장 상승") == "기준선: 버핏 통과 종목 시장 상승일"


def test_ranking_uses_matching_baseline_and_min_n():
    rows = [
        {"strategy": "A", "h": 20, "n": 200, "mean": 0.020, "se": 0.005},
        {"strategy": "버핏+A", "h": 20, "n": 150, "mean": 0.030, "se": 0.010},
        {"strategy": "B", "h": 20, "n": 10, "mean": 0.090, "se": 0.050},   # 건수 부족 → 제외
        {"strategy": "기준선: 유니버스 아무 날", "h": 20, "n": 9999, "mean": 0.010, "se": 0.001},
        {"strategy": "기준선: 버핏 통과 종목 아무 날", "h": 20, "n": 999, "mean": 0.015, "se": 0.001},
    ]
    r = ru.ranking(pd.DataFrame(rows), min_n=100)
    assert list(r["strategy"]) == ["버핏+A", "A"]
    assert np.isclose(r.set_index("strategy").at["버핏+A", "z"], 1.5)   # (0.030 − 0.015) ÷ 0.010
    assert np.isclose(r.set_index("strategy").at["A", "z"], 2.0)       # (0.020 − 0.010) ÷ 0.005


def test_sp500_reference_renames_duplicate_signals(tmp_path):
    pd.DataFrame([{"strategy": "RSI<30 첫날", "h": 20, "n": 5, "mean": 0.01},
                  {"strategy": "버핏+BB I 돌파", "h": 20, "n": 3, "mean": 0.02}]).to_csv(tmp_path / "oversold_stats.csv",
                                                                                     index=False)
    ref = ru.sp500_reference(tmp_path)
    assert set(ref["strategy"]) == {"RSI<30", "버핏+BB-I"}
    assert ru.sp500_reference(tmp_path / "없음").empty


def test_as_traded_undoes_later_splits_only():
    days = pd.bdate_range("2024-01-01", periods=4)
    closes = pd.DataFrame({"FWD": [10.0, 10.0, 10.0, 10.0], "REV": [10.0, 10.0, 10.0, 10.0]}, index=days)
    splits = pd.DataFrame({"FWD": [0.0, 0.0, 4.0, 0.0], "REV": [0.0, 0.0, 0.05, 0.0]}, index=days)
    raw = ru.as_traded(closes, splits)
    assert raw["FWD"].tolist() == [40.0, 40.0, 10.0, 10.0]   # 4:1 액면분할 전에는 실제로 40달러
    assert raw["REV"].tolist() == [0.5, 0.5, 10.0, 10.0]     # 1:20 병합 전에는 실제로 동전주


def test_gap_ahead_flags_days_whose_window_has_missing_trading_days():
    cal = pd.bdate_range("2024-01-01", periods=10)
    close = pd.Series([1.0, 1, 1, np.nan, np.nan, 1, 1, 1, 1, 1], index=cal)
    g = ru.gap_ahead(close, 2)
    # t 다음 2거래일(t+1, t+2)에 빈 날이 있으면 True. 끝 두 날은 구간이 데이터 밖이라 True
    assert g.tolist() == [False, True, True, True, False, False, False, False, True, True]
