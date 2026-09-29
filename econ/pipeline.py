"""Orquestador del pipeline de datos.

Uso::

    python -m econ.pipeline daily                       # precios recientes + macro + snapshots
    python -m econ.pipeline backfill --start 2015-01-01 # historico completo de precios
    python -m econ.pipeline prices --days 10
    python -m econ.pipeline macro
    python -m econ.pipeline fundamentals
    python -m econ.pipeline snapshots
"""
from __future__ import annotations

import argparse
import logging
from datetime import date, timedelta

import pandas as pd

from econ import config, snapshots, storage
from econ.sources import banxico, fred, yahoo

log = logging.getLogger("econ.pipeline")


def update_prices(start: str, tickers: list[str] | None = None) -> int:
    tickers = tickers or config.load_universe()["ticker"].tolist()
    log.info("Descargando precios de %d tickers desde %s", len(tickers), start)
    df = yahoo.download_prices(tickers, start=start)
    if df.empty:
        raise RuntimeError("Yahoo Finance no devolvio precios; revisa conectividad o rate limit")
    written = storage.write_partitioned(df, config.PRICES_DIR, keys=["ticker", "date"], freq="M")
    log.info("Precios: %d filas, %d tickers, %d particiones escritas", len(df), df["ticker"].nunique(), len(written))
    return len(df)


def update_macro(start: str = config.DEFAULT_MACRO_START) -> int:
    series = config.load_macro_series()
    fred_ids = series.loc[series["source"] == "FRED", "series_id"].tolist()
    bmx_ids = series.loc[series["source"] == "BANXICO", "series_id"].tolist()

    fred_df, fred_failed = fred.fetch_many(fred_ids, start)
    bmx_df, bmx_failed = banxico.fetch_many(bmx_ids, start)
    if fred_failed:
        log.warning("Series FRED sin datos: %s", fred_failed)
    if bmx_failed:
        log.warning("Series Banxico sin datos: %s", bmx_failed)

    frames = [f for f in (fred_df, bmx_df) if not f.empty]
    if not frames:
        raise RuntimeError("No se obtuvo ninguna serie macro")
    df = pd.concat(frames, ignore_index=True)
    written = storage.write_partitioned(df, config.MACRO_DIR, keys=["source", "series_id", "date"], freq="Y")
    log.info("Macro: %d observaciones, %d particiones escritas", len(df), len(written))
    return len(df)


def update_fundamentals() -> int:
    universe = config.load_universe()
    tickers = universe.loc[universe["asset_type"].isin(["stock", "fibra"]), "ticker"].tolist()
    df = yahoo.download_fundamentals(tickers)
    written = storage.write_partitioned(df, config.FUNDAMENTALS_DIR, keys=["ticker", "date"], freq="M")
    log.info("Fundamentales: %d emisoras, %d particiones escritas", len(df), len(written))
    return len(df)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pipeline de datos ECONOMICS")
    parser.add_argument("task", choices=["daily", "backfill", "prices", "macro", "fundamentals", "snapshots"])
    parser.add_argument("--start", help="Fecha inicial YYYY-MM-DD (precios)")
    parser.add_argument("--days", type=int, default=10, help="Dias hacia atras para 'prices'/'daily'")
    parser.add_argument("--tickers", help="Lista separada por comas (por defecto, todo el universo)")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    tickers = args.tickers.split(",") if args.tickers else None
    recent = (date.today() - timedelta(days=args.days)).isoformat()

    steps = []
    if args.task in ("daily", "prices"):
        steps.append(("prices", lambda: update_prices(args.start or recent, tickers)))
    if args.task == "backfill":
        steps.append(("prices", lambda: update_prices(args.start or config.DEFAULT_HISTORY_START, tickers)))
    if args.task in ("daily", "macro"):
        steps.append(("macro", update_macro))
    if args.task == "fundamentals":
        steps.append(("fundamentals", update_fundamentals))

    # Un paso que falla no impide guardar lo que los demas si obtuvieron.
    failed = []
    for name, step in steps:
        try:
            step()
        except Exception:  # noqa: BLE001
            log.exception("Fallo el paso %s", name)
            failed.append(name)

    # Los snapshots se regeneran siempre para que reflejen lo que acaba de cambiar.
    manifest = snapshots.build()
    log.info("Snapshots listos: %s", manifest["health"])
    if failed:
        log.error("Pasos con error: %s", failed)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
