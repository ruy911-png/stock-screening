"""레딧 WSB 글 → 종목 언급·감성 (코드만 계산, LLM 미사용).

- 종목: S&P 500 현재 구성종목. `$NVDA` 같은 캐시태그는 대소문자 무관, 맨 대문자 단어는 3글자 이상이고
  일반 단어 목록(COMMON_WORDS)에 없을 때만 센다. 1~2글자 티커는 캐시태그일 때만 센다. (임시 규칙)
- 감성: VADER(규칙 기반) + WSB 은어 사전(WSB_LEXICON, 임시 값). 제목만 본다.
"""
from __future__ import annotations

import re

from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

# WSB 은어 점수(VADER 척도 −4~+4). 이 시험에서 정한 임시값.
WSB_LEXICON = {
    "moon": 2.5, "mooning": 2.5, "rocket": 2.5, "tendies": 2.0, "calls": 1.5, "call": 1.0,
    "bull": 1.5, "bullish": 2.5, "squeeze": 1.5, "undervalued": 2.0, "breakout": 1.5, "printing": 1.5,
    "puts": -1.5, "put": -1.0, "bear": -1.5, "bearish": -2.5, "drill": -2.0, "drilling": -2.0,
    "crash": -3.0, "crashing": -3.0, "dump": -2.5, "dumping": -2.5, "rug": -2.0, "rugpull": -3.0,
    "bagholder": -2.5, "bagholding": -2.5, "bagholders": -2.5, "overvalued": -2.0, "shorting": -1.5,
    "loss": -2.0, "losses": -2.0, "gain": 2.0, "gains": 2.0,
}
# 대문자로 자주 쓰는 일반 단어와 겹치는 3글자 이상 티커 — 캐시태그일 때만 센다 (임시 목록)
COMMON_WORDS = {
    "ALL", "ARE", "CAT", "DAY", "KEY", "LOW", "NOW", "HAS", "ICE", "MET", "PEG", "POOL", "COST", "FAST",
    "TECH", "WELL", "TAP", "YUM", "WAT", "LUV", "DOC", "DOW", "UPS", "USB", "GEN", "BALL", "TRUE",
    "PLAY", "NEXT", "LIFE", "CASH", "BEST", "GOOD", "HOLD", "MAIN", "SAFE", "REAL", "OPEN", "POST",
    "DTE", "PSA",  # 2026-10-05 결과에서 발견: Days To Expiration(옵션 만기), PSA(공지)로 흔히 씀
}
_CASHTAG = re.compile(r"\$([A-Za-z]{1,5}(?:\.[A-Za-z])?)\b")
_UPPER = re.compile(r"(?<![A-Za-z$])([A-Z]{3,5})(?![A-Za-z])")

_analyzer = SentimentIntensityAnalyzer()
_analyzer.lexicon.update(WSB_LEXICON)


def extract_tickers(title: str, universe: set[str]) -> set[str]:
    found = {m.upper().replace(".", "-") for m in _CASHTAG.findall(title or "")}
    found = {t for t in found if t in universe}
    for word in _UPPER.findall(title or ""):
        if word in universe and word not in COMMON_WORDS:
            found.add(word)
    return found


def sentiment(title: str) -> float:
    """VADER compound(−1~+1)."""
    return float(_analyzer.polarity_scores(title or "")["compound"])
