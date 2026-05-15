FROM python:3.12-slim AS builder

WORKDIR /build
COPY pyproject.toml README.md ./
COPY raven/ raven/
RUN pip install --no-cache-dir build && python -m build --wheel

FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    libnss3 libatk-bridge2.0-0 libdrm2 libxkbcommon0 libgbm1 \
    libasound2 libxshmfence1 curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin/raven /usr/local/bin/raven

COPY workspace/ workspace/
COPY plugins/ plugins/

RUN playwright install chromium 2>/dev/null || true

RUN mkdir -p /app/data
VOLUME ["/app/data", "/app/workspace"]

EXPOSE 18888

ENV PYTHONUNBUFFERED=1
ENV DB_PATH=/app/data/raven.db
ENV LOG_FILE=/app/data/raven.log
ENV WORKSPACE_PATH=/app/workspace

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:18888/api/health/ready || exit 1

USER nobody
CMD ["raven", "start"]
