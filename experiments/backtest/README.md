# 시험: SEPA 실행 확인 · 버핏 × 볼린저 I·II·III 백테스트 (미장)

> 앱 본 구현이 아니라 사용자 요청(2026-10-05) 시험용 코드다. 결과는 **스크리닝 결과(통계용)**이며 매수·매도 권유가 아니다.
> 숫자는 모두 코드가 계산한다. 아래 '임시값'은 PRD 미결 질문이 정해지면 바꾼다.

## 무엇을 하나
| 스크립트 | 내용 | 결과 파일 |
|---|---|---|
| `run_sepa.py` | 지금 시세로 SEPA Trend Template(명세 §3.2, 코드 부분)이 제대로 도는지 확인 — 단계별 통과 수, 통과 종목, 자체 검산 | `results/sepa_screen.md`, `sepa_screen_all.csv` |
| `run_oscillators.py` | 버핏 숫자 필터 × RSI·스토캐스틱·윌리엄스 %R 과매수·과매도 신호(+ PRD (b)안 참고) | `results/oscillators.md`, `oscillators_stats.csv`, `oscillators_events.csv` |
| `run_oversold.py` | 과매도 매수 진입 변형(RSI 30 재돌파, 스토캐스틱 과매도 골든크로스, 윌리엄스 %R −80 재돌파, 시장 상승 조건) — 버핏 유무 | `results/oversold.md`, `oversold_stats.csv`, `oversold_events.csv` |
| `run_bb_rsi.py` | 버핏 × 볼린저+RSI 조합(하단 이탈 + RSI<30, Method I 돌파 + RSI>50) | `results/bb_rsi.md`, `bb_rsi_stats.csv`, `bb_rsi_events.csv` |
| `run_backtest.py` | 버핏 숫자 필터 × 볼린저 Method I·II·III(+ 참고 I+II) 신호의 5·10·20거래일 수익률 비교, 기준선(유니버스·버핏 통과 종목·SPY) | `results/backtest.md`, `backtest_stats.csv`, `backtest_events.csv`, `buffett_checkpoints.csv` |

## 실행
```
pip install -r requirements.txt
python -m pytest -q tests            # 가상 데이터 검사 (네트워크 불필요)
python run_sepa.py --out results
SEC_USER_AGENT="이름 연락처" python run_backtest.py --out results
```
네트워크 필요: raw.githubusercontent.com(구성종목), query1·query2.finance.yahoo.com·fc.yahoo.com(일봉), data.sec.gov(재무).

## 데이터
- 유니버스: [datasets/s-and-p-500-companies](https://github.com/datasets/s-and-p-500-companies) 현재 구성종목(GICS 섹터·CIK). 백테스트는 금융 섹터 제외(명세: 금융업 별도 처리 미결).
- 일봉: 야후(yfinance, 비공식) 분할 보정 OHLCV. 배당 미포함 가격 수익률(PRD Q14 미정).
- 재무: SEC EDGAR companyfacts(10-K 계열 연간값). 그 시점에 제출된 값만 사용(point-in-time).

## 임시값 (출처 없는 값은 이 시험에서 정한 것)
| 항목 | 값 | 근거 |
|---|---|---|
| SEPA 유니버스(미장) | S&P 500 전체 | PRD Q19 미정 → 임시 |
| SEPA 200일선 상승 | 오늘 MA200 > 22거래일 전 | PRD 참고값(최소 1개월), Q20 |
| SEPA 52주 저점 대비 | +30% 이상 | PRD 참고값(+25~30%), Q20 |
| SEPA RS | 0.4·3개월+0.2·6개월+0.2·9개월+0.2·12개월 수익률의 유니버스 내 백분위 ≥ 70 | IBD식 근사, Q20 |
| 52주 고·저 | 종가 기준 252거래일 | 명세 '종가 기준' |
| 볼린저 밴드 | 20일, ±2σ(모집단) | 명세 §2.1 |
| Method I | 직전 20거래일 안 Squeeze일(BandWidth 125거래일 최저) + 종가가 처음 UB 위 | 명세 §2.2 조건 3·4 |
| Method II | %b > 0.8 그리고 MFI(10) > 80이 처음 함께 성립 | 명세(2차 출처) |
| Method III | 하단 밖 종가(첫 저점) → %b 0.5 이상 반등 → 첫 저점 종가 +3% 이내·밴드 안 둘째 저점 → 그 사이 최고 종가 돌파. 첫 저점부터 60거래일 이내. 거래량 지표 확인 생략 | **이 시험의 단순화**(원전 정량 정의 없음) |
| I+II | Q41 기본안(창 안 Squeeze → UB 돌파 → %b > 0.8·MFI > 80) | 명세 §2.2, 참고용 |
| 과매수·과매도 | RSI(14) 30/70 · 스토캐스틱(14,3,3) 느린 %K 20/80 · 윌리엄스 %R(14) −80/−20, 조건이 처음 성립한 날 | 통상 기준(사용자 요청: RSI·스토캐스틱·윌리엄스 %R) |
| (b)안 | 종가 > 200일선 · 6개월 수익률 > 0 · RSI(2) < 10 | PRD §9.1 제안 |
| 시장 상승 | 그날 SPY 종가 > SPY 200일선 | 임시 기준 |
| 수익률 | 신호일 종가 → 5·10·20거래일 뒤 종가 | 스윙 기준 임시(PRD Q56 ③) |
| 겹침 방지 | 같은 종목·전략은 신호 뒤 20거래일 동안 새 신호 안 셈 | 임시 |
| 신호 기간 | 2016-01-01 ~ 마지막 일봉 − 20거래일 | 재무 7년 이력 확보 시점 |
| 버핏 판정 주기 | 월말 판정 → 다음 날부터 적용 | 임시 |

## 버핏 필터 근사·생략 (명세 §3 대비)
- 해자 원천·지속성(LLM 판단) 제외 — 과거 시점 재현 불가(모델이 이후 결과를 앎).
- TTM 영업이익·현재 ROE 생략, 연간값만.
- 부채비율 = 총부채 ÷ 자기자본(총부채 태그 없으면 부채와자본총계 − 자기자본). 자본 음수면 미충족.
- 업종 중앙값 = 같은 유니버스의 GICS 섹터 중앙값, 현재 섹터 분류를 과거에도 적용.
- 1달러 테스트 = 5년 시가총액 증가 ≥ 최근 5개 회계연도 (순이익 − 배당) 합. 배당 태그 없으면 0. 시가총액 = 그때 공개된 발행주식수 × 종가(분할 기준 맞춤).
- 시가총액 ≥ $10억 생략(S&P 500), 후보 정렬·최대 3종목 선정(LLM) 생략 — 통과 종목의 신호를 모두 센다.
- 태그가 없어 계산 못 하면 미확인 → 통과 안 함. 조건별 미확인 비율은 결과 파일에 표시.

## 한계 (결과 해석 시 주의)
- 현재 구성종목만 써서 생존편향이 있다(상장폐지·편출 종목 없음) — 모든 행의 수익률이 위로 치우칠 수 있다.
- 같은 날 여러 종목 신호, 겹치는 보유 기간 때문에 표준오차는 실제보다 작게 나온다.
- 임시값을 바꾸면 결과가 달라진다. 여러 방법을 비교했으므로 우연히 좋아 보이는 결과가 섞일 수 있다.
- 거래비용·세금·슬리피지 미반영. 신호일 종가에 산다고 가정.
