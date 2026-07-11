ARG RAVEN_VERSION=0.4.0

FROM python:3.13-slim@sha256:e3c825ce1ff0a6cf9c8f04bed269fa2844955bcc0da8e2f29ff65c21da6046f1 AS base
RUN apt-get update && apt-get install -y --no-install-recommends \
    libnss3 libatk-bridge2.0-0 libdrm2 libxkbcommon0 libgbm1 \
    libasound2 libxshmfence1 curl \
    && rm -rf /var/lib/apt/lists/*
RUN groupadd -r raven && useradd -r -g raven -d /app -s /sbin/nologin raven

FROM python:3.13-slim@sha256:e3c825ce1ff0a6cf9c8f04bed269fa2844955bcc0da8e2f29ff65c21da6046f1 AS builder
ARG RAVEN_VERSION
WORKDIR /build
COPY pyproject.toml README.md ./
RUN pip install --no-cache-dir build hatchling
COPY raven/ raven/
RUN python -m build --wheel
RUN pip install --no-cache-dir dist/*.whl && \
    playwright install chromium 2>/dev/null || true

FROM base
ARG RAVEN_VERSION
LABEL org.opencontainers.image.title="Raven AI" \
      org.opencontainers.image.description="Enterprise-grade personal AI assistant" \
      org.opencontainers.image.version=$RAVEN_VERSION \
      org.opencontainers.image.source="https://github.com/ssrjkk/raven" \
      org.opencontainers.image.licenses="MIT"

WORKDIR /app
COPY --from=builder /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages
COPY --from=builder /usr/local/bin/raven /usr/local/bin/raven
COPY workspace/ workspace/
COPY plugins/ plugins/

RUN mkdir -p /app/data /app/workspace && chown -R raven:raven /app/data /app/workspace && \
    chmod 755 /app/data /app/workspace

VOLUME ["/app/data", "/app/workspace"]

EXPOSE 18888

ENV PYTHONUNBUFFERED=1 \
    DB_PATH=/app/data/raven.db \
    LOG_FILE=/app/data/raven.log \
    WORKSPACE_PATH=/app/workspace \
    RAVEN_ENV=production

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:18888/api/health/ready || exit 1

USER raven
CMD ["raven", "start"]
