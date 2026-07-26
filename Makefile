SHELL := /bin/bash
PYTHON ?= python3
COMPOSE ?= docker compose
PYTHONPATH := apps/api:packages/source_adapters:packages/signal_processing:workers/audio_processor

.PHONY: install infra migrate seed dev test test-integration lint typecheck e2e backup restore

install:
	npm install
	$(PYTHON) -m venv .venv
	.venv/bin/pip install --upgrade pip
	.venv/bin/pip install -e ".[dev,audio]"

infra:
	$(COMPOSE) up -d postgres redis minio minio-init

migrate:
	PYTHONPATH=$(PYTHONPATH) .venv/bin/alembic -c infra/migrations/alembic.ini upgrade head

seed:
	PYTHONPATH=$(PYTHONPATH) .venv/bin/python scripts/seed/seed.py

dev:
	$(COMPOSE) up --build

test:
	PYTHONPATH=$(PYTHONPATH) .venv/bin/pytest -m "not integration" -q
	npm test

test-integration:
	PYTHONPATH=$(PYTHONPATH) SIGNAL_INDEX_INTEGRATION=1 .venv/bin/pytest -m integration -q

lint:
	.venv/bin/ruff check apps packages workers scripts tests
	npm run lint

typecheck:
	PYTHONPATH=$(PYTHONPATH) .venv/bin/mypy apps packages workers
	npm run typecheck

e2e:
	npm run e2e

backup:
	bash scripts/backup/backup.sh

restore:
	@test -n "$(BACKUP)" || (echo "Use: make restore BACKUP=/absolute/backup.tar.gz"; exit 2)
	bash scripts/restore/restore.sh "$(BACKUP)"

