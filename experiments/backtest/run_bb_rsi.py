"""버핏 숫자 필터 × 볼린저+RSI 조합 백테스트 — 사용자 요청(2026-10-05): "둘 다 해봐 버핏 붙여서".

조합: 하단 밴드 이탈 + RSI(14)<30, 볼린저 Method I 돌파 + RSI(14)>50. 비교용으로 볼린저 단독 줄도 둔다.
결과는 스크리닝 결과(통계용)이며 매수·매도 권유가 아니다.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from bt.oscillators import BB_RSI, bb_rsi_signals  # noqa: E402
from bt.runner import run_signal_set  # noqa: E402

NOTES = [
    "- 볼린저(20, ±2σ): 하단 이탈 = 종가 < 하단 밴드(%b < 0)가 처음 된 날 · I 돌파 = 직전 20거래일 안 Squeeze(BandWidth 125거래일 최저) 뒤 종가가 처음 상단 밴드 위",
    "- RSI(14) Wilder: 하단 이탈과 함께 < 30(과매도 재확인), I 돌파일에 > 50(상승 힘 확인) — 임시 경계값",
]

if __name__ == "__main__":
    sys.exit(run_signal_set(title="# 버핏 × 볼린저+RSI 조합 백테스트 — 스크리닝 결과(통계용)",
                            label="볼린저+RSI", notes=NOTES, names=BB_RSI, signal_fn=bb_rsi_signals, out_name="bb_rsi"))
