# 출처 접속 시험 — 2026-10-05 03:56 UTC (GitHub Actions)

원칙: robots.txt가 막은 경로는 요청 안 함 · 출처당 1~3회 · 정직한 User-Agent · 키 필요한 API는 키 없이 응답만 확인.

## 안 되는 것 (8)
- **미장 SEC 티커→CIK 표** (CIK 조회): 안 됨 — HTTP 403 — User-Agent: stock-screening backtest research github.com/ruy911-png/stock-screening
- **미장 SEC EDGAR (ANET)** (공시 재무(분기·연간)): 안 됨 — HTTP 403
- **미장 SEC EDGAR (APH)** (공시 재무(분기·연간)): 안 됨 — HTTP 403
- **미장 SEC EDGAR (TSM)** (공시 재무(분기·연간)): 안 됨 — HTTP 403
- **국장 Investing.com (www, 삼성전자)** (일봉): 안 됨 — HTTP 403
- **국장 Investing.com (kr, 삼성전자)** (일봉): 안 됨 — HTTP 403
- **국장 한국경제 Markets 종목 페이지** (일봉): 안 됨 — HTTP 404 — 종목 페이지 주소는 추정
- **국장 네이버 모바일 (005930) — 참고(주식킹 방식)** (일봉 종가): 안 됨 — robots.txt가 막음(요청 안 함) — 비공식 API

## 키를 발급받아야 되는 것 (2)
- **국장 DART OpenAPI** (공시 재무·기업정보): 키 필요 — 인증키 발급 후 사용
- **국장 KRX Open API** (유가증권 일별매매정보): 키 필요 — 인증키 발급·서비스 신청 후 사용 — 키 승인 약 1영업일(검색 결과)

## 일부만 되는 것 (0)

## 전체 결과
| 시장 | 출처 | 용도 | robots.txt | HTTP | 받은 데이터 | 판정 | 메모 |
|---|---|---|---|---|---|---|---|
| 미장 | StockAnalysis.com (ANET) | 일봉 OHLC·거래량 | 허용 | 200 | 종가 표 50행, 최근 2026-10-02 | 기술적으로 됨 | 약관: 자동 수집·대량 다운로드 금지(robots.txt 따르는 크롤러 예외) — 검색 요약 |
| 미장 | TrendScreeners.com | Trend Template·RS 계산값 | 허용 | 200 | 페이지 제목: 트렌드 스크리너 — 미국·국내 주식 조건 검색기 · 업종 랭킹 · 시장 환경 | 접속됨 |  |
| 미장 | Arista IR | 실적·가이던스 | 허용 | 200 | 제목: Arista Networks - Home · PDF 링크 8개 · '실적' 단어 8회 | 접속됨 — 숫자는 보도자료(HTML/PDF), 회사마다 형식 다름 |  |
| 미장 | Amphenol IR | 실적·가이던스 | 허용 | 200 | 제목: Amphenol Corporation - Investor Relations · PDF 링크 10개 · '실적' 단어 16회 | 접속됨 — 숫자는 보도자료(HTML/PDF), 회사마다 형식 다름 |  |
| 미장 | TSMC IR | 실적·가이던스 | 허용 | 200 | 제목: TSMC 2026 Q3 Quarterly Results - Taiwan Semiconductor Manufa · PDF 링크 2개 · '실적' 단어 242회 | 접속됨 — 숫자는 보도자료(HTML/PDF), 회사마다 형식 다름 |  |
| 미장 | SEC 티커→CIK 표 | CIK 조회 | - | 403 |          SEC.gov | Request Rate Threshold Exceeded    html {height: 100%} body {height: 100%; margin | 안 됨 — HTTP 403 | User-Agent: stock-screening backtest research github.com/ruy911-png/stock-screening |
| 미장 | SEC EDGAR (ANET) | 공시 재무(분기·연간) | - | 403 |          SEC.gov | Your Request Originates from an Undeclared Automated Tool    html {height: 100%}  | 안 됨 — HTTP 403 |  |
| 미장 | SEC EDGAR (APH) | 공시 재무(분기·연간) | - | 403 |          SEC.gov | Your Request Originates from an Undeclared Automated Tool    html {height: 100%}  | 안 됨 — HTTP 403 |  |
| 미장 | SEC EDGAR (TSM) | 공시 재무(분기·연간) | - | 403 |          SEC.gov | Your Request Originates from an Undeclared Automated Tool    html {height: 100%}  | 안 됨 — HTTP 403 |  |
| 미장 | 야후 yfinance (ANET) — 참고 | 일봉(현재 시험 코드 원천) | - | 200 | 44일, 최근 2026-10-02 | 됨 |  |
| 국장 | Investing.com (www, 삼성전자) | 일봉 | 허용 | 403 | Just a moment... | 안 됨 — HTTP 403 |  |
| 국장 | Investing.com (kr, 삼성전자) | 일봉 | 허용 | 403 | Just a moment... | 안 됨 — HTTP 403 |  |
| 국장 | 한국경제 Markets | 시세 | 허용 | 200 | 페이지 제목: 시장종합 | 한국경제 | 접속됨 |  |
| 국장 | 한국경제 Markets 종목 페이지 | 일봉 | 허용 | 404 | This page could not be found | 안 됨 — HTTP 404 | 종목 페이지 주소는 추정 |
| 국장 | DART OpenAPI | 공시 재무·기업정보 | - | 200 | status 010 · 등록되지 않은 인증키입니다. | 키 필요 — 인증키 발급 후 사용 |  |
| 국장 | KRX Open API | 유가증권 일별매매정보 | - | 401 | {"respMsg":"Unauthorized Key","respCode":"401"} | 키 필요 — 인증키 발급·서비스 신청 후 사용 | 키 승인 약 1영업일(검색 결과) |
| 국장 | KRX 정보데이터시스템 via pykrx (005930) | 일봉 OHLCV | - | 200 | 29일, 최근 2026-10-02 | 됨 | pykrx README: 일부 기능 KRX 로그인 필요 |
| 국장 | KIND | 시장경보 공시 | 허용(robots.txt 없음 404) | 200 | 페이지 제목: ëíë¯¼êµ­ ëí ê¸°ì ê³µìì±ë KIND | 접속됨 |  |
| 국장 | KRX 시장감시위원회 | 시장경보 조회 | 허용(robots.txt 없음 404) | 200 | 페이지 제목: Surveillance | 접속됨 |  |
| 국장 | 연합뉴스 | 보조 실적·뉴스 | 허용 | 200 | 페이지 제목: 연합뉴스 | 접속됨 | 앱은 직접 수집 대신 팩트체크 검색으로 사용 예정 |
| 국장 | 네이버 모바일 (005930) — 참고(주식킹 방식) | 일봉 종가 | 막힘 | - | - | 안 됨 — robots.txt가 막음(요청 안 함) | 비공식 API |

## 원천끼리 종가 대조
- ANET 야후 vs StockAnalysis: 겹치는 44일, 종가 최대 차이 0.0000% (최근 2026-10-02: 야후 207.35 / StockAnalysis 207.35)
- 삼성전자 KRX(pykrx) vs 네이버: 비교 못 함(네이버 데이터 없음)
