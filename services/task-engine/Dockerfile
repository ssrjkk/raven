FROM python:3.13-alpine3.20 AS builder
RUN apk add --no-cache gcc musl-dev
COPY services/observability_sdk/ /build/services/observability_sdk/
COPY services/task-engine/requirements.txt /build/
RUN pip install --no-cache-dir -r /build/requirements.txt && \
    pip install --no-cache-dir /build/services/observability_sdk && \
    pip install --no-cache-dir opentelemetry-sdk opentelemetry-api \
    opentelemetry-instrumentation-fastapi opentelemetry-exporter-otlp-proto-grpc

FROM python:3.13-alpine3.20
RUN addgroup -S raven && adduser -S -G raven -h /app raven && \
    apk add --no-cache curl ca-certificates
WORKDIR /app
COPY --from=builder /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages
COPY services/task-engine/ .
COPY services/observability_sdk/ /app/services/observability_sdk/
RUN chown -R raven:raven /app
ENV PYTHONPATH=/app/services \
    OTEL_SERVICE_NAME=task-engine \
    OTEL_TRACES_SAMPLER=parentbased_traceidratio \
    OTEL_TRACES_SAMPLER_ARG=0.1
EXPOSE 8005
HEALTHCHECK --interval=10s --timeout=3s --retries=3 \
    CMD curl -f http://localhost:8005/health || exit 1
USER raven
CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8005"]
