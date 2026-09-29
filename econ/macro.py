"""Consultas macro por periodo, pensadas para el agente ``analista-macro``.

Incluye las series de FRED y Banxico mas los indices y tipos de cambio de ``prices``
(IPC, S&P 500, VIX, USD/MXN...), todo con el mismo formato.

Ejemplos::

    python -m econ.macro panel                          # ultimo dato y cambios 1d/1s/1m/YTD/1a
    python -m econ.macro panel --date 2026-03-31        # igual, a una fecha
    python -m econ.macro change --period ytd            # cambio en el periodo
    python -m econ.macro change --period last-week --category tasas
    python -m econ.macro change --period 2026-03 --series CPIAUCSL,SP1
    python -m econ.macro series DGS10,SF61745 --freq M --from 2025-01-01
    python -m econ.macro list

Periodos (``--period``): today, yesterday, wtd, last-week, mtd, last-month, qtd,
last-quarter, ytd, last-year, 1w, 1m, 3m, 6m, 1y, YYYY, YYYY-MM, YYYY-Qn, YYYY-Sn,
YYYY-Www (semana ISO), YYYY-MM-DD o FECHA1:FECHA2.
"""
from __future__ import annotations

import argparse
import re
import sys
from datetime import date, timedelta
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from econ import query

MARKET_SOURCE = "MERCADO"
# Unidades que se comparan en puntos (pp o absolutos) en lugar de en %.
POINT_UNITS = set(query.NO_PCT_UNITS)
FREQS = {"D", "W", "M", "Q", "S", "A"}
AGG_VIEWS = {"M": "macro_monthly", "Q": "macro_quarterly", "S": "macro_semiannual", "A": "macro_annual"}


# --------------------------------------------------------------------------- datos

def load(data_dir: Path | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Devuelve (observaciones, catalogo) de macro + indices/FX de mercado."""
    con = query.connect(data_dir=data_dir)
    tables = set(con.execute("SELECT table_name FROM information_schema.tables").df()["table_name"])
    frames = []
    if "macro" in tables:
        frames.append(con.execute("SELECT source, series_id, CAST(date AS DATE) AS date, value FROM macro").df())
    meta = con.execute(
        "SELECT source, series_id, name, category, units, frequency, coalesce(nullif(agg, ''), 'avg') AS agg "
        "FROM macro_series"
    ).df()
    if "prices" in tables:
        frames.append(con.execute(f"""
            SELECT '{MARKET_SOURCE}' AS source, p.ticker AS series_id, CAST(p.date AS DATE) AS date, p.close AS value
            FROM prices p JOIN universe u USING (ticker)
            WHERE u.market IN ('INDEX', 'FX')
        """).df())
        market = con.execute(f"""
            SELECT '{MARKET_SOURCE}' AS source, ticker AS series_id, name,
                   CASE market WHEN 'FX' THEN 'divisas' ELSE 'mercado' END AS category,
                   CASE market WHEN 'FX' THEN 'fx' ELSE 'indice' END AS units,
                   'D' AS frequency, 'last' AS agg
            FROM universe WHERE market IN ('INDEX', 'FX')
        """).df()
        meta = pd.concat([meta, market], ignore_index=True)
    obs = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=["source", "series_id", "date", "value"])
    obs["date"] = pd.to_datetime(obs["date"])
    return obs.sort_values(["source", "series_id", "date"]).reset_index(drop=True), meta


def select(meta: pd.DataFrame, series: str | None = None, category: str | None = None,
           source: str | None = None) -> pd.DataFrame:
    out = meta
    if series:
        wanted = [s.strip().upper() for s in series.split(",") if s.strip()]
        out = out[out["series_id"].str.upper().isin(wanted)]
        missing = set(wanted) - set(out["series_id"].str.upper())
        if missing:
            raise SystemExit(f"Series desconocidas: {sorted(missing)}. Usa 'python -m econ.macro list'.")
    if category:
        out = out[out["category"].isin([c.strip() for c in category.split(",")])]
    if source:
        out = out[out["source"].str.upper().isin([s.strip().upper() for s in source.split(",")])]
    return out


# ------------------------------------------------------------------------ periodos

def _prev_weekday(d: date) -> date:
    d -= timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def _quarter_start(d: date) -> date:
    return date(d.year, 3 * ((d.month - 1) // 3) + 1, 1)


def _month_end(y: int, m: int) -> date:
    return (date(y + m // 12, m % 12 + 1, 1)) - timedelta(days=1)


def resolve_period(spec: str, today: date) -> tuple[date, date, str]:
    """Convierte un periodo a (inicio, fin, etiqueta). El fin nunca pasa de ``today``."""
    s = spec.strip().lower()
    monday = today - timedelta(days=today.weekday())
    q0 = _quarter_start(today)
    rel = {"1w": 7, "1m": 30, "3m": 91, "6m": 182, "1y": 365}
    if s in ("today", "hoy"):
        start = end = today
    elif s in ("yesterday", "ayer"):
        start = end = _prev_weekday(today)
    elif s in ("wtd", "week", "semana"):
        start, end = monday, today
    elif s in ("last-week", "semana-pasada"):
        start, end = monday - timedelta(days=7), monday - timedelta(days=1)
    elif s in ("mtd", "month", "mes"):
        start, end = today.replace(day=1), today
    elif s in ("last-month", "mes-pasado"):
        end = today.replace(day=1) - timedelta(days=1)
        start = end.replace(day=1)
    elif s in ("qtd", "quarter", "trimestre"):
        start, end = q0, today
    elif s in ("last-quarter", "trimestre-pasado"):
        end = q0 - timedelta(days=1)
        start = _quarter_start(end)
    elif s in ("ytd",):
        start, end = date(today.year, 1, 1), today
    elif s in ("last-year", "anio-pasado"):
        start, end = date(today.year - 1, 1, 1), date(today.year - 1, 12, 31)
    elif s in rel:
        start, end = today - timedelta(days=rel[s]) + timedelta(days=1), today
    elif ":" in s:
        a, b = s.split(":", 1)
        start, end = date.fromisoformat(a), date.fromisoformat(b)
    elif m := re.fullmatch(r"(\d{4})", s):
        y = int(m[1])
        start, end = date(y, 1, 1), date(y, 12, 31)
    elif m := re.fullmatch(r"(\d{4})-(\d{2})", s):
        y, mo = int(m[1]), int(m[2])
        start, end = date(y, mo, 1), _month_end(y, mo)
    elif m := re.fullmatch(r"(\d{4})-q([1-4])", s):
        y, q = int(m[1]), int(m[2])
        start, end = date(y, 3 * q - 2, 1), _month_end(y, 3 * q)
    elif m := re.fullmatch(r"(\d{4})-s([12])", s):
        y, h = int(m[1]), int(m[2])
        start, end = date(y, 6 * h - 5, 1), _month_end(y, 6 * h)
    elif m := re.fullmatch(r"(\d{4})-w(\d{1,2})", s):
        start = date.fromisocalendar(int(m[1]), int(m[2]), 1)
        end = start + timedelta(days=6)
    elif re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        start = end = date.fromisoformat(s)
    else:
        raise SystemExit(f"Periodo no reconocido: {spec!r}")
    if start > today:
        raise SystemExit(f"El periodo {spec!r} empieza en el futuro ({start})")
    end = min(end, today)
    return start, end, f"{start.isoformat()} a {end.isoformat()}"


# ---------------------------------------------------------------------- calculos

def _delta(new: float, old: float, units: str) -> float:
    if pd.isna(new) or pd.isna(old):
        return np.nan
    if units in POINT_UNITS:
        return new - old
    return 100 * (new / old - 1) if old else np.nan


def _kind(units: str) -> str:
    return {"pct": "pp", "desv_std": "abs"}.get(units, "%")


def _value_at(g: pd.DataFrame, when: pd.Timestamp, strict: bool = False) -> tuple[pd.Timestamp | None, float]:
    """Ultima observacion en ``when`` o antes (``strict``: estrictamente antes)."""
    sub = g[g["date"] < when] if strict else g[g["date"] <= when]
    if sub.empty:
        return None, np.nan
    row = sub.iloc[-1]
    return row["date"], row["value"]


def panel(obs: pd.DataFrame, meta: pd.DataFrame, as_of: date, decimals: int | None = 3) -> pd.DataFrame:
    """Ultimo dato a ``as_of`` y cambios contra dato previo, 1 semana, 1 mes, YTD y 1 anio."""
    t = pd.Timestamp(as_of)
    rows = []
    for m in meta.itertuples():
        g = obs[(obs["source"] == m.source) & (obs["series_id"] == m.series_id)]
        d, v = _value_at(g, t)
        if d is None:
            continue
        _, prev = _value_at(g, d, strict=True)
        refs = {
            "d_1w": _value_at(g, t - pd.Timedelta(days=7))[1],
            "d_1m": _value_at(g, t - pd.DateOffset(months=1))[1],
            "d_ytd": _value_at(g, pd.Timestamp(as_of.year, 1, 1), strict=True)[1],
            "d_1y": _value_at(g, t - pd.DateOffset(years=1))[1],
        }
        rows.append({
            "source": m.source, "series_id": m.series_id, "name": m.name, "units": m.units,
            "date": d.date().isoformat(), "value": v, "d_prev": _delta(v, prev, m.units),
            **{k: _delta(v, ref, m.units) for k, ref in refs.items()}, "tipo": _kind(m.units),
        })
    return _round(pd.DataFrame(rows), decimals)


def change(obs: pd.DataFrame, meta: pd.DataFrame, start: date, end: date, decimals: int | None = 3) -> pd.DataFrame:
    """Cambio de cada serie en [start, end]: ultimo dato antes del periodo vs ultimo dato del periodo."""
    t0, t1 = pd.Timestamp(start), pd.Timestamp(end)
    rows = []
    for m in meta.itertuples():
        g = obs[(obs["source"] == m.source) & (obs["series_id"] == m.series_id)]
        bd, bv = _value_at(g, t0, strict=True)
        ed, ev = _value_at(g, t1)
        within = g[(g["date"] >= t0) & (g["date"] <= t1)]["value"]
        if ed is None:
            continue
        rows.append({
            "source": m.source, "series_id": m.series_id, "name": m.name, "units": m.units,
            "base_date": bd.date().isoformat() if bd is not None else None, "base_value": bv,
            "end_date": ed.date().isoformat(), "end_value": ev,
            "cambio": _delta(ev, bv, m.units) if len(within) else np.nan, "tipo": _kind(m.units),
            "min": within.min() if len(within) else np.nan,
            "max": within.max() if len(within) else np.nan,
            "n_obs": int(len(within)),
            # Sin observaciones dentro del periodo: el "fin" es el ultimo dato previo publicado.
            "sin_datos_en_periodo": len(within) == 0,
        })
    return _round(pd.DataFrame(rows), decimals)


def series(obs: pd.DataFrame, meta: pd.DataFrame, start: date, end: date, freq: str,
           decimals: int | None = 3) -> pd.DataFrame:
    """Evolucion de una o varias series en frecuencia D, W (cierre semanal), M, Q, S o A."""
    t0, t1 = pd.Timestamp(start), pd.Timestamp(end)
    keys = set(zip(meta["source"], meta["series_id"]))
    sub = obs[[k in keys for k in zip(obs["source"], obs["series_id"])]]
    if freq in AGG_VIEWS:
        con = duckdb.connect()
        con.register("macro", sub)
        con.register("macro_series", meta)
        sql = query.macro_agg_sql(*query.MACRO_AGG_VIEWS[AGG_VIEWS[freq]])
        df = con.execute(f"""
            SELECT series_id, name, units, agg, period_label AS periodo, is_partial AS parcial, n_obs,
                   value, chg_prev, pct_prev, chg_yoy, pct_yoy
            FROM ({sql}) v
            WHERE period <= DATE '{t1.date()}'
              AND period + INTERVAL {query.MACRO_AGG_VIEWS[AGG_VIEWS[freq]][0]} MONTH > DATE '{t0.date()}'
            ORDER BY series_id, period
        """).df()
        return _round(df, decimals)

    rows = []
    for m in meta.itertuples():
        g = sub[(sub["source"] == m.source) & (sub["series_id"] == m.series_id)].set_index("date")["value"]
        if freq == "W":
            # Cierre de cada semana (lun-dom) con la fecha de su ultimo dato real.
            g = g.groupby(g.index.to_period("W-SUN")).tail(1)
        prev = g.shift(1)
        g, prev = g[(g.index >= t0) & (g.index <= t1)], prev[(prev.index >= t0) & (prev.index <= t1)]
        for d, v in g.items():
            rows.append({"series_id": m.series_id, "name": m.name, "units": m.units,
                         "date": d.date().isoformat(), "value": v,
                         "cambio": _delta(v, prev[d], m.units), "tipo": _kind(m.units)})
    return _round(pd.DataFrame(rows), decimals)


def _round(df: pd.DataFrame, decimals: int | None = 3) -> pd.DataFrame:
    """Redondea para mostrar en terminal; ``decimals=None`` conserva la precision (graficas)."""
    if df.empty or decimals is None:
        return df
    num = df.select_dtypes("number").columns.drop("n_obs", errors="ignore")
    df[num] = df[num].round(decimals)
    return df


def freshness(obs: pd.DataFrame) -> str:
    if obs.empty:
        return "Sin datos: corre el pipeline."
    last = obs.groupby("source")["date"].max().dt.date
    return "Ultimo dato por fuente: " + ", ".join(f"{s} {d}" for s, d in last.items())


# ---------------------------------------------------------------------------- CLI

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Consultas macro por periodo")
    sub = parser.add_subparsers(dest="cmd", required=True)
    filters = argparse.ArgumentParser(add_help=False)
    filters.add_argument("--series", help="IDs separados por coma (p.ej. DGS10,SF61745,MXN=X)")
    filters.add_argument("--category", help="politica_monetaria, tasas, inflacion, empleo, actividad, riesgo, divisas, materias_primas, mercado")
    filters.add_argument("--source", help="FRED, BANXICO o MERCADO")
    filters.add_argument("--format", choices=["table", "csv"], default="table")
    filters.add_argument("--today", help=argparse.SUPPRESS)

    sub.add_parser("list", parents=[filters], help="Catalogo de series")
    p = sub.add_parser("panel", parents=[filters], help="Ultimo dato y cambios a una fecha")
    p.add_argument("--date", help="Fecha de corte YYYY-MM-DD (por defecto hoy)")
    c = sub.add_parser("change", parents=[filters], help="Cambio en un periodo")
    c.add_argument("--period", required=True)
    s = sub.add_parser("series", parents=[filters], help="Evolucion de series")
    s.add_argument("ids", help="IDs separados por coma")
    s.add_argument("--from", dest="start", help="YYYY-MM-DD (por defecto, 1 anio atras)")
    s.add_argument("--to", dest="end", help="YYYY-MM-DD (por defecto hoy)")
    s.add_argument("--period", help="Alternativa a --from/--to (mismos formatos que change)")
    s.add_argument("--freq", default="D", choices=sorted(FREQS))
    args = parser.parse_args(argv)

    today = date.fromisoformat(args.today) if args.today else date.today()
    obs, meta = load()
    meta = select(meta, args.series if args.cmd != "series" else args.ids, args.category, args.source)

    if args.cmd == "list":
        df, header = meta, f"{len(meta)} series"
    elif args.cmd == "panel":
        as_of = date.fromisoformat(args.date) if args.date else today
        df, header = panel(obs, meta, as_of), f"Panel al {as_of}"
    elif args.cmd == "change":
        start, end, label = resolve_period(args.period, today)
        df, header = change(obs, meta, start, end), f"Cambio {args.period}: {label}"
    else:
        if args.period:
            start, end, _ = resolve_period(args.period, today)
        else:
            end = date.fromisoformat(args.end) if args.end else today
            start = date.fromisoformat(args.start) if args.start else end - timedelta(days=365)
        df, header = series(obs, meta, start, end, args.freq), f"Serie {args.freq} {start} a {end}"

    print(f"# {header}. {freshness(obs)}. Hoy: {today}.")
    print("# tipo: % = cambio porcentual, pp = puntos porcentuales, abs = diferencia absoluta.")
    if df.empty:
        print("(sin resultados)")
    elif args.format == "csv":
        df.to_csv(sys.stdout, index=False)
    else:
        with pd.option_context("display.max_rows", 500, "display.max_columns", 50, "display.width", 250):
            print(df.to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
