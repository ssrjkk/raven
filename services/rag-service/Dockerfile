FROM python:3.14-alpine AS builder
RUN pip install --no-cache-dir fastapi uvicorn[standard] httpx

FROM python:3.14-alpine
WORKDIR /app
COPY --from=builder /usr/local/lib/python3.14/site-packages /usr/local/lib/python3.14/site-packages
COPY services/rag-service/ .
RUN apk add --no-cache curl
EXPOSE 8004
HEALTHCHECK --interval=10s --timeout=3s --retries=3 CMD curl -f http://localhost:8004/health || exit 1
CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8004"]
