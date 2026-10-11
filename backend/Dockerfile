# syntax=docker/dockerfile:1

# --- Build: install the locked dependencies into /app/.venv with uv ----------------------------
FROM python:3.14.8-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:0.12.23 /uv /bin/uv

# Byte-compile for faster startup; copy (not hardlink) from the cache mount; use the image's
# Python instead of downloading one.
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-dev --no-install-project

# --- Runtime: slim image, non-root user, no build tools ------------------------------------------
FROM python:3.14.8-slim

# UID/GID 1000 match the usual first user on Linux/WSL, so the bind-mounted ./data directory is
# writable by the container and its files stay editable on the host.
ARG APP_UID=1000
ARG APP_GID=1000
RUN groupadd --gid "${APP_GID}" app \
    && useradd --uid "${APP_UID}" --gid app --home-dir /app --no-create-home --shell /usr/sbin/nologin app \
    && mkdir /data \
    && chown app:app /data

WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY alembic.ini ./
COPY app ./app

ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    APP_ENV=production \
    DATA_DIR=/data

USER app
EXPOSE 8000

# One worker on purpose: SQLite, a single local user, and in-process state (YouTube quota
# pause, Spotify token) that must not be split across processes.
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--forwarded-allow-ips", "*"]
