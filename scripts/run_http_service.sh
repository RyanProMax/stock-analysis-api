#!/bin/zsh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$REPO_ROOT"
mkdir -p .cache/logs

if [[ -f .env ]]; then
  tmp_env="$(mktemp)"
  tr -d '\r' < .env > "$tmp_env"
  set -a
  source "$tmp_env"
  set +a
  rm "$tmp_env"
fi

export ENV=production
export PYTHONUNBUFFERED=1
export PYTHONPATH="$REPO_ROOT${PYTHONPATH:+:$PYTHONPATH}"

if [[ ! -x "$REPO_ROOT/.venv/bin/python" ]]; then
  echo "missing virtualenv python: $REPO_ROOT/.venv/bin/python" >&2
  exit 1
fi

exec "$REPO_ROOT/.venv/bin/python" -m uvicorn src.main:app --host 0.0.0.0 --port "${PORT:-8080}"
