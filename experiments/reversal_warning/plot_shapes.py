"""Draw real archived OHLCV, marking shape labels only after bar completion."""
from pathlib import Path
import json
import os
os.environ.setdefault('MPLCONFIGDIR', '/tmp/reversal-matplotlib')
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
from matplotlib.font_manager import FontProperties
from daily import parse, label

BASE = Path(__file__).parent


def main():
    font = Path('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc')
    prop = FontProperties(fname=str(font)) if font.exists() else FontProperties()
    rows = parse((BASE / 'results/298040.xml').read_bytes())
    dates = ['2026-07-16', '2026-09-02', '2026-09-30']
    fig, axes = plt.subplots(1, 3, figsize=(15, 5.8))
    for ax, date in zip(axes, dates):
        index = next(i for i, r in enumerate(rows) if r['date'] == date)
        start = max(0, index - 9)
        frame = rows[start:index + 4]
        event_x = index - start
        for i, row in enumerate(frame):
            o, h, l, c = [row[k] / 10000 for k in ['open', 'high', 'low', 'close']]
            color = '#e34b59' if c >= o else '#2877d4'
            ax.vlines(i, l, h, color=color, linewidth=1.5)
            ax.add_patch(Rectangle((i-.28, min(o, c)), .56, max(abs(c-o), .12), facecolor=color, edgecolor=color))
        event = rows[index]
        result = label(event, rows[index-1]['close'])
        ax.axvspan(event_x-.5, event_x+.5, color='#f0b629', alpha=.18)
        ax.annotate('윗꼬리 확인', (event_x, event['high']/10000), xytext=(0, 18),
                    textcoords='offset points', ha='center', fontproperties=prop, fontsize=10,
                    arrowprops=dict(arrowstyle='->', color='#594520'))
        ax.set_title(f"효성중공업 · {date}", fontproperties=prop, fontsize=13, pad=25)
        ax.set_xticks(range(0, len(frame), 3), [r['date'][5:] for r in frame[::3]], rotation=30)
        ax.set_ylabel('주가 (만원)', fontproperties=prop)
        ax.grid(axis='y', alpha=.18)
        ax.set_xlim(-1, len(frame))
        ax.margins(y=.2)
        ax.text(.03, .02, f"윗꼬리/전체 길이 {result['upper_wick_fraction']:.0%}\n고점→종가 {result['high_to_close']:.1%}",
                transform=ax.transAxes, fontproperties=prop, fontsize=10,
                bbox=dict(facecolor='white', alpha=.9, edgecolor='none'))
    fig.suptitle('실제 일봉에서 찾은 긴 윗꼬리 — 노란 표시일은 사후 확인한 모양', fontproperties=prop, fontsize=17, y=.98)
    fig.text(.5, .01, '출처: NAVER 일봉 OHLCV · 2026-10-07 수집 | 첨부 사진의 거래일로 확인된 사례는 아님 | 이 표시는 사전 경고가 아님',
             ha='center', fontproperties=prop, fontsize=10, color='#555555')
    fig.tight_layout(rect=[0,.06,1,.91])
    fig.savefig(BASE / 'results/hyosung_upper_wicks.png', dpi=150)


if __name__ == '__main__':
    main()
