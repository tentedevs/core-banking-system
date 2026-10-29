.PHONY: env-init format-check install dev up down db-config db-prerequisites db-up db-down db-restart db-status db-logs db-ready db-check db-shell db-test db-check-sqlalchemy db-init db-migrate db-current db-history lint format typecheck test test-verbose test-integration check

DB_PROJECT := core-banking-db
DB_ENV ?= $(CURDIR)/database/.env
DB_COMPOSE = docker compose --project-name "$(DB_PROJECT)" --project-directory "$(CURDIR)/database" --env-file "$(DB_ENV)" -f "$(CURDIR)/database/compose.yml"

install:
	uv sync --locked

dev: install
	uv run --locked uvicorn api.main:app --app-dir src --port 8001 --reload --reload-dir src

up:
	docker compose up --build -d

down:
	docker compose down

db-config:
	@command -v docker >/dev/null 2>&1 || { printf '%s\n' 'Docker no está instalado. Instala Docker con Compose v2.' >&2; exit 1; }
	@docker compose version >/dev/null 2>&1 || { printf '%s\n' 'Docker Compose v2 no está disponible.' >&2; exit 1; }
	@test -f "$(DB_ENV)" || { printf '%s\n' 'Falta $(DB_ENV). Ejecuta: cp database/.env.example database/.env' >&2; exit 1; }
	@$(DB_COMPOSE) config --quiet
	@printf '%s\n' 'Configuración PostgreSQL válida (credenciales ocultas).'

db-prerequisites: db-config
	@docker info >/dev/null 2>&1 || { printf '%s\n' 'Docker no está disponible. Arranca Docker Desktop o el daemon configurado.' >&2; exit 1; }

db-up: db-prerequisites
	@$(DB_COMPOSE) up -d --wait --wait-timeout 120 postgres || { printf '%s\n' 'No se pudo iniciar PostgreSQL. Revisa POSTGRES_PORT y ejecuta make db-logs.' >&2; exit 1; }

db-down: db-prerequisites
	$(DB_COMPOSE) stop postgres

db-restart: db-prerequisites
	$(DB_COMPOSE) up -d --wait --wait-timeout 120 postgres
	$(DB_COMPOSE) restart postgres
	$(DB_COMPOSE) up -d --wait --wait-timeout 120 postgres

db-status: db-prerequisites
	$(DB_COMPOSE) ps -a postgres

db-logs: db-prerequisites
	$(DB_COMPOSE) logs --tail 100 --follow postgres

db-ready: db-prerequisites
	@$(DB_COMPOSE) exec -T postgres sh -c 'exec pg_isready -h 127.0.0.1 -p 5432 -U "$$POSTGRES_USER" -d "$$POSTGRES_DB"' || { printf '%s\n' 'PostgreSQL no está disponible. Ejecuta make db-up y revisa make db-status.' >&2; exit 1; }

db-check: db-ready
	$(MAKE) db-check-sqlalchemy

db-init: db-ready
	PYTHONPATH=src uv run --locked python -m infrastructure.persistence.migrate init

db-migrate:
	PYTHONPATH=src uv run --locked python -m infrastructure.persistence.migrate migrate

db-current:
	PYTHONPATH=src uv run --locked python -m infrastructure.persistence.migrate current

db-history:
	PYTHONPATH=src uv run --locked python -m infrastructure.persistence.migrate history

db-shell: db-prerequisites
	$(DB_COMPOSE) exec postgres sh -c 'exec psql -U "$$POSTGRES_USER" -d "$$POSTGRES_DB"'

db-test:
	sh database/test-service.sh

db-check-sqlalchemy:
	PYTHONPATH=src uv run --locked python -m infrastructure.persistence.check_db

lint:
	uv run ruff check .

format:
	uv run ruff format .

typecheck:
	uv run mypy src

test:
	uv run pytest tests/unit

test-verbose:
	uv run --locked pytest tests/unit -vv --capture=tee-sys --tb=long

test-integration:
	uv run --locked pytest tests/integration -m integration -ra

format-check:
	uv run --locked ruff format --check .

check: lint format-check typecheck test

env-init:
	@test -f .env || cp .env.example .env
	@test -f database/.env || cp database/.env.example database/.env

.PHONY: frontend-install frontend-dev frontend-typecheck frontend-lint frontend-test frontend-build

frontend-install:
	npm --prefix frontend ci

frontend-dev:
	npm --prefix frontend run dev

frontend-typecheck:
	npm --prefix frontend run typecheck

frontend-lint:
	npm --prefix frontend run lint

frontend-test:
	npm --prefix frontend test

frontend-build:
	npm --prefix frontend run build
