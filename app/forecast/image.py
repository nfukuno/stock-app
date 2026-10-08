"""予想 vs 実際 の比較画像（matplotlib のみ）。"""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.patches import Rectangle

from . import config

UP, DOWN = "#d6403a", "#1f7ae0"
_CJK_CANDIDATES = ["Noto Sans CJK JP", "Noto Sans JP", "IPAexGothic", "IPAGothic", "TakaoGothic",
                   "Hiragino Sans", "Yu Gothic", "Meiryo", "VL Gothic"]


def pick_cjk_font() -> str | None:
    names = {f.name for f in font_manager.fontManager.ttflist}
    return next((n for n in _CJK_CANDIDATES if n in names), None)


def _candle(ax, x, o, h, l, c, alpha=1.0, dashed=False, width=0.6):
    col = UP if c >= o else DOWN
    ax.plot([x, x], [l, h], color=col, lw=1.2, alpha=alpha, zorder=2)
    body_lo, body_hi = min(o, c), max(o, c)
    ax.add_patch(Rectangle((x - width / 2, body_lo), width, max(body_hi - body_lo, (h - l) * 0.004 or 0.01),
                           facecolor=col, alpha=alpha, edgecolor=col, lw=1.4,
                           linestyle="--" if dashed else "-", zorder=3))


def render(pred: dict, hist, out_path: Path) -> Path:
    """pred: スコア済み予想 dict / hist: 対象日より前の実際の日足 DataFrame(直近20本を使用)。"""
    font = pick_cjk_font()
    if font:
        plt.rcParams["font.family"] = font
    jp = font is not None
    act, p, sc = pred["actual"], pred["pred"], pred["score"]
    hist = hist.tail(20)
    fig, ax = plt.subplots(figsize=(8, 4.5), dpi=110)
    for i, (_, r) in enumerate(hist.iterrows()):
        _candle(ax, i, r.open, r.high, r.low, r.close, alpha=0.55)
    n = len(hist)
    _candle(ax, n + 0.3, act["open"], act["high"], act["low"], act["close"])
    _candle(ax, n + 1.5, p["open"], p["high"], p["low"], p["close"], alpha=0.35, dashed=True)
    ax.axhline(act["prev_close"], color="#999", lw=0.8, ls=":")
    ax.set_xticks([n + 0.3, n + 1.5])
    ax.set_xticklabels(["実際" if jp else "Actual", "予想" if jp else "Pred"])
    ax.set_xlim(-1, n + 2.5)
    ax.grid(alpha=0.25)
    skill = pred.get("skill")
    skill_s = "" if skill is None else (f"（横ばい比 {skill:+.1f}）" if jp else f" (vs flat {skill:+.1f})")
    name = pred.get("name") if jp else ""
    unit = "点" if jp else " pts"
    ax.set_title(f"{pred['symbol']} {name} {pred['target_date']}  {sc['total']:.1f}{unit}{skill_s}".replace("  ", " "))
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, bbox_inches="tight")
    plt.close(fig)
    return out_path


def image_path(pred_id: str) -> Path:
    return config.IMAGE_DIR / f"{pred_id}.png"


def image_url(pred_id: str) -> str:
    return f"{config.PAGES_BASE_URL}/output/forecast/{pred_id}.png"
