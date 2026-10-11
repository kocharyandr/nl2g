.PHONY: help venv install test run ollama-lora mlx-start mlx-stop mlx-status up down logs

help:
	@echo "install     — create .venv and install dependencies"
	@echo "test        — run the test suite"
	@echo "run         — run the service locally on :8500"
	@echo "ollama-lora — build the three LoRA role models in Ollama"
	@echo "mlx-start   — start the three LoRA role servers via MLX (8071/8072/8073)"
	@echo "mlx-status  — check whether the role servers answer"
	@echo "mlx-stop    — stop the role servers"
	@echo "up/down     — docker compose"

install:
	uv venv .venv --python 3.12
	uv pip install -r requirements.txt pytest pytest-asyncio

test:
	.venv/bin/python -m pytest tests/ -q

run:
	.venv/bin/python -m uvicorn main:app --host 0.0.0.0 --port 8500 --reload

ollama-lora:
	./scripts/setup_ollama_lora.sh

mlx-start:
	./scripts/run_mlx_servers.sh start

mlx-status:
	./scripts/run_mlx_servers.sh status

mlx-stop:
	./scripts/run_mlx_servers.sh stop

up:
	docker compose up --build -d

down:
	docker compose down

logs:
	docker compose logs -f
