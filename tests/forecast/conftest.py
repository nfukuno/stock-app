import pytest


def make_pred(target="2026-10-08", symbol="7203.T", status="pending", **kw):
    p = {
        "id": f"{target}_{symbol}", "schema_version": 1, "symbol": symbol, "name": "トヨタ自動車",
        "target_date": target, "created_at": "2026-10-08T08:00:00+09:00",
        "updated_at": "2026-10-08T08:00:00+09:00", "late": False,
        "snapshot": {"prev_date": "2026-10-07", "prev_close": 100.0, "atr14": 10.0},
        "pred": {"open": 101.0, "high": 108.0, "low": 99.0, "close": 106.0},
        "scenario": "up_trend", "confidence": 3, "memo": "メモ\nテスト",
        "status": status, "actual": None, "actual_scenario": None, "score": None,
        "baselines": None, "scored_at": None, "scoring_version": None,
    }
    p.update(kw)
    return p


@pytest.fixture
def pred_factory():
    return make_pred
