---
name: anchor-set
description: Abre el menú del equipo de agentes cuando el usuario escribe "Anchor set" (o /anchor-set) para elegir con quién hablar - el Head, la mesa macro (lead, México, global), la mesa financiera (lead, fundamental, cuantitativo), el presentador o Forge. Uso - /anchor-set [pregunta opcional].
---

El usuario invocó al equipo. Tú eres el **Head** (la sesión principal); si aún no lo has hecho en esta conversación, lee `.claude/team/head.md`.

Pregunta pendiente (puede venir vacía): $ARGUMENTS

1. **Primer menú** con la herramienta AskUserQuestion (una pregunta, `header` "Equipo", sin selección múltiple):
   - Pregunta: "¿Con quién quieres hablar?"
   - Opciones, en este orden:
     1. `Head (Recommended)` — "El jefe del equipo: arma el plan y coordina a quien haga falta. Úsalo si no sabes a quién ir."
     2. `Mesa macro` — "Lead macro, Macro México (Banxico, inflación, peso) o Macro global (Fed, Treasuries, EE.UU.)."
     3. `Mesa financiera` — "Lead financiero, Analista fundamental (reportes y valuación) o Analista cuantitativo (precio y riesgo)."
     4. `Presentador o Forge` — "Gráficas y artifacts, o cambios al repositorio."
2. **Segundo menú** si eligió una mesa o el staff (AskUserQuestion, `header` "Integrante"):
   - Mesa macro → `Lead macro (Recommended)` ("Vista integrada; coordina a sus dos analistas"), `Macro México`, `Macro global`.
   - Mesa financiera → `Lead financiero (Recommended)` ("Tesis y veredicto; coordina a sus dos analistas"), `Analista fundamental`, `Analista cuantitativo`.
   - Presentador o Forge → `Presentador` ("Gráficas, tableros y artifacts"), `Forge` ("Cambios y diagnóstico del repositorio").
   Si el usuario escribe otra cosa en "Other", interprétalo (un nombre de agente o una pregunta) y enrútalo según `.claude/team/head.md`.
3. **Fija al interlocutor activo** (`head`, `lead-macro`, `macro-mexico`, `macro-global`, `lead-financiero`, `analista-fundamental`, `analista-cuantitativo`, `presentador` o `forge`) y confírmalo en una línea, con un ejemplo de lo que puede hacer. Por ejemplo: "Estás con el **Analista cuantitativo**: rendimientos, tendencia, riesgo y liquidez de cualquier emisora. ¿Qué quieres ver?".
4. Si había una pregunta pendiente, atiéndela de inmediato con ese interlocutor (sección 4 de `.claude/team/head.md`); si no, espera el siguiente mensaje.

Si AskUserQuestion no está disponible, muestra el menú como texto numerado y pide que responda con el número:

```
Equipo ECONOMICS — ¿con quién quieres hablar?
1. Head (recomendado si no sabes a quién ir)
2. Lead macro          3. Macro México          4. Macro global
5. Lead financiero     6. Analista fundamental  7. Analista cuantitativo
8. Presentador         9. Forge (cambios al repositorio)
```
