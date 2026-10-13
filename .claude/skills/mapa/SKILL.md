---
name: mapa
description: Muestra el mapa visual e interactivo del proyecto ECONOMICS (disparadores, fuentes, almacenamiento, resúmenes, equipo de agentes y recorridos) como artifact. Uso - /mapa.
---

1. Genera la versión para artifact desde el código actual: `python -m econ.mapa --fragment out/mapa.html`.
2. Publícala con la herramienta Artifact (`file_path: out/mapa.html`, `icon: "flow"` la primera vez, `description`: "Mapa interactivo del proyecto ECONOMICS: datos, pipeline y equipo de agentes"). Si ya se publicó en esta conversación, publica la misma ruta para actualizar el mismo enlace.
3. Responde con el enlace y una línea: los recorridos de la barra superior iluminan cada flujo y un clic en un nodo muestra su detalle.

`docs/mapa.html` es la misma página para abrir en el navegador. Si el usuario pide cambiar el mapa, es un cambio al repo: va con `forge` (se edita `econ/mapa/spec.py` y se regenera con `python -m econ.mapa`).
