# ECONOMICS

Base de datos financiera y macroeconómica que se actualiza sola con GitHub Actions y se consulta con SQL, parecido a BigQuery pero gratis y dentro de este repo.

- **Mercado**: precios diarios (OHLCV) de emisoras de la **BMV**, del **SIC** (acciones y ETFs extranjeros), índices y tipos de cambio, desde Yahoo Finance.
- **Macro EE.UU.**: tasas de la Fed, curva de Treasuries, inflación, empleo, actividad, riesgo, desde **FRED**.
- **Macro México**: tasa objetivo, TIIE, CETES, tipo de cambio FIX e INPC, desde **Banxico (SIE)**.
- **Fundamentales**: corte semanal de valuación y rentabilidad (P/U, P/VL, EV/EBITDA, ROE, deuda…).
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
| `config/macro_series.csv` | Series macro de FRED y Banxico. **Aquí agregas indicadores.** |
| `econ/` | Código: fuentes (`sources/`), almacenamiento, pipeline, snapshots y consultas. |
| `data/prices/AAAA-MM/` | Precios diarios, un Parquet por mes. |
| `data/macro/AAAA/` | Observaciones macro en formato largo, un Parquet por año. |
| `data/fundamentals/AAAA-MM/` | Cortes semanales de fundamentales. |
| `data/snapshots/` | `briefing.md`, `market_snapshot.csv`, `macro_snapshot.csv`, `manifest.json`. |
| `sql/` | Consultas de ejemplo. |

Los datos se particionan por mes/año y solo se reescriben las particiones que cambian, así el repo crece poco con cada actualización diaria.

## Puesta en marcha

1. **Llaves gratuitas** (opcionales pero recomendadas). En GitHub: *Settings → Secrets and variables → Actions → New repository secret*:
   - `FRED_API_KEY`: https://fred.stlouisfed.org/docs/api/api_key.html (sin ella se usa el CSV público de FRED, menos estable).
   - `BANXICO_TOKEN`: https://www.banxico.org.mx/SieAPIRest/service/v1/token (sin él se omiten las series de Banxico).
2. **Fusiona esta rama a `main`**: los workflows programados solo corren desde la rama por defecto.
3. **Carga el histórico**: *Actions → Actualizar datos → Run workflow* con `task = backfill` (por defecto desde 2015-01-01), y después una vez con `task = fundamentals`.
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
| `macro_series` | Catálogo de series (`config/macro_series.csv`) |
| `fundamentals` / `fundamentals_latest` | Cortes semanales de fundamentales / el más reciente por ticker |
| `universe` | Catálogo de tickers (`config/universe.csv`) |

## Notas sobre el universo

- **BMV**: tickers de Yahoo con sufijo `.MX` (p.ej. `WALMEX.MX`, `GFNORTEO.MX`). Incluye emisoras del IPC, otras líquidas, FIBRAs y el NAFTRAC.
- **SIC**: se descarga el ticker de la bolsa de origen (p.ej. `AAPL`, en USD), que tiene mejor calidad de datos que la réplica en `.MX`. El precio aproximado en pesos es `precio_usd × MXN=X`. La columna `mx_ticker` guarda la clave con la que cotiza en el SIC.
- El SIC tiene miles de valores; el archivo arranca con ~150 de los más operados. Para agregar más, añade filas a `config/universe.csv`.

## Uso con agentes de IA

La idea es que los agentes **no** descarguen datos de internet: leen este repo. Orden de lectura recomendado, de menos a más tokens:

1. `data/snapshots/briefing.md`: resumen de una página (macro, índices, movers).
2. `data/snapshots/macro_snapshot.csv` y `market_snapshot.csv`: una fila por serie/emisora con rendimientos, volatilidad, RSI, distancia a máximos y a medias móviles.
3. `data/snapshots/manifest.json`: qué archivos Parquet existen y sus fechas.
4. Consultas SQL (`python -m econ.query ...`) para análisis a detalle.

Ver [`CLAUDE.md`](CLAUDE.md) para el diccionario de datos pensado para agentes.

> Si el repo es público, cualquier agente puede leer los snapshots vía `https://raw.githubusercontent.com/filomenaantonellacocacola-hue/ECONOMICS/main/data/snapshots/briefing.md`. Si es privado, necesitará un token de GitHub.

## Hoja de ruta

1. **Datos** (este paso): pipeline, base consultable y snapshots.
2. **Enriquecer**: dividendos y splits, estados financieros trimestrales, calendario de resultados, noticias y comunicados de Banxico/FOMC.
3. **Agentes**: analista macro, analista de renta variable (BMV/SIC), constructor de portafolios y gestor de riesgo, que lean los snapshots, consulten con SQL y dejen sus reportes en el repo.
4. **Portafolio**: registro de tus posiciones (`config/portfolio.csv`), seguimiento de rendimiento, rebalanceos y alertas.

> Este proyecto es una herramienta de información, no una recomendación de inversión.
