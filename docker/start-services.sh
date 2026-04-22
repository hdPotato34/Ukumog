#!/bin/sh
set -eu

UKUMOG_HOST="${UKUMOG_HOST:-127.0.0.1}"
UKUMOG_PORT="${UKUMOG_PORT:-8011}"
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8787}"
ENGINE_SERVICE_TIMEOUT_MS="${ENGINE_SERVICE_TIMEOUT_MS:-15000}"
ENGINE_SERVICE_ORIGIN="${ENGINE_SERVICE_ORIGIN:-http://${UKUMOG_HOST}:${UKUMOG_PORT}}"

export HOST PORT ENGINE_SERVICE_TIMEOUT_MS ENGINE_SERVICE_ORIGIN

python -m uvicorn app:app \
  --app-dir /app/model-server/src/serving \
  --host "$UKUMOG_HOST" \
  --port "$UKUMOG_PORT" &
PYTHON_PID=$!

cleanup() {
  kill "$PYTHON_PID" 2>/dev/null || true
}

trap cleanup EXIT INT TERM

ATTEMPTS=0
until python -c "import os, sys, urllib.request; url=os.environ['ENGINE_SERVICE_ORIGIN'] + '/health'; resp=urllib.request.urlopen(url, timeout=3); sys.exit(0 if resp.status == 200 else 1)"; do
  ATTEMPTS=$((ATTEMPTS + 1))
  if [ "$ATTEMPTS" -ge 50 ]; then
    echo "Engine service failed to become healthy at ${ENGINE_SERVICE_ORIGIN}" >&2
    exit 1
  fi
  sleep 0.2
done

node server.mjs
