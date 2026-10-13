---
name: macro
description: Pregunta a la mesa macro (lead-macro con sus analistas macro-mexico y macro-global) sobre tasas, inflación, Fed, Banxico, empleo, PIB, riesgo, peso o índices en cualquier periodo, o pídele que te ponga al día. Uso - /macro <pregunta>; sin pregunta hace un resumen de la última semana.
---

Actúas como el Head (`.claude/team/head.md`) enrutando a la **mesa macro**.

- Pregunta: $ARGUMENTS
- Si no hay pregunta, usa: "Ponme al día: cómo cerró la última semana en macro y mercados (Banxico y Fed, Treasuries y CETES, inflación, peso, IPC y S&P 500, riesgo), qué cambió respecto a la semana previa y qué datos siguen pendientes de publicarse."

1. **Pregunta acotada de un solo país** (un dato, una serie, un periodo): encárgasela directo a `macro-mexico` o `macro-global` (modo directo) y muestra su respuesta completa.
2. **Pregunta amplia o que cruza México y EE.UU.** (ponme al día, qué esperar, cómo afecta X al peso): lanza en paralelo `macro-mexico` y `macro-global` en modo comité con su parte del encargo; luego pasa la pregunta y los dos memos completos a `lead-macro` y muestra su respuesta.

Incluye siempre la fecha de hoy y el contexto de la conversación que haga falta (p. ej. si preguntan "¿y en marzo?"). No resumas ni reinterpretes la respuesta del agente.
