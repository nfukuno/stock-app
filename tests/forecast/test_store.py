import base64
import json

from app.forecast import results, store
from tests.forecast.conftest import make_pred


def test_local_roundtrip(tmp_path):
    st = store.LocalStore(tmp_path)
    assert st.get("2026-10-08", "7203.T") is None
    p = make_pred()
    st.put(p)
    assert (tmp_path / "2026/10/2026-10-08_7203.T.json").exists()
    assert st.get("2026-10-08", "7203.T") == p
    st.put(make_pred(symbol="6758.T"))
    assert len(st.list_all()) == 2
    st.write_text("results.csv", "a,b\n")
    assert st.read_text("results.csv") == "a,b\n"
    assert st.read_text("none.csv") is None


class FakeResp:
    def __init__(self, status=200, data=None, text=""):
        self.status_code, self._data, self.text = status, data, text

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


def test_github_store(monkeypatch):
    files = {}  # path -> (sha, text)
    calls = []

    def fake_get(url, headers=None, params=None, timeout=None):
        path = url.split("/contents/")[1]
        calls.append(("GET", path))
        if path not in files:
            return FakeResp(404)
        sha, text = files[path]
        return FakeResp(200, {"sha": sha, "content": base64.b64encode(text.encode()).decode()})

    def fake_put(url, headers=None, json=None, timeout=None):
        path = url.split("/contents/")[1]
        old = files.get(path)
        assert json["branch"] == "main"
        assert (old is None) == ("sha" not in json)       # 更新時のみ sha を付ける
        if old:
            assert json["sha"] == old[0]
        files[path] = (f"sha{len(calls)}", base64.b64decode(json["content"]).decode())
        calls.append(("PUT", path))
        return FakeResp(201, {})

    monkeypatch.setattr(store.requests, "get", fake_get)
    monkeypatch.setattr(store.requests, "put", fake_put)
    st = store.GitHubStore(repo="o/r", branch="main", token="TOKEN")
    assert st.get("2026-10-08", "7203.T") is None
    p = make_pred()
    st.put(p)
    st.put(make_pred(memo="更新"))                       # 2 回目は sha 付き
    assert "forecasts/2026/10/2026-10-08_7203.T.json" in files
    assert st.get("2026-10-08", "7203.T")["memo"] == "更新"
    assert json.loads(files["forecasts/2026/10/2026-10-08_7203.T.json"][1])["id"] == p["id"]
    assert st._headers()["Authorization"] == "Bearer TOKEN"


def test_results_csv():
    scored = make_pred(
        status="scored",
        actual={"open": 100.0, "high": 109.0, "low": 98.0, "close": 107.0, "prev_close": 100.0, "atr14": 10.0},
        actual_scenario="up_trend",
        score={"total": 80.0, "direction": 100, "close": 90, "open": 90, "range_iou": 60,
               "body_iou": 50, "shadow": 80, "scenario_hit": True},
        baselines={"flat": {"total": 50.0}, "prev_copy": {"total": None}}, skill=30.0,
        scored_at="2026-10-08T16:31:00+09:00", scoring_version=1)
    csv_text = results.build_csv([scored, make_pred(symbol="6758.T")])
    lines = csv_text.strip().split("\n")
    assert len(lines) == 2                          # pending は含まない
    row = dict(zip(lines[0].split(","), results.to_row(scored).values()))
    assert row["pred_change_atr"] == 0.6 and row["act_change_atr"] == 0.7
    assert row["weekday"] == 3 and row["memo"] == "メモ テスト"
    assert row["skill"] == 30.0


def test_github_list_symbols(monkeypatch):
    listing = [{"name": "2026-10-09_5801.T.json"}, {"name": "2026-10-09_7203.T.json"},
               {"name": "2026-10-08_6758.T.json"}, {"name": "readme.md"}]
    monkeypatch.setattr(store.requests, "get",
                        lambda url, **k: FakeResp(200, listing) if url.endswith("/forecasts/2026/10") else FakeResp(404))
    st = store.GitHubStore(repo="o/r", branch="main", token="t")
    assert st.list_symbols("2026-10-09") == ["5801.T", "7203.T"]
    assert st.list_symbols("2026-11-02") == []
