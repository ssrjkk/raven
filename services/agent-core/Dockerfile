FROM python:3.14-alpine AS builder
WORKDIR /app
COPY services/agent-core/requirements.txt .
COPY services/observability_sdk/ /app/services/observability_sdk/
RUN pip install --no-cache-dir \
    fastapi uvicorn[standard] httpx nats-py loguru

FROM python:3.14-alpine
WORKDIR /app
COPY --from=builder /usr/local/lib/python3.14/site-packages /usr/local/lib/python3.14/site-packages
COPY services/agent-core/ .
COPY services/observability_sdk/ /app/services/observability_sdk/
EXPOSE 8002
CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8002"]
