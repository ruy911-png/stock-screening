import numpy as np
import pandas as pd
import pytest

from bt.universe import build, holdings_to_spec, norm_ticker, parse_spec, read_ishares_holdings, ticker_cik_map

XLS = """<?xml version="1.0"?>
<ss:Workbook xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet">
<ss:Worksheet ss:Name="Disclaimers"><ss:Table><ss:Row>
<ss:Cell ss:HRef="https://example.com/?a=1&b=2"><ss:Data ss:Type="String">personal use only</ss:Data></ss:Cell>
</ss:Row></ss:Table></ss:Worksheet>
<ss:Worksheet ss:Name="Holdings"><ss:Table>
<ss:Row><ss:Cell><ss:Data ss:Type="String">10/02/2026</ss:Data></ss:Cell></ss:Row>
<ss:Row><ss:Cell><ss:Data ss:Type="String">Fund Holdings as of</ss:Data></ss:Cell><ss:Cell><ss:Data ss:Type="String">Oct 02, 2026</ss:Data></ss:Cell></ss:Row>
<ss:Row>{head}</ss:Row>
{rows}
</ss:Table></ss:Worksheet>
</ss:Workbook>
"""
COLS = ["Ticker", "Name", "Sector", "Asset Class", "Market Value", "Weight (%)", "Exchange"]
DATA = [
    ["SMALL", "SMALL CO", "Industrials", "Equity", "10", "0.01", "NYSE"],
    ["BIG", "BIG CO", "Communication", "Equity", "90", "0.90", "NASDAQ"],
    ["BRK B", "BERKSHIRE CLASS B", "Financials", "Equity", "50", "0.50", "NYSE"],
    ["VYLR WI", "WHEN ISSUED", "Industrials", "Equity", "5", "0.05", "NYSE"],
    ["UWMC RTWI", "RIGHTS", "Financials", "Equity", "1", "0.001", "NYSE"],
    ["HOLX", "UNLISTED", "Health Care", "Equity", "0", "0", "NO MARKET (E.G. UNLISTED)"],
    ["USD", "CASH", "Cash and/or Derivatives", "Cash", "3", "0.03", "--"],
    ["ESZ6", "S&amp;P500 EMINI", "Cash and/or Derivatives", "Futures", "0", "0", "Index And Options Market"],
]


def _cells(values):
    return "".join(f'<ss:Cell><ss:Data ss:Type="String">{v}</ss:Data></ss:Cell>' for v in values)


def test_norm_ticker_unifies_class_separators():
    assert norm_ticker("BRK B") == norm_ticker("brk.b") == norm_ticker("BRK/B") == "BRK-B"


def test_parse_spec_keeps_order_and_maps_sectors():
    df = parse_spec(" nvda:it, BRK B:fn ,HEI.A:IN\n")
    assert list(df.index) == ["NVDA", "BRK-B", "HEI-A"]
    assert list(df["sector"]) == ["Information Technology", "Financials", "Industrials"]
    assert list(df["rank"]) == [1, 2, 3]


def test_parse_spec_rejects_bad_input_without_echoing_it():
    with pytest.raises(ValueError) as e:
        parse_spec("AAA:IT,SECRETTKR:XX")
    assert "SECRETTKR" not in str(e.value)  # Secret 내용은 로그에 남기지 않는다
    with pytest.raises(ValueError):
        parse_spec("  ")


def test_ticker_cik_map_normalizes_tickers():
    m = ticker_cik_map({"0": {"cik_str": 320193, "ticker": "AAPL"}, "1": {"cik_str": 1067983, "ticker": "BRK.B"}})
    assert m == {"AAPL": 320193, "BRK-B": 1067983}


def test_build_drops_sp500_companies_financials_and_extra_share_classes():
    spec = parse_spec("AAA:IT,BRK-B:FN,GOOG:CM,FOXA:CM,HEI:IN,HEI-A:IN,ZZZ:HC,NEW:IT,BF-A:CS")
    sp = pd.DataFrame({"cik": [1652044, 1652044, 14693, 1754301]}, index=["GOOGL", "GOOG", "BF.B", "FOX"])
    ciks = {"AAA": 1, "HEI": 4, "HEI-A": 4, "FOXA": 1754301, "ZZZ": 5, "BF-A": 14693}
    uni, counts = build(spec, ciks, sp)
    assert list(uni.index) == ["AAA", "HEI", "ZZZ", "NEW"]       # 순서(비중 큰 순) 유지
    assert list(uni["rank"]) == [1, 2, 3, 4]                     # 제외 후 다시 매긴 순위
    assert np.isnan(uni.at["NEW", "cik"]) and uni.at["HEI", "cik"] == 4
    assert counts["S&P 500과 같은 티커·클래스"] == 2              # GOOG, BF-A(BF.B와 같은 회사)
    assert counts["금융"] == 1
    assert counts["S&P 500과 같은 회사(CIK)"] == 1                # FOXA(FOX와 CIK 같음)
    assert counts["같은 회사 다른 클래스"] == 1                    # HEI-A
    assert counts["CIK 못 찾음(재무 미확인)"] == 1 and counts["최종"] == 4
    assert set(uni.columns) >= {"yahoo", "sector", "cik", "rank"}


def test_ishares_xls_to_spec(tmp_path):
    path = tmp_path / "IWB.xls"
    path.write_text(XLS.format(head=_cells(COLS), rows="\n".join(f"<ss:Row>{_cells(r)}</ss:Row>" for r in DATA)),
                    encoding="utf-8")
    spec, counts = holdings_to_spec(read_ishares_holdings(path))
    assert spec == "BIG:CM,BRK-B:FN,SMALL:IN"  # 비중 큰 순, 클래스 표기 정리, 금융은 여기서 빼지 않는다
    assert counts["주식"] == 6 and counts["권리·발행 전·비상장 제외"] == 3


def test_ishares_csv_to_spec(tmp_path):
    path = tmp_path / "IWB.csv"
    lines = ["iShares Russell 1000 ETF", "Fund Holdings as of,\"Oct 02, 2026\"", "", ",".join(COLS)]
    lines += [",".join(r) for r in DATA[:3]]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    spec, _ = holdings_to_spec(read_ishares_holdings(path))
    assert spec == "BIG:CM,BRK-B:FN,SMALL:IN"
