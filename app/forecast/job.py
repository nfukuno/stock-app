"""採点ジョブ: python -m app.forecast.job [--date YYYY-MM-DD] [--dry-run] [--no-notify] [--rescore] [--notify-only]"""
from __future__ import annotations

import argparse
import json
from datetime import date, datetime

from . import config, market, results, scenarios, scoring
from .image import image_path, render
from .store import LocalStore

PENDING_NOTIFY = ".pending_notify.json"


def is_final(target: date, now: datetime) -> bool:
    """対象日の日足が確定している時刻か。"""
    if target < now.date():
        return True
    return target == now.date() and (now.hour, now.minute) >= (config.CANDLE_FINAL_HOUR, config.CANDLE_FINAL_MIN)


def score_prediction(p: dict, df, now: datetime) -> tuple[str, dict | None]:
    """戻り値 (outcome, 更新後 dict)。outcome: scored / void / wait。df は日足 DataFrame。"""
    target = date.fromisoformat(p["target_date"])
    if not is_final(target, now):
        return "wait", None
    if p.get("late"):      # 場中予想（9:00 以降に保存/編集）は採点しない
        return "void", {**p, "status": "void", "void_reason": "intraday_unscored",
                        "scored_at": now.isoformat(timespec="seconds")}
    hist = df[[d < target for d in df.index]]
    has_target = target in df.index
    later = any(d > target for d in df.index)
    if not has_target:
        reason = None
        if not market.is_trading_day(target):
            reason = "non_trading_day"
        elif later:
            reason = "no_data"
        if reason:
            return "void", {**p, "status": "void", "void_reason": reason, "scored_at": now.isoformat(timespec="seconds")}
        return "wait", None
    if len(hist) < 2:
        return "void", {**p, "status": "void", "void_reason": "insufficient_history",
                        "scored_at": now.isoformat(timespec="seconds")}
    row = df[[d == target for d in df.index]].iloc[-1]
    pc = float(hist["close"].iloc[-1])
    atr = scoring.safe_atr(market.atr_before(df, target), pc)
    actual = {k: round(float(row[k]), 2) for k in ("open", "high", "low", "close")}
    pb = hist.iloc[-1]
    prev_bar = {k: float(pb[k]) for k in ("open", "high", "low", "close")}
    pc1 = float(hist["close"].iloc[-2])
    sc = scoring.score_bars(p["pred"], actual, pc, atr)
    actual_scn = scenarios.classify(actual["open"], actual["high"], actual["low"], actual["close"], pc, atr)
    hit = None if p["scenario"] == "other" else p["scenario"] == actual_scn
    sc["scenario_hit"] = hit
    base = scoring.score_baselines(actual, pc, atr, prev_bar, pc1)
    out = {**p, "status": "scored", "actual": {**actual, "prev_close": round(pc, 2), "atr14": round(atr, 2)},
           "actual_scenario": actual_scn, "score": sc, "baselines": base,
           "skill": scoring.skill(sc["total"], base), "scored_at": now.isoformat(timespec="seconds"),
           "scoring_version": config.SCORING_VERSION}
    out.pop("void_reason", None)
    return "scored", out


def recent_skill_avg(preds: list[dict], n: int = 10) -> float | None:
    sk = [p for p in preds if p["status"] == "scored" and not p.get("late") and p.get("skill") is not None]
    sk.sort(key=lambda p: (p["target_date"], p["symbol"]))
    vals = [p["skill"] for p in sk[-n:]]
    return round(sum(vals) / len(vals), 1) if vals else None


def run(args, store=None, fetch=None, now=None) -> list[dict]:
    store = store or LocalStore()
    fetch = fetch or (lambda sym: market.fetch_daily(sym, 160, use_cache=False))
    now = now or market.now_jst()
    today = date.fromisoformat(args.date) if args.date else now.date()
    all_preds = store.list_all()
    targets = [p for p in all_preds
               if date.fromisoformat(p["target_date"]) <= today
               and (p["status"] == "pending" or (args.rescore and p["status"] in ("scored", "void")))]
    frames: dict = {}
    updated, newly_scored = {}, []
    for p in targets:
        sym = p["symbol"]
        if sym not in frames:
            try:
                frames[sym] = fetch(sym)
            except Exception as e:
                print(f"[skip] {sym}: 取得失敗 {e}")
                frames[sym] = None
        df = frames[sym]
        if df is None or df.empty:
            continue
        outcome, new = score_prediction(p, df, now)
        print(f"{p['id']}: {outcome}" + (f" total={new['score']['total']} skill={new['skill']}" if outcome == "scored" else ""))
        if new is None:
            continue
        updated[p["id"]] = new
        if outcome == "scored":
            newly_scored.append(new)
            if not args.dry_run:
                hist = frames[sym][[d < date.fromisoformat(p["target_date"]) for d in frames[sym].index]]
                render(new, hist, image_path(p["id"]))
    if args.dry_run:
        return newly_scored
    merged = []
    for p in all_preds:
        if p["id"] in updated:
            store.put(updated[p["id"]])
            merged.append(updated[p["id"]])
        else:
            merged.append(p)
    if updated or args.rescore:
        store.write_text("results.csv", results.build_csv(merged))
    if newly_scored and not args.rescore:
        pend = json.loads(store.read_text(PENDING_NOTIFY) or "[]")
        for p in newly_scored:
            if p["id"] not in pend:
                pend.append(p["id"])
        store.write_text(PENDING_NOTIFY, json.dumps(pend))
    return newly_scored


def notify_pending(store=None, sender=None) -> int:
    from . import notify

    store = store or LocalStore()
    ids = json.loads(store.read_text(PENDING_NOTIFY) or "[]")
    if not ids:
        print("通知対象なし")
        return 0
    all_preds = store.list_all()
    by_id = {p["id"]: p for p in all_preds}
    preds = [by_id[i] for i in ids if i in by_id and by_id[i]["status"] == "scored"]
    if preds:
        (sender or notify.send)(preds, recent_skill_avg(all_preds))
    store.write_text(PENDING_NOTIFY, "[]")
    return len(preds)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--date")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-notify", action="store_true")
    ap.add_argument("--rescore", action="store_true")
    ap.add_argument("--notify-only", action="store_true")
    args = ap.parse_args(argv)
    if args.notify_only:
        notify_pending()
        return
    scored = run(args)
    if args.dry_run:
        print(f"[dry-run] {len(scored)} 件を採点（ファイルは書いていません）")
        if scored:
            from . import notify
            print("--- LINE 文面 ---\n" + notify.build_message(scored, None))
    elif scored and not args.no_notify and not args.rescore:
        notify_pending()


if __name__ == "__main__":
    main()
