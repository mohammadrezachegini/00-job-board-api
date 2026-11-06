# ---------- builder: production dependencies ----------
FROM python:3.12-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:0.13.0 /uv /bin/uv

ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --locked --no-dev --no-install-project

# ---------- builder-test: production + dev dependencies ----------
FROM builder AS builder-test
RUN uv sync --locked --no-install-project

# ---------- base: shared by test and runtime ----------
FROM python:3.12-slim AS base

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN useradd --uid 1000 --no-create-home --shell /usr/sbin/nologin app
WORKDIR /app

# ---------- test: runs pytest (never deployed) ----------
FROM base AS test
COPY --from=builder-test /opt/venv /opt/venv
COPY . .
USER app
CMD ["pytest"]

# ---------- runtime: the production image (last stage = default target) ----------
FROM base AS runtime
COPY --from=builder /opt/venv /opt/venv
COPY . .
USER app
EXPOSE 8006
CMD ["gunicorn", "config.wsgi:application", "--config", "gunicorn.conf.py"]