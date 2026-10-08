"""全予想 JSON から results.csv を再生成する（冪等）。"""
from __future__ import annotations

import csv
import io
from datetime import date

from . import config as c


def _div(a, b):
    return round(a / b, 3) if a is not None and b else None


def to_row(p: dict) -> dict:
    pred, act, sc = p["pred"], p.get("actual") or {}, p.get("score") or {}
    bl = p.get("baselines") or {}
    atr = act.get("atr14") or (p.get("snapshot") or {}).get("atr14")
    pc = act.get("prev_close") or (p.get("snapshot") or {}).get("prev_close")
    weekday = date.fromisoformat(p["target_date"]).weekday()
    row = {
        "id": p["id"], "symbol": p["symbol"], "name": p.get("name", ""),
        "target_date": p["target_date"], "weekday": weekday, "late": str(bool(p.get("late"))).lower(),
        "status": p["status"], "scenario": p.get("scenario"), "actual_scenario": p.get("actual_scenario"),
        "scenario_hit": "" if sc.get("scenario_hit") is None else str(bool(sc["scenario_hit"])).lower(),
        "confidence": p.get("confidence"),
        "pred_open": pred["open"], "pred_high": pred["high"], "pred_low": pred["low"], "pred_close": pred["close"],
        "act_open": act.get("open"), "act_high": act.get("high"), "act_low": act.get("low"),
        "act_close": act.get("close"), "prev_close": pc, "atr14": atr,
        "total": sc.get("total"), "direction": sc.get("direction"), "close_s": sc.get("close"),
        "open_s": sc.get("open"), "range_iou": sc.get("range_iou"), "body_iou": sc.get("body_iou"),
        "shadow": sc.get("shadow"),
        "flat_total": (bl.get("flat") or {}).get("total"),
        "prev_copy_total": (bl.get("prev_copy") or {}).get("total"),
        "skill": p.get("skill"),
        "pred_change_atr": _div(pred["close"] - pc, atr) if pc and atr else None,
        "act_change_atr": _div(act["close"] - pc, atr) if act and pc and atr else None,
        "pred_range_atr": _div(pred["high"] - pred["low"], atr),
        "act_range_atr": _div(act["high"] - act["low"], atr) if act else None,
        "memo": (p.get("memo") or "").replace("\r", " ").replace("\n", " "),
        "scored_at": p.get("scored_at"), "scoring_version": p.get("scoring_version"),
    }
    return {k: ("" if v is None else v) for k, v in row.items()}


def build_csv(preds: list[dict]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=c.RESULT_COLUMNS, lineterminator="\n")
    w.writeheader()
    scored = [p for p in preds if p.get("status") == "scored"]
    for p in sorted(scored, key=lambda x: (x["target_date"], x["symbol"])):
        w.writerow(to_row(p))
    return buf.getvalue()
