"""日足予想機能の定数・パス・環境変数。採点式の重みや閾値はここだけで管理する。"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent          # app/
REPO_ROOT = BASE_DIR.parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"
SYMBOLS_CSV = BASE_DIR / "data" / "forecast_symbols.csv"
IMAGE_DIR = REPO_ROOT / "output" / "forecast"
PAGES_BASE_URL = "https://nfukuno.github.io/stock-app"

# ---- 環境変数 -------------------------------------------------------------
def storage_mode() -> str:
    return os.getenv("FORECAST_STORAGE", "local").lower()


def data_dir() -> Path:
    return Path(os.getenv("FORECAST_DATA_DIR", str(REPO_ROOT / "forecasts")))


def github_repo() -> str:
    return os.getenv("FORECAST_GITHUB_REPO", "nfukuno/stock-app")


def github_branch() -> str:
    return os.getenv("FORECAST_GITHUB_BRANCH", "main")


def github_token() -> str:
    return os.getenv("FORECAST_GITHUB_TOKEN", "")


# ---- 時刻 -----------------------------------------------------------------
LOCK_HOUR_JST = 9            # 対象日のこの時刻以降は既存予想を編集不可
MARKET_CLOSE_HOUR, MARKET_CLOSE_MIN = 15, 30   # 大引け
CANDLE_FINAL_HOUR, CANDLE_FINAL_MIN = 15, 45   # 日足が確定したとみなす時刻
YF_CACHE_SECONDS = 300

# ---- 採点 -----------------------------------------------------------------
SCORING_VERSION = 1
ATR_PERIOD = 14
WEIGHTS = {
    "direction": 0.25,
    "close": 0.20,
    "open": 0.10,
    "range_iou": 0.25,
    "body_iou": 0.15,
    "shadow": 0.05,
}
DIRECTION_THRESHOLD_ATR = 0.1      # |x - pc| がこの ATR 倍以下なら「方向なし」
MIN_BODY_ATR = 0.05                # 実体 IoU の最低実体幅（ATR 倍）
FLAT_HALF_RANGE_ATR = 0.5          # flat ベースラインの H/L = pc ± A * 0.5
FALLBACK_ATR_PCT = 0.01            # ATR<=0 のとき pc * 1%

# ---- シナリオ -------------------------------------------------------------
GAP_ATR = 0.3
ROUND_TRIP_RANGE_ATR = 1.0
ROUND_TRIP_BODY_RATIO = 0.25
RANGE_RANGE_ATR = 0.6
RANGE_CHANGE_ATR = 0.3
TREND_ATR = 0.3

# (key, 表示名, 自動判定ルールの説明)  ※判定は scenarios.classify が上から順に評価
SCENARIOS = [
    ("round_trip", "往って来い（長いヒゲ）", "値幅 ≥ 1.0ATR かつ 実体 ≤ 値幅の25%"),
    ("gap_up_trend", "GU→上昇継続", "始値が前日比 +0.3ATR 以上 かつ 陽線(C≥O)"),
    ("gap_up_fade", "GU→寄り天", "始値が前日比 +0.3ATR 以上 かつ 陰線(C<O)"),
    ("gap_down_rebound", "GD→切り返し", "始値が前日比 -0.3ATR 以下 かつ 陽線(C>O)"),
    ("gap_down_trend", "GD→下落継続", "始値が前日比 -0.3ATR 以下 かつ 陰線(C≤O)"),
    ("range", "もみ合い（小動き）", "値幅 < 0.6ATR かつ |終値-前日終値| < 0.3ATR"),
    ("up_trend", "じり上げ", "終値が前日比 +0.3ATR 以上"),
    ("down_trend", "じり下げ", "終値が前日比 -0.3ATR 以下"),
    ("other", "その他", "上記以外"),
]
SCENARIO_KEYS = [s[0] for s in SCENARIOS]
SCENARIO_LABELS = {k: label for k, label, _ in SCENARIOS}

MEMO_MAX = 500

RESULT_COLUMNS = [
    "id", "symbol", "name", "target_date", "weekday", "late", "status", "scenario",
    "actual_scenario", "scenario_hit", "confidence",
    "pred_open", "pred_high", "pred_low", "pred_close",
    "act_open", "act_high", "act_low", "act_close", "prev_close", "atr14",
    "total", "direction", "close_s", "open_s", "range_iou", "body_iou", "shadow",
    "flat_total", "prev_copy_total", "skill",
    "pred_change_atr", "act_change_atr", "pred_range_atr", "act_range_atr",
    "memo", "scored_at", "scoring_version",
]
