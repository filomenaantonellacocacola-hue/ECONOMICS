# ECONOMICS

Base de datos financiera y macroeconómica que se actualiza sola con GitHub Actions y se consulta con SQL, parecido a BigQuery pero gratis y dentro de este repo.

- **Mercado**: precios **diarios** (OHLCV) de emisoras de la **BMV** y del **SIC** (acciones y ETFs extranjeros), todo en pesos (`.MX`), más índices y tipos de cambio, desde Yahoo Finance.
- **Macro EE.UU.**: tasas de la Fed, curva de Treasuries, inflación, empleo, actividad, riesgo, desde **FRED**.
- **Macro México**: tasa objetivo, TIIE, CETES, tipo de cambio FIX e INPC, desde **Banxico (SIE)**.
- **Fundamentales**: corte semanal de valuación y rentabilidad (P/U, P/VL, EV/EBITDA, ROE, deuda…).
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
| `data/snapshots/` | `briefing.md`, `market_snapshot.csv`, `macro_snapshot.csv`, `macro_{monthly,quarterly,semiannual,annual}.csv`, `manifest.json`. |
| `sql/` | Consultas de ejemplo. |

Los datos se particionan por mes/año y solo se reescriben las particiones que cambian, así el repo crece poco con cada actualización diaria.

## Puesta en marcha

1. **Llaves gratuitas** (opcionales pero recomendadas). En GitHub: *Settings → Secrets and variables → Actions → New repository secret*:
   - `FRED_API_KEY`: https://fred.stlouisfed.org/docs/api/api_key.html (sin ella se usa el CSV público de FRED, menos estable).
   - `BANXICO_TOKEN`: https://www.banxico.org.mx/SieAPIRest/service/v1/token (sin él se omiten las series de Banxico).
2. **Fusiona esta rama a `main`**: los workflows programados solo corren desde la rama por defecto.
3. **Carga el histórico**: *Actions → Actualizar datos → Run workflow* con `task = backfill` (por defecto desde 2015-01-01), y después una vez con `task = fundamentals`. `backfill` descarga precios y macro, y además borra de `data/` los tickers que ya no estén en `config/universe.csv`.
4. Desde ese momento corre solo:
   - Lunes a viernes 23:30 UTC: precios de los últimos 10 días + macro + snapshots.
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

# Tests
python -m pytest -q
```

### Tablas y vistas disponibles

| Nombre | Descripción |
|---|---|
| `prices` | `date, ticker, open, high, low, close, adj_close, volume` |
| `prices_latest` | Último precio por ticker con mercado, nombre y cambio diario (`chg_1d`, %) |
| `macro` | `source, series_id, date, value` |
| `macro_latest` | Último dato por serie con nombre, categoría y unidades |
| `macro_monthly`, `macro_quarterly`, `macro_semiannual`, `macro_annual` | Macro agregada por periodo (ver abajo) |
| `macro_series` | Catálogo de series (`config/macro_series.csv`) |
| `fundamentals` / `fundamentals_latest` | Cortes semanales de fundamentales / el más reciente por ticker |
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
- Algunas réplicas del SIC operan poco: si un ticker no opera en México un día, ese día no tiene precio. Revisa `health.tickers_stale` en `data/snapshots/manifest.json`.

## Uso con agentes de IA

La idea es que los agentes **no** descarguen datos de internet: leen este repo. Orden de lectura recomendado, de menos a más tokens:

1. `data/snapshots/briefing.md`: resumen de una página (macro, índices, movers).
2. `data/snapshots/macro_snapshot.csv` y `market_snapshot.csv`: una fila por serie/emisora con rendimientos, volatilidad, RSI, distancia a máximos y a medias móviles.
3. `data/snapshots/macro_quarterly.csv` (y `_monthly`, `_semiannual`, `_annual`): una fila por serie y una columna por periodo (24 meses, 12 trimestres, 8 semestres, 10 años), con el valor y su variación anual.
4. `data/snapshots/manifest.json`: qué archivos Parquet existen y sus fechas.
5. Consultas SQL (`python -m econ.query ...`) para análisis a detalle.

Ver [`CLAUDE.md`](CLAUDE.md) para el diccionario de datos pensado para agentes.

> Si el repo es público, cualquier agente puede leer los snapshots vía `https://raw.githubusercontent.com/filomenaantonellacocacola-hue/ECONOMICS/main/data/snapshots/briefing.md`. Si es privado, necesitará un token de GitHub.

## Equipo de agentes (por chat)

Los agentes viven en el repo (`.claude/`), así que funcionan en cualquier sesión de Claude Code conectada a ECONOMICS. Se usan preguntando en el chat; no hay nada programado.

| Agente | Qué responde | Cómo usarlo |
|---|---|---|
| `analista-macro` | Tasas (Fed, Banxico, Treasuries, CETES), inflación de EE.UU. y México, empleo, PIB, riesgo, peso, IPC y S&P 500, en cualquier ventana: hoy, ayer, esta semana, semanas anteriores, un mes, trimestre, semestre, YTD o una fecha exacta | `/macro ¿cómo va la inflación en lo que va del año?` o simplemente pregunta en el chat |

Por debajo usa `python -m econ.macro`, que resuelve los periodos y devuelve tablas compactas:

```bash
python -m econ.macro panel                                   # último dato y cambios 1d/1s/1m/YTD/1a
python -m econ.macro change --period last-week --category tasas
python -m econ.macro change --period 2026-03 --series CPIAUCSL,SP1,MXN=X
python -m econ.macro series SF61745,DFEDTARU --freq M --period ytd
```

Periodos: `today`, `yesterday`, `wtd`, `last-week`, `mtd`, `last-month`, `qtd`, `last-quarter`, `ytd`, `last-year`, `1w`/`1m`/`3m`/`6m`/`1y`, `2026`, `2026-03`, `2026-Q1`, `2026-S1`, `2026-W38`, `2026-03-17` o `2026-01-15:2026-02-15`.

| `presentador` | Gráficas, tableros y reportes visuales como artifacts interactivos, siempre con el mismo estilo (TradingView oscuro / terminal Bloomberg) | `/presenta tablero de tasas Banxico vs Fed con la curva de Treasuries` |

Al iniciar cada sesión en la web, `.claude/hooks/session-start.sh` instala las dependencias de Python.

### Presentador: estilo fijo

El presentador no escribe HTML. Arma una especificación JSON (qué datos mostrar y con qué tipo de bloque) y `python -m econ.present` la convierte en una página con el mismo diseño siempre:

- **Series de tiempo** con [Lightweight Charts](https://www.tradingview.com/lightweight-charts/) de TradingView: cursor, zoom y arrastre, botones de rango (1M a MÁX), leyenda con lectura de valores y marcas de eventos.
- **Categorías** (rankings, curva de rendimientos) con ECharts, con los mismos colores y tipografía.
- **KPIs**, tablas ordenables y texto; cada gráfica tiene su vista de tabla.
- **El tema** (`econ/present/assets/theme.css`) es la única fuente de estilo. La especificación rechaza cualquier clave de color o tamaño, así que el estilo no puede variar entre reportes.

```bash
python -m econ.present econ/present/examples/tablero-tasas.json   # genera out/ejemplo-tablero-tasas.html
```

## Hoja de ruta

1. **Datos** (este paso): pipeline, base consultable y snapshots.
2. **Enriquecer**: dividendos y splits, estados financieros trimestrales, calendario de resultados, noticias y comunicados de Banxico/FOMC.
3. **Agentes**: analista macro, analista de renta variable (BMV/SIC), constructor de portafolios y gestor de riesgo, que lean los snapshots, consulten con SQL y dejen sus reportes en el repo.
4. **Portafolio**: registro de tus posiciones (`config/portfolio.csv`), seguimiento de rendimiento, rebalanceos y alertas.

> Este proyecto es una herramienta de información, no una recomendación de inversión.
