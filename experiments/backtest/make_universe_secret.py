"""사용자가 직접 내려받은 iShares IWB 보유종목 파일 → GitHub Secret(R1000X_UNIVERSE)에 넣을 한 줄 문자열.

출력은 저장소에 올리지 않는다(파일의 저작권 고지: 개인·비상업적 용도, 복사·배포·게시 금지).
사용: python make_universe_secret.py <보유종목 .xls 또는 .csv> --out <저장소 밖 경로.txt>
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from bt.universe import ENV_NAME, holdings_to_spec, read_ishares_holdings  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--out", required=True, help="문자열을 저장할 파일(저장소 밖)")
    args = ap.parse_args()
    out = Path(args.out).resolve()
    repo = Path(__file__).resolve().parents[2]
    if repo in out.parents:
        raise SystemExit("저장소 안에는 저장하지 않는다 — 저장소 밖 경로를 주세요")
    spec, counts = holdings_to_spec(read_ishares_holdings(Path(args.path)))
    out.write_text(spec + "\n", encoding="utf-8")
    print(f"{ENV_NAME}: {len(spec):,}자 → {out}")
    for k, v in counts.items():
        print(f"- {k}: {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
