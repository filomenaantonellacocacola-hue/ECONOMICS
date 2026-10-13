#!/usr/bin/env python3
"""Hook UserPromptSubmit: si el mensaje dice "Anchor set", pide al Head abrir el menu del equipo.

Lee el evento (JSON) de stdin y, si la frase aparece, responde con ``additionalContext``.
Cualquier error se ignora para no bloquear nunca el mensaje del usuario.
"""
import json
import re
import sys

PATTERN = re.compile(r"\banchor[\s_-]*set\b", re.IGNORECASE)


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except Exception:  # noqa: BLE001
        return 0
    prompt = str(event.get("prompt", ""))
    match = PATTERN.search(prompt)
    if not match:
        return 0
    rest = (prompt[: match.start()] + prompt[match.end():]).strip(" \t\n:,.-")
    context = (
        "El usuario invoco al equipo con 'Anchor set'. Eres el Head: usa la skill `anchor-set` "
        "(herramienta Skill) para mostrar el menu y elegir con quien hablar"
        + (f"; despues atiende esta pregunta con el interlocutor elegido: {rest}" if rest else "")
        + "."
    )
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": context}},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
