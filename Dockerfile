FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml README.md ./
COPY raven/ raven/

RUN pip install --no-cache-dir -e "."

EXPOSE 18888

VOLUME ["/app/data"]

ENV PYTHONUNBUFFERED=1

CMD ["raven", "start"]
