"""Precios y fundamentales desde Yahoo Finance (via yfinance)."""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

import pandas as pd

log = logging.getLogger(__name__)

PRICE_COLUMNS = {
    "Open": "open",
    "High": "high",
    "Low": "low",
    "Close": "close",
    "Adj Close": "adj_close",
    "Volume": "volume",
}

FUNDAMENTAL_FIELDS = [
    "shortName", "sector", "industry", "country", "currency", "exchange",
    "marketCap", "enterpriseValue", "sharesOutstanding", "floatShares",
    "trailingPE", "forwardPE", "pegRatio", "priceToBook", "priceToSalesTrailing12Months",
    "enterpriseToEbitda", "enterpriseToRevenue",
    "trailingEps", "forwardEps", "bookValue",
    "dividendYield", "payoutRatio", "beta",
    "returnOnEquity", "returnOnAssets", "profitMargins", "operatingMargins", "grossMargins",
    "revenueGrowth", "earningsGrowth",
    "totalRevenue", "ebitda", "freeCashflow", "operatingCashflow",
    "totalCash", "totalDebt", "debtToEquity", "currentRatio", "quickRatio",
    "fiftyTwoWeekHigh", "fiftyTwoWeekLow", "averageVolume",
    "targetMeanPrice", "recommendationMean", "numberOfAnalystOpinions",
]


def normalize_download(raw: pd.DataFrame, tickers: list[str]) -> pd.DataFrame:
    """Convierte la salida de ``yf.download`` a formato largo (date, ticker, ...)."""
    if raw is None or raw.empty:
        return pd.DataFrame(columns=["date", "ticker", *PRICE_COLUMNS.values()])

    if isinstance(raw.columns, pd.MultiIndex):
        # Identificar que nivel contiene los campos (Close, Open...) y cual el ticker.
        field_level = 0 if "Close" in raw.columns.get_level_values(0) else 1
        ticker_level = 1 - field_level
        frames = []
        for ticker in raw.columns.get_level_values(ticker_level).unique():
            sub = raw.xs(ticker, axis=1, level=ticker_level).copy()
            sub["ticker"] = ticker
            frames.append(sub)
        long = pd.concat(frames)
    else:
        long = raw.copy()
        long["ticker"] = tickers[0]

    long.index.name = "date"
    long = long.reset_index().rename(columns=PRICE_COLUMNS)
    for col in PRICE_COLUMNS.values():
        if col not in long.columns:
            long[col] = pd.NA
    long = long[["date", "ticker", *PRICE_COLUMNS.values()]]
    long = long.dropna(subset=["close"])
    long["date"] = pd.to_datetime(long["date"]).dt.tz_localize(None).dt.normalize()
    long["ticker"] = long["ticker"].astype(str)
    for col in ["open", "high", "low", "close", "adj_close"]:
        long[col] = pd.to_numeric(long[col], errors="coerce").astype("float64")
    long["volume"] = pd.to_numeric(long["volume"], errors="coerce").fillna(0).astype("int64")
    return long.reset_index(drop=True)


def download_prices(
    tickers: list[str],
    start: str,
    end: str | None = None,
    chunk_size: int = 50,
    retries: int = 3,
    pause: float = 2.0,
) -> pd.DataFrame:
    """Descarga precios diarios OHLCV en lotes, con reintentos por lote."""
    import yfinance as yf

    frames = []
    for i in range(0, len(tickers), chunk_size):
        batch = tickers[i : i + chunk_size]
        for attempt in range(1, retries + 1):
            try:
                raw = yf.download(
                    batch,
                    start=start,
                    end=end,
                    interval="1d",
                    group_by="ticker",
                    auto_adjust=False,
                    actions=False,
                    threads=True,
                    progress=False,
                )
                frames.append(normalize_download(raw, batch))
                break
            except Exception as exc:  # noqa: BLE001 - yfinance lanza de todo
                log.warning("Lote %s intento %s fallo: %s", i // chunk_size, attempt, exc)
                time.sleep(pause * 2**attempt)
        time.sleep(pause)
    if not frames:
        return normalize_download(pd.DataFrame(), tickers)
    return pd.concat(frames, ignore_index=True)


def download_fundamentals(tickers: list[str], pause: float = 0.5) -> pd.DataFrame:
    """Descarga un corte de fundamentales (``Ticker.info``) por emisora."""
    import yfinance as yf

    today = datetime.now(timezone.utc).date()
    rows = []
    for ticker in tickers:
        try:
            info = yf.Ticker(ticker).info or {}
        except Exception as exc:  # noqa: BLE001
            log.warning("Fundamentales de %s fallaron: %s", ticker, exc)
            continue
        row = {"date": pd.Timestamp(today), "ticker": ticker}
        row.update({field: info.get(field) for field in FUNDAMENTAL_FIELDS})
        rows.append(row)
        time.sleep(pause)
    return fundamentals_frame(rows)


def fundamentals_frame(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows, columns=["date", "ticker", *FUNDAMENTAL_FIELDS])
    text_cols = {"ticker", "shortName", "sector", "industry", "country", "currency", "exchange"}
    for col in df.columns:
        if col == "date":
            df[col] = pd.to_datetime(df[col])
        elif col in text_cols:
            df[col] = df[col].astype("string")
        else:
            df[col] = pd.to_numeric(df[col], errors="coerce").astype("float64")
    return df
