#!/bin/bash
# Instala las dependencias de Python para que el pipeline, las consultas SQL y los
# agentes funcionen desde el primer mensaje en Claude Code on the web.
set -euo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "${CLAUDE_PROJECT_DIR:-$(dirname "$0")/../..}"
python3 -m pip install --quiet --disable-pip-version-check --root-user-action=ignore -r requirements.txt
