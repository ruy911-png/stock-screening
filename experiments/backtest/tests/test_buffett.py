import numpy as np
import pandas as pd
import pytest

from bt.buffett import build_snapshots, daily_mask, evaluate, market_cap, snapshot_metrics, cum_split_factor
from bt.sec import annual_rows, facts_frame, latest_shares, pit


def _fy(year, val, filed_year=None, filed="02-20"):
    return {"start": f"{year}-01-01", "end": f"{year}-12-31", "val": val,
            "filed": f"{filed_year or year + 1}-{filed}", "form": "10-K"}


def _inst(year, val, filed_year=None):
    return {"end": f"{year}-12-31", "val": val, "filed": f"{filed_year or year + 1}-02-20", "form": "10-K"}


def make_cf(years=range(2008, 2019), op=100.0, ni=60.0, eq=300.0, liab=200.0, rev=1000.0, ocf=90.0,
            capex=30.0, div=20.0, shares=None):
    gaap = {
        "OperatingIncomeLoss": {"units": {"USD": [_fy(y, op) for y in years]}},
        "NetIncomeLoss": {"units": {"USD": [_fy(y, ni) for y in years]}},
        "Revenues": {"units": {"USD": [_fy(y, rev) for y in years]}},
        "StockholdersEquity": {"units": {"USD": [_inst(y, eq) for y in years]}},
        "Liabilities": {"units": {"USD": [_inst(y, liab) for y in years]}},
        "NetCashProvidedByUsedInOperatingActivities": {"units": {"USD": [_fy(y, ocf) for y in years]}},
        "PaymentsToAcquirePropertyPlantAndEquipment": {"units": {"USD": [_fy(y, capex) for y in years]}},
        "PaymentsOfDividendsCommonStock": {"units": {"USD": [_fy(y, div) for y in years]}},
    }
    dei = {"EntityCommonStockSharesOutstanding": {"units": {"shares": shares or [
        {"end": f"{y + 1}-02-01", "val": 10.0, "filed": f"{y + 1}-02-20", "form": "10-K"} for y in years]}}}
    return {"facts": {"us-gaap": gaap, "dei": dei}}


def test_pit_uses_only_filed_values_and_latest_restatement():
    cf = make_cf()
    cf["facts"]["us-gaap"]["NetIncomeLoss"]["units"]["USD"].append(_fy(2015, 999.0, filed_year=2018))  # 2018년 정정
    ann = annual_rows(facts_frame(cf))
    before = pit(ann, "net_income", pd.Timestamp("2017-06-30"))
    after = pit(ann, "net_income", pd.Timestamp("2018-06-30"))
    assert before[pd.Timestamp("2015-12-31")] == 60.0
    assert after[pd.Timestamp("2015-12-31")] == 999.0
    assert pd.Timestamp("2017-12-31") not in before.index  # 아직 제출 전


def test_snapshot_needs_seven_years_for_b1():
    ann = annual_rows(facts_frame(make_cf(years=range(2010, 2019))))
    assert snapshot_metrics(ann, pd.Timestamp("2016-03-01"))["b1"] is None   # 2010~2015: 6년
    m = snapshot_metrics(ann, pd.Timestamp("2017-03-01"))                   # 2010~2016: 7년
    assert m["b1"] is True
    assert m["b2"] is True and m["roe3"] == pytest.approx([0.2, 0.2, 0.2])
    assert m["de"] == pytest.approx(200 / 300)
    assert m["om"] == pytest.approx(0.1) and m["nm"] == pytest.approx(0.06)
    assert m["retained5"] == pytest.approx(5 * (60 - 20))
    assert m["b6"] is True


def test_one_loss_year_fails_b1_and_negative_equity_fails_b2():
    cf = make_cf()
    cf["facts"]["us-gaap"]["OperatingIncomeLoss"]["units"]["USD"][-3] = _fy(2016, -5.0)
    cf["facts"]["us-gaap"]["StockholdersEquity"]["units"]["USD"][-1] = _inst(2018, -50.0)
    m = snapshot_metrics(annual_rows(facts_frame(cf)), pd.Timestamp("2019-06-30"))
    assert m["b1"] is False
    assert m["b2"] is False and m["neg_equity"] and m["de"] is None


def test_market_cap_adjusts_for_split_after_share_count():
    shares = [{"end": "2019-02-01", "val": 100.0, "filed": "2019-02-20", "form": "10-K"}]
    rows = facts_frame(make_cf(shares=shares))
    days = pd.bdate_range("2019-01-01", "2020-12-31")
    # 2020-06-01에 4:1 분할. 분할 보정 종가는 과거가 1/4로 낮아져 있음 (명목 40 → 보정 10)
    close_adj = pd.Series(np.where(days < "2020-06-01", 10.0, 11.0), index=days)
    splits = pd.Series(0.0, index=days)
    splits[pd.Timestamp("2020-06-01")] = 4.0
    cum = cum_split_factor(splits)
    mc = market_cap(rows, close_adj, cum, pd.Timestamp("2019-06-28"))
    assert mc == pytest.approx(100 * 40.0)  # 분할 전 주식수 100 × 명목 종가 40


def test_latest_shares_falls_back_to_diluted_and_rejects_stale():
    cf = make_cf(shares=[{"end": "2012-02-01", "val": 7.0, "filed": "2012-02-20", "form": "10-K"}])
    cf["facts"]["us-gaap"]["WeightedAverageNumberOfDilutedSharesOutstanding"] = {
        "units": {"shares": [_fy(2018, 12.0)]}}
    rows = facts_frame(cf)
    assert latest_shares(rows, pd.Timestamp("2012-06-01")) == (7.0, pd.Timestamp("2012-02-01"))
    assert latest_shares(rows, pd.Timestamp("2019-06-01")) == (12.0, pd.Timestamp("2019-02-20"))
    assert latest_shares(rows, pd.Timestamp("2016-06-01")) == (None, None)  # 둘 다 오래됨/없음


def test_evaluate_sector_median_and_daily_mask():
    good = facts_frame(make_cf(op=150.0, ni=90.0, liab=100.0))   # 이익률↑ 부채↓
    weak = facts_frame(make_cf(op=50.0, ni=30.0, liab=600.0))
    mid = facts_frame(make_cf())
    rows = {"GOOD": good, "WEAK": weak, "MID": mid}
    snaps = {t: build_snapshots(r) for t, r in rows.items()}
    days = pd.bdate_range("2012-01-02", "2019-12-31")
    closes = pd.DataFrame({t: pd.Series(np.linspace(10, 200, len(days)), index=days) for t in rows})
    splits = pd.DataFrame(0.0, index=days, columns=list(rows))
    sectors = pd.Series({"GOOD": "IT", "WEAK": "IT", "MID": "IT"})
    ckpts = pd.DatetimeIndex(["2019-03-31", "2019-06-30"])
    qual, rec = evaluate(snaps, rows, sectors, closes, splits, ckpts)
    assert bool(qual.loc[pd.Timestamp("2019-06-30"), "GOOD"])
    assert not bool(qual.loc[pd.Timestamp("2019-06-30"), "WEAK"])
    r = rec[(rec.ticker == "WEAK") & (rec.checkpoint == pd.Timestamp("2019-06-30"))].iloc[0]
    assert all(r[k] is not None and not r[k] for k in ("b2", "b3", "b4"))  # 미충족(미확인 아님)
    mask = daily_mask(qual, pd.bdate_range("2019-03-29", "2019-04-03"))
    assert not mask.loc[pd.Timestamp("2019-03-29"), "GOOD"]   # 첫 체크포인트 이전
    assert mask.loc[pd.Timestamp("2019-04-01"), "GOOD"]       # 체크포인트 다음 날부터
