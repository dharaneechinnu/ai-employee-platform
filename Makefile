.DEFAULT_GOAL := help
COMPOSE := docker compose

help:  ## Show the available commands
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

up:  ## Start everything
	$(COMPOSE) up --build

down:  ## Stop everything
	$(COMPOSE) down

clean:  ## Stop everything and delete the database volume
	$(COMPOSE) down -v

logs:  ## Follow the logs
	$(COMPOSE) logs -f

migrate:  ## Apply migrations
	$(COMPOSE) run --rm migrate alembic upgrade head

migrate-down:  ## Roll back one migration
	$(COMPOSE) run --rm migrate alembic downgrade -1

revision:  ## Create a migration: make revision m="add users"
	$(COMPOSE) run --rm migrate alembic revision --autogenerate -m "$(m)"

test-db:  ## Create and migrate the separate test database
	-docker compose exec -T postgres psql -U app -d postgres -c 'CREATE DATABASE ai_employee_test OWNER app'
	cd backend && DATABASE_URL=postgresql+asyncpg://app:app@localhost:5433/ai_employee_test python -m alembic upgrade head

test: test-db  ## Run the test suite (never touches the dev database)
	cd backend && python -m pytest

cov:  ## Run tests with a coverage report
	cd backend && python -m pytest --cov=app --cov-report=term-missing

lint:  ## Run ruff and mypy
	cd backend && python -m ruff check . && python -m ruff format --check . && python -m mypy app

fix:  ## Auto-fix what ruff can
	cd backend && python -m ruff check --fix . && python -m ruff format .

check: lint test  ## Everything CI runs

.PHONY: help up down clean logs migrate migrate-down revision test-db test cov lint fix check
