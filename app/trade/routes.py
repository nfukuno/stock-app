"""仮想信用口座の画面と API。"""
from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.forecast import config as fconfig
from app.forecast import market
from app.forecast.routes import resolve_name
from . import config, engine, store as tstore
from .models import CloseGroupIn, CloseIn, EditIn, OpenIn, ResetIn

router = APIRouter()
templates = Jinja2Templates(directory=str(fconfig.TEMPLATES_DIR))


def last_price(symbol: str) -> float | None:
    """直近値（yfinance の当日足の終値。場中は遅延した現在値）。取れなければ None。"""
    try:
        df = market.fetch_daily(symbol, 5)
        return round(float(df["close"].iloc[-1]), 1) if not df.empty else None
    except Exception:
        return None


def close_price_on(symbol: str, d: date) -> float | None:
    """d の確定した終値。当日分は日足が確定する時刻まで None。"""
    now = market.now_jst()
    final = datetime(d.year, d.month, d.day, fconfig.CANDLE_FINAL_HOUR, fconfig.CANDLE_FINAL_MIN, tzinfo=market.JST)
    if now < final:
        return None
    try:
        df = market.fetch_daily(symbol, max(10, (now.date() - d).days + 10))
    except Exception:
        return None
    return round(float(df.loc[d, "close"]), 1) if d in df.index else None


def _prices(acct: dict, extra: str | None = None) -> dict:
    syms = {p["symbol"] for p in acct["positions"]} | ({extra} if extra else set())
    return {s: last_price(s) for s in syms}


def _save(store, acct: dict, message: str, make_current: bool = False) -> None:
    try:
        tstore.save(store, acct, message, make_current)
    except Exception as e:
        hint = "（.env の FORECAST_GITHUB_TOKEN と権限 Contents: Read and write を確認してください）" \
            if config.storage_mode() == "github" else ""
        raise HTTPException(502, f"口座の保存に失敗しました: {e}{hint}")


def _load(store) -> dict:
    """現在の口座を読み、強制返済を反映する（反映があれば保存）。口座がなければ作る。"""
    now = market.now_jst()
    try:
        acct = tstore.load_current(store)
    except Exception as e:
        raise HTTPException(502, f"口座の読み込みに失敗しました: {e}")
    if acct is None:
        acct = engine.new_account(now)
        _save(store, acct, f"open account {acct['id']}", make_current=True)
    forced = engine.apply_forced(acct, now, close_price_on)
    if forced:
        _save(store, acct, f"forced close {', '.join(t['id'] for t in forced)}")
    return acct


def _view(acct: dict) -> dict:
    now = market.now_jst()
    s = engine.summary(acct, _prices(acct), now)
    today = now.date().isoformat()
    s["today_trades"] = [t for t in reversed(acct["trades"]) if t["close_date"] == today]
    s["as_of"] = now.isoformat(timespec="seconds")
    s["roadmap"] = engine.roadmap(engine.stats(acct["trades"]), acct["initial_cash"])
    return s


def _time(at: datetime | None) -> datetime:
    now = market.now_jst()
    return (at or now).astimezone(market.JST)


def _err(e: engine.TradeError):
    return HTTPException(e.status, str(e))


# ---------------------------------------------------------------- 画面
def _static_version() -> int:
    """JS のキャッシュ対策。更新時刻をクエリに付けて、変更後は必ず読み直させる。"""
    js = fconfig.STATIC_DIR / "js"
    return int(max((js / f).stat().st_mtime for f in ("trade.js", "trade_history.js", "trade_edit.js")))


def _ctx() -> dict:
    return {"margin_types": config.MARGIN_TYPES, "tags": config.TAGS, "emotions": config.EMOTIONS,
            "lot": config.LOT, "memo_max": config.MEMO_MAX, "v": _static_version()}


@router.get("/trade", response_class=HTMLResponse)
def trade_index(request: Request):
    return templates.TemplateResponse(request, "trade_index.html", _ctx())


@router.get("/trade/history", response_class=HTMLResponse)
def trade_history(request: Request):
    return templates.TemplateResponse(request, "trade_history.html", _ctx())


# ---------------------------------------------------------------- API
@router.get("/api/trade/account")
def api_account():
    return _view(_load(tstore.get_store()))


@router.get("/api/trade/quote/{symbol}")
def api_quote(symbol: str):
    sym = market.normalize_symbol(symbol)
    return {"symbol": sym, "name": resolve_name(sym), "last": last_price(sym)}


@router.post("/api/trade/open")
def api_open(body: OpenIn):
    store = tstore.get_store()
    acct = _load(store)
    now = market.now_jst()
    sym = market.normalize_symbol(body.symbol)
    body = body.model_copy(update={"symbol": sym})
    try:
        pos = engine.open_position(acct, body, _time(body.executed_at), now, resolve_name(sym, override=body.name),
                                   _prices(acct, sym))
    except engine.TradeError as e:
        raise _err(e)
    engine.apply_forced(acct, now, close_price_on)        # 過去日のいちにち信用を入力した場合など
    side = "買" if pos["side"] == "long" else "売"
    _save(store, acct, f"open {pos['id']} {sym} {side} {pos['qty']}@{pos['open_price']}")
    return {"position": pos, "account": _view(acct)}


@router.post("/api/trade/close")
def api_close(body: CloseIn):
    store = tstore.get_store()
    acct = _load(store)
    now = market.now_jst()
    try:
        tr = engine.close_position(acct, body.position_id, body.qty, body.price, _time(body.executed_at), now, body.memo)
    except engine.TradeError as e:
        raise _err(e)
    _save(store, acct, f"close {tr['id']} {tr['symbol']} {tr['qty']}@{tr['close_price']} {tr['net_pnl']:+,}")
    return {"trade": tr, "account": _view(acct)}


@router.post("/api/trade/close_group")
def api_close_group(body: CloseGroupIn):
    store = tstore.get_store()
    acct = _load(store)
    now = market.now_jst()
    try:
        trades = engine.close_group(acct, body.key, body.qty, body.price, _time(body.executed_at), now, body.memo)
    except engine.TradeError as e:
        raise _err(e)
    net = sum(t["net_pnl"] for t in trades)
    _save(store, acct, f"close {','.join(t['id'] for t in trades)} {trades[0]['symbol']} {body.qty}@{body.price} {net:+,}")
    return {"trades": trades, "account": _view(acct)}


@router.patch("/api/trade/positions/{position_id}")
def api_edit_position(position_id: str, body: EditIn):
    """建玉の修正・追記（建値の打ち間違い、損切り / 利確、メモ・タグ・感情の後入力）。"""
    store = tstore.get_store()
    acct = _load(store)
    try:
        pos = engine.edit_position(acct, position_id, body.changes(), market.now_jst())
    except engine.TradeError as e:
        raise _err(e)
    _save(store, acct, f"edit {position_id}")
    return {"position": pos, "account": _view(acct)}


@router.patch("/api/trade/trades/{trade_id}")
def api_edit_trade(trade_id: str, body: EditIn):
    """返済済み約定の修正・追記。価格を直すと損益・R・金利を再計算する。"""
    store = tstore.get_store()
    acct = _load(store)
    try:
        tr = engine.edit_trade(acct, trade_id, body.changes(), market.now_jst())
    except engine.TradeError as e:
        raise _err(e)
    _save(store, acct, f"edit {trade_id} net {tr['net_pnl']:+,}")
    return {"trade": tr, "account": _view(acct)}


@router.post("/api/trade/reset")
def api_reset(body: ResetIn):
    """新しい口座を作って切り替える。過去の口座ファイルはそのまま残す。"""
    store = tstore.get_store()
    acct = engine.new_account(market.now_jst(), body.initial_cash)
    _save(store, acct, f"open account {acct['id']}", make_current=True)
    return _view(acct)


@router.get("/api/trade/trades")
def api_trades():
    acct = _load(tstore.get_store())
    return {"account_id": acct["id"], "initial_cash": acct["initial_cash"],
            "trades": list(reversed(acct["trades"])), "stats": engine.stats(acct["trades"])}
