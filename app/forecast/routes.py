"""日足予想の画面と API。"""
from __future__ import annotations

import csv
import json
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from . import config, market, stats
from .models import ForecastIn, prediction_id
from .store import get_store

router = APIRouter()
templates = Jinja2Templates(directory=str(config.TEMPLATES_DIR))


def load_symbols() -> list[dict]:
    with open(config.SYMBOLS_CSV, newline="", encoding="utf-8") as f:
        return [{"symbol": r["symbol"], "name": r["name"]} for r in csv.DictReader(f)]


WATCHLIST = "symbols.json"     # 保存したことのある銘柄 {symbol: name}（ストア上に保持）


def load_watchlist(store) -> dict:
    try:
        d = json.loads(store.read_text(WATCHLIST) or "{}")
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def resolve_name(symbol: str, store=None, override: str = "", watch: dict | None = None, fetch: bool = True) -> str:
    """銘柄名: 入力値 > 自分の銘柄リスト > CSV > yfinance > コード。"""
    if override and override.strip():
        return override.strip()
    if watch is None:
        watch = load_watchlist(store) if store is not None else {}
    if watch.get(symbol) and watch[symbol] != symbol:
        return watch[symbol]
    for s in load_symbols():
        if s["symbol"] == symbol:
            return s["name"]
    return (market.lookup_name(symbol) if fetch else None) or symbol


def all_symbols(store, extra: list[str] = ()) -> list[dict]:
    """CSV + 自分の銘柄リスト + extra（その日に保存済みの銘柄）。重複なし・順序維持。"""
    watch = load_watchlist(store)
    out = [dict(s) for s in load_symbols()]
    seen = {s["symbol"] for s in out}
    for sym in list(watch) + list(extra):
        if sym not in seen:
            seen.add(sym)
            out.append({"symbol": sym, "name": resolve_name(sym, store, watch=watch, fetch=False)})
    return out


def _scenario_ctx() -> list[dict]:
    return [{"key": k, "label": l, "rule": r} for k, l, r in config.SCENARIOS]


def _load_results_df():
    return stats.load_results(get_store().read_text("results.csv"))


# ---------------------------------------------------------------- 画面
@router.get("/forecast", response_class=HTMLResponse)
def forecast_index(request: Request):
    now = market.now_jst()
    target = market.target_date_for(now)
    store = get_store()
    items, error = [], None
    try:
        extra = store.list_symbols(target.isoformat())
    except Exception:
        extra = []
    for s in all_symbols(store, extra):
        try:
            saved = store.get(target.isoformat(), s["symbol"])
        except Exception as e:                     # GitHub 側の一時エラーで画面を落とさない
            saved, error = None, f"保存済み予想の取得に失敗しました: {e}"
        if saved and saved.get("name") and saved["name"] != s["symbol"]:
            s = {**s, "name": saved["name"]}
        items.append({**s, "saved": saved})
    try:
        recent = stats.to_records(stats.filter_results(_load_results_df(), include_late=True).tail(5).iloc[::-1])
    except Exception:
        recent = []
    return templates.TemplateResponse(request, "forecast_index.html", {
        "target_date": target.isoformat(), "items": items, "recent": recent, "error": error,
        "labels": config.SCENARIO_LABELS, "locked_at": market.lock_time(target).strftime("%H:%M"),
    })


@router.get("/forecast/dashboard", response_class=HTMLResponse)   # /forecast/{symbol} より先に登録
def forecast_dashboard(request: Request):
    return templates.TemplateResponse(request, "forecast_dashboard.html", {
        "scenarios": _scenario_ctx(), "symbols": all_symbols(get_store()), "pages_url": config.PAGES_BASE_URL})


@router.get("/forecast/{symbol}", response_class=HTMLResponse)
def forecast_input(request: Request, symbol: str):
    sym = market.normalize_symbol(symbol)
    return templates.TemplateResponse(request, "forecast_input.html", {
        "symbol": sym, "name": "", "scenarios": _scenario_ctx(),
        "memo_max": config.MEMO_MAX})


# ---------------------------------------------------------------- API
@router.get("/api/forecast/candles/{symbol}")
def api_candles(symbol: str, days: int = 120):
    sym = market.normalize_symbol(symbol)
    days = max(30, min(days, 400))
    now = market.now_jst()
    target = market.target_date_for(now)
    try:
        df = market.fetch_daily(sym, days + 5)
    except Exception as e:
        raise HTTPException(502, f"株価の取得に失敗しました: {e}")
    snap = market.snapshot_before(df, target)
    if snap is None:
        raise HTTPException(404, f"{sym} の日足が取得できません")
    hist = df[[d < target for d in df.index]].tail(days)
    bars = [{"time": d.isoformat(), "open": round(float(r.open), 1), "high": round(float(r.high), 1),
             "low": round(float(r.low), 1), "close": round(float(r.close), 1), "volume": int(r.volume)}
            for d, r in hist.iterrows()]
    try:
        existing = get_store().get(target.isoformat(), sym)
    except Exception as e:
        raise HTTPException(502, f"保存済み予想の取得に失敗しました: {e}")
    locked = now >= market.lock_time(target)
    name = (existing or {}).get("name") or ""
    if not name or name == sym:
        name = resolve_name(sym, get_store())
    return {"symbol": sym, "name": name, "bars": bars, "prev_close": snap["prev_close"],
            "prev_date": snap["prev_date"], "atr14": snap["atr14"], "target_date": target.isoformat(),
            "locked": existing is not None and (locked or existing.get("status") != "pending"),
            "past_lock": locked, "existing": existing}


@router.get("/api/forecast/results")
def api_results(include_late: bool = False, symbol: str | None = None,
                date_from: str | None = Query(None, alias="from"), date_to: str | None = Query(None, alias="to"),
                last: int | None = None):
    try:
        df = _load_results_df()
    except Exception as e:
        raise HTTPException(502, f"results.csv の取得に失敗しました: {e}")
    df = stats.filter_results(df, include_late, symbol, date_from, date_to, last)
    return {"records": stats.to_records(df), "summary": stats.dashboard(df)}


@router.get("/api/forecast/{target_date}/{symbol}")
def api_get(target_date: str, symbol: str):
    p = get_store().get(target_date, market.normalize_symbol(symbol))
    if p is None:
        raise HTTPException(404, "予想がありません")
    return p


@router.post("/api/forecast")
def api_save(body: ForecastIn):
    sym = market.normalize_symbol(body.symbol)
    now = market.now_jst()
    target = market.target_date_for(now)
    if body.target_date != target.isoformat():
        raise HTTPException(422, f"対象日が変わりました（現在の対象日: {target.isoformat()}）。画面を開き直してください")
    store = get_store()
    existing = store.get(body.target_date, sym)
    past_lock = now >= market.lock_time(target)
    if existing is not None and (past_lock or existing.get("status") != "pending"):
        raise HTTPException(409, "9:00 を過ぎた（または採点済みの）予想は編集できません")
    try:
        df = market.fetch_daily(sym, 60)
    except Exception as e:
        raise HTTPException(502, f"株価の取得に失敗しました: {e}")
    snap = market.snapshot_before(df, target)
    if snap is None:
        raise HTTPException(404, f"{sym} の日足が取得できません")
    watch = load_watchlist(store)
    name = resolve_name(sym, store, body.name or ((existing or {}).get("name") if (existing or {}).get("name") != sym else ""), watch)
    ts = now.isoformat(timespec="seconds")
    pred = {
        "id": prediction_id(body.target_date, sym), "schema_version": 1, "symbol": sym,
        "name": name, "target_date": body.target_date,
        "created_at": existing["created_at"] if existing else ts, "updated_at": ts,
        "late": bool(existing["late"]) if existing else past_lock,
        "snapshot": snap, "pred": body.pred.rounded(), "scenario": body.scenario,
        "confidence": body.confidence, "memo": body.memo, "status": "pending",
        "actual": None, "actual_scenario": None, "score": None, "baselines": None,
        "scored_at": None, "scoring_version": None,
    }
    store.put(pred)
    if watch.get(sym) != name:                      # 次回から一覧に常に表示する
        try:
            store.write_text(WATCHLIST, json.dumps({**watch, sym: name}, ensure_ascii=False, indent=2) + "\n")
        except Exception:
            pass
    return pred
