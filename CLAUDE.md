# Guía para agentes

Repo de datos financieros y macro (BMV, SIC, FRED, Banxico, reportes de emisoras) que GitHub Actions actualiza los días hábiles. **Usa estos datos en lugar de buscarlos en internet.**

## Equipo de agentes

**Tú, la sesión principal, eres el Head**: el jefe del equipo y el único que habla con el usuario. Antes de orquestar lee `.claude/team/head.md` (rutas, comité de inversión, marco de decisión y formato). Las reglas comunes de todos los agentes están en `.claude/team/protocolo.md`.

**"Anchor set"**: si el usuario escribe "Anchor set" (con o sin pregunta), usa la skill `anchor-set` para mostrar el menú y elegir con quién hablar. El elegido queda como interlocutor activo hasta que pida otro.

| Mesa | Agente | Reporta a | Cubre | Atajo |
|---|---|---|---|---|
| — | Head (tú) | usuario | Plan de análisis, coordinación, veredicto final; si el usuario no sabe a quién ir | `/head`, `/anchor-set` |
| Macro | `lead-macro` | Head | Vista macro integrada, escenario, implicaciones para activos y sectores | `/macro` |
| Macro | `macro-mexico` | `lead-macro` | Banxico, TIIE, CETES, INPC, peso, agregados M1–M4, IPC | |
| Macro | `macro-global` | `lead-macro` | Fed, Treasuries, inflación y empleo de EE.UU., riesgo, dólar, petróleo, S&P 500 | |
| Financiera | `lead-financiero` | Head | Tesis por emisora, comparables, veredicto preliminar, ideas, portafolios | `/finanzas` |
| Financiera | `analista-fundamental` | `lead-financiero` | Estados financieros, valuación, rentabilidad, deuda, dividendos, consenso, reportes | |
| Financiera | `analista-cuantitativo` | `lead-financiero` | Rendimientos por periodo, tendencia, riesgo, beta, liquidez, correlaciones | |
| Staff | `presentador` | Head | Gráficas, tableros y artifacts (uno solo para todo el equipo) | `/presenta` |
| Staff | `forge` | usuario | Cambios y diagnóstico del repo, **solo por petición directa del usuario** | `/forge` |
| — | Mapa del proyecto | — | Mapa visual e interactivo de datos, pipeline y equipo (`docs/mapa.html`) | `/mapa` |

Reglas de mando:
- **Solo el usuario pide cambios.** Ningún agente pide cambios al Head ni a otro agente. Envía a `forge` solo peticiones explícitas del usuario; si un agente sugiere un cambio o reporta una brecha de datos, díselo al usuario como sugerencia y no actúes.
- **La jerarquía la ejecutas tú** (los subagentes no llaman a otros): analistas en paralelo → su lead con los memos completos → tu integración. Ruta más ligera que dé una respuesta completa: un dato puntual va directo al analista; "¿compro o vendo?" va a comité (las dos mesas).
- **Comunicación piramidal**: primero lo que se preguntó (cifra o veredicto con fecha), luego el soporte, y el detalle si lo piden. El análisis siempre es completo.
- Si el usuario eligió a un agente, muestra su respuesta completa. Para seguimientos, continúa al mismo agente con `SendMessage`.
- Gráficas o artifacts: si también piden análisis, obtenlo primero; luego pásalo al `presentador`, que devuelve `out/<nombre>.html`. Publícalo con la herramienta Artifact (`icon: "chart"` la primera vez; la misma ruta para actualizar el mismo enlace). Nunca escribas HTML/CSS de reportes a mano: el estilo es fijo y vive en `econ/present/assets/` (terminal Bloomberg).

## Cómo ponerte al día (de menos a más tokens)

1. `data/snapshots/briefing.md`: resumen de una página (macro, índices, movers y reportes trimestrales de las próximas 2 semanas).
2. `data/snapshots/macro_snapshot.csv`: `source, series_id, name, category, units, frequency, date, value, prev_value, chg_1y, pct_1y`.
   - `chg_1y` = cambio absoluto a 12 meses (en puntos porcentuales si `units = pct`).
   - `pct_1y` = cambio % a 12 meses, solo para niveles/índices (p.ej. CPI → inflación anual).
3. `data/snapshots/macro_{monthly,quarterly,semiannual,annual}.csv`: tablas anchas con los últimos 24 meses / 12 trimestres / 8 semestres / 10 años.
   - Columnas: `source, series_id, name, units, agg, metric, <periodos...>, partial`.
   - `metric = value` es el valor del periodo (`agg`: `avg` = promedio, `last` = último dato). `metric = pct_yoy` es el cambio % contra el mismo periodo del año anterior (solo para niveles/índices; p.ej. CPI → inflación anual).
   - `partial` lista los periodos incompletos; no los compares como si fueran definitivos.
4. `data/snapshots/market_snapshot.csv`: una fila por ticker: `ticker, market, asset_type, name, date, close, chg_1d, chg_1w, chg_1m, chg_3m, chg_6m, chg_1y, chg_ytd, pct_from_52w_high, pct_from_52w_low, vol_30d, vs_sma50, vs_sma200, rsi14, avg_vol_20d`.
   - Todos los `chg_*`, `pct_*`, `vs_*` y `vol_30d` están en %. Los rendimientos usan precio ajustado (dividendos/splits).
   - `market`: `BMV` (en MXN), `SIC` (réplica en la BMV, en MXN; `ref_ticker` = ticker de origen), `INDEX`, `FX` (`MXN=X` = pesos por dólar).
5. `data/snapshots/equity_snapshot.csv`: una fila por acción, FIBRA o ETF (BMV y SIC) con todo ya normalizado: rendimientos, `mom_12_1`, riesgo (`vol_1y`, `downside_vol_1y`, `max_dd_1y`, `max_dd_3y`, `beta_2y`, `corr_2y`, `var95_1d`, `cvar95_1d`, `skew_1y`, `kurt_1y`, `sharpe_1y`, `sortino_1y`, `rf_pct`), fuerza relativa (`rs_3m`, `rs_1y`), liquidez (`avg_value_20d_mxn_mm`, `traded_days_pct_3m`), dividendos (`div_12m`, `div_yield_12m_pct`), valuación (`mkt_cap_mxn_bn`, `pe`, `fwd_pe`, `peg`, `pb`, `ps`, `ev_ebitda`, `ev_sales`, `earnings_yield_pct`, `fcf_yield_pct`, `div_yield_pct`, `payout_pct`), rentabilidad y balance (`roe_pct`, `roa_pct`, márgenes `*_margin_pct`, `rev_growth_pct`, `eps_growth_pct`, `debt_to_equity`, `net_debt_ebitda`, `current_ratio`), analistas (`target_mean`, `target_upside_pct`, `rec_mean`, `rec_key`, `n_analysts`, `rec_buy_pct`, `rec_sell_pct`), tenencia (`insiders_pct`, `institutions_pct`), reportes (`next_earnings`, `last_earnings`, `last_surprise_pct`, `beats_4q`, `last_quarter`), puntajes (`score_value`, `score_quality`, `score_momentum`, `score_risk`: percentil 0–100 en su mercado, más alto = mejor), `data_flags`, monedas (`quote_currency`, `fin_currency`) y `fund_date`.
   - Unidades: `*_pct` y `chg_*` en %, múltiplos en veces (`debt_to_equity = 0.35`), `rs_*` en pp. Diccionario completo: `python -m econ.equity columnas`.
   - Benchmark: BMV → IPC (`^MXX`); SIC → `SPY.MX`. La beta es semanal de 2 años. `rf_pct` = CETES 28 promedio de 1 año.
   - SIC: precio en MXN, pero múltiplos, estados y precio objetivo del ticker de origen en su moneda.
   - `data_flags`: splits que Yahoo no ajustó en las `.MX` (ya corregidos en snapshots, `econ.equity` y gráficas), saltos raros, "poco operada", "historia corta". La tabla `prices` es cruda.
6. `data/snapshots/manifest.json`: rango de fechas, archivos Parquet y `health` (tickers/series sin datos, `company_coverage` = emisoras con estados financieros). `data/snapshots/last_run.json`: última corrida del pipeline (tarea, pasos, errores y advertencias).
7. Consultas macro por periodo: `python -m econ.macro panel | change --period <p> | series <ids> --freq <D|W|M|Q|S|A> | list` (incluye índices y FX de mercado).
8. Emisoras: `python -m econ.equity ficha <ticker> | estados <ticker> [--freq Q] | screen --where "..." | compare <t1 t2...> | peers <ticker> | periodo <tickers> --period <p> | dividendos <ticker> | buscar <texto> | columnas`. Resuelve `WALMEX` → `WALMEX.MX`, `AAPL` → `AAPL.MX`, "banorte" → `GFNORTEO.MX`. Si `equity_snapshot.csv` aún no existe, lo calcula al vuelo.
9. SQL con DuckDB: `python -m econ.query "<SQL>"` (ver `python -m econ.query --tables` y `sql/`).
10. Visualizaciones: `python -m econ.present <spec.json>` genera un artifact HTML interactivo (ver `.claude/agents/presentador.md`).

## Tablas SQL

- `prices(date, ticker, open, high, low, close, adj_close, volume, dividend, split)`; `dividend` y `split` existen en los precios bajados con eventos corporativos (tras un `backfill`).
- `prices_latest(ticker, market, asset_type, name, date, close, volume, chg_1d)`
- `dividends(date, ticker, market, name, dividend, close, yield_pct)`: pagos por acción en MXN (fecha ex-dividendo); solo si `prices` tiene la columna `dividend`.
- `macro(source, series_id, date, value)`; `macro_latest(...)`; catálogo `macro_series(source, series_id, name, category, units, frequency)`
- `macro_monthly`, `macro_quarterly`, `macro_semiannual`, `macro_annual(source, series_id, name, category, units, frequency, agg, period, period_label, is_partial, n_obs, value, last, avg, min, max, chg_prev, pct_prev, chg_yoy, pct_yoy)`
- `fundamentals(date, ticker, shortName, longName, sector, industry, currency, financialCurrency, marketCap, trailingPE, forwardPE, priceToBook, enterpriseToEbitda, dividendYield, returnOnEquity, profitMargins, debtToEquity, revenueGrowth, earningsGrowth, freeCashflow, targetMeanPrice, recommendationMean, ...)`; `fundamentals_latest`. Escalas crudas de Yahoo (`dividendYield` en %, razones en fracción, `debtToEquity` ×100): para análisis usa `equity_snapshot`.
- `financials(ticker, statement, freq, period_end, item, value)`: estados financieros completos; `statement` = `income`, `balance`, `cashflow`; `freq` = `A` (anual) o `Q` (trimestral); `item` con la clave de Yahoo (`TotalRevenue`, `EBITDA`, `NetIncomeCommonStockholders`, `DilutedEPS`, `TotalDebt`, `NetDebt`, `FreeCashFlow`...); montos en la moneda de reporte (`financialCurrency`).
- `earnings(ticker, date, eps_estimate, eps_reported, surprise_pct)`: fechas de reporte (pasadas y próximas).
- `recommendations(date, ticker, strong_buy, buy, hold, sell, strong_sell)`; `recommendations_latest`.
- `company_log(date, ticker, symbol, status, financial_rows, earnings_rows, recommendations, error)`: bitácora de descargas de reportes.
- `universe(ticker, market, asset_type, name, ref_ticker)`
- `market_snapshot`, `macro_snapshot`, `equity_snapshot`: los CSV de `data/snapshots/` como tablas (una fila por ticker / serie)

## Reglas

- Cita siempre la fecha del dato (`date`, `period_end`, `fund_date`); los datos tienen distinta frecuencia y rezago.
- No modifiques `data/` a mano: lo genera `python -m econ.pipeline`.
- Para agregar emisoras o series edita `config/universe.csv` o `config/macro_series.csv` (vía `forge`, a petición del usuario).

## Desarrollo

- Si cambias el flujo (agente, skill, tarea, cron, dataset, resumen, módulo o la configuración), regenera el mapa visual con `python -m econ.mapa` (y edita `econ/mapa/spec.py` si hace falta); `tests/test_mapa.py` lo exige.
- `python -m pytest -q` antes de hacer commit. `tests/test_forge.py` exige que `.claude/agents/forge.md` (el mapa del repo) y este archivo describan cada módulo, tarea, columna, vista, agente y skill, y que el bloque de `.claude/team/protocolo.md` esté idéntico en cada agente.
- Código en `econ/`: `sources/` (descarga), `storage.py` (Parquet particionado con upsert), `pipeline.py` (CLI), `snapshots.py`, `equity.py` (emisoras), `query.py`, `macro.py` (consultas por periodo), `present/` (artifacts), `mapa/` (mapa visual del proyecto).
- El estilo visual solo se cambia en `econ/present/assets/` y aplica a todos los reportes; la paleta de series está validada para daltonismo y contraste sobre el panel negro `#000000`.
