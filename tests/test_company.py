"""Reportes de emisoras: estados financieros, fechas de reporte y recomendaciones."""
import json

import pandas as pd
import pytest

from econ import config, pipeline, storage
from econ.sources import yahoo


def _statement(items, periods):
    cols = pd.to_datetime(periods)
    data = {c: [float(10 * (i + 1) + j) for i in range(len(items))] for j, c in enumerate(cols)}
    return pd.DataFrame(data, index=items)


def _earnings():
    idx = pd.DatetimeIndex(
        [pd.Timestamp("2026-10-22 16:00").tz_localize("America/New_York"),
         pd.Timestamp("2026-07-23 20:00").tz_localize("America/New_York")],
        name="Earnings Date",
    )
    return pd.DataFrame({"EPS Estimate": [1.1, 1.0], "Reported EPS": [None, 1.2],
                         "Surprise(%)": [None, 20.0]}, index=idx)


def _recommendations():
    return pd.DataFrame({"period": ["0m", "-1m"], "strongBuy": [5, 4], "buy": [10, 9], "hold": [3, 4],
                         "sell": [1, 1], "strongSell": [0, 0]})


class FakeTicker:
    calls: list[str] = []
    fail_on: str | None = None

    def __init__(self, symbol):
        self.symbol = symbol

    def _call(self, what):
        FakeTicker.calls.append(f"{self.symbol}:{what}")
        if FakeTicker.fail_on and FakeTicker.fail_on == f"{self.symbol}:{what}":
            raise RuntimeError("YFRateLimitError: Too Many Requests. Rate limited.")

    def _stmt(self, name, freq):
        self._call(f"{name}/{freq}")
        periods = ["2025-12-31", "2024-12-31"] if freq == "yearly" else ["2026-06-30", "2026-03-31"]
        return _statement(["TotalRevenue", "NetIncome"], periods)

    def get_income_stmt(self, freq="yearly"):
        return self._stmt("income", freq)

    def get_balance_sheet(self, freq="yearly"):
        return self._stmt("balance", freq)

    def get_cash_flow(self, freq="yearly"):
        if self.symbol == "EMPTY":
            return pd.DataFrame()
        return self._stmt("cashflow", freq)

    def get_earnings_dates(self, limit=12):
        self._call("earnings")
        return _earnings()

    def get_recommendations(self):
        self._call("recommendations")
        if self.symbol == "EMPTY":
            raise ValueError("no recommendations")
        return _recommendations()


@pytest.fixture
def fake_yf(monkeypatch):
    import yfinance

    FakeTicker.calls = []
    FakeTicker.fail_on = None
    monkeypatch.setattr(yfinance, "Ticker", FakeTicker)
    monkeypatch.setattr(yahoo.time, "sleep", lambda s: None)
    return FakeTicker


def test_statement_rows_long_format():
    rows = yahoo.statement_rows(_statement(["TotalRevenue", "NetIncome"], ["2025-12-31", "2024-12-31"]),
                                "WALMEX.MX", "income", "A")
    df = pd.DataFrame(rows)
    assert len(df) == 4
    assert set(df.columns) == {"ticker", "statement", "freq", "period_end", "item", "value"}
    assert df.loc[(df["item"] == "TotalRevenue") & (df["period_end"] == "2025-12-31"), "value"].item() == 10.0
    assert yahoo.statement_rows(None, "X", "income", "A") == []
    assert yahoo.statement_rows(pd.DataFrame(), "X", "income", "A") == []


def test_earnings_rows_keep_local_report_date():
    rows = yahoo.earnings_rows(_earnings(), "AAPL.MX")
    df = pd.DataFrame(rows)
    # 20:00 en Nueva York ya es el dia siguiente en UTC: se conserva la fecha local.
    assert df["date"].dt.strftime("%Y-%m-%d").tolist() == ["2026-10-22", "2026-07-23"]
    assert df["surprise_pct"].tolist()[1] == 20.0 and pd.isna(df["eps_reported"].iloc[0])
    events = _earnings().assign(**{"Event Type": ["Earnings", "Meeting"]})
    assert len(yahoo.earnings_rows(events, "AAPL.MX")) == 1


def test_recommendation_row_uses_current_month():
    row = yahoo.recommendation_row(_recommendations(), "AAPL.MX", pd.Timestamp("2026-10-13"))
    assert row["strong_buy"] == 5 and row["hold"] == 3 and row["ticker"] == "AAPL.MX"
    assert yahoo.recommendation_row(pd.DataFrame(), "AAPL.MX", pd.Timestamp("2026-10-13")) is None


def test_download_company_collects_everything(fake_yf):
    out = yahoo.download_company({"AAPL.MX": "AAPL", "EMPTY.MX": "EMPTY"})
    fin = out["financials"]
    assert set(fin["statement"]) == {"income", "balance", "cashflow"} and set(fin["freq"]) == {"A", "Q"}
    assert set(fin["ticker"]) == {"AAPL.MX", "EMPTY.MX"}
    assert len(fin[fin["ticker"] == "AAPL.MX"]) == 3 * 2 * 4
    assert len(out["earnings"]) == 4 and len(out["recommendations"]) == 1
    logs = out["log"].set_index("ticker")
    assert logs.loc["AAPL.MX", "status"] == "ok" and logs.loc["AAPL.MX", "symbol"] == "AAPL"
    assert logs.loc["EMPTY.MX", "recommendations"] == 0
    assert "recommendations" in logs.loc["EMPTY.MX", "error"]


def test_download_company_stops_on_rate_limit(fake_yf):
    fake_yf.fail_on = "BBB:balance/yearly"
    out = yahoo.download_company({"AAA.MX": "AAA", "BBB.MX": "BBB", "CCC.MX": "CCC"})
    assert out["log"]["ticker"].tolist() == ["AAA.MX"]
    assert not any(c.startswith("CCC") for c in fake_yf.calls)


def _patch_dirs(monkeypatch, tmp_path):
    data = tmp_path / "data"
    for attr, sub in (("DATA_DIR", ""), ("PRICES_DIR", "prices"), ("MACRO_DIR", "macro"),
                      ("FUNDAMENTALS_DIR", "fundamentals"), ("FINANCIALS_DIR", "financials"),
                      ("EARNINGS_DIR", "earnings"), ("RECOMMENDATIONS_DIR", "recommendations"),
                      ("COMPANY_LOG_DIR", "company_log"), ("SNAPSHOTS_DIR", "snapshots")):
        monkeypatch.setattr(config, attr, data / sub if sub else data)
    return data


def test_company_targets_stalest_first(tmp_path, monkeypatch):
    _patch_dirs(monkeypatch, tmp_path)
    monkeypatch.setattr(pipeline, "stock_symbols",
                        lambda: {"A.MX": "A", "B.MX": "B", "C.MX": "C", "AAPL.MX": "AAPL"})
    done = pd.DataFrame({"date": pd.to_datetime(["2026-10-01", "2026-09-01", "2026-10-10"]),
                         "ticker": ["A.MX", "B.MX", "AAPL.MX"], "status": "ok"})
    storage.write_partitioned(done, config.COMPANY_LOG_DIR, keys=["ticker", "date"], freq="M")
    assert list(pipeline.company_targets(3)) == ["C.MX", "B.MX", "A.MX"]
    assert pipeline.company_targets(1) == {"C.MX": "C"}


def test_pipeline_company_task(tmp_path, monkeypatch, fake_yf):
    data = _patch_dirs(monkeypatch, tmp_path)
    monkeypatch.setattr(pipeline, "stock_symbols", lambda: {"AAPL.MX": "AAPL", "WALMEX.MX": "WALMEX.MX"})
    assert pipeline.main(["company", "--limit", "1"]) == 0
    log = storage.read_dataset(config.COMPANY_LOG_DIR)
    assert log["ticker"].tolist() == ["AAPL.MX"]
    assert pipeline.main(["company", "--limit", "1"]) == 0
    assert set(storage.read_dataset(config.COMPANY_LOG_DIR)["ticker"]) == {"AAPL.MX", "WALMEX.MX"}
    fin = storage.read_dataset(config.FINANCIALS_DIR)
    assert {p.name for p in config.FINANCIALS_DIR.iterdir()} == {"AAPL.MX", "WALMEX.MX"}  # una por emisora
    assert not fin.duplicated(["ticker", "statement", "freq", "period_end", "item"]).any()
    run = json.loads((data / "snapshots" / "last_run.json").read_text())
    assert run["task"] == "company" and run["args"]["limit"] == 1

    # Si Yahoo bloquea desde la primera emisora, el paso queda en error (y se reintenta otro dia).
    fake_yf.fail_on = "AAPL:income/yearly"
    monkeypatch.setattr(pipeline, "stock_symbols", lambda: {"AAPL.MX": "AAPL"})
    assert pipeline.main(["company"]) == 1
