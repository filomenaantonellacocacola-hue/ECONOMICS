import json
import re
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from econ import snapshots, storage
from econ.present import SpecError, build
from econ.present.__main__ import main as present_main
from econ.present.build import Palette, fmt

TODAY = date(2026, 9, 29)
EXAMPLE = Path(__file__).resolve().parent.parent / "econ" / "present" / "examples" / "tablero-tasas.json"


@pytest.fixture(scope="module")
def data_dir(tmp_path_factory):
    data = tmp_path_factory.mktemp("present") / "data"
    rng = np.random.default_rng(7)
    days = pd.bdate_range("2023-01-02", "2026-09-28")
    rows = []
    for ticker, base in [("^MXX", 55000), ("MXN=X", 18.5), ("WALMEX.MX", 60), ("AMXB.MX", 17), ("AAPL.MX", 3000)]:
        close = base * np.exp(np.cumsum(rng.normal(0, 0.01, len(days))))
        rows.append(pd.DataFrame({"date": days, "ticker": ticker, "open": close * 0.998, "high": close * 1.01,
                                  "low": close * 0.99, "close": close, "adj_close": close, "volume": 1000}))
    storage.write_partitioned(pd.concat(rows), data / "prices", keys=["ticker", "date"], freq="M")
    cal = pd.date_range("2023-01-01", "2026-09-29")
    months = pd.date_range("2022-01-01", "2026-08-01", freq="MS")
    macro = pd.concat([
        pd.DataFrame({"source": "BANXICO", "series_id": "SF61745", "date": cal,
                      "value": np.where(cal < "2026-03-26", 7.0, 6.5)}),
        pd.DataFrame({"source": "FRED", "series_id": "DFEDTARU", "date": cal, "value": 4.0}),
        *[pd.DataFrame({"source": "FRED", "series_id": sid, "date": days, "value": np.linspace(lo, hi, len(days))})
          for sid, lo, hi in [("DGS3MO", 4.5, 4.2), ("DGS2", 4.2, 4.8), ("DGS10", 4.0, 5.2), ("DGS30", 4.2, 5.5)]],
        pd.DataFrame({"source": "FRED", "series_id": "CPIAUCSL", "date": months,
                      "value": 300 * 1.0025 ** np.arange(len(months))}),
    ])
    storage.write_partitioned(macro, data / "macro", keys=["source", "series_id", "date"], freq="Y")
    snapshots.build(data_dir=data, out_dir=data / "snapshots")
    return data


def _build(spec, data_dir, tmp_path):
    out, info = build(spec, tmp_path / "r.html", data_dir=data_dir, today=TODAY)
    page = out.read_text()
    charts = json.loads(re.search(r'id="econ-data">(.*?)</script>', page, re.S)[1].replace("<\\/", "</"))["charts"]
    return page, charts, info


def test_example_spec_builds(data_dir, tmp_path):
    spec = json.loads(EXAMPLE.read_text())
    page, charts, info = _build(spec, data_dir, tmp_path)
    assert page.startswith("<title>Tasas México y EE.UU.</title>")
    assert "lightweight-charts@4.2.3" in page and "echarts@5.6.0" in page
    assert {c["kind"] for c in charts.values()} == {"line", "baseline", "curve", "candles", "hbar", "histogram"}
    assert info["as_of"] == "2026-09-29"
    assert info["sources"] == ["Banxico", "FRED", "Yahoo Finance"]
    assert "--panel: #131722" in page  # el tema siempre se incrusta completo


def test_kpis_resolve_values_and_deltas(data_dir, tmp_path):
    spec = {"title": "KPIs", "blocks": [{"type": "kpis", "items": [
        {"label": "Banxico", "macro": "SF61745", "delta": "ytd"},
        {"label": "Manual", "value": 12.5, "unit": "pct", "delta_value": -0.25, "delta_unit": "pp", "note": "estimado"},
    ]}]}
    page, _, _ = _build(spec, data_dir, tmp_path)
    assert '<div class="kpi-v">6.50%</div>' in page
    assert '<div class="kpi-d down">▼ -0.50 pp</div>' in page
    assert "29 sep 2026 · en el año" in page
    assert "▼ -0.25 pp" in page and "estimado" in page


def test_time_chart_series_ranges_and_markers(data_dir, tmp_path):
    spec = {"title": "Tasas", "blocks": [{"type": "chart", "kind": "line", "from": "2025-01-01", "range": "1A",
             "series": [{"label": "Banxico", "macro": "SF61745"}, {"label": "Fed", "macro": "DFEDTARU"}],
             "markers": [{"date": "2026-03-28", "text": "Recorte"}], "hlines": [{"value": 5, "label": "Neutral"}]}]}
    _, charts, _ = _build(spec, data_dir, tmp_path)
    c = charts["c1"]
    assert c["unit"] == "pct" and c["freq"] == "D"
    assert [s["label"] for s in c["series"]] == ["Banxico", "Fed"]
    assert c["series"][0]["points"][0] == ["2025-01-01", 7.0]
    assert c["ranges"] == ["1M", "3M", "6M", "YTD", "1A", "MAX"]
    assert c["markers"] == [{"date": "2026-03-28", "text": "Recorte", "position": "above"}]
    assert c["watermark"] is None  # dos series: sin marca de agua


def test_monthly_fields_and_diff(data_dir, tmp_path):
    spec = {"title": "Macro", "blocks": [
        {"type": "chart", "kind": "histogram", "polarity": True, "from": "2025-01-01",
         "series": [{"macro": "CPIAUCSL", "freq": "M", "field": "pct_yoy"}]},
        {"type": "chart", "kind": "baseline", "from": "2026-01-01",
         "series": [{"diff": [{"macro": "SF61745"}, {"macro": "DFEDTARU"}]}]},
    ]}
    _, charts, _ = _build(spec, data_dir, tmp_path)
    h = charts["c1"]
    assert h["freq"] == "M" and h["unit"] == "pct" and h["watermark"] == "CPIAUCSL"
    assert h["series"][0]["points"][-1] == ["2026-08-01", pytest.approx(100 * (1.0025**12 - 1), abs=1e-4)]
    assert "1M" not in h["ranges"]  # mensual: sin rangos de 1 y 3 meses
    d = charts["c2"]
    assert d["unit"] == "pp" and d["series"][0]["label"] == "Diferencial" and d["watermark"] is None
    assert d["series"][0]["points"][-1] == ["2026-09-29", 2.5]


def test_mixed_units_need_compare(data_dir, tmp_path):
    series = [{"label": "USD/MXN", "ticker": "MXN=X"}, {"label": "IPC", "ticker": "^MXX"}]
    with pytest.raises(SpecError, match="unidades distintas"):
        _build({"title": "X", "blocks": [{"type": "chart", "kind": "line", "series": series}]}, data_dir, tmp_path)
    _, charts, _ = _build({"title": "X", "blocks": [{"type": "chart", "kind": "line", "compare": True, "series": series}]},
                          data_dir, tmp_path)
    assert charts["c1"]["compare"] is True


def test_candles_with_volume_and_sma(data_dir, tmp_path):
    spec = {"title": "IPC", "blocks": [{"type": "chart", "kind": "candles", "series": [{"ticker": "^MXX"}], "sma": [20, 50]}]}
    _, charts, _ = _build(spec, data_dir, tmp_path)
    c = charts["c1"]
    s = c["series"][0]
    assert c["watermark"] == "^MXX" and c["unit"] == "num"
    assert len(s["ohlc"][0]) == 5 and all(b[2] >= max(b[1], b[4]) and b[3] <= min(b[1], b[4]) for b in s["ohlc"])
    assert len(s["volume"]) == len(s["ohlc"])
    assert [o["label"] for o in c["overlays"]] == ["SMA 20", "SMA 50"]
    assert c["overlays"][0]["slot"] != c["overlays"][1]["slot"]


def test_categorical_sql_sort_and_curve_points(data_dir, tmp_path):
    spec = {"title": "Cat", "blocks": [
        {"type": "chart", "kind": "hbar", "polarity": True, "sort": "asc", "unit": "pct",
         "sql": "SELECT ticker, chg_ytd AS YTD FROM market_snapshot WHERE market = 'BMV'"},
        {"type": "chart", "kind": "curve", "points": [{"category": "2A", "macro": "DGS2"}, {"category": "10A", "macro": "DGS10"}],
         "series": [{"label": "Hoy"}, {"label": "Hace 1 año", "as_of": "-1y"}]},
    ]}
    _, charts, _ = _build(spec, data_dir, tmp_path)
    bar = charts["c1"]
    vals = bar["series"][0]["values"]
    assert vals == sorted(vals) and set(bar["categories"]) == {"WALMEX.MX", "AMXB.MX"}
    assert bar["labels"] is True and bar["height"] >= 240
    curve = charts["c2"]
    assert curve["categories"] == ["2A", "10A"] and curve["unit"] == "pct"
    today, year_ago = curve["series"][0]["values"], curve["series"][1]["values"]
    assert today[1] == pytest.approx(5.2, abs=0.01) and year_ago[1] < today[1]


def test_table_formats_and_escaping(data_dir, tmp_path):
    spec = {"title": "<script>alert(1)</script>", "blocks": [
        {"type": "table", "title": "Top", "columns": [
            {"key": "t", "label": "Ticker", "format": "text"}, {"key": "c", "label": "Cambio", "format": "chg"},
            {"key": "p", "label": "Precio", "format": "mxn"}],
         "rows": [{"t": "A</td><b>", "c": 1.234, "p": 1500.5}, {"t": "B", "c": -2.5, "p": None}]},
        {"type": "text", "body": "Hola **mundo**\n\n- uno\n- <b>dos</b>"},
        {"type": "chart", "kind": "bar", "categories": ["x</script><script>alert(2)"], "series": [{"label": "S", "values": [1]}]},
    ]}
    page, _, _ = _build(spec, data_dir, tmp_path)
    assert "<title>&lt;script&gt;alert(1)&lt;/script&gt;</title>" in page
    assert 'class="num up" data-v="1.234">▲ +1.23%</td>' in page
    assert 'class="num down" data-v="-2.5">▼ -2.50%</td>' in page
    assert "$1,500.50" in page and "A&lt;/td&gt;&lt;b&gt;" in page
    assert "<strong>mundo</strong>" in page and "<li>&lt;b&gt;dos&lt;/b&gt;</li>" in page
    assert "</script><script>alert(2)" not in page and "x<\\/script><script>alert(2)" in page


@pytest.mark.parametrize("blk, message", [
    ({"type": "chart", "kind": "line", "color": "red", "series": [{"macro": "DGS10"}]}, "estilo"),
    ({"type": "chart", "kind": "line", "series": [{"macro": "DGS10", "lineWidth": 4}]}, "no permitidas"),
    ({"type": "chart", "kind": "line", "series": [{"macro": "DGS11"}]}, "DGS10"),
    ({"type": "chart", "kind": "line", "series": [{"ticker": "NOPE.MX"}]}, "ticker desconocido"),
    ({"type": "chart", "kind": "pie", "series": []}, "kind debe ser"),
    ({"type": "chart", "kind": "line", "range": "5A", "from": "2026-01-01", "series": [{"macro": "DGS10"}]}, "no disponible"),
    ({"type": "chart", "kind": "line", "series": [{"macro": "DGS10"}] * 7}, "hasta 6 series"),
    ({"type": "chart", "kind": "candles", "series": [{"macro": "DGS10"}]}, "requieren 'ticker'"),
    ({"type": "chart", "kind": "bar", "categories": ["a", "b"], "series": [{"values": [1]}]}, "2 números"),
    ({"type": "table", "rows": [{"a": 1}], "columns": [{"key": "b"}]}, "no existe"),
    ({"type": "kpis", "items": [{"label": "X", "macro": "DGS10", "delta": "2y"}]}, "delta debe ser"),
    ({"type": "video"}, "desconocido"),
])
def test_invalid_specs_explain_the_fix(data_dir, tmp_path, blk, message):
    with pytest.raises(SpecError, match=message):
        _build({"title": "X", "blocks": [blk]}, data_dir, tmp_path)


def test_palette_is_stable_and_never_repeats_in_a_chart():
    p = Palette()
    assert p.assign(["Banxico", "Fed"]) == [0, 1]
    assert p.assign(["Fed", "Banxico", "CETES"]) == [1, 0, 2]  # el color sigue a la serie
    p.assign(["d", "e", "f"])
    assert p.assign(["g", "Banxico"]) == [1, 0]  # sin slots libres: toma el primero no usado en la gráfica
    assert len(set(p.assign(["a", "b", "c", "d", "e", "f"]))) == 6


def test_fmt_matches_js_conventions():
    assert fmt(1234.5, "pct") == "1,234.50%"
    assert fmt(-0.25, "pp") == "-0.25 pp"
    assert fmt(-3, "mxn") == "-$3.00"
    assert fmt(17.74871, "fx") == "17.7487"
    assert fmt(6747704, "compact") == "6.75 M"
    assert fmt(None, "pct") == "—"


def test_cli_reports_errors(tmp_path, capsys):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"title": "X", "blocks": [{"type": "chart", "kind": "line", "series": [], "font": "x"}]}))
    assert present_main([str(bad), "-o", str(tmp_path / "x.html")]) == 2
    assert "ERROR" in capsys.readouterr().err
