# syntax=docker/dockerfile:1
#
# One image serving both halves: the React build and the API that serves it.
#
# Two services would mean two free-tier instances, two cold starts, and a CORS
# allowlist that has to be updated whenever either URL changes. One origin
# means the browser sees no cross-origin request at all -- the same thing the
# Vite dev proxy arranges locally, so development and production agree.

# --- stage 1: build the web app --------------------------------------------
# Node is needed to produce web/dist and for nothing afterwards. Building it in
# a stage that is thrown away keeps npm, node_modules and the toolchain out of
# the shipped image.
FROM node:22-alpine AS web

WORKDIR /web

# Dependencies first, so a change to application code does not re-run npm ci.
COPY web/package.json web/package-lock.json ./
RUN npm ci

COPY web/ ./

# The API is served from this same origin, so requests go to /login rather
# than /api/login. That /api prefix exists only for local development, where
# Vite's dev proxy catches it and forwards to a separate port -- a convenience
# that quietly makes development and production disagree about URLs.
#
# Without this, every request 404s, and a POST lands on the SPA catch-all
# (which is GET-only) for a "Method Not Allowed" that says nothing about the
# actual cause.
#
# Written as .env.production rather than passed as a shell variable because
# Vite loads that file for production builds regardless of how the build is
# invoked.
RUN echo "VITE_API_URL=" > .env.production \
    && npm run build


# --- stage 2: the service ---------------------------------------------------
FROM python:3.14-slim AS app

# uv is copied from its own published image rather than pip-installed, which
# is both faster and version-pinned by the tag.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# libpq for psycopg. Present even when psycopg[binary] bundles its own, because
# the failure when it is missing -- an ImportError at startup, after a
# successful build -- is not worth the few megabytes saved.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 \
    && rm -rf /var/lib/apt/lists/*

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# The project's virtualenv first on PATH, so the entrypoint runs the binaries
# already installed in this image instead of going through `uv run`.
#
# `uv run` re-resolves the environment on every start and downloads what it
# thinks is missing -- which turned each container start into a network-
# dependent install of dbt, psycopg2 and fifty other packages, while the
# platform's health check was already counting down. The image had them all
# along; it simply was not using them.
ENV PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# Dependencies as their own layer, installed from the lockfile without the
# project itself. Application code changes on every deploy; the dependency set
# rarely does, and this is what keeps a redeploy to seconds.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src/ src/
COPY migrations/ migrations/
# README.md is not documentation here: pyproject.toml declares it as the
# project's readme, so the build backend opens it while installing the package.
# Without it this layer fails with "failed to open file /app/README.md", which
# reads like a missing doc and is actually a missing build input.
COPY alembic.ini load_prices.py README.md ./
COPY pipelines/dags/lib/ pipelines/dags/lib/
RUN uv sync --frozen --no-dev

# Where main.py looks for the built frontend: REPO_ROOT / "web" / "dist".
COPY --from=web /web/dist web/dist

# Not root. A web-facing process has no reason to be able to write to its own
# code, and this is the cheapest possible mitigation for a whole class of
# problems.
RUN useradd --create-home --uid 10001 app \
    && chown -R app:app /app
USER app

EXPOSE 8000

# Migrations run before the server starts, so a deploy that changes the schema
# cannot serve traffic against the old one.
#
# This is safe here because the free plan runs a single instance. With several,
# they would race to migrate, and the right shape is a separate pre-deploy job
# that runs once.
#
# $PORT is assigned by the platform; the default is for running this image
# locally.
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn dispatchledger.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
