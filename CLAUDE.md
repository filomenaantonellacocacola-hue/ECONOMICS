# Guía para agentes

Repo de datos financieros y macro (BMV, SIC, FRED, Banxico) que GitHub Actions actualiza los días hábiles. **Usa estos datos en lugar de buscarlos en internet.**

## Cómo ponerte al día (de menos a más tokens)

1. `data/snapshots/briefing.md`: resumen de una página.
2. `data/snapshots/macro_snapshot.csv`: `source, series_id, name, category, units, frequency, date, value, prev_value, chg_1y, pct_1y`.
   - `chg_1y` = cambio absoluto a 12 meses (en puntos porcentuales si `units = pct`).
   - `pct_1y` = cambio % a 12 meses, solo para niveles/índices (p.ej. CPI → inflación anual).
3. `data/snapshots/market_snapshot.csv`: una fila por ticker: `ticker, market, asset_type, name, date, close, chg_1d, chg_1w, chg_1m, chg_3m, chg_6m, chg_1y, chg_ytd, pct_from_52w_high, pct_from_52w_low, vol_30d, vs_sma50, vs_sma200, rsi14, avg_vol_20d`.
   - Todos los `chg_*`, `pct_*`, `vs_*` y `vol_30d` están en %. Los rendimientos usan precio ajustado (dividendos/splits).
   - `market`: `BMV` (en MXN), `SIC` (ticker de origen, normalmente en USD), `INDEX`, `FX` (`MXN=X` = pesos por dólar).
4. `data/snapshots/manifest.json`: rango de fechas, archivos Parquet y `health` (tickers/series sin datos).
5. SQL con DuckDB: `python -m econ.query "<SQL>"` (ver `python -m econ.query --tables` y `sql/`).

## Tablas SQL

- `prices(date, ticker, open, high, low, close, adj_close, volume)`
- `prices_latest(ticker, market, asset_type, name, date, close, volume, chg_1d)`
- `macro(source, series_id, date, value)`; `macro_latest(...)`; catálogo `macro_series(source, series_id, name, category, units, frequency)`
- `fundamentals(date, ticker, shortName, sector, industry, marketCap, trailingPE, forwardPE, priceToBook, enterpriseToEbitda, dividendYield, returnOnEquity, profitMargins, debtToEquity, revenueGrowth, earningsGrowth, freeCashflow, ...)`; `fundamentals_latest`
- `universe(ticker, market, asset_type, name, mx_ticker)`

## Reglas

- Cita siempre la fecha del dato (`date`); los datos macro tienen distinta frecuencia y rezago.
- No modifiques `data/` a mano: lo genera `python -m econ.pipeline`.
- Para agregar emisoras o series edita `config/universe.csv` o `config/macro_series.csv`.

## Desarrollo

- `python -m pytest -q` antes de hacer commit.
- Código en `econ/`: `sources/` (descarga), `storage.py` (Parquet particionado con upsert), `pipeline.py` (CLI), `snapshots.py`, `query.py`.
