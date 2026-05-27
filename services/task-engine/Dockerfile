FROM python:3.14-slim AS builder
WORKDIR /app
RUN pip install --no-cache-dir grpcio-tools
COPY services/proto /app/services/proto
RUN python -m grpc_tools.protoc -I/services/proto \
  --python_out=/app --grpc_python_out=/app \
  /app/services/proto/task/v1/task.proto \
  /app/services/proto/agent/v1/agent.proto

FROM python:3.14-slim
WORKDIR /app
RUN pip install --no-cache-dir fastapi uvicorn[standard] pydantic>=2 aiosqlite \
  grpcio opentelemetry-api opentelemetry-sdk \
  nats-py httpx loguru
COPY --from=builder /app /app
COPY services/task-engine/ /app/services/task-engine/
COPY services/observability_sdk/ /app/services/observability_sdk/
ENV PYTHONPATH=/app
EXPOSE 8005
CMD ["uvicorn", "services.task-engine.main:app", "--host", "0.0.0.0", "--port", "8005"]
