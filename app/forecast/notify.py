"""LINE 通知の文面生成と送信。"""
from __future__ import annotations

from datetime import date

from . import config
from .image import image_url

LINE_MAX_MESSAGES = 5
LINE_TEXT_MAX = 4900


def _yn(v) -> str:
    return "－" if v is None else ("○" if v else "✕")


def _fmt_date(s: str) -> str:
    d = date.fromisoformat(s)
    return f"{d.month}/{d.day}"


def build_message(preds: list[dict], recent_skill_avg: float | None) -> str:
    labels = config.SCENARIO_LABELS
    dates = sorted({p["target_date"] for p in preds})
    lines = [f"📊 {' / '.join(_fmt_date(d) for d in dates)} 日足予想の採点結果"]
    for p in sorted(preds, key=lambda x: (x["target_date"], x["symbol"])):
        sc = p["score"]
        skill = p.get("skill")
        skill_s = f"（横ばい比 {skill:+.1f}）" if skill is not None else ""
        lines.append(f"{p['symbol']} {p.get('name', '')}  {sc['total']:.1f}点{skill_s}")
        dir_ok = sc["direction"] >= 100
        hit = sc.get("scenario_hit")
        if hit is None:
            scn = f"シナリオ－({labels.get(p['scenario'], p['scenario'])})"
        elif hit:
            scn = f"シナリオ○({labels.get(p['scenario'], p['scenario'])})"
        else:
            scn = f"シナリオ✕(予想:{labels.get(p['scenario'], p['scenario'])} / 実際:{labels.get(p['actual_scenario'], p['actual_scenario'])})"
        lines.append(f"  方向{_yn(dir_ok)}  {scn}  自信{p.get('confidence', '-')}")
        if p.get("memo"):
            lines.append(f"  メモ: {p['memo']}")
    if recent_skill_avg is not None:
        lines.append(f"直近10件 平均スキル {recent_skill_avg:+.1f}")
    return "\n".join(lines)[:LINE_TEXT_MAX]


def send(preds: list[dict], recent_skill_avg: float | None) -> None:
    from app.line_notify.notify import send_line_messages

    text = build_message(preds, recent_skill_avg)
    urls = [image_url(p["id"]) for p in preds][: LINE_MAX_MESSAGES - 1]
    if len(preds) > len(urls):
        text += f"\n（画像は先頭{len(urls)}件のみ送信）"
    send_line_messages(text, urls)
