from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app.forecast import market
from app.main import app
from tests.forecast.conftest import make_pred
from tests.forecast.test_market import make_df


def jst(*a):
    return datetime(*a, tzinfo=market.JST)


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("FORECAST_STORAGE", "local")
    monkeypatch.setenv("FORECAST_DATA_DIR", str(tmp_path))
    df = make_df(40)
    monkeypatch.setattr(market, "fetch_daily", lambda sym, days=120, use_cache=True: df)
    clock = {"now": jst(2026, 10, 30, 8, 0)}      # 金曜 朝 → 対象日=当日
    monkeypatch.setattr(market, "now_jst", lambda: clock["now"])
    c = TestClient(app)
    c.clock = clock
    c.target = "2026-10-30"
    return c


def body(target="2026-10-30", **kw):
    b = {"symbol": "7203", "target_date": target, "pred": {"open": 100, "high": 105, "low": 98, "close": 103},
         "scenario": "up_trend", "confidence": 3, "memo": "メモ"}
    b.update(kw)
    return b


def test_save_and_get(client):
    r = client.post("/api/forecast", json=body())
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["id"] == "2026-10-30_7203.T" and j["late"] is False and j["status"] == "pending"
    assert j["snapshot"]["prev_close"] > 0
    assert client.get("/api/forecast/2026-10-30/7203.T").json()["memo"] == "メモ"
    assert client.get("/api/forecast/2026-10-30/9999.T").status_code == 404
    # 上書き（ロック前）
    r2 = client.post("/api/forecast", json=body(memo="更新"))
    assert r2.status_code == 200 and r2.json()["created_at"] == j["created_at"]


@pytest.mark.parametrize("patch", [
    {"pred": {"open": 100, "high": 99, "low": 98, "close": 103}},      # high < close
    {"pred": {"open": 100, "high": 105, "low": 101, "close": 103}},    # low > open
    {"pred": {"open": -1, "high": 105, "low": 98, "close": 103}},
    {"scenario": "nope"}, {"confidence": 0}, {"confidence": 6}, {"memo": "あ" * 501},
])
def test_validation(client, patch):
    assert client.post("/api/forecast", json=body(**patch)).status_code == 422


def test_wrong_target_date(client):
    assert client.post("/api/forecast", json=body(target="2026-11-02")).status_code == 422


def test_lock_after_9(client):
    assert client.post("/api/forecast", json=body()).status_code == 200
    client.clock["now"] = jst(2026, 10, 30, 9, 0)
    assert client.post("/api/forecast", json=body(memo="x")).status_code == 409
    info = client.get("/api/forecast/candles/7203").json()
    assert info["locked"] is True and info["existing"]["memo"] == "メモ"


def test_late_new_after_9(client):
    client.clock["now"] = jst(2026, 10, 30, 10, 30)
    r = client.post("/api/forecast", json=body())
    assert r.status_code == 200 and r.json()["late"] is True
    # 遅延で保存したものも次回以降は編集不可
    assert client.post("/api/forecast", json=body(memo="x")).status_code == 409
    assert client.get("/api/forecast/candles/7203").json()["past_lock"] is True


def test_candles(client):
    j = client.get("/api/forecast/candles/7203?days=60").json()
    assert j["symbol"] == "7203.T" and all(b["time"] < "2026-10-30" for b in j["bars"]) and j["target_date"] == "2026-10-30"
    assert j["locked"] is False and j["existing"] is None and j["atr14"] > 0


def test_pages(client):
    for url in ["/forecast", "/forecast/7203", "/forecast/dashboard"]:
        assert client.get(url).status_code == 200, url
    assert "7203.T" in client.get("/forecast/7203").text


def test_results_empty(client):
    j = client.get("/api/forecast/results").json()
    assert j["records"] == [] and j["summary"]["n"] == 0


def test_custom_name_and_watchlist(client, monkeypatch):
    monkeypatch.setattr(market, "lookup_name", lambda s: None)
    r = client.post("/api/forecast", json=body(symbol="9999", name="テスト商事"))
    assert r.status_code == 200 and r.json()["name"] == "テスト商事"
    # 名前が保存され、画面（候補）に出る
    assert client.get("/api/forecast/candles/9999").json()["name"] == "テスト商事"
    html = client.get("/forecast").text
    assert "9999.T テスト商事" in html and "入力済み" in html
    # 翌日（別の対象日）でも、銘柄リストに残っている
    client.clock["now"] = jst(2026, 10, 30, 16, 0)
    html = client.get("/forecast").text
    assert "9999.T テスト商事" in html and "未入力" in html
    # 名前を省略して再保存しても名前は維持される
    client.clock["now"] = jst(2026, 10, 30, 8, 30)
    r = client.post("/api/forecast", json=body(symbol="9999"))
    assert r.json()["name"] == "テスト商事"


def test_name_fallbacks(client, monkeypatch):
    monkeypatch.setattr(market, "lookup_name", lambda s: "ACME CORP" if s == "1111.T" else None)
    assert client.post("/api/forecast", json=body(symbol="1111")).json()["name"] == "ACME CORP"
    assert client.post("/api/forecast", json=body(symbol="2222")).json()["name"] == "2222.T"
    assert client.post("/api/forecast", json=body(symbol="5801")).json()["name"] == "古河電気工業"   # CSV


def test_list_symbols_includes_saved_unlisted(client, monkeypatch):
    monkeypatch.setattr(market, "lookup_name", lambda s: None)
    from app.forecast.store import get_store
    st = get_store()
    st.put(make_pred(target="2026-10-30", symbol="4444.T", name="4444.T"))
    assert st.list_symbols("2026-10-30") == ["4444.T"]
    assert "4444.T" in client.get("/forecast").text
