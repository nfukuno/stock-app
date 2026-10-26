"""仮想信用口座の計算（I/O なし）。口座は dict で、建玉 positions と約定済みトレード trades を持つ。

保証金の考え方（国内証券の信用取引に準拠）:
- 現金保証金 = 初期保証金 + 確定損益の累計
- 実質保証金 = 現金保証金 + min(0, 評価損益合計) - 未払いの金利・貸株料   ※評価益は保証金に算入しない
- 維持率 = 実質保証金 / 建玉代金。MAINTENANCE_RATE を下回ると追証（新規建不可）
- 余力 = 実質保証金 - Σ(建玉代金 × 区分ごとの保証金率)。新規建余力（信用）= 余力 / MARGIN_RATE、現物買付余力 = 余力
- 維持率は信用建玉の代金に対して計算する（現物は含めない）
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


# ---------------------------------------------------------------- 建玉のまとまり
ADD_LABELS = {None: "単独・初回", "nanpin": "ナンピン（不利な価格で追加）", "pyramid": "買い増し・売り増し（有利な価格で追加）"}


def group_key(p: dict) -> str:
    """同じ銘柄・同じ売買・同じ信用区分の建玉をひとまとまりとして扱う。"""
    return f"{p['symbol']}|{p['side']}|{p['margin_type']}"


def _same_group(acct: dict, key: str) -> list[dict]:
    return sorted((p for p in acct["positions"] if group_key(p) == key), key=lambda p: (p["opened_at"], p["id"]))


def avg_price(positions: list[dict]) -> float:
    qty = sum(p["qty"] for p in positions)
    return sum(p["open_price"] * p["qty"] for p in positions) / qty


# ---------------------------------------------------------------- 新規・返済
def open_position(acct: dict, o, at: datetime, now: datetime, name: str, prices: dict[str, float | None]) -> dict:
    _check_time(at, now)
    s = summary(acct, prices, now)
    if s["margin_call"]:
        raise TradeError("追証が発生しているため新規建てできません（建玉を返済して維持率を回復してください）")
    if s["effective_margin"] < c.MIN_MARGIN:
        raise TradeError(f"実質保証金が最低保証金 {c.MIN_MARGIN:,} 円を下回っています")
    mt = c.MARGIN_TYPES[o.margin_type]
    need = o.price * o.qty * mt["margin_rate"]
    if need > s["free_margin"]:
        what = "買付代金" if o.margin_type == "cash" else "必要保証金"
        raise TradeError(f"余力が不足しています（{what} {need:,.0f} 円 / 余力 {max(0, s['free_margin']):,.0f} 円）")
    key = f"{o.symbol}|{o.side}|{o.margin_type}"
    existing = _same_group(acct, key)
    add_type = None
    if existing:
        # 既存建玉の平均建値より不利な価格（買いなら安く、売りなら高く）で追加 = ナンピン
        add_type = "nanpin" if (o.price - avg_price(existing)) * _sign(o.side) < 0 else "pyramid"
        if add_type == "nanpin":
            for p in existing:
                p["nanpin_group"] = True
    pos = {
        "id": _next_id(acct, "P"), "symbol": o.symbol, "name": name, "margin_type": o.margin_type,
        "side": o.side, "qty": o.qty, "initial_qty": o.qty, "open_price": o.price,
        "opened_at": at.isoformat(timespec="seconds"), "open_date": at.date().isoformat(),
        "entered_at": now.isoformat(timespec="seconds"),
        "expiry_date": _iso(_expiry_for(o.margin_type, at.date())),
        "stop": o.stop, "target": o.target, "tags": o.tags, "emotion": o.emotion, "memo": o.memo,
        "setup": o.setup, "plan_basis": o.plan_basis, "plan_exit_rule": o.plan_exit_rule,
        "plan_target_basis": o.plan_target_basis,
        "add_type": add_type, "nanpin_group": add_type == "nanpin",
        "horizon": o.horizon, **{k: _jsonable(getattr(o, k)) for k in SWING_FIELDS},
    }
    acct["positions"].append(pos)
    return pos


def close_position(acct: dict, position_id: str, qty: int, price: float, at: datetime, now: datetime,
                   memo: str = "", reason: str = "manual", exit_type: str = "") -> dict:
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
        if pos["expiry_date"] and at.date().isoformat() > pos["expiry_date"]:
            raise TradeError("期日を過ぎた建玉です")
    trade = {
        "id": _next_id(acct, "T"), "position_id": pos["id"], "symbol": pos["symbol"], "name": pos["name"],
        "margin_type": pos["margin_type"], "side": pos["side"], "qty": qty,
        "open_price": pos["open_price"], "close_price": price,
        "opened_at": pos["opened_at"], "closed_at": at.isoformat(timespec="seconds"),
        "open_date": pos["open_date"], "close_date": at.date().isoformat(),
        "entered_at": now.isoformat(timespec="seconds"),
        "holding_minutes": int((at - opened).total_seconds() // 60),
        "commission": c.MARGIN_TYPES[pos["margin_type"]]["commission"],
        "stop": pos.get("stop"), "target": pos.get("target"),
        "tags": pos["tags"], "emotion": pos["emotion"], "memo": pos["memo"], "exit_memo": memo,
        "setup": pos.get("setup"), "plan_basis": pos.get("plan_basis", ""), "plan_exit_rule": pos.get("plan_exit_rule", ""),
        "plan_target_basis": pos.get("plan_target_basis", ""),
        "exit_reason": reason, "exit_type": exit_type, "add_type": pos.get("add_type"), "nanpin_group": bool(pos.get("nanpin_group")),
        "horizon": pos.get("horizon", "day"), **{k: pos.get(k) for k in SWING_FIELDS},
        "reverse_fee": 0, "hold_high": None, "hold_low": None, "hold_range_source": None,
    }
    _derive(trade)
    acct["trades"].append(trade)
    pos["qty"] -= qty
    if pos["qty"] == 0:
        acct["positions"].remove(pos)
    return trade


def _derive(t: dict) -> None:
    """約定の損益・金利・R・保有日数・MFE/MAE・保険ストップの滑りなどを計算し直す。"""
    sign, qty, op = _sign(t["side"]), t["qty"], t["open_price"]
    od, cd = date.fromisoformat(t["open_date"]), date.fromisoformat(t["close_date"])
    t["gross_pnl"] = round((t["close_price"] - op) * qty * sign)
    t["carry_cost"], t["carry_days"] = carry_cost(t["margin_type"], t["side"], op, qty, od, cd)
    t["carry_total"] = t["carry_cost"] + int(t.get("reverse_fee") or 0)       # 金利・貸株料 ＋ 逆日歩
    t["net_pnl"] = t["gross_pnl"] - t["carry_total"] - t["commission"]
    t["holding_bdays"] = trading_days_between(od, cd)
    stop, target = t.get("stop"), t.get("target")
    per = abs(op - stop) if stop else None                                     # 1株あたりのリスク（1R）
    t["r_multiple"] = round(t["net_pnl"] / (per * qty), 2) if per else None
    t["planned_rr"] = round(abs(target - op) / per, 2) if per and target else None
    t["beyond_stop"] = ((t["close_price"] - stop) * sign < 0) if stop else None
    # MFE / MAE: 保有中の最高値・最安値から、有利・不利に最大どれだけ動いたか（R 単位）
    hi, lo = t.get("hold_high"), t.get("hold_low")
    best, worst = (hi, lo) if sign > 0 else (lo, hi)
    t["mfe_r"] = round((best - op) * sign / per, 2) if per and best is not None else None
    t["mae_r"] = round((worst - op) * sign / per, 2) if per and worst is not None else None
    # 保険ストップの滑り: 損切りの決済で、計画価格よりどれだけ不利に約定したか（マイナス = 不利）
    if stop and t.get("exit_type") in c.STOP_EXITS:
        slip = (t["close_price"] - stop) * sign
        t["stop_slip_yen"], t["stop_slip_r"] = round(slip * qty), round(slip / per, 2)
    else:
        t["stop_slip_yen"] = t["stop_slip_r"] = None
    # 決算またぎ: 決算日の大引け後の発表を、建玉を持ったまま越えたか
    ed = t.get("earnings_date")
    t["earnings_crossed"] = (od <= date.fromisoformat(ed) < cd) if ed else None


def trading_days_between(a: date, b: date) -> int:
    """a から b までの営業日数（両端を含む。同日なら 1）。"""
    n, d = 1, a
    while d < b:
        d = market.next_trading_day(d)
        n += 1
    return n


# ---------------------------------------------------------------- 後からの修正・追記
SWING_FIELDS = ("decision_date", "entry_method", "judge_stop", "next_wall_price", "next_wall_kind", "earnings_date")
POSITION_FIELDS = {"open_price", "opened_at", "stop", "target", "tags", "emotion", "memo",
                   "setup", "plan_basis", "plan_exit_rule", "plan_target_basis", "horizon", *SWING_FIELDS}
TRADE_FIELDS = POSITION_FIELDS | {"close_price", "closed_at", "exit_memo", "exit_type", "reverse_fee", "hold_high", "hold_low"}


def _jsonable(v):
    return v.isoformat() if isinstance(v, date) else v


def _iso(d: date | None) -> str | None:
    return d.isoformat() if d else None


def _check_levels(side: str, price: float, stop: float | None, target: float | None) -> None:
    sign = _sign(side)
    if stop is not None and (stop - price) * sign >= 0:
        raise TradeError("損切りラインは買いなら建値より下、売りなら建値より上に置いてください")
    if target is not None and (target - price) * sign <= 0:
        raise TradeError("利確目標は買いなら建値より上、売りなら建値より下に置いてください")


def _apply_edit(obj: dict, changes: dict, allowed: set, now: datetime) -> dict:
    """変更を反映し、変わった項目を edits に履歴として残す（修正したことが後から分かるように）。"""
    bad = set(changes) - allowed
    if bad:
        raise TradeError(f"変更できない項目です: {sorted(bad)}")
    changes = {k: _jsonable(v) for k, v in changes.items()}
    merged = {**obj, **changes}
    _check_levels(obj["side"], merged["open_price"], merged.get("stop"), merged.get("target"))
    if merged.get("horizon") == "swing" and obj["margin_type"] == "day":
        raise TradeError("いちにち信用はスイング（持ち越し）にできません")
    if merged.get("hold_high") is not None and merged.get("hold_low") is not None and merged["hold_high"] < merged["hold_low"]:
        raise TradeError("保有中の高値が安値より低くなっています")
    diff = {k: [obj.get(k), v] for k, v in changes.items() if obj.get(k) != v}
    if diff:
        obj.update(changes)
        obj.setdefault("edits", []).append({"at": now.isoformat(timespec="seconds"), "changes": diff})
    return diff


def _times(changes: dict, now: datetime) -> dict:
    """日時の変更を検証し、保存形式（JST の ISO 文字列）にそろえる。"""
    out = dict(changes)
    for k in ("opened_at", "closed_at"):
        if k in out:
            at = out[k].astimezone(JST)
            _check_time(at, now)
            out[k] = at.isoformat(timespec="seconds")
    return out


def _expiry_for(margin_type: str, open_date: date) -> date | None:
    """返済期限。いちにち信用は建日、制度信用は6ヶ月後の期日、一般信用（無期限）と現物は None。"""
    exp = c.MARGIN_TYPES[margin_type]["expiry"]
    if exp == "same_day":
        return open_date
    return expiry_date(open_date, exp) if exp else None


def edit_position(acct: dict, position_id: str, changes: dict, now: datetime) -> dict:
    pos = next((p for p in acct["positions"] if p["id"] == position_id), None)
    if pos is None:
        raise TradeError("建玉が見つかりません（すでに返済済みの可能性があります）", 404)
    if _apply_edit(pos, _times(changes, now), POSITION_FIELDS, now).get("opened_at"):
        d = datetime.fromisoformat(pos["opened_at"]).date()
        pos["open_date"], pos["expiry_date"] = d.isoformat(), _iso(_expiry_for(pos["margin_type"], d))
    return pos


def edit_trade(acct: dict, trade_id: str, changes: dict, now: datetime) -> dict:
    t = next((t for t in acct["trades"] if t["id"] == trade_id), None)
    if t is None:
        raise TradeError("約定が見つかりません", 404)
    changes = _times(changes, now)
    opened = datetime.fromisoformat(changes.get("opened_at", t["opened_at"]))
    closed = datetime.fromisoformat(changes.get("closed_at", t["closed_at"]))
    if closed < opened:
        raise TradeError("返済日時が建日時より前です")
    exp = _expiry_for(t["margin_type"], opened.date())
    if exp and closed.date() > exp:
        raise TradeError("返済日時が返済期限を過ぎています（いちにち信用は建てた日のうちに返済）")
    diff = _apply_edit(t, changes, TRADE_FIELDS, now)
    if diff:
        t["open_date"], t["close_date"] = opened.date().isoformat(), closed.date().isoformat()
        t["holding_minutes"] = int((closed - opened).total_seconds() // 60)
        if "closed_at" in diff and t["exit_reason"] != "manual":
            # 強制返済の時刻を直した = 実際は自分で返済した。強制返済の扱いを外す
            diff["exit_reason"] = [t["exit_reason"], "manual"]
            t["exit_reason"] = "manual"
        _derive(t)
    return t


def close_group(acct: dict, key: str, qty: int, price: float, at: datetime, now: datetime, memo: str = "",
                exit_type: str = "") -> list[dict]:
    """まとめて返済。古い建玉から順に qty 株を返済する（途中で失敗したら口座は保存しない前提）。"""
    group = _same_group(acct, key)
    total = sum(p["qty"] for p in group)
    if not group:
        raise TradeError("建玉が見つかりません（すでに返済済みの可能性があります）", 404)
    if qty > total:
        raise TradeError(f"返済株数が建玉合計 {total} 株を超えています")
    trades, left = [], qty
    for p in group:
        if left == 0:
            break
        n = min(left, p["qty"])
        trades.append(close_position(acct, p["id"], n, price, at, now, memo, exit_type=exit_type))
        left -= n
    return trades


def apply_forced(acct: dict, now: datetime, close_price: Callable[[str, date], float | None]) -> list[dict]:
    """いちにち信用は建日の大引け、制度信用は期日の大引けで、その日の終値で強制返済する。
    終値がまだ取れないものは残す（summary で overdue 表示）。
    期限を過ぎてから入力した建玉（TradingView のリプレイなど過去日の練習）は自動返済せず、返済の入力を待つ。"""
    done = []
    for pos in list(acct["positions"]):
        if not pos["expiry_date"]:
            continue
        due = date.fromisoformat(pos["expiry_date"])
        if now < at_close(due) or is_backdated(pos):
            continue
        px = close_price(pos["symbol"], due)
        if px is None:
            continue
        reason = "day_close" if pos["margin_type"] == "day" else "expiry"
        done.append(close_position(acct, pos["id"], pos["qty"], px, at_close(due), now,
                                   "大引けで強制返済", reason))
    return done


def is_backdated(pos: dict) -> bool:
    """返済期限（大引け）を過ぎてから入力した建玉か。期限のない区分は常に False。"""
    if not pos["expiry_date"]:
        return False
    return datetime.fromisoformat(pos["entered_at"]) >= at_close(date.fromisoformat(pos["expiry_date"]))


# ---------------------------------------------------------------- 口座サマリー
def summary(acct: dict, prices: dict[str, float | None], now: datetime) -> dict:
    today = now.astimezone(JST).date()
    rows, unreal_total, accrued_total, amount_total, need_total, stale = [], 0, 0, 0, 0, False
    for p in acct["positions"]:
        last = prices.get(p["symbol"])
        unreal = round((last - p["open_price"]) * p["qty"] * _sign(p["side"])) if last else None
        accrued, _ = carry_cost(p["margin_type"], p["side"], p["open_price"], p["qty"],
                                date.fromisoformat(p["open_date"]), max(today, date.fromisoformat(p["open_date"])))
        amount = p["open_price"] * p["qty"]
        stale |= last is None
        unreal_total += unreal or 0
        accrued_total += accrued
        need_total += amount * c.MARGIN_TYPES[p["margin_type"]]["margin_rate"]
        if p["margin_type"] != "cash":
            amount_total += amount
        ed = p.get("earnings_date")
        rows.append({**p, "last": last, "unrealized": unreal, "accrued_cost": accrued, "amount": round(amount),
                     "overdue": bool(p["expiry_date"]) and now >= at_close(date.fromisoformat(p["expiry_date"])),
                     "earnings_days": (date.fromisoformat(ed) - today).days if ed else None,
                     "backdated": is_backdated(p),
                     "label": c.MARGIN_TYPES[p["margin_type"]]["label"]})
    cash = cash_balance(acct)
    effective = cash + min(0, unreal_total) - accrued_total
    maintenance = effective / amount_total if amount_total else None
    free = effective - need_total
    today_trades = [t for t in acct["trades"] if t["close_date"] == today.isoformat()]
    return {
        "account_id": acct["id"], "initial_cash": acct["initial_cash"], "cash": cash,
        "realized_total": cash - acct["initial_cash"], "unrealized": unreal_total, "accrued_cost": accrued_total,
        "equity": cash + unreal_total - accrued_total, "effective_margin": round(effective),
        "position_amount": round(amount_total), "maintenance_rate": maintenance,
        "margin_call": maintenance is not None and maintenance < c.MAINTENANCE_RATE,
        "free_margin": round(free), "buying_power": max(0, round(free / c.MARGIN_RATE)) if effective >= c.MIN_MARGIN else 0,
        "cash_power": max(0, round(free)),
        "today_realized": sum(t["net_pnl"] for t in today_trades), "today_count": len(today_trades),
        "positions": rows, "groups": _groups(rows), "prices_stale": stale,
    }


def _groups(rows: list[dict]) -> list[dict]:
    """建玉の合計行（同じ銘柄・売買・区分）。建てた順に並べ、各建玉の行を members に持つ。"""
    out: dict[str, dict] = {}
    for r in sorted(rows, key=lambda r: (r["opened_at"], r["id"])):
        g = out.setdefault(group_key(r), {"key": group_key(r), "symbol": r["symbol"], "name": r["name"],
                                          "side": r["side"], "margin_type": r["margin_type"], "label": r["label"],
                                          "last": r["last"], "members": []})
        g["members"].append(r)
    for g in out.values():
        m = g["members"]
        g["qty"] = sum(r["qty"] for r in m)
        g["avg_price"] = round(avg_price(m), 2)
        g["unrealized"] = None if any(r["unrealized"] is None for r in m) else sum(r["unrealized"] for r in m)
        g["accrued_cost"] = sum(r["accrued_cost"] for r in m)
        g["nanpin"] = any(r.get("add_type") == "nanpin" for r in m)
    return list(out.values())


# ---------------------------------------------------------------- 成績
def _group(trades: list[dict]) -> dict:
    n = len(trades)
    wins = [t for t in trades if t["net_pnl"] > 0]
    total = sum(t["net_pnl"] for t in trades)
    rs = [t["r_multiple"] for t in trades if t.get("r_multiple") is not None]
    return {"n": n, "win_rate": len(wins) / n if n else None, "total": total, "avg": total / n if n else None,
            "avg_r": sum(rs) / len(rs) if rs else None}


def setup_label(t: dict) -> str:
    """型の表示名（買い・売りで名前が変わる）。3行メモ導入前の記録は「未設定」。"""
    names = c.SETUPS.get(t.get("setup") or "")
    return names[0 if t["side"] == "long" else 1] if names else "未設定"


def rr_rule_label(t: dict) -> str:
    rr = t.get("planned_rr")
    if rr is None:
        return "RR 未計算"
    return f"RR {c.RR_BASE} 以上（基準どおり）" if rr >= c.RR_BASE else f"RR {c.RR_BASE} 未満（基準違反）"


def exit_type_label(t: dict) -> str:
    if t["exit_reason"] != "manual":
        return "強制返済"
    return c.EXIT_TYPES.get(t.get("exit_type") or "", "未分類")


def _avg(xs: list) -> float | None:
    return sum(xs) / len(xs) if xs else None


def _swing_stats(ts: list[dict]) -> dict:
    """持ち越し・MFE/MAE・保険ストップの滑り・決算またぎの集計（デイトレの記録も対象。値がないものは除外）。"""
    mfe = [t["mfe_r"] for t in ts if t.get("mfe_r") is not None]
    mae = [t["mae_r"] for t in ts if t.get("mae_r") is not None]
    # 取り切り率 = 実際の R ÷ MFE（伸びた分のうち何割を取れたか）
    capture = [t["r_multiple"] / t["mfe_r"] for t in ts if (t.get("mfe_r") or 0) > 0 and t.get("r_multiple") is not None]
    slips = [t["stop_slip_r"] for t in ts if t.get("stop_slip_r") is not None]
    return {
        "avg_hold_bdays": _avg([t["holding_bdays"] for t in ts if t.get("holding_bdays")]),
        "carry_total": sum(t.get("carry_total", t.get("carry_cost", 0)) for t in ts),
        "avg_mfe_r": _avg(mfe), "avg_mae_r": _avg(mae), "mfe_count": len(mfe), "avg_capture": _avg(capture),
        "gap_stops": sum(1 for t in ts if t.get("exit_type") == "gap_stop"),
        "avg_stop_slip_r": _avg(slips), "stop_slip_count": len(slips),
        "earnings_crossed": sum(1 for t in ts if t.get("earnings_crossed")),
    }


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
        # ペイオフレシオ = 平均利益 ÷ |平均損失|（結果ベースのリスクリワード）。損益分岐勝率 = 1 ÷ (1 + ペイオフ)
        "payoff_ratio": (sum(wins) / len(wins)) / -(sum(losses) / len(losses))
                        if wins and losses and sum(losses) < 0 else None,
        "breakeven_win_rate": 1 / (1 + (sum(wins) / len(wins)) / -(sum(losses) / len(losses)))
                              if wins and losses and sum(losses) < 0 else None,
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
        "by_setup": by(setup_label),
        "by_horizon": by(lambda t: c.HORIZONS[t.get("horizon") or "day"]),
        "by_entry_method": by(lambda t: c.ENTRY_METHODS.get(t.get("entry_method") or "", "未設定（デイトレなど）")),
        "by_earnings": by(lambda t: {True: "決算をまたいだ", False: "またいでいない"}.get(t.get("earnings_crossed"), "決算日未入力")),
        **_swing_stats(ts),
        "by_rr_rule": by(rr_rule_label),
        "below_rr_base": sum(1 for t in ts if t.get("planned_rr") is not None and t["planned_rr"] < c.RR_BASE),
        "by_exit_type": by(exit_type_label, [*c.EXIT_TYPES.values(), "強制返済", "未分類"].index),
        "unclassified_exits": sum(1 for t in ts if exit_type_label(t) == "未分類"),
        "by_add_type": by(lambda t: ADD_LABELS[t.get("add_type")], list(ADD_LABELS.values()).index),
        "by_nanpin_group": by(lambda t: "ナンピンした建玉" if t.get("nanpin_group") else "ナンピンなし",
                              lambda k: k != "ナンピンなし"),
        "nanpin_count": sum(1 for t in ts if t.get("add_type") == "nanpin"),
        "trading_days": len({t["open_date"] for t in ts}),
    }


# ---------------------------------------------------------------- 出力（CSV・レビュー用）
def entry_limit(stop: float | None, target: float | None, rr: float = c.RR_BASE) -> float | None:
    """RR が rr ちょうどになるエントリー価格（買いならこれ以下、売りならこれ以上で入れば基準を満たす）。"""
    if stop is None or target is None:
        return None
    return round(stop + (target - stop) / (1 + rr), 1)


CSV_COLUMNS = [
    ("ID", lambda t: t["id"]), ("建日時", lambda t: t["opened_at"][:16].replace("T", " ")),
    ("返済日時", lambda t: t["closed_at"][:16].replace("T", " ")), ("銘柄コード", lambda t: t["symbol"]),
    ("銘柄名", lambda t: t["name"]), ("信用区分", lambda t: c.MARGIN_TYPES[t["margin_type"]]["label"]),
    ("売買", lambda t: "買い" if t["side"] == "long" else "売り"), ("株数", lambda t: t["qty"]),
    ("建値", lambda t: t["open_price"]), ("返済価格", lambda t: t["close_price"]),
    ("損益(金利等込)", lambda t: t["net_pnl"]), ("金利等", lambda t: t["carry_cost"]),
    ("R倍数", lambda t: t.get("r_multiple")), ("損切りライン", lambda t: t.get("stop")),
    ("利確目標", lambda t: t.get("target")), ("計画RR", lambda t: t.get("planned_rr")),
    ("時間軸", lambda t: c.HORIZONS[t.get("horizon") or "day"]),
    ("判断日", lambda t: t.get("decision_date") or ""),
    ("エントリー方法", lambda t: c.ENTRY_METHODS.get(t.get("entry_method") or "", "")),
    ("保有営業日数", lambda t: t.get("holding_bdays")),
    ("判断ストップ", lambda t: t.get("judge_stop")),
    ("次の壁", lambda t: t.get("next_wall_price")), ("次の壁の種類", lambda t: t.get("next_wall_kind") or ""),
    ("次回決算日", lambda t: t.get("earnings_date") or ""),
    ("決算またぎ", lambda t: {True: "あり", False: "なし"}.get(t.get("earnings_crossed"), "")),
    ("持ち越し費用(金利等+逆日歩)", lambda t: t.get("carry_total", t.get("carry_cost"))), ("逆日歩", lambda t: t.get("reverse_fee") or 0),
    ("MFE(R)", lambda t: t.get("mfe_r")), ("MAE(R)", lambda t: t.get("mae_r")),
    ("保険ストップの滑り(円)", lambda t: t.get("stop_slip_yen")), ("保険ストップの滑り(R)", lambda t: t.get("stop_slip_r")),
    ("型", setup_label), ("根拠", lambda t: t.get("plan_basis") or ""),
    ("無効化の条件", lambda t: t.get("plan_exit_rule") or ""), ("目標の根拠", lambda t: t.get("plan_target_basis") or ""),
    (f"上限価格(RR{c.RR_BASE})", lambda t: entry_limit(t.get("stop"), t.get("target"))),
    ("保有分", lambda t: t["holding_minutes"]), ("理由タグ", lambda t: "・".join(t.get("tags") or [])),
    ("感情", lambda t: t.get("emotion") or ""), ("決済理由", lambda t: exit_type_label(t)),
    ("損切りライン超え", lambda t: {True: "あり", False: "なし"}.get(t.get("beyond_stop"), "")),
    ("追加の種類", lambda t: ADD_LABELS[t.get("add_type")]), ("修正あり", lambda t: "あり" if t.get("edits") else ""),
    ("メモ", lambda t: t.get("memo") or ""), ("決済メモ", lambda t: t.get("exit_memo") or ""),
]


def trades_csv(trades: list[dict]) -> str:
    import csv
    import io
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([h for h, _ in CSV_COLUMNS])
    for t in sorted(trades, key=lambda t: t["closed_at"]):
        w.writerow(["" if (v := f(t)) is None else v for _, f in CSV_COLUMNS])
    return buf.getvalue()


# ---------------------------------------------------------------- ロードマップ
_OPS = {">=": lambda v, t: v >= t, ">": lambda v, t: v > t, "<=": lambda v, t: v <= t}


def roadmap(st: dict, initial_cash: int) -> list[dict]:
    """各フェーズと「次に進む条件」の達成状況。取引がまだない指標は未達扱い。"""
    n = st["n"]
    metrics = {
        "n": n, "trading_days": st["trading_days"], "stop_set_rate": st["stop_set_rate"],
        "avg_r": st["avg_r"], "profit_factor": st["profit_factor"],
        "beyond_stop_rate": st["beyond_stop"] / n if n else None,
        "nanpin_rate": st["nanpin_count"] / n if n else None,
        "max_dd_rate": st["max_drawdown"] / initial_cash if n else None,
    }
    out = []
    for ph in c.ROADMAP:
        conds = [{"label": label, "value": metrics[m], "fmt": fmt,
                  "ok": metrics[m] is not None and _OPS[op](metrics[m], th)}
                 for label, m, op, th, fmt in ph.get("next_conditions", [])]
        out.append({"title": ph["title"], "done": ph["done"], "items": ph["items"],
                    "next_label": ph.get("next_label", "次のフェーズに進む条件"), "conditions": conds,
                    "ready": bool(conds) and all(x["ok"] for x in conds)})
    return out
