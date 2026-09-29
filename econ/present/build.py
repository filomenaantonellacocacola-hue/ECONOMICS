"""Presentador: convierte una especificacion JSON en un artifact HTML interactivo.

El estilo es fijo (``assets/theme.css`` + ``assets/app.js``): la especificacion solo dice
QUE mostrar (datos, titulos, texto) y cualquier clave de estilo se rechaza. Los datos se
resuelven desde el repo (series macro, tickers, SQL), asi el agente no copia numeros a mano.
"""
from __future__ import annotations

import difflib
import html
import json
import math
import re
import unicodedata
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from econ import config, macro, query

ASSETS = Path(__file__).parent / "assets"
THEME_VERSION = "1"
LW_URL = "https://cdn.jsdelivr.net/npm/lightweight-charts@4.2.3/dist/lightweight-charts.standalone.production.js"
ECHARTS_URL = "https://cdn.jsdelivr.net/npm/echarts@5.6.0/dist/echarts.min.js"
FONTS_URL = ("https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600"
             "&family=IBM+Plex+Sans:wght@400;500;600&display=swap")

TIME_KINDS = {"line", "area", "candles", "histogram", "baseline"}
CAT_KINDS = {"bar", "hbar", "curve"}
MAX_SERIES = {"line": 6, "area": 3, "candles": 1, "histogram": 1, "baseline": 1, "bar": 4, "hbar": 2, "curve": 4}
N_SLOTS = 6
MAX_CATEGORIES = 40
MAX_TABLE_ROWS = 500
RANGE_DAYS = {"1M": 31, "3M": 92, "6M": 183, "YTD": 0, "1A": 366, "3A": 3 * 366, "5A": 5 * 366, "10A": 10 * 366}
AGG_FIELDS = {"value", "pct_yoy", "chg_yoy", "pct_prev", "chg_prev"}
DELTAS = {"prev": "d_prev", "1d": "d_prev", "1w": "d_1w", "1m": "d_1m", "ytd": "d_ytd", "1y": "d_1y"}
DELTA_LABELS = {"prev": "vs dato previo", "1d": "vs día previo", "1w": "en 1 semana", "1m": "en 1 mes",
                "ytd": "en el año", "1y": "en 1 año"}
FORMATS = {"text", "num", "int", "pct", "pp", "chg", "chgpp", "mxn", "usd", "fx", "compact", "date"}
UNIT_CODES = {"pct", "pp", "mxn", "usd", "fx", "num", "compact"}
FREQ_LABELS = {"D": "Diario", "W": "Semanal", "M": "Mensual", "Q": "Trimestral", "S": "Semestral", "A": "Anual"}
MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]

# Unidades del catalogo -> codigo de formato y rotulo legible.
RAW_UNITS = {
    "pct": ("pct", "%"), "pp": ("pp", "puntos porcentuales"), "indice": ("num", "índice"),
    "fx": ("fx", "MXN por unidad"), "mxn_por_usd": ("fx", "MXN por USD"), "usd_barril": ("usd", "USD por barril"),
    "millones_usd": ("compact", "millones de USD"), "miles_millones_usd": ("compact", "miles de millones de USD"),
    "miles": ("compact", "miles"), "personas": ("compact", "personas"), "desv_std": ("num", "desviaciones estándar"),
    "mxn": ("mxn", "MXN"), "pts": ("num", "puntos"), "num": ("num", ""), "usd": ("usd", "USD"), "compact": ("compact", ""),
}
SOURCE_NAMES = {"FRED": "FRED", "BANXICO": "Banxico", "MERCADO": "Yahoo Finance"}

ALLOWED = {
    "doc": {"title", "subtitle", "description", "sources", "blocks", "file"},
    "kpis": {"type", "items"},
    "kpi": {"label", "macro", "ticker", "delta", "as_of", "value", "unit", "delta_value", "delta_unit", "note", "decimals"},
    "chart": {"type", "kind", "title", "subtitle", "note", "span", "series", "period", "from", "to", "range", "compare",
              "decimals", "markers", "hlines", "base", "polarity", "categories", "category_label", "sql", "sort",
              "labels", "points", "volume", "sma", "unit"},
    "series": {"label", "macro", "ticker", "sql", "data", "diff", "freq", "field", "values", "points", "as_of", "unit"},
    "operand": {"macro", "ticker", "sql", "data", "freq", "field", "unit"},
    "point": {"category", "macro", "ticker", "field", "freq"},
    "table": {"type", "title", "subtitle", "note", "span", "columns", "rows", "sql", "limit"},
    "column": {"key", "label", "format", "decimals"},
    "text": {"type", "title", "body", "span"},
    "marker": {"date", "text", "position"},
    "hline": {"value", "label"},
}


class SpecError(ValueError):
    """La especificacion no es valida; el mensaje dice como corregirla."""


# ------------------------------------------------------------------ utilidades

def esc(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _check_keys(obj: Any, kind: str, where: str) -> None:
    if not isinstance(obj, dict):
        raise SpecError(f"{where}: se esperaba un objeto JSON")
    bad = set(obj) - ALLOWED[kind]
    if bad:
        raise SpecError(f"{where}: claves no permitidas {sorted(bad)}. Permitidas: {sorted(ALLOWED[kind])}. "
                        "El estilo (colores, tamaños, fuentes) es fijo y no se configura.")


def _num(v: Any) -> float | None:
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _parse_date(v: Any, where: str) -> date:
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError as exc:
        raise SpecError(f"{where}: fecha inválida {v!r} (usa YYYY-MM-DD)") from exc


def fmt_date(d: date | str, freq: str = "D") -> str:
    d = date.fromisoformat(d[:10]) if isinstance(d, str) else d
    if freq == "M":
        return f"{MESES[d.month - 1]} {d.year}"
    if freq == "Q":
        return f"T{(d.month - 1) // 3 + 1} {d.year}"
    if freq == "S":
        return f"S{1 if d.month <= 6 else 2} {d.year}"
    if freq == "A":
        return str(d.year)
    return f"{d.day} {MESES[d.month - 1]} {d.year}"


def compact(v: float) -> str:
    a = abs(v)
    if a >= 1e12:
        return f"{v / 1e12:,.2f} B"
    if a >= 1e9:
        return f"{v / 1e9:,.2f} MM"
    if a >= 1e6:
        return f"{v / 1e6:,.2f} M"
    if a >= 1e3:
        return f"{v / 1e3:,.1f} K"
    return f"{v:,.0f}"


DEFAULT_DEC = {"pct": 2, "pp": 2, "mxn": 2, "usd": 2, "fx": 4, "num": 2}


def fmt(v: Any, unit: str = "num", dec: int | None = None) -> str:
    """Mismo formato que ``fmt`` en assets/app.js (es-MX: 1,234.56)."""
    f = _num(v)
    if f is None:
        return "—"
    d = DEFAULT_DEC.get(unit, 2) if dec is None else dec
    sign = "-" if f < 0 else ""
    a = abs(f)
    if unit == "pct":
        return f"{sign}{a:,.{d}f}%"
    if unit == "pp":
        return f"{sign}{a:,.{d}f} pp"
    if unit == "mxn":
        return f"{sign}${a:,.{d}f}"
    if unit == "usd":
        return f"{sign}US${a:,.{d}f}"
    if unit == "compact":
        return compact(f)
    return f"{sign}{a:,.{d}f}"


def signed(v: Any, unit: str, dec: int | None = None) -> str:
    f = _num(v)
    if f is None:
        return "—"
    return ("+" if f > 0 else "") + fmt(f, unit, dec)


def direction(v: Any) -> str:
    f = _num(v)
    return "flat" if f is None or f == 0 else ("up" if f > 0 else "down")


def slugify(text: str) -> str:
    t = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    t = re.sub(r"[^a-zA-Z0-9]+", "-", t).strip("-").lower()
    return t[:60] or "reporte"


def _label_to_date(label: str) -> str:
    if m := re.fullmatch(r"(\d{4})-(\d{2})", label):
        return f"{m[1]}-{m[2]}-01"
    if m := re.fullmatch(r"(\d{4})-Q([1-4])", label):
        return f"{m[1]}-{3 * int(m[2]) - 2:02d}-01"
    if m := re.fullmatch(r"(\d{4})-S([12])", label):
        return f"{m[1]}-{6 * int(m[2]) - 5:02d}-01"
    return f"{label}-01-01"


def _md(text: str) -> str:
    """Markdown minimo: parrafos, listas con '- ', **negritas** y `codigo`."""
    def inline(s: str) -> str:
        s = esc(s)
        s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
        return re.sub(r"`(.+?)`", r"<code>\1</code>", s)

    out = []
    for block in re.split(r"\n\s*\n", str(text).strip()):
        lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
        if lines and all(ln.startswith(("- ", "* ")) for ln in lines):
            out.append("<ul>" + "".join(f"<li>{inline(ln[2:])}</li>" for ln in lines) + "</ul>")
        elif lines:
            out.append(f"<p>{inline(' '.join(lines))}</p>")
    return "\n".join(out)


# ------------------------------------------------------------------ colores

class Palette:
    """Asigna a cada serie (por su rotulo) un color fijo en todo el documento; nunca se cicla."""

    def __init__(self) -> None:
        self.slots: dict[str, int] = {}

    def assign(self, labels: list[str]) -> list[int]:
        for label in labels:
            if label not in self.slots and len(self.slots) < N_SLOTS:
                self.slots[label] = len(self.slots)
        out: list[int | None] = [None] * len(labels)
        used: set[int] = set()
        for i, label in enumerate(labels):
            slot = self.slots.get(label)
            if slot is not None and slot not in used:
                out[i] = slot
                used.add(slot)
        for i in range(len(labels)):
            if out[i] is None:
                out[i] = min(set(range(N_SLOTS)) - used)
                used.add(out[i])
        return out


# ------------------------------------------------------------------ datos

class Resolver:
    """Resuelve fuentes de datos del repo para la especificacion."""

    def __init__(self, data_dir: Path | None = None, today: date | None = None) -> None:
        self.today = today or date.today()
        self.con = query.connect(data_dir=data_dir)
        self.obs, self.meta = macro.load(data_dir=data_dir)
        self.universe = self.con.execute("SELECT * FROM universe").df()
        tables = set(self.con.execute("SELECT table_name FROM information_schema.tables").df()["table_name"])
        self.has_prices = "prices" in tables
        self._px: dict[str, pd.DataFrame] = {}
        self.sources: set[str] = set()
        self.dates: list[date] = []

    # -- catalogos
    def macro_row(self, sid: str, where: str) -> pd.Series:
        hit = self.meta[self.meta["series_id"].str.upper() == str(sid).upper()]
        if hit.empty:
            close = difflib.get_close_matches(str(sid).upper(), self.meta["series_id"].str.upper().tolist(), n=3)
            raise SpecError(f"{where}: serie macro desconocida {sid!r}. Parecidas: {close}. Ver 'python -m econ.macro list'.")
        return hit.iloc[0]

    def ticker_row(self, ticker: str, where: str) -> pd.Series:
        hit = self.universe[self.universe["ticker"].str.upper() == str(ticker).upper()]
        if hit.empty:
            close = difflib.get_close_matches(str(ticker).upper(), self.universe["ticker"].str.upper().tolist(), n=3)
            raise SpecError(f"{where}: ticker desconocido {ticker!r}. Parecidos: {close}. Revisa config/universe.csv.")
        return hit.iloc[0]

    @staticmethod
    def ticker_unit(row: pd.Series) -> str:
        return {"BMV": "mxn", "SIC": "mxn", "FX": "fx", "INDEX": "pts"}.get(row["market"], "num")

    def prices(self, ticker: str) -> pd.DataFrame:
        if ticker not in self._px:
            if not self.has_prices:
                raise SpecError("No hay precios en data/prices; corre el pipeline.")
            df = self.con.execute(
                "SELECT CAST(date AS DATE) AS date, open, high, low, close, adj_close, volume "
                "FROM prices WHERE ticker = ? ORDER BY date", [ticker]).df()
            df["date"] = pd.to_datetime(df["date"])
            self._px[ticker] = df
        return self._px[ticker]

    def sql(self, sql: str, where: str) -> pd.DataFrame:
        try:
            df = self.con.execute(sql).df()
        except Exception as exc:  # noqa: BLE001 - error de DuckDB para el agente
            raise SpecError(f"{where}: error en SQL: {exc}") from exc
        lowered = sql.lower()
        if any(t in lowered for t in ("prices", "market_snapshot", "fundamentals", "universe")):
            self.sources.add("Yahoo Finance")
        if "macro" in lowered:
            self.sources.update({"FRED", "Banxico"})
        return df

    def _note(self, source: str, last: date | None) -> None:
        self.sources.add(SOURCE_NAMES.get(source, source))
        if last:
            self.dates.append(last)

    # -- ventana de tiempo
    def window(self, blk: dict, freq: str, kind: str, where: str) -> tuple[date, date]:
        if "period" in blk:
            try:
                start, end, _ = macro.resolve_period(str(blk["period"]), self.today)
            except SystemExit as exc:
                raise SpecError(f"{where}: {exc}") from exc
            return start, end
        end = _parse_date(blk["to"], where) if "to" in blk else self.today
        if "from" in blk:
            return _parse_date(blk["from"], where), end
        years = {"D": 3, "W": 5, "M": 10, "Q": 15, "S": 26, "A": 26}.get(freq, 3)
        if kind == "candles":
            years = 2
        return end - timedelta(days=int(365.25 * years)), end

    # -- series de tiempo
    def time_series(self, item: dict, start: date, end: date, where: str, kind: str = "series") -> dict:
        _check_keys(item, kind, where)
        sources = [k for k in ("macro", "ticker", "sql", "data", "diff") if k in item]
        if len(sources) != 1:
            raise SpecError(f"{where}: indica exactamente una fuente entre macro, ticker, sql, data o diff")
        src = sources[0]
        freq = str(item.get("freq", "D")).upper()
        field = item.get("field", "value" if src != "ticker" else "close")
        t0, t1 = pd.Timestamp(start), pd.Timestamp(end)

        if src == "macro":
            row = self.macro_row(item["macro"], where)
            if freq not in macro.FREQS:
                raise SpecError(f"{where}: freq {freq!r} inválida; usa D, W, M, Q, S o A")
            sel = self.meta[(self.meta["source"] == row["source"]) & (self.meta["series_id"] == row["series_id"])]
            df = macro.series(self.obs, sel, start, end, freq, decimals=None)
            if freq in ("D", "W"):
                if field != "value":
                    raise SpecError(f"{where}: field={field!r} solo aplica con freq M, Q, S o A")
                points = [(d, v) for d, v in zip(df.get("date", []), df.get("value", []))]
            else:
                if field not in AGG_FIELDS:
                    raise SpecError(f"{where}: field debe ser uno de {sorted(AGG_FIELDS)}")
                points = [(_label_to_date(p), v) for p, v in zip(df.get("periodo", []), df.get(field, []))]
            raw = row["units"]
            if field.startswith("pct"):
                raw = "pct"
            elif field.startswith("chg"):
                raw = "pp" if row["units"] == "pct" else row["units"]
            label = item.get("label") or row["name"]
            ident, source = row["series_id"], row["source"]
        elif src == "ticker":
            row = self.ticker_row(item["ticker"], where)
            if field not in ("close", "adj_close"):
                raise SpecError(f"{where}: con ticker, field debe ser close o adj_close")
            if freq not in ("D", "W"):
                raise SpecError(f"{where}: con ticker, freq debe ser D o W")
            px = self.prices(row["ticker"])
            s = px.set_index("date")[field]
            if freq == "W":
                s = s.groupby(s.index.to_period("W-SUN")).tail(1)
            s = s[(s.index >= t0) & (s.index <= t1)]
            points = [(d.date().isoformat(), v) for d, v in s.items()]
            raw = self.ticker_unit(row)
            label = item.get("label") or row["name"]
            ident, source = row["ticker"], "MERCADO"
        elif src == "sql":
            df = self.sql(item["sql"], where)
            if df.shape[1] < 2:
                raise SpecError(f"{where}: el SQL debe devolver (fecha, valor)")
            dates = pd.to_datetime(df.iloc[:, 0], errors="coerce")
            points = [(d.date().isoformat(), v) for d, v in zip(dates, df.iloc[:, 1])
                      if pd.notna(d) and t0 <= d <= t1]
            raw = item.get("unit", "num")
            label = item.get("label") or str(df.columns[1])
            ident, source = None, ""
        elif src == "data":
            if not isinstance(item["data"], list):
                raise SpecError(f"{where}: data debe ser una lista de [fecha, valor]")
            points = []
            for p in item["data"]:
                if not isinstance(p, (list, tuple)) or len(p) != 2:
                    raise SpecError(f"{where}: cada punto de data debe ser [fecha, valor]")
                d = _parse_date(p[0], where)
                if start <= d <= end:
                    points.append((d.isoformat(), p[1]))
            raw = item.get("unit", "num")
            label = item.get("label", "Serie")
            ident, source = None, ""
        else:  # diff
            ops = item["diff"]
            if not isinstance(ops, list) or len(ops) != 2:
                raise SpecError(f"{where}: diff debe ser una lista de dos fuentes [a, b] (resultado a - b)")
            a = self.time_series(ops[0], start, end, f"{where}.diff[0]", "operand")
            b = self.time_series(ops[1], start, end, f"{where}.diff[1]", "operand")
            sa = pd.Series({p[0]: p[1] for p in a["points"]}, dtype="float64")
            sb = pd.Series({p[0]: p[1] for p in b["points"]}, dtype="float64")
            idx = sa.index.union(sb.index)
            both = pd.DataFrame({"a": sa.reindex(idx).ffill(), "b": sb.reindex(idx).ffill()}).dropna()
            points = [(d, v) for d, v in (both["a"] - both["b"]).items()]
            raw = "pp" if a["raw_unit"] in ("pct", "pp") and b["raw_unit"] in ("pct", "pp") else a["raw_unit"]
            label = item.get("label") or "Diferencial"
            ident, source = None, ""
            freq = a["freq"]

        clean = []
        for d, v in points:
            f = _num(v)
            if f is not None:
                clean.append([str(d)[:10], round(f, 6)])
        clean.sort(key=lambda p: p[0])
        if kind != "operand" and not clean:
            raise SpecError(f"{where}: '{label}' no tiene datos entre {start} y {end}")
        if clean and source:
            self._note(source, date.fromisoformat(clean[-1][0]))
        unit_code, unit_label = RAW_UNITS.get(raw, ("num", raw))
        return {"label": label, "id": ident, "unit": unit_code, "unit_label": unit_label, "raw_unit": raw,
                "freq": freq, "points": clean}

    def candles(self, item: dict, start: date, end: date, volume: bool, where: str) -> dict:
        _check_keys(item, "series", where)
        if "ticker" not in item:
            raise SpecError(f"{where}: las velas requieren 'ticker'")
        row = self.ticker_row(item["ticker"], where)
        px = self.prices(row["ticker"])
        w = px[(px["date"] >= pd.Timestamp(start)) & (px["date"] <= pd.Timestamp(end))].copy()
        if w.empty:
            raise SpecError(f"{where}: {row['ticker']} no tiene precios entre {start} y {end}")
        for col in ("open", "high", "low"):
            w[col] = w[col].where(w[col] > 0, w["close"])
        w["high"] = w[["open", "high", "close"]].max(axis=1)
        w["low"] = w[["open", "low", "close"]].min(axis=1)
        ohlc = [[d.date().isoformat(), round(o, 6), round(h, 6), round(lo, 6), round(c, 6)]
                for d, o, h, lo, c in zip(w["date"], w["open"], w["high"], w["low"], w["close"])]
        vol = None
        if volume and (w["volume"] > 0).any():
            vol = [[d.date().isoformat(), int(v)] for d, v in zip(w["date"], w["volume"])]
        self._note("MERCADO", w["date"].iloc[-1].date())
        unit, unit_label = RAW_UNITS[self.ticker_unit(row)]
        return {"label": item.get("label") or row["name"], "id": row["ticker"], "unit": unit,
                "unit_label": unit_label, "ohlc": ohlc, "volume": vol}

    def sma(self, ticker: str, n: int, start: date, end: date) -> list:
        px = self.prices(ticker).set_index("date")["close"]
        s = px.rolling(n).mean()
        s = s[(s.index >= pd.Timestamp(start)) & (s.index <= pd.Timestamp(end))].dropna()
        return [[d.date().isoformat(), round(v, 6)] for d, v in s.items()]

    # -- valores puntuales
    def value_at(self, point: dict, as_of: date, where: str) -> tuple[float | None, str]:
        _check_keys(point, "point", where)
        if "macro" in point:
            row = self.macro_row(point["macro"], where)
            freq = str(point.get("freq", "D")).upper()
            field = point.get("field", "value")
            sel = self.meta[(self.meta["source"] == row["source"]) & (self.meta["series_id"] == row["series_id"])]
            if freq in ("D", "W"):
                g = self.obs[(self.obs["source"] == row["source"]) & (self.obs["series_id"] == row["series_id"])]
                g = g[g["date"] <= pd.Timestamp(as_of)]
                val = g["value"].iloc[-1] if len(g) else None
                last = g["date"].iloc[-1].date() if len(g) else None
            else:
                df = macro.series(self.obs, sel, date(2000, 1, 1), as_of, freq, decimals=None)
                df = df.dropna(subset=[field]) if field in df else df.iloc[0:0]
                val = df[field].iloc[-1] if len(df) else None
                last = date.fromisoformat(_label_to_date(df["periodo"].iloc[-1])) if len(df) else None
            raw = "pct" if field.startswith("pct") else ("pp" if field.startswith("chg") and row["units"] == "pct" else row["units"])
            self._note(row["source"], last)
            return _num(val), raw
        if "ticker" in point:
            row = self.ticker_row(point["ticker"], where)
            px = self.prices(row["ticker"])
            px = px[px["date"] <= pd.Timestamp(as_of)]
            self._note("MERCADO", px["date"].iloc[-1].date() if len(px) else None)
            return (_num(px["close"].iloc[-1]) if len(px) else None), self.ticker_unit(row)
        raise SpecError(f"{where}: cada punto necesita 'macro' o 'ticker'")


def _as_of(v: Any, today: date, where: str) -> date:
    if v in (None, "", "today", "hoy"):
        return today
    if m := re.fullmatch(r"-(\d+)([dwmy])", str(v).lower()):
        n, u = int(m[1]), m[2]
        if u == "d":
            return today - timedelta(days=n)
        if u == "w":
            return today - timedelta(weeks=n)
        offset = pd.DateOffset(months=n) if u == "m" else pd.DateOffset(years=n)
        return (pd.Timestamp(today) - offset).date()
    return _parse_date(v, where)


# ------------------------------------------------------------------ bloques

class Builder:
    def __init__(self, resolver: Resolver) -> None:
        self.r = resolver
        self.palette = Palette()
        self.charts: dict[str, dict] = {}
        self.summary: list[str] = []
        self.needs_time = False
        self.needs_cat = False

    # -- KPIs
    def kpis(self, blk: dict, where: str) -> str:
        _check_keys(blk, "kpis", where)
        items = blk.get("items")
        if not isinstance(items, list) or not 1 <= len(items) <= 8:
            raise SpecError(f"{where}: items debe ser una lista de 1 a 8 indicadores")
        cells = [self.kpi(it, f"{where}.items[{i}]") for i, it in enumerate(items)]
        self.summary.append(f"kpis({len(cells)})")
        return f'<section class="kpis span-full" aria-label="Indicadores">{"".join(cells)}</section>'

    def kpi(self, it: dict, where: str) -> str:
        _check_keys(it, "kpi", where)
        if "label" not in it:
            raise SpecError(f"{where}: falta 'label'")
        dec = it.get("decimals")
        delta_key = str(it.get("delta", "1d" if "ticker" in it else "prev")).lower()
        if ("macro" in it or "ticker" in it) and delta_key not in DELTAS:
            raise SpecError(f"{where}: delta debe ser uno de {sorted(DELTAS)}")
        as_of = _as_of(it.get("as_of"), self.r.today, where)
        meta_parts = []
        if "macro" in it or "ticker" in it:
            if "macro" in it:
                row = self.r.macro_row(it["macro"], where)
                sel = self.r.meta[(self.r.meta["source"] == row["source"]) & (self.r.meta["series_id"] == row["series_id"])]
                p = macro.panel(self.r.obs, sel, as_of, decimals=None)
                source, raw = row["source"], row["units"]
                shown_value = None
            else:
                row = self.r.ticker_row(it["ticker"], where)
                px = self.r.prices(row["ticker"])
                obs = pd.DataFrame({"source": "TICKER", "series_id": row["ticker"], "date": px["date"],
                                    "value": px["adj_close"].fillna(px["close"])})
                sel = pd.DataFrame([{"source": "TICKER", "series_id": row["ticker"], "name": row["name"],
                                     "units": "px", "category": "", "frequency": "D", "agg": "last"}])
                p = macro.panel(obs, sel, as_of, decimals=None)
                source, raw = "MERCADO", self.r.ticker_unit(row)
                shown_value = None
                if not p.empty:
                    at = px[px["date"] == pd.Timestamp(p.iloc[0]["date"])]
                    shown_value = at["close"].iloc[-1] if len(at) else None
            if p.empty:
                raise SpecError(f"{where}: sin datos al {as_of}")
            r0 = p.iloc[0]
            last = date.fromisoformat(r0["date"])
            self.r._note(source, last)
            unit = RAW_UNITS.get(raw, ("num", ""))[0]
            value_text = fmt(shown_value if shown_value is not None else r0["value"], unit, dec)
            delta = r0[DELTAS[delta_key]]
            tipo = r0["tipo"]
            delta_unit = {"%": "pct", "pp": "pp"}.get(tipo, unit)
            delta_text = signed(delta, delta_unit)
            meta_parts = [fmt_date(last), DELTA_LABELS[delta_key]]
        else:
            if "value" not in it:
                raise SpecError(f"{where}: indica 'macro', 'ticker' o 'value'")
            unit = it.get("unit", "num")
            if unit not in UNIT_CODES:
                raise SpecError(f"{where}: unit debe ser uno de {sorted(UNIT_CODES)}")
            value_text = fmt(it["value"], unit, dec) if _num(it["value"]) is not None else str(it["value"])
            delta = it.get("delta_value")
            delta_unit = it.get("delta_unit", unit)
            if delta_unit not in UNIT_CODES:
                raise SpecError(f"{where}: delta_unit debe ser uno de {sorted(UNIT_CODES)}")
            delta_text = signed(delta, delta_unit) if delta is not None else ""
        if it.get("note"):
            meta_parts.append(str(it["note"]))
        cls = direction(delta)
        arrow = {"up": "▲ ", "down": "▼ ", "flat": ""}[cls]
        delta_html = f'<div class="kpi-d {cls}">{arrow}{esc(delta_text)}</div>' if delta_text else ""
        meta_html = f'<div class="kpi-m">{esc(" · ".join(meta_parts))}</div>' if meta_parts else ""
        return (f'<div class="kpi"><div class="kpi-l">{esc(it["label"])}</div>'
                f'<div class="kpi-v">{esc(value_text)}</div>{delta_html}{meta_html}</div>')

    # -- graficas
    def chart(self, blk: dict, where: str, cid: str) -> str:
        _check_keys(blk, "chart", where)
        kind = blk.get("kind")
        if kind not in TIME_KINDS | CAT_KINDS:
            raise SpecError(f"{where}: kind debe ser uno de {sorted(TIME_KINDS | CAT_KINDS)}")
        if kind in TIME_KINDS:
            cfg, sub = self.time_chart(blk, where, kind)
            self.needs_time = True
        else:
            cfg, sub = self.cat_chart(blk, where, kind)
            self.needs_cat = True
        self.charts[cid] = cfg
        title = blk.get("title") or (cfg["series"][0]["label"] if cfg["series"] else kind)
        tools = []
        if cfg["time"]:
            tools += [f'<button type="button" class="btn" data-range="{r}" aria-pressed="false">{"MÁX" if r == "MAX" else r}</button>'
                      for r in cfg["ranges"]]
            tools += ['<span class="sep" aria-hidden="true"></span>',
                      '<button type="button" class="btn" data-act="fit">Ajustar</button>']
        tools.append('<button type="button" class="btn" data-act="table" aria-pressed="false">Tabla</button>')
        style = f' style="height:{cfg["height"]}px"' if cfg.get("height") else ""
        note = f'<p class="note">{esc(blk["note"])}</p>' if blk.get("note") else ""
        return (f'<section class="card {self.span(blk, where)}" id="{cid}" aria-label="{esc(title)}">'
                f'<div class="card-h"><h2>{esc(title)}</h2><div class="tools">{"".join(tools)}</div></div>'
                f'<p class="card-sub">{esc(sub)}</p><div class="chart"{style}></div>'
                f'<div class="tableview" hidden></div>{note}</section>')

    def time_chart(self, blk: dict, where: str, kind: str) -> tuple[dict, str]:
        items = blk.get("series")
        if not isinstance(items, list) or not items:
            raise SpecError(f"{where}: 'series' debe ser una lista con al menos una serie")
        if len(items) > MAX_SERIES[kind]:
            raise SpecError(f"{where}: {kind} admite hasta {MAX_SERIES[kind]} series; divide en varias gráficas")
        compare = bool(blk.get("compare", False))
        if compare and kind not in ("line", "area"):
            raise SpecError(f"{where}: compare solo aplica a line o area")
        for key in ("categories", "sql", "points", "category_label", "sort", "labels"):
            if key in blk:
                raise SpecError(f"{where}: '{key}' es para gráficas de categorías (bar, hbar, curve)")
        freq_hint = str(items[0].get("freq", "D")).upper() if isinstance(items[0], dict) else "D"
        start, end = self.r.window(blk, freq_hint, kind, where)
        overlays: list[dict] = []
        if kind == "candles":
            s = self.r.candles(items[0], start, end, bool(blk.get("volume", True)), f"{where}.series[0]")
            series = [s]
            unit = s["unit"]
            unit_label = s["unit_label"]
            freq = "D"
            first, last = s["ohlc"][0][0], s["ohlc"][-1][0]
            watermark = s["id"]
        else:
            if "volume" in blk:
                raise SpecError(f"{where}: 'volume' solo aplica a candles")
            series = [self.r.time_series(it, start, end, f"{where}.series[{i}]") for i, it in enumerate(items)]
            units = {s["unit"] for s in series}
            if len(units) > 1 and not compare:
                detail = ", ".join(f"{s['label']}: {s['unit_label'] or s['unit']}" for s in series)
                raise SpecError(f"{where}: series con unidades distintas ({detail}). No se usan dos ejes: "
                                "usa compare: true (cambio % desde el inicio del rango) o gráficas separadas.")
            unit = series[0]["unit"]
            unit_label = series[0]["unit_label"]
            freqs = {s["freq"] for s in series}
            freq = freqs.pop() if len(freqs) == 1 else "D"
            first = min(s["points"][0][0] for s in series)
            last = max(s["points"][-1][0] for s in series)
            watermark = series[0]["id"] if len(series) == 1 else None
        if "unit" in blk:
            if blk["unit"] not in UNIT_CODES:
                raise SpecError(f"{where}: unit debe ser uno de {sorted(UNIT_CODES)}")
            unit = blk["unit"]
        if "sma" in blk:
            if kind not in ("candles", "line") or len(items) != 1 or "ticker" not in items[0]:
                raise SpecError(f"{where}: sma aplica a candles o line con un solo ticker")
            ns = blk["sma"] if isinstance(blk["sma"], list) else [blk["sma"]]
            for n in ns:
                if not isinstance(n, int) or not 2 <= n <= 400:
                    raise SpecError(f"{where}: sma debe ser una lista de enteros entre 2 y 400")
                overlays.append({"label": f"SMA {n}", "points": self.r.sma(series[0]["id"], n, start, end)})
        if kind == "baseline" and "base" in blk and _num(blk["base"]) is None:
            raise SpecError(f"{where}: base debe ser un número")
        if "polarity" in blk and kind != "histogram":
            raise SpecError(f"{where}: polarity en series de tiempo solo aplica a histogram")

        slot_labels = [s["label"] for s in series] if kind not in ("candles", "baseline") else []
        slots = self.palette.assign(slot_labels + [o["label"] for o in overlays])
        for s, slot in zip(series if slot_labels else [], slots):
            s["slot"] = slot
        for o, slot in zip(overlays, slots[len(slot_labels):]):
            o["slot"] = slot

        span_days = (date.fromisoformat(last) - date.fromisoformat(first)).days
        skip = {"M": {"1M", "3M"}, "Q": {"1M", "3M", "6M"}, "S": {"1M", "3M", "6M", "YTD"}, "A": {"1M", "3M", "6M", "YTD", "1A"}}
        ranges = [r for r, days in RANGE_DAYS.items() if r not in skip.get(freq, set()) and (r == "YTD" or days < span_days)]
        if "YTD" in ranges and date.fromisoformat(first) > date(date.fromisoformat(last).year, 1, 1):
            ranges.remove("YTD")
        ranges.append("MAX")
        init = str(blk.get("range", "MAX")).upper().replace("MÁX", "MAX")
        if init not in ranges:
            raise SpecError(f"{where}: range {init!r} no disponible para estos datos; opciones: {ranges}")

        markers = []
        for i, m in enumerate(blk.get("markers", []) or []):
            _check_keys(m, "marker", f"{where}.markers[{i}]")
            d = _parse_date(m.get("date"), f"{where}.markers[{i}]").isoformat()
            pts = [p[0] for p in (series[0].get("points") or series[0].get("ohlc"))]
            snapped = max((p for p in pts if p <= d), default=pts[0])
            pos = m.get("position", "above")
            if pos not in ("above", "below"):
                raise SpecError(f"{where}.markers[{i}]: position debe ser above o below")
            markers.append({"date": snapped, "text": str(m.get("text", "")), "position": pos})
        hlines = []
        for i, h in enumerate(blk.get("hlines", []) or []):
            _check_keys(h, "hline", f"{where}.hlines[{i}]")
            if _num(h.get("value")) is None:
                raise SpecError(f"{where}.hlines[{i}]: value debe ser un número")
            hlines.append({"value": _num(h["value"]), "label": str(h.get("label", ""))})

        dec = blk.get("decimals")
        if dec is not None and (not isinstance(dec, int) or not 0 <= dec <= 6):
            raise SpecError(f"{where}: decimals debe ser un entero de 0 a 6")
        cfg = {
            "time": True, "kind": kind, "unit": unit, "decimals": dec, "freq": freq, "compare": compare,
            "range": init, "ranges": ranges, "markers": markers, "hlines": hlines,
            "base": _num(blk.get("base")) or 0, "polarity": bool(blk.get("polarity", False)),
            "watermark": watermark if not compare else None,
            "series": [{k: s[k] for k in ("label", "slot", "unit", "points", "ohlc", "volume") if k in s} for s in series],
            "overlays": overlays,
        }
        n_points = sum(len(s.get("points") or s.get("ohlc") or []) for s in series)
        self.summary.append(f"chart {kind}({len(series)} series, {n_points:,} puntos)")
        parts = [blk["subtitle"]] if blk.get("subtitle") else [FREQ_LABELS.get(freq, "")]
        if compare:
            parts.append("cambio % desde el inicio del rango visible")
        elif unit_label and not blk.get("subtitle"):
            parts.append(unit_label)
        return cfg, " · ".join(p for p in parts if p)

    def cat_chart(self, blk: dict, where: str, kind: str) -> tuple[dict, str]:
        for key in ("period", "from", "to", "range", "compare", "markers", "hlines", "base", "volume", "sma"):
            if key in blk:
                raise SpecError(f"{where}: '{key}' es para series de tiempo, no para {kind}")
        items = blk.get("series", [])
        if not isinstance(items, list):
            raise SpecError(f"{where}: 'series' debe ser una lista")
        unit = blk.get("unit")
        if unit is not None and unit not in UNIT_CODES:
            raise SpecError(f"{where}: unit debe ser uno de {sorted(UNIT_CODES)}")
        if "sql" in blk:
            if "categories" in blk or "points" in blk:
                raise SpecError(f"{where}: usa sql o categories/points, no ambos")
            df = self.r.sql(blk["sql"], where)
            if df.shape[1] < 2:
                raise SpecError(f"{where}: el SQL debe devolver (categoría, valor[, valor...])")
            categories = [str(c) for c in df.iloc[:, 0]]
            series = [{"label": str(c), "values": [_num(v) for v in df[c]]} for c in df.columns[1:]]
            raw_units = set()
        elif "points" in blk:
            if "categories" in blk:
                raise SpecError(f"{where}: con points las categorías salen de cada punto")
            pts = blk["points"]
            if not isinstance(pts, list) or not pts:
                raise SpecError(f"{where}: points debe ser una lista de {{category, macro|ticker}}")
            categories = [str(p.get("category", "")) for p in pts]
            items = items or [{"label": "Hoy"}]
            series, raw_units = [], set()
            for i, it in enumerate(items):
                _check_keys(it, "series", f"{where}.series[{i}]")
                as_of = _as_of(it.get("as_of"), self.r.today, f"{where}.series[{i}]")
                values = []
                for j, p in enumerate(pts):
                    v, raw = self.r.value_at(p, as_of, f"{where}.points[{j}]")
                    values.append(v)
                    raw_units.add(raw)
                label = it.get("label") or fmt_date(as_of)
                series.append({"label": label, "values": values})
        else:
            categories = blk.get("categories")
            if not isinstance(categories, list) or not categories:
                raise SpecError(f"{where}: indica categories + series[].values, sql o points")
            categories = [str(c) for c in categories]
            series, raw_units = [], set()
            for i, it in enumerate(items):
                _check_keys(it, "series", f"{where}.series[{i}]")
                vals = it.get("values")
                if not isinstance(vals, list) or len(vals) != len(categories):
                    raise SpecError(f"{where}.series[{i}]: values debe tener {len(categories)} números (uno por categoría)")
                series.append({"label": it.get("label") or f"Serie {i + 1}", "values": [_num(v) for v in vals]})
        if not series:
            raise SpecError(f"{where}: no hay series")
        if len(series) > MAX_SERIES[kind]:
            raise SpecError(f"{where}: {kind} admite hasta {MAX_SERIES[kind]} series")
        if len(categories) > MAX_CATEGORIES:
            raise SpecError(f"{where}: máximo {MAX_CATEGORIES} categorías; filtra o usa una tabla")
        if all(v is None for s in series for v in s["values"]):
            raise SpecError(f"{where}: todas las series están vacías")
        if unit is None:
            codes = {RAW_UNITS.get(u, ("num", ""))[0] for u in raw_units}
            if len(codes) > 1:
                raise SpecError(f"{where}: puntos con unidades distintas {sorted(raw_units)}; indica 'unit' o separa")
            unit = codes.pop() if codes else "num"
        if blk.get("polarity") and kind == "curve":
            raise SpecError(f"{where}: polarity aplica a bar o hbar")
        sort = blk.get("sort")
        if sort is not None:
            if sort not in ("asc", "desc") or kind == "curve":
                raise SpecError(f"{where}: sort debe ser asc o desc (solo bar/hbar)")
            key = [(-math.inf if v is None else v) for v in series[0]["values"]]
            order = sorted(range(len(categories)), key=lambda i: key[i], reverse=(sort == "desc"))
            categories = [categories[i] for i in order]
            for s in series:
                s["values"] = [s["values"][i] for i in order]
        slots = self.palette.assign([s["label"] for s in series])
        for s, slot in zip(series, slots):
            s["slot"] = slot
        labels = blk.get("labels", kind != "curve" and len(categories) <= 25 and len(series) == 1)
        values = [abs(v) for s in series for v in s["values"] if v is not None]
        axis_dec = 4 if unit == "fx" else (0 if values and max(values) >= 10 else 1)
        dec = blk.get("decimals")
        if dec is not None and (not isinstance(dec, int) or not 0 <= dec <= 6):
            raise SpecError(f"{where}: decimals debe ser un entero de 0 a 6")
        height = None
        if kind == "hbar":
            height = max(240, 30 * len(categories) * len(series) + (40 if len(series) > 1 else 18) + 36)
        cfg = {
            "time": False, "kind": kind, "unit": unit, "decimals": dec, "axis_decimals": axis_dec,
            "categories": categories, "category_label": blk.get("category_label") or ("Plazo" if kind == "curve" else "Categoría"),
            "series": series, "polarity": bool(blk.get("polarity", False)), "labels": bool(labels), "height": height,
        }
        self.summary.append(f"chart {kind}({len(series)} series, {len(categories)} categorías)")
        unit_label = {"pct": "%", "pp": "puntos porcentuales", "mxn": "MXN", "usd": "USD", "fx": "tipo de cambio"}.get(unit, "")
        sub = blk.get("subtitle") or unit_label
        return cfg, sub

    # -- tablas
    def table(self, blk: dict, where: str) -> str:
        _check_keys(blk, "table", where)
        cols = blk.get("columns")
        if ("rows" in blk) == ("sql" in blk):
            raise SpecError(f"{where}: indica 'rows' o 'sql' (uno de los dos)")
        if "sql" in blk:
            df = self.r.sql(blk["sql"], where)
        else:
            rows = blk["rows"]
            if not isinstance(rows, list):
                raise SpecError(f"{where}: rows debe ser una lista")
            if rows and isinstance(rows[0], list):
                if not cols:
                    raise SpecError(f"{where}: con filas como listas, 'columns' es obligatorio")
                df = pd.DataFrame(rows, columns=[c["key"] if isinstance(c, dict) else c for c in cols])
            else:
                df = pd.DataFrame(rows)
        if df.empty:
            raise SpecError(f"{where}: la tabla no tiene filas")
        if cols is None:
            cols = [{"key": c, "label": c, "format": "num" if pd.api.types.is_numeric_dtype(df[c]) else
                     ("date" if pd.api.types.is_datetime64_any_dtype(df[c]) else "text")} for c in df.columns]
        spec_cols = []
        for i, c in enumerate(cols):
            c = {"key": c} if isinstance(c, str) else c
            _check_keys(c, "column", f"{where}.columns[{i}]")
            if c["key"] not in df.columns:
                raise SpecError(f"{where}.columns[{i}]: la columna {c['key']!r} no existe; disponibles: {list(df.columns)}")
            f = c.get("format", "num" if pd.api.types.is_numeric_dtype(df[c["key"]]) else "text")
            if f not in FORMATS:
                raise SpecError(f"{where}.columns[{i}]: format debe ser uno de {sorted(FORMATS)}")
            spec_cols.append({"key": c["key"], "label": c.get("label", c["key"]), "format": f, "decimals": c.get("decimals")})
        limit = int(blk.get("limit", 200))
        if not 1 <= limit <= MAX_TABLE_ROWS:
            raise SpecError(f"{where}: limit debe estar entre 1 y {MAX_TABLE_ROWS}")
        total = len(df)
        df = df.head(limit)
        head = "".join(
            f'<th class="{"txt" if c["format"] in ("text", "date") else "num"}" scope="col">'
            f'<button type="button">{esc(c["label"])}</button></th>' for c in spec_cols)
        body = []
        for _, row in df.iterrows():
            cells = []
            for c in spec_cols:
                text, sort_v, cls = self.cell(row[c["key"]], c["format"], c["decimals"])
                cells.append(f'<td class="{cls}" data-v="{esc(sort_v)}">{esc(text)}</td>')
            body.append("<tr>" + "".join(cells) + "</tr>")
        title = blk.get("title", "Tabla")
        sub = f'<p class="card-sub">{esc(blk["subtitle"])}</p>' if blk.get("subtitle") else ""
        notes = [blk["note"]] if blk.get("note") else []
        if total > limit:
            notes.append(f"Mostrando {limit} de {total} filas.")
        note = f'<p class="note">{esc(" ".join(notes))}</p>' if notes else ""
        self.summary.append(f"table({len(df)} filas)")
        return (f'<section class="card {self.span(blk, where)}" aria-label="{esc(title)}">'
                f'<div class="card-h"><h2>{esc(title)}</h2></div>{sub}'
                f'<div class="tablewrap"><table class="data" data-sortable><thead><tr>{head}</tr></thead>'
                f'<tbody>{"".join(body)}</tbody></table></div>{note}</section>')

    @staticmethod
    def cell(v: Any, f: str, dec: int | None) -> tuple[str, str, str]:
        if f == "text":
            text = "" if v is None or (isinstance(v, float) and math.isnan(v)) else str(v)
            return text, text, "txt"
        if f == "date":
            if v is None or (isinstance(v, float) and math.isnan(v)):
                return "", "", "txt"
            d = pd.Timestamp(v).date()
            return fmt_date(d), d.isoformat(), "txt"
        n = _num(v)
        sort_v = "" if n is None else repr(n)
        if f == "int":
            return ("—" if n is None else f"{n:,.0f}"), sort_v, "num"
        if f in ("chg", "chgpp"):
            cls = direction(n)
            arrow = {"up": "▲ ", "down": "▼ ", "flat": ""}[cls] if n is not None else ""
            return arrow + signed(n, "pct" if f == "chg" else "pp", dec), sort_v, f"num {cls}"
        return fmt(n, f, dec), sort_v, "num"

    # -- texto
    def text(self, blk: dict, where: str) -> str:
        _check_keys(blk, "text", where)
        if not blk.get("body"):
            raise SpecError(f"{where}: falta 'body'")
        title = blk.get("title", "Lectura")
        self.summary.append("text")
        return (f'<section class="card {self.span(blk, where)}" aria-label="{esc(title)}">'
                f'<div class="card-h"><h2>{esc(title)}</h2></div><div class="prose">{_md(blk["body"])}</div></section>')

    @staticmethod
    def span(blk: dict, where: str) -> str:
        span = blk.get("span", "full")
        if span not in ("full", "half"):
            raise SpecError(f"{where}: span debe ser full o half")
        return "span-full" if span == "full" else "span-half"


# ------------------------------------------------------------------ documento

def render(spec: dict, resolver: Resolver) -> tuple[str, dict]:
    _check_keys(spec, "doc", "documento")
    title = str(spec.get("title", "")).strip()
    if not title:
        raise SpecError("documento: falta 'title' (un nombre corto de 2 a 4 palabras)")
    if len(title) > 60:
        raise SpecError("documento: 'title' debe ser un nombre corto (máx. 60 caracteres); el detalle va en 'subtitle'")
    blocks = spec.get("blocks")
    if not isinstance(blocks, list) or not blocks:
        raise SpecError("documento: 'blocks' debe ser una lista con al menos un bloque")

    b = Builder(resolver)
    parts = []
    for i, blk in enumerate(blocks):
        where = f"blocks[{i}]"
        if not isinstance(blk, dict) or "type" not in blk:
            raise SpecError(f"{where}: cada bloque necesita 'type' (kpis, chart, table o text)")
        t = blk["type"]
        if t == "kpis":
            parts.append(b.kpis(blk, where))
        elif t == "chart":
            parts.append(b.chart(blk, where, f"c{i + 1}"))
        elif t == "table":
            parts.append(b.table(blk, where))
        elif t == "text":
            parts.append(b.text(blk, where))
        else:
            raise SpecError(f"{where}: type {t!r} desconocido; usa kpis, chart, table o text")

    extra = spec.get("sources", [])
    if not isinstance(extra, list):
        raise SpecError("documento: 'sources' debe ser una lista de nombres")
    sources = sorted(resolver.sources | {str(s) for s in extra})
    as_of = max(resolver.dates) if resolver.dates else None
    now = datetime.now(timezone.utc)
    meta = []
    if as_of:
        meta.append(f"Datos al <b>{esc(fmt_date(as_of))}</b>")
    if sources:
        meta.append(esc(" · ".join(sources)))
    subtitle = f'<p class="subtitle">{esc(spec["subtitle"])}</p>' if spec.get("subtitle") else ""
    header = (f'<header class="topbar"><div class="topbar-row"><span class="brand">ECONOMICS</span>'
              f'<span class="meta">{" · ".join(meta)}</span></div><h1>{esc(title)}</h1>{subtitle}</header>')
    libs = []
    if b.needs_time:
        libs.append("TradingView Lightweight Charts")
    if b.needs_cat:
        libs.append("Apache ECharts")
    footer = (f'<footer class="foot"><span>Fuentes: {esc(", ".join(sources) or "—")}. '
              f'Información, no recomendación de inversión.</span>'
              f'<span>Generado {esc(fmt_date(now.date()))} {now:%H:%M} UTC'
              + (f' · Gráficas: <a href="https://www.tradingview.com/" target="_blank" rel="noopener">{esc(", ".join(libs))}</a>'
                 if libs else "") + "</span></footer>")

    theme = (ASSETS / "theme.css").read_text()
    app = (ASSETS / "app.js").read_text()
    data_json = json.dumps({"charts": b.charts}, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    data_json = data_json.replace("</", "<\\/")
    description = spec.get("description") or spec.get("subtitle") or title
    scripts = ""
    if b.needs_time:
        scripts += f'<script src="{LW_URL}"></script>\n'
    if b.needs_cat:
        scripts += f'<script src="{ECHARTS_URL}"></script>\n'
    page = (
        f"<title>{esc(title)}</title>\n"
        f'<meta name="description" content="{esc(description)}">\n'
        f'<meta name="generator" content="ECONOMICS presentador v{THEME_VERSION}">\n'
        '<link rel="preconnect" href="https://fonts.googleapis.com">\n'
        '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>\n'
        f'<link rel="stylesheet" href="{FONTS_URL}">\n'
        f"<style>\n{theme}</style>\n"
        f"{scripts}"
        f'<div class="term">{header}<main class="grid">{"".join(parts)}</main>{footer}</div>\n'
        f'<script type="application/json" id="econ-data">{data_json}</script>\n'
        f"<script>\n{app}</script>\n"
    )
    info = {"title": title, "description": str(description), "as_of": as_of.isoformat() if as_of else None,
            "blocks": b.summary, "sources": sources}
    return page, info


def build(spec: dict, out: Path | None = None, data_dir: Path | None = None, today: date | None = None) -> tuple[Path, dict]:
    """Construye el HTML y lo guarda. Devuelve (ruta, resumen)."""
    resolver = Resolver(data_dir=data_dir, today=today)
    page, info = render(spec, resolver)
    if out is None:
        name = spec.get("file") or slugify(info["title"])
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,59}", str(name)):
            raise SpecError("documento: 'file' debe ser un nombre en minúsculas con guiones (p.ej. tasas-mx-eeuu)")
        out = config.ROOT / "out" / f"{name}.html"
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page)
    return out, info
