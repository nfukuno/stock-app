import pytest

from app.forecast import scoring as s
from app.forecast.config import WEIGHTS


def bar(o, h, l, c):
    return {"open": o, "high": h, "low": l, "close": c}


PC, A = 100.0, 10.0


def test_identical_is_100():
    b = bar(101, 108, 99, 106)
    r = s.score_bars(b, b, PC, A)
    assert r["total"] == 100.0
    assert all(r[k] == 100.0 for k in WEIGHTS)


def test_opposite_direction_is_low():
    pred = bar(100, 110, 99, 108)
    act = bar(100, 101, 88, 90)
    assert s.score_bars(pred, act, PC, A)["total"] < 30


def test_weights_sum_to_one():
    assert sum(WEIGHTS.values()) == pytest.approx(1.0)


def test_doji_no_zero_division():
    b = bar(100, 105, 95, 100)
    assert s.score_bars(b, b, PC, A)["total"] == 100.0
    assert 0 <= s.score_bars(b, bar(100, 104, 96, 101), PC, A)["body_iou"] <= 100


def test_high_equals_low_bar():
    flat = bar(100, 100, 100, 100)
    r = s.score_bars(flat, flat, PC, A)
    assert r["total"] == 100.0
    s.score_bars(flat, bar(100, 105, 95, 102), PC, A)


def test_direction_levels():
    assert s.direction_score(105, 106, PC, A) == 100
    assert s.direction_score(100.5, 106, PC, A) == 50   # 片方だけ横ばい
    assert s.direction_score(105, 95, PC, A) == 0


def test_close_open_proximity():
    assert s.proximity_score(100, 105, A) == 50
    assert s.proximity_score(100, 130, A) == 0


def test_iou():
    assert s.iou(0, 10, 5, 15) == pytest.approx(100 * 5 / 15)
    assert s.iou(0, 1, 2, 3) == 0
    assert s.iou(5, 5, 5, 5) == 100


def test_shadow_score():
    a = bar(100, 110, 90, 105)  # u=.25 l=.5
    assert s.shadow_score(a, a) == 100
    assert s.shadow_score(bar(90, 110, 90, 110), bar(100, 100, 100, 100)) == 100  # 比率は両方0


def test_flat_baseline_formula():
    f = s.flat_bar(PC, A)
    assert f == {"open": 100, "close": 100, "high": 105, "low": 95}


def test_prev_copy_baseline():
    prev = bar(98, 104, 96, 102)
    f = s.prev_copy_bar(prev, pc1=100, pc=110)
    assert f == {"open": 108, "high": 114, "low": 106, "close": 112}


def test_baselines_and_skill():
    act = bar(100, 105, 95, 100)
    b = s.score_baselines(act, PC, A, bar(98, 104, 96, 102), 100)
    assert b["flat"]["total"] == 100.0
    assert s.skill(80.0, b) == -20.0
    assert s.score_baselines(act, PC, A)["prev_copy"]["total"] is None


def test_atr_fallback():
    assert s.safe_atr(0, 200) == 2
    assert s.safe_atr(None, 200) == 2
