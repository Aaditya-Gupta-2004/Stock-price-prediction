from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import yfinance as yf
import pandas as pd
from statsmodels.tsa.arima.model import ARIMA
import joblib, os, math, requests
from sklearn.metrics import mean_squared_error
from datetime import datetime
from sqlalchemy import create_engine, Column, String, Float, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# ==========================================================
# CONFIGURATION
# ==========================================================
app = FastAPI(title="StockAI - Smart Predictor", version="2.4")

# Enable CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==========================================================
# DATABASE (SQLite)
# ==========================================================
DATABASE_URL = "sqlite:///./stocks.db"
Base = declarative_base()
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

os.makedirs("models", exist_ok=True)


class StockModel(Base):
    __tablename__ = "stock_models"
    symbol = Column(String, primary_key=True, index=True)
    ma_file = Column(String)
    arma_file = Column(String)
    arima_file = Column(String)
    rmse_ma = Column(Float)
    rmse_arma = Column(Float)
    rmse_arima = Column(Float)
    last_trained = Column(DateTime, default=datetime.utcnow)


Base.metadata.create_all(bind=engine)

# ==========================================================
# UTILITIES
# ==========================================================
def rmse(actual, predicted):
    return math.sqrt(mean_squared_error(actual, predicted))


def fetch_stock_data(symbol: str, period="6mo", interval="1d"):
    """Download stock data with auto-suffix detection (.NS for Indian stocks)."""
    df = yf.download(symbol, period=period, interval=interval)["Close"]

    # Auto-add .NS for Indian stocks if no data found
    if df.empty and not any(suffix in symbol for suffix in [".NS", ".BO", ".L", ".TO", ".AX"]):
        try:
            df = yf.download(symbol + ".NS", period=period, interval=interval)["Close"]
            if not df.empty:
                symbol = symbol + ".NS"
        except Exception:
            pass

    # Try other global exchange suffixes if still empty
    if df.empty:
        for suffix in [".BO", ".L", ".TO", ".AX"]:
            try:
                df = yf.download(symbol + suffix, period=period, interval=interval)["Close"]
                if not df.empty:
                    symbol = symbol + suffix
                    break
            except Exception:
                continue

    return df, symbol


def train_and_save_models(symbol: str):
    """Train MA, ARMA, and ARIMA models and save them locally"""
    df, resolved_symbol = fetch_stock_data(symbol)

    if df.empty:
        raise HTTPException(status_code=404, detail="Invalid or unsupported stock symbol")

    train = df[:-30]
    test = df[-30:]

    # Moving Average Model (MA)
    ma_model = ARIMA(train, order=(0, 0, 1)).fit()
    ma_pred = ma_model.forecast(steps=30)
    ma_rmse = rmse(test, ma_pred)
    ma_file = os.path.join("models", f"{resolved_symbol}_ma.pkl")
    joblib.dump(ma_model, ma_file)

    # ARMA Model
    arma_model = ARIMA(train, order=(2, 0, 1)).fit()
    arma_pred = arma_model.forecast(steps=30)
    arma_rmse = rmse(test, arma_pred)
    arma_file = os.path.join("models", f"{resolved_symbol}_arma.pkl")
    joblib.dump(arma_model, arma_file)

    # ARIMA Model
    arima_model = ARIMA(train, order=(2, 1, 1)).fit()
    arima_pred = arima_model.forecast(steps=30)
    arima_rmse = rmse(test, arima_pred)
    arima_file = os.path.join("models", f"{resolved_symbol}_arima.pkl")
    joblib.dump(arima_model, arima_file)

    # Save to DB
    db = SessionLocal()
    stock = StockModel(
        symbol=resolved_symbol,
        ma_file=ma_file,
        arma_file=arma_file,
        arima_file=arima_file,
        rmse_ma=ma_rmse,
        rmse_arma=arma_rmse,
        rmse_arima=arima_rmse,
        last_trained=datetime.utcnow(),
    )
    db.merge(stock)
    db.commit()
    db.close()

    return resolved_symbol, ma_pred.tolist(), arma_pred.tolist(), arima_pred.tolist(), ma_rmse, arma_rmse, arima_rmse


# ==========================================================
# ENDPOINTS
# ==========================================================
@app.get("/")
def root():
    return {
        "message": "📊 StockAI API running locally!",
        "endpoints": [
            "/predict/{symbol}",
            "/realtime/{symbol}",
            "/autocomplete/{query}",
        ],
    }


@app.get("/predict/{symbol}")
def predict(symbol: str):
    """Predict stock prices using MA, ARMA, and ARIMA models"""
    try:
        symbol = symbol.upper()
        db = SessionLocal()
        record = db.query(StockModel).filter(StockModel.symbol == symbol).first()
        db.close()

        if not record:
            resolved_symbol, ma, arma, arima, r1, r2, r3 = train_and_save_models(symbol)
        else:
            resolved_symbol = symbol
            ma_model = joblib.load(record.ma_file)
            arma_model = joblib.load(record.arma_file)
            arima_model = joblib.load(record.arima_file)
            ma = ma_model.forecast(steps=30).tolist()
            arma = arma_model.forecast(steps=30).tolist()
            arima = arima_model.forecast(steps=30).tolist()
            r1, r2, r3 = record.rmse_ma, record.rmse_arma, record.rmse_arima

        return {
            "symbol": resolved_symbol,
            "MA_Prediction": ma,
            "ARMA_Prediction": arma,
            "ARIMA_Prediction": arima,
            "RMSE": {"MA": r1, "ARMA": r2, "ARIMA": r3},
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/realtime/{symbol}")
def get_realtime_price(symbol: str):
    """Fetch latest available stock price using Yahoo Finance"""
    symbol = symbol.upper()
    try:
        ticker = yf.Ticker(symbol)
        data = ticker.history(period="1d", interval="1m")

        # Auto-add .NS for Indian stocks if empty
        if data.empty and not any(suffix in symbol for suffix in [".NS", ".BO", ".L", ".TO", ".AX"]):
            ticker = yf.Ticker(symbol + ".NS")
            data = ticker.history(period="1d", interval="1m")
            if not data.empty:
                symbol = symbol + ".NS"

        # Try other exchanges
        if data.empty:
            for suffix in [".BO", ".L", ".TO", ".AX"]:
                ticker = yf.Ticker(symbol + suffix)
                data = ticker.history(period="1d", interval="1m")
                if not data.empty:
                    symbol = symbol + suffix
                    break

        if data.empty:
            raise HTTPException(status_code=404, detail="Symbol not found or no recent data.")

        last_row = data.iloc[-1]
        return {
            "symbol": symbol,
            "source": "yfinance",
            "current": round(float(last_row["Close"]), 2),
            "high": round(float(last_row["High"]), 2),
            "low": round(float(last_row["Low"]), 2),
            "open": round(float(last_row["Open"]), 2),
            "timestamp": last_row.name.strftime("%Y-%m-%d %H:%M:%S"),
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Realtime fetch error: {str(e)}")


@app.get("/autocomplete/{query}")
def autocomplete(query: str):
    """Fetch stock search suggestions using Yahoo Finance (enhanced)"""
    try:
        url = f"https://query1.finance.yahoo.com/v1/finance/search?q={query}&quotesCount=50&newsCount=0"
        res = requests.get(url, timeout=8)

        if res.status_code != 200:
            raise HTTPException(status_code=500, detail="Yahoo API error")

        data = res.json()
        quotes = data.get("quotes", [])
        if not quotes:
            return []

        # Return simplified list to frontend
        return [
            {
                "symbol": q.get("symbol"),
                "name": q.get("shortname") or q.get("longname"),
                "exchange": q.get("exchange"),
            }
            for q in quotes
            if q.get("symbol") and (q.get("shortname") or q.get("longname"))
        ]

    except requests.Timeout:
        raise HTTPException(status_code=504, detail="Yahoo API request timed out")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Autocomplete fetch error: {str(e)}")
