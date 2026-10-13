"""Todo lo necesario de cada emisora: riesgo, fundamentales, estados financieros y screener.

Los calculos alimentan ``data/snapshots/equity_snapshot.csv`` (una fila por accion, FIBRA o ETF
de la BMV y el SIC) y el CLI de los analistas financieros::

    python -m econ.equity ficha WALMEX            # todo sobre una emisora
    python -m econ.equity estados AAPL --freq Q   # estados financieros (partidas clave + TTM)
    python -m econ.equity screen --market BMV --where "pe < 12 and roe_pct > 15" --sort score_value
    python -m econ.equity compare WALMEX SORIANAB CHDRAUIB
    python -m econ.equity peers GFNORTEO
    python -m econ.equity dividendos KOFUBL
    python -m econ.equity periodo WALMEX AMXB --period 2026-03   # rendimiento vs benchmark
    python -m econ.equity buscar banco
    python -m econ.equity columnas                # diccionario de columnas y unidades

Convenciones (todo ya normalizado, sin las trampas de escala de Yahoo):

- Porcentajes en % (``roe_pct = 18.5`` es 18.5 %); multiplos en veces (``debt_to_equity = 0.35``).
- Precios y rendimientos en pesos (las replicas del SIC cotizan en MXN). Los multiplos y estados
  del SIC vienen del ticker de origen (p.ej. ``AAPL``), en su moneda (``fin_currency``).
- Benchmark: BMV -> IPC (``^MXX``); SIC -> ``SPY.MX`` (S&P 500 en pesos, mismo horario que las replicas).
- Las metricas usan precios ajustados y corrigen splits que Yahoo no registro en las replicas .MX
  (``clean_prices``); ``data_flags`` avisa de splits corregidos, saltos raros y baja operatividad.
- Tasa libre de riesgo: CETES 28 dias promedio del ultimo anio (``rf_pct``).
"""
from __future__ import annotations

import argparse
import json
import sys
import unicodedata
from datetime import datetime, timezone
from functools import cached_property
from pathlib import Path

import numpy as np
import pandas as pd

from econ import config, storage

EQUITY_MARKETS = ("BMV", "SIC")
BENCHMARKS = {"BMV": "^MXX", "SIC": "SPY.MX"}
SIC_FALLBACK = "^GSPC"  # x MXN=X si no hay SPY.MX
FX_TICKER = "MXN=X"
RF_SERIES = ("BANXICO", "SF43936")  # CETES 28 dias
TRADING_DAYS = 252
MIN_OBS = 60  # observaciones diarias minimas para volatilidad y razones de riesgo
MIN_WEEKS = 52  # semanas minimas para beta y correlacion
JUMP = 0.4  # salto diario (40 %) que se revisa como posible split no ajustado
SPLIT_RATIOS = (2, 3, 4, 5, 6, 8, 10, 15, 20, 25, 50, 100)
SPLIT_TOL = 0.04
BREAK = 3.0  # un salto sostenido de 3x o mas que no es split se toma como error de escala

# Partidas clave por estado (etiqueta -> claves de Yahoo en orden de preferencia).
KEY_ITEMS = {
    "income": [
        ("Ingresos", ["TotalRevenue", "OperatingRevenue"]),
        ("Utilidad bruta", ["GrossProfit"]),
        ("Margen financiero (bancos)", ["NetInterestIncome"]),
        ("Utilidad de operacion", ["OperatingIncome"]),
        ("EBITDA", ["EBITDA", "NormalizedEBITDA"]),
        ("Utilidad antes de impuestos", ["PretaxIncome"]),
        ("Utilidad neta mayoritaria", ["NetIncomeCommonStockholders", "NetIncome"]),
        ("UPA diluida", ["DilutedEPS", "BasicEPS"]),
        ("Acciones promedio diluidas", ["DilutedAverageShares", "BasicAverageShares"]),
    ],
    "balance": [
        ("Activo total", ["TotalAssets"]),
        ("Efectivo e inversiones CP", ["CashCashEquivalentsAndShortTermInvestments", "CashAndCashEquivalents"]),
        ("Deuda total", ["TotalDebt"]),
        ("Deuda neta", ["NetDebt"]),
        ("Pasivo total", ["TotalLiabilitiesNetMinorityInterest"]),
        ("Capital contable mayoritario", ["StockholdersEquity", "CommonStockEquity"]),
        ("Capital de trabajo", ["WorkingCapital"]),
        ("Acciones en circulacion", ["OrdinarySharesNumber", "ShareIssued"]),
    ],
    "cashflow": [
        ("Flujo de operacion", ["OperatingCashFlow"]),
        ("Capex", ["CapitalExpenditure"]),
        ("Flujo libre", ["FreeCashFlow"]),
        ("Dividendos pagados", ["CashDividendsPaid", "CommonStockDividendPaid"]),
        ("Recompra de acciones", ["RepurchaseOfCapitalStock"]),
    ],
}
STATEMENT_NAMES = {"income": "Estado de resultados", "balance": "Balance", "cashflow": "Flujo de efectivo"}
PER_SHARE_ITEMS = {"DilutedEPS", "BasicEPS"}
SHARE_ITEMS = {"DilutedAverageShares", "BasicAverageShares", "OrdinarySharesNumber", "ShareIssued"}

# Puntajes relativos (0-100, percentil dentro de su mercado; mas alto = mejor).
SCORES = {
    "score_value": {"earnings_yield_pct": 1, "pb": -1, "ev_ebitda": -1, "div_yield_pct": 1, "fcf_yield_pct": 1},
    "score_quality": {"roe_pct": 1, "op_margin_pct": 1, "net_margin_pct": 1, "debt_to_equity": -1},
    "score_momentum": {"mom_12_1": 1, "chg_6m": 1, "rs_3m": 1, "vs_sma200": 1},
    "score_risk": {"vol_1y": -1, "max_dd_1y": 1, "beta_2y": -1, "var95_1d": 1},
}

# Diccionario de columnas de equity_snapshot.csv: columna -> (unidad, descripcion).
COLUMNS = {
    "ticker": ("", "Clave en el repo (.MX = cotiza en pesos en la BMV)"),
    "market": ("", "BMV o SIC"),
    "asset_type": ("", "stock, fibra o etf"),
    "name": ("", "Nombre de la emisora"),
    "sector": ("", "Sector (Yahoo)"),
    "industry": ("", "Industria (Yahoo)"),
    "date": ("fecha", "Ultimo precio disponible"),
    "close": ("MXN", "Precio de cierre"),
    "chg_1d": ("%", "Rendimiento 1 dia"),
    "chg_1m": ("%", "Rendimiento 1 mes (21 sesiones)"),
    "chg_3m": ("%", "Rendimiento 3 meses"),
    "chg_6m": ("%", "Rendimiento 6 meses"),
    "chg_ytd": ("%", "Rendimiento en el anio"),
    "chg_1y": ("%", "Rendimiento 12 meses"),
    "pct_from_52w_high": ("%", "Distancia al maximo de 52 semanas"),
    "vs_sma200": ("%", "Distancia a la media movil de 200 dias"),
    "rsi14": ("0-100", "RSI de 14 dias (>70 sobrecompra, <30 sobreventa)"),
    "mom_12_1": ("%", "Momentum: rendimiento de hace 12 meses a hace 1 mes"),
    "vol_1y": ("% anual", "Volatilidad anualizada de 1 anio"),
    "downside_vol_1y": ("% anual", "Volatilidad a la baja (bajo la tasa libre de riesgo)"),
    "max_dd_1y": ("%", "Maxima caida desde un pico en 1 anio (negativo)"),
    "max_dd_3y": ("%", "Maxima caida desde un pico en 3 anios o desde que hay datos (negativo)"),
    "beta_2y": ("x", "Beta semanal de 2 anios contra su benchmark (BMV: IPC; SIC: SPY.MX)"),
    "corr_2y": ("-1 a 1", "Correlacion semanal de 2 anios con su benchmark"),
    "rs_3m": ("pp", "Fuerza relativa: rendimiento 3m menos el del benchmark"),
    "rs_1y": ("pp", "Fuerza relativa: rendimiento 12m menos el del benchmark"),
    "sharpe_1y": ("x", "Sharpe de 1 anio ((rendimiento - rf) / volatilidad)"),
    "sortino_1y": ("x", "Sortino de 1 anio ((rendimiento - rf) / volatilidad a la baja)"),
    "var95_1d": ("%", "VaR historico 95 % a 1 dia (negativo: peor 5 % de los dias)"),
    "cvar95_1d": ("%", "CVaR 95 % a 1 dia (promedio del peor 5 % de los dias)"),
    "skew_1y": ("", "Sesgo de rendimientos diarios (negativo = caidas mas violentas)"),
    "kurt_1y": ("", "Curtosis en exceso (colas gordas si > 0)"),
    "up_days_pct_1y": ("%", "Porcentaje de dias al alza en 1 anio"),
    "obs_1y": ("dias", "Rendimientos diarios usados en las metricas de 1 anio"),
    "avg_value_20d_mxn_mm": ("millones MXN", "Importe operado promedio de 20 sesiones"),
    "traded_days_pct_3m": ("%", "Sesiones de la BMV con operacion en 3 meses (bajo = poco liquida)"),
    "div_12m": ("MXN", "Dividendos por accion pagados en 12 meses (serie de precios)"),
    "div_yield_12m_pct": ("%", "Dividendos de 12 meses entre el precio"),
    "rf_pct": ("%", "Tasa libre de riesgo usada (CETES 28 dias promedio de 1 anio)"),
    "data_flags": ("", "Alertas de datos: splits corregidos, saltos raros, poco operada, historia corta"),
    "mkt_cap_mxn_bn": ("miles de millones MXN", "Valor de mercado"),
    "pe": ("x", "P/U de 12 meses"),
    "fwd_pe": ("x", "P/U estimado"),
    "peg": ("x", "P/U entre crecimiento esperado"),
    "pb": ("x", "Precio / valor en libros"),
    "ps": ("x", "Precio / ventas"),
    "ev_ebitda": ("x", "Valor empresa / EBITDA"),
    "ev_sales": ("x", "Valor empresa / ventas"),
    "earnings_yield_pct": ("%", "Rendimiento de utilidades (1 / P/U)"),
    "fcf_yield_pct": ("%", "Flujo libre / valor de mercado (solo si coinciden las monedas)"),
    "div_yield_pct": ("%", "Rendimiento por dividendo (Yahoo)"),
    "payout_pct": ("%", "Utilidad que se paga como dividendo"),
    "roe_pct": ("%", "Rentabilidad sobre capital"),
    "roa_pct": ("%", "Rentabilidad sobre activos"),
    "gross_margin_pct": ("%", "Margen bruto"),
    "op_margin_pct": ("%", "Margen de operacion"),
    "ebitda_margin_pct": ("%", "Margen EBITDA"),
    "net_margin_pct": ("%", "Margen neto"),
    "rev_growth_pct": ("%", "Crecimiento de ingresos (ultimo trimestre vs anio anterior)"),
    "eps_growth_pct": ("%", "Crecimiento de utilidades (ultimo trimestre vs anio anterior)"),
    "debt_to_equity": ("x", "Deuda / capital"),
    "net_debt_ebitda": ("x", "Deuda neta / EBITDA (negativo = caja neta)"),
    "current_ratio": ("x", "Activo circulante / pasivo circulante"),
    "target_mean": ("moneda de cotizacion de origen", "Precio objetivo promedio de analistas"),
    "target_upside_pct": ("%", "Potencial al precio objetivo promedio"),
    "rec_mean": ("1-5", "Recomendacion promedio (1 = compra fuerte, 5 = venta)"),
    "rec_key": ("", "Recomendacion de consenso (Yahoo)"),
    "n_analysts": ("", "Analistas con precio objetivo"),
    "rec_buy_pct": ("%", "Analistas con compra o compra fuerte este mes"),
    "rec_sell_pct": ("%", "Analistas con venta o venta fuerte este mes"),
    "insiders_pct": ("%", "Tenencia de internos"),
    "institutions_pct": ("%", "Tenencia institucional"),
    "next_earnings": ("fecha", "Proximo reporte trimestral"),
    "last_earnings": ("fecha", "Ultimo reporte con UPA publicada"),
    "last_surprise_pct": ("%", "Sorpresa de UPA del ultimo reporte"),
    "beats_4q": ("0-4", "Reportes que superaron el estimado en los ultimos 4"),
    "last_quarter": ("fecha", "Cierre del ultimo trimestre con estados financieros"),
    "score_value": ("0-100", "Puntaje de valor (percentil en su mercado)"),
    "score_quality": ("0-100", "Puntaje de calidad (percentil en su mercado)"),
    "score_momentum": ("0-100", "Puntaje de momentum (percentil en su mercado)"),
    "score_risk": ("0-100", "Puntaje de riesgo: alto = menos riesgosa (percentil en su mercado)"),
    "quote_currency": ("", "Moneda de cotizacion del ticker con el que se piden los fundamentales"),
    "fin_currency": ("", "Moneda de los estados financieros"),
    "fund_date": ("fecha", "Fecha del corte de fundamentales"),
}

DEFAULT_SCREEN_COLS = ["ticker", "name", "close", "chg_ytd", "chg_1y", "pe", "ev_ebitda", "div_yield_pct",
                       "roe_pct", "target_upside_pct", "score_value", "score_quality", "score_momentum", "score_risk"]
COMPARE_COLS = ["market", "sector", "close", "chg_1m", "chg_ytd", "chg_1y", "vol_1y", "max_dd_1y", "beta_2y",
                "sharpe_1y", "mkt_cap_mxn_bn", "pe", "fwd_pe", "pb", "ev_ebitda", "div_yield_pct", "roe_pct",
                "net_margin_pct", "rev_growth_pct", "debt_to_equity", "net_debt_ebitda", "target_upside_pct",
                "rec_mean", "next_earnings", "score_value", "score_quality", "score_momentum", "score_risk"]


# ----------------------------------------------------------------------------- calculos

def _num(df: pd.DataFrame, col: str) -> pd.Series:
    if col in df.columns:
        return pd.to_numeric(df[col], errors="coerce").astype("float64")
    return pd.Series(np.nan, index=df.index, dtype="float64")


def _text(df: pd.DataFrame, col: str) -> pd.Series:
    if col in df.columns:
        return df[col].astype("string")
    return pd.Series(pd.NA, index=df.index, dtype="string")


def _ret(px: pd.Series, end: pd.Timestamp, start: pd.Timestamp) -> float:
    """Rendimiento % entre el ultimo precio a ``start`` y el ultimo a ``end`` (inclusive)."""
    a, b = px[px.index <= start], px[px.index <= end]
    if a.empty or b.empty:
        return np.nan
    return 100 * (b.iloc[-1] / a.iloc[-1] - 1)


def _max_drawdown(px: pd.Series) -> float:
    if len(px) < 2:
        return np.nan
    return 100 * float((px / px.cummax() - 1).min())


def rf_rate(macro: pd.DataFrame) -> float:
    """CETES 28 dias promedio del ultimo anio, en % (0 si no hay datos)."""
    if macro.empty:
        return 0.0
    s = macro[(macro["source"] == RF_SERIES[0]) & (macro["series_id"] == RF_SERIES[1])]
    if s.empty:
        return 0.0
    dates = pd.to_datetime(s["date"])
    recent = s.loc[dates >= dates.max() - pd.DateOffset(years=1), "value"]
    return float(recent.mean())


def clean_prices(px: pd.Series) -> tuple[pd.Series, list[str]]:
    """Corrige splits que Yahoo no ajusto (frecuente en las replicas .MX) y reporta saltos raros.

    Un salto diario de mas de ``JUMP`` se toma como split si el cociente esta a menos de
    ``SPLIT_TOL`` de un split comun (2:1, 3:1, 1:10...) y el nuevo nivel se sostiene los dias
    siguientes; entonces se reescalan los precios anteriores. Un salto sostenido de ``BREAK``
    veces o mas que no parece split se trata como error de escala y se descarta la historia
    previa. Cualquier otro salto solo se reporta.
    """
    px = px.dropna()
    if len(px) < 2:
        return px, []
    ratio = px / px.shift(1)
    adj = px.copy()
    notes = []
    for when in ratio.index[(ratio - 1).abs() > JUMP]:
        r = float(ratio[when])
        n = r if r > 1 else 1 / r
        k = min(SPLIT_RATIOS, key=lambda s: abs(n / s - 1))
        after = px[px.index >= when].iloc[:5]
        holds = (after / px[when] - 1).abs().max() < 0.15
        if abs(n / k - 1) < SPLIT_TOL and holds:
            adj[adj.index < when] *= (k if r > 1 else 1 / k)
            label = f"1:{k}" if r > 1 else f"{k}:1"
            notes.append(f"split {label} no ajustado el {when:%Y-%m-%d} (corregido)")
        elif n >= BREAK and holds:
            # Cambio de escala que no es un split comun: la historia previa no es comparable.
            adj = adj[adj.index >= when]
            notes.append(f"cambio de escala de {100 * (r - 1):+.0f}% el {when:%Y-%m-%d} (solo se usa la historia posterior)")
        else:
            notes.append(f"salto de {100 * (r - 1):+.0f}% el {when:%Y-%m-%d} (revisar)")
    return adj, notes


def price_series(prices: pd.DataFrame) -> dict[str, tuple[pd.DataFrame, list[str]]]:
    """Por ticker: precios ordenados por fecha con ``px`` (ajustado y sin splits pendientes) y alertas."""
    p = prices.copy()
    p["date"] = pd.to_datetime(p["date"])
    p["px"] = p["adj_close"].fillna(p["close"])
    p = p.sort_values(["ticker", "date"]).dropna(subset=["px"])
    out = {}
    for t, g in p.groupby("ticker", sort=False):
        g = g.set_index("date")
        # Solo los tickers .MX: indices, FX y VIX pueden moverse mas de 40 % sin ser un split.
        px, notes = clean_prices(g["px"]) if t.endswith(".MX") else (g["px"], [])
        out[t] = (g.assign(px=px), notes)
    return out


def _benchmarks(groups: dict[str, pd.DataFrame]) -> dict[str, pd.Series]:
    """BMV: IPC. SIC: SPY.MX (S&P 500 en pesos operado en la BMV, mismo horario que las replicas);
    si no hay datos, S&P 500 por tipo de cambio."""
    out = {}
    if BENCHMARKS["BMV"] in groups:
        out["BMV"] = groups[BENCHMARKS["BMV"]]["px"]
    if BENCHMARKS["SIC"] in groups:
        out["SIC"] = groups[BENCHMARKS["SIC"]]["px"]
    elif SIC_FALLBACK in groups and FX_TICKER in groups:
        spx = groups[SIC_FALLBACK]["px"]
        fx = groups[FX_TICKER]["px"]
        fx = fx.reindex(spx.index.union(fx.index)).ffill().reindex(spx.index)
        out["SIC"] = (spx * fx).dropna()
    return out


def _weekly_returns(px: pd.Series, since: pd.Timestamp) -> pd.Series:
    return px[px.index >= since].resample("W-FRI").last().pct_change(fill_method=None).dropna()


def _risk_row(g: pd.DataFrame, bench: pd.Series | None, rf_pct: float, calendar: pd.Index | None) -> dict:
    px = g["px"]
    last = px.index[-1]
    y1_start = last - pd.DateOffset(years=1)
    base = px[px.index <= y1_start]
    window = px[px.index >= base.index[-1]] if len(base) else px
    r = window.pct_change().dropna()
    row: dict = {"obs_1y": len(r)}
    ret_1y = _ret(px, last, y1_start)
    row["mom_12_1"] = _ret(px, last - pd.DateOffset(months=1), y1_start)
    enough = len(r) >= MIN_OBS
    vol = r.std() * np.sqrt(TRADING_DAYS) * 100 if enough else np.nan
    rf_d = rf_pct / 100 / TRADING_DAYS
    downside = np.sqrt((np.minimum(r - rf_d, 0) ** 2).mean()) * np.sqrt(TRADING_DAYS) * 100 if enough else np.nan
    row["vol_1y"] = vol
    row["downside_vol_1y"] = downside
    row["max_dd_1y"] = _max_drawdown(window)
    row["max_dd_3y"] = _max_drawdown(px[px.index >= last - pd.DateOffset(years=3)])
    row["beta_2y"] = row["corr_2y"] = row["rs_3m"] = row["rs_1y"] = np.nan
    if bench is not None and len(bench):
        # Beta semanal de 2 anios: los cierres diarios de las replicas no son simultaneos con los de su
        # mercado de origen y la beta diaria sale sesgada a cero.
        since = last - pd.DateOffset(years=2)
        joint = pd.concat([_weekly_returns(px, since).rename("a"), _weekly_returns(bench, since).rename("b")],
                          axis=1, join="inner").dropna()
        if len(joint) >= MIN_WEEKS and joint["b"].var() > 0:
            row["beta_2y"] = joint["a"].cov(joint["b"]) / joint["b"].var()
            row["corr_2y"] = joint["a"].corr(joint["b"])
        row["rs_3m"] = _ret(px, last, last - pd.DateOffset(months=3)) - _ret(bench, last, last - pd.DateOffset(months=3))
        row["rs_1y"] = ret_1y - _ret(bench, last, y1_start)
    row["sharpe_1y"] = (ret_1y - rf_pct) / vol if enough and vol else np.nan
    row["sortino_1y"] = (ret_1y - rf_pct) / downside if enough and downside else np.nan
    q05 = r.quantile(0.05) if enough else np.nan
    row["var95_1d"] = 100 * q05
    row["cvar95_1d"] = 100 * r[r <= q05].mean() if enough else np.nan
    row["skew_1y"] = r.skew() if enough else np.nan
    row["kurt_1y"] = r.kurt() if enough else np.nan
    row["up_days_pct_1y"] = 100 * (r > 0).mean() if enough else np.nan
    row["avg_value_20d_mxn_mm"] = float((g["close"] * g["volume"]).iloc[-20:].mean()) / 1e6
    since = last - pd.DateOffset(months=3)
    traded = int(((g.index > since) & (g["volume"] > 0)).sum())
    sessions = int((calendar > since).sum()) if calendar is not None and len(calendar) else 0
    row["traded_days_pct_3m"] = min(100.0, 100 * traded / sessions) if sessions else np.nan
    row["div_12m"] = row["div_yield_12m_pct"] = np.nan
    if "dividend" in g.columns:
        divs = g.loc[g.index > y1_start, "dividend"]
        # Si la ventana tiene huecos (precios bajados sin eventos corporativos), no se sabe.
        if len(divs) and not divs.isna().any() and len(base):
            row["div_12m"] = float(divs.sum())
            row["div_yield_12m_pct"] = 100 * row["div_12m"] / float(g["close"].iloc[-1])
    return row


def _flags(row: dict, notes: list[str], last: pd.Timestamp) -> str:
    recent = [n for n in notes if pd.Timestamp(n.rsplit(" el ", 1)[1][:10]) >= last - pd.DateOffset(years=3)]
    if pd.notna(row.get("traded_days_pct_3m")) and row["traded_days_pct_3m"] < 50:
        recent.append("poco operada")
    if row.get("obs_1y", 0) < 200:
        recent.append("historia corta")
    return "; ".join(recent)


def risk_stats(prices: pd.DataFrame, universe: pd.DataFrame, rf_pct: float = 0.0) -> pd.DataFrame:
    """Riesgo, fuerza relativa, liquidez, dividendos y alertas de datos por emisora (BMV y SIC)."""
    if prices.empty:
        return pd.DataFrame()
    series = price_series(prices)
    groups = {t: g for t, (g, _) in series.items()}
    benches = _benchmarks(groups)
    calendar = groups[BENCHMARKS["BMV"]].index if BENCHMARKS["BMV"] in groups else None
    eq = universe[universe["market"].isin(EQUITY_MARKETS)]
    rows = []
    for ticker, market in zip(eq["ticker"], eq["market"]):
        if ticker not in series or len(series[ticker][0]) < 2:
            continue
        g, notes = series[ticker]
        row = _risk_row(g, benches.get(market), rf_pct, calendar)
        row["data_flags"] = _flags(row, notes, g.index[-1])
        rows.append({"ticker": ticker, **row})
    out = pd.DataFrame(rows)
    if not out.empty:
        out["rf_pct"] = rf_pct
    return out


def latest_fundamentals(fundamentals: pd.DataFrame) -> pd.DataFrame:
    if fundamentals.empty:
        return pd.DataFrame()
    f = fundamentals.copy()
    f["date"] = pd.to_datetime(f["date"])
    return f.sort_values("date").groupby("ticker", as_index=False).tail(1).reset_index(drop=True)


def last_close(prices: pd.DataFrame) -> pd.Series:
    if prices.empty:
        return pd.Series(dtype="float64")
    p = prices.sort_values("date")
    return p.groupby("ticker")["close"].last()


def normalize_fundamentals(fundamentals: pd.DataFrame, close: pd.Series, usdmxn: float) -> pd.DataFrame:
    """Fundamentales con unidades consistentes (% en %, multiplos en veces, valor en MXN)."""
    f = latest_fundamentals(fundamentals)
    if f.empty:
        return pd.DataFrame()
    cur = _text(f, "currency")
    fin_cur = _text(f, "financialCurrency")
    fx = cur.map({"MXN": 1.0, "USD": usdmxn}).astype("float64")
    pe = _num(f, "trailingPE")
    mcap = _num(f, "marketCap")
    ebitda = _num(f, "ebitda")
    out = pd.DataFrame({"ticker": f["ticker"].astype(str)})
    out["sector"] = _text(f, "sector")
    out["industry"] = _text(f, "industry")
    out["mkt_cap_mxn_bn"] = mcap * fx / 1e9
    out["pe"] = pe
    out["fwd_pe"] = _num(f, "forwardPE")
    out["peg"] = _num(f, "pegRatio")
    out["pb"] = _num(f, "priceToBook")
    out["ps"] = _num(f, "priceToSalesTrailing12Months")
    out["ev_ebitda"] = _num(f, "enterpriseToEbitda")
    out["ev_sales"] = _num(f, "enterpriseToRevenue")
    out["earnings_yield_pct"] = (100 / pe).where(pe > 0)
    same_cur = fin_cur.notna() & (fin_cur == cur)
    out["fcf_yield_pct"] = (100 * _num(f, "freeCashflow") / mcap).where(same_cur.fillna(False))
    out["div_yield_pct"] = _num(f, "dividendYield")  # Yahoo ya lo entrega en %
    out["payout_pct"] = 100 * _num(f, "payoutRatio")
    for new, old in (("roe_pct", "returnOnEquity"), ("roa_pct", "returnOnAssets"),
                     ("gross_margin_pct", "grossMargins"), ("op_margin_pct", "operatingMargins"),
                     ("ebitda_margin_pct", "ebitdaMargins"), ("net_margin_pct", "profitMargins"),
                     ("rev_growth_pct", "revenueGrowth"), ("eps_growth_pct", "earningsGrowth"),
                     ("insiders_pct", "heldPercentInsiders"), ("institutions_pct", "heldPercentInstitutions")):
        out[new] = 100 * _num(f, old)
    out["debt_to_equity"] = _num(f, "debtToEquity") / 100  # Yahoo lo entrega x100
    out["net_debt_ebitda"] = ((_num(f, "totalDebt") - _num(f, "totalCash")) / ebitda).where(ebitda > 0)
    out["current_ratio"] = _num(f, "currentRatio")
    target = _num(f, "targetMeanPrice")
    px_mxn = f["ticker"].map(close).astype("float64")
    ref_px = _num(f, "currentPrice").fillna(px_mxn / fx)
    out["target_mean"] = target
    out["target_upside_pct"] = 100 * (target / ref_px - 1)
    out["rec_mean"] = _num(f, "recommendationMean")
    out["rec_key"] = _text(f, "recommendationKey")
    out["n_analysts"] = _num(f, "numberOfAnalystOpinions")
    out["quote_currency"] = cur
    out["fin_currency"] = fin_cur.fillna(cur)
    out["fund_date"] = f["date"].dt.date.astype(str)
    out["long_name"] = _text(f, "longName").fillna(_text(f, "shortName"))
    out["summary"] = _text(f, "longBusinessSummary")
    out["website"] = _text(f, "website")
    out["employees"] = _num(f, "fullTimeEmployees")
    return out


def earnings_summary(earnings: pd.DataFrame, today: pd.Timestamp) -> pd.DataFrame:
    if earnings.empty:
        return pd.DataFrame(columns=["ticker"])
    e = earnings.copy()
    e["date"] = pd.to_datetime(e["date"])
    nxt = e[e["date"] >= today].groupby("ticker")["date"].min().rename("next_earnings")
    rep = e[e["eps_reported"].notna() & (e["date"] <= today)].sort_values("date")
    last = rep.groupby("ticker").tail(1).set_index("ticker")
    beats = rep.groupby("ticker").tail(4).groupby("ticker")["surprise_pct"].apply(lambda s: int((s > 0).sum()))
    out = pd.concat([nxt, last["date"].rename("last_earnings"), last["surprise_pct"].rename("last_surprise_pct"),
                     beats.rename("beats_4q")], axis=1)
    for col in ("next_earnings", "last_earnings"):
        out[col] = pd.to_datetime(out[col]).dt.date.astype("string")
    return out.rename_axis("ticker").reset_index()


def recommendations_summary(recs: pd.DataFrame) -> pd.DataFrame:
    if recs.empty:
        return pd.DataFrame(columns=["ticker"])
    r = recs.copy()
    r["date"] = pd.to_datetime(r["date"])
    r = r.sort_values("date").groupby("ticker").tail(1)
    total = r[["strong_buy", "buy", "hold", "sell", "strong_sell"]].sum(axis=1)
    return pd.DataFrame({
        "ticker": r["ticker"],
        "rec_buy_pct": (100 * (r["strong_buy"] + r["buy"]) / total).where(total > 0),
        "rec_sell_pct": (100 * (r["sell"] + r["strong_sell"]) / total).where(total > 0),
    })


def add_scores(df: pd.DataFrame) -> pd.DataFrame:
    """Percentiles por mercado (solo acciones y FIBRAs). Requiere al menos 2 componentes."""
    df = df.copy()
    cos = df["asset_type"].isin(["stock", "fibra"])
    for score, parts in SCORES.items():
        ranks = []
        for col, sign in parts.items():
            x = df[col].astype("float64") if col in df.columns else pd.Series(np.nan, index=df.index)
            if col in ("pb", "ev_ebitda"):
                x = x.where(x > 0)  # capital o EBITDA negativos no son "baratos"
            x = (sign * x).where(cos)
            ranks.append(x.groupby(df["market"]).rank(pct=True))
        r = pd.concat(ranks, axis=1)
        df[score] = (100 * r.mean(axis=1)).where(r.notna().sum(axis=1) >= 2).round(0)
    return df


def equity_snapshot(prices: pd.DataFrame, universe: pd.DataFrame, fundamentals: pd.DataFrame,
                    macro: pd.DataFrame, market: pd.DataFrame, earnings: pd.DataFrame | None = None,
                    recommendations: pd.DataFrame | None = None, financials: pd.DataFrame | None = None,
                    today: pd.Timestamp | None = None) -> pd.DataFrame:
    """Una fila por accion, FIBRA o ETF con precio, riesgo, fundamentales, analistas y puntajes."""
    if prices.empty or market.empty:
        return pd.DataFrame()
    today = today or pd.Timestamp(datetime.now(timezone.utc).date())
    close = last_close(prices)
    usdmxn = float(close.get(FX_TICKER, np.nan))
    base_cols = ["ticker", "market", "asset_type", "name", "date", "close", "chg_1d", "chg_1m", "chg_3m",
                 "chg_6m", "chg_ytd", "chg_1y", "pct_from_52w_high", "vs_sma200", "rsi14"]
    df = market[market["market"].isin(EQUITY_MARKETS)][base_cols]
    df = df.merge(risk_stats(prices, universe, rf_rate(macro)), on="ticker", how="left")
    fund = normalize_fundamentals(fundamentals, close, usdmxn)
    if not fund.empty:
        df = df.merge(fund.drop(columns=["long_name", "summary", "website", "employees"]), on="ticker", how="left")
    df = df.merge(recommendations_summary(recommendations if recommendations is not None else pd.DataFrame()),
                  on="ticker", how="left")
    df = df.merge(earnings_summary(earnings if earnings is not None else pd.DataFrame(), today),
                  on="ticker", how="left")
    if financials is not None and not financials.empty:
        q = financials[financials["freq"] == "Q"]
        lastq = pd.to_datetime(q["period_end"]).groupby(q["ticker"]).max().dt.date.astype("string")
        df = df.merge(lastq.rename("last_quarter").rename_axis("ticker").reset_index(), on="ticker", how="left")
    df = add_scores(df).reindex(columns=list(COLUMNS))
    num = df.select_dtypes("number").columns
    df[num] = df[num].round(3)
    return df.reset_index(drop=True)


# ----------------------------------------------------------------------------- estados

def _pick(items: pd.DataFrame, keys: list[str]) -> tuple[str | None, pd.Series | None]:
    for k in keys:
        if k in items.index:
            return k, items.loc[k]
    return None, None


def statement_table(fin: pd.DataFrame, statement: str, freq: str, periods: int, full: bool = False,
                    ttm: bool = True) -> pd.DataFrame:
    """Partidas x periodos (mas reciente primero). Con ``freq='Q'`` agrega TTM a resultados y flujos."""
    f = fin[(fin["statement"] == statement) & (fin["freq"] == freq)]
    if f.empty:
        return pd.DataFrame()
    wide = f.pivot_table(index="item", columns="period_end", values="value", aggfunc="last")
    wide = wide[sorted(wide.columns, reverse=True)]
    cols = list(wide.columns[:periods])
    rows = []
    if full:
        for item in wide.index:
            rows.append((item, item, wide.loc[item]))
    else:
        for label, keys in KEY_ITEMS[statement]:
            key, series = _pick(wide, keys)
            if key is not None:
                rows.append((label, key, series))
    if not rows:
        return pd.DataFrame()
    table = pd.DataFrame({"partida": [r[0] for r in rows], "clave": [r[1] for r in rows]})
    for c in cols:
        table[pd.Timestamp(c).date().isoformat()] = [r[2].get(c, np.nan) for r in rows]
    if freq == "Q" and ttm and statement in ("income", "cashflow") and len(wide.columns) >= 4:
        last4 = list(wide.columns[:4])
        if (pd.Timestamp(last4[0]) - pd.Timestamp(last4[3])).days <= 300:
            table.insert(2, "TTM", [r[2][last4].sum(min_count=4) if r[1] not in SHARE_ITEMS
                                    else r[2].get(last4[0], np.nan) for r in rows])
    return table


def annual_summary(fin: pd.DataFrame, years: int = 4) -> pd.DataFrame:
    """Cifras clave por anio fiscal (+ TTM): ingresos, EBITDA, utilidad, UPA, flujo libre, deuda neta."""
    if fin.empty:
        return pd.DataFrame()
    picks = [("Ingresos", "income", ["TotalRevenue", "OperatingRevenue"]),
             ("EBITDA", "income", ["EBITDA", "NormalizedEBITDA"]),
             ("Utilidad neta", "income", ["NetIncomeCommonStockholders", "NetIncome"]),
             ("UPA diluida", "income", ["DilutedEPS", "BasicEPS"]),
             ("Flujo libre", "cashflow", ["FreeCashFlow"]),
             ("Deuda neta", "balance", ["NetDebt"])]
    out = {}
    for freq in ("A", "Q"):
        for label, st, keys in picks:
            f = fin[(fin["statement"] == st) & (fin["freq"] == freq)]
            if f.empty:
                continue
            wide = f.pivot_table(index="item", columns="period_end", values="value", aggfunc="last")
            wide = wide[sorted(wide.columns, reverse=True)]
            key, s = _pick(wide, keys)
            if key is None:
                continue
            if freq == "A":
                for c in wide.columns[:years]:
                    out.setdefault(label, {})[f"FY{pd.Timestamp(c).year}"] = s.get(c, np.nan)
            elif len(wide.columns) >= 4 and (wide.columns[0] - wide.columns[3]).days <= 300:
                last4 = list(wide.columns[:4])
                out.setdefault(label, {})["TTM"] = s[last4[0]] if st == "balance" else s[last4].sum(min_count=4)
    if not out:
        return pd.DataFrame()
    table = pd.DataFrame(out).T
    order = (["TTM"] if "TTM" in table.columns else []) + sorted([c for c in table.columns if c != "TTM"], reverse=True)
    table = table[order]
    if "Ingresos" in table.index:
        if "Utilidad neta" in table.index:
            table.loc["Margen neto %"] = 100 * table.loc["Utilidad neta"] / table.loc["Ingresos"]
        fy = [c for c in table.columns if c.startswith("FY")]
        growth = table.loc["Ingresos", fy].astype(float)
        table.loc["Crec. ingresos %", fy] = (100 * (growth / growth.shift(-1) - 1)).values
    return table.rename_axis("cifra").reset_index()


# ----------------------------------------------------------------------------- acceso a datos

def _fold(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", str(text)) if not unicodedata.combining(c)).lower()


class Repo:
    """Acceso perezoso a los datos del repo (lee solo lo que pide cada comando)."""

    def __init__(self, data_dir: Path | None = None) -> None:
        self.data_dir = Path(data_dir or config.DATA_DIR)

    def _read(self, name: str) -> pd.DataFrame:
        return storage.read_dataset(self.data_dir / name)

    @cached_property
    def universe(self) -> pd.DataFrame:
        return config.load_universe()

    @cached_property
    def prices(self) -> pd.DataFrame:
        return self._read("prices")

    @cached_property
    def fundamentals(self) -> pd.DataFrame:
        return self._read("fundamentals")

    @cached_property
    def financials(self) -> pd.DataFrame:
        return self._read("financials")

    @cached_property
    def earnings(self) -> pd.DataFrame:
        return self._read("earnings")

    @cached_property
    def recommendations(self) -> pd.DataFrame:
        return self._read("recommendations")

    @cached_property
    def profiles(self) -> pd.DataFrame:
        f = normalize_fundamentals(self.fundamentals, pd.Series(dtype="float64"), np.nan)
        return f.set_index("ticker") if not f.empty else pd.DataFrame()

    @cached_property
    def equity(self) -> pd.DataFrame:
        path = self.data_dir / "snapshots" / "equity_snapshot.csv"
        if path.exists():
            return pd.read_csv(path)
        from econ import snapshots  # se calcula al vuelo si el pipeline aun no genero el CSV

        market = snapshots.market_snapshot(self.prices, self.universe)
        return equity_snapshot(self.prices, self.universe, self.fundamentals, self._read("macro"), market,
                               self.earnings, self.recommendations, self.financials)

    def resolve(self, text: str) -> str:
        """WALMEX -> WALMEX.MX, AAPL -> AAPL.MX (por ref_ticker), 'banorte' -> GFNORTEO.MX."""
        u = self.universe
        q = text.strip().upper()
        tickers = set(u["ticker"])
        for cand in (q, f"{q}.MX"):
            if cand in tickers:
                return cand
        ref = u[u["ref_ticker"].str.upper() == q]
        if len(ref):
            return ref["ticker"].iloc[0]
        eq = u[u["market"].isin(EQUITY_MARKETS)]
        pref = eq[eq["ticker"].str.upper().str.startswith(q)]
        if len(pref) == 1:
            return pref["ticker"].iloc[0]
        folded = _fold(text)
        names = eq[eq["name"].map(_fold).str.contains(folded, regex=False)]
        if len(names) == 1:
            return names["ticker"].iloc[0]
        options = list(dict.fromkeys([*pref["ticker"], *names["ticker"]]))[:10]
        hint = f" Opciones: {', '.join(options)}" if options else " Usa: python -m econ.equity buscar <texto>"
        raise LookupError(f"No identifico la emisora '{text}'.{hint}")


# ----------------------------------------------------------------------------- formato

def _fmt(v, decimals: int = 2) -> str:
    if v is None or (isinstance(v, float) and np.isnan(v)) or v is pd.NA or (isinstance(v, str) and v == "nan"):
        return "-"
    if isinstance(v, (int, np.integer)):
        return f"{v:,}"
    if isinstance(v, (float, np.floating)):
        return f"{v:,.{decimals}f}"
    return str(v)


INT_COLUMNS = {*SCORES, "n_analysts", "beats_4q", "obs_1y", "sesiones", "pagos"}


def md_table(df: pd.DataFrame, decimals: int = 2) -> str:
    if df is None or df.empty:
        return "_sin datos_\n"
    cols = [str(c) for c in df.columns]
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for _, r in df.iterrows():
        cells = [_fmt(_i(v) if c in INT_COLUMNS else v, decimals) for c, v in zip(cols, r)]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def _scaled(table: pd.DataFrame) -> pd.DataFrame:
    """Montos en millones; UPA tal cual; acciones en millones."""
    t = table.copy()
    value_cols = [c for c in t.columns if c not in ("partida", "clave")]
    for i, key in enumerate(t["clave"]):
        if key not in PER_SHARE_ITEMS:
            t.loc[i, value_cols] = t.loc[i, value_cols].astype(float) / 1e6
    return t


def _i(v):
    """Conteos y puntajes como enteros."""
    return int(v) if isinstance(v, (int, float, np.integer, np.floating)) and pd.notna(v) else v


def _kv(pairs: list[tuple[str, object, str]]) -> str:
    cells = [f"{label}: **{_fmt(v)}{unit}**" for label, v, unit in pairs if _fmt(v) != "-"]
    return " · ".join(cells) if cells else "_sin datos_"


# ----------------------------------------------------------------------------- comandos

def ficha(repo: Repo, ticker: str) -> str:
    t = repo.resolve(ticker)
    eq = repo.equity.set_index("ticker")
    u = repo.universe.set_index("ticker").loc[t]
    row = eq.loc[t] if t in eq.index else pd.Series(dtype=object)
    prof = repo.profiles.loc[t] if t in repo.profiles.index else pd.Series(dtype=object)
    g = row.get
    out = [f"# {t} · {u['name']} ({u['market']}, {u['asset_type']})\n"]
    head = [f"Cierre **{_fmt(g('close'))} MXN** ({g('date', '-')})",
            f"1d {_fmt(g('chg_1d'))}%", f"1m {_fmt(g('chg_1m'))}%", f"YTD {_fmt(g('chg_ytd'))}%",
            f"12m {_fmt(g('chg_1y'))}%"]
    out.append(" · ".join(head) + "\n")
    if isinstance(g("data_flags"), str) and g("data_flags"):
        out.append(f"**Alerta de datos:** {g('data_flags')}.\n")
    if u["ref_ticker"]:
        out.append(f"Replica del SIC de `{u['ref_ticker']}`: precio y rendimientos en MXN; multiplos, estados y "
                   f"objetivos de analistas del ticker de origen en {g('fin_currency', 'su moneda')}.\n")
    out.append("## Puntajes (percentil en su mercado, 100 = mejor)\n")
    out.append(_kv([("Valor", _i(g("score_value")), ""), ("Calidad", _i(g("score_quality")), ""),
                    ("Momentum", _i(g("score_momentum")), ""), ("Riesgo (alto = menos riesgo)", _i(g("score_risk")), "")]) + "\n")
    out.append("## Desempeno y tecnico\n")
    out.append(_kv([("3m", g("chg_3m"), "%"), ("6m", g("chg_6m"), "%"), ("Mom 12-1", g("mom_12_1"), "%"),
                    ("vs max 52s", g("pct_from_52w_high"), "%"), ("vs SMA200", g("vs_sma200"), "%"),
                    ("RSI14", g("rsi14"), ""), ("RS 3m vs benchmark", g("rs_3m"), " pp"),
                    ("RS 12m", g("rs_1y"), " pp")]) + "\n")
    out.append("## Riesgo (1 anio)\n")
    out.append(_kv([("Vol", g("vol_1y"), "%"), ("Vol a la baja", g("downside_vol_1y"), "%"),
                    ("Max caida 1a", g("max_dd_1y"), "%"), ("Max caida 3a", g("max_dd_3y"), "%"),
                    ("Beta 2a sem.", g("beta_2y"), ""), ("Correlacion", g("corr_2y"), ""), ("Sharpe", g("sharpe_1y"), ""),
                    ("Sortino", g("sortino_1y"), ""), ("VaR95 1d", g("var95_1d"), "%"),
                    ("CVaR95 1d", g("cvar95_1d"), "%"), ("Sesgo", g("skew_1y"), ""), ("Curtosis", g("kurt_1y"), ""),
                    ("rf", g("rf_pct"), "%")]) + "\n")
    out.append("## Liquidez y dividendos\n")
    out.append(_kv([("Importe 20d", g("avg_value_20d_mxn_mm"), " mm MXN"),
                    ("Sesiones operadas 3m", g("traded_days_pct_3m"), "%"),
                    ("Dividendos 12m", g("div_12m"), " MXN"), ("Yield 12m", g("div_yield_12m_pct"), "%"),
                    ("Yield (Yahoo)", g("div_yield_pct"), "%"), ("Payout", g("payout_pct"), "%")]) + "\n")
    out.append("## Valuacion\n")
    out.append(_kv([("Valor de mercado", g("mkt_cap_mxn_bn"), " mmm MXN"), ("P/U", g("pe"), "x"),
                    ("P/U est.", g("fwd_pe"), "x"), ("PEG", g("peg"), ""), ("P/VL", g("pb"), "x"),
                    ("P/Ventas", g("ps"), "x"), ("VE/EBITDA", g("ev_ebitda"), "x"),
                    ("Rend. utilidades", g("earnings_yield_pct"), "%"), ("FCF yield", g("fcf_yield_pct"), "%")]) + "\n")
    out.append("## Rentabilidad, crecimiento y balance\n")
    out.append(_kv([("ROE", g("roe_pct"), "%"), ("ROA", g("roa_pct"), "%"), ("Margen bruto", g("gross_margin_pct"), "%"),
                    ("Margen op.", g("op_margin_pct"), "%"), ("Margen EBITDA", g("ebitda_margin_pct"), "%"),
                    ("Margen neto", g("net_margin_pct"), "%"), ("Crec. ingresos", g("rev_growth_pct"), "%"),
                    ("Crec. utilidades", g("eps_growth_pct"), "%"), ("Deuda/capital", g("debt_to_equity"), "x"),
                    ("Deuda neta/EBITDA", g("net_debt_ebitda"), "x"), ("Liquidez corriente", g("current_ratio"), "x")]) + "\n")
    out.append("## Analistas y reportes\n")
    out.append(_kv([("Objetivo promedio", g("target_mean"), f" {g('quote_currency', '')}"),
                    ("Potencial", g("target_upside_pct"), "%"), ("Consenso", g("rec_key"), ""),
                    ("Recomendacion media (1-5)", g("rec_mean"), ""), ("Analistas", _i(g("n_analysts")), ""),
                    ("Compra", g("rec_buy_pct"), "%"), ("Venta", g("rec_sell_pct"), "%"),
                    ("Proximo reporte", g("next_earnings"), ""), ("Ultimo reporte", g("last_earnings"), ""),
                    ("Sorpresa UPA", g("last_surprise_pct"), "%"), ("Superados (4 rep.)", _i(g("beats_4q")), "/4")]) + "\n")
    fin = repo.financials
    fin = fin[fin["ticker"] == t] if not fin.empty else fin
    summary = annual_summary(fin)
    cur = g("fin_currency") if isinstance(g("fin_currency"), str) else "moneda de reporte"
    out.append(f"## Cifras clave (millones de {cur}; UPA por accion)\n")
    if summary.empty:
        out.append("_Sin estados financieros todavia (tarea `company` del pipeline)._\n")
    else:
        s = summary.set_index("cifra")
        money = [i for i in s.index if i not in ("UPA diluida", "Margen neto %", "Crec. ingresos %")]
        s.loc[money] = s.loc[money].astype(float) / 1e6
        out.append(md_table(s.reset_index()))
        if pd.notna(g("last_quarter")):
            out.append(f"\nUltimo trimestre reportado: {g('last_quarter')}. Detalle: `python -m econ.equity estados {t}`.\n")
    out.append("\n## Pares\n")
    out.append(md_table(peers(repo, t, limit=6)))
    if len(prof) and isinstance(prof.get("summary"), str):
        out.append("\n## Perfil\n")
        meta = [x for x in (prof.get("long_name"), g("sector"), g("industry"), prof.get("website")) if isinstance(x, str)]
        out.append(" · ".join(meta) + "\n\n" + prof["summary"] + "\n")
    out.append(f"\n_Fuentes: precios al {g('date', '-')}; fundamentales al {g('fund_date', '-')} (Yahoo Finance)._\n")
    return "\n".join(out)


def estados(repo: Repo, ticker: str, freq: str = "A", statement: str = "all", periods: int | None = None,
            full: bool = False) -> str:
    t = repo.resolve(ticker)
    fin = repo.financials
    fin = fin[fin["ticker"] == t] if not fin.empty else fin
    if fin.empty:
        return f"{t}: sin estados financieros todavia (los baja la tarea `company` del pipeline)."
    cur = repo.profiles["fin_currency"].get(t) if not repo.profiles.empty else None
    periods = periods or (4 if freq == "A" else 5)
    out = [f"# {t} · estados financieros ({'anuales' if freq == 'A' else 'trimestrales'})\n",
           f"Millones de {cur or 'la moneda de reporte'} (UPA por accion; acciones en millones).\n"]
    for st in (STATEMENTS_ORDER if statement == "all" else [statement]):
        table = statement_table(fin, st, freq, periods, full=full)
        out.append(f"\n## {STATEMENT_NAMES[st]}\n")
        out.append(md_table(_scaled(table)) if not table.empty else "_sin datos_\n")
    return "\n".join(out)


STATEMENTS_ORDER = ["income", "balance", "cashflow"]


def screen(repo: Repo, market: str | None = None, asset_type: str | None = None, sector: str | None = None,
           where: str | None = None, sort: str | None = None, ascending: bool = False, limit: int = 20,
           cols: list[str] | None = None) -> pd.DataFrame:
    df = repo.equity.copy()
    if market:
        df = df[df["market"] == market.upper()]
    if asset_type:
        df = df[df["asset_type"] == asset_type]
    if sector:
        s = _fold(sector)
        df = df[df["sector"].fillna("").map(_fold).str.contains(s, regex=False)
                | df["industry"].fillna("").map(_fold).str.contains(s, regex=False)]
    if where:
        df = df.query(where, engine="python")
    if sort:
        df = df.sort_values(sort, ascending=ascending, na_position="last")
    cols = cols or DEFAULT_SCREEN_COLS
    return df[[c for c in cols if c in df.columns]].head(limit)


def compare(repo: Repo, tickers: list[str], cols: list[str] | None = None) -> pd.DataFrame:
    resolved = [repo.resolve(t) for t in tickers]
    eq = repo.equity.set_index("ticker")
    cols = [c for c in (cols or COMPARE_COLS) if c in eq.columns]
    table = eq.reindex(resolved)[cols].T
    return table.rename_axis("metrica").reset_index()


def peers(repo: Repo, ticker: str, limit: int = 10, all_markets: bool = False) -> pd.DataFrame:
    t = repo.resolve(ticker)
    eq = repo.equity
    me = eq[eq["ticker"] == t]
    if me.empty:
        return pd.DataFrame()
    me = me.iloc[0]
    pool = eq if all_markets else eq[eq["market"] == me["market"]]
    pool = pool[pool["asset_type"] == me["asset_type"]]
    same = pool[pool["industry"] == me["industry"]] if pd.notna(me["industry"]) else pool.iloc[0:0]
    if len(same) < 4 and pd.notna(me["sector"]):
        same = pool[pool["sector"] == me["sector"]]
    cols = ["ticker", "name", "mkt_cap_mxn_bn", "chg_ytd", "pe", "ev_ebitda", "pb", "div_yield_pct", "roe_pct",
            "net_margin_pct", "target_upside_pct"]
    same = same.sort_values("mkt_cap_mxn_bn", ascending=False, na_position="last")
    top = same.head(limit)
    if t not in set(top["ticker"]):
        top = pd.concat([me.to_frame().T, top.head(limit - 1)])
    return top[[c for c in cols if c in top.columns]].reset_index(drop=True)


def dividendos(repo: Repo, ticker: str, years: int = 5) -> str:
    t = repo.resolve(ticker)
    p = repo.prices
    p = p[p["ticker"] == t]
    if "dividend" not in p.columns or p["dividend"].isna().all():
        return (f"{t}: la serie de precios aun no trae dividendos. Corre la tarea `backfill` del pipeline "
                "(baja el historico con dividendos y splits).")
    p = p.assign(date=pd.to_datetime(p["date"])).sort_values("date")
    since = p["date"].max() - pd.DateOffset(years=years)
    pays = p[(p["dividend"] > 0) & (p["date"] >= since)][["date", "dividend", "close"]].copy()
    if pays.empty:
        return f"{t}: sin dividendos registrados en {years} anios."
    pays["yield_pct"] = 100 * pays["dividend"] / pays["close"]
    yearly = pays.groupby(pays["date"].dt.year)["dividend"].agg(["sum", "count"]).reset_index()
    yearly.columns = ["anio", "dividendo_mxn", "pagos"]
    last_close_px = float(p["close"].iloc[-1])
    ttm = float(pays.loc[pays["date"] > p["date"].max() - pd.DateOffset(years=1), "dividend"].sum())
    pays["date"] = pays["date"].dt.date.astype(str)
    return "\n".join([
        f"# {t} · dividendos (MXN por accion)\n",
        f"Ultimos 12 meses: **{ttm:,.4f} MXN** = **{100 * ttm / last_close_px:,.2f}%** del precio actual "
        f"({last_close_px:,.2f}).\n",
        "## Por anio\n", md_table(yearly, 4),
        "\n## Pagos\n", md_table(pays.iloc[::-1].rename(columns={"date": "fecha", "dividend": "dividendo"}), 4),
        "\n_Fecha = fecha ex-dividendo en la BMV (Yahoo)._",
    ])


# Busqueda en espanol sobre sectores e industrias de Yahoo (en ingles).
SEARCH_SYNONYMS = {
    "banco": "bank", "financier": "financial", "seguro": "insurance", "bebida": "beverage",
    "cerveza": "brewer", "alimento": "food", "comida": "food", "restaurante": "restaurant",
    "autoservicio": "discount stores", "supermercado": "grocery", "tienda": "retail", "minori": "retail",
    "miner": "mining", "metal": "metal", "acero": "steel", "cobre": "copper", "oro": "gold",
    "cemento": "building materials", "construc": "construction", "vivienda": "residential",
    "inmobiliari": "real estate", "fibra": "reit", "aeropuerto": "airports", "aerolinea": "airlines",
    "transporte": "transport", "ferrocarril": "railroads", "telecom": "telecom", "medio": "media",
    "salud": "health", "farmac": "drug", "hospital": "medical", "energia": "energy", "petrole": "oil",
    "gas": "gas", "electric": "utilities", "tecnolog": "technology", "semiconductor": "semiconductor",
    "software": "software", "auto": "auto", "quimic": "chemical", "papel": "paper", "hotel": "lodging",
    "entretenimiento": "entertainment", "educacion": "education", "defensa": "defense",
}


def buscar(repo: Repo, text: str) -> pd.DataFrame:
    u = repo.universe[repo.universe["market"].isin(EQUITY_MARKETS)].copy()
    prof = repo.profiles
    if not prof.empty:
        u = u.merge(prof[["sector", "industry", "long_name"]].reset_index(), on="ticker", how="left")
    else:
        u[["sector", "industry", "long_name"]] = pd.NA
    q = _fold(text)
    found = [es for es in SEARCH_SYNONYMS if es in q]
    found = [es for es in found if not any(es != o and es in o for o in found)]  # autoservicio != auto
    terms = [q] + [SEARCH_SYNONYMS[es] for es in found]
    hay = (u["ticker"] + " " + u["ref_ticker"] + " " + u["name"] + " " + u["sector"].fillna("") + " "
           + u["industry"].fillna("") + " " + u["long_name"].fillna("")).map(_fold)
    hit = pd.concat([hay.str.contains(t, regex=False) for t in terms], axis=1).any(axis=1)
    return u[hit][["ticker", "market", "asset_type", "name", "sector", "industry"]]


def periodo(repo: Repo, tickers: list[str], spec: str, today=None) -> tuple[pd.DataFrame, str]:
    """Rendimiento de emisoras en un periodo (mismos formatos que ``econ.macro``: ytd, 2026-03,
    last-week, 2026-Q1...) contra su benchmark. Ultimo cierre antes del periodo vs ultimo del periodo."""
    from datetime import date

    from econ import macro

    start, end, label = macro.resolve_period(spec, today or date.today())
    t0, t1 = pd.Timestamp(start), pd.Timestamp(end)
    u = repo.universe.set_index("ticker")
    resolved = [repo.resolve(t) for t in tickers]
    need = set(resolved) | set(BENCHMARKS.values()) | {SIC_FALLBACK, FX_TICKER}
    groups = {t: g for t, (g, _) in price_series(repo.prices[repo.prices["ticker"].isin(need)]).items()}
    benches = _benchmarks(groups)
    rows = []
    for t in resolved:
        g = groups.get(t)
        if g is None:
            continue
        px = g["px"]
        before, upto = px[px.index < t0], px[px.index <= t1]
        within = g[(g.index >= t0) & (g.index <= t1)]
        if upto.empty:
            continue
        chg = 100 * (upto.iloc[-1] / before.iloc[-1] - 1) if len(before) and len(within) else np.nan
        bench = benches.get(u.loc[t, "market"]) if t in u.index else None
        b_chg = np.nan
        if bench is not None and len(within):
            bb, be = bench[bench.index < t0], bench[bench.index <= t1]
            b_chg = 100 * (be.iloc[-1] / bb.iloc[-1] - 1) if len(bb) and len(be) else np.nan
        span = px[(px.index >= (before.index[-1] if len(before) else t0)) & (px.index <= t1)]
        rows.append({
            "ticker": t, "name": u.loc[t, "name"] if t in u.index else "",
            "base_date": before.index[-1].date().isoformat() if len(before) else None,
            "base_close": float(g.loc[before.index[-1], "close"]) if len(before) else np.nan,
            "end_date": upto.index[-1].date().isoformat(), "end_close": float(g.loc[upto.index[-1], "close"]),
            "chg_pct": chg, "benchmark_chg_pct": b_chg, "exceso_pp": chg - b_chg,
            "max_close": within["close"].max() if len(within) else np.nan,
            "min_close": within["close"].min() if len(within) else np.nan,
            "max_dd_pct": _max_drawdown(span), "sesiones": int(len(within)),
        })
    df = pd.DataFrame(rows)
    num = df.select_dtypes("number").columns
    df[num] = df[num].round(2)
    note = ("chg_pct usa precio ajustado (dividendos y splits); benchmark: BMV = IPC, SIC = SPY.MX. "
            "sesiones = 0: sin operaciones en el periodo (se muestra el ultimo cierre previo).")
    return df, f"Rendimiento {spec}: {label}. {note}"


def columnas() -> pd.DataFrame:
    return pd.DataFrame([(c, u, d) for c, (u, d) in COLUMNS.items()], columns=["columna", "unidad", "descripcion"])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Emisoras: ficha, estados financieros, screener y comparables")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("ficha", help="Todo sobre una emisora")
    p.add_argument("ticker")
    p = sub.add_parser("estados", help="Estados financieros")
    p.add_argument("ticker")
    p.add_argument("--freq", choices=["A", "Q"], default="A", help="A = anual, Q = trimestral (con TTM)")
    p.add_argument("--statement", choices=["all", *STATEMENTS_ORDER], default="all")
    p.add_argument("--periods", type=int)
    p.add_argument("--full", action="store_true", help="Todas las partidas, no solo las clave")
    p = sub.add_parser("screen", help="Filtra y ordena emisoras")
    p.add_argument("--market", choices=list(EQUITY_MARKETS))
    p.add_argument("--type", dest="asset_type", choices=["stock", "fibra", "etf"])
    p.add_argument("--sector", help="Texto en sector o industria")
    p.add_argument("--where", help='Filtro estilo pandas: "pe < 15 and roe_pct > 15"')
    p.add_argument("--sort", help="Columna para ordenar (descendente)")
    p.add_argument("--asc", action="store_true", help="Orden ascendente")
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--cols", help="Columnas separadas por comas")
    p = sub.add_parser("compare", help="Compara emisoras lado a lado")
    p.add_argument("tickers", nargs="+")
    p.add_argument("--cols", help="Columnas separadas por comas")
    p = sub.add_parser("peers", help="Comparables de la misma industria")
    p.add_argument("ticker")
    p.add_argument("--limit", type=int, default=10)
    p.add_argument("--all-markets", action="store_true", help="Incluye BMV y SIC")
    p = sub.add_parser("dividendos", help="Historial de dividendos")
    p.add_argument("ticker")
    p.add_argument("--years", type=int, default=5)
    p = sub.add_parser("periodo", help="Rendimiento en un periodo contra su benchmark")
    p.add_argument("tickers", nargs="+")
    p.add_argument("--period", required=True, help="ytd, mtd, last-week, 2026-03, 2026-Q1, 1y, 2026-01-15:2026-02-15...")
    p.add_argument("--today", help=argparse.SUPPRESS)
    p = sub.add_parser("buscar", help="Busca emisoras por texto")
    p.add_argument("texto")
    sub.add_parser("columnas", help="Diccionario de columnas de equity_snapshot")
    for name in ("screen", "compare", "peers", "periodo", "buscar", "columnas"):
        sub.choices[name].add_argument("--format", choices=["md", "csv", "json"], default="md")
    args = parser.parse_args(argv)

    repo = Repo()
    try:
        if args.cmd == "ficha":
            print(ficha(repo, args.ticker))
            return 0
        if args.cmd == "estados":
            print(estados(repo, args.ticker, args.freq, args.statement, args.periods, args.full))
            return 0
        if args.cmd == "dividendos":
            print(dividendos(repo, args.ticker, args.years))
            return 0
        cols = args.cols.split(",") if getattr(args, "cols", None) else None
        if args.cmd == "screen":
            df = screen(repo, args.market, args.asset_type, args.sector, args.where, args.sort, args.asc,
                        args.limit, cols)
        elif args.cmd == "compare":
            df = compare(repo, args.tickers, cols)
        elif args.cmd == "peers":
            df = peers(repo, args.ticker, args.limit, args.all_markets)
        elif args.cmd == "periodo":
            from datetime import date

            today = date.fromisoformat(args.today) if args.today else None
            df, header = periodo(repo, args.tickers, args.period, today)
            if args.format == "md":
                print(header + "\n")
        elif args.cmd == "buscar":
            df = buscar(repo, args.texto)
        else:
            df = columnas()
    except LookupError as exc:
        print(exc, file=sys.stderr)
        return 2
    if args.format == "csv":
        df.to_csv(sys.stdout, index=False)
    elif args.format == "json":
        print(json.dumps(df.to_dict(orient="records"), ensure_ascii=False, default=str, indent=1))
    else:
        print(md_table(df))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
