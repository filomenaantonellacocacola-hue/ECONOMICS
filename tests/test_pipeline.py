import json

import numpy as np
import pandas as pd
import pytest

from econ import config, query, snapshots, storage
from econ.sources import banxico, fred, yahoo


def _raw_download(tickers, days=5, tz=None, fields_first=False):
    idx = pd.date_range("2026-01-05", periods=days, freq="B", tz=tz, name="Date")
    fields = ["Open", "High", "Low", "Close", "Adj Close", "Volume"]
    cols = [(t, f) for t in tickers for f in fields]
    if fields_first:
        cols = [(f, t) for t, f in cols]
    data = np.arange(len(idx) * len(cols), dtype=float).reshape(len(idx), len(cols)) + 1
    return pd.DataFrame(data, index=idx, columns=pd.MultiIndex.from_tuples(cols))


def _prices(tickers=("AAA.MX", "BBB"), days=300):
    dates = pd.bdate_range("2025-01-01", periods=days)
    rows = []
    for i, t in enumerate(tickers):
        px = 100 * (1 + 0.001 * (i + 1)) ** np.arange(days)
        rows.append(pd.DataFrame({
            "date": dates, "ticker": t, "open": px, "high": px, "low": px,
            "close": px, "adj_close": px, "volume": 1000,
        }))
    return pd.concat(rows, ignore_index=True)


@pytest.mark.parametrize("fields_first", [False, True])
@pytest.mark.parametrize("tz", [None, "America/Mexico_City"])
def test_normalize_download_multiindex(fields_first, tz):
    raw = _raw_download(["AAA.MX", "BBB"], tz=tz, fields_first=fields_first)
    df = yahoo.normalize_download(raw, ["AAA.MX", "BBB"])
    assert list(df.columns) == ["date", "ticker", "open", "high", "low", "close", "adj_close", "volume"]
    assert sorted(df["ticker"].unique()) == ["AAA.MX", "BBB"]
    assert len(df) == 10
    assert df["date"].dt.tz is None


def test_normalize_download_drops_empty_rows_and_single_ticker():
    raw = _raw_download(["AAA.MX"]).droplevel(0, axis=1)
    raw.iloc[0, raw.columns.get_loc("Close")] = np.nan
    df = yahoo.normalize_download(raw, ["AAA.MX"])
    assert len(df) == 4 and set(df["ticker"]) == {"AAA.MX"}


def test_write_partitioned_upsert_and_idempotent(tmp_path):
    df = _prices(days=40)
    written = storage.write_partitioned(df, tmp_path, keys=["ticker", "date"], freq="M")
    assert {p.parent.name for p in written} == {"2025-01", "2025-02"}
    assert storage.write_partitioned(df, tmp_path, keys=["ticker", "date"], freq="M") == []

    update = df.tail(1).assign(close=999.0)
    written = storage.write_partitioned(update, tmp_path, keys=["ticker", "date"], freq="M")
    assert [p.parent.name for p in written] == ["2025-02"]
    back = storage.read_dataset(tmp_path)
    assert len(back) == len(df)
    assert back.loc[back["close"] == 999.0].shape[0] == 1


def test_fred_parsers():
    csv_new = "observation_date,DGS10\n2026-01-02,4.1\n2026-01-05,.\n2026-01-06,4.2\n"
    csv_old = "DATE,DGS10\n2026-01-02,4.1\n"
    assert fred.parse_csv(csv_new, "DGS10")["value"].tolist() == [4.1, 4.2]
    assert len(fred.parse_csv(csv_old, "DGS10")) == 1
    api = {"observations": [{"date": "2026-01-02", "value": "4.1"}, {"date": "2026-01-03", "value": "."}]}
    df = fred.parse_api_json(api, "DGS10")
    assert df.iloc[0].to_dict()["source"] == "FRED" and len(df) == 1


def test_banxico_parser():
    payload = {"bmx": {"series": [{"idSerie": "SF43718", "datos": [
        {"fecha": "02/01/2026", "dato": "17.1234"},
        {"fecha": "03/01/2026", "dato": "N/E"},
        {"fecha": "04/01/2026", "dato": "1,234.5"},
    ]}]}}
    df = banxico.parse_response(payload)
    assert df["value"].tolist() == [17.1234, 1234.5]
    assert df["date"].iloc[0] == pd.Timestamp("2026-01-02")


def test_banxico_without_token_is_skipped(monkeypatch):
    monkeypatch.delenv("BANXICO_TOKEN", raising=False)
    df, failed = banxico.fetch_many(["SF43718"], "2020-01-01")
    assert df.empty and failed == ["SF43718"]


def test_market_snapshot_metrics():
    universe = pd.DataFrame({"ticker": ["AAA.MX", "BBB"], "market": ["BMV", "SIC"],
                             "asset_type": ["stock", "stock"], "name": ["A", "B"]})
    snap = snapshots.market_snapshot(_prices(), universe).set_index("ticker")
    assert snap.loc["AAA.MX", "chg_1d"] == pytest.approx(0.1, abs=0.01)
    assert snap.loc["BBB", "chg_1w"] == pytest.approx(100 * (1.002**5 - 1), abs=0.01)
    assert snap.loc["AAA.MX", "rsi14"] == 100.0
    assert snap.loc["AAA.MX", "pct_from_52w_high"] == 0.0
    assert snap.loc["AAA.MX", "vs_sma200"] > 0


def test_macro_snapshot_pct_only_for_levels():
    dates = pd.date_range("2024-01-01", periods=30, freq="MS")
    macro = pd.concat([
        pd.DataFrame({"source": "FRED", "series_id": "CPIAUCSL", "date": dates, "value": np.linspace(300, 330, 30)}),
        pd.DataFrame({"source": "FRED", "series_id": "DGS10", "date": dates, "value": np.linspace(4, 5, 30)}),
    ])
    series = config.load_macro_series()
    snap = snapshots.macro_snapshot(macro, series).set_index("series_id")
    assert pd.notna(snap.loc["CPIAUCSL", "pct_1y"])
    assert pd.isna(snap.loc["DGS10", "pct_1y"])
    assert snap.loc["DGS10", "chg_1y"] > 0


def test_query_views_and_build(tmp_path):
    data = tmp_path / "data"
    universe = config.load_universe()
    prices = _prices(tickers=("WALMEX.MX", "AAPL.MX"))
    storage.write_partitioned(prices, data / "prices", keys=["ticker", "date"], freq="M")
    macro = pd.DataFrame({"source": "FRED", "series_id": "DGS10",
                          "date": pd.bdate_range("2025-01-01", periods=10), "value": 4.0})
    storage.write_partitioned(macro, data / "macro", keys=["source", "series_id", "date"], freq="Y")

    con = query.connect(data_dir=data)
    latest = query.run("SELECT ticker, market, chg_1d FROM prices_latest ORDER BY ticker", con)
    assert latest["ticker"].tolist() == ["AAPL.MX", "WALMEX.MX"]
    assert latest["market"].tolist() == ["SIC", "BMV"]
    m = query.run("SELECT name, value FROM macro_latest", con)
    assert m.iloc[0]["name"] == "Treasury 10 anios"

    out = tmp_path / "snap"
    manifest = snapshots.build(data_dir=data, out_dir=out)
    assert manifest["datasets"]["prices"]["ids"] == 2
    assert manifest["datasets"]["prices"]["files"][0].startswith("data/prices/")
    assert "WALMEX.MX" not in manifest["health"]["tickers_missing"]
    assert (out / "market_snapshot.csv").exists()
    assert "Treasury 10 anios" in (out / "briefing.md").read_text()
    assert json.loads((out / "manifest.json").read_text())["datasets"]["fundamentals"] == {"rows": 0}


def test_universe_is_well_formed():
    u = config.load_universe()
    assert u["ticker"].is_unique
    assert set(u["market"]) <= {"BMV", "SIC", "INDEX", "FX"}
    assert u.loc[u["market"].isin(["BMV", "SIC"]), "ticker"].str.endswith(".MX").all()
    sic = u[u["market"] == "SIC"]
    assert (sic["ref_ticker"] != "").all()
    from econ import resolve
    for ticker, ref in zip(sic["ticker"], sic["ref_ticker"]):
        base = ref.replace("-", "").replace(".", "")
        assert ticker in {f"{base}{s}.MX" for s in ("", *resolve.SUFFIXES)}, (ticker, ref)
    s = config.load_macro_series()
    assert not s.duplicated(["source", "series_id"]).any()
    assert set(s["agg"]) <= {"avg", "last"}
    assert set(s["frequency"]) <= {"D", "W", "M", "Q"}


def test_pipeline_daily_end_to_end(tmp_path, monkeypatch):
    from econ import pipeline

    data = tmp_path / "data"
    monkeypatch.setattr(config, "DATA_DIR", data)
    monkeypatch.setattr(config, "PRICES_DIR", data / "prices")
    monkeypatch.setattr(config, "MACRO_DIR", data / "macro")
    monkeypatch.setattr(config, "SNAPSHOTS_DIR", data / "snapshots")
    monkeypatch.setattr(yahoo, "download_prices", lambda tickers, start: _prices(tickers=("WALMEX.MX",), days=30))
    monkeypatch.setattr(pipeline, "tickers_without_data", lambda tickers: [])
    macro = pd.DataFrame({"source": "FRED", "series_id": "DGS10",
                          "date": pd.bdate_range("2026-01-01", periods=5), "value": 4.0})
    monkeypatch.setattr(fred, "fetch_many", lambda ids, start: (macro, []))
    monkeypatch.setattr(banxico, "fetch_many", lambda ids, start: (pd.DataFrame(), ids))

    assert pipeline.main(["daily"]) == 0
    manifest = json.loads((data / "snapshots" / "manifest.json").read_text())
    assert manifest["datasets"]["prices"]["ids"] == 1
    assert manifest["datasets"]["macro"]["rows"] == 5

    # Si una fuente falla, el resto se guarda y el proceso termina con error.
    monkeypatch.setattr(fred, "fetch_many", lambda ids, start: (pd.DataFrame(), ids))
    assert pipeline.main(["daily"]) == 1
    assert (data / "snapshots" / "briefing.md").exists()


def _macro_fixture(tmp_path):
    cpi = pd.DataFrame({"source": "FRED", "series_id": "CPIAUCSL",
                        "date": pd.date_range("2023-01-01", "2026-08-01", freq="MS")})
    cpi["value"] = 300 * 1.0025 ** np.arange(len(cpi))
    gdp = pd.DataFrame({"source": "FRED", "series_id": "GDPC1",
                        "date": pd.date_range("2023-01-01", "2026-04-01", freq="QS")})
    gdp["value"] = 100 * 1.005 ** np.arange(len(gdp))
    days = pd.bdate_range("2023-01-02", "2026-09-28")
    target = pd.DataFrame({"source": "FRED", "series_id": "DFEDTARU", "date": days,
                           "value": np.where(days < "2026-09-15", 5.5, 5.25)})
    data = tmp_path / "data"
    storage.write_partitioned(pd.concat([cpi, gdp, target]), data / "macro",
                              keys=["source", "series_id", "date"], freq="Y")
    return data


def test_macro_aggregated_views(tmp_path):
    con = query.connect(data_dir=_macro_fixture(tmp_path))

    monthly = query.run("SELECT * FROM macro_monthly", con)
    assert "GDPC1" not in set(monthly["series_id"])  # PIB es trimestral: no se baja a mensual

    q = query.run("SELECT * FROM macro_quarterly", con).set_index(["series_id", "period_label"])
    assert q.loc[("CPIAUCSL", "2026-Q2"), "pct_yoy"] == pytest.approx(100 * (1.0025**12 - 1))
    assert q.loc[("CPIAUCSL", "2026-Q2"), "n_obs"] == 3
    assert not q.loc[("CPIAUCSL", "2026-Q2"), "is_partial"]
    assert q.loc[("CPIAUCSL", "2026-Q3"), "is_partial"]  # falta el dato de septiembre
    assert not q.loc[("GDPC1", "2026-Q2"), "is_partial"]
    assert q.loc[("GDPC1", "2026-Q2"), "pct_prev"] == pytest.approx(0.5)
    # Regla 'last' para la tasa objetivo; las tasas en % no tienen cambio porcentual.
    assert q.loc[("DFEDTARU", "2026-Q3"), "value"] == 5.25
    assert q.loc[("DFEDTARU", "2026-Q3"), "chg_prev"] == pytest.approx(-0.25)
    assert pd.isna(q.loc[("DFEDTARU", "2026-Q3"), "pct_prev"])

    s = query.run("SELECT period_label, is_partial FROM macro_semiannual WHERE series_id = 'GDPC1'", con)
    assert s["period_label"].iloc[-1] == "2026-S1" and not s["is_partial"].iloc[-1]
    a = query.run("SELECT period_label, n_obs FROM macro_annual WHERE series_id = 'CPIAUCSL' ORDER BY 1", con)
    assert a["period_label"].tolist() == ["2023", "2024", "2025", "2026"]
    assert a["n_obs"].tolist() == [12, 12, 12, 8]


def test_macro_aggregated_snapshots(tmp_path):
    data = _macro_fixture(tmp_path)
    out = tmp_path / "snap"
    manifest = snapshots.build(data_dir=data, out_dir=out)
    assert {"macro_monthly.csv", "macro_quarterly.csv", "macro_semiannual.csv",
            "macro_annual.csv"} <= set(manifest["snapshots"])

    q = pd.read_csv(out / "macro_quarterly.csv")
    assert len([c for c in q.columns if c.startswith("20")]) <= 13
    cpi = q[q["series_id"] == "CPIAUCSL"].set_index("metric")
    assert list(cpi.index) == ["value", "pct_yoy"]
    assert cpi.loc["pct_yoy", "2026-Q2"] == pytest.approx(3.042, abs=0.001)
    assert cpi.loc["value", "partial"] == "2026-Q3"
    assert q.loc[q["series_id"] == "DFEDTARU", "metric"].tolist() == ["value"]
    m = pd.read_csv(out / "macro_monthly.csv")
    assert "GDPC1" not in set(m["series_id"])


def test_prune_removes_tickers_and_empty_partitions(tmp_path):
    df = _prices(tickers=("AAA.MX", "BBB"), days=40)
    df.loc[(df["ticker"] == "BBB") & (df["date"] < "2025-02-01"), "ticker"] = "OLD"
    storage.write_partitioned(df[df["ticker"] != "BBB"], tmp_path, keys=["ticker", "date"], freq="M")
    storage.write_partitioned(df[df["ticker"] == "BBB"], tmp_path, keys=["ticker", "date"], freq="M")
    changed = storage.prune(tmp_path, "ticker", {"AAA.MX", "BBB"})
    assert [p.parent.name for p in changed] == ["2025-01"]
    assert set(storage.read_dataset(tmp_path)["ticker"]) == {"AAA.MX", "BBB"}
    storage.prune(tmp_path, "ticker", {"BBB"})
    assert not (tmp_path / "2025-01").exists()  # solo tenia AAA.MX
    assert set(storage.read_dataset(tmp_path)["ticker"]) == {"BBB"}


def _patch_dirs(monkeypatch, data):
    for attr, sub in [("DATA_DIR", ""), ("PRICES_DIR", "prices"), ("MACRO_DIR", "macro"),
                      ("FUNDAMENTALS_DIR", "fundamentals"), ("SNAPSHOTS_DIR", "snapshots")]:
        monkeypatch.setattr(config, attr, data / sub if sub else data)


def test_daily_backfills_new_tickers_from_existing_history_start(tmp_path, monkeypatch):
    from econ import pipeline

    _patch_dirs(monkeypatch, tmp_path / "data")
    universe = pd.DataFrame({"ticker": ["OLD.MX", "NEW.MX"], "market": "BMV", "asset_type": "stock",
                             "name": ["Old", "New"], "ref_ticker": ""})
    monkeypatch.setattr(config, "load_universe", lambda: universe)
    history = _prices(tickers=("OLD.MX",), days=60)  # arranca 2025-01-01
    storage.write_partitioned(history, config.PRICES_DIR, keys=["ticker", "date"], freq="M")

    calls = []
    def fake_download(tickers, start):
        calls.append((sorted(tickers), start))
        return _prices(tickers=tuple(tickers), days=5)
    monkeypatch.setattr(yahoo, "download_prices", fake_download)

    pipeline.update_daily_prices("2026-09-20")
    assert calls == [(["NEW.MX", "OLD.MX"], "2026-09-20"), (["NEW.MX"], "2025-01-01")]
    assert pipeline.tickers_without_data(["OLD.MX", "NEW.MX"]) == []


def test_backfill_prunes_and_fundamentals_use_ref_ticker(tmp_path, monkeypatch):
    from econ import pipeline

    _patch_dirs(monkeypatch, tmp_path / "data")
    universe = pd.DataFrame({
        "ticker": [f"T{i}.MX" for i in range(10)] + ["AAPL.MX", "SPY.MX"],
        "market": ["BMV"] * 10 + ["SIC", "SIC"],
        "asset_type": ["stock"] * 11 + ["etf"],
        "name": "x",
        "ref_ticker": [""] * 10 + ["AAPL", "SPY"],
    })
    monkeypatch.setattr(config, "load_universe", lambda: universe)
    storage.write_partitioned(_prices(tickers=("T0.MX", "AAPL")), config.PRICES_DIR,
                              keys=["ticker", "date"], freq="M")
    pipeline.prune_to_universe()
    assert set(storage.read_dataset(config.PRICES_DIR)["ticker"]) == {"T0.MX"}

    seen = {}
    def fake_fundamentals(symbols):
        seen.update(symbols)
        return yahoo.fundamentals_frame([{"date": "2026-09-26", "ticker": t} for t in symbols])
    monkeypatch.setattr(yahoo, "download_fundamentals", fake_fundamentals)
    pipeline.update_fundamentals()
    assert seen["AAPL.MX"] == "AAPL" and seen["T3.MX"] == "T3.MX" and "SPY.MX" not in seen


def test_health_reports_missing_macro_when_empty():
    series = config.load_macro_series()
    h = snapshots.health(pd.DataFrame(), pd.DataFrame(), config.load_universe(), series)
    assert len(h["macro_missing"]) == len(series)


def test_resolve_accepts_only_price_consistent_candidates(tmp_path, monkeypatch):
    from econ import resolve

    universe = pd.DataFrame({
        "ticker": ["TSM.MX", "FOO.MX", "BAR.MX", "WALMEX.MX"],
        "market": ["SIC", "SIC", "SIC", "BMV"],
        "asset_type": "stock",
        "name": "x",
        "ref_ticker": ["TSM", "FOO", "BAR", ""],
    })
    dates = pd.bdate_range("2026-08-01", periods=20)

    def frame(ticker, close):
        return pd.DataFrame({"date": dates, "ticker": ticker, "open": close, "high": close, "low": close,
                             "close": close, "adj_close": close, "volume": 1})

    fx = np.full(len(dates), 18.0)
    fake = pd.concat([
        frame("MXN=X", fx),
        frame("TSM", np.linspace(200, 220, 20)),
        frame("TSMN.MX", np.linspace(200, 220, 20) * fx * 1.01),  # coincide (1% de diferencia)
        frame("FOO", np.full(20, 50.0)),
        frame("FOON.MX", np.full(20, 50.0 * 18 * 3)),  # existe pero es otra emisora
        frame("BAR", np.full(20, 10.0)),
    ])
    requested = []
    monkeypatch.setattr(yahoo, "download_prices", lambda tickers, start: requested.extend(tickers) or fake)

    report = resolve.resolve(["TSM.MX", "FOO.MX", "BAR.MX", "WALMEX.MX"], universe)
    assert report["resolved"] == {"TSM.MX": {"ticker": "TSMN.MX", "price_ratio": 1.01}}
    assert report["mismatch"] == {"FOO.MX": {"FOON.MX": 3.0}}
    assert report["not_found"] == ["BAR.MX"]
    assert "TSM.MX" not in requested and "DELLC.MX" not in requested and "BARN.MX" in requested

    csv_path = tmp_path / "universe.csv"
    universe.to_csv(csv_path, index=False)
    monkeypatch.setattr(config, "UNIVERSE_CSV", csv_path)
    assert resolve.apply(report) == ["TSMN.MX"]
    assert config.load_universe()["ticker"].tolist() == ["TSMN.MX", "FOO.MX", "BAR.MX", "WALMEX.MX"]
    assert config.load_universe().loc[0, "ref_ticker"] == "TSM"


def test_resolve_candidates():
    from econ import resolve

    assert resolve.candidates("BRK-B", "BRKB.MX") == [
        "BRKBN.MX", "BRKBC.MX", "BRKB1.MX", "BRKBN1.MX", "BRKB1N.MX", "BRKBI.MX", "BRKBW.MX"]
    assert resolve.candidates("DELL", "DELLC.MX")[0] == "DELL.MX"


def test_resolve_symbols_tries_current_ticker_first(tmp_path, monkeypatch):
    from econ import pipeline, resolve

    _patch_dirs(monkeypatch, tmp_path / "data")
    universe = pd.DataFrame({"ticker": ["OK.MX", "GOOD.MX", "BAD.MX"], "market": ["BMV", "SIC", "SIC"],
                             "asset_type": "stock", "name": "x", "ref_ticker": ["", "GOOD", "BAD"]})
    monkeypatch.setattr(config, "load_universe", lambda: universe)
    storage.write_partitioned(_prices(tickers=("OK.MX",), days=30), config.PRICES_DIR,
                              keys=["ticker", "date"], freq="M")
    # GOOD.MX responde con su clave actual; BAD.MX no.
    monkeypatch.setattr(yahoo, "download_prices",
                        lambda tickers, start: _prices(tickers=tuple(t for t in tickers if t == "GOOD.MX"), days=30)
                        if "GOOD.MX" in tickers else pd.DataFrame())
    seen = {}
    def fake_resolve(targets, u):
        seen["targets"] = targets
        return {"resolved": {}, "mismatch": {}, "not_found": targets}
    monkeypatch.setattr(resolve, "resolve", fake_resolve)
    monkeypatch.setattr(pipeline, "prune_to_universe", lambda: None)

    assert pipeline.resolve_symbols() == 0
    assert seen["targets"] == ["BAD.MX"]
    assert json.loads((config.SNAPSHOTS_DIR / "symbol_resolution.json").read_text())["not_found"] == ["BAD.MX"]
