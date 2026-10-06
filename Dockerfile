# Multi-stage build:
#   base    - slim Python + runtime dependencies + application code
#   test    - base + dev dependencies + test suite  (docker build --target test)
#   runtime - what ships: no test tooling, non-root user, gunicorn  (default)

ARG PYTHON_VERSION=3.12

# ---------- base ----------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Unprivileged user; /app/data is the only path it can write to.
RUN groupadd --system --gid 10001 aceest \
 && useradd --system --uid 10001 --gid aceest --no-create-home aceest \
 && mkdir /app/data \
 && chown aceest:aceest /app/data

# Dependencies first so this layer is cached until requirements.txt changes.
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app.py .

# ---------- test ----------------------------------------------------------
FROM base AS test

COPY requirements-dev.txt pytest.ini .flake8 ./
RUN pip install -r requirements-dev.txt
COPY tests ./tests

USER aceest
CMD ["pytest", "-v", "-p", "no:cacheprovider"]

# ---------- runtime (default target) --------------------------------------
FROM base AS runtime

ENV ACEEST_DB=/app/data/aceest_fitness.db
USER aceest
EXPOSE 5000

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:5000/health', timeout=2).status == 200 else 1)"]

CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", "app:create_app()"]
