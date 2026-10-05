import pandas as pd

import collect
from run_reddit import entry_mask, make_signals
from wsb import extract_tickers, sentiment

UNI = {"NVDA", "AAPL", "MSFT", "NOW", "ALL", "BRK-B", "TSLA", "C"}


def test_extract_tickers_rules():
    assert extract_tickers("$nvda to the moon", UNI) == {"NVDA"}
    assert extract_tickers("AAPL and MSFT earnings", UNI) == {"AAPL", "MSFT"}
    assert extract_tickers("ALL IN on NOW", UNI) == set()          # 일반 단어 티커는 캐시태그만
    assert extract_tickers("$NOW beat, $ALL too", UNI) == {"NOW", "ALL"}
    assert extract_tickers("$BRK.B and C", UNI) == {"BRK-B"}       # 1글자 티커는 캐시태그만
    assert extract_tickers("NVDAX is not NVDA", UNI) == {"NVDA"}


def test_wsb_lexicon_direction():
    assert sentiment("NVDA to the moon 🚀 calls printing") > 0.05
    assert sentiment("TSLA puts, this will drill and crash") < -0.05


def test_entry_is_next_trading_day():
    days = pd.bdate_range("2024-01-01", "2024-01-12")  # 금 1/5 → 월 1/8
    m = entry_mask(days, pd.Series(pd.to_datetime(["2024-01-05", "2024-01-06"])))
    assert list(days[m.to_numpy()]) == [pd.Timestamp("2024-01-08")]


def test_make_signals_pos_neg():
    td = pd.DataFrame({
        "date": pd.to_datetime(["2024-03-01"] * 3),
        "ticker": ["AAA", "BBB", "CCC"],
        "n": [4, 5, 2],
        "sent_sum": [1.2, -1.0, 1.0],
        "n_pos": [3, 0, 2],
        "n_neg": [0, 4, 0],
        "score_sum": [10, 10, 10],
    })
    s = make_signals(td)
    got = {(r.ticker, r.strategy) for r in s.itertuples()}
    assert ("AAA", "레딧 긍정") in got and ("BBB", "레딧 부정") in got
    assert not any(t == "CCC" for t, _ in got)  # 언급 2건 → 신호 없음


class _Resp:
    def __init__(self, code, data=None, headers=None):
        self.status_code, self._d, self.headers = code, data, headers or {}

    def json(self):
        return {"data": self._d}


class _Sess:
    def __init__(self, responses):
        self.responses, self.calls = list(responses), 0

    def get(self, *a, **k):
        self.calls += 1
        return self.responses.pop(0)


def test_fetch_day_paginates_and_reports_failure(monkeypatch):
    monkeypatch.setattr(collect.time, "sleep", lambda s: None)
    day = pd.Timestamp("2024-01-02")
    t0 = int(day.timestamp())
    page1 = [{"id": str(i), "created_utc": t0 + i * 60, "title": "x", "score": 1} for i in range(150)]  # 02:30까지
    page2 = [{"id": str(i), "created_utc": t0 + i * 60, "title": "x", "score": 1} for i in range(149, 170)]
    posts, complete = collect.fetch_day(_Sess([_Resp(200, page1), _Resp(200, page2)]), day)
    assert complete and len(posts) == 170
    posts, complete = collect.fetch_day(_Sess([_Resp(422, headers={"X-RateLimit-Reset": "1"})] * 5), day)
    assert posts is None and not complete


def test_options_jargon_is_not_a_ticker():
    uni = {"DTE", "PSA", "NVDA"}
    assert extract_tickers("PSA: 0 DTE NVDA calls", uni) == {"NVDA"}
    assert extract_tickers("$DTE earnings", uni) == {"DTE"}
