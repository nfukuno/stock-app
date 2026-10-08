"""取引日カレンダー・日足取得・ATR。"""
from __future__ import annotations

import time
from datetime import date, datetime, timedelta, timezone

import jpholiday
import pandas as pd

from . import config

JST = timezone(timedelta(hours=9))
_cache: dict[str, tuple[float, pd.DataFrame]] = {}


def now_jst() -> datetime:
    return datetime.now(JST)


def is_trading_day(d: date) -> bool:
    if d.weekday() >= 5 or jpholiday.is_holiday(d):
        return False
    if (d.month == 12 and d.day == 31) or (d.month == 1 and d.day <= 3):
        return False
    return True


def next_trading_day(d: date) -> date:
    """d より後の最初の取引日。"""
    d = d + timedelta(days=1)
    while not is_trading_day(d):
        d += timedelta(days=1)
    return d


def prev_trading_day(d: date) -> date:
    d = d - timedelta(days=1)
    while not is_trading_day(d):
        d -= timedelta(days=1)
    return d


def target_date_for(now: datetime) -> date:
    """予想時点での「次の取引日」。15:30 前で当日が取引日なら当日。"""
    now = now.astimezone(JST)
    today = now.date()
    before_close = (now.hour, now.minute) < (config.MARKET_CLOSE_HOUR, config.MARKET_CLOSE_MIN)
    if is_trading_day(today) and before_close:
        return today
    return next_trading_day(today)


def lock_time(target: date) -> datetime:
    return datetime(target.year, target.month, target.day, config.LOCK_HOUR_JST, tzinfo=JST)


def normalize_symbol(raw: str) -> str:
    s = raw.strip().upper()
    if not s:
        return s
    return s if "." in s else f"{s}.T"


def fetch_daily(symbol: str, days: int = 120, use_cache: bool = True) -> pd.DataFrame:
    """日足(auto_adjust=False)。index は Asia/Tokyo の date、列は open/high/low/close/volume。"""
    key = f"{symbol}:{days}"
    hit = _cache.get(key)
    if use_cache and hit and time.time() - hit[0] < config.YF_CACHE_SECONDS:
        return hit[1].copy()
    import yfinance as yf

    # 営業日 days 本ぶんに余裕を持たせた暦日数
    raw = yf.Ticker(symbol).history(period=f"{int(days * 1.6) + 30}d", interval="1d", auto_adjust=False)
    df = _normalize(raw).tail(days)
    _cache[key] = (time.time(), df)
    return df.copy()


def _normalize(raw: pd.DataFrame) -> pd.DataFrame:
    if raw is None or raw.empty:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    df = raw.rename(columns=str.lower)[["open", "high", "low", "close", "volume"]].copy()
    idx = pd.DatetimeIndex(df.index)
    if idx.tz is not None:
        idx = idx.tz_convert("Asia/Tokyo")
    df.index = [d.date() for d in idx]
    df = df.dropna(subset=["open", "high", "low", "close"])
    df = df[~df.index.duplicated(keep="last")]
    return df.sort_index()


def true_range(df: pd.DataFrame) -> pd.Series:
    pc = df["close"].shift(1)
    tr = pd.concat([df["high"] - df["low"], (df["high"] - pc).abs(), (df["low"] - pc).abs()], axis=1).max(axis=1)
    tr.iloc[0] = df["high"].iloc[0] - df["low"].iloc[0]
    return tr


def atr_before(df: pd.DataFrame, target: date, period: int = config.ATR_PERIOD) -> float | None:
    """target より前の直近 period 本の TR 単純平均。足りなければ None。"""
    hist = df[[d < target for d in df.index]]
    if len(hist) < 2:
        return None
    tr = true_range(hist).tail(period)
    return float(tr.mean())


def snapshot_before(df: pd.DataFrame, target: date) -> dict | None:
    hist = df[[d < target for d in df.index]]
    if hist.empty:
        return None
    atr = atr_before(df, target)
    return {
        "prev_date": hist.index[-1].isoformat(),
        "prev_close": round(float(hist["close"].iloc[-1]), 2),
        "atr14": round(atr, 2) if atr is not None else None,
    }


_names: dict[str, str] = {}


def lookup_name(symbol: str) -> str | None:
    """yfinance から銘柄名を取得（英語名のことが多い）。失敗時は None。"""
    if symbol in _names:
        return _names[symbol] or None
    name = ""
    try:
        import yfinance as yf

        info = yf.Ticker(symbol).info
        name = (info.get("shortName") or info.get("longName") or "").strip()
    except Exception:
        pass
    _names[symbol] = name
    return name or None
