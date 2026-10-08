"""採点ロジック（純粋関数）。足は dict(open, high, low, close)。"""
from __future__ import annotations

from . import config as c


def safe_atr(atr: float | None, pc: float) -> float:
    return atr if atr and atr > 0 else pc * c.FALLBACK_ATR_PCT


def _d(x: float, pc: float, atr: float) -> int:
    diff = x - pc
    th = c.DIRECTION_THRESHOLD_ATR * atr
    return 1 if diff > th else (-1 if diff < -th else 0)


def direction_score(cp: float, cr: float, pc: float, atr: float) -> float:
    dp, dr = _d(cp, pc, atr), _d(cr, pc, atr)
    if dp == dr:
        return 100.0
    if dp == 0 or dr == 0:
        return 50.0
    return 0.0


def proximity_score(a: float, b: float, atr: float) -> float:
    return 100.0 * max(0.0, 1.0 - abs(a - b) / atr)


def iou(a_lo: float, a_hi: float, b_lo: float, b_hi: float) -> float:
    inter = max(0.0, min(a_hi, b_hi) - max(a_lo, b_lo))
    union = (a_hi - a_lo) + (b_hi - b_lo) - inter
    if union <= 0:
        return 100.0
    return 100.0 * inter / union


def _body(bar: dict, atr: float) -> tuple[float, float]:
    lo, hi = min(bar["open"], bar["close"]), max(bar["open"], bar["close"])
    min_w = c.MIN_BODY_ATR * atr
    if hi - lo < min_w:
        mid = (lo + hi) / 2
        lo, hi = mid - min_w / 2, mid + min_w / 2
    return lo, hi


def shadow_ratios(bar: dict) -> tuple[float, float]:
    rng = bar["high"] - bar["low"]
    if rng <= 0:
        return 0.0, 0.0
    top = max(bar["open"], bar["close"])
    bot = min(bar["open"], bar["close"])
    return (bar["high"] - top) / rng, (bot - bar["low"]) / rng


def shadow_score(p: dict, r: dict) -> float:
    up, lp = shadow_ratios(p)
    ur, lr = shadow_ratios(r)
    return 100.0 * (1.0 - (abs(up - ur) + abs(lp - lr)) / 2.0)


def score_bars(pred: dict, actual: dict, pc: float, atr: float | None) -> dict:
    """予想足と実際の足を採点。戻り値は各要素と total（小数1桁）。"""
    a = safe_atr(atr, pc)
    pb, rb = _body(pred, a), _body(actual, a)
    parts = {
        "direction": direction_score(pred["close"], actual["close"], pc, a),
        "close": proximity_score(pred["close"], actual["close"], a),
        "open": proximity_score(pred["open"], actual["open"], a),
        "range_iou": iou(pred["low"], pred["high"], actual["low"], actual["high"]),
        "body_iou": iou(pb[0], pb[1], rb[0], rb[1]),
        "shadow": shadow_score(pred, actual),
    }
    total = sum(c.WEIGHTS[k] * v for k, v in parts.items())
    out = {k: round(v, 1) for k, v in parts.items()}
    out["total"] = round(total, 1)
    return out


def flat_bar(pc: float, atr: float | None) -> dict:
    a = safe_atr(atr, pc)
    return {"open": pc, "close": pc,
            "high": pc + a * c.FLAT_HALF_RANGE_ATR, "low": pc - a * c.FLAT_HALF_RANGE_ATR}


def prev_copy_bar(prev_bar: dict, pc1: float, pc: float) -> dict:
    """前日の足の形を pc 基準で平行移動（pc1 = 前々日終値）。"""
    return {k: pc + (prev_bar[k] - pc1) for k in ("open", "high", "low", "close")}


def score_baselines(actual: dict, pc: float, atr: float | None,
                    prev_bar: dict | None = None, pc1: float | None = None) -> dict:
    out = {"flat": {"total": score_bars(flat_bar(pc, atr), actual, pc, atr)["total"]}}
    if prev_bar is not None and pc1 is not None:
        out["prev_copy"] = {"total": score_bars(prev_copy_bar(prev_bar, pc1, pc), actual, pc, atr)["total"]}
    else:
        out["prev_copy"] = {"total": None}
    return out


def skill(total: float, baselines: dict) -> float | None:
    flat = baselines.get("flat", {}).get("total")
    return None if flat is None else round(total - flat, 1)
