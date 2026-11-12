FROM ghcr.io/astral-sh/uv:0.6.3 AS uv
FROM python:3.12.8-slim AS base
# Poppler rasterizes PDF pages; Tesseract performs local Russian/English OCR.
RUN apt-get update && apt-get install -y --no-install-recommends \
    poppler-utils tesseract-ocr tesseract-ocr-rus tesseract-ocr-eng libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*
FROM base AS builder
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
# Keep large CPU OCR wheels cached independently of source changes.
COPY pyproject.toml uv.lock ./
COPY scripts/prefetch_ocr_wheels.py /tmp/prefetch_ocr_wheels.py
RUN --mount=type=cache,target=/root/.cache/uv --mount=type=cache,target=/root/.cache/ocr-wheels \
    python /tmp/prefetch_ocr_wheels.py \
    && uv sync --frozen --no-dev --no-install-package paddlepaddle --no-install-package opencv-contrib-python \
    && uv pip install --no-deps --no-index --find-links /root/.cache/ocr-wheels paddlepaddle==3.2.2 opencv-contrib-python==4.10.0.84 \
    && uv sync --frozen --no-dev
COPY . .
FROM builder AS checks
RUN uv sync --frozen
COPY . .
ENV PYTHONPATH=/app/src
CMD ["sh", "-c", "uv run --frozen ruff check . && uv run --frozen ruff format --check . && uv run --frozen mypy src && uv run --frozen pytest"]
FROM base AS runtime
RUN useradd --create-home app
WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY src src
COPY migrations migrations
COPY alembic.ini .
ENV OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1
ENV PATH="/app/.venv/bin:$PATH" PYTHONPATH=/app/src PYTHONUNBUFFERED=1
USER app
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
