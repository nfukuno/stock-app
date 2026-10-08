"""results.csv の読み込み・フィルタ・ダッシュボード集計（pandas）。"""
from __future__ import annotations

import io

import numpy as np
import pandas as pd

from . import config as c

NUMERIC = [
    "pred_open", "pred_high", "pred_low", "pred_close", "act_open", "act_high", "act_low", "act_close",
    "prev_close", "atr14", "total", "direction", "close_s", "open_s", "range_iou", "body_iou", "shadow",
    "flat_total", "prev_copy_total", "skill", "pred_change_atr", "act_change_atr", "pred_range_atr",
    "act_range_atr", "confidence", "weekday",
]
WEEKDAYS = ["月", "火", "水", "木", "金"]


def load_results(csv_text: str | None) -> pd.DataFrame:
    if not csv_text or not csv_text.strip():
        return pd.DataFrame(columns=c.RESULT_COLUMNS)
    df = pd.read_csv(io.StringIO(csv_text), dtype=str, keep_default_na=False)
    for col in c.RESULT_COLUMNS:
        if col not in df.columns:
            df[col] = ""
    for col in NUMERIC:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["late"] = df["late"].str.lower() == "true"
    df["scenario_hit"] = df["scenario_hit"].map({"true": True, "false": False})   # 空は NaN(=対象外)
    return df.sort_values(["target_date", "symbol"]).reset_index(drop=True)


def filter_results(df: pd.DataFrame, include_late: bool = False, symbol: str | None = None,
                   date_from: str | None = None, date_to: str | None = None,
                   last_n_days: int | None = None) -> pd.DataFrame:
    df = df[df["status"] == "scored"]
    if not include_late:
        df = df[~df["late"]]
    if symbol:
        df = df[df["symbol"] == symbol]
    if date_from:
        df = df[df["target_date"] >= date_from]
    if date_to:
        df = df[df["target_date"] <= date_to]
    if last_n_days:
        dates = sorted(df["target_date"].unique())[-last_n_days:]
        df = df[df["target_date"].isin(dates)]
    return df.reset_index(drop=True)


def _num(x, nd=1):
    if x is None or (isinstance(x, float) and (np.isnan(x) or np.isinf(x))):
        return None
    return round(float(x), nd)


def _rate(series: pd.Series):
    s = series.dropna()
    return _num(s.astype(float).mean() * 100) if len(s) else None


def to_records(df: pd.DataFrame) -> list[dict]:
    out = df.astype(object).where(pd.notna(df), None)
    return out.to_dict(orient="records")


def _group(df: pd.DataFrame, col: str, order: list | None = None) -> list[dict]:
    rows = []
    keys = order if order is not None else sorted(df[col].dropna().unique())
    for k in keys:
        g = df[df[col] == k]
        rows.append({
            "key": k if not isinstance(k, (np.integer, np.floating)) else k.item(),
            "n": int(len(g)),
            "mean_total": _num(g["total"].mean()) if len(g) else None,
            "mean_skill": _num(g["skill"].mean()) if len(g) else None,
            "hit_rate": _rate(g["scenario_hit"]) if len(g) else None,
        })
    return rows


def dashboard(df: pd.DataFrame) -> dict:
    """フィルタ済み(scored)の DataFrame からダッシュボード用の集計を作る。"""
    n = int(len(df))
    if n == 0:
        return {"n": 0, "kpi": {}, "trend": [], "bias": {}, "scatter": [], "by_confidence": [],
                "by_scenario": [], "confusion": {"rows": [], "cols": [], "matrix": []},
                "by_symbol": [], "by_weekday": [], "recent": []}
    skill = df["skill"].dropna()
    dir_ok = df["direction"].dropna()
    kpi = {
        "n": n,
        "mean_total": _num(df["total"].mean()),
        "mean_skill": _num(skill.mean()) if len(skill) else None,
        "skill_positive_rate": _num((skill > 0).mean() * 100) if len(skill) else None,
        "direction_rate": _num((dir_ok == 100).mean() * 100) if len(dir_ok) else None,
        "scenario_rate": _rate(df["scenario_hit"]),
    }

    d = df.sort_values(["target_date", "symbol"]).reset_index(drop=True)
    d["ma_total"] = d["total"].rolling(10, min_periods=1).mean()
    d["ma_flat"] = d["flat_total"].rolling(10, min_periods=1).mean()
    trend = [{"label": f"{r.target_date[5:]} {r.symbol}", "date": r.target_date, "total": _num(r.total),
              "ma": _num(r.ma_total), "flat_ma": _num(r.ma_flat)} for r in d.itertuples()]

    chg = (d["pred_change_atr"] - d["act_change_atr"]).dropna()
    ratio = (d["pred_range_atr"] / d["act_range_atr"]).replace([np.inf, -np.inf], np.nan).dropna()
    bias = {"optimism": _num(chg.mean(), 2) if len(chg) else None,
            "range_ratio": _num(ratio.mean(), 2) if len(ratio) else None}
    sc = d.dropna(subset=["act_change_atr", "pred_change_atr"])
    scatter = [{"x": _num(r.act_change_atr, 2), "y": _num(r.pred_change_atr, 2), "label": f"{r.target_date} {r.symbol}"}
               for r in sc.itertuples()]

    by_conf = _group(d, "confidence", [1, 2, 3, 4, 5])
    by_scn = _group(d, "scenario", c.SCENARIO_KEYS)
    by_scn = [r for r in by_scn if r["n"]]
    keys = c.SCENARIO_KEYS
    mat = [[int(((d["scenario"] == p) & (d["actual_scenario"] == a)).sum()) for a in keys] for p in keys]
    by_symbol = _group(d, "symbol")
    by_wd = [r for r in _group(d, "weekday", [0, 1, 2, 3, 4]) if r["n"]]
    for r in by_wd:
        r["label"] = WEEKDAYS[int(r["key"])]
    recent = to_records(d.sort_values(["target_date", "symbol"], ascending=False).head(10))
    return {"n": n, "kpi": kpi, "trend": trend, "bias": bias, "scatter": scatter, "by_confidence": by_conf,
            "by_scenario": by_scn, "confusion": {"rows": keys, "cols": keys, "matrix": mat},
            "by_symbol": by_symbol, "by_weekday": by_wd, "recent": recent}
