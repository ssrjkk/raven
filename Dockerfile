FROM python:3.14-slim AS base
RUN apt-get update && apt-get install -y --no-install-recommends \
    libnss3 libatk-bridge2.0-0 libdrm2 libxkbcommon0 libgbm1 \
    libasound2 libxshmfence1 curl \
    && rm -rf /var/lib/apt/lists/*
RUN groupadd -r raven && useradd -r -g raven -d /app -s /sbin/nologin raven

FROM python:3.14-slim AS builder
WORKDIR /build
COPY pyproject.toml README.md ./
RUN pip install --no-cache-dir build hatchling
COPY raven/ raven/
RUN python -m build --wheel
RUN pip install --no-cache-dir dist/*.whl && \
    playwright install chromium 2>/dev/null || true

FROM base
WORKDIR /app
COPY --from=builder /usr/local/lib/python3.14/site-packages /usr/local/lib/python3.14/site-packages
COPY --from=builder /usr/local/bin/raven /usr/local/bin/raven
COPY workspace/ workspace/
COPY plugins/ plugins/

RUN mkdir -p /app/data && chown -R raven:raven /app/data /app/workspace

VOLUME ["/app/data", "/app/workspace"]

EXPOSE 18888

ENV PYTHONUNBUFFERED=1 \
    DB_PATH=/app/data/raven.db \
    LOG_FILE=/app/data/raven.log \
    WORKSPACE_PATH=/app/workspace

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:18888/api/health/ready || exit 1

USER raven
CMD ["raven", "start"]
