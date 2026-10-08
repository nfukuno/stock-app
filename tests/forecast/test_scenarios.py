import pytest

from app.forecast.scenarios import classify

PC, A = 100.0, 10.0


@pytest.mark.parametrize("bar,expected", [
    ((100, 112, 98, 101), "round_trip"),
    ((104, 110, 103, 109), "gap_up_trend"),
    ((104, 106, 98, 99), "gap_up_fade"),
    ((96, 102, 95, 101), "gap_down_rebound"),
    ((96, 97, 90, 92), "gap_down_trend"),
    ((100, 102, 98, 101), "range"),
    ((101, 106, 100, 105), "up_trend"),
    ((99, 100, 94, 95), "down_trend"),
    ((100, 107, 99, 102), "other"),
])
def test_classify(bar, expected):
    o, h, l, c = bar
    assert classify(o, h, l, c, PC, A) == expected
