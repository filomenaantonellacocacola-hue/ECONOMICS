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

# Unidades en las que un cambio % no tiene sentido (se reporta el cambio absoluto).
NO_PCT_UNITS = ("pct", "desv_std")

# Vistas macro agregadas: nombre -> (meses por periodo, inicio de periodo, etiqueta).
MACRO_AGG_VIEWS = {
    "macro_monthly": (1, "date_trunc('month', m.date)", "strftime(v.period, '%Y-%m')"),
    "macro_quarterly": (3, "date_trunc('quarter', m.date)", "year(v.period) || '-Q' || quarter(v.period)"),
    "macro_semiannual": (
        6,
        "make_date(year(m.date), CASE WHEN month(m.date) <= 6 THEN 1 ELSE 7 END, 1)",
        "year(v.period) || '-S' || CASE WHEN month(v.period) = 1 THEN 1 ELSE 2 END",
    ),
    "macro_annual": (12, "date_trunc('year', m.date)", "CAST(year(v.period) AS VARCHAR)"),
}


def macro_agg_sql(months: int, period_expr: str, label_expr: str) -> str:
    """SQL que agrega ``macro`` a periodos de ``months`` meses.

    - ``value`` usa la regla ``agg`` de ``config/macro_series.csv`` (``avg`` o ``last``).
    - Se omiten series cuya frecuencia nativa es mas gruesa que el periodo (p.ej. PIB en mensual).
    - ``is_partial`` marca periodos que aun no tienen todos sus datos publicados.
    - ``chg_*`` son cambios absolutos; ``pct_*`` son cambios % (solo para niveles e indices).
    """
    no_pct = ", ".join(f"'{u}'" for u in NO_PCT_UNITS)
    return f"""
        WITH s AS (
            SELECT source, series_id, name, category, units, frequency,
                   coalesce(nullif(agg, ''), 'avg') AS agg,
                   CASE frequency WHEN 'Q' THEN 3 WHEN 'M' THEN 1 ELSE 0 END AS native_months
            FROM macro_series
        ),
        cov AS (
            SELECT source, series_id, CAST(max(date) AS DATE) AS last_date FROM macro GROUP BY ALL
        ),
        g AS (
            SELECT m.source, m.series_id, CAST({period_expr} AS DATE) AS period,
                   arg_max(m.value, m.date) AS last, avg(m.value) AS avg,
                   min(m.value) AS min, max(m.value) AS max, count(*) AS n_obs
            FROM macro m
            GROUP BY ALL
        ),
        v AS (
            SELECT g.*, s.name, s.category, s.units, s.frequency, s.agg,
                   CASE WHEN s.agg = 'last' THEN g.last ELSE g.avg END AS value,
                   CAST(g.period + INTERVAL {months} MONTH - INTERVAL 1 DAY AS DATE) > CASE s.frequency
                       WHEN 'Q' THEN CAST(date_trunc('quarter', c.last_date) + INTERVAL 3 MONTH - INTERVAL 1 DAY AS DATE)
                       WHEN 'M' THEN last_day(c.last_date)
                       WHEN 'W' THEN CAST(c.last_date + INTERVAL 6 DAY AS DATE)
                       ELSE c.last_date
                   END AS is_partial
            FROM g
            JOIN s USING (source, series_id)
            JOIN cov c USING (source, series_id)
            WHERE s.native_months <= {months}
        )
        SELECT v.source, v.series_id, v.name, v.category, v.units, v.frequency, v.agg,
               v.period, {label_expr} AS period_label, v.is_partial, v.n_obs,
               v.value, v.last, v.avg, v.min, v.max,
               v.value - lag(v.value) OVER w AS chg_prev,
               CASE WHEN v.units NOT IN ({no_pct}) THEN 100 * (v.value / lag(v.value) OVER w - 1) END AS pct_prev,
               v.value - y.value AS chg_yoy,
               CASE WHEN v.units NOT IN ({no_pct}) THEN 100 * (v.value / y.value - 1) END AS pct_yoy
        FROM v
        LEFT JOIN v y
          ON y.source = v.source AND y.series_id = v.series_id
         AND y.period = CAST(v.period - INTERVAL 1 YEAR AS DATE)
        WINDOW w AS (PARTITION BY v.source, v.series_id ORDER BY v.period)
    """


for _name, _spec in MACRO_AGG_VIEWS.items():
    DERIVED_VIEWS[_name] = ("macro", macro_agg_sql(*_spec))


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

    # Resumenes para agentes (una fila por ticker / serie), si ya se generaron.
    for name in ("market_snapshot", "macro_snapshot"):
        path = data_dir / "snapshots" / f"{name}.csv"
        if path.exists():
            con.execute(f"CREATE VIEW {name} AS SELECT * FROM read_csv('{path}', header=true)")

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
