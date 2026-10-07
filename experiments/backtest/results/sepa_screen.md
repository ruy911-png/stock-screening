# SEPA Trend Template 실행 확인 — 스크리닝 결과(통계용)

- 기준일(종가): **2026-10-02** · 유니버스: S&P 500 현재 구성종목 503개(임시, PRD Q19 미정)
- 데이터: 야후(yfinance) 분할 보정 종가 · 받지 못한 종목 0개
- 범위: 코드가 계산하는 Trend Template(명세 §3.2)만. VCP·피벗·손절·R/R(LLM 판정)과 펀더멘털은 제외
- 임시 수치(PRD Q20 미정): 200일선 상승 = 22거래일 전 대비, 52주 저점 +30% 이상, RS = 0.4·3개월+0.2·6개월+0.2·9개월+0.2·12개월 수익률의 S&P 500 내 백분위 ≥ 70
- 매수·매도 권유가 아니다.

## 단계별 통과 수 (누적)
| 단계 | 종목 수 |
|---|---:|
| 대상 종목(S&P 500) | 503 |
| 일봉 받음 | 503 |
| 기준일 데이터 정상 | 500 |
| + c1 종가 > MA50·MA150·MA200 | 102 |
| + c2 MA50 > MA150 > MA200 | 65 |
| + c3 MA200 상승(22거래일 전 대비) | 65 |
| + c4 종가 ≥ 52주 저점 × 1.30 | 63 |
| + c5 종가 ≥ 52주 고점 × 0.75 | 59 |
| + c6 RS 백분위 ≥ 70 | 59 |

## 조건별 단독 통과 수 (기준일 데이터 정상 종목 중)
| 조건 | 종목 수 |
|---|---:|
| c1 종가 > MA50·MA150·MA200 | 102 |
| c2 MA50 > MA150 > MA200 | 192 |
| c3 MA200 상승(22거래일 전 대비) | 307 |
| c4 종가 ≥ 52주 저점 × 1.30 | 187 |
| c5 종가 ≥ 52주 고점 × 0.75 | 360 |
| c6 RS 백분위 ≥ 70 | 151 |

## 모든 조건 통과 — 59종목 (RS 순)
| 종목 | 회사 | 섹터 | 종가 | 52주 저점 대비 | 52주 고점 대비 | RS |
|---|---|---|---:|---:|---:|---:|
| MRNA | Moderna | Health Care | 190.01 | +749.8% | -6.6% | 100 |
| MU | Micron Technology | Information Technology | 1074.89 | +491.9% | -11.4% | 100 |
| DELL | Dell Technologies | Information Technology | 562.52 | +406.5% | -4.4% | 99 |
| LITE | Lumentum | Information Technology | 1085.42 | +625.5% | +0.0% | 99 |
| AMD | Advanced Micro Devices | Information Technology | 633.91 | +285.0% | +0.0% | 99 |
| HPE | Hewlett Packard Enterprise | Information Technology | 69.33 | +246.7% | +0.0% | 99 |
| MRVL | Marvell Technology | Information Technology | 272.29 | +269.3% | -13.9% | 99 |
| INTC | Intel | Information Technology | 119.33 | +254.9% | -15.3% | 98 |
| BE | Bloom Energy | Industrials | 289.15 | +275.7% | -16.4% | 98 |
| CRWD | CrowdStrike | Information Technology | 270.04 | +208.4% | +0.0% | 98 |
| ILMN | Illumina, Inc. | Health Care | 273.04 | +200.0% | -0.3% | 98 |
| MPC | Marathon Petroleum | Energy | 422.33 | +159.7% | -0.6% | 97 |
| VLO | Valero Energy | Energy | 406.30 | +159.8% | -1.7% | 97 |
| P | Everpure | Information Technology | 140.14 | +145.9% | +0.0% | 97 |
| TER | Teradyne | Information Technology | 449.04 | +240.0% | -7.2% | 97 |
| NTAP | NetApp | Information Technology | 226.27 | +140.4% | +0.0% | 97 |
| PANW | Palo Alto Networks | Information Technology | 403.24 | +184.6% | +0.0% | 96 |
| FTNT | Fortinet | Information Technology | 180.95 | +140.5% | +0.0% | 96 |
| PSX | Phillips 66 | Energy | 264.58 | +108.7% | -3.5% | 96 |
| DDOG | Datadog | Information Technology | 277.22 | +170.2% | -3.8% | 96 |
| LRCX | Lam Research | Information Technology | 347.49 | +164.5% | -19.8% | 95 |
| KEYS | Keysight Technologies | Information Technology | 384.64 | +141.2% | +0.0% | 95 |
| RVTY | Revvity | Health Care | 151.53 | +84.2% | -0.9% | 95 |
| ZBRA | Zebra Technologies | Information Technology | 375.86 | +88.6% | -1.9% | 94 |
| CRL | Charles River Laboratories | Health Care | 290.19 | +93.6% | -2.8% | 94 |
| APA | APA Corporation | Energy | 43.68 | +101.7% | -7.9% | 94 |
| HUM | Humana | Health Care | 388.36 | +137.3% | -5.2% | 93 |
| HPQ | HP Inc. | Information Technology | 32.12 | +76.5% | -9.5% | 93 |
| TGT | Target Corporation | Consumer Staples | 156.00 | +86.4% | -8.2% | 93 |
| ANET | Arista Networks | Information Technology | 207.35 | +78.5% | -1.5% | 93 |
| FFIV | F5, Inc. | Information Technology | 454.04 | +102.7% | -0.4% | 92 |
| FCX | Freeport-McMoRan | Materials | 72.04 | +86.4% | -9.8% | 92 |
| TXN | Texas Instruments | Information Technology | 293.80 | +91.6% | -11.6% | 91 |
| SWKS | Skyworks Solutions | Information Technology | 85.03 | +62.0% | -7.0% | 91 |
| VTRS | Viatris | Health Care | 17.60 | +80.7% | -3.7% | 90 |
| EXPD | Expeditors International | Industrials | 192.47 | +70.1% | -0.7% | 90 |
| TRGP | Targa Resources | Energy | 281.74 | +92.6% | -6.8% | 90 |
| CSCO | Cisco | Information Technology | 112.20 | +66.3% | -13.7% | 89 |
| MRK | Merck & Co. | Health Care | 144.30 | +74.9% | -7.8% | 89 |
| NDSN | Nordson Corporation | Industrials | 333.54 | +47.1% | -0.3% | 88 |
| DE | Deere & Company | Industrials | 687.00 | +56.5% | -3.2% | 88 |
| XOM | ExxonMobil | Energy | 164.01 | +48.2% | -4.4% | 87 |
| NVDA | Nvidia | Information Technology | 233.95 | +41.6% | -0.8% | 87 |
| CVX | Chevron Corporation | Energy | 206.69 | +40.8% | -5.1% | 86 |
| WST | West Pharmaceutical Services | Health Care | 364.98 | +58.0% | -3.1% | 86 |
| APH | Amphenol | Information Technology | 86.96 | +46.0% | -1.4% | 85 |
| JCI | Johnson Controls | Industrials | 156.24 | +48.0% | +0.0% | 85 |
| BBY | Best Buy | Consumer Discretionary | 87.97 | +58.4% | -7.2% | 84 |
| IEX | IDEX Corporation | Industrials | 232.99 | +44.9% | -3.1% | 84 |
| BIIB | Biogen | Health Care | 219.88 | +54.6% | -3.9% | 83 |
| DVN | Devon Energy | Energy | 47.65 | +50.1% | -8.5% | 83 |
| AAPL | Apple Inc. | Information Technology | 333.69 | +36.1% | -2.2% | 83 |
| URI | United Rentals | Industrials | 1081.04 | +52.2% | -7.2% | 81 |
| ETN | Eaton Corporation | Industrials | 436.11 | +38.1% | -5.2% | 80 |
| AME | Ametek | Industrials | 251.93 | +40.5% | -2.5% | 80 |
| DAL | Delta Air Lines | Industrials | 84.09 | +51.1% | -10.2% | 79 |
| GILD | Gilead Sciences | Health Care | 144.74 | +30.9% | -7.1% | 77 |
| ROK | Rockwell Automation | Industrials | 454.35 | +36.1% | -8.2% | 72 |
| ABBV | AbbVie | Health Care | 262.82 | +33.2% | -1.3% | 71 |

## 자체 검산 (통과 종목을 pandas 없이 다시 계산해 대조)
- 결과: 불일치 없음

## 데이터 점검
- 기준일 데이터 없음(마지막 일봉 ≠ 기준일 또는 기간 부족): 3종목 — FDXF, HONA, Q
- 최근 1년 이상치 표시 종목: 2개
  - CTVA: 분할 없는 ±50% 변동 1일 (첫날 2026-10-01)
  - MRNA: 분할 없는 ±50% 변동 1일 (첫날 2026-08-19)
