"""Orquestador del pipeline de datos.

Uso::

    python -m econ.pipeline daily                       # precios recientes + macro + snapshots
    python -m econ.pipeline backfill --start 2015-01-01 # historico completo + macro + limpieza
    python -m econ.pipeline prices --days 10
    python -m econ.pipeline macro
    python -m econ.pipeline fundamentals
    python -m econ.pipeline snapshots
    python -m econ.pipeline resolve                     # corrige claves del SIC sin datos
    python -m econ.pipeline banxico-search --query "agregado monetario;M4"  # busca claves en el SIE
"""
from __future__ import annotations

import argparse
import json
import logging
import re
from datetime import date, timedelta

import pandas as pd

from econ import config, resolve, snapshots, storage
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


def history_start() -> str:
    """Fecha inicial del historico ya guardado (o la de por defecto si no hay datos)."""
    files = sorted(config.PRICES_DIR.glob(f"*/{storage.FILE_NAME}"))
    if not files:
        return config.DEFAULT_HISTORY_START
    return pd.read_parquet(files[0], columns=["date"])["date"].min().date().isoformat()


def tickers_without_data(tickers: list[str]) -> list[str]:
    have: set[str] = set()
    for path in config.PRICES_DIR.glob(f"*/{storage.FILE_NAME}"):
        have.update(pd.read_parquet(path, columns=["ticker"])["ticker"].unique())
    return [t for t in tickers if t not in have]


def update_daily_prices(start: str) -> int:
    """Precios recientes de todo el universo, mas el historico completo de los tickers nuevos."""
    tickers = config.load_universe()["ticker"].tolist()
    new = tickers_without_data(tickers)
    rows = update_prices(start, tickers)
    if new:
        log.info("Tickers nuevos (o sin datos): %s", new)
        try:
            rows += update_prices(history_start(), new)
        except RuntimeError:
            log.warning("Sin historico para los tickers nuevos; revisa health.tickers_missing")
    return rows


def prune_to_universe() -> None:
    """Quita de precios y fundamentales los tickers que ya no estan en config/universe.csv."""
    keep = set(config.load_universe()["ticker"])
    if len(keep) < 10:
        raise RuntimeError(f"Universo sospechosamente chico ({len(keep)} tickers); no se limpia nada")
    for root in (config.PRICES_DIR, config.FUNDAMENTALS_DIR):
        changed = storage.prune(root, "ticker", keep)
        log.info("Limpieza de %s: %d particiones modificadas", root.name, len(changed))


def resolve_symbols() -> int:
    """Busca la clave correcta de las emisoras del SIC sin datos o desactualizadas."""
    universe = config.load_universe()
    # Primero se intenta cada ticker sin datos tal cual; solo los que sigan fallando se resuelven.
    missing = tickers_without_data(universe["ticker"].tolist())
    if missing:
        try:
            update_prices(history_start(), missing)
        except RuntimeError:
            log.info("Ningun ticker sin datos respondio con su clave actual")
    prices = storage.read_dataset(config.PRICES_DIR)
    health = snapshots.health(prices, pd.DataFrame(), universe, config.load_macro_series())
    targets = health.get("tickers_missing", []) + health.get("tickers_stale", [])
    report = resolve.resolve(targets, universe)
    config.SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    (config.SNAPSHOTS_DIR / "symbol_resolution.json").write_text(json.dumps(report, indent=2))
    log.info("Resolucion de claves: %d corregidas, %d con precio distinto, %d sin datos",
             len(report["resolved"]), len(report["mismatch"]), len(report["not_found"]))
    new = resolve.apply(report)
    if new:
        update_prices(history_start(), new)
    prune_to_universe()
    return len(new)


def banxico_search(queries: list[str]) -> int:
    """Busca claves de series en el catalogo de Banxico y deja el resultado en snapshots."""
    result = banxico.search_catalog(queries)
    config.SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    path = config.SNAPSHOTS_DIR / "banxico_search.json"
    path.write_text(json.dumps(result, indent=2, ensure_ascii=False))
    log.info("Busqueda en Banxico: %s -> %s", {q: len(v) for q, v in result.items()}, path)
    return sum(len(v) for v in result.values())


def apply_scale(df: pd.DataFrame, series: pd.DataFrame) -> pd.DataFrame:
    """Multiplica cada serie por su ``scale`` del catalogo (p.ej. miles de pesos -> miles de millones)."""
    scale = {(r.source, r.series_id): float(r.scale) for r in series.itertuples() if r.scale not in ("", "1")}
    if not scale:
        return df
    df = df.copy()
    factor = [scale.get(k, 1.0) for k in zip(df["source"], df["series_id"])]
    df["value"] = df["value"] * factor
    return df


FORMULA_TERM = re.compile(r"([+-])\s*([A-Za-z0-9_.=^]+)")


def derived_series(df: pd.DataFrame, series: pd.DataFrame) -> pd.DataFrame:
    """Calcula las series con source=CALC a partir de su ``formula`` (sumas y restas de otras series)."""
    out = []
    wide = df.pivot_table(index="date", columns="series_id", values="value", aggfunc="last")
    for r in series[series["source"] == "CALC"].itertuples():
        formula = r.formula.replace(" ", "")
        if formula and formula[0] not in "+-":
            formula = "+" + formula
        terms = FORMULA_TERM.findall(formula)
        if "".join(s + t for s, t in terms) != formula:
            log.warning("Formula invalida para %s: %r", r.series_id, r.formula)
            continue
        missing = [sid for _, sid in terms if sid not in wide.columns]
        if not terms or missing:
            log.warning("No se pudo calcular %s: faltan %s", r.series_id, missing or "terminos")
            continue
        parts = [wide[sid] * (1 if sign == "+" else -1) for sign, sid in terms]
        value = pd.concat(parts, axis=1).dropna().sum(axis=1)
        out.append(pd.DataFrame({"source": "CALC", "series_id": r.series_id, "date": value.index, "value": value.values}))
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame(columns=["source", "series_id", "date", "value"])


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
    df = apply_scale(pd.concat(frames, ignore_index=True), series)
    df = pd.concat([df, derived_series(df, series)], ignore_index=True)
    written = storage.write_partitioned(df, config.MACRO_DIR, keys=["source", "series_id", "date"], freq="Y")
    log.info("Macro: %d observaciones, %d particiones escritas", len(df), len(written))
    return len(df)


def update_fundamentals() -> int:
    universe = config.load_universe()
    stocks = universe[universe["asset_type"].isin(["stock", "fibra"])]
    symbols = dict(zip(stocks["ticker"], stocks["ref_ticker"].where(stocks["ref_ticker"] != "", stocks["ticker"])))
    df = yahoo.download_fundamentals(symbols)
    written = storage.write_partitioned(df, config.FUNDAMENTALS_DIR, keys=["ticker", "date"], freq="M")
    log.info("Fundamentales: %d emisoras, %d particiones escritas", len(df), len(written))
    return len(df)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pipeline de datos ECONOMICS")
    parser.add_argument(
        "task",
        choices=["daily", "backfill", "prices", "macro", "fundamentals", "snapshots", "resolve", "banxico-search"],
    )
    parser.add_argument("--start", help="Fecha inicial YYYY-MM-DD (precios)")
    parser.add_argument("--days", type=int, default=10, help="Dias hacia atras para 'prices'/'daily'")
    parser.add_argument("--tickers", help="Lista separada por comas (por defecto, todo el universo)")
    parser.add_argument("--query", default="agregado monetario",
                        help="banxico-search: texto a buscar; varias consultas separadas por ';'")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    tickers = args.tickers.split(",") if args.tickers else None
    recent = (date.today() - timedelta(days=args.days)).isoformat()

    steps = []
    if args.task == "daily":
        steps.append(("prices", lambda: update_daily_prices(args.start or recent)))
    if args.task == "prices":
        steps.append(("prices", lambda: update_prices(args.start or recent, tickers)))
    if args.task == "backfill":
        steps.append(("prices", lambda: update_prices(args.start or config.DEFAULT_HISTORY_START, tickers)))
    if args.task in ("daily", "backfill", "macro"):
        steps.append(("macro", update_macro))
    if args.task == "backfill" and not tickers:
        steps.append(("prune", prune_to_universe))
    if args.task == "fundamentals":
        steps.append(("fundamentals", update_fundamentals))
    if args.task == "resolve":
        steps.append(("resolve", resolve_symbols))
    if args.task == "banxico-search":
        queries = [q.strip() for q in args.query.split(";") if q.strip()]
        steps.append(("banxico-search", lambda: banxico_search(queries)))

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
