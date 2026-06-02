FROM python:3.11-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libffi-dev \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /app
COPY backend/requirements.txt /tmp/requirements.txt
RUN pip install --upgrade pip setuptools wheel \
    && pip install -r /tmp/requirements.txt

FROM python:3.11-slim AS runtime

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    libffi8 \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app/backend

COPY --from=builder /opt/venv /opt/venv
COPY backend/ .

RUN chmod +x /app/backend/docker-entrypoint.sh \
    && mkdir -p /app/backend/data

EXPOSE 8000

ENTRYPOINT ["/app/backend/docker-entrypoint.sh"]

# Gunicorn + Uvicorn workers, tuned for long OCR/form-filling requests.
CMD ["gunicorn", "app.main:app", "-k", "uvicorn.workers.UvicornWorker", "--bind", "0.0.0.0:8000", "--timeout", "300", "--graceful-timeout", "300", "--keep-alive", "65", "--proxy-protocol", "--forwarded-allow-ips=*"]
