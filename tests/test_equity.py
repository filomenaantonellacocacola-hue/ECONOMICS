"""Estadistica por emisora, fundamentales normalizados, estados financieros y CLI de econ.equity."""
import numpy as np
import pandas as pd
import pytest

from econ import config, equity, query, snapshots, storage

DAYS = pd.bdate_range("2023-10-02", "2026-10-09")


def _universe():
    return pd.DataFrame([
        ("^MXX", "INDEX", "index", "S&P/BMV IPC", ""),
        ("MXN=X", "FX", "fx", "USD/MXN", ""),
        ("AAA.MX", "BMV", "stock", "Alfa Alimentos", ""),
        ("CCC.MX", "BMV", "stock", "Cementos del Centro", ""),
        ("SPY.MX", "SIC", "etf", "SPDR S&P 500", "SPY"),
        ("BBB.MX", "SIC", "stock", "Beta Bank", "BBB"),
    ], columns=["ticker", "market", "asset_type", "name", "ref_ticker"])


def _series(ticker, px, volume=1000):
    return pd.DataFrame({"date": DAYS, "ticker": ticker, "open": px, "high": px, "low": px, "close": px,
                         "adj_close": px, "volume": volume, "dividend": 0.0, "split": 0.0})


def _prices():
    rng = np.random.default_rng(7)
    mxx = rng.normal(0.0004, 0.01, len(DAYS))
    spy = rng.normal(0.0005, 0.01, len(DAYS))
    aaa = 1.5 * mxx + rng.normal(0, 0.004, len(DAYS))
    ccc = 0.5 * mxx + rng.normal(0, 0.004, len(DAYS))
    bbb = 2.0 * spy + rng.normal(0, 0.004, len(DAYS))
    frames = [
        _series("^MXX", 50000 * np.cumprod(1 + mxx)),
        _series("MXN=X", np.full(len(DAYS), 18.0)),
        _series("AAA.MX", 50 * np.cumprod(1 + aaa)),
        _series("CCC.MX", 20 * np.cumprod(1 + ccc), volume=np.where(np.arange(len(DAYS)) % 4 == 0, 500, 0)),
        _series("SPY.MX", 10000 * np.cumprod(1 + spy)),
    ]
    b = 3000 * np.cumprod(1 + bbb)
    b[:500] *= 2  # split 2:1 que Yahoo no ajusto: antes del dia 500 el precio es el doble
    frames.append(_series("BBB.MX", b))
    df = pd.concat(frames, ignore_index=True)
    # AAA paga dividendo trimestral de 0.5 MXN
    pay = (df["ticker"] == "AAA.MX") & df["date"].isin(DAYS[::63])
    df.loc[pay, "dividend"] = 0.5
    return df


def _fundamentals():
    return pd.DataFrame([
        {"date": pd.Timestamp("2026-10-03"), "ticker": "AAA.MX", "shortName": "ALFA", "longName": "Alfa Alimentos SAB",
         "sector": "Consumer Defensive", "industry": "Packaged Foods", "currency": "MXN", "financialCurrency": "MXN",
         "marketCap": 2.0e11, "trailingPE": 12.5, "forwardPE": 11.0, "priceToBook": 2.0, "enterpriseToEbitda": 7.0,
         "dividendYield": 3.5, "payoutRatio": 0.45, "returnOnEquity": 0.18, "profitMargins": 0.08,
         "operatingMargins": 0.12, "revenueGrowth": 0.06, "debtToEquity": 45.0, "totalDebt": 30.0e9,
         "totalCash": 10.0e9, "ebitda": 20.0e9, "freeCashflow": 10.0e9, "targetMeanPrice": 75.0,
         "currentPrice": 60.0, "recommendationMean": 2.0, "numberOfAnalystOpinions": 12,
         "longBusinessSummary": "Fabrica alimentos."},
        {"date": pd.Timestamp("2026-10-03"), "ticker": "BBB.MX", "shortName": "BETA", "sector": "Financial Services",
         "industry": "Banks - Regional", "currency": "USD", "marketCap": 1.0e10, "trailingPE": -5.0,
         "priceToBook": -1.0, "dividendYield": 1.2, "returnOnEquity": 0.11, "debtToEquity": 822.0,
         "freeCashflow": 5.0e8, "targetMeanPrice": 200.0},
        {"date": pd.Timestamp("2026-09-26"), "ticker": "BBB.MX", "trailingPE": 99.0, "currency": "USD"},
    ])


def _financials():
    rows = []
    q_ends = pd.to_datetime(["2025-09-30", "2025-12-31", "2026-03-31", "2026-06-30", "2026-09-30"])
    for i, end in enumerate(q_ends):
        rows += [("AAA.MX", "income", "Q", end, "TotalRevenue", 100.0e6 + 10e6 * i),
                 ("AAA.MX", "income", "Q", end, "NetIncome", 10.0e6),
                 ("AAA.MX", "income", "Q", end, "DilutedEPS", 0.25),
                 ("AAA.MX", "balance", "Q", end, "NetDebt", 20.0e9 - 1e9 * i)]
    for y, rev in ((2023, 300e6), (2024, 360e6), (2025, 450e6)):
        end = pd.Timestamp(f"{y}-12-31")
        rows += [("AAA.MX", "income", "A", end, "TotalRevenue", rev),
                 ("AAA.MX", "income", "A", end, "NetIncome", rev / 10),
                 ("AAA.MX", "cashflow", "A", end, "FreeCashFlow", rev / 20),
                 ("AAA.MX", "income", "A", end, "SomethingElse", 1.0)]
    return pd.DataFrame(rows, columns=["ticker", "statement", "freq", "period_end", "item", "value"])


def _earnings():
    return pd.DataFrame({
        "ticker": "AAA.MX",
        "date": pd.to_datetime(["2026-10-22", "2026-07-21", "2026-04-22", "2026-02-10", "2025-10-21"]),
        "eps_estimate": [0.3, 0.25, 0.24, 0.22, 0.2],
        "eps_reported": [np.nan, 0.27, 0.22, 0.25, 0.21],
        "surprise_pct": [np.nan, 8.0, -8.3, 13.6, 5.0],
    })


def _recs():
    return pd.DataFrame({"date": pd.to_datetime(["2026-09-01", "2026-10-01"]), "ticker": "AAA.MX",
                         "strong_buy": [1, 2], "buy": [3, 4], "hold": [4, 3], "sell": [1, 1], "strong_sell": [0, 0]})


@pytest.fixture
def repo_data(tmp_path, monkeypatch):
    data = tmp_path / "data"
    cfg = tmp_path / "config"
    cfg.mkdir()
    _universe().to_csv(cfg / "universe.csv", index=False)
    (cfg / "macro_series.csv").write_text(
        "source,series_id,name,category,units,frequency,agg,scale,formula\n"
        "BANXICO,SF43936,CETES 28 dias,tasas,pct,W,avg,1,\n")
    monkeypatch.setattr(config, "UNIVERSE_CSV", cfg / "universe.csv")
    monkeypatch.setattr(config, "MACRO_SERIES_CSV", cfg / "macro_series.csv")
    monkeypatch.setattr(config, "CONFIG_DIR", cfg)
    monkeypatch.setattr(config, "DATA_DIR", data)
    storage.write_partitioned(_prices(), data / "prices", keys=["ticker", "date"], freq="M")
    storage.write_partitioned(_fundamentals(), data / "fundamentals", keys=["ticker", "date"], freq="M")
    storage.write_partitioned(_financials(), data / "financials",
                              keys=["ticker", "statement", "freq", "period_end", "item"], date_col="period_end", by="ticker")
    storage.write_partitioned(_earnings(), data / "earnings", keys=["ticker", "date"], freq="Y")
    storage.write_partitioned(_recs(), data / "recommendations", keys=["ticker", "date"], freq="M")
    cetes = pd.DataFrame({"source": "BANXICO", "series_id": "SF43936",
                          "date": pd.date_range("2025-10-02", "2026-10-08", freq="W-THU"), "value": 7.0})
    storage.write_partitioned(cetes, data / "macro", keys=["source", "series_id", "date"], freq="Y")
    return data


def test_clean_prices_fixes_unrecorded_splits_and_flags_jumps():
    idx = pd.bdate_range("2026-01-01", periods=12)
    px = pd.Series([100.0] * 6 + [50.0] * 6, index=idx)
    adj, notes = equity.clean_prices(px)
    assert np.allclose(adj, 50.0) and "split 2:1" in notes[0]
    rev = pd.Series([1.0] * 6 + [10.1] * 6, index=idx)
    adj, notes = equity.clean_prices(rev)
    assert np.allclose(adj[:6], 10.0) and adj.iloc[-1] == 10.1 and "split 1:10" in notes[0]
    scale = pd.Series([34.0] * 6 + [590.0] * 6, index=idx)  # 17x: no es un split comun
    adj, notes = equity.clean_prices(scale)
    assert len(adj) == 6 and "cambio de escala" in notes[0]
    real = pd.Series([100.0] * 6 + [160.0] * 6, index=idx)  # +60 %: puede ser real, solo se avisa
    adj, notes = equity.clean_prices(real)
    assert adj.equals(real) and "salto de +60%" in notes[0]
    glitch = pd.Series([100.0] * 6 + [50.0] + [100.0] * 5, index=idx)  # dato aislado que regresa
    assert not equity.clean_prices(glitch)[1][0].startswith("split")


def test_risk_stats(repo_data):
    stats = equity.risk_stats(_prices(), _universe(), rf_pct=7.0).set_index("ticker")
    assert set(stats.index) == {"AAA.MX", "CCC.MX", "SPY.MX", "BBB.MX"}
    assert stats.loc["AAA.MX", "beta_2y"] == pytest.approx(1.5, abs=0.25)
    assert stats.loc["CCC.MX", "beta_2y"] == pytest.approx(0.5, abs=0.2)
    # El split no ajustado de BBB se corrige: beta ~2 contra SPY.MX y sin caida artificial de 50 %.
    assert stats.loc["BBB.MX", "beta_2y"] == pytest.approx(2.0, abs=0.3)
    assert stats.loc["BBB.MX", "max_dd_3y"] > -50 and "split 2:1" in stats.loc["BBB.MX", "data_flags"]
    assert stats.loc["SPY.MX", "beta_2y"] == pytest.approx(1.0) and stats.loc["SPY.MX", "corr_2y"] == pytest.approx(1.0)
    a = stats.loc["AAA.MX"]
    assert a["vol_1y"] > 0 and a["max_dd_1y"] <= 0 and a["var95_1d"] < 0 and a["cvar95_1d"] <= a["var95_1d"]
    assert a["downside_vol_1y"] > 0 and a["obs_1y"] >= 250 and a["rf_pct"] == 7.0
    assert a["traded_days_pct_3m"] == pytest.approx(100)
    assert stats.loc["CCC.MX", "traded_days_pct_3m"] < 30 and "poco operada" in stats.loc["CCC.MX", "data_flags"]
    assert a["div_12m"] == pytest.approx(2.0)  # 4 pagos de 0.5 en 12 meses
    assert a["div_yield_12m_pct"] > 0


def test_risk_stats_without_dividend_column_leaves_yield_unknown():
    prices = _prices().drop(columns=["dividend", "split"])
    stats = equity.risk_stats(prices, _universe()).set_index("ticker")
    assert stats["div_12m"].isna().all()


def test_normalize_fundamentals_fixes_yahoo_scales():
    close = pd.Series({"AAA.MX": 60.0, "BBB.MX": 3600.0})
    f = equity.normalize_fundamentals(_fundamentals(), close, usdmxn=18.0).set_index("ticker")
    a, b = f.loc["AAA.MX"], f.loc["BBB.MX"]
    assert a["div_yield_pct"] == 3.5  # Yahoo ya lo da en %
    assert a["payout_pct"] == pytest.approx(45) and a["roe_pct"] == pytest.approx(18)
    assert a["debt_to_equity"] == pytest.approx(0.45) and b["debt_to_equity"] == pytest.approx(8.22)
    assert a["net_debt_ebitda"] == pytest.approx(1.0)
    assert a["mkt_cap_mxn_bn"] == pytest.approx(200) and b["mkt_cap_mxn_bn"] == pytest.approx(180)
    assert a["earnings_yield_pct"] == pytest.approx(8) and pd.isna(b["earnings_yield_pct"])
    assert a["fcf_yield_pct"] == pytest.approx(5) and pd.isna(b["fcf_yield_pct"])  # sin moneda de reporte
    assert a["target_upside_pct"] == pytest.approx(25)  # 75 / currentPrice 60
    assert b["target_upside_pct"] == pytest.approx(0)  # sin currentPrice: 3600 MXN / 18 = 200 USD
    assert b["pe"] == -5.0  # se toma el corte mas reciente, no el del 26-sep
    assert a["fin_currency"] == "MXN" and b["fin_currency"] == "USD"


def test_earnings_and_recommendations_summary():
    e = equity.earnings_summary(_earnings(), pd.Timestamp("2026-10-13")).set_index("ticker").loc["AAA.MX"]
    assert e["next_earnings"] == "2026-10-22" and e["last_earnings"] == "2026-07-21"
    assert e["last_surprise_pct"] == 8.0 and e["beats_4q"] == 3
    r = equity.recommendations_summary(_recs()).set_index("ticker").loc["AAA.MX"]
    assert r["rec_buy_pct"] == pytest.approx(60) and r["rec_sell_pct"] == pytest.approx(10)


def test_statement_table_and_annual_summary():
    fin = _financials()
    q = equity.statement_table(fin, "income", "Q", periods=5)
    assert list(q.columns[:3]) == ["partida", "clave", "TTM"]
    rev = q.set_index("clave").loc["TotalRevenue"]
    assert rev["TTM"] == pytest.approx((140 + 130 + 120 + 110) * 1e6)
    assert q.columns[3] == "2026-09-30"
    assert q.set_index("clave").loc["DilutedEPS", "TTM"] == pytest.approx(1.0)
    full = equity.statement_table(fin, "income", "A", periods=3, full=True)
    assert "SomethingElse" in set(full["clave"])
    assert "SomethingElse" not in set(equity.statement_table(fin, "income", "A", periods=3)["clave"])
    s = equity.annual_summary(fin).set_index("cifra")
    assert list(s.columns) == ["TTM", "FY2025", "FY2024", "FY2023"]
    assert s.loc["Crec. ingresos %", "FY2025"] == pytest.approx(25)
    assert s.loc["Margen neto %", "FY2024"] == pytest.approx(10)
    assert s.loc["Deuda neta", "TTM"] == pytest.approx(16e9)  # balance: ultimo trimestre, no suma


def test_scores_rank_within_market():
    df = pd.DataFrame({"ticker": list("abcd"), "market": ["BMV", "BMV", "SIC", "SIC"],
                       "asset_type": ["stock", "stock", "stock", "etf"],
                       "earnings_yield_pct": [10, 5, 3, 1], "pb": [1, 3, -2, 1], "ev_ebitda": [5, 10, 8, 1],
                       "div_yield_pct": [4, 1, 0, 0]})
    s = equity.add_scores(df).set_index("ticker")
    assert s.loc["a", "score_value"] > s.loc["b", "score_value"]
    assert pd.isna(s.loc["d", "score_value"])  # ETF: sin puntajes de emisora
    assert s.loc["c", "score_value"] == 100  # unica accion del SIC; P/VL negativo no cuenta como barato


def test_equity_snapshot_build_and_views(repo_data):
    manifest = snapshots.build(data_dir=repo_data, out_dir=repo_data / "snapshots")
    eq = pd.read_csv(repo_data / "snapshots" / "equity_snapshot.csv")
    assert list(eq.columns) == list(equity.COLUMNS)
    assert set(eq["ticker"]) == {"AAA.MX", "CCC.MX", "SPY.MX", "BBB.MX"}
    a = eq.set_index("ticker").loc["AAA.MX"]
    assert a["next_earnings"] == "2026-10-22" and a["last_quarter"] == "2026-09-30" and a["rf_pct"] == 7.0
    assert manifest["datasets"]["financials"]["ids"] == 1
    assert manifest["datasets"]["financials"]["max_date"] == "2026-09-30"
    assert manifest["health"]["company_coverage"] == "0/3"
    con = query.connect(data_dir=repo_data, config_dir=config.CONFIG_DIR)
    tables = set(con.execute("SELECT table_name FROM information_schema.tables").df()["table_name"])
    assert {"financials", "earnings", "recommendations", "recommendations_latest", "dividends",
            "equity_snapshot"} <= tables
    assert con.execute("SELECT count(*) FROM dividends WHERE ticker = 'AAA.MX'").fetchone()[0] == len(DAYS[::63])
    assert con.execute("SELECT strong_buy FROM recommendations_latest").fetchone()[0] == 2


def test_dividends_view_skipped_without_column(tmp_path):
    data = tmp_path / "data"
    storage.write_partitioned(_prices().drop(columns=["dividend", "split"]), data / "prices",
                              keys=["ticker", "date"], freq="M")
    con = query.connect(data_dir=data)
    tables = set(con.execute("SELECT table_name FROM information_schema.tables").df()["table_name"])
    assert "prices_latest" in tables and "dividends" not in tables


def test_resolve_tickers(repo_data):
    repo = equity.Repo(repo_data)
    assert repo.resolve("aaa") == "AAA.MX"
    assert repo.resolve("BBB") == "BBB.MX"  # por ref_ticker
    assert repo.resolve("cementos") == "CCC.MX"  # por nombre, sin acentos ni mayusculas
    with pytest.raises(LookupError):
        repo.resolve("zzz")


def test_cli_commands(repo_data, capsys):
    snapshots.build(data_dir=repo_data, out_dir=repo_data / "snapshots")
    assert equity.main(["ficha", "AAA"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("# AAA.MX · Alfa Alimentos (BMV, stock)")
    for section in ("## Puntajes", "## Riesgo", "## Valuacion", "## Cifras clave (millones de MXN", "## Pares",
                    "## Perfil", "Fabrica alimentos."):
        assert section in out
    assert equity.main(["ficha", "BBB"]) == 0
    assert "Alerta de datos:** split 2:1" in capsys.readouterr().out
    assert equity.main(["estados", "AAA", "--freq", "Q"]) == 0
    out = capsys.readouterr().out
    assert "| partida | clave | TTM | 2026-09-30 |" in out and "| Ingresos | TotalRevenue | 500.00 |" in out
    assert equity.main(["screen", "--where", "pe < 20", "--format", "csv"]) == 0
    assert capsys.readouterr().out.splitlines()[1].startswith("AAA.MX,")
    assert equity.main(["compare", "AAA", "BBB"]) == 0
    assert "| metrica | AAA.MX | BBB.MX |" in capsys.readouterr().out
    assert equity.main(["dividendos", "AAA"]) == 0
    assert "Ultimos 12 meses: **2.0000 MXN**" in capsys.readouterr().out
    assert equity.main(["buscar", "alimentos"]) == 0
    assert "AAA.MX" in capsys.readouterr().out
    assert equity.main(["columnas", "--format", "json"]) == 0
    assert '"columna": "beta_2y"' in capsys.readouterr().out
    assert equity.main(["periodo", "AAA", "BBB", "--period", "2026-03", "--today", "2026-10-13", "--format", "csv"]) == 0
    per = pd.read_csv(__import__("io").StringIO(capsys.readouterr().out)).set_index("ticker")
    assert per.loc["AAA.MX", "base_date"] == "2026-02-27" and per.loc["AAA.MX", "end_date"] == "2026-03-31"
    px = _prices().set_index(["ticker", "date"])["adj_close"]
    expected = 100 * (px["AAA.MX", "2026-03-31"] / px["AAA.MX", "2026-02-27"] - 1)
    assert per.loc["AAA.MX", "chg_pct"] == pytest.approx(expected, abs=0.01)
    assert per.loc["AAA.MX", "exceso_pp"] == pytest.approx(
        per.loc["AAA.MX", "chg_pct"] - per.loc["AAA.MX", "benchmark_chg_pct"], abs=0.02)
    assert equity.main(["ficha", "zzz"]) == 2
