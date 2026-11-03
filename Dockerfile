# =============================================================================
# TaarYa — Multi-stage production Dockerfile
# =============================================================================
# Stage 1 (builder): compile heavy dependencies (astropy, sentence-transformers)
# Stage 2 (runtime): slim production image
# =============================================================================

# ── Stage 1: Builder ──────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /build

# Install build dependencies
RUN apt-get update && apt-get install --no-install-recommends -y \
        gcc \
        g++ \
        libpq-dev \
        cmake \
        pkg-config \
    && rm -rf /var/lib/apt/lists/*

# Install uv for fast dependency management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Explicitly use CPU-only index for PyTorch and others to avoid CUDA bloat
ENV UV_EXTRA_INDEX_URL=https://download.pytorch.org/whl/cpu
ENV UV_INDEX_STRATEGY=unsafe-best-match

# 1. Install heavy dependencies first (cached if pyproject.toml doesn't change)
COPY pyproject.toml ./
RUN uv pip install --system --no-cache \
        "numpy>=1.26.3" \
        "scipy>=1.11.0" \
        "torch>=2.0.0" \
        "sentence-transformers>=3.0.0"

# 2. Copy source and install the project normally.
# Do not use an editable install here: the runtime image does not contain
# the builder path, and editable metadata can leave imports pointing at /build.
COPY . .
RUN uv pip install --system --no-cache .

# ── Stage 2: Runtime ──────────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

LABEL maintainer="Amit Kumar <amit.kumar@inst.edu.in>"
LABEL description="TaarYa — Hybrid Retrieval Extension for Cross-Catalog Astronomical Discovery Support"
LABEL homepage="https://github.com/HmbleCreator/TaarYa"
LABEL version="1.0.0"

# Non-root user for security
RUN groupadd --gid 1000 taarya \
    && useradd --uid 1000 --gid taarya --shell /bin/bash --create-home taarya

WORKDIR /app

# Install runtime dependencies only (no compiler needed)
RUN apt-get update && apt-get install --no-install-recommends -y \
        libpq5 \
        libgomp1 \
        libfreetype6 \
        libjpeg62-turbo \
        fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

# Copy pre-built site-packages from builder
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application source from builder so `PYTHONPATH=/app` also works for
# direct module execution and local debugging inside the container.
COPY --from=builder /build/src /app/src

# Copy static files (required for web UI)
COPY static/ /app/static/

# Copy config templates
COPY .env.example /app/.env.example

# Pre-create data directory
RUN mkdir -p /app/data && chown taarya:taarya /app/data

# Switch to non-root user
USER taarya

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD python -c "import httpx; r=httpx.get('http://localhost:8000/health', timeout=5); assert r.status_code==200" \
    || exit 1

# Default: start the API server
EXPOSE 8000

ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

CMD ["python", "-m", "uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
