.PHONY: up down migrate check smoke models lock lint-python
up:
	docker compose up -d --build
migrate:
	docker compose run --rm migrate
down:
	docker compose down
check:
	docker compose --profile tools run --build --rm checks
	docker compose --profile tools run --rm -v "$(CURDIR)/web-admin:/app/web-admin" checks python scripts/export_openapi.py
	docker compose --profile tools run --build --rm web-checks
smoke:
	docker compose exec -T api python -m app.smoke
models:
	ollama list

lock:
	docker run --rm -v "$(CURDIR):/app" -w /app ghcr.io/astral-sh/uv:0.6.3-python3.12-bookworm uv lock
	docker run --rm -v "$(CURDIR)/web-admin:/app" -w /app node:22.13.0-alpine npm install --package-lock-only --ignore-scripts

lint-python:
	docker compose --profile tools run --build --rm --no-deps checks uv run --frozen ruff check src migrations scripts tests
