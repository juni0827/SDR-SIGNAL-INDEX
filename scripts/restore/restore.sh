#!/usr/bin/env bash
set -euo pipefail

archive="${1:?Usage: restore.sh /absolute/path/to/backup.tar.gz}"
if [[ ! -f "${archive}" ]]; then
  echo "Backup archive does not exist: ${archive}" >&2
  exit 2
fi
workdir="$(mktemp -d)"
trap 'rm -rf "${workdir}"' EXIT
tar -xzf "${archive}" -C "${workdir}"
root="$(find "${workdir}" -mindepth 1 -maxdepth 1 -type d | head -n 1)"
(cd "${root}" && sha256sum -c SHA256SUMS)
docker compose exec -T postgres dropdb -U signal --if-exists signal
docker compose exec -T postgres createdb -U signal signal
docker compose exec -T postgres pg_restore -U signal -d signal --clean --if-exists < "${root}/database.dump"
docker compose cp "${root}/objects/." minio:/data/
echo "Restore completed with checksum verification."
