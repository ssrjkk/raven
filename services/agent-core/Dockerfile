FROM python:3.13-alpine3.20 AS builder
WORKDIR /build
RUN apk add --no-cache gcc musl-dev linux-headers
COPY services/observability_sdk/ /build/services/observability_sdk/
COPY services/agent-core/requirements.txt /build/
RUN pip install --no-cache-dir -r /build/requirements.txt && \
    pip install --no-cache-dir /build/services/observability_sdk && \
    pip install --no-cache-dir opentelemetry-sdk opentelemetry-api opentelemetry-instrumentation-fastapi \
    opentelemetry-exporter-otlp-proto-grpc opentelemetry-instrumentation-httpx

FROM python:3.13-alpine3.20
RUN addgroup -S raven && adduser -S -G raven -h /app raven && \
    apk add --no-cache curl ca-certificates
WORKDIR /app
COPY --from=builder /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages
COPY services/agent-core/ .
COPY services/observability_sdk/ /app/services/observability_sdk/
RUN chown -R raven:raven /app
ENV PYTHONPATH=/app/services \
    OTEL_SERVICE_NAME=agent-core \
    OTEL_TRACES_SAMPLER=parentbased_traceidratio \
    OTEL_TRACES_SAMPLER_ARG=0.1
EXPOSE 8002
HEALTHCHECK --interval=10s --timeout=3s --retries=3 \
    CMD curl -f http://localhost:8002/health || exit 1
USER raven
CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8002"]
