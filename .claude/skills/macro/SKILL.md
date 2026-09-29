---
name: macro
description: Pregunta al analista macro del equipo (tasas, inflación, Fed, Banxico, empleo, PIB, riesgo, peso, índices) sobre cualquier periodo, o pídele que te ponga al día. Uso - /macro <pregunta>; sin pregunta hace un resumen de la última semana.
---

Delega en el subagente `analista-macro` (herramienta Agent, `subagent_type: "analista-macro"`) y pásale la pregunta del usuario tal cual, junto con la fecha de hoy:

- Pregunta: $ARGUMENTS
- Si no hay pregunta, pídele: "Ponme al día: cómo cerró la última semana en macro y mercados (Fed y Banxico, Treasuries, inflación, peso, IPC y S&P 500, riesgo), qué cambió respecto a la semana previa y qué datos siguen pendientes de publicarse."

Si la pregunta hace referencia a la conversación (p.ej. "¿y en marzo?"), incluye en el encargo el contexto necesario para que sea autocontenida.

Muestra al usuario la respuesta del analista completa, sin resumirla ni reinterpretarla.
