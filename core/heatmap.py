"""C-scan dB 맵 그림 (PNG bytes). 지시 경계 상자와 ID를 겹쳐 그린다."""
import io

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402


def render_png(amp_db, pitch_mm, indications=(), excluded=(), ref_db=0.0, drop_db=6.0, dark=False):
    """dark=True: 화면(어두운 테마)용 색. 보고서(인쇄용 문서)에는 기본(흰 바탕)을 쓴다. 그림 내용은 같다."""
    ny, nx = amp_db.shape
    w, h = nx * pitch_mm, ny * pitch_mm
    fig_w = 9.0
    fig, ax = plt.subplots(figsize=(fig_w, max(2.2, fig_w * h / w + 0.9)), dpi=110)
    if dark:
        ink = "#C9D6E8"
        fig.patch.set_facecolor("#0B1626")
        ax.set_facecolor("#0B1626")
        ax.tick_params(colors=ink)
        for sp in ax.spines.values():
            sp.set_color("#3A4F6E")
        ax.xaxis.label.set_color(ink)
        ax.yaxis.label.set_color(ink)
    im = ax.imshow(amp_db, extent=[0, w, h, 0], cmap="viridis", vmin=ref_db - 30, vmax=ref_db + 3,
                   aspect="equal", interpolation="nearest")
    # 격자 중심 좌표로 그린다. extent+origin으로 그리면 Y가 뒤집힌 축에서 경계선이 위아래로 뒤집혀 그려졌다.
    xs = (np.arange(nx) + 0.5) * pitch_mm
    ys = (np.arange(ny) + 0.5) * pitch_mm
    ax.contour(xs, ys, (amp_db <= ref_db - drop_db).astype(float), levels=[0.5], colors="white", linewidths=0.8)
    for n, i in enumerate(indications):
        x0, y0, x1, y1 = i["bbox_mm"]
        off = i["id"] in excluded
        color = "#9aa0a6" if off else "#ff5252"
        ax.add_patch(Rectangle((x0, y0), x1 - x0, y1 - y0, fill=False, edgecolor=color, linewidth=1.4,
                               linestyle="--" if off else "-"))
        label = i["id"] + (" (excluded)" if off else f"  {i['major_mm']} mm")
        if n == 0:  # 가장 큰 지시는 상자 위, 나머지는 상자 왼쪽에 적어 겹치지 않게 한다
            ax.text(x0, max(y0 - 0.8, 1.2), label, color=color, fontsize=8, fontweight="bold", va="bottom")
        else:
            ax.text(max(x0 - 0.8, 0.5), (y0 + y1) / 2, label, color=color, fontsize=7, fontweight="bold",
                    va="center", ha="right")
    ax.set_xlabel("X (mm)")
    ax.set_ylabel("Y (mm)")
    cb = fig.colorbar(im, ax=ax, fraction=0.025, pad=0.02)
    cb.set_label("dB (rel. to sound area)")
    if dark:
        cb.ax.yaxis.label.set_color("#C9D6E8")
        cb.ax.tick_params(colors="#C9D6E8")
        cb.outline.set_edgecolor("#3A4F6E")
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=fig.get_facecolor())
    plt.close(fig)
    return buf.getvalue()
