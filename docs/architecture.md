# 아키텍처 설계 — 기법 플러그인 · 도구 호출형 LLM · Claude 1차 → Gemini 2차 검수
- 기준: [PRD v0.2](prd/screening-v0.2.md) · 기법 명세 4종 · 작성: architect · 2026-10-03 · 초안
- 목표: 새 기법 = `strategies/<id>/` 폴더 추가만으로 동작(코어·워크플로 파일 수정 없음). 모든 결과는 "스크리닝 결과(통계용)".

## 1. 설계 원칙
1. **기법 = 폴더 하나**(매니페스트·도구·프롬프트). 코어는 기법 이름을 모르고, 레지스트리가 폴더를 찾아 검증한 뒤 실행 단위(기법×시장)를 만든다.
2. **판단은 LLM, 숫자는 코드**: LLM이 도구를 골라 부르고 판정·사유를 쓴다. 수치는 동결 스냅샷 위의 결정적 도구만 만들고, 사유 속 숫자는 도구 출력과 대조한다.
3. **일관성은 구조로**: 같은 스냅샷·도구·필수 체크리스트 + **Claude 1차 검수 → Gemini 2차 검수**(둘 다 적격일 때만 적격). 2차는 승인하거나 낮출 수만 있고, 어떤 경로로도 판정을 올리거나 종목을 더하지 않는다.
4. **계약 테스트 자동 적용**: 등록된 모든 기법에 붙고, 통과가 곧 합류 조건이다.
5. **설정으로 교체**: 검수 순서(1차·2차 제공자)·예산·표시 문구·데이터 소스는 `config/`. 기록은 코드값(enum), 문구는 화면에서 매핑.
6. **추가만 하는 기록 · 레지스트리 기반 워크플로**: 실행마다 새 파일. 기준 변경 = version 올림 → 통계 분리. 실행 폼의 기법 체크박스는 레지스트리에서 생성기로만 만든다(손 수정 금지, CI가 동기화 검사).

## 2. 디렉터리 구조
```
stock-screening/
├── config/      settings.yaml(검수 순서·예산·소스) · universes.yaml(범위 프리셋) · pricing.yaml · labels.yaml(판정 문구·고지문) · banned_terms.yaml
├── src/screener/
│   ├── api.py(기법용 유일 공개 API) · cli.py(list·validate·new·run·track·site·lock·sync-workflow) · registry.py · manifest.py · pipeline.py · review.py
│   ├── data/      catalog.yaml · snapshot.py · asof.py · adapters/{naver_stock,krx_pykrx,kr_dart,us_yfinance,fake}.py · universes.py
│   ├── features/  technical.py · fundamental.py
│   ├── tools/     common.py(공통 도구) · executor.py(호출·메모이즈·증거 기록)
│   ├── llm/       base.py · loop.py · schema.py · validate.py · budget.py · prompts/common.md · providers/{anthropic,gemini,mock}.py
│   ├── ledger/    writer.py · returns.py · stats.py
│   └── site/      render.py · templates/
├── strategies/  _template/(복제용) · technical/ · buffett_moat/(active) · minervini_sepa/ · soros_reflexivity/(hold) · strategies.lock
│   └── <id>/    strategy.yaml(필수) · tools.py · prompt.md(active 필수) · postprocess.py · tracking.py(선택) · tests/
├── results/     runs/<run_id>/ · picks/ · events/ · derived/(매 실행 재생성)
├── tests/       unit/ · contract/ · scenarios/(mock 대본)
└── .github/workflows/  screen.yml(workflow_dispatch만) · ci.yml
```

## 3. 기법 플러그인 규격
**매니페스트 `strategy.yaml` 예(technical)** — hold 기법은 이 파일만 있으면 된다.
```yaml
id: technical                      # = 폴더명, ^[a-z][a-z0-9_]{1,31}$
name: 기술적 분석
version: 1.0.0                     # 판정 기준 변경 시 올림(CI가 lock으로 강제) → 통계 분리
spec: docs/strategies/technical.md
markets: {KR: active, US: active}  # 시장별 active | hold
data: {required: [ohlcv_daily, traded_value_20d], optional: [sector]}    # 필드 카탈로그 ID만
tools: {common: [get_fields, compute_indicator], own: [tech_candidates, tech_evidence]}
candidates_tool: tech_candidates   # 픽 ⊆ 이 도구가 반환한 종목
params: {min_history: 120, rsi_max: 70, vol_ratio_min: 1.0, candidate_limit: 30}   # 제안값(Q2·Q4)
universe:                          # 기법별 기본 범위(§6.2 프리셋 ID, 여러 개 가능). 실행 폼 범위 체크박스로 덮어쓸 수 있음
  KR: {default: [kr_all], allowed: all}   # 기본 = 국장 전체(사용자 결정). all = §6.2 프리셋 전부 허용, 또는 [kospi200, kosdaq150, …]
  US: {default: [us_all], allowed: all}   # 기본 = 미장 전체(사용자 결정, PRD Q34 해결)
  combine: union                   # union = 합집합에서 시장별 최대 3(제안) | per_universe = 범위마다 최대 3(비용 × 범위 수) — PRD Q37
checklist:                         # 순서대로 저장. by=code는 도구 값이 판정, by=llm은 LLM 판정 + 근거
  - {id: trend,    by: code, from: tech_evidence.aligned}
  - {id: momentum, by: llm,  needs: [tech_evidence]}
output: {llm_fields: {}, computed_fields: []}   # llm_fields 타입: enum|text|bool|level_ref (숫자 금지)
tracking: [prev_close]
limits: {max_turns: 12, max_tool_calls: 30}
```
**기법별 출력 확장 예(SEPA 착수 시 — 지금은 hold)**
```yaml
output:
  llm_fields: {vcp_state: {type: enum, values: [complete, forming, none]},
               pivot: {type: level_ref, from: sepa_levels}, stop: {type: level_ref, from: sepa_levels}, target: {type: level_ref, from: sepa_levels}}
  computed_fields: [entry, extension_pct, risk_pct, rr_current, rr_entry]  # postprocess.py가 계산, R/R<2면 관찰로 강등
tracking: [prev_close, entry]          # entry 기준 수익률 여부 Q22
labels: {eligible: 적격, watch: 관찰}    # 기법별 표시 재정의(금지어 검사, Q24)
```
**Python 인터페이스**
```python
# screener/api.py
class Verdict(StrEnum): ELIGIBLE = "eligible"; WATCH = "watch"; EXCLUDED = "excluded"
@dataclass(frozen=True)
class Num: value: float | None; display: str; field: str   # None=미확인(대체값 금지), display=코드 포맷 — LLM은 이것만 인용
@dataclass(frozen=True)
class ToolContext:                     # 도구의 유일한 입력원(네트워크 없음, 선언 필드만 읽기)
    market: Literal["KR", "US"]; as_of: date; params: Mapping[str, Any]; data: SnapshotReader; features: FeatureLib
@dataclass(frozen=True)
class CandidateList: passed_count: int; items: list[Candidate]; funnel: list[tuple[str, int]]  # 통과 수(F6)·상위 N·조건별 잔여
def tool(*, candidates: bool = False): ...            # 시그니처·docstring → 도구 JSON 스키마
@tool(candidates=True)                                # strategies/<id>/tools.py
def tech_candidates(ctx: ToolContext) -> CandidateList: ...       # 1차 필터: 기준 = params 고정, LLM 인자 없음
@tool()
def tech_evidence(ctx: ToolContext, ticker: str) -> dict[str, Num]: ...
def postprocess(draft: PickDraft, ev: Evidence, ctx: ToolContext) -> PickDraft: ...  # postprocess.py(선택): 수치 계산·강등만
```

## 4. 레지스트리 · 자동 인식
- `strategies/*/strategy.yaml` 탐색(`_`·`.` 시작 폴더 제외) → Pydantic(`extra="forbid"`) 검증 → `tools.py`·`postprocess.py`를 고유 모듈명으로 `importlib` 로드. 등록 코드·목록 파일 없음.

| 검사 | 규칙 |
|---|---|
| 식별·상태 | id = 폴더명·형식·중복 없음, semver. 전 시장 hold면 매니페스트만 검사하고 실행 요청은 거부 |
| 데이터 | 필드 ⊆ 카탈로그(미등록 ID 거부), 피처 ID(`sma:20`)는 피처 레지스트리가 파싱 |
| 도구 | common ⊆ 코어 도구, own ⊆ `@tool`, 인자 스키마는 이식 가능한 부분집합(`$ref`·`oneOf` 금지). 후보 도구는 LLM 인자 없음(기준 완화 불가, AC17) |
| 체크리스트·출력·프롬프트 | 참조 도구 실재, llm_fields 타입 제한, computed_fields면 postprocess.py 필수, prompt.md StrictUndefined 렌더, 라벨 재정의에 금지어 없음 |
| 버전 | criteria_hash(params·checklist·도구/프롬프트/후처리 소스)가 바뀌면 version도 바뀌어야 함(`strategies.lock`) |
| 격리 | 기법 코드는 `screener.api`·`screener.features`·표준 라이브러리·numpy/pandas만 import(네트워크·LLM SDK 금지) |
- 실패 시: CI는 빨간불. 실행 중에는 그 기법만 "실패(검증)"로 기록하고 나머지는 진행.

## 5. 공통 실행 파이프라인
1. 입력 파싱(체크된 기법·시장·범위 덮어쓰기) → 레지스트리 로드 → 실행 단위(체크된 active 기법×시장) 확정. 체크박스와 레지스트리가 어긋나면 즉시 실패(동기화 필요). 제공자 키·단가 확인(없으면 LLM 호출 전 실패).
2. 시장별 as_of 계산 → 단위별 범위 집합 결정(실행 폼에서 체크한 범위 > 기법 기본 범위, 허용 목록 밖 범위는 그 기법에서 제외·기록) → 범위별 구성종목 스냅샷(출처·근사 여부·종목 수·해시) → `combine`에 따라 합집합(중복 제거) 또는 범위별 단위로 분할 → 전체 범위 합집합 × 선언 필드 합집합을 1회 조회 → 동결·해시.
3. 단위별(순차): 코어가 후보 도구를 먼저 실행(캐시). 통과 0이면 "현재 적격 종목 없음" + 통과 수 기록, LLM 미호출(F3·AC16).
4. 예산 승인 → 불가면 이 단위부터 "예산 초과로 미실행".
5. 1차 검수: Claude가 도구 루프로 판정(`submit_verdicts`: 시장별 적격 ≤3 + 관찰 + 근거) → 검증기 → postprocess.
6. 2차 검수: Gemini가 같은 스냅샷·같은 도구로 1차의 적격·관찰 종목만 검수(`submit_review`: 종목별 승인 / 하향 + 근거) → 검증기. 하향이 있으면 재검토(≤R 라운드) → 최종 판정·승인율.
7. 기록: 단위 레코드 + 픽 행(기준가 = 그 시장 as_of 종가). 실패·중단 단위는 픽 행을 쓰지 않음.
8. 추적: 원장 전 종목 최신 종가 → 수익률·통계·2차 승인율·비용 재집계 → 사이트 렌더 → 커밋 → Pages 배포 → 실행 요약.

## 6. 데이터 계층
- **필드 카탈로그**(`data/catalog.yaml`): `id·kind(series/snapshot/annual/quarterly/text)·unit·format·cost·ttl·시장별 어댑터`. cost=cheap은 유니버스 전체 선적재, expensive는 첫 요청 시 적재.
- **어댑터**: `provides`·`universe(as_of)`·`fetch(fields, tickers, as_of) -> FieldFrame`(값 + missing_reason). 시장별 순서는 설정(`KR: [naver_stock, krx_pykrx, kr_dart]`, `US: [naver_stock, us_yfinance]`, §6.1) → 소스 교체 = 어댑터 추가 + 설정 변경. 스로틀·재시도·백오프는 공통 래퍼.
- **스냅샷**: 도구는 스냅샷만 읽는다. 늦게 적재한 값과 **조회 실패도 메모이즈** → 두 모델·모든 라운드가 같은 값을 본다. 해시는 기록, 파일은 Actions artifact(커밋 안 함). 실행 간 캐시(`actions/cache`)는 ttl이 긴 필드(연간 재무)만.
- **기준일**: as_of = "마감시각+버퍼 ≤ 실행시각"인 마지막 거래일(대표 지수 일봉으로 확인). as_of 이후 봉(장중 미완성)은 버린다(AC4).
- **결측**: None + 사유(not_provided·fetch_failed·insufficient_history·not_applicable), 대체값 금지, 표시는 "미확인". required 결측 종목은 후보 도구가 빼고 funnel에 집계. 소스 전체 실패는 그 시장 단위만 "실패(데이터: 사유)"(F11·AC13).

### 6.1 주식킹 방식 — 네이버 증권 API 어댑터 (`naver_stock`, 국장·미장 공통 1순위)
- **출처:** 주식킹(stock-DASHBB) `scripts/collect-market-data.mjs`. 국장 지수 `m.stock.naver.com/api/index/{KOSPI|KOSDAQ}/basic`, 미장 지수 `api.stock.naver.com/index/{.INX|.IXIC}/basic`을 GitHub Actions에서 조회하며 매일 정상 수집 중(자동 커밋 "Update market data for 2026-09-29" 등으로 확인).
- **그대로 가져올 규칙:** 요청 헤더(user-agent·accept-language `ko-KR`·referer `https://m.stock.naver.com/`), 요청당 타임아웃 15초, 3회 재시도(1초·2초 대기), 마감 확인(`marketStatus == "CLOSE"`가 아니면 그 값은 쓰지 않음 → as_of 규칙과 일치), 숫자 파싱 실패는 오류(대체값 금지).
- **종목 단위 확장 — 비공식·미문서화 엔드포인트** (출처: 제3자 정리 [dd3ok/naverstock-api-skill](https://github.com/dd3ok/naverstock-api-skill), 2026-09 관찰 기록. **이 작업 환경은 네이버 접속이 차단돼 직접 호출 검증 못함 → 구현 9단계에서 Actions로 검증**):

| 용도 | 엔드포인트(`stock.naver.com` 기준) |
|---|---|
| 종목 검색(자동완성·전체) | `/api/autocomplete/search/autoComplete?query={q}&target=stock,index,…` · `/api/autocomplete/search?q={q}&target=…&size=30&page=1` |
| 국장 전 종목 목록 | `/api/stockSecurity/individual-stocks/v3/domestic?listingType=…&exchangeType=consolidated&index=0&size=…` |
| 국장 일봉 | `/api/securityService/chart/domestic/item/{code}?periodType=day` · `/api/stockSecurity/items/v2/domestic/{code}/daily-prices` |
| 미장 일봉 | `/api/securityService/stock/{reutersCode}/price?page=1&pageSize=…` (예: `AAPL.O`) |
| 미장 지수 구성종목 | `/api/securityService/index/{reutersCode}/enrollStocks` |
| ETF 구성(범위 근사용) | 국장 `/api/domestic/detail/{etfCode}/ETFComponent` · 미장 `/api/stockSecurity/etfs/v2/foreign/{reutersCode}/composition` |
- **어댑터 순서(설정):** `KR: [naver_stock, krx_pykrx, kr_dart]`, `US: [naver_stock, us_yfinance]`. 네이버 실패 시 다음 소스로 넘어가고, 어느 소스 값인지 기록한다. 비공식 API라 언제든 바뀔 수 있음 → 응답 스키마 검사 실패 시 그 소스를 "실패"로 처리(빈 목록으로 바꾸지 않음).

### 6.2 범위(유니버스) 프리셋 — 기법별로 제한, 여러 범위 동시 선택
- `config/universes.yaml`에 프리셋을 정의하고, 기법 매니페스트 `universe`가 시장별 **기본 범위 목록**·허용 목록을 가진다.
- **여러 범위:** 실행 폼에서 범위 체크박스를 여러 개 고를 수 있다(예: 코스피200 + 코스닥150, S&P 100 + 나스닥100). 시장별로 하나도 고르지 않으면 각 기법의 기본 범위를 쓴다. 고른 범위는 체크된 모든 기법에 적용하되, 기법의 허용 목록 밖 범위는 그 기법에서 빼고 기록한다(남는 범위가 없으면 그 기법×시장은 "실패(범위)").
- **합치는 방식(`combine`, PRD Q37):** `union`(제안) = 고른 범위의 합집합(중복 종목 1번만)에서 시장별 최대 3종목 — LLM 비용은 범위 1개일 때와 비슷. `per_universe` = 범위마다 따로 최대 3종목 — 비용이 범위 수만큼 늘어남.
- **근사(사용자 결정):** 공식 지수 구성종목을 못 받으면 해당 지수 추종 ETF 보유 종목으로 대신한다. ETF 보유 목록에서 현금·선물 등 주식이 아닌 항목은 뺀다. ETF 보유 목록 공시 시차는 미확인.

| ID | 범위 | 1순위 소스 | 근사 소스(1순위 실패 시) |
|---|---|---|---|
| `kr_all` · `kospi` · `kosdaq` | 국장 전체 / 코스피 전체 / 코스닥 전체 | 네이버 국장 종목 목록 | pykrx 시장별 티커 |
| `kospi200` | 코스피200 | pykrx 지수 구성 `1028` | 코스피200 ETF 보유 종목 |
| `kospi100` · `kospi50` | 코스피100 / 코스피50 | pykrx 지수 구성 `1034` / `1035` | 해당 지수 ETF 보유 종목(ETF 미확인) |
| `kosdaq150` | 코스닥150 | pykrx 지수 구성 `2203`(2차 출처) | 코스닥150 ETF 보유 종목 |
| `krx300` | KRX300 | pykrx 지수 구성(코드 미확인) | KRX300 ETF 보유 종목 |
| `us_all` | 미장 전체(NYSE·나스닥·NYSE American 등 상장 보통주) | 나스닥 공식 심볼 목록 `nasdaqlisted.txt` + `otherlisted.txt`(매일 갱신) | 네이버 미국 종목 목록 |
| `nasdaq` · `nyse` | 나스닥 상장 전체 / NYSE 상장 전체 | 같은 심볼 목록(거래소 구분) | 네이버 미국 종목 목록 |
| `sp500` | S&P 500 | 네이버 지수 구성(`.INX` enrollStocks, 응답 미검증) | SPY 등 ETF 보유 종목 |
| `sp100` | S&P 100 | 네이버 지수 구성(지수 코드 미확인) | OEF ETF 보유 종목 |
| `nasdaq100` · `dow30` | 나스닥100 / 다우30 | 네이버 지수 구성(코드 미확인) | QQQ / DIA ETF 보유 종목 |
| `sox` | 필라델피아 반도체 | 네이버 지수 구성(`.SOX`, 주식킹이 지수 시세 조회에 사용 중, 구성 응답 미검증) | SOXX ETF 보유 종목 |
| `russell2000` | 러셀2000 | 무료 공식 소스 미확인 | IWM ETF 보유 종목 |
- **기본 범위가 전체라서(사용자 결정)** 아무 범위도 안 고른 실행은 국장 전체·미장 전체를 쓴다 → 아래 "가벼운 값으로 먼저 줄이기"가 매 실행 적용되고, 데이터 수집 시간은 시험 실행에서 실측한다.
- **거래소 전체 범위(`kr_all`·`kospi`·`kosdaq`·`us_all`·`nasdaq`·`nyse`):** 보통주만 쓴다(ETF·테스트 종목·워런트·우선주 등은 심볼 목록의 구분값과 이름으로 제외 — 구분 규칙은 구현 때 실제 파일로 확인). 종목 수가 수천 개라(정확한 수 미확인) 일봉 같은 무거운 데이터는 가벼운 값(시가총액·거래대금)으로 먼저 줄인 뒤에만 조회한다 — 기법 1차 필터의 유동성 하한을 먼저 적용. LLM 비용은 후보 상한 N이 있어 범위 크기와 무관하지만, 데이터 수집 시간·요청 수는 늘어난다.
- **소스 출처:** pykrx 지수 코드 `1028`·`1034`·`1035`는 [pykrx README](https://github.com/sharebook-kr/pykrx), `2203`은 [WikiDocs](https://wikidocs.net/226894)(2차 출처). 나스닥 심볼 목록은 [Nasdaq Trader](https://nasdaqtrader.com/) 공개 파일.
- **기록:** 실행마다 범위별 스냅샷(`universe_id`·출처·근사 여부·기준일·종목 수·해시)을 단위 레코드에 저장한다. 픽 행에는 `universe_set`(그 단위에 쓴 범위 집합, 예: `kospi200+kosdaq150`)과 `in_universes`(그 종목이 속한 범위들)를 넣는다 → 통계를 범위 집합별·범위별로 나눠 볼 수 있다. 근사 소스를 쓴 범위는 결과 화면에 "근사"로 표시한다.
- **새 범위 추가:** `config/universes.yaml`에 항목 추가 + 소스 함수 등록. 실행 폼 선택지는 동기화 스크립트가 갱신(§10).

## 7. 공통 피처 라이브러리 · 공통 도구
- `features/technical.py`: sma·ema·rsi(Wilder)·볼린저 %b·거래량 비율·평균 거래대금·n일 수익률·52주 고저·drawdown·MA 기울기·지수 대비 RS·스윙 고저점(규칙은 SEPA 착수 시 사용자 확인). `features/fundamental.py`: ROE 시계열·이익률·YoY/CAGR·연속 흑자 수·FCF(=OCF−capex)·D/E·업종 중앙값·1달러 테스트.
- 파라미터형 피처 ID(`sma:20`, `rsi:14`, `ret:126d`)는 실행 내 메모이즈되어 기법 간 공유. 공통 도구(`get_fields`·`compute_indicator`·`get_price_summary`·`get_financials`)는 모두 `Num` 반환·출력 크기 상한. 두 기법 이상이 쓰는 계산은 라이브러리로 올리고, 기법 도구는 조합만 한다.

## 8. LLM 계층
### 8.1 제공자
```python
class LLMProvider(Protocol):
    id: str                                          # "anthropic" | "gemini" | "mock"
    def turn(self, msgs: list[Message], tools: list[ToolSpec], *, max_output_tokens: int, timeout_s: float) -> Turn: ...
# Turn = text · tool_calls[(id, name, args)] · usage(입·출력 토큰) · model(응답 보고값) · stop_reason
```
- `anthropic.py`(Anthropic SDK 도구 호출) · `gemini.py`(함수 호출) · `mock.py`(대본 + 가짜 usage). `llm.review: {first: anthropic, second: gemini}`로 검수 순서 구성(모델명 Q32). 키는 `ANTHROPIC_API_KEY`·`GEMINI_API_KEY`. 실제 제공자는 `SCREENER_ALLOW_PAID_LLM=1`일 때만 생성(screen.yml의 비-dry_run 스텝에서만 설정).

### 8.2 에이전트 루프 · 출력
- 시스템 프롬프트 = 코어 공통 규칙(`prompts/common.md`: 도구 수치만·`display` 그대로 인용·권유 표현 금지·판정 정의·적격 ≤3·승격 금지·체크리스트 준수) + 기법 `prompt.md` + 체크리스트 + params. 공통 규칙은 기법이 빠뜨릴 수 없다.
- 도구 = 공통 + 기법 + `submit_verdicts`. submit 또는 한도(max_turns·max_tool_calls) 도달 시 종료(한도 도달 = 무효).
- `submit_verdicts` 스키마(공통 + 기법 확장 자동 병합): `{market, evaluations: [{ticker, verdict, reasons[1..3], checklist: [{id, status: met|unmet|unknown, evidence: [tool_call_id]}], missing[], ext{}}], summary}`. 목록에 없는 후보 = 제외.

### 8.3 검증기(매 라운드·매 제출)
| # | 검사 | 근거 |
|---|---|---|
| V1 | 스키마·verdict enum·중복 없음 | F5 |
| V2 | 종목 ⊆ 후보 도구 반환 종목(코어 선실행 결과와 동일) | F5 |
| V3 | 적격 ≤ 3 — 초과분을 코드가 자르지 않고 재제출 요구 | F4 |
| V4 | 적격 종목마다 체크리스트 `needs` 도구 호출 실재, evidence = 실제 tool_call_id. by=code 항목은 도구 값으로 채움 | 명세 |
| V5 | 자유 텍스트의 모든 숫자 = 그 종목 도구 출력의 display/value(표시 자릿수 반올림 허용) 또는 params | F4·AC20 |
| V6 | 금지어(`banned_terms.yaml`), 정책 설정(resubmit 기본 / fail / mask, Q9). 출력물만 검사(프롬프트 제외) | AC9 |
| V7 | level_ref ∈ 해당 도구가 낸 레벨 ID. postprocess 후 판정 ≤ 이전 판정 | F12 |
| V8 | 2차 검수 제출: 종목 ⊆ 1차의 적격·관찰 종목, 행동은 approve·downgrade만(상향·추가 금지) | F13 |
- 위반 → 오류 목록을 도구 오류로 돌려 같은 대화에서 재제출(≤ `submit_attempts`, 제안 2). 소진 시: 라운드 0이면 그 모델 실패 → 단위 "실패"(F13), 재검토 라운드면 직전 판정 유지.

### 8.4 순차 검수 — Claude 1차 → Gemini 2차 (사용자 결정, 설계도 코멘트 2026-10-04)
- 판정 순서 적격 > 관찰 > 제외. **1차(Claude)** 는 후보 도구 결과에서 판정하고, **2차(Gemini)** 는 1차가 적격·관찰로 낸 종목을 같은 스냅샷·도구로 다시 확인해 종목마다 `approve`(그대로) 또는 `downgrade`(관찰·제외로 낮춤)만 낸다. 2차가 새 종목을 내거나 판정을 올리면 검증기가 거부(V8).
- 재검토: 하향된 종목만 2차의 **V5 통과 근거**와 tool_call_id를 1차에 전달 → 1차는 수용(낮춘 판정 따름) 또는 데이터 근거로 반론 → 반론이 있으면 2차가 다시 검수. 라운드 ≤ R(기본 2, Q33). 승인 종목은 동결, 하향 0이면 조기 종료.
- 최종: 끝까지 이견인 종목은 낮은 쪽 규칙(적격+관찰 → 관찰, 적격+제외 → 제외). 2차 실패(오류·한도)면 그 단위는 "실패(2차 검수)"로 기록하고 최종 적격을 내지 않는다(1차 결과는 기록). 어떤 경로로도 승격 없음(AC18).
- 지표: 2차 승인율 = 2차 승인 수 ÷ 1차 적격 수, 하향 후 1차 수용 수·유지 수. 1차 적격·최종 적격·2차에서 걸러진 종목을 모두 기록해 **2차 검수가 수익률을 실제로 개선하는지** 통계로 비교한다.

### 8.5 비용 가드 · 장애 격리 · 기록
- 설정: `budget.max_usd`(첫 시험 실행 임시 **2.00**, 최종 Q31) 및/또는 `max_tokens`·`max_llm_calls` — 실행 전체(모든 제공자·기법·시장·라운드) 누적. 단가는 `pricing.yaml`(모델별 입·출력 USD/1M 토큰 — 공식 가격표 출처·날짜 기입, 현재 미확인).
- 호출 전 승인: `누적 실비 + 입력 추정×입력 단가 + max_output_tokens×출력 단가 > 상한`이면 거부. 실비는 응답 usage로 누적. 입력 추정은 보수적 근사(정확도 미확인 → 시험 실행에서 실측과 비교해 보정).
- 거부 시: 새 호출 중단, 진행 중 호출은 마치고 기록. 진행 중 단위 = "예산 초과로 중단"(픽 저장 안 함, 대화·비용은 실행 레코드), 남은 단위 = "예산 초과로 미실행"(F14·AC19). `unit_reserve_usd`(선택, 실측 후 설정)보다 잔액이 적으면 새 단위를 시작하지 않는다.
- 제공자별 `timeout_s`·`max_retries`(429·5xx·타임아웃 지수 백오프). 인증·한도 오류 또는 연속 실패 N회 → 그 제공자 차단 → 남은 단위는 상대 모델도 부르지 않고 "실패(<제공자> 불가)"(최종 판정을 낼 수 없는 호출에 예산 낭비 방지).
- **비용 리포트**: 제공자 × 기법 × 시장 × 모델 × 라운드별 호출 수·입출력 토큰·추정 USD·도구 호출 수·소요 시간 → `results/runs/<run_id>/cost.json` + 실행 요약 표 + 누적 `derived/costs.csv`.
- **기록**: 제공자·모델(응답 보고값)·`prompt_sha256`(시스템+기법 프롬프트+도구 스키마+params)·version/criteria_hash·snapshot_sha256·시도 수·검증 오류·usage·비용 → 단위 레코드. 전체 대화는 Actions artifact, 레코드엔 도구 호출 요약(이름·인자·결과 해시).

## 9. 기록(원장) · 수익률 · 통계
- 실행마다 새 파일만 추가 → 덮어쓰기·병합 충돌 없음(AC6). 원장 쓰기는 파이프라인만(수동·과거 기록 — SEPA 부록 등 — 미포함). 단위 상태: `ok` · `no_eligible`(현재 적격 종목 없음) · `failed`(사유) · `budget_stopped`(예산 초과로 중단) · `budget_skipped`(예산 초과로 미실행).
  - `results/runs/<run_id>/`: `run.json`(입력·git SHA·설정 해시·검수 순서·as_of·단위 상태) · `units/<기법>__<시장>.json`(통과 수·funnel·1차·2차 라운드 출력·검증 오류·최종 판정·승인율·비용) · `cost.json`
  - `results/picks/<run_id>.jsonl`(픽 행) · `events/<run_id>.jsonl`(entry 확정·상장폐지 등) · `derived/`(returns·stats·agreement·costs, 매번 재생성)

| 픽 행 필드 | 내용 |
|---|---|
| pick_id · run_id · picked_at | `run:기법:시장:stage:종목`, 실행 시각(UTC·KST) |
| strategy_id · strategy_version · criteria_hash | 통계 분리 키 |
| market · exchange · ticker · name · passed_count | KR(KOSPI/KOSDAQ)/US, 1차 필터 통과 수 |
| universe_set · in_universes · universe_approx | 단위에 쓴 범위 집합(예: `kospi200+kosdaq150`), 이 종목이 속한 범위들, 근사 소스 사용 여부 |
| stage · verdict · review_action · rounds_used | `first`(Claude 1차) / `second`(Gemini 2차) / `final`, 판정은 코드값, 2차의 `approve`·`downgrade` |
| reasons · checklist · missing · ext | 사유(도구 수치, 최종 행은 1차·2차 근거), 단계별 결과+근거, 미확인 목록, 기법 확장(예: SEPA pivot·stop·R/R) |
| ref_prices[] | `{kind: prev_close/entry…, date, price, currency, source, status: resolved/pending}` |
| llm · snapshot_sha256 · prompt_sha256 | 재현·감사 |
- 적격·관찰 모두 행으로 남기고 통계 기본은 최종 적격(관찰 추적 Q23). PRD의 "결과 레코드"(AC2·AC3) = `stage=final`·적격 행(0~3건). 수익률 = 최신 종가 ÷ 기준가 − 1(기준가 종류별, 같은 소스·같은 조정 기준 — Q14), 최신 종가 날짜 함께 표시. pending은 계산 안 함. 상장폐지·조회 실패는 빼지 않고 상태 표시(생존편향 방지).
- 통계 키: 기법 × version × 시장 × 범위 집합 × 단계(1차·최종·2차 탈락) × 기준가 종류 → 건수·평균·중앙값·승률(>0)·평균 보유일. 추이: 2차 승인율·재검토 비율·실행당 비용.

## 10. GitHub Actions
```yaml
on:
  workflow_dispatch:            # 유일한 트리거(AC1)
    inputs:
      # ↓ 기법 체크박스: active 기법마다 1개, `screener sync-workflow`가 레지스트리로 생성(손으로 고치지 않음)
      technical:    {type: boolean, default: true, description: "기술적 분석"}
      buffett_moat: {type: boolean, default: true, description: "워렌 버핏(해자)"}
      # ↑ 생성 구간 끝
      # ↓ 범위 체크박스: universes.yaml에서 `checkbox: true`인 자주 쓰는 범위만(생성기가 생성). 시장별로 하나도 안 고르면 기법 기본 범위
      u_kr_all:     {type: boolean, default: false, description: "국장 범위: 전체"}
      u_kospi:      {type: boolean, default: false, description: "국장 범위: 코스피 전체"}
      u_kosdaq:     {type: boolean, default: false, description: "국장 범위: 코스닥 전체"}
      u_kospi200:   {type: boolean, default: false, description: "국장 범위: 코스피200"}
      u_kosdaq150:  {type: boolean, default: false, description: "국장 범위: 코스닥150"}
      u_us_all:     {type: boolean, default: false, description: "미장 범위: 전체"}
      u_nasdaq:     {type: boolean, default: false, description: "미장 범위: 나스닥 전체"}
      u_sp500:      {type: boolean, default: false, description: "미장 범위: S&P 500"}
      u_sp100:      {type: boolean, default: false, description: "미장 범위: S&P 100"}
      u_nasdaq100:  {type: boolean, default: false, description: "미장 범위: 나스닥100"}
      # ↑ 생성 구간 끝
      extra_universes: {type: string, default: "", description: "추가 범위 ID(쉼표): kospi100, kospi50, krx300, nyse, dow30, sox, russell2000"}
      markets:      {type: choice, options: [all, KR, US], default: all}
      mode:         {type: choice, options: [screen, track-only], default: screen}   # track-only = LLM 없이 수익률·통계만 갱신
      dry_run:      {type: boolean, default: false}   # mock 제공자·커밋/배포 없음·LLM 비용 0
```

| 방식 | 기법 추가 시 워크플로 수정 | 판단 |
|---|---|---|
| A. 문자열 입력 + 레지스트리 검증 | 없음. 오타·hold는 즉시 실패 + 유효 ID 목록 | 기각 — 사용자가 **기법별 선택** 요청 |
| B. 기법별 체크박스 + 생성기 + CI 동기화 검사 | 기법 추가 PR에 생성기가 만든 워크플로 변경이 함께 들어감(손 수정 없음). CI가 레지스트리와 체크박스 불일치를 실패로 처리 | **채택** |
| C. choice 드롭다운(단일 선택) + 생성기 | B와 같지만 한 번에 1개(또는 all)만 선택 | 대안 |
- **제약:** 입력 최대 25개 → 고정 입력 4개(markets·extra_universes·mode·dry_run) + 범위 체크박스 10개를 빼면 **기법 체크박스는 최대 11개**. 범위 프리셋 17개를 전부 체크박스로 만들면 기법이 5개로 줄어서, 자주 쓰는 10개만 체크박스로 두고 나머지는 `extra_universes`에 ID로 입력한다(체크박스 대상은 `universes.yaml`의 `checkbox` 값으로 바꿀 수 있음, PRD Q38). 워크플로 파일 변경 push에는 `workflows` 권한이 필요하다는 보고가 있어([커뮤니티 보고](https://github.community/t/refusing-to-allow-a-github-app-to-create-or-update-workflow-without-workflows-permission/182573), 공식 문구 미확인) 이 세션의 GitHub 앱 권한으로 push가 막히면 사용자가 그 변경만 직접 반영해야 함 → 첫 기법 추가 때 확인. GitHub Mobile에서 boolean 입력이 어떻게 보이는지 **미확인**(dry_run으로 확인).
- 확인한 사실: choice `options`는 YAML 정적 목록, 동적 채우기 미지원([Community #12029](https://github.com/orgs/community/discussions/12029), 2025-12 기준 backlog) · 입력 최대 25개([Changelog 2025-12-04](https://github.blog/changelog/2025-12-04-actions-workflow-dispatch-workflows-now-support-25-inputs/)) · GitHub Mobile에서 workflow_dispatch 실행 가능([Changelog 2024-07-30](https://github.blog/changelog/2024-07-30-run-workflows-set-as-workflow_dispatch-manually), 입력 UI 세부 미확인) · 잡 최대 6시간([Docs](https://docs.github.com/en/actions/reference/actions-limits)).
- 잡: checkout → Python → `screener validate` → `run` → `track` → `site` → `results/` 커밋·push(충돌 시 rebase 재시도) → Pages 배포(upload-pages-artifact + deploy-pages, `site/`만) → 실행 요약(단위 상태·비용 표·유효 기법 ID).
- `permissions: {contents: write, pages: write, id-token: write}` · `concurrency: {group: screening, cancel-in-progress: false}` · `timeout-minutes`(Q10). 입력은 `env`로 넘겨 허용값(체크박스 true/false·선택지 목록, `extra_universes`는 `^[a-z0-9_, ]*$` + 등록된 범위 ID)만 통과시키는 검증(스크립트 인젝션 방지, 모르는 ID는 즉시 실패 + 유효 ID 목록 출력). 비밀값은 실행 스텝 env에만: `ANTHROPIC_API_KEY`·`GEMINI_API_KEY`·`DART_API_KEY`·`KRX_ID`·`KRX_PW`. 저장소가 **공개**(GitHub API로 확인)라 Pages는 Free로 가능([GitHub 요금제](https://help.github.com/articles/github-s-products))하지만 결과 사이트·커밋된 결과·Actions 로그가 모두 공개 → 비밀값·계정 정보 로그 출력 금지.
- `ci.yml`(pull_request): pytest(계약·단위·시나리오), mock 제공자·네트워크 차단·비밀값 없음, lock 검사, 출력물 금지어 스캔, 시크릿 스캔(AC12).

## 11. 테스트
- **계약 테스트**(`tests/contract/`, 레지스트리의 모든 기법에 파라미터화로 자동 적용): ① 모든 기법 — 매니페스트 스키마·카탈로그 ID·라벨 금지어, hold면 실행 거부 ② active 도구 — import 제한·스키마 이식성·결정성(같은 픽스처 2회 → 같은 해시)·NaN 없음(결측 = None + "미확인")·후보 도구 params 고정 ③ active e2e — 매니페스트에서 자동 생성한 "모범 mock 에이전트"(후보 도구 → 체크리스트 도구 → display 인용 제출)로 단위·픽 레코드 생성 ④ active 음성 — 후보 밖·중복·적격 4개·근거 없는 숫자·금지어·체크리스트 누락·level_ref 위조 → 전부 거부.
- **코어 시나리오**(`tests/scenarios/*.yaml` 대본): 2차 전부 승인 · 하향 후 1차 수용 · 끝까지 이견 → 낮은 쪽(AC18) · 2차가 새 종목·상향을 내면 거부 · 1차/2차 제공자 실패 → 단위 실패 · 예산 중단/미실행(AC19) · 0후보 LLM 미호출(AC16) · 2건 정상(AC15) · 시장 데이터 실패 격리(AC13) · as_of(AC4).
- **AC10 자동화**: `_template`를 `zz_dummy`로 복제·active → `screener sync-workflow` → 실행 폼에 `zz_dummy` 체크박스 생성·mock 실행·결과에 등장, 코어 diff 없음. CI는 레지스트리와 체크박스가 어긋나면 실패.
- **범위 테스트**: 픽스처 범위 2개(가짜 kospi200 10종목 + 가짜 kosdaq150 8종목, 겹침 2종목)로 실행하면 후보 ⊆ 합집합(16종목, 중복 1번), 픽 행에 `universe_set`·`in_universes` 기록, 허용 목록 밖 범위는 그 기법에서 빠짐, 1순위 소스 실패 모킹 시 ETF 근사로 대체되고 "근사" 표시.
- **유료 호출 0**: CI에 비밀값 없음 + `SCREENER_ALLOW_PAID_LLM` 미설정 시 실제 제공자 생성 거부 + 소켓 차단. mock은 설정한 가짜 usage를 보고 → 예산 로직도 CI에서 검증.

## 12. 새 기법 추가 절차
1. PM: `docs/strategies/<id>.md`(정의·1차 필터·판단 기준·필요 데이터·확보 여부) → 사용자 승인.
2. `python -m screener new <id>` → `_template` 복제(전 시장 hold).
3. `strategy.yaml` 작성. 카탈로그에 없는 데이터가 필요하면 **데이터 계층 PR 선행**(카탈로그 + 어댑터) — 파이프라인은 수정하지 않는다.
4. `tools.py`: 후보 도구(기준 = params, LLM 인자 없음) + 종목별 근거 도구. 계산은 `screener.features` 조합, 반환은 `Num`. `prompt.md`는 기법 고유 기준·판정 정의만, 필요 시 `postprocess.py`·`tracking.py`.
5. 픽스처 → `pytest -k <id>`(계약 테스트 자동 적용) → `screener run --strategies <id> --dry-run`.
6. 매니페스트에 시장별 기본 범위·허용 범위(`universe`)를 적는다.
7. 시장별 `active` 전환 → `python -m screener sync-workflow`로 실행 폼 체크박스 재생성 → PR → CI 통과(동기화 검사 포함) → 사용자 요청 시 머지 → 실행 폼에서 체크해서 실행. 이후 판정 기준을 바꾸면 version을 올린다(CI가 lock으로 강제).

## 13. 단계별 구현 계획
| # | 단계 | 주요 파일 | 합격 확인 | 의존 |
|---|---|---|---|---|
| 1 | 골격·설정 로더·CLI | `pyproject.toml`, `cli.py`, `config/*.yaml`, `tests/conftest.py` | pytest 통과, 소켓 차단 동작 | — |
| 2 | 매니페스트·레지스트리·`_template`·hold 매니페스트 2종(상태·명세 링크만) | `registry.py`, `manifest.py`, `strategies/` | 잘못된 매니페스트 유형별 거부, `list`에 hold 2종 표시·실행 거부 | 1 |
| 3 | 데이터 계층(카탈로그·어댑터 IF·fake·스냅샷·as_of·결측) + 범위 프리셋(`universes.yaml`·범위 스냅샷) | `data/*`, `config/universes.yaml` | AC4·AC21, 합집합 1회 조회(호출 수), 실패 메모이즈 | 1 |
| 4 | 피처 라이브러리·`Num`·공통 도구 | `features/*`, `tools/*`, `api.py` | 수기 계산 대조, 결측 전파(대체값 없음) | 1 |
| 5 | 에이전트 루프·mock 제공자·스키마 병합·검증기 V1~V7 | `llm/*`, `providers/mock.py` | AC5·AC9·AC15·AC20, 허용 플래그 없으면 실제 제공자 거부 | 2, 4 |
| 6 | 예산 가드·비용 리포트·단가표 | `llm/budget.py`, `pricing.yaml` | AC19, 리포트 합계 = 호출별 합 | 1 |
| 7 | 순차 검수 엔진(1차 → 2차 · 하향 시 재검토 · 낮은 쪽 규칙 · 승인율) | `review.py` | AC18, 2차가 새 종목·상향을 내면 거부, 재검토 실패 시 직전 판정 유지 | 5, 6 |
| 8 | 파이프라인·원장·실패 격리·계약 테스트 하네스 | `pipeline.py`, `ledger/writer.py`, `tests/contract/` | mock e2e, AC2·AC3·AC6·AC10·AC11·AC13·AC16·AC17 | 3, 7 |
| 9 | 실데이터 어댑터: **네이버 증권(주식킹 방식, 1순위)**·pykrx·DART·yfinance, 범위 구성종목 소스, 스로틀·ttl 캐시 | `data/adapters/*`, `data/universes.py` | 녹화 픽스처 테스트(CI 무네트워크) + Actions 스모크로 네이버 엔드포인트·범위 구성(코스피200·S&P 100) 실제 응답 확인 | 3 |
| 10 | 실제 제공자(Anthropic·Gemini) | `providers/{anthropic,gemini}.py` | SDK 모킹 테스트, 수동 스모크(같은 도구 스키마로 양쪽 성공) | 5 |
| 11 | 기법 technical · buffett_moat | `strategies/{technical,buffett_moat}/` | 계약 테스트 자동 통과, 골든 후보 일치 | 4, 8(buffett은 9의 재무 필드) |
| 12 | 추적·통계(1차·최종·2차 탈락 비교·승인율·비용 누적) | `ledger/{returns,stats}.py` | AC7·AC8, 다중 기준가·pending | 8 |
| 13 | 정적 사이트 | `site/*` | AC9·AC14, 단위 상태 문구 표시 | 12 |
| 14 | 워크플로 2종·`sync-workflow` 생성기·동기화 검사·시크릿 스캔 | `.github/workflows/*`, `cli.py` | AC1·AC10·AC12·AC22, 휴대폰에서 체크박스·범위 선택 후 dry_run 성공 | 8, 12, 13 |
| 15 | **시험 실행으로 비용 실측 → 상한 확정** | `config/settings.yaml`(budget) | 임시 $2로 1단위(예: technical×KR)부터 실행 → 비용 리포트 검토 → 사용자 최종 상한 반영(Q31), 입력 추정 보정 | 9, 10, 11, 14 |
- 병렬: {2, 3, 4, 6} → {5, 9} → {7, 10} → 8 → {11, 12} → 13 → 14 → 15 (9는 8까지 병렬 진행 가능).

## 14. 리스크 · 미결 질문
| 리스크 | 대응 |
|---|---|
| 모델이 다른 도구 경로를 타 결과가 흔들림 | 동결 스냅샷·결정적 도구·필수 체크리스트·2차 검수, 대화 보관 |
| V5 숫자 대조 오탐(예: "2분기 연속") → 재제출 비용 | 개수·기간도 도구가 `Num`으로 제공, 허용 목록(params·지표명) 조정 |
| 루프가 매 턴 대화 전체를 재전송 → 토큰 증가 | 도구 출력 상한·max_turns·비용 가드. $2로 몇 단위가 도는지는 15단계에서 실측 |
| [pykrx README](https://github.com/sharebook-kr/pykrx): KRX 로그인 필요 API는 `KRX_ID`·`KRX_PW` 환경변수 필수(대상 함수 범위 미확인) | Secrets 등록 또는 대체 어댑터(FinanceDataReader 등, 미검증) |
| OpenDART 약 20,000건 이상 요청 시 020(요청 제한) 오류([2차 출처](https://raw.githubusercontent.com/NomaDamas/k-skill/main/docs/features/k-dart.md), 공식 수치 미확인) · Gemini 함수 스키마는 OpenAPI 스키마 부분집합([Vertex AI 문서](https://cloud.google.com/vertex-ai/generative-ai/docs/model-reference/function-calling)) | ttl 캐시·조회 수 최소화 · 이식 가능한 스키마만 허용 |
- ~~Q-A1~~: 해결 — 사용자 요청으로 기법별 체크박스(생성기 + CI 동기화 검사) 채택(§10).
- Q-A2: AC1 범위 — 테스트용 `ci.yml`(pull_request 트리거)을 허용하는가?
- Q-A3: 미해소 불일치 — 낮은 쪽 규칙(제안) vs 전부 관찰(Q33 구체화). 재검토 대상은 적격 불일치만(제안)인가?
- Q-A4: 사유 숫자 규칙 — `display` 문자열 그대로 인용 + 대조 검사(제안)를 받아들이는가?
- Q-A5: 결과 저장·공개 — main 직접 push vs 별도 `data` 브랜치(Q8, 브랜치 보호 여부). 저장소가 공개라 결과 페이지·데이터·로그도 공개되는데 허용하는가?(Q7)
- Q-A6: pykrx용 KRX 계정을 Secrets로 등록할지, KR 가격 소스를 바꿀지(Q5·Q6 연계).
- Q-A7: 비용 상한 단위 — USD(단가표 유지 필요) / 토큰 / 둘 다(Q31).
