import json
from datetime import date, datetime

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.forecast import market
from app.main import app


def jst(*a):
    return datetime(*a, tzinfo=market.JST)


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("FORECAST_STORAGE", "local")
    monkeypatch.setenv("TRADE_DATA_DIR", str(tmp_path))
    px = {"close": 1000.0}
    days = [date(2026, 10, 16), date(2026, 10, 19), date(2026, 10, 20)]

    def fetch(sym, days_=120, use_cache=True):
        return pd.DataFrame({"open": 1000.0, "high": 1050.0, "low": 950.0, "close": px["close"], "volume": 1},
                            index=days)
    monkeypatch.setattr(market, "fetch_daily", fetch)
    monkeypatch.setattr(market, "lookup_name", lambda s: "Toyota")
    clock = {"now": jst(2026, 10, 19, 10, 0)}
    monkeypatch.setattr(market, "now_jst", lambda: clock["now"])
    c = TestClient(app)
    c.clock, c.px, c.root = clock, px, tmp_path
    return c


def open_body(**kw):
    b = {"symbol": "7203", "margin_type": "day", "side": "long", "qty": 100, "price": 1000, "stop": 990,
         "tags": ["押し目"], "emotion": "冷静", "memo": "テスト"}
    b.update(kw)
    return b


def test_account_created_and_persisted(client):
    a = client.get("/api/trade/account").json()
    assert a["initial_cash"] == 5_000_000 and a["positions"] == []
    cur = json.loads((client.root / "current.json").read_text())
    assert (client.root / "accounts" / f"{cur['account_id']}.json").exists()
    assert client.get("/api/trade/account").json()["account_id"] == a["account_id"]


def test_open_close_flow(client):
    r = client.post("/api/trade/open", json=open_body())
    assert r.status_code == 200, r.text
    p = r.json()["position"]
    assert p["symbol"] == "7203.T" and p["name"] == "トヨタ自動車"   # forecast_symbols.csv の名前
    client.px["close"] = 1015.0
    acc = client.get("/api/trade/account").json()
    assert acc["positions"][0]["unrealized"] == 1500
    client.clock["now"] = jst(2026, 10, 19, 10, 30)
    r = client.post("/api/trade/close", json={"position_id": p["id"], "qty": 100, "price": 1020,
                                               "executed_at": "2026-10-19T10:25", "memo": "目標手前"})
    assert r.status_code == 200, r.text
    t = r.json()["trade"]
    assert t["net_pnl"] == 2000 and t["closed_at"] == "2026-10-19T10:25:00+09:00" and t["r_multiple"] == 2.0
    a = r.json()["account"]
    assert a["today_realized"] == 2000 and a["cash"] == 5_002_000 and a["today_trades"][0]["id"] == t["id"]
    h = client.get("/api/trade/trades").json()
    assert h["stats"]["n"] == 1 and h["trades"][0]["exit_memo"] == "目標手前"
    assert client.get("/trade").status_code == 200 and client.get("/trade/history").status_code == 200


def test_errors(client):
    assert client.post("/api/trade/open", json=open_body(qty=50)).status_code == 422
    r = client.post("/api/trade/open", json=open_body(qty=100000))
    assert r.status_code == 422 and "建余力" in r.json()["detail"]
    r = client.post("/api/trade/open", json=open_body(executed_at="2026-10-19T08:30"))
    assert r.status_code == 422 and "立会時間外" in r.json()["detail"]
    r = client.post("/api/trade/close", json={"position_id": "P99999", "qty": 100, "price": 1})
    assert r.status_code == 404


def test_day_position_forced_close_next_day(client):
    pid = client.post("/api/trade/open", json=open_body()).json()["position"]["id"]
    client.px["close"] = 990.0
    client.clock["now"] = jst(2026, 10, 20, 8, 0)
    a = client.get("/api/trade/account").json()
    assert a["positions"] == []
    h = client.get("/api/trade/trades").json()["trades"][0]
    assert h["position_id"] == pid and h["exit_reason"] == "day_close" and h["net_pnl"] == -1000


def test_reset_keeps_old_account(client):
    old = client.get("/api/trade/account").json()["account_id"]
    client.post("/api/trade/open", json=open_body(margin_type="system"))
    client.clock["now"] = jst(2026, 10, 19, 11, 0)
    r = client.post("/api/trade/reset", json={"initial_cash": 3_000_000})
    assert r.status_code == 200 and r.json()["initial_cash"] == 3_000_000 and r.json()["positions"] == []
    assert r.json()["account_id"] != old and (client.root / "accounts" / f"{old}.json").exists()
    assert client.post("/api/trade/reset", json={"initial_cash": 1000}).status_code == 422


def test_save_failure_is_502(client, monkeypatch):
    from app.trade import store as tstore

    def boom(*a, **k):
        raise RuntimeError("403 Forbidden")
    monkeypatch.setattr(tstore, "save", boom)
    r = client.get("/api/trade/account")
    assert r.status_code == 502 and "保存に失敗" in r.json()["detail"]


def test_close_group_route_and_roadmap(client):
    client.post("/api/trade/open", json=open_body(price=1000))
    assert client.post("/api/trade/open", json=open_body(price=990, stop=980)).status_code == 200
    a = client.get("/api/trade/account").json()
    assert len(a["groups"]) == 1 and a["groups"][0]["qty"] == 200 and a["groups"][0]["avg_price"] == 995
    assert a["roadmap"][0]["title"].startswith("Phase 1")
    r = client.post("/api/trade/close_group", json={"key": a["groups"][0]["key"], "qty": 200, "price": 1000})
    assert r.status_code == 200, r.text
    assert len(r.json()["trades"]) == 2 and r.json()["account"]["positions"] == []
    assert r.json()["trades"][1]["add_type"] == "nanpin"


def test_edit_routes(client):
    pid = client.post("/api/trade/open", json=open_body(memo="")).json()["position"]["id"]
    r = client.patch(f"/api/trade/positions/{pid}", json={"memo": "あとで追記", "emotion": "焦り"})
    assert r.status_code == 200 and r.json()["position"]["memo"] == "あとで追記"
    t = client.post("/api/trade/close", json={"position_id": pid, "qty": 100, "price": 985}).json()["trade"]
    r = client.patch(f"/api/trade/trades/{t['id']}", json={"close_price": 1030, "exit_memo": "入力ミス修正"})
    assert r.status_code == 200, r.text
    assert r.json()["trade"]["net_pnl"] == 3000 and r.json()["account"]["cash"] == 5_003_000
    assert client.patch(f"/api/trade/trades/{t['id']}", json={"tags": ["なにか"]}).status_code == 422
    assert client.patch("/api/trade/trades/T99999", json={"memo": "x"}).status_code == 404


def test_edit_time_route(client):
    pid = client.post("/api/trade/open", json=open_body()).json()["position"]["id"]
    t = client.post("/api/trade/close", json={"position_id": pid, "qty": 100, "price": 1010}).json()["trade"]
    r = client.patch(f"/api/trade/trades/{t['id']}", json={"closed_at": "2026-10-19T09:00", "opened_at": "2026-10-19T09:00"})
    assert r.status_code == 200, r.text
    assert r.json()["trade"]["holding_minutes"] == 0
    r = client.patch(f"/api/trade/trades/{t['id']}", json={"closed_at": "2026-10-19T08:00"})
    assert r.status_code == 422 and "立会時間外" in r.json()["detail"]


def test_exit_type_routes(client):
    pid = client.post("/api/trade/open", json=open_body()).json()["position"]["id"]
    bad = client.post("/api/trade/close", json={"position_id": pid, "qty": 100, "price": 1010, "exit_type": "nope"})
    assert bad.status_code == 422
    t = client.post("/api/trade/close", json={"position_id": pid, "qty": 100, "price": 1010,
                                               "exit_type": "board_exit"}).json()["trade"]
    assert t["exit_type"] == "board_exit"
    r = client.patch(f"/api/trade/trades/{t['id']}", json={"exit_type": "plan_target"})
    assert r.json()["trade"]["exit_type"] == "plan_target"
    st = client.get("/api/trade/trades").json()["stats"]
    assert st["by_exit_type"][0]["key"] == "計画どおり利確"
