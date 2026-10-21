from datetime import date, datetime

import pytest

from app.forecast import market
from app.trade import engine as e
from app.trade.models import OpenIn


def jst(*a):
    return datetime(*a, tzinfo=market.JST)


def order(**kw):
    b = {"symbol": "7203.T", "margin_type": "system", "side": "long", "qty": 100, "price": 1000, "stop": 990}
    b.update(kw)
    return OpenIn(**b)


NOW = jst(2026, 10, 19, 10, 0)          # 月


def opened(acct, prices=None, at=NOW, **kw):
    o = order(**kw)
    return e.open_position(acct, o, at, at, "トヨタ", prices or {o.symbol: o.price})


def test_carry_cost():
    # 制度・買い 10万円: 当日返済でも受渡日が同じ → 1日分。2.85% → 7.8円 → 7円
    assert e.carry_cost("system", "long", 1000, 100, date(2026, 10, 19), date(2026, 10, 19)) == (7, 1)
    # 月建て→金返済: 受渡 10/21 → 10/27（両端入れ 7日）
    assert e.carry_cost("system", "long", 1000, 100, date(2026, 10, 19), date(2026, 10, 23)) == (54, 7)
    # 売り: 貸株料 1.10%
    assert e.carry_cost("system", "short", 1000, 100, date(2026, 10, 19), date(2026, 10, 19)) == (3, 1)
    assert e.carry_cost("day", "long", 1000, 100, date(2026, 10, 19), date(2026, 10, 19)) == (0, 0)


def test_expiry_and_session():
    assert e.expiry_date(date(2026, 10, 19), 6) == date(2027, 4, 19)
    assert e.expiry_date(date(2026, 8, 31), 6) == date(2027, 2, 26)        # 2/28(日) → 前営業日
    assert e.in_session(jst(2026, 10, 19, 9, 0)) and e.in_session(jst(2026, 10, 19, 11, 30))
    assert e.in_session(jst(2026, 10, 19, 15, 30))
    assert not e.in_session(jst(2026, 10, 19, 11, 31)) and not e.in_session(jst(2026, 10, 19, 12, 0))
    assert not e.in_session(jst(2026, 10, 19, 15, 30, 1)) and not e.in_session(jst(2026, 10, 19, 8, 59))
    assert not e.in_session(jst(2026, 10, 17, 10, 0))                     # 土


def test_open_checks():
    acct = e.new_account(NOW)
    s = e.summary(acct, {}, NOW)
    assert s["effective_margin"] == 5_000_000 and s["buying_power"] == 16_666_667
    with pytest.raises(e.TradeError, match="建余力"):
        opened(acct, qty=10000, price=2000, stop=1990)                   # 2000万 > 余力
    with pytest.raises(e.TradeError, match="立会時間外"):
        opened(acct, at=jst(2026, 10, 19, 12, 0))
    with pytest.raises(e.TradeError, match="未来"):
        e.open_position(acct, order(), jst(2026, 10, 19, 10, 30), NOW, "", {})
    p = opened(acct)
    assert p["id"] == "P00001" and p["expiry_date"] == "2027-04-19"
    d = opened(acct, margin_type="day")
    assert d["expiry_date"] == "2026-10-19"


def test_margin_call():
    acct = e.new_account(NOW)
    opened(acct, qty=8000, price=2000, stop=1900)                         # 建玉 1600万・必要保証金 480万
    s = e.summary(acct, {"7203.T": 2100}, NOW)
    assert s["unrealized"] == 800_000 and s["effective_margin"] == 5_000_000 - s["accrued_cost"]  # 評価益は算入しない
    s = e.summary(acct, {"7203.T": 1700}, NOW)                           # 評価損 240万 → 維持率 16%
    assert s["margin_call"] and s["maintenance_rate"] < 0.2 and s["buying_power"] == 0
    with pytest.raises(e.TradeError, match="追証"):
        opened(acct, prices={"7203.T": 1700})


def test_close_partial_and_r():
    acct = e.new_account(NOW)
    p = opened(acct, qty=200, stop=990, target=1030, margin_type="day")
    t = e.close_position(acct, p["id"], 100, 1020, jst(2026, 10, 19, 10, 30), jst(2026, 10, 19, 10, 31))
    assert t["gross_pnl"] == 2000 and t["net_pnl"] == 2000 and t["r_multiple"] == 2.0 and t["planned_rr"] == 3.0
    assert t["holding_minutes"] == 30 and t["beyond_stop"] is False
    assert acct["positions"][0]["qty"] == 100
    t2 = e.close_position(acct, p["id"], 100, 985, jst(2026, 10, 19, 11, 0), jst(2026, 10, 19, 11, 0))
    assert t2["net_pnl"] == -1500 and t2["beyond_stop"] is True and acct["positions"] == []
    assert e.cash_balance(acct) == 5_000_500
    with pytest.raises(e.TradeError):
        e.close_position(acct, p["id"], 100, 1000, jst(2026, 10, 19, 11, 0), jst(2026, 10, 19, 11, 0))


def test_close_short_swing_with_cost():
    acct = e.new_account(NOW)
    p = opened(acct, side="short", stop=1010, target=950)
    t = e.close_position(acct, p["id"], 100, 950, jst(2026, 10, 23, 14, 0), jst(2026, 10, 23, 14, 0))
    assert t["gross_pnl"] == 5000 and t["carry_cost"] == 21 and t["net_pnl"] == 4979   # 1.10% × 7日
    with pytest.raises(e.TradeError, match="前"):
        q = opened(acct)
        e.close_position(acct, q["id"], 100, 1000, jst(2026, 10, 19, 9, 30), NOW)


def test_apply_forced():
    acct = e.new_account(NOW)
    d = opened(acct, margin_type="day")
    opened(acct)                                                           # 制度は残る
    assert e.apply_forced(acct, jst(2026, 10, 19, 15, 0), lambda s, dd: 1010) == []
    assert e.apply_forced(acct, jst(2026, 10, 19, 16, 0), lambda s, dd: None) == []   # 終値待ち
    s = e.summary(acct, {"7203.T": 1010}, jst(2026, 10, 19, 16, 0))
    assert [p["overdue"] for p in s["positions"]] == [True, False]
    done = e.apply_forced(acct, jst(2026, 10, 20, 9, 0), lambda s, dd: 1010 if dd == date(2026, 10, 19) else None)
    assert len(done) == 1 and done[0]["position_id"] == d["id"] and done[0]["exit_reason"] == "day_close"
    assert done[0]["closed_at"] == "2026-10-19T15:30:00+09:00" and done[0]["net_pnl"] == 1000
    assert len(acct["positions"]) == 1


def test_stats():
    acct = e.new_account(NOW)
    for px, tags in [(1020, ["押し目"]), (980, ["ブレイク"]), (1010, ["押し目"])]:
        p = opened(acct, margin_type="day", tags=tags)
        e.close_position(acct, p["id"], 100, px, jst(2026, 10, 19, 11, 0), jst(2026, 10, 19, 11, 0))
    s = e.stats(acct["trades"])
    assert s["n"] == 3 and s["wins"] == 2 and s["total"] == 1000
    assert s["profit_factor"] == 1.5 and s["max_drawdown"] == 2000 and s["max_loss_streak"] == 1
    assert s["beyond_stop"] == 1 and s["avg_r"] == pytest.approx((2 - 2 + 1) / 3)
    assert {g["key"]: g["n"] for g in s["by_tag"]} == {"ブレイク": 1, "押し目": 2}
    assert [g["key"] for g in s["by_hour"]] == ["10時台"] and s["by_weekday"][0]["key"] == "月"
    assert e.stats([])["n"] == 0


@pytest.mark.parametrize("kw", [
    {"qty": 150}, {"stop": 1010}, {"target": 990}, {"side": "short", "stop": 990},
    {"tags": ["なにか"]}, {"emotion": "ふつう"}, {"margin_type": "general"},
])
def test_order_validation(kw):
    with pytest.raises(ValueError):
        order(**kw)


def test_groups_nanpin_and_close_group():
    acct = e.new_account(NOW)
    a = opened(acct, price=1000, stop=990)
    b = opened(acct, price=980, stop=970, at=jst(2026, 10, 19, 10, 0))          # 平均より安く買い増し → ナンピン
    c = opened(acct, price=1010, stop=1000, at=jst(2026, 10, 19, 10, 0))        # 平均(990)より高い → 増し玉
    opened(acct, side="short", stop=1010)                                       # 売りは別グループ
    assert b["add_type"] == "nanpin" and c["add_type"] == "pyramid" and a.get("add_type") is None
    assert a["nanpin_group"] and b["nanpin_group"] and not c["nanpin_group"]
    s = e.summary(acct, {"7203.T": 1000}, NOW)
    g = next(x for x in s["groups"] if x["side"] == "long")
    assert len(s["groups"]) == 2 and g["qty"] == 300 and g["avg_price"] == pytest.approx(996.67)
    assert g["unrealized"] == 0 + 2000 - 1000 and g["nanpin"]
    at = jst(2026, 10, 19, 11, 0)
    with pytest.raises(e.TradeError, match="合計"):
        e.close_group(acct, g["key"], 400, 1000, at, at)
    ts = e.close_group(acct, g["key"], 200, 1000, at, at)                       # 古い順: a 100 + b 100
    assert [t["position_id"] for t in ts] == [a["id"], b["id"]] and [p["id"] for p in acct["positions"]][0] == c["id"]
    st = e.stats(acct["trades"])
    assert st["nanpin_count"] == 1 and {x["key"]: x["n"] for x in st["by_nanpin_group"]} == {"ナンピンした建玉": 2}


def test_roadmap():
    acct = e.new_account(NOW)
    rm = e.roadmap(e.stats([]), acct["initial_cash"])
    assert rm[0]["done"] and not rm[0]["ready"] and all(not x["ok"] for x in rm[0]["conditions"])
    for i in range(30):                                                          # 10 日 × 3 回、全て損切り設定あり
        d = date(2026, 10, 1)
        for _ in range(i // 3):
            d = market.next_trading_day(d)
        at = jst(d.year, d.month, d.day, 10, 0)
        p = opened(acct, margin_type="day", at=at)
        e.close_position(acct, p["id"], 100, 1005, jst(d.year, d.month, d.day, 10, 30), at.replace(minute=30))
    rm = e.roadmap(e.stats(acct["trades"]), acct["initial_cash"])
    assert rm[0]["ready"] and [x["value"] for x in rm[0]["conditions"]] == [30, 10, 1.0]
    assert rm[-1]["conditions"] == [] and not rm[-1]["ready"]
