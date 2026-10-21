"""仮想信用口座の計算（I/O なし）。口座は dict で、建玉 positions と約定済みトレード trades を持つ。

保証金の考え方（国内証券の信用取引に準拠）:
- 現金保証金 = 初期保証金 + 確定損益の累計
- 実質保証金 = 現金保証金 + min(0, 評価損益合計) - 未払いの金利・貸株料   ※評価益は保証金に算入しない
- 維持率 = 実質保証金 / 建玉代金。MAINTENANCE_RATE を下回ると追証（新規建不可）
- 新規建余力 = (実質保証金 - 建玉代金 × MARGIN_RATE) / MARGIN_RATE
"""
from __future__ import annotations

import calendar
import math
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Callable

from app.forecast import market
from . import config as c

JST = market.JST
WEEKDAYS = "月火水木金土日"


class TradeError(Exception):
    def __init__(self, message: str, status: int = 422):
        super().__init__(message)
        self.status = status


# ---------------------------------------------------------------- 口座
def new_account(now: datetime, initial_cash: int = c.INITIAL_CASH) -> dict:
    return {
        "schema_version": 1, "id": now.strftime("%Y%m%d-%H%M%S"),
        "created_at": now.isoformat(timespec="seconds"), "initial_cash": int(initial_cash),
        "seq": 0, "positions": [], "trades": [],
    }


def _next_id(acct: dict, prefix: str) -> str:
    acct["seq"] += 1
    return f"{prefix}{acct['seq']:05d}"


def cash_balance(acct: dict) -> int:
    return acct["initial_cash"] + sum(t["net_pnl"] for t in acct["trades"])


# ---------------------------------------------------------------- 日付・時刻
def settlement_date(d: date) -> date:
    for _ in range(c.SETTLEMENT_DAYS):
        d = market.next_trading_day(d)
    return d


def expiry_date(open_date: date, months: int) -> date:
    """期日 = 建日の months ヶ月後の応当日。休業日なら前営業日。"""
    m = open_date.month - 1 + months
    y, m = open_date.year + m // 12, m % 12 + 1
    d = date(y, m, min(open_date.day, calendar.monthrange(y, m)[1]))
    return d if market.is_trading_day(d) else market.prev_trading_day(d)


def at_close(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, *c.CLOSE_HM, tzinfo=JST)


def in_session(dt: datetime) -> bool:
    dt = dt.astimezone(JST)
    t = (dt.hour, dt.minute, dt.second + dt.microsecond / 1e6)
    return market.is_trading_day(dt.date()) and any((*s, 0) <= t <= (*e, 0) for s, e in c.SESSIONS)


def _check_time(at: datetime, now: datetime) -> None:
    if (at - now).total_seconds() > c.FUTURE_TOLERANCE_SEC:
        raise TradeError("約定時刻が未来になっています")
    if not in_session(at):
        raise TradeError("約定時刻が立会時間外です（9:00〜11:30 / 12:30〜15:30、取引日のみ）")


# ---------------------------------------------------------------- 金利・貸株料
def carry_cost(margin_type: str, side: str, price: float, qty: int, open_date: date, close_date: date) -> tuple[int, int]:
    """(費用[円], 日数)。受渡日〜受渡日の両端入れ・年365日・円未満切り捨て。売方金利は費用から差し引く。"""
    mt = c.MARGIN_TYPES[margin_type]
    rate = mt["buy_rate"] if side == "long" else mt["lending_fee"] - mt["sell_rate"]
    if rate == 0:
        return 0, 0
    days = (settlement_date(close_date) - settlement_date(open_date)).days + 1
    raw = price * qty * abs(rate) / 100 * days / 365
    return int(math.copysign(math.floor(raw), rate)), days


def _sign(side: str) -> int:
    return 1 if side == "long" else -1


# ---------------------------------------------------------------- 新規・返済
def open_position(acct: dict, o, at: datetime, now: datetime, name: str, prices: dict[str, float | None]) -> dict:
    _check_time(at, now)
    s = summary(acct, prices, now)
    if s["margin_call"]:
        raise TradeError("追証が発生しているため新規建てできません（建玉を返済して維持率を回復してください）")
    if s["effective_margin"] < c.MIN_MARGIN:
        raise TradeError(f"実質保証金が最低保証金 {c.MIN_MARGIN:,} 円を下回っています")
    need = o.price * o.qty * c.MARGIN_RATE
    if need > s["free_margin"]:
        raise TradeError(f"建余力が不足しています（必要保証金 {need:,.0f} 円 / 余力 {max(0, s['free_margin']):,.0f} 円）")
    mt = c.MARGIN_TYPES[o.margin_type]
    pos = {
        "id": _next_id(acct, "P"), "symbol": o.symbol, "name": name, "margin_type": o.margin_type,
        "side": o.side, "qty": o.qty, "initial_qty": o.qty, "open_price": o.price,
        "opened_at": at.isoformat(timespec="seconds"), "open_date": at.date().isoformat(),
        "entered_at": now.isoformat(timespec="seconds"),
        "expiry_date": (expiry_date(at.date(), mt["expiry_months"]) if mt["expiry_months"] else at.date()).isoformat(),
        "stop": o.stop, "target": o.target, "tags": o.tags, "emotion": o.emotion, "memo": o.memo,
    }
    acct["positions"].append(pos)
    return pos


def close_position(acct: dict, position_id: str, qty: int, price: float, at: datetime, now: datetime,
                   memo: str = "", reason: str = "manual") -> dict:
    pos = next((p for p in acct["positions"] if p["id"] == position_id), None)
    if pos is None:
        raise TradeError("建玉が見つかりません（すでに返済済みの可能性があります）", 404)
    if qty > pos["qty"]:
        raise TradeError(f"返済株数が建玉 {pos['qty']} 株を超えています")
    opened = datetime.fromisoformat(pos["opened_at"])
    if reason == "manual":
        _check_time(at, now)
        if at < opened:
            raise TradeError("返済時刻が建てた時刻より前です")
        if at.date().isoformat() > pos["expiry_date"]:
            raise TradeError("期日を過ぎた建玉です")
    open_date = date.fromisoformat(pos["open_date"])
    sign = _sign(pos["side"])
    gross = round((price - pos["open_price"]) * qty * sign)
    cost, days = carry_cost(pos["margin_type"], pos["side"], pos["open_price"], qty, open_date, at.date())
    commission = c.MARGIN_TYPES[pos["margin_type"]]["commission"]
    net = gross - cost - commission
    risk = abs(pos["open_price"] - pos["stop"]) * qty if pos.get("stop") else None
    trade = {
        "id": _next_id(acct, "T"), "position_id": pos["id"], "symbol": pos["symbol"], "name": pos["name"],
        "margin_type": pos["margin_type"], "side": pos["side"], "qty": qty,
        "open_price": pos["open_price"], "close_price": price,
        "opened_at": pos["opened_at"], "closed_at": at.isoformat(timespec="seconds"),
        "open_date": pos["open_date"], "close_date": at.date().isoformat(),
        "entered_at": now.isoformat(timespec="seconds"),
        "holding_minutes": int((at - opened).total_seconds() // 60),
        "gross_pnl": gross, "carry_cost": cost, "carry_days": days, "commission": commission, "net_pnl": net,
        "stop": pos.get("stop"), "target": pos.get("target"),
        "r_multiple": round(net / risk, 2) if risk else None,
        "planned_rr": (round(abs(pos["target"] - pos["open_price"]) / abs(pos["open_price"] - pos["stop"]), 2)
                       if pos.get("stop") and pos.get("target") else None),
        "beyond_stop": ((price - pos["stop"]) * sign < 0) if pos.get("stop") else None,
        "tags": pos["tags"], "emotion": pos["emotion"], "memo": pos["memo"], "exit_memo": memo,
        "exit_reason": reason,
    }
    acct["trades"].append(trade)
    pos["qty"] -= qty
    if pos["qty"] == 0:
        acct["positions"].remove(pos)
    return trade


def apply_forced(acct: dict, now: datetime, close_price: Callable[[str, date], float | None]) -> list[dict]:
    """いちにち信用は建日の大引け、制度信用は期日の大引けで、その日の終値で強制返済する。
    終値がまだ取れないものは残す（summary で overdue 表示）。"""
    done = []
    for pos in list(acct["positions"]):
        due = date.fromisoformat(pos["expiry_date"])
        if now < at_close(due):
            continue
        px = close_price(pos["symbol"], due)
        if px is None:
            continue
        reason = "day_close" if pos["margin_type"] == "day" else "expiry"
        done.append(close_position(acct, pos["id"], pos["qty"], px, at_close(due), now,
                                   "大引けで強制返済", reason))
    return done


# ---------------------------------------------------------------- 口座サマリー
def summary(acct: dict, prices: dict[str, float | None], now: datetime) -> dict:
    today = now.astimezone(JST).date()
    rows, unreal_total, accrued_total, amount_total, stale = [], 0, 0, 0, False
    for p in acct["positions"]:
        last = prices.get(p["symbol"])
        unreal = round((last - p["open_price"]) * p["qty"] * _sign(p["side"])) if last else None
        accrued, _ = carry_cost(p["margin_type"], p["side"], p["open_price"], p["qty"],
                                date.fromisoformat(p["open_date"]), max(today, date.fromisoformat(p["open_date"])))
        amount = p["open_price"] * p["qty"]
        stale |= last is None
        unreal_total += unreal or 0
        accrued_total += accrued
        amount_total += amount
        rows.append({**p, "last": last, "unrealized": unreal, "accrued_cost": accrued, "amount": round(amount),
                     "overdue": now >= at_close(date.fromisoformat(p["expiry_date"])),
                     "label": c.MARGIN_TYPES[p["margin_type"]]["label"]})
    cash = cash_balance(acct)
    effective = cash + min(0, unreal_total) - accrued_total
    maintenance = effective / amount_total if amount_total else None
    free = effective - amount_total * c.MARGIN_RATE
    today_trades = [t for t in acct["trades"] if t["close_date"] == today.isoformat()]
    return {
        "account_id": acct["id"], "initial_cash": acct["initial_cash"], "cash": cash,
        "realized_total": cash - acct["initial_cash"], "unrealized": unreal_total, "accrued_cost": accrued_total,
        "equity": cash + unreal_total - accrued_total, "effective_margin": round(effective),
        "position_amount": round(amount_total), "maintenance_rate": maintenance,
        "margin_call": maintenance is not None and maintenance < c.MAINTENANCE_RATE,
        "free_margin": round(free), "buying_power": max(0, round(free / c.MARGIN_RATE)) if effective >= c.MIN_MARGIN else 0,
        "today_realized": sum(t["net_pnl"] for t in today_trades), "today_count": len(today_trades),
        "positions": rows, "prices_stale": stale,
    }


# ---------------------------------------------------------------- 成績
def _group(trades: list[dict]) -> dict:
    n = len(trades)
    wins = [t for t in trades if t["net_pnl"] > 0]
    total = sum(t["net_pnl"] for t in trades)
    return {"n": n, "win_rate": len(wins) / n if n else None, "total": total, "avg": total / n if n else None}


def stats(trades: list[dict]) -> dict:
    ts = sorted(trades, key=lambda t: t["closed_at"])
    n = len(ts)
    wins = [t["net_pnl"] for t in ts if t["net_pnl"] > 0]
    losses = [t["net_pnl"] for t in ts if t["net_pnl"] <= 0]
    rs = [t["r_multiple"] for t in ts if t.get("r_multiple") is not None]
    peak = cum = max_dd = streak = max_streak = 0
    curve = []
    for t in ts:
        cum += t["net_pnl"]
        peak = max(peak, cum)
        max_dd = max(max_dd, peak - cum)
        streak = streak + 1 if t["net_pnl"] <= 0 else 0
        max_streak = max(max_streak, streak)
        curve.append({"closed_at": t["closed_at"], "cum": cum})
    with_stop = [t for t in ts if t.get("beyond_stop") is not None]
    hold = lambda xs: sum(t["holding_minutes"] for t in xs) / len(xs) if xs else None  # noqa: E731

    def by(key: Callable[[dict], list[str] | str], order: Callable[[str], object] = str) -> list[dict]:
        g = defaultdict(list)
        for t in ts:
            ks = key(t)
            for k in (ks if isinstance(ks, list) else [ks]):
                g[k].append(t)
        return [{"key": k, **_group(v)} for k, v in sorted(g.items(), key=lambda kv: order(kv[0]))]

    return {
        **_group(ts),
        "wins": len(wins), "losses": len(losses),
        "avg_win": sum(wins) / len(wins) if wins else None,
        "avg_loss": sum(losses) / len(losses) if losses else None,
        "profit_factor": sum(wins) / -sum(losses) if losses and sum(losses) < 0 else None,
        "avg_r": sum(rs) / len(rs) if rs else None, "r_count": len(rs),
        "max_drawdown": max_dd, "max_loss_streak": max_streak,
        "avg_hold_win": hold([t for t in ts if t["net_pnl"] > 0]),
        "avg_hold_loss": hold([t for t in ts if t["net_pnl"] <= 0]),
        "stop_set_rate": len(with_stop) / n if n else None,
        "beyond_stop": sum(1 for t in with_stop if t["beyond_stop"]),
        "curve": curve,
        "by_tag": by(lambda t: t["tags"] or ["(なし)"]),
        "by_margin_type": by(lambda t: c.MARGIN_TYPES[t["margin_type"]]["label"]),
        "by_side": by(lambda t: "買い" if t["side"] == "long" else "売り"),
        "by_hour": by(lambda t: f"{datetime.fromisoformat(t['opened_at']).hour:02d}時台"),
        "by_weekday": by(lambda t: WEEKDAYS[date.fromisoformat(t["open_date"]).weekday()], WEEKDAYS.index),
        "by_emotion": by(lambda t: t["emotion"] or "(なし)"),
        "by_symbol": by(lambda t: f"{t['symbol']} {t['name']}".strip()),
    }
