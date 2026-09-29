"""Encuentra la clave correcta en Yahoo de las emisoras del SIC que no traen datos.

En el SIC muchas emisoras no usan el ticker de origen tal cual: las extranjeras suelen
llevar una ``N`` (``TSM`` -> ``TSMN.MX``) y otras llevan ``C``, ``1``, ``1N``, ``I`` o ``W``
(``DELL`` -> ``DELLC.MX``, ``ETN`` -> ``ETN1N.MX``, ``WM`` -> ``WMI.MX``, ``NOW`` -> ``NOWW.MX``).
Para cada ticker sin datos se prueban esas variantes y solo se acepta una si su precio en
pesos coincide con ``precio de origen x USD/MXN``; asi no se confunde con otra emisora
que casualmente tenga la clave. Si no coincide (p.ej. ADRs que representan varias acciones,
como Shell), queda en ``mismatch`` para revision manual.
"""
from __future__ import annotations

import logging
import re
from datetime import date, timedelta

import pandas as pd

from econ import config
from econ.sources import yahoo

log = logging.getLogger(__name__)

SUFFIXES = ("N", "C", "1", "N1", "1N", "I", "W")
FX_TICKER = "MXN=X"
MAX_PRICE_GAP = 0.15  # tolerancia contra precio_origen x tipo de cambio


def candidates(ref_ticker: str, current: str) -> list[str]:
    base = re.sub(r"[-.]", "", ref_ticker)
    options = [f"{base}.MX"] + [f"{base}{s}.MX" for s in SUFFIXES]
    return [c for c in dict.fromkeys(options) if c != current]


def _price_ratio(prices: pd.DataFrame, candidate: str, ref: str) -> float | None:
    """Mediana de precio_candidato / (precio_origen x USD/MXN) en las fechas comunes."""
    wide = prices.pivot_table(index="date", columns="ticker", values="close").sort_index()
    if not {candidate, ref, FX_TICKER} <= set(wide.columns):
        return None
    base = wide[[ref, FX_TICKER]].ffill()
    ratio = (wide[candidate] / (base[ref] * base[FX_TICKER])).dropna()
    return float(ratio.median()) if len(ratio) else None


def resolve(tickers: list[str], universe: pd.DataFrame, days: int = 45) -> dict:
    """Busca claves alternativas para ``tickers`` (del SIC) y devuelve un reporte."""
    sic = universe[(universe["market"] == "SIC") & universe["ticker"].isin(tickers) & (universe["ref_ticker"] != "")]
    if sic.empty:
        return {"resolved": {}, "mismatch": {}, "not_found": []}
    options = {r.ticker: candidates(r.ref_ticker, r.ticker) for r in sic.itertuples()}
    symbols = sorted({c for cs in options.values() for c in cs} | set(sic["ref_ticker"]) | {FX_TICKER})
    start = (date.today() - timedelta(days=days)).isoformat()
    prices = yahoo.download_prices(symbols, start=start)

    report: dict = {"resolved": {}, "mismatch": {}, "not_found": []}
    for r in sic.itertuples():
        checked = {}
        for cand in options[r.ticker]:
            ratio = _price_ratio(prices, cand, r.ref_ticker)
            if ratio is None:
                continue
            checked[cand] = round(ratio, 3)
            if abs(ratio - 1) <= MAX_PRICE_GAP:
                report["resolved"][r.ticker] = {"ticker": cand, "price_ratio": round(ratio, 3)}
                break
        else:
            if checked:
                report["mismatch"][r.ticker] = checked
            else:
                report["not_found"].append(r.ticker)
    return report


def apply(report: dict) -> list[str]:
    """Reemplaza en ``config/universe.csv`` las claves resueltas. Devuelve las nuevas."""
    mapping = {old: v["ticker"] for old, v in report["resolved"].items()}
    if not mapping:
        return []
    universe = config.load_universe()
    taken = set(universe["ticker"])
    mapping = {old: new for old, new in mapping.items() if new not in taken}
    universe["ticker"] = universe["ticker"].replace(mapping)
    universe.to_csv(config.UNIVERSE_CSV, index=False, lineterminator="\n")
    for old, new in mapping.items():
        log.info("Clave corregida: %s -> %s", old, new)
    return list(mapping.values())
