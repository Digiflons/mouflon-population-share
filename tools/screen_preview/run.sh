#!/usr/bin/env bash
# Live preview of the e-ink screen (MOUL-57), started by the VS Code task
# "Aperçu écran e-ink". First run: creates a private Python environment
# (.venv-screen) and installs Pillow from the hash-pinned lock. Then it watches
# the renderer, fonts and sample data and regenerates docs/screen-preview/.
# No server, no other network access: Live Preview in VS Code shows the page.
set -euo pipefail
cd "$(dirname "$0")/../.."

VENV=.venv-screen
LOCK=tools/screen_preview/requirements.lock

find_python() {
  for candidate in python3.13 python3.12 python3.11 python3; do
    if command -v "$candidate" >/dev/null 2>&1 &&
      "$candidate" -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null; then
      echo "$candidate"
      return 0
    fi
  done
  return 1
}

if [ ! -x "$VENV/bin/python" ]; then
  if ! PYTHON=$(find_python); then
    echo "Python 3.11 ou plus récent est introuvable."
    echo "Installez-le depuis python.org (voir docs/install.md), puis relancez la tâche."
    exit 1
  fi
  echo "Première fois : création de l'environnement Python ($VENV)…"
  "$PYTHON" -m venv "$VENV"
fi

STAMP="$VENV/.lock-installed"
if [ ! -f "$STAMP" ] || ! cmp -s "$LOCK" "$STAMP"; then
  echo "Installation de Pillow (version épinglée et vérifiée)…"
  "$VENV/bin/python" -m pip install --quiet --disable-pip-version-check \
    --require-hashes --only-binary=:all: --no-deps -r "$LOCK"
  cp "$LOCK" "$STAMP"
fi

export PYTHONPATH=app/src
exec "$VENV/bin/python" -m mouflon_population.screen --watch \
  --input app/samples/detections.json --output docs/screen-preview \
  --library app/library
