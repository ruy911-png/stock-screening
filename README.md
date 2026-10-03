# stock-screening

투자 기법별로 **국장(코스피·코스닥)·미장 각각 최대 3종목**을 스크리닝하고,
선정된 종목의 **사후 수익률**(추천 시점 ~ 현재)을 통계 목적으로 추적하는 앱입니다.

> ⚠️ 이 앱의 결과는 **스크리닝 결과(통계용)**이며 투자 권유나 매수·매도 추천이 아닙니다.

## 현재 상태
**설계 단계 (PRD v0.2)** — 아직 실행 가능한 코드는 없습니다.
요구사항은 [docs/prd/screening-v0.2.md](docs/prd/screening-v0.2.md)에 정리되어 있습니다.

## 기능 (계획)
| 기능 | 내용 |
|---|---|
| 기법별 스크리닝 | 기법마다 국장·미장 각각 최대 3종목 (적격 종목이 없으면 "현재 적격 종목 없음") |
| LLM 수행 | LLM이 도구(데이터 조회·지표 계산·1차 필터)를 호출해 후보 축소 → 최대 3종목 선정 + 이유 기록. 숫자는 도구만 계산 |
| 멀티모델 합의 | Claude·Gemini가 각각 실행 → 둘 다 적격인 종목만 적격, 불일치 시 상호 재검토 |
| 비용 상한 | 실행 1회 LLM 비용 상한 (첫 시험 실행으로 실측 후 확정) |
| 요청 시 실행 | GitHub Actions의 **Run workflow** 버튼으로 실행 (휴대폰 브라우저·GitHub 앱 가능) |
| 기법 선택 | 실행 화면에서 기법별 체크박스로 선택 (기법을 추가하면 체크박스 자동 생성) |
| 범위 제한 | 기법별로 범위 지정, **여러 범위 동시 선택 가능** — 국장 전체·코스피·코스닥·코스피200·코스닥150 / S&P 500·S&P 100·나스닥100·다우30. 공식 구성종목을 못 받으면 ETF 보유 종목으로 근사("근사" 표시) |
| 데이터 | 주식킹(stock-DASHBB)과 같은 네이버 증권 API를 국장·미장 1순위로 사용, 실패 시 대체 소스 |
| 사후 수익률 | 기준가 = **추천 시점 직전 종가**, 추천일 ~ 현재 수익률을 모든 과거 선정 건에 대해 계산 |
| 기법별 통계 | 기법별 선정 수 · 평균/중앙값 수익률 · 상승 비율 |
| 기법 추가 | `strategies/<기법>/` 폴더 추가만으로 새 기법 등록 (플러그인 구조) |

화면은 최소한으로 두고 기능을 우선합니다.

## 스크리닝 기법
| 기법 | 상태 | 명세 |
|---|---|---|
| 기술적 분석 | 진행 | [docs/strategies/technical.md](docs/strategies/technical.md) |
| 워렌 버핏 (경제적 해자 중심) | 진행 | [docs/strategies/buffett-moat.md](docs/strategies/buffett-moat.md) |
| 조지 소로스 (재귀성) | 보류 (명세 완료) | [docs/strategies/soros-reflexivity.md](docs/strategies/soros-reflexivity.md) |
| 마크 미너비니 SEPA | 보류 (명세 완료) | [docs/strategies/minervini-sepa.md](docs/strategies/minervini-sepa.md) |

## 동작 흐름 (계획)
```
Run workflow (기법 선택)
  → 데이터 수집 (국장 / 미장)
  → Claude·Gemini 각각: 도구 호출로 1차 필터 → 판정 (최대 3종목 + 이유)
  → 불일치 시 상호 재검토 → 합의 결과
  → 결과 기록 (선정일 · 직전 종가 · 기법 · 모델별 결과)
  → 과거 선정 전체의 사후 수익률 재계산 → 결과/통계 화면
```

## 미정 사항
아래 항목은 아직 결정되지 않았습니다. 전체 목록은 [PRD v0.2](docs/prd/screening-v0.2.md)의 **미결 질문** 참고.
- 모델 등급(Claude Opus/Sonnet, Gemini 모델명), 실행 1회 비용 최종 상한
- 데이터 소스: 국장 다년 재무(DART Open API 검토 중), 미장(yfinance 검토 중)
- 기법별 기본 범위(제안: 코스피200 / S&P 100), 기술적 분석 지표, 결과 화면 호스팅 방식

## 문서
| 문서 | 내용 |
|---|---|
| [docs/prd/screening-v0.2.md](docs/prd/screening-v0.2.md) | 요구사항 · 합격 기준 · 미결 질문 |
| [docs/architecture.md](docs/architecture.md) | 설계 — 기법 플러그인 · 도구 호출형 LLM · 멀티모델 합의 · 새 기법 추가 절차 |
| [docs/strategies/](docs/strategies/) | 기법별 명세 |
| [docs/backlog.md](docs/backlog.md) | 단계별 작업 목록 · 우선순위 |
| [CLAUDE.md](CLAUDE.md) | 개발 규칙 |

## 개발 방식 (Claude Code 에이전트 팀)
| 역할 | 모델 | 담당 |
|---|---|---|
| 메인 | — | 사용자와 대화 · 작업 분배 · 결과 취합 |
| product-manager | Opus | PRD · 기법 명세 · 백로그 · 최종 확인 |
| architect | Opus | 기술 설계 · 구현 계획 |
| implementer | Sonnet | 코드 구현 · 테스트 작성 |
| tester | Sonnet | 합격 기준 검증 (코드 수정 불가) |

에이전트 정의: [.claude/agents/](.claude/agents/)

## 보안
API 키·계좌번호는 GitHub Secrets(환경변수)로만 다루며 저장소에 커밋하지 않습니다.
