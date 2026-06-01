FROM python:3.14-alpine AS builder
WORKDIR /app
RUN pip install --no-cache-dir fastapi uvicorn[standard]
COPY services/observability_sdk/ /app/services/observability_sdk/
RUN pip install --no-cache-dir /app/services/observability_sdk

FROM python:3.14-alpine
WORKDIR /app
COPY --from=builder /usr/local/lib/python3.14/site-packages /usr/local/lib/python3.14/site-packages
COPY services/task-engine/ .
COPY services/observability_sdk/ /app/services/observability_sdk/
RUN apk add --no-cache curl
ENV PYTHONPATH=/app/services
EXPOSE 8005
HEALTHCHECK --interval=10s --timeout=3s --retries=3 CMD curl -f http://localhost:8005/health || exit 1
CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8005"]
