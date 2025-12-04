import csv
from datetime import datetime, timezone, timedelta
import yfinance as yf
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from app.services.yahoo_finance import get_drawdown_bulk

app = FastAPI(title="Stock Drawdown Checker")
templates = Jinja2Templates(directory="app/templates")

def load_stock_list():
    stocks = []
    with open("data/stocks.csv", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            stocks.append({
                "number": int(row["number"]),
                "name": row["name"],
                "symbol": row["symbol"]
            })
    return stocks

@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    stock_list = load_stock_list()
    symbols = [s["symbol"] for s in stock_list]

    # 毎回取得（キャッシュなし）
    bulk_data = get_drawdown_bulk(symbols)

    results = []
    jst_now = datetime.now(timezone(timedelta(hours=9))).replace(second=0, microsecond=0)
    jst_str = jst_now.strftime("%Y-%m-%d %H:%M")

    for stock in stock_list:
        data = bulk_data.get(stock["symbol"])
        if data:
            prev_close = None
            hist = yf.Ticker(stock["symbol"]).history(period="5d")
            if len(hist) >= 2:
                prev_close = hist["Close"].iloc[-2]

            prev_close_str = f"{prev_close:.2f}" if prev_close else ""
            change_str = ""
            if prev_close:
                change_val = (data["latest_price"] - prev_close) / prev_close * 100
                arrow = "↑" if change_val > 0 else ("↓" if change_val < 0 else "")
                change_str = f"{change_val:.2f}% {arrow}"

            evaluation = ""
            if data['drawdown_6m'] is not None and data['drawdown_3m'] is not None:
                if data['drawdown_6m'] <= -30 and data['drawdown_3m'] <= -20:
                    evaluation = "◎"
                elif data['drawdown_6m'] <= -30:
                    evaluation = "〇"
                elif data['drawdown_3m'] <= -20:
                    evaluation = "△"
                elif data['drawdown_6m'] <= -20:
                    evaluation = "□"

            max_val = max(v for v in [data['max_price_3m'], data['max_price_6m'], data['max_price_all']] if v is not None)
            highlight_3m = "blue" if data['max_price_3m'] == max_val else ""
            highlight_6m = "blue" if data['max_price_6m'] == max_val else ""
            highlight_all = "blue" if data['max_price_all'] == max_val else ""

            results.append({
                "number": stock["number"],
                "name": stock["name"],
                "symbol": stock["symbol"],
                "evaluation": evaluation,
                "latest_date": jst_str,
                "latest_price": f"{data['latest_price']:.2f}" if data['latest_price'] else "",
                "prev_close": prev_close_str,
                "change": change_str,
                "drawdown_3m": f"{data['drawdown_3m']:.2f}%" if data['drawdown_3m'] is not None else "",
                "drawdown_6m": f"{data['drawdown_6m']:.2f}%" if data['drawdown_6m'] is not None else "",
                "drawdown_all": f"{data['drawdown_all']:.2f}%" if data['drawdown_all'] is not None else "",
                "max_date_3m": data['max_date_3m'] or "",
                "max_price_3m": f"{data['max_price_3m']:.2f}" if data['max_price_3m'] else "",
                "highlight_3m": highlight_3m,
                "max_date_6m": data['max_date_6m'] or "",
                "max_price_6m": f"{data['max_price_6m']:.2f}" if data['max_price_6m'] else "",
                "highlight_6m": highlight_6m,
                "max_date_all": data['max_date_all'] or "",
                "max_price_all": f"{data['max_price_all']:.2f}" if data['max_price_all'] else "",
                "highlight_all": highlight_all,
            })
        else:
            results.append({
                "number": stock["number"],
                "name": stock["name"],
                "symbol": stock["symbol"],
                "evaluation": "",
                "latest_date": jst_str,
                "latest_price": "",
                "prev_close": "",
                "change": "",
                "drawdown_3m": "",
                "drawdown_6m": "",
                "drawdown_all": "",
                "max_date_3m": "",
                "max_price_3m": "",
                "highlight_3m": "",
                "max_date_6m": "",
                "max_price_6m": "",
                "highlight_6m": "",
                "max_date_all": "",
                "max_price_all": "",
                "highlight_all": "",
            })

    return templates.TemplateResponse("index.html", {"request": request, "results": results, "exec_time": jst_str})