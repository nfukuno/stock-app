import requests, os

API_KEY = os.getenv("ALPHAVANTAGE_API_KEY")
BASE_URL = "https://www.alphavantage.co/query"

def get_drawdown(symbol: str):
    params = {
        "function": "TIME_SERIES_DAILY",
        "symbol": symbol,
        "apikey": API_KEY
    }
    resp = requests.get(BASE_URL, params=params)
    data = resp.json()
    ts = data.get("Time Series (Daily)", {})
    if not ts:
        raise ValueError("No data returned")

    # 最新日付と価格
    latest_date = sorted(ts.keys())[-1]
    latest_price = float(ts[latest_date]["4. close"])

    # 最高値とその日付
    max_date, max_price = max(ts.items(), key=lambda kv: float(kv[1]["4. close"]))
    max_price = float(max_price["4. close"])

    drawdown = (latest_price - max_price) / max_price * 100
    return latest_price, max_price, drawdown, max_date, latest_date