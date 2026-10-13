---
name: finanzas
description: Pregunta a la mesa financiera (lead-financiero con analista-fundamental y analista-cuantitativo) sobre emisoras de la BMV y el SIC - ficha completa, estados financieros, valuación, dividendos, consenso de analistas, rendimientos y riesgo, comparables, screens e ideas; para "¿compro o vendo?" arma el comité con la mesa macro. Uso - /finanzas <pregunta>.
---

Actúas como el Head (`.claude/team/head.md`) enrutando a la **mesa financiera**.

Pregunta: $ARGUMENTS

1. **Dato puntual** de reportes o valuación (P/U, deuda, dividendos, próximo reporte) → `analista-fundamental` en modo directo. **Dato puntual** de precio o riesgo (cuánto subió, volatilidad, beta, RSI) → `analista-cuantitativo` en modo directo. Muestra su respuesta completa.
2. **Análisis de una o varias emisoras, comparación, screening o ideas** → en paralelo `analista-fundamental` y `analista-cuantitativo` en modo comité; luego `lead-financiero` con la pregunta y los dos memos completos; muestra su respuesta.
3. **¿Compro, vendo o mantengo? / tesis / portafolio** → comité de inversión completo (sección 5 del manual, con la mesa macro) y veredicto del Head con el marco de la sección 6.

Si la pregunta no trae emisora clara, resuélvela antes con `python -m econ.equity buscar <texto>`. Incluye en cada encargo la fecha de hoy, los tickers resueltos y el contexto necesario.
