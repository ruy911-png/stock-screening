"""SEC EDGAR companyfacts → 연간 재무를 '그 시점에 공개된 값'으로 꺼낸다.

- 연간 값: 10-K 계열 제출물의 기간 350~380일 사실(fact)만 쓴다.
- 시점 기준: 기준일(asof) 이전에 제출(filed)된 값만 쓰고, 같은 회계기간 값이 여러 번 제출됐으면
  asof 이전 마지막 제출값(정정 반영)을 쓴다. 같은 날 여러 태그면 TAGS 순서가 앞선 태그.
- 태그가 없으면 결측(미확인)으로 둔다. 대체값을 지어내지 않는다.
"""
from __future__ import annotations

import gzip
import json
import time
from pathlib import Path

import pandas as pd

FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
DEFAULT_UA = "stock-screening backtest research github.com/ruy911-png/stock-screening"
ANNUAL_FORMS = ("10-K", "10-K/A", "10-KT", "10-KT/A")
CACHE_DAYS = 7  # 받아 둔 재무는 일주일 안에서만 다시 쓴다(새 10-K 반영)

TAGS = {
    "revenue": ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet",
                "RevenueFromContractWithCustomerIncludingAssessedTax", "SalesRevenueGoodsNet",
                "SalesRevenueServicesNet"],
    "op_income": ["OperatingIncomeLoss"],
    "net_income": ["NetIncomeLoss", "ProfitLoss", "NetIncomeLossAvailableToCommonStockholdersBasic"],
    "ocf": ["NetCashProvidedByUsedInOperatingActivities",
            "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"],
    "capex": ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets",
              "PaymentsForCapitalImprovements"],
    "dividends": ["PaymentsOfDividendsCommonStock", "PaymentsOfDividends", "DividendsCommonStockCash",
                  "DividendsCommonStock", "DividendsCash"],
    "equity": ["StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"],
    "liabilities": ["Liabilities"],
    "liab_and_equity": ["LiabilitiesAndStockholdersEquity"],
    "shares_diluted": ["WeightedAverageNumberOfDilutedSharesOutstanding"],
}
INSTANT = {"equity", "liabilities", "liab_and_equity"}
SHARE_UNITS = {"shares_diluted"}
COLUMNS = ["concept", "rank", "start", "end", "val", "filed", "form"]


def facts_frame(cf: dict) -> pd.DataFrame:
    """companyfacts JSON → 필요한 사실만 담은 긴 표."""
    rows = []
    gaap = cf.get("facts", {}).get("us-gaap", {})
    for concept, tags in TAGS.items():
        unit = "shares" if concept in SHARE_UNITS else "USD"
        for rank, tag in enumerate(tags):
            for f in gaap.get(tag, {}).get("units", {}).get(unit, []):
                rows.append((concept, rank, f.get("start"), f.get("end"), f.get("val"), f.get("filed"), f.get("form")))
    dei = cf.get("facts", {}).get("dei", {}).get("EntityCommonStockSharesOutstanding", {})
    for f in dei.get("units", {}).get("shares", []):
        rows.append(("shares_out", 0, None, f.get("end"), f.get("val"), f.get("filed"), f.get("form")))
    df = pd.DataFrame(rows, columns=COLUMNS)
    for col in ("start", "end", "filed"):
        df[col] = pd.to_datetime(df[col], errors="coerce")
    df["val"] = pd.to_numeric(df["val"], errors="coerce")
    df = df.dropna(subset=["end", "filed", "val"])
    df["days"] = (df["end"] - df["start"]).dt.days
    return df.reset_index(drop=True)


def annual_rows(df: pd.DataFrame) -> pd.DataFrame:
    """10-K 계열의 연간 기간값 + 회계연도 말 시점값."""
    annual = df["form"].isin(ANNUAL_FORMS)
    duration = ~df["concept"].isin(INSTANT | {"shares_out"}) & df["days"].between(350, 380)
    instant = df["concept"].isin(INSTANT)
    return df[annual & (duration | instant)]


def pit(rows: pd.DataFrame, concept: str, asof: pd.Timestamp) -> pd.Series:
    """concept의 회계기간말(end)별 값 — asof 이전 마지막 제출값."""
    sub = rows[(rows["concept"] == concept) & (rows["filed"] <= asof) & (rows["end"] <= asof)]
    if sub.empty:
        return pd.Series(dtype=float)
    sub = sub.sort_values(["end", "filed", "rank"], ascending=[True, True, False])
    last = sub.groupby("end").tail(1)
    return pd.Series(last["val"].to_numpy(float), index=pd.DatetimeIndex(last["end"]))


def latest_shares(df: pd.DataFrame, asof: pd.Timestamp):
    """asof 이전 제출된 최신 발행주식수와 그 주식수의 기준일(분할 보정용). 없으면 (None, None).

    1순위 dei 표지 발행주식수(기준일 = end), 없으면 직전 회계연도 희석 가중평균 주식수(기준일 = 제출일).
    """
    s = df[(df["concept"] == "shares_out") & (df["filed"] <= asof)]
    if not s.empty:
        row = s.sort_values(["end", "filed"]).iloc[-1]
        if row["end"] >= asof - pd.DateOffset(months=15):
            return float(row["val"]), row["end"]
    d = annual_rows(df)
    d = d[(d["concept"] == "shares_diluted") & (d["filed"] <= asof)]
    if d.empty:
        return None, None
    row = d.sort_values(["end", "filed"]).iloc[-1]
    if row["end"] < asof - pd.DateOffset(months=15):
        return None, None
    return float(row["val"]), row["filed"]


class SecBlocked(RuntimeError):
    """SEC가 접근 정책(User-Agent 등)으로 막음(HTTP 403) — 재시도해도 소용없다."""


def fetch_companyfacts(cik: int, cache_dir: Path, user_agent: str = DEFAULT_UA, session=None,
                       pause: float = 0.12) -> pd.DataFrame | None:
    """companyfacts를 받아 facts_frame으로 줄여 캐시한다. 실패하면 None."""
    cache = Path(cache_dir) / f"sec_{cik:010d}.pkl.gz"
    if cache.exists() and time.time() - cache.stat().st_mtime < CACHE_DAYS * 86400:
        return pd.read_pickle(cache)
    import requests

    sess = session or requests.Session()
    url = FACTS_URL.format(cik=cik)
    resp = None
    for attempt in range(3):
        try:
            resp = sess.get(url, headers={"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"}, timeout=60)
        except requests.RequestException as e:  # 접속 오류는 재시도 후 실패로 보고
            time.sleep(2 * (attempt + 1))
            last_error = type(e).__name__
            continue
        time.sleep(pause)
        if resp.status_code == 200:
            frame = facts_frame(resp.json())
            cache.parent.mkdir(parents=True, exist_ok=True)
            frame.to_pickle(cache)
            return frame
        if resp.status_code == 404:
            return None
        if resp.status_code == 403:
            snippet = " ".join(resp.text.split())[:120]
            has_contact = "@" in user_agent  # User-Agent는 연락처가 들어 있을 수 있어 기록에 남기지 않는다
            raise SecBlocked(f"SEC 403 (CIK {cik}, User-Agent 연락처 {'있음' if has_contact else '없음'}): {snippet}")
        if resp.status_code in (429, 500, 502, 503):
            time.sleep(2 * (attempt + 1))
            continue
        break
    reason = f"HTTP {resp.status_code}" if resp is not None else last_error
    raise RuntimeError(f"SEC companyfacts 실패 CIK {cik}: {reason}")


def load_json_gz(path: Path) -> dict:
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        return json.load(fh)
