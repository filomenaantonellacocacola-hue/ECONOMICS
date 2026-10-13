"""Genera el mapa visual del proyecto a partir del codigo y la configuracion.

    python -m econ.mapa                      # escribe docs/mapa.html (pagina completa)
    python -m econ.mapa --fragment out/mapa.html   # version para publicar como artifact
    python -m econ.mapa --check              # falla si docs/mapa.html no esta al dia

Los disparadores salen de ``.github/workflows/``; tareas, agentes, skills y conteos salen del
repo. El contenido editorial (nodos, conexiones y recorridos) vive en ``econ/mapa/spec.py``.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from string import Template

from econ import config
from econ.mapa import spec

ASSETS = Path(__file__).resolve().parent / "assets"
OUTPUT = config.ROOT / "docs" / "mapa.html"
WORKFLOWS = config.ROOT / ".github" / "workflows"
TITLE = "Mapa ECONOMICS"
FONTS = ("https://fonts.googleapis.com/css2?family=Sora:wght@400;500;600;700"
         "&family=IBM+Plex+Mono:wght@400;500&display=swap")
DAYS = {"*": "Diario", "1-5": "L–V", "1-6": "L–S", "0-6": "Diario", "6": "Sáb", "0": "Dom", "1": "Lun", "5": "Vie"}


def facts() -> dict[str, str]:
    """Datos del repo que se insertan en los textos del mapa (``$variable``)."""
    from econ import equity, pipeline, query

    universe = config.load_universe()
    series = config.load_macro_series()
    skills = sorted(p.name for p in (config.ROOT / ".claude" / "skills").iterdir() if (p / "SKILL.md").exists())
    tests = sorted(p.name for p in (config.ROOT / "tests").glob("test_*.py"))
    commands = re.findall(r'sub\.add_parser\("([a-z]+)"', (config.ROOT / "econ" / "equity.py").read_text())
    return {
        "n_tickers": str(len(universe)),
        "n_bmv": str(int((universe["market"] == "BMV").sum())),
        "n_sic": str(int((universe["market"] == "SIC").sum())),
        "n_series": str(len(series)),
        "n_calc": str(int((series["source"] == "CALC").sum())),
        "n_tasks": str(len(pipeline.TASKS)),
        "tasks": ", ".join(f"<code>{t}</code>" for t in pipeline.TASKS),
        "n_columns": str(len(equity.COLUMNS)),
        "n_tables": str(len(query.DATASETS) + len(query.SNAPSHOT_VIEWS) + len(query.DERIVED_VIEWS) + 2),
        "skills": ", ".join(f"<code>/{s}</code>" for s in skills),
        "test_files": ", ".join(f"<code>{t}</code>" for t in tests),
        "equity_cmds": ", ".join(f"<code>{c}</code>" for c in commands),
    }


def _when(cron: str) -> str:
    minute, hour, _, _, dow = cron.split()
    return f"{DAYS.get(dow, dow)} {int(hour):02d}:{int(minute):02d} UTC"


def workflow_triggers() -> tuple[list[dict], list[list]]:
    """Nodos y conexiones de los disparadores: crons y ejecucion manual de update-data.yml, push de tests.yml."""
    text = (WORKFLOWS / "update-data.yml").read_text()
    crons = re.findall(r'-\s*cron:\s*"([^"]+)"\s*(?:#\s*(.*))?', text)
    mapped = dict(re.findall(r'SCHEDULE" = "([^"]+)" \]; then TASK="([^"]+)"', text))
    options = re.search(r"options: \[([^\]]+)\]", text)[1]
    nodes, edges = [], []
    for cron, comment in crons:
        task = mapped.get(cron, "daily")
        detail = spec.TASK_TEXT.get(task, f"Corre la tarea {task} del pipeline.")
        nodes.append({"id": f"trigger-{task}", "c": "trigger", "ic": "clock", "tag": "cron", "t": f"Cron · {task}",
                      "s": _when(cron), "d": detail,
                      "l": [f"Programación: <code>{cron}</code>" + (f" ({comment.strip()})" if comment else ""),
                            "Solo corre desde <code>main</code>; GitHub suele arrancarlo con retraso"]})
        edges.append([f"trigger-{task}", "gha", "r", "l"])
    nodes.append({"id": "trigger-manual", "c": "trigger", "ic": "play", "tag": "manual", "t": "Run workflow",
                  "s": "Manual desde Actions",
                  "d": "Tú eliges la tarea en Actions → Actualizar datos.",
                  "l": [f"<code>{o.strip()}</code>: {spec.TASK_TEXT.get(o.strip(), '')}" for o in options.split(",")]})
    edges.append(["trigger-manual", "gha", "r", "l"])
    if (WORKFLOWS / "tests.yml").exists():
        nodes.append({"id": "trigger-push", "c": "trigger", "ic": "branch", "tag": "git", "t": "Push o PR",
                      "s": "Cambios al código",
                      "d": "Cada push o pull request corre las pruebas. Los cambios llegan a main cuando fusionas el PR.",
                      "l": ["<code>.github/workflows/tests.yml</code>"]})
        edges.append(["trigger-push", "tests", "r", "l"])
    z = spec.TRIGGER_ZONE
    step = (z["y1"] - z["y0"]) / max(1, len(nodes) - 1)
    for i, n in enumerate(nodes):
        n["x"], n["y"] = z["x"], round(z["y0"] + i * step)
    return nodes, edges


def _fill(value, values: dict[str, str]):
    if isinstance(value, str):
        return Template(value).safe_substitute(values)
    if isinstance(value, list):
        return [_fill(v, values) for v in value]
    if isinstance(value, dict):
        return {k: _fill(v, values) for k, v in value.items()}
    return value


def model() -> dict:
    """Todo lo que dibuja la pagina: grupos, nodos, conexiones y recorridos."""
    trig_nodes, trig_edges = workflow_triggers()
    values = facts()
    return {
        "groups": spec.GROUPS,
        "nodes": _fill(trig_nodes + spec.NODES, values),
        "edges": trig_edges + spec.EDGES,
        "flows": spec.FLOWS,
    }


def render(fragment: bool = False) -> str:
    css = (ASSETS / "mapa.css").read_text()
    js = (ASSETS / "mapa.js").read_text()
    body = (ASSETS / "mapa.body.html").read_text()
    data = json.dumps(model(), ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    head = (f"<title>{TITLE}</title>\n"
            f'<link rel="preconnect" href="https://fonts.googleapis.com">\n'
            f'<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>\n'
            f'<link rel="stylesheet" href="{FONTS}">\n<style>\n{css}</style>\n')
    content = (f"{body}\n<script type=\"application/json\" id=\"mapa-data\">{data}</script>\n"
               f"<script>\n{js}</script>\n")
    if fragment:
        return head + content
    return ("<!doctype html>\n<html lang=\"es\">\n<head>\n<meta charset=\"utf-8\">\n"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1, viewport-fit=cover\">\n"
            "<!-- Generado por python -m econ.mapa; no lo edites a mano (edita econ/mapa/spec.py). -->\n"
            f"{head}</head>\n<body>\n{content}</body>\n</html>\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Genera el mapa visual del proyecto")
    parser.add_argument("--fragment", metavar="RUTA", help="Escribe la version para artifact en RUTA")
    parser.add_argument("--check", action="store_true", help="Falla si docs/mapa.html no esta al dia")
    args = parser.parse_args(argv)
    if args.check:
        if not OUTPUT.exists() or OUTPUT.read_text() != render():
            print("docs/mapa.html no esta al dia: corre python -m econ.mapa", file=sys.stderr)
            return 1
        print("docs/mapa.html al dia")
        return 0
    if args.fragment:
        out = Path(args.fragment)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(render(fragment=True))
        print(out)
        return 0
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(render())
    print(OUTPUT.relative_to(config.ROOT))
    return 0
