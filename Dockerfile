FROM python:3.12-slim AS builder

WORKDIR /app
COPY pyproject.toml .

RUN pip install --no-cache-dir hatchling && \
    pip install --no-cache-dir --prefix=/install .

FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /install /usr/local
COPY . .

RUN pip install --no-cache-dir -e . && \
    playwright install chromium --with-deps 2>/dev/null || true

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

EXPOSE 18888

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD raven status || exit 1

ENTRYPOINT ["raven"]
CMD ["start"]
