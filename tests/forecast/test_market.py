from datetime import date, datetime

import pandas as pd

from app.forecast import market as m


def jst(*a):
    return datetime(*a, tzinfo=m.JST)


def test_trading_days():
    assert m.is_trading_day(date(2026, 10, 8))          # 木
    assert not m.is_trading_day(date(2026, 10, 10))     # 土
    assert not m.is_trading_day(date(2026, 10, 12))     # スポーツの日
    assert not m.is_trading_day(date(2026, 12, 31))
    assert not m.is_trading_day(date(2027, 1, 2))
    assert m.is_trading_day(date(2027, 1, 4))


def test_next_prev_trading_day():
    assert m.next_trading_day(date(2026, 10, 9)) == date(2026, 10, 13)   # 金 → 火(月曜は祝日)
    assert m.prev_trading_day(date(2026, 10, 13)) == date(2026, 10, 9)


def test_target_date():
    assert m.target_date_for(jst(2026, 10, 8, 8, 0)) == date(2026, 10, 8)
    assert m.target_date_for(jst(2026, 10, 8, 15, 29)) == date(2026, 10, 8)
    assert m.target_date_for(jst(2026, 10, 8, 15, 30)) == date(2026, 10, 9)
    assert m.target_date_for(jst(2026, 10, 10, 10, 0)) == date(2026, 10, 13)  # 土曜


def test_normalize_symbol():
    assert m.normalize_symbol("7203") == "7203.T"
    assert m.normalize_symbol("285a") == "285A.T"
    assert m.normalize_symbol("7203.T") == "7203.T"


def make_df(n=20):
    rows, d, price = [], date(2026, 9, 1), 100.0
    while len(rows) < n:
        if m.is_trading_day(d):
            rows.append((d, price, price + 3, price - 2, price + 1, 1000))
            price += 1
        d = date.fromordinal(d.toordinal() + 1)
    return pd.DataFrame(rows, columns=["d", "open", "high", "low", "close", "volume"]).set_index("d")


def test_atr_and_snapshot():
    df = make_df(20)
    target = date.fromordinal(df.index[-1].toordinal() + 1)
    atr = m.atr_before(df, target)
    assert atr is not None and 4.0 <= atr <= 6.0   # TR = max(5, |103-p|, ...) ≒ 4〜5
    snap = m.snapshot_before(df, target)
    assert snap["prev_date"] == df.index[-1].isoformat()
    # 最後の日を target にすると、その日は ATR に含まれない
    assert m.snapshot_before(df, df.index[-1])["prev_date"] == df.index[-2].isoformat()


def test_atr_insufficient():
    assert m.atr_before(make_df(1), date(2030, 1, 1)) is None
