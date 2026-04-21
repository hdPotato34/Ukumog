#!/bin/sh
set -eu

UKUMOG_HOST="${UKUMOG_HOST:-127.0.0.1}"
UKUMOG_PORT="${UKUMOG_PORT:-8011}"
PORT="${PORT:-8787}"

python -m uvicorn app:app \
  --app-dir /app/model-server/src/serving \
  --host "$UKUMOG_HOST" \
  --port "$UKUMOG_PORT" &
PYTHON_PID=$!

cleanup() {
  kill "$PYTHON_PID" 2>/dev/null || true
}

trap cleanup EXIT INT TERM

node server.mjs
