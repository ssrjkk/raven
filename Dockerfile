ARG RAVEN_VERSION=0.4.8

# --- Web dashboard (React SPA) ---
FROM node:22-alpine AS web-builder
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY tsconfig.base.json /tsconfig.base.json
COPY web/ ./
RUN npm run build

# --- Python wheel ---
# Every directory in pyproject `[tool.hatch.build.targets.wheel] packages` must be copied:
# hatchling silently skips missing ones, so a partial context produces a partial wheel.
FROM python:3.14-slim AS wheel-builder
ARG RAVEN_VERSION
WORKDIR /build
COPY pyproject.toml README.md ./
COPY raven/ raven/
COPY aios/ aios/
COPY ravencode/ ravencode/
RUN pip install --no-cache-dir build \
    && python -m build --wheel

FROM python:3.14-slim AS base
# curl is for the healthcheck only. Chromium's shared libraries used to be installed here for
# the optional `browser` extra, which nothing in the image installs; add them back together
# with `pip install "raven-agent[browser]" && playwright install chromium` if that changes.
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*
RUN groupadd -r raven && useradd -r -g raven -d /app -s /sbin/nologin raven
RUN pip install --no-cache-dir --upgrade pip setuptools

FROM base
ARG RAVEN_VERSION
LABEL org.opencontainers.image.title="Raven AI" \
      org.opencontainers.image.description="Personal AI assistant: coding agent, workflow gateway and web dashboard" \
      org.opencontainers.image.version=$RAVEN_VERSION \
      org.opencontainers.image.authors="ssrjkk (https://github.com/ssrjkk)" \
      org.opencontainers.image.source="https://github.com/ssrjkk/raven" \
      org.opencontainers.image.licenses="MIT"

WORKDIR /app
COPY --from=wheel-builder /build/dist/*.whl /tmp/
RUN pip install --no-cache-dir /tmp/*.whl && rm -f /tmp/*.whl
COPY workspace/ workspace/
COPY plugins/ plugins/
COPY --from=web-builder /web/dist /app/web/dist

RUN mkdir -p /app/data /app/workspace && chown -R raven:raven /app/data /app/workspace && \
    chmod 755 /app/data /app/workspace

VOLUME ["/app/data", "/app/workspace"]

EXPOSE 18888

ENV PYTHONUNBUFFERED=1 \
    DB_PATH=/app/data/raven.db \
    LOG_FILE=/app/data/raven.log \
    WORKSPACE_PATH=/app/workspace \
    RAVEN_WEB_DIST=/app/web/dist \
    RAVEN_ENV=production

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:18888/api/health/ready || exit 1

USER raven
CMD ["raven", "start"]
