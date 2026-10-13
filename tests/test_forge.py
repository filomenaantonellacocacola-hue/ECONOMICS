"""El agente Forge y la guia de agentes deben describir el repo tal como es.

Si agregas un modulo, tarea, columna, vista, agente o skill y este test falla,
documentalo en .claude/agents/forge.md (y en CLAUDE.md cuando aplique).
"""
import re
from pathlib import Path

import pandas as pd

from econ import pipeline, query
from econ.present.build import CAT_KINDS, TIME_KINDS

ROOT = Path(__file__).resolve().parent.parent
FORGE = (ROOT / ".claude" / "agents" / "forge.md").read_text()
CLAUDE = (ROOT / "CLAUDE.md").read_text()
PRESENTADOR = (ROOT / ".claude" / "agents" / "presentador.md").read_text()


def _missing(names, text):
    return sorted(n for n in names if n not in text)


def test_forge_maps_every_module_and_presenter_file():
    files = [p for p in (ROOT / "econ").rglob("*") if p.is_file() and "__pycache__" not in p.parts]
    paths = [p.relative_to(ROOT).as_posix() for p in files if p.name != "__init__.py"]
    assert _missing(paths, FORGE) == []


def test_forge_documents_config_columns():
    for csv in ("universe.csv", "macro_series.csv"):
        assert f"config/{csv}" in FORGE
        cols = pd.read_csv(ROOT / "config" / csv, nrows=0).columns
        assert _missing([f"`{c}`" for c in cols], FORGE) == [], csv


def test_pipeline_tasks_match_workflow_and_docs():
    workflow = (ROOT / ".github" / "workflows" / "update-data.yml").read_text()
    options = re.search(r"options: \[([^\]]+)\]", workflow)[1]
    assert [o.strip() for o in options.split(",")] == list(pipeline.TASKS)
    assert _missing([f"`{t}`" for t in pipeline.TASKS], FORGE) == []


def test_agents_skills_and_workflows_are_registered():
    agents = [p.stem for p in (ROOT / ".claude" / "agents").glob("*.md")]
    skills = [p.name for p in (ROOT / ".claude" / "skills").iterdir() if (p / "SKILL.md").exists()]
    assert {"analista-macro", "presentador", "forge"} <= set(agents)
    assert _missing([f".claude/agents/{a}.md" for a in agents], FORGE) == []
    assert _missing([f"`{a}`" for a in agents], CLAUDE) == []  # tabla "Equipo de agentes"
    assert _missing([f".claude/skills/{s}" for s in skills], FORGE) == []
    assert _missing([f"/{s}" for s in skills], CLAUDE) == []
    workflows = [p.relative_to(ROOT).as_posix() for p in (ROOT / ".github" / "workflows").glob("*.yml")]
    assert _missing(workflows, FORGE) == []


def test_snapshot_outputs_are_documented():
    names = set()
    for module in ("snapshots.py", "pipeline.py"):
        names |= set(re.findall(r'"([a-z_]+\.(?:json|csv|md))"', (ROOT / "econ" / module).read_text()))
    assert names and _missing(names, FORGE) == []


def test_sql_views_and_chart_kinds_are_documented():
    assert _missing([f"`{v}" for v in query.DERIVED_VIEWS], CLAUDE) == []
    assert _missing([f"`{k}`" for k in TIME_KINDS | CAT_KINDS], PRESENTADOR) == []
