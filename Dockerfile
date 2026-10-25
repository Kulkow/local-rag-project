FROM ghcr.io/astral-sh/uv:0.6.3 AS uv
FROM python:3.12.8-slim AS builder
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY . .
# Generate the lock during bootstrap; make lock persists it for frozen builds.
RUN uv lock && uv sync --frozen --no-dev
FROM builder AS checks
RUN uv sync --frozen
COPY . .
ENV PYTHONPATH=/app/src
CMD ["sh", "-c", "uv run --frozen ruff check . && uv run --frozen ruff format --check . && uv run --frozen mypy src && uv run --frozen pytest"]
FROM python:3.12.8-slim AS runtime
RUN useradd --create-home app
WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY src src
COPY migrations migrations
COPY alembic.ini .
ENV PATH="/app/.venv/bin:$PATH" PYTHONPATH=/app/src PYTHONUNBUFFERED=1
USER app
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
