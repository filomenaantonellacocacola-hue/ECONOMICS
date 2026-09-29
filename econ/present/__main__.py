"""CLI del presentador.

    python -m econ.present out/specs/tasas.json            # escribe out/<nombre>.html
    python -m econ.present spec.json -o out/mi-reporte.html
    cat spec.json | python -m econ.present -
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from econ.present.build import SpecError, build


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Genera un artifact HTML a partir de una especificación JSON")
    parser.add_argument("spec", help="Archivo JSON con la especificación, o - para leer de stdin")
    parser.add_argument("-o", "--out", help="Ruta del HTML (por defecto out/<file o título>.html)")
    parser.add_argument("--today", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    try:
        text = sys.stdin.read() if args.spec == "-" else Path(args.spec).read_text()
        spec = json.loads(text)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: no pude leer la especificación: {exc}", file=sys.stderr)
        return 2
    try:
        out, info = build(spec, Path(args.out) if args.out else None,
                          today=date.fromisoformat(args.today) if args.today else None)
    except SpecError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    size = out.stat().st_size / 1024
    print(f"OK {out} ({size:,.0f} KB)")
    print(f"title: {info['title']}")
    print(f"description: {info['description']}")
    print(f"datos al: {info['as_of']}")
    print(f"fuentes: {', '.join(info['sources'])}")
    print(f"bloques: {'; '.join(info['blocks'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
