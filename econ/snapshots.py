"""Resumenes compactos pensados para agentes de IA (pocos tokens, mucha senal).

Genera en ``data/snapshots/``:

- ``market_snapshot.csv``: una fila por emisora con rendimientos, volatilidad y tendencia.
- ``macro_snapshot.csv``: ultimo dato de cada serie macro y su cambio.
- ``briefing.md``: resumen de una pagina (macro + mercado + movers).
- ``manifest.json``: que datos hay, fechas, archivos y salud del pipeline.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from econ import config, storage

WINDOWS = {"chg_1d": 1, "chg_1w": 5, "chg_1m": 21, "chg_3m": 63, "chg_6m": 126, "chg_1y": 252}
LEVEL_UNITS_PREFIXES = ("indice", "miles", "millones", "personas")


def _rsi(series: pd.Series, period: int = 14) -> float:
    delta = series.diff().dropna()
    if len(delta) < period:
        return np.nan
    gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean().iloc[-1]
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean().iloc[-1]
    if loss == 0:
        return 100.0
    return 100 - 100 / (1 + gain / loss)


def _ticker_metrics(g: pd.DataFrame) -> dict:
    g = g.sort_values("date")
    px = g["adj_close"].fillna(g["close"])
    last = px.iloc[-1]
    last_date = g["date"].iloc[-1]
    row = {"date": last_date.date().isoformat(), "close": g["close"].iloc[-1]}
    for name, n in WINDOWS.items():
        row[name] = 100 * (last / px.iloc[-1 - n] - 1) if len(px) > n else np.nan
    prev_year = px[g["date"].dt.year < last_date.year]
    row["chg_ytd"] = 100 * (last / prev_year.iloc[-1] - 1) if len(prev_year) else np.nan
    last_252 = px.iloc[-252:]
    row["pct_from_52w_high"] = 100 * (last / last_252.max() - 1)
    row["pct_from_52w_low"] = 100 * (last / last_252.min() - 1)
    rets = px.pct_change().iloc[-30:]
    row["vol_30d"] = 100 * rets.std() * np.sqrt(252) if rets.count() > 5 else np.nan
    sma50 = px.iloc[-50:].mean() if len(px) >= 50 else np.nan
    sma200 = px.iloc[-200:].mean() if len(px) >= 200 else np.nan
    row["vs_sma50"] = 100 * (last / sma50 - 1) if pd.notna(sma50) else np.nan
    row["vs_sma200"] = 100 * (last / sma200 - 1) if pd.notna(sma200) else np.nan
    row["rsi14"] = _rsi(px)
    row["avg_vol_20d"] = g["volume"].iloc[-20:].mean()
    return row


def market_snapshot(prices: pd.DataFrame, universe: pd.DataFrame) -> pd.DataFrame:
    if prices.empty:
        return pd.DataFrame()
    prices = prices.copy()
    prices["date"] = pd.to_datetime(prices["date"])
    rows = []
    for ticker, g in prices.groupby("ticker", sort=True):
        rows.append({"ticker": ticker, **_ticker_metrics(g)})
    snap = pd.DataFrame(rows)
    snap = universe[["ticker", "market", "asset_type", "name"]].merge(snap, on="ticker", how="inner")
    num = snap.select_dtypes("number").columns
    snap[num] = snap[num].round(2)
    snap["avg_vol_20d"] = snap["avg_vol_20d"].round(0)
    return snap


def macro_snapshot(macro: pd.DataFrame, series: pd.DataFrame) -> pd.DataFrame:
    if macro.empty:
        return pd.DataFrame()
    macro = macro.copy()
    macro["date"] = pd.to_datetime(macro["date"])
    rows = []
    for (source, sid), g in macro.groupby(["source", "series_id"], sort=False):
        g = g.sort_values("date")
        last = g.iloc[-1]
        prev = g.iloc[-2] if len(g) > 1 else None
        year_ago = g[g["date"] <= last["date"] - pd.DateOffset(years=1)]
        ya = year_ago.iloc[-1]["value"] if len(year_ago) else np.nan
        rows.append({
            "source": source,
            "series_id": sid,
            "date": last["date"].date().isoformat(),
            "value": last["value"],
            "prev_value": prev["value"] if prev is not None else np.nan,
            "chg_1y": last["value"] - ya,
            "pct_1y": 100 * (last["value"] / ya - 1) if ya else np.nan,
        })
    snap = pd.DataFrame(rows)
    meta = series[["source", "series_id", "name", "category", "units", "frequency"]]
    snap = meta.merge(snap, on=["source", "series_id"], how="inner")
    # El % anual solo tiene sentido para niveles/indices, no para tasas en %.
    is_level = snap["units"].str.startswith(LEVEL_UNITS_PREFIXES)
    snap.loc[~is_level, "pct_1y"] = np.nan
    num = snap.select_dtypes("number").columns
    snap[num] = snap[num].round(3)
    return snap


def _md_table(df: pd.DataFrame) -> str:
    if df.empty:
        return "_sin datos_\n"
    cols = list(df.columns)
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for _, r in df.iterrows():
        cells = ["" if pd.isna(v) else (f"{v:,.2f}" if isinstance(v, float) else str(v)) for v in r]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def briefing(market: pd.DataFrame, macro: pd.DataFrame, generated_at: str) -> str:
    out = [f"# Briefing de mercado\n\nGenerado: {generated_at} (UTC)\n"]

    if not macro.empty:
        out.append("## Macro\n")
        cols = ["source", "name", "date", "value", "prev_value", "chg_1y", "pct_1y"]
        out.append(_md_table(macro.sort_values(["category", "source"])[cols]))

    if not market.empty:
        ref = market[market["market"].isin(["INDEX", "FX"])]
        if not ref.empty:
            out.append("\n## Indices y divisas\n")
            out.append(_md_table(ref[["name", "date", "close", "chg_1d", "chg_1m", "chg_ytd", "chg_1y"]]))
        for mkt in ("BMV", "SIC"):
            m = market[market["market"] == mkt].dropna(subset=["chg_1d"])
            if m.empty:
                continue
            breadth = (m["vs_sma200"] > 0).mean() * 100
            out.append(f"\n## {mkt} ({len(m)} emisoras, {breadth:.0f}% sobre su media de 200 dias)\n")
            cols = ["ticker", "name", "close", "chg_1d", "chg_1m", "chg_ytd", "rsi14"]
            out.append("\n**Mayores alzas del dia**\n\n" + _md_table(m.nlargest(5, "chg_1d")[cols]))
            out.append("\n**Mayores bajas del dia**\n\n" + _md_table(m.nsmallest(5, "chg_1d")[cols]))
    return "\n".join(out)


def _dataset_summary(df: pd.DataFrame, root: Path, id_col: str) -> dict:
    if df.empty:
        return {"rows": 0}
    # Rutas relativas a la raiz del repo (p.ej. data/prices/2026-09/data.parquet).
    files = sorted(p.relative_to(root.parent.parent).as_posix() for p in root.glob("*/data.parquet"))
    return {
        "rows": int(len(df)),
        "ids": int(df[id_col].nunique()),
        "min_date": pd.to_datetime(df["date"]).min().date().isoformat(),
        "max_date": pd.to_datetime(df["date"]).max().date().isoformat(),
        "files": files,
    }


def health(prices: pd.DataFrame, macro: pd.DataFrame, universe: pd.DataFrame, series: pd.DataFrame) -> dict:
    """Detecta emisoras/series sin datos o desactualizadas (para depurar el universo)."""
    result: dict = {}
    if not prices.empty:
        last = pd.to_datetime(prices.groupby("ticker")["date"].max())
        cutoff = last.max() - pd.Timedelta(days=7)
        result["tickers_missing"] = sorted(set(universe["ticker"]) - set(last.index))
        result["tickers_stale"] = sorted(last[last < cutoff].index)
    if not macro.empty:
        have = set(zip(macro["source"], macro["series_id"]))
        want = set(zip(series["source"], series["series_id"]))
        result["macro_missing"] = sorted(f"{s}:{i}" for s, i in want - have)
    return result


def build(data_dir: Path | None = None, out_dir: Path | None = None) -> dict:
    data_dir = Path(data_dir or config.DATA_DIR)
    out_dir = Path(out_dir or config.SNAPSHOTS_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)
    universe = config.load_universe()
    series = config.load_macro_series()
    prices = storage.read_dataset(data_dir / "prices")
    macro = storage.read_dataset(data_dir / "macro")
    fundamentals = storage.read_dataset(data_dir / "fundamentals")
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")

    market = market_snapshot(prices, universe)
    macro_snap = macro_snapshot(macro, series)
    if not market.empty:
        market.to_csv(out_dir / "market_snapshot.csv", index=False)
    if not macro_snap.empty:
        macro_snap.to_csv(out_dir / "macro_snapshot.csv", index=False)
    (out_dir / "briefing.md").write_text(briefing(market, macro_snap, generated_at))

    manifest = {
        "generated_at_utc": generated_at,
        "datasets": {
            "prices": _dataset_summary(prices, data_dir / "prices", "ticker"),
            "macro": _dataset_summary(macro, data_dir / "macro", "series_id"),
            "fundamentals": _dataset_summary(fundamentals, data_dir / "fundamentals", "ticker"),
        },
        "health": health(prices, macro, universe, series),
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    return manifest
