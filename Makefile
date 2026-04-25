.PHONY: run lint fix format check install up down logs

# Local development
run:
	USE_POLLING=1 PYTHONPATH=src uv run uvicorn bot.main:app --host 0.0.0.0 --port 8000 --reload

install:
	uv sync

# Linting & formatting
lint:
	uv run ruff check src/

fix:
	uv run ruff check src/ --fix
	uv run ruff format src/

format:
	uv run ruff format src/

check:
	uv run ruff check src/
	uv run ruff format --check src/

# Docker
up:
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs bot -f --tail 100
