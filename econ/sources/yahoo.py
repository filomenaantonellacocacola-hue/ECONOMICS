"""Precios, fundamentales y reportes de emisoras desde Yahoo Finance (via yfinance)."""
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
    "Dividends": "dividend",
    "Stock Splits": "split",
}
NUMERIC_PRICE_COLUMNS = ["open", "high", "low", "close", "adj_close", "dividend", "split"]

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
    # Perfil y moneda de los estados financieros
    "longName", "longBusinessSummary", "website", "fullTimeEmployees", "financialCurrency",
    # Analistas (vienen en el mismo info: no cuestan otra consulta)
    "currentPrice", "targetHighPrice", "targetLowPrice", "targetMedianPrice", "recommendationKey",
    # Mas detalle de dividendos, crecimiento, margenes y tenencia
    "dividendRate", "trailingAnnualDividendYield", "fiveYearAvgDividendYield",
    "earningsQuarterlyGrowth", "ebitdaMargins", "revenuePerShare", "totalCashPerShare",
    "heldPercentInsiders", "heldPercentInstitutions", "shortPercentOfFloat",
    "fiftyDayAverage", "twoHundredDayAverage",
]
TEXT_FIELDS = {"ticker", "shortName", "sector", "industry", "country", "currency", "exchange", "longName",
               "longBusinessSummary", "website", "financialCurrency", "recommendationKey"}
SUMMARY_CHARS = 600

# Estados financieros que se guardan completos (todas las partidas que publique Yahoo).
STATEMENTS = {"income": "get_income_stmt", "balance": "get_balance_sheet", "cashflow": "get_cash_flow"}
STATEMENT_FREQS = {"A": "yearly", "Q": "quarterly"}
RECOMMENDATION_COLUMNS = {"strongBuy": "strong_buy", "buy": "buy", "hold": "hold", "sell": "sell",
                          "strongSell": "strong_sell"}


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
    for col in NUMERIC_PRICE_COLUMNS:
        long[col] = pd.to_numeric(long[col], errors="coerce").astype("float64")
    # Sin evento corporativo ese dia: dividendo 0 y split 0 (0 = sin split).
    long[["dividend", "split"]] = long[["dividend", "split"]].fillna(0.0)
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
                    actions=True,
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


def download_fundamentals(symbols: dict[str, str], pause: float = 0.5) -> pd.DataFrame:
    """Descarga un corte de fundamentales (``Ticker.info``) por emisora.

    ``symbols`` mapea el ticker con el que se guarda -> el simbolo que se consulta en Yahoo.
    Para el SIC se consulta el ticker de origen (p.ej. ``AAPL`` para ``AAPL.MX``), porque
    en la replica ``.MX`` los multiplos mezclan precio en pesos con utilidades en dolares.
    """
    import yfinance as yf

    today = datetime.now(timezone.utc).date()
    rows = []
    for ticker, symbol in symbols.items():
        try:
            info = yf.Ticker(symbol).info or {}
        except Exception as exc:  # noqa: BLE001
            log.warning("Fundamentales de %s (%s) fallaron: %s", ticker, symbol, exc)
            continue
        row = {"date": pd.Timestamp(today), "ticker": ticker}
        row.update({field: info.get(field) for field in FUNDAMENTAL_FIELDS})
        rows.append(row)
        time.sleep(pause)
    return fundamentals_frame(rows)


def fundamentals_frame(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows, columns=["date", "ticker", *FUNDAMENTAL_FIELDS])
    for col in df.columns:
        if col == "date":
            df[col] = pd.to_datetime(df[col])
        elif col in TEXT_FIELDS:
            df[col] = df[col].astype("string")
        else:
            df[col] = pd.to_numeric(df[col], errors="coerce").astype("float64")
    df["longBusinessSummary"] = df["longBusinessSummary"].str.slice(0, SUMMARY_CHARS)
    return df


class RateLimited(RuntimeError):
    """Yahoo empezo a limitar consultas: conviene parar y seguir en la siguiente corrida."""


def _is_rate_limit(exc: Exception) -> bool:
    text = f"{type(exc).__name__} {exc}".lower()
    return "ratelimit" in text.replace(" ", "") or "too many requests" in text or "429" in text


def statement_rows(frame: pd.DataFrame | None, ticker: str, statement: str, freq: str) -> list[dict]:
    """Convierte un estado de yfinance (partidas x fechas de cierre) a filas largas."""
    if frame is None or getattr(frame, "empty", True):
        return []
    rows = []
    for period_end in frame.columns:
        for item, value in frame[period_end].items():
            if pd.notna(value):
                rows.append({"ticker": ticker, "statement": statement, "freq": freq,
                             "period_end": pd.Timestamp(period_end).tz_localize(None).normalize(),
                             "item": str(item), "value": float(value)})
    return rows


def earnings_rows(frame: pd.DataFrame | None, ticker: str) -> list[dict]:
    """Fechas de reporte con UPA estimada, reportada y sorpresa (%)."""
    if frame is None or getattr(frame, "empty", True):
        return []
    df = frame.copy()
    if "Event Type" in df.columns:
        df = df[df["Event Type"].astype(str).str.contains("Earnings", case=False, na=False)]
    cols = {c.lower().replace(" ", ""): c for c in df.columns}
    est, rep = cols.get("epsestimate"), cols.get("reportedeps")
    sur = cols.get("surprise(%)")
    rows = []
    for when, r in df.iterrows():
        ts = pd.Timestamp(when)
        ts = ts.tz_localize(None) if ts.tzinfo else ts  # fecha local del reporte
        rows.append({"ticker": ticker, "date": ts.normalize(),
                     "eps_estimate": pd.to_numeric(r.get(est), errors="coerce") if est else None,
                     "eps_reported": pd.to_numeric(r.get(rep), errors="coerce") if rep else None,
                     "surprise_pct": pd.to_numeric(r.get(sur), errors="coerce") if sur else None})
    return rows


def recommendation_row(frame: pd.DataFrame | None, ticker: str, when: pd.Timestamp) -> dict | None:
    """Conteo de recomendaciones del mes en curso (periodo '0m')."""
    if frame is None or getattr(frame, "empty", True):
        return None
    df = frame
    if "period" in df.columns and (df["period"] == "0m").any():
        df = df[df["period"] == "0m"]
    r = df.iloc[0]
    row = {"date": when, "ticker": ticker}
    row.update({new: pd.to_numeric(r.get(old), errors="coerce") for old, new in RECOMMENDATION_COLUMNS.items()})
    return row


def download_company(symbols: dict[str, str], pause: float = 0.4) -> dict[str, pd.DataFrame]:
    """Reportes de cada emisora: estados financieros (anual y trimestral), fechas de reporte
    y recomendaciones. Para el SIC ``symbols`` apunta al ticker de origen.

    Devuelve ``financials``, ``earnings``, ``recommendations`` y ``log`` (una fila por emisora).
    Si Yahoo empieza a limitar consultas, se detiene y devuelve lo obtenido.
    """
    import yfinance as yf

    today = pd.Timestamp(datetime.now(timezone.utc).date())
    fin, earn, recs, log_rows = [], [], [], []
    for ticker, symbol in symbols.items():
        t = yf.Ticker(symbol)
        errors: list[str] = []
        n_fin = n_earn = 0
        n_rec = 0
        try:
            for statement, method in STATEMENTS.items():
                for freq, yf_freq in STATEMENT_FREQS.items():
                    try:
                        rows = statement_rows(getattr(t, method)(freq=yf_freq), ticker, statement, freq)
                    except Exception as exc:  # noqa: BLE001
                        if _is_rate_limit(exc):
                            raise RateLimited(str(exc)) from exc
                        errors.append(f"{statement}/{freq}: {exc}")
                        continue
                    fin += rows
                    n_fin += len(rows)
                    time.sleep(pause)
            for label, call in (("earnings", lambda: earnings_rows(t.get_earnings_dates(limit=12), ticker)),
                                ("recommendations", lambda: recommendation_row(t.get_recommendations(), ticker, today))):
                try:
                    out = call()
                except Exception as exc:  # noqa: BLE001
                    if _is_rate_limit(exc):
                        raise RateLimited(str(exc)) from exc
                    errors.append(f"{label}: {exc}")
                    continue
                if label == "earnings":
                    earn += out
                    n_earn = len(out)
                elif out:
                    recs.append(out)
                    n_rec = 1
                time.sleep(pause)
        except RateLimited as exc:
            log.warning("Yahoo limito consultas en %s; se continua en la siguiente corrida: %s", ticker, exc)
            break
        status = "ok" if n_fin else ("error" if errors else "sin_datos")
        log_rows.append({"date": today, "ticker": ticker, "symbol": symbol, "status": status,
                         "financial_rows": n_fin, "earnings_rows": n_earn, "recommendations": n_rec,
                         "error": "; ".join(errors)[:300]})
    return {
        "financials": pd.DataFrame(fin, columns=["ticker", "statement", "freq", "period_end", "item", "value"]),
        "earnings": pd.DataFrame(earn, columns=["ticker", "date", "eps_estimate", "eps_reported", "surprise_pct"]),
        "recommendations": pd.DataFrame(recs, columns=["date", "ticker", *RECOMMENDATION_COLUMNS.values()]),
        "log": pd.DataFrame(log_rows, columns=["date", "ticker", "symbol", "status", "financial_rows",
                                               "earnings_rows", "recommendations", "error"]),
    }
