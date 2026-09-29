from datetime import date

import numpy as np
import pandas as pd
import pytest

from econ import macro, storage

TODAY = date(2026, 9, 29)  # martes


@pytest.mark.parametrize("spec, start, end", [
    ("today", "2026-09-29", "2026-09-29"),
    ("yesterday", "2026-09-28", "2026-09-28"),
    ("wtd", "2026-09-28", "2026-09-29"),
    ("last-week", "2026-09-21", "2026-09-27"),
    ("mtd", "2026-09-01", "2026-09-29"),
    ("last-month", "2026-08-01", "2026-08-31"),
    ("qtd", "2026-07-01", "2026-09-29"),
    ("last-quarter", "2026-04-01", "2026-06-30"),
    ("ytd", "2026-01-01", "2026-09-29"),
    ("last-year", "2025-01-01", "2025-12-31"),
    ("1m", "2026-08-31", "2026-09-29"),
    ("2025", "2025-01-01", "2025-12-31"),
    ("2026-02", "2026-02-01", "2026-02-28"),
    ("2024-02", "2024-02-01", "2024-02-29"),
    ("2026-12", None, None),
    ("2026-Q1", "2026-01-01", "2026-03-31"),
    ("2026-Q3", "2026-07-01", "2026-09-29"),  # recortado a hoy
    ("2025-S2", "2025-07-01", "2025-12-31"),
    ("2026-W38", "2026-09-14", "2026-09-20"),
    ("2026-03-17", "2026-03-17", "2026-03-17"),
    ("2026-01-15:2026-02-15", "2026-01-15", "2026-02-15"),
])
def test_resolve_period(spec, start, end):
    if start is None:
        with pytest.raises(SystemExit):
            macro.resolve_period(spec, TODAY)
        return
    s, e, _ = macro.resolve_period(spec, TODAY)
    assert (s.isoformat(), e.isoformat()) == (start, end)


def test_yesterday_on_monday_is_friday():
    s, e, _ = macro.resolve_period("yesterday", date(2026, 9, 28))
    assert s == e == date(2026, 9, 25)


def _fixture():
    days = pd.bdate_range("2025-01-01", "2026-09-28")
    months = pd.date_range("2024-01-01", "2026-08-01", freq="MS")
    obs = pd.concat([
        pd.DataFrame({"source": "FRED", "series_id": "DGS10", "date": days,
                      "value": np.linspace(4.0, 5.0, len(days))}),
        pd.DataFrame({"source": "FRED", "series_id": "CPIAUCSL", "date": months,
                      "value": 300 * 1.0025 ** np.arange(len(months))}),
        pd.DataFrame({"source": "MERCADO", "series_id": "MXN=X", "date": days,
                      "value": np.where(days < "2026-09-01", 18.0, 17.0)}),
    ], ignore_index=True)
    meta = pd.DataFrame([
        ("FRED", "DGS10", "Treasury 10 anios", "tasas", "pct", "D", "avg"),
        ("FRED", "CPIAUCSL", "CPI general", "inflacion", "indice", "M", "avg"),
        ("MERCADO", "MXN=X", "USD/MXN", "divisas", "fx", "D", "last"),
    ], columns=["source", "series_id", "name", "category", "units", "frequency", "agg"])
    return obs, meta


def test_change_ytd_and_month():
    obs, meta = _fixture()
    ytd = macro.change(obs, meta, date(2026, 1, 1), TODAY).set_index("series_id")
    assert ytd.loc["DGS10", "base_date"] == "2025-12-31"
    assert ytd.loc["DGS10", "tipo"] == "pp"
    assert ytd.loc["MXN=X", "cambio"] == pytest.approx(100 * (17 / 18 - 1), abs=1e-3)
    assert ytd.loc["CPIAUCSL", "cambio"] == pytest.approx(100 * (1.0025**8 - 1), abs=1e-3)

    sep = macro.change(obs, meta, date(2026, 9, 1), date(2026, 9, 30)).set_index("series_id")
    assert bool(sep.loc["CPIAUCSL", "sin_datos_en_periodo"])  # el CPI de sept aun no se publica
    assert pd.isna(sep.loc["CPIAUCSL", "cambio"])
    assert sep.loc["MXN=X", "min"] == sep.loc["MXN=X", "max"] == 17.0


def test_panel_as_of_date():
    obs, meta = _fixture()
    p = macro.panel(obs, meta, date(2026, 6, 30)).set_index("series_id")
    assert p.loc["DGS10", "date"] == "2026-06-30"
    assert p.loc["CPIAUCSL", "date"] == "2026-06-01"
    assert p.loc["CPIAUCSL", "d_1y"] == pytest.approx(100 * (1.0025**12 - 1), abs=1e-3)
    assert p.loc["DGS10", "d_ytd"] > 0 and p.loc["DGS10", "tipo"] == "pp"


def test_series_frequencies():
    obs, meta = _fixture()
    w = macro.series(obs, meta[meta["series_id"] == "MXN=X"], date(2026, 9, 1), TODAY, "W")
    assert w["date"].tolist() == ["2026-09-04", "2026-09-11", "2026-09-18", "2026-09-25", "2026-09-28"]
    m = macro.series(obs, meta, date(2026, 6, 1), TODAY, "M")
    cpi = m[m["series_id"] == "CPIAUCSL"]
    assert cpi["periodo"].tolist() == ["2026-06", "2026-07", "2026-08"]
    assert cpi["pct_yoy"].iloc[-1] == pytest.approx(100 * (1.0025**12 - 1), abs=1e-3)
    q = macro.series(obs, meta, date(2026, 1, 1), TODAY, "Q")
    fx = q[q["series_id"] == "MXN=X"].set_index("periodo")
    assert bool(fx.loc["2026-Q3", "parcial"]) and fx.loc["2026-Q3", "value"] == 17.0  # agg = last


def test_load_includes_market_series(tmp_path, monkeypatch):
    data = tmp_path / "data"
    days = pd.bdate_range("2026-09-01", periods=5)
    px = pd.DataFrame({"date": days, "ticker": "MXN=X", "open": 17.0, "high": 17.0, "low": 17.0,
                       "close": 17.0, "adj_close": 17.0, "volume": 0})
    px = pd.concat([px, px.assign(ticker="AAPL.MX")])
    storage.write_partitioned(px, data / "prices", keys=["ticker", "date"], freq="M")
    storage.write_partitioned(pd.DataFrame({"source": "FRED", "series_id": "DGS10", "date": days, "value": 4.0}),
                              data / "macro", keys=["source", "series_id", "date"], freq="Y")
    obs, meta = macro.load(data_dir=data)
    assert set(obs["series_id"]) == {"DGS10", "MXN=X"}  # AAPL.MX no es macro
    fx = meta.set_index("series_id").loc["MXN=X"]
    assert (fx["source"], fx["units"], fx["agg"]) == ("MERCADO", "fx", "last")
    assert len(macro.select(meta, category="divisas")) >= 2
    with pytest.raises(SystemExit):
        macro.select(meta, series="NOEXISTE")
