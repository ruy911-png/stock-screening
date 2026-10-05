"""버핏 숫자 필터 × 과매수·과매도 지표(RSI·스토캐스틱·윌리엄스 %R) 백테스트 — 사용자 요청(2026-10-05).

결과는 스크리닝 결과(통계용)이며 매수·매도 권유가 아니다. 지표 경계값·한계는 bt/oscillators.py·README.md.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from bt.oscillators import SIGNALS, signals  # noqa: E402
from bt.runner import run_signal_set  # noqa: E402

NOTES = [
    "- 지표(임시 경계값): RSI(14) 30/70 · 스토캐스틱(14,3,3) %K 20/80 · 윌리엄스 %R(14) −80/−20. 조건이 처음 성립한 날이 신호",
    "- 윌리엄스 %R(14) = 빠른 스토캐스틱 %K − 100 이라 스토캐스틱(느린 %K)과 결과가 비슷할 수 있다",
    "- (b)안 = PRD §9.1 제안(종가 > 200일선, 6개월 수익률 > 0, RSI(2) < 10) — 참고",
]

if __name__ == "__main__":
    sys.exit(run_signal_set(title="# 버핏 × 과매수·과매도(RSI·스토캐스틱·윌리엄스 %R) 백테스트 — 스크리닝 결과(통계용)",
                            label="지표", notes=NOTES, names=SIGNALS, signal_fn=signals, out_name="oscillators"))
