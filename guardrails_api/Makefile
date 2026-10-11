.PHONY: help format lint up down logs restart clean tests bash create_migration

# PROFILE: gpu | cpu. Read from .env (PROFILE=...), fallback to gpu.
# Override on CLI: `make up PROFILE=cpu`.
PROFILE ?= $(shell grep -E '^PROFILE=' .env 2>/dev/null | tail -n1 | cut -d= -f2)
PROFILE := $(if $(strip $(PROFILE)),$(strip $(PROFILE)),gpu)
SERVICE := api-$(PROFILE)
COMPOSE := docker compose -f docker-compose.yml --profile $(PROFILE)

# Тег образа: имя:short_commit-profile (переопределяется через IMAGE_TAG= при вызове make)
IMAGE_NAME ?= guardrails_api
GIT_SHA := $(shell git rev-parse --short HEAD 2>/dev/null || echo "nogit")
IMAGE_TAG ?= $(IMAGE_NAME):$(GIT_SHA)-$(PROFILE)
export IMAGE_TAG

help: ## Показать справку по командам
	@echo "Доступные команды:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "Примеры использования:"
	@echo "  make up                # GPU-профиль (по умолчанию)"
	@echo "  make up PROFILE=cpu    # CPU-профиль (без nvidia-резервации)"

format: ## Форматировать код с помощью ruff
	uv run ruff format .

lint: ## Проверить код линтером
	uv run ruff check . --fix

up: ## Пересборка и запуск проекта (PROFILE=gpu|cpu)
	$(COMPOSE) --env-file .env up -d --build

down: ## Остановка контейнеров
	$(COMPOSE) down


clear: ## Удаление контейнера и volumes
	$(COMPOSE) down -v

logs: ## Просмотр логов
	$(COMPOSE) logs -f $(SERVICE)

restart: ## Перезапуск контейнера проекта
	$(COMPOSE) restart




# Скачать HF-модель в кеш (для offline-режима).
# Usage: make download-model MODEL=fastino/gliner2-base-v1
MODEL ?= fastino/gliner2-multi-v1
download-model: ## Скачать HF-модель в кеш через compose run (MODEL=org/repo)
	$(COMPOSE) run --rm -e HF_HUB_OFFLINE=0 $(SERVICE) \
		uv run python -c "from huggingface_hub import snapshot_download; snapshot_download('$(MODEL)')"

MESSAGE ?= $(filter-out $@,$(MAKECMDGOALS))

%:
	@:
