"""Generate Big Dipper banner images for the README."""

import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import numpy as np

FONT_TITLE  = fm.FontProperties(family="Songti SC", size=20)
FONT_LABEL  = fm.FontProperties(family="PingFang SC", size=8)
FONT_ICON   = fm.FontProperties(family="Songti SC", size=24)

STARS = {
    "Tianshu":  (1.00, 5.20),
    "Tianxuan": (1.00, 4.30),
    "Tianji":   (2.00, 4.00),
    "Tianquan": (2.10, 4.90),
    "Yuheng":   (3.20, 5.20),
    "Kaiyang":  (4.30, 5.60),
    "Yaoguang": (5.50, 6.30),
}

BOWL   = ["Tianshu", "Tianxuan", "Tianji", "Tianquan", "Tianshu"]
HANDLE = ["Tianquan", "Yuheng", "Kaiyang", "Yaoguang"]

CHINESE = {
    "Tianshu":  "天枢",
    "Tianxuan": "天璇",
    "Tianji":   "天玑",
    "Tianquan": "天权",
    "Yuheng":   "玉衡",
    "Kaiyang":  "开阳",
    "Yaoguang": "摇光",
}

LINE_STYLE = dict(color="#4a9eff", linewidth=1.2, alpha=0.55,
                  linestyle="--", zorder=2, solid_capstyle="round")


def scatter_bg_stars(ax, n=320, seed=42):
    rng = np.random.default_rng(seed)
    xs = rng.uniform(0, 7, n)
    ys = rng.uniform(2.5, 8, n)
    sizes = rng.exponential(0.8, n) * 4
    alphas = rng.uniform(0.15, 0.55, n)
    colors = rng.choice(["#cce0ff", "#e0eeff", "#fff8f0", "#ffe8cc"], n)
    for x, y, s, a, c in zip(xs, ys, sizes, alphas, colors):
        ax.scatter(x, y, s=s, color=c, alpha=a, zorder=1)


def draw_constellation(ax, **kw):
    style = {**LINE_STYLE, **kw}
    for segment in (BOWL, HANDLE):
        xs = [STARS[s][0] for s in segment]
        ys = [STARS[s][1] for s in segment]
        ax.plot(xs, ys, **style)


def glow(ax, x, y, size, color, n_layers=6):
    for i in range(n_layers, 0, -1):
        ax.scatter(x, y, s=size * (i * 2.5) ** 1.6, color=color, alpha=0.04, zorder=2)
    ax.scatter(x, y, s=size, color=color, zorder=3)


def make_banner():
    fig, ax = plt.subplots(figsize=(12, 4))
    fig.patch.set_facecolor("#050a1a")
    ax.set_facecolor("#050a1a")
    ax.set_xlim(-0.4, 7.4)
    ax.set_ylim(2.5, 8)
    ax.axis("off")

    scatter_bg_stars(ax)
    draw_constellation(ax)

    FONT_LABEL_LG = fm.FontProperties(family="Songti SC", size=16)
    for name, (x, y) in STARS.items():
        is_tianshu = name == "Tianshu"
        color = "#ffe066" if is_tianshu else "#c8e0ff"
        glow(ax, x, y, 260 if is_tianshu else 160, color)
        if is_tianshu:
            ax.text(x, y + 0.52, CHINESE[name],
                    color="#ffe066", ha="center", va="bottom", zorder=4,
                    fontproperties=FONT_LABEL_LG)
        else:
            offset_y = 0.38 if y < 5 else -0.42
            ax.text(x, y + offset_y, CHINESE[name],
                    color="#aaccee", ha="center", va="center", zorder=4,
                    fontproperties=FONT_LABEL)

    ax.text(0.01, 0.96, "天枢｜枢运北斗，御动九天",
            transform=ax.transAxes,
            color="#ffe066", va="top", ha="left", zorder=5,
            fontproperties=FONT_TITLE)

    for v in np.arange(0, 7.5, 1):
        ax.axvline(v, color="#1a2a4a", linewidth=0.4, alpha=0.3, zorder=0)
    for h in np.arange(2.5, 8.5, 0.5):
        ax.axhline(h, color="#1a2a4a", linewidth=0.4, alpha=0.3, zorder=0)

    out = "/Users/I552307/projects/tianshu/resources/banner.png"
    fig.savefig(out, dpi=180, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    print(f"saved {out}")


def make_icon():
    fig, ax = plt.subplots(figsize=(4, 4))
    fig.patch.set_facecolor("#050a1a")
    ax.set_facecolor("#050a1a")
    ax.set_xlim(0.4, 6.1)
    ax.set_ylim(3.5, 7.0)
    ax.axis("off")

    scatter_bg_stars(ax, n=180, seed=7)
    draw_constellation(ax, linewidth=1.6, alpha=0.6)

    for name, (x, y) in STARS.items():
        is_tianshu = name == "Tianshu"
        color = "#ffe066" if is_tianshu else "#c8e0ff"
        glow(ax, x, y, 320 if is_tianshu else 180, color)

    tx, ty = STARS["Tianshu"]
    FONT_ICON_LG = fm.FontProperties(family="Songti SC", size=30)
    ax.text(tx + 0.55, ty + 0.45, "天枢",
            color="#ffe066", ha="center", va="bottom", zorder=5,
            fontproperties=FONT_ICON_LG)

    out = "/Users/I552307/projects/tianshu/resources/icon.png"
    fig.savefig(out, dpi=180, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    print(f"saved {out}")


if __name__ == "__main__":
    make_banner()
    make_icon()
