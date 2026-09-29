"""Consulta la base con SQL (DuckDB), al estilo BigQuery pero local y gratis.

Ejemplos::

    python -m econ.query "SELECT * FROM prices_latest WHERE market = 'BMV' ORDER BY chg_1d DESC LIMIT 10"
    python -m econ.query -f sql/curva_rendimientos.sql
    python -m econ.query --tables
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import duckdb
import pandas as pd

from econ import config

# Vistas derivadas: se crean solo si existen sus tablas base.
DERIVED_VIEWS = {
    "prices_latest": ("prices", """
        WITH p AS (
            SELECT ticker, date, close, adj_close, volume,
                   lag(adj_close) OVER (PARTITION BY ticker ORDER BY date) AS prev_adj_close,
                   row_number() OVER (PARTITION BY ticker ORDER BY date DESC) AS rn
            FROM prices
        )
        SELECT p.ticker, u.market, u.asset_type, u.name, p.date, p.close, p.volume,
               round(100 * (p.adj_close / p.prev_adj_close - 1), 2) AS chg_1d
        FROM p LEFT JOIN universe u USING (ticker)
        WHERE rn = 1
    """),
    "macro_latest": ("macro", """
        SELECT m.source, m.series_id, s.name, s.category, s.units, m.date, m.value
        FROM macro m LEFT JOIN macro_series s USING (source, series_id)
        QUALIFY row_number() OVER (PARTITION BY m.source, m.series_id ORDER BY m.date DESC) = 1
    """),
    "fundamentals_latest": ("fundamentals", """
        SELECT * FROM fundamentals
        QUALIFY row_number() OVER (PARTITION BY ticker ORDER BY date DESC) = 1
    """),
}


def connect(data_dir: Path | None = None, config_dir: Path | None = None) -> duckdb.DuckDBPyConnection:
    data_dir = Path(data_dir or config.DATA_DIR)
    config_dir = Path(config_dir or config.CONFIG_DIR)
    con = duckdb.connect()

    con.execute(
        f"CREATE VIEW universe AS SELECT * FROM read_csv('{config_dir / 'universe.csv'}', header=true, all_varchar=true)"
    )
    con.execute(
        f"CREATE VIEW macro_series AS SELECT * FROM read_csv('{config_dir / 'macro_series.csv'}', header=true, all_varchar=true)"
    )

    available = {"universe", "macro_series"}
    for name in ("prices", "macro", "fundamentals"):
        pattern = data_dir / name / "*" / "data.parquet"
        if any((data_dir / name).glob("*/data.parquet")):
            con.execute(f"CREATE VIEW {name} AS SELECT * FROM read_parquet('{pattern}', union_by_name=true)")
            available.add(name)

    for view, (base, sql) in DERIVED_VIEWS.items():
        if base in available:
            con.execute(f"CREATE VIEW {view} AS {sql}")
    return con


def run(sql: str, con: duckdb.DuckDBPyConnection | None = None) -> pd.DataFrame:
    con = con or connect()
    return con.execute(sql).df()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Consulta SQL sobre la base ECONOMICS")
    parser.add_argument("sql", nargs="?", help="Consulta SQL")
    parser.add_argument("-f", "--file", help="Archivo .sql a ejecutar")
    parser.add_argument("--format", choices=["table", "csv"], default="table")
    parser.add_argument("--tables", action="store_true", help="Lista tablas/vistas disponibles")
    args = parser.parse_args(argv)

    con = connect()
    if args.tables:
        sql = "SELECT table_name FROM information_schema.tables ORDER BY 1"
    elif args.file:
        sql = Path(args.file).read_text()
    elif args.sql:
        sql = args.sql
    else:
        parser.error("Indica una consulta, -f archivo.sql o --tables")

    df = run(sql, con)
    if args.format == "csv":
        df.to_csv(sys.stdout, index=False)
    else:
        with pd.option_context("display.max_rows", 200, "display.max_columns", 50, "display.width", 200):
            print(df.to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
