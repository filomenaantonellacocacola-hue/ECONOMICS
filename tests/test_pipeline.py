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
    prices = _prices(tickers=("WALMEX.MX", "AAPL"))
    storage.write_partitioned(prices, data / "prices", keys=["ticker", "date"], freq="M")
    macro = pd.DataFrame({"source": "FRED", "series_id": "DGS10",
                          "date": pd.bdate_range("2025-01-01", periods=10), "value": 4.0})
    storage.write_partitioned(macro, data / "macro", keys=["source", "series_id", "date"], freq="Y")

    con = query.connect(data_dir=data)
    latest = query.run("SELECT ticker, market, chg_1d FROM prices_latest ORDER BY ticker", con)
    assert latest["ticker"].tolist() == ["AAPL", "WALMEX.MX"]
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
    assert u.loc[u["market"] == "BMV", "ticker"].str.endswith(".MX").all()
    s = config.load_macro_series()
    assert not s.duplicated(["source", "series_id"]).any()


def test_pipeline_daily_end_to_end(tmp_path, monkeypatch):
    from econ import pipeline

    data = tmp_path / "data"
    monkeypatch.setattr(config, "DATA_DIR", data)
    monkeypatch.setattr(config, "PRICES_DIR", data / "prices")
    monkeypatch.setattr(config, "MACRO_DIR", data / "macro")
    monkeypatch.setattr(config, "SNAPSHOTS_DIR", data / "snapshots")
    monkeypatch.setattr(yahoo, "download_prices", lambda tickers, start: _prices(tickers=("WALMEX.MX",), days=30))
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
