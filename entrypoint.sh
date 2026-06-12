#!/bin/sh
# Per-user workspaces under $DATA_DIR/users/ are created and seeded by app.py
# on first login; nothing to seed globally.
set -e

mkdir -p "${DATA_DIR:-/data}"

exec gunicorn \
  --worker-class gthread \
  --workers 1 \
  --threads 16 \
  --timeout 120 \
  --bind "0.0.0.0:${PORT:-8000}" \
  app:app
