# ECONOMICS

Base de datos financiera y macroeconómica que se actualiza sola con GitHub Actions y se consulta con SQL, parecido a BigQuery pero gratis y dentro de este repo.

- **Mercado**: precios **diarios** (OHLCV) de emisoras de la **BMV** y del **SIC** (acciones y ETFs extranjeros), todo en pesos (`.MX`), más índices y tipos de cambio, desde Yahoo Finance.
- **Macro EE.UU.**: tasas de la Fed, curva de Treasuries, inflación, empleo, actividad, riesgo, desde **FRED**.
- **Macro México**: tasa objetivo, TIIE, CETES, tipo de cambio FIX e INPC, desde **Banxico (SIE)**.
- **Fundamentales**: corte semanal de valuación, rentabilidad, deuda, perfil de la empresa y consenso de analistas (P/U, P/VL, EV/EBITDA, ROE, precio objetivo…).
- **Reportes de emisoras**: estados financieros anuales y trimestrales completos (resultados, balance y flujo), fechas de reporte con sorpresas de utilidades y recomendaciones de analistas; dividendos y splits en la serie de precios.
- **Estadística por emisora**: riesgo (volatilidad, máximas caídas, beta, VaR, Sharpe/Sortino), fuerza relativa, liquidez, valuación normalizada y puntajes de valor, calidad, momentum y riesgo en `equity_snapshot.csv`, más el CLI `python -m econ.equity` (ficha, estados, screener, comparables).
- **Macro en 4 frecuencias**: además del dato original (diario, semanal, mensual o trimestral), vistas **mensual, trimestral, semestral y anual** con variación contra el periodo anterior y contra el año anterior.
- **Snapshots para agentes**: resúmenes compactos (`data/snapshots/`) para que un agente de IA se ponga al día leyendo unos pocos KB en lugar de descargar todo.

## Arquitectura

```
Yahoo Finance ─┐
FRED ──────────┼─> econ/pipeline.py ─> data/*.parquet ─> DuckDB (SQL) ─> tú / notebooks
Banxico SIE ───┘        │                                   │
                        └─> data/snapshots/ (CSV, MD, JSON) ─┴─> agentes de IA
          (GitHub Actions lo corre todos los días hábiles y hace commit de los datos)
```

| Carpeta | Contenido |
|---|---|
| `config/universe.csv` | Universo de tickers (BMV, SIC, índices, FX). **Aquí agregas o quitas emisoras.** |
| `config/macro_series.csv` | Series macro de FRED y Banxico y su regla de agregación (`agg`). **Aquí agregas indicadores.** |
| `econ/` | Código: fuentes (`sources/`), almacenamiento, pipeline, snapshots y consultas. |
| `data/prices/AAAA-MM/` | Precios diarios, un Parquet por mes. |
| `data/macro/AAAA/` | Observaciones macro en formato largo, un Parquet por año. |
| `data/fundamentals/AAAA-MM/` | Cortes semanales de fundamentales. |
| `data/financials/<ticker>/` | Estados financieros anuales y trimestrales, un Parquet por emisora (solo se reescribe la emisora que cambia). |
| `data/earnings/AAAA/`, `data/recommendations/AAAA-MM/`, `data/company_log/AAAA-MM/` | Fechas de reporte y sorpresas, recomendaciones de analistas y bitácora de descargas. |
| `data/snapshots/` | `briefing.md`, `market_snapshot.csv`, `equity_snapshot.csv`, `macro_snapshot.csv`, `macro_{monthly,quarterly,semiannual,annual}.csv`, `manifest.json`. |
| `sql/` | Consultas de ejemplo. |

Los datos se particionan por mes/año y solo se reescriben las particiones que cambian, así el repo crece poco con cada actualización diaria.

## Puesta en marcha

1. **Llaves gratuitas** (opcionales pero recomendadas). En GitHub: *Settings → Secrets and variables → Actions → New repository secret*:
   - `FRED_API_KEY`: https://fred.stlouisfed.org/docs/api/api_key.html (sin ella se usa el CSV público de FRED, menos estable).
   - `BANXICO_TOKEN`: https://www.banxico.org.mx/SieAPIRest/service/v1/token (sin él se omiten las series de Banxico).
2. **Fusiona esta rama a `main`**: los workflows programados solo corren desde la rama por defecto.
3. **Carga el histórico**: *Actions → Actualizar datos → Run workflow* con `task = backfill` (por defecto desde 2015-01-01; trae también dividendos y splits), y después una vez con `task = fundamentals` y otra con `task = company`. `backfill` descarga precios y macro, y además borra de `data/` los tickers que ya no estén en `config/universe.csv`.
4. Desde ese momento corre solo:
   - Lunes a viernes 23:30 UTC: precios de los últimos 10 días + macro + snapshots.
   - Lunes a sábado 11:15 UTC: reportes (estados financieros, fechas de reporte, recomendaciones) de un lote de ~60 emisoras, empezando por las que nunca se han bajado o tienen los datos más viejos; el universo completo se cubre en unos 5 días y luego se refresca solo.
   - Sábados: fundamentales.
5. Revisa `data/snapshots/manifest.json` → `health.tickers_missing`: lista los tickers que Yahoo no reconoció, para corregirlos en `config/universe.csv`.

## Uso local

```bash
pip install -r requirements.txt

# Actualizar datos
python -m econ.pipeline daily
python -m econ.pipeline backfill --start 2020-01-01
python -m econ.pipeline prices --tickers WALMEX.MX,AAPL --days 30

# Consultar con SQL
python -m econ.query --tables
python -m econ.query "SELECT * FROM prices_latest WHERE market = 'BMV' ORDER BY chg_1d DESC LIMIT 10"
python -m econ.query -f sql/curva_rendimientos.sql
python -m econ.query -f sql/momentum_bmv.sql --format csv > momentum.csv

# Emisoras
python -m econ.pipeline company --limit 20              # reportes de un lote de emisoras
python -m econ.equity ficha WALMEX                      # todo de una emisora
python -m econ.equity estados AAPL --freq Q             # estados trimestrales con TTM
python -m econ.equity screen --market BMV --where "pe < 12 and roe_pct > 15" --sort score_value
python -m econ.equity periodo WALMEX AMX --period ytd   # rendimiento contra su benchmark

# Tests
python -m pytest -q
```

### Tablas y vistas disponibles

| Nombre | Descripción |
|---|---|
| `prices` | `date, ticker, open, high, low, close, adj_close, volume, dividend, split` |
| `dividends` | Pagos de dividendos por acción (fecha ex-dividendo) con su rendimiento |
| `prices_latest` | Último precio por ticker con mercado, nombre y cambio diario (`chg_1d`, %) |
| `macro` | `source, series_id, date, value` |
| `macro_latest` | Último dato por serie con nombre, categoría y unidades |
| `macro_monthly`, `macro_quarterly`, `macro_semiannual`, `macro_annual` | Macro agregada por periodo (ver abajo) |
| `macro_series` | Catálogo de series (`config/macro_series.csv`) |
| `fundamentals` / `fundamentals_latest` | Cortes semanales de fundamentales / el más reciente por ticker (escalas crudas de Yahoo) |
| `financials` | Estados financieros en formato largo: `ticker, statement, freq, period_end, item, value` |
| `earnings` | Fechas de reporte con UPA estimada, reportada y sorpresa (%) |
| `recommendations` / `recommendations_latest` | Conteo mensual de recomendaciones de analistas |
| `company_log` | Bitácora de descargas de reportes por emisora |
| `market_snapshot`, `equity_snapshot`, `macro_snapshot` | Los resúmenes de `data/snapshots/` como tablas (en `equity_snapshot` todo está normalizado: % en %, múltiplos en veces) |
| `universe` | Catálogo de tickers (`config/universe.csv`) |

## Macro mensual, trimestral, semestral y anual

Las vistas `macro_monthly`, `macro_quarterly`, `macro_semiannual` y `macro_annual` se calculan al vuelo a partir de los datos originales, así que siempre coinciden con ellos y no ocupan espacio extra en el repo.

| Columna | Significado |
|---|---|
| `period`, `period_label` | Inicio del periodo y etiqueta (`2026-09`, `2026-Q3`, `2026-S2`, `2026`) |
| `value` | Valor del periodo según la regla `agg` de la serie: `avg` (promedio del periodo) o `last` (último dato) |
| `last`, `avg`, `min`, `max`, `n_obs` | Estadísticos del periodo |
| `chg_prev`, `pct_prev` | Cambio absoluto y % contra el periodo anterior |
| `chg_yoy`, `pct_yoy` | Cambio absoluto y % contra el mismo periodo del año anterior (p.ej. inflación anual) |
| `is_partial` | `true` si el periodo aún no tiene todos sus datos publicados |

Reglas:
- Los cambios % (`pct_*`) solo se calculan para niveles e índices; para tasas en % usa `chg_*` (puntos porcentuales).
- Una serie no se baja a una frecuencia más fina que la original: el PIB (trimestral) no aparece en `macro_monthly`.
- `agg = last` se usa para tasas objetivo, saldos (balance de la Fed, M2) y el S&P 500; el resto usa promedio. Puedes cambiarlo en `config/macro_series.csv`.

```bash
python -m econ.query -f sql/macro_trimestral.sql
python -m econ.query "SELECT * FROM macro_annual WHERE series_id = 'CPIAUCSL'" --format csv > cpi_anual.csv
```

## Notas sobre el universo

- **BMV**: tickers de Yahoo con sufijo `.MX` (p.ej. `WALMEX.MX`, `GFNORTEO.MX`). Incluye emisoras del IPC, otras líquidas, FIBRAs y el NAFTRAC.
- **SIC**: réplica en pesos que cotiza en la BMV, con sufijo `.MX` y sin guiones (`AAPL.MX`, `BRKB.MX`, `VOO.MX`). La columna `ref_ticker` guarda el ticker de la bolsa de origen (`AAPL`, `BRK-B`); se usa para los fundamentales, porque en la réplica `.MX` los múltiplos mezclarían precio en pesos con utilidades en dólares.
- El universo incluye ~230 acciones del SIC (S&P 100, tecnológicas grandes, ADRs relevantes) y ~70 ETFs. Para agregar más, añade filas a `config/universe.csv`: la actualización diaria detecta los tickers nuevos y descarga su histórico completo sola.
- Las claves del SIC no siempre son el ticker de origen: las extranjeras suelen llevar `N` (`TSMN.MX`, `BABAN.MX`, `MELIN.MX`) y algunas series `C` (`DELLC.MX`). Si un ticker aparece en `health.tickers_missing`, corre la tarea `resolve`: prueba esas variantes, acepta solo la que tenga un precio consistente con `precio de origen × USD/MXN`, corrige `config/universe.csv` y baja el histórico. El detalle queda en `data/snapshots/symbol_resolution.json`.
- Algunas réplicas del SIC operan poco: si un ticker no opera en México un día, ese día no tiene precio. Revisa `health.tickers_stale` en `data/snapshots/manifest.json` y `traded_days_pct_3m` / `data_flags` en `equity_snapshot.csv`.
- Yahoo a veces no registra los splits de las réplicas `.MX` (p. ej. los ETFs sectoriales en dic-2025). Los snapshots, `econ.equity` y las gráficas los corrigen solos cuando el salto es un cociente común (2:1, 1:20…) y lo anotan en `data_flags`; la tabla `prices` queda cruda.

## Uso con agentes de IA

La idea es que los agentes **no** descarguen datos de internet: leen este repo. Orden de lectura recomendado, de menos a más tokens:

1. `data/snapshots/briefing.md`: resumen de una página (macro, índices, movers).
2. `data/snapshots/macro_snapshot.csv`, `market_snapshot.csv` y `equity_snapshot.csv`: una fila por serie/emisora con rendimientos, riesgo, valuación, analistas y puntajes.
3. `data/snapshots/macro_quarterly.csv` (y `_monthly`, `_semiannual`, `_annual`): una fila por serie y una columna por periodo (24 meses, 12 trimestres, 8 semestres, 10 años), con el valor y su variación anual.
4. `data/snapshots/manifest.json`: qué archivos Parquet existen y sus fechas.
5. Consultas SQL (`python -m econ.query ...`) para análisis a detalle.

Ver [`CLAUDE.md`](CLAUDE.md) para el diccionario de datos pensado para agentes.

> Si el repo es público, cualquier agente puede leer los snapshots vía `https://raw.githubusercontent.com/filomenaantonellacocacola-hue/ECONOMICS/main/data/snapshots/briefing.md`. Si es privado, necesitará un token de GitHub.

## Equipo de agentes (por chat)

Los agentes viven en el repo (`.claude/`), así que funcionan en cualquier sesión de Claude Code conectada a ECONOMICS. Se usan por chat; no hay nada programado.

**Cómo empezar**: escribe **Anchor set** y elige con quién hablar en el menú. Si no sabes a quién ir, elige al **Head**.

```
Usuario
  └─ Head (la sesión principal: plan, coordinación y veredicto final)
       ├─ Mesa macro ─ lead-macro
       │                 ├─ macro-mexico   (Banxico, TIIE, CETES, INPC, peso, M1–M4, IPC)
       │                 └─ macro-global   (Fed, Treasuries, inflación y empleo de EE.UU., riesgo, dólar, petróleo)
       ├─ Mesa financiera ─ lead-financiero
       │                 ├─ analista-fundamental  (estados financieros, valuación, dividendos, consenso)
       │                 └─ analista-cuantitativo (rendimientos, tendencia, riesgo, beta, liquidez)
       └─ Staff: presentador (gráficas y artifacts) · forge (cambios al repo, solo si tú los pides)
```

- **Jerarquía**: los analistas trabajan en paralelo y entregan memos a su lead; los leads integran y reportan al Head; el Head verifica, integra y responde. Para "¿compro o vendo X?" el Head arma un comité con las dos mesas y da un veredicto (Compra, Acumular, Mantener, Reducir o Venta) con convicción, horizonte, catalizadores, riesgos y qué cambiaría la vista.
- **Solo tú pides cambios**: ningún agente le pide cambios al Head ni a otro agente. Si un agente detecta que falta un dato, el Head te lo sugiere y tú decides si Forge lo agrega.
- **Respuestas en pirámide**: primero lo que preguntaste (la cifra o el veredicto con su fecha), luego el soporte y, si pides "más a fondo", el detalle completo.
- **Hablar directo con alguien**: elígelo en el menú (p. ej. el analista cuantitativo para "¿cuánto subió AMX en marzo?") y queda activo hasta que digas "Anchor set" otra vez o pidas a otro.

| Atajo | Qué hace | Ejemplo |
|---|---|---|
| `Anchor set` o `/anchor-set` | Menú del equipo | `Anchor set` |
| `/head` | El Head arma el plan y coordina | `/head ¿compro WALMEX o KOF?` |
| `/macro` | Mesa macro (sin pregunta: resumen de la semana) | `/macro ¿cómo va la inflación en lo que va del año?` |
| `/finanzas` | Mesa financiera | `/finanzas compara los bancos de la BMV` |
| `/presenta` | Gráficas y artifacts | `/presenta tablero de tasas Banxico vs Fed con la curva de Treasuries` |
| `/forge` | Cambios o diagnóstico del repositorio | `/forge agrega la serie de desempleo de México` |
| `/mapa` | Mapa visual e interactivo del proyecto | `/mapa` |

Manual del Head: `.claude/team/head.md`. Protocolo común: `.claude/team/protocolo.md`. El hook `.claude/hooks/anchor_set.py` detecta "Anchor set" y `.claude/hooks/session-start.sh` instala las dependencias de Python al iniciar cada sesión en la web.

Herramientas que usan los agentes:

```bash
python -m econ.macro panel                                   # último dato y cambios 1d/1s/1m/YTD/1a
python -m econ.macro change --period last-week --category tasas
python -m econ.macro series SF61745,DFEDTARU --freq M --period ytd
python -m econ.equity ficha GFNORTEO                         # emisoras: ficha, estados, screen, compare, peers, periodo, dividendos
```

Periodos: `today`, `yesterday`, `wtd`, `last-week`, `mtd`, `last-month`, `qtd`, `last-quarter`, `ytd`, `last-year`, `1w`/`1m`/`3m`/`6m`/`1y`, `2026`, `2026-03`, `2026-Q1`, `2026-S1`, `2026-W38`, `2026-03-17` o `2026-01-15:2026-02-15`.

### Presentador: estilo fijo

El presentador no escribe HTML. Arma una especificación JSON (qué datos mostrar y con qué tipo de bloque) y `python -m econ.present` la convierte en una página con el mismo diseño siempre:

- **Series de tiempo** con [Lightweight Charts](https://www.tradingview.com/lightweight-charts/) de TradingView: cursor, zoom y arrastre, botones de rango (1M a MÁX), leyenda con lectura de valores y marcas de eventos.
- **Categorías** (rankings, curva de rendimientos) con ECharts, con los mismos colores y tipografía.
- **KPIs**, tablas ordenables y texto; cada gráfica tiene su vista de tabla.
- **El tema** (`econ/present/assets/theme.css`) es la única fuente de estilo. La especificación rechaza cualquier clave de color o tamaño, así que el estilo no puede variar entre reportes.

```bash
python -m econ.present econ/present/examples/tablero-tasas.json   # genera out/ejemplo-tablero-tasas.html
```

## Mapa del proyecto

[`docs/mapa.html`](docs/mapa.html) es un mapa interactivo de todo el proyecto, estilo editor de nodos: disparadores, fuentes, almacenamiento, resúmenes, equipo de agentes, herramientas y entregables. Ábrelo en el navegador (o pide `/mapa` en el chat): arrastra para moverte, usa la rueda para el zoom, haz clic en un nodo para ver su detalle y elige un recorrido ("Actualización diaria", "¿Compro o vendo?"…) para ver el flujo paso a paso.

Se genera desde el código con `python -m econ.mapa`: los crons salen del workflow y los conteos, tareas, skills y comandos salen del repo. Si el flujo cambia y el mapa no se regenera, las pruebas fallan, así que siempre está al día.

## Hoja de ruta

1. **Datos** (este paso): pipeline, base consultable y snapshots.
2. **Enriquecer** (hecho en parte): dividendos y splits, estados financieros, calendario de resultados y consenso. Pendiente: noticias y comunicados de Banxico/FOMC, precios de metales, PIB y empleo de México.
3. **Agentes** (hecho): equipo jerárquico con Head, mesa macro, mesa financiera, presentador y Forge.
4. **Portafolio**: registro de tus posiciones (`config/portfolio.csv`), seguimiento de rendimiento, rebalanceos y alertas.

> Este proyecto es una herramienta de información, no una recomendación de inversión.
