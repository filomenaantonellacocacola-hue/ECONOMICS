"""El mapa visual (docs/mapa.html) debe reflejar el proyecto tal como es.

Si cambias el flujo (agente, skill, tarea, cron, dataset, resumen o modulo) y esto falla,
actualiza econ/mapa/spec.py y corre: python -m econ.mapa
"""
import json
import re
from pathlib import Path

from econ import pipeline, query
from econ.mapa import build

ROOT = Path(__file__).resolve().parent.parent
MODEL = build.model()
IDS = [n["id"] for n in MODEL["nodes"]]
TEXT = json.dumps(MODEL, ensure_ascii=False)


def _node(node_id):
    return next(n for n in MODEL["nodes"] if n["id"] == node_id)


def test_map_html_is_current():
    assert build.OUTPUT.exists(), "falta docs/mapa.html: corre python -m econ.mapa"
    assert build.OUTPUT.read_text() == build.render(), "docs/mapa.html no esta al dia: corre python -m econ.mapa"


def test_map_graph_is_consistent():
    assert len(IDS) == len(set(IDS))
    linked = set()
    for a, b, sa, sb, *_ in MODEL["edges"]:
        assert a in IDS and b in IDS, (a, b)
        assert sa in "rltb" and sb in "rltb"
        linked |= {a, b}
    assert set(IDS) == linked, "cada nodo necesita al menos una conexion"
    for flow in MODEL["flows"]:
        assert set(flow["n"]) <= set(IDS), flow["k"]
    assert "$" not in TEXT.replace("$VAR", ""), "quedo una $variable sin llenar"


def test_map_covers_team_and_skills():
    agents = [p.stem for p in (ROOT / ".claude" / "agents").glob("*.md")]
    assert set(agents) <= set(IDS), "agrega un nodo por agente en econ/mapa/spec.py"
    skills = [p.name for p in (ROOT / ".claude" / "skills").iterdir() if (p / "SKILL.md").exists()]
    detail = " ".join(_node("user")["l"])
    assert all(f"/{s}<" in detail for s in skills)


def test_map_covers_pipeline_and_workflows():
    detail = " ".join(_node("pipeline")["l"])
    assert all(f"<code>{t}</code>" in detail for t in pipeline.TASKS)
    workflow = (ROOT / ".github" / "workflows" / "update-data.yml").read_text()
    for cron in re.findall(r'cron:\s*"([^"]+)"', workflow):
        assert cron in TEXT, f"cron {cron} sin disparador en el mapa"
    for wf in (ROOT / ".github" / "workflows").glob("*.yml"):
        assert f".github/workflows/{wf.name}" in TEXT


def test_map_covers_data_and_modules():
    for name in query.DATASETS:
        assert name in IDS or f"data/{name}" in TEXT, f"dataset {name} sin nodo en el mapa"
    files = set()
    for module in ("snapshots.py", "pipeline.py"):
        files |= set(re.findall(r'"([a-z_]+\.(?:json|csv|md))"', (ROOT / "econ" / module).read_text()))
    assert files and all(f in TEXT for f in files)
    modules = [p for p in [*(ROOT / "econ").glob("*.py"), *(ROOT / "econ" / "sources").glob("*.py")]
               if p.name != "__init__.py"]
    modules.append(ROOT / "econ" / "present" / "build.py")
    modules.append(ROOT / "econ" / "mapa" / "spec.py")
    missing = [p.relative_to(ROOT).as_posix() for p in modules if p.relative_to(ROOT).as_posix() not in TEXT]
    assert missing == [], "menciona estos modulos en algun nodo"
