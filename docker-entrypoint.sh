#!/usr/bin/env bash
set -euo pipefail

mkdir -p data logs

exec uvicorn backend.app.main:app \
  --host "${BACKEND_HOST:-0.0.0.0}" \
  --port "${BACKEND_PORT:-8000}"
