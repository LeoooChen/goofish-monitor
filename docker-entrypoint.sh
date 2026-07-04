#!/usr/bin/env bash
set -euo pipefail

mkdir -p data logs

if [[ -z "${GOOFISH_ADMIN_PASSWORD:-}" && -z "${GOOFISH_ADMIN_PASSWORD_HASH:-}" ]]; then
  echo "Set GOOFISH_ADMIN_PASSWORD or GOOFISH_ADMIN_PASSWORD_HASH in .env before starting."
  exit 1
fi

exec uvicorn backend.app.main:app \
  --host "${BACKEND_HOST:-0.0.0.0}" \
  --port "${BACKEND_PORT:-8000}"
