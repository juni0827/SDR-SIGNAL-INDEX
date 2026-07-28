#!/usr/bin/env bash
set -euo pipefail

# The application itself runs in Compose containers. Keeping the Codespace
# container dependency-free prevents the editor bootstrap from failing before
# the PWA can start. Native development dependencies remain available through
# `make install` when explicitly wanted.
if [ ! -f .env ]; then
  cp .env.example .env
fi

mkdir -p .codespaces
