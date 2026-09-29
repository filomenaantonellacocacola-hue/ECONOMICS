---
name: presenta
description: Genera una gráfica, tablero o artifact interactivo con el estilo fijo de la casa (TradingView oscuro / terminal Bloomberg) a partir de los datos del repo. Uso - /presenta <qué quieres ver>.
---

1. Si la petición también pide análisis o explicación ("explícame y grafica..."), pide primero ese análisis al agente que corresponda (p.ej. `analista-macro`).
2. Delega en el subagente `presentador` (herramienta Agent, `subagent_type: "presentador"`). Pásale:
   - la petición: $ARGUMENTS
   - el análisis del paso 1, si lo hay, para su bloque de texto;
   - el contexto de la conversación necesario para que el encargo sea autocontenido.
3. Publica el HTML que devuelve con la herramienta Artifact. Usa `file_path` con la ruta devuelta, la `description` que devuelve e `icon: "chart"` en la primera publicación. Si esa misma vista ya se publicó en esta conversación, publica de nuevo la misma ruta para actualizar el mismo enlace. Si Artifact no está disponible, envía el archivo con SendUserFile (`display: "render"`).
4. Responde con el enlace y una o dos líneas de lo que muestra.

No escribas ni retoques el HTML: el estilo es fijo y vive en `econ/present/assets/`.
