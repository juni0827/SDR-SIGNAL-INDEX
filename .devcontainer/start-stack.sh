#!/usr/bin/env bash
set -euo pipefail

if [ ! -f .env ]; then
  cp .env.example .env
fi

docker compose up -d --build postgres redis minio minio-init api web worker scheduler

for attempt in $(seq 1 60); do
  if curl --fail --silent --show-error http://localhost:8000/api/v1/health >/dev/null; then
    break
  fi
  if [ "$attempt" = "60" ]; then
    echo "Signal Index API did not become healthy within 120 seconds." >&2
    docker compose ps >&2
    docker compose logs --tail=100 api >&2
    exit 1
  fi
  sleep 2
done

# Seed only an empty development database. The query is deliberately inside the
# API container so its database URL always targets the Compose network.
if ! docker compose exec -T api python -c 'from signal_index.database import SessionLocal; from signal_index.models import User; s=SessionLocal(); print(s.query(User).count()); s.close()' | tail -1 | grep -qx '[1-9][0-9]*'; then
  docker compose exec -T api python scripts/seed/seed.py
fi
