#!/usr/bin/env bash
set -euo pipefail

backup_root="${BACKUP_DIR:-./backups}"
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
target="${backup_root}/signal-index-${timestamp}"
mkdir -p "${target}"

docker compose exec -T postgres pg_dump -U signal -d signal --format=custom > "${target}/database.dump"
docker compose exec -T minio mc mirror --overwrite "/data" "/tmp/signal-index-object-backup"
docker compose cp minio:/tmp/signal-index-object-backup "${target}/objects"
sha256sum "${target}/database.dump" > "${target}/SHA256SUMS"
find "${target}/objects" -type f -print0 | sort -z | xargs -0 sha256sum >> "${target}/SHA256SUMS"
tar -C "${backup_root}" -czf "${target}.tar.gz" "$(basename "${target}")"
echo "${target}.tar.gz"
