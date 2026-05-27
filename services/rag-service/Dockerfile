FROM python:3.14-alpine AS builder
RUN pip install --no-cache-dir fastapi uvicorn[standard] httpx

FROM python:3.14-alpine
WORKDIR /app
COPY --from=builder /usr/local/lib/python3.14/site-packages /usr/local/lib/python3.14/site-packages
COPY services/rag-service/ .
EXPOSE 8004
CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8004"]
