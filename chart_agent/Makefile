PYTHON ?= conda run --no-capture-output -n my_env python
COMPOSE ?= docker compose

.PHONY: help install install-dev install-all format lint typecheck unit test docker-build docker-up docker-down docker-logs run

help:
	@echo "Available targets:"
	@echo "  install      Install runtime dependencies"
	@echo "  install-dev  Install dev dependencies"
	@echo "  install-all  Install runtime + dev dependencies"
	@echo "  format       Auto-fix code style (ruff --fix + format)"
	@echo "  lint         Run linter"
	@echo "  typecheck    Run mypy checker"
	@echo "  unit         Run unit tests"
	@echo "  test         Run lint + typecheck + unit tests"
	@echo "  run          Run FastAPI locally"
	@echo "  docker-build Build Docker image"
	@echo "  docker-up    Auto-fix code, then start Docker"
	@echo "  docker-down  Stop Docker"
	@echo "  docker-logs  Show Docker logs"

install:
	$(PYTHON) -m pip install -r requirements.txt

install-dev:
	$(PYTHON) -m pip install -r requirements-dev.txt

install-all: install install-dev

format:
	$(PYTHON) -m ruff check --fix app tests
	$(PYTHON) -m ruff format app tests

lint:
	$(PYTHON) -m ruff check app tests

typecheck:
	$(PYTHON) -m mypy app tests

unit:
	$(PYTHON) -m pytest

test: lint typecheck unit

run:
	$(PYTHON) -m uvicorn app.main:app --host 0.0.0.0 --port 9911 --reload --env-file .env

docker-build:
	$(COMPOSE) build

docker-up: format
	$(COMPOSE) up --build

docker-down:
	$(COMPOSE) down

docker-logs:
	$(COMPOSE) logs -f
