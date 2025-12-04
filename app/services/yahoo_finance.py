import yfinance as yf
import pandas as pd
import time
from functools import lru_cache

def safe_download(symbols, period, retries=3, delay=2):
    """
    yfinance.download() を安定化するためのリトライ付きラッパー
    """
    for i in range(retries):
        try:
            print(f"[INFO] Attempt {i+1} to download {period} data")
            data = yf.download(list(symbols), period=period, group_by="ticker", auto_adjust=True)
            if not data.empty:
                return data
            print("[WARN] Empty data returned, retrying...")
        except Exception as e:
            print(f"[ERROR] Download failed: {e}")
        time.sleep(delay)
    print("[ERROR] All retries failed, returning empty DataFrame")
    return pd.DataFrame()


@lru_cache(maxsize=1)
def get_bulk_history(symbols: tuple, period: str = "max"):
    """
    複数銘柄を一括で取得してキャッシュする
    """
    return safe_download(symbols, period)


import yfinance as yf
import pandas as pd

def get_drawdown_bulk(symbols):
    print("[INFO] Attempt 1 to download max data")
    max_data = yf.download(symbols, period="max", group_by="ticker", threads=True)
    print("[INFO] Attempt 1 to download 6mo data")
    data_6m = yf.download(symbols, period="6mo", group_by="ticker", threads=True)
    print("[INFO] Attempt 1 to download 3mo data")
    data_3m = yf.download(symbols, period="3mo", group_by="ticker", threads=True)

    results = {}

    for symbol in symbols:
        print(f"[DEBUG] Processing symbol: {symbol}")
        try:
            # インデックス記号付きは個別取得に切り替え
            if symbol.startswith("^"):
                ticker = yf.Ticker(symbol)
                hist_max = ticker.history(period="max")
                hist_6m = ticker.history(period="6mo")
                hist_3m = ticker.history(period="3mo")
            else:
                hist_max = max_data[symbol] if symbol in max_data else None
                hist_6m = data_6m[symbol] if symbol in data_6m else None
                hist_3m = data_3m[symbol] if symbol in data_3m else None

            # データが揃っていない場合は空データを返す
            if hist_max is None or hist_max.empty:
                print(f"[WARN] {symbol} max data missing")
                results[symbol] = empty_result()
                continue

            latest_price = hist_max["Close"].iloc[-1]

            def get_max_info(df):
                if df is None or df.empty:
                    return None, None
                max_price = df["Close"].max()
                max_date = df["Close"].idxmax().strftime("%Y-%m-%d")
                return max_price, max_date

            max_price_3m, max_date_3m = get_max_info(hist_3m)
            max_price_6m, max_date_6m = get_max_info(hist_6m)
            max_price_all, max_date_all = get_max_info(hist_max)

            def calc_drawdown(max_price):
                if max_price and latest_price:
                    return (latest_price - max_price) / max_price * 100
                return None

            results[symbol] = {
                "latest_price": latest_price,
                "drawdown_3m": calc_drawdown(max_price_3m),
                "drawdown_6m": calc_drawdown(max_price_6m),
                "drawdown_all": calc_drawdown(max_price_all),
                "max_price_3m": max_price_3m,
                "max_date_3m": max_date_3m,
                "max_price_6m": max_price_6m,
                "max_date_6m": max_date_6m,
                "max_price_all": max_price_all,
                "max_date_all": max_date_all,
            }

        except Exception as e:
            print(f"[ERROR] Failed to process {symbol}: {e}")
            results[symbol] = empty_result()

    return results

def empty_result():
    return {
        "latest_price": None,
        "drawdown_3m": None,
        "drawdown_6m": None,
        "drawdown_all": None,
        "max_price_3m": None,
        "max_date_3m": None,
        "max_price_6m": None,
        "max_date_6m": None,
        "max_price_all": None,
        "max_date_all": None,
    }
