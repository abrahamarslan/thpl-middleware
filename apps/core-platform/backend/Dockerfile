# ==============================================================================
# Backend — production image (multi-stage, non-root, baked dependencies)
# ==============================================================================
# The previous "mounted-code + venv-in-volume" pattern is replaced: production
# runs a fully baked, immutable image. Development uses docker-compose.dev.yml
# to bind-mount source over /app and run uvicorn --reload on this same image.
# ==============================================================================

ARG PYTHON_VERSION=3.12

# ── Builder: install dependencies into an isolated venv ──────────────────────
FROM python:${PYTHON_VERSION}-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN python -m venv /opt/venv
COPY requirements.txt .
RUN /opt/venv/bin/pip install -r requirements.txt

# ── Runtime ───────────────────────────────────────────────────────────────────
FROM python:${PYTHON_VERSION}-slim

# curl is used by container healthchecks and the gotenberg healthcheck script
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY . .

RUN useradd --create-home --uid 1000 appuser \
    && mkdir -p /app/media \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# Production default; compose overrides for celery worker / beat / flower
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
