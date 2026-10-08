"""実際の足からのシナリオ自動判定（日足の近似）。"""
from . import config as c


def classify(o: float, h: float, l: float, cl: float, pc: float, atr: float) -> str:
    rng = h - l
    gap = o - pc
    chg = cl - pc
    if rng >= c.ROUND_TRIP_RANGE_ATR * atr and abs(cl - o) <= c.ROUND_TRIP_BODY_RATIO * rng:
        return "round_trip"
    if gap >= c.GAP_ATR * atr:
        return "gap_up_trend" if cl >= o else "gap_up_fade"
    if gap <= -c.GAP_ATR * atr:
        return "gap_down_rebound" if cl > o else "gap_down_trend"
    if rng < c.RANGE_RANGE_ATR * atr and abs(chg) < c.RANGE_CHANGE_ATR * atr:
        return "range"
    if chg >= c.TREND_ATR * atr:
        return "up_trend"
    if chg <= -c.TREND_ATR * atr:
        return "down_trend"
    return "other"
