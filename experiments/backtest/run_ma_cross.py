"""버핏 숫자 필터 × 이동평균선 골든크로스(+ 거래량) 백테스트 — 사용자 요청(2026-10-05):
"버핏과 이평선 골드크로스는? 거래량까지 고려".

결과는 스크리닝 결과(통계용)이며 매수·매도 권유가 아니다. 신호 정의·임시값은 bt/ma_cross.py.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from bt.ma_cross import MA_CROSS, VOL_MULT, VOL_WINDOW, signals  # noqa: E402
from bt.runner import run_signal_set  # noqa: E402

NOTES = [
    "- 골든크로스 = 짧은 이동평균(종가 단순평균)이 긴 이동평균을 아래에서 위로 넘은 날. 조합 5/20(단기) · 20/60(국내에서 흔함) · 50/200(미국식)",
    f"- + 거래량 = 그날 거래량 ≥ 직전 {VOL_WINDOW}거래일 평균 × {VOL_MULT} (임시값)",
]

if __name__ == "__main__":
    sys.exit(run_signal_set(title="# 버핏 × 이동평균선 골든크로스(+ 거래량) 백테스트 — 스크리닝 결과(통계용)",
                            label="골든크로스", notes=NOTES, names=MA_CROSS, signal_fn=signals, out_name="ma_cross"))
