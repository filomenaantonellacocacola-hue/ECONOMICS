---
name: forge
description: Pide un cambio o un diagnóstico del repositorio ECONOMICS al agente Forge (agregar o quitar datos, emisoras o series, nuevas fuentes, ajustes al pipeline, a GitHub Actions, al presentador o a los agentes, investigar fallas). Uso - /forge <petición>.
---

1. Delega en el subagente `forge` (herramienta Agent, `subagent_type: "forge"`) con la petición del usuario: $ARGUMENTS
   Incluye el contexto de la conversación que haga falta para que el encargo sea autocontenido (p. ej. claves o resultados ya encontrados).
2. Cuando regrese, revisa el resultado: `git status --short`, `git diff --stat` y `python -m pytest -q`.
3. Si hay cambios y la sesión tiene una rama de trabajo asignada, haz commit con un mensaje claro y push a esa rama, nunca directo a `main`. Si el usuario pidió solo revisar o diagnosticar, no hagas commit.
4. Responde al usuario con las cuatro secciones de Forge (Cambios, Validación, Pasos para el usuario, Supuestos y riesgos), en lenguaje claro. Si hay que fusionar un PR o correr una tarea en Actions, dile exactamente qué elegir en cada campo.
