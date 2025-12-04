FROM python:3.10-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY ./app ./app
COPY ./app/data/stocks.csv ./app/data/stocks.csv 

ENV ALPHAVANTAGE_API_KEY=your_api_key_here


CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]