import pandas as pd

from app.forecast import results, stats
from tests.forecast.conftest import make_pred


def scored(target, symbol="7203.T", total=80.0, flat=50.0, scenario="up_trend", actual_scn="up_trend",
           conf=3, late=False, close=107.0, pred_close=106.0):
    return make_pred(
        target=target, symbol=symbol, status="scored", scenario=scenario, confidence=conf, late=late,
        pred={"open": 101.0, "high": 108.0, "low": 99.0, "close": pred_close},
        actual={"open": 100.0, "high": 109.0, "low": 98.0, "close": close, "prev_close": 100.0, "atr14": 10.0},
        actual_scenario=actual_scn,
        score={"total": total, "direction": 100, "close": 90, "open": 90, "range_iou": 60, "body_iou": 50,
               "shadow": 80, "scenario_hit": None if scenario == "other" else scenario == actual_scn},
        baselines={"flat": {"total": flat}, "prev_copy": {"total": 40.0}}, skill=round(total - flat, 1),
        scored_at="2026-10-10T16:30:00+09:00", scoring_version=1)


def df_from(preds):
    return stats.load_results(results.build_csv(preds))


def test_empty():
    for text in (None, "", results.build_csv([])):
        d = stats.dashboard(stats.filter_results(stats.load_results(text)))
        assert d["n"] == 0 and d["trend"] == [] and d["confusion"]["matrix"] == []


def test_kpi_and_groups():
    preds = [scored("2026-10-05", total=80, flat=50, conf=4),
             scored("2026-10-06", total=40, flat=60, conf=2, scenario="range", actual_scn="up_trend"),
             scored("2026-10-07", "6758.T", total=60, flat=50, conf=4, scenario="other"),
             scored("2026-10-08", total=70, flat=50, late=True)]
    df = stats.filter_results(df_from(preds))
    assert len(df) == 3                                   # late 除外
    assert len(stats.filter_results(df_from(preds), include_late=True)) == 4
    d = stats.dashboard(df)
    k = d["kpi"]
    assert k["n"] == 3 and k["mean_total"] == 60.0 and k["mean_skill"] == 6.7
    assert k["skill_positive_rate"] == 66.7 and k["direction_rate"] == 100.0
    assert k["scenario_rate"] == 50.0                     # other は対象外 → 1/2
    by_conf = {r["key"]: r for r in d["by_confidence"]}
    assert by_conf[4]["n"] == 2 and by_conf[4]["mean_total"] == 70.0 and by_conf[3]["n"] == 0
    assert d["bias"]["optimism"] == -0.1                  # 予想 +0.6ATR / 実際 +0.7ATR
    keys = d["confusion"]["rows"]
    assert d["confusion"]["matrix"][keys.index("range")][keys.index("up_trend")] == 1
    assert {r["key"] for r in d["by_symbol"]} == {"7203.T", "6758.T"}
    assert len(d["recent"]) == 3 and len(d["scatter"]) == 3


def test_filters():
    preds = [scored(f"2026-10-0{i}", total=50 + i) for i in range(1, 8) if i not in (3, 4)]
    df = df_from(preds)
    assert len(stats.filter_results(df, last_n_days=2)) == 2
    assert len(stats.filter_results(df, date_from="2026-10-06")) == 2
    assert len(stats.filter_results(df, symbol="9999.T")) == 0
