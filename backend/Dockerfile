# syntax=docker/dockerfile:1
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH=/opt/venv/bin:$PATH

COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /bin/uv

WORKDIR /app

# Dependency layer — cached unless the lockfile changes.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# Drop root. The api container takes uploaded photos from the internet and hands them to an
# image decoder, which is the one place in this app where hostile bytes meet a C library —
# so it should not be running as uid 0 when that goes wrong.
#
# The uid is pinned because it outlives the image: Docker seeds a NEW named volume from the
# image's ownership at that path, so creating /data/media here is what makes a fresh
# deployment's media volume writable. An EXISTING volume keeps the ownership it already has
# — see docs/deploy-dockhand.md for the one-time chown that a stack built before this needs.
RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin app \
    && mkdir -p /data/media \
    && chown -R app:app /data/media /app
USER app

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
