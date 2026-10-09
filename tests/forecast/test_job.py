import json
from datetime import date, datetime

import pandas as pd
import pytest

from app.forecast import job, market, notify
from app.forecast.store import LocalStore
from tests.forecast.conftest import make_pred


def jst(*a):
    return datetime(*a, tzinfo=market.JST)


def frame(rows):
    return pd.DataFrame([(date.fromisoformat(d), o, h, l, c, 1000) for d, o, h, l, c in rows],
                        columns=["d", "open", "high", "low", "close", "volume"]).set_index("d")


def base_rows():
    d0 = date(2026, 9, 1)
    rows, d, px = [], d0, 100.0
    while len(rows) < 14:
        if market.is_trading_day(d):
            rows.append((d.isoformat(), px, px + 3, px - 3, px + 1)); px += 1
        d = date.fromordinal(d.toordinal() + 1)
    return rows   # 最終日 2026-09-18(金)


class Args:
    def __init__(self, **kw):
        self.date = None; self.dry_run = False; self.rescore = False
        self.__dict__.update(kw)


def setup(tmp_path, target, pred_kw=None):
    st = LocalStore(tmp_path)
    st.put(make_pred(target=target, **(pred_kw or {})))
    return st


def test_score_prediction(tmp_path):
    rows = base_rows() + [("2026-09-24", 115, 120, 114, 119)]
    df = frame(rows)
    p = make_pred(target="2026-09-24")
    p["pred"] = {"open": 115.0, "high": 120.0, "low": 114.0, "close": 119.0}
    out, new = job.score_prediction(p, df, jst(2026, 9, 24, 16, 0))
    assert out == "scored" and new["status"] == "scored"
    assert new["score"]["total"] == 100.0 and new["score"]["scenario_hit"] in (True, False)
    assert new["baselines"]["flat"]["total"] < 100 and new["skill"] > 0
    assert new["actual"]["prev_close"] == 114.0 and new["scoring_version"] == 1


def test_wait_before_final_and_when_missing():
    df = frame(base_rows())
    p = make_pred(target="2026-09-24")
    assert job.score_prediction(p, df, jst(2026, 9, 24, 15, 44))[0] == "wait"
    assert job.score_prediction(p, df, jst(2026, 9, 24, 16, 0))[0] == "wait"       # データ遅延 → 持ち越し


def test_void_cases():
    df = frame(base_rows() + [("2026-09-28", 120, 125, 119, 123)])
    out, new = job.score_prediction(make_pred(target="2026-09-26"), df, jst(2026, 9, 29, 9, 0))   # 土曜
    assert out == "void" and new["void_reason"] == "non_trading_day"
    out, new = job.score_prediction(make_pred(target="2026-09-25"), df, jst(2026, 9, 29, 9, 0))   # 取引日・足なし・以後の足あり
    assert out == "void" and new["void_reason"] == "no_data"


def test_run_end_to_end(tmp_path, monkeypatch):
    target = "2026-09-24"
    st = setup(tmp_path, target)
    st.put(make_pred(target="2026-09-24", symbol="6758.T", late=True))
    df = frame(base_rows() + [(target, 115, 121, 114, 120)])
    monkeypatch.setattr(job, "render", lambda *a, **k: None)
    scored = job.run(Args(), store=st, fetch=lambda s: df, now=jst(2026, 9, 24, 17, 0))
    assert len(scored) == 1                              # late(場中予想) は採点しない
    assert st.get(target, "6758.T")["status"] == "void"
    assert st.get(target, "7203.T")["status"] == "scored"
    csv_lines = st.read_text("results.csv").strip().split("\n")
    assert len(csv_lines) == 2
    assert json.loads(st.read_text(".pending_notify.json")) == ["2026-09-24_7203.T"]
    sent = []
    n = job.notify_pending(st, sender=lambda preds, avg: sent.append((preds, avg)))
    assert n == 1 and st.read_text(".pending_notify.json") == "[]"
    # 2 回目は何もしない
    assert job.run(Args(), store=st, fetch=lambda s: df, now=jst(2026, 9, 24, 17, 0)) == []


def test_dry_run_writes_nothing(tmp_path):
    target = "2026-09-24"
    st = setup(tmp_path, target)
    df = frame(base_rows() + [(target, 115, 121, 114, 120)])
    job.run(Args(dry_run=True), store=st, fetch=lambda s: df, now=jst(2026, 9, 24, 17, 0))
    assert st.get(target, "7203.T")["status"] == "pending"
    assert st.read_text("results.csv") is None


def test_message():
    p = make_pred(status="scored", actual_scenario="gap_down_trend", skill=-9.8, confidence=2, memo="メモ",
                  score={"total": 41.0, "direction": 0, "scenario_hit": False})
    msg = notify.build_message([p], 6.3)
    assert "10/8" in msg and "41.0点（横ばい比 -9.8）" in msg and "方向✕" in msg
    assert "予想:じり上げ / 実際:GD→下落継続" in msg and "メモ: メモ" in msg and "+6.3" in msg


def test_recent_skill_avg():
    ps = [make_pred(target=f"2026-09-{d:02d}", status="scored", skill=float(d)) for d in range(1, 13)]
    assert job.recent_skill_avg(ps) == pytest.approx(sum(range(3, 13)) / 10, abs=0.05)


def test_intraday_prediction_is_not_scored(tmp_path, monkeypatch):
    target = "2026-09-24"
    st = LocalStore(tmp_path)
    st.put(make_pred(target=target, late=True))
    df = frame(base_rows() + [(target, 115, 121, 114, 120)])
    monkeypatch.setattr(job, "render", lambda *a, **k: (_ for _ in ()).throw(AssertionError("画像は作らない")))
    # 引け前は触らない（まだ編集できる）
    assert job.run(Args(), store=st, fetch=lambda s: df, now=jst(2026, 9, 24, 12, 0)) == []
    assert st.get(target, "7203.T")["status"] == "pending"
    # 引け後は採点せず void にする（通知・集計の対象外）
    assert job.run(Args(), store=st, fetch=lambda s: df, now=jst(2026, 9, 24, 17, 0)) == []
    p = st.get(target, "7203.T")
    assert p["status"] == "void" and p["void_reason"] == "intraday_unscored" and p["score"] is None
    assert st.read_text(".pending_notify.json") in (None, "[]")
